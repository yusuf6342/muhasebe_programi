"""Hızlı Satış — ürün ve müşteri kutusunda 2 harf yazınca açılan canlı liste."""

from __future__ import annotations

import sys
import time
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.stok_test_ortami import StokOrtami  # noqa: E402


class HizliSatisCanliAramaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Tk yok: {exc}")
        cls.root.geometry("1x1+0+0")
        try:
            cls.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        from database.database import get_session
        from database.models.cari import Cari

        self.ortam = StokOrtami("hs_canli")
        self.ortam.urun_ekle("VD035", "Selectron 3,5x18 Sunta Vidası")
        self.ortam.urun_ekle("MN010", "Çelik Menteşe 35mm")
        with get_session() as s:
            s.add(Cari(cari_kodu="M777", unvan="AHMET YILMAZ MOBİLYA", cari_turu="Müşteri", aktif=True))
            s.commit()

        self.mesajlar: list[tuple] = []
        self._yamalar = [
            patch(f"hizli_satis_ui.messagebox.{ad}", lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
            for ad in ("showerror", "showwarning", "showinfo", "askyesno")
        ]
        for p in self._yamalar:
            p.start()

        import hizli_satis_ui

        self.pencere = hizli_satis_ui.HizliSatisPencere(self.root)
        self.pencere._urun_arama.arka_plan = False
        self.pencere._musteri_arama.arka_plan = False
        self._pompala(0.3)

    def tearDown(self):
        try:
            self.pencere._urun_arama.kapat()
            self.pencere._musteri_arama.kapat()
            self.pencere.destroy()
        except tk.TclError:
            pass
        for p in reversed(self._yamalar):
            p.stop()
        self.ortam.kapat()

    def _pompala(self, sure: float) -> None:
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            self.root.update()
            time.sleep(0.01)

    def _yaz(self, entry, metin: str, alan) -> None:
        entry.focus_force()
        entry.delete(0, "end")
        entry.insert(0, metin)
        entry.event_generate("<KeyRelease>", keysym=metin[-1:] or "a")
        bitis = time.monotonic() + 2.0
        while time.monotonic() < bitis:
            self.root.update()
            if alan.acik_mi():
                break
            time.sleep(0.01)
        self._pompala(0.35)

    def test_urun_tek_harfte_liste_acilmaz_iki_harfte_acilir(self):
        p = self.pencere
        self._yaz(p.arama_entry, "S", p._urun_arama)
        self.assertFalse(p._urun_arama.acik_mi())
        self._yaz(p.arama_entry, "Se", p._urun_arama)
        self.assertTrue(p._urun_arama.acik_mi())
        self.assertIn("VD035", [s.stok_kodu for s in p._urun_arama.sonuclar])

    def test_urun_adin_ortasindan_arar_ve_enter_sepete_ekler(self):
        p = self.pencere
        self._yaz(p.arama_entry, "sunta", p._urun_arama)
        self.assertTrue(p._urun_arama.acik_mi())
        self.assertEqual([s.stok_kodu for s in p._urun_arama.sonuclar], ["VD035"])
        self.assertEqual(p._urun_arama.secili, 0)

        p.arama_entry.event_generate("<Return>")
        self._pompala(0.2)
        self.assertEqual([s.stok_kodu for s in p.sepet_model.satirlar], ["VD035"])
        self.assertEqual(p.sepet_model.satirlar[0].miktar, Decimal("1"))
        self.assertEqual(p.arama_entry.get(), "")
        self.assertFalse(p._urun_arama.acik_mi())
        self.assertEqual(self.mesajlar, [])

    def test_urun_turkce_harf_ve_fare_secimi(self):
        p = self.pencere
        self._yaz(p.arama_entry, "MENTEŞ", p._urun_arama)
        self.assertEqual([s.stok_kodu for s in p._urun_arama.sonuclar], ["MN010"])
        p._urun_arama.sec(0)
        self._pompala(0.2)
        self.assertEqual([s.stok_kodu for s in p.sepet_model.satirlar], ["MN010"])

    def test_arama_kutusunda_delete_ve_eksi_sepeti_degistirmez(self):
        p = self.pencere
        self._yaz(p.arama_entry, "sunta", p._urun_arama)
        p.arama_entry.event_generate("<Return>")
        self._pompala(0.2)
        p.sepet.selection_set("0")
        p.arama_entry.focus_force()
        self._pompala(0.1)
        p.arama_entry.event_generate("<Delete>")
        p.arama_entry.event_generate("<KeyPress-minus>")
        self._pompala(0.1)
        self.assertEqual(len(p.sepet_model.satirlar), 1)
        self.assertEqual(p.sepet_model.satirlar[0].miktar, Decimal("1"))

    def test_musteri_iki_harfte_listeler_ve_secim_kutuyu_doldurur(self):
        p = self.pencere
        self._yaz(p.musteri_entry, "o", p._musteri_arama)
        self.assertFalse(p._musteri_arama.acik_mi())

        self._yaz(p.musteri_entry, "obil", p._musteri_arama)
        self.assertTrue(p._musteri_arama.acik_mi())
        self.assertEqual([c.cari_kodu for c in p._musteri_arama.sonuclar], ["M777"])

        p.musteri_entry.event_generate("<Return>")
        self._pompala(0.3)
        self.assertEqual(p.secili_cari.get("cari_kodu"), "M777")
        self.assertEqual(p.musteri_entry.get(), "M777 — AHMET YILMAZ MOBİLYA")
        self.assertFalse(p._musteri_arama.acik_mi())
        self.assertEqual(self.mesajlar, [])

    def test_musteri_secilmeden_cikilirsa_eski_musteri_geri_gelir(self):
        p = self.pencere
        onceki = p.musteri_entry.get()
        self._yaz(p.musteri_entry, "yılmaz", p._musteri_arama)
        self.assertTrue(p._musteri_arama.acik_mi())
        p.barkod_entry.focus_force()
        self._pompala(0.6)
        self.assertFalse(p._musteri_arama.acik_mi())
        self.assertEqual(p.musteri_entry.get(), onceki)


if __name__ == "__main__":
    unittest.main()
