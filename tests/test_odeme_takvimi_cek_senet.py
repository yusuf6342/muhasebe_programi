"""Borç çek / senet ödemeleri (Ödeme Takvimi ek talimatı): kısmi / tam ödeme, ödeme iptali, tek işlem, evrak iptali.

Takvim satırları bu evrakların ``kalan_tutar`` ve durumundan okunur; burada kaynak modülün ödeme etkisi denetlenir.
"""

from __future__ import annotations

import unittest
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch

from sqlalchemy import func, inspect, select, text

from tests.stok_test_ortami import StokOrtami

from database.cek_senet_service import CekSenetService
from database.database import get_session
from database.models.cari import Cari
from database.models.cek_senet import (
    DURUM_IPTAL,
    DURUM_KISMI_ODENDI,
    DURUM_ODENDI,
    DURUM_TEDARIKCIYE_VERILDI,
    CekSenetEvrak,
    CekSenetHareket,
)
from database.models.finans import FinansHareketi, FinansHesabi
from database.session_manager import oturum

ODEME_TURU = "ÇEK/SENET ÖDEME"
IPTAL_TURU = "ÇEK/SENET ÖDEME İPTAL"


class CekOrtami:
    def setUp(self):
        self.ort = StokOrtami("cek_senet_odeme")
        with get_session() as s:
            banka = FinansHesabi(hesap_adi="Akbank Mevduat", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT",
                                 iban="TR12 0004 6000 0000 0000 0000 01", acilis_bakiyesi=D("1000000"), aktif=True)
            kasa = FinansHesabi(hesap_adi="Merkez Kasa", hesap_turu="KASA", acilis_bakiyesi=D("1000000"), aktif=True)
            ted_b = Cari(cari_kodu="T002", unvan="Tedarikçi B", cari_turu="Tedarikçi", aktif=True)
            ted_c = Cari(cari_kodu="T003", unvan="Tedarikçi C", cari_turu="Tedarikçi", aktif=True)
            s.add_all([banka, kasa, ted_b, ted_c])
            s.flush()
            self.banka_id, self.kasa_id = int(banka.id), int(kasa.id)
            self.ted_b, self.ted_c = int(ted_b.id), int(ted_c.id)

    def tearDown(self):
        self.ort.kapat()

    # ------------------------------------------------------------------ yardımcılar
    def evrak(self, no: str, tutar: str, *, tur: str = "CEK", cari_id: int | None = None,
              vade: date = date(2026, 10, 16), **ek) -> int:
        sonuc = CekSenetService.olustur({
            "islem_yonu": "VERILEN", "basit_tur": tur, "evrak_no": no, "cari_id": cari_id or self.ort.ted_id,
            "duzenleme_tarihi": date(2026, 10, 1), "vade_tarihi": vade, "tutar": tutar, **ek})
        return int(sonuc["id"])

    def ode(self, eid: int, tutar=None, hesap: int | None = None) -> dict:
        return CekSenetService.ode(eid, tutar=tutar, finans_hesap_id=hesap or self.banka_id, tarih=date(2026, 10, 12))

    def durum(self, eid: int) -> tuple[str, D, D]:
        with get_session() as s:
            e = s.get(CekSenetEvrak, eid)
            return e.durum, D(str(e.kalan_tutar)), D(str(e.tahsil_edilen_tutar))

    def odeme_hareketleri(self, eid: int) -> list[CekSenetHareket]:
        with get_session() as s:
            return list(s.scalars(select(CekSenetHareket).where(
                CekSenetHareket.evrak_id == eid, CekSenetHareket.islem_turu.in_(("ODEME", "KISMI_ODEME")))
                .order_by(CekSenetHareket.id)).all())

    def finans_cikislari(self, tur: str = ODEME_TURU) -> list[D]:
        with get_session() as s:
            return [D(str(t)) for t in s.scalars(select(FinansHareketi.tutar).where(
                FinansHareketi.hareket_turu == tur).order_by(FinansHareketi.id)).all()]

    def iptal_girisleri(self) -> list[D]:
        return self.finans_cikislari(IPTAL_TURU)

    def banka_bakiyesi(self) -> D:
        from database.finans_service import FinansService

        with get_session() as s:
            return FinansService.bakiye(s.get(FinansHesabi, self.banka_id))


