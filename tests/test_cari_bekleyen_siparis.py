# -*- coding: utf-8 -*-
"""Smoke: bekleyen siparis hesaplama + import."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from database.cari_bekleyen_siparis_service import (
    _siparis_acik_mi,
    _satir_tutarlari,
    ornek_bekleyen_tutar,
)


class TestBekleyenHesap(unittest.TestCase):
    def test_talimat_ornek(self):
        r = ornek_bekleyen_tutar(10, 4, 1, 100)
        self.assertEqual(r["kalan_miktar"], Decimal("5"))
        self.assertEqual(r["kalan_tutar"], Decimal("500"))

    def test_satir_fatura_kalani_miktar(self):
        satir = SimpleNamespace(
            miktar=Decimal("10"),
            irsaliyelenen_miktar=Decimal("4"),
            faturalanan_miktar=Decimal("4"),
            birim_satis_fiyati=Decimal("100"),
            iskonto_orani=Decimal("0"),
            kdv_orani=Decimal("0"),
        )
        o = _satir_tutarlari(satir, fiyat_alani="birim_satis_fiyati")
        self.assertEqual(o["fatura_kalani"], Decimal("6"))
        self.assertEqual(o["kalan_tutar"], Decimal("600"))

    def test_taslak_acik_degil(self):
        self.assertFalse(_siparis_acik_mi("TASLAK", [{"fatura_kalani": Decimal("5")}]))
        self.assertFalse(_siparis_acik_mi("IPTAL", [{"fatura_kalani": Decimal("5")}] ))
        self.assertTrue(_siparis_acik_mi("ACIK", [{"fatura_kalani": Decimal("5")}]) or _siparis_acik_mi("AÇIK", [{"fatura_kalani": Decimal("5")}]))


if __name__ == "__main__":
    unittest.main()
