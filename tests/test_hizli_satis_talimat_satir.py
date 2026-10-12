"""Hızlı Satış talimatı (07.10.2026) — bakiye/valör, satır birimi, fiyat listesi,
stok hareketleri, Genel Toplam / Yeni Toplam ve cari tutarlılığı.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_hizli_satis_talimat_satir.py -q
"""

from __future__ import annotations

import queue
import random
import sys
import time
import tkinter as tk
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hizli_satis_sepet import HizliSatisSepet  # noqa: E402


def _kayit_toplami(sepet: HizliSatisSepet) -> Decimal:
    """Kaydedilecek fatura toplamı — servis ile aynı yol."""
    from database.hizli_satis_service import HizliSatisService

    return HizliSatisService._genel_toplam_satirlardan(HizliSatisService._sepetten_satirlar(sepet))


def _sepet_600_400() -> HizliSatisSepet:
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="600")
    sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=1, birim_fiyat="400")
    return sepet


class YeniToplamModelTest(unittest.TestCase):
    def test_1000_900_800_1000_referanstan_dagitim(self):
        sepet = _sepet_600_400()
        self.assertEqual(sepet.referans_toplam(), Decimal("1000.00"))
        sepet.hedef_toplam_uygula("900")
        self.assertEqual([s.satir_toplam for s in sepet.satirlar], [Decimal("540.00"), Decimal("360.00")])
        self.assertEqual(sepet.referans_toplam(), Decimal("1000.00"))
        self.assertEqual(sepet.toplamlar()["genel_toplam"], Decimal("900.00"))
        sepet.hedef_toplam_uygula("800")
        self.assertEqual([s.satir_toplam for s in sepet.satirlar], [Decimal("480.00"), Decimal("320.00")])
        self.assertEqual(sepet.referans_toplam(), Decimal("1000.00"))
        sepet.hedef_toplam_uygula("1000")
        self.assertEqual([s.birim_fiyat for s in sepet.satirlar], [Decimal("600"), Decimal("400")])
        self.assertTrue(all(s.referans_birim_fiyat is None for s in sepet.satirlar))
        self.assertIsNone(sepet.hedef_toplam)

    def test_ayni_hedef_tekrar_indirim_ustune_binmez(self):
        sepet = _sepet_600_400()
        sepet.hedef_toplam_uygula("900")
        ilk = [s.birim_fiyat for s in sepet.satirlar]
        sepet.hedef_toplam_uygula("900")
        sepet.hedef_toplam_uygula("900")
        self.assertEqual([s.birim_fiyat for s in sepet.satirlar], ilk)

    def test_farkli_kdv_ve_kurus_tam_karsilanir(self):
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=3, birim_fiyat="33.33", kdv_orani=20)
        sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=7, birim_fiyat="12.5", kdv_orani=10)
        sepet.ekle(stok_id=3, stok_kodu="C", stok_adi="C", miktar=1, birim_fiyat="0.99", kdv_orani=0)
        sepet.ekle(stok_id=4, stok_kodu="D", stok_adi="D", miktar="2.5", birim_fiyat="19.9",
                   kdv_orani=1, iskonto_orani=7)
        genel = sepet.referans_toplam()
        kdvler = [s.kdv_orani for s in sepet.satirlar]
        rnd = random.Random(7)
        for _ in range(60):
            hedef = (genel * Decimal(str(rnd.uniform(0.5, 1.3)))).quantize(Decimal("0.01"))
            sepet.hedef_toplam_uygula(hedef)
            self.assertEqual(sepet.toplamlar()["genel_toplam"], hedef)
            self.assertEqual(_kayit_toplami(sepet), hedef, "kaydedilecek fatura toplamı Yeni Toplam olmalı")
            self.assertEqual(sepet.referans_toplam(), genel)
            self.assertEqual([s.kdv_orani for s in sepet.satirlar], kdvler)
            # Oran korunur (kuruş toleransı)
            for s in sepet.satirlar:
                beklenen = s.referans_satir_toplam * hedef / genel
                self.assertLess(abs(s.satir_toplam - beklenen), Decimal("0.05"))

    def test_sepet_ve_kayit_toplami_iskontoda_ayni(self):
        rnd = random.Random(3)
        for _ in range(200):
            sepet = HizliSatisSepet()
            sepet.ekle(
                stok_id=1, stok_kodu="A", stok_adi="A",
                miktar=Decimal(str(rnd.randint(1, 30))) / Decimal(rnd.choice([1, 2, 4])),
                birim_fiyat=Decimal(str(rnd.randint(1, 99999))) / Decimal("100"),
                iskonto_orani=Decimal(str(rnd.randint(0, 3500))) / Decimal("100"),
                kdv_orani=rnd.choice([0, 1, 8, 10, 18, 20]),
            )
            self.assertEqual(sepet.toplamlar()["genel_toplam"], _kayit_toplami(sepet))

    def test_gercek_sepet_degisikligi_duzeltmeyi_kaldirir(self):
        for islem in (
            lambda s: s.ekle(stok_id=3, stok_kodu="C", stok_adi="C", miktar=1, birim_fiyat="100"),
            lambda s: s.sil(1),
            lambda s: s.miktar_ayarla(0, 2),
            lambda s: s.fiyat_ayarla(1, "450"),
            lambda s: s.iskonto_ayarla(0, 5),
            lambda s: s.kdv_ayarla(0, 20),
            lambda s: s.birim_uygula(0, birim="Koli", miktar="0.1", birim_fiyat="6000", carpan=10),
        ):
            sepet = _sepet_600_400()
            sepet.hedef_toplam_uygula("900")
            islem(sepet)
            self.assertTrue(sepet.son_degisiklik_duzeltme_kaldirdi)
            self.assertFalse(sepet.duzeltme_aktif)
            self.assertIsNone(sepet.hedef_toplam)
            self.assertEqual(sepet.toplamlar()["genel_toplam"], sepet.referans_toplam())

    def test_sifir_genel_negatif_ve_bos(self):
        sepet = HizliSatisSepet()
        with self.assertRaises(ValueError):
            sepet.hedef_toplam_uygula(100)
        sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="0")
        with self.assertRaises(ValueError) as ctx:
            sepet.hedef_toplam_uygula(100)
        self.assertIn("Genel Toplam sıfır", str(ctx.exception))
        with self.assertRaises(ValueError):
            _sepet_600_400().hedef_toplam_uygula("-1")

    def test_iptal_edilen_yeni_toplam_satiri_degistirmez(self):
        sepet = _sepet_600_400()
        sepet.hedef_toplam_uygula("900")
        once = [(s.birim_fiyat, s.referans_birim_fiyat) for s in sepet.satirlar]
        with patch.object(HizliSatisSepet, "_tam_fiyat_bul", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                sepet.hedef_toplam_uygula("850")
        self.assertEqual([(s.birim_fiyat, s.referans_birim_fiyat) for s in sepet.satirlar], once)
        self.assertEqual(sepet.hedef_toplam, Decimal("900.00"))


class YardimciMetinTest(unittest.TestCase):
    def test_yeni_toplam_girisi(self):
        from hizli_satis_ui import _hedef_metni_coz

        self.assertIsNone(_hedef_metni_coz(""))
        self.assertIsNone(_hedef_metni_coz("9,"))
        self.assertIsNone(_hedef_metni_coz("-"))
        self.assertEqual(_hedef_metni_coz("1.050,25"), Decimal("1050.25"))
        self.assertEqual(_hedef_metni_coz("900"), Decimal("900.00"))
        for kotu in ("-5", "abc", "12a"):
            with self.assertRaises(ValueError):
                _hedef_metni_coz(kotu)

    def test_bakiye_valor_metni_cari_kart_kurali(self):
        from cari_borc_alacak_ozet import kisa_bakiye_valor_metni

        b, v, _ = kisa_bakiye_valor_metni(
            {"bakiye": Decimal("12500"), "bakiye_yonu": "BORCLU",
             "ortalama_valor_tarihi": date(2026, 10, 15)}
        )
        self.assertEqual((b, v), ("Bakiye 12.500,00 TL Borç", "Valör 15.10.2026"))
        b, v, _ = kisa_bakiye_valor_metni({"bakiye": Decimal("-250.5"), "bakiye_yonu": "ALACAKLI"})
        self.assertEqual((b, v), ("Bakiye 250,50 TL Alacak", "Valör bilgisi yok"))
        b, _v, _ = kisa_bakiye_valor_metni({"bakiye": Decimal("0"), "bakiye_yonu": "KAPALI"})
        self.assertEqual(b, "Bakiye 0,00 TL Kapalı")


class _PencereStub:
    """Tk açmadan pencere metotlarını çağırmak için minimal nesne."""

    def __init__(self):
        self.etiketler: list[tuple] = []
        self.cagrilar: list[str] = []
        self._bakiye_seq = 0
        self.secili_cari = None
        self.sepet = object()
        self._sepet_odak_sutun = None
        self.sepet_model = SimpleNamespace(satirlar=[1, 2])

    def winfo_exists(self):
        return True

    def after(self, _ms, _fn):
        return None

    def _bakiye_etiketleri(self, b, v, r):
        self.etiketler.append((b, v))

    def focus_get(self):
        return self.sepet

    def _secili_index(self):
        return 0

    def _fiyat_listesi_ac(self, idx):
        self.cagrilar.append("fiyat")

    def _stok_hareketleri_ac(self, idx):
        self.cagrilar.append("hareket")

    def _odeme_al(self):
        self.cagrilar.append("odeme")
        return "break"


class PencereMantigiTest(unittest.TestCase):
    def test_gec_gelen_eski_musteri_sonucu_yazilmaz(self):
        from hizli_satis_ui import HizliSatisPencere

        stub = _PencereStub()
        kutu_a, kutu_b = queue.Queue(), queue.Queue()
        stub.secili_cari = {"id": 1}
        stub._bakiye_seq = 1  # A isteği
        stub.secili_cari = {"id": 2}
        stub._bakiye_seq = 2  # B isteği
        kutu_b.put(("ok", {"bakiye": Decimal("10"), "bakiye_yonu": "BORCLU"}))
        HizliSatisPencere._bakiye_valor_bekle(stub, 2, 2, kutu_b)
        kutu_a.put(("ok", {"bakiye": Decimal("999"), "bakiye_yonu": "BORCLU"}))
        HizliSatisPencere._bakiye_valor_bekle(stub, 1, 1, kutu_a)  # geç gelen A
        self.assertEqual(stub.etiketler, [("Bakiye 10,00 TL Borç", "Valör bilgisi yok")])
        self.assertEqual(stub.secili_cari["bakiye"], Decimal("10"))

    def test_sorgu_hatasi_sifir_gostermez(self):
        from hizli_satis_ui import HizliSatisPencere

        stub = _PencereStub()
        stub.secili_cari = {"id": 5}
        stub._bakiye_seq = 1
        kutu = queue.Queue()
        kutu.put(("hata", "db kilitli"))
        HizliSatisPencere._bakiye_valor_bekle(stub, 1, 5, kutu)
        self.assertEqual(stub.etiketler[0][0], "Bakiye/valör alınamadı")
        self.assertNotIn("0,00", stub.etiketler[0][0])

    def test_f10_hucreye_gore_tek_islem(self):
        from hizli_satis_ui import HizliSatisPencere

        for sutun, beklenen in (("fiyat", ["fiyat"]), ("ad", ["hareket"]), ("miktar", ["odeme"]),
                                (None, ["odeme"])):
            stub = _PencereStub()
            stub._sepet_odak_sutun = sutun
            HizliSatisPencere._f10_tusu(stub)
            self.assertEqual(stub.cagrilar, beklenen, sutun)
        stub = _PencereStub()
        stub._sepet_odak_sutun = "fiyat"
        stub.focus_get = lambda: object()  # sepet dışında F10 → ödeme
        HizliSatisPencere._f10_tusu(stub)
        self.assertEqual(stub.cagrilar, ["odeme"])


class _DbTabani(unittest.TestCase):
    def setUp(self):
        from database.database import get_session
        from database.models.cari import Cari
        from database.models.finans import FinansHesabi
        from database.models.stok import StokBirim, StokFiyati, StokKarti
        from sqlalchemy import select
        from tests.stok_test_ortami import StokOrtami

        from database import hizli_satis_service as mod

        with mod._token_kilidi:
            mod._kullanilan_tokenler.clear()
        self.ortam = StokOrtami("hs_talimat")
        with get_session() as s:
            s.add(FinansHesabi(hesap_adi="ANA KASA", hesap_turu="KASA", aktif=True))
            s.add(Cari(cari_kodu="M002", unvan="İkinci Müşteri", cari_turu="Müşteri", aktif=True))
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            koli = s.scalar(select(StokBirim).where(StokBirim.stok_id == stok.id))
            koli.carpan = Decimal("10")
            koli.satis_1 = Decimal("95")  # koliye özel bağımsız fiyat
            s.add(StokBirim(stok_id=stok.id, birim_adi="Paket", carpan=Decimal("5"),
                            satis_kullanilabilir=False))
            s.add(StokBirim(stok_id=stok.id, birim_adi="Bozuk", carpan=Decimal("0")))
            s.add(StokBirim(stok_id=stok.id, birim_adi="Eski", carpan=Decimal("3"), aktif=False))
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("10"), para_birimi="TL"))
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="SATIŞ FİYATI 2", tutar=Decimal("12"), para_birimi="TL"))
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="ALIŞ FİYATI", tutar=Decimal("5"), para_birimi="TL"))
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="SATIŞ FİYATI 3", tutar=Decimal("0"), para_birimi="TL"))
            s.commit()
            self.stok_id = int(stok.id)
            self.m2_id = int(s.scalar(select(Cari.id).where(Cari.cari_kodu == "M002")))
        self.ortam.alis(1000, 5, date.today() - timedelta(days=3))

    def tearDown(self):
        self.ortam.kapat()

    def _sepet(self, birim="Adet", miktar="1", fiyat="10") -> HizliSatisSepet:
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", birim=birim,
                   miktar=miktar, birim_fiyat=fiyat)
        return sepet

    def _sat(self, sepet, *, cari_id=None, tahsilat=None, token=None):
        from database.hizli_satis_service import HizliSatisService

        return HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=cari_id or self.ortam.mus_id,
            tahsilatlar=tahsilat or [],
            idempotency_token=token or HizliSatisService.yeni_idempotency_token(),
            musteri_bakiye=0,
            risk_limiti=None,
        )

    def _hareket(self, fatura_no):
        from database.database import get_session
        from database.models.cari import SatisHareketi
        from sqlalchemy import select

        with get_session() as s:
            return s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fatura_no))


