"""Alış fatura alt toplam — talimat örneği 0,43 TL / %20 KDV → 0,09 KDV / 0,52 genel."""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.alis_faturasi_service import AlisFaturasiService


class AlisAltToplamOrnekTest(unittest.TestCase):
    def test_043_yuzde_20(self):
        t = AlisFaturasiService.toplam(
            [
                {
                    "miktar": 1,
                    "birim_fiyat": Decimal("0.43"),
                    "iskonto_orani": 0,
                    "kdv_orani": 20,
                }
            ]
        )
        self.assertEqual(t["ara_toplam"], Decimal("0.43"))
        self.assertEqual(t["iskonto"], Decimal("0.00"))
        self.assertEqual(t["kdv"], Decimal("0.09"))
        self.assertEqual(t["genel_toplam"], Decimal("0.52"))


if __name__ == "__main__":
    unittest.main()
