"""Teklif fiyat formülleri, dağıtım ve durum sabitleri."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from database.teklif_pricing_service import (
    QuotePricingService,
    dagitimli_hesapla,
    kar_metrikleri,
    tahmini_teslim_hesapla,
    yuvarla,
)
from database.teklif_service import DURUM_GECISLERI, TEKLIF_DURUMLARI


def _satir(miktar, birim_maliyet, **kw):
    miktar = Decimal(str(miktar))
    mal = Decimal(str(birim_maliyet))
    return {
        "urun_kodu": kw.get("kod", "U1"),
        "urun_adi": kw.get("ad", "Ürün"),
        "miktar": miktar,
        "birim": "Adet",
        "birim_maliyet": mal,
        "purchase_unit_price": mal,
        "purchase_unit_price_base": mal,
        "purchase_total_cost": (mal * miktar).quantize(Decimal("0.01")),
        "teklif_fiyati": Decimal("0"),
        "iskonto_orani": 0,
        "iskonto_orani_2": 0,
        "iskonto_orani_3": 0,
        "kdv_orani": 20,
        "is_manual_price": False,
        **{k: v for k, v in kw.items() if k not in ("kod", "ad")},
    }


class TeklifFiyatMotoruTest(unittest.TestCase):
    def test_maliyet_ustu_oran(self):
        # 100 + %25 = 125
        r = QuotePricingService.fiyat_hesapla(
            yontem="MALIYET_USTU_ORAN",
            birim_maliyet=Decimal("100"),
            oran_veya_tutar=Decimal("25"),
            miktar=Decimal("1"),
        )
        self.assertEqual(r.teklif_fiyati, Decimal("125.00"))
        self.assertEqual(r.kar_orani, Decimal("25.00"))
        self.assertEqual(r.gercek_marj, Decimal("20.00"))

    def test_hedef_marj(self):
        # 100 / (1-0.25) = 133.33
        r = QuotePricingService.fiyat_hesapla(
            yontem="HEDEF_MARJ",
            birim_maliyet=Decimal("100"),
            oran_veya_tutar=Decimal("25"),
            miktar=Decimal("1"),
        )
        self.assertEqual(r.teklif_fiyati, Decimal("133.33"))

    def test_maktu(self):
        r = QuotePricingService.fiyat_hesapla(
            yontem="MAKTU_KAR",
            birim_maliyet=Decimal("100"),
            oran_veya_tutar=Decimal("30"),
        )
        self.assertEqual(r.teklif_fiyati, Decimal("130.00"))

    def test_maliyet_eksik_hata(self):
        with self.assertRaises(ValueError):
            QuotePricingService.fiyat_hesapla(
                yontem="MALIYET_USTU_ORAN",
                birim_maliyet=Decimal("0"),
                oran_veya_tutar=Decimal("20"),
            )

    def test_kar_metrikleri(self):
        oran, marj = kar_metrikleri(Decimal("125"), Decimal("100"))
        self.assertEqual(oran, Decimal("25.00"))
        self.assertEqual(marj, Decimal("20.00"))

    def test_yuvarlama(self):
        self.assertEqual(yuvarla(Decimal("12.345"), "kurus"), Decimal("12.35"))
        self.assertEqual(yuvarla(Decimal("12.4"), "1"), Decimal("12"))

    def test_durumlar_tanimli(self):
        self.assertIn("TASLAK", TEKLIF_DURUMLARI)
        self.assertIn("SİPARİŞE DÖNÜŞTÜ", TEKLIF_DURUMLARI)
        self.assertIn("KABUL EDİLDİ", DURUM_GECISLERI["MÜŞTERİYE GÖNDERİLDİ"])


class TeklifDagitimTest(unittest.TestCase):
    """Senaryo 1–7 ve 15 — saf Decimal, DB yok."""

    def test_01_sadece_yuzde_yirmi(self):
        # 10000 + %20 = 12000
        s = [_satir(1, 10000, kod="A")]
        r = dagitimli_hesapla(s, profit_rate=20)
        self.assertEqual(r.calculated_offer_subtotal, Decimal("12000.00"))
        self.assertEqual(r.percentage_profit_amount, Decimal("2000.00"))
        self.assertEqual(r.satirlar[0]["satir_ara"], Decimal("12000.00"))

    def test_02_sadece_maktu_1000(self):
        s = [_satir(1, 10000, kod="A")]
        r = dagitimli_hesapla(s, fixed_profit_amount=1000)
        self.assertEqual(r.calculated_offer_subtotal, Decimal("11000.00"))

    def test_03_yuzde_ve_maktu(self):
        s = [_satir(1, 10000, kod="A")]
        r = dagitimli_hesapla(s, profit_rate=20, fixed_profit_amount=1000)
        self.assertEqual(r.calculated_offer_subtotal, Decimal("13000.00"))

    def test_04_sadece_masraf_500(self):
        s = [_satir(1, 10000, kod="A")]
        r = dagitimli_hesapla(s, customer_expense_amount=500)
        self.assertEqual(r.calculated_offer_subtotal, Decimal("10500.00"))

    def test_05_yuzde_maktu_masraf(self):
        s = [_satir(1, 10000, kod="A")]
        r = dagitimli_hesapla(
            s, profit_rate=20, fixed_profit_amount=1000, customer_expense_amount=500
        )
        self.assertEqual(r.calculated_offer_subtotal, Decimal("13500.00"))
        self.assertEqual(r.percentage_profit_amount, Decimal("2000.00"))
        self.assertEqual(r.total_target_profit, Decimal("3000.00"))

    def test_06_oranli_dagitim_60_40(self):
        # Ek 3500 (= %20*10000 + 1000 + 500) → 2100 / 1400
        s = [
            _satir(1, 6000, kod="A"),
            _satir(1, 4000, kod="B"),
        ]
        r = dagitimli_hesapla(
            s, profit_rate=20, fixed_profit_amount=1000, customer_expense_amount=500
        )
        self.assertEqual(r.calculated_offer_subtotal, Decimal("13500.00"))
        a = next(x for x in r.satir_sonuclari if x.index == 0)
        b = next(x for x in r.satir_sonuclari if x.index == 1)
        ekstra_a = a.allocated_percentage_profit + a.allocated_fixed_profit + a.allocated_expense
        ekstra_b = b.allocated_percentage_profit + b.allocated_fixed_profit + b.allocated_expense
        self.assertEqual(ekstra_a.quantize(Decimal("0.01")), Decimal("2100.00"))
        self.assertEqual(ekstra_b.quantize(Decimal("0.01")), Decimal("1400.00"))
        self.assertEqual(a.satir_ara, Decimal("8100.00"))
        self.assertEqual(b.satir_ara, Decimal("5400.00"))

    def test_07_ondalik_miktar(self):
        s = [
            _satir(Decimal("1.5"), Decimal("100"), kod="A"),
            _satir(Decimal("2.5"), Decimal("100"), kod="B"),
        ]
        # alış: 150 + 250 = 400; %20 = 80 → toplam 480
        r = dagitimli_hesapla(s, profit_rate=20)
        self.assertEqual(r.total_purchase_cost, Decimal("400.00"))
        self.assertEqual(r.calculated_offer_subtotal, Decimal("480.00"))
        self.assertEqual(
            sum((x.satir_ara for x in r.satir_sonuclari), Decimal("0")),
            Decimal("480.00"),
        )

    def test_15_satir_toplamlari_baslik_esit(self):
        s = [
            _satir(3, Decimal("12.34"), kod="A"),
            _satir(7, Decimal("5.67"), kod="B"),
            _satir(Decimal("0.25"), Decimal("1000"), kod="C"),
        ]
        r = dagitimli_hesapla(
            s, profit_rate=Decimal("17.5"), fixed_profit_amount=Decimal("123.45"),
            customer_expense_amount=Decimal("67.89"),
        )
        satir_sum = sum((_decimal_ara(x) for x in r.satirlar), Decimal("0"))
        self.assertEqual(satir_sum, r.calculated_offer_subtotal)
        # kuruş doğruluğu
        self.assertEqual(satir_sum, satir_sum.quantize(Decimal("0.01")))

    def test_eksik_maliyet_engeller(self):
        s = [_satir(1, 0, kod="X")]
        with self.assertRaises(ValueError):
            dagitimli_hesapla(s, profit_rate=10)

    def test_tahmini_teslim(self):
        self.assertEqual(
            tahmini_teslim_hesapla(date(2026, 9, 16), 7),
            date(2026, 9, 23),
        )


def _decimal_ara(s):
    return Decimal(str(s.get("satir_ara", 0)))


if __name__ == "__main__":
    unittest.main()
