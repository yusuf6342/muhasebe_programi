"""İş panosu personel atama / filtre / geçmiş / atomiklik."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_is_panosu_"))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.personel_performans import PersonelIsGecmis, PersonelIsKaydi
from database.personel_performans_sema import schema_hazirla
from database.personel_performans_service import PersonelPerformansService
from database.personel_service import PersonelService
from database.session_manager import oturum
from database.user_audit import OturumGerekli


class IsPanosuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cin_is_db_")
        cls.db = Path(cls.tmp) / "test.db"
        cls.engine = create_engine(f"sqlite:///{cls.db.as_posix()}", future=True)
        Base.metadata.create_all(cls.engine)
        schema_hazirla(cls.engine)

    def setUp(self):
        self.sf = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        mock_cdb = MagicMock()
        mock_cdb.acik = True
        self._patches = [
            patch("database.personel_service.get_session", self._session_cm),
            patch("database.personel_performans_service.get_session", self._session_cm),
            patch("database.personel_service.schema_hazirla"),
            patch("database.personel_performans_service.schema_hazirla"),
            patch("database.personel_performans_sema.schema_hazirla"),
            patch("database.access.yetki_var", return_value=True),
            patch("database.access.yetki_zorunlu"),
            patch("database.access.yazma_zorunlu"),
            patch("database.access.aktif_firma_zorunlu"),
            patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
        ]
        for p in self._patches:
            p.start()
        oturum.user_id = 7
        oturum.kullanici_adi = "is_test_user"
        oturum.ad_soyad = "İş Test"
        oturum.role_kod = "YONETICI"
        oturum.permissions = set()
        if hasattr(oturum, "username"):
            delattr(oturum, "username")

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _session_cm(self):
        outer = self

        class CM:
            def __enter__(self):
                self.s = outer.sf()
                return self.s

            def __exit__(self, exc_type, exc, tb):
                try:
                    if exc_type is not None:
                        self.s.rollback()
                    else:
                        self.s.commit()
                except Exception:
                    self.s.rollback()
                    raise
                finally:
                    self.s.close()
                return False

        return CM()

    def _personel(self, kod, ad, soyad):
        return PersonelService.kaydet(
            {
                "kod": kod,
                "ad": ad,
                "soyad": soyad,
                "kimlik_turu": "DIGER",
                "calisma_durumu": "AKTIF",
                "donem": {"giris_tarihi": "2024-01-01", "gorev": "Depo"},
            }
        )

    def test_iki_personele_ayri_is(self):
        a = self._personel("ISP01", "Ali", "Bir")
        b = self._personel("ISP02", "Ali", "Iki")
        i1 = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Sipariş hazırla",
                "sorumlu_personel_id": a["id"],
                "gorev_alani": "HAZIRLAMA",
                "durum": "PLANLANDI",
                "hedef_tarih": "2026-10-20",
                "hedef_saat": "14:30",
            }
        )
        i2 = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Sevkiyat kontrol",
                "sorumlu_personel_id": b["id"],
                "gorev_alani": "SEVKIYAT",
                "durum": "BASLADI",
            }
        )
        self.assertEqual(i1["sorumlu_personel_id"], a["id"])
        self.assertEqual(i2["sorumlu_personel_id"], b["id"])
        self.assertIn("ISP01", i1["sorumlu_etiket"])
        self.assertIn("ISP02", i2["sorumlu_etiket"])
        # Yeniden aç
        g1 = PersonelPerformansService.is_getir(i1["id"])
        self.assertEqual(g1["sorumlu_personel_id"], a["id"])
        self.assertEqual(g1["hedef_saat"], "14:30")

    def test_filtre_ve_atanmamis(self):
        a = self._personel("ISP10", "Ayşe", "Filtre")
        PersonelPerformansService.is_kaydet(
            {
                "baslik": "Aktif iş",
                "sorumlu_personel_id": a["id"],
                "gorev_alani": "STOK",
                "durum": "PLANLANDI",
            }
        )
        # Eski sorumlusuz kayıt (doğrudan model)
        with self._session_cm() as s:
            s.add(
                PersonelIsKaydi(
                    baslik="Eski iş",
                    gorev_alani="FINANS",
                    durum="PLANLANDI",
                    sorumlu_personel_id=None,
                    olusturan="legacy",
                )
            )
        liste = PersonelPerformansService.is_panosu(atanmamis=True)
        self.assertTrue(any(x["baslik"] == "Eski iş" and x["atanmamis"] for x in liste))
        self.assertTrue(all(x["eksik_sorumlu"] for x in liste))
        filtre = PersonelPerformansService.is_panosu(personel_id=a["id"])
        self.assertTrue(all(x["sorumlu_personel_id"] == a["id"] for x in filtre))
        durum = PersonelPerformansService.is_panosu(durum="PLANLANDI", baslik_arama="Aktif")
        self.assertTrue(any(x["baslik"] == "Aktif iş" for x in durum))

    def test_sorumlu_degisikligi_gecmis(self):
        a = self._personel("ISP20", "Can", "A")
        b = self._personel("ISP21", "Can", "B")
        i = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Değişecek",
                "sorumlu_personel_id": a["id"],
                "gorev_alani": "SATIS",
                "durum": "PLANLANDI",
            }
        )
        PersonelPerformansService.is_kaydet(
            {
                "id": i["id"],
                "baslik": "Değişecek",
                "sorumlu_personel_id": b["id"],
                "gorev_alani": "SATIS",
                "durum": "BASLADI",
            }
        )
        gecmis = PersonelPerformansService.is_gecmis(i["id"])
        alanlar = {g["alan"] for g in gecmis}
        self.assertIn("sorumlu_personel_id", alanlar)
        self.assertIn("durum", alanlar)
        self.assertTrue(all(g["kullanici"] == "is_test_user" for g in gecmis))

    def test_personel_secmeden_hata(self):
        with self.assertRaises(ValueError) as cm:
            PersonelPerformansService.is_kaydet(
                {"baslik": "Boş sorumlu", "gorev_alani": "STOK", "durum": "PLANLANDI"}
            )
        self.assertIn("Sorumlu", str(cm.exception))

    def test_oturumsuz_sahte_kimlik_yok(self):
        oturum.user_id = None
        oturum.kullanici_adi = None
        with self.assertRaises(OturumGerekli):
            PersonelPerformansService.is_kaydet(
                {
                    "baslik": "X",
                    "sorumlu_personel_id": 1,
                    "gorev_alani": "STOK",
                }
            )

    def test_hata_atomik_rollback(self):
        a = self._personel("ISP30", "Roll", "Back")
        once = 0
        with self._session_cm() as s:
            once = s.scalar(select(func.count()).select_from(PersonelIsKaydi)) or 0
        with patch.object(
            PersonelPerformansService,
            "_is_gecmis_yaz",
            side_effect=ValueError("gecmis hata"),
        ):
            with self.assertRaises(ValueError):
                PersonelPerformansService.is_kaydet(
                    {
                        "baslik": "Atomik",
                        "sorumlu_personel_id": a["id"],
                        "gorev_alani": "STOK",
                        "durum": "PLANLANDI",
                    }
                )
        with self._session_cm() as s:
            sonra = s.scalar(select(func.count()).select_from(PersonelIsKaydi)) or 0
            g = s.scalar(select(func.count()).select_from(PersonelIsGecmis)) or 0
        self.assertEqual(sonra, once)

    def test_tamamlandi_prim_uretmez(self):
        a = self._personel("ISP40", "Prim", "Yok")
        i = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Bitti",
                "sorumlu_personel_id": a["id"],
                "gorev_alani": "SATIS",
                "durum": "TAMAMLANDI",
            }
        )
        self.assertEqual(i["durum"], "TAMAMLANDI")
        # Prim dönemi / pay oluşmamalı
        from database.models.personel_performans import PersonelPrimDonemi, PersonelPrimPay

        with self._session_cm() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(PersonelPrimDonemi)) or 0, 0)
            self.assertEqual(s.scalar(select(func.count()).select_from(PersonelPrimPay)) or 0, 0)

    def test_atanmis_eski_is_duzenlenebilir(self):
        a = self._personel("ISP50", "Eski", "Ata")
        with self._session_cm() as s:
            k = PersonelIsKaydi(
                baslik="Atanacak",
                gorev_alani="HAZIRLAMA",
                durum="ENGELLENDI",
                sorumlu_personel_id=None,
                dis_engel="Malzeme yok",
            )
            s.add(k)
            s.flush()
            kid = k.id
        g = PersonelPerformansService.is_getir(kid)
        self.assertTrue(g["atanmamis"])
        u = PersonelPerformansService.is_kaydet(
            {
                "id": kid,
                "baslik": "Atanacak",
                "sorumlu_personel_id": a["id"],
                "gorev_alani": "HAZIRLAMA",
                "durum": "BASLADI",
                "dis_engel": None,
            }
        )
        self.assertEqual(u["sorumlu_personel_id"], a["id"])
        self.assertFalse(u["atanmamis"])


if __name__ == "__main__":
    unittest.main()