class CekSenetOdemeTest(CekOrtami, unittest.TestCase):
    # ------------------------------------------------------------------ ödeme
    def test_kismi_ve_tam_odeme_ornek_tutarlar(self):
        c1 = self.evrak("ÇEK 001", "25000")
        c2 = self.evrak("ÇEK 002", "15000", cari_id=self.ted_b)
        s1 = self.evrak("SNT 001", "10000", tur="SENET", cari_id=self.ted_c)

        self.ode(c1, "5000")
        self.assertEqual(self.durum(c1), (DURUM_KISMI_ODENDI, D("20000.00"), D("5000.00")))
        toplam = sum((self.durum(e)[1] for e in (c1, c2, s1)), D(0))
        self.assertEqual(toplam, D("45000.00"))

        self.ode(c1, "20000")
        self.assertEqual(self.durum(c1), (DURUM_ODENDI, D("0.00"), D("25000.00")))
        toplam = sum((self.durum(e)[1] for e in (c1, c2, s1)), D(0))
        self.assertEqual(toplam, D("25000.00"))
        self.assertEqual(self.finans_cikislari(), [D("5000.00"), D("20000.00")])
        self.assertEqual(self.durum(c2)[0], DURUM_TEDARIKCIYE_VERILDI)

    def test_kalandan_fazla_odeme_reddedilir(self):
        c1 = self.evrak("ÇEK 001", "1000")
        with self.assertRaises(ValueError):
            self.ode(c1, "1000.01")
        self.assertEqual(self.durum(c1)[1], D("1000.00"))

    def test_ayni_numarali_farkli_evraklar_karismaz(self):
        a = self.evrak("SMK-1", "300")
        b = self.evrak("SMK-1", "500", cari_id=self.ted_b)
        self.ode(a, "300")
        self.assertEqual(self.durum(a)[0], DURUM_ODENDI)
        self.assertEqual(self.durum(b), (DURUM_TEDARIKCIYE_VERILDI, D("500.00"), D("0.00")))

    def test_odeme_tek_islem_finans_hatasinda_evrak_degismez(self):
        c1 = self.evrak("ÇEK 001", "25000")
        with patch.object(CekSenetService, "_finans_hareket_yaz", side_effect=RuntimeError("banka yazılamadı")):
            with self.assertRaises(RuntimeError):
                self.ode(c1, "5000")
        self.assertEqual(self.durum(c1), (DURUM_TEDARIKCIYE_VERILDI, D("25000.00"), D("0.00")))
        self.assertEqual(self.odeme_hareketleri(c1), [])
        self.assertEqual(self.finans_cikislari(), [])

    # ------------------------------------------------------------------ ödeme iptali
    def test_odeme_iptali_kalani_geri_getirir_ters_banka_hareketi_yazar(self):
        c1 = self.evrak("ÇEK 001", "25000")
        self.ode(c1, "5000")
        self.ode(c1, "20000")
        self.assertEqual(self.banka_bakiyesi(), D("975000.00"))
        ilk, ikinci = self.odeme_hareketleri(c1)

        sonuc = CekSenetService.odeme_iptal(ikinci.id, "Yanlış dekont")
        self.assertEqual((sonuc["durum"], sonuc["kalan_tutar"]), (DURUM_KISMI_ODENDI, D("20000.00")))
        self.assertEqual(self.durum(c1), (DURUM_KISMI_ODENDI, D("20000.00"), D("5000.00")))
        self.assertEqual(self.finans_cikislari(), [D("5000.00"), D("20000.00")], "ödeme çıkışı silinmez")
        self.assertEqual(self.iptal_girisleri(), [D("20000.00")])
        self.assertEqual(self.banka_bakiyesi(), D("995000.00"))

        CekSenetService.odeme_iptal(ilk.id, "Yanlış hesap")
        self.assertEqual(self.durum(c1), (DURUM_TEDARIKCIYE_VERILDI, D("25000.00"), D("0.00")))
        self.assertEqual(self.iptal_girisleri(), [D("20000.00"), D("5000.00")])
        self.assertEqual(self.banka_bakiyesi(), D("1000000.00"), "ödeme + ters hareket net sıfır")
        with get_session() as s:
            iptaller = s.scalars(select(CekSenetHareket).where(
                CekSenetHareket.evrak_id == c1, CekSenetHareket.islem_turu == "ODEME_IPTAL")).all()
            self.assertEqual(sorted(D(str(h.tutar)) for h in iptaller), [D("5000.00"), D("20000.00")])
            self.assertTrue(all(s.get(CekSenetHareket, h.id).iptal for h in (ilk, ikinci)))
            self.assertIsNotNone(s.get(CekSenetHareket, ilk.id).iptal_tarihi)
            belgeler = set()
            for h in iptaller:
                ters = s.get(FinansHareketi, h.finans_hareket_id)
                self.assertEqual(ters.hareket_turu, IPTAL_TURU)
                self.assertEqual(ters.tarih, max(date.today(), date(2026, 10, 12)), "iptal günü tarihli")
                belgeler.add(ters.belge_no)
            orijinaller = [s.get(FinansHareketi, h.finans_hareket_id) for h in (ilk, ikinci)]
            self.assertEqual({o.tarih for o in orijinaller}, {date(2026, 10, 12)}, "ödeme tarihi korunur")
            self.assertEqual({o.belge_no for o in orijinaller}, belgeler, "ters hareket ödemenin belgesini taşır")
        with self.assertRaisesRegex(ValueError, "zaten iptal"):
            CekSenetService.odeme_iptal(ilk.id, "Tekrar")

        # Yeniden ödeme ve evrak iptali: iptal edilmiş ödeme engel olmaz
        self.ode(c1, "1000")
        self.assertEqual(self.durum(c1), (DURUM_KISMI_ODENDI, D("24000.00"), D("1000.00")))
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c1)[-1].id, "Vazgeçildi")
        CekSenetService.iptal(c1, aciklama="Çek kullanılmadı")
        self.assertEqual(self.durum(c1)[0], DURUM_IPTAL)

    def test_ileri_tarihli_odeme_iptalinde_ters_hareket_odeme_gunune_yazilir(self):
        c1 = self.evrak("ÇEK 001", "700", vade=date.today() + timedelta(days=40))
        ileri = date.today() + timedelta(days=20)
        CekSenetService.ode(c1, finans_hesap_id=self.banka_id, tarih=ileri)
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c1)[0].id, "Erken girildi")
        with get_session() as s:
            ters = s.scalars(select(FinansHareketi).where(FinansHareketi.hareket_turu == IPTAL_TURU)).one()
            self.assertEqual(ters.tarih, ileri, "ödemeden önce banka girişi oluşmaz")

    def test_odeme_iptali_muhasebe_ters_kaydini_ister(self):
        c1 = self.evrak("ÇEK 001", "700")
        self.ode(c1)
        odeme = self.odeme_hareketleri(c1)[0]
        cagrilar = []
        with patch("database.muhasebe_entegrasyon.muhasebe_hook",
                   lambda ad, *a, **k: cagrilar.append((ad, a))):
            CekSenetService.odeme_iptal(odeme.id, "Yanlış ödeme")
        self.assertIn(("cek_senet_iptal", (odeme.id, "Çek/senet ödeme iptali: Yanlış ödeme")), cagrilar)
        self.assertNotIn("cek_senet_fisi", [c[0] for c in cagrilar], "iptal hareketi yeni ödeme fişi üretmez")

    def test_odeme_iptali_tek_islem_hata_olursa_hicbir_sey_degismez(self):
        c1 = self.evrak("ÇEK 001", "700")
        self.ode(c1, "200")
        odeme = self.odeme_hareketleri(c1)[0]
        with patch.object(CekSenetService, "_muhasebe_iptal", side_effect=RuntimeError("fiş iptal edilemedi")):
            with self.assertRaises(RuntimeError):
                CekSenetService.odeme_iptal(odeme.id, "Deneme")
        self.assertEqual(self.durum(c1), (DURUM_KISMI_ODENDI, D("500.00"), D("200.00")))
        self.assertEqual(self.finans_cikislari(), [D("200.00")])
        self.assertEqual(self.iptal_girisleri(), [])
        with get_session() as s:
            self.assertFalse(s.get(CekSenetHareket, odeme.id).iptal)

    def test_odeme_iptali_neden_yetki_ve_hareket_turu(self):
        c1 = self.evrak("ÇEK 001", "700")
        self.ode(c1, "200")
        odeme = self.odeme_hareketleri(c1)[0]
        with self.assertRaisesRegex(ValueError, "nedenini"):
            CekSenetService.odeme_iptal(odeme.id, "   ")
        with get_session() as s:
            kayit_id = s.scalar(select(CekSenetHareket.id).where(
                CekSenetHareket.evrak_id == c1, CekSenetHareket.islem_turu == "KAYIT"))
        with self.assertRaisesRegex(ValueError, "Yalnız verilen"):
            CekSenetService.odeme_iptal(kayit_id, "Kayıt iptal denemesi")

        oturum.set_user(user_id=2, kullanici_adi="kasiyer", ad_soyad="Kasiyer", role_kod="KASIYER",
                        role_ad="Kasiyer", permissions={"finans_goruntuleme"})
        with self.assertRaises(PermissionError):
            CekSenetService.odeme_iptal(odeme.id, "Yetkisiz")
        self.assertEqual(self.durum(c1)[1], D("500.00"))

    def test_alinan_evrak_tahsilati_odeme_iptaliyle_geri_alinmaz(self):
        sonuc = CekSenetService.olustur({
            "islem_yonu": "ALINAN", "basit_tur": "CEK", "evrak_no": "M-1", "cari_id": self.ort.mus_id,
            "duzenleme_tarihi": date(2026, 10, 1), "vade_tarihi": date(2026, 10, 16), "tutar": "400"})
        CekSenetService.tahsil_et(sonuc["id"], finans_hesap_id=self.banka_id, tarih=date(2026, 10, 12))
        with get_session() as s:
            tahsil = s.scalar(select(CekSenetHareket.id).where(
                CekSenetHareket.evrak_id == sonuc["id"], CekSenetHareket.islem_turu == "TAHSIL"))
        with self.assertRaisesRegex(ValueError, "Yalnız verilen"):
            CekSenetService.odeme_iptal(tahsil, "Deneme")

    # ------------------------------------------------------------------ evrak iptali
    def test_evrak_iptali_odenmis_evraka_izin_vermez(self):
        acik = self.evrak("ÇEK 010", "900")
        CekSenetService.iptal(acik, aciklama="Yanlış kayıt")
        durum, kalan, _ = self.durum(acik)
        self.assertEqual(durum, DURUM_IPTAL)
        self.assertEqual(kalan, D("900.00"), "iptal kalanı sıfırlamaz; takvim durumu esas almalı")

        odenmis = self.evrak("ÇEK 011", "900")
        self.ode(odenmis)
        with self.assertRaises(ValueError):
            CekSenetService.iptal(odenmis, aciklama="Ödenmiş evrak")
        kismi = self.evrak("ÇEK 012", "900")
        self.ode(kismi, "100")
        with self.assertRaises(ValueError):
            CekSenetService.iptal(kismi, aciklama="Kısmi ödenmiş evrak")
        self.assertEqual(self.durum(kismi)[1], D("800.00"))


