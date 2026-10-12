"""GİRİŞ ekranı: satış, tahsilat, ödeme yükü ve tedarikçi açık borcu özeti (sarı-lacivert).

Hesap ``database.giris_ozet_service`` içindedir; bu modül yalnız gösterir. Ana kart, bölüm tablosu ve
ayrıntı listesi aynı hesap sonucunu kullanır. Eski giriş ekranı ``ana_panel_ui.eski_giris_dashboard_goster``.
"""

from __future__ import annotations

import csv
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk

from ana_panel_tema import (
    ACIK_BG,
    BASARI,
    BEYAZ,
    CIZGI,
    FONT_ALT,
    FONT_KUCUK,
    FONT_UI,
    FONT_UI_BOLD,
    KOYU_LACIVERT,
    LACIVERT,
    LACIVERT_HOVER,
    METIN,
    PASIF,
    SARI,
    SARI_HOVER,
    UYARI,
    para_tr,
    sayi_tr,
)
from database import giris_ozet_service as go

DAR_ESIK = 1180
MIN_GENISLIK = 720
YOKLAMA_MS = 15000
SATIR_ACIK = "#F7F9FB"
SATIR_TOPLAM = "#FFF6D6"
FONT_KART_DEGER = ("Segoe UI", 15, "bold")
FONT_BOLUM = ("Segoe UI", 11, "bold")

AYRINTI_KOLONLARI = (
    ("kaynak", "Kaynak", 150, "w"),
    ("belge_no", "Belge / hesap", 150, "w"),
    ("tarih", "Tarih", 82, "w"),
    ("vade", "Vade", 82, "w"),
    ("cari", "Cari / banka", 190, "w"),
    ("yontem", "Yöntem", 110, "w"),
    ("aciklama", "Açıklama", 230, "w"),
    ("tutar", "Tutar", 110, "e"),
)


def _tl(v) -> str:
    return "—" if v is None else para_tr(v)


def _yuzde(v, mesaj: str = "") -> str:
    if v is None:
        return mesaj or "—"
    return ("-%" if v < 0 else "%") + sayi_tr(abs(v), 2)


