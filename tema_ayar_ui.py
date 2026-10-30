"""Ayarlar > Görünüm > Tema — önizleme, Kaydet, Vazgeç, Varsayılana Dön."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import ui_tema

# Alt düğmeler: ttk stili tema sonrası metni kaybetmesin diye sabit kontrastlı tk.Button
_BTN_BG = "#102A43"
_BTN_FG = "#F5F8FF"
_BTN_ACCENT_BG = "#F4C542"
_BTN_ACCENT_FG = "#081B2C"


def _alt_dugme(parent, text: str, command, *, vurgu: bool = False) -> tk.Button:
    if vurgu:
        bg, fg, abg = _BTN_ACCENT_BG, _BTN_ACCENT_FG, "#FFE89A"
    else:
        bg, fg, abg = _BTN_BG, _BTN_FG, "#1A3A56"
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=abg,
        activeforeground=fg if not vurgu else _BTN_ACCENT_FG,
        disabledforeground="#94A3B8",
        relief="flat",
        padx=14,
        pady=6,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    )


def tema_ayarlari_ac(parent) -> None:
    """Yerel önizleme diyaloğu; Kaydet olmadan uygulama teması değişmez."""
    win = tk.Toplevel(parent)
    win.title("Görünüm — Tema")
    win.transient(parent)
    win.grab_set()
    win.geometry("560x520")
    try:
        win.minsize(520, 440)
    except tk.TclError:
        pass

    onceki = ui_tema.aktif_tema_id()
    secim = tk.StringVar(value=onceki)

    # Önce alt çubuk — görev çubuğu / expand yüzünden yazı kaybolmasın
    alt = tk.Frame(win, bg="#E8EEF4", padx=12, pady=10)
    alt.pack(side="bottom", fill="x")

    ust = ttk.Frame(win, padding=12)
    ust.pack(fill="both", expand=True)

    ttk.Label(ust, text="Tema", font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(
        ust,
        text="Seçim yalnızca önizlemeyi değiştirir. Uygulamaya aktarmak için Kaydet’e basın.",
        wraplength=500,
    ).pack(anchor="w", pady=(4, 10))

    liste_fr = ttk.LabelFrame(ust, text="Hazır temalar (ilk aşama)", padding=8)
    liste_fr.pack(fill="x")
    onizleme = tk.Frame(ust, height=160, highlightthickness=1, highlightbackground="#D9E2EC")
    onizleme.pack(fill="x", pady=12)
    onizleme.pack_propagate(False)

    def _onizle(*_a):
        tid = secim.get()
        t = ui_tema.tema_getir(tid)
        r = t["renkler"]
        for w in onizleme.winfo_children():
            w.destroy()
        baslik = tk.Frame(onizleme, bg=r["LACIVERT"], height=36)
        baslik.pack(fill="x")
        baslik.pack_propagate(False)
        tk.Label(
            baslik,
            text=f"Önizleme — {t['ad']}",
            bg=r["LACIVERT"],
            fg=r.get("METIN_ACIK", "#F5F8FF"),
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=10)
        govde = tk.Frame(onizleme, bg=r["ACIK_BG"])
        govde.pack(fill="both", expand=True)
        tk.Label(
            govde,
            text="Örnek metin kutusu",
            bg=r["BEYAZ"],
            fg=r["METIN"],
            relief="solid",
            bd=1,
        ).pack(anchor="w", padx=10, pady=(10, 4))
        btn_fr = tk.Frame(govde, bg=r["ACIK_BG"])
        btn_fr.pack(anchor="w", padx=10, pady=4)
        tk.Label(
            btn_fr,
            text=" Ana işlem ",
            bg=r["LACIVERT"],
            fg=r.get("METIN_ACIK", "#FFFFFF"),
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 8))
        tk.Label(
            btn_fr,
            text=" Vurgu ",
            bg=r["SARI"],
            fg=r.get("KOYU_LACIVERT", r["METIN"]),
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            govde,
            text="⚠ Örnek uyarı (iş anlamı korunur)",
            bg=r["ACIK_BG"],
            fg=r.get("UYARI", "#D64545"),
        ).pack(anchor="w", padx=10, pady=6)
        ornek = tk.Frame(govde, bg=r["ACIK_BG"])
        ornek.pack(anchor="w", padx=10, pady=(0, 8))
        for hex_r in (r["LACIVERT"], r["SARI"], r["ACIK_BG"]):
            tk.Frame(
                ornek,
                bg=hex_r,
                width=28,
                height=16,
                highlightthickness=1,
                highlightbackground="#99A",
            ).pack(side="left", padx=3)

    for t in ui_tema.etkin_temalar():
        rb = ttk.Radiobutton(
            liste_fr,
            text=t["ad"],
            value=t["id"],
            variable=secim,
            command=_onizle,
        )
        rb.pack(anchor="w", pady=2)

    _onizle()

    def _kaydet():
        from database.session_manager import oturum

        tid = secim.get()
        try:
            ui_tema.tercih_yaz(oturum.user_id, tid)
            ui_tema.uygula(tid, root=parent.winfo_toplevel())
        except Exception as exc:
            messagebox.showerror("Tema", f"Tema kaydedilemedi:\n{exc}", parent=win)
            return
        win.destroy()

    def _vazgec():
        # Kaydetmeden kapanınca uygulama teması önceki gibi kalır (önizleme zaten yerel)
        win.destroy()

    def _varsayilan():
        secim.set(ui_tema.TEMA_KLASIK)
        _onizle()

    _alt_dugme(alt, "Varsayılana Dön", _varsayilan).pack(side="left")
    _alt_dugme(alt, "Kaydet", _kaydet, vurgu=True).pack(side="right")
    _alt_dugme(alt, "Vazgeç", _vazgec).pack(side="right", padx=(0, 8))
    win.protocol("WM_DELETE_WINDOW", _vazgec)
    # T19 — klavye: Enter kaydet, Esc vazgeç
    win.bind("<Return>", lambda _e: _kaydet())
    win.bind("<Escape>", lambda _e: _vazgec())
    try:
        win.focus_set()
    except tk.TclError:
        pass
