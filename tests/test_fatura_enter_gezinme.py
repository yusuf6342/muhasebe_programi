"""Fatura satır Enter gezinme / otomatik odak testleri."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fatura_satir_hucre_edit import (
    DUZENLENEBILIR_KOLONLAR,
    EDITABLE_COLUMN_ORDER,
    find_next_editable_cell,
    ilk_duzenlenebilir_kolon,
    kolon_duzenlenebilir_mi,
)


class FakeTree:
    def __init__(self, columns, display=None):
        self._columns = columns
        self._display = display if display is not None else columns

    def __getitem__(self, key):
        if key == "displaycolumns":
            return self._display
        if key == "columns":
            return self._columns
        raise KeyError(key)


class FakeDialog:
    def __init__(self, satirlar, display=None):
        cols = list(EDITABLE_COLUMN_ORDER) + ["urun_kodu", "urun_adi", "toplam"]
        self.satirlar = satirlar
        self.satir_tablosu = FakeTree(cols, display)
        self._fatura_kilitli = False


class EnterGezinmeTest(unittest.TestCase):
    def test_sira_miktar_ilk(self):
        self.assertEqual(EDITABLE_COLUMN_ORDER[0], "miktar")
        self.assertIn("miktar", DUZENLENEBILIR_KOLONLAR)

    @patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True)
    @patch("fatura_satir_hucre_edit.stok_aktif_birimleri", return_value=["Adet"])
    def test_gizli_kolon_atla(self, _birim, _yetki):
        satir = {
            "urun_kodu": "X",
            "miktar": "1",
            "birim": "Adet",
            "para_birimi": "TRY",
            "satir_para_birimi": "TRY",
        }
        dlg = FakeDialog([satir], display=("miktar", "fiyat", "kdv", "aciklama"))
        self.assertTrue(kolon_duzenlenebilir_mi(dlg, 0, "miktar"))
        self.assertFalse(kolon_duzenlenebilir_mi(dlg, 0, "birim"))  # gizli
        self.assertFalse(kolon_duzenlenebilir_mi(dlg, 0, "kur"))  # TRY
        nxt = find_next_editable_cell(dlg, 0, "miktar", direction=1)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt[1], "fiyat")

    @patch("fatura_satir_hucre_edit.stok_aktif_birimleri", return_value=["Adet"])
    def test_son_alandan_sonraki_satir(self, _birim):
        s1 = {"urun_kodu": "A", "miktar": "1", "birim": "Adet", "para_birimi": "TRY"}
        s2 = {"urun_kodu": "B", "miktar": "2", "birim": "Adet", "para_birimi": "TRY"}
        dlg = FakeDialog([s1, s2], display=list(EDITABLE_COLUMN_ORDER))
        nxt = find_next_editable_cell(dlg, 0, "aciklama", direction=1)
        self.assertEqual(nxt, (1, "miktar"))

    @patch("fatura_satir_hucre_edit.stok_aktif_birimleri", return_value=["Adet"])
    def test_son_satir_son_alan_none(self, _birim):
        s1 = {"urun_kodu": "A", "miktar": "1", "birim": "Adet", "para_birimi": "TRY"}
        dlg = FakeDialog([s1], display=list(EDITABLE_COLUMN_ORDER))
        nxt = find_next_editable_cell(dlg, 0, "aciklama", direction=1)
        self.assertIsNone(nxt)

    @patch("fatura_satir_hucre_edit.stok_aktif_birimleri", return_value=["Adet"])
    def test_geri_gezinme(self, _birim):
        s1 = {"urun_kodu": "A", "miktar": "1", "birim": "Adet", "para_birimi": "TRY"}
        s2 = {"urun_kodu": "B", "miktar": "2", "birim": "Adet", "para_birimi": "TRY"}
        dlg = FakeDialog([s1, s2], display=("miktar", "fiyat", "aciklama"))
        nxt = find_next_editable_cell(dlg, 1, "miktar", direction=-1)
        self.assertEqual(nxt, (0, "aciklama"))

    def test_ilk_kolon(self):
        satir = {"urun_kodu": "X", "miktar": "1", "birim": "Adet", "para_birimi": "TRY"}
        dlg = FakeDialog([satir], display=("urun_adi", "miktar", "kdv"))
        self.assertEqual(ilk_duzenlenebilir_kolon(dlg, 0), "miktar")

    @patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=False)
    @patch("fatura_satir_hucre_edit.stok_aktif_birimleri", return_value=["Adet"])
    def test_fiyat_yetki_yok(self, _birim, _yetki):
        satir = {"urun_kodu": "X", "miktar": "1", "birim": "Adet", "para_birimi": "TRY"}
        dlg = FakeDialog([satir], display=list(EDITABLE_COLUMN_ORDER))
        self.assertFalse(kolon_duzenlenebilir_mi(dlg, 0, "fiyat"))
        nxt = find_next_editable_cell(dlg, 0, "miktar", direction=1)
        self.assertIsNotNone(nxt)
        self.assertNotEqual(nxt[1], "fiyat")


if __name__ == "__main__":
    unittest.main()