class BirimVeFiyatDbTest(_DbTabani):
    def test_birim_listesi_yalniz_kart_satis_birimleri(self):
        from database.hizli_satis_satir_service import satis_birim_secenekleri

        secenekler = {s["birim"]: s for s in satis_birim_secenekleri("U001")}
        self.assertEqual(set(secenekler), {"Adet", "Koli", "Bozuk"})
        self.assertTrue(secenekler["Koli"]["kullanilabilir"])
        self.assertEqual(secenekler["Koli"]["carpan"], Decimal("10"))
        self.assertFalse(secenekler["Bozuk"]["kullanilabilir"])
        self.assertIn("Katsayı", secenekler["Bozuk"]["sebep"])

    def test_birim_degisimi_bagimsiz_fiyati_ezmez(self):
        from database.hizli_satis_satir_service import birim_degisimi_hesapla

        sonuc = birim_degisimi_hesapla(stok_kodu="U001", eski_birim="Adet", yeni_birim="Koli",
                                       miktar=Decimal("20"), referans_fiyat=Decimal("10"),
                                       fiyat_adi="SATIŞ FİYATI 1")
        self.assertEqual(sonuc["miktar"], Decimal("2"))
        self.assertEqual(sonuc["birim_fiyat"], Decimal("95"))  # 10×10 değil
        self.assertEqual(sonuc["temel_miktar"], Decimal("20"))
        geri = birim_degisimi_hesapla(stok_kodu="U001", eski_birim="Koli", yeni_birim="Adet",
                                      miktar=Decimal("2"), referans_fiyat=Decimal("95"),
                                      fiyat_adi="SATIŞ FİYATI 1")
        self.assertEqual((geri["miktar"], geri["birim_fiyat"]), (Decimal("20"), Decimal("10")))
        # Kartta katsayısı olmayan fiyat türü → mevcut kural (temel × katsayı)
        sf2 = birim_degisimi_hesapla(stok_kodu="U001", eski_birim="Adet", yeni_birim="Koli",
                                     miktar=Decimal("10"), referans_fiyat=Decimal("12"),
                                     fiyat_adi="SATIŞ FİYATI 2")
        self.assertEqual(sf2["birim_fiyat"], Decimal("120"))
        for kotu in ("Paket", "Bozuk", "Eski", "Kutu"):
            with self.assertRaises(ValueError):
                birim_degisimi_hesapla(stok_kodu="U001", eski_birim="Adet", yeni_birim=kotu,
                                       miktar=1, referans_fiyat=10, fiyat_adi=None)

    def test_fiyat_secenekleri_birim_yetki_ve_gecersizler(self):
        from database.hizli_satis_satir_service import fiyat_secenekleri

        liste = {s["fiyat_adi"]: s for s in fiyat_secenekleri(
            "U001", "Koli", fiyat_degistirme_izni=True, maliyet_izni=True, aktif_liste="SATIŞ FİYATI 1")}
        self.assertEqual(liste["SATIŞ FİYATI 1"]["uygulanacak"], Decimal("95"))
        self.assertTrue(liste["SATIŞ FİYATI 1"]["aktif_liste"])
        self.assertEqual(liste["SATIŞ FİYATI 2"]["uygulanacak"], Decimal("120"))
        self.assertEqual(liste["SATIŞ FİYATI 2"]["birim"], "Adet")
        self.assertEqual(liste["SATIŞ FİYATI 2"]["kdv"], "KDV durumu belirtilmemiş")
        self.assertTrue(liste["SATIŞ FİYATI 2"]["kdv_onay_gerekli"])
        self.assertFalse(liste["SATIŞ FİYATI 3"]["kullanilabilir"])
        self.assertTrue(liste["ALIŞ FİYATI"]["kullanilabilir"])
        gizli = {s["fiyat_adi"]: s for s in fiyat_secenekleri(
            "U001", "Adet", fiyat_degistirme_izni=False, maliyet_izni=False)}
        self.assertIsNone(gizli["ALIŞ FİYATI"]["tutar"])
        self.assertTrue(all(not s["kullanilabilir"] for s in gizli.values()))
        self.assertIn("yetki", gizli["SATIŞ FİYATI 1"]["sebep"])
        self.assertEqual(fiyat_secenekleri("YOK", "Adet", fiyat_degistirme_izni=True, maliyet_izni=True), [])

    def test_doviz_fiyati_kur_yoksa_secilemez(self):
        from database.database import get_session
        from database.models.stok import StokFiyati
        from database.hizli_satis_satir_service import fiyat_secenekleri

        with get_session() as s:
            s.add(StokFiyati(stok_id=self.stok_id, fiyat_adi="SATIŞ FİYATI 4", tutar=Decimal("2"),
                             para_birimi="USD"))
            s.commit()
        with patch("database.doviz_service.DovizService.kur_degeri", return_value=Decimal("0")):
            sf4 = next(s for s in fiyat_secenekleri("U001", "Adet", fiyat_degistirme_izni=True,
                                                    maliyet_izni=True) if s["fiyat_adi"] == "SATIŞ FİYATI 4")
        self.assertFalse(sf4["kullanilabilir"])
        self.assertIn("Kur", sf4["sebep"])
        with patch("database.doviz_service.DovizService.kur_degeri", return_value=Decimal("40")):
            sf4 = next(s for s in fiyat_secenekleri("U001", "Adet", fiyat_degistirme_izni=True,
                                                    maliyet_izni=True) if s["fiyat_adi"] == "SATIŞ FİYATI 4")
        self.assertEqual(sf4["uygulanacak"], Decimal("80"))


