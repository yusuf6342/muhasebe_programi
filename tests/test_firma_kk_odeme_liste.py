"""Firma kredi kartıyla ödeme: liste filtresi, tek kimlik, taksit planı toplamı."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.finans_service import FinansService


class FirmaKkOdemeListeTest(unittest.TestCase):
    def test_taksit_plani_50000_4_toplam_esit(self):
        plan = FinansService.kk_taksit_plani(date(2026, 11, 11), 4, Decimal("50000.00"))
        self.assertEqual(len(plan), 4)
        self.assertEqual(sum((p["tutar"] for p in plan), Decimal("0")), Decimal("50000.00"))
        self.assertEqual(plan[0]["taksit_no"], 1)
        self.assertEqual(plan[3]["taksit_no"], 4)

    def test_sekil_normalize_eski_ad(self):
        from kasa_makbuz_ui import (
            ODEME_HAVALE_SEKLI,
            ODEME_MAKBUZ_SEKILLERI,
            ODEME_NAKIT_SEKLI,
            SIRKET_KARTI_SEKLI,
            TAHSILAT_MAKBUZ_SEKILLERI,
            _odeme_sekil_normalize,
            _sekil_turu,
        )

        self.assertEqual(_odeme_sekil_normalize("ŞİRKET KREDİ KARTI"), SIRKET_KARTI_SEKLI)
        self.assertEqual(_odeme_sekil_normalize("Firma Kredi Kartıyla Ödeme"), SIRKET_KARTI_SEKLI)
        self.assertEqual(_odeme_sekil_normalize("GÖNDERİLEN HAVALE"), ODEME_HAVALE_SEKLI)
        self.assertEqual(_odeme_sekil_normalize("NAKİT / KASA"), ODEME_NAKIT_SEKLI)
        self.assertEqual(_sekil_turu(SIRKET_KARTI_SEKLI), "KART")
        self.assertEqual(_sekil_turu(ODEME_HAVALE_SEKLI), "HAVALE")
        self.assertEqual(_sekil_turu(ODEME_NAKIT_SEKLI), "KASA")
        # Ödeme menüsünde tahsilat şekilleri yok
        for yasak in ("GELEN HAVALE", "KREDİ KARTIYLA TAHSİLAT"):
            self.assertNotIn(yasak, ODEME_MAKBUZ_SEKILLERI)
            self.assertIn(yasak, TAHSILAT_MAKBUZ_SEKILLERI)

    def test_odeme_hesaplari_pos_ve_kk_karismaz(self):
        from kasa_makbuz_ui import ODEME_HAVALE_SEKLI, ODEME_NAKIT_SEKLI, SIRKET_KARTI_SEKLI

        # Firma kartı şekli finans hesabı döndürmez (UI tanım listesi kullanır)
        self.assertEqual(FinansService.odeme_hesaplari(SIRKET_KARTI_SEKLI), [])
        for h in FinansService.odeme_hesaplari(ODEME_NAKIT_SEKLI):
            self.assertEqual((h.hesap_turu or "").upper(), "KASA")
        for h in FinansService.odeme_hesaplari(ODEME_HAVALE_SEKLI):
            self.assertIn((h.alt_hesap_turu or "").upper(), ("MEVDUAT", "KMH"))


if __name__ == "__main__":
    unittest.main()
