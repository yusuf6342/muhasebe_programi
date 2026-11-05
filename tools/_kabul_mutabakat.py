"""Kaynak SQLite yedek ↔ PG deneme mutabakatı (satır + mali + örnekler)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from tools._sqlite_to_postgres_gecis import (  # noqa: E402
    BEKLENEN_SAYIMLAR,
    _kaynak_yollari,
    _mali_farklar,
    _mali_ozet_pg,
    _mali_ozet_sqlite,
    _ozet_mutabakat,
    _pg_sayimlar,
    _sayimlar,
    _sqlite_ro,
    _sqlite_tablolar,
)

HOST = "192.168.1.114"
SISTEM = "cin_sistem_deneme"
FIRMA = "cin_firma_deneme"
KAYNAK = Path(
    r"C:\Users\cigde\AppData\Local\CinMuhasebeAktarim"
    r"\Ray_Aktarim_2026-11-04_194017\veri_yedek"
)


def _eng(db: str):
    pwd = quote_plus(postgres_parola_al())
    url = f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/{db}?sslmode=require"
    return create_engine(url, connect_args={"connect_timeout": 15})


def _ornek_tr_karakter(eng, sqlite_path: Path) -> dict:
    """Türkçe karakter / NULL / küsurat örnekleri."""
    out: dict = {}
    with _sqlite_ro(sqlite_path) as c:
        row = c.execute(
            "SELECT id, unvan FROM cari_kartlar "
            "WHERE unvan LIKE '%ş%' OR unvan LIKE '%ğ%' OR unvan LIKE '%ü%' "
            "LIMIT 1"
        ).fetchone()
        out["sqlite_tr_cari"] = {"id": row[0], "unvan": row[1]} if row else None
        miktar = c.execute(
            "SELECT id, miktar FROM stok_hareketleri "
            "WHERE miktar IS NOT NULL AND ABS(miktar - ROUND(miktar)) > 0.000001 "
            "LIMIT 1"
        ).fetchone()
        out["sqlite_kusurat_hareket"] = (
            {"id": miktar[0], "miktar": miktar[1]} if miktar else None
        )
        null_ornek = c.execute(
            "SELECT id FROM cari_kartlar WHERE telefon IS NULL OR telefon = '' LIMIT 1"
        ).fetchone()
        out["sqlite_null_telefon_cari_id"] = null_ornek[0] if null_ornek else None

    with eng.connect() as conn:
        if out.get("sqlite_tr_cari"):
            cid = out["sqlite_tr_cari"]["id"]
            pg = conn.execute(
                text('SELECT id, unvan FROM cari_kartlar WHERE id = :i'),
                {"i": cid},
            ).mappings().first()
            out["pg_tr_cari"] = dict(pg) if pg else None
            out["tr_eslesme"] = (
                pg is not None
                and pg["unvan"] == out["sqlite_tr_cari"]["unvan"]
            )
        if out.get("sqlite_kusurat_hareket"):
            hid = out["sqlite_kusurat_hareket"]["id"]
            pg = conn.execute(
                text('SELECT id, miktar FROM stok_hareketleri WHERE id = :i'),
                {"i": hid},
            ).mappings().first()
            out["pg_kusurat_hareket"] = (
                {"id": pg["id"], "miktar": float(pg["miktar"])} if pg else None
            )
        if out.get("sqlite_null_telefon_cari_id") is not None:
            cid = out["sqlite_null_telefon_cari_id"]
            tel = conn.execute(
                text("SELECT telefon FROM cari_kartlar WHERE id = :i"),
                {"i": cid},
            ).scalar()
            out["pg_null_telefon"] = tel
            out["null_korundu"] = tel is None or tel == ""
    return out


def _sequence_kontrol(eng) -> dict:
    """Yeni kimliklerin mevcut max ile çakışmaması."""
    checks = {}
    with eng.connect() as conn:
        for tablo in ("satis_faturalari", "cari_kartlar", "stok_kartlari", "stok_hareketleri"):
            try:
                mx = conn.execute(text(f'SELECT COALESCE(MAX(id),0) FROM "{tablo}"')).scalar()
                seq = conn.execute(
                    text(
                        "SELECT pg_get_serial_sequence(:t, 'id')"
                    ),
                    {"t": tablo},
                ).scalar()
                last = None
                if seq:
                    last = conn.execute(text("SELECT last_value FROM " + seq)).scalar()
                checks[tablo] = {
                    "max_id": int(mx or 0),
                    "sequence": seq,
                    "last_value": int(last) if last is not None else None,
                    "ok": (last is None) or (int(last) >= int(mx or 0)),
                }
            except Exception as exc:
                checks[tablo] = {"hata": str(exc)[:200]}
    return checks


def main() -> int:
    sys_db, firma_db = _kaynak_yollari(KAYNAK)
    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "kaynak": str(KAYNAK),
        "hedef": f"{HOST}:{SISTEM}/{FIRMA}",
        "sistem_db_path": str(sys_db),
        "firma_db_path": str(firma_db),
    }
    if not sys_db.is_file() or not firma_db.is_file():
        rapor["hata"] = "kaynak sqlite yok"
        print(json.dumps(rapor, ensure_ascii=False, indent=2))
        return 2

    with _sqlite_ro(sys_db) as c:
        src_sys_tabs = _sqlite_tablolar(c)
        src_sys = _sayimlar(c, src_sys_tabs)
    with _sqlite_ro(firma_db) as c:
        src_fr_tabs = _sqlite_tablolar(c)
        src_fr = _sayimlar(c, src_fr_tabs)

    eng_sys = _eng(SISTEM)
    eng_fr = _eng(FIRMA)
    dst_sys = _pg_sayimlar(eng_sys, list(src_sys.keys()))
    dst_fr = _pg_sayimlar(eng_fr, list(src_fr.keys()))

    fark_sys = _ozet_mutabakat(src_sys, dst_sys)
    fark_fr = _ozet_mutabakat(src_fr, dst_fr)
    rapor["sistem_tablo_sayisi"] = {"kaynak": len(src_sys), "hedef": len(dst_sys)}
    rapor["firma_tablo_sayisi"] = {"kaynak": len(src_fr), "hedef": len(dst_fr)}
    rapor["sistem_tablo_fark"] = fark_sys
    rapor["firma_tablo_fark"] = fark_fr
    rapor["firma_eslesen"] = (
        f"{sum(1 for t,a in src_fr.items() if dst_fr.get(t)==a)}/{len(src_fr)}"
    )

    dokuz = {}
    for t, exp in BEKLENEN_SAYIMLAR.items():
        dokuz[t] = {
            "beklenen": exp,
            "sqlite": src_fr.get(t),
            "pg": dst_fr.get(t),
            "ok": src_fr.get(t) == dst_fr.get(t) == exp,
        }
    rapor["dokuz_sayim"] = dokuz
    rapor["dokuz_sayim_ok"] = all(v["ok"] for v in dokuz.values())

    mali_src = _mali_ozet_sqlite(firma_db)
    mali_dst = _mali_ozet_pg(eng_fr)
    mali_fark = _mali_farklar(mali_src, mali_dst)
    rapor["mali_kaynak"] = mali_src
    rapor["mali_hedef"] = mali_dst
    rapor["mali_fark"] = mali_fark
    rapor["mali_ok"] = not mali_fark
    rapor["ornekler"] = _ornek_tr_karakter(eng_fr, firma_db)
    rapor["sequence"] = _sequence_kontrol(eng_fr)

    eng_sys.dispose()
    eng_fr.dispose()

    yol = ROOT / "kurulum" / "_kabul_mutabakat.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "dokuz_ok": rapor["dokuz_sayim_ok"],
        "mali_ok": rapor["mali_ok"],
        "firma_eslesen": rapor["firma_eslesen"],
        "sistem_fark_adet": len(fark_sys),
        "firma_fark_adet": len(fark_fr),
        "mali_fark": mali_fark,
        "ornek_tr": rapor["ornekler"].get("tr_eslesme"),
        "seq_ozet": {k: v.get("ok", v.get("hata")) for k, v in rapor["sequence"].items()},
    }, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0 if rapor["dokuz_sayim_ok"] and rapor["mali_ok"] and not fark_sys and not fark_fr else 3


if __name__ == "__main__":
    raise SystemExit(main())
