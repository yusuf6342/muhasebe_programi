"""Kurumsal Satış İrsaliyesi dialog — stok çıkışı yalnızca Sevk Et ile."""

from __future__ import annotations

import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from database.satis_irsaliyesi_service import (
    IRSALIYE_DURUMLARI,
    SatisIrsaliyesiService,
    durum_gosterim,
)
from database.satis_siparisi_service import decimal
from urun_sec_ui import UrunSecDialog

LACIVERT = "#1B2A4A"
BEYAZ = "#FFFFFF"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
TURUNCU = "#E65100"
KIRMIZI = "#C62828"
MAVI = "#1565C0"
GRI = "#64748B"

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")

DURUM_RENK = {
    "TASLAK": (GRI, BEYAZ),
    "HAZIRLANIYOR": (TURUNCU, BEYAZ),
    "SEVKİYATA HAZIR": ("#00838F", BEYAZ),
    "SEVK EDİLDİ": (MAVI, BEYAZ),
    "AÇIK": (MAVI, BEYAZ),
    "KISMEN TESLİM EDİLDİ": ("#6A1B9A", BEYAZ),
    "TESLİM EDİLDİ": (YESIL, BEYAZ),
    "KISMİ FATURALANDI": ("#558B2F", BEYAZ),
    "FATURALANDI": (YESIL, BEYAZ),
    "İPTAL": (KIRMIZI, BEYAZ),
    "İADE": ("#6D4C41", BEYAZ),
}


def _para(tutar) -> str:
    try:
        return f"{float(tutar or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"
    except Exception:
        return "0,00 TL"