class SatisVeCariDbTest(_DbTabani):
    def test_iki_koli_satis_yirmi_adet_dusurur_ve_birim_korunur(self):
        from database.satis_faturasi_service import SatisFaturasiService

        once = self.ortam.lot_toplam()
        sonuc = self._sat(self._sepet(birim="Koli", miktar="2", fiyat="95"))
        self.assertEqual(once - self.ortam.lot_toplam(), Decimal("20"))
        fatura = SatisFaturasiService.getir(sonuc["fatura_id"])
        satir = fatura.satirlar[0]
        self.assertEqual((satir.birim, Decimal(str(satir.miktar))), ("Koli", Decimal("2")))
        self.assertEqual(Decimal(str(satir.birim_carpani)), Decimal("10"))
        self.assertIsNone(satir.referans_birim_fiyat)

    def test_stok_kontrolu_katsayiyi_kullanir(self):
        from database.hizli_satis_service import HizliSatisService

        sepet = self._sepet(birim="Koli", miktar="101", fiyat="95")  # 1010 adet > 1000
        hatalar = HizliSatisService.stok_yeterlilik_kontrol(sepet.satirlar)
        self.assertTrue(hatalar and "istenen: 1010" in hatalar[0], hatalar)
        self.assertEqual(HizliSatisService.stok_yeterlilik_kontrol(self._sepet("Koli", "100").satirlar), [])

    def _sepet_900(self):
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", miktar=60, birim_fiyat="10")
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", birim="Koli",
                   miktar=4, birim_fiyat="100")
        sepet.hedef_toplam_uygula("900")
        self.assertEqual(sepet.referans_toplam(), Decimal("1000.00"))
        return sepet

    def test_900_satis_tahsilatsiz_tam_ve_kismi(self):
        for tahsilat, kalan in ((None, "900.00"), ("900", "0.00"), ("500", "400.00")):
            th = [{"odeme_sekli": "NAKİT / KASA", "tutar": tahsilat, "hesap": "ANA KASA"}] if tahsilat else None
            sonuc = self._sat(self._sepet_900(), tahsilat=th)
            self.assertEqual(sonuc["genel_toplam"], Decimal("900.00"))
            hareket = self._hareket(sonuc["fatura_no"])
            self.assertEqual(Decimal(str(hareket.satis_tutari)), Decimal("900.00"))
            self.assertEqual(Decimal(str(hareket.kalan_acik_tutar)).quantize(Decimal("0.01")), Decimal(kalan))

    def test_yeniden_acilista_referans_korunur_indirim_tekrar_uygulanmaz(self):
        from database.satis_faturasi_service import SatisFaturasiService

        sonuc = self._sat(self._sepet_900())
        fatura = SatisFaturasiService.getir(sonuc["fatura_id"])
        satirlar = sorted(fatura.satirlar, key=lambda s: s.id)
        self.assertEqual([Decimal(str(s.referans_birim_fiyat)) for s in satirlar], [Decimal("10"), Decimal("100")])
        self.assertEqual([Decimal(str(s.birim_fiyat)) for s in satirlar], [Decimal("9"), Decimal("90")])
        self.assertEqual(SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"], Decimal("900.00"))

    def test_cift_kayit_ayni_token_reddedilir(self):
        from database.database import get_session
        from database.hizli_satis_service import HizliSatisService
        from database.models.satis_faturasi import SatisFaturasi
        from sqlalchemy import func, select

        token = HizliSatisService.yeni_idempotency_token()
        self._sat(self._sepet_900(), token=token)
        with self.assertRaises(Exception):
            self._sat(self._sepet_900(), token=token)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SatisFaturasi.id))), 1)

    def test_basarisiz_kayit_kismi_iz_birakmaz(self):
        from database.database import get_session
        from database.models.cari import SatisHareketi
        from database.models.satis_faturasi import SatisFaturasi
        from sqlalchemy import func, select

        once = self.ortam.lot_toplam()
        with get_session() as s:
            hareket_once = s.scalar(select(func.count(SatisHareketi.id)))
        with patch("database.finans_service.FinansService.fatura_tahsilati", side_effect=ValueError("kasa yok")):
            with self.assertRaises(ValueError):
                self._sat(self._sepet_900(), tahsilat=[{"odeme_sekli": "NAKİT / KASA", "tutar": "100",
                                                       "hesap": "ANA KASA"}])
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SatisFaturasi.id))), 0)
            self.assertEqual(s.scalar(select(func.count(SatisHareketi.id))), hareket_once)
        self.assertEqual(self.ortam.lot_toplam(), once)

    def test_beklet_ve_geri_cagir_referansi_korur(self):
        from database.hizli_satis_service import HizliSatisService

        bek = HizliSatisService.save_hold(self._sepet_900(), cari_id=self.ortam.mus_id)
        veri = HizliSatisService.load_hold(bek["id"])
        self.assertEqual([s["referans_birim_fiyat"] for s in veri["satirlar"]], [Decimal("10"), Decimal("100")])
        yeni = HizliSatisSepet()
        for s in veri["satirlar"]:
            yeni.ekle(stok_id=s["stok_id"], stok_kodu=s["stok_kodu"], stok_adi=s["stok_adi"], birim=s["birim"],
                      miktar=s["miktar"], birim_fiyat=s["birim_fiyat"], birlestir=False,
                      referans_birim_fiyat=s["referans_birim_fiyat"], geri_yukleme=True)
        self.assertEqual(yeni.referans_toplam(), Decimal("1000.00"))
        self.assertEqual(yeni.toplamlar()["genel_toplam"], Decimal("900.00"))
        yeni.hedef_toplam_uygula("1000")
        self.assertEqual([s.birim_fiyat for s in yeni.satirlar], [Decimal("10"), Decimal("100")])

    def test_stok_hareketleri_musteri_ve_tumu(self):
        from database.hizli_satis_satir_service import stok_hareketleri

        a1 = self._sat(self._sepet(miktar="1"))
        b1 = self._sat(self._sepet(miktar="2"), cari_id=self.m2_id)
        a2 = self._sat(self._sepet(birim="Koli", miktar="1", fiyat="95"))
        sadece_a = stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id)
        belgeler = [r["belge_no"] for r in sadece_a["satirlar"]]
        self.assertEqual(belgeler, [a2["fatura_no"], a1["fatura_no"]])  # yeniden eskiye
        self.assertTrue(all(r["cari_id"] == self.ortam.mus_id for r in sadece_a["satirlar"]))
        ilk = sadece_a["satirlar"][0]
        self.assertEqual((ilk["miktar"], ilk["birim"], ilk["birim_fiyat"], ilk["tutar"]),
                         (Decimal("1"), "Koli", Decimal("95.0000"), Decimal("95.00")))
        self.assertEqual(ilk["yon"], "cikis")
        tumu = stok_hareketleri(self.stok_id, cari_id=None)
        tum_belgeler = [r["belge_no"] for r in tumu["satirlar"]]
        self.assertIn(b1["fatura_no"], tum_belgeler)
        self.assertEqual(len(tum_belgeler), 4)  # 3 satış + 1 alış
        self.assertEqual(stok_hareketleri(self.stok_id, cari_id=999999)["satirlar"], [])


