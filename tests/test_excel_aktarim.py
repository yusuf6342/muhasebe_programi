"""Excel aktarım — şablon, okuyucu, eşleme, müşteri dry-run."""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import excel_aktarim  # noqa: F401
from excel_aktarim.mapping import ColumnMappingService
from excel_aktarim.normalize import baslik_normalize, decimal_parse, tarih_parse
from excel_aktarim.reader import ExcelReaderService
from excel_aktarim.template import ImportTemplateService
from excel_aktarim.types import getir, modul_tipleri


class ExcelAktarimTest(unittest.TestCase):
    def test_baslik_normalize(self):
        self.assertEqual(baslik_normalize("Cari Kodu"), "carikodu")
        self.assertEqual(baslik_normalize("Vergi No"), "vergino")

    def test_decimal_ve_tarih(self):
        self.assertEqual(decimal_parse("1.234,56"), Decimal("1234.56"))
        self.assertEqual(tarih_parse("17.09.2026").isoformat(), "2026-09-17")

    def test_modul_tipleri_kayitli(self):
        self.assertTrue(any(t.kod == "musteri_cari" for t in modul_tipleri("satis")))
        self.assertTrue(any(t.kod == "tedarikci_cari" for t in modul_tipleri("satin_alma")))
        self.assertTrue(any(t.kod == "stok_karti" for t in modul_tipleri("stok")))
        self.assertTrue(any(t.kod == "stok_birim" for t in modul_tipleri("stok")))

    def test_stok_birim_sablon(self):
        tip = getir("stok_birim")
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "birim.xlsx"
            ImportTemplateService.olustur(tip, yol)
            self.assertTrue(yol.is_file())
            okuma = ExcelReaderService.oku(yol)
            esleme = ColumnMappingService.otomatik_esle(tip, okuma.basliklar)
            self.assertIn("yeni_birim", esleme.esleme.values())

    def test_stok_birim_dogrulama_eksik(self):
        from excel_aktarim.importers.stok_birim import StokBirimImporter, STOK_BIRIM_TIPI

        importer = StokBirimImporter(STOK_BIRIM_TIPI)
        rapor = importer.dogrula_satirlar(
            [{"yeni_birim": "Paket", "carpan": "1000"}],
            guncelleme_modu="guncelle",
        )
        self.assertEqual(rapor.hatali, 1)

    def test_fatura_excel_tipleri(self):
        self.assertTrue(any(t.kod == "satis_fatura_excel" for t in modul_tipleri("satis")))
        self.assertTrue(any(t.kod == "alis_fatura_excel" for t in modul_tipleri("satin_alma")))
        tip = getir("satis_fatura_excel")
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "sf.xlsx"
            ImportTemplateService.olustur(tip, yol)
            self.assertTrue(yol.is_file())

    def test_fatura_excel_dogrulama_eksik(self):
        from excel_aktarim.importers.fatura_excel import FaturaExcelImporter, SATIS_FATURA_TIPI

        importer = FaturaExcelImporter(SATIS_FATURA_TIPI, "SATIS")
        rapor = importer.dogrula_satirlar(
            [{"fatura_grubu": "G1", "miktar": "1"}],
            guncelleme_modu="guncelle",
        )
        self.assertGreaterEqual(rapor.hatali, 1)

    def test_sablon_ve_okuma(self):
        tip = getir("musteri_cari")
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "musteri.xlsx"
            ImportTemplateService.olustur(tip, yol)
            self.assertTrue(yol.is_file())
            # Veriler: yalnız başlık; örnek satırlar Örnekler sayfasında
            okuma = ExcelReaderService.oku(yol, sayfa="Veriler")
            self.assertTrue(any("nvan" in b.casefold() for b in okuma.basliklar))
            self.assertEqual(len(okuma.satirlar), 0)
            ornek = ExcelReaderService.oku(yol, sayfa="Örnekler")
            self.assertGreaterEqual(len(ornek.satirlar), 1)
            esleme = ColumnMappingService.otomatik_esle(tip, okuma.basliklar)
            self.assertIn("unvan", esleme.esleme.values())

    def test_musteri_dogrulama_dry(self):
        from excel_aktarim.importers.cari_kart import CariKartImporter, MUSTERI_TIPI

        importer = CariKartImporter(MUSTERI_TIPI, "Müşteri")
        rapor = importer.dogrula_satirlar(
            [{"unvan": "Test Firma A.Ş."}],
            guncelleme_modu="guncelle",
        )
        self.assertEqual(rapor.gecerli, 1)
        self.assertEqual(rapor.satirlar[0].islem, "insert")

    def test_musteri_unvan_zorunlu(self):
        from excel_aktarim.importers.cari_kart import CariKartImporter, MUSTERI_TIPI

        importer = CariKartImporter(MUSTERI_TIPI, "Müşteri")
        rapor = importer.dogrula_satirlar([{"cari_kodu": "X"}], guncelleme_modu="guncelle")
        self.assertEqual(rapor.hatali, 1)


if __name__ == "__main__":
    unittest.main()
