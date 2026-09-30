"""Müşteriye verilen SATIŞ SİPARİŞ FORMU görünümü — maliyet/kâr/iç bilgi yok.

PDF ve Word aynı görünüm modelini kullanır; tutarlar sipariş kartındaki
``satir_hesapla`` / ``belge_toplamlari`` ile birebir aynı yuvarlanır.
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
    assert_customer_model_safe,
    assert_customer_output_safe,
    birim_toplamlari,
    firma_vergi_metni,
    miktar_metni,
    musteri_vergi_metni,
    toplam_miktar_metni,
)


@dataclass
class SiparisFormSatiri:
    sira: int
    urun_kodu: str
    urun_adi: str
    aciklama: str = ""
    termin: str = ""
    miktar: Decimal = Decimal("0")
    birim: str = "Adet"
    miktar_goster: str = ""
    birim_fiyat_goster: str = ""
    iskonto_goster: str = ""
    kdv_oran_goster: str = ""
    tutar_goster: str = ""


@dataclass
class SiparisFormViewModel:
    belge_baslik: str = "SATIŞ SİPARİŞ FORMU"
    firma: dict[str, Any] = field(default_factory=dict)
    logo_data_uri: str | None = None
    siparis_no: str = ""
    siparis_tarihi: str = ""
    termin: str = ""
    musteri_ref: str = ""
    durum: str = ""
    para_birimi: str = "TRY"
    para_etiketi: str = "TL"
    kur_goster: str = ""
    musteri: dict[str, Any] = field(default_factory=dict)
    teslimat_adresi: str = ""
    satirlar: list[SiparisFormSatiri] = field(default_factory=list)
    satir_termini_var: bool = False
    ara_goster: str = ""
    iskonto_toplam_goster: str = ""
    matrah_goster: str = ""
    kdv_goster: str = ""
    genel_goster: str = ""
    toplam_miktar_goster: str = ""
    teslim_kosulu: str = ""
    odeme_kosulu: str = ""
    aciklama: str = ""
    olusturma: str = ""


def _iskonto_metni(*oranlar) -> str:
    dolu = [f"%{miktar_metni(o)}" for o in oranlar if _d(o) > 0]
    return " + ".join(dolu) or "—"


def build_siparis_form_from_record(siparis_id: int) -> SiparisFormViewModel:
    """Kayıtlı siparişten form modeli. Maliyet alanları modele alınmaz."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.satis_siparisi import SatisSiparisi
    from database.satis_siparisi_service import belge_toplamlari, satir_hesapla

    branding, logo = _firma_markasi()
    with get_session() as session:
        sp = session.scalar(
            select(SatisSiparisi)
            .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.cari))
            .where(SatisSiparisi.id == int(siparis_id))
        )
        if sp is None:
            raise ValueError("Sipariş bulunamadı; silinmiş olabilir.")
        pb = (getattr(sp, "para_birimi", None) or "TRY").upper()
        satirlar = sorted(sp.satirlar, key=lambda s: int(s.id or 0))
        lines: list[SiparisFormSatiri] = []
        for i, s in enumerate(satirlar, start=1):
            i1, i2, i3 = s.iskonto_orani or 0, getattr(s, "iskonto_orani_2", 0) or 0, getattr(s, "iskonto_orani_3", 0) or 0
            kdv = s.kdv_orani if s.kdv_orani is not None else 20
            h = satir_hesapla(s.miktar or 0, s.birim_satis_fiyati or 0, i1, i2, i3, kdv)
            lines.append(
                SiparisFormSatiri(
                    sira=i,
                    urun_kodu=str(s.urun_kodu or ""),
                    urun_adi=str(s.urun_adi or ""),
                    aciklama=str(s.aciklama or "").strip(),
                    termin=_tarih(getattr(s, "estimated_delivery_date", None)),
                    miktar=_d(s.miktar),
                    birim=str(s.birim or "Adet"),
                    miktar_goster=miktar_metni(s.miktar),
                    birim_fiyat_goster=_para(s.birim_satis_fiyati),
                    iskonto_goster=_iskonto_metni(i1, i2, i3),
                    kdv_oran_goster=f"%{miktar_metni(kdv)}",
                    tutar_goster=_para(h["net"]),
                )
            )
        t = belge_toplamlari(satirlar)
        cari = sp.cari
        musteri = {
            "kod": getattr(cari, "cari_kodu", None) or "",
            "unvan": getattr(cari, "unvan", None) or "",
            "vergi_dairesi": getattr(cari, "vergi_dairesi", None) or "",
            "vergi_no": getattr(cari, "vergi_numarasi", None) or getattr(cari, "tc_kimlik", None) or "",
            "adres": _birlestir(
                getattr(cari, "adres", None),
                _birlestir(getattr(cari, "ilce", None), getattr(cari, "il", None)),
                ayrac=" — ",
            ),
            "telefon": getattr(cari, "telefon", None) or "",
        }
        teslimat = _birlestir(
            getattr(sp, "teslimat_adresi", None),
            _birlestir(getattr(sp, "teslimat_ilce", None), getattr(sp, "teslimat_il", None)),
            ayrac=" — ",
        )
        kur = _d(getattr(sp, "kur", None) or 1)
        vm = SiparisFormViewModel(
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
            siparis_no=sp.siparis_no or "",
            siparis_tarihi=_tarih(sp.siparis_tarihi),
            termin=_tarih(sp.termin_tarihi),
            musteri_ref=(getattr(sp, "musteri_siparis_no", None) or "").strip(),
            durum=sp.durum or "",
            para_birimi=pb,
            para_etiketi="TL" if pb == "TRY" else pb,
            kur_goster="" if pb == "TRY" else f"1 {pb} = {miktar_metni(kur)} TL",
            musteri=musteri,
            teslimat_adresi=teslimat,
            satirlar=lines,
            satir_termini_var=any(line.termin for line in lines),
            ara_goster=_para(t["ara_toplam"]),
            iskonto_toplam_goster=_para(t["iskonto"]),
            matrah_goster=_para(t["net"]),
            kdv_goster=_para(t["kdv"]),
            genel_goster=_para(t["genel_toplam"]),
            toplam_miktar_goster=toplam_miktar_metni(lines),
            teslim_kosulu=(getattr(sp, "teslim_kosulu", None) or "").strip(),
            odeme_kosulu=(getattr(sp, "odeme_kosulu", None) or "").strip(),
            aciklama=(sp.aciklama or "").strip(),
            olusturma=datetime.now().strftime("%d.%m.%Y %H:%M"),
        )
    assert_customer_model_safe(vm)
    return vm


