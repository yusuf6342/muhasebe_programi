"""Satış irsaliyesi Word (.docx) çıktısı — düzenlenebilir metin ve tablolar (görüntü yok)."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor

from database.irsaliye_customer_view import (
    CustomerDispatchViewModel,
    assert_customer_model_safe,
    assert_customer_output_safe,
    belge_bilgi_satirlari,
    birim_toplamlari,
    firma_vergi_metni,
    miktar_metni,
    musteri_vergi_metni,
    not_bolumleri,
    teslimat_satirlari,
    toplam_miktar_metni,
)

LACIVERT = RGBColor(0x10, 0x2A, 0x43)
SARI = RGBColor(0xF4, 0xC5, 0x42)
METIN = RGBColor(0x17, 0x2B, 0x4D)
SOLUK = RGBColor(0x62, 0x7D, 0x98)
BEYAZ = RGBColor(0xFF, 0xFF, 0xFF)

KULLANILABILIR_MM = 186
MIKTAR_KOLONLARI = (12, 34, 96, 20, 24)
FIYATLI_KOLONLAR = (12, 24, 56, 14, 18, 22, 11, 11, 18)


def _run(p, metin: str, *, boyut=9.0, kalin=False, renk=METIN):
    r = p.add_run(metin)
    r.font.size = Pt(boyut)
    r.font.bold = kalin
    r.font.color.rgb = renk
    r.font.name = "Segoe UI"
    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Segoe UI")
    return r


def _paragraf(hucre_veya_doc, *, ilk=False, hiza=None, once=0, sonra=0):
    if ilk:
        p = hucre_veya_doc.paragraphs[0]
    else:
        p = hucre_veya_doc.add_paragraph()
    p.paragraph_format.space_before = Pt(once)
    p.paragraph_format.space_after = Pt(sonra)
    if hiza is not None:
        p.alignment = hiza
    return p


def _golge(hucre, renk: str):
    tcPr = hucre._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), renk)
    tcPr.append(shd)


def _kenarlik(hucre, **kenarlar):
    tcPr = hucre._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for kenar in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{kenar}")
        ayar = kenarlar.get(kenar)
        if ayar is None:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), ayar.get("val", "single"))
            el.set(qn("w:sz"), str(ayar.get("sz", 4)))
            el.set(qn("w:color"), ayar.get("renk", "D9E2EC"))
        borders.append(el)
    tcPr.append(borders)


def _tablo_sabit(tablo, genislikler_mm):
    tablo.autofit = False
    tblPr = tablo._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    for satir in tablo.rows:
        for hucre, mm in zip(satir.cells, genislikler_mm):
            hucre.width = Mm(mm)
    grid = tablo._tbl.tblGrid
    for col, mm in zip(grid.findall(qn("w:gridCol")), genislikler_mm):
        col.set(qn("w:w"), str(int(mm * 56.7)))


def _satir_bolunmesin(satir, *, baslik=False):
    trPr = satir._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))
    if baslik:
        trPr.append(OxmlElement("w:tblHeader"))


def _sabit_yukseklik(satir, mm: float):
    trPr = satir._tr.get_or_add_trPr()
    h = OxmlElement("w:trHeight")
    h.set(qn("w:val"), str(int(mm * 56.7)))
    h.set(qn("w:hRule"), "atLeast")
    trPr.append(h)


def _alan(p, kod: str):
    for tur, metin in (("begin", None), (None, kod), ("separate", None), (None, "1"), ("end", None)):
        r = _run(p, "", boyut=7.5, renk=LACIVERT)
        if tur:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), tur)
            r._element.append(fld)
        elif metin == kod:
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = f" {kod} "
            r._element.append(instr)
        else:
            r.text = metin


def _alt_cizgi(p, renk: str, kalinlik: int):
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    alt = OxmlElement("w:bottom")
    alt.set(qn("w:val"), "single")
    alt.set(qn("w:sz"), str(kalinlik))
    alt.set(qn("w:color"), renk)
    bdr.append(alt)
    pPr.append(bdr)


def _ust_cizgi(p, renk: str, kalinlik: int):
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    ust = OxmlElement("w:top")
    ust.set(qn("w:val"), "single")
    ust.set(qn("w:sz"), str(kalinlik))
    ust.set(qn("w:color"), renk)
    bdr.append(ust)
    pPr.append(bdr)


def _kutu_satiri(hucre, etiket: str, deger: str):
    p = _paragraf(hucre, once=1)
    _run(p, f"{etiket}: ", boyut=8.5, renk=SOLUK)
    _run(p, deger, boyut=8.5, kalin=True)


def render_dispatch_docx(vm: CustomerDispatchViewModel, hedef: Path) -> Path:
    assert_customer_model_safe(vm)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    f = vm.firma or {}
    m = vm.musteri or {}

    doc = Document()
    stil = doc.styles["Normal"]
    stil.font.name = "Segoe UI"
    stil.font.size = Pt(9)
    bolum = doc.sections[0]
    bolum.page_width, bolum.page_height = Mm(210), Mm(297)
    bolum.left_margin = bolum.right_margin = Mm(12)
    bolum.top_margin = Mm(12)
    bolum.bottom_margin = Mm(18)
    bolum.footer_distance = Mm(7)

    # Alt bilgi: evrak no + Sayfa X / Y (Word alanları)
    alt = bolum.footer.paragraphs[0]
    sekmeler = alt.paragraph_format.tab_stops
    for varsayilan in (Inches(3.25), Inches(6.5)):  # «Footer» stilinin orta/sağ sekmeleri
        sekmeler.add_tab_stop(varsayilan, WD_TAB_ALIGNMENT.CLEAR)
    sekmeler.add_tab_stop(Mm(KULLANILABILIR_MM), WD_TAB_ALIGNMENT.RIGHT)
    _ust_cizgi(alt, "F4C542", 8)
    _run(alt, f"Evrak No: {vm.irsaliye_no}", boyut=7.5, renk=LACIVERT)
    _run(alt, "\tSayfa ", boyut=7.5, renk=LACIVERT)
    _alan(alt, "PAGE")
    _run(alt, " / ", boyut=7.5, renk=LACIVERT)
    _alan(alt, "NUMPAGES")

    # Antet
    antet = doc.add_table(rows=1, cols=2)
    _tablo_sabit(antet, (108, 78))
    sol, sag = antet.rows[0].cells
    p = _paragraf(sol, ilk=True)
    if vm.logo_data_uri and "," in vm.logo_data_uri:
        try:
            veri = base64.b64decode(vm.logo_data_uri.split(",", 1)[1])
            p.add_run().add_picture(io.BytesIO(veri), height=Mm(16))
            p = _paragraf(sol, once=2)
        except Exception:
            pass
    _run(p, f.get("unvan") or "", boyut=12, kalin=True, renk=LACIVERT)
    for satir in (
        f.get("adres"),
        "  ·  ".join(x for x in (f"Tel: {f['telefon']}" if f.get("telefon") else "", f.get("email") or "") if x),
        firma_vergi_metni(f),
    ):
        if satir:
            _run(_paragraf(sol), satir, boyut=8.5, renk=SOLUK)

    bp = _paragraf(sag, ilk=True, sonra=3)
    _golge(sag, "FFFFFF")
    baslik_tablo = sag.add_table(rows=1, cols=1)
    bh = baslik_tablo.rows[0].cells[0]
    _golge(bh, "102A43")
    _kenarlik(bh, left={"sz": 24, "renk": "F4C542"})
    _run(_paragraf(bh, ilk=True, once=2, sonra=2), vm.belge_baslik, boyut=15, kalin=True, renk=BEYAZ)
    bp._p.getparent().remove(bp._p)
    bilgi = sag.add_table(rows=0, cols=2)
    for etiket, deger in belge_bilgi_satirlari(vm):
        c0, c1 = bilgi.add_row().cells
        _run(_paragraf(c0, ilk=True, once=1), etiket, boyut=8.5, renk=SOLUK)
        _run(_paragraf(c1, ilk=True, once=1), deger, boyut=9, kalin=True, renk=LACIVERT)
    _tablo_sabit(bilgi, (28, 50))
    _paragraf(sag).paragraph_format.line_spacing = Pt(2)  # Word: hücre bir paragrafla bitmeli

    serit = _paragraf(doc, once=2, sonra=6)
    serit.paragraph_format.line_spacing = Pt(4)
    _alt_cizgi(serit, "F4C542", 24)

    # Müşteri / teslimat kutuları
    kutular = doc.add_table(rows=1, cols=2)
    kutular.alignment = WD_TABLE_ALIGNMENT.CENTER
    _tablo_sabit(kutular, (93, 93))
    _satir_bolunmesin(kutular.rows[0])
    k_m, k_t = kutular.rows[0].cells
    for hucre, baslik in ((k_m, "MÜŞTERİ"), (k_t, "TESLİMAT")):
        _golge(hucre, "F3F6F9")
        _kenarlik(
            hucre, top={"sz": 18, "renk": "102A43"}, left={}, bottom={}, right={},
        )
        _run(_paragraf(hucre, ilk=True, once=2), baslik, boyut=9, kalin=True, renk=LACIVERT)
    _run(_paragraf(k_m, once=1), m.get("unvan") or "", boyut=10.5, kalin=True, renk=LACIVERT)
    _kutu_satiri(k_m, "Müşteri Kodu", m.get("kod") or "")
    vergi = musteri_vergi_metni(m)
    if vergi:
        _kutu_satiri(k_m, "Vergi Bilgisi", vergi)
    if m.get("adres"):
        _kutu_satiri(k_m, "Adres", m["adres"])
    for etiket, deger in teslimat_satirlari(vm):
        _kutu_satiri(k_t, etiket, deger)
    for hucre in (k_m, k_t):
        _paragraf(hucre, sonra=2)

    _paragraf(doc, sonra=4)

    # Ürün tablosu
    basliklar = ["Sıra", "Stok Kodu", "Ürün Adı / Açıklama", "Birim", "Miktar"]
    hizalar = ["c", "l", "l", "c", "r"]
    genislik = MIKTAR_KOLONLARI
    if vm.is_priced:
        basliklar += ["Birim Fiyat", "İsk.", "KDV", "Tutar"]
        hizalar += ["r", "c", "c", "r"]
        genislik = FIYATLI_KOLONLAR
    hiza_map = {"c": WD_ALIGN_PARAGRAPH.CENTER, "l": WD_ALIGN_PARAGRAPH.LEFT, "r": WD_ALIGN_PARAGRAPH.RIGHT}
    tablo = doc.add_table(rows=1, cols=len(basliklar))
    for hucre, metin, hz in zip(tablo.rows[0].cells, basliklar, hizalar):
        _golge(hucre, "102A43")
        _kenarlik(hucre, bottom={"sz": 12, "renk": "F4C542"})
        _run(_paragraf(hucre, ilk=True, hiza=hiza_map[hz], once=2, sonra=2), metin, boyut=8.5, kalin=True, renk=BEYAZ)
    _satir_bolunmesin(tablo.rows[0], baslik=True)
    for i, s in enumerate(vm.satirlar):
        satir = tablo.add_row()
        _satir_bolunmesin(satir)
        degerler = [str(s.sira), s.urun_kodu, s.urun_adi, s.birim, s.miktar_goster]
        if vm.is_priced:
            degerler += [s.birim_fiyat_goster, s.iskonto_goster, s.kdv_oran_goster, s.satir_toplam_goster]
        for j, (hucre, deger, hz) in enumerate(zip(satir.cells, degerler, hizalar)):
            if i % 2:
                _golge(hucre, "F8FAFC")
            _kenarlik(hucre, bottom={"sz": 4, "renk": "D9E2EC"})
            p = _paragraf(hucre, ilk=True, hiza=hiza_map[hz], once=1.5, sonra=1.5)
            _run(p, deger or "", boyut=8.5, kalin=(j == 4))
            if j == 2 and s.aciklama:
                _run(_paragraf(hucre, sonra=1.5), s.aciklama, boyut=7.5, renk=SOLUK)
    _tablo_sabit(tablo, genislik)

    # Toplamlar (birim bazında)
    toplamlar = birim_toplamlari(vm.satirlar)
    tp = _paragraf(doc, once=6, sonra=1)
    tp.paragraph_format.keep_with_next = True
    _run(tp, f"Toplam Miktar: {vm.toplam_miktar_goster or toplam_miktar_metni(vm.satirlar)}", boyut=9.5, kalin=True, renk=LACIVERT)
    rozet = doc.add_table(rows=1, cols=max(len(toplamlar), 1))
    for hucre, (birim, miktar) in zip(rozet.rows[0].cells, toplamlar):
        _golge(hucre, "FFE89A")
        _kenarlik(hucre, left={"sz": 18, "renk": "102A43"})
        _run(_paragraf(hucre, ilk=True, once=1, sonra=1), f"{miktar_metni(miktar)} {birim}", boyut=9, kalin=True, renk=RGBColor(0x08, 0x1B, 0x2C))
    _tablo_sabit(rozet, [min(32, KULLANILABILIR_MM // max(len(toplamlar), 1))] * max(len(toplamlar), 1))
    kp = _paragraf(doc, once=1, sonra=2)
    _run(
        kp,
        f"Kalem: {len(vm.satirlar)}" + (" · Farklı birimler ayrı toplanır" if len(toplamlar) > 1 else ""),
        boyut=8,
        renk=SOLUK,
    )
    if vm.is_priced:
        tutar = doc.add_table(rows=0, cols=2)
        tutar.alignment = WD_TABLE_ALIGNMENT.RIGHT
        for etiket, deger, genel in (
            ("Ara Toplam", vm.ara_goster, False),
            ("KDV", vm.kdv_goster, False),
            ("Genel Toplam", vm.genel_goster, True),
        ):
            c0, c1 = tutar.add_row().cells
            if genel:
                _golge(c0, "102A43")
                _golge(c1, "102A43")
            renk = SARI if genel else METIN
            _run(_paragraf(c0, ilk=True, once=1, sonra=1), etiket, boyut=9, kalin=genel, renk=renk)
            _run(
                _paragraf(c1, ilk=True, hiza=WD_ALIGN_PARAGRAPH.RIGHT, once=1, sonra=1),
                f"{deger} {vm.para_birimi}", boyut=9, kalin=True, renk=renk,
            )
        _tablo_sabit(tutar, (32, 36))

    # Notlar (imza bölümünün üstünde)
    for baslik, metin in not_bolumleri(vm):
        np_ = _paragraf(doc, once=6, sonra=0)
        np_.paragraph_format.keep_with_next = True
        _run(np_, baslik, boyut=9, kalin=True, renk=LACIVERT)
        for parca in str(metin).splitlines() or [""]:
            pp = _paragraf(doc, sonra=0)
            pp.paragraph_format.keep_with_next = True
            _run(pp, parca, boyut=8.5)

    ara = _paragraf(doc, once=8, sonra=0)
    ara.paragraph_format.keep_with_next = True

    # Teslim eden / teslim alan — tek satırlık, bölünmeyen tablo
    imza = doc.add_table(rows=1, cols=3)
    _tablo_sabit(imza, (90, 6, 90))
    _satir_bolunmesin(imza.rows[0])
    for hucre, baslik in ((imza.rows[0].cells[0], "TESLİM EDEN"), (imza.rows[0].cells[2], "TESLİM ALAN")):
        kenar = {"sz": 10, "renk": "102A43"}
        _kenarlik(hucre, top=kenar, left=kenar, bottom=kenar, right=kenar)
        bas = _paragraf(hucre, ilk=True, once=0, sonra=4)
        pPr = bas._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "102A43")
        pPr.append(shd)
        _run(bas, f" {baslik}", boyut=9.5, kalin=True, renk=SARI)
        for etiket, bosluk in (("Adı Soyadı", 14), ("Tarih / Saat", 14), ("İmza", 40)):
            p = _paragraf(hucre, once=bosluk, sonra=2)
            p.paragraph_format.tab_stops.add_tab_stop(Mm(86), WD_TAB_ALIGNMENT.LEFT, WD_TAB_LEADER.DOTS)
            _run(p, f" {etiket}", boyut=8.5, renk=SOLUK)
            _run(p, "\t", boyut=8.5, renk=SOLUK)
    orta = imza.rows[0].cells[1]
    _kenarlik(orta)
    _sabit_yukseklik(imza.rows[0], 52)

    son = _paragraf(doc, once=4)
    _run(
        son,
        "Bu belge müşteri sevk irsaliyesidir." + (f" Oluşturulma: {vm.olusturma}" if vm.olusturma else ""),
        boyut=7.5,
        renk=RGBColor(0x94, 0xA3, 0xB8),
    )

    metin = "\n".join(p.text for p in doc.paragraphs)
    for t in doc.tables:
        for satir in t.rows:
            for hucre in satir.cells:
                metin += "\n" + hucre.text
    assert_customer_output_safe(metin)
    gecici = hedef.with_name(f".{hedef.stem}_gecici.docx")
    doc.save(str(gecici))
    gecici.replace(hedef)
    return hedef
