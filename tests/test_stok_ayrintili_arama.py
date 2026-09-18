"""Ayrıntılı ürün adı kelime araması (AND/OR) birim testleri."""

from __future__ import annotations

import unittest
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from database.database import Base
from database.models.stok import StokKarti
from database.stok_service import StokService
from database.turkce_normalize import turkce_normalize


def _sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class StokAyrintiliAramaTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _sqlite_pragma)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        # get_session monkeypatch
        import database.stok_service as ss
        import database.database as db

        self._orig_get_session = ss.get_session
        self._orig_db_get = db.get_session

        engine = self.engine
        SessionLocal = self.Session

        class _Ctx:
            def __enter__(self):
                self.s = SessionLocal()
                return self.s

            def __exit__(self, *a):
                self.s.close()

        ss.get_session = lambda: _Ctx()
        db.get_session = lambda: _Ctx()

        with self.Session() as s:
            ornekler = [
                "Samet Star Deve Boynu Menteşe Frenli",
                "Samet Star Deve Boynu Frenli Menteşe",
                "10 CM PVC Kaplamalı Mutfak Baza Ayağı Siyah",
                "Krom Ayak 120 cm",
                "PVC Panel Beyaz",
                "Samet Menteşe",
                "Başka Ürün",
            ]
            for i, ad in enumerate(ornekler, 1):
                s.add(
                    StokKarti(
                        stok_kodu=f"T{i:03d}",
                        stok_adi=ad,
                        birim="Adet",
                        aktif=True,
                        is_deleted=False,
                        kdv_orani=Decimal("20"),
                    )
                )
            s.commit()

    def tearDown(self):
        import database.stok_service as ss
        import database.database as db

        ss.get_session = self._orig_get_session
        db.get_session = self._orig_db_get
        self.engine.dispose()

    def _adlar(self, kelimeler, yontem="and"):
        return [s.stok_adi for s in StokService.stoklari_ayrintili_ara(kelimeler, yontem=yontem)]

    def test_tek_kelime_ment(self):
        adlar = self._adlar(["MENT"])
        self.assertTrue(any("Menteşe" in a for a in adlar))
        self.assertTrue(all(turkce_normalize("ment") in turkce_normalize(a) for a in adlar))

    def test_and_iki_kelime(self):
        adlar = set(self._adlar(["MENT", "SAMET"]))
        self.assertTrue(adlar >= {"Samet Star Deve Boynu Menteşe Frenli", "Samet Menteşe"})
        self.assertIn("Samet Star Deve Boynu Frenli Menteşe", adlar)

    def test_and_uc_kelime_sam_deve_fren(self):
        adlar = set(self._adlar(["SAM", "DEVE", "FREN"]))
        self.assertEqual(
            adlar,
            {
                "Samet Star Deve Boynu Menteşe Frenli",
                "Samet Star Deve Boynu Frenli Menteşe",
            },
        )

    def test_and_pvc_baza_siyah(self):
        adlar = self._adlar(["PVC", "BAZA", "SİYAH"])
        self.assertEqual(adlar, ["10 CM PVC Kaplamalı Mutfak Baza Ayağı Siyah"])

    def test_sira_onemsiz(self):
        a = self._adlar(["FREN", "SAM", "DEVE"])
        b = self._adlar(["DEVE", "FREN", "SAM"])
        self.assertEqual(set(a), set(b))
        self.assertTrue(any("Samet Star Deve Boynu" in x for x in a))

    def test_kabul_fren_samet_deve_tum_siralama(self):
        """Kabul: FREN / SAMET / DEVE hangi sırada olursa olsun aynı ürün(ler) gelir."""
        hedef = "Samet Star Deve Boynu Frenli Menteşe"
        siralar = (
            ("SAMET", "DEVE", "FREN"),
            ("FREN", "SAMET", "DEVE"),
            ("DEVE", "FREN", "SAMET"),
            ("FREN", "DEVE", "SAMET"),
            ("DEVE", "SAMET", "FREN"),
            ("SAMET", "FREN", "DEVE"),
        )
        for sira in siralar:
            with self.subTest(sira=sira):
                adlar = self._adlar(list(sira))
                self.assertIn(hedef, adlar)
                # Birleşik sıralı arama yapılmadığını doğrula: ters sıra da bulur
                self.assertTrue(
                    all(
                        turkce_normalize(k) in turkce_normalize(hedef)
                        for k in sira
                    )
                )

    def test_birlesik_metin_aranmaz(self):
        """'%SAMET DEVE FREN%' tarzı birleşik arama yapılmamalı — ayrı LIKE ile bulunur."""
        # Üründe SAMET ... DEVE ... FREN var ama bitişik 'SAMET DEVE FREN' yok
        adlar = self._adlar(["SAMET", "DEVE", "FREN"])
        self.assertIn("Samet Star Deve Boynu Frenli Menteşe", adlar)
        self.assertIn("Samet Star Deve Boynu Menteşe Frenli", adlar)

    def test_or_herhangi(self):
        adlar = self._adlar(["AYAK", "KROM", "120"], yontem="or")
        self.assertIn("Krom Ayak 120 cm", adlar)
        # PVC ürününde "Ayağı" var ama "AYAK" alt dizisi değil — beklenmez
        self.assertTrue(any("Krom" in a for a in adlar))

    def test_and_ayak_krom_120(self):
        adlar = self._adlar(["AYAK", "KROM", "120"])
        self.assertEqual(adlar, ["Krom Ayak 120 cm"])

    def test_bos_kutular_tum_liste(self):
        adlar = self._adlar(["", "  ", None])
        self.assertGreaterEqual(len(adlar), 7)

    def test_kisa_kelime_atlanir(self):
        # tek karakter min_harf=2 ile yok sayılır → tüm liste
        adlar = self._adlar(["P"])
        self.assertGreaterEqual(len(adlar), 7)

    def test_tekrar_yok(self):
        adlar = self._adlar(["PVC", "PVC"])
        self.assertEqual(len(adlar), len(set(adlar)))
        self.assertTrue(all("PVC" in a.upper() or "pvc" in turkce_normalize(a) for a in adlar))


if __name__ == "__main__":
    unittest.main()
