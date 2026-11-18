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

    def test_taksit_kesimi_vade_sizintisini_yoksayar(self):
        """Kayıtlı ekstre_kesim vade ise (kart kesim gününe uymaz) dönem kurala göre birleşir."""
        kart = {"hesap_kesim_gunu": 30, "kesimden_sonra_odeme_gun": 10}
        odeme = SimpleNamespace(tarih=date(2026, 11, 2))
        # Eski aktarım: vade 02.12 → ekstre_kesim yazılmış
        t_a = SimpleNamespace(taksit_no=1, ekstre_kesim_tarihi=date(2026, 12, 2))
        t_b = SimpleNamespace(taksit_no=1, ekstre_kesim_tarihi=date(2026, 12, 4))
        d_a = KrediKartiEkstreService.taksit_kesimi(odeme, t_a, kart)
        d_b = KrediKartiEkstreService.taksit_kesimi(
            SimpleNamespace(tarih=date(2026, 11, 4)), t_b, kart
        )
        self.assertEqual(d_a["kesim_tarihi"], date(2026, 11, 30))
        self.assertEqual(d_a["son_odeme_tarihi"], date(2026, 12, 10))
        self.assertEqual(d_b["kesim_tarihi"], date(2026, 11, 30))
        self.assertEqual(d_a["kesim_tarihi"], d_b["kesim_tarihi"])

    def test_taksit_kesimi_gecerli_kayitli_kesimi_korur(self):
        kart = {"hesap_kesim_gunu": 30, "kesimden_sonra_odeme_gun": 10}
        odeme = SimpleNamespace(tarih=date(2026, 10, 5))
        t = SimpleNamespace(taksit_no=1, ekstre_kesim_tarihi=date(2026, 10, 30))
        d = KrediKartiEkstreService.taksit_kesimi(odeme, t, kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 10, 30))
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 11, 9))

    def test_sahte_kesimi_duzelt_son_odeme_penceresi(self):
        kart = {"hesap_kesim_gunu": 30, "kesimden_sonra_odeme_gun": 10}
        # 02.12 vade → 30.11 kesim / 10.12 son ödeme penceresine düşer
        self.assertEqual(
            KrediKartiEkstreService.sahte_kesimi_duzelt(date(2026, 12, 2), kart),
            date(2026, 11, 30),
        )


class EkstreRaporYansimaTest(unittest.TestCase):
    def test_odeme_ayi_ekim_degil_eylul(self):
        kart = {"hesap_kesim_gunu": 7, "son_odeme_gunu": 12}
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 9, 17), kart)
        self.assertEqual(d["son_odeme_tarihi"].month, 10)
        self.assertNotEqual(d["son_odeme_tarihi"].month, 9)


