"""KREDILER hesabı ↔ BankaKredisi eşlemesi; ekran bakiyesi ana kartla aynı."""

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
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi, BankaKredisi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class KrediEslemeGorunumTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "kredi_esleme.db"
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
            firma = Firma(firma_kodu="KRES", unvan="Kredi Esleme", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Sube(
                    firma_id=firma.id,
                    sube_kodu="MERKEZ",
                    sube_adi="Merkez",
                    merkez=True,
                    aktif=True,
                )
            )
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
            ana = BankaKarti(banka_adi="Akbank", aktif=True)
            s.add(ana)
            s.flush()
            yer = FinansHesabi(
                hesap_adi="Akbank — Krediler Hesabı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=ana.id,
                aktif=False,
                acilis_bakiyesi=Decimal("0"),
            )
            gercek = FinansHesabi(
                hesap_adi="Akbank 01 Nolu RKN Kredi",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("-42585.36"),
            )
            s.add_all([yer, gercek])
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=gercek.id,
                    tarih=date(2026, 9, 12),
                    hareket_turu="BANKA GİRİŞ",
                    belge_no="EVB-BN-1",
                    tutar=Decimal("14195.12"),
                    aciklama="Anapara ödemesi",
                )
            )
            s.commit()
            self.ana_id = int(ana.id)
            self.gercek_id = int(gercek.id)
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        self.engine = eng
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="t",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Y",
            permissions={"finans_duzenleme"},
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="KRES",
            firma_unvan="Kredi Esleme",
            firma_uid="kres",
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
            self.engine.dispose()
        finally:
            self._tmpdir.cleanup()

    def test_esleme_ekran_bakiyesi_ve_hareket(self):
        with get_session() as s:
            kart = s.get(BankaKarti, self.ana_id)
            ham = FinansService.banka_bakiyeler(kart)["KREDILER"]
            self.assertEqual(ham, Decimal("-28390.24"))
            alt = FinansService.banka_alt_hesap(kart, "KREDILER")
            self.assertEqual(int(alt.id), self.gercek_id)

        self.assertEqual(FinansService.banka_kredileri(banka_karti_id=self.ana_id), [])

        rapor = FinansService.banka_kredileri_eslestir(yaz=True)
        self.assertEqual(len(rapor["olusturulan"]), 1)

        krediler = FinansService.banka_kredileri(banka_karti_id=self.ana_id)
        self.assertEqual(len(krediler), 1)
        self.assertEqual(int(krediler[0].bagli_hesap_id), self.gercek_id)
        self.assertEqual(krediler[0].taksit_sayisi, 0)

        det = FinansService.banka_kredi_getir(krediler[0].id)
        self.assertTrue(det["plan_eksik"])
        self.assertEqual(det["kalan_anapara"], Decimal("28390.24"))

        with get_session() as s:
            kart = s.get(BankaKarti, self.ana_id)
            varlik = FinansService.banka_bakiyeler_varlik(kart)["KREDILER"]
            # Evo/devir: ham borç − → işletme de −
            self.assertEqual(varlik, Decimal("-28390.24"))

        har = FinansService.banka_kredi_hesap_hareketleri(self.ana_id)
        self.assertGreaterEqual(len(har), 1)
        self.assertFalse(har[0]["esleme_bekliyor"])

        # Tekrar çoğaltmaz; ledger aynı
        rapor2 = FinansService.banka_kredileri_eslestir(yaz=True)
        self.assertEqual(rapor2["olusturulan"], [])
        self.assertEqual(len(FinansService.banka_kredileri(banka_karti_id=self.ana_id)), 1)
        with get_session() as s:
            self.assertEqual(
                FinansService.bakiye(s.get(FinansHesabi, self.gercek_id)),
                Decimal("-28390.24"),
            )
            self.assertEqual(
                s.scalar(select(BankaKredisi).where(BankaKredisi.bagli_hesap_id == self.gercek_id)).ana_para,
                Decimal("42585.36"),
            )


if __name__ == "__main__":
    unittest.main()
