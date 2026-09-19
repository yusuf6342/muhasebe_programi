"""Üçüncü iskonto satır metninde '9' görünmesi — format + kolon kırpma testleri.

Hesap motoruna dokunulmaz; yalnızca görüntüleme.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.iskonto_hesap_service import (
    etkili_iskonto_orani,
    iskonto_goster_metin,
    satir_iskonto_hesapla,
)


class UcuncuIskontoGoruntuTest(unittest.TestCase):
    """Talimat matrisi: satır metni ham oranlardan, üçüncü oran asla sahte 9 olmaz."""

    def test_matris(self):
        durumlar = (
            ((0, 0, 0), ""),
            ((10, 0, 0), "%10"),
            ((10, 8, 0), "%10 + %8"),
            ((10, 8, 5), "%10 + %8 + %5"),
            ((10, 8, 7), "%10 + %8 + %7"),
            ((10, 8, 9), "%10 + %8 + %9"),
            ((10, 8, 12), "%10 + %8 + %12"),
            ((Decimal("2.5"), Decimal("1.25"), Decimal("0.5")), "%2.5 + %1.25 + %0.5"),
        )
        for oranlar, beklenen in durumlar:
            metin = iskonto_goster_metin(*oranlar, bos_goster="")
            self.assertEqual(metin, beklenen, msg=f"oranlar={oranlar}")
            # Sahte '9' yok (gerçek 9 hariç)
            if oranlar[2] != 9 and oranlar[2] != Decimal("9"):
                self.assertFalse(
                    metin.endswith(" 9") or metin.endswith("+ 9") or metin == "9",
                    msg=f"sahte 9: {metin!r}",
                )
            # Her görünen oran % ile başlar
            if metin:
                for parca in metin.split(" + "):
                    self.assertTrue(parca.startswith("%"), msg=parca)

    def test_1085_hesap_dokunulmadi(self):
        """1.250 TL brüt, 10+8+5 → 266,75 / %21,34 / 1.179,90 (KDV dahil)."""
        h = satir_iskonto_hesapla(
            miktar=1,
            brut_birim_fiyat=Decimal("1250"),
            iskonto1=10,
            iskonto2=8,
            iskonto3=5,
            kdv_orani=20,
        )
        self.assertEqual(etkili_iskonto_orani(10, 8, 5), Decimal("21.34"))
        self.assertEqual(h["iskonto_tutari"], Decimal("266.75"))
        self.assertEqual(h["net_tutar"], Decimal("1179.90"))
        self.assertEqual(iskonto_goster_metin(10, 8, 5), "%10 + %8 + %5")

    def test_sadece_gercek_9(self):
        self.assertEqual(iskonto_goster_metin(10, 8, 9), "%10 + %8 + %9")
        self.assertNotEqual(iskonto_goster_metin(10, 8, 5), "%10 + %8 + %9")
        self.assertNotEqual(iskonto_goster_metin(10, 8, 5), "%10 + %8 + 9")

    def test_kolon_min_genislik_yukle(self):
        """Kayıtlı 90px ayar yüklense bile iskonto ≥160 olmalı."""
        from app import fatura_kolon_ayarlari_yukle, fatura_kolon_varsayilan_ayarlari
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            yol = Path(td) / "kolon.json"
            yol.write_text(
                json.dumps(
                    {
                        "iskonto": {"genislik": 90, "gorunur": True},
                        "kdv": {"genislik": 40, "gorunur": True},
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.fatura_kolon_ayar_dosyasi", return_value=yol):
                ayar = fatura_kolon_ayarlari_yukle()
            self.assertGreaterEqual(ayar["iskonto"]["genislik"], 160)
            self.assertGreaterEqual(ayar["kdv"]["genislik"], 70)
            # Varsayılan da yeterli
            v = fatura_kolon_varsayilan_ayarlari()
            self.assertGreaterEqual(v["iskonto"]["genislik"], 160)


if __name__ == "__main__":
    unittest.main()
