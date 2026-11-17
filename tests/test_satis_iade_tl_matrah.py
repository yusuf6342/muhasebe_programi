"""Satış iade: tl_matrah/tl_kdv/tl_genel_toplam INSERT'e yazılmalı (KDV %0 → matrah tutar)."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import get_session
from database.models.satis_iade_faturasi import SatisIadeFaturasi
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from sqlalchemy import select
from tests import test_uzlasma_net_cari as _uz

D = Decimal


class SatisIadeTlMatrahTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)

    def tearDown(self):
        _uz._sokum(self)

    def _kaynak(self, *, fiyat=D("250"), kdv=D("0")):
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 6, 1),
                "vade_tarihi": date(2026, 6, 1),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Masa",
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": fiyat,
                    "iskonto_orani": D("0"),
                    "kdv_orani": kdv,
                }
            ],
        )
        SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def test_kdv_sifir_matrah_yazilir(self):
        kaynak = self._kaynak(fiyat=D("250"), kdv=D("0"))
        ks = kaynak.satirlar[0]
        iade = SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": date(2026, 6, 2),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "kaynak_fatura_id": kaynak.id,
                "iade_odeme_tutari": D("0"),
            },
            [
                {
                    "urun_kodu": ks.urun_kodu,
                    "urun_adi": ks.urun_adi,
                    "miktar": D("1"),
                    "birim": ks.birim or "Adet",
                    "birim_fiyat": D("250"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("0"),
                    "kaynak_fatura_satiri_id": ks.id,
                    "onceki_fatura_no": kaynak.fatura_no,
                }
            ],
        )
        self.assertEqual(D(iade.tl_matrah), D("250.00"))
        self.assertEqual(D(iade.tl_kdv), D("0.00"))
        self.assertEqual(D(iade.tl_genel_toplam), D("250.00"))
        with get_session() as s:
            row = s.scalar(select(SatisIadeFaturasi).where(SatisIadeFaturasi.id == iade.id))
            self.assertEqual(D(row.tl_matrah), D("250.00"))
            self.assertEqual(D(row.tl_kdv), D("0.00"))
            self.assertEqual(D(row.tl_genel_toplam), D("250.00"))

    def test_kdv_yuzde_yirmi_matrah_ve_kdv(self):
        kaynak = self._kaynak(fiyat=D("100"), kdv=D("20"))
        ks = kaynak.satirlar[0]
        iade = SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": date(2026, 6, 3),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "kaynak_fatura_id": kaynak.id,
                "iade_odeme_tutari": D("0"),
            },
            [
                {
                    "urun_kodu": ks.urun_kodu,
                    "urun_adi": ks.urun_adi,
                    "miktar": D("1"),
                    "birim": ks.birim or "Adet",
                    "birim_fiyat": D("100"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "kaynak_fatura_satiri_id": ks.id,
                    "onceki_fatura_no": kaynak.fatura_no,
                }
            ],
        )
        self.assertEqual(D(iade.tl_matrah), D("100.00"))
        self.assertEqual(D(iade.tl_kdv), D("20.00"))
        self.assertEqual(D(iade.tl_genel_toplam), D("120.00"))

    def test_guncellemede_toplamlar_yenilenir(self):
        kaynak = self._kaynak(fiyat=D("250"), kdv=D("0"))
        ks = kaynak.satirlar[0]
        iade = SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": date(2026, 6, 4),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "kaynak_fatura_id": kaynak.id,
                "iade_odeme_tutari": D("0"),
            },
            [
                {
                    "urun_kodu": ks.urun_kodu,
                    "urun_adi": ks.urun_adi,
                    "miktar": D("1"),
                    "birim": ks.birim or "Adet",
                    "birim_fiyat": D("250"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("0"),
                    "kaynak_fatura_satiri_id": ks.id,
                    "onceki_fatura_no": kaynak.fatura_no,
                }
            ],
        )
        iade2 = SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": date(2026, 6, 4),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "kaynak_fatura_id": kaynak.id,
                "iade_odeme_tutari": D("0"),
            },
            [
                {
                    "urun_kodu": ks.urun_kodu,
                    "urun_adi": ks.urun_adi,
                    "miktar": D("1"),
                    "birim": ks.birim or "Adet",
                    "birim_fiyat": D("250"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("0"),
                    "kaynak_fatura_satiri_id": ks.id,
                    "onceki_fatura_no": kaynak.fatura_no,
                }
            ],
            iade_id=iade.id,
        )
        self.assertEqual(iade2.id, iade.id)
        self.assertEqual(D(iade2.tl_matrah), D("250.00"))
        self.assertEqual(D(iade2.tl_genel_toplam), D("250.00"))


if __name__ == "__main__":
    unittest.main()
