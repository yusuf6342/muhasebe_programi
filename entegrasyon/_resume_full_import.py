# -*- coding: utf-8 -*-
"""UTF-8 progress log ile kalan EvoBulut aktarımını sürdür."""
from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "entegrasyon" / "_full_import_progress.txt"
PID = ROOT / "entegrasyon" / "_full_import.pid"
sys.path.insert(0, str(ROOT))


def _pid_temizle() -> None:
    try:
        if PID.is_file():
            PID.unlink()
    except OSError:
        pass


PID.write_text(f"{os.getpid()}\n", encoding="utf-8")
atexit.register(_pid_temizle)

log_f = open(LOG, "a", encoding="utf-8", errors="replace", buffering=1)
sys.stdout = log_f
sys.stderr = log_f
print("\n=== YENİDEN BAŞLATILDI ===", flush=True)

sys.argv = ["entegrasyon.import_all_remaining_cli", "--api"]
from entegrasyon.import_all_remaining_cli import main

try:
    raise SystemExit(main())
finally:
    _pid_temizle()
