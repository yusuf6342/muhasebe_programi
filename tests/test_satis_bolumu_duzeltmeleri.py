"""Satış bölümü düzeltmeleri: cari kart, tahsilat/ödeme evrakları, bekleyen siparişler, müşteri listesi.

Yalnız geçici test veritabanı ve geçici ayar klasörü kullanır.
"""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari, CariIslem
from tests import test_tahsilat_makbuzu as _servis_testi
from tutar_bicim import servis_metni, tr_tutar, tutar_coz


def _kurulum(test):
    _servis_testi.TahsilatMakbuzuTest.setUp(test)
    with get_session() as s:
        s.add_all(
            [
                Cari(cari_kodu="M002", unvan="ŞİŞLİ IŞIK AYDINLATMA", cari_turu="Müşteri"),
                Cari(cari_kodu="M003", unvan="DENİZ İNŞAAT A.Ş.", cari_turu="Müşteri"),
            ]
        )


class TutarBicimTest(unittest.TestCase):
    def test_turkce_ve_karisik_girisler(self):
        ornekler = {
            "1.234,50": Decimal("1234.50"),
            "1.234.567,89": Decimal("1234567.89"),
            "1234,5": Decimal("1234.5"),
            "1.234": Decimal("1234"),
            "300.00": Decimal("300.00"),
            "12.5": Decimal("12.5"),
            "1,234.50": Decimal("1234.50"),
            " 1.234,50 TL": Decimal("1234.50"),
        }
        for metin, beklenen in ornekler.items():
            with self.subTest(metin=metin):
                self.assertEqual(tutar_coz(metin), beklenen)
        for hatali in ("", "abc", "1,2,3"):
            with self.subTest(hatali=hatali), self.assertRaises(ValueError):
                tutar_coz(hatali)

    def test_gosterim_ve_servis_metni_degeri_korur(self):
        self.assertEqual(tr_tutar(Decimal("1234.5")), "1.234,50")
        self.assertEqual(tr_tutar(Decimal("1234567.89"), birim="TL"), "1.234.567,89 TL")
        for d in (Decimal("1234.50"), Decimal("1234567.89"), Decimal("0.01")):
            self.assertEqual(tutar_coz(tr_tutar(d)), d)
            # Tüm servis ayrıştırıcıları aynı değeri okur
            self.assertEqual(CariService._tutar(servis_metni(d)), d)
            from database.finans_service import _decimal

            self.assertEqual(_decimal(servis_metni(d)), d)


class _TemelTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)
        self._ayar_dizini = tempfile.TemporaryDirectory()
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar_dizini.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._ayar_dizini.cleanup()
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)


class MusteriListesiAramaTest(_TemelTest):
    def _liste(self, arama, tur="Müşteri"):
        return [o["cari"].unvan for o in CariService.listele(arama, cari_turu=tur, hizli=True)]

    def test_ara_hatasi_giderildi_ve_senaryolar(self):
        # Önceden: arama sonucu başka oturumdan geldiği için "not present in this Session" hatası
        self.assertEqual(len(self._liste("")), 3)
        self.assertEqual(self._liste("çelik"), ["ALİ ÇELİK MOBİLYA LTD"])
        self.assertEqual(self._liste("ELİK"), ["ALİ ÇELİK MOBİLYA LTD"])
        self.assertEqual(self._liste("sisli"), ["ŞİŞLİ IŞIK AYDINLATMA"])
        self.assertEqual(self._liste("ışık"), ["ŞİŞLİ IŞIK AYDINLATMA"])
        self.assertEqual(self._liste("yoktur"), [])
        self.assertEqual(self._liste("aksesuar", "Tedarikçi"), ["YILDIZ AKSESUAR"])
        with self.assertRaises(ValueError):
            CariService.listele("ab", cari_turu="Müşteri")
        bakiye = CariService.listele("çelik", cari_turu="Müşteri")[0]["bakiye"]
        self.assertEqual(bakiye, Decimal("1000"))

    def test_liste_ekrani_ara_dugmesi(self):
        import app as app_mod

        try:
            root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        root.withdraw()
        try:
            from cari_liste_ui import cari_liste_ayarlari_yukle, gorunur_kolonlar

            ayar = cari_liste_ayarlari_yukle()
            tablo = tk.ttk.Treeview(root, columns=tuple(gorunur_kolonlar(ayar)), show="headings")
            arama = tk.ttk.Entry(root)
            sahte = SimpleNamespace(cari_tablosu=tablo, cari_arama=arama, _cari_liste_turu="Müşteri")
            hatalar = []

            def hemen(_w, is_, on_ok=None, on_err=None):
                try:
                    on_ok(is_())
                except Exception as exc:  # noqa: BLE001
                    on_err(exc)

            with patch.object(app_mod, "arka_planda", hemen), patch.object(
                app_mod.messagebox, "showerror", side_effect=lambda *a, **k: hatalar.append(a)
            ):
                arama.insert(0, "mobilya")
                app_mod.MuhasebeApp.cari_listesini_yenile(sahte)
            self.assertEqual(hatalar, [])
            satirlar = [tablo.item(i, "values") for i in tablo.get_children()]
            self.assertEqual(len(satirlar), 1)
            self.assertIn("ALİ ÇELİK MOBİLYA LTD", satirlar[0])
        finally:
            root.destroy()


