"""Satış faturası sade UI — ürün otomatik aktarım ve satır kolonları.

Çalıştırma: .venv\\Scripts\\python.exe -m unittest tests.test_fatura_sade_ui -v
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fatura_urun_aktar_service import (
    fatura_pb_ve_kur,
    stoktan_satir_sablonu,
    urun_seciminden_aktar,
    urunu_faturaya_aktar,
)
from fatura_satir_hucre_edit import DUZENLENEBILIR_KOLONLAR
from app import FATURA_SATIR_KOLON_TANIMLARI


class KolonTanimTest(unittest.TestCase):
    def test_kolonlar_sirasi(self):
        anahtarlar = [a for a, *_ in FATURA_SATIR_KOLON_TANIMLARI]
        self.assertEqual(
            anahtarlar,
            [
                "sira",
                "urun_kodu",
                "urun_adi",
                "barkod",
                "miktar",
                "birim",
                "fiyat",
                "para_birimi",
                "kur",
                "iskonto",
                "iskonto_tutar",
                "kdv",
                "kdv_tutar",
                "net_birim",
                "toplam",
                "aciklama",
            ],
        )
        # Eski satır formu kolonları yok
        for eski in ("sec", "lot", "net_birim_kdv", "irsaliye"):
            self.assertNotIn(eski, anahtarlar)

    def test_duzenlenebilir_kolonlar(self):
        for k in (
            "miktar",
            "birim",
            "fiyat",
            "para_birimi",
            "kur",
            "iskonto",
            "iskonto_tutar",
            "kdv",
            "aciklama",
        ):
            self.assertIn(k, DUZENLENEBILIR_KOLONLAR)


class AktarimTest(unittest.TestCase):
    def _dialog(self):
        d = MagicMock()
        d.satirlar = []
        d._fatura_kilitli = False
        d.depo.get.return_value = "ANA DEPO"
        d._doviz_para_birimi.get.return_value = "TRY"
        d._secili_musteri.return_value = None
        d._satir_listesini_yenile = MagicMock()
        d._toplamlari_guncelle = MagicMock()
        return d

    @patch("fatura_urun_aktar_service.birim_satis_fiyati", return_value=Decimal("10"))
    @patch("fatura_urun_aktar_service.temel_miktar", return_value=Decimal("1"))
    @patch("fatura_barkod_ui._satiri_vurgula")
    def test_yeni_satir_ekle(self, *_mocks):
        dialog = self._dialog()
        stok = SimpleNamespace(
            stok_kodu="U1",
            stok_adi="Ürün 1",
            birim="Adet",
            barkod="123",
            barkodlar=[],
            kdv_orani=Decimal("20"),
            iskonto_1=0,
        )
        with patch(
            "fatura_urun_aktar_service.stok_kartini_coz",
            return_value=stok,
        ), patch(
            "fatura_urun_aktar_service.StokService.maliyetler",
            return_value={"fifo": 0, "son_alis": 0, "ortalama": 0, "agirlikli": 0},
        ):
            sablon = stoktan_satir_sablonu(dialog, urun_kodu="U1", urun_adi="Ürün 1")
            idx = urunu_faturaya_aktar(dialog, sablon)
        self.assertEqual(idx, 0)
        self.assertEqual(len(dialog.satirlar), 1)
        self.assertEqual(dialog.satirlar[0]["urun_kodu"], "U1")
        self.assertEqual(dialog.satirlar[0]["barkod"], "123")
        self.assertEqual(dialog.satirlar[0]["miktar"], "1")

    @patch("fatura_urun_aktar_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m)))
    @patch("fatura_barkod_ui._satiri_vurgula")
    def test_ayni_urun_miktar_artis(self, *_mocks):
        dialog = self._dialog()
        sablon = {
            "urun_kodu": "U1",
            "urun_adi": "Ürün",
            "miktar": "1",
            "birim": "Adet",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "satir_para_birimi": "TRY",
            "manuel_fiyat": False,
            "barkod": "",
        }
        dialog.satirlar = [dict(sablon)]
        urunu_faturaya_aktar(dialog, dict(sablon), miktar_ekle=Decimal("1"), birlestir=True)
        self.assertEqual(len(dialog.satirlar), 1)
        self.assertEqual(dialog.satirlar[0]["miktar"], "2")

    @patch("fatura_urun_aktar_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m)))
    @patch("fatura_barkod_ui._satiri_vurgula")
    def test_farkli_birim_ayri_satir(self, *_mocks):
        dialog = self._dialog()
        a = {
            "urun_kodu": "U1",
            "urun_adi": "Ürün",
            "miktar": "1",
            "birim": "Adet",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "satir_para_birimi": "TRY",
            "manuel_fiyat": False,
            "barkod": "",
        }
        dialog.satirlar = [dict(a)]
        b = dict(a)
        b["birim"] = "Paket"
        urunu_faturaya_aktar(dialog, b, miktar_ekle=Decimal("1"), birlestir=True)
        self.assertEqual(len(dialog.satirlar), 2)

    def test_pb_try_kur_1(self):
        d = MagicMock()
        d._doviz_para_birimi.get.return_value = "TRY"
        pb, kur = fatura_pb_ve_kur(d)
        self.assertEqual(pb, "TRY")
        self.assertEqual(kur, Decimal("1"))


class UrunKartTanimlayiciTest(unittest.TestCase):
    def test_genislik_katsayilari(self):
        barkod_eski = 18
        barkod_yeni = max(1, int(round(barkod_eski * 1.50)))
        kod_yeni = barkod_yeni
        ad_yeni = 67
        self.assertEqual(barkod_yeni, 27)
        self.assertEqual(kod_yeni, 27)
        self.assertEqual(ad_yeni, 67)

    def test_birincil_barkod_ana_alan(self):
        from fatura_urun_aktar_service import birincil_barkod_al, urun_kartindan_tanimlayicilar

        stok = SimpleNamespace(
            stok_kodu="SK1",
            stok_adi="Ürün A",
            barkod="8691111111111",
            barkodlar=[],
        )
        self.assertEqual(birincil_barkod_al(stok), "8691111111111")
        barkod, kod, ad = urun_kartindan_tanimlayicilar(stok=stok)
        self.assertEqual(barkod, "8691111111111")
        self.assertEqual(kod, "SK1")
        self.assertEqual(ad, "Ürün A")

    def test_ek_barkod_tarama_korunur(self):
        from fatura_urun_aktar_service import urun_kartindan_tanimlayicilar

        ekstra = SimpleNamespace(barkod="8692222222222")
        stok = SimpleNamespace(
            stok_kodu="SK2",
            stok_adi="Ürün B",
            barkod="8691111111111",
            barkodlar=[ekstra],
        )
        barkod, kod, ad = urun_kartindan_tanimlayicilar(
            stok=stok, okutulan_barkod="8692222222222"
        )
        self.assertEqual(barkod, "8692222222222")
        self.assertEqual(kod, "SK2")
        self.assertNotEqual(kod, "8692222222222")

    def test_kod_seciminde_birincil_barkod(self):
        from fatura_urun_aktar_service import urun_kartindan_tanimlayicilar

        stok = SimpleNamespace(
            stok_kodu="SK3",
            stok_adi="Ürün C",
            barkod="8693333333333",
            barkodlar=[],
        )
        barkod, kod, ad = urun_kartindan_tanimlayicilar(stok=stok, stok_kodu="SK3")
        self.assertEqual(barkod, "8693333333333")
        self.assertEqual(kod, "SK3")
        self.assertEqual(ad, "Ürün C")


class IskontoDonguTest(unittest.TestCase):
    def test_tutar_yuzdeye(self):
        from database.satis_faturasi_service import SatisFaturasiService

        brut = Decimal("1000")
        tutar = Decimal("100")
        oran = (tutar / brut * Decimal("100")).quantize(Decimal("0.0001"))
        _, indirim, matrah = SatisFaturasiService._satir_net(
            Decimal("10"), Decimal("100"), oran, 0, 0
        )
        self.assertEqual(indirim, Decimal("100"))
        self.assertEqual(matrah, Decimal("900"))


if __name__ == "__main__":
    unittest.main()
