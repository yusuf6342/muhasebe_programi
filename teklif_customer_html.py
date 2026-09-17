"""Müşteri teklif A4 HTML şablonu — CustomerQuoteViewModel (maliyet/kâr yok)."""

from __future__ import annotations

import html
import re

from database.teklif_customer_view import (
    CustomerQuoteViewModel,
    FIRMA_ALT_UNVAN,
    assert_customer_model_safe,
    assert_customer_output_safe,
    para_birimli,
)


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _css_str(v) -> str:
    """@page content için güvenli düz metin."""
    return re.sub(r'["\'\\]', "", "" if v is None else str(v))


def _firma_iletisim_satirlari(f: dict) -> list[str]:
    """Yalnızca dolu firma iletişim satırları."""
    satırlar: list[str] = []
    if f.get("telefon"):
        satırlar.append(f"Tel: {_e(f['telefon'])}")
    if f.get("adres"):
        satırlar.append(_e(f["adres"]))
    if f.get("email"):
        satırlar.append(f"E-posta: {_e(f['email'])}")
    if f.get("web"):
        satırlar.append(f"Web: {_e(f['web'])}")
    if f.get("vergi_dairesi"):
        satırlar.append(f"VD: {_e(f['vergi_dairesi'])}")
    if f.get("vergi_no"):
        satırlar.append(f"VN: {_e(f['vergi_no'])}")
    return satırlar


def _musteri_alan_html(m: dict) -> str:
    """Müşteri kutusu — boş alanları atla."""
    alanlar = [
        ("Unvan", m.get("unvan")),
        ("Yetkili", m.get("yetkili")),
        ("Vergi Dairesi", m.get("vergi_dairesi")),
        ("Vergi / T.C. No", m.get("vergi_no")),
        ("Telefon", m.get("telefon")),
        ("E-posta", m.get("email")),
        ("Fatura Adresi", m.get("fatura_adresi") or m.get("adres")),
        ("Teslimat Adresi", m.get("teslimat_adresi")),
    ]
    satirlar = []
    for etiket, deger in alanlar:
        if not deger or not str(deger).strip() or str(deger).strip() == "—":
            continue
        bold = " class='alan-deger-kalin'" if etiket == "Unvan" else ""
        satirlar.append(
            f"<div class='alan-satir'><span class='alan-etiket'>{_e(etiket)}</span>"
            f"<span{bold}>{_e(deger)}</span></div>"
        )
    return "".join(satirlar)


def _toplam_html(vm: CustomerQuoteViewModel) -> str:
    """Toplam satırları — sifir_kalemleri_gizle ise sıfırları gizle."""
    pb = vm.para_birimi_etiket or vm.para_birimi
    gizle = vm.sifir_kalemleri_gizle
    satirlar: list[tuple[str, str, bool]] = [
        ("Ara Toplam", para_birimli(vm.ara_goster, pb), False),
    ]
    if not gizle or (vm.iskonto_toplam and vm.iskonto_toplam > 0):
        satirlar.append(("Satır İskontoları", para_birimli(vm.iskonto_goster, pb), False))
    if not gizle or (vm.genel_iskonto and vm.genel_iskonto > 0):
        satirlar.append(("Genel İskonto", para_birimli(vm.genel_iskonto_goster, pb), False))
        satirlar.append(
            ("İskonto Sonrası", para_birimli(vm.iskonto_sonrasi_goster, pb), False)
        )
    satirlar.append(("KDV Toplamı", para_birimli(vm.kdv_goster, pb), False))
    if not gizle or (vm.nakliye and vm.nakliye > 0):
        satirlar.append(("Nakliye / Hizmet", para_birimli(vm.nakliye_goster, pb), False))
    if not gizle or (vm.yuvarlama and vm.yuvarlama != 0):
        satirlar.append(("Yuvarlama", para_birimli(vm.yuvarlama_goster, pb), False))
    satirlar.append(("GENEL TOPLAM", para_birimli(vm.genel_goster, pb), True))

    rows = []
    for etiket, deger, genel in satirlar:
        cls = " class='genel'" if genel else ""
        rows.append(
            f"<tr{cls}><td>{_e(etiket)}</td><td class='r'>{_e(deger)}</td></tr>"
        )
    return "<table class='toplam'>" + "".join(rows) + "</table>"


