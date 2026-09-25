"""Cari kart — bekleyen satış / satın alma siparişleri (ortak hesaplama).

Sipariş tutarı cari bakiyeye veya muhasebe hareketine eklenmez.
Kalan tutar satır bazında fatura kalanı × birim fiyat / iskonto / KDV ile hesaplanır;
sevk ve fatura sayaçları ayrı tutulur (mükerrer düşülmez).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.kalan_belge_service import IPTAL_DURUMLARI, _satir_net_tutar
from database.models.alis_siparisi import AlisSiparisi
from database.models.satis_siparisi import SatisSiparisi
from database.satis_siparisi_service import decimal, satir_kalanlari

SiparisYon = Literal["satis", "alis"]

# Risk / varsayılan listeden hariç
_RISK_HARIC = frozenset({"TASLAK", "İPTAL", "IPTAL", "FATURALI"})


def _pb() -> str:
    """Sipariş modelinde para birimi yok; sistem TRY kabul eder."""
    return "TRY"


def _sifir_alti(deger: Decimal) -> Decimal:
    return deger if deger > 0 else Decimal("0")


def _satir_tutarlari(satir, *, fiyat_alani: str) -> dict[str, Decimal]:
    miktar = decimal(satir.miktar or 0, "Miktar", Decimal("0"))
    sevk = decimal(getattr(satir, "irsaliyelenen_miktar", 0) or 0, "Sevk", Decimal("0"))
    fat = decimal(getattr(satir, "faturalanan_miktar", 0) or 0, "Fatura", Decimal("0"))
    if sevk > miktar:
        sevk = miktar
    if fat > miktar:
        fat = miktar
    kalanlar = satir_kalanlari(miktar, sevk, fat)
    fiyat = getattr(satir, fiyat_alani)
    isk = getattr(satir, "iskonto_orani", 0) or 0
    kdv = getattr(satir, "kdv_orani", 0) or 0

    siparis_t = _satir_net_tutar(miktar, fiyat, isk, kdv)
    sevk_t = _satir_net_tutar(sevk, fiyat, isk, kdv)
    fatura_t = _satir_net_tutar(fat, fiyat, isk, kdv)
    kalan_t = _satir_net_tutar(kalanlar["fatura_kalani"], fiyat, isk, kdv)

    return {
        "miktar": miktar,
        "sevk_miktar": sevk,
        "fatura_miktar": fat,
        "sevk_kalani": _sifir_alti(kalanlar["sevk_kalani"]),
        "fatura_kalani": _sifir_alti(kalanlar["fatura_kalani"]),
        "siparis_brut": siparis_t["brut"],
        "siparis_net": siparis_t["net"],
        "siparis_genel": siparis_t["genel"],
        "sevk_tutar": sevk_t["genel"],
        "fatura_tutar": fatura_t["genel"],
        "kalan_tutar": _sifir_alti(kalan_t["genel"]),
    }


def _siparis_acik_mi(durum: str, satir_ozetleri: list[dict]) -> bool:
    d = (durum or "").strip().upper()
    if d in IPTAL_DURUMLARI or d == "TASLAK":
        return False
    if d == "FATURALI":
        return False
    return any(s["fatura_kalani"] > 0 for s in satir_ozetleri)


def _siparis_ozetle(
    siparis,
    *,
    yon: SiparisYon,
    fiyat_alani: str,
    dahil_kapali: bool,
) -> dict[str, Any] | None:
    durum = (siparis.durum or "").strip()
    durum_u = durum.upper()
    cari = siparis.cari
    satir_ozetleri = [_satir_tutarlari(s, fiyat_alani=fiyat_alani) for s in (siparis.satirlar or [])]

    acik = _siparis_acik_mi(durum, satir_ozetleri)
    # Taslaklar risk/liste varsayılanında yok; kapali filtre acik olsa da gösterme
    if durum_u == "TASLAK":
        return None
    if not dahil_kapali and not acik:
        return None
    if not dahil_kapali and durum_u in _RISK_HARIC:
        return None

    iptal_mi = durum_u in IPTAL_DURUMLARI
    siparis_brut = sum((s["siparis_brut"] for s in satir_ozetleri), Decimal("0"))
    siparis_net = sum((s["siparis_net"] for s in satir_ozetleri), Decimal("0"))
    siparis_genel = sum((s["siparis_genel"] for s in satir_ozetleri), Decimal("0"))
    sevk_tutar = sum((s["sevk_tutar"] for s in satir_ozetleri), Decimal("0"))
    fatura_tutar = sum((s["fatura_tutar"] for s in satir_ozetleri), Decimal("0"))
    fatura_kalani_miktar = sum((s["fatura_kalani"] for s in satir_ozetleri), Decimal("0"))
    sevk_kalani_miktar = sum((s["sevk_kalani"] for s in satir_ozetleri), Decimal("0"))
    kalan_satir_sayisi = sum(1 for s in satir_ozetleri if s["fatura_kalani"] > 0)

    if iptal_mi:
        kalan_tutar = Decimal("0")
        iptal_tutar = siparis_genel
        kalan_satir_sayisi = 0
    else:
        kalan_tutar = sum((s["kalan_tutar"] for s in satir_ozetleri), Decimal("0"))
        iptal_tutar = Decimal("0")

    return {
        "siparis_id": int(siparis.id),
        "siparis_no": siparis.siparis_no or "",
        "siparis_tarihi": siparis.siparis_tarihi,
        "termin_tarihi": siparis.termin_tarihi,
        "cari_id": int(siparis.cari_id),
        "cari_kodu": (cari.cari_kodu if cari else "") or "",
        "cari_unvan": (cari.unvan if cari else "") or "",
        "durum": durum,
        "para_birimi": _pb(),
        "yon": yon,
        "acik": acik and not iptal_mi,
        "siparis_brut": siparis_brut,
        "siparis_net": siparis_net,
        "siparis_genel": siparis_genel,
        "sevk_tutar": sevk_tutar,
        "fatura_tutar": fatura_tutar,
        "iptal_tutar": iptal_tutar,
        "kalan_tutar": kalan_tutar,
        "sevk_kalani_miktar": sevk_kalani_miktar,
        "fatura_kalani_miktar": fatura_kalani_miktar,
        "kalan_satir_sayisi": int(kalan_satir_sayisi),
    }


def _listele_yon(
    *,
    cari_id: int,
    yon: SiparisYon,
    dahil_tamamlanan: bool = False,
    dahil_iptal: bool = False,
    ara: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    cid = int(cari_id)
    dahil_kapali = bool(dahil_tamamlanan or dahil_iptal)
    ara_f = (ara or "").strip().casefold()

    if yon == "satis":
        model = SatisSiparisi
        fiyat_alani = "birim_satis_fiyati"
    else:
        model = AlisSiparisi
        fiyat_alani = "birim_alis_fiyati"

    with get_session() as session:
        stmt = (
            select(model)
            .options(selectinload(model.satirlar), selectinload(model.cari))
            .where(model.cari_id == cid)
            .order_by(model.siparis_tarihi.desc(), model.id.desc())
            .limit(max(1, int(limit)))
        )
        siparisler = list(session.scalars(stmt).all())
        sonuc: list[dict[str, Any]] = []
        for siparis in siparisler:
            durum_u = (siparis.durum or "").strip().upper()
            if not dahil_iptal and durum_u in IPTAL_DURUMLARI:
                continue
            ozet = _siparis_ozetle(
                siparis, yon=yon, fiyat_alani=fiyat_alani, dahil_kapali=dahil_kapali
            )
            if ozet is None:
                continue
            if not dahil_tamamlanan and durum_u == "FATURALI" and ozet["kalan_tutar"] <= 0:
                continue
            if not dahil_iptal and durum_u in IPTAL_DURUMLARI:
                continue
            if ara_f:
                metin = " ".join(
                    [
                        ozet["siparis_no"],
                        ozet["cari_kodu"],
                        ozet["cari_unvan"],
                        ozet["durum"],
                        ozet["para_birimi"],
                    ]
                ).casefold()
                if ara_f not in metin:
                    continue
            sonuc.append(ozet)
        return sonuc


def cari_bekleyen_siparisleri(
    cari_id: int,
    *,
    yon: SiparisYon,
    dahil_tamamlanan: bool = False,
    dahil_iptal: bool = False,
    ara: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Cari ID ile filtrelenmiş sipariş listesi + para birimine göre kalan toplamlar.

    Varsayılan: yalnız açık / kısmen karşılanan siparişler (TASLAK, tam FATURALI, İPTAL hariç).
    """
    if yon not in ("satis", "alis"):
        raise ValueError("yon 'satis' veya 'alis' olmalı.")
    kayitlar = _listele_yon(
        cari_id=cari_id,
        yon=yon,
        dahil_tamamlanan=dahil_tamamlanan,
        dahil_iptal=dahil_iptal,
        ara=ara,
        limit=limit,
    )
    aciklar = [k for k in kayitlar if k.get("acik")]
    toplamlar: dict[str, Decimal] = {}
    for k in aciklar:
        pb = k.get("para_birimi") or "TRY"
        toplamlar[pb] = toplamlar.get(pb, Decimal("0")) + Decimal(str(k["kalan_tutar"] or 0))
    gorunen_toplamlar: dict[str, Decimal] = {}
    for k in kayitlar:
        if not k.get("acik"):
            continue
        pb = k.get("para_birimi") or "TRY"
        gorunen_toplamlar[pb] = gorunen_toplamlar.get(pb, Decimal("0")) + Decimal(
            str(k["kalan_tutar"] or 0)
        )
    return {
        "yon": yon,
        "kayitlar": kayitlar,
        "toplamlar": toplamlar,
        "gorunen_toplamlar": gorunen_toplamlar,
        "adet": len(kayitlar),
        "adet_acik": len(aciklar),
    }


