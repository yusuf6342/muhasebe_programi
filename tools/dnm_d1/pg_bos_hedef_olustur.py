"""DNM D1 boş izole PostgreSQL hedefi — Python (keyring parola).

Korunan DB adlarına yazmaz. TEMPLATE kopyalamaz.
cin_app CREATEDB yetkisi yoksa superuser gerekir.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.pg_bos_hedef_olustur
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from tools.dnm_d1.donem_sabitleri import (
    CALISMA_KOK,
    KORUNAN_HEDEFLER,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

KOK = Path(__file__).resolve().parents[2]


def _parola_app() -> str:
    from database.baglanti_modu import postgres_parola_al

    return postgres_parola_al()


def _parola_super() -> str:
    env = (os.environ.get("MUHASEBE_PG_SUPER_PASSWORD") or "").strip()
    if env:
        return env
    try:
        import keyring

        for user in ("postgres_super", "postgres"):
            p = keyring.get_password("CinMuhasebe", user)
            if p:
                return p
            p = keyring.get_password("PostgreSQL", user)
            if p:
                return p
    except Exception:
        pass
    return ""


def _url(host: str, port: int, user: str, password: str, db: str, sslmode: str) -> str:
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?sslmode={sslmode}"
    )


def main() -> int:
    from sqlalchemy import create_engine, text

    from database.baglanti_modu import ayari_yukle

    ayar = ayari_yukle()
    if not ayar.ag_mi:
        print("AG_DEGIL", flush=True)
        return 2
    pg = ayar.postgres
    sistem = ONERILEN_SISTEM_DB
    firma = ONERILEN_FIRMA_DB
    for ad in (sistem, firma):
        if ad in KORUNAN_HEDEFLER or ad.endswith("_deneme") or "_kabul_" in ad or "_restore_" in ad:
            print("KORUNAN_AD", ad, flush=True)
            return 3

    app_pwd = _parola_app()
    if not app_pwd:
        print("APP_PAROLA_YOK", flush=True)
        return 4

    # pg_hba çoğu kurulumda yalnız uygulama DB’lerine izin verir; "postgres" bakım DB’si kapalı olabilir.
    baglan_db = pg.sistem_db or "cin_sistem_kabul_20261105"
    eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, app_pwd, baglan_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    createdb = False
    with eng.connect() as conn:
        rol = conn.execute(
            text("select current_user, rolcreatedb from pg_roles where rolname=current_user")
        ).one()
        print("BAGLANDI", rol[0], "via", baglan_db, "createdb=", rol[1], flush=True)
        createdb = bool(rol[1])
    eng.dispose()

    user = pg.kullanici
    pwd = app_pwd
    if not createdb:
        super_pwd = _parola_super()
        if not super_pwd:
            print(
                "SUPER_PAROLA_YOK — cin_app CREATEDB yetkisiz. "
                "Ana makinede (DESKTOP-CGSE5GK) şunu çalıştırın:\n"
                "  .\\kurulum\\sunucu\\10_pg_dnm_d1_bos_hedef.ps1\n"
                "veya MUHASEBE_PG_SUPER_PASSWORD / keyring postgres_super sağlayın.",
                flush=True,
            )
            return 5
        # Superuser ile yine uygulama DB üzerinden dene; postgres DB hba’da yoksa
        user = "postgres"
        pwd = super_pwd

    eng = create_engine(
        _url(pg.host, pg.port, user, pwd, baglan_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    olusan: list[str] = []
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for db in (sistem, firma):
            var = conn.execute(
                text("select 1 from pg_database where datname=:d"), {"d": db}
            ).scalar()
            if var:
                print("MEVCUT", db, flush=True)
                olusan.append(db)
                continue
            conn.execute(text(f'CREATE DATABASE "{db}" OWNER "{pg.kullanici}"'))
            print("OLUSTURULDU", db, flush=True)
            olusan.append(db)
    eng.dispose()

    # Doğrulama: cin_app ile bağlan
    dogrulama = {}
    for db in (sistem, firma):
        e2 = create_engine(
            _url(pg.host, pg.port, pg.kullanici, app_pwd, db, pg.sslmode),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )
        with e2.connect() as c:
            dogrulama[db] = {
                "current_database": c.execute(text("select current_database()")).scalar(),
                "current_user": c.execute(text("select current_user")).scalar(),
            }
        e2.dispose()

    kanit = {
        "format": "d1-hedef-db-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": pg.host,
        "port": pg.port,
        "sslmode": pg.sslmode,
        "app_user": pg.kullanici,
        "sistem_db": sistem,
        "firma_db": firma,
        "olusan_veya_mevcut": olusan,
        "dogrulama": dogrulama,
        "korunanlara_dokunulmadi": True,
        "not": "Boş DB; şema henüz kurulmadı. Mevcut baglanti_ayari.json hâlâ kabul DB’lerini gösterir — D1 profili ayrı tutulmalı.",
    }
    out = KOK / CALISMA_KOK / "hedef" / "D1_20260831_HEDEF_DB_KANIT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kanit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    man_yol = KOK / CALISMA_KOK / "CALISMA_MANIFESTI.json"
    if man_yol.is_file():
        man = json.loads(man_yol.read_text(encoding="utf-8"))
        man.setdefault("hedef", {})
        man["hedef"]["gercek_sistem_db"] = sistem
        man["hedef"]["gercek_firma_db"] = firma
        man["hedef"]["uygulama_durumu"] = "OLUSTURULDU"
        man["hedef"]["db_kanit"] = str(out.relative_to(KOK)).replace("\\", "/")
        man["uygulama_kapilari"]["K06_hedef_izolasyonu"] = True
        man_yol.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("KANIT", out, flush=True)
    print("K06", "OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
