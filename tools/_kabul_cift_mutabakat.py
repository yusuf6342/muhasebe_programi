"""Kabul TEMPLATE kopyası + restore hedefini kaynak deneme / dump ile karşılaştır."""
from __future__ import annotations

import json
import os
import socket
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
    _mali_farklar,
    _mali_ozet_pg,
    _ozet_mutabakat,
    _pg_sayimlar,
)

HOST = (os.environ.get("KABUL_MUTABAKAT_HOST") or "192.168.1.114").strip()
PORT = int(os.environ.get("KABUL_MUTABAKAT_PORT") or "5432")
USER = "cin_app"
# Yerel 127.0.0.1'de sunucu SSL zorunlu olmayabilir; LAN'da require.
SSL = (os.environ.get("KABUL_MUTABAKAT_SSLMODE") or (
    "prefer" if HOST in ("127.0.0.1", "localhost") else "require"
)).strip()

KAYNAK_SYS = "cin_sistem_deneme"
KAYNAK_FR = "cin_firma_deneme"
KABUL_SYS = "cin_sistem_kabul_20261105"
KABUL_FR = "cin_firma_kabul_20261105"
RESTORE_SYS = "cin_sistem_restore_20261105"
RESTORE_FR = "cin_firma_restore_20261105"


def eng(db: str):
    pwd = quote_plus(postgres_parola_al())
    url = f"postgresql+psycopg://{USER}:{pwd}@{HOST}:{PORT}/{db}?sslmode={SSL}"
    return create_engine(url, connect_args={"connect_timeout": 12})


def tablo_listesi(e) -> list[str]:
    with e.connect() as c:
        rows = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "ORDER BY 1"
            )
        ).fetchall()
    return [r[0] for r in rows]


def companies(e) -> list[dict]:
    with e.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT id, firma_kodu, db_path, aktif FROM companies ORDER BY id"
                )
            ).mappings()
        ]


def dokuz(e) -> dict:
    out = {}
    with e.connect() as c:
        for t, exp in BEKLENEN_SAYIMLAR.items():
            n = int(c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0)
            out[t] = {"n": n, "expected": exp, "ok": n == exp}
    return out


def karsilastir(label: str, src_fr, dst_fr, src_sys, dst_sys) -> dict:
    tabs = tablo_listesi(src_fr)
    src_counts = _pg_sayimlar(src_fr, tabs)
    dst_counts = _pg_sayimlar(dst_fr, tabs)
    fark = _ozet_mutabakat(src_counts, dst_counts)
    mali_src = _mali_ozet_pg(src_fr)
    mali_dst = _mali_ozet_pg(dst_fr)
    mali_fark = _mali_farklar(mali_src, mali_dst)
    stabs = tablo_listesi(src_sys)
    sf = _ozet_mutabakat(_pg_sayimlar(src_sys, stabs), _pg_sayimlar(dst_sys, stabs))
    return {
        "etiket": label,
        "firma_tablo": len(tabs),
        "firma_eslesen": f"{sum(1 for t,a in src_counts.items() if dst_counts.get(t)==a)}/{len(src_counts)}",
        "firma_fark": fark[:20],
        "firma_fark_adet": len(fark),
        "sistem_fark_adet": len(sf),
        "sistem_fark": sf[:10],
        "mali_kaynak": mali_src,
        "mali_hedef": mali_dst,
        "mali_fark": mali_fark,
        "dokuz": dokuz(dst_fr),
        "dokuz_ok": all(v["ok"] for v in dokuz(dst_fr).values()),
        "companies": companies(dst_sys),
        "ray_ok": any(
            c.get("firma_kodu") == "RAY001"
            and c.get("aktif")
            and str(c.get("db_path", "")).startswith("pg:")
            for c in companies(dst_sys)
        ),
    }


