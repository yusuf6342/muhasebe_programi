"""Satıştan iade: Kâr Analizi yok, Onaylı düğme, müşteriye iade ödemesi."""

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

from database.finans_service import FinansService
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from tests import test_uzlasma_net_cari as _uz

D = Decimal


class SatisIadeOnayOdemeUiTest(unittest.TestCase):
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
        # Kasa hesabı
        try:
            FinansService.hesap_kaydet(
                {"hesap_adi": "ANA KASA", "hesap_turu": "KASA", "aktif": True}
            )
        except Exception:
            pass

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
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": D("100"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def test_kar_analizi_yok_onayli_ve_iade_odeme(self):
        import app
        import fatura_tema as ftema

        kaynak = self._kaynak_satis()
        self.dlg = app.SatisIadeFaturasiDialog(self.root, cari=self.musteri_id, kaynak_fatura=kaynak)
        self._pompala()
        d = self.dlg

        # Analiz / Kâr Analizi menüsü yok
        self.assertIsNone(getattr(d, "_analiz_menu", "x") if d._analiz_menu is None else d._analiz_menu)
        mb = getattr(d, "_analiz_mb", None)
        if mb is not None:
            self.assertFalse(bool(mb.winfo_ismapped()))

        # Kâr Analizi diğer menüde de olmamalı
        diger = getattr(d, "_diger_menu", None)
        if diger is not None:
            etiketler = []
            try:
                son = diger.index("end")
                if son is not None:
                    for i in range(son + 1):
                        try:
                            etiketler.append(diger.entrycget(i, "label"))
                        except tk.TclError:
                            pass
            except tk.TclError:
                pass
            self.assertFalse(any("Kâr" in str(e) or "Kar" in str(e) for e in etiketler))

        # Kaydet → Onaylı
        self.assertTrue(d._iade_kaydet_isle())
        self._pompala()
        btn = d.kaydet_onay_btn
        if isinstance(btn, ftema.FaturaOvalButon):
            self.assertEqual(btn._metin, "Onaylı")
            self.assertEqual(btn._rol, "onayli")
        else:
            self.assertEqual(str(btn.cget("text")), "Onaylı")

        # Yeniden açılışta Onaylı
        iade_id = int(d.iade.id)
        d.destroy()
        self.dlg = None
        iade = SatisIadeFaturasiService.getir(iade_id)
        self.dlg = app.SatisIadeFaturasiDialog(self.root, iade=iade)
        self._pompala()
        d = self.dlg
        btn = d.kaydet_onay_btn
        if isinstance(btn, ftema.FaturaOvalButon):
            self.assertEqual(btn._metin, "Onaylı")
        else:
            self.assertEqual(str(btn.cget("text")), "Onaylı")

        # İade ödemesi menüsü
        self.assertIsNotNone(getattr(d, "_iade_odeme_mb", None))
        hesaplar = [h.hesap_adi for h in FinansService.hesaplar()]
        self.assertTrue(hesaplar)
        once = Decimal(str(d.iade.iade_odeme_tutari or 0))
        d._iade_odeme_tutari = once + D("50")
        d._iade_odeme_sekli = "NAKİT / KASA"
        d._iade_odeme_hesabi = hesaplar[0]
        self.assertTrue(d._iade_kaydet_isle())
        guncel = SatisIadeFaturasiService.getir(iade_id)
        self.assertEqual(Decimal(str(guncel.iade_odeme_tutari)), once + D("50"))
        self.assertEqual(guncel.iade_odeme_sekli, "NAKİT / KASA")
        self.assertEqual(guncel.cari_id, self.musteri_id)


if __name__ == "__main__":
    unittest.main()
