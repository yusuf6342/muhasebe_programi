"""Üç seviyeli stok grubu — zorunlu senaryolar.

Çalıştırma: python tests/test_stok_grubu_hiyerarsi.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import StokGrubu, StokKarti
from database.session_manager import oturum
from database.stok_grup_service import (
    SEVIYE_ALT,
    SEVIYE_ANA,
    SEVIYE_TALI,
    StokGrupService,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class StokGrubuHiyerarsiTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_stok_grup.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.donem  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="GRP", unvan="Grup Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 55
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=55,
            firma_kodu="GRP",
            firma_unvan="Grup Test",
            firma_uid="grp-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            if company_db._engine is not None:
                company_db._engine.dispose()
        except Exception:
            pass
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_01_hiyerarsi_mutfak_raylar(self):
        ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="MUT", ad="Mutfak Aksesuarları")
        tali = StokGrupService.ekle(
            seviye=SEVIYE_TALI, kod="RAY", ad="Raylar", parent_id=ana["id"]
        )
        alt = StokGrupService.ekle(
            seviye=SEVIYE_ALT, kod="TEL", ad="Teleskopik Raylar", parent_id=tali["id"]
        )
        dog = StokGrupService.hiyerarsi_dogrula(ana["id"], tali["id"], alt["id"])
        self.assertEqual(dog["rapor_grubu"], "Mutfak Aksesuarları / Raylar / Teleskopik Raylar")

    def test_02_sinirsiz_cogaltma(self):
        ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A1", ad="Ana1")
        for i in range(5):
            t = StokGrupService.ekle(
                seviye=SEVIYE_TALI, kod=f"T{i}", ad=f"Tali{i}", parent_id=ana["id"]
            )
            for j in range(3):
                StokGrupService.ekle(
                    seviye=SEVIYE_ALT,
                    kod=f"L{i}{j}",
                    ad=f"Alt{i}-{j}",
                    parent_id=t["id"],
                )
        tali = StokGrupService.listele(seviye=SEVIYE_TALI, parent_id=ana["id"])
        self.assertEqual(len(tali), 5)
        alt = StokGrupService.listele(seviye=SEVIYE_ALT, parent_id=tali[0]["id"])
        self.assertEqual(len(alt), 3)

    def test_03_kademeli_secim(self):
        a1 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="X", ad="XAna")
        a2 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="Y", ad="YAna")
        t1 = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="XT", ad="XTali", parent_id=a1["id"])
        StokGrupService.ekle(seviye=SEVIYE_TALI, kod="YT", ad="YTali", parent_id=a2["id"])
        StokGrupService.ekle(seviye=SEVIYE_ALT, kod="XA", ad="XAlt", parent_id=t1["id"])
        tali_x = StokGrupService.listele(seviye=SEVIYE_TALI, parent_id=a1["id"])
        self.assertEqual([t["ad"] for t in tali_x], ["XTali"])
        alt_x = StokGrupService.listele(seviye=SEVIYE_ALT, parent_id=t1["id"])
        self.assertEqual([a["ad"] for a in alt_x], ["XAlt"])

    def test_04_mukerrer(self):
        a = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="M1", ad="Merkez")
        with self.assertRaises(ValueError):
            StokGrupService.ekle(seviye=SEVIYE_ANA, kod="m1", ad="Başka")
        with self.assertRaises(ValueError):
            StokGrupService.ekle(seviye=SEVIYE_ANA, kod="M2", ad="merkez")
        t = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T1", ad="Tali", parent_id=a["id"])
        with self.assertRaises(ValueError):
            StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T1", ad="Diğer", parent_id=a["id"])
        self.assertIsNotNone(t)

    def test_05_yanlis_ust_baglanti(self):
        a = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A", ad="Ana")
        with self.assertRaises(ValueError):
            StokGrupService.ekle(seviye=SEVIYE_ALT, kod="L", ad="Alt", parent_id=a["id"])

    def test_06_tasi_ve_stok_koruma(self):
        a1 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A1", ad="Ana1")
        a2 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A2", ad="Ana2")
        t = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T", ad="Tali", parent_id=a1["id"])
        with get_session() as s:
            st = StokKarti(
                stok_kodu="S1",
                stok_adi="Ürün",
                birim="Adet",
                aktif=True,
                ana_grup_id=a1["id"],
                tali_grup_id=t["id"],
                rapor_grubu="Ana1 / Tali",
            )
            s.add(st)
            s.commit()
            sid = st.id
        StokGrupService.tasi(t["id"], a2["id"])
        with get_session() as s:
            st = s.get(StokKarti, sid)
            self.assertEqual(st.tali_grup_id, t["id"])
            self.assertEqual(st.ana_grup_id, a2["id"])
            self.assertIn("Ana2", st.rapor_grubu or "")

    def test_07_silme_guvenligi(self):
        a = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A", ad="Ana")
        t = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T", ad="Tali", parent_id=a["id"])
        with self.assertRaises(ValueError):
            StokGrupService.sil(a["id"])
        with get_session() as s:
            s.add(
                StokKarti(
                    stok_kodu="S2",
                    stok_adi="Ürün2",
                    birim="Adet",
                    aktif=True,
                    ana_grup_id=a["id"],
                    tali_grup_id=t["id"],
                )
            )
            s.commit()
        with self.assertRaises(ValueError):
            StokGrupService.sil(t["id"])
        # boş alt grup silinebilir
        a2 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="BOS", ad="BosAna")
        StokGrupService.sil(a2["id"])
        self.assertIsNone(StokGrupService.getir(a2["id"]))

    def test_08_toplu_tasima(self):
        a = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="A", ad="Ana")
        t1 = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T1", ad="T1", parent_id=a["id"])
        t2 = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="T2", ad="T2", parent_id=a["id"])
        l1 = StokGrupService.ekle(seviye=SEVIYE_ALT, kod="L1", ad="L1", parent_id=t1["id"])
        l2 = StokGrupService.ekle(seviye=SEVIYE_ALT, kod="L2", ad="L2", parent_id=t2["id"])
        idler = []
        with get_session() as s:
            for i in range(3):
                st = StokKarti(
                    stok_kodu=f"TX{i}",
                    stok_adi=f"Ürün{i}",
                    birim="Adet",
                    aktif=True,
                    ana_grup_id=a["id"],
                    tali_grup_id=t1["id"],
                    alt_grup_id=l1["id"],
                )
                s.add(st)
                s.flush()
                idler.append(st.id)
            s.commit()
        sonuc = StokGrupService.stoklara_ata(
            idler, ana_id=a["id"], tali_id=t2["id"], alt_id=l2["id"]
        )
        self.assertEqual(sonuc["adet"], 3)
        with get_session() as s:
            for sid in idler:
                st = s.get(StokKarti, sid)
                self.assertEqual(st.alt_grup_id, l2["id"])
                self.assertEqual(st.tali_grup_id, t2["id"])

    def test_09_migration_rapor_grubu(self):
        with get_session() as s:
            s.add_all(
                [
                    StokKarti(
                        stok_kodu="M1",
                        stok_adi="A",
                        birim="Adet",
                        aktif=True,
                        rapor_grubu="Eski Grup",
                    ),
                    StokKarti(
                        stok_kodu="M2",
                        stok_adi="B",
                        birim="Adet",
                        aktif=True,
                        rapor_grubu="Eski Grup",
                    ),
                    StokKarti(
                        stok_kodu="M3",
                        stok_adi="C",
                        birim="Adet",
                        aktif=True,
                        rapor_grubu="Diğer",
                    ),
                ]
            )
            s.commit()
        rapor = StokGrupService.migration_rapor_grubundan()
        self.assertGreaterEqual(rapor["olusan_ana_grup"], 2)
        self.assertGreaterEqual(rapor["eslesen_stok"], 3)
        with get_session() as s:
            st = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "M1"))
            self.assertIsNotNone(st.ana_grup_id)
            g = s.get(StokGrubu, st.ana_grup_id)
            self.assertEqual(g.ad, "Eski Grup")
            self.assertEqual(g.seviye, SEVIYE_ANA)

    def test_10_filtre_kapsam(self):
        a = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="F", ad="FiltreAna")
        t = StokGrupService.ekle(seviye=SEVIYE_TALI, kod="FT", ad="FiltreTali", parent_id=a["id"])
        l1 = StokGrupService.ekle(seviye=SEVIYE_ALT, kod="FL1", ad="Alt1", parent_id=t["id"])
        l2 = StokGrupService.ekle(seviye=SEVIYE_ALT, kod="FL2", ad="Alt2", parent_id=t["id"])
        with get_session() as s:
            s.add(
                StokKarti(
                    stok_kodu="F1",
                    stok_adi="U1",
                    birim="Adet",
                    aktif=True,
                    ana_grup_id=a["id"],
                    tali_grup_id=t["id"],
                    alt_grup_id=l1["id"],
                )
            )
            s.add(
                StokKarti(
                    stok_kodu="F2",
                    stok_adi="U2",
                    birim="Adet",
                    aktif=True,
                    ana_grup_id=a["id"],
                    tali_grup_id=t["id"],
                    alt_grup_id=l2["id"],
                )
            )
            s.commit()
        from database.stok_service import StokService

        r = StokService.stoklari_liste_filtreli(filtre={"tali_grup_id": t["id"]}, limit=50)
        kodlar = {x["values"]["kod"] for x in r["satirlar"]}
        self.assertEqual(kodlar, {"F1", "F2"})
        r2 = StokService.stoklari_liste_filtreli(filtre={"alt_grup_id": l1["id"]}, limit=50)
        self.assertEqual({x["values"]["kod"] for x in r2["satirlar"]}, {"F1"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