def render_customer_quote_html(vm: CustomerQuoteViewModel) -> str:
    """customer_quote_template — A4 kurumsal müşteri teklifi (maliyet/kâr yok)."""
    assert_customer_model_safe(vm)

    f = vm.firma or {}
    m = vm.musteri or {}
    pb = vm.para_birimi_etiket or vm.para_birimi

    logo = ""
    if vm.logo_data_uri:
        logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>'

    unvan = (f.get("unvan") or "RAY MOBİLYA AKSESUARLARI").upper()
    slogan = vm.firma_slogan or ""
    iletisim = _firma_iletisim_satirlari(f)
    iletisim_html = "".join(f"<div>{s}</div>" for s in iletisim)

    meta_alanlar = [
        ("Teklif No", vm.teklif_no),
        ("Teklif Tarihi", vm.teklif_tarihi),
        ("Geçerlilik", vm.gecerlilik_tarihi),
        ("Para Birimi", pb),
        ("Hazırlayan", vm.hazirlayan),
        ("Müşteri Temsilcisi", vm.satis_temsilcisi),
        ("Revizyon", vm.revizyon_goster),
        ("Durum", vm.durum),
    ]
    meta_rows = "".join(
        f"<tr><td class='meta-k'>{_e(k)}</td><td class='meta-v'>{_e(v)}</td></tr>"
        for k, v in meta_alanlar
        if v and str(v).strip()
    )
    meta_box = (
        f"<div class='meta-kutu'><table class='meta'>{meta_rows}</table></div>"
        if meta_rows
        else ""
    )

    musteri_html = _musteri_alan_html(m)
    musteri_box = (
        f"<div class='musteri-kutu'><h3>Sayın / Müşteri Bilgileri</h3>{musteri_html}</div>"
        if musteri_html
        else ""
    )

    hitap = ""
    if vm.hitap_metni and str(vm.hitap_metni).strip():
        hitap = f"<div class='hitap'>{_e(vm.hitap_metni)}</div>"

    satir_html = []
    for s in vm.satirlar:
        acik = _e(s.urun_adi or "")
        if s.aciklama:
            acik += f"<div class='muted'>{_e(s.aciklama)}</div>"
        satir_html.append(
            "<tr>"
            f"<td class='c'>{s.sira}</td>"
            f"<td>{_e(s.urun_kodu)}</td>"
            f"<td class='aciklama'>{acik}</td>"
            f"<td class='c'>{_e(s.miktar_goster)}</td>"
            f"<td class='c'>{_e(s.birim)}</td>"
            f"<td class='r'>{_e(para_birimli(s.birim_fiyat_goster, pb))}</td>"
            f"<td class='c'>{_e(s.iskonto_goster)}</td>"
            f"<td class='c'>{_e(s.kdv_oran_goster)}</td>"
            f"<td class='r'>{_e(para_birimli(s.kdv_hariç_goster, pb))}</td>"
            "</tr>"
        )

    sartlar_html = ""
    if vm.sart_satirlari or vm.sart_maddeleri:
        parcalar = ["<div class='bolum'><h3>Teklif Şartları</h3>"]
        for k, v in vm.sart_satirlari or []:
            parcalar.append(
                f"<div class='sart-satir'><strong>{_e(k)}:</strong> {_e(v)}</div>"
            )
        if vm.sart_maddeleri:
            parcalar.append("<ul class='sart-liste'>")
            for madde in vm.sart_maddeleri:
                if madde and str(madde).strip():
                    parcalar.append(f"<li>{_e(madde)}</li>")
            parcalar.append("</ul>")
        parcalar.append("</div>")
        sartlar_html = "".join(parcalar)

    banka = ""
    if vm.banka_satirlari:
        banka = "<div class='bolum'><h3>Banka Bilgileri</h3><ul>" + "".join(
            f"<li>{_e(b.get('banka', ''))} — {_e(b.get('iban', ''))}</li>"
            for b in vm.banka_satirlari
        ) + "</ul></div>"

    onay = f"<div class='onay-beyan'>{_e(vm.onay_beyani)}</div>" if vm.onay_beyani else ""

    alt_parcalar = [
        FIRMA_ALT_UNVAN,
        f.get("telefon"),
        f.get("adres"),
        f.get("web") or f.get("email"),
        f"Oluşturulma: {vm.olusturma_tarih_saat}" if vm.olusturma_tarih_saat else "",
    ]
    alt = " · ".join(_e(x) for x in alt_parcalar if x)

    html_out = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} {_e(vm.teklif_no)}</title>
