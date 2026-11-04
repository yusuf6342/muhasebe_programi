"""PostgreSQL yardımcıları: tr_norm fonksiyonu, boş DB kontrolü, sequence ayarı."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

TR_NORM_SQL = """
CREATE OR REPLACE FUNCTION tr_norm(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $fn$
  SELECT CASE
    WHEN t IS NULL THEN NULL
    ELSE lower(
      translate(
        replace(t, U&'\\0307', ''),
        'İIıŞşĞğÜüÖöÇç',
        'iiissgguuoocc'
      )
    )
  END
$fn$;
"""


def postgres_tr_norm_kur(baglanti: Engine | Connection) -> None:
    eng = baglanti if isinstance(baglanti, Engine) else baglanti.engine
    if eng.dialect.name not in ("postgresql", "postgres"):
        return
    if isinstance(baglanti, Engine):
        with baglanti.begin() as conn:
            conn.execute(text(TR_NORM_SQL))
    else:
        baglanti.execute(text(TR_NORM_SQL))


def pg_public_tablo_sayisi(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalar()
        or 0
    )


def pg_hedef_bos_mu(engine: Engine) -> bool:
    with engine.connect() as conn:
        return pg_public_tablo_sayisi(conn) == 0


def pg_sequence_ayarla(conn: Connection, tablo: str, id_kolon: str = "id") -> None:
    """SERIAL/identity kolonunu mevcut MAX(id) sonrasına alır."""
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    kol = "".join(c for c in id_kolon if c.isalnum() or c == "_")
    if ad != tablo or kol != id_kolon:
        raise ValueError("Geçersiz tablo/kolon")
    seq = conn.execute(
        text("SELECT pg_get_serial_sequence(:t, :c)"),
        {"t": ad, "c": kol},
    ).scalar()
    if not seq:
        return
    mx = conn.execute(text(f'SELECT MAX("{kol}") FROM "{ad}"')).scalar()
    if mx is None:
        return
    conn.execute(text("SELECT setval(:s, :v, true)"), {"s": seq, "v": int(mx)})


def pg_tr_norm_dosya() -> Path:
    return Path(__file__).with_name("pg_tr_norm.sql")
