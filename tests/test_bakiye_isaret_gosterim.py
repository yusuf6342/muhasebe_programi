"""İşletme bakiyesi yönü + para metni (+/−/0) — native ve Evo ledger."""

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
from database.finans_service import (
    BAKIYE_RENK_NEGATIF,
    BAKIYE_RENK_POZITIF,
    BAKIYE_RENK_SIFIR,
    FinansService,
)
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class BakiyeIsaretGosterimTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "bakiye_isaret.db"
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
            firma = Firma(firma_kodu="BIS", unvan="Bakiye Isaret", aktif=True)
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
            ana = BankaKarti(banka_adi="Test Bank", kmh_limiti=Decimal("5000"), aktif=True)
            s.add(ana)
            s.flush()
            # Evo: borç −
            evo_kk = FinansHesabi(
                hesap_adi="Evo KK",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("-1500"),
            )
            # Native: borç +
            nat_kk = FinansHesabi(
                hesap_adi="Native KK",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("2000"),
            )
            # Fazla ödeme Evo: açılış 0, BANKA GİRİŞ ile +
            evo_fazla = FinansHesabi(
                hesap_adi="Evo Fazla",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("0"),
            )
            mev = FinansHesabi(
                hesap_adi="Mevduat",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("10000"),
            )
            kmh = FinansHesabi(
                hesap_adi="KMH",
                hesap_turu="BANKA",
                alt_hesap_turu="KMH",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("-800"),
            )
            s.add_all([evo_kk, nat_kk, evo_fazla, mev, kmh])
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=evo_fazla.id,
                    tarih=date(2026, 1, 1),
                    hareket_turu="BANKA GİRİŞ",
                    belge_no="EVO-F",
                    tutar=Decimal("300"),
                )
            )
            # Native açılış 0 + KK ÖDEME → native yön
            nat0 = FinansHesabi(
                hesap_adi="Native Sifir Acilis",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("0"),
            )
            s.add(nat0)
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=nat0.id,
                    tarih=date(2026, 1, 2),
                    hareket_turu="KK ÖDEME",
                    belge_no="T-1",
                    tutar=Decimal("400"),
                )
            )
            s.commit()
            self.ana_id = int(ana.id)
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
            firma_kodu="BIS",
            firma_unvan="Bakiye Isaret",
            firma_uid="bis",
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

    def test_para_metni_ve_renk(self):
        self.assertEqual(FinansService.para_metni(Decimal("1234.5"), isaretli=True), "1.234,50 TL")
        self.assertEqual(FinansService.para_metni(Decimal("-1234.5"), isaretli=True), "-1.234,50 TL")
        self.assertEqual(FinansService.para_metni(Decimal("-0.004"), isaretli=True), "0,00 TL")
        self.assertEqual(FinansService.para_metni(Decimal("0"), isaretli=True), "0,00 TL")
        self.assertEqual(FinansService.bakiye_renk_kodu(1), BAKIYE_RENK_POZITIF)
        self.assertEqual(FinansService.bakiye_renk_kodu(-1), BAKIYE_RENK_NEGATIF)
        self.assertEqual(FinansService.bakiye_renk_kodu(0), BAKIYE_RENK_SIFIR)

    def test_native_alt_tur_flip(self):
        # Hesap yoksa çevirme yok (fazla ödeme + bozulmasın); native için hesap şart
        self.assertEqual(
            FinansService.varlik_bakiyesi(Decimal("30000"), alt_tur="KREDI_KARTI"),
            Decimal("30000.00"),
        )
        with get_session() as s:
            from sqlalchemy.orm import selectinload

            kart = s.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == self.ana_id)
                .options(
                    selectinload(BankaKarti.alt_hesaplar).selectinload(
                        FinansHesabi.hareketler
                    )
                )
            )
            nat = next(h for h in kart.alt_hesaplar if h.hesap_adi == "Native KK")
            # Native borç büyüklüğü +2000 → işletme −2000
            self.assertEqual(
                FinansService.isletme_bakiyesi(nat),
                Decimal("-2000.00"),
            )
            evo_fazla = next(h for h in kart.alt_hesaplar if h.hesap_adi == "Evo Fazla")
            self.assertEqual(
                FinansService.isletme_bakiyesi(evo_fazla),
                Decimal("300.00"),
            )
            self.assertEqual(
                FinansService.bakiye_renk_kodu(FinansService.isletme_bakiyesi(evo_fazla)),
                BAKIYE_RENK_POZITIF,
            )

    def test_banka_ozet_yonleri(self):
        with get_session() as s:
            kart = s.get(BankaKarti, self.ana_id)
            from sqlalchemy.orm import selectinload

            kart = s.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == self.ana_id)
                .options(selectinload(BankaKarti.alt_hesaplar).selectinload(FinansHesabi.hareketler))
            )
            var = FinansService.banka_bakiyeler_varlik(kart)
            # Mevduat +
            self.assertEqual(var["MEVDUAT"], Decimal("10000.00"))
            # KMH borç −
            self.assertEqual(var["KMH"], Decimal("-800.00"))
            # KK: Evo −1500 + Native −2000 + Evo fazla +300 + Native0 −400 = −3600
            self.assertEqual(var["KREDI_KARTI"], Decimal("-3600.00"))
            ozet = FinansService.banka_varlik_borc_ozeti(kart)
            self.assertEqual(ozet["varlik"], Decimal("10000.00"))
            self.assertEqual(ozet["borc_buyukluk"], Decimal("4400.00"))  # 800+3600
            self.assertEqual(ozet["borc_gosterim"], Decimal("-4400.00"))
            self.assertEqual(ozet["net"], Decimal("5600.00"))


if __name__ == "__main__":
    unittest.main()
