"""Ana panel açık ekranlar yığını: menü değişince önceki ekran yaşamaya devam eder."""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_ekran_yigini_"))

import ana_panel_ui  # noqa: E402
import app as app_mod  # noqa: E402

ANA_MENULER = (
    "giris",
    "satislar",
    "satin_alma",
    "stoklar",
    "finans",
    "gelir_gider",
    "ozet_tablolar",
    "genel_muhasebe",
)


def _sahte_ciz(anahtar):
    """Modül kök sayfası yerine: içerik alanına Entry çizer, app'e ortak ad yazar."""

    def ciz(app, *_a, **_k):
        app._icerigi_temizle()
        ttk.Label(app.icerik, text=anahtar.upper()).pack()
        giris = ttk.Entry(app.icerik)
        giris.pack()
        app.cizim_sayaci[anahtar] = app.cizim_sayaci.get(anahtar, 0) + 1
        app.girisler[anahtar] = giris
        # Gerçek modüller gibi app üzerinde ortak öznitelik (ör. cari_tablosu)
        app.ortak_tablo = giris
        app.ortak_tur = anahtar

    return ciz


def _alt_sayfa(app, anahtar):
    """Modül içi gezinme: aynı ekranın içeriğini temizleyip alt sayfa çizer."""
    app._nav_ileri = True
    app._icerigi_temizle()
    ttk.Label(app.icerik, text=f"{anahtar} alt sayfa").pack()
    alt = ttk.Entry(app.icerik)
    alt.pack()
    return alt


