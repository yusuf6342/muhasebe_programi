"""SQLite → PostgreSQL DENEME geçiş aracı (terminalden uzak host).

Düzeltmeler (2026-11-05):
1) companies.db_path yalnız seçilen firma (RAY001) için güncellenir; diğerleri
   Ray PG veritabanına yönlendirilmez ve seçilemez (aktif=false).
2) PG modelinde olmayan / kolon eksik tablolar aktarım öncesi raporlanır;
   dolu tablo/kolon atlanırsa başarı verilmez.
3) Tüm kaynak/hedef/şema/erişim önkoşulları yazmadan önce kontrol edilir.
4) Sistem ve firma ayrı transaction; yarım aktarım başarılı sayılmaz;
   hedef verisi otomatik silinmez.
5) Boolean/tarih/sayı/BLOB dönüşümü PG kolon tipine göre yapılır.
6) dry-run: kaynak_plan ile aktarim_uygunlugu ayrıdır; bağlantı yokken
   aktarılabilir onayı verilmez (çıkış kodu 7).
7) Proje kökünden (.venv) çalıştırılır; ana makinede 127.0.0.1 hedef olamaz
   (terminal için --hedef-host zorunlu LAN adresi).
8) Şema yükleme geçici MUHASEBE_DB_DIR altında; canlı veriye yazılmaz.

Kullanım (DESKTOP-FL08BVD örnek):
  .venv\\Scripts\\python.exe tools\\_sqlite_to_postgres_gecis.py --dry-run ^
    --kaynak \"%LOCALAPPDATA%\\CinMuhasebeAktarim\\Ray_Aktarim_2026-11-04_194017\\veri_yedek\" ^
    --hedef-host 192.168.1.114 --firma-kodu RAY001
  .venv\\Scripts\\python.exe tools\\_sqlite_to_postgres_gecis.py --uygula ...
Parola: MUHASEBE_PG_PASSWORD / keyring / güvenli istem (sohbete yazılmaz).
"""

from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import pkgutil
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ATLA_TABLOLAR = frozenset({"sqlite_sequence"})

# Sistem DB FK sırası (yoksa alfabetik sona)
_SISTEM_TABLO_SIRA = [
    "roles",
    "permissions",
    "companies",
    "users",
    "role_permissions",
    "user_companies",
    "user_permissions",
    "app_settings",
    "login_logs",
    "audit_logs",
    "schema_migrations",
]


def _sirali_tablolar(tablolar: list[str], oncelik: list[str] | None = None) -> list[str]:
    if not oncelik:
        return sorted(tablolar)
    idx = {n: i for i, n in enumerate(oncelik)}
    return sorted(tablolar, key=lambda t: (idx.get(t, 10_000), t))

# Talimattaki doğrulanmış 9 sayım (RAY001 / 2026)
BEKLENEN_SAYIMLAR = {
    "cari_kartlar": 1098,
    "stok_kartlari": 3031,
    "satis_faturalari": 9771,
    "alis_faturalari": 1080,
    "stok_hareketleri": 31909,
    "finans_hareketleri": 9819,
    "finans_hesaplari": 169,
    "satis_siparisleri": 228,
    "satis_irsaliyeleri": 10,
}

