"""Yerine koyma: A = N−Y, D = Y−C, G = A+D; rapor stok hareketi üretmez."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from database import stok_rapor_service as srv  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.stok import StokFiyati, StokHareketi, StokKarti  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

BAS, BIT = date(2026, 9, 1), date(2026, 9, 30)


class YerineKoymaTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            self.stok_id = int(stok.id)

    def tearDown(self):
        self.o.kapat()

    def test_temel_ornek_n1300_c1000_r12(self):
        """100 adet × 13 satış, FIFO C=10 → G=300; R=12 → Y=1200, A=100, D=200."""
        self.o.alis(100, 10, date(2026, 8, 20), lot="L1")
        self.o.satis(100, 13, date(2026, 9, 15))
        # Alış faturası kart ALIŞ FİYATI'nı 10 yazar; yerine koyma R olarak güncel teklif 12
        with get_session() as s:
            f = s.scalar(
                select(StokFiyati).where(
                    StokFiyati.stok_id == self.stok_id, StokFiyati.fiyat_adi == "ALIŞ FİYATI"
                )
            )
            if f is None:
                s.add(StokFiyati(stok_id=self.stok_id, fiyat_adi="ALIŞ FİYATI", tutar=D("12"), para_birimi="TL"))
            else:
                f.tutar = D("12")
            once = int(s.scalar(select(func.count(StokHareketi.id))) or 0)
        rapor = srv.yatirim_verimliligi(bas=BAS, bit=BIT, bugun=date(2026, 10, 8))
        yk = srv.yerine_koyma_ekle(rapor, fiyat_tarihi=date(2026, 9, 30))
        u = next(x for x in yk["yerine_koyma"] if x["urun_kodu"] == "U001" and not x.get("_sabit"))
        self.assertEqual(u["net_miktar"], D("100"))
        self.assertEqual(u["net_satis"], D("1300.00"))
        self.assertEqual(u["smm"], D("1000.00"))
        self.assertEqual(u["brut_kar"], D("300.00"))
        self.assertEqual(u["yerine_birim"], D("12.00"))
        self.assertEqual(u["yerine_tutar"], D("1200.00"))
        self.assertEqual(u["yerine_katki"], D("100.00"))
        self.assertEqual(u["maliyet_farki"], D("200.00"))
        self.assertEqual(u["brut_marj"], D("23.08"))
        self.assertEqual(u["yerine_marj"], D("7.69"))
        self.assertTrue(u["_yk_tam"])
        with get_session() as s:
            self.assertEqual(int(s.scalar(select(func.count(StokHareketi.id))) or 0), once)


if __name__ == "__main__":
    unittest.main()
