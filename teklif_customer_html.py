"""Müşteri teklif A4 HTML şablonu — Genel Bilgiler · Stok Kalemleri · Özel Şartlar.

Alış / maliyet / kâr / ayrı masraf satırı YOK (masraf fiyata gömülü).
"""

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
    return re.sub(r'["\'\\]', "", "" if v is None else str(v))


def _firma_iletisim_satirlari(f: dict) -> list[str]:
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


def _alan_satir(etiket: str, deger, *, kalin: bool = False) -> str:
    if deger is None or not str(deger).strip() or str(deger).strip() == "—":
        return ""
    cls = " class='deger-kalin'" if kalin else ""
    return (
        f"<div class='alan'><span class='etiket'>{_e(etiket)}</span>"
        f"<span{cls}>{_e(deger)}</span></div>"
    )


def _toplam_html(vm: CustomerQuoteViewModel) -> str:
    """Ticari toplamlar — masraf/alış satırı yok; nihai tutar Net Toplam."""
    pb = vm.para_birimi_etiket or vm.para_birimi
    gizle = vm.sifir_kalemleri_gizle
    satirlar: list[tuple[str, str, bool]] = [
        ("Ara Toplam (KDV Hariç)", para_birimli(vm.ara_goster, pb), False),
    ]
    if not gizle or (vm.iskonto_toplam and vm.iskonto_toplam > 0):
        satirlar.append(("Satır İskontoları", para_birimli(vm.iskonto_goster, pb), False))
    if not gizle or (vm.genel_iskonto and vm.genel_iskonto > 0):
        satirlar.append(("İndirim", para_birimli(vm.genel_iskonto_goster, pb), False))
    satirlar.append(("KDV Toplamı", para_birimli(vm.kdv_goster, pb), False))
    # Nihai tutar formdaki Net Toplam ile aynı (brüt değil)
    satirlar.append(("NET TOPLAM", para_birimli(vm.genel_goster, pb), True))

    rows = []
    for etiket, deger, genel in satirlar:
        cls = " class='genel'" if genel else ""
        rows.append(
            f"<tr{cls}><td>{_e(etiket)}</td><td class='r'>{_e(deger)}</td></tr>"
        )
    return "<table class='toplam'>" + "".join(rows) + "</table>"