class KesimGunOnDonemSinirTest(unittest.TestCase):
    """Kesim günü 10 — kullanıcı tablosu: önceki+1 .. yeni kesim (dahil)."""

    def setUp(self):
        self.kart = {"hesap_kesim_gunu": 10, "kesimden_sonra_odeme_gun": 5}

    def test_donem_araliklari_kesintisiz(self):
        from datetime import timedelta

        beklenen = [
            (date(2026, 10, 10), date(2026, 9, 11), date(2026, 10, 10)),
            (date(2026, 11, 10), date(2026, 10, 11), date(2026, 11, 10)),
            (date(2026, 12, 10), date(2026, 11, 11), date(2026, 12, 10)),
            (date(2027, 1, 10), date(2026, 12, 11), date(2027, 1, 10)),
        ]
        onceki_bitis = None
        for kesim, bas, bit in beklenen:
            d = KrediKartiEkstreService.kesim_donemi(kesim, self.kart)
            self.assertEqual(d["donem_baslangic"], bas)
            self.assertEqual(d["donem_bitis"], bit)
            self.assertEqual(d["kesim_tarihi"], kesim)
            if onceki_bitis is not None:
                self.assertEqual(d["donem_baslangic"], onceki_bitis + timedelta(days=1))
            onceki_bitis = bit

    def test_1010_1110_1011_1111_hareket_sinirlari(self):
        d_1010 = KrediKartiEkstreService.donem_bilgisi(date(2026, 10, 10), self.kart)
        d_1110 = KrediKartiEkstreService.donem_bilgisi(date(2026, 10, 11), self.kart)
        d_1011 = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 10), self.kart)
        d_1111 = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 11), self.kart)
        # 10.10 → 10.10'da kapanan
        self.assertEqual(d_1010["kesim_tarihi"], date(2026, 10, 10))
        self.assertEqual((d_1010["donem_baslangic"], d_1010["donem_bitis"]),
                         (date(2026, 9, 11), date(2026, 10, 10)))
        # 11.10 → sonraki (11.10–10.11)
        self.assertEqual(d_1110["kesim_tarihi"], date(2026, 11, 10))
        self.assertEqual((d_1110["donem_baslangic"], d_1110["donem_bitis"]),
                         (date(2026, 10, 11), date(2026, 11, 10)))
        # 10.11 → 10.11'de kapanan (11.10 ile aynı ekstre)
        self.assertEqual(d_1011["kesim_tarihi"], date(2026, 11, 10))
        self.assertEqual(d_1011["kesim_tarihi"], d_1110["kesim_tarihi"])
        # 11.11 → sonraki (11.11–10.12)
        self.assertEqual(d_1111["kesim_tarihi"], date(2026, 12, 10))
        self.assertEqual((d_1111["donem_baslangic"], d_1111["donem_bitis"]),
                         (date(2026, 11, 11), date(2026, 12, 10)))

    def test_tek_doneme_dahil_cift_sayim_yok(self):
        from datetime import timedelta

        tarihler = [
            date(2026, 10, 10), date(2026, 10, 11),
            date(2026, 11, 10), date(2026, 11, 11),
            date(2026, 12, 10), date(2026, 12, 11),
            date(2027, 1, 10), date(2027, 1, 11),
        ]
        for t in tarihler:
            d = KrediKartiEkstreService.donem_bilgisi(t, self.kart)
            self.assertLessEqual(d["donem_baslangic"], t)
            self.assertLessEqual(t, d["donem_bitis"])
        # Komşu dönemler bitişik, örtüşmez
        for kesim in (date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)):
            a = KrediKartiEkstreService.kesim_donemi(kesim, self.kart)
            b = KrediKartiEkstreService.kesim_donemi(
                KrediKartiEkstreService.kesim_ay_sonra(kesim, 1, self.kart), self.kart
            )
            self.assertEqual(b["donem_baslangic"], a["donem_bitis"] + timedelta(days=1))
            self.assertLess(a["donem_bitis"], b["donem_baslangic"])

    def test_rapor_son_odeme_ayinda(self):
        d = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 10), self.kart)
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 11, 15))
        self.assertEqual(d["son_odeme_tarihi"].month, 11)

    def test_kayitli_erken_kesim_takvime_doner(self):
        """Takvimden önceki geçerli kayıtlı kesim yok sayılır (sınır taşması önlenir)."""
        odeme = SimpleNamespace(tarih=date(2026, 11, 11))
        t = SimpleNamespace(
            taksit_no=1, ekstre_kesim_tarihi=date(2026, 11, 10), vade_tarihi=None
        )
        d = KrediKartiEkstreService.taksit_kesimi(odeme, t, self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 12, 10))
        self.assertEqual(d["donem_baslangic"], date(2026, 11, 11))


class Kesim16YansimaTest(unittest.TestCase):
    """Kesim günü 16 — kullanıcı örneği + yansıma tarihi dönemi belirler."""

    def setUp(self):
        self.kart = {"hesap_kesim_gunu": 16, "son_odeme_gunu": 26}

    def test_kasim_aralik_ocak_donemleri(self):
        kasim = KrediKartiEkstreService.donem_bilgisi(date(2026, 10, 20), self.kart)
        self.assertEqual(kasim["donem_baslangic"], date(2026, 10, 17))
        self.assertEqual(kasim["kesim_tarihi"], date(2026, 11, 16))
        aralik = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 17), self.kart)
        self.assertEqual(aralik["donem_baslangic"], date(2026, 11, 17))
        self.assertEqual(aralik["kesim_tarihi"], date(2026, 12, 16))
        ocak = KrediKartiEkstreService.donem_bilgisi(date(2026, 12, 17), self.kart)
        self.assertEqual(ocak["donem_baslangic"], date(2026, 12, 17))
        self.assertEqual(ocak["kesim_tarihi"], date(2027, 1, 16))

    def test_kesim_gunu_dahil_ertesi_sonraki(self):
        a = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 16), self.kart)
        b = KrediKartiEkstreService.donem_bilgisi(date(2026, 11, 17), self.kart)
        self.assertEqual(a["kesim_tarihi"], date(2026, 11, 16))
        self.assertEqual(b["kesim_tarihi"], date(2026, 12, 16))

    def test_taksit_kesimi_yansima_tarihine_gore(self):
        odeme = SimpleNamespace(tarih=date(2026, 5, 1))  # eski çekim
        t = SimpleNamespace(
            taksit_no=6,
            vade_tarihi=date(2026, 10, 19),
            ekstre_kesim_tarihi=None,
        )
        d = KrediKartiEkstreService.taksit_kesimi(odeme, t, self.kart)
        self.assertEqual(d["kesim_tarihi"], date(2026, 11, 16))
        self.assertEqual(d["donem_baslangic"], date(2026, 10, 17))
        # Son ödeme dönemi kaydırmaz
        self.assertEqual(d["son_odeme_tarihi"], date(2026, 11, 26))


if __name__ == "__main__":
    unittest.main()
