"""SATIN ALMA TALEBİ görünümü — şirket içi belge (A4 dikey).

PDF ve Word aynı görünüm modelini kullanır. Fiyat kolonları yalnızca
``alis_talep_fiyat_gorme`` yetkisi olan ve fiyatlı çıktı isteyen kullanıcıda modele girer;
fiyatsız çıktıda fiyat alanları modelde hiç bulunmaz.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from database.irsaliye_customer_view import (
    _birlestir,
    _d,
    _firma_markasi,
    _para,
    _tarih,
    birim_toplamlari,
    firma_vergi_metni,
    miktar_metni,
)

FILIGRANLI_DURUMLAR = {"TASLAK": "TASLAK", "İPTAL": "İPTAL", "REDDEDİLDİ": "REDDEDİLDİ"}
TAHMINI_NOT = "Tahmini bedeller bilgi amaçlıdır; finansal kayıt değildir ve stok, cari veya muhasebe etkisi yoktur."


@dataclass
class TalepFormSatiri:
    sira: int
    urun_kodu: str
    urun_adi: str
    aciklama: str = ""
    miktar: Decimal = Decimal("0")
    birim: str = "Adet"
    miktar_goster: str = ""
    ihtiyac: str = ""
    birim_fiyat_goster: str = ""
    tutar_goster: str = ""


@dataclass
class TalepFormViewModel:
    belge_baslik: str = "SATIN ALMA TALEBİ"
    firma: dict[str, Any] = field(default_factory=dict)
    logo_data_uri: str | None = None
    talep_no: str = ""
    talep_tarihi: str = ""
    ihtiyac_tarihi: str = ""
    durum: str = ""
    oncelik: str = ""
    isteyen: str = ""
    departman: str = ""
    depo: str = ""
    talep_nedeni: str = ""
    proje_ref: str = ""
    aciklama: str = ""
    onaylayan: str = ""
    onay_tarihi: str = ""
    fiyatli: bool = False
    tahmini_toplam_goster: str = ""
    satirlar: list[TalepFormSatiri] = field(default_factory=list)
    toplam_miktar_goster: str = ""
    olusturma: str = ""
    dovizli: bool = False
    ekler: list[str] = field(default_factory=list)

    @property
    def filigran(self) -> str:
        return FILIGRANLI_DURUMLAR.get(self.durum, "")

    @property
    def tahmini_notu(self) -> str:
        if not self.fiyatli:
            return ""
        return TAHMINI_NOT + (" Dövizli satırlar talepte kayıtlı kurla TL'ye çevrilmiştir." if self.dovizli else "")


def build_talep_form(talep_id: int, fiyatli: bool = False, ek_listesi: bool = False) -> TalepFormViewModel:
    from database.satin_alma_talep_service import SatinAlmaTalepService

    d = SatinAlmaTalepService.detay(int(talep_id))
    fiyatli = bool(fiyatli and d.get("fiyat_gorunur"))
    branding, logo = _firma_markasi()
    lines: list[TalepFormSatiri] = []
    toplam = Decimal("0")
    dovizli = False
    for i, s in enumerate(d["satirlar"], start=1):
        fiyat = s.get("tahmini_birim_fiyat") if fiyatli else None
        tutar = None
        pb = (s.get("para_birimi") or "TRY").upper()
        if fiyat is not None:
            tutar = _d(fiyat) * _d(s["miktar"])
            dovizli = dovizli or pb != "TRY"
            toplam += tutar * (_d(s.get("kur") or 1) if pb != "TRY" else Decimal("1"))
        pb_metin = pb.replace("TRY", "TL")
        lines.append(TalepFormSatiri(
            sira=i,
            urun_kodu=str(s.get("urun_kodu") or ""),
            urun_adi=str(s.get("urun_adi") or ""),
            aciklama=str(s.get("aciklama") or "").strip(),
            miktar=_d(s["miktar"]),
            birim=str(s.get("birim") or "Adet"),
            miktar_goster=miktar_metni(s["miktar"]),
            ihtiyac=_tarih(s.get("ihtiyac_tarihi") or d.get("ihtiyac_tarihi")),
            birim_fiyat_goster=f"{_para(fiyat)} {pb_metin}" if fiyat is not None else "",
            tutar_goster=f"{_para(tutar)} {pb_metin}" if tutar is not None else "",
        ))
    toplamlar = birim_toplamlari(lines)
    return TalepFormViewModel(
        firma={
            "unvan": branding.get("unvan") or "",
            "adres": _birlestir(branding.get("adres"), _birlestir(branding.get("ilce"), branding.get("il")), ayrac=" — "),
            "telefon": branding.get("telefon") or "",
            "email": branding.get("email") or "",
            "vergi_dairesi": branding.get("vergi_dairesi") or "",
            "vergi_no": branding.get("vergi_no") or "",
            "mersis": branding.get("mersis") or "",
        },
        logo_data_uri=logo,
        talep_no=d.get("talep_no") or "",
        talep_tarihi=_tarih(d.get("talep_tarihi")),
        ihtiyac_tarihi=_tarih(d.get("ihtiyac_tarihi")),
        durum=d.get("durum") or "",
        oncelik=d.get("oncelik") or "",
        isteyen=d.get("isteyen_kullanici") or "",
        departman=d.get("departman") or "",
        depo=d.get("depo") or "",
        talep_nedeni=(d.get("talep_nedeni") or "").strip(),
        proje_ref=(d.get("proje_ref") or "").strip(),
        aciklama=(d.get("aciklama") or "").strip(),
        onaylayan=d.get("onaylayan") or "",
        onay_tarihi=(d["onay_tarihi"].strftime("%d.%m.%Y %H:%M") if isinstance(d.get("onay_tarihi"), datetime)
                     else _tarih(d.get("onay_tarihi"))),
        fiyatli=fiyatli,
        tahmini_toplam_goster=_para(toplam) if fiyatli else "",
        satirlar=lines,
        toplam_miktar_goster=" + ".join(f"{miktar_metni(m)} {b}" for b, m in toplamlar),
        olusturma=datetime.now().strftime("%d.%m.%Y %H:%M"),
        dovizli=dovizli,
        ekler=[e["dosya_adi"] for e in d.get("ekler") or []] if ek_listesi else [],
    )


def belge_bilgi_satirlari(vm: TalepFormViewModel) -> list[tuple[str, str]]:
    satirlar = [
        ("Talep No", vm.talep_no),
        ("Talep Tarihi", vm.talep_tarihi),
        ("İhtiyaç Tarihi", vm.ihtiyac_tarihi),
        ("Öncelik", vm.oncelik),
        ("Durum", vm.durum),
    ]
    return [(k, v) for k, v in satirlar if v]


def talep_bilgi_satirlari(vm: TalepFormViewModel) -> list[tuple[str, str]]:
    satirlar = [
        ("Talep Eden", vm.isteyen),
        ("Departman", vm.departman),
        ("Depo", vm.depo),
        ("Talep Nedeni", vm.talep_nedeni),
        ("Proje / Referans", vm.proje_ref),
    ]
    return [(k, v) for k, v in satirlar if v]


def kolonlar(vm: TalepFormViewModel) -> list[tuple[str, str, float | None]]:
    """(başlık, hiza, genişlik mm; None = kalan). PDF ve Word ortak."""
    liste: list[tuple[str, str, float | None]] = [
        ("Sıra", "c", 10), ("Stok Kodu", "l", 24), ("Ürün Adı / Teknik Açıklama", "l", None),
        ("Birim", "c", 14), ("Miktar", "r", 17), ("İhtiyaç Tarihi", "c", 22),
    ]
    if vm.fiyatli:
        liste += [("Tahmini B. Fiyat", "r", 25), ("Tahmini Tutar", "r", 24)]
    return liste


def satir_degerleri(vm: TalepFormViewModel, s: TalepFormSatiri) -> list[str]:
    degerler = [str(s.sira), s.urun_kodu, s.urun_adi, s.birim, s.miktar_goster, s.ihtiyac]
    if vm.fiyatli:
        degerler += [s.birim_fiyat_goster, s.tutar_goster]
    return degerler


def onay_metni(vm: TalepFormViewModel) -> str:
    if vm.onaylayan and vm.onay_tarihi:
        return f"Dijital olarak onaylandı: {vm.onaylayan} — {vm.onay_tarihi}"
    return ""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _cok_satir(metin: str) -> str:
    return "<br/>".join(_e(p) for p in str(metin or "").splitlines())


def render_talep_form_html(vm: TalepFormViewModel) -> str:
    """A4 dikey SATIN ALMA TALEBİ. Sayfa numarası PDF üretiminden sonra basılır."""
    f = vm.firma or {}
    logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>' if vm.logo_data_uri else ""
    kol = kolonlar(vm)
    colgroup = "".join(f"<col style='width:{g}mm'/>" if g else "<col/>" for _b, _h, g in kol)
    thead = "".join(f"<th class='{h}'>{_e(b)}</th>" for b, h, _g in kol)
    satir_html = []
    for line in vm.satirlar:
        hucreler = []
        for i, (deger, (b, hiza, _g)) in enumerate(zip(satir_degerleri(vm, line), kol)):
            icerik = _e(deger)
            if i == 2 and line.aciklama:
                icerik += f"<div class='muted'>{_cok_satir(line.aciklama)}</div>"
            sinif = hiza + (" miktar" if b == "Miktar" else "") + (" kod" if i == 1 else "")
            hucreler.append(f"<td class='{sinif}'>{icerik}</td>")
        satir_html.append("<tr>" + "".join(hucreler) + "</tr>")
    bilgi = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in belge_bilgi_satirlari(vm))
    talep_bilgi = "".join(
        f"<div class='satir'><span>{_e(k)}</span><b>{_cok_satir(v)}</b></div>" for k, v in talep_bilgi_satirlari(vm)
    )
    firma_iletisim = _birlestir(f"Tel: {f['telefon']}" if f.get("telefon") else "", f.get("email"), ayrac="  ·  ")
    notlar = (
        f"<div class='not'><strong>Açıklama</strong><p>{_cok_satir(vm.aciklama)}</p></div>" if vm.aciklama else ""
    )
    toplam_tutar = (
        f"<table class='tutarlar'><tr class='genel'><td>Tahmini Toplam</td>"
        f"<td class='r'>{_e(vm.tahmini_toplam_goster)} TL</td></tr></table>" if vm.fiyatli else ""
    )
    tahmini_not = f"<div class='tahmini'>{_e(vm.tahmini_notu)}</div>" if vm.tahmini_notu else ""
    ek_html = (
        "<div class='not'><strong>Ekler</strong><ol>" + "".join(f"<li>{_e(a)}</li>" for a in vm.ekler)
        + "</ol></div>" if vm.ekler else ""
    )
    filigran = f"<div class='filigran'>{_e(vm.filigran)}</div>" if vm.filigran else ""
    onay = onay_metni(vm)

    def _imza_kutusu(baslik: str, ad: str = "", dijital: str = "") -> str:
        return (
            f"<div class='imza-kutu'><h4>{baslik}</h4>"
            f"<div class='alan'><span>Adı Soyadı</span><i>{_e(ad)}</i></div>"
            "<div class='alan'><span>Tarih</span><i></i></div>"
            "<div class='alan imza'><span>İmza</span><i></i></div>"
            + (f"<div class='dijital'>{_e(dijital)}</div>" if dijital else "")
            + "</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} — {_e(vm.talep_no)}</title>
<style>
@page {{ size: A4 portrait; margin: 12mm 12mm 18mm 12mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin:0; padding:0; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; color:#172B4D; font-size:9.5pt; line-height:1.35;
  -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.filigran {{ position:fixed; top:40%; left:0; right:0; text-align:center; font-size:80pt; font-weight:800;
  color:rgba(200,30,30,.13); transform:rotate(-30deg); z-index:0; pointer-events:none; letter-spacing:6px; }}
.ust {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8mm; }}
.firma {{ flex:1; min-width:0; }}
.logo {{ max-height:18mm; max-width:55mm; display:block; margin-bottom:2mm; }}
.firma .unvan {{ font-size:12pt; font-weight:700; color:#102A43; }}
.firma .meta {{ color:#486581; font-size:8.5pt; overflow-wrap:anywhere; }}
.belge {{ width:88mm; flex:none; }}
.belge h1 {{ margin:0 0 2mm; background:#102A43; color:#FFFFFF; font-size:13pt; letter-spacing:.5px;
  padding:2.5mm 4mm; border-left:5px solid #F4C542; white-space:nowrap; }}
.belge table {{ width:100%; border-collapse:collapse; }}
.belge th {{ text-align:left; color:#627D98; font-weight:600; padding:1mm 2mm; width:27mm; white-space:nowrap; }}
.belge td {{ font-weight:700; color:#102A43; padding:1mm 2mm; overflow-wrap:anywhere; }}
.serit {{ height:2.2mm; background:#F4C542; margin:4mm 0 4mm; border-bottom:1.2mm solid #102A43; }}
.kutu {{ background:#F3F6F9; border:1px solid #D9E2EC; border-top:3px solid #102A43; padding:2.5mm 3mm;
  margin-bottom:4mm; break-inside:avoid; }}
.kutu h3 {{ margin:0 0 1.5mm; color:#102A43; font-size:9pt; letter-spacing:.5px; }}
.kutu .satir {{ display:flex; gap:2mm; margin-top:1mm; }}
.kutu .satir span {{ color:#627D98; width:32mm; flex:none; }}
.kutu .satir b {{ font-weight:600; overflow-wrap:anywhere; min-width:0; }}
table.urunler {{ width:100%; border-collapse:collapse; table-layout:fixed; position:relative; }}
table.urunler thead {{ display:table-header-group; }}
table.urunler tr {{ break-inside:avoid; page-break-inside:avoid; }}
table.urunler th {{ background:#102A43; color:#FFFFFF; padding:2mm 1.2mm; font-size:8pt; text-align:left;
  border-bottom:2px solid #F4C542; }}
table.urunler td {{ border-bottom:1px solid #D9E2EC; padding:1.6mm 1.2mm; vertical-align:top; font-size:8.5pt;
  overflow-wrap:anywhere; word-break:break-word; }}
table.urunler tbody tr:nth-child(even) td {{ background:rgba(243,246,249,.7); }}
.c {{ text-align:center !important; }} .r {{ text-align:right !important; }}
td.miktar {{ font-weight:700; }}
.muted {{ color:#627D98; font-size:7.5pt; margin-top:.5mm; }}
.toplam {{ display:flex; justify-content:space-between; align-items:flex-start; gap:6mm; margin-top:3mm;
  break-inside:avoid; }}
.toplam .etiket {{ font-weight:700; color:#102A43; }}
table.tutarlar {{ border-collapse:collapse; min-width:70mm; }}
table.tutarlar td {{ padding:1mm 2mm; }}
table.tutarlar tr.genel td {{ background:#102A43; color:#F4C542; font-weight:700; font-size:10.5pt; }}
.son {{ margin-top:4mm; }}
.not {{ border:1px solid #D9E2EC; border-left:3px solid #F4C542; padding:2mm 3mm; margin-bottom:3mm;
  break-inside:avoid; }}
.not p {{ margin:1mm 0 0; overflow-wrap:anywhere; }}
.not ol {{ margin:1mm 0 0 5mm; padding:0; overflow-wrap:anywhere; }}
.tahmini {{ margin-top:2mm; font-size:7.5pt; color:#9A6700; text-align:right; break-inside:avoid; }}
.imzalar {{ display:flex; gap:4mm; break-inside:avoid; page-break-inside:avoid; }}
.imza-kutu {{ flex:1; border:1.2px solid #102A43; min-width:0; }}
.imza-kutu h4 {{ margin:0; background:#102A43; color:#F4C542; padding:1.8mm 3mm; font-size:9pt; letter-spacing:1px; }}
.imza-kutu .alan {{ display:flex; align-items:flex-end; gap:2mm; padding:0 3mm; height:8mm; }}
.imza-kutu .alan.imza {{ height:14mm; }}
.imza-kutu .alan span {{ width:20mm; flex:none; color:#486581; padding-bottom:1mm; }}
.imza-kutu .alan i {{ flex:1; border-bottom:1px dotted #486581; margin-bottom:1.5mm; font-style:normal;
  font-weight:600; overflow-wrap:anywhere; }}
.imza-kutu .dijital {{ margin:1mm 3mm 2mm; color:#0F7B3F; font-size:7.5pt; font-weight:600; }}
.alt {{ margin-top:2mm; font-size:7.5pt; color:#94A3B8; }}
</style>
</head>
<body>
{filigran}
<div class="ust">
  <div class="firma">
    {logo}
    <div class="unvan">{_e(f.get("unvan"))}</div>
    <div class="meta">{_e(f.get("adres"))}</div>
    <div class="meta">{_e(firma_iletisim)}</div>
    <div class="meta">{_e(firma_vergi_metni(f))}</div>
  </div>
  <div class="belge">
    <h1>{_e(vm.belge_baslik)}</h1>
    <table>{bilgi}</table>
  </div>
</div>
<div class="serit"></div>
<div class="kutu">
  <h3>TALEP BİLGİLERİ</h3>
  {talep_bilgi}
</div>
<table class="urunler">
  <colgroup>{colgroup}</colgroup>
  <thead><tr>{thead}</tr></thead>
  <tbody>
    {''.join(satir_html)}
  </tbody>
</table>
<div class="toplam">
  <div><span class="etiket">Toplam Miktar: {_e(vm.toplam_miktar_goster)}</span>
    <div class="muted">Kalem: {len(vm.satirlar)}</div></div>
  {toplam_tutar}
</div>
{tahmini_not}
<div class="son">
  {notlar}
  {ek_html}
  <div class="imzalar">{_imza_kutusu("TALEP EDEN", vm.isteyen)}{_imza_kutusu("KONTROL EDEN")}{_imza_kutusu("ONAYLAYAN", vm.onaylayan, onay)}</div>
  <div class="alt">Bu belge şirket içi satın alma talebidir; sipariş yerine geçmez.{f' Oluşturulma: {_e(vm.olusturma)}' if vm.olusturma else ''}</div>
</div>
</body>
</html>"""
