"""KK taksit planı: ilk vade çekimden bağımsız; ekstre kesim yazılır."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from database.finans_service import FinansService


class KkTaksitIlkVadeTest(unittest.TestCase):
    def test_ilk_taksit_cekimden_ayri(self):
        plan = FinansService.kk_taksit_plani(
            date(2026, 10, 19),
            3,
            Decimal("300.00"),
            ilk_taksit_tarihi=date(2026, 11, 8),
        )
        self.assertEqual([s["vade_tarihi"] for s in plan], [
            date(2026, 11, 8),
            date(2026, 12, 8),
            date(2027, 1, 8),
        ])
        self.assertEqual(sum((s["tutar"] for s in plan), Decimal("0")), Decimal("300.00"))

    def test_kart_kesim_ile_ekstre_yazilir(self):
        kart = SimpleNamespace(
            hesap_kesim_gunu=7,
            son_odeme_gunu=None,
            kesimden_sonra_odeme_gun=1,
            kart_adi="Test",
        )
        plan = FinansService.kk_taksit_plani(
            date(2026, 10, 19),
            2,
            Decimal("100.00"),
            kart=kart,
        )
        self.assertEqual(len(plan), 2)
        self.assertIsNotNone(plan[0].get("ekstre_kesim_tarihi"))
        self.assertEqual(plan[0]["ekstre_kesim_tarihi"], date(2026, 11, 7))
        self.assertEqual(plan[0]["vade_tarihi"], date(2026, 11, 8))


if __name__ == "__main__":
    unittest.main()
