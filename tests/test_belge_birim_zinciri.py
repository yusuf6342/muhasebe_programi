"""Belgelerde birim seçimi: sipariş → irsaliye → fatura → iade zincirinde birim korunur,
stok temel birimde işler (2 Koli × 12 = 24), teklif katsayısı karttan gelir.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_belge_birim_zinciri.py -q
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.models.stok import StokHareketi, StokKarti  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

BUGUN = date.today()
T1, T2, T3 = BUGUN - timedelta(days=6), BUGUN - timedelta(days=5), BUGUN - timedelta(days=4)


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])

    def tearDown(self):
        self.o.kapat()


class AlisZinciriBirimTest(_Taban):
    def _siparis(self, miktar="2", birim="Koli"):
        from database.alis_siparisi_service import AlisSiparisiService

        s = AlisSiparisiService.kaydet(
            {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.ted_id},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": miktar, "birim": birim,
              "birim_alis_fiyati": "120", "kdv_orani": "20"}],
            [],
        )
        return AlisSiparisiService.getir(s.id).satirlar[0]

    def _irsaliye(self, ss, birim, miktar="2"):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        i = AlisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": T2, "cari_id": self.o.ted_id, "siparis_id": ss.siparis_id},
            [{"siparis_satiri_id": ss.id, "urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": miktar,
              "birim": birim, "birim_fiyat": "120", "kdv_orani": "20"}],
        )
        return AlisIrsaliyesiService.getir(i.id)

    def _fatura(self, birim, miktar="2", **bag):
        from database.alis_faturasi_service import AlisFaturasiService

        return AlisFaturasiService.kaydet(
            {"fatura_tarihi": T3, "vade_tarihi": T3, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal(miktar), "birim": birim,
              "birim_fiyat": Decimal("120"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"), **bag}],
        )

    def test_siparisten_irsaliyeye_farkli_birim_reddedilir(self):
        ss = self._siparis()
        with self.assertRaises(ValueError) as ctx:
            self._irsaliye(ss, "Adet", "24")
        self.assertIn("sipariş birimiyle aynı", str(ctx.exception))
        from database.alis_siparisi_service import AlisSiparisiService

        self.assertEqual(AlisSiparisiService.getir(ss.siparis_id).satirlar[0].irsaliyelenen_miktar, Decimal("0"))
        irs = self._irsaliye(ss, "koli")
        self.assertEqual(irs.satirlar[0].miktar, Decimal("2"))

    def test_irsaliyeden_faturaya_birim_korunur_stok_temel_birimde(self):
        ss = self._siparis()
        irs = self._irsaliye(ss, "Koli")
        isid = irs.satirlar[0].id
        with self.assertRaises(ValueError) as ctx:
            self._fatura("Adet", "24", irsaliye_satiri_id=isid)
        self.assertIn("irsaliye birimiyle aynı", str(ctx.exception))
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))

        f = self._fatura("Koli", "2", irsaliye_satiri_id=isid)
        self.assertEqual(self.o.lot_toplam(), Decimal("24"))
        from database.alis_faturasi_service import AlisFaturasiService

        tekrar = AlisFaturasiService.getir(f.id)
        satir = tekrar.satirlar[0]
        self.assertEqual((satir.birim, Decimal(str(satir.miktar))), ("Koli", Decimal("2")))
        self.assertEqual(Decimal(str(satir.birim_carpani)), Decimal("12"))
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        self.assertEqual(AlisIrsaliyesiService.getir(irs.id).satirlar[0].faturalanan_miktar, Decimal("2"))

    def test_siparisten_dogrudan_faturada_farkli_birim_reddedilir(self):
        ss = self._siparis()
        with self.assertRaises(ValueError) as ctx:
            self._fatura("Adet", "24", siparis_satiri_id=ss.id)
        self.assertIn("sipariş birimiyle aynı", str(ctx.exception))
        self._fatura("Koli", "1", siparis_satiri_id=ss.id)
        self.assertEqual(self.o.lot_toplam(), Decimal("12"))


class SatisZinciriBirimTest(_Taban):
    def test_siparis_irsaliye_fatura_iade_koli_temel_birimde(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService
        from database.satis_siparisi_service import SatisSiparisiService

        self.o.alis(30, 10, T1, lot="L1")
        sp = SatisSiparisiService.kaydet(
            {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.mus_id, "onayla": True},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("2"), "birim": "Koli",
              "birim_satis_fiyati": Decimal("150"), "kdv_orani": Decimal("20")}], [])
        ss = sp.satirlar[0]
        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": T2, "cari_id": self.o.mus_id, "depo": "ANA DEPO"},
            [{"siparis_satiri_id": ss.id, "urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("2"),
              "birim": "Koli", "birim_fiyat": Decimal("150"), "kdv_orani": Decimal("20")}])
        SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        irs = SatisIrsaliyesiService.getir(irs.id)
        self.assertEqual(irs.satirlar[0].birim, "Koli")

        fatura_veri = {"fatura_tarihi": T3, "vade_tarihi": T3, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
                       "irsaliye_id": irs.id, "odeme_tutari": Decimal("0"), "sales_person_id": 1}
        satir = {"urun_kodu": "U001", "urun_adi": "Test Ürün", "birim_fiyat": Decimal("150"),
                 "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
                 "irsaliye_satiri_id": irs.satirlar[0].id, "siparis_satiri_id": ss.id}
        with self.assertRaises(ValueError) as ctx:
            SatisFaturasiService.kaydet(fatura_veri, [{**satir, "miktar": Decimal("24"), "birim": "Adet"}])
        self.assertIn("irsaliye birimiyle aynı", str(ctx.exception))
        f = SatisFaturasiService.kaydet(fatura_veri, [{**satir, "miktar": Decimal("2"), "birim": "Koli"}])
        SatisFaturasiService.onayla(f.id)
        self.assertEqual(self.o.lot_toplam(), Decimal("6"), "irsaliyeli faturada ikinci stok çıkışı olmamalı")
        f = SatisFaturasiService.getir(f.id)
        self.assertEqual((f.satirlar[0].birim, Decimal(str(f.satirlar[0].miktar))), ("Koli", Decimal("2")))

        SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO", "kaynak_fatura_id": f.id,
             "iade_odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("150"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "kaynak_fatura_satiri_id": f.satirlar[0].id}])
        self.assertEqual(self.o.lot_toplam(), Decimal("18"))
        with get_session() as s:
            stok_id = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001"))
            miktarlar = [Decimal(str(m)) for m in s.scalars(
                select(StokHareketi.miktar).where(StokHareketi.stok_id == stok_id).order_by(StokHareketi.id))]
        self.assertIn(Decimal("24"), [abs(m) for m in miktarlar])
        self.assertIn(Decimal("12"), [abs(m) for m in miktarlar])


class TeklifBirimKatsayisiTest(_Taban):
    def _teklif(self, *satirlar):
        from database.teklif_service import QuoteService

        return QuoteService.kaydet(
            {"teklif_tarihi": T1, "gecerlilik_tarihi": BUGUN, "cari_id": self.o.mus_id},
            [{"urun_adi": "Test Ürün", "miktar": Decimal("2"), "birim_satis_fiyati": Decimal("150"),
              "teklif_fiyati": Decimal("150"), "kdv_orani": Decimal("20"), **s} for s in satirlar],
        )

    def test_katsayi_gonderilmezse_karttan_alinir_kartsizda_bir(self):
        from database.teklif_service import QuoteService

        t = self._teklif({"urun_kodu": "U001", "birim": "Koli"}, {"urun_kodu": "OZEL", "birim": "Koli"},
                         {"urun_kodu": "U001", "birim": "Adet"})
        satirlar = sorted(QuoteService.getir(t.id).satirlar, key=lambda s: s.sira_no)
        self.assertEqual([Decimal(str(s.birim_carpani)) for s in satirlar],
                         [Decimal("12"), Decimal("1"), Decimal("1")])
        self.assertEqual([s.birim for s in satirlar], ["Koli", "Koli", "Adet"])

    def test_tanimsiz_birim_taslakta_kalir_onaylanamaz(self):
        from database.stok_service import BirimDonusumHatasi
        from database.teklif_service import QuoteService

        t = self._teklif({"urun_kodu": "U001", "birim": "Palet"})
        self.assertEqual(t.durum, "TASLAK")
        self.assertIn("Palet", t.birim_uyarisi)
        with self.assertRaises(BirimDonusumHatasi):
            QuoteService.durum_degistir(t.id, "MÜŞTERİYE GÖNDERİLDİ")


if __name__ == "__main__":
    unittest.main()
