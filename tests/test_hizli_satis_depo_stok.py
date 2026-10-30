"""Hızlı satış depo çözümleme + sepet tutar / yeni toplam tutarlılığı."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.hizli_satis_service import (  # noqa: E402
    HizliSatisService,
    depo_bul,
    satis_deposu_adi,
)
from database.models.stok import Depo, StokKarti, StokLotu  # noqa: E402
from hizli_satis_sepet import HizliSatisSepet  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402


class HizliSatisDepoStokTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])

    def tearDown(self):
        self.o.kapat()

    def test_depo_norm_bos_akrani_dolu_depoya_yonlendirir(self):
        """«ANA DEPO» boş, «Ana Depo» doluysa çözümleme dolu depoyu seçer."""
        with get_session() as s:
            ana = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            if ana is None:
                ana = Depo(ad="ANA DEPO", aktif=True, varsayilan=True)
                s.add(ana)
                s.flush()
            else:
                ana.varsayilan = True
            # İkinci depo — büyük/küçük farkı
            ikiz = s.scalar(select(Depo).where(Depo.ad == "Ana Depo"))
            if ikiz is None:
                ikiz = Depo(ad="Ana Depo", aktif=True, varsayilan=False)
                s.add(ikiz)
                s.flush()
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            # ANA DEPO lotlarını sıfırla / ekleme
            for L in s.scalars(select(StokLotu).where(StokLotu.stok_id == stok.id)).all():
                if L.depo_id == ana.id:
                    L.kalan_miktar = Decimal("0")
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=ikiz.id,
                    lot_no="TEST-ANA-DEPO",
                    giris_tarihi=__import__("datetime").date.today(),
                    kalan_miktar=Decimal("289"),
                    birim_maliyet=Decimal("1"),
                )
            )
            s.flush()
            bulunan = depo_bul(s, "ANA DEPO")
            self.assertIsNotNone(bulunan)
            self.assertEqual(bulunan.ad, "Ana Depo")

        # Stok kontrolü 89 adedi kabul etmeli
        sepet = HizliSatisSepet()
        sepet.ekle(
            stok_id=1,
            stok_kodu="U001",
            stok_adi="Test",
            miktar=Decimal("89"),
            birim_fiyat=Decimal("1"),
        )
        # stok_id gerçek id ile
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            sepet.satirlar[0].stok_id = stok.id
        hatalar = HizliSatisService.stok_yeterlilik_kontrol(sepet.satirlar, depo="ANA DEPO")
        self.assertEqual(hatalar, [], hatalar)
        self.assertEqual(satis_deposu_adi("ANA DEPO"), "Ana Depo")

    def test_sepet_tutar_ve_yeni_toplam(self):
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=3, birim_fiyat=Decimal("0.60"))
        sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=5, birim_fiyat=Decimal("1.00"))
        t = sepet.toplamlar()
        self.assertEqual(t["genel_toplam"], Decimal("6.80"))
        sepet.fiyat_ayarla(1, Decimal("1.20"))
        t2 = sepet.toplamlar()
        self.assertEqual(sepet.satirlar[1].satir_toplam, Decimal("6.00"))
        self.assertEqual(t2["genel_toplam"], Decimal("7.80"))
        # Yeni toplam onayında genel = hedef
        sepet.hedef_toplam_uygula(Decimal("540.00"))
        t3 = sepet.toplamlar()
        self.assertEqual(t3["genel_toplam"], Decimal("540.00"))


if __name__ == "__main__":
    unittest.main()
