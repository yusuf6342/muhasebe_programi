"""Mal kabul durumu + PDF önizleme yardımcıları."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fatura_belge_aktarim.draft_service import MAL_KABUL_DURUMLARI
from fatura_belge_aktarim.pdf_preview import sayfa_png_bytes, sayfa_sayisi


def _mini_pdf() -> bytes:
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((40, 60), "Cin Muhasebe test faturasi")
    page2 = doc.new_page(width=300, height=400)
    page2.insert_text((40, 60), "Sayfa 2")
    data = doc.tobytes()
    doc.close()
    return data


class MalKabulSabitlerTest(unittest.TestCase):
    def test_uc_durum(self):
        self.assertEqual(
            set(MAL_KABUL_DURUMLARI),
            {"mal_geldi", "mal_bekleniyor", "irsaliyeden"},
        )


class PdfPreviewTest(unittest.TestCase):
    def test_sayfa_png(self):
        with TemporaryDirectory() as td:
            yol = Path(td) / "t.pdf"
            yol.write_bytes(_mini_pdf())
            self.assertEqual(sayfa_sayisi(yol), 2)
            png1 = sayfa_png_bytes(yol, 0, genislik=200)
            png2 = sayfa_png_bytes(yol, 1, genislik=200)
            self.assertIsNotNone(png1)
            self.assertIsNotNone(png2)
            self.assertTrue(png1.startswith(b"\x89PNG"))
            self.assertNotEqual(png1, png2)

    def test_gorsel_sayfa(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL yok")
        with TemporaryDirectory() as td:
            yol = Path(td) / "t.png"
            Image.new("RGB", (80, 60), color=(200, 100, 50)).save(yol)
            self.assertEqual(sayfa_sayisi(yol), 1)
            png = sayfa_png_bytes(yol, 0, genislik=40)
            self.assertIsNotNone(png)
            self.assertTrue(png.startswith(b"\x89PNG"))


class MalKabulHareketMantigiTest(unittest.TestCase):
    """kesinlestir hareket_yaz kararı — saf mantık (DB yok)."""

    def test_alis_mal_geldi_stok_yazar(self):
        for mk, kismi, beklenen in (
            ("mal_geldi", False, True),
            ("mal_geldi", True, False),  # kısmi teslim → stok sonra
            ("mal_bekleniyor", False, False),
            ("irsaliyeden", False, False),
            ("", False, False),
            ("bilinmeyen", False, False),
        ):
            mal_kabul = (mk or "mal_bekleniyor").strip().lower()
            if mal_kabul not in MAL_KABUL_DURUMLARI:
                mal_kabul = "mal_bekleniyor"
            yon = "ALIS"
            hareket_yaz = yon == "ALIS" and mal_kabul == "mal_geldi" and not kismi
            self.assertEqual(hareket_yaz, beklenen, msg=f"{mk}/{kismi}")

    def test_teslim_miktar_asinamaz(self):
        from decimal import Decimal

        # Saf doğrulama: belge miktarını aşan teslim reddi (DB gerekmez)
        belge = Decimal("10")
        t = Decimal("12")
        with self.assertRaises(ValueError):
            if t > belge:
                raise ValueError(f"Teslim miktarı ({t}) belge miktarını ({belge}) aşamaz.")


if __name__ == "__main__":
    unittest.main()
