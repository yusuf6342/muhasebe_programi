"""Smoke: sipariş→fatura aktarım + alınan sipariş satır sütunları."""

from __future__ import annotations

import inspect
import unittest
from decimal import Decimal
from types import SimpleNamespace

from database.kalan_belge_service import siparis_fatura_aktarim_satirlari


class TestSiparisFaturaAktarim(unittest.TestCase):
    def _siparis(self, miktar=10, fat=0, sevk=0):
        s1 = SimpleNamespace(
            id=1,
            miktar=miktar,
            faturalanan_miktar=fat,
            irsaliyelenen_miktar=sevk,
            urun_kodu="A",
            urun_adi="Urun",
            aciklama="",
            birim="Adet",
            birim_satis_fiyati=100,
            iskonto_orani=0,
            kdv_orani=20,
        )
        return SimpleNamespace(satirlar=[s1]), s1

    def test_ilk_aktarim_tam_kalan(self):
        sip, _ = self._siparis()
        r = siparis_fatura_aktarim_satirlari(sip, form_satirlar=[])
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["miktar"], Decimal("10"))
        self.assertEqual(r[0]["siparis_satiri_id"], 1)

    def test_mukerrer_form_dusulur(self):
        sip, _ = self._siparis()
        r = siparis_fatura_aktarim_satirlari(
            sip, form_satirlar=[{"siparis_satiri_id": 1, "miktar": 6}]
        )
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["miktar"], Decimal("4"))

    def test_tamami_formdaysa_bos(self):
        sip, _ = self._siparis()
        r = siparis_fatura_aktarim_satirlari(
            sip, form_satirlar=[{"siparis_satiri_id": 1, "miktar": 10}]
        )
        self.assertEqual(r, [])

    def test_kayitli_fatura_geri_eklenir(self):
        sip, s1 = self._siparis(fat=3)
        db = [SimpleNamespace(siparis_satiri_id=1, miktar=3)]
        r = siparis_fatura_aktarim_satirlari(
            sip, form_satirlar=[], bu_fatura_db_satirlar=db
        )
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["miktar"], Decimal("10"))


class TestSiparisSatirSutunlari(unittest.TestCase):
    def test_yalniz_sevk_ve_kalan(self):
        import app as app_mod

        src = inspect.getsource(app_mod.SatisSiparisiDialog._siparis_satir_olustur)
        self.assertNotIn("fatura_kalan", src)
        self.assertNotIn("sevk_kalan", src)
        self.assertNotIn("Faturalanan", src)
        self.assertIn("Sevk Edilen", src)
        self.assertIn("Kalan", src)
        self.assertIn("_siparis_ilerleme_sutun_ortala", src)
        ortala = inspect.getsource(app_mod.SatisSiparisiDialog._siparis_ilerleme_sutun_ortala)
        self.assertIn('anchor="center"', ortala)
        yenile = inspect.getsource(app_mod.SatisSiparisiDialog._satir_listesini_yenile)
        self.assertIn("_siparis_ilerleme_sutun_ortala", yenile)

    def test_yenile_max_sevk(self):
        import app as app_mod

        src = inspect.getsource(app_mod.SatisSiparisiDialog._satir_listesini_yenile)
        self.assertIn("max(irsaliye, fatura)", src)
        self.assertNotIn("kalanlar[\"fatura_kalani\"]", src)
        self.assertNotIn("kalanlar['fatura_kalani']", src)

    def test_fatura_siparisten_getir_var(self):
        import app as app_mod

        self.assertTrue(hasattr(app_mod.SatisFaturasiDialog, "_fatura_siparisten_getir"))


if __name__ == "__main__":
    unittest.main()
