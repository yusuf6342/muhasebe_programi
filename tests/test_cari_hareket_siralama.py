"""ui_tablo_siralama + Cari Hareketler sıralama kabul testleri.

Çalıştırma: python tests/test_cari_hareket_siralama.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui_tablo_siralama import (
    baslik_sirali,
    dogal_belge_anahtar,
    liste_sirala,
    para_coz,
    siralama_yonu_degistir,
    tarih_coz,
    turkce_metin_anahtar,
)


class YardimciTest(unittest.TestCase):
    def test_tarih_coz(self):
        self.assertEqual(tarih_coz(date(2026, 3, 15)), date(2026, 3, 15))
        self.assertEqual(tarih_coz("15.03.2026"), date(2026, 3, 15))
        self.assertIsNone(tarih_coz(""))
        self.assertIsNone(tarih_coz(None))

    def test_para_coz_bicimler(self):
        self.assertEqual(para_coz("900 TL"), Decimal("900"))
        self.assertEqual(para_coz("1.250 TL"), Decimal("1250"))
        self.assertEqual(para_coz("10.000 TL"), Decimal("10000"))
        self.assertEqual(para_coz("1.250,50 TL"), Decimal("1250.50"))
        self.assertEqual(para_coz("₺1.250,50"), Decimal("1250.50"))
        self.assertEqual(para_coz("-100,25"), Decimal("-100.25"))
        self.assertEqual(para_coz("(50,00)"), Decimal("-50"))
        self.assertIsNone(para_coz(""))
        self.assertIsNone(para_coz(None))

    def test_para_sayisal_sira(self):
        tutarlar = ["10.000 TL", "900 TL", "1.250 TL"]
        sirali = liste_sirala(tutarlar, anahtar_fn=para_coz, azalan=False)
        self.assertEqual([para_coz(x) for x in sirali], [Decimal("900"), Decimal("1250"), Decimal("10000")])

    def test_negatif_bakiye(self):
        bakiyeler = [Decimal("100"), Decimal("-50"), Decimal("0"), None, ""]
        artan = liste_sirala(bakiyeler, anahtar_fn=para_coz, azalan=False)
        self.assertEqual(artan[:3], [Decimal("-50"), Decimal("0"), Decimal("100")])
        self.assertTrue(_bos_son(artan[-2:]))

    def test_dogal_belge(self):
        belgeler = ["F100", "F2", "F10", "", None]
        sirali = liste_sirala(belgeler, anahtar_fn=dogal_belge_anahtar, azalan=False)
        self.assertEqual(sirali[:3], ["F2", "F10", "F100"])
        self.assertTrue(_bos_son(sirali[-2:]))

    def test_turkce_alfabe(self):
        kelimeler = ["Şube", "Cari", "Çeki", "Ada"]
        sirali = liste_sirala(kelimeler, anahtar_fn=turkce_metin_anahtar, azalan=False)
        self.assertEqual(sirali, ["Ada", "Cari", "Çeki", "Şube"])

    def test_baslik_isaret_ve_yon(self):
        self.assertEqual(baslik_sirali("Tarih", aktif=True, azalan=False), "Tarih ▲")
        self.assertEqual(baslik_sirali("Tarih ▲", aktif=True, azalan=True), "Tarih ▼")
        self.assertEqual(baslik_sirali("Tarih ▼", aktif=False, azalan=False), "Tarih")
        k, a = siralama_yonu_degistir(None, False, "tarih")
        self.assertEqual((k, a), ("tarih", False))
        k, a = siralama_yonu_degistir("tarih", False, "tarih")
        self.assertEqual((k, a), ("tarih", True))
        k, a = siralama_yonu_degistir("tarih", True, "borc")
        self.assertEqual((k, a), ("borc", False))


def _bos_son(parca):
    return all(x in (None, "") for x in parca)


class CariHareketSiralaTest(unittest.TestCase):
    """CariKartDialog sıralama anahtarları — Tk olmadan."""

    def setUp(self):
        # Minimal stub: sadece sıralama metotlarını kullan
        from cari_kart_ui import CariDialog

        self.cls = CariDialog
        self.hareketler = [
            {
                "tarih": date(2026, 1, 10),
                "tur": "Satış",
                "belge_no": "F10",
                "aciklama": "Zebra",
                "borc": Decimal("1250"),
                "alacak": Decimal("0"),
                "kalan": Decimal("1250"),
                "hareket_id": 2,
                "para_birimi": "TRY",
                "doviz_tutari": 0,
                "kur": 1,
            },
            {
                "tarih": date(2026, 1, 5),
                "tur": "Tahsilat",
                "belge_no": "F2",
                "aciklama": "Alfa",
                "borc": Decimal("0"),
                "alacak": Decimal("900"),
                "kalan": Decimal("350"),
                "hareket_id": 1,
                "para_birimi": "TRY",
                "doviz_tutari": 0,
                "kur": 1,
            },
            {
                "tarih": date(2026, 2, 1),
                "tur": "Satış",
                "belge_no": "F100",
                "aciklama": "",
                "borc": Decimal("10000"),
                "alacak": Decimal("0"),
                "kalan": Decimal("-50"),
                "hareket_id": 3,
                "para_birimi": "TRY",
                "doviz_tutari": 0,
                "kur": 1,
            },
        ]

    def _sirala(self, kolon, azalan=False):
        return liste_sirala(
            self.hareketler,
            anahtar_fn=lambda h: self.cls._hareket_siralama_anahtar(h, kolon),
            azalan=azalan,
            ikincil_fn=self.cls._hareket_ikincil_anahtar,
        )

    def test_tarih_artan_azalan(self):
        artan = self._sirala("tarih", False)
        self.assertEqual([h["belge_no"] for h in artan], ["F2", "F10", "F100"])
        azalan = self._sirala("tarih", True)
        self.assertEqual([h["belge_no"] for h in azalan], ["F100", "F10", "F2"])

    def test_borc_sayisal(self):
        sirali = self._sirala("borc", False)
        # 0 borclu (tahsilat) önce, sonra 1250, 10000
        self.assertEqual([h["belge_no"] for h in sirali], ["F2", "F10", "F100"])

    def test_bakiye_negatif(self):
        sirali = self._sirala("bakiye", False)
        self.assertEqual(sirali[0]["kalan"], Decimal("-50"))

    def test_belge_dogal(self):
        sirali = self._sirala("belge", False)
        self.assertEqual([h["belge_no"] for h in sirali], ["F2", "F10", "F100"])

    def test_bos_aciklama_sonda(self):
        sirali = self._sirala("aciklama", False)
        self.assertEqual(sirali[-1]["belge_no"], "F100")
        self.assertEqual(sirali[0]["belge_no"], "F2")  # Alfa

    def test_toplamlar_siralamadan_bagimsiz(self):
        from cari_kart_ui import CariDialog

        t1 = CariDialog._hareket_tutar_toplamlari(self.hareketler)
        sirali = self._sirala("borc", True)
        t2 = CariDialog._hareket_tutar_toplamlari(sirali)
        self.assertEqual(t1, t2)

    def test_iid_meta_kimlik_korunur(self):
        """Sıralama dict kopyalarını taşısa da hareket_id aynı kalır."""
        sirali = self._sirala("tarih", True)
        ids = {h["hareket_id"] for h in sirali}
        self.assertEqual(ids, {1, 2, 3})


class ImportSmokeTest(unittest.TestCase):
    def test_cari_kart_import(self):
        import cari_kart_ui  # noqa: F401
        from cari_kart_ui import CariDialog

        self.assertTrue(hasattr(CariDialog, "_hareket_sutun_sirala"))
        self.assertTrue(hasattr(CariDialog, "_hareket_listeyi_sirala"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
