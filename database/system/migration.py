"""system.db migration sürüm takibi."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.system.models import SchemaMigration, SystemBase

SYSTEM_SCHEMA_VERSION = "1"


def system_tablolari_olustur(engine) -> None:
    SystemBase.metadata.create_all(engine)


def migration_uygula(session: Session) -> None:
    mevcut = session.scalar(
        select(SchemaMigration).where(SchemaMigration.surum == SYSTEM_SCHEMA_VERSION)
    )
    if mevcut is None:
        session.add(
            SchemaMigration(
                surum=SYSTEM_SCHEMA_VERSION,
                aciklama="İlk sistem şeması: kullanıcı, firma, rol, yetki, audit",
            )
        )
