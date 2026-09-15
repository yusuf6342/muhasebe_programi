"""Silinen kayıtlar merkezi — Phase A kabul testleri.

Çalıştırma: python -m pytest test_silinen_kayitlar.py -q
veya: python test_silinen_kayitlar.py
"""

from __future__ import annotations

import sys
import tempfile
import traceback
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari
from database.models.deleted_record import DeletedRecordLog
from database.models.stok import StokKarti
from database.models.satis_faturasi import SatisFaturasi
from database.session_manager import oturum
from database.deleted_record_service import (
    ENTITY_CARI,
    ENTITY_STOK,
    AuditDeleteService,
    RestoreService,
    SoftDeleteError,
    compute_integrity_hash,
    dumps_safe,
    loads_json,
    sanitize_snapshot,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class SilinenKayitlarTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_company.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)
        # Ana uygulama ile aynı model seti
        from database.models.firma import Firma
        from database.models.donem import Donem
        from database.models.cari import CariIslem, SatisHareketi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.hizmet  # noqa: F401
        import database.models.hizmet_faturasi  # noqa: F401
        import database.models.kk_cekimi  # noqa: F401
        import database.models.deleted_record  # noqa: F401

        Base.metadata.create_all(eng)

        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="TST", unvan="Test", aktif=True)
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
        company_db._company_id = 42
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
            company_id=42,
            firma_kodu="TST",
            firma_unvan="Test Firma",
            firma_uid="test-uid",
            db_path=str(self.db_path),
        )
        AuditDeleteService.schema_hazirla()

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        oturum.clear()
        self._tmpdir.cleanup()

    def _cari(self, kod="C001", unvan="Test Cari") -> Cari:
        from database.database import get_session

        with get_session() as session:
            c = Cari(
                cari_kodu=kod,
                unvan=unvan,
                cari_turu="Müşteri",
                aktif=True,
                is_deleted=False,
            )
            session.add(c)
            session.flush()
            session.refresh(c)
            return c

    def _stok(self, kod="S001", ad="Test Stok") -> StokKarti:
        from database.database import get_session

        with get_session() as session:
            s = StokKarti(
                stok_kodu=kod,
                stok_adi=ad,
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            session.add(s)
            session.flush()
            session.refresh(s)
            return s

    def test_simple_card_soft_delete_and_log(self):
        c = self._cari()
        log = AuditDeleteService.delete_record(
            ENTITY_CARI,
            c.id,
            reason="Test verisi",
            note="pytest",
            critical_confirm=c.cari_kodu,
        )
        self.assertEqual(log["entity_type"], ENTITY_CARI)
        self.assertEqual(log["restore_status"], "none")
        self.assertTrue(log["integrity_hash"])

        from database.database import get_session

        with get_session() as session:
            cari = session.get(Cari, c.id)
            self.assertTrue(cari.is_deleted)
            self.assertFalse(cari.aktif)
            self.assertIsNotNone(cari.deletion_log_id)
            kayit = session.get(DeletedRecordLog, log["id"])
            self.assertIsNotNone(kayit)
            self.assertEqual(kayit.company_id, 42)

    def test_rollback_if_error_mid_delete(self):
        c = self._cari("C002")
        # Kritik onay yanlış → hata; kayıt silinmemeli / log oluşmamalı
        with self.assertRaises(SoftDeleteError):
            AuditDeleteService.delete_record(
                ENTITY_CARI,
                c.id,
                reason="Test verisi",
                critical_confirm="YANLIS",
            )
        from database.database import get_session

        with get_session() as session:
            cari = session.get(Cari, c.id)
            self.assertFalse(bool(cari.is_deleted))
            n = session.scalar(select(DeletedRecordLog).limit(1))
            # get_session commits on success; failed transaction should roll back
            # SoftDeleteError raised inside with get_session → rollback
            logs = list(session.scalars(select(DeletedRecordLog)).all())
            self.assertEqual(len(logs), 0)

    def test_no_delete_without_log_and_cannot_delete_twice(self):
        c = self._cari("C003")
        AuditDeleteService.delete_record(
            ENTITY_CARI, c.id, reason="Yanlış kayıt", critical_confirm="C003"
        )
        with self.assertRaises(SoftDeleteError):
            AuditDeleteService.delete_record(
                ENTITY_CARI, c.id, reason="Yanlış kayıt", critical_confirm="C003"
            )

    def test_restore_once_second_fails(self):
        c = self._cari("C004")
        log = AuditDeleteService.delete_record(
            ENTITY_CARI, c.id, reason="Test verisi", critical_confirm="C004"
        )
        RestoreService.restore_record(log["id"])
        from database.database import get_session

        with get_session() as session:
            cari = session.get(Cari, c.id)
            self.assertFalse(bool(cari.is_deleted))
            self.assertTrue(cari.aktif)
        with self.assertRaises(SoftDeleteError):
            RestoreService.restore_record(log["id"])

    def test_hash_tamper_detection(self):
        c = self._cari("C005")
        log = AuditDeleteService.delete_record(
            ENTITY_CARI, c.id, reason="Test verisi", critical_confirm="C005"
        )
        from database.database import get_session

        with get_session() as session:
            kayit = session.get(DeletedRecordLog, log["id"])
            kayit.snapshot_json = '{"tampered": true}'
            session.flush()
            self.assertFalse(AuditDeleteService.verify_log_integrity(kayit))
        # restore engellenmeli
        with self.assertRaises(SoftDeleteError):
            RestoreService.restore_record(log["id"])

    def test_json_decimal_date_serialization(self):
        payload = {
            "tutar": Decimal("12.50"),
            "tarih": date(2024, 1, 15),
            "saat": datetime(2024, 1, 15, 10, 30, 0),
            "parola": "gizli",
            "nested": {"api_key": "xyz", "ok": True},
        }
        raw = dumps_safe(payload)
        data = loads_json(raw)
        self.assertEqual(data["tutar"], "12.50")
        self.assertEqual(data["tarih"], "2024-01-15")
        self.assertEqual(data["parola"], "***")
        self.assertEqual(data["nested"]["api_key"], "***")
        clean = sanitize_snapshot({"password_hash": "abc", "ad": "x"})
        self.assertEqual(clean["password_hash"], "***")
        self.assertEqual(clean["ad"], "x")

    def test_company_isolation_for_search(self):
        c = self._cari("C006")
        AuditDeleteService.delete_record(
            ENTITY_CARI, c.id, reason="Test verisi", critical_confirm="C006"
        )
        # aynı DB'de başka company_id ile log arama boş dönmeli
        data = AuditDeleteService.search_deleted_records(company_id=999, page=1, page_size=10)
        self.assertEqual(data["total"], 0)
        data_ok = AuditDeleteService.search_deleted_records(company_id=42, page=1, page_size=10)
        self.assertGreaterEqual(data_ok["total"], 1)

    def test_stok_soft_delete(self):
        s = self._stok()
        log = AuditDeleteService.delete_record(
            ENTITY_STOK, s.id, reason="Mükerrer kayıt", critical_confirm=s.stok_kodu
        )
        self.assertEqual(log["module"], "stok")
        from database.database import get_session

        with get_session() as session:
            stok = session.get(StokKarti, s.id)
            self.assertTrue(stok.is_deleted)

    def test_integrity_hash_stable(self):
        now = datetime(2024, 5, 1, 12, 0, 0)
        h1 = compute_integrity_hash(
            company_id=1,
            entity_type="cari",
            record_id="5",
            deleted_at=now,
            snapshot_json="{}",
            deletion_reason="Test",
            deleted_by_user_id=1,
        )
        h2 = compute_integrity_hash(
            company_id=1,
            entity_type="cari",
            record_id="5",
            deleted_at=now,
            snapshot_json="{}",
            deletion_reason="Test",
            deleted_by_user_id=1,
        )
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_cancel_log_satis_siparis(self):
        from database.models.satis_siparisi import SatisSiparisi
        from database.deleted_record_service import (
            ENTITY_SATIS_SIPARIS,
            AuditDeleteService,
            safe_log_cancel,
        )
        from database.database import get_session

        cari = self._cari(kod="C-CANCEL", unvan="Cancel Test")
        with get_session() as session:
            sip = SatisSiparisi(
                siparis_no=f"SIP-TEST-{datetime.now():%H%M%S%f}",
                siparis_tarihi=date.today(),
                termin_tarihi=date.today(),
                cari_id=cari.id,
                maliyet_yontemi="FIFO",
                hedef_kar_marji=Decimal("0"),
                durum="İPTAL",
            )
            session.add(sip)
            session.flush()
            sid = int(sip.id)

        log = safe_log_cancel(ENTITY_SATIS_SIPARIS, sid, note="test iptal")
        self.assertIsNotNone(log)
        self.assertEqual(log["deletion_type"], "cancel")
        self.assertFalse(log["can_restore"])
        detay = AuditDeleteService.get_deleted_record_detail(log["id"])
        self.assertEqual(detay["entity_type"], ENTITY_SATIS_SIPARIS)

    def test_purge_skips_active_soft_delete(self):
        """Aktif soft-delete log purge adayı olmamalı; iptal log purge edilebilir."""
        from database.deleted_record_service import safe_log_cancel_snapshot

        cari = self._cari(kod="C-PURGE", unvan="Purge Test")
        AuditDeleteService.delete_record(
            ENTITY_CARI,
            cari.id,
            reason="Test verisi",
            note="aktif soft",
            critical_confirm=cari.cari_kodu,
        )
        snap_log = safe_log_cancel_snapshot(
            "cari_virman",
            "VRM-TEST-1",
            note="test",
            snapshot={"entity": {"belge_no": "VRM-TEST-1"}, "related": []},
            record_code="VRM-TEST-1",
            record_title="Test virman",
            module="cari",
        )
        self.assertIsNotNone(snap_log)
        # Silme tarihini eskiye çek
        from database.database import get_session
        from database.models.deleted_record import DeletedRecordLog

        with get_session() as session:
            log = session.get(DeletedRecordLog, snap_log["id"])
            log.deleted_at = datetime(2020, 1, 1, 12, 0, 0)
            # hash yenile
            from database.deleted_record_service import compute_integrity_hash

            log.integrity_hash = compute_integrity_hash(
                company_id=log.company_id,
                entity_type=log.entity_type,
                record_id=log.record_id,
                deleted_at=log.deleted_at,
                snapshot_json=log.snapshot_json,
                deletion_reason=log.deletion_reason,
                deleted_by_user_id=log.deleted_by_user_id,
            )
            session.flush()

        aday = AuditDeleteService.count_purge_candidates(before_date=date(2021, 1, 1))
        self.assertGreaterEqual(aday, 1)
        sonuc = AuditDeleteService.purge_old_logs(
            before_date=date(2021, 1, 1),
            confirm_phrase="SİL",
            expected_count=aday,
        )
        self.assertGreaterEqual(sonuc["purged"], 1)
        # Soft-delete cari hâlâ silinmiş durumda ve logu duruyor olmalı
        with get_session() as session:
            c = session.get(Cari, cari.id)
            self.assertTrue(c.is_deleted)
            aktif_log = session.scalar(
                select(DeletedRecordLog).where(
                    DeletedRecordLog.entity_type == ENTITY_CARI,
                    DeletedRecordLog.record_id == str(cari.id),
                    DeletedRecordLog.restore_status == "none",
                )
            )
            self.assertIsNotNone(aktif_log)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SilinenKayitlarTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        for test, err in result.failures + result.errors:
            print("---", test)
            print(err)
        sys.exit(1)
    print(f"\nOK: {result.testsRun} tests passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