BOOL_TRUE = frozenset({"1", "true", "t", "yes", "y", "on"})
BOOL_FALSE = frozenset({"0", "false", "f", "no", "n", "off", ""})


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def _sqlite_tablolar(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
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
                # Eksik tablo / izin hatası tüm transaction'ı kilitlemesin
                conn.execute(text(f'SAVEPOINT sp_cnt_{abs(hash(t)) % 100000}'))
                out[t] = int(conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0)
                conn.execute(text(f'RELEASE SAVEPOINT sp_cnt_{abs(hash(t)) % 100000}'))
            except Exception:
                try:
                    conn.execute(text(f'ROLLBACK TO SAVEPOINT sp_cnt_{abs(hash(t)) % 100000}'))
                except Exception:
                    conn.rollback()
                out[t] = -1
    return out


def _ozet_mutabakat(src: dict[str, int], dst: dict[str, int]) -> list[str]:
    farklar = []
    for t, a in sorted(src.items()):
        b = dst.get(t, -1)
        if a != b:
            farklar.append(f"{t}: kaynak={a} hedef={b}")
    return farklar


def _kaynak_yollari(kaynak: Path) -> tuple[Path, Path]:
    sys_db = kaynak / "system.db"
    if not sys_db.is_file():
        alt = kaynak / "data" / "system.db"
        if alt.is_file():
            sys_db = alt
    firma = kaynak / "muhasebe.db"
    if not firma.is_file():
        alt = kaynak / "data" / "muhasebe.db"
        if alt.is_file():
            firma = alt
    return sys_db, firma


def _ray_firma_sec(sys_db: Path, firma_kodu: str) -> dict[str, Any]:
    with _sqlite_ro(sys_db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(companies)")]
        rows = c.execute("SELECT * FROM companies").fetchall()
    firmalar = [dict(zip(cols, r)) for r in rows]
    hedef = next(
        (f for f in firmalar if str(f.get("firma_kodu") or "").upper() == firma_kodu.upper()),
        None,
    )
    if hedef is None:
        raise ValueError(f"Firma kodu bulunamadı: {firma_kodu}")
    return {"secilen": hedef, "tum": firmalar}


def _dogrula_beklenen_sayimlar(firma_db: Path) -> tuple[bool, dict[str, Any]]:
    with _sqlite_ro(firma_db) as c:
        gercek = {t: int(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in BEKLENEN_SAYIMLAR}
    fark = {t: {"beklenen": BEKLENEN_SAYIMLAR[t], "kaynak": gercek[t]} for t in BEKLENEN_SAYIMLAR if gercek[t] != BEKLENEN_SAYIMLAR[t]}
    return (not fark), {"sayimlar": gercek, "farklar": fark}


def _sqlite_para_toplam(con: sqlite3.Connection, sql: str, *, scale: int = 2) -> float:
    """SQLite REAL altındaki NUMERIC(18,2) değerleri PG ile aynı ROUND_HALF_UP ile topla."""
    from decimal import ROUND_HALF_UP, Decimal

    q = Decimal(10) ** -scale
    toplam = Decimal(0)
    for (val,) in con.execute(sql):
        if val is None:
            continue
        toplam += Decimal(str(val)).quantize(q, rounding=ROUND_HALF_UP)
    return float(toplam)


def _mali_ozet_sqlite(firma_db: Path) -> dict[str, Any]:
    """Miktar 6 hane; para PG NUMERIC scale=2 ROUND_HALF_UP (SQLite REAL afinite farkı)."""
    with _sqlite_ro(firma_db) as c:
        return {
            "stok_hareket_abs_miktar": float(
                c.execute(
                    "SELECT ROUND(COALESCE(SUM(ABS(miktar)),0), 6) FROM stok_hareketleri"
                ).fetchone()[0]
                or 0
            ),
            "finans_hareket_tutar_toplam": _sqlite_para_toplam(
                c, "SELECT tutar FROM finans_hareketleri"
            ),
            "finans_hesap_acilis_toplam": _sqlite_para_toplam(
                c, "SELECT acilis_bakiyesi FROM finans_hesaplari"
            ),
            "satis_tl_genel_toplam": _sqlite_para_toplam(
                c, "SELECT tl_genel_toplam FROM satis_faturalari"
            ),
            "satis_tl_kdv": _sqlite_para_toplam(c, "SELECT tl_kdv FROM satis_faturalari"),
            "alis_tl_genel_toplam": _sqlite_para_toplam(
                c, "SELECT tl_genel_toplam FROM alis_faturalari"
            ),
            "alis_tl_kdv": _sqlite_para_toplam(c, "SELECT tl_kdv FROM alis_faturalari"),
        }


def _mali_ozet_pg(eng) -> dict[str, Any]:
    from sqlalchemy import text

    q = {
        "stok_hareket_abs_miktar": (
            'SELECT ROUND(COALESCE(SUM(ABS(miktar)),0)::numeric, 6) FROM "stok_hareketleri"'
        ),
        "finans_hareket_tutar_toplam": (
            'SELECT ROUND(COALESCE(SUM(ROUND(tutar::numeric, 4)),0), 2) FROM "finans_hareketleri"'
        ),
        "finans_hesap_acilis_toplam": (
            'SELECT ROUND(COALESCE(SUM(ROUND(acilis_bakiyesi::numeric, 4)),0), 2) FROM "finans_hesaplari"'
        ),
        "satis_tl_genel_toplam": (
            'SELECT ROUND(COALESCE(SUM(ROUND(tl_genel_toplam::numeric, 4)),0), 2) FROM "satis_faturalari"'
        ),
        "satis_tl_kdv": (
            'SELECT ROUND(COALESCE(SUM(ROUND(tl_kdv::numeric, 4)),0), 2) FROM "satis_faturalari"'
        ),
        "alis_tl_genel_toplam": (
            'SELECT ROUND(COALESCE(SUM(ROUND(tl_genel_toplam::numeric, 4)),0), 2) FROM "alis_faturalari"'
        ),
        "alis_tl_kdv": (
            'SELECT ROUND(COALESCE(SUM(ROUND(tl_kdv::numeric, 4)),0), 2) FROM "alis_faturalari"'
        ),
    }
    out: dict[str, Any] = {}
    with eng.connect() as conn:
        for k, sql in q.items():
            try:
                out[k] = float(conn.execute(text(sql)).scalar() or 0)
            except Exception as exc:
                out[k] = {"hata": str(exc)}
    return out


def _mali_farklar(src: dict[str, Any], dst: dict[str, Any], *, tol: float = 0.02) -> list[str]:
    """Para: 0.02 TL (kuruş); miktar aynı tolerans. Gerekçe: REAL→float birikimi."""
    farklar = []
    for k, a in src.items():
        b = dst.get(k)
        if isinstance(b, dict) and "hata" in b:
            farklar.append(f"{k}: hedef hata={b['hata']}")
            continue
        try:
            fa, fb = float(a), float(b)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            farklar.append(f"{k}: karşılaştırılamadı src={a!r} dst={b!r}")
            continue
        if abs(fa - fb) > tol:
            farklar.append(f"{k}: kaynak={fa} hedef={fb} delta={fa-fb}")
    return farklar


def _parola_al(*, istem_izin: bool) -> str:
    """Parola sohbete yazılmaz. İstem yalnız TTY + istem_izin iken."""
    from database.baglanti_modu import postgres_parola_al

    p = postgres_parola_al()
    if p:
        return p
    if not istem_izin:
        return ""
    if not sys.stdin.isatty():
        return ""
    try:
        p = getpass.getpass("cin_app PostgreSQL parolası: ")
    except Exception:
        p = ""
    return (p or "").strip()


def _modelleri_yukle_guvenli() -> Any:
    """Base.metadata doldur; canlı DB_DIR kullanmadan geçici scratch."""
    scratch = Path(tempfile.mkdtemp(prefix="cin_pg_sema_"))
    os.environ["MUHASEBE_DB_DIR"] = str(scratch)
    # database.database import yan etkisi scratch'e yazar; canlıya değil.
    import database.models as models_pkg

    for info in pkgutil.walk_packages(models_pkg.__path__, models_pkg.__name__ + "."):
        try:
            importlib.import_module(info.name)
        except Exception:
            continue
    # Servislerde tanımlı ek tablolar
    for mod_name in (
        "database.servis_sistem.models",
        "database.models.gider_rapor",
    ):
        try:
            importlib.import_module(mod_name)
        except Exception:
            pass
    from database.database import Base, engine as firma_eng

    try:
        firma_eng.dispose()
    except Exception:
        pass
    return Base


def _sqlite_decl_to_pg(decl: str | None, col: str) -> str:
    t = (decl or "").strip().upper()
    if "BOOL" in t:
        return "BOOLEAN"
    if "BLOB" in t or "BINARY" in t:
        return "BYTEA"
    if "DATETIME" in t or t == "TIMESTAMP" or t.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if t == "DATE":
        return "DATE"
    if t == "TIME":
        return "TIME"
    if "NUM" in t or "DEC" in t:
        m = re.search(r"\((\d+)\s*,\s*(\d+)\)", t)
        if m:
            return f"NUMERIC({m.group(1)},{m.group(2)})"
        return "NUMERIC"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE PRECISION"
    if "INT" in t:
        return "BIGINT"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t or t == "":
        return "TEXT"
    return "TEXT"


def _yansit_tablo_ddl(con: sqlite3.Connection, tablo: str) -> str:
    infos = con.execute(f'PRAGMA table_info("{tablo}")').fetchall()
    # cid, name, type, notnull, dflt, pk
    pks = [r[1] for r in infos if r[5]]
    parts: list[str] = []
    if len(pks) == 1:
        for _cid, name, decl, notnull, _dflt, pk in infos:
            pg_t = _sqlite_decl_to_pg(decl, name)
            if pk:
                parts.append(f'"{name}" {pg_t} PRIMARY KEY')
            else:
                null_sql = "NOT NULL" if notnull else ""
                parts.append(f'"{name}" {pg_t} {null_sql}'.strip())
    else:
        for _cid, name, decl, notnull, _dflt, pk in infos:
            pg_t = _sqlite_decl_to_pg(decl, name)
            null_sql = "NOT NULL" if notnull and not pk else ""
            parts.append(f'"{name}" {pg_t} {null_sql}'.strip())
        if pks:
            parts.append("PRIMARY KEY (" + ", ".join(f'"{p}"' for p in pks) + ")")
    return f'CREATE TABLE IF NOT EXISTS "{tablo}" (\n  ' + ",\n  ".join(parts) + "\n)"


def _eksik_kolonlari_ekle(pg_eng, sqlite_con: sqlite3.Connection, tablolar: list[str]) -> list[dict[str, str]]:
    """ORM create_all sonrası SQLite soft-ALTER kolonlarını ADD COLUMN ile tamamla."""
    from sqlalchemy import text

    eklenen: list[dict[str, str]] = []
    with pg_eng.begin() as conn:
        for tablo in tablolar:
            # information_schema — Inspector cache/clear_caches sürüm farkına bağlı kalma
            pg_cols = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=:t"
                    ),
                    {"t": tablo},
                ).fetchall()
            }
            if not pg_cols:
                continue
            for _cid, name, decl, _notnull, _dflt, _pk in sqlite_con.execute(
                f'PRAGMA table_info("{tablo}")'
            ).fetchall():
                if name in pg_cols:
                    continue
                pg_t = _sqlite_decl_to_pg(decl, name)
                conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{name}" {pg_t}'))
                eklenen.append({"tablo": tablo, "kolon": name, "tip": pg_t})
                pg_cols.add(name)
    return eklenen


