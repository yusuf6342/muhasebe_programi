"""Satışlar bölümü kurumsal renk / tipografi / ortak görsel bileşenler (Tkinter).

İş mantığı yok — yalnızca renk, font, ölçü ve tekrar kullanılabilir chrome.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Callable

# Kurumsal palet (Satışlar)
LACIVERT = "#102A43"
KOYU_LACIVERT = "#081B2C"
SARI = "#F4C542"
ACIK_SARI = "#FFE89A"
BEYAZ = "#FFFFFF"
ACIK_BG = "#F3F6F9"
METIN = "#172B4D"
IKINCIL = "#627D98"
BASARI = "#1F9D74"
UYARI = "#D64545"

LACIVERT_HOVER = "#1A3A56"
LACIVERT_ACIK = "#243B53"
CIZGI = "#D9E2EC"
KART_HOVER_BG = "#FFF8E1"

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
    """Satış ekranları ttk stillerini kaydeder."""
    stil = stil or ttk.Style(root)
    if "vista" in stil.theme_names():
        try:
            stil.theme_use("vista")
        except tk.TclError:
            pass
    elif "clam" in stil.theme_names():
        try:
            stil.theme_use("clam")
        except tk.TclError:
            pass

    f_ui = font(10, root=root)
    f_bold = font(10, "bold", root=root)
    f_baslik = font(16, "bold", root=root)
    f_alt = font(9, root=root)
    f_btn = font(11, "bold", root=root)

    stil.configure("Satis.TFrame", background=ACIK_BG)
    stil.configure("SatisPanel.TFrame", background=BEYAZ)
    stil.configure("Satis.TLabel", background=ACIK_BG, foreground=METIN, font=f_ui)
    stil.configure("SatisMuted.TLabel", background=ACIK_BG, foreground=IKINCIL, font=f_alt)
    stil.configure("SatisPanel.TLabel", background=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("SatisBaslik.TLabel", background=ACIK_BG, foreground=LACIVERT, font=f_baslik)
    stil.configure("SatisPanelBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_bold)

    stil.configure(
        "SatisKaydet.TButton",
        font=f_btn,
        padding=(14, 8),
        foreground=BEYAZ,
        background=LACIVERT,
    )
    stil.map(
        "SatisKaydet.TButton",
        background=[("active", LACIVERT_HOVER), ("!disabled", LACIVERT)],
        foreground=[("!disabled", BEYAZ)],
    )
    stil.configure(
        "SatisYeni.TButton",
        font=f_btn,
        padding=(14, 8),
        foreground=KOYU_LACIVERT,
        background=SARI,
    )
    stil.map(
        "SatisYeni.TButton",
        background=[("active", ACIK_SARI), ("!disabled", SARI)],
        foreground=[("!disabled", KOYU_LACIVERT)],
    )
    stil.configure(
        "SatisIptal.TButton",
        font=f_btn,
        padding=(14, 8),
        foreground=BEYAZ,
        background=UYARI,
    )
    stil.map(
        "SatisIptal.TButton",
        background=[("active", "#B83B3B"), ("!disabled", UYARI)],
        foreground=[("!disabled", BEYAZ)],
    )
    stil.configure(
        "SatisGeri.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=LACIVERT,
        background=BEYAZ,
    )
    stil.map(
        "SatisGeri.TButton",
        background=[("active", ACIK_BG), ("!disabled", BEYAZ)],
        foreground=[("!disabled", LACIVERT)],
    )
    stil.configure(
        "SatisAra.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=LACIVERT_ACIK,
    )
    stil.map(
        "SatisAra.TButton",
        background=[("active", LACIVERT), ("!disabled", LACIVERT_ACIK)],
        foreground=[("!disabled", BEYAZ)],
    )

    stil.configure(
        "Satis.Treeview",
        font=f_alt,
        rowheight=28,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
    )
    stil.configure(
        "Satis.Treeview.Heading",
        font=f_bold,
        background=LACIVERT,
        foreground=BEYAZ,
    )
    stil.map(
        "Satis.Treeview",
        background=[("selected", ACIK_SARI)],
        foreground=[("selected", KOYU_LACIVERT)],
    )
    return stil


def tk_buton(
    parent,
    metin: str,
    komut: Callable | None = None,
    *,
    rol: str = "kaydet",
    **kwargs,
) -> tk.Button:
    """Kurumsal tk.Button (ttk tema sınırlarını aşmak için)."""
    stiller = {
        "kaydet": (LACIVERT, BEYAZ, LACIVERT_HOVER),
        "yeni": (SARI, KOYU_LACIVERT, ACIK_SARI),
        "duzenle": (LACIVERT_ACIK, BEYAZ, LACIVERT),
        "iptal": (UYARI, BEYAZ, "#B83B3B"),
        "ara": (SARI, KOYU_LACIVERT, ACIK_SARI),
        "geri": (BEYAZ, LACIVERT, ACIK_BG),
        "yazdir": (KOYU_LACIVERT, BEYAZ, LACIVERT),
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
        activeforeground=fg if rol != "geri" else LACIVERT,
        relief="flat",
        bd=0,
        padx=14,
        pady=7,
        font=font(11, "bold", root),
        cursor="hand2",
        highlightthickness=1 if rol == "geri" else 0,
        highlightbackground=LACIVERT if rol == "geri" else bg,
        **kwargs,
    )
    return btn


def oturum_bilgileri(app) -> tuple[str, str, str]:
    """firma, kullanıcı, tarih metinleri."""
    firma = "—"
    kullanici = "—"
    try:
        from database.session_manager import oturum

        firma = oturum.firma_unvan or oturum.firma_kodu or "—"
        kullanici = oturum.kullanici_adi or oturum.kullanici_kodu or "—"
    except Exception:
        pass
    tarih = datetime.now().strftime("%d.%m.%Y")
    return firma, kullanici, tarih


def hub_ust_baslik(
    parent,
    *,
    baslik: str,
    alt_baslik: str,
    app=None,
    geri_komut: Callable | None = None,
    geri_metin: str = "Ana Menüye Dön",
) -> tk.Frame:
    """Lacivert kurumsal üst şerit (hub / alt menü)."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    ust = tk.Frame(parent, bg=LACIVERT, highlightthickness=0)
    ust.pack(fill="x")

    sol = tk.Frame(ust, bg=LACIVERT)
    sol.pack(side="left", fill="both", expand=True, padx=20, pady=16)
    tk.Label(
        sol,
        text=baslik,
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(28, "bold", root),
        anchor="w",
    ).pack(anchor="w")
    tk.Label(
        sol,
        text=alt_baslik,
        bg=LACIVERT,
        fg=ACIK_SARI,
        font=font(12, root=root),
        anchor="w",
        wraplength=640,
        justify="left",
    ).pack(anchor="w", pady=(4, 0))
    tk.Frame(sol, bg=SARI, height=3).pack(anchor="w", fill="x", pady=(10, 0))

    sag = tk.Frame(ust, bg=LACIVERT)
    sag.pack(side="right", padx=16, pady=12)
    if app is not None:
        firma, kullanici, tarih = oturum_bilgileri(app)
        for metin, renk in (
            (firma, BEYAZ),
            (f"Kullanıcı: {kullanici}", ACIK_SARI),
            (tarih, IKINCIL),
        ):
            tk.Label(
                sag,
                text=metin,
                bg=LACIVERT,
                fg=renk,
                font=font(9, root=root),
                anchor="e",
            ).pack(anchor="e")
    if geri_komut is not None:
        tk_buton(sag, geri_metin, geri_komut, rol="geri").pack(anchor="e", pady=(8, 0))
    return ust


