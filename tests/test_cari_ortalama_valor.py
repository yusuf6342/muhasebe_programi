"""Çift yönlü cari ortalama valör — T−V / P−V / FIFO sayısal testleri.

Çalıştırma: python -m unittest tests.test_cari_ortalama_valor -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.session_manager import oturum
from database.cari_ortalama_valor_service import (
    calculate_account_average_value_date,
    fifo_valor_paketi_hesapla,
    kapanan_valor_ortalama,
)
from database.cari_service import CariService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _mock_hareket(hid, tarih, belge, tutar, kalan=None):
    h = MagicMock()
    h.id = hid
    h.satis_tarihi = tarih
    h.belge_no = belge
    h.satis_tutari = Decimal(str(tutar))
    h.kalan_acik_tutar = Decimal(str(kalan if kalan is not None else tutar))
    return h


def _mock_islem(iid, tarih, belge, alacak=0, borc=0, tur="Tahsilat"):
    i = MagicMock()
    i.id = iid
    i.tarih = tarih
    i.belge_no = belge
    i.alacak = Decimal(str(alacak))
    i.borc = Decimal(str(borc))
    i.islem_turu = tur
    return i


class OrtalamaValorBirimTest(unittest.TestCase):
    """FIFO / ağırlıklı ortalama — DB'siz mock hareketler."""

    def test_00_acik_valor_T_eksi_I(self):
        """Açık valör = T − I (belge yaşı; talimat 13.11.2026).

        T=27.10.2026; SAF04090 I=19.08 → 69g; SAF06132 I=15.10 → 12g.
        (28800×69 + 33870×12) / 62670 ≈ 38,194.
        """
        referans = date(2026, 10, 27)
        hareketler = [
            _mock_hareket(1, date(2026, 8, 19), "SAF04090", 28800),
            _mock_hareket(2, date(2026, 10, 15), "SAF06132", 33870),
        ]
        vade_harita = {
            "SAF04090": date(2026, 9, 1),
            "SAF06132": date(2026, 10, 1),
        }
        _tam, acik, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler,
            [],
            cari_turu="Müşteri",
            vade_harita=vade_harita,
            referans=referans,
        )
        self.assertEqual(len(acik), 2)
        self.assertEqual(acik[0]["gun"], 69)  # T−I
        self.assertEqual(acik[1]["gun"], 12)
        self.assertEqual(acik[0]["yas_gun"], 69)
        self.assertEqual(acik[1]["yas_gun"], 12)
        self.assertEqual(acik[0]["vade_farki_gun"], 56)  # T−V ayrı
        self.assertEqual(acik[1]["vade_farki_gun"], 26)
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("62670"), acik, _al, referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 38.19, places=2)
        # Ağırlıklı ortalama belge tarihi (I)
        self.assertEqual(sonuc["ortalama_valor_tarihi"], date(2026, 9, 19))
        self.assertAlmostEqual(sonuc["ortalama_yas_gun"], 38.19, places=2)
        self.assertEqual(sonuc["olcu"], "acik_valor_T_eksi_I")

    def test_00b_vade_eksik_belge_tarihi_esas(self):
        """Özgün vade yoksa esas vade = belge tarihi; açık valör T−I (talimat 08.11.2026)."""
        referans = date(2026, 10, 27)
        hareketler = [
            _mock_hareket(1, date(2026, 8, 19), "SAF04090", 28800),
            _mock_hareket(2, date(2026, 10, 15), "SAF06132", 33870),
        ]
        _tam, acik, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler, [], cari_turu="Müşteri", vade_harita={}, referans=referans
        )
        self.assertTrue(all(d.get("vade_eksik") for d in acik))
        self.assertTrue(all(d.get("vade_kaynak") == "BELGE_TARIHI" for d in acik))
        self.assertTrue(all(d.get("gun") is not None for d in acik))
        self.assertFalse(any(d.get("valor_uygulanamaz") for d in acik))
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("62670"), acik, _al, referans)
        # Valör günü = belge yaşı (özgün vade olmadığı için)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 38.19, places=2)
        self.assertAlmostEqual(sonuc["ortalama_yas_gun"], 38.19, places=2)

    def test_00c_vade_yoksa_belge_tarihi_gecikme(self):
        """1 Kasım belgesi, vade boş → 11 Kasım’da 10 gün gecikmiş."""
        referans = date(2026, 11, 11)
        hareketler = [_mock_hareket(1, date(2026, 11, 1), "DK-1", 10000)]
        _tam, acik, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler, [], cari_turu="Müşteri", vade_harita={}, referans=referans
        )
        self.assertEqual(len(acik), 1)
        self.assertEqual(acik[0]["gun"], 10)  # T−I
        self.assertEqual(acik[0]["esas_vade"], date(2026, 11, 1))
        self.assertEqual(acik[0]["vade_kaynak"], "BELGE_TARIHI")
        # Vade 5 Kasım: açık valör hâlâ belge yaşı; vade farkı ayrı
        _tam2, acik2, _d2, _a2 = fifo_valor_paketi_hesapla(
            hareketler,
            [],
            cari_turu="Müşteri",
            vade_harita={"DK-1": date(2026, 11, 5)},
            referans=referans,
        )
        self.assertEqual(acik2[0]["gun"], 10)
        self.assertEqual(acik2[0]["vade_farki_gun"], 6)
        self.assertEqual(acik2[0]["vade_kaynak"], "VADE")

    def test_01_avans_valor_uygulanamaz_bekleme_yasi(self):
        """Müşteri avansı: sözleşmesel vade yok → valör None, bekleme yaşı T−I."""
        rapor = date(2026, 10, 13)
        islemler = [
            _mock_islem(1, date(2026, 10, 10), "THS-1", alacak=10000),
            _mock_islem(2, date(2026, 10, 20), "THS-2", alacak=5000),
        ]
        _tam, acik_b, _dil, acik_a = fifo_valor_paketi_hesapla(
            [], islemler, cari_turu="Müşteri", referans=rapor
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(len(acik_a), 2)
        self.assertTrue(all(d.get("valor_uygulanamaz") for d in acik_a))
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("-15000"), acik_b, acik_a, rapor)
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertIsNone(sonuc["ortalama_valor_gun"])
        self.assertIsNone(sonuc["ortalama_valor_tarihi"])
        # (10000×3 + 5000×(-7)) / 15000 = -0.333… → ağırlıklı yaş
        self.assertAlmostEqual(sonuc["ortalama_yas_gun"], -0.3333, delta=0.01)
        self.assertIn("avans", (sonuc.get("uyari") or "").casefold())

    def test_02_borc_valor_belge_yasi(self):
        """Borçlu: açık valör T−I (belge yaşı)."""
        referans = date(2026, 10, 20)
        hareketler = [
            _mock_hareket(1, date(2026, 10, 1), "SF-1", 1000),
            _mock_hareket(2, date(2026, 10, 10), "SF-2", 2000),
        ]
        vade = {
            "SF-1": date(2026, 10, 1),
            "SF-2": date(2026, 10, 10),
        }
        _tam, acik, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler, [], cari_turu="Müşteri", vade_harita=vade, referans=referans
        )
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("3000"), acik, _al, referans)
        self.assertEqual(sonuc["valor_turu"], "BORC")
        # 1000*19 + 2000*10 = 39000 / 3000 = 13
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 13.0, places=4)

    def test_03_tam_kapanan_acik_haric(self):
        hareketler = [_mock_hareket(1, date(2026, 9, 1), "SF-1", 500)]
        islemler = [_mock_islem(1, date(2026, 9, 15), "THS-1", alacak=500)]
        vade = {"SF-1": date(2026, 9, 10)}
        _tam, acik_b, dilimler, acik_a = fifo_valor_paketi_hesapla(
            hareketler,
            islemler,
            cari_turu="Müşteri",
            vade_harita=vade,
            referans=date(2026, 10, 1),
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(acik_a, [])
        self.assertTrue(dilimler)
        self.assertEqual(dilimler[0]["kapanan_valor_gun"], 14)  # P−I: 15.09−01.09
        self.assertEqual(dilimler[0]["odeme_suresi_gun"], 14)
        self.assertEqual(dilimler[0]["vade_farki_gun"], 5)  # P−V: 15.09−10.09

    def test_04_kismi_odeme_kalan_agirlik_ve_kapanan_dilim(self):
        hareketler = [_mock_hareket(1, date(2026, 10, 1), "SF-1", 1000)]
        islemler = [_mock_islem(1, date(2026, 10, 5), "THS-1", alacak=400)]
        vade = {"SF-1": date(2026, 10, 1)}
        _tam, acik_b, dilimler, _al = fifo_valor_paketi_hesapla(
            hareketler,
            islemler,
            cari_turu="Müşteri",
            vade_harita=vade,
            referans=date(2026, 10, 11),
        )
        self.assertEqual(len(acik_b), 1)
        self.assertEqual(acik_b[0]["tutar"], Decimal("600.00"))
        self.assertEqual(acik_b[0]["gun"], 10)  # T−I (belge 01.10, ref 11.10)
        self.assertEqual(dilimler[0]["tutar"], Decimal("400.00"))
        self.assertEqual(dilimler[0]["kapanan_valor_gun"], 4)  # P−I (V=I)

    def test_05_bakiye_sifir_valor_yok(self):
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("0"), [], [], date(2026, 10, 1))
        self.assertEqual(sonuc["valor_turu"], "YOK")
        self.assertIsNone(sonuc["ortalama_valor_tarihi"])
        self.assertIsNone(sonuc["ortalama_valor_gun"])

    def test_06_fifo_belge_no_sirasi_liste_bagimsiz(self):
        """Aynı tarihte belge_no sırası; girdi listesi sırası sonucu değiştirmez."""
        h1 = [
            _mock_hareket(2, date(2026, 10, 1), "SF-B", 100),
            _mock_hareket(1, date(2026, 10, 1), "SF-A", 100),
        ]
        h2 = list(reversed(h1))
        islem = [_mock_islem(1, date(2026, 10, 2), "THS-1", alacak=100)]
        r1 = fifo_valor_paketi_hesapla(h1, islem, cari_turu="Müşteri", referans=date(2026, 10, 5))
        r2 = fifo_valor_paketi_hesapla(h2, islem, cari_turu="Müşteri", referans=date(2026, 10, 5))
        # SF-A (belge_no) önce kapanır → açık kalan SF-B
        self.assertEqual(r1[1][0]["borc_belge_no"], "SF-B")
        self.assertEqual(r2[1][0]["borc_belge_no"], "SF-B")
        self.assertEqual(r1[1][0]["tutar"], r2[1][0]["tutar"])

    def test_06b_fifo_artan_odeme_siradaki_kaleme(self):
        """Ödeme önce en eskiyi kapatır; artan sıradakine geçer."""
        hareketler = [
            _mock_hareket(1, date(2026, 9, 1), "SF-1", 300),
            _mock_hareket(2, date(2026, 9, 10), "SF-2", 500),
        ]
        islemler = [_mock_islem(1, date(2026, 9, 20), "THS-1", alacak=400)]
        vade = {"SF-1": date(2026, 9, 5), "SF-2": date(2026, 9, 15)}
        _tam, acik, dilimler, _a = fifo_valor_paketi_hesapla(
            hareketler,
            islemler,
            cari_turu="Müşteri",
            vade_harita=vade,
            referans=date(2026, 10, 1),
        )
        self.assertEqual(len(dilimler), 2)
        self.assertEqual(dilimler[0]["borc_belge_no"], "SF-1")
        self.assertEqual(dilimler[0]["tutar"], Decimal("300.00"))
        self.assertEqual(dilimler[1]["borc_belge_no"], "SF-2")
        self.assertEqual(dilimler[1]["tutar"], Decimal("100.00"))
        self.assertEqual(acik[0]["borc_belge_no"], "SF-2")
        self.assertEqual(acik[0]["tutar"], Decimal("400.00"))

    def test_07_odeme_fazlasi_avans(self):
        hareketler = [_mock_hareket(1, date(2026, 10, 1), "SF-1", 100)]
        islemler = [_mock_islem(1, date(2026, 10, 5), "THS-1", alacak=250)]
        _tam, acik_b, _d, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=date(2026, 10, 10)
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(len(acik_a), 1)
        self.assertEqual(acik_a[0]["tutar"], Decimal("150.00"))
        self.assertEqual(acik_a[0]["kalem_turu"], "AVANS")

    def test_07b_kapanan_valor_ortalama_P_eksi_I(self):
        """İki dilim P−I: 300@20g + 100@5g → (6000+500)/400 = 16,25."""
        dilimler = [
            {
                "tutar": Decimal("300"),
                "kapanan_valor_gun": 20,
                "vade_farki_gun": 5,
                "odeme_tarihi": date(2026, 9, 20),
                "borc_tarihi": date(2026, 8, 31),
            },
            {
                "tutar": Decimal("100"),
                "kapanan_valor_gun": 5,
                "vade_farki_gun": -2,
                "odeme_tarihi": date(2026, 9, 20),
                "borc_tarihi": date(2026, 9, 15),
            },
        ]
        ozet = kapanan_valor_ortalama(dilimler)
        self.assertAlmostEqual(ozet["odenen_ortalama_valor_gun"], 16.25, places=2)
        self.assertEqual(ozet["olcu"], "kapanan_valor_P_eksi_I")
        self.assertAlmostEqual(ozet["ortalama_odeme_suresi_gun"], 16.25, places=2)
        self.assertAlmostEqual(ozet["ortalama_vade_farki_gun"], 3.25, places=2)

    def test_07c_net_bakiye_acik_esitlik(self):
        """Açık borç − açık alacak = net (FIFO sonrası)."""
        hareketler = [
            _mock_hareket(1, date(2026, 9, 1), "SF-1", 1000),
            _mock_hareket(2, date(2026, 9, 5), "SF-2", 400),
        ]
        islemler = [
            _mock_islem(1, date(2026, 9, 10), "THS-1", alacak=600),
            _mock_islem(2, date(2026, 9, 12), "THS-2", alacak=200),
        ]
        _tam, acik_b, _d, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=date(2026, 10, 1)
        )
        acik_borc = sum((Decimal(str(d["tutar"])) for d in acik_b), Decimal("0"))
        acik_alacak = sum((Decimal(str(d["tutar"])) for d in acik_a), Decimal("0"))
        net = Decimal("1400") - Decimal("800")
        self.assertEqual(acik_borc - acik_alacak, net)

    def test_07d_devir_cari_islem_ile_kalan(self):
        """Devir CariIslem'de; avans+satış sonrası kalan SAF06333."""
        referans = date(2026, 10, 30)
        from database.cari_ortalama_valor_service import _sonuc_olustur

        hareketler = [
            _mock_hareket(1, date(2026, 10, 20), "SAF06289", 2000),
            _mock_hareket(2, date(2026, 10, 22), "SAF06333", 2520),
        ]
        islemler = [
            _mock_islem(10, date(2025, 9, 2), "EVB-DEVIR-1195", borc=305.99, alacak=0, tur="Devir"),
            _mock_islem(11, date(2026, 6, 13), "EVB-BN-12791", alacak=2000),
            _mock_islem(12, date(2026, 10, 22), "EVB-BN-21241", alacak=2000),
            _mock_islem(13, date(2026, 10, 22), "EVB-BN-21242", alacak=617),
            _mock_islem(14, date(2026, 10, 20), "SAF06289", borc=2000, tur="Satış"),
            _mock_islem(15, date(2026, 10, 22), "SAF06333", borc=2520, tur="Satış"),
        ]
        vade = {"SAF06289": date(2026, 10, 20), "SAF06333": date(2026, 10, 22)}
        bakiye = Decimal("208.99")
        _tam, acik_b, _d, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", vade_harita=vade, referans=referans
        )
        sonuc = _sonuc_olustur(bakiye, acik_b, acik_a, referans)
        self.assertEqual(sonuc["valor_turu"], "BORC")
        self.assertEqual(sonuc["toplam_acik_tutar"], Decimal("208.99"))
        self.assertEqual(sonuc["acik_kalemler"][0]["borc_belge_no"], "SAF06333")
        self.assertEqual(sonuc["ortalama_valor_gun"], 8.0)  # T−V

    def test_07e_ayni_belge_yetim_sh_oncesi_kapanir(self):
        """Aynı belgedeki yetim SH borç, CI alacağıyla önce kapanır (0 gün)."""
        referans = date(2026, 11, 8)
        hareketler = [
            _mock_hareket(36, date(2026, 8, 21), "EVB-AK-7147-60060", "0.52", kalan="0"),
            _mock_hareket(100, date(2026, 10, 31), "SAF06697", "43.95"),
            _mock_hareket(101, date(2026, 11, 5), "SAF06830", "3350.00"),
        ]
        islemler = [
            _mock_islem(
                36,
                date(2026, 8, 21),
                "EVB-AK-7147-60060",
                alacak="44.48",
                borc=0,
                tur="Açılış",
            ),
        ]
        _tam, acik_b, dilimler, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=referans
        )
        ayni = [
            d
            for d in dilimler
            if d.get("borc_belge_no") == "EVB-AK-7147-60060"
            and d.get("odeme_belge_no") == "EVB-AK-7147-60060"
        ]
        self.assertEqual(len(ayni), 1)
        self.assertEqual(ayni[0]["tutar"], Decimal("0.52"))
        self.assertEqual(ayni[0]["kapanan_valor_gun"], 0)
        self.assertEqual(ayni[0]["yontem"], "AYNI_BELGE")
        acik_borc = sum((Decimal(str(d["tutar"])) for d in acik_b), Decimal("0"))
        acik_alacak = sum((Decimal(str(d["tutar"])) for d in acik_a), Decimal("0"))
        # 0.52 aynı belgede kapandı; kalan alacak 43.96 → net 3349.99
        self.assertEqual(acik_borc - acik_alacak, Decimal("3349.99"))
        self.assertEqual(acik_alacak, Decimal("43.96"))

    def test_07f_kismi_kapama_acik_ve_kapanan_valor(self):
        """01.11 1000 borç; 06.11 400 + 11.11 200 kapama → 13.11 açık 400@12g, kapanan 6,67g."""
        referans = date(2026, 11, 13)
        hareketler = [_mock_hareket(1, date(2026, 11, 1), "SF-K", 1000)]
        islemler = [
            _mock_islem(1, date(2026, 11, 6), "THS-A", alacak=400),
            _mock_islem(2, date(2026, 11, 11), "THS-B", alacak=200),
        ]
        _tam, acik_b, dilimler, _a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=referans
        )
        self.assertEqual(acik_b[0]["tutar"], Decimal("400.00"))
        self.assertEqual(acik_b[0]["gun"], 12)
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("400"), acik_b, _a, referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 12.0, places=2)
        ozet = kapanan_valor_ortalama(dilimler)
        # (400×5 + 200×10) / 600 = 6.666…
        self.assertAlmostEqual(ozet["odenen_ortalama_valor_gun"], 6.6666, places=2)
        self.assertEqual(ozet["kapanan_tutar"], Decimal("600.00"))

    def test_07g_ayni_gun_kapama_sifir_gun(self):
        hareketler = [_mock_hareket(1, date(2026, 11, 10), "SF-Z", 500)]
        islemler = [_mock_islem(1, date(2026, 11, 10), "THS-Z", alacak=500)]
        _tam, acik_b, dilimler, _a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=date(2026, 11, 13)
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(dilimler[0]["kapanan_valor_gun"], 0)
        self.assertEqual(kapanan_valor_ortalama(dilimler)["odenen_ortalama_valor_gun"], 0.0)

    def test_07h_acilis_sh_ve_ci_cift_sayilmaz(self):
        """Açılış hem SH hem CI borçta → tek kez kuyruğa girer (ABERRA tipi)."""
        referans = date(2026, 11, 13)
        hareketler = [
            _mock_hareket(1, date(2026, 9, 1), "EVB-AK-DEV", 10000),
            _mock_hareket(2, date(2026, 11, 10), "SAF-YENI", 5000),
        ]
        islemler = [
            _mock_islem(1, date(2026, 9, 1), "EVB-AK-DEV", borc=10000, tur="Açılış"),
            _mock_islem(2, date(2026, 10, 1), "THS-1", alacak=3000),
        ]
        _tam, acik_b, dilimler, _a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=referans
        )
        acik = sum((Decimal(str(d["tutar"])) for d in acik_b), Decimal("0"))
        kap = sum((Decimal(str(d["tutar"])) for d in dilimler), Decimal("0"))
        self.assertEqual(acik + kap, Decimal("15000.00"))
        self.assertEqual(acik, Decimal("12000.00"))
        self.assertEqual(dilimler[0]["borc_belge_no"], "EVB-AK-DEV")


class OrtalamaValorDbTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "valor.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.kart_turu  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="VAL", unvan="Valor Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="VAL",
            firma_unvan="Valor",
            firma_uid="val",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        with get_session() as s:
            from database.models.satis_faturasi import SatisFaturasi

            m = Cari(
                cari_kodu="M-HAKAN",
                unvan="Hakan Çevik",
                cari_turu="Müşteri",
                aktif=True,
            )
            t = Cari(
                cari_kodu="T-ALACAK",
                unvan="Alacaklı Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            m2 = Cari(
                cari_kodu="M-BORC",
                unvan="Borçlu Müşteri",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add_all([m, t, m2])
            s.flush()
            self.alacakli_id = int(m.id)
            self.tedarikci_id = int(t.id)
            self.borclu_id = int(m2.id)
            s.add(
                CariIslem(
                    cari_id=m.id,
                    tarih=date(2026, 10, 10),
                    islem_turu="Açılış",
                    belge_no="ACL-H1",
                    borc=Decimal("0"),
                    alacak=Decimal("10000"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=m.id,
                    tarih=date(2026, 10, 20),
                    islem_turu="Tahsilat",
                    belge_no="THS-H2",
                    borc=Decimal("0"),
                    alacak=Decimal("5000"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=t.id,
                    tarih=date(2026, 9, 1),
                    islem_turu="Ödeme",
                    belge_no="ODM-T1",
                    borc=Decimal("0"),
                    alacak=Decimal("800"),
                )
            )
            s.add(
                SatisHareketi(
                    cari_id=m2.id,
                    satis_tarihi=date(2026, 10, 1),
                    belge_no="SF-B1",
                    satis_tutari=Decimal("1200"),
                    kalan_acik_tutar=Decimal("1200"),
                )
            )
            s.add(
                SatisFaturasi(
                    fatura_no="SF-B1",
                    fatura_tarihi=date(2026, 10, 1),
                    vade_tarihi=date(2026, 10, 15),
                    cari_id=m2.id,
                    tl_genel_toplam=Decimal("1200"),
                )
            )
            s.commit()

    def tearDown(self):
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_08_hakan_avans_valor_yok_yas_var(self):
        rapor = date(2026, 10, 13)
        sonuc = calculate_account_average_value_date(
            self.alacakli_id, rapor_tarihi=rapor
        )
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertEqual(sonuc["valor_turu"], "ALACAK")
        self.assertIsNone(sonuc["ortalama_valor_gun"])
        self.assertIsNotNone(sonuc["ortalama_yas_gun"])
        metrik = CariService.kart_ozet_metrikleri(self.alacakli_id, rapor_tarihi=rapor)
        self.assertEqual(metrik["valor_turu"], "ALACAK")
        self.assertIsNone(metrik["bakiye_ortalama_valor_gun"])

    def test_09_tedarikci_avans_valor(self):
        sonuc = calculate_account_average_value_date(
            self.tedarikci_id, rapor_tarihi=date(2026, 9, 11)
        )
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertIsNone(sonuc["ortalama_valor_gun"])
        self.assertIsNotNone(sonuc["ortalama_yas_gun"])

    def test_10_borclu_kart_ozet_T_eksi_I(self):
        metrik = CariService.kart_ozet_metrikleri(
            self.borclu_id, rapor_tarihi=date(2026, 10, 20)
        )
        self.assertEqual(metrik["bakiye_yonu"], "BORCLU")
        self.assertEqual(metrik["valor_turu"], "BORC")
        # T=20.10, I=01.10 → 19 gün açık valör (belge yaşı)
        self.assertAlmostEqual(float(metrik["bakiye_ortalama_valor_gun"]), 19.0, places=4)
        self.assertAlmostEqual(float(metrik["ortalama_yas_gun"]), 19.0, places=4)

    def test_13_musteri_fifo_baglantisiz_8_62(self):
        """Talimat: 1000@30.10 + 2000@06.11 − 400 tahsilat → valör 8,62."""
        referans = date(2026, 11, 13)
        hareketler = [
            _mock_hareket(1, date(2026, 10, 30), "SF-1", 1000),
            _mock_hareket(2, date(2026, 11, 6), "SF-2", 2000),
        ]
        islemler = [_mock_islem(1, date(2026, 11, 13), "THS-1", alacak=400)]
        _tam, acik, _d, _a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=referans
        )
        from database.cari_ortalama_valor_service import _sonuc_olustur

        self.assertEqual(acik[0]["tutar"], Decimal("600.00"))
        self.assertEqual(acik[1]["tutar"], Decimal("2000.00"))
        sonuc = _sonuc_olustur(Decimal("2600"), acik, _a, referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 8.62, places=2)

    def test_14_musteri_baglantili_tahsilat_9_69(self):
        """Aynı tahsilat 2. faturaya bağlıysa valör 9,69."""
        referans = date(2026, 11, 13)
        # Manuel bağ: 400 doğrudan SF-2'ye → kalan 1000 + 1600
        acik = [
            {
                "borc_belge_no": "SF-1",
                "borc_tarihi": date(2026, 10, 30),
                "tutar": Decimal("1000.00"),
                "gun": 14,
                "yas_gun": 14,
                "kalem_turu": "FATURA",
            },
            {
                "borc_belge_no": "SF-2",
                "borc_tarihi": date(2026, 11, 6),
                "tutar": Decimal("1600.00"),
                "gun": 7,
                "yas_gun": 7,
                "kalem_turu": "FATURA",
            },
        ]
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("2600"), acik, [], referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 9.69, places=2)

    def test_15_tedarikci_negatif_alis_fifo(self):
        """Tedarikçi negatif SH + ödeme → açık alış belge yaşı."""
        referans = date(2026, 11, 13)
        hareketler = [
            _mock_hareket(1, date(2026, 10, 30), "AF-1", -19046.70),
            _mock_hareket(2, date(2026, 11, 6), "AF-2", -21024.50),
            _mock_hareket(3, date(2026, 11, 13), "AF-3", -3771.46),
        ]
        islemler = [
            _mock_islem(1, date(2026, 11, 13), "ODM-1", borc=1710.25, tur="Ödeme"),
        ]
        _tam, acik_b, dil, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Tedarikçi", referans=referans
        )
        self.assertEqual(acik_b, [])
        fatura = [d for d in acik_a if d.get("kalem_turu") == "FATURA"]
        self.assertEqual(len(fatura), 3)
        self.assertEqual(fatura[0]["tutar"], Decimal("17336.45"))
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("-42132.41"), [], acik_a, referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 9.25, places=2)

    def test_16b_kapanan_valor_p_kucuk_i_sifir(self):
        """Açılış tarihi < DEVIREN belge tarihi → kapanan P−I = 0 (negatif değil)."""
        referans = date(2026, 11, 17)
        hareketler = [_mock_hareket(1, date(2026, 8, 31), "DEV", -10000)]
        # Tedarikçi: negatif SH = alış; açılış BORÇ erken tarih
        islemler = [
            _mock_islem(1, date(2026, 8, 31), "DEV", alacak=10000, tur="AÇILIŞ"),
            _mock_islem(2, date(2026, 6, 16), "AK-1", borc=10000, tur="Açılış"),
        ]
        # DEV pozitif SH yok; CI alacak kuyruk + açılış borc
        hareketler = []  # yalnız CI
        _tam, acik_b, dilimler, acik_a = fifo_valor_paketi_hesapla(
            [_mock_hareket(99, date(2026, 8, 31), "DEV", 1)],  # pozitif SH atlanır
            [
                _mock_islem(1, date(2026, 8, 31), "DEV", alacak=10000, tur="AÇILIŞ"),
                _mock_islem(2, date(2026, 6, 16), "AK-1", borc=10000, tur="Açılış"),
            ],
            cari_turu="Tedarikçi",
            referans=referans,
        )
        self.assertTrue(dilimler)
        self.assertTrue(dilimler[0].get("kapanan_valor_haric"))
        self.assertEqual(dilimler[0]["kalem_turu"], "ACILIS_AKTARIM")
        self.assertEqual(dilimler[0]["odeme_tarihi"], date(2026, 6, 16))
        self.assertEqual(dilimler[0]["borc_tarihi"], date(2026, 8, 31))
        oz = kapanan_valor_ortalama(dilimler)
        # Teknik açılış pay/paydada yok → kapanan valör yok
        self.assertIsNone(oz["odenen_ortalama_valor_gun"])
        self.assertEqual(oz["acilis_aktarim_haric_tutar"], Decimal("10000.00"))
        _ = (hareketler, islemler, acik_b, acik_a)

    def test_16_tedarikci_deviren_acilis_agirlikli_valor(self):
        """DEVIREN alacak + açılış BORÇ + ödemeler → açık valör tutar-ağırlıklı (T00073 tipi)."""
        referans = date(2026, 11, 17)
        hareketler = [
            _mock_hareket(6103, date(2026, 8, 31), "DEVIREN", 50751.86),  # pozitif SH yok sayılır
            _mock_hareket(1, date(2026, 10, 16), "AF-14302", -1306.89),
            _mock_hareket(2, date(2026, 11, 3), "AF-15099", -283.14),
            _mock_hareket(3, date(2026, 11, 13), "ARAY19", -9781.59),
        ]
        islemler = [
            _mock_islem(1, date(2026, 8, 31), "DEVIREN", alacak=50751.86, tur="AÇILIŞ"),
            _mock_islem(2, date(2026, 6, 16), "AK-1", borc=38040.07, tur="Açılış"),
            _mock_islem(3, date(2026, 11, 17), "OMK-90", borc=12711.79 + 880.06, tur="Ödeme"),
        ]
        # Basitleştirilmiş: açılış 38040,07 DEVIREN'i kısmen kapatır; kalan + faturalar − ödeme
        # Bu test tam T00073 değil; oturum motoru + ağırlıklı formül için duman.
        from database.cari_ortalama_valor_service import _sonuc_olustur

        acik = [
            {
                "borc_belge_no": "AF-14302",
                "borc_tarihi": date(2026, 10, 16),
                "alacak_belge_no": "AF-14302",
                "alacak_tarihi": date(2026, 10, 16),
                "tutar": Decimal("426.83"),
                "gun": 32,
                "yas_gun": 32,
                "kalem_turu": "FATURA",
                "yon": "ALACAK",
            },
            {
                "borc_belge_no": "AF-15099",
                "borc_tarihi": date(2026, 11, 3),
                "alacak_belge_no": "AF-15099",
                "alacak_tarihi": date(2026, 11, 3),
                "tutar": Decimal("283.14"),
                "gun": 14,
                "yas_gun": 14,
                "kalem_turu": "FATURA",
                "yon": "ALACAK",
            },
            {
                "borc_belge_no": "ARAY19",
                "borc_tarihi": date(2026, 11, 13),
                "alacak_belge_no": "ARAY19",
                "alacak_tarihi": date(2026, 11, 13),
                "tutar": Decimal("9781.59"),
                "gun": 4,
                "yas_gun": 4,
                "kalem_turu": "FATURA",
                "yon": "ALACAK",
            },
        ]
        # Avans yaşları karışırsa valör bozulmamalı
        avans = {
            "alacak_belge_no": "OMK-AV",
            "alacak_tarihi": date(2026, 9, 1),
            "tutar": Decimal("4000.00"),
            "gun": None,
            "yas_gun": 77,
            "valor_uygulanamaz": True,
            "kalem_turu": "AVANS",
            "yon": "ALACAK",
        }
        sonuc = _sonuc_olustur(Decimal("-10491.56"), [], acik + [avans], referans)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 5.41, places=2)
        self.assertEqual(sonuc["valor_dahil_tutar"], Decimal("10491.56"))
        _ = (hareketler, islemler)

    def test_11_tarihsel_kesim_sonraki_odeme_yok(self):
        """08.11 kesiminde 09.11 tahsilatı kapatma yaratmaz; 10.11'de kapatır."""
        from database.cari_ortalama_valor_service import fifo_valor_paketi_oturumdan

        with get_session() as s:
            s.add(
                CariIslem(
                    cari_id=self.borclu_id,
                    tarih=date(2026, 11, 9),
                    islem_turu="Tahsilat",
                    belge_no="THS-SONRA",
                    borc=Decimal("0"),
                    alacak=Decimal("1200"),
                )
            )
            s.commit()
            eski = fifo_valor_paketi_oturumdan(
                s, self.borclu_id, cari_turu="Müşteri", referans=date(2026, 11, 8)
            )
            yeni = fifo_valor_paketi_oturumdan(
                s, self.borclu_id, cari_turu="Müşteri", referans=date(2026, 11, 10)
            )
        self.assertEqual(len(eski[1]), 1)
        self.assertEqual(eski[1][0]["tutar"], Decimal("1200.00"))
        self.assertEqual(eski[2], [])  # 09.11 ödemesi 08.11'de yok
        # Açık valör = T−I (belge 01.10 → 08.11 = 38 gün)
        self.assertEqual(eski[1][0]["gun"], (date(2026, 11, 8) - date(2026, 10, 1)).days)
        self.assertEqual(yeni[1], [])
        self.assertTrue(yeni[2])
        # Kapanan valör = P−I (belge 01.10 → ödeme 09.11 = 39 gün)
        self.assertEqual(yeni[2][0]["kapanan_valor_gun"], (date(2026, 11, 9) - date(2026, 10, 1)).days)
        self.assertEqual(yeni[2][0]["vade_farki_gun"], (date(2026, 11, 9) - date(2026, 10, 15)).days)

    def test_12_firma_izolasyonu_ayri_cari(self):
        with get_session() as s:
            diger = Cari(
                cari_kodu="M-HAKAN-2",
                unvan="Başka Hakan",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(diger)
            s.flush()
            diger_id = int(diger.id)
            s.add(
                CariIslem(
                    cari_id=diger_id,
                    tarih=date(2026, 1, 1),
                    islem_turu="Tahsilat",
                    belge_no="THS-DIGER",
                    borc=Decimal("0"),
                    alacak=Decimal("99999"),
                )
            )
            s.commit()
        a = calculate_account_average_value_date(
            self.alacakli_id, rapor_tarihi=date(2026, 10, 20)
        )
        b = calculate_account_average_value_date(
            diger_id, rapor_tarihi=date(2026, 10, 20)
        )
        self.assertEqual(a["toplam_acik_tutar"], Decimal("15000.00"))
        self.assertEqual(b["toplam_acik_tutar"], Decimal("99999.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
