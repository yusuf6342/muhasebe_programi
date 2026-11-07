"""Terminalden cin_app ile D2 hedeflerine salt okunur doğrulama.

Aktif baglanti_ayari (kabul) değiştirilmez. Parola yazdırılmaz.
Yönetici/CREATEDB gerekmez. Veri/profil yazımı yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.pg_d2_terminal_salt_okuma
"""
from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK, ONERILEN_FIRMA_DB, ONERILEN_SISTEM_DB

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK

# Bu aşama: yalnız iki asıl D2 hedefi (restore_test HBA kapsamı dışı)
HEDEFLER = (
    ONERILEN_SISTEM_DB,
    ONERILEN_FIRMA_DB,
)
RESTORE_TEST_KAPSAM_DISI = (
    "cin_sistem_dnm_d2_restore_test",
    "cin_firma_dnm_d2_restore_test",
)
BEKLENEN_TABLO = {
    ONERILEN_SISTEM_DB: 14,
    ONERILEN_FIRMA_DB: 252,
}
BEKLENEN_SUNUCU = "192.168.1.114"
BEKLENEN_TERMINAL = "192.168.1.133"


def _yerel_ipv4() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((BEKLENEN_SUNUCU, 5432))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _dogrula_db(eng, db: str, beklenen_user: str) -> dict:
    with eng.connect() as c:
        # Salt okunur oturum — yazım yok
        c.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        c.execute(text("BEGIN"))
        try:
            c.execute(text("SET TRANSACTION READ ONLY"))
            row = c.execute(
                text(
                    "select current_user, current_database(), "
                    "inet_server_addr()::text, inet_client_addr()::text, "
                    "(select count(*) from information_schema.tables "
                    " where table_schema='public' and table_type='BASE TABLE'), "
                    "current_setting('transaction_read_only')"
                )
            ).one()
            ssl_used = c.execute(
                text(
                    "select coalesce("
                    "(select ssl from pg_stat_ssl where pid = pg_backend_pid()), false)"
                )
            ).scalar()
            rol = c.execute(
                text(
                    "select rolcreatedb, rolsuper from pg_roles where rolname=current_user"
                )
            ).one()
        finally:
            c.execute(text("ROLLBACK"))

    tablo = int(row[4] or 0)
    bek = BEKLENEN_TABLO.get(db)
    ro = str(row[5] or "").lower() in ("on", "true", "1")
    kayit = {
        "ok": True,
        "user": row[0],
        "database": row[1],
        "inet_server": row[2],
        "inet_client": row[3],
        "ssl": bool(ssl_used),
        "transaction_read_only": ro,
        "public_tablo": tablo,
        "beklenen_tablo": bek,
        "tablo_eslesme": (bek is None) or (tablo == bek),
        "rolcreatedb": bool(rol[0]),
        "rolsuper": bool(rol[1]),
    }
    if (
        not kayit["tablo_eslesme"]
        or row[0] != beklenen_user
        or row[1] != db
        or not kayit["ssl"]
        or not kayit["transaction_read_only"]
        or bool(rol[0])
        or bool(rol[1])
    ):
        kayit["ok"] = False
    return kayit


