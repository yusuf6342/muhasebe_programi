"""D2 boş hedef + şema + adlandırılmış profil + yedek/restore — mali yazım yok.

cin_app'e CREATEDB/SUPERUSER vermez. Super parola: env / keyring / yerel GUI
(sohbet/log'a yazılmaz). Aktif baglanti_ayari.json (kabul) değiştirilmez.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.pg_d2_hedef_hazirla
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    KORUNAN_HEDEFLER,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
HEDEF_SISTEM = ONERILEN_SISTEM_DB
HEDEF_FIRMA = ONERILEN_FIRMA_DB
RESTORE_SISTEM = "cin_sistem_dnm_d2_restore_test"
RESTORE_FIRMA = "cin_firma_dnm_d2_restore_test"
PROFIL_DOSYA = CALISMA / "esleme" / "BAGLANTI_PROFIL_DNM_D2_20260901.json"


def _app_pwd() -> str:
    from database.baglanti_modu import postgres_parola_al

    return postgres_parola_al() or ""


def _super_pwd() -> str:
    env = (os.environ.get("MUHASEBE_PG_SUPER_PASSWORD") or "").strip()
    if env:
        return env
    try:
        import keyring

        for svc, user in (
            ("CinMuhasebe", "postgres_super"),
            ("CinMuhasebe", "postgres"),
            ("PostgreSQL", "postgres"),
            ("PostgreSQL", "postgres_super"),
        ):
            p = keyring.get_password(svc, user)
            if p:
                return p
    except Exception:
        pass
    return ""


def _super_pwd_gui() -> str:
    """Yerel güvenli giriş — stdout/log'a yazılmaz."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = simpledialog.askstring(
            "DNM D2 PostgreSQL",
            "postgres superuser parolası (yalnız bu oturum; kaydedilmez):",
            show="*",
            parent=root,
        )
        root.destroy()
        return (p or "").strip()
    except Exception:
        return ""


def _url(host, port, user, password, db, sslmode) -> str:
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?sslmode={sslmode}"
    )


def _adim(sonuc: dict, ad: str, **kw) -> None:
    sonuc.setdefault("adimlar", []).append({"ad": ad, **kw})


def _db_var(conn, name: str) -> bool:
    return bool(
        conn.execute(text("select 1 from pg_database where datname=:d"), {"d": name}).scalar()
    )


def _ensure_db(conn, name: str, owner: str, sonuc: dict) -> str:
    if name in KORUNAN_HEDEFLER:
        raise RuntimeError(f"Korunan ad: {name}")
    if _db_var(conn, name):
        # İçerik incelemeden silme/üzerine yazma YOK
        ntab = None
        try:
            e = conn.engine
        except Exception:
            e = None
        _adim(sonuc, "db_mevcut_dokunulmadi", ok=True, db=name)
        return "MEVCUT"
    conn.execute(text(f'CREATE DATABASE "{name}" OWNER "{owner}"'))
    _adim(sonuc, "db_olusturuldu", ok=True, db=name, owner=owner)
    return "OLUSTURULDU"


def _sema_sistem(url: str, sonuc: dict) -> dict:
    from database.system.models import SystemBase
    from database.system.migration import migrate_system_schema

    eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 20})
    SystemBase.metadata.create_all(eng)
    try:
        migrate_system_schema(eng)
    except Exception as e:
        _adim(sonuc, "sistem_migrate", ok=False, hata=type(e).__name__, mesaj=str(e)[:160])
    insp = inspect(eng)
    tablolar = sorted(insp.get_table_names())
    eng.dispose()
    bil = {"tablo_adet": len(tablolar), "ornek": tablolar[:12], "companies": "companies" in tablolar}
    _adim(sonuc, "sema_sistem", ok=True, **bil)
    return bil


def _sema_firma(url: str, sonuc: dict) -> dict:
    from database.models import Base

    eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 30})
    Base.metadata.create_all(eng)
    insp = inspect(eng)
    tablolar = sorted(insp.get_table_names())
    eng.dispose()
    bil = {"tablo_adet": len(tablolar), "ornek": tablolar[:12]}
    _adim(sonuc, "sema_firma", ok=True, **bil)
    return bil


def _find_bin(name: str) -> str | None:
    for root in (
        r"C:\Program Files\PostgreSQL\17\bin",
        r"C:\Program Files\PostgreSQL\16\bin",
        r"C:\Program Files\PostgreSQL\18\bin",
    ):
        p = Path(root) / name
        if p.is_file():
            return str(p)
    return shutil.which(name)


