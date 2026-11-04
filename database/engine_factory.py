"""SQLite / PostgreSQL engine üretimi — tek giriş noktası.

LAN kipinde bağlantı hatası → Exception; sessiz SQLite fallback YOK.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from database.baglanti_modu import BaglantiAyari, CalismaKipi, postgres_parola_al

_LOG = logging.getLogger("engine_factory")

# Havuz: terminal başına düşük tut; sunucu max_connections ile birlikte planlanır
PG_POOL_SIZE = 3
PG_MAX_OVERFLOW = 2
PG_POOL_TIMEOUT = 30
PG_POOL_RECYCLE = 1800


class AgBaglantiHatasi(RuntimeError):
    """Yerel ağ kipinde sunucuya bağlanılamadı — yazma durdurulur."""


def _sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA cache_size=-65536")
    cur.close()


def sqlite_engine(db_path, *, echo: bool = False) -> Engine:
    url = f"sqlite:///{db_path.resolve().as_posix()}"
    eng = create_engine(
        url,
        echo=echo,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(eng, "connect", _sqlite_pragma)
    return eng


def _pg_connect_hazirlik(dbapi_connection, _connection_record) -> None:
    """İlk bağlantıda tr_norm yoksa kur (her bağda hafif kontrol)."""
    try:
        cur = dbapi_connection.cursor()
        cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'tr_norm' LIMIT 1")
        var = cur.fetchone()
        if not var:
            from database.pg_helpers import TR_NORM_SQL

            cur.execute(TR_NORM_SQL)
        cur.close()
    except Exception:
        _LOG.debug("tr_norm kurulum atlandı", exc_info=True)


def postgres_engine(url: str, *, echo: bool = False) -> Engine:
    eng = create_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=PG_POOL_SIZE,
        max_overflow=PG_MAX_OVERFLOW,
        pool_timeout=PG_POOL_TIMEOUT,
        pool_recycle=PG_POOL_RECYCLE,
    )
    event.listen(eng, "connect", _pg_connect_hazirlik)
    return eng


def sistem_engine_olustur(ayar: BaglantiAyari, *, sqlite_path=None, echo: bool = False) -> Engine:
    if ayar.kipi == CalismaKipi.YEREL_SQLITE.value:
        if sqlite_path is None:
            raise ValueError("SQLite sistem yolu gerekli")
        return sqlite_engine(sqlite_path, echo=echo)
    parola = postgres_parola_al()
    if not parola:
        raise AgBaglantiHatasi(
            "Yerel ağ kipinde PostgreSQL parolası yok. "
            "Bağlantı ayarlarından veya MUHASEBE_PG_PASSWORD ile tanımlayın."
        )
    try:
        eng = postgres_engine(ayar.postgres.dsn_sistem(parola), echo=echo)
        from database.schema_surum import schema_uyum_kontrol

        schema_uyum_kontrol(eng)
        return eng
    except Exception as exc:
        from database.schema_surum import SchemaUyumsuzlugu

        if isinstance(exc, SchemaUyumsuzlugu):
            raise
        raise AgBaglantiHatasi(
            f"Sistem veritabanına bağlanılamadı ({ayar.postgres.ozet()}):\n{exc}"
        ) from exc


def firma_engine_olustur(
    ayar: BaglantiAyari,
    *,
    sqlite_path=None,
    firma_db: str | None = None,
    echo: bool = False,
) -> Engine:
    if ayar.kipi == CalismaKipi.YEREL_SQLITE.value:
        if sqlite_path is None:
            raise ValueError("SQLite firma yolu gerekli")
        return sqlite_engine(sqlite_path, echo=echo)
    parola = postgres_parola_al()
    if not parola:
        raise AgBaglantiHatasi("Yerel ağ kipinde PostgreSQL parolası yok.")
    try:
        return postgres_engine(ayar.postgres.dsn_firma(parola, firma_db), echo=echo)
    except Exception as exc:
        raise AgBaglantiHatasi(
            f"Firma veritabanına bağlanılamadı ({ayar.postgres.ozet()}):\n{exc}"
        ) from exc


def havuz_ozeti() -> dict[str, Any]:
    return {
        "pg_pool_size": PG_POOL_SIZE,
        "pg_max_overflow": PG_MAX_OVERFLOW,
        "pg_pool_timeout": PG_POOL_TIMEOUT,
        "pg_pool_recycle": PG_POOL_RECYCLE,
        "not": "Her terminal kendi havuzunu açar; sunucu max_connections buna göre boyutlandırılmalı.",
    }
