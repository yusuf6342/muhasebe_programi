"""Cari adı kutusunda yazarken otomatik arama ve açılır sonuç listesi.

Arama ``SearchService.search_customers`` (çoklu blok, Türkçe harf / büyük-küçük duyarsız)
ile yapılır; seçim görünen metne değil cari kartının kendisine bağlanır.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

_LOG = logging.getLogger("cari_arama_alani")

MIN_HARF = 2
GECIKME_MS = 220
AZAMI_SONUC = 50
YOKSAYILAN_TUSLAR = frozenset({
    "Up", "Down", "Return", "KP_Enter", "Escape", "Tab", "ISO_Left_Tab", "Left", "Right",
    "Prior", "Next", "Home", "End", "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Caps_Lock", "F10",
})


def cari_ara(metin: str, cari_turu: str, limit: int = AZAMI_SONUC) -> list[Any]:
    from database.search_service import SearchService, tokenize_query

    if len((metin or "").strip()) < MIN_HARF or not tokenize_query(metin):
        return []
    sonuc = SearchService.search_customers(metin, limit=limit, cari_turu=cari_turu, sadece_aktif=True)
    return [x["cari"] for x in sonuc if x.get("cari") is not None]


def _ek_bilgi(cari) -> str:
    parcalar = []
    yer = " / ".join(p for p in ((getattr(cari, "il", None) or "").strip(), (getattr(cari, "ilce", None) or "").strip()) if p)
    if yer:
        parcalar.append(yer)
    vergi = (getattr(cari, "vergi_numarasi", None) or "").strip()
    if vergi:
        parcalar.append(f"VN {vergi}")
    tel = (getattr(cari, "telefon", None) or "").strip()
    if tel:
        parcalar.append(tel)
    return " · ".join(parcalar)


class CariAramaAlani:
    """Entry'ye bağlanan otomatik cari arama listesi.

    ``on_secim(cari)`` kart seçildiğinde, ``on_temizle()`` seçili kartın adı elle
    değiştirildiğinde (eski kimlik bağlı kalmasın diye) çağrılır.
    """

    def __init__(
        self,
        dialog: tk.Misc,
        entry: ttk.Entry,
        *,
        cari_turu: str,
        on_secim: Callable[[Any], None],
        on_temizle: Callable[[], None],
        secili_ad: Callable[[], str],
        on_yeni: Callable[[], None] | None = None,
        kayit_adi: str = "Tedarikçi",
        arka_plan: bool = True,
    ):
        self.dialog = dialog
        self.entry = entry
        self.cari_turu = cari_turu
        self.on_secim = on_secim
        self.on_temizle = on_temizle
        self.secili_ad = secili_ad
        self.on_yeni = on_yeni
        self.kayit_adi = kayit_adi
        self.arka_plan = arka_plan
        self.sonuclar: list[Any] = []
        self.secili = -1
        self.popup: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None
        self.durum: tk.Label | None = None
        self.yeni_btn: tk.Button | None = None
        self._after = None
        self._seq = 0
        self._sonuc_metin = ""
        entry.bind("<KeyRelease>", self._tus, add="+")
        entry.bind("<Down>", self._asagi)
        entry.bind("<Up>", self._yukari)
        entry.bind("<Return>", self._enter)
        entry.bind("<KP_Enter>", self._enter)
        entry.bind("<Escape>", self._esc)
        entry.bind("<FocusOut>", lambda _e: self.dialog.after(200, self._odak_kontrol), add="+")
        try:
            dialog.bind("<Configure>", lambda e: self._konumla() if e.widget is dialog else None, add="+")
            dialog.bind("<Unmap>", lambda e: self.kapat() if e.widget is dialog else None, add="+")
        except tk.TclError:
            pass

    # ─── yazma / arama
    def metin(self) -> str:
        try:
            return (self.entry.get() or "").strip()
        except tk.TclError:
            return ""

    def _tus(self, event=None):
        if event is not None and getattr(event, "keysym", "") in YOKSAYILAN_TUSLAR:
            return None
        if str(self.entry.cget("state")) in ("disabled", "readonly"):
            return None
        metin = self.metin()
        secili = (self.secili_ad() or "").strip()
        if secili and metin != secili:
            self.on_temizle()
        self._iptal()
        if len(metin) < MIN_HARF:
            self._seq += 1
            self.kapat()
            return None
        if secili and metin == secili:
            return None
        self._after = self.dialog.after(GECIKME_MS, lambda m=metin: self.ara(m))
        return None

    def _iptal(self):
        if self._after is not None:
            try:
                self.dialog.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def ara(self, metin: str | None = None, *, senkron: bool | None = None) -> None:
        """Sorguyu başlatır; geç gelen eski sonuç yeni sorgunun listesini değiştirmez."""
        self._after = None
        metin = self.metin() if metin is None else metin
        if metin != self.metin():
            return
        self._seq += 1
        seq = self._seq
        tur = self.cari_turu

        def _is():
            return cari_ara(metin, tur)

        def _tamam(sonuc):
            self.sonuc_uygula(seq, metin, sonuc)

        def _hata(exc):
            _LOG.warning("cari arama hatası: %s", exc)
            if seq == self._seq:
                self._goster([], mesaj=f"Arama yapılamadı: {exc}")

        if senkron is None:
            senkron = not self.arka_plan
        if not senkron:
            from ui_bg import arka_planda

            try:
                arka_planda(self.dialog, _is, on_ok=_tamam, on_err=_hata)
                return
            except RuntimeError:
                pass
        try:
            _tamam(_is())
        except Exception as exc:  # noqa: BLE001
            _hata(exc)

    def sonuc_uygula(self, seq: int, metin: str, sonuc: list[Any]) -> None:
        if seq != self._seq or metin != self.metin():
            return
        try:
            if not self.entry.winfo_exists():
                return
        except tk.TclError:
            return
        self._sonuc_metin = metin
        self.sonuclar = list(sonuc or [])
        self.secili = 0 if self.sonuclar else -1
        self._goster(self.sonuclar, mesaj=None if self.sonuclar else f"{self.kayit_adi} bulunamadı.")

    # ─── liste
    def acik_mi(self) -> bool:
        try:
            return self.popup is not None and bool(self.popup.winfo_exists())
        except tk.TclError:
            return False

    def _olustur(self) -> None:
        pop = tk.Toplevel(self.dialog)
        pop.withdraw()
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        frm = tk.Frame(pop, bg="#0B2A4A", bd=1)
        frm.pack(fill="both", expand=True)
        tree = ttk.Treeview(frm, columns=("kod", "unvan", "ek"), show="headings", height=8, selectmode="browse")
        for cid, baslik, gen, uzat in (
            ("kod", "Kod", 90, False),
            ("unvan", "Ünvan", 300, True),
            ("ek", "Ek Bilgi", 220, True),
        ):
            tree.heading(cid, text=baslik)
            tree.column(cid, width=gen, stretch=uzat, anchor="w")
        sy = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sy.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)
        alt = tk.Frame(frm, bg="#F1F5F9")
        alt.grid(row=1, column=0, columnspan=2, sticky="ew")
        durum = tk.Label(alt, text="", bg="#F1F5F9", fg="#334155", font=("Segoe UI", 8), anchor="w")
        durum.pack(side="left", fill="x", expand=True, padx=4)
        if self.on_yeni is not None:
            self.yeni_btn = tk.Button(
                alt, text=f"Yeni {self.kayit_adi}", relief="flat", bg="#DCFCE7",
                font=("Segoe UI", 8), command=self._yeni,
            )
            self.yeni_btn.pack(side="right", padx=2, pady=1)
        tree.bind("<ButtonRelease-1>", self._tik)
        tree.bind("<Double-1>", self._tik)
        tree.tag_configure("cift", background="#F8FAFC")
        self.popup, self.tree, self.durum = pop, tree, durum

    def _goster(self, sonuclar: list[Any], *, mesaj: str | None = None) -> None:
        try:
            if not self.entry.winfo_exists() or not self.entry.winfo_ismapped():
                return
        except tk.TclError:
            return
        if not self.acik_mi():
            self._olustur()
        tree = self.tree
        assert tree is not None and self.durum is not None
        tree.delete(*tree.get_children())
        for i, cari in enumerate(sonuclar):
            tree.insert(
                "", "end", iid=str(i),
                values=((cari.cari_kodu or ""), (cari.unvan or ""), _ek_bilgi(cari)),
                tags=("cift",) if i % 2 else (),
            )
        bilgi = "↑↓ gezin · Enter seç · Esc kapat · F10 tam liste"
        if len(sonuclar) >= AZAMI_SONUC:
            bilgi = f"İlk {AZAMI_SONUC} sonuç — aramayı daraltın · " + bilgi
        self.durum.configure(text=mesaj or bilgi, fg="#B91C1C" if mesaj else "#334155")
        tree.configure(height=max(1, min(8, len(sonuclar))))
        self._secim_gorsel()
        self._konumla()
        try:
            self.popup.deiconify()
            self.popup.lift()
        except tk.TclError:
            pass

    def _konumla(self) -> None:
        if not self.acik_mi():
            return
        try:
            self.entry.update_idletasks()
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height()
            genislik = max(self.entry.winfo_width(), 560)
            self.popup.update_idletasks()
            yukseklik = self.popup.winfo_reqheight()
            ekran_h = self.entry.winfo_screenheight()
            if y + yukseklik > ekran_h:
                y = max(0, self.entry.winfo_rooty() - yukseklik)
            self.popup.geometry(f"{genislik}x{yukseklik}+{x}+{y}")
        except tk.TclError:
            pass

    def _secim_gorsel(self) -> None:
        if self.tree is None:
            return
        try:
            if 0 <= self.secili < len(self.sonuclar):
                iid = str(self.secili)
                self.tree.selection_set(iid)
                self.tree.see(iid)
            else:
                self.tree.selection_remove(*self.tree.selection())
        except tk.TclError:
            pass

    def kapat(self) -> None:
        pop, self.popup = self.popup, None
        self.tree = self.durum = self.yeni_btn = None
        if pop is not None:
            try:
                pop.destroy()
            except tk.TclError:
                pass

    # ─── klavye / fare
    def _asagi(self, _e=None):
        if not self.acik_mi():
            if len(self.metin()) >= MIN_HARF:
                self._iptal()
                self.ara(self.metin())
            return "break"
        if self.sonuclar:
            self.secili = min(self.secili + 1, len(self.sonuclar) - 1)
            self._secim_gorsel()
        return "break"

    def _yukari(self, _e=None):
        if self.acik_mi() and self.sonuclar:
            self.secili = max(self.secili - 1, 0)
            self._secim_gorsel()
            return "break"
        return None

    def _enter(self, _e=None):
        if self.acik_mi() and self.sonuclar and 0 <= self.secili < len(self.sonuclar):
            if self._sonuc_metin == self.metin():
                self.sec(self.secili)
                return "break"
        return None

    def _esc(self, _e=None):
        if self.acik_mi():
            self.kapat()
            return "break"
        return None

    def _tik(self, event=None):
        if self.tree is None:
            return "break"
        iid = self.tree.identify_row(event.y) if event is not None else ""
        if not iid:
            secim = self.tree.selection()
            iid = secim[0] if secim else ""
        if iid:
            self.sec(int(iid))
        return "break"

    def _yeni(self):
        self.kapat()
        if self.on_yeni is not None:
            self.on_yeni()

    def sec(self, indeks: int) -> None:
        if not (0 <= indeks < len(self.sonuclar)):
            return
        cari = self.sonuclar[indeks]
        self._iptal()
        self._seq += 1
        self.kapat()
        self.on_secim(cari)
        try:
            self.entry.focus_set()
            self.entry.icursor("end")
        except tk.TclError:
            pass

    def _odak_kontrol(self) -> None:
        try:
            odak = self.dialog.focus_get()
        except (tk.TclError, KeyError):
            odak = None
        if odak is self.entry:
            return
        if odak is not None and self.popup is not None and str(odak).startswith(str(self.popup)):
            return
        self.kapat()
