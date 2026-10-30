"""Alt hesap IBAN / şube kaydı (Doc5: IBAN ana kartta değil, hesapta)."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

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
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHesabi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum

GECERLI_TR = "TR330006100519786457841326"


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class AltHesapIbanTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "alt_iban.db"
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
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="IB", unvan="IBAN Test", aktif=True)
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
            banka = BankaKarti(
                banka_adi="TEST IBAN BANK",
                sube="Eski Şube",
                hesap_no="999",
                iban=GECERLI_TR,
            )
            s.add(banka)
            s.flush()
            s.add(
                FinansHesabi(
                    hesap_adi="TEST IBAN BANK — Mevduat",
                    hesap_turu="BANKA",
                    banka_karti_id=banka.id,
                    alt_hesap_turu="MEVDUAT",
                    acilis_bakiyesi=Decimal("0"),
                    para_birimi="TRY",
                )
            )
            s.commit()
            self.banka_id = banka.id
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
            firma_kodu="IB",
            firma_unvan="IBAN Test",
            firma_uid="ib",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_migrate_kart_iban_to_mevduat(self):
        finans_hesap_schemasini_guncelle(company_db._engine)
        with get_session() as s:
            h = s.scalar(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == self.banka_id,
                    FinansHesabi.alt_hesap_turu == "MEVDUAT",
                )
            )
            self.assertEqual(h.iban, GECERLI_TR)
            self.assertEqual(h.sube, "Eski Şube")
            self.assertEqual(h.hesap_no, "999")

    def test_alt_hesap_kaydet_iban_dogrular(self):
        with get_session() as s:
            hid = s.scalar(
                select(FinansHesabi.id).where(
                    FinansHesabi.banka_karti_id == self.banka_id,
                    FinansHesabi.alt_hesap_turu == "MEVDUAT",
                )
            )
        with self.assertRaisesRegex(ValueError, "kontrol basamağı|26 karakter"):
            FinansService.alt_hesap_kaydet({"hesap_id": hid, "iban": "TR990006100519786457841326"})
        h = FinansService.alt_hesap_kaydet(
            {
                "hesap_id": hid,
                "sube": "Kadıköy",
                "sube_kodu": "1234",
                "hesap_no": "555001",
                "iban": "TR33 0006 1005 1978 6457 8413 26",
                "bloke_tutari": "100",
                "varsayilan": True,
            }
        )
        self.assertEqual(h.iban, GECERLI_TR)
        self.assertEqual(h.sube, "Kadıköy")
        self.assertEqual(h.sube_kodu, "1234")
        self.assertEqual(h.hesap_no, "555001")
        self.assertEqual(Decimal(str(h.bloke_tutari)), Decimal("100"))
        self.assertTrue(h.varsayilan)


if __name__ == "__main__":
    unittest.main()
