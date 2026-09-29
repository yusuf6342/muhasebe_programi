"""Ödeme sözleri: kalan hesabı, geçmiş, durumlar, bağlantı sınırları, iptal geri alma (geçici test veritabanı)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import CariIslem, SatisHareketi
from database.odeme_sozu_service import (
    ALINAN,
    D_BUGUN,
    D_ERTELENDI,
    D_GECIKTI,
    D_IPTAL,
    D_KISMEN,
    D_TAMAM,
    D_YAKLASIYOR,
    VERILEN,
    OdemeSozuService,
)
from tests import test_tahsilat_makbuzu as _servis_testi

D = Decimal
BUGUN = date.today()


class OdemeSozuTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        OdemeSozuService._hazir_motor = None

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def _soz(self, tutar="20000", *, cari=None, yon=ALINAN, vade=None, pb="TRY", faturalar=()):
        return OdemeSozuService.olustur(
            {"cari_id": cari or self.musteri_id, "yon": yon, "soz_tarihi": BUGUN,
             "vade_tarihi": vade or BUGUN + timedelta(days=10), "tutar": tutar, "para_birimi": pb,
             "yontem": "Havale/EFT", "gorusulen_kisi": "Ali Bey", "sorumlu": "admin", "aciklama": "Telefon"},
            faturalar,
        )

    def _makbuz(self, tutar, *, cari=None, odeme=False):
        veri = {
            "tarih": BUGUN, "cari_id": cari or self.musteri_id, "makbuz_no_otomatik": True,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": tutar}],
        }
        return (FinansService.kasa_odeme_makbuzu_kaydet if odeme else FinansService.kasa_tahsilat_makbuzu_kaydet)(veri)

    def _bagla(self, soz_id, makbuz, tutar, **ek):
        return OdemeSozuService.baglanti_ekle(
            soz_id, evrak_turu="Tahsilat Makbuzu", evrak_belge_no=makbuz.belge_no, tutar=tutar,
            evrak_tutari=makbuz.tutar, evrak_id=makbuz.id, **ek,
        )

    def test_kismi_karsilama_ve_mali_etki_yok(self):
        with get_session() as s:
            onceki_hareket = len(s.scalars(select(CariIslem)).all())
            onceki_acik = len(s.scalars(select(SatisHareketi)).all())
        sid = self._soz("20000")
        with get_session() as s:
            self.assertEqual(len(s.scalars(select(CariIslem)).all()), onceki_hareket)
            self.assertEqual(len(s.scalars(select(SatisHareketi)).all()), onceki_acik)
        m = self._makbuz("8000")
        self._bagla(sid, m, "8000")
        s = OdemeSozuService.getir(sid)
        self.assertEqual((s["gerceklesen"], s["kalan"]), (D("8000.00"), D("12000.00")))
        self.assertIn(D_KISMEN, s["etiketler"])
        self.assertEqual(s["gecmis"][0]["islem"], "OLUSTURMA")
        self.assertEqual(s["gecmis"][-1]["islem"], "BAGLANTI")

    def test_erteleme_gecmisi_ve_durum(self):
        sid = self._soz(vade=BUGUN - timedelta(days=2))
        self.assertEqual(OdemeSozuService.getir(sid)["durum"], D_GECIKTI)
        self.assertEqual(OdemeSozuService.getir(sid)["gecikme_gunu"], 2)
        with self.assertRaises(ValueError):
            OdemeSozuService.ertele(sid, BUGUN + timedelta(days=5), "")
        OdemeSozuService.ertele(sid, BUGUN + timedelta(days=2), "Müşteri tahsilatı gecikti")
        s = OdemeSozuService.getir(sid)
        self.assertEqual(s["durum"], D_YAKLASIYOR)
        self.assertIn(D_ERTELENDI, s["etiketler"])
        g = s["gecmis"][-1]
        self.assertEqual((g["islem"], g["kullanici"], g["aciklama"]), ("ERTELEME", "admin", "Müşteri tahsilatı gecikti"))
        self.assertEqual(g["eski"], f"{BUGUN - timedelta(days=2):%d.%m.%Y}")

    def test_bugun_ve_esik_ayari(self):
        sid = self._soz(vade=BUGUN)
        self.assertEqual(OdemeSozuService.getir(sid)["durum"], D_BUGUN)
        uzak = self._soz(vade=BUGUN + timedelta(days=5))
        self.assertNotEqual(OdemeSozuService.getir(uzak)["durum"], D_YAKLASIYOR)
        OdemeSozuService.esik_gun_ayarla(7)
        self.assertEqual(OdemeSozuService.getir(uzak)["durum"], D_YAKLASIYOR)

    def test_iptal_ve_elle_tamamlama(self):
        sid = self._soz()
        with self.assertRaises(ValueError):
            OdemeSozuService.iptal_et(sid, " ")
        OdemeSozuService.iptal_et(sid, "Müşteri vazgeçti")
        s = OdemeSozuService.getir(sid)
        self.assertEqual((s["durum"], s["kalan"]), (D_IPTAL, D("0")))
        with self.assertRaises(ValueError):
            OdemeSozuService.ertele(sid, BUGUN + timedelta(days=3), "x")
        t = self._soz("500")
        OdemeSozuService.elle_tamamla(t, "Nakit elden alındı, evrak ayrı kesildi")
        s = OdemeSozuService.getir(t)
        self.assertEqual((s["durum"], s["kalan"], s["gerceklesen"]), (D_TAMAM, D("0"), D("0.00")))
        self.assertEqual(s["gecmis"][-1]["islem"], "DUZELTME")

    def test_tam_karsilama_tamamlandi(self):
        sid = self._soz("1000")
        m = self._makbuz("1000")
        self._bagla(sid, m, "1000")
        self.assertEqual(OdemeSozuService.getir(sid)["durum"], D_TAMAM)
        self.assertEqual(OdemeSozuService.acik_sozler(self.musteri_id, ALINAN), [])

    def test_bagla_sinirlari_ve_coklu_dagitim(self):
        a = self._soz("3000")
        b = self._soz("5000")
        m = self._makbuz("6000")
        with self.assertRaises(ValueError):
            self._bagla(a, m, "3500")
        self._bagla(a, m, "3000")
        self._bagla(b, m, "3000")
        with self.assertRaises(ValueError):
            self._bagla(b, m, "1")
        self.assertEqual(OdemeSozuService.getir(a)["durum"], D_TAMAM)
        self.assertEqual(OdemeSozuService.getir(b)["kalan"], D("2000.00"))
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_guncelle(m.id, {
                "tarih": BUGUN, "cari_id": self.musteri_id,
                "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "5000"}],
            })

    def test_makbuz_iptali_baglantiyi_geri_alir(self):
        sid = self._soz("20000")
        m = self._makbuz("8000")
        self._bagla(sid, m, "8000")
        FinansService.kasa_makbuz_iptal(m.id)
        s = OdemeSozuService.getir(sid)
        self.assertEqual((s["gerceklesen"], s["kalan"]), (D("0.00"), D("20000.00")))
        self.assertTrue(s["baglantilar"][0]["iptal"])
        self.assertEqual(s["gecmis"][-1]["islem"], "BAGLANTI_IPTAL")

    def test_soz_faturayi_kapatmaz(self):
        with get_session() as s:
            s.add(SatisHareketi(cari_id=self.musteri_id, satis_tarihi=BUGUN, belge_no="SF-S-1",
                                satis_tutari=D("2000"), kalan_acik_tutar=D("2000")))
        sid = self._soz("2000", faturalar=[("SF-S-1", "2000")])
        OdemeSozuService.elle_tamamla(sid, "Test")
        with get_session() as s:
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-S-1"))
            self.assertEqual(D(str(h.kalan_acik_tutar)), D("2000.00"))
        with self.assertRaises(ValueError):
            self._soz("100", faturalar=[("SF-S-1", "200")])

    def test_iki_yon_ve_dovizler_ayri(self):
        self._soz("1000", vade=BUGUN)
        self._soz("300", pb="USD", vade=BUGUN)
        self._soz("700", cari=self.tedarikci_id, yon=VERILEN, vade=BUGUN)
        self._soz("400", cari=self.tedarikci_id, yon=VERILEN, vade=BUGUN - timedelta(days=1))
        oz = OdemeSozuService.takvim_ozeti()
        self.assertEqual(oz["bugun_giris"], {"TRY": D("1000.00"), "USD": D("300.00")})
        self.assertEqual(oz["bugun_cikis"], {"TRY": D("700.00")})
        self.assertEqual(oz["geciken_tedarikci"], {"TRY": D("400.00")})
        self.assertEqual(oz["geciken_musteri"], {})
        self.assertEqual(oz["araliklar"][7]["giris"], {"TRY": D("1000.00"), "USD": D("300.00")})
        self.assertEqual(oz["araliklar"][30]["cikis"], {"TRY": D("1100.00")})
        m = self._makbuz("100")
        usd = OdemeSozuService.acik_sozler(self.musteri_id, ALINAN, "USD")[0]["id"]
        with self.assertRaises(ValueError):
            self._bagla(usd, m, "100")
        self.assertIn("Tahmini", oz["not"])

    def test_ayni_caride_iki_yon(self):
        self._soz("1000", yon=ALINAN)
        self._soz("600", yon=VERILEN)
        self.assertEqual(len(OdemeSozuService.liste(cari_id=self.musteri_id, yon=ALINAN)), 1)
        self.assertEqual(len(OdemeSozuService.liste(cari_id=self.musteri_id, yon=VERILEN)), 1)
        self.assertEqual(OdemeSozuService.cari_ozeti(self.musteri_id)["acik_adet"], 2)

    def test_faturasiz_soz_ve_sonradan_baglama(self):
        sid = self._soz("1500")
        self.assertEqual(OdemeSozuService.getir(sid)["faturalar"], [])
        m = self._makbuz("1000")
        bilgi = OdemeSozuService.evrak_bilgisi(m.belge_no, self.musteri_id)
        self.assertEqual((bilgi["tutar"], bilgi["evrak_turu"]), (D("1000.00"), "Tahsilat Makbuzu"))
        self.assertIsNone(OdemeSozuService.evrak_bilgisi(m.belge_no, self.tedarikci_id))
        self._bagla(sid, m, "1000", sonradan=True)
        self.assertEqual(OdemeSozuService.getir(sid)["kalan"], D("500.00"))

    def test_tutar_yontem_not_gecmisi_ve_csv(self):
        sid = self._soz("1000")
        m = self._makbuz("400")
        self._bagla(sid, m, "400")
        with self.assertRaises(ValueError):
            OdemeSozuService.tutar_degistir(sid, "300", "Azalt")
        OdemeSozuService.tutar_degistir(sid, "800", "Anlaşma güncellendi")
        OdemeSozuService.yontem_degistir(sid, "Çek", "Çek verecek")
        OdemeSozuService.gorusme_notu(sid, "Yarın ara", hatirlat_tarihi=BUGUN)
        s = OdemeSozuService.getir(sid)
        self.assertEqual([g["islem"] for g in s["gecmis"]],
                         ["OLUSTURMA", "BAGLANTI", "TUTAR", "YONTEM", "GORUSME"])
        self.assertEqual((s["kalan"], s["yontem"], s["son_not"]), (D("400.00"), "Çek", "Yarın ara"))
        self.assertEqual(len(OdemeSozuService.hatirlatmalar()), 1)
        self.assertIn("söz takip bekliyor", OdemeSozuService.hatirlatma_metni())
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / "s.csv"
            OdemeSozuService.csv_yaz(OdemeSozuService.liste(), str(yol))
            self.assertIn("Çek", yol.read_text(encoding="utf-8-sig"))

    def test_merkez_filtreleri(self):
        self._soz("1000", vade=BUGUN + timedelta(days=3))
        self._soz("2000", vade=BUGUN + timedelta(days=20))
        self._soz("500", cari=self.tedarikci_id, yon=VERILEN, vade=BUGUN + timedelta(days=3))
        self.assertEqual(len(OdemeSozuService.liste(vade_bit=BUGUN + timedelta(days=7))), 2)
        self.assertEqual(len(OdemeSozuService.liste(yon=VERILEN)), 1)
        self.assertEqual(len(OdemeSozuService.liste(durum=D_YAKLASIYOR)), 2)
        self.assertEqual(len(OdemeSozuService.liste(sorumlu="adm")), 3)
        self.assertEqual(len(OdemeSozuService.liste(yontem="Nakit")), 0)


if __name__ == "__main__":
    unittest.main()
