"""Beş aylık ödeme durumu penceresi — takvim ayı hesabı testleri."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from database.odeme_durumu_service import (
    BES_AYLIK_OFFSETLER,
    DURUM_GECIKMIS,
    DURUM_KISMI,
    DURUM_ODENDI,
    DURUM_PLANLANDI,
    KAYNAK_CEK,
    KAYNAK_KK,
    KAYNAK_KREDI,
    OdemeDurumuService,
    ROL_BU_AY,
    ROL_GECEN,
    ROL_GELECEK,
    SIFIR,
    _ay_ekle,
    _durum_hesapla,
)


class BesAylikPencereTest(unittest.TestCase):
    def test_eylul_2026(self):
        p = OdemeDurumuService.bes_aylik_pencere(date(2026, 9, 17))
        self.assertEqual(len(p), 5)
        self.assertEqual([(m["yil"], m["ay"]) for m in p], [
            (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12),
        ])
        self.assertEqual(p[0]["rol"], ROL_GECEN)
        self.assertEqual(p[0]["etiket"], "Geçen Ay")
        self.assertEqual(p[1]["rol"], ROL_BU_AY)
        self.assertEqual(p[1]["etiket"], "Bu Ay")
        self.assertEqual(p[1]["baslik"], "EYLÜL 2026")
        self.assertTrue(all(m["rol"] == ROL_GELECEK for m in p[2:]))
        self.assertTrue(all(m["etiket"] == "Gelecek Dönem" for m in p[2:]))

    def test_ocak_yil_gecisi(self):
        p = OdemeDurumuService.bes_aylik_pencere(date(2027, 1, 5))
        self.assertEqual([(m["yil"], m["ay"]) for m in p], [
            (2026, 12), (2027, 1), (2027, 2), (2027, 3), (2027, 4),
        ])

    def test_aralik_yil_gecisi(self):
        p = OdemeDurumuService.bes_aylik_pencere(date(2026, 12, 31))
        self.assertEqual([(m["yil"], m["ay"]) for m in p], [
            (2026, 11), (2026, 12), (2027, 1), (2027, 2), (2027, 3),
        ])

    def test_subat_artik_yil(self):
        p = OdemeDurumuService.bes_aylik_pencere(date(2024, 2, 29))
        self.assertEqual(p[1]["ay"], 2)
        self.assertEqual(p[1]["son"].day, 29)
        self.assertEqual(p[0]["ay"], 1)
        self.assertEqual([(m["yil"], m["ay"]) for m in p], [
            (2024, 1), (2024, 2), (2024, 3), (2024, 4), (2024, 5),
        ])

    def test_ay_ekle_takvim_ayi(self):
        # 30 gün ekleme değil — Ocak 1 → Şubat 1
        self.assertEqual(_ay_ekle(date(2026, 1, 1), 1), date(2026, 2, 1))
        self.assertEqual(_ay_ekle(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(len(BES_AYLIK_OFFSETLER), 5)

    def test_otomatik_donem_kaydirma(self):
        eylul = OdemeDurumuService.bes_aylik_pencere(date(2026, 9, 1))
        ekim = OdemeDurumuService.bes_aylik_pencere(date(2026, 10, 1))
        self.assertEqual([(m["yil"], m["ay"]) for m in eylul], [
            (2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12),
        ])
        self.assertEqual([(m["yil"], m["ay"]) for m in ekim], [
            (2026, 9), (2026, 10), (2026, 11), (2026, 12), (2027, 1),
        ])

    def test_bos_ay_ozeti(self):
        ozet = OdemeDurumuService.ay_ozeti(
            2026, 8, [], rol=ROL_GECEN, etiket="Geçen Ay", baslik="AĞUSTOS 2026"
        )
        self.assertTrue(ozet["bos"])
        self.assertEqual(ozet["toplam"], Decimal("0.00"))
        self.assertEqual(ozet["kalan"], Decimal("0.00"))
        self.assertEqual(ozet["odenen"], Decimal("0.00"))
        self.assertEqual(ozet["baslik"], "AĞUSTOS 2026")

    def test_kismi_odeme_durum_ve_kalan(self):
        durum = _durum_hesapla(
            date(2026, 9, 10),
            Decimal("250.00"),
            Decimal("750.00"),
            bugun=date(2026, 9, 17),
        )
        self.assertEqual(durum, DURUM_KISMI)

    def test_odenen_durum(self):
        durum = _durum_hesapla(
            date(2026, 8, 5),
            Decimal("0.00"),
            Decimal("1000.00"),
            bugun=date(2026, 9, 17),
        )
        self.assertEqual(durum, DURUM_ODENDI)

    def test_obligation_key_tekil(self):
        k1 = OdemeDurumuService.obligation_key(KAYNAK_KREDI, 42, date(2026, 9, 15))
        k2 = OdemeDurumuService.obligation_key(KAYNAK_KREDI, 42, date(2026, 9, 15))
        k3 = OdemeDurumuService.obligation_key(KAYNAK_KK, 42, date(2026, 9, 15))
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)


class BesAylikRaporFiltreTest(unittest.TestCase):
    """Filtre uygulansa bile her zaman 5 ay kartı kalır."""

    def _sahte_satirlar(self):
        return [
            {
                "obligation_key": "KREDI_TAKSIT:1:2026-09-10",
                "source_type": KAYNAK_KREDI,
                "source_id": 1,
                "due_date": date(2026, 9, 10),
                "aciklama": "Taksit 1",
                "kaynak_etiket": "Banka kredisi",
                "banka_adi": "Ziraat",
                "tl_tutar": Decimal("1000.00"),
                "odenen": Decimal("0.00"),
                "kalan": Decimal("1000.00"),
                "durum": DURUM_PLANLANDI,
            },
            {
                "obligation_key": "KREDI_KARTI_EKSTRE:x:2026-09-20",
                "source_type": KAYNAK_KK,
                "source_id": "x",
                "due_date": date(2026, 9, 20),
                "aciklama": "KK ekstre",
                "kaynak_etiket": "Kredi kartı",
                "banka_adi": "Garanti",
                "tl_tutar": Decimal("500.00"),
                "odenen": Decimal("0.00"),
                "kalan": Decimal("500.00"),
                "durum": DURUM_PLANLANDI,
            },
            {
                "obligation_key": "CEK_SENET:9:2026-08-05",
                "source_type": KAYNAK_CEK,
                "source_id": 9,
                "due_date": date(2026, 8, 5),
                "aciklama": "Gecikmiş çek",
                "kaynak_etiket": "Çek / Senet",
                "banka_adi": "İş Bankası",
                "tl_tutar": Decimal("200.00"),
                "odenen": Decimal("0.00"),
                "kalan": Decimal("200.00"),
                "durum": DURUM_GECIKMIS,
            },
            {
                "obligation_key": "KREDI_TAKSIT:2:2026-08-01",
                "source_type": KAYNAK_KREDI,
                "source_id": 2,
                "due_date": date(2026, 8, 1),
                "aciklama": "Ödenen taksit",
                "kaynak_etiket": "Banka kredisi",
                "banka_adi": "Ziraat",
                "tl_tutar": Decimal("300.00"),
                "odenen": Decimal("300.00"),
                "kalan": Decimal("0.00"),
                "durum": DURUM_ODENDI,
            },
        ]

    def test_filtre_bes_ay_korunur_ve_bos_aylar_kalir(self):
        satirlar = self._sahte_satirlar()

        def _fake_tum(**kwargs):
            ks = kwargs.get("kaynaklar")
            out = list(satirlar)
            if ks:
                out = [s for s in out if s["source_type"] in ks]
            return out

        with patch.object(OdemeDurumuService, "yetki_kontrol", return_value=None), patch.object(
            OdemeDurumuService, "tum_yukumlulukler", side_effect=_fake_tum
        ), patch.object(
            OdemeDurumuService, "referans_tarih", return_value=date(2026, 9, 17)
        ):
            rapor = OdemeDurumuService.bes_aylik_rapor(
                referans=date(2026, 9, 17),
                sadece_acik=True,
                odenenleri_dahil=False,
                kaynaklar={KAYNAK_KREDI},  # sadece kredi → KK ve çek düşer
            )

        self.assertEqual(len(rapor["aylar"]), 5)
        self.assertEqual(
            [(a["yil"], a["ay"]) for a in rapor["aylar"]],
            [(2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12)],
        )
        # Ekim–Aralık boş kalmalı
        for ay in rapor["aylar"][2:]:
            self.assertTrue(ay["gorunen_bos"] or ay["bos"])
            self.assertEqual(ay["filtre_adet"], 0)

        agustos = rapor["aylar"][0]
        self.assertEqual(agustos["baslik"], "AĞUSTOS 2026")
        self.assertEqual(agustos["rol"], ROL_GECEN)

        eylul = rapor["aylar"][1]
        self.assertEqual(eylul["rol"], ROL_BU_AY)
        self.assertEqual(eylul["filtre_adet"], 1)  # yalnızca kredi taksiti
        self.assertEqual(eylul["gorunen_satirlar"][0]["source_type"], KAYNAK_KREDI)

    def test_tutar_filtresi_bes_ayi_korur(self):
        satirlar = self._sahte_satirlar()

        with patch.object(OdemeDurumuService, "yetki_kontrol", return_value=None), patch.object(
            OdemeDurumuService, "tum_yukumlulukler", return_value=list(satirlar)
        ):
            rapor = OdemeDurumuService.bes_aylik_rapor(
                referans=date(2026, 9, 17),
                min_tutar=Decimal("800.00"),
                max_tutar=Decimal("2000.00"),
                sadece_acik=True,
            )
        self.assertEqual(len(rapor["aylar"]), 5)
        eylul = rapor["aylar"][1]
        # 1000 TL kredi geçer, 500 TL KK elenir
        self.assertEqual(eylul["filtre_adet"], 1)
        self.assertEqual(eylul["gorunen_satirlar"][0]["kalan"], Decimal("1000.00"))

    def test_mukerrer_obligation_birlesir(self):
        ayni = {
            "obligation_key": "KREDI_TAKSIT:1:2026-09-10",
            "source_type": KAYNAK_KREDI,
            "source_id": 1,
            "due_date": date(2026, 9, 10),
            "aciklama": "Taksit",
            "kaynak_etiket": "Banka kredisi",
            "banka_adi": "X",
            "tl_tutar": Decimal("100.00"),
            "odenen": SIFIR,
            "kalan": Decimal("100.00"),
            "durum": DURUM_PLANLANDI,
        }
        cift = [dict(ayni), dict(ayni)]
        birlesik: dict = {}
        for s in cift:
            birlesik[s["obligation_key"]] = s
        self.assertEqual(len(birlesik), 1)


if __name__ == "__main__":
    unittest.main()