class SemaGocuTest(unittest.TestCase):
    def test_eski_tablolara_kolon_eklenir_veri_korunur(self):
        import tempfile

        from sqlalchemy import create_engine, inspect, text

        from database import hizli_satis_service as mod
        from database.database import _aktif_engine_bagla, company_db, doviz_schema_guncelle

        with tempfile.TemporaryDirectory() as tmp:
            eng = create_engine(f"sqlite:///{Path(tmp, 'eski.db').as_posix()}")
            with eng.begin() as c:
                c.execute(text(
                    "CREATE TABLE satis_faturasi_satirlari (id INTEGER PRIMARY KEY, fatura_id INTEGER, "
                    "urun_kodu VARCHAR(50), birim_fiyat NUMERIC(18,4))"
                ))
                c.execute(text("INSERT INTO satis_faturasi_satirlari VALUES (1, 1, 'U001', 12.5)"))
                c.execute(text(
                    "CREATE TABLE hizli_satis_bekleyen_satirlari (id INTEGER PRIMARY KEY, bekleyen_id INTEGER, "
                    "birim_fiyat NUMERIC(18,4))"
                ))
            onceki_engine = company_db._engine
            _aktif_engine_bagla(eng)
            company_db._engine = eng
            try:
                doviz_schema_guncelle()
                mod._REFERANS_KOLON_HAZIR.clear()
                mod.HizliSatisService.schema_hazirla()
                insp = inspect(eng)
                self.assertIn("referans_birim_fiyat",
                              {k["name"] for k in insp.get_columns("satis_faturasi_satirlari")})
                self.assertIn("referans_birim_fiyat",
                              {k["name"] for k in insp.get_columns("hizli_satis_bekleyen_satirlari")})
                with eng.connect() as c:
                    satir = c.execute(text(
                        "SELECT birim_fiyat, referans_birim_fiyat FROM satis_faturasi_satirlari"
                    )).one()
                self.assertEqual((Decimal(str(satir[0])), satir[1]), (Decimal("12.5"), None))
            finally:
                company_db._engine = onceki_engine
                mod._REFERANS_KOLON_HAZIR.clear()
                eng.dispose()


