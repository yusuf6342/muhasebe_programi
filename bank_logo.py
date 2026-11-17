"""Finans → Bankalar listesi: banka adı → logo dosyası eşlemesi."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import tkinter as tk

_log = logging.getLogger(__name__)

# Ekrandaki kart adı (normalize) → assets/bank_logos altındaki dosya
_ESLEME: tuple[tuple[str, str], ...] = (
    ("akbank", "akbank.png"),
    ("purlikit", "akbank.png"),
    ("denizbank", "denizbank.png"),
    ("enpara şirketim", "enpara_sirketim.png"),
    ("enpara sirketim", "enpara_sirketim.png"),
    ("enpara", "enpara.png"),
    ("halkbank", "halkbank.png"),
    ("kuveyt", "kuveytturk.png"),
    ("yapı kredi", "yapikredi.png"),
    ("yapi kredi", "yapikredi.png"),
    ("paytr", "yapikredi.png"),
    ("qnb", "qnb.png"),
    ("rönesans", "ronesans.png"),
    ("ronesans", "ronesans.png"),
    ("vakıfbank", "vakifbank.png"),
    ("vakifbank", "vakifbank.png"),
)

_image_cache: dict[str, tk.PhotoImage] = {}


def _kok() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def logo_dizini() -> Path:
    return _kok() / "assets" / "bank_logos"


def _normalize(ad: str) -> str:
    t = (ad or "").strip().casefold()
    t = t.replace("ı", "i").replace("İ", "i")
    t = re.sub(r"\s+", " ", t)
    return t


def logo_dosya_adi(banka_adi: str) -> str | None:
    """Kart adına göre logo dosyası; RSÇ World ve bilinmeyen → None."""
    n = _normalize(banka_adi)
    if not n or "rsç" in n or "rsc world" in n or n.startswith("rsc"):
        return None
    for anahtar, dosya in _ESLEME:
        if anahtar in n:
            return dosya
    return None


def logo_yolu(banka_adi: str) -> Path | None:
    dosya = logo_dosya_adi(banka_adi)
    if not dosya:
        return None
    yol = logo_dizini() / dosya
    return yol if yol.is_file() else None


def get_bank_logo(
    banka_adi: str,
    *,
    max_height: int = 20,
    max_width: int = 48,
) -> tk.PhotoImage | None:
    """Banka logosunu oran koruyarak yükler; yoksa None."""
    yol = logo_yolu(banka_adi)
    if yol is None:
        return None
    cache_key = f"{yol}|{max_width}x{max_height}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]
    try:
        from PIL import Image, ImageTk  # type: ignore

        with Image.open(yol) as im:
            im = im.convert("RGBA")
            w, h = im.size
            scale = 1.0
            if max_width and w > max_width:
                scale = min(scale, max_width / w)
            if max_height and h > max_height:
                scale = min(scale, max_height / h)
            if scale < 1.0:
                nw = max(1, int(round(w * scale)))
                nh = max(1, int(round(h * scale)))
                im = im.resize((nw, nh), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
        _image_cache[cache_key] = photo
        return photo
    except Exception as exc:  # noqa: BLE001
        _log.debug("Pillow banka logo: %s", exc)
    try:
        img = tk.PhotoImage(file=str(yol))
    except tk.TclError as exc:
        _log.warning("Banka logo yüklenemedi (%s): %s", yol, exc)
        return None
    _image_cache[cache_key] = img
    return img
