"""Tarih alanları için takvim popup ve saat yardımcıları."""
from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk


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


def saat_kisa_giris_coz(
    metin: str,
    *,
    bos_izinli: bool = True,
    alan_adi: str = "Saat",
) -> str | None:
    """Kısa saat girişini HH:mm'ye çevirir.

    Kabul: ``16``→16:00, ``1643``→16:43, ``9``→09:00, ``930``→09:30,
    ``0905``→09:05, ``16:43``→16:43.

    Boş metin ``bos_izinli`` ise ``None`` (00:00 yapılmaz). Geçersiz değerde
    ValueError; saat başka bir değere “düzeltilmez”.
    """
    ham = (metin or "").strip()
    if not ham:
        if bos_izinli:
            return None
        raise ValueError(f"{alan_adi} boş olamaz.")

    if ":" in ham:
        parcalar = ham.split(":")
        if len(parcalar) != 2 or any(p.strip() == "" for p in parcalar):
            raise ValueError(
                f"{alan_adi} geçersiz. Örnek: 16, 1643, 09:05 veya 16:43."
            )
        try:
            saat = int(parcalar[0].strip())
            dakika = int(parcalar[1].strip())
        except ValueError as hata:
            raise ValueError(
                f"{alan_adi} geçersiz. Örnek: 16, 1643, 09:05 veya 16:43."
            ) from hata
    else:
        rakam = ham.replace(" ", "")
        if not rakam.isdigit():
            raise ValueError(
                f"{alan_adi} geçersiz. Örnek: 16, 1643, 09:05 veya 16:43."
            )
        n = len(rakam)
        if n in (1, 2):
            saat = int(rakam)
            dakika = 0
        elif n == 3:
            saat = int(rakam[0])
            dakika = int(rakam[1:])
        elif n == 4:
            saat = int(rakam[:2])
            dakika = int(rakam[2:])
        else:
            raise ValueError(
                f"{alan_adi} geçersiz. En fazla 4 rakam veya SS:DD girin."
            )

    if not (0 <= saat <= 23 and 0 <= dakika <= 59):
        raise ValueError(
            f"{alan_adi} geçersiz: saat 00–23, dakika 00–59 olmalı "
            f"(girilen: {saat:02d}:{dakika:02d})."
        )
    return f"{saat:02d}:{dakika:02d}"


def saat_alani_bagla(
    entry: ttk.Entry | tk.Entry,
    *,
    bos_izinli: bool = True,
    alan_adi: str = "Teslim saati",
    parent: tk.Misc | None = None,
):
    """FocusOut / Enter / KP_Enter'da biçimlendir; yazarken dokunmaz."""

    def _bicimlendir(event=None):
        try:
            sonuc = saat_kisa_giris_coz(
                entry.get(), bos_izinli=bos_izinli, alan_adi=alan_adi
            )
        except ValueError as hata:
            try:
                ust = parent or entry.winfo_toplevel()
            except tk.TclError:
                ust = None
            messagebox.showwarning(alan_adi, str(hata), parent=ust)
            if event is not None and getattr(event, "keysym", "") in (
                "Return",
                "KP_Enter",
            ):
                return "break"
            return None
        hedef = "" if sonuc is None else sonuc
        try:
            guncel = entry.get()
        except tk.TclError:
            return None
        if guncel.strip() == hedef:
            return None
        try:
            entry.delete(0, "end")
            if hedef:
                entry.insert(0, hedef)
        except tk.TclError:
            pass
        return None

    entry.bind("<FocusOut>", _bicimlendir, add="+")
    entry.bind("<Return>", _bicimlendir, add="+")
    entry.bind("<KP_Enter>", _bicimlendir, add="+")
    return _bicimlendir


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


_acik_takvim: TakvimPopup | None = None


def takvim_ac(parent, entry, on_select=None):
    """Tek takvim; zaten açıksa yenisini açmaz."""
    global _acik_takvim
    if _acik_takvim is not None:
        try:
            if _acik_takvim.winfo_exists():
                _acik_takvim.lift()
                _acik_takvim.focus_force()
                return _acik_takvim
        except tk.TclError:
            _acik_takvim = None
    popup = TakvimPopup(parent, entry, on_select=on_select)
    _acik_takvim = popup

    def _temizle(_e=None, p=popup):
        global _acik_takvim
        if _acik_takvim is p:
            _acik_takvim = None

    popup.bind("<Destroy>", _temizle, add="+")
    # Entry yakınına konumlandır
    try:
        popup.update_idletasks()
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height() + 2
        popup.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    return popup


def takvim_butonu(parent, entry, on_select=None, *, text="Takvim", width=8):
    """Entry yanına takvim butonu ekler."""
    btn = ttk.Button(
        parent,
        text=text,
        width=width,
        command=lambda: takvim_ac(parent.winfo_toplevel(), entry, on_select),
    )
    btn.pack(side="left", padx=(4, 0))
    return btn


def takvim_entry_bagla(entry, on_select=None):
    """Tarih alanına tek tık → yakında takvim; Esc iptal; klavye yazımı korunur."""

    def _tikla(_event=None):
        try:
            top = entry.winfo_toplevel()
        except tk.TclError:
            return
        # break yok: imleç alana gelsin, Esc sonrası yazılabilir kalsın
        top.after_idle(lambda: takvim_ac(top, entry, on_select=on_select))

    entry.bind("<Button-1>", _tikla, add="+")
    return entry


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
