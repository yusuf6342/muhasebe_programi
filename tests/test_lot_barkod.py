"""Lot barkod üretimi, çözümleme ve etiket işi (stok miktarı değişmez)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.lot_barkod_service import LotBarkodService  # noqa: E402
from database.models.stok import Depo, StokKarti, StokLotu  # noqa: E402
from database.stok_service import StokService  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402


class LotBarkodTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])
        LotBarkodService._schema_hazir = False
        LotBarkodService.ensure_schema()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            lot = StokLotu(
                stok_id=stok.id,
                depo_id=depo.id,
                lot_no="TEST-LOT-001",
                giris_tarihi=date.today(),
                kalan_miktar=Decimal("100"),
                birim_maliyet=Decimal("1"),
            )
            s.add(lot)
            s.flush()
            self.stok_id = int(stok.id)
            self.lot_id = int(lot.id)

    def tearDown(self):
        self.o.kapat()

    def test_ayni_kombinasyon_tek_barkod(self):
        with get_session() as s:
            a = LotBarkodService.lot_barkodu_al_veya_olustur(
                s, stok_id=self.stok_id, lot_id=self.lot_id, birim="Adet"
            )
            b = LotBarkodService.lot_barkodu_al_veya_olustur(
                s, stok_id=self.stok_id, lot_id=self.lot_id, birim="Adet"
            )
            self.assertEqual(a.barkod, b.barkod)
            self.assertTrue(a.barkod.startswith("L"))
            self.assertEqual(len(a.barkod), 9)

    def test_coz_ve_barkod_ile_bul(self):
        with get_session() as s:
            kayit = LotBarkodService.lot_barkodu_al_veya_olustur(
                s, stok_id=self.stok_id, lot_id=self.lot_id, birim="Adet"
            )
            kod = kayit.barkod
        ozet = LotBarkodService.coz(kod)
        self.assertEqual(ozet["durum"], "ok")
        self.assertEqual(ozet["lot_id"], self.lot_id)
        bulunan = StokService.barkod_ile_bul(kod)
        self.assertIsNotNone(bulunan)
        self.assertTrue(bulunan.get("lot_barkod"))
        self.assertEqual(bulunan["lot_id"], self.lot_id)

    def test_sepet_farkli_lot_ayri_satir(self):
        from hizli_satis_sepet import HizliSatisSepet

        sepet = HizliSatisSepet()
        sepet.ekle(
            stok_id=self.stok_id,
            stok_kodu="U001",
            stok_adi="Test",
            birim="Adet",
            miktar=1,
            birim_fiyat=10,
            lot_id=self.lot_id,
            lot_no="TEST-LOT-001",
        )
        # Aynı lot → birleşir
        sepet.ekle(
            stok_id=self.stok_id,
            stok_kodu="U001",
            stok_adi="Test",
            birim="Adet",
            miktar=2,
            birim_fiyat=10,
            lot_id=self.lot_id,
            lot_no="TEST-LOT-001",
        )
        self.assertEqual(len(sepet.satirlar), 1)
        self.assertEqual(sepet.satirlar[0].miktar, Decimal("3"))
        # Farklı lot → ayrı satır
        sepet.ekle(
            stok_id=self.stok_id,
            stok_kodu="U001",
            stok_adi="Test",
            birim="Adet",
            miktar=1,
            birim_fiyat=10,
            lot_id=999999,
            lot_no="DIGER-LOT",
        )
        self.assertEqual(len(sepet.satirlar), 2)

    def test_etiket_isi_mukerrer_yok_ve_basim_stok_degistirmez(self):
        with get_session() as s:
            kalan0 = s.get(StokLotu, self.lot_id).kalan_miktar
        is1 = LotBarkodService.giristen_etiket_isi_olustur(
            kaynak_tur="ALIS_FATURA",
            kaynak_belge_no="AF-TEST-1",
            kaynak_belge_id=1,
            lotlar=[{"lot_id": self.lot_id, "stok_id": self.stok_id, "miktar": 10, "birim": "Adet"}],
        )
        self.assertIsNotNone(is1)
        is2 = LotBarkodService.giristen_etiket_isi_olustur(
            kaynak_tur="ALIS_FATURA",
            kaynak_belge_no="AF-TEST-1",
            kaynak_belge_id=1,
            lotlar=[{"lot_id": self.lot_id, "stok_id": self.stok_id, "miktar": 10}],
        )
        self.assertEqual(is1["id"], is2["id"])
        from database.models.stok import StokFiyati

        with get_session() as s:
            s.add(
                StokFiyati(
                    stok_id=self.stok_id,
                    fiyat_adi="SATIŞ FİYATI 1",
                    tutar=Decimal("12.50"),
                    para_birimi="TL",
                )
            )
        LotBarkodService.basim_kaydet(is1["id"])
        with get_session() as s:
            kalan1 = s.get(StokLotu, self.lot_id).kalan_miktar
        self.assertEqual(kalan0, kalan1)


if __name__ == "__main__":
    unittest.main()