def _dump_restore(
    *,
    host: str,
    port: int,
    app_user: str,
    app_pwd: str,
    admin_user: str,
    admin_pwd: str,
    baglan_db: str,
    sslmode: str,
    sonuc: dict,
) -> bool:
    dump = _find_bin("pg_dump.exe") or _find_bin("pg_dump")
    restore = _find_bin("pg_restore.exe") or _find_bin("pg_restore")
    if not dump or not restore:
        _adim(sonuc, "pg_dump", ok=False, mesaj="pg_dump/pg_restore yok")
        return False

    yedek_dir = CALISMA / "yedek" / f"pg_d2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    yedek_dir.mkdir(parents=True, exist_ok=True)
    env_app = {**os.environ, "PGPASSWORD": app_pwd}
    env_adm = {**os.environ, "PGPASSWORD": admin_pwd}

    dumps = {}
    for db in (HEDEF_SISTEM, HEDEF_FIRMA):
        yol = yedek_dir / f"{db}.dump"
        r = subprocess.run(
            [
                dump,
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                app_user,
                "-d",
                db,
                "-Fc",
                "-f",
                str(yol),
            ],
            capture_output=True,
            text=True,
            env=env_app,
            timeout=300,
        )
        dumps[db] = str(yol)
        _adim(
            sonuc,
            f"pg_dump_{db}",
            ok=r.returncode == 0,
            yol=str(yol),
            boyut=yol.stat().st_size if yol.is_file() else 0,
            stderr=(r.stderr or "")[:200],
        )
        if r.returncode != 0:
            return False

    # Restore hedefleri — varsa içeriği incelemeden DROP/üzerine yazma YOK
    eng = create_engine(
        _url(host, port, admin_user, admin_pwd, baglan_db, sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for db in (RESTORE_SISTEM, RESTORE_FIRMA):
            if _db_var(conn, db):
                _adim(
                    sonuc,
                    "restore_db_mevcut_dokunulmadi",
                    ok=True,
                    db=db,
                    not_="İçerik incelemeden silinmedi; restore atlandı veya mevcut üzerinde doğrulama",
                )
            else:
                conn.execute(text(f'CREATE DATABASE "{db}" OWNER "{app_user}"'))
                _adim(sonuc, "restore_db_olusturuldu", ok=True, db=db)
    eng.dispose()

    ok_all = True
    mapping = {
        HEDEF_SISTEM: RESTORE_SISTEM,
        HEDEF_FIRMA: RESTORE_FIRMA,
    }
    for src, dst in mapping.items():
        # Hedef yeni boşsa restore et
        eng2 = create_engine(
            _url(host, port, app_user, app_pwd, dst, sslmode),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 15},
        )
        with eng2.connect() as c:
            n = c.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_schema='public' and table_type='BASE TABLE'"
                )
            ).scalar()
        eng2.dispose()
        if int(n or 0) > 0:
            _adim(
                sonuc,
                f"pg_restore_{dst}",
                ok=True,
                atlandi=True,
                neden="hedef_zaten_tablolu_silinmedi",
                tablo_adet=int(n),
            )
            continue
        r2 = subprocess.run(
            [
                restore,
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                app_user,
                "-d",
                dst,
                "--no-owner",
                "--no-acl",
                str(dumps[src]),
            ],
            capture_output=True,
            text=True,
            env=env_app,
            timeout=600,
        )
        ok = r2.returncode in (0, 1)
        ok_all = ok_all and ok
        _adim(
            sonuc,
            f"pg_restore_{dst}",
            ok=ok,
            returncode=r2.returncode,
            stderr=(r2.stderr or "")[:300],
        )
    sonuc["yedek_klasor"] = str(yedek_dir)
    return ok_all


def _dogrula_baglanti(host, port, user, pwd, db, sslmode) -> dict:
    eng = create_engine(
        _url(host, port, user, pwd, db, sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 12},
    )
    with eng.connect() as c:
        cur = c.execute(
            text(
                "select current_user, current_database(), "
                "inet_server_addr()::text, "
                "(select count(*) from information_schema.tables "
                " where table_schema='public' and table_type='BASE TABLE')"
            )
        ).one()
        out = {
            "ok": True,
            "user": cur[0],
            "database": cur[1],
            "inet_server": cur[2],
            "public_tablo": int(cur[3] or 0),
        }
    eng.dispose()
    return out


