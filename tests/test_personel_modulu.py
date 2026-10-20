"""Personel / özlük / SGK ilk teslim — hedefli kabul kontrolleri."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_personel_"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.personel_sema import schema_hazirla
from database.personel_service import PersonelService, kimlik_dogrula
from database.personel_finans_service import PersonelFinansService
from database.personel_sgk_service import PersonelSgkService, son_tarih_hesapla
from database.personel_puantaj_service import yillik_izin_asgari_gun
from database.personel_belge_service import PersonelBelgeService, hassas_gorur
from database.models.personel import GIZLILIK_HASSAS_SAGLIK, Personel, PersonelGecmis
from database.session_manager import oturum
from database.user_audit import OturumGerekli
from sqlalchemy import func, select


class PersonelModulTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cin_personel_db_")
        cls.db = Path(cls.tmp) / "test.db"
        cls.engine = create_engine(f"sqlite:///{cls.db.as_posix()}", future=True)
        Base.metadata.create_all(cls.engine)
        schema_hazirla(cls.engine)

    def setUp(self):
        self.sf = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        mock_cdb = MagicMock()
        mock_cdb.acik = True
        mock_cdb._db_path = self.db
        mock_cdb._company_id = 1

        self._patches = [
            patch("database.personel_service.get_session", self._session_cm),
            patch("database.personel_finans_service.get_session", self._session_cm),
            patch("database.personel_sgk_service.get_session", self._session_cm),
            patch("database.personel_puantaj_service.get_session", self._session_cm),
            patch("database.personel_belge_service.get_session", self._session_cm),
            patch("database.personel_service.schema_hazirla"),
            patch("database.personel_finans_service.schema_hazirla"),
            patch("database.personel_sgk_service.schema_hazirla"),
            patch("database.personel_puantaj_service.schema_hazirla"),
            patch("database.personel_belge_service.schema_hazirla"),
            patch("database.personel_arsiv.company_db", mock_cdb),
            patch("database.access.yetki_var", return_value=True),
            patch("database.access.yetki_zorunlu"),
            patch("database.access.yazma_zorunlu"),
            patch("database.access.aktif_firma_zorunlu"),
            patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
        ]
        for p in self._patches:
            p.start()
        oturum.user_id = 42
        oturum.kullanici_adi = "test_kullanici"
        oturum.ad_soyad = "Test Kullanıcı"
        oturum.role_kod = "FINANS"
        oturum.permissions = {
            "personel_goruntuleme",
            "personel_duzenleme",
            "personel_finans_goruntuleme",
            "personel_finans_duzenleme",
            "personel_sgk_goruntuleme",
            "personel_sgk_duzenleme",
        }
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

    def test_kimlik_tckn_ve_zorunlu_degil(self):
        self.assertEqual(kimlik_dogrula("TCKN", "10000000146"), "10000000146")
        self.assertIsNone(kimlik_dogrula("DIGER", None))
        with self.assertRaises(ValueError):
            kimlik_dogrula("TCKN", "123")

    def test_kart_kayit_ve_yeni_donem(self):
        kart = PersonelService.kaydet(
            {
                "kod": "P9001",
                "ad": "Test",
                "soyad": "Personel",
                "kimlik_turu": "DIGER",
                "calisma_durumu": "AKTIF",
                "donem": {
                    "giris_tarihi": "2024-01-15",
                    "gorev": "Depo",
                    "sube": "Merkez",
                    "ucret": {
                        "ucret_turu": "NET",
                        "tutar": "30000",
                        "gecerli_baslangic": "2024-01-15",
                    },
                },
            }
        )
        self.assertEqual(kart["kod"], "P9001")
        self.assertTrue(kart["donemler"])
        self.assertEqual(kart["olusturan"], "test_kullanici")
        with self._session_cm() as s:
            gecmis = s.scalars(
                select(PersonelGecmis).where(PersonelGecmis.personel_id == kart["id"])
            ).all()
            self.assertTrue(any(g.alan == "olusturma" for g in gecmis))
            self.assertTrue(all(g.kullanici == "test_kullanici" for g in gecmis))
        PersonelService.kaydet(
            {
                "kod": "P9001",
                "ad": "Test",
                "soyad": "Guncel",
                "kimlik_turu": "DIGER",
                "calisma_durumu": "AKTIF",
            },
            personel_id=kart["id"],
        )
        kart_g = PersonelService.getir(kart["id"])
        self.assertEqual(kart_g["soyad"], "Guncel")
        self.assertEqual(kart_g["guncelleyen"], "test_kullanici")
        PersonelService.yeni_calisma_donemi(kart["id"], "2026-03-01", gorev="Satış")
        kart2 = PersonelService.getir(kart["id"])
        aktif = [d for d in kart2["donemler"] if d["aktif"]]
        self.assertEqual(len(aktif), 1)
        self.assertEqual(aktif[0]["giris_tarihi"], "2026-03-01")
        self.assertEqual(aktif[0]["ucretler"], [])
        with self._session_cm() as s:
            yeniden = s.scalars(
                select(PersonelGecmis).where(
                    PersonelGecmis.personel_id == kart["id"],
                    PersonelGecmis.alan == "yeni_calisma_donemi",
                )
            ).all()
            self.assertEqual(len(yeniden), 1)
            self.assertEqual(yeniden[0].kullanici, "test_kullanici")

    def test_oturumsuz_kayit_ve_admin_yok(self):
        oturum.user_id = None
        oturum.kullanici_adi = None
        oturum.ad_soyad = None
        with self.assertRaises(OturumGerekli):
            PersonelService.kaydet(
                {
                    "kod": "P_NOAUTH",
                    "ad": "X",
                    "soyad": "Y",
                    "kimlik_turu": "DIGER",
                }
            )
        with self._session_cm() as s:
            n = s.scalar(select(func.count()).select_from(Personel).where(Personel.kod == "P_NOAUTH"))
            self.assertEqual(n, 0)

    def test_hata_sonrasi_kismi_kayit_yok(self):
        with patch.object(
            PersonelService, "_donem_kaydet", side_effect=ValueError("donem hata")
        ):
            with self.assertRaises(ValueError):
                PersonelService.kaydet(
                    {
                        "kod": "P_ROLL",
                        "ad": "Roll",
                        "soyad": "Back",
                        "kimlik_turu": "DIGER",
                        "donem": {"giris_tarihi": "2026-01-01"},
                    }
                )
        with self._session_cm() as s:
            n = s.scalar(select(func.count()).select_from(Personel).where(Personel.kod == "P_ROLL"))
            self.assertEqual(n, 0)
            g = s.scalar(
                select(func.count())
                .select_from(PersonelGecmis)
                .where(PersonelGecmis.yeni_deger.like("P_ROLL%"))
            )
            self.assertEqual(g, 0)

    def test_maas_avans_kismi_odeme(self):
        kart = PersonelService.kaydet(
            {
                "kod": "P9002",
                "ad": "Ayşe",
                "soyad": "Yılmaz",
                "kimlik_turu": "DIGER",
                "donem": {
                    "giris_tarihi": "2025-01-01",
                    "ucret": {"tutar": "30000", "gecerli_baslangic": "2025-01-01"},
                },
            }
        )
        donem_id = kart["donemler"][0]["id"]
        h = PersonelFinansService.hakedis_kaydet(
            {
                "personel_id": kart["id"],
                "donem_id": donem_id,
                "yil": 2026,
                "ay": 10,
                "temel_ucret": 30000,
                "net_hakedis": 30000,
            }
        )
        PersonelFinansService.hakedis_onayla(h["id"])
        PersonelFinansService.avans_kaydet(
            {"personel_id": kart["id"], "tutar": 5000, "belge_turu": "KASA", "belge_id": 1}
        )
        PersonelFinansService.avans_mahsup(
            {"personel_id": kart["id"], "tutar": 5000, "hakedis_id": h["id"]}
        )
        PersonelFinansService.maas_odeme_kaydet(
            {
                "personel_id": kart["id"],
                "hakedis_id": h["id"],
                "tutar": 15000,
                "belge_turu": "KASA",
                "belge_id": 2,
            }
        )
        oz = PersonelFinansService.ay_ozeti(kart["id"], 2026, 10)
        self.assertAlmostEqual(oz["onayli_net_hakedis"], 30000)
        self.assertAlmostEqual(oz["yapilan_maas_odemesi"], 15000)
        self.assertAlmostEqual(oz["kalan_odeme"], 10000)

    def test_mphb_tek_ana_kayit_ve_taslak_onay_degil(self):
        PersonelSgkService.kaydet(
            {
                "islem_turu": "MPHB",
                "isyeri_kodu": "ISY1",
                "donem_yil": 2026,
                "donem_ay": 9,
                "nitelik": "ASIL",
                "durum": "HAZIRLANDI",
            }
        )
        with self.assertRaises(ValueError):
            PersonelSgkService.kaydet(
                {
                    "islem_turu": "MPHB",
                    "isyeri_kodu": "ISY1",
                    "donem_yil": 2026,
                    "donem_ay": 9,
                    "nitelik": "ASIL",
                }
            )
        with self.assertRaises(ValueError):
            PersonelSgkService.kaydet(
                {
                    "islem_turu": "MPHB",
                    "isyeri_kodu": "X",
                    "donem_yil": 2026,
                    "donem_ay": 1,
                    "durum": "GONDERILDI",
                }
            )
        islem = PersonelSgkService.kaydet(
            {
                "islem_turu": "MPHB",
                "isyeri_kodu": "ISY2",
                "donem_yil": 2026,
                "donem_ay": 8,
                "durum": "HAZIRLANDI",
            }
        )
        with self.assertRaises(ValueError):
            PersonelSgkService.durum_guncelle(islem["id"], "RESMI_ONAY_BELGESI_KAYDEDILDI")

    def test_son_tarih_kaynakli(self):
        with patch("database.personel_sgk_service.get_session", self._session_cm), patch(
            "database.personel_sgk_service.schema_hazirla"
        ):
            st = son_tarih_hesapla("MPHB", date(2026, 9, 1), donem_yil=2026, donem_ay=9)
        self.assertEqual(st["son_tarih"], date(2026, 10, 26))
        self.assertIn("SGK", st["kaynak"])

    def test_yillik_izin_parametre(self):
        with patch("database.personel_puantaj_service.get_session", self._session_cm), patch(
            "database.personel_puantaj_service.schema_hazirla"
        ):
            r = yillik_izin_asgari_gun(3, 30)
            r2 = yillik_izin_asgari_gun(3, 55)
        self.assertEqual(r["gun"], 14)
        self.assertEqual(r2["gun"], 20)
        self.assertIn("[5]", r["kural_kaynak"])

    def test_hassas_yetki_yonetici_otomatik_degil(self):
        oturum.role_kod = "YONETICI"
        oturum.permissions = {"personel_goruntuleme", "personel_duzenleme"}
        self.assertFalse(hassas_gorur(GIZLILIK_HASSAS_SAGLIK))
        oturum.permissions.add("personel_hassas_saglik")
        self.assertTrue(hassas_gorur(GIZLILIK_HASSAS_SAGLIK))

    def test_belge_yukle_arsiv(self):
        kart = PersonelService.kaydet(
            {
                "kod": "P9003",
                "ad": "Belge",
                "soyad": "Test",
                "kimlik_turu": "DIGER",
                "donem": {"giris_tarihi": "2025-06-01"},
            }
        )
        turler = PersonelBelgeService.turler()
        sozlesme = next(t for t in turler if t["kod"] == "SOZLESME")
        pdf = Path(self.tmp) / "sozlesme.pdf"
        pdf.write_bytes(b"%PDF-1.4 test personel belgesi")
        r = PersonelBelgeService.yukle(kart["id"], sozlesme["id"], str(pdf), belge_adi="Sözleşme")
        self.assertIn("belge_id", r)
        veri, _ad, _mime = PersonelBelgeService.dosya_oku(r["surum_id"])
        self.assertTrue(veri.startswith(b"%PDF"))
        eksik = PersonelBelgeService.eksik_listesi(kart["id"])
        self.assertFalse(any(e["tur_kod"] == "ADLI_SICIL" for e in eksik))


if __name__ == "__main__":
    unittest.main()
