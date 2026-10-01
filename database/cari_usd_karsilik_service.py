"""TL cari hareketlerin işlem tarihindeki USD karşılığı (yalnız raporlama).

Kural: USD karşılık = TL tutar / işlem tarihindeki USD döviz satış (forex_selling) kuru.
- İşlem günü kur yoksa (tatil / henüz yayımlanmamış) en son yayımlanmış ÖNCEKİ kur kullanılır;
  sonraki tarihin kuru asla kullanılmaz. Kur tarihi işlem tarihinden ayrı saklanır.
- Kur bulunamazsa kayıt EKSIK olur; bugünün kuru veya 1 varsayılmaz.
- TL borç/alacak, evrak, kapatma ve dövizli evrak kuru bu modülden etkilenmez.
- Kur, hareket kaydedilirken yerel kur tablosundan bulunur; rapor açılırken internete çıkılmaz.
"""

from __future__ import annotations

import logging
import weakref
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete, event, insert, inspect as sa_inspect, select, update
from sqlalchemy.orm import Session

from database.database import get_session
from database.models.cari import CariIslem, CariUsdKarsilik, SatisHareketi
from database.models.doviz import DovizKuru

logger = logging.getLogger("cari_usd_karsilik")

KURUS = Decimal("0.01")
KUR_TURU = "forex_selling"
GERI_GUN = 14
KAYNAK_ISLEM = "CARI_ISLEM"
KAYNAK_HAREKET = "SATIS_HAREKETI"
DURUM_TAMAM = "TAMAM"
DURUM_EKSIK = "EKSIK"
DURUM_UYUSMAZ = "UYUSMAZ"

FARK_ACIKLAMASI = (
    "Tarihsel USD karşılık farkı: TL işlemlerin farklı tarihlerdeki kurlarla USD'ye "
    "çevrilmesinden doğan bilgi amaçlı farktır. Gerçek bir USD borç veya alacak değildir; "
    "kur farkı evrakı, borç veya alacak oluşturmaz."
)

_HAZIR_ENGINELER: "weakref.WeakSet" = weakref.WeakSet()


def _d(deger) -> Decimal:
    if deger is None:
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def usd_hesapla(tl_tutar, kur) -> Decimal:
    kur = _d(kur)
    if kur <= 0:
        raise ValueError("USD kuru sıfırdan büyük olmalıdır.")
    return (_d(tl_tutar) / kur).quantize(KURUS, rounding=ROUND_HALF_UP)


def manuel_kur_dogrula(deger) -> Decimal:
    """Manuel kur metni/değeri → Decimal; sıfır ve negatif kur engellenir."""
    if isinstance(deger, str):
        deger = deger.strip().replace(" ", "")
        if "," in deger:
            deger = deger.replace(".", "").replace(",", ".")
    try:
        kur = Decimal(str(deger))
    except (InvalidOperation, ValueError, TypeError) as hata:
        raise ValueError("Geçerli bir USD kuru girin.") from hata
    if kur <= 0:
        raise ValueError("USD kuru sıfır veya negatif olamaz.")
    return kur.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- tablo


def tablo_hazirla(bind) -> None:
    """Mevcut firma veritabanlarında tabloyu oluşturur (yoksa)."""
    engine = getattr(bind, "engine", bind)
    if engine is None:
        return
    try:
        if engine in _HAZIR_ENGINELER:
            return
    except TypeError:
        pass
    CariUsdKarsilik.__table__.create(bind=bind, checkfirst=True)
    try:
        _HAZIR_ENGINELER.add(engine)
    except TypeError:
        pass


# ---------------------------------------------------------------- kur bulma


def _kur_satirlari(session, tarih: date) -> list[DovizKuru]:
    return list(
        session.scalars(
            select(DovizKuru)
            .where(
                DovizKuru.currency_code == "USD",
                DovizKuru.rate_date <= tarih,
                DovizKuru.rate_date >= tarih - timedelta(days=GERI_GUN),
                DovizKuru.forex_selling > 0,
            )
            .order_by(DovizKuru.rate_date.desc())
        ).all()
    )


