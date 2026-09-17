"""Fatura belge aktarım — yardımcılar."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ALLOWED_EXT = {".xml", ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".zip"}
MAX_BYTES = 25 * 1024 * 1024


def safe_filename(ad: str) -> str:
    ad = Path(ad).name
    ad = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", ad)
    ad = ad.strip(" .") or "belge"
    return ad[:180]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_vkn(deger: Any) -> str:
    s = re.sub(r"\D", "", str(deger or ""))
    return s


def normalize_text(deger: Any) -> str:
    metin = unicodedata.normalize("NFKD", str(deger or "").strip())
    metin = "".join(c for c in metin if not unicodedata.combining(c))
    metin = metin.casefold().replace("ı", "i")
    return re.sub(r"\s+", " ", metin).strip()


def normalize_header(value: Any) -> str:
    """Tablo başlığı karşılaştırması için normalize (Türkçe karakter korunur)."""
    value = str(value or "").replace("\n", " ").replace("\r", " ").strip().casefold()
    value = " ".join(value.split())
    value = (
        value.replace("%", "")
        .replace(":", " ")
        .replace(".", " ")
        .replace("/", " ")
        .replace("-", " ")
        .replace("(", " ")
        .replace(")", " ")
    )
    return " ".join(value.split())


def header_key_plain(value: Any) -> str:
    """Alternatif eşleşme: aksanları sadeleştirilmiş başlık."""
    return normalize_text(normalize_header(value))


def parse_decimal_tr(value: Any) -> Decimal | None:
    """Türkçe/İngilizce para ve oran biçimlerini Decimal'e çevir (float yok)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    text = (
        text.replace("TL", "")
        .replace("TRY", "")
        .replace("₺", "")
        .replace("%", "")
        .replace(" ", "")
    )
    # 120m, 110TL (TL zaten silindi), 13.200,00TL
    text = re.sub(r"[A-Za-zÇĞİÖŞÜçğıöşü]+$", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def decimal_tr(deger: Any) -> Decimal | None:
    """Geriye uyumlu alias — parse_decimal_tr kullanır."""
    return parse_decimal_tr(deger)


def tarih_tr(deger: Any) -> date | None:
    if deger is None or deger == "":
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    metin = str(deger).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10), ("%d/%m/%Y", 10)):
        try:
            return datetime.strptime(metin[:n], fmt).date()
        except ValueError:
            continue
    return None


def birim_normalize(birim: str | None) -> str:
    b = normalize_text(birim or "")
    es = {
        "ad": "ADET",
        "adet": "ADET",
        "c62": "ADET",
        "pcs": "ADET",
        "pc": "ADET",
        "ea": "ADET",
        "kg": "KG",
        "kilo": "KG",
        "gr": "GR",
        "g": "GR",
        "m": "M",
        "mt": "M",
        "mtr": "M",
        "koli": "KOLI",
        "paket": "PAKET",
        "pk": "PAKET",
    }
    return es.get(b, (birim or "ADET").upper())
