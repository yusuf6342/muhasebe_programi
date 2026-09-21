"""Bağlama duyarlı fatura listesi — belge türü ve tek pencere senaryoları."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestFaturaListeBaglama(unittest.TestCase):
    def test_document_type_sabitleri(self):
        from fatura_liste_pencere import DOC_ALIS, DOC_SATIS

        self.assertEqual(DOC_SATIS, "SALES_INVOICE")
        self.assertEqual(DOC_ALIS, "PURCHASE_INVOICE")
        self.assertNotEqual(DOC_SATIS, DOC_ALIS)

    def test_listele_ozet_satis_document_type(self):
        from database.satis_faturasi_service import SatisFaturasiService

        with patch.object(SatisFaturasiService, "listele_ozet", return_value=[
            {"id": 1, "document_type": "SALES_INVOICE", "fatura_no": "S1"},
        ]) as mock:
            rows = SatisFaturasiService.listele_ozet()
            mock.assert_called()
            self.assertTrue(all(r.get("document_type") == "SALES_INVOICE" for r in rows))

    def test_listele_ozet_alis_document_type(self):
        from database.alis_faturasi_service import AlisFaturasiService

        with patch.object(AlisFaturasiService, "listele_ozet", return_value=[
            {"id": 2, "document_type": "PURCHASE_INVOICE", "fatura_no": "A1"},
        ]):
            rows = AlisFaturasiService.listele_ozet()
            self.assertTrue(all(r.get("document_type") == "PURCHASE_INVOICE" for r in rows))

    def test_satis_bagli_ac_tur_reddi(self):
        from fatura_liste_pencere import DOC_ALIS
        from app import SatisFaturasiDialog

        class Fake:
            fatura = None
            satirlar = []
            musteri = MagicMock(get=MagicMock(return_value=""))
            _fatura_form_kirli = False

            def _fatura_kirli_mi(self):
                return False

        Fake.bagli_listeden_fatura_ac = SatisFaturasiDialog.bagli_listeden_fatura_ac
        with self.assertRaises(ValueError):
            Fake().bagli_listeden_fatura_ac(1, document_type=DOC_ALIS)

    def test_alis_bagli_ac_tur_reddi(self):
        from fatura_liste_pencere import DOC_SATIS
        from alis_ui import AlisFaturasiDialog

        class Fake:
            fatura = None
            satirlar = []
            tedarikci = MagicMock(get=MagicMock(return_value=""))
            _fatura_form_kirli = False

            def _fatura_kirli_mi(self):
                return False

        Fake.bagli_listeden_fatura_ac = AlisFaturasiDialog.bagli_listeden_fatura_ac
        with self.assertRaises(ValueError):
            Fake().bagli_listeden_fatura_ac(1, document_type=DOC_SATIS)

    def test_fatura_listesi_ac_tek_pencere(self):
        from fatura_liste_pencere import DOC_SATIS, fatura_listesi_ac

        kart = MagicMock()
        mevcut = MagicMock()
        mevcut.winfo_exists.return_value = True
        kart._bagli_fatura_liste_pencere = mevcut

        with patch("fatura_liste_pencere.FaturaListePencere") as cls, patch(
            "fatura_liste_pencere.messagebox"
        ), patch("database.session_manager.oturum") as oturum:
            oturum.has_permission.return_value = True
            oturum.role_kod = "YONETICI"
            fatura_listesi_ac(kart, document_type=DOC_SATIS)
            cls.assert_not_called()
            mevcut.deiconify.assert_called()
            mevcut.lift.assert_called()
            mevcut.yenile.assert_called()


if __name__ == "__main__":
    unittest.main()
