"""TLS (require / verify-full) + pg_dump yedek (şifre yazdırılmaz)."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
PORT = 5432
USER = "cin_app"
SISTEM = "cin_sistem_deneme"
FIRMA = "cin_firma_deneme"
PG_BIN = Path(r"C:\Program Files\PostgreSQL\17\bin")
YEDEK_KOK = Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "yedekler_pg"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tls_probe(sslmode: str, *, sslrootcert: str | None = None) -> dict:
    pwd = quote_plus(postgres_parola_al())
    q = f"sslmode={sslmode}"
    connect_args: dict = {"connect_timeout": 8}
    if sslrootcert:
        # psycopg connection kw
        connect_args["sslrootcert"] = sslrootcert
        q += f"&sslrootcert={quote_plus(sslrootcert)}"
    url = f"postgresql+psycopg://{USER}:{pwd}@{HOST}:{PORT}/{SISTEM}?{q}"
    out: dict = {"sslmode": sslmode, "host": HOST}
    try:
        eng = create_engine(url, connect_args=connect_args)
        with eng.connect() as c:
            row = c.execute(
                text(
                    "SELECT ssl, version, cipher FROM pg_stat_ssl "
                    "WHERE pid = pg_backend_pid()"
                )
            ).mappings().first()
            out["ok"] = True
            out["pg_stat_ssl"] = dict(row) if row else None
            # libpq info via SHOW
            out["server_version"] = c.execute(text("SHOW server_version")).scalar()
        eng.dispose()
    except Exception as exc:
        out["ok"] = False
        out["hata"] = str(exc)[:500]
    return out


def _dump_db(dbname: str, hedef: Path) -> dict:
    pwd = postgres_parola_al()
    env = os.environ.copy()
    env["PGPASSWORD"] = pwd
    env["PGSSLMODE"] = "require"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PG_BIN / "pg_dump.exe"),
        "-h", HOST,
        "-p", str(PORT),
        "-U", USER,
        "-Fc",
        "-f", str(hedef),
        dbname,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    info = {
        "db": dbname,
        "dosya": str(hedef),
        "exit": r.returncode,
        "stderr": (r.stderr or "")[-400:],
    }
    if r.returncode == 0 and hedef.is_file():
        info["boyut"] = hedef.stat().st_size
        info["sha256"] = _sha256(hedef)
        info["mtime"] = datetime.fromtimestamp(hedef.stat().st_mtime).isoformat(timespec="seconds")
    return info


def main() -> int:
    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "hedef": f"{HOST}:{PORT}",
    }

    # CA / sertifika dosyası ara (proje + yaygın yollar; içerik yazılmaz)
    ca_adaylar = [
        ROOT / "kurulum" / "certs" / "root.crt",
        ROOT / "kurulum" / "certs" / "ca.crt",
        Path(os.environ.get("APPDATA", "")) / "postgresql" / "root.crt",
        Path(r"C:\Program Files\PostgreSQL\17\data\root.crt"),
    ]
    rapor["ca_dosyalari"] = {str(p): p.is_file() for p in ca_adaylar}
    ca = next((p for p in ca_adaylar if p.is_file()), None)

    rapor["tls_require"] = _tls_probe("require")
    rapor["tls_verify_full"] = _tls_probe("verify-full")
    if ca:
        rapor["tls_verify_full_with_ca"] = _tls_probe("verify-full", sslrootcert=str(ca))
    # Yanlış host ile reddedilmeli
    pwd = quote_plus(postgres_parola_al())
    bad_url = (
        f"postgresql+psycopg://{USER}:{pwd}@127.0.0.1:{PORT}/{SISTEM}"
        f"?sslmode=verify-full&hostaddr={HOST}"
    )
    # host=yanlış isim — verify-full reddetmeli
    try:
        # Doğrudan yanlış sunucu adı
        bad = _tls_probe.__wrapped__ if False else None  # placeholder
    except Exception:
        pass
    # Manuel yanlış CN: host olarak uydurma ad + hostaddr gerçek IP
    from psycopg import connect as pg_connect

    try:
        conninfo = (
            f"host=yanlis-sunucu-adi.local hostaddr={HOST} port={PORT} "
            f"dbname={SISTEM} user={USER} password={postgres_parola_al()} "
            f"sslmode=verify-full connect_timeout=8"
        )
        with pg_connect(conninfo) as conn:
            conn.execute("SELECT 1")
        rapor["tls_yanlis_host_red"] = {"ok": False, "hata": "beklenmeyen_basari"}
    except Exception as exc:
        rapor["tls_yanlis_host_red"] = {"ok": True, "reddedildi": True, "hata": str(exc)[:300]}

    etiket = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    klasor = YEDEK_KOK / f"pg_kume_kabul_{etiket}"
    rapor["yedek"] = {
        "klasor": str(klasor),
        "sistem": _dump_db(SISTEM, klasor / f"{SISTEM}.dump"),
        "firma": _dump_db(FIRMA, klasor / f"{FIRMA}.dump"),
    }
    (klasor / "KUME.json").write_text(
        json.dumps(
            {
                "zaman": etiket,
                "host": HOST,
                "sistem_db": SISTEM,
                "firma_db": FIRMA,
                "not": "Tutarlı küme; yazmalar dump sırasında durdurulmadıysa anlık fark olabilir",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    yol = ROOT / "kurulum" / "_kabul_tls_yedek.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    ozet = {
        "tls_require_ok": rapor["tls_require"].get("ok"),
        "tls_require_ver": (rapor["tls_require"].get("pg_stat_ssl") or {}).get("version"),
        "tls_verify_full_ok": rapor["tls_verify_full"].get("ok"),
        "tls_verify_full_hata": (rapor["tls_verify_full"].get("hata") or "")[:160],
        "yanlis_host_red": rapor["tls_yanlis_host_red"].get("reddedildi"),
        "yedek_sistem_exit": rapor["yedek"]["sistem"].get("exit"),
        "yedek_firma_exit": rapor["yedek"]["firma"].get("exit"),
        "yedek_sistem_sha": rapor["yedek"]["sistem"].get("sha256"),
        "yedek_firma_sha": rapor["yedek"]["firma"].get("sha256"),
        "yedek_klasor": str(klasor),
    }
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
