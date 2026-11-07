"""Backend'e göre SQL yardımcıları — SQLAlchemy inspect / dialect (PRAGMA yok)."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine


def dialect_name(baglanti: Engine | Connection) -> str:
    eng = baglanti if isinstance(baglanti, Engine) else baglanti.engine
    return (eng.dialect.name or "").lower()


def sqlite_mi(baglanti: Engine | Connection) -> bool:
    return dialect_name(baglanti) == "sqlite"


def postgres_mi(baglanti: Engine | Connection) -> bool:
    return dialect_name(baglanti) in ("postgresql", "postgres")


def _inspector(baglanti: Engine | Connection):
    return inspect(baglanti) if isinstance(baglanti, Engine) else inspect(baglanti.engine)


def tablo_var_mi(conn: Connection, tablo: str) -> bool:
    """Tablo adı güvenli (yalnız tanımlayıcı)."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    return _inspector(conn).has_table(ad)


def kolon_adlari(conn: Connection, tablo: str) -> list[str]:
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    return [c["name"] for c in _inspector(conn).get_columns(ad)]


def indeks_adlari(conn: Connection | Engine, tablo: str) -> set[str]:
    """Tablodaki indeks adları (unique constraint indeksleri dahil dialect'e göre)."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    insp = _inspector(conn)
    if not insp.has_table(ad):
        return set()
    adlar = {ix["name"] for ix in insp.get_indexes(ad) if ix.get("name")}
    for uc in insp.get_unique_constraints(ad):
        if uc.get("name"):
            adlar.add(uc["name"])
    return adlar


def benzersiz_kolon_indeksi_var_mi(
    conn: Connection | Engine, tablo: str, kolonlar: list[str]
) -> bool:
    """Unique index veya unique constraint kolon listesi birebir eşleşiyor mu."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    if not ad or ad != tablo:
        raise ValueError(f"Geçersiz tablo adı: {tablo!r}")
    hedef = list(kolonlar)
    insp = _inspector(conn)
    if not insp.has_table(ad):
        return False
    for ix in insp.get_indexes(ad):
        if ix.get("unique") and list(ix.get("column_names") or []) == hedef:
            return True
    for uc in insp.get_unique_constraints(ad):
        if list(uc.get("column_names") or []) == hedef:
            return True
    return False
