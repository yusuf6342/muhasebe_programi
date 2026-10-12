"""Stok raporları — durum, değerleme, planlama, yaşlandırma, devir, sayım, transfer, tutarlılık ve
stok yatırım verimliliği (GMROI).

Bütün fonksiyonlar salt okunurdur: stok hareketi, lot, belge, cari veya muhasebe kaydı oluşturmaz,
değiştirmez ya da silmez. Satış miktarı ve hızı, satış yönetici raporlarıyla aynı hesaptan
(``SatisKarAnalizService._satirlari_yukle`` → ``topla`` / ``tamamla``) gelir.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import selectinload

from database.access import maliyet_izinli, yetki_zorunlu
from database.database import get_session
from database.models.stok import (
    Depo,
    DepoTransferFisi,
    StokBarkod,
    StokBirim,
    StokFiyati,
    StokHareketi,
    StokKarti,
    StokLotu,
)
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService
from database.turkce_normalize import turkce_normalize

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
DORT = Decimal("0.0001")
ESIK = Decimal("0.0001")

TRANSFER = frozenset({"TRANSFER GİRİŞ", "TRANSFER ÇIKIŞ"})
GIRIS = frozenset(GIRIS_HAREKETLERI) | {"İRSALİYE İADE GİRİŞ"}
CIKIS = frozenset(CIKIS_HAREKETLERI) | {"İRSALİYE ÇIKIŞ"}

REZERVASYON_NOTU = (
    "Programda ayrı stok rezervasyonu tutulmuyor (Rezervasyon = 0). Bekleyen müşteri siparişleri "
    "kullanılabilir miktardan bir kez düşülür; rezervasyon ve sipariş birlikte düşülmez."
)
TRANSIT_NOTU = (
    "Depo transferi tek adımda kaynak depodan çıkış ve hedef depoya giriş olarak kaydedilir; yolda stok "
    "oluşmaz (Yoldaki = 0). Firma toplamında transfer edilen miktar iki kez sayılmaz."
)
SALT_OKUNUR_NOTU = "Rapor salt okunurdur; stok, belge, cari veya muhasebe kaydı oluşturmaz ve değiştirmez."

FIFO = "FIFO"


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def _yetki() -> None:
    yetki_zorunlu("stok_goruntuleme", "stok_duzenleme", mesaj="Stok raporlarını görüntüleme yetkiniz yok.")


def maliyet_gorunur() -> bool:
    try:
        return bool(maliyet_izinli())
    except Exception:  # noqa: BLE001
        return False


def _hizmet(kart) -> bool:
    return "hizmet" in (kart.kart_turu or "").casefold()


def _tablo_var(session, ad: str) -> bool:
    try:
        return inspect(session.connection()).has_table(ad)
    except Exception:  # noqa: BLE001
        return False


def _kartlar(session, arama: str = "", grup_id=None, *, pasif_dahil: bool = False) -> list[StokKarti]:
    q = select(StokKarti).options(selectinload(StokKarti.birimler))
    if not pasif_dahil:
        q = q.where(StokKarti.aktif.is_(True))
    hedef = turkce_normalize((arama or "").strip())
    out = []
    for k in session.scalars(q.order_by(StokKarti.stok_kodu)).all():
        if getattr(k, "is_deleted", False) or _hizmet(k):
            continue
        if hedef and hedef not in turkce_normalize(k.stok_kodu or "") and hedef not in turkce_normalize(
                k.stok_adi or "") and hedef not in turkce_normalize(k.barkod or ""):
            continue
        if grup_id and int(grup_id) not in {k.ana_grup_id, k.tali_grup_id, k.alt_grup_id}:
            continue
        out.append(k)
    return out


def _carpan(kart, birim: str | None, kayitli=None) -> Decimal | None:
    c = _d(kayitli)
    if c > 0:
        return c
    if kart is None:
        return None
    try:
        return StokService.birim_carpani_kesin(kart, birim or kart.birim)
    except Exception:  # noqa: BLE001
        return None


def _depo_eslesir(ad: str | None, depo: str | None) -> bool:
    return not depo or (ad or "") == depo


def _varsayilan_depo_adi(session) -> str:
    d = session.scalar(select(Depo).where(Depo.varsayilan.is_(True)).limit(1)) \
        or session.scalar(select(Depo).order_by(Depo.id).limit(1))
    return d.ad if d else ""


def _lot_bakiyeleri(session) -> dict[tuple[int, int], Decimal]:
    return {(int(s), int(d)): _d(m) for s, d, m in session.execute(
        select(StokLotu.stok_id, StokLotu.depo_id, func.sum(StokLotu.kalan_miktar))
        .group_by(StokLotu.stok_id, StokLotu.depo_id)).all()}


def _urun_toplami(degerler: dict[tuple[int, int], Decimal], depolar: dict[int, str], depo: str | None) -> dict:
    out: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    for (sid, did), m in degerler.items():
        if _depo_eslesir(depolar.get(did), depo):
            out[sid] += m
    return out


def _kod_toplami(degerler: dict[tuple[str, str], Decimal], depo: str | None) -> dict:
    out: dict[str, Decimal] = defaultdict(lambda: SIFIR)
    for (kod, d), m in degerler.items():
        if _depo_eslesir(d, depo):
            out[kod] += m
    return out


def _bekleyenler(session, kod_kart: dict[str, StokKarti]):
    """(ürün kodu, depo) → bekleyen alış ve bekleyen satış siparişi (temel birim) + çevrimsiz satır kodları."""
    from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
    from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
    from database.stok_uyari_service import SATIS_SIPARIS_HARIC, SIPARIS_HARIC

    varsayilan = _varsayilan_depo_adi(session)
    alis: dict[tuple[str, str], Decimal] = defaultdict(lambda: SIFIR)
    satis: dict[tuple[str, str], Decimal] = defaultdict(lambda: SIFIR)
    cevrimsiz: set[str] = set()
    for s, depo in session.execute(
            select(AlisSiparisiSatiri, AlisSiparisi.teslim_depo)
            .join(AlisSiparisi, AlisSiparisi.id == AlisSiparisiSatiri.siparis_id)
            .where(AlisSiparisi.durum.notin_(SIPARIS_HARIC))).all():
        kart = kod_kart.get(s.urun_kodu)
        acik = _d(s.miktar) - _d(s.faturalanan_miktar)
        if kart is None or acik <= 0:
            continue
        c = _carpan(kart, s.birim)
        if c is None:
            cevrimsiz.add(s.urun_kodu)
            c = Decimal("1")
        alis[(s.urun_kodu, depo or varsayilan)] += acik * c
    for s, depo in session.execute(
            select(SatisSiparisiSatiri, SatisSiparisi.depo)
            .join(SatisSiparisi, SatisSiparisi.id == SatisSiparisiSatiri.siparis_id)
            .where(SatisSiparisi.durum.notin_(SATIS_SIPARIS_HARIC))).all():
        kart = kod_kart.get(s.urun_kodu)
        acik = _d(s.miktar) - max(_d(s.irsaliyelenen_miktar), _d(s.faturalanan_miktar))
        if kart is None or acik <= 0:
            continue
        c = _carpan(kart, s.birim)
        if c is None:
            cevrimsiz.add(s.urun_kodu)
            c = Decimal("1")
        satis[(s.urun_kodu, depo or varsayilan)] += acik * c
    return alis, satis, cevrimsiz


def satis_ozeti(bas: date, bit: date, filtre: dict | None = None) -> dict[str, dict]:
    """Ürün kodu → satış yönetici raporlarıyla aynı net satış kovası (iadeler düşülmüş)."""
    from database.satis_kar_analiz_service import SatisKarAnalizService
    from database.satis_yonetici_rapor_service import kar_filtresi, tamamla, topla

    satirlar = SatisKarAnalizService._satirlari_yukle(kar_filtresi(bas, bit, filtre or {}))
    return {kod: tamamla(k) for kod, k in topla(satirlar, "urun").items()}


def _son_satislar(bugun: date) -> dict[str, date]:
    from database.satis_yonetici_rapor_service import son_satis_tarihleri

    return son_satis_tarihleri(bugun, "urun")


def _grup_meta(session):
    from database.satis_kar_analiz_service import SatisKarAnalizService

    adlar = SatisKarAnalizService._grup_adlari(session)
    return lambda kart: SatisKarAnalizService._stok_meta(kart, adlar)


# ---------------------------------------------------------------------------
# 2) Stok durumu / kullanılabilir miktar
# ---------------------------------------------------------------------------

def stok_durumu(*, depo: str | None = None, arama: str = "", grup_id=None, sifir_dahil: bool = False) -> dict:
    _yetki()
    maliyet_ok = maliyet_gorunur()
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = _kartlar(s, arama, grup_id)
        kod_kart = {k.stok_kodu: k for k in kartlar}
        lotlar = _lot_bakiyeleri(s)
        alis, satis, cevrimsiz = _bekleyenler(s, kod_kart)
        fifo = StokService.fifo_envanter_degerleri(s) if maliyet_ok else {}
    sid_depo: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for (sid, did), m in lotlar.items():
        sid_depo[sid][depolar.get(did, f"#{did}")] = m
    deger: dict[tuple[int, str], Decimal] = {(sid, depolar.get(did, "")): _d(v["deger"]) for (sid, did), v in fifo.items()}
    siparis_depolari: dict[str, set[str]] = defaultdict(set)
    for kod, d in list(alis) + list(satis):
        siparis_depolari[kod].add(d)
    satirlar, urunler = [], []
    depo_ozet: dict[str, dict] = {}
    for k in kartlar:
        adlar = set(sid_depo.get(k.id, {})) | siparis_depolari.get(k.stok_kodu, set())
        toplam = {"mevcut": SIFIR, "bekleyen_satis": SIFIR, "bekleyen_alis": SIFIR, "deger": SIFIR, "depo_sayisi": 0}
        for ad in sorted(adlar):
            if not _depo_eslesir(ad, depo):
                continue
            mevcut = sid_depo.get(k.id, {}).get(ad, SIFIR)
            bs, ba = satis.get((k.stok_kodu, ad), SIFIR), alis.get((k.stok_kodu, ad), SIFIR)
            if not sifir_dahil and mevcut == 0 and bs == 0 and ba == 0:
                continue
            kullanilabilir = mevcut - bs
            notlar = []
            if mevcut < 0:
                notlar.append("Negatif stok")
            if kullanilabilir < 0 <= mevcut:
                notlar.append("Bekleyen müşteri siparişi stoktan fazla")
            if k.stok_kodu in cevrimsiz:
                notlar.append("Birimi çevrilemeyen sipariş satırı 1 kabul edildi")
            v = deger.get((k.id, ad)) if maliyet_ok else None
            r = {"urun_kodu": k.stok_kodu, "urun_adi": k.stok_adi, "birim": k.birim or "Adet", "depo": ad,
                 "mevcut": mevcut, "rezervasyon": SIFIR, "bekleyen_satis": bs, "kullanilabilir": kullanilabilir,
                 "bekleyen_alis": ba, "ongorulen": kullanilabilir + ba, "yoldaki": SIFIR,
                 "deger": _q2(v) if v is not None else None, "aciklama": "; ".join(notlar), "stok_id": k.id}
            satirlar.append(r)
            toplam["mevcut"] += mevcut
            toplam["bekleyen_satis"] += bs
            toplam["bekleyen_alis"] += ba
            toplam["deger"] += _d(v)
            toplam["depo_sayisi"] += 1
            o = depo_ozet.setdefault(ad, {"depo": ad, "urun_sayisi": 0, "negatif": 0, "kullanilabilir_eksi": 0,
                                          "bekleyen_alis_urun": 0, "bekleyen_satis_urun": 0, "deger": SIFIR})
            o["urun_sayisi"] += 1
            o["negatif"] += mevcut < 0
            o["kullanilabilir_eksi"] += kullanilabilir < 0
            o["bekleyen_alis_urun"] += ba > 0
            o["bekleyen_satis_urun"] += bs > 0
            o["deger"] += _d(v)
        if toplam["depo_sayisi"]:
            ku = toplam["mevcut"] - toplam["bekleyen_satis"]
            urunler.append({"urun_kodu": k.stok_kodu, "urun_adi": k.stok_adi, "birim": k.birim or "Adet",
                            "depo_sayisi": toplam["depo_sayisi"], "mevcut": toplam["mevcut"], "rezervasyon": SIFIR,
                            "bekleyen_satis": toplam["bekleyen_satis"], "kullanilabilir": ku,
                            "bekleyen_alis": toplam["bekleyen_alis"], "ongorulen": ku + toplam["bekleyen_alis"],
                            "yoldaki": SIFIR, "deger": _q2(toplam["deger"]) if maliyet_ok else None,
                            "stok_id": k.id})
    depolar_l = sorted(depo_ozet.values(), key=lambda o: o["depo"])
    for o in depolar_l:
        o["deger"] = _q2(o["deger"]) if maliyet_ok else None
    if depolar_l:
        depolar_l.append({"depo": "FİRMA TOPLAMI", "_sabit": True,
                          **{a: sum(o[a] for o in depolar_l) for a in ("negatif", "kullanilabilir_eksi",
                                                                       "bekleyen_alis_urun", "bekleyen_satis_urun")},
                          "urun_sayisi": len(urunler),
                          "deger": _q2(sum((_d(o["deger"]) for o in depolar_l), SIFIR)) if maliyet_ok else None})
    notlar = [
        "Kullanılabilir = Mevcut − Rezervasyon − Bekleyen satış siparişi. Bekleyen alış teslim alınmadan "
        "kullanılabilir miktara eklenmez; ayrıca 'Öngörülen (alış gelince)' sütununda gösterilir.",
        REZERVASYON_NOTU,
        "Bekleyen satış = taslak/iptal/faturalı dışındaki siparişlerde miktar − max(irsaliyelenen, faturalanan); "
        "irsaliyelenen miktar stoktan zaten düştüğü için ikinci kez düşülmez.",
        "Bekleyen alış = taslak/iptal dışındaki alış siparişlerinde faturalanmamış kalan (stoğa fatura ile girer).",
        TRANSIT_NOTU,
        "Firma toplamı ürün bazında tüm depoların toplamıdır; farklı birimli ürünlerin miktarları birbirine eklenmez.",
        SALT_OKUNUR_NOTU,
    ]
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından stok değeri gösterilmez.")
    return {"satirlar": satirlar, "urunler": urunler, "depolar": depolar_l, "notlar": notlar}


# ---------------------------------------------------------------------------
# 4) Değerleme / envanter (tarih itibarıyla)
# ---------------------------------------------------------------------------

def degerleme_yontemleri() -> list[tuple[str, str]]:
    from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI, SON_ALIS

    return [(FIFO, "FIFO (tarihteki açık katmanlar)"), (HAREKETLI, "Hareketli ağırlıklı ortalama (tarih sonu)"),
            (DONEMSEL, "Dönemsel ağırlıklı ortalama (o ay)"),
            (SON_ALIS, "Son alış maliyeti — tarihe kadarki son alış (karşılaştırma amaçlı)")]


def _lot_bakiyesi_tarihte(session, tarih: date) -> dict[int, Decimal]:
    out: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    for lot_id, tur, m in session.execute(
            select(StokHareketi.lot_id, StokHareketi.hareket_turu, func.sum(StokHareketi.miktar))
            .where(StokHareketi.tarih <= tarih, StokHareketi.lot_id.is_not(None))
            .group_by(StokHareketi.lot_id, StokHareketi.hareket_turu)).all():
        if tur in GIRIS:
            out[int(lot_id)] += _d(m)
        elif tur in CIKIS:
            out[int(lot_id)] -= _d(m)
    return out


def _satis_fiyatlari(session) -> dict[int, Decimal]:
    out: dict[int, tuple[int, Decimal]] = {}
    for sid, ad, tutar in session.execute(select(StokFiyati.stok_id, StokFiyati.fiyat_adi, StokFiyati.tutar)).all():
        ad = (ad or "").strip().upper()
        if not ad.startswith("SATIŞ FİYATI"):
            continue
        oncelik = 0 if ad == "SATIŞ FİYATI 1" else 1
        if int(sid) not in out or oncelik < out[int(sid)][0]:
            out[int(sid)] = (oncelik, _d(tutar))
    return {k: v for k, (_o, v) in out.items()}


def degerleme(*, tarih: date | None = None, yontem: str = FIFO, depo: str | None = None, arama: str = "",
              grup_id=None, satis_fiyati: bool = False) -> dict:
    from database.satis_maliyet_motoru import MaliyetMotoru

    _yetki()
    tarih = tarih or date.today()
    yontemler = dict(degerleme_yontemleri())
    if yontem not in yontemler:
        raise ValueError(f"Desteklenmeyen değerleme yöntemi: {yontem}")
    maliyet_ok = maliyet_gorunur()
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = {k.id: k for k in _kartlar(s, arama, grup_id, pasif_dahil=True)}
        hizmet_sayisi = sum(1 for k in s.scalars(select(StokKarti)).all() if _hizmet(k))
        fifo = StokService.fifo_envanter_degerleri(s, tarih)
        maliyetsiz: dict[tuple[int, int], Decimal] = defaultdict(lambda: SIFIR)
        if yontem == FIFO:
            lot_q = _lot_bakiyesi_tarihte(s, tarih)
            for lot in s.scalars(select(StokLotu).where(StokLotu.birim_maliyet <= 0)).all():
                q = lot_q.get(int(lot.id), SIFIR)
                if q > 0:
                    maliyetsiz[(int(lot.stok_id), int(lot.depo_id))] += q
        motor = MaliyetMotoru(s, bitis=tarih) if yontem != FIFO else None
        meta = _grup_meta(s)
        fiyatlar = _satis_fiyatlari(s) if satis_fiyati else {}
        satirlar = []
        for (sid, did), v in sorted(fifo.items(), key=lambda x: (kartlar[x[0][0]].stok_kodu if x[0][0] in kartlar
                                                                  else "", depolar.get(x[0][1], ""))):
            kart = kartlar.get(sid)
            ad = depolar.get(did, f"#{did}")
            miktar = _d(v["miktar"])
            if kart is None or miktar == 0 or not _depo_eslesir(ad, depo):
                continue
            birim = tutar = None
            durum, kaynak = "", ""
            if miktar < 0:
                durum = "Negatif stok"
                kaynak = "Negatif miktar değerlenmez"
            elif yontem == FIFO:
                eksik = maliyetsiz.get((sid, did), SIFIR)
                if eksik >= miktar:
                    durum, kaynak = "Eksik maliyet", "Açık katmanların maliyeti yok"
                else:
                    tutar = _q2(v["deger"])
                    birim = (tutar / (miktar - eksik)).quantize(DORT)
                    kaynak = "Tarihteki açık FIFO katmanları"
                    if eksik > 0:
                        durum = f"Kısmi eksik maliyet ({eksik.normalize():f} {kart.birim or ''} maliyetsiz)"
            else:
                b, kaynak = motor.birim_maliyet(yontem, kart, tarih)
                if b is None:
                    durum = "Eksik maliyet"
                else:
                    birim, tutar = b, _q2(miktar * b)
            fiyat = fiyatlar.get(sid)
            satirlar.append({
                "stok_id": sid, "urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi, "birim": kart.birim or "Adet",
                "depo": ad, **meta(kart), "miktar": miktar, "birim_maliyet": birim, "toplam_maliyet": tutar,
                "yontem": yontemler[yontem], "maliyet_kaynagi": kaynak, "durum": durum,
                "pasif": "" if kart.aktif else "Pasif kart",
                "satis_fiyati": fiyat, "satis_degeri": _q2(miktar * fiyat) if fiyat is not None and miktar > 0 else None,
            })
    if not maliyet_ok:
        for r in satirlar:
            r["birim_maliyet"] = r["toplam_maliyet"] = None

    def ozet(anahtar_fn, meta_fn):
        out: dict[Any, dict] = {}
        for r in satirlar:
            a = anahtar_fn(r)
            o = out.setdefault(a, {**meta_fn(r), "satir": 0, "miktar": SIFIR, "toplam_maliyet": SIFIR,
                                   "eksik": 0, "negatif": 0, "satis_degeri": SIFIR})
            o["satir"] += 1
            if r["miktar"] > 0:
                o["miktar"] += r["miktar"]
            o["toplam_maliyet"] += _d(r["toplam_maliyet"])
            o["eksik"] += r["durum"].startswith(("Eksik", "Kısmi"))
            o["negatif"] += r["durum"] == "Negatif stok"
            o["satis_degeri"] += _d(r["satis_degeri"])
        liste = list(out.values())
        for o in liste:
            o["durum"] = "; ".join(x for x in (f"{o['eksik']} eksik maliyetli" if o["eksik"] else "",
                                               f"{o['negatif']} negatif" if o["negatif"] else "") if x)
            o["toplam_maliyet"] = _q2(o["toplam_maliyet"]) if maliyet_ok else None
            o["satis_degeri"] = _q2(o["satis_degeri"]) if satis_fiyati else None
        return liste

    urunler = ozet(lambda r: r["urun_kodu"], lambda r: {"urun_kodu": r["urun_kodu"], "urun_adi": r["urun_adi"],
                                                         "birim": r["birim"]})
    for u in urunler:
        if len({r["birim"] for r in satirlar if r["urun_kodu"] == u["urun_kodu"]}) > 1:
            u["miktar"] = None
    depo_l = ozet(lambda r: r["depo"], lambda r: {"depo": r["depo"]})
    for o in depo_l:
        o["miktar"] = None
    gruplar = ozet(lambda r: (r["ana_grup"], r["tali_grup"], r["alt_grup"]),
                   lambda r: {"ana_grup": r["ana_grup"] or "(Grupsuz)", "tali_grup": r["tali_grup"],
                              "alt_grup": r["alt_grup"]})
    for o in gruplar:
        o["miktar"] = None
    gruplar.sort(key=lambda o: (o["ana_grup"], o["tali_grup"], o["alt_grup"]))
    sorunlu = [r for r in satirlar if r["durum"]]
    toplam = _q2(sum((_d(r["toplam_maliyet"]) for r in satirlar), SIFIR))
    notlar = [
        f"Değerleme tarihi {tarih:%d.%m.%Y}; yöntem: {yontemler[yontem]}. Miktarlar o tarihe kadarki stok "
        "hareketlerinden hesaplanır; bugünkü son alış fiyatıyla değerleme yapılmaz.",
        "Eksik maliyetli satırlar sıfır sayılmaz; değer toplamına katılmaz ve 'Eksik / Negatif' sekmesinde listelenir. "
        "Kısmi eksik satırlarda yalnız maliyeti bilinen katmanların değeri toplama girer.",
        "Negatif stok satırları değerlenmez ve toplama katılmaz.",
        f"Kapsam: aktif ve pasif stok kartları (pasif olanlar işaretli); hizmet kartları ({hizmet_sayisi}) stok "
        "tutmadığı için hariçtir.",
    ]
    if yontem != FIFO:
        notlar.append("Ortalama ve son alış yöntemleri ürün bazında tüm depolar için hesaplanır; muhasebedeki "
                      "maliyet yöntemini değiştirmez.")
    if satis_fiyati:
        notlar.append("'Satış fiyatıyla değer' maliyet değeri değildir; karttaki güncel SATIŞ FİYATI 1 (yoksa ilk "
                      "satış fiyatı) × miktar olarak ayrıca gösterilir ve maliyet toplamına katılmaz.")
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından maliyet sütunları gösterilmez.")
    notlar.append(SALT_OKUNUR_NOTU)
    return {"satirlar": satirlar, "urunler": urunler, "depolar": depo_l, "gruplar": gruplar, "sorunlu": sorunlu,
            "toplam_maliyet": toplam if maliyet_ok else None, "eksik_satir": sum(1 for r in sorunlu if r["durum"] !=
                                                                                 "Negatif stok"),
            "negatif_satir": sum(1 for r in sorunlu if r["durum"] == "Negatif stok"),
            "tarih": tarih, "yontem": yontemler[yontem], "notlar": notlar}


# ---------------------------------------------------------------------------
# 5) Kritik / tükenen stok
# ---------------------------------------------------------------------------

def _stoksuz_donemler(hareketler: list[tuple[date, str, Decimal]], bugun: date) -> list[dict]:
    """Gün sonu bakiyesi 0 veya altına düştüğü dönemler (önce stok girmiş olmalı)."""
    gunluk: dict[date, Decimal] = defaultdict(lambda: SIFIR)
    for t, tur, m in hareketler:
        if tur in GIRIS:
            gunluk[t] += m
        elif tur in CIKIS:
            gunluk[t] -= m
    bakiye, goruldu, bas = SIFIR, False, None
    out = []
    for t in sorted(gunluk):
        bakiye += gunluk[t]
        if bakiye > 0:
            goruldu = True
            if bas is not None:
                out.append({"bas": bas, "bit": t, "gun": (t - bas).days, "devam": False})
                bas = None
        elif goruldu and bas is None:
            bas = t
    if bas is not None:
        out.append({"bas": bas, "bit": None, "gun": (bugun - bas).days, "devam": True})
    return out


def kritik_tukenen(*, donem_gun: int = 90, depo: str | None = None, arama: str = "", grup_id=None,
                   bugun: date | None = None) -> dict:
    from database.models.stok_uyari import StokUyariAyari
    from database.stok_uyari_service import StokUyariService

    _yetki()
    b = bugun or date.today()
    donem_gun = max(1, int(donem_gun or 1))
    bas = b - timedelta(days=donem_gun - 1)
    satis = satis_ozeti(bas, b, {"depo": depo} if depo else None)
    son_satis = _son_satislar(b)
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        depo_id = next((i for i, a in depolar.items() if a == depo), None) if depo else None
        kartlar = _kartlar(s, arama, grup_id)
        kod_kart = {k.stok_kodu: k for k in kartlar}
        lotlar = _lot_bakiyeleri(s)
        alis, sat, _c = _bekleyenler(s, kod_kart)
        genel = StokUyariService.genel_ayarlar(s)
        ayarlar: dict[int, dict] = defaultdict(dict)
        if _tablo_var(s, StokUyariAyari.__tablename__):
            for a in s.scalars(select(StokUyariAyari)).all():
                ayarlar[int(a.stok_id)][a.depo_id] = a
        hareketli = {int(x) for (x,) in s.execute(select(StokHareketi.stok_id).distinct()).all()}
        girisli = {int(x) for (x,) in s.execute(select(StokHareketi.stok_id).where(
            StokHareketi.hareket_turu.in_(GIRIS - TRANSFER)).distinct()).all()}
        son_alis = StokUyariService.alis_gecmisi(s, list(kod_kart))
        mevcut_u, bs_u, ba_u = _urun_toplami(lotlar, depolar, depo), _kod_toplami(sat, depo), _kod_toplami(alis, depo)
        satirlar, minimumsuz = [], []
        for k in kartlar:
            mevcut = mevcut_u.get(k.id, SIFIR)
            bs, ba = bs_u.get(k.stok_kodu, SIFIR), ba_u.get(k.stok_kodu, SIFIR)
            kullanilabilir = mevcut - bs
            ayar = StokUyariService.etkin_ayar(s, k, depo_id, genel, ayarlar.get(k.id, {}))
            minimum = ayar.get("minimum")
            t = satis.get(k.stok_kodu)
            net_m = t["net_miktar"] if t else SIFIR
            hiz = (net_m / donem_gun).quantize(Decimal("0.001")) if net_m and net_m > 0 else None
            if mevcut < 0:
                durum = "Negatif"
            elif mevcut == 0:
                durum = "Sıfır" if k.id in girisli else "Sıfır — hiç stok girişi yok"
            elif minimum is not None and minimum > 0 and kullanilabilir <= minimum:
                durum = "Minimum altı"
            elif kullanilabilir <= 0:
                durum = "Kullanılabilir yok (siparişe bağlı)"
            else:
                durum = ""
            son = (son_alis.get(k.stok_kodu) or [None])[0]
            r = {"stok_id": k.id, "urun_kodu": k.stok_kodu, "urun_adi": k.stok_adi, "birim": k.birim or "Adet",
                 "durum": durum, "mevcut": mevcut, "bekleyen_satis": bs, "kullanilabilir": kullanilabilir,
                 "minimum": minimum if minimum and minimum > 0 else None,
                 "minimum_kaynagi": ayar.get("kaynak", {}).get("minimum", "") if minimum else "",
                 "donem_satis": net_m, "gunluk_hiz": hiz,
                 "son_alis": son["tarih"] if son else None, "son_satis": son_satis.get(k.stok_kodu),
                 "son_tedarikci": son["cari"] if son else "", "bekleyen_alis": ba,
                 "aciklama": "Birim çevrimi yok — hız hesaplanamadı" if t and net_m is None else ""}
            if durum and (k.id in hareketli or (minimum and minimum > 0)):
                satirlar.append(r)
            if not (minimum and minimum > 0) and k.id in hareketli:
                minimumsuz.append(r)
        sira = {"Negatif": 0, "Sıfır": 1, "Sıfır — hiç stok girişi yok": 2, "Minimum altı": 3}
        satirlar.sort(key=lambda r: (sira.get(r["durum"], 4), r["urun_kodu"]))
        idler = [r["stok_id"] for r in satirlar]
        gecmis = []
        depo_kosul = (StokHareketi.depo_id == depo_id,) if depo_id else ()
        for i in range(0, len(idler), 500):
            har: dict[int, list] = defaultdict(list)
            for sid, t, tur, m in s.execute(
                    select(StokHareketi.stok_id, StokHareketi.tarih, StokHareketi.hareket_turu, StokHareketi.miktar)
                    .where(StokHareketi.stok_id.in_(idler[i:i + 500]), *depo_kosul)
                    .order_by(StokHareketi.stok_id, StokHareketi.tarih, StokHareketi.id)).all():
                har[int(sid)].append((t, tur, _d(m)))
            kart_id = {k.id: k for k in kartlar}
            for sid, liste in har.items():
                kart = kart_id[sid]
                for p in _stoksuz_donemler(liste, b)[-10:]:
                    gecmis.append({"urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi, "bas": p["bas"],
                                   "bit": p["bit"], "gun": p["gun"],
                                   "durum": "Devam ediyor" if p["devam"] else "Stok yeniden girdi",
                                   "son_satis": son_satis.get(kart.stok_kodu)})
    gecmis.sort(key=lambda r: (r["urun_kodu"], r["bas"]))
    sayac = defaultdict(int)
    for r in satirlar:
        sayac[r["durum"]] += 1
    notlar = [
        f"Satış hızı: son {donem_gun} günün net satış miktarı (iadeler düşülmüş, temel birim) / {donem_gun} gün; "
        "satış yönetici raporlarıyla aynı hesap. Transfer ve alış iadesi satış sayılmaz.",
        "Durumlar ayrıdır: Negatif (mevcut < 0), Sıfır (mevcut = 0), Minimum altı (kullanılabilir ≤ minimum). "
        "Minimum: depo/ürün uyarı ayarı, yoksa stok kartı, yoksa firma varsayılanı.",
        "Minimum stok tanımı olmayan ve hareket görmüş ürünler 'Minimum Tanımsız' sekmesinde ayrıca listelenir.",
        "Stoksuz kalma geçmişi gün sonu bakiyesinin sıfır veya altına düştüğü dönemleri gösterir (ürün başına son 10).",
        REZERVASYON_NOTU, SALT_OKUNUR_NOTU,
    ]
    return {"satirlar": satirlar, "minimumsuz": minimumsuz, "gecmis": gecmis, "sayac": dict(sayac), "notlar": notlar}


# ---------------------------------------------------------------------------
# 7) Yavaş hareket eden / satılmayan
# ---------------------------------------------------------------------------

def yavas_satilmayan(*, bas: date, bit: date, esik_gun: int = 90, yeni_gun: int = 30, depo: str | None = None,
                     arama: str = "", grup_id=None, tur: str = "tumu", bugun: date | None = None) -> dict:
    """tur: tumu | hic_satilmayan | yavas | yeni."""
    _yetki()
    b = bugun or date.today()
    esik_gun, yeni_gun = max(0, int(esik_gun or 0)), max(0, int(yeni_gun or 0))
    maliyet_ok = maliyet_gorunur()
    satis = satis_ozeti(bas, bit, {"depo": depo} if depo else None)
    son_satis = _son_satislar(b)
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = _kartlar(s, arama, grup_id)
        meta = _grup_meta(s)
        lotlar = _lot_bakiyeleri(s)
        fifo = StokService.fifo_envanter_degerleri(s) if maliyet_ok else {}
        girisler = {int(sid): (ilk, son) for sid, ilk, son in s.execute(
            select(StokHareketi.stok_id, func.min(StokHareketi.tarih), func.max(StokHareketi.tarih))
            .where(StokHareketi.hareket_turu.in_(GIRIS - TRANSFER)).group_by(StokHareketi.stok_id)).all()}
    mevcut_u = _urun_toplami(lotlar, depolar, depo)
    deger_u = _urun_toplami({a: _d(v["deger"]) for a, v in fifo.items()}, depolar, depo)
    satirlar = []
    for k in kartlar:
        mevcut = mevcut_u.get(k.id, SIFIR)
        if mevcut <= 0:
            continue
        deger = deger_u.get(k.id, SIFIR) if maliyet_ok else None
        son_t = son_satis.get(k.stok_kodu)
        gun = (b - son_t).days if son_t else None
        ilk_g, son_g = girisler.get(k.id, (None, None))
        t = satis.get(k.stok_kodu)
        if son_t is None:
            if ilk_g and (b - ilk_g).days <= yeni_gun:
                sinif, kod = f"Yeni alım — henüz satış yok (ilk giriş {(b - ilk_g).days} gün önce)", "yeni"
            else:
                bekleme = f"{(b - ilk_g).days} gündür stokta" if ilk_g else "giriş tarihi bilinmiyor"
                sinif, kod = f"Hiç satılmadı — {bekleme}", "hic_satilmayan"
        elif gun >= esik_gun:
            sinif, kod = f"Yavaş — {gun} gündür satış yok", "yavas"
            if son_g and (b - son_g).days <= yeni_gun:
                sinif += f"; son giriş yeni ({son_g:%d.%m.%Y})"
        else:
            continue
        if tur != "tumu" and tur != kod:
            continue
        satirlar.append({"stok_id": k.id, "urun_kodu": k.stok_kodu, "urun_adi": k.stok_adi,
                         "birim": k.birim or "Adet", **meta(k), "miktar": mevcut,
                         "maliyet_degeri": _q2(deger) if deger is not None else None,
                         "son_satis": son_t, "son_satis_gun": gun,
                         "donem_net_satis": t["net"] if t else SIFIR,
                         "donem_net_miktar": t["net_miktar"] if t else SIFIR,
                         "ilk_giris": ilk_g, "son_giris": son_g, "sinif": sinif, "tur": kod})
    satirlar.sort(key=lambda r: (-(r["son_satis_gun"] if r["son_satis_gun"] is not None else 10 ** 6), r["urun_kodu"]))
    notlar = [
        f"Yavaş: son satıştan bu yana {esik_gun} gün ve üzeri geçmiş, stokta olan ürünler. Son satış, onaylı "
        "satış faturalarından gelir; depo transferi, sayım ve alış iadesi satış sayılmaz.",
        "Hiç satılmamış ürünlerde son satış tarihi uydurulmaz; transfer dışı ilk stok giriş tarihi gösterilir.",
        f"İlk girişi son {yeni_gun} gün içinde olan ve henüz satılmayan ürünler 'Yeni alım' olarak ayrılır.",
        f"Dönem net satışı {bas:%d.%m.%Y}–{bit:%d.%m.%Y} aralığında, iadeler düşülmüş ve KDV hariçtir.",
        SALT_OKUNUR_NOTU,
    ]
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından maliyet değeri gösterilmez.")
    return {"satirlar": satirlar, "notlar": notlar,
            "toplam_deger": _q2(sum((_d(r["maliyet_degeri"]) for r in satirlar), SIFIR)) if maliyet_ok else None}


# ---------------------------------------------------------------------------
# 8) Stok yaşlandırma (katman bazlı)
# ---------------------------------------------------------------------------

YAS_KOVALARI = ((0, 30, "0_30", "0–30"), (31, 60, "31_60", "31–60"), (61, 90, "61_90", "61–90"),
                (91, 180, "91_180", "91–180"), (181, 365, "181_365", "181–365"), (366, None, "365p", ">365"))
_DEVIR_IPUCLARI = ("acilis", "devir", "evo oto")


def devir_lotu_mu(lot) -> bool:
    ted = turkce_normalize(lot.tedarikci or "")
    no = (lot.lot_no or "").upper()
    return any(i in ted for i in _DEVIR_IPUCLARI) or no.startswith(("EVB-", "DEVIR", "DEVİR"))


def _kova(gun: int) -> str:
    for a, b_, k, _e in YAS_KOVALARI:
        if gun >= a and (b_ is None or gun <= b_):
            return k
    return YAS_KOVALARI[0][2]


def yaslandirma(*, tarih: date | None = None, depo: str | None = None, arama: str = "", grup_id=None) -> dict:
    _yetki()
    tarih = tarih or date.today()
    maliyet_ok = maliyet_gorunur()
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = {k.id: k for k in _kartlar(s, arama, grup_id, pasif_dahil=True)}
        lot_q = _lot_bakiyesi_tarihte(s, tarih)
        lotlar = {int(l.id): l for l in s.scalars(select(StokLotu)).all()}
        lotsuz = {int(sid) for (sid,) in s.execute(select(StokHareketi.stok_id).where(
            StokHareketi.tarih <= tarih, StokHareketi.lot_id.is_(None)).distinct()).all()}
    urun: dict[int, dict] = {}
    for lot_id, q in lot_q.items():
        lot = lotlar.get(lot_id)
        if lot is None or q <= 0:
            continue
        kart = kartlar.get(int(lot.stok_id))
        if kart is None or not _depo_eslesir(depolar.get(int(lot.depo_id)), depo):
            continue
        r = urun.setdefault(kart.id, {"stok_id": kart.id, "urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi,
                                      "birim": kart.birim or "Adet", "miktar": SIFIR, "deger": SIFIR,
                                      "devir_miktar": SIFIR, "devir_deger": SIFIR, "_yas": SIFIR, "_yas_q": SIFIR,
                                      "en_eski": None,
                                      **{f"m_{k}": SIFIR for *_x, k, _e in YAS_KOVALARI},
                                      **{f"d_{k}": SIFIR for *_x, k, _e in YAS_KOVALARI}})
        v = q * _d(lot.birim_maliyet)
        r["miktar"] += q
        r["deger"] += v
        if devir_lotu_mu(lot):
            r["devir_miktar"] += q
            r["devir_deger"] += v
            continue
        gun = max(0, (tarih - lot.giris_tarihi).days) if lot.giris_tarihi else 0
        k = _kova(gun)
        r[f"m_{k}"] += q
        r[f"d_{k}"] += v
        r["_yas"] += q * gun
        r["_yas_q"] += q
        if lot.giris_tarihi and (r["en_eski"] is None or lot.giris_tarihi < r["en_eski"]):
            r["en_eski"] = lot.giris_tarihi
    satirlar = []
    for r in sorted(urun.values(), key=lambda x: x["urun_kodu"]):
        r["ort_yas"] = (r["_yas"] / r["_yas_q"]).quantize(Decimal("0.1")) if r["_yas_q"] else None
        r["aciklama"] = "; ".join(x for x in (
            "Lot bağlantısız hareket var — yaş yaklaşık" if r["stok_id"] in lotsuz else "",
            "Devir stoku (geçmişi bilinmiyor) ayrı" if r["devir_miktar"] else "") if x)
        for a in [a for a in r if a.startswith("_")]:
            r.pop(a)
        for a in [a for a in r if a.startswith("d_") or a in ("deger", "devir_deger")]:
            r[a] = _q2(r[a]) if maliyet_ok else None
        satirlar.append(r)
    if satirlar:
        toplam = {"urun_kodu": "TOPLAM", "_sabit": True}
        for a in [a for a in satirlar[0] if a.startswith("d_") or a in ("deger", "devir_deger")]:
            toplam[a] = _q2(sum((_d(r[a]) for r in satirlar), SIFIR)) if maliyet_ok else None
        satirlar.append(toplam)
    notlar = [
        f"Yaş = {tarih:%d.%m.%Y} − stok katmanının (lot) giriş tarihi. Katmanların o tarihteki kalan miktarı stok "
        "hareketlerinden hesaplanır.",
        "Depo transferinde katman giriş tarihi korunur; transfer yaşı sıfırlamaz.",
        "Devir/açılış katmanları (EvoBulut açılış, EVB- lotları, devir girişleri) gerçek giriş tarihi bilinmediğinden "
        "yaş kovalarına konmaz, 'Devir (geçmişi bilinmiyor)' sütunlarında ayrı gösterilir.",
        "Yaklaşımlar: sayım fazlası katmanları sayım tarihiyle yaşlanır; değer, katmanın güncel birim maliyetiyle "
        "(sonradan dağıtılan masraf payı dahil) hesaplanır; lot bağlantısız hareketler yaşa yansıtılamaz.",
        "Yaşlandırma raporu muhasebe maliyet yöntemini değiştirmez.", SALT_OKUNUR_NOTU,
    ]
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından değer sütunları gösterilmez.")
    return {"satirlar": satirlar, "notlar": notlar}


# ---------------------------------------------------------------------------
# 9) Devir hızı / yeterlilik günü
# ---------------------------------------------------------------------------

def devir_yeterlilik(*, bas: date, bit: date, depo: str | None = None, arama: str = "", grup_id=None,
                     bugun: date | None = None) -> dict:
    _yetki()
    if bit < bas:
        raise ValueError("Bitiş, başlangıçtan önce olamaz.")
    b = bugun or date.today()
    son = min(bit, b)
    gun = max(1, (son - bas).days + 1)
    maliyet_ok = maliyet_gorunur()
    satis = satis_ozeti(bas, bit, {"depo": depo} if depo else None)
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = _kartlar(s, arama, grup_id)
        kod_kart = {k.stok_kodu: k for k in kartlar}
        lotlar = _lot_bakiyeleri(s)
        _a, sat, _c = _bekleyenler(s, kod_kart)
        ortalamalar = (_ortalama_degerler(_gunluk_seriler(s, bas, son, depo, depolar, {k.id for k in kartlar}),
                                          bas, son, FIFO, {k.id: k for k in kartlar}, None, b)
                       if maliyet_ok else {})
    mevcut_u, bs_u = _urun_toplami(lotlar, depolar, depo), _kod_toplami(sat, depo)
    satirlar = []
    for k in kartlar:
        t = satis.get(k.stok_kodu)
        mevcut = mevcut_u.get(k.id, SIFIR)
        if t is None and mevcut == 0:
            continue
        bs = bs_u.get(k.stok_kodu, SIFIR)
        kullanilabilir = mevcut - bs
        net_m = t["net_miktar"] if t else SIFIR
        hiz = net_m / gun if net_m is not None and net_m > 0 else None
        yeterlilik = int(kullanilabilir / hiz) if hiz and kullanilabilir > 0 else None
        cogs = t["maliyet"] if t else SIFIR
        eksik = t["eksik_satir"] if t else 0
        o = ortalamalar.get(k.id) or {"ort": SIFIR, "eksik": ""}
        ort = o["ort"]
        devir = kalma = None
        notlar = []
        if t is not None and net_m is None:
            notlar.append("Birim çevrimi yok — hız hesaplanamadı")
        elif hiz is None:
            notlar.append("Satış hızı 0 veya negatif — yeterlilik günü hesaplanmaz")
        if not maliyet_ok:
            pass
        elif eksik:
            notlar.append(f"Veri yetersiz: {eksik} satış satırında maliyet eksik — devir oranı verilmez")
        elif ort is None:
            notlar.append(f"Veri yetersiz: {o['eksik']} — ortalama stok değeri kesin değil")
        elif ort <= 0:
            notlar.append("Veri yetersiz: ortalama stok değeri 0")
        elif cogs <= 0:
            notlar.append("Dönemde satış maliyeti yok")
        else:
            devir = (cogs / ort).quantize(Decimal("0.01"))
            kalma = (Decimal(gun) / devir).quantize(Decimal("0.1")) if devir > 0 else None
        satirlar.append({"stok_id": k.id, "urun_kodu": k.stok_kodu, "urun_adi": k.stok_adi,
                         "birim": k.birim or "Adet", "net_satis_miktari": net_m,
                         "gunluk_hiz": hiz.quantize(Decimal("0.001")) if hiz else None,
                         "mevcut": mevcut, "kullanilabilir": kullanilabilir, "yeterlilik_gun": yeterlilik,
                         "satis_maliyeti": _q2(cogs) if maliyet_ok else None,
                         "ort_stok_degeri": _q2(ort) if maliyet_ok and ort is not None else None,
                         "devir_orani": devir, "stokta_kalma_gun": kalma, "aciklama": "; ".join(notlar)})
    satirlar.sort(key=lambda r: (r["devir_orani"] is None, -(r["devir_orani"] or 0), r["urun_kodu"]))
    notlar = [
        f"Günlük hız = dönem net satış miktarı / {gun} gün ({bas:%d.%m.%Y}–{son:%d.%m.%Y}). Satış iadeleri düşülür; "
        "depo transferi ve alış iadesi satış sayılmaz. Hesap satış yönetici raporlarıyla ortaktır.",
        "Yeterlilik günü = kullanılabilir stok (mevcut − bekleyen müşteri siparişi) / günlük hız; hız 0 veya "
        "negatifse gösterilmez.",
        f"Devir oranı = dönem satış maliyeti (iadeler düşülmüş) / ortalama stok değeri. Ortalama stok değeri "
        f"{gun} günün her birinin gün sonu FIFO stok değerinin ortalamasıdır (Stok Yatırım Verimliliği raporuyla "
        "aynı hesap). Stokta kalma günü = dönem günü / devir oranı.",
        "Maliyeti eksik satışı veya maliyetsiz stok katmanı olan ya da ortalama stok değeri sıfır olan ürünlerde "
        "devir oranı kesin olmadığından verilmez.",
        REZERVASYON_NOTU, SALT_OKUNUR_NOTU,
    ]
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından maliyet ve devir oranı sütunları gösterilmez.")
    return {"satirlar": satirlar, "gun": gun, "notlar": notlar}


# ---------------------------------------------------------------------------
# 10) Sayım farkları
# ---------------------------------------------------------------------------

def sayim_farklari(*, bas: date | None = None, bit: date | None = None, depo: str | None = None, arama: str = "",
                   sadece_farkli: bool = True) -> dict:
    from database.models.stok_sayim import StokSayimFisi, StokSayimSatiri

    _yetki()
    maliyet_ok = maliyet_gorunur()
    hedef = turkce_normalize((arama or "").strip())
    satirlar = []
    with get_session() as s:
        if not _tablo_var(s, StokSayimFisi.__tablename__):
            return {"satirlar": [], "notlar": ["Bu firmada henüz stok sayımı yapılmamış."]}
        q = (select(StokSayimSatiri, StokSayimFisi, StokKarti, Depo.ad)
             .join(StokSayimFisi, StokSayimFisi.id == StokSayimSatiri.fis_id)
             .join(StokKarti, StokKarti.id == StokSayimSatiri.stok_id)
             .join(Depo, Depo.id == StokSayimFisi.depo_id))
        if bas:
            q = q.where(StokSayimFisi.fis_tarihi >= bas)
        if bit:
            q = q.where(StokSayimFisi.fis_tarihi <= bit)
        if depo:
            q = q.where(Depo.ad == depo)
        kayitlar = s.execute(q.order_by(StokSayimFisi.fis_tarihi, StokSayimFisi.id, StokSayimSatiri.id)).all()
        nolar = sorted({f.fis_no for _s, f, _k, _d0 in kayitlar})
        duzeltme: dict[tuple[str, int], dict] = {}
        for i in range(0, len(nolar), 500):
            for belge, sid, tur, m, c in s.execute(
                    select(StokHareketi.belge_no, StokHareketi.stok_id, StokHareketi.hareket_turu,
                           StokHareketi.miktar, StokHareketi.birim_maliyet)
                    .where(StokHareketi.belge_no.in_(nolar[i:i + 500]),
                           StokHareketi.hareket_turu.in_(("SAYIM GİRİŞ", "SAYIM ÇIKIŞ")))).all():
                d = duzeltme.setdefault((belge, int(sid)), {"miktar": SIFIR, "tutar": SIFIR, "turler": set()})
                isaret = 1 if tur == "SAYIM GİRİŞ" else -1
                d["miktar"] += isaret * _d(m)
                d["tutar"] += isaret * _d(m) * _d(c)
                d["turler"].add(tur)
        for satir, fis, kart, depo_adi in kayitlar:
            fark = _d(satir.fark)
            if sadece_farkli and fark == 0:
                continue
            if hedef and hedef not in turkce_normalize(kart.stok_kodu or "") and hedef not in turkce_normalize(
                    kart.stok_adi or ""):
                continue
            d = duzeltme.get((fis.fis_no, int(kart.id)))
            sonraki = s.execute(
                select(StokHareketi.hareket_turu, StokHareketi.miktar)
                .where(StokHareketi.stok_id == kart.id, StokHareketi.depo_id == fis.depo_id,
                       StokHareketi.olusturma_tarihi > fis.olusturma_tarihi,
                       StokHareketi.belge_no != fis.fis_no)).all()
            net = sum(((_d(m) if t in GIRIS else -_d(m)) for t, m in sonraki), SIFIR)
            if fark != 0 and d is None:
                bagli = "Düzeltme hareketi yok"
            elif d is None:
                bagli = ""
            else:
                bagli = f"{fis.fis_no} ({', '.join(sorted(d['turler']))})"
            satirlar.append({
                "fis_id": fis.id, "tarih": fis.fis_tarihi, "fis_no": fis.fis_no, "depo": depo_adi,
                "urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi, "birim": kart.birim or "Adet",
                "sistem": _d(satir.sistem_miktar), "sayilan": _d(satir.sayilan_miktar), "fark": fark,
                "eksik_fazla": "Fazla" if fark > 0 else ("Eksik" if fark < 0 else "Tam"),
                "maliyet_farki": _q2(d["tutar"]) if (d and maliyet_ok) else None,
                "durum": fis.durum, "onaylayan": "Kayıtlı değil", "bagli_evrak": bagli,
                "sonraki": f"Sayımdan sonra {len(sonraki)} hareket (net {net.normalize():f})" if sonraki else "",
                "neden": satir.fark_nedeni or "",
            })
    fazla = sum((_d(r["maliyet_farki"]) for r in satirlar if r["fark"] > 0), SIFIR)
    eksik = sum((_d(r["maliyet_farki"]) for r in satirlar if r["fark"] < 0), SIFIR)
    notlar = [
        "Sistem miktarı sayımın kaydedildiği andaki depo bakiyesidir; sayımdan sonra oluşan hareketler 'Sonraki "
        "hareketler' sütununda ayrıca gösterilir ve farka karışmaz.",
        "Maliyet farkı, sayım fişinin oluşturduğu SAYIM GİRİŞ / SAYIM ÇIKIŞ hareketlerinin tutarıdır.",
        "Sayım fişlerinde onaylayan kullanıcı alanı tutulmuyor ('Kayıtlı değil').",
        "Rapor düzeltme fişi oluşturmaz. " + SALT_OKUNUR_NOTU,
    ]
    if not maliyet_ok:
        notlar.append("Maliyet görme yetkiniz olmadığından maliyet farkı gösterilmez.")
    return {"satirlar": satirlar, "fazla_tutar": _q2(fazla) if maliyet_ok else None,
            "eksik_tutar": _q2(eksik) if maliyet_ok else None, "notlar": notlar}


# ---------------------------------------------------------------------------
# 11) Depo transfer takibi
# ---------------------------------------------------------------------------

def transfer_takibi(*, bas: date | None = None, bit: date | None = None, depo: str | None = None, arama: str = "",
                    bugun: date | None = None) -> dict:
    _yetki()
    b = bugun or date.today()
    hedef = turkce_normalize((arama or "").strip())
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        q = select(DepoTransferFisi).options(selectinload(DepoTransferFisi.satirlar))
        if bas:
            q = q.where(DepoTransferFisi.fis_tarihi >= bas)
        if bit:
            q = q.where(DepoTransferFisi.fis_tarihi <= bit)
        fisler = [f for f in s.scalars(q.order_by(DepoTransferFisi.fis_tarihi, DepoTransferFisi.id)).all()
                  if not depo or depo in (f.cikis_depo, f.giris_depo)]
        nolar = [f.fis_no for f in fisler]
        har: dict[tuple[str, int, str, str], Decimal] = defaultdict(lambda: SIFIR)
        for i in range(0, len(nolar), 500):
            for belge, sid, did, tur, m in s.execute(
                    select(StokHareketi.belge_no, StokHareketi.stok_id, StokHareketi.depo_id,
                           StokHareketi.hareket_turu, func.sum(StokHareketi.miktar))
                    .where(StokHareketi.belge_no.in_(nolar[i:i + 500]), StokHareketi.hareket_turu.in_(TRANSFER))
                    .group_by(StokHareketi.belge_no, StokHareketi.stok_id, StokHareketi.depo_id,
                              StokHareketi.hareket_turu)).all():
                har[(belge, int(sid), depolar.get(int(did), ""), tur)] += _d(m)
        kod_kart = {k.stok_kodu: k for k in s.scalars(
            select(StokKarti).options(selectinload(StokKarti.birimler))).all()}
        satirlar = []
        for f in fisler:
            urunler: dict[str, dict] = {}
            for st in f.satirlar:
                u = urunler.setdefault(st.urun_kodu, {"urun_adi": st.urun_adi, "birim": st.birim, "fis_miktari": SIFIR,
                                                      "fis_temel": SIFIR, "cevrimsiz": False})
                u["fis_miktari"] += _d(st.miktar)
                c = _carpan(kod_kart.get(st.urun_kodu), st.birim)
                u["cevrimsiz"] |= c is None
                u["fis_temel"] += _d(st.miktar) * (c or Decimal("1"))
            for kod, u in urunler.items():
                if hedef and hedef not in turkce_normalize(kod) and hedef not in turkce_normalize(u["urun_adi"] or ""):
                    continue
                kart = kod_kart.get(kod)
                sid = kart.id if kart else -1
                gonderilen = har.get((f.fis_no, sid, f.cikis_depo, "TRANSFER ÇIKIŞ"), SIFIR)
                alinan = har.get((f.fis_no, sid, f.giris_depo, "TRANSFER GİRİŞ"), SIFIR)
                yoldaki = gonderilen - alinan
                if gonderilen == 0 and alinan == 0:
                    durum = "İptal / stok hareketi yok"
                elif yoldaki > ESIK:
                    durum = "Kısmi — yolda"
                elif yoldaki < -ESIK:
                    durum = "Uyumsuz: alınan gönderilenden fazla"
                elif abs(gonderilen - u["fis_temel"]) > ESIK:
                    durum = "Uyumsuz: fiş miktarından farklı"
                else:
                    durum = "Tamamlandı"
                satirlar.append({"fis_id": f.id, "tarih": f.fis_tarihi, "fis_no": f.fis_no, "kaynak": f.cikis_depo,
                                 "hedef": f.giris_depo, "urun_kodu": kod, "urun_adi": u["urun_adi"],
                                 "birim": (kart.birim if kart else u["birim"]) or "Adet",
                                 "fis_miktari": u["fis_temel"], "gonderilen": gonderilen, "alinan": alinan,
                                 "yoldaki": yoldaki, "bekleme_gun": (b - f.fis_tarihi).days if yoldaki > ESIK else 0,
                                 "durum": durum,
                                 "aciklama": "Fiş birimi çevrilemedi (1 kabul edildi)" if u["cevrimsiz"] else ""})
    notlar = [
        "Gönderilen = kaynak depodaki TRANSFER ÇIKIŞ, alınan = hedef depodaki TRANSFER GİRİŞ hareketleri (temel birim).",
        TRANSIT_NOTU,
        "Stok hareketi bulunmayan fişler 'İptal / stok hareketi yok' olarak gösterilir.",
        "Rapor yeni stok hareketi oluşturmaz. " + SALT_OKUNUR_NOTU,
    ]
    return {"satirlar": satirlar, "notlar": notlar}


# ---------------------------------------------------------------------------
# 12) Tutarlılık kontrolü (salt okunur)
# ---------------------------------------------------------------------------

ONEM_SIRA = {"Yüksek": 0, "Orta": 1, "Düşük": 2}


def _belge_nolari(session, model, alan: str, *kosul) -> set[str]:
    return {n for (n,) in session.execute(select(getattr(model, alan)).where(*kosul)).all() if n}


def tutarlilik_kontrolu(*, onem: str | None = None, hata_turu: str | None = None) -> dict:
    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
    from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri
    from database.models.satis_irsaliyesi import SatisIrsaliyesi

    _yetki()
    sorunlar: list[dict] = []

    def ekle(tur, derece, urun="", depo_ad="", belge="", aciklama="", oneri=""):
        sorunlar.append({"hata_turu": tur, "onem": derece, "urun": urun, "depo": depo_ad, "belge": belge,
                         "aciklama": aciklama, "oneri": oneri})

    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        kartlar = {k.id: k for k in s.scalars(select(StokKarti).options(selectinload(StokKarti.birimler))).all()}
        kod_kart = {k.stok_kodu: k for k in kartlar.values()}

        def ad(sid):
            k = kartlar.get(int(sid))
            return f"{k.stok_kodu} — {k.stok_adi}" if k else f"#{sid}"

        # Negatif stok ve lot / hareket bakiyesi
        lot_b = _lot_bakiyeleri(s)
        har_b: dict[tuple[int, int], Decimal] = defaultdict(lambda: SIFIR)
        for sid, did, tur, m in s.execute(
                select(StokHareketi.stok_id, StokHareketi.depo_id, StokHareketi.hareket_turu,
                       func.sum(StokHareketi.miktar))
                .group_by(StokHareketi.stok_id, StokHareketi.depo_id, StokHareketi.hareket_turu)).all():
            if tur in GIRIS:
                har_b[(int(sid), int(did))] += _d(m)
            elif tur in CIKIS:
                har_b[(int(sid), int(did))] -= _d(m)
        for key in sorted(set(lot_b) | set(har_b)):
            lm, hm = lot_b.get(key, SIFIR), har_b.get(key, SIFIR)
            if lm < 0 or hm < -ESIK:
                ekle("Negatif stok", "Yüksek", ad(key[0]), depolar.get(key[1], ""), "",
                     f"Depo bakiyesi negatif (lot {lm.normalize():f}, hareket {hm.normalize():f}).",
                     "Ürün ekstresinde negatife düştüğü tarihi ve eksik giriş belgesini inceleyin.")
            if abs(lm - hm) > ESIK:
                ekle("Lot ve hareket bakiyesi farklı", "Orta", ad(key[0]), depolar.get(key[1], ""), "",
                     f"Lot kalanı {lm.normalize():f}, hareketlerden hesaplanan {hm.normalize():f}.",
                     "Lotlu olmayan veya silinmiş belgeye ait hareketleri inceleyin.")
        # Eksik maliyet
        for lot in s.scalars(select(StokLotu).where(StokLotu.kalan_miktar > 0, StokLotu.birim_maliyet <= 0)).all():
            ekle("Eksik maliyet", "Orta", ad(lot.stok_id), depolar.get(int(lot.depo_id), ""), lot.lot_no,
                 f"Açık stok katmanında {_d(lot.kalan_miktar).normalize():f} birim maliyetsiz.",
                 "Giriş belgesinin fiyatını veya sayım/aktarım maliyetini kontrol edin.")
        # Geçersiz birim dönüşümü
        ciftler: dict[tuple[str, str], str] = {}
        for model, baslik in ((SatisFaturasiSatiri, "Satış faturası"), (AlisFaturasiSatiri, "Alış faturası"),
                              (SatisIadeFaturasiSatiri, "Satış iadesi"), (AlisIadeFaturasiSatiri, "Alış iadesi")):
            for kod, birim in s.execute(select(model.urun_kodu, model.birim).where(model.birim_carpani.is_(None))
                                        .distinct()).all():
                ciftler.setdefault(((kod or "").strip(), birim or ""), baslik)
        for (kod, birim), baslik in sorted(ciftler.items()):
            kart = kod_kart.get(kod)
            if kart is None or _hizmet(kart):
                continue
            if _carpan(kart, birim) is None:
                ekle("Geçersiz birim dönüşümü", "Orta", f"{kart.stok_kodu} — {kart.stok_adi}", "", baslik,
                     f"'{birim}' biriminin temel birime ({kart.birim}) çevrimi stok kartında tanımlı değil.",
                     "Stok kartı → Barkod & Birimler → Alternatif Birimler bölümünde çarpanı tanımlayın.")
        # Mükerrer barkod / stok kodu
        barkodlar: dict[str, set[int]] = defaultdict(set)
        for sid, bk in s.execute(select(StokKarti.id, StokKarti.barkod).where(StokKarti.barkod.is_not(None))).all():
            barkodlar[bk.strip()].add(int(sid))
        for sid, bk in s.execute(select(StokBarkod.stok_id, StokBarkod.barkod)).all():
            barkodlar[(bk or "").strip()].add(int(sid))
        for sid, bk in s.execute(select(StokBirim.stok_id, StokBirim.birim_barkod)
                                 .where(StokBirim.birim_barkod.is_not(None))).all():
            barkodlar[bk.strip()].add(int(sid))
        for bk, idler in sorted(barkodlar.items()):
            if bk and len(idler) > 1:
                ekle("Mükerrer barkod", "Yüksek", ", ".join(ad(i) for i in sorted(idler)), "", bk,
                     f"Aynı barkod {len(idler)} farklı stok kartında kayıtlı.",
                     "Barkodun hangi ürüne ait olduğunu belirleyip diğer karttan kaldırın.")
        kodlar: dict[str, list[StokKarti]] = defaultdict(list)
        for k in kartlar.values():
            kodlar[turkce_normalize((k.stok_kodu or "").strip())].append(k)
        for _n, liste in sorted(kodlar.items()):
            if len(liste) > 1:
                ekle("Mükerrer stok kodu", "Orta", ", ".join(f"{k.stok_kodu} — {k.stok_adi}" for k in liste), "", "",
                     "Büyük/küçük harf veya boşluk farkıyla aynı stok kodu birden çok kartta.",
                     "Kartları karşılaştırın; gerekirse Stok Birleştir ile güvenli birleştirin.")
        # Kaynak evrak ↔ hareket miktarı / depo
        hareketler: dict[tuple[str, str, int], dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: SIFIR))
        tum_hareket = s.execute(select(StokHareketi.id, StokHareketi.hareket_turu, StokHareketi.belge_no,
                                       StokHareketi.stok_id, StokHareketi.depo_id, StokHareketi.miktar,
                                       StokHareketi.tarih, StokHareketi.lot_id, StokHareketi.birim_maliyet)).all()
        for _hid, tur, belge, sid, did, m, *_r in tum_hareket:
            hareketler[(tur, belge, int(sid))][depolar.get(int(did), "")] += _d(m)

        def gercek(turler, belge, sid) -> dict[str, Decimal]:
            out: dict[str, Decimal] = defaultdict(lambda: SIFIR)
            for t in turler:
                for dp, m in hareketler.get((t, belge, sid), {}).items():
                    out[dp] += m
            return out

        def karsilastir(baslik, belge, belge_depo, beklenen: dict[int, tuple[Decimal, Decimal]], turler):
            for sid, (en_az, en_cok) in beklenen.items():
                g = gercek(turler, belge, sid)
                toplam = sum(g.values(), SIFIR)
                if toplam < en_az - ESIK or toplam > en_cok + ESIK:
                    bek = f"{en_az.normalize():f}" if en_az == en_cok else f"{en_az.normalize():f}–{en_cok.normalize():f}"
                    ekle("Belge ile hareket miktarı farklı", "Yüksek", ad(sid), belge_depo, f"{baslik} {belge}",
                         f"Belgeye göre beklenen {bek}, stok hareketi {toplam.normalize():f} (temel birim).",
                         "Belgeyi açıp stok etkisini ürün ekstresiyle karşılaştırın.")
                yanlis = [dp for dp, m in g.items() if m and dp != belge_depo]
                if yanlis:
                    ekle("Belge ile hareket deposu farklı", "Orta", ad(sid), ", ".join(yanlis), f"{baslik} {belge}",
                         f"Belge deposu {belge_depo}, hareket deposu {', '.join(yanlis)}.",
                         "Belgedeki depo ile stok hareketinin deposunu kontrol edin.")

        def satir_temel(satir) -> tuple[int | None, Decimal | None]:
            kart = kod_kart.get((satir.urun_kodu or "").strip())
            if kart is None or _hizmet(kart):
                return None, None
            c = _carpan(kart, satir.birim, getattr(satir, "birim_carpani", None))
            return kart.id, (_d(satir.miktar) * c if c is not None else None)

        iptal_nolari: dict[str, set[str]] = defaultdict(set)
        for f in s.scalars(select(SatisFaturasi).options(selectinload(SatisFaturasi.satirlar))).all():
            if f.durum == "İPTAL" or f.is_deleted:
                iptal_nolari["FATURA ÇIKIŞ"].add(f.fatura_no)
                continue
            bek: dict[int, list[Decimal]] = defaultdict(lambda: [SIFIR, SIFIR])
            for st in f.satirlar:
                sid, q = satir_temel(st)
                if sid is None or q is None:
                    continue
                if not f.onaylandi:
                    continue
                if not st.irsaliye_satiri_id:
                    bek[sid][0] += q
                bek[sid][1] += q
            if not f.onaylandi:
                for st in f.satirlar:
                    sid, _q = satir_temel(st)
                    if sid is not None:
                        bek.setdefault(sid, [SIFIR, SIFIR])
            karsilastir("Satış faturası", f.fatura_no, f.depo, {k: tuple(v) for k, v in bek.items()}, ("FATURA ÇIKIŞ",))
        alis_iade_nolari = _belge_nolari(s, AlisIadeFaturasi, "iade_no")
        for f in s.scalars(select(AlisFaturasi).options(selectinload(AlisFaturasi.satirlar))).all():
            if f.durum == "İPTAL" or getattr(f, "is_deleted", False):
                iptal_nolari["FATURA GİRİŞ"].add(f.fatura_no)
                continue
            bek = defaultdict(lambda: [SIFIR, SIFIR])
            for st in f.satirlar:
                sid, q = satir_temel(st)
                if sid is not None and q is not None:
                    bek[sid][0] += q
                    bek[sid][1] += q
            karsilastir("Alış faturası", f.fatura_no, f.depo, {k: tuple(v) for k, v in bek.items()}, ("FATURA GİRİŞ",))
        for model, baslik, turler, anahtar in (
                (SatisIadeFaturasi, "Satış iadesi", ("İADE GİRİŞ", "İRSALİYE İADE GİRİŞ"), "İADE GİRİŞ"),
                (AlisIadeFaturasi, "Alış iadesi", ("ALIŞ İADE ÇIKIŞ", "FATURA ÇIKIŞ"), "ALIŞ İADE ÇIKIŞ")):
            for f in s.scalars(select(model).options(selectinload(model.satirlar))).all():
                if f.durum == "İPTAL" or getattr(f, "is_deleted", False):
                    for t in turler:
                        iptal_nolari[t].add(f.iade_no)
                    continue
                if f.durum == "TASLAK":
                    continue
                bek = defaultdict(lambda: [SIFIR, SIFIR])
                for st in f.satirlar:
                    sid, q = satir_temel(st)
                    if sid is not None and q is not None:
                        bek[sid][0] += q
                        bek[sid][1] += q
                karsilastir(baslik, f.iade_no, f.depo, {k: tuple(v) for k, v in bek.items()}, turler)
        # İptal / silinmiş evrak kalıntısı
        iptal_nolari["FATURA ÇIKIŞ"] -= alis_iade_nolari - iptal_nolari["ALIŞ İADE ÇIKIŞ"]
        goruldu: set[tuple[str, str, int]] = set()
        for _hid, tur, belge, sid, did, m, *_r in tum_hareket:
            if belge in iptal_nolari.get(tur, ()) and (tur, belge, int(sid)) not in goruldu:
                goruldu.add((tur, belge, int(sid)))
                ekle("İptal belgeden kalan stok etkisi", "Yüksek", ad(sid), depolar.get(int(did), ""), belge,
                     f"İptal edilmiş/silinmiş belgenin {tur} hareketi duruyor.",
                     "Belge iptalinde stok geri alınmamış olabilir; ürün ekstresiyle doğrulayın.")
        # Kaynağı bulunamayan hareket
        kaynaklar: dict[str, set[str]] = {
            "FATURA ÇIKIŞ": _belge_nolari(s, SatisFaturasi, "fatura_no") | alis_iade_nolari,
            "FATURA GİRİŞ": _belge_nolari(s, AlisFaturasi, "fatura_no"),
            "İADE GİRİŞ": _belge_nolari(s, SatisIadeFaturasi, "iade_no"),
            "ALIŞ İADE ÇIKIŞ": alis_iade_nolari,
            "İRSALİYE ÇIKIŞ": _belge_nolari(s, SatisIrsaliyesi, "irsaliye_no"),
            "İRSALİYE İADE GİRİŞ": _belge_nolari(s, SatisIrsaliyesi, "irsaliye_no"),
            "TRANSFER ÇIKIŞ": _belge_nolari(s, DepoTransferFisi, "fis_no"),
            "TRANSFER GİRİŞ": _belge_nolari(s, DepoTransferFisi, "fis_no"),
        }
        try:
            from database.models.stok_sayim import StokSayimFisi

            if _tablo_var(s, StokSayimFisi.__tablename__):
                kaynaklar["SAYIM GİRİŞ"] = kaynaklar["SAYIM ÇIKIŞ"] = _belge_nolari(s, StokSayimFisi, "fis_no")
        except Exception:  # noqa: BLE001
            pass
        try:
            from database.models.stok import StokPaketUretim

            if _tablo_var(s, StokPaketUretim.__tablename__):
                kaynaklar["PAKET GİRİŞ"] = kaynaklar["PAKET ÇIKIŞ"] = _belge_nolari(s, StokPaketUretim, "fis_no")
        except Exception:  # noqa: BLE001
            pass
        goruldu = set()
        for _hid, tur, belge, sid, did, m, *_r in tum_hareket:
            bilinen = kaynaklar.get(tur)
            if bilinen is None or belge in bilinen or (tur, belge) in goruldu:
                continue
            goruldu.add((tur, belge))
            ekle("Kaynağı bulunamayan hareket", "Yüksek", ad(sid), depolar.get(int(did), ""), belge,
                 f"{tur} hareketinin kaynak belgesi ({belge}) bulunamadı.",
                 "Belge silinmiş veya numarası değişmiş olabilir; hareketin hangi işlemden geldiğini inceleyin.")
        # Olası mükerrer hareket
        sayac: dict[tuple, int] = defaultdict(int)
        for _hid, tur, belge, sid, did, m, t, lot_id, c in tum_hareket:
            sayac[(tur, belge, int(sid), int(did), lot_id, _d(m), _d(c), t)] += 1
        for (tur, belge, sid, did, _l, m, _c, t), n in sayac.items():
            if n > 1:
                ekle("Olası mükerrer hareket", "Düşük", ad(sid), depolar.get(did, ""), belge,
                     f"{t:%d.%m.%Y} {tur} hareketi aynı lot ve miktarla ({m.normalize():f}) {n} kez kayıtlı.",
                     "Belgede aynı ürün birden çok satırda olabilir; değilse mükerrer kaydı inceleyin.")
    if onem:
        sorunlar = [r for r in sorunlar if r["onem"] == onem]
    if hata_turu:
        sorunlar = [r for r in sorunlar if r["hata_turu"] == hata_turu]
    sorunlar.sort(key=lambda r: (ONEM_SIRA.get(r["onem"], 3), r["hata_turu"], r["urun"], r["belge"]))
    ozet: dict[str, int] = defaultdict(int)
    for r in sorunlar:
        ozet[r["hata_turu"]] += 1
    notlar = [
        "Kontrol yalnız okuma yapar; hiçbir kaydı silmez, düzeltmez veya yeniden hesaplamaz.",
        "Stok etkisi gerekmeyen belgeler hata sayılmaz: hizmet kartları, onaylanmamış/taslak belgeler, irsaliyeden "
        "stok düşülmüş fatura satırları ve manuel stok giriş/çıkış fişleri (kaynak tablosu tutulmaz).",
        "Satış faturasında irsaliyeye bağlı satırlar stok düşmeyebilir; beklenen miktar bu durumda aralık olarak verilir.",
        "Olası mükerrer hareket bir uyarıdır; aynı ürünün belgede birden çok satırda olması normaldir.",
    ]
    return {"satirlar": sorunlar, "ozet": [{"hata_turu": k, "adet": v} for k, v in sorted(ozet.items())],
            "notlar": notlar}


def hata_turleri() -> list[str]:
    return ["Negatif stok", "Lot ve hareket bakiyesi farklı", "Eksik maliyet", "Geçersiz birim dönüşümü",
            "Mükerrer barkod", "Mükerrer stok kodu", "Belge ile hareket miktarı farklı",
            "Belge ile hareket deposu farklı", "İptal belgeden kalan stok etkisi", "Kaynağı bulunamayan hareket",
            "Olası mükerrer hareket"]


def depo_adlari() -> list[str]:
    with get_session() as s:
        return [d.ad for d in s.scalars(select(Depo).order_by(Depo.ad)).all()]


def grup_secenekleri(seviye: int | None = None) -> list[tuple[str, str]]:
    from database.models.stok import StokGrubu

    with get_session() as s:
        try:
            q = select(StokGrubu).where(StokGrubu.aktif.is_(True))
            if seviye:
                q = q.where(StokGrubu.seviye == int(seviye))
            gruplar = s.scalars(q.order_by(StokGrubu.seviye, StokGrubu.ad)).all()
        except Exception:  # noqa: BLE001
            return []
        if seviye:
            return [(str(g.id), g.ad or "") for g in gruplar]
        return [(str(g.id), ("  " * (int(g.seviye or 1) - 1)) + (g.ad or "")) for g in gruplar]


# ---------------------------------------------------------------------------
# Günlük kapanış stok değeri (devir hızı ve yatırım verimliliği ortak)
# ---------------------------------------------------------------------------

_GIRIS_T = frozenset(GIRIS_HAREKETLERI)
_CIKIS_T = frozenset(CIKIS_HAREKETLERI)


def _gun(t) -> date:
    return t.date() if isinstance(t, datetime) else t


def _pencere_toplami(acilis: Decimal, deltalar: dict[date, Decimal], bas: date, son: date) -> Decimal:
    """Σ_{t=bas..son} (açılış + t gününe kadarki değişimler) — günlük kapanışların toplamı."""
    if son < bas:
        return SIFIR
    toplam = acilis * ((son - bas).days + 1)
    for d, x in deltalar.items():
        if d <= son:
            toplam += x * ((son - d).days + 1)
    return toplam


def _tarihte(acilis: Decimal, deltalar: dict[date, Decimal], t: date) -> Decimal:
    return acilis + sum((x for d, x in deltalar.items() if d <= t), SIFIR)


def _kosullu_gun(acilis: Decimal, deltalar: dict[date, Decimal], bas: date, son: date, kosul) -> int:
    """Gün sonu bakiyesi ``kosul``u sağlayan gün sayısı."""
    gun, q, onceki = 0, acilis, bas
    for d in sorted(deltalar):
        if d > son:
            break
        if kosul(q):
            gun += (d - onceki).days
        q += deltalar[d]
        onceki = d
    if kosul(q):
        gun += (son - onceki).days + 1
    return gun


class _Seri:
    """Bir ürünün (depo filtresine uyan) dönem başı bakiyesi ve dönem içi günlük değişimleri."""

    __slots__ = ("acilis_q", "acilis_v", "acilis_q0", "dq", "dv", "dq0", "gunler")

    def __init__(self):
        self.acilis_q = self.acilis_v = self.acilis_q0 = SIFIR
        self.dq: dict[date, Decimal] = {}
        self.dv: dict[date, Decimal] = {}
        self.dq0: dict[date, Decimal] = {}
        self.gunler: set[date] = set()  # tüm depolardaki hareket günleri (ortalama maliyetin değiştiği günler)


def _masraf_paylari(session, bas: date) -> list[tuple[int, Decimal, date]]:
    """(lot, birim pay, dağıtım tarihi): ``fifo_envanter_degerleri`` ile aynı geriye dönük masraf düzeltmesi."""
    try:
        from database.masraf_dagitim_service import DURUM_ONAYLANDI, MasrafDagitimService, _q4
        from database.models.masraf_dagitim import MasrafDagitim

        dagitimlar = session.scalars(
            select(MasrafDagitim)
            .where(MasrafDagitim.durum == DURUM_ONAYLANDI, MasrafDagitim.dagitim_tarihi >= bas)
            .options(selectinload(MasrafDagitim.satirlar))).all()
    except Exception:  # noqa: BLE001 — eski/kısmi şemada masraf tablosu olmayabilir
        return []
    out = []
    for d in dagitimlar:
        for s in d.satirlar:
            ana = _d(s.ana_miktar)
            if not s.lot_id or ana <= 0:
                continue
            e_kok = _d(s.pay) / ana
            lotlar: dict[int, Decimal] = {}
            MasrafDagitimService._lot_izi(session, int(s.lot_id), Decimal("1"), set(), lotlar, [])
            for lot_id, carpan in lotlar.items():
                out.append((int(lot_id), _q4(e_kok * carpan), _gun(d.dagitim_tarihi)))
    return out


def _gunluk_seriler(session, bas: date, son: date, depo: str | None, depolar: dict[int, str],
                    sidler: set[int] | None = None) -> dict:
    """Tek sorguyla bütün ürünlerin hareket serileri (ürün başına ayrı sorgu yok)."""
    lot_maliyet: dict[int, Decimal] = {}
    devir_lotlari: list = []
    for lot in session.scalars(select(StokLotu)).all():
        lot_maliyet[int(lot.id)] = _d(lot.birim_maliyet)
        if devir_lotu_mu(lot):
            devir_lotlari.append(lot)
    masraf = _masraf_paylari(session, bas)
    masraf_lotlari = {lot for lot, _e, _t in masraf}
    seriler: dict[int, _Seri] = {}
    lot_seri: dict[int, list] = {}
    ilk_tarih: date | None = None
    for sid, did, t, tur, m, b, lot_id in session.execute(
            select(StokHareketi.stok_id, StokHareketi.depo_id, StokHareketi.tarih, StokHareketi.hareket_turu,
                   StokHareketi.miktar, StokHareketi.birim_maliyet, StokHareketi.lot_id)
            .where(StokHareketi.tarih <= son)).all():
        if tur in _GIRIS_T:
            isaret = 1
        elif tur in _CIKIS_T:
            isaret = -1
        else:
            continue
        sid = int(sid)
        if sidler is not None and sid not in sidler:
            continue
        t = _gun(t)
        if ilk_tarih is None or t < ilk_tarih:
            ilk_tarih = t
        s = seriler.get(sid)
        if s is None:
            s = seriler[sid] = _Seri()
        if t >= bas:
            s.gunler.add(t)
        if not _depo_eslesir(depolar.get(int(did)), depo):
            continue
        q = _d(m) * isaret
        v = q * _d(b)
        if lot_id:
            maliyetsiz = lot_maliyet.get(int(lot_id), _d(b)) <= 0
        else:
            maliyetsiz = isaret > 0 and _d(b) <= 0
        q0 = q if maliyetsiz else SIFIR
        if t < bas:
            s.acilis_q += q
            s.acilis_v += v
            s.acilis_q0 += q0
        else:
            s.dq[t] = s.dq.get(t, SIFIR) + q
            s.dv[t] = s.dv.get(t, SIFIR) + v
            if q0:
                s.dq0[t] = s.dq0.get(t, SIFIR) + q0
        if lot_id and int(lot_id) in masraf_lotlari:
            ls = lot_seri.setdefault(int(lot_id), [sid, SIFIR, {}])
            if t < bas:
                ls[1] += q
            else:
                ls[2][t] = ls[2].get(t, SIFIR) + q
    return {"seriler": seriler, "masraf": masraf, "lot_seri": lot_seri, "ilk_tarih": ilk_tarih,
            "devir_lotlari": [l for l in devir_lotlari if _depo_eslesir(depolar.get(int(l.depo_id)), depo)]}


def _fifo_degerleri(veri: dict, bas: date, son: date, bugun: date) -> dict[int, dict]:
    """Ürün → dönem başı / sonu FIFO değeri ve günlük kapanış değerlerinin toplamı (masraf düzeltmeli)."""
    duz_top: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    duz_bas: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    duz_son: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    once = bas - timedelta(days=1)
    for lot_id, e, d_tarih in veri["masraf"]:
        ls = veri["lot_seri"].get(lot_id)
        if ls is None:
            continue
        sid, acilis, deltalar = ls
        w = min(son, d_tarih - timedelta(days=1), bugun - timedelta(days=1))
        duz_top[sid] += e * _pencere_toplami(acilis, deltalar, bas, w)
        if d_tarih > once:
            duz_bas[sid] += e * acilis
        if d_tarih > son and son < bugun:
            duz_son[sid] += e * _tarihte(acilis, deltalar, son)
    out = {}
    for sid, s in veri["seriler"].items():
        out[sid] = {
            "bas_v": s.acilis_v - duz_bas[sid],
            "son_v": s.acilis_v + sum(s.dv.values(), SIFIR) - duz_son[sid],
            "toplam_v": _pencere_toplami(s.acilis_v, s.dv, bas, son) - duz_top[sid],
            "bas_eksik": s.acilis_q0 > ESIK,
            "son_eksik": s.acilis_q0 + sum(s.dq0.values(), SIFIR) > ESIK,
            "eksik_gun": _kosullu_gun(s.acilis_q0, s.dq0, bas, son, lambda q: q > ESIK),
        }
    return out


def _ortalama_degerler(veri: dict, bas: date, son: date, yontem: str, kartlar: dict[int, Any], motor,
                       bugun: date) -> dict[int, dict]:
    """Ürün → bas_v, son_v, ort (günlük kapanış ortalaması), eksik nedeni; yönteme göre."""
    from database.satis_maliyet_motoru import DONEMSEL

    gun = (son - bas).days + 1
    once = bas - timedelta(days=1)
    out: dict[int, dict] = {}
    if yontem == FIFO:
        for sid, f in _fifo_degerleri(veri, bas, son, bugun).items():
            eksik = "Maliyeti olmayan stok katmanı (eksik maliyet)" if f["eksik_gun"] or f["bas_eksik"] else ""
            out[sid] = {"bas_v": None if f["bas_eksik"] else f["bas_v"],
                        "son_v": None if f["son_eksik"] else f["son_v"],
                        "ort": None if eksik else f["toplam_v"] / gun, "eksik": eksik}
        return out
    ay_baslari: list[date] = []
    if yontem == DONEMSEL:
        t = date(bas.year, bas.month, 1)
        while t <= son:
            if t > bas:
                ay_baslari.append(t)
            t = date(t.year + (t.month == 12), t.month % 12 + 1, 1)
    for sid, s in veri["seriler"].items():
        kart = kartlar.get(sid)
        if kart is None:
            continue
        eksik = ""

        def deger(q, t, donem_ici=True):
            nonlocal eksik
            if q == 0:
                return SIFIR
            b, kaynak = motor.birim_maliyet(yontem, kart, t)
            if b is None:
                if donem_ici:
                    eksik = eksik or kaynak
                return None
            return q * b

        son_q = s.acilis_q + sum(s.dq.values(), SIFIR)
        bas_v, son_v = deger(s.acilis_q, once, False), deger(son_q, son)
        noktalar = sorted({bas, *ay_baslari, *(g for g in s.gunler if bas <= g <= son)})
        gunler = sorted(s.dq)
        i, q, toplam = 0, s.acilis_q, SIFIR
        for j, p in enumerate(noktalar):
            while i < len(gunler) and gunler[i] <= p:
                q += s.dq[gunler[i]]
                i += 1
            bitis = noktalar[j + 1] - timedelta(days=1) if j + 1 < len(noktalar) else son
            v = deger(q, p)
            if v is not None:
                toplam += v * ((bitis - p).days + 1)
        out[sid] = {"bas_v": bas_v, "son_v": son_v, "ort": None if eksik else toplam / gun,
                    "eksik": f"Eksik maliyet: {eksik.removeprefix('Eksik: ')}" if eksik else ""}
    return out


# ---------------------------------------------------------------------------
# 13) Stok yatırım verimliliği (GMROI)
# ---------------------------------------------------------------------------

HESAPLANAMADI = "Hesaplanamadı"
VERIMLILIK_SIRALAMA = (("brut_kar", "Brüt kâr"), ("ort_stok", "Stok yatırımı (ort. stok değeri)"),
                       ("gmroi", "GMROI"), ("devir", "Stok devir hızı"))
GRUP_SEVIYELERI = (("ana", "Ana grup"), ("tali", "Tali grup"), ("alt", "Alt grup"))
_GRUP_ALANLARI = {"ana": ("ana_grup",), "tali": ("ana_grup", "tali_grup"),
                  "alt": ("ana_grup", "tali_grup", "alt_grup")}
_ONDA = Decimal("0.1")


def verimlilik_yontemleri() -> list[tuple[str, str]]:
    """Satış maliyeti ve stok değerlemesinde tutarlı kullanılabilen yöntemler (karşılaştırma amaçlılar hariç)."""
    from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI

    return [(FIFO, "FIFO"), (HAREKETLI, "Hareketli ağırlıklı ortalama"),
            (DONEMSEL, "Dönemsel ağırlıklı ortalama (aylık)")]


def _oranlar(net: Decimal, smm: Decimal | None, kar: Decimal | None, ort: Decimal | None, gun: int,
             stok_nedeni: list[str]) -> tuple[dict, list[str]]:
    """Oranlar daima tutarlardan hesaplanır; hesaplanamayan oran 0 değil 'Hesaplanamadı' olur."""
    nedenler: list[str] = []
    r: dict[str, Any] = {}
    if kar is None:
        r["marj"] = HESAPLANAMADI
    elif net <= 0:
        r["marj"] = HESAPLANAMADI
        nedenler.append("Marj: dönemde net satış yok veya negatif")
    else:
        r["marj"] = (kar / net * 100).quantize(KURUS, rounding=ROUND_HALF_UP)
    r["devir"] = r["kalma_gun"] = r["gmroi"] = HESAPLANAMADI
    if stok_nedeni or ort is None:
        return r, nedenler
    if ort <= 0:
        nedenler.append("Ortalama stok değeri sıfır veya negatif — devir, stokta kalma ve GMROI hesaplanamaz")
        return r, nedenler
    if smm is not None:
        r["devir"] = (smm / ort).quantize(KURUS, rounding=ROUND_HALF_UP)
        if smm > 0:
            r["kalma_gun"] = (Decimal(gun) * ort / smm).quantize(_ONDA, rounding=ROUND_HALF_UP)
        else:
            nedenler.append("Stokta kalma: dönemde satış maliyeti yok, stok devretmedi")
    if kar is not None:
        r["gmroi"] = (kar / ort).quantize(KURUS, rounding=ROUND_HALF_UP)
    return r, nedenler


def _son_tarihler(session, son: date, depo: str | None) -> tuple[dict[str, date], dict[str, date]]:
    from sqlalchemy import or_

    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri

    qa = (select(AlisFaturasiSatiri.urun_kodu, func.max(AlisFaturasi.fatura_tarihi))
          .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
          .where(AlisFaturasi.durum != "İPTAL", AlisFaturasi.fatura_tarihi <= son))
    qs = (select(SatisFaturasiSatiri.urun_kodu, func.max(SatisFaturasi.fatura_tarihi))
          .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiSatiri.fatura_id)
          .where(SatisFaturasi.durum != "İPTAL", SatisFaturasi.onaylandi.is_(True),
                 or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)),
                 SatisFaturasi.fatura_tarihi <= son))
    if depo:
        qa = qa.where(AlisFaturasi.depo == depo)
        qs = qs.where(SatisFaturasi.depo == depo)
    alis = {k: _gun(t) for k, t in session.execute(qa.group_by(AlisFaturasiSatiri.urun_kodu)).all() if k}
    satis = {k: _gun(t) for k, t in session.execute(qs.group_by(SatisFaturasiSatiri.urun_kodu)).all() if k}
    return alis, satis


def _deger(v) -> Any:
    return _q2(v) if v is not None else HESAPLANAMADI


def _verimlilik_toplami(satirlar: list[dict], gun: int, meta: dict) -> dict:
    """Grup / genel toplam: tutarlar toplanır, oranlar hesaplanabilir ürünlerin toplam tutarlarından yeniden
    hesaplanır (satır yüzdelerinin ortalaması alınmaz)."""
    r: dict[str, Any] = dict(meta)
    r["urun_sayisi"] = len(satirlar)
    for alan in ("bas_deger", "son_deger", "ort_stok", "net_satis", "smm", "brut_kar"):
        r[alan] = _q2(sum((x[alan] for x in satirlar if isinstance(x.get(alan), Decimal)), SIFIR))
    birimler = {x["birim"] for x in satirlar}
    tek = len(birimler) == 1
    for alan in ("bas_miktar", "son_miktar", "net_miktar"):
        degerler = [x.get(alan) for x in satirlar]
        r[alan] = sum(degerler, SIFIR) if tek and all(isinstance(v, Decimal) for v in degerler) else None
    r["birim"] = next(iter(birimler)) if tek else ("Karışık" if birimler else "")
    tam = [x for x in satirlar if x.get("_tam")]
    oran, nedenler = _oranlar(sum((x["_net"] for x in tam), SIFIR), sum((x["_smm"] for x in tam), SIFIR),
                              sum((x["_kar"] for x in tam), SIFIR),
                              sum((x["_ort"] for x in tam), SIFIR) if tam else None, gun,
                              [] if tam else ["yok"])
    r.update(oran)
    r["kapsam"] = f"{len(tam)}/{len(satirlar)} ürün"
    notlar = []
    if not tam:
        notlar.append("Hesaplanabilir ürün yok — oranlar verilmez")
    elif len(tam) < len(satirlar):
        notlar.append(f"Oranlar {len(tam)} ürünün toplam tutarlarından hesaplandı; {len(satirlar) - len(tam)} "
                      "ürün hesaplanamadığı için oranlara katılmadı")
    if not tek and birimler:
        notlar.append("Farklı birimler — miktarlar toplanmaz")
    r["hesap_notu"] = "; ".join(notlar + nedenler)
    for alan in ("son_alis", "son_satis"):
        tarihler = [x[alan] for x in satirlar if x.get(alan)]
        r[alan] = max(tarihler) if tarihler else None
    return r


def _siralama_anahtari(alan: str):
    def anahtar(r):
        v = r.get(alan)
        return (0, -v, r.get("urun_kodu") or "") if isinstance(v, Decimal) else (1, SIFIR, r.get("urun_kodu") or "")
    return anahtar


def yatirim_verimliligi(*, bas: date, bit: date, yontem: str = FIFO, depo: str | None = None, arama: str = "",
                        ana_grup_id=None, tali_grup_id=None, alt_grup_id=None, grup_seviyesi: str = "ana",
                        siralama: str = "brut_kar", bugun: date | None = None) -> dict:
    """Ürün / grup bazında stokta bağlı sermayenin ürettiği brüt kâr (GMROI), devir hızı ve stokta kalma süresi."""
    from database.access import maliyet_zorunlu
    from database.satis_kar_analiz_service import SatisKarAnalizService
    from database.satis_maliyet_motoru import MaliyetMotoru
    from database.satis_yonetici_rapor_service import kar_filtresi, tamamla, topla

    _yetki()
    maliyet_zorunlu()
    yontemler = dict(verimlilik_yontemleri())
    if yontem not in yontemler:
        raise ValueError(f"Desteklenmeyen maliyet yöntemi: {yontem}")
    if grup_seviyesi not in _GRUP_ALANLARI:
        raise ValueError(f"Geçersiz grup seviyesi: {grup_seviyesi}")
    if siralama not in dict(VERIMLILIK_SIRALAMA):
        siralama = "brut_kar"
    if bas is None or bit is None:
        raise ValueError("Başlangıç ve bitiş tarihi gerekli.")
    b = bugun or date.today()
    son = min(bit, b)
    if son < bas:
        raise ValueError("Bitiş, başlangıçtan önce olamaz (gelecek tarihler bugüne kadar hesaplanır).")
    gun = (son - bas).days + 1
    gruplar_f = {"ana_grup_id": ana_grup_id, "tali_grup_id": tali_grup_id, "alt_grup_id": alt_grup_id}
    filtreli = bool((arama or "").strip() or any(gruplar_f.values()))

    satis_satirlari = SatisKarAnalizService._satirlari_yukle(
        kar_filtresi(bas, son, {"depo": depo, "maliyet_yontemi": yontem}))
    satis = {kod: tamamla(k) for kod, k in topla(satis_satirlari, "urun").items()}
    with get_session() as s:
        depolar = {d.id: d.ad for d in s.scalars(select(Depo)).all()}
        hizmet_kodlari = {k for k, tur in s.execute(select(StokKarti.stok_kodu, StokKarti.kart_turu)).all()
                          if "hizmet" in (tur or "").casefold()}
        tum_kodlar = {k for (k,) in s.execute(select(StokKarti.stok_kodu)).all()}
        kartlar = [k for k in _kartlar(s, arama, None, pasif_dahil=True)
                   if all(not v or getattr(k, a) == int(v) for a, v in gruplar_f.items())]
        kart_id = {k.id: k for k in kartlar}
        meta = _grup_meta(s)
        metalar = {k.id: meta(k) for k in kartlar}
        veri = _gunluk_seriler(s, bas, son, depo, depolar, set(kart_id))
        motor = MaliyetMotoru(s, bitis=son) if yontem != FIFO else None
        degerler = _ortalama_degerler(veri, bas, son, yontem, kart_id, motor, b)
        son_alis, son_satis = _son_tarihler(s, son, depo)
    devir_ici: dict[int, date] = {}
    for lot in veri["devir_lotlari"]:
        t = _gun(lot.giris_tarihi) if lot.giris_tarihi else None
        sid = int(lot.stok_id)
        if t and bas < t <= son and sid in kart_id:
            devir_ici[sid] = min(t, devir_ici.get(sid, t))

    satirlar: list[dict] = []
    for k in kartlar:
        sr = veri["seriler"].get(k.id)
        t = satis.get(k.stok_kodu)
        d = degerler.get(k.id) or {"bas_v": SIFIR, "son_v": SIFIR, "ort": SIFIR, "eksik": ""}
        bas_q = sr.acilis_q if sr else SIFIR
        son_q = bas_q + (sum(sr.dq.values(), SIFIR) if sr else SIFIR)
        if t is None and bas_q == 0 and son_q == 0 and not d["ort"]:
            continue
        stok_nedeni = [d["eksik"]] if d["eksik"] else []
        neg = _kosullu_gun(sr.acilis_q, sr.dq, bas, son, lambda q: q < -ESIK) if sr else 0
        if neg:
            stok_nedeni.append(f"Negatif stok ({neg} gün)")
            d = dict(d, ort=None)
        if bas_q < -ESIK or son_q < -ESIK:
            d = dict(d, bas_v=None if bas_q < -ESIK else d["bas_v"], son_v=None if son_q < -ESIK else d["son_v"])
        if k.id in devir_ici:
            stok_nedeni.append(f"Eksik devir verisi: açılış/devir girişi {devir_ici[k.id]:%d.%m.%Y} dönem içinde, "
                               "öncesindeki stok bilinmiyor")
        satirlar.append(_verimlilik_satiri(k.stok_kodu, k.stok_adi, k.birim or "Adet", metalar[k.id], t, d,
                                           bas_q, son_q, stok_nedeni, gun,
                                           son_alis.get(k.stok_kodu), son_satis.get(k.stok_kodu),
                                           stok_id=k.id, pasif="" if k.aktif else "Pasif kart"))
    if not filtreli:
        kart_kodlari = {k.stok_kodu for k in kartlar}
        for kod, t in satis.items():
            if kod in hizmet_kodlari or kod in kart_kodlari:
                continue
            neden = "Stok kartı bulunamadı — stok değeri yok" if kod not in tum_kodlar else \
                "Stok kartı silinmiş — stok değeri yok"
            satirlar.append(_verimlilik_satiri(kod, t.get("urun_adi") or "", t.get("birim") or "",
                                               {"ana_grup": "(Stok kartı yok)", "tali_grup": "", "alt_grup": ""},
                                               t, {"bas_v": None, "son_v": None, "ort": None, "eksik": ""},
                                               None, None, [neden], gun, son_alis.get(kod), son_satis.get(kod)))
    satirlar.sort(key=_siralama_anahtari(siralama))

    alanlar = _GRUP_ALANLARI[grup_seviyesi]
    gruplu: dict[tuple, list[dict]] = defaultdict(list)
    for r in satirlar:
        gruplu[tuple(r.get(a) or ("(Grupsuz)" if i == 0 else "") for i, a in enumerate(alanlar))].append(r)
    gruplar = [_verimlilik_toplami(rs, gun, dict(zip(alanlar, anahtar))) for anahtar, rs in gruplu.items()]
    gruplar.sort(key=_siralama_anahtari(siralama))
    toplam = _verimlilik_toplami(satirlar, gun, {"urun_kodu": "GENEL TOPLAM", "ana_grup": "GENEL TOPLAM",
                                                 "_sabit": True})
    hesaplanamayan = [r for r in satirlar if r["hesap_notu"]]

    ilk = veri["ilk_tarih"]
    yontem_ad = yontemler[yontem]
    bilgi = [f"Dönem: {bas:%d.%m.%Y} – {son:%d.%m.%Y} ({gun} gün)", f"Maliyet yöntemi: {yontem_ad}",
             f"Ortalama stok: günlük kapanış değerlerinin ortalaması ({gun} gün)",
             f"Grup görünümü: {dict(GRUP_SEVIYELERI)[grup_seviyesi]}"]
    notlar = [
        f"Maliyet yöntemi: {yontem_ad}. Satılan malın maliyeti ve stok değerlemesi aynı yöntemle hesaplanır"
        + (" (satış maliyeti satışta kaydedilen gerçek FIFO çıkış maliyeti; stok değeri o gün açık FIFO "
           "katmanları)." if yontem == FIFO else
           " (ürün bazında firma geneli ortalama birim maliyet × deponun miktarı)."),
        f"Ortalama stok maliyet değeri = {bas:%d.%m.%Y}–{son:%d.%m.%Y} arasındaki {gun} günün her birinin gün sonu "
        "stok değerinin ortalamasıdır; stok hareket geçmişinden her gün için hesaplanır (dönem başı/sonu "
        "ortalaması değildir).",
        "Brüt kâr = KDV hariç net satış (satış iadeleri düşülmüş) − satılan malın maliyeti (iadelerin maliyeti "
        "düşülmüş). Brüt kâr net işletme kârı değildir: genel giderler, finansman ve vergi düşülmez.",
        "Brüt kâr marjı (%) = Brüt kâr / Net satış × 100. Stok devir hızı = Satılan malın maliyeti / Ortalama stok "
        "maliyet değeri. Ortalama stokta kalma süresi = Dönem gün sayısı / Stok devir hızı.",
        "GMROI = Brüt kâr / Ortalama stok maliyet değeri, katsayıdır: 0,40 seçilen dönemde ortalama stok "
        "yatırımının her 1 TL'si için 0,40 TL brüt kâr üretildiğini gösterir. Sonuç yıllıklandırılmaz.",
        f"Grup kuralı: her ürün tek ana / tali / alt gruba bağlıdır; seçilen seviyede ({dict(GRUP_SEVIYELERI)[grup_seviyesi].lower()}) "
        "her ürün yalnız bir grupta sayılır. Genel toplam ürün satırlarından bir kez toplanır, grup satırları "
        "toplanmaz. Grup ve genel oranlar satır yüzdelerinin ortalaması değildir; hesaplanabilir ürünlerin toplam "
        "tutarlarından yeniden hesaplanır (Kapsam sütunu: oranlara giren ürün sayısı).",
        "Miktarlar stok kartının temel birimindedir; satış satırları stok kartındaki birim çarpanlarıyla temel "
        "birime çevrilir. Farklı birimli ürünlerin miktarları grup / genel toplamda toplanmaz (Birim: Karışık).",
        "Satışlar onaylı satış faturaları ve satış iade faturalarından gelir (satış yönetici raporlarıyla ortak "
        "hesap). Hızlı satış, sipariş ve irsaliyeden faturaya dönüşen satış yalnız faturadan bir kez sayılır; "
        "irsaliyeli satırın maliyeti irsaliye çıkışından bir kez alınır. Faturalanmamış irsaliye satış sayılmaz "
        "ancak stoktan düştüğü için stok değerini azaltır.",
        "Alış iadeleri stoktan çıkış maliyetiyle düşer. Depo transferleri satış veya kâr sayılmaz; firma "
        "toplamında birbirini götürür, depo filtresinde yalnız ilgili deponun stoğunu değiştirir. Depo "
        "filtresinde satışlar faturanın deposuna göre süzülür.",
        "Maliyet dağıtımıyla alış katmanlarına eklenen nakliye vb. masraflar katman maliyetine dahildir; dağıtım "
        "tarihinden önceki günlerde bu pay stok değerinden düşülür (değerleme raporuyla aynı kural).",
        "Eksik maliyet, negatif stok, eksik devir verisi veya sıfır/negatif ortalama stok değeri olan ürünlerde "
        "oranlar 0 gösterilmez; 'Hesaplanamadı' yazılır ve nedeni 'Hesap Notu' sütunundadır.",
        "Negatif bakiye değerlenmez (değerleme raporuyla aynı): negatif günü olan ürünün ortalama stok değeri, "
        "negatif dönem başı / sonu bakiyesinin değeri 'Hesaplanamadı' olur ve toplamlara katılmaz. Kısmen "
        "maliyetsiz stokta da değer 'Hesaplanamadı' gösterilir; değerleme raporu bu durumda maliyeti bilinen "
        "kısmı gösterdiğinden toplamlar arasında bu ürünler kadar fark olabilir.",
        "Hareket görmeyen fakat stokta sermaye tutan ürünler de listelenir (devir 0, GMROI 0).",
        SALT_OKUNUR_NOTU,
    ]
    if ilk and ilk > bas:
        uyari = (f"Firmanın stok hareket geçmişi {ilk:%d.%m.%Y} tarihinde başlıyor; öncesindeki günler stok değeri 0 "
                 "kabul edildi — ortalama stok düşük, devir ve GMROI yüksek çıkabilir.")
        notlar.insert(2, uyari)
        bilgi.append("Uyarı: hareket geçmişi dönem başından sonra başlıyor")
    if satis_satirlari and any(kod in hizmet_kodlari for kod in satis):
        notlar.append("Hizmet kartlarının satışları stok tutmadığı için rapora alınmaz.")
    return {"urunler": satirlar + ([toplam] if satirlar else []),
            "gruplar": gruplar + ([dict(toplam, **{a: ("GENEL TOPLAM" if i == 0 else "") for i, a in
                                                   enumerate(alanlar)})] if gruplar else []),
            "hesaplanamayan": hesaplanamayan, "toplam": toplam, "gun": gun, "bas": bas, "son": son,
            "yontem": yontem_ad, "_baslik": f"STOK YATIRIM VERİMLİLİĞİ — {yontem_ad}", "_bilgi": bilgi,
            "notlar": notlar}


def _verimlilik_satiri(kod, ad, birim, meta, t, d, bas_q, son_q, stok_nedeni, gun, son_alis, son_satis,
                       stok_id=None, pasif="") -> dict:
    nedenler = list(stok_nedeni)
    net = t["net"] if t else SIFIR
    eksik_satir = t["eksik_satir"] if t else 0
    smm = None if eksik_satir else (t["maliyet"] if t else SIFIR)
    kar = None if eksik_satir else (t["kar"] if t else SIFIR)
    if eksik_satir:
        nedenler.append(f"{eksik_satir} satış satırında maliyet eksik — satış maliyeti ve brüt kâr verilmez")
    net_miktar = t["net_miktar"] if t else SIFIR
    if t and net_miktar is None:
        nedenler.append("Satış birimi stok kartındaki birime çevrilemedi — net miktar verilmez")
    ort = d["ort"]
    oran, oran_neden = _oranlar(net, smm, kar, ort, gun, stok_nedeni)
    nedenler += oran_neden
    return {"stok_id": stok_id, "urun_kodu": kod, "urun_adi": ad, "birim": birim, **meta,
            "bas_miktar": bas_q if bas_q is not None else HESAPLANAMADI, "bas_deger": _deger(d["bas_v"]),
            "son_miktar": son_q if son_q is not None else HESAPLANAMADI, "son_deger": _deger(d["son_v"]),
            "ort_stok": _deger(ort), "net_satis": _q2(net),
            "net_miktar": net_miktar if net_miktar is not None else HESAPLANAMADI,
            "smm": _deger(smm), "brut_kar": _deger(kar), **oran, "son_alis": son_alis, "son_satis": son_satis,
            "pasif": pasif, "hesap_notu": "; ".join(nedenler),
            "_tam": not stok_nedeni and ort is not None and smm is not None,
            "_ort": ort if ort is not None else SIFIR, "_smm": smm or SIFIR, "_kar": kar or SIFIR, "_net": net}
