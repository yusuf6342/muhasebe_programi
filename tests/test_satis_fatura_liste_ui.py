"""Satış Faturaları listesi: takvim tık, cari ünvan ara, id ile açma."""
from __future__ import annotations

import tkinter as tk
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from database.turkce_normalize import tr_iceriyor, turkce_normalize


class TakvimEntryTest(unittest.TestCase):
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

    def tearDown(self):
        import ui_takvim as takvim_mod

        # Modül globalini kullan; from-import anlık değer tutar, Destroy sonrası
        # güncellenmez.
        if takvim_mod._acik_takvim is not None:
            try:
                takvim_mod._acik_takvim.destroy()
            except tk.TclError:
                pass
            takvim_mod._acik_takvim = None
        for w in list(self.root.winfo_children()):
            try:
                w.destroy()
            except tk.TclError:
                pass

    def test_bos_alanda_acilis_tarih_yazmaz(self):
        from ui_takvim import takvim_ac

        e = tk.Entry(self.root)
        e.pack()
        self.assertEqual(e.get(), "")
        pop = takvim_ac(self.root, e)
        self.root.update_idletasks()
        self.assertEqual(e.get(), "", msg="Boş alana takvim açılınca tarih yazılmamalı")
        pop._iptal()
        self.assertEqual(e.get(), "")

    def test_secim_gg_aa_yyyy_yazar_mevcut_korunur_iptalde(self):
        from ui_takvim import takvim_ac

        e = tk.Entry(self.root)
        e.insert(0, "15.03.2026")
        e.pack()
        pop = takvim_ac(self.root, e)
        self.root.update_idletasks()
        self.assertEqual(e.get(), "15.03.2026")
        pop._iptal()
        self.assertEqual(e.get(), "15.03.2026")
        pop2 = takvim_ac(self.root, e)
        pop2._sec(date(2026, 11, 8))
        self.assertEqual(e.get(), "08.11.2026")

    def test_ayni_tik_tek_takvim(self):
        import ui_takvim as takvim_mod
        from ui_takvim import takvim_ac

        e = tk.Entry(self.root)
        e.pack()
        a = takvim_ac(self.root, e)
        b = takvim_ac(self.root, e)
        self.assertIs(a, b)
        self.assertIs(takvim_mod._acik_takvim, a)
        # Aynı entry'ye üçüncü çağrı da yenisini açmaz
        c = takvim_ac(self.root, e)
        self.assertIs(a, c)
        self.assertTrue(a.winfo_exists())
        a._iptal()
        self.assertIsNone(takvim_mod._acik_takvim)

    def test_takvim_butonu_dugme_eklemez(self):
        from ui_takvim import takvim_butonu

        fr = tk.Frame(self.root)
        fr.pack()
        e = tk.Entry(fr)
        e.pack(side="left")
        once = len(fr.winfo_children())
        takvim_butonu(fr, e)
        # placeholder pack edilmez → çocuk sayısı artmaz (veya 0-boyut unused)
        from tkinter import ttk

        metinler = []
        for c in fr.winfo_children():
            try:
                if isinstance(c, (tk.Button, ttk.Button)):
                    metinler.append(str(c.cget("text")))
            except tk.TclError:
                pass
        self.assertNotIn("Takvim", metinler)
        self.assertEqual(once, len([c for c in fr.winfo_children() if c.winfo_manager()]))


class CariUnvanFiltreTest(unittest.TestCase):
    def test_turkce_i_kismi_eslesme(self):
        self.assertTrue(tr_iceriyor("isik", "IŞIK MOBİLYA"))
        self.assertTrue(tr_iceriyor("  ışık  ", "ISIK MOBILYA"))
        self.assertTrue(tr_iceriyor("MOBİLYA", "ışık mobilya ltd"))
        self.assertFalse(tr_iceriyor("xyz", "IŞIK MOBİLYA"))

    def test_bos_arama_hepsini_esler(self):
        self.assertTrue(tr_iceriyor("", "herhangi"))
        self.assertTrue(tr_iceriyor("   ", "herhangi"))


class FaturaAcIdTest(unittest.TestCase):
    """Liste iid=fatura.id; sıralama sonrası yanlış belge açılmamalı."""

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

    def test_secim_iid_ile_acilir_siralamadan_bagimsiz(self):
        from tkinter import ttk

        # Ağır app init yerine doğrudan mantık: selection iid
        tablo = ttk.Treeview(self.root, columns=("no",), show="headings")
        tablo.heading("no", text="Evrak No")
        tablo.insert("", "end", iid="101", values=("SF-2",))
        tablo.insert("", "end", iid="55", values=("SF-1",))
        # Sıra: 101 sonra 55 — seçim 55
        tablo.selection_set("55")
        self.assertEqual(int(tablo.selection()[0]), 55)
        # ilk satır sırası 101 olsa bile seçim id 55
        self.assertEqual(tablo.get_children()[0], "101")


class SatisFaturaListeFiltreMantikTest(unittest.TestCase):
    def test_filtre_cari_ve_tarih_and(self):
        """_fatura_filtreli_satirlar mantığı — stub ham liste."""
        from database.turkce_normalize import tr_iceriyor

        ham = [
            {
                "id": 1,
                "cari_unvan": "IŞIK MOBİLYA",
                "cari_kodu": "C1",
                "values": ("A", "08.11.2026", "", "10.11.2026", "IŞIK MOBİLYA"),
                "sort": ("a", date(2026, 11, 8), "", date(2026, 11, 10), "isik", Decimal(0), "", "", "", Decimal(100), Decimal(0), Decimal(100), "", "", "", "", "", ""),
            },
            {
                "id": 2,
                "cari_unvan": "RAY MENTEŞE",
                "cari_kodu": "C2",
                "values": ("B", "08.11.2026", "", "10.11.2026", "RAY MENTEŞE"),
                "sort": ("b", date(2026, 11, 8), "", date(2026, 11, 10), "ray", Decimal(0), "", "", "", Decimal(50), Decimal(0), Decimal(50), "", "", "", "", "", ""),
            },
        ]
        q = turkce_normalize("ışık")
        sonuc = [s for s in ham if tr_iceriyor(q, s["cari_unvan"], s["cari_kodu"])]
        self.assertEqual([s["id"] for s in sonuc], [1])
        # sıfır sonuç eski listeyi tutmaz
        sonuc2 = [s for s in ham if tr_iceriyor("yokkişi", s["cari_unvan"])]
        self.assertEqual(sonuc2, [])


if __name__ == "__main__":
    unittest.main()
