"""Teklif fiyat motoru — maliyet üstü kâr + maktu + masraf dağıtımı.

Decimal; KDV hariç net satış üzerinden kâr. Eski API'ler korunur.
Yeni: maliyet_getir, dagitimli_hesapla, tahmini_teslim_hesapla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from database.access import maliyet_izinli
from database.stok_service import StokService

YUVARLAMA = Literal["kurus", "1", "5", "10", "psikolojik", "yok"]

FIYAT_YONTEMLERI = (
    "FIYAT_LISTESI",
    "SON_SATIS",
    "MUSTERI_SON_SATIS",
    "MALIYET_USTU_ORAN",
    "HEDEF_MARJ",
    "MAKTU_KAR",
    "MANUEL",
    "LISTE_INDIRIM",
)

MALIYET_KAYNAKLARI = (
    "SON_ALIS",
    "FIFO",
    "ORTALAMA",
    "AGIRLIKLI",
    "STANDART",
    "STOK_KARTI",
    "MANUEL",
)

MALIYET_KAYNAK_ETIKET = {
    "SON_ALIS": "Son Alış Faturası",
    "FIFO": "FIFO",
    "ORTALAMA": "Ortalama",
    "AGIRLIKLI": "Ağırlıklı Ortalama",
    "STANDART": "Standart",
    "STOK_KARTI": "Stok Kartı Alış",
    "MANUEL": "Manuel",
}

TERMIN_TURLERI = (
    "Takvim Günü",
    "İş Günü",
    "Stoktan",
    "Sipariş Üzerine",
    "Anlaşmaya Göre",
)

MASRAF_TURLERi = (
    "Nakliye",
    "Montaj",
    "Ambalaj",
    "Sigorta",
    "Komisyon",
    "Gümrük",
    "Diğer",
)

_KURUS = Decimal("0.01")
_DORT = Decimal("0.0001")
_ALTI = Decimal("0.000001")


def _d(deger, alan: str = "Değer", minimum: Decimal | None = None) -> Decimal:
    try:
        if isinstance(deger, Decimal):
            s = deger
        else:
            m = str(deger).strip().replace(" ", "")
            if "," in m:
                m = m.replace(".", "").replace(",", ".")
            s = Decimal(m or "0")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from exc
    if minimum is not None and s < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return s


def yuvarla(fiyat: Decimal, kural: YUVARLAMA = "kurus") -> Decimal:
    if kural == "yok":
        return fiyat
    if kural == "kurus":
        return fiyat.quantize(_KURUS, rounding=ROUND_HALF_UP)
    if kural == "1":
        return fiyat.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if kural == "5":
        return (fiyat / 5).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 5
    if kural == "10":
        return (fiyat / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10
    if kural == "psikolojik":
        ust = (fiyat / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10
        return max(ust - Decimal("1"), _KURUS)
    return fiyat.quantize(_KURUS, rounding=ROUND_HALF_UP)


@dataclass
class CostSnapshot:
    birim_maliyet: Decimal = Decimal("0")
    maliyet_kaynagi: str = "SON_ALIS"
    purchase_unit_price: Decimal = Decimal("0")
    purchase_currency: str = "TRY"
    purchase_exchange_rate: Decimal = Decimal("1")
    purchase_unit_price_base: Decimal = Decimal("0")
    cost_source_date: date | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None
    maliyet_hesap_zamani: datetime | None = None
    uyari: str | None = None


@dataclass
class PriceCalculationResult:
    maliyet_kaynagi: str = ""
    birim_maliyet: Decimal = Decimal("0")
    yontem: str = "MANUEL"
    oran_veya_tutar: Decimal = Decimal("0")
    liste_fiyati: Decimal = Decimal("0")
    teklif_fiyati: Decimal = Decimal("0")
    net_birim_fiyat: Decimal = Decimal("0")
    iskonto_1: Decimal = Decimal("0")
    iskonto_2: Decimal = Decimal("0")
    iskonto_3: Decimal = Decimal("0")
    kdv_orani: Decimal = Decimal("20")
    satir_ara: Decimal = Decimal("0")
    satir_kdv: Decimal = Decimal("0")
    satir_toplam: Decimal = Decimal("0")
    kar_orani: Decimal = Decimal("0")
    gercek_marj: Decimal = Decimal("0")
    maliyet_hesap_zamani: datetime | None = None
    uyari: str | None = None
    ekstra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DagitimSatirSonucu:
    index: int
    purchase_total_cost: Decimal
    share: Decimal
    allocated_percentage_profit: Decimal
    allocated_fixed_profit: Decimal
    allocated_expense: Decimal
    calculated_offer_unit_price: Decimal
    final_offer_unit_price: Decimal
    satir_ara: Decimal
    actual_profit_amount: Decimal
    actual_margin_rate: Decimal
    is_manual_price: bool = False


@dataclass
class DagitimSonucu:
    satirlar: list[dict[str, Any]]
    total_purchase_cost: Decimal
    percentage_profit_amount: Decimal
    fixed_profit_amount: Decimal
    customer_expense_amount: Decimal
    internal_expense_amount: Decimal
    total_target_profit: Decimal
    calculated_offer_subtotal: Decimal
    actual_profit_amount: Decimal
    cost_markup_rate: Decimal
    sales_margin_rate: Decimal
    yuvarlama: str = "kurus"
    calculation_method: str = "MALIYET_USTU_KAR"
    satir_sonuclari: list[DagitimSatirSonucu] = field(default_factory=list)


def net_iskontolu(fiyat: Decimal, i1=0, i2=0, i3=0) -> Decimal:
    n = fiyat
    for oran in (_d(i1), _d(i2), _d(i3)):
        if oran:
            n = n * (Decimal("1") - oran / Decimal("100"))
    return n.quantize(_DORT, rounding=ROUND_HALF_UP)


def kar_metrikleri(net: Decimal, maliyet: Decimal) -> tuple[Decimal, Decimal]:
    """(maliyet_üstü_oran %, gerçek_marj %)."""
    if maliyet > 0 and net > 0:
        oran = ((net - maliyet) / maliyet * 100).quantize(_KURUS, rounding=ROUND_HALF_UP)
    else:
        oran = Decimal("0")
    if net > 0:
        marj = ((net - maliyet) / net * 100).quantize(_KURUS, rounding=ROUND_HALF_UP)
    else:
        marj = Decimal("0")
    return oran, marj


def tahmini_teslim_hesapla(teklif_tarihi: date | None, termin_gun: int | None) -> date | None:
    if teklif_tarihi is None or termin_gun is None:
        return None
    gun = int(termin_gun)
    if gun < 0:
        raise ValueError("Termin süresi negatif olamaz.")
    return teklif_tarihi + timedelta(days=gun)


def _son_alis_fatura_detay(urun_kodu: str) -> CostSnapshot | None:
    """Son alış faturası net (iskonto dahil, KDV hariç) + tedarikçi/tarih."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri

    kod = (urun_kodu or "").strip()
    if not kod:
        return None
    try:
        with get_session() as session:
            satir = session.scalar(
                select(AlisFaturasiSatiri)
                .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                .options(selectinload(AlisFaturasiSatiri.fatura).selectinload(AlisFaturasi.cari))
                .where(
                    AlisFaturasiSatiri.urun_kodu == kod,
                    AlisFaturasi.durum != "İPTAL",
                )
                .order_by(
                    AlisFaturasi.fatura_tarihi.desc(),
                    AlisFaturasi.id.desc(),
                    AlisFaturasiSatiri.id.desc(),
                )
            )
            if not satir:
                return None
            fatura = satir.fatura
            birim = _d(satir.birim_fiyat)
            # Döviz satırı varsa tercih et; net = iskontolu
            if _d(getattr(satir, "birim_fiyat_doviz", 0) or 0) > 0:
                birim = _d(satir.birim_fiyat_doviz)
            oran = _d(satir.iskonto_orani or 0)
            net = (birim * (Decimal("1") - oran / Decimal("100"))).quantize(_DORT, rounding=ROUND_HALF_UP)
            pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
            kur = _d(getattr(fatura, "kur", 1) or 1)
            if kur <= 0:
                kur = Decimal("1")
            base = net if pb in ("TRY", "TL") else (net * kur).quantize(_ALTI, rounding=ROUND_HALF_UP)
            if pb in ("TRY", "TL") and _d(getattr(satir, "tl_birim_fiyat", 0) or 0) > 0:
                # TL birim fiyat iskontosuz olabilir; net hesaplananı kullan
                pass
            supplier_id = getattr(fatura, "cari_id", None)
            supplier_name = None
            if getattr(fatura, "cari", None) is not None:
                supplier_name = getattr(fatura.cari, "unvan", None)
            return CostSnapshot(
                birim_maliyet=base.quantize(_DORT, rounding=ROUND_HALF_UP),
                maliyet_kaynagi="SON_ALIS",
                purchase_unit_price=net,
                purchase_currency=pb if pb != "TL" else "TRY",
                purchase_exchange_rate=kur,
                purchase_unit_price_base=base.quantize(_DORT, rounding=ROUND_HALF_UP),
                cost_source_date=getattr(fatura, "fatura_tarihi", None),
                supplier_id=int(supplier_id) if supplier_id else None,
                supplier_name=supplier_name,
                maliyet_hesap_zamani=datetime.now(),
            )
    except Exception:
        return None


