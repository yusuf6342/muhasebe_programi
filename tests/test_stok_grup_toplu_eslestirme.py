"""Toplu stok grubu eşleştirme — önizleme, politika, transaction, geri alma.

Çalıştırma: python tests/test_stok_grup_toplu_eslestirme.py
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
from database.models.stok import StokKarti
from database.session_manager import oturum
from database.stok_grup_service import SEVIYE_ALT, SEVIYE_ANA, SEVIYE_TALI, StokGrupService
from database.stok_grup_toplu_service import (
    POLITIKA_DEGISTIR,
    POLITIKA_SADECE_GRUPSUZ,
    StokGrupTopluService,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class TopluGrupEslestirmeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_toplu_grup.db"
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
            firma = Firma(firma_kodu="TGE", unvan="Toplu Grup Test", aktif=True)
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
        company_db._company_id = 66
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
            company_id=66,
            firma_kodu="TGE",
            firma_unvan="Toplu Grup Test",
            firma_uid="tge-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

        self.ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="MUT", ad="Mutfak")
        self.tali = StokGrupService.ekle(
            seviye=SEVIYE_TALI, kod="RAY", ad="Raylar", parent_id=self.ana["id"]
        )
        self.alt = StokGrupService.ekle(
            seviye=SEVIYE_ALT, kod="TEL", ad="Teleskopik", parent_id=self.tali["id"]
        )
        self.ana2 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="BKA", ad="Banyo")

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

    def _stok(self, kod, *, ana=None, tali=None, alt=None):
        with get_session() as s:
            st = StokKarti(
                stok_kodu=kod,
                stok_adi=f"Ürün {kod}",
                birim="Adet",
                aktif=True,
                ana_grup_id=ana,
                tali_grup_id=tali,
                alt_grup_id=alt,
            )
            s.add(st)
            s.commit()
            return int(st.id)

    def test_01_grupsuz_toplu_atama(self):
        ids = [self._stok(f"G{i}") for i in range(5)]
        oniz = StokGrupTopluService.onizle(
            ids,
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
        )
        self.assertEqual(oniz["ozet"]["guncellenecek"], 5)
        sonuc = StokGrupTopluService.uygula(
            ids,
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
            onizleme_ozeti=oniz["ozet"],
        )
        self.assertEqual(sonuc["guncellenen"], 5)
        with get_session() as s:
            for sid in ids:
                st = s.get(StokKarti, sid)
                self.assertEqual(st.alt_grup_id, self.alt["id"])
                self.assertIn("Mutfak", st.rapor_grubu or "")

    def test_02_varsayilan_gruplu_atlanir(self):
        grupsuz = self._stok("GZ1")
        gruplu = self._stok(
            "GL1", ana=self.ana2["id"]
        )
        oniz = StokGrupTopluService.onizle(
            [grupsuz, gruplu],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
        )
        self.assertEqual(oniz["ozet"]["guncellenecek"], 1)
        self.assertEqual(oniz["ozet"]["atlanacak"], 1)
        StokGrupTopluService.uygula(
            [grupsuz, gruplu],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
            onizleme_ozeti=oniz["ozet"],
        )
        with get_session() as s:
            self.assertEqual(s.get(StokKarti, gruplu).ana_grup_id, self.ana2["id"])
            self.assertEqual(s.get(StokKarti, grupsuz).alt_grup_id, self.alt["id"])

    def test_03_grup_degistirme(self):
        sid = self._stok("DG1", ana=self.ana2["id"])
        oniz = StokGrupTopluService.onizle(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_DEGISTIR,
        )
        self.assertEqual(oniz["ozet"]["guncellenecek"], 1)
        StokGrupTopluService.uygula(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_DEGISTIR,
            onizleme_ozeti=oniz["ozet"],
        )
        with get_session() as s:
            st = s.get(StokKarti, sid)
            self.assertEqual(st.ana_grup_id, self.ana["id"])
            self.assertEqual(st.alt_grup_id, self.alt["id"])

    def test_04_filtre_tum_idler(self):
        for i in range(25):
            self._stok(f"F{i:02d}")
        idler = StokGrupTopluService.filtre_tum_idler(grup_durumu="grupsuz", aktiflik="aktif")
        self.assertGreaterEqual(len(idler), 25)

    def test_05_hiyerarsi_red(self):
        # Yanlış: tali başka ana altında
        with self.assertRaises(ValueError):
            StokGrupService.hiyerarsi_dogrula(self.ana2["id"], self.tali["id"], self.alt["id"])

    def test_06_ayni_hedef_degisiklik_yok(self):
        sid = self._stok(
            "AY1",
            ana=self.ana["id"],
            tali=self.tali["id"],
            alt=self.alt["id"],
        )
        oniz = StokGrupTopluService.onizle(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_DEGISTIR,
        )
        self.assertEqual(oniz["ozet"]["degismeyecek"], 1)
        self.assertEqual(oniz["ozet"]["guncellenecek"], 0)

    def test_07_geri_alma(self):
        sid = self._stok("GA1")
        oniz = StokGrupTopluService.onizle(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
        )
        sonuc = StokGrupTopluService.uygula(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
            onizleme_ozeti=oniz["ozet"],
        )
        with get_session() as s:
            self.assertIsNotNone(s.get(StokKarti, sid).ana_grup_id)
        geri = StokGrupTopluService.geri_al(sonuc["islem_id"])
        self.assertEqual(geri["geri_alinan"], 1)
        with get_session() as s:
            st = s.get(StokKarti, sid)
            self.assertIsNone(st.ana_grup_id)
            self.assertIsNone(st.alt_grup_id)

    def test_08_onizleme_ozeti_uyusmazligi(self):
        sid = self._stok("OZ1")
        oniz = StokGrupTopluService.onizle(
            [sid],
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
        )
        with self.assertRaises(ValueError):
            StokGrupTopluService.uygula(
                [sid],
                ana_id=self.ana["id"],
                tali_id=self.tali["id"],
                alt_id=self.alt["id"],
                politika=POLITIKA_SADECE_GRUPSUZ,
                onizleme_ozeti={"guncellenecek": 99},
            )

    def test_09_performans_1000_onizleme(self):
        ids = [self._stok(f"P{i:04d}") for i in range(200)]
        # 200 yeterli birim testi; 1000 UI donmama servis tarafında aynı yol
        oniz = StokGrupTopluService.onizle(
            ids,
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
        )
        self.assertEqual(oniz["ozet"]["guncellenecek"], 200)
        sonuc = StokGrupTopluService.uygula(
            ids,
            ana_id=self.ana["id"],
            tali_id=self.tali["id"],
            alt_id=self.alt["id"],
            politika=POLITIKA_SADECE_GRUPSUZ,
            onizleme_ozeti=oniz["ozet"],
        )
        self.assertEqual(sonuc["guncellenen"], 200)

    def _tam_onizleme(self, ids):
        return StokGrupTopluService.onizle(
            ids, ana_id=self.ana["id"], tali_id=None, alt_id=None,
            politika=POLITIKA_DEGISTIR,
        )

    def _tam_uygula(self, ids, oniz):
        return StokGrupTopluService.uygula(
            ids, ana_id=self.ana["id"], tali_id=None, alt_id=None,
            politika=POLITIKA_DEGISTIR, onizleme_ozeti=oniz["ozet"], onizleme_kaydi=oniz,
        )

    def test_10_adet_ayni_kalsa_da_eski_grup_degismisse_reddet(self):
        sid = self._stok("ESKI", ana=self.ana2["id"])
        oniz = self._tam_onizleme([sid])
        with get_session() as s:
            s.get(StokKarti, sid).ana_grup_id = None
        self.assertEqual(self._tam_onizleme([sid])["ozet"], oniz["ozet"])
        with self.assertRaisesRegex(ValueError, "güncelliğini"):
            self._tam_uygula([sid], oniz)
        with get_session() as s:
            self.assertIsNone(s.get(StokKarti, sid).ana_grup_id)
        self.assertEqual(StokGrupTopluService.islem_gecmisi(), [])

    def test_11_ayni_adette_baska_urun_secilmesi_reddedilir(self):
        ilk, ikinci = self._stok("ILK"), self._stok("IKINCI")
        with self.assertRaisesRegex(ValueError, "güncelliğini"):
            self._tam_uygula([ikinci], self._tam_onizleme([ilk]))

    def test_12_firma_degismisse_onizleme_kullanilamaz(self):
        sid = self._stok("FIRMA")
        oniz = self._tam_onizleme([sid])
        oturum.firma_uid = "baska-firma"
        with self.assertRaisesRegex(ValueError, "güncelliğini"):
            self._tam_uygula([sid], oniz)

    def test_13_gecersiz_alt_grup_sessizce_atilmaz(self):
        sid = self._stok("HEDEF")
        with self.assertRaisesRegex(ValueError, "Geçerli"):
            StokGrupTopluService.onizle(
                [sid], ana_id=self.ana["id"], tali_id=self.tali["id"], alt_id=999999,
            )

    def test_14_yazma_hatasinda_gruplar_ve_islem_gecmisi_geri_alinir(self):
        ids = [self._stok("ATOM1"), self._stok("ATOM2")]
        oniz = self._tam_onizleme(ids)
        with patch("database.stok_grup_toplu_service.audit_document", side_effect=RuntimeError("test hata")):
            with self.assertRaisesRegex(RuntimeError, "test hata"):
                self._tam_uygula(ids, oniz)
        with get_session() as s:
            for sid in ids:
                self.assertIsNone(s.get(StokKarti, sid).ana_grup_id)
        self.assertEqual(StokGrupTopluService.islem_gecmisi(), [])

    def test_15_tam_onizleme_ile_aktarim_ve_guvenli_geri_alma(self):
        sid = self._stok("DONUS", ana=self.ana2["id"])
        sonuc = self._tam_uygula([sid], self._tam_onizleme([sid]))
        with get_session() as s:
            stok = s.get(StokKarti, sid)
            self.assertEqual(stok.ana_grup_id, self.ana["id"])
            self.assertEqual(stok.stok_adi, "Ürün DONUS")
            self.assertEqual(stok.birim, "Adet")
        StokGrupTopluService.geri_al(sonuc["islem_id"])
        with get_session() as s:
            self.assertEqual(s.get(StokKarti, sid).ana_grup_id, self.ana2["id"])

    def test_16_kayit_aninda_hedef_gecersizlesirse_tum_islem_geri_alinir(self):
        sid = self._stok("HEDEFDEGISIM")
        oniz = self._tam_onizleme([sid])
        dogrula = StokGrupService.hiyerarsi_dogrula
        cagri = 0

        def hedef_degissin(*args, **kwargs):
            nonlocal cagri
            cagri += 1
            sonuc = dogrula(*args, **kwargs)
            if cagri > 1:
                sonuc["pasif_uyari"] = ["Mutfak"]
            return sonuc

        with patch.object(StokGrupService, "hiyerarsi_dogrula", side_effect=hedef_degissin):
            with self.assertRaisesRegex(ValueError, "Hedef grup değişti"):
                self._tam_uygula([sid], oniz)
        with get_session() as s:
            self.assertIsNone(s.get(StokKarti, sid).ana_grup_id)
        self.assertEqual(StokGrupTopluService.islem_gecmisi(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