def ekran_ust_cubugu(
    app,
    baslik: str,
    *,
    alt_baslik: str = "",
    geri_komut: Callable | None = None,
    geri_metin: str = "← Satışlar",
) -> tk.Frame:
    """Çalışma ekranı chrome: lacivert başlık + sarı çizgi + açık gri gövde alanı.

    Dönüş: içerik gövdesi (beyaz panel üzerinde pack edilecek alan).
    """
    stil_uygula(root=app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)

    ust = tk.Frame(kok, bg=LACIVERT)
    ust.pack(fill="x")
    sol = tk.Frame(ust, bg=LACIVERT)
    sol.pack(side="left", fill="both", expand=True, padx=16, pady=12)
    tk.Label(
        sol,
        text=baslik,
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(18, "bold", app),
        anchor="w",
    ).pack(anchor="w")
    if alt_baslik:
        tk.Label(
            sol,
            text=alt_baslik,
            bg=LACIVERT,
            fg=ACIK_SARI,
            font=font(10, root=app),
            anchor="w",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))
    tk.Frame(ust, bg=SARI, height=3).pack(fill="x")

    if geri_komut is not None:
        sag = tk.Frame(ust, bg=LACIVERT)
        sag.pack(side="right", padx=12, pady=10)
        tk_buton(sag, geri_metin, geri_komut, rol="geri").pack()

    govde = tk.Frame(kok, bg=ACIK_BG)
    govde.pack(fill="both", expand=True, padx=12, pady=10)

    panel = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    panel.pack(fill="both", expand=True)
    ic = tk.Frame(panel, bg=BEYAZ)
    ic.pack(fill="both", expand=True, padx=12, pady=10)
    return ic


