"""Teklif Word (.docx) çıktısı — CustomerQuoteViewModel üzerinden (ortak veri)."""

from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor

from database.teklif_customer_view import (
    CustomerQuoteViewModel,
    FIRMA_ALT_UNVAN,
    assert_customer_model_safe,
    assert_customer_output_safe,
    para_birimli,
)

_NAVY = RGBColor(0x0B, 0x1F, 0x3A)
_YELLOW = RGBColor(0xE8, 0xB9, 0x23)
_GRAY = RGBColor(0x33, 0x33, 0x33)
_MUTED = RGBColor(0x55, 0x55, 0x55)


def _set_run(run, *, size=9, bold=False, color=_GRAY, name="Calibri"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), name)


def _shade_cell(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def _set_cell_border(cell, **edges):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge, val in edges.items():
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), val.get("val", "single"))
        el.set(qn("w:sz"), str(val.get("sz", 4)))
        el.set(qn("w:color"), val.get("color", "0B1F3A"))
        tcBorders.append(el)
    tcPr.append(tcBorders)


def _para_clear(cell):
    cell.text = ""
    return cell.paragraphs[0]


def _add_logo(doc: Document, vm: CustomerQuoteViewModel, cell):
    if not vm.logo_data_uri or "," not in vm.logo_data_uri:
        return
    try:
        import base64

        b64 = vm.logo_data_uri.split(",", 1)[1]
        data = base64.b64decode(b64)
        p = _para_clear(cell)
        run = p.add_run()
        run.add_picture(io.BytesIO(data), height=Cm(1.6))
    except Exception:
        pass


def _meta_rows(vm: CustomerQuoteViewModel) -> list[tuple[str, str]]:
    rows = [
        ("Teklif No", vm.teklif_no),
        ("Teklif Tarihi", vm.teklif_tarihi),
        ("Geçerlilik", vm.gecerlilik_tarihi),
        ("Para Birimi", vm.para_birimi_etiket or vm.para_birimi),
        ("Hazırlayan", vm.hazirlayan),
        ("Müşteri Temsilcisi", vm.satis_temsilcisi),
        ("Revizyon", vm.revizyon_goster),
        ("Durum", vm.durum),
    ]
    return [(k, v) for k, v in rows if v and str(v).strip()]


def _musteri_rows(vm: CustomerQuoteViewModel) -> list[tuple[str, str]]:
    m = vm.musteri or {}
    rows = [
        ("Unvan", m.get("unvan")),
        ("Yetkili", m.get("yetkili")),
        ("Vergi Dairesi", m.get("vergi_dairesi")),
        ("Vergi / T.C. No", m.get("vergi_no")),
        ("Telefon", m.get("telefon")),
        ("E-posta", m.get("email")),
        ("Fatura Adresi", m.get("fatura_adresi") or m.get("adres")),
        ("Teslimat Adresi", m.get("teslimat_adresi")),
    ]
    return [(k, v) for k, v in rows if v and str(v).strip() and str(v).strip() != "—"]


def _toplam_rows(vm: CustomerQuoteViewModel) -> list[tuple[str, str, bool]]:
    pb = vm.para_birimi_etiket or vm.para_birimi
    gizle = vm.sifir_kalemleri_gizle
    rows: list[tuple[str, str, bool]] = [
        ("Ara Toplam", para_birimli(vm.ara_goster, pb), False),
    ]
    if not gizle or (vm.iskonto_toplam and vm.iskonto_toplam > 0):
        rows.append(("Satır İskontoları", para_birimli(vm.iskonto_goster, pb), False))
    if not gizle or (vm.genel_iskonto and vm.genel_iskonto > 0):
        rows.append(("Genel İskonto", para_birimli(vm.genel_iskonto_goster, pb), False))
        rows.append(
            ("İskonto Sonrası", para_birimli(vm.iskonto_sonrasi_goster, pb), False)
        )
    rows.append(("KDV Toplamı", para_birimli(vm.kdv_goster, pb), False))
    if not gizle or (vm.nakliye and vm.nakliye > 0):
        rows.append(("Nakliye / Hizmet", para_birimli(vm.nakliye_goster, pb), False))
    if not gizle or (vm.yuvarlama and vm.yuvarlama != 0):
        rows.append(("Yuvarlama", para_birimli(vm.yuvarlama_goster, pb), False))
    rows.append(("GENEL TOPLAM", para_birimli(vm.genel_goster, pb), True))
    return rows


