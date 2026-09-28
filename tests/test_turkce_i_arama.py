"""Aramalarda ı/i/I/İ ayrımı yok — normalizer, SQLite tr_norm() ve servis aramaları.

Gerçek veri dosyalarına dokunmaz; bellek içi SQLite kullanır.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.cari import Cari
from database.models.stok import StokBarkod, StokKarti
from database.search_service import SearchService
from database.sqlite_funcs import tr_herhangi_icerir, tr_icerir
from database.turkce_normalize import tr_iceriyor, turkce_normalize


def _sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class NormalizerTest(unittest.TestCase):
    def test_dort_i_harfi_ayni(self):
        for harf in ("İ", "I", "ı", "i"):
            self.assertEqual(turkce_normalize(harf), "i", msg=harf)

    def test_karisik_buyuk_kucuk(self):
        beklenen = turkce_normalize("kilit")
        for yazim in ("KİLİT", "KILIT", "kılıt", "KiLıT", "kİlIt", "Kilit"):
            self.assertEqual(turkce_normalize(yazim), beklenen, msg=yazim)
        self.assertEqual(turkce_normalize("ışık"), turkce_normalize("IŞIK"))
        self.assertEqual(turkce_normalize("isik"), turkce_normalize("İŞİK"))

    def test_birlesik_nokta_atilir(self):
        # Ayrışık 'İ' (I + U+0307) ve 'i̇' (i + U+0307)
        self.assertEqual(turkce_normalize("KI\u0307LI\u0307T"), "kilit")
        self.assertEqual(turkce_normalize("ki\u0307li\u0307t"), "kilit")
        self.assertNotIn("\u0307", turkce_normalize("İSTANBUL"))

    def test_mevcut_turkce_katlama_korunur(self):
        self.assertEqual(turkce_normalize("ŞĞÜÖÇ"), "sguoc")
        self.assertEqual(turkce_normalize("şğüöç"), "sguoc")

    def test_bos_ve_none(self):
        self.assertEqual(turkce_normalize(None), "")
        self.assertEqual(turkce_normalize(""), "")
        self.assertEqual(turkce_normalize(123), "123")

    def test_bellek_ici_filtre(self):
        self.assertTrue(tr_iceriyor("kilit", "ÇELİK KİLİT"))
        self.assertTrue(tr_iceriyor("KILIT", None, "kapı kilidi", "kılıt"))
        self.assertTrue(tr_iceriyor("", "herhangi"))
        self.assertFalse(tr_iceriyor("kilit", "KAPAK", None))

    def test_firma_secim_filtresi(self):
        from firma_secim_theme import firma_arama_eslesir

        firma = SimpleNamespace(unvan="IŞIK MOBİLYA", firma_kodu="F1", vergi_no="", kisa_ad="")
        for sorgu in ("isik", "ışık", "IŞIK", "mobilya", "MOBILYA", "mobılya"):
            self.assertTrue(firma_arama_eslesir(firma, sorgu), msg=sorgu)
        self.assertFalse(firma_arama_eslesir(firma, "kilit"))


class SqliteTrNormTest(unittest.TestCase):
    def setUp(self):
        # Ayrı listener eklemeden: tr_norm() global Engine olayıyla kaydedilmeli
        self.engine = create_engine("sqlite:///:memory:")

    def tearDown(self):
        self.engine.dispose()

    def test_tr_norm_fonksiyonu(self):
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT tr_norm('KİLİT')")).scalar(), "kilit")
            self.assertEqual(conn.execute(text("SELECT tr_norm('KILIT')")).scalar(), "kilit")
            self.assertEqual(conn.execute(text("SELECT tr_norm('kılıt')")).scalar(), "kilit")
            self.assertIsNone(conn.execute(text("SELECT tr_norm(NULL)")).scalar())

    def test_tr_icerir_like_kacis(self):
        Base.metadata.create_all(self.engine, tables=[StokKarti.__table__])
        Session = sessionmaker(bind=self.engine)
        with Session() as s:
            s.add_all(
                [
                    StokKarti(stok_kodu="A", stok_adi="%50 İNDİRİM", birim="Adet", aktif=True),
                    StokKarti(stok_kodu="B", stok_adi="150 INDIRIM", birim="Adet", aktif=True),
                ]
            )
            s.commit()
            kodlar = s.scalars(
                select(StokKarti.stok_kodu).where(tr_icerir(StokKarti.stok_adi, "%50 indirim"))
            ).all()
            self.assertEqual(list(kodlar), ["A"])

    def test_herhangi_icerir_alan_siniri_asilmaz(self):
        Base.metadata.create_all(self.engine, tables=[StokKarti.__table__])
        Session = sessionmaker(bind=self.engine)
        with Session() as s:
            s.add(StokKarti(stok_kodu="KIL", stok_adi="İTLER", marka=None, birim="Adet", aktif=True))
            s.commit()
            alanlar = (StokKarti.stok_kodu, StokKarti.marka, StokKarti.stok_adi)

            def _say(q):
                return len(s.scalars(select(StokKarti.id).where(tr_herhangi_icerir(alanlar, q))).all())

            self.assertEqual(_say("kıl"), 1)
            self.assertEqual(_say("İTLER"), 1)
            self.assertEqual(_say("kilit"), 0)


class _ServisTabani(unittest.TestCase):
    STOKLAR = (
        ("K-1", "KİLİT ÇELİK", "8690000000011"),
        ("K-2", "KAPI KILIT", "8690000000028"),
        ("K-3", "dolap kılıt", "8690000000035"),
        ("D-1", "PVC PANEL", "8690000000042"),
    )

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        import database.cari_service as cari_svc
        import database.database as db
        import database.search_service as ss
        import database.stok_service as stok_svc

        # İç içe get_session çağrıları aynı oturumu paylaşır (uygulamadaki gibi)
        self._ortak_session = None
        test = self

        class _Ctx:
            def __enter__(self):
                if test._ortak_session is None:
                    test._ortak_session = test.Session()
                return test._ortak_session

            def __exit__(self, *a):
                return False

        self._patches = []
        for mod in (db, ss, stok_svc, cari_svc):
            self._patches.append((mod, getattr(mod, "get_session", None)))
            mod.get_session = lambda: _Ctx()

        with self.Session() as s:
            for kod, ad, barkod in self.STOKLAR:
                s.add(
                    StokKarti(
                        stok_kodu=kod,
                        stok_adi=ad,
                        barkod=barkod,
                        birim="Adet",
                        aktif=True,
                        is_deleted=False,
                        kdv_orani=Decimal("20"),
                    )
                )
            s.add(
                Cari(
                    cari_kodu="M001",
                    unvan="IŞIK MOBİLYA",
                    cari_turu="Müşteri",
                    il="İzmir",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.add(
                Cari(
                    cari_kodu="M002",
                    unvan="Ankara Fren Ltd",
                    cari_turu="Müşteri",
                    aktif=True,
                    is_deleted=False,
                )
            )
            s.commit()
            k1 = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "D-1"))
            s.add(StokBarkod(stok_id=k1.id, barkod="EKİ-BARKOD-1"))
            s.commit()

    def tearDown(self):
        for mod, orig in self._patches:
            if orig is not None:
                mod.get_session = orig
        if self._ortak_session is not None:
            self._ortak_session.close()
        self.engine.dispose()


class StokAramaTest(_ServisTabani):
    KILITLER = {"KİLİT ÇELİK", "KAPI KILIT", "dolap kılıt"}
    SORGULAR = ("kilit", "KILIT", "kılıt", "KİLİT", "İLİT", "ılıt")

    def test_search_stocks(self):
        for sorgu in self.SORGULAR:
            urunler = SearchService.search_stocks(sorgu, limit=50).get("urunler") or []
            adlar = {u.stok_adi for u in urunler}
            self.assertEqual(adlar, self.KILITLER, msg=sorgu)

    def test_coklu_blok_karisik_yazim(self):
        urunler = SearchService.search_stocks("çelık KILİT", limit=50).get("urunler") or []
        self.assertEqual([u.stok_adi for u in urunler], ["KİLİT ÇELİK"])

    def test_stoklari_ara(self):
        from database.stok_service import StokService

        for sorgu in self.SORGULAR:
            adlar = {u.stok_adi for u in StokService.stoklari_ara(sorgu)}
            self.assertEqual(adlar, self.KILITLER, msg=sorgu)

    def test_stoklari_filtrele_klasik(self):
        from database.stok_service import StokService

        for sorgu in self.SORGULAR:
            adlar = {u.stok_adi for u in StokService.stoklari_filtrele(ad=sorgu)}
            self.assertEqual(adlar, self.KILITLER, msg=sorgu)
        kodlar = {u.stok_kodu for u in StokService.stoklari_filtrele(kod="k-")}
        self.assertEqual(kodlar, {"K-1", "K-2", "K-3"})

    def test_oneriler(self):
        from database.stok_service import StokService

        adlar = {u.stok_adi for u in StokService.stok_adi_onerileri("KILIT")}
        self.assertEqual(adlar, self.KILITLER)
        kodlar = {u.stok_kodu for u in StokService.stok_kodu_onerileri("k-")}
        self.assertEqual(kodlar, {"K-1", "K-2", "K-3"})

    def test_ayrintili_ara_or(self):
        from database.stok_service import StokService

        urunler = StokService.stoklari_ayrintili_ara(["ılıt", "PANEL"], yontem="or")
        self.assertEqual({u.stok_adi for u in urunler}, self.KILITLER | {"PVC PANEL"})

    def test_teklif_urun_ara(self):
        from database.stok_service import StokService

        StokService._teklif_arama_onbellek.clear()
        sonuc = StokService.teklif_urun_ara("KILIT", maliyet_dahil=False)
        adlar = {u.get("stok_adi") or u.get("urun_adi") or u.get("ad") for u in sonuc["urunler"]}
        self.assertEqual(sonuc["toplam_eslesen"], 3, msg=adlar)

    def test_ek_barkod_turkce(self):
        urunler = SearchService.search_stocks("eki-barkod", limit=10).get("urunler") or []
        self.assertEqual([u.stok_kodu for u in urunler], ["D-1"])

    def test_tam_barkod_yolu_korunur(self):
        sonuc = SearchService.search_stocks("8690000000011", limit=10)
        self.assertTrue(sonuc.get("barkod_tam"))
        self.assertEqual(sonuc["urunler"][0].stok_kodu, "K-1")


class CariAramaTest(_ServisTabani):
    def test_search_customers(self):
        for sorgu in ("isik", "ışık", "IŞIK", "İŞİK", "mobilya", "MOBILYA", "mobılya", "izmir"):
            hits = SearchService.search_customers(sorgu, limit=20)
            self.assertEqual([h["kod"] for h in hits], ["M001"], msg=sorgu)

    def test_cari_listele(self):
        from database.cari_service import CariService

        for sorgu in ("isik", "ışık mobilya", "MOBILYA"):
            sonuc = CariService.listele(sorgu)
            self.assertEqual([r["cari"].cari_kodu for r in sonuc], ["M001"], msg=sorgu)


if __name__ == "__main__":
    unittest.main()
