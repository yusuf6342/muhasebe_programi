"""Tercih lot yetersizken diğer lotlardan FIFO ile fatura çıkışı."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select  # noqa: E402

import test_stok_birlestir as _ortam  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.stok import StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.stok_service import StokService  # noqa: E402


class FaturaOnayLotFallbackTest(unittest.TestCase):
    tearDown = _ortam.StokBirlestirTest.tearDown

    def setUp(self):
        import database.models.kart_turu  # noqa: F401 — stok FK

        _ortam.StokBirlestirTest.setUp(self)

    def test_tercih_lot_yetersiz_diger_lotlardan_tamamlanir(self):
        with get_session() as s:
            kart = StokKarti(
                stok_kodu="LOT-FB-1",
                stok_adi="Test Lot Fallback",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            s.add(kart)
            s.flush()
            s.add_all(
                [
                    StokLotu(
                        stok_id=kart.id,
                        depo_id=self.depo1_id,
                        lot_no="ESKI-AZ",
                        giris_tarihi=date(2026, 10, 1),
                        kalan_miktar=Decimal("34"),
                        birim_maliyet=Decimal("10"),
                    ),
                    StokLotu(
                        stok_id=kart.id,
                        depo_id=self.depo1_id,
                        lot_no="YENI-COK",
                        giris_tarihi=date(2026, 11, 11),
                        kalan_miktar=Decimal("300"),
                        birim_maliyet=Decimal("12"),
                    ),
                ]
            )

        with get_session() as s:
            r = StokService.fatura_cikisi(
                s,
                "RAY-TEST-LOT",
                date(2026, 11, 11),
                "LOT-FB-1",
                "Merkez",
                Decimal("240"),
                "ESKI-AZ",
            )
            self.assertIn("ESKI-AZ:34", r["lot_cikisi"])
            self.assertIn("YENI-COK:206", r["lot_cikisi"])
            s.flush()
            hrk = list(
                s.scalars(
                    select(StokHareketi).where(StokHareketi.belge_no == "RAY-TEST-LOT")
                ).all()
            )
            self.assertEqual(len(hrk), 2)
            self.assertEqual(sum((h.miktar for h in hrk), Decimal("0")), Decimal("240"))

    def test_toplam_yetersiz_net_mesaj(self):
        with get_session() as s:
            kart = StokKarti(
                stok_kodu="LOT-FB-2",
                stok_adi="Az Stok",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            s.add(kart)
            s.flush()
            s.add(
                StokLotu(
                    stok_id=kart.id,
                    depo_id=self.depo1_id,
                    lot_no="L1",
                    giris_tarihi=date(2026, 10, 1),
                    kalan_miktar=Decimal("5"),
                    birim_maliyet=Decimal("1"),
                )
            )

        with get_session() as s:
            with self.assertRaises(ValueError) as ctx:
                StokService.fatura_cikisi(
                    s,
                    "RAY-TEST-AZ",
                    date(2026, 11, 11),
                    "LOT-FB-2",
                    "Merkez",
                    Decimal("10"),
                    "L1",
                )
            msg = str(ctx.exception)
            self.assertIn("Az Stok", msg)
            self.assertIn("LOT-FB-2", msg)
            self.assertIn("Mevcut: 5", msg)
            self.assertIn("Gereken: 10", msg)
            self.assertIn("Eksik: 5", msg)


if __name__ == "__main__":
    unittest.main()
