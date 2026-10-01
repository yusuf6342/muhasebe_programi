"""Satış faturası "Satır Sil": veri modeli, tablo, hücre editörü, vurgulu etiketler ve odak.

Gerçek SatisFaturasiDialog (görünmez pencere) + geçici test veritabanı kullanır.
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import get_session
from database.models.stok import StokKarti
from tests import test_uzlasma_net_cari as _uz


def _satir(kod, ad, miktar="2", fiyat="100"):
    return {
        "urun_kodu": kod, "urun_adi": ad, "miktar": miktar, "birim": "Adet",
        "birim_satis_fiyati": fiyat, "kdv_orani": "20", "iskonto_orani": "0",
        "iskonto_orani_2": "0", "iskonto_orani_3": "0", "satir_para_birimi": "TRY", "kur": "1",
    }


class FaturaSatirSilEkranTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)
        with get_session() as s:
            s.add(StokKarti(stok_kodu="U002", stok_adi="Sandalye", birim="Adet", aktif=True, is_deleted=False))
        from database.alis_faturasi_service import AlisFaturasiService

        AlisFaturasiService.kaydet(
            {"fatura_tarihi": date(2026, 1, 6), "vade_tarihi": date(2026, 1, 6), "cari_id": self.tedarikci_id,
             "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U002", "urun_adi": "Sandalye", "miktar": Decimal("10"), "birim": "Adet",
              "birim_fiyat": Decimal("50"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "lot_no": "LOT-2"}],
        )
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _uz._sokum(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.geometry("+20+20")
        self.root.attributes("-alpha", 0.0)
        self._ui_yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
            patch("fatura_satir_araclar.messagebox.askyesno", return_value=True),
        ]
        for y in self._ui_yamalar:
            y.start()
        self.dlg = None

    def tearDown(self):
        try:
            if self.dlg is not None:
                self.dlg.destroy()
        except Exception:
            pass
        for y in reversed(self._ui_yamalar):
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        _uz._sokum(self)

    # —— yardımcılar ——
    def _ac(self, satirlar=None, fatura=None):
        from app import CariService, SatisFaturasiDialog

        if fatura is not None:
            self.dlg = SatisFaturasiDialog(self.root, fatura=fatura)
        else:
            self.dlg = SatisFaturasiDialog(self.root, cari=CariService.getir(self.musteri_id))
        self.dlg.geometry("1400x800+20+20")
        self.dlg.attributes("-alpha", 0.0)
        if satirlar is not None:
            self.dlg.satirlar = satirlar
            self.dlg._satir_listesini_yenile()
            self.dlg._toplamlari_guncelle()
        self._pompala()
        return self.dlg

    def _pompala(self, tur=8):
        for _ in range(tur):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _sec(self, idx):
        t = self.dlg.satir_tablosu
        t.selection_set(str(idx))
        t.focus(str(idx))
        self._pompala()

    def _sil(self):
        from fatura_satir_araclar import satir_sil

        satir_sil(self.dlg)
        self._pompala()

    def _gorunen_etiket_metinleri(self):
        t = self.dlg.satir_tablosu
        return [
            str(w.cget("text")) for w in t.winfo_children()
            if isinstance(w, tk.Label) and w.winfo_ismapped()
        ]

    def _veri_satirlari(self):
        return [i for i in self.dlg.satir_tablosu.get_children() if i != "__yeni__"]

    def _ust_bilgi(self):
        d = self.dlg
        return (d._secili_musteri().id, d.girdiler["siparis_tarihi"].get(), d.depo.get())

    # —— senaryolar ——
    def test_iki_urunden_birini_silmek_digerini_korur(self):
        self._ac([_satir("U001", "Masa"), _satir("U002", "Sandalye", fiyat="50")])
        ust = self._ust_bilgi()
        self._sec(0)
        self._sil()
        self.assertEqual([s["urun_kodu"] for s in self.dlg.satirlar], ["U002"])
        self.assertEqual(self._veri_satirlari(), ["0"])
        self.assertEqual(str(self.dlg.satir_tablosu.set("0", "sira")), "1")
        metinler = self._gorunen_etiket_metinleri()
        self.assertNotIn("Masa", metinler)
        self.assertIn("Sandalye", metinler)
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("120.00"))  # 2 × 50 + %20
        self.assertEqual(self._ust_bilgi(), ust, "müşteri / tarih / depo korunur")
        self.assertEqual(self.dlg.satir_tablosu.selection(), ())

    def test_son_satir_silinince_eski_bilgiler_kaybolur_yeni_urun_eklenir(self):
        self._ac([_satir("U001", "Masa")])
        self._sec(0)
        self._sil()
        self.assertEqual(self.dlg.satirlar, [])
        self.assertEqual(self._veri_satirlari(), [])
        metinler = self._gorunen_etiket_metinleri()
        self.assertNotIn("Masa", metinler)
        self.assertFalse(any(m.startswith("2") for m in metinler), metinler)
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("0.00"))
        self.assertIsNone(getattr(self.dlg, "_satir_hucre_editor", None))
        giris = self.dlg._satir_ici_giris
        self.assertTrue(giris.acik_mi(), "silme sonrası ürün arama alanı açık olmalı")
        self.assertIs(self.dlg.focus_get(), giris.entry)
        giris.urun_ekle_fn(("U002", "Sandalye", "Adet", "50", "1", "Stok Kartı", "20", None), None)
        self._pompala()
        self.assertEqual([s["urun_kodu"] for s in self.dlg.satirlar], ["U002"])
        self.assertIn("Sandalye", self._gorunen_etiket_metinleri())

    def test_kdv_kutusu_acikken_silmek_kutuyu_ve_satiri_temizler(self):
        from fatura_satir_hucre_edit import kdv_hucre_duzenle

        self._ac([_satir("U001", "Masa"), _satir("U002", "Sandalye", fiyat="50")])
        self._sec(1)
        kdv_hucre_duzenle(self.dlg, idx=1)
        self._pompala()
        editor = self.dlg._satir_hucre_editor
        self.assertIsNotNone(editor)
        self._sil()
        self.assertIsNone(self.dlg._satir_hucre_editor)
        self.assertFalse(editor.winfo_exists())
        self.assertEqual([s["urun_kodu"] for s in self.dlg.satirlar], ["U001"])
        metinler = self._gorunen_etiket_metinleri()
        self.assertNotIn("Sandalye", metinler)
        self.assertIn("Masa", metinler)
        self.assertFalse(
            [w for w in self.dlg.satir_tablosu.winfo_children()
             if isinstance(w, __import__("tkinter.ttk").ttk.Combobox) and w.winfo_ismapped()],
            "KDV seçim kutusu kalmamalı",
        )

    def test_art_arda_silme_ve_cok_isaretli_silme(self):
        self._ac([_satir("U001", "Masa"), _satir("U002", "Sandalye", fiyat="50"),
                  _satir("U001", "Masa 2", miktar="1"), _satir("U002", "Sandalye 2", miktar="1")])
        self.dlg._satir_isaretleri = {0, 2}
        self.dlg._satir_listesini_yenile()
        self._pompala()
        self._sil()
        self.assertEqual([s["urun_adi"] for s in self.dlg.satirlar], ["Sandalye", "Sandalye 2"])
        self.assertEqual(self.dlg._satir_isaretleri, set())
        self._sec(1)
        self._sil()
        self.assertEqual([s["urun_adi"] for s in self.dlg.satirlar], ["Sandalye"])
        self._sec(0)
        self._sil()
        self.assertEqual(self.dlg.satirlar, [])
        self.assertEqual(self._veri_satirlari(), [])

    def test_secim_yoksa_silmez_uyari_verir(self):
        self._ac([_satir("U001", "Masa"), _satir("U002", "Sandalye", fiyat="50")])
        t = self.dlg.satir_tablosu
        t.selection_remove(*t.selection())
        t.focus("")
        with patch("fatura_satir_araclar.messagebox.showinfo") as uyari:
            self._sil()
        uyari.assert_called_once()
        self.assertEqual(len(self.dlg.satirlar), 2)

    def test_kaydet_yeniden_ac_silinen_satir_gelmez_tutar_korunur(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self._ac([_satir("U001", "Masa", fiyat="1000"), _satir("U002", "Sandalye", fiyat="50")])
        veriler, satirlar = self.dlg._fatura_kayit_verilerini_topla()
        f = SatisFaturasiService.kaydet(veriler, satirlar)
        self.dlg.destroy()
        self._ac(fatura=SatisFaturasiService.getir(f.id))
        self.assertEqual(len(self.dlg.satirlar), 2)
        self._sec(0)
        self._sil()
        veriler, satirlar = self.dlg._fatura_kayit_verilerini_topla()
        SatisFaturasiService.kaydet(veriler, satirlar, f.id)
        self.dlg.destroy()
        yeniden = SatisFaturasiService.getir(f.id)
        self.assertEqual([s.urun_kodu for s in yeniden.satirlar], ["U002"])
        self.assertEqual(Decimal(str(yeniden.satirlar[0].birim_fiyat)), Decimal("50"))
        self.assertEqual(Decimal(str(yeniden.satirlar[0].miktar)), Decimal("2"))
        self.assertEqual(Decimal(str(yeniden.tl_brut_toplam)), Decimal("120.00"))
        self._ac(fatura=yeniden)
        self.assertEqual([s["urun_kodu"] for s in self.dlg.satirlar], ["U002"])

    def test_kaydetmeden_once_silinen_satir_kayda_girmez(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self._ac([_satir("U001", "Masa", fiyat="1000"), _satir("U002", "Sandalye", fiyat="50")])
        self._sec(0)
        self._sil()
        veriler, satirlar = self.dlg._fatura_kayit_verilerini_topla()
        f = SatisFaturasiService.kaydet(veriler, satirlar)
        self.dlg.destroy()
        kayit = SatisFaturasiService.getir(f.id)
        self.assertEqual([s.urun_kodu for s in kayit.satirlar], ["U002"])
        self.assertEqual(Decimal(str(kayit.tl_genel_toplam)), Decimal("120.00"))
        self._ac(fatura=kayit)
        self.assertEqual([s["urun_kodu"] for s in self.dlg.satirlar], ["U002"])
        self.assertNotIn("Masa", self._gorunen_etiket_metinleri())


class SatirSilDugmesiTest(unittest.TestCase):
    def test_ust_seridde_secili_satiri_sil_dugmesi_yok(self):
        kaynak = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('"Seçili Satırı Sil",\n            lambda: satir_sil(self)', kaynak)
        self.assertIn('text="Satır Sil",\n            command=self.satir_sil', kaynak)


if __name__ == "__main__":
    unittest.main()
