"""Teslim Saati kısa giriş → HH:mm biçimlendirme."""

from __future__ import annotations

import unittest

from ui_takvim import saat_kisa_giris_coz


class SaatKisaGirisTest(unittest.TestCase):
    def test_ornekler(self):
        self.assertEqual(saat_kisa_giris_coz("16"), "16:00")
        self.assertEqual(saat_kisa_giris_coz("1643"), "16:43")
        self.assertEqual(saat_kisa_giris_coz("9"), "09:00")
        self.assertEqual(saat_kisa_giris_coz("930"), "09:30")
        self.assertEqual(saat_kisa_giris_coz("0905"), "09:05")
        self.assertEqual(saat_kisa_giris_coz("16:43"), "16:43")
        self.assertEqual(saat_kisa_giris_coz("00:00"), "00:00")
        self.assertEqual(saat_kisa_giris_coz("0"), "00:00")
        self.assertEqual(saat_kisa_giris_coz("2359"), "23:59")

    def test_bos_izinli(self):
        self.assertIsNone(saat_kisa_giris_coz(""))
        self.assertIsNone(saat_kisa_giris_coz("   "))
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("", bos_izinli=False)

    def test_gecersiz_aralik(self):
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("24")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("2460")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("2360")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("999")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("25:00")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("12:60")

    def test_gecersiz_bicim(self):
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("ab")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("12:30:00")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("12345")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz("16:")
        with self.assertRaises(ValueError):
            saat_kisa_giris_coz(":30")

    def test_gecersizi_baska_saate_cevirmez(self):
        # 2460 → 00:00 vb. yapılmamalı
        with self.assertRaises(ValueError) as ctx:
            saat_kisa_giris_coz("2460")
        self.assertIn("00–23", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