def _tarih_tr(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError("Tarih GG.AA.YYYY biçiminde olmalı.")


def _toplam(kalemler) -> Decimal:
    return sum((Decimal(str(k["tutar"])) for k in kalemler), Decimal("0"))


TABLO_STILI = "Giris.Treeview"


def tablo_stili(widget) -> str:
    """Liste stili. Windows 'vista' teması başlık zeminini yok saydığı için başlık metni lacivert."""
    stil = ttk.Style(widget)
    stil.configure(TABLO_STILI, font=FONT_ALT, rowheight=24, background=BEYAZ, fieldbackground=BEYAZ,
                   foreground=METIN)
    stil.configure(TABLO_STILI + ".Heading", font=FONT_UI_BOLD, foreground=LACIVERT)
    stil.map(TABLO_STILI, background=[("selected", SARI)], foreground=[("selected", KOYU_LACIVERT)])
    return TABLO_STILI


def _buton(parent, metin, komut, *, vurgu=False, **kw):
    return tk.Button(
        parent, text=metin, command=komut, relief="flat", bd=0, cursor="hand2", font=FONT_ALT,
        bg=SARI if vurgu else BEYAZ, fg=KOYU_LACIVERT if vurgu else LACIVERT,
        activebackground=SARI_HOVER if vurgu else ACIK_BG, highlightthickness=1,
        highlightbackground=SARI if vurgu else CIZGI, padx=kw.pop("padx", 12), pady=kw.pop("pady", 6), **kw)


# ----------------------------------------------------------------------------- ayrıntı listesi
class AyrintiPenceresi(tk.Toplevel):
    """Kalem listesi; alt toplam ekrandaki rakamla aynı kapsamdır. CSV dışa aktarma."""

    def __init__(self, parent, baslik: str, kalemler: list[dict], *, aciklama: str = ""):
        super().__init__(parent)
        self.title(baslik)
        self.configure(bg=ACIK_BG)
        self.geometry("1080x520")
        self.minsize(640, 320)
        self.transient(parent.winfo_toplevel())
        self._baslik = baslik
        self._kalemler = kalemler

        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(ust, text=baslik, bg=LACIVERT, fg=BEYAZ, font=FONT_BOLUM).pack(side="left", padx=14, pady=8)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        if aciklama:
            tk.Label(self, text=aciklama, bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK, justify="left",
                     wraplength=1000).pack(anchor="w", padx=14, pady=(6, 0))

        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(side="bottom", fill="x", padx=12, pady=(0, 10))
        tk.Label(alt, text=f"{sayi_tr(len(kalemler))} kayıt · Toplam {para_tr(_toplam(kalemler))}",
                 bg=ACIK_BG, fg=LACIVERT, font=FONT_UI_BOLD).pack(side="left")
        _buton(alt, "Kapat", self.destroy).pack(side="right", padx=(6, 0))
        _buton(alt, "CSV olarak kaydet", self.csv_kaydet, vurgu=True).pack(side="right")

        orta = tk.Frame(self, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        orta.pack(fill="both", expand=True, padx=12, pady=8)
        self.tablo = ttk.Treeview(orta, columns=[k[0] for k in AYRINTI_KOLONLARI], show="headings",
                                  style=tablo_stili(self))
        for kod, ad, gen, hiza in AYRINTI_KOLONLARI:
            self.tablo.heading(kod, text=ad, anchor=hiza)
            self.tablo.column(kod, width=gen, anchor=hiza, stretch=kod in ("aciklama", "cari"))
        dsb = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        ysb = ttk.Scrollbar(orta, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dsb.set, xscrollcommand=ysb.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dsb.grid(row=0, column=1, sticky="ns")
        ysb.grid(row=1, column=0, sticky="ew")
        orta.rowconfigure(0, weight=1)
        orta.columnconfigure(0, weight=1)
        self.tablo.tag_configure("cift", background=SATIR_ACIK)
        self.tablo.tag_configure("tahmini", foreground=PASIF)
        for i, k in enumerate(self._satirlar()):
            etiket = ["cift"] if i % 2 else []
            if kalemler[i].get("tahmini"):
                etiket.append("tahmini")
            self.tablo.insert("", "end", values=k, tags=tuple(etiket))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _satirlar(self) -> list[tuple]:
        out = []
        for k in self._kalemler:
            aciklama = k.get("aciklama") or ""
            if k.get("tahmini") and "tahmini" not in aciklama:
                aciklama = (aciklama + " · tahmini").strip(" ·")
            out.append((k.get("kaynak", ""), k.get("belge_no", ""), _tarih_tr(k.get("tarih")),
                        _tarih_tr(k.get("vade")) or ("Vadesiz" if "vade" in k and k.get("satir") else ""),
                        k.get("cari", ""), k.get("yontem", ""), aciklama, para_tr(k.get("tutar"))))
        return out

    def csv_kaydet(self) -> None:
        ad = "".join(c if c.isalnum() else "_" for c in self._baslik)[:60]
        yol = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile=f"{ad}.csv",
                                           filetypes=[("CSV", "*.csv")])
        if not yol:
            return
        try:
            with open(yol, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow([k[1] for k in AYRINTI_KOLONLARI])
                w.writerows(self._satirlar())
                w.writerow(["Toplam", "", "", "", "", "", "", para_tr(_toplam(self._kalemler))])
        except OSError as hata:
            messagebox.showerror("CSV", f"Dosya yazılamadı:\n{hata}", parent=self)
            return
        messagebox.showinfo("CSV", f"{len(self._kalemler)} kayıt kaydedildi.", parent=self)


# ----------------------------------------------------------------------------- bölüm kutusu
class _Kutu(tk.Frame):
    def __init__(self, parent, baslik: str):
        super().__init__(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        self.ust = tk.Frame(self, bg=BEYAZ)
        self.ust.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(self.ust, text=baslik, bg=BEYAZ, fg=LACIVERT, font=FONT_BOLUM).pack(side="left")
        self.durum_lbl = tk.Label(self.ust, text="", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK)
        self.durum_lbl.pack(side="left", padx=8)
        self.sag = tk.Frame(self.ust, bg=BEYAZ)
        self.sag.pack(side="right")
        self.govde = tk.Frame(self, bg=BEYAZ)
        self.govde.pack(fill="x", padx=12, pady=(0, 4))
        self.not_f = tk.Frame(self, bg=BEYAZ)
        self.not_f.pack(fill="x", padx=12, pady=(0, 10))
        self._sarma = 0
        self.bind("<Configure>", self._sar)

    def _sar(self, e):
        # Kutu genişliği yerleşimden gelir; metin genişliği ondan küçük tutulur, aksi halde
        # <Configure> → wraplength → yeniden boyut döngüsü oluşur.
        gen = max(200, e.width - 34)
        if abs(gen - self._sarma) < 6:
            return
        self._sarma = gen
        for w in self.not_f.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(wraplength=gen)

    def temizle(self):
        for f in (self.govde, self.not_f):
            for w in f.winfo_children():
                w.destroy()

    def durum(self, metin: str, renk=PASIF):
        self.durum_lbl.configure(text=metin, fg=renk)

    def mesaj(self, metin: str, renk=PASIF):
        tk.Label(self.govde, text=metin, bg=BEYAZ, fg=renk, font=FONT_UI, justify="left").pack(anchor="w", pady=8)

    def notlar(self, uyarilar=(), notlar=()):
        gen = self._sarma or max(200, self.winfo_width() - 34)
        for u in uyarilar:
            tk.Label(self.not_f, text="Uyarı: " + u, bg=BEYAZ, fg=UYARI, font=FONT_KUCUK, justify="left",
                     anchor="w", wraplength=gen).pack(fill="x", anchor="w")
        for n in notlar:
            tk.Label(self.not_f, text=n, bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, justify="left", anchor="w",
                     wraplength=gen).pack(fill="x", anchor="w")


def _tablo(parent, basliklar: list[str], satirlar: list[list], *, toplam_satirlari=(), ilk_gen=26):
    """Etiket tablosu. Hücre: metin ya da {"m": metin, "cmd": fn, "renk": .., "kalin": ..}. Sayılar sağa yaslı."""
    t = tk.Frame(parent, bg=BEYAZ)
    t.pack(fill="x")
    t.columnconfigure(0, weight=3, minsize=ilk_gen * 6)
    for i in range(1, len(basliklar)):
        t.columnconfigure(i, weight=2, uniform="sayi", minsize=86)
    for c, b in enumerate(basliklar):
        tk.Label(t, text=b, bg=LACIVERT, fg=BEYAZ, font=FONT_KUCUK, anchor="w" if c == 0 else "e", padx=6, pady=4,
                 justify="right" if c else "left").grid(row=0, column=c, sticky="nsew")
    for r, satir in enumerate(satirlar, start=1):
        toplam = (r - 1) in toplam_satirlari
        bg = SATIR_TOPLAM if toplam else (SATIR_ACIK if r % 2 == 0 else BEYAZ)
        for c, h in enumerate(satir):
            h = h if isinstance(h, dict) else {"m": h}
            kalin = toplam or h.get("kalin")
            renk = h.get("renk") or (METIN if c == 0 else LACIVERT)
            lbl = tk.Label(t, text=h.get("m", ""), bg=bg, fg=renk, anchor="w" if c == 0 else "e", padx=6, pady=3,
                           font=FONT_UI_BOLD if kalin else FONT_ALT, justify="left" if c == 0 else "right",
                           wraplength=0 if c == 0 else 130)
            lbl.grid(row=r, column=c, sticky="nsew")
            if h.get("cmd"):
                lbl.configure(cursor="hand2", font=(FONT_UI_BOLD if kalin else FONT_ALT) + ("underline",))
                lbl.bind("<Button-1>", lambda _e, f=h["cmd"]: f())
    return t


# ----------------------------------------------------------------------------- ana panel
class GirisPaneli(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ACIK_BG)
        self.app = app
        self._istek = 0
        self._calisan: tuple | None = None
        self._sonuc: dict | None = None
        self._sayac = None
        self._tek_sutun: bool | None = None
        self._takvim_gorunum = tk.StringVar(value="takvim")
        self._subeler: dict[str, int | None] = {"Tümü": None}
        self._ust_bar()
        self._kaydirma()
        self._govde()
        self.after(50, lambda: self.yenile())
        self.after(YOKLAMA_MS, self._yokla)

    # --- üst bar ---
    def _ust_bar(self):
        from database.session_manager import oturum

        bar = tk.Frame(self, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        bar.pack(fill="x")
        sol = tk.Frame(bar, bg=BEYAZ)
        sol.pack(side="left", padx=14, pady=8)
        tk.Label(sol, text="GİRİŞ", bg=BEYAZ, fg=LACIVERT, font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Frame(sol, bg=SARI, width=3, height=22).pack(side="left", padx=10)
        tk.Label(sol, text=oturum.firma_unvan or "", bg=BEYAZ, fg=METIN, font=FONT_UI_BOLD).pack(side="left")

        sag = tk.Frame(bar, bg=BEYAZ)
        sag.pack(side="right", padx=12, pady=6)
        self.yenile_btn = _buton(sag, "Yenile", lambda: self.yenile(zorla=True), vurgu=True, padx=16)
        self.yenile_btn.pack(side="right", padx=(8, 0))
        _buton(sag, "Eski giriş ekranı", self._eski_ekran).pack(side="right", padx=(8, 0))

        orta = tk.Frame(bar, bg=BEYAZ)
        orta.pack(side="right", padx=8)
        tk.Label(orta, text="Rapor tarihi", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK).pack(side="left")
        self.tarih_e = ttk.Entry(orta, width=11)
        self.tarih_e.insert(0, _tarih_tr(date.today()))
        self.tarih_e.pack(side="left", padx=(4, 0))
        self.tarih_e.bind("<Return>", lambda _e: self._tarih_degisti())
        try:
            from ui_takvim import takvim_butonu

            takvim_butonu(orta, self.tarih_e, on_select=lambda *_a: self._tarih_degisti(), width=7)
        except Exception:  # noqa: BLE001
            pass
        tk.Label(orta, text="Şube", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK).pack(side="left", padx=(12, 4))
        self.sube_cb = ttk.Combobox(orta, values=["Tümü"], state="readonly", width=16)
        self.sube_cb.set("Tümü")
        self.sube_cb.pack(side="left")
        self.sube_cb.bind("<<ComboboxSelected>>", lambda _e: self.yenile())
        try:
            for sid, ad in go.subeler():
                self._subeler[ad] = sid
            self.sube_cb.configure(values=list(self._subeler))
        except Exception:  # noqa: BLE001 — şube tablosu yoksa yalnız Tümü
            pass

        durum = tk.Frame(self, bg=ACIK_BG)
        durum.pack(fill="x", padx=16, pady=(6, 0))
        self.durum_lbl = tk.Label(durum, text="Hazırlanıyor…", bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK)
        self.durum_lbl.pack(side="left")
        self.bayat_lbl = tk.Label(durum, text="", bg=ACIK_BG, fg=UYARI, font=FONT_UI_BOLD)
        self.bayat_lbl.pack(side="left", padx=10)

    # --- kaydırma ---
    def _kaydirma(self):
        dis = tk.Frame(self, bg=ACIK_BG)
        dis.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(dis, bg=ACIK_BG, highlightthickness=0)
        dsb = ttk.Scrollbar(dis, orient="vertical", command=self.canvas.yview)
        ysb = ttk.Scrollbar(dis, orient="horizontal", command=self.canvas.xview)
        self.ic = tk.Frame(self.canvas, bg=ACIK_BG)
        self.ic.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._pencere = self.canvas.create_window((0, 0), window=self.ic, anchor="nw")
        self.canvas.configure(yscrollcommand=dsb.set, xscrollcommand=ysb.set)
        dsb.pack(side="right", fill="y")
        ysb.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._boyut)

        def tekerlek(e):
            if self.canvas.winfo_ismapped():
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", tekerlek))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))
        self.ic.bind("<Destroy>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _boyut(self, e):
        self.canvas.itemconfigure(self._pencere, width=max(e.width, MIN_GENISLIK))
        tek = e.width < DAR_ESIK
        if tek != self._tek_sutun:
            self._tek_sutun = tek
            self._yerlestir()

    # --- gövde ---
    def _govde(self):
        p = tk.Frame(self.ic, bg=ACIK_BG)
        p.pack(fill="both", expand=True, padx=14, pady=10)
        self.kartlar_f = tk.Frame(p, bg=ACIK_BG)
        self.kartlar_f.pack(fill="x")
        self.kartlar = [self._kart(i, b) for i, b in enumerate(
            ("Bugün net satış", "Bu ay net satış", "Likit varlıklar", "Bu ay sonu birikimli ödeme yükü"))]

        self.orta_f = tk.Frame(p, bg=ACIK_BG)
        self.orta_f.pack(fill="x", pady=(10, 0))
        self.k_satis = _Kutu(self.orta_f, "Satışlar")
        self.k_tahsilat = _Kutu(self.orta_f, "Tahsilatlar ve cari işlemler")
        self.k_borc = _Kutu(p, "Borçlar ve ödeme yükü")
        self.k_tedarikci = _Kutu(p, "Tedarikçi açık borcu")
        for k in (self.k_borc, self.k_tedarikci):
            k.pack(fill="x", pady=(0, 10))
        for deger, ad in (("takvim", "Ödeme takvimi"), ("bakiye", "Borç bakiyeleri")):
            tk.Radiobutton(self.k_borc.sag, text=ad, value=deger, variable=self._takvim_gorunum, indicatoron=False,
                           bg=BEYAZ, fg=LACIVERT, selectcolor=SARI, activebackground=SARI_HOVER, relief="flat",
                           bd=0, padx=10, pady=3, font=FONT_KUCUK, highlightthickness=1,
                           highlightbackground=CIZGI, command=self._borc_ciz).pack(side="left", padx=(4, 0))

        self.k_hizli = _Kutu(p, "Hızlı işlemler")
        self.k_hizli.pack(fill="x", pady=(0, 10))
        self._hizli_islemler()
        self._yerlestir()

    def _kart(self, i, baslik):
        k = tk.Frame(self.kartlar_f, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI, cursor="hand2")
        tk.Frame(k, bg=SARI if i in (0, 1) else LACIVERT, height=3).pack(fill="x")
        g = tk.Frame(k, bg=BEYAZ)
        g.pack(fill="both", expand=True, padx=12, pady=8)
        tk.Label(g, text=baslik, bg=BEYAZ, fg=PASIF, font=FONT_ALT).pack(anchor="w")
        deger = tk.Label(g, text="…", bg=BEYAZ, fg=LACIVERT, font=FONT_KART_DEGER)
        deger.pack(anchor="w", pady=(2, 0))
        alt = tk.Label(g, text="Yükleniyor…", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, justify="left", anchor="w")
        alt.pack(fill="x", anchor="w")
        rozet = tk.Label(g, text="", bg=BEYAZ, fg=UYARI, font=FONT_KUCUK)
        rozet.pack(anchor="w")
        kayit = {"cerceve": k, "deger": deger, "alt": alt, "rozet": rozet, "cmd": None, "sarma": 0}

        def sar(e):
            gen = max(120, e.width - 30)
            if abs(gen - kayit["sarma"]) >= 6:
                kayit["sarma"] = gen
                alt.configure(wraplength=gen)

        k.bind("<Configure>", sar)

        def tikla(_e=None):
            if kayit["cmd"]:
                kayit["cmd"]()

        for w in (k, g, deger, alt, rozet):
            w.bind("<Button-1>", tikla)
        return kayit

    def _yerlestir(self):
        tek = bool(self._tek_sutun)
        for i, k in enumerate(self.kartlar):
            r, c = (divmod(i, 2) if tek else (0, i))
            k["cerceve"].grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
        for c in range(4):
            bos = tek and c >= 2
            self.kartlar_f.columnconfigure(c, weight=0 if bos else 1, uniform="" if bos else "kart")
        f, a, b = self.orta_f, self.k_satis, self.k_tahsilat
        a.grid_forget()
        b.grid_forget()
        if tek:
            a.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
            b.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
            f.columnconfigure(0, weight=1, uniform="")
            f.columnconfigure(1, weight=0, uniform="")
        else:
            a.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=(0, 10))
            b.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=(0, 10))
            f.columnconfigure(0, weight=1, uniform="iki")
            f.columnconfigure(1, weight=1, uniform="iki")

    # --- hızlı işlemler (eski giriş kısayolları korunur) ---
    def _hizli_islemler(self):
        from ana_panel_ui import HIZLI_ISLEMLER, _hizli_islem_calistir

        g = self.k_hizli.govde
        ust = tk.Frame(g, bg=BEYAZ)
        ust.pack(fill="x", pady=(2, 6))
        app = self.app
        for metin, komut in (("Satış faturası", lambda: app._menu_islemi(app.hizli_fatura_ac)),
                             ("Tahsilat", lambda: app._menu_islemi(app.tahsilat_makbuzu_ac)),
                             ("Ödeme", lambda: app._menu_islemi(app.odeme_makbuzu_ac)),
                             ("Cari listesi", self._cari_listesi)):
            _buton(ust, metin, komut, vurgu=True, padx=14).pack(side="left", padx=(0, 6))
        _buton(ust, "Sabit gider planları", self._sabit_gider).pack(side="left", padx=(12, 0))
        alt = tk.Frame(g, bg=BEYAZ)
        alt.pack(fill="x")
        for i, (etiket, kod) in enumerate(HIZLI_ISLEMLER):
            _buton(alt, etiket, lambda k=kod: _hizli_islem_calistir(app, k), pady=4).grid(
                row=i // 5, column=i % 5, sticky="ew", padx=3, pady=3)
        for c in range(5):
            alt.columnconfigure(c, weight=1)
        self.soz_f = tk.Frame(g, bg=BEYAZ)
        self.soz_f.pack(fill="x", pady=(6, 0))

    def _cari_listesi(self):
        app = self.app
        if not hasattr(app, "cariler_goster"):
            return
        app.sayfa_goster("satislar", ust_duzey=True)

        def ac(deneme=0):
            if getattr(app, "_busy_pending", False) or getattr(app, "_aktif_sayfa", None) != "satislar":
                if deneme < 100:
                    app.after(50, lambda: ac(deneme + 1))
                return
            app._menu_islemi(app.cariler_goster)

        app.after(50, ac)

    def _sabit_gider(self):
        from sabit_gider_ui import SabitGiderPlanlariDialog

        try:
            SabitGiderPlanlariDialog(self.app, on_degisti=lambda: self.yenile())
        except PermissionError as hata:
            messagebox.showwarning("Yetki", str(hata), parent=self)

    def _eski_ekran(self):
        from ana_panel_ui import eski_giris_dashboard_goster

        eski_giris_dashboard_goster(self.app)

    # --- yenileme ---
    def _parametreler(self) -> tuple[date, int | None]:
        return tarih_oku(self.tarih_e.get()), self._subeler.get(self.sube_cb.get())

    def _tarih_degisti(self):
        try:
            d = tarih_oku(self.tarih_e.get())
        except ValueError as hata:
            messagebox.showwarning("Rapor tarihi", str(hata), parent=self)
            return
        if d > date.today():
            messagebox.showwarning("Rapor tarihi", "Rapor tarihi bugünden sonra olamaz.", parent=self)
            self.tarih_e.delete(0, "end")
            self.tarih_e.insert(0, _tarih_tr(date.today()))
        self.yenile()

    def yenile(self, zorla: bool = False):
        try:
            d, sube = self._parametreler()
        except ValueError as hata:
            messagebox.showwarning("Rapor tarihi", str(hata), parent=self)
            return
        if d > date.today():
            d = date.today()
        anahtar = (d, sube)
        if self._calisan == anahtar and not zorla:
            return
        self._istek += 1
        jeton = self._istek
        self._calisan = anahtar
        self.yenile_btn.configure(state="disabled", text="Hesaplanıyor…")
        self.durum_lbl.configure(text="Hesaplanıyor…", fg=PASIF)
        from ui_bg import arka_planda

        arka_planda(self, lambda: go.ozet(d, sube, zorla=zorla),
                    on_ok=lambda s, j=jeton: self._geldi(j, s),
                    on_err=lambda e, j=jeton: self._hata(j, e))

    def _bitti(self, jeton) -> bool:
        if jeton != self._istek or not self.winfo_exists():
            return False
        self._calisan = None
        self.yenile_btn.configure(state="normal", text="Yenile")
        return True

    def _hata(self, jeton, hata):
        if not self._bitti(jeton):
            return
        self.bayat_lbl.configure(text="Güncel değil")
        self.durum_lbl.configure(text=f"Yenileme başarısız: {hata}", fg=UYARI)

    def _geldi(self, jeton, sonuc):
        if not self._bitti(jeton):
            return
        self._sonuc = sonuc
        self._sayac = go.degisim_sayaci()
        self.bayat_lbl.configure(text="")
        sure = sonuc.get("sureler", {}).get("toplam", 0) / 1000
        ek = " · önbellekten" if sonuc.get("onbellek") else f" · {sayi_tr(sure, 1)} sn"
        if sonuc.get("veri_degisti"):
            ek += " · hesap sırasında veri değişti"
        self.durum_lbl.configure(text=f"Son yenileme: {sonuc['zaman']:%d.%m.%Y %H:%M:%S}{ek}", fg=PASIF)
        try:
            self._ciz(sonuc)
        except Exception as hata:  # noqa: BLE001 — çizim hatası eski veriyi bozmasın
            import logging

            logging.getLogger("giris_paneli").exception("GİRİŞ çizimi")
            self.bayat_lbl.configure(text="Güncel değil")
            self.durum_lbl.configure(text=f"Ekran çizilemedi: {hata}", fg=UYARI)
        if sonuc["tarih"] == date.today():
            self._soz_hatirlatma()

    def _yokla(self):
        if not self.winfo_exists():
            return
        try:
            if (self._sonuc is not None and self._calisan is None and self.winfo_ismapped()
                    and go.degisim_sayaci() != self._sayac):
                self.bayat_lbl.configure(text="Güncel değil")
                self.yenile()
        finally:
            self.after(YOKLAMA_MS, self._yokla)

    def _soz_hatirlatma(self):
        def metin():
            from database.odeme_sozu_service import OdemeSozuService

            return OdemeSozuService.hatirlatma_metni()

        def goster(m):
            if not self.soz_f.winfo_exists():
                return
            for w in self.soz_f.winfo_children():
                w.destroy()
            if not m:
                return
            tk.Label(self.soz_f, text="Ödeme sözü hatırlatması: " + m, bg=BEYAZ, fg=UYARI, font=FONT_KUCUK,
                     justify="left", wraplength=800).pack(side="left")

            def ac():
                from odeme_sozu_ui import OdemeSozleriMerkezDialog

                OdemeSozleriMerkezDialog(self.app)

            _buton(self.soz_f, "Ödeme Sözleri Takvimi", ac, pady=3).pack(side="right")

        from ui_bg import arka_planda

        arka_planda(self, metin, on_ok=goster, on_err=lambda _e: None)

    # --- ayrıntı ---
    def _ac(self, baslik, kalemler, aciklama=""):
        AyrintiPenceresi(self, baslik, list(kalemler), aciklama=aciklama)

    def _hucre(self, tutar, baslik, kalemler, *, kalin=False, aciklama="", renk=None):
        h = {"m": _tl(tutar), "kalin": kalin}
        if renk:
            h["renk"] = renk
        if tutar is not None and kalemler is not None:
            kalemler = list(kalemler)
            h["cmd"] = lambda: self._ac(baslik, kalemler, aciklama)
        return h

    # --- çizim ---
    def _ciz(self, s: dict):
        d = s["tarih"]
        self._kartlari_ciz(s)
        self._satis_ciz(s["satis"], d)
        self._tahsilat_ciz(s["tahsilat"], d)
        self._borc_ciz()
        self._tedarikci_ciz(s["tedarikci_acik"])

    @staticmethod
    def _kullanilamaz(bolum: dict) -> str | None:
        if bolum["durum"] == go.YETKISIZ:
            return "Yetkisiz"
        if bolum["durum"] == go.HATA:
            return "Hata"
        return None

    def _kart_yaz(self, i, deger, alt, rozet="", cmd=None, renk=LACIVERT):
        k = self.kartlar[i]
        k["deger"].configure(text=deger, fg=renk)
        k["alt"].configure(text=alt)
        k["rozet"].configure(text=rozet)
        k["cmd"] = cmd
        k["cerceve"].configure(cursor="hand2" if cmd else "arrow")

    def _kartlari_ciz(self, s):
        d = s["tarih"]
        sat = s["satis"]
        engel = self._kullanilamaz(sat)
        if engel:
            for i in (0, 1):
                self._kart_yaz(i, engel, sat.get("mesaj", ""), renk=PASIF)
        else:
            dn = go.donemler(d)
            for i, ad, onceki in ((0, "bugun", "önceki ay aynı gün"), (1, "ay", "önceki ay aynı dönem")):
                r = sat["satirlar"][ad]
                kal = [x for x in sat["kalemler"] if go._icinde(x["tarih"], dn[ad])]
                alt = (f"{sayi_tr(r['belge_adedi'])} belge · {onceki}: {para_tr(r['onceki_net'])} · "
                       f"{_yuzde(r['yuzde'], r['yuzde_mesaj'])}")
                rozet = "Gün devam ediyor" if sat.get("gun_devam") else ""
                self._kart_yaz(i, para_tr(r["net"]), alt, rozet,
                               cmd=lambda k=kal, a=ad: self._ac(f"Net satış — {'bugün' if a == 'bugun' else 'bu ay'}",
                                                                 k))
        v = s["likit"]
        engel = self._kullanilamaz(v)
        if engel:
            self._kart_yaz(2, engel, v.get("mesaj", ""), renk=PASIF)
        else:
            kal = v["kalemler"]
            self._kart_yaz(2, para_tr(v["likit"]), "Kasa ve mevduat toplamı (blokaj bilgisi yok)",
                           cmd=lambda: self._ac("Likit varlıklar — kasa ve mevduat", kal))
        b = s["borc"]
        engel = self._kullanilamaz(b)
        if engel:
            self._kart_yaz(3, engel, b.get("mesaj", ""), renk=PASIF)
        else:
            t = b["toplam"]
            rozet = []
            if t["vadesiz"] > 0:
                rozet.append("Vade eksik")
            if b.get("eksik"):
                rozet.append("Eksik veri")
            if b["durum"] == go.TARIHSEL_YOK:
                rozet.append("Bilinen tutarlar")
            kal = go.sutun_kalemleri(b["kalemler"], d, "ay1")
            self._kart_yaz(3, para_tr(t["ay1"]),
                           f"{_tarih_tr(go.kesimler(d)['ay1'])} itibarıyla · gecikmiş {para_tr(t['gecikmis'])} · "
                           f"vadesiz {para_tr(t['vadesiz'])}", " · ".join(rozet),
                           cmd=lambda: self._ac("Bu ay sonu birikimli ödeme yükü", kal))

    def _hazirla(self, kutu: _Kutu, bolum: dict) -> bool:
        kutu.temizle()
        durum = bolum["durum"]
        renk = {go.HAZIR: BASARI, go.BOS: PASIF, go.HATA: UYARI, go.YETKISIZ: UYARI}.get(durum, UYARI)
        kutu.durum(go.DURUM_ADI.get(durum, durum), renk)
        if durum in (go.YETKISIZ, go.HATA):
            kutu.mesaj(bolum.get("mesaj") or go.DURUM_ADI[durum], UYARI)
            return False
        return True

    def _satis_ciz(self, sat, d):
        k = self.k_satis
        if not self._hazirla(k, sat):
            return
        if sat.get("gun_devam"):
            k.durum("Hazır · Gün devam ediyor", BASARI)
        dn = go.donemler(d)
        kal = sat["kalemler"]

        def sec(aralik, tur=None):
            return [x for x in kal if go._icinde(x["tarih"], aralik) and (tur is None or x["tur"] == tur)]

        b, a = sat["satirlar"]["bugun"], sat["satirlar"]["ay"]
        satirlar = []
        for ad, alan, tur in (("Satış belgesi adedi", "belge_adedi", None), ("Satış tutarı", "satis_tutari", "satis"),
                              ("İade adedi", "iade_adedi", None), ("İade tutarı", "iade_tutari", "iade"),
                              ("Net satış", "net", ""), ("KDV hariç net satış", "kdv_haric_net", None),
                              ("Önceki dönem net satış", "onceki_net", "onceki"), ("Fark", "fark", None),
                              ("Değişim %", "yuzde", None)):
            satir = [ad]
            for r, ak, ok in ((b, "bugun", "onceki_gun"), (a, "ay", "onceki_ay")):
                v = r[alan]
                if alan in ("belge_adedi", "iade_adedi"):
                    satir.append(sayi_tr(v))
                elif alan == "yuzde":
                    satir.append(_yuzde(v, r["yuzde_mesaj"]))
                elif tur is None:
                    satir.append({"m": _tl(v), "renk": UYARI if alan == "fark" and v < 0 else None})
                else:
                    aralik = dn[ok] if tur == "onceki" else dn[ak]
                    liste = sec(aralik, None if tur in ("", "onceki") else tur)
                    if tur == "iade":
                        liste = [{**x, "tutar": -x["tutar"]} for x in liste]
                    satir.append(self._hucre(v, f"{ad} — {_tarih_tr(aralik[0])}–{_tarih_tr(aralik[1])}", liste,
                                             kalin=alan == "net"))
            satirlar.append(satir)
        _tablo(k.govde, ["", f"Bugün ({_tarih_tr(d)})", f"Bu ay ({_tarih_tr(dn['ay'][0])}–{_tarih_tr(d)})"],
               satirlar, toplam_satirlari=(4,))
        notlar = list(sat["notlar"])
        if any(x["kdv_haric"] is None for x in kal):
            notlar.append("KDV bilgisi eksik belge(ler) KDV hariç toplama katılmadı.")
        k.notlar(sat["uyarilar"], notlar)

    def _tahsilat_ciz(self, th, d):
        k = self.k_tahsilat
        if not self._hazirla(k, th):
            return
        dn = go.donemler(d)
        listeler = {go.NAKIT: [x for x in th["gercek"] if x["yontem"] == go.NAKIT],
                    go.HAVALE: [x for x in th["gercek"] if x["yontem"] == go.HAVALE],
                    go.KART: [x for x in th["gercek"] if x["yontem"] == go.KART],
                    go.VIRMAN: th["virmanlar"], go.MUS_TED: th["mus_ted"]}

        def hucreler(liste, ad, deger, aralik_kod):
            aralik = dn[aralik_kod]
            sec = [x for x in liste if go._icinde(x["tarih"], aralik)]
            return [sayi_tr(deger["adet"]),
                    self._hucre(deger["tutar"], f"{ad} — {_tarih_tr(aralik[0])}–{_tarih_tr(aralik[1])}", sec)]

        satirlar = []
        for r in th["turler"]:
            satirlar.append([r["tur"]] + hucreler(listeler[r["tur"]], r["tur"], r["bugun"], "bugun")
                            + hucreler(listeler[r["tur"]], r["tur"], r["ay"], "ay"))
        tb, ta = th["toplam"]["bugun"], th["toplam"]["ay"]
        satirlar.append(["Gerçek tahsilat toplamı"] + hucreler(th["gercek"], "Gerçek tahsilat", tb, "bugun")
                        + hucreler(th["gercek"], "Gerçek tahsilat", ta, "ay"))
        satirlar.append(["Önceki dönem", sayi_tr(tb["onceki_adet"]),
                         self._hucre(tb["onceki_tutar"], "Gerçek tahsilat — önceki ay aynı gün",
                                     [x for x in th["gercek"] if go._icinde(x["tarih"], dn["onceki_gun"])]),
                         sayi_tr(ta["onceki_adet"]),
                         self._hucre(ta["onceki_tutar"], "Gerçek tahsilat — önceki ay aynı dönem",
                                     [x for x in th["gercek"] if go._icinde(x["tarih"], dn["onceki_ay"])])])
        satirlar.append(["Fark", "", {"m": _tl(tb["fark"]), "renk": UYARI if tb["fark"] < 0 else None},
                         "", {"m": _tl(ta["fark"]), "renk": UYARI if ta["fark"] < 0 else None}])
        satirlar.append(["Değişim %", "", _yuzde(tb["yuzde"], tb["yuzde_mesaj"]), "",
                         _yuzde(ta["yuzde"], ta["yuzde_mesaj"])])
        satirlar.append(["Tahsilat / net satış oranı", "", _yuzde(tb["oran"], tb["oran_mesaj"]), "",
                         _yuzde(ta["oran"], ta["oran_mesaj"])])
        _tablo(k.govde, ["Tür", "Bugün adet", "Bugün tutar", "Bu ay adet", "Bu ay tutar"], satirlar,
               toplam_satirlari=(len(th["turler"]),))
        k.notlar(th["uyarilar"], ["Cari virman ve müşteriden tedarikçiye ödeme gerçek tahsilata eklenmez."]
                 + th["notlar"])

    def _sutun_basliklari(self, d):
        k = go.kesimler(d)
        return ["Kalem", f"Bugün itibarıyla\n{_tarih_tr(d)}", f"Ay sonu\n{_tarih_tr(k['ay1'])}",
                f"2. ay sonu\n{_tarih_tr(k['ay2'])}", f"3. ay sonu\n{_tarih_tr(k['ay3'])}", "Tamamı kayıtlı\nkapsam"]

    def _sutun_satiri(self, ad, toplamlar, kalemler, d, *, durum=go.HAZIR, kalin=False):
        if durum in (go.TARIHSEL_YOK, go.YETKISIZ, go.HATA):
            metin = go.GECMIS_METNI if durum == go.TARIHSEL_YOK else go.DURUM_ADI[durum]
            return [ad, {"m": metin, "renk": PASIF}, "", "", "", ""]
        return [ad] + [self._hucre(toplamlar[s], f"{ad} — {self._sutun_adi(s, d)}",
                                   go.sutun_kalemleri(kalemler, d, s), kalin=kalin) for s in go.SUTUNLAR]

    @staticmethod
    def _sutun_adi(s, d):
        k = go.kesimler(d)
        return {"bugun": f"bugün itibarıyla ({_tarih_tr(d)})", "ay1": f"ay sonu ({_tarih_tr(k['ay1'])})",
                "ay2": f"2. ay sonu ({_tarih_tr(k['ay2'])})", "ay3": f"3. ay sonu ({_tarih_tr(k['ay3'])})",
                "tamami": "tamamı kayıtlı kapsam"}[s]

    def _borc_ciz(self):
        if self._sonuc is None:
            return
        b, d = self._sonuc["borc"], self._sonuc["tarih"]
        k = self.k_borc
        if not self._hazirla(k, b):
            return
        if self._takvim_gorunum.get() == "takvim":
            satirlar = [self._sutun_satiri(r["ad"], r, [x for x in b["kalemler"] if x.get("satir") == r["kod"]], d,
                                           durum=r["durum"]) for r in b["satirlar"]]
            satirlar.append(self._sutun_satiri("Birikimli ödeme yükü", b["toplam"], b["kalemler"], d, kalin=True))
            _tablo(k.govde, self._sutun_basliklari(d), satirlar, toplam_satirlari=(len(satirlar) - 1,))
            t = b["toplam"]
            alt = tk.Frame(k.govde, bg=BEYAZ)
            alt.pack(fill="x", pady=(8, 0))
            for ad, deger, liste in (
                    ("Vadesiz tutar", t["vadesiz"], go.sutun_kalemleri(b["kalemler"], d, "vadesiz")),
                    ("Gecikmiş tutar", t["gecikmis"], go.sutun_kalemleri(b["kalemler"], d, "gecikmis")),
                    ("Planlanan ek çıkış (3. ay sonuna kadar)", b["planlanan_ek"]["ay3"],
                     go.sutun_kalemleri([x for x in b["kalemler"] if not x["gercek_borc"]], d, "ay3"))):
                f = tk.Frame(alt, bg=BEYAZ)
                f.pack(side="left", padx=(0, 18))
                tk.Label(f, text=ad + ":", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK).pack(side="left")
                lbl = tk.Label(f, text=para_tr(deger), bg=BEYAZ, fg=UYARI if deger > 0 else LACIVERT,
                               font=FONT_UI_BOLD + ("underline",), cursor="hand2")
                lbl.pack(side="left", padx=4)
                lbl.bind("<Button-1>", lambda _e, a=ad, l=liste: self._ac(a, l))
        else:
            satirlar = []
            for ad, deger in b["borc_satirlari"]:
                liste = self._bakiye_kalemleri(ad, b)
                if deger is None:
                    satirlar.append([ad, {"m": go.GECMIS_METNI if b["durum"] == go.TARIHSEL_YOK else "Eksik veri",
                                          "renk": PASIF}])
                elif liste is not None and abs(_toplam(liste) - deger) <= Decimal("0.01"):
                    satirlar.append([ad, self._hucre(deger, ad, liste)])
                else:
                    satirlar.append([ad, _tl(deger)])
            gb = b.get("gercek_borc")
            satirlar.append(["Gerçek borç toplamı (tedarikçi açık borcu hariç)",
                             {"m": _tl(gb) if gb is not None else f"Bilinen tutarlar: {para_tr(b['bilinen_borc'])}",
                              "kalin": True}])
            _tablo(k.govde, ["Kalem", f"{_tarih_tr(d)} itibarıyla"], satirlar, toplam_satirlari=(len(satirlar) - 1,),
                   ilk_gen=40)
        k.notlar(b["uyarilar"], b["notlar"])

    @staticmethod
    def _bakiye_kalemleri(ad, b):
        kal = b["kalemler"]
        if ad.startswith("KMH"):
            return [x for x in kal if x.get("satir") == go.KMH]
        if ad == "Diğer banka borçları":
            return [x for x in kal if x["kaynak"] == "Diğer banka borçları"]
        if ad.startswith("Verilen çek"):
            return [x for x in kal if x["kaynak"] == "Verilen çek / senet"]
        if ad == "Kredi kartı borcu":
            return [x for x in kal if x.get("satir") == go.KK]
        return None

    def _tedarikci_ciz(self, t):
        k = self.k_tedarikci
        if not self._hazirla(k, t):
            return
        satir = tk.Frame(k.govde, bg=BEYAZ)
        satir.pack(fill="x", pady=(2, 4))
        tk.Label(satir, text=f"Bugün itibarıyla ({_tarih_tr(t['tarih'])})", bg=BEYAZ, fg=PASIF,
                 font=FONT_UI).pack(side="left")
        tutar = tk.Label(satir, text=para_tr(t["toplam"]), bg=BEYAZ, fg=LACIVERT, cursor="hand2",
                         font=FONT_KART_DEGER + ("underline",))
        tutar.pack(side="left", padx=(12, 0))
        baslik = f"Tedarikçi açık borcu — {_tarih_tr(t['tarih'])} itibarıyla"
        tutar.bind("<Button-1>", lambda _e: self._ac(baslik, t["kalemler"]))
        k.notlar(t["uyarilar"], t["notlar"])


def giris_paneli_goster(app) -> None:
    """Ana sayfa (giriş) içeriği — yeni özet paneli."""
    for w in app.icerik.winfo_children():
        w.destroy()
    panel = GirisPaneli(app.icerik, app)
    panel.pack(fill="both", expand=True)
    app._giris_paneli = panel
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.durum_guncelle()
