"""Teklif ürün adı araması — normalize, min 3 harf, contains, öncelik."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokFiyati, StokKarti
from database.stok_service import StokService
from database.turkce_normalize import (
    arama_like_varyantlari,
    kelime_basi_eslesme,
    turkce_normalize,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class TestTurkceNormalize(unittest.TestCase):
    def test_i_dot_fold(self):
        self.assertEqual(turkce_normalize("VİD"), turkce_normalize("vid"))
        self.assertEqual(turkce_normalize("I"), "i")
        self.assertEqual(turkce_normalize("ı"), "i")

    def test_cekmece(self):
        self.assertIn(turkce_normalize("cek"), turkce_normalize("Çekmece Rayı"))
        self.assertTrue(turkce_normalize("Çekmece").find(turkce_normalize("cekmece")) >= 0)

    def test_gonye(self):
        self.assertIn(turkce_normalize("gon"), turkce_normalize("Gönye"))
        self.assertIn(turkce_normalize("gonye"), turkce_normalize("Gönye 30cm"))

    def test_contains_orta(self):
        ad = "Selectron 3.5x50 Sunta Vidası"
        for parca in ("sel", "lect", "3.5", "5x5", "sun", "nta", "vida"):
            self.assertIn(turkce_normalize(parca), turkce_normalize(ad), msg=parca)

    def test_like_varyantlari_parametre(self):
        v = arama_like_varyantlari("cek")
        self.assertTrue(any("çek" in x.lower() or "cek" in x.lower() for x in v))
        self.assertTrue(all(x.startswith("%") and x.endswith("%") for x in v))

    def test_kelime_basi(self):
        self.assertTrue(kelime_basi_eslesme("Sunta Vidası", "vid"))
        self.assertTrue(kelime_basi_eslesme("Selectron Vida", "sel"))


class TestTeklifUrunAra(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_teklif_ara.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="TAR", unvan="Ara Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                )
            )
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 99
        StokService._teklif_arama_onbellek.clear()

        self.kod_prefix = "TARA01"
        with Session() as session:
            ornekler = [
                (f"{self.kod_prefix}-1", "Selectron 3.5x50 Sunta Vidası", True),
                (f"{self.kod_prefix}-2", "Çekmece Rayı 450mm", True),
                (f"{self.kod_prefix}-3", "Gönye Alüminyum", True),
                (f"{self.kod_prefix}-4", "Pasif Ray Ürün", False),
                (f"{self.kod_prefix}-5", "Menfez Kapak", True),
            ]
            for kod, ad, aktif in ornekler:
                session.add(
                    StokKarti(
                        stok_kodu=kod,
                        stok_adi=ad,
                        birim="Adet",
                        aktif=aktif,
                        is_deleted=False,
                        kdv_orani=Decimal("20"),
                    )
                )
            session.flush()
            s1 = session.scalar(
                select(StokKarti).where(StokKarti.stok_kodu == f"{self.kod_prefix}-1")
            )
            session.add(
                StokFiyati(
                    stok_id=s1.id,
                    fiyat_adi="SATIŞ FİYATI 1",
                    tutar=Decimal("10"),
                    para_birimi="TL",
                )
            )
            session.add(
                StokFiyati(
                    stok_id=s1.id,
                    fiyat_adi="ALIŞ FİYATI",
                    tutar=Decimal("5"),
                    para_birimi="TL",
                )
            )
            session.commit()

    def tearDown(self):
        StokService._teklif_arama_onbellek.clear()
        try:
            if getattr(company_db, "_engine", None) is not None:
                company_db._engine.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def _ara(self, metin, **kw):
        return StokService.teklif_urun_ara(metin, depo_ad="ANA DEPO", **kw)

    def test_iki_harf_arama_yok(self):
        r = self._ara("ra")
        self.assertTrue(r["min_harf_uyari"])
        self.assertEqual(r["urunler"], [])

    def test_ray_contains(self):
        r = self._ara("ray")
        adlar = [u["urun_adi"] for u in r["urunler"]]
        self.assertTrue(any("Ray" in a or "ray" in a.lower() for a in adlar))
        self.assertFalse(any("Pasif" in a for a in adlar))

    def test_vid_casefold(self):
        r1 = self._ara("VİD")
        r2 = self._ara("vid")
        k1 = {u["urun_kodu"] for u in r1["urunler"]}
        k2 = {u["urun_kodu"] for u in r2["urunler"]}
        self.assertEqual(k1, k2)
        self.assertIn(f"{self.kod_prefix}-1", k1)

    def test_cek_cekmece(self):
        r = self._ara("cek")
        self.assertTrue(any("Çekmece" in u["urun_adi"] for u in r["urunler"]))

    def test_gon_gonye(self):
        r = self._ara("gon")
        self.assertTrue(any("Gönye" in u["urun_adi"] for u in r["urunler"]))

    def test_ucbes(self):
        r = self._ara("3.5")
        self.assertTrue(any("3.5" in u["urun_adi"] for u in r["urunler"]))

    def test_orta_karakter(self):
        r = self._ara("nta")
        self.assertTrue(any(u["urun_kodu"] == f"{self.kod_prefix}-1" for u in r["urunler"]))

    def test_pasif_yok(self):
        r = self._ara("pas")
        self.assertFalse(any(u["urun_kodu"] == f"{self.kod_prefix}-4" for u in r["urunler"]))

    def test_maliyet_yetkisiz_sutun_yok(self):
        with patch("database.access.maliyet_izinli", return_value=False):
            StokService._teklif_arama_onbellek.clear()
            r = self._ara("vid", maliyet_dahil=False)
        for u in r["urunler"]:
            self.assertNotIn("son_alis_fiyati", u)

    def test_limit_sabitleri(self):
        self.assertEqual(StokService._TEKLIF_ARAMA_LIMIT, 50)
        self.assertEqual(StokService._TEKLIF_ARAMA_MIN, 3)


if __name__ == "__main__":
    unittest.main()
