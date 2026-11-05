"""04.11 aktarım yedeği sonrası SQLite kaynakta yeni işlem var mı?"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KAYNAK = Path(
    r"C:\Users\cigde\AppData\Local\CinMuhasebeAktarim"
    r"\Ray_Aktarim_2026-11-04_194017\veri_yedek\muhasebe.db"
)
# Günlük SQLite (varsa)
GUNLUK_ADAYLAR = [
    Path(r"C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi\data\muhasebe.db"),
    Path(os_local := __import__("os").environ.get("LOCALAPPDATA", ""))
    / "MuhasebeProgrami"
    / "data"
    / "muhasebe.db",
]


def _max_tarih(con: sqlite3.Connection, sql: str):
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def _ozet(db: Path) -> dict:
    if not db.is_file():
        return {"yol": str(db), "var": False}
    con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return {
            "yol": str(db),
            "var": True,
            "mtime": datetime.fromtimestamp(db.stat().st_mtime).isoformat(timespec="seconds"),
            "boyut": db.stat().st_size,
            "satis_max_tarih": _max_tarih(con, "SELECT MAX(fatura_tarihi) FROM satis_faturalari"),
            "alis_max_tarih": _max_tarih(con, "SELECT MAX(fatura_tarihi) FROM alis_faturalari"),
            "stok_hareket_max": _max_tarih(con, "SELECT MAX(tarih) FROM stok_hareketleri"),
            "finans_max": _max_tarih(con, "SELECT MAX(tarih) FROM finans_hareketleri"),
            "satis_sayim": con.execute("SELECT count(*) FROM satis_faturalari").fetchone()[0],
            "stok_hareket_sayim": con.execute("SELECT count(*) FROM stok_hareketleri").fetchone()[0],
        }
    finally:
        con.close()


def main() -> int:
    rapor = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "aktarim_yedek": _ozet(KAYNAK),
        "gunluk_adaylar": [_ozet(p) for p in GUNLUK_ADAYLAR],
        "not": "Canlı geçişte 04.11 yedeğini esas alma; güncel günlük SQLite ile yeni dump+aktarım gerekir.",
    }
    yol = ROOT / "kurulum" / "_kabul_canli_kaynak_fark.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(rapor, ensure_ascii=False, indent=2, default=str))
    print("YAZILDI:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
