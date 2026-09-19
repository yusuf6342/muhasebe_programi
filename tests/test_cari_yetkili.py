"""Cari işletme yetkilisi — doğrulama, ana yetkili, doğum günü, soft-delete."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.cari import Cari, CariYetkili
from database.cari_yetkili_service import (
    CariYetkiliService,
    _dogrula,
    _sonraki_dogum,
    _yas,
)
from database.turkce_normalize import turkce_normalize


def _sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class YetkiliDogrulamaTest(unittest.TestCase):
    def test_ad_soyad_zorunlu(self):
        with self.assertRaises(ValueError):
            _dogrula({"ad": "", "soyad": "Yılmaz"}, hassas_izinli=True)
        with self.assertRaises(ValueError):
            _dogrula({"ad": "Ali", "soyad": "  "}, hassas_izinli=True)

    def test_email_bicim(self):
        with self.assertRaises(ValueError):
            _dogrula({"ad": "Ali", "soyad": "Yılmaz", "email": "yanlis"}, hassas_izinli=True)
        v = _dogrula({"ad": "Ali", "soyad": "Yılmaz", "email": "ali@ornek.com"}, hassas_izinli=True)
        self.assertEqual(v["email"], "ali@ornek.com")

    def test_telefon_bicim(self):
        with self.assertRaises(ValueError):
            _dogrula({"ad": "Ali", "soyad": "Yılmaz", "cep_telefonu": "123"}, hassas_izinli=True)
        v = _dogrula(
            {"ad": "Ali", "soyad": "Yılmaz", "cep_telefonu": "0532 111 22 33"},
            hassas_izinli=True,
        )
        self.assertEqual(v["cep_telefonu"], "0532 111 22 33")

    def test_dogum_gelecek_red(self):
        gelecek = date.today().replace(year=date.today().year + 1)
        with self.assertRaises(ValueError):
            _dogrula(
                {"ad": "Ali", "soyad": "Yılmaz", "dogum_tarihi": gelecek.strftime("%d.%m.%Y")},
                hassas_izinli=True,
            )

    def test_hassas_alan_yetkisiz_temizlenir(self):
        v = _dogrula(
            {
                "ad": "Ali",
                "soyad": "Yılmaz",
                "dogum_tarihi": "01.01.1990",
                "ozel_notlar": "gizli",
                "pazarlama_izni": True,
            },
            hassas_izinli=False,
        )
        self.assertIsNone(v["dogum_tarihi"])
        self.assertIsNone(v["ozel_notlar"])
        self.assertFalse(v["pazarlama_izni"])

    def test_ad_soyad_norm(self):
        v = _dogrula({"ad": "Çiğdem", "soyad": "Öztürk"}, hassas_izinli=True)
        self.assertEqual(v["ad_soyad_norm"], turkce_normalize("Çiğdem Öztürk"))


class DogumGunuHesapTest(unittest.TestCase):
    def test_yas(self):
        self.assertEqual(_yas(date(2000, 1, 1), date(2026, 1, 1)), 26)
        self.assertEqual(_yas(date(2000, 6, 1), date(2026, 1, 1)), 25)

    def test_sonraki_bugun(self):
        bugun = date(2026, 3, 15)
        self.assertEqual(_sonraki_dogum(date(1990, 3, 15), bugun), bugun)

    def test_sonraki_yil_basi(self):
        bugun = date(2026, 12, 30)
        self.assertEqual(_sonraki_dogum(date(1990, 1, 2), bugun), date(2027, 1, 2))

    def test_29_subat(self):
        bugun = date(2026, 2, 1)  # 2026 artık yıl değil
        self.assertEqual(_sonraki_dogum(date(2000, 2, 29), bugun), date(2026, 2, 28))


class CariYetkiliCrudTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        import database.database as db
        import database.cari_yetkili_service as svc
        import database.search_service as ss

        self._patches = []
        for mod in (db, svc, ss):
            self._patches.append((mod, getattr(mod, "get_session", None)))

        SessionLocal = self.Session

        class _Ctx:
            def __enter__(self):
                self.s = SessionLocal()
                return self.s

            def __exit__(self, *a):
                self.s.commit()
                self.s.close()

        for mod, _ in self._patches:
            if hasattr(mod, "get_session"):
                mod.get_session = lambda: _Ctx()

        self._perm = patch("database.cari_yetkili_service.yetki_var", return_value=True)
        self._perm_z = patch("database.cari_yetkili_service.yetki_zorunlu", return_value=None)
        self._yaz = patch("database.cari_yetkili_service.yazma_zorunlu", return_value=None)
        self._audit = patch("database.cari_yetkili_service.audit_document", return_value=None)
        self._perm.start()
        self._perm_z.start()
        self._yaz.start()
        self._audit.start()

        with self.Session() as s:
            m = Cari(
                cari_kodu="M-YET",
                unvan="Yetkili Test Müşteri",
                cari_turu="Müşteri",
                aktif=True,
                is_deleted=False,
            )
            t = Cari(
                cari_kodu="T-YET",
                unvan="Yetkili Test Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
                is_deleted=False,
            )
            s.add_all([m, t])
            s.commit()
            self.musteri_id = m.id
            self.tedarikci_id = t.id

    def tearDown(self):
        self._perm.stop()
        self._perm_z.stop()
        self._yaz.stop()
        self._audit.stop()
        for mod, orig in self._patches:
            if orig is not None:
                mod.get_session = orig
        self.engine.dispose()

    def test_coklu_yetkili_musteri_tedarikci(self):
        a = CariYetkiliService.ekle(
            self.musteri_id,
            {"ad": "Ayşe", "soyad": "Demir", "cep_telefonu": "05320001111", "ana_yetkili": True},
        )
        b = CariYetkiliService.ekle(
            self.musteri_id,
            {"ad": "Mehmet", "soyad": "Kaya", "email": "m@ornek.com"},
        )
        c = CariYetkiliService.ekle(
            self.tedarikci_id,
            {"ad": "Can", "soyad": "Öz", "ana_yetkili": True},
        )
        self.assertTrue(a["ana_yetkili"])
        self.assertFalse(b["ana_yetkili"])
        liste_m = CariYetkiliService.listele(self.musteri_id)
        self.assertEqual(len(liste_m), 2)
        liste_t = CariYetkiliService.listele(self.tedarikci_id)
        self.assertEqual(len(liste_t), 1)
        self.assertEqual(liste_t[0]["id"], c["id"])

    def test_ana_yetkili_tek(self):
        a = CariYetkiliService.ekle(
            self.musteri_id, {"ad": "Bir", "soyad": "Kişi", "ana_yetkili": True}
        )
        b = CariYetkiliService.ekle(
            self.musteri_id, {"ad": "İki", "soyad": "Kişi", "ana_yetkili": True}
        )
        liste = CariYetkiliService.listele(self.musteri_id)
        ana_sayisi = sum(1 for k in liste if k["ana_yetkili"])
        self.assertEqual(ana_sayisi, 1)
        self.assertTrue(b["ana_yetkili"])
        guncel_a = next(k for k in liste if k["id"] == a["id"])
        self.assertFalse(guncel_a["ana_yetkili"])

    def test_mukerrer_ad_soyad(self):
        CariYetkiliService.ekle(self.musteri_id, {"ad": "Ali", "soyad": "Veli"})
        with self.assertRaises(ValueError):
            CariYetkiliService.ekle(self.musteri_id, {"ad": "ali", "soyad": "VELİ"})

    def test_soft_delete(self):
        y = CariYetkiliService.ekle(self.musteri_id, {"ad": "Sil", "soyad": "Inecek"})
        CariYetkiliService.sil(y["id"], fiziksel=False)
        aktifler = CariYetkiliService.listele(self.musteri_id, pasifler_dahil=True)
        self.assertEqual(len(aktifler), 0)
        with self.Session() as s:
            kayit = s.get(CariYetkili, y["id"])
            self.assertTrue(kayit.is_deleted)
            self.assertFalse(kayit.aktif)

    def test_dogum_gunu_sorgusu(self):
        bugun = date.today()
        CariYetkiliService.ekle(
            self.musteri_id,
            {
                "ad": "Dogum",
                "soyad": "Yakin",
                "dogum_tarihi": bugun.strftime("%d.%m.%Y"),
                "dogum_gunu_hatirlat": True,
            },
        )
        with patch.object(CariYetkiliService, "hassas_izinli", return_value=True):
            sonuc = CariYetkiliService.dogum_gunleri(gun=7)
        self.assertTrue(any(r["ad_soyad"] == "Dogum Yakin" for r in sonuc))
        self.assertEqual(sonuc[0]["gun_kaldi"], 0)

    def test_yetkili_arama_ids(self):
        CariYetkiliService.ekle(
            self.musteri_id,
            {"ad": "Zeynep", "soyad": "Şahin", "cep_telefonu": "05551234567"},
        )
        ids = CariYetkiliService.cari_ids_yetkili_arama(["zeynep", "sahin"])
        self.assertIn(self.musteri_id, ids)
        ids2 = CariYetkiliService.cari_ids_yetkili_arama(["05551234567"])
        self.assertIn(self.musteri_id, ids2)


if __name__ == "__main__":
    unittest.main()