def _kapsam_analizi(
    sqlite_con: sqlite3.Connection,
    orm_tables: set[str],
    pg_existing: set[str] | None = None,
) -> dict[str, Any]:
    st = _sqlite_tablolar(sqlite_con)
    sayim = _sayimlar(sqlite_con, st)
    orm_var = [t for t in st if t in orm_tables]
    orm_yok = [t for t in st if t not in orm_tables]
    dolu_orm_yok = [t for t in orm_yok if sayim.get(t, 0) > 0]
    bos_orm_yok = [t for t in orm_yok if sayim.get(t, 0) == 0]

    kolon_eksik: list[dict[str, Any]] = []
    return {
        "sqlite_tablo_sayisi": len(st),
        "orm_tablo_sayisi": len(orm_tables),
        "orm_eslesen": orm_var,
        "orm_disi_bos": bos_orm_yok,
        "orm_disi_dolu": dolu_orm_yok,
        "orm_disi_dolu_sayim": {t: sayim[t] for t in dolu_orm_yok},
        "yansitilacak": orm_yok,  # boş + dolu; hepsi DDL ile oluşturulacak
        "pg_mevcut": sorted(pg_existing or []),
        "kolon_eksik": kolon_eksik,
        "sayimlar": sayim,
    }


def _orm_kolon_kontrol(Base, sqlite_con: sqlite3.Connection) -> list[dict[str, Any]]:
    eksikler: list[dict[str, Any]] = []
    for tablo, table in Base.metadata.tables.items():
        try:
            sq_cols = {r[1] for r in sqlite_con.execute(f'PRAGMA table_info("{tablo}")').fetchall()}
        except sqlite3.Error:
            continue
        if not sq_cols:
            continue
        orm_cols = {c.name for c in table.columns}
        # SQLite'ta olup ORM'de olmayan ve veri içeren kolonlar
        for col in sorted(sq_cols - orm_cols):
            try:
                n = int(
                    sqlite_con.execute(
                        f'SELECT COUNT(*) FROM "{tablo}" WHERE "{col}" IS NOT NULL'
                    ).fetchone()[0]
                )
            except sqlite3.Error:
                n = -1
            if n > 0:
                eksikler.append({"tablo": tablo, "kolon": col, "dolu_satir": n, "yon": "sqlite>orm"})
        # ORM'de zorunlu olup SQLite'ta olmayan (aktarımda NULL kalır) — uyarı
        for col in table.columns:
            if col.name not in sq_cols and not col.nullable and col.default is None and not col.primary_key:
                eksikler.append(
                    {
                        "tablo": tablo,
                        "kolon": col.name,
                        "dolu_satir": 0,
                        "yon": "orm_zorunlu_sqlite_yok",
                    }
                )
    return eksikler


def _sema_olustur(pg_eng, *, sistem_mi: bool, Base=None, sqlite_con: sqlite3.Connection | None = None, yansit: list[str] | None = None) -> dict[str, Any]:
    from database.pg_helpers import postgres_tr_norm_kur
    from sqlalchemy import text

    postgres_tr_norm_kur(pg_eng)
    bilgi: dict[str, Any] = {"orm_create_all": False, "yansitilan": []}
    if sistem_mi:
        from database.system.models import SystemBase

        SystemBase.metadata.create_all(pg_eng)
        bilgi["orm_create_all"] = True
        return bilgi

    # Firma: ORM create_all PG'de Boolean DEFAULT 0 gibi SQLite kalıntıları yüzünden
    # düşebiliyor. Tüm tabloları SQLite PRAGMA'dan yansıt (tip dönüşümü dahil).
    if sqlite_con is None:
        raise RuntimeError("Firma şeması için sqlite bağlantısı gerekli")
    hedefler = list(yansit or [])
    if not hedefler:
        hedefler = _sqlite_tablolar(sqlite_con)
    with pg_eng.begin() as conn:
        for t in hedefler:
            ddl = _yansit_tablo_ddl(sqlite_con, t)
            conn.execute(text(ddl))
            bilgi["yansitilan"].append(t)
    bilgi["orm_create_all"] = False
    bilgi["yontem"] = "sqlite_pragma_yansitma"
    return bilgi


