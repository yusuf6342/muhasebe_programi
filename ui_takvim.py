"""Tarih alanları için takvim popup ve saat yardımcıları."""
from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk


def saat_varsayilan(mevcut: str | None = None) -> str:
    metin = (mevcut or "").strip()
    if metin:
        return metin
    return datetime.now().strftime("%H:%M")


def saat_dogrula(metin: str) -> str:
    metin = (metin or "").strip()
    if not metin:
        return datetime.now().strftime("%H:%M")
    try:
        datetime.strptime(metin, "%H:%M")
    except ValueError as hata:
        raise ValueError("İşlem saati SS:DD formatında olmalıdır (ör. 14:35).") from hata
    return metin


def _tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    if not metin:
        return date.today()
    try:
        return datetime.strptime(metin, "%d.%m.%Y").date()
    except ValueError:
        return date.today()


class TakvimPopup(tk.Toplevel):
    def __init__(self, parent, entry: ttk.Entry | tk.Entry, on_select=None):
        super().__init__(parent)
        self.entry = entry
        self.on_select = on_select
        self.title("Takvim")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        secili = _tarih_oku(entry.get())
        self.yil = secili.year
        self.ay = secili.month

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Button(ust, text="<", width=3, command=self._onceki).pack(side="left")
        self.baslik = ttk.Label(ust, font=("Segoe UI", 10, "bold"))
        self.baslik.pack(side="left", expand=True)
        ttk.Button(ust, text=">", width=3, command=self._sonraki).pack(side="right")

        self.gunler = ttk.Frame(self, padding=(8, 0, 8, 8))
        self.gunler.pack()
        self._ciz()

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Bugün", command=self._bugun).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + 40
            y = parent.winfo_rooty() + 40
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _onceki(self):
        if self.ay == 1:
            self.ay = 12
            self.yil -= 1
        else:
            self.ay -= 1
        self._ciz()

    def _sonraki(self):
        if self.ay == 12:
            self.ay = 1
            self.yil += 1
        else:
            self.ay += 1
        self._ciz()

    def _bugun(self):
        self._sec(date.today())

    def _ciz(self):
        for w in self.gunler.winfo_children():
            w.destroy()
        aylar = (
            "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
        )
        self.baslik.configure(text=f"{aylar[self.ay - 1]} {self.yil}")
        for i, gun in enumerate(("Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz")):
            ttk.Label(self.gunler, text=gun, width=4, anchor="center").grid(row=0, column=i, padx=1, pady=1)

        cal = calendar.Calendar(firstweekday=0)
        satir = 1
        for hafta in cal.monthdayscalendar(self.yil, self.ay):
            for sutun, gun in enumerate(hafta):
                if gun == 0:
                    ttk.Label(self.gunler, text="", width=4).grid(row=satir, column=sutun)
                    continue
                gun_tarihi = date(self.yil, self.ay, gun)
                btn = ttk.Button(
                    self.gunler,
                    text=str(gun),
                    width=4,
                    command=lambda t=gun_tarihi: self._sec(t),
                )
                btn.grid(row=satir, column=sutun, padx=1, pady=1)
            satir += 1

    def _sec(self, secilen: date):
        self.entry.configure(state="normal")
        self.entry.delete(0, "end")
        self.entry.insert(0, secilen.strftime("%d.%m.%Y"))
        if self.on_select:
            self.on_select()
        self.destroy()


def takvim_ac(parent, entry, on_select=None):
    TakvimPopup(parent, entry, on_select=on_select)


def takvim_butonu(parent, entry, on_select=None):
    """Entry yanına takvim butonu ekler."""
    btn = ttk.Button(
        parent,
        text="Takvim",
        width=8,
        command=lambda: takvim_ac(parent.winfo_toplevel(), entry, on_select),
    )
    btn.pack(side="left", padx=(4, 0))
    return btn


def tarih_alani(parent, satir, baslik, alan, deger, girdiler, on_select=None, sutun=0, genislik=28):
    """Label + tarih entry + Takvim butonu."""
    ttk.Label(parent, text=baslik).grid(row=satir, column=sutun, padx=8, pady=5, sticky="w")
    cerceve = ttk.Frame(parent)
    cerceve.grid(row=satir, column=sutun + 1, padx=8, pady=5, sticky="ew")
    entry = ttk.Entry(cerceve, width=genislik)
    entry.pack(side="left", fill="x", expand=True)
    entry.insert(0, deger)
    takvim_butonu(cerceve, entry, on_select=on_select)
    girdiler[alan] = entry
    return entry
