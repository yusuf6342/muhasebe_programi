"""Firma seçim yardımcıları — birim testleri (GUI olmadan)."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from firma_secim_theme import (
    firmalari_filtrele,
    kart_sutun_sayisi,
    konum_metni,
    tr_normalize,
    varsayilan_secim_id,
)


@dataclass
class FakeFirma:
    id: int
    unvan: str
    firma_kodu: str = ""
    vergi_no: str | None = None
    kisa_ad: str | None = None


class TestTrNormalize(unittest.TestCase):
    def test_turkce_i(self):
        self.assertEqual(tr_normalize("İSTANBUL"), tr_normalize("istanbul"))
        self.assertIn(tr_normalize("ş"), tr_normalize("ŞİRKET"))


class TestFiltre(unittest.TestCase):
    def setUp(self):
        self.firmalar = [
            FakeFirma(1, "Ray Mobilya A.Ş.", "RAY", "1234567890"),
            FakeFirma(2, "Ankara Ticaret", "ANK", "999"),
            FakeFirma(3, "İzmir Deniz", "IZM", None),
        ]

    def test_bos_sorgu_hepsi(self):
        self.assertEqual(len(firmalari_filtrele(self.firmalar, "")), 3)

    def test_unvan(self):
        sonuc = firmalari_filtrele(self.firmalar, "ankara")
        self.assertEqual([f.id for f in sonuc], [2])

    def test_kod(self):
        sonuc = firmalari_filtrele(self.firmalar, "ray")
        self.assertEqual([f.id for f in sonuc], [1])

    def test_vergi(self):
        sonuc = firmalari_filtrele(self.firmalar, "123456")
        self.assertEqual([f.id for f in sonuc], [1])

    def test_turkce_izmir(self):
        sonuc = firmalari_filtrele(self.firmalar, "izmir")
        self.assertEqual([f.id for f in sonuc], [3])


class TestVarsayilanSecim(unittest.TestCase):
    def test_son_kullanilan_oncelikli(self):
        firmalar = [FakeFirma(1, "A"), FakeFirma(2, "B"), FakeFirma(3, "C")]
        self.assertEqual(
            varsayilan_secim_id(firmalar, son_id=3, varsayilan_id=1),
            3,
        )

    def test_varsayilan(self):
        firmalar = [FakeFirma(1, "A"), FakeFirma(2, "B")]
        self.assertEqual(
            varsayilan_secim_id(firmalar, son_id=None, varsayilan_id=2),
            2,
        )

    def test_ilk(self):
        firmalar = [FakeFirma(5, "A"), FakeFirma(6, "B")]
        self.assertEqual(varsayilan_secim_id(firmalar), 5)

    def test_bos(self):
        self.assertIsNone(varsayilan_secim_id([]))


class TestKartSutun(unittest.TestCase):
    def test_tek(self):
        self.assertEqual(kart_sutun_sayisi(1, 1366), 1)

    def test_iki(self):
        self.assertEqual(kart_sutun_sayisi(2, 1100), 2)

    def test_cok(self):
        self.assertEqual(kart_sutun_sayisi(8, 1366), 3)

    def test_dar(self):
        self.assertEqual(kart_sutun_sayisi(5, 640), 1)


class TestKonum(unittest.TestCase):
    def test_il_ilce(self):
        self.assertEqual(konum_metni(il="İstanbul", ilce="Kadıköy"), "Kadıköy / İstanbul")

    def test_adres_yedek(self):
        self.assertTrue(konum_metni(adres="Atatürk Cad. No:1").startswith("Atatürk"))


class TestImportAuth(unittest.TestCase):
    def test_modul_import(self):
        import auth_ui
        import firma_secim_theme

        self.assertTrue(hasattr(auth_ui, "FirmaSecimDialog"))
        self.assertTrue(hasattr(auth_ui, "firma_oturumu_ac"))
        self.assertTrue(hasattr(auth_ui, "firma_ozet"))
        self.assertEqual(firma_secim_theme.COLOR_NAVY, "#102A43")


class TestSmokeDialog(unittest.TestCase):
    def test_dialog_acilip_kapanir(self):
        import tkinter as tk

        from auth_ui import FirmaSecimDialog

        root = tk.Tk()
        root.withdraw()
        try:
            # Oturum yokken liste boş kalabilir — diyalog yine de kurulmalı
            dlg = FirmaSecimDialog(root, yeni_firma_izinli=False)

            def kapat():
                try:
                    dlg._iptal()
                except Exception:
                    try:
                        dlg.destroy()
                    except Exception:
                        pass

            root.after(200, kapat)
            root.wait_window(dlg)
            self.assertIsNone(dlg.result)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
