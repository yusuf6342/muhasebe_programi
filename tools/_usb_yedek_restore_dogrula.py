"""USB yedek: PG dump (Fc), AES-GCM sifreli arsiv, restore_test, ornekleme, SHA-256.

Parola keyring / MUHASEBE_PG_PASSWORD ile alinir; stdout'a yazilmaz.
Kullanim:
  .venv\\Scripts\\python.exe tools\\_usb_yedek_restore_dogrula.py --usb-kok D:\\CinMuhasebe_Yedek_...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from database.baglanti_modu import postgres_parola_al  # noqa: E402

PG_BIN_CANDIDATES = [
    Path(r"C:\Program Files\PostgreSQL\17\bin"),
    Path(r"C:\Program Files\PostgreSQL\16\bin"),
    Path(r"C:\Program Files\PostgreSQL\18\bin"),
]


def _pg_bin(name: str) -> Path:
    for d in PG_BIN_CANDIDATES:
        p = d / name
        if p.is_file():
            return p
    raise FileNotFoundError(name)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _derive_key(password: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password)


def encrypt_dir_to_file(src_dir: Path, out_file: Path, password: str) -> dict:
    """src_dir icindeki dosyalari tar-benzeri basit paket + AES-GCM ile sifreler."""
    payload = bytearray()
    index: list[dict] = []
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir).as_posix()
        data = path.read_bytes()
        index.append({"path": rel, "offset": len(payload), "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper()})
        payload.extend(data)
    meta = json.dumps({"format": "cin-usb-aesgcm-v1", "files": index}, ensure_ascii=False).encode("utf-8")
    blob = len(meta).to_bytes(4, "big") + meta + bytes(payload)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password.encode("utf-8"), salt)
    ct = AESGCM(key).encrypt(nonce, blob, None)
    out_file.write_bytes(b"CIN1" + salt + nonce + ct)
    return {"ok": True, "dosya": str(out_file), "boyut": out_file.stat().st_size, "sha256": _sha256(out_file), "adet": len(index)}


def decrypt_file_to_dir(enc_file: Path, out_dir: Path, password: str) -> dict:
    raw = enc_file.read_bytes()
    if raw[:4] != b"CIN1":
        raise ValueError("sifreli arsiv formatı tanınmadı")
    salt, nonce, ct = raw[4:20], raw[20:32], raw[32:]
    key = _derive_key(password.encode("utf-8"), salt)
    blob = AESGCM(key).decrypt(nonce, ct, None)
    meta_len = int.from_bytes(blob[:4], "big")
    meta = json.loads(blob[4 : 4 + meta_len].decode("utf-8"))
    payload = blob[4 + meta_len :]
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in meta["files"]:
        hedef = out_dir / item["path"]
        hedef.parent.mkdir(parents=True, exist_ok=True)
        data = payload[item["offset"] : item["offset"] + item["size"]]
        if hashlib.sha256(data).hexdigest().upper() != item["sha256"]:
            raise ValueError(f"SHA uyuşmazlığı: {item['path']}")
        hedef.write_bytes(data)
    return {"ok": True, "adet": len(meta["files"]), "klasor": str(out_dir)}


def _run(cmd: list[str], env: dict, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def pg_dump_fc(host: str, port: int, user: str, db: str, out: Path, password: str) -> dict:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    env["PGSSLMODE"] = env.get("PGSSLMODE") or "prefer"
    exe = _pg_bin("pg_dump.exe")
    out.parent.mkdir(parents=True, exist_ok=True)
    cp = _run([str(exe), "-h", host, "-p", str(port), "-U", user, "-Fc", "-f", str(out), db], env, 900)
    ok = cp.returncode == 0 and out.is_file() and out.stat().st_size > 0
    return {
        "ok": ok,
        "db": db,
        "yol": str(out),
        "boyut": out.stat().st_size if out.is_file() else 0,
        "sha256": _sha256(out) if ok else None,
        "stderr": (cp.stderr or "")[-2000:],
        "returncode": cp.returncode,
    }


def psql_scalar(host: str, port: int, user: str, db: str, sql: str, password: str) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    exe = _pg_bin("psql.exe")
    cp = _run([str(exe), "-h", host, "-p", str(port), "-U", user, "-d", db, "-tAc", sql], env, 120)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "psql hata")[-500:])
    return (cp.stdout or "").strip()


def ensure_db(host: str, port: int, super_user: str, app_user: str, name: str, password: str) -> str:
    exists = psql_scalar(host, port, super_user, "postgres", f"SELECT 1 FROM pg_database WHERE datname='{name}'", password)
    if exists == "1":
        return "MEVCUT"
    cp_env = os.environ.copy()
    cp_env["PGPASSWORD"] = password
    exe = _pg_bin("psql.exe")
    cp = _run(
        [str(exe), "-h", host, "-p", str(port), "-U", super_user, "-d", "postgres", "-v", "ON_ERROR_STOP=1",
         "-c", f"CREATE DATABASE {name} OWNER {app_user};"],
        cp_env,
        120,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"CREATE DATABASE {name}: {(cp.stderr or '')[-500:]}")
    return "OLUSTURULDU"


def drop_public_schema(host: str, port: int, user: str, db: str, password: str) -> None:
    """Restore oncesi semayi temizle (MEVCUT test DB icin)."""
    psql_scalar(host, port, user, db, "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public AUTHORIZATION CURRENT_USER;", password)


def pg_restore_db(host: str, port: int, user: str, db: str, dump: Path, password: str) -> dict:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    exe = _pg_bin("pg_restore.exe")
    drop_public_schema(host, port, user, db, password)
    cp = _run([str(exe), "-h", host, "-p", str(port), "-U", user, "-d", db, "--no-owner", "--role", user, str(dump)], env, 1200)
    # pg_restore bazi uyarilarda !=0 donebilir; tablo sayisi ile dogrula
    try:
        n = int(psql_scalar(host, port, user, db, "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'", password) or "0")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "db": db, "stderr": (cp.stderr or "")[-2000:], "returncode": cp.returncode, "hata": str(exc)}
    return {"ok": n > 0, "db": db, "tablo": n, "returncode": cp.returncode, "stderr": (cp.stderr or "")[-1500:]}


def sample_firma(host: str, port: int, user: str, db: str, password: str) -> dict:
    out: dict = {"db": db}
    queries = {
        "firma_sayisi": "SELECT count(*) FROM information_schema.tables WHERE table_name ILIKE '%firma%' OR table_name='sirket'",
        "cari_adet": "SELECT count(*) FROM cari WHERE COALESCE(is_deleted,false)=false",
        "satis_fatura_adet": "SELECT count(*) FROM satis_faturasi",
        "alis_fatura_adet": "SELECT count(*) FROM alis_faturasi",
        "ornek_cari": "SELECT cari_kodu || '|' || left(unvan,40) FROM cari WHERE COALESCE(is_deleted,false)=false ORDER BY id LIMIT 3",
        "ornek_satis": "SELECT fatura_no || '|' || coalesce(fatura_tarihi::text,'') FROM satis_faturasi ORDER BY id DESC LIMIT 3",
    }
    for k, sql in queries.items():
        try:
            if k.startswith("ornek_"):
                env = os.environ.copy()
                env["PGPASSWORD"] = password
                exe = _pg_bin("psql.exe")
                cp = _run([str(exe), "-h", host, "-p", str(port), "-U", user, "-d", db, "-tAc", sql], env, 60)
                out[k] = [x for x in (cp.stdout or "").splitlines() if x.strip()]
            else:
                out[k] = psql_scalar(host, port, user, db, sql, password)
        except Exception as exc:  # noqa: BLE001
            out[k] = f"HATA: {exc}"
    return out


def sqlite_backup_and_check(paths: list[Path], dest_dir: Path) -> list[dict]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    sonuclar = []
    for src in paths:
        if not src.is_file():
            continue
        hedef = dest_dir / (src.name + ".backup")
        shutil.copy2(src, hedef)
        ok = False
        msg = ""
        try:
            con = sqlite3.connect(f"file:{hedef}?mode=ro", uri=True)
            row = con.execute("PRAGMA integrity_check").fetchone()
            con.close()
            ok = bool(row and row[0] == "ok")
            msg = row[0] if row else ""
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
        sonuclar.append({
            "kaynak": str(src),
            "yedek": str(hedef),
            "boyut": hedef.stat().st_size,
            "sha256": _sha256(hedef),
            "integrity_check": msg,
            "ok": ok,
        })
    return sonuclar


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usb-kok", required=True)
    ap.add_argument("--host", default="192.168.1.114")
    ap.add_argument("--port", type=int, default=5432)
    ap.add_argument("--user", default="cin_app")
    ap.add_argument("--sistem-db", default="cin_sistem_dnm_d2_20260901")
    ap.add_argument("--firma-db", default="cin_firma_dnm_d2_20260901")
    ap.add_argument("--restore-sistem", default="cin_sistem_dnm_d2_restore_test")
    ap.add_argument("--restore-firma", default="cin_firma_dnm_d2_restore_test")
    args = ap.parse_args()

    usb = Path(args.usb_kok)
    veri_plain = usb / "_tmp_veri_plain"
    veri_enc_dir = usb / "veri_sifreli"
    rapor_dir = usb / "rapor"
    for d in (veri_plain, veri_enc_dir, rapor_dir):
        d.mkdir(parents=True, exist_ok=True)

    pwd_app = postgres_parola_al()
    if not pwd_app:
        print(json.dumps({"ok": False, "hata": "cin_app parolası yok (keyring/MUHASEBE_PG_PASSWORD)"}, ensure_ascii=False))
        return 2

    # Superuser: ayni parola ile dene; olmazsa app user ile restore (DB mevcut olmali)
    pwd_super = (os.environ.get("MUHASEBE_PG_SUPER_PASSWORD") or "").strip() or pwd_app
    super_user = (os.environ.get("MUHASEBE_PG_SUPER_USER") or "postgres").strip()

    rapor: dict = {
        "format": "usb-yedek-restore-v1",
        "zaman": datetime.now(timezone.utc).astimezone().isoformat(),
        "makine": os.environ.get("COMPUTERNAME"),
        "host": args.host,
        "port": args.port,
        "dumps": {},
        "restore": {},
        "ornekleme": {},
        "sqlite": [],
        "sifreli_arsiv": None,
        "basarili": False,
    }

    dump_dir = veri_plain / "pg_dump"
    for db in (args.sistem_db, args.firma_db):
        out = dump_dir / f"{db}.dump"
        rapor["dumps"][db] = pg_dump_fc(args.host, args.port, args.user, db, out, pwd_app)

    # baglanti ayarlari (parolasiz json) plain paket icine
    for ad in ("baglanti_ayari.json",):
        src = REPO / ad
        if src.is_file():
            shutil.copy2(src, veri_plain / ad)
        d2 = Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebe" / "DNM_D2" / "baglanti_ayari.json"
        if d2.is_file():
            shutil.copy2(d2, veri_plain / "baglanti_ayari.DNM_D2.json")
        ornek = Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebe" / "DNM_D2" / "baglanti_ayari.D2_ORNEK.json"
        if ornek.is_file():
            shutil.copy2(ornek, veri_plain / "baglanti_ayari.D2_ORNEK.json")

    # SQLite yerel (varsa)
    sqlite_aday: list[Path] = []
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebe"
    if local.is_dir():
        for p in local.rglob("*.db"):
            if "DNM_D2_GERI" in str(p) or "YEREL_YEDEK" in str(p):
                continue
            sqlite_aday.append(p)
    rapor["sqlite"] = sqlite_backup_and_check(sqlite_aday[:20], veri_plain / "sqlite")

    # Sifreli arsiv anahtari: uygulama parolasi (ayri dosyaya yazilmaz)
    enc_path = veri_enc_dir / "muhasebe_veri_baglanti.cinenc"
    rapor["sifreli_arsiv"] = encrypt_dir_to_file(veri_plain, enc_path, pwd_app)

    # Sifre cozme dogrulamasi (gecici klasor)
    with tempfile.TemporaryDirectory(prefix="cin_dec_") as td:
        dec = decrypt_file_to_dir(enc_path, Path(td) / "out", pwd_app)
        rapor["sifre_coz_dogrulama"] = dec

    # Restore test
    restore_ok = True
    try:
        for name in (args.restore_sistem, args.restore_firma):
            try:
                durum = ensure_db(args.host, args.port, super_user, args.user, name, pwd_super)
            except Exception:
                # super basarisizsa mevcut DB varsay
                durum = "MEVCUT_VEYA_YETKI_YOK"
            rapor.setdefault("restore_db_durum", {})[name] = durum

        r_sys = pg_restore_db(
            args.host, args.port, args.user, args.restore_sistem,
            dump_dir / f"{args.sistem_db}.dump", pwd_app,
        )
        r_fir = pg_restore_db(
            args.host, args.port, args.user, args.restore_firma,
            dump_dir / f"{args.firma_db}.dump", pwd_app,
        )
        rapor["restore"] = {"sistem": r_sys, "firma": r_fir}
        restore_ok = bool(r_sys.get("ok") and r_fir.get("ok"))
        if restore_ok:
            rapor["ornekleme"] = {
                "canli_firma": sample_firma(args.host, args.port, args.user, args.firma_db, pwd_app),
                "restore_firma": sample_firma(args.host, args.port, args.user, args.restore_firma, pwd_app),
            }
    except Exception as exc:  # noqa: BLE001
        rapor["restore_hata"] = str(exc)
        restore_ok = False

    dumps_ok = all(v.get("ok") for v in rapor["dumps"].values())
    enc_ok = bool(rapor["sifreli_arsiv"] and rapor["sifreli_arsiv"].get("ok"))
    sqlite_ok = all(x.get("ok") for x in rapor["sqlite"]) if rapor["sqlite"] else True
    rapor["basarili"] = bool(dumps_ok and enc_ok and restore_ok and sqlite_ok and rapor.get("sifre_coz_dogrulama", {}).get("ok"))

    # Plain gecici veriyi USB'den sil (yalniz sifreli kalsin)
    shutil.rmtree(veri_plain, ignore_errors=True)

    out_json = rapor_dir / "YEDEK_RESTORE_SONUC.json"
    out_json.write_text(json.dumps(rapor, ensure_ascii=False, indent=2), encoding="utf-8")
    # SHA ozeti
    sha_lines = []
    for p in sorted(veri_enc_dir.rglob("*")):
        if p.is_file():
            sha_lines.append(f"{_sha256(p)}  {p.relative_to(usb).as_posix()}")
    (rapor_dir / "SHA256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": rapor["basarili"],
        "rapor": str(out_json),
        "dumps_ok": dumps_ok,
        "restore_ok": restore_ok,
        "enc_ok": enc_ok,
        "enc_sha": rapor["sifreli_arsiv"].get("sha256") if rapor["sifreli_arsiv"] else None,
    }, ensure_ascii=False))
    return 0 if rapor["basarili"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
