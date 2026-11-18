"""Krediler ekranı: seçili kredi_id ile taksit/hareket ayrımı."""

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
from database.models.finans import (
    BankaKarti,
    BankaKredisi,
    BankaKrediTaksit,
    FinansHareketi,
    FinansHesabi,
)
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum

D = Decimal


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class KrediSecimFiltreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "kredi_sec.db"
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
            firma = Firma(firma_kodu="KSEL", unvan="Kredi Secim", aktif=True)
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
            banka = BankaKarti(banka_adi="TestBank", aktif=True)
            s.add(banka)
            s.flush()
            h1 = FinansHesabi(
                hesap_adi="TestBank 1 Nolu",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=banka.id,
                aktif=True,
                acilis_bakiyesi=D("-210000"),
            )
            h2 = FinansHesabi(
                hesap_adi="TestBank 2 Nolu",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=banka.id,
                aktif=True,
                acilis_bakiyesi=D("-83733.28"),
            )
            s.add_all([h1, h2])
            s.flush()
            k1 = BankaKredisi(
                belge_no="EVB-KR-T147",
                banka_karti_id=banka.id,
                kredi_adi="1 Nolu",
                kredi_turu="ESNAF",
                ana_para=D("210000"),
                toplam_faiz=0,
                toplam_masraf=0,
                taksit_sayisi=2,
                kullandirim_tarihi=date(2026, 1, 1),
                ilk_taksit_tarihi=date(2026, 2, 1),
                odeme_hesap_turu="MEVDUAT",
                bagli_hesap_id=h1.id,
                durum="KULLANDIRILDI",
                aktif=True,
            )
            k2 = BankaKredisi(
                belge_no="EVB-KR-T142",
                banka_karti_id=banka.id,
                kredi_adi="2 Nolu",
                kredi_turu="ESNAF",
                ana_para=D("83733.28"),
                toplam_faiz=0,
                toplam_masraf=0,
                taksit_sayisi=2,
                kullandirim_tarihi=date(2026, 1, 1),
                ilk_taksit_tarihi=date(2026, 2, 1),
                odeme_hesap_turu="MEVDUAT",
                bagli_hesap_id=h2.id,
                durum="KULLANDIRILDI",
                aktif=True,
            )
            s.add_all([k1, k2])
            s.flush()
            # H142 benzeri: banka taksit_no 17–18, plan adedi 2
            s.add_all(
                [
                    BankaKrediTaksit(
                        kredi_id=k1.id,
                        taksit_no=1,
                        vade_tarihi=date(2026, 2, 1),
                        anapara=D("100000"),
                        faiz=D("1000"),
                        masraf=0,
                        durum="BEKLIYOR",
                    ),
                    BankaKrediTaksit(
                        kredi_id=k1.id,
                        taksit_no=2,
                        vade_tarihi=date(2026, 3, 1),
                        anapara=D("110000"),
                        faiz=D("900"),
                        masraf=0,
                        durum="ODENDI",
                    ),
                    BankaKrediTaksit(
                        kredi_id=k2.id,
                        taksit_no=17,
                        vade_tarihi=date(2026, 2, 1),
                        anapara=D("40000"),
                        faiz=D("500"),
                        masraf=0,
                        durum="BEKLIYOR",
                    ),
                    BankaKrediTaksit(
                        kredi_id=k2.id,
                        taksit_no=18,
                        vade_tarihi=date(2026, 3, 1),
                        anapara=D("43733.28"),
                        faiz=D("400"),
                        masraf=0,
                        durum="BEKLIYOR",
                    ),
                ]
            )
            s.add(
                FinansHareketi(
                    hesap_id=h2.id,
                    tarih=date(2026, 1, 15),
                    hareket_turu="BANKA ÇIKIŞ",
                    belge_no="OD-142",
                    tutar=D("1000"),
                    aciklama="H142 odeme",
                )
            )
            s.add(
                FinansHareketi(
                    hesap_id=h1.id,
                    tarih=date(2026, 1, 16),
                    hareket_turu="BANKA ÇIKIŞ",
                    belge_no="OD-147",
                    tutar=D("2000"),
                    aciklama="H147 odeme",
                )
            )
            s.commit()
            self.banka_id = int(banka.id)
            self.k1 = int(k1.id)
            self.k2 = int(k2.id)
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
            firma_kodu="KSEL",
            firma_unvan="Kredi Secim",
            firma_uid="ksel",
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

    def test_taksitler_krediye_gore_ayrilir(self):
        t142 = FinansService.banka_kredi_taksitleri(self.k2)
        self.assertEqual(len(t142), 2)
        self.assertTrue(all(t["kredi_id"] == self.k2 for t in t142))
        self.assertEqual(t142[0]["plan_sira"], 1)
        self.assertEqual(t142[0]["plan_adet"], 2)
        self.assertEqual(t142[0]["taksit_no"], 17)  # banka no korunur
        self.assertEqual(f"{t142[0]['plan_sira']}/{t142[0]['plan_adet']}", "1/2")

        t147 = FinansService.banka_kredi_taksitleri(self.k1)
        self.assertEqual(len(t147), 2)
        self.assertTrue(all(t["kredi_id"] == self.k1 for t in t147))
        # Ödenmiş de dahil
        durumlar = {t["durum"] for t in t147}
        self.assertIn("ODENDI", durumlar)
        self.assertIn("BEKLIYOR", durumlar)

    def test_hareketler_krediye_gore_ayrilir(self):
        h142 = FinansService.banka_kredi_hesap_hareketleri(
            self.banka_id, kredi_id=self.k2
        )
        self.assertTrue(h142)
        self.assertTrue(all(h.get("kredi_id") == self.k2 for h in h142))
        self.assertTrue(any(h.get("belge_no") == "OD-142" for h in h142))
        self.assertFalse(any(h.get("belge_no") == "OD-147" for h in h142))

        h147 = FinansService.banka_kredi_hesap_hareketleri(
            self.banka_id, kredi_id=self.k1
        )
        self.assertTrue(any(h.get("belge_no") == "OD-147" for h in h147))
        self.assertFalse(any(h.get("belge_no") == "OD-142" for h in h147))


if __name__ == "__main__":
    unittest.main()
