"""Banka adı → logo eşlemesi (Finans → Bankalar)."""

from __future__ import annotations

import unittest

from bank_logo import logo_dosya_adi, logo_dizini, logo_yolu


class BankLogoEslemeTest(unittest.TestCase):
    def test_dizinde_pngler_var(self):
        d = logo_dizini()
        self.assertTrue(d.is_dir(), d)
        for ad in ("akbank.png", "yapikredi.png", "enpara_sirketim.png"):
            self.assertTrue((d / ad).is_file(), ad)

    def test_eslemeler(self):
        self.assertEqual(logo_dosya_adi("Akbank"), "akbank.png")
        self.assertEqual(logo_dosya_adi("Purlikit Akbank"), "akbank.png")
        self.assertEqual(logo_dosya_adi("PayTR Yapı Kredi"), "yapikredi.png")
        self.assertEqual(logo_dosya_adi("Yapı Kredi"), "yapikredi.png")
        self.assertEqual(logo_dosya_adi("Enpara Şirketim"), "enpara_sirketim.png")
        self.assertEqual(logo_dosya_adi("Enpara Mehmet Can"), "enpara.png")
        self.assertEqual(logo_dosya_adi("QNB"), "qnb.png")
        self.assertEqual(logo_dosya_adi("Rönesans Holding Hisse"), "ronesans.png")
        self.assertIsNone(logo_dosya_adi("RSÇ World"))
        self.assertIsNone(logo_dosya_adi("Bilinmeyen Banka XYZ"))

    def test_yol_akbank(self):
        self.assertIsNotNone(logo_yolu("Akbank"))


if __name__ == "__main__":
    unittest.main()