def render_customer_quote_html(
    vm: CustomerQuoteViewModel,
    *,
    preview: bool = False,
    zoom_pct: int = 100,
) -> str:
    """A4 kurumsal müşteri teklifi — maliyet/kâr/ayrı masraf yok.

    preview=True: ekranda gri zemin + A4 kağıt + yazdır araç çubuğu.
    """
    assert_customer_model_safe(vm)
    scale = max(50, min(200, int(zoom_pct))) / 100.0

    f = vm.firma or {}
    m = vm.musteri or {}
    pb = vm.para_birimi_etiket or vm.para_birimi

    logo = ""
    if vm.logo_data_uri:
        logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>'

    unvan = (f.get("unvan") or "RAY MOBİLYA AKSESUARLARI").upper()
    slogan = vm.firma_slogan or ""
    iletisim_html = "".join(f"<div>{s}</div>" for s in _firma_iletisim_satirlari(f))

    # ——— 1) Genel Bilgiler ———
    genel_sol = "".join(
        [
            _alan_satir("Teklif No", vm.teklif_no, kalin=True),
            _alan_satir("Teklif Tarihi", vm.teklif_tarihi),
            _alan_satir("Geçerlilik", vm.gecerlilik_tarihi),
            _alan_satir("Geçerlilik Süresi", vm.gecerlilik_suresi),
            _alan_satir("Para Birimi", pb),
            _alan_satir("Revizyon", vm.revizyon_goster),
            _alan_satir("Referans No", vm.referans_no),
            _alan_satir("Konu", vm.konu),
            _alan_satir("Proje", vm.proje),
        ]
    )
    genel_orta = "".join(
        [
            _alan_satir("Müşteri", m.get("unvan"), kalin=True),
            _alan_satir("Yetkili", m.get("yetkili")),
            _alan_satir("Telefon", m.get("telefon")),
            _alan_satir("E-posta", m.get("email")),
            _alan_satir("Vergi Dairesi", m.get("vergi_dairesi")),
            _alan_satir("Vergi / T.C. No", m.get("vergi_no")),
        ]
    )
    genel_sag = "".join(
        [
            _alan_satir("Ödeme Şekli", vm.odeme_sekli, kalin=True),
            _alan_satir(
                "Vade",
                vm.vade_bilgisi
                if vm.vade_bilgisi and vm.vade_bilgisi != vm.odeme_sekli
                else "",
            ),
            _alan_satir("Teslim Süresi", vm.termin_suresi),
            _alan_satir("Tahmini Teslim", vm.tahmini_teslim_tarihi),
            _alan_satir("Teslimat Şekli", vm.teslimat_sekli),
            _alan_satir("Nakliye", vm.nakliye_durumu),
            _alan_satir("Hazırlayan", vm.hazirlayan),
            _alan_satir("Satış Temsilcisi", vm.satis_temsilcisi),
        ]
    )
    adres_blok = ""
    fatura_adres = m.get("fatura_adresi") or m.get("adres")
    if fatura_adres or m.get("teslimat_adresi"):
        adres_blok = (
            "<div class='adres-satir'>"
            + _alan_satir("Fatura Adresi", fatura_adres)
            + _alan_satir("Teslimat Adresi", m.get("teslimat_adresi"))
            + "</div>"
        )

    hitap = ""
    if vm.hitap_metni and str(vm.hitap_metni).strip():
        hitap = f"<div class='hitap'>{_e(vm.hitap_metni)}</div>"

    # ——— 2) Stok / ürün kalemleri ———
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
    if not satir_html:
        satir_html.append(
            "<tr><td colspan='9' class='c muted'>Ürün kalemi bulunmamaktadır.</td></tr>"
        )

    # ——— 3) Özel şartlar ———
    # Alış / maliyet / kâr / masraf dağıtımı gizlenir; "masraf fiyata dahil" açıklaması kalır.
    _yasak_sart = (
        "alış fiyat",
        "alis fiyat",
        "birim maliyet",
        "maliyet",
        "kâr oran",
        "kar oran",
        "marj",
        "masraf dağıt",
        "masraf dagit",
        "tedarikçi",
        "tedarikci",
    )
    sart_parcalar: list[str] = []
    for k, v in vm.sart_satirlari or []:
        kt = f"{k} {v}".casefold()
        if any(x in kt for x in _yasak_sart):
            continue
        if v and str(v).strip():
            sart_parcalar.append(
                f"<div class='sart-satir'><strong>{_e(k)}:</strong> {_e(v)}</div>"
            )
    madde_html = ""
    if vm.sart_maddeleri:
        maddeler = [
            f"<li>{_e(madde)}</li>"
            for madde in vm.sart_maddeleri
            if madde and str(madde).strip()
        ]
        if maddeler:
            madde_html = "<ul class='sart-liste'>" + "".join(maddeler) + "</ul>"

    banka = ""
    if vm.banka_satirlari:
        banka = (
            "<div class='banka'><h4>Banka Bilgileri</h4><ul>"
            + "".join(
                f"<li>{_e(b.get('banka', ''))} — {_e(b.get('iban', ''))}</li>"
                for b in vm.banka_satirlari
            )
            + "</ul></div>"
        )

    onay = f"<div class='onay-beyan'>{_e(vm.onay_beyani)}</div>" if vm.onay_beyani else ""
    alt_parcalar = [
        FIRMA_ALT_UNVAN,
        f.get("telefon"),
        f.get("adres"),
        f.get("web") or f.get("email"),
        f"Oluşturulma: {vm.olusturma_tarih_saat}" if vm.olusturma_tarih_saat else "",
    ]
    alt = " · ".join(_e(x) for x in alt_parcalar if x)

    toolbar_html = ""
    preview_css = ""
    body_cls = ""
    sayfa_ac = ""
    sayfa_kapa = ""
    if preview:
        body_cls = ' class="onizleme"'
        sayfa_ac = '<div class="a4-sayfa">'
        sayfa_kapa = "</div>"
        toolbar_html = """
<div class="toolbar no-print">
  <span class="toolbar-baslik">Teklif Yazdırma Ön İzlemesi — A4</span>
  <button type="button" onclick="window.print()">Yazdır</button>
  <button type="button" class="ghost" onclick="window.close()">Kapat</button>
</div>
"""
        preview_css = f"""
body.onizleme {{
  background: #6B7280;
  padding: 0 0 24px;
}}
.toolbar {{
  position: sticky; top: 0; z-index: 20;
  background: #0B1F3A; color: #fff;
  padding: 8px 14px;
  display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
}}
.toolbar-baslik {{
  font-weight: 700; color: #E8B923; margin-right: 8px; font-size: 10pt;
}}
.toolbar button {{
  background: #E8B923; color: #0B1F3A; border: 0;
  padding: 6px 14px; cursor: pointer; font-weight: 700;
  border-radius: 4px; font-size: 9.5pt;
}}
.toolbar button.ghost {{ background: #374151; color: #fff; }}
.a4-sayfa {{
  width: 210mm;
  min-height: 297mm;
  margin: 14px auto;
  padding: 10mm 12mm 16mm 12mm;
  background: #fff;
  box-shadow: 0 6px 28px rgba(0,0,0,.35);
  transform: scale({scale});
  transform-origin: top center;
}}
@media print {{
  body.onizleme {{ background: #fff !important; padding: 0 !important; }}
  .toolbar, .no-print {{ display: none !important; }}
  .a4-sayfa {{
    width: auto !important; min-height: auto !important;
    margin: 0 !important; padding: 0 !important;
    box-shadow: none !important; transform: none !important;
  }}
}}
"""

    html_out = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} {_e(vm.teklif_no)}</title>