class EkranYiginiTest(unittest.TestCase):
    def setUp(self):
        try:
            self.app = app_mod.MuhasebeApp.__new__(app_mod.MuhasebeApp)
            tk.Tk.__init__(self.app)
        except tk.TclError as exc:
            self.skipTest(f"Tk yok: {exc}")
        # Odak kaydı için pencere eşlenmiş olmalı; ekran dışında tut
        self.app.geometry("1100x700+-5000+-5000")
        self.app.cizim_sayaci = {}
        self.app.girisler = {}

        yamalar = [
            patch("database.access.yetki_var", return_value=True),
            patch.object(app_mod.MuhasebeApp, "_menu_islemi", lambda self, komut: komut()),
            patch.object(ana_panel_ui, "giris_dashboard_goster", _sahte_ciz("giris")),
            patch.object(app_mod, "satislar_hub_goster", _sahte_ciz("satislar")),
            patch.object(app_mod.MuhasebeApp, "satin_alma_menusu_goster", _sahte_ciz("satin_alma")),
            patch.object(app_mod.MuhasebeApp, "stoklar_menusu_goster", _sahte_ciz("stoklar")),
            patch.object(app_mod.MuhasebeApp, "finans_goster", _sahte_ciz("finans")),
            patch.object(app_mod, "gelir_gider_menusu_goster", _sahte_ciz("gelir_gider")),
            patch.object(app_mod, "genel_muhasebe_menusu_goster", _sahte_ciz("genel_muhasebe")),
            patch.object(app_mod, "ozet_tablolar_menusu_goster", _sahte_ciz("ozet_tablolar")),
        ]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        self.app._stil_ayarla()
        self.app._arayuzu_olustur()
        self.yon = self.app._ekran_yoneticisi
        self.app.ana_sayfa_goster()
        self.app.update_idletasks()

    def tearDown(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    def _ac(self, anahtar):
        self.app.sayfa_goster(anahtar, ust_duzey=True)
        self.app.update_idletasks()
        return self.yon.getir(anahtar)

    def test_satislar_stoklar_satislar_ayni_cerceve_ve_veri(self):
        satislar = self._ac("satislar")
        self.app.girisler["satislar"].insert(0, "kaydedilmemiş 123")
        stoklar = self._ac("stoklar")
        self.assertIs(self.yon.aktif, stoklar)
        self.assertTrue(satislar.cerceve.winfo_exists())
        self.assertFalse(satislar.cerceve.winfo_ismapped())

        geri = self._ac("satislar")
        self.assertIs(geri, satislar)
        self.assertIs(self.app.icerik, satislar.cerceve)
        self.assertEqual(self.app.girisler["satislar"].get(), "kaydedilmemiş 123")
        self.assertEqual(self.app.cizim_sayaci["satislar"], 1, "öne getirmek yeniden çizmemeli")
        self.assertEqual(self.app._aktif_sayfa, "satislar")

    def test_ekran_ozniteliklerini_geri_yukler(self):
        self._ac("satislar")
        satis_tablo = self.app.ortak_tablo
        self._ac("stoklar")
        self.assertEqual(self.app.ortak_tur, "stoklar")
        self._ac("satislar")
        self.assertIs(self.app.ortak_tablo, satis_tablo)
        self.assertEqual(self.app.ortak_tur, "satislar")

    def test_ayni_menu_iki_kez_kopya_olusturmaz(self):
        ilk = self._ac("stoklar")
        alt = _alt_sayfa(self.app, "stoklar")
        alt.insert(0, "alt veri")
        ikinci = self._ac("stoklar")
        self.assertIs(ilk, ikinci)
        self.assertEqual(self.yon.acilis_sirasi.count("stoklar"), 1)
        self.assertEqual(len(self.app.ekran_kabi.winfo_children()), len(self.yon.ekranlar))
        self.assertTrue(alt.winfo_exists(), "sol menüden tekrar tıklamak alt sayfayı silmemeli")
        self.assertEqual(alt.get(), "alt veri")
        self.assertEqual(self.app.cizim_sayaci["stoklar"], 1)

    def test_modul_ici_geri_dugmesi_koke_doner(self):
        self._ac("stoklar")
        _alt_sayfa(self.app, "stoklar")
        # «← Stoklar Menüsü» düğmeleri ust_duzey olmadan çağırır
        self.app.sayfa_goster("stoklar")
        self.assertEqual(self.app.cizim_sayaci["stoklar"], 2)
        self.assertTrue(self.yon.aktif.kokte)

    def test_on_ekrani_kapatinca_onceki_ve_odagi_doner(self):
        satislar = self._ac("satislar")
        giris = self.app.girisler["satislar"]
        giris.focus_set()
        self.app.update()
        stoklar = self._ac("stoklar")
        self.app.update()
        # Yeni ekran odağı alır; gizli ekrandaki alanda kalmaz
        self.assertTrue(str(self.app.focus_lastfor()).startswith(str(stoklar.cerceve)))
        self.assertTrue(self.yon.kapat("stoklar"))
        self.app.update()
        self.assertIsNone(self.yon.getir("stoklar"))
        self.assertIs(self.yon.aktif, satislar)
        self.assertTrue(satislar.cerceve.winfo_ismapped() or satislar.cerceve.winfo_manager())
        self.assertIs(self.app.focus_lastfor(), giris)
        self.assertEqual(self.app.menu_dugmeleri["satislar"]._aktif, True)

    def test_ctrl_w_aktif_ekrani_kapatir_giris_kapanmaz(self):
        self._ac("finans")
        self.assertTrue(self.yon.aktif_ekrani_kapat())
        self.assertEqual(self.yon.aktif_anahtar(), "giris")
        self.assertFalse(self.yon.aktif_ekrani_kapat())
        self.assertIsNotNone(self.yon.getir("giris"))

    def test_kapatma_kontrolu_false_ise_kapanmaz(self):
        ekran = self._ac("genel_muhasebe")
        self.app.ekran_kapatma_kontrolu_ekle(lambda: False)
        self.assertFalse(self.yon.kapat("genel_muhasebe"))
        self.assertTrue(ekran.cerceve.winfo_exists())
        self.assertFalse(self.app._acik_ekranlar_kapatilabilir_mi())

    def test_acik_belge_penceresi_menu_degisiminde_yasar(self):
        self._ac("satislar")
        belge = tk.Toplevel(self.app)
        belge.transient(self.app)
        alan = ttk.Entry(belge)
        alan.pack()
        alan.insert(0, "SATIŞ FATURASI taslak")
        belge.update_idletasks()
        try:
            belge.grab_set()
        except tk.TclError:
            pass
        grab_once = self.app.grab_current()
        self._ac("stoklar")
        self._ac("finans")
        self.assertTrue(belge.winfo_exists())
        self.assertEqual(alan.get(), "SATIŞ FATURASI taslak")
        self.assertEqual(self.app.grab_current(), grab_once)
        belge.grab_release()
        belge.destroy()

    def test_tum_ana_menuler_ortak_fonksiyonla_acilir(self):
        for anahtar in ANA_MENULER:
            ekran = self._ac(anahtar)
            self.assertIsNotNone(ekran, anahtar)
            self.assertIs(self.yon.aktif, ekran)
            self.assertTrue(ekran.cerceve.winfo_children(), anahtar)
        self.assertEqual(sorted(self.yon.acilis_sirasi), sorted(ANA_MENULER))
        # Şerit: her açık ekran için sekme + GİRİŞ dışında kapat düğmesi
        metinler = [
            w.cget("text")
            for sekme in self.app.ekran_seridi.winfo_children()
            for w in ([sekme] + list(sekme.winfo_children()))
            if isinstance(w, tk.Label)
        ]
        self.assertIn("SATIŞLAR", metinler)
        self.assertEqual(metinler.count("×"), len(ANA_MENULER) - 1)

    def test_modul_ici_temizleme_diger_ekrani_silmez(self):
        satislar = self._ac("satislar")
        satis_giris = self.app.girisler["satislar"]
        self._ac("stoklar")
        _alt_sayfa(self.app, "stoklar")
        self.app._icerigi_temizle()
        self.assertTrue(satislar.cerceve.winfo_exists())
        self.assertTrue(satis_giris.winfo_exists())

    def test_gecmis_ekran_basina_tutulur(self):
        self._ac("stoklar")
        self.app.nav_sayfa_isaretle(lambda: None)
        _alt_sayfa(self.app, "stoklar")
        self.assertEqual(len(self.app._nav_gecmis), 1)
        self._ac("satislar")
        self.assertEqual(self.app._nav_gecmis, [])
        self._ac("stoklar")
        self.assertEqual(len(self.app._nav_gecmis), 1)

    def test_firma_degisimi_tum_ekranlari_kapatir(self):
        for anahtar in ("satislar", "stoklar", "finans"):
            self._ac(anahtar)
        self.app._ekranlari_temizle()
        self.assertEqual(self.yon.ekranlar, {})
        self.assertIs(self.app.icerik, self.app.ekran_kabi)
        self.app.ana_sayfa_goster()
        self.assertEqual(self.yon.acilis_sirasi, ["giris"])

    def test_yetkisiz_ekran_kullanici_degisince_kapanir(self):
        self._ac("finans")
        with patch("database.access.yetki_var", return_value=False):
            self.app._sistem_menu_gorunurluk_guncelle()
        self.assertIsNone(self.yon.getir("finans"))
        self.assertEqual(self.yon.aktif_anahtar(), "giris")


if __name__ == "__main__":
    unittest.main()
