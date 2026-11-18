"""KK Tanım Formu V4: yerleşim, menü ayrımı, faiz dönüşümü, taksit takvimi."""

from __future__ import annotations

import inspect
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from database.finans_service import FinansService


class KkTanimFormuV4Test(unittest.TestCase):
    def test_islemleri_menude_yanlis_buton_yok(self):
        from finans_ui import KrediKartiIslemleriDialog

        src = inspect.getsource(KrediKartiIslemleriDialog.__init__)
        for yasak in (
            "Taksitli Harcama",
            "Taksit Planını Düzenle",
            "Kart Ödemesi",
            "Hesap Ekstresi",
            "Yeni Harcama",
            "_harcama_ac",
        ):
            self.assertNotIn(yasak, src)
        for gerekli in (
            "Kredi Kartı Tanımla",
            "Kartları Düzenle",
            "Ekstre Ödeme Evrakı",
            "Taksitli Nakit Avans",
            "Tarihleri değiştir",
        ):
            self.assertIn(gerekli, src)
        self.assertIn("_nakit_avans_ac", src)

    def test_tanim_dialog_bolum_ve_butonlar(self):
        from finans_ui import KrediKartiTanimDialog

        src = inspect.getsource(KrediKartiTanimDialog.__init__)
        for bolum in (
            "Kart Bilgileri",
            "Limit ve Özet",
            "Vade ve Asgari Ödeme",
            "Faiz Ayarları",
            "İşlemler (bu kart)",
        ):
            self.assertIn(bolum, src)
        for btn in (
            "Taksitli Harcama",
            "Taksitli Nakit Avans",
            "Taksit Planını Düzenle",
            "Karta Ödeme Kaydet",
            "Hesap Ekstresi",
        ):
            self.assertIn(btn, src)
        self.assertIn("varsayilan_taksit", src)
        self.assertIn("asgari_oran", src)
        self.assertIn("akdi_aylik", src)
        self.assertIn("gecikme_yillik", src)

    def test_duzenle_ve_yeni_ayni_sinif(self):
        from finans_ui import KrediKartiIslemleriDialog, KrediKartiTanimDialog

        self.assertIn(
            "KrediKartiTanimDialog",
            inspect.getsource(KrediKartiIslemleriDialog._kart_tanim_ac),
        )
        self.assertIn(
            "KrediKartiTanimDialog",
            inspect.getsource(KrediKartiIslemleriDialog._kart_duzenle_secili),
        )
        self.assertTrue(hasattr(KrediKartiTanimDialog, "_taksitli_harcama"))
        self.assertTrue(hasattr(KrediKartiTanimDialog, "_plan_duzenle"))
        self.assertTrue(hasattr(KrediKartiTanimDialog, "_karta_odeme"))
        self.assertTrue(hasattr(KrediKartiTanimDialog, "_hesap_ekstresi"))
        self.assertTrue(hasattr(KrediKartiTanimDialog, "_faiz_kaydet"))

    def test_faiz_aylik_yillik_donusum(self):
        root = __import__("tkinter").Tk()
        root.withdraw()
        try:
            from finans_ui import KrediKartiTanimDialog

            fake_banka = MagicMock(banka_adi="Test Banka")
            with patch("finans_ui.FinansService.banka_karti_getir", return_value=fake_banka), patch(
                "finans_ui.FinansService.kredi_karti_getir", return_value=None
            ), patch("ui_pencere.pencere_os_krom_ac", lambda w: None), patch(
                "finans_ui.messagebox.showinfo", return_value=None
            ):
                dlg = KrediKartiTanimDialog(root, banka_karti_id=1, kart_id=None)
                dlg._faiz_esas.set("AYLIK")
                dlg.akdi_aylik.delete(0, "end")
                dlg.akdi_aylik.insert(0, "3,5")
                dlg.gecikme_aylik.delete(0, "end")
                dlg.gecikme_aylik.insert(0, "4")
                dlg._faiz_esas_degisti()
                self.assertEqual(dlg.akdi_yillik.get().replace(",", "."), "42")
                self.assertEqual(dlg.gecikme_yillik.get().replace(",", "."), "48")
                dlg._faiz_esas.set("YILLIK")
                dlg.akdi_yillik.configure(state="normal")
                dlg.akdi_yillik.delete(0, "end")
                dlg.akdi_yillik.insert(0, "36")
                dlg.gecikme_yillik.configure(state="normal")
                dlg.gecikme_yillik.delete(0, "end")
                dlg.gecikme_yillik.insert(0, "48")
                dlg._faiz_esas_degisti()
                self.assertEqual(dlg.akdi_aylik.get().replace(",", "."), "3")
                self.assertEqual(dlg.gecikme_aylik.get().replace(",", "."), "4")
                self.assertFalse(dlg._kayit_gerekli("Test"))
                dlg.destroy()
        finally:
            root.destroy()

    def test_taksit_takvim_ornekleri(self):
        p = FinansService.kk_taksit_plani(
            date(2027, 1, 31), 4, Decimal("1000.00"), ilk_taksit_tarihi=date(2027, 1, 31)
        )
        self.assertEqual(
            [s["vade_tarihi"] for s in p],
            [
                date(2027, 1, 31),
                date(2027, 2, 28),
                date(2027, 3, 31),
                date(2027, 4, 30),
            ],
        )
        p2 = FinansService.kk_taksit_plani(
            date(2028, 1, 31), 3, Decimal("100.00"), ilk_taksit_tarihi=date(2028, 1, 31)
        )
        self.assertEqual(
            [s["vade_tarihi"] for s in p2],
            [date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)],
        )
        p3 = FinansService.kk_taksit_plani(
            date(2027, 2, 28), 2, Decimal("100.00"), ilk_taksit_tarihi=date(2027, 2, 28)
        )
        self.assertEqual(
            [s["vade_tarihi"] for s in p3],
            [date(2027, 2, 28), date(2027, 3, 28)],
        )

    def test_kurus_dagilimi(self):
        plan = FinansService.kk_taksit_plani(
            date(2026, 11, 1), 3, Decimal("1000.00"), ilk_taksit_tarihi=date(2026, 11, 1)
        )
        tutarlar = [s["tutar"] for s in plan]
        self.assertEqual(sum(tutarlar, Decimal("0")), Decimal("1000.00"))
        self.assertEqual(sorted(tutarlar), [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")])


if __name__ == "__main__":
    unittest.main()
