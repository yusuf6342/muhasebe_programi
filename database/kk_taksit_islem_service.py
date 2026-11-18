"""Firma kredi kartı taksitlerini karta / ekstreye yansıtma.

Kural:
* Evrak işlendiğinde **tüm** taksitler kalıcı kart hareketi olarak yazılır.
* Her hareket kendi ``vade_tarihi`` (yansıma) ile kaydedilir; hareket ≠ ödeme.
* CARI: bakiyeyi artıran ``KK ÖDEME``. EVO/EVO_DEVIR/GIDER vb. zaten ledger'da
  borcu olan kaynaklarda ``KK TAKSİT`` (nötr) — mükerrer borç yok.
* Aynı ``odeme_id`` + ``taksit_no`` için tek hareket (``islem_anahtari`` / belge-Tn).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import (
    FinansHareketi,
    FinansHesabi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")
DURUM_BEKLIYOR = "BEKLIYOR"
DURUM_KARTA = "KARTA_ISLENDI"
DURUM_ODENDI = "ODENDI"
HAREKET_KK = "KK ÖDEME"
HAREKET_TAKSIT_DETAY = "KK TAKSİT"
# Bu kaynaklarda taksit hareketi bakiyeyi artırmaz (açılış/devir/gider zaten yazılmış)
KAYNAK_DETAY = frozenset({"EVO", "EVO_DEVIR", "GIDER", "NAKIT_AVANS"})
KAYNAK_ISLENIR = frozenset({"CARI", "EVO", "EVO_DEVIR", "GIDER", "NAKIT_AVANS"})


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def taksit_hareket_belge(odeme_belge: str, taksit_no: int) -> str:
    return f"{(odeme_belge or '').strip()}-T{int(taksit_no)}"


def taksit_islem_anahtari(odeme_id: int, taksit_no: int) -> str:
    return f"kk-odeme-{int(odeme_id)}-T{int(taksit_no)}"


def schema_hazirla(bind=None) -> None:
    from database.kk_plan_service import schema_hazirla as _plan_schema

    _plan_schema(bind=bind)


def _kk_hesap(session, kart: KrediKartiTanimi) -> FinansHesabi:
    hid = getattr(kart, "bagli_hesap_id", None)
    if hid:
        h = session.get(FinansHesabi, int(hid))
        if h is not None and (h.alt_hesap_turu or "").upper() == "KREDI_KARTI":
            return h
    from database.finans_service import FinansService
    from database.models.finans import BankaKarti

    banka = session.get(BankaKarti, int(kart.banka_karti_id)) if kart.banka_karti_id else None
    if banka is None:
        raise ValueError(f"{kart.kart_adi}: banka kartı yok.")
    h = FinansService.banka_alt_hesap(banka, "KREDI_KARTI")
    if h is None:
        raise ValueError(f"{kart.kart_adi}: kredi kartı hesabı yok.")
    return h


def _hareket_turu_sec(session, odeme: KrediKartiOdeme, kk_hesap: FinansHesabi) -> str:
    """Borç artıran KK ÖDEME mi, yoksa nötr KK TAKSİT mi?"""
    kaynak = (getattr(odeme, "kaynak_turu", None) or "CARI").upper()
    if kaynak in KAYNAK_DETAY:
        return HAREKET_TAKSIT_DETAY
    # Ana belge zaten ledger'da (toplu yazım) → taksitler ayrıntı
    bel = (odeme.belge_no or "").strip()
    if bel:
        mevcut = session.scalar(
            select(FinansHareketi.id).where(
                FinansHareketi.belge_no == bel,
                FinansHareketi.hesap_id == int(kk_hesap.id),
                FinansHareketi.hareket_turu == HAREKET_KK,
            )
        )
        if mevcut is not None:
            return HAREKET_TAKSIT_DETAY
    return HAREKET_KK


def taksit_karta_isle_oturum(
    session,
    taksit: KrediKartiOdemeTaksit,
    *,
    islem_tarihi: date | None = None,
    islem_anahtari: str | None = None,
    sube_id: int | None = None,
    hareket_belge_no: str | None = None,
) -> dict[str, Any]:
    """Açık oturumda taksiti karta yaz; durum ``KARTA_ISLENDI``. Hareket ≠ ödeme."""
    schema_hazirla(bind=session.get_bind())
    durum = (taksit.durum or "").upper()
    if durum == DURUM_ODENDI and taksit.kk_hareket_belge_no:
        return _taksit_ozet(taksit)
    if durum == DURUM_KARTA and taksit.kk_hareket_belge_no:
        # Tutar/tarih güncellemesi (düzenleme)
        return _taksit_hareket_guncelle(session, taksit, islem_tarihi=islem_tarihi)

    if durum in ("PLAN_IPTAL", "IADE") or getattr(taksit, "aktif", True) is False:
        raise ValueError("İptal / pasif taksit karta işlenemez.")

    odeme = taksit.odeme or session.get(KrediKartiOdeme, int(taksit.odeme_id))
    if odeme is None or (odeme.durum or "").upper() not in ("AÇIK", "ACIK"):
        raise ValueError("Kart ödeme fişi açık değil.")
    kaynak = (getattr(odeme, "kaynak_turu", None) or "CARI").upper()
    if kaynak not in KAYNAK_ISLENIR:
        raise ValueError(f"Bu kaynak ({kaynak}) için taksit karta işleme uygulanmaz.")

    anahtar = (islem_anahtari or taksit.islem_anahtari or taksit_islem_anahtari(odeme.id, taksit.taksit_no)).strip()
    if anahtar:
        once = session.scalar(
            select(KrediKartiOdemeTaksit).where(
                KrediKartiOdemeTaksit.islem_anahtari == anahtar,
                KrediKartiOdemeTaksit.durum.in_((DURUM_KARTA, DURUM_ODENDI)),
            )
        )
        if once is not None and int(once.id) != int(taksit.id):
            return _taksit_ozet(once)
        if once is not None and once.kk_hareket_belge_no and int(once.id) == int(taksit.id):
            return _taksit_ozet(once)

    kart = session.get(KrediKartiTanimi, int(odeme.kredi_karti_id))
    if kart is None:
        raise ValueError("Kredi kartı bulunamadı.")
    kk_hesap = _kk_hesap(session, kart)
    tutar = _d(taksit.tutar)
    if tutar <= 0:
        raise ValueError("Taksit tutarı pozitif olmalıdır.")

    # Nakit avans: borç zaten ``KK NAKİT AVANS`` satırında — ikinci -Tn üretme; bağla.
    if kaynak == "NAKIT_AVANS":
        ana_belge = (odeme.belge_no or "").strip()
        na_h = session.scalar(
            select(FinansHareketi).where(
                FinansHareketi.belge_no == ana_belge,
                FinansHareketi.hesap_id == int(kk_hesap.id),
                FinansHareketi.hareket_turu == "KK NAKİT AVANS",
            )
        )
        if na_h is not None:
            # Eski mükerrer -Tn ayrıntı satırını temizle (borç artırmazdı; görüntü kirliliği)
            tn_bel = taksit_hareket_belge(ana_belge, int(taksit.taksit_no))
            for eski in list(
                session.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == int(kk_hesap.id),
                        FinansHareketi.belge_no == tn_bel,
                        FinansHareketi.hareket_turu == HAREKET_TAKSIT_DETAY,
                    )
                ).all()
            ):
                session.delete(eski)
            taksit.durum = DURUM_KARTA
            taksit.kk_hareket_belge_no = ana_belge
            taksit.islem_anahtari = anahtar
            session.flush()
            return _taksit_ozet(taksit)

    belge = (hareket_belge_no or taksit.kk_hareket_belge_no or taksit_hareket_belge(odeme.belge_no, taksit.taksit_no)).strip()
    tur = _hareket_turu_sec(session, odeme, kk_hesap)
    mevcut_h = session.scalar(
        select(FinansHareketi).where(
            FinansHareketi.belge_no == belge,
            FinansHareketi.hesap_id == int(kk_hesap.id),
            FinansHareketi.hareket_turu.in_((HAREKET_KK, HAREKET_TAKSIT_DETAY)),
        )
    )
    tarih = islem_tarihi or taksit.vade_tarihi or odeme.tarih or date.today()
    n = int(odeme.taksit_sayisi or 1)
    acik = (
        f"{odeme.aciklama or odeme.belge_no} · taksit {taksit.taksit_no}/{n}"
        + (" · plan ayrıntı (borç mükerrer değil)" if tur == HAREKET_TAKSIT_DETAY else "")
    )[:500]
    if mevcut_h is None:
        session.add(
            FinansHareketi(
                hesap_id=int(kk_hesap.id),
                sube_id=sube_id,
                tarih=tarih,
                hareket_turu=tur,
                belge_no=belge,
                tutar=tutar,
                aciklama=acik,
            )
        )
    else:
        # Idempotent: mevcut hareketi güncelle (ikinci satır yok)
        mevcut_h.tarih = tarih
        mevcut_h.tutar = tutar
        mevcut_h.hareket_turu = tur
        mevcut_h.aciklama = acik
        belge = mevcut_h.belge_no

    taksit.durum = DURUM_KARTA
    taksit.kk_hareket_belge_no = belge
    taksit.islem_anahtari = anahtar
    session.flush()
    return _taksit_ozet(taksit)


def _taksit_hareket_guncelle(
    session,
    taksit: KrediKartiOdemeTaksit,
    *,
    islem_tarihi: date | None = None,
) -> dict[str, Any]:
    """Mevcut bağlantılı hareketi tutar/tarihle güncelle; ikinci hareket ekleme."""
    odeme = taksit.odeme or session.get(KrediKartiOdeme, int(taksit.odeme_id))
    if odeme is None:
        return _taksit_ozet(taksit)
    kart = session.get(KrediKartiTanimi, int(odeme.kredi_karti_id))
    if kart is None:
        return _taksit_ozet(taksit)
    kk_hesap = _kk_hesap(session, kart)
    belge = (taksit.kk_hareket_belge_no or "").strip()
    if not belge:
        return _taksit_ozet(taksit)
    h = session.scalar(
        select(FinansHareketi).where(
            FinansHareketi.belge_no == belge,
            FinansHareketi.hesap_id == int(kk_hesap.id),
        )
    )
    if h is not None:
        h.tarih = islem_tarihi or taksit.vade_tarihi or h.tarih
        h.tutar = _d(taksit.tutar)
        tur = _hareket_turu_sec(session, odeme, kk_hesap)
        h.hareket_turu = tur
        session.flush()
    return _taksit_ozet(taksit)


def _taksit_ozet(t: KrediKartiOdemeTaksit) -> dict[str, Any]:
    o = t.odeme
    return {
        "taksit_id": int(t.id),
        "odeme_id": int(t.odeme_id),
        "taksit_no": int(t.taksit_no),
        "tutar": _d(t.tutar),
        "vade_tarihi": t.vade_tarihi,
        "durum": t.durum,
        "kk_hareket_belge_no": t.kk_hareket_belge_no,
        "islem_anahtari": t.islem_anahtari,
        "belge_no": o.belge_no if o else None,
    }


def odeme_tum_taksitleri_isle(
    session,
    odeme: KrediKartiOdeme,
    *,
    sube_id: int | None = None,
) -> list[dict[str, Any]]:
    """Kayıt anında tüm taksitleri kendi yansıma tarihleriyle karta yaz."""
    session.flush()
    taksitler = sorted(
        [
            t
            for t in (odeme.taksitler or [])
            if getattr(t, "aktif", True)
            and (t.durum or "").upper() not in ("PLAN_IPTAL", "IADE")
        ],
        key=lambda x: int(x.taksit_no),
    )
    if not taksitler:
        taksitler = list(
            session.scalars(
                select(KrediKartiOdemeTaksit)
                .where(
                    KrediKartiOdemeTaksit.odeme_id == int(odeme.id),
                    KrediKartiOdemeTaksit.aktif.is_(True),
                )
                .order_by(KrediKartiOdemeTaksit.taksit_no)
            ).all()
        )
        taksitler = [
            t
            for t in taksitler
            if (t.durum or "").upper() not in ("PLAN_IPTAL", "IADE")
        ]
    sonuc: list[dict[str, Any]] = []
    for t in taksitler:
        try:
            sonuc.append(
                taksit_karta_isle_oturum(
                    session,
                    t,
                    islem_tarihi=t.vade_tarihi or odeme.tarih,
                    islem_anahtari=taksit_islem_anahtari(odeme.id, int(t.taksit_no)),
                    sube_id=sube_id,
                )
            )
        except Exception as exc:
            sonuc.append(
                {
                    "taksit_id": int(t.id),
                    "taksit_no": int(t.taksit_no),
                    "hata": str(exc),
                }
            )
    return sonuc


def odeme_ilk_taksiti_isle(
    session,
    odeme: KrediKartiOdeme,
    *,
    sube_id: int | None = None,
) -> dict[str, Any] | None:
    """Geriye uyum: tüm taksitleri işler; özet olarak 1. taksiti döner."""
    sonuc = odeme_tum_taksitleri_isle(session, odeme, sube_id=sube_id)
    for s in sonuc:
        if int(s.get("taksit_no") or 0) == 1 and not s.get("hata"):
            return s
    return sonuc[0] if sonuc else None


def eksik_taksit_hareketlerini_tamamla(
    *,
    kredi_karti_id: int | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    """BEKLIYOR / hareketsiz taksitleri kalıcı harekete bağla (idempotent; evrak çoğalmaz)."""
    schema_hazirla()
    yazilan = 0
    atlanan = 0
    hatalar: list[dict] = []
    with get_session() as session:
        q = (
            select(KrediKartiOdemeTaksit)
            .join(KrediKartiOdeme)
            .where(
                KrediKartiOdeme.durum == "AÇIK",
                KrediKartiOdeme.kaynak_turu.in_(tuple(KAYNAK_ISLENIR)),
                KrediKartiOdemeTaksit.aktif.is_(True),
                KrediKartiOdemeTaksit.durum.in_((DURUM_BEKLIYOR, DURUM_KARTA)),
            )
            .options(selectinload(KrediKartiOdemeTaksit.odeme))
            .order_by(KrediKartiOdemeTaksit.id)
            .limit(int(limit))
        )
        if kredi_karti_id is not None:
            q = q.where(KrediKartiOdeme.kredi_karti_id == int(kredi_karti_id))
        ids = [
            int(t.id)
            for t in session.scalars(q).all()
            if not (t.kk_hareket_belge_no and (t.durum or "").upper() == DURUM_KARTA)
        ]
    for tid in ids:
        try:
            with get_session() as session:
                t = session.get(KrediKartiOdemeTaksit, tid)
                if t is None:
                    continue
                if t.kk_hareket_belge_no and (t.durum or "").upper() in (
                    DURUM_KARTA,
                    DURUM_ODENDI,
                ):
                    atlanan += 1
                    continue
                taksit_karta_isle_oturum(
                    session,
                    t,
                    islem_tarihi=t.vade_tarihi,
                    islem_anahtari=taksit_islem_anahtari(t.odeme_id, int(t.taksit_no)),
                )
                yazilan += 1
        except Exception as exc:
            hatalar.append({"taksit_id": tid, "hata": str(exc)})
    return {
        "yazilan": yazilan,
        "atlanan": atlanan,
        "hata_adet": len(hatalar),
        "hatalar": hatalar[:50],
    }


def odeme_taksit_hareketlerini_sil(session, odeme: KrediKartiOdeme) -> int:
    """Ödeme fişine bağlı taksit kart hareketlerini sil (iptal / yeniden yazım)."""
    from database.finans_service import FinansService

    silinen = 0
    belgeler: set[str] = set()
    for t in odeme.taksitler or []:
        if getattr(t, "kk_hareket_belge_no", None):
            belgeler.add(str(t.kk_hareket_belge_no).strip())
        belgeler.add(taksit_hareket_belge(odeme.belge_no, t.taksit_no))
    for bel in belgeler:
        if bel:
            silinen += FinansService._finans_hareketlerini_sil(session, bel)
    return silinen


def vadesi_gelenleri_isle(
    *,
    kredi_karti_id: int | None = None,
    bugun: date | None = None,
) -> list[dict[str, Any]]:
    """Geriye uyum: eksik taksit hareketlerini tamamlar (tarih filtresi yok — hepsi)."""
    _ = bugun  # artık vade beklemeden tüm eksikler yazılır
    ozet = eksik_taksit_hareketlerini_tamamla(kredi_karti_id=kredi_karti_id)
    return [
        {"yazilan": ozet["yazilan"], "atlanan": ozet["atlanan"], "hata_adet": ozet["hata_adet"]}
    ]


def brut_ledger_duzelt(
    session,
    odeme: KrediKartiOdeme,
    *,
    makbuz_belge_no: str | None = None,
    bugun: date | None = None,
) -> dict[str, Any]:
    """Eski tek kalem (tam tutar) KK ÖDEME satırını taksit planına çevir.

    * Tam tutarlı hareket ve varsa dengeleyen ``KK ÖDEME İPTAL`` doğrudan silinir.
    * Tüm taksitler kendi yansıma tarihleriyle kalıcı harekete yazılır (aktarım aşaması yok).
    """
    _ = bugun  # geriye uyum; artık vade filtresi yok
    schema_hazirla(bind=session.get_bind())
    kart = session.get(KrediKartiTanimi, int(odeme.kredi_karti_id))
    if kart is None:
        raise ValueError("Kart yok.")
    kk_hesap = _kk_hesap(session, kart)
    aday_belgeler = {odeme.belge_no}
    if makbuz_belge_no:
        aday_belgeler.add(makbuz_belge_no)
    if "-K" in (odeme.belge_no or ""):
        aday_belgeler.add(odeme.belge_no.rsplit("-K", 1)[0])

    brut = _d(odeme.tutar)
    silinen = []
    for bel in list(aday_belgeler):
        for h in list(
            session.scalars(
                select(FinansHareketi).where(
                    FinansHareketi.belge_no == bel,
                    FinansHareketi.hareket_turu == HAREKET_KK,
                    FinansHareketi.hesap_id == int(kk_hesap.id),
                )
            ).all()
        ):
            if _d(h.tutar) != brut:
                continue
            bel_u = (h.belge_no or "").rstrip().upper()
            if "-T" in bel_u and bel_u.rsplit("-T", 1)[-1].isdigit():
                continue
            silinen.append({"id": int(h.id), "belge_no": h.belge_no, "tutar": brut, "tur": h.hareket_turu})
            session.delete(h)
        iptal_belge = f"{bel}-IPTAL-TAKSIT"
        for h in list(
            session.scalars(
                select(FinansHareketi).where(
                    FinansHareketi.belge_no == iptal_belge,
                    FinansHareketi.hesap_id == int(kk_hesap.id),
                )
            ).all()
        ):
            silinen.append(
                {
                    "id": int(h.id),
                    "belge_no": h.belge_no,
                    "tutar": _d(h.tutar),
                    "tur": h.hareket_turu,
                }
            )
            session.delete(h)

    session.flush()
    islenen = odeme_tum_taksitleri_isle(session, odeme)
    return {
        "odeme_id": int(odeme.id),
        "belge_no": odeme.belge_no,
        "terslenen": silinen,
        "silinen": silinen,
        "islenen": islenen,
    }


def taksit_durum_etiket(durum: str | None) -> str:
    """Ekran / ekstre: BEKLIYOR→Planlandı, KARTA_ISLENDI→Karta işlendi."""
    d = (durum or "").upper()
    if d == DURUM_BEKLIYOR:
        return "Planlandı"
    if d == DURUM_KARTA:
        return "Karta işlendi"
    if d == DURUM_ODENDI:
        return "Ödendi"
    if d == "PLAN_IPTAL":
        return "Plan iptal"
    if d == "IADE":
        return "İade"
    return durum or "—"


def _hareket_sozluk(h: FinansHareketi, *, kart_adi: str = "") -> dict[str, Any]:
    return {
        "id": int(h.id),
        "hesap_id": int(h.hesap_id),
        "tarih": h.tarih,
        "hareket_turu": h.hareket_turu,
        "belge_no": h.belge_no or "",
        "tutar": _d(h.tutar),
        "aciklama": h.aciklama or "",
        "kart_adi": kart_adi,
    }


def kredi_karti_hareket_sil_onizleme(hareket_id: int) -> dict[str, Any]:
    """Silme öncesi: hareket + dengeleyen / bağlı kayıtlar (salt okunur)."""
    schema_hazirla()
    with get_session() as s:
        h = s.get(FinansHareketi, int(hareket_id))
        if h is None:
            return {"bulundu": False, "hareket_id": int(hareket_id), "zaten_silinmis": True}
        hesap = s.get(FinansHesabi, int(h.hesap_id))
        kart = None
        if hesap and getattr(hesap, "banka_karti_id", None):
            kart = s.scalar(
                select(KrediKartiTanimi).where(
                    KrediKartiTanimi.bagli_hesap_id == int(hesap.id)
                )
            ) or s.scalar(
                select(KrediKartiTanimi).where(
                    KrediKartiTanimi.banka_karti_id == int(hesap.banka_karti_id)
                ).order_by(KrediKartiTanimi.id)
            )
        kart_adi = kart.kart_adi if kart else (hesap.hesap_adi if hesap else "")
        bagli: list[dict] = []
        engel: list[str] = []

        belge = (h.belge_no or "").strip()

        # Taksit satırı bağlantısı (klasik KK ödeme taksiti)
        taksit = s.scalar(
            select(KrediKartiOdemeTaksit).where(
                KrediKartiOdemeTaksit.kk_hareket_belge_no == belge
            )
        )
        if taksit is not None:
            bagli.append(
                {
                    "tur": "taksit",
                    "taksit_id": int(taksit.id),
                    "odeme_id": int(taksit.odeme_id),
                    "taksit_no": int(taksit.taksit_no),
                    "durum": taksit.durum,
                    "etki": "Silinince taksit Planlandı'ya döner",
                }
            )

        # Nakit avans: bağlantı NakitAvansTaksit.kk_hareket_belge_no / KrediKartiOdeme.belge_no
        na_taksit_id = None
        if belge.startswith("NAT-") or (h.hareket_turu or "").upper().startswith("KK NAKİT AVANS"):
            from database.models.finans import NakitAvansTaksit

            na_t = s.scalar(
                select(NakitAvansTaksit).where(NakitAvansTaksit.kk_hareket_belge_no == belge)
            )
            if na_t is None:
                od_na = s.scalar(
                    select(KrediKartiOdeme).where(
                        KrediKartiOdeme.belge_no == belge,
                        KrediKartiOdeme.kaynak_turu == "NAKIT_AVANS",
                    )
                )
                if od_na is not None and getattr(od_na, "nakit_avans_taksit_id", None):
                    na_t = s.get(NakitAvansTaksit, int(od_na.nakit_avans_taksit_id))
            if na_t is not None:
                na_taksit_id = int(na_t.id)
                bagli.append(
                    {
                        "tur": "nakit_avans_taksit",
                        "taksit_id": na_taksit_id,
                        "avans_id": int(na_t.avans_id),
                        "taksit_no": int(na_t.taksit_no),
                        "durum": na_t.durum,
                        "belge_no": belge,
                        "etki": (
                            "Silinince nakit avans taksit geri alınır "
                            "(kalan anapara / ödeme / gider bağları)"
                        ),
                    }
                )

        # Ekstre ödemesi
        from database.models.finans import KrediKartiEkstreOdeme

        ekstre_od = list(
            s.scalars(
                select(KrediKartiEkstreOdeme).where(
                    (KrediKartiEkstreOdeme.finans_belge_no == (h.belge_no or ""))
                    | (KrediKartiEkstreOdeme.belge_no == (h.belge_no or ""))
                )
            ).all()
        )
        for eo in ekstre_od:
            if eo.iptal:
                continue
            bagli.append(
                {
                    "tur": "ekstre_odeme",
                    "id": int(eo.id),
                    "belge_no": eo.belge_no,
                    "tutar": _d(eo.tutar),
                    "ekstre_id": int(eo.ekstre_id),
                }
            )
            engel.append(
                f"Ekstre ödeme bağı: {eo.belge_no} (id={eo.id}) — önce ekstre ödemesini iptal edin."
            )

        # Dengeleyen IPTAL / ÖDEME çifti (aynı tutar, aynı hesap)
        denge = None
        tur = (h.hareket_turu or "").upper()
        if tur == HAREKET_KK:
            aday = s.scalar(
                select(FinansHareketi).where(
                    FinansHareketi.hesap_id == int(h.hesap_id),
                    FinansHareketi.hareket_turu == "KK ÖDEME İPTAL",
                    FinansHareketi.tutar == h.tutar,
                    FinansHareketi.id != int(h.id),
                    FinansHareketi.belge_no.like(f"{(h.belge_no or '')}%IPTAL%"),
                )
            )
            if aday is None:
                # Belge kalıbı OMK-…-IPTAL-TAKSIT
                aday = s.scalar(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == int(h.hesap_id),
                        FinansHareketi.hareket_turu == "KK ÖDEME İPTAL",
                        FinansHareketi.tutar == h.tutar,
                        FinansHareketi.id != int(h.id),
                    ).order_by(FinansHareketi.id.desc())
                )
            if aday is not None:
                denge = _hareket_sozluk(aday, kart_adi=kart_adi)
                bagli.append(
                    {
                        "tur": "denge_iptal",
                        "id": int(aday.id),
                        "belge_no": aday.belge_no,
                        "tutar": _d(aday.tutar),
                        "etki": "Birlikte silinince net etki 0 (çift kaldırılır)",
                    }
                )
        elif tur == "KK ÖDEME İPTAL":
            # Eşleşen asıl ödeme
            kok = (h.belge_no or "").replace("-IPTAL-TAKSIT", "").replace("-IPTAL", "")
            aday = s.scalar(
                select(FinansHareketi).where(
                    FinansHareketi.hesap_id == int(h.hesap_id),
                    FinansHareketi.hareket_turu == HAREKET_KK,
                    FinansHareketi.tutar == h.tutar,
                    FinansHareketi.belge_no == kok,
                )
            )
            if aday is None:
                aday = s.scalar(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == int(h.hesap_id),
                        FinansHareketi.hareket_turu == HAREKET_KK,
                        FinansHareketi.tutar == h.tutar,
                        FinansHareketi.id != int(h.id),
                    ).order_by(FinansHareketi.id)
                )
            if aday is not None:
                denge = _hareket_sozluk(aday, kart_adi=kart_adi)
                bagli.append(
                    {
                        "tur": "denge_odeme",
                        "id": int(aday.id),
                        "belge_no": aday.belge_no,
                        "tutar": _d(aday.tutar),
                        "etki": "Birlikte silinince net etki 0",
                    }
                )

        # POS/banka mutabakat id listesinde geçiyor mu
        from database.models.finans import PosValorKaydi

        for pv in s.scalars(
            select(PosValorKaydi).where(PosValorKaydi.eslesen_banka_hareket_idler.isnot(None))
        ).all():
            idler = {
                int(p.strip())
                for p in (pv.eslesen_banka_hareket_idler or "").split(",")
                if p.strip().isdigit()
            }
            if int(h.id) in idler:
                bagli.append(
                    {
                        "tur": "pos_banka_mutabakat",
                        "pos_valor_id": int(pv.id),
                        "belge_no": pv.belge_no,
                    }
                )
                engel.append(
                    f"POS/banka mutabakat bağı: {pv.belge_no} (valor id={pv.id})"
                )

        return {
            "bulundu": True,
            "zaten_silinmis": False,
            "hareket": _hareket_sozluk(h, kart_adi=kart_adi or ""),
            "kart_adi": kart_adi or "",
            "bagli": bagli,
            "dengeleyen": denge,
            "engel": engel,
            "silinebilir": len(engel) == 0,
            "nakit_avans_taksit_id": na_taksit_id,
        }


def kredi_karti_hareket_sil(
    hareket_id: int,
    *,
    dengeleyen_dahil: bool = True,
    neden: str | None = None,
) -> dict[str, Any]:
    """Seçili KK hesap hareketini id ile sil; isteğe bağlı dengeleyen IPTAL/ÖDEME çifti.

    İkinci çağrıda kayıt yoksa ``zaten_silinmis=True`` — hesap bir kez etkilenir.
    """
    from database.access import yazma_zorunlu
    from database.user_audit import audit_document

    yazma_zorunlu("finans_duzenleme")
    schema_hazirla()
    oniz = kredi_karti_hareket_sil_onizleme(int(hareket_id))
    if oniz.get("zaten_silinmis") or not oniz.get("bulundu"):
        return {
            "silindi": False,
            "zaten_silinmis": True,
            "hareket_id": int(hareket_id),
            "silinen_idler": [],
        }
    if oniz.get("engel"):
        raise ValueError(" / ".join(oniz["engel"]))

    # NAT: ham silme yerine nakit avans taksit geri alma (kalan_anapara / ödeme / gider)
    na_tid = oniz.get("nakit_avans_taksit_id")
    if na_tid:
        from database.nakit_avans_service import NakitAvansService

        sonuc_na = NakitAvansService.taksit_sil(int(na_tid))
        audit_document(
            "KK_HAREKET_SIL_NAKIT_AVANS",
            modul="finans",
            kayit_id=str(hareket_id),
            belge_no=(oniz.get("hareket") or {}).get("belge_no"),
            eski={"hareket": oniz.get("hareket"), "taksit_id": int(na_tid)},
            yeni={"taksit_sil": sonuc_na},
            aciklama=(neden or "NAT nakit avans taksit geri alındı")[:300],
        )
        return {
            "silindi": True,
            "zaten_silinmis": False,
            "hareket_id": int(hareket_id),
            "silinen_idler": [],
            "nakit_avans_taksit_id": int(na_tid),
            "yontem": "nakit_avans_taksit_sil",
            "taksit": sonuc_na,
        }

    silinecek_idler = [int(hareket_id)]
    if dengeleyen_dahil and oniz.get("dengeleyen"):
        silinecek_idler.append(int(oniz["dengeleyen"]["id"]))

    with get_session() as s:
        mevcut = []
        for hid in silinecek_idler:
            h = s.get(FinansHareketi, int(hid))
            if h is not None:
                mevcut.append(h)
        if not mevcut:
            return {
                "silindi": False,
                "zaten_silinmis": True,
                "hareket_id": int(hareket_id),
                "silinen_idler": [],
            }
        eski = [_hareket_sozluk(h) for h in mevcut]
        for h in mevcut:
            # Taksit geri al
            if h.belge_no:
                for t in s.scalars(
                    select(KrediKartiOdemeTaksit).where(
                        KrediKartiOdemeTaksit.kk_hareket_belge_no == h.belge_no
                    )
                ).all():
                    if (t.durum or "").upper() == DURUM_KARTA:
                        t.durum = DURUM_BEKLIYOR
                        t.kk_hareket_belge_no = None
                        t.islem_anahtari = None
            s.delete(h)
        s.flush()
        silinen = [int(x["id"]) for x in eski]
        audit_document(
            "KK_HAREKET_SIL",
            modul="finans",
            kayit_id=str(hareket_id),
            belge_no=eski[0].get("belge_no") if eski else None,
            eski={"hareketler": eski},
            yeni={"silinen_idler": silinen},
            aciklama=(neden or "KK hesap hareketi silindi")[:300],
        )
        return {
            "silindi": True,
            "zaten_silinmis": False,
            "hareket_id": int(hareket_id),
            "silinen_idler": silinen,
            "eski": eski,
        }


def kredi_karti_hareket_cift_sil(hareket_idler: list[int], *, neden: str | None = None) -> dict[str, Any]:
    """Belirli id listesini tek transaction'da sil (dengeleyen 55k+İPTAL gibi)."""
    from database.access import yazma_zorunlu
    from database.user_audit import audit_document

    yazma_zorunlu("finans_duzenleme")
    idler = [int(i) for i in hareket_idler]
    with get_session() as s:
        hareketler = []
        for hid in idler:
            h = s.get(FinansHareketi, hid)
            if h is not None:
                hareketler.append(h)
        if not hareketler:
            return {"silindi": False, "zaten_silinmis": True, "silinen_idler": []}
        # Denge doğrula (2 satır, aynı tutar, zıt yön)
        if len(hareketler) == 2:
            a, b = hareketler
            if _d(a.tutar) != _d(b.tutar):
                raise ValueError("İki hareket tutarı eşit değil; silme iptal.")
            turler = {(a.hareket_turu or "").upper(), (b.hareket_turu or "").upper()}
            if not ({HAREKET_KK, "KK ÖDEME İPTAL"} <= turler or len(turler) == 1):
                # izin: KK ÖDEME + KK ÖDEME İPTAL
                if HAREKET_KK not in turler or "KK ÖDEME İPTAL" not in turler:
                    raise ValueError(
                        f"Beklenen denge çifti değil: {turler}"
                    )
        eski = [_hareket_sozluk(h) for h in hareketler]
        for h in hareketler:
            s.delete(h)
        s.flush()
        audit_document(
            "KK_HAREKET_CIFT_SIL",
            modul="finans",
            kayit_id=",".join(str(i) for i in idler),
            belge_no=eski[0].get("belge_no") if eski else None,
            eski={"hareketler": eski},
            yeni={"silinen_idler": [int(x["id"]) for x in eski]},
            aciklama=(neden or "KK dengeleyen hareket çifti silindi")[:300],
        )
        return {
            "silindi": True,
            "zaten_silinmis": False,
            "silinen_idler": [int(x["id"]) for x in eski],
            "eski": eski,
        }
