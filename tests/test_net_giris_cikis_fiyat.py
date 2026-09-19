"""Net giriş/çıkış birim fiyat — _net_birim smoke testleri.

Çalıştırma: python tests/test_net_giris_cikis_fiyat.py
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.fiyatli_stok_ekstresi_service import _net_birim


class NetBirimFiyatTest(unittest.TestCase):
    def test_iskonto_cascade(self):
        """10 adet, brüt 120, %10 iskonto → net birim 108."""
        satir = SimpleNamespace(
            birim_fiyat=Decimal("120"),
            tl_birim_fiyat=None,
            iskonto_orani=Decimal("10"),
            iskonto_orani_2=Decimal("0"),
            iskonto_orani_3=Decimal("0"),
            kdv_orani=Decimal("20"),
        )
        self.assertEqual(_net_birim(satir), Decimal("108.0000"))

    def test_tl_birim_iskonto_uygula(self):
        """tl_birim_fiyat varken de iskonto uygulanmalı."""
        satir = SimpleNamespace(
            birim_fiyat=Decimal("100"),
            tl_birim_fiyat=Decimal("200"),
            iskonto_orani=Decimal("10"),
            iskonto_orani_2=Decimal("0"),
            iskonto_orani_3=Decimal("0"),
            kdv_orani=Decimal("0"),
        )
        self.assertEqual(_net_birim(satir), Decimal("180.0000"))

    def test_sifir_fiyat(self):
        satir = SimpleNamespace(
            birim_fiyat=Decimal("0"),
            tl_birim_fiyat=Decimal("0"),
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=0,
        )
        self.assertEqual(_net_birim(satir), Decimal("0"))

    def test_kaynak_yok(self):
        self.assertIsNone(_net_birim(None))

    def test_satis_net_birim(self):
        """5 adet, satır birim 150 → net çıkış 150."""
        satir = SimpleNamespace(
            birim_fiyat=Decimal("150"),
            tl_birim_fiyat=None,
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=20,
        )
        self.assertEqual(_net_birim(satir), Decimal("150.0000"))


if __name__ == "__main__":
    unittest.main()
