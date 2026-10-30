"""Kasa döviz / kayıt kuru (Doc5 §9–10): tek PB, hareket PB+kur+TL, PB ara toplam."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

# select used in setUp / assertions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    finans_hesap_schemasini_guncelle,
    get_session,
)
from database.finans_service import FinansService
from database.models.doviz import DovizKuru
from database.models.donem import Donem
from database.models.finans import FinansHareketi, FinansHesabi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class KasaDovizKurTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "kasa_fx.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")
        Base.metadata.create_all(eng)
        finans_hesap_schemasini_guncelle(eng)
        self.eng = eng
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="FX", unvan="FX Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Sube(firma_id=firma.id, sube_kodu="MERKEZ", sube_adi="Merkez", merkez=True, aktif=True))
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2000, 1, 1),
                    bitis_tarihi=date(2099, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.add(
                DovizKuru(
                    rate_date=date(2026, 10, 28),
                    currency_code="USD",
                    forex_buying=Decimal("39.500000"),
                    forex_selling=Decimal("40.000000"),
                    effective_buying=Decimal("39.400000"),
                    effective_selling=Decimal("40.000000"),
                    source="MANUEL",
                )
            )
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="t",
            ad_soyad="t",
            role_kod="YONETICI",
            role_ad="Y",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="FX",
            firma_unvan="FX Test",
            firma_uid="fx",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_usd_kasa_acilis_ve_hareket_tl_kayit(self):
        """Doc5 örnek: 2.000 USD @ 40 → bakiye 2000 USD, TL kayıt 80.000."""
        hesap = FinansService.hesap_kaydet(
            {
                "hesap_adi": "USD KASA",
                "hesap_turu": "KASA",
                "para_birimi": "USD",
                "acilis_bakiyesi": "2000",
                "acilis_tarihi": "28.10.2026",
                "acilis_kuru": "40",
            }
        )
        self.assertEqual(FinansService.hesap_pb(hesap), "USD")
        self.assertEqual(FinansService.bakiye(hesap), Decimal("2000.00"))
        self.assertEqual(FinansService.tl_kayit_bakiyesi(hesap), Decimal("80000.00"))

        with get_session() as s:
            FinansService.hareket_ekle(
                s,
                "FX-1",
                date(2026, 10, 28),
                Decimal("100"),
                "FATURA TAHSİLATI",
                "USD KASA",
                kur=Decimal("42"),
            )
        hesap = FinansService.hesap_getir(hesap.id)
        self.assertEqual(FinansService.bakiye(hesap), Decimal("2100.00"))
        self.assertEqual(FinansService.tl_kayit_bakiyesi(hesap), Decimal("84200.00"))
        with get_session() as s:
            har = s.scalar(
                select(FinansHareketi).where(FinansHareketi.belge_no == "FX-1")
            )
            self.assertEqual(har.para_birimi, "USD")
            self.assertEqual(har.kur, Decimal("42.000000"))
            self.assertEqual(har.tl_karsiligi, Decimal("4200.00"))

    def test_try_hareket_kur_1(self):
        FinansService.hesap_kaydet(
            {
                "hesap_adi": "TL KASA",
                "hesap_turu": "KASA",
                "para_birimi": "TRY",
                "acilis_bakiyesi": "0",
            }
        )
        with get_session() as s:
            FinansService.hareket_ekle(
                s, "TL-1", date(2026, 10, 28), Decimal("150.50"), "KASA GİRİŞ", "TL KASA"
            )
            s.flush()
            har = s.scalar(select(FinansHareketi).where(FinansHareketi.belge_no == "TL-1"))
            self.assertIsNotNone(har)
            self.assertEqual(har.para_birimi, "TRY")
            self.assertEqual(Decimal(str(har.kur)), Decimal("1"))
            self.assertEqual(har.tl_karsiligi, Decimal("150.50"))

    def test_pb_degisikligi_hareketten_sonra_engellenir(self):
        hesap = FinansService.hesap_kaydet(
            {
                "hesap_adi": "KASA A",
                "hesap_turu": "KASA",
                "para_birimi": "TRY",
                "acilis_bakiyesi": "10",
            }
        )
        with get_session() as s:
            FinansService.hareket_ekle(
                s, "A-1", date(2026, 10, 28), Decimal("5"), "KASA GİRİŞ", "KASA A"
            )
        with self.assertRaisesRegex(ValueError, "para birimi değiştirilemez"):
            FinansService.hesap_kaydet(
                {
                    "hesap_id": hesap.id,
                    "hesap_adi": "KASA A",
                    "hesap_turu": "KASA",
                    "para_birimi": "USD",
                    "acilis_bakiyesi": "10",
                    "acilis_kuru": "40",
                }
            )

    def test_pb_uyusmazligi_harekette(self):
        FinansService.hesap_kaydet(
            {
                "hesap_adi": "EUR KASA",
                "hesap_turu": "KASA",
                "para_birimi": "EUR",
                "acilis_bakiyesi": "0",
                "acilis_kuru": "45",
                "acilis_tarihi": "28.10.2026",
            }
        )
        with get_session() as s:
            with self.assertRaisesRegex(ValueError, "uyuşmuyor"):
                FinansService.hareket_ekle(
                    s,
                    "E-1",
                    date(2026, 10, 28),
                    Decimal("10"),
                    "KASA GİRİŞ",
                    "EUR KASA",
                    kur=Decimal("45"),
                    para_birimi="USD",
                )

    def test_dogrudan_eklemede_try_kur_dolar(self):
        with get_session() as s:
            h = FinansHesabi(
                hesap_adi="DOĞRUDAN KASA",
                hesap_turu="KASA",
                para_birimi="TRY",
                acilis_bakiyesi=Decimal("0"),
            )
            s.add(h)
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=h.id,
                    tarih=date(2026, 10, 28),
                    hareket_turu="KASA GİRİŞ",
                    belge_no="D-1",
                    tutar=Decimal("25"),
                )
            )
            s.flush()
            har = s.scalar(select(FinansHareketi).where(FinansHareketi.belge_no == "D-1"))
            self.assertEqual(har.para_birimi, "TRY")
            self.assertEqual(har.kur, Decimal("1"))
            self.assertEqual(har.tl_karsiligi, Decimal("25.00"))


if __name__ == "__main__":
    unittest.main()