class DonenSermayeOdemeIptaliTest(CekOrtami, unittest.TestCase):
    """Seçilen rapor tarihi T: ödeme (P) öncesi etkisiz, P ≤ T < iptal (C) ödenmiş, T ≥ C geri alınmış."""

    BUGUN = date.today()
    P = BUGUN - timedelta(days=10)

    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="donen_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._env.stop()
        self._ayar.cleanup()

    def rapor(self, t: date) -> tuple[D, D]:
        """(banka kalemi, firma çek borcu) — rapor tarihi t, bugün BUGUN."""
        from database import donen_sermaye_service as ds

        r = ds.hesapla(t, bugun=self.BUGUN)
        aktif = {x["etiket"]: x["tutar"] for x in r[ds.AKTIF] if x["seviye"] == ds.KALEM}
        pasif = {x["etiket"]: x["tutar"] for x in r[ds.PASIF] if x["seviye"] == ds.KALEM}
        return aktif.get("Akbank Mevduat", D(0)), pasif.get("Firma Çek Borçları", D(0))

    def odenmis_cek(self, *tutarlar: str) -> int:
        c = self.evrak("ÇEK 001", "25000")
        with get_session() as s:
            s.get(CekSenetEvrak, c).duzenleme_tarihi = self.BUGUN - timedelta(days=30)
        for tutar in tutarlar or (None,):
            CekSenetService.ode(c, tutar=tutar, finans_hesap_id=self.banka_id, tarih=self.P)
        return c

    def iptali_gecmise_al(self, gun: date) -> None:
        """İptali `gun` tarihinde yapılmış gibi kaydırır (iptal anı, ODEME_IPTAL ve ters banka hareketi)."""
        with get_session() as s:
            for h in s.scalars(select(CekSenetHareket)).all():
                if h.iptal:
                    h.iptal_tarihi = datetime.combine(gun, datetime.min.time())
                if h.islem_turu == "ODEME_IPTAL":
                    h.tarih = datetime.combine(gun, datetime.min.time())
            for f in s.scalars(select(FinansHareketi).where(FinansHareketi.hareket_turu == IPTAL_TURU)).all():
                f.tarih = gun

    def test_bugun_iptal_edilen_odeme_gecmis_tarihlerde_gecerli(self):
        c = self.odenmis_cek()
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c)[0].id, "Yanlış dekont")
        self.assertEqual(self.rapor(self.P - timedelta(days=5)), (D("1000000.00"), D("-25000.00")), "T < P")
        self.assertEqual(self.rapor(self.P), (D("975000.00"), D(0)), "T = P")
        self.assertEqual(self.rapor(self.BUGUN - timedelta(days=1)), (D("975000.00"), D(0)), "P ≤ T < C")
        self.assertEqual(self.rapor(self.BUGUN), (D("1000000.00"), D("-25000.00")), "T = C: çift etki yok")

    def test_gecmiste_iptal_edilen_odeme_iptal_gununden_itibaren_geri_alinir(self):
        c = self.odenmis_cek()
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c)[0].id, "Yanlış dekont")
        C = self.BUGUN - timedelta(days=4)
        self.iptali_gecmise_al(C)
        self.assertEqual(self.rapor(self.P - timedelta(days=1)), (D("1000000.00"), D("-25000.00")))
        self.assertEqual(self.rapor(C - timedelta(days=1)), (D("975000.00"), D(0)))
        self.assertEqual(self.rapor(C), (D("1000000.00"), D("-25000.00")))
        self.assertEqual(self.rapor(self.BUGUN - timedelta(days=1)), (D("1000000.00"), D("-25000.00")))

    def test_kismi_odemeden_biri_iptal(self):
        c = self.odenmis_cek("5000", "20000")
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c)[1].id, "Yanlış tutar")
        C = self.BUGUN - timedelta(days=4)
        self.iptali_gecmise_al(C)
        self.assertEqual(self.rapor(C - timedelta(days=1)), (D("975000.00"), D(0)))
        self.assertEqual(self.rapor(C), (D("995000.00"), D("-20000.00")))
        self.assertEqual(self.rapor(self.BUGUN), (D("995000.00"), D("-20000.00")))

    def test_geriye_tarihli_odeme_banka_tarihinden_sayilir(self):
        """Evrak hareketi bugün girilse de ödeme etkisi kasa/banka tarihinde başlar (banka ile aynı gün)."""
        self.odenmis_cek("5000")
        self.assertEqual(self.rapor(self.P - timedelta(days=1)), (D("1000000.00"), D("-25000.00")))
        self.assertEqual(self.rapor(self.P), (D("995000.00"), D("-20000.00")))


