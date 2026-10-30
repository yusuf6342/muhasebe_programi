"""Sorulan ürün — stok geldiğinde müşteri arama görevi (Aktivite tekilliği)."""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import _aktif_engine_bagla, company_db
from database.models.aktivite import Aktivite, AktiviteTekillik, AktiviteTuru
from database.models.sorulan_urun import SorulanUrunAday, SorulanUrunTalep
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class SorulanAramaGoreviTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sor_arama_")
        cls.db_path = Path(cls._tmpdir.name) / "firma.db"
        eng = create_engine(
            f"sqlite:///{cls.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        SorulanUrunAday.__table__.create(bind=eng, checkfirst=True)
        SorulanUrunTalep.__table__.create(bind=eng, checkfirst=True)
        AktiviteTuru.__table__.create(bind=eng, checkfirst=True)
        Aktivite.__table__.create(bind=eng, checkfirst=True)
        AktiviteTekillik.__table__.create(bind=eng, checkfirst=True)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 55
        company_db._db_path = cls.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=55,
            firma_kodu="ARM",
            firma_unvan="Arama Test",
            firma_uid="arama-test",
            db_path=str(cls.db_path),
        )
        cls._donem = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        cls._donem.start()
        from database.aktivite_service import AktiviteService
        from database.sorulan_urun_service import SorulanUrunService

        AktiviteService._schema_hazir = False
        AktiviteService.ensure_schema(eng)
        SorulanUrunService._schema_hazir = True
        cls.sorulan = SorulanUrunService
        cls.akt = AktiviteService
        cls._engine = eng

    @classmethod
    def tearDownClass(cls):
        cls._donem.stop()
        oturum.clear()
        try:
            company_db.close()
        except Exception:
            pass
        company_db._engine = None
        company_db._session_factory = None
        company_db._db_path = None
        try:
            cls._engine.dispose()
        except Exception:
            pass
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def test_bilinen_musteri_gorev_olustur_ve_tekil(self):
        r = self.sorulan.hizli_kaydet(
            {
                "urun_adi": "Ray 50 cm",
                "talep_nedeni": "STOKTA_YOK",
                "musteri_adi": "Ayşe",
                "telefon": "05321234567",
                "stok_id": 101,
            }
        )
        s1 = self.sorulan.stok_geldiginde_degerlendir(
            stok_id=101,
            mevcut_miktar=Decimal("12"),
            olay_anahtar="TEST1",
        )
        self.assertEqual(s1["olusturulan"], 1)
        self.assertEqual(s1["atlanan"], 0)
        s2 = self.sorulan.stok_geldiginde_degerlendir(
            stok_id=101,
            mevcut_miktar=Decimal("15"),
            olay_anahtar="TEST1_RETRY",
        )
        self.assertEqual(s2["olusturulan"], 0)
        self.assertEqual(s2["guncellenen"], 1)
        mevcut = self.akt.kaynak_ile_bul(
            kaynak_belge_tur="SORULAN_TALEP",
            kaynak_belge_id=r["talep_id"],
            tur_kod="MUSTERI_ARAMASI",
        )
        self.assertIsNotNone(mevcut)
        talepler = self.sorulan.talepler(r["aday_id"])
        self.assertTrue(any(t["durum"] == "ARAMA_BEKLIYOR" for t in talepler))

    def test_anonim_telefonsuz_gorev_yok(self):
        self.sorulan.hizli_kaydet(
            {
                "urun_adi": "Ray anonim",
                "talep_nedeni": "CESITTE_YOK",
                "stok_id": 202,
            }
        )
        s = self.sorulan.stok_geldiginde_degerlendir(
            stok_id=202,
            mevcut_miktar=Decimal("5"),
        )
        self.assertEqual(s["olusturulan"], 0)
        self.assertGreaterEqual(s["atlanan"], 1)

    def test_stok_sifir_yeni_gorev_yok(self):
        r = self.sorulan.hizli_kaydet(
            {
                "urun_adi": "Ray sifir",
                "talep_nedeni": "STOKTA_YOK",
                "musteri_adi": "Veli",
                "telefon": "05551112233",
                "stok_id": 303,
            }
        )
        s = self.sorulan.stok_geldiginde_degerlendir(
            stok_id=303,
            mevcut_miktar=Decimal("0"),
        )
        self.assertEqual(s["olusturulan"], 0)
        mevcut = self.akt.kaynak_ile_bul(
            kaynak_belge_tur="SORULAN_TALEP",
            kaynak_belge_id=r["talep_id"],
            tur_kod="MUSTERI_ARAMASI",
        )
        self.assertIsNone(mevcut)

    def test_aktivite_ertele_son_tarih_korunur(self):
        from datetime import date, timedelta

        kayit = self.akt.kaydet(
            {
                "konu": "Ertele deneme",
                "tur_kod": "MUSTERI_ARAMASI",
                "plan_tarih": date.today(),
                "durum": "ACIK",
            }
        )
        yeni = date.today() + timedelta(days=3)
        out = self.akt.ertele(kayit["id"], yeni_tarih=yeni, gerekce="müşteri yok")
        self.assertEqual(out["plan_tarih"], yeni)
        self.assertEqual(out["son_tarih"], date.today())

    def test_arama_sonucu_kaydet_satis_dogurmaz(self):
        r = self.sorulan.hizli_kaydet(
            {
                "urun_adi": "Ray sonuc",
                "talep_nedeni": "STOKTA_YOK",
                "musteri_adi": "Zeynep",
                "telefon": "05339998877",
            }
        )
        out = self.sorulan.arama_sonucu_kaydet(
            r["talep_id"], sonuc_kod="ULASILDI", notlar="fiyat konuşuldu"
        )
        self.assertEqual(out["sonuc"], "ULASILDI")
        self.assertEqual(out["durum"], "TAKIPTE")
        vaz = self.sorulan.arama_sonucu_kaydet(r["talep_id"], sonuc_kod="VAZGECTI")
        self.assertEqual(vaz["durum"], "IPTAL")


if __name__ == "__main__":
    unittest.main()
