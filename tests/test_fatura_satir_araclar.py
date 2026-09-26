"""Satış faturası satır araçları — çoğalt, taşı, sil, boş mesaj.

Çalıştırma: .venv\\Scripts\\python.exe -m unittest tests.test_fatura_satir_araclar -v
"""

from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fatura_satir_araclar as araclar


def _satir(**kw):
    base = {
        "urun_kodu": "U1",
        "urun_adi": "Ürün 1",
        "miktar": "2",
        "birim": "Adet",
        "birim_satis_fiyati": "100",
        "iskonto_orani": "10",
        "iskonto_orani_2": "0",
        "iskonto_orani_3": "0",
        "kdv_orani": "20",
        "aciklama": "not",
        "barkod": "111",
        "satir_para_birimi": "TRY",
        "manuel_fiyat": False,
    }
    base.update(kw)
    return base


def _dialog(satirlar=None):
    d = MagicMock()
    d.satirlar = list(satirlar or [])
    d._fatura_kilitli = False
    d._duzenlenen_satir = None
    d.fatura = None
    d.depo.get.return_value = "ANA DEPO"
    d._satir_listesini_yenile = MagicMock()
    d._toplamlari_guncelle = MagicMock()
    d.satir_tablosu = MagicMock()
    d.satir_tablosu.selection.return_value = ()
    d.satir_tablosu.yview.return_value = (0.0, 1.0)
    d._fatura_bos_mesaj = None
    return d


class CogaltTasiSilTest(unittest.TestCase):
    @patch("fatura_satir_araclar.messagebox")
    @patch("fatura_satir_araclar.temel_miktar", return_value=Decimal("1"))
    def test_cogalt_miktar_1(self, _tm, mb):
        d = _dialog([_satir(miktar="5")])
        d.satir_tablosu.selection.return_value = ("0",)
        with patch("fatura_barkod_ui._eksi_stok_kontrol"), patch(
            "fatura_barkod_ui._urun_talep_toplami", return_value=Decimal("5")
        ):
            araclar.satir_cogalt(d)
        self.assertEqual(len(d.satirlar), 2)
        self.assertEqual(d.satirlar[1]["miktar"], "1")
        self.assertEqual(d.satirlar[1]["urun_kodu"], "U1")
        self.assertEqual(d.satirlar[1]["iskonto_orani"], "10")

    def test_uste_alta_tasi(self):
        d = _dialog([_satir(urun_kodu="A"), _satir(urun_kodu="B"), _satir(urun_kodu="C")])
        d.satir_tablosu.selection.return_value = ("1",)
        araclar.satir_uste_tasi(d)
        self.assertEqual([s["urun_kodu"] for s in d.satirlar], ["B", "A", "C"])
        d.satir_tablosu.selection.return_value = ("0",)
        araclar.satir_alta_tasi(d)
        self.assertEqual([s["urun_kodu"] for s in d.satirlar], ["A", "B", "C"])

    @patch("fatura_satir_araclar.messagebox")
    @patch("fatura_satir_araclar._audit_satir_sil")
    def test_sil_onay_ve_vazgec(self, _audit, mb):
        d = _dialog([_satir(), _satir(urun_kodu="U2")])
        d.satir_tablosu.selection.return_value = ("0",)
        mb.askyesno.return_value = False
        araclar.satir_sil(d)
        self.assertEqual(len(d.satirlar), 2)
        mb.askyesno.return_value = True
        araclar.satir_sil(d)
        self.assertEqual(len(d.satirlar), 1)
        self.assertEqual(d.satirlar[0]["urun_kodu"], "U2")

    @patch("fatura_satir_araclar.messagebox")
    @patch("fatura_satir_araclar._audit_satir_sil")
    def test_toplu_sil(self, _audit, mb):
        d = _dialog([_satir(urun_kodu="A"), _satir(urun_kodu="B"), _satir(urun_kodu="C")])
        d.satir_tablosu.selection.return_value = ("0", "2")
        mb.askyesno.return_value = True
        araclar.satir_sil(d)
        self.assertEqual([s["urun_kodu"] for s in d.satirlar], ["B"])

    @patch("fatura_satir_araclar.messagebox")
    @patch("fatura_satir_araclar._audit_satir_sil")
    def test_isaretli_satirlari_sil(self, _audit, mb):
        """Checkbox (☐/☑) işaretleri Treeview seçiminden önce gelir."""
        d = _dialog([_satir(urun_kodu="A"), _satir(urun_kodu="B"), _satir(urun_kodu="C")])
        d._satir_isaretleri = {0, 2}
        d.satir_tablosu.selection.return_value = ("1",)  # yok sayılmalı
        mb.askyesno.return_value = True
        araclar.satir_sil(d)
        self.assertEqual([s["urun_kodu"] for s in d.satirlar], ["B"])
        self.assertEqual(d._satir_isaretleri, set())

    @patch("fatura_satir_araclar.messagebox")
    def test_iskontoyu_temizle(self, mb):
        d = _dialog([_satir(iskonto_orani="15", iskonto_orani_2="5")])
        d.satir_tablosu.selection.return_value = ("0",)
        araclar.iskontoyu_temizle(d)
        self.assertEqual(d.satirlar[0]["iskonto_orani"], "0")
        self.assertEqual(d.satirlar[0]["iskonto_orani_2"], "0")


class BosMesajTest(unittest.TestCase):
    def test_bos_mesaj_goster_gizle(self):
        d = _dialog([])
        parent = MagicMock()
        d.satir_tablosu.master = parent
        with patch("fatura_satir_araclar.tk.Label") as Lbl:
            lbl = MagicMock()
            Lbl.return_value = lbl
            araclar._bos_mesaj_guncelle(d)
            self.assertTrue(Lbl.called)
            args, kwargs = Lbl.call_args
            self.assertIn("barkod", kwargs.get("text", args[1] if len(args) > 1 else ""))
            lbl.place.assert_called()
        d.satirlar = [_satir()]
        d._fatura_bos_mesaj = MagicMock()
        araclar._bos_mesaj_guncelle(d)
        d._fatura_bos_mesaj.place_forget.assert_called()


class MetinOdakTest(unittest.TestCase):
    def test_entry_odakta_kisayol_yok(self):
        d = MagicMock()
        entry = MagicMock()
        entry.winfo_class.return_value = "TEntry"
        d.focus_get.return_value = entry
        d._satir_hucre_editor = None
        self.assertTrue(araclar._metin_odakli_mi(d))


class KolonKritikTest(unittest.TestCase):
    def test_kritik_kolonlar(self):
        from app import FATURA_KRITIK_KOLONLAR

        self.assertIn("miktar", FATURA_KRITIK_KOLONLAR)
        self.assertIn("birim", FATURA_KRITIK_KOLONLAR)
        self.assertIn("toplam", FATURA_KRITIK_KOLONLAR)


if __name__ == "__main__":
    unittest.main()
