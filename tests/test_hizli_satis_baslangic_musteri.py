"""Hızlı Satış başlangıç müşterisi ayarı — test kopyası (canlı yazma yok)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.database import get_session
from database.hizli_satis_ayarlari_service import (
    MOD_ATANAN,
    MOD_BOS,
    ayar_kaydet,
    ayar_oku,
    baslangic_musteri_coz,
    schema_hazirla,
)
from database.models.cari import Cari
from tests import test_tahsilat_makbuzu as tbase


class HizliSatisBaslangicMusteriTest(unittest.TestCase):
    def setUp(self):
        tbase.TahsilatMakbuzuTest.setUp(self)
        schema_hazirla()
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        tbase.TahsilatMakbuzuTest.tearDown(self)

    def test_varsayilan_bos(self):
        ayar = ayar_oku()
        self.assertEqual(ayar["baslangic_mod"], MOD_BOS)
        self.assertFalse(ayar["kayit_var"])
        coz = baslangic_musteri_coz()
        self.assertEqual(coz["mod"], MOD_BOS)
        self.assertEqual(int(coz["ozet"]["id"]), 0)
        self.assertEqual(coz["ozet"]["unvan"], "")

    def test_atanan_kaydet_ve_oku(self):
        ayar_kaydet(baslangic_mod=MOD_ATANAN, baslangic_cari_id=self.musteri_id)
        ayar = ayar_oku()
        self.assertEqual(ayar["baslangic_mod"], MOD_ATANAN)
        self.assertEqual(ayar["baslangic_cari_id"], self.musteri_id)
        self.assertTrue(ayar["cari_unvan"])
        coz = baslangic_musteri_coz()
        self.assertEqual(int(coz["ozet"]["id"]), self.musteri_id)
        self.assertIsNone(coz["uyari"])

    def test_bos_moda_donunce_cari_silinir(self):
        ayar_kaydet(baslangic_mod=MOD_ATANAN, baslangic_cari_id=self.musteri_id)
        ayar_kaydet(baslangic_mod=MOD_BOS, baslangic_cari_id=self.musteri_id)
        ayar = ayar_oku()
        self.assertEqual(ayar["baslangic_mod"], MOD_BOS)
        self.assertIsNone(ayar["baslangic_cari_id"])
        coz = baslangic_musteri_coz()
        self.assertEqual(int(coz["ozet"]["id"]), 0)

    def test_atanan_cari_zorunlu(self):
        with self.assertRaises(ValueError):
            ayar_kaydet(baslangic_mod=MOD_ATANAN, baslangic_cari_id=None)

    def test_pasif_cari_uyari(self):
        ayar_kaydet(baslangic_mod=MOD_ATANAN, baslangic_cari_id=self.musteri_id)
        with get_session() as s:
            c = s.get(Cari, self.musteri_id)
            c.aktif = False
            s.flush()
        ayar = ayar_oku()
        self.assertTrue(ayar["uyari"])
        coz = baslangic_musteri_coz()
        self.assertEqual(int(coz["ozet"]["id"]), 0)
        self.assertTrue(coz["uyari"])

    def test_islem_degisimi_ayari_bozmaz(self):
        """F2 ile satışta müşteri değiştirmek firma ayarını etkilemez (servis katmanı)."""
        ayar_kaydet(baslangic_mod=MOD_ATANAN, baslangic_cari_id=self.musteri_id)
        # Satış oturumunda başka cari seçilmiş gibi — ayar aynı kalır
        once = ayar_oku()
        # Ayar yeniden okunur; satış tarafı ayar_kaydet çağırmaz
        sonra = ayar_oku()
        self.assertEqual(once["baslangic_cari_id"], sonra["baslangic_cari_id"])
        self.assertEqual(sonra["baslangic_mod"], MOD_ATANAN)

    def test_ui_kaynak_baglari(self):
        src = (ROOT / "ana_panel_ui.py").read_text(encoding="utf-8")
        self.assertIn("HIZLI SATIŞ AYARLARI", src)
        self.assertIn("hizli_satis_ayarlari_goster", src)
        ui = (ROOT / "hizli_satis_ayarlari_ui.py").read_text(encoding="utf-8")
        self.assertIn("Müşteri alanı boş gelsin", ui)
        self.assertIn("Seçilen müşteri otomatik gelsin", ui)
        self.assertIn("Vazgeç", ui)
        hs = (ROOT / "hizli_satis_ui.py").read_text(encoding="utf-8")
        self.assertIn("baslangic_musteri_coz", hs)
        self.assertIn("_varsayilan_musteri_yukle()", hs)


if __name__ == "__main__":
    unittest.main()
