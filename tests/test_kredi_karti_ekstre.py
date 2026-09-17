"""Kredi kartı ekstre dönem / AXESS senaryo testleri."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from database.kredi_karti_ekstre_service import (
    DURUM_KISMI,
    DURUM_ODENDI,
    KrediKartiEkstreService,
    ay_gunu,
)


class AxessDonemTest(unittest.TestCase):
    """AXESS: kesim 7, ödeme 12."""

    def setUp(self):
        self.kart = {"hesap_kesim_gunu": 7, "son_odeme_gunu": 12}

    def test_1709_harcama_1210_odeme(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), self.kart)
        self.assertEqual(d["donem_baslangic"], date(2026, 9, 8))
        self.assertEqual(d["donem_bitis"], date(2026, 10, 7))
        self.assertEqual(d["kesim_tarihi"], date(2026, 10, 7))
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 10, 12))

    def test_kesim_gunu_ayni_ekstreye(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 10, 7), self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 10, 7))
        self.assertEqual(d["donem_baslangic"], date(2026, 9, 8))

    def test_kesim_sonrasi_sonraki_ekstre(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 10, 8), self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 11, 7))
        self.assertEqual(d["donem_baslangic"], date(2026, 10, 8))
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 11, 12))

    def test_onceki_donem_agustos(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 1), self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 9, 7))
        self.assertEqual(d["donem_baslangic"], date(2026, 8, 8))
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 9, 12))

    def test_ay_sonu_31(self):
        kart = {"hesap_kesim_gunu": 31, "son_odeme_gunu": 31}
        self.assertEqual(ay_gunu(2026, 4, 31), date(2026, 4, 30))
        self.assertEqual(ay_gunu(2026, 2, 31), date(2026, 2, 28))
        self.assertEqual(ay_gunu(2024, 2, 31), date(2024, 2, 29))
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 4, 15), kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 4, 30))
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 4, 30))

    def test_aralik_ocak_yil_gecisi(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 12, 20), self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2027, 1, 7))
        self.assertEqual(d["son_odeme_tarihi"], date(2027, 1, 12))

    def test_taksit_2_sonraki_donem(self):
        d1 = KrediKartiEkstreService.taksit_donem_bilgisi(
            date(2026, 9, 17), 1, self.kart
        )
        d2 = KrediKartiEkstreService.taksit_donem_bilgisi(
            date(2026, 9, 17), 2, self.kart
        )
        self.assertEqual(d1["son_odeme_tarihi"], date(2026, 10, 12))
        self.assertEqual(d2["kesim_tarihi"], date(2026, 11, 7))
        self.assertEqual(d2["son_odeme_tarihi"], date(2026, 11, 12))

    def test_farkli_kartlar_ayri_donem(self):
        bonus = {"hesap_kesim_gunu": 15, "son_odeme_gunu": 25}
        d_a = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), self.kart)
        d_b = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), bonus)
        self.assertEqual(d_a["son_odeme_tarihi"], date(2026, 10, 12))
        self.assertEqual(d_b["kesim_tarihi"], date(2026, 10, 15))
        self.assertEqual(d_b["son_odeme_tarihi"], date(2026, 10, 25))

    def test_obligation_key_tekil(self):
        k1 = KrediKartiEkstreService.obligation_key(5, date(2026, 10, 7))
        k2 = KrediKartiEkstreService.obligation_key(5, date(2026, 10, 7))
        k3 = KrediKartiEkstreService.obligation_key(5, date(2026, 11, 7))
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_durum_kismi_ve_odendi(self):
        self.assertEqual(
            KrediKartiEkstreService._durum_hesapla(
                Decimal("15000"),
                Decimal("5000"),
                date(2026, 10, 12),
                bugun=date(2026, 9, 20),
            ),
            DURUM_KISMI,
        )
        self.assertEqual(
            KrediKartiEkstreService._durum_hesapla(
                Decimal("15000"),
                Decimal("15000"),
                date(2026, 10, 12),
                bugun=date(2026, 10, 13),
            ),
            DURUM_ODENDI,
        )

    def test_kesimden_sonra_odeme_gun(self):
        kart = {"hesap_kesim_gunu": 7, "son_odeme_gunu": 12, "kesimden_sonra_odeme_gun": 5}
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), kart)
        # kesim 7.10 + 5 gün = 12.10
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 10, 12))


class EkstreRaporYansimaTest(unittest.TestCase):
    def test_odeme_ayi_ekim_degil_eylul(self):
        kart = {"hesap_kesim_gunu": 7, "son_odeme_gunu": 12}
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), kart)
        self.assertEqual(d["son_odeme_tarihi"].month, 10)
        self.assertNotEqual(d["son_odeme_tarihi"].month, 9)


if __name__ == "__main__":
    unittest.main()
