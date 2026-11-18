"""Alış net birim → stok alış fiyatı (KDV dahil) kuralları."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from database.alis_stok_fiyat_service import (
    evo_alis_mi,
    fatura_sira_anahtari,
    net_birim_kdv_dahil,
    net_birim_kdv_haric,
    satir_net_birim_ana,
)


class AlisStokFiyatTest(TestCase):
    def test_ardisik_iskonto_kdv_haric(self):
        # 0.756 × (1-0.58) × (1-0.05) = 0.301644
        net = net_birim_kdv_haric("0.756", "58", "5", "0")
        self.assertEqual(net, Decimal("0.301644"))

    def test_talimat_kdv20_100_to_120(self):
        """KDV hariç net 100 TL, KDV %20 → stok alış 120 TL."""
        self.assertEqual(net_birim_kdv_dahil(100, 0, 0, 0, 20), Decimal("120"))
        fatura = SimpleNamespace(para_birimi="TRY", kur=1)
        satir = SimpleNamespace(
            miktar=1,
            urun_kodu="T1",
            birim_fiyat=Decimal("100"),
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=20,
            birim_carpani=1,
            birim_fiyat_doviz=0,
            kdv_dahil=False,
        )
        self.assertEqual(satir_net_birim_ana(satir, fatura, kdv_dahil=True), Decimal("120"))

    def test_talimat_zaten_dahil_120_ikinci_kez_yok(self):
        """Zaten KDV dahil 120 TL → stok alış 120 TL; tekrar KDV eklenmez."""
        self.assertEqual(
            net_birim_kdv_dahil(120, 0, 0, 0, 20, kdv_dahil_giris=True),
            Decimal("120"),
        )
        fatura = SimpleNamespace(para_birimi="TRY", kur=1)
        satir = SimpleNamespace(
            miktar=1,
            urun_kodu="T2",
            birim_fiyat=Decimal("120"),
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=20,
            birim_carpani=1,
            birim_fiyat_doviz=0,
            kdv_dahil=True,
        )
        self.assertEqual(satir_net_birim_ana(satir, fatura, kdv_dahil=True), Decimal("120"))

    def test_talimat_kdv0_100_kalir(self):
        """KDV %0, net 100 TL → stok alış 100 TL."""
        self.assertEqual(net_birim_kdv_dahil(100, 0, 0, 0, 0), Decimal("100"))
        fatura = SimpleNamespace(para_birimi="TRY", kur=1)
        satir = SimpleNamespace(
            miktar=1,
            urun_kodu="T3",
            birim_fiyat=Decimal("100"),
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=0,
            birim_carpani=1,
            birim_fiyat_doviz=0,
        )
        self.assertEqual(satir_net_birim_ana(satir, fatura, kdv_dahil=True), Decimal("100"))

    def test_ardisik_iskonto_sonrasi_kdv_dahil(self):
        # 0.301644 × 1.20 = 0.3619728
        net = net_birim_kdv_dahil("0.756", 58, 5, 0, 20)
        self.assertEqual(net, Decimal("0.3619728"))

    def test_yuksek_miktar_hassasiyet_kdv0(self):
        net = net_birim_kdv_dahil("2.6904", 58, 5, 0, 0)
        self.assertEqual(net, Decimal("1.0734696"))
        self.assertEqual((Decimal("4800") * net).quantize(Decimal("0.01")), Decimal("5152.65"))

    def test_satir_ana_birim_carpan_kdv(self):
        fatura = SimpleNamespace(para_birimi="TRY", kur=1, genel_islem_tutari=0, genel_islem_turu=None)
        satir = SimpleNamespace(
            miktar=2,
            urun_kodu="X",
            birim_fiyat=Decimal("100"),
            iskonto_orani=0,
            iskonto_orani_2=0,
            iskonto_orani_3=0,
            kdv_orani=20,
            birim_carpani=Decimal("1"),
            birim_fiyat_doviz=0,
        )
        self.assertEqual(satir_net_birim_ana(satir, fatura, kdv_dahil=True), Decimal("120"))
        self.assertEqual(satir_net_birim_ana(satir, fatura, kdv_dahil=False), Decimal("100"))

    def test_evo_oneki(self):
        self.assertTrue(evo_alis_mi(SimpleNamespace(kaynak_sistem=None, fatura_no="EVB-AF-123")))
        self.assertTrue(evo_alis_mi(SimpleNamespace(kaynak_sistem="EVOBULUT", fatura_no="SERI1")))
        self.assertFalse(evo_alis_mi(SimpleNamespace(kaynak_sistem="CIN_MUHASEBE", fatura_no="EVB-AF-1")))
        self.assertFalse(evo_alis_mi(SimpleNamespace(kaynak_sistem=None, fatura_no="ARAY000040")))

    def test_sira_deterministik(self):
        a = SimpleNamespace(
            fatura_tarihi=date(2026, 11, 1),
            islem_saati="10:00",
            onay_tarihi=None,
            id=10,
        )
        b = SimpleNamespace(
            fatura_tarihi=date(2026, 11, 1),
            islem_saati="10:00",
            onay_tarihi=None,
            id=11,
        )
        self.assertGreater(fatura_sira_anahtari(b), fatura_sira_anahtari(a))