class OdemeTakvimiCekSenetTest(CekOrtami, unittest.TestCase):
    """Ek talimat kabul kontrolleri: takvimde Borç Çeki / Borç Senedi satırları."""

    BUGUN = date(2026, 10, 13)
    VADE = date(2026, 10, 16)

    def takvim(self) -> dict:
        from database import odeme_takvimi_service as ots

        return ots.hesapla(self.BUGUN)

    def cek_satirlari(self, v: dict | None = None) -> list[dict]:
        v = v or self.takvim()
        return [k for a in v["aylar"] for k in a["kalemler"] if k["kaynak"] == "CEKSENET"] + \
            [k for k in v["gecmis"] if k["kaynak"] == "CEKSENET"]

    def ekim(self, v: dict) -> dict:
        return next(a for a in v["aylar"] if (a["yil"], a["ay"]) == (2026, 10))

    def ornek(self) -> tuple[int, int, int]:
        return (self.evrak("ÇEK 001", "25000"), self.evrak("ÇEK 002", "15000", cari_id=self.ted_b),
                self.evrak("SNT 001", "10000", tur="SENET", cari_id=self.ted_c))

    def test_ornek_tablo_50_45_25_ve_diger_borclar_korunur(self):
        from database import sabit_gider_service as sg

        sg.plan_kaydet({"kategori": "KIRA", "ad": "Mağaza kirası", "periyot": "AYLIK", "odeme_gunu": 16,
                        "tutar": "8000", "baslangic_ay": "10.2026"})
        c1, c2, s1 = self.ornek()
        v = self.takvim()
        satirlar = self.cek_satirlari(v)
        self.assertEqual({k["evrak_id"]: (k["tarih"], k["gun"], k["tur"], k["kalan"]) for k in satirlar}, {
            c1: (self.VADE, "Cuma", "Borç Çeki", D("25000.00")), c2: (self.VADE, "Cuma", "Borç Çeki", D("15000.00")),
            s1: (self.VADE, "Cuma", "Borç Senedi", D("10000.00"))})
        self.assertEqual([k["tur"] for k in satirlar], ["Borç Çeki", "Borç Çeki", "Borç Senedi"])
        self.assertEqual(sorted(k["anahtar"] for k in satirlar), sorted(f"CEKSENET:{i}" for i in (c1, c2, s1)))
        self.assertTrue(next(k for k in satirlar if k["evrak_id"] == c1)["aciklama"].startswith("ÇEK 001 • "))
        self.assertEqual(self.ekim(v)["toplam"], D("58000.00"))
        kasim, genel = v["aylar"][1]["toplam"], v["genel_toplam"]

        self.ode(c1, "5000")
        v = self.takvim()
        self.assertEqual(sum((k["kalan"] for k in self.cek_satirlari(v)), D(0)), D("45000.00"))
        self.assertEqual(self.ekim(v)["toplam"], D("53000.00"), "toplam yalnız 5.000 azalır")
        self.assertEqual((v["aylar"][1]["toplam"], v["genel_toplam"]), (kasim, genel - D("5000")))

        self.ode(c1, "20000")
        v = self.takvim()
        self.assertEqual({k["evrak_id"] for k in self.cek_satirlari(v)}, {c2, s1}, "yalnız ÇEK 001 kaybolur")
        self.assertEqual(sum((k["kalan"] for k in self.cek_satirlari(v)), D(0)), D("25000.00"))
        self.assertEqual(v["aylar"][1]["toplam"], kasim, "diğer ayların toplamı korunur")
        self.assertTrue(any(k["tarih"] == self.VADE for k in self.ekim(v)["kalemler"]), "16 Ekim görünmeye devam")

    def test_vade_tarihi_kullanilir_gun_adi_degisir(self):
        c = self.evrak("ÇEK 001", "1000")
        k = self.cek_satirlari()[0]
        self.assertEqual((k["tarih"], k["gun"]), (self.VADE, "Cuma"))
        self.assertNotEqual(k["tarih"], date(2026, 10, 1), "düzenleme tarihi kullanılmaz")
        with get_session() as s:
            s.get(CekSenetEvrak, c).vade_tarihi = date(2026, 10, 19)
        k = self.cek_satirlari()[0]
        self.assertEqual((k["tarih"], k["gun"]), (date(2026, 10, 19), "Pazartesi"))

    def test_son_borc_kapaninca_gun_kaybolur(self):
        c = self.evrak("ÇEK 001", "1000")
        self.ode(c)
        v = self.takvim()
        self.assertEqual(self.ekim(v)["kalemler"], [])
        self.assertEqual(self.ekim(v)["toplam"], D("0.00"))

    def test_dort_aylik_pencere_ve_gecmis(self):
        eski = self.evrak("ÇEK ESKİ", "700", vade=date(2026, 9, 5), duzenleme_tarihi=date(2026, 9, 1))
        ocak = self.evrak("ÇEK OCAK", "900", vade=date(2027, 1, 15))
        self.evrak("ÇEK ŞUBAT", "1100", vade=date(2027, 2, 1))
        v = self.takvim()
        self.assertEqual([k["evrak_id"] for k in v["gecmis"]], [eski])
        self.assertTrue(v["gecmis"][0]["gecikmis"])
        self.assertEqual(v["gecmis_toplam"], D("700.00"))
        self.assertEqual([k["evrak_id"] for k in v["aylar"][3]["kalemler"]], [ocak])
        self.assertEqual(v["genel_toplam"], D("900.00"), "geçmiş ve pencere dışı genel toplama girmez")

    def test_odeme_iptali_satiri_geri_getirir(self):
        c = self.evrak("ÇEK 001", "25000")
        self.ode(c)
        self.assertEqual(self.cek_satirlari(), [])
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c)[0].id, "Yanlış dekont")
        satirlar = self.cek_satirlari()
        self.assertEqual([(k["evrak_id"], k["kalan"]) for k in satirlar], [(c, D("25000.00"))])
        self.assertTrue(satirlar[0]["odemeler"][0]["iptal"])
        self.assertEqual(satirlar[0]["odenen"], D("0.00"))

    def test_iade_ve_iptal_evrak_kaybolur(self):
        iade = self.evrak("ÇEK 010", "900")
        iptal = self.evrak("ÇEK 011", "800")
        kalan = self.evrak("ÇEK 012", "700")
        CekSenetService.iade_et(iade, aciklama="Tedarikçi geri verdi")
        CekSenetService.iptal(iptal, aciklama="Yanlış kayıt")
        self.assertEqual([k["evrak_id"] for k in self.cek_satirlari()], [kalan])

    def test_alacak_evraklari_ciro_ve_tedarikci_borcu_gorunmez(self):
        alinan = CekSenetService.olustur({
            "islem_yonu": "ALINAN", "basit_tur": "CEK", "evrak_no": "M-1", "cari_id": self.ort.mus_id,
            "duzenleme_tarihi": date(2026, 10, 1), "vade_tarihi": self.VADE, "tutar": "4000"})
        CekSenetService.ciro_et(alinan["id"], hedef_cari_id=self.ort.ted_id, tarih=date(2026, 10, 12))
        self.ort.alis(10, 100, date(2026, 10, 1))
        v = self.takvim()
        self.assertEqual(self.cek_satirlari(v), [])
        self.assertEqual((v["genel_toplam"], v["eksikler"]), (D("0.00"), []))

    def test_celiski_ve_tutarsiz_kalan_eksik_bilgide_toplama_girmez(self):
        dogru = self.evrak("ÇEK 001", "1000")
        tutarsiz = self.evrak("ÇEK 002", "2000")
        with get_session() as s:
            s.get(CekSenetEvrak, tutarsiz).kalan_tutar = D("1500")
            s.add(CekSenetEvrak(cari_id=self.ort.ted_id, evrak_turu="MUSTERI_CEKI", islem_yonu="VERILEN",
                                evrak_no="CİRO-1", portfoy_no="VRÇ-CIRO-1", duzenleme_tarihi=date(2026, 10, 1),
                                vade_tarihi=self.VADE, tl_tutari=D("3000"), kalan_tutar=D("3000"),
                                doviz_tutari=D("3000"), durum="TEDARIKCIYE_VERILDI"))
        v = self.takvim()
        self.assertEqual([k["evrak_id"] for k in self.cek_satirlari(v)], [dogru])
        self.assertEqual(v["genel_toplam"], D("1000.00"))
        nedenler = " | ".join(e["neden"] for e in v["eksikler"])
        self.assertIn("uyuşmuyor", nedenler)
        self.assertIn("müşteri evrakı", nedenler)
        self.assertTrue(v["toplam_eksik"])
        self.assertTrue(any(f"#{tutarsiz} " in e["ad"] for e in v["eksikler"]), "evrak kimliğiyle gösterilir")

    def test_muhasebelestirme_ve_yenileme_cift_etki_yapmaz(self):
        """Gerçek muhasebe kancası (fiş üretimi, iki kez) evrak kalanını ve banka hareketini değiştirmez."""
        c = self.evrak("ÇEK 001", "25000")
        self.ode(c, "5000")
        once = self.cek_satirlari()
        hid = self.odeme_hareketleri(c)[0].id
        kanca_yamasi = self.ort._yamalar[0]
        kanca_yamasi.stop()
        try:
            from database.muhasebe_entegrasyon import muhasebe_hook

            for _ in range(2):
                try:
                    muhasebe_hook("cek_senet_fisi", hid)
                except Exception:  # noqa: BLE001  (hesap eşlemesi olmayan test firması)
                    pass
        finally:
            kanca_yamasi.start()
        self.assertEqual([k["kalan"] for k in self.cek_satirlari()], [k["kalan"] for k in once])
        self.assertEqual(self.takvim()["genel_toplam"], D("20000.00"))
        self.assertEqual(self.finans_cikislari(), [D("5000.00")], "banka hareketi tek")
        self.assertEqual(self.durum(c)[1], D("20000.00"))

    def test_cek_odeme_belgesi_sabit_gidere_baglanamaz(self):
        from database import sabit_gider_service as sg

        plan_id = sg.plan_kaydet({"kategori": "KIRA", "ad": "Depo kirası", "periyot": "AYLIK", "odeme_gunu": 16,
                                  "tutar": "25000", "baslangic_ay": "10.2026"})
        c = self.evrak("ÇEK 001", "25000")
        self.ode(c)
        with get_session() as s:
            belge = s.scalar(select(FinansHareketi.belge_no).where(FinansHareketi.hareket_turu == ODEME_TURU))
        donem_id = sg.donem_hazirla(plan_id, 2026, 10)
        with self.assertRaisesRegex(ValueError, "çek / senet"):
            sg.baglanti_ekle(donem_id, belge, "25000")
        CekSenetService.odeme_iptal(self.odeme_hareketleri(c)[0].id, "Deneme")
        with self.assertRaisesRegex(ValueError, "çek / senet"):
            sg.baglanti_ekle(donem_id, belge, "25000")