def _pg_kolon_tipleri(eng, tablo: str) -> dict[str, str]:
    from sqlalchemy import text

    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, udt_name "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t"
            ),
            {"t": tablo},
        ).fetchall()
    out: dict[str, str] = {}
    for name, data_type, udt in rows:
        out[name] = (udt or data_type or "").lower()
    return out


def _deger_donustur(val: Any, pg_udt: str) -> Any:
    if val is None:
        return None
    t = (pg_udt or "").lower()
    if t in ("bool", "boolean"):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        s = str(val).strip().lower()
        if s in BOOL_TRUE:
            return True
        if s in BOOL_FALSE:
            return False
        return bool(val)
    if t in ("bytea",):
        if isinstance(val, memoryview):
            return bytes(val)
        if isinstance(val, bytes):
            return val
        if isinstance(val, str):
            return val.encode("utf-8", errors="replace")
        return val
    if t in ("int2", "int4", "int8", "integer", "bigint", "smallint"):
        if val == "":
            return None
        return int(val)
    if t in ("float4", "float8", "double precision", "real"):
        if val == "":
            return None
        return float(val)
    if t in ("numeric", "decimal", "money"):
        if val == "":
            return None
        try:
            from decimal import ROUND_HALF_UP

            d = Decimal(str(val))
            # PG NUMERIC(18,2) ile aynı: kuruşa HALF_UP (SQLite REAL fazla hane taşır)
            return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return val
    if t in ("timestamp", "timestamptz", "date", "time"):
        if isinstance(val, (datetime, date, time)):
            return val
        s = str(val).strip()
        if not s:
            return None
        # SQLite sık formatlar
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if t == "date":
                    return dt.date()
                if t == "time":
                    return dt.time()
                return dt
            except ValueError:
                continue
        return val
    return val


def _kopyala_tablo(
    sqlite_con: sqlite3.Connection,
    pg_conn,
    tablo: str,
    pg_types: dict[str, str],
) -> int:
    from sqlalchemy import text

    sq_cols = [r[1] for r in sqlite_con.execute(f'PRAGMA table_info("{tablo}")').fetchall()]
    ortak = [c for c in sq_cols if c in pg_types]
    if not ortak:
        return 0
    col_list = ", ".join(f'"{c}"' for c in ortak)
    placeholders = ", ".join(f":{c}" for c in ortak)
    rows = sqlite_con.execute(f'SELECT {col_list} FROM "{tablo}"').fetchall()
    if not rows:
        return 0
    sql = text(f'INSERT INTO "{tablo}" ({col_list}) VALUES ({placeholders})')
    batch = []
    for row in rows:
        d = {}
        for c, v in zip(ortak, row):
            d[c] = _deger_donustur(v, pg_types[c])
        batch.append(d)
    # DISABLE TRIGGER ALL süperuser ister; başarısız olursa transaction'ı savepoint ile koru.
    trig_off = False
    pg_conn.execute(text("SAVEPOINT sp_trig_off"))
    try:
        pg_conn.execute(text(f'ALTER TABLE "{tablo}" DISABLE TRIGGER ALL'))
        trig_off = True
        pg_conn.execute(text("RELEASE SAVEPOINT sp_trig_off"))
    except Exception:
        pg_conn.execute(text("ROLLBACK TO SAVEPOINT sp_trig_off"))
    for i in range(0, len(batch), 500):
        pg_conn.execute(sql, batch[i : i + 500])
    if trig_off:
        pg_conn.execute(text("SAVEPOINT sp_trig_on"))
        try:
            pg_conn.execute(text(f'ALTER TABLE "{tablo}" ENABLE TRIGGER ALL'))
            pg_conn.execute(text("RELEASE SAVEPOINT sp_trig_on"))
        except Exception:
            pg_conn.execute(text("ROLLBACK TO SAVEPOINT sp_trig_on"))
    return len(batch)


def _sequences(pg_eng, tablolar: list[str]) -> list[str]:
    from database.pg_helpers import pg_sequence_ayarla
    from sqlalchemy import inspect

    uyari: list[str] = []
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
                    uyari.append(f"{t}: {exc}")
    return uyari


def _companies_pilot_guncelle(eng_sys, *, firma_kodu: str, firma_db_adi: str) -> dict[str, Any]:
    """Yalnız seçilen firmanın db_path'ini pg:firma_db yap; diğerlerini kilitle."""
    from sqlalchemy import text

    with eng_sys.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id, firma_kodu, unvan FROM companies "
                "WHERE UPPER(firma_kodu)=UPPER(:k)"
            ),
            {"k": firma_kodu},
        ).fetchone()
        if not row:
            raise RuntimeError(f"PG sistemde firma yok: {firma_kodu}")
        cid = int(row[0])
        conn.execute(
            text(
                "UPDATE companies SET db_path=:p, aktif=TRUE WHERE id=:id"
            ),
            {"p": f"pg:{firma_db_adi}", "id": cid},
        )
        # Diğer firmalar Ray verisine erişmesin
        diger = conn.execute(
            text(
                "UPDATE companies SET aktif=FALSE, "
                "db_path='pg:__kapsam_disi_aktarilmadi__' "
                "WHERE id<>:id RETURNING id, firma_kodu"
            ),
            {"id": cid},
        ).fetchall()
    return {
        "ray_id": cid,
        "ray_db_path": f"pg:{firma_db_adi}",
        "kilitlenen": [{"id": int(r[0]), "firma_kodu": r[1]} for r in diger],
    }