def treeview_stil(tablo: ttk.Treeview) -> None:
    """Satış tablolarına kurumsal stil + kuşak etiketleri."""
    tablo.configure(style="Satis.Treeview")
    tablo.tag_configure("tek", background=BEYAZ)
    tablo.tag_configure("cift", background=ACIK_BG)


# Müşteri / tedarikçi kart listesi — okunabilir punto + belirgin şerit
_CARI_LISTE_STRIPE = "#E4EBF3"
_CARI_LISTE_BAKIYE_FG = "#081B2C"


def cari_liste_treeview_stil(tablo: ttk.Treeview, root: tk.Misc | None = None) -> None:
    """Müşteri/tedarikçi kart listesi: büyük punto, görünür kolon başlıkları, şerit."""
    stil = ttk.Style(root)
    # Vista Treeview heading arka planı boyamaz; beyaz yazı kaybolur → clam zorunlu
    try:
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
    except tk.TclError:
        pass

    f_govde = font(11, root=root)
    f_baslik = font(12, "bold", root=root)
    f_bakiye = font(12, "bold", root=root)
    stil.configure(
        "CariListe.Treeview",
        font=f_govde,
        rowheight=34,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "CariListe.Treeview.Heading",
        font=f_baslik,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        borderwidth=0,
        padding=(8, 8),
    )
    stil.map(
        "CariListe.Treeview",
        background=[("selected", ACIK_SARI)],
        foreground=[("selected", KOYU_LACIVERT)],
    )
    stil.map(
        "CariListe.Treeview.Heading",
        background=[("active", LACIVERT_HOVER), ("pressed", LACIVERT_HOVER)],
        foreground=[("active", BEYAZ), ("pressed", BEYAZ)],
    )
    tablo.configure(style="CariListe.Treeview")
    tablo.tag_configure("tek", background=BEYAZ)
    tablo.tag_configure("cift", background=_CARI_LISTE_STRIPE)
    tablo.tag_configure(
        "bakiye_koyu",
        foreground=_CARI_LISTE_BAKIYE_FG,
        font=f_bakiye,
    )


class HubKart(tk.Frame):
    """Büyük tıklanabilir menü kartı (hover sarı/lacivert)."""

    def __init__(
        self,
        parent,
        *,
        baslik: str,
        aciklama: str,
        komut: Callable,
        simge: str = "●",
        wrap_baslik: int = 0,
        **kwargs,
    ):
        super().__init__(
            parent,
            bg=BEYAZ,
            highlightthickness=1,
            highlightbackground=CIZGI,
            cursor="hand2",
            **kwargs,
        )
        self._komut = komut
        self._baslik = baslik
        root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None

        accent = tk.Frame(self, bg=SARI, width=5)
        accent.pack(side="left", fill="y")

        ic = tk.Frame(self, bg=BEYAZ)
        ic.pack(side="left", fill="both", expand=True, padx=14, pady=14)
        self._ic = ic

        ust = tk.Frame(ic, bg=BEYAZ)
        ust.pack(fill="x")
        self._simge = tk.Label(
            ust, text=simge, bg=BEYAZ, fg=SARI, font=font(16, "bold", root)
        )
        self._simge.pack(side="left", padx=(0, 8))
        self._lbl_baslik = tk.Label(
            ust,
            text=baslik,
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(13, "bold", root),
            anchor="w",
            justify="left",
            wraplength=wrap_baslik or 0,
        )
        self._lbl_baslik.pack(side="left", fill="x", expand=True)

        self._lbl_aciklama = tk.Label(
            ic,
            text=aciklama,
            bg=BEYAZ,
            fg=IKINCIL,
            font=font(10, root=root),
            anchor="w",
            justify="left",
            wraplength=280,
        )
        self._lbl_aciklama.pack(anchor="w", pady=(8, 0), fill="x")

        for w in (self, ic, ust, self._simge, self._lbl_baslik, self._lbl_aciklama, accent):
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            w.bind("<Button-1>", self._click)

    def _enter(self, _e=None):
        for w in (self, self._ic, self._simge, self._lbl_baslik, self._lbl_aciklama):
            try:
                w.configure(bg=KART_HOVER_BG)
            except tk.TclError:
                pass
        self.configure(highlightbackground=SARI, highlightthickness=2)

    def _leave(self, _e=None):
        for w in (self, self._ic, self._simge, self._lbl_baslik, self._lbl_aciklama):
            try:
                w.configure(bg=BEYAZ)
            except tk.TclError:
                pass
        self._lbl_baslik.configure(fg=LACIVERT)
        self._lbl_aciklama.configure(fg=IKINCIL)
        self._simge.configure(fg=SARI)
        self.configure(highlightbackground=CIZGI, highlightthickness=1)

    def _click(self, _e=None):
        if self._komut:
            self._komut()
