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


# Varsayılan müşteri hitabı (ayarlarla değiştirilebilir)
DEFAULT_HITAP_METNI = (
    "Değerli müşterimiz, görüşmemize istinaden hazırlamış olduğumuz teklifimiz aşağıdadır. "
    "Kıymetli sipariş emirlerinizi bekler, hayırlı işler dileriz."
)

DEFAULT_SART_MADDELERI = (
    "Teklif, belirtilen geçerlilik tarihine kadar geçerlidir.",
    "Stok durumu sipariş onayı tarihinde yeniden kontrol edilir; rezervasyon sipariş onayı ile başlar.",
    "Teslim / sevkiyat süresi, sipariş onayı ve ödeme şartlarının tamamlanmasından sonra başlar.",
    "Ürünlerin miktar, ölçü, renk ve model kontrolü sipariş onayından önce müşteriye aittir.",
    "Teklif fiyatlarına yansıtılan masraf ve hizmet bedelleri birim fiyatlara dahildir; ayrıca tahsil edilmez.",
    "İade ve garanti koşulları, ürün tipine ve üretici şartlarına tabidir.",
)

MUSTERI_ONAY_BEYANI = (
    "Yukarıdaki ürün, fiyat ve teklif şartlarını okuyarak kabul ettiğimizi beyan ederiz."
)

FIRMA_ALT_UNVAN = "Ray Mobilya Aksesuarları"
FIRMA_ALT_SLOGAN = "Mobilya Aksesuarları ve Hırdavat Ürünleri"


def para_birimi_etiket(kod: str) -> str:
    k = (kod or "TRY").upper()
    return {"TRY": "TL", "TRL": "TL"}.get(k, k)


def para_birimli(tutar_goster: str, para_birimi: str) -> str:
    return f"{tutar_goster} {para_birimi_etiket(para_birimi)}".strip()


@dataclass
class CustomerQuoteViewModel:
    """Müşteriye gönderilecek teklif — maliyet/kâr alanı YOK."""

    sablon_id: str = "customer_quote_template"
    belge_baslik: str = "FİYAT TEKLİFİ"
    onizleme_baslik: str = "Müşteri Teklif Ön İzlemesi"
    # Firma
    firma: dict[str, Any] = field(default_factory=dict)
    logo_data_uri: str | None = None
    firma_slogan: str = FIRMA_ALT_SLOGAN
    # Teklif meta
    teklif_no: str = ""
    teklif_tarihi: str = ""
    gecerlilik_tarihi: str = ""
    referans_no: str = ""
    konu: str = ""
    proje: str = ""
    hazirlayan: str = ""
    hazirlayan_gorev: str = ""
    satis_temsilcisi: str = ""
    durum: str = ""
    revizyon_no: int = 0
    revizyon_goster: str = ""
    # Müşteri
    musteri: dict[str, Any] = field(default_factory=dict)
    # Satırlar
    satirlar: list[CustomerQuoteLine] = field(default_factory=list)
    urun_gorseli_aktif: bool = False
    # Toplamlar
    ara_toplam: Decimal = Decimal("0")
    iskonto_toplam: Decimal = Decimal("0")
    genel_iskonto: Decimal = Decimal("0")
    iskonto_sonrasi: Decimal = Decimal("0")
    kdv_toplam: Decimal = Decimal("0")
    kdv_haric_toplam: Decimal = Decimal("0")
    nakliye: Decimal = Decimal("0")
    yuvarlama: Decimal = Decimal("0")
    genel_toplam: Decimal = Decimal("0")
    para_birimi: str = "TRY"
    para_birimi_etiket: str = "TL"
    kdv_dahil_fiyat: bool = False
    kdv_aciklama: str = "Fiyatlara KDV dahil değildir."
    ara_goster: str = ""
    iskonto_goster: str = ""
    genel_iskonto_goster: str = ""
    iskonto_sonrasi_goster: str = ""
    kdv_goster: str = ""
    kdv_haric_goster: str = ""
    nakliye_goster: str = ""
    yuvarlama_goster: str = ""
    genel_goster: str = ""
    sifir_kalemleri_gizle: bool = True
    # Hitap / şartlar
    hitap_metni: str = DEFAULT_HITAP_METNI
    odeme_sekli: str = ""
    termin_suresi: str = ""
    tahmini_teslim_tarihi: str = ""
    teslimat_sekli: str = ""
    gecerlilik_suresi: str = ""
    nakliye_durumu: str = ""
    vade_bilgisi: str = ""
    garanti_kosullari: str = ""
    kur_aciklama: str = ""
    musteri_notu: str = ""
    ticari_sartlar: str = ""
    sart_maddeleri: list[str] = field(default_factory=list)
    sart_satirlari: list[tuple[str, str]] = field(default_factory=list)
    banka_satirlari: list[dict[str, str]] = field(default_factory=list)
    alt_bilgi: str = ""
    onay_beyani: str = MUSTERI_ONAY_BEYANI
    olusturma_tarih_saat: str = ""
    teklif_id: int | None = None


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


