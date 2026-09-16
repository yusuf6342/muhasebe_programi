"""Müşteri teklif çıktısı güvenlik — maliyet/kâr sızdırma testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.teklif_customer_view import (
    CustomerQuoteLine,
    CustomerQuoteSecurityError,
    CustomerQuoteViewModel,
    assert_customer_model_safe,
    assert_customer_output_safe,
    build_customer_quote_from_dialog,
)
from teklif_print import render_customer_quote_html, render_internal_cost_html
from database.teklif_customer_view import InternalCostLine, InternalQuoteCostViewModel


class MusteriCiktiGuvenlikTest(unittest.TestCase):
    def _ornek_vm(self) -> CustomerQuoteViewModel:
        return CustomerQuoteViewModel(
            teklif_no="TKL-2026-0001",
            teklif_tarihi="16.09.2026",
            gecerlilik_tarihi="16.10.2026",
            hazirlayan="Ahmet Yılmaz",
            musteri={"unvan": "ABC Ltd", "telefon": "555", "email": "a@b.com"},
            firma={"unvan": "Ray Mobilya", "telefon": "212"},
            satirlar=[
                CustomerQuoteLine(
                    sira=1,
                    urun_kodu="U1",
                    urun_adi="Vida",
                    miktar=Decimal("10"),
                    birim="Adet",
                    birim_fiyat=Decimal("100"),
                    net_birim_fiyat=Decimal("100"),
                    kdv_orani=Decimal("20"),
                    kdv_hariç_toplam=Decimal("1000"),
                    kdv_tutari=Decimal("200"),
                    kdv_dahil_toplam=Decimal("1200"),
                    miktar_goster="10,00",
                    birim_fiyat_goster="100,00",
                    iskonto_goster="—",
                    net_goster="100,00",
                    kdv_oran_goster="%20,00",
                    kdv_hariç_goster="1.000,00",
                    kdv_goster="200,00",
                    kdv_dahil_goster="1.200,00",
                )
            ],
            ara_toplam=Decimal("1000"),
            kdv_toplam=Decimal("200"),
            genel_toplam=Decimal("1200"),
            ara_goster="1.000,00",
            kdv_goster="200,00",
            genel_goster="1.200,00",
            kdv_haric_goster="1.000,00",
            iskonto_goster="0,00",
            para_birimi="TRY",
            termin_suresi="7 Gün",
            tahmini_teslim_tarihi="23.09.2026",
        )

    def test_model_yasak_alan_yok(self):
        vm = self._ornek_vm()
        assert_customer_model_safe(vm)
        d = vm.__dataclass_fields__
        for yasak in (
            "purchase_price",
            "purchase_cost",
            "cost_source",
            "supplier",
            "profit_rate",
            "profit_amount",
            "fixed_profit",
            "margin_rate",
            "internal_expense",
            "allocated_expense",
            "allocated_profit",
            "birim_maliyet",
            "toplam_maliyet",
        ):
            self.assertNotIn(yasak, d)

    def test_musteri_html_maliyet_yok(self):
        html = render_customer_quote_html(self._ornek_vm())
        self.assertIn("TEKLİF FORMU", html)
        self.assertIn("1.200,00", html)
        lower = html.lower()
        for kelime in ("alış", "alis fiyat", "maliyet", "tedarikçi", "fifo", "maktu", "marj %"):
            self.assertNotIn(kelime, lower.replace("ı", "i"))
        # Güvenlik tarayıcı
        assert_customer_output_safe(html)

    def test_yasak_metin_engeller(self):
        with self.assertRaises(CustomerQuoteSecurityError):
            assert_customer_output_safe("Teklif Alış Fiyatı: 100 TL")
        with self.assertRaises(CustomerQuoteSecurityError):
            assert_customer_output_safe("Toplam maliyet 5000")
        with self.assertRaises(CustomerQuoteSecurityError):
            assert_customer_output_safe("Kâr oranı %20")
        with self.assertRaises(CustomerQuoteSecurityError):
            assert_customer_output_safe("Supplier: ABC")

    def test_dialogdan_musteri_model_maliyet_almaz(self):
        dialog = MagicMock()
        dialog.teklif = None
        dialog.girdiler = {
            "teklif_no": MagicMock(get=lambda: "TKL-1"),
            "teklif_tarihi": MagicMock(get=lambda: "16.09.2026"),
            "gecerlilik_tarihi": MagicMock(get=lambda: "16.10.2026"),
            "gecerlilik_gunu": MagicMock(get=lambda: "30"),
            "referans_no": MagicMock(get=lambda: ""),
            "konu": MagicMock(get=lambda: "Test"),
            "proje": MagicMock(get=lambda: ""),
            "para_birimi": MagicMock(get=lambda: "TRY"),
            "odeme_sekli": MagicMock(get=lambda: "Nakit"),
            "teslim_suresi": MagicMock(get=lambda: ""),
            "teslimat_sekli": MagicMock(get=lambda: ""),
            "delivery_term_days": MagicMock(get=lambda: "7"),
            "estimated_delivery_date": MagicMock(get=lambda: "23.09.2026"),
            "aday_musteri_adi": MagicMock(get=lambda: "Test Müşteri"),
            "musteri_yetkilisi": MagicMock(get=lambda: ""),
            "musteri_telefon": MagicMock(get=lambda: ""),
            "musteri_email": MagicMock(get=lambda: ""),
            "satis_temsilcisi": MagicMock(get=lambda: "Ayşe"),
        }
        dialog.musteri_notu = MagicMock(get=lambda *_a, **_k: "Müşteri notu")
        dialog.ticari_sartlar = MagicMock(get=lambda *_a, **_k: "30 gün vade")
        dialog.ic_not = MagicMock(get=lambda *_a, **_k: "GİZLİ İÇ NOT — ALIŞ 50 TL KÂR %40")
        dialog._secili_musteri = MagicMock(return_value=None)
        dialog.satirlar = [
            {
                "urun_kodu": "X1",
                "urun_adi": "Ürün",
                "miktar": Decimal("2"),
                "birim": "Adet",
                "teklif_fiyati": Decimal("135"),
                "final_offer_unit_price": Decimal("135"),
                "birim_maliyet": Decimal("100"),  # iç alan — modele girmemeli
                "purchase_unit_price": Decimal("100"),
                "maliyet_kaynagi": "SON_ALIS",
                "supplier_name": "Gizli Tedarikçi",
                "allocated_expense": Decimal("5"),
                "kar_orani": Decimal("35"),
                "gercek_marj": Decimal("25"),
                "iskonto_orani": 0,
                "kdv_orani": Decimal("20"),
                "net_birim_fiyat": Decimal("135"),
                "toplama_dahil": True,
                "opsiyonel": False,
            }
        ]
        with patch(
            "invoice_print.branding.load_company_branding",
            return_value={"unvan": "Firma", "ibanlar": []},
        ), patch(
            "invoice_print.branding.logo_data_uri",
            return_value=None,
        ), patch(
            "belge_kullanici_ui.aktif_kullanici_adi",
            return_value="Test User",
        ):
            vm = build_customer_quote_from_dialog(dialog)
        html = render_customer_quote_html(vm)
        self.assertNotIn("Gizli Tedarikçi", html)
        self.assertNotIn("SON_ALIS", html)
        self.assertNotIn("GİZLİ İÇ NOT", html)
        self.assertIn("135", html)
        line_fields = vm.satirlar[0].__dataclass_fields__
        self.assertNotIn("birim_maliyet", line_fields)
        self.assertNotIn("purchase_unit_price", line_fields)

    def test_ic_maliyet_sablonu_uyari_bant(self):
        vm = InternalQuoteCostViewModel(
            teklif_no="TKL-1",
            musteri_unvan="ABC",
            total_purchase_cost=Decimal("10000"),
            profit_rate=Decimal("20"),
            percentage_profit_amount=Decimal("2000"),
            fixed_profit_amount=Decimal("1000"),
            customer_expense_amount=Decimal("500"),
            actual_profit_amount=Decimal("3500"),
            satirlar=[
                InternalCostLine(
                    sira=1,
                    urun_kodu="A",
                    urun_adi="Ürün A",
                    miktar=Decimal("1"),
                    alis_birim=Decimal("6000"),
                    alis_toplam=Decimal("6000"),
                    maliyet_kaynagi="SON_ALIS",
                    tedarikci="Tedarikçi X",
                    teklif_birim=Decimal("8100"),
                    teklif_ara=Decimal("8100"),
                    gercek_kar=Decimal("2100"),
                    marj=Decimal("25.93"),
                )
            ],
        )
        html = render_internal_cost_html(vm)
        self.assertIn("ŞİRKET İÇİDİR", html)
        self.assertIn("Tedarikçi X", html)
        self.assertIn("SON_ALIS", html)
        self.assertIn("Alış", html)


if __name__ == "__main__":
    unittest.main()