def _hedef_ozet(eng) -> dict[str, Any]:
    from database.pg_helpers import pg_public_tablo_sayisi
    from sqlalchemy import text

    with eng.connect() as conn:
        n = pg_public_tablo_sayisi(conn)
        sayimlar: dict[str, int] = {}
        tabs: list[str] = []
        if n:
            tabs = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_type='BASE TABLE' "
                        "ORDER BY 1"
                    )
                ).fetchall()
            ]
            for t in tabs:
                try:
                    sayimlar[t] = int(conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0)
                except Exception:
                    sayimlar[t] = -1
        dolu = {t: c for t, c in sayimlar.items() if c != 0}
        return {
            "tablo_sayisi": n,
            "tablolar": tabs,
            "sayimlar": sayimlar,
            "ornek_sayimlar": {k: sayimlar[k] for k in list(sayimlar)[:50]},
            "dolu_tablolar": dolu,
            "sadece_bos_sema": n > 0 and not dolu and all(c >= 0 for c in sayimlar.values()),
        }


def _bos_semayi_temizle(eng) -> None:
    """Yalnız tüm tablolar 0 satırsa public şemayı sıfırlar. Dolu veriye dokunmaz."""
    from sqlalchemy import text

    ozet = _hedef_ozet(eng)
    if ozet["tablo_sayisi"] == 0:
        return
    if not ozet["sadece_bos_sema"]:
        raise RuntimeError(
            f"Boş şema temizliği reddedildi; dolu/okunamayan tablolar: {ozet['dolu_tablolar']}"
        )
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def _rapor_yaz(rapor: dict) -> Path:
    yol = ROOT / "kurulum" / "GECIS_RAPORU.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print("Rapor:", yol)
    return yol


