"""Firma seçim ekranı — renkler, font ve saf yardımcı fonksiyonlar (Tkinter)."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path
from typing import Any, Sequence

# Ray Mobilya tarzı kurumsal palet (sarı yalnızca vurgu)
COLOR_NAVY = "#102A43"
COLOR_NAVY_DEEP = "#081B2C"
COLOR_NAVY_MID = "#172B4D"
COLOR_YELLOW = "#F4C542"
COLOR_YELLOW_SOFT = "#FFE89A"
COLOR_WHITE = "#FFFFFF"
COLOR_BG = "#F3F6F9"
COLOR_MUTED = "#627D98"
COLOR_OK = "#1F9D74"
COLOR_DANGER = "#D64545"

FONT_CANDIDATES = ("Segoe UI", "Aptos", "Calibri", "Arial")

_TR_MAP = str.maketrans(
    {
        "I": "ı",
        "İ": "i",
        "Ş": "ş",
        "Ğ": "ğ",
        "Ü": "ü",
        "Ö": "ö",
        "Ç": "ç",
    }
)


def tr_normalize(metin: str | None) -> str:
    """Türkçe-duyarlı küçük harf (casefold) — arama için."""
    if not metin:
        return ""
    return str(metin).translate(_TR_MAP).casefold()


def resolve_ui_font(root: tk.Misc | None = None) -> str:
    """Sistemde bulunan ilk UI fontunu döndürür."""
    families: set[str] = set()
    try:
        probe = root if root is not None else tk._default_root  # type: ignore[attr-defined]
        if probe is not None:
            families = {f.lower() for f in probe.tk.call("font", "families")}
    except Exception:
        families = set()
    for name in FONT_CANDIDATES:
        if not families or name.lower() in families:
            return name
    return "Arial"


def ui_font(size: int, weight: str = "normal", root: tk.Misc | None = None) -> tuple:
    family = resolve_ui_font(root)
    if weight == "bold":
        return (family, size, "bold")
    return (family, size)


def firma_arama_eslesir(firma: Any, sorgu: str) -> bool:
    """Unvan, kod, vergi no — TR normalize, case-insensitive."""
    q = tr_normalize(sorgu).strip()
    if not q:
        return True
    alanlar = (
        getattr(firma, "unvan", None),
        getattr(firma, "firma_kodu", None),
        getattr(firma, "vergi_no", None),
        getattr(firma, "kisa_ad", None),
    )
    haystack = " ".join(tr_normalize(a) for a in alanlar if a)
    return q in haystack


def firmalari_filtrele(firmalar: Sequence[Any], sorgu: str) -> list[Any]:
    return [f for f in firmalar if firma_arama_eslesir(f, sorgu)]


def varsayilan_secim_id(
    firmalar: Sequence[Any],
    *,
    son_id: str | int | None = None,
    varsayilan_id: int | None = None,
) -> int | None:
    """Son kullanılan (öncelikli) veya kullanıcı varsayılanı; yoksa ilk kayıt."""
    if not firmalar:
        return None
    ids = {int(getattr(f, "id")) for f in firmalar}
    if son_id is not None and str(son_id).strip():
        try:
            sid = int(son_id)
            if sid in ids:
                return sid
        except (TypeError, ValueError):
            pass
    if varsayilan_id is not None and int(varsayilan_id) in ids:
        return int(varsayilan_id)
    return int(getattr(firmalar[0], "id"))


def kart_sutun_sayisi(firma_sayisi: int, genislik_px: int) -> int:
    """Az firmada dengeli; çok firmada 2–3 sütun. 1366 genişlikte güvenli."""
    if firma_sayisi <= 0:
        return 1
    if genislik_px < 700 or firma_sayisi == 1:
        return 1
    if genislik_px < 1000 or firma_sayisi == 2:
        return min(2, firma_sayisi)
    if firma_sayisi <= 3:
        return firma_sayisi
    return 3


def konum_metni(
    *,
    il: str | None = None,
    ilce: str | None = None,
    adres: str | None = None,
) -> str:
    parcalar = [p for p in (ilce, il) if (p or "").strip()]
    if parcalar:
        return " / ".join(parcalar)
    if adres and str(adres).strip():
        metin = str(adres).strip()
        return metin if len(metin) <= 60 else metin[:57] + "…"
    return ""


def aktif_donem_oku(db_path: str | None) -> str | None:
    """Firma DB'sinden aktif/varsayılan dönem adı — salt okunur, oturumu bozmaz."""
    if not db_path:
        return None
    yol = Path(db_path)
    if not yol.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{yol.resolve().as_posix()}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT donem_adi FROM donemler "
                "WHERE COALESCE(aktif, 0) = 1 OR COALESCE(varsayilan, 0) = 1 "
                "ORDER BY COALESCE(aktif, 0) DESC, COALESCE(varsayilan, 0) DESC "
                "LIMIT 1"
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        finally:
            con.close()
    except Exception:
        return None
    return None
