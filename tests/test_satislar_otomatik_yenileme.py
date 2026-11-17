"""Ana ekran Satışlar otomatik yenileme — izole SQLite; canlı D2 yok.

Aynı süreç + ayrı session (diğer terminal simülasyonu) ile imza/yenileme süresi ölçülür.
"""
from __future__ import annotations

import os
import tempfile
import time
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from tests.stok_test_ortami import StokOrtami

import giris_paneli_ui as gp
from database import giris_ozet_service as go
from database.satis_faturasi_service import SatisFaturasiService

D = Decimal


def _senkron(widget, is_fn, on_ok=None, on_err=None):
    try:
        sonuc = is_fn()
    except Exception as hata:  # noqa: BLE001
        if on_err:
            on_err(hata)
        return
    if on_ok:
        on_ok(sonuc)


class SatislarOtomatikYenilemeTest(unittest.TestCase):
    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="satis_yenile_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("satis_yenile")
        go.onbellegi_temizle()
        try:
            self.kok = tk.Tk()
        except tk.TclError as hata:
            self.o.kapat()
            self._env.stop()
            self.skipTest(f"Tk yok: {hata}")
        self.kok.withdraw()
        self.kok.icerik = tk.Frame(self.kok)
        self.kok.icerik.pack(fill="both", expand=True)
        self.kok._menu_islemi = lambda k: None
        self._bg = patch("ui_bg.arka_planda", _senkron)
        self._bg.start()
        self._yokla_ms = patch.object(gp, "YOKLAMA_MS", 200)
        self._yokla_ms.start()

    def tearDown(self):
        self._yokla_ms.stop()
        self._bg.stop()
        try:
            self.kok.destroy()
        except Exception:
            pass
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()
        go.onbellegi_temizle()

    def _fatura(self, tutar=1000, *, onayla=True):
        bugun = date.today()
        if onayla:
            self.o.alis(10, 10, bugun)
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": bugun,
                "vade_tarihi": bugun,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": D(str(tutar)),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return f

    def test_imza_ayri_session_degisimini_gorur(self):
        """Diğer terminal simülasyonu: aynı DB, yeni satış kaydı → imza değişir."""
        once = go.satis_degisim_imzasi()
        self._fatura(500, onayla=False)
        sonra = go.satis_degisim_imzasi()
        self.assertNotEqual(once, sonra)

    def test_giris_satislari_ayni_oturum_otomatik_yenilenir(self):
        # withdraw kökte winfo_ismapped False olabilir — yoklama yolunu açık tut
        with patch.object(gp.GirisPaneli, "winfo_ismapped", return_value=True):
            p = gp.GirisPaneli(self.kok.icerik, self.kok)
            p.pack(fill="both", expand=True)
            p.yenile()
            self.kok.update()
            once_net = p._sonuc["satis"]["satirlar"]["bugun"]["net"]
            once_imza = p._imza
            t0 = time.perf_counter()
            self._fatura(1000)
            # Yerel sayaç yolu: _yokla doğrudan
            p._yokla()
            self.kok.update()
            if p._sonuc["satis"]["satirlar"]["bugun"]["net"] == once_net:
                # DB imza yolu (diğer terminal simülasyonu)
                p._imza_geldi(go.satis_degisim_imzasi())
                self.kok.update()
            sure = time.perf_counter() - t0
            yeni_net = p._sonuc["satis"]["satirlar"]["bugun"]["net"]
            self.assertNotEqual(yeni_net, once_net)
            self.assertEqual(yeni_net, once_net + D("1200.00"))
            self.assertNotEqual(p._imza, once_imza)
            self.assertLessEqual(sure, 5.0, f"yenileme {sure:.2f}s > 5s")
            self.assertEqual(p.tarih_e.get().strip(), date.today().strftime("%d.%m.%Y"))
            self.assertEqual(p.sube_cb.get(), "Tümü")

    def test_filtre_korunur_yenilemede(self):
        p = gp.GirisPaneli(self.kok.icerik, self.kok)
        p.pack(fill="both", expand=True)
        p.yenile()
        p.sube_cb.set("Tümü")
        tarih = p.tarih_e.get()
        p.yenile(zorla=True)
        self.assertEqual(p.tarih_e.get(), tarih)
        self.assertEqual(p.sube_cb.get(), "Tümü")


if __name__ == "__main__":
    unittest.main()
