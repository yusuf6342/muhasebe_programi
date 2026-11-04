"""SQLite → PostgreSQL geçiş aracı.

Kaynak: tutarlı TEST/yedek kopyası (canlıyı değiştirmez).
Hedef doluysa sessiz üzerine yazmaz. Sequence ayarı + satır sayısı mutabakatı.

Kullanım:
  set MUHASEBE_PG_PASSWORD=...
  .venv\\Scripts\\python.exe tools\\_sqlite_to_postgres_gecis.py --dry-run
  .venv\\Scripts\\python.exe tools\\_sqlite_to_postgres_gecis.py --uygula
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Büyük BLOB tabloları isteğe bağlı atlanabilir
ATLA_TABLOLAR = frozenset({"sqlite_sequence"})


def _sqlite_tablolar(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r[0] not in ATLA_TABLOLAR]


def _sayimlar(con: sqlite3.Connection, tablolar: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tablolar:
        try:
            out[t] = int(con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
        except sqlite3.Error:
            out[t] = -1
    return out


def _pg_sayimlar(eng, tablolar: list[str]) -> dict[str, int]:
    from sqlalchemy import text

    out: dict[str, int] = {}
    with eng.connect() as conn:
        for t in tablolar:
            try:
                out[t] = int(conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0)
            except Exception:
                out[t] = -1
    return out


def _kopyala_tablo(sqlite_con: sqlite3.Connection, pg_eng, tablo: str) -> int:
    from sqlalchemy import text

    cols = [r[1] for r in sqlite_con.execute(f'PRAGMA table_info("{tablo}")').fetchall()]
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    rows = sqlite_con.execute(f'SELECT {col_list} FROM "{tablo}"').fetchall()
    if not rows:
        return 0
    sql = text(f'INSERT INTO "{tablo}" ({col_list}) VALUES ({placeholders})')
    batch = [dict(zip(cols, row)) for row in rows]
    with pg_eng.begin() as conn:
        for i in range(0, len(batch), 500):
            chunk = batch[i : i + 500]
            conn.execute(sql, chunk)
    return len(batch)


def _sequences(pg_eng, tablolar: list[str]) -> None:
    from database.pg_helpers import pg_sequence_ayarla
    from sqlalchemy import inspect

    insp = inspect(pg_eng)
    with pg_eng.begin() as conn:
        for t in tablolar:
            try:
                cols = {c["name"] for c in insp.get_columns(t)}
            except Exception:
                continue
            if "id" in cols:
                try:
                    pg_sequence_ayarla(conn, t, "id")
                except Exception as exc:
                    print(f"  sequence uyarı {t}: {exc}")


def _sema_olustur(pg_eng, *, sistem_mi: bool) -> None:
    from database.pg_helpers import postgres_tr_norm_kur

    postgres_tr_norm_kur(pg_eng)
    if sistem_mi:
        from database.system.models import SystemBase

        SystemBase.metadata.create_all(pg_eng)
    else:
        # Firma modellerini yükle
        import database.database as dbmod  # noqa: F401
        from database.database import Base

        Base.metadata.create_all(pg_eng)


def _ozet_mutabakat(src: dict[str, int], dst: dict[str, int]) -> list[str]:
    farklar = []
    for t, a in sorted(src.items()):
        b = dst.get(t, -1)
        if a != b:
            farklar.append(f"{t}: kaynak={a} hedef={b}")
    return farklar


def main() -> int:
    p = argparse.ArgumentParser(description="SQLite→PostgreSQL geçiş")
    p.add_argument(
        "--kaynak",
        type=Path,
        default=Path.home()
        / "AppData/Local/CinMuhasebeTest/yedekler_ag_hazirlik/tam_yedek_2026-11-04_141614",
        help="Yedek/TEST kopya kökü (system.db + muhasebe.db veya companies)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--uygula", action="store_true", help="Gerçek aktarım (hedef boş olmalı)")
    p.add_argument("--hedef-host", default="127.0.0.1")
    p.add_argument("--hedef-port", type=int, default=5432)
    p.add_argument("--sistem-db", default="cin_sistem_deneme")
    p.add_argument("--firma-db", default="cin_firma_deneme")
    p.add_argument("--kullanici", default="cin_app")
    args = p.parse_args()

    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "kaynak": str(args.kaynak),
        "hedef": f"{args.hedef_host}:{args.hedef_port}",
        "adimlar": [],
    }

    print("Cin Muhasebe SQLite→PostgreSQL geçiş")
    print(f"  kaynak: {args.kaynak}")
    print(f"  hedef: {args.hedef_host}:{args.hedef_port}/ sistem={args.sistem_db} firma={args.firma_db}")

    if not args.kaynak.exists():
        print("HATA: kaynak klasör yok.")
        return 2

    sys_db = args.kaynak / "system.db"
    if not sys_db.is_file():
        # Alternatif: data altında
        alt = args.kaynak / "data" / "system.db"
        sys_db = alt if alt.is_file() else sys_db
    firma_db_path = args.kaynak / "muhasebe.db"
    if not firma_db_path.is_file():
        alt = args.kaynak / "data" / "muhasebe.db"
        if alt.is_file():
            firma_db_path = alt
        else:
            # companies klasöründe ilk .db
            for aday in (args.kaynak / "companies").glob("*.db") if (args.kaynak / "companies").is_dir() else []:
                firma_db_path = aday
                break
            if not firma_db_path.is_file():
                for aday in (args.kaynak / "data" / "companies").glob("*.db") if (args.kaynak / "data" / "companies").is_dir() else []:
                    firma_db_path = aday
                    break

    print(f"  system.db: {sys_db} ({'OK' if sys_db.is_file() else 'YOK'})")
    print(f"  firma.db:  {firma_db_path} ({'OK' if firma_db_path.is_file() else 'YOK'})")

    from database.baglanti_modu import BaglantiAyari, CalismaKipi, baglanti_sina, postgres_parola_al
    from database.engine_factory import postgres_engine
    from database.pg_helpers import pg_hedef_bos_mu

    ayar = BaglantiAyari.from_dict(
        {
            "kipi": CalismaKipi.YEREL_AG_POSTGRES.value,
            "postgres": {
                "host": args.hedef_host,
                "port": args.hedef_port,
                "sistem_db": args.sistem_db,
                "firma_db": args.firma_db,
                "kullanici": args.kullanici,
                "ortam": "DENEME",
                "sslmode": "prefer",
            },
        }
    )
    sina = baglanti_sina(ayar)
    if not sina.get("ok"):
        print("PostgreSQL bağlantı yok:", sina.get("hata"))
        rapor["adimlar"].append({"ad": "baglanti", "ok": False, "hata": sina.get("hata")})
        if args.dry_run:
            # Kaynak planı yine yaz
            if sys_db.is_file():
                with sqlite3.connect(f"file:{sys_db.resolve().as_posix()}?mode=ro", uri=True) as c:
                    st = _sqlite_tablolar(c)
                    print(f"  plan sistem tabloları ({len(st)}):", ", ".join(st[:20]), "...")
                    rapor["sistem_sayim"] = _sayimlar(c, st)
            if firma_db_path.is_file():
                with sqlite3.connect(f"file:{firma_db_path.resolve().as_posix()}?mode=ro", uri=True) as c:
                    ft = _sqlite_tablolar(c)
                    print(f"  plan firma tabloları ({len(ft)})")
                    rapor["firma_sayim"] = _sayimlar(c, ft)
            print("dry-run: bağlantı olmadan plan tamam.")
            _rapor_yaz(rapor)
            return 0
        return 3

    print("Bağlantı OK:", sina.get("server_version"))
    parola = postgres_parola_al()
    sistem_url = ayar.postgres.dsn_sistem(parola)
    firma_url = ayar.postgres.dsn_firma(parola, args.firma_db)

    if args.dry_run and not args.uygula:
        print("dry-run: şema/kopya uygulanmadı.")
        if sys_db.is_file():
            with sqlite3.connect(f"file:{sys_db.resolve().as_posix()}?mode=ro", uri=True) as c:
                rapor["sistem_sayim"] = _sayimlar(c, _sqlite_tablolar(c))
        if firma_db_path.is_file():
            with sqlite3.connect(f"file:{firma_db_path.resolve().as_posix()}?mode=ro", uri=True) as c:
                rapor["firma_sayim"] = _sayimlar(c, _sqlite_tablolar(c))
        _rapor_yaz(rapor)
        return 0

    if not args.uygula:
        print("Aktarım için --uygula verin (veya yalnız --dry-run).")
        return 1

    # --- SİSTEM ---
    if not sys_db.is_file():
        print("HATA: system.db yok")
        return 4
    eng_sys = postgres_engine(sistem_url)
    if not pg_hedef_bos_mu(eng_sys):
        print(f"HATA: hedef {args.sistem_db} dolu — üzerine yazılmaz.")
        eng_sys.dispose()
        return 5
    print("Sistem şema oluşturuluyor...")
    _sema_olustur(eng_sys, sistem_mi=True)
    with sqlite3.connect(f"file:{sys_db.resolve().as_posix()}?mode=ro", uri=True) as sc:
        stablolar = _sqlite_tablolar(sc)
        src_sys = _sayimlar(sc, stablolar)
        for t in stablolar:
            n = _kopyala_tablo(sc, eng_sys, t)
            print(f"  sistem {t}: {n}")
            rapor["adimlar"].append({"db": "sistem", "tablo": t, "satir": n})
        _sequences(eng_sys, stablolar)
        dst_sys = _pg_sayimlar(eng_sys, stablolar)
    fark_sys = _ozet_mutabakat(src_sys, dst_sys)
    rapor["sistem_fark"] = fark_sys
    print("Sistem mutabakat:", "OK" if not fark_sys else fark_sys[:10])

    # --- FİRMA ---
    if not firma_db_path.is_file():
        print("UYARI: firma SQLite yok; yalnız sistem aktarıldı.")
        eng_sys.dispose()
        _rapor_yaz(rapor)
        return 0 if not fark_sys else 6

    eng_fr = postgres_engine(firma_url)
    if not pg_hedef_bos_mu(eng_fr):
        print(f"HATA: hedef {args.firma_db} dolu — üzerine yazılmaz.")
        eng_fr.dispose()
        eng_sys.dispose()
        return 5
    print("Firma şema oluşturuluyor...")
    _sema_olustur(eng_fr, sistem_mi=False)
    with sqlite3.connect(f"file:{firma_db_path.resolve().as_posix()}?mode=ro", uri=True) as sc:
        ftablolar = _sqlite_tablolar(sc)
        # Yalnız PG şemasında olan tabloları kopyala
        from sqlalchemy import inspect

        pg_tablolar = set(inspect(eng_fr).get_table_names())
        kopyalanacak = [t for t in ftablolar if t in pg_tablolar]
        atlanan = [t for t in ftablolar if t not in pg_tablolar]
        if atlanan:
            print("  PG şemasında yok (atlandı):", ", ".join(atlanan[:30]))
            rapor["firma_atlanan"] = atlanan
        src_fr = _sayimlar(sc, kopyalanacak)
        for t in kopyalanacak:
            try:
                n = _kopyala_tablo(sc, eng_fr, t)
                print(f"  firma {t}: {n}")
                rapor["adimlar"].append({"db": "firma", "tablo": t, "satir": n})
            except Exception as exc:
                print(f"  HATA {t}: {exc}")
                rapor["adimlar"].append({"db": "firma", "tablo": t, "hata": str(exc)})
        _sequences(eng_fr, kopyalanacak)
        dst_fr = _pg_sayimlar(eng_fr, kopyalanacak)
    fark_fr = _ozet_mutabakat(src_fr, dst_fr)
    rapor["firma_fark"] = fark_fr
    print("Firma mutabakat:", "OK" if not fark_fr else fark_fr[:15])

    # Companies.db_path → pg:firma_db güncelle (sistem)
    try:
        from sqlalchemy import text

        with eng_sys.begin() as conn:
            conn.execute(
                text("UPDATE companies SET db_path = :p"),
                {"p": f"pg:{args.firma_db}"},
            )
        print(f"companies.db_path → pg:{args.firma_db}")
    except Exception as exc:
        print("companies.db_path güncelleme:", exc)

    eng_fr.dispose()
    eng_sys.dispose()
    _rapor_yaz(rapor)
    if fark_sys or fark_fr:
        print("Aktarım tamamlandı ama mutabakat farkı var — başarılı sayılmaz.")
        return 6
    print("Aktarım ve mutabakat OK.")
    return 0


def _rapor_yaz(rapor: dict) -> None:
    yol = ROOT / "kurulum" / "GECIS_RAPORU.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Rapor:", yol)


if __name__ == "__main__":
    raise SystemExit(main())
