"""Ekstre rapor verisi oturum kapandıktan sonra lazy-load gerektirmez."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class RaporVerisiDetachedTest(unittest.TestCase):
    def test_rapor_verisi_oturum_sonrasi_banka_lazy_yok(self):
        from database import kk_ekstre_rapor_service as mod

        kart = SimpleNamespace(
            id=7,
            kart_adi="TEST KART",
            kart_bankasi="Test Banka",
            banka_karti_id=3,
            para_birimi="TRY",
            son_dort_hane="1234",
            kart_numarasi=None,
            banka_karti=SimpleNamespace(banka_adi="Test Banka"),
        )
        ozet = {
            "toplam_borc": Decimal("100.00"),
            "kullanilan": Decimal("100.00"),
            "kesilmemis": Decimal("0"),
            "para_birimi": "TRY",
            "limit": None,
            "limit_tanimli": False,
            "kullanilabilir": None,
            "hesap_borc": Decimal("100.00"),
        }

        session = MagicMock()
        session.scalar.return_value = kart
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)

        with patch("database.database.get_session", return_value=session), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.schema_hazirla"
        ), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.kart_borc_ozeti",
            return_value=ozet,
        ), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.ekstreleri_hesapla",
            return_value=[],
        ), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.gelecek_donem_ozeti",
            return_value=[],
        ), patch(
            "database.finans_service.FinansService.kredi_karti_bekleyen_taksitler",
            return_value=[],
        ):
            rapor = mod.rapor_verisi(7, kesim_tarihi=None, rapor_tarihi=date(2026, 11, 18))

        self.assertEqual(rapor["kart_adi"], "TEST KART")
        self.assertEqual(rapor["banka_adi"], "Test Banka")
        self.assertEqual(rapor["maskeli_no"], "****1234")
        self.assertIn("hareketler", rapor)
        self.assertIn("gelecek_donemler", rapor)
        # Rapor ORM kartı taşımıyor
        self.assertNotIn("kart", rapor)


class TaksitHareketIsaretTest(unittest.TestCase):
    def test_kk_taksit_notr(self):
        from database.finans_service import FinansService

        self.assertEqual(FinansService.hareket_isareti("KK TAKSİT"), 0)
        self.assertEqual(FinansService.hareket_isareti("KK TAKSİT DETAY"), 0)
        self.assertEqual(FinansService.hareket_isareti("KK ÖDEME"), 1)


if __name__ == "__main__":
    unittest.main()
