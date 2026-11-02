"""Konsinye verilen/alınan: sahiplik, FIFO maliyet, hareket net, gerçek fatura bağlantısı."""

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
    miktar_goster,
)
from database.models.cari import Cari  # noqa: E402
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402


def _depo_miktar(stok_id: int, depo_ad: str | None = None, *, sadece_firma: bool = False) -> Decimal:
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
        if sadece_firma:
            q = q.where(StokLotu.sahip_turu == "BIZE")
        return Decimal(str(s.scalar(q) or 0))


def _firma_deger(stok_id: int) -> Decimal:
    with get_session() as s:
        lotlar = list(
            s.scalars(
                select(StokLotu).where(
                    StokLotu.stok_id == stok_id,
                    StokLotu.sahip_turu == "BIZE",
                    StokLotu.kalan_miktar > 0,
                )
            ).all()
        )
        return sum(
            (Decimal(str(l.kalan_miktar)) * Decimal(str(l.birim_maliyet or 0)) for l in lotlar),
            Decimal("0"),
        )


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


class MiktarGosterTest(unittest.TestCase):
    def test_tam_sayi_sifir_silinmez(self):
        for v, bek in (
            (0, "0"),
            (10, "10"),
            (30, "30"),
            (50, "50"),
            (100, "100"),
            (1000, "1000"),
            ("10.0000", "10"),
            ("15.50", "15.5"),
            ("1234.50", "1234.5"),
        ):
            self.assertEqual(miktar_goster(v), bek, v)


class VerilenKonsinyeKabulTest(unittest.TestCase):
    """Talimat: 200→100 teslim; maliyet 2000; 35 bildirim + 15 iade → magaza 115 + müşteri 50."""

    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        KonsinyeService._schema_hazir = False
        KonsinyeService._schema_hazir_engine_id = None
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
                    sahip_turu="BIZE",
                )
            )
            s.flush()
            self.stok_id = int(stok.id)
            self.depo_id = int(depo.id)
            self.mus_id = int(self.o.mus_id)

    def tearDown(self):
        self.o.kapat()

    def test_teslim_bildirim_iade_maliyet_fifo(self):
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
        # Toplam bize ait 200, maliyet 2000 — satış fiyatı maliyeti şişirmesin
        ozet = KonsinyeService.stok_sahiplik_ozeti(self.stok_id)
        self.assertEqual(ozet["bize_ait"], Decimal("200"))
        self.assertEqual(ozet["bize_ait_deger"], Decimal("2000"))
        self.assertEqual(
            Decimal(str(teslim["satirlar"][0]["fifo_birim_maliyet"])), Decimal("10")
        )
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
        self.assertEqual(_firma_deger(self.stok_id), Decimal("1650"))

        # Hayali fatura bağlama reddedilir
        with self.assertRaises(ValueError):
            KonsinyeService.fatura_bagla(teslim_satiri_id=satir_id, miktar=20, belge_no="SF-1")

        with self.assertRaises(ValueError):
            KonsinyeService.iade_al(teslim_satiri_id=satir_id, miktar=51)


class AlinanKonsinyeTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        KonsinyeService._schema_hazir = False
        KonsinyeService._schema_hazir_engine_id = None
        KonsinyeService.ensure_schema()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            self.stok_id = int(stok.id)
            self.depo_id = int(depo.id)
            self.ted_id = int(self.o.ted_id)

    def tearDown(self):
        self.o.kapat()

    def test_giris_kesin_al_iade_hareket_net(self):
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("0"))
        teslim = KonsinyeService.teslim_kaydet(
            yon=YON_ALINAN,
            cari_id=self.ted_id,
            depo_id=self.depo_id,
            belge_tarihi=date.today(),
            satirlar=[{"stok_kodu": "U001", "miktar": 100, "birim": "Adet", "birim_fiyat": 50}],
            onayla=True,
        )
        # Fiziksel 100; bize ait 0; borç yok
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("100"))
        ozet = KonsinyeService.stok_sahiplik_ozeti(self.stok_id)
        self.assertEqual(ozet["fiziksel"], Decimal("100"))
        self.assertEqual(ozet["bize_ait"], Decimal("0"))
        self.assertEqual(ozet["tedarikciye_ait"], Decimal("100"))
        self.assertEqual(ozet["bize_ait_deger"], Decimal("0"))
        self.assertTrue(_cari_hareket_yok(self.ted_id))
        self.assertEqual(KonsinyeService.hareket_net_miktar(self.stok_id), Decimal("100"))

        sid = teslim["satirlar"][0]["id"]
        KonsinyeService.kesin_al(teslim_satiri_id=sid, miktar=30, birim_maliyet=50)
        g = KonsinyeService.getir(teslim["id"])
        self.assertEqual(g["satirlar"][0]["kalan_miktar"], Decimal("70"))
        self.assertEqual(g["satirlar"][0]["bildirilen_miktar"], Decimal("30"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("100"))
        ozet = KonsinyeService.stok_sahiplik_ozeti(self.stok_id)
        self.assertEqual(ozet["bize_ait"], Decimal("30"))
        self.assertEqual(ozet["tedarikciye_ait"], Decimal("70"))
        self.assertEqual(ozet["bize_ait_deger"], Decimal("1500"))
        # Hareket esaslı rapor 130 göstermesin
        self.assertEqual(KonsinyeService.hareket_net_miktar(self.stok_id), Decimal("100"))

        KonsinyeService.iade_al(teslim_satiri_id=sid, miktar=20)
        g = KonsinyeService.getir(teslim["id"])
        self.assertEqual(g["satirlar"][0]["kalan_miktar"], Decimal("50"))
        self.assertEqual(_depo_miktar(self.stok_id, "ANA DEPO"), Decimal("80"))
        ozet = KonsinyeService.stok_sahiplik_ozeti(self.stok_id)
        self.assertEqual(ozet["bize_ait"], Decimal("30"))
        self.assertEqual(ozet["tedarikciye_ait"], Decimal("50"))
        self.assertEqual(KonsinyeService.hareket_net_miktar(self.stok_id), Decimal("80"))


class KonsinyeRaporTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        KonsinyeService._schema_hazir = False
        KonsinyeService._schema_hazir_engine_id = None
        KonsinyeService.ensure_schema()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_no="R1",
                    giris_tarihi=date.today(),
                    kalan_miktar=Decimal("50"),
                    birim_maliyet=Decimal("10"),
                    sahip_turu="BIZE",
                )
            )
            self.depo_id = int(depo.id)
            self.mus_id = int(self.o.mus_id)

    def tearDown(self):
        self.o.kapat()

    def test_raporlar_tum_kayit(self):
        from database.konsinye_rapor_service import KonsinyeRaporService

        KonsinyeService.teslim_kaydet(
            yon=YON_VERILEN,
            cari_id=self.mus_id,
            depo_id=self.depo_id,
            belge_tarihi=date.today(),
            satirlar=[{"stok_kodu": "U001", "miktar": 10, "birim": "Adet", "birim_fiyat": 50}],
            onayla=True,
        )
        a = KonsinyeRaporService.musterideki_mallar()
        self.assertGreaterEqual(a["adet"], 1)
        d = KonsinyeRaporService.fatura_bekleyen(yon=YON_VERILEN)
        self.assertIsInstance(d["satirlar"], list)
        f = KonsinyeRaporService.hareket_gecmisi()
        self.assertIsInstance(f["satirlar"], list)


if __name__ == "__main__":
    unittest.main()
