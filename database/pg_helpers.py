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
    """id PK için sequence yoksa oluşturur, DEFAULT nextval bağlar, setval(MAX).

    SQLAlchemy Integer PK create_all bazen PG'de SERIAL üretmez; aktarım sonrası
    ham INSERT ve bazı sürücü yolları id NULL hatası verir. Bu fonksiyon eksik
    bağlantıyı onarır; mevcut identity/serial varsa yalnız setval yapar.
    """
    ad = "".join(c for c in tablo if c.isalnum() or c == "_")
    kol = "".join(c for c in id_kolon if c.isalnum() or c == "_")
    if ad != tablo or kol != id_kolon:
        raise ValueError("Geçersiz tablo/kolon")
    seq = conn.execute(
        text("SELECT pg_get_serial_sequence(:t, :c)"),
        {"t": ad, "c": kol},
    ).scalar()
    mx = conn.execute(text(f'SELECT COALESCE(MAX("{kol}"), 0) FROM "{ad}"')).scalar()
    mx_i = int(mx or 0)
    if not seq:
        seq_name = f"{ad}_{kol}_seq"
        exists = conn.execute(
            text("SELECT 1 FROM pg_class WHERE relname = :s AND relkind = 'S'"),
            {"s": seq_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE SEQUENCE "{seq_name}"'))
        conn.execute(text(f'ALTER SEQUENCE "{seq_name}" OWNED BY "{ad}"."{kol}"'))
        conn.execute(
            text(
                f'ALTER TABLE "{ad}" ALTER COLUMN "{kol}" '
                f"SET DEFAULT nextval('{seq_name}')"
            )
        )
        seq = seq_name
    if mx_i <= 0:
        conn.execute(text("SELECT setval(:s, 1, false)"), {"s": seq})
    else:
        conn.execute(text("SELECT setval(:s, :v, true)"), {"s": seq, "v": mx_i})


def pg_tr_norm_dosya() -> Path:
    return Path(__file__).with_name("pg_tr_norm.sql")
