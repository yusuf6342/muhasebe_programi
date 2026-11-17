"""Satış Faturaları Treeview başlıkları: metin + kontrast (vista beyaz-yazı kaybı)."""
from __future__ import annotations

import tkinter as tk
import unittest
from tkinter import ttk

from app import SATIS_FATURA_LISTE_BASLIKLARI, SATIS_FATURA_LISTE_KOLONLARI
from satis_tema import BEYAZ, LACIVERT, stil_uygula, treeview_stil


class SatisFaturaBaslikGorunurTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def test_stil_uygula_clam_tercih_heading_kontrast(self):
        stil = stil_uygula(root=self.root)
        tema = stil.theme_use()
        self.assertIn(tema, ("clam", "vista", "default", "winnative", "xpnative"))
        # clam varsa tercih edilmeli
        if "clam" in stil.theme_names():
            self.assertEqual(tema, "clam")
        fg = stil.lookup("Satis.Treeview.Heading", "foreground")
        bg = stil.lookup("Satis.Treeview.Heading", "background")
        self.assertTrue(fg)
        self.assertTrue(bg)
        # Beyaz yazı + boyanmayan bg olmamalı: clam'da lacivert zemin
        if tema == "clam":
            self.assertEqual(fg.lower(), BEYAZ.lower())
            self.assertEqual(bg.lower(), LACIVERT.lower())
        elif tema == "vista":
            # Vista yedek: koyu yazı
            self.assertEqual(fg.lower(), LACIVERT.lower())

    def test_treeview_stil_sonrasi_baslik_metinleri_dolu(self):
        stil_uygula(root=self.root)
        tv = ttk.Treeview(self.root, columns=SATIS_FATURA_LISTE_KOLONLARI, show="headings")
        treeview_stil(tv)
        for kolon, baslik in zip(SATIS_FATURA_LISTE_KOLONLARI, SATIS_FATURA_LISTE_BASLIKLARI):
            tv.heading(kolon, text=f"{baslik} ▾")
            tv.column(kolon, width=90, minwidth=50)
        for kolon, baslik in zip(SATIS_FATURA_LISTE_KOLONLARI, SATIS_FATURA_LISTE_BASLIKLARI):
            metin = tv.heading(kolon, "text")
            self.assertTrue(metin, msg=f"{kolon} başlığı boş")
            self.assertIn(baslik, metin, msg=f"{kolon}: {metin!r}")
        # Beklenen ana başlıklar
        for beklenen in (
            "Evrak No",
            "Tarih",
            "Saat",
            "Vade Tarihi",
            "Cari Ünvanı",
            "Cari Bakiye",
            "Sipariş No",
            "İrsaliye No",
            "Depo",
            "Toplam",
            "Kapanan",
            "Kalan",
            "Ödeme Durumu",
            "Satış Personeli",
            "İşlemi Yapan",
        ):
            self.assertTrue(
                any(beklenen in tv.heading(k, "text") for k in SATIS_FATURA_LISTE_KOLONLARI),
                msg=beklenen,
            )
        stil = ttk.Style(self.root)
        fg = (stil.lookup("Satis.Treeview.Heading", "foreground") or "").lower()
        bg = (stil.lookup("Satis.Treeview.Heading", "background") or "").lower()
        # Yeterli karşıtlık: aynı renk olmasın; beyaz yazı ancak koyu zeminde
        self.assertNotEqual(fg, bg)
        if fg in ("#ffffff", "white", BEYAZ.lower()):
            self.assertNotIn(bg, ("#ffffff", "white", "#f3f6f9", BEYAZ.lower()))

    def test_baslik_guncelle_bosaltmaz(self):
        """Filtre işareti güncellemesi başlık metnini silmemeli."""
        from unittest.mock import MagicMock

        app = MagicMock()
        app._fatura_liste_kolonlar = SATIS_FATURA_LISTE_KOLONLARI
        app._fatura_liste_basliklar = dict(
            zip(SATIS_FATURA_LISTE_KOLONLARI, SATIS_FATURA_LISTE_BASLIKLARI)
        )
        app._fatura_liste_filtre = {}
        app._fatura_liste_siralama = None
        tv = ttk.Treeview(self.root, columns=SATIS_FATURA_LISTE_KOLONLARI, show="headings")
        for kolon, baslik in zip(SATIS_FATURA_LISTE_KOLONLARI, SATIS_FATURA_LISTE_BASLIKLARI):
            tv.heading(kolon, text=baslik)
        app.fatura_tablosu = tv

        # Gerçek metodu bağla
        from app import MuhasebeApp

        MuhasebeApp._fatura_basliklari_guncelle(app)
        for kolon, baslik in zip(SATIS_FATURA_LISTE_KOLONLARI, SATIS_FATURA_LISTE_BASLIKLARI):
            self.assertIn(baslik, tv.heading(kolon, "text"))


if __name__ == "__main__":
    unittest.main()
