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


def _tarih_oku(metin: str) -> date | None:
    """Entry metninden tarih; boş veya geçersiz → None (takvim bugünü gösterir, yazmaz)."""
    metin = (metin or "").strip()
    if not metin:
        return None
    try:
        return datetime.strptime(metin, "%d.%m.%Y").date()
    except ValueError:
        return None


def _ekrana_sigdir(win: tk.Toplevel, x: int, y: int) -> None:
    """Popup'ı ekran dışına taşmayacak şekilde konumlandırır."""
    try:
        win.update_idletasks()
        w = max(win.winfo_reqwidth(), win.winfo_width())
        h = max(win.winfo_reqheight(), win.winfo_height())
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, min(int(x), max(0, sw - w - 8)))
        y = max(0, min(int(y), max(0, sh - h - 8)))
        win.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


class TakvimPopup(tk.Toplevel):
    def __init__(self, parent, entry: ttk.Entry | tk.Entry, on_select=None):
        super().__init__(parent)
        self.entry = entry
        self.on_select = on_select
        self._secildi = False
        self._arka = None
        self.title("Takvim")
        self.resizable(False, False)
        self.transient(parent)
        # grab yok: dışarı tıklayınca (arka plan) kapanır; Esc/dışarı seçim yazmaz

        secili = _tarih_oku(entry.get())
        bugun = date.today()
        acilis = secili or bugun
        self.yil = acilis.year
        self.ay = acilis.month
        self._vurgulu = secili  # boş alanda vurgulama yok

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
        ttk.Button(alt, text="Kapat", command=self._iptal).pack(side="right")

        self.bind("<Escape>", lambda _e: self._iptal())
        self.protocol("WM_DELETE_WINDOW", self._iptal)
        self.after(1, self._disari_katman)

    def _disari_katman(self):
        """Tam ekran saydam katman: dışarı tıklamada seçimsiz kapat (bind_all yok)."""
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            arka = tk.Toplevel(self.master)
            arka.withdraw()
            arka.overrideredirect(True)
            arka.geometry(f"{sw}x{sh}+0+0")
            try:
                arka.attributes("-alpha", 0.01)
            except tk.TclError:
                pass
            arka.bind("<Button-1>", lambda _e: self._iptal())
            arka.deiconify()
            arka.lower(self)
            self.lift()
            self.focus_force()
            self._arka = arka
        except tk.TclError:
            self._arka = None

    def _disari_kaldir(self):
        arka = self._arka
        self._arka = None
        if arka is None:
            return
        try:
            if arka.winfo_exists():
                arka.destroy()
        except tk.TclError:
            pass

    def _iptal(self):
        """Seçim yok — entry değeri korunur."""
        self._disari_kaldir()
        try:
            self.destroy()
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
                if self._vurgulu and gun_tarihi == self._vurgulu:
                    try:
                        btn.state(["pressed"])
                    except tk.TclError:
                        pass
                btn.grid(row=satir, column=sutun, padx=1, pady=1)
            satir += 1

    def _sec(self, secilen: date):
        self._secildi = True
        try:
            self.entry.configure(state="normal")
            self.entry.delete(0, "end")
            self.entry.insert(0, secilen.strftime("%d.%m.%Y"))
        except tk.TclError:
            pass
        if self.on_select:
            try:
                self.on_select()
            except Exception:
                pass
        self._disari_kaldir()
        try:
            self.destroy()
        except tk.TclError:
            pass


_acik_takvim: TakvimPopup | None = None


