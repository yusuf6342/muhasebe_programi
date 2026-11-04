"""Açılış aşamalarını zaman damgasıyla kaydet (donma teşhisi)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

_t0 = time.perf_counter()
_satirlar: list[str] = []


def _log_yolu() -> Path:
    base = os.environ.get("MUHASEBE_DB_DIR") or os.environ.get("LOCALAPPDATA") or "."
    p = Path(base)
    if p.name.lower() == "data":
        return p.parent / "acil_asama_log.txt"
    return p / "CinMuhasebeTest" / "acil_asama_log.txt"


def asama(ad: str) -> None:
    dt = time.perf_counter() - _t0
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"{ts}  +{dt:7.3f}s  {ad}"
    _satirlar.append(line)
    try:
        print(f"[acil] {line}", flush=True)
    except Exception:
        pass
    try:
        yol = _log_yolu()
        yol.parent.mkdir(parents=True, exist_ok=True)
        with yol.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def oturum_baslat() -> None:
    """Her süreçte yeni bölüm."""
    global _t0, _satirlar
    _t0 = time.perf_counter()
    _satirlar = []
    try:
        yol = _log_yolu()
        yol.parent.mkdir(parents=True, exist_ok=True)
        with yol.open("a", encoding="utf-8") as f:
            f.write(
                f"\n===== {datetime.now().isoformat(timespec='seconds')} "
                f"pid={os.getpid()} =====\n"
            )
    except OSError:
        pass
    asama("oturum_baslat")
