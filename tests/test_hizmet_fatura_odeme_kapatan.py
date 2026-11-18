"""Hizmet fatura Ödemeler/Tahsilatlar — kapatan kayıt listesi (alış negatif SH)."""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from database.models.cari import Cari, CariIslem, CariKapatma, SatisHareketi
from database.models.hizmet_faturasi import HizmetFaturasi, HizmetFaturasiSatiri
from tests import test_tahsilat_makbuzu as _servis_testi

D = Decimal


class HizmetFaturaOdemeKapatanTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        from database.database import get_session
        from database.acik_kalem_service import AcikKalemService

        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())
            cari = Cari(
                cari_kodu="T-HF-1",
                unvan="Test Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            f = HizmetFaturasi(
                fatura_no="HF-TEST-950",
                fatura_turu="GIDER",
                fatura_tarihi=date(2026, 10, 6),
                vade_tarihi=date(2026, 10, 6),
                cari_id=cari.id,
                odeme_tutari=D("950"),
                durum="KAPALI",
                tl_genel_toplam=D("950"),
            )
            f.satirlar.append(
                HizmetFaturasiSatiri(
                    hizmet_kodu="HG-1",
                    hizmet_adi="Test Gider",
                    miktar=D("1"),
                    birim="Adet",
                    birim_fiyat=D("950"),
                    kdv_orani=D("0"),
                    tl_birim_fiyat=D("950"),
                    tl_tutar=D("950"),
                )
            )
            s.add(f)
            s.flush()
            hedef = SatisHareketi(
                cari_id=cari.id,
                satis_tarihi=date(2026, 10, 6),
                belge_no="HF-TEST-950",
                satis_tutari=D("-950"),
                kalan_acik_tutar=D("0"),
            )
            s.add(hedef)
            s.flush()
            kaynak = SatisHareketi(
                cari_id=cari.id,
                satis_tarihi=date(2026, 10, 6),
                belge_no="EVB-BNC-TEST",
                satis_tutari=D("0"),
                kalan_acik_tutar=D("0"),
            )
            s.add(kaynak)
            s.flush()
            s.add(
                CariIslem(
                    cari_id=cari.id,
                    belge_no="EVB-BNC-TEST",
                    islem_turu="Ödeme",
                    tarih=date(2026, 10, 6),
                    borc=D("950"),
                    alacak=D("0"),
                    hesap_adi="Test KK",
                )
            )
            s.add(
                CariKapatma(
                    islem_kimligi=str(uuid.uuid4()),
                    cari_id=cari.id,
                    kaynak_belge_no="EVB-BNC-TEST",
                    kaynak_tur="AVANS",
                    kaynak_hareket_id=kaynak.id,
                    hedef_hareket_id=hedef.id,
                    hedef_belge_no="HF-TEST-950",
                    tutar=D("950"),
                    para_birimi="TRY",
                    tarih=date(2026, 10, 6),
                    yontem="FIFO",
                    iptal=False,
                )
            )
            s.flush()
            self.fatura_id = f.id
            self.cari_id = cari.id

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def test_negatif_sh_kapatan_listelenir(self):
        from database.kapatma_izleme_service import evrak_kapatma_detayi
        from database.hizmet_faturasi_service import HizmetFaturasiService

        d = evrak_kapatma_detayi("HF-TEST-950", self.cari_id)
        self.assertEqual(d["esas_tutar"], D("950.00"))
        self.assertEqual(d["kapanan"], D("950.00"))
        self.assertEqual(d["kalan"], D("0.00"))
        self.assertTrue(d["kapatanlar"])
        self.assertEqual(d["kapatanlar"][0]["belge_no"], "EVB-BNC-TEST")
        self.assertEqual(d["kapatanlar"][0]["pay"], D("950.00"))

        bil = HizmetFaturasiService.kapatan_odemeleri(self.fatura_id)
        self.assertFalse(bil["eksik_baglanti"])
        self.assertEqual(len(bil["satirlar"]), 1)
        self.assertEqual(bil["satirlar"][0]["hesap"], "Test KK")

    def test_odeme_silince_fatura_acilir(self):
        from database.acik_kalem_service import AcikKalemService
        from database.database import get_session
        from database.hizmet_faturasi_service import HizmetFaturasiService

        with get_session() as s:
            AcikKalemService.belge_geri_al(
                s, self.cari_id, "EVB-BNC-TEST", neden="test iptal"
            )
        sync = HizmetFaturasiService.odeme_durumunu_senkronla(self.fatura_id)
        self.assertEqual(sync["durum"], "AÇIK")
        self.assertEqual(Decimal(str(sync["odeme_tutari"])), D("0.00"))
        with get_session() as s:
            f = s.get(HizmetFaturasi, self.fatura_id)
            self.assertEqual(f.durum, "AÇIK")
            h = s.scalar(
                select(SatisHareketi).where(SatisHareketi.belge_no == "HF-TEST-950")
            )
            self.assertEqual(Decimal(str(h.kalan_acik_tutar)), D("-950.00"))

    def test_kismi_iki_odeme_ve_tutar_degisimi(self):
        """İki kısmi kapatma → kalan; biri iptal → kalan güncellenir."""
        from database.acik_kalem_service import AcikKalemService
        from database.database import get_session
        from database.hizmet_faturasi_service import HizmetFaturasiService

        with get_session() as s:
            AcikKalemService.belge_geri_al(
                s, self.cari_id, "EVB-BNC-TEST", neden="reset"
            )
            hedef = s.scalar(
                select(SatisHareketi).where(SatisHareketi.belge_no == "HF-TEST-950")
            )
            hedef.kalan_acik_tutar = D("-950")
            k1 = SatisHareketi(
                cari_id=self.cari_id,
                satis_tarihi=date(2026, 10, 7),
                belge_no="ODM-P1",
                satis_tutari=D("0"),
                kalan_acik_tutar=D("0"),
            )
            k2 = SatisHareketi(
                cari_id=self.cari_id,
                satis_tarihi=date(2026, 10, 8),
                belge_no="ODM-P2",
                satis_tutari=D("0"),
                kalan_acik_tutar=D("0"),
            )
            s.add_all([k1, k2])
            s.flush()
            s.add(
                CariKapatma(
                    islem_kimligi=str(uuid.uuid4()),
                    cari_id=self.cari_id,
                    kaynak_belge_no="ODM-P1",
                    kaynak_tur="ODEME",
                    kaynak_hareket_id=k1.id,
                    hedef_hareket_id=hedef.id,
                    hedef_belge_no="HF-TEST-950",
                    tutar=D("400"),
                    para_birimi="TRY",
                    tarih=date(2026, 10, 7),
                    yontem="MANUEL",
                    iptal=False,
                )
            )
            s.add(
                CariKapatma(
                    islem_kimligi=str(uuid.uuid4()),
                    cari_id=self.cari_id,
                    kaynak_belge_no="ODM-P2",
                    kaynak_tur="ODEME",
                    kaynak_hareket_id=k2.id,
                    hedef_hareket_id=hedef.id,
                    hedef_belge_no="HF-TEST-950",
                    tutar=D("550"),
                    para_birimi="TRY",
                    tarih=date(2026, 10, 8),
                    yontem="MANUEL",
                    iptal=False,
                )
            )
            hedef.kalan_acik_tutar = D("0")
            s.flush()

        bil = HizmetFaturasiService.kapatan_odemeleri(self.fatura_id)
        self.assertEqual(len(bil["satirlar"]), 2)
        self.assertEqual(Decimal(str(bil["kapanan"])), D("950.00"))
        self.assertEqual(Decimal(str(bil["kalan"])), D("0.00"))

        with get_session() as s:
            AcikKalemService.belge_geri_al(s, self.cari_id, "ODM-P2", neden="kısmi iptal")
        sync = HizmetFaturasiService.odeme_durumunu_senkronla(self.fatura_id)
        self.assertEqual(sync["durum"], "AÇIK")
        self.assertEqual(Decimal(str(sync["odeme_tutari"])), D("400.00"))
        self.assertEqual(Decimal(str(sync["kalan"])), D("550.00"))

        # Yeniden aç / mükerrer yok
        bil2 = HizmetFaturasiService.kapatan_odemeleri(self.fatura_id)
        self.assertEqual(len(bil2["satirlar"]), 1)
        self.assertEqual(bil2["satirlar"][0]["belge_no"], "ODM-P1")

    def test_gelir_tahsilat_yonu(self):
        from database.database import get_session
        from database.hizmet_faturasi_service import HizmetFaturasiService

        with get_session() as s:
            cari = Cari(
                cari_kodu="M-HF-G",
                unvan="Test Müşteri HF",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            f = HizmetFaturasi(
                fatura_no="HF-GELIR-100",
                fatura_turu="GELIR",
                fatura_tarihi=date(2026, 10, 1),
                vade_tarihi=date(2026, 10, 1),
                cari_id=cari.id,
                odeme_tutari=D("100"),
                durum="KAPALI",
                tl_genel_toplam=D("100"),
            )
            f.satirlar.append(
                HizmetFaturasiSatiri(
                    hizmet_kodu="HGEL",
                    hizmet_adi="Hizmet Gelir",
                    miktar=D("1"),
                    birim="Adet",
                    birim_fiyat=D("100"),
                    kdv_orani=D("0"),
                    tl_birim_fiyat=D("100"),
                    tl_tutar=D("100"),
                )
            )
            s.add(f)
            s.flush()
            hedef = SatisHareketi(
                cari_id=cari.id,
                satis_tarihi=date(2026, 10, 1),
                belge_no="HF-GELIR-100",
                satis_tutari=D("100"),
                kalan_acik_tutar=D("0"),
            )
            s.add(hedef)
            s.flush()
            kaynak = SatisHareketi(
                cari_id=cari.id,
                satis_tarihi=date(2026, 10, 1),
                belge_no="THS-G1",
                satis_tutari=D("0"),
                kalan_acik_tutar=D("0"),
            )
            s.add(kaynak)
            s.flush()
            s.add(
                CariIslem(
                    cari_id=cari.id,
                    belge_no="THS-G1",
                    islem_turu="Tahsilat",
                    tarih=date(2026, 10, 1),
                    borc=D("0"),
                    alacak=D("100"),
                    hesap_adi="Test Kasa",
                )
            )
            s.add(
                CariKapatma(
                    islem_kimligi=str(uuid.uuid4()),
                    cari_id=cari.id,
                    kaynak_belge_no="THS-G1",
                    kaynak_tur="TAHSILAT",
                    kaynak_hareket_id=kaynak.id,
                    hedef_hareket_id=hedef.id,
                    hedef_belge_no="HF-GELIR-100",
                    tutar=D("100"),
                    para_birimi="TRY",
                    tarih=date(2026, 10, 1),
                    yontem="FIFO",
                    iptal=False,
                )
            )
            s.flush()
            fid = f.id

        bil = HizmetFaturasiService.kapatan_odemeleri(fid)
        self.assertFalse(bil["eksik_baglanti"])
        self.assertEqual(bil["satirlar"][0]["belge_no"], "THS-G1")
        self.assertEqual(bil["satirlar"][0]["odeme_sekli"], "Tahsilat")
        self.assertEqual(bil["satirlar"][0]["hesap"], "Test Kasa")


if __name__ == "__main__":
    unittest.main()
