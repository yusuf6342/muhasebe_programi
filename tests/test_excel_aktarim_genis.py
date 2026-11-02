"""Excel aktarım genişleme — writer, karşılaştırma, yeni tip kayıtları."""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import excel_aktarim  # noqa: F401
from excel_aktarim.karsilastirma import karsilastir
from excel_aktarim.reader import ExcelReaderService
from excel_aktarim.template import ImportTemplateService
from excel_aktarim.types import getir, modul_tipleri
from excel_aktarim.writer import SABLON_SURUM, excel_yaz
from openpyxl import load_workbook


class ExcelAktarimGenisTest(unittest.TestCase):
    def test_writer_kod_sifir_korur(self):
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "kod.xlsx"
            excel_yaz(
                yol,
                basliklar=["Barkod", "Ad", "Tutar"],
                satirlar=[["000123", "Kalem", "1.234,50"]],
                kolon_tipleri=["kod", "metin", "para"],
                amac="yeniden_al",
                meta={"sablon_turu": "test", "kayit_sayisi": 1},
            )
            wb = load_workbook(yol)
            self.assertIn("Aktarım Bilgisi", wb.sheetnames)
            ws = wb["Veriler"]
            self.assertEqual(str(ws["A2"].value), "000123")
            self.assertEqual(ws["A2"].number_format, "@")
            wb.close()

    def test_sablon_aktarim_bilgisi_ve_ornekler(self):
        tip = getir("stok_karti")
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "stok.xlsx"
            ImportTemplateService.olustur(tip, yol)
            wb = load_workbook(yol)
            self.assertIn("Aktarım Bilgisi", wb.sheetnames)
            self.assertIn("Örnekler", wb.sheetnames)
            self.assertIn("Veriler", wb.sheetnames)
            self.assertEqual(wb["Aktarım Bilgisi"]["B2"].value, SABLON_SURUM)
            wb.close()

    def test_karsilastirma_kovalar(self):
        program = [
            {"kod": "A", "tutar": Decimal("10")},
            {"kod": "B", "tutar": Decimal("20")},
            {"kod": "C", "tutar": Decimal("30")},
        ]
        excel = [
            {"kod": "A", "tutar": Decimal("10")},
            {"kod": "B", "tutar": Decimal("21")},
            {"kod": "D", "tutar": Decimal("40")},
        ]
        s = karsilastir(program, excel, anahtar_alanlar=["kod"], tutar_alani="tutar")
        o = s.ozet()
        self.assertEqual(o["eslesen"], 1)
        self.assertEqual(o["tutar_farkli"], 1)
        self.assertEqual(o["sadece_program"], 1)
        self.assertEqual(o["sadece_excel"], 1)

    def test_yeni_evrak_tipleri_kayitli(self):
        kodlar = {t.kod for t in modul_tipleri("satis")}
        self.assertIn("satis_siparis_excel", kodlar)
        self.assertIn("satis_irsaliye_excel", kodlar)
        self.assertIn("teklif_excel", kodlar)
        self.assertIn("alis_siparis_excel", {t.kod for t in modul_tipleri("satin_alma")})
        self.assertIn("alis_irsaliye_excel", {t.kod for t in modul_tipleri("satin_alma")})

    def test_export_kart_stok_baslik(self):
        from excel_aktarim.export_kart import stok_kartlari_excel_aktar

        tip = getir("stok_karti")
        ornek = {a.kod: (a.ornek or "x") for a in tip.alanlar}
        ornek["stok_kodu"] = "000099"
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "kart.xlsx"
            stok_kartlari_excel_aktar(yol, [ornek], firma="Test")
            okuma = ExcelReaderService.oku(yol, sayfa="Kartlar")
            self.assertEqual(len(okuma.satirlar), 1)


if __name__ == "__main__":
    unittest.main()
