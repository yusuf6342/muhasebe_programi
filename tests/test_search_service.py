"""Çoklu blok / sıra bağımsız SearchService testleri (CANEX kabul senaryosu)."""

from __future__ import annotations

import unittest
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.cari import Cari
from database.models.stok import StokKarti
from database.search_service import (
    SearchService,
    normalize_text,
    tokenize_query,
)


def _sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class SearchServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        import database.database as db
        import database.search_service as ss
        import database.stok_service as stok_svc
        import database.cari_service as cari_svc

        self._patches = []
        for mod in (db, ss, stok_svc, cari_svc):
            self._patches.append((mod, getattr(mod, "get_session", None)))

        engine = self.engine
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
                StokKarti(
                    stok_kodu="CANEX-50",
                    stok_adi="CANEX FRENLİ TELESKOPİK RAY 50 CM",
                    barkod="8690001122334",
                    birim="Adet",
                    marka="CANEX",
                    aktif=True,
                    is_deleted=False,
                    kdv_orani=Decimal("20"),
                )
            )
            s.add(
                StokKarti(
                    stok_kodu="DIGER-1",
                    stok_adi="PVC Panel Beyaz 100 cm",
                    barkod="111",
                    birim="Adet",
                    aktif=True,
                    is_deleted=False,
                    kdv_orani=Decimal("20"),
                )
            )
            s.add(
                StokKarti(
                    stok_kodu="PASIF-1",
                    stok_adi="CANEX Eski Ray",
                    birim="Adet",
                    aktif=False,
                    is_deleted=False,
                    kdv_orani=Decimal("20"),
                )
            )
            s.add(
                Cari(
                    cari_kodu="M001",
                    unvan="Ankara Fren Sanayi Ltd",
                    cari_turu="Müşteri",
                    telefon="03121234567",
                    il="Ankara",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add(
                Cari(
                    cari_kodu="T001",
                    unvan="İzmir Ray Tedarik A.Ş.",
                    cari_turu="Tedarikçi",
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

    def _adlar(self, sorgu: str) -> list[str]:
        urunler = SearchService.search_stocks(sorgu, limit=50).get("urunler") or []
        return [u.stok_adi for u in urunler]

    def test_tokenize_min_iki_karakter(self):
        self.assertEqual(tokenize_query("a b cd"), ["cd"])
        self.assertEqual(tokenize_query("  50   fr  ray "), ["50", "fr", "ray"])
        self.assertEqual(tokenize_query("a"), [])
        self.assertEqual(tokenize_query("fr fr fr"), ["fr"])

    def test_normalize_turkce(self):
        self.assertEqual(normalize_text("frenli"), normalize_text("FRENLİ"))
        self.assertEqual(normalize_text("kose"), normalize_text("köşe"))
        self.assertEqual(normalize_text("cekmece"), normalize_text("çekmece"))
        self.assertEqual(normalize_text("olcu"), normalize_text("ölçü"))

    def test_canex_sirasiz_sorgular(self):
        hedef = "CANEX FRENLİ TELESKOPİK RAY 50 CM"
        for sorgu in (
            "50 fr ray",
            "ray 50 fre",
            "fre can 50",
            "can cm",
            "50 ray fre can cm",
        ):
            adlar = self._adlar(sorgu)
            self.assertIn(hedef, adlar, msg=f"sorgu={sorgu!r} → {adlar}")

    def test_blok_eksikse_bulunmaz(self):
        adlar = self._adlar("50 fr xyz")
        self.assertNotIn("CANEX FRENLİ TELESKOPİK RAY 50 CM", adlar)

    def test_tam_barkod_oncelik(self):
        sonuc = SearchService.search_stocks("8690001122334", limit=10)
        self.assertTrue(sonuc.get("barkod_tam"))
        self.assertEqual(len(sonuc.get("urunler") or []), 1)
        self.assertEqual(sonuc["urunler"][0].stok_kodu, "CANEX-50")

    def test_tam_stok_kodu(self):
        urunler = SearchService.search_stocks("CANEX-50", limit=10).get("urunler") or []
        self.assertEqual(len(urunler), 1)
        self.assertEqual(urunler[0].stok_kodu, "CANEX-50")

    def test_aktif_filtresi(self):
        adlar = self._adlar("CANEX Eski")
        self.assertNotIn("CANEX Eski Ray", adlar)

    def test_stoklari_filtrele_kelime_sirasiz(self):
        from database.stok_service import StokService

        urunler = StokService.stoklari_filtrele(
            ad="50 fr ray", limit=50, kelime_sirasiz=True, min_ad_harf=2
        )
        adlar = [u.stok_adi for u in urunler]
        self.assertIn("CANEX FRENLİ TELESKOPİK RAY 50 CM", adlar)

    def test_musteri_coklu_blok(self):
        hits = SearchService.search_customers("ankara fren", limit=20)
        unvanlar = [h["unvan"] for h in hits]
        self.assertTrue(any("Ankara Fren" in u for u in unvanlar))

    def test_tedarikci_coklu_blok(self):
        hits = SearchService.search_suppliers("izmir ray", limit=20)
        unvanlar = [h["unvan"] for h in hits]
        self.assertTrue(any("İzmir Ray" in u or "Izmir Ray" in u for u in unvanlar))


if __name__ == "__main__":
    unittest.main()