def rapor_kuru_bul(session, tarih: date) -> dict[str, Any] | None:
    """İşlem tarihi için yerel kur tablosundan USD döviz satış kuru.

    TCMB'den gelen ve hedef güne kopyalanmış kayıtlarda (aynı alış/satış değerleri) gerçek
    yayın tarihi geriye doğru izlenir; böylece kur tarihi işlem tarihinden ayrı görünür.
    """
    satirlar = _kur_satirlari(session, tarih)
    if not satirlar:
        return None
    ilk = satirlar[0]
    kur = _d(ilk.forex_selling)
    if kur <= 0:
        return None
    kur_tarihi = ilk.rate_date
    kaynak = "TCMB" if (ilk.source or "").upper() == "TCMB" else "MANUEL"
    if kaynak == "TCMB":
        for onceki in satirlar[1:]:
            if (onceki.source or "").upper() != "TCMB":
                break
            if _d(onceki.forex_selling) == kur and _d(onceki.forex_buying) == _d(ilk.forex_buying):
                kur_tarihi = onceki.rate_date
                continue
            break
    return {"kur": kur, "kur_tarihi": kur_tarihi, "kaynak": kaynak, "kur_turu": KUR_TURU}


# ---------------------------------------------------------------- otomatik kayıt


def _satir_bilgisi(obj) -> tuple[str, int, int, str, date, Decimal, Decimal]:
    if isinstance(obj, CariIslem):
        return (
            KAYNAK_ISLEM, int(obj.id), int(obj.cari_id), obj.belge_no or "", obj.tarih,
            _kurus(obj.borc), _kurus(obj.alacak),
        )
    return (
        KAYNAK_HAREKET, int(obj.id), int(obj.cari_id), obj.belge_no or "", obj.satis_tarihi,
        _kurus(obj.satis_tutari), Decimal("0.00"),
    )


def _degerler(
    session, *, kaynak, kaynak_id, cari_id, belge_no, tarih, borc, alacak, mevcut=None
) -> dict[str, Any]:
    """Kayıt değerleri: tarih değişmediyse saklı kur korunur, değiştiyse yeniden bulunur."""
    kur_bilgi = None
    if (
        mevcut is not None
        and mevcut.get("usd_kur")
        and mevcut.get("islem_tarihi") == tarih
        and _d(mevcut.get("usd_kur")) > 0
    ):
        kur_bilgi = {
            "kur": _d(mevcut["usd_kur"]),
            "kur_tarihi": mevcut.get("kur_tarihi"),
            "kaynak": mevcut.get("kur_kaynagi"),
        }
    elif tarih is not None:
        kur_bilgi = rapor_kuru_bul(session, tarih)
    deger = {
        "kaynak": kaynak,
        "kaynak_id": kaynak_id,
        "cari_id": cari_id,
        "belge_no": belge_no[:50] if belge_no else None,
        "islem_tarihi": tarih,
        "tl_borc": borc,
        "tl_alacak": alacak,
        "kur_turu": KUR_TURU,
        "guncelleme": datetime.now(),
    }
    if kur_bilgi:
        deger.update(
            usd_kur=kur_bilgi["kur"],
            kur_tarihi=kur_bilgi["kur_tarihi"],
            kur_kaynagi=kur_bilgi["kaynak"],
            usd_borc=usd_hesapla(borc, kur_bilgi["kur"]),
            usd_alacak=usd_hesapla(alacak, kur_bilgi["kur"]),
            durum=DURUM_TAMAM,
        )
    else:
        deger.update(
            usd_kur=None, kur_tarihi=None, kur_kaynagi=None,
            usd_borc=None, usd_alacak=None, durum=DURUM_EKSIK,
        )
    return deger


def _mevcut_kayit(conn, kaynak: str, kaynak_id: int) -> dict[str, Any] | None:
    t = CariUsdKarsilik.__table__
    satir = conn.execute(
        select(t).where(t.c.kaynak == kaynak, t.c.kaynak_id == kaynak_id)
    ).mappings().first()
    return dict(satir) if satir else None


def _kaydet(conn, deger: dict[str, Any], mevcut: dict[str, Any] | None) -> None:
    t = CariUsdKarsilik.__table__
    if mevcut is None:
        conn.execute(insert(t).values(**deger))
    else:
        conn.execute(update(t).where(t.c.id == mevcut["id"]).values(**deger))


_ILGILI_ALANLAR = {
    CariIslem: ("tarih", "borc", "alacak", "cari_id", "belge_no"),
    SatisHareketi: ("satis_tarihi", "satis_tutari", "cari_id", "belge_no"),
}


def _degisti_mi(obj) -> bool:
    durum = sa_inspect(obj)
    for alan in _ILGILI_ALANLAR[type(obj)]:
        if durum.attrs[alan].history.has_changes():
            return True
    return False


