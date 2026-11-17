"""Durum çubuğu önbelleği menüyü kilitlemesin."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import ana_panel_ui as ap


class AnaPanelDurumOnbellekTest(unittest.TestCase):
    def setUp(self):
        ap._YEDEK_ONBELLEK = None
        ap._DB_BAGLI_ONBELLEK = None

    def test_yedek_onbellek_ikinci_cagri_hizli(self):
        with patch.object(ap, "_YEDEK_TTL_SN", 60.0):
            t0 = time.perf_counter()
            a = ap.son_yedek_metni(zorla=True)
            cold = time.perf_counter() - t0
            t1 = time.perf_counter()
            b = ap.son_yedek_metni()
            cached = time.perf_counter() - t1
        self.assertEqual(a, b)
        self.assertLess(cached, 0.05)
        self.assertLess(cold, 2.0)

    def test_db_bagli_onbellek(self):
        cagri = {"n": 0}

        class _S:
            def __enter__(self):
                cagri["n"] += 1
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *_a, **_k):
                return None

        with patch("database.database.get_session", return_value=_S()):
            ap._DB_BAGLI_ONBELLEK = None
            self.assertTrue(ap.db_bagli_mi(zorla=True))
            self.assertEqual(cagri["n"], 1)
            self.assertTrue(ap.db_bagli_mi())
            self.assertEqual(cagri["n"], 1, "önbellekten ikinci SELECT olmamalı")

    def test_sol_menu_grup_tik_hub_ertele(self):
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        parent = tk.Frame(root)
        parent.pack()
        cagrilar = []

        def komut():
            cagrilar.append("hub")

        grup = ap.SolMenuGrup(
            parent,
            etiket="Satışlar",
            anahtar="satislar",
            simge="+",
            vurgulu=False,
            komut=komut,
            alt_ogeler=[("A", "a", lambda: None)],
        )
        grup.pack()
        root.update_idletasks()
        grup._on_click()
        self.assertTrue(grup.acik)
        self.assertEqual(cagrilar, [], "hub hemen çalışmamalı")
        bitis = time.monotonic() + 1.0
        while time.monotonic() < bitis and not cagrilar:
            root.update()
            time.sleep(0.01)
        self.assertEqual(cagrilar, ["hub"])


if __name__ == "__main__":
    unittest.main()