class CariListeKolonAyarTest(_TemelTest):
    def test_valor_basligi_ve_kalici_ayarlar(self):
        import cari_liste_ui as cl

        self.assertEqual(cl.baslik_metni("agirlikli"), "Valör")
        try:
            root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        root.withdraw()
        try:
            uygulanan = []
            d = cl.CariListeKolonAyarDialog(root, cl.cari_liste_ayarlari_yukle(), on_uygula=uygulanan.append)
            metinler = [
                w.cget("text")
                for satir in d._ic.winfo_children()
                for w in satir.winfo_children()
                if isinstance(w, tk.ttk.Checkbutton)
            ]
            self.assertIn("Valör", metinler)
            self.assertNotIn("Ağırlıklı Ortalama Geçen Gün", metinler)
            d._vars["email"].set(False)
            d._genislik["unvan"].set("333")
            d._tasi("bakiye", -1)
            d._tasi("bakiye", -1)
            d._vars["kod"].set(False)  # zorunlu kolon gizlenemez
            d._uygula()
            self.assertEqual(len(uygulanan), 1)

            yeni = cl.cari_liste_ayarlari_yukle()
            self.assertFalse(yeni["kolonlar"]["email"]["gorunur"])
            self.assertTrue(yeni["kolonlar"]["kod"]["gorunur"])
            self.assertEqual(yeni["kolonlar"]["unvan"]["genislik"], 333)
            sira = yeni["sira"]
            self.assertLess(sira.index("bakiye"), sira.index("yaklasan_dogum"))
            gorunur = cl.gorunur_kolonlar(yeni)
            self.assertNotIn("email", gorunur)

            # Başlıktan sürüklenen genişlik kaydedilir
            tablo = tk.ttk.Treeview(root, columns=tuple(gorunur), show="headings")
            tablo.column("telefon", width=222)
            cl.tablo_genisliklerini_kaydet(tablo, yeni)
            self.assertEqual(cl.cari_liste_ayarlari_yukle()["kolonlar"]["telefon"]["genislik"], 222)
        finally:
            root.destroy()


