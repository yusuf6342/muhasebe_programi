"""POS valör: iş günü hesabı, hedef mevduat, otomatik mahsup kapısı."""

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
    FinansService,
    is_gunu_ekle,
    valor_tarihi_hesapla,
)
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHesabi, PosValorKaydi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class IsGunuTest(unittest.TestCase):
    def test_cuma_arti_1_pazartesi(self):
        # 2026-10-30 Cuma → +1 iş günü = 2 Kasım Pazartesi
        self.assertEqual(is_gunu_ekle(date(2026, 10, 30), 1), date(2026, 11, 2))

    def test_takvim_vs_is(self):
        cuma = date(2026, 10, 30)
        self.assertEqual(valor_tarihi_hesapla(cuma, 1, is_gunu=False), date(2026, 10, 31))
        self.assertEqual(valor_tarihi_hesapla(cuma, 1, is_gunu=True), date(2026, 11, 2))


class PosValorHedefTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "pos_fx.db"
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
            firma = Firma(firma_kodu="POS", unvan="POS Test", aktif=True)
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
            musteri = Cari(cari_kodu="M001", unvan="POS Müşteri", cari_turu="Müşteri")
            s.add(musteri)
            banka = BankaKarti(
                banka_adi="TEST POS BANK",
                kk_komisyon_orani=Decimal("2"),
                pos_valor_gun=1,
                pos_hedef_hesap_turu="MEVDUAT",
                pos_valor_is_gunu=True,
                pos_otomatik_mahsup=False,
            )
            s.add(banka)
            s.flush()
            for alt, tur in (
                ("MEVDUAT", "BANKA"),
                ("KMH", "BANKA"),
                ("POS", "BANKA"),
            ):
                s.add(
                    FinansHesabi(
                        hesap_adi=f"TEST POS BANK — {alt}",
                        hesap_turu=tur,
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                    )
                )
            s.commit()
            self.banka_id = banka.id
            self.musteri_id = musteri.id
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
            firma_kodu="POS",
            firma_unvan="POS Test",
            firma_uid="pos",
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

    def test_tahsilat_hedef_mevduat_ve_is_gunu(self):
        # Cuma tahsilat (23 Eki) → valör Pazartesi 26 Eki, hedef mevduat
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 10, 23),
            "1000",
            cari_id=self.musteri_id,
        )
        self.assertEqual(r["valor_tarihi"], date(2026, 10, 26))
        with get_session() as s:
            pv = s.get(PosValorKaydi, r["kayit_id"])
            mevduat = s.scalar(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == self.banka_id,
                    FinansHesabi.alt_hesap_turu == "MEVDUAT",
                )
            )
            self.assertEqual(pv.hedef_hesap_id, mevduat.id)
            self.assertEqual(pv.kmh_hesap_id, mevduat.id)

    def test_otomatik_kapali_arkaplan_aktarmaz(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 10, 28),  # Çarşamba → valör Perşembe 29
            "500",
            cari_id=self.musteri_id,
        )
        # Valör geçmiş sayılsın
        with get_session() as s:
            pv = s.get(PosValorKaydi, r["kayit_id"])
            pv.valor_tarihi = date(2026, 10, 1)
            s.commit()
        sonuclar = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        self.assertEqual(sonuclar, [])
        with get_session() as s:
            self.assertEqual(s.get(PosValorKaydi, r["kayit_id"]).durum, "BEKLIYOR")
        # Manuel / zorla aktarır
        sonuclar = FinansService.pos_valor_vadesi_gelenleri_aktar(zorla=True)
        self.assertEqual(len(sonuclar), 1)
        with get_session() as s:
            self.assertEqual(s.get(PosValorKaydi, r["kayit_id"]).durum, "AKTARILDI")


if __name__ == "__main__":
    unittest.main()
