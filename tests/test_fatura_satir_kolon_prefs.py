"""Fatura satır kolon görünürlük / genişlik tercih testleri."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatura_satir_kolon_prefs import (
    EKRAN_ALIS,
    EKRAN_SATIS,
    ayar_dosyasi,
    ayarlari_kaydet,
    ayarlari_yukle,
    flat_to_nested,
    nested_to_flat,
    varsayilan_ayarlar,
    zorunlu_kolonlar,
)


class FaturaKolonPrefsTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self._patch = patch(
            "fatura_satir_kolon_prefs.ayar_dosyasi",
            side_effect=lambda ekran: self.base / f"{ekran}.json",
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._td.cleanup()

    def test_urun_adi_zorunlu(self):
        self.assertIn("urun_adi", zorunlu_kolonlar(EKRAN_SATIS))
        self.assertIn("ad", zorunlu_kolonlar(EKRAN_ALIS))

    def test_satis_alis_ayri_dosya(self):
        # Gerçek kimlikli yollar farklı ekran kodu içerir
        from fatura_satir_kolon_prefs import ayar_dosyasi as gercek

        self.assertNotEqual(str(gercek(EKRAN_SATIS)), str(gercek(EKRAN_ALIS)))
        self.assertIn(EKRAN_SATIS, gercek(EKRAN_SATIS).name)
        self.assertIn(EKRAN_ALIS, gercek(EKRAN_ALIS).name)

    def test_kaydet_yukle_genislik(self):
        ayar = varsayilan_ayarlar(EKRAN_SATIS)
        ayar["kolonlar"]["barkod"]["genislik"] = 150
        ayar["kolonlar"]["barkod"]["gorunur"] = False
        ayarlari_kaydet(EKRAN_SATIS, ayar)
        yuklu = ayarlari_yukle(EKRAN_SATIS)
        self.assertEqual(yuklu["kolonlar"]["barkod"]["genislik"], 150)
        self.assertFalse(yuklu["kolonlar"]["barkod"]["gorunur"])
        # Ürün adı zorunlu açık
        self.assertTrue(yuklu["kolonlar"]["urun_adi"]["gorunur"])

    def test_satis_alis_izole(self):
        s = varsayilan_ayarlar(EKRAN_SATIS)
        s["kolonlar"]["miktar"]["genislik"] = 133
        ayarlari_kaydet(EKRAN_SATIS, s)
        a = varsayilan_ayarlar(EKRAN_ALIS)
        a["kolonlar"]["miktar"]["genislik"] = 77
        ayarlari_kaydet(EKRAN_ALIS, a)
        self.assertEqual(ayarlari_yukle(EKRAN_SATIS)["kolonlar"]["miktar"]["genislik"], 133)
        self.assertEqual(ayarlari_yukle(EKRAN_ALIS)["kolonlar"]["miktar"]["genislik"], 77)

    def test_bozuk_json_varsayilan(self):
        yol = self.base / f"{EKRAN_SATIS}.json"
        yol.write_text("{bozuk", encoding="utf-8")
        yuklu = ayarlari_yukle(EKRAN_SATIS)
        self.assertIn("urun_adi", yuklu["kolonlar"])
        self.assertTrue(yuklu["kolonlar"]["urun_adi"]["gorunur"])

    def test_yeni_kolon_eski_ayar(self):
        # Eski kayıtta eksik kolon → varsayılanla eklenir
        yol = self.base / f"{EKRAN_SATIS}.json"
        yol.write_text(
            json.dumps(
                {
                    "sira": ["sira", "urun_adi", "toplam"],
                    "kolonlar": {
                        "sira": {"genislik": 50, "gorunur": True},
                        "urun_adi": {"genislik": 200, "gorunur": True},
                        "toplam": {"genislik": 100, "gorunur": True},
                    },
                }
            ),
            encoding="utf-8",
        )
        yuklu = ayarlari_yukle(EKRAN_SATIS)
        self.assertIn("iskonto", yuklu["kolonlar"])
        self.assertIn("iskonto", yuklu["sira"])

    def test_zorunlu_gizlenemez(self):
        ayar = varsayilan_ayarlar(EKRAN_SATIS)
        ayar["kolonlar"]["urun_adi"]["gorunur"] = False
        ayarlari_kaydet(EKRAN_SATIS, ayar)
        yuklu = ayarlari_yukle(EKRAN_SATIS)
        self.assertTrue(yuklu["kolonlar"]["urun_adi"]["gorunur"])

    def test_flat_roundtrip(self):
        nested = varsayilan_ayarlar(EKRAN_SATIS)
        nested["kolonlar"]["kur"]["gorunur"] = False
        flat = nested_to_flat(nested, EKRAN_SATIS)
        self.assertFalse(flat["kur"]["gorunur"])
        self.assertIn("_sira", flat)
        back = flat_to_nested(flat, EKRAN_SATIS)
        self.assertFalse(back["kolonlar"]["kur"]["gorunur"])

    def test_min_max_genislik(self):
        ayar = varsayilan_ayarlar(EKRAN_SATIS)
        ayar["kolonlar"]["para_birimi"]["genislik"] = 5  # min altına
        ayarlari_kaydet(EKRAN_SATIS, ayar)
        yuklu = ayarlari_yukle(EKRAN_SATIS)
        self.assertGreaterEqual(yuklu["kolonlar"]["para_birimi"]["genislik"], 40)


if __name__ == "__main__":
    unittest.main()
