"""Sabit gider ödeme planı: dönem üretimi, mükerrer önleme, bağlantı, tutar değişikliği, durdurma."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from tests.stok_test_ortami import StokOrtami

from database import sabit_gider_service as sg
from database.database import get_session
from database.models.cari import CariIslem
from database.models.finans import FinansHareketi, FinansHesabi
from database.models.hizmet_faturasi import HizmetFaturasi
from database.models.sabit_gider import SabitGiderDonemi

D = date(2026, 10, 10)


def _kira(**ek) -> dict:
    veri = {"kategori": "KIRA", "ad": "Dükkan kirası", "periyot": "AYLIK", "odeme_gunu": 31,
            "tutar": "20000", "baslangic_ay": "01.2026"}
    veri.update(ek)
    return veri


class SabitGiderTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("sabit_gider")
        with get_session() as s:
            h = FinansHesabi(hesap_adi="BANKA M", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT")
            s.add(h)
            s.flush()
            self.hesap_id = h.id

    def tearDown(self):
        self.ort.kapat()

    def _odeme(self, belge_no: str, tutar: str, tarih: date = D) -> None:
        with get_session() as s:
            s.add(FinansHareketi(hesap_id=self.hesap_id, tarih=tarih, hareket_turu="GÖNDERİLEN HAVALE",
                                 belge_no=belge_no, tutar=Decimal(tutar)))

    def _kalemler(self, tarih: date = D) -> list[dict]:
        with get_session() as s:
            return sg.takvim_kalemleri(s, tarih)

    def _donem(self, ay: int) -> dict:
        return next(k for k in self._kalemler() if k["ay"] == ay)

    def test_uc_ay_uretim_mukerrer_yok_ve_ay_sonu(self):
        sg.plan_kaydet(_kira())
        self.assertEqual(sg.donemleri_uret(D), 3)
        self.assertEqual(sg.donemleri_uret(D), 0)
        kalemler = self._kalemler()
        self.assertEqual([(k["ay"], k["vade"]) for k in kalemler],
                         [(10, date(2026, 10, 31)), (11, date(2026, 11, 30)), (12, date(2026, 12, 31))])
        self.assertEqual(sum(k["kalan"] for k in kalemler), Decimal("60000.00"))

    def test_uretim_cari_finans_kaydi_olusturmaz(self):
        with get_session() as s:
            once = (s.scalar(select(func.count(CariIslem.id))), s.scalar(select(func.count(FinansHareketi.id))))
        sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        with get_session() as s:
            sonra = (s.scalar(select(func.count(CariIslem.id))), s.scalar(select(func.count(FinansHareketi.id))))
        self.assertEqual(once, sonra)

    def test_kismi_odeme_kalan_55000(self):
        sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        self._odeme("HV-1", "5000")
        sg.baglanti_ekle(self._donem(10)["donem_id"], "HV-1", "5000")
        self.assertEqual(self._donem(10)["kalan"], Decimal("15000.00"))
        self.assertEqual(sum(k["kalan"] for k in self._kalemler()), Decimal("55000.00"))
        # Ödeme rapor tarihinden sonra yapıldıysa geçmiş tarihli raporda kalanı azaltmaz
        self.assertEqual(next(k for k in self._kalemler(date(2026, 10, 9)) if k["ay"] == 10)["kalan"],
                         Decimal("20000.00"))

    def test_fazla_dagitim_ve_iptal_bagi(self):
        sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        self._odeme("HV-2", "25000")
        ekim = self._donem(10)["donem_id"]
        with self.assertRaises(ValueError):
            sg.baglanti_ekle(ekim, "HV-2", "25000")
        bid = sg.baglanti_ekle(ekim, "HV-2", "20000")
        with self.assertRaises(ValueError):  # evrakın kalan 5.000'i aşılamaz
            sg.baglanti_ekle(self._donem(11)["donem_id"], "HV-2", "6000")
        self.assertEqual(self._donem(10)["kalan"], Decimal("0.00"))
        sg.baglanti_iptal(bid, "yanlış dönem")
        self.assertEqual(self._donem(10)["kalan"], Decimal("20000.00"))
        with self.assertRaises(ValueError):
            sg.baglanti_ekle(ekim, "YOK-1", "100")

    def test_faturaya_bagli_kisim_plani_cogaltmaz(self):
        sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        with get_session() as s:
            s.add(HizmetFaturasi(fatura_no="HZF-1", fatura_turu="GIDER", fatura_tarihi=date(2026, 11, 1),
                                 vade_tarihi=date(2026, 11, 30), cari_id=self.ort.ted_id,
                                 tl_genel_toplam=Decimal("20000")))
        sg.baglanti_ekle(self._donem(11)["donem_id"], "HZF-1", "20000", tarih=D)
        kasim = self._donem(11)
        self.assertEqual(kasim["faturaya_bagli"], Decimal("20000.00"))
        self.assertEqual(kasim["kalan"], Decimal("0.00"))

    def test_tutar_degisikligi_ileriye_doner(self):
        pid = sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        sg.plan_kaydet(_kira(tutar="22000"), pid, gecerli_ay="12.2026", bugun=D)
        tutarlar = {k["ay"]: k["tutar"] for k in self._kalemler()}
        self.assertEqual(tutarlar, {10: Decimal("20000.00"), 11: Decimal("20000.00"), 12: Decimal("22000.00")})

    def test_durdurma_gelecek_donemi_iptal_eder(self):
        pid = sg.plan_kaydet(_kira())
        sg.donemleri_uret(D)
        self._odeme("HV-3", "20000")
        sg.baglanti_ekle(self._donem(10)["donem_id"], "HV-3", "20000")
        sg.plan_durdur(pid, "11.2026")
        self.assertEqual(sorted(k["ay"] for k in self._kalemler()), [10, 11])
        self.assertEqual(sg.donemleri_uret(D), 0)
        sg.plan_iptal(pid, "taşındık", bugun=D)
        # Ödenmiş Ekim korunur, ödenmemiş Kasım iptal
        self.assertEqual([k["ay"] for k in self._kalemler()], [10])
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SabitGiderDonemi.id))), 3)

    def test_subat_ve_tek_seferlik(self):
        sg.plan_kaydet(_kira(baslangic_ay="02.2027", ad="Şubat"))
        sg.plan_kaydet({"kategori": "SGK_VERGI", "ad": "Emlak vergisi", "periyot": "TEK", "odeme_gunu": 30,
                        "tutar": "3000", "baslangic_ay": "11.2026"})
        sg.donemleri_uret(date(2026, 12, 15))
        vadeler = sorted((k["plan_adi"], k["vade"]) for k in self._kalemler(date(2026, 12, 15)))
        self.assertEqual(vadeler, [("Şubat", date(2027, 2, 28))])
        sg.donemleri_uret(date(2026, 11, 2))
        self.assertIn(("Emlak vergisi", date(2026, 11, 30)),
                      [(k["plan_adi"], k["vade"]) for k in self._kalemler(date(2026, 12, 15))])

    def test_dogrulama(self):
        for hatali in (_kira(tutar="0"), _kira(odeme_gunu=32), _kira(kategori="X"),
                       _kira(bitis_ay="12.2025")):
            with self.assertRaises(ValueError):
                sg.plan_kaydet(hatali)


if __name__ == "__main__":
    unittest.main()
