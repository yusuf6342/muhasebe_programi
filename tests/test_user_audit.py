"""Belge denetim kaydı (audit_document) system.db audit_logs tablosuna yazılır."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import database.database as dbm  # noqa: E402
from database.system.bootstrap import system_engine_olustur, system_tablolari_olustur  # noqa: E402
from database.system.models import AuditLog  # noqa: E402
from database.user_audit import audit_document  # noqa: E402


class AuditDocumentTest(unittest.TestCase):
    """Geçici system.db'ye yazar.

    ``MUHASEBE_DB_DIR`` ortam değişkeni, ``database.database`` daha önce içe aktarıldıysa (toplu
    pytest çalıştırması) etkisizdir; bu yüzden sistem oturumu doğrudan geçici veritabanına bağlanır.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="cin_user_audit_")
        cls._engine = system_engine_olustur(Path(cls._tmp.name) / "system.db")
        system_tablolari_olustur(cls._engine)
        cls._onceki = dbm.SystemSessionLocal
        dbm.SystemSessionLocal = sessionmaker(bind=cls._engine, autoflush=False, autocommit=False,
                                              expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        dbm.SystemSessionLocal = cls._onceki
        cls._engine.dispose()
        cls._tmp.cleanup()

    def test_audit_document_kayit_yazar(self):
        self.assertIn(Path(self._tmp.name).resolve().as_posix(), str(self._engine.url))
        audit_document(
            "BELGE_ONAY",
            modul="satis_faturasi",
            kayit_id="42",
            belge_no="TST-0001",
            yeni={"durum": "ONAYLANDI"},
        )
        with dbm.get_system_session() as s:
            kayit = s.scalars(
                select(AuditLog).where(AuditLog.modul == "satis_faturasi", AuditLog.kayit_id == "42")
            ).first()
            self.assertIsNotNone(kayit)
            self.assertEqual(kayit.islem_turu, "BELGE_ONAY")
            self.assertEqual(json.loads(kayit.yeni_deger)["belge_no"], "TST-0001")


if __name__ == "__main__":
    unittest.main()
