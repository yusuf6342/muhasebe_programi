"""İskonto penceresi ↔ satır uyuşmazlığı — 10→1 kırpma ve 10/8/5 senkron testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal

from database.iskonto_hesap_service import (
    etkili_iskonto_orani,
    iskonto_goster_metin,
    iskonto_oran_metin,
    satir_iskonto_hesapla,
)
from database.alis_faturasi_service import AlisFaturasiService
from database.satis_faturasi_service import SatisFaturasiService


class OranMetinKirpmaTest(unittest.TestCase):
    """Eski bug: f'{o:f}'.rstrip('0') → 10→1, 100→1."""

    def test_10_20_100_kirpilmaz(self):
        self.assertEqual(iskonto_oran_metin(10), "10")
        self.assertEqual(iskonto_oran_metin(20), "20")
        self.assertEqual(iskonto_oran_metin(100), "100")
        self.assertEqual(iskonto_oran_metin("10"), "10")
        self.assertEqual(iskonto_oran_metin(Decimal("10.00")), "10")

    def test_ondalik_korunur(self):
        self.assertEqual(iskonto_oran_metin(Decimal("12.5")), "12.5")
        self.assertEqual(iskonto_oran_metin("7.25"), "7.25")

    def test_sifir(self):
        self.assertEqual(iskonto_oran_metin(0), "0")
        self.assertEqual(iskonto_oran_metin(""), "0")

    def test_eski_rstrip_bug_simule(self):
        """Doğrudan rstrip('0') 10'u 1 yapar — yeni helper yapmaz."""
        eski = f"{Decimal('10'):f}".rstrip("0").rstrip(".")
        self.assertEqual(eski, "1")  # eski hatalı davranış
        self.assertEqual(iskonto_oran_metin(10), "10")


class Ornek1085Test(unittest.TestCase):
    """Talimat örneği: 10+8+5, brüt 4200 / birim 60×70."""

    def test_etkili_oran(self):
        self.assertEqual(etkili_iskonto_orani(10, 8, 5), Decimal("21.34"))

    def test_brut_4200(self):
        h = satir_iskonto_hesapla(
            miktar=70,
            brut_birim_fiyat=Decimal("60"),
            iskonto1=10,
            iskonto2=8,
            iskonto3=5,
            kdv_orani=20,
        )
        self.assertEqual(h["brut_satir"], Decimal("4200.00"))
        self.assertEqual(h["iskonto_tutari"], Decimal("896.28"))
        self.assertEqual(h["iskonto_sonrasi_satir"], Decimal("3303.72"))
        self.assertEqual(h["iskonto_sonrasi_birim_fiyat"], Decimal("47.20"))
        self.assertEqual(h["net_birim_fiyat"], Decimal("56.64"))

    def test_yanlis_185_farkli(self):
        """Pencerede 1,8,5 görünürse (kırpma) tutar 565,91 olur — doğru 10,8,5 değil."""
        yanlis = satir_iskonto_hesapla(
            miktar=70,
            brut_birim_fiyat=Decimal("60"),
            iskonto1=1,
            iskonto2=8,
            iskonto3=5,
            kdv_orani=20,
        )
        dogru = satir_iskonto_hesapla(
            miktar=70,
            brut_birim_fiyat=Decimal("60"),
            iskonto1=10,
            iskonto2=8,
            iskonto3=5,
            kdv_orani=20,
        )
        self.assertEqual(yanlis["etkili_iskonto_orani"], Decimal("13.47"))
        self.assertEqual(yanlis["iskonto_tutari"], Decimal("565.91"))
        self.assertEqual(dogru["iskonto_tutari"], Decimal("896.28"))
        self.assertNotEqual(yanlis["iskonto_tutari"], dogru["iskonto_tutari"])

    def test_satir_metni(self):
        self.assertEqual(iskonto_goster_metin(10, 8, 5), "%10 + %8 + %5")
        self.assertEqual(iskonto_goster_metin(10, 0, 0), "%10")
        self.assertEqual(iskonto_goster_metin(0, 0, 0, bos_goster=""), "")


class SenaryoMatrisiTest(unittest.TestCase):
    def test_oran_kombinasyonlari(self):
        for i1, i2, i3 in (
            (0, 0, 0),
            (10, 0, 0),
            (10, 8, 0),
            (10, 8, 5),
            (12.5, 0, 0),
        ):
            h = satir_iskonto_hesapla(
                miktar=1,
                brut_birim_fiyat=1000,
                iskonto1=i1,
                iskonto2=i2,
                iskonto3=i3,
                kdv_orani=20,
            )
            self.assertEqual(h["iskonto_1_orani"], Decimal(str(i1)))
            metin = iskonto_goster_metin(i1, i2, i3, bos_goster="")
            if i1 or i2 or i3:
                self.assertIn("%", metin)
                if i1 == 10:
                    self.assertIn("%10", metin)
                    self.assertNotEqual(metin, "%1")


class SatisAlisOrtakMotorTest(unittest.TestCase):
    def test_ayni_sonuc(self):
        s_brut, s_ind, s_net = SatisFaturasiService._satir_net(70, 60, 10, 8, 5)
        a_net = AlisFaturasiService._net_birim_maliyet(
            Decimal("60"), Decimal("10"), 8, 5
        )
        self.assertEqual(s_net.quantize(Decimal("0.01")), Decimal("3303.72"))
        self.assertEqual(
            (a_net * 70).quantize(Decimal("0.01")), Decimal("3303.72")
        )
        self.assertEqual(s_ind.quantize(Decimal("0.01")), Decimal("896.28"))


class DialogOranYukleTest(unittest.TestCase):
    """Pencere açılışında ham oranlar kırpılmadan yüklenir."""

    def test_oran_metin_dialog_yolu(self):
        from database.iskonto_hesap_service import iskonto_oran_metin as svc

        satir = {"iskonto_orani": 10, "iskonto_orani_2": 8, "iskonto_orani_3": 5}
        self.assertEqual(svc(satir["iskonto_orani"]), "10")
        self.assertEqual(svc(satir["iskonto_orani_2"]), "8")
        self.assertEqual(svc(satir["iskonto_orani_3"]), "5")
        # fatura_iskonto_ui aynı helper'ı import eder
        import fatura_iskonto_ui as ui

        self.assertIs(ui.iskonto_oran_metin, svc)


if __name__ == "__main__":
    unittest.main()
