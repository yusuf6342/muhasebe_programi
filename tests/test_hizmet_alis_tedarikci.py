"""Hizmet Alış (Gider) faturası — Tedarikçi alanı aranabilir seçici + kayıt/yeniden açılış."""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.database import get_session
from database.hizmet_faturasi_service import HizmetFaturasiService
from database.hizmet_service import HizmetService
from database.models.cari import Cari
from tests.stok_test_ortami import StokOrtami

import hizmet_fatura_ui
from hizmet_fatura_ui import HizmetFaturaDialog


class HizmetAlisTedarikciTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("hizmet_ted")
        with get_session() as s:
            s.add(
                Cari(
                    cari_kodu="T002",
                    unvan="Çelik Yapı Malzemeleri Ltd",
                    cari_turu="Tedarikçi",
                    aktif=True,
                )
            )
            s.add(
                Cari(
                    cari_kodu="T003",
                    unvan="Çelik Teknik Servis A.Ş.",
                    cari_turu="Tedarikçi",
                    aktif=True,
                )
            )
            s.add(
                Cari(
                    cari_kodu="M002",
                    unvan="Çelik Müşteri",
                    cari_turu="Müşteri",
                    aktif=True,
                )
            )
            s.commit()
            self.ids = {
                c.cari_kodu: c.id
                for c in s.scalars(select(Cari).where(Cari.cari_kodu.in_(["T001", "T002", "T003", "M002"])))
            }
        HizmetService._schema_hazir = False
        HizmetService.ensure_schema()
        HizmetService.kaydet(
            {
                "hizmet_kodu": "HZM-NAK",
                "hizmet_adi": "Nakliye",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
                "birim": "Adet",
                "alis_fiyati": Decimal("100"),
                "kdv_orani": 20,
                "aktif": True,
            }
        )
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.ort.kapat()
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.mesajlar = []
        self._yamalar = [
            patch.object(
                hizmet_fatura_ui.messagebox,
                ad,
                side_effect=lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)),
            )
            for ad in ("showerror", "showinfo", "showwarning", "askyesno")
        ]
        for y in self._yamalar:
            y.start()

    def tearDown(self):
        for y in getattr(self, "_yamalar", []):
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        self.ort.kapat()

    def _dialog(self, **ek):
        d = HizmetFaturaDialog(self.root, hizmet_turu="GIDER", **ek)
        d.update_idletasks()
        return d

    def _ara(self, d, metin: str):
        d.cari_var.set(metin)
        d._cari_arama.ara(metin, senkron=True)
        return list(d._cari_arama.sonuclar)

    def test_etiket_tedarikci_ve_yazilabilir(self):
        d = self._dialog()
        try:
            self.assertEqual(d.cari_etiket, "Tedarikçi")
            self.assertEqual(str(d.cari_entry.cget("state")), "normal")
            self.assertEqual(d._cari_arama.cari_turu, "Tedarikçi")
            self.assertIsNone(d._secili_cari_id)
        finally:
            d.destroy()

    def test_unvan_ve_kod_ile_turkce_arama_sonuclarda_kod_unvan(self):
        d = self._dialog()
        try:
            for sorgu in ("çelik", "CELIK", "ÇELİK", "yapi", "teknik"):
                sonuclar = self._ara(d, sorgu)
                kodlar = [c.cari_kodu for c in sonuclar]
                self.assertTrue(kodlar, msg=sorgu)
                self.assertNotIn("M002", kodlar, msg=f"müşteri sızmamalı: {sorgu}")
                self.assertTrue(
                    {"T002", "T003"} & set(kodlar) or "T001" in kodlar,
                    msg=f"{sorgu} → {kodlar}",
                )
                for i, cari in enumerate(sonuclar):
                    satir = d._cari_arama._satir(cari)
                    self.assertEqual(satir[0], cari.cari_kodu or "")
                    self.assertEqual(satir[1], cari.unvan or "")

            # Cari kodu ile
            sonuclar = self._ara(d, "T002")
            self.assertEqual([c.cari_kodu for c in sonuclar], ["T002"])

            # Benzer unvanlardan birini seç
            sonuclar = self._ara(d, "çelik")
            hedef = next(c for c in sonuclar if c.cari_kodu == "T003")
            indeks = next(i for i, c in enumerate(sonuclar) if c.cari_kodu == "T003")
            d._cari_arama.sec(indeks)
            self.assertEqual(d._secili_cari_id, self.ids["T003"])
            self.assertEqual(d.cari_var.get(), hedef.unvan)
            self.assertIn("T003", d._cari_kod_lbl.cget("text"))
        finally:
            d.destroy()

    def test_kaydet_ve_yeniden_acinca_tedarikci_secili(self):
        d = self._dialog()
        try:
            sonuclar = self._ara(d, "yapi")
            hedef = next(c for c in sonuclar if c.cari_kodu == "T002")
            d._cari_arama.sec(next(i for i, c in enumerate(sonuclar) if c.id == hedef.id))
            d.satirlar.append(
                {
                    "hizmet_kodu": "HZM-NAK",
                    "hizmet_adi": "Nakliye",
                    "miktar": Decimal("1"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("250"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            )
            d.kaydet()
            self.assertIsNotNone(d.result)
            fatura_id = int(d.result.id)
            self.assertEqual(int(d.result.cari_id), self.ids["T002"])
        finally:
            try:
                d.destroy()
            except tk.TclError:
                pass

        d2 = self._dialog(fatura_id=fatura_id)
        try:
            self.assertEqual(d2.cari_etiket, "Tedarikçi")
            self.assertEqual(d2._secili_cari_id, self.ids["T002"])
            self.assertEqual(d2.cari_var.get(), "Çelik Yapı Malzemeleri Ltd")
            self.assertIn("T002", d2._cari_kod_lbl.cget("text"))
            kayit = HizmetFaturasiService.getir(fatura_id)
            self.assertEqual(kayit.cari.cari_kodu, "T002")
        finally:
            d2.destroy()


if __name__ == "__main__":
    unittest.main()
