"""Ana panel kurumsal renk / tipografi sabitleri (Tkinter)."""

from __future__ import annotations

from tkinter import ttk

# Marka paleti — sarı yalnızca vurgu
LACIVERT = "#102A43"
KOYU_LACIVERT = "#071A2B"
SARI = "#F5C518"
ACIK_BG = "#F4F6F8"
BEYAZ = "#FFFFFF"
METIN = "#263238"
PASIF = "#7B8794"
BASARI = "#2E7D32"
UYARI = "#D97706"

# Türetilmiş
LACIVERT_HOVER = "#1A3A56"
METIN_ACIK = "#E8EEF4"
SARI_HOVER = "#E0B010"
CIZGI = "#D0D7DE"
KART_GOLEGE = "#E2E8EE"

FIRMA_ADI = "RAY MOBİLYA AKSESUARLARI"
FIRMA_KISA = "RAY"

FONT_UI = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_BASLIK = ("Segoe UI", 16, "bold")
FONT_ALT = ("Segoe UI", 9)
FONT_KUCUK = ("Segoe UI", 8)
FONT_MENU = ("Segoe UI", 10)
FONT_MENU_BOLD = ("Segoe UI", 10, "bold")
FONT_KART_BASLIK = ("Segoe UI", 11, "bold")
FONT_OZET = ("Segoe UI", 18, "bold")
FONT_SIDEBAR = ("Segoe UI", 11, "bold")

SOL_MENU_GENISLIK = 250


def para_tr(tutar) -> str:
    """TR para biçimi: 1.234,56"""
    try:
        v = float(tutar or 0)
    except (TypeError, ValueError):
        return "0,00"
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def sayi_tr(tutar, basamak: int = 0) -> str:
    try:
        v = float(tutar or 0)
    except (TypeError, ValueError):
        return "0"
    if basamak <= 0:
        return f"{int(round(v)):,}".replace(",", ".")
    s = f"{v:,.{basamak}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def stil_uygula(stil: ttk.Style) -> None:
    """Ana panel ve içerik alanı ttk stilleri."""
    if "vista" in stil.theme_names():
        stil.theme_use("vista")
    elif "clam" in stil.theme_names():
        stil.theme_use("clam")

    stil.configure("Baslik.TLabel", font=FONT_BASLIK, foreground=METIN, background=ACIK_BG)
    stil.configure("AnaPanel.TFrame", background=ACIK_BG)
    stil.configure("AnaPanelKart.TFrame", background=BEYAZ)
    stil.configure("AnaPanel.TLabel", background=ACIK_BG, foreground=METIN, font=FONT_UI)
    stil.configure("AnaPanelMuted.TLabel", background=ACIK_BG, foreground=PASIF, font=FONT_ALT)
    stil.configure("AnaPanelKart.TLabel", background=BEYAZ, foreground=METIN, font=FONT_UI)
    stil.configure("AnaPanelKartMuted.TLabel", background=BEYAZ, foreground=PASIF, font=FONT_ALT)
    stil.configure("AnaPanelBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=FONT_KART_BASLIK)
    stil.configure("AnaPanelOzet.TLabel", background=BEYAZ, foreground=LACIVERT, font=FONT_OZET)
    stil.configure("Header.TFrame", background=BEYAZ)
    stil.configure("Header.TLabel", background=BEYAZ, foreground=METIN, font=FONT_UI)
    stil.configure("HeaderMuted.TLabel", background=BEYAZ, foreground=PASIF, font=FONT_ALT)
    stil.configure("HeaderTitle.TLabel", background=BEYAZ, foreground=LACIVERT, font=FONT_BASLIK)
    stil.configure("Status.TFrame", background=KOYU_LACIVERT)
    stil.configure("Status.TLabel", background=KOYU_LACIVERT, foreground=METIN_ACIK, font=FONT_KUCUK)

    stil.configure("Menu.TButton", anchor="w", padding=(14, 10))
    stil.configure("AltMenu.TButton", anchor="w", padding=(16, 12))
    stil.configure(
        "SeciliMenu.TButton",
        anchor="w",
        padding=(14, 10),
        foreground=KOYU_LACIVERT,
        background=SARI,
    )
    stil.map(
        "SeciliMenu.TButton",
        background=[("active", SARI_HOVER), ("!disabled", SARI)],
        foreground=[("!disabled", KOYU_LACIVERT)],
    )
    stil.configure(
        "HizliSatisMenu.TButton",
        anchor="w",
        padding=(14, 10),
        foreground=KOYU_LACIVERT,
        background=SARI,
    )
    stil.map(
        "HizliSatisMenu.TButton",
        background=[("active", SARI_HOVER), ("!disabled", SARI)],
        foreground=[("!disabled", KOYU_LACIVERT)],
    )
    stil.configure("Oturum.TLabel", font=FONT_ALT, background=BEYAZ, foreground=METIN)
    stil.configure(
        "Geri.TButton",
        font=FONT_UI_BOLD,
        padding=(12, 6),
        foreground=BEYAZ,
        background=LACIVERT,
    )
    stil.map(
        "Geri.TButton",
        background=[("active", LACIVERT_HOVER), ("!disabled", LACIVERT)],
        foreground=[("!disabled", BEYAZ)],
    )

    stil.configure(
        "AnaPanel.Treeview",
        font=FONT_ALT,
        rowheight=26,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
    )
    stil.configure(
        "AnaPanel.Treeview.Heading",
        font=FONT_UI_BOLD,
        background=LACIVERT,
        foreground=BEYAZ,
    )
    stil.map(
        "AnaPanel.Treeview",
        background=[("selected", SARI)],
        foreground=[("selected", KOYU_LACIVERT)],
    )