def _after_flush(session: Session, _flush_context) -> None:
    yeni = [o for o in session.new if type(o) in _ILGILI_ALANLAR]
    kirli = [o for o in session.dirty if type(o) in _ILGILI_ALANLAR]
    silinen = [o for o in session.deleted if type(o) in _ILGILI_ALANLAR]
    if not (yeni or kirli or silinen):
        return
    try:
        conn = session.connection()
        tablo_hazirla(conn)
        t = CariUsdKarsilik.__table__
        with session.no_autoflush:
            for obj in silinen:
                kaynak = KAYNAK_ISLEM if isinstance(obj, CariIslem) else KAYNAK_HAREKET
                if obj.id is not None:
                    conn.execute(delete(t).where(t.c.kaynak == kaynak, t.c.kaynak_id == int(obj.id)))
            for obj in yeni + [o for o in kirli if _degisti_mi(o)]:
                if obj.id is None:
                    continue
                kaynak, kid, cari_id, belge_no, tarih, borc, alacak = _satir_bilgisi(obj)
                mevcut = _mevcut_kayit(conn, kaynak, kid)
                deger = _degerler(
                    session, kaynak=kaynak, kaynak_id=kid, cari_id=cari_id, belge_no=belge_no,
                    tarih=tarih, borc=borc, alacak=alacak, mevcut=mevcut,
                )
                _kaydet(conn, deger, mevcut)
    except Exception:
        logger.exception("USD karşılık kaydı güncellenemedi (cari işlem etkilenmedi).")


if not event.contains(Session, "after_flush", _after_flush):
    event.listen(Session, "after_flush", _after_flush)


# ---------------------------------------------------------------- rapor


def _evrak_turu(session, h: SatisHareketi) -> str:
    try:
        from database.acik_kalem_service import AcikKalemService

        tur = AcikKalemService._evrak_turu(session, h)
        if tur:
            return str(tur)
    except Exception:
        pass
    return "Satış"


def _hareketleri_topla(session, cari_id: int) -> list[dict[str, Any]]:
    """cari_bakiye_service._kayitlari_topla ile aynı kaynak ve süzme (kimlik bilgisiyle)."""
    cid = int(cari_id)
    islemler = list(session.scalars(select(CariIslem).where(CariIslem.cari_id == cid)).all())
    hareketler = list(session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cid)).all())
    from database.cari_bakiye_service import _DEFTER_ATLA_ONEK

    islem_belgeleri = {(i.belge_no or "") for i in islemler}
    kayitlar: list[dict[str, Any]] = []
    for h in hareketler:
        bn = h.belge_no or ""
        if bn in islem_belgeleri or bn.startswith(_DEFTER_ATLA_ONEK):
            continue
        kayitlar.append({
            "kaynak": KAYNAK_HAREKET, "kaynak_id": int(h.id), "tarih": h.satis_tarihi,
            "belge_no": bn, "tur": _evrak_turu(session, h), "aciklama": "",
            "tl_borc": _kurus(h.satis_tutari), "tl_alacak": Decimal("0.00"),
        })
    for i in islemler:
        kayitlar.append({
            "kaynak": KAYNAK_ISLEM, "kaynak_id": int(i.id), "tarih": i.tarih,
            "belge_no": i.belge_no or "", "tur": i.islem_turu or "", "aciklama": i.aciklama or "",
            "tl_borc": _kurus(i.borc), "tl_alacak": _kurus(i.alacak),
        })
    kayitlar.sort(
        key=lambda x: (x["tarih"] or date.min, x["belge_no"] or "", str(x["tl_borc"]), str(x["tl_alacak"]))
    )
    return kayitlar


def _karsiliklari_eslestir(session, cari_id: int | None, kayitlar: list[dict[str, Any]]) -> None:
    stmt = select(CariUsdKarsilik)
    if cari_id is not None:
        stmt = stmt.where(CariUsdKarsilik.cari_id == int(cari_id))
    harita = {(k.kaynak, int(k.kaynak_id)): k for k in session.scalars(stmt).all()}
    for r in kayitlar:
        k = harita.get((r["kaynak"], r["kaynak_id"]))
        r.update(usd_kur=None, kur_tarihi=None, kur_kaynagi=None, usd_borc=None, usd_alacak=None,
                 onceki_gun_kuru=False, kayit_islem_tarihi=k.islem_tarihi if k is not None else None)
        if k is None or k.durum != DURUM_TAMAM or not k.usd_kur or _d(k.usd_kur) <= 0:
            r["durum"] = DURUM_EKSIK
            r["kayit_var"] = k is not None
            continue
        r["kayit_var"] = True
        r["usd_kur"] = _d(k.usd_kur)
        r["kur_tarihi"] = k.kur_tarihi
        r["kur_kaynagi"] = k.kur_kaynagi
        if (
            k.islem_tarihi != r["tarih"]
            or _kurus(k.tl_borc) != r["tl_borc"]
            or _kurus(k.tl_alacak) != r["tl_alacak"]
        ):
            r["durum"] = DURUM_UYUSMAZ
            continue
        r["durum"] = DURUM_TAMAM
        r["usd_borc"] = _kurus(k.usd_borc)
        r["usd_alacak"] = _kurus(k.usd_alacak)
        r["onceki_gun_kuru"] = bool(k.kur_tarihi and r["tarih"] and k.kur_tarihi < r["tarih"])


