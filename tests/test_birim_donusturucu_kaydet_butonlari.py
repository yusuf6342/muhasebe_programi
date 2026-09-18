"""Barkod Birim Dönüştürücü — alt çubuk Kaydet düğmeleri.

Çalıştırma: python tests/test_birim_donusturucu_kaydet_butonlari.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class BirimKaydetButonlariTest(unittest.TestCase):
    def test_metodlar_ve_varsayilan_kapat(self):
        from stok_ui import StokBirimlerDialog
        import inspect

        self.assertTrue(callable(StokBirimlerDialog._kaydet_acik_kal))
        self.assertTrue(callable(StokBirimlerDialog._kaydet_ve_kapat))
        self.assertTrue(callable(StokBirimlerDialog.kaydet))
        self.assertTrue(callable(StokBirimlerDialog._f1_kaydet))
        sig = inspect.signature(StokBirimlerDialog.kaydet)
        self.assertFalse(sig.parameters["kapat"].default)

    def test_kaydet_acik_kal_kapat_false(self):
        dlg = MagicMock()
        dlg.kaydet = MagicMock(return_value=True)
        from stok_ui import StokBirimlerDialog

        StokBirimlerDialog._kaydet_acik_kal(dlg)
        dlg.kaydet.assert_called_once_with(kapat=False)

    def test_kaydet_ve_kapat_kapat_true(self):
        dlg = MagicMock()
        dlg.kaydet = MagicMock(return_value=True)
        from stok_ui import StokBirimlerDialog

        StokBirimlerDialog._kaydet_ve_kapat(dlg)
        dlg.kaydet.assert_called_once_with(kapat=True)

    def test_pasiflestir_uc_dugme(self):
        dlg = MagicMock()
        dlg.btn_kaydet = MagicMock()
        dlg.btn_kaydet_kapat = MagicMock()
        dlg.btn_vazgec = MagicMock()
        dlg._kayit_devam = False
        dlg._f1_kilit = False
        from stok_ui import StokBirimlerDialog

        StokBirimlerDialog._kayit_pasiflestir(dlg, True)
        dlg.btn_kaydet.configure.assert_called_with(state="disabled")
        dlg.btn_kaydet_kapat.configure.assert_called_with(state="disabled")
        dlg.btn_vazgec.configure.assert_called_with(state="disabled")
        self.assertTrue(dlg._kayit_devam)
        self.assertTrue(dlg._f1_kilit)

    def test_f1_kaydet_kapat_false(self):
        dlg = MagicMock()
        dlg.winfo_exists.return_value = True
        dlg._kayit_devam = False
        dlg._f1_kilit = False
        dlg._kapatiliyor = False
        dlg.btn_kaydet = MagicMock()
        dlg.btn_kaydet.cget.return_value = "normal"
        odak = MagicMock()
        odak.master = dlg
        dlg.focus_get.return_value = odak
        dlg.kaydet = MagicMock(return_value=True)
        dlg.after = MagicMock()
        from stok_ui import StokBirimlerDialog

        with patch.object(StokBirimlerDialog, "_kayit_aktif_mi", return_value=True):
            sonuc = StokBirimlerDialog._f1_kaydet(dlg)
        self.assertEqual(sonuc, "break")
        dlg.kaydet.assert_called_once_with(kapat=False)

    def test_stok_karti_kaydet_ayri(self):
        """Ana Stok Kartı kaydet metodu StokBirimlerDialog.kaydet değil."""
        from stok_ui import StokBirimlerDialog, StokKartiDialog

        self.assertIsNot(StokKartiDialog.kaydet, StokBirimlerDialog.kaydet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
