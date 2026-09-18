"""Stok Kartı — Depo CRUD, birim filtresi, hareket renkleri (DOCX talimatı).

Çalıştırma: python tests/test_stok_karti_depo_birim.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokBirim, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService
from stok_ui import (
    _ALIS_ETIKET_FG,
    _SATIS_ETIKET_FG,
    hareket_yon_tag,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class StokKartiDepoBirimTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_stok_depo.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.stok_sayim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="SDK", unvan="Stok Depo Test", aktif=True)
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
        company_db._company_id = 77
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
            company_id=77,
            firma_kodu="SDK",
            firma_unvan="Stok Depo Test",
            firma_uid="sdk-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit_patch = patch("database.user_audit.audit_document", return_value=None)
        self._audit_patch.start()

    def tearDown(self):
        self._audit_patch.stop()
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

    def test_01_depo_olusturma(self):
        d1 = StokService.depo_ekle("Ana Depo", kod="ANA", varsayilan=True)
        d2 = StokService.depo_ekle("Şube Depo", kod="SUBE", aciklama="İkinci depo")
        self.assertIsNotNone(d1.id)
        self.assertEqual(d1.kod, "ANA")
        self.assertTrue(d1.varsayilan)
        self.assertEqual(d2.ad, "ŞUBE DEPO")
        liste = StokService.depolar(aktif_only=False)
        self.assertEqual(len(liste), 2)

    def test_02_mukerrer_depo(self):
        StokService.depo_ekle("Merkez", kod="MRK")
        with self.assertRaises(ValueError) as ctx_kod:
            StokService.depo_ekle("Başka Ad", kod="mrk")
        self.assertIn("kod", str(ctx_kod.exception).lower())
        with self.assertRaises(ValueError) as ctx_ad:
            StokService.depo_ekle("merkez", kod="X1")
        self.assertIn("ad", str(ctx_ad.exception).lower())

    def test_03_bos_depo_silme(self):
        d = StokService.depo_ekle("Boş Depo", kod="BOS")
        depo_id = int(d.id)
        StokService.depo_sil(depo_id)
        self.assertIsNone(StokService.depo_getir(depo_id))

    def test_04_dolu_depo_silinemez(self):
        d = StokService.depo_ekle("Dolu Depo", kod="DOLU")
        with get_session() as s:
            stok = StokKarti(stok_kodu="S1", stok_adi="Ürün", birim="Adet", aktif=True)
            s.add(stok)
            s.flush()
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=d.id,
                    lot_no="L1",
                    giris_tarihi=date(2026, 1, 5),
                    kalan_miktar=Decimal("10"),
                    birim_maliyet=Decimal("1"),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=stok.id,
                    depo_id=d.id,
                    tarih=date(2026, 1, 5),
                    hareket_turu="FATURA GİRİŞ",
                    belge_no="AF-1",
                    miktar=Decimal("10"),
                    birim_maliyet=Decimal("1"),
                )
            )
            s.commit()
            depo_id = int(d.id)
        with self.assertRaises(ValueError) as ctx:
            StokService.depo_sil(depo_id)
        msg = str(ctx.exception).lower()
        self.assertTrue("silinemez" in msg or "pasife" in msg)
        self.assertIsNotNone(StokService.depo_getir(depo_id))

    def test_05_varsayilan_depo_silinemez(self):
        d = StokService.depo_ekle("Varsayılan", kod="VAR", varsayilan=True)
        with self.assertRaises(ValueError) as ctx:
            StokService.depo_sil(int(d.id))
        self.assertIn("varsayılan", str(ctx.exception).lower())

    def test_06_hareket_renk_etiketleri(self):
        for tur in GIRIS_HAREKETLERI:
            self.assertEqual(hareket_yon_tag(tur), "giris", tur)
        for tur in CIKIS_HAREKETLERI:
            self.assertEqual(hareket_yon_tag(tur), "cikis", tur)
        self.assertEqual(hareket_yon_tag("İPTAL"), "notr")
        self.assertEqual(hareket_yon_tag("TRANSFER GİRİŞ"), "giris")
        self.assertEqual(hareket_yon_tag("TRANSFER ÇIKIŞ"), "cikis")
        self.assertEqual(hareket_yon_tag("İADE GİRİŞ"), "giris")

    def test_07_fiyat_etiket_renkleri(self):
        self.assertEqual(_ALIS_ETIKET_FG.upper(), "#C62828")
        self.assertEqual(_SATIS_ETIKET_FG.upper(), "#2E7D32")

    def test_08_birim_filtresi_stoka_ozel(self):
        with get_session() as s:
            a = StokKarti(stok_kodu="A1", stok_adi="Stok A", birim="Adet", aktif=True)
            b = StokKarti(stok_kodu="B1", stok_adi="Stok B", birim="Kg", aktif=True)
            s.add_all([a, b])
            s.flush()
            s.add_all(
                [
                    StokBirim(stok_id=a.id, birim_adi="Adet", carpan=Decimal("1"), aktif=True),
                    StokBirim(stok_id=a.id, birim_adi="Paket", carpan=Decimal("12"), aktif=True),
                    StokBirim(stok_id=a.id, birim_adi="Koli", carpan=Decimal("24"), aktif=True),
                    StokBirim(stok_id=b.id, birim_adi="Kg", carpan=Decimal("1"), aktif=True),
                    StokBirim(stok_id=b.id, birim_adi="Torba", carpan=Decimal("25"), aktif=False),
                ]
            )
            s.commit()
            a_id, b_id = int(a.id), int(b.id)

        with get_session() as s:
            stok_a = s.get(StokKarti, a_id)
            stok_b = s.get(StokKarti, b_id)
            _ = list(stok_a.birimler or [])
            _ = list(stok_b.birimler or [])
            birimler_a = StokService.birimleri_dict_listesi(stok_a)
            birimler_b = StokService.birimleri_dict_listesi(stok_b)

        def aktif_adlar(lst):
            out = []
            for kayit in lst:
                if isinstance(kayit, dict) and not kayit.get("aktif", True):
                    continue
                ad = (kayit.get("birim_adi") or kayit.get("birim") or "").strip()
                if ad:
                    out.append(ad)
            return out

        self.assertEqual(set(aktif_adlar(birimler_a)), {"Adet", "Paket", "Koli"})
        self.assertEqual(set(aktif_adlar(birimler_b)), {"Kg"})
        self.assertNotIn("Torba", aktif_adlar(birimler_b))
        self.assertNotIn("Paket", aktif_adlar(birimler_b))

    def test_09_pasife_al(self):
        d = StokService.depo_ekle("Pasif Aday", kod="PAS")
        StokService.depo_pasife_al(int(d.id))
        yenilenmis = StokService.depo_getir(int(d.id))
        self.assertIsNotNone(yenilenmis)
        self.assertFalse(yenilenmis.aktif)


if __name__ == "__main__":
    unittest.main(verbosity=2)
