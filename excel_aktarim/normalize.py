"""Excel başlık / değer normalizasyonu."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def baslik_normalize(baslik: str) -> str:
    metin = unicodedata.normalize("NFKD", str(baslik or "").strip())
    metin = "".join(c for c in metin if not unicodedata.combining(c))
    metin = metin.casefold().replace("ı", "i")
    return re.sub(r"[^a-z0-9]+", "", metin)


def temiz(deger: Any) -> str:
    if deger is None:
        return ""
    if isinstance(deger, datetime):
        return deger.strftime("%d.%m.%Y")
    if isinstance(deger, date):
        return deger.strftime("%d.%m.%Y")
    if isinstance(deger, float) and deger == int(deger):
        return str(int(deger))
    return str(deger).strip()


def decimal_parse(deger: Any, *, alan: str = "Tutar") -> Decimal | None:
    metin = temiz(deger).replace(" ", "").replace("%", "")
    if not metin:
        return None
    if "," in metin and "." in metin:
        if metin.rfind(",") > metin.rfind("."):
            metin = metin.replace(".", "").replace(",", ".")
        else:
            metin = metin.replace(",", "")
    else:
        metin = metin.replace(",", ".")
    try:
        return Decimal(metin)
    except InvalidOperation as exc:
        raise ValueError(f"{alan} sayısal değil: {deger!r}") from exc


def tarih_parse(deger: Any) -> date | None:
    if deger is None or deger == "":
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    metin = temiz(deger)
    if not metin:
        return None
    for fmt, n in (
        ("%d.%m.%Y %H:%M:%S", 19),
        ("%d.%m.%Y", 10),
        ("%Y-%m-%d", 10),
        ("%d/%m/%Y", 10),
        ("%Y/%m/%d", 10),
    ):
        try:
            return datetime.strptime(metin[:n], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih okunamadı: {deger!r}")
