"""Fatura içi kredi kartı tahsilatı → PosValorKaydi (POS İŞLEMLERİ görünürlüğü)."""
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
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi, PosValorKaydi
from database.models.firma import Firma
from database.models.satis_faturasi import SatisFaturasi
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FaturaPosTahsilatValorTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "fatura_pos.db"
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
            firma = Firma(firma_kodu="FP", unvan="Fatura POS", aktif=True)
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
            musteri = Cari(cari_kodu="M001", unvan="Müşteri", cari_turu="Müşteri")
            s.add(musteri)
            banka = BankaKarti(
                banka_adi="TEST POS BANK",
                kk_komisyon_orani=Decimal("0"),
                pos_valor_gun=1,
                pos_hedef_hesap_turu="MEVDUAT",
                pos_valor_is_gunu=True,
                pos_otomatik_mahsup=False,
            )
            s.add(banka)
            s.flush()
            for alt, tur in (("MEVDUAT", "BANKA"), ("KMH", "BANKA"), ("POS", "BANKA")):
                s.add(
                    FinansHesabi(
                        hesap_adi=f"TEST POS BANK — {alt}",
                        hesap_turu=tur,
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                    )
                )
            s.add(
                FinansHesabi(
                    hesap_adi="Merkez Kasa",
                    hesap_turu="KASA",
                    acilis_bakiyesi=Decimal("0"),
                )
            )
            s.commit()
            self.musteri_id = musteri.id
            self.pos_adi = "TEST POS BANK — POS"
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
            firma_kodu="FP",
            firma_unvan="Fatura POS",
            firma_uid="fp",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()
        self._muh = patch("database.muhasebe_entegrasyon.muhasebe_hook", return_value=None)
        self._muh.start()

    def tearDown(self):
        self._muh.stop()
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_pos_hesaba_fatura_tahsilati_pos_valor_uretir(self):
        with get_session() as s:
            FinansService.fatura_tahsilati(
                s,
                "RAY-TEST-001",
                date(2026, 11, 11),
                Decimal("2115.00"),
                "KREDİ KARTIYLA TAHSİLAT",
                self.pos_adi,
                cari_id=self.musteri_id,
            )
        with get_session() as s:
            pv = list(s.scalars(select(PosValorKaydi).where(PosValorKaydi.belge_no == "RAY-TEST-001")).all())
            self.assertEqual(len(pv), 1)
            self.assertEqual(pv[0].durum, "BEKLIYOR")
            self.assertEqual(Decimal(str(pv[0].brut_tutar)), Decimal("2115.00"))
            self.assertEqual(int(pv[0].cari_id), self.musteri_id)
            turler = {
                h.hareket_turu
                for h in s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == "RAY-TEST-001")
                ).all()
            }
            self.assertIn("POS TAHSİLAT", turler)
            self.assertNotIn("FATURA TAHSİLATI", turler)
        liste = FinansService.pos_tahsilat_listele(limit=50)
        self.assertIn("RAY-TEST-001", {r.get("belge_no") for r in liste})

    def test_kasa_tahsilati_eski_yol(self):
        with get_session() as s:
            FinansService.fatura_tahsilati(
                s,
                "RAY-TEST-002",
                date(2026, 11, 11),
                Decimal("100.00"),
                "NAKİT / KASA",
                "Merkez Kasa",
                cari_id=self.musteri_id,
            )
        with get_session() as s:
            self.assertEqual(
                list(s.scalars(select(PosValorKaydi).where(PosValorKaydi.belge_no == "RAY-TEST-002")).all()),
                [],
            )
            h = s.scalar(
                select(FinansHareketi).where(
                    FinansHareketi.belge_no == "RAY-TEST-002",
                    FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
                )
            )
            self.assertIsNotNone(h)

    def test_geri_al_pos_valor_siler(self):
        with get_session() as s:
            FinansService.fatura_tahsilati(
                s,
                "RAY-TEST-003",
                date(2026, 11, 11),
                Decimal("50.00"),
                "KREDİ KARTIYLA TAHSİLAT",
                self.pos_adi,
                cari_id=self.musteri_id,
            )
            FinansService.fatura_tahsilatini_geri_al(s, "RAY-TEST-003")
        with get_session() as s:
            self.assertEqual(
                list(s.scalars(select(PosValorKaydi).where(PosValorKaydi.belge_no == "RAY-TEST-003")).all()),
                [],
            )
            self.assertEqual(
                list(s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == "RAY-TEST-003")).all()),
                [],
            )

    def test_eksik_valor_onar_eski_fatura_tahsilati(self):
        with get_session() as s:
            pos = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == self.pos_adi))
            s.add(
                SatisFaturasi(
                    fatura_no="RAY-TEST-004",
                    fatura_tarihi=date(2026, 11, 11),
                    vade_tarihi=date(2026, 11, 11),
                    cari_id=self.musteri_id,
                    depo="ANA DEPO",
                    durum="AÇIK",
                    onaylandi=True,
                )
            )
            s.add(
                FinansHareketi(
                    hesap_id=pos.id,
                    tarih=date(2026, 11, 11),
                    hareket_turu="FATURA TAHSİLATI",
                    belge_no="RAY-TEST-004",
                    tutar=Decimal("2115.00"),
                    aciklama="KREDİ KARTIYLA TAHSİLAT",
                )
            )
        ozet = FinansService.fatura_pos_tahsilat_eksik_valor_onar(dry_run=False, belge_no="RAY-TEST-004")
        self.assertEqual(ozet["onarilan_sayisi"], 1)
        with get_session() as s:
            pv = s.scalar(select(PosValorKaydi).where(PosValorKaydi.belge_no == "RAY-TEST-004"))
            self.assertIsNotNone(pv)
            self.assertEqual(pv.durum, "BEKLIYOR")
            turler = {
                h.hareket_turu
                for h in s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == "RAY-TEST-004")
                ).all()
            }
            self.assertIn("POS TAHSİLAT", turler)
            self.assertNotIn("FATURA TAHSİLATI", turler)


if __name__ == "__main__":
    unittest.main()
