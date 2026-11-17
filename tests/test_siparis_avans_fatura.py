"""Sipariş avansı → fatura taşıma: tek kasa, rezerv eski borca gitmez, kalan açık doğru."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.acik_kalem_service import AcikKalemService
from database.database import get_session
from database.models.cari import CariKapatma, SatisHareketi
from database.models.finans import FinansHareketi, FinansHesabi
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_siparisi_service import SatisSiparisiService
from tests.test_alinan_siparis import _SiparisTemel, _satir

D = Decimal
TARIH = date(2026, 3, 1)


class SiparisAvansFaturaTest(_SiparisTemel):
    def setUp(self):
        super().setUp()
        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())
            kasa = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == "TEST KASA"))
            if kasa is None:
                kasa = FinansHesabi(
                    hesap_adi="TEST KASA", hesap_turu="KASA", acilis_bakiyesi=D("100000")
                )
                s.add(kasa)
                s.flush()
            self.kasa_adi = kasa.hesap_adi

    def _eski_borc(self, tutar="5000"):
        with get_session() as s:
            s.add(
                SatisHareketi(
                    cari_id=self.cari_id,
                    satis_tarihi=date(2026, 2, 1),
                    belge_no="SF-ESKI-5000",
                    satis_tutari=D(tutar),
                    kalan_acik_tutar=D(tutar),
                )
            )

    def _siparis_avansli(self, miktar="10", fiyat="1000", avans="6000"):
        # 10 × 1000 + %20 KDV = 12000; avans 6000
        return SatisSiparisiService.kaydet(
            self._veri(onayla=True),
            [_satir(miktar, "Adet", fiyat=fiyat, kdv_orani=D("20"))],
            [
                {
                    "tahsilat_tarihi": TARIH,
                    "tutar": D(avans),
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": self.kasa_adi,
                    "aciklama": "Sipariş avansı",
                }
            ],
        )

    def _kasa_adet(self, belge_no) -> int:
        with get_session() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(FinansHareketi)
                    .where(
                        FinansHareketi.belge_no == belge_no,
                        FinansHareketi.hareket_turu == "SİPARİŞ AVANSI",
                    )
                )
                or 0
            )

    def _fatura_kasa_adet(self, fatura_no) -> int:
        with get_session() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(FinansHareketi)
                    .where(
                        FinansHareketi.belge_no == fatura_no,
                        FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
                    )
                )
                or 0
            )

    def test_avans_eski_borca_gitmez_ve_faturaya_tasinir(self):
        self._eski_borc("5000")
        sip = self._siparis_avansli()
        self.assertEqual(self._kasa_adet(sip.siparis_no), 1)
        with get_session() as s:
            eski = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-ESKI-5000"))
            self.assertEqual(D(str(eski.kalan_acik_tutar)), D("5000.00"))
            avans = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == sip.siparis_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertEqual(D(str(avans.kalan_acik_tutar)), D("-6000.00"))
            # Serbest FIFO avans uygulaması sipariş rezervini yememeli
            AcikKalemService.avanslari_uygula(s, self.cari_id)
            s.refresh(eski)
            s.refresh(avans)
            self.assertEqual(D(str(eski.kalan_acik_tutar)), D("5000.00"))
            self.assertEqual(D(str(avans.kalan_acik_tutar)), D("-6000.00"))

        satir = sip.satirlar[0]
        fat = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "siparis_id": sip.id,
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "miktar": D("10"),
                    "birim": satir.birim,
                    "birim_fiyat": D("1000"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "siparis_satiri_id": satir.id,
                }
            ],
            tahsilat_verileri=[],
        )
        SatisFaturasiService.onayla(fat.id)
        with get_session() as s:
            fh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fat.fatura_no))
            self.assertEqual(D(str(fh.satis_tutari)), D("12000.00"))
            self.assertEqual(D(str(fh.kalan_acik_tutar)), D("6000.00"))
            avans = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == sip.siparis_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertEqual(D(str(avans.kalan_acik_tutar)), D("0.00"))
            eski = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-ESKI-5000"))
            self.assertEqual(D(str(eski.kalan_acik_tutar)), D("5000.00"))
            kayit = s.scalars(
                select(CariKapatma).where(
                    CariKapatma.kaynak_belge_no == sip.siparis_no,
                    CariKapatma.iptal.is_(False),
                )
            ).all()
            self.assertEqual(len(kayit), 1)
            self.assertEqual((D(str(kayit[0].tutar)), (kayit[0].yontem or "").upper()), (D("6000.00"), "SIPARIS"))
        self.assertEqual(self._kasa_adet(sip.siparis_no), 1)
        self.assertEqual(self._fatura_kasa_adet(fat.fatura_no), 0)

    def test_kismi_iki_fatura_avans_paylari(self):
        """6000 avans: 4800'lük kısmi fatura hepsini kapatır, kalan 1200 ikinci faturaya gider."""
        sip = self._siparis_avansli()
        satir = sip.satirlar[0]
        fat1 = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "siparis_id": sip.id,
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "miktar": D("4"),
                    "birim": satir.birim,
                    "birim_fiyat": D("1000"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "siparis_satiri_id": satir.id,
                }
            ],
            tahsilat_verileri=[],
        )
        SatisFaturasiService.onayla(fat1.id)
        with get_session() as s:
            fh1 = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fat1.fatura_no))
            av = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == sip.siparis_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertEqual(D(str(fh1.satis_tutari)), D("4800.00"))
            self.assertEqual(D(str(fh1.kalan_acik_tutar)), D("0.00"))
            self.assertEqual(D(str(av.kalan_acik_tutar)), D("-1200.00"))

        fat2 = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "siparis_id": sip.id,
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "miktar": D("6"),
                    "birim": satir.birim,
                    "birim_fiyat": D("1000"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "siparis_satiri_id": satir.id,
                }
            ],
            tahsilat_verileri=[],
        )
        SatisFaturasiService.onayla(fat2.id)
        with get_session() as s:
            fh2 = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fat2.fatura_no))
            av = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == sip.siparis_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertEqual(D(str(fh2.satis_tutari)), D("7200.00"))
            self.assertEqual(D(str(fh2.kalan_acik_tutar)), D("6000.00"))
            self.assertEqual(D(str(av.kalan_acik_tutar)), D("0.00"))
            kayitlar = s.scalars(
                select(CariKapatma).where(
                    CariKapatma.kaynak_belge_no == sip.siparis_no,
                    CariKapatma.iptal.is_(False),
                )
            ).all()
            self.assertEqual(len(kayitlar), 2)
            self.assertEqual(sum(D(str(k.tutar)) for k in kayitlar), D("6000.00"))
        self.assertEqual(self._kasa_adet(sip.siparis_no), 1)

    def test_iptal_kullanilmayan_avansi_geri_alir(self):
        sip = self._siparis_avansli(avans="1500")
        self.assertEqual(self._kasa_adet(sip.siparis_no), 1)
        SatisSiparisiService.iptal_et(sip.id, sebep="test iptal avans")
        self.assertEqual(self._kasa_adet(sip.siparis_no), 0)
        with get_session() as s:
            av = s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == sip.siparis_no,
                    SatisHareketi.satis_tutari == 0,
                )
            )
            self.assertIsNone(av)

    def test_iptal_tasinmis_avansi_reddeder(self):
        sip = self._siparis_avansli()
        satir = sip.satirlar[0]
        fat = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "siparis_id": sip.id,
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "miktar": D("10"),
                    "birim": satir.birim,
                    "birim_fiyat": D("1000"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "siparis_satiri_id": satir.id,
                }
            ],
            tahsilat_verileri=[],
        )
        SatisFaturasiService.onayla(fat.id)
        with self.assertRaises(ValueError) as ctx:
            SatisSiparisiService.iptal_et(sip.id, sebep="taşınmış avans")
        self.assertIn("taşınmış", str(ctx.exception).casefold())
        sip2 = SatisSiparisiService.getir(sip.id)
        self.assertNotEqual((sip2.durum or "").upper(), "İPTAL")
        self.assertEqual(self._kasa_adet(sip.siparis_no), 1)


if __name__ == "__main__":
    unittest.main()
