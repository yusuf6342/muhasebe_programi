"""Giderin kredi kartıyla tek çekim / taksitli ödenmesi — ek talimatın 10 kabul kontrolü ve geçiş.

Yalnız geçici test veritabanı (StokOrtami); gerçek firma verisine dokunmaz. Örnek: 31.10.2026, 12.000 TL SGK,
kart kesim günü 5 (son ödeme 15).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from sqlalchemy import create_engine, func, inspect, select, text

from tests.stok_test_ortami import StokOrtami

from database import gider_kart_odeme_service as gk
from database import odeme_takvimi_service as ots
from database import sabit_gider_service as sg
from database.database import get_session
from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    GiderKartOdeme,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)
from database.models.hizmet import HizmetKarti
from database.models.sabit_gider import SabitGiderBaglanti

ISLEM = date(2026, 10, 31)
K1, K2, K3, K4 = date(2026, 11, 5), date(2026, 12, 5), date(2027, 1, 5), date(2027, 2, 5)


class _Gun:
    deger = ISLEM


class _DateMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, date)


class SahteDate(date, metaclass=_DateMeta):
    @classmethod
    def today(cls):
        return _Gun.deger


@contextlib.contextmanager
def bugun(gun: date):
    eski = _Gun.deger
    _Gun.deger = gun
    try:
        with patch("database.gider_kart_odeme_service.date", SahteDate), \
                patch("database.finans_service.date", SahteDate), \
                patch("database.kredi_karti_ekstre_service.date", SahteDate):
            yield
    finally:
        _Gun.deger = eski


class GiderKartOdemeTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("gider_kart")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Akbank", sube="Merkez", aktif=True)
            s.add(banka)
            s.flush()
            mev = FinansHesabi(hesap_adi="Akbank Mevduat", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT",
                               banka_karti_id=banka.id, acilis_bakiyesi=D("1000000"), aktif=True)
            kk = FinansHesabi(hesap_adi="Akbank Kredi Kartı", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI",
                              banka_karti_id=banka.id, acilis_bakiyesi=D("0"), aktif=True)
            kasa = FinansHesabi(hesap_adi="Merkez Kasa", hesap_turu="KASA", acilis_bakiyesi=D("1000000"), aktif=True)
            s.add_all([mev, kk, kasa])
            s.flush()
            kart = KrediKartiTanimi(banka_karti_id=banka.id, kart_adi="Akbank Business", hesap_kesim_gunu=5,
                                    son_odeme_gunu=15, aktif=True)
            h = HizmetKarti(hizmet_kodu="SGK", hizmet_adi="SGK primi", hizmet_turu="GIDER", aktif=True)
            s.add_all([kart, h])
            s.flush()
            self.banka_id, self.mev_id, self.kk_id, self.kasa_id = banka.id, mev.id, kk.id, kasa.id
            self.kart_id, self.hizmet_id = kart.id, h.id
        self.sgk = self.plan("SGK_VERGI", "SGK primi", 31, "12000")
        self._anahtar = 0

    def tearDown(self):
        self.ort.kapat()

    # ------------------------------------------------------------------ yardımcılar
    def plan(self, kategori, ad, gun, tutar, ay="10.2026") -> int:
        return sg.plan_kaydet({"kategori": kategori, "ad": ad, "periyot": "AYLIK", "odeme_gunu": gun,
                               "tutar": tutar, "baslangic_ay": ay, "bitis_ay": ay})

    def anahtar(self) -> str:
        self._anahtar += 1
        return f"test-{self._anahtar}"

    def ode(self, plan=None, *, tutar="12000", faiz=gk.FAIZSIZ, plan_id=None, ucret=None, anahtar=None,
            kaynak=..., tarih=ISLEM, kart_id=None):
        if plan is None:
            plan = gk.esit_taslak(self.kart_id, K1, 3, tutar)
        if kaynak is ...:
            kaynak = {"tur": gk.KAYNAK_SABIT, "plan_id": plan_id or self.sgk, "yil": tarih.year, "ay": tarih.month}
        with bugun(tarih):
            return gk.kart_ile_ode(istek_anahtari=anahtar or self.anahtar(), kredi_karti_id=kart_id or self.kart_id,
                                   islem_tarihi=tarih, gider_tutari=tutar, plan=plan, faiz_durumu=faiz,
                                   hizmet_id=self.hizmet_id, kaynak=kaynak, ucret=ucret)

    def sabit_kalan(self, plan_id=None, yil=2026, ay=10) -> D:
        with get_session() as s:
            donem_id = sg._donem_al(s, plan_id or self.sgk, yil, ay).id
        with get_session() as s:
            from database.models.sabit_gider import SabitGiderDonemi

            return sg.donem_ozeti(s, s.get(SabitGiderDonemi, donem_id), date.max)["kalan"]

    def takvim(self, gun=ISLEM):
        v = ots.hesapla(gun)
        return [a["toplam"] for a in v["aylar"]], v["genel_toplam"], v

    def kart_satirlari(self, v) -> dict[date, D]:
        return {k["kesim"]: k["kalan"] for a in v["aylar"] for k in a["kalemler"] if k["tur"] == ots.TUR_KART}

    def ekstre(self, kesim: date) -> dict:
        return next(h for h in E.ekstreleri_hesapla(kredi_karti_id=self.kart_id, odenenleri_dahil=True)
                    if h["kesim_tarihi"] == kesim)

    def hareket_sayisi(self, hesap_id) -> int:
        with get_session() as s:
            return s.scalar(select(func.count(FinansHareketi.id)).where(FinansHareketi.hesap_id == hesap_id))

    def say(self, model) -> int:
        with get_session() as s:
            return s.scalar(select(func.count(model.id)))

    # ------------------------------------------------------------------ 1. gider türleri
    def test_01_gider_turleri_ayni_islev(self):
        kira = self.plan("KIRA", "Mağaza kirası", 20, "20000")
        muh = self.plan("MUHASEBE", "Muhasebe ücreti", 25, "3000")
        self.ode(tutar="12000")
        self.ode(gk.esit_taslak(self.kart_id, K1, 1, "20000"), tutar="20000", plan_id=kira)
        self.ode(gk.esit_taslak(self.kart_id, K1, 2, "3000"), tutar="3000", plan_id=muh)
        self.ode(gk.esit_taslak(self.kart_id, K1, 1, "750"), tutar="750", kaynak=None)  # doğrudan gider fişi
        self.assertEqual([self.sabit_kalan(p) for p in (self.sgk, kira, muh)], [D("0.00")] * 3)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(GiderKartOdeme.id))), 4)
            self.assertEqual(s.scalar(select(func.count(GiderFisi.id)).where(GiderFisi.finans_hesap_id == self.kk_id)), 4)
        self.assertEqual(self.ekstre(K1)["tl_tutar"], D("4000.00") + D("20000") + D("1500") + D("750"))

    # ------------------------------------------------------------------ 2. tek çekim
    def test_02_tek_cekim_bir_kez_dogru_ekstreye(self):
        plan = gk.esit_taslak(self.kart_id, K1, 1, "12000")
        sonuc = self.ode(plan)
        self.assertEqual(self.sabit_kalan(), D("0.00"))
        _a, genel, v = self.takvim()
        self.assertEqual(self.kart_satirlari(v), {K1: D("12000.00")})
        self.assertEqual(genel, D("12000.00"))
        with get_session() as s:
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
            self.assertEqual((ko.cekim_turu, ko.cari_id, ko.kaynak_turu, len(ko.taksitler)),
                             ("TEK_CEKIM", 0, "GIDER", 1))

    # ------------------------------------------------------------------ 3. üç taksit (örnek tablo)
    def test_03_uc_taksit_ornek_tablo(self):
        taslak = gk.esit_taslak(self.kart_id, K1, 3, "12000")
        self.assertEqual([(r["kesim"], r["gun"], r["tutar"]) for r in taslak], [
            (K1, "Perşembe", D("4000.00")), (K2, "Cumartesi", D("4000.00")), (K3, "Salı", D("4000.00"))])
        with get_session() as s:
            once = s.scalar(select(func.count(GiderKartOdeme.id)))
        aylar, genel, v = self.takvim()
        self.assertEqual((aylar[0], genel), (D("12000.00"), D("12000.00")))  # SGK 31.10 satırı, kart yok
        self.assertEqual(once, 0)
        sonuc = self.ode(taslak)
        self.assertEqual(self.sabit_kalan(), D("0.00"))
        aylar, genel, v = self.takvim()
        self.assertEqual(aylar, [D("0.00"), D("4000.00"), D("4000.00"), D("4000.00")])
        self.assertEqual(genel, D("12000.00"))  # gider kapandı, yük kartta sürüyor
        self.assertNotIn(ots.TUR_VERGI, {k["tur"] for a in v["aylar"] for k in a["kalemler"]})
        detay = v["aylar"][1]["kalemler"][0]["detay"]
        self.assertIn(sonuc["gider_fisi"], detay[0]["aciklama"])
        self.assertIn("SGK primi 10.2026", detay[0]["aciklama"])
        satirlar = self.ekstre(K1)["satirlar"] if "satirlar" in self.ekstre(K1) else None
        if satirlar is not None:
            self.assertTrue(any(r.get("kaynak_gider") for r in satirlar))

    # ------------------------------------------------------------------ 4. kısmi ödeme
    def test_04_kismi_odeme(self):
        self.ode(gk.esit_taslak(self.kart_id, K1, 1, "5000"), tutar="5000")
        self.assertEqual(self.sabit_kalan(), D("7000.00"))
        aylar, genel, v = self.takvim()
        self.assertEqual(aylar[0], D("7000.00"))
        self.assertEqual(self.kart_satirlari(v), {K1: D("5000.00")})
        self.assertEqual(genel, D("12000.00"))
        with self.assertRaises(ValueError):  # kalanı aşan kart ödemesi
            self.ode(gk.esit_taslak(self.kart_id, K1, 1, "7000.01"), tutar="7000.01")

    # ------------------------------------------------------------------ 5. finansman farkı
    def test_05_finansman_farki_bir_kez(self):
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H

        plan = gk.esit_taslak(self.kart_id, K1, 3, "12300")
        self.assertEqual([r["tutar"] for r in plan], [D("4100.00")] * 3)
        with self.assertRaises(ValueError):  # faizsiz onayı ile fark kaydedilmez
            self.ode(plan, faiz=gk.FAIZSIZ)
        with self.assertRaises(ValueError):  # bilinmeyen faiz sıfır sayılmaz
            self.ode(plan, faiz=None)
        sonuc = self.ode(plan, faiz=gk.FAIZ_GIRILDI)
        self.assertEqual((sonuc["gider_tutari"], sonuc["kart_toplami"], sonuc["finansman_farki"]),
                         (D("12000.00"), D("12300.00"), D("300.00")))
        self.assertEqual(self.sabit_kalan(), D("0.00"))
        self.assertEqual(self.takvim()[1], D("12300.00"))
        with patch.object(H, "_hesap", staticmethod(lambda a, session=None: {"id": a})), \
                patch.object(H, "_finans_karsiligi_ayarli", staticmethod(lambda h, s: {"id": "KART"})):
            with get_session() as s:
                ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
                fis = H._plan_kart_odeme(s, ko.id)
        self.assertEqual([(r["hesap_id"], r["borc"], r["alacak"]) for r in fis["satirlar"]],
                         [("kredi_diger_finansman", D("300.00"), D("0")), ("KART", D("0"), D("300.00"))])

    def test_05b_ayri_ucret_kendi_doneminde_fark_tek_fiste(self):
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H

        plan = gk.esit_taslak(self.kart_id, K1, 3, "12000")
        sonuc = self.ode(plan, faiz=gk.FAIZ_GIRILDI, ucret={"tutar": "300", "kesim": K2})
        self.assertEqual(sonuc["finansman_farki"], D("300.00"))
        self.assertEqual(self.ekstre(K2)["tl_tutar"], D("4300.00"))
        self.assertEqual(self.ekstre(K1)["tl_tutar"], D("4000.00"))
        with patch.object(H, "_hesap", staticmethod(lambda a, session=None: {"id": a})), \
                patch.object(H, "_finans_karsiligi_ayarli", staticmethod(lambda h, s: {"id": "KART"})):
            with get_session() as s:
                fisler = [H._plan_kart_odeme(s, ko.id) for ko in s.scalars(select(KrediKartiOdeme)).all()]
        farklar = [r["borc"] for f in fisler if f for r in f["satirlar"] if r["hesap_id"] == "kredi_diger_finansman"]
        self.assertEqual(farklar, [D("300.00")])

    # ------------------------------------------------------------------ 6. kuruş ve dönem
    def test_06_kurus_ve_donem(self):
        taslak = gk.esit_taslak(self.kart_id, K1, 3, "1000")
        self.assertEqual([r["tutar"] for r in taslak], [D("333.33"), D("333.33"), D("333.34")])
        p = self.plan("DIGER", "Diğer gider", 30, "1000")
        with self.assertRaises(ValueError):  # banka planı yeniden yuvarlanmaz: kuruştan küçük basamak
            self.ode([{"kesim": K1, "tutar": "333.333"}, {"kesim": K2, "tutar": "666.667"}], tutar="1000", plan_id=p)
        with self.assertRaises(ValueError):  # toplam uyuşmazlığı
            self.ode([{"kesim": K1, "tutar": "500"}, {"kesim": K2, "tutar": "499.99"}], tutar="1000", plan_id=p)
        with self.assertRaises(ValueError):  # kartın kesim günü olmayan tarih
            self.ode([{"kesim": date(2026, 11, 6), "tutar": "1000"}], tutar="1000", plan_id=p)
        with self.assertRaises(ValueError):  # işlemden önce kesilmiş ekstre
            self.ode([{"kesim": date(2026, 10, 5), "tutar": "1000"}], tutar="1000", plan_id=p)
        # Banka ilk taksiti sonraki döneme erteleyebilir
        secenek = gk.ilk_kesim_secenekleri(self.kart_id, ISLEM)
        self.assertEqual([r["kesim"] for r in secenek], [K1, K2, K3, K4])
        sonuc = self.ode(gk.esit_taslak(self.kart_id, K2, 3, "1000"), tutar="1000", plan_id=p)
        with get_session() as s:
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
            self.assertEqual([(t.ekstre_kesim_tarihi, t.tutar) for t in ko.taksitler],
                             [(K2, D("333.33")), (K3, D("333.33")), (K4, D("333.34"))])
            self.assertEqual(sum(t.tutar for t in ko.taksitler), ko.tutar)

    # ------------------------------------------------------------------ 7. pencere dışı
    def test_07_pencere_disi_subat_taksiti(self):
        self.ode(gk.esit_taslak(self.kart_id, K1, 4, "12000"))
        _a, genel, v = self.takvim(ISLEM)
        self.assertEqual(genel, D("9000.00"))
        self.assertNotIn(K4, self.kart_satirlari(v))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(KrediKartiOdemeTaksit.id))), 4)
        _a, genel, v = self.takvim(date(2026, 11, 1))
        self.assertEqual(genel, D("12000.00"))
        self.assertEqual(self.kart_satirlari(v)[K4], D("3000.00"))

    # ------------------------------------------------------------------ 8. ekstre ödeme
    def test_08_ekstre_odemesi_yalniz_o_donemi_azaltir(self):
        self.ode()
        with bugun(date(2026, 11, 10)):
            E.odeme_yap(ekstre_id=self.ekstre(K1)["ekstre_id"], tutar="4000", finans_hesap_id=self.mev_id)
        _a, genel, v = self.takvim(date(2026, 11, 10))
        self.assertEqual(self.kart_satirlari(v), {K2: D("4000.00"), K3: D("4000.00")})
        self.assertEqual(genel, D("8000.00"))
        self.assertEqual(self.sabit_kalan(), D("0.00"))  # gider tekrar açılmaz

    # ------------------------------------------------------------------ 9. iptal ve mükerrerlik
    def test_09_mukerrer_kayit_yok(self):
        plan = gk.esit_taslak(self.kart_id, K1, 3, "12000")
        ilk = self.ode(plan, anahtar="ayni")
        ikinci = self.ode(plan, anahtar="ayni")
        self.assertTrue(ikinci["mevcut"])
        self.assertEqual(ilk["kart_odeme"], ikinci["kart_odeme"])
        self.assertEqual((self.say(GiderKartOdeme), self.say(KrediKartiOdeme), self.say(KrediKartiOdemeTaksit),
                          self.say(GiderFisi), self.say(SabitGiderBaglanti)), (1, 1, 3, 1, 1))

    def test_09b_hata_olursa_yarim_kayit_kalmaz(self):
        with patch("database.sabit_gider_service._baglanti_yaz", side_effect=RuntimeError("kesinti")):
            with self.assertRaises(RuntimeError):
                self.ode()
        self.assertEqual((self.say(GiderKartOdeme), self.say(KrediKartiOdeme), self.say(KrediKartiOdemeTaksit),
                          self.say(GiderFisi), self.say(FinansHareketi)), (0, 0, 0, 0, 0))
        self.assertEqual(self.sabit_kalan(), D("12000.00"))

    def test_09c_hatali_kayit_iptali_birlikte_geri_alir(self):
        sonuc = self.ode()
        with bugun(ISLEM):
            gk.iptal(sonuc["id"], "Yanlış kart seçildi")
        self.assertEqual(self.sabit_kalan(), D("12000.00"))
        _a, genel, v = self.takvim()
        self.assertEqual((self.kart_satirlari(v), genel), ({}, D("12000.00")))
        with get_session() as s:
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
            fis = s.scalar(select(GiderFisi).where(GiderFisi.belge_no == sonuc["gider_fisi"]))
            g = s.get(GiderKartOdeme, sonuc["id"])
            self.assertEqual((ko.durum, fis.durum, g.durum), ("İPTAL", "IPTAL", "IPTAL"))
            turler = sorted(h.hareket_turu for h in s.scalars(select(FinansHareketi).where(
                FinansHareketi.hesap_id == self.kk_id)).all())
            self.assertEqual(turler, ["KK ÖDEME", "KK ÖDEME İPTAL"])  # silinmez, ters hareket görünür
            self.assertEqual(len(ko.taksitler), 3)
        with self.assertRaises(ValueError):
            with bugun(ISLEM):
                gk.iptal(sonuc["id"], "tekrar")

    def test_09d_odenmis_donemde_iptal_yok_banka_iadesi(self):
        sonuc = self.ode()
        with bugun(date(2026, 11, 10)):
            E.odeme_yap(ekstre_id=self.ekstre(K1)["ekstre_id"], tutar="4000", finans_hesap_id=self.mev_id)
            with self.assertRaises(ValueError):
                gk.iptal(sonuc["id"], "Banka iptal etti")
        with bugun(date(2026, 11, 20)):
            iade = gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 20), tutar="4000", istek_anahtari="iade-1")
            tekrar = gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 20), tutar="4000", istek_anahtari="iade-1")
            with self.assertRaises(ValueError):  # iade edilebilir tutarı aşan iade
                gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 20), tutar="8000.01", istek_anahtari="iade-2")
        self.assertTrue(tekrar["mevcut"])
        self.assertEqual(iade["kesim"], K2)  # iade tarihinin ekstresi
        k1 = self.ekstre(K1)
        self.assertEqual((k1["tl_tutar"], k1["odenen"]), (D("4000.00"), D("4000.00")))  # kapanmış dönem aynı
        self.assertNotIn(K2, self.kart_satirlari(self.takvim(date(2026, 11, 20))[2]))
        self.assertEqual(self.sabit_kalan(), D("4000.00"))  # gider kalanı iade kadar açıldı
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(KrediKartiOdeme.id)).where(
                KrediKartiOdeme.cekim_turu == "IADE")), 1)

    # ------------------------------------------------------------------ 10. kasa ve banka
    def test_10_kartla_odemede_cikis_yok_ekstre_odemesinde_bir_kez(self):
        once = (self.hareket_sayisi(self.kasa_id), self.hareket_sayisi(self.mev_id))
        self.ode()
        self.assertEqual((self.hareket_sayisi(self.kasa_id), self.hareket_sayisi(self.mev_id)), once)
        with get_session() as s:
            kk = s.scalars(select(FinansHareketi).where(FinansHareketi.hesap_id == self.kk_id)).all()
            self.assertEqual([(h.hareket_turu, h.tutar) for h in kk], [("KK ÖDEME", D("12000.00"))])
        with bugun(date(2026, 11, 10)):
            E.odeme_yap(ekstre_id=self.ekstre(K1)["ekstre_id"], tutar="4000", finans_hesap_id=self.mev_id)
        self.assertEqual(self.hareket_sayisi(self.mev_id), once[1] + 1)
        self.assertEqual(self.hareket_sayisi(self.kasa_id), once[0])

    # ------------------------------------------------------------------ kart bilgileri
    def test_kesim_gunu_eksik_kaydeder_son_odeme_eksik_uyarir(self):
        """Kesim günü tanımsız kartla gider kaydedilir (borç bakiye ve limitte), takvimde 'Eksik bilgi';
        gün sonradan girilince dönemler yeni hareket olmadan belirlenir."""
        with get_session() as s:
            k1 = KrediKartiTanimi(banka_karti_id=self.banka_id, kart_adi="Kesimsiz", hesap_kesim_gunu=None,
                                  son_odeme_gunu=15, kart_limiti=D("50000"), aktif=True)
            k2 = KrediKartiTanimi(banka_karti_id=self.banka_id, kart_adi="Son ödemesiz", hesap_kesim_gunu=5,
                                  son_odeme_gunu=None, aktif=True)
            s.add_all([k1, k2])
            s.flush()
            kesimsiz, sonsuz = k1.id, k2.id
            ozet = gk.kart_ozeti(k2)
            ozet_kesimsiz = gk.kart_ozeti(k1)
        self.assertFalse(ozet["son_odeme_bilinir"])
        self.assertTrue(ozet["uyarilar"])
        self.assertTrue(ozet_kesimsiz["uyarilar"])
        with self.assertRaises(ValueError):
            self.ode([{"kesim": K1, "tutar": "12000"}], kart_id=kesimsiz)
        taslak = gk.esit_taslak(kesimsiz, None, 3, "12000")
        self.assertEqual([t["kesim"] for t in taslak], [None, None, None])
        kk_once = self.hareket_sayisi(self.kk_id)
        self.ode(taslak, kart_id=kesimsiz, kaynak=None)
        self.assertEqual(self.hareket_sayisi(self.kk_id), kk_once + 1)
        oz = E.kart_borc_ozeti(kesimsiz)
        self.assertEqual((oz["toplam_borc"], oz["kullanilan"], oz["kullanilabilir"], oz["belirsiz"]),
                         (D("12000.00"), D("12000.00"), D("38000.00"), D("12000.00")))
        _a, _g, v = self.takvim()
        self.assertIn(("Kesimsiz", D("12000.00")), {(e["ad"], e["tutar"]) for e in v["eksikler"]})
        with get_session() as s:
            s.get(KrediKartiTanimi, kesimsiz).hesap_kesim_gunu = 5
        self.assertEqual(self.hareket_sayisi(self.kk_id), kk_once + 1)
        with bugun(ISLEM):
            kesimler = {h["kesim_tarihi"]: h["tl_tutar"]
                        for h in E.ekstreleri_hesapla(kredi_karti_id=kesimsiz, odenenleri_dahil=True)}
        self.assertEqual(kesimler, {K1: D("4000.00"), K2: D("4000.00"), K3: D("4000.00")})
        self.assertEqual(E.kart_borc_ozeti(kesimsiz)["belirsiz"], D("0.00"))
        self.ode(gk.esit_taslak(sonsuz, K1, 1, "12000"), kart_id=sonsuz)
        _a, _g, v = self.takvim()
        self.assertIn("Son ödemesiz", {e["ad"] for e in v["eksikler"]})
        satir = next(h for h in E.ekstreleri_hesapla(kredi_karti_id=sonsuz) if h["kesim_tarihi"] == K1)
        self.assertIsNone(satir["son_odeme_tarihi"])
        self.assertEqual(satir["ekstre_durum"], "EKSIK_BILGI")

    def test_baglanti_elle_iptal_ve_ekleme_engellenir(self):
        sonuc = self.ode()
        with get_session() as s:
            b = s.scalar(select(SabitGiderBaglanti))
            bid, donem_id = b.id, b.donem_id
        with self.assertRaises(ValueError):
            sg.baglanti_iptal(bid, "elle")
        with self.assertRaises(ValueError):
            sg.baglanti_ekle(donem_id, sonuc["kart_odeme"], "100")
        from database.finans_service import FinansService

        with get_session() as s:
            fis_id = s.scalar(select(GiderFisi.id).where(GiderFisi.belge_no == sonuc["gider_fisi"]))
        with self.assertRaises(ValueError):
            FinansService.gider_fisi_iptal(fis_id)

    # ------------------------------------------------------------------ kayıt düzeltmesi / banka iadesi
    def ikinci_kart(self, limit="50000") -> tuple[int, int]:
        with get_session() as s:
            banka = BankaKarti(banka_adi="Garanti", sube="Merkez", aktif=True)
            s.add(banka)
            s.flush()
            kk = FinansHesabi(hesap_adi="Garanti Kredi Kartı", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI",
                              banka_karti_id=banka.id, acilis_bakiyesi=D("0"), aktif=True)
            kart = KrediKartiTanimi(banka_karti_id=banka.id, kart_adi="Garanti Bonus", hesap_kesim_gunu=5,
                                    son_odeme_gunu=15, kart_limiti=D(limit), aktif=True)
            s.add_all([kk, kart])
            s.flush()
            return kart.id, kk.id

    def bakiye(self, hesap_id, gun=None) -> D:
        from database.finans_service import FinansService

        with get_session() as s:
            q = select(FinansHareketi).where(FinansHareketi.hesap_id == hesap_id)
            if gun is not None:
                q = q.where(FinansHareketi.tarih <= gun)
            return sum((D(str(h.tutar)) * FinansService.hareket_isareti(h.hareket_turu) for h in s.scalars(q)),
                       D("0"))

    def ekstre_kart(self, kart_id, kesim: date) -> dict:
        return next(h for h in E.ekstreleri_hesapla(kredi_karti_id=kart_id, odenenleri_dahil=True)
                    if h["kesim_tarihi"] == kesim)

    def fis_planlari(self) -> dict:
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H

        with patch.object(H, "_hesap", staticmethod(lambda a, session=None: {"id": a})), \
                patch.object(H, "_finans_karsiligi_ayarli", staticmethod(lambda h, s: {"id": "KART"})), \
                patch.object(H, "gider_fisi_hesaplari", staticmethod(lambda fid, session=None: ["GIDER"])):
            with get_session() as s:
                return {ko.belge_no: H._plan_kart_odeme(s, ko.id)
                        for ko in s.scalars(select(KrediKartiOdeme).order_by(KrediKartiOdeme.id)).all()}

    @staticmethod
    def hesap_toplami(planlar: dict, hesap: str, alan: str) -> D:
        return sum((r[alan] for f in planlar.values() if f for r in f["satirlar"] if r["hesap_id"] == hesap), D("0"))

    def iade_sayisi(self) -> int:
        from database.models.finans import GiderKartIade

        with get_session() as s:
            return (s.scalar(select(func.count(KrediKartiOdeme.id)).where(KrediKartiOdeme.cekim_turu == "IADE"))
                    + s.scalar(select(func.count(GiderKartIade.id))))

    def test_11_duzeltme_odemeden_once_tutar_kart_taksit(self):
        sonuc = self.ode()  # 12.000, 3 taksit, Akbank
        kart2, kk2 = self.ikinci_kart()
        with bugun(date(2026, 11, 2)):
            r = gk.duzelt(sonuc["id"], istek_anahtari="dz-1", neden="Yanlış kart ve tutar seçildi",
                          gider_tutari="11400", plan=gk.esit_taslak(kart2, K1, 2, "11400"), faiz_durumu=gk.FAIZSIZ,
                          kredi_karti_id=kart2)
        self.assertEqual(r["tur"], gk.DUZELTME_TAM)
        self.assertEqual((r["eski"]["gider_tutari"], r["eski"]["kart"], r["yeni"]["gider_tutari"], r["yeni"]["kart"]),
                         ("12000.00", "Akbank Business", "11400.00", "Garanti Bonus"))
        self.assertEqual(self.iade_sayisi(), 0)  # düzeltme iade değildir
        self.assertEqual(self.sabit_kalan(), D("600.00"))  # gider yalnız düzeltilmiş tutar kadar kapalı
        with get_session() as s:
            eski = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
            self.assertEqual((eski.durum, len(eski.taksitler)), (gk.DUZELTILDI, 3))  # silinmez
            fisler = {f.belge_no: (f.durum, f.tutar) for f in s.scalars(select(GiderFisi)).all()}
            self.assertEqual(fisler[sonuc["gider_fisi"]][0], "IPTAL")
            self.assertEqual(sorted(v for v in fisler.values() if v[0] == "AÇIK"), [("AÇIK", D("11400.00"))])
            baglantilar = s.scalars(select(SabitGiderBaglanti).where(SabitGiderBaglanti.iptal.is_(False))).all()
            self.assertEqual([D(str(b.tutar)) for b in baglantilar], [D("11400.00")])
            turler = sorted(h.hareket_turu for h in s.scalars(select(FinansHareketi).where(
                FinansHareketi.hesap_id == self.kk_id)).all())
            self.assertEqual(turler, ["KK ÖDEME", "KK ÖDEME DÜZELTME"])
        self.assertEqual((self.bakiye(self.kk_id), self.bakiye(kk2)), (D("0.00"), D("11400.00")))
        self.assertEqual(E.kart_borc_ozeti(self.kart_id)["toplam_borc"], D("0.00"))
        oz2 = E.kart_borc_ozeti(kart2)
        self.assertEqual((oz2["toplam_borc"], oz2["kullanilabilir"]), (D("11400.00"), D("38600.00")))
        _a, _g, v = self.takvim(date(2026, 11, 2))
        self.assertEqual(self.kart_satirlari(v), {K1: D("5700.00"), K2: D("5700.00")})
        self.assertIsNone(self.fis_planlari()[sonuc["kart_odeme"]])  # düzeltilen kaydın fişi yeniden oluşmaz

        # Aynı kartta yalnız taksit sayısı düzeltmesi; geçmiş iki satır olarak kalır
        with bugun(date(2026, 11, 3)):
            r2 = gk.duzelt(sonuc["id"], istek_anahtari="dz-2", neden="Banka 3 taksit yaptı", gider_tutari="11400",
                           plan=gk.esit_taslak(kart2, K1, 3, "11400"), faiz_durumu=gk.FAIZSIZ)
        self.assertEqual(r2["eski"]["kart_kayitlari"], [r["yeni_kayitlar"]])
        _a, _g, v = self.takvim(date(2026, 11, 3))
        self.assertEqual(self.kart_satirlari(v), {K1: D("3800.00"), K2: D("3800.00"), K3: D("3800.00")})
        self.assertEqual(self.bakiye(kk2), D("11400.00"))
        bilgi = gk.duzeltme_bilgisi(sonuc["id"])
        self.assertEqual([(h["neden"], h["tur"]) for h in bilgi["gecmis"]],
                         [("Yanlış kart ve tutar seçildi", "TAM"), ("Banka 3 taksit yaptı", "TAM")])
        self.assertEqual(self.iade_sayisi(), 0)

    def test_12_duzeltme_mukerrer_degil(self):
        from database.models.finans import GiderKartDuzeltme

        sonuc = self.ode()
        plan = gk.esit_taslak(self.kart_id, K1, 4, "12000")
        with bugun(date(2026, 11, 1)):
            r1 = gk.duzelt(sonuc["id"], istek_anahtari="ayni", neden="4 taksit", gider_tutari="12000", plan=plan,
                           faiz_durumu=gk.FAIZSIZ)
            r2 = gk.duzelt(sonuc["id"], istek_anahtari="ayni", neden="4 taksit", gider_tutari="12000", plan=plan,
                           faiz_durumu=gk.FAIZSIZ)
            with self.assertRaises(ValueError):  # değişiklik yoksa düzeltme kaydı oluşmaz
                gk.duzelt(sonuc["id"], istek_anahtari="baska", neden="tekrar", gider_tutari="12000", plan=plan,
                          faiz_durumu=gk.FAIZSIZ)
            with self.assertRaises(ValueError):  # neden zorunlu
                gk.duzelt(sonuc["id"], istek_anahtari="nedensiz", neden=" ", gider_tutari="11000",
                          plan=gk.esit_taslak(self.kart_id, K1, 1, "11000"), faiz_durumu=gk.FAIZSIZ)
        self.assertTrue(r2["mevcut"])
        self.assertEqual(r1["duzeltme_id"], r2["duzeltme_id"])
        self.assertEqual((self.say(GiderKartDuzeltme), self.say(KrediKartiOdeme), self.say(GiderKartOdeme),
                          self.hareket_sayisi(self.kk_id)), (1, 2, 1, 3))
        self.assertEqual(self.bakiye(self.kk_id), D("12000.00"))
        self.assertEqual(self.takvim(date(2026, 11, 1))[1], D("12000.00"))

    def test_13_ilk_ekstre_odendikten_sonra_duzeltme(self):
        sonuc = self.ode()
        with bugun(date(2026, 11, 10)):
            E.odeme_yap(ekstre_id=self.ekstre(K1)["ekstre_id"], tutar="4000", finans_hesap_id=self.mev_id)
        kart2, _kk2 = self.ikinci_kart()
        dogru = [{"kesim": K1, "tutar": "4000"}, {"kesim": K2, "tutar": "4150"}, {"kesim": K3, "tutar": "4150"}]
        with bugun(date(2026, 11, 11)):
            with self.assertRaises(ValueError):  # ödenmiş dönem kartın ekstresinde kalır
                gk.duzelt(sonuc["id"], istek_anahtari="x1", neden="kart", gider_tutari="12000",
                          plan=gk.esit_taslak(kart2, K1, 3, "12000"), faiz_durumu=gk.FAIZSIZ, kredi_karti_id=kart2)
            with self.assertRaises(ValueError):  # kapanmış dönem plandan çıkarılamaz
                gk.duzelt(sonuc["id"], istek_anahtari="x2", neden="plan", gider_tutari="12000",
                          plan=[{"kesim": K2, "tutar": "6000"}, {"kesim": K3, "tutar": "6000"}], faiz_durumu=gk.FAIZSIZ)
            r = gk.duzelt(sonuc["id"], istek_anahtari="dz-acik", neden="Banka faiz yansıttı", gider_tutari="12000",
                          plan=dogru, faiz_durumu=gk.FAIZ_GIRILDI)
        self.assertEqual(r["tur"], gk.DUZELTME_ACIK_DONEM)
        k1 = self.ekstre(K1)
        self.assertEqual((k1["tl_tutar"], k1["odenen"]), (D("4000.00"), D("4000.00")))  # kapanmış dönem aynı
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(KrediKartiOdemeTaksit.id)).where(
                KrediKartiOdemeTaksit.ekstre_kesim_tarihi == K1)), 1)
            ana = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == sonuc["kart_odeme"]))
            self.assertEqual(ana.durum, "AÇIK")  # ödenmiş taksiti taşıyan kayıt korunur
        self.assertEqual((self.ekstre(K2)["tl_tutar"], self.ekstre(K3)["tl_tutar"]), (D("4150.00"), D("4150.00")))
        self.assertEqual(E.kart_borc_ozeti(self.kart_id)["toplam_borc"], D("8300.00"))
        self.assertEqual(self.bakiye(self.kk_id), D("8300.00"))
        planlar = self.fis_planlari()
        self.assertEqual(self.hesap_toplami(planlar, "kredi_diger_finansman", "borc"), D("300.00"))  # bir kez
        self.assertEqual(self.sabit_kalan(), D("0.00"))
        self.assertEqual(self.iade_sayisi(), 0)

        # Kapanmış dönemin tutarı da hatalıymış: fark ilk açık döneme ayrı satır olarak yazılır
        with bugun(date(2026, 11, 12)):
            gk.duzelt(sonuc["id"], istek_anahtari="dz-kapali", neden="1. taksit 3.900 olmalıydı",
                      gider_tutari="12000", plan=[{"kesim": K1, "tutar": "3900"}, {"kesim": K2, "tutar": "4150"},
                                                  {"kesim": K3, "tutar": "4250"}], faiz_durumu=gk.FAIZ_GIRILDI)
        self.assertEqual(self.ekstre(K1)["tl_tutar"], D("4000.00"))
        self.assertEqual((self.ekstre(K2)["tl_tutar"], self.ekstre(K3)["tl_tutar"]), (D("4050.00"), D("4250.00")))
        self.assertEqual(E.kart_borc_ozeti(self.kart_id)["toplam_borc"], D("8300.00"))
        self.assertEqual(self.hesap_toplami(self.fis_planlari(), "kredi_diger_finansman", "borc"), D("300.00"))

    def test_14_iade_faiz_ve_ucret_ilgili_kayitlara_bagli(self):
        from database.models.finans import GiderKartIade

        sonuc = self.ode(gk.esit_taslak(self.kart_id, K1, 3, "12300"), faiz=gk.FAIZ_GIRILDI,
                         ucret={"tutar": "300", "kesim": K2})
        self.assertEqual(sonuc["finansman_farki"], D("600.00"))
        with bugun(date(2026, 11, 10)):
            E.odeme_yap(ekstre_id=self.ekstre(K1)["ekstre_id"], tutar="4100", finans_hesap_id=self.mev_id)
        with bugun(date(2026, 11, 20)):
            r = gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 20), tutar="4000", faiz_tutari="300",
                               ucret_tutari="300", istek_anahtari="iade-tam")
            with self.assertRaises(ValueError):  # faiz payı tükendi
                gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 20), tutar="0", faiz_tutari="0.01",
                               istek_anahtari="iade-faiz")
            with self.assertRaises(ValueError):  # iadeden sonra kayıt düzeltmesi yok
                gk.duzelt(sonuc["id"], istek_anahtari="dz", neden="x", gider_tutari="8000",
                          plan=gk.esit_taslak(self.kart_id, K1, 1, "8000"), faiz_durumu=gk.FAIZSIZ)
        self.assertEqual((r["tutar"], r["gider"], r["faiz"], r["ucret"], r["kesim"]),
                         (D("4600.00"), D("4000.00"), D("300.00"), D("300.00"), K2))
        with get_session() as s:
            i = s.scalar(select(GiderKartIade))
            g = s.get(GiderKartOdeme, sonuc["id"])
            self.assertEqual((i.faiz_kk_odeme_id, i.ucret_kk_odeme_id), (g.kk_odeme_id, g.ucret_kk_odeme_id))
        self.assertEqual(self.sabit_kalan(), D("4000.00"))  # yalnız ana para gideri açar
        k1 = self.ekstre(K1)
        self.assertEqual((k1["tl_tutar"], k1["odenen"]), (D("4100.00"), D("4100.00")))
        self.assertEqual(self.ekstre(K2)["tl_tutar"], D("-200.00"))  # 4.100 + 300 ücret − 4.600 iade
        planlar = self.fis_planlari()
        iade_fisi = planlar[r["belge_no"]]
        self.assertEqual([(x["hesap_id"], x["borc"], x["alacak"]) for x in iade_fisi["satirlar"]],
                         [("KART", D("4600.00"), D("0")), ("GIDER", D("0"), D("4000.00")),
                          ("kredi_diger_finansman", D("0"), D("600.00"))])
        self.assertEqual(self.hesap_toplami(planlar, "kredi_diger_finansman", "borc"), D("600.00"))
        self.assertEqual(self.hesap_toplami(planlar, "kredi_diger_finansman", "alacak"), D("600.00"))

    def test_15_kismi_iade_ucret_ve_kalan_faiz_acik_kalir(self):
        sonuc = self.ode(gk.esit_taslak(self.kart_id, K1, 3, "12300"), faiz=gk.FAIZ_GIRILDI,
                         ucret={"tutar": "300", "kesim": K2})
        with bugun(date(2026, 11, 2)):
            r = gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 2), tutar="2000", faiz_tutari="100",
                               istek_anahtari="iade-kismi")
        self.assertEqual((r["tutar"], r["kesim"]), (D("2100.00"), K1))
        satir = next(x for x in gk.liste() if x["id"] == sonuc["id"])
        self.assertEqual((satir["iade_edilebilir"], satir["faiz_iade_edilebilir"], satir["ucret_iade_edilebilir"]),
                         (D("10000.00"), D("200.00"), D("300.00")))
        self.assertEqual(self.sabit_kalan(), D("2000.00"))
        self.assertEqual((self.ekstre(K1)["tl_tutar"], self.ekstre(K2)["tl_tutar"]), (D("2000.00"), D("4400.00")))
        with get_session() as s:
            g = s.get(GiderKartOdeme, sonuc["id"])
            uk = s.get(KrediKartiOdeme, g.ucret_kk_odeme_id)
            self.assertEqual((g.durum, uk.durum, [t.durum for t in uk.taksitler]), ("AÇIK", "AÇIK", ["BEKLIYOR"]))
        planlar = self.fis_planlari()
        self.assertEqual([(x["hesap_id"], x["borc"], x["alacak"]) for x in planlar[r["belge_no"]]["satirlar"]],
                         [("KART", D("2100.00"), D("0")), ("GIDER", D("0"), D("2000.00")),
                          ("kredi_diger_finansman", D("0"), D("100.00"))])
        self.assertEqual(self.hesap_toplami(planlar, "kredi_diger_finansman", "borc"), D("600.00"))

    def test_16_iade_edilmeyen_masraf_kendiliginden_kapanmaz(self):
        sonuc = self.ode(gk.esit_taslak(self.kart_id, K1, 3, "12300"), faiz=gk.FAIZ_GIRILDI,
                         ucret={"tutar": "300", "kesim": K2})
        with bugun(date(2026, 11, 2)):
            gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 2), tutar="12000", istek_anahtari="iade-gider")
            with self.assertRaises(ValueError):  # gider payı tükendi; fazlası faiz / ücret olarak girilmeli
                gk.iade_kaydet(sonuc["id"], tarih=date(2026, 11, 2), tutar="0.01", istek_anahtari="iade-fazla")
        self.assertEqual(self.sabit_kalan(), D("12000.00"))
        self.assertEqual(E.kart_borc_ozeti(self.kart_id)["toplam_borc"], D("600.00"))  # faiz + ücret bankada
        satir = next(x for x in gk.liste() if x["id"] == sonuc["id"])
        self.assertEqual((satir["durum"], satir["faiz_iade_edilebilir"], satir["ucret_iade_edilebilir"]),
                         ("AÇIK", D("300.00"), D("300.00")))
        with get_session() as s:
            acik = [o.durum for o in s.scalars(select(KrediKartiOdeme).where(
                KrediKartiOdeme.cekim_turu != "IADE")).all()]
        self.assertEqual(acik, ["AÇIK", "AÇIK"])
        planlar = self.fis_planlari()
        self.assertEqual(self.hesap_toplami(planlar, "kredi_diger_finansman", "alacak"), D("0"))

    def test_17_donen_sermaye_ve_gecmis_tarih_tek_sayim(self):
        from database import donen_sermaye_service as ds
        from database import giris_ozet_service as go

        sonuc = self.ode()
        with bugun(date(2026, 11, 2)):
            gk.duzelt(sonuc["id"], istek_anahtari="dz-ds", neden="Tutar 11.400", gider_tutari="11400",
                      plan=gk.esit_taslak(self.kart_id, K1, 3, "11400"), faiz_durumu=gk.FAIZSIZ)

        def kart_satiri(gun):
            with get_session() as s:
                fin, _n, _e = ds._finans(go._Baglam(s, gun, gun, None))
            return sum((x["tutar"] for x in fin["kartlar"]), D("0"))

        def donem_toplami(gun):
            with get_session() as s:
                return E.donem_borclari(s, tarih=gun, kart_ids=[self.kart_id])[self.kart_id]["toplam_borc"]

        self.assertEqual(abs(kart_satiri(date(2026, 11, 1))), D("12000.00"))  # düzeltmeden önce kayıtlı tutar
        self.assertEqual(abs(kart_satiri(date(2026, 11, 2))), D("11400.00"))  # 23.400 değil
        self.assertEqual(donem_toplami(date(2026, 11, 1)), D("11400.00"))  # düzeltilmiş plan; çift sayım yok
        self.assertEqual(donem_toplami(date(2026, 11, 2)), D("11400.00"))
        self.assertEqual(self.iade_sayisi(), 0)


class GecisTest(unittest.TestCase):
    def test_eski_veritabani_ekleyerek_gecer_veri_korunur(self):
        klasor = tempfile.mkdtemp(prefix="gk_gecis_")
        yol = os.path.join(klasor, "eski.db")
        motor = create_engine(f"sqlite:///{yol}")
        try:
            with motor.begin() as b:
                b.execute(text("CREATE TABLE kredi_karti_odemeleri (id INTEGER PRIMARY KEY, belge_no VARCHAR(50), "
                               "tarih DATE, vade_tarihi DATE, banka_karti_id INTEGER, kredi_karti_id INTEGER, "
                               "cari_id INTEGER NOT NULL, cekim_turu VARCHAR(20), taksit_sayisi INTEGER, "
                               "tutar NUMERIC(18,2), referans_no VARCHAR(50), aciklama VARCHAR(500), durum VARCHAR(20))"))
                b.execute(text("CREATE TABLE kredi_karti_odeme_taksitleri (id INTEGER PRIMARY KEY, odeme_id INTEGER, "
                               "taksit_no INTEGER, vade_tarihi DATE, tutar NUMERIC(18,2), durum VARCHAR(20))"))
                b.execute(text("INSERT INTO kredi_karti_odemeleri VALUES (1,'KKO-1','2026-10-01','2026-10-01',1,1,7,"
                               "'TEK_CEKIM',1,500,NULL,NULL,'AÇIK')"))
                b.execute(text("INSERT INTO kredi_karti_odeme_taksitleri VALUES (1,1,1,'2026-10-01',500,'BEKLIYOR')"))
            gk.schema_hazirla(motor)
            gk._HAZIR.discard(motor)
            gk.schema_hazirla(motor)  # ikinci çalıştırma değişiklik yapmaz
            ins = inspect(motor)
            self.assertTrue(ins.has_table("gider_kart_odemeleri"))
            self.assertTrue(ins.has_table("gider_kart_duzeltmeleri"))
            self.assertTrue(ins.has_table("gider_kart_iadeleri"))
            self.assertIn("ekstre_kesim_tarihi", {c["name"] for c in ins.get_columns("kredi_karti_odeme_taksitleri")})
            self.assertTrue({"finansman_farki", "duzeltme_id"} <= {c["name"] for c in
                                                                   ins.get_columns("kredi_karti_odemeleri")})
            with motor.connect() as b:
                satir = b.execute(text("SELECT cari_id, tutar, kaynak_turu, gider_kart_odeme_id, finansman_farki "
                                       "FROM kredi_karti_odemeleri")).one()
                self.assertEqual((satir[0], D(str(satir[1])), satir[2], satir[3], satir[4]),
                                 (7, D("500"), "CARI", None, None))
                self.assertIsNone(b.execute(text("SELECT ekstre_kesim_tarihi FROM kredi_karti_odeme_taksitleri"))
                                  .scalar())
                self.assertEqual(b.execute(text("SELECT surum FROM modul_sema_surumleri WHERE modul='gider_kart_odeme'"))
                                 .scalar(), 2)
        finally:
            motor.dispose()


if __name__ == "__main__":
    unittest.main()
