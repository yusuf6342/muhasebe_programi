"""Satıştan iade: Kaydet/Onayla ekran akışı (geçici SQLite; canlı D2 yok).

Kök neden regresyonu: ölü girdiler['aciklama'] Entry → TclError; yalnızca ValueError yakalanıyordu.
"""
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

from database.database import get_session
from database.models.stok import StokHareketi
from database.models.cari import CariIslem
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from sqlalchemy import select, func
from tests import test_uzlasma_net_cari as _uz

D = Decimal


class SatisIadeKaydetOnaylaUiTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _uz._sokum(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.root.attributes("-alpha", 0.0)
        self._yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
        ]
        for y in self._yamalar:
            y.start()
        self.dlg = None

    def tearDown(self):
        try:
            if self.dlg is not None:
                self.dlg.destroy()
        except Exception:
            pass
        for y in reversed(self._yamalar):
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        _uz._sokum(self)

    def _pompala(self, n=12):
        for _ in range(n):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _ac_iade(self):
        import app

        self.dlg = app.SatisIadeFaturasiDialog(self.root, cari=self.musteri_id)
        self._pompala()
        return self.dlg

    def _kaynak_satis(self):
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 6, 1),
                "vade_tarihi": date(2026, 6, 1),
                "cari_id": self.musteri_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Masa",
                    "miktar": D("2"),
                    "birim": "Adet",
                    "birim_fiyat": D("100"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def test_olu_aciklama_entry_ile_toplama_tclerror_olmaz(self):
        """Eski bug: girdiler['aciklama'].get() ölü Entry'de TclError → Kaydet sessizce düşer."""
        d = self._ac_iade()
        ack = d.girdiler.get("aciklama")
        self.assertIsNotNone(ack)
        # Stub/ölü Entry simülasyonu
        try:
            ack.destroy()
        except tk.TclError:
            pass
        d.satirlar = [
            {
                "urun_kodu": "U001",
                "urun_adi": "Masa",
                "miktar": "1",
                "birim": "Adet",
                "birim_satis_fiyati": "100",
                "kdv_orani": "20",
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
            }
        ]
        # Düzeltme sonrası: TclError fırlatmamalı
        veriler, satirlar = d._iade_kayit_verilerini_topla()
        self.assertEqual(veriler["cari_id"], self.musteri_id)
        self.assertEqual(len(satirlar), 1)

    def test_olu_aciklama_ile_oval_kaydet_basarili(self):
        """Kayıt sonrası _iadeyi_doldur ölü Entry'ye yazınca Kaydet çökmesin (oval _birak)."""
        kaynak = self._kaynak_satis()
        d = self._ac_iade()
        try:
            d.girdiler["aciklama"].destroy()
        except tk.TclError:
            pass
        ks = kaynak.satirlar[0]
        d.satirlar = [
            {
                "urun_kodu": ks.urun_kodu,
                "urun_adi": ks.urun_adi,
                "miktar": "1",
                "birim": ks.birim or "Adet",
                "birim_satis_fiyati": str(ks.birim_fiyat),
                "kdv_orani": str(ks.kdv_orani or 20),
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
                "kaynak_fatura_satiri_id": ks.id,
                "onceki_fatura_no": kaynak.fatura_no,
            }
        ]
        d._satir_listesini_yenile()
        d.kaynak_map[kaynak.fatura_no] = kaynak
        d.kaynak.set(kaynak.fatura_no)

        with patch("tkinter.messagebox.showinfo") as si, patch(
            "tkinter.messagebox.showerror"
        ) as se, patch("tkinter.messagebox.showwarning") as sw, patch(
            "tkinter.messagebox.askyesno", return_value=True
        ):
            d.kaydet_btn._birak()
            self._pompala()
            self.assertFalse(se.called, se.call_args)
            self.assertTrue(si.called or sw.called, "başarı/uyarı yok")
            self.assertIsNotNone(d.iade)
            self.assertTrue(str(d.iade.iade_no).startswith("IAD-"))

    def test_kaydet_ve_onayla_ekran_akisi_kayit_korunur(self):
        kaynak = self._kaynak_satis()
        d = self._ac_iade()
        # Kaynak satır bağla
        ks = kaynak.satirlar[0]
        d.satirlar = [
            {
                "urun_kodu": ks.urun_kodu,
                "urun_adi": ks.urun_adi,
                "miktar": "1",
                "birim": ks.birim or "Adet",
                "birim_satis_fiyati": str(ks.birim_fiyat),
                "kdv_orani": str(ks.kdv_orani or 20),
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
                "kaynak_fatura_satiri_id": ks.id,
                "onceki_fatura_no": kaynak.fatura_no,
            }
        ]
        d._satir_listesini_yenile()
        d.kaynak_map[kaynak.fatura_no] = kaynak
        d.kaynak.set(kaynak.fatura_no)

        with patch("tkinter.messagebox.showinfo"), patch(
            "tkinter.messagebox.showerror"
        ) as se, patch("tkinter.messagebox.askyesno", return_value=True):
            ok = d._iade_kaydet_isle()
            self.assertTrue(ok, f"Kaydet başarısız; showerror={se.call_args}")
            self.assertIsNotNone(d.iade)
            iade_no = d.iade.iade_no
            iade_id = d.iade.id

        # Kapat / yeniden aç simülasyonu
        d.destroy()
        self.dlg = None
        import app

        self.dlg = app.SatisIadeFaturasiDialog(
            self.root, iade=SatisIadeFaturasiService.getir(iade_id)
        )
        self._pompala()
        self.assertEqual(self.dlg.iade.iade_no, iade_no)
        self.assertEqual(len(self.dlg.satirlar), 1)
        self.assertEqual(str(self.dlg.satirlar[0]["urun_kodu"]), ks.urun_kodu)

        # Onayla = aynı kayıt yolu (iade tek adımlı)
        with patch("tkinter.messagebox.showinfo"), patch(
            "tkinter.messagebox.showerror"
        ) as se2, patch("tkinter.messagebox.askyesno", return_value=True):
            self.dlg.onayla()
            self.assertFalse(se2.called, se2.call_args)

        with get_session() as s:
            stok = s.scalar(
                select(func.count())
                .select_from(StokHareketi)
                .where(StokHareketi.belge_no == iade_no)
            )
            cari = s.scalar(
                select(func.count())
                .select_from(CariIslem)
                .where(CariIslem.belge_no == iade_no)
            )
        self.assertGreaterEqual(stok, 1)
        self.assertGreaterEqual(cari, 1)

        # Tekrar kaydet → mükerrer stok/cari şişmesin (güncelleme)
        once_stok, once_cari = stok, cari
        with patch("tkinter.messagebox.showinfo"), patch(
            "tkinter.messagebox.askyesno", return_value=True
        ):
            self.dlg._iade_kaydet_isle()
        with get_session() as s:
            stok2 = s.scalar(
                select(func.count())
                .select_from(StokHareketi)
                .where(StokHareketi.belge_no == iade_no)
            )
            cari2 = s.scalar(
                select(func.count())
                .select_from(CariIslem)
                .where(CariIslem.belge_no == iade_no)
            )
        self.assertEqual(stok2, once_stok)
        self.assertEqual(cari2, once_cari)


if __name__ == "__main__":
    unittest.main()