class OdemeTakvimiCekSenetEkranTest(CekOrtami, unittest.TestCase):
    BUGUN = date(2026, 10, 13)

    def setUp(self):
        import tkinter as tk

        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:  # pragma: no cover
            self.ort.kapat()
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        super().tearDown()

    def test_ekran_satiri_ve_odeme_penceresi_hazir_gelir(self):
        from odeme_takvimi_ui import OdemeTakvimiSayfasi, odeme_evraki_ac

        c = self.evrak("ÇEK 001", "25000", iban="TR12 0004 6000 0000 0000 0000 01", banka_adi="Akbank")
        sayfa = OdemeTakvimiSayfasi(self.root, None, bugun_fn=lambda: self.BUGUN)
        anahtar = f"CEKSENET:{c}"
        degerler = sayfa.tablo.item(anahtar, "values")
        self.assertEqual(degerler[:3], ("16.10.2026", "Cuma", "Borç Çeki"))
        self.assertTrue(degerler[3].startswith("ÇEK 001 • Test Tedarikçi"))
        sayfa.tablo.selection_set(anahtar)
        sayfa._detay_goster()
        detay = sayfa.detay.get("1.0", "end")
        self.assertIn("Vade: 16.10.2026", detay)
        self.assertIn("Alacaklı: Test Tedarikçi", detay)

        dlg = odeme_evraki_ac(self.root, sayfa.secili_kalem(), sayfa.yenile)
        self.assertEqual(int(dlg.evrak["id"]), c)
        self.assertEqual(dlg.tutar.get(), "25000,00")
        self.assertEqual(dlg.girdiler["islem_tarihi"].get(), date.today().strftime("%d.%m.%Y"))
        self.assertIn("Akbank Mevduat", dlg.hesap_var.get())
        dlg.tutar.delete(0, "end")
        dlg.tutar.insert(0, "5000")
        hatalar = []
        with patch("cek_senet_ui.messagebox.showinfo"), \
                patch("cek_senet_ui.messagebox.showerror", lambda *a, **k: hatalar.append(a)):
            dlg._kaydet()
        self.assertEqual(hatalar, [])
        sayfa.yenile()
        degerler = sayfa.tablo.item(anahtar, "values")
        self.assertEqual(degerler[0], "16.10.2026", "vade değişmez")
        self.assertEqual(self.durum(c)[1], D("20000.00"))
        self.assertIn("20.000", degerler[4])
        sayfa.destroy()

    def test_vadesi_gecmis_satirdan_odeme_penceresi_acilir_ve_oder(self):
        from odeme_takvimi_ui import odeme_evraki_ac
        from database import odeme_takvimi_service as ots

        c = self.evrak("ÇEK 001", "1000", vade=date(2026, 10, 5))
        with get_session() as s:
            s.get(CekSenetEvrak, c).durum = "VADESI_GECTI"
        k = next(x for a in ots.hesapla(self.BUGUN)["aylar"] for x in a["kalemler"] if x["evrak_id"] == c)
        self.assertTrue(k["gecikmis"])
        dlg = odeme_evraki_ac(self.root, k, lambda: None)
        self.assertEqual(dlg.tutar.get(), "1000,00")
        dlg.tutar.delete(0, "end")
        dlg.tutar.insert(0, "400")
        dlg.hesap_var.set(next(e for e in dlg._hesap_map if dlg._hesap_map[e] == self.banka_id))
        hatalar = []
        with patch("cek_senet_ui.messagebox.showinfo"), \
                patch("cek_senet_ui.messagebox.showerror", lambda *a, **k: hatalar.append(a)):
            dlg._kaydet()
        self.assertEqual(hatalar, [])
        self.assertEqual(self.durum(c)[:2], (DURUM_KISMI_ODENDI, D("600.00")))
        self.assertEqual(self.finans_cikislari(), [D("400.00")])

    def test_kapanmis_evrakta_acik_uyari(self):
        from odeme_takvimi_ui import odeme_evraki_ac
        from database import odeme_takvimi_service as ots

        c = self.evrak("ÇEK 001", "1000")
        k = next(x for a in ots.hesapla(self.BUGUN)["aylar"] for x in a["kalemler"] if x["evrak_id"] == c)
        with get_session() as s:
            s.get(CekSenetEvrak, c).durum = DURUM_IPTAL
        with self.assertRaisesRegex(ValueError, "Ödenemez"):
            odeme_evraki_ac(self.root, k, lambda: None)


