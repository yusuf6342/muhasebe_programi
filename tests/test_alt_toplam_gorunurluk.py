"""Alt toplam talimatı: alış teklifi / konsinye / alış fatura band görünürlüğü."""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AltToplamGorunurlukTest(unittest.TestCase):
    def test_tedarikci_teklif_toplam_bandi(self):
        from satin_alma_ui import TedarikciTeklifDialog

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = TedarikciTeklifDialog(root)
            dlg.update_idletasks()
            self.assertEqual(dlg._teklif_toplam_lbl.winfo_manager(), "pack")
            self.assertGreater(dlg._teklif_toplam_lbl.winfo_reqheight(), 0)
            dlg.satirlar = [
                {
                    "cari_id": 1,
                    "urun_kodu": "A",
                    "urun_adi": "1",
                    "miktar": Decimal("1"),
                    "birim_fiyat": Decimal("65"),
                    "nakliye_tutari": Decimal("0"),
                },
                {
                    "cari_id": 1,
                    "urun_kodu": "B",
                    "urun_adi": "2",
                    "miktar": Decimal("1"),
                    "birim_fiyat": Decimal("8.5"),
                    "nakliye_tutari": Decimal("0"),
                },
            ]
            dlg._toplamlari_guncelle()
            metin = dlg._teklif_toplam_lbl.cget("text")
            self.assertIn("73", metin)
            self.assertIn("Teklif Toplamı", metin)
            dlg.destroy()
        finally:
            root.destroy()

    def test_konsinye_teslim_toplam_bandi(self):
        from konsinye_ui import _TeslimDialog
        from database.konsinye_service import YON_ALINAN

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = _TeslimDialog(root, yon=YON_ALINAN)
            dlg.update_idletasks()
            self.assertEqual(dlg._konsinye_toplam_lbl.winfo_manager(), "pack")
            self.assertGreater(dlg._konsinye_toplam_lbl.winfo_reqheight(), 0)
            dlg.satirlar = [
                {"stok_kodu": "A", "miktar": Decimal("2"), "birim_fiyat": Decimal("10")},
                {"stok_kodu": "B", "miktar": Decimal("1"), "birim_fiyat": Decimal("5")},
            ]
            dlg._toplamlari_guncelle()
            metin = dlg._konsinye_toplam_lbl.cget("text")
            self.assertIn("25", metin)
            self.assertIn("Tahmini Tutar", metin)
            dlg.destroy()
        finally:
            root.destroy()

    def test_hizmet_ve_irsaliye_band_altta(self):
        from hizmet_fatura_ui import HizmetFaturaDialog
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

        root = tk.Tk()
        root.withdraw()
        try:
            h = HizmetFaturaDialog(root)
            h.update_idletasks()
            self.assertEqual(h._hizmet_toplam_band.winfo_manager(), "pack")
            self.assertEqual(h._hizmet_toplam_band.pack_info()["side"], "bottom")
            h.destroy()

            i = SatisIrsaliyesiDialog(root)
            i.update_idletasks()
            self.assertEqual(i._irsaliye_toplam_band.winfo_manager(), "pack")
            self.assertEqual(i._irsaliye_toplam_band.pack_info()["side"], "bottom")
            i.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