def cari_usd_raporu(
    cari_id: int,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> dict[str, Any]:
    """Cari hareketleri TL ve işlem tarihindeki USD karşılığıyla döner.

    Tarih aralığında başlangıç öncesi hareketler devir satırına (TL + USD) toplanır.
    Kuru eksik satırlar USD toplamlarına katılmaz; toplamlar bu durumda "eksik" işaretlenir.
    """
    with get_session() as session:
        tablo_hazirla(session.connection())
        kayitlar = _hareketleri_topla(session, cari_id)
        _karsiliklari_eslestir(session, cari_id, kayitlar)

    devir = {"tl": Decimal("0.00"), "usd": Decimal("0.00"), "eksik": 0, "var": False}
    satirlar: list[dict[str, Any]] = []
    for r in kayitlar:
        t = r["tarih"]
        if baslangic and t and t < baslangic:
            devir["var"] = True
            devir["tl"] += r["tl_borc"] - r["tl_alacak"]
            if r["durum"] == DURUM_TAMAM:
                devir["usd"] += r["usd_borc"] - r["usd_alacak"]
            else:
                devir["eksik"] += 1
            continue
        if bitis and t and t > bitis:
            continue
        satirlar.append(r)

    tl_bakiye = devir["tl"]
    usd_bakiye = devir["usd"]
    toplam = {
        "tl_borc": Decimal("0.00"), "tl_alacak": Decimal("0.00"),
        "usd_borc": Decimal("0.00"), "usd_alacak": Decimal("0.00"),
    }
    eksik = 0
    for r in satirlar:
        tl_bakiye += r["tl_borc"] - r["tl_alacak"]
        toplam["tl_borc"] += r["tl_borc"]
        toplam["tl_alacak"] += r["tl_alacak"]
        if r["durum"] == DURUM_TAMAM:
            usd_bakiye += r["usd_borc"] - r["usd_alacak"]
            toplam["usd_borc"] += r["usd_borc"]
            toplam["usd_alacak"] += r["usd_alacak"]
        else:
            eksik += 1
        r["tl_bakiye"] = tl_bakiye
        r["usd_bakiye"] = usd_bakiye
        r["usd_eksik_birikimli"] = eksik + devir["eksik"]

    tam = eksik == 0 and devir["eksik"] == 0
    fark_notu = ""
    if tam and tl_bakiye == 0 and usd_bakiye != 0:
        fark_notu = (
            f"TL bakiye 0,00; tarihsel USD karşılık farkı {usd_bakiye:+,.2f} USD. {FARK_ACIKLAMASI}"
        )
    return {
        "cari_id": int(cari_id),
        "baslangic": baslangic,
        "bitis": bitis,
        "devir": devir,
        "satirlar": satirlar,
        "toplam": toplam,
        "tl_bakiye": tl_bakiye,
        "usd_bakiye": usd_bakiye,
        "eksik_sayisi": eksik,
        "devir_eksik": devir["eksik"],
        "tam": tam,
        "fark_notu": fark_notu,
        "aciklama": FARK_ACIKLAMASI,
    }


# ---------------------------------------------------------------- geçmiş kayıt tamamlama


def eksik_kur_onizleme(
    cari_id: int | None = None,
    *,
    internetten: bool = False,
) -> dict[str, Any]:
    """Kuru eksik / uyuşmayan hareketler ve önerilen kurlar (veritabanına karşılık yazmaz).

    internetten=True ise kuru yerelde bulunamayan her tarih için TCMB'den çekilir
    (yalnız kur tablosuna yazılır; mevcut manuel kurlar korunur).
    """
    with get_session() as session:
        tablo_hazirla(session.connection())
        if cari_id is not None:
            cari_idler = [int(cari_id)]
        else:
            cari_idler = sorted(
                set(session.scalars(select(CariIslem.cari_id).distinct()).all())
                | set(session.scalars(select(SatisHareketi.cari_id).distinct()).all())
            )
        adaylar: list[dict[str, Any]] = []
        for cid in cari_idler:
            kayitlar = _hareketleri_topla(session, cid)
            _karsiliklari_eslestir(session, cid, kayitlar)
            for r in kayitlar:
                if r["durum"] != DURUM_TAMAM:
                    r["cari_id"] = cid
                    adaylar.append(r)

    hatalar: dict[date, str] = {}
    if internetten:
        from database.doviz_service import DovizService

        with get_session() as session:
            eksik_tarihler = sorted({
                r["tarih"] for r in adaylar
                if r["tarih"] and rapor_kuru_bul(session, r["tarih"]) is None
            })
        for tarih in eksik_tarihler:
            try:
                DovizService.tcmb_kurlari_cek(tarih, hedefe_kopyala=False)
            except ValueError as hata:
                hatalar[tarih] = str(hata)

    with get_session() as session:
        for r in adaylar:
            if (
                r["durum"] == DURUM_UYUSMAZ
                and r.get("kayit_islem_tarihi") == r["tarih"]
                and r.get("usd_kur")
            ):
                # Tarih değişmedi: saklı kur korunur, yalnız USD tutarı yeniden hesaplanır
                r["oneri"] = {
                    "kur": r["usd_kur"], "kur_tarihi": r.get("kur_tarihi"),
                    "kaynak": r.get("kur_kaynagi"), "kur_turu": KUR_TURU,
                }
            else:
                r["oneri"] = rapor_kuru_bul(session, r["tarih"]) if r["tarih"] else None
    return {
        "satirlar": adaylar,
        "hatalar": hatalar,
        "kur_bulunamayan_tarihler": sorted({r["tarih"] for r in adaylar if r["oneri"] is None and r["tarih"]}),
    }


def eksik_kurlari_uygula(
    satirlar: list[dict[str, Any]],
    manuel_kurlar: dict[date, Any] | None = None,
) -> dict[str, int]:
    """Önizlemesi onaylanan satırlara USD karşılık yazar.

    - Eksiksiz (TAMAM) ve tutarı uyan kayıtların kuru asla değiştirilmez.
    - Manuel kur yalnız bu karşılık kaydına yazılır (kur tablosuna değil); kaynak MANUEL,
      kur tarihi işlem tarihidir. Sıfır/negatif kur reddedilir.
    """
    manuel = {t: manuel_kur_dogrula(k) for t, k in (manuel_kurlar or {}).items()}
    sonuc = {"yazilan": 0, "manuel": 0, "atlanan": 0}
    with get_session() as session:
        conn = session.connection()
        tablo_hazirla(conn)
        for r in satirlar:
            kaynak, kid = r["kaynak"], int(r["kaynak_id"])
            obj = session.get(CariIslem if kaynak == KAYNAK_ISLEM else SatisHareketi, kid)
            if obj is None:
                sonuc["atlanan"] += 1
                continue
            kaynak, kid, cari_id, belge_no, tarih, borc, alacak = _satir_bilgisi(obj)
            mevcut = _mevcut_kayit(conn, kaynak, kid)
            if (
                mevcut
                and mevcut.get("durum") == DURUM_TAMAM
                and mevcut.get("islem_tarihi") == tarih
                and _kurus(mevcut.get("tl_borc")) == borc
                and _kurus(mevcut.get("tl_alacak")) == alacak
            ):
                sonuc["atlanan"] += 1
                continue
            if tarih in manuel:
                kur = manuel[tarih]
                deger = {
                    "kaynak": kaynak, "kaynak_id": kid, "cari_id": cari_id,
                    "belge_no": belge_no[:50] if belge_no else None, "islem_tarihi": tarih,
                    "tl_borc": borc, "tl_alacak": alacak, "kur_turu": KUR_TURU,
                    "usd_kur": kur, "kur_tarihi": tarih, "kur_kaynagi": "MANUEL",
                    "usd_borc": usd_hesapla(borc, kur), "usd_alacak": usd_hesapla(alacak, kur),
                    "durum": DURUM_TAMAM, "guncelleme": datetime.now(),
                }
                sonuc["manuel"] += 1
            else:
                deger = _degerler(
                    session, kaynak=kaynak, kaynak_id=kid, cari_id=cari_id, belge_no=belge_no,
                    tarih=tarih, borc=borc, alacak=alacak, mevcut=mevcut,
                )
                if deger["durum"] != DURUM_TAMAM:
                    sonuc["atlanan"] += 1
                    continue
            _kaydet(conn, deger, mevcut)
            sonuc["yazilan"] += 1
    return sonuc


def eksik_ozet(onizleme: dict[str, Any]) -> dict[date, int]:
    sayac: dict[date, int] = defaultdict(int)
    for r in onizleme.get("satirlar", []):
        if r.get("tarih"):
            sayac[r["tarih"]] += 1
    return dict(sayac)