class VadesiGecmisCekOdemeTest(CekOrtami, unittest.TestCase):
    """Vadenin geçmiş olması ödemeyi engellemez; banka hareketi tek, iptal etkisi tek."""

    BUGUN = date(2026, 10, 13)

    def takvim(self) -> dict:
        from database import odeme_takvimi_service as ots

        return ots.hesapla(self.BUGUN)

    def gecikmis(self, no: str, tutar: str, vade: date = date(2026, 9, 20), durum: str = "VADESI_GECTI") -> int:
        e = self.evrak(no, tutar, vade=vade, duzenleme_tarihi=date(2026, 9, 1))
        with get_session() as s:
            s.get(CekSenetEvrak, e).durum = durum
        return e

    def gecmis_kalan(self, eid: int) -> D | None:
        return next((k["kalan"] for k in self.takvim()["gecmis"] if k.get("evrak_id") == eid), None)

    def test_gecmis_bolumdeki_evrak_kismi_sonra_tam_odenir(self):
        e = self.gecikmis("ÇEK 090", "10000")
        bakiye = self.banka_bakiyesi()
        v = self.takvim()
        self.assertEqual((self.gecmis_kalan(e), v["gecmis_toplam"]), (D("10000.00"), D("10000.00")))

        self.ode(e, "4000")
        self.assertEqual(self.durum(e), (DURUM_KISMI_ODENDI, D("6000.00"), D("4000.00")))
        self.assertEqual(self.finans_cikislari(), [D("4000.00")], "ödeme başına tek banka hareketi")
        self.assertEqual(self.banka_bakiyesi(), bakiye - D("4000"))
        self.assertEqual((self.gecmis_kalan(e), self.takvim()["gecmis_toplam"]), (D("6000.00"), D("6000.00")))

        self.ode(e)
        self.assertEqual(self.durum(e), (DURUM_ODENDI, D("0.00"), D("10000.00")))
        self.assertEqual(self.finans_cikislari(), [D("4000.00"), D("6000.00")])
        self.assertEqual(self.banka_bakiyesi(), bakiye - D("10000"))
        v = self.takvim()
        self.assertEqual((self.gecmis_kalan(e), v["gecmis_toplam"]), (None, D("0.00")))

    def test_ay_icindeki_gecikmis_evrak_ay_toplamini_dusurur(self):
        e = self.gecikmis("SNT 091", "5000", vade=date(2026, 10, 5))
        v = self.takvim()
        ekim = v["aylar"][0]
        self.assertTrue(next(k for k in ekim["kalemler"] if k["evrak_id"] == e)["gecikmis"])
        once_ay, once_genel = ekim["toplam"], v["genel_toplam"]
        self.ode(e, "3000")
        v = self.takvim()
        self.assertEqual(v["aylar"][0]["toplam"], once_ay - D("3000"))
        self.assertEqual(v["genel_toplam"], once_genel - D("3000"))
        self.assertEqual(self.finans_cikislari(), [D("3000.00")])

    def test_iptal_etkisi_bir_kez_geri_alinir_durum_vadesi_gecti_olur(self):
        e = self.gecikmis("ÇEK 092", "10000")
        bakiye = self.banka_bakiyesi()
        self.ode(e, "4000")
        self.ode(e, "6000")
        ilk, ikinci = self.odeme_hareketleri(e)

        CekSenetService.odeme_iptal(ikinci.id, "Yanlış tutar")
        self.assertEqual(self.durum(e), (DURUM_KISMI_ODENDI, D("6000.00"), D("4000.00")))
        CekSenetService.odeme_iptal(ilk.id, "Yanlış dekont")
        self.assertEqual(self.durum(e), ("VADESI_GECTI", D("10000.00"), D("0.00")))
        with self.assertRaisesRegex(ValueError, "zaten"):
            CekSenetService.odeme_iptal(ilk.id, "Tekrar")

        self.assertEqual(self.finans_cikislari(), [D("4000.00"), D("6000.00")], "çıkışlar silinmez")
        self.assertEqual(self.iptal_girisleri(), [D("6000.00"), D("4000.00")], "her iptal tek ters giriş")
        self.assertEqual(self.banka_bakiyesi(), bakiye)
        self.assertEqual(self.gecmis_kalan(e), D("10000.00"))
        with get_session() as s:
            iptaller = s.scalar(select(func.count()).select_from(CekSenetHareket).where(
                CekSenetHareket.evrak_id == e, CekSenetHareket.islem_turu == "ODEME_IPTAL"))
        self.assertEqual(iptaller, 2)

    def test_iptal_son_odeme_zincirinin_durumuna_doner(self):
        e = self.evrak("ÇEK 093", "2000", vade=date(2026, 9, 20), duzenleme_tarihi=date(2026, 9, 1))
        self.ode(e)
        CekSenetService.odeme_iptal(self.odeme_hareketleri(e)[0].id, "Deneme")
        self.assertEqual(self.durum(e)[0], DURUM_TEDARIKCIYE_VERILDI)
        with get_session() as s:
            s.get(CekSenetEvrak, e).durum = "VADESI_GECTI"
        self.ode(e, "500")
        CekSenetService.odeme_iptal(self.odeme_hareketleri(e)[1].id, "Deneme 2")
        self.assertEqual(self.durum(e), ("VADESI_GECTI", D("2000.00"), D("0.00")))

    def test_sorunlu_acik_firma_evraki_odenir(self):
        for i, durum in enumerate(("KARSILIKSIZ", "PROTESTO", "HUKUKI_TAKIP")):
            e = self.gecikmis(f"ÇEK 10{i}", "1000", durum=durum)
            self.ode(e)
            self.assertEqual(self.durum(e)[:2], (DURUM_ODENDI, D("0.00")), durum)
        self.assertEqual(len(self.finans_cikislari()), 3)

    def test_alinan_ve_ciro_musteri_evraki_ode_ile_odenmez(self):
        alinan = CekSenetService.olustur({
            "islem_yonu": "ALINAN", "basit_tur": "CEK", "evrak_no": "M-1", "cari_id": self.ort.mus_id,
            "duzenleme_tarihi": date(2026, 9, 1), "vade_tarihi": date(2026, 9, 20), "tutar": "4000"})["id"]
        with get_session() as s:
            s.get(CekSenetEvrak, alinan).durum = "VADESI_GECTI"
            ciro = CekSenetEvrak(cari_id=self.ort.ted_id, evrak_turu="MUSTERI_CEKI", islem_yonu="VERILEN",
                                 evrak_no="CİRO-1", portfoy_no="VRÇ-CIRO-1", duzenleme_tarihi=date(2026, 9, 1),
                                 vade_tarihi=date(2026, 9, 20), tl_tutari=D("3000"), kalan_tutar=D("3000"),
                                 doviz_tutari=D("3000"), durum="VADESI_GECTI")
            s.add(ciro)
            s.flush()
            ciro_id = int(ciro.id)
        with self.assertRaisesRegex(ValueError, "yalnızca verilen"):
            self.ode(alinan, "1000")
        with self.assertRaisesRegex(ValueError, "Ödenemez"):
            self.ode(ciro_id, "1000")
        self.assertEqual(self.finans_cikislari(), [])
        self.assertEqual(self.durum(alinan)[:2], ("VADESI_GECTI", D("4000.00")))


