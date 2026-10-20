"""Prim motoru kabul senaryoları (ek talimat tablo 11)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.personel_prim_motoru import (
    DagitimKisi,
    havuz_hesapla,
    kisi_dagitimi,
    pos_uzlasma,
    tahsil_kar_katkisi,
)


class PrimMotoruTest(unittest.TestCase):
    def test_kismi_tahsilat_15000(self):
        h = tahsil_kar_katkisi(S=100_000, C=70_000, F=100_000, T=50_000)
        self.assertEqual(h["M"], Decimal("30000.00"))
        self.assertEqual(h["H"], Decimal("15000.00"))

    def test_sonraki_tahsilat_ilave(self):
        h1 = tahsil_kar_katkisi(S=100_000, C=70_000, F=100_000, T=50_000)
        h2 = tahsil_kar_katkisi(S=100_000, C=70_000, F=100_000, T=100_000)
        self.assertEqual(h2["H"] - h1["H"], Decimal("15000.00"))

    def test_f_sifir_h_sifir(self):
        h = tahsil_kar_katkisi(S=0, C=0, F=0, T=1000)
        self.assertEqual(h["H"], Decimal("0.00"))

    def test_negatif_marj_korunur(self):
        h = tahsil_kar_katkisi(S=10_000, C=15_000, F=11_800, T=11_800)
        self.assertEqual(h["M"], Decimal("-5000.00"))
        self.assertEqual(h["H"], Decimal("-5000.00"))

    def test_pos_uzlasma(self):
        p = pos_uzlasma("370", "4.03")
        self.assertEqual(p["net"], Decimal("365.97"))

    def test_zarar_devri(self):
        # G=5000, eski zarar 8000 → N=-3000, havuz 0, yeni zarar 3000
        h = havuz_hesapla(
            tahsil_kar_katkisi_toplam=5000,
            uygun_giderler=0,
            onceki_zarar_devri=8000,
            guvence_tutari=0,
            prim_orani="0.10",
        )
        self.assertEqual(h["G"], Decimal("5000.00"))
        self.assertEqual(h["yeni_zarar_devri"], Decimal("3000.00"))
        self.assertEqual(h["prim_butcesi"], Decimal("0.00"))

    def test_havuz_ornek_10000(self):
        h = havuz_hesapla(
            tahsil_kar_katkisi_toplam=300_000,
            uygun_giderler=180_000,
            onceki_zarar_devri=0,
            guvence_tutari=20_000,
            prim_orani="0.10",
        )
        self.assertEqual(h["B"], Decimal("100000.00"))
        self.assertEqual(h["prim_butcesi"], Decimal("10000.00"))

    def test_uc_kisi_dagitim(self):
        d = kisi_dagitimi(
            10_000,
            [
                DagitimKisi(1, 0, Decimal(80)),
                DagitimKisi(2, 2, Decimal(90)),
                DagitimKisi(3, 5, Decimal(100)),
            ],
        )
        paylar = {s["personel_id"]: s["toplam"] for s in d["kisiler"]}
        self.assertEqual(paylar[1], Decimal("3178.61"))
        self.assertEqual(paylar[2], Decimal("3327.10"))
        self.assertEqual(paylar[3], Decimal("3494.29"))
        self.assertEqual(d["dagitilan"], Decimal("10000.00"))
        self.assertEqual(d["dagitilmamis"], Decimal("0.00"))

    def test_katki_sifir_dilim_dagitilmaz(self):
        d = kisi_dagitimi(
            10_000,
            [
                DagitimKisi(1, 0, Decimal(0)),
                DagitimKisi(2, 1, Decimal(0)),
            ],
        )
        self.assertTrue(d["katki_dilimi_dagitilmadi"])
        self.assertEqual(d["dagitilmamis_detay"]["katki_dilimi"], Decimal("3000.00"))
        # katkı payları 0
        self.assertTrue(all(s["katki_payi"] == 0 for s in d["kisiler"]))

    def test_tekrar_ayni_sonuc(self):
        kisiler = [
            DagitimKisi(1, 0, Decimal(80)),
            DagitimKisi(2, 2, Decimal(90)),
            DagitimKisi(3, 5, Decimal(100)),
        ]
        a = kisi_dagitimi(10_000, kisiler)
        b = kisi_dagitimi(10_000, kisiler)
        self.assertEqual(a["kisiler"], b["kisiler"])


if __name__ == "__main__":
    unittest.main()
