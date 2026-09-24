"""A4 HTML şablon renderer — mm birimli, çok sayfalı."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from invoice_print.view_model import InvoicePrintLine, InvoicePrintViewModel

LACIVERT = "#0B2A4A"
SARI = "#D4A017"
GRI = "#E5E7EB"
METIN = "#111827"


def _e(x: Any) -> str:
    if x is None or x == "":
        return ""
    return html.escape(str(x))


def _meta_satir(etiket: str, deger: str) -> str:
    if not (deger or "").strip() or deger.strip() in ("—", "-", "None", "null"):
        return ""
    return f"<div class='meta-row'><span>{_e(etiket)}</span><b>{_e(deger)}</b></div>"


def _tablo_baslik(vm: InvoicePrintViewModel) -> str:
    a = vm.ayarlar
    hucreler = ["<th class='c'>Sıra</th>"]
    if a.get("urun_kodu_goster", True):
        hucreler.append("<th>Kod</th>")
    hucreler.append("<th class='ad'>Ürün / Hizmet</th>")
    if a.get("aciklama_goster", True):
        hucreler.append("<th>Açıklama</th>")
    hucreler.extend(
        [
            "<th class='c'>Miktar</th>",
            "<th class='c'>Birim</th>",
            "<th class='r'>B.Fiyat</th>",
            "<th class='r'>Net B.F.</th>",
            "<th class='c'>İsk.</th>",
            "<th class='c'>KDV</th>",
            "<th class='r'>Net</th>",
            "<th class='r'>Toplam</th>",
        ]
    )
    return "<tr>" + "".join(hucreler) + "</tr>"


def _tablo_satir(vm: InvoicePrintViewModel, s: InvoicePrintLine) -> str:
    a = vm.ayarlar
    ad = _e(s.urun_adi)
    if s.lot:
        ad += f"<div class='kucuk'>Lot: {_e(s.lot)}</div>"
    if s.barkod:
        ad += f"<div class='kucuk'>Barkod: {_e(s.barkod)}</div>"
    h = [f"<td class='c'>{s.sira}</td>"]
    if a.get("urun_kodu_goster", True):
        h.append(f"<td>{_e(s.urun_kodu)}</td>")
    h.append(f"<td class='ad'>{ad}</td>")
    if a.get("aciklama_goster", True):
        h.append(f"<td class='acik'>{_e(s.aciklama)}</td>")
    isk_hucre = _e(s.iskonto_goster)
    if getattr(s, "iskonto_tutar_goster", None) and s.iskonto_tutar_goster not in ("", "—"):
        isk_hucre += f"<div class='kucuk'>{_e(s.iskonto_tutar_goster)}</div>"
    kdv_hucre = _e(s.kdv_goster)
    if getattr(s, "kdv_tutar_goster", None):
        kdv_hucre += f"<div class='kucuk'>{_e(s.kdv_tutar_goster)}</div>"
    h.extend(
        [
            f"<td class='c'>{_e(s.miktar_goster)}</td>",
            f"<td class='c'>{_e(s.birim)}</td>",
            f"<td class='r'>{_e(s.birim_fiyat_goster)}</td>",
            f"<td class='r'>{_e(getattr(s, 'net_birim_fiyat_goster', '') or '')}</td>",
            f"<td class='c'>{isk_hucre}</td>",
            f"<td class='c'>{kdv_hucre}</td>",
            f"<td class='r'>{_e(s.net_goster)}</td>",
            f"<td class='r'>{_e(s.satir_toplam_goster)}</td>",
        ]
    )
    return "<tr>" + "".join(h) + "</tr>"


def _firma_blok(vm: InvoicePrintViewModel, kucuk: bool = False) -> str:
    f = vm.firma or {}
    a = vm.ayarlar
    if not a.get("firma_bilgi_goster", True):
        return f"<div class='firma-ad'>{_e(f.get('unvan') or f.get('kisa_ad') or '')}</div>"
    logo = ""
    if a.get("logo_goster", True) and vm.logo_data_uri and not kucuk:
        logo = f"<img class='logo' src='{vm.logo_data_uri}' alt='Logo'/>"
    elif a.get("logo_goster", True) and vm.logo_data_uri and kucuk:
        logo = f"<img class='logo-kucuk' src='{vm.logo_data_uri}' alt='Logo'/>"
    unvan = _e(f.get("unvan") or "")
    if not logo and unvan:
        logo = f"<div class='firma-ad-buyuk'>{unvan}</div>"
    adres_parca = [
        p
        for p in (
            f.get("adres") or "",
            " ".join(x for x in (f.get("ilce") or "", f.get("il") or "") if x),
        )
        if p
    ]
    bilgiler = []
    if not kucuk:
        if f.get("kisa_ad"):
            bilgiler.append(_e(f["kisa_ad"]))
        if adres_parca:
            bilgiler.append(_e(" · ".join(adres_parca)))
        for et, key in (
            ("Tel", "telefon"),
            ("E-posta", "email"),
            ("Web", "web"),
            ("V.D.", "vergi_dairesi"),
            ("V.N.", "vergi_no"),
            ("MERSİS", "mersis"),
            ("Tic. Sicil", "ticaret_sicil"),
        ):
            if f.get(key):
                bilgiler.append(f"{et}: {_e(f[key])}")
    else:
        bilgiler.append(_e(f.get("kisa_ad") or f.get("unvan") or ""))
    return (
        f"<div class='firma {'kucuk' if kucuk else ''}'>"
        f"<div class='logo-wrap'>{logo}</div>"
        f"<div class='firma-info'>{'<br/>'.join(bilgiler)}</div>"
        f"</div>"
    )


def _musteri_blok(vm: InvoicePrintViewModel) -> str:
    m = vm.musteri or {}
    satirlar = []
    unvan = m.get("unvan") or ""
    kod = m.get("cari_kodu") or ""
    baslik = " ".join(x for x in (kod, unvan) if x)
    satirlar.append(f"<div class='m-unvan'>{_e(baslik)}</div>")
    for et, key in (
        ("Vergi Dairesi", "vergi_dairesi"),
        ("Vergi / T.C.", "vergi_no"),
        ("Adres", "adres"),
        ("İlçe / İl", None),
        ("Telefon", "telefon"),
        ("E-posta", "email"),
    ):
        if key is None:
            il = " / ".join(x for x in (m.get("ilce") or "", m.get("il") or "") if x)
            if il:
                satirlar.append(f"<div><span>{et}:</span> {_e(il)}</div>")
            continue
        if m.get(key):
            satirlar.append(f"<div><span>{et}:</span> {_e(m[key])}</div>")
    return "<div class='musteri'><div class='m-baslik'>Sayın</div>" + "".join(satirlar) + "</div>"


def _belge_meta(vm: InvoicePrintViewModel) -> str:
    parcalar = [
        _meta_satir("Fatura No", vm.fatura_no),
        _meta_satir("Tarih", vm.fatura_tarihi),
        _meta_satir("Saat", vm.islem_saati),
        _meta_satir("Vade", vm.vade_tarihi),
        _meta_satir("Vade Günü", vm.vade_gunu),
        _meta_satir("Sipariş", vm.siparis_no),
        _meta_satir("İrsaliye", vm.irsaliye_no),
        _meta_satir("Depo", vm.depo),
        _meta_satir("Para Birimi", vm.para_birimi if vm.para_birimi not in ("TRY", "TL") else ""),
        _meta_satir("Kur", vm.kur),
        _meta_satir("Kur Tarihi", vm.kur_tarihi),
        _meta_satir("Ödeme", vm.odeme_sekli),
        _meta_satir("Durum", vm.durum),
        _meta_satir("Satış Personeli", getattr(vm, "satis_personeli", "") or ""),
    ]
    return "<div class='belge-meta'>" + "".join(p for p in parcalar if p) + "</div>"


def _toplamlar(vm: InvoicePrintViewModel) -> str:
    a = vm.ayarlar
    satirlar = [
        f"<tr><td>Ara Toplam</td><td class='r'>{_e(vm.brut_goster)}</td></tr>",
        f"<tr><td>Toplam İskonto</td><td class='r'>{_e(vm.iskonto_goster)}</td></tr>",
        f"<tr><td>KDV Matrahı</td><td class='r'>{_e(vm.ara_goster)}</td></tr>",
    ]
    if a.get("kdv_dokum_goster", True):
        for k in vm.kdv_dokum:
            oran = f"%{float(k.oran):g}"
            satirlar.append(
                f"<tr><td>{oran} KDV Matrahı</td><td class='r'>{_e(k.matrah_goster)}</td></tr>"
            )
            satirlar.append(
                f"<tr><td>{oran} KDV Tutarı</td><td class='r'>{_e(k.kdv_goster)}</td></tr>"
            )
    satirlar.append(f"<tr><td>KDV Toplamı</td><td class='r'>{_e(vm.kdv_goster)}</td></tr>")
    fatura_brut = getattr(vm, "fatura_brut_goster", "") or ""
    if fatura_brut:
        satirlar.append(
            f"<tr><td>Brüt Toplam</td><td class='r'>{_e(fatura_brut)}</td></tr>"
        )
    # İndirim/Masraf tutarı (yüzde yok); sıfırsa satır yok
    if getattr(vm, "genel_islem_etiket", "") and getattr(vm, "genel_islem_goster", ""):
        satirlar.append(
            f"<tr><td>{_e(vm.genel_islem_etiket)}</td>"
            f"<td class='r'>{_e(vm.genel_islem_goster)}</td></tr>"
        )
    satirlar.append(
        f"<tr class='genel'><td>Genel Toplam</td><td class='r'>{_e(vm.genel_goster)}</td></tr>"
    )
    if a.get("tahsil_kalan_goster", True):
        satirlar.append(
            f"<tr><td>Tahsil Edilen</td><td class='r'>{_e(vm.tahsil_goster)}</td></tr>"
        )
        satirlar.append(
            f"<tr><td>Kalan Bakiye</td><td class='r'>{_e(vm.kalan_goster)}</td></tr>"
        )
    if vm.tl_goster:
        satirlar.append(
            f"<tr><td>TL Karşılığı</td><td class='r'>{_e(vm.tl_goster)}</td></tr>"
        )
    yazi = ""
    if a.get("yaziyla_toplam_goster", True) and vm.yaziyla_toplam:
        yazi = f"<div class='yaziyla'>{_e(vm.yaziyla_toplam)}</div>"
    return (
        "<div class='ozet'><div class='ozet-baslik'>Fatura Özeti</div>"
        f"<table>{''.join(satirlar)}</table>{yazi}</div>"
    )


def _not_banka_imza(vm: InvoicePrintViewModel) -> str:
    a = vm.ayarlar
    bloklar = []
    if vm.notlar:
        bloklar.append(
            f"<div class='notlar'><div class='alt-baslik'>Açıklama / Not</div>"
            f"<div>{_e(vm.notlar)}</div></div>"
        )
    if a.get("banka_goster", True) and vm.banka_satirlari:
        satir = "".join(
            f"<div>{_e(b.get('banka'))} {_e(b.get('sube'))} "
            f"IBAN: <b>{_e(b.get('iban'))}</b> {_e(b.get('pb'))}</div>"
            for b in vm.banka_satirlari
        )
        bloklar.append(
            f"<div class='banka'><div class='alt-baslik'>Ödeme Bilgileri</div>{satir}</div>"
        )
    if a.get("imza_alani_goster", True):
        # Hazırlayan = sistem kullanıcısı müşteri çıktısında yok
        ona = _e(vm.onaylayan or "—")
        duz = _e(vm.duzenleme_tarihi or "")
        kaynak = ""
        if vm.kaynak_siparis_olusturan or vm.siparis_no:
            kaynak = (
                f"<div style='margin-top:6px;font-size:8.5pt'>"
                f"Kaynak sipariş: {_e(vm.siparis_no or '—')}"
                f" &nbsp; Siparişi oluşturan: {_e(vm.kaynak_siparis_olusturan or '—')}"
                f"</div>"
            )
        bloklar.append(
            "<div class='imza'>"
            f"<div><div class='alt-baslik'>Kontrol Eden / Onaylayan</div>"
            f"<div>{ona}</div>"
            f"<div class='cizgi'>İmza</div></div>"
            "</div>"
            f"<div style='margin-top:4px;font-size:8.5pt'>Düzenleme tarihi: {duz or '—'}</div>"
            f"{kaynak}"
        )
    if vm.alt_bilgi:
        bloklar.append(f"<div class='dipnot'>{_e(vm.alt_bilgi)}</div>")
    return "".join(bloklar)


def _css(zoom_pct: int = 100) -> str:
    scale = max(50, min(200, int(zoom_pct))) / 100.0
    return f"""
