"""Ürün seçim listesi — stil, kolon sırası, token arama smoke testleri."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class UrunSecListeTest(unittest.TestCase):
    def test_para_tr(self):
        from urun_sec_ui import _para_tr

        self.assertEqual(_para_tr(Decimal("1234.5")), "1.234,50 TL")
        self.assertEqual(_para_tr(0), "0,00 TL")

    def test_mik_goster(self):
        from urun_sec_ui import _mik_goster

        self.assertEqual(_mik_goster(Decimal("10.5000")), "10.5")
        self.assertEqual(_mik_goster(0), "0")

    def test_callback_sozlesme(self):
        from urun_sec_ui import UrunSecDialog

        stok = SimpleNamespace(
            stok_kodu="K1",
            stok_adi="Ray Mobilya 45 cm",
            birim="Adet",
            barkod="8690001112223",
            barkodlar=[],
            lotlar=[SimpleNamespace(kalan_miktar=Decimal("3.5"))],
            fiyatlar=[
                SimpleNamespace(fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("199.99"))
            ],
            kdv_orani=Decimal("20"),
        )
        dlg = object.__new__(UrunSecDialog)
        degerler = UrunSecDialog._callback_degerleri(dlg, stok)
        self.assertEqual(degerler[0], "K1")
        self.assertEqual(degerler[1], "Ray Mobilya 45 cm")
        self.assertEqual(degerler[2], "Adet")
        self.assertEqual(degerler[3], "3.5")
        self.assertTrue(degerler[4].startswith("199"))
        self.assertEqual(len(degerler), 7)

    def test_filtre_kelime_sirasiz_imza(self):
        from database.stok_service import StokService
        import inspect

        sig = inspect.signature(StokService.stoklari_filtrele)
        self.assertIn("kelime_sirasiz", sig.parameters)
        self.assertIn("min_ad_harf", sig.parameters)

    def test_stil_adi_izole(self):
        from urun_sec_ui import _STIL_ADI

        self.assertEqual(_STIL_ADI, "UrunSecKurumsal.Treeview")


if __name__ == "__main__":
    unittest.main()