def _tarih(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


class SatisIrsaliyesiDialog(tk.Toplevel):
    """Kurumsal satış irsaliyesi kartı."""

    def __init__(self, parent, irsaliye=None, siparis=None, cari=None):
        super().__init__(parent)
        self.irsaliye = irsaliye
        self.siparis = siparis
        self.result = None
        self.title("SATIŞ İRSALİYESİ")
        self.geometry("1280x820")
        self.minsize(980, 640)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.transient(parent)
        self.grab_set()

        self.satirlar: list[dict[str, Any]] = []
        try:
            self.musteriler = SatisIrsaliyesiService.aktif_musterileri()
            if siparis and siparis.cari and siparis.cari not in self.musteriler:
                self.musteriler.append(siparis.cari)
            self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
            self.siparisler = SatisIrsaliyesiService.acik_siparisler()
            self.siparis_map = {s.siparis_no: s for s in self.siparisler}
            self.depolar = SatisIrsaliyesiService.depolar() or ["ANA DEPO"]
        except Exception as exc:
            import traceback

            traceback.print_exc()
            messagebox.showerror(
                "Satış İrsaliyesi",
                "İrsaliye kartı açılamadı.\n\n"
                f"{exc}\n\n"
                "Teknik ayrıntı terminal çıktısına yazıldı.",
                parent=parent,
            )
            self.destroy()
            return
        self.girdiler: dict[str, Any] = {}
        self.satir_girdileri: dict[str, Any] = {}
        self._durum_var = tk.StringVar(value=irsaliye.durum if irsaliye else "TASLAK")
        self._is_priced = tk.BooleanVar(
            value=True if irsaliye is None else bool(getattr(irsaliye, "is_priced", True))
        )

        self._ust_baslik()
        try:
            from kullanici_degistir_ui import aktif_kullanici_cubugu

            self._aktif_kullanici_cubugu = aktif_kullanici_cubugu(self, yenile=self._meta_yenile)
        except Exception:
            self._aktif_kullanici_cubugu = None

        alan = ttk.Frame(self, padding=8)
        alan.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(alan, highlightthickness=0, bg=ACIK_GRI)
        kaydirma = ttk.Scrollbar(alan, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas, padding=6)
        pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind(
            "<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(pencere, width=e.width)
        )
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        self._toolbar()
        self._baslik_alanlari()
        self._sevk_adres_alanlari()
        self._satir_alani()
        self._notlar_ve_toplam()

        self.bind("<F1>", lambda _e: self.kaydet())
        if irsaliye:
            self._doldur()
        elif siparis:
            self._siparisten_doldur(siparis)
        elif cari:
            self.musteri.set(f"{cari.cari_kodu} - {cari.unvan}")
            self.bakiye_guncelle()
            self._sevk_adres_cari_doldur(cari)
        self._durum_rozet_guncelle()
        self._meta_yenile()

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _ust_baslik(self):
        ust = tk.Frame(self, bg=LACIVERT, height=56)
        ust.pack(fill="x")
        ust.pack_propagate(False)
        tk.Label(
            ust,
            text="SATIŞ İRSALİYESİ",
            bg=LACIVERT,
            fg=BEYAZ,
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left", padx=16, pady=10)
        self._meta_label = tk.Label(
            ust, text="", bg=LACIVERT, fg="#CBD5E1", font=("Segoe UI", 9)
        )
        self._meta_label.pack(side="left", padx=8)
        self._badge = tk.Label(
            ust,
            text="TASLAK",
            bg=GRI,
            fg=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=4,
        )
        self._badge.pack(side="right", padx=16)

    def _meta_yenile(self):
        no = ""
        if self.irsaliye:
            no = getattr(self.irsaliye, "irsaliye_no", "") or ""
        elif "irsaliye_no" in self.girdiler:
            no = self.girdiler["irsaliye_no"].get()
        stok = ""
        if self.irsaliye and getattr(self.irsaliye, "stok_cikis_yapildi", False):
            stok = " | Stok: ÇIKIŞ YAPILDI"
        self._meta_label.configure(text=f"{no}{stok}")

    def _durum_rozet_guncelle(self):
        d = self._durum_var.get() or "TASLAK"
        goster = durum_gosterim(d)
        bg, fg = DURUM_RENK.get(d, DURUM_RENK.get(goster, (GRI, BEYAZ)))
        self._badge.configure(text=goster, bg=bg, fg=fg)

    def _toolbar(self):
        bar = ttk.Frame(self.icerik)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Kaydet (F1)", command=self.kaydet).pack(side="left", padx=2)
        ttk.Button(bar, text="Siparişten Getir", command=self.siparisi_secildi).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="Sevkiyata Hazırla", command=self.hazirla).pack(side="left", padx=2)
        ttk.Button(bar, text="Sevk Et", command=self.sevk_et).pack(side="left", padx=2)
        ttk.Button(bar, text="Teslim", command=self.teslim_et).pack(side="left", padx=2)
        ttk.Button(bar, text="Fatura Oluştur", command=self.fatura_olustur).pack(
            side="left", padx=2
        )
        ttk.Button(bar, text="İptal", command=self.iptal_et).pack(side="left", padx=2)
        ttk.Button(bar, text="Önizleme", command=self.onizleme).pack(side="left", padx=2)
        ttk.Button(bar, text="PDF", command=self.pdf_kaydet).pack(side="left", padx=2)
        ttk.Button(bar, text="Kapat", command=self.destroy).pack(side="right", padx=2)

    def _girdi(self, parent, row, col, label, field, value="", width=28):
        ttk.Label(parent, text=label).grid(row=row, column=col * 2, padx=4, pady=3, sticky="w")
        widget = ttk.Entry(parent, width=width)
        widget.grid(row=row, column=col * 2 + 1, padx=4, pady=3, sticky="ew")
        if value:
            widget.insert(0, value)
        self.girdiler[field] = widget
        return widget

    def _baslik_alanlari(self):
        frame = ttk.LabelFrame(self.icerik, text="İrsaliye Bilgileri", padding=8)
        frame.pack(fill="x", pady=4)
        no = self.irsaliye.irsaliye_no if self.irsaliye else "Otomatik oluşturulacak"
        self._girdi(frame, 0, 0, "İrsaliye No", "irsaliye_no", no)
        self._girdi(
            frame,
            0,
            1,
            "Tarih",
            "irsaliye_tarihi",
            _tarih(self.irsaliye.irsaliye_tarihi) if self.irsaliye else date.today().strftime("%d.%m.%Y"),
        )
        ttk.Label(frame, text="Depo").grid(row=0, column=4, padx=4, sticky="w")
        self.depo = ttk.Combobox(frame, values=self.depolar, width=18)
        self.depo.grid(row=0, column=5, padx=4, sticky="ew")
        self.depo.set(
            getattr(self.irsaliye, "depo", None) if self.irsaliye else (self.depolar[0] if self.depolar else "ANA DEPO")
        )
        ttk.Label(frame, text="Durum").grid(row=0, column=6, padx=4, sticky="w")
        self.durum_cb = ttk.Combobox(
            frame, textvariable=self._durum_var, values=list(IRSALIYE_DURUMLARI) + ["AÇIK"], state="readonly", width=18
        )
        self.durum_cb.grid(row=0, column=7, padx=4, sticky="ew")
        self.durum_cb.bind("<<ComboboxSelected>>", lambda _e: self._durum_rozet_guncelle())

        ttk.Label(frame, text="Müşteri").grid(row=1, column=0, padx=4, sticky="w")
        self.musteri = ttk.Combobox(frame, values=list(self.musteri_map), state="readonly", width=36)
        self.musteri.grid(row=1, column=1, columnspan=3, padx=4, sticky="ew")
        self.musteri.bind("<<ComboboxSelected>>", lambda _e: self._musteri_degisti())
        self._girdi(frame, 1, 2, "Bakiye", "bakiye", "0,00 TL", width=16)
        self.girdiler["bakiye"].configure(state="readonly")

        ttk.Label(frame, text="Sipariş").grid(row=2, column=0, padx=4, sticky="w")
        self.siparis_secimi = ttk.Combobox(
            frame, values=list(self.siparis_map), state="readonly", width=28
        )
        self.siparis_secimi.grid(row=2, column=1, padx=4, sticky="ew")
        self.siparis_secimi.bind("<<ComboboxSelected>>", lambda _e: self.siparisi_secildi())
        ttk.Checkbutton(
            frame, text="Fiyatlı irsaliye (müşteri PDF)", variable=self._is_priced
        ).grid(row=2, column=2, columnspan=2, sticky="w", padx=4)
        for c in (1, 3, 5, 7):
            frame.columnconfigure(c, weight=1)

    def _sevk_adres_alanlari(self):
        frame = ttk.LabelFrame(self.icerik, text="Sevk / Teslimat", padding=8)
        frame.pack(fill="x", pady=4)
        self._girdi(frame, 0, 0, "Sevk Adresi", "sevk_adresi", width=40)
        self._girdi(frame, 0, 1, "İl", "sevk_il", width=14)
        self._girdi(frame, 0, 2, "İlçe", "sevk_ilce", width=14)
        self._girdi(frame, 1, 0, "Teslim Kişi", "teslim_kisi")
        self._girdi(frame, 1, 1, "Telefon", "teslim_telefon")
        self._girdi(frame, 1, 2, "Sevkiyat Yöntemi", "sevkiyat_yontemi")
        self._girdi(frame, 2, 0, "Nakliyeci", "nakliyeci")
        self._girdi(frame, 2, 1, "Plaka", "arac_plaka", width=14)
        self._girdi(frame, 2, 2, "Şoför", "sofor_adi")
        self._girdi(frame, 3, 0, "Şoför Tel", "sofor_telefon")
        self._girdi(frame, 3, 1, "Takip No", "takip_no")
        self._girdi(frame, 3, 2, "Planlanan Teslim", "planlanan_teslim")

    def _satir_alani(self):
        frame = ttk.LabelFrame(self.icerik, text="İrsaliye Satırları", padding=8)
        frame.pack(fill="both", expand=True, pady=4)
        # Barkod önce — 13 haneli okuyucu Enter ile ürünü doldurur
        alanlar = (
            ("Barkod", "barkod"),
            ("Ürün Kodu", "urun_kodu"),
            ("Ürün Adı", "urun_adi"),
            ("Açıklama", "aciklama"),
            ("Miktar", "miktar"),
            ("Birim", "birim"),
            ("Birim Fiyat", "birim_fiyat"),
            ("İskonto %", "iskonto_orani"),
            ("KDV %", "kdv_orani"),
            ("Lot", "lot_no"),
        )
        for col, (label, field) in enumerate(alanlar):
            ttk.Label(frame, text=label).grid(row=0, column=col, padx=2, sticky="w")
            if field == "birim":
                w = ttk.Combobox(frame, values=BIRIM_SECENEKLERI, state="readonly", width=8)
                w.set("Adet")
            elif field == "barkod":
                w = ttk.Entry(frame, width=16)
            else:
                w = ttk.Entry(frame, width={1: 10, 2: 20, 3: 12}.get(col, 8))
            w.grid(row=1, column=col, padx=2, sticky="ew")
            self.satir_girdileri[field] = w
            if field in ("urun_kodu", "urun_adi"):
                w.bind("<KeyRelease>", self.urun_arama_ac)
            if field == "barkod":
                w.bind("<Return>", self.barkoddan_satir_bul)
                w.bind("<KeyRelease>", self._barkod_otomatik)
            if field == "birim_fiyat":
                w.bind("<F10>", self.fiyat_secimi_ac)
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        btn = ttk.Frame(frame)
        btn.grid(row=2, column=0, columnspan=10, sticky="w", pady=4)
        ttk.Button(btn, text="Ekle/Güncelle", command=self.satir_ekle).pack(side="left", padx=2)
        ttk.Button(btn, text="Temizle", command=self.satir_temizle).pack(side="left", padx=2)
        ttk.Button(btn, text="STOK LİSTESİ", command=self.stok_listesi_ac).pack(side="left", padx=6)
        kolonlar = (
            "kod",
            "ad",
            "aciklama",
            "miktar",
            "birim",
            "fiyat",
            "iskonto",
            "kdv",
            "toplam",
            "fatura",
            "kalan",
            "lot",
        )
        self.satir_tablosu = ttk.Treeview(frame, columns=kolonlar, show="headings", height=10)
        basliklar = (
            "Kod",
            "Ürün Adı",
            "Açıklama",
            "Miktar",
            "Birim",
            "Fiyat",
            "İsk%",
            "KDV%",
            "Toplam",
            "Faturalanan",
            "Kalan",
            "Lot",
        )
        for col, label in zip(kolonlar, basliklar):
            self.satir_tablosu.heading(col, text=label)
            self.satir_tablosu.column(col, width=90 if col != "ad" else 180, stretch=(col == "ad"))
        self.satir_tablosu.grid(row=3, column=0, columnspan=10, sticky="nsew", pady=4)
        self.satir_tablosu.bind("<<TreeviewSelect>>", self.satir_secildi)
        ttk.Button(frame, text="Satır Düzenle", command=self.satir_duzenle).grid(
            row=4, column=0, sticky="w"
        )
        ttk.Button(frame, text="Satır Kaldır", command=self.satir_kaldir).grid(
            row=4, column=1, sticky="w"
        )
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(2, weight=1)

    def _notlar_ve_toplam(self):
        frame = ttk.LabelFrame(self.icerik, text="Notlar ve Toplamlar", padding=8)
        frame.pack(fill="x", pady=4)
        ttk.Label(frame, text="Müşteri Notu").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text="Sevk Notu").grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text="İç Not (müşteriye gitmez)").grid(row=0, column=2, sticky="w")
        self.musteri_notu = tk.Text(frame, height=3, width=36)
        self.musteri_notu.grid(row=1, column=0, padx=4, sticky="ew")
        self.sevk_notu = tk.Text(frame, height=3, width=36)
        self.sevk_notu.grid(row=1, column=1, padx=4, sticky="ew")
        self.ic_not = tk.Text(frame, height=3, width=36)
        self.ic_not.grid(row=1, column=2, padx=4, sticky="ew")
        self._girdi(frame, 2, 0, "Genel Açıklama", "aciklama", width=40)
        self.toplam = ttk.Label(
            frame, text="Ara: 0,00 | KDV: 0,00 | Genel: 0,00", font=("Segoe UI", 10, "bold")
        )
        self.toplam.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

    def _musteri_degisti(self):
        self.bakiye_guncelle()
        m = self.musteri_map.get(self.musteri.get())
        if m:
            self._sevk_adres_cari_doldur(m)

    def _sevk_adres_cari_doldur(self, cari):
        if not self.girdiler.get("sevk_adresi").get().strip():
            self.girdiler["sevk_adresi"].insert(0, getattr(cari, "adres", None) or "")
        if not self.girdiler.get("sevk_il").get().strip():
            self.girdiler["sevk_il"].insert(0, getattr(cari, "il", None) or "")
        if not self.girdiler.get("sevk_ilce").get().strip():
            self.girdiler["sevk_ilce"].insert(0, getattr(cari, "ilce", None) or "")

    def urun_arama_ac(self, _event):
        widget = self.focus_get()
        query = widget.get().strip() if widget else ""
        if len(query) < 2:
            return
        if widget is self.satir_girdileri.get("urun_kodu"):
            UrunSecDialog(self, on_select=self.urun_secildi, kod=query)
        elif widget is self.satir_girdileri.get("urun_adi"):
            UrunSecDialog(self, on_select=self.urun_secildi, ad=query)
        else:
            UrunSecDialog(self, query, self.urun_secildi)

    def stok_listesi_ac(self):
        """Tüm stok kartlarını listeler (barkod / kod / ad aramasından bağımsız)."""
        if getattr(self, "_urun_sec_pencere", None):
            try:
                if self._urun_sec_pencere.winfo_exists():
                    self._urun_sec_pencere.lift()
                    return
            except tk.TclError:
                self._urun_sec_pencere = None
        depo = ""
        if "depo" in self.girdiler:
            depo = self.girdiler["depo"].get().strip()
        dialog = UrunSecDialog(
            self,
            on_select=self.urun_secildi,
            depo_ad=depo or None,
        )
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None
        try:
            self.satir_girdileri["miktar"].focus_set()
        except tk.TclError:
            pass

    def _barkod_otomatik(self, _event=None):
        """13 hane dolunca (Enter olmadan da) ürünü getir — el tipi okuyucu desteği."""
        w = self.satir_girdileri.get("barkod")
        if w is None:
            return
        kod = w.get().strip()
        if len(kod) == 13 and kod.isdigit():
            self.barkoddan_satir_bul()

    def barkoddan_satir_bul(self, _event=None):
        from database.stok_service import StokService

        barkod = self.satir_girdileri["barkod"].get().strip()
        if not barkod:
            return "break"
        bulunan = StokService.barkod_ile_bul(barkod)
        if bulunan:
            self._urun_alanlarini_doldur(
                kod=bulunan.get("stok_kodu") or "",
                ad=bulunan.get("stok_adi") or "",
                birim=bulunan.get("birim") or "Adet",
                fiyat=bulunan.get("birim_fiyat"),
                kdv=bulunan.get("kdv_orani"),
                barkod=barkod,
                miktar=bulunan.get("miktar") or 1,
            )
            try:
                self.satir_girdileri["miktar"].focus_set()
                self.satir_girdileri["miktar"].selection_range(0, "end")
            except tk.TclError:
                pass
            return "break"
        # Tam eşleşme yoksa genel arama
        liste = [
            s
            for s in StokService.stoklari_ara(barkod)
            if (s.barkod or "").strip() == barkod
        ]
        if not liste:
            liste = StokService.stoklari_ara(barkod)
        if not liste:
            messagebox.showinfo("Barkod", "Bu barkoda ait stok bulunamadı.", parent=self)
            return "break"
        stok = liste[0]
        try:
            fiyat = StokService.satis_fiyati_1(stok.stok_kodu, Decimal("0"))
        except Exception:
            fiyat = Decimal("0")
        self._urun_alanlarini_doldur(
            kod=stok.stok_kodu,
            ad=stok.stok_adi,
            birim=stok.birim or "Adet",
            fiyat=fiyat,
            kdv=getattr(stok, "kdv_orani", None),
            barkod=(stok.barkod or barkod),
            miktar=1,
        )
        try:
            self.satir_girdileri["miktar"].focus_set()
            self.satir_girdileri["miktar"].selection_range(0, "end")
        except tk.TclError:
            pass
        return "break"

    def _urun_alanlarini_doldur(
        self, *, kod, ad, birim="Adet", fiyat=None, kdv=None, barkod=None, miktar=None
    ):
        if barkod is not None and "barkod" in self.satir_girdileri:
            self.satir_girdileri["barkod"].delete(0, "end")
            self.satir_girdileri["barkod"].insert(0, str(barkod))
        self.satir_girdileri["urun_kodu"].delete(0, "end")
        self.satir_girdileri["urun_kodu"].insert(0, kod or "")
        self.satir_girdileri["urun_adi"].delete(0, "end")
        self.satir_girdileri["urun_adi"].insert(0, ad or "")
        self.satir_girdileri["birim"].set((birim or "Adet").strip() or "Adet")
        if fiyat is not None:
            self.satir_girdileri["birim_fiyat"].delete(0, "end")
            tutar = f"{Decimal(str(fiyat or 0)):f}".rstrip("0").rstrip(".") or "0"
            self.satir_girdileri["birim_fiyat"].insert(0, tutar)
        if kdv is not None:
            self.satir_girdileri["kdv_orani"].delete(0, "end")
            kdv_m = f"{Decimal(str(kdv)):f}".rstrip("0").rstrip(".") or "20"
            self.satir_girdileri["kdv_orani"].insert(0, kdv_m)
        if miktar is not None:
            self.satir_girdileri["miktar"].delete(0, "end")
            m = f"{Decimal(str(miktar)):f}".rstrip("0").rstrip(".") or "1"
            self.satir_girdileri["miktar"].insert(0, m)

    def urun_secildi(self, values):
        kod = values[0] if values else ""
        ad = values[1] if len(values) > 1 else ""
        birim = values[2] if len(values) > 2 else "Adet"
        fiyat = values[4] if len(values) > 4 else ""
        barkod = ""
        try:
            from database.stok_service import StokService

            kartlar = StokService.stoklari_ara(kod) if kod else []
            kart = next((s for s in kartlar if (s.stok_kodu or "") == kod), None)
            if kart and kart.barkod:
                barkod = kart.barkod
        except Exception:
            pass
        self._urun_alanlarini_doldur(
            kod=kod,
            ad=ad,
            birim=birim or "Adet",
            fiyat=fiyat if fiyat not in (None, "") else None,
            barkod=barkod or None,
            miktar=None,
        )
        if not self.satir_girdileri["miktar"].get().strip():
            self.satir_girdileri["miktar"].insert(0, "1")
        try:
            self.satir_girdileri["miktar"].focus_set()
        except tk.TclError:
            pass

    def fiyat_secimi_ac(self, _event):
        from app import PriceSelectionDialog

        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(self, kod, on_select=self.fiyati_secildi, fiyat_turu="satis")
        self.wait_window(dialog)
        return "break"

    def fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_fiyat"]
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)

    def satir_ekle(self):
        veri = {
            f: w.get().strip()
            for f, w in self.satir_girdileri.items()
            if f != "barkod"
        }
        if not veri["urun_kodu"] or not veri["urun_adi"]:
            messagebox.showwarning("Eksik bilgi", "Ürün kodu ve adı zorunludur.", parent=self)
            return
        if not veri.get("miktar"):
            messagebox.showwarning("Miktar", "Miktar girin.", parent=self)
            return
        try:
            decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
            decimal(veri["birim_fiyat"] or 0, "Birim fiyat", Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        secim = self.satir_tablosu.selection()
        if secim:
            eski = self.satirlar[int(secim[0])]
            veri["siparis_satiri_id"] = eski.get("siparis_satiri_id")
            veri["faturalanan_miktar"] = eski.get("faturalanan_miktar", 0)
            self.satirlar[int(secim[0])] = veri
        else:
            veri["siparis_satiri_id"] = None
            self.satirlar.append(veri)
        self.satir_temizle()
        self.satir_listesini_yenile()
        try:
            self.satir_girdileri["barkod"].focus_set()
        except tk.TclError:
            pass

    def satir_temizle(self):
        for field, widget in self.satir_girdileri.items():
            if field == "birim":
                widget.set("Adet")
            else:
                widget.delete(0, "end")
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())

    def satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for index, veri in enumerate(self.satirlar):
            miktar = decimal(veri["miktar"], "Miktar")
            fiyat = decimal(veri.get("birim_fiyat") or 0, "Birim fiyat")
            iskonto = decimal(veri.get("iskonto_orani") or 0, "İskonto")
            kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
            net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100))
            toplam = net * (Decimal(1) + kdv / Decimal(100))
            fatura = decimal(veri.get("faturalanan_miktar") or 0, "Faturalanan")
            self.satir_tablosu.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    veri["urun_kodu"],
                    veri["urun_adi"],
                    veri.get("aciklama", ""),
                    miktar,
                    veri["birim"],
                    _para(fiyat),
                    f"{iskonto}%",
                    f"{kdv}%",
                    _para(toplam),
                    fatura,
                    miktar - fatura,
                    veri.get("lot_no", ""),
                ),
            )
        self.toplam_guncelle()

    def toplam_guncelle(self):
        ara = Decimal("0")
        kdv_toplam = Decimal("0")
        for veri in self.satirlar:
            miktar = decimal(veri["miktar"], "Miktar")
            fiyat = decimal(veri.get("birim_fiyat") or 0, "Birim fiyat")
            iskonto = decimal(veri.get("iskonto_orani") or 0, "İskonto")
            kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
            net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100))
            ara += net
            kdv_toplam += net * kdv / Decimal(100)
        self.toplam.configure(
            text=f"Ara: {_para(ara)} | KDV: {_para(kdv_toplam)} | Genel: {_para(ara + kdv_toplam)}"
        )

    def satir_secildi(self, _event=None):
        secim = self.satir_tablosu.selection()
        if not secim:
            return
        self.satir_temizle()
        veri = self.satirlar[int(secim[0])]
        for field, widget in self.satir_girdileri.items():
            deger = str(veri.get(field, "") or "")
            if field == "birim":
                if deger and deger not in BIRIM_SECENEKLERI:
                    widget["values"] = BIRIM_SECENEKLERI + (deger,)
                widget.set(deger or "Adet")
            else:
                widget.insert(0, deger)

    def satir_duzenle(self):
        self.satir_secildi()

    def satir_kaldir(self):
        secim = self.satir_tablosu.selection()
        if secim and messagebox.askyesno("Satır kaldır", "Seçili satır kaldırılsın mı?", parent=self):
            self.satirlar.pop(int(secim[0]))
            self.satir_listesini_yenile()

    def _siparisten_doldur(self, siparis):
        self.siparis_secimi.set(siparis.siparis_no)
        self.musteri.set(f"{siparis.cari.cari_kodu} - {siparis.cari.unvan}")
        self.bakiye_guncelle()
        self._sevk_adres_cari_doldur(siparis.cari)
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.irsaliyelenen_miktar
            if acik > 0:
                self.satirlar.append(
                    {
                        "siparis_satiri_id": satir.id,
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "aciklama": satir.aciklama or "",
                        "miktar": acik,
                        "birim": satir.birim,
                        "birim_fiyat": satir.birim_satis_fiyati,
                        "iskonto_orani": satir.iskonto_orani,
                        "kdv_orani": satir.kdv_orani,
                        "siparis_miktar": satir.miktar,
                        "onceki_sevk": satir.irsaliyelenen_miktar,
                        "lot_no": "",
                    }
                )
        self.satir_listesini_yenile()

    def siparisi_secildi(self):
        siparis = self.siparis_map.get(self.siparis_secimi.get())
        if siparis:
            self._siparisten_doldur(siparis)

    def bakiye_guncelle(self):
        musteri = self.musteri_map.get(self.musteri.get())
        bakiye = SatisIrsaliyesiService.mevcut_bakiye(musteri.id) if musteri else Decimal("0")
        self.girdiler["bakiye"].configure(state="normal")
        self.girdiler["bakiye"].delete(0, "end")
        self.girdiler["bakiye"].insert(0, _para(bakiye))
        self.girdiler["bakiye"].configure(state="readonly")

    def _doldur(self):
        ir = self.irsaliye
        self.musteri.set(f"{ir.cari.cari_kodu} - {ir.cari.unvan}")
        self.bakiye_guncelle()
        self.girdiler["irsaliye_tarihi"].delete(0, "end")
        self.girdiler["irsaliye_tarihi"].insert(0, _tarih(ir.irsaliye_tarihi))
        self.siparis_secimi.set(ir.siparis.siparis_no if ir.siparis else "")
        self._durum_var.set(ir.durum)
        if getattr(ir, "depo", None):
            self.depo.set(ir.depo)
        self._is_priced.set(bool(getattr(ir, "is_priced", True)))
        for alan in (
            "sevk_adresi",
            "sevk_il",
            "sevk_ilce",
            "teslim_kisi",
            "teslim_telefon",
            "sevkiyat_yontemi",
            "nakliyeci",
            "arac_plaka",
            "sofor_adi",
            "sofor_telefon",
            "takip_no",
            "aciklama",
        ):
            w = self.girdiler.get(alan)
            if w is None:
                continue
            w.delete(0, "end")
            deger = getattr(ir, alan, None)
            if alan == "aciklama":
                deger = ir.aciklama
            if deger:
                w.insert(0, deger)
        if getattr(ir, "planlanan_teslim", None):
            self.girdiler["planlanan_teslim"].delete(0, "end")
            self.girdiler["planlanan_teslim"].insert(0, _tarih(ir.planlanan_teslim))
        self.musteri_notu.insert("1.0", getattr(ir, "musteri_notu", None) or ir.ayrintili_notlar or "")
        self.sevk_notu.insert("1.0", getattr(ir, "sevk_notu", None) or "")
        self.ic_not.insert("1.0", getattr(ir, "ic_not", None) or "")
        for satir in ir.satirlar:
            self.satirlar.append(
                {
                    "siparis_satiri_id": satir.siparis_satiri_id,
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "aciklama": satir.aciklama or "",
                    "miktar": satir.miktar,
                    "birim": satir.birim,
                    "birim_fiyat": satir.birim_fiyat,
                    "iskonto_orani": satir.iskonto_orani,
                    "kdv_orani": satir.kdv_orani,
                    "faturalanan_miktar": satir.faturalanan_miktar,
                    "lot_no": getattr(satir, "lot_no", None) or "",
                    "depo": getattr(satir, "depo", None) or "",
                }
            )
        self.satir_listesini_yenile()
        self._durum_rozet_guncelle()
        self._meta_yenile()

    def _veri_topla(self) -> tuple[dict, list]:
        tarih = datetime.strptime(self.girdiler["irsaliye_tarihi"].get().strip(), "%d.%m.%Y").date()
        musteri = self.musteri_map.get(self.musteri.get())
        if not musteri:
            raise ValueError("Müşteri seçin.")
        plan = self.girdiler["planlanan_teslim"].get().strip()
        planlanan = datetime.strptime(plan, "%d.%m.%Y").date() if plan else None
        veriler = {
            "irsaliye_tarihi": tarih,
            "cari_id": musteri.id,
            "siparis_id": self.siparis_map.get(self.siparis_secimi.get()).id
            if self.siparis_secimi.get()
            else None,
            "aciklama": self.girdiler["aciklama"].get().strip(),
            "ayrintili_notlar": self.musteri_notu.get("1.0", "end").strip(),
            "musteri_notu": self.musteri_notu.get("1.0", "end").strip(),
            "sevk_notu": self.sevk_notu.get("1.0", "end").strip(),
            "ic_not": self.ic_not.get("1.0", "end").strip(),
            "depo": self.depo.get().strip() or "ANA DEPO",
            "is_priced": bool(self._is_priced.get()),
            "sevk_adresi": self.girdiler["sevk_adresi"].get().strip(),
            "sevk_il": self.girdiler["sevk_il"].get().strip(),
            "sevk_ilce": self.girdiler["sevk_ilce"].get().strip(),
            "teslim_kisi": self.girdiler["teslim_kisi"].get().strip(),
            "teslim_telefon": self.girdiler["teslim_telefon"].get().strip(),
            "sevkiyat_yontemi": self.girdiler["sevkiyat_yontemi"].get().strip(),
            "nakliyeci": self.girdiler["nakliyeci"].get().strip(),
            "arac_plaka": self.girdiler["arac_plaka"].get().strip(),
            "sofor_adi": self.girdiler["sofor_adi"].get().strip(),
            "sofor_telefon": self.girdiler["sofor_telefon"].get().strip(),
            "takip_no": self.girdiler["takip_no"].get().strip(),
            "planlanan_teslim": planlanan,
        }
        ozel = self.girdiler["irsaliye_no"].get().strip()
        if ozel and ozel != "Otomatik oluşturulacak":
            veriler["irsaliye_no"] = ozel
        return veriler, self.satirlar

    def kaydet(self):
        try:
            veriler, satirlar = self._veri_topla()
            kayit = SatisIrsaliyesiService.kaydet(
                veriler, satirlar, self.irsaliye.id if self.irsaliye else None
            )
        except ValueError as hata:
            messagebox.showerror("İrsaliye kaydedilemedi", str(hata), parent=self)
            return
        self.irsaliye = kayit
        self._durum_var.set(kayit.durum)
        self._durum_rozet_guncelle()
        self._meta_yenile()
        self.result = True
        messagebox.showinfo("Kayıt", "İrsaliye taslak olarak kaydedildi (stok çıkışı yok).", parent=self)

    def hazirla(self):
        if not self._ensure_saved():
            return
        try:
            self.irsaliye = SatisIrsaliyesiService.hazirla(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Hazırlık", str(hata), parent=self)
            return
        self._durum_var.set(self.irsaliye.durum)
        self._durum_rozet_guncelle()
        self.result = True
        messagebox.showinfo("Hazırlık", "İrsaliye sevkiyata hazırlandı.", parent=self)

    def sevk_et(self):
        if not self._ensure_saved():
            return
        if not messagebox.askyesno(
            "Sevk Et",
            "Stok çıkışı yapılacak (İRSALİYE ÇIKIŞ). Devam edilsin mi?",
            parent=self,
        ):
            return
        try:
            self.irsaliye = SatisIrsaliyesiService.sevk_et(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Sevk", str(hata), parent=self)
            return
        self._durum_var.set(self.irsaliye.durum)
        self._durum_rozet_guncelle()
        self._meta_yenile()
        self.result = True
        messagebox.showinfo("Sevk", "İrsaliye sevk edildi; stok çıkışı kaydedildi.", parent=self)

    def teslim_et(self):
        if not self.irsaliye:
            messagebox.showinfo("Teslim", "Önce kaydedin.", parent=self)
            return
        try:
            self.irsaliye = SatisIrsaliyesiService.teslim_et(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Teslim", str(hata), parent=self)
            return
        self._durum_var.set(self.irsaliye.durum)
        self._durum_rozet_guncelle()
        self.result = True

    def fatura_olustur(self):
        if not self.irsaliye:
            messagebox.showinfo("Fatura", "Önce irsaliyeyi kaydedin.", parent=self)
            return
        try:
            from app import SatisFaturasiDialog, CariDialog
        except Exception:
            messagebox.showerror("Fatura", "Fatura diyaloğu açılamadı.", parent=self)
            return
        dialog = SatisFaturasiDialog(
            self, irsaliye=self.irsaliye, cari_ac=lambda c: CariDialog(self, c)
        )
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.result = True
            self.irsaliye = SatisIrsaliyesiService.getir(self.irsaliye.id)
            if self.irsaliye:
                self._durum_var.set(self.irsaliye.durum)
                self._durum_rozet_guncelle()

    def iptal_et(self):
        if not self.irsaliye:
            messagebox.showinfo("İptal", "Kayıtlı irsaliye yok.", parent=self)
            return
        if not messagebox.askyesno("İptal", "İrsaliye iptal edilsin mi?", parent=self):
            return
        sebep = simpledialog.askstring("İptal — Sebep", "İptal nedenini yazın (zorunlu):", parent=self)
        if not (sebep or "").strip():
            messagebox.showwarning("İptal", "İptal nedeni girilmeden iptal yapılmaz.", parent=self)
            return
        try:
            SatisIrsaliyesiService.iptal_et(self.irsaliye.id, sebep=sebep.strip())
        except ValueError as hata:
            messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
            return
        self.result = True
        self.destroy()

    def _ensure_saved(self) -> bool:
        if self.irsaliye and self.irsaliye.id:
            return True
        self.kaydet()
        return bool(self.irsaliye and self.irsaliye.id)

    def onizleme(self):
        from database.irsaliye_customer_view import (
            CustomerDispatchSecurityError,
            assert_customer_dispatch_safe,
            build_customer_dispatch_from_dialog,
            render_customer_dispatch_html,
        )

        try:
            vm = build_customer_dispatch_from_dialog(self)
            html_metin = render_customer_dispatch_html(vm)
            assert_customer_dispatch_safe(vm, html_metin)
        except (CustomerDispatchSecurityError, ValueError) as exc:
            messagebox.showerror("Önizleme", str(exc), parent=self)
            return
        yol = Path(tempfile.gettempdir()) / f"irsaliye_onizleme_{datetime.now():%H%M%S}.html"
        yol.write_text(html_metin, encoding="utf-8")
        win = tk.Toplevel(self)
        win.title("Müşteri İrsaliye Ön İzlemesi")
        win.geometry("900x700")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", "Önizleme tarayıcıda açıldı.\n\n" + html_metin[:2000])
        webbrowser.open(yol.as_uri())

    def pdf_kaydet(self):
        from database.irsaliye_customer_view import (
            CustomerDispatchSecurityError,
            assert_customer_dispatch_safe,
            build_customer_dispatch_from_dialog,
            render_customer_dispatch_html,
        )

        try:
            vm = build_customer_dispatch_from_dialog(self)
            html_metin = render_customer_dispatch_html(vm)
            assert_customer_dispatch_safe(vm, html_metin)
        except (CustomerDispatchSecurityError, ValueError) as exc:
            messagebox.showerror("PDF", str(exc), parent=self)
            return
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("Tüm dosyalar", "*.*")],
            initialfile=f"Sevk_Irsaliyesi_{(getattr(self.irsaliye, 'irsaliye_no', None) or 'yeni')}.html",
        )
        if not yol:
            return
        Path(yol).write_text(html_metin, encoding="utf-8")
        messagebox.showinfo("PDF", f"Müşteri irsaliye belgesi kaydedildi:\n{yol}", parent=self)
        webbrowser.open(Path(yol).as_uri())