def cari_bekleyen_siparis_ozeti(cari_id: int, *, yon: SiparisYon) -> dict[str, Any]:
    """Kart risk satırı için özet — mevcut bakiye/risk hesaplarını değiştirmez."""
    data = cari_bekleyen_siparisleri(
        cari_id, yon=yon, dahil_tamamlanan=False, dahil_iptal=False
    )
    toplamlar = data["toplamlar"]
    try_toplam = Decimal(str(toplamlar.get("TRY") or 0))
    diger = {k: v for k, v in toplamlar.items() if k != "TRY" and v}
    return {
        "yon": yon,
        "adet": data["adet_acik"],
        "toplamlar": toplamlar,
        "toplam_try": try_toplam,
        "diger_pb": diger,
        "etiket": (
            "Bekleyen satış siparişleri"
            if yon == "satis"
            else "Bekleyen satın alma siparişleri"
        ),
    }


def ornek_bekleyen_tutar(
    siparis_miktar: Decimal | int | str = 10,
    karsilanan: Decimal | int | str = 4,
    iptal: Decimal | int | str = 1,
    birim_fiyat: Decimal | int | str = 100,
    iskonto_orani: Decimal | int | str = 0,
    kdv_orani: Decimal | int | str = 0,
) -> dict[str, Decimal]:
    """Talimat örneği: 10 − 4 − 1 = 5 adet → 500 TL (KDV/iskonto yoksa)."""
    m = decimal(siparis_miktar, "Miktar", Decimal("0"))
    k = decimal(karsilanan, "Karşılanan", Decimal("0"))
    i = decimal(iptal, "İptal", Decimal("0"))
    kalan_m = _sifir_alti(m - k - i)
    t = _satir_net_tutar(kalan_m, birim_fiyat, iskonto_orani, kdv_orani)
    return {
        "kalan_miktar": kalan_m,
        "kalan_tutar": t["genel"],
        "brut": t["brut"],
        "net": t["net"],
    }
