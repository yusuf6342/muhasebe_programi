"""Belge numarası MAX kuyruk sorgusu — SQLite GLOB ve PostgreSQL ~ uyumlu."""

from __future__ import annotations

from sqlalchemy import text


def max_sayisal_kuyruk(session, *, tablo: str, kolon: str, onek: str) -> int:
    """onek + yalnız rakam kuyruklarından en büyük tamsayıyı döner (yoksa 0)."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    kol = "".join(c for c in kolon if c.isalnum() or c == "_")
    if ad != tablo or kol != kolon:
        raise ValueError("Geçersiz tablo/kolon")
    bas = len(onek) + 1
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        sql = (
            f'SELECT MAX(CAST(SUBSTR("{kol}", :bas) AS INTEGER)) FROM "{ad}" '
            f'WHERE "{kol}" LIKE :patern AND SUBSTR("{kol}", :bas) GLOB \'[0-9]*\''
        )
    else:
        # PostgreSQL: SUBSTR 1-based; ~ '^[0-9]+$'
        sql = (
            f'SELECT MAX(CAST(SUBSTR("{kol}", :bas) AS INTEGER)) FROM "{ad}" '
            f'WHERE "{kol}" LIKE :patern AND SUBSTR("{kol}", :bas) ~ \'^[0-9]+$\''
        )
    val = session.execute(
        text(sql),
        {"bas": bas, "patern": f"{onek}%"},
    ).scalar()
    return int(val or 0)