def maliyet_getir(
    urun_kodu: str,
    depo: str = "ANA DEPO",
    kaynagi: str = "SON_ALIS",
    manuel: Decimal | None = None,
) -> CostSnapshot:
    """Alış maliyeti anlık görüntüsü — kaynak + fallback zinciri."""
    kay = (kaynagi or "SON_ALIS").upper().replace(" ", "_")
    now = datetime.now()
    if not maliyet_izinli() and kay != "MANUEL":
        return CostSnapshot(
            maliyet_kaynagi=kay,
            maliyet_hesap_zamani=now,
            uyari="Maliyet görme yetkisi yok",
        )

    if kay == "MANUEL":
        tutar = _d(manuel or 0)
        return CostSnapshot(
            birim_maliyet=tutar,
            maliyet_kaynagi="MANUEL",
            purchase_unit_price=tutar,
            purchase_unit_price_base=tutar,
            maliyet_hesap_zamani=now,
            uyari=None if tutar > 0 else "Manuel maliyet girilmedi",
        )

    # 1) İstenen kaynak SON_ALIS (veya varsayılan zincir başlangıcı)
    if kay in ("SON_ALIS", "STANDART"):
        snap = _son_alis_fatura_detay(urun_kodu)
        if snap and snap.birim_maliyet > 0:
            return snap

    # 2) Stok lot maliyetleri (AGIRLIKLI / FIFO / ORTALAMA / SON_ALIS lot)
    try:
        m = StokService.maliyetler(urun_kodu, depo or "ANA DEPO")
    except Exception:
        m = {}
    map_key = {
        "FIFO": "fifo",
        "SON_ALIS": "son_alis",
        "ORTALAMA": "ortalama",
        "AGIRLIKLI": "agirlikli",
        "STANDART": "agirlikli",
        "STOK_KARTI": "son_alis",
    }.get(kay, "agirlikli")
    lot_tutar = _d(m.get(map_key, 0) if m else 0)
    if kay in ("AGIRLIKLI", "FIFO", "ORTALAMA") and lot_tutar > 0:
        return CostSnapshot(
            birim_maliyet=lot_tutar,
            maliyet_kaynagi=kay,
            purchase_unit_price=lot_tutar,
            purchase_unit_price_base=lot_tutar,
            maliyet_hesap_zamani=now,
        )
    if lot_tutar > 0 and kay in ("SON_ALIS", "STANDART"):
        return CostSnapshot(
            birim_maliyet=lot_tutar,
            maliyet_kaynagi="AGIRLIKLI" if kay == "STANDART" else "SON_ALIS",
            purchase_unit_price=lot_tutar,
            purchase_unit_price_base=lot_tutar,
            maliyet_hesap_zamani=now,
            uyari="Son alış faturası yok; stok maliyeti kullanıldı",
        )

    # 3) Stok kartı ALIŞ FİYATI
    try:
        kart = _d(StokService.son_alis_fiyati(urun_kodu, Decimal("0")))
    except Exception:
        kart = Decimal("0")
    if kart > 0:
        kaynak = "STOK_KARTI" if kay == "STOK_KARTI" else "STOK_KARTI"
        return CostSnapshot(
            birim_maliyet=kart,
            maliyet_kaynagi=kaynak,
            purchase_unit_price=kart,
            purchase_unit_price_base=kart,
            maliyet_hesap_zamani=now,
            uyari="Fatura/lot yok; stok kartı alış fiyatı kullanıldı",
        )

    # AGIRLIKLI istenmiş ama boşsa yine fallback dene (yukarıda zaten bitti)
    if kay == "AGIRLIKLI" and lot_tutar <= 0:
        snap = _son_alis_fatura_detay(urun_kodu)
        if snap and snap.birim_maliyet > 0:
            snap.uyari = "Ağırlıklı maliyet yok; son alış kullanıldı"
            return snap

    return CostSnapshot(
        maliyet_kaynagi=kay,
        maliyet_hesap_zamani=now,
        uyari="Alış maliyeti bulunamadı",
    )


