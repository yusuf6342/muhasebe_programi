"""A4 fatura yazdırma — birim testler."""

from __future__ import annotations

import unittest
from decimal import Decimal

from invoice_print.amount_to_words import amount_to_words
from invoice_print.builder import build_from_satirlar, calculate_page_breaks
from invoice_print.html_renderer import render_invoice_html
from invoice_print.view_model import InvoicePrintLine


class AmountToWordsTest(unittest.TestCase):
    def test_tl(self):
        y = amount_to_words(Decimal("1234.56"), "TRY")
        self.assertIn("Bin İki Yüz Otuz Dört", y)
        self.assertIn("Türk Lirası", y)
        self.assertIn("Elli Altı", y)
        self.assertTrue(y.startswith("Yalnız"))

    def test_sifir_kurus(self):
        y = amount_to_words(Decimal("100"), "TRY")
        self.assertIn("Yüz Türk Lirası", y)
        self.assertNotIn("Kuruş", y)

    def test_usd(self):
        y = amount_to_words(Decimal("10.5"), "USD")
        self.assertIn("Amerikan Doları", y)


class PageBreakTest(unittest.TestCase):
    def test_cok_sayfa(self):
        satirlar = [
            InvoicePrintLine(sira=i, urun_kodu=f"U{i}", urun_adi=f"Ürün {i}")
            for i in range(1, 40)
        ]
        sayfalar = calculate_page_breaks(
            satirlar, {"ilk_sayfa_satir": 12, "sonraki_sayfa_satir": 22}
        )
        self.assertEqual(len(sayfalar), 3)
        self.assertEqual(len(sayfalar[0]), 12)
        self.assertEqual(len(sayfalar[1]), 22)
        self.assertEqual(len(sayfalar[2]), 5)


class BuildAndHtmlTest(unittest.TestCase):
    def test_tek_satir_html(self):
        vm = build_from_satirlar(
            fatura_id=1,
            fatura_no="SF-00001",
            fatura_tarihi=__import__("datetime").date(2026, 9, 16),
            islem_saati="14:00",
            vade_tarihi=__import__("datetime").date(2026, 10, 16),
            vade_gunu=30,
            depo="ANA DEPO",
            para_birimi="TRY",
            kur=1,
            kur_tarihi=None,
            durum="TASLAK",
            onaylandi=False,
            aciklama="Test not",
            satirlar_dict=[
                {
                    "urun_kodu": "URN1",
                    "urun_adi": "Test Ürün Çöğün",
                    "miktar": 2,
                    "birim": "AD",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": 0,
                    "iskonto_orani_2": 0,
                    "iskonto_orani_3": 0,
                    "kdv_orani": 20,
                }
            ],
            musteri={
                "cari_kodu": "C001",
                "unvan": "Test Müşteri",
                "vergi_dairesi": "Kadıköy",
                "vergi_no": "123",
                "adres": "Adres satırı",
            },
            tahsilat_tutari=0,
        )
        self.assertEqual(vm.filigran, "TASLAKTIR – MALİ BELGE DEĞİLDİR")
        self.assertEqual(vm.genel_toplam, Decimal("240.00"))
        html = render_invoice_html(vm, toolbar=False)
        self.assertIn("SATIŞ FATURASI", html)
        self.assertIn("SF-00001", html)
        self.assertIn("Test Ürün", html)
        self.assertIn("240,00", html)
        self.assertIn("TASLAKTIR", html)
        self.assertIn("@page", html)
        self.assertIn("210mm", html)


if __name__ == "__main__":
    unittest.main()
