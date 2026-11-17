"""Hizmet Alış: satır açıklaması, toplamlar, tedarikçi ödeme, stok kartı reddi."""

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
from database.finans_service import FinansService
from database.hizmet_faturasi_service import ODEME_SEKILLERI, HizmetFaturasiService
from database.hizmet_service import HizmetService
from database.models.cari import Cari
from database.models.stok import StokKarti
from tests.stok_test_ortami import StokOrtami

import hizmet_fatura_ui
from hizmet_fatura_ui import HizmetFaturaDialog, HizmetOdemeDialog


class HizmetAlisAciklamaOdemeTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("hizmet_ack")
        with get_session() as s:
            s.add(
                Cari(
                    cari_kodu="T010",
                    unvan="Hizmet Tedarik A.Ş.",
                    cari_turu="Tedarikçi",
                    aktif=True,
                )
            )
            s.add(
                StokKarti(
                    stok_kodu="STK-X",
                    stok_adi="Stok Ürün",
                    birim="Adet",
                    aktif=True,
                )
            )
            s.commit()
            self.tedarikci_id = s.scalar(
                select(Cari.id).where(Cari.cari_kodu == "T010")
            )
        HizmetService._schema_hazir = False
        HizmetService.ensure_schema()
        for kod, ad, fiyat in (
            ("HZM-A", "Nakliye Hizmeti", Decimal("100")),
            ("HZM-B", "Montaj Hizmeti", Decimal("200")),
        ):
            HizmetService.kaydet(
                {
                    "hizmet_kodu": kod,
                    "hizmet_adi": ad,
                    "hizmet_turu": "GIDER",
                    "gider_sinifi": "ISLETME",
                    "birim": "Adet",
                    "alis_fiyati": fiyat,
                    "kdv_orani": 20,
                    "aktif": True,
                }
            )
        try:
            FinansService.hesap_kaydet(
                {"hesap_adi": "ANA KASA", "hesap_turu": "KASA", "aktif": True}
            )
        except Exception:
            pass
        hesaplar = [h.hesap_adi for h in FinansService.hesaplar()]
        self.hesap_adi = hesaplar[0] if hesaplar else "ANA KASA"
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

    def test_aciklama_toplam_odeme_ve_hizmet_dogrulama(self):
        d = self._dialog()
        try:
            self.assertEqual(d.cari_etiket, "Tedarikçi")
            self.assertTrue(hasattr(d, "_ozet_lbls"))
            for k in ("ara", "iskonto", "matrah", "kdv", "net", "odenen", "kalan"):
                self.assertIn(k, d._ozet_lbls)

            # Stok kodu satıra eklenemez
            d.satir_girdileri["hizmet_kodu"].insert(0, "STK-X")
            d.satir_girdileri["hizmet_adi"].insert(0, "Stok Ürün")
            d.satir_ekle()
            self.assertFalse(d.satirlar)
            self.assertTrue(any("hizmet" in str(a).lower() for _ad, a in self.mesajlar))

            d._cari_secildi(
                type("C", (), {"id": self.tedarikci_id, "unvan": "Hizmet Tedarik A.Ş.", "cari_kodu": "T010", "cari_turu": "Tedarikçi"})()
            )
            d.satirlar = [
                {
                    "hizmet_kodu": "HZM-A",
                    "hizmet_adi": "Nakliye Hizmeti",
                    "miktar": Decimal("1"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "aciklama": "Şehirler arası nakliye",
                },
                {
                    "hizmet_kodu": "HZM-B",
                    "hizmet_adi": "Montaj Hizmeti",
                    "miktar": Decimal("1"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("200"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "aciklama": "Kurulum açıklaması",
                },
            ]
            d._satir_listesini_yenile()
            # 100*1.2 + 200*1.2 = 360
            self.assertIn("360", d._ozet_lbls["net"].cget("text").replace(".", "").replace(",", ""))

            # Kısmi ödeme
            d.odemeler.append(
                {
                    "tarih": date.today(),
                    "tutar": Decimal("100"),
                    "odeme_sekli": ODEME_SEKILLERI[0],
                    "hesap": self.hesap_adi,
                    "aciklama": "kısmi",
                }
            )
            d._odeme_yenile()
            self.assertIn("100", d._ozet_lbls["odenen"].cget("text"))
            self.assertIn("260", d._ozet_lbls["kalan"].cget("text").replace(".", "").replace(",", ""))

            # Tam ödeme tamamı
            d.odemeler.append(
                {
                    "tarih": date.today(),
                    "tutar": Decimal("260"),
                    "odeme_sekli": ODEME_SEKILLERI[1],
                    "hesap": self.hesap_adi,
                    "aciklama": "kalan",
                }
            )
            d._odeme_yenile()
            self.assertEqual(len(d.odemeler), 2)

            d.kaydet()
            self.assertIsNotNone(d.result)
            fid = int(d.result.id)
        finally:
            try:
                d.destroy()
            except tk.TclError:
                pass

        d2 = self._dialog(fatura_id=fid)
        try:
            self.assertEqual(d2._secili_cari_id, self.tedarikci_id)
            self.assertEqual(len(d2.satirlar), 2)
            aciklamalar = {s["hizmet_kodu"]: s.get("aciklama") for s in d2.satirlar}
            self.assertEqual(aciklamalar["HZM-A"], "Şehirler arası nakliye")
            self.assertEqual(aciklamalar["HZM-B"], "Kurulum açıklaması")
            kayit = HizmetFaturasiService.getir(fid)
            self.assertEqual(float(kayit.odeme_tutari), 360.0)
            # Boş açıklamalı eski satır düzenlenebilir
            d2.satirlar[0]["aciklama"] = ""
            d2._satir_listesini_yenile()
            self.assertEqual(d2.satirlar[0].get("aciklama"), "")
        finally:
            d2.destroy()

    def test_odeme_dialog_varsayilan_sekil(self):
        d = HizmetOdemeDialog(self.root, gelir_mi=False, varsayilan_sekil="GÖNDERİLEN HAVALE")
        try:
            self.assertEqual(d.girdiler["odeme_sekli"].get(), "GÖNDERİLEN HAVALE")
            self.assertEqual(set(ODEME_SEKILLERI), {"KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME"})
        finally:
            d.destroy()


if __name__ == "__main__":
    unittest.main()
