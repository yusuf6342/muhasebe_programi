"""Satış Faturası Kartı — kurumsal renk, tipografi ve chrome (Tkinter).

İş mantığı yok; yalnızca görsel sabitler ve tekrar kullanılabilir üst/alt çubuk.
Palet: cari_kart_tema / satis_tema ile uyumlu (lacivert + sarı).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

# Kurumsal palet
LACIVERT = "#0B2A4A"
LACIVERT_ORTA = "#163E66"
LACIVERT_HOVER = "#1A4068"
SARI = "#F5B700"
SARI_HOVER = "#FFD54F"
ACIK_BG = "#F4F6F8"
BEYAZ = "#FFFFFF"
METIN = "#1F2937"
IKINCIL = "#667085"
BASARI = "#15803D"
BASARI_HOVER = "#166534"
UYARI = "#D97706"
UYARI_HOVER = "#B45309"
IPTAL = "#DC2626"
IPTAL_HOVER = "#B91C1C"
CIZGI = "#D7DEE7"
SECIM = "#FFE082"
STRIPE = "#F0F3F7"

# Durum rozetleri
DURUM_RENKLERI = {
    "TASLAK": ("#64748B", BEYAZ),
    "ONAYLANDI": (BASARI, BEYAZ),
    "AÇIK": (BASARI, BEYAZ),
    "KAPALI": (LACIVERT_ORTA, BEYAZ),
    "İPTAL": (IPTAL, BEYAZ),
    "MUHASEBELEŞTİ": ("#0E7490", BEYAZ),
    "E-FATURA": ("#1D4ED8", BEYAZ),
    "HATA": (IPTAL, BEYAZ),
}

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
    f_baslik = font(13, "bold", root=root)
    f_alt = font(9, root=root)
    f_btn = font(10, "bold", root=root)
    f_toplam = font(12, "bold", root=root)

    stil.configure("Fatura.TFrame", background=ACIK_BG)
    stil.configure("FaturaPanel.TFrame", background=BEYAZ)
    stil.configure("Fatura.TLabel", background=ACIK_BG, foreground=METIN, font=f_ui)
    stil.configure("FaturaMuted.TLabel", background=ACIK_BG, foreground=IKINCIL, font=f_alt)
    stil.configure("FaturaPanel.TLabel", background=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("FaturaPanelMuted.TLabel", background=BEYAZ, foreground=IKINCIL, font=f_alt)
    stil.configure("FaturaBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_baslik)
    stil.configure("FaturaBolum.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_bold)
    stil.configure(
        "FaturaToplam.TLabel",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_toplam,
    )
    stil.configure(
        "FaturaGenelToplam.TLabel",
        background=BEYAZ,
        foreground=LACIVERT,
        font=font(14, "bold", root),
    )

    stil.configure(
        "Fatura.TLabelframe",
        background=BEYAZ,
        foreground=LACIVERT,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "Fatura.TLabelframe.Label",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_bold,
    )
    stil.configure("Fatura.TEntry", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("Fatura.TCombobox", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)

    stil.configure(
        "FaturaSatir.Treeview",
        font=f_alt,
        rowheight=24,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "FaturaSatir.Treeview.Heading",
        font=f_bold,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
    )
    stil.map(
        "FaturaSatir.Treeview",
        background=[("selected", SECIM)],
        foreground=[("selected", LACIVERT)],
    )
    stil.map(
        "FaturaSatir.Treeview.Heading",
        background=[("active", LACIVERT_ORTA)],
        foreground=[("active", BEYAZ)],
    )

    stil.configure(
        "FaturaKaydet.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=LACIVERT,
    )
    stil.map(
        "FaturaKaydet.TButton",
        background=[("active", LACIVERT_HOVER), ("!disabled", LACIVERT)],
        foreground=[("!disabled", BEYAZ)],
    )
    stil.configure(
        "FaturaOnay.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=BASARI,
    )
    stil.map(
        "FaturaOnay.TButton",
        background=[("active", BASARI_HOVER), ("!disabled", BASARI)],
        foreground=[("!disabled", BEYAZ)],
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
        "onay": (BASARI, BEYAZ, BASARI_HOVER),
        "vurgu": (SARI, LACIVERT, SARI_HOVER),
        "ikincil": (BEYAZ, LACIVERT, ACIK_BG),
        "uyari": (UYARI, BEYAZ, UYARI_HOVER),
        "tehlike": (IPTAL, BEYAZ, IPTAL_HOVER),
        "yazdir": (LACIVERT_ORTA, BEYAZ, LACIVERT),
    }
    bg, fg, active = stiller.get(rol, stiller["kaydet"])
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    return tk.Button(
        parent,
        text=metin,
        command=komut,
        bg=bg,
        fg=fg,
        activebackground=active,
        activeforeground=fg,
        relief="flat",
        bd=0,
        padx=10,
        pady=5,
        font=font(10, "bold", root),
        cursor="hand2" if state == "normal" else "arrow",
        state=state,
        highlightthickness=1 if rol == "ikincil" else 0,
        highlightbackground=CIZGI if rol == "ikincil" else bg,
        disabledforeground=IKINCIL,
        **kwargs,
    )


def beyaz_kart(parent, *, padx: int = 10, pady: int = 8) -> tuple[tk.Frame, tk.Frame]:
    dis = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    ic = tk.Frame(dis, bg=BEYAZ)
    ic.pack(fill="both", expand=True, padx=padx, pady=pady)
    return dis, ic


def durum_rozet(parent, metin: str) -> tk.Label:
    """Durum rozeti; metne göre renk seçilir."""
    anahtar = (metin or "TASLAK").strip().upper()
    bg, fg = DURUM_RENKLERI.get(anahtar, DURUM_RENKLERI["TASLAK"])
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    return tk.Label(
        parent,
        text=anahtar,
        bg=bg,
        fg=fg,
        font=font(9, "bold", root),
        padx=10,
        pady=3,
    )


def rozet_guncelle(label: tk.Label, metin: str) -> None:
    anahtar = (metin or "TASLAK").strip().upper()
    bg, fg = DURUM_RENKLERI.get(anahtar, DURUM_RENKLERI["TASLAK"])
    try:
        label.configure(text=anahtar, bg=bg, fg=fg)
    except tk.TclError:
        pass


def ust_toolbar(
    parent,
    *,
    baslik: str = "SATIŞ FATURASI",
    fatura_no: str = "",
    musteri_kisa: str = "",
    durum: str = "TASLAK",
) -> dict:
    """Sabit üst araç çubuğu iskeleti. Dönen dict widget referansları içerir."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    cubuk = tk.Frame(parent, bg=LACIVERT, highlightthickness=0)
    cubuk.pack(side="top", fill="x")

    sol = tk.Frame(cubuk, bg=LACIVERT)
    sol.pack(side="left", fill="y", padx=(14, 8), pady=8)

    tk.Label(
        sol,
        text=baslik,
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(14, "bold", root),
        anchor="w",
    ).pack(anchor="w")

    meta = tk.Frame(sol, bg=LACIVERT)
    meta.pack(anchor="w", pady=(4, 0))

    no_lbl = tk.Label(
        meta,
        text=fatura_no or "—",
        bg=LACIVERT,
        fg=SARI,
        font=font(11, "bold", root),
    )
    no_lbl.pack(side="left", padx=(0, 10))

    rozet = durum_rozet(meta, durum)
    rozet.pack(side="left", padx=(0, 10))

    musteri_lbl = tk.Label(
        meta,
        text=(musteri_kisa or "")[:48],
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(10, root=root),
    )
    musteri_lbl.pack(side="left")

    sag = tk.Frame(cubuk, bg=LACIVERT)
    sag.pack(side="right", padx=10, pady=8)

    # Sarı ayırıcı çizgi
    tk.Frame(cubuk, bg=SARI, height=3).pack(side="bottom", fill="x")

    return {
        "cubuk": cubuk,
        "sol": sol,
        "sag": sag,
        "fatura_no": no_lbl,
        "rozet": rozet,
        "musteri": musteri_lbl,
    }


