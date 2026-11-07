"""kredi_karti_ekstreleri eksik kolonlar — PG kabul (açılış şema takılmasını önler)."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DB = "cin_firma_kabul_20261105"
KOLONLAR = {
    "son_odeme_manuel": "BOOLEAN DEFAULT FALSE",
    "asgari_tutar": "NUMERIC(18,2)",
    "asgari_odenen": "NUMERIC(18,2)",
}


def main() -> int:
    pwd = quote_plus(postgres_parola_al())
    e = create_engine(
        f"postgresql+psycopg://cin_app:{pwd}@192.168.1.114:5432/{DB}?sslmode=require"
    )
    with e.begin() as c:
        existing = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='kredi_karti_ekstreleri'"
                )
            )
        }
        for col, tip in KOLONLAR.items():
            if col in existing:
                print("ok", col)
                continue
            c.execute(
                text(
                    f'ALTER TABLE kredi_karti_ekstreleri '
                    f'ADD COLUMN IF NOT EXISTS "{col}" {tip}'
                )
            )
            print("added", col, tip)
    e.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
