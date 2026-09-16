"""Satış irsaliyesi birim testleri — DB gerektirmeyen kontroller."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.satis_irsaliyesi_service import (
    IRSALIYE_DURUMLARI,
    LEGACY_DURUM_MAP,
    SatisIrsaliyesiService,
    durum_gosterim,
    faturalanacak_kalan,
    stok_cikis_gerekli,
)


class TestIrsaliyeDurum(unittest.TestCase):
    def test_durumlar_taslak_ve_sevk(self):
        self.assertIn("TASLAK", IRSALIYE_DURUMLARI)
        self.assertIn("SEVK EDİLDİ", IRSALIYE_DURUMLARI)
        self.assertIn("İPTAL", IRSALIYE_DURUMLARI)

    def test_legacy_acik_map(self):
        self.assertIn("AÇIK", LEGACY_DURUM_MAP)
        self.assertEqual(durum_gosterim("AÇIK"), "SEVK EDİLDİ")
        self.assertEqual(durum_gosterim("TASLAK"), "TASLAK")


class TestStokCikisGerekli(unittest.TestCase):
    def test_posted_skip(self):
        ir = SimpleNamespace(stok_cikis_yapildi=True)
        self.assertFalse(stok_cikis_gerekli(ir))

    def test_legacy_needs_fatura_cikis(self):
        ir = SimpleNamespace(stok_cikis_yapildi=False, durum="AÇIK")
        self.assertTrue(stok_cikis_gerekli(ir))

    def test_none_needs_stock(self):
        self.assertTrue(stok_cikis_gerekli(None))


class TestToplamDecimal(unittest.TestCase):
    def test_toplam(self):
        satir = SimpleNamespace(
            miktar=Decimal("2"),
            birim_fiyat=Decimal("100"),
            iskonto_orani=Decimal("10"),
            kdv_orani=Decimal("20"),
        )
        t = SatisIrsaliyesiService.toplam([satir])
        # brut 200, isk 20, net 180, kdv 36, genel 216
        self.assertEqual(t["ara_toplam"], Decimal("200"))
        self.assertEqual(t["iskonto"], Decimal("20"))
        self.assertEqual(t["kdv"], Decimal("36"))
        self.assertEqual(t["genel_toplam"], Decimal("216"))

    def test_faturalanacak_kalan(self):
        satir = SimpleNamespace(miktar=Decimal("10"), faturalanan_miktar=Decimal("3"))
        self.assertEqual(faturalanacak_kalan(satir), Decimal("7"))


class TestSevkEtStok(unittest.TestCase):
    @patch("database.satis_irsaliyesi_service.get_session")
    @patch("database.satis_irsaliyesi_service.yazma_zorunlu")
    @patch("database.user_audit.require_user_session")
    @patch("database.user_audit.current_actor")
    @patch("database.user_audit.stamp_update")
    @patch("database.user_audit.audit_document")
    @patch("database.stok_service.StokService.irsaliye_cikisi")
    @patch.object(SatisIrsaliyesiService, "schema_hazirla")
    @patch.object(SatisIrsaliyesiService, "getir")
    def test_sevk_et_calls_irsaliye_cikisi(
        self,
        mock_getir,
        mock_schema,
        mock_cikis,
        mock_audit,
        mock_stamp,
        mock_actor,
        mock_req,
        mock_yazma,
        mock_session_cm,
    ):
        from datetime import date

        satir = SimpleNamespace(
            urun_kodu="U1",
            miktar=Decimal("5"),
            depo="ANA DEPO",
            lot_no="",
        )
        irsaliye = SimpleNamespace(
            id=1,
            irsaliye_no="IRS-1",
            durum="TASLAK",
            stok_cikis_yapildi=False,
            satirlar=[satir],
            depo="ANA DEPO",
            irsaliye_tarihi=date.today(),
        )
        session = MagicMock()
        session.scalar.return_value = irsaliye
        mock_session_cm.return_value.__enter__.return_value = session
        mock_session_cm.return_value.__exit__.return_value = False
        mock_actor.return_value = {
            "user_id": 1,
            "username": "t",
            "full_name": "Test",
            "now": MagicMock(),
        }
        mock_cikis.return_value = {"lot_cikisi": "L1:5", "fifo_birim_maliyeti": Decimal("1")}
        mock_getir.return_value = irsaliye

        SatisIrsaliyesiService.sevk_et(1)

        mock_cikis.assert_called_once()
        args = mock_cikis.call_args[0]
        self.assertEqual(args[1], "IRS-1")
        self.assertEqual(args[3], "U1")
        self.assertTrue(irsaliye.stok_cikis_yapildi)
        self.assertEqual(irsaliye.durum, "SEVK EDİLDİ")


class TestCustomerDispatchSecurity(unittest.TestCase):
    def test_model_and_html_safe(self):
        from database.irsaliye_customer_view import (
            CustomerDispatchLine,
            CustomerDispatchViewModel,
            assert_customer_dispatch_safe,
            render_customer_dispatch_html,
        )

        vm = CustomerDispatchViewModel(
            irsaliye_no="IRS-T",
            irsaliye_tarihi="16.09.2026",
            is_priced=True,
            musteri={"unvan": "ABC", "kod": "C1"},
            sevk={"adres": "Cadde 1"},
            satirlar=[
                CustomerDispatchLine(
                    sira=1,
                    urun_kodu="P1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim_fiyat=Decimal("10"),
                    satir_toplam=Decimal("12"),
                    miktar_goster="1",
                    birim_fiyat_goster="10,00",
                    iskonto_goster="%0",
                    kdv_oran_goster="%20",
                    satir_toplam_goster="12,00",
                )
            ],
            ara_toplam=Decimal("10"),
            kdv_toplam=Decimal("2"),
            genel_toplam=Decimal("12"),
            ara_goster="10,00",
            kdv_goster="2,00",
            genel_goster="12,00",
        )
        html = render_customer_dispatch_html(vm)
        assert_customer_dispatch_safe(vm, html)
        self.assertIn("SEVK İRSALİYESİ", html)
        self.assertNotIn("ic_not", html.lower())


if __name__ == "__main__":
    unittest.main()