@page {{ size: A4 portrait; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0;
  font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
  color: {METIN}; background: #9CA3AF;
  font-size: 9.5pt;
}}
.toolbar {{
  position: sticky; top: 0; z-index: 10;
  background: #111827; color: #fff; padding: 8px 12px;
  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
}}
.toolbar button {{
  background: #F5C518; border: 0; padding: 6px 12px; cursor: pointer;
  font-weight: 600; border-radius: 4px;
}}
.toolbar .ghost {{ background: #374151; color: #fff; }}
.sayfa {{
  width: 210mm; min-height: 297mm;
  margin: 12px auto; padding: 12mm;
  background: #fff; box-shadow: 0 4px 18px rgba(0,0,0,.25);
  position: relative;
  transform: scale({scale});
  transform-origin: top center;
}}
.filigran {{
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  pointer-events: none; z-index: 1;
  font-size: 28pt; font-weight: 800; color: rgba(185,28,28,.18);
  transform: rotate(-28deg); letter-spacing: 2px; text-align: center;
}}
.icerik {{ position: relative; z-index: 2; }}
.firma {{ display: flex; gap: 14px; align-items: flex-start; border-bottom: 2px solid {LACIVERT}; padding-bottom: 8px; }}
.firma.kucuk {{ border-bottom: 1px solid {GRI}; padding-bottom: 4px; font-size: 8.5pt; }}
.logo {{ max-height: 22mm; max-width: 55mm; object-fit: contain; }}
.logo-kucuk {{ max-height: 10mm; max-width: 28mm; object-fit: contain; }}
.firma-ad-buyuk {{ font-size: 14pt; font-weight: 800; color: {LACIVERT}; }}
.firma-info {{ font-size: 8.5pt; color: #374151; line-height: 1.35; flex: 1; }}
.baslik-satir {{
  display: flex; justify-content: space-between; gap: 12px;
  margin: 10px 0 8px; align-items: flex-start;
}}
h1 {{
  margin: 0; font-size: 16pt; color: {LACIVERT}; letter-spacing: .5px;
  border-left: 5px solid {SARI}; padding-left: 8px;
}}
.belge-meta {{ min-width: 58mm; font-size: 8.5pt; }}
.meta-row {{ display: flex; justify-content: space-between; gap: 8px; border-bottom: 1px solid {GRI}; padding: 2px 0; }}
.meta-row span {{ color: #6B7280; }}
.ust-2 {{ display: flex; gap: 16px; margin-bottom: 8px; }}
.musteri {{ flex: 1; border: 1px solid {GRI}; padding: 8px; border-radius: 2px; }}
.m-baslik {{ color: {LACIVERT}; font-weight: 700; font-size: 8pt; text-transform: uppercase; }}
.m-unvan {{ font-weight: 700; font-size: 11pt; margin: 2px 0 6px; }}
.musteri span {{ color: #6B7280; }}
table.urunler {{ width: 100%; border-collapse: collapse; margin-top: 6px; table-layout: fixed; }}
table.urunler th {{
  background: {LACIVERT}; color: #fff; font-weight: 600; font-size: 8pt;
  padding: 5px 4px; border: 1px solid {LACIVERT};
}}
table.urunler td {{
  border-bottom: 1px solid {GRI}; padding: 4px; vertical-align: top; font-size: 8.5pt;
  word-wrap: break-word; overflow-wrap: anywhere;
}}
table.urunler th.ad, table.urunler td.ad {{ width: 28%; }}
table.urunler .c {{ text-align: center; }}
table.urunler .r {{ text-align: right; white-space: nowrap; }}
.kucuk {{ font-size: 7.5pt; color: #6B7280; }}
.alt-grid {{ display: flex; gap: 12px; margin-top: 10px; align-items: flex-start; }}
.ozet {{ margin-left: auto; min-width: 72mm; border: 1px solid {GRI}; padding: 8px; }}
.ozet-baslik {{ font-weight: 700; color: {LACIVERT}; margin-bottom: 4px; }}
.ozet table {{ width: 100%; border-collapse: collapse; }}
.ozet td {{ padding: 3px 0; font-size: 8.5pt; }}
.ozet .genel td {{ font-size: 11pt; font-weight: 800; color: {LACIVERT}; border-top: 2px solid {SARI}; padding-top: 6px; }}
.yaziyla {{ margin-top: 6px; font-size: 8pt; font-style: italic; color: #374151; }}
.notlar, .banka {{ flex: 1; font-size: 8.5pt; }}
.alt-baslik {{ font-weight: 700; color: {LACIVERT}; margin-bottom: 4px; }}
.imza {{ display: flex; gap: 24px; margin-top: 18px; }}
.imza > div {{ flex: 1; }}
.cizgi {{ border-top: 1px solid #9CA3AF; margin-top: 28px; padding-top: 4px; color: #6B7280; font-size: 8pt; }}
.footer {{
  margin-top: 10px; padding-top: 6px; border-top: 1px solid {GRI};
  display: flex; justify-content: space-between; font-size: 7.5pt; color: #6B7280;
}}
.dipnot {{ margin-top: 8px; font-size: 8pt; color: #4B5563; }}
.devreden {{ text-align: right; font-size: 8pt; color: #4B5563; margin-top: 4px; }}
@media print {{
  body {{ background: #fff; }}
  .toolbar {{ display: none !important; }}
  .sayfa {{
    margin: 0; box-shadow: none; transform: none !important;
    page-break-after: always; width: auto; min-height: auto; padding: 0;
  }}
  .sayfa:last-child {{ page-break-after: auto; }}
}}
"""


def render_invoice_html(
    vm: InvoicePrintViewModel,
    *,
    zoom_pct: int = 100,
    toolbar: bool = True,
    aktif_sayfa: int | None = None,
) -> str:
    sayfalar = vm.sayfalar or [vm.satirlar]
    toplam_sayfa = max(1, len(sayfalar))
    olusturma = datetime.now().strftime("%d.%m.%Y %H:%M")
    sayfa_html: list[str] = []
    for i, satirlar in enumerate(sayfalar):
        sn = i + 1
        if aktif_sayfa is not None and sn != aktif_sayfa:
            continue
        ilk = sn == 1
        son = sn == toplam_sayfa
        filigran = (
            f"<div class='filigran'>{_e(vm.filigran)}</div>" if vm.filigran else ""
        )
        ust = _firma_blok(vm, kucuk=not ilk)
        if ilk:
            orta = (
                f"<div class='baslik-satir'><h1>{_e(vm.belge_turu)}</h1>{_belge_meta(vm)}</div>"
                f"<div class='ust-2'>{_musteri_blok(vm)}</div>"
            )
        else:
            orta = (
                f"<div class='baslik-satir'><h1 style='font-size:12pt'>{_e(vm.belge_turu)} "
                f"(devam)</h1>"
                f"<div class='belge-meta'>"
                f"{_meta_satir('Fatura No', vm.fatura_no)}"
                f"{_meta_satir('Müşteri', (vm.musteri or {}).get('unvan') or '')}"
                f"</div></div>"
            )
        tablo = (
            f"<table class='urunler'>{_tablo_baslik(vm)}"
            + "".join(_tablo_satir(vm, s) for s in satirlar)
            + "</table>"
        )
        alt = ""
        if not son and vm.ayarlar.get("ara_toplam_devri_goster", True):
            alt += "<div class='devreden'>Ara Toplam Devreden →</div>"
        if son:
            alt += f"<div class='alt-grid'>{_not_banka_imza(vm)}{_toplamlar(vm)}</div>"
        firma_kisa = (vm.firma or {}).get("kisa_ad") or (vm.firma or {}).get("unvan") or ""
        footer = (
            f"<div class='footer'><span>{_e(firma_kisa)} · {_e(vm.fatura_no)}</span>"
            f"<span>Sayfa {sn} / {toplam_sayfa}</span>"
            f"<span>{_e(olusturma)}</span></div>"
        )
        sayfa_html.append(
            f"<section class='sayfa' data-page='{sn}'>{filigran}"
            f"<div class='icerik'>{ust}{orta}{tablo}{alt}{footer}</div></section>"
        )

    tb = ""
    if toolbar:
        tb = """
<div class="toolbar">
  <button type="button" onclick="window.print()">Yazdır</button>
  <button type="button" class="ghost" onclick="window.close()">Kapat</button>
  <span style="margin-left:auto;opacity:.8;font-size:12px">A4 Önizleme — Ctrl+P ile yazdırın</span>
</div>"""
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>{_e(vm.belge_turu)} {_e(vm.fatura_no)}</title>
<style>{_css(zoom_pct)}</style>
</head><body>
{tb}
{''.join(sayfa_html)}
</body></html>"""
