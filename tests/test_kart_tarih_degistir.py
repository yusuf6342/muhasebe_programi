"""Kart tarih kuralı ve ekstre son ödeme düzeltmesi — borç tutarına dokunmaz."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from database.kredi_karti_ekstre_service import KrediKartiEkstreService


class KartTarihDegistirTest(unittest.TestCase):
    def test_kart_tarih_ozeti_gg_aa_yyyy(self):
        kart = MagicMock()
        kart.hesap_kesim_gunu = 18
        kart.son_odeme_gunu = 28
        kart.kesimden_sonra_odeme_gun = None
        oz = KrediKartiEkstreService.kart_tarih_ozeti(kart, bugun=date(2026, 10, 20))
        self.assertRegex(oz["son_kesim_metin"], r"\d{2}\.\d{2}\.\d{4}")
        self.assertIn("18.11.2026", oz["sonraki_kesim_metin"])

    def test_ekstre_son_odeme_durum_yenilenir(self):
        """Manuel son ödeme sonrası durum yeni vadeye göre hesaplanır."""
        durum = KrediKartiEkstreService._durum_hesapla(
            Decimal("4000"),
            Decimal("0"),
            date(2026, 12, 5),
            bugun=date(2026, 12, 2),
            kesin=True,
        )
        self.assertNotEqual(durum, "GECIKMIS")

    @patch("database.kredi_karti_ekstre_service.yazma_zorunlu")
    @patch("database.kredi_karti_ekstre_service.get_session")
    def test_kurali_guncelle_gun_araligi(self, mock_session, _yz):
        kart = MagicMock()
        kart.id = 7
        kart.hesap_kesim_gunu = 18
        kart.son_odeme_gunu = 28
        kart.kesimden_sonra_odeme_gun = None
        kart.aciklama = ""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.get.return_value = kart
        mock_session.return_value = session
        with patch.object(
            KrediKartiEkstreService,
            "schema_hazirla",
        ), patch.object(
            KrediKartiEkstreService,
            "kart_tarih_ozeti",
            return_value={"son_kesim_metin": "18.10.2026"},
        ):
            sonuc = KrediKartiEkstreService.kart_tarih_kurali_guncelle(
                7,
                hesap_kesim_gunu="20",
                son_odeme_gunu="5",
                kesimden_sonra_odeme_gun="",
                neden="Banka bildirdi",
            )
        self.assertEqual(kart.hesap_kesim_gunu, 20)
        self.assertEqual(kart.son_odeme_gunu, 5)
        self.assertEqual(sonuc["kart_id"], 7)
        self.assertIn("Banka bildirdi", kart.aciklama)


if __name__ == "__main__":
    unittest.main()