def alt_ozet_cubugu(parent) -> dict:
    """Sabit alt özet kartı: sol işlem düğmeleri + not, sağ toplamlar."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis = tk.Frame(parent, bg=ACIK_BG, highlightthickness=0)
    dis.pack(side="bottom", fill="x")

    kart_dis, kart = beyaz_kart(dis, padx=12, pady=8)
    kart_dis.pack(fill="x", padx=8, pady=(4, 8))

    kart.columnconfigure(0, weight=1)
    kart.columnconfigure(1, weight=0)

    sol = tk.Frame(kart, bg=BEYAZ)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

    islem = tk.Frame(sol, bg=BEYAZ)
    islem.pack(fill="x", anchor="w")
    tk.Label(
        sol,
        text="Notlar / Açıklama",
        bg=BEYAZ,
        fg=LACIVERT,
        font=font(9, "bold", root),
        anchor="w",
    ).pack(anchor="w", pady=(8, 0))
    not_alani = tk.Text(sol, height=2, width=40, wrap="word", font=font(9, root=root), relief="solid", bd=1)
    not_alani.pack(fill="both", expand=True, pady=(4, 0))

    sag = tk.Frame(kart, bg=BEYAZ)
    sag.grid(row=0, column=1, sticky="ne")

    degerler: dict[str, tk.Label | ttk.Entry] = {}
    satirlar = (
        ("brut", "Brüt Toplam", False),
        ("iskonto", "Toplam İskonto", False),
        ("matrah", "KDV Matrahı", False),
        ("kdv", "KDV Toplamı", False),
        ("ara_toplam", "Ara Toplam", False),
        ("genel", "GENEL TOPLAM", True),
        ("doviz", "Döviz Karşılığı", False),
    )
    for i, (anahtar, baslik, vurgulu) in enumerate(satirlar):
        fg = LACIVERT if vurgulu else IKINCIL
        fnt = font(13 if vurgulu else 10, "bold" if vurgulu else "normal", root)
        tk.Label(sag, text=baslik, bg=BEYAZ, fg=fg, font=fnt, anchor="e").grid(
            row=i, column=0, sticky="e", padx=(0, 12), pady=(1 if not vurgulu else 4)
        )
        if anahtar == "genel":
            genel_cerceve = tk.Frame(sag, bg=BEYAZ)
            genel_cerceve.grid(row=i, column=1, sticky="e", pady=4)
            entry = ttk.Entry(genel_cerceve, font=font(13, "bold", root), width=12, justify="right")
            entry.insert(0, "0,00")
            entry.pack(side="left")
            degerler[anahtar] = entry
            yansit_btn = tk_buton(genel_cerceve, "Fiyatlara Yansıt", rol="ikincil")
            yansit_btn.pack(side="left", padx=(6, 0))
            degerler["yansit_btn"] = yansit_btn  # type: ignore[assignment]
        else:
            lbl = tk.Label(
                sag,
                text="0,00 TL" if anahtar != "doviz" else "—",
                bg=BEYAZ,
                fg=METIN,
                font=font(10, "bold", root),
                anchor="e",
                width=14,
            )
            lbl.grid(row=i, column=1, sticky="e", pady=1)
            degerler[anahtar] = lbl

    ipucu = tk.Label(
        sag,
        text="GENEL TOPLAM → Enter / Fiyatlara Yansıt ile birim fiyatlara dağıtılır",
        bg=BEYAZ,
        fg=IKINCIL,
        font=font(8, root=root),
        anchor="e",
    )
    ipucu.grid(row=len(satirlar), column=0, columnspan=2, sticky="e", pady=(2, 0))

    return {
        "dis": dis,
        "kart": kart,
        "not_alani": not_alani,
        "degerler": degerler,
        "sag": sag,
        "sol": sol,
        "islem": islem,
    }


def validation_panel(parent) -> dict:
    """Onay öncesi kısa doğrulama paneli (gizlenebilir)."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis = tk.Frame(parent, bg="#FEF3C7", highlightthickness=1, highlightbackground=UYARI)
    metin = tk.Label(
        dis,
        text="",
        bg="#FEF3C7",
        fg="#92400E",
        font=font(9, root=root),
        justify="left",
        anchor="w",
        wraplength=900,
    )
    metin.pack(fill="x", padx=10, pady=6)
    return {"dis": dis, "metin": metin}
