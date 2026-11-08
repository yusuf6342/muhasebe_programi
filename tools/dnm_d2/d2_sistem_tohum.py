"""D2 sistem DB tohumu: roller/yetkiler/kullanıcılar (kabulden) + DNM D2 firma.

Aktif baglanti_ayari.json değiştirilmez. Parola yazdırmaz.
Mevcut D2 companies/users/roles doluysa üzerine yazmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_sistem_tohum
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from database.baglanti_modu import ayari_yukle, postgres_parola_al
from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
KAYNAK_SISTEM = "cin_sistem_kabul_20261105"
FIRMA_KOD = "DNM_D2"
FIRMA_UNVAN = "DNM – RAY MOBİLYA AKSESUARLAR ETÜD (D2)"
FIRMA_KISA = "DNM D2"


def _url(host, port, user, pwd, db, sslmode) -> str:
    return (
        f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(pwd)}"
        f"@{host}:{port}/{db}?sslmode={quote_plus(sslmode)}"
    )


def _cols(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name=:t "
                "order by ordinal_position"
            ),
            {"t": table},
        )
    ]


def _kopyala(src, dst, table: str) -> int:
    cols = _cols(src, table)
    dst_cols = set(_cols(dst, table))
    cols = [c for c in cols if c in dst_cols]
    if not cols:
        return 0
    cl = ", ".join(cols)
    ph = ", ".join(f":{c}" for c in cols)
    rows = src.execute(text(f"select {cl} from {table} order by id")).mappings().all()
    for row in rows:
        dst.execute(text(f"insert into {table} ({cl}) values ({ph})"), dict(row))
    return len(rows)


def main() -> int:
    ayar = ayari_yukle()
    pg = ayar.postgres
    pwd = postgres_parola_al()
    if not pwd:
        print("APP_PAROLA_YOK")
        return 2

    sonuc: dict = {
        "format": "d2-sistem-tohum-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hedef_sistem": ONERILEN_SISTEM_DB,
        "hedef_firma_db": ONERILEN_FIRMA_DB,
        "kaynak_sistem": KAYNAK_SISTEM,
        "aktif_profil_degistirilmedi": True,
        "adimlar": [],
    }

    src_eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, pwd, KAYNAK_SISTEM, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )
    dst_eng = create_engine(
        _url(pg.host, pg.port, pg.kullanici, pwd, ONERILEN_SISTEM_DB, pg.sslmode),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )

    with dst_eng.connect() as c:
        n_co = int(c.execute(text("select count(*) from companies")).scalar() or 0)
        n_us = int(c.execute(text("select count(*) from users")).scalar() or 0)
        n_ro = int(c.execute(text("select count(*) from roles")).scalar() or 0)
    if n_co or n_us or n_ro:
        sonuc["adimlar"].append(
            {
                "ad": "mevcut_tohum",
                "ok": True,
                "atlandi": True,
                "companies": n_co,
                "users": n_us,
                "roles": n_ro,
            }
        )
        sonuc["basarili"] = True
        _yaz(sonuc)
        print("ATLANDI_MEVCUT", n_co, n_us, n_ro)
        return 0

    with src_eng.connect() as src, dst_eng.begin() as dst:
        n_roles = _kopyala(src, dst, "roles")
        n_perm = _kopyala(src, dst, "permissions")
        n_rp = _kopyala(src, dst, "role_permissions")
        n_mig = _kopyala(src, dst, "schema_migrations")
        sonuc["adimlar"].append(
            {
                "ad": "roller_yetkiler",
                "ok": True,
                "roles": n_roles,
                "permissions": n_perm,
                "role_permissions": n_rp,
                "migrations": n_mig,
            }
        )

        firma_id = 1
        dst.execute(
            text(
                "insert into companies ("
                "id, firma_uid, firma_kodu, unvan, kisa_ad, varsayilan_para_birimi, "
                "aktif, db_path, olusturma_tarihi"
                ") values ("
                ":id, :uid, :kod, :unvan, :kisa, 'TRY', true, :db_path, now()"
                ")"
            ),
            {
                "id": firma_id,
                "uid": str(uuid.uuid4()),
                "kod": FIRMA_KOD,
                "unvan": FIRMA_UNVAN,
                "kisa": FIRMA_KISA,
                "db_path": f"pg:{ONERILEN_FIRMA_DB}",
            },
        )
        sonuc["adimlar"].append(
            {
                "ad": "firma",
                "ok": True,
                "firma_kodu": FIRMA_KOD,
                "db_path": f"pg:{ONERILEN_FIRMA_DB}",
                "profil": PROFIL_ADI,
            }
        )

        user_cols = _cols(src, "users")
        dst_user_cols = set(_cols(dst, "users"))
        user_cols = [c for c in user_cols if c in dst_user_cols]
        ul = ", ".join(user_cols)
        uph = ", ".join(f":{c}" for c in user_cols)
        users = src.execute(
            text("select * from users where aktif is true order by id")
        ).mappings().all()
        for row in users:
            data = {k: row[k] for k in user_cols}
            if "varsayilan_firma_id" in data:
                data["varsayilan_firma_id"] = firma_id
            dst.execute(text(f"insert into users ({ul}) values ({uph})"), data)
            dst.execute(
                text("insert into user_companies (user_id, company_id) values (:u, :c)"),
                {"u": data["id"], "c": firma_id},
            )
        sonuc["adimlar"].append({"ad": "kullanicilar", "ok": True, "adet": len(users)})

        dst.execute(
            text(
                "insert into app_settings (anahtar, deger) values "
                "('son_firma_id', :fid), ('tek_firma_otomatik_giris', '1'), "
                "('kurulum_tamam', '1')"
            ),
            {"fid": str(firma_id)},
        )
        for seq_table in (
            "roles",
            "permissions",
            "role_permissions",
            "users",
            "companies",
            "user_companies",
            "app_settings",
            "schema_migrations",
        ):
            dst.execute(
                text(
                    f"select setval(pg_get_serial_sequence('{seq_table}', 'id'), "
                    f"coalesce((select max(id) from {seq_table}), 1))"
                )
            )

    sonuc["basarili"] = True
    src_eng.dispose()
    dst_eng.dispose()
    _yaz(sonuc)
    print(json.dumps({"basarili": True, "firma": FIRMA_KOD, "users": len(users)}, ensure_ascii=False))
    return 0


def _yaz(sonuc: dict) -> None:
    CALISMA.mkdir(parents=True, exist_ok=True)
    (CALISMA / "D2_SISTEM_TOHUM.json").write_text(
        json.dumps(sonuc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CALISMA / "D2_SISTEM_TOHUM_OZET.json").write_text(
        json.dumps(
            {
                "zaman": sonuc.get("zaman"),
                "basarili": sonuc.get("basarili", False),
                "firma_kodu": FIRMA_KOD,
                "hedef_sistem": ONERILEN_SISTEM_DB,
                "hedef_firma": ONERILEN_FIRMA_DB,
                "aktif_profil_degistirilmedi": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