<style>
@page {{
  size: A4 portrait;
  margin: 10mm 12mm 16mm 12mm;
  @bottom-left {{
    content: "{_css_str(FIRMA_ALT_UNVAN)} · {_css_str(vm.teklif_no)}";
    font-size: 7pt;
    color: #64748B;
  }}
  @bottom-right {{
    content: "Sayfa " counter(page) " / " counter(pages);
    font-size: 7pt;
    color: #64748B;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: 'Segoe UI', Calibri, Arial, sans-serif;
  font-size: 9.5pt;
  color: #1E293B;
  margin: 0;
  padding: 0;
  background: #fff;
}}
{preview_css}
.wrap {{ padding: 0; }}
.ust {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 6px;
}}
.ust-sol {{ flex: 1; min-width: 0; }}
.ust-sag {{
  text-align: right;
  font-size: 7.5pt;
  color: #475569;
  line-height: 1.45;
  max-width: 40%;
}}
.logo {{ max-height: 52px; max-width: 150px; display: block; margin-bottom: 4px; }}
.firma-unvan {{
  font-size: 14pt;
  font-weight: 700;
  color: #0B2A4A;
  letter-spacing: 0.4px;
  margin: 0;
}}
.firma-slogan {{ font-size: 8pt; color: #64748B; margin: 2px 0 0; }}
.serit {{
  height: 3px;
  background: linear-gradient(90deg, #0B2A4A 0%, #0B2A4A 72%, #E8B923 72%, #E8B923 100%);
  margin: 6px 0 8px;
}}
.baslik {{
  text-align: center;
  color: #0B2A4A;
  font-size: 15pt;
  font-weight: 700;
  margin: 0 0 10px;
  letter-spacing: 1.5px;
}}
.bolum {{
  margin: 0 0 10px;
  page-break-inside: avoid;
}}
.bolum-baslik {{
  background: #0B2A4A;
  color: #fff;
  font-size: 8.5pt;
  font-weight: 700;
  letter-spacing: 0.6px;
  padding: 5px 10px;
  margin: 0 0 0;
}}
.bolum-govde {{
  border: 1px solid #CBD5E1;
  border-top: none;
  padding: 8px 10px;
  background: #F8FAFC;
}}
.genel-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px 14px;
}}
.alan {{
  font-size: 8.5pt;
  margin: 2px 0;
  line-height: 1.35;
}}
.etiket {{
  display: inline-block;
  min-width: 92px;
  color: #64748B;
  font-size: 7.5pt;
  font-weight: 600;
}}
.deger-kalin {{ font-weight: 700; color: #0B2A4A; }}
.adres-satir {{
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #CBD5E1;
  grid-column: 1 / -1;
}}
.hitap {{
  font-style: italic;
  color: #334155;
  background: #FFFBEB;
  border-left: 3px solid #E8B923;
  padding: 7px 10px;
  margin: 0 0 10px;
  font-size: 8.5pt;
  line-height: 1.4;
}}
table.urun {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  background: #fff;
}}
table.urun thead {{ display: table-header-group; }}
table.urun th {{
  background: #163E66;
  color: #fff;
  font-size: 7.5pt;
  padding: 5px 3px;
  text-align: center;
  font-weight: 700;
}}
table.urun td {{
  border-bottom: 1px solid #E2E8F0;
  padding: 4px 3px;
  font-size: 8pt;
  vertical-align: top;
  word-wrap: break-word;
}}
table.urun tr {{ page-break-inside: avoid; }}
table.urun tbody tr:nth-child(even) {{ background: #F1F5F9; }}
table.urun td.aciklama {{ text-align: left; }}
.r {{ text-align: right; }}
.c {{ text-align: center; }}
.muted {{ color: #64748B; font-size: 7.5pt; margin-top: 1px; }}
.alt-ozet {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-top: 8px;
}}
.kdv-not {{
  font-size: 8pt;
  color: #64748B;
  max-width: 55%;
  padding-top: 4px;
}}
table.toplam {{
  width: 260px;
  border-collapse: collapse;
  flex-shrink: 0;
}}
table.toplam td {{
  padding: 3px 6px;
  font-size: 8.5pt;
  color: #475569;
}}
table.toplam td.r {{ font-weight: 700; color: #0F172A; }}
table.toplam tr.genel td {{
  background: #0B2A4A;
  color: #fff;
  font-weight: 700;
  font-size: 10pt;
  padding: 6px;
}}
table.toplam tr.genel td.r {{ color: #E8B923; }}
.sart-satir {{ margin: 3px 0; font-size: 8.5pt; }}
.sart-liste {{ margin: 6px 0 0 16px; padding: 0; font-size: 8.5pt; }}
.sart-liste li {{ margin: 3px 0; }}
.banka {{ margin-top: 8px; font-size: 8pt; }}
.banka h4 {{ margin: 0 0 4px; color: #0B2A4A; font-size: 9pt; }}
.banka ul {{ margin: 0; padding-left: 16px; }}
.imza {{
  display: flex;
  justify-content: space-between;
  gap: 28px;
  margin-top: 22px;
  page-break-inside: avoid;
}}
.imza .alan-imza {{
  width: 46%;
  border-top: 1px solid #94A3B8;
  padding-top: 8px;
}}
.imza .alan-imza h4 {{
  margin: 0 0 6px;
  color: #0B2A4A;
  font-size: 9pt;
}}
.imza .alan-imza div {{ font-size: 8pt; color: #64748B; margin: 2px 0; }}
.onay-beyan {{
  margin-top: 8px;
  font-size: 7pt;
  color: #64748B;
  font-style: italic;
}}
.alt-bilgi {{
  margin-top: 14px;
  font-size: 7pt;
  color: #94A3B8;
  border-top: 1px solid #E2E8F0;
  padding-top: 5px;
}}
@media print {{
  body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .bolum-baslik, table.urun th, table.toplam tr.genel td {{
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
}}
</style>
</head>
<body{body_cls}>
{toolbar_html}
{sayfa_ac}
<div class="wrap">
  <div class="ust">
    <div class="ust-sol">
      {logo}
      <div class="firma-unvan">{_e(unvan)}</div>
      {f'<div class="firma-slogan">{_e(slogan)}</div>' if slogan else ''}
    </div>
    <div class="ust-sag">{iletisim_html}</div>
  </div>
  <div class="serit"></div>
  <h1 class="baslik">{_e(vm.belge_baslik or 'FİYAT TEKLİFİ')}</h1>
  {hitap}

  <div class="bolum">
    <div class="bolum-baslik">1 · GENEL BİLGİLER</div>
    <div class="bolum-govde">
      <div class="genel-grid">
        <div>{genel_sol}</div>
        <div>{genel_orta}</div>
        <div>{genel_sag}</div>
        {adres_blok}
      </div>
    </div>
  </div>

  <div class="bolum">
    <div class="bolum-baslik">2 · STOK / ÜRÜN KALEMLERİ</div>
    <div class="bolum-govde" style="padding:0;background:#fff">
      <table class="urun">
        <colgroup>
          <col style="width:5%"/><col style="width:11%"/><col style="width:32%"/>
          <col style="width:8%"/><col style="width:7%"/><col style="width:12%"/>
          <col style="width:7%"/><col style="width:7%"/><col style="width:11%"/>
        </colgroup>
        <thead>
          <tr>
            <th>Sıra</th><th>Stok Kodu</th><th>Ürün / Açıklama</th>
            <th>Miktar</th><th>Birim</th><th>Birim Fiyat</th>
            <th>İsk.%</th><th>KDV%</th><th>Tutar</th>
          </tr>
        </thead>
        <tbody>
{''.join(satir_html)}
        </tbody>
      </table>
      <div class="alt-ozet" style="padding:8px 10px">
        <div class="kdv-not">{_e(vm.kdv_aciklama)}</div>
        {_toplam_html(vm)}
      </div>
    </div>
  </div>

  <div class="bolum">
    <div class="bolum-baslik">3 · ÖZEL ŞARTLAR</div>
    <div class="bolum-govde">
      {''.join(sart_parcalar) if sart_parcalar else ''}
      {madde_html}
      {banka}
    </div>
  </div>

  <div class="imza">
    <div class="alan-imza">
      <h4>Teklifi Hazırlayan</h4>
      {f'<div>{_e(vm.hazirlayan)}</div>' if vm.hazirlayan else ''}
      {f'<div>{_e(vm.hazirlayan_gorev)}</div>' if vm.hazirlayan_gorev else ''}
      <div>İmza / Kaşe</div>
    </div>
    <div class="alan-imza">
      <h4>Müşteri Onayı</h4>
      {f'<div>{_e(m.get("unvan"))}</div>' if m.get("unvan") else ''}
      <div>Tarih: _______________</div>
      <div>İmza / Kaşe</div>
      {onay}
    </div>
  </div>
  {f'<div class="alt-bilgi">{alt}</div>' if alt else ''}
</div>
{sayfa_kapa}
</body>
</html>"""
    assert_customer_output_safe(html_out)
    return html_out
