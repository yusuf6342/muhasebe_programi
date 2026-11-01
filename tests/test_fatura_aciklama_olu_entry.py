"""Kaydet: stub destroy sonrası ölü aciklama Entry → invalid command name."""

from __future__ import annotations

import inspect
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch


class FaturaAciklamaOluEntryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        import sys

        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    def test_ek_fatura_kaynakta_olu_entry_yenileme_var(self):
        from app import SatisFaturasiDialog

        src = inspect.getsource(SatisFaturasiDialog._ek_fatura_bilgileri)
        self.assertIn("winfo_exists", src)
        self.assertIn('girdiler["aciklama"]', src)
        self.assertIn("_ack_canli", src)
        src_kayit = inspect.getsource(SatisFaturasiDialog._fatura_kayit_verilerini_topla)
        self.assertIn("_aciklama_metni_oku", src_kayit)

    def test_aciklama_metni_oku_olu_entry_yok_sayar(self):
        root = tk.Tk()
        root.withdraw()
        try:
            from app import SatisFaturasiDialog

            with patch.object(SatisFaturasiDialog, "__init__", lambda self, *a, **k: None):
                dlg = SatisFaturasiDialog.__new__(SatisFaturasiDialog)
            stub = tk.Frame(root)
            olu = tk.Entry(stub)
            dlg.girdiler = {"aciklama": olu}
            dlg._fatura_ust_aciklama = tk.Text(root, height=2, width=10)
            dlg._fatura_ust_aciklama.insert("1.0", "ust-metin")
            stub.destroy()
            with self.assertRaises(tk.TclError):
                olu.get()
            self.assertEqual(dlg._aciklama_metni_oku(), "ust-metin")
        finally:
            root.destroy()

    def test_olu_entry_yeniden_kurulunca_get_calisir(self):
        """_ek_fatura_bilgileri ile aynı canlılık kontrolü."""
        root = tk.Tk()
        root.withdraw()
        try:
            parent = tk.Frame(root)
            stub = tk.Frame(parent)
            olu = tk.Entry(stub)
            olu.insert(0, "eski")
            girdiler = {"aciklama": olu}
            stub.destroy()
            eski = girdiler.get("aciklama")
            canli = False
            if eski is not None:
                try:
                    canli = bool(eski.winfo_exists())
                except tk.TclError:
                    canli = False
            self.assertFalse(canli)
            if not canli:
                girdiler["aciklama"] = tk.Entry(parent)
            self.assertTrue(girdiler["aciklama"].winfo_exists())
            self.assertEqual(girdiler["aciklama"].get(), "")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
