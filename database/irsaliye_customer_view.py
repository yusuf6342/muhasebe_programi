"""Müşteri sevk irsaliyesi görünümü — maliyet/kâr/iç not yok."""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

YASAK_MUSTERI_ALANLARI = frozenset(
    {
        "purchase_price",
        "purchase_cost",
        "maliyet",
        "birim_maliyet",
        "toplam_maliyet",
        "profit",
        "kar",
        "kâr",
        "marj",
        "fifo",
        "ic_not",
        "internal",
        "alis",
        "alış",
        "tedarikci",
        "supplier",
        "cost",
        "margin",
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
class CustomerDispatchLine:
    sira: int
    urun_kodu: str
    urun_adi: str
    aciklama: str = ""
    miktar: Decimal = Decimal("0")
    birim: str = "Adet"
    birim_fiyat: Decimal = Decimal("0")
    iskonto_orani: Decimal = Decimal("0")
    kdv_orani: Decimal = Decimal("20")
    satir_toplam: Decimal = Decimal("0")
    miktar_goster: str = ""
    birim_fiyat_goster: str = ""
    iskonto_goster: str = ""
    kdv_oran_goster: str = ""
    satir_toplam_goster: str = ""


@dataclass
class CustomerDispatchViewModel:
    """Müşteri sevk irsaliyesi — iç not / maliyet yok."""

    sablon_id: str = "customer_dispatch_template"
    belge_baslik: str = "SATIŞ İRSALİYESİ"
    onizleme_baslik: str = "Müşteri İrsaliye Ön İzlemesi"
    firma: dict[str, Any] = field(default_factory=dict)
    logo_data_uri: str | None = None
    irsaliye_no: str = ""
    irsaliye_tarihi: str = ""
    depo: str = ""
    durum: str = ""
    is_priced: bool = True
    musteri: dict[str, Any] = field(default_factory=dict)
    sevk: dict[str, Any] = field(default_factory=dict)
    satirlar: list[CustomerDispatchLine] = field(default_factory=list)
    ara_toplam: Decimal = Decimal("0")
    kdv_toplam: Decimal = Decimal("0")
    genel_toplam: Decimal = Decimal("0")
    ara_goster: str = ""
    kdv_goster: str = ""
    genel_goster: str = ""
    musteri_notu: str = ""
    sevk_notu: str = ""
    siparis_no: str = ""
    para_birimi: str = "TRY"
    toplam_miktar_goster: str = ""
    aciklama: str = ""
    sevk_tarih_saat: str = ""
    siparis_nolari: list[str] = field(default_factory=list)
    olusturma: str = ""


def miktar_metni(miktar) -> str:
    """10 → '10', 2.5000 → '2,5' (tam sayının sıfırları silinmez)."""
    metin = f"{_d(miktar):f}"
    if "." in metin:
        metin = metin.rstrip("0").rstrip(".")
    return (metin or "0").replace(".", ",")


def birim_toplamlari(satirlar) -> list[tuple[str, Decimal]]:
    """Farklı birimler toplanmaz; her birim kendi toplamını alır (ilk görülme sırasıyla)."""
    toplamlar: dict[str, Decimal] = {}
    for s in satirlar:
        toplamlar[s.birim or "Adet"] = toplamlar.get(s.birim or "Adet", Decimal("0")) + _d(s.miktar)
    return list(toplamlar.items())


def toplam_miktar_metni(satirlar) -> str:
    """Birim bazında toplam miktar: '12 Adet · 3 Koli'."""
    return " · ".join(f"{miktar_metni(m)} {b}" for b, m in birim_toplamlari(satirlar))


class CustomerDispatchSecurityError(ValueError):
    """Müşteri irsaliyesinde yasak alan/metin."""


def assert_customer_model_safe(vm: CustomerDispatchViewModel) -> None:
    alanlar = set(asdict(vm).keys())
    if vm.satirlar:
        alanlar |= set(asdict(vm.satirlar[0]).keys())
    yasak = alanlar & YASAK_MUSTERI_ALANLARI
    if yasak:
        raise CustomerDispatchSecurityError(
            "Müşteri irsaliyesinde şirket içi maliyet veya kârlılık bilgisi tespit edildi. "
            f"Yasak alanlar: {', '.join(sorted(yasak))}"
        )


def assert_customer_output_safe(metin: str) -> None:
    if not metin:
        return
    temiz = re.sub(r"<script[\s\S]*?</script>", " ", metin, flags=re.I)
    temiz = re.sub(r"<style[\s\S]*?</style>", " ", temiz, flags=re.I)
    temiz = re.sub(r"<[^>]+>", " ", temiz)
    for kalip in YASAK_METIN_KALIPLARI:
        if re.search(kalip, temiz, flags=re.IGNORECASE):
            raise CustomerDispatchSecurityError(
                "Müşteri irsaliyesinde şirket içi maliyet veya kârlılık bilgisi tespit edildi. "
                "Belge gönderilemedi."
            )


def assert_customer_dispatch_safe(vm: CustomerDispatchViewModel, html_metin: str = "") -> None:
    assert_customer_model_safe(vm)
    if html_metin:
        assert_customer_output_safe(html_metin)


def _satir_modelleri(
    satirlar_raw: list[dict[str, Any]], is_priced: bool
) -> tuple[list[CustomerDispatchLine], Decimal, Decimal]:
    lines: list[CustomerDispatchLine] = []
    ara = Decimal("0")
    kdv_t = Decimal("0")
    for i, veri in enumerate(satirlar_raw, start=1):
        miktar = _d(veri.get("miktar"))
        fiyat = _d(veri.get("birim_fiyat")) if is_priced else Decimal("0")
        iskonto = _d(veri.get("iskonto_orani"))
        kdv = _d(veri.get("kdv_orani"), Decimal("20"))
        net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100))
        kdv_tut = net * kdv / Decimal(100) if is_priced else Decimal("0")
        toplam = net + kdv_tut
        ara += net
        kdv_t += kdv_tut
        lines.append(
            CustomerDispatchLine(
                sira=i,
                urun_kodu=str(veri.get("urun_kodu") or ""),
                urun_adi=str(veri.get("urun_adi") or ""),
                aciklama=str(veri.get("aciklama") or ""),
                miktar=miktar,
                birim=str(veri.get("birim") or "Adet"),
                birim_fiyat=fiyat,
                iskonto_orani=iskonto,
                kdv_orani=kdv,
                satir_toplam=toplam,
                miktar_goster=miktar_metni(miktar),
                birim_fiyat_goster=_para(fiyat) if is_priced else "—",
                iskonto_goster=f"%{miktar_metni(iskonto)}" if is_priced else "—",
                kdv_oran_goster=f"%{miktar_metni(kdv)}" if is_priced else "—",
                satir_toplam_goster=_para(toplam) if is_priced else "—",
            )
        )
    return lines, ara, kdv_t


