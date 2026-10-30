"""Aktivite kaydet / tamamla — stok-finans üretmez."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import _aktif_engine_bagla, company_db
from datetime import date

from database.models.aktivite import (
    Aktivite,
    AktiviteSefer,
    AktiviteSeferDurak,
    AktiviteTekillik,
    AktiviteTuru,
)
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class AktiviteServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="akt_")
        cls.db_path = Path(cls._tmpdir.name) / "firma.db"
        eng = create_engine(
            f"sqlite:///{cls.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        AktiviteTuru.__table__.create(bind=eng, checkfirst=True)
        Aktivite.__table__.create(bind=eng, checkfirst=True)
        AktiviteTekillik.__table__.create(bind=eng, checkfirst=True)
        AktiviteSefer.__table__.create(bind=eng, checkfirst=True)
        AktiviteSeferDurak.__table__.create(bind=eng, checkfirst=True)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 77
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
            company_id=77,
            firma_kodu="AKT",
            firma_unvan="Aktivite Test",
            firma_uid="akt-test",
            db_path=str(cls.db_path),
        )
        cls._donem = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        cls._donem.start()
        from database.aktivite_service import AktiviteService

        AktiviteService._schema_hazir = False
        AktiviteService.ensure_schema(eng)
        cls.svc = AktiviteService
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
            # Windows: WAL dosyası kısa süre kilitli kalabilir
            pass

    def test_kaydet_ve_tamamla(self):
        turler = self.svc.tur_listesi()
        self.assertTrue(turler)
        kayit = self.svc.kaydet(
            {
                "konu": "Test arama",
                "tur_kod": turler[0]["kod"],
                "teslimat_turu": "BELIRLENMEDI",
                "durum": "ACIK",
            }
        )
        self.assertIn("id", kayit)
        self.svc.tamamla(int(kayit["id"]))
        acik = self.svc.listele(filtre="acik")
        self.assertFalse(any(a["id"] == kayit["id"] for a in acik))

    def test_sefer_rota_test_verisi_195_dk(self):
        """Talimat: yol 105 + iş 90 = 195 dk; 09:00 → dönüş 12:15."""
        sefer = self.svc.sefer_olustur(
            {
                "sefer_tarih": date(2026, 10, 30),
                "sefer_no": 1,
                "arac_kod": "T1",
                "cikis_saat": "09:00",
            }
        )
        ids = []
        for i in range(6):
            a = self.svc.kaydet(
                {
                    "konu": f"Durak {i+1}",
                    "tur_kod": "SEVKIYAT",
                    "teslimat_turu": "KENDI_ARACIMIZ",
                    "adres_metin": f"Adres {i+1}",
                    "tahmini_sure_dk": 15,
                    "durum": "ACIK",
                }
            )
            ids.append(int(a["id"]))
            self.svc.sefer_durak_ekle(int(sefer["id"]), int(a["id"]))
        rota = self.svc.sefer_rota_hesapla(int(sefer["id"]), mod="TEST_VERISI")
        self.assertEqual(rota["tahmini_yol_dk"], 105)
        self.assertEqual(rota["tahmini_is_dk"], 90)
        self.assertEqual(rota["tahmini_toplam_dk"], 195)
        self.assertEqual(rota["tahmini_donus_saat"], "12:15")
        self.assertEqual(rota["rota_modu"], "TEST_VERISI")
        # Gerçek sağlayıcı iddiası yok
        self.assertIn("gerçek sağlayıcı değil", (rota.get("rota_ozet") or "").lower())

    def test_sefer_cift_yukleme_engel(self):
        s1 = self.svc.sefer_olustur(
            {"sefer_tarih": date(2026, 10, 31), "sefer_no": 1, "arac_kod": "A"}
        )
        s2 = self.svc.sefer_olustur(
            {"sefer_tarih": date(2026, 10, 31), "sefer_no": 2, "arac_kod": "B"}
        )
        a = self.svc.kaydet(
            {
                "konu": "Tek yük",
                "tur_kod": "SEVKIYAT",
                "adres_metin": "X",
                "durum": "ACIK",
            }
        )
        self.svc.sefer_durak_ekle(int(s1["id"]), int(a["id"]))
        with self.assertRaises(ValueError):
            self.svc.sefer_durak_ekle(int(s2["id"]), int(a["id"]))

    def test_harita_anahtar_yoksa_saglayici_hesap_yok(self):
        durum = self.svc.harita_saglayici_durumu()
        self.assertFalse(durum["bagli"])
        sefer = self.svc.sefer_olustur(
            {"sefer_tarih": date(2026, 11, 1), "sefer_no": 1}
        )
        a = self.svc.kaydet(
            {"konu": "Y", "tur_kod": "SEVKIYAT", "adres_metin": "A", "durum": "ACIK"}
        )
        self.svc.sefer_durak_ekle(int(sefer["id"]), int(a["id"]))
        with self.assertRaises(ValueError):
            self.svc.sefer_rota_hesapla(int(sefer["id"]), mod="SAGLAYICI")


if __name__ == "__main__":
    unittest.main()
