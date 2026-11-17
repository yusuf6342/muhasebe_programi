"""Cari kart karşı taraf arama + KK çekim fişi aranabilir seçim."""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _SahteCari:
    def __init__(self, cid, kod, unvan, tur="Müşteri", aktif=True, ust=None):
        self.id = cid
        self.cari_kodu = kod
        self.unvan = unvan
        self.cari_turu = tur
        self.aktif = aktif
        self.ust_cari_id = ust
        self.is_deleted = False
        self.telefon = ""
        self.musteri_grubu = ""


class CariKarsiTarafAramaTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_hizli_menude_karsi_taraf_ara_var(self):
        from cari_kart_ui import CariDialog

        self.assertTrue(hasattr(CariDialog, "karsi_taraf_ara"))
        with patch.object(CariDialog, "_onceki_kartlari_kapat", return_value=True), patch.object(
            CariDialog, "grab_set"
        ), patch.object(CariDialog, "yenile"), patch.object(
            CariDialog, "_alanlari_doldur"
        ), patch.object(CariDialog, "_kirli_izlemeyi_bagla"), patch.object(
            CariDialog, "_form_snapshot", return_value=""
        ), patch.object(CariDialog, "_baslik_rozetlerini_guncelle"), patch.object(
            CariDialog, "_uyari_bandini_guncelle"
        ), patch.object(CariDialog, "_cari_pencere_boyutlandirma_ac"), patch.object(
            CariDialog, "_ust_baslik_olustur"
        ), patch.object(CariDialog, "_ana_kolonlari_olustur"), patch.object(
            CariDialog, "_detay_seridini_olustur"
        ), patch.object(CariDialog, "_hareket_tablosunu_olustur"), patch(
            "cari_kart_ui.stil_uygula"
        ):
            # Minimal iskelet: yalnız menü maddelerini doğrula
            d = object.__new__(CariDialog)
            d.tedarikci_modu = False
            d.cari = None
            d._hizli_islem_maddelerini_hazirla()
            basliklar = [b for b, _k, _i in d._hizli_islem_maddeleri]
            self.assertIn("Tedarikçi Ara", basliklar)

            t = object.__new__(CariDialog)
            t.tedarikci_modu = True
            t.cari = None
            t._hizli_islem_maddelerini_hazirla()
            basliklar_t = [b for b, _k, _i in t._hizli_islem_maddeleri]
            self.assertIn("Müşteri Ara", basliklar_t)

    def test_musteri_secim_dialog_tur_filtresi_ve_kolonlar(self):
        import app as app_mod

        m1 = _SahteCari(1, "C001", "Alpha Müşteri", "Müşteri")
        m2 = _SahteCari(2, "C002", "Beta Alt", "Müşteri", ust=1)
        with patch.object(app_mod.MusteriSecimDialog, "grab_set"), patch.object(
            app_mod.CariService, "getir", return_value=m1
        ):
            dlg = app_mod.MusteriSecimDialog(
                self.root,
                musteriler=[m1, m2],
                bakiyeler={1: 100, 2: -50},
                canli_arama=True,
                cari_turu="Müşteri",
                baslik="Müşteri Ara",
                kayit_adi="müşteri",
            )
            self.assertFalse(dlg._tum_turler.get())
            self.assertEqual(dlg._etkin_cari_turu(), "Müşteri")
            self.assertIn("hesap", dlg.tablo["columns"])
            self.assertTrue(dlg._cari_hesap_bilgi(m2).startswith("Alt →"))
            dlg._tum_turler.set(True)
            self.assertEqual(dlg._etkin_cari_turu(), "EVRAK")
            # Esc / iptal result None
            self.assertIsNone(dlg.result)
            dlg.destroy()

    def test_kk_cekimi_ara_dugmeleri_kimlik_ve_iptal_korur(self):
        import app as app_mod

        m = _SahteCari(10, "M10", "Müşteri On", "Müşteri")
        t = _SahteCari(20, "T20", "Tedarikçi Yirmi", "Tedarikçi")
        m2 = _SahteCari(11, "M11", "Müşteri Onbir", "Müşteri")

        with patch.object(app_mod.KkCekimiDialog, "grab_set"), patch.object(
            app_mod.CariService, "aktif_musteriler", return_value=[m, m2]
        ), patch.object(
            app_mod.CariService, "aktif_tedarikciler", return_value=[t]
        ), patch.object(
            app_mod.CariService, "aktif_cariler", return_value=[m, m2, t]
        ), patch.object(
            app_mod.CariService, "listele", return_value=[
                {"cari": m, "bakiye": 0},
                {"cari": m2, "bakiye": 0},
                {"cari": t, "bakiye": 0},
            ]
        ), patch.object(
            app_mod.CariService, "musteri_bakiyeleri_toplu", return_value={10: 0, 11: 0, 20: 0}
        ), patch.object(app_mod.CariService, "getir", side_effect=lambda cid: {10: m, 11: m2, 20: t}.get(cid)):
            d = app_mod.KkCekimiDialog(self.root, musteri_id=m.id, tedarikci_id=t.id)
            self.assertTrue(hasattr(d, "_musteri_ara"))
            self.assertTrue(hasattr(d, "_tedarikci_ara"))
            self.assertEqual(d._musteri_id, m.id)
            self.assertEqual(d._tedarikci_id, t.id)
            self.assertEqual(d.title(), d.BASLIK_YENI)
            self.assertEqual(d.girdiler["musteri"].get(), "Müşteri On")
            self.assertEqual(d.girdiler["tedarikci"].get(), "Tedarikçi Yirmi")
            self.assertNotIn("M10", d.girdiler["musteri"].get())
            self.assertNotIn("T20", d.girdiler["tedarikci"].get())
            self.assertEqual(d._tedarikci_arama.min_harf, 1)
            self.assertTrue(d._tedarikci_arama.yalniz_unvan)
            once_m, once_t = d._musteri_id, d._tedarikci_id
            d.girdiler["tutar"].delete(0, "end")
            d.girdiler["tutar"].insert(0, "125,50")
            d.girdiler["banka"].delete(0, "end")
            d.girdiler["banka"].insert(0, "TestBanka")

            with patch.object(app_mod, "MusteriSecimDialog") as Sahte:
                ornek = MagicMock()
                ornek.result = None
                Sahte.return_value = ornek
                d.wait_window = lambda *_a, **_k: None
                d._musteri_ara()

            self.assertEqual(d._musteri_id, once_m)
            self.assertEqual(d._tedarikci_id, once_t)
            self.assertIn("125", d.girdiler["tutar"].get())
            self.assertEqual(d.girdiler["banka"].get(), "TestBanka")

            d._taraf_sec("musteri", m2)
            self.assertEqual(d._musteri_id, m2.id)
            self.assertEqual(d._secili_cari("musteri").id, m2.id)
            self.assertEqual(d.girdiler["musteri"].get(), "Müşteri Onbir")
            self.assertEqual(d._tedarikci_id, once_t)
            d.destroy()


if __name__ == "__main__":
    unittest.main()