def load_teklif_sablon_ayarlari() -> dict[str, Any]:
    """Firma teklif şablon ayarları (hitap, şart maddeleri, KDV varsayılanı)."""
    import json

    from sqlalchemy import select

    from database.database import get_system_session
    from database.session_manager import oturum
    from database.system.models import AppSetting

    sonuc = {
        "hitap_metni": DEFAULT_HITAP_METNI,
        "sart_maddeleri": list(DEFAULT_SART_MADDELERI),
        "kdv_dahil_fiyat": False,
        "urun_gorseli_aktif": False,
        "sifir_kalemleri_gizle": True,
        "firma_slogan": FIRMA_ALT_SLOGAN,
        "onay_beyani": MUSTERI_ONAY_BEYANI,
    }
    cid = getattr(oturum, "company_id", None)
    if not cid:
        return sonuc
    anahtar = f"teklif_sablon_{int(cid)}"
    try:
        with get_system_session() as session:
            kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
            if kayit and kayit.deger:
                data = json.loads(kayit.deger)
                if isinstance(data, dict):
                    if data.get("hitap_metni"):
                        sonuc["hitap_metni"] = str(data["hitap_metni"]).strip()
                    if isinstance(data.get("sart_maddeleri"), list) and data["sart_maddeleri"]:
                        sonuc["sart_maddeleri"] = [
                            str(x).strip() for x in data["sart_maddeleri"] if str(x).strip()
                        ]
                    for k in (
                        "kdv_dahil_fiyat",
                        "urun_gorseli_aktif",
                        "sifir_kalemleri_gizle",
                    ):
                        if k in data:
                            sonuc[k] = bool(data[k])
                    if data.get("firma_slogan"):
                        sonuc["firma_slogan"] = str(data["firma_slogan"]).strip()
                    if data.get("onay_beyani"):
                        sonuc["onay_beyani"] = str(data["onay_beyani"]).strip()
    except Exception:
        pass
    return sonuc


def save_teklif_sablon_ayarlari(data: dict[str, Any]) -> None:
    import json
    from sqlalchemy import select
    from database.session_manager import oturum
    from database.database import get_system_session
    from database.system.models import AppSetting

    cid = getattr(oturum, "company_id", None)
    if not cid:
        raise ValueError("Aktif firma seçilmedi.")
    anahtar = f"teklif_sablon_{int(cid)}"
    with get_system_session() as session:
        kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
        metin = json.dumps(data, ensure_ascii=False)
        if kayit:
            kayit.deger = metin
        else:
            session.add(AppSetting(anahtar=anahtar, deger=metin))
        session.flush()


def _adres_satiri(*parcalar) -> str:
    return " ".join(str(p).strip() for p in parcalar if p and str(p).strip())