class CekSenetSemaGecisiTest(unittest.TestCase):
    """İptal kolonları olmayan eski firma tablosu: okuma / ekleme çalışır, geçiş kolonları ekler."""

    def setUp(self):
        self.ort = StokOrtami("cek_senet_sema")

    def tearDown(self):
        self.ort.kapat()

    def kolonlar(self) -> set[str]:
        return {c["name"] for c in inspect(self.ort.engine).get_columns("cek_senet_hareketleri")}

    def test_eski_tabloya_kolonlar_eklenir_veri_korunur(self):
        from database import cek_senet_service as css

        CekSenetEvrak.__table__.create(self.ort.engine, checkfirst=True)
        CekSenetHareket.__table__.create(self.ort.engine, checkfirst=True)
        with self.ort.engine.begin() as b:
            b.execute(text('ALTER TABLE cek_senet_hareketleri DROP COLUMN "iptal"'))
            b.execute(text('ALTER TABLE cek_senet_hareketleri DROP COLUMN "iptal_tarihi"'))
        self.assertNotIn("iptal", self.kolonlar())
        css._HAZIR_MOTORLAR.discard(self.ort.engine)

        with get_session() as s:
            e = CekSenetEvrak(cari_id=self.ort.ted_id, evrak_turu="FIRMA_CEKI", islem_yonu="VERILEN",
                              evrak_no="ESKI-1", portfoy_no="VRÇ-ESKI-1", duzenleme_tarihi=date(2026, 10, 1),
                              vade_tarihi=date(2026, 10, 16), tl_tutari=D("100"), kalan_tutar=D("100"),
                              doviz_tutari=D("100"), durum=DURUM_TEDARIKCIYE_VERILDI)
            s.add(e)
            s.flush()
            s.add(CekSenetHareket(evrak_id=e.id, yeni_durum=DURUM_TEDARIKCIYE_VERILDI, islem_turu="KAYIT",
                                  tutar=D("100")))
        with get_session() as s:
            self.assertEqual(len(s.scalars(select(CekSenetEvrak)).first().hareketler), 1)

        CekSenetService.schema_hazirla()
        self.assertTrue({"iptal", "iptal_tarihi"} <= self.kolonlar())
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CekSenetHareket.id)).where(
                CekSenetHareket.iptal.is_(False))), 1)


if __name__ == "__main__":
    unittest.main()
