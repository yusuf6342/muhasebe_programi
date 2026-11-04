"""SQLite'a özgü kullanımların envanteri — PostgreSQL geçiş kontrol listesi."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "sqlite_master": re.compile(r"sqlite_master"),
    "PRAGMA": re.compile(r"\bPRAGMA\b"),
    "sqlite3_module": re.compile(r"\bimport sqlite3\b|\bsqlite3\."),
    "sqlite_where": re.compile(r"sqlite_where\s*="),
    "tr_norm_sqlite_funcs": re.compile(r"from database\.sqlite_funcs|sqlite_funcs"),
    "sqlite_url": re.compile(r"sqlite:///"),
}

SKIP = {".venv", "dist", "build", "__pycache__", "tmp_screens", "Banka_Guncelleme_Yedek"}


def main() -> int:
    counts: Counter[str] = Counter()
    hits: list[tuple[str, str, int, str]] = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, rx in PATTERNS.items():
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    counts[name] += 1
                    hits.append((name, str(path.relative_to(ROOT)), i, line.strip()[:120]))
    print("=== SQLite özgü kullanım sayıları ===")
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    print(f"\nToplam eşleşme: {sum(counts.values())}")
    print("\n=== Örnek (ilk 40) ===")
    for name, rel, ln, line in hits[:40]:
        print(f"[{name}] {rel}:{ln}: {line}")
    out = ROOT / "kurulum" / "SQLITE_PG_ENVANTER.txt"
    lines = [f"{n}\t{p}:{ln}\t{t}" for n, p, ln, t in hits]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nYazıldı: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
