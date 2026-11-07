"""Restore DB: SELECT yetkisi ve tahsilat tablo adları."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"


def main() -> int:
    pwd = quote_plus(postgres_parola_al())
    e = create_engine(
        f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/cin_firma_restore_20261105?sslmode=require",
        connect_args={"connect_timeout": 12},
    )
    out: dict = {"ornek": [], "no_select": []}
    with e.connect() as c:
        for t in ("kart_ana_turleri", "kasa_makbuzlari", "satis_faturalari", "kabul_kopma_test"):
            try:
                c.execute(text("SAVEPOINT sp_probe"))
                n = c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                c.execute(text("RELEASE SAVEPOINT sp_probe"))
                out["ornek"].append({"t": t, "ok": True, "n": int(n)})
            except Exception as ex:
                try:
                    c.execute(text("ROLLBACK TO SAVEPOINT sp_probe"))
                except Exception:
                    c.rollback()
                out["ornek"].append({"t": t, "ok": False, "err": str(ex).splitlines()[0][:160]})
        rows = c.execute(
            text(
                "SELECT c.relname, has_table_privilege(current_user, c.oid, 'SELECT') AS sel "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind='r' ORDER BY 1"
            )
        ).fetchall()
        out["no_select"] = [r[0] for r in rows if not r[1]]
        out["tablo_adet"] = len(rows)
    e.dispose()

    e2 = create_engine(
        f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/cin_firma_kabul_20261105?sslmode=require"
    )
    with e2.connect() as c:
        out["tahsil_tabs"] = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name ILIKE '%tahsil%' ORDER BY 1"
                )
            )
        ]
        out["cari_cols"] = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='cari_kartlar' "
                    "AND column_name IN ('notlar','aciklama','not','aciklama_not')"
                )
            )
        ]
        out["stok_cols"] = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='stok_kartlari' "
                    "AND column_name IN ('aciklama','barkod','barkod1','notlar')"
                )
            )
        ]
    e2.dispose()
    yol = ROOT / "kurulum" / "_kabul_restore_grant_probe.json"
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
