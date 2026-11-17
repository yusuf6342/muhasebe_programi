"""Pasif cari varsayılan filtre + işlemsiz silme / kaynak engel."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from database.cari_service import CariService
from database.cari_silme_service import (
    KAYNAK_EVO,
    cari_kaynak_engelli_mi,
    eslestirme_gerekli_mesaji,
)


class DurumFiltreNormTest(unittest.TestCase):
    def test_aktif_pasif_tumu(self):
        self.assertEqual(CariService._durum_filtre_norm("Aktif"), "Aktif")
        self.assertEqual(CariService._durum_filtre_norm("aktif"), "Aktif")
        self.assertEqual(CariService._durum_filtre_norm("Pasif"), "Pasif")
        self.assertEqual(CariService._durum_filtre_norm("Tümü"), "Tümü")
        self.assertEqual(CariService._durum_filtre_norm(None), "Tümü")
        self.assertEqual(CariService._durum_filtre_norm(""), "Tümü")


class EngelMesajTest(unittest.TestCase):
    def test_eslestirme_mesaji(self):
        m = eslestirme_gerekli_mesaji("3066", "DECOREVİM")
        self.assertIn("3066", m)
        self.assertIn("eşleştirme", m.casefold())


class SoftSilMesajTest(unittest.TestCase):
    def test_neden_metni_ornek_format(self):
        from database.cari_silme_service import CariSilmeDurumu

        d = CariSilmeDurumu(
            cari_id=1,
            silinebilir=False,
            nedenler=["2 satış faturası kaydı var; silinemez.", "1 cari işlem kaydı var; silinemez."],
        )
        self.assertIn("silinemez", d.neden_metni)
        self.assertIn("2 satış faturası", d.neden_metni)


if __name__ == "__main__":
    unittest.main()
