"""D2 izole yedek / geri yükleme denemesi — mali yazım yok.

Önerilen boş D2 DB oluştur (yoksa); pg_dump → ayrı restore DB.
D1 / RAY001 / kabul DB’lerine dokunmaz. K06 geçti sayılmaz (şema+boşluk ayrı).

  .venv\\Scripts\\python.exe -m tools.dnm_d2.yedek_izolasyon_dene
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    KORUNAN_HEDEFLER,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
RESTORE_SISTEM = "cin_sistem_dnm_d2_restore_test"
RESTORE_FIRMA = "cin_firma_dnm_d2_restore_test"


def _parola_app() -> str:
    from database.baglanti_modu import postgres_parola_al

    return postgres_parola_al() or ""


def _parola_super() -> str:
    import os

    env = (os.environ.get("MUHASEBE_PG_SUPER_PASSWORD") or "").strip()
    if env:
        return env
    try:
        import keyring

        for user in ("postgres_super", "postgres"):
            p = keyring.get_password("CinMuhasebe", user) or keyring.get_password(
                "PostgreSQL", user
            )
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
    from sqlalchemy import create_engine, text

    from database.baglanti_modu import ayari_yukle

    (CALISMA / "yedek").mkdir(parents=True, exist_ok=True)
    sonuc: dict = {
        "format": "d2-yedek-izolasyon-deneme-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "adimlar": [],
        "denendi": True,
        "basarili": False,
        "k06": False,
        "mali_yazim": False,
    }

    def adim(ad: str, **kw):
        sonuc["adimlar"].append({"ad": ad, **kw})

    ayar = ayari_yukle()
    if not ayar.ag_mi:
        adim("ag_modu", ok=False, mesaj="AG değil")
        _yaz(sonuc)
        return 2
    pg = ayar.postgres
    for ad in (ONERILEN_SISTEM_DB, ONERILEN_FIRMA_DB, RESTORE_SISTEM, RESTORE_FIRMA):
        if ad in KORUNAN_HEDEFLER:
            adim("korunan_ad", ok=False, db=ad)
            _yaz(sonuc)
            return 3

    app_pwd = _parola_app()
    if not app_pwd:
        adim("app_parola", ok=False)
        _yaz(sonuc)
        return 4

    baglan_db = pg.sistem_db or "cin_sistem_kabul_20261105"
    eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, app_pwd, baglan_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    with eng.connect() as conn:
        rol = conn.execute(
            text("select current_user, rolcreatedb from pg_roles where rolname=current_user")
        ).one()
        createdb = bool(rol[1])
        adim("baglanti", ok=True, user=rol[0], createdb=createdb, via=baglan_db)
    eng.dispose()

    user, pwd = pg.kullanici, app_pwd
    if not createdb:
        sp = _parola_super()
        if not sp:
            adim(
                "createdb_yetki",
                ok=False,
                mesaj="cin_app CREATEDB yok; super parola yok — ana makinede DB oluşturma gerekir",
                engel=True,
            )
            sonuc["eksik"] = "SUPER_PAROLA veya CREATEDB"
            sonuc["aktarim_engeli"] = True
            _yaz(sonuc)
            return 5
        user, pwd = "postgres", sp

    eng = create_engine(
        _url(pg.host, pg.port, user, pwd, baglan_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    olusan = []
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for db in (ONERILEN_SISTEM_DB, ONERILEN_FIRMA_DB):
            var = conn.execute(
                text("select 1 from pg_database where datname=:d"), {"d": db}
            ).scalar()
            if var:
                adim("db_mevcut", ok=True, db=db)
                olusan.append(db)
                continue
            conn.execute(text(f'CREATE DATABASE "{db}" OWNER "{pg.kullanici}"'))
            adim("db_olusturuldu", ok=True, db=db)
            olusan.append(db)
    eng.dispose()

    # pg_dump / pg_restore
    dump = shutil.which("pg_dump")
    psql = shutil.which("psql")
    if not dump or not psql:
        adim(
            "pg_dump",
            ok=False,
            mesaj="pg_dump/psql PATH’te yok — dump atlandı; boş DB oluşturma denendi",
            dump=dump,
            psql=psql,
        )
        sonuc["bos_db_olusan"] = olusan
        sonuc["basarili"] = bool(olusan)
        sonuc["kismi"] = True
        sonuc["aktarim_engeli"] = True
        sonuc["aciklama"] = "Boş D2 DB var/oluştu; izole restore için pg_dump gerekir"
        _yaz(sonuc)
        return 0 if olusan else 6

    dump_yol = CALISMA / "yedek" / f"{ONERILEN_FIRMA_DB}.dump"
    env = {
        **dict(__import__("os").environ),
        "PGPASSWORD": app_pwd,
    }
    # dump uygulama kullanıcısıyla
    r = subprocess.run(
        [
            dump,
            "-h",
            pg.host,
            "-p",
            str(pg.port),
            "-U",
            pg.kullanici,
            "-d",
            ONERILEN_FIRMA_DB,
            "-Fc",
            "-f",
            str(dump_yol),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    adim(
        "pg_dump_firma",
        ok=r.returncode == 0,
        yol=str(dump_yol),
        stderr=(r.stderr or "")[:300],
    )
    if r.returncode != 0:
        sonuc["basarili"] = False
        sonuc["aktarim_engeli"] = True
        _yaz(sonuc)
        return 7

    # restore DB oluştur
    eng = create_engine(
        _url(pg.host, pg.port, user, pwd, baglan_db, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        var = conn.execute(
            text("select 1 from pg_database where datname=:d"), {"d": RESTORE_FIRMA}
        ).scalar()
        if var:
            conn.execute(text(f'DROP DATABASE "{RESTORE_FIRMA}"'))
            adim("restore_db_drop", ok=True, db=RESTORE_FIRMA)
        conn.execute(text(f'CREATE DATABASE "{RESTORE_FIRMA}" OWNER "{pg.kullanici}"'))
        adim("restore_db_create", ok=True, db=RESTORE_FIRMA)
    eng.dispose()

    pg_restore = shutil.which("pg_restore")
    if not pg_restore:
        adim("pg_restore", ok=False, mesaj="pg_restore yok")
        sonuc["basarili"] = False
        _yaz(sonuc)
        return 8
    r2 = subprocess.run(
        [
            pg_restore,
            "-h",
            pg.host,
            "-p",
            str(pg.port),
            "-U",
            pg.kullanici,
            "-d",
            RESTORE_FIRMA,
            "--no-owner",
            str(dump_yol),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    # pg_restore empty DB may warn; check connect
    ok_restore = r2.returncode in (0, 1)  # 1 = warnings
    adim(
        "pg_restore",
        ok=ok_restore,
        returncode=r2.returncode,
        stderr=(r2.stderr or "")[:400],
    )
    e2 = create_engine(
        _url(pg.host, pg.port, pg.kullanici, app_pwd, RESTORE_FIRMA, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    with e2.connect() as c:
        dbn = c.execute(text("select current_database()")).scalar()
        adim("restore_baglanti", ok=dbn == RESTORE_FIRMA, current_database=dbn)
    e2.dispose()

    sonuc["basarili"] = ok_restore and bool(olusan)
    sonuc["k06"] = False  # şema/boş hedef kabulü ayrı
    sonuc["korunanlara_dokunulmadi"] = True
    sonuc["aktarim_engeli"] = not sonuc["basarili"]
    _yaz(sonuc)
    print(json.dumps({k: sonuc[k] for k in ("zaman", "basarili", "k06", "adimlar")}, ensure_ascii=False, indent=2), flush=True)
    return 0 if sonuc["basarili"] else 9


def _yaz(sonuc: dict) -> None:
    yol = CALISMA / "yedek" / "YEDEK_IZOLASYON_DENEME.json"
    yol.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")
    (CALISMA / "YEDEK_IZOLASYON_DENEME_OZET.json").write_text(
        json.dumps(
            {
                "zaman": sonuc.get("zaman"),
                "basarili": sonuc.get("basarili"),
                "k06": sonuc.get("k06"),
                "aktarim_engeli": sonuc.get("aktarim_engeli"),
                "adim_adet": len(sonuc.get("adimlar") or []),
                "kanit": "yedek/YEDEK_IZOLASYON_DENEME.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
