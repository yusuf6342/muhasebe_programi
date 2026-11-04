"""Backend'e göre SQL yardımcıları — SQLite PRAGMA / PostgreSQL information_schema."""

from __future__ import annotations

from sqlalchemy.engine import Connection, Engine


def dialect_name(baglanti: Engine | Connection) -> str:
    eng = baglanti if isinstance(baglanti, Engine) else baglanti.engine
    return (eng.dialect.name or "").lower()


def sqlite_mi(baglanti: Engine | Connection) -> bool:
    return dialect_name(baglanti) == "sqlite"


def postgres_mi(baglanti: Engine | Connection) -> bool:
    return dialect_name(baglanti) in ("postgresql", "postgres")


def tablo_var_mi(conn: Connection, tablo: str) -> bool:
    """Tablo adı güvenli (yalnız tanımlayıcı)."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    if sqlite_mi(conn):
        row = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (ad,),
        ).fetchone()
        return row is not None
    row = conn.exec_driver_sql(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=%s LIMIT 1",
        (ad,),
    ).fetchone()
    return row is not None


def kolon_adlari(conn: Connection, tablo: str) -> list[str]:
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    if sqlite_mi(conn):
        return [r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{ad}")').fetchall()]
    rows = conn.exec_driver_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (ad,),
    ).fetchall()
    return [r[0] for r in rows]
