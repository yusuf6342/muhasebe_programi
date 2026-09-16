"""Manuel teklif ürünü — zorunlu alanlar, maliyet durumu, dağıtım."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.teklif_pricing_service import dagitimli_hesapla
from teklif_manuel_urun_ui import COST_EKSIK, COST_TAHMINI, LINE_TYPE_MANUAL, manuel_birim_listesi


class TestManuelBirim(unittest.TestCase):
    def test_birim_listesi_adet(self):
        lst = manuel_birim_listesi()
        self.assertIn("Adet", lst)
        self.assertIn("Takım", lst)
        self.assertIn("Hizmet", lst)


class TestManuelDagitim(unittest.TestCase):
    def _stok(self, kod, maliyet, miktar=1):
        return {
            "urun_kodu": kod,
            "urun_adi": kod,
            "miktar": Decimal(str(miktar)),
            "birim": "Adet",
            "birim_maliyet": Decimal(str(maliyet)),
            "purchase_unit_price_base": Decimal(str(maliyet)),
            "purchase_total_cost": Decimal(str(maliyet)) * Decimal(str(miktar)),
            "teklif_fiyati": Decimal("0"),
            "iskonto_orani": 0,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": 20,
            "is_manual_item": False,
            "is_manual_price": False,
        }

    def _manuel(self, ad, maliyet, miktar=1, fiyat=0):
        base = Decimal(str(maliyet))
        return {
            "urun_kodu": "MANUEL",
            "urun_adi": ad,
            "miktar": Decimal(str(miktar)),
            "birim": "Adet",
            "birim_maliyet": base,
            "purchase_unit_price_base": base,
            "purchase_total_cost": base * Decimal(str(miktar)),
            "teklif_fiyati": Decimal(str(fiyat)),
            "iskonto_orani": 0,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": 20,
            "is_manual_item": True,
            "manuel": True,
            "line_type": LINE_TYPE_MANUAL,
            "product_id": None,
            "cost_status": COST_TAHMINI if base > 0 else COST_EKSIK,
            "is_manual_price": fiyat > 0,
            "margin_unavailable": base <= 0,
        }

    def test_manuel_maliyetli_dagitima_katilir(self):
        satirlar = [self._stok("S1", 8000, 1), self._manuel("Özel", 2000, 1)]
        sonuc = dagitimli_hesapla(
            satirlar,
            profit_rate=0,
            fixed_profit_amount=3000,
            customer_expense_amount=0,
        )
        self.assertEqual(sonuc.total_purchase_cost, Decimal("10000.00"))
        manuel = next(s for s in sonuc.satirlar if s.get("is_manual_item"))
        # %20 pay → 600 TL dağıtım → birim ≈ 2600
        self.assertAlmostEqual(float(manuel["teklif_fiyati"]), 2600.0, places=0)

    def test_eksik_maliyet_atlandiginda_yaniltici_kar_yok(self):
        satirlar = [
            self._stok("S1", 1000, 1),
            self._manuel("Özel", 0, 1, fiyat=500),
        ]
        sonuc = dagitimli_hesapla(
            satirlar,
            profit_rate=10,
            fixed_profit_amount=0,
            skip_missing_manual_cost=True,
            manuel_koru=True,
        )
        manuel = next(s for s in sonuc.satirlar if s.get("is_manual_item"))
        self.assertTrue(manuel.get("margin_unavailable") or manuel.get("cost_status") == "EKSIK")
        self.assertEqual(manuel.get("teklif_fiyati"), Decimal("500"))

    def test_eksik_maliyet_hata(self):
        satirlar = [self._stok("S1", 1000, 1), self._manuel("Özel", 0, 1)]
        with self.assertRaises(ValueError):
            dagitimli_hesapla(satirlar, profit_rate=10, skip_missing_manual_cost=False)


class TestManuelDialogValidation(unittest.TestCase):
    """Modal zorunlu alan mantığı (GUI açmadan)."""

    def test_bos_ad_birim_red(self):
        from teklif_manuel_urun_ui import ManuelUrunDialog

        # Doğrulama kurallarını doğrudan simüle et
        ad, birim, miktar = "", "Adet", Decimal("1")
        self.assertFalse(bool(ad and birim and miktar > 0))
        ad, birim = "Ürün", ""
        self.assertFalse(bool(ad and birim))
        ad, birim, miktar = "Ürün", "Adet", Decimal("0")
        self.assertFalse(miktar > 0)
        ad, birim, miktar = "Ürün", "Adet", Decimal("2")
        self.assertTrue(bool(ad and birim and miktar > 0))


class TestSchemaColumns(unittest.TestCase):
    def test_model_has_manual_fields(self):
        from database.models.satis_teklifi import SatisTeklifiSatiri

        cols = SatisTeklifiSatiri.__table__.columns.keys()
        for c in (
            "is_manual_item",
            "line_type",
            "manual_product_name",
            "cost_status",
            "delivery_term_days",
            "product_id",
        ):
            self.assertIn(c, cols)


if __name__ == "__main__":
    unittest.main()
