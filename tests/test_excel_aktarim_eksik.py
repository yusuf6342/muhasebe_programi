"""Eksik tip kayıtları, şablon ve doğrulama smoke."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import excel_aktarim  # noqa: F401
from excel_aktarim.template import ImportTemplateService
from excel_aktarim.types import getir, modul_tipleri, tum_tipler


class ExcelAktarimEksikTest(unittest.TestCase):
    YENI = (
        "personel_kart",
        "banka_kart",
        "kasa_hesap",
        "pos_hesap",
        "depo_transfer",
        "gider_fisi",
        "cek_senet",
        "konsinye_teslim",
        "satis_siparis_excel",
        "alis_siparis_excel",
        "teklif_excel",
    )

    def test_yeni_tipler_kayitli(self):
        kodlar = {t.kod for t in tum_tipler()}
        for k in self.YENI:
            self.assertIn(k, kodlar, k)

    def test_finans_hub_dolu(self):
        kodlar = {t.kod for t in modul_tipleri("finans")}
        self.assertTrue({"banka_kart", "kasa_hesap", "personel_kart", "cek_senet"} <= kodlar)

    def test_gelir_gider_hub_dolu(self):
        kodlar = {t.kod for t in modul_tipleri("gelir_gider")}
        self.assertIn("gider_fisi", kodlar)

    def test_sablonlar(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kod in self.YENI:
                tip = getir(kod)
                yol = Path(tmp) / f"{kod}.xlsx"
                ImportTemplateService.olustur(tip, yol)
                self.assertTrue(yol.is_file(), kod)

    def test_dogrulama_eksik_alan(self):
        from excel_aktarim.importers.finans_kartlari import BankaKartImporter, BANKA_TIPI
        from excel_aktarim.importers.diger_evrak import GiderFisiImporter, GIDER_FISI_TIPI

        r1 = BankaKartImporter(BANKA_TIPI).dogrula_satirlar([{}])
        self.assertGreaterEqual(r1.hatali, 1)
        r2 = GiderFisiImporter(GIDER_FISI_TIPI).dogrula_satirlar([{"tarih": "02.11.2026"}])
        self.assertGreaterEqual(r2.hatali, 1)

    def test_mukerrer_helper_import(self):
        from excel_aktarim.mukerrer import mukerrer_mi

        # boş anahtar → mükerrer değil
        ok, _ = mukerrer_mi("banka_kart", {})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
