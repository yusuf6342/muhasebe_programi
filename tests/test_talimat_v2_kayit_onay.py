"""Talimat V2: kaydet=cari/finans, onayla=stok, onay_kaldir=stok geri."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.database import get_session
from database.models.cari import SatisHareketi
from database.models.finans import FinansHareketi, FinansHesabi
from database.models.stok import StokHareketi
from database.satis_faturasi_service import SatisFaturasiService
from tests.test_fatura_miktar_birim import FaturaStokEntegrasyonTest

D = Decimal


def _satir(miktar="1", fiyat="833.33"):
    return {
        "urun_kodu": "MB001",
        "urun_adi": "Birim Ürün",
        "miktar": D(miktar),
        "birim": "Adet",
        "birim_fiyat": D(fiyat),
        "iskonto_orani": D("0"),
        "kdv_orani": D("20"),
    }


class TalimatV2KayitOnayTest(FaturaStokEntegrasyonTest):
    def _say(self, fatura_no):
        with get_session() as s:
            stok = s.scalar(
                select(func.count()).select_from(StokHareketi).where(StokHareketi.belge_no == fatura_no)
            ) or 0
            cari = s.scalar(
                select(func.count()).select_from(SatisHareketi).where(SatisHareketi.belge_no == fatura_no)
            ) or 0
            fin = s.scalar(
                select(func.count())
                .select_from(FinansHareketi)
                .where(
                    FinansHareketi.belge_no == fatura_no,
                    FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
                )
            ) or 0
            return int(stok), int(cari), int(fin)

    def _hesap(self):
        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == "TEST KASA"))
            if h is None:
                h = FinansHesabi(hesap_adi="TEST KASA", hesap_turu="KASA", aktif=True)
                s.add(h)
                s.flush()
            return h.hesap_adi, "NAKİT / KASA"

    def test_1_tahsilatsiz_kaydet_cari_var_stok_yok(self):
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 1),
                "vade_tarihi": date(2026, 3, 1),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "sales_person_id": 1,
            },
            [_satir()],
            tahsilat_verileri=[],
        )
        self.assertFalse(f.onaylandi)
        stok, cari, fin = self._say(f.fatura_no)
        self.assertEqual(stok, 0)
        self.assertEqual(cari, 1)
        self.assertEqual(fin, 0)
        with get_session() as s:
            sh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == f.fatura_no))
            self.assertGreater(sh.satis_tutari, 0)
            self.assertEqual(sh.kalan_acik_tutar, sh.satis_tutari)

    def test_2_400_tahsilat_kaydet(self):
        hesap, sekil = self._hesap()
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 1),
                "vade_tarihi": date(2026, 3, 1),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "sales_person_id": 1,
            },
            [_satir("1", "833.33")],
            tahsilat_verileri=[
                {
                    "tahsilat_tarihi": date(2026, 3, 1),
                    "tutar": D("400"),
                    "odeme_sekli": sekil,
                    "hesap": hesap,
                }
            ],
        )
        stok, cari, fin = self._say(f.fatura_no)
        self.assertEqual(stok, 0)
        self.assertEqual(cari, 1)
        self.assertGreaterEqual(fin, 1)
        with get_session() as s:
            sh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == f.fatura_no))
            self.assertEqual(sh.kalan_acik_tutar, sh.satis_tutari - D("400"))

    def test_3_5_tekrar_kaydet_onay_tekrar(self):
        hesap, sekil = self._hesap()
        tah = [
            {
                "tahsilat_tarihi": date(2026, 3, 1),
                "tutar": D("400"),
                "odeme_sekli": sekil,
                "hesap": hesap,
            }
        ]
        temel = {
            "fatura_tarihi": date(2026, 3, 1),
            "vade_tarihi": date(2026, 3, 1),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
            "sales_person_id": 1,
        }
        f = SatisFaturasiService.kaydet(temel, [_satir()], tahsilat_verileri=tah)
        fid = f.id
        fno = f.fatura_no
        st0, ca0, fi0 = self._say(fno)
        f2 = SatisFaturasiService.kaydet(
            {**temel, "row_version": f.row_version},
            [_satir()],
            fatura_id=fid,
            tahsilat_verileri=tah,
        )
        self.assertEqual(f2.id, fid)
        st1, ca1, fi1 = self._say(fno)
        self.assertEqual(ca1, 1)
        self.assertEqual(ca1, ca0)
        self.assertEqual(st1, 0)

        f3 = SatisFaturasiService.onayla(fid)
        self.assertTrue(f3.onaylandi)
        st2, ca2, fi2 = self._say(fno)
        self.assertGreater(st2, 0)
        self.assertEqual(ca2, 1)
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(fid)
        st3, ca3, fi3 = self._say(fno)
        self.assertEqual((st3, ca3, fi3), (st2, ca2, fi2))

        # +100 tahsilat onaylı
        tah2 = tah + [
            {
                "tahsilat_tarihi": date(2026, 3, 1),
                "tutar": D("100"),
                "odeme_sekli": sekil,
                "hesap": hesap,
            }
        ]
        f4 = SatisFaturasiService.tahsilatlari_guncelle(fid, tah2)
        self.assertTrue(f4.onaylandi)
        st4, ca4, _ = self._say(fno)
        self.assertEqual(st4, st2)
        self.assertEqual(ca4, 1)
        with get_session() as s:
            sh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fno))
            self.assertEqual(sh.kalan_acik_tutar, sh.satis_tutari - D("500"))

        # onay kaldır: stok 0, cari kalır
        f5 = SatisFaturasiService.onay_kaldir(fid)
        self.assertFalse(f5.onaylandi)
        st5, ca5, fi5 = self._say(fno)
        self.assertEqual(st5, 0)
        self.assertEqual(ca5, 1)
        self.assertGreaterEqual(fi5, 1)


if __name__ == "__main__":
    unittest.main()
