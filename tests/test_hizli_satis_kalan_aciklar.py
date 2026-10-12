"""Hızlı Satış açık kapatma raporunun kalan açıkları (07.10.2026):
stok kartında fiyat KDV anlamı, normal fatura fiyat seçicisinde KDV anlamı,
döviz başlıklı faturada dağıtım sonrası satır döviz fiyatı.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_hizli_satis_kalan_aciklar.py -q
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_hizli_satis_talimat_satir import _DbTabani  # noqa: E402


def _durumlar(stok_id):
    from database.database import get_session
    from database.models.stok import StokFiyati
    from sqlalchemy import select

    with get_session() as s:
        return {
            f.fiyat_adi: (f.kdv_durumu, Decimal(str(f.tutar)))
            for f in s.scalars(select(StokFiyati).where(StokFiyati.stok_id == stok_id))
        }


class StokKartiKdvSeciciTest(_DbTabani):
    def _kaydet(self, **kw):
        from database.stok_service import StokService

        StokService.stok_kaydi(
            {"stok_id": self.stok_id, "stok_kodu": "U001", "stok_adi": "Test Ürün", "birim": "Adet"},
            [("SATIŞ FİYATI 1", "10"), ("SATIŞ FİYATI 2", "12"), ("ALIŞ FİYATI", "5")],
            **kw,
        )

    def test_kdv_durumu_kaydedilir_ve_korunur(self):
        self._kaydet(kdv_durumlari={"SATIŞ FİYATI 1": "DAHIL", "SATIŞ FİYATI 2": "HARIC"})
        d = _durumlar(self.stok_id)
        self.assertEqual(d["SATIŞ FİYATI 1"], ("DAHIL", Decimal("10")))
        self.assertEqual(d["SATIŞ FİYATI 2"], ("HARIC", Decimal("12")))
        # KDV seçimi verilmeyen kayıt (eski çağıranlar) mevcut anlamı korur
        self._kaydet()
        d = _durumlar(self.stok_id)
        self.assertEqual(d["SATIŞ FİYATI 1"][0], "DAHIL")
        self.assertEqual(d["SATIŞ FİYATI 2"][0], "HARIC")
        # Belirtilmemiş seçimi anlamı kaldırır
        self._kaydet(kdv_durumlari={"SATIŞ FİYATI 1": None})
        self.assertIsNone(_durumlar(self.stok_id)["SATIŞ FİYATI 1"][0])

    def test_gecersiz_kdv_durumu_reddedilir(self):
        with self.assertRaises(ValueError):
            self._kaydet(kdv_durumlari={"SATIŞ FİYATI 1": "BELKİ"})
        self.assertIsNone(_durumlar(self.stok_id)["SATIŞ FİYATI 1"][0])

    def test_eski_fiyat_belirtilmemis_kalir(self):
        d = _durumlar(self.stok_id)
        self.assertIsNone(d["SATIŞ FİYATI 1"][0])
        self.assertIsNone(d["SATIŞ FİYATI 2"][0])

    def test_ekran_metin_kod_donusumu(self):
        from stok_ui import FIYAT_KDV_SECENEKLERI, fiyat_kdv_kodu, fiyat_kdv_metni

        self.assertEqual(fiyat_kdv_kodu("KDV Dahil"), "DAHIL")
        self.assertEqual(fiyat_kdv_kodu("KDV Hariç"), "HARIC")
        self.assertIsNone(fiyat_kdv_kodu(FIYAT_KDV_SECENEKLERI[0]))
        for kod in ("HARIC", "DAHIL", None):
            self.assertEqual(fiyat_kdv_kodu(fiyat_kdv_metni(kod)), kod)


from tests.test_stok_karti_birim_arama import _EkranTemel  # noqa: E402


class StokKartiKdvEkranTest(_EkranTemel):
    def test_kart_ekraninda_kdv_secilir_kaydedilir_yeniden_yuklenir(self):
        from database.stok_service import StokService

        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        self.assertEqual(dlg.fiyat_kdv_alanlari["SATIŞ FİYATI 1"].get(), "KDV belirtilmemiş")
        dlg.fiyat_alanlari["SATIŞ FİYATI 1"].insert(0, "120")
        dlg.fiyat_alanlari["SATIŞ FİYATI 2"].insert(0, "100")
        dlg.fiyat_kdv_alanlari["SATIŞ FİYATI 1"].set("KDV Dahil")
        dlg.fiyat_kdv_alanlari["SATIŞ FİYATI 2"].set("KDV Hariç")
        self.assertTrue(dlg.kaydet())
        d = _durumlar(self.stok_id)
        self.assertEqual(d["SATIŞ FİYATI 1"], ("DAHIL", Decimal("120")))
        self.assertEqual(d["SATIŞ FİYATI 2"], ("HARIC", Decimal("100")))
        self.assertIsNone(d.get("SATIŞ FİYATI 3", (None,))[0])
        dlg.destroy()

        yeni = self._yeni(stok=StokService.stok_getir(self.stok_id))
        self.assertEqual(yeni.fiyat_kdv_alanlari["SATIŞ FİYATI 1"].get(), "KDV Dahil")
        self.assertEqual(yeni.fiyat_kdv_alanlari["SATIŞ FİYATI 2"].get(), "KDV Hariç")
        # KDV seçimi değişikliği kaydedilmemiş değişiklik sayılır
        ilk = yeni._durum_ozeti()
        yeni.fiyat_kdv_alanlari["SATIŞ FİYATI 2"].set("KDV Dahil")
        self.assertNotEqual(ilk, yeni._durum_ozeti())
        yeni.destroy()


class FaturaFiyatSeciciKdvTest(unittest.TestCase):
    def _hesapla(self, durum, oran, cevap=None):
        from app import PriceSelectionDialog

        sahte = SimpleNamespace(_kdv_orani=oran)
        fiyat = SimpleNamespace(fiyat_adi="SATIŞ FİYATI 1", kdv_durumu=durum)
        self.sorular = []
        self.hatalar = []
        with patch("app.messagebox.askyesnocancel",
                   lambda *a, **k: self.sorular.append(a) or cevap), \
                patch("app.messagebox.showerror", lambda *a, **k: self.hatalar.append(a)):
            return PriceSelectionDialog._kdv_haric_tutar(sahte, fiyat, Decimal("120"))

    def test_haric_fiyat_oldugu_gibi(self):
        self.assertEqual(self._hesapla("HARIC", "20"), Decimal("120"))
        self.assertEqual(self.sorular, [])

    def test_dahil_fiyat_satir_kdv_ile_ayristirilir(self):
        self.assertEqual(self._hesapla("DAHIL", "20"), Decimal("100.0000"))
        self.assertEqual(self._hesapla("DAHIL", lambda: "%10"), Decimal("109.0909"))
        self.assertEqual(self._hesapla("DAHIL", "0"), Decimal("120.0000"))

    def test_dahil_fiyat_kdv_orani_yoksa_uygulanmaz(self):
        self.assertIsNone(self._hesapla("DAHIL", ""))
        self.assertEqual(len(self.hatalar), 1)
        self.assertIsNone(self._hesapla("DAHIL", None))

    def test_belirtilmemis_fiyat_sorulur(self):
        self.assertEqual(self._hesapla(None, "20", cevap=True), Decimal("120"))
        self.assertEqual(len(self.sorular), 1)
        self.assertEqual(self._hesapla(None, "20", cevap=False), Decimal("100.0000"))
        self.assertIsNone(self._hesapla(None, "20", cevap=None))


class FaturaFiyatSeciciEkranTest(_DbTabani):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Tk yok: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def _sec(self, fiyat_adi, **kw):
        from app import PriceSelectionDialog

        secilen = []
        with patch.object(PriceSelectionDialog, "grab_set", lambda self: None):
            d = PriceSelectionDialog(self.root, "U001", on_select=secilen.append, fiyat_turu="satis", **kw)
        try:
            iid = next(i for i in d.tablo.get_children() if d.tablo.item(i, "values")[0] == fiyat_adi)
            kdv_metni = d.tablo.item(iid, "values")[3]
            d.tablo.selection_set(iid)
            d.sec()
        finally:
            if d.winfo_exists():
                d.destroy()
        return kdv_metni, (secilen[0].tutar if secilen else None)

    def test_dahil_fiyat_net_aktarilir_kolon_gorunur(self):
        from database.stok_service import StokService

        StokService.stok_kaydi(
            {"stok_id": self.stok_id, "stok_kodu": "U001", "stok_adi": "Test Ürün", "birim": "Adet"},
            [("SATIŞ FİYATI 1", "120"), ("SATIŞ FİYATI 2", "12")],
            kdv_durumlari={"SATIŞ FİYATI 1": "DAHIL", "SATIŞ FİYATI 2": "HARIC"},
        )
        metin, tutar = self._sec("SATIŞ FİYATI 1", kdv_orani="20")
        self.assertEqual((metin, tutar), ("KDV dahil", Decimal("100.0000")))
        metin, tutar = self._sec("SATIŞ FİYATI 2", kdv_orani="20")
        self.assertEqual((metin, Decimal(str(tutar))), ("KDV hariç", Decimal("12")))

    def test_kdv_orani_verilmeyen_cagiran_eski_davranis(self):
        from database.stok_service import StokService

        StokService.stok_kaydi(
            {"stok_id": self.stok_id, "stok_kodu": "U001", "stok_adi": "Test Ürün", "birim": "Adet"},
            [("SATIŞ FİYATI 1", "120")],
            kdv_durumlari={"SATIŞ FİYATI 1": "DAHIL"},
        )
        _metin, tutar = self._sec("SATIŞ FİYATI 1")
        self.assertEqual(Decimal(str(tutar)), Decimal("120"))


class DovizDagitimSatirFiyatiTest(unittest.TestCase):
    def _sahte(self, satirlar):
        from app import SatisFaturasiDialog

        sahte = SimpleNamespace(satirlar=satirlar)
        sahte._doviz_fiyatlarini_esitle = lambda: SatisFaturasiDialog._doviz_fiyatlarini_esitle(sahte)
        return sahte

    def test_dagitim_sonrasi_doviz_fiyati_tl_den_turetilir(self):
        from app import SatisFaturasiDialog

        satirlar = [
            {"satir_para_birimi": "USD", "kur": "40", "birim_satis_fiyati": Decimal("360"),
             "birim_fiyat_doviz": Decimal("10")},
            {"satir_para_birimi": "TRY", "kur": "1", "birim_satis_fiyati": Decimal("50"),
             "birim_fiyat_doviz": 0},
        ]
        SatisFaturasiDialog._doviz_fiyatlarini_esitle(self._sahte(satirlar))
        self.assertEqual(satirlar[0]["birim_fiyat_doviz"], Decimal("9.0000"))
        self.assertEqual(satirlar[1]["birim_fiyat_doviz"], 0)

    def test_referansa_donuste_doviz_fiyati_geri_gelir(self):
        from app import SatisFaturasiDialog

        satirlar = [
            {"satir_para_birimi": "EUR", "kur": "45", "birim_satis_fiyati": Decimal("405"),
             "birim_fiyat_doviz": Decimal("9"), "referans_birim_fiyat": Decimal("450")},
        ]
        sahte = self._sahte(satirlar)
        self.assertTrue(SatisFaturasiDialog._referans_fiyatlarina_don(sahte))
        self.assertEqual(satirlar[0]["birim_satis_fiyati"], Decimal("450"))
        self.assertEqual(satirlar[0]["birim_fiyat_doviz"], Decimal("10.0000"))

    def test_kursuz_satir_dokunulmaz(self):
        from app import SatisFaturasiDialog

        satirlar = [{"satir_para_birimi": "USD", "kur": "0", "birim_satis_fiyati": Decimal("100"),
                     "birim_fiyat_doviz": Decimal("3")}]
        SatisFaturasiDialog._doviz_fiyatlarini_esitle(self._sahte(satirlar))
        self.assertEqual(satirlar[0]["birim_fiyat_doviz"], Decimal("3"))


from tests.test_hizli_satis_acik_kapatma import _FaturaEkraniTabani  # noqa: E402


class DovizDagitimEkranTest(_FaturaEkraniTabani):
    def test_dovizli_satirlarda_dagitim_aninda_doviz_fiyati_guncellenir(self):
        from database.satis_faturasi_service import SatisFaturasiService

        sonuc = self._sat(self._sepet_1000(None))
        SatisFaturasiService.onay_kaldir(sonuc["fatura_id"])
        d = self._ac(sonuc["fatura_id"])
        for v in d.satirlar:
            v.update(satir_para_birimi="USD", para_birimi="USD", kur="40",
                     birim_fiyat_doviz=(Decimal(str(v["birim_satis_fiyati"])) / 40).quantize(Decimal("0.0001")))
        once = [v["birim_fiyat_doviz"] for v in d.satirlar]
        d._uzlasilan_tutar = Decimal("900")
        d._uzlasilan_fiyatlara_dagit()
        for v in d.satirlar:
            self.assertEqual(
                v["birim_fiyat_doviz"],
                (Decimal(str(v["birim_satis_fiyati"])) / 40).quantize(Decimal("0.0001")),
            )
        self.assertNotEqual(once, [v["birim_fiyat_doviz"] for v in d.satirlar])
        d._referans_fiyatlarina_don()
        self.assertEqual(once, [v["birim_fiyat_doviz"] for v in d.satirlar])


if __name__ == "__main__":
    unittest.main()
