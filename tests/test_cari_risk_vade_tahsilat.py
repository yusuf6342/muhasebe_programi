"""Cari risk/limit, vade farkı oranı ve tahsilatta açık borç seçimi (talimat örnekleri).

Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu); gerçek firma verisine dokunmaz.
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text

from database import cari_risk_service as crs
from database.acik_kalem_service import AcikKalemDegisti, AcikKalemService, dagitim_onizleme
from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.cek_senet import CekSenetEvrak
from database.session_manager import oturum
from tests import test_tahsilat_makbuzu as _servis_testi

D = Decimal


def _kalem(s, cari_id, belge, tarih, tutar):
    h = SatisHareketi(cari_id=cari_id, satis_tarihi=tarih, belge_no=belge,
                      satis_tutari=D(tutar), kalan_acik_tutar=D(tutar))
    s.add(h)
    s.flush()
    return h.id


def _kalan(hid):
    with get_session() as s:
        return D(str(s.get(SatisHareketi, hid).kalan_acik_tutar))


def _avans(cari_id):
    with get_session() as s:
        return sum((-D(str(h.kalan_acik_tutar)) for h in s.scalars(
            select(SatisHareketi).where(SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar < 0)
        ).all()), D("0"))


def _evrak(s, cari_id, no, tur, tutar, durum, vade=None):
    e = CekSenetEvrak(
        evrak_turu=tur, islem_yonu="ALINAN", evrak_no=no, portfoy_no=f"P-{no}", cari_id=cari_id,
        duzenleme_tarihi=date(2026, 1, 1), vade_tarihi=vade or date(2026, 12, 31),
        doviz_turu="TL", doviz_tutari=D(tutar), kur=D("1"), tl_tutari=D(tutar), kalan_tutar=D(tutar),
        durum=durum, aktif=True,
    )
    s.add(e)
    s.flush()
    return e.id


class Temel(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())
        crs.schema_hazirla(self.eng)
        with get_session() as s:
            c = Cari(cari_kodu="M700", unvan="RİSK TEST MÜŞTERİ", cari_turu="Müşteri")
            s.add(c)
            s.flush()
            self.cid = c.id

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def _limitler(self, **ek):
        return CariService.guncelle(self.cid, dict(ek))


class LimitKayitTest(Temel):
    def test_eski_kart_limit_kapali_varsayilan(self):
        cari = CariService.getir(self.cid)
        self.assertFalse(cari.acik_hesap_limit_uygula)
        self.assertFalse(cari.toplam_limit_uygula)
        ozet = crs.risk_ozeti(self.cid)
        self.assertEqual(ozet["satirlar"][crs.TUR_TOPLAM]["etiket"], "Limit tanımlı değil")

    def test_limit_kaydet_yeniden_ac(self):
        self._limitler(acik_hesap_risk_limiti="120.000,00", acik_hesap_limit_uygula=True,
                       toplam_risk_limiti="150000", toplam_limit_uygula=True)
        cari = CariService.getir(self.cid)
        self.assertEqual((D(str(cari.acik_hesap_risk_limiti)), cari.acik_hesap_limit_uygula),
                         (D("120000.00"), True))
        self.assertEqual(D(str(cari.toplam_risk_limiti)), D("150000.00"))
        self.assertFalse(cari.cek_limit_uygula)

    def test_bos_limit_sifira_cevrilmez_negatif_reddedilir(self):
        with self.assertRaises(ValueError):
            self._limitler(acik_hesap_risk_limiti="", acik_hesap_limit_uygula=True)
        with self.assertRaises(ValueError):
            self._limitler(acik_hesap_risk_limiti="-5", acik_hesap_limit_uygula=True)
        self.assertFalse(CariService.getir(self.cid).acik_hesap_limit_uygula)

    def test_limitsiz_ile_sifir_limit_farkli(self):
        self.assertEqual(crs.limit_durumu(D("0"), None, False)["durum"], crs.DURUM_TANIMSIZ)
        self.assertEqual(crs.limit_durumu(D("0"), D("0"), True)["etiket"], "Limit dolu")
        d = crs.limit_durumu(D("100"), D("0"), True)
        self.assertEqual((d["durum"], d["asim"], d["kalan"]), (crs.DURUM_ASILDI, D("100.00"), D("-100.00")))

    def test_yetkisiz_kullanici_limit_degistiremez(self):
        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"cari_duzenleme", "goruntuleme", "yeni_kayit", "duzenleme"})
        with self.assertRaises(PermissionError):
            self._limitler(acik_hesap_risk_limiti="1000", acik_hesap_limit_uygula=True)
        self.assertFalse(CariService.getir(self.cid).acik_hesap_limit_uygula)


class RiskHesapTest(Temel):
    def _ornek(self):
        with get_session() as s:
            _kalem(s, self.cid, "SF-100", date(2026, 1, 5), "100000")
            self.cek = _evrak(s, self.cid, "C1", "MUSTERI_CEKI", "40000", "CIRO_EDILDI",
                              vade=date.today() - timedelta(days=10))
            self.senet = _evrak(s, self.cid, "S1", "MUSTERI_SENEDI", "20000", "CIRO_EDILDI")
        self._limitler(toplam_risk_limiti="150000", toplam_limit_uygula=True,
                       acik_hesap_risk_limiti="120000", acik_hesap_limit_uygula=True)

    def test_160_bin_risk_150_bin_limit_10_bin_asim(self):
        self._ornek()
        ozet = crs.risk_ozeti(self.cid)
        s = ozet["satirlar"]
        self.assertEqual((s[crs.TUR_ACIK]["risk"], s[crs.TUR_CEK]["risk"], s[crs.TUR_SENET]["risk"]),
                         (D("100000.00"), D("40000.00"), D("20000.00")))
        self.assertEqual(s[crs.TUR_TOPLAM]["risk"], D("160000.00"))
        self.assertEqual((s[crs.TUR_TOPLAM]["asim"], s[crs.TUR_TOPLAM]["etiket"]), (D("10000.00"), "Limit aşıldı"))
        self.assertEqual((s[crs.TUR_ACIK]["kalan"], s[crs.TUR_ACIK]["durum"]), (D("20000.00"), crs.DURUM_UYGUN))
        self.assertEqual(len(ozet["detay"][crs.TUR_CEK]), 1)

    def test_vadesi_gecen_ciro_riskte_kalir_karsiliksiz_cift_sayilmaz(self):
        self._ornek()
        self.assertEqual(crs.risk_ozeti(self.cid)["satirlar"][crs.TUR_CEK]["risk"], D("40000.00"))
        from database.models.cek_senet import CekSenetHareket

        with get_session() as s:
            s.get(CekSenetEvrak, self.cek).durum = "KARSILIKSIZ"
            kalem = _kalem(s, self.cid, "KRS-C1", date.today(), "40000")
            # karsiliksiz_protesto: cariye geri borç + cari_hareket_id bağlı evrak hareketi
            s.add(CekSenetHareket(evrak_id=self.cek, onceki_durum="CIRO_EDILDI", yeni_durum="KARSILIKSIZ",
                                  islem_turu="KARSILIKSIZ", tutar=D("40000"), cari_hareket_id=kalem))
        s2 = crs.risk_ozeti(self.cid)["satirlar"]
        self.assertEqual((s2[crs.TUR_CEK]["risk"], s2[crs.TUR_ACIK]["risk"]), (D("0.00"), D("140000.00")))
        self.assertEqual(s2[crs.TUR_TOPLAM]["risk"], D("160000.00"))

    def test_karsiliksiz_geri_borc_yoksa_risk_kaybolmaz(self):
        self._ornek()
        with get_session() as s:
            s.get(CekSenetEvrak, self.cek).durum = "KARSILIKSIZ"
        ozet = crs.risk_ozeti(self.cid)
        self.assertEqual(ozet["satirlar"][crs.TUR_PORTFOY]["risk"], D("40000.00"))
        self.assertEqual(ozet["satirlar"][crs.TUR_TOPLAM]["risk"], D("160000.00"))
        diger = {b["bilesen"]: b for b in ozet["genel"]["bilesenler"]}[crs.BILESEN_DIGER_CEK]
        self.assertEqual(diger["ham"], D("40000.00"))

    def test_ciro_kapanisi_kesinlesince_risk_duser(self):
        from database.cek_senet_service import CekSenetService

        self._ornek()
        with self.assertRaises(ValueError):
            CekSenetService.ciro_kapanisi_kesinlestir(self.senet, aciklama="")
        CekSenetService.ciro_kapanisi_kesinlestir(self.senet, aciklama="Lehtar ödemeyi teyit etti")
        self.assertEqual(crs.risk_ozeti(self.cid)["satirlar"][crs.TUR_SENET]["risk"], D("0.00"))

    def test_avans_bir_kez_dusulur(self):
        with get_session() as s:
            _kalem(s, self.cid, "SF-1", date(2026, 1, 5), "1000")
        CariService.tahsilat_yap(self.cid, date.today(), "1300", "NAKİT", "TEST KASA", None)
        ozet = crs.risk_ozeti(self.cid)
        self.assertEqual((ozet["avans"], ozet["satirlar"][crs.TUR_ACIK]["risk"]), (D("300.00"), D("0.00")))

    def test_islem_kontrolu_ve_olay_kaydi(self):
        self._ornek()
        k = crs.islem_kontrolu(self.cid, D("30000"))
        asim = {a["tur"]: a for a in k["asimlar"]}
        self.assertEqual((asim[crs.TUR_ACIK]["yeni"], asim[crs.TUR_ACIK]["asim"]), (D("130000.00"), D("10000.00")))
        self.assertEqual(asim[crs.TUR_TOPLAM]["asim"], D("40000.00"))
        self.assertEqual(k["politika"], crs.POLITIKA_UYARI)
        self.assertEqual(crs.islem_kontrolu(self.cid, D("-5000"))["asimlar"], [])
        crs.olay_kaydet(k, belge_turu="Satış Faturası", belge_no="SF-TEST", karar=crs.KARAR_UYARI_GECILDI,
                        gerekce="Yönetici onayı")
        olaylar = crs.olaylar(self.cid)
        self.assertEqual(len(olaylar), 2)
        self.assertTrue(all(o["kullanici"] == "admin" and o["gerekce"] == "Yönetici onayı" for o in olaylar))

    def test_politika_ayari_ve_gecmisi(self):
        self.assertEqual(crs.politika_ayarla("ENGEL"), crs.POLITIKA_ENGEL)
        self.assertEqual(crs.politika_getir(), crs.POLITIKA_ENGEL)
        self.assertEqual(crs.degisiklik_gecmisi(0)[0]["yeni"], "ENGEL")


class VadeFarkiTest(Temel):
    def test_oran_kaydi_borc_uretmez_gecmis_tutulur(self):
        with get_session() as s:
            once = s.scalar(select(func.count(CariIslem.id)))
        self._limitler(vade_farki_aylik_oran="2,50", vade_farki_yillik_oran="30", vade_farki_donem="AYLIK",
                       vade_farki_aciklama="Peşin dışı satış")
        cari = CariService.getir(self.cid)
        self.assertEqual((D(str(cari.vade_farki_aylik_oran)), D(str(cari.vade_farki_yillik_oran))),
                         (D("2.5000"), D("30.0000")))
        self.assertEqual(cari.vade_farki_donem, crs.DONEM_AYLIK)
        sabit = crs.vade_farki_sabitle(cari)
        self.assertEqual((sabit["donem"], sabit["oran"]), (crs.DONEM_AYLIK, D("2.5000")))
        self._limitler(vade_farki_aylik_oran="3")
        self.assertEqual(sabit["oran"], D("2.5000"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CariIslem.id))), once)
        gecmis = crs.degisiklik_gecmisi(self.cid, ["vade_farki_aylik_oran"])
        self.assertEqual([(g["eski"], g["yeni"]) for g in gecmis], [("2.5", "3"), ("", "2.5")])

    def test_oran_dogrulama(self):
        with self.assertRaises(ValueError):
            self._limitler(vade_farki_aylik_oran="-1")
        with self.assertRaises(ValueError):
            self._limitler(vade_farki_yillik_oran="abc")
        with self.assertRaises(ValueError):
            self._limitler(vade_farki_yillik_oran="", vade_farki_donem="YILLIK")


class DagitimOnizlemeTest(unittest.TestCase):
    KALEMLER = [
        {"hareket_id": 1, "tarih": date(2026, 1, 1), "evrak_no": "A", "kalan": D("8000"), "kapanan": D("0")},
        {"hareket_id": 2, "tarih": date(2026, 2, 1), "evrak_no": "B", "kalan": D("12000"), "kapanan": D("0")},
        {"hareket_id": 3, "tarih": date(2026, 3, 1), "evrak_no": "C", "kalan": D("5000"), "kapanan": D("0")},
    ]

    def test_secimsiz_fifo(self):
        o = dagitim_onizleme(self.KALEMLER, D("15000"))
        self.assertEqual(o["mod"], "Otomatik FIFO")
        self.assertEqual(o["dagitim"], [(1, D("8000.00")), (2, D("7000.00"))])
        self.assertEqual((o["satirlar"][1]["durum"], o["satirlar"][2]["sonra"]), ("Kapalı", D("5000.00")))

    def test_secili_b_c_tiklama_sirasi_onemsiz(self):
        for secim in ([2, 3], [3, 2]):
            o = dagitim_onizleme(self.KALEMLER, D("15000"), secim)
            self.assertEqual(o["dagitim"], [(2, D("12000.00")), (3, D("3000.00"))])
            self.assertEqual((o["satirlar"][3]["sonra"], o["satirlar"][3]["durum"]), (D("2000.00"), "Kısmen Kapalı"))
            self.assertEqual((o["secilen_toplam"], o["artan"]), (D("17000.00"), D("0.00")))

    def test_artan_avans_veya_istenirse_fifo(self):
        o = dagitim_onizleme(self.KALEMLER, D("20000"), [2, 3])
        self.assertEqual((o["dagitilan"], o["artan"]), (D("17000.00"), D("3000.00")))
        o2 = dagitim_onizleme(self.KALEMLER, D("20000"), [2, 3], artani_fifo=True)
        self.assertEqual((o2["satirlar"][1]["kapanacak"], o2["artan"]), (D("3000.00"), D("0.00")))

    def test_kismi_kapatma(self):
        o = dagitim_onizleme([{"hareket_id": 9, "tarih": date(2026, 1, 1), "evrak_no": "X", "kalan": D("6000"),
                               "kapanan": D("0")}], D("4000"), [9])
        self.assertEqual((o["satirlar"][9]["sonra"], o["satirlar"][9]["durum"]), (D("2000.00"), "Kısmen Kapalı"))


class TahsilatServisTest(Temel):
    def setUp(self):
        super().setUp()
        with get_session() as s:
            self.a = _kalem(s, self.cid, "A", date(2026, 1, 1), "8000")
            self.b = _kalem(s, self.cid, "B", date(2026, 2, 1), "12000")
            self.c = _kalem(s, self.cid, "C", date(2026, 3, 1), "5000")
            diger = Cari(cari_kodu="M701", unvan="DİĞER MÜŞTERİ", cari_turu="Müşteri")
            s.add(diger)
            s.flush()
            self.diger = _kalem(s, diger.id, "D", date(2025, 1, 1), "1000")

    def _plan(self, tutar, secim, artani_fifo=False):
        kalemler = AcikKalemService.secim_listesi_getir(self.cid)
        o = dagitim_onizleme(kalemler, D(tutar), secim, artani_fifo=artani_fifo)
        beklenen = {int(k["hareket_id"]): k["kalan"] for k in kalemler if int(k["hareket_id"]) in set(secim)}
        return o, beklenen

    def test_fifo_15_bin(self):
        CariService.tahsilat_yap(self.cid, date.today(), "15000", "NAKİT", "TEST KASA", None)
        self.assertEqual((_kalan(self.a), _kalan(self.b), _kalan(self.c)), (D("0.00"), D("5000.00"), D("5000.00")))
        self.assertEqual(_kalan(self.diger), D("1000.00"))

    def test_secili_b_c_15_bin_a_dokunulmaz(self):
        o, beklenen = self._plan("15000", [self.c, self.b])
        CariService.tahsilat_yap(self.cid, date.today(), "15000", "NAKİT", "TEST KASA", None,
                                 dagitim=o["dagitim"], fazla="AVANS", beklenen=beklenen)
        self.assertEqual((_kalan(self.a), _kalan(self.b), _kalan(self.c)), (D("8000.00"), D("0.00"), D("2000.00")))

    def test_secili_20_bin_artan_avans(self):
        o, beklenen = self._plan("20000", [self.b, self.c])
        CariService.tahsilat_yap(self.cid, date.today(), "20000", "NAKİT", "TEST KASA", None,
                                 dagitim=o["dagitim"], fazla="AVANS", beklenen=beklenen)
        self.assertEqual((_kalan(self.a), _kalan(self.b), _kalan(self.c)), (D("8000.00"), D("0.00"), D("0.00")))
        self.assertEqual(_avans(self.cid), D("3000.00"))

    def test_baska_carinin_belgesi_kapatilamaz(self):
        with self.assertRaises(ValueError):
            CariService.tahsilat_yap(self.cid, date.today(), "500", "NAKİT", "TEST KASA", None,
                                     dagitim=[(self.diger, D("500"))], fazla="AVANS")
        self.assertEqual(_kalan(self.diger), D("1000.00"))

    def test_eszamanli_degisiklik_yarim_kayit_birakmaz(self):
        o, beklenen = self._plan("5000", [self.b])
        with self.eng.begin() as baglanti:
            baglanti.execute(text("UPDATE cari_satis_hareketleri SET kalan_acik_tutar = 3000 WHERE id = :i"),
                             {"i": self.b})
        with get_session() as s:
            once = s.scalar(select(func.count(CariIslem.id)))
        with self.assertRaises(AcikKalemDegisti):
            CariService.tahsilat_yap(self.cid, date.today(), "5000", "NAKİT", "TEST KASA", None,
                                     dagitim=o["dagitim"], fazla="AVANS", beklenen=beklenen)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CariIslem.id))), once)
        self.assertEqual(_kalan(self.b), D("3000.00"))

    def test_makbuz_secili_kapatma_iptalde_bir_kez_geri_alinir(self):
        o, beklenen = self._plan("15000", [self.b, self.c])
        m = FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": date.today(), "cari_id": self.cid, "makbuz_no_otomatik": True,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "15000"}],
            "kapatma_dagitimi": [{"hareket_id": h, "tutar": t} for h, t in o["dagitim"]],
            "kapatma_fazla": "AVANS",
            "kapatma_beklenen": beklenen,
        })
        self.assertEqual((_kalan(self.b), _kalan(self.c)), (D("0.00"), D("2000.00")))
        FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual((_kalan(self.a), _kalan(self.b), _kalan(self.c)),
                         (D("8000.00"), D("12000.00"), D("5000.00")))
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual((_kalan(self.b), _kalan(self.c)), (D("12000.00"), D("5000.00")))

    def test_makbuz_eski_bakiye_ile_kaydedilmez(self):
        o, beklenen = self._plan("4000", [self.c])
        with self.eng.begin() as baglanti:
            baglanti.execute(text("UPDATE cari_satis_hareketleri SET kalan_acik_tutar = 1000 WHERE id = :i"),
                             {"i": self.c})
        with self.assertRaises(AcikKalemDegisti):
            FinansService.kasa_tahsilat_makbuzu_kaydet({
                "tarih": date.today(), "cari_id": self.cid, "makbuz_no_otomatik": True,
                "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "4000"}],
                "kapatma_dagitimi": [{"hareket_id": h, "tutar": t} for h, t in o["dagitim"]],
                "kapatma_fazla": "AVANS",
                "kapatma_beklenen": beklenen,
            })
        self.assertEqual(_kalan(self.c), D("1000.00"))


class MakbuzDuzenlemeTest(Temel):
    """Kayıtlı makbuz düzenlemesi: A 8.000 / B 12.000 / C 5.000; makbuz 15.000 ile B+C seçili kaydedilir."""

    def setUp(self):
        super().setUp()
        from database.models.cari import CariKapatma

        self.CariKapatma = CariKapatma
        with get_session() as s:
            self.a = _kalem(s, self.cid, "A", date(2026, 1, 1), "8000")
            self.b = _kalem(s, self.cid, "B", date(2026, 2, 1), "12000")
            self.c = _kalem(s, self.cid, "C", date(2026, 3, 1), "5000")
        kalemler = AcikKalemService.secim_listesi_getir(self.cid)
        o = dagitim_onizleme(kalemler, D("15000"), [self.b, self.c])
        self.m = FinansService.kasa_tahsilat_makbuzu_kaydet(self._veri("15000", o["dagitim"], "AVANS", {
            self.b: D("12000"), self.c: D("5000")}))

    def _veri(self, tutar, dagitim=None, fazla="AVANS", beklenen=None):
        v = {"tarih": date.today(), "cari_id": self.cid, "makbuz_no_otomatik": True,
             "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": str(tutar)}]}
        if dagitim:
            v.update({"kapatma_dagitimi": [{"hareket_id": h, "tutar": t} for h, t in dagitim],
                      "kapatma_fazla": fazla, "kapatma_beklenen": beklenen or {}})
        return v

    def _kalanlar(self):
        return _kalan(self.a), _kalan(self.b), _kalan(self.c)

    def _plan_veri(self, plan, tutar):
        return self._veri(tutar, plan["dagitim"], plan["fazla"], plan["beklenen"])

    def test_kayitli_secim_ve_dagitim_yuklenir(self):
        from acik_kalem_secim_ui import kayitli_plan

        self.assertEqual(self._kalanlar(), (D("8000.00"), D("0.00"), D("2000.00")))
        plan = kayitli_plan(self.cid, self.m.belge_no, D("15000"))
        self.assertEqual(plan["secili"], sorted([self.b, self.c]))
        self.assertEqual(plan["dagitim"], [(self.b, D("12000.00")), (self.c, D("3000.00"))])
        self.assertEqual(plan["fazla"], "AVANS")
        self.assertEqual(plan["beklenen"], {self.b: D("12000.00"), self.c: D("5000.00")})
        liste = {k["hareket_id"]: k for k in AcikKalemService.secim_listesi_getir(
            self.cid, haric_belge_no=self.m.belge_no)}
        self.assertEqual((liste[self.b]["kalan"], liste[self.b]["kayitli_dagitim"]), (D("12000.00"), D("12000.00")))
        self.assertEqual(liste[self.c]["kalan"], D("5000.00"))

    def test_degismeyen_duzenleme_secimi_korur_fifoya_donmez(self):
        from acik_kalem_secim_ui import kayitli_plan

        plan = kayitli_plan(self.cid, self.m.belge_no, D("15000"))
        FinansService.kasa_makbuz_guncelle(self.m.id, self._plan_veri(plan, "15000"))
        self.assertEqual(self._kalanlar(), (D("8000.00"), D("0.00"), D("2000.00")))
        with get_session() as s:
            aktif = s.scalars(select(self.CariKapatma).where(
                self.CariKapatma.kaynak_belge_no == self.m.belge_no, self.CariKapatma.iptal.is_(False))).all()
            self.assertEqual(sorted((k.hedef_hareket_id, D(str(k.tutar)), k.yontem) for k in aktif),
                             sorted([(self.b, D("12000.00"), "MANUEL"), (self.c, D("3000.00"), "MANUEL")]))

    def test_tutar_degisince_secili_belgeler_icinde_kismi_yeniden_hesap(self):
        kalemler = AcikKalemService.secim_listesi_getir(self.cid, haric_belge_no=self.m.belge_no)
        for tutar, beklenen_c in (("13000", D("4000.00")), ("16500", D("500.00"))):
            o = dagitim_onizleme(kalemler, D(tutar), [self.b, self.c])
            beklenen = {h: k["kalan"] for k in kalemler for h in (k["hareket_id"],) if h in (self.b, self.c)}
            FinansService.kasa_makbuz_guncelle(self.m.id, self._veri(tutar, o["dagitim"], "AVANS", beklenen))
            self.assertEqual(self._kalanlar(), (D("8000.00"), D("0.00"), beklenen_c))
            kalemler = AcikKalemService.secim_listesi_getir(self.cid, haric_belge_no=self.m.belge_no)

    def _aktif_kapatmalar(self):
        with get_session() as s:
            return sorted((k.hedef_hareket_id, D(str(k.tutar)), k.yontem) for k in s.scalars(
                select(self.CariKapatma).where(self.CariKapatma.kaynak_belge_no == self.m.belge_no,
                                               self.CariKapatma.iptal.is_(False))))

    def _cari_islem_sayisi(self):
        with get_session() as s:
            return s.scalar(select(func.count()).select_from(CariIslem).where(CariIslem.cari_id == self.cid))

    def test_hatali_duzenleme_eski_kaydi_eksiksiz_korur(self):
        once = (self._kalanlar(), _avans(self.cid), self._aktif_kapatmalar(), self._cari_islem_sayisi())
        kalemler = AcikKalemService.secim_listesi_getir(self.cid, haric_belge_no=self.m.belge_no)
        o = dagitim_onizleme(kalemler, D("13000"), [self.b, self.c])
        with self.assertRaises(AcikKalemDegisti):
            FinansService.kasa_makbuz_guncelle(self.m.id, self._veri(
                "13000", o["dagitim"], "AVANS", {self.b: D("99999"), self.c: D("5000")}))
        self.assertEqual((self._kalanlar(), _avans(self.cid), self._aktif_kapatmalar(),
                          self._cari_islem_sayisi()), once)

    def test_ayni_duzenleme_tekrar_kaydedilince_mukerrer_olusmaz(self):
        from acik_kalem_secim_ui import kayitli_plan

        sayi = self._cari_islem_sayisi()
        for _ in range(2):
            plan = kayitli_plan(self.cid, self.m.belge_no, D("15000"))
            FinansService.kasa_makbuz_guncelle(self.m.id, self._plan_veri(plan, "15000"))
        self.assertEqual(self._cari_islem_sayisi(), sayi)
        self.assertEqual((*self._kalanlar(), _avans(self.cid)), (D("8000.00"), D("0.00"), D("2000.00"), D("0")))
        self.assertEqual(self._aktif_kapatmalar(),
                         sorted([(self.b, D("12000.00"), "MANUEL"), (self.c, D("3000.00"), "MANUEL")]))

    def test_secim_temizlenirse_fifo(self):
        FinansService.kasa_makbuz_guncelle(self.m.id, self._veri("15000"))
        self.assertEqual(self._kalanlar(), (D("0.00"), D("5000.00"), D("5000.00")))

    def test_duzenleme_sonrasi_iptal_kayitli_dagitimlari_bir_kez_geri_alir(self):
        kalemler = AcikKalemService.secim_listesi_getir(self.cid, haric_belge_no=self.m.belge_no)
        o = dagitim_onizleme(kalemler, D("20000"), [self.b, self.c])
        FinansService.kasa_makbuz_guncelle(self.m.id, self._veri("20000", o["dagitim"], "AVANS",
                                                                 {self.b: D("12000"), self.c: D("5000")}))
        self.assertEqual((*self._kalanlar(), _avans(self.cid)), (D("8000.00"), D("0.00"), D("0.00"), D("3000.00")))
        FinansService.kasa_makbuz_iptal(self.m.id)
        self.assertEqual((*self._kalanlar(), _avans(self.cid)),
                         (D("8000.00"), D("12000.00"), D("5000.00"), D("0")))
        with get_session() as s:
            aktif = s.scalars(select(self.CariKapatma).where(
                self.CariKapatma.kaynak_belge_no == self.m.belge_no, self.CariKapatma.iptal.is_(False))).all()
            self.assertEqual(aktif, [])
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(self.m.id)
        self.assertEqual(self._kalanlar(), (D("8000.00"), D("12000.00"), D("5000.00")))

    def test_ekran_duzenleme_akisi(self):
        from unittest.mock import patch

        import kasa_makbuz_ui
        from acik_kalem_secim_ui import AcikKalemSecimDialog

        root = tk.Tk()
        root.withdraw()
        mb = patch("kasa_makbuz_ui.messagebox")
        mb.start()
        try:
            d = kasa_makbuz_ui.KasaMakbuzDialog(root, "TAHSILAT", makbuz_id=self.m.id)
            d.duzenlemeye_gec()
            self.assertEqual(d.mod, "duzenle")
            self.assertEqual(d._kapatma_plani["secili"], sorted([self.b, self.c]))
            self.assertIn("kayıtlı dağıtım korunuyor", d.mesaj_lbl.cget("text"))
            # Değişiklik yok: pencere sorulmadan kayıtlı seçim korunur
            with patch("acik_kalem_secim_ui.kapatma_plani_sor") as sor:
                self.assertTrue(d.kaydet())
                sor.assert_not_called()
            self.assertEqual(self._kalanlar(), (D("8000.00"), D("0.00"), D("2000.00")))

            # Tutar değişince pencere kayıtlı seçimle açılır; dağıtım seçili belgeler içinde yeniden hesaplanır
            d.duzenlemeye_gec()
            d.satirlar[0]["tutar"] = D("13000")
            gorulen = {}

            def _pencere(parent, cari_id, tutar, **kw):
                kalemler = AcikKalemService.secim_listesi_getir(cari_id, haric_belge_no=kw["haric_belge_no"])
                p = AcikKalemSecimDialog(parent, cari_id, tutar, kalemler=kalemler,
                                         onceki_secim=kw["onceki_secim"], kayitli=kw["kayitli"],
                                         artani_fifo=kw["artani_fifo"])
                gorulen.update(secili=set(p.secili), dagit_c=p.tablo.set(str(self.c), "dagit"),
                               not_=p.duzenleme_lbl.cget("text"), korundu=p.onizleme["kayitli_korundu"])
                p.uygula()
                return True, p.sonuc

            with patch("acik_kalem_secim_ui.kapatma_plani_sor", side_effect=_pencere):
                self.assertTrue(d.kaydet())
            self.assertEqual(gorulen["secili"], {self.b, self.c})
            self.assertEqual((gorulen["dagit_c"], gorulen["korundu"]), ("1.000,00", False))
            self.assertIn("yeniden hesaplandı", gorulen["not_"])
            self.assertEqual(self._kalanlar(), (D("8000.00"), D("0.00"), D("4000.00")))
            d.destroy()
        finally:
            mb.stop()
            root.destroy()

    def test_secim_penceresi_kayitli_dagitim_ve_temizleme(self):
        from acik_kalem_secim_ui import AcikKalemSecimDialog, kayitli_plan

        plan = kayitli_plan(self.cid, self.m.belge_no, D("15000"))
        kalemler = AcikKalemService.secim_listesi_getir(self.cid, haric_belge_no=self.m.belge_no)
        root = tk.Tk()
        root.withdraw()
        try:
            p = AcikKalemSecimDialog(root, self.cid, D("15000"), kalemler=kalemler, onceki_secim=plan["secili"],
                                     kayitli=plan["kayitli"])
            self.assertTrue(p.onizleme["kayitli_korundu"])
            self.assertIn("kayitli", p.tablo.cget("displaycolumns"))
            self.assertEqual((p.tablo.set(str(self.b), "kayitli"), p.tablo.set(str(self.c), "dagit")),
                             ("12.000,00", "3.000,00"))
            p.temizle()
            self.assertEqual(p.onizleme["mod"], "Otomatik FIFO")
            self.assertIn("otomatik FIFO", p.duzenleme_lbl.cget("text"))
            p.uygula()
            self.assertIsNone(p.sonuc)
        finally:
            root.destroy()


class SecimEkraniTest(Temel):
    def setUp(self):
        super().setUp()
        with get_session() as s:
            self.a = _kalem(s, self.cid, "A", date(2026, 1, 1), "8000")
            self.b = _kalem(s, self.cid, "B", date(2026, 2, 1), "12000")
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        super().tearDown()

    def test_coklu_secim_yesil_ozet_ve_listeyi_kapat_secimi_korur(self):
        from acik_kalem_secim_ui import SECILI_ZEMIN, AcikKalemSecimDialog

        p = AcikKalemSecimDialog(self.root, self.cid, D("10000"), ust_bilgi={"cari": "RİSK TEST"})
        self.assertEqual(p.ozet_lbl["mod"].cget("text"), "Otomatik FIFO")
        p.secimi_degistir(self.b)
        self.assertEqual(str(p.tablo.tag_configure("secili", "background")), SECILI_ZEMIN)
        self.assertIn("secili", p.tablo.item(str(self.b), "tags"))
        self.assertEqual(p.ozet_lbl["mod"].cget("text"), "Seçilen Belgeler")
        self.assertEqual(p.tablo.set(str(self.b), "dagit"), "10.000,00")
        self.assertEqual(p.tablo.set(str(self.a), "dagit"), "")
        p.kapat()
        self.assertEqual(p.sonuc["dagitim"], [(self.b, D("10000.00"))])

    def test_risk_paneli_ve_kart(self):
        from cari_risk_ui import RiskLimitPaneli

        self._limitler(acik_hesap_risk_limiti="15000", acik_hesap_limit_uygula=True)
        panel = RiskLimitPaneli(self.root, cari_id_getir=lambda: self.cid)
        panel.doldur(CariService.getir(self.cid))
        panel.risk_goster(crs.risk_ozeti(self.cid))
        self.assertEqual(panel._hucre[(crs.TUR_ACIK, "risk")].cget("text"), "20.000,00 TL")
        self.assertEqual(panel._hucre[(crs.TUR_ACIK, "asim")].cget("text"), "5.000,00 TL")
        self.assertEqual(panel._hucre[(crs.TUR_ACIK, "durum")].cget("text"), "Limit aşıldı")
        self.assertEqual(panel._hucre[(crs.TUR_TOPLAM, "durum")].cget("text"), "Limit tanımlı değil")
        veri = panel.degerler()
        self.assertEqual((veri["acik_hesap_risk_limiti"], veri["acik_hesap_limit_uygula"]), ("15.000,00", True))
        panel.destroy()


if __name__ == "__main__":
    unittest.main()
