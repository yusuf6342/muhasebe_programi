"""Zorunlu takvim / tutar / plan düzenleme testleri (talimat §15 A–B)."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.finans_service import FinansService
from database.kk_plan_service import plan_onizleme


class KkTaksitTakvimTest(unittest.TestCase):
    def test_13_kasim_6_taksit(self):
        plan = FinansService.kk_taksit_plani(date(2026, 11, 13), 6, Decimal("1200.00"))
        self.assertEqual(
            [s["vade_tarihi"] for s in plan],
            [
                date(2026, 11, 13),
                date(2026, 12, 13),
                date(2027, 1, 13),
                date(2027, 2, 13),
                date(2027, 3, 13),
                date(2027, 4, 13),
            ],
        )

    def test_31_ocak_6_taksit(self):
        plan = FinansService.kk_taksit_plani(date(2027, 1, 31), 6, Decimal("600.00"))
        self.assertEqual(
            [s["vade_tarihi"] for s in plan],
            [
                date(2027, 1, 31),
                date(2027, 2, 28),
                date(2027, 3, 31),
                date(2027, 4, 30),
                date(2027, 5, 31),
                date(2027, 6, 30),
            ],
        )

    def test_30_ocak_3_taksit(self):
        plan = FinansService.kk_taksit_plani(date(2027, 1, 30), 3, Decimal("300.00"))
        self.assertEqual(
            [s["vade_tarihi"] for s in plan],
            [date(2027, 1, 30), date(2027, 2, 28), date(2027, 3, 30)],
        )

    def test_artik_yil_31_ocak(self):
        plan = FinansService.kk_taksit_plani(date(2028, 1, 31), 3, Decimal("300.00"))
        self.assertEqual(
            [s["vade_tarihi"] for s in plan],
            [date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)],
        )

    def test_28_subat_sonraki_28_mart(self):
        plan = FinansService.kk_taksit_plani(date(2027, 2, 28), 2, Decimal("100.00"))
        self.assertEqual(
            [s["vade_tarihi"] for s in plan],
            [date(2027, 2, 28), date(2027, 3, 28)],
        )

    def test_1_6_12_taksit_ilk_islem_gunu(self):
        for n in (1, 6, 12):
            plan = FinansService.kk_taksit_plani(date(2026, 11, 13), n, Decimal("1200.00"))
            self.assertEqual(len(plan), n)
            self.assertEqual(plan[0]["vade_tarihi"], date(2026, 11, 13))

    def test_kurus_dagilimi(self):
        plan = FinansService.kk_taksit_plani(date(2026, 11, 13), 3, Decimal("1000.00"))
        self.assertEqual([s["tutar"] for s in plan], [
            Decimal("333.33"), Decimal("333.33"), Decimal("333.34"),
        ])
        self.assertEqual(sum((s["tutar"] for s in plan), Decimal("0")), Decimal("1000.00"))

    def test_sifir_ve_negatif_red(self):
        with self.assertRaises(ValueError):
            FinansService.kk_taksit_plani(date(2026, 11, 13), 3, Decimal("0"))
        with self.assertRaises(ValueError):
            FinansService.kk_taksit_plani(date(2026, 11, 13), 3, Decimal("-10"))
        with self.assertRaises(ValueError):
            FinansService.kk_taksit_plani(date(2026, 11, 13), 0, Decimal("100"))

    def test_kart_kesim_ic_plan_ezilmez(self):
        kart = SimpleNamespace(
            hesap_kesim_gunu=7,
            son_odeme_gunu=None,
            kesimden_sonra_odeme_gun=1,
            kart_adi="Test",
        )
        plan = FinansService.kk_taksit_plani(
            date(2026, 10, 19), 2, Decimal("100.00"), kart=kart
        )
        self.assertEqual(plan[0]["vade_tarihi"], date(2026, 10, 19))
        self.assertEqual(plan[0]["ekstre_kesim_tarihi"], date(2026, 11, 7))
        self.assertIsNotNone(plan[0].get("banka_vade_tarihi"))

    def test_kalan_plan_6000_ornek(self):
        # 6000 / 6, 2000 ödenmiş → kalan 4000 / 2
        plan = plan_onizleme(
            Decimal("4000.00"),
            2,
            date(2026, 12, 1),
        )
        self.assertEqual(len(plan), 2)
        self.assertEqual(sum((s["tutar"] for s in plan), Decimal("0")), Decimal("4000.00"))
        self.assertEqual(plan[0]["vade_tarihi"], date(2026, 12, 1))
        self.assertEqual(plan[1]["vade_tarihi"], date(2027, 1, 1))

    def test_ilk_taksit_oner_islem_gunu(self):
        self.assertEqual(
            FinansService.kk_ilk_taksit_oner(None, date(2026, 11, 13)),
            date(2026, 11, 13),
        )


class KkPlanDuzenleServisTest(unittest.TestCase):
    def test_tamamen_odenen_yeniden_borclanmaz(self):
        from database import kk_plan_service as S

        ozet = {
            "odeme_id": 1,
            "belge_no": "KKO-1",
            "tarih": date(2026, 1, 1),
            "tutar": Decimal("100.00"),
            "plan_versiyon": 1,
            "odenen_toplam": Decimal("100.00"),
            "kalan_anapara": Decimal("0.00"),
            "tamamen_odendi": True,
            "satirlar": [],
            "kredi_karti_id": 1,
        }
        with patch.object(S, "plan_durum_ozeti", return_value=ozet):
            with patch.object(S, "schema_hazirla"):
                with patch.object(S, "get_session") as gs:
                    # plani_duzenle kendi session'ında kalanı hesaplar; mock odeme
                    odeme = MagicMock()
                    odeme.durum = "AÇIK"
                    odeme.tutar = Decimal("100.00")
                    odeme.plan_versiyon = 1
                    odeme.tarih = date(2026, 1, 1)
                    odeme.kredi_karti_id = 1
                    odeme.kredi_karti = None
                    odeme.aciklama = ""
                    t = MagicMock()
                    t.aktif = True
                    t.durum = "ODENDI"
                    t.tutar = Decimal("100.00")
                    t.odenen_tutar = Decimal("100.00")
                    t.taksit_no = 1
                    t.vade_tarihi = date(2026, 1, 1)
                    t.id = 1
                    odeme.taksitler = [t]
                    session = MagicMock()
                    session.scalar.return_value = odeme
                    session.scalars.return_value.all.return_value = []
                    gs.return_value.__enter__.return_value = session
                    with patch("database.access.yazma_zorunlu"):
                        with self.assertRaises(ValueError) as ctx:
                            S.plani_duzenle(
                                1,
                                yeni_kalan_taksit_sayisi=2,
                                yeni_baslangic_vade=date(2026, 2, 1),
                                aciklama="test",
                            )
                        self.assertIn("Kalan borç yok", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
