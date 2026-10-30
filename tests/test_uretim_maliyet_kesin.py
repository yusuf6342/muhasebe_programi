"""Üretim maliyet kesinleştirme ve kısmi üretim mantığı (saf / hafif)."""

from __future__ import annotations

import unittest
from decimal import Decimal


class UretimMaliyetMantikTest(unittest.TestCase):
    def test_kismi_oran(self):
        plan = Decimal("100")
        hedef = Decimal("40")
        oran = (hedef / plan).quantize(Decimal("0.00000001"))
        self.assertEqual(oran, Decimal("0.40000000"))
        sarf_plan = Decimal("25")
        mik = (sarf_plan * oran).quantize(Decimal("0.0001"))
        self.assertEqual(mik, Decimal("10.0000"))

    def test_kesin_yalniz_kapali_gecici(self):
        for durum, maliyet, ok in (
            ("KAPALI", "GECICI", True),
            ("KAPALI", "KESIN", True),  # idempotent
            ("ACIK", "GECICI", False),
            ("KAPALI", "TAHMINI", True),
            ("IPTAL", "GECICI", False),
        ):
            izin = durum == "KAPALI" and maliyet in {"GECICI", "TAHMINI", "KESIN"}
            self.assertEqual(izin, ok, msg=f"{durum}/{maliyet}")


if __name__ == "__main__":
    unittest.main()
