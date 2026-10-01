"""Fatura alt özet kartındaki Notlar alanı ve «Notu büyüt» düzenleme penceresi."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import fatura_tema as ftema

NOT_SATIR = 5


def _otomatik_kaydirma(text: tk.Text, sb: ttk.Scrollbar) -> None:
    """Kaydırma çubuğu yalnız metin kutuya sığmadığında görünür."""

    def _ayarla(ilk, son):
        sb.set(ilk, son)
        sigmiyor = float(ilk) > 0.0 or float(son) < 1.0
        try:
            if sigmiyor and not sb.winfo_manager():
                sb.pack(side="right", fill="y", before=text)
            elif not sigmiyor and sb.winfo_manager():
                sb.pack_forget()
        except tk.TclError:
            pass

    text.configure(yscrollcommand=_ayarla)


def not_buyut_dugmesi(parent, komut: Callable[[], None]) -> tk.Button:
    root = parent.winfo_toplevel()
    return tk.Button(
        parent, text="Notu büyüt", command=komut,
        bg=ftema.BEYAZ, fg=ftema.LACIVERT, activebackground=ftema.ACIK_BG,
        activeforeground=ftema.LACIVERT, relief="flat", bd=0, padx=6, pady=0,
        font=ftema.font(8, root=root), cursor="hand2",
        highlightthickness=1, highlightbackground=ftema.CIZGI,
    )


def not_kutusu_kur(parent, *, satir: int = NOT_SATIR) -> tk.Text:
    """Kenarlıklı, otomatik satır kaydırmalı ve gerektiğinde dikey kaydırmalı not kutusu."""
    root = parent.winfo_toplevel()
    kutu = tk.Frame(
        parent, bg=ftema.BEYAZ, highlightthickness=1,
        highlightbackground=ftema.CIZGI, highlightcolor=ftema.LACIVERT,
    )
    kutu.pack(fill="both", expand=True)
    text = tk.Text(
        kutu, height=satir, width=30, wrap="word", undo=True,
        font=ftema.font(9, root=root), relief="flat", bd=0, padx=4, pady=2,
        bg=ftema.BEYAZ, fg=ftema.METIN, insertbackground=ftema.METIN,
    )
    sb = ttk.Scrollbar(kutu, orient="vertical", command=text.yview)
    text.pack(side="left", fill="both", expand=True)
    _otomatik_kaydirma(text, sb)
    text.not_kaydirma = sb
    return text


def not_alani_kur(sol: tk.Frame, *, buyut: Callable[[], None]) -> tk.Text:
    """`sol` çerçevesini «Notlar» başlığı + «Notu büyüt» + not kutusu ile yeniden kurar."""
    root = sol.winfo_toplevel()
    for w in sol.winfo_children():
        w.destroy()
    baslik = tk.Frame(sol, bg=ftema.BEYAZ)
    baslik.pack(fill="x", pady=(4, 0))
    tk.Label(
        baslik, text="Notlar", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
        font=ftema.font(8, "bold", root), anchor="w",
    ).pack(side="left")
    btn = not_buyut_dugmesi(baslik, buyut)
    btn.pack(side="right")
    govde = tk.Frame(sol, bg=ftema.BEYAZ)
    govde.pack(fill="both", expand=True, pady=(2, 0))
    text = not_kutusu_kur(govde)
    text.not_buyut_btn = btn
    return text


def not_oku(text: tk.Text) -> str:
    try:
        return text.get("1.0", "end-1c")
    except tk.TclError:
        return ""


def not_yaz(text: tk.Text, metin: str) -> None:
    try:
        durum = text.cget("state")
        text.configure(state="normal")
        text.delete("1.0", "end")
        if metin:
            text.insert("1.0", metin)
        text.edit_reset()
        text.configure(state=durum)
    except tk.TclError:
        pass


def not_kilitle(text: tk.Text, kilitli: bool) -> None:
    """Onaylı faturada not salt okunur; «Notu büyüt» okumak için açık kalır."""
    try:
        text.configure(
            state="disabled" if kilitli else "normal",
            bg=ftema.ACIK_BG if kilitli else ftema.BEYAZ,
        )
    except tk.TclError:
        pass


def not_kilitli_mi(text: tk.Text) -> bool:
    try:
        return str(text.cget("state")) == "disabled"
    except tk.TclError:
        return True


class NotBuyutDialog(tk.Toplevel):
    def __init__(self, parent, metin: str, *, salt_okunur: bool = False,
                 uygula: Callable[[str], None] | None = None, baslik: str = "Fatura Notu"):
        super().__init__(parent)
        self.result: str | None = None
        self._uygula_fn = uygula
        self.salt_okunur = salt_okunur
        self.title(baslik + (" (salt okunur)" if salt_okunur else ""))
        self.configure(bg=ftema.ACIK_BG)
        self.transient(parent.winfo_toplevel())
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        gen, yuk = min(760, max(420, sw - 80)), min(520, max(300, sh - 120))
        self.geometry(f"{gen}x{yuk}+{max(0, (sw - gen) // 2)}+{max(0, (sh - yuk) // 3)}")
        self.minsize(380, 260)

        kart_dis, kart = ftema.beyaz_kart(self, padx=10, pady=8)
        kart_dis.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        tk.Label(
            kart, text="Notlar", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
            font=ftema.font(10, "bold", self), anchor="w",
        ).pack(anchor="w")
        kutu = tk.Frame(kart, bg=ftema.BEYAZ, highlightthickness=1,
                        highlightbackground=ftema.CIZGI, highlightcolor=ftema.LACIVERT)
        kutu.pack(fill="both", expand=True, pady=(4, 0))
        self.text = tk.Text(
            kutu, wrap="word", undo=True, font=ftema.font(10, root=self),
            relief="flat", bd=0, padx=6, pady=4,
            bg=ftema.ACIK_BG if salt_okunur else ftema.BEYAZ, fg=ftema.METIN,
            insertbackground=ftema.METIN,
        )
        sb = ttk.Scrollbar(kutu, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        if metin:
            self.text.insert("1.0", metin)
        self.text.edit_reset()

        alt = tk.Frame(self, bg=ftema.ACIK_BG)
        alt.pack(fill="x", padx=10, pady=(0, 10))
        if salt_okunur:
            self.text.configure(state="disabled")
            ftema.tk_buton(alt, "Kapat", self.vazgec, rol="ikincil").pack(side="right")
        else:
            tk.Label(
                alt, text="Ctrl+Enter: Uygula · Esc: Vazgeç", bg=ftema.ACIK_BG,
                fg=ftema.IKINCIL, font=ftema.font(8, root=self),
            ).pack(side="left")
            ftema.tk_buton(alt, "Vazgeç", self.vazgec, rol="ikincil").pack(side="right")
            ftema.tk_buton(alt, "Uygula", self.uygula, rol="kaydet").pack(
                side="right", padx=(0, 6)
            )
            self.bind("<Control-Return>", lambda _e: self.uygula() or "break")
        self.bind("<Escape>", lambda _e: self.vazgec())
        self.protocol("WM_DELETE_WINDOW", self.vazgec)
        self.text.focus_set()
        self.text.mark_set("insert", "end-1c")

    def uygula(self) -> None:
        if self.salt_okunur:
            self.vazgec()
            return
        self.result = self.text.get("1.0", "end-1c")
        if self._uygula_fn is not None:
            self._uygula_fn(self.result)
        self.destroy()

    def vazgec(self) -> None:
        self.destroy()


def notu_buyut(parent, text: tk.Text, *, degisti: Callable[[], None] | None = None,
               bekle: bool = True) -> NotBuyutDialog:
    """Not kutusunu geniş pencerede açar; Uygula ile metin kutuya geri yazılır."""

    def _yaz(metin: str) -> None:
        not_yaz(text, metin)
        if degisti is not None:
            degisti()
        try:
            text.focus_set()
        except tk.TclError:
            pass

    dlg = NotBuyutDialog(parent, not_oku(text), salt_okunur=not_kilitli_mi(text), uygula=_yaz)
    if bekle:
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        parent.wait_window(dlg)
    return dlg
