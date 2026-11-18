"""finans_belge_ac: kredi / ekstre / gider prefix yönlendirme (UI açmadan)."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class FinansBelgeKaynakRouteTest(unittest.TestCase):
    def test_krk_kto_kke_gdf_prefix_isle(self):
        import belge_onizleme_ui as bou

        calls = []

        def _kredi(parent, belge_no, *, tur=""):
            calls.append(("kredi", belge_no, tur))
            return True

        def _kke(parent, belge_no):
            calls.append(("kke", belge_no))
            return True

        def _gider_ac(*a, **k):
            calls.append(("gider_ui", k))
            return True

        with (
            patch.object(bou, "_kredi_belge_ac", side_effect=_kredi),
            patch.object(bou, "_kk_ekstre_odeme_ac", side_effect=_kke),
            patch(
                "kredi_gider_fisi_ui.kredi_gider_fisini_ac",
                side_effect=_gider_ac,
            ),
        ):
            self.assertTrue(bou.finans_belge_ac(None, "KREDİ KULLANDIRIM", "KRK-2026-0001"))
            self.assertTrue(bou.finans_belge_ac(None, "KREDİ TAKSİT ÖDEME", "KTO-2026-0001"))
            self.assertTrue(bou.finans_belge_ac(None, "KK EKSTRE ÖDEME", "KKE-2026-0001"))
            self.assertTrue(bou.finans_belge_ac(None, "GİDER FİŞİ", "GDF-2026-0001"))

        self.assertEqual(calls[0][0], "kredi")
        self.assertEqual(calls[1][0], "kredi")
        self.assertEqual(calls[2][0], "kke")
        self.assertEqual(calls[3][0], "gider_ui")


if __name__ == "__main__":
    unittest.main()
