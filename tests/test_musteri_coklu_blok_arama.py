"""Fatura müşteri seçimi — çoklu blok / sıra bağımsız arama kabul testleri."""

from __future__ import annotations

import time
import unittest
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.cari import Cari
from database.search_service import (
    SearchService,
    normalize_text,
    tokenize_query,
)


def _sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class MusteriCokluBlokAramaTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        import database.cari_service as cari_svc
        import database.database as db
        import database.search_service as ss

        self._patches = []
        for mod in (db, ss, cari_svc):
            self._patches.append((mod, getattr(mod, "get_session", None)))

        SessionLocal = self.Session

        class _Ctx:
            def __enter__(self):
                self.s = SessionLocal()
                return self.s

            def __exit__(self, *a):
                self.s.close()

        for mod, _ in self._patches:
            if hasattr(mod, "get_session"):
                mod.get_session = lambda: _Ctx()

        with self.Session() as s:
            s.add(
                Cari(
                    cari_kodu="AY001",
                    unvan="AHMET YILMAZ",
                    cari_turu="Müşteri",
                    telefon="05551112233",
                    vergi_numarasi="1234567890",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add(
                Cari(
                    cari_kodu="AY002",
                    unvan="AHMET DEMİR",
                    cari_turu="Müşteri",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add(
                Cari(
                    cari_kodu="CS001",
                    unvan="ÇAĞRI ÖZKAN MOBİLYA SANAYİ",
                    cari_turu="Müşteri",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add(
                Cari(
                    cari_kodu="MS001",
                    unvan="MOBİLYA SANAYİ LTD",
                    cari_turu="Müşteri",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.commit()

    def tearDown(self):
        for mod, orig in self._patches:
            if orig is not None:
                mod.get_session = orig
        self.engine.dispose()

    def _unvanlar(self, sorgu: str) -> list[str]:
        return [h["unvan"] for h in SearchService.search_customers(sorgu, limit=50)]

    def test_tokenize_normalize(self):
        self.assertEqual(tokenize_query("  ahm   yıl  "), ["ahm", "yıl"])
        self.assertEqual(tokenize_query("ahm, yıl!"), ["ahm", "yıl"])
        self.assertEqual(normalize_text("YILMAZ"), normalize_text("yılmaz"))

    def test_matris_bulur(self):
        hedef = "AHMET YILMAZ"
        for sorgu in (
            "ahm",
            "ahm yıl",
            "yıl ahm",
            "AHM YIL",
            "ahmet yıl",
            "met maz",
        ):
            unvanlar = self._unvanlar(sorgu)
            self.assertIn(hedef, unvanlar, msg=f"sorgu={sorgu!r} → {unvanlar}")

    def test_ahm_dem_bulmaz_yilmaz(self):
        unvanlar = self._unvanlar("ahm dem")
        self.assertNotIn("AHMET YILMAZ", unvanlar)
        self.assertIn("AHMET DEMİR", unvanlar)

    def test_mob_san(self):
        unvanlar = self._unvanlar("mob san")
        self.assertTrue(
            any("MOBİLYA" in u or "Mobilya" in u for u in unvanlar),
            msg=unvanlar,
        )

    def test_yil_mob_ahm(self):
        # Üç blok: yıl + mob + ahm — YILMAZ'da mob yok → bulmaz
        unvanlar = self._unvanlar("yıl mob ahm")
        self.assertNotIn("AHMET YILMAZ", unvanlar)

    def test_turkce_cag_oz(self):
        unvanlar = self._unvanlar("çağ öz")
        self.assertTrue(any("ÇAĞRI" in u or "CAGRI" in u.upper() for u in unvanlar), msg=unvanlar)
        unvanlar2 = self._unvanlar("cag oz")
        self.assertTrue(any("ÇAĞRI" in u or "CAGRI" in u.upper() for u in unvanlar2), msg=unvanlar2)

    def test_tekilleştirme(self):
        hits = SearchService.search_customers("ahm yıl", limit=50)
        ids = [h["cari"].id for h in hits]
        self.assertEqual(len(ids), len(set(ids)))

    def test_kod_telefon_vergi(self):
        self.assertEqual(self._unvanlar("AY001"), ["AHMET YILMAZ"])
        self.assertEqual(self._unvanlar("05551112233"), ["AHMET YILMAZ"])
        self.assertEqual(self._unvanlar("1234567890"), ["AHMET YILMAZ"])


class MusteriAramaPerformansTest(unittest.TestCase):
    """≥10.000 cari ile sorgu süresi (bellek SQLite)."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        event.listen(cls.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

        import database.cari_service as cari_svc
        import database.database as db
        import database.search_service as ss

        cls._patches = []
        for mod in (db, ss, cari_svc):
            cls._patches.append((mod, getattr(mod, "get_session", None)))

        SessionLocal = cls.Session

        class _Ctx:
            def __enter__(self):
                self.s = SessionLocal()
                return self.s

            def __exit__(self, *a):
                self.s.close()

        for mod, _ in cls._patches:
            if hasattr(mod, "get_session"):
                mod.get_session = lambda: _Ctx()

        with cls.Session() as s:
            batch = []
            for i in range(10_000):
                batch.append(
                    Cari(
                        cari_kodu=f"P{i:05d}",
                        unvan=f"TEST CARİ {i:05d} SANAYİ",
                        cari_turu="Müşteri",
                        aktif=True,
                        is_deleted=False,
                    )
                )
            batch.append(
                Cari(
                    cari_kodu="PERF01",
                    unvan="AHMET YILMAZ PERF",
                    cari_turu="Müşteri",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add_all(batch)
            s.commit()

    @classmethod
    def tearDownClass(cls):
        for mod, orig in cls._patches:
            if orig is not None:
                mod.get_session = orig
        cls.engine.dispose()

    def test_10000_cari_sorgu_suresi(self):
        t0 = time.perf_counter()
        hits = SearchService.search_customers("ahm yıl", limit=50)
        ms = (time.perf_counter() - t0) * 1000
        unvanlar = [h["unvan"] for h in hits]
        self.assertIn("AHMET YILMAZ PERF", unvanlar)
        # UI debounce 280ms; sorgu bunun altında kalmalı (SQLite bellek)
        self.assertLess(ms, 2000, msg=f"sorgu {ms:.1f} ms — çok yavaş")
        # ASCII-only log (Windows cp1254 konsol)
        print(f"\n[PERF] 10000+ cari 'ahm yil' = {ms:.1f} ms, {len(hits)} sonuc")


if __name__ == "__main__":
    unittest.main()