def main() -> int:
    from database.baglanti_modu import BaglantiAyari, PostgresBaglanti, ayari_yukle

    (CALISMA / "yedek").mkdir(parents=True, exist_ok=True)
    (CALISMA / "esleme").mkdir(parents=True, exist_ok=True)

    sonuc: dict = {
        "format": "d2-pg-hedef-hazirla-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bu_pc": os.environ.get("COMPUTERNAME") or socket.gethostname(),
        "cin_app_createdb_verilmedi": True,
        "cin_app_superuser_verilmedi": True,
        "aktif_profil_korundu": True,
        "mali_yazim": False,
        "k05": False,
        "k06": False,
        "adimlar": [],
    }

    ayar = ayari_yukle()
    if not ayar.ag_mi:
        _adim(sonuc, "ag", ok=False)
        return _bitir(sonuc, 2)

    pg = ayar.postgres
    app_pwd = _app_pwd()
    if not app_pwd:
        _adim(sonuc, "app_parola", ok=False)
        sonuc["kullanici_islemi"] = "cin_app parolası keyring/MUHASEBE_PG_PASSWORD"
        return _bitir(sonuc, 3)

    aktif_sistem = pg.sistem_db
    aktif_firma = pg.firma_db
    sonuc["aktif_profil"] = {
        "host": pg.host,
        "sistem_db": aktif_sistem,
        "firma_db": aktif_firma,
        "terminal": pg.terminal_kimligi,
    }
    sonuc["manifest_hedef"] = {"sistem": HEDEF_SISTEM, "firma": HEDEF_FIRMA}

    # Aktif kabul bağlantısı
    try:
        k = _dogrula_baglanti(pg.host, pg.port, pg.kullanici, app_pwd, aktif_sistem, pg.sslmode)
        _adim(sonuc, "aktif_kabul_baglanti", **k)
    except Exception as e:
        _adim(sonuc, "aktif_kabul_baglanti", ok=False, hata=type(e).__name__, mesaj=str(e)[:160])
        return _bitir(sonuc, 4)

    # Yetki
    eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, app_pwd, aktif_sistem, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 12},
    )
    with eng.connect() as c:
        rol = c.execute(
            text(
                "select rolsuper, rolcreatedb from pg_roles where rolname=current_user"
            )
        ).one()
        _adim(
            sonuc,
            "cin_app_yetki",
            ok=True,
            rolsuper=bool(rol[0]),
            rolcreatedb=bool(rol[1]),
        )
        createdb = bool(rol[1])
        adlar = {
            r[0]
            for r in c.execute(
                text("select datname from pg_database where datistemplate=false")
            )
        }
    eng.dispose()

    admin_user, admin_pwd = pg.kullanici, app_pwd
    if not createdb:
        sp = _super_pwd()
        if not sp:
            print(
                "SUPER_PAROLA gerekli — yerel güvenli pencere açılıyor…",
                flush=True,
            )
            sp = _super_pwd_gui()
        if not sp:
            _adim(
                sonuc,
                "super_parola",
                ok=False,
                engel=True,
            )
            sonuc["kullanici_islemi"] = (
                "1) Bu PC veya DESKTOP-CGSE5GK üzerinde "
                "MUHASEBE_PG_SUPER_PASSWORD ortam değişkenini oturuma ayarlayın "
                "(sohbet/log yok), VEYA\n"
                "2) Ana makinede yönetici PowerShell:\n"
                "   .\\kurulum\\sunucu\\12_pg_dnm_d2_hedef_yedek_restore.ps1\n"
                "   (Read-Host SecureString; PgHost=127.0.0.1)\n"
                "3) cin_app'e CREATEDB/SUPERUSER vermeyin."
            )
            sonuc["basarili"] = False
            sonuc["aktarim_engeli"] = True
            return _bitir(sonuc, 5)
        admin_user, admin_pwd = "postgres", sp
        # Super'ı uygulama DB üzerinden dene (postgres bakım DB hba kapalı olabilir)
        try:
            seng = create_engine(
                _url(pg.host, pg.port, admin_user, admin_pwd, aktif_sistem, pg.sslmode),
                pool_pre_ping=True,
                connect_args={"connect_timeout": 15},
            )
            with seng.connect() as c:
                u = c.execute(text("select current_user")).scalar()
                _adim(sonuc, "super_baglanti", ok=True, user=u, via=aktif_sistem)
            seng.dispose()
        except Exception as e:
            _adim(
                sonuc,
                "super_baglanti",
                ok=False,
                hata=type(e).__name__,
                mesaj=str(e)[:200],
            )
            sonuc["kullanici_islemi"] = (
                "postgres kullanıcısı 192.168.1.114 üzerinde uygulama DB’sine "
                "bağlanamadı (pg_hba). Ana makinede (DESKTOP-CGSE5GK) "
                "127.0.0.1 ile 12_pg_dnm_d2_hedef_yedek_restore.ps1 çalıştırın."
            )
            sonuc["basarili"] = False
            return _bitir(sonuc, 6)

    # CREATE DATABASE
    eng_a = create_engine(
        _url(pg.host, pg.port, admin_user, admin_pwd, aktif_sistem, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 20},
    )
    durum_db = {}
    try:
        with eng_a.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for db in (HEDEF_SISTEM, HEDEF_FIRMA):
                durum_db[db] = _ensure_db(conn, db, pg.kullanici, sonuc)
    except Exception as e:
        _adim(sonuc, "create_database", ok=False, hata=type(e).__name__, mesaj=str(e)[:220])
        sonuc["basarili"] = False
        return _bitir(sonuc, 7)
    finally:
        eng_a.dispose()

    # Şema — yalnızca boş/az tablolu ise create_all (üzerine yazma değil; checkfirst)
    sema = {}
    try:
        for db, kind in ((HEDEF_SISTEM, "sistem"), (HEDEF_FIRMA, "firma")):
            dog = _dogrula_baglanti(pg.host, pg.port, pg.kullanici, app_pwd, db, pg.sslmode)
            _adim(sonuc, f"baglanti_{db}", **dog)
            url = _url(pg.host, pg.port, pg.kullanici, app_pwd, db, pg.sslmode)
            if dog["public_tablo"] == 0:
                if kind == "sistem":
                    sema[db] = _sema_sistem(url, sonuc)
                else:
                    sema[db] = _sema_firma(url, sonuc)
            else:
                _adim(
                    sonuc,
                    f"sema_atlandi_{db}",
                    ok=True,
                    public_tablo=dog["public_tablo"],
                    not_="Mevcut şema incelendi; recreate/silme yok",
                )
                sema[db] = {"tablo_adet": dog["public_tablo"], "mevcut": True}
    except Exception as e:
        _adim(sonuc, "sema", ok=False, hata=type(e).__name__, mesaj=str(e)[:220])
        sonuc["basarili"] = False
        return _bitir(sonuc, 8)

    # Adlandırılmış D2 profil (aktif kabul dosyasını değiştirme)
    profil = BaglantiAyari(
        kipi="yerel_ag_postgres",
        postgres=PostgresBaglanti(
            host=pg.host,
            port=pg.port,
            sistem_db=HEDEF_SISTEM,
            firma_db=HEDEF_FIRMA,
            kullanici=pg.kullanici,
            sslmode=pg.sslmode,
            ortam="DENEME",
            terminal_kimligi=f"DNM-D2-20260901-{sonuc['bu_pc']}",
        ),
    ).to_dict()
    profil["profil_adi"] = PROFIL_ADI
    profil["aktif_gunluk_profil_degistirilmedi"] = True
    profil["aktif_referans"] = {
        "sistem_db": aktif_sistem,
        "firma_db": aktif_firma,
    }
    profil["not"] = (
        "Bu dosya D2 deneme profilidir. Günlük/kabul baglanti_ayari.json "
        "bilinçli geçiş olmadan değiştirilmez."
    )
    PROFIL_DOSYA.write_text(json.dumps(profil, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _adim(sonuc, "profil_yazildi", ok=True, yol=str(PROFIL_DOSYA.relative_to(KOK)).replace("\\", "/"))

    # Yedek + restore test
    try:
        ok_yr = _dump_restore(
            host=pg.host,
            port=pg.port,
            app_user=pg.kullanici,
            app_pwd=app_pwd,
            admin_user=admin_user,
            admin_pwd=admin_pwd,
            baglan_db=aktif_sistem,
            sslmode=pg.sslmode,
            sonuc=sonuc,
        )
    except Exception as e:
        ok_yr = False
        _adim(sonuc, "yedek_restore", ok=False, hata=type(e).__name__, mesaj=str(e)[:220])

    # Restore + D2 bağlantı doğrulama
    dog_hedef = {}
    for db in (HEDEF_SISTEM, HEDEF_FIRMA, RESTORE_SISTEM, RESTORE_FIRMA):
        try:
            dog_hedef[db] = _dogrula_baglanti(
                pg.host, pg.port, pg.kullanici, app_pwd, db, pg.sslmode
            )
        except Exception as e:
            dog_hedef[db] = {"ok": False, "hata": type(e).__name__, "mesaj": str(e)[:160]}

    # Aktif kabul hâlâ ayakta
    try:
        kabul_son = _dogrula_baglanti(
            pg.host, pg.port, pg.kullanici, app_pwd, aktif_sistem, pg.sslmode
        )
        _adim(sonuc, "aktif_kabul_korundu", **kabul_son)
    except Exception as e:
        _adim(sonuc, "aktif_kabul_korundu", ok=False, hata=type(e).__name__)

    sonuc["sema"] = sema
    sonuc["db_durum"] = durum_db
    sonuc["dogrulama"] = dog_hedef
    sonuc["yedek_restore_ok"] = ok_yr
    hedef_ok = all(dog_hedef.get(d, {}).get("ok") for d in (HEDEF_SISTEM, HEDEF_FIRMA))
    restore_ok = all(
        dog_hedef.get(d, {}).get("ok") for d in (RESTORE_SISTEM, RESTORE_FIRMA)
    )
    sonuc["basarili"] = bool(hedef_ok and restore_ok and ok_yr)
    # K06: yedek+restore+izolasyon kanıtı — kaynak kabul (K05) değil
    sonuc["k06_izolasyon_yedek_kaniti"] = bool(sonuc["basarili"])
    sonuc["k06"] = False  # tam K06 paketi kaynak kabulü olmadan işaretlenmez
    sonuc["k05"] = False
    sonuc["aktarim_engeli"] = not sonuc["basarili"]
    sonuc["aciklama"] = (
        "D2 boş DB + şema + dump/restore kanıtı; gerçek açılış/hareket yazımı yok. "
        "K05/K06 tam kabul için D1 FIFO/LOT/kaynak kapanışı ayrıca gerekli."
    )
    return _bitir(sonuc, 0 if sonuc["basarili"] else 9)


def _bitir(sonuc: dict, kod: int) -> int:
    yol = CALISMA / "yedek" / "PG_D2_HEDEF_HAZIRLA.json"
    yol.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")
    ozet = {
        "zaman": sonuc.get("zaman"),
        "bu_pc": sonuc.get("bu_pc"),
        "basarili": sonuc.get("basarili"),
        "k06_izolasyon_yedek_kaniti": sonuc.get("k06_izolasyon_yedek_kaniti"),
        "k06": sonuc.get("k06", False),
        "k05": False,
        "mali_yazim": False,
        "aktif_profil_korundu": sonuc.get("aktif_profil_korundu"),
        "hedef": sonuc.get("manifest_hedef"),
        "db_durum": sonuc.get("db_durum"),
        "dogrulama_ozet": {
            k: {"ok": v.get("ok"), "public_tablo": v.get("public_tablo")}
            for k, v in (sonuc.get("dogrulama") or {}).items()
        },
        "kullanici_islemi": sonuc.get("kullanici_islemi"),
        "adim_adet": len(sonuc.get("adimlar") or []),
        "kanit": "yedek/PG_D2_HEDEF_HAZIRLA.json",
    }
    (CALISMA / "PG_D2_HEDEF_HAZIRLA_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # YEDEK özetini güncelle
    (CALISMA / "YEDEK_IZOLASYON_DENEME_OZET.json").write_text(
        json.dumps(
            {
                "zaman": sonuc.get("zaman"),
                "basarili": bool(sonuc.get("basarili")),
                "k06": False,
                "k06_izolasyon_yedek_kaniti": sonuc.get("k06_izolasyon_yedek_kaniti"),
                "aktarim_engeli": not bool(sonuc.get("basarili")),
                "durum": (
                    "BASARILI_KANIT"
                    if sonuc.get("basarili")
                    else "ENGEL_VEYA_KISMI"
                ),
                "kanit": "yedek/PG_D2_HEDEF_HAZIRLA.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return kod


if __name__ == "__main__":
    raise SystemExit(main())