def main() -> int:
    from database.baglanti_modu import ayari_yukle, postgres_parola_al

    ayar = ayari_yukle()
    pg = ayar.postgres
    pwd = postgres_parola_al() or ""
    yerel_ip = _yerel_ipv4()
    out: dict = {
        "format": "d2-terminal-salt-okuma-v2",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "aktif_profil_degistirilmedi": True,
        "aktif_profil": {
            "sistem_db": pg.sistem_db,
            "firma_db": pg.firma_db,
            "host": pg.host,
        },
        "baglanti": {
            "host": pg.host,
            "port": pg.port,
            "kullanici": pg.kullanici,
            "sslmode": pg.sslmode,
        },
        "yerel_ipv4": yerel_ip,
        "beklenen_terminal_ip": BEKLENEN_TERMINAL,
        "beklenen_sunucu": BEKLENEN_SUNUCU,
        "hedefler": {},
        "restore_test_kapsam_disi": list(RESTORE_TEST_KAPSAM_DISI),
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
    }
    if not pwd:
        out["ok"] = False
        out["hata"] = "APP_PAROLA_YOK"
        _yaz(out)
        return 2

    if pg.host != BEKLENEN_SUNUCU:
        out["uyari_host"] = f"aktif host={pg.host}; beklenen={BEKLENEN_SUNUCU}"

    ok_all = True
    for db in HEDEFLER:
        url = (
            f"postgresql+psycopg://{quote_plus(pg.kullanici)}:{quote_plus(pwd)}"
            f"@{pg.host}:{pg.port}/{db}?sslmode={quote_plus(pg.sslmode)}"
        )
        try:
            eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
            kayit = _dogrula_db(eng, db, pg.kullanici)
            eng.dispose()
            if not kayit["ok"]:
                ok_all = False
            out["hedefler"][db] = kayit
        except Exception as e:
            ok_all = False
            out["hedefler"][db] = {
                "ok": False,
                "hata_tipi": type(e).__name__,
                "mesaj": str(e)[:400],
            }

    # Aktif kabul hâlâ ayakta (salt okuma)
    try:
        url_k = (
            f"postgresql+psycopg://{quote_plus(pg.kullanici)}:{quote_plus(pwd)}"
            f"@{pg.host}:{pg.port}/{pg.sistem_db}?sslmode={quote_plus(pg.sslmode)}"
        )
        eng = create_engine(url_k, pool_pre_ping=True, connect_args={"connect_timeout": 12})
        with eng.connect() as c:
            c.execute(text("SET TRANSACTION READ ONLY"))
            d = c.execute(text("select current_database()")).scalar()
            ssl_k = c.execute(
                text(
                    "select coalesce("
                    "(select ssl from pg_stat_ssl where pid = pg_backend_pid()), false)"
                )
            ).scalar()
        eng.dispose()
        out["aktif_kabul_korundu"] = {
            "ok": d == pg.sistem_db,
            "database": d,
            "ssl": bool(ssl_k),
        }
        if d != pg.sistem_db:
            ok_all = False
    except Exception as e:
        out["aktif_kabul_korundu"] = {
            "ok": False,
            "hata_tipi": type(e).__name__,
            "mesaj": str(e)[:200],
        }
        ok_all = False

    out["ok"] = ok_all
    out["altyapi_kontrolu"] = ok_all
    out["ana_makine_hba_referans"] = "yedek/HBA_SONUC_20261107_163837.json"
    out["ana_makine_hazirlik_referans"] = "yedek/CALISTIR_SONUC_20261107_160153.json"
    _yaz(out)
    ozet = {
        "zaman": out["zaman"],
        "ok": out["ok"],
        "host": pg.host,
        "yerel_ipv4": yerel_ip,
        "hedefler": {
            k: {
                "ok": v.get("ok"),
                "public_tablo": v.get("public_tablo"),
                "ssl": v.get("ssl"),
                "transaction_read_only": v.get("transaction_read_only"),
                "inet_client": v.get("inet_client"),
                "inet_server": v.get("inet_server"),
                "hata_tipi": v.get("hata_tipi"),
                "mesaj": v.get("mesaj"),
            }
            for k, v in out["hedefler"].items()
        },
        "aktif_profil_degistirilmedi": True,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
        "kanit": "yedek/PG_D2_TERMINAL_SALT_OKUMA.json",
    }
    (CALISMA / "PG_D2_TERMINAL_SALT_OKUMA_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok_all else 1


def _yaz(out: dict) -> None:
    (CALISMA / "yedek").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (CALISMA / "yedek" / "PG_D2_TERMINAL_SALT_OKUMA.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (CALISMA / "yedek" / f"PG_D2_TERMINAL_SALT_OKUMA_{stamp}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
