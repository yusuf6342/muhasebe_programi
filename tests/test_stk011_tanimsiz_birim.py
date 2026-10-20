"""STK-011 / S14: kartta tanımsız alternatif birim sessizce ×1 sayılmaz.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_stk011_tanimsiz_birim.py -q
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.stok_service import BirimDonusumHatasi, StokService
from fatura_satir_birim_service import (
    birim_degistir,
    birim_satis_fiyati,
    fiyat_birim_donustur,
    miktar_birim_donustur,
    temel_miktar,
)


def _kart(*birimler, ana="Adet", kod="U001"):
    return SimpleNamespace(
        stok_kodu=kod,
        birim=ana,
        birimler=[
            SimpleNamespace(birim_adi=ad, carpan=Decimal(c), aktif=aktif, fiyat_modu="oto", satis_1=None)
            for ad, c, aktif in birimler
        ],
        fiyatlar=[SimpleNamespace(fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("10"), para_birimi="TL")],
    )


class StokServiceKesinCarpanTest(unittest.TestCase):
    def setUp(self):
        self.kart = _kart(("Koli", "12", True), ("Eski", "6", False), ("Bos", "0", True))

    def test_tanimli_birim_donusur(self):
        self.assertEqual(StokService.temel_miktara_cevir(2, "Koli", self.kart), Decimal("24.000000"))
        self.assertEqual(StokService.temel_miktara_cevir(5, "adet", self.kart), Decimal("5.000000"))

    def test_tanimsiz_pasif_ve_katsayisiz_birim_hata_verir(self):
        for birim in ("Paket", "Eski", "Bos"):
            with self.subTest(birim=birim), self.assertRaises(BirimDonusumHatasi) as ctx:
                StokService.temel_miktara_cevir(2, birim, self.kart)
            self.assertIn("U001", ctx.exception.urun_kodlari)
            self.assertIn("katsayı 1 kabul edilmez", str(ctx.exception))

    def test_onizleme_tanimsiz_birimde_hata(self):
        with self.assertRaises(BirimDonusumHatasi):
            StokService.birim_donusum_onizleme(2, "Paket", "Adet", self.kart)
        with self.assertRaises(BirimDonusumHatasi):
            StokService.birim_donusum_onizleme(2, "Koli", "Paket", self.kart)

    def test_bul_none_doner_eski_okuma_1(self):
        self.assertIsNone(StokService.birim_carpani_bul(self.kart, "Paket"))
        self.assertEqual(StokService.birim_carpani(self.kart, "Paket"), Decimal("1"))

    def test_birim_fiyati_tanimsiz_birimde_ana_fiyat_donmez(self):
        self.assertIsNone(StokService.birim_fiyati_getir(self.kart, "Paket"))
        self.assertEqual(StokService.birim_fiyati_getir(self.kart, "Adet"), Decimal("10"))


class S14FaturaSatirTest(unittest.TestCase):
    """S14: temel_miktar(2, 'Paket', 'U001') — Paket kartta yoksa sonuç 2 olamaz."""

    def setUp(self):
        self.kart = _kart(("Koli", "12", True))
        self.p = patch("fatura_satir_birim_service._stok_yukle", return_value=self.kart)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_s14_temel_miktar(self):
        with self.assertRaises(BirimDonusumHatasi):
            temel_miktar(Decimal("2"), "Paket", "U001")
        self.assertEqual(temel_miktar(Decimal("2"), "Koli", "U001"), Decimal("24.000000"))

    def test_miktar_ve_fiyat_donusumu_tanimsiz_birimde_hata(self):
        with self.assertRaises(BirimDonusumHatasi):
            miktar_birim_donustur(Decimal("2"), "Koli", "Paket", "U001")
        with self.assertRaises(BirimDonusumHatasi):
            fiyat_birim_donustur(Decimal("120"), "Koli", "Paket", "U001")
        with self.assertRaises(BirimDonusumHatasi):
            birim_satis_fiyati("U001", "Paket")

    def test_birim_degistir_tanimsiz_birime_gecmez(self):
        satir = {"urun_kodu": "U001", "birim": "Adet", "miktar": "24", "birim_satis_fiyati": "10"}
        with self.assertRaises(BirimDonusumHatasi):
            birim_degistir(satir, "Paket")
        g = birim_degistir(satir, "Koli")
        self.assertEqual(Decimal(g["miktar"]), Decimal("2"))
        self.assertEqual(Decimal(g["temel_miktar"]), Decimal("24"))
        self.assertEqual(Decimal(g["birim_satis_fiyati"]), Decimal("120"))

    def test_kartsiz_serbest_satir_etkilenmez(self):
        with patch("fatura_satir_birim_service._stok_yukle", return_value=None):
            self.assertEqual(temel_miktar(Decimal("3"), "Saat", "HIZMET"), Decimal("3.000000"))


class TeklifCarpanTest(unittest.TestCase):
    def test_teklif_tanimsiz_birim_hata_verir(self):
        from database import teklif_pricing_service as tps

        kart = _kart(("Koli", "12", True))
        oturum = SimpleNamespace(scalar=lambda *_a, **_k: kart)

        class _Ctx:
            def __enter__(self):
                return oturum

            def __exit__(self, *a):
                return False

        from tests._oturum_yamasi import oturum_yamasi

        with oturum_yamasi(_Ctx):
            self.assertEqual(tps.stok_birim_carpani("U001", "Koli"), Decimal("12"))
        with oturum_yamasi(_Ctx):
            with self.assertRaises(BirimDonusumHatasi):
                tps.stok_birim_carpani("U001", "Paket")
        self.assertEqual(tps.stok_birim_carpani("OZEL", "Paket"), Decimal("1"))


class KarAnalizTanimsizBirimTest(unittest.TestCase):
    def test_tanimsiz_birim_maliyeti_belirsiz(self):
        from database.satis_kar_analiz_service import SatisKarAnalizService

        kart = _kart(("Koli", "12", True))
        kart.marka = kart.rapor_grubu = ""
        ortak = dict(
            belge_turu="FATURA", belge_id=1, belge_no="F1", tarih=None, cari=None, stok=kart,
            depo="", alan="fifo_birim_maliyeti", yontem="FIFO", dusuk_esik=Decimal("10"),
            personel="", isaret=1,
        )

        def satir(birim):
            return SimpleNamespace(
                urun_kodu="U001", urun_adi="Ürün", miktar=Decimal("2"), birim_fiyat=Decimal("200"), birim=birim,
                fifo_birim_maliyeti=Decimal("5"), birim_carpani=None,
            )

        koli = SatisKarAnalizService._satir_analiz(satir=satir("Koli"), **ortak)
        self.assertEqual(koli.toplam_maliyet, Decimal("120.00"))
        paket = SatisKarAnalizService._satir_analiz(satir=satir("Paket"), **ortak)
        self.assertEqual(paket.maliyet_kodu, "UNIT_UNDEFINED")
        self.assertEqual(paket.durum, "maliyeti_belirsiz")
        self.assertIsNone(paket.toplam_maliyet)


if __name__ == "__main__":
    unittest.main()