def assert_siparis_form_safe(vm: SiparisFormViewModel, metin: str = "") -> None:
    assert_customer_model_safe(vm)
    if metin:
        assert_customer_output_safe(metin)


def belge_bilgi_satirlari(vm: SiparisFormViewModel) -> list[tuple[str, str]]:
    satirlar = [
        ("Sipariş No", vm.siparis_no),
        ("Sipariş Tarihi", vm.siparis_tarihi),
        ("Termin", vm.termin),
        ("Müşteri Ref.", vm.musteri_ref),
        ("Para Birimi", vm.para_etiketi if not vm.kur_goster else f"{vm.para_etiketi} ({vm.kur_goster})"),
    ]
    return [(k, v) for k, v in satirlar if v]


def teslimat_satirlari(vm: SiparisFormViewModel) -> list[tuple[str, str]]:
    satirlar = [
        ("Teslimat Adresi", vm.teslimat_adresi or (vm.musteri or {}).get("adres") or ""),
        ("Genel Termin", vm.termin),
        ("Teslim Koşulu", vm.teslim_kosulu),
        ("Ödeme Koşulu", vm.odeme_kosulu),
    ]
    return [(k, v) for k, v in satirlar if v]


def tutar_satirlari(vm: SiparisFormViewModel) -> list[tuple[str, str, bool]]:
    pb = vm.para_etiketi
    satirlar = [("Ara Toplam", f"{vm.ara_goster} {pb}", False)]
    if _d(vm.iskonto_toplam_goster) > 0:
        satirlar.append(("İskonto", f"-{vm.iskonto_toplam_goster} {pb}", False))
        satirlar.append(("Matrah", f"{vm.matrah_goster} {pb}", False))
    satirlar.append(("KDV", f"{vm.kdv_goster} {pb}", False))
    satirlar.append(("Genel Toplam", f"{vm.genel_goster} {pb}", True))
    return satirlar


