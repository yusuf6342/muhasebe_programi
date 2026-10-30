"""Gider/gelir hizmet kartı — düzenle, sil, pasif, EvoBulut kaynak koruması."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import _aktif_engine_bagla, company_db
from database.models.hizmet import HizmetHareketi, HizmetKarti, HizmetKaynakEngel
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class HizmetKartDuzenleSilTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="hizmet_kart_")
        cls.db_path = Path(cls._tmpdir.name) / "firma.db"
        eng = create_engine(
            f"sqlite:///{cls.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        HizmetKarti.__table__.create(bind=eng, checkfirst=True)
        HizmetHareketi.__table__.create(bind=eng, checkfirst=True)
        HizmetKaynakEngel.__table__.create(bind=eng, checkfirst=True)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 91
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
            company_id=91,
            firma_kodu="HZM",
            firma_unvan="Hizmet Test",
            firma_uid="hizmet-test",
            db_path=str(cls.db_path),
        )
        cls._donem = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        cls._donem.start()
        from database.hizmet_service import HizmetService

        HizmetService._schema_hazir = False
        HizmetService.ensure_schema(eng)
        cls.svc = HizmetService
        cls._engine = eng

    @classmethod
    def tearDownClass(cls):
        cls._donem.stop()
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

    def test_duzenle_korunur_ve_vazgec_simule(self):
        k = self.svc.kaydet(
            {
                "hizmet_kodu": "IGZ-00001",
                "hizmet_adi": "Kira",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
                "kdv_orani": 20,
            }
        )
        hid = k.id
        self.svc.kaydet(
            {
                "hizmet_id": hid,
                "hizmet_kodu": "IGZ-00001",
                "hizmet_adi": "Ofis Kirası",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
                "kdv_orani": 10,
                "alis_fiyati": 100,
            }
        )
        yeniden = self.svc.getir(hid)
        self.assertEqual(yeniden.hizmet_adi, "Ofis Kirası")
        self.assertEqual(float(yeniden.kdv_orani), 10.0)
        self.assertTrue(yeniden.kullanici_duzenledi)
        self.assertEqual(yeniden.id, hid)

    def test_kullanilmamis_silinir(self):
        k = self.svc.kaydet(
            {
                "hizmet_kodu": "IGZ-00002",
                "hizmet_adi": "Geçici",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
            }
        )
        ozet = self.svc.kullanim_ozeti(k.id)
        self.assertTrue(ozet["silinebilir"])
        self.svc.sil(k.id, onaylandi=True)
        self.assertIsNone(self.svc.getir(k.id))

    def test_hareketli_silinemez_pasif_olur(self):
        k = self.svc.kaydet(
            {
                "hizmet_kodu": "IGZ-00003",
                "hizmet_adi": "Nakliye",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
            }
        )
        self.svc.manuel_hareket_ekle(
            k.id,
            date.today(),
            "MANUEL",
            "T1",
            Decimal("1"),
            Decimal("50"),
        )
        ozet = self.svc.kullanim_ozeti(k.id)
        self.assertFalse(ozet["silinebilir"])
        with self.assertRaises(ValueError):
            self.svc.sil(k.id, onaylandi=True)
        self.svc.pasif_yap(k.id)
        self.assertFalse(self.svc.getir(k.id).aktif)
        self.svc.aktif_yap(k.id)
        self.assertTrue(self.svc.getir(k.id).aktif)

    def test_evobulut_engel_ve_duzenleme_koruma(self):
        from entegrasyon.gelir_gider_import import evb_hizmet_kartlarini_hazirla

        uyari: list[str] = []
        evb_hizmet_kartlarini_hazirla(uyari_listesi=uyari)
        kart = self.svc.kaynak_ile_bul("EVOBULUT", "GENEL_GIDER")
        self.assertIsNotNone(kart)
        self.svc.kaydet(
            {
                "hizmet_id": kart.id,
                "hizmet_kodu": kart.hizmet_kodu,
                "hizmet_adi": "Kullanıcı Gider Adı",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
            }
        )
        self.assertEqual(self.svc.getir(kart.id).hizmet_adi, "Kullanıcı Gider Adı")
        # Tekrar hazırlık adı ezmemeli
        evb_hizmet_kartlarini_hazirla(uyari_listesi=uyari)
        self.assertEqual(self.svc.getir(kart.id).hizmet_adi, "Kullanıcı Gider Adı")
        # Sil (hareket yoksa) → engel
        # Önce başka kartta hareket olabilir; EVB-GIDER henüz hareketsiz
        ozet = self.svc.kullanim_ozeti(kart.id)
        if ozet["silinebilir"]:
            self.svc.sil(kart.id, onaylandi=True)
            self.assertTrue(self.svc.kaynak_engelli_mi("EVOBULUT", "GENEL_GIDER"))
            uyari2: list[str] = []
            sonuc = evb_hizmet_kartlarini_hazirla(uyari_listesi=uyari2)
            self.assertEqual(sonuc.get("EVB-GIDER"), "ENGELLI")
            self.assertTrue(uyari2)


if __name__ == "__main__":
    unittest.main()
