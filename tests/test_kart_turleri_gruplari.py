"""Kart türleri / grupları kabul kontrolleri (K01–K16 özeti)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import database.models.kart_turu  # noqa: F401 — metadata
from database.kart_turu_service import KAPSAM_CARI, KAPSAM_STOK, KartTuruService
from database.session_manager import oturum
from tests.stok_test_ortami import StokOrtami


class KartTurleriTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ortam = StokOrtami("kart_tur")
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        cls._patch = patch("database.kart_turu_service.yazma_zorunlu")
        cls._patch.start()
        KartTuruService.schema_ve_seed()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        oturum.clear()
        cls.ortam.kapat()

    def test_k01_seed_tanimlar(self):
        stok = KartTuruService.ana_turleri_listele(KAPSAM_STOK)
        cari = KartTuruService.ana_turleri_listele(KAPSAM_CARI)
        self.assertTrue(any(a.ad == "Ham Madde" for a in stok))
        self.assertTrue(any(a.ad == "Paket Stok" for a in stok))
        self.assertTrue(any(a.ad == "Müşteri" for a in cari))
        self.assertTrue(any(a.ad == "Tedarikçi" for a in cari))
        sektor = KartTuruService.sektor_listele()
        adlar = {s["ad"] for s in sektor}
        self.assertIn("Mobilyacı", adlar)
        self.assertNotIn("Perakende Müşteri", adlar)
        self.assertNotIn("PERAKENDE MÜŞTERİ", adlar)

    def test_k02_musteri_alt_tur_ekle(self):
        musteri = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI) if a.kod == "MUSTERI")
        ad = "Test Alt Tur XYZ"
        mevcut = [x for x in KartTuruService.alt_turleri_listele(musteri.id, sadece_aktif=False) if x.ad == ad]
        if not mevcut:
            kayit = KartTuruService.alt_kaydet({"ana_tur_id": musteri.id, "ad": ad, "kod": "TEST_ALT_XYZ"})
            self.assertEqual(kayit.ana_tur_id, musteri.id)
        liste = KartTuruService.alt_turleri_listele(musteri.id)
        self.assertTrue(any(x.ad == ad for x in liste))

    def test_k03_alt_tur_yalniz_kendi_ana(self):
        ham = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_STOK) if a.kod == "HAM_MADDE")
        paket = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_STOK) if a.kod == "PAKET_STOK")
        ham_alt = KartTuruService.alt_turleri_listele(ham.id)
        paket_alt = KartTuruService.alt_turleri_listele(paket.id)
        ham_idler = {a.id for a in ham_alt}
        for a in paket_alt:
            self.assertNotIn(a.id, ham_idler)

    def test_k05_uyumsuz_alt_engelle(self):
        ham = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_STOK) if a.kod == "HAM_MADDE")
        paket = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_STOK) if a.kod == "PAKET_STOK")
        paket_altlar = KartTuruService.alt_turleri_listele(paket.id)
        if not paket_altlar:
            self.skipTest("Paket alt tür yok")
        ana_id, alt_id, uyari = KartTuruService.stok_tur_dogrula(ham.id, paket_altlar[0].id)
        self.assertEqual(ana_id, ham.id)
        self.assertIsNone(alt_id)
        self.assertTrue(uyari)

    def test_k11_perakende_alt_tur(self):
        musteri = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI) if a.kod == "MUSTERI")
        altlar = KartTuruService.alt_turleri_listele(musteri.id)
        self.assertTrue(any(a.ad == "Perakende Müşteri" for a in altlar))

    def test_k12_hizmet_tedarikci_alt(self):
        ted = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI) if a.kod == "TEDARIKCI")
        altlar = KartTuruService.alt_turleri_listele(ted.id)
        self.assertTrue(any(a.ad == "Hizmet Tedarikçisi" for a in altlar))
        ana_adlar = {a.ad for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI)}
        self.assertNotIn("Hizmet Tedarikçisi", ana_adlar)

    def test_k14_mukerrer_alt(self):
        musteri = next(a for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI) if a.kod == "MUSTERI")
        with self.assertRaises(ValueError):
            KartTuruService.alt_kaydet(
                {"ana_tur_id": musteri.id, "ad": "Perakende Müşteri", "kod": "PERAKENDE_MUSTERI_X"}
            )

    def test_k16_gecis_ikinci_kez(self):
        r1 = KartTuruService.gecis_calistir()
        r2 = KartTuruService.gecis_calistir()
        self.assertIsInstance(r1, dict)
        self.assertIsInstance(r2, dict)


if __name__ == "__main__":
    unittest.main()
