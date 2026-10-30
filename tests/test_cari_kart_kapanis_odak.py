"""Müşteri kartı kapanışında ana uygulama / Satışlar geri yükleme."""
from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import MagicMock

from cari_kart_ui import CariDialog


class CariKartKapanisOdakTest(unittest.TestCase):
    def test_ana_uygulamayi_geri_yukle_iconic_ve_satislar(self):
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.state.return_value = "iconic"
        CariDialog._ana_uygulamayi_geri_yukle(app, satislar=True)
        app.deiconify.assert_called()
        app.lift.assert_called()
        app.focus_force.assert_called()
        app.sayfa_goster.assert_called_with("satislar", ust_duzey=True)

    def test_ana_uygulamayi_geri_yukle_tedarikci_sayfa_degistirmez(self):
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.state.return_value = "normal"
        CariDialog._ana_uygulamayi_geri_yukle(app, satislar=False)
        app.deiconify.assert_not_called()
        app.lift.assert_called()
        app.sayfa_goster.assert_not_called()

    def test_karti_kapat_iptal_acik_birakir(self):
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = tk.Toplevel(root)
            dlg.tedarikci_modu = False
            dlg._donus_ana_menu = False
            dlg._kapatmadan_once_onay = MagicMock(return_value=False)
            dlg.destroy = MagicMock()
            # Metodları sınıftan bağla
            ok = CariDialog._karti_kapat(dlg, onay=True, ana_menuye_don=True)
            self.assertFalse(ok)
            dlg.destroy.assert_not_called()
            dlg.destroy()
        finally:
            root.destroy()

    def test_karti_kapat_basarili_donus_bayragi(self):
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = tk.Toplevel(root)
            dlg.tedarikci_modu = False
            dlg._donus_ana_menu = False
            dlg._kapatmadan_once_onay = MagicMock(return_value=True)
            destroyed = []

            def _d():
                destroyed.append(dlg._donus_ana_menu)
                tk.Toplevel.destroy(dlg)

            dlg.destroy = _d
            ok = CariDialog._karti_kapat(dlg, onay=True, ana_menuye_don=True)
            self.assertTrue(ok)
            self.assertEqual(destroyed, [True])
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
