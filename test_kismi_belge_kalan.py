"""Kısmi sipariş / irsaliye / fatura kalan miktar birim testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from database.kalan_belge_service import (
    miktar_kalani_dogrula,
    ornek_senaryo_kalanlari,
    secimden_fatura_satirlari,
    secimden_irsaliye_satirlari,
    siparis_secim_satirlari,
)
from database.satis_siparisi_service import satir_kalanlari


class TestSatirKalanlari(unittest.TestCase):
    def test_bagimsiz_sevk_ve_fatura(self):
        k = satir_kalanlari(10, irsaliyelenen=4, faturalanan=2)
        self.assertEqual(k["sevk_kalani"], Decimal("6"))
        self.assertEqual(k["fatura_kalani"], Decimal("8"))

    def test_dogrudan_fatura_sevk_etmez(self):
        k = satir_kalanlari(10, irsaliyelenen=0, faturalanan=3)
        self.assertEqual(k["sevk_kalani"], Decimal("10"))
        self.assertEqual(k["fatura_kalani"], Decimal("7"))


class TestOrnekSenaryo(unittest.TestCase):
    def test_talimat_ornek_10_4_2_3(self):
        # 10 sipariş → 4 irsaliye → sevk kalan 6
        # irsaliyenin 2'si fatura → faturalanmamış irsaliye 2
        # +3 irsaliye → sevk kalan 3
        sonuc = ornek_senaryo_kalanlari(
            Decimal("10"),
            sevk_adimlari=[Decimal("4")],
            fatura_irsaliye_adimlari=[(0, Decimal("2"))],
        )
        self.assertEqual(sonuc["sevk_kalani"], Decimal("6"))
        self.assertEqual(sonuc["fatura_kalani"], Decimal("8"))
        self.assertEqual(sonuc["irsaliye_fatura_kalanlari"], [Decimal("2")])

        sonuc2 = ornek_senaryo_kalanlari(
            Decimal("10"),
            sevk_adimlari=[Decimal("4"), Decimal("3")],
            fatura_irsaliye_adimlari=[(0, Decimal("2"))],
        )
        self.assertEqual(sonuc2["sevk_miktar"], Decimal("7"))
        self.assertEqual(sonuc2["sevk_kalani"], Decimal("3"))
        self.assertEqual(sonuc2["fatura_miktar"], Decimal("2"))
        self.assertEqual(sonuc2["fatura_kalani"], Decimal("8"))

    def test_limit_asimi(self):
        with self.assertRaises(ValueError):
            ornek_senaryo_kalanlari(
                Decimal("10"),
                sevk_adimlari=[Decimal("11")],
                fatura_irsaliye_adimlari=[],
            )
        with self.assertRaises(ValueError):
            ornek_senaryo_kalanlari(
                Decimal("10"),
                sevk_adimlari=[Decimal("4")],
                fatura_irsaliye_adimlari=[(0, Decimal("5"))],
            )

    def test_dogrudan_fatura_ayri_satir_karismaz(self):
        # İki sipariş satırı simülasyonu: her satır kendi fatura kalanı
        a = satir_kalanlari(10, 0, 3)
        b = satir_kalanlari(5, 0, 0)
        self.assertEqual(a["fatura_kalani"], Decimal("7"))
        self.assertEqual(b["fatura_kalani"], Decimal("5"))
        # Doğrudan fatura sevk sayılmaz
        self.assertEqual(a["sevk_kalani"], Decimal("10"))


class TestMiktarDogrula(unittest.TestCase):
    def test_kalani_asamaz(self):
        self.assertEqual(
            miktar_kalani_dogrula(4, 6),
            Decimal("4"),
        )
        with self.assertRaises(ValueError):
            miktar_kalani_dogrula(7, 6)

    def test_sifir_haric(self):
        with self.assertRaises(ValueError):
            miktar_kalani_dogrula(0, 5, sifir_izinli=False)


class TestSecimDonusumu(unittest.TestCase):
    def test_siparis_secim_satirlari(self):
        siparis = SimpleNamespace(
            satirlar=[
                SimpleNamespace(
                    id=1,
                    urun_kodu="U1",
                    urun_adi="Ürün 1",
                    aciklama=None,
                    birim="Adet",
                    miktar=Decimal("10"),
                    irsaliyelenen_miktar=Decimal("4"),
                    faturalanan_miktar=Decimal("2"),
                    birim_satis_fiyati=Decimal("100"),
                    iskonto_orani=Decimal("0"),
                    kdv_orani=Decimal("20"),
                ),
                SimpleNamespace(
                    id=2,
                    urun_kodu="U2",
                    urun_adi="Ürün 2",
                    aciklama="",
                    birim="Adet",
                    miktar=Decimal("5"),
                    irsaliyelenen_miktar=Decimal("5"),
                    faturalanan_miktar=Decimal("5"),
                    birim_satis_fiyati=Decimal("50"),
                    iskonto_orani=Decimal("0"),
                    kdv_orani=Decimal("20"),
                ),
            ]
        )
        sevk = siparis_secim_satirlari(siparis, hedef="irsaliye")
        self.assertEqual(len(sevk), 1)
        self.assertEqual(sevk[0]["kalan_miktar"], Decimal("6"))
        fat = siparis_secim_satirlari(siparis, hedef="fatura")
        self.assertEqual(len(fat), 1)
        self.assertEqual(fat[0]["kalan_miktar"], Decimal("8"))

    def test_secimden_satirlar(self):
        secim = [
            {
                "kaynak_satir_id": 1,
                "siparis_satiri_id": 1,
                "urun_kodu": "U1",
                "urun_adi": "Ürün",
                "aciklama": "",
                "birim": "Adet",
                "siparis_miktar": Decimal("10"),
                "onceki_miktar": Decimal("0"),
                "kalan_miktar": Decimal("10"),
                "bu_belge_miktar": Decimal("4"),
                "birim_fiyat": Decimal("100"),
                "birim_satis_fiyati": Decimal("100"),
                "iskonto_orani": 0,
                "kdv_orani": 20,
                "irsaliyelenen_miktar": 0,
            },
            {
                "kaynak_satir_id": 2,
                "siparis_satiri_id": 2,
                "urun_kodu": "U2",
                "urun_adi": "Ürün2",
                "aciklama": "",
                "birim": "Adet",
                "siparis_miktar": Decimal("5"),
                "onceki_miktar": Decimal("0"),
                "kalan_miktar": Decimal("5"),
                "bu_belge_miktar": Decimal("0"),
                "birim_fiyat": Decimal("50"),
                "birim_satis_fiyati": Decimal("50"),
                "iskonto_orani": 0,
                "kdv_orani": 20,
            },
        ]
        ir = secimden_irsaliye_satirlari(secim)
        self.assertEqual(len(ir), 1)
        self.assertEqual(ir[0]["miktar"], Decimal("4"))
        self.assertEqual(ir[0]["siparis_satiri_id"], 1)

        fat = secimden_fatura_satirlari(secim, kaynak="siparis")
        self.assertEqual(len(fat), 1)
        self.assertEqual(fat[0]["siparis_satiri_id"], 1)
        self.assertIsNone(fat[0]["irsaliye_satiri_id"])


class TestSiparisSatirIdKoruma(unittest.TestCase):
    def test_miktar_alt_sinir(self):
        from database.satis_siparisi_service import SatisSiparisiService

        satir = SimpleNamespace(
            irsaliyelenen_miktar=Decimal("4"),
            faturalanan_miktar=Decimal("2"),
            urun_kodu="U1",
            urun_adi="Ürün",
            aciklama=None,
            birim="Adet",
            birim_satis_fiyati=Decimal("10"),
            iskonto_orani=Decimal("0"),
            kdv_orani=Decimal("20"),
            fifo_birim_maliyeti=Decimal("0"),
            son_alis_birim_maliyeti=Decimal("0"),
            ortalama_birim_maliyeti=Decimal("0"),
            agirlikli_ortalama_birim_maliyeti=Decimal("0"),
            is_manual_item=False,
            line_type="STOCK_PRODUCT",
            product_id=None,
            delivery_term_days=None,
            estimated_delivery_date=None,
            delivery_term_note=None,
            stock_pending=False,
            miktar=Decimal("10"),
        )
        with self.assertRaises(ValueError):
            SatisSiparisiService._satir_alanlarini_yaz(
                satir,
                {
                    "urun_kodu": "U1",
                    "urun_adi": "Ürün",
                    "miktar": 3,
                    "birim": "Adet",
                    "birim_satis_fiyati": 10,
                },
            )
        SatisSiparisiService._satir_alanlarini_yaz(
            satir,
            {
                "urun_kodu": "U1",
                "urun_adi": "Ürün",
                "miktar": 4,
                "birim": "Adet",
                "birim_satis_fiyati": 10,
            },
        )
        self.assertEqual(satir.miktar, Decimal("4"))


if __name__ == "__main__":
    unittest.main()
