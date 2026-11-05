"""Ana makine devam: mevcut DB listesi + dump SHA doğrulama."""
from __future__ import annotations

import hashlib
import json
import os
import socket
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
from database.engine_factory import sistem_engine_olustur  # noqa: E402
from sqlalchemy import text  # noqa: E402

DUMP = (
    Path(os.environ["LOCALAPPDATA"])
    / "CinMuhasebeTest"
    / "yedekler_pg"
    / "pg_kume_kabul_2026-11-05_131615"
)
BEK_SHA = {
    "cin_sistem_deneme.dump": "99c70fe00c9d2ed46d6244a74b0c90d6d2f88ed3ce2961cf1ef7670b43f360e7",
    "cin_firma_deneme.dump": "07e6e5fc02040d8e2bc8f5c45edbc55251ad7ab6e07230a5cda93f2619e49af4",
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "super_env": bool(os.environ.get("MUHASEBE_PG_SUPER_PASSWORD")),
        "dump_klasor": str(DUMP),
        "dump_var": DUMP.is_dir(),
        "dump_sha": {},
    }
    for ad, bek in BEK_SHA.items():
        p = DUMP / ad
        if not p.is_file():
            out["dump_sha"][ad] = {"var": False}
            continue
        g = sha256(p)
        out["dump_sha"][ad] = {
            "var": True,
            "boyut": p.stat().st_size,
            "sha256": g,
            "eslesme": g.lower() == bek.lower(),
            "beklenen": bek,
        }

    ayar = BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host="192.168.1.114",
            port=5432,
            sistem_db="cin_sistem_deneme",
            kullanici="cin_app",
            sslmode="require",
            ortam="DENEME",
            firma_db="cin_firma_deneme",
        ),
    )
    eng = sistem_engine_olustur(ayar)
    try:
        with eng.connect() as c:
            out["cin_dbs"] = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'cin_%' ORDER BY 1"
                    )
                )
            ]
            out["companies"] = [
                dict(r)
                for r in c.execute(
                    text(
                        "SELECT id, firma_kodu, db_path, aktif "
                        "FROM companies ORDER BY id"
                    )
                ).mappings()
            ]
            # CREATEDB yetkisi
            out["cin_app_createdb"] = bool(
                c.execute(text("SELECT rolcreatedb FROM pg_roles WHERE rolname='cin_app'")).scalar()
            )
    finally:
        eng.dispose()

    out["kabul_dbs_hazir"] = all(
        n in out.get("cin_dbs", [])
        for n in ("cin_sistem_kabul_20261105", "cin_firma_kabul_20261105")
    )
    out["restore_dbs_hazir"] = all(
        n in out.get("cin_dbs", [])
        for n in ("cin_sistem_restore_20261105", "cin_firma_restore_20261105")
    )

    yol = ROOT / "kurulum" / "_kabul_devam_durum.json"
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print("YAZILDI:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
