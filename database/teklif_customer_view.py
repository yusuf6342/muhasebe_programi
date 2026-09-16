"""Müşteri teklif görünümü — maliyet/kâr alanları bu modele HİÇ eklenmez.

CustomerQuoteViewModel yalnızca müşteriye gösterilebilir alanları taşır.
İç maliyet analizi ayrı InternalQuoteCostViewModel ile yapılır.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

_KURUS = Decimal("0.01")
_DORT = Decimal("0.0001")

# Müşteri belgesinde yasak anahtarlar / başlıklar (güvenlik tarayıcısı)
YASAK_MUSTERI_ALANLARI = frozenset(
    {
        "purchase_price",
        "purchase_cost",
        "purchase_unit_price",
        "purchase_total_cost",
        "cost_source",
        "maliyet_kaynagi",
        "supplier",
        "tedarikci",
        "profit_rate",
        "profit_amount",
        "fixed_profit",
        "fixed_profit_amount",
        "percentage_profit",
        "margin_rate",
        "gercek_marj",
        "kar_orani",
        "internal_expense",
        "allocated_expense",
        "allocated_profit",
        "birim_maliyet",
        "toplam_maliyet",
        "brut_kar",
        "ic_not",
        "fifo",
        "agirlikli",
    }
)

YASAK_METIN_KALIPLARI = (
    r"\bal[ıi][şs]\b",
    r"\bmaliyet\b",
    r"\btedarikçi\b",
    r"\btedarikci\b",
    r"\bkâr\b",
    r"\bkar\b",
    r"\bmarj\b",
    r"\bfifo\b",
    r"\bortalama maliyet\b",
    r"\bmaktu\b",
    r"\bmasraf da[gğ][ıi]t[ıi]m",
    r"\biç not\b",
    r"\bic not\b",
    r"\bcost\b",
    r"\bprofit\b",
    r"\bmargin\b",
    r"\bsupplier\b",
    r"\bpurchase\b",
)


def _d(v, varsayilan: Decimal = Decimal("0")) -> Decimal:
    try:
        if isinstance(v, Decimal):
            return v
        m = str(v or "0").strip().replace(" ", "")
        if "," in m:
            m = m.replace(".", "").replace(",", ".")
        return Decimal(m or "0")
    except (InvalidOperation, ValueError):
        return varsayilan


def _para(v) -> str:
    try:
        return f"{float(_d(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def _tarih(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


@dataclass
class CustomerQuoteLine:
    sira: int
    urun_kodu: str
    urun_adi: str
    aciklama: str = ""
    miktar: Decimal = Decimal("0")
    birim: str = "Adet"
    birim_fiyat: Decimal = Decimal("0")
    iskonto_orani: Decimal = Decimal("0")
    net_birim_fiyat: Decimal = Decimal("0")
    kdv_orani: Decimal = Decimal("20")
    kdv_hariç_toplam: Decimal = Decimal("0")
    kdv_tutari: Decimal = Decimal("0")
    kdv_dahil_toplam: Decimal = Decimal("0")
    # Gösterim
    miktar_goster: str = ""
    birim_fiyat_goster: str = ""
    iskonto_goster: str = ""
    net_goster: str = ""
    kdv_oran_goster: str = ""
    kdv_hariç_goster: str = ""
    kdv_goster: str = ""
    kdv_dahil_goster: str = ""


@dataclass
class CustomerQuoteViewModel:
    """Müşteriye gönderilecek teklif — maliyet/kâr alanı YOK."""

    sablon_id: str = "customer_quote_template"
    belge_baslik: str = "TEKLİF FORMU"
    onizleme_baslik: str = "Müşteri Teklif Ön İzlemesi"
    # Firma
    firma: dict[str, Any] = field(default_factory=dict)
    logo_data_uri: str | None = None
    # Teklif
    teklif_no: str = ""
    teklif_tarihi: str = ""
    gecerlilik_tarihi: str = ""
    referans_no: str = ""
    konu: str = ""
    proje: str = ""
    hazirlayan: str = ""
    satis_temsilcisi: str = ""
    # Müşteri
    musteri: dict[str, Any] = field(default_factory=dict)
    # Satırlar
    satirlar: list[CustomerQuoteLine] = field(default_factory=list)
    # Toplamlar
    ara_toplam: Decimal = Decimal("0")
    iskonto_toplam: Decimal = Decimal("0")
    kdv_toplam: Decimal = Decimal("0")
    kdv_haric_toplam: Decimal = Decimal("0")
    genel_toplam: Decimal = Decimal("0")
    para_birimi: str = "TRY"
    ara_goster: str = ""
    iskonto_goster: str = ""
    kdv_goster: str = ""
    kdv_haric_goster: str = ""
    genel_goster: str = ""
    # Ticari şartlar
    odeme_sekli: str = ""
    termin_suresi: str = ""
    tahmini_teslim_tarihi: str = ""
    teslimat_sekli: str = ""
    gecerlilik_suresi: str = ""
    musteri_notu: str = ""
    ticari_sartlar: str = ""
    banka_satirlari: list[dict[str, str]] = field(default_factory=list)
    alt_bilgi: str = ""


@dataclass
class InternalCostLine:
    sira: int
    urun_kodu: str
    urun_adi: str
    miktar: Decimal = Decimal("0")
    birim: str = ""
    alis_birim: Decimal = Decimal("0")
    alis_toplam: Decimal = Decimal("0")
    maliyet_kaynagi: str = ""
    maliyet_tarihi: str = ""
    tedarikci: str = ""
    dagitilan_masraf: Decimal = Decimal("0")
    dagitilan_yuzde_kar: Decimal = Decimal("0")
    dagitilan_maktu: Decimal = Decimal("0")
    teklif_birim: Decimal = Decimal("0")
    teklif_ara: Decimal = Decimal("0")
    gercek_kar: Decimal = Decimal("0")
    marj: Decimal = Decimal("0")
    manuel: bool = False


@dataclass
class InternalQuoteCostViewModel:
    """Şirket içi maliyet analizi — müşteriyle paylaşılmaz."""

    sablon_id: str = "internal_quote_cost_analysis_template"
    uyari_bant: str = "ŞİRKET İÇİDİR – MÜŞTERİYLE PAYLAŞILMAZ"
    teklif_no: str = ""
    teklif_tarihi: str = ""
    musteri_unvan: str = ""
    cost_source: str = ""
    total_purchase_cost: Decimal = Decimal("0")
    profit_rate: Decimal = Decimal("0")
    percentage_profit_amount: Decimal = Decimal("0")
    fixed_profit_amount: Decimal = Decimal("0")
    customer_expense_amount: Decimal = Decimal("0")
    internal_expense_amount: Decimal = Decimal("0")
    total_target_profit: Decimal = Decimal("0")
    calculated_offer_subtotal: Decimal = Decimal("0")
    actual_profit_amount: Decimal = Decimal("0")
    cost_markup_rate: Decimal = Decimal("0")
    sales_margin_rate: Decimal = Decimal("0")
    satirlar: list[InternalCostLine] = field(default_factory=list)
    zarar_uyarisi: str = ""


class CustomerQuoteSecurityError(ValueError):
    """Müşteri çıktısında yasak alan/metin tespit edildi."""


def assert_customer_model_safe(vm: CustomerQuoteViewModel) -> None:
    """ViewModel üzerinde yasak alan adı kontrolü (dataclass alanları)."""
    alanlar = set(asdict(vm).keys())
    # Satır alt alanları
    if vm.satirlar:
        alanlar |= set(asdict(vm.satirlar[0]).keys())
    yasak = alanlar & YASAK_MUSTERI_ALANLARI
    if yasak:
        raise CustomerQuoteSecurityError(
            "Müşteri teklifinde şirket içi maliyet veya kârlılık bilgisi tespit edildi. "
            f"Belge gönderilemedi. Yasak alanlar: {', '.join(sorted(yasak))}"
        )


def assert_customer_output_safe(metin: str) -> None:
    """HTML/PDF metninde yasak ifadeleri tara."""
    if not metin:
        return
    # Görünür metin — script/style temizle
    temiz = re.sub(r"<script[\s\S]*?</script>", " ", metin, flags=re.I)
    temiz = re.sub(r"<style[\s\S]*?</style>", " ", temiz, flags=re.I)
    temiz = re.sub(r"<[^>]+>", " ", temiz)
    for kalip in YASAK_METIN_KALIPLARI:
        if re.search(kalip, temiz, flags=re.IGNORECASE):
            raise CustomerQuoteSecurityError(
                "Müşteri teklifinde şirket içi maliyet veya kârlılık bilgisi tespit edildi. "
                "Belge gönderilemedi."
            )


def build_customer_quote_from_dialog(dialog) -> CustomerQuoteViewModel:
    """TeklifDialog / kayıttan müşteri ViewModel üretir — maliyet alanları kopyalanmaz."""
    from invoice_print.branding import load_company_branding, logo_data_uri
    from database.teklif_service import QuoteService
    from database.user_audit import display_user
    from belge_kullanici_ui import aktif_kullanici_adi

    branding = load_company_branding()
    logo = logo_data_uri(branding.get("logo_yolu"))

    teklif = getattr(dialog, "teklif", None)
    girdiler = getattr(dialog, "girdiler", {}) or {}

    def _g(anahtar, varsayilan=""):
        w = girdiler.get(anahtar)
        if w is None:
            return varsayilan
        try:
            return (w.get() or "").strip() or varsayilan
        except Exception:
            return varsayilan

    cari = None
    try:
        cari = dialog._secili_musteri() if hasattr(dialog, "_secili_musteri") else None
    except Exception:
        cari = None

    musteri = {
        "unvan": "",
        "yetkili": _g("musteri_yetkilisi"),
        "adres": "",
        "telefon": _g("musteri_telefon"),
        "email": _g("musteri_email"),
        "vergi_dairesi": "",
        "vergi_no": "",
    }
    if cari:
        musteri["unvan"] = getattr(cari, "unvan", "") or ""
        musteri["adres"] = getattr(cari, "adres", "") or ""
        musteri["telefon"] = (
            musteri["telefon"]
            or getattr(cari, "telefon", None)
            or getattr(cari, "cep_telefonu", "")
            or ""
        )
        musteri["email"] = musteri["email"] or getattr(cari, "email", "") or ""
        musteri["vergi_dairesi"] = getattr(cari, "vergi_dairesi", "") or ""
        musteri["vergi_no"] = (
            getattr(cari, "vergi_numarasi", None) or getattr(cari, "tc_kimlik", "") or ""
        )
    else:
        musteri["unvan"] = _g("aday_musteri_adi") or "—"

    teklif_no = _g("teklif_no")
    if teklif:
        try:
            teklif_no = QuoteService.gosterim_no(teklif)
        except Exception:
            teklif_no = getattr(teklif, "teklif_no", teklif_no) or teklif_no

    hazirlayan = ""
    if teklif and (
        getattr(teklif, "created_by_full_name", None) or getattr(teklif, "created_by_user_id", None)
    ):
        hazirlayan = display_user(teklif.created_by_full_name, teklif.created_by_user_id)
    else:
        hazirlayan = aktif_kullanici_adi()

    satirlar_src = list(getattr(dialog, "satirlar", None) or [])
    if not satirlar_src and teklif is not None:
        satirlar_src = [
            {
                "urun_kodu": s.urun_kodu,
                "urun_adi": s.urun_adi,
                "aciklama": s.aciklama,
                "miktar": s.miktar,
                "birim": s.birim,
                "teklif_fiyati": s.teklif_fiyati,
                "final_offer_unit_price": getattr(s, "final_offer_unit_price", None),
                "iskonto_orani": s.iskonto_orani,
                "iskonto_orani_2": s.iskonto_orani_2,
                "iskonto_orani_3": s.iskonto_orani_3,
                "kdv_orani": s.kdv_orani,
                "net_birim_fiyat": s.net_birim_fiyat,
                "opsiyonel": s.opsiyonel,
                "toplama_dahil": s.toplama_dahil,
                "is_manual_item": bool(getattr(s, "is_manual_item", False)),
                "manual_product_name": getattr(s, "manual_product_name", None),
                "customer_note": getattr(s, "customer_note", None),
                "delivery_term_note": getattr(s, "delivery_term_note", None),
                "delivery_term_days": getattr(s, "delivery_term_days", None),
            }
            for s in (teklif.satirlar or [])
        ]

    from database.teklif_pricing_service import net_iskontolu

    lines: list[CustomerQuoteLine] = []
    ara = Decimal("0")
    isk_toplam = Decimal("0")
    kdv_toplam = Decimal("0")
    sira = 0
    for s in satirlar_src:
        if s.get("opsiyonel") and not s.get("toplama_dahil", True):
            continue
        sira += 1
        miktar = _d(s.get("miktar", 0))
        # Yalnız nihai satış/teklif fiyatı — alış/maliyet alanlarına bakılmaz
        birim_fiyat = _d(
            s.get("final_offer_unit_price")
            or s.get("teklif_fiyati")
            or s.get("birim_satis_fiyati")
            or s.get("birim_fiyat")
            or 0
        )
        i1 = _d(s.get("iskonto_orani", 0))
        i2 = _d(s.get("iskonto_orani_2", 0))
        i3 = _d(s.get("iskonto_orani_3", 0))
        net = _d(s.get("net_birim_fiyat") or 0)
        if net <= 0:
            net = net_iskontolu(birim_fiyat, i1, i2, i3)
        kdv_o = _d(s.get("kdv_orani", 20))
        satir_ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        satir_brut = (birim_fiyat * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        satir_kdv = (satir_ara * kdv_o / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
        satir_dahil = satir_ara + satir_kdv
        ara += satir_ara
        isk_toplam += satir_brut - satir_ara
        kdv_toplam += satir_kdv
        # Müşteri çıktısı: MANUEL kodu gizle; termin notunu açıklamaya ekle (iç etiket yok)
        kod = str(s.get("urun_kodu") or "")
        if kod.upper() in ("MANUEL", "OZEL") or s.get("is_manual_item"):
            kod = ""
        ack_parcalar = []
        if s.get("customer_note"):
            ack_parcalar.append(str(s.get("customer_note")))
        elif s.get("aciklama"):
            ack_parcalar.append(str(s.get("aciklama")))
        term_not = s.get("delivery_term_note")
        if term_not:
            ack_parcalar.append(str(term_not))
        elif s.get("delivery_term_days"):
            ack_parcalar.append(f"Termin: {s.get('delivery_term_days')} gün")
        lines.append(
            CustomerQuoteLine(
                sira=sira,
                urun_kodu=kod,
                urun_adi=str(s.get("urun_adi") or s.get("manual_product_name") or ""),
                aciklama=" — ".join(ack_parcalar),
                miktar=miktar,
                birim=str(s.get("birim") or "Adet"),
                birim_fiyat=birim_fiyat.quantize(_DORT),
                iskonto_orani=i1,
                net_birim_fiyat=net.quantize(_DORT),
                kdv_orani=kdv_o,
                kdv_hariç_toplam=satir_ara,
                kdv_tutari=satir_kdv,
                kdv_dahil_toplam=satir_dahil,
                miktar_goster=_para(miktar),
                birim_fiyat_goster=_para(birim_fiyat),
                iskonto_goster=f"%{_para(i1)}" if i1 else "—",
                net_goster=_para(net),
                kdv_oran_goster=f"%{_para(kdv_o)}",
                kdv_hariç_goster=_para(satir_ara),
                kdv_goster=_para(satir_kdv),
                kdv_dahil_goster=_para(satir_dahil),
            )
        )

    genel = ara + kdv_toplam

    termin_gun = _g("delivery_term_days")
    termin_metin = ""
    if termin_gun:
        termin_metin = f"{termin_gun} Gün"
    elif _g("teslim_suresi"):
        termin_metin = _g("teslim_suresi")
    elif teklif and getattr(teklif, "delivery_term_days", None):
        termin_metin = f"{teklif.delivery_term_days} Gün"

    tahmini = _g("estimated_delivery_date")
    if not tahmini and teklif and getattr(teklif, "estimated_delivery_date", None):
        tahmini = _tarih(teklif.estimated_delivery_date)
    elif not tahmini and teklif and getattr(teklif, "tahmini_termin", None):
        tahmini = _tarih(teklif.tahmini_termin)

    gecerlilik_gun = _g("gecerlilik_gunu")
    if teklif and not gecerlilik_gun:
        gecerlilik_gun = str(getattr(teklif, "gecerlilik_gunu", "") or "")

    musteri_notu = ""
    ticari = ""
    try:
        musteri_notu = dialog.musteri_notu.get("1.0", "end").strip()
    except Exception:
        if teklif:
            musteri_notu = teklif.musteri_notu or ""
    try:
        ticari = dialog.ticari_sartlar.get("1.0", "end").strip()
    except Exception:
        if teklif:
            ticari = teklif.ticari_sartlar or ""

    # İç not ASLA eklenmez

    vm = CustomerQuoteViewModel(
        firma={
            "unvan": branding.get("unvan") or "",
            "adres": branding.get("adres") or "",
            "ilce": branding.get("ilce") or "",
            "il": branding.get("il") or "",
            "telefon": branding.get("telefon") or "",
            "email": branding.get("email") or "",
            "web": branding.get("web") or "",
            "vergi_dairesi": branding.get("vergi_dairesi") or "",
            "vergi_no": branding.get("vergi_no") or "",
        },
        logo_data_uri=logo,
        teklif_no=teklif_no,
        teklif_tarihi=_g("teklif_tarihi")
        or (_tarih(teklif.teklif_tarihi) if teklif else ""),
        gecerlilik_tarihi=_g("gecerlilik_tarihi")
        or (_tarih(teklif.gecerlilik_tarihi) if teklif else ""),
        referans_no=_g("referans_no") or (getattr(teklif, "referans_no", None) or ""),
        konu=_g("konu") or (getattr(teklif, "konu", None) or ""),
        proje=_g("proje") or (getattr(teklif, "proje", None) or ""),
        hazirlayan=hazirlayan,
        satis_temsilcisi=_g("satis_temsilcisi")
        or (getattr(teklif, "satis_temsilcisi", None) or ""),
        musteri=musteri,
        satirlar=lines,
        ara_toplam=ara,
        iskonto_toplam=isk_toplam,
        kdv_toplam=kdv_toplam,
        kdv_haric_toplam=ara,
        genel_toplam=genel,
        para_birimi=_g("para_birimi") or (getattr(teklif, "para_birimi", None) or "TRY"),
        ara_goster=_para(ara),
        iskonto_goster=_para(isk_toplam),
        kdv_goster=_para(kdv_toplam),
        kdv_haric_goster=_para(ara),
        genel_goster=_para(genel),
        odeme_sekli=_g("odeme_sekli") or (getattr(teklif, "odeme_sekli", None) or ""),
        termin_suresi=termin_metin,
        tahmini_teslim_tarihi=tahmini,
        teslimat_sekli=_g("teslimat_sekli")
        or (getattr(teklif, "teslimat_sekli", None) or "")
        or (
            getattr(dialog, "termin_turu", None).get()
            if hasattr(dialog, "termin_turu")
            else ""
        )
        or (getattr(teklif, "delivery_term_type", None) or ""),
        gecerlilik_suresi=f"{gecerlilik_gun} Gün" if gecerlilik_gun else "",
        musteri_notu=musteri_notu,
        ticari_sartlar=ticari,
        banka_satirlari=list(branding.get("ibanlar") or []),
        alt_bilgi=branding.get("alt_bilgi") or "",
    )
    assert_customer_model_safe(vm)
    return vm


def build_internal_cost_from_dialog(dialog) -> InternalQuoteCostViewModel:
    """Yetkili iç maliyet görünümü — müşteri şablonuna bağlanmaz."""
    from database.access import maliyet_izinli, kar_izinli
    from database.teklif_service import QuoteService

    if not (maliyet_izinli() or kar_izinli()):
        raise PermissionError("İç maliyet analizini görüntüleme yetkiniz yok.")

    teklif = getattr(dialog, "teklif", None)
    girdiler = getattr(dialog, "girdiler", {}) or {}
    fiyat_g = getattr(dialog, "fiyat_girdiler", {}) or {}

    def _g(anahtar, kaynak=None):
        kaynak = kaynak or girdiler
        w = kaynak.get(anahtar)
        if w is None:
            return ""
        try:
            return (w.get() or "").strip()
        except Exception:
            return ""

    satirlar_src = list(getattr(dialog, "satirlar", None) or [])
    lines: list[InternalCostLine] = []
    for i, s in enumerate(satirlar_src, start=1):
        miktar = _d(s.get("miktar", 0))
        alis = _d(s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0)
        teklif_f = _d(s.get("final_offer_unit_price") or s.get("teklif_fiyati") or 0)
        net = _d(s.get("net_birim_fiyat") or teklif_f)
        ara = (net * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        alis_t = (alis * miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
        lines.append(
            InternalCostLine(
                sira=i,
                urun_kodu=str(s.get("urun_kodu") or ""),
                urun_adi=str(s.get("urun_adi") or ""),
                miktar=miktar,
                birim=str(s.get("birim") or ""),
                alis_birim=alis,
                alis_toplam=alis_t,
                maliyet_kaynagi=str(s.get("maliyet_kaynagi") or ""),
                maliyet_tarihi=_tarih(s.get("cost_source_date")),
                tedarikci=str(s.get("supplier_name") or ""),
                dagitilan_masraf=_d(s.get("allocated_expense")),
                dagitilan_yuzde_kar=_d(s.get("allocated_percentage_profit")),
                dagitilan_maktu=_d(s.get("allocated_fixed_profit")),
                teklif_birim=teklif_f,
                teklif_ara=ara,
                gercek_kar=_d(s.get("actual_profit_amount") or (ara - alis_t)),
                marj=_d(s.get("actual_margin_rate") or s.get("gercek_marj")),
                manuel=bool(s.get("is_manual_price")),
            )
        )

    musteri = ""
    try:
        cari = dialog._secili_musteri()
        musteri = getattr(cari, "unvan", "") if cari else _g("aday_musteri_adi")
    except Exception:
        musteri = _g("aday_musteri_adi")

    total_alis = sum((l.alis_toplam for l in lines), Decimal("0"))
    ara_teklif = sum((l.teklif_ara for l in lines), Decimal("0"))
    gercek_kar = ara_teklif - total_alis - _d(_g("internal_expense_amount", fiyat_g) or 0)

    teklif_no = _g("teklif_no")
    if teklif:
        try:
            teklif_no = QuoteService.gosterim_no(teklif)
        except Exception:
            pass

    zarar = ""
    if gercek_kar < 0:
        zarar = "Bu teklif zarar oluşturmaktadır"

    return InternalQuoteCostViewModel(
        teklif_no=teklif_no,
        teklif_tarihi=_g("teklif_tarihi"),
        musteri_unvan=musteri or "—",
        cost_source=getattr(dialog, "maliyet_kaynak", None)
        and dialog.maliyet_kaynak.get()
        or (getattr(teklif, "cost_source", None) or "SON_ALIS"),
        total_purchase_cost=total_alis,
        profit_rate=_d(_g("profit_rate", fiyat_g) or 0),
        percentage_profit_amount=_d(
            getattr(teklif, "percentage_profit_amount", None)
            if teklif
            else 0
        ),
        fixed_profit_amount=_d(_g("fixed_profit_amount", fiyat_g) or 0),
        customer_expense_amount=_d(_g("customer_expense_amount", fiyat_g) or 0),
        internal_expense_amount=_d(_g("internal_expense_amount", fiyat_g) or 0),
        total_target_profit=_d(getattr(teklif, "total_target_profit", None) if teklif else 0),
        calculated_offer_subtotal=ara_teklif,
        actual_profit_amount=gercek_kar,
        cost_markup_rate=(
            (gercek_kar / total_alis * 100).quantize(_KURUS) if total_alis else Decimal("0")
        ),
        sales_margin_rate=(
            (gercek_kar / ara_teklif * 100).quantize(_KURUS) if ara_teklif else Decimal("0")
        ),
        satirlar=lines,
        zarar_uyarisi=zarar,
    )
