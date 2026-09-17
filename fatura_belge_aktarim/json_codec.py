"""Muhasebe JSON serileştirme — Decimal float'a çevrilmez.

Parasal değerler JSON'da noktalı metin olarak saklanır (örn. \"15000.10\").
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import UUID


class AccountingJSONEncoder(json.JSONEncoder):
    """Decimal → format(obj, 'f'); tarih/UUID/Enum → metin. float kullanılmaz."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return format(obj, "f")
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def make_json_safe(value: Any) -> Any:
    """İç içe yapıyı JSON'a uygun hale getirir; Decimal float olmaz."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dumps_accounting(data: Any, *, ensure_ascii: bool = False, **kwargs: Any) -> str:
    """Fatura aktarım / denetim JSON çıktısı — tek merkezi yöntem."""
    return json.dumps(
        data,
        cls=AccountingJSONEncoder,
        ensure_ascii=ensure_ascii,
        **kwargs,
    )


def to_decimal(value: Any, default: str = "0") -> Decimal:
    """JSON metninden veya ham değerden güvenli Decimal."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        metin = str(value).strip().replace(" ", "")
        if "," in metin and "." in metin:
            if metin.rfind(",") > metin.rfind("."):
                metin = metin.replace(".", "").replace(",", ".")
            else:
                metin = metin.replace(",", "")
        else:
            metin = metin.replace(",", ".")
        return Decimal(metin)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
