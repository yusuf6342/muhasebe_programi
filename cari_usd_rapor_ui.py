"""Cari hareket raporu: TL / İşlem tarihindeki USD karşılığı görünümü.

USD karşılık yalnız raporlamadır; TL borç/alacak, evrak ve kapatma değişmez.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from database import cari_usd_karsilik_service as usd_servis

GORUNUM_TL = "TL"
GORUNUM_USD = "USD"
GORUNUM_SECENEKLERI = (
    (GORUNUM_TL, "TL"),
    (GORUNUM_USD, "TL / İşlem tarihindeki USD karşılığı"),
)

_KOLONLAR = (
    ("tarih", "İşlem Tarihi", 88, "center"),
    ("belge", "Belge No", 115, "w"),
    ("tur", "Tür", 110, "w"),
    ("tl_borc", "TL Borç", 105, "e"),
    ("tl_alacak", "TL Alacak", 105, "e"),
    ("tl_bakiye", "TL Bakiye", 110, "e"),
    ("kur", "USD Kuru", 80, "e"),
    ("kur_tarihi", "Kur Tarihi", 88, "center"),
    ("kaynak", "Kur Kaynağı", 80, "center"),
    ("usd_borc", "USD Borç", 95, "e"),
    ("usd_alacak", "USD Alacak", 95, "e"),
    ("usd_bakiye", "Tarihsel USD Bakiye", 125, "e"),
    ("durum", "Durum", 150, "w"),
)


def _para(tutar, pb: str = "") -> str:
    if tutar is None:
        return ""
    metin = f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {pb}".strip()


def _kur_metin(kur) -> str:
    if kur is None:
        return ""
    return f"{float(kur):,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if t else ""


def _durum_metni(r: dict) -> str:
    if r["durum"] == usd_servis.DURUM_EKSIK:
        return "⚠ Kur yok — USD hesaplanmadı"
    if r["durum"] == usd_servis.DURUM_UYUSMAZ:
        return "⚠ Kayıt değişmiş — yeniden hesaplanmalı"
    if r.get("kur_kaynagi") == "MANUEL":
        return "Manuel kur"
    if r.get("onceki_gun_kuru"):
        return "Önceki yayın günü kuru"
    return ""


class CariUsdRaporCercevesi(ttk.Frame):
    """Gömülebilir USD karşılık tablosu + özet + eksik kur tamamlama."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._cari_id: int | None = None
        self._baslangic: date | None = None
        self._bitis: date | None = None

        ust = ttk.Frame(self)
        ust.pack(fill="x", pady=(4, 2))
        self.ozet = ttk.Label(ust, text="Cari seçip raporu getirin.", font=("Segoe UI", 10, "bold"))
        self.ozet.pack(side="left", anchor="w")
        ttk.Button(ust, text="Eksik kurları tamamla…", command=self.eksik_kurlari_tamamla).pack(side="right")
        ttk.Label(
            self,
            text=(
                "Kur: TCMB USD döviz satış — işlem tarihindeki kur; o gün yayımlanmamışsa son yayımlanmış "
                "önceki kur (Kur Tarihi sütunu). Kur hareket kaydedilirken saklanır; rapor açılırken "
                "internetten kur alınmaz."
            ),
            foreground="#455A64", wraplength=1100, justify="left",
        ).pack(fill="x")

        govde = ttk.Frame(self)
        govde.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(govde, columns=[k[0] for k in _KOLONLAR], show="headings", height=16)
        for anahtar, baslik, genislik, hiza in _KOLONLAR:
            self.tablo.heading(anahtar, text=baslik)
            self.tablo.column(anahtar, width=genislik, anchor=hiza, stretch=anahtar in ("belge", "tur", "durum"))
        dikey = ttk.Scrollbar(govde, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(govde, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        govde.rowconfigure(0, weight=1)
        govde.columnconfigure(0, weight=1)
        self.tablo.tag_configure("eksik", background="#FDECEA", foreground="#B71C1C")
        self.tablo.tag_configure("uyusmaz", background="#FFF4E5", foreground="#8A4B00")
        self.tablo.tag_configure("onceki", foreground="#6D4C41")
        self.tablo.tag_configure("devir", background="#EEF3FA", font=("Segoe UI", 9, "bold"))
        self.tablo.tag_configure("toplam", background="#E3EAF5", font=("Segoe UI", 9, "bold"))

        self.not_etiketi = ttk.Label(
            self, text=usd_servis.FARK_ACIKLAMASI, foreground="#455A64", wraplength=1100, justify="left"
        )
        self.not_etiketi.pack(fill="x", pady=(6, 0))
        self.uyari_etiketi = ttk.Label(self, text="", foreground="#B71C1C", wraplength=1100, justify="left")
        self.uyari_etiketi.pack(fill="x")
        self.rapor: dict | None = None

    def yukle(self, cari_id: int, baslangic: date | None = None, bitis: date | None = None) -> dict:
        self._cari_id, self._baslangic, self._bitis = int(cari_id), baslangic, bitis
        rapor = usd_servis.cari_usd_raporu(cari_id, baslangic, bitis)
        self.rapor = rapor
        self.tablo.delete(*self.tablo.get_children())
        devir = rapor["devir"]
        if baslangic is not None:
            usd_devir = _para(devir["usd"], "USD")
            if devir["eksik"]:
                usd_devir = f"{usd_devir} (eksik)"
            self.tablo.insert("", "end", tags=("devir",), values=(
                _tarih(baslangic), "DEVİR", "Önceki hareketler", "", "", _para(devir["tl"], "TL"),
                "", "", "", "", "", usd_devir,
                f"⚠ {devir['eksik']} hareketin kuru yok" if devir["eksik"] else "",
            ))
        for r in rapor["satirlar"]:
            etiket = ()
            if r["durum"] == usd_servis.DURUM_EKSIK:
                etiket = ("eksik",)
            elif r["durum"] == usd_servis.DURUM_UYUSMAZ:
                etiket = ("uyusmaz",)
            elif r.get("onceki_gun_kuru"):
                etiket = ("onceki",)
            tamam = r["durum"] == usd_servis.DURUM_TAMAM
            usd_bakiye = _para(r["usd_bakiye"], "USD")
            if r.get("usd_eksik_birikimli"):
                usd_bakiye = f"{usd_bakiye} *"
            self.tablo.insert("", "end", tags=etiket, values=(
                _tarih(r["tarih"]), r["belge_no"], r["tur"],
                _para(r["tl_borc"]) if r["tl_borc"] else "",
                _para(r["tl_alacak"]) if r["tl_alacak"] else "",
                _para(r["tl_bakiye"], "TL"),
                _kur_metin(r["usd_kur"]) if tamam else "—",
                _tarih(r.get("kur_tarihi")) if tamam else "",
                (r.get("kur_kaynagi") or "") if tamam else "",
                _para(r["usd_borc"]) if tamam and r["usd_borc"] else ("" if tamam else "—"),
                _para(r["usd_alacak"]) if tamam and r["usd_alacak"] else ("" if tamam else "—"),
                usd_bakiye,
                _durum_metni(r),
            ))
        t = rapor["toplam"]
        eksik_toplam = rapor["eksik_sayisi"] + rapor["devir_eksik"]
        usd_ek = "" if rapor["tam"] else " (eksik)"
        self.tablo.insert("", "end", tags=("toplam",), values=(
            "", "TOPLAM", "", _para(t["tl_borc"]), _para(t["tl_alacak"]), _para(rapor["tl_bakiye"], "TL"),
            "", "", "", _para(t["usd_borc"]) + usd_ek, _para(t["usd_alacak"]) + usd_ek,
            _para(rapor["usd_bakiye"], "USD") + usd_ek, "",
        ))
        ozet = (
            f"TL bakiye: {_para(rapor['tl_bakiye'], 'TL')}   |   "
            f"Tarihsel USD bakiye: {_para(rapor['usd_bakiye'], 'USD')}{usd_ek}"
        )
        self.ozet.configure(text=ozet)
        if not rapor["tam"]:
            self.uyari_etiketi.configure(text=(
                f"⚠ {eksik_toplam} hareketin USD kuru yok veya kaydı değişmiş. USD toplamları ve bakiye "
                "bu hareketler hariç hesaplandı ve EKSİKTİR (* işaretli bakiyeler). "
                "\"Eksik kurları tamamla…\" ile önizleyip tamamlayabilirsiniz."
            ))
        else:
            self.uyari_etiketi.configure(text="")
        self.not_etiketi.configure(text=rapor["fark_notu"] or usd_servis.FARK_ACIKLAMASI)
        return rapor

    def yenile(self) -> None:
        if self._cari_id is not None:
            self.yukle(self._cari_id, self._baslangic, self._bitis)

    def eksik_kurlari_tamamla(self) -> None:
        if self._cari_id is None:
            messagebox.showinfo("USD karşılık", "Önce bir cari seçip raporu getirin.", parent=self)
            return
        EksikKurDialog(self, self._cari_id, on_uygulandi=self.yenile)


class EksikKurDialog(tk.Toplevel):
    """Eksik USD kurlarını önizleme + TCMB / manuel kurla kontrollü tamamlama."""

    def __init__(self, parent, cari_id: int | None, on_uygulandi=None):
        super().__init__(parent)
        self.title("Eksik USD kurlarını tamamla")
        self.geometry("980x520")
        self.transient(parent.winfo_toplevel())
        self.cari_id = cari_id
        self.on_uygulandi = on_uygulandi
        self.onizleme: dict = {"satirlar": [], "hatalar": {}}
        self.manuel: dict[date, Decimal] = {}

        ttk.Label(
            self,
            text=(
                "Kuru eksik hareketler aşağıda önizlenir. Önerilen kur, işlem tarihindeki (yoksa son "
                "yayımlanmış önceki) USD döviz satış kurudur; sonraki tarihin kuru kullanılmaz. "
                "Uygula'ya basmadan hiçbir kayıt değişmez; eksiksiz kayıtların kuru değiştirilmez."
            ),
            wraplength=940, justify="left",
        ).pack(fill="x", padx=10, pady=(10, 6))
        cubuk = ttk.Frame(self)
        cubuk.pack(fill="x", padx=10)
        ttk.Button(cubuk, text="TCMB'den eksik kurları getir", command=lambda: self.yukle(True)).pack(side="left")
        ttk.Button(cubuk, text="Seçili tarihe manuel kur…", command=self.manuel_kur_gir).pack(side="left", padx=6)
        ttk.Button(cubuk, text="Önerileri uygula", command=self.uygula).pack(side="right")

        kolonlar = (
            ("tarih", "İşlem Tarihi", 90), ("belge", "Belge No", 120), ("tur", "Tür", 110),
            ("tl", "TL Tutar", 110), ("kur", "Önerilen Kur", 95), ("kur_tarihi", "Kur Tarihi", 90),
            ("kaynak", "Kaynak", 80), ("durum", "Durum", 230),
        )
        govde = ttk.Frame(self)
        govde.pack(fill="both", expand=True, padx=10, pady=6)
        self.tablo = ttk.Treeview(govde, columns=[k[0] for k in kolonlar], show="headings")
        for k, b, g in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=g, anchor="e" if k in ("tl", "kur") else "w")
        sb = ttk.Scrollbar(govde, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sb.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tablo.tag_configure("yok", foreground="#B71C1C")
        self.tablo.tag_configure("manuel", foreground="#0D47A1")
        self.bilgi = ttk.Label(self, text="", foreground="#B71C1C", wraplength=940, justify="left")
        self.bilgi.pack(fill="x", padx=10, pady=(0, 10))
        self.yukle(False)

    def yukle(self, internetten: bool) -> None:
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            self.onizleme = usd_servis.eksik_kur_onizleme(self.cari_id, internetten=internetten)
        except Exception as hata:
            messagebox.showerror("USD karşılık", str(hata), parent=self)
            return
        finally:
            try:
                self.config(cursor="")
            except tk.TclError:
                pass
        self._doldur()
        hatalar = self.onizleme.get("hatalar") or {}
        if internetten and hatalar:
            ornek = next(iter(hatalar.values()))
            messagebox.showwarning(
                "TCMB",
                f"{len(hatalar)} tarih için TCMB kuru alınamadı.\n\n{ornek}\n\n"
                "Kayıtlı uygun kur yoksa ilgili tarihe manuel kur girebilirsiniz.",
                parent=self,
            )

    def _doldur(self) -> None:
        self.tablo.delete(*self.tablo.get_children())
        yok = 0
        for i, r in enumerate(self.onizleme["satirlar"]):
            tl = r["tl_borc"] or r["tl_alacak"]
            manuel = self.manuel.get(r["tarih"])
            oneri = r.get("oneri")
            if manuel is not None:
                deger = (_kur_metin(manuel), _tarih(r["tarih"]), "MANUEL", "Manuel kur uygulanacak")
                etiket = ("manuel",)
            elif oneri:
                durum = "Önceki yayın günü kuru" if oneri["kur_tarihi"] < r["tarih"] else "İşlem günü kuru"
                if r["durum"] == usd_servis.DURUM_UYUSMAZ:
                    durum = "Kayıt değişmiş — yeniden hesaplanacak"
                deger = (_kur_metin(oneri["kur"]), _tarih(oneri["kur_tarihi"]), oneri.get("kaynak") or "", durum)
                etiket = ()
            else:
                hata = (self.onizleme.get("hatalar") or {}).get(r["tarih"])
                deger = ("—", "", "", "Kur bulunamadı" + (f" ({hata})" if hata else "") + " — manuel girin")
                etiket = ("yok",)
                yok += 1
            self.tablo.insert("", "end", iid=str(i), tags=etiket, values=(
                _tarih(r["tarih"]), r["belge_no"], r["tur"], _para(tl), *deger,
            ))
        toplam = len(self.onizleme["satirlar"])
        if not toplam:
            self.bilgi.configure(text="Kuru eksik hareket yok.", foreground="#2E7D32")
        else:
            self.bilgi.configure(
                text=f"{toplam} hareket önizlemede; {yok} hareket için kur bulunamadı.",
                foreground="#B71C1C" if yok else "#2E7D32",
            )

    def manuel_kur_gir(self) -> None:
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Manuel kur", "Önce listeden bir hareket seçin.", parent=self)
            return
        r = self.onizleme["satirlar"][int(secim[0])]
        metin = simpledialog.askstring(
            "Manuel USD kuru",
            f"{_tarih(r['tarih'])} tarihli hareketler için USD döviz satış kuru:\n"
            "(Yalnız bu tarihteki eksik hareketlere uygulanır; kur tablosu değişmez.)",
            parent=self,
        )
        if metin is None:
            return
        try:
            self.manuel[r["tarih"]] = usd_servis.manuel_kur_dogrula(metin)
        except ValueError as hata:
            messagebox.showerror("Manuel kur", str(hata), parent=self)
            return
        self._doldur()

    def uygula(self) -> None:
        satirlar = [
            r for r in self.onizleme["satirlar"] if r.get("oneri") or r["tarih"] in self.manuel
        ]
        if not satirlar:
            messagebox.showinfo("USD karşılık", "Uygulanacak öneri yok.", parent=self)
            return
        if not messagebox.askyesno(
            "Onay",
            f"{len(satirlar)} hareketin USD karşılığı kaydedilecek "
            f"({len(self.manuel)} tarihte manuel kur). TL tutarlar ve evraklar değişmez.\n\nDevam edilsin mi?",
            parent=self,
        ):
            return
        try:
            sonuc = usd_servis.eksik_kurlari_uygula(satirlar, self.manuel)
        except ValueError as hata:
            messagebox.showerror("USD karşılık", str(hata), parent=self)
            return
        messagebox.showinfo(
            "USD karşılık",
            f"{sonuc['yazilan']} hareket kaydedildi ({sonuc['manuel']} manuel), {sonuc['atlanan']} atlandı.",
            parent=self,
        )
        if self.on_uygulandi:
            self.on_uygulandi()
        self.destroy()


def tarih_coz(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def usd_rapor_penceresi(parent, cari_id: int, baslik: str = "") -> tk.Toplevel:
    """Cari kartından açılan bağımsız TL / USD karşılığı penceresi."""
    pencere = tk.Toplevel(parent)
    pencere.title(f"TL / İşlem tarihindeki USD karşılığı — {baslik}".strip(" —"))
    pencere.geometry("1320x640")
    try:
        pencere.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    filtre = ttk.Frame(pencere)
    filtre.pack(fill="x", padx=10, pady=(10, 4))
    ttk.Label(filtre, text=baslik, font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 16))
    from ui_takvim import takvim_butonu

    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    bas = ttk.Entry(filtre, width=11)
    bas.pack(side="left", padx=(4, 0))
    takvim_butonu(filtre, bas)
    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(10, 0))
    bit = ttk.Entry(filtre, width=11)
    bit.pack(side="left", padx=(4, 0))
    takvim_butonu(filtre, bit)
    cerceve = CariUsdRaporCercevesi(pencere)
    cerceve.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _getir():
        try:
            b, s = tarih_coz(bas.get()), tarih_coz(bit.get())
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=pencere)
            return
        if b and s and b > s:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=pencere)
            return
        cerceve.yukle(cari_id, b, s)

    ttk.Button(filtre, text="Getir", command=_getir).pack(side="left", padx=6)
    _getir()
    return pencere
