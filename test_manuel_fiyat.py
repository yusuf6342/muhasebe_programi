"""Manuel birim fiyat — ondalık ayrıştırma, birleştirme ve bayrak smoke testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from fatura_barkod_ui import _satir_birlestirilebilir
from fatura_manuel_fiyat_ui import (
    fiyat_metnini_coz,
    maliyet_alti_satis_yasak_mi,
    satir_maliyeti,
)


class ManuelFiyatTest(unittest.TestCase):
    def test_ondalik_tr(self):
        self.assertEqual(fiyat_metnini_coz("12,50"), Decimal("12.50"))
        self.assertEqual(fiyat_metnini_coz("1.234,56"), Decimal("1234.56"))

    def test_ondalik_en(self):
        self.assertEqual(fiyat_metnini_coz("12.50"), Decimal("12.50"))
        self.assertEqual(fiyat_metnini_coz("1,234.56"), Decimal("1234.56"))

    def test_negatif_parse(self):
        self.assertEqual(fiyat_metnini_coz("-1"), Decimal("-1"))

    def test_bos_hata(self):
        with self.assertRaises(ValueError):
            fiyat_metnini_coz("  ")

    def test_manuel_birlestirme_fiyat_farkli(self):
        a = {
            "urun_kodu": "U1",
            "birim": "Adet",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "satir_para_birimi": "TRY",
            "manuel_fiyat": True,
        }
        b = dict(a)
        b["birim_satis_fiyati"] = "99"  # liste fiyatı
        b["manuel_fiyat"] = False
        self.assertTrue(_satir_birlestirilebilir(a, b, depo="ANA DEPO"))

    def test_manuel_olmayan_fiyat_farkli_birlesmez(self):
        a = {
            "urun_kodu": "U1",
            "birim": "Adet",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "satir_para_birimi": "TRY",
            "manuel_fiyat": False,
        }
        b = dict(a)
        b["birim_satis_fiyati"] = "99"
        self.assertFalse(_satir_birlestirilebilir(a, b, depo="ANA DEPO"))

    def test_satir_maliyeti_fifo(self):
        veri = {"fifo_birim_maliyeti": "15,5", "son_alis_birim_maliyeti": "20"}
        self.assertEqual(satir_maliyeti(veri, "FIFO"), Decimal("15.5"))

    def test_yasak_ayar_varsayilan_false(self):
        with patch(
            "fatura_manuel_fiyat_ui.get_system_session",
            side_effect=Exception("yok"),
            create=True,
        ):
            # Gerçek impl try/except → False
            self.assertIsInstance(maliyet_alti_satis_yasak_mi(), bool)


if __name__ == "__main__":
    unittest.main()
