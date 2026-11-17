"""Lot adı kesilmez; stok barkod SVG etiket genişliğine yayılır / ortalanır."""

from __future__ import annotations

import inspect
import re
import unittest

from lot_etiket_ui import lot_etiket_html
from stok_barkod_ui import (
    code128_bitleri,
    code128_svg,
    etiket_barkod_durumu,
    etiket_html,
    StokBarkodBasimSayfasi,
)
from stok_ui import StokKartiDialog


class EtiketBarkodYerlesimTest(unittest.TestCase):
    def test_lot_urun_adi_max_height_yok(self):
        html = lot_etiket_html(
            [
                {
                    "barkod": "L00000001",
                    "stok_adi": "Çok Uzun Türkçe Ürün Adı Şğüöçı İle Test",
                    "birim": "Adet",
                    "satis_fiyati": 12.5,
                    "etiket_adedi": 1,
                    "lot_no": "LOT-1",
                }
            ],
            lot_goster=True,
        )
        self.assertNotIn("max-height:2.4em", html)
        self.assertNotIn("max-height: 2.4em", html)
        self.assertIn("overflow-wrap:anywhere", html.replace(" ", ""))
        self.assertIn("Çok Uzun Türkçe Ürün Adı", html)
        self.assertIn('class="metin"', html)
        self.assertIn("gap:1.4mm", html.replace(" ", ""))
        self.assertIn("flex:00auto", html.replace(" ", ""))
        self.assertIn('class="birim"', html)
        self.assertRegex(html, r"TRY\s*<span class=\"birim\">")
        self.assertNotIn("KDV dahil", html)
        self.assertNotIn("KDV hariç", html)
        # Barkod çubuğu kontrollü yükseklik (eski ~54px yerine ≤28)
        yukseklikler = re.findall(r'height="(\d+)" fill="#000"', html)
        self.assertTrue(yukseklikler)
        self.assertLessEqual(max(int(h) for h in yukseklikler), 28)
        self.assertIn("text-align:center", html)

    def test_code128_svg_hedef_genislik_ortali(self):
        kod = "8690123456789"
        # Geçersiz kontrol basamağı olsa da çizim için metin yeter
        svg = code128_svg(kod, yukseklik=40, hedef_genislik_px=200)
        self.assertIn('width="100%"', svg)
        self.assertIn("preserveAspectRatio=\"xMidYMid meet\"", svg)
        self.assertIn('text-anchor="middle"', svg)
        bits = code128_bitleri(kod)
        quiet = 10
        vb = bits and (len(bits) + 2 * quiet)
        self.assertIn(f'viewBox="0 0 {vb} ', svg)
        # Quiet zone: ilk rect x >= quiet
        xs = [int(m) for m in re.findall(r'<rect x="(\d+)"', svg)]
        self.assertTrue(xs)
        self.assertGreaterEqual(min(xs), quiet)

    def test_etiket_html_58x40_barkod_yayilir(self):
        html = etiket_html(
            [
                {
                    "barkod": "8690000000017",
                    "stok_kodu": "S1",
                    "stok_adi": "Kısa Ad",
                    "birim": "Adet",
                    "fiyat": 10,
                }
            ],
            kopya=1,
            genislik_mm=58,
            yukseklik_mm=40,
        )
        self.assertIn('width="100%"', html)
        self.assertIn(".barkod svg", html)
        self.assertIn("width: 100%", html)

    def test_ornek_gecersiz_ean13_durumu(self):
        neden = etiket_barkod_durumu("2575765502612")
        self.assertIsNotNone(neden)
        self.assertIn("kontrol basamağı", neden)

    def test_cift_tik_ve_yeniden_olustur_bagli(self):
        self.assertTrue(hasattr(StokBarkodBasimSayfasi, "_satir_cift_tik"))
        self.assertTrue(hasattr(StokKartiDialog, "barkodu_yeniden_olustur"))
        sig = inspect.signature(StokKartiDialog.__init__)
        self.assertIn("on_saved", sig.parameters)


if __name__ == "__main__":
    unittest.main()
