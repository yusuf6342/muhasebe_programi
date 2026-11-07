"""Ana makine PostgreSQL: gerçek bağlantı, DB listesi, yetkiler — parola yazdırılmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.pg_ana_makine_dogrula
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
ANA_HOST_BEKLENEN = "DESKTOP-CGSE5GK"
HEDEF_SISTEM = ONERILEN_SISTEM_DB
HEDEF_FIRMA = ONERILEN_FIRMA_DB
RESTORE_SISTEM = "cin_sistem_dnm_d2_restore_test"
RESTORE_FIRMA = "cin_firma_dnm_d2_restore_test"


def _super_parola() -> str:
    env = (os.environ.get("MUHASEBE_PG_SUPER_PASSWORD") or "").strip()
    if env:
        return env
    try:
        import keyring

        for user in ("postgres_super", "postgres"):
            for svc in ("CinMuhasebe", "PostgreSQL"):
                p = keyring.get_password(svc, user)
                if p:
                    return p
    except Exception:
        pass
    return ""


def _url(host, port, user, password, db, sslmode) -> str:
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?sslmode={sslmode}"
    )


def main() -> int:
    from database.baglanti_modu import ayari_yukle, postgres_parola_al

    (CALISMA / "yedek").mkdir(parents=True, exist_ok=True)
    ayar = ayari_yukle()
    pg = ayar.postgres
    app_pwd = postgres_parola_al() or ""
    out: dict = {
        "format": "d2-pg-ana-makine-dogrula-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bu_pc": {
            "hostname": socket.gethostname(),
            "computername": os.environ.get("COMPUTERNAME"),
            "ana_makine_mi": os.environ.get("COMPUTERNAME") == ANA_HOST_BEKLENEN,
        },
        "baglanti_ayari": {
            "ag_mi": ayar.ag_mi,
            "host": pg.host,
            "port": pg.port,
            "kullanici": pg.kullanici,
            "sistem_db_aktif_profil": pg.sistem_db,
            "firma_db_aktif_profil": getattr(pg, "firma_db", None),
            "sslmode": pg.sslmode,
            "ortam": getattr(pg, "ortam", None),
        },
        "manifest_hedefler": {
            "sistem": HEDEF_SISTEM,
            "firma": HEDEF_FIRMA,
            "restore_sistem": RESTORE_SISTEM,
            "restore_firma": RESTORE_FIRMA,
            "aktif_profil_ile_ayni_degil": True,
        },
        "app_parola": "SET" if app_pwd else "MISSING",
        "super_parola": "SET" if _super_parola() else "MISSING",
        "k05": False,
        "k06": False,
        "mali_yazim": False,
    }

    if not ayar.ag_mi or not app_pwd:
        out["ok"] = False
        out["engel"] = "AG veya app parola yok"
        _yaz(out)
        return 2

    eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, app_pwd, pg.sistem_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )
    with eng.connect() as c:
        row = c.execute(
            text(
                "select current_user, current_database(), "
                "inet_server_addr()::text, inet_server_port(), version()"
            )
        ).one()
        out["canli_baglanti"] = {
            "user": row[0],
            "database": row[1],
            "inet_server_addr": row[2],
            "inet_server_port": row[3],
            "version": (row[4] or "")[:80],
            "ok": True,
        }
        rol = c.execute(
            text(
                "select rolsuper, rolcreatedb, rolcanlogin, rolreplication "
                "from pg_roles where rolname=current_user"
            )
        ).one()
        out["cin_app_yetki"] = {
            "rolsuper": bool(rol[0]),
            "rolcreatedb": bool(rol[1]),
            "rolcanlogin": bool(rol[2]),
            "rolreplication": bool(rol[3]),
        }
        dbs = c.execute(
            text(
                "select datname, pg_catalog.pg_get_userbyid(datdba) as owner, "
                "pg_database_size(datname) as bytes "
                "from pg_database where datistemplate=false order by 1"
            )
        ).fetchall()
        out["veritabanlari"] = [
            {"datname": d[0], "owner": d[1], "bytes": int(d[2] or 0)} for d in dbs
        ]
        adlar = {d[0] for d in dbs}
        out["hedef_durum"] = {
            HEDEF_SISTEM: "VAR" if HEDEF_SISTEM in adlar else "YOK",
            HEDEF_FIRMA: "VAR" if HEDEF_FIRMA in adlar else "YOK",
            RESTORE_SISTEM: "VAR" if RESTORE_SISTEM in adlar else "YOK",
            RESTORE_FIRMA: "VAR" if RESTORE_FIRMA in adlar else "YOK",
            "cin_sistem_dnm_d1_20260831": (
                "VAR" if "cin_sistem_dnm_d1_20260831" in adlar else "YOK"
            ),
            "cin_firma_dnm_d1_20260831": (
                "VAR" if "cin_firma_dnm_d1_20260831" in adlar else "YOK"
            ),
            "cin_sistem": "VAR" if "cin_sistem" in adlar else "YOK",
            "cin_firma_ray": "VAR" if "cin_firma_ray" in adlar else "YOK",
            "cin_sistem_kabul_20261105": (
                "VAR" if "cin_sistem_kabul_20261105" in adlar else "YOK"
            ),
            "cin_firma_kabul_20261105": (
                "VAR" if "cin_firma_kabul_20261105" in adlar else "YOK"
            ),
        }
    eng.dispose()

    # Super ile CREATE yetkisi denemesi (sadece yetki okuma; CREATE yok)
    sp = _super_parola()
    if sp:
        try:
            seng = create_engine(
                _url(pg.host, pg.port, "postgres", sp, "postgres", pg.sslmode),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 15},
            )
            with seng.connect() as c:
                u = c.execute(text("select current_user, rolsuper from pg_roles where rolname=current_user")).one()
                out["super_baglanti"] = {
                    "ok": True,
                    "user": u[0],
                    "rolsuper": bool(u[1]),
                    "via": "MUHASEBE_PG_SUPER_PASSWORD|keyring",
                }
            seng.dispose()
        except Exception as e:
            out["super_baglanti"] = {
                "ok": False,
                "hata_tipi": type(e).__name__,
                "mesaj": str(e)[:200],
            }
    else:
        out["super_baglanti"] = {
            "ok": False,
            "neden": "SUPER_PAROLA_YOK",
            "kullanici_islemi": (
                "Yerelde MUHASEBE_PG_SUPER_PASSWORD ayarlayın veya "
                "11_pg_dnm_d2_bos_hedef.ps1 / 12_* betiğinde Read-Host ile girin "
                "(sohbet/log yok)"
            ),
        }

    out["ok"] = bool(out.get("canli_baglanti", {}).get("ok"))
    out["createdb_icin"] = (
        out.get("cin_app_yetki", {}).get("rolcreatedb")
        or out.get("super_baglanti", {}).get("ok")
    )
    _yaz(out)
    # Özet — parola yok
    ozet = {
        "zaman": out["zaman"],
        "bu_pc": out["bu_pc"]["computername"],
        "pg_host": pg.host,
        "inet_server": out.get("canli_baglanti", {}).get("inet_server_addr"),
        "cin_app_createdb": out.get("cin_app_yetki", {}).get("rolcreatedb"),
        "cin_app_super": out.get("cin_app_yetki", {}).get("rolsuper"),
        "super_baglanti_ok": out.get("super_baglanti", {}).get("ok"),
        "hedef_durum": out.get("hedef_durum"),
        "db_adet": len(out.get("veritabanlari") or []),
        "ok": out["ok"],
        "kanit": "yedek/PG_ANA_MAKINE_DOGRULA.json",
    }
    (CALISMA / "PG_ANA_MAKINE_DOGRULA_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0 if out["ok"] else 1


def _yaz(out: dict) -> None:
    yol = CALISMA / "yedek" / "PG_ANA_MAKINE_DOGRULA.json"
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
