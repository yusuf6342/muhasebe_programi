"""Ray Mobilya'ya özgü varsayılanlar (başlık, alt unvan) başka firmalara sızmamalı."""
from __future__ import annotations

import unittest

import branding
from database.session_manager import oturum
from database.teklif_customer_view import FIRMA_ALT_UNVAN, alt_unvan


class FirmaVarsayilanTest(unittest.TestCase):
    def setUp(self):
        self._eski = oturum.firma_unvan

    def tearDown(self):
        oturum.firma_unvan = self._eski

    def test_ray_firmasi_tanima(self):
        for unvan in ("Ray Mobilya Aksesuarları", "RAY MOBİLYA AKSESUARLARI", "ray mobilya"):
            self.assertTrue(branding.ray_firmasi_mi(unvan), unvan)
        for unvan in ("YENİ FİRMA", "TEST FİRMASI (Deneme)", "Raylı Sistemler", ""):
            self.assertFalse(branding.ray_firmasi_mi(unvan), unvan)

    def test_ana_panel_basligi(self):
        oturum.firma_unvan = "Ray Mobilya Aksesuarları"
        self.assertEqual(branding.firma_basligi("RAY MOBİLYA AKSESUARLARI"), "RAY MOBİLYA AKSESUARLARI")
        oturum.firma_unvan = "Yıldız Ticaret"
        self.assertEqual(branding.firma_basligi("RAY MOBİLYA AKSESUARLARI"), "YILDIZ TİCARET")
        oturum.firma_unvan = None
        self.assertEqual(branding.firma_basligi("RAY MOBİLYA AKSESUARLARI"), "CİN MUHASEBE")

    def test_teklif_alt_unvani(self):
        oturum.firma_unvan = "YENİ FİRMA"
        self.assertEqual(alt_unvan({"unvan": "YENİ FİRMA"}), "YENİ FİRMA")
        self.assertEqual(alt_unvan({"unvan": ""}), "")
        oturum.firma_unvan = "Ray Mobilya Aksesuarları"
        self.assertEqual(alt_unvan({"unvan": ""}), FIRMA_ALT_UNVAN)
        self.assertEqual(alt_unvan({"unvan": "RAY MOBİLYA AKSESUARLARI"}), FIRMA_ALT_UNVAN)


if __name__ == "__main__":
    unittest.main()
