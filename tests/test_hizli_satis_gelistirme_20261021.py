"""Hızlı Satış Geliştirme Talimatı (21/28 Ekim) — sepet sütunları, pin önizleme, odak yardımcıları."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SepetSutunTest(unittest.TestCase):
    def test_varsayilan_gorunum_urun_adi_en_genis(self):
        from hizli_satis_ui import SEPET_GORUNUR, SEPET_SUTUNLARI

        self.assertEqual(SEPET_GORUNUR[0], "ad")
        self.assertNotIn("kod", SEPET_GORUNUR)
        self.assertNotIn("sıra", SEPET_GORUNUR)
        for k in ("ad", "miktar", "birim", "fiyat", "isk", "kdv", "toplam"):
            self.assertIn(k, SEPET_GORUNUR)
            self.assertIn(k, SEPET_SUTUNLARI)


class PinOnizlemeImportTest(unittest.TestCase):
    def test_servis_metodlari_var(self):
        from database.hizli_satis_service import HizliSatisService
        import inspect

        self.assertTrue(callable(HizliSatisService.pin_stok_rapor_grubu_onizle))
        self.assertTrue(callable(HizliSatisService.pin_stok_rapor_grubu_ekle))
        self.assertTrue(callable(HizliSatisService.pin_toplu_ekle))
        sig = inspect.signature(HizliSatisService.pin_stok_rapor_grubu_onizle)
        self.assertIn("alt_gruplar_dahil", sig.parameters)


class OrtaPanedLayoutTest(unittest.TestCase):
    def test_paned_yardimcilari(self):
        from hizli_satis_ui import HizliSatisPencere

        self.assertTrue(hasattr(HizliSatisPencere, "_orta_layout_yukle"))
        self.assertTrue(hasattr(HizliSatisPencere, "_panel_daralt_ac"))
        self.assertTrue(hasattr(HizliSatisPencere, "_orta_layout_kaydet"))


class CariKartHizliMenuImportTest(unittest.TestCase):
    def test_menu_metotlari(self):
        from cari_kart_ui import CariDialog

        self.assertTrue(hasattr(CariDialog, "_hizli_islemler_menu_ac"))
        self.assertTrue(hasattr(CariDialog, "_hizli_islem_maddelerini_hazirla"))


if __name__ == "__main__":
    unittest.main()
