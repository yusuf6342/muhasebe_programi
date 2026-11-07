"""Cari Hareketler fatura ürün detayı — sütunlu görünüm kabul testleri.

EXE/paket üretmez. Çalıştırma:
  python -m pytest tests/test_cari_hareket_urun_sutun.py -q
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class UrunSutunTercihTest(unittest.TestCase):
    def test_varsayilan_acik_ve_kalici(self):
        from cari_kart_ui import (
            _hareket_urun_sutun_tercih_oku,
            _hareket_urun_sutun_tercih_yaz,
        )

        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "tercih.json"
            with patch("cari_kart_ui._hareket_urun_sutun_tercih_yolu", return_value=yol):
                self.assertTrue(_hareket_urun_sutun_tercih_oku(True))
                _hareket_urun_sutun_tercih_yaz(False)
                self.assertFalse(_hareket_urun_sutun_tercih_oku(True))
                ham = json.loads(yol.read_text(encoding="utf-8"))
                self.assertEqual(ham.get("urun_sutunlari_acik"), False)
                _hareket_urun_sutun_tercih_yaz(True)
                self.assertTrue(_hareket_urun_sutun_tercih_oku(False))


class UrunSutunExpandTest(unittest.TestCase):
    """Yalnız _expand_invoice_row — tam cari kart UI'sı açılmaz."""

    def setUp(self):
        import tkinter as tk
        from cari_kart_ui import CariDialog

        self.root = tk.Tk()
        self.root.withdraw()
        kolonlar = (
            "tarih",
            "tur",
            "belge",
            "aciklama",
            "barkod",
            "urun_adi",
            "miktar",
            "birim",
            "net_birim_fiyat",
            "satir_tutari",
            "pb",
            "doviz",
            "kur",
            "borc",
            "alacak",
            "bakiye",
            "gun",
        )
        self.tablo = tk.ttk.Treeview(
            self.root, columns=kolonlar, show="tree headings", height=6
        )
        self.tablo["displaycolumns"] = kolonlar
        self.host = MagicMock()
        self.host.hareket_tablosu = self.tablo
        self.host._hareket_iid_meta = {}
        self.host._fatura_detay_cache = {}
        self.host._hareket_yukleniyor = False
        self.host._hareket_urun_sutunlari_acik = True
        self.host.cari = MagicMock(id=1)
        self.host._hareket_gorunum_uygula = MagicMock()
        self.host._expand_invoice_row = types.MethodType(
            CariDialog._expand_invoice_row, self.host
        )

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _parent(self, belge="SAF04886"):
        iid = self.tablo.insert(
            "",
            "end",
            text="▶",
            values=(
                "01.01.2026",
                "Satış",
                belge,
                "Fatura",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "100,00",
                "",
                "100,00",
                "10",
            ),
        )
        self.host._hareket_iid_meta[iid] = {
            "genisletilebilir": True,
            "fatura_id": 99 if belge == "SAF04886" else 88,
            "belge_tipi": "satis",
            "cari_id": 1,
            "hareket_id": 1,
        }
        return iid

    def test_expand_sutunlara_yazar_aciklamaya_yigmaz(self):
        parent = self._parent("SAF04886")
        self.host._fatura_detay_cache[("satis", 99)] = {
            "satirlar": [
                {
                    "urun_kodu": "STK001",
                    "barkod": "8690001",
                    "urun_adi": "Menteşe 35mm",
                    "miktar_goster": "10",
                    "birim": "Adet",
                    "net_birim_fiyat_goster": "12,50",
                    "net_goster": "125,00",
                    "para_birimi": "TRY",
                    "iskonto": "0",
                    "aciklama": "",
                    "depo": "",
                    "lot": "",
                    "stok_fark_uyari": "",
                }
            ]
        }
        self.host._expand_invoice_row(parent)
        children = self.tablo.get_children(parent)
        self.assertEqual(len(children), 1)
        vals = self.tablo.item(children[0], "values")
        aciklama, barkod, urun, miktar, birim, fiyat, tutar = vals[3:10]
        self.assertEqual(barkod, "STK001")
        self.assertEqual(urun, "Menteşe 35mm")
        self.assertEqual(miktar, "10")
        self.assertEqual(birim, "Adet")
        self.assertEqual(fiyat, "12,50")
        self.assertEqual(tutar, "125,00")
        self.assertNotIn("Menteşe 35mm", aciklama)
        self.assertNotIn("12,50", aciklama)
        self.assertNotIn(" · ", aciklama or "")
        # Tekrar açınca çoğalma yok
        self.host._expand_invoice_row(parent)
        self.assertEqual(len(self.tablo.get_children(parent)), 1)

    def test_detay_borc_alacak_bakiye_bos(self):
        parent = self._parent("SAF04881")
        self.host._fatura_detay_cache[("satis", 88)] = {
            "satirlar": [
                {
                    "urun_kodu": "X1",
                    "barkod": "",
                    "urun_adi": "Ürün X",
                    "miktar_goster": "1",
                    "birim": "Adet",
                    "net_birim_fiyat_goster": "200,00",
                    "net_goster": "200,00",
                    "para_birimi": "TRY",
                    "iskonto": "",
                    "aciklama": "",
                    "depo": "",
                    "lot": "",
                    "stok_fark_uyari": "",
                }
            ]
        }
        self.host._expand_invoice_row(parent)
        vals = self.tablo.item(self.tablo.get_children(parent)[0], "values")
        self.assertEqual((vals[13], vals[14], vals[15]), ("", "", ""))

    def test_kapali_sutun_acilir_expand_ile(self):
        parent = self._parent("SAF04886")
        self.host._hareket_urun_sutunlari_acik = False
        self.host._fatura_detay_cache[("satis", 99)] = {
            "satirlar": [
                {
                    "urun_kodu": "A",
                    "barkod": "",
                    "urun_adi": "Ürün A",
                    "miktar_goster": "2",
                    "birim": "Adet",
                    "net_birim_fiyat_goster": "5,00",
                    "net_goster": "10,00",
                    "para_birimi": "TRY",
                    "iskonto": "",
                    "aciklama": "",
                    "depo": "",
                    "lot": "",
                    "stok_fark_uyari": "",
                }
            ]
        }
        with patch("cari_kart_ui._hareket_urun_sutun_tercih_yaz") as yaz:
            self.host._expand_invoice_row(parent)
            self.assertTrue(self.host._hareket_urun_sutunlari_acik)
            yaz.assert_called_with(True)
            self.host._hareket_gorunum_uygula.assert_called()


