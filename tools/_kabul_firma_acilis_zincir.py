"""Firma açılış hazırlık zinciri (firma_oturumu_ac) — PG DENEME, GUI yok.

Parola yazdırılmaz. SQLite'a düşmez. RAY001 pg: eşlemesini doğrular.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
)
import database.baglanti_modu as bm  # noqa: E402

HOST = "192.168.1.114"
SYS = "cin_sistem_kabul_20261105"
FR = "cin_firma_kabul_20261105"

_AYAR = BaglantiAyari(
    kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
    postgres=PostgresBaglanti(
        host=HOST,
        port=5432,
        sistem_db=SYS,
        kullanici="cin_app",
        sslmode="verify-full",
        ortam="DENEME",
        firma_db=FR,
        terminal_kimligi="KABUL-ZINCIR",
    ),
)
bm.ayari_yukle = lambda program_dir=None: _AYAR  # type: ignore

os.environ["MUHASEBE_DB_DIR"] = str(
    Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeKabulDeneme_20261105" / "data"
)


def main() -> int:
    from sqlalchemy import text

    from database.database import (
        get_system_session,
        pg_firma_tanimi_mi,
        sistem_altyapisini_baslat,
    )
    from database.session_manager import oturum
    from database.system.models import Company, Role, User
    from auth_ui import firma_oturumu_ac, firma_ozet
    from sqlalchemy.orm import selectinload

    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "adimlar": [],
    }

    def adim(ad: str, **kw):
        rapor["adimlar"].append({"ad": ad, **kw})
        print("ADIM", ad, kw, flush=True)

    try:
        sistem_altyapisini_baslat()
        adim("sistem_altyapi", ok=True)
        with get_system_session() as s:
            ray = s.query(Company).filter(Company.firma_kodu == "RAY001").one()
            admin = (
                s.query(User)
                .options(selectinload(User.role))
                .join(Role, User.role_id == Role.id)
                .filter(Role.kod == "YONETICI")
                .order_by(User.id)
                .first()
            )
            rapor["ray"] = {
                "id": ray.id,
                "db_path": ray.db_path,
                "aktif": bool(ray.aktif),
                "pg": pg_firma_tanimi_mi(ray.db_path),
            }
            rapor["admin_id"] = admin.id if admin else None
            if not admin:
                raise RuntimeError("YONETICI kullanici yok")
            # Oturum (sifre dogrulama yok — zincir testi)
            oturum.user_id = admin.id
            oturum.role_kod = "YONETICI"
            oturum.kullanici_adi = getattr(admin, "kullanici_adi", None) or "admin"
        adim("oturum", ok=True, user_id=oturum.user_id)

        if rapor["ray"]["db_path"] != f"pg:{FR}":
            raise RuntimeError(f"RAY001 db_path bozulmus: {rapor['ray']['db_path']}")

        ozet = firma_ozet(ray, donem_yukle=True)
        adim("firma_ozet", ok=True, db_path=ozet.db_path, donem=ozet.aktif_donem)

        firma_oturumu_ac(ozet)
        adim("firma_oturumu_ac", ok=True)

        from database import database as db

        with db.engine.connect() as c:
            dbname = c.execute(text("SELECT current_database()")).scalar()
            cari = int(c.execute(text("SELECT count(*) FROM cari_kartlar")).scalar() or 0)
            # PRAGMA kalmamali — dialect kontrol
            dialect = c.dialect.name
        rapor["acilis"] = {
            "ok": True,
            "dialect": dialect,
            "current_database": dbname,
            "beklenen": FR,
            "eslesme": dbname == FR,
            "cari": cari,
        }
        adim("engine_dogrula", **rapor["acilis"])
        rapor["durum"] = "GECTI" if rapor["acilis"]["eslesme"] else "KALDI"
    except Exception as exc:
        rapor["durum"] = "KALDI"
        rapor["hata"] = str(exc).split("\n")[0][:400]
        rapor["traceback"] = traceback.format_exc()[-2000:]
        print("HATA", rapor["hata"], flush=True)

    yol = ROOT / "kurulum" / "_kabul_firma_acilis_zincir.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"durum": rapor["durum"], "acilis": rapor.get("acilis"), "hata": rapor.get("hata")}, ensure_ascii=False, indent=2))
    print("YAZILDI", yol)
    return 0 if rapor.get("durum") == "GECTI" else 2


if __name__ == "__main__":
    raise SystemExit(main())
