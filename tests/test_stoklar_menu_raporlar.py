"""Stoklar ekranı: STOK RAPORLARI açılır başlığı, rapor bağlantıları ve kaydırma (gerçek ana panel kabuğu)."""
from __future__ import annotations

import time
import tkinter as tk
import unittest

import tests.test_satin_alma_menu_acilis as menu_acilis


class StoklarMenuRaporlarTest(unittest.TestCase):
    _K = menu_acilis.SatinAlmaMenuAcilisTest
    _alis = _K._alis
    _gider = _K._gider
    _pompala = _K._pompala
    _kartlar = _K._kartlar
    _gorunen_basliklar = _K._gorunen_basliklar
    _yeni_pencereler = _K._yeni_pencereler
    _tum_widgetlar = _K._tum_widgetlar
    tearDown = _K.tearDown

    def setUp(self):
        self._K.setUp(self)
        self._stoklar_ac()

    def _stoklar_ac(self):
        import stoklar_ui

        stoklar_ui.stoklar_hub_goster(self.app)
        bitis = time.monotonic() + 10
        while "STOK KARTI" not in self._kartlar() and time.monotonic() < bitis:
            self._pompala(0.1)
        self._pompala(0.3)
        return self.app.stok_raporlari_grubu

    def test_baslik_gorunur_kapali_acilir_kapanir(self):
        import stoklar_ui

        grup = self.app.stok_raporlari_grubu
        self.assertIn("STOK RAPORLARI", self._gorunen_basliklar())
        self.assertTrue(grup.baslik.winfo_ismapped())
        self.assertFalse(grup.acik)
        self.assertNotIn("STOK YAŞLANDIRMA", self._gorunen_basliklar())
        cocuk = list(self.app.icerik.winfo_children())
        grup.etiket.event_generate("<Button-1>")
        self._pompala(0.2)
        self.assertTrue(grup.acik)
        self.assertEqual(list(self.app.icerik.winfo_children()), cocuk, "başlık ayrı ekran açmamalı")
        gorunen = self._gorunen_basliklar()
        for g, _k in stoklar_ui.RAPOR_GRUPLARI:
            self.assertIn(g, gorunen)
        grup.degistir()
        self._pompala(0.2)
        self.assertFalse(grup.acik)
        self.assertNotIn("STOK YAŞLANDIRMA", self._gorunen_basliklar())

    def test_rapor_secenekleri_tam_ve_bagli(self):
        import stoklar_ui

        grup = self.app.stok_raporlari_grubu
        alt_kartlar = {}

        def gez(w):
            for c in w.winfo_children():
                if c.__class__.__name__ == "HubKart":
                    alt_kartlar[c._baslik] = c
                gez(c)

        gez(grup.alt)
        self.assertEqual(list(alt_kartlar), [b for b, *_ in stoklar_ui.RAPOR_KARTLARI])
        self.assertEqual(len(alt_kartlar), 16)

    def test_her_rapor_ekrani_acilir(self):
        import stoklar_ui

        hata = self.mb["satin_alma_ui"].showerror
        for baslik, _a, _k in stoklar_ui.RAPOR_KARTLARI:
            grup = self._stoklar_ac()
            grup.degistir()
            self._pompala(0.1)
            kart = self._kartlar()[baslik]
            kart._click()
            self._pompala(0.6)
            for p in self._yeni_pencereler():
                p.destroy()
            self.assertEqual(self.geri_cagri_hatalari, [], baslik)
            self.assertFalse(hata.called, f"{baslik}: {hata.call_args}")
            self.assertNotIn("STOK KARTI", self._kartlar(), f"{baslik} rapor ekranını açmadı")

    def test_kaydirma_ile_tum_seceneklere_ulasilir(self):
        self.app.geometry("1100x560")
        self._pompala(0.3)
        grup = self.app.stok_raporlari_grubu
        grup.degistir()
        self._pompala(0.3)
        kanvas = next(w for w in self._tum_widgetlar() if isinstance(w, tk.Canvas))
        son = self._kartlar()["EXCEL AKTARIM"]
        self.assertGreater(son.winfo_rooty() + son.winfo_height(),
                           kanvas.winfo_rooty() + kanvas.winfo_height(), "kart başta ekran dışında olmalı")
        kanvas.yview_moveto(1.0)
        self._pompala(0.3)
        self.assertLessEqual(son.winfo_rooty() + son.winfo_height(),
                             kanvas.winfo_rooty() + kanvas.winfo_height() + 2, "kaydırınca en alt kart görünmeli")
        kanvas.yview_moveto(0.0)
        self._pompala(0.2)
        self.assertGreaterEqual(grup.baslik.winfo_rooty(), kanvas.winfo_rooty() - 1)


if __name__ == "__main__":
    unittest.main()
