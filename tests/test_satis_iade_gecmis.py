"""Satış iade: geçmiş satış bilgisi, önceki iade nedeniyle kalan miktar, kaynak bağlama doğrulaması,
satış yokken devam kararı; satış faturası TASLAK → onay → AÇIK akışı, ödeme durumu ve fatura menüsü sırası.

Yalnız geçici test veritabanı kullanır (FaturaStokEntegrasyonTest kurulumu).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.database import get_session
from database.models.cari import Cari
from database.models.satis_faturasi import SatisFaturasi
from database.models.satis_iade_faturasi import SatisIadeFaturasiSatiri
from database.satis_faturasi_service import SatisFaturasiService, evrak_durumu, odeme_durumu
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from tests.test_fatura_miktar_birim import FaturaStokEntegrasyonTest

D = Decimal


def _satir(miktar, birim="Adet", fiyat="10", iskonto="0"):
    return {"urun_kodu": "MB001", "urun_adi": "Birim Ürün", "miktar": D(miktar), "birim": birim,
            "birim_fiyat": D(fiyat), "iskonto_orani": D(iskonto), "kdv_orani": D("20")}


class IadeTemel(unittest.TestCase):
    def setUp(self):
        FaturaStokEntegrasyonTest.setUp(self)
        with get_session() as s:
            diger = Cari(cari_kodu="M002", unvan="Başka Müşteri", cari_turu="Müşteri", aktif=True)
            s.add(diger)
            s.flush()
            self.diger_id = diger.id

    def tearDown(self):
        FaturaStokEntegrasyonTest.tearDown(self)

    def _fatura(self, tarih, satirlar, *, cari_id=None, onayla=True):
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": cari_id or self.cari_id,
             "depo": "ANA DEPO", "odeme_tutari": D("0"), "sales_person_id": 1},
            satirlar,
        )
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def _iade(self, satirlar, **ek):
        veriler = {"iade_tarihi": date(2026, 6, 1), "cari_id": self.cari_id, "kaynak_fatura_id": None,
                   "depo": "ANA DEPO", "aciklama": None, "iade_odeme_tutari": 0}
        veriler.update(ek)
        return SatisIadeFaturasiService.kaydet(veriler, satirlar)


class DurumAkisiTest(IadeTemel):
    def test_taslak_onay_acik_ve_odeme_durumu_ayri(self):
        f = self._fatura(date(2026, 3, 1), [_satir("5")], onayla=False)
        self.assertEqual(f.durum, "TASLAK")
        SatisFaturasiService.onayla(f.id)
        f = SatisFaturasiService.getir(f.id)
        self.assertEqual((f.durum, f.onaylandi), ("AÇIK", True))
        ozet = next(o for o in SatisFaturasiService.listele_ozet() if o["id"] == f.id)
        self.assertEqual(ozet["odeme_durumu"], "Ödenmedi")
        self.assertEqual(ozet["evrak_durumu"], "AÇIK")
        self.assertEqual(ozet["acik_tutar"], D("60.00"))

    def test_basarisiz_onay_taslak_kalir(self):
        f = self._fatura(date(2026, 3, 1), [_satir("3", "Koli")], onayla=False)
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(f.id)
        self.assertEqual(SatisFaturasiService.getir(f.id).durum, "TASLAK")

    def test_evrak_ve_odeme_durumu_yardimcilari(self):
        self.assertEqual(evrak_durumu("KAPALI"), "AÇIK")
        self.assertEqual(evrak_durumu("TASLAK"), "TASLAK")
        self.assertEqual(odeme_durumu(D("100"), D("0")), "Ödenmedi")
        self.assertEqual(odeme_durumu(D("100"), D("40")), "Kısmen Ödendi")
        self.assertEqual(odeme_durumu(D("100"), D("100")), "Kapandı")

    def test_fatura_menusu_sirasi(self):
        import app

        self.assertEqual(
            [m[0] for m in app.SATIS_FATURA_MENU_SIRASI],
            ["HIZLI FATURA", "SATIŞ FATURA LİSTESİ", "SATIŞ İADE FATURALARI", "FATURA GÖRSELİ İÇE AKTAR"],
        )
        for baslik in ("Tarih", "Evrak No", "Cari Ünvanı", "Evrak Durumu", "Toplam", "Kapanan", "Kalan", "Ödeme Durumu"):
            self.assertIn(baslik, app.SATIS_FATURA_LISTE_BASLIKLARI)


class GecmisSatisTest(IadeTemel):
    def test_tek_ve_coklu_gecmis_yeniden_eskiye_yalniz_bu_musteri(self):
        eski = self._fatura(date(2026, 2, 1), [_satir("5", fiyat="10", iskonto="10")])
        yeni = self._fatura(date(2026, 4, 1), [_satir("2", "Paket", fiyat="900")])
        self._fatura(date(2026, 4, 5), [_satir("1")], cari_id=self.diger_id)
        self._fatura(date(2026, 4, 6), [_satir("1")], onayla=False)
        ozet = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")
        self.assertEqual([g["fatura_no"] for g in ozet["gecmis"]], [yeni.fatura_no, eski.fatura_no])
        g = ozet["gecmis"][1]
        self.assertEqual((g["miktar"], g["birim"]), (D("5.0000"), "Adet"))
        self.assertEqual(g["net_fiyat"].quantize(D("0.01")), D("9.00"))
        self.assertEqual(g["net_satir_tutari"], D("45.00"))
        self.assertEqual(g["satir_kdv_dahil"], D("54.00"))
        self.assertEqual(ozet["gecmis"][0]["satilan_temel"], D("200"))
        self.assertEqual(SatisIadeFaturasiService.musteri_urun_gecmisi(self.diger_id, "MB001")["adet"], 1)

    def test_onceki_iade_kalan_ve_tamamen_iade_gizlenmez(self):
        f = self._fatura(date(2026, 2, 1), [_satir("5")])
        satir_id = f.satirlar[0].id
        iade = self._iade([dict(_satir("2"), kaynak_fatura_satiri_id=satir_id)])
        g = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["gecmis"][0]
        self.assertEqual((g["iade_edilen_temel"], g["kalan_iade_miktar"], g["tamamen_iade"]),
                         (D("2"), D("3.0000"), False))
        self.assertEqual(g["onceki_iadeler"][0]["iade_no"], iade.iade_no)
        haric = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001", haric_iade_id=iade.id)
        self.assertEqual(haric["gecmis"][0]["kalan_iade_miktar"], D("5.0000"))
        self._iade([dict(_satir("3"), kaynak_fatura_satiri_id=satir_id)])
        g = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["gecmis"][0]
        self.assertTrue(g["tamamen_iade"])

    def test_miktar_asimi_ve_birim_farki_uyarisi(self):
        f = self._fatura(date(2026, 2, 1), [_satir("150")])
        satir_id = f.satirlar[0].id
        uyarilar = SatisIadeFaturasiService.iade_satiri_uyarilari(
            self.cari_id, dict(_satir("2", "Paket"), kaynak_fatura_satiri_id=satir_id)
        )
        self.assertEqual(len(uyarilar), 2)
        self.assertTrue(any("Birim farkı" in u for u in uyarilar))
        self.assertTrue(any("Miktar aşımı" in u for u in uyarilar))
        diger = [dict(_satir("100"), kaynak_fatura_satiri_id=satir_id)]
        uyarilar = SatisIadeFaturasiService.iade_satiri_uyarilari(
            self.cari_id, dict(_satir("60"), kaynak_fatura_satiri_id=satir_id), diger_satirlar=diger
        )
        self.assertTrue(any("Miktar aşımı" in u for u in uyarilar))

    def test_baska_musterinin_satisina_baglanamaz(self):
        f = self._fatura(date(2026, 2, 1), [_satir("5")], cari_id=self.diger_id)
        satir = dict(_satir("1"), kaynak_fatura_satiri_id=f.satirlar[0].id)
        self.assertTrue(SatisIadeFaturasiService.iade_satiri_uyarilari(self.cari_id, satir))
        with self.assertRaises(ValueError) as ctx:
            self._iade([satir])
        self.assertIn("kaynak satış satırı", str(ctx.exception))

    def test_satis_yokken_devam_karari_kaydedilir(self):
        self.assertFalse(SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["aldi"])
        zaman = datetime(2026, 6, 1, 10, 30)
        iade = self._iade([dict(_satir("1"), kaynak_yok_onay=True, kaynak_yok_gerekce="Devir öncesi satış",
                                kaynak_yok_kullanici="admin", kaynak_yok_tarih=zaman)])
        with get_session() as s:
            satir = s.scalar(select(SatisIadeFaturasiSatiri).where(SatisIadeFaturasiSatiri.iade_id == iade.id))
            self.assertEqual(
                (satir.kaynak_fatura_satiri_id, satir.kaynak_yok_onay, satir.kaynak_yok_gerekce,
                 satir.kaynak_yok_kullanici, satir.kaynak_yok_tarih),
                (None, True, "Devir öncesi satış", "admin", zaman),
            )

    def test_iptal_edilen_satis_gecmisten_duser(self):
        f = self._fatura(date(2026, 2, 1), [_satir("5")])
        SatisFaturasiService.iptal_et(f.id, "test")
        self.assertFalse(SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["aldi"])

    def test_cari_iade_listesi_filtresi(self):
        self._iade([dict(_satir("1"), kaynak_yok_onay=True)])
        self.assertEqual(len(SatisIadeFaturasiService.listele(cari_id=self.cari_id)), 1)
        self.assertEqual(SatisIadeFaturasiService.listele(cari_id=self.diger_id), [])


class IadeEkranTest(IadeTemel):
    def setUp(self):
        super().setUp()
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        super().tearDown()

    def _dialog(self, **ek):
        import app

        return app.SatisIadeFaturasiDialog(self.root, cari=self.cari_id, **ek)

    def test_cari_karttan_liste_ve_sabit_musteri(self):
        import app

        self._iade([dict(_satir("1"), kaynak_yok_onay=True)])
        liste = app.CariSatisIadeListesiDialog(self.root, self.cari_id)
        self.assertEqual(len(liste.tablo.get_children()), 1)
        liste.destroy()
        d = self._dialog()
        self.assertEqual(str(d.musteri.cget("state")), "disabled")
        self.assertEqual(d._secili_musteri().id, self.cari_id)
        d.destroy()

    def test_gecmis_panel_bagla_fiyat_sessiz_degismez(self):
        from unittest.mock import patch

        f = self._fatura(date(2026, 2, 1), [_satir("5", fiyat="10")])
        d = self._dialog()
        for alan, deger in (("urun_kodu", "MB001"), ("urun_adi", "Birim Ürün"), ("birim_fiyat", "7")):
            d.satir_girdileri[alan].delete(0, "end")
            d.satir_girdileri[alan].insert(0, deger)
        d.urun_gecmisini_goster()
        self.assertEqual(len(d.gecmis_tablo.get_children()), 1)
        self.assertEqual(d.satir_girdileri["birim_fiyat"].get(), "7")
        self.assertIsNone(d._secili_gecmis)
        d.gecmis_tablo.selection_set(("0",))
        d.gecmis_satira_bagla()
        self.assertEqual(d._secili_gecmis["satir_id"], f.satirlar[0].id)
        with patch("app.messagebox.askyesno", return_value=True):
            d.satir_ekle()
        self.assertEqual(d.satirlar[0]["kaynak_fatura_satiri_id"], f.satirlar[0].id)
        self.assertEqual(D(str(d.satirlar[0]["birim_fiyat"])), D("7"))
        d.destroy()

    def test_satis_yokken_vazgec_ve_devam(self):
        from unittest.mock import patch

        d = self._dialog()
        for alan, deger in (("urun_kodu", "MB001"), ("urun_adi", "Birim Ürün"), ("birim_fiyat", "5")):
            d.satir_girdileri[alan].delete(0, "end")
            d.satir_girdileri[alan].insert(0, deger)
        with patch.object(d, "_kaynak_yok_karari", return_value=None):
            d.satir_ekle()
        self.assertEqual(d.satirlar, [])
        karar = {"kaynak_yok_onay": True, "kaynak_yok_gerekce": "Devir", "kaynak_yok_kullanici": "admin",
                 "kaynak_yok_tarih": datetime(2026, 6, 1)}
        for alan, deger in (("urun_kodu", "MB001"), ("urun_adi", "Birim Ürün"), ("birim_fiyat", "5")):
            d.satir_girdileri[alan].delete(0, "end")
            d.satir_girdileri[alan].insert(0, deger)
        with patch.object(d, "_kaynak_yok_karari", return_value=karar):
            d.satir_ekle()
        self.assertTrue(d.satirlar[0]["kaynak_yok_onay"])
        self.assertIsNone(d.satirlar[0]["kaynak_fatura_satiri_id"])
        self.assertIn("KAYNAKSIZ", d.satir_tablosu.item("0", "values")[7])
        d.destroy()


if __name__ == "__main__":
    unittest.main()
