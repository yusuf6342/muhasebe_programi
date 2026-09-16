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
    belge_baslik: str = "SEVK İRSALİYESİ"
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

    satirlar_raw = list(getattr(dialog, "satirlar", []) or [])
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
                miktar_goster=f"{miktar:f}".rstrip("0").rstrip(".") or "0",
                birim_fiyat_goster=_para(fiyat) if is_priced else "—",
                iskonto_goster=f"%{iskonto}" if is_priced else "—",
                kdv_oran_goster=f"%{kdv}" if is_priced else "—",
                satir_toplam_goster=_para(toplam) if is_priced else "—",
            )
        )

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
    )
    assert_customer_model_safe(vm)
    return vm


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def render_customer_dispatch_html(vm: CustomerDispatchViewModel) -> str:
    """A4 SEVK İRSALİYESİ HTML — fiyatlar is_priced=False ise gizlenir."""
    assert_customer_model_safe(vm)
    f = vm.firma or {}
    m = vm.musteri or {}
    s = vm.sevk or {}
    logo = ""
    if vm.logo_data_uri:
        logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>'

    if vm.is_priced:
        head_extra = (
            "<th>Birim Fiyat</th><th>İsk</th><th>KDV</th><th>Satır Toplam</th>"
        )
    else:
        head_extra = ""

    satir_html = []
    for line in vm.satirlar:
        row = (
            f"<tr><td class='c'>{line.sira}</td>"
            f"<td>{_e(line.urun_kodu)}</td>"
            f"<td>{_e(line.urun_adi)}"
            f"{('<div class=\"muted\">' + _e(line.aciklama) + '</div>') if line.aciklama else ''}</td>"
            f"<td class='r'>{_e(line.miktar_goster)}</td>"
            f"<td class='c'>{_e(line.birim)}</td>"
        )
        if vm.is_priced:
            row += (
                f"<td class='r'>{_e(line.birim_fiyat_goster)}</td>"
                f"<td class='c'>{_e(line.iskonto_goster)}</td>"
                f"<td class='c'>{_e(line.kdv_oran_goster)}</td>"
                f"<td class='r'>{_e(line.satir_toplam_goster)}</td>"
            )
        row += "</tr>"
        satir_html.append(row)

    toplam_html = ""
    if vm.is_priced:
        toplam_html = f"""
        <div class="toplam">
          <div>Ara Toplam: {_e(vm.ara_goster)} {vm.para_birimi}</div>
          <div>KDV: {_e(vm.kdv_goster)} {vm.para_birimi}</div>
          <div class="genel">Genel Toplam: {_e(vm.genel_goster)} {vm.para_birimi}</div>
        </div>"""

    notlar = ""
    if vm.musteri_notu:
        notlar += f"<div class='bolum'><strong>Müşteri Notu</strong><p>{_e(vm.musteri_notu)}</p></div>"
    if vm.sevk_notu:
        notlar += f"<div class='bolum'><strong>Sevk Notu</strong><p>{_e(vm.sevk_notu)}</p></div>"

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.onizleme_baslik)} — {_e(vm.irsaliye_no)}</title>
<style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1a1a1a; font-size: 11px; }}
.header {{ display:flex; justify-content:space-between; border-bottom:3px solid #1B2A4A; padding-bottom:10px; margin-bottom:14px; }}
.logo {{ max-height:64px; }}
h1 {{ color:#1B2A4A; margin:0 0 4px; font-size:20px; letter-spacing:1px; }}
.meta {{ color:#475569; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }}
.kutu {{ background:#F8FAFC; border:1px solid #E2E8F0; padding:10px; border-radius:4px; }}
.kutu h3 {{ margin:0 0 6px; color:#1B2A4A; font-size:12px; }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
th {{ background:#1B2A4A; color:#fff; padding:6px; text-align:left; }}
td {{ border-bottom:1px solid #E2E8F0; padding:6px; vertical-align:top; }}
.c {{ text-align:center; }} .r {{ text-align:right; }}
.muted {{ color:#64748B; font-size:10px; margin-top:2px; }}
.toplam {{ margin-top:12px; text-align:right; }}
.toplam .genel {{ font-weight:700; font-size:13px; color:#1B2A4A; }}
.bolum {{ margin-top:12px; }}
.footer {{ margin-top:24px; font-size:9px; color:#94A3B8; border-top:1px solid #E2E8F0; padding-top:8px; }}
</style>
</head>
<body>
<div class="header">
  <div>
    {logo}
    <div><strong>{_e(f.get("unvan"))}</strong></div>
    <div class="meta">{_e(f.get("adres"))}</div>
    <div class="meta">{_e(f.get("telefon"))}</div>
  </div>
  <div style="text-align:right">
    <h1>{_e(vm.belge_baslik)}</h1>
    <div><strong>No:</strong> {_e(vm.irsaliye_no)}</div>
    <div><strong>Tarih:</strong> {_e(vm.irsaliye_tarihi)}</div>
    <div><strong>Depo:</strong> {_e(vm.depo)}</div>
    {f'<div><strong>Sipariş:</strong> {_e(vm.siparis_no)}</div>' if vm.siparis_no else ''}
  </div>
</div>
<div class="grid">
  <div class="kutu">
    <h3>Müşteri</h3>
    <div><strong>{_e(m.get("unvan"))}</strong> ({_e(m.get("kod"))})</div>
    <div>{_e(m.get("adres"))}</div>
    <div>VD: {_e(m.get("vergi_dairesi"))} — VN: {_e(m.get("vergi_no"))}</div>
  </div>
  <div class="kutu">
    <h3>Sevk Adresi</h3>
    <div>{_e(s.get("adres"))}</div>
    <div>{_e(s.get("ilce"))} / {_e(s.get("il"))}</div>
    <div>Teslim: {_e(s.get("teslim_kisi"))} — {_e(s.get("teslim_telefon"))}</div>
    <div>Nakliye: {_e(s.get("nakliyeci"))} · Plaka: {_e(s.get("plaka"))}</div>
    {f'<div>Takip: {_e(s.get("takip_no"))}</div>' if s.get("takip_no") else ''}
  </div>
</div>
<table>
  <thead>
    <tr>
      <th>#</th><th>Kod</th><th>Ürün</th><th>Miktar</th><th>Birim</th>
      {head_extra}
    </tr>
  </thead>
  <tbody>
    {''.join(satir_html)}
  </tbody>
</table>
{toplam_html}
{notlar}
<div class="footer">Bu belge müşteri sevk irsaliyesidir. Şirket içi notlar paylaşılmaz.</div>
</body>
</html>"""
