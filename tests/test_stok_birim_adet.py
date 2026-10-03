"""Birim adı normalizasyonu (ADET = Adet = adet, TAKIM = Takım) ve Adet katsayısıyla satış.

Geçmiş belge satırları değişmez; yalnız karta eklenen alternatif birim yeni işlemlerde kullanılır.
Çalıştırma: python -m pytest tests/test_stok_birim_adet.py
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select  # noqa: E402

import test_stok_birlestir as _ortam  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.stok import StokFiyati, StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.stok_service import BirimDonusumHatasi, StokService, birim_anahtari  # noqa: E402


def _kart(birim, *birimler):
    return SimpleNamespace(stok_kodu="X", stok_adi="X", birim=birim,
                           birimler=[SimpleNamespace(birim_adi=a, carpan=Decimal(c), aktif=True)
                                     for a, c in birimler])


class BirimAnahtariTest(unittest.TestCase):
    def test_varyantlar_esit(self):
        for a, b in (("ADET", "Adet"), ("adet", " Adet "), ("TAKIM", "Takım"), ("KİLOGRAM", "Kilogram"),
                     ("UNIT", "Unit"), ("KOLİ", "koli")):
            self.assertEqual(birim_anahtari(a), birim_anahtari(b), (a, b))
        self.assertNotEqual(birim_anahtari("Ad"), birim_anahtari("Adet"))

    def test_kesin_carpan_varyantla(self):
        self.assertEqual(StokService.birim_carpani_kesin(_kart("Adet"), "ADET"), Decimal("1"))
        self.assertEqual(StokService.birim_carpani_kesin(_kart("Takım"), "TAKIM"), Decimal("1"))
        self.assertEqual(StokService.birim_carpani_kesin(_kart("Paket", ("Adet", "0.2")), "ADET"), Decimal("0.2"))
        self.assertEqual(StokService.birim_carpani(_kart("Paket", ("Adet", "0.2")), "adet"), Decimal("0.2"))
        with self.assertRaises(BirimDonusumHatasi):
            StokService.birim_carpani_kesin(_kart("Paket"), "Adet")


class AdetKatsayisiSatisTest(unittest.TestCase):
    setUp = _ortam.StokBirlestirTest.setUp
    tearDown = _ortam.StokBirlestirTest.tearDown

    def test_yeni_adet_katsayisiyla_satis(self):
        with get_session() as s:
            kart = StokKarti(stok_kodu="P5", stok_adi="DEKUPAJ AĞZI 5 Lİ PAKET", birim="Paket",
                             aktif=True, is_deleted=False)
            s.add(kart)
            s.flush()
            s.add(StokFiyati(stok_id=kart.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("150")))
            s.add(StokLotu(stok_id=kart.id, depo_id=self.depo1_id, lot_no="P-L1", giris_tarihi=date(2026, 1, 5),
                           kalan_miktar=Decimal("10"), birim_maliyet=Decimal("100")))
            s.add(StokHareketi(stok_id=kart.id, depo_id=self.depo1_id, miktar=Decimal("10"),
                               birim_maliyet=Decimal("100"), hareket_turu="GİRİŞ", belge_no="P-G1",
                               tarih=date(2026, 1, 5)))
            kart_id = kart.id

        # Tanımsızken yeni belgede engellenir
        with get_session() as s:
            hata = StokService.belge_birim_sorunu(s, [{"urun_kodu": "P5", "birim": "ADET"}], "Satış faturası")
        self.assertIsNotNone(hata)

        StokService.stok_birimleri_kaydet(kart_id, [{"birim_adi": "Adet", "carpan": "0.2",
                                                     "referans_birim": "Paket", "referans_carpan": "0.2",
                                                     "fiyat_modu": "otomatik"}])
        with get_session() as s:
            self.assertIsNone(StokService.belge_birim_sorunu(s, [{"urun_kodu": "P5", "birim": "ADET"}], "Satış"))
            kart = StokService._stok_yukle(s, stok_id=kart_id)
            temel = StokService.temel_miktara_cevir(Decimal("5"), "adet", kart)
            self.assertEqual(temel, Decimal("1"))
            self.assertEqual(StokService.birim_fiyati_getir(kart, "Adet"), Decimal("30"))
            r = StokService.fatura_cikisi(s, "SAT-ADET-1", date(2026, 2, 1), "P5", "Merkez", temel)
        self.assertEqual(r["fifo_birim_maliyeti"], Decimal("100"))
        with get_session() as s:
            lot = s.scalar(select(StokLotu).where(StokLotu.lot_no == "P-L1"))
            self.assertEqual(lot.kalan_miktar, Decimal("9"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
