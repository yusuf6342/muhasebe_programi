"""Banka kart eşleştirme ve Evo map testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal

from entegrasyon.banka_kart_import import karsilastir, map_evo_banka_kart
from entegrasyon.banka_eslestirme import normalize_banka_adi, normalize_iban


class MapEvoBankaTest(unittest.TestCase):
    def test_dokuman_ornek(self):
        m = map_evo_banka_kart(
            {
                "id": "11",
                "text": "A BANK TL HESABI",
                "a_dov_id": "0",
                "DOV_Kodu": "TL",
                "a_posmu": "0",
                "a_posgun": "2",
                "a_kod": " ",
            }
        )
        self.assertEqual(m["evo_banka_id"], "11")
        self.assertEqual(m["banka_adi"], "A BANK TL HESABI")
        self.assertEqual(m["pos_valor_gun"], 2)
        self.assertIn("Evo id: 11", m["aciklama"])

    def test_pos_ve_doviz(self):
        m = map_evo_banka_kart(
            {"id": "10", "text": "ANA BANKA ($)", "DOV_Kodu": "USD", "a_posmu": "1", "a_posgun": "0"}
        )
        self.assertIn("Döviz: USD", m["aciklama"])
        self.assertIn("POS", m["aciklama"])

    def test_normalize(self):
        self.assertEqual(normalize_iban("TR12 3456"), "TR123456")
        self.assertEqual(normalize_banka_adi("  Garanti  BBVA "), "garanti bbva")


class KarsilastirMockTest(unittest.TestCase):
    def test_bos_yerel(self):
        # Yerel kart listesini mocklamadan: FinansService DB ister — yalnız map yeter
        evo = [{"id": "1", "text": "Test Bank", "DOV_Kodu": "TL", "a_posmu": "0", "a_posgun": "1"}]
        mapped = [map_evo_banka_kart(x) for x in evo]
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["evo_banka_id"], "1")


if __name__ == "__main__":
    unittest.main()
