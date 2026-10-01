"""Satın Alma hub kartları: Masraf Dağıtımı ve Satın Alma Talebi ekranları görünür açılır.

Gerçek ana panel ekran yığını + gerçek hub kartı tıklaması (nav_ac → _menu_islemi → after).
Liste ekranı hub'ın altına eklenip görünmez kalmamalı; açılış hatası sessizce kaybolmamalı.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_sa_menu_"))

import ana_panel_ui  # noqa: E402
import app as app_mod  # noqa: E402
import tests.test_masraf_dagitim as md  # noqa: E402
from database.session_manager import oturum  # noqa: E402

def _bos_giris(app, *_a, **_k):
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="GİRİŞ").pack()


class SatinAlmaMenuAcilisTest(unittest.TestCase):
    _alis = md.MasrafDagitimTest._alis
    _gider = md.MasrafDagitimTest._gider

    def setUp(self):
        md.MasrafDagitimTest.setUp(self)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        SatinAlmaTalepService._hazir_motor = None
        try:
            self.app = app_mod.MuhasebeApp.__new__(app_mod.MuhasebeApp)
            tk.Tk.__init__(self.app)
        except tk.TclError as exc:
            md.MasrafDagitimTest.tearDown(self)
            self.skipTest(f"Tk yok: {exc}")
        self.app.geometry("1300x800+20+20")
        self.app.attributes("-alpha", 0.0)
        self.geri_cagri_hatalari: list = []
        self.app.report_callback_exception = lambda *e: self.geri_cagri_hatalari.append(e)
        self.mb = {}
        for modul in ("satin_alma_ui", "masraf_dagitim_ui", "satin_alma_talep_ui"):
            y = patch(f"{modul}.messagebox")
            self.mb[modul] = y.start()
            self.mb[modul].askyesno.return_value = True
            self.addCleanup(y.stop)
        y = patch.object(ana_panel_ui, "giris_dashboard_goster", _bos_giris)
        y.start()
        self.addCleanup(y.stop)
        self.app._stil_ayarla()
        self.app._arayuzu_olustur()
        self.app.ana_sayfa_goster()
        self.app.sayfa_goster("satin_alma", ust_duzey=True)
        bitis = time.monotonic() + 10
        while "MASRAF DAĞITIMI" not in self._kartlar() and time.monotonic() < bitis:
            self._pompala(0.1)
        self._pompala(0.2)
        self.assertIn("MASRAF DAĞITIMI", self._kartlar(), f"hub açılmadı: {self.geri_cagri_hatalari}")

    def tearDown(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass
        md.MasrafDagitimTest.tearDown(self)

    # ------------------------------------------------------------ yardımcı
    def _pompala(self, sure: float = 0.4):
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            self.app.update()
            time.sleep(0.01)

    def _kartlar(self) -> dict:
        bulunan = {}

        def gez(w):
            for c in w.winfo_children():
                if c.__class__.__name__ == "HubKart":
                    bulunan[c._baslik] = c
                gez(c)

        gez(self.app.icerik)
        return bulunan

    def _kart_tikla(self, baslik: str):
        kartlar = self._kartlar()
        self.assertIn(baslik, kartlar, f"hub kartı yok: {baslik}")
        kartlar[baslik]._click()
        self._pompala()

    def _gorunen_basliklar(self) -> list[str]:
        """Ekranda gerçekten görünen (eşlenmiş) etiket metinleri."""
        metinler = []

        def gez(w):
            for c in w.winfo_children():
                try:
                    if not c.winfo_ismapped():
                        continue
                except tk.TclError:
                    continue
                if isinstance(c, tk.Label):
                    metinler.append(str(c.cget("text")))
                gez(c)

        gez(self.app.icerik)
        return metinler

    def _yeni_pencereler(self) -> list[tk.Toplevel]:
        return [w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists()]

    def _tek_ekran(self):
        cocuklar = self.app.icerik.winfo_children()
        self.assertEqual(len(cocuklar), 1, "liste ekranı hub'ın altına eklenmemeli; içerik temizlenmeli")
        self.assertTrue(cocuklar[0].winfo_ismapped())
        self.assertGreater(cocuklar[0].winfo_height(), 100)

    # ------------------------------------------------------------ testler
    def test_masraf_dagitimi_karti_ekrani_gorunur_acar_kaydet_yeniden_ac(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        kaynak_id, _ks = self._gider("1000")

        self._kart_tikla("MASRAF DAĞITIMI")
        self.assertEqual(self.geri_cagri_hatalari, [])
        self._tek_ekran()
        self.assertIn("MASRAF DAĞITIMI", self._gorunen_basliklar())
        self.assertNotIn("SATIN ALMA TALEPLERİ", self._gorunen_basliklar())
        tablo = next(w for w in self._tum_widgetlar() if isinstance(w, ttk.Treeview))
        self.assertEqual(tablo.get_children(), ())

        # Yeni → kart açılır, öne gelir; veri girilip taslak kaydedilir
        acilan = []
        with patch.object(self.app, "wait_window", lambda w: acilan.append(w)):
            self._dugme("Yeni").invoke()
        self.assertEqual(len(acilan), 1, "Yeni düğmesi masraf kartını açmalı")
        d = acilan[0]
        self.assertTrue(d.winfo_exists())
        self.assertTrue(d.winfo_viewable())
        d.kaynak_ayarla(kaynak_id)
        d.hedef_ekle([h for h in MasrafDagitimService.hedef_satirlar() if h["satir_id"] == alis_satir])
        self.assertTrue(d.taslak_kaydet(sessiz=True))
        did = d.dagitim_id
        self.assertIsNotNone(did)
        d.destroy()

        # Liste yenilenir; kayıt listeden yeniden açılır
        self._dugme("Listele").invoke()
        self.assertEqual(tablo.get_children(), (str(did),))
        tablo.selection_set(str(did))
        with patch.object(self.app, "wait_window", lambda w: acilan.append(w)):
            self._dugme("Aç").invoke()
        d2 = acilan[-1]
        self.assertEqual(d2.dagitim_id, did)
        self.assertEqual(d2.kaynak["id"], kaynak_id)
        self.assertEqual([h["satir_id"] for h in d2.hedefler], [alis_satir])
        d2.destroy()

    def test_satin_alma_talebi_karti_formu_one_getirir_kaydet_yeniden_ac(self):
        from database.satin_alma_talep_service import SatinAlmaTalepService as S

        self._kart_tikla("SATIN ALMA TALEPLERİ")
        self.assertEqual(self.geri_cagri_hatalari, [])
        pencereler = self._yeni_pencereler()
        self.assertEqual(len(pencereler), 1, "kart talep formunu açmalı")
        d = pencereler[0]
        self.assertTrue(d.winfo_viewable())
        self.assertTrue(d.no.get().startswith("TAL"))
        satir = d._yeni_satir(("U001", "Test Ürün", "Adet"))
        satir["miktar"] = Decimal("5")
        d.satirlar.append(satir)
        d._satirlari_yenile()
        d.departman.insert(0, "Bakım")
        self.assertTrue(d._kaydet())
        tid = d.talep_id
        d.destroy()

        self._kart_tikla("SATIN ALMA TALEP LİSTESİ")
        self.assertEqual(self.geri_cagri_hatalari, [])
        self._tek_ekran()
        self.assertIn("SATIN ALMA TALEP LİSTESİ", self._gorunen_basliklar())
        tablo = next(w for w in self._tum_widgetlar() if isinstance(w, ttk.Treeview))
        self.assertEqual(tablo.get_children(), (str(tid),))
        tablo.selection_set(str(tid))
        acilan = []
        with patch.object(self.app, "wait_window", lambda w: acilan.append(w)):
            self._dugme("Aç").invoke()
        d2 = acilan[0]
        self.assertEqual(d2.talep_id, tid)
        self.assertTrue(d2.winfo_viewable())
        self.assertEqual(d2.departman.get(), "Bakım")
        self.assertEqual([(s["urun_kodu"], s["miktar"]) for s in d2.satirlar], [("U001", Decimal("5"))])
        self.assertEqual(S.detay(tid)["departman"], "Bakım")
        d2.destroy()

    def test_geri_dugmesi_hube_doner(self):
        self._kart_tikla("MASRAF DAĞITIMI")
        self._dugme("← Satın Alma").invoke()
        self._pompala()
        self.assertIn("MASRAF DAĞITIMI", self._kartlar())
        self.assertEqual(len(self.app.icerik.winfo_children()), 1)

    def test_yetkisiz_kullanici_nedeni_gorur(self):
        oturum.set_user(user_id=5, kullanici_adi="depo", ad_soyad="Depo", role_kod="DEPO", role_ad="Depo",
                        permissions=set())
        self._kart_tikla("MASRAF DAĞITIMI")
        self._tek_ekran()
        hata = self.mb["masraf_dagitim_ui"].showerror
        self.assertTrue(hata.called, "listeleme yetkisi yoksa neden gösterilmeli")
        self.assertIn("yetki", hata.call_args.args[1].lower())
        self._dugme("Yeni").invoke()
        uyari = self.mb["masraf_dagitim_ui"].showwarning
        self.assertTrue(uyari.called)
        self.assertIn("yetkiniz yok", uyari.call_args.args[1])
        self.assertEqual(self._yeni_pencereler(), [])

    def test_acilis_hatasi_mesaj_ve_gunluk_yarim_pencere_kalmaz(self):
        with tempfile.TemporaryDirectory() as klasor, patch(
            "hizli_satis_log.log_dizini", return_value=Path(klasor)
        ), patch(
            "database.satin_alma_talep_service.SatinAlmaTalepService.talep_no",
            side_effect=RuntimeError("tablo bozuk"),
        ):
            self._kart_tikla("SATIN ALMA TALEPLERİ")
            gunluk = (Path(klasor) / "uygulama_hata.log").read_text(encoding="utf-8")
        self.assertEqual(self.geri_cagri_hatalari, [], "hata Tk geri çağrısına sızmamalı")
        hata = self.mb["satin_alma_ui"].showerror
        self.assertTrue(hata.called)
        self.assertIn("açılamadı", hata.call_args.args[0])
        self.assertIn("tablo bozuk", hata.call_args.args[1])
        self.assertIn("uygulama_hata.log", hata.call_args.args[1])
        self.assertIn("RuntimeError: tablo bozuk", gunluk)
        self.assertEqual(self._yeni_pencereler(), [], "yarım kalan pencere kapatılmalı")

    def test_hub_karti_beklenmeyen_hatayi_gosterir(self):
        with tempfile.TemporaryDirectory() as klasor, patch(
            "hizli_satis_log.log_dizini", return_value=Path(klasor)
        ), patch("masraf_dagitim_ui.masraf_dagitimi_goster", side_effect=RuntimeError("ekran kurulamadı")):
            self._kart_tikla("MASRAF DAĞITIMI")
        self.assertEqual(self.geri_cagri_hatalari, [])
        hata = self.mb["satin_alma_ui"].showerror
        self.assertTrue(hata.called)
        self.assertIn("MASRAF DAĞITIMI", hata.call_args.args[0])
        self.assertIn("ekran kurulamadı", hata.call_args.args[1])

    # ------------------------------------------------------------ widget arama
    def _tum_widgetlar(self, kok=None) -> list:
        kok = kok or self.app.icerik
        out = []
        for c in kok.winfo_children():
            out.append(c)
            out.extend(self._tum_widgetlar(c))
        return out

    def _dugme(self, metin: str):
        for w in self._tum_widgetlar():
            try:
                if str(w.cget("text")) == metin and w.winfo_ismapped():
                    return w
            except tk.TclError:
                continue
        self.fail(f"görünür düğme yok: {metin}")


if __name__ == "__main__":
    unittest.main()
