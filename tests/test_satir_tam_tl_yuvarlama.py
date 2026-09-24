"""Satış faturası satır toplamı — kuruş hassasiyeti (tam TL alta/üste yok)."""

from decimal import Decimal
import unittest

from database.iskonto_hesap_service import round_line_total, satir_net_brut_indirim
from database.satis_faturasi_service import SatisFaturasiService
from database.alis_faturasi_service import AlisFaturasiService


class RoundLineTotalHelperTest(unittest.TestCase):
    """Yardımcı hâlâ tam TL yapabilir; satış satırı artık kullanmaz."""

    def test_yardimci_tam_tl(self):
        self.assertEqual(round_line_total(Decimal("324.10")), Decimal("324"))
        self.assertEqual(round_line_total(Decimal("324.50")), Decimal("325"))


class SatisSatirNetKurusTest(unittest.TestCase):
    def test_vida_ornek_kurus_korunur(self):
        fiyat = Decimal("0.3241")
        brut, indirim, net = SatisFaturasiService._satir_net(1000, fiyat, 0, 0, 0)
        self.assertEqual(net, Decimal("324.10"))
        self.assertEqual(brut, Decimal("324.10"))
        self.assertEqual(indirim, Decimal("0"))
        self.assertEqual(Decimal("1000") * fiyat, Decimal("324.1000"))

    def test_1_x_32449_ve_32450_kurus(self):
        _, _, n49 = SatisFaturasiService._satir_net(1, Decimal("324.49"), 0, 0, 0)
        _, _, n50 = SatisFaturasiService._satir_net(1, Decimal("324.50"), 0, 0, 0)
        self.assertEqual(n49, Decimal("324.49"))
        self.assertEqual(n50, Decimal("324.50"))

    def test_kdv_kuruslu_matrahtan(self):
        _, _, net = SatisFaturasiService._satir_net(1000, Decimal("0.3241"), 0, 0, 0)
        kdv = (net * Decimal("20") / Decimal("100")).quantize(Decimal("0.01"))
        self.assertEqual(net, Decimal("324.10"))
        self.assertEqual(kdv, Decimal("64.82"))
        self.assertEqual(net + kdv, Decimal("388.92"))

    def test_alis_ve_satis_kurus_uyumlu(self):
        ham_b, ham_i, ham_n = satir_net_brut_indirim(1000, Decimal("0.3241"), 0, 0, 0)
        self.assertEqual(ham_n, Decimal("324.1000"))
        _, _, satis_n = SatisFaturasiService._satir_net(1000, Decimal("0.3241"), 0, 0, 0)
        self.assertEqual(satis_n, Decimal("324.10"))
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
        self.assertEqual(alis["ara_toplam"], Decimal("324.10"))

    def test_toplam_coklu_satir_kurus(self):
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
        # 324.10 + 10.50 = 334.60 (tam TL yok)
        self.assertEqual(toplam["genel_toplam"], Decimal("334.60"))
        self.assertEqual(toplam["ara_toplam"], Decimal("334.60"))


if __name__ == "__main__":
    unittest.main()
