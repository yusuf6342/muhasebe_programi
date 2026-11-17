"""Onaysız satış faturası cari borç yazmaz; onayda bir kez oluşur."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from database.cari_bakiye_service import (
    _evo_onaysiz_satis_faturasi_belgesi_mi,
    net_bakiye,
)
from database.database import get_session
from database.models.cari import SatisHareketi
from database.models.satis_faturasi import SatisFaturasi
from database.satis_faturasi_service import SatisFaturasiService
from tests import test_uzlasma_net_cari as _uz


class OnaysizCariBorcTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)
        self.fatura_no = f"TASLAK-ONAYSIZ-{self.musteri_id}"
        with get_session() as s:
            self.bak_taban = Decimal(str(net_bakiye(self.musteri_id, session=s)["bakiye"]))

    def tearDown(self):
        _uz._sokum(self)

    def _satir(self):
        return {
            "urun_kodu": "U001",
            "urun_adi": "Masa",
            "miktar": Decimal("1"),
            "birim": "Adet",
            "birim_fiyat": Decimal("100"),
            "iskonto_orani": Decimal("0"),
            "iskonto_orani_2": Decimal("0"),
            "iskonto_orani_3": Decimal("0"),
            "kdv_orani": Decimal("20"),
        }

    def _kaydet(self, fatura_id=None):
        return SatisFaturasiService.kaydet(
            {
                "fatura_no": self.fatura_no,
                "fatura_tarihi": date(2026, 9, 10),
                "vade_tarihi": date(2026, 9, 10),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "tahsilat_tutari": 0,
                "sales_person_id": 1,
            },
            [self._satir()],
            fatura_id=fatura_id,
        )

    def _bak(self):
        with get_session() as s:
            return Decimal(str(net_bakiye(self.musteri_id, session=s)["bakiye"]))

    def test_01_kaydet_cari_borc_yazmaz_belge_kalir(self):
        f = self._kaydet()
        self.assertFalse(f.onaylandi)
        with get_session() as s:
            sh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == f.fatura_no))
            self.assertIsNone(sh)
            fat = s.scalar(select(SatisFaturasi).where(SatisFaturasi.fatura_no == self.fatura_no))
            self.assertIsNotNone(fat)
            self.assertFalse(fat.onaylandi)
            self.assertEqual(fat.durum, "AÇIK")
        self.assertEqual(self._bak(), self.bak_taban)

    def test_02_tekrar_kaydet_borc_cogaltmaz(self):
        f = self._kaydet()
        self._kaydet(fatura_id=f.id)
        with get_session() as s:
            adet = len(
                list(
                    s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == self.fatura_no))
                )
            )
            self.assertEqual(adet, 0)
        self.assertEqual(self._bak(), self.bak_taban)

    def test_03_onayla_bir_kez_borc_yazar(self):
        f = self._kaydet()
        SatisFaturasiService.onayla(f.id, eksi_izin=True)
        tutar = Decimal("0")
        with get_session() as s:
            shs = list(
                s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == self.fatura_no))
            )
            self.assertEqual(len(shs), 1)
            tutar = Decimal(str(shs[0].satis_tutari))
            self.assertGreater(tutar, Decimal("0"))
            fat = s.get(SatisFaturasi, f.id)
            self.assertTrue(fat.onaylandi)
        self.assertEqual(self._bak(), self.bak_taban + tutar)
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(f.id, eksi_izin=True)
        with get_session() as s:
            adet = len(
                list(
                    s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == self.fatura_no))
                )
            )
            self.assertEqual(adet, 1)

    def test_04_onay_kaldir_borcu_siler_belgeyi_korur(self):
        f = self._kaydet()
        SatisFaturasiService.onayla(f.id, eksi_izin=True)
        SatisFaturasiService.onay_kaldir(f.id)
        with get_session() as s:
            fat = s.get(SatisFaturasi, f.id)
            self.assertIsNotNone(fat)
            self.assertFalse(fat.onaylandi)
            self.assertEqual(fat.durum, "AÇIK")
            self.assertIsNone(
                s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == self.fatura_no))
            )
        self.assertEqual(self._bak(), self.bak_taban)

    def test_05_filtre_satis_faturasi_ile_satis_fisi_ayrilir(self):
        self.assertTrue(_evo_onaysiz_satis_faturasi_belgesi_mi("SAF04895"))
        self.assertTrue(_evo_onaysiz_satis_faturasi_belgesi_mi("EVB-SF-12411"))
        self.assertFalse(_evo_onaysiz_satis_faturasi_belgesi_mi("SFŞ0785"))
        self.assertFalse(_evo_onaysiz_satis_faturasi_belgesi_mi("SFS0785"))
        self.assertFalse(_evo_onaysiz_satis_faturasi_belgesi_mi("RAY-00022"))
        self.assertFalse(_evo_onaysiz_satis_faturasi_belgesi_mi("MCC-12440"))


if __name__ == "__main__":
    unittest.main()
