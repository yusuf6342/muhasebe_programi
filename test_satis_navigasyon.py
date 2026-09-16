"""Satışlar menü / navigasyon smoke testleri (GUI açmadan)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class SatisNavigasyonTest(unittest.TestCase):
    def test_hub_sira(self):
        from satis_ui import CARI_ISLEM_KARTLARI, RAPOR_KARTLARI, SATIS_HUB_KARTLARI, navigasyon_haritasi

        hub = [k[0] for k in SATIS_HUB_KARTLARI]
        self.assertEqual(
            hub,
            [
                "MÜŞTERİ KARTLARI",
                "SATIŞ FATURALARI",
                "ALINAN SİPARİŞLER",
                "SATIŞ İRSALİYELERİ",
                "CARİ HESAP İŞLEMLERİ",
                "RAPORLAR",
            ],
        )
        cari = [k[0].replace("\n", " ") for k in CARI_ISLEM_KARTLARI]
        self.assertEqual(cari[0], "TAHSİLAT MAKBUZU")
        self.assertEqual(cari[1], "CARİ VİRMAN")
        self.assertIn("KREDİ KARTI ÇEKİM EVRAKI", cari[2])
        self.assertNotIn("...", cari[2])
        self.assertEqual(cari[3], "GELİR FİŞİ")
        self.assertEqual(cari[4], "GİDER FİŞİ")
        rapor = [k[0] for k in RAPOR_KARTLARI]
        self.assertEqual(
            rapor,
            ["SATIŞ RAPORLARI", "DÖVİZ KURLARI", "DÖVİZ BAZINDA RAPORLAR"],
        )
        harita = navigasyon_haritasi()
        self.assertEqual(harita["hub"], hub)

    def test_tema_renkleri(self):
        from satis_tema import (
            ACIK_BG,
            ACIK_SARI,
            BASARI,
            BEYAZ,
            IKINCIL,
            KOYU_LACIVERT,
            LACIVERT,
            METIN,
            SARI,
            UYARI,
        )

        self.assertEqual(LACIVERT, "#102A43")
        self.assertEqual(KOYU_LACIVERT, "#081B2C")
        self.assertEqual(SARI, "#F4C542")
        self.assertEqual(ACIK_SARI, "#FFE89A")
        self.assertEqual(BEYAZ, "#FFFFFF")
        self.assertEqual(ACIK_BG, "#F3F6F9")
        self.assertEqual(METIN, "#172B4D")
        self.assertEqual(IKINCIL, "#627D98")
        self.assertEqual(BASARI, "#1F9D74")
        self.assertEqual(UYARI, "#D64545")

    def test_modul_import(self):
        import satis_tema
        import satis_ui
        from doviz_kur_ui import doviz_kur_yonetimi_goster
        from doviz_rapor_ui import doviz_raporlari_goster

        self.assertTrue(callable(satis_ui.satislar_hub_goster))
        self.assertTrue(callable(satis_ui.cari_hesap_islemleri_goster))
        self.assertTrue(callable(satis_ui.satis_raporlar_hub_goster))
        self.assertTrue(callable(doviz_kur_yonetimi_goster))
        self.assertTrue(callable(doviz_raporlari_goster))
        self.assertTrue(hasattr(satis_tema, "ekran_ust_cubugu"))

    def test_app_satislar_hub_baglantisi(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("satislar_hub_goster", src)
        self.assertIn("from satis_ui import", src)
        # Eski düz menü satırları hub'a taşındı
        self.assertNotIn('("DÖVİZ KURLARI", lambda: doviz_kur_yonetimi_goster(self))', src)


if __name__ == "__main__":
    unittest.main()
