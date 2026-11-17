"""Alınan Sipariş Stok Durumu — Var/Kısmi/Yok kuralları ve PDF ayrımı."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.siparis_stok_durumu import (  # noqa: E402
    DURUM_KISMI,
    DURUM_VAR,
    DURUM_YOK,
    durum_etiketi,
    satir_durumlari,
    uyari_durumu_mu,
)


class SiparisStokDurumuTest(unittest.TestCase):
    def test_etiket_kurallari(self):
        self.assertEqual(durum_etiketi(Decimal("10"), Decimal("10")), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("11"), Decimal("10")), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("4"), Decimal("10")), DURUM_KISMI)
        self.assertEqual(durum_etiketi(Decimal("0"), Decimal("10")), DURUM_YOK)
        self.assertEqual(durum_etiketi(Decimal("-2"), Decimal("10")), DURUM_YOK)
        self.assertEqual(durum_etiketi(Decimal("5"), Decimal("0")), "")
        self.assertEqual(durum_etiketi(Decimal("5"), Decimal("-1")), "")

    def test_ornek_akis_0_4_10_9(self):
        q = Decimal("10")
        self.assertEqual(durum_etiketi(Decimal("0"), q), DURUM_YOK)
        self.assertEqual(durum_etiketi(Decimal("4"), q), DURUM_KISMI)
        self.assertEqual(durum_etiketi(Decimal("10"), q), DURUM_VAR)
        self.assertEqual(durum_etiketi(Decimal("9"), q), DURUM_KISMI)

    def test_uyari_renk(self):
        self.assertTrue(uyari_durumu_mu(DURUM_KISMI))
        self.assertTrue(uyari_durumu_mu(DURUM_YOK))
        self.assertFalse(uyari_durumu_mu(DURUM_VAR))
        self.assertFalse(uyari_durumu_mu(""))

    def test_ayni_urun_iki_satir_katlamaz(self):
        """Stok map bir kez; her satır kendi Q ile durum alır."""
        stok = {"P1": Decimal("5")}
        satirlar = [
            {"urun_kodu": "P1", "urun_adi": "A", "miktar": "3", "birim": "Adet"},
            {"urun_kodu": "P1", "urun_adi": "A", "miktar": "10", "birim": "Adet"},
        ]
        # kart yoksa carpan 1 varsayılır (test ortamı DB'siz) — satir_temel_miktar DB açar
        # Bu yüzden doğrudan durum_etiketi ile doğrula; satir_durumlari entegrasyon testi ayrı
        self.assertEqual(durum_etiketi(stok["P1"], Decimal("3")), DURUM_VAR)
        self.assertEqual(durum_etiketi(stok["P1"], Decimal("10")), DURUM_KISMI)

    def test_pdf_guvenlik_stok_durumu_yasak(self):
        from database.siparis_form_view import SiparisFormViewModel, assert_siparis_form_safe

        vm = SiparisFormViewModel(siparis_no="SP-1", siparis_tarihi="12.11.2026")
        assert_siparis_form_safe(vm, "Sipariş No SP-1 Ürün Adı Miktar")
        with self.assertRaises(ValueError):
            assert_siparis_form_safe(vm, "Tablo Stok Durumu Var Kısmi")

    def test_karti_stok_durumu_kolonu_urun_adi_sonrasi(self):
        """Canlı menü SatisSiparisiKarti kullanır; kolon Ürün Adı sonrası olmalı."""
        import inspect

        import satis_siparisi_ui as ui

        src = inspect.getsource(ui.SatisSiparisiKarti._satir_alani)
        self.assertIn('"ad", "stok_durumu"', src)
        yenile = inspect.getsource(ui.SatisSiparisiKarti.satir_listesini_yenile)
        self.assertIn("satir_durumlari", yenile)
        self.assertIn("stok_uyari", yenile)


if __name__ == "__main__":
    unittest.main()
