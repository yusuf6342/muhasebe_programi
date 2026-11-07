"""EXE yerine kaynak ile PG DENEME sistem bootstrap + firma listesi duman testi."""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Günlük ayarı değiştirme — yalnız env + geçici bellek
os.environ["MUHASEBE_BAGLANTI_KIPI"] = "yerel_ag_postgres"
os.environ["MUHASEBE_DB_DIR"] = str(
    Path(os.environ["LOCALAPPDATA"]) / "CinMuhasebeKabulDeneme_20261105" / "data"
)

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
    ayari_yukle,
    baglanti_sina,
)
import database.baglanti_modu as bm  # noqa: E402


def main() -> int:
    ayar = BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host="192.168.1.114",
            port=5432,
            sistem_db="cin_sistem_kabul_20261105",
            kullanici="cin_app",
            sslmode="verify-full",
            ortam="DENEME",
            firma_db="cin_firma_kabul_20261105",
            terminal_kimligi="KABUL-SMOKE",
        ),
    )
    bm.ayari_yukle = lambda program_dir=None: ayar  # type: ignore

    rapor = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "baglanti": baglanti_sina(ayar),
    }

    from database.engine_factory import sistem_engine_olustur, firma_engine_olustur
    from sqlalchemy import text

    eng = sistem_engine_olustur(ayar)
    with eng.connect() as c:
        firms = c.execute(
            text(
                "SELECT firma_kodu, unvan, db_path, aktif FROM companies ORDER BY id"
            )
        ).mappings().all()
        users = c.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='users' ORDER BY ordinal_position"
            )
        ).fetchall()
        cols = [r[0] for r in users]
        kullanici_kol = next(
            (c for c in ("kullanici_adi", "username", "email", "ad") if c in cols),
            cols[1] if len(cols) > 1 else "id",
        )
        user_rows = c.execute(
            text(
                f'SELECT id, "{kullanici_kol}" AS kullanici FROM users ORDER BY id LIMIT 5'
            )
        ).mappings().all()
    eng.dispose()

    engf = firma_engine_olustur(ayar, sqlite_path=None, firma_db="cin_firma_kabul_20261105")
    with engf.connect() as c:
        n_cari = c.execute(text("SELECT count(*) FROM cari_kartlar")).scalar()
        n_stok = c.execute(text("SELECT count(*) FROM stok_kartlari")).scalar()
        ornek = c.execute(
            text(
                "SELECT id, unvan FROM cari_kartlar ORDER BY id LIMIT 1"
            )
        ).mappings().first()
    engf.dispose()

    rapor["companies"] = [dict(r) for r in firms]
    rapor["users"] = [dict(r) for r in user_rows]
    rapor["firma_ornek"] = {
        "cari": n_cari,
        "stok": n_stok,
        "ornek_cari": dict(ornek) if ornek else None,
    }
    rapor["durum"] = (
        "GECTI"
        if rapor["baglanti"].get("ok")
        and any(f["firma_kodu"] == "RAY001" and f["aktif"] for f in rapor["companies"])
        else "KALDI"
    )

    # EXE dosya kanıtı + SHA-256
    import hashlib

    def _sha256(p: Path) -> str | None:
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().upper()

    exe = (
        Path(os.environ["LOCALAPPDATA"])
        / "CinMuhasebeKabulDeneme_20261105"
        / "program"
        / "CinMuhasebe.exe"
    )
    dist = ROOT / "dist" / "CinMuhasebe" / "CinMuhasebe.exe"
    sha_exe, sha_dist = _sha256(exe), _sha256(dist)
    rapor["exe"] = {
        "deneme_yol": str(exe),
        "deneme_var": exe.is_file(),
        "deneme_sha256": sha_exe,
        "dist_yol": str(dist),
        "dist_var": dist.is_file(),
        "dist_sha256": sha_dist,
        "sha_eslesme": bool(sha_exe and sha_dist and sha_exe == sha_dist),
        "dist_mtime": datetime.fromtimestamp(dist.stat().st_mtime).isoformat(timespec="seconds")
        if dist.is_file()
        else None,
        "not": "Ana makine (CGSE5GK) EXE SHA bu terminalden admin paylaşımı kapalı; "
        "aynı hash yerelde dist+DENEME profilinde doğrulandı. GUI giriş ayrı.",
    }
    if not rapor["exe"]["sha_eslesme"]:
        rapor["durum"] = "KALDI"

    yol = ROOT / "kurulum" / "_kabul_exe_giris_smoke.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"durum": rapor["durum"], "cari": n_cari, "stok": n_stok, "users": len(user_rows)}, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0 if rapor["durum"] == "GECTI" else 2


if __name__ == "__main__":
    raise SystemExit(main())
