"""Satış kâr analizi formül testleri (talimat örnek A–D)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.satis_kar_analiz_service import degisim_hesapla, satir_brut_iskonto_net


class SatisKarAnalizFormulTest(unittest.TestCase):
    def test_ornek_a_kar_marji_ve_markup(self):
        net = Decimal("100")
        maliyet = Decimal("80")
        kar = net - maliyet
        marj = kar / net * Decimal("100")
        markup = kar / maliyet * Decimal("100")
        self.assertEqual(kar, Decimal("20"))
        self.assertEqual(marj, Decimal("20"))
        self.assertEqual(markup, Decimal("25"))

    def test_ornek_b_zarar(self):
        net = Decimal("80")
        maliyet = Decimal("100")
        kar = net - maliyet
        marj = kar / net * Decimal("100")
        markup = kar / maliyet * Decimal("100")
        self.assertEqual(kar, Decimal("-20"))
        self.assertEqual(marj, Decimal("-25"))
        self.assertEqual(markup, Decimal("-20"))

    def test_ornek_c_donem_degisim(self):
        d = degisim_hesapla(Decimal("150000"), Decimal("100000"))
        self.assertEqual(d["fark"], Decimal("50000"))
        self.assertEqual(d["degisim_yuzde"], Decimal("50.00"))
        self.assertEqual(d["yon"], "artış")

    def test_ornek_d_baz_yok(self):
        d = degisim_hesapla(Decimal("100"), Decimal("0"))
        self.assertIsNone(d["degisim_yuzde"])
        self.assertEqual(d["etiket"], "Yeni / Baz yok")
        d0 = degisim_hesapla(Decimal("0"), Decimal("0"))
        self.assertEqual(d0["degisim_yuzde"], Decimal("0"))

    def test_uc_kademeli_iskonto(self):
        brut, isk, net = satir_brut_iskonto_net(Decimal("10"), Decimal("100"), 10, 5, 0)
        self.assertEqual(brut, Decimal("1000"))
        # 1000 * 0.9 * 0.95 = 855
        self.assertEqual(net, Decimal("855"))
        self.assertEqual(isk, Decimal("145"))


if __name__ == "__main__":
    unittest.main()
