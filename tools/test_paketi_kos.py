"""Test paketini dosya dosya, paralel ve izole veritabanıyla çalıştırır.

Her test dosyası ayrı süreçte, TEMP altında yeni bir MUHASEBE_DB_DIR ile koşar; süre sınırını
aşan dosya sonlandırılır. ``--hash`` ile depo .py dosyalarının SHA256 özeti yazılır.

Kullanım:
    python tools/test_paketi_kos.py --log C:/.../suite.log [--paralel 4] [--sure 400] [dosya ...]
    python tools/test_paketi_kos.py --hash C:/.../hash.txt
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
HARIC = {".venv", "build", "dist", "__pycache__", ".git"}


def hash_yaz(hedef: Path) -> None:
    satirlar = []
    for p in sorted(KOK.rglob("*.py")):
        if HARIC & set(p.relative_to(KOK).parts):
            continue
        satirlar.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(KOK).as_posix()}")
    hedef.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    print(f"{len(satirlar)} dosya -> {hedef}")


def kos(dosya: Path, sure: int) -> tuple[str, str, float, str]:
    db_dir = Path(tempfile.gettempdir()) / f"cin_suite_{uuid.uuid4().hex}"
    db_dir.mkdir(parents=True)
    env = dict(os.environ, MUHASEBE_DB_DIR=str(db_dir), PYTHONIOENCODING="utf-8")
    bas = time.perf_counter()
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(dosya)],
            cwd=KOK, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=sure,
        )
        durum = "OK" if p.returncode == 0 else ("BOS" if p.returncode == 5 else "FAIL")
        cikti = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        durum = "TIMEOUT"
        cikti = str(e.stdout or "")[-4000:]
    ozet = next((s for s in reversed(cikti.strip().splitlines()) if " in " in s), "")
    return dosya.name, durum, time.perf_counter() - bas, cikti if durum not in ("OK", "BOS") else ozet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log")
    ap.add_argument("--hash")
    ap.add_argument("--paralel", type=int, default=4)
    ap.add_argument("--sure", type=int, default=400)
    ap.add_argument("dosyalar", nargs="*")
    a = ap.parse_args()
    if a.hash:
        hash_yaz(Path(a.hash))
        return 0
    dosyalar = [KOK / d for d in a.dosyalar] if a.dosyalar else sorted(
        p for p in (KOK / "tests").glob("test_*.py"))
    dosyalar = [d for d in dosyalar if not d.name.startswith("_probe_")]
    log = open(a.log, "w", encoding="utf-8") if a.log else sys.stdout
    bas = time.perf_counter()
    print(f"Başlangıç {time.strftime('%H:%M:%S')} — {len(dosyalar)} dosya, paralel {a.paralel}", file=log,
          flush=True)
    sonuclar = []
    with ThreadPoolExecutor(a.paralel) as havuz:
        for ad, durum, sn, ozet in havuz.map(lambda d: kos(d, a.sure), dosyalar):
            sonuclar.append((ad, durum))
            print(f"[{durum}] {ad} {sn:.1f}s :: {ozet if durum in ('OK', 'BOS') else ''}", file=log, flush=True)
            if durum not in ("OK", "BOS"):
                print(ozet[-6000:], file=log, flush=True)
    kotu = [s for s in sonuclar if s[1] not in ("OK", "BOS")]
    print(f"Bitiş {time.strftime('%H:%M:%S')} — {time.perf_counter() - bas:.0f}s — toplam {len(sonuclar)}, "
          f"başarısız {len(kotu)}: {kotu}", file=log, flush=True)
    return 1 if kotu else 0


if __name__ == "__main__":
    raise SystemExit(main())