def takvim_ac(parent, entry, on_select=None):
    """Tek takvim; zaten açıksa yenisini açmaz. Boş entry'ye tarih yazmaz."""
    global _acik_takvim
    if _acik_takvim is not None:
        try:
            if _acik_takvim.winfo_exists():
                # Aynı entry için öne getir; farklı entry ise eskisini kapatıp yenisini aç
                if getattr(_acik_takvim, "entry", None) is entry:
                    # Aynı entry: yenisini açma. focus_force Destroy tetikleyebilir;
                    # lift + yumuşak odak yeterli; global tutarlı kalsın.
                    try:
                        _acik_takvim.lift()
                        if _acik_takvim.winfo_exists():
                            try:
                                _acik_takvim.focus_set()
                            except tk.TclError:
                                pass
                            return _acik_takvim
                    except tk.TclError:
                        _acik_takvim = None
                    else:
                        _acik_takvim = None
                try:
                    _acik_takvim._iptal()
                except Exception:
                    try:
                        _acik_takvim.destroy()
                    except tk.TclError:
                        pass
                _acik_takvim = None
        except tk.TclError:
            _acik_takvim = None
    popup = TakvimPopup(parent, entry, on_select=on_select)
    _acik_takvim = popup

    def _temizle(_e=None, p=popup):
        global _acik_takvim
        if _acik_takvim is p:
            _acik_takvim = None
        try:
            p._disari_kaldir()
        except Exception:
            pass

    popup.bind("<Destroy>", _temizle, add="+")
    try:
        popup.update_idletasks()
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height() + 2
        _ekrana_sigdir(popup, x, y)
    except tk.TclError:
        pass
    return popup


class _TakvimYerTutucu(ttk.Frame):
    """Eski Takvim düğmesi yerine görünmez çerçeve.

    Birçok ekran hâlâ ``takvim_butonu(...).configure(state=...)`` çağırıyor;
    ``ttk.Frame`` ``-state`` desteklemez → TclError. state yok sayılır.
    """

    def configure(self, cnf=None, **kw):  # noqa: A003 — Tk API
        if cnf == "state":
            return None
        if isinstance(cnf, dict):
            cnf = {k: v for k, v in cnf.items() if k != "state"}
        kw.pop("state", None)
        try:
            if cnf is None:
                return super().configure(**kw) if kw else None
            if isinstance(cnf, dict):
                birlesik = {**cnf, **kw}
                return super().configure(**birlesik) if birlesik else None
            return super().configure(cnf, **kw)
        except tk.TclError:
            return None

    config = configure


def takvim_butonu(parent, entry, on_select=None, *, text="Takvim", width=8):
    """Geriye dönük API: ayrı Takvim düğmesi eklemez; alana tıklayınca takvim açılır.

    Eski çağrılarda `.pack()` zinciri kırılmasın diye görünmez 0 boyutlu çerçeve döner.
    """
    takvim_entry_bagla(entry, on_select=on_select)
    placeholder = _TakvimYerTutucu(parent, width=0, height=0)
    try:
        placeholder.pack_propagate(False)
    except tk.TclError:
        pass
    return placeholder


def takvim_entry_bagla(entry, on_select=None):
    """Tarih alanına tek tık → yakında takvim; Esc iptal; klavye yazımı korunur.

    Programatik doldurma veya takvimden dönen odak yeniden açmaz; yalnız Button-1.
    Aynı alan için tek takvim; zaten açıksa yenisini açmaz (takvim_ac).
    """

    def _tikla(_event=None):
        global _acik_takvim
        try:
            top = entry.winfo_toplevel()
        except tk.TclError:
            return
        if _acik_takvim is not None:
            try:
                if _acik_takvim.winfo_exists() and getattr(_acik_takvim, "entry", None) is entry:
                    return
            except tk.TclError:
                pass
        # break yok: imleç alana gelsin, Esc sonrası yazılabilir kalsın
        top.after_idle(lambda: takvim_ac(top, entry, on_select=on_select))

    entry.bind("<Button-1>", _tikla, add="+")
    return entry


def tarih_alani(
    parent,
    satir,
    baslik,
    alan,
    deger,
    girdiler,
    on_select=None,
    sutun=0,
    genislik=28,
    *,
    takvim_dugmesi: bool = False,
):
    """Label + tarih entry; varsayılan: Takvim düğmesi yok, alana tıkla → takvim."""
    ttk.Label(parent, text=baslik).grid(row=satir, column=sutun, padx=8, pady=5, sticky="w")
    cerceve = ttk.Frame(parent)
    cerceve.grid(row=satir, column=sutun + 1, padx=8, pady=5, sticky="ew")
    entry = ttk.Entry(cerceve, width=genislik)
    entry.pack(side="left", fill="x", expand=True)
    entry.insert(0, deger)
    if takvim_dugmesi:
        # Bilinçli eski davranış (nadir); yine de düğme yerine tık bağlanır
        takvim_entry_bagla(entry, on_select=on_select)
    else:
        takvim_entry_bagla(entry, on_select=on_select)
    girdiler[alan] = entry
    return entry
