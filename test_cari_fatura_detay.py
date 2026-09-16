"""Cari hareket → fatura ürün detayı (aç/kapat) smoke testleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.cari_fatura_detay_service import (
    CariFaturaDetayService,
    belge_tipi_coz,
    hareket_genisletilebilir_mi,
)
from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from database.models.stok import Depo, StokHareketi, StokKarti


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class BelgeTipiTest(unittest.TestCase):
    def test_satis_alis_iade(self):
        self.assertEqual(belge_tipi_coz("Satış", "SF-00001"), "satis_faturasi")
        self.assertEqual(belge_tipi_coz("Alış", "AFAT-1"), "alis_faturasi")
        self.assertEqual(belge_tipi_coz("Satış", "IAD-1"), "satis_iade")
        self.assertEqual(belge_tipi_coz("Alış İadesi", "AIAD-1"), "alis_iade")
        self.assertIsNone(belge_tipi_coz("Tahsilat", "THS-2026-0001"))
        self.assertFalse(hareket_genisletilebilir_mi("Ödeme", "ODM-1"))
        self.assertTrue(hareket_genisletilebilir_mi("Satış", "SF-9"))


class MetaVeDetayTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "cari_fatura_detay.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            cari = Cari(
                cari_kodu="T001",
                unvan="Test Müşteri",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            depo = Depo(ad="ANA DEPO", aktif=True)
            s.add(depo)
            s.flush()
            stok = StokKarti(
                stok_kodu="U1",
                stok_adi="Ürün 1",
                birim="Adet",
                aktif=True,
                kdv_orani=Decimal("20"),
            )
            s.add(stok)
            s.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-TEST-1",
                fatura_tarihi=date.today(),
                vade_tarihi=date.today(),
                cari_id=cari.id,
                durum="AÇIK",
                depo="ANA DEPO",
            )
            s.add(fatura)
            s.flush()
            s.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün 1",
                    miktar=Decimal("2"),
                    birim="Adet",
                    birim_fiyat=Decimal("100"),
                    iskonto_orani=Decimal("0"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("200"),
                )
            )
            s.add(
                SatisHareketi(
                    cari_id=cari.id,
                    satis_tarihi=date.today(),
                    belge_no="SF-TEST-1",
                    satis_tutari=Decimal("240"),
                    kalan_acik_tutar=Decimal("240"),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date.today(),
                    hareket_turu="FATURA ÇIKIŞ",
                    belge_no="SF-TEST-1",
                    stok_id=stok.id,
                    depo_id=depo.id,
                    miktar=Decimal("2"),
                    birim_maliyet=Decimal("0"),
                )
            )
            s.commit()
            self.fatura_id = int(fatura.id)
            self.cari_id = int(cari.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        self._eng = eng

        from database.session_manager import oturum

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="CFD",
            firma_unvan="Cari Fatura Detay Test",
            firma_uid="cfd-test",
            db_path=str(self.db_path),
        )
        oturum.set_period(1, "2026")

    def tearDown(self):
        from database.session_manager import oturum

        oturum.clear()
        try:
            self._eng.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_meta_ve_detay(self):
        from database.cari_service import CariService
        from database.database import get_session

        with get_session() as s:
            defter = CariService._defter(s, self.cari_id)
        self.assertTrue(any(d.get("belge_no") == "SF-TEST-1" for d in defter))
        satir = next(d for d in defter if d.get("belge_no") == "SF-TEST-1")
        self.assertTrue(satir.get("genisletilebilir"))
        self.assertEqual(satir.get("fatura_id"), self.fatura_id)
        self.assertEqual(satir.get("belge_tipi"), "satis_faturasi")

        detay = CariFaturaDetayService.load_invoice_details(
            self.fatura_id, "satis_faturasi", cari_id=self.cari_id
        )
        self.assertEqual(len(detay["satirlar"]), 1)
        self.assertEqual(detay["satirlar"][0]["urun_kodu"], "U1")
        self.assertIn("ÇIKIŞ", detay["satirlar"][0]["stok_yonu"])

        bos = CariFaturaDetayService.load_invoice_details(
            self.fatura_id, "satis_faturasi", cari_id=999999
        )
        self.assertEqual(bos["satirlar"], [])

    def test_bakiye_etkilenmez(self):
        from database.cari_service import CariService
        from database.database import get_session

        with get_session() as s:
            d1 = CariService._defter(s, self.cari_id)
        CariFaturaDetayService.load_invoice_details(
            self.fatura_id, "satis_faturasi", cari_id=self.cari_id
        )
        with get_session() as s:
            d2 = CariService._defter(s, self.cari_id)
        self.assertEqual(len(d1), len(d2))
        self.assertEqual(d1[0]["borc"], d2[0]["borc"])
        self.assertEqual(d1[0]["kalan"], d2[0]["kalan"])


if __name__ == "__main__":
    unittest.main()
