"""D2 hedef DB pg_dump (yazım öncesi). Restore testini tekrarlamaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_hedef_yedek_al
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from database.baglanti_modu import ayari_yukle, postgres_parola_al
from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
PG_DUMP = Path(r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe")


def main() -> int:
    if not PG_DUMP.is_file():
        print("pg_dump yok:", PG_DUMP)
        return 2
    ayar = ayari_yukle()
    pg = ayar.postgres
    pwd = postgres_parola_al()
    if not pwd:
        print("APP_PAROLA_YOK")
        return 3

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek_dir = CALISMA / "yedek" / f"yazim_oncesi_{stamp}"
    yedek_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PGPASSWORD"] = pwd
    sonuc = {
        "format": "d2-yazim-oncesi-yedek-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": pg.host,
        "klasor": str(yedek_dir),
        "dumps": {},
        "restore_tekrarlanmadi": True,
        "onceki_izolasyon_kaniti": "yedek/CALISTIR_SONUC_ANA_MAKINE_20261107_160153.json",
    }
    ok = True
    for db in (ONERILEN_SISTEM_DB, ONERILEN_FIRMA_DB):
        yol = yedek_dir / f"{db}.dump"
        cmd = [
            str(PG_DUMP),
            "-h",
            pg.host,
            "-p",
            str(pg.port),
            "-U",
            pg.kullanici,
            "-d",
            db,
            "-Fc",
            "-f",
            str(yol),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
        entry = {
            "ok": r.returncode == 0,
            "yol": str(yol),
            "boyut": yol.stat().st_size if yol.is_file() else 0,
            "stderr": (r.stderr or "")[:300],
        }
        sonuc["dumps"][db] = entry
        ok = ok and entry["ok"]
        print(db, "OK" if entry["ok"] else "FAIL", entry["boyut"])

    sonuc["basarili"] = ok
    (yedek_dir / "YEDEK_MANIFEST.json").write_text(
        json.dumps(sonuc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CALISMA / "D2_YAZIM_ONCESI_YEDEK_OZET.json").write_text(
        json.dumps(
            {
                "zaman": sonuc["zaman"],
                "basarili": ok,
                "klasor": str(yedek_dir),
                "restore_tekrarlanmadi": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
