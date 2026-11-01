"""Satış faturası — müşteri satış vadesinin Vade Günü alanına getirilmesi."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from app import SatisFaturasiDialog


class SatisFaturaMusteriVadeTest(unittest.TestCase):
    def test_cari_satis_vade_none_vs_sifir(self):
        self.assertIsNone(SatisFaturasiDialog._cari_satis_vade_gunu(None))
        self.assertIsNone(
            SatisFaturasiDialog._cari_satis_vade_gunu(
                SimpleNamespace(satis_vade_gunu=None)
            )
        )
        self.assertEqual(
            SatisFaturasiDialog._cari_satis_vade_gunu(
                SimpleNamespace(satis_vade_gunu=0)
            ),
            0,
        )
        self.assertEqual(
            SatisFaturasiDialog._cari_satis_vade_gunu(
                SimpleNamespace(satis_vade_gunu=30)
            ),
            30,
        )
        self.assertEqual(
            SatisFaturasiDialog._cari_satis_vade_gunu(
                SimpleNamespace(satis_vade_gunu="45")
            ),
            45,
        )
        self.assertIsNone(
            SatisFaturasiDialog._cari_satis_vade_gunu(
                SimpleNamespace(satis_vade_gunu="")
            )
        )

    def test_vade_tarihi_takvim_gunu(self):
        # 01.11.2026 + 30 gün = 01.12.2026
        fatura = date(2026, 11, 1)
        self.assertEqual(fatura + timedelta(days=30), date(2026, 12, 1))
        # 0 gün = aynı gün
        self.assertEqual(fatura + timedelta(days=0), fatura)


if __name__ == "__main__":
    unittest.main()
