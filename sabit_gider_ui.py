"""Sabit gider ödeme planları ekranı (Gelir ve Giderler → Giderler).

Plan yalnız ödeme takvimidir: cari borç, muhasebe fişi veya kasa / banka hareketi oluşturmaz. Gerçek ödeme
mevcut makbuz / gider fişi / havale ekranlarından yapılır ve burada döneme bağlanır.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk

from ana_panel_tema import ACIK_BG, BEYAZ, CIZGI, FONT_ALT, FONT_KUCUK, LACIVERT, PASIF, SARI, para_tr
from database import sabit_gider_service as sg
from database.access import yetki_var
from database.models.sabit_gider import (
    BAGLANTI_ODEME,
    KATEGORILER,
    PERIYOT_AYLIK,
    PERIYOTLAR,
    PLAN_DURDURULDU,
    PLAN_DURUMLARI,
    PLAN_IPTAL,
)
from giris_paneli_ui import _buton, tablo_stili

DURUM_ADI = dict(PLAN_DURUMLARI)
PERIYOT_ADI = dict(PERIYOTLAR)


def _ay_tr(t) -> str:
    return t.strftime("%m.%Y") if isinstance(t, date) else ""


def _tarih_tr(t) -> str:
    return t.strftime("%d.%m.%Y") if isinstance(t, date) else ""


def _baslik(pencere, metin):
    ust = tk.Frame(pencere, bg=LACIVERT)
    ust.pack(fill="x")
    tk.Label(ust, text=metin, bg=LACIVERT, fg=BEYAZ, font=("Segoe UI", 12, "bold")).pack(side="left", padx=14,
                                                                                        pady=8)
    tk.Frame(pencere, bg=SARI, height=3).pack(fill="x")


def _tablo(parent, kolonlar):
    f = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    t = ttk.Treeview(f, columns=[k[0] for k in kolonlar], show="headings", style=tablo_stili(parent),
                     selectmode="browse")
    for kod, ad, gen, hiza in kolonlar:
        t.heading(kod, text=ad, anchor=hiza)
        t.column(kod, width=gen, anchor=hiza, stretch=kod in ("ad", "aciklama"))
    sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    t.tag_configure("pasif", foreground=PASIF)
    return f, t


class SabitGiderPlanlariDialog(tk.Toplevel):
    KOLONLAR = (
        ("kategori", "Gider türü", 150, "w"), ("ad", "Açıklama", 220, "w"), ("periyot", "Dönem", 90, "w"),
        ("gun", "Ödeme günü", 100, "e"), ("bas", "Başlangıç", 80, "w"), ("bit", "Bitiş", 80, "w"),
        ("tutar", "Bu ay tutarı", 110, "e"), ("tahmini", "Tahmini", 70, "w"), ("durum", "Durum", 90, "w"),
    )

    def __init__(self, parent, on_degisti=None):
        if not sg.okuma_izni():
            raise PermissionError("Sabit gider planlarını görüntüleme yetkiniz yok.")
        super().__init__(parent)
        self.title("Sabit Gider Planları")
        self.configure(bg=ACIK_BG)
        self.geometry("1020x520")
        self.minsize(760, 380)
        self._on_degisti = on_degisti
        self._yazabilir = yetki_var(*sg.YAZMA_YETKISI)
        self._planlar: dict[str, dict] = {}
        _baslik(self, "SABİT GİDER PLANLARI")
        tk.Label(self, text="Plan yalnız ödeme takvimidir; cari borç, muhasebe fişi veya kasa / banka hareketi "
                            "oluşturmaz. Bu ay ve sonraki iki ayın dönemleri otomatik üretilir. Gerçek ödemeyi "
                            "makbuz / gider fişi / havale ile yapıp 'Dönemler' penceresinden bağlayın.",
                 bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK, justify="left", wraplength=980).pack(anchor="w", padx=14,
                                                                                             pady=(6, 0))
        bar = tk.Frame(self, bg=ACIK_BG)
        bar.pack(fill="x", padx=12, pady=6)
        self._yazma_btn = []
        for metin, komut, vurgu in (("Yeni plan", self.yeni, True), ("Düzenle", self.duzenle, False),
                                    ("Durdur", self.durdur, False), ("Yeniden başlat", self.yeniden, False),
                                    ("İptal et", self.iptal, False)):
            b = _buton(bar, metin, komut, vurgu=vurgu)
            b.pack(side="left", padx=(0, 6))
            self._yazma_btn.append(b)
        _buton(bar, "Dönemler ve bağlantılar", self.donemler).pack(side="left", padx=(12, 0))
        _buton(bar, "Kapat", self.destroy).pack(side="right")
        if not self._yazabilir:
            for b in self._yazma_btn:
                b.configure(state="disabled")
        f, self.tablo = _tablo(self, self.KOLONLAR)
        f.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tablo.bind("<Double-1>", lambda _e: self.donemler())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yukle()

    def yukle(self):
        self.tablo.delete(*self.tablo.get_children())
        self._planlar.clear()
        for p in sg.plan_listesi():
            iid = str(p["id"])
            self._planlar[iid] = p
            self.tablo.insert("", "end", iid=iid, tags=("pasif",) if p["durum"] != "AKTIF" else (), values=(
                p["kategori_adi"], p["ad"], PERIYOT_ADI.get(p["periyot"], p["periyot"]), p["odeme_gunu"],
                _ay_tr(p["baslangic_ay"]), _ay_tr(p["bitis_ay"]) or "Süresiz", para_tr(p["tutar"]),
                "Evet" if p["tahmini"] else "", DURUM_ADI.get(p["durum"], p["durum"])))

    def _degisti(self):
        self.yukle()
        if self._on_degisti:
            self._on_degisti()

    def _secili(self) -> dict | None:
        sec = self.tablo.selection()
        if not sec:
            messagebox.showinfo("Sabit gider", "Önce bir plan seçin.", parent=self)
            return None
        return self._planlar[sec[0]]

    def _calistir(self, fn):
        try:
            fn()
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Sabit gider", str(hata), parent=self)
            return False
        self._degisti()
        return True

    def yeni(self):
        PlanFormu(self, None, self._degisti)

    def duzenle(self):
        p = self._secili()
        if p:
            if p["durum"] == PLAN_IPTAL:
                messagebox.showinfo("Sabit gider", "İptal edilmiş plan değiştirilemez.", parent=self)
                return
            PlanFormu(self, p, self._degisti)

    def durdur(self):
        p = self._secili()
        if not p:
            return
        son = simpledialog.askstring("Planı durdur", "Son ödeme ayı (AA.YYYY):", parent=self,
                                     initialvalue=_ay_tr(date.today()))
        if son:
            self._calistir(lambda: sg.plan_durdur(p["id"], son, "Plan durduruldu"))

    def yeniden(self):
        p = self._secili()
        if not p:
            return
        if p["durum"] != PLAN_DURDURULDU:
            messagebox.showinfo("Sabit gider", "Yalnız durdurulmuş plan yeniden başlatılabilir.", parent=self)
            return
        self._calistir(lambda: (sg.plan_yeniden_baslat(p["id"]), sg.donemleri_uret()))

    def iptal(self):
        p = self._secili()
        if not p:
            return
        neden = simpledialog.askstring("Planı iptal et", "İptal nedeni (ödenmiş dönemler korunur):", parent=self)
        if neden is not None:
            self._calistir(lambda: sg.plan_iptal(p["id"], neden))

    def donemler(self):
        p = self._secili()
        if p:
            DonemlerDialog(self, p, self._yazabilir, self._degisti)


class PlanFormu(tk.Toplevel):
    def __init__(self, parent, plan: dict | None, on_kaydet):
        super().__init__(parent)
        self.title("Sabit gider planı" + (" — düzenle" if plan else " — yeni"))
        self.configure(bg=ACIK_BG)
        self.transient(parent)
        self.resizable(False, False)
        self._plan = plan
        self._on_kaydet = on_kaydet
        _baslik(self, "SABİT GİDER PLANI")
        g = tk.Frame(self, bg=ACIK_BG)
        g.pack(fill="both", padx=16, pady=10)
        self._cariler = self._cari_listesi()
        self._hesaplar = self._hesap_listesi()
        bugun = date.today()
        p = plan or {}
        self.alan: dict[str, tk.Widget] = {}
        self.tahmini = tk.BooleanVar(value=bool(p.get("tahmini")))
        satirlar = (
            ("kategori", "Gider türü", ttk.Combobox(g, state="readonly", width=34, values=[a for _k, a in KATEGORILER])),
            ("ad", "Açıklama / plan adı", ttk.Entry(g, width=37)),
            ("cari", "Tedarikçi (isteğe bağlı)", ttk.Combobox(g, width=34, values=[""] + list(self._cariler))),
            ("hesap", "Ödeme hesabı (isteğe bağlı)", ttk.Combobox(g, width=34, values=[""] + self._hesaplar)),
            ("periyot", "Dönem", ttk.Combobox(g, state="readonly", width=34, values=[a for _k, a in PERIYOTLAR])),
            ("gun", "Ödeme günü (1-31)", ttk.Spinbox(g, from_=1, to=31, width=8)),
            ("bas", "Başlangıç ayı (AA.YYYY)", ttk.Entry(g, width=12)),
            ("bit", "Bitiş ayı (boş: süresiz)", ttk.Entry(g, width=12)),
            ("tutar", "Aylık tutar", ttk.Entry(g, width=16, justify="right")),
            ("gecerli", "Tutar hangi aydan geçerli", ttk.Entry(g, width=12)),
            ("not", "Not", ttk.Entry(g, width=37)),
        )
        for i, (kod, etiket, w) in enumerate(satirlar):
            tk.Label(g, text=etiket, bg=ACIK_BG, fg=LACIVERT, font=FONT_ALT).grid(row=i, column=0, sticky="w",
                                                                                pady=3, padx=(0, 10))
            w.grid(row=i, column=1, sticky="w", pady=3)
            self.alan[kod] = w
        ttk.Checkbutton(g, text="Tutar tahmini (fatura gelince kesinleşir)", variable=self.tahmini).grid(
            row=len(satirlar), column=1, sticky="w", pady=(4, 0))
        kat = dict(KATEGORILER)
        self.alan["kategori"].set(kat.get(p.get("kategori"), ""))
        self.alan["ad"].insert(0, p.get("ad", ""))
        cari_ad = next((ad for ad, cid in self._cariler.items() if cid == p.get("cari_id")), "")
        self.alan["cari"].set(cari_ad)
        self.alan["hesap"].set(p.get("odeme_hesabi", ""))
        self.alan["periyot"].set(PERIYOT_ADI.get(p.get("periyot", PERIYOT_AYLIK)))
        self.alan["gun"].set(p.get("odeme_gunu", 1))
        self.alan["bas"].insert(0, _ay_tr(p.get("baslangic_ay") or bugun))
        self.alan["bit"].insert(0, _ay_tr(p.get("bitis_ay")))
        if p:
            self.alan["tutar"].insert(0, para_tr(p["tutar"]))
            self.alan["gecerli"].insert(0, _ay_tr(bugun))
        else:
            self.alan["gecerli"].insert(0, "—")
            self.alan["gecerli"].configure(state="disabled")
        self.alan["not"].insert(0, p.get("aciklama", ""))
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(alt, text="Tutar değişikliği seçilen aydan itibaren uygulanır; önceki dönemler değişmez.",
                 bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK).pack(side="left")
        _buton(alt, "Vazgeç", self.destroy).pack(side="right", padx=(6, 0))
        _buton(alt, "Kaydet", self.kaydet, vurgu=True).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(50, self._kilitle)

    def _kilitle(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    @staticmethod
    def _cari_listesi() -> dict[str, int]:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.cari import Cari

        with get_session() as s:
            return {f"{unvan} ({kod})": int(i) for i, kod, unvan in s.execute(
                select(Cari.id, Cari.cari_kodu, Cari.unvan).where(Cari.cari_turu.in_(("Tedarikçi", "Tedarikci")))
                .order_by(Cari.unvan)).all()}

    @staticmethod
    def _hesap_listesi() -> list[str]:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.finans import FinansHesabi

        with get_session() as s:
            return [ad for (ad,) in s.execute(select(FinansHesabi.hesap_adi).where(
                FinansHesabi.hesap_turu.in_(("KASA", "BANKA"))).order_by(FinansHesabi.hesap_adi)).all()]

    def kaydet(self):
        a = self.alan
        kat_kod = {ad: k for k, ad in KATEGORILER}.get(a["kategori"].get(), "")
        periyot = {ad: k for k, ad in PERIYOTLAR}.get(a["periyot"].get(), PERIYOT_AYLIK)
        tutar_metni = a["tutar"].get().strip().replace(".", "").replace(",", ".")
        cari = a["cari"].get().strip()
        if cari and cari not in self._cariler:
            messagebox.showwarning("Sabit gider", "Tedarikçiyi listeden seçin veya boş bırakın.", parent=self)
            return
        veri = {"kategori": kat_kod, "ad": a["ad"].get(), "cari_id": self._cariler.get(cari),
                "odeme_hesabi": a["hesap"].get(), "periyot": periyot, "odeme_gunu": a["gun"].get(),
                "baslangic_ay": a["bas"].get(), "bitis_ay": a["bit"].get().strip() or None,
                "tutar": tutar_metni or "0", "tahmini": self.tahmini.get(), "aciklama": a["not"].get()}
        try:
            if self._plan:
                sg.plan_kaydet(veri, self._plan["id"], gecerli_ay=a["gecerli"].get().strip() or None)
            else:
                sg.plan_kaydet(veri)
            sg.donemleri_uret()
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Sabit gider", str(hata), parent=self)
            return
        except Exception as hata:  # noqa: BLE001 — ör. geçersiz tutar biçimi
            messagebox.showerror("Sabit gider", f"Kaydedilemedi: {hata}", parent=self)
            return
        self.destroy()
        self._on_kaydet()


class DonemlerDialog(tk.Toplevel):
    KOLONLAR = (
        ("donem", "Dönem", 70, "w"), ("vade", "Vade", 85, "w"), ("tutar", "Tutar", 100, "e"),
        ("odenen", "Ödenen", 100, "e"), ("fatura", "Faturaya bağlı", 110, "e"), ("kalan", "Kalan", 100, "e"),
        ("durum", "Durum", 120, "w"),
    )
    BAG_KOLONLAR = (
        ("belge", "Evrak no", 140, "w"), ("tur", "Bağlantı", 110, "w"), ("tarih", "Tarih", 85, "w"),
        ("tutar", "Tutar", 100, "e"), ("durum", "Durum", 80, "w"), ("aciklama", "Kullanıcı / iptal nedeni", 260, "w"),
    )

    def __init__(self, parent, plan: dict, yazabilir: bool, on_degisti):
        super().__init__(parent)
        self.title(f"Dönemler — {plan['ad']}")
        self.configure(bg=ACIK_BG)
        self.geometry("860x560")
        self.transient(parent)
        self._plan = plan
        self._on_degisti = on_degisti
        self._donemler: dict[str, dict] = {}
        _baslik(self, f"{plan['kategori_adi'].upper()} — {plan['ad']}")
        bar = tk.Frame(self, bg=ACIK_BG)
        bar.pack(fill="x", padx=12, pady=6)
        b1 = _buton(bar, "Evrak bağla", self.bagla, vurgu=True)
        b1.pack(side="left", padx=(0, 6))
        b2 = _buton(bar, "Bağlantıyı iptal et", self.bag_iptal)
        b2.pack(side="left")
        if not yazabilir:
            b1.configure(state="disabled")
            b2.configure(state="disabled")
        _buton(bar, "Kapat", self.destroy).pack(side="right")
        f, self.tablo = _tablo(self, self.KOLONLAR)
        f.pack(fill="both", expand=True, padx=12)
        tk.Label(self, text="Seçili dönemin bağlantıları", bg=ACIK_BG, fg=LACIVERT, font=FONT_ALT).pack(
            anchor="w", padx=12, pady=(8, 2))
        f2, self.bag = _tablo(self, self.BAG_KOLONLAR)
        f2.configure(height=150)
        f2.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(self, text="Ödeme evrakı (ödeme makbuzu, gider fişi, havale) kalanı azaltır. Fatura bağlantısı "
                            "planın yerini alır; borç tedarikçi açık borcunda bir kez sayılır.",
                 bg=ACIK_BG, fg=PASIF, font=FONT_KUCUK, wraplength=820, justify="left").pack(anchor="w", padx=12,
                                                                                             pady=(0, 10))
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._baglantilari_goster())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yukle()

    def yukle(self, secili: str | None = None):
        self.tablo.delete(*self.tablo.get_children())
        self._donemler.clear()
        for d in sg.plan_donemleri(self._plan["id"]):
            iid = str(d["donem_id"])
            self._donemler[iid] = d
            durum = "İptal" if d["durum"] != "ACIK" else ("Kapandı" if d["kalan"] <= 0 else "Açık")
            if d["tahmini"] and d["durum"] == "ACIK":
                durum += " · tahmini"
            self.tablo.insert("", "end", iid=iid, tags=("pasif",) if d["durum"] != "ACIK" else (), values=(
                f"{d['ay']:02d}.{d['yil']}", _tarih_tr(d["vade"]), para_tr(d["tutar"]), para_tr(d["odenen"]),
                para_tr(d["faturaya_bagli"]), para_tr(d["kalan"]), durum))
        if secili and self.tablo.exists(secili):
            self.tablo.selection_set(secili)
        self._baglantilari_goster()

    def _baglantilari_goster(self):
        self.bag.delete(*self.bag.get_children())
        sec = self.tablo.selection()
        if not sec:
            return
        d = self._donemler[sec[0]]
        for b in d["tum_baglantilar"]:
            self.bag.insert("", "end", iid=str(b["id"]), tags=("pasif",) if b["iptal"] else (), values=(
                b["belge_no"], "Ödeme" if b["tur"] == BAGLANTI_ODEME else "Borç belgesi", _tarih_tr(b["tarih"]),
                para_tr(b["tutar"]), "İptal" if b["iptal"] else "Aktif",
                b["iptal_nedeni"] if b["iptal"] else b["kullanici"]))

    def _secili_donem(self):
        sec = self.tablo.selection()
        if not sec:
            messagebox.showinfo("Sabit gider", "Önce bir dönem seçin.", parent=self)
            return None
        return sec[0]

    def _calistir(self, fn, secili):
        try:
            fn()
        except (ValueError, PermissionError) as hata:
            messagebox.showwarning("Sabit gider", str(hata), parent=self)
            return
        except ArithmeticError:
            messagebox.showwarning("Sabit gider", "Tutar geçerli bir sayı olmalıdır.", parent=self)
            return
        self.yukle(secili)
        self._on_degisti()

    def bagla(self):
        iid = self._secili_donem()
        if not iid:
            return
        d = self._donemler[iid]
        belge = simpledialog.askstring("Evrak bağla", "Evrak no (ödeme makbuzu, gider fişi, havale veya fatura):",
                                       parent=self)
        if not belge:
            return
        varsayilan = para_tr(d["kalan"] if d["kalan"] > 0 else d["tutar"])
        tutar = simpledialog.askstring("Evrak bağla", "Bu döneme dağıtılacak tutar:", parent=self,
                                       initialvalue=varsayilan)
        if not tutar:
            return
        tutar = tutar.strip().replace(".", "").replace(",", ".")
        self._calistir(lambda: sg.baglanti_ekle(int(iid), belge.strip(), tutar), iid)

    def bag_iptal(self):
        iid = self._secili_donem()
        sec = self.bag.selection()
        if not iid or not sec:
            if iid:
                messagebox.showinfo("Sabit gider", "Alttaki listeden bir bağlantı seçin.", parent=self)
            return
        neden = simpledialog.askstring("Bağlantıyı iptal et", "İptal nedeni:", parent=self)
        if neden is not None:
            self._calistir(lambda: sg.baglanti_iptal(int(sec[0]), neden), iid)


def sabit_gider_planlari_ac(app) -> None:
    try:
        SabitGiderPlanlariDialog(app)
    except PermissionError as hata:
        messagebox.showwarning("Yetki", str(hata), parent=app)

