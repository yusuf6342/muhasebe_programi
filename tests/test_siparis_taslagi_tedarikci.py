"""Stok uyarı sipariş taslağı: fiziksel stok filtresi + sistem cari tedarikçi engeli."""

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
from database.models.cari import Cari  # noqa: E402
from database.models.stok import Depo, StokKarti  # noqa: E402
from database.models.stok_uyari import StokIhtiyac  # noqa: E402
from database.stok_uyari_service import (  # noqa: E402
    SINIFLANDIRMA_SURUMU,
    StokUyariService,
    _fiziksel_stok_karti,
    _sistem_tedarikci_mi,
)
from tests.stok_test_ortami import StokOrtami  # noqa: E402


class SiparisTaslagiTedarikciTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])

    def tearDown(self):
        self.o.kapat()

    def test_siniflandirma_surumu_hizmet_filtresi(self):
        self.assertEqual(SINIFLANDIRMA_SURUMU, "3")
        self.assertTrue(_fiziksel_stok_karti(type("K", (), {"kart_turu": "Ticari Mal"})()))
        self.assertFalse(_fiziksel_stok_karti(type("K", (), {"kart_turu": "Hizmet"})()))
        self.assertFalse(_fiziksel_stok_karti(type("K", (), {"kart_turu": "hizmet geliri"})()))
        self.assertTrue(_sistem_tedarikci_mi("STOK SAYIM FAZLASI HESABI"))
        self.assertFalse(_sistem_tedarikci_mi("BİRR YAPI"))

    def test_hizmet_karti_ihtiyac_acmaz(self):
        with get_session() as s:
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            hizmet = StokKarti(
                stok_kodu="HZM-TEST-1",
                stok_adi="KARGO GELİRİ",
                birim="Adet",
                kart_turu="Hizmet",
                aktif=True,
                is_deleted=False,
                minimum_stok=Decimal("0"),
            )
            s.add(hizmet)
            s.flush()
            s.info["_stok_uyari_calisiyor"] = True
            olaylar = StokUyariService.yeniden_degerlendir(s, [(hizmet.id, depo.id)])
            aktif = s.scalar(
                select(StokIhtiyac).where(
                    StokIhtiyac.stok_id == hizmet.id,
                    StokIhtiyac.depo_id == depo.id,
                    StokIhtiyac.aktif.is_(True),
                )
            )
        self.assertIsNone(aktif)
        self.assertTrue(all(o["tur"] != "YENI" for o in olaylar))

    def test_sistem_cari_siparis_hazirlanamaz(self):
        kart_id = self.o.urun_ekle("MLZ-SYS-1", "Test Malzeme Sipariş", kart_turu="Ticari Mal")
        with get_session() as s:
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            sistem = Cari(
                cari_kodu="SYS-SAYIM",
                unvan="STOK SAYIM FAZLASI HESABI",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(sistem)
            s.flush()
            ihtiyac = s.scalar(
                select(StokIhtiyac).where(
                    StokIhtiyac.stok_id == kart_id, StokIhtiyac.depo_id == depo.id
                )
            )
            if ihtiyac is None:
                ihtiyac = StokIhtiyac(
                    stok_id=kart_id,
                    depo_id=depo.id,
                    aktif=True,
                    olay_no=1,
                    fiziksel=Decimal("0"),
                    rezerve=Decimal("0"),
                    satilabilir=Decimal("0"),
                    beklenen=Decimal("0"),
                    minimum=Decimal("10"),
                    hedef=Decimal("20"),
                    oneri_temel=Decimal("20"),
                    oneri_alim=Decimal("20"),
                    alim_birimi="Adet",
                    nedenler="TUKENDI",
                    row_version=1,
                )
                s.add(ihtiyac)
            else:
                ihtiyac.aktif = True
                ihtiyac.row_version = int(ihtiyac.row_version or 1)
            s.flush()
            ihtiyac_id, rv, sistem_id, depo_ad = ihtiyac.id, ihtiyac.row_version, sistem.id, depo.ad

        with self.assertRaises(ValueError) as ctx:
            StokUyariService.siparis_hazirla(
                [{
                    "ihtiyac_id": ihtiyac_id,
                    "row_version": rv,
                    "tedarikci_id": sistem_id,
                    "miktar": Decimal("5"),
                    "birim": "Adet",
                    "fiyat": Decimal("1"),
                    "teslim_depo": depo_ad,
                }],
                termin=date.today(),
            )
        self.assertIn("sistem", str(ctx.exception).casefold())


if __name__ == "__main__":
    unittest.main()
