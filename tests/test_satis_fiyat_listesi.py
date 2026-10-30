"""Satış fiyat listesi — listeye bağlı hesaplama ve seed."""

from decimal import Decimal
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ListeBagliHesapTest(unittest.TestCase):
    def test_110_iskonto_30_equals_77(self):
        from database.satis_fiyat_listesi_service import liste_bagli_satis_fiyati

        self.assertEqual(
            liste_bagli_satis_fiyati("110,00", "30"),
            Decimal("77.0000"),
        )

    def test_200_iskonto_30_equals_140(self):
        from database.satis_fiyat_listesi_service import liste_bagli_satis_fiyati

        self.assertEqual(
            liste_bagli_satis_fiyati("200", 30),
            Decimal("140.0000"),
        )

    def test_bos_liste_raises(self):
        from database.satis_fiyat_listesi_service import liste_bagli_satis_fiyati

        with self.assertRaises(ValueError):
            liste_bagli_satis_fiyati("", "30")

    def test_alis_iskonto_karismaz(self):
        """Satış iskontosu tek adım; alış ardışık formülü kullanılmaz."""
        from database.satis_fiyat_listesi_service import liste_bagli_satis_fiyati
        from database.stok_service import fabrika_fiyati_hesapla

        # Alış: 110, %30+%0+%0 → 77 (aynı sonuç tesadüfen) ama %10+%10+%10 farklı
        fabrika = fabrika_fiyati_hesapla("110", 10, 10, 10)
        satis = liste_bagli_satis_fiyati("110", "30")
        self.assertNotEqual(fabrika, satis)
        self.assertEqual(satis, Decimal("77.0000"))


if __name__ == "__main__":
    unittest.main()
