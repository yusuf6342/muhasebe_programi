"""Stoklar → Raporlar: durum, değerleme, kritik, yavaş, yaşlandırma, devir, sayım, transfer, tutarlılık (izole DB)."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from database import stok_rapor_service as srv  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

BUGUN = date.today()


def gun(n: int) -> date:
    return BUGUN - timedelta(days=n)


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])
        self.u2 = self.o.urun_ekle("U002", "İkinci Ürün")
        with get_session() as s:
            self.u1 = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001"))
            self.ana = s.scalar(select(Depo.id).where(Depo.ad == "ANA DEPO"))

    def tearDown(self):
        self.o.kapat()

    def hareket_sayisi(self) -> int:
        with get_session() as s:
            return int(s.scalar(select(func.count(StokHareketi.id))) or 0)

    def transfer(self, miktar, tarih, kod="U001"):
        from database.stok_service import StokService

        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "DEPO 2", "fis_tarihi": tarih},
            [{"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": D(str(miktar))}])


class StokDurumuTest(_Taban):
    def test_bekleyen_siparisler_ayri_kullanilabilir_cift_dusmez(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from database.satis_siparisi_service import SatisSiparisiService

        self.o.alis(10, 100, gun(10))
        self.o.satis(3, 150, gun(5))
        self.o.satis(2, 150, gun(4), onayla=False)
        sp = AlisSiparisiService.kaydet(
            {"siparis_tarihi": gun(3), "termin_tarihi": BUGUN, "cari_id": self.o.ted_id, "durum": "TASLAK"},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("5"), "birim": "Adet",
              "birim_alis_fiyati": D("100"), "kdv_orani": D("20")}], [])
        AlisSiparisiService.kesinlestir(sp.id)
        SatisSiparisiService.kaydet(
            {"siparis_tarihi": gun(2), "termin_tarihi": BUGUN, "cari_id": self.o.mus_id, "onayla": True},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("4"), "birim": "Adet",
              "birim_satis_fiyati": D("150"), "kdv_orani": D("20")}], [])
        once = self.hareket_sayisi()

        r = srv.stok_durumu()
        satir = next(x for x in r["satirlar"] if x["urun_kodu"] == "U001" and x["depo"] == "ANA DEPO")
        self.assertEqual(satir["mevcut"], D("7"))
        self.assertEqual(satir["rezervasyon"], D("0"))
        self.assertEqual(satir["bekleyen_satis"], D("4"))
        self.assertEqual(satir["kullanilabilir"], D("3"))
        self.assertEqual(satir["bekleyen_alis"], D("5"))
        self.assertEqual(satir["ongorulen"], D("8"))
        self.assertEqual(satir["yoldaki"], D("0"))
        self.assertEqual(satir["deger"], D("700.00"))
        self.assertEqual(r["depolar"][-1]["depo"], "FİRMA TOPLAMI")
        self.assertTrue(r["depolar"][-1]["_sabit"])
        self.assertEqual(self.hareket_sayisi(), once)


class DegerlemeTest(_Taban):
    def test_tarihli_fifo_eksik_maliyet_sifir_sayilmaz(self):
        self.o.alis(10, 100, gun(40), lot="L1")
        self.o.alis(10, 200, gun(30), lot="L2")
        self.o.satis(15, 300, gun(20))
        self.o.alis(4, 50, gun(15), kod="U002", lot="M1")
        with get_session() as s:
            for lot in s.scalars(select(StokLotu).where(StokLotu.stok_id == self.u2)).all():
                lot.birim_maliyet = D("0")

        gecmis = srv.degerleme(tarih=gun(35))
        u1 = next(x for x in gecmis["satirlar"] if x["urun_kodu"] == "U001")
        self.assertEqual((u1["miktar"], u1["toplam_maliyet"]), (D("10"), D("1000.00")))
        self.assertFalse(any(x["urun_kodu"] == "U002" for x in gecmis["satirlar"]))

        bugun = srv.degerleme(tarih=BUGUN)
        u1 = next(x for x in bugun["satirlar"] if x["urun_kodu"] == "U001")
        self.assertEqual((u1["miktar"], u1["toplam_maliyet"]), (D("5"), D("1000.00")))
        u2 = next(x for x in bugun["satirlar"] if x["urun_kodu"] == "U002")
        self.assertEqual(u2["durum"], "Eksik maliyet")
        self.assertIsNone(u2["toplam_maliyet"])
        self.assertEqual(bugun["toplam_maliyet"], D("1000.00"))
        self.assertEqual(bugun["eksik_satir"], 1)
        self.assertEqual([x["urun_kodu"] for x in bugun["sorunlu"]], ["U002"])
        self.assertEqual(bugun["gruplar"][0]["ana_grup"], "(Grupsuz)")

        from database.satis_maliyet_motoru import HAREKETLI

        hareketli = srv.degerleme(tarih=BUGUN, yontem=HAREKETLI)
        u1 = next(x for x in hareketli["satirlar"] if x["urun_kodu"] == "U001")
        self.assertEqual(u1["toplam_maliyet"], D("750.00"))

    def test_satis_fiyati_degeri_ayri_ve_toplama_girmez(self):
        from database.models.stok import StokFiyati

        self.o.alis(2, 100, gun(5))
        with get_session() as s:
            s.add(StokFiyati(stok_id=self.u1, fiyat_adi="SATIŞ FİYATI 1", tutar=D("180")))
        r = srv.degerleme(tarih=BUGUN, satis_fiyati=True)
        u1 = next(x for x in r["satirlar"] if x["urun_kodu"] == "U001")
        self.assertEqual(u1["satis_degeri"], D("360.00"))
        self.assertEqual(r["toplam_maliyet"], D("200.00"))


class KritikTest(_Taban):
    def test_minimum_alti_sifir_ve_stoksuz_gecmis(self):
        from database.stok_uyari_service import StokUyariService

        StokUyariService.ayar_kaydet(self.u1, None, {"minimum": "20"})
        self.o.alis(10, 100, gun(10))
        self.o.alis(2, 100, gun(9), kod="U002")
        self.o.satis(2, 150, gun(3), kod="U002")
        self.o.urun_ekle("U003", "Hareketsiz")

        r = srv.kritik_tukenen(donem_gun=30)
        durum = {x["urun_kodu"]: x["durum"] for x in r["satirlar"]}
        self.assertEqual(durum["U001"], "Minimum altı")
        self.assertEqual(durum["U002"], "Sıfır")
        self.assertNotIn("U003", durum)
        self.assertIn("U002", [x["urun_kodu"] for x in r["minimumsuz"]])
        self.assertNotIn("U001", [x["urun_kodu"] for x in r["minimumsuz"]])
        u2 = next(x for x in r["satirlar"] if x["urun_kodu"] == "U002")
        self.assertEqual(u2["donem_satis"], D("2"))
        self.assertEqual(u2["son_tedarikci"], "Test Tedarikçi")
        g = next(x for x in r["gecmis"] if x["urun_kodu"] == "U002")
        self.assertEqual((g["bas"], g["durum"]), (gun(3), "Devam ediyor"))


class YavasSatilmayanTest(_Taban):
    def test_yavas_hic_satilmayan_yeni_ve_transfer_satis_sayilmaz(self):
        self.o.alis(5, 100, gun(200))
        self.o.satis(1, 150, gun(150))
        self.o.alis(3, 100, gun(10), kod="U002")
        self.o.urun_ekle("U003", "Eski")
        self.o.alis(4, 100, gun(120), kod="U003")
        self.transfer(2, gun(5), kod="U003")

        r = srv.yavas_satilmayan(bas=gun(364), bit=BUGUN, esik_gun=90, yeni_gun=30)
        satir = {x["urun_kodu"]: x for x in r["satirlar"]}
        self.assertEqual(satir["U001"]["tur"], "yavas")
        self.assertEqual(satir["U001"]["son_satis_gun"], 150)
        self.assertEqual(satir["U002"]["tur"], "yeni")
        self.assertEqual(satir["U003"]["tur"], "hic_satilmayan")
        self.assertIsNone(satir["U003"]["son_satis"])
        self.assertEqual(satir["U003"]["ilk_giris"], gun(120))
        self.assertEqual(satir["U003"]["son_giris"], gun(120))
        self.assertEqual(satir["U003"]["miktar"], D("4"))
        sadece = srv.yavas_satilmayan(bas=gun(364), bit=BUGUN, tur="hic_satilmayan")
        self.assertEqual([x["urun_kodu"] for x in sadece["satirlar"]], ["U003"])


class YaslandirmaTest(_Taban):
    def test_transfer_yasi_sifirlamaz_devir_ayri(self):
        self.o.alis(5, 100, gun(100))
        self.transfer(5, gun(1))
        with get_session() as s:
            lot = StokLotu(stok_id=self.u2, depo_id=self.ana, lot_no="EVB-1", tedarikci="EvoBulut açılış (a_kalan)",
                           giris_tarihi=gun(400), kalan_miktar=D("3"), birim_maliyet=D("10"))
            s.add(lot)
            s.flush()
            s.add(StokHareketi(tarih=gun(400), hareket_turu="GİRİŞ", belge_no="EVB-1", stok_id=self.u2,
                               depo_id=self.ana, lot_id=lot.id, miktar=D("3"), birim_maliyet=D("10")))

        r = srv.yaslandirma(tarih=BUGUN)
        satir = {x["urun_kodu"]: x for x in r["satirlar"]}
        self.assertEqual(satir["U001"]["m_91_180"], D("5"))
        self.assertEqual(satir["U001"]["m_0_30"], D("0"))
        self.assertEqual(satir["U001"]["d_91_180"], D("500.00"))
        self.assertEqual(satir["U002"]["devir_miktar"], D("3"))
        self.assertEqual(satir["U002"]["m_365p"], D("0"))
        self.assertTrue(satir["TOPLAM"]["_sabit"])
        self.assertEqual(satir["TOPLAM"]["deger"], D("530.00"))


class DevirYeterlilikTest(_Taban):
    def test_iade_dahil_hiz_yeterlilik_ve_devir_orani(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(10, 100, gun(60))
        f = self.o.satis(4, 150, gun(30))
        kaynak = SatisFaturasiService.getir(f.id).satirlar[0]
        SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": gun(20), "cari_id": self.o.mus_id, "depo": "ANA DEPO", "kaynak_fatura_id": f.id,
             "iade_odeme_tutari": D("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("1"), "birim": "Adet",
              "birim_fiyat": D("150"), "kdv_orani": D("20"), "kaynak_fatura_satiri_id": kaynak.id}])
        self.o.alis(3, 100, gun(10), kod="U002")

        r = srv.devir_yeterlilik(bas=gun(59), bit=BUGUN)
        self.assertEqual(r["gun"], 60)
        satir = {x["urun_kodu"]: x for x in r["satirlar"]}
        u1 = satir["U001"]
        self.assertEqual(u1["net_satis_miktari"], D("3"))
        self.assertEqual(u1["gunluk_hiz"], D("0.050"))
        self.assertEqual(u1["kullanilabilir"], D("7"))
        self.assertEqual(u1["yeterlilik_gun"], 140)
        self.assertEqual(u1["satis_maliyeti"], D("300.00"))
        self.assertIsNotNone(u1["devir_orani"])
        self.assertGreater(u1["devir_orani"], 0)
        self.assertIsNone(satir["U002"]["yeterlilik_gun"])
        self.assertIsNone(satir["U002"]["devir_orani"])
        self.assertIn("Satış hızı 0", satir["U002"]["aciklama"])


class SayimTransferTest(_Taban):
    def test_sayim_farki_maliyet_ve_sonraki_hareket(self):
        from database.stok_sayim_service import StokSayimService

        self.o.alis(10, 100, gun(5))
        StokSayimService.kaydet_ve_onayla(self.ana, gun(2), [
            {"stok_id": self.u1, "sistem_miktar": D("10"), "sayilan_miktar": D("8")}])
        self.o.satis(1, 150, gun(1))
        once = self.hareket_sayisi()

        r = srv.sayim_farklari()
        self.assertEqual(len(r["satirlar"]), 1)
        x = r["satirlar"][0]
        self.assertEqual((x["sistem"], x["sayilan"], x["fark"]), (D("10"), D("8"), D("-2")))
        self.assertEqual(x["eksik_fazla"], "Eksik")
        self.assertEqual(x["maliyet_farki"], D("-200.00"))
        self.assertIn(x["fis_no"], x["bagli_evrak"])
        self.assertEqual(x["onaylayan"], "Kayıtlı değil")
        self.assertIn("1 hareket", x["sonraki"])
        self.assertEqual(r["eksik_tutar"], D("-200.00"))
        self.assertEqual(self.hareket_sayisi(), once)

    def test_transfer_takibi_tamamlanan_ve_hareket_eklemez(self):
        self.o.alis(5, 100, gun(5))
        self.transfer(3, gun(2))
        once = self.hareket_sayisi()
        r = srv.transfer_takibi()
        self.assertEqual(len(r["satirlar"]), 1)
        x = r["satirlar"][0]
        self.assertEqual((x["gonderilen"], x["alinan"], x["yoldaki"]), (D("3"), D("3"), D("0")))
        self.assertEqual(x["durum"], "Tamamlandı")
        self.assertEqual((x["kaynak"], x["hedef"]), ("ANA DEPO", "DEPO 2"))
        self.assertEqual(srv.transfer_takibi(depo="DEPO 2")["satirlar"][0]["fis_no"], x["fis_no"])
        self.assertEqual(self.hareket_sayisi(), once)


class TutarlilikTest(_Taban):
    def test_normal_belgeler_hata_degil_sorunlar_bulunur_veri_degismez(self):
        self.o.alis(10, 100, gun(5))
        self.o.satis(3, 150, gun(3))
        self.o.satis(1, 150, gun(2), onayla=False)
        temiz = srv.tutarlilik_kontrolu()
        self.assertEqual(temiz["satirlar"], [])

        self.o.alis(2, 100, gun(4), kod="U002")
        with get_session() as s:
            from database.models.stok import StokBarkod

            s.get(StokKarti, self.u1).barkod = "8690000000001"
            s.add(StokBarkod(stok_id=self.u2, barkod="8690000000001", birim="Adet"))
            for lot in s.scalars(select(StokLotu).where(StokLotu.stok_id == self.u2)).all():
                lot.birim_maliyet = D("0")
            lot = s.scalar(select(StokLotu).where(StokLotu.stok_id == self.u1))
            s.add(StokHareketi(tarih=gun(1), hareket_turu="FATURA ÇIKIŞ", belge_no="YOK-1", stok_id=self.u1,
                               depo_id=self.ana, lot_id=lot.id, miktar=D("1"), birim_maliyet=D("100")))
        once = self.hareket_sayisi()
        r = srv.tutarlilik_kontrolu()
        turler = {x["hata_turu"] for x in r["satirlar"]}
        self.assertIn("Mükerrer barkod", turler)
        self.assertIn("Eksik maliyet", turler)
        self.assertIn("Kaynağı bulunamayan hareket", turler)
        self.assertIn("Lot ve hareket bakiyesi farklı", turler)
        self.assertTrue(all(x["oneri"] for x in r["satirlar"]))
        self.assertEqual(self.hareket_sayisi(), once)
        yuksek = srv.tutarlilik_kontrolu(onem="Yüksek")["satirlar"]
        self.assertTrue(all(x["onem"] == "Yüksek" for x in yuksek))


class YenidenSiparisTest(_Taban):
    def test_tedarik_suresi_varsayimi_hedefe_eklenir(self):
        from database.satin_alma_rapor_service import yeniden_siparis_onerisi
        from database.stok_uyari_service import StokUyariService

        StokUyariService.ayar_kaydet(self.u1, None, {"minimum": "5"})
        self.o.alis(10, 100, gun(40))
        self.o.satis(9, 150, gun(5))
        yok = next(x for x in yeniden_siparis_onerisi(donem_gun=30, hedef_gun=30)["satirlar"]
                   if x["stok_kodu"] == "U001")
        r = yeniden_siparis_onerisi(donem_gun=30, hedef_gun=30, tedarik_gun=10)
        var = next(x for x in r["satirlar"] if x["stok_kodu"] == "U001")
        self.assertEqual(yok["hedef"], D("9"))
        self.assertEqual(var["hedef"], D("12"))
        self.assertTrue(any("kullanıcı varsayımı 10 gün" in n for n in r["notlar"]))


class EkranMenuTest(_Taban):
    def test_gruplu_menu_ve_ekranlar_acilir(self):
        import tkinter as tk

        import stok_raporlari_ui as ui
        import stoklar_ui

        self.o.alis(5, 100, gun(5))
        try:
            kok = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        kok.withdraw()
        kok.icerik = tk.Frame(kok)
        kok.icerik.pack()
        kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
        kok.stok_kartlari_goster = lambda: None
        try:
            self.assertEqual([g for g, _k in stoklar_ui.RAPOR_GRUPLARI],
                             ["Stok Listeleri", "Durum ve Hareket", "Stok Planlama", "Değer ve Verimlilik",
                              "Sayım ve Kontrol"])
            komutlar = stoklar_ui._rapor_komutlar(kok)
            for _b, _a, anahtar in stoklar_ui.RAPOR_KARTLARI:
                self.assertTrue(callable(komutlar.get(anahtar)), anahtar)
            stoklar_ui.stoklar_raporlar_hub_goster(kok)
            for fn in (ui.stok_durumu_goster, ui.degerleme_goster, ui.kritik_tukenen_goster,
                       ui.yavas_satilmayan_goster, ui.yaslandirma_goster, ui.devir_yeterlilik_goster,
                       ui.sayim_farklari_goster, ui.transfer_takibi_goster, ui.tutarlilik_kontrolu_goster):
                ekran = fn(kok, otomatik=False)
                ekran.raporla(senkron=True)
                self.assertIn("notlar", ekran.sonuc, fn.__name__)
            ekran = ui.degerleme_goster(kok, sekme="gruplar", otomatik=False)
            self.assertEqual(ekran.defter.index(ekran.defter.select()), 3)
            from satin_alma_rapor_ui import yeniden_siparis_onerisi_goster

            ekran = yeniden_siparis_onerisi_goster(kok, ust=ui._ust, otomatik=False)
            ekran.raporla(senkron=True)
            self.assertTrue(any("Tedarik süresi" in n for n in ekran.sonuc["notlar"]))
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
