"""Stok Kartı — Kaydet düğmesi görünür, 3D kırmızı; Stok Adı 11 punto kalın.

Çalıştırma: python tests/test_stok_karti_kaydet_gorunur.py
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_stok_karti_ozet_sirasi as taban  # noqa: E402

from database.stok_service import StokService  # noqa: E402
from stok_ui import StokKartiDialog, geometriyi_alana_sigdir  # noqa: E402

CALISMA_ALANI = (0, 0, 1920, 1040)


class GeometriSigdirmaTest(unittest.TestCase):
    def test_gorev_cubugunu_asan_kayit_kirpilir(self):
        # Kullanıcının kayıtlı boyutu: 1057 + başlık çubuğu > 1040 → alt çubuk görev çubuğu altında kalıyordu
        self.assertEqual(geometriyi_alana_sigdir("1920x1057+0+0", CALISMA_ALANI), "1904x1000+0+0")

    def test_sigan_kayit_degismez(self):
        self.assertEqual(geometriyi_alana_sigdir("1280x860+100+50", CALISMA_ALANI), "1280x860+100+50")

    def test_ekran_disina_tasan_konum_iceri_alinir(self):
        self.assertEqual(geometriyi_alana_sigdir("1280x860+-8+-8", CALISMA_ALANI), "1280x860+0+0")
        self.assertEqual(geometriyi_alana_sigdir("1280x860+900+400", CALISMA_ALANI), "1280x860+632+140")

    def test_bozuk_kayit_aynen_doner(self):
        self.assertEqual(geometriyi_alana_sigdir("zoomed", CALISMA_ALANI), "zoomed")


class StokKartiKaydetGorunurTest(unittest.TestCase):
    setUp = taban.StokKartiOzetSirasiTest.setUp
    tearDown = taban.StokKartiOzetSirasiTest.tearDown

    def _dialog_ac(self, root, geometri):
        stok = StokService.stok_getir(self.stok_id)
        with patch.object(StokKartiDialog, "_pencere_boyutunu_ayarla", lambda self: self.geometry(geometri)):
            dlg = StokKartiDialog(root, stok=stok)
        dlg.update()
        return dlg

    def test_kaydet_3d_kirmizi_ve_pencere_icinde(self):
        # Kök gizlenirse transient kart da gizli kalır; yerleşim ölçülemez
        root = tk.Tk()
        root.geometry("1x1+0+0")
        try:
            dlg = self._dialog_ac(root, geometriyi_alana_sigdir("1920x1057+0+0", CALISMA_ALANI))
            btn = dlg.kaydet_btn
            self.assertEqual(btn.cget("bg").upper(), "#C62828")
            self.assertEqual(btn.cget("fg").upper(), "#FFFFFF")
            self.assertEqual(str(btn.cget("relief")), "raised")
            self.assertGreaterEqual(int(btn.cget("bd")), 3)
            self.assertTrue(dlg.winfo_ismapped())
            self.assertTrue(btn.winfo_ismapped())
            alt_kenar = btn.winfo_rooty() + btn.winfo_height()
            self.assertLessEqual(alt_kenar, dlg.winfo_rooty() + dlg.winfo_height())
            self.assertLessEqual(alt_kenar, CALISMA_ALANI[1] + CALISMA_ALANI[3])
            dlg.destroy()
        finally:
            root.destroy()

    def test_stok_adi_11_punto_kalin(self):
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = self._dialog_ac(root, "1280x860+0+0")
            yazi = tkfont.Font(root=dlg, font=dlg.alanlar["stok_adi"].cget("font"))
            self.assertEqual(abs(int(yazi.actual("size"))), 11)
            self.assertEqual(yazi.actual("weight"), "bold")
            self.assertEqual(dlg.alanlar["stok_adi"].get(), "Özet Ürün")
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
