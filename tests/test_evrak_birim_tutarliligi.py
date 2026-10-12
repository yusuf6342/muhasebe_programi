"""Evraklarda birim tutarlılığı: iade kaynak satışın katsayısıyla girer, siparişe bağlı fatura satırının
birimi değiştirilemez, kartta tanımsız barkod birimi 1 sayılmaz.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_evrak_birim_tutarliligi.py -q
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.database import get_session
from database.models.satis_iade_faturasi import SatisIadeFaturasiSatiri
from database.models.stok import StokBarkod, StokBirim, StokHareketi, StokKarti
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from database.stok_service import StokService
from tests.test_satis_iade_gecmis import IadeTemel, _satir

D = Decimal


def _paket_carpani(yeni: str) -> None:
    with get_session() as s:
        for b in s.scalars(select(StokBirim).where(StokBirim.birim_adi == "Paket")):
            b.carpan = D(yeni)


class IadeKaynakKatsayisiTest(IadeTemel):
    def test_kart_katsayisi_sonradan_degisse_de_iade_satis_katsayisiyla_girer(self):
        f = self._fatura(date(2026, 2, 1), [_satir("1", "Paket", fiyat="90")])
        satir_id = f.satirlar[0].id
        _paket_carpani("50")

        g = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["gecmis"][0]
        self.assertEqual(g["satilan_temel"], D("100"))
        self.assertEqual(
            SatisIadeFaturasiService.iade_satiri_uyarilari(
                self.cari_id, dict(_satir("1", "Paket"), kaynak_fatura_satiri_id=satir_id)
            ),
            [],
        )

        iade = self._iade([dict(_satir("1", "Paket", fiyat="90"), kaynak_fatura_satiri_id=satir_id)])
        with get_session() as s:
            satir = s.scalar(select(SatisIadeFaturasiSatiri).where(SatisIadeFaturasiSatiri.iade_id == iade.id))
            self.assertEqual(D(str(satir.birim_carpani)), D("100"))
            giris = s.scalar(select(StokHareketi).where(StokHareketi.belge_no == iade.iade_no))
            self.assertEqual(D(str(giris.miktar)), D("100"))
        g = SatisIadeFaturasiService.musteri_urun_gecmisi(self.cari_id, "MB001")["gecmis"][0]
        self.assertTrue(g["tamamen_iade"])

    def test_farkli_birimle_iade_kart_katsayisini_kullanir(self):
        f = self._fatura(date(2026, 2, 1), [_satir("2", "Paket", fiyat="90")])
        iade = self._iade([dict(_satir("50"), kaynak_fatura_satiri_id=f.satirlar[0].id)])
        with get_session() as s:
            satir = s.scalar(select(SatisIadeFaturasiSatiri).where(SatisIadeFaturasiSatiri.iade_id == iade.id))
            self.assertEqual(D(str(satir.birim_carpani)), D("1"))


class BagliFaturaSatiriBirimTest(IadeTemel):
    def _siparis_satiri(self, birim="Paket"):
        from database.satis_siparisi_service import SatisSiparisiService

        sp = SatisSiparisiService.kaydet(
            {"siparis_tarihi": date(2026, 2, 1), "termin_tarihi": date(2026, 2, 10), "cari_id": self.cari_id,
             "onayla": True},
            [{"urun_kodu": "MB001", "urun_adi": "Birim Ürün", "miktar": D("3"), "birim": birim,
              "birim_satis_fiyati": D("90"), "kdv_orani": D("20")}],
            [],
        )
        return SatisSiparisiService.getir(sp.id).satirlar[0]

    def test_siparise_bagli_satir_farkli_birimle_kaydedilmez(self):
        ss = self._siparis_satiri()
        with self.assertRaises(ValueError) as ctx:
            self._fatura(date(2026, 2, 2), [dict(_satir("300"), siparis_satiri_id=ss.id)], onayla=False)
        self.assertIn("sipariş birimiyle aynı", str(ctx.exception))
        f = self._fatura(date(2026, 2, 2), [dict(_satir("2", "paket"), siparis_satiri_id=ss.id)], onayla=False)
        self.assertEqual(f.satirlar[0].siparis_satiri_id, ss.id)

    def test_bagli_satirda_birim_hucresi_duzenlenemez(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        import fatura_satir_hucre_edit as he

        dialog = SimpleNamespace(
            satirlar=[{"urun_kodu": "MB001", "birim": "Paket", "siparis_satiri_id": 7},
                      {"urun_kodu": "MB001", "birim": "Paket"}],
            satir_tablosu=None,
        )
        with patch.object(he, "_kolon_gorunur_mu", return_value=True):
            self.assertFalse(he.kolon_duzenlenebilir_mi(dialog, 0, "birim"))
            self.assertTrue(he.kolon_duzenlenebilir_mi(dialog, 1, "birim"))
        with patch.object(he, "messagebox") as mb:
            he.birim_hucre_duzenle(dialog, idx=0)
        self.assertIn("siparişten aktarıldı", mb.showwarning.call_args.args[1])


class BarkodTanimsizBirimTest(IadeTemel):
    def test_tanimsiz_birim_barkodu_bir_sayilmaz(self):
        from database.barkod_okut_service import barkod_ile_ara

        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "MB001"))
            s.add(StokBarkod(stok_id=stok.id, barkod="8690000000005", birim="Kasa"))
            s.add(StokBarkod(stok_id=stok.id, barkod="8690000000012", birim="Paket"))
        bulunan = StokService.barkod_ile_bul("8690000000005")
        self.assertIsNone(bulunan["carpan"])
        self.assertIsNone(bulunan["miktar"])
        self.assertIn("katsayı 1 kabul edilmez", bulunan["birim_hatasi"])
        sonuc = barkod_ile_ara("8690000000005")
        self.assertEqual(sonuc["durum"], "birim_hatasi")

        paket = StokService.barkod_ile_bul("8690000000012")
        self.assertEqual(paket["carpan"], D("100"))
        self.assertIsNone(paket["birim_hatasi"])
        self.assertEqual(barkod_ile_ara("8690000000012")["durum"], "ok")


if __name__ == "__main__":
    unittest.main()