def kolonlar(vm: SiparisFormViewModel) -> list[tuple[str, str, float | None]]:
    """(başlık, hiza, genişlik mm; None = kalan). PDF ve Word ortak."""
    liste: list[tuple[str, str, float | None]] = [
        ("Sıra", "c", 10), ("Stok Kodu", "l", 22), ("Ürün Adı / Açıklama", "l", None),
    ]
    if vm.satir_termini_var:
        liste.append(("Termin", "c", 18))
    liste += [
        ("Miktar", "r", 15), ("Birim", "c", 13), ("Birim Fiyat", "r", 20), ("İsk.", "c", 15),
        ("KDV", "c", 11), ("Tutar", "r", 23),
    ]
    return liste


def satir_degerleri(vm: SiparisFormViewModel, s: SiparisFormSatiri) -> list[str]:
    degerler = [str(s.sira), s.urun_kodu, s.urun_adi]
    if vm.satir_termini_var:
        degerler.append(s.termin)
    degerler += [s.miktar_goster, s.birim, s.birim_fiyat_goster, s.iskonto_goster, s.kdv_oran_goster, s.tutar_goster]
    return degerler


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _cok_satir(metin: str) -> str:
    return "<br/>".join(_e(p) for p in str(metin or "").splitlines())


def render_siparis_form_html(vm: SiparisFormViewModel) -> str:
    """A4 dikey SATIŞ SİPARİŞ FORMU. Sayfa numarası PDF üretiminden sonra basılır."""
    assert_customer_model_safe(vm)
    f = vm.firma or {}
    m = vm.musteri or {}
    logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>' if vm.logo_data_uri else ""
    kol = kolonlar(vm)
    colgroup = "".join(f"<col style='width:{g}mm'/>" if g else "<col/>" for _b, _h, g in kol)
    thead = "".join(f"<th class='{h}'>{_e(b)}</th>" for b, h, _g in kol)
    ad_index = 2
    miktar_index = next(i for i, (b, _h, _g) in enumerate(kol) if b == "Miktar")
    satir_html = []
    for line in vm.satirlar:
        hucreler = []
        for i, (deger, (_b, hiza, _g)) in enumerate(zip(satir_degerleri(vm, line), kol)):
            icerik = _e(deger)
            if i == ad_index and line.aciklama:
                icerik += f"<div class='muted'>{_cok_satir(line.aciklama)}</div>"
            sinif = hiza + (" miktar" if i == miktar_index else "") + (" kod" if i == 1 else "")
            hucreler.append(f"<td class='{sinif}'>{icerik}</td>")
        satir_html.append("<tr>" + "".join(hucreler) + "</tr>")

    toplamlar = birim_toplamlari(vm.satirlar)
    rozet = "".join(f"<span class='rozet'>{_e(miktar_metni(mk))} {_e(b)}</span>" for b, mk in toplamlar)
    tutarlar = "".join(
        f"<tr class='{'genel' if genel else ''}'><td>{_e(k)}</td><td class='r'>{_e(v)}</td></tr>"
        for k, v, genel in tutar_satirlari(vm)
    )
    bilgi = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in belge_bilgi_satirlari(vm))
    teslimat = "".join(
        f"<div class='satir'><span>{_e(k)}</span><b>{_cok_satir(v)}</b></div>" for k, v in teslimat_satirlari(vm)
    )
    musteri_vergi = musteri_vergi_metni(m)
    firma_vergi = firma_vergi_metni(f)
    firma_iletisim = _birlestir(f"Tel: {f['telefon']}" if f.get("telefon") else "", f.get("email"), ayrac="  ·  ")
    notlar = (
        f"<div class='not'><strong>Açıklama</strong><p>{_cok_satir(vm.aciklama)}</p></div>" if vm.aciklama else ""
    )

    def _imza_kutusu(baslik: str) -> str:
        return (
            f"<div class='imza-kutu'><h4>{baslik}</h4>"
            "<div class='alan'><span>Adı Soyadı</span><i></i></div>"
            "<div class='alan'><span>Tarih</span><i></i></div>"
            "<div class='alan imza'><span>İmza</span><i></i></div></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} — {_e(vm.siparis_no)}</title>
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
.belge {{ width:88mm; flex:none; }}
.belge h1 {{ margin:0 0 2mm; background:#102A43; color:#FFFFFF; font-size:14pt; letter-spacing:.5px;
  padding:2.5mm 4mm; border-left:5px solid #F4C542; white-space:nowrap; }}
.belge table {{ width:100%; border-collapse:collapse; }}
.belge th {{ text-align:left; color:#627D98; font-weight:600; padding:1mm 2mm; width:27mm; white-space:nowrap; vertical-align:top; }}
.belge td {{ font-weight:700; color:#102A43; padding:1mm 2mm; overflow-wrap:anywhere; }}
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
table.urunler th {{ background:#102A43; color:#FFFFFF; padding:2mm 1.2mm; font-size:8pt; text-align:left;
  border-bottom:2px solid #F4C542; }}
table.urunler td {{ border-bottom:1px solid #D9E2EC; padding:1.6mm 1.2mm; vertical-align:top; font-size:8.5pt;
  overflow-wrap:anywhere; word-break:break-word; }}
table.urunler tbody tr:nth-child(even) td {{ background:#F8FAFC; }}
.c {{ text-align:center !important; }} .r {{ text-align:right !important; }}
td.miktar {{ font-weight:700; }}
.muted {{ color:#627D98; font-size:7.5pt; margin-top:.5mm; }}
.toplam {{ display:flex; justify-content:space-between; align-items:flex-start; gap:6mm; margin-top:3mm;
  break-inside:avoid; }}
.toplam-miktar .etiket {{ font-weight:700; color:#102A43; }}
.rozetler {{ margin-top:1mm; }}
.rozet {{ display:inline-block; background:#FFE89A; color:#081B2C; font-weight:700; padding:1mm 2.5mm;
  margin:0 1.5mm 1.5mm 0; border-left:3px solid #102A43; }}
.aciklama-kucuk {{ color:#627D98; font-size:8pt; }}
table.tutarlar {{ border-collapse:collapse; min-width:70mm; }}
table.tutarlar td {{ padding:1mm 2mm; }}
table.tutarlar tr.genel td {{ background:#102A43; color:#F4C542; font-weight:700; font-size:10.5pt; }}
.son {{ margin-top:3mm; }}
.not {{ border:1px solid #D9E2EC; border-left:3px solid #F4C542; padding:2mm 3mm; margin-bottom:3mm;
  break-inside:avoid; }}
.not p {{ margin:1mm 0 0; overflow-wrap:anywhere; }}
.imzalar {{ display:flex; gap:6mm; break-inside:avoid; page-break-inside:avoid; }}
.imza-kutu {{ flex:1; border:1.2px solid #102A43; }}
.imza-kutu h4 {{ margin:0; background:#102A43; color:#F4C542; padding:1.8mm 3mm; font-size:9.5pt; letter-spacing:1px; }}
.imza-kutu .alan {{ display:flex; align-items:flex-end; gap:2mm; padding:0 3mm; height:8mm; }}
.imza-kutu .alan.imza {{ height:15mm; }}
.imza-kutu .alan span {{ width:24mm; flex:none; color:#486581; padding-bottom:1mm; }}
.imza-kutu .alan i {{ flex:1; border-bottom:1px dotted #486581; margin-bottom:1.5mm; }}
.alt {{ margin-top:2mm; font-size:7.5pt; color:#94A3B8; }}
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
    {f'<div class="satir"><span>Telefon</span><b>{_e(m.get("telefon"))}</b></div>' if m.get("telefon") else ''}
  </div>
  <div class="kutu">
    <h3>TESLİMAT VE KOŞULLAR</h3>
    {teslimat}
  </div>
</div>
<table class="urunler">
  <colgroup>{colgroup}</colgroup>
  <thead><tr>{thead}</tr></thead>
  <tbody>
    {''.join(satir_html)}
  </tbody>
</table>
<div class="toplam">
  <div class="toplam-miktar"><span class="etiket">Toplam Miktar: {_e(vm.toplam_miktar_goster)}</span>
    <div class="rozetler">{rozet}</div>
    <div class="aciklama-kucuk">Kalem: {len(vm.satirlar)}{' · Farklı birimler ayrı toplanır' if len(toplamlar) > 1 else ''}</div>
  </div>
  <table class="tutarlar">{tutarlar}</table>
</div>
<div class="son">
  {notlar}
  <div class="imzalar">{_imza_kutusu("SİPARİŞİ HAZIRLAYAN")}{_imza_kutusu("MÜŞTERİ ONAYI")}</div>
  <div class="alt">Bu belge satış sipariş formudur; fatura veya irsaliye yerine geçmez.{f' Oluşturulma: {_e(vm.olusturma)}' if vm.olusturma else ''}</div>
</div>
</body>
</html>"""