class _EkranTest(_TemelTest):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _TemelTest.tearDown(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        import app as app_mod
        import cari_kart_ui
        import kasa_makbuz_ui

        self.app = app_mod
        self.kart_ui = cari_kart_ui
        self.mesajlar = []
        self._yamalar = [
            patch.object(mod.messagebox, ad, side_effect=lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
            for mod in (app_mod, cari_kart_ui, kasa_makbuz_ui)
            for ad in ("showerror", "showinfo", "showwarning")
        ]
        self._yamalar.append(patch("cari_kart_ui.cari_uyari_goster", return_value=None))
        for y in self._yamalar:
            y.start()

    def tearDown(self):
        for y in self._yamalar:
            y.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        _TemelTest.tearDown(self)

    def _acik_kartlar(self):
        return [k for k in self.kart_ui.CariDialog._acik_kartlar if k.winfo_exists()]


class CariKartTest(_EkranTest):
    def test_kimlik_no_bos_veya_farkli_uzunlukta_kaydi_engellemez(self):
        for tc in ("", "123", "1234567890123", "ABC-12"):
            with self.subTest(tc=tc):
                kart = self.kart_ui.CariDialog(self.root, cari=None, cari_turu="Müşteri")
                kart.degerler["unvan"].insert(0, f"KİMLİK TEST {tc or 'BOŞ'}")
                kart.degerler["tc_kimlik"].insert(0, tc)
                self.assertTrue(kart.kaydet(), self.mesajlar)
                with get_session() as s:
                    kayit = s.get(Cari, kart.cari.id)
                    self.assertEqual(kayit.tc_kimlik or "", tc)
                kart.destroy()
        self.assertFalse([m for m in self.mesajlar if m[0] != "showinfo"])

    def test_baska_cari_secilince_tek_kart_kalir(self):
        a = CariService.getir(self.musteri_id)
        with get_session() as s:
            b = s.scalar(select(Cari).where(Cari.cari_kodu == "M002"))
        kart_a = self.kart_ui.CariDialog(self.root, cari=a)
        self.root.update()
        kart_b = self.kart_ui.CariDialog(self.root, cari=b)
        self.root.update()
        self.assertFalse(kart_a.winfo_exists())
        self.assertEqual(self._acik_kartlar(), [kart_b])
        self.assertEqual(kart_b.degerler["unvan"].get(), "ŞİŞLİ IŞIK AYDINLATMA")

        # Kaydedilmemiş değişiklikte kullanıcı "İptal" derse eski kart korunur
        kart_b.degerler["email"].insert(0, "x@y.com")
        with patch.object(self.kart_ui.messagebox, "askyesnocancel", return_value=None):
            yeni = self.kart_ui.CariDialog(self.root, cari=a)
            self.root.update()
        self.assertTrue(kart_b.winfo_exists())
        self.assertFalse(yeni.winfo_exists())
        # "Hayır" = kaydetmeden geç
        with patch.object(self.kart_ui.messagebox, "askyesnocancel", return_value=False):
            kart_a2 = self.kart_ui.CariDialog(self.root, cari=a)
            self.root.update()
        self.assertFalse(kart_b.winfo_exists())
        self.assertEqual(self._acik_kartlar(), [kart_a2])
        with get_session() as s:
            self.assertIsNone(s.get(Cari, b.id).email)

    def test_unvan_icinden_arama_ile_kart_yuklenir(self):
        kart = self.kart_ui.CariDialog(self.root, cari=None, cari_turu="Müşteri")
        arama = kart._unvan_arama
        self.assertEqual(arama.ara("ş"), [], "tek karakterde sorgu çalışmamalı")
        self.assertEqual([c.unvan for c in arama.ara("işlı")], ["ŞİŞLİ IŞIK AYDINLATMA"])
        self.assertEqual([c.unvan for c in arama.ara("MOBİLYA")], ["ALİ ÇELİK MOBİLYA LTD"])
        self.assertEqual({c.cari_kodu for c in arama.ara("in")}, {"M002", "M003"})
        self.assertEqual([c.cari_kodu for c in arama.ara("insaat")], ["M003"])
        self.assertEqual(arama.ara("aksesuar"), [], "tedarikçi müşteri kartında önerilmez")
        kart.degerler["unvan"].insert(0, "mobilya")
        arama.ara()
        arama.sec(0)
        self.root.update()
        self.assertFalse(kart.winfo_exists())
        (yeni,) = self._acik_kartlar()
        self.assertEqual(yeni.cari.id, self.musteri_id)
        self.assertEqual(yeni.degerler["unvan"].get(), "ALİ ÇELİK MOBİLYA LTD")
        self.assertFalse([m for m in self.mesajlar if m[0] != "showinfo"])

    def test_secili_cari_ile_uc_evrak_acilir(self):
        musteri = CariService.getir(self.musteri_id)
        kart = self.kart_ui.CariDialog(self.root, cari=musteri)
        metinler = [d.cget("text") for d in kart.hizli_dugmeleri]
        for ad in ("Ödeme Gir", "Cari Virman", "Müşteriden Tedarikçiye"):
            self.assertIn(ad, metinler)
        acilan = []
        with patch.object(kart, "wait_window", side_effect=acilan.append):
            kart.odeme_gir()
            kart.cari_virman_ac()
            kart.kk_cekimi_ac()
        odeme, virman, kk = acilan
        self.assertIn("ALİ ÇELİK MOBİLYA LTD", odeme.cari_lbl.cget("text"))
        self.assertIn("ALİ ÇELİK MOBİLYA LTD", virman.girdiler["kaynak"].get())
        self.assertEqual(virman.girdiler["hedef"].get(), "")
        self.assertIn("ALİ ÇELİK MOBİLYA LTD", kk.girdiler["musteri"].get())
        for d in acilan:
            self.assertEqual(d.resizable(), (True, True))
            d.destroy()

        tedarikci = CariService.getir(self.tedarikci_id)
        tkart = self.kart_ui.CariDialog(self.root, cari=tedarikci)
        acilan.clear()
        with patch.object(tkart, "wait_window", side_effect=acilan.append):
            tkart.cari_virman_ac()
            tkart.kk_cekimi_ac()
        virman, kk = acilan
        self.assertIn("YILDIZ AKSESUAR", virman.girdiler["hedef"].get())
        self.assertIn("YILDIZ AKSESUAR", kk.girdiler["tedarikci"].get())
        for d in acilan:
            d.destroy()


class EvrakTutarTest(_EkranTest):
    def _odak_cik(self, entry):
        entry.event_generate("<FocusOut>")

    def test_odeme_gir_turkce_tutar(self):
        cari = CariService.getir(self.tedarikci_id)
        d = self.app.CariTahsilatOdemeDialog(self.root, cari, tur="odeme")
        d.girdiler["tutar"].insert(0, "1234,5")
        self._odak_cik(d.girdiler["tutar"])
        self.assertEqual(d.girdiler["tutar"].get(), "1.234,50")
        self.assertIn("bold", str(d.girdiler["tutar"].cget("font")))
        d.girdiler["hesap"].set("TEST KASA")
        d.kaydet()
        self.assertFalse(self.mesajlar)
        self.assertEqual(Decimal(d.result.alacak) + Decimal(d.result.borc), Decimal("1234.50"))

    def test_virman_ve_kk_buyuk_tutar_yeniden_acilinca_ayni(self):
        v = self.app.CariVirmanDialog(self.root, kaynak_id=self.musteri_id, hedef_id=self.tedarikci_id)
        v.girdiler["tutar"].insert(0, "1.234,50")
        v.kaydet()
        with get_session() as s:
            islemler = s.scalars(select(CariIslem).where(CariIslem.islem_turu.ilike("%virman%"))).all()
            self.assertEqual({Decimal(i.borc) + Decimal(i.alacak) for i in islemler}, {Decimal("1234.50")})

        kk = self.app.KkCekimiDialog(self.root, musteri_id=self.musteri_id, tedarikci_id=self.tedarikci_id)
        kk.girdiler["tutar"].insert(0, "1234567.89")
        self._odak_cik(kk.girdiler["tutar"])
        self.assertEqual(kk.girdiler["tutar"].get(), "1.234.567,89")
        kk.girdiler["banka"].insert(0, "TEST BANK")
        kk.kaydet()
        belge = kk.result["belge_no"]
        self.assertEqual(Decimal(str(kk.result["tutar"])), Decimal("1234567.89"))
        tekrar = self.app.KkCekimiDialog(self.root, belge_no=belge)
        self.assertEqual(tekrar.girdiler["tutar"].get(), "1.234.567,89")
        tekrar.destroy()

    def test_tahsilat_makbuzu_turkce_tutar(self):
        import kasa_makbuz_ui as ui

        d = ui.KasaMakbuzDialog(self.root, "TAHSILAT")
        self.assertIn("bold", str(d.cari_entry.cget("font")))
        d.cari_var.set("çelik")
        d._cari_arama.sec(0)
        for metin, beklenen in (("1.234,50", Decimal("1234.50")), ("1.234", Decimal("1234.00"))):
            d.tutar_var.set(metin)
            self._odak_cik(d.tutar_entry)
            self.assertEqual(d.tutar_var.get(), tr_tutar(beklenen))
            d.satir_ekle()
        self.assertEqual([s["tutar"] for s in d.satirlar], [Decimal("1234.50"), Decimal("1234.00")])
        self.assertTrue(d.kaydet(), self.mesajlar)
        self.assertEqual(Decimal(str(d.makbuz.tutar)), Decimal("2468.50"))
        d.kapat()


class BekleyenSiparisTest(_EkranTest):
    def test_pencere_boyutlandirilabilir_ve_buyuk_yazi(self):
        from cari_bekleyen_siparis_ui import CariBekleyenSiparislerDialog

        d = CariBekleyenSiparislerDialog(self.root, CariService.getir(self.musteri_id))
        self.root.update()
        self.assertEqual(d.resizable(), (True, True))
        self.assertEqual(str(d.wm_transient() or ""), "")
        self.assertEqual(str(d.tablo.cget("style")), "Bekleyen.Treeview")
        font = tk.ttk.Style(d).lookup("Bekleyen.Treeview", "font")
        self.assertIn("bold", str(font))
        self.assertTrue(d.tablo.column("cari", "stretch"))
        d.geometry("760x380")
        self.root.update()
        self.assertGreater(d.tablo.winfo_width(), 300)
        d.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