<style>
@page {{
  size: A4 portrait;
  margin: 12mm 12mm 18mm 12mm;
  @bottom-left {{
    content: "{_css_str(FIRMA_ALT_UNVAN)} · {_css_str(vm.teklif_no)}";
    font-size: 7.5pt;
    color: #666;
  }}
  @bottom-right {{
    content: "Sayfa " counter(page) " / " counter(pages);
    font-size: 7.5pt;
    color: #666;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: Calibri, 'Segoe UI', Arial, sans-serif;
  font-size: 9.5pt;
  color: #333;
  margin: 0;
  padding: 0;
}}
.wrap {{ padding: 0 2px; }}
.ust {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}}
.ust-sol {{ flex: 1; min-width: 0; }}
.ust-sag {{
  text-align: right;
  font-size: 8pt;
  color: #555;
  line-height: 1.45;
  max-width: 42%;
}}
.logo {{ max-height: 56px; max-width: 160px; display: block; margin-bottom: 4px; }}
.firma-unvan {{
  font-size: 13pt;
  font-weight: 700;
  color: #0b1f3a;
  letter-spacing: 0.3px;
  margin: 0;
}}
.firma-slogan {{ font-size: 8pt; color: #666; margin: 2px 0 0; }}
.ayirici {{
  border: 0;
  border-top: 2.5px solid #0b1f3a;
  margin: 8px 0 2px;
}}
.ayirici-sari {{
  border: 0;
  border-top: 2px solid #e8b923;
  margin: 0 0 10px;
}}
.baslik {{
  text-align: center;
  color: #0b1f3a;
  font-size: 16pt;
  font-weight: 700;
  margin: 4px 0 12px;
  letter-spacing: 1px;
}}
.meta-kutu {{
  background: #eef1f5;
  border: 1px solid #d5dae3;
  padding: 6px 10px;
  margin-bottom: 10px;
}}
.meta {{ width: 100%; border-collapse: collapse; }}
.meta td {{ padding: 2px 8px 2px 0; vertical-align: top; }}
.meta-k {{ width: 28%; color: #0b1f3a; font-weight: 700; font-size: 8pt; }}
.meta-v {{ font-weight: 700; font-size: 9pt; color: #333; }}
.musteri-kutu {{
  border: 1px solid #d5dae3;
  padding: 8px 10px;
  margin-bottom: 10px;
}}
.musteri-kutu h3 {{
  margin: 0 0 6px;
  color: #0b1f3a;
  font-size: 10pt;
}}
.alan-satir {{ margin: 2px 0; font-size: 9pt; }}
.alan-etiket {{
  display: inline-block;
  min-width: 120px;
  color: #666;
  font-size: 8pt;
}}
.alan-deger-kalin {{ font-weight: 700; }}
.hitap {{
  font-style: italic;
  color: #444;
  background: #faf8f2;
  border-left: 3px solid #e8b923;
  padding: 8px 12px;
  margin: 0 0 12px;
  font-size: 9pt;
  line-height: 1.4;
}}
table.urun {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 4px;
  table-layout: fixed;
}}
table.urun thead {{ display: table-header-group; }}
table.urun th {{
  background: #0b1f3a;
  color: #fff;
  font-size: 7.5pt;
  padding: 5px 3px;
  text-align: center;
  font-weight: 700;
}}
table.urun td {{
  border-bottom: 1px solid #e5e7eb;
  padding: 4px 3px;
  font-size: 8pt;
  vertical-align: top;
  word-wrap: break-word;
}}
table.urun tr {{ page-break-inside: avoid; }}
table.urun td.aciklama {{ width: 32%; text-align: left; }}
.r {{ text-align: right; }}
.c {{ text-align: center; }}
.muted {{ color: #6b7280; font-size: 7.5pt; margin-top: 1px; }}
.toplam-wrap {{ margin-top: 10px; display: flex; justify-content: flex-end; }}
table.toplam {{
  width: 280px;
  border-collapse: collapse;
}}
table.toplam td {{
  padding: 3px 6px;
  font-size: 8.5pt;
  color: #555;
}}
table.toplam td.r {{ font-weight: 700; color: #333; }}
table.toplam tr.genel td {{
  background: #0b1f3a;
  color: #fff;
  font-weight: 700;
  font-size: 10pt;
  padding: 6px;
}}
table.toplam tr.genel td.r {{ color: #e8b923; }}
.kdv-not {{
  margin-top: 6px;
  font-size: 8pt;
  color: #666;
  text-align: right;
}}
.bolum {{ margin-top: 14px; font-size: 8.5pt; }}
.bolum h3 {{
  margin: 0 0 6px;
  color: #0b1f3a;
  font-size: 10pt;
}}
.sart-satir {{ margin: 2px 0; }}
.sart-liste {{ margin: 4px 0 0 18px; padding: 0; }}
.sart-liste li {{ margin: 2px 0; }}
.imza {{
  display: flex;
  justify-content: space-between;
  gap: 24px;
  margin-top: 28px;
  page-break-inside: avoid;
}}
.imza .alan {{
  width: 46%;
  border-top: 1px solid #9ca3af;
  padding-top: 8px;
}}
.imza .alan h4 {{
  margin: 0 0 6px;
  color: #0b1f3a;
  font-size: 9pt;
}}
.imza .alan div {{ font-size: 8pt; color: #666; margin: 2px 0; }}
.onay-beyan {{
  margin-top: 8px;
  font-size: 7pt;
  color: #666;
  font-style: italic;
}}
.alt-bilgi {{
  margin-top: 16px;
  font-size: 7pt;
  color: #888;
  border-top: 1px solid #e5e7eb;
  padding-top: 6px;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="ust">
    <div class="ust-sol">
      {logo}
      <div class="firma-unvan">{_e(unvan)}</div>
      {f'<div class="firma-slogan">{_e(slogan)}</div>' if slogan else ''}
    </div>
    <div class="ust-sag">{iletisim_html}</div>
  </div>
  <hr class="ayirici"/>
  <hr class="ayirici-sari"/>
  <h1 class="baslik">{_e(vm.belge_baslik or 'FİYAT TEKLİFİ')}</h1>
  {meta_box}
  {musteri_box}
  {hitap}
  <table class="urun">
    <colgroup>
      <col style="width:5%"/><col style="width:11%"/><col style="width:32%"/>
      <col style="width:8%"/><col style="width:7%"/><col style="width:12%"/>
      <col style="width:7%"/><col style="width:7%"/><col style="width:11%"/>
    </colgroup>
    <thead>
      <tr>
        <th>Sıra</th><th>Ürün Kodu</th><th>Açıklama</th>
        <th>Miktar</th><th>Birim</th><th>Birim Fiyat</th>
        <th>İsk.%</th><th>KDV%</th><th>Toplam</th>
      </tr>
    </thead>
    <tbody>
{''.join(satir_html)}
    </tbody>
  </table>
  <div class="toplam-wrap">{_toplam_html(vm)}</div>
  <div class="kdv-not">{_e(vm.kdv_aciklama)}</div>
  {sartlar_html}
  {banka}
  <div class="imza">
    <div class="alan">
      <h4>Teklifi Hazırlayan</h4>
      {f'<div>{_e(vm.hazirlayan)}</div>' if vm.hazirlayan else ''}
      {f'<div>{_e(vm.hazirlayan_gorev)}</div>' if vm.hazirlayan_gorev else ''}
      <div>İmza / Kaşe</div>
    </div>
    <div class="alan">
      <h4>Müşteri Onayı</h4>
      {f'<div>{_e(m.get("unvan"))}</div>' if m.get("unvan") else ''}
      <div>Tarih: _______________</div>
      <div>İmza / Kaşe</div>
      {onay}
    </div>
  </div>
  {f'<div class="alt-bilgi">{alt}</div>' if alt else ''}
</div>
</body>
</html>"""
    assert_customer_output_safe(html_out)
    return html_out
