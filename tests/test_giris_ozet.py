"""GİRİŞ özeti kabul örnekleri — yalnız geçici test veritabanı (StokOrtami); gerçek firma verisine dokunmaz."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from tests.stok_test_ortami import StokOrtami

from database import giris_ozet_service as go
from database.database import get_session
from database.session_manager import oturum

D = Decimal
GUN = date(2026, 10, 10)


def gp_toplam(kalemler) -> Decimal:
    return sum((k["tutar"] for k in kalemler), D("0"))


class TarihVeOranTest(unittest.TestCase):
    def test_onceki_ay_ayni_gun_ve_yil_gecisi(self):
        self.assertEqual(go.onceki_ay_ayni_gun(date(2026, 3, 31)), date(2026, 2, 28))
        self.assertEqual(go.onceki_ay_ayni_gun(date(2024, 3, 31)), date(2024, 2, 29))
        self.assertEqual(go.onceki_ay_ayni_gun(date(2026, 1, 15)), date(2025, 12, 15))
        dn = go.donemler(date(2026, 3, 31))
        self.assertEqual(dn["onceki_ay"], (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(go.kesimler(GUN), {"bugun": GUN, "ay1": date(2026, 10, 31), "ay2": date(2026, 11, 30),
                                            "ay3": date(2026, 12, 31)})
        self.assertEqual(go.kesimler(date(2026, 12, 5))["ay3"], date(2027, 2, 28))

    def test_yuzde_ve_oran_kurallari(self):
        self.assertEqual(go.yuzde_degisim(D("0"), D("0")), (None, "Değişim yok"))
        self.assertEqual(go.yuzde_degisim(D("10"), D("0")), (None, "Önceki dönem tutarı yok"))
        self.assertEqual(go.yuzde_degisim(D("10"), D("-5")), (None, "Negatif karşılaştırma tabanı"))
        self.assertEqual(go.yuzde_degisim(D("150"), D("100")), (D("50.00"), ""))
        self.assertEqual(go.tahsilat_orani(D("6000"), D("7580")), (D("79.16"), ""))
        self.assertIsNone(go.tahsilat_orani(D("6000"), D("0"))[0])
        self.assertIsNone(go.tahsilat_orani(D("6000"), D("-10"))[0])
        self.assertEqual(go.tahsilat_orani(D("9000"), D("6000"))[0], D("150.00"))

    def test_birikimli_vade_sutunlari(self):
        kalemler = [go._kalem("x", "10000", vade=date(2026, 11, 5)), go._kalem("x", "500", vade=None),
                    go._kalem("x", "300", vade=date(2026, 10, 1))]
        k = go.kova_toplamlari(kalemler, GUN)
        self.assertEqual((k["bugun"], k["ay1"], k["ay2"], k["ay3"], k["tamami"]),
                         (D("300.00"), D("300.00"), D("10300.00"), D("10300.00"), D("10800.00")))
        self.assertEqual((k["vadesiz"], k["gecikmis"]), (D("500.00"), D("300.00")))
        self.assertEqual(sum(x["tutar"] for x in go.sutun_kalemleri(kalemler, GUN, "ay2")), k["ay2"])

    def test_butunlesik_finansal_durum(self):
        varlik = {"toplam": D("100000"), "likit": D("20000"), "bilinen": D("100000"), "eksik": [], "durum": go.HAZIR}
        borc = {"gercek_borc": D("40000"), "toplam": {"ay3": D("60000"), "vadesiz": D("0")}, "eksik": [],
                "kalemler": [], "durum": go.HAZIR, "bilinen_borc": D("40000")}
        f = go.finansal_durum(varlik, borc)
        self.assertEqual((f["net_varlik"], f["uc_ay_fark"], f["likit_fark"]), (D("60000.00"), D("40000.00"),
                                                                                D("-40000.00")))
        self.assertEqual(f["likit_etiket"], "Kasa ve mevduat karşılama farkı")
        borc["toplam"]["vadesiz"] = D("1")
        self.assertIn("Vade eksik", go.finansal_durum(varlik, borc)["etiketler"])


def _satir(miktar, fiyat):
    return {"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D(str(miktar)), "birim": "Adet",
            "birim_fiyat": D(str(fiyat)), "iskonto_orani": D("0"), "kdv_orani": D("20")}


class GirisOzetTest(unittest.TestCase):
    def setUp(self):
        from database.models.finans import BankaKarti, FinansHesabi

        self._ayar = tempfile.TemporaryDirectory(prefix="giris_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("giris_ozet")
        go.onbellegi_temizle()
        with get_session() as s:
            bk = BankaKarti(banka_adi="TEST BANKASI")
            s.add(bk)
            s.flush()
            self.bk = bk.id
            for ad, tur, alt in (("ANA KASA", "KASA", None), ("MEVDUAT", "BANKA", "MEVDUAT"),
                                 ("KMH", "BANKA", "KMH"), ("POS", "BANKA", "POS")):
                h = FinansHesabi(hesap_adi=ad, hesap_turu=tur, alt_hesap_turu=alt, banka_karti_id=None if
                                 tur == "KASA" else bk.id)
                s.add(h)
                s.flush()
                setattr(self, "h_" + ad.split()[-1].lower(), h.id)

    def tearDown(self):
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()
        go.onbellegi_temizle()

    # --- yardımcılar ---
    def fh(self, hesap, tur, tutar, belge, tarih=GUN):
        from database.models.finans import FinansHareketi

        with get_session() as s:
            s.add(FinansHareketi(hesap_id=hesap, tarih=tarih, hareket_turu=tur, belge_no=belge, tutar=D(str(tutar))))

    def ci(self, cari, tur, belge, borc=0, alacak=0, tarih=GUN, hesap_adi=None):
        from database.models.cari import CariIslem

        with get_session() as s:
            s.add(CariIslem(cari_id=cari, tarih=tarih, islem_turu=tur, belge_no=belge, borc=D(str(borc)),
                            alacak=D(str(alacak)), hesap_adi=hesap_adi))

    def fatura(self, tarih, satirlar, onayla=True):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet({"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": self.o.mus_id,
                                         "depo": "ANA DEPO", "odeme_tutari": D("0"), "sales_person_id": 1}, satirlar)
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return f

    def ozet(self, tarih=GUN, **kw):
        return go.hesapla(tarih, bugun=GUN, **kw)

    # --- satış ---
    def test_satis_net_iade_taslak_ve_karsilastirma(self):
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(100, 10, date(2026, 9, 1))
        self.fatura(GUN, [_satir(5, 1000)])
        usd = self.fatura(GUN, [_satir(1, 1000)])
        from database.models.satis_faturasi import SatisFaturasi

        with get_session() as s:
            # Dövizli faturada satır tutarları TL'dir; kur ile ikinci kez çarpılmamalı
            f = s.get(SatisFaturasi, usd.id)
            f.para_birimi, f.kur, f.borc_esasi = "USD", D("40"), "TL_SABIT"
        self.fatura(GUN, [_satir(1, 500)], onayla=False)
        self.fatura(date(2026, 9, 10), [_satir(1, 500)])
        self.fatura(date(2026, 9, 20), [_satir(1, 100)])
        SatisIadeFaturasiService.kaydet({"iade_tarihi": GUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
                                         "aciklama": None, "iade_odeme_tutari": 0}, [_satir(1, 500)])
        sat = self.ozet()["satis"]
        b, a = sat["satirlar"]["bugun"], sat["satirlar"]["ay"]
        self.assertEqual((b["belge_adedi"], b["satis_tutari"], b["iade_adedi"], b["iade_tutari"], b["net"]),
                         (2, D("7200.00"), 1, D("600.00"), D("6600.00")))
        self.assertEqual(b["kdv_haric_net"], D("5500.00"))
        self.assertEqual((b["onceki_net"], b["fark"], b["yuzde"]), (D("600.00"), D("6000.00"), D("1000.00")))
        # Ay: 1-10 Ekim ↔ 1-10 Eylül (20 Eylül faturası karşılaştırmaya girmez)
        self.assertEqual((a["net"], a["onceki_net"]), (D("6600.00"), D("600.00")))
        self.assertTrue(sat["gun_devam"])
        self.assertEqual(sum((x["tutar"] for x in sat["kalemler"] if go._icinde(x["tarih"], (GUN, GUN))), D("0")),
                         b["net"])

    # --- tahsilat ---
    def test_tahsilat_tekil_belge_yontem_iade_pos_ve_dogrudan_odeme(self):
        from database.models.finans import CariVirmanMakbuzu

        m = self.o.mus_id
        self.ci(m, "Tahsilat", "TMK-1", alacak=5000)
        self.fh(self.h_kasa, "TAHSİLAT MAKBUZU", 2000, "TMK-1")
        self.fh(self.h_mevduat, "TAHSİLAT MAKBUZU", 3000, "TMK-1")
        self.ci(m, "Tahsilat", "POS-1", alacak=1000)
        self.fh(self.h_pos, "POS TAHSİLAT", 1000, "POS-1")
        self.fh(self.h_pos, "POS KOMİSYON", 20, "POS-1")
        self.fh(self.h_kasa, "VIRMAN ÇIKIŞ", 700, "VRM-1")
        self.fh(self.h_mevduat, "VIRMAN GİRİŞ", 700, "VRM-1")
        self.ci(m, "Ödeme", "ODM-1", borc=500)
        self.fh(self.h_kasa, "ÖDEME MAKBUZU", 500, "ODM-1")
        self.ci(m, "Virman Tahsilat", "CVT-1", alacak=4000)
        self.ci(self.o.ted_id, "Virman Ödeme", "CVO-1", alacak=4000)
        with get_session() as s:
            s.add(CariVirmanMakbuzu(belge_no="CVM-1", tahsilat_belge_no="CVT-1", odeme_belge_no="CVO-1",
                                    tarih=GUN, tutar=D("4000"), musteri_id=m, tedarikci_id=self.o.ted_id))
        oz = self.ozet()
        t = oz["tahsilat"]
        turler = {r["tur"]: r["bugun"] for r in t["turler"]}
        self.assertEqual(turler[go.NAKIT], {"adet": 1, "tutar": D("1500.00")})
        self.assertEqual(turler[go.HAVALE], {"adet": 1, "tutar": D("3000.00")})
        self.assertEqual(turler[go.KART], {"adet": 1, "tutar": D("1000.00")})
        self.assertEqual(turler[go.MUS_TED], {"adet": 1, "tutar": D("4000.00")})
        self.assertEqual((t["toplam"]["bugun"]["adet"], t["toplam"]["bugun"]["tutar"]), (2, D("5500.00")))
        self.assertEqual(t["toplam"]["bugun"]["oran_mesaj"], "Net satış sıfır; oran hesaplanmadı.")
        # Kasa 2000-700-500, mevduat 3000+700; POS likit değildir; iç virman ve doğrudan ödeme likiditeyi değiştirmez
        self.assertEqual(oz["likit"]["likit"], D("4500.00"))
        self.assertNotIn("Bankaya geçmemiş POS", {k["kaynak"] for k in oz["likit"]["kalemler"]})

    # --- borç, ödeme takvimi, varlık ---
    def _borc_verisi(self):
        from database import sabit_gider_service as sg
        from database.models.cari import Cari, SatisHareketi
        from database.models.finans import (
            BankaKredisi,
            BankaKrediTaksit,
            KrediKartiEkstre,
            KrediKartiEkstreOdeme,
            KrediKartiOdeme,
            KrediKartiOdemeTaksit,
            KrediKartiTanimi,
        )

        self.o.alis(10, 50, date(2026, 9, 1))  # tedarikçi faturası 600 TL, vade = fatura tarihi (gecikmiş)
        self.o.alis(5, 70, date(2026, 9, 2))   # 420 TL
        with get_session() as s:
            k1 = BankaKredisi(belge_no="KR-1", banka_karti_id=self.bk, kredi_adi="İşletme", ana_para=D("100000"),
                              taksit_sayisi=3, kullandirim_tarihi=date(2026, 9, 1), ilk_taksit_tarihi=date(2026, 10, 5))
            k1.taksitler = [
                BankaKrediTaksit(taksit_no=1, vade_tarihi=date(2026, 10, 5), anapara=D("0"), faiz=D("2000")),
                BankaKrediTaksit(taksit_no=2, vade_tarihi=date(2026, 11, 5), anapara=D("50000"), faiz=D("4000")),
                BankaKrediTaksit(taksit_no=3, vade_tarihi=date(2026, 12, 5), anapara=D("50000"), faiz=D("4000")),
            ]
            k2 = BankaKredisi(belge_no="KR-2", banka_karti_id=self.bk, kredi_adi="Kısa", ana_para=D("10000"),
                              taksit_sayisi=1, kullandirim_tarihi=date(2026, 9, 1), ilk_taksit_tarihi=date(2026, 11, 5))
            k2.taksitler = [BankaKrediTaksit(taksit_no=1, vade_tarihi=date(2026, 11, 5), anapara=D("10000"),
                                             faiz=D("0"), odenen_tutar=D("4000"), odenen_anapara=D("4000"),
                                             durum="KISMEN_ODENDI")]
            s.add_all([k1, k2])
            kart = KrediKartiTanimi(banka_karti_id=self.bk, kart_adi="Firma Kartı", hesap_kesim_gunu=15,
                                    son_odeme_gunu=25)
            s.add(kart)
            s.flush()
            od = KrediKartiOdeme(belge_no="KKO-1", tarih=date(2026, 10, 1), vade_tarihi=date(2026, 10, 1),
                                 banka_karti_id=self.bk, kredi_karti_id=kart.id, cari_id=self.o.ted_id,
                                 cekim_turu="TAKSITLI", taksit_sayisi=3, tutar=D("3000"))
            od.taksitler = [KrediKartiOdemeTaksit(taksit_no=i, vade_tarihi=date(2026, 9 + i, 1), tutar=D("1000"))
                            for i in (1, 2, 3)]
            s.add(od)
            ek = KrediKartiEkstre(kredi_karti_id=kart.id, kesim_tarihi=date(2026, 10, 15),
                                  donem_baslangic=date(2026, 9, 16), donem_bitis=date(2026, 10, 15),
                                  son_odeme_tarihi=date(2026, 10, 25))
            s.add(ek)
            s.flush()
            s.add(KrediKartiEkstreOdeme(ekstre_id=ek.id, belge_no="KKE-1", tarih=date(2026, 10, 8), tutar=D("400")))
            s.add(SatisHareketi(cari_id=self.o.ted_id, belge_no="DVR-1", satis_tarihi=date(2026, 1, 1),
                                satis_tutari=D("3000"), kalan_acik_tutar=D("3000")))
            t2 = Cari(cari_kodu="T002", unvan="Avans Tedarikçi", cari_turu="Tedarikçi", aktif=True)
            s.add(t2)
            s.flush()
            self.t2 = t2.id
        self.ci(self.t2, "Ödeme", "ODM-AV", alacak=8000, tarih=date(2026, 10, 1))
        self.fh(self.h_mevduat, "BANKA GİRİŞ", 38000, "BG-1", tarih=date(2026, 9, 1))
        self.fh(self.h_mevduat, "GÖNDERİLEN HAVALE", 8000, "ODM-AV", tarih=date(2026, 10, 1))
        self.fh(self.h_kmh, "BANKA ÇIKIŞ", 50000, "BC-1", tarih=date(2026, 9, 1))
        pid = sg.plan_kaydet({"kategori": "KIRA", "ad": "Kira", "odeme_gunu": 31, "tutar": "20000",
                              "baslangic_ay": "01.2026"})
        sg.donemleri_uret(GUN)
        self.fh(self.h_kasa, "KASA GİRİŞ", 5000, "KG-1", tarih=date(2026, 10, 1))
        self.fh(self.h_kasa, "GİDER FİŞİ", 5000, "GF-1", tarih=date(2026, 10, 9))
        donem = next(x for x in sg.plan_donemleri(pid, GUN) if x["ay"] == 10)
        sg.baglanti_ekle(donem["donem_id"], "GF-1", "5000")

    def test_odeme_takvimi_borc_bakiyesi_ve_finansal_durum(self):
        self._borc_verisi()
        oz = self.ozet()
        b = oz["borc"]
        self.assertEqual(b["durum"], go.HAZIR, b["uyarilar"])
        sat = {r["kod"]: r for r in b["satirlar"]}
        kr = sat[go.KREDI]
        # Kredi: takvim kalan taksitler 110.000 + kısmi ödenmiş 6.000; gerçek borç 100.000 + 2.000 faiz + 6.000
        self.assertEqual((kr["bugun"], kr["ay1"], kr["ay2"], kr["ay3"], kr["tamami"]),
                         (D("2000.00"), D("2000.00"), D("62000.00"), D("116000.00"), D("116000.00")))
        borc = dict(b["borc_satirlari"])
        self.assertEqual(borc["Kredi borcu (kalan anapara + vadesi gelmiş faiz)"], D("108000.00"))
        # Kart: ekstre 1000-400 ödendi = 600 (25 Ekim), sonraki taksitler kesime girmedi
        kk = sat[go.KK]
        self.assertEqual((kk["ay1"], kk["ay2"], kk["ay3"]), (D("600.00"), D("1600.00"), D("2600.00")))
        self.assertEqual(borc["Kredi kartı borcu"], D("2600.00"))
        self.assertEqual((sat[go.KMH]["bugun"], sat[go.KMH]["ay1"]), (D("0.00"), D("50000.00")))
        # Tedarikçi açık cari borcu ödeme takviminde ve borç bakiyelerinde yer almaz
        self.assertEqual({r["kod"] for r in b["satirlar"]}, {go.KREDI, go.KK, go.KMH, go.SABIT, go.DIGER})
        self.assertFalse(any("Tedarikçi" in ad for ad, _v in b["borc_satirlari"]))
        self.assertNotIn("plan_satirlari", b)
        # Sabit gider: 20.000 - 5.000 + 20.000 + 20.000 = 55.000; gerçek borca girmez
        sab = sat[go.SABIT]
        self.assertEqual((sab["ay1"], sab["ay3"], sab["tamami"]), (D("15000.00"), D("55000.00"), D("55000.00")))
        self.assertEqual(b["planlanan_ek"]["tamami"], D("55000.00"))
        self.assertEqual(b["gercek_borc"], D("108000.00") + D("2600.00") + D("50000.00"))
        self.assertEqual(b["toplam"]["tamami"], sum((sat[k]["tamami"] for k, _ in go.TAKVIM_SATIRLARI), D("0")))
        self.assertEqual(b["toplam"]["ay1"], kr["ay1"] + kk["ay1"] + sat[go.KMH]["ay1"] + sab["ay1"]
                         + sat[go.DIGER]["ay1"])
        # Ayrı başlık: 600 + 420 + 3.000 devir; 8.000 avanslı tedarikçi toplam borcu düşürmez
        ted = oz["tedarikci_acik"]
        self.assertEqual((ted["durum"], ted["tarih"], ted["toplam"], ted["adet"]),
                         (go.HAZIR, GUN, D("4020.00"), 1))
        self.assertEqual(gp_toplam(ted["kalemler"]), ted["toplam"])
        # Mevduat 38.000 - 8.000 = 30.000; KMH -50.000 borçta; kasa 0
        self.assertEqual(oz["likit"]["likit"], D("30000.00"))
        for kaldirilan in ("beklenen", "varlik", "finansal"):
            self.assertNotIn(kaldirilan, oz)

    def test_ust_ozet_tedarikci_borcundan_etkilenmez(self):
        """Talimat örneği: diğer yük 180.000 TL; açık cari borç 70.000 → 60.000 iken üst özet 180.000 TL kalır."""
        from database.models.cari import SatisHareketi
        from database.models.finans import BankaKredisi, BankaKrediTaksit

        with get_session() as s:
            k = BankaKredisi(belge_no="KR-9", banka_karti_id=self.bk, kredi_adi="Yük", ana_para=D("180000"),
                             taksit_sayisi=1, kullandirim_tarihi=date(2026, 9, 1), ilk_taksit_tarihi=date(2026, 10, 20))
            k.taksitler = [BankaKrediTaksit(taksit_no=1, vade_tarihi=date(2026, 10, 20), anapara=D("180000"),
                                            faiz=D("0"))]
            s.add(k)
            s.add(SatisHareketi(cari_id=self.o.ted_id, belge_no="DVR-70", satis_tarihi=date(2026, 9, 1),
                                satis_tutari=D("70000"), kalan_acik_tutar=D("70000")))
        oz = self.ozet()
        self.assertEqual((oz["borc"]["toplam"]["ay1"], oz["tedarikci_acik"]["toplam"]),
                         (D("180000.00"), D("70000.00")))
        self.ci(self.o.ted_id, "Ödeme", "ODM-10", alacak=10000)
        go.onbellegi_temizle()
        oz = self.ozet()
        self.assertEqual((oz["borc"]["toplam"]["ay1"], oz["tedarikci_acik"]["toplam"]),
                         (D("180000.00"), D("60000.00")))

    def test_tedarikci_acik_borcu_kapsami(self):
        """Kapanmış ve silinmiş tedarikçi katılmaz; müşteri bakiyesi ve tedarikçi avansı toplamı etkilemez."""
        from database.models.cari import Cari, SatisHareketi

        with get_session() as s:
            kapali = Cari(cari_kodu="T010", unvan="Kapanmış Tedarikçi", cari_turu="Tedarikçi", aktif=True)
            silinen = Cari(cari_kodu="T011", unvan="Silinmiş Tedarikçi", cari_turu="Tedarikçi", aktif=True,
                           is_deleted=True)
            avans = Cari(cari_kodu="T012", unvan="Avans Tedarikçi", cari_turu="Tedarikçi", aktif=True)
            s.add_all([kapali, silinen, avans])
            s.flush()
            ids = (kapali.id, silinen.id, avans.id)
            for cid, belge in ((self.o.ted_id, "A-1"), (kapali.id, "A-2"), (silinen.id, "A-3")):
                s.add(SatisHareketi(cari_id=cid, belge_no=belge, satis_tarihi=date(2026, 9, 1),
                                    satis_tutari=D("2500"), kalan_acik_tutar=D("2500")))
        self.ci(ids[0], "Ödeme", "ODM-K", alacak=2500)
        self.ci(ids[2], "Ödeme", "ODM-A", alacak=900)
        self.ci(self.o.mus_id, "Satış", "MS-1", borc=4000)
        ted = self.ozet()["tedarikci_acik"]
        self.assertEqual((ted["toplam"], ted["adet"]), (D("2500.00"), 1))
        self.assertEqual([k["cari_id"] for k in ted["kalemler"]], [self.o.ted_id])

    def test_odeme_sozleri_giris_ozetine_katilmaz(self):
        from database.models.cari import SatisHareketi
        from database.odeme_sozu_service import OdemeSozuService

        with get_session() as s:
            s.add(SatisHareketi(cari_id=self.o.ted_id, belge_no="DVR-9", satis_tarihi=date(2026, 1, 1),
                                satis_tutari=D("3000"), kalan_acik_tutar=D("3000")))
        OdemeSozuService.olustur({"yon": "VERILEN", "cari_id": self.o.ted_id, "soz_tarihi": GUN,
                                  "vade_tarihi": date(2026, 11, 20), "tutar": "2000", "yontem": "Nakit"},
                                 [("DVR-9", "2000")])
        OdemeSozuService.olustur({"yon": "ALINAN", "cari_id": self.o.mus_id, "soz_tarihi": date(2026, 10, 2),
                                  "vade_tarihi": GUN, "tutar": "700", "yontem": "Nakit"})
        oz = self.ozet()
        self.assertEqual(oz["borc"]["toplam"]["tamami"], D("0.00"))
        self.assertEqual(oz["tedarikci_acik"]["toplam"], D("3000.00"))
        self.assertNotIn("Müşteri ödeme sözü", [r["tur"] for r in oz["tahsilat"]["turler"]])
        self.assertNotIn("sozler", oz["tahsilat"])
        self.assertEqual(len(OdemeSozuService.liste()), 2, "Söz kayıtları silinmemeli")

    def test_gecmis_tarih_guncel_kaynaklari_katmaz(self):
        self._borc_verisi()
        oz = self.ozet(date(2026, 10, 1))
        self.assertEqual(oz["borc"]["durum"], go.TARIHSEL_YOK)
        self.assertIsNone(oz["borc"]["gercek_borc"])
        # Kasa / banka D itibarıyla: 9 Ekim gider fişi henüz yok
        self.assertEqual(oz["likit"]["likit"], D("35000.00"))
        # Tedarikçi açık borcu rapor tarihinden bağımsız, bugünün bakiyesi
        ted = oz["tedarikci_acik"]
        self.assertEqual((ted["tarih"], ted["toplam"]), (GUN, D("4020.00")))
        with self.assertRaises(ValueError):
            go.hesapla(date(2026, 10, 11), bugun=GUN)

    def test_yetkisiz_kullanici_tutar_gormez(self):
        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme"})
        oz = self.ozet()
        for bolum in ("tahsilat", "borc", "likit", "tedarikci_acik"):
            self.assertEqual(oz[bolum]["durum"], go.YETKISIZ)
            self.assertNotIn("toplam", oz[bolum])
        self.assertIn(oz["satis"]["durum"], (go.HAZIR, go.BOS))

    def test_onbellek_ve_yazma_sonrasi_yenileme(self):
        ilk = go.ozet(GUN, bugun=GUN)
        self.assertFalse(ilk.get("onbellek"))
        self.assertTrue(go.ozet(GUN, bugun=GUN).get("onbellek"))
        self.fh(self.h_kasa, "KASA GİRİŞ", 100, "KG-9")
        son = go.ozet(GUN, bugun=GUN)
        self.assertFalse(son.get("onbellek"))
        self.assertEqual(son["likit"]["likit"], D("100.00"))


if __name__ == "__main__":
    unittest.main()
