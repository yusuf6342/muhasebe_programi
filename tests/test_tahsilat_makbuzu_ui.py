"""Tahsilat / ödeme makbuzu ekranı: boş açılış, cari arama, bakiye, numara, kapatma uyarısı, kart satırları.

Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu).
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import FinansHareketi, KasaMakbuzu, KrediKartiOdeme, PosValorKaydi
from tests import test_tahsilat_makbuzu as _servis_testi

import kasa_makbuz_ui
from kasa_makbuz_ui import SIRKET_KARTI_SEKLI, KasaMakbuzDialog


class TahsilatMakbuzuEkranTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _servis_testi.TahsilatMakbuzuTest.tearDown(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.mesajlar = []
        self._yamalar = [
            patch.object(kasa_makbuz_ui.messagebox, ad, side_effect=lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
            for ad in ("showerror", "showinfo", "showwarning")
        ]
        for y in self._yamalar:
            y.start()

    def tearDown(self):
        for y in self._yamalar:
            y.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    # —— yardımcılar ——
    def _dialog(self, tur="TAHSILAT", **ek):
        d = KasaMakbuzDialog(self.root, tur, **ek)
        self.root.update_idletasks()
        return d

    def _cari_sec(self, d, aranan):
        d.cari_var.set(aranan)
        self.assertTrue(d._cari_arama.eslesen, f"'{aranan}' için sonuç yok")
        d._cari_arama.sec(0)

    def _satir(self, d, tutar, sekil=None, hesap=None):
        if sekil:
            d.sekil_var.set(sekil)
            d._sekil_degisti()
        if hesap:
            d.hesap_var.set(hesap)
        d.tutar_var.set(tutar)
        self.assertTrue(d.satir_ekle(), self.mesajlar)

    def _makbuz_sayisi(self):
        with get_session() as s:
            return s.scalar(select(func.count(KasaMakbuzu.id)))

    # —— testler ——
    def test_yeni_makbuz_bos_acilir_ve_kaydetmeden_kapatinca_numara_tuketmez(self):
        d = self._dialog()
        self.assertEqual(d.mod, "yeni")
        self.assertEqual(d.makbuz_no_var.get(), "MKB-00001")
        self.assertEqual(d.cari_var.get(), "")
        self.assertEqual(d.bakiye_metni(), "—")
        self.assertEqual(d.satirlar, [])
        self.assertIn("YENİ", d.durum_rozet.cget("text"))
        self.assertTrue(d.kapat())
        self.assertEqual(self._makbuz_sayisi(), 0)
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00001")

    def test_cari_adin_ortasindan_aranir_ve_klavyeyle_secilir(self):
        d = self._dialog()
        for aranan in ("çelik", "CELIK", "mobil", "LTD", "m001", "ali çel"):
            etiketler = [k[0] for k in d._cari_arama.ara(aranan)]
            self.assertEqual(etiketler, ["M001 - ALİ ÇELİK MOBİLYA LTD"], aranan)
        d.cari_var.set("mobil")
        self.assertTrue(d._cari_arama.acik_mi(), "yazarken liste açılmalı")
        d._cari_arama._enter()
        self.assertFalse(d._cari_arama.acik_mi())
        self.assertEqual(d.secili_cari_id(), self.musteri_id)
        self.assertEqual(d.bakiye_metni(), "1.000,00 TL  Borçlu")
        d.kapat()

    def test_cari_degisince_bakiye_hemen_guncellenir(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        self.assertEqual(d.bakiye_metni(), "1.000,00 TL  Borçlu")
        self._cari_sec(d, "yıldız")
        self.assertEqual(d.secili_cari_id(), self.tedarikci_id)
        self.assertEqual(d.bakiye_metni(), "5.000,00 TL  Borçlu")
        d.cari_var.set("YILDIZ AKS")  # seçili metin elle bozuldu
        self.assertIsNone(d.secili_cari_id())
        self.assertEqual(d.bakiye_metni(), "—")
        with patch.object(kasa_makbuz_ui.messagebox, "askyesnocancel", return_value=False):
            d.kapat()

    def test_kayit_sonrasi_bakiye_yeniden_hesaplanir_ve_yeni_makbuz_bos_gelir(self):
        kayitlar = []
        d = self._dialog(on_kayit=kayitlar.append)
        self._cari_sec(d, "mobilya")
        self._satir(d, "250,00")  # tek kasa hesabı otomatik seçili
        self.assertTrue(d.kaydet(), self.mesajlar)
        self.assertEqual(d.mod, "goruntule")
        self.assertEqual(d.makbuz_no_var.get(), "MKB-00001")
        self.assertEqual(d.no_buyuk_lbl.cget("text"), "MKB-00001")
        self.assertEqual(d.bakiye_metni(), "750,00 TL  Borçlu")
        self.assertEqual(str(d.tarih_entry.cget("state")), "disabled")
        self.assertEqual(len(kayitlar), 1)
        self.assertEqual(kayitlar[0].makbuz_no, "MKB-00001")
        self.assertIn("KAYITLI", d.durum_rozet.cget("text"))

        d2 = self._dialog()
        self.assertEqual(d2.cari_var.get(), "")
        self.assertEqual(d2.bakiye_metni(), "—")
        self.assertEqual(d2.satirlar, [])
        self.assertEqual(d2.makbuz_no_var.get(), "MKB-00002")
        d2.kapat()
        d.kapat()

    def test_kapatirken_kaydedilmemis_degisiklik_uyarisi(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        self._satir(d, "100")
        with patch.object(kasa_makbuz_ui.messagebox, "askyesnocancel", return_value=None) as sor:
            self.assertFalse(d.kapat())
            sor.assert_called_once()
        self.assertTrue(d.winfo_exists())
        with patch.object(kasa_makbuz_ui.messagebox, "askyesnocancel", return_value=False):
            self.assertTrue(d.kapat())
        self.assertEqual(self._makbuz_sayisi(), 0)
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00001")

    def test_yeni_no_elle_girilir_mukerrer_reddedilir(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        self._satir(d, "100")
        self.assertTrue(d.kaydet())
        d.kapat()

        d2 = self._dialog()
        self.assertFalse(d2.yeni_no_gir(" mkb-00001 "))
        self.assertTrue(any(m[0] == "showerror" and "zaten var" in m[1][1] for m in self.mesajlar))
        self.assertTrue(d2.yeni_no_gir("ÖZEL-7"))
        self.assertEqual(d2.makbuz_no_var.get(), "ÖZEL-7")
        self._cari_sec(d2, "çelik")
        self._satir(d2, "50")
        self.assertTrue(d2.kaydet(), self.mesajlar)
        self.assertEqual(d2.result.makbuz_no, "ÖZEL-7")
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00002")
        self.assertFalse(d2.yeni_no_gir(""), "kayıtlı makbuzda düzenleme dışında numara değişmez")
        d2.kapat()

    def test_bos_no_otomatik_numaraya_doner(self):
        d = self._dialog()
        self.assertTrue(d.yeni_no_gir("ELLE-1"))
        self.assertTrue(d.yeni_no_gir(""))
        self.assertEqual(d.makbuz_no_var.get(), "MKB-00001")
        self.assertFalse(d._makbuz_no_manuel)
        with patch.object(kasa_makbuz_ui.messagebox, "askyesnocancel", return_value=False):
            d.kapat()

    def test_kayitli_makbuz_duzenlenir_mukerrer_hareket_olmaz(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        self._satir(d, "200")
        d.kaydet()
        makbuz_id, belge = d.result.id, d.result.belge_no
        d.kapat()

        g = self._dialog(makbuz_id=makbuz_id)
        self.assertEqual(g.mod, "goruntule")
        self.assertEqual(g.makbuz_no_var.get(), "MKB-00001")
        self.assertEqual(g.bakiye_metni(), "800,00 TL  Borçlu")
        g.duzenlemeye_gec()
        self.assertEqual(g.mod, "duzenle")
        g.tablo.selection_set("0")
        g.satir_duzenle()
        g.tutar_var.set("300")
        self.assertTrue(g.satir_ekle())
        self.assertTrue(g.kaydet(), self.mesajlar)
        self.assertEqual(g.result.belge_no, belge)
        self.assertEqual(g.result.makbuz_no, "MKB-00001")
        self.assertEqual(Decimal(str(g.result.tutar)), Decimal("300"))
        self.assertEqual(g.bakiye_metni(), "700,00 TL  Borçlu")
        with get_session() as s:
            adet = s.scalar(select(func.count(FinansHareketi.id)).where(FinansHareketi.belge_no == belge))
        self.assertEqual(adet, 1)
        g.kapat()

    def test_kredi_karti_tahsilat_satiri_pos_hesabina(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        d.sekil_var.set("KREDİ KARTIYLA TAHSİLAT")
        d._sekil_degisti()
        self.assertEqual(d.hesap_var.get(), "TEST BANK — POS")
        self.assertEqual(d.kart_kutu.winfo_manager(), "grid")
        d.kart_tipi_var.set("Kredi Kartı")
        d.taksit_var.set("3")
        d.tutar_var.set("1000")
        self.assertTrue(d.satir_ekle(), self.mesajlar)
        self.assertEqual(d.satirlar[0]["kart_tipi"], "KREDI_KARTI")
        self.assertEqual(d.satirlar[0]["taksit_sayisi"], 3)
        self.assertTrue(d.kaydet(), self.mesajlar)
        with get_session() as s:
            pv = s.scalar(select(PosValorKaydi).where(PosValorKaydi.belge_no == d.result.belge_no))
        self.assertIsNotNone(pv)
        self.assertEqual(pv.taksit_sayisi, 3)
        d.kapat()

    def test_tedarikci_odemesi_sirket_kredi_karti(self):
        d = self._dialog("ODEME")
        self.assertEqual(d.makbuz_no_var.get(), "")
        self._cari_sec(d, "yıldız")
        d.sekil_var.set(SIRKET_KARTI_SEKLI)
        d._sekil_degisti()
        self.assertEqual(list(d.hesap_cb.cget("values")), ["ŞİRKET KARTI — TEST BANK"])
        self.assertEqual(d.hesap_var.get(), "ŞİRKET KARTI — TEST BANK")
        d.taksit_var.set("2")
        d.tutar_var.set("2000")
        self.assertTrue(d.satir_ekle(), self.mesajlar)
        self.assertTrue(d.kaydet(), self.mesajlar)
        self.assertEqual(d.bakiye_metni(), "3.000,00 TL  Borçlu")
        with get_session() as s:
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no.like(f"{d.result.belge_no}-%")))
        self.assertIsNotNone(ko)
        d.kapat()

    def test_iptal_edilen_makbuz_salt_okunur(self):
        d = self._dialog()
        self._cari_sec(d, "çelik")
        self._satir(d, "100")
        d.kaydet()
        with patch.object(kasa_makbuz_ui.messagebox, "askyesno", return_value=True):
            d.iptal_et()
        self.assertEqual(d.makbuz.durum, "IPTAL")
        self.assertIn("İPTAL", d.durum_rozet.cget("text"))
        self.assertFalse(d.btn_duzenle.winfo_manager())
        self.assertEqual(d.bakiye_metni(), "1.000,00 TL  Borçlu")
        d.kapat()


if __name__ == "__main__":
    unittest.main()