def main() -> int:
    p = argparse.ArgumentParser(description="SQLite→PostgreSQL DENEME geçiş")
    p.add_argument(
        "--kaynak",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", ""))
        / "CinMuhasebeAktarim"
        / "Ray_Aktarim_2026-11-04_194017"
        / "veri_yedek",
        help="Doğrulanmış DENEME yedek kökü (system.db + muhasebe.db)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--uygula", action="store_true")
    p.add_argument("--hedef-host", default="", help="Ana makine LAN IP/host (127.0.0.1 terminalde yasak)")
    p.add_argument("--hedef-port", type=int, default=5432)
    p.add_argument("--sistem-db", default="cin_sistem_deneme")
    p.add_argument("--firma-db", default="cin_firma_deneme")
    p.add_argument("--kullanici", default="cin_app")
    p.add_argument("--firma-kodu", default="RAY001")
    p.add_argument(
        "--sslmode",
        default="require",
        help="TLS zorunlu: require veya verify-full. prefer/disable kabul edilmez.",
    )
    p.add_argument(
        "--localhost-izin",
        action="store_true",
        help="Yalnız ana makinede yerel çalıştırma için 127.0.0.1'e izin verir",
    )
    args = p.parse_args()

    rapor: dict[str, Any] = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": os.environ.get("COMPUTERNAME"),
        "kaynak": str(args.kaynak),
        "hedef": f"{args.hedef_host}:{args.hedef_port}",
        "sistem_db": args.sistem_db,
        "firma_db": args.firma_db,
        "firma_kapsami": {
            "firma_kodu": args.firma_kodu,
            "aciklama": "Yalnız bu firma pg:firma_db'ye bağlanır; diğerleri kilitlenir.",
        },
        "adimlar": [],
        "basarili": False,
        "aktarim_uygunlugu": False,
        "kaynak_plan_hazir": False,
    }

    print("Cin Muhasebe SQLite→PostgreSQL geçiş")
    print(f"  kaynak: {args.kaynak}")
    print(f"  hedef: {args.hedef_host or '(yok)'}:{args.hedef_port}")
    print(f"  sistem={args.sistem_db} firma={args.firma_db} firma_kodu={args.firma_kodu}")
    print(f"  sslmode={args.sslmode}")

    if not args.kaynak.exists():
        print("HATA: kaynak klasör yok.")
        rapor["hata"] = "kaynak yok"
        _rapor_yaz(rapor)
        return 2

    if not args.hedef_host:
        print("HATA: --hedef-host gerekli (ana makine LAN IP/host).")
        rapor["hata"] = "hedef-host yok"
        _rapor_yaz(rapor)
        return 2

    sslmode = (args.sslmode or "").strip().lower()
    if sslmode not in ("require", "verify-ca", "verify-full"):
        print(
            f"HATA: sslmode={args.sslmode!r} yasak. "
            "TLS zorunlu: require | verify-ca | verify-full (prefer/disable yok)."
        )
        rapor["hata"] = "sslmode zayif"
        _rapor_yaz(rapor)
        return 2
    args.sslmode = sslmode

    host = args.hedef_host.strip()
    if host in ("127.0.0.1", "localhost", "::1") and not args.localhost_izin:
        print(
            "HATA: Terminalden 127.0.0.1 hedef olamaz (bu makinenin kendisi). "
            "Ana makine LAN IP/host verin veya ana makinede --localhost-izin kullanın."
        )
        rapor["hata"] = "localhost yasak"
        _rapor_yaz(rapor)
        return 2

    sys_db, firma_db = _kaynak_yollari(args.kaynak)
    if not sys_db.is_file() or not firma_db.is_file():
        print("HATA: system.db veya muhasebe.db yok")
        rapor["hata"] = "eksik db"
        _rapor_yaz(rapor)
        return 2

    # --- Kaynak kimlik / sayım ---
    try:
        firma_bilgi = _ray_firma_sec(sys_db, args.firma_kodu)
    except ValueError as exc:
        print("HATA:", exc)
        rapor["hata"] = str(exc)
        _rapor_yaz(rapor)
        return 2

    rapor["firma_kapsami"]["secilen"] = {
        "id": firma_bilgi["secilen"].get("id"),
        "firma_kodu": firma_bilgi["secilen"].get("firma_kodu"),
        "unvan": firma_bilgi["secilen"].get("unvan"),
        "kaynak_db_path": firma_bilgi["secilen"].get("db_path"),
    }
    rapor["firma_kapsami"]["aktarilmayan"] = [
        {
            "id": f.get("id"),
            "firma_kodu": f.get("firma_kodu"),
            "unvan": f.get("unvan"),
            "kaynak_db_path": f.get("db_path"),
            "not": "SQLite dosyası korunur; PG pilotunda seçilemez / Ray verisine bağlanmaz",
        }
        for f in firma_bilgi["tum"]
        if f.get("id") != firma_bilgi["secilen"].get("id")
    ]
    print(
        f"  firma: {firma_bilgi['secilen'].get('firma_kodu')} — "
        f"{firma_bilgi['secilen'].get('unvan')}"
    )

    ok_sayim, sayim_rapor = _dogrula_beklenen_sayimlar(firma_db)
    rapor["beklenen_sayim_kontrol"] = sayim_rapor
    if not ok_sayim:
        print("HATA: kaynak sayımlar doğrulanmış RAY001/2026 ile eşleşmiyor:", sayim_rapor["farklar"])
        rapor["hata"] = "sayim uyumsuz"
        _rapor_yaz(rapor)
        return 2
    print("  beklenen 9 sayım: OK")
    rapor["mali_kaynak"] = _mali_ozet_sqlite(firma_db)
    rapor["kaynak_plan_hazir"] = True

    # --- ORM / kapsam (yazmadan, canlıya dokunmadan) ---
    Base = _modelleri_yukle_guvenli()
    orm_tables = set(Base.metadata.tables.keys())
    with _sqlite_ro(firma_db) as sc:
        kapsam = _kapsam_analizi(sc, orm_tables)
        kolon_eksik = _orm_kolon_kontrol(Base, sc)
        kapsam["kolon_eksik"] = kolon_eksik
    with _sqlite_ro(sys_db) as sc:
        stablolar_sys = _sqlite_tablolar(sc)
        rapor["sistem_sayim"] = _sayimlar(sc, stablolar_sys)
    soft_alter_kolonlar = [k for k in kolon_eksik if k.get("yon") == "sqlite>orm"]
    rapor["firma_kapsam_analizi"] = {
        "sqlite_tablo_sayisi": kapsam["sqlite_tablo_sayisi"],
        "orm_tablo_sayisi": len(orm_tables),
        "orm_disi_dolu": kapsam["orm_disi_dolu"],
        "orm_disi_dolu_sayim": kapsam["orm_disi_dolu_sayim"],
        "yansitilacak_sayisi": len(kapsam["yansitilacak"]),
        "soft_alter_kolon_sayisi": len(soft_alter_kolonlar),
        "kolon_eksik_ornek": soft_alter_kolonlar[:30],
        "plan": "ORM create_all + soft-ALTER ADD COLUMN + ORM-dışı CREATE TABLE yansıtma",
    }
    print(
        f"  firma tabloları: sqlite={kapsam['sqlite_tablo_sayisi']} "
        f"orm={len(orm_tables)} yansitilacak={len(kapsam['yansitilacak'])} "
        f"orm_disi_dolu={len(kapsam['orm_disi_dolu'])} "
        f"soft_alter_kolon={len(soft_alter_kolonlar)}"
    )

    # --- Bağlantı ---
    from database.baglanti_modu import BaglantiAyari, CalismaKipi, baglanti_sina
    from database.engine_factory import postgres_engine
    from database.pg_helpers import pg_hedef_bos_mu

    ayar = BaglantiAyari.from_dict(
        {
            "kipi": CalismaKipi.YEREL_AG_POSTGRES.value,
            "postgres": {
                "host": host,
                "port": args.hedef_port,
                "sistem_db": args.sistem_db,
                "firma_db": args.firma_db,
                "kullanici": args.kullanici,
                "ortam": "DENEME",
                "sslmode": args.sslmode,
            },
        }
    )

    # dry-run: yalnız env/keyring (askıya alma). --uygula: TTY ise gizli istem.
    parola = _parola_al(istem_izin=bool(args.uygula))
    sina = baglanti_sina(ayar, parola=parola or None)
    rapor["adimlar"].append({"ad": "baglanti", "ok": bool(sina.get("ok")), "hata": sina.get("hata")})
    if not sina.get("ok"):
        print("PostgreSQL bağlantı yok:", sina.get("hata"))
        print("kaynak_plan_hazir=True; aktarim_uygunlugu=False")
        rapor["aktarim_uygunlugu"] = False
        _rapor_yaz(rapor)
        if args.dry_run and not args.uygula:
            return 7
        return 3

    print("Bağlantı OK:", sina.get("server_version"))
    sistem_url = ayar.postgres.dsn_sistem(parola)
    firma_url = ayar.postgres.dsn_firma(parola, args.firma_db)
    eng_sys = postgres_engine(sistem_url)
    eng_fr = postgres_engine(firma_url)

    # TLS gerçekten kullanılıyor mu? (prefer sessizce şifresiz düşmesin)
    from sqlalchemy import text as _sql_text

    try:
        with eng_sys.connect() as _c:
            row = _c.execute(
                _sql_text(
                    "SELECT ssl, version, cipher FROM pg_stat_ssl "
                    "WHERE pid = pg_backend_pid()"
                )
            ).fetchone()
        ssl_used = bool(row[0]) if row else False
        ssl_ver = row[1] if row else None
        ssl_cipher = row[2] if row else None
        rapor["tls"] = {
            "sslmode": args.sslmode,
            "ssl_is_used": ssl_used,
            "ssl_version": ssl_ver,
            "cipher": ssl_cipher,
        }
        print(
            f"  TLS: sslmode={args.sslmode} ssl_is_used={ssl_used} "
            f"ver={ssl_ver} cipher={ssl_cipher}"
        )
        if not ssl_used:
            print("HATA: Bağlantı şifresiz — TLS zorunlu; aktarım durduruldu.")
            rapor["aktarim_uygunlugu"] = False
            rapor["hata"] = "tls yok"
            _rapor_yaz(rapor)
            eng_fr.dispose()
            eng_sys.dispose()
            return 3
    except Exception as exc:
        print("HATA: TLS doğrulama sorgusu başarısız:", exc)
        rapor["aktarim_uygunlugu"] = False
        rapor["hata"] = f"tls dogrulama: {exc}"
        _rapor_yaz(rapor)
        eng_fr.dispose()
        eng_sys.dispose()
        return 3

    try:
        sys_ozet = _hedef_ozet(eng_sys)
        fr_ozet = _hedef_ozet(eng_fr)
        rapor["hedef_on_kontrol"] = {"sistem": sys_ozet, "firma": fr_ozet}
        print(f"  hedef sistem tabloları: {sys_ozet['tablo_sayisi']}")
        print(f"  hedef firma tabloları: {fr_ozet['tablo_sayisi']}")

        with _sqlite_ro(sys_db) as _sc_plan:
            _st_plan = _sirali_tablolar(_sqlite_tablolar(_sc_plan), _SISTEM_TABLO_SIRA)
            src_sys_plan = _sayimlar(_sc_plan, _st_plan)
        sistem_atla = False
        firma_atla = False
        if sys_ozet.get("dolu_tablolar"):
            dst_sys_now = _pg_sayimlar(eng_sys, list(src_sys_plan.keys()))
            fark_sys_now = _ozet_mutabakat(src_sys_plan, dst_sys_now)
            if fark_sys_now:
                print("HATA: sistem hedefte veri var ve kaynakla eşleşmiyor — silinmez.")
                rapor["sistem_fark_mevcut"] = fark_sys_now[:30]
                rapor["aktarim_uygunlugu"] = False
                rapor["hata"] = "sistem hedef dolu/uyumsuz"
                _rapor_yaz(rapor)
                return 4
            sistem_atla = True
            rapor["sistem_fark"] = []
            print("  sistem: mevcut veri kaynakla eşleşiyor — yeniden kopyalanmayacak")
        if fr_ozet.get("dolu_tablolar"):
            # Firma doluysa yalnız tam eşleşme ile atlanır; aksi halde dur
            dst_fr_now = _pg_sayimlar(eng_fr, list(kapsam["sayimlar"].keys())[:80])
            # kaba kontrol: 9 ana sayım
            ana = {t: kapsam["sayimlar"][t] for t in BEKLENEN_SAYIMLAR}
            dst_ana = _pg_sayimlar(eng_fr, list(ana.keys()))
            fark_fr_now = _ozet_mutabakat(ana, dst_ana)
            if fark_fr_now:
                print("HATA: firma hedefte veri var ve kaynakla eşleşmiyor — silinmez.")
                rapor["firma_fark_mevcut"] = fark_fr_now
                rapor["aktarim_uygunlugu"] = False
                rapor["hata"] = "firma hedef dolu/uyumsuz"
                _rapor_yaz(rapor)
                return 4
            firma_atla = True
            print("  firma: mevcut ana sayımlar eşleşiyor — yeniden kopyalanmayacak")

        # Önceki başarısız denemeden kalan 0-satırlı şema: dry-run'da bildir, uygula'da temizle
        bos_sema = []
        if (not sistem_atla) and sys_ozet["tablo_sayisi"] > 0 and sys_ozet.get("sadece_bos_sema"):
            bos_sema.append("sistem")
        if (not firma_atla) and fr_ozet["tablo_sayisi"] > 0 and fr_ozet.get("sadece_bos_sema"):
            bos_sema.append("firma")
        if bos_sema:
            rapor["bos_sema_tespit"] = bos_sema
            print(f"  UYARI: boş şema (0 satır) tespit: {bos_sema}")

        if not sistem_atla and not firma_atla and not bos_sema:
            if not pg_hedef_bos_mu(eng_sys) or not pg_hedef_bos_mu(eng_fr):
                print("HATA: pg_hedef_bos_mu false")
                rapor["aktarim_uygunlugu"] = False
                _rapor_yaz(rapor)
                return 4

        rapor["aktarim_uygunlugu"] = True
        rapor["adimlar"].append({"ad": "on_kontrol", "ok": True, "sistem_atla": sistem_atla, "firma_atla": firma_atla})

        if args.dry_run and not args.uygula:
            print("dry-run: aktarim_uygunlugu=True — şema/kopya uygulanmadı.")
            if bos_sema:
                print("  Not: --uygula sırasında yalnız 0-satırlı şema temizlenir; dolu veri silinmez.")
            rapor["firma_sayim"] = kapsam["sayimlar"]
            _rapor_yaz(rapor)
            return 0

        if not args.uygula:
            print("Aktarım için --uygula verin (veya yalnız --dry-run).")
            _rapor_yaz(rapor)
            return 1

        # ========== UYGULA ==========
        # Sistem + firma ayrı transaction; companies güncellemesi en sonda.
        # Hata → basarili=False; dolu veri otomatik silinmez.
        if "sistem" in bos_sema:
            print("Sistem: boş şema temizleniyor (tüm sayımlar 0)...")
            _bos_semayi_temizle(eng_sys)
            rapor["adimlar"].append({"ad": "bos_sema_temiz_sistem", "ok": True})
        if "firma" in bos_sema:
            print("Firma: boş şema temizleniyor (tüm sayımlar 0)...")
            _bos_semayi_temizle(eng_fr)
            rapor["adimlar"].append({"ad": "bos_sema_temiz_firma", "ok": True})

        if sistem_atla:
            print("Sistem kopya atlandı (zaten mutabık).")
            rapor["adimlar"].append({"ad": "sistem_atlandi", "ok": True})
        else:
            print("Sistem şema + kopya...")
            try:
                with _sqlite_ro(sys_db) as sc:
                    stablolar = _sirali_tablolar(_sqlite_tablolar(sc), _SISTEM_TABLO_SIRA)
                    src_sys = _sayimlar(sc, stablolar)
                    _sema_olustur(eng_sys, sistem_mi=True)
                    ek_sys = _eksik_kolonlari_ekle(eng_sys, sc, stablolar)
                    rapor["sema_sistem"] = {"eklenen_kolon_sayisi": len(ek_sys)}

                    # tek transaction
                    with eng_sys.begin() as conn:
                        conn.execute(_sql_text("SAVEPOINT sp_defer"))
                        try:
                            conn.execute(_sql_text("SET CONSTRAINTS ALL DEFERRED"))
                            conn.execute(_sql_text("RELEASE SAVEPOINT sp_defer"))
                        except Exception:
                            conn.execute(_sql_text("ROLLBACK TO SAVEPOINT sp_defer"))
                        for t in stablolar:
                            types = _pg_kolon_tipleri(eng_sys, t)
                            if not types:
                                raise RuntimeError(f"Sistem tablosu PG'de yok: {t}")
                            n = _kopyala_tablo(sc, conn, t, types)
                            print(f"  sistem {t}: {n}")
                            rapor["adimlar"].append({"db": "sistem", "tablo": t, "satir": n})
                    seq_uyari = _sequences(eng_sys, stablolar)
                    dst_sys = _pg_sayimlar(eng_sys, stablolar)
                fark_sys = _ozet_mutabakat(src_sys, dst_sys)
                rapor["sistem_fark"] = fark_sys
                rapor["sequence_uyari_sistem"] = seq_uyari
                if fark_sys:
                    print("Sistem mutabakat FARK:", fark_sys[:15])
                    rapor["hata"] = "sistem mutabakat"
                    _rapor_yaz(rapor)
                    return 6
                print("Sistem mutabakat: OK")
            except Exception as exc:
                print("HATA sistem aktarım:", exc)
                rapor["hata"] = f"sistem: {exc}"
                rapor["kismi"] = True
                _rapor_yaz(rapor)
                return 8

        if firma_atla:
            print("Firma kopya atlandı (zaten mutabık).")
            rapor["adimlar"].append({"ad": "firma_atlandi", "ok": True})
        else:
            print("Firma şema + kopya...")
            try:
                with _sqlite_ro(firma_db) as sc:
                    ftablolar = _sqlite_tablolar(sc)
                    src_fr = _sayimlar(sc, ftablolar)
                    sema_bilgi = _sema_olustur(
                        eng_fr,
                        sistem_mi=False,
                        Base=Base,
                        sqlite_con=sc,
                        yansit=ftablolar,
                    )
                    rapor["sema_firma"] = {
                        "orm_create_all": sema_bilgi["orm_create_all"],
                        "yontem": sema_bilgi.get("yontem"),
                        "yansitilan_sayisi": len(sema_bilgi["yansitilan"]),
                    }
                    from sqlalchemy import inspect

                    pg_tabs = set(inspect(eng_fr).get_table_names())
                    eksik_tablo = [t for t in ftablolar if t not in pg_tabs]
                    if eksik_tablo:
                        rapor["firma_atlanan"] = eksik_tablo
                        rapor["hata"] = "firma tablo eksik"
                        print("HATA PG'de tablo yok:", eksik_tablo[:30])
                        _rapor_yaz(rapor)
                        return 5

                    with eng_fr.begin() as conn:
                        for t in ftablolar:
                            types = _pg_kolon_tipleri(eng_fr, t)
                            sq_cols = {
                                r[1]
                                for r in sc.execute(f'PRAGMA table_info("{t}")').fetchall()
                            }
                            kayip = []
                            for col in sq_cols - set(types):
                                nnull = int(
                                    sc.execute(
                                        f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NOT NULL'
                                    ).fetchone()[0]
                                )
                                if nnull > 0:
                                    kayip.append({"kolon": col, "dolu": nnull})
                            if kayip:
                                raise RuntimeError(f"{t} kolon kaybı: {kayip}")
                            n = _kopyala_tablo(sc, conn, t, types)
                            print(f"  firma {t}: {n}")
                            rapor["adimlar"].append({"db": "firma", "tablo": t, "satir": n})
                    seq_uyari_f = _sequences(eng_fr, ftablolar)
                    dst_fr = _pg_sayimlar(eng_fr, ftablolar)
                fark_fr = _ozet_mutabakat(src_fr, dst_fr)
                rapor["firma_fark"] = fark_fr
                rapor["sequence_uyari_firma"] = seq_uyari_f
                if fark_fr:
                    print("Firma mutabakat FARK:", fark_fr[:20])
                    rapor["hata"] = "firma mutabakat"
                    _rapor_yaz(rapor)
                    return 6
                print("Firma satır mutabakat: OK")
            except Exception as exc:
                print("HATA firma aktarım:", exc)
                rapor["hata"] = f"firma: {exc}"
                rapor["kismi"] = True
                _rapor_yaz(rapor)
                return 8

        # Mali mutabakat
        mali_dst = _mali_ozet_pg(eng_fr)
        rapor["mali_hedef"] = mali_dst
        mali_fark = _mali_farklar(rapor["mali_kaynak"], mali_dst)
        rapor["mali_fark"] = mali_fark
        if mali_fark:
            print("Mali mutabakat FARK:", mali_fark)
            rapor["hata"] = "mali mutabakat"
            _rapor_yaz(rapor)
            return 6
        print("Mali mutabakat: OK")

        # Companies güncellemesi en sonda
        try:
            guncelle = _companies_pilot_guncelle(
                eng_sys, firma_kodu=args.firma_kodu, firma_db_adi=args.firma_db
            )
            rapor["companies_guncelleme"] = guncelle
            print(
                f"companies: {args.firma_kodu} → pg:{args.firma_db}; "
                f"kilitlenen={len(guncelle['kilitlenen'])}"
            )
        except Exception as exc:
            print("HATA companies güncelleme:", exc)
            rapor["hata"] = f"companies: {exc}"
            rapor["kismi"] = True
            _rapor_yaz(rapor)
            return 8

        rapor["basarili"] = True
        rapor["geri_donus"] = {
            "sqlite_deneme": r"C:\CinMuhasebe\DENEME_2026-11-04_194017 (ana makine)",
            "kaynak_yedek_terminal": str(args.kaynak),
            "pg_otomatik_silinmedi": True,
            "not": "PG kip başarısızsa sessiz SQLite fallback yok; Bağlantı Ayarları'nda yerel SQLite'a dönün.",
        }
        _rapor_yaz(rapor)
        print("Aktarım ve mutabakat OK.")
        return 0
    finally:
        eng_fr.dispose()
        eng_sys.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