def build_customer_quote_from_dialog(dialog) -> CustomerQuoteViewModel:
    """TeklifDialog / kayıttan müşteri ViewModel üretir — maliyet alanları kopyalanmaz."""
    from invoice_print.branding import load_company_branding, logo_data_uri
    from database.teklif_service import QuoteService
    from database.user_audit import display_user
    from belge_kullanici_ui import aktif_kullanici_adi

    branding = load_company_branding()
    logo = logo_data_uri(branding.get("logo_yolu"))
    sablon = load_teklif_sablon_ayarlari()

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
        "fatura_adresi": "",
        "teslimat_adresi": "",
        "telefon": _g("musteri_telefon"),
        "email": _g("musteri_email"),
        "vergi_dairesi": "",
        "vergi_no": "",
    }
    if cari:
        musteri["unvan"] = getattr(cari, "unvan", "") or ""
        adres = _adres_satiri(
            getattr(cari, "adres", None),
            getattr(cari, "ilce", None),
            getattr(cari, "il", None),
        )
        musteri["adres"] = adres
        musteri["fatura_adresi"] = adres
        musteri["telefon"] = (
            musteri["telefon"]
            or getattr(cari, "telefon", None)
            or getattr(cari, "cep_telefonu", None)
            or ""
        )
        musteri["email"] = musteri["email"] or getattr(cari, "email", "") or ""
        musteri["vergi_dairesi"] = getattr(cari, "vergi_dairesi", "") or ""
        musteri["vergi_no"] = (
            getattr(cari, "vergi_numarasi", None) or getattr(cari, "tc_kimlik", "") or ""
        )
    else:
        musteri["unvan"] = _g("aday_musteri_adi") or "—"

    teslimat = _g("teslimat_adresi")
    if not teslimat and teklif:
        teslimat = getattr(teklif, "teslimat_adresi", None) or ""
    musteri["teslimat_adresi"] = teslimat or musteri.get("fatura_adresi") or ""

    teklif_no = _g("teklif_no")
    revizyon_no = 0
    durum = ""
    if teklif:
        try:
            teklif_no = QuoteService.gosterim_no(teklif)
        except Exception:
            teklif_no = getattr(teklif, "teklif_no", teklif_no) or teklif_no
        revizyon_no = int(getattr(teklif, "revizyon_no", 0) or 0)
        durum = getattr(teklif, "durum", None) or ""

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

    # Masraf/kâr dağıtımı fiyatlara gömülü — müşteri belgesinde ayrı masraf/nakliye satırı yok
    nakliye = Decimal("0")

    genel_isk_oran = _d(_g("genel_iskonto_orani") or 0)
    if genel_isk_oran <= 0 and teklif:
        genel_isk_oran = _d(getattr(teklif, "genel_iskonto_orani", 0) or 0)
    genel_isk_tutar = Decimal("0")
    if genel_isk_oran > 0:
        genel_isk_tutar = (ara * genel_isk_oran / Decimal("100")).quantize(
            _KURUS, rounding=ROUND_HALF_UP
        )
    iskonto_sonrasi = ara - genel_isk_tutar
    # Genel iskonto sonrası KDV yeniden (basit oran: satır KDV toplamını orantıla)
    if genel_isk_tutar > 0 and ara > 0:
        kdv_toplam = (kdv_toplam * iskonto_sonrasi / ara).quantize(_KURUS, rounding=ROUND_HALF_UP)
    genel = iskonto_sonrasi + kdv_toplam

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

    pb = _g("para_birimi") or (getattr(teklif, "para_birimi", None) or "TRY")
    pb_etiket = para_birimi_etiket(pb)
    kdv_dahil = bool(sablon.get("kdv_dahil_fiyat"))
    # Dialogda açık seçim varsa onu kullan
    try:
        if hasattr(dialog, "kdv_dahil_var") and dialog.kdv_dahil_var is not None:
            kdv_dahil = bool(dialog.kdv_dahil_var.get())
    except Exception:
        pass

    odeme = _g("odeme_sekli") or (getattr(teklif, "odeme_sekli", None) or "")
    # Yapılandırılmış ödeme alanlarından zengin özet
    try:
        from database.teklif_odeme import kayittan_odeme, odeme_ozet

        if hasattr(dialog, "_odeme_alanlari_oku"):
            od = dialog._odeme_alanlari_oku()
            ozet = od.get("odeme_ozet") or odeme_ozet(
                od.get("odeme_sekli"),
                taksit=od.get("odeme_taksit"),
                vade_gun=od.get("odeme_vade_gun"),
                vade_tarihi=od.get("odeme_vade_tarihi"),
            )
            if ozet:
                odeme = ozet
        elif teklif is not None:
            ozet = kayittan_odeme(teklif).get("ozet") or ""
            if ozet:
                odeme = ozet
    except Exception:
        pass
    teslimat_sekli = (
        _g("teslimat_sekli")
        or (getattr(teklif, "teslimat_sekli", None) or "")
        or (
            getattr(dialog, "termin_turu", None).get()
            if hasattr(dialog, "termin_turu")
            else ""
        )
        or (getattr(teklif, "delivery_term_type", None) or "")
    )
    gecerlilik_sure = f"{gecerlilik_gun} Gün" if gecerlilik_gun else ""

    kur_aciklama = ""
    if pb.upper() not in ("TRY", "TRL", "TL"):
        kur = getattr(teklif, "kur", None) if teklif else None
        if kur and _d(kur) != 1:
            kur_aciklama = f"Kur: {_para(kur)} (1 {pb_etiket})"
        else:
            kur_aciklama = f"Para birimi: {pb_etiket}"

    sart_satirlari: list[tuple[str, str]] = []
    for baslik, deger in (
        ("Teklif geçerlilik süresi", gecerlilik_sure or (_g("gecerlilik_tarihi") or "")),
        ("Ödeme şekli", odeme),
        ("Teslim süresi", termin_metin),
        ("Teslimat şekli", teslimat_sekli),
        ("Nakliye durumu", _g("nakliye_durumu") or ""),
        ("Vade bilgisi", _g("vade_bilgisi") or odeme),
        ("Garanti koşulları", _g("garanti_kosullari") or ""),
        ("Para birimi / kur", kur_aciklama or pb_etiket),
        (
            "KDV",
            "Fiyatlara KDV dahildir." if kdv_dahil else "Fiyatlara KDV dahil değildir.",
        ),
        ("Özel açıklamalar", musteri_notu),
        ("Ticari şartlar", ticari),
    ):
        if deger and str(deger).strip():
            # Vade = ödeme tekrarıysa ikinci kez ekleme
            if baslik == "Vade bilgisi" and deger == odeme and ("Ödeme şekli", odeme) in sart_satirlari:
                continue
            sart_satirlari.append((baslik, str(deger).strip()))

    firma_adres = _adres_satiri(
        branding.get("adres"), branding.get("ilce"), branding.get("il")
    )
    # Ray Mobilya varsayılan iletişim (firma kartı boşsa)
    telefon = branding.get("telefon") or "0506 136 97 24"
    if not firma_adres:
        firma_adres = "Adnan Kahveci Mah. Kazım Karabekir Cad. No:52 Beylikdüzü/İstanbul"
    unvan = branding.get("unvan") or "RAY MOBİLYA AKSESUARLARI"

    vm = CustomerQuoteViewModel(
        belge_baslik="FİYAT TEKLİFİ",
        firma={
            "unvan": unvan,
            "adres": firma_adres,
            "ilce": branding.get("ilce") or "",
            "il": branding.get("il") or "",
            "telefon": telefon,
            "email": branding.get("email") or "",
            "web": branding.get("web") or "",
            "vergi_dairesi": branding.get("vergi_dairesi") or "",
            "vergi_no": branding.get("vergi_no") or "",
        },
        logo_data_uri=logo,
        firma_slogan=sablon.get("firma_slogan") or FIRMA_ALT_SLOGAN,
        teklif_no=teklif_no,
        teklif_tarihi=_g("teklif_tarihi")
        or (_tarih(teklif.teklif_tarihi) if teklif else ""),
        gecerlilik_tarihi=_g("gecerlilik_tarihi")
        or (_tarih(teklif.gecerlilik_tarihi) if teklif else ""),
        referans_no=_g("referans_no") or (getattr(teklif, "referans_no", None) or ""),
        konu=_g("konu") or (getattr(teklif, "konu", None) or ""),
        proje=_g("proje") or (getattr(teklif, "proje", None) or ""),
        hazirlayan=hazirlayan,
        hazirlayan_gorev=_g("hazirlayan_gorev") or "",
        satis_temsilcisi=_g("satis_temsilcisi")
        or (getattr(teklif, "satis_temsilcisi", None) or ""),
        durum=durum,
        revizyon_no=revizyon_no,
        revizyon_goster=f"R{revizyon_no:02d}" if revizyon_no else "",
        musteri=musteri,
        satirlar=lines,
        urun_gorseli_aktif=bool(sablon.get("urun_gorseli_aktif")),
        ara_toplam=ara,
        iskonto_toplam=isk_toplam,
        genel_iskonto=genel_isk_tutar,
        iskonto_sonrasi=iskonto_sonrasi,
        kdv_toplam=kdv_toplam,
        kdv_haric_toplam=iskonto_sonrasi,
        nakliye=nakliye,
        yuvarlama=Decimal("0"),
        genel_toplam=genel,
        para_birimi=pb,
        para_birimi_etiket=pb_etiket,
        kdv_dahil_fiyat=kdv_dahil,
        kdv_aciklama=(
            "Fiyatlara KDV dahildir." if kdv_dahil else "Fiyatlara KDV dahil değildir."
        ),
        ara_goster=_para(ara),
        iskonto_goster=_para(isk_toplam),
        genel_iskonto_goster=_para(genel_isk_tutar),
        iskonto_sonrasi_goster=_para(iskonto_sonrasi),
        kdv_goster=_para(kdv_toplam),
        kdv_haric_goster=_para(iskonto_sonrasi),
        nakliye_goster=_para(nakliye),
        yuvarlama_goster=_para(0),
        genel_goster=_para(genel),
        sifir_kalemleri_gizle=bool(sablon.get("sifir_kalemleri_gizle", True)),
        hitap_metni=sablon.get("hitap_metni") or DEFAULT_HITAP_METNI,
        odeme_sekli=odeme,
        termin_suresi=termin_metin,
        tahmini_teslim_tarihi=tahmini,
        teslimat_sekli=teslimat_sekli,
        gecerlilik_suresi=gecerlilik_sure,
        nakliye_durumu=_g("nakliye_durumu") or "",
        vade_bilgisi=_g("vade_bilgisi") or "",
        garanti_kosullari=_g("garanti_kosullari") or "",
        kur_aciklama=kur_aciklama,
        musteri_notu=musteri_notu,
        ticari_sartlar=ticari,
        sart_maddeleri=list(sablon.get("sart_maddeleri") or DEFAULT_SART_MADDELERI),
        sart_satirlari=sart_satirlari,
        banka_satirlari=list(branding.get("ibanlar") or []),
        alt_bilgi=branding.get("alt_bilgi") or "",
        onay_beyani=sablon.get("onay_beyani") or MUSTERI_ONAY_BEYANI,
        olusturma_tarih_saat=datetime.now().strftime("%d.%m.%Y %H:%M"),
        teklif_id=getattr(teklif, "id", None) if teklif else None,
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