def main() -> int:
    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "host": f"{HOST}:{PORT}",
        "sslmode": SSL,
    }
    engines = {}
    try:
        for name in (
            KAYNAK_SYS,
            KAYNAK_FR,
            KABUL_SYS,
            KABUL_FR,
            RESTORE_SYS,
            RESTORE_FR,
        ):
            engines[name] = eng(name)
            with engines[name].connect() as c:
                c.execute(text("SELECT 1"))
            rapor.setdefault("baglanti", {})[name] = True
    except Exception as exc:
        rapor["baglanti_hata"] = str(exc)[:400]
        yol = ROOT / "kurulum" / "_kabul_cift_mutabakat.json"
        yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rapor, ensure_ascii=False, indent=2))
        return 2

    rapor["kabul_vs_deneme"] = karsilastir(
        "kabul<-deneme",
        engines[KAYNAK_FR],
        engines[KABUL_FR],
        engines[KAYNAK_SYS],
        engines[KABUL_SYS],
    )
    # Restore: dump deneme anından; deneme ile karşılaştır (yazma sonrası fark olabilir)
    rapor["restore_vs_deneme"] = karsilastir(
        "restore<-deneme",
        engines[KAYNAK_FR],
        engines[RESTORE_FR],
        engines[KAYNAK_SYS],
        engines[RESTORE_SYS],
    )
    # Kabul vs restore firma (ikisi de deneme türevi)
    rapor["kabul_vs_restore_firma_fark_adet"] = len(
        _ozet_mutabakat(
            _pg_sayimlar(engines[KABUL_FR], tablo_listesi(engines[KABUL_FR])),
            _pg_sayimlar(engines[RESTORE_FR], tablo_listesi(engines[RESTORE_FR])),
        )
    )

    # RAY eşlemeleri
    rapor["ray_esleme"] = {
        "kabul": next(
            (c for c in rapor["kabul_vs_deneme"]["companies"] if c["firma_kodu"] == "RAY001"),
            None,
        ),
        "restore": next(
            (c for c in rapor["restore_vs_deneme"]["companies"] if c["firma_kodu"] == "RAY001"),
            None,
        ),
        "kabul_beklenen": f"pg:{KABUL_FR}",
        "restore_beklenen": f"pg:{RESTORE_FR}",
    }
    k = rapor["ray_esleme"]["kabul"]
    r = rapor["ray_esleme"]["restore"]
    rapor["ray_esleme_ok"] = (
        k
        and r
        and k.get("db_path") == f"pg:{KABUL_FR}"
        and r.get("db_path") == f"pg:{RESTORE_FR}"
        and k.get("aktif")
        and r.get("aktif")
    )

    for e in engines.values():
        e.dispose()

    kabul_ok = (
        rapor["kabul_vs_deneme"]["firma_fark_adet"] == 0
        and rapor["kabul_vs_deneme"]["sistem_fark_adet"] == 0
        and not rapor["kabul_vs_deneme"]["mali_fark"]
        and rapor["kabul_vs_deneme"]["dokuz_ok"]
        and rapor["ray_esleme_ok"]
    )
    # Restore: mali fark varsa başarısız; yalnız dump-sonrası test tabloları farkı kabul edilir
    rf = rapor["restore_vs_deneme"]
    restore_farklar = list(rf.get("firma_fark") or [])
    yalniz_test_farki = all(
        s.startswith("kabul_") and "hedef=-1" in s for s in restore_farklar
    ) if restore_farklar else True
    restore_mali_ok = not rf.get("mali_fark")
    restore_ok = (
        restore_mali_ok
        and rf.get("dokuz_ok")
        and rf.get("sistem_fark_adet", 0) == 0
        and (
            rf.get("firma_fark_adet", 0) == 0
            or yalniz_test_farki
        )
        and rapor["ray_esleme"]["restore"]
        and rapor["ray_esleme"]["restore"].get("db_path") == f"pg:{RESTORE_FR}"
    )
    rapor["kabul_mutabakat_ok"] = kabul_ok
    rapor["restore_mutabakat_ok"] = restore_ok
    rapor["restore_mutabakat_ozet"] = {
        "firma_fark_adet": rf["firma_fark_adet"],
        "sistem_fark_adet": rf["sistem_fark_adet"],
        "mali_fark": rf["mali_fark"],
        "dokuz_ok": rf["dokuz_ok"],
        "yalniz_test_tablosu_farki": yalniz_test_farki,
        "restore_ok": restore_ok,
        "not": (
            "Dump sonrası deneme'ye eklenen kabul_* test tabloları restore'da yok; "
            "iş verisi/mali özet eşleşiyorsa restore başarılı sayılır. "
            "Mali fark varsa exit 0 olsa bile restore_ok=false."
        ),
    }

    yol = ROOT / "kurulum" / "_kabul_cift_mutabakat.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "kabul_ok": kabul_ok,
                "kabul_firma_eslesen": rapor["kabul_vs_deneme"]["firma_eslesen"],
                "kabul_mali_fark": rapor["kabul_vs_deneme"]["mali_fark"],
                "restore_ok": restore_ok,
                "restore_firma_fark": rf["firma_fark_adet"],
                "restore_mali_fark": rf["mali_fark"],
                "ray_esleme_ok": rapor["ray_esleme_ok"],
                "ray": rapor["ray_esleme"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    print("YAZILDI:", yol)
    # Kabul zorunlu; restore mali/iş farkı varsa 3
    if not kabul_ok or not rapor["ray_esleme_ok"]:
        return 3
    if not restore_ok:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
