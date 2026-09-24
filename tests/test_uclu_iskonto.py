"""Üçlü iskonto / net birim fiyat birim testleri (satış + alış)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.iskonto_hesap_service import (
    etkili_iskonto_orani,
    iskonto_carpani,
    iskonto_goster_metin,
    iskonto_oranlarini_dogrula,
    satir_iskonto_hesapla,
    satir_net_brut_indirim,
)
from database.alis_faturasi_service import AlisFaturasiService
from database.satis_faturasi_service import SatisFaturasiService


class UcluIskontoHesapTest(unittest.TestCase):
    def test_ornek_1000_10_5_2_kdv20(self):
        """Zorunlu örnek: 1000 TL, %10+%5+%2, %20 KDV → 837,90 / 1.005,48."""
        h = satir_iskonto_hesapla(
            miktar=1,
            brut_birim_fiyat=Decimal("1000"),
            iskonto1=10,
            iskonto2=5,
            iskonto3=2,
            kdv_orani=20,
        )
        self.assertEqual(h["iskonto_sonrasi_birim_fiyat"], Decimal("837.90"))
        self.assertEqual(h["net_birim_fiyat"], Decimal("1005.48"))
        self.assertEqual(h["net_tutar"], Decimal("1005.48"))
        self.assertEqual(h["etkili_iskonto_orani"], Decimal("16.21"))

    def test_etkili_oran_toplama_degil(self):
        self.assertEqual(etkili_iskonto_orani(10, 5, 2), Decimal("16.21"))
        self.assertNotEqual(etkili_iskonto_orani(10, 5, 2), Decimal("17"))

    def test_siralı_carpan(self):
        self.assertEqual(
            iskonto_carpani(10, 5, 2).quantize(Decimal("0.000001")),
            Decimal("0.837900"),
        )

    def test_negatif_red(self):
        with self.assertRaises(ValueError):
            iskonto_oranlarini_dogrula(-1, 0, 0)
        with self.assertRaises(ValueError):
            iskonto_oranlarini_dogrula(0, 101, 0)

    def test_bos_sifir(self):
        brut, ind, net = satir_net_brut_indirim(2, 100, 0, 0, 0)
        self.assertEqual(brut, Decimal("200"))
        self.assertEqual(ind, Decimal("0"))
        self.assertEqual(net, Decimal("200"))

    def test_yuzde_yuz(self):
        brut, ind, net = satir_net_brut_indirim(1, 100, 100, 0, 0)
        self.assertEqual(net, Decimal("0"))
        self.assertEqual(ind, Decimal("100"))

    def test_goster_metin(self):
        self.assertEqual(iskonto_goster_metin(10, 5, 2), "%10 + %5 + %2")
        self.assertEqual(iskonto_goster_metin(10, 0, 0), "%10")
        self.assertEqual(iskonto_goster_metin(0, 0, 0, bos_goster=""), "")

    def test_satis_servis_uyum(self):
        # Satış: ham 837,90 kuruşta kalır (tam TL yuvarlama yok)
        brut, ind, net = SatisFaturasiService._satir_net(1, 1000, 10, 5, 2)
        self.assertEqual(net, Decimal("837.90"))
        self.assertEqual(ind.quantize(Decimal("0.01")), Decimal("162.10"))

    def test_alis_toplam_uclu(self):
        toplam = AlisFaturasiService.toplam(
            [
                {
                    "miktar": 1,
                    "birim_fiyat": 1000,
                    "iskonto_orani": 10,
                    "iskonto_orani_2": 5,
                    "iskonto_orani_3": 2,
                    "kdv_orani": 20,
                }
            ]
        )
        # ara 1000, iskonto 162.10, kdv 167.58, genel 1005.48
        self.assertEqual(toplam["ara_toplam"], Decimal("1000.00"))
        self.assertEqual(toplam["iskonto"], Decimal("162.10"))
        self.assertEqual(toplam["kdv"], Decimal("167.58"))
        self.assertEqual(toplam["genel_toplam"], Decimal("1005.48"))

    def test_satis_toplam_uclu(self):
        toplam = SatisFaturasiService.toplam(
            [
                {
                    "miktar": 1,
                    "birim_fiyat": 1000,
                    "iskonto_orani": 10,
                    "iskonto_orani_2": 5,
                    "iskonto_orani_3": 2,
                    "kdv_orani": 20,
                }
            ]
        )
        # Matrah 837,90; KDV %20 = 167,58; genel = 1005,48 (alış ile aynı)
        self.assertEqual(toplam["genel_toplam"], Decimal("1005.48"))
        self.assertEqual(toplam["ara_toplam"], Decimal("1000.00"))
        self.assertEqual(toplam["iskonto"], Decimal("162.10"))
        self.assertEqual(toplam["kdv"], Decimal("167.58"))

    def test_alis_net_birim_maliyet(self):
        net = AlisFaturasiService._net_birim_maliyet(
            Decimal("1000"), Decimal("10"), 5, 2
        )
        self.assertEqual(net.quantize(Decimal("0.01")), Decimal("837.90"))

    def test_kdv_dahil_cift_ekleme_yok(self):
        h = satir_iskonto_hesapla(
            miktar=1,
            brut_birim_fiyat=Decimal("1200"),
            iskonto1=0,
            iskonto2=0,
            iskonto3=0,
            kdv_orani=20,
            kdv_dahil=True,
        )
        # 1200 dahil → matrah 1000, KDV 200, net birim 1200
        self.assertEqual(h["net_birim_fiyat"], Decimal("1200.00"))
        self.assertEqual(h["iskonto_sonrasi_birim_fiyat"], Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main()
