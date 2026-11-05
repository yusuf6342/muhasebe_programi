"""PG deneme: id kolonlarında eksik SERIAL/IDENTITY default'larını onar.

SQLite aktarımında PK sequence oluşmuş ama column DEFAULT bağlanmamış olabilir.
Yalnız deneme/kabul DB'lerinde çalışır; canlı DB adlarını reddeder.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
)
from database.engine_factory import firma_engine_olustur, sistem_engine_olustur  # noqa: E402
from sqlalchemy import text  # noqa: E402

ALLOWED = {
    "cin_sistem_deneme",
    "cin_firma_deneme",
    "cin_sistem_kabul_20261105",
    "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105",
    "cin_firma_restore_20261105",
}


def _ayar(db: str, *, sistem: bool) -> BaglantiAyari:
    return BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host="192.168.1.114",
            port=5432,
            sistem_db="cin_sistem_deneme" if not sistem else db,
            kullanici="cin_app",
            sslmode="require",
            ortam="DENEME",
            firma_db=db if not sistem else None,
        ),
    )


def _onar(eng, dbname: str) -> dict:
    out = {"db": dbname, "tablolar": [], "duzeltilen": [], "zaten_ok": [], "hatalar": []}
    with eng.connect() as c:
        tabs = c.execute(
            text(
                """
                SELECT c.table_name, c.column_name, c.column_default,
                       c.data_type, c.is_nullable
                FROM information_schema.columns c
                JOIN information_schema.table_constraints tc
                  ON tc.table_schema=c.table_schema AND tc.table_name=c.table_name
                JOIN information_schema.key_column_usage kcu
                  ON kcu.constraint_name=tc.constraint_name
                 AND kcu.table_schema=c.table_schema
                 AND kcu.column_name=c.column_name
                WHERE c.table_schema='public'
                  AND c.column_name='id'
                  AND tc.constraint_type='PRIMARY KEY'
                  AND c.data_type IN ('integer','bigint')
                ORDER BY c.table_name
                """
            )
        ).mappings().all()

    for row in tabs:
        t = row["table_name"]
        default = row["column_default"]
        info = {"tablo": t, "default": default}
        if default and ("nextval" in default or "identity" in (default or "").lower()):
            info["durum"] = "ok"
            out["zaten_ok"].append(t)
            out["tablolar"].append(info)
            continue
        try:
            with eng.begin() as c:
                mx = c.execute(text(f'SELECT COALESCE(MAX(id),0) FROM "{t}"')).scalar()
                seq = f"{t}_id_seq"
                exists = c.execute(
                    text("SELECT 1 FROM pg_class WHERE relname = :s AND relkind = 'S'"),
                    {"s": seq},
                ).scalar()
                if not exists:
                    c.execute(text(f'CREATE SEQUENCE "{seq}"'))
                c.execute(text(f'ALTER SEQUENCE "{seq}" OWNED BY "{t}".id'))
                c.execute(
                    text(f"SELECT setval(:s, :m, true)"),
                    {"s": seq, "m": max(int(mx or 0), 1)},
                )
                # setval(..., true) means next nextval returns m+1; if mx=0 use 1 with is_called false
                if int(mx or 0) == 0:
                    c.execute(text(f"SELECT setval(:s, 1, false)"), {"s": seq})
                else:
                    c.execute(text(f"SELECT setval(:s, :m, true)"), {"s": seq, "m": int(mx)})
                c.execute(
                    text(
                        f'ALTER TABLE "{t}" ALTER COLUMN id SET DEFAULT nextval(\'{seq}\')'
                    )
                )
                # NOT NULL zaten olmalı
            info["durum"] = "duzeltildi"
            info["max_id"] = int(mx or 0)
            info["sequence"] = seq
            out["duzeltilen"].append(t)
        except Exception as exc:
            info["durum"] = "hata"
            info["hata"] = str(exc)[:300]
            out["hatalar"].append(info)
        out["tablolar"].append(info)
    return out


def main() -> int:
    hedefler = [
        ("cin_firma_deneme", False),
        ("cin_sistem_deneme", True),
    ]
    rapor = {"zaman": datetime.now().isoformat(timespec="seconds"), "sonuclar": []}
    for db, sistem in hedefler:
        if db not in ALLOWED:
            continue
        ayar = _ayar(db, sistem=sistem)
        eng = sistem_engine_olustur(ayar) if sistem else firma_engine_olustur(
            ayar, sqlite_path=None, firma_db=db
        )
        try:
            rapor["sonuclar"].append(_onar(eng, db))
        finally:
            eng.dispose()

    yol = ROOT / "kurulum" / "_kabul_sequence_onar.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    ozet = [
        {
            "db": s["db"],
            "duzeltilen": len(s["duzeltilen"]),
            "ok": len(s["zaten_ok"]),
            "hata": len(s["hatalar"]),
            "ornek_duzeltilen": s["duzeltilen"][:10],
        }
        for s in rapor["sonuclar"]
    ]
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0 if all(not s["hatalar"] for s in rapor["sonuclar"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
