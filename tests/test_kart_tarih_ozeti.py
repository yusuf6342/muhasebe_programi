"""Firma KK listesi: son/sonraki kesim ve son ödeme GG.AA.YYYY."""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from database.kredi_karti_ekstre_service import KrediKartiEkstreService


class KartTarihOzetiTest(unittest.TestCase):
    def test_doc5_ornek_20_ekim(self):
        # Kesim günü 18; 20.10.2026 → son 18.10, sonraki 18.11 (planlanan), son ödeme 28.10
        kart = SimpleNamespace(
            hesap_kesim_gunu=18,
            son_odeme_gunu=28,
            kesimden_sonra_odeme_gun=None,
            kart_adi="Test",
        )
        oz = KrediKartiEkstreService.kart_tarih_ozeti(kart, bugun=date(2026, 10, 20))
        self.assertEqual(oz["son_kesim"], date(2026, 10, 18))
        self.assertEqual(oz["sonraki_kesim"], date(2026, 11, 18))
        self.assertEqual(oz["son_odeme"], date(2026, 10, 28))
        self.assertIn("Planlanan", oz["sonraki_kesim_metin"])
        self.assertEqual(oz["son_kesim_metin"], "18.10.2026")

    def test_kesim_gunu_yok(self):
        kart = SimpleNamespace(
            hesap_kesim_gunu=None,
            son_odeme_gunu=None,
            kesimden_sonra_odeme_gun=None,
            kart_adi="X",
        )
        oz = KrediKartiEkstreService.kart_tarih_ozeti(kart)
        self.assertIsNone(oz["son_kesim"])
        self.assertEqual(oz["son_kesim_metin"], "—")


if __name__ == "__main__":
    unittest.main()
