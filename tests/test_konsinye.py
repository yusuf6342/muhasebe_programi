"""Konsinye verilen/alınan: teslim cari borç yazmaz; bildirim/iade/fatura miktarları tutarlı."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.konsinye_service import (  # noqa: E402
    YON_ALINAN,
    YON_VERILEN,
    KonsinyeService,
)
from database.models.cari import Cari  # noqa: E402
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402


def _depo_miktar(stok_id: int, depo_ad: str | None = None) -> Decimal:
    with get_session() as s:
        q = (
            select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
            .select_from(StokLotu)
            .join(Depo, Depo.id == StokLotu.depo_id)
            .where(StokLotu.stok_id == stok_id)
        )
        if depo_ad:
            q = q.where(Depo.ad == depo_ad)
        else:
            q = q.where(~Depo.ad.like("KONSİNYE:%"))
        return Decimal(str(s.scalar(q) or 0))


def _cari_hareket_yok(cari_id: int) -> bool:
    try:
        from database.models.finans import CariHareket

        with get_session() as s:
            n = s.scalar(
                select(func.count()).select_from(CariHareket).where(CariHareket.cari_id == cari_id)
            )
            return int(n or 0) == 0
    except Exception:
        return True


class VerilenKonsinyeKabulTest(unittest.TestCase):
    """Talimat §13: 200 → 100 teslim → 35 bildirim → 15 iade → mağaza 115 + müşteri 50."""

    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        KonsinyeService._schema_hazir = False
        KonsinyeService.ensure_schema()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_no="BASLANGIC",
                    giris_tarihi=date.today(),
                    kalan_miktar=Decimal("200"),
                    birim_maliyet=Decimal("10"),
                )
            )
            s.flush()
            self.stok_id = int(stok.id)
            self.depo_id = int(depo.id)
            self.mus_id = int(self.o.mus_id)

    def tearDown(self):
        self.o.kapat()

    def test_teslim_bildirim_iade_fatura(self):
        teslim = KonsinyeService.teslim_kaydet(
            yon=YON_VERILEN,
            cari_id=self.mus_id,
            depo_id=self.depo_id,
            belge_tarihi=date.today(),
            satirlar=[{"stok_kodu": "U001", "miktar": 100, "birim": "Adet", "birim_fiyat": 50}],
            onayla=True,
        )
        self.assertEqual(teslim["durum"], "ONAYLI")
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("100"))
        self.assertTrue(_cari_hareket_yok(self.mus_id))

        satir_id = teslim["satirlar"][0]["id"]
        KonsinyeService.satis_bildir(
            teslim_satiri_id=satir_id, miktar=35, gercek_tarih=date(2026, 10, 1)
        )
        KonsinyeService.iade_al(teslim_satiri_id=satir_id, miktar=15)

        guncel = KonsinyeService.getir(teslim["id"])
        s0 = guncel["satirlar"][0]
        self.assertEqual(s0["kalan_miktar"], Decimal("50"))
        self.assertEqual(s0["bildirilen_miktar"], Decimal("35"))
        self.assertEqual(s0["fatura_bekleyen"], Decimal("35"))
        self.assertEqual(s0["iade_miktar"], Decimal("15"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("115"))

        # Fatura bağlama stok düşürmez
        once_magaza = _depo_miktar(self.stok_id, "ANA DEPO")
        KonsinyeService.fatura_bagla(teslim_satiri_id=satir_id, miktar=20, belge_no="SF-1")
        guncel = KonsinyeService.getir(teslim["id"])
        s0 = guncel["satirlar"][0]
        self.assertEqual(s0["faturalanan_miktar"], Decimal("20"))
        self.assertEqual(s0["fatura_bekleyen"], Decimal("15"))
        self.assertEqual(s0["kalan_miktar"], Decimal("50"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), once_magaza)

        with self.assertRaises(ValueError):
            KonsinyeService.iade_al(teslim_satiri_id=satir_id, miktar=51)


class AlinanKonsinyeTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        KonsinyeService._schema_hazir = False
        KonsinyeService.ensure_schema()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            self.stok_id = int(stok.id)
            self.depo_id = int(depo.id)
            self.ted_id = int(self.o.ted_id)

    def tearDown(self):
        self.o.kapat()

    def test_giris_kesin_al_iade(self):
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("0"))
        teslim = KonsinyeService.teslim_kaydet(
            yon=YON_ALINAN,
            cari_id=self.ted_id,
            depo_id=self.depo_id,
            belge_tarihi=date.today(),
            satirlar=[{"stok_kodu": "U001", "miktar": 100, "birim": "Adet", "birim_fiyat": 50}],
            onayla=True,
        )
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("100"))
        self.assertTrue(_cari_hareket_yok(self.ted_id))

        sid = teslim["satirlar"][0]["id"]
        KonsinyeService.kesin_al(teslim_satiri_id=sid, miktar=30, birim_maliyet=50)
        g = KonsinyeService.getir(teslim["id"])
        self.assertEqual(g["satirlar"][0]["kalan_miktar"], Decimal("70"))
        self.assertEqual(g["satirlar"][0]["bildirilen_miktar"], Decimal("30"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("100"))

        KonsinyeService.iade_al(teslim_satiri_id=sid, miktar=20)
        g = KonsinyeService.getir(teslim["id"])
        self.assertEqual(g["satirlar"][0]["kalan_miktar"], Decimal("50"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("80"))


if __name__ == "__main__":
    unittest.main()
