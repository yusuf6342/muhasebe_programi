"""system.db migration sürüm takibi."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.system.models import SchemaMigration, SystemBase

SYSTEM_SCHEMA_VERSION = "2"


def system_tablolari_olustur(engine) -> None:
    # create_all yalnız eksik tabloları ekler; mevcut kayıtları silmez/değiştirmez
    SystemBase.metadata.create_all(engine)


def migration_uygula(session: Session) -> None:
    surumler = {
        "1": "İlk sistem şeması: kullanıcı, firma, rol, yetki, audit",
        "2": "Firma içi kullanıcı mesajlaşması (konuşma / üye / mesaj)",
    }
    for surum, aciklama in surumler.items():
        mevcut = session.scalar(
            select(SchemaMigration).where(SchemaMigration.surum == surum)
        )
        if mevcut is None:
            session.add(SchemaMigration(surum=surum, aciklama=aciklama))