def _firma_markasi() -> tuple[dict[str, Any], str | None]:
    try:
        from invoice_print.branding import load_company_branding, logo_data_uri

        branding = load_company_branding()
        return branding, logo_data_uri(branding.get("logo_yolu"))
    except Exception:
        return {}, None


def _birlestir(*parcalar, ayrac: str = " / ") -> str:
    return ayrac.join(str(p).strip() for p in parcalar if p and str(p).strip())


def build_customer_dispatch_from_record(irsaliye_id: int, *, fiyatli: bool = False) -> CustomerDispatchViewModel:
    """Kayıtlı irsaliyeden çıktı modeli (PDF ve Word aynı veriyi kullanır).

    Varsayılan miktar esaslıdır; ``fiyatli=True`` ayrı çıktı seçeneğidir. İç not,
    depo notu, maliyet ve kâr bilgisi modele alınmaz.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.satis_irsaliyesi import SatisIrsaliyesi
    from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri

    branding, logo = _firma_markasi()
    with get_session() as session:
        ir = session.scalar(
            select(SatisIrsaliyesi)
            .options(
                selectinload(SatisIrsaliyesi.satirlar),
                selectinload(SatisIrsaliyesi.cari),
                selectinload(SatisIrsaliyesi.siparis),
            )
            .where(SatisIrsaliyesi.id == int(irsaliye_id))
        )
        if ir is None:
            raise ValueError("İrsaliye bulunamadı; silinmiş olabilir.")
        satirlar = sorted(ir.satirlar, key=lambda s: int(s.id or 0))
        siparis_nolari: list[str] = []
        if ir.siparis is not None and ir.siparis.siparis_no:
            siparis_nolari.append(ir.siparis.siparis_no)
        ssidler = [int(s.siparis_satiri_id) for s in satirlar if s.siparis_satiri_id]
        if ssidler:
            for no in session.scalars(
                select(SatisSiparisi.siparis_no)
                .join(SatisSiparisiSatiri, SatisSiparisiSatiri.siparis_id == SatisSiparisi.id)
                .where(SatisSiparisiSatiri.id.in_(ssidler))
                .order_by(SatisSiparisi.siparis_no)
            ):
                if no and no not in siparis_nolari:
                    siparis_nolari.append(no)
        cari = ir.cari
        lines, ara, kdv_t = _satir_modelleri(
            [
                {
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "aciklama": s.aciklama,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_fiyat": s.birim_fiyat,
                    "iskonto_orani": s.iskonto_orani,
                    "kdv_orani": s.kdv_orani,
                }
                for s in satirlar
            ],
            fiyatli,
        )
        sevk_tarih_saat = ""
        if ir.fiili_sevk_tarihi:
            sevk_tarih_saat = _tarih(ir.fiili_sevk_tarihi)
            if ir.fiili_sevk_saati:
                sevk_tarih_saat += f" {ir.fiili_sevk_saati:%H:%M}"
        musteri = {
            "kod": getattr(cari, "cari_kodu", None) or ir.musteri_kodu_snap or "",
            "unvan": getattr(cari, "unvan", None) or ir.musteri_unvan_snap or "",
            "vergi_dairesi": getattr(cari, "vergi_dairesi", None) or ir.vergi_dairesi_snap or "",
            "vergi_no": getattr(cari, "vergi_numarasi", None)
            or getattr(cari, "tc_kimlik", None)
            or ir.vergi_no_snap
            or "",
            "adres": _birlestir(
                getattr(cari, "adres", None),
                _birlestir(getattr(cari, "ilce", None), getattr(cari, "il", None)),
                ayrac=" — ",
            ),
            "telefon": getattr(cari, "telefon", None) or "",
        }
        sevk = {
            "adres": ir.sevk_adresi or "",
            "il": ir.sevk_il or "",
            "ilce": ir.sevk_ilce or "",
            "teslim_kisi": ir.teslim_kisi or "",
            "teslim_telefon": ir.teslim_telefon or "",
            "sevkiyat_yontemi": ir.sevkiyat_yontemi or "",
            "nakliyeci": ir.nakliyeci or "",
            "plaka": ir.arac_plaka or "",
            "sofor": ir.sofor_adi or "",
            "takip_no": ir.takip_no or "",
        }
        vm = CustomerDispatchViewModel(
            firma={
                "unvan": branding.get("unvan") or "",
                "adres": _birlestir(
                    branding.get("adres"), _birlestir(branding.get("ilce"), branding.get("il")), ayrac=" — "
                ),
                "telefon": branding.get("telefon") or "",
                "email": branding.get("email") or "",
                "vergi_dairesi": branding.get("vergi_dairesi") or "",
                "vergi_no": branding.get("vergi_no") or "",
                "mersis": branding.get("mersis") or "",
            },
            logo_data_uri=logo,
            irsaliye_no=ir.irsaliye_no or "",
            irsaliye_tarihi=_tarih(ir.irsaliye_tarihi),
            depo=ir.depo or "ANA DEPO",
            durum=ir.durum or "",
            is_priced=bool(fiyatli),
            musteri=musteri,
            sevk=sevk,
            satirlar=lines,
            ara_toplam=ara,
            kdv_toplam=kdv_t,
            genel_toplam=ara + kdv_t,
            ara_goster=_para(ara) if fiyatli else "",
            kdv_goster=_para(kdv_t) if fiyatli else "",
            genel_goster=_para(ara + kdv_t) if fiyatli else "",
            musteri_notu=(ir.musteri_notu or ir.ayrintili_notlar or "").strip(),
            sevk_notu=(ir.sevk_notu or "").strip(),
            siparis_no=", ".join(siparis_nolari),
            para_birimi=ir.para_birimi or "TRY",
            toplam_miktar_goster=toplam_miktar_metni(lines),
            aciklama=(ir.aciklama or "").strip(),
            sevk_tarih_saat=sevk_tarih_saat,
            siparis_nolari=siparis_nolari,
            olusturma=datetime.now().strftime("%d.%m.%Y %H:%M"),
        )
    assert_customer_model_safe(vm)
    return vm


def build_customer_dispatch_from_dialog(dialog) -> CustomerDispatchViewModel:
    """Dialog / kayıtlı irsaliyeden müşteri ViewModel — ic_not kopyalanmaz."""
    try:
        from invoice_print.branding import load_company_branding, logo_data_uri

        branding = load_company_branding()
        logo = logo_data_uri(branding.get("logo_yolu"))
    except Exception:
        branding = {}
        logo = None

    girdiler = getattr(dialog, "girdiler", {}) or {}
    irsaliye = getattr(dialog, "irsaliye", None)

    def _g(anahtar, varsayilan=""):
        w = girdiler.get(anahtar)
        if w is None:
            return varsayilan
        try:
            return (w.get() or "").strip() or varsayilan
        except Exception:
            return varsayilan

    musteri_obj = None
    try:
        musteri_map = getattr(dialog, "musteri_map", {}) or {}
        musteri_obj = musteri_map.get(dialog.musteri.get()) if hasattr(dialog, "musteri") else None
    except Exception:
        musteri_obj = None
    if musteri_obj is None and irsaliye is not None:
        musteri_obj = getattr(irsaliye, "cari", None)

    is_priced = True
    if hasattr(dialog, "_is_priced"):
        try:
            is_priced = bool(dialog._is_priced.get())
        except Exception:
            is_priced = True
    elif irsaliye is not None:
        is_priced = bool(getattr(irsaliye, "is_priced", True))

    lines, ara, kdv_t = _satir_modelleri(list(getattr(dialog, "satirlar", []) or []), is_priced)

    musteri = {
        "kod": getattr(musteri_obj, "cari_kodu", None)
        or getattr(irsaliye, "musteri_kodu_snap", None)
        or "",
        "unvan": getattr(musteri_obj, "unvan", None)
        or getattr(irsaliye, "musteri_unvan_snap", None)
        or "",
        "vergi_dairesi": getattr(musteri_obj, "vergi_dairesi", None)
        or getattr(irsaliye, "vergi_dairesi_snap", None)
        or "",
        "vergi_no": getattr(musteri_obj, "vergi_numarasi", None)
        or getattr(irsaliye, "vergi_no_snap", None)
        or "",
        "adres": getattr(musteri_obj, "adres", None) or "",
    }
    sevk = {
        "adres": _g("sevk_adresi") or getattr(irsaliye, "sevk_adresi", None) or "",
        "il": _g("sevk_il") or getattr(irsaliye, "sevk_il", None) or "",
        "ilce": _g("sevk_ilce") or getattr(irsaliye, "sevk_ilce", None) or "",
        "teslim_kisi": _g("teslim_kisi") or getattr(irsaliye, "teslim_kisi", None) or "",
        "teslim_telefon": _g("teslim_telefon") or getattr(irsaliye, "teslim_telefon", None) or "",
        "nakliyeci": _g("nakliyeci") or getattr(irsaliye, "nakliyeci", None) or "",
        "plaka": _g("arac_plaka") or getattr(irsaliye, "arac_plaka", None) or "",
        "takip_no": _g("takip_no") or getattr(irsaliye, "takip_no", None) or "",
    }
    musteri_notu = ""
    sevk_notu = ""
    if hasattr(dialog, "musteri_notu"):
        try:
            musteri_notu = dialog.musteri_notu.get("1.0", "end").strip()
        except Exception:
            pass
    if hasattr(dialog, "sevk_notu"):
        try:
            sevk_notu = dialog.sevk_notu.get("1.0", "end").strip()
        except Exception:
            pass
    if not musteri_notu and irsaliye is not None:
        musteri_notu = getattr(irsaliye, "musteri_notu", None) or ""
    if not sevk_notu and irsaliye is not None:
        sevk_notu = getattr(irsaliye, "sevk_notu", None) or ""

    siparis_no = ""
    try:
        if hasattr(dialog, "siparis_secimi") and dialog.siparis_secimi.get():
            siparis_no = dialog.siparis_secimi.get()
        elif irsaliye and getattr(irsaliye, "siparis", None):
            siparis_no = irsaliye.siparis.siparis_no
    except Exception:
        pass

    depo = ""
    try:
        depo = dialog.depo.get().strip() if hasattr(dialog, "depo") else ""
    except Exception:
        depo = getattr(irsaliye, "depo", None) or ""

    vm = CustomerDispatchViewModel(
        firma={
            "unvan": branding.get("unvan") or branding.get("firma_adi") or "",
            "adres": branding.get("adres") or "",
            "telefon": branding.get("telefon") or "",
            "vergi_dairesi": branding.get("vergi_dairesi") or "",
            "vergi_no": branding.get("vergi_no") or "",
        },
        logo_data_uri=logo,
        irsaliye_no=_g("irsaliye_no")
        or (getattr(irsaliye, "irsaliye_no", None) if irsaliye else "")
        or "",
        irsaliye_tarihi=_g("irsaliye_tarihi")
        or _tarih(getattr(irsaliye, "irsaliye_tarihi", None) if irsaliye else None),
        depo=depo or "ANA DEPO",
        durum=getattr(dialog, "_durum_var", None).get()
        if getattr(dialog, "_durum_var", None)
        else (getattr(irsaliye, "durum", None) or ""),
        is_priced=is_priced,
        musteri=musteri,
        sevk=sevk,
        satirlar=lines,
        ara_toplam=ara,
        kdv_toplam=kdv_t,
        genel_toplam=ara + kdv_t,
        ara_goster=_para(ara) if is_priced else "",
        kdv_goster=_para(kdv_t) if is_priced else "",
        genel_goster=_para(ara + kdv_t) if is_priced else "",
        musteri_notu=musteri_notu,
        sevk_notu=sevk_notu,
        siparis_no=siparis_no,
        toplam_miktar_goster=toplam_miktar_metni(lines),
        aciklama=_g("aciklama") or (getattr(irsaliye, "aciklama", None) if irsaliye else "") or "",
    )
    assert_customer_model_safe(vm)
    return vm


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def firma_vergi_metni(f: dict[str, Any]) -> str:
    return _birlestir(
        f"VD: {f['vergi_dairesi']}" if f.get("vergi_dairesi") else "",
        f"VN: {f['vergi_no']}" if f.get("vergi_no") else "",
        f"MERSİS: {f['mersis']}" if f.get("mersis") else "",
        ayrac="  ·  ",
    )


def musteri_vergi_metni(m: dict[str, Any]) -> str:
    return _birlestir(
        f"Vergi Dairesi: {m['vergi_dairesi']}" if m.get("vergi_dairesi") else "",
        f"Vergi/TC No: {m['vergi_no']}" if m.get("vergi_no") else "",
        ayrac="  ·  ",
    )


def teslimat_satirlari(vm: CustomerDispatchViewModel) -> list[tuple[str, str]]:
    """Teslimat kutusu (etiket, değer) — boş olanlar atlanır; PDF ve Word ortak."""
    s = vm.sevk or {}
    adres = _birlestir(s.get("adres"), _birlestir(s.get("ilce"), s.get("il")), ayrac=" — ")
    satirlar = [
        ("Teslimat Adresi", adres or (vm.musteri or {}).get("adres") or ""),
        ("Teslim Alacak", _birlestir(s.get("teslim_kisi"), s.get("teslim_telefon"), ayrac=" · ")),
        ("Sevkiyat", _birlestir(s.get("sevkiyat_yontemi"), s.get("nakliyeci"), ayrac=" · ")),
        ("Araç / Şoför", _birlestir(s.get("plaka"), s.get("sofor"), ayrac=" · ")),
        ("Takip No", s.get("takip_no") or ""),
        ("Sipariş No", ", ".join(vm.siparis_nolari) or vm.siparis_no or ""),
    ]
    return [(k, v) for k, v in satirlar if v]


def belge_bilgi_satirlari(vm: CustomerDispatchViewModel) -> list[tuple[str, str]]:
    satirlar = [
        ("İrsaliye No", vm.irsaliye_no),
        ("Evrak Tarihi", vm.irsaliye_tarihi),
        ("Sevk Tarihi / Saati", vm.sevk_tarih_saat),
        ("Depo", vm.depo),
    ]
    return [(k, v) for k, v in satirlar if v]


def not_bolumleri(vm: CustomerDispatchViewModel) -> list[tuple[str, str]]:
    return [
        (baslik, metin)
        for baslik, metin in (
            ("Açıklama", vm.aciklama),
            ("Müşteri Notu", vm.musteri_notu),
            ("Sevk Notu", vm.sevk_notu),
        )
        if (metin or "").strip()
    ]


def _cok_satir(metin: str) -> str:
    return "<br/>".join(_e(p) for p in str(metin or "").splitlines())


def render_customer_dispatch_html(vm: CustomerDispatchViewModel) -> str:
    """A4 dikey SATIŞ İRSALİYESİ HTML.

    Sayfa altındaki «evrak no · Sayfa X / Y» satırı PDF üretiminden sonra basılır
    (``invoice_print.irsaliye_cikti``); alt boşluk bunun için ayrılmıştır.
    """
    assert_customer_model_safe(vm)
    f = vm.firma or {}
    m = vm.musteri or {}
    logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>' if vm.logo_data_uri else ""

    if vm.is_priced:
        colgroup = (
            "<col style='width:8mm'/><col style='width:26mm'/><col/><col style='width:15mm'/>"
            "<col style='width:18mm'/><col style='width:22mm'/><col style='width:11mm'/>"
            "<col style='width:11mm'/><col style='width:25mm'/>"
        )
        head_extra = "<th class='r'>Birim Fiyat</th><th class='c'>İsk.</th><th class='c'>KDV</th><th class='r'>Tutar</th>"
    else:
        colgroup = (
            "<col style='width:10mm'/><col style='width:34mm'/><col/>"
            "<col style='width:20mm'/><col style='width:24mm'/>"
        )
        head_extra = ""

    satir_html = []
    for line in vm.satirlar:
        ad = _e(line.urun_adi)
        if line.aciklama:
            ad += f"<div class='muted'>{_e(line.aciklama)}</div>"
        row = (
            f"<tr><td class='c'>{line.sira}</td>"
            f"<td class='kod'>{_e(line.urun_kodu)}</td>"
            f"<td class='ad'>{ad}</td>"
            f"<td class='c'>{_e(line.birim)}</td>"
            f"<td class='r miktar'>{_e(line.miktar_goster)}</td>"
        )
        if vm.is_priced:
            row += (
                f"<td class='r'>{_e(line.birim_fiyat_goster)}</td>"
                f"<td class='c'>{_e(line.iskonto_goster)}</td>"
                f"<td class='c'>{_e(line.kdv_oran_goster)}</td>"
                f"<td class='r'>{_e(line.satir_toplam_goster)}</td>"
            )
        satir_html.append(row + "</tr>")

    toplamlar = birim_toplamlari(vm.satirlar)
    toplam_miktar = vm.toplam_miktar_goster or toplam_miktar_metni(vm.satirlar)
    birim_rozet = "".join(
        f"<span class='rozet'>{_e(miktar_metni(mk))} {_e(b)}</span>" for b, mk in toplamlar
    )
    toplam_html = (
        "<div class='toplam'>"
        f"<div class='toplam-miktar'><span class='etiket'>Toplam Miktar: {_e(toplam_miktar)}</span>"
        f"<div class='rozetler'>{birim_rozet}</div>"
        f"<div class='aciklama-kucuk'>Kalem: {len(vm.satirlar)}"
        f"{' · Farklı birimler ayrı toplanır' if len(toplamlar) > 1 else ''}</div></div>"
    )
    if vm.is_priced:
        pb = _e(vm.para_birimi)
        toplam_html += (
            "<table class='tutarlar'>"
            f"<tr><td>Ara Toplam</td><td class='r'>{_e(vm.ara_goster)} {pb}</td></tr>"
            f"<tr><td>KDV</td><td class='r'>{_e(vm.kdv_goster)} {pb}</td></tr>"
            f"<tr class='genel'><td>Genel Toplam</td><td class='r'>{_e(vm.genel_goster)} {pb}</td></tr>"
            "</table>"
        )
    toplam_html += "</div>"

    notlar = "".join(
        f"<div class='not'><strong>{_e(baslik)}</strong><p>{_cok_satir(metin)}</p></div>"
        for baslik, metin in not_bolumleri(vm)
    )
    bilgi = "".join(
        f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in belge_bilgi_satirlari(vm)
    )
    teslimat = "".join(
        f"<div class='satir'><span>{_e(k)}</span><b>{_cok_satir(v)}</b></div>"
        for k, v in teslimat_satirlari(vm)
    )
    musteri_vergi = musteri_vergi_metni(m)
    firma_vergi = firma_vergi_metni(f)
    firma_iletisim = _birlestir(
        f"Tel: {f['telefon']}" if f.get("telefon") else "", f.get("email"), ayrac="  ·  "
    )

    def _imza_kutusu(baslik: str) -> str:
        return (
            f"<div class='imza-kutu'><h4>{baslik}</h4>"
            "<div class='alan'><span>Adı Soyadı</span><i></i></div>"
            "<div class='alan'><span>Tarih / Saat</span><i></i></div>"
            "<div class='alan imza'><span>İmza</span><i></i></div></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} — {_e(vm.irsaliye_no)}</title>
<style>
@page {{ size: A4 portrait; margin: 12mm 12mm 18mm 12mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin:0; padding:0; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; color:#172B4D; font-size:9.5pt; line-height:1.35;
  -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.ust {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8mm; }}
.firma {{ flex:1; min-width:0; }}
.logo {{ max-height:18mm; max-width:55mm; display:block; margin-bottom:2mm; }}
.firma .unvan {{ font-size:12pt; font-weight:700; color:#102A43; }}
.firma .meta {{ color:#486581; font-size:8.5pt; overflow-wrap:anywhere; }}
.belge {{ width:84mm; flex:none; }}
.belge h1 {{ margin:0 0 2mm; background:#102A43; color:#FFFFFF; font-size:15pt; letter-spacing:1px;
  padding:2.5mm 4mm; border-left:5px solid #F4C542; }}
.belge table {{ width:100%; border-collapse:collapse; }}
.belge th {{ text-align:left; color:#627D98; font-weight:600; padding:1mm 2mm; width:29mm; white-space:nowrap; }}
.belge td {{ font-weight:700; color:#102A43; padding:1mm 2mm; white-space:nowrap; }}
.serit {{ height:2.2mm; background:#F4C542; margin:4mm 0 4mm; border-bottom:1.2mm solid #102A43; }}
.kutular {{ display:flex; gap:4mm; margin-bottom:4mm; }}
.kutu {{ flex:1; min-width:0; background:#F3F6F9; border:1px solid #D9E2EC; border-top:3px solid #102A43;
  padding:2.5mm 3mm; break-inside:avoid; }}
.kutu h3 {{ margin:0 0 1.5mm; color:#102A43; font-size:9pt; letter-spacing:.5px; }}
.kutu .buyuk {{ font-size:10.5pt; font-weight:700; color:#102A43; overflow-wrap:anywhere; }}
.kutu .satir {{ display:flex; gap:2mm; margin-top:1mm; }}
.kutu .satir span {{ color:#627D98; width:27mm; flex:none; }}
.kutu .satir b {{ font-weight:600; overflow-wrap:anywhere; min-width:0; }}
table.urunler {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
table.urunler thead {{ display:table-header-group; }}
table.urunler tr {{ break-inside:avoid; page-break-inside:avoid; }}
table.urunler th {{ background:#102A43; color:#FFFFFF; padding:2mm 1.5mm; font-size:8.5pt; text-align:left;
  border-bottom:2px solid #F4C542; }}
table.urunler td {{ border-bottom:1px solid #D9E2EC; padding:1.6mm 1.5mm; vertical-align:top;
  overflow-wrap:anywhere; word-break:break-word; }}
table.urunler tbody tr:nth-child(even) td {{ background:#F8FAFC; }}
.c {{ text-align:center !important; }} .r {{ text-align:right !important; }}
td.miktar {{ font-weight:700; }}
.muted {{ color:#627D98; font-size:8pt; margin-top:.5mm; }}
.toplam {{ display:flex; justify-content:space-between; align-items:flex-start; gap:6mm; margin-top:3mm;
  break-inside:avoid; }}
.toplam-miktar .etiket {{ font-weight:700; color:#102A43; }}
.rozetler {{ margin-top:1mm; }}
.rozet {{ display:inline-block; background:#FFE89A; color:#081B2C; font-weight:700; padding:1mm 2.5mm;
  margin:0 1.5mm 1.5mm 0; border-left:3px solid #102A43; }}
.aciklama-kucuk {{ color:#627D98; font-size:8pt; }}
table.tutarlar {{ border-collapse:collapse; min-width:62mm; }}
table.tutarlar td {{ padding:1mm 2mm; }}
table.tutarlar tr.genel td {{ background:#102A43; color:#F4C542; font-weight:700; }}
.son {{ break-inside:avoid; page-break-inside:avoid; margin-top:5mm; }}
.not {{ border:1px solid #D9E2EC; border-left:3px solid #F4C542; padding:2mm 3mm; margin-bottom:3mm;
  break-inside:avoid; }}
.not p {{ margin:1mm 0 0; overflow-wrap:anywhere; }}
.teslim {{ display:flex; gap:6mm; break-inside:avoid; page-break-inside:avoid; }}
.imza-kutu {{ flex:1; border:1.2px solid #102A43; }}
.imza-kutu h4 {{ margin:0; background:#102A43; color:#F4C542; padding:1.8mm 3mm; font-size:9.5pt; letter-spacing:1px; }}
.imza-kutu .alan {{ display:flex; align-items:flex-end; gap:2mm; padding:0 3mm; height:10mm; }}
.imza-kutu .alan.imza {{ height:22mm; }}
.imza-kutu .alan span {{ width:24mm; flex:none; color:#486581; padding-bottom:1mm; }}
.imza-kutu .alan i {{ flex:1; border-bottom:1px dotted #486581; margin-bottom:1.5mm; }}
.alt {{ margin-top:3mm; font-size:7.5pt; color:#94A3B8; }}
</style>
</head>
<body>
<div class="ust">
  <div class="firma">
    {logo}
    <div class="unvan">{_e(f.get("unvan"))}</div>
    <div class="meta">{_e(f.get("adres"))}</div>
    <div class="meta">{_e(firma_iletisim)}</div>
    <div class="meta">{_e(firma_vergi)}</div>
  </div>
  <div class="belge">
    <h1>{_e(vm.belge_baslik)}</h1>
    <table>{bilgi}</table>
  </div>
</div>
<div class="serit"></div>
<div class="kutular">
  <div class="kutu">
    <h3>MÜŞTERİ</h3>
    <div class="buyuk">{_e(m.get("unvan"))}</div>
    <div class="satir"><span>Müşteri Kodu</span><b>{_e(m.get("kod"))}</b></div>
    {f'<div class="satir"><span>Vergi Bilgisi</span><b>{_e(musteri_vergi)}</b></div>' if musteri_vergi else ''}
    {f'<div class="satir"><span>Adres</span><b>{_e(m.get("adres"))}</b></div>' if m.get("adres") else ''}
  </div>
  <div class="kutu">
    <h3>TESLİMAT</h3>
    {teslimat}
  </div>
</div>
<table class="urunler">
  <colgroup>{colgroup}</colgroup>
  <thead>
    <tr><th class="c">Sıra</th><th>Stok Kodu</th><th>Ürün Adı / Açıklama</th><th class="c">Birim</th><th class="r">Miktar</th>{head_extra}</tr>
  </thead>
  <tbody>
    {''.join(satir_html)}
  </tbody>
</table>
{toplam_html}
<div class="son">
  {notlar}
  <div class="teslim">{_imza_kutusu("TESLİM EDEN")}{_imza_kutusu("TESLİM ALAN")}</div>
  <div class="alt">Bu belge müşteri sevk irsaliyesidir.{f' Oluşturulma: {_e(vm.olusturma)}' if vm.olusturma else ''}</div>
</div>
</body>
</html>"""
