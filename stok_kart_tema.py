"""Stok Kartı — kurumsal renk, tipografi ve chrome (sarı #F5C400 / lacivert #142B4A).

İş mantığı yok; yalnızca görsel sabitler ve tekrar kullanılabilir bileşenler.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

# Talimat paleti
LACIVERT = "#142B4A"
LACIVERT_ORTA = "#1E3A5F"
SARI = "#F5C400"
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
    f_btn = font(10, "bold", root=root)

    stil.configure("StokKart.TFrame", background=ACIK_BG)
    stil.configure("StokKartPanel.TFrame", background=BEYAZ)
    stil.configure("StokKart.TLabel", background=ACIK_BG, foreground=METIN, font=f_ui)
    stil.configure("StokKartMuted.TLabel", background=ACIK_BG, foreground=IKINCIL, font=f_alt)
    stil.configure("StokKartPanel.TLabel", background=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("StokKartPanelMuted.TLabel", background=BEYAZ, foreground=IKINCIL, font=f_alt)
    stil.configure("StokKartBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_baslik)
    stil.configure("StokKartBolum.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_bold)

    stil.configure(
        "StokKart.TLabelframe",
        background=BEYAZ,
        foreground=LACIVERT,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "StokKart.TLabelframe.Label",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_bold,
    )
    stil.configure("StokKart.TEntry", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("StokKart.TCombobox", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("StokKart.TNotebook", background=BEYAZ)
    stil.configure("StokKart.TNotebook.Tab", font=f_bold, padding=(14, 6))

    stil.configure(
        "StokKart.Treeview",
        font=f_alt,
        rowheight=28,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=0,
    )
    stil.configure(
        "StokKart.Treeview.Heading",
        font=f_bold,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        padding=(6, 6),
    )
    stil.map(
        "StokKart.Treeview",
        background=[("selected", SECIM_SARI)],
        foreground=[("selected", LACIVERT)],
    )
    stil.map(
        "StokKart.Treeview.Heading",
        background=[("active", LACIVERT_ORTA)],
        foreground=[("active", BEYAZ)],
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
        "ara": (LACIVERT_ORTA, BEYAZ, LACIVERT),
        "yeni": (SARI, LACIVERT, SARI_HOVER),
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
    dis = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
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


def ozet_karti(
    parent,
    baslik: str,
    *,
    deger: str = "—",
    alt: str = "",
    deger_renk: str = LACIVERT,
) -> dict:
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
        wraplength=180,
        justify="left",
    )
    lbl_deger.pack(fill="x", pady=(2, 0))
    lbl_alt = tk.Label(ic, text=alt, bg=BEYAZ, fg=IKINCIL, font=font(8, root=root), anchor="w")
    lbl_alt.pack(fill="x", pady=(2, 0))
    return {"frame": dis, "baslik": lbl_baslik, "deger": lbl_deger, "alt": lbl_alt}


def baslik_seridi(
    parent,
    *,
    baslik: str,
    alt: str = "",
    durum: str | None = None,
) -> dict:
    """Lacivert üst şerit + sarı çizgi; durum rozeti opsiyonel."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    ust = tk.Frame(parent, bg=LACIVERT)
    ust.pack(fill="x")
    ic = tk.Frame(ust, bg=LACIVERT)
    ic.pack(fill="x", padx=16, pady=12)
    sol = tk.Frame(ic, bg=LACIVERT)
    sol.pack(side="left", fill="both", expand=True)
    lbl_baslik = tk.Label(
        sol, text=baslik, bg=LACIVERT, fg=BEYAZ, font=font(18, "bold", root), anchor="w"
    )
    lbl_baslik.pack(anchor="w")
    lbl_alt = tk.Label(
        sol, text=alt, bg=LACIVERT, fg=SARI, font=font(10, root=root), anchor="w"
    )
    lbl_alt.pack(anchor="w", pady=(2, 0))
    sag = tk.Frame(ic, bg=LACIVERT)
    sag.pack(side="right")
    rozet_lbl = None
    if durum:
        renk = BASARI if "Aktif" in durum else (DIKKAT if "Kapalı" in durum else IKINCIL)
        rozet_lbl = rozet(sag, durum, bg=renk, fg=BEYAZ)
        rozet_lbl.pack(side="right")
    tk.Frame(ust, bg=SARI, height=3).pack(fill="x")
    return {"frame": ust, "baslik": lbl_baslik, "alt": lbl_alt, "rozet": rozet_lbl}


def form_etiket(parent, metin: str, *, zorunlu: bool = False) -> tk.Label:
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    text = f"{metin} *" if zorunlu else metin
    return tk.Label(
        parent,
        text=text,
        bg=BEYAZ,
        fg=LACIVERT if zorunlu else IKINCIL,
        font=font(9, "bold" if zorunlu else "normal", root),
        anchor="w",
    )
