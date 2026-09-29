"""Fatura ödeme / kapatma izleme ve faturadan yeni adres ekleme (yalnız geçici test veritabanı)."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.kapatma_izleme_service import (
    BILINMIYOR,
    MESAJ_KAYIT_YOK,
    MESAJ_TASLAK,
    acik_kalemler_listesi,
    evrak_kapatma_detayi,
    fatura_odeme_ozeti,
    kaynak_dagitim_detayi,
    tutarsizlik_raporu,
)
from database.models.cari import Cari, CariKapatma, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from tests import test_tahsilat_makbuzu as _servis_testi

D = Decimal


def _fatura(s, cari_id, no, tarih, toplam, *, onayli=True, kalan=None):
    toplam = D(toplam)
    f = SatisFaturasi(
        fatura_no=no, fatura_tarihi=tarih, vade_tarihi=tarih, cari_id=cari_id,
        durum="AÇIK" if onayli else "TASLAK", onaylandi=onayli, depo="ANA DEPO",
        tahsilat_tutari=D("0") if kalan is None else toplam - D(kalan),
        tl_genel_toplam=toplam, tl_brut_toplam=toplam, row_version=1,
    )
    f.satirlar.append(
        SatisFaturasiSatiri(urun_kodu="U1", urun_adi="Masa", miktar=D("1"), birim="Adet",
                            birim_fiyat=toplam, kdv_orani=D("0"))
    )
    s.add(f)
    if onayli:
        s.add(SatisHareketi(cari_id=cari_id, satis_tarihi=tarih, belge_no=no, satis_tutari=toplam,
                            kalan_acik_tutar=toplam if kalan is None else D(kalan)))
    s.flush()
    return f.id


class OdemeKapatmaIzlemeTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        with get_session() as s:
            self.f1000 = _fatura(s, self.musteri_id, "SF-K-1000", date(2026, 5, 1), "1000")

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def _makbuz(self, tutar, fatura_id=0, tarih=None):
        return FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": tarih or date.today(),
            "cari_id": self.musteri_id,
            "makbuz_no_otomatik": True,
            "fatura_id": fatura_id,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": tutar}],
        })

    def test_kismi_sonra_tam_iki_taraftan(self):
        m1 = self._makbuz("400", self.f1000)
        d = evrak_kapatma_detayi("SF-K-1000")
        self.assertEqual((d["esas_tutar"], d["kapanan"], d["kalan"]), (D("1000.00"), D("400.00"), D("600.00")))
        self.assertEqual(d["odeme_durumu"], "Kısmen Ödendi")
        self.assertEqual([(r["kaynak"], r["pay"]) for r in d["kapatanlar"]], [("KAYIT", D("400.00"))])
        self.assertEqual(d["kapatanlar"][0]["evrak_toplami"], D("400.00"))
        self.assertTrue(d["tutarli"])
        k = kaynak_dagitim_detayi(m1.belge_no, self.musteri_id)
        self.assertEqual([(r["evrak_no"], r["kapatilan"], r["sonrasi_kalan"]) for r in k["satirlar"]],
                         [("SF-K-1000", D("400.00"), D("600.00"))])
        self.assertEqual((k["toplam"], k["dagitilan"], k["avans_kalan"]), (D("400.00"), D("400.00"), D("0.00")))
        self._makbuz("600", self.f1000)
        d = evrak_kapatma_detayi("SF-K-1000")
        self.assertEqual((d["kalan"], d["odeme_durumu"]), (D("0.00"), "Kapandı"))
        self.assertEqual(sum(r["pay"] for r in d["kapatanlar"]) + d["kalan"], d["esas_tutar"])
        oz = fatura_odeme_ozeti(self.f1000)
        self.assertEqual((oz["kapanan"], oz["kalan"], oz["durum"]), (D("1000.00"), D("0.00"), "Kapandı"))
        with get_session() as s:
            self.assertEqual(D(str(s.get(SatisFaturasi, self.f1000).tahsilat_tutari)), D("1000.00"))

    def test_bir_makbuz_iki_fatura_ve_avans_fifo(self):
        with get_session() as s:
            a = _fatura(s, self.musteri_id, "SF-K-A", date(2026, 6, 1), "500")
            b = _fatura(s, self.musteri_id, "SF-K-B", date(2026, 6, 2), "700")
        # FIFO: SF-K-1000 (en eski) önce; fatura bağsız 1.500 → 1000 + 500, avans yok
        m = self._makbuz("1500")
        k = kaynak_dagitim_detayi(m.belge_no, self.musteri_id)
        self.assertEqual([r["evrak_no"] for r in k["satirlar"]], ["SF-K-1000", "SF-K-A"])
        self.assertEqual(k["dagitilan"] + k["avans_kalan"], k["toplam"])
        # İkinci makbuz: 700 + 300 avans
        m2 = self._makbuz("1000")
        k2 = kaynak_dagitim_detayi(m2.belge_no, self.musteri_id)
        self.assertEqual((k2["dagitilan"], k2["avans_kalan"], k2["toplam"]), (D("700.00"), D("300.00"), D("1000.00")))
        self.assertIsNone(k2["mesaj"])
        # Avans sonra yeni faturaya kullanılır → iki tarafta da bağlantı görünür
        from database.acik_kalem_service import AcikKalemService
        with get_session() as s:
            _fatura(s, self.musteri_id, "SF-K-C", date(2026, 6, 3), "200")
            AcikKalemService.avanslari_uygula(s, self.musteri_id)
        dc = evrak_kapatma_detayi("SF-K-C")
        self.assertEqual([(r["tur"], r["pay"]) for r in dc["kapatanlar"]], [("Avans kullanımı", D("200.00"))])
        k2 = kaynak_dagitim_detayi(m2.belge_no, self.musteri_id)
        self.assertIn("SF-K-C", [r["evrak_no"] for r in k2["satirlar"]])
        self.assertEqual((k2["avans_kalan"], k2["dagitilan"] + k2["avans_kalan"]), (D("100.00"), D("1000.00")))
        _ = (a, b)

    def test_sadece_avans_mesaji_ve_iptal_gecmisi(self):
        with get_session() as s:
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-K-1000"))
            s.delete(h)
            s.get(SatisFaturasi, self.f1000).durum = "İPTAL"
        m = self._makbuz("250")
        k = kaynak_dagitim_detayi(m.belge_no, self.musteri_id)
        self.assertEqual((k["satirlar"], k["avans_kalan"]), ([], D("250.00")))
        self.assertEqual(k["mesaj"], "Açık kaleme bağlanmadı / Avans")

    def test_makbuz_iptali_geri_acar_ve_gecmise_yazar(self):
        m = self._makbuz("400", self.f1000)
        FinansService.kasa_makbuz_iptal(m.id)
        d = evrak_kapatma_detayi("SF-K-1000")
        self.assertEqual((d["kalan"], d["odeme_durumu"]), (D("1000.00"), "Ödenmedi"))
        self.assertEqual(d["kapatanlar"], [])
        self.assertEqual(d["mesaj"], MESAJ_KAYIT_YOK)
        self.assertEqual([i["tutar"] for i in d["iptaller"]], [D("400.00")])
        with get_session() as s:
            self.assertEqual(D(str(s.get(SatisFaturasi, self.f1000).tahsilat_tutari)), D("0.00"))

    def test_tarihsel_bilinmeyen_tahmin_edilmez(self):
        with get_session() as s:
            _fatura(s, self.musteri_id, "SF-K-ESKI", date(2025, 1, 1), "1000", kalan="700")
        d = evrak_kapatma_detayi("SF-K-ESKI")
        self.assertEqual([(r["kaynak"], r["pay"], r["evrak_turu"]) for r in d["kapatanlar"]],
                         [("BILINMIYOR", D("300.00"), BILINMIYOR)])
        self.assertEqual(d["odeme_durumu"], "Kısmen Ödendi")

    def test_tutarsizlik_uyarir_duzeltmez(self):
        with get_session() as s:
            fid = _fatura(s, self.musteri_id, "SF-K-BOZUK", date(2026, 1, 1), "100")
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-K-BOZUK"))
            s.add(CariKapatma(islem_kimligi="x", cari_id=self.musteri_id, kaynak_belge_no="THS-X",
                              kaynak_tur="TAHSILAT", hedef_hareket_id=h.id, hedef_belge_no="SF-K-BOZUK",
                              tutar=D("60"), para_birimi="TRY", tarih=date(2026, 1, 2), yontem="FIFO",
                              iptal=False))
        d = evrak_kapatma_detayi("SF-K-BOZUK")
        self.assertFalse(d["tutarli"])
        self.assertIn("aşıyor", d["uyari"])
        self.assertIn("SF-K-BOZUK", [r["belge_no"] for r in tutarsizlik_raporu(self.musteri_id)])
        with get_session() as s:
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-K-BOZUK"))
            self.assertEqual(D(str(h.kalan_acik_tutar)), D("100.00"))
        _ = fid

    def test_taslak_mesaji(self):
        with get_session() as s:
            tid = _fatura(s, self.musteri_id, "SF-K-TASLAK", date(2026, 6, 1), "300", onayli=False)
        d = evrak_kapatma_detayi("SF-K-TASLAK")
        self.assertTrue(d["taslak"])
        self.assertEqual(d["mesaj"], MESAJ_TASLAK)
        self.assertEqual(fatura_odeme_ozeti(tid)["taslak"], True)

    def test_onay_kaldirmada_bagli_makbuz_payi_faturada_kalir(self):
        m = self._makbuz("400", self.f1000)
        with get_session() as s:
            f = s.get(SatisFaturasi, self.f1000)
            FinansService.bagli_makbuz_paylarini_faturada_tut(s, f, neden="test")
            from database.acik_kalem_service import AcikKalemService
            AcikKalemService.belge_kalemlerini_sil(s, f.fatura_no, f.cari_id, neden="test")
            f.onaylandi = False
            f.durum = "TASLAK"
        with get_session() as s:
            f = s.get(SatisFaturasi, self.f1000)
            self.assertEqual(D(str(f.tahsilat_tutari)), D("400.00"))
            avans = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == m.belge_no))
            self.assertIsNone(avans)
        FinansService.kasa_makbuz_iptal(m.id)
        with get_session() as s:
            self.assertEqual(D(str(s.get(SatisFaturasi, self.f1000).tahsilat_tutari)), D("0.00"))

    def test_acik_kalemler_vadesi_gecen(self):
        with get_session() as s:
            _fatura(s, self.musteri_id, "SF-K-GELECEK", date.today() + timedelta(days=10), "50")
        tum = acik_kalemler_listesi(self.musteri_id)
        gecen = acik_kalemler_listesi(self.musteri_id, sadece_vadesi_gecen=True)
        self.assertIn("SF-K-GELECEK", [s["evrak_no"] for s in tum])
        self.assertNotIn("SF-K-GELECEK", [s["evrak_no"] for s in gecen])
        self.assertIn("SF-K-1000", [s["evrak_no"] for s in gecen])

    def test_buyuk_tutar(self):
        with get_session() as s:
            fid = _fatura(s, self.musteri_id, "SF-K-BUYUK", date(2026, 1, 1), "987654321.99")
        # Bağsız 1.000 FIFO ile en eski (SF-K-BUYUK) kaleme düşer
        self._makbuz("1000", 0)
        self._makbuz("123456789.10", fid)
        d = evrak_kapatma_detayi("SF-K-BUYUK")
        self.assertEqual(d["kalan"], D("864196532.89"))
        self.assertEqual(sum(r["pay"] for r in d["kapatanlar"]) + d["kalan"], d["esas_tutar"])


class YeniAdresTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def test_bos_yuvaya_ekler_ve_dogrular(self):
        with get_session() as s:
            c = s.get(Cari, self.musteri_id)
            c.adres, c.il, c.ilce = "Eski Mah. 1", "Ankara", "Çankaya"
            c.adres2 = c.il2 = c.ilce2 = c.adres3 = c.il3 = c.ilce3 = None
        self.assertEqual(CariService.bos_adres_slotu(self.musteri_id), 2)
        with self.assertRaises(ValueError):
            CariService.adres_ekle(self.musteri_id, "Sevk", "   ")
        with self.assertRaises(ValueError):
            CariService.adres_ekle(self.musteri_id, "Yok", "Adres")
        no = CariService.adres_ekle(self.musteri_id, "Sevk", "Depo Sok. 5", il="İzmir", ilce="Bornova")
        self.assertEqual(no, 2)
        c = CariService.getir(self.musteri_id)
        self.assertEqual((c.adres2, c.il2, c.ilce2, c.adres_tipi2), ("Depo Sok. 5", "İzmir", "Bornova", "Sevk"))
        self.assertEqual(c.adres, "Eski Mah. 1")
        CariService.adres_ekle(self.musteri_id, "Şube", "Şube Cad. 9")
        with self.assertRaises(ValueError):
            CariService.adres_ekle(self.musteri_id, "Diğer", "Dördüncü")
        self.assertIsNone(CariService.bos_adres_slotu(self.musteri_id))


if __name__ == "__main__":
    unittest.main()
