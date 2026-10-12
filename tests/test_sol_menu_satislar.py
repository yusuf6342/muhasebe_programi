"""Sol lacivert menü: Satışlar alt menüleri (açılır/kapanır, mevcut liste ekranları) — gerçek ana panel kabuğu."""
from __future__ import annotations

import time
import tkinter as tk
import unittest

import tests.test_satin_alma_menu_acilis as menu_acilis


class SolMenuSatislarTest(unittest.TestCase):
    _K = menu_acilis.SatinAlmaMenuAcilisTest
    setUp = _K.setUp
    tearDown = _K.tearDown
    _alis = _K._alis
    _gider = _K._gider
    _pompala = _K._pompala
    _kartlar = _K._kartlar
    _yeni_pencereler = _K._yeni_pencereler
    _tum_widgetlar = _K._tum_widgetlar

    def _gorunen_metinler(self) -> list[str]:
        out = []
        for w in self._tum_widgetlar():
            try:
                if w.winfo_ismapped():
                    out.append(str(w.cget("text")))
            except tk.TclError:
                continue
        return out

    def _bekle_metin(self, metin: str, sure: float = 10) -> bool:
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            self._pompala(0.1)
            if metin in self._gorunen_metinler():
                return True
        return False

    def test_baslangicta_kapali_ve_sira(self):
        grup = self.app.menu_gruplari["satislar"]
        self.assertEqual([d._etiket for d in grup.alt_dugmeler.values()],
                         ["Satış Faturaları", "Alınan Siparişler", "Müşteri Kartları"])
        self.assertFalse(grup.acik)
        self.assertFalse(grup.alt_cerceve.winfo_manager())
        self.assertEqual(grup.lbl_ok.cget("text"), "▸")
        self.assertFalse(self.app.menu_gruplari["satin_alma"].acik)

    def test_baslik_ve_ok_acar_kapatir_bosluk_kalmaz(self):
        grup = self.app.menu_gruplari["satislar"]
        alttaki = self.app.menu_dugmeleri["satin_alma"]
        kapali_y = alttaki.winfo_y()
        for tiklanan in (grup.lbl_text, grup.inner, grup.lbl_simge, grup.lbl_ok):
            tiklanan.event_generate("<Button-1>")
            self._pompala(0.3)
            self.assertTrue(grup.acik)
            self.assertEqual(grup.lbl_ok.cget("text"), "▾")
            dugmeler = list(grup.alt_dugmeler.values())
            self.assertTrue(all(d.winfo_ismapped() for d in dugmeler))
            self.assertLessEqual(abs(grup.alt_cerceve.winfo_y() - (grup.winfo_y() + grup.winfo_height())), 2)
            ys = [d.winfo_y() for d in dugmeler]
            self.assertEqual(ys, sorted(ys), "alt alta, belirtilen sırayla")
            self.assertGreater(alttaki.winfo_y(), kapali_y)
            self.assertEqual(self.app._ekran_yoneticisi.aktif_anahtar(), "satislar")

            tiklanan.event_generate("<Button-1>")
            self._pompala(0.3)
            self.assertFalse(grup.acik)
            self.assertEqual(grup.lbl_ok.cget("text"), "▸")
            self.assertFalse(any(d.winfo_ismapped() for d in grup.alt_dugmeler.values()))
            self.assertEqual(alttaki.winfo_y(), kapali_y, "kapanınca boşluk kalmamalı")

    def test_satislar_ekrani_sol_menuyu_kendiliginden_acmaz(self):
        grup = self.app.menu_gruplari["satislar"]
        self.app.sayfa_goster("satislar", ust_duzey=True)
        self._pompala(0.8)
        self.app.satis_faturalari_goster()
        self._pompala(0.5)
        self.app.sayfa_goster("satin_alma", ust_duzey=True)
        self._pompala(0.5)
        self.app.sayfa_goster("satislar", ust_duzey=True)
        self._pompala(0.5)
        self.assertFalse(grup.acik)
        self.assertFalse(grup.alt_cerceve.winfo_manager())

    def test_alt_secenekler_mevcut_listeleri_acar(self):
        grup = self.app.menu_gruplari["satislar"]
        beklenen = {
            "satis_faturalari_goster": "SATIŞ FATURALARI",
            "satis_siparisleri_goster": "ALINAN SİPARİŞ LİSTESİ",
        }
        for anahtar, baslik in beklenen.items():
            # Her seferinde başka ekrandan başla: Satışlar ekranı öne gelip liste orada açılmalı
            self.app.sayfa_goster("satin_alma", ust_duzey=True)
            self._pompala(0.4)
            if not grup.acik:
                grup.lbl_text.event_generate("<Button-1>")
                self._pompala(0.4)
                self.app.sayfa_goster("satin_alma", ust_duzey=True)
                self._pompala(0.4)
            dugme = grup.alt_dugmeler[anahtar]
            self.assertTrue(dugme.winfo_ismapped())
            dugme.lbl_text.event_generate("<Button-1>")
            self.assertTrue(self._bekle_metin(baslik), f"{anahtar}: {baslik} açılmadı")
            self.assertEqual(self.app._ekran_yoneticisi.aktif_anahtar(), "satislar")
            self.assertEqual(self.geri_cagri_hatalari, [])
            self.assertFalse(self.mb["satin_alma_ui"].showerror.called)
            self.assertTrue(dugme._aktif, "seçili alt öğe vurgulanır")
            self.assertTrue(grup.acik, "alt öğe tıklaması grubu kapatmaz")
            self.assertEqual(self._yeni_pencereler(), [], "yeni pencere değil mevcut liste ekranı")

    def test_musteri_kartlari_bos_yeni_kart_acar_ve_yeni_kayit_olusturur(self):
        from unittest.mock import patch

        from cari_kart_ui import CariDialog
        from database.cari_service import CariService

        a = CariService.ekle({"cari_kodu": "M900", "unvan": "Mevcut Müşteri A.Ş.", "cari_turu": "Müşteri",
                              "telefon": "05550000000", "aktif": True})
        b = CariService.ekle({"cari_kodu": "M901", "unvan": "İkinci Müşteri Ltd.", "cari_turu": "Müşteri",
                              "telefon": "05551111111", "aktif": True})
        mb = patch("cari_kart_ui.messagebox").start()
        self.addCleanup(patch.stopall)
        mb.askyesnocancel.return_value = False

        def musteri_sayisi():
            from sqlalchemy import func, select

            from database.database import get_session
            from database.models.cari import Cari

            with get_session() as s:
                return s.scalar(select(func.count(Cari.id)).where(Cari.cari_turu == "Müşteri"))

        def kart():
            kartlar = [w for w in self._yeni_pencereler() if isinstance(w, CariDialog)]
            self.assertEqual(len(kartlar), 1, "tek müşteri kartı açık olmalı")
            return kartlar[0]

        eski = CariDialog(self.app, cari=CariService.getir(a.id))
        self._pompala(0.5)
        self.assertEqual(eski._widget_deger("unvan"), "Mevcut Müşteri A.Ş.")
        ekran_once = self.app._ekran_yoneticisi.aktif_anahtar()

        # 1) Sol menü → boş kart: önceki müşteri ve kimliği taşınmaz
        grup = self.app.menu_gruplari["satislar"]
        grup.ac_kapat(True)
        self._pompala(0.2)
        grup.alt_dugmeler["musteri_karti_ac"]._on_click()
        self._pompala(0.6)
        bos = kart()
        self.assertIsNot(bos, eski)
        self.assertIsNone(bos.cari)
        self.assertEqual(bos.cari_turu, "Müşteri")
        self.assertEqual(bos._widget_deger("unvan"), "")
        self.assertNotEqual(bos._widget_deger("telefon") or "", "05550000000")
        baslik = bos._baslik_alt.cget("text")
        self.assertNotIn("M900", baslik)
        self.assertNotIn("Mevcut Müşteri", baslik)
        self.assertEqual(self.app._ekran_yoneticisi.aktif_anahtar(), ekran_once, "kart ekran değiştirmez")
        self.assertTrue(grup.alt_dugmeler["musteri_karti_ac"]._aktif)

        # 2) Mevcut arama/seçim ile eski müşteri aynı karta çağrılır
        class SecimSahte:
            def __init__(self, _parent, musteriler, ara, **_k):
                self.result = next(c for c in CariService.aktif_musteriler() if c.unvan.startswith(ara))

        with patch("app.MusteriSecimDialog", SecimSahte), patch.object(CariDialog, "wait_window", lambda *_a: None):
            bos._hizli_ara.insert(0, "Mevcut")
            bos._hizli_cari_ara()
        self._pompala(0.6)
        kart_a = kart()
        self.assertEqual(kart_a.cari.id, a.id)
        self.assertEqual(kart_a._widget_deger("unvan"), "Mevcut Müşteri A.Ş.")
        self.assertEqual(kart_a._widget_deger("telefon"), "05550000000")
        self.assertEqual(kart_a._widget_deger("cari_kodu"), "M900")

        # 3) Seçili müşteride Kaydet günceller, mükerrer kayıt oluşturmaz
        sayi = musteri_sayisi()
        kart_a.degerler["telefon"].delete(0, "end")
        kart_a.degerler["telefon"].insert(0, "05559999999")
        self.assertTrue(kart_a.kaydet())
        self.assertEqual(musteri_sayisi(), sayi)
        self.assertEqual(CariService.getir(a.id).telefon, "05559999999")
        self.assertEqual(kart_a.cari.id, a.id)

        # 4) Müşteri değişince tüm bilgiler yenilenir
        kart_a._cariye_gec(CariService.getir(b.id))
        self._pompala(0.6)
        kart_b = kart()
        self.assertEqual(kart_b.cari.id, b.id)
        self.assertEqual(kart_b._widget_deger("unvan"), "İkinci Müşteri Ltd.")
        self.assertEqual(kart_b._widget_deger("telefon"), "05551111111")
        self.assertEqual(kart_b._widget_deger("cari_kodu"), "M901")

        # 5) Boş karttan yeni müşteri: Kaydet yeni kayıt oluşturur; ikinci Kaydet aynı kaydı günceller
        kart_b.yeni_kart()
        self._pompala(0.6)
        yeni = kart()
        self.assertIsNone(yeni.cari)
        self.assertEqual(yeni._widget_deger("unvan"), "")
        yeni.degerler["unvan"].insert(0, "Yeni Deneme Müşterisi")
        self.assertTrue(yeni.kaydet())
        self.assertEqual(musteri_sayisi(), sayi + 1)
        self.assertNotIn(yeni.cari.id, (a.id, b.id))
        self.assertTrue(yeni.kaydet())
        self.assertEqual(musteri_sayisi(), sayi + 1, "ikinci Kaydet mükerrer oluşturmamalı")
        self.assertEqual(CariService.getir(b.id).unvan, "İkinci Müşteri Ltd.")
        yeni.destroy()

    def test_musteri_listesine_diger_yol_korunur(self):
        import satis_ui

        self.assertEqual(satis_ui._hub_komutlar(self.app)["musteri_liste"], self.app.cariler_goster)
        self.app.sayfa_goster("satislar", ust_duzey=True)
        self._pompala(0.6)
        self.app.cariler_goster()
        self.assertTrue(self._bekle_metin("MÜŞTERİ LİSTESİ"))

    def test_satin_alma_grubu_bagimsiz_calisir(self):
        satis = self.app.menu_gruplari["satislar"]
        alis = self.app.menu_gruplari["satin_alma"]
        satis.lbl_text.event_generate("<Button-1>")
        self._pompala(0.3)
        alis.lbl_text.event_generate("<Button-1>")
        self._pompala(0.3)
        self.assertTrue(satis.acik and alis.acik)
        self.assertLessEqual(abs(alis.winfo_y() - (satis.alt_cerceve.winfo_y() + satis.alt_cerceve.winfo_height())), 3)
        satis.lbl_text.event_generate("<Button-1>")
        self._pompala(0.3)
        self.assertFalse(satis.acik)
        self.assertTrue(alis.acik)


if __name__ == "__main__":
    unittest.main()