def maliyet_snapshot(urun_kodu: str, depo: str, kaynagi: str) -> tuple[Decimal, str, datetime]:
    """Geriye uyumlu: (birim_maliyet, kaynak, zaman). Varsayılan SON_ALIS."""
    snap = maliyet_getir(urun_kodu, depo, kaynagi or "SON_ALIS")
    return snap.birim_maliyet, snap.maliyet_kaynagi, snap.maliyet_hesap_zamani or datetime.now()


def fiyat_hesapla(
    *,
    yontem: str,
    birim_maliyet: Decimal = Decimal("0"),
    liste_fiyati: Decimal = Decimal("0"),
    son_satis: Decimal = Decimal("0"),
    musteri_son_satis: Decimal = Decimal("0"),
    oran_veya_tutar: Decimal = Decimal("0"),
    manuel_fiyat: Decimal | None = None,
    iskonto_1: Decimal = Decimal("0"),
    iskonto_2: Decimal = Decimal("0"),
    iskonto_3: Decimal = Decimal("0"),
    kdv_orani: Decimal = Decimal("20"),
    miktar: Decimal = Decimal("1"),
    yuvarlama: YUVARLAMA = "kurus",
    maliyet_kaynagi: str = "",
) -> PriceCalculationResult:
    return QuotePricingService.fiyat_hesapla(
        yontem=yontem,
        birim_maliyet=birim_maliyet,
        liste_fiyati=liste_fiyati,
        son_satis=son_satis,
        musteri_son_satis=musteri_son_satis,
        oran_veya_tutar=oran_veya_tutar,
        manuel_fiyat=manuel_fiyat,
        iskonto_1=iskonto_1,
        iskonto_2=iskonto_2,
        iskonto_3=iskonto_3,
        kdv_orani=kdv_orani,
        miktar=miktar,
        yuvarlama=yuvarlama,
        maliyet_kaynagi=maliyet_kaynagi,
    )


