"""Satış iadesi → açık satış borcu kapatma (izole SQLite; canlı D2 yok).

İade onayı/kaydı cari alacak + AcikKalem kapatma kaydı üretir; ikinci stok/cari borç yaratmaz.
Kaynak fatura varsa öncelikli mahsup.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from database.acik_kalem_service import AcikKalemService
from database.database import get_session
from database.models.cari import CariIslem, CariKapatma, SatisHareketi
from database.models.stok import StokHareketi
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from tests.stok_test_ortami import StokOrtami

D = Decimal
TARIH = date(2026, 11, 12)


class SatisIadeBorcKapatmaTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami("iade_kapat")
        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())
        self.o.alis(1000, "10", TARIH, lot="IK1")

    def tearDown(self):
        self.o.kapat()

    def _satis(self, tutar_hedef="10000"):
        """KDV %20 dahil ~hedef genel toplam (matrah = hedef/1.2)."""
        matrah = (D(tutar_hedef) / D("1.2")).quantize(D("0.01"))
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": matrah,
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        SatisFaturasiService.onayla(f.id)
        return SatisFaturasiService.getir(f.id)

    def _iade(self, fatura, tutar_hedef="3000"):
        matrah = (D(tutar_hedef) / D("1.2")).quantize(D("0.01"))
        satir = fatura.satirlar[0]
        return SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": TARIH,
                "cari_id": self.o.mus_id,
                "kaynak_fatura_id": fatura.id,
                "depo": "ANA DEPO",
                "iade_odeme_tutari": D("0"),
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": matrah,
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "kaynak_fatura_satiri_id": satir.id,
                }
            ],
        )

    def _kalan(self, belge_no: str) -> Decimal:
        with get_session() as s:
            h = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.satis_tutari > 0,
                )
            )
            return D(str(h.kalan_acik_tutar)) if h else D("0")

    def _kapatma_kaynak(self, iade_no: str):
        with get_session() as s:
            return list(
                s.scalars(
                    select(CariKapatma).where(
                        CariKapatma.kaynak_belge_no == iade_no,
                        CariKapatma.iptal.is_(False),
                    )
                ).all()
            )

    def test_10000_borc_3000_iade_kalan_7000(self):
        f = self._satis("10000")
        self.assertEqual(self._kalan(f.fatura_no), D("10000.00"))
        once_cikis = self.o.hareket_sayisi(tur="FATURA ÇIKIŞ")
        once_cari = 0
        with get_session() as s:
            once_cari = int(s.scalar(select(func.count()).select_from(CariIslem)) or 0)
        iade = self._iade(f, "3000")
        self.assertEqual(self._kalan(f.fatura_no), D("7000.00"))
        kayit = self._kapatma_kaynak(iade.iade_no)
        self.assertEqual(len(kayit), 1)
        self.assertEqual(D(str(kayit[0].tutar)), D("3000.00"))
        self.assertEqual((kayit[0].kaynak_tur or "").upper(), "IADE")
        # İkinci stok çıkışı / mükerrer cari borç yok; iade girişi + bir cari alacak beklenir
        self.assertEqual(self.o.hareket_sayisi(tur="FATURA ÇIKIŞ"), once_cikis)
        with get_session() as s:
            after_cari = int(s.scalar(select(func.count()).select_from(CariIslem)) or 0)
        self.assertEqual(after_cari, once_cari + 1)

    def test_10000_borc_10000_iade_kalan_0_nakit_yok(self):
        f = self._satis("10000")
        iade = self._iade(f, "10000")
        self.assertEqual(self._kalan(f.fatura_no), D("0.00"))
        with get_session() as s:
            from database.models.finans import FinansHareketi

            nakit = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == iade.iade_no)
                ).all()
            )
        self.assertEqual(nakit, [])
        f2 = SatisFaturasiService.getir(f.id)
        self.assertEqual(f2.durum, "AÇIK")  # kalan=0 otomatik KAPALI değil

    def test_10000_borc_12000_iade_avans_2000(self):
        f = self._satis("10000")
        iade = self._iade(f, "12000")
        self.assertEqual(self._kalan(f.fatura_no), D("0.00"))
        with get_session() as s:
            avans = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == iade.iade_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertIsNotNone(avans)
            self.assertEqual(D(str(avans.kalan_acik_tutar)), D("-2000.00"))

    def test_iade_iptal_borcu_geri_acar(self):
        f = self._satis("10000")
        iade = self._iade(f, "3000")
        self.assertEqual(self._kalan(f.fatura_no), D("7000.00"))
        SatisIadeFaturasiService.iptal_et(iade.id)
        self.assertEqual(self._kalan(f.fatura_no), D("10000.00"))
        aktif = self._kapatma_kaynak(iade.iade_no)
        self.assertEqual(aktif, [])

    def test_taslak_farkli_cari_red(self):
        f = self._satis("10000")
        with self.assertRaises(Exception):
            SatisIadeFaturasiService.kaydet(
                {
                    "iade_tarihi": TARIH,
                    "cari_id": self.o.ted_id,  # tedarikçi — müşteri değil
                    "kaynak_fatura_id": f.id,
                    "depo": "ANA DEPO",
                    "iade_odeme_tutari": D("0"),
                },
                [
                    {
                        "urun_kodu": "U001",
                        "urun_adi": "Test",
                        "miktar": D("1"),
                        "birim": "Adet",
                        "birim_fiyat": D("100"),
                        "iskonto_orani": D("0"),
                        "kdv_orani": D("20"),
                        "kaynak_fatura_satiri_id": f.satirlar[0].id,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
