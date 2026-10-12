"""KDV raporu: belge kaynağı, oranlar, iadeler, devreden, GM açık/kapalı ve karşılaştırma (izole DB)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, update  # noqa: E402

from database import kdv_rapor_service as srv  # noqa: E402
from database.access import AccessError  # noqa: E402
from database.database import get_session  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

EYLUL = (date(2026, 9, 1), date(2026, 9, 30))


def _satir(miktar, fiyat, kdv="20", kod="U001", **ek):
    return {"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": D(str(miktar)), "birim": "Adet",
            "birim_fiyat": D(str(fiyat)), "iskonto_orani": D("0"), "kdv_orani": D(kdv), **ek}


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])
        self.o.urun_ekle("U002", "İkinci Ürün")

    def tearDown(self):
        self.o.kapat()

    def satis(self, tarih, satirlar, onayla=True, **veriler):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "odeme_tutari": D("0"), "sales_person_id": 1, **veriler}, satirlar)
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def alis(self, tarih, satirlar, **veriler):
        from database.alis_faturasi_service import AlisFaturasiService

        return AlisFaturasiService.kaydet(
            {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": D("0"), **veriler}, satirlar)

    def kayit_sayilari(self) -> tuple:
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.genel_muhasebe import MuhasebeFisi
        from database.models.satis_faturasi import SatisFaturasi
        from database.models.stok import StokHareketi

        with get_session() as s:
            return tuple(int(s.scalar(select(func.count(m.id))) or 0)
                         for m in (SatisFaturasi, AlisFaturasi, StokHareketi, MuhasebeFisi))

    def gm_ac(self):
        from database.models.firma import Firma
        from database.models.genel_muhasebe import MuhasebelestirmeAyari

        with get_session() as s:
            fid = s.scalar(select(Firma.id))
            s.add(MuhasebelestirmeAyari(firma_id=fid, evrak_turu="*", gm_kullan=True, yontem="otomatik"))
        return fid


class TemelSenaryo(_Taban):
    """Eylül: çok oranlı satış + kaynaklı iade + taslak + iptal; alış + kaynaksız alış iadesi."""

    def senaryo(self):
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.a1 = self.alis(date(2026, 9, 1), [_satir(20, 100)])
        self.a2 = self.alis(date(2026, 9, 1), [_satir(5, 50, kod="U002")])
        self.f1 = self.satis(date(2026, 9, 5), [_satir(2, 150), _satir(1, 100, kdv="10", kod="U002")])
        self.satis(date(2026, 9, 6), [_satir(1, 150)], onayla=False)
        iptal = self.satis(date(2026, 9, 7), [_satir(1, 150)])
        SatisFaturasiService.iptal_et(iptal.id, "test")
        self.si = SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": date(2026, 9, 10), "cari_id": self.o.mus_id, "kaynak_fatura_id": self.f1.id,
             "depo": "ANA DEPO", "aciklama": None, "iade_odeme_tutari": 0},
            [_satir(1, 150, kaynak_fatura_satiri_id=self.f1.satirlar[0].id)])
        self.ai = AlisIadeFaturasiService.kaydet_ve_onayla(
            {"iade_tarihi": date(2026, 9, 12), "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "iade_odeme_tutari": D("0")}, [_satir(2, 100)], kaynaksiz_gerekce="Test: kaynaksız iade")

    def test_oranlar_iadeler_haric_belgeler_ve_salt_okunur(self):
        self.senaryo()
        once = self.kayit_sayilari()
        r = srv.rapor(*EYLUL)
        self.assertEqual(self.kayit_sayilari(), once)
        t = r["toplamlar"]
        self.assertEqual((t["SATIS_matrah"], t["SATIS_kdv"]), (D("400.00"), D("70.00")))
        self.assertEqual((t["SATIS_IADE_matrah"], t["SATIS_IADE_kdv"]), (D("150.00"), D("30.00")))
        self.assertEqual((t["ALIS_matrah"], t["ALIS_kdv"]), (D("2250.00"), D("450.00")))
        self.assertEqual((t["ALIS_IADE_matrah"], t["ALIS_IADE_kdv"]), (D("200.00"), D("40.00")))
        self.assertEqual(t["net_hesaplanan"], D("40.00"))
        self.assertEqual(t["net_alis_kdv"], D("410.00"))
        oran = {(x["yon"], x["oran"]): x for x in r["oranlar"]}
        self.assertEqual((oran[(srv.HESAPLANAN, "%20")]["satis_kdv"], oran[(srv.HESAPLANAN, "%20")]["iade_kdv"],
                          oran[(srv.HESAPLANAN, "%20")]["net_kdv"]), (D("60.00"), D("30.00"), D("30.00")))
        self.assertEqual(oran[(srv.HESAPLANAN, "%10")]["satis_matrah"], D("100.00"))
        self.assertEqual(r["haric"]["Satış faturası"], {"Taslak / onaysız": 1, "İptal": 1})
        belge = next(b for b in r["belgeler"] if b["no"] == self.f1.fatura_no)
        self.assertEqual((belge["matrah"], belge["kdv"], belge["oranlar"]), (D("400.00"), D("70.00"), "%10, %20"))
        alis = next(b for b in r["belgeler"] if b["no"] == self.a1.fatura_no)
        self.assertEqual(alis["indirilebilirlik"], srv.INDIRILEBILIRLIK_YOK)
        ai = next(b for b in r["belgeler"] if b["no"] == self.ai.iade_no)
        self.assertEqual(ai["sorun"], "")          # kaynaksız kararı kayıtlı: uyarı değil bilgi
        self.assertTrue(ai["not"])
        self.assertTrue(any("Taslak" in e["sorun"] for e in r["eksik"]))
        self.assertTrue(r["belgeler"][-1]["_sabit"])
        self.assertTrue(any("indirilebilirlik" in n.casefold() for n in r["notlar"]))
        self.assertTrue(any("tevkifat" in n.casefold() for n in r["notlar"]))
        satirlar = srv.belge_satirlari(srv.SATIS, self.f1.id)
        self.assertEqual(sum((x["kdv"] for x in satirlar), D("0")), D("70.00"))

    def test_gm_kapali_ve_acik_temel_rapor_ayni_karsilastirma_ayri(self):
        self.senaryo()
        with patch.object(srv, "_gm_karsilastirma", side_effect=AssertionError("GM kapalıyken çağrıldı")):
            kapali = srv.rapor(*EYLUL)
        self.assertFalse(kapali["gm_aktif"])
        self.assertEqual(kapali["gm"], [])
        self.assertIn("kullanılamaz", kapali["gm_mesaj"])

        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeFisiSatiri

        firma_id = self.gm_ac()
        with get_session() as s:
            h391 = HesapPlani(firma_id=firma_id, hesap_kodu="391.01", hesap_adi="Hesaplanan KDV", hesap_turu="Pasif")
            h191 = HesapPlani(firma_id=firma_id, hesap_kodu="191.01", hesap_adi="İndirilecek KDV", hesap_turu="Aktif")
            s.add_all([h391, h191])
            s.flush()

            def fis(no, tarih, durum, satirlar, kaynak=None, belge_no=None):
                f = MuhasebeFisi(firma_id=firma_id, mali_yil=2026, fis_no=no, fis_tarihi=tarih, fis_turu="Mahsup",
                                 durum=durum, belge_no=belge_no, kaynak_turu=kaynak[0] if kaynak else None,
                                 kaynak_id=kaynak[1] if kaynak else None)
                s.add(f)
                s.flush()
                for i, (h, borc, alacak) in enumerate(satirlar, 1):
                    s.add(MuhasebeFisiSatiri(fis_id=f.id, firma_id=firma_id, sira_no=i, hesap_id=h.id,
                                             hesap_kodu=h.hesap_kodu, hesap_adi=h.hesap_adi,
                                             borc=D(borc), alacak=D(alacak)))

            fis("F1", date(2026, 9, 5), "Kesinleşmiş", [(h391, "0", "70")], ("satis_faturasi", self.f1.id),
                self.f1.fatura_no)
            fis("F2", date(2026, 9, 1), "Kesinleşmiş", [(h191, "390", "0")], ("alis_faturasi", self.a1.id),
                self.a1.fatura_no)
            fis("F3", date(2026, 10, 2), "Kesinleşmiş", [(h191, "50", "0")], ("alis_faturasi", self.a2.id),
                self.a2.fatura_no)
            fis("F4", date(2026, 9, 12), "Taslak", [(h191, "0", "40")], ("alis_iade", self.ai.id), self.ai.iade_no)
            fis("F5", date(2026, 9, 20), "Kesinleşmiş", [(h391, "0", "5")], belge_no="MAN-1")
            fis("F6", date(2026, 9, 21), "Kesinleşmiş", [(h391, "0", "70")], belge_no=self.f1.fatura_no)

        acik = srv.rapor(*EYLUL)
        self.assertTrue(acik["gm_aktif"])
        for anahtar in ("ozet", "oranlar", "belgeler", "eksik", "aylik", "toplamlar"):
            self.assertEqual(acik[anahtar], kapali[anahtar], anahtar)
        kat = {}
        for g in acik["gm"]:
            kat.setdefault(g["kategori"], []).append(g)
        self.assertEqual([g["belge"] for g in kat["Muhasebeleşmemiş belge"]],
                         [f"Satış iade faturası {self.si.iade_no}", f"Alış iade faturası {self.ai.iade_no}"])
        farklar = {g["belge"]: g for g in kat["Tutar / dönem farkı"]}
        self.assertEqual(farklar[f"Alış faturası {self.a1.fatura_no}"]["fark"], D("10"))
        self.assertIn("dönem dışında", farklar[f"Alış faturası {self.a2.fatura_no}"]["aciklama"])
        self.assertEqual([g["fis_no"] for g in kat["Olası mükerrer fiş"]], ["F6"])
        self.assertEqual([g["fis_no"] for g in kat["Belge dışı muhasebe hareketi"]], ["F5"])
        ozet = {o["kalem"]: o for o in acik["gm_ozet"]}
        h = ozet["Hesaplanan KDV (belgelerdeki, net)"]
        self.assertEqual((h["belge"], h["gm"]), (D("40.00"), D("145")))
        i = ozet["Alış KDV (tümü, net)"]
        self.assertEqual((i["belge"], i["gm"]), (D("410.00"), D("390")))


class HesapKurallari(_Taban):
    def test_kdv_dahil_yuvarlama_genel_iskonto_belge_toplamiyla_ayni(self):
        self.o.alis(50, 10, date(2026, 9, 1))
        yuv = self.satis(date(2026, 9, 3), [_satir(1, "33.33"), _satir(1, "33.33"), _satir(1, "33.33")])
        dahil = self.satis(date(2026, 9, 4), [_satir(1, "99.1667")])
        isk = self.satis(date(2026, 9, 5), [_satir(1, 1000)], tl_brut_toplam=D("1200.00"),
                         tl_genel_toplam=D("1100.00"), genel_islem_turu="INDIRIM", genel_islem_tutari=D("100"),
                         genel_islem_orani=D("8.3333"))
        r = srv.rapor(*EYLUL)
        b = {x["no"]: x for x in r["belgeler"]}
        for f in (yuv, dahil, isk):
            self.assertEqual(b[f.fatura_no]["kdv"], D(str(f.tl_kdv)), f.fatura_no)
            self.assertEqual(b[f.fatura_no]["toplam"], D(str(f.tl_genel_toplam)), f.fatura_no)
        self.assertEqual(b[yuv.fatura_no]["kdv"], D("20.01"))
        self.assertEqual((b[dahil.fatura_no]["matrah"], b[dahil.fatura_no]["kdv"]), (D("99.17"), D("19.83")))
        self.assertEqual((b[isk.fatura_no]["matrah"], b[isk.fatura_no]["kdv"]), (D("900.00"), D("200.00")))
        self.assertIn("Genel indirim", b[isk.fatura_no]["sorun"])
        fark = next(x for x in r["oranlar"] if x["tip"] == srv.ORANSIZ)
        self.assertEqual((fark["satis_matrah"], fark["satis_kdv"]), (D("-100.00"), D("0.00")))
        self.assertEqual(len(srv.rapor(*EYLUL, kdv_orani="ORANSIZ")["belgeler"]), 2)

    def test_aktarilmis_baslik_yalniz_genel_toplam_kdv_satirdan(self):
        from database.models.satis_faturasi import SatisFaturasi

        self.o.alis(10, 10, date(2026, 9, 1))
        f = self.satis(date(2026, 9, 2), [_satir(5, "8.5")])
        with get_session() as s:
            s.execute(update(SatisFaturasi).where(SatisFaturasi.id == f.id).values(tl_matrah=0, tl_kdv=0))
        r = srv.rapor(*EYLUL)
        b = next(x for x in r["belgeler"] if x["no"] == f.fatura_no)
        self.assertEqual((b["matrah"], b["kdv"], b["toplam"]), (D("42.50"), D("8.50"), D("51.00")))
        self.assertEqual(b["sorun"], "")
        self.assertIn("ayrımı kayıtlı değil", b["not"])
        self.assertEqual(r["sorunlu_sayisi"], 0)
        self.assertTrue(any(e["sorun"].startswith("Bilgi — 1 belgede") for e in r["eksik"]))

    def test_doviz_kayitli_tl_karsiligi_ve_eksik_kur(self):
        from database.models.satis_faturasi import SatisFaturasi

        self.o.alis(10, 100, date(2026, 9, 1))
        f = self.satis(date(2026, 9, 6), [_satir(2, 300, birim_fiyat_doviz=D("10"))], para_birimi="USD",
                       kur=D("30"), kur_tarihi=date(2026, 9, 6))
        r = srv.rapor(*EYLUL)
        b = next(x for x in r["belgeler"] if x["no"] == f.fatura_no)
        self.assertEqual((b["matrah"], b["kdv"], b["para_birimi"]), (D("600.00"), D("120.00"), "USD"))
        self.assertEqual(b["sorun"], "")
        with get_session() as s:
            s.execute(update(SatisFaturasi).where(SatisFaturasi.id == f.id).values(kur=D("1")))
        b = next(x for x in srv.rapor(*EYLUL)["belgeler"] if x["no"] == f.fatura_no)
        self.assertEqual(b["kdv"], D("120.00"))
        self.assertIn("kur kayıtlı değil", b["sorun"])

    def test_mukerrer_alis_ve_irsaliye_hizli_satis_donusumleri_bir_kez(self):
        from database.hizli_satis_service import HizliSatisService
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.stok import StokKarti
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService
        from hizli_satis_sepet import HizliSatisSepet

        a1 = self.alis(date(2026, 9, 1), [_satir(30, 10)], tedarikci_fatura_no="TF-55")
        a2 = self.alis(date(2026, 9, 2), [_satir(1, 10)])
        with get_session() as s:
            s.execute(update(AlisFaturasi).where(AlisFaturasi.id == a2.id).values(tedarikci_fatura_no="tf-55"))
        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date(2026, 9, 8), "cari_id": self.o.mus_id, "depo": "ANA DEPO"}, [_satir(4, 25)])
        SatisIrsaliyesiService.sevk_et(irs.id)
        irs = SatisIrsaliyesiService.getir(irs.id)
        f = self.satis(date(2026, 9, 9), [_satir(4, 25, irsaliye_satiri_id=irs.satirlar[0].id)], irsaliye_id=irs.id)
        r = srv.rapor(*EYLUL)
        self.assertEqual([b["no"] for b in r["belgeler"] if b["tur"] == srv.SATIS], [f.fatura_no])
        self.assertEqual(r["toplamlar"]["SATIS_kdv"], D("20.00"))
        mukerrer = [b["no"] for b in r["belgeler"] if "olası mükerrer" in b["sorun"]]
        self.assertEqual(sorted(mukerrer), sorted([a1.fatura_no, a2.fatura_no]))

        bugun = date.today()
        with get_session() as s:
            sid = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001"))
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=sid, stok_kodu="U001", stok_adi="Test Ürün", miktar=2, birim_fiyat="60")
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet, cari_id=self.o.mus_id, tahsilatlar=[],
            idempotency_token=HizliSatisService.yeni_idempotency_token(), musteri_bakiye=0, risk_limiti=None)
        r = srv.rapor(date(bugun.year, bugun.month, 1), bugun)
        hizli = [b for b in r["belgeler"] if b["no"] == sonuc["fatura_no"]]
        self.assertEqual(len(hizli), 1)
        self.assertEqual(len([b for b in r["belgeler"] if b["tur"] == srv.SATIS]), 1)


class DevredenKdv(_Taban):
    def test_kayit_zinciri_cift_sayim_yok_ve_kesin_kayit_korunur(self):
        from database import kdv_belge_bilgi_service as kb
        from database.models.alis_faturasi import AlisFaturasi

        self.o.alis(10, 100, date(2026, 7, 2))                         # Temmuz: alış KDV 200
        self.satis(date(2026, 8, 3), [_satir(2, 150)])                  # Ağustos: satış KDV 60
        self.satis(date(2026, 9, 3), [_satir(3, 150)])                  # Eylül: satış KDV 90
        srv.devreden_kaydet(2026, 7, 50, kaynak="Verilen beyanname", aciklama="Haziran beyannamesi")
        r = srv.rapor(date(2026, 8, 1), date(2026, 9, 30))
        # İndirilebilirlik belirtilmemişken alış KDV'si devrede kesin indirilecek sayılmaz
        self.assertEqual({x["donem"]: x for x in r["aylik"]}["2026-08"]["devreden_giris"], D("50.00"))
        with get_session() as s:
            idler = list(s.scalars(select(AlisFaturasi.id)))
        kb.toplu_bilgi_kaydet([(srv.ALIS, i) for i in idler], indirilebilirlik="INDIRILECEK")
        r = srv.rapor(date(2026, 8, 1), date(2026, 9, 30))
        ay = {x["donem"]: x for x in r["aylik"]}
        self.assertEqual(list(ay), ["2026-08", "2026-09"])
        # Temmuz: 0 − 200 − 50 → 250 devreder; Ağustos: 60 − 250 → 190; Eylül: 90 − 190 → 100
        self.assertEqual((ay["2026-08"]["devreden_giris"], ay["2026-08"]["devreden"]), (D("250.00"), D("190.00")))
        self.assertEqual((ay["2026-09"]["devreden_giris"], ay["2026-09"]["devreden"]), (D("190.00"), D("100.00")))
        self.assertEqual(ay["2026-09"]["devreden_kaynak"], "Önceki ayın ön hesabı")
        self.assertEqual(ay["2026-08"]["durum"], srv.ON_HESAP)
        self.assertFalse(r["tam_ay"])

        srv.devreden_kaydet(2026, 9, 180, kaynak="Verilen beyanname", aciklama="Ağustos beyannamesi",
                            kesinlesti=True)
        ay = {x["donem"]: x for x in srv.rapor(date(2026, 9, 1), date(2026, 9, 30))["aylik"]}
        self.assertEqual((ay["2026-09"]["devreden_giris"], ay["2026-09"]["devreden"]), (D("180.00"), D("90.00")))
        self.assertIn("190.00", ay["2026-09"]["uyari"])
        with self.assertRaises(ValueError):
            srv.devreden_kaydet(2026, 9, 200, kaynak="Diğer", aciklama="düzeltme")
        srv.devreden_kaydet(2026, 9, 190, kaynak="Mali müşavir bildirimi", aciklama="düzeltme",
                            degisiklik_gerekcesi="Ağustos beyannamesi düzeltildi")
        kayitlar = srv.devreden_kayitlari(2026)
        eylul = [k for k in kayitlar if k["donem"] == "2026-09"]
        self.assertEqual(sorted(k["durum"] for k in eylul), ["AKTIF", "IPTAL"])
        self.assertEqual(next(k for k in eylul if k["durum"] == "IPTAL")["iptal_gerekcesi"],
                         "Ağustos beyannamesi düzeltildi")
        ay = {x["donem"]: x for x in srv.rapor(date(2026, 9, 1), date(2026, 9, 30))["aylik"]}
        self.assertEqual(ay["2026-09"]["uyari"], "")
        with self.assertRaises(ValueError):
            srv.devreden_kaydet(2026, 9, 10, kaynak="Diğer", aciklama="")

    def test_yetkiler(self):
        from database.session_manager import oturum

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme", "muhasebe_goruntuleme"})
        with self.assertRaises(AccessError):
            srv.rapor(*EYLUL)
        oturum.set_user(user_id=3, kullanici_adi="izleyici", ad_soyad="İzleyici", role_kod="GORUNTULEME",
                        role_ad="Görüntüleme", permissions={srv.GORUNTULEME_YETKISI})
        self.assertEqual(srv.rapor(*EYLUL)["belge_sayisi"], 0)
        with self.assertRaises(AccessError):
            srv.devreden_kaydet(2026, 9, 10, kaynak="Diğer", aciklama="x")


class EkranMenu(_Taban):
    def test_menu_baglantilari_tek_ekran(self):
        import satin_alma_ui
        import satis_ui
        from database.system.bootstrap import IZINLER, ROL_IZINLERI

        kodlar = {k for k, _a, _m in IZINLER}
        self.assertTrue({srv.GORUNTULEME_YETKISI, srv.DEVREDEN_YETKISI} <= kodlar)
        self.assertIn(srv.GORUNTULEME_YETKISI, ROL_IZINLERI["GORUNTULEME"])
        self.assertNotIn(srv.DEVREDEN_YETKISI, ROL_IZINLERI["GORUNTULEME"])
        for modul in (satis_ui, satin_alma_ui):
            self.assertIn("kdv", [k[2] for k in modul.RAPOR_KARTLARI])
        app = type("A", (), {})()
        for ad in ("satis_raporlari_goster", "rapor_tedarikci_bakiye_durum", "rapor_tedarikci_ekstresi",
                   "rapor_stok_detayli_tedarikci_ekstre", "rapor_tahsilat_odeme"):
            setattr(app, ad, lambda: None)
        cagrilar = []
        with patch("kdv_raporu_ui.kdv_raporu_goster", lambda a, k="raporlar", **kw: cagrilar.append(k)):
            satis_ui._rapor_komutlar(app)["kdv"]()
            satin_alma_ui._rapor_komutlar(app)["kdv"]()
        self.assertEqual(cagrilar, ["satis", "satin_alma"])
        src = (ROOT / "ana_panel_ui.py").read_text(encoding="utf-8")
        self.assertIn('kdv_raporu_goster(app, "raporlar")', src)
        self.assertIn('kdv_raporu_goster(app, "genel_muhasebe")',
                      (ROOT / "genel_muhasebe_ui.py").read_text(encoding="utf-8"))

    def test_ekran_raporlar_ve_excel(self):
        import tempfile
        import tkinter as tk

        import kdv_raporu_ui

        self.o.alis(10, 100, date(2026, 9, 1))
        self.satis(date(2026, 9, 3), [_satir(2, 150)])
        try:
            kok = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        kok.withdraw()
        kok.icerik = tk.Frame(kok)
        kok.icerik.pack()
        kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
        try:
            ekran = kdv_raporu_ui.kdv_raporu_goster(kok, otomatik=False)
            ekran.girdiler["yil"].set("2026")
            ekran.girdiler["ay"].set("Eylül")
            ekran.raporla(senkron=True)
            self.assertEqual(len(ekran.tablolar_tanim), 7)
            self.assertEqual(ekran.sonuc["toplamlar"]["net_hesaplanan"], D("60.00"))
            self.assertEqual(ekran.sonuc["gm_tablo"][0]["kategori"], "Kullanılamaz")
            self.assertIn("Dönem: 01.09.2026 – 30.09.2026", ekran.filtre_ozeti())
            html = ekran.html_metni()
            self.assertIn("KDV RAPORU", html)
            self.assertIn("Genel Muhasebe: kapalı", html)
            with tempfile.TemporaryDirectory() as d:
                yol = str(Path(d) / "kdv.xlsx")
                ekran.excel_yaz(yol)
                self.assertTrue(Path(yol).is_file())
            pencere = kdv_raporu_ui.satirlari_goster(kok, next(r for r in ekran.sonuc["belgeler"] if r.get("id")))
            pencere.destroy()
            dv = kdv_raporu_ui.devreden_penceresi(kok, ekran)
            dv.alanlar["tutar"].insert(0, "1.250,50")
            dv.alanlar["aciklama"].insert(0, "Ağustos beyannamesi")
            dv.alanlar["ay"].set("Eylül")
            dv.alanlar["yil"].set("2026")
            with patch("kdv_raporu_ui.messagebox"), patch.object(ekran, "raporla"):
                dv.kaydet()
            self.assertEqual(srv.devreden_kayitlari()[0]["tutar"], D("1250.50"))
            dv.destroy()
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