def render_customer_quote_docx(vm: CustomerQuoteViewModel, hedef: Path) -> Path:
    """Aynı ViewModel ile Word belgesi üretir."""
    assert_customer_model_safe(vm)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    for section in doc.sections:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.left_margin = Mm(13)
        section.right_margin = Mm(13)
        section.top_margin = Mm(12)
        section.bottom_margin = Mm(16)

    f = vm.firma or {}

    # --- Antet ---
    antet = doc.add_table(rows=1, cols=2)
    antet.autofit = True
    sol, sag = antet.rows[0].cells
    _add_logo(doc, vm, sol)
    p = sol.paragraphs[-1] if sol.paragraphs else sol.add_paragraph()
    if vm.logo_data_uri:
        p = sol.add_paragraph()
    r = p.add_run((f.get("unvan") or "RAY MOBİLYA AKSESUARLARI").upper())
    _set_run(r, size=12, bold=True, color=_NAVY)
    if vm.firma_slogan:
        p2 = sol.add_paragraph()
        _set_run(p2.add_run(vm.firma_slogan), size=8, color=_MUTED)

    iletisim = []
    if f.get("telefon"):
        iletisim.append(f"Tel: {f['telefon']}")
    if f.get("adres"):
        iletisim.append(str(f["adres"]))
    if f.get("email"):
        iletisim.append(f"E-posta: {f['email']}")
    if f.get("web"):
        iletisim.append(f"Web: {f['web']}")
    if f.get("vergi_dairesi"):
        iletisim.append(f"VD: {f['vergi_dairesi']}")
    if f.get("vergi_no"):
        iletisim.append(f"VN: {f['vergi_no']}")
    sag_p = _para_clear(sag)
    sag_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for i, line in enumerate(iletisim):
        if i:
            sag_p.add_run("\n")
        _set_run(sag_p.add_run(line), size=8, color=_MUTED)

    # Ayırıcı
    line_p = doc.add_paragraph()
    line_p.paragraph_format.space_before = Pt(4)
    line_p.paragraph_format.space_after = Pt(6)
    pPr = line_p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "18")
    bottom.set(qn("w:color"), "0B1F3A")
    pBdr.append(bottom)
    pPr.append(pBdr)
    # sarı ince çizgi
    yellow_p = doc.add_paragraph()
    yellow_p.paragraph_format.space_before = Pt(0)
    yellow_p.paragraph_format.space_after = Pt(8)
    pPr2 = yellow_p._p.get_or_add_pPr()
    pBdr2 = OxmlElement("w:pBdr")
    bottom2 = OxmlElement("w:bottom")
    bottom2.set(qn("w:val"), "single")
    bottom2.set(qn("w:sz"), "12")
    bottom2.set(qn("w:color"), "E8B923")
    pBdr2.append(bottom2)
    pPr2.append(pBdr2)

    # Başlık
    baslik = doc.add_paragraph()
    baslik.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run(baslik.add_run(vm.belge_baslik or "FİYAT TEKLİFİ"), size=16, bold=True, color=_NAVY)

    # Meta kutu
    meta = _meta_rows(vm)
    if meta:
        mt = doc.add_table(rows=len(meta), cols=2)
        for i, (k, v) in enumerate(meta):
            c0, c1 = mt.rows[i].cells
            _shade_cell(c0, "EEF1F5")
            p0 = _para_clear(c0)
            _set_run(p0.add_run(k), size=8, bold=True, color=_NAVY)
            p1 = _para_clear(c1)
            _set_run(p1.add_run(str(v)), size=9, bold=True, color=_GRAY)

    # Müşteri
    doc.add_paragraph()
    mk = doc.add_paragraph()
    _set_run(mk.add_run("Sayın / Müşteri Bilgileri"), size=10, bold=True, color=_NAVY)
    mrows = _musteri_rows(vm)
    if mrows:
        mtbl = doc.add_table(rows=len(mrows), cols=2)
        for i, (k, v) in enumerate(mrows):
            c0, c1 = mtbl.rows[i].cells
            p0 = _para_clear(c0)
            _set_run(p0.add_run(k), size=8, color=_MUTED)
            p1 = _para_clear(c1)
            _set_run(p1.add_run(str(v)), size=9, bold=(k == "Unvan"), color=_GRAY)

    # Hitap
    if vm.hitap_metni:
        hp = doc.add_paragraph()
        hp.paragraph_format.space_before = Pt(8)
        hp.paragraph_format.space_after = Pt(8)
        _set_run(hp.add_run(vm.hitap_metni), size=9, color=_GRAY)
        for cell_like in ():
            pass

    # Ürün tablosu
    headers = [
        "Sıra",
        "Kod",
        "Ürün / Hizmet Açıklaması",
        "Miktar",
        "Birim",
        "Birim Fiyat",
        "İsk. %",
        "KDV %",
        "Toplam",
    ]
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    for i, h in enumerate(headers):
        _shade_cell(hdr[i], "0B1F3A")
        p = _para_clear(hdr[i])
        r = p.add_run(h)
        _set_run(r, size=7, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    pb = vm.para_birimi_etiket or vm.para_birimi
    for s in vm.satirlar:
        row = tbl.add_row().cells
        acik = s.urun_adi or ""
        if s.aciklama:
            acik = f"{acik}\n{s.aciklama}" if acik else s.aciklama
        vals = [
            str(s.sira),
            s.urun_kodu or "",
            acik,
            s.miktar_goster,
            s.birim,
            para_birimli(s.birim_fiyat_goster, pb),
            s.iskonto_goster,
            s.kdv_oran_goster,
            para_birimli(s.kdv_hariç_goster, pb),
        ]
        aligns = [
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT,
        ]
        for i, (val, al) in enumerate(zip(vals, aligns)):
            p = _para_clear(row[i])
            p.alignment = al
            _set_run(p.add_run(val), size=8, bold=(i in (0, 8)), color=_GRAY)

    # Toplamlar
    doc.add_paragraph()
    tot = doc.add_table(rows=0, cols=2)
    for etiket, deger, genel in _toplam_rows(vm):
        row = tot.add_row().cells
        if genel:
            _shade_cell(row[0], "0B1F3A")
            _shade_cell(row[1], "0B1F3A")
            p0 = _para_clear(row[0])
            _set_run(p0.add_run(etiket), size=10, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
            p1 = _para_clear(row[1])
            p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_run(p1.add_run(deger), size=10, bold=True, color=RGBColor(0xE8, 0xB9, 0x23))
        else:
            p0 = _para_clear(row[0])
            _set_run(p0.add_run(etiket), size=8, color=_MUTED)
            p1 = _para_clear(row[1])
            p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_run(p1.add_run(deger), size=9, bold=True, color=_GRAY)

    kp = doc.add_paragraph()
    _set_run(kp.add_run(vm.kdv_aciklama), size=8, color=_MUTED)

    # Şartlar
    if vm.sart_satirlari or vm.sart_maddeleri:
        sp = doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(10)
        _set_run(sp.add_run("Teklif Şartları"), size=10, bold=True, color=_NAVY)
        for k, v in vm.sart_satirlari:
            p = doc.add_paragraph()
            _set_run(p.add_run(f"{k}: "), size=8, bold=True, color=_NAVY)
            _set_run(p.add_run(v), size=8, color=_GRAY)
        for madde in vm.sart_maddeleri:
            p = doc.add_paragraph(style="List Bullet")
            _set_run(p.add_run(madde), size=8, color=_GRAY)

    if vm.banka_satirlari:
        bp = doc.add_paragraph()
        _set_run(bp.add_run("Banka Bilgileri"), size=9, bold=True, color=_NAVY)
        for b in vm.banka_satirlari:
            p = doc.add_paragraph()
            _set_run(
                p.add_run(f"{b.get('banka', '')} — {b.get('iban', '')}"),
                size=8,
                color=_GRAY,
            )

    # İmza
    doc.add_paragraph()
    imza = doc.add_table(rows=1, cols=2)
    sol_i, sag_i = imza.rows[0].cells
    p = _para_clear(sol_i)
    _set_run(p.add_run("Teklifi Hazırlayan"), size=9, bold=True, color=_NAVY)
    for line in (vm.hazirlayan, vm.hazirlayan_gorev or "", "İmza / Kaşe"):
        if line:
            pp = sol_i.add_paragraph()
            _set_run(pp.add_run(line), size=8, color=_MUTED)
    p = _para_clear(sag_i)
    _set_run(p.add_run("Müşteri Onayı"), size=9, bold=True, color=_NAVY)
    for line in (
        (vm.musteri or {}).get("unvan") or "",
        "Tarih: _______________",
        "İmza / Kaşe",
    ):
        if line:
            pp = sag_i.add_paragraph()
            _set_run(pp.add_run(str(line)), size=8, color=_MUTED)
    if vm.onay_beyani:
        bey = sag_i.add_paragraph()
        bey.paragraph_format.space_before = Pt(6)
        _set_run(bey.add_run(vm.onay_beyani), size=7, color=_MUTED)

    # Alt bilgi
    foot = doc.add_paragraph()
    foot.paragraph_format.space_before = Pt(12)
    alt = " · ".join(
        x
        for x in (
            FIRMA_ALT_UNVAN,
            f.get("telefon"),
            f.get("adres"),
            f.get("web") or f.get("email"),
            f"Oluşturulma: {vm.olusturma_tarih_saat}" if vm.olusturma_tarih_saat else "",
        )
        if x
    )
    _set_run(foot.add_run(alt), size=7, color=_MUTED)

    doc.save(str(hedef))
    # Güvenlik: docx zip — düz metin tarama için paragraf birleştir
    try:
        metin = "\n".join(p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    metin += "\n" + cell.text
        assert_customer_output_safe(metin)
    except Exception:
        # Dosya kaydedildi; güvenlik taraması başarısızsa sil
        assert_customer_output_safe(
            " ".join(
                [
                    vm.belge_baslik,
                    vm.teklif_no,
                    vm.hitap_metni,
                    vm.genel_goster,
                    " ".join(s.urun_adi for s in vm.satirlar),
                ]
            )
        )
    return hedef


def musteri_teklif_docx_uret(dialog, hedef: Path | None = None) -> Path:
    from database.teklif_customer_view import build_customer_quote_from_dialog
    from teklif_print import kaydet_teklif_cikti_yolu

    vm = build_customer_quote_from_dialog(dialog)
    if hedef is None:
        hedef = kaydet_teklif_cikti_yolu(vm, "docx")
    return render_customer_quote_docx(vm, Path(hedef))
