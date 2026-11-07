"""Terminalden 4 DB'ye sslmode=verify-full bağlantı kanıtı."""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
USER = "cin_app"
DBS = [
    "cin_sistem_kabul_20261105",
    "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105",
    "cin_firma_restore_20261105",
]


def probe(db: str) -> dict:
    pwd = quote_plus(postgres_parola_al())
    ca = Path(os.environ.get("APPDATA", "")) / "postgresql" / "root.crt"
    q = "sslmode=verify-full"
    args: dict = {"connect_timeout": 10}
    if ca.is_file():
        args["sslrootcert"] = str(ca)
        q += f"&sslrootcert={quote_plus(str(ca))}"
    url = f"postgresql+psycopg://{USER}:{pwd}@{HOST}:5432/{db}?{q}"
    out: dict = {"db": db, "sslmode": "verify-full", "ca": str(ca) if ca.is_file() else None}
    try:
        eng = create_engine(url, connect_args=args)
        with eng.connect() as c:
            row = c.execute(
                text(
                    "SELECT ssl, version, cipher FROM pg_stat_ssl "
                    "WHERE pid = pg_backend_pid()"
                )
            ).mappings().first()
            out["ok"] = True
            out["pg_stat_ssl"] = dict(row) if row else None
            out["current_database"] = c.execute(text("SELECT current_database()")).scalar()
        eng.dispose()
    except Exception as exc:
        out["ok"] = False
        out["hata"] = str(exc)[:400]
    return out


def main() -> int:
    rapor = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "host": HOST,
        "sonuclar": [probe(db) for db in DBS],
    }
    rapor["hepsi_ok"] = all(s["ok"] for s in rapor["sonuclar"])
    yol = ROOT / "kurulum" / "_kabul_verify_full_4db.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(
        {"hepsi_ok": rapor["hepsi_ok"], "ozet": [(s["db"], s["ok"], (s.get("pg_stat_ssl") or {}).get("version")) for s in rapor["sonuclar"]]},
        ensure_ascii=False,
        indent=2,
    ))
    print("YAZILDI:", yol)
    return 0 if rapor["hepsi_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