class HizliSatisPencereGuiTest(_DbTabani):
    """Gerçek pencere: sağ tık / F10 / birim / fiyat / hareketler / Yeni Toplam."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Tk yok: {exc}")
        cls.root.geometry("1x1+0+0")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        super().setUp()
        self.mesajlar: list[tuple] = []
        self._yamalar = [
            patch(f"hizli_satis_ui.messagebox.{ad}", lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
            for ad in ("showerror", "showwarning", "showinfo")
        ]
        for p in self._yamalar:
            p.start()
        import hizli_satis_ui

        self.pencere = hizli_satis_ui.HizliSatisPencere(self.root)
        self._pompala(0.4)

    def tearDown(self):
        try:
            for w in list(self.pencere.winfo_children()):
                if isinstance(w, tk.Toplevel):
                    w.destroy()
            self.pencere.destroy()
        except tk.TclError:
            pass
        for p in reversed(self._yamalar):
            p.stop()
        super().tearDown()

    def _pompala(self, sure: float) -> None:
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            self.root.update()
            time.sleep(0.01)

    def _ust_pencereler(self):
        return [w for w in self.pencere.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists()]

    def _musteri_sec(self, cari_id):
        from hizli_satis_musteri import cari_ozet_coz

        self.assertTrue(self.pencere._musteri_uygula(cari_ozet_coz(cari_id), risk_kontrol=False))

    def _sepete(self, birim="Adet", miktar="1"):
        self.pencere._sepete_ekle_kayit({"stok_id": self.stok_id, "stok_kodu": "U001", "stok_adi": "Test Ürün",
                                         "birim": birim, "miktar": Decimal(miktar), "birim_fiyat": Decimal("10")})

    def test_bakiye_valor_musteri_alti_ve_degisim(self):
        self._sat(self._sepet(miktar="3"))  # M001: 30 TL borç
        self._musteri_sec(self.ortam.mus_id)
        self._pompala(1.5)
        self.assertEqual(self.pencere.bakiye_lbl.cget("text"), "Bakiye 30,00 TL Borç")
        self.assertTrue(self.pencere.valor_lbl.cget("text").startswith("Valör"))
        self._musteri_sec(self.m2_id)
        self._pompala(1.5)
        self.assertEqual(self.pencere.bakiye_lbl.cget("text"), "Bakiye 0,00 TL Kapalı")

    def test_sag_tik_ve_f10_hucre_hedefleme(self):
        self._musteri_sec(self.ortam.mus_id)
        self._sepete()
        self._sepete(birim="Koli")
        self._pompala(0.3)
        p = self.pencere
        p.focus_get = lambda: p.sepet  # test penceresi Windows'ta odak almayabilir
        p._sepet_satiri_sec(1)
        p._sepet_odak_ayarla("fiyat")
        p._f10_tusu()
        self._pompala(0.2)
        pencereler = self._ust_pencereler()
        self.assertEqual(len(pencereler), 1)
        self.assertIn("Fiyat Listesi", pencereler[0].title())
        pencereler[0].event_generate("<Escape>")
        self._pompala(0.2)
        self.assertEqual(self._ust_pencereler(), [])
        self.assertEqual(p.sepet.selection(), ("1",))
        p._sepet_odak_ayarla("ad")
        p._f10_tusu()
        self._pompala(0.3)
        pencereler = self._ust_pencereler()
        self.assertEqual(len(pencereler), 1)
        self.assertIn("Stok Hareketleri", pencereler[0].title())
        pencereler[0].event_generate("<Escape>")
        self._pompala(0.2)
        # Sağ tık: tıklanan satır + hücre
        p.update_idletasks()
        x, y, w, h = p.sepet.bbox("0", "fiyat")
        p.sepet.event_generate("<Button-3>", x=x + w // 2, y=y + h // 2)
        self._pompala(0.2)
        self.assertEqual(p.sepet.selection(), ("0",))
        self.assertEqual(p._sepet_odak_sutun, "fiyat")
        self.assertEqual(len(self._ust_pencereler()), 1)

    def test_fiyat_secimi_yalniz_satiri_degistirir_iptal_degistirmez(self):
        from database.stok_service import StokService

        self._musteri_sec(self.ortam.mus_id)
        self._sepete()
        self._sepete(birim="Koli")
        p = self.pencere
        once = [s.birim_fiyat for s in p.sepet_model.satirlar]
        p._fiyat_listesi_ac(1)
        self._pompala(0.2)
        dlg = self._ust_pencereler()[0]
        dlg.event_generate("<Escape>")
        self._pompala(0.2)
        self.assertEqual([s.birim_fiyat for s in p.sepet_model.satirlar], once)
        p._fiyat_listesi_ac(1)
        self._pompala(0.2)
        dlg = self._ust_pencereler()[0]
        tree = next(w for w in dlg.winfo_children() if isinstance(w, tk.ttk.Treeview))
        sf2 = next(i for i in tree.get_children() if tree.item(i, "values")[0] == "SATIŞ FİYATI 2")
        tree.selection_set(sf2)
        # KDV durumu kayıtsız → sorulur; İptal fiyatı uygulamaz
        with patch("hizli_satis_ui.messagebox.askyesnocancel", return_value=None) as soru:
            tree.event_generate("<Return>")
            self._pompala(0.2)
        self.assertEqual(soru.call_count, 1)
        self.assertEqual([s.birim_fiyat for s in p.sepet_model.satirlar], once)
        dlg = self._ust_pencereler()[0]
        tree = next(w for w in dlg.winfo_children() if isinstance(w, tk.ttk.Treeview))
        sf2 = next(i for i in tree.get_children() if tree.item(i, "values")[0] == "SATIŞ FİYATI 2")
        tree.selection_set(sf2)
        with patch("hizli_satis_ui.messagebox.askyesnocancel", return_value=True):  # Evet = KDV hariç
            tree.event_generate("<Return>")
            self._pompala(0.2)
        self.assertEqual(p.sepet_model.satirlar[1].birim_fiyat, Decimal("120.0000"))
        self.assertEqual(p.sepet_model.satirlar[0].birim_fiyat, once[0])
        self.assertEqual(StokService.satis_fiyati_adi_ile("U001", "SATIŞ FİYATI 2"), Decimal("12"))

    def test_birim_hucresi_secimi_ve_yeni_toplam(self):
        self._musteri_sec(self.ortam.mus_id)
        self._sepete(miktar="20")
        p = self.pencere
        p._birim_sec(0)
        self._pompala(0.2)
        dlg = self._ust_pencereler()[0]
        liste = next(w for w in dlg.winfo_children() if isinstance(w, tk.Listbox))
        degerler = list(liste.get(0, "end"))
        self.assertEqual(len(degerler), 3)  # Adet, Koli, Bozuk (gri)
        bozuk = next(i for i, m in enumerate(degerler) if m.startswith("Bozuk"))
        liste.selection_clear(0, "end")
        liste.selection_set(bozuk)
        liste.event_generate("<Return>")
        self._pompala(0.1)
        self.assertEqual(p.sepet_model.satirlar[0].birim, "Adet")
        koli = next(i for i, m in enumerate(degerler) if m.startswith("Koli"))
        liste.selection_clear(0, "end")
        liste.selection_set(koli)
        liste.event_generate("<Return>")
        self._pompala(0.2)
        satir = p.sepet_model.satirlar[0]
        self.assertEqual((satir.birim, satir.miktar, satir.birim_fiyat), ("Koli", Decimal("2"), Decimal("95")))
        self.assertIn("20 Adet stoktan düşer", p.durum_lbl.cget("text"))
        # Yeni Toplam: Genel Toplam sabit, satır fiyatı otomatik
        p.hedef_toplam_entry.focus_set()
        p._hedef_toplam_odak()
        p.hedef_toplam_var.set("171")
        self._pompala(1.0)
        self.assertEqual(p.sepet_model.toplamlar()["genel_toplam"], Decimal("171.00"))
        self.assertIn("190,00", p.toplam_lbl.cget("text"))
        p.hedef_toplam_var.set("-5")
        self._pompala(1.0)
        self.assertEqual(p.sepet_model.toplamlar()["genel_toplam"], Decimal("171.00"))
        p.hedef_toplam_var.set("")
        self._pompala(1.0)
        self.assertEqual(p.sepet_model.toplamlar()["genel_toplam"], Decimal("171.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
