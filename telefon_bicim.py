"""Türkiye cep / sabit hat telefon gösterim şablonu: (532) 311 55 33.

Baştaki 0 yazılmaz / saklanmaz. En fazla 10 rakam.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Callable

AZAMI_RAKAM = 10
ORNEK = "(532) 311 55 33"


def telefon_rakamlari(metin: str | None, *, azami: int = AZAMI_RAKAM) -> str:
    """Yalnız rakamlar; baştaki sıfırlar atılır, uzunluk sınırlanır."""
    ham = re.sub(r"\D", "", metin or "")
    ham = ham.lstrip("0")
    return ham[:azami]


def telefon_bicimle(metin: str | None) -> str:
    """Görünüm: (532) 311 55 33 — eksik rakamda kısmi şablon."""
    d = telefon_rakamlari(metin)
    if not d:
        return ""
    alan = d[:3]
    if len(d) < 3:
        return f"({alan}"
    sonuc = f"({alan})"
    orta = d[3:6]
    if orta:
        sonuc += f" {orta}"
    parca = d[6:8]
    if parca:
        sonuc += f" {parca}"
    son = d[8:10]
    if son:
        sonuc += f" {son}"
    return sonuc


def telefon_kayit(metin: str | None) -> str | None:
    """Boşsa None; aksi halde biçimli metin (DB / form)."""
    bicimli = telefon_bicimle(metin)
    return bicimli or None


def telefon_entry_bagla(
    entry: ttk.Entry | tk.Entry,
    *,
    on_degisim: Callable[[], None] | None = None,
) -> None:
    """Yazarken şablona zorla; baştaki 0 ve harf engellenir."""

    def _uygula(_event=None):
        onceki = entry.get()
        yeni = telefon_bicimle(onceki)
        if yeni != onceki:
            try:
                imlec = entry.index(tk.INSERT)
            except tk.TclError:
                imlec = len(yeni)
            entry.delete(0, tk.END)
            entry.insert(0, yeni)
            # Silme sırasında imleci korumaya çalış; eklemede sona al
            try:
                if _event is not None and getattr(_event, "keysym", "") in (
                    "BackSpace",
                    "Delete",
                ):
                    entry.icursor(min(imlec, len(yeni)))
                else:
                    entry.icursor(tk.END)
            except tk.TclError:
                pass
        if on_degisim:
            on_degisim()

    def _tus(event):
        if event.state & 0x4:  # Ctrl
            return None
        if event.keysym in (
            "BackSpace",
            "Delete",
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Tab",
            "Return",
            "KP_Enter",
            "Escape",
        ):
            return None
        ch = event.char or ""
        if not ch:
            return None
        if not ch.isdigit():
            return "break"
        # Boş alanda baştaki 0 yazılamaz
        if ch == "0" and not telefon_rakamlari(entry.get()):
            return "break"
        # Azami doluysa ek rakam yok (seçim yoksa)
        try:
            if entry.selection_present():
                return None
        except tk.TclError:
            pass
        if len(telefon_rakamlari(entry.get())) >= AZAMI_RAKAM:
            return "break"
        return None

    entry.bind("<KeyPress>", _tus, add="+")
    entry.bind("<KeyRelease>", _uygula, add="+")
    entry.bind("<FocusOut>", _uygula, add="+")
    entry.bind("<<Paste>>", lambda _e: entry.after_idle(_uygula), add="+")
