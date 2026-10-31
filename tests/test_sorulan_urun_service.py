"""Sorulan ürün hızlı kayıt — stok hareketi üretmez."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import _aktif_engine_bagla, company_db
from database.models.sorulan_urun import SorulanUrunAday, SorulanUrunTalep
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class SorulanUrunServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sorulan_")
        cls.db_path = Path(cls._tmpdir.name) / "firma.db"
        eng = create_engine(
            f"sqlite:///{cls.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 42
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
            company_id=42,
            firma_kodu="TST",
            firma_unvan="Sorulan Test",
            firma_uid="sorulan-test",
            db_path=str(cls.db_path),
        )
        cls._donem_patch = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        cls._donem_patch.start()
        from database.sorulan_urun_service import SorulanUrunService

        SorulanUrunService.ensure_schema(eng)
        cls.svc = SorulanUrunService
        cls._engine = eng

    @classmethod
    def tearDownClass(cls):
        cls._donem_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        try:
            cls._engine.dispose()
        except Exception:
            pass
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def test_hizli_kaydet_ve_birlestir(self):
        r1 = self.svc.hizli_kaydet(
            {"urun_adi": "70 cm frenli ray", "talep_nedeni": "CESITTE_YOK", "musteri_adi": "Ali"}
        )
        r2 = self.svc.hizli_kaydet(
            {"urun_adi": "70 cm  frenli  ray", "talep_nedeni": "STOKTA_YOK", "musteri_adi": "Veli"}
        )
        self.assertEqual(r1["aday_id"], r2["aday_id"])
        ozet = self.svc.urun_ozet_listesi()
        self.assertTrue(any(o["id"] == r1["aday_id"] and o["sorulma_sayisi"] >= 2 for o in ozet))
        talepler = self.svc.talepler(r1["aday_id"])
        self.assertGreaterEqual(len(talepler), 2)

    def test_urun_adi_veya_tarif_zorunlu(self):
        with self.assertRaises(ValueError):
            self.svc.hizli_kaydet({"urun_adi": "  ", "talep_nedeni": "CESITTE_YOK"})
        r = self.svc.hizli_kaydet(
            {
                "urun_adi": "",
                "musteri_tarifi": "Gri plastik kapak, vida delikli",
                "talep_nedeni": "CESITTE_YOK",
                "musteri_adi": "Ayşe",
            }
        )
        self.assertTrue(r["aday_id"])

    def test_tekrar_sorulma_bagimsiz_artmaz(self):
        r = self.svc.hizli_kaydet(
            {"urun_adi": "Ray kapak X", "talep_nedeni": "CESITTE_YOK", "musteri_adi": "Can"}
        )
        o1 = next(o for o in self.svc.urun_ozet_listesi() if o["id"] == r["aday_id"])
        self.svc.tekrar_soruldu(r["talep_id"], notlar="Tekrar sordu")
        o2 = next(o for o in self.svc.urun_ozet_listesi() if o["id"] == r["aday_id"])
        self.assertEqual(o2["bagimsiz_talep"], o1["bagimsiz_talep"])
        self.assertEqual(o2["toplam_sorulma"], o1["toplam_sorulma"] + 1)
        talepler = self.svc.talepler(r["aday_id"])
        self.assertEqual(len(talepler), 1)
        self.assertEqual(talepler[0]["tekrar_sayisi"], 1)

    def test_gecmis_sorulma_tarihi(self):
        from datetime import date, timedelta

        eski = date.today() - timedelta(days=10)
        r = self.svc.hizli_kaydet(
            {
                "urun_adi": "Eski talep ürün",
                "talep_nedeni": "CESITTE_YOK",
                "talep_tarihi": eski,
                "musteri_adi": "Deniz",
            }
        )
        t = self.svc.talepler(r["aday_id"])[0]
        self.assertEqual(t["tarih_iso"], eski.isoformat())
        with self.assertRaises(ValueError):
            self.svc.hizli_kaydet(
                {
                    "urun_adi": "Gelecek yasak",
                    "talep_nedeni": "CESITTE_YOK",
                    "talep_tarihi": date.today() + timedelta(days=1),
                }
            )


if __name__ == "__main__":
    unittest.main()
