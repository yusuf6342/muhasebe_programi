"""Cari beş ana tür, bakiye yönü ve alış Onaylı düğmesi — birim testler."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CariAnaTurSeedTest(unittest.TestCase):
    def test_bes_ana_kod(self):
        from database.kart_turu_service import CARI_ANA_KODLARI, _CARI_ANA_SEED

        self.assertEqual(len(CARI_ANA_KODLARI), 5)
        self.assertEqual(
            tuple(k for k, *_ in _CARI_ANA_SEED),
            CARI_ANA_KODLARI,
        )
        self.assertNotIn("MUSTERI_TEDARIKCI", CARI_ANA_KODLARI)

    def test_eski_esleme(self):
        from database.kart_turu_service import KartTuruService

        self.assertEqual(KartTuruService.cari_ana_kod_esle("Tedarikçi"), "TEDARIKCI")
        self.assertEqual(KartTuruService.cari_ana_kod_esle("Personel"), "PERSONEL")
        self.assertEqual(KartTuruService.cari_ana_kod_esle("Resmi Kurumlar"), "RESMI_KURUMLAR")
        self.assertEqual(
            KartTuruService.cari_ana_kod_esle("Düzenleyici Hesaplar"), "DUZENLEYICI"
        )
        self.assertIsNone(KartTuruService.cari_ana_kod_esle("Müşteri/Tedarikçi"))
        self.assertIsNone(KartTuruService.cari_ana_kod_esle("Diğer"))

    def test_diger_liste_ve_evo_esleme(self):
        from database.kart_turu_service import (
            DIGER_CARI_ANA_KODLARI,
            ESLEME_GEREKEN_ETIKET,
            KartTuruService,
        )

        self.assertEqual(len(DIGER_CARI_ANA_KODLARI), 3)
        self.assertTrue(KartTuruService.digger_liste_mi("Diğer"))
        self.assertTrue(KartTuruService.digger_liste_mi("DIGER"))
        self.assertFalse(KartTuruService.digger_liste_mi("Personel"))
        self.assertEqual(
            KartTuruService.evo_grup_ana_kod("Evo: DÜZENLEYİCİ"), "DUZENLEYICI"
        )
        self.assertEqual(
            KartTuruService.evo_grup_ana_kod("Evo: RESMİ KURUMLAR"), "RESMI_KURUMLAR"
        )
        self.assertEqual(KartTuruService.evo_grup_ana_kod("Evo: PERSONEL"), "PERSONEL")
        self.assertIsNone(KartTuruService.evo_grup_ana_kod("Evo: Türü belirtilmemiş"))
        self.assertTrue(
            KartTuruService.cari_esleme_gereken_mi(
                cari_turu="Müşteri",
                ana_kod="MUSTERI",
                musteri_grubu="Evo: Türü belirtilmemiş",
            )
        )
        self.assertFalse(
            KartTuruService.cari_esleme_gereken_mi(
                cari_turu="Personel",
                ana_kod="PERSONEL",
                musteri_grubu="Evo: PERSONEL",
            )
        )
        self.assertTrue(KartTuruService.esleme_gereken_filtre_mi(ESLEME_GEREKEN_ETIKET))

    def test_cari_rol_metni(self):
        from database.kart_turu_service import KartTuruService
        from types import SimpleNamespace

        self.assertEqual(
            KartTuruService.cari_rol_metni(
                SimpleNamespace(muhasebe_rol="RESMI_KURUMLAR", kod="RESMI_KURUMLAR", ad="Resmi Kurumlar")
            ),
            "Resmi Kurumlar",
        )


class BakiyeYonTest(unittest.TestCase):
    def test_oz_metal_alacakli(self):
        """net = borç − alacak = −20421 → (A) Alacaklı; tedarikçi modu ters çevirmez."""
        from cari_borc_alacak_ozet import bakiye_yon_eki, kalan_bakiye_metni
        from database.cari_bakiye_service import bakiye_yon_kisa

        net = Decimal("-20421.00")
        self.assertEqual(bakiye_yon_kisa(net, tedarikci_modu=True), "Alacaklı")
        self.assertEqual(bakiye_yon_eki(net, tedarikci_modu=True), "(A)")
        self.assertEqual(
            kalan_bakiye_metni(net, tedarikci_modu=True),
            "20.421,00 TL (A)",
        )

    def test_borclu_tedarikci(self):
        from database.cari_bakiye_service import bakiye_yon_kisa

        self.assertEqual(
            bakiye_yon_kisa(Decimal("100"), tedarikci_modu=True), "Borçlu"
        )

    def test_tedarikci_alacak_rengi_siyah_musteri_yesil(self):
        """Tedarikçi (A) siyah; müşteri (A) yeşil; tutar/metin aynı."""
        from cari_borc_alacak_ozet import (
            BASARI,
            TEDARIKCI_ALACAK_RENK,
            bakiye_rengi,
            ozet_metinleri,
            tedarikci_ana_turu_mu,
        )
        from cari_kart_tema import BASARI as TEMA_BASARI

        net = Decimal("-25650.00")
        self.assertEqual(bakiye_rengi(net, tedarikci_modu=True), TEDARIKCI_ALACAK_RENK)
        self.assertEqual(TEDARIKCI_ALACAK_RENK, "#000000")
        self.assertEqual(bakiye_rengi(net, tedarikci_modu=False), BASARI)
        self.assertEqual(BASARI, TEMA_BASARI)
        # Kod öneki değil ana tür
        self.assertTrue(tedarikci_ana_turu_mu("Tedarikçi", None))
        self.assertTrue(tedarikci_ana_turu_mu(None, "Tedarikçi"))
        self.assertFalse(tedarikci_ana_turu_mu("Müşteri", None))
        self.assertFalse(tedarikci_ana_turu_mu(None, "Müşteri"))
        metrik = {"bakiye": net, "toplam_borc": 0, "toplam_alacak": 25650}
        t_metin, t_renk = ozet_metinleri(metrik, tedarikci_modu=True)["Kalan Bakiye"]
        m_metin, m_renk = ozet_metinleri(metrik, tedarikci_modu=False)["Kalan Bakiye"]
        self.assertEqual(t_metin, m_metin)
        self.assertIn("(A)", t_metin)
        self.assertEqual(t_renk, "#000000")
        self.assertEqual(m_renk, BASARI)


class AlisOnayliDugmeTest(unittest.TestCase):
    def test_toolbar_onayli_metin_ve_rol(self):
        """Onaylı faturada düğme Onaylı + onayli rol; onay kaldırınca Onayla."""
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        root.withdraw()
        try:
            from alis_ui import AlisFaturasiDialog
            from fatura_tema import oval_buton

            # Minimal stub: yalnız _toolbar_guncelle yolu
            dlg = MagicMock(spec=AlisFaturasiDialog)
            dlg.fatura = SimpleNamespace(id=1, durum="AÇIK", onaylandi=True, fatura_no="AF1")
            dlg._alis_toolbar = {
                "fatura_no": MagicMock(),
                "musteri": MagicMock(),
                "rozet": MagicMock(),
                "sag": root,
            }
            dlg.tedarikci_map = {}
            dlg.tedarikci = MagicMock(get=lambda: "")
            dugme = oval_buton(root, "Onayla", rol="onayla", grup="dis")
            dlg.onayla_btn = dugme
            dlg.onay_kaldir_btn = None
            dlg._alis_onayli = lambda: bool(dlg.fatura and dlg.fatura.onaylandi)
            dlg._pencere_basligi = lambda: "t"
            dlg.title = MagicMock()
            dlg._kilit_uygula = MagicMock()

            AlisFaturasiDialog._toolbar_guncelle(dlg)
            self.assertEqual(dugme.cget("text"), "Onaylı")
            self.assertEqual(dugme._rol, "onayli")

            dlg.fatura.onaylandi = False
            AlisFaturasiDialog._toolbar_guncelle(dlg)
            self.assertEqual(dugme.cget("text"), "Onayla")
            self.assertEqual(dugme._rol, "onayla")
        finally:
            root.destroy()


from types import SimpleNamespace  # noqa: E402 — test stub


class AnaTurKaydetEngeliTest(unittest.TestCase):
    def test_yeni_cari_ana_tur_reddedilir(self):
        from unittest.mock import patch

        from database.kart_turu_service import KartTuruService

        with patch("database.kart_turu_service.yazma_zorunlu"), patch(
            "database.kart_turu_service.get_session"
        ) as gs:
            # session context manager — kaydet id yokken ValueError üretmeli
            cm = MagicMock()
            cm.__enter__.return_value = MagicMock()
            cm.__enter__.return_value.scalars.return_value.all.return_value = []
            gs.return_value = cm
            with self.assertRaises(ValueError) as ctx:
                KartTuruService.ana_kaydet(
                    {
                        "kapsam": "CARI",
                        "ad": "Altıncı Tür",
                        "muhasebe_rol": "MUSTERI",
                    }
                )
            self.assertIn("sabit", str(ctx.exception).casefold())


if __name__ == "__main__":
    unittest.main()
