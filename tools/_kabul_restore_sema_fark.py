"""Restore vs deneme/kabul tablo kümesi farkı (kaynak dump sonrası değişim)."""
from __future__ import annotations

import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
DBS = {
    "deneme": "cin_firma_deneme",
    "kabul": "cin_firma_kabul_20261105",
    "restore": "cin_firma_restore_20261105",
}


def tabs(db: str) -> set[str]:
    pwd = quote_plus(postgres_parola_al())
    e = create_engine(
        f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/{db}?sslmode=require",
        connect_args={"connect_timeout": 12},
    )
    with e.connect() as c:
        rows = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).fetchall()
    e.dispose()
    return {r[0] for r in rows}


def count_in(db: str, table: str) -> int | None:
    pwd = quote_plus(postgres_parola_al())
    e = create_engine(
        f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/{db}?sslmode=require",
        connect_args={"connect_timeout": 12},
    )
    try:
        with e.connect() as c:
            return int(c.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0)
    except Exception:
        return None
    finally:
        e.dispose()


def main() -> int:
    sets = {k: tabs(v) for k, v in DBS.items()}
    den, kab, res = sets["deneme"], sets["kabul"], sets["restore"]
    missing_res = sorted(den - res)
    only_res = sorted(res - den)
    kabul_vs_res = sorted(kab - res)
    # -1 tipi: tablo yok; sayı farkı: tablo var ama satır farklı
    sayim_fark = []
    ortak = sorted(den & res)
    for t in ortak:
        a, b = count_in(DBS["deneme"], t), count_in(DBS["restore"], t)
        if a != b:
            sayim_fark.append({"tablo": t, "deneme": a, "restore": b})
    test_tables = [t for t in missing_res if t.startswith("kabul_")]
    rapor = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "adet": {k: len(v) for k, v in sets.items()},
        "restore_eksik_tablo_adet": len(missing_res),
        "restore_eksik_ornek": missing_res[:40],
        "restore_fazla_tablo": only_res[:20],
        "kabul_restore_eksik": kabul_vs_res[:20],
        "kabul_restore_eksik_adet": len(kabul_vs_res),
        "ortak_satir_fark_adet": len(sayim_fark),
        "ortak_satir_fark_ornek": sayim_fark[:30],
        "test_tablolari_dump_sonrasi": test_tables,
        "yorum": (
            "Restore dump anındaki şema/veri; deneme sonra değiştiyse eksik tablo veya satır farkı beklenir. "
            "Mali dokuzlu eşleşse bile şema eksikliği restore kabulü için KALDI sayılır."
            if missing_res
            else "Tablo kümeleri eşleşiyor."
        ),
    }
    yol = ROOT / "kurulum" / "_kabul_restore_sema_fark.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rapor, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    # Restore şema eksikse başarısız çıkış (mali eşleşse bile)
    return 0 if not missing_res and not sayim_fark else 4


if __name__ == "__main__":
    raise SystemExit(main())
