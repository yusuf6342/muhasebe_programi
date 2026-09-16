"""Müşteri / Tedarikçi Cari Hesap Kartı — kurumsal renk, tipografi ve bileşenler.

İş mantığı yok; yalnızca görsel sabitler ve tekrar kullanılabilir chrome.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

# Kullanıcı paleti
LACIVERT = "#0B2A4A"
LACIVERT_ORTA = "#163E66"
SARI = "#F5B700"
ACIK_BG = "#F4F6F8"
BEYAZ = "#FFFFFF"
METIN = "#1F2937"
IKINCIL = "#667085"
BASARI = "#15803D"
UYARI = "#DC2626"
DIKKAT = "#D97706"
CIZGI = "#D7DEE7"

LACIVERT_HOVER = "#1A4068"
SARI_HOVER = "#FFD54F"
KART_GOEGE = "#E8EDF2"
SECIM_SARI = "#FFE082"
STRIPE = "#F0F3F7"

FONT_ADAYLARI = ("Segoe UI", "Aptos", "Calibri", "Arial")
_font_aile: str | None = None


def resolve_ui_font(root: tk.Misc | None = None) -> str:
    global _font_aile
    if _font_aile:
        return _font_aile
    families: set[str] = set()
    try:
        probe = root if root is not None else tk._default_root  # type: ignore[attr-defined]
        if probe is not None:
            families = {str(f).lower() for f in probe.tk.call("font", "families")}
    except Exception:
        families = set()
    for name in FONT_ADAYLARI:
        if not families or name.lower() in families:
            _font_aile = name
            return name
    _font_aile = "Arial"
    return _font_aile


def font(size: int, weight: str = "normal", root: tk.Misc | None = None) -> tuple:
    aile = resolve_ui_font(root)
    if weight in ("bold", "semibold"):
        return (aile, size, "bold")
    return (aile, size)


def stil_uygula(stil: ttk.Style | None = None, root: tk.Misc | None = None) -> ttk.Style:
    stil = stil or ttk.Style(root)
    try:
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
        elif "vista" in stil.theme_names():
            stil.theme_use("vista")
    except tk.TclError:
        pass

    f_ui = font(10, root=root)
    f_bold = font(10, "bold", root=root)
    f_baslik = font(14, "bold", root=root)
    f_alt = font(9, root=root)
    f_kucuk = font(8, root=root)
    f_btn = font(10, "bold", root=root)

    stil.configure("CariKart.TFrame", background=ACIK_BG)
    stil.configure("CariKartPanel.TFrame", background=BEYAZ)
    stil.configure("CariKart.TLabel", background=ACIK_BG, foreground=METIN, font=f_ui)
    stil.configure("CariKartMuted.TLabel", background=ACIK_BG, foreground=IKINCIL, font=f_alt)
    stil.configure("CariKartPanel.TLabel", background=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("CariKartPanelMuted.TLabel", background=BEYAZ, foreground=IKINCIL, font=f_alt)
    stil.configure("CariKartBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_baslik)
    stil.configure("CariKartBolum.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_bold)
    stil.configure("CariKartKucuk.TLabel", background=BEYAZ, foreground=IKINCIL, font=f_kucuk)

    stil.configure(
        "CariKart.TLabelframe",
        background=BEYAZ,
        foreground=LACIVERT,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "CariKart.TLabelframe.Label",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_bold,
    )
    stil.configure("CariKart.TEntry", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("CariKart.TCombobox", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("CariKart.TNotebook", background=BEYAZ)
    stil.configure("CariKart.TNotebook.Tab", font=f_alt, padding=(10, 4))

    stil.configure(
        "CariKart.Treeview",
        font=f_alt,
        rowheight=26,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=0,
    )
    stil.configure(
        "CariKart.Treeview.Heading",
        font=f_bold,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        padding=(6, 5),
    )
    stil.map(
        "CariKart.Treeview",
        background=[("selected", SECIM_SARI)],
        foreground=[("selected", LACIVERT)],
    )
    stil.map(
        "CariKart.Treeview.Heading",
        background=[("active", LACIVERT_ORTA)],
        foreground=[("active", BEYAZ)],
    )

    stil.configure(
        "CariKartKaydet.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=LACIVERT,
    )
    stil.map(
        "CariKartKaydet.TButton",
        background=[("active", LACIVERT_HOVER), ("!disabled", LACIVERT)],
        foreground=[("!disabled", BEYAZ)],
    )
    stil.configure(
        "CariKartVurgu.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=LACIVERT,
        background=SARI,
    )
    stil.map(
        "CariKartVurgu.TButton",
        background=[("active", SARI_HOVER), ("!disabled", SARI)],
        foreground=[("!disabled", LACIVERT)],
    )
    return stil


def tk_buton(
    parent,
    metin: str,
    komut: Callable | None = None,
    *,
    rol: str = "kaydet",
    state: str = "normal",
    **kwargs,
) -> tk.Button:
    stiller = {
        "kaydet": (LACIVERT, BEYAZ, LACIVERT_HOVER),
        "vurgu": (SARI, LACIVERT, SARI_HOVER),
        "ikincil": (BEYAZ, LACIVERT, ACIK_BG),
        "tehlike": (UYARI, BEYAZ, "#B91C1C"),
        "basari": (BASARI, BEYAZ, "#166534"),
        "ara": (LACIVERT_ORTA, BEYAZ, LACIVERT),
        "excel": ("#217346", BEYAZ, "#1a5c38"),
    }
    bg, fg, active = stiller.get(rol, stiller["kaydet"])
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    btn = tk.Button(
        parent,
        text=metin,
        command=komut,
        bg=bg,
        fg=fg,
        activebackground=active,
        activeforeground=fg,
        relief="flat",
        bd=0,
        padx=12,
        pady=6,
        font=font(10, "bold", root),
        cursor="hand2" if state == "normal" else "arrow",
        state=state,
        highlightthickness=1 if rol == "ikincil" else 0,
        highlightbackground=CIZGI if rol == "ikincil" else bg,
        disabledforeground=IKINCIL,
        **kwargs,
    )
    return btn


def beyaz_kart(parent, *, padx: int = 10, pady: int = 10) -> tuple[tk.Frame, tk.Frame]:
    """İnce kenarlı beyaz kart; (dış, iç) döner."""
    dis = tk.Frame(
        parent,
        bg=BEYAZ,
        highlightthickness=1,
        highlightbackground=CIZGI,
    )
    ic = tk.Frame(dis, bg=BEYAZ)
    ic.pack(fill="both", expand=True, padx=padx, pady=pady)
    return dis, ic


def rozet(parent, metin: str, *, bg: str, fg: str = BEYAZ) -> tk.Label:
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    return tk.Label(
        parent,
        text=metin,
        bg=bg,
        fg=fg,
        font=font(8, "bold", root),
        padx=8,
        pady=2,
    )


class ToolTip:
    """Basit hover ipucu."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._goster, add="+")
        widget.bind("<Leave>", self._gizle, add="+")

    def _goster(self, _e=None):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#111827",
            foreground=BEYAZ,
            relief="solid",
            borderwidth=1,
            font=font(8, root=self.widget),
            padx=8,
            pady=5,
            wraplength=320,
        ).pack()

    def _gizle(self, _e=None):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def ozet_karti(
    parent,
    baslik: str,
    *,
    deger: str = "—",
    alt: str = "",
    deger_renk: str = LACIVERT,
) -> dict:
    """Üst özet kartı; dönen dict ile metin güncellenir."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis, ic = beyaz_kart(parent, padx=12, pady=10)
    lbl_baslik = tk.Label(
        ic, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(8, root=root), anchor="w"
    )
    lbl_baslik.pack(fill="x")
    lbl_deger = tk.Label(
        ic,
        text=deger,
        bg=BEYAZ,
        fg=deger_renk,
        font=font(14, "bold", root),
        anchor="w",
        wraplength=200,
        justify="left",
    )
    lbl_deger.pack(fill="x", pady=(2, 0))
    lbl_alt = tk.Label(
        ic, text=alt, bg=BEYAZ, fg=IKINCIL, font=font(8, root=root), anchor="w"
    )
    lbl_alt.pack(fill="x", pady=(2, 0))
    return {"frame": dis, "baslik": lbl_baslik, "deger": lbl_deger, "alt": lbl_alt}
