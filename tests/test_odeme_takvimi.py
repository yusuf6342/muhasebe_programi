"""Ödeme takvimi: dönem, gün adları, örnek tablo toplamları, kısmi / tam ödeme, iptal, kredi, sabit gider, kapsam."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import func, select

from tests.stok_test_ortami import StokOrtami

from database import odeme_takvimi_service as ots
from database import sabit_gider_service as sg
from database.database import get_session
from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
from database.models.finans import (
    BankaKarti,
    BankaKredisi,
    BankaKrediTaksit,
    FinansHareketi,
    FinansHesabi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)
from database.models.sabit_gider import SabitGiderDonemi

BUGUN = date(2026, 10, 13)


class OdemeTakvimiTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("odeme_takvimi")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Akbank", sube="Merkez", aktif=True)
            s.add(banka)
            s.flush()
            mev = FinansHesabi(hesap_adi="Akbank Mevduat", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT",
                               banka_karti_id=banka.id, acilis_bakiyesi=D("1000000"), aktif=True)
            kasa = FinansHesabi(hesap_adi="Merkez Kasa", hesap_turu="KASA", acilis_bakiyesi=D("1000000"), aktif=True)
            kk = FinansHesabi(hesap_adi="Akbank Kredi Kartı", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI",
                              banka_karti_id=banka.id, acilis_bakiyesi=D("0"), aktif=True)
            s.add_all([mev, kasa, kk])
            s.flush()
            self.banka_id, self.mev_id, self.kasa_id = banka.id, mev.id, kasa.id
        self._kart_no = 0

    def tearDown(self):
        self.ort.kapat()

    # ------------------------------------------------------------------ yardımcılar
    def kart(self, ad="Akbank Business", kesim=13, son=23, **ek) -> int:
        with get_session() as s:
            k = KrediKartiTanimi(banka_karti_id=self.banka_id, kart_adi=ad, hesap_kesim_gunu=kesim,
                                 son_odeme_gunu=son, aktif=True, **ek)
            s.add(k)
            s.flush()
            return int(k.id)

    def harcama(self, kart_id: int, tarih: date, *taksitler) -> str:
        self._kart_no += 1
        belge = f"KKO-T-{self._kart_no}"
        with get_session() as s:
            o = KrediKartiOdeme(belge_no=belge, tarih=tarih, vade_tarihi=tarih, banka_karti_id=self.banka_id,
                                kredi_karti_id=kart_id, cari_id=self.ort.ted_id,
                                cekim_turu="TEK_CEKIM" if len(taksitler) == 1 else "TAKSITLI",
                                taksit_sayisi=len(taksitler), tutar=sum((D(t) for t in taksitler), D(0)), durum="AÇIK")
            s.add(o)
            s.flush()
            for i, t in enumerate(taksitler, 1):
                s.add(KrediKartiOdemeTaksit(odeme_id=o.id, taksit_no=i, vade_tarihi=tarih, tutar=D(t)))
        return belge

    def kredi(self, ad="İşletme kredisi", vadeler=(), anapara="10000", faiz="2000", bsmv="500",
              durum="KULLANDIRILDI") -> list[int]:
        with get_session() as s:
            k = BankaKredisi(belge_no=f"KR-{ad}", banka_karti_id=self.banka_id, kredi_adi=ad, ana_para=D("100000"),
                             taksit_sayisi=len(vadeler), kullandirim_tarihi=date(2026, 1, 1),
                             ilk_taksit_tarihi=vadeler[0], durum=durum, para_birimi="TRY")
            s.add(k)
            s.flush()
            ids = []
            for i, v in enumerate(vadeler, 1):
                t = BankaKrediTaksit(kredi_id=k.id, taksit_no=i, vade_tarihi=v, anapara=D(anapara), faiz=D(faiz),
                                     bsmv=D(bsmv), masraf=D(0), durum="BEKLIYOR")
                s.add(t)
                s.flush()
                ids.append(int(t.id))
            return ids

    def ornek(self) -> int:
        """Talimattaki örnek: kart 30.000 + 3×25.000 tahmini, kredi 4×12.500, kira 20.000, vergi 6.000/6.500."""
        kid = self.kart()
        self.harcama(kid, date(2026, 9, 20), "10000")
        self.harcama(kid, date(2026, 9, 25), "20000")
        self.harcama(kid, date(2026, 10, 14), "25000", "25000", "25000")
        self.kredi(vadeler=[date(2026, 10, 16), date(2026, 11, 16), date(2026, 12, 16), date(2027, 1, 16)])
        sg.plan_kaydet({"kategori": "KIRA", "ad": "Mağaza kirası", "periyot": "AYLIK", "odeme_gunu": 20,
                        "tutar": "20000", "baslangic_ay": "10.2026"})
        pid = sg.plan_kaydet({"kategori": "SGK_VERGI", "ad": "Planlanmış vergi ödemesi", "periyot": "AYLIK",
                              "odeme_gunu": 26, "tutar": "6000", "baslangic_ay": "10.2026"})
        sg.plan_kaydet({"kategori": "SGK_VERGI", "ad": "Planlanmış vergi ödemesi", "periyot": "AYLIK",
                        "odeme_gunu": 26, "tutar": "6500", "baslangic_ay": "10.2026"}, pid, gecerli_ay="11.2026")
        return kid

    def toplamlar(self, bugun=BUGUN):
        v = ots.hesapla(bugun)
        return [a["toplam"] for a in v["aylar"]], v["genel_toplam"], v

    def ekstre_ode(self, kart_id: int, kesim: date, tutar) -> str:
        detay = next(h for h in E.ekstreleri_hesapla(kredi_karti_id=kart_id) if h["kesim_tarihi"] == kesim)
        return E.odeme_yap(ekstre_id=detay["ekstre_id"], tutar=tutar, finans_hesap_id=self.mev_id)["belge_no"]

    # ------------------------------------------------------------------ dönem ve gün adı
    def test_donem_dort_takvim_ayi_yil_ve_subat(self):
        self.assertEqual(ots.donem(date(2026, 10, 12)), (date(2026, 10, 1), date(2027, 1, 31)))
        self.assertEqual(ots.donem(date(2026, 11, 1)), (date(2026, 11, 1), date(2027, 2, 28)))
        self.assertEqual(ots.donem(date(2027, 11, 30)), (date(2027, 11, 1), date(2028, 2, 29)))
        self.assertEqual(ots.donem(date(2026, 12, 31)), (date(2026, 12, 1), date(2027, 3, 31)))

    def test_gun_adlari(self):
        self.assertEqual(ots.gun_adi(date(2026, 10, 13)), "Salı")
        self.assertEqual(ots.gun_adi(date(2026, 10, 16)), "Cuma")
        self.assertEqual(ots.gun_adi(date(2026, 12, 13)), "Pazar")
        self.assertEqual(ots.gun_adi(date(2027, 1, 16)), "Cumartesi")

    # ------------------------------------------------------------------ örnek tablo
    def test_ornek_tablo_toplamlari_ve_satirlar(self):
        self.ornek()
        aylar, genel, v = self.toplamlar()
        self.assertEqual(aylar, [D("68500.00"), D("64000.00"), D("64000.00"), D("64000.00")])
        self.assertEqual(genel, D("260500.00"))
        ekim = v["aylar"][0]["kalemler"]
        self.assertEqual([(k["tarih"], k["gun"], k["tur"], k["kalan"]) for k in ekim], [
            (date(2026, 10, 13), "Salı", ots.TUR_KART, D("30000.00")),
            (date(2026, 10, 16), "Cuma", ots.TUR_KREDI, D("12500.00")),
            (date(2026, 10, 20), "Salı", ots.TUR_SABIT, D("20000.00")),
            (date(2026, 10, 26), "Pazartesi", ots.TUR_VERGI, D("6000.00")),
        ])
        self.assertFalse(ekim[0]["tahmini"])
        kasim_kart = v["aylar"][1]["kalemler"][0]
        self.assertEqual((kasim_kart["tarih"], kasim_kart["gun"], kasim_kart["tahmini"]),
                         (date(2026, 11, 13), "Cuma", True))
        self.assertIn("Tahmini", kasim_kart["aciklama"])
        self.assertTrue(v["aylar"][1]["tahmini_var"])
        # Kart: takvim tarihi kesim, son ödeme ayrı
        self.assertEqual((ekim[0]["kesim"], ekim[0]["son_odeme"]), (date(2026, 10, 13), date(2026, 10, 23)))

    def test_ekrani_acmak_kayit_uretmez(self):
        self.ornek()
        with get_session() as s:
            once = (s.scalar(select(func.count(SabitGiderDonemi.id))), s.scalar(select(func.count(FinansHareketi.id))))
        ots.hesapla(BUGUN)
        ots.hesapla(BUGUN)
        with get_session() as s:
            sonra = (s.scalar(select(func.count(SabitGiderDonemi.id))), s.scalar(select(func.count(FinansHareketi.id))))
        self.assertEqual(once, sonra)
        self.assertEqual(once[0], 0)

    # ------------------------------------------------------------------ kart ödemesi
    def test_kart_kismi_tam_odeme_ve_iptal(self):
        kid = self.ornek()
        kesim = date(2026, 10, 13)
        b1 = self.ekstre_ode(kid, kesim, "10000")
        aylar, genel, v = self.toplamlar()
        self.assertEqual((aylar[0], genel), (D("58500.00"), D("250500.00")))
        self.assertEqual(v["aylar"][0]["kalemler"][0]["kalan"], D("20000.00"))
        # Ekstre servisi de aynı kalanı verir (FIFO ile kapanan taksit ikinci kez düşülmez)
        detay = next(h for h in E.ekstreleri_hesapla(kredi_karti_id=kid) if h["kesim_tarihi"] == kesim)
        self.assertEqual(detay["kalan"], D("20000.00"))
        with self.assertRaises(ValueError):
            self.ekstre_ode(kid, kesim, "20001")
        self.ekstre_ode(kid, kesim, "20000")
        aylar, genel, v = self.toplamlar()
        self.assertEqual((aylar[0], genel), (D("38500.00"), D("230500.00")))
        self.assertNotIn(date(2026, 10, 13), [k["tarih"] for k in v["aylar"][0]["kalemler"]])
        E.odeme_iptal(b1, "Hatalı tutar")
        aylar, genel, v = self.toplamlar()
        self.assertEqual((aylar[0], genel), (D("48500.00"), D("240500.00")))
        self.assertEqual(v["aylar"][0]["kalemler"][0]["kalan"], D("10000.00"))

    def test_kart_ileri_tarihli_odeme_reddedilir(self):
        kid = self.ornek()
        with self.assertRaises(ValueError):
            detay = next(h for h in E.ekstreleri_hesapla(kredi_karti_id=kid))
            E.odeme_yap(ekstre_id=detay["ekstre_id"], tutar="100", tarih=date.today() + timedelta(days=1),
                        finans_hesap_id=self.mev_id)

    def test_kart_gecikme_son_odemeye_gore_ve_gecmis_bolumu(self):
        kid = self.kart(ad="Eski kart", kesim=7, son=20)
        self.harcama(kid, date(2026, 9, 1), "5000")       # kesim 07.09, son ödeme 20.09 → gecikmiş
        kid2 = self.kart(ad="Geç ödemeli", kesim=28, son=15)
        self.harcama(kid2, date(2026, 9, 10), "3000")     # kesim 28.09, son ödeme 15.10 → gecikmemiş
        _a, genel, v = self.toplamlar()
        gecmis = {k["hesap"]: k for k in v["gecmis"]}
        self.assertTrue(gecmis["Eski kart"]["gecikmis"])
        self.assertFalse(gecmis["Geç ödemeli"]["gecikmis"])
        self.assertEqual(v["gecmis_toplam"], D("8000.00"))
        self.assertEqual(genel, D("0.00"))

    def test_eksik_bilgi_sifirla_gizlenmez(self):
        kid = self.kart(ad="Günsüz kart", kesim=None, son=None)
        self.harcama(kid, date(2026, 10, 2), "4000")
        kid2 = self.kart(ad="Son ödemesiz", kesim=10, son=None)
        self.harcama(kid2, date(2026, 10, 5), "1500")
        _a, _g, v = self.toplamlar()
        eksik = {e["ad"]: e for e in v["eksikler"]}
        self.assertEqual(eksik["Günsüz kart"]["tutar"], D("4000.00"))
        self.assertIn("Son ödemesiz", eksik)
        satir = v["aylar"][0]["kalemler"][0]
        self.assertEqual((satir["hesap"], satir["son_odeme"], satir["gecikmis"]), ("Son ödemesiz", None, None))
        self.assertTrue(v["toplam_eksik"])

    # ------------------------------------------------------------------ kredi
    def test_kredi_kalan_odenmis_ve_kapali(self):
        ids = self.kredi(vadeler=[date(2026, 9, 28), date(2026, 10, 28)])
        self.kredi(ad="Kapanmış", vadeler=[date(2026, 10, 5)], durum="KAPALI")
        with get_session() as s:
            t = s.get(BankaKrediTaksit, ids[1])
            t.odenen_tutar = D("5000")
        _a, genel, v = self.toplamlar()
        self.assertEqual(genel, D("7500.00"))
        self.assertEqual([k["kalan"] for k in v["gecmis"]], [D("12500.00")])
        self.assertTrue(v["gecmis"][0]["gecikmis"])
        with get_session() as s:
            s.get(BankaKrediTaksit, ids[1]).durum = "ODENDI"
        self.assertEqual(self.toplamlar()[1], D("0.00"))

    def test_ayni_gun_iki_borc_ayri_satir(self):
        kid = self.kart(kesim=16, son=26)
        self.harcama(kid, date(2026, 10, 1), "12500")
        self.kredi(vadeler=[date(2026, 10, 16)])
        _a, _g, v = self.toplamlar()
        ekim = v["aylar"][0]["kalemler"]
        self.assertEqual(len(ekim), 2)
        self.assertEqual({k["tarih"] for k in ekim}, {date(2026, 10, 16)})
        self.assertEqual(len({k["anahtar"] for k in ekim}), 2)
        self.assertEqual([k["kalan"] for k in ekim], [D("12500.00"), D("12500.00")])

    # ------------------------------------------------------------------ sabit gider
    def test_sabit_gider_fisi_ile_odeme_iptal_ve_fatura(self):
        from database.finans_service import FinansService
        from database.models.hizmet import HizmetKarti

        pid = sg.plan_kaydet({"kategori": "KIRA", "ad": "Mağaza kirası", "periyot": "AYLIK", "odeme_gunu": 20,
                              "tutar": "20000", "baslangic_ay": "10.2026"})
        with get_session() as s:
            h = HizmetKarti(hizmet_kodu="GDR-1", hizmet_adi="Kira gideri", hizmet_turu="GIDER", aktif=True)
            s.add(h)
            s.flush()
            hid = h.id
        oc = sg.gider_fisi_ile_ode(pid, 2026, 10, finans_hesap_id=self.kasa_id, hizmet_id=hid, tutar="5000",
                                   tarih=date.today())
        aylar, genel, _v = self.toplamlar()
        self.assertEqual((aylar[0], genel), (D("15000.00"), D("75000.00")))
        with self.assertRaises(ValueError):
            sg.gider_fisi_ile_ode(pid, 2026, 10, finans_hesap_id=self.kasa_id, hizmet_id=hid, tutar="15000.01")
        from database.models.finans import GiderFisi

        with get_session() as s:
            fis_id = s.scalar(select(GiderFisi.id).where(GiderFisi.belge_no == oc["belge_no"]))
        FinansService.gider_fisi_iptal(fis_id)
        self.assertEqual(self.toplamlar()[0][0], D("20000.00"))
        # Plan iptal: üretilmemiş gelecek aylar kalkar, ödemesi olan dönem silinmez
        sg.plan_iptal(pid, "Taşındık", bugun=date(2026, 11, 1))
        aylar, _g, v = self.toplamlar()
        self.assertEqual(aylar, [D("20000.00"), D("0.00"), D("0.00"), D("0.00")])
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SabitGiderDonemi.id))), 1)

    def test_kartla_odenen_gider_cift_sayilmaz(self):
        pid = sg.plan_kaydet({"kategori": "MUHASEBE", "ad": "Muhasebe", "periyot": "AYLIK", "odeme_gunu": 5,
                              "tutar": "3000", "baslangic_ay": "11.2026", "bitis_ay": "11.2026"})
        kid = self.kart(kesim=13, son=23)
        belge = self.harcama(kid, date(2026, 10, 10), "3000")
        once = self.toplamlar()[1]
        self.assertEqual(once, D("6000.00"))
        donem_id = sg.donem_hazirla(pid, 2026, 11)
        sg.baglanti_ekle(donem_id, belge, "3000")
        self.assertEqual(self.toplamlar()[1], D("3000.00"))

    def test_tedarikci_acik_borcu_kapsam_disi(self):
        self.ort.alis(10, 100, date(2026, 10, 1))
        _a, genel, v = self.toplamlar()
        self.assertEqual((genel, v["gecmis_toplam"]), (D("0.00"), D("0.00")))

    def test_gecisi_yapilmamis_firmada_kaynak_okunamadi_olmaz(self):
        """Kart geçişleri (gider_kart_odeme v2, kart_bakiye v1) yapılmamış firma: takvim önce geçişi tamamlar."""
        from sqlalchemy import inspect, text

        import database.database as vt
        from database import gider_kart_odeme_service as gk
        from database import kart_bakiye_gecis as kbg

        kid = self.kart()
        self.harcama(kid, date(2026, 9, 20), "10000")
        motor = vt.company_db._engine
        with motor.begin() as b:
            b.execute(text("ALTER TABLE kredi_karti_odeme_taksitleri DROP COLUMN ekstre_kesim_tarihi"))
            b.execute(text("DROP TABLE kredi_karti_ekstre_odeme_taksitleri"))
            if inspect(b).has_table("modul_sema_surumleri"):
                b.execute(text("DELETE FROM modul_sema_surumleri WHERE modul IN ('gider_kart_odeme', 'kart_bakiye')"))
        for hazir in (gk._HAZIR, kbg._HAZIR, ots._SEMA_HAZIR):
            hazir.discard(motor)
        with get_session() as s, self.assertRaisesRegex(Exception, "ekstre_kesim_tarihi"):
            ots._kart_kalemleri(s, BUGUN, [])  # eski şemada doğrudan okuma bu hatayı verirdi

        v = ots.hesapla(BUGUN)
        self.assertEqual(v["eksikler"], [])
        self.assertEqual([k["kalan"] for k in v["aylar"][0]["kalemler"]], [D("10000.00")])
        ins = inspect(motor)
        self.assertIn("ekstre_kesim_tarihi", {c["name"] for c in ins.get_columns("kredi_karti_odeme_taksitleri")})
        self.assertTrue(ins.has_table("kredi_karti_ekstre_odeme_taksitleri"))
        with motor.connect() as b:
            self.assertEqual(dict(b.execute(text(
                "SELECT modul, surum FROM modul_sema_surumleri WHERE modul IN ('gider_kart_odeme', 'kart_bakiye')"))
                .all()), {"gider_kart_odeme": 2, "kart_bakiye": 1})


class OdemeTakvimiEkranTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        self.ort = StokOrtami("odeme_takvimi_ui")
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:  # pragma: no cover
            self.ort.kapat()
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.ort.kapat()

    def test_ekran_satirlari_secim_korunur(self):
        from odeme_takvimi_ui import OdemeTakvimiSayfasi

        sg.plan_kaydet({"kategori": "KIRA", "ad": "Mağaza kirası", "periyot": "AYLIK", "odeme_gunu": 20,
                        "tutar": "20000", "baslangic_ay": "10.2026"})
        sayfa = OdemeTakvimiSayfasi(self.root, None, bugun_fn=lambda: BUGUN)
        sayfa.pack()
        satirlar = [sayfa.tablo.item(i, "values") for i in sayfa.tablo.get_children()]
        self.assertEqual(satirlar[0][3], "EKİM 2026")
        self.assertEqual(satirlar[1][:3], ("20.10.2026", "Salı", "Sabit Gider"))
        self.assertEqual(satirlar[-1][0], "Genel toplam")
        anahtar = sayfa.tablo.get_children()[1]
        sayfa.tablo.selection_set(anahtar)
        sayfa.yenile()
        self.assertEqual(sayfa.tablo.selection(), (anahtar,))
        self.assertIn("Ödeme vadesi: 20.10.2026", sayfa.detay.get("1.0", "end"))
        sayfa.destroy()


if __name__ == "__main__":
    unittest.main()
