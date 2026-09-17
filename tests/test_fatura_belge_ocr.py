"""Tesseract OCR yapılandırma ve motor testleri."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from fatura_belge_aktarim.json_codec import dumps_accounting, to_decimal
from fatura_belge_aktarim.normalize import parse_decimal_tr
from fatura_belge_aktarim.ocr_config import (
    find_tesseract,
    list_tesseract_languages,
    ocr_durum_raporu,
    set_tesseract_path,
    tesseract_version,
)


class TesseractPathTest(unittest.TestCase):
    def test_find_tesseract(self):
        path = find_tesseract()
        self.assertTrue(path is None or os.path.isfile(path))
        if path:
            self.assertTrue(path.lower().endswith("tesseract.exe") or path.lower().endswith("tesseract"))

    def test_bulunamazsa_crash_yok(self):
        with mock.patch("fatura_belge_aktarim.ocr_config.get_ocr_setting", return_value=None):
            with mock.patch.dict(os.environ, {"TESSERACT_CMD": ""}, clear=False):
                with mock.patch("fatura_belge_aktarim.ocr_config.shutil.which", return_value=None):
                    with mock.patch("fatura_belge_aktarim.ocr_config.os.path.isfile", return_value=False):
                        self.assertIsNone(find_tesseract())
                        rapor = ocr_durum_raporu()
                        self.assertIn("bulundu", rapor)

    def test_diller(self):
        path = find_tesseract()
        if not path:
            self.skipTest("Tesseract kurulu değil")
        langs = list_tesseract_languages(path)
        self.assertTrue(langs)
        # Kullanıcı ortamında tur/eng/osd beklenir
        for dil in ("tur", "eng", "osd"):
            if dil not in langs:
                self.skipTest(f"{dil} dil paketi yok: {langs}")
        self.assertIn("tur", langs)
        self.assertIn("eng", langs)
        self.assertIn("osd", langs)
        ver = tesseract_version(path)
        self.assertTrue(ver)


class DecimalOcrTest(unittest.TestCase):
    def test_para(self):
        self.assertEqual(parse_decimal_tr("1.250,00 TL"), Decimal("1250.00"))
        self.assertEqual(to_decimal(parse_decimal_tr("%20")), Decimal("20"))
        text = dumps_accounting({"v": Decimal("15000.10")})
        self.assertIn("15000.10", text)


class RenderAndOcrTest(unittest.TestCase):
    def test_pdf_render_dpi(self):
        path = find_tesseract()
        if not path:
            self.skipTest("Tesseract yok")
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF yok")
        from fatura_belge_aktarim.ocr_engine import render_pdf_pages

        # boş PDF
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 50), "Fatura No: OCR-1")
        pdf_bytes = doc.tobytes()
        doc.close()
        pages = render_pdf_pages(pdf_bytes, dpi=300)
        self.assertEqual(len(pages), 1)
        w, h = pages[0]["image"].size
        self.assertGreater(w, 500)

    def test_image_jpg_png_webp_ocr_pipeline(self):
        if not find_tesseract():
            self.skipTest("Tesseract yok")
        try:
            from PIL import Image, ImageDraw
            import pytesseract
            from fatura_belge_aktarim.ocr_config import configure_pytesseract
        except ImportError:
            self.skipTest("PIL/pytesseract yok")
        self.assertTrue(configure_pytesseract())
        from fatura_belge_aktarim.ocr_engine import extract_with_ocr

        img = Image.new("RGB", (900, 400), "white")
        d = ImageDraw.Draw(img)
        d.text((30, 30), "Fatura No: IMG-001", fill="black")
        d.text((30, 80), "Mal/Hizmet Bilgileri", fill="black")
        d.text((30, 130), "Kalem Alfa 5 Adet 100,00 20 500,00", fill="black")
        d.text((30, 200), "Genel Toplam 600,00", fill="black")

        for fmt, ext in (("JPEG", ".jpg"), ("PNG", ".png"), ("WEBP", ".webp")):
            buf = io.BytesIO()
            save_kw = {"format": fmt}
            if fmt == "JPEG":
                save_kw["quality"] = 95
            try:
                img.save(buf, **save_kw)
            except Exception:
                if fmt == "WEBP":
                    self.skipTest("WebP kayıt desteklenmiyor")
                raise
            inv, diag = extract_with_ocr(buf.getvalue(), is_pdf=False, dosya_adi=f"t{ext}")
            self.assertTrue(diag.get("ocr_used"))
            # OCR satır bulamayabilir (sentetik font); en azından çökmemeli
            self.assertIsNotNone(inv)

    def test_force_ocr_on_tesay_still_works_via_table_first(self):
        """Gerçek PDF: önce tablo, force OCR da çalışır."""
        candidates = list(
            Path(r"C:\Users\cigde\AppData\Local\MuhasebeProgrami\data\invoice_imports").glob(
                "*tesay fatura.pdf"
            )
        )
        if not candidates:
            self.skipTest("Tesay PDF yok")
        from fatura_belge_aktarim.pdf_extractor import extract_pdf_invoice

        data = candidates[0].read_bytes()
        inv, kaynak, diag = extract_pdf_invoice(data)
        self.assertGreaterEqual(len(inv.satirlar), 1)
        # force OCR
        if not find_tesseract():
            return
        inv2, kaynak2, diag2 = extract_pdf_invoice(data, force_method="ocr")
        self.assertTrue(diag2.get("ocr_used"))
        # OCR veya önceki yöntem; çökmemeli
        self.assertIsNotNone(inv2)

    def test_preprocess_rotate_safe(self):
        from PIL import Image
        from fatura_belge_aktarim.ocr_preprocess import preprocess_for_ocr

        img = Image.new("RGB", (200, 100), "white")
        out = preprocess_for_ocr(img)
        self.assertIsNotNone(out)


class MultiLineDescTest(unittest.TestCase):
    def test_heuristic_merge_like(self):
        from fatura_belge_aktarim.pdf_lines import text_heuristic_lines

        metin = """
Mal/Hizmet Bilgileri
Uzun ürün adı devam eden
açıklama satırı 2 Adet 50,00 20 100,00
Genel Toplam 100,00
"""
        # Sezgisel tek satır kalıbı ikinci satırı yakalayabilir
        lines = text_heuristic_lines(metin)
        self.assertIsInstance(lines, list)


if __name__ == "__main__":
    unittest.main()