def satir_toplamlari(satirlar: list[dict] | list[Any]) -> dict[str, Decimal]:
    return QuotePricingService.satir_toplamlari(satirlar)


def apply_bulk_pricing(
    satirlar: list[dict],
    *,
    yontem: str,
    oran_veya_tutar: Decimal = Decimal("0"),
    maliyet_kaynagi: str = "SON_ALIS",
    depo: str = "ANA DEPO",
    yuvarlama: YUVARLAMA = "kurus",
) -> list[dict]:
    return QuotePricingService.apply_bulk_pricing(
        satirlar,
        yontem=yontem,
        oran_veya_tutar=oran_veya_tutar,
        maliyet_kaynagi=maliyet_kaynagi,
        depo=depo,
        yuvarlama=yuvarlama,
    )


def dagitimli_hesapla(
    satirlar: list[dict],
    profit_rate=0,
    fixed_profit_amount=0,
    customer_expense_amount=0,
    internal_expense_amount=0,
    yuvarlama: YUVARLAMA = "kurus",
    manuel_koru: bool = False,
    calculation_method: str = "MALIYET_USTU_KAR",
    skip_missing_manual_cost: bool = False,
) -> DagitimSonucu:
    """Alış + %kâr + maktu + müşteri masrafını satır alış payına göre dağıtır.

    New_toplam = purchase + %profit_amount + fixed + customer_expense
    Satır payı = satır_alış / toplam_alış; kuruş farkı en büyük paylı satıra.
    """
    if not satirlar:
        raise ValueError("Dağıtım için en az bir satır gerekli.")

    profit_rate = _d(profit_rate, "Kâr oranı", Decimal("0"))
    fixed_profit_amount = _d(fixed_profit_amount, "Maktu kâr", Decimal("0"))
    customer_expense_amount = _d(customer_expense_amount, "Teklif masrafı", Decimal("0"))
    internal_expense_amount = _d(internal_expense_amount, "İç masraf", Decimal("0"))

    hazir: list[dict[str, Any]] = []
    for i, s in enumerate(satirlar):
        row = dict(s)
        miktar = _d(row.get("miktar", 0), "Miktar", Decimal("0.0001"))
        unit_base = _d(
            row.get("purchase_unit_price_base")
            or row.get("birim_maliyet")
            or row.get("purchase_unit_price")
            or 0
        )
        purchase_total = _d(row.get("purchase_total_cost") or 0)
        if purchase_total <= 0:
            purchase_total = (unit_base * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        row["_idx"] = i
        row["_miktar"] = miktar
        row["_unit_base"] = unit_base
        row["_purchase_total"] = purchase_total
        row["_manuel"] = bool(row.get("is_manual_price")) and manuel_koru
        # Eksik maliyetli manuel ürün: yanıltıcı kâr üretme — dağıtımdan çıkar
        if bool(row.get("is_manual_item") or row.get("manuel")) and (
            unit_base <= 0 or (row.get("cost_status") or "").upper() == "EKSIK"
        ):
            if skip_missing_manual_cost:
                row["_manuel"] = True
                row["_eksik_maliyet"] = True
            else:
                raise ValueError(
                    f"Manuel ürünün alış maliyeti eksik: {row.get('urun_adi') or row.get('urun_kodu')}. "
                    "Maliyet girin, satış fiyatını elle belirleyin veya satırı dağıtım dışında bırakın."
                )
        hazir.append(row)

    dagitilacak = [r for r in hazir if not r["_manuel"]]
    if not dagitilacak:
        raise ValueError("Tüm satırlar manuel; yeniden hesaplanacak satır yok.")

    for r in dagitilacak:
        if r["_unit_base"] <= 0 or r["_purchase_total"] <= 0:
            kod = r.get("urun_kodu") or "?"
            raise ValueError(f"Alış maliyeti eksik veya sıfır: {kod}")

    total_purchase = sum((r["_purchase_total"] for r in dagitilacak), Decimal("0"))
    if total_purchase <= 0:
        raise ValueError("Toplam alış maliyeti sıfır; fiyat dağıtılamaz.")

    percentage_profit_amount = (total_purchase * profit_rate / Decimal("100")).quantize(
        _KURUS, rounding=ROUND_HALF_UP
    )
    total_target_profit = percentage_profit_amount + fixed_profit_amount
    hedef_dagitim_toplam = (
        total_purchase + total_target_profit + customer_expense_amount
    ).quantize(_KURUS, rounding=ROUND_HALF_UP)

    # Paylar ve ön yuvarlama
    on_hesap: list[tuple[dict, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    # (row, share, alloc_pct, alloc_fix, alloc_exp, unit_raw)
    for r in dagitilacak:
        share = (r["_purchase_total"] / total_purchase).quantize(_ALTI, rounding=ROUND_HALF_UP)
        alloc_pct = (percentage_profit_amount * share).quantize(_ALTI, rounding=ROUND_HALF_UP)
        alloc_fix = (fixed_profit_amount * share).quantize(_ALTI, rounding=ROUND_HALF_UP)
        alloc_exp = (customer_expense_amount * share).quantize(_ALTI, rounding=ROUND_HALF_UP)
        line_total = r["_purchase_total"] + alloc_pct + alloc_fix + alloc_exp
        unit_raw = line_total / r["_miktar"]
        on_hesap.append((r, share, alloc_pct, alloc_fix, alloc_exp, unit_raw))

    # Birim fiyat yuvarla
    for r, share, alloc_pct, alloc_fix, alloc_exp, unit_raw in on_hesap:
        unit = yuvarla(unit_raw, yuvarlama)
        r["_share"] = share
        r["_alloc_pct"] = alloc_pct.quantize(_DORT, rounding=ROUND_HALF_UP)
        r["_alloc_fix"] = alloc_fix.quantize(_DORT, rounding=ROUND_HALF_UP)
        r["_alloc_exp"] = alloc_exp.quantize(_DORT, rounding=ROUND_HALF_UP)
        r["_calc_unit"] = unit
        r["_final_unit"] = unit
        r["_satir_ara"] = (unit * r["_miktar"]).quantize(_KURUS, rounding=ROUND_HALF_UP)

    # Kuruş farkını en büyük paylı satıra yaz
    mevcut_toplam = sum((r["_satir_ara"] for r in dagitilacak), Decimal("0"))
    fark = (hedef_dagitim_toplam - mevcut_toplam).quantize(_KURUS, rounding=ROUND_HALF_UP)
    if fark != 0 and dagitilacak:
        en_buyuk = max(dagitilacak, key=lambda x: (x["_share"], x["_purchase_total"], -x["_idx"]))
        en_buyuk["_satir_ara"] = (en_buyuk["_satir_ara"] + fark).quantize(_KURUS, rounding=ROUND_HALF_UP)
        en_buyuk["_final_unit"] = (en_buyuk["_satir_ara"] / en_buyuk["_miktar"]).quantize(
            _ALTI, rounding=ROUND_HALF_UP
        )
        # Dağıtılan kalemlere de farkı expense/profit olarak yansıtma — satır ara doğruluğu yeterli

    kontrol = sum((r["_satir_ara"] for r in dagitilacak), Decimal("0"))
    if kontrol != hedef_dagitim_toplam:
        raise ValueError(
            f"Dağıtım toplamı eşleşmedi: satırlar={kontrol}, hedef={hedef_dagitim_toplam}"
        )

    # Manuel korunan satırların ara toplamları
    manuel_ara = Decimal("0")
    for r in hazir:
        if not r["_manuel"]:
            continue
        miktar = r["_miktar"]
        fiyat = _d(r.get("teklif_fiyati") or r.get("manual_offer_unit_price") or 0)
        net = _d(r.get("net_birim_fiyat") or 0)
        if net <= 0:
            net = net_iskontolu(
                fiyat,
                r.get("iskonto_orani", 0),
                r.get("iskonto_orani_2", 0),
                r.get("iskonto_orani_3", 0),
            )
        ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        r["_satir_ara"] = ara
        r["_final_unit"] = fiyat
        r["_calc_unit"] = _d(r.get("calculated_offer_unit_price") or fiyat)
        r["_share"] = Decimal("0")
        r["_alloc_pct"] = Decimal("0")
        r["_alloc_fix"] = Decimal("0")
        r["_alloc_exp"] = Decimal("0")
        manuel_ara += ara

    calculated_offer_subtotal = (hedef_dagitim_toplam + manuel_ara).quantize(
        _KURUS, rounding=ROUND_HALF_UP
    )
    # Gerçek kâr: teklif ara − alış − müşteri masrafı − iç masraf
    # (müşteri masrafı fiyata dahil ama kâr değil)
    all_purchase = sum((r["_purchase_total"] for r in hazir), Decimal("0"))
    actual_profit = (
        calculated_offer_subtotal
        - all_purchase
        - customer_expense_amount
        - internal_expense_amount
    ).quantize(_KURUS, rounding=ROUND_HALF_UP)
    cost_markup = (
        (actual_profit / all_purchase * 100).quantize(_KURUS, rounding=ROUND_HALF_UP)
        if all_purchase > 0
        else Decimal("0")
    )
    sales_margin = (
        (actual_profit / calculated_offer_subtotal * 100).quantize(_KURUS, rounding=ROUND_HALF_UP)
        if calculated_offer_subtotal > 0
        else Decimal("0")
    )

    sonuc_satirlar: list[dict[str, Any]] = []
    satir_sonuclari: list[DagitimSatirSonucu] = []
    for r in hazir:
        miktar = r["_miktar"]
        unit = r["_final_unit"]
        i1 = r.get("iskonto_orani", 0)
        i2 = r.get("iskonto_orani_2", 0)
        i3 = r.get("iskonto_orani_3", 0)
        net = net_iskontolu(unit, i1, i2, i3) if not r["_manuel"] else _d(
            r.get("net_birim_fiyat") or net_iskontolu(unit, i1, i2, i3)
        )
        if not r["_manuel"]:
            net = net_iskontolu(unit, i1, i2, i3)
        kdv_o = _d(r.get("kdv_orani", 20))
        ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        # İskontosuz dağıtım hedefi için teklif_fiyati = final unit; iskonto varsa ara farklı olabilir
        # Dağıtım iskonto öncesi birim fiyat üretir — satır_ara dağıtım hedefiyle uyum için
        # iskonto yoksa ara == _satir_ara
        if _d(i1) == 0 and _d(i2) == 0 and _d(i3) == 0 and not r["_manuel"]:
            ara = r["_satir_ara"]
            net = (ara / miktar).quantize(_DORT, rounding=ROUND_HALF_UP) if miktar else unit
        kdv = (ara * kdv_o / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
        mal = r["_unit_base"]
        kar_oran, marj = kar_metrikleri(net, mal)
        line_profit = (ara - r["_purchase_total"] - r.get("_alloc_exp", Decimal("0"))).quantize(
            _KURUS, rounding=ROUND_HALF_UP
        )
        line_margin = (
            (line_profit / ara * 100).quantize(_KURUS, rounding=ROUND_HALF_UP) if ara else Decimal("0")
        )

        out = {k: v for k, v in r.items() if not str(k).startswith("_")}
        if r.get("_eksik_maliyet") or (
            mal <= 0 and bool(r.get("is_manual_item") or r.get("manuel"))
        ):
            kar_oran = Decimal("0")
            marj = Decimal("0")
            line_profit = Decimal("0")
            line_margin = Decimal("0")
            out["cost_status"] = "EKSIK"
            out["margin_unavailable"] = True
        out.update(
            {
                "birim_maliyet": mal,
                "purchase_unit_price": _d(r.get("purchase_unit_price") or mal),
                "purchase_unit_price_base": mal,
                "purchase_total_cost": r["_purchase_total"],
                "allocated_percentage_profit": r.get("_alloc_pct", Decimal("0")),
                "allocated_fixed_profit": r.get("_alloc_fix", Decimal("0")),
                "allocated_expense": r.get("_alloc_exp", Decimal("0")),
                "calculated_offer_unit_price": r.get("_calc_unit", unit),
                "final_offer_unit_price": unit,
                "teklif_fiyati": unit,
                "net_birim_fiyat": net,
                "satir_toplam": ara + kdv,
                "satir_ara": ara,
                "kar_orani": kar_oran,
                "gercek_marj": marj,
                "actual_profit_amount": line_profit,
                "actual_margin_rate": line_margin,
                "fiyat_yontemi": calculation_method,
                "is_manual_price": bool(r.get("is_manual_price")) if r["_manuel"] else False,
            }
        )
        if not r["_manuel"]:
            out["is_manual_price"] = False
            out["manual_offer_unit_price"] = None
        sonuc_satirlar.append(out)
        satir_sonuclari.append(
            DagitimSatirSonucu(
                index=int(r["_idx"]),
                purchase_total_cost=r["_purchase_total"],
                share=r.get("_share", Decimal("0")),
                allocated_percentage_profit=r.get("_alloc_pct", Decimal("0")),
                allocated_fixed_profit=r.get("_alloc_fix", Decimal("0")),
                allocated_expense=r.get("_alloc_exp", Decimal("0")),
                calculated_offer_unit_price=r.get("_calc_unit", unit),
                final_offer_unit_price=unit,
                satir_ara=ara,
                actual_profit_amount=line_profit,
                actual_margin_rate=line_margin,
                is_manual_price=bool(out["is_manual_price"]),
            )
        )

    # İskontosuz senaryoda satır ara toplamları == calculated_offer_subtotal (manuel dahil)
    ara_sum = sum((_d(s.get("satir_ara", 0)) for s in sonuc_satirlar), Decimal("0"))
    # Hedef yalnızca dağıtılan + manuel; iskonto varsa fark olabilir — iskontosuz doğrula
    if all(
        _d(s.get("iskonto_orani", 0)) == 0
        and _d(s.get("iskonto_orani_2", 0)) == 0
        and _d(s.get("iskonto_orani_3", 0)) == 0
        for s in sonuc_satirlar
    ):
        if ara_sum != calculated_offer_subtotal:
            raise ValueError(
                f"Satır toplamları başlık ile uyuşmuyor: {ara_sum} != {calculated_offer_subtotal}"
            )

    return DagitimSonucu(
        satirlar=sonuc_satirlar,
        total_purchase_cost=all_purchase.quantize(_KURUS, rounding=ROUND_HALF_UP),
        percentage_profit_amount=percentage_profit_amount,
        fixed_profit_amount=fixed_profit_amount,
        customer_expense_amount=customer_expense_amount,
        internal_expense_amount=internal_expense_amount,
        total_target_profit=total_target_profit,
        calculated_offer_subtotal=calculated_offer_subtotal,
        actual_profit_amount=actual_profit,
        cost_markup_rate=cost_markup,
        sales_margin_rate=sales_margin,
        yuvarlama=yuvarlama,
        calculation_method=calculation_method,
        satir_sonuclari=satir_sonuclari,
    )


class QuotePricingService:
    """Merkezi teklif fiyat hesaplama."""

    maliyet_getir = staticmethod(maliyet_getir)
    dagitimli_hesapla = staticmethod(dagitimli_hesapla)
    tahmini_teslim_hesapla = staticmethod(tahmini_teslim_hesapla)

    @staticmethod
    def maliyet_snapshot(urun_kodu: str, depo: str, kaynagi: str) -> tuple[Decimal, str, datetime]:
        return maliyet_snapshot(urun_kodu, depo, kaynagi or "SON_ALIS")

    @staticmethod
    def fiyat_hesapla(
        *,
        yontem: str,
        birim_maliyet: Decimal = Decimal("0"),
        liste_fiyati: Decimal = Decimal("0"),
        son_satis: Decimal = Decimal("0"),
        musteri_son_satis: Decimal = Decimal("0"),
        oran_veya_tutar: Decimal = Decimal("0"),
        manuel_fiyat: Decimal | None = None,
        iskonto_1: Decimal = Decimal("0"),
        iskonto_2: Decimal = Decimal("0"),
        iskonto_3: Decimal = Decimal("0"),
        kdv_orani: Decimal = Decimal("20"),
        miktar: Decimal = Decimal("1"),
        yuvarlama: YUVARLAMA = "kurus",
        maliyet_kaynagi: str = "",
    ) -> PriceCalculationResult:
        yontem = (yontem or "MANUEL").upper()
        maliyet = _d(birim_maliyet)
        oran = _d(oran_veya_tutar)
        uyari = None

        if yontem == "FIYAT_LISTESI":
            fiyat = _d(liste_fiyati)
        elif yontem == "SON_SATIS":
            fiyat = _d(son_satis) if son_satis else _d(liste_fiyati)
        elif yontem == "MUSTERI_SON_SATIS":
            fiyat = _d(musteri_son_satis) if musteri_son_satis else _d(son_satis or liste_fiyati)
        elif yontem == "MALIYET_USTU_ORAN":
            if maliyet <= 0:
                raise ValueError("Maliyet üstü oran için geçerli maliyet kaynağı gerekli.")
            fiyat = maliyet * (Decimal("1") + oran / Decimal("100"))
        elif yontem == "HEDEF_MARJ":
            if maliyet <= 0:
                raise ValueError("Hedef marj için geçerli maliyet kaynağı gerekli.")
            if oran >= 100:
                raise ValueError("Hedef marj %100 veya üzeri olamaz.")
            fiyat = maliyet / (Decimal("1") - oran / Decimal("100"))
        elif yontem == "MAKTU_KAR":
            if maliyet <= 0:
                raise ValueError("Maktu kâr için geçerli maliyet kaynağı gerekli.")
            fiyat = maliyet + oran
        elif yontem == "LISTE_INDIRIM":
            fiyat = _d(liste_fiyati) * (Decimal("1") - oran / Decimal("100"))
        else:  # MANUEL
            if manuel_fiyat is None:
                raise ValueError("Manuel fiyat girilmelidir.")
            fiyat = _d(manuel_fiyat)

        fiyat = yuvarla(fiyat, yuvarlama)
        net = net_iskontolu(fiyat, iskonto_1, iskonto_2, iskonto_3)
        miktar = _d(miktar, "Miktar", Decimal("0.0001"))
        ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        kdv = (ara * _d(kdv_orani) / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
        toplam = ara + kdv
        kar_oran, marj = kar_metrikleri(net, maliyet)

        if maliyet > 0 and net < maliyet:
            uyari = "Maliyet altı fiyat"
        elif marj < Decimal("5") and maliyet > 0:
            uyari = "Minimum marj altında"

        return PriceCalculationResult(
            maliyet_kaynagi=maliyet_kaynagi,
            birim_maliyet=maliyet,
            yontem=yontem,
            oran_veya_tutar=oran,
            liste_fiyati=_d(liste_fiyati),
            teklif_fiyati=fiyat,
            net_birim_fiyat=net,
            iskonto_1=_d(iskonto_1),
            iskonto_2=_d(iskonto_2),
            iskonto_3=_d(iskonto_3),
            kdv_orani=_d(kdv_orani),
            satir_ara=ara,
            satir_kdv=kdv,
            satir_toplam=toplam,
            kar_orani=kar_oran,
            gercek_marj=marj,
            maliyet_hesap_zamani=datetime.now(),
            uyari=uyari,
        )

    @staticmethod
    def satir_toplamlari(satirlar: list[dict] | list[Any]) -> dict[str, Decimal]:
        brut = Decimal("0")
        isk = Decimal("0")
        ara = Decimal("0")
        kdv = Decimal("0")
        genel = Decimal("0")
        maliyet = Decimal("0")
        for s in satirlar:
            if isinstance(s, dict):
                dahil = s.get("toplama_dahil", True)
                ops = s.get("opsiyonel", False)
                if ops and not dahil:
                    continue
                miktar = _d(s.get("miktar", 0))
                liste = _d(s.get("teklif_fiyati", s.get("liste_fiyati", 0)))
                net = _d(s.get("net_birim_fiyat", 0))
                if net <= 0:
                    net = net_iskontolu(
                        liste,
                        s.get("iskonto_orani", 0),
                        s.get("iskonto_orani_2", 0),
                        s.get("iskonto_orani_3", 0),
                    )
                kdv_o = _d(s.get("kdv_orani", 20))
                mal = _d(s.get("birim_maliyet", s.get("purchase_unit_price_base", 0)))
            else:
                if getattr(s, "opsiyonel", False) and not getattr(s, "toplama_dahil", True):
                    continue
                miktar = _d(s.miktar)
                liste = _d(s.teklif_fiyati)
                net = _d(s.net_birim_fiyat)
                kdv_o = _d(s.kdv_orani)
                mal = _d(getattr(s, "birim_maliyet", 0) or 0)
            satir_brut = (liste * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
            satir_ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
            satir_isk = satir_brut - satir_ara
            satir_kdv = (satir_ara * kdv_o / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
            brut += satir_brut
            isk += satir_isk
            ara += satir_ara
            kdv += satir_kdv
            genel += satir_ara + satir_kdv
            maliyet += (mal * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        kar = ara - maliyet
        marj = (kar / ara * 100).quantize(_KURUS, rounding=ROUND_HALF_UP) if ara else Decimal("0")
        oran = (kar / maliyet * 100).quantize(_KURUS, rounding=ROUND_HALF_UP) if maliyet else Decimal("0")
        return {
            "brut_toplam": brut,
            "iskonto_toplam": isk,
            "ara_toplam": ara,
            "kdv_toplam": kdv,
            "genel_toplam": genel,
            "toplam_maliyet": maliyet,
            "brut_kar": kar,
            "gercek_marj": marj,
            "maliyet_ustu_oran": oran,
        }

    @staticmethod
    def apply_bulk_pricing(
        satirlar: list[dict],
        *,
        yontem: str,
        oran_veya_tutar: Decimal = Decimal("0"),
        maliyet_kaynagi: str = "SON_ALIS",
        depo: str = "ANA DEPO",
        yuvarlama: YUVARLAMA = "kurus",
    ) -> list[dict]:
        """Önizleme satırları döner (eski/yeni fiyat). Uygulama UI tarafında onaylanır."""
        sonuc = []
        for s in satirlar:
            kod = (s.get("urun_kodu") or "").strip()
            eski = _d(s.get("teklif_fiyati", 0))
            maliyet, kay, _ = QuotePricingService.maliyet_snapshot(kod, depo, maliyet_kaynagi)
            liste = _d(s.get("liste_fiyati", 0))
            if liste <= 0 and kod:
                try:
                    liste = _d(StokService.satis_fiyati_1(kod, Decimal("0")))
                except Exception:
                    liste = Decimal("0")
            calc = QuotePricingService.fiyat_hesapla(
                yontem=yontem,
                birim_maliyet=maliyet,
                liste_fiyati=liste,
                oran_veya_tutar=oran_veya_tutar,
                manuel_fiyat=eski if yontem == "MANUEL" else None,
                iskonto_1=s.get("iskonto_orani", 0),
                iskonto_2=s.get("iskonto_orani_2", 0),
                iskonto_3=s.get("iskonto_orani_3", 0),
                kdv_orani=s.get("kdv_orani", 20),
                miktar=s.get("miktar", 1),
                yuvarlama=yuvarlama,
                maliyet_kaynagi=kay,
            )
            sonuc.append(
                {
                    **s,
                    "eski_fiyat": eski,
                    "yeni_fiyat": calc.teklif_fiyati,
                    "fark": calc.teklif_fiyati - eski,
                    "birim_maliyet": calc.birim_maliyet,
                    "maliyet_kaynagi": calc.maliyet_kaynagi,
                    "teklif_fiyati": calc.teklif_fiyati,
                    "net_birim_fiyat": calc.net_birim_fiyat,
                    "kar_orani": calc.kar_orani,
                    "gercek_marj": calc.gercek_marj,
                    "fiyat_yontemi": calc.yontem,
                    "uyari": calc.uyari,
                    "satir_toplam": calc.satir_toplam,
                }
            )
        return sonuc
