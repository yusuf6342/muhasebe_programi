"""Alınan Sipariş Stok Durumu — Var / N eksik, Depolar Toplamı, PDF ayrımı."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.siparis_stok_durumu import (  # noqa: E402
    DURUM_KISMI,
    DURUM_VAR,
    DURUM_YOK,
    durum_etiketi,
    eksik_etiketi,
    satir_stok_bilgileri,
    uyari_durumu_mu,
)


class SiparisStokDurumuTest(unittest.TestCase):
    def test_etiket_kurallari(self):
        self.assertEqual(durum_etiketi(Decimal("10"), Decimal("10")), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("11"), Decimal("10")), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("4"), Decimal("10")), "6 eksik")
        self.assertEqual(durum_etiketi(Decimal("0"), Decimal("10")), "10 eksik")
        self.assertEqual(durum_etiketi(Decimal("-2"), Decimal("10")), "10 eksik")
        self.assertEqual(durum_etiketi(Decimal("5"), Decimal("0")), "")
        self.assertEqual(eksik_etiketi(Decimal("2.5")), "2,5 eksik")
        self.assertEqual(eksik_etiketi(Decimal("100")), "100 eksik")
        self.assertEqual(eksik_etiketi(Decimal("250")), "250 eksik")
        self.assertEqual(eksik_etiketi(Decimal("0")), DURUM_VAR)

    def test_ornek_tablosu_250(self):
        q = Decimal("250")
        self.assertEqual(durum_etiketi(Decimal("150"), q), "100 eksik")
        self.assertEqual(durum_etiketi(Decimal("0"), q), "250 eksik")
        self.assertEqual(durum_etiketi(Decimal("250"), q), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("400"), q), DURUM_VAR)

    def test_uyari_renk(self):
        self.assertTrue(uyari_durumu_mu("100 eksik"))
        self.assertTrue(uyari_durumu_mu("2,5 eksik"))
        self.assertTrue(uyari_durumu_mu(DURUM_KISMI))
        self.assertTrue(uyari_durumu_mu(DURUM_YOK))
        self.assertFalse(uyari_durumu_mu(DURUM_VAR))
        self.assertFalse(uyari_durumu_mu(""))

    def test_ayni_urun_iki_satir_stok_paylasir(self):
        """150 stok: ilk 100 → Var; ikinci 100 → 50 eksik (tekrar sayılmaz)."""
        stok = {"P1": Decimal("150")}
        satirlar = [
            {"urun_kodu": "P1", "miktar": "100", "birim": "Adet"},
            {"urun_kodu": "P1", "miktar": "100", "birim": "Adet"},
        ]
        # get_session + kart yok: stok_map ile; kart boş → carpan 1
        with patch("database.siparis_stok_durumu.get_session") as gs:
            from contextlib import contextmanager
            from unittest.mock import MagicMock

            @contextmanager
            def _cm():
                s = MagicMock()
                s.scalars.return_value.all.return_value = []
                s.execute.return_value.all.return_value = []
                yield s

            gs.side_effect = lambda: _cm()
            bilgiler = satir_stok_bilgileri(satirlar, stok_map=stok, siparis_id=None)
        self.assertEqual(bilgiler[0]["durum"], DURUM_VAR)
        self.assertEqual(bilgiler[1]["durum"], "50 eksik")
        self.assertEqual(bilgiler[0]["depolar_toplami"], "150")
        self.assertEqual(bilgiler[1]["depolar_toplami"], "150")

    def test_kismi_sevk_kalan_esas(self):
        """250 sipariş, 100 sevk → karşılanacak 150; stok 150 → Var."""
        stok = {"P1": Decimal("150")}
        satirlar = [
            {
                "urun_kodu": "P1",
                "miktar": "250",
                "birim": "Adet",
                "irsaliyelenen": "100",
            }
        ]
        with patch("database.siparis_stok_durumu.get_session") as gs:
            from contextlib import contextmanager
            from unittest.mock import MagicMock

            @contextmanager
            def _cm():
                s = MagicMock()
                s.scalars.return_value.all.return_value = []
                s.execute.return_value.all.return_value = []
                yield s

            gs.side_effect = lambda: _cm()
            bilgiler = satir_stok_bilgileri(satirlar, stok_map=stok)
        self.assertEqual(bilgiler[0]["durum"], DURUM_VAR)

    def test_pdf_guvenlik_stok_durumu_yasak(self):
        from database.siparis_form_view import SiparisFormViewModel, assert_siparis_form_safe

        vm = SiparisFormViewModel(siparis_no="SP-1", siparis_tarihi="12.11.2026")
        assert_siparis_form_safe(vm, "Sipariş No SP-1 Ürün Adı Miktar")
        with self.assertRaises(ValueError):
            assert_siparis_form_safe(vm, "Tablo Stok Durumu Var Kısmi")
        with self.assertRaises(ValueError):
            assert_siparis_form_safe(vm, "Depolar Toplamı 150")

    def test_karti_stok_kolonlari_urun_adi_sonrasi(self):
        import inspect

        import satis_siparisi_ui as ui

        src = inspect.getsource(ui.SatisSiparisiKarti._satir_alani)
        self.assertIn('"ad", "stok_durumu", "depolar_toplami"', src)
        yenile = inspect.getsource(ui.SatisSiparisiKarti.satir_listesini_yenile)
        self.assertIn("satir_stok_bilgileri", yenile)
        self.assertIn("stok_uyari", yenile)
        self.assertIn("depolar_toplami", yenile)


if __name__ == "__main__":
    unittest.main()
