"""Ekstre devir + vade günü/sonrası ödeme + yürüyen bakiye + tarih aralığı."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from database.kk_ekstre_rapor_service import (
    _onceki_devir,
    _yuruyen_bakiye,
    rapor_verisi,
)


class OncekiDevirTest(unittest.TestCase):
    def test_vade_gunu_ve_sonrasi_odeme_dusulur(self):
        # Önceki ekstre 10.000; son ödeme günü 4.000 + sonrası 3.000 → kalan 3.000
        donemler = [
            {
                "kesim_tarihi": date(2026, 10, 16),
                "son_odeme_tarihi": date(2026, 10, 26),
                "tl_tutar": D("10000.00"),
                "odemeler": [
                    {
                        "tarih": date(2026, 10, 26),
                        "tutar": D("4000.00"),
                        "iptal": False,
                        "belge_no": "P1",
                    },
                    {
                        "tarih": date(2026, 10, 28),
                        "tutar": D("3000.00"),
                        "iptal": False,
                        "belge_no": "P2",
                    },
                ],
            }
        ]
        # Yeni kesim 16.11 — her iki ödeme de kesimden önce/eşit değil; 28.10 < 16.11
        top, det = _onceki_devir(donemler, kesim=date(2026, 11, 16), as_of=date(2026, 11, 16))
        self.assertEqual(top, D("3000.00"))
        self.assertEqual(det[0]["kalan"], D("3000.00"))

    def test_kesimden_sonra_odeme_kesim_anini_degistirmez(self):
        donemler = [
            {
                "kesim_tarihi": date(2026, 10, 16),
                "tl_tutar": D("10000.00"),
                "odemeler": [
                    {"tarih": date(2026, 10, 20), "tutar": D("2000.00"), "iptal": False},
                    {"tarih": date(2026, 11, 20), "tutar": D("3000.00"), "iptal": False},
                ],
            }
        ]
        kesimde, _ = _onceki_devir(
            donemler, kesim=date(2026, 11, 16), as_of=date(2026, 11, 16)
        )
        raporda, _ = _onceki_devir(
            donemler, kesim=date(2026, 11, 16), as_of=date(2026, 11, 30)
        )
        self.assertEqual(kesimde, D("8000.00"))
        self.assertEqual(raporda, D("5000.00"))

    def test_iptal_odeme_dusulmez(self):
        donemler = [
            {
                "kesim_tarihi": date(2026, 10, 16),
                "tl_tutar": D("1000.00"),
                "odemeler": [
                    {"tarih": date(2026, 10, 20), "tutar": D("1000.00"), "iptal": True},
                ],
            }
        ]
        top, _ = _onceki_devir(donemler, kesim=date(2026, 11, 16), as_of=date(2026, 11, 16))
        self.assertEqual(top, D("1000.00"))


class YuruyenBakiyeTest(unittest.TestCase):
    def test_borc_eksi_odeme_arti(self):
        satirlar = [
            {"borc": D("1000"), "odeme": D("0")},
            {"borc": D("500"), "odeme": D("0")},
            {"borc": D("0"), "odeme": D("400")},
        ]
        out = _yuruyen_bakiye(satirlar, acilis=D("0"))
        self.assertEqual(out[0]["bakiye"], D("-1000.00"))
        self.assertEqual(out[1]["bakiye"], D("-1500.00"))
        self.assertEqual(out[2]["bakiye"], D("-1100.00"))


class RaporTarihAraligiTest(unittest.TestCase):
    def test_gecersiz_aralik(self):
        with self.assertRaises(ValueError):
            rapor_verisi(
                1,
                mod="tarih_araligi",
                baslangic=date(2026, 11, 16),
                bitis=date(2026, 10, 17),
            )


class RaporDevirEntegrasyonMock(unittest.TestCase):
    def test_devir_satiri_ve_odeme_listede(self):
        from database import kk_ekstre_rapor_service as mod

        kart = SimpleNamespace(
            id=5,
            kart_adi="T",
            kart_bankasi="B",
            banka_karti_id=1,
            para_birimi="TRY",
            son_dort_hane="0000",
            kart_numarasi=None,
            banka_karti=SimpleNamespace(banka_adi="B"),
        )
        ozet = {
            "toplam_borc": D("3000"),
            "kullanilan": D("3000"),
            "kesilmemis": D("0"),
            "kesilmis_kalan": D("3000"),
            "para_birimi": "TRY",
            "limit": None,
            "limit_tanimli": False,
            "kullanilabilir": None,
            "hesap_borc": D("3000"),
        }
        onceki = {
            "ekstre_id": 1,
            "kesim_tarihi": date(2026, 10, 16),
            "donem_baslangic": date(2026, 9, 17),
            "donem_bitis": date(2026, 10, 16),
            "son_odeme_tarihi": date(2026, 10, 26),
            "tl_tutar": D("10000"),
            "odenen": D("7000"),
            "kalan": D("3000"),
            "asgari_tutar": None,
            "asgari_odenen": D("0"),
            "kesin": True,
            "detay_satirlari": [],
            "odemeler": [
                {"id": 1, "tarih": date(2026, 10, 26), "tutar": D("4000"), "iptal": False,
                 "belge_no": "P1", "aciklama": "", "kaynak": "EKSTRE", "dekont_no": "",
                 "finans_hesap_id": None, "iptal_tarihi": None},
                {"id": 2, "tarih": date(2026, 10, 28), "tutar": D("3000"), "iptal": False,
                 "belge_no": "P2", "aciklama": "", "kaynak": "EKSTRE", "dekont_no": "",
                 "finans_hesap_id": None, "iptal_tarihi": None},
            ],
        }
        yeni = {
            "ekstre_id": 2,
            "kesim_tarihi": date(2026, 11, 16),
            "donem_baslangic": date(2026, 10, 17),
            "donem_bitis": date(2026, 11, 16),
            "son_odeme_tarihi": date(2026, 11, 26),
            "tl_tutar": D("0"),
            "odenen": D("0"),
            "kalan": D("0"),
            "asgari_tutar": None,
            "asgari_odenen": D("0"),
            "kesin": True,
            "detay_satirlari": [],
            "odemeler": [],
        }

        class _Sess:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def scalar(self, *_a, **_k):
                return kart

        with patch("database.database.get_session", return_value=_Sess()), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.schema_hazirla"
        ), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.kart_borc_ozeti",
            return_value=ozet,
        ), patch(
            "database.kredi_karti_ekstre_service.KrediKartiEkstreService.ekstreleri_hesapla",
            return_value=[onceki, yeni],
        ):
            r = mod.rapor_verisi(5, kesim_tarihi=date(2026, 11, 16), rapor_tarihi=date(2026, 11, 18))

        self.assertEqual(r["onceki_devir"], D("3000.00"))
        self.assertEqual(r["hareketler"][0]["satir_turu"], "DEVIR")
        self.assertEqual(r["hareketler"][0]["borc"], D("3000.00"))
        self.assertEqual(r["hareketler"][0]["bakiye"], D("-3000.00"))
        self.assertNotIn("etki", r["hareketler"][0])


if __name__ == "__main__":
    unittest.main()