class GorunumUygulaTest(unittest.TestCase):
    def test_displaycolumns_urunlu(self):
        import tkinter as tk
        import types
        from cari_kart_ui import CariDialog

        root = tk.Tk()
        root.withdraw()
        try:
            kolonlar = (
                "tarih",
                "tur",
                "belge",
                "aciklama",
                "barkod",
                "urun_adi",
                "miktar",
                "birim",
                "net_birim_fiyat",
                "satir_tutari",
                "pb",
                "doviz",
                "kur",
                "borc",
                "alacak",
                "bakiye",
                "gun",
            )
            tablo = tk.ttk.Treeview(root, columns=kolonlar, show="headings")
            host = MagicMock()
            host.hareket_tablosu = tablo
            host._hareket_urun_sutunlari_acik = True
            host._hareket_urun_kolonlar = (
                "barkod",
                "urun_adi",
                "miktar",
                "birim",
                "net_birim_fiyat",
                "satir_tutari",
                "pb",
                "doviz",
                "kur",
            )
            host._hareket_temel_kolonlar = (
                "tarih",
                "tur",
                "belge",
                "aciklama",
                "borc",
                "alacak",
                "bakiye",
                "gun",
            )
            host._hareket_baslik_isaretlerini_guncelle = MagicMock()
            host._hareket_sutunlari_sigdir = MagicMock()
            host._hareket_gorunum_uygula = types.MethodType(
                CariDialog._hareket_gorunum_uygula, host
            )
            host._hareket_gorunum_uygula()
            goster = tuple(tablo.cget("displaycolumns"))
            for k in ("barkod", "urun_adi", "miktar", "birim", "net_birim_fiyat", "satir_tutari", "bakiye"):
                self.assertIn(k, goster)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
