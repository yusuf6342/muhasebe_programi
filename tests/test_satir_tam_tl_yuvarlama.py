"""Satış faturası satır toplamı tam TL yuvarlama (ROUND_HALF_UP)."""

from decimal import Decimal
import unittest

from database.iskonto_hesap_service import round_line_total, satir_net_brut_indirim
from database.satis_faturasi_service import SatisFaturasiService
from database.alis_faturasi_service import AlisFaturasiService


class RoundLineTotalTest(unittest.TestCase):
    def test_zorunlu_ornek_1000_x_03241(self):
        ham = Decimal("1000") * Decimal("0.3241")
        self.assertEqual(ham, Decimal("324.1000"))
        self.assertEqual(round_line_total(ham), Decimal("324"))

    def test_alt_ust_sinir(self):
        self.assertEqual(round_line_total(Decimal("324.10")), Decimal("324"))
        self.assertEqual(round_line_total(Decimal("324.49")), Decimal("324"))
        self.assertEqual(round_line_total(Decimal("324.50")), Decimal("325"))
        self.assertEqual(round_line_total(Decimal("324.99")), Decimal("325"))

    def test_negatif_simetrik(self):
        self.assertEqual(round_line_total(Decimal("-324.50")), Decimal("-325"))
        self.assertEqual(round_line_total(Decimal("-324.49")), Decimal("-324"))

    def test_float_string_uzerinden(self):
        # float doğrudan Decimal'e verilmez; str ile
        self.assertEqual(round_line_total("324.50"), Decimal("325"))

    def test_coklu_satir_toplami(self):
        a = round_line_total(Decimal("324.10"))
        b = round_line_total(Decimal("10.50"))
        self.assertEqual(a + b, Decimal("335"))


class SatisSatirNetTamTlTest(unittest.TestCase):
    def test_vida_ornek_birim_fiyat_korunur(self):
        fiyat = Decimal("0.3241")
        brut, indirim, net = SatisFaturasiService._satir_net(1000, fiyat, 0, 0, 0)
        self.assertEqual(net, Decimal("324"))
        self.assertEqual(brut, Decimal("324"))
        self.assertEqual(indirim, Decimal("0"))
        # Ham çarpım kontrolü — birim fiyat değişmez
        self.assertEqual(Decimal("1000") * fiyat, Decimal("324.1000"))

    def test_1_x_32449_ve_32450(self):
        _, _, n49 = SatisFaturasiService._satir_net(1, Decimal("324.49"), 0, 0, 0)
        _, _, n50 = SatisFaturasiService._satir_net(1, Decimal("324.50"), 0, 0, 0)
        self.assertEqual(n49, Decimal("324"))
        self.assertEqual(n50, Decimal("325"))

    def test_kdv_yuvarlanmis_matrahtan(self):
        _, _, net = SatisFaturasiService._satir_net(1000, Decimal("0.3241"), 0, 0, 0)
        kdv = (net * Decimal("20") / Decimal("100")).quantize(
            Decimal("0.01")
        )
        self.assertEqual(net, Decimal("324"))
        self.assertEqual(kdv, Decimal("64.80"))
        self.assertEqual(net + kdv, Decimal("388.80"))

    def test_alis_ham_kalir_satis_yuvarlar(self):
        """Alış ortak motoru kuruşta kalır; satış _satir_net tam TL."""
        ham_b, ham_i, ham_n = satir_net_brut_indirim(1000, Decimal("0.3241"), 0, 0, 0)
        self.assertEqual(ham_n, Decimal("324.1000"))
        _, _, satis_n = SatisFaturasiService._satir_net(1000, Decimal("0.3241"), 0, 0, 0)
        self.assertEqual(satis_n, Decimal("324"))
        alis = AlisFaturasiService.toplam(
            [
                {
                    "miktar": 1000,
                    "birim_fiyat": Decimal("0.3241"),
                    "iskonto_orani": 0,
                    "iskonto_orani_2": 0,
                    "iskonto_orani_3": 0,
                    "kdv_orani": 0,
                }
            ]
        )
        # Alış: ara = 324.10 (kuruş)
        self.assertEqual(alis["ara_toplam"], Decimal("324.10"))

    def test_toplam_coklu_satir(self):
        toplam = SatisFaturasiService.toplam(
            [
                {
                    "miktar": 1000,
                    "birim_fiyat": Decimal("0.3241"),
                    "iskonto_orani": 0,
                    "kdv_orani": 0,
                },
                {
                    "miktar": 1,
                    "birim_fiyat": Decimal("10.50"),
                    "iskonto_orani": 0,
                    "kdv_orani": 0,
                },
            ]
        )
        # 324 + 11 = 335
        self.assertEqual(toplam["genel_toplam"], Decimal("335.00"))
        self.assertEqual(toplam["ara_toplam"], Decimal("335.00"))


if __name__ == "__main__":
    unittest.main()
