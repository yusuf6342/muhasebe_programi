"""DNM D1 ortak yardımcılar — yazım, SHA, tarih/para parse."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
KAYNAK = CALISMA / "kaynak"
SURUMLER = CALISMA / "surumler"
ESLEME = CALISMA / "esleme"
PLAN = CALISMA / "plan"

_TARIH = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")


def dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def dec_opt(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def parse_tarih(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19] if " " in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    m = _TARIH.search(s)
    if not m:
        return None
    g, a, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, a, g)
    except ValueError:
        return None


def yaz_json(yol: Path, veri: Any) -> str:
    yol.parent.mkdir(parents=True, exist_ok=True)
    ham = json.dumps(veri, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(yol.suffix + ".sha256").write_text(
        f"{sha}  {yol.name}\n", encoding="ascii"
    )
    return sha


def yaz_kaynak(ad: str, veri: Any) -> tuple[Path, str]:
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    sha = yaz_json(yol, veri)
    print("YAZILDI", yol.name, "sha", sha[:16], flush=True)
    return yol, sha


def sha256_dosya(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def oturum_gecersiz_mi(y: dict) -> bool:
    if y.get("status") == "OK":
        return False
    veri = y.get("veri")
    metin = json.dumps(veri, ensure_ascii=False) if veri is not None else ""
    return "Geçersiz oturum" in metin or "Token" in metin or "Login" in metin
