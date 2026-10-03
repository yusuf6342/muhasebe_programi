"""Alış İade Faturası (Tedarikçiye İade) ekranı ve ayrı liste ekranı.

- Menüden her açılış yeni boş taslaktır; açılışta stok/cari/fiş oluşmaz.
- Kaydet taslak yazar ve belge açık kalır; stok/cari/muhasebe etkisi yalnız Onayla ile oluşur.
- Kaynaksız ürünlerde kullanıcıya Kaynak Seç / Gerekçeyle Devam Et / Vazgeç sorulur.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk
from birim_hatasi_ui import birim_hatasi_goster

from database.access import AccessError, maliyet_izinli, yetki_var
from database.alis_iade_faturasi_service import (
    BASKA_TEDARIKCI,
    DEVIR,
    KAYNAK_YOK_MESAJI,
    KAYNAKLI,
    KAYNAKSIZ,
    AlisIadeFaturasiService as S,
    IadeDegisti,
    KaynakTercihiGerekli,
)
from fatura_tema import (
    ACIK_BG,
    BEYAZ,
    IKINCIL,
    IPTAL as KIRMIZI,
    LACIVERT,
    SARI,
    beyaz_kart,
    font,
    rozet_guncelle,
    stil_uygula,
    tk_buton,
    ust_toolbar,
)

BASLIK = "ALIŞ İADE FATURASI · TEDARİKÇİYE İADE"
IADE_NEDENLERI = ("Hasarlı / kusurlu ürün", "Yanlış ürün gönderimi", "Fazla gönderim", "Son kullanma tarihi",
                  "Fiyat / anlaşma farkı", "Diğer")
MAHSUP_ETIKETLERI = {
    "FIFO": "En eski tedarikçi borcundan düş",
    "KAYNAK": "Kaynak alış faturasının borcundan düş",
    "AVANS": "Kapatma yapma (açık iade alacağı)",
}
PARA_BIRIMLERI = ("TRY", "USD", "EUR", "GBP")
SIFIR = Decimal("0")


def _d(deger) -> Decimal:
    if deger in (None, ""):
        return SIFIR
    if isinstance(deger, Decimal):
        return deger
    metin = str(deger).strip().replace("₺", "").replace(" ", "")
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    try:
        return Decimal(metin)
    except InvalidOperation as hata:
        raise ValueError(f"Geçersiz sayı: {deger}") from hata


def para(deger) -> str:
    d = _d(deger).quantize(Decimal("0.01"))
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def miktar_metni(deger) -> str:
    d = _d(deger).normalize()
    return f"{d:f}".replace(".", ",")


def _tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError("Tarih GG.AA.YYYY biçiminde olmalı.")


def _ekrana_sigdir(pencere: tk.Toplevel, gen: int, yuk: int, min_gen: int = 860, min_yuk: int = 540) -> None:
    sw, sh = pencere.winfo_screenwidth(), pencere.winfo_screenheight()
    g, y = min(gen, max(min_gen, sw - 40)), min(yuk, max(min_yuk, sh - 80))
    pencere.geometry(f"{g}x{y}+{max(0, (sw - g) // 2)}+{max(0, (sh - y) // 3)}")
    pencere.minsize(min(min_gen, g), min(min_yuk, y))


# ====================================================================== diyaloglar
class KaynaksizUyariDialog(tk.Toplevel):
    """Kaynak alışı bulunmayan ürün: Kaynak Seç / Gerekçeyle Devam Et / Vazgeç.

    result: None (vazgeç) | {"kaynak_durumu": DEVIR, "kaynak_lot_id": id}
            | {"kaynak_durumu": KAYNAKSIZ|BASKA_TEDARIKCI, "kaynak_gerekce": metin}
    """

    def __init__(self, parent, urun_kodu: str, urun_adi: str, durum: dict):
        super().__init__(parent)
        self.result = None
        self.durum = durum
        self.title("Kaynak alış bulunamadı")
        self.transient(parent)
        self.configure(bg=BEYAZ)
        self.resizable(True, False)
        ic = tk.Frame(self, bg=BEYAZ, padx=14, pady=12)
        ic.pack(fill="both", expand=True)
        tk.Label(ic, text=f"{urun_kodu} — {urun_adi}", bg=BEYAZ, fg=LACIVERT,
                 font=font(11, "bold")).pack(anchor="w")
        self.mesaj = tk.Label(ic, text=KAYNAK_YOK_MESAJI, bg=BEYAZ, fg="#7A2E0E", justify="left",
                              wraplength=520, font=font(10))
        self.mesaj.pack(anchor="w", pady=(6, 6))
        baska = durum.get("baska_tedarikciler") or []
        if baska:
            tk.Label(ic, text="Bu ürün başka tedarikçiden alınmış: " + ", ".join(baska[:5])
                     + ". Başka tedarikçinin alışı bu tedarikçiye kaynak gösterilemez.",
                     bg=BEYAZ, fg=KIRMIZI, justify="left", wraplength=520).pack(anchor="w", pady=(0, 6))
        self.devirler = durum.get("devir_lotlari") or []
        self.devir_liste = None
        if self.devirler:
            tk.Label(ic, text="Devir / açılış katmanları (Kaynak Seç için birini seçin):", bg=BEYAZ,
                     fg=IKINCIL).pack(anchor="w")
            self.devir_liste = tk.Listbox(ic, height=min(5, len(self.devirler)), exportselection=False)
            for d in self.devirler:
                self.devir_liste.insert("end", f"{d['lot_no']} · {d['depo']} · kalan {miktar_metni(d['kalan'])}")
            self.devir_liste.selection_set(0)
            self.devir_liste.pack(fill="x", pady=(2, 6))
        tk.Label(ic, text="Gerekçe (bağlantısız iade için zorunlu):", bg=BEYAZ, fg=IKINCIL).pack(anchor="w")
        self.gerekce = ttk.Entry(ic, width=70)
        self.gerekce.pack(fill="x", pady=(2, 10))
        btn = tk.Frame(ic, bg=BEYAZ)
        btn.pack(fill="x")
        self.btn_kaynak = tk_buton(btn, "Kaynak Seç", self.kaynak_sec, rol="kaydet",
                                   state="normal" if self.devirler else "disabled")
        self.btn_kaynak.pack(side="left")
        self.btn_devam = tk_buton(btn, "Gerekçeyle Devam Et", self.devam, rol="uyari")
        self.btn_devam.pack(side="left", padx=8)
        self.btn_vazgec = tk_buton(btn, "Vazgeç", self.vazgec, rol="ikincil")
        self.btn_vazgec.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.vazgec)
        self.bind("<Escape>", lambda _e: self.vazgec())
        self.gerekce.focus_set()

    def kaynak_sec(self):
        if not self.devirler or self.devir_liste is None:
            return
        secim = self.devir_liste.curselection()
        if not secim:
            messagebox.showwarning("Kaynak", "Devir katmanı seçin.", parent=self)
            return
        self.result = {"kaynak_durumu": DEVIR, "kaynak_lot_id": self.devirler[secim[0]]["lot_id"],
                       "kaynak_gerekce": self.gerekce.get().strip() or None}
        self.destroy()

    def devam(self):
        gerekce = self.gerekce.get().strip()
        if not gerekce:
            messagebox.showwarning("Gerekçe", "Bağlantısız iade için gerekçe yazın.", parent=self)
            return
        tur = BASKA_TEDARIKCI if self.durum.get("baska_tedarikciler") else KAYNAKSIZ
        self.result = {"kaynak_durumu": tur, "kaynak_gerekce": gerekce}
        self.destroy()

    def vazgec(self):
        self.result = None
        self.destroy()


class KaynakSecDialog(tk.Toplevel):
    """Tedarikçinin bu ürün için alış satırlarından kaynak seçimi (çoklu kaynak alt dağılımı)."""

    KOLONLAR = (("fatura", "Alış No", 110), ("tarih", "Tarih", 82), ("depo", "Depo", 90),
                ("alinan", "Alınan", 70), ("onceki", "Önceki İade", 80), ("hak", "Kalan Hak", 76),
                ("stokta", "Depoda", 70), ("iade", "İade Edilebilir", 96), ("fiyat", "Net Fiyat", 90),
                ("miktar", "İade Miktarı", 90))

    def __init__(self, parent, urun_kodu: str, adaylar: list[dict], varsayilan: Decimal | None = None,
                 temel_birim: str = "Adet"):
        super().__init__(parent)
        self.result = None
        self.adaylar = adaylar
        self.miktarlar: dict[int, Decimal] = {}
        self.title(f"Kaynak alış seç — {urun_kodu}")
        self.transient(parent)
        self.configure(bg=BEYAZ)
        _ekrana_sigdir(self, 980, 420, 640, 320)
        ic = tk.Frame(self, bg=BEYAZ, padx=10, pady=8)
        ic.pack(fill="both", expand=True)
        tk.Label(ic, text=f"Miktarlar temel birimdedir ({temel_birim}). Satılmış, tüketilmiş veya başka depoya "
                          "aktarılmış miktar iade edilemez.", bg=BEYAZ, fg=IKINCIL).pack(anchor="w")
        btn = tk.Frame(ic, bg=BEYAZ)
        btn.pack(side="bottom", fill="x", pady=(6, 0))
        tk_buton(btn, "Seçileni Kullan", self.tamam, rol="onay").pack(side="right")
        tk_buton(btn, "Vazgeç", self.destroy, rol="ikincil").pack(side="right", padx=8)
        tk.Label(btn, text="Miktar:", bg=BEYAZ).pack(side="left")
        self.miktar = ttk.Entry(btn, width=10)
        self.miktar.pack(side="left", padx=4)
        tk_buton(btn, "Satıra Yaz", self.miktar_yaz, rol="ikincil").pack(side="left")
        self.tablo = ttk.Treeview(ic, columns=[k for k, *_ in self.KOLONLAR], show="headings", selectmode="browse")
        for k, b, w in self.KOLONLAR:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="e" if k not in ("fatura", "tarih", "depo") else "w")
        self.tablo.pack(fill="both", expand=True, pady=(6, 0))
        kalan = varsayilan
        for a in adaylar:
            m = SIFIR
            if kalan is not None and kalan > 0:
                m = min(kalan, a["iade_edilebilir_temel"])
                kalan -= m
            self.miktarlar[a["satir_id"]] = m
            self.tablo.insert("", "end", iid=str(a["satir_id"]), values=self._degerler(a))
        if adaylar:
            self.tablo.selection_set(str(adaylar[0]["satir_id"]))
        self.tablo.bind("<<TreeviewSelect>>", self._secildi)
        self._secildi()

    def _degerler(self, a):
        return (a["fatura_no"], f"{a['tarih']:%d.%m.%Y}" if a.get("tarih") else "", a.get("depo") or "",
                miktar_metni(a["alinan_temel"]), miktar_metni(a["onceki_iade_temel"]),
                miktar_metni(a["hak_temel"]),
                miktar_metni(a["stokta_temel"]) if a.get("stokta_temel") is not None else "—",
                miktar_metni(a["iade_edilebilir_temel"]), para(a["net_fiyat"]),
                miktar_metni(self.miktarlar.get(a["satir_id"], SIFIR)))

    def _secildi(self, _e=None):
        secim = self.tablo.selection()
        if secim:
            self.miktar.delete(0, "end")
            self.miktar.insert(0, miktar_metni(self.miktarlar.get(int(secim[0]), SIFIR)))

    def miktar_yaz(self):
        secim = self.tablo.selection()
        if not secim:
            return
        try:
            m = _d(self.miktar.get())
        except ValueError as hata:
            messagebox.showerror("Miktar", str(hata), parent=self)
            return
        a = next(x for x in self.adaylar if x["satir_id"] == int(secim[0]))
        if m < 0 or m > a["iade_edilebilir_temel"]:
            messagebox.showwarning("Miktar", f"İade edilebilir en fazla {miktar_metni(a['iade_edilebilir_temel'])}.",
                                   parent=self)
            return
        self.miktarlar[a["satir_id"]] = m
        self.tablo.item(secim[0], values=self._degerler(a))

    def tamam(self):
        self.miktar_yaz()
        secilen = [(a, self.miktarlar[a["satir_id"]]) for a in self.adaylar if self.miktarlar.get(a["satir_id"], 0) > 0]
        if not secilen:
            messagebox.showwarning("Kaynak", "En az bir kaynakta iade miktarı girin.", parent=self)
            return
        self.result = secilen
        self.destroy()


class SatirDuzenleDialog(tk.Toplevel):
    def __init__(self, parent, satir: dict, birimler: list[str]):
        super().__init__(parent)
        self.result = None
        self.title(f"Satır — {satir.get('urun_kodu')}")
        self.transient(parent)
        self.configure(bg=BEYAZ)
        ic = tk.Frame(self, bg=BEYAZ, padx=12, pady=10)
        ic.pack(fill="both", expand=True)
        self.alanlar = {}
        for sira, (anahtar, etiket) in enumerate((
                ("miktar", "Miktar"), ("birim", "Birim"), ("birim_fiyat", "Birim Fiyat (TL)"),
                ("iskonto_orani", "İskonto 1 %"), ("iskonto_orani_2", "İskonto 2 %"),
                ("iskonto_orani_3", "İskonto 3 %"), ("kdv_orani", "KDV %"))):
            tk.Label(ic, text=etiket, bg=BEYAZ).grid(row=sira, column=0, sticky="w", pady=2)
            if anahtar == "birim":
                w = ttk.Combobox(ic, values=birimler, state="readonly", width=14)
                w.set(satir.get("birim") or (birimler[0] if birimler else "Adet"))
            else:
                w = ttk.Entry(ic, width=16)
                w.insert(0, miktar_metni(satir.get(anahtar) or 0))
            w.grid(row=sira, column=1, sticky="w", padx=8, pady=2)
            self.alanlar[anahtar] = w
        btn = tk.Frame(ic, bg=BEYAZ)
        btn.grid(row=10, column=0, columnspan=2, sticky="e", pady=(8, 0))
        tk_buton(btn, "Tamam", self.tamam, rol="onay").pack(side="right")
        tk_buton(btn, "Vazgeç", self.destroy, rol="ikincil").pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self.tamam())
        self.alanlar["miktar"].focus_set()

    def tamam(self):
        try:
            sonuc = {k: (w.get() if k == "birim" else _d(w.get())) for k, w in self.alanlar.items()}
        except ValueError as hata:
            messagebox.showerror("Satır", str(hata), parent=self)
            return
        if sonuc["miktar"] <= 0:
            messagebox.showwarning("Satır", "İade miktarı sıfırdan büyük olmalı.", parent=self)
            return
        self.result = sonuc
        self.destroy()


# ====================================================================== belge penceresi
class AlisIadeFaturasiPenceresi(tk.Toplevel):
    """Yeni (boş) veya mevcut alış iadesi. ``result`` kayıt yapıldıysa True olur."""

    SATIR_KOLONLARI = (("kod", "Kod", 90), ("barkod", "Barkod", 100), ("ad", "Ürün", 200),
                       ("miktar", "Miktar", 64), ("birim", "Birim", 56), ("temel", "Temel Karş.", 80),
                       ("fiyat", "Fiyat", 84), ("isk", "İsk.", 64), ("net_fiyat", "Net Fiyat", 84),
                       ("kdv", "KDV", 46), ("net_tutar", "Net Tutar", 96), ("kaynak", "Kaynak", 190))

    def __init__(self, parent, iade=None, kaynak_fatura=None, *, iade_id: int | None = None):
        super().__init__(parent)
        stil_uygula(root=self)
        self.result = None
        self.configure(bg=ACIK_BG)
        self.title(BASLIK)
        _ekrana_sigdir(self, 1320, 820)
        self.iade = S.getir(iade_id) if iade_id else (S.getir(iade.id) if iade is not None else None)
        self.satirlar: list[dict] = []
        self._kirli = False
        self._yukleniyor = True
        self._maliyet_goster = maliyet_izinli()
        self._kartlar: dict[str, object] = {}
        self._tedarikciler = list(S.aktif_tedarikcileri())
        if self.iade is not None and self.iade.cari is not None and self.iade.cari not in self._tedarikciler:
            self._tedarikciler.append(self.iade.cari)
        if kaynak_fatura is not None and kaynak_fatura.cari is not None and kaynak_fatura.cari not in self._tedarikciler:
            self._tedarikciler.append(kaynak_fatura.cari)
        self._ted_map = {f"{c.cari_kodu} - {c.unvan}": c for c in self._tedarikciler}
        self._kur()
        if self.iade is not None:
            self._doldur()
        elif kaynak_fatura is not None:
            self._kaynak_faturadan(kaynak_fatura)
        self._yukleniyor = False
        self._durum_uygula()
        self.protocol("WM_DELETE_WINDOW", self.kapat)
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<F2>", lambda _e: self.urun_ekle())
        self.bind("<Delete>", lambda _e: self.satir_sil() if self.focus_get() is self.tablo else None)

    # ---------------------------------------------------------------- arayüz
    def _kur(self):
        self.ust = ust_toolbar(self, baslik=BASLIK, fatura_no="Yeni (kaydedilmedi)", durum="TASLAK")
        # Belge işlemleri: her zaman görünür (küçük ekranda da) — içerikten önce yerleşir
        self.btn_cubugu = tk.Frame(self, bg=ACIK_BG)
        self.btn_cubugu.pack(side="top", fill="x", padx=8, pady=(6, 2))
        self.butonlar: dict[str, tk.Button] = {}
        for anahtar, metin, komut, rol in (
                ("yeni", "Yeni", self.yeni, "ikincil"), ("kaydet", "Kaydet", self.kaydet, "kaydet"),
                ("onayla", "Onayla", self.onayla, "onay"), ("iptal", "İptal", self.iptal, "tehlike"),
                ("yazdir", "Yazdır", self.yazdir, "yazdir"), ("liste", "Liste", self.liste, "ikincil"),
                ("fis", "Muhasebe Fişi", self.muhasebe_fisi, "ikincil"), ("kapat", "Kapat", self.kapat, "ikincil")):
            b = tk_buton(self.btn_cubugu, metin, komut, rol=rol)
            b.pack(side="left", padx=(0, 6))
            self.butonlar[anahtar] = b
        self.durum_yazi = tk.Label(self.btn_cubugu, text="", bg=ACIK_BG, fg=IKINCIL, font=font(9))
        self.durum_yazi.pack(side="right")

        # Alt toplamlar: içerikten önce (alta sabit)
        alt_dis, alt = beyaz_kart(self, padx=10, pady=6)
        alt_dis.pack(side="bottom", fill="x", padx=8, pady=(2, 8))
        self.toplam_lbl: dict[str, tk.Label] = {}
        for anahtar, etiket in (("brut", "Brüt"), ("iskonto", "İskonto"), ("net", "Net"), ("kdv", "KDV"),
                                ("genel", "GENEL TOPLAM"), ("doviz", ""), ("maliyet", "İç Stok Maliyeti")):
            if anahtar == "maliyet" and not self._maliyet_goster:
                continue
            kutu = tk.Frame(alt, bg=SARI if anahtar == "genel" else BEYAZ)
            kutu.pack(side="right", padx=(10, 0))
            tk.Label(kutu, text=etiket, bg=kutu["bg"], fg=IKINCIL if anahtar != "genel" else LACIVERT,
                     font=font(8)).pack(anchor="e", padx=6)
            lbl = tk.Label(kutu, text="0,00", bg=kutu["bg"], fg=LACIVERT,
                           font=font(12 if anahtar == "genel" else 10, "bold"))
            lbl.pack(anchor="e", padx=6)
            self.toplam_lbl[anahtar] = lbl
        self.uyari_lbl = tk.Label(alt, text="", bg=BEYAZ, fg=KIRMIZI, justify="left", wraplength=420,
                                  font=font(9))
        self.uyari_lbl.pack(side="left", fill="x", expand=True)

        govde = tk.Frame(self, bg=ACIK_BG)
        govde.pack(side="top", fill="both", expand=True, padx=8)
        form_dis, form = beyaz_kart(govde, padx=10, pady=6)
        form_dis.pack(fill="x", pady=(2, 4))
        self._form_kur(form)

        satir_dis, satir_ic = beyaz_kart(govde, padx=6, pady=4)
        satir_dis.pack(fill="both", expand=True, pady=(0, 2))
        arac = tk.Frame(satir_ic, bg=BEYAZ)
        arac.pack(side="top", fill="x", pady=(0, 4))
        tk.Label(arac, text="Kod / Barkod:", bg=BEYAZ, fg=LACIVERT, font=font(9, "bold")).pack(side="left")
        self.kod_giris = ttk.Entry(arac, width=22)
        self.kod_giris.pack(side="left", padx=(4, 6))
        self.kod_giris.bind("<Return>", lambda _e: self.urun_ekle())
        for anahtar, metin, komut, rol in (
                ("urun_ekle", "Ürün Ekle (F2)", self.urun_ekle, "vurgu"),
                ("kaynak_alis", "Kaynak Alıştan Seç", self.kaynak_alistan_sec, "kaydet"),
                ("satir_kaynak", "Satır Kaynağı", self.satir_kaynagi_sec, "ikincil"),
                ("kaynak_ac", "Kaynağı Aç", self.kaynagi_ac, "ikincil"),
                ("satir_sil", "Satır Sil", self.satir_sil, "tehlike")):
            b = tk_buton(arac, metin, komut, rol=rol)
            b.pack(side="left", padx=(0, 6))
            self.butonlar[anahtar] = b
        kolonlar = list(self.SATIR_KOLONLARI)
        if self._maliyet_goster:
            kolonlar.append(("maliyet", "İç Maliyet", 90))
        cerceve = tk.Frame(satir_ic, bg=BEYAZ)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(cerceve, columns=[k for k, *_ in kolonlar], show="headings", selectmode="browse",
                                  height=8)
        for k, b, w in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, minwidth=40, stretch=k in ("ad", "kaynak"),
                              anchor="w" if k in ("kod", "barkod", "ad", "birim", "kaynak") else "e")
        ys = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        xs = ttk.Scrollbar(cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.tablo.pack(side="left", fill="both", expand=True)
        self.tablo.tag_configure("eksik", background="#FDECEC")
        self.tablo.tag_configure("kaynaksiz", background="#FFF6DB")
        self.tablo.bind("<Double-1>", lambda _e: self.satir_duzenle())

    def _form_kur(self, f):
        def etiket(metin, r, c):
            tk.Label(f, text=metin, bg=BEYAZ, fg=IKINCIL, font=font(9)).grid(row=r, column=c, sticky="w", padx=(0, 4))

        etiket("İade No", 0, 0)
        self.no_lbl = tk.Label(f, text="(kayıtta verilir)", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold"))
        self.no_lbl.grid(row=0, column=1, sticky="w")
        etiket("Tarih", 0, 2)
        self.tarih = ttk.Entry(f, width=12)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=3, sticky="w", padx=(0, 10))
        etiket("Tedarikçi", 0, 4)
        self.tedarikci = ttk.Combobox(f, values=list(self._ted_map), width=42)
        self.tedarikci.grid(row=0, column=5, columnspan=3, sticky="we", padx=(0, 10))
        self.tedarikci.bind("<KeyRelease>", self._tedarikci_filtre)
        self.tedarikci.bind("<<ComboboxSelected>>", lambda _e: self._tedarikci_degisti())
        self.tedarikci.bind("<FocusOut>", lambda _e: self._tedarikci_degisti())
        etiket("Cari Bakiye", 0, 8)
        self.bakiye_lbl = tk.Label(f, text="—", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold"))
        self.bakiye_lbl.grid(row=0, column=9, sticky="w")

        from database.session_manager import oturum

        etiket("Firma", 1, 0)
        tk.Label(f, text=(getattr(oturum, "firma_unvan", "") or "")[:32], bg=BEYAZ, fg=LACIVERT).grid(
            row=1, column=1, sticky="w")
        etiket("Şube", 1, 2)
        try:
            from sube_ui import sube_secim_hazirla

            self.sube, self._sube_map = sube_secim_hazirla(f, getattr(self.iade, "sube_id", None))
        except Exception:  # noqa: BLE001
            self.sube, self._sube_map = ttk.Combobox(f, values=[], state="readonly", width=20), {}
        self.sube.configure(width=20)
        self.sube.grid(row=1, column=3, sticky="w", padx=(0, 10))
        etiket("Depo", 1, 4)
        from database.stok_service import StokService

        self.depolar = [d.ad for d in StokService.depolar()] or ["ANA DEPO"]
        self.depo = ttk.Combobox(f, values=self.depolar, state="readonly", width=16)
        self.depo.set(self.depolar[0])
        self.depo.grid(row=1, column=5, sticky="w", padx=(0, 10))
        self.depo.bind("<<ComboboxSelected>>", lambda _e: self._depo_degisti())
        etiket("Para Birimi", 1, 6)
        self.para_birimi = ttk.Combobox(f, values=PARA_BIRIMLERI, state="readonly", width=6)
        self.para_birimi.set("TRY")
        self.para_birimi.grid(row=1, column=7, sticky="w", padx=(0, 10))
        self.para_birimi.bind("<<ComboboxSelected>>", lambda _e: self._kur_doldur())
        etiket("Kur", 1, 8)
        self.kur = ttk.Entry(f, width=10)
        self.kur.insert(0, "1")
        self.kur.grid(row=1, column=9, sticky="w")
        self.kur.bind("<KeyRelease>", lambda _e: self._degisti())

        etiket("İade Nedeni", 2, 0)
        self.iade_nedeni = ttk.Combobox(f, values=IADE_NEDENLERI, width=26)
        self.iade_nedeni.grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 10))
        self.iade_nedeni.bind("<KeyRelease>", lambda _e: self._degisti())
        self.iade_nedeni.bind("<<ComboboxSelected>>", lambda _e: self._degisti())
        etiket("Borç Kapatma", 2, 3)
        self.mahsup = ttk.Combobox(f, values=list(MAHSUP_ETIKETLERI.values()), state="readonly", width=36)
        self.mahsup.set(MAHSUP_ETIKETLERI["FIFO"])
        self.mahsup.grid(row=2, column=4, columnspan=2, sticky="w", padx=(0, 10))
        self.mahsup.bind("<<ComboboxSelected>>", lambda _e: self._degisti())
        etiket("Açıklama", 2, 6)
        self.aciklama = ttk.Entry(f, width=40)
        self.aciklama.grid(row=2, column=7, columnspan=3, sticky="we")
        self.aciklama.bind("<KeyRelease>", lambda _e: self._degisti())
        for c in range(10):
            f.grid_columnconfigure(c, weight=1 if c in (5, 7) else 0)

    # ---------------------------------------------------------------- durum
    def _onayli(self) -> bool:
        return self.iade is not None and self.iade.durum in S.ONAYLI_DURUMLAR

    def _iptal(self) -> bool:
        return self.iade is not None and self.iade.durum == S.IPTAL

    def _durum_uygula(self):
        durum = self.iade.durum if self.iade is not None else "TASLAK"
        self.ust["fatura_no"].configure(text=self.iade.iade_no if self.iade is not None else "Yeni (kaydedilmedi)")
        rozet_guncelle(self.ust["rozet"], {"AÇIK": "ONAYLANDI", "KAPALI": "ONAYLANDI"}.get(durum, durum))
        self.ust["musteri"].configure(text=(self.tedarikci.get() or "")[:48])
        self.no_lbl.configure(text=self.iade.iade_no if self.iade is not None else "(kayıtta verilir)")
        kilit = self._onayli() or self._iptal()
        for w in (self.tarih, self.tedarikci, self.kur, self.kod_giris):
            w.configure(state="disabled" if kilit else "normal")
        for w in (self.depo, self.para_birimi, self.mahsup, self.sube):
            w.configure(state="disabled" if kilit else "readonly")
        for w in (self.iade_nedeni, self.aciklama):
            w.configure(state="disabled" if self._iptal() else "normal")
        for k in ("urun_ekle", "kaynak_alis", "satir_kaynak", "satir_sil"):
            self.butonlar[k].configure(state="disabled" if kilit else "normal")
        self.butonlar["onayla"].configure(state="disabled" if kilit else "normal")
        self.butonlar["kaydet"].configure(state="disabled" if self._iptal() else "normal")
        self.butonlar["iptal"].configure(state="normal" if self.iade is not None and not self._iptal() else "disabled")
        self.butonlar["yazdir"].configure(state="normal" if self.iade is not None else "disabled")
        self.butonlar["fis"].configure(state="normal" if self._onayli() or self._iptal() else "disabled")
        if not yetki_var("alis_duzenleme", "yeni_kayit"):
            for k in ("kaydet", "onayla", "urun_ekle", "kaynak_alis", "satir_kaynak", "satir_sil"):
                self.butonlar[k].configure(state="disabled")
        if not yetki_var("alis_duzenleme", "iptal"):
            self.butonlar["iptal"].configure(state="disabled")
        bilgi = {"TASLAK": "Taslak: stok, cari ve muhasebe etkisi yok. Onayla ile kesinleşir.",
                 "İPTAL": "İptal edilmiş belge (salt okunur).", }.get(durum, "Onaylı belge: yalnız açıklama/iade nedeni "
                                                                       "değiştirilebilir; düzeltme için iptal edin.")
        self.durum_yazi.configure(text=bilgi + ("  •  Kaydedilmemiş değişiklik var" if self._kirli else ""))
        self.title(f"{BASLIK} — {self.iade.iade_no}" if self.iade is not None else BASLIK)

    def _degisti(self):
        if self._yukleniyor:
            return
        self._kirli = True
        self._durum_uygula()

    # ---------------------------------------------------------------- tedarikçi / depo
    def _tedarikci_filtre(self, event=None):
        if event is not None and event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        aranan = self.tedarikci.get().strip().casefold()
        self.tedarikci["values"] = [k for k in self._ted_map if aranan in k.casefold()][:200] or list(self._ted_map)

    def _secili_cari(self):
        return self._ted_map.get(self.tedarikci.get())

    def _tedarikci_degisti(self):
        cari = self._secili_cari()
        onceki = getattr(self, "_onceki_cari_id", None)
        yeni_id = int(cari.id) if cari is not None else None
        if yeni_id == onceki:
            return
        self._onceki_cari_id = yeni_id
        self._bakiye_guncelle()
        if self._yukleniyor:
            return
        if self.satirlar and onceki is not None:
            for s in self.satirlar:
                for k in ("kaynak_fatura_satiri_id", "kaynaklar", "kaynak_durumu", "kaynak_gerekce", "kaynak_lot_id"):
                    s.pop(k, None)
                s["kaynak_etiket"] = "SEÇİLMEDİ (tedarikçi değişti)"
            self.uyari_lbl.configure(text="Tedarikçi değişti: satırların kaynak bağlantıları ve tercihleri kaldırıldı; "
                                          "Satır Kaynağı ile yeniden belirleyin.")
        self._satirlari_ciz()
        self._degisti()

    def _depo_degisti(self):
        if self._yukleniyor:
            return
        for s in self.satirlar:
            if s.get("kaynak_durumu") in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI):
                s.pop("kaynak_durumu", None)
                s.pop("kaynak_lot_id", None)
                s["kaynak_etiket"] = "SEÇİLMEDİ (depo değişti)"
        self._satirlari_ciz()
        self._degisti()

    def _bakiye_guncelle(self):
        cari = self._secili_cari()
        if cari is None:
            self.bakiye_lbl.configure(text="—")
            return
        try:
            from database.cari_service import CariService

            ozet = CariService.kart_ozet_metrikleri(int(cari.id)) or {}
            self.bakiye_lbl.configure(text=f"{para(ozet.get('bakiye', 0))} ({ozet.get('bakiye_durumu', '')})")
        except Exception:  # noqa: BLE001
            self.bakiye_lbl.configure(text="—")

    def _kur_doldur(self):
        pb = self.para_birimi.get() or "TRY"
        self.kur.configure(state="normal")
        self.kur.delete(0, "end")
        if pb == "TRY":
            self.kur.insert(0, "1")
        else:
            try:
                from database.doviz_service import DovizService

                self.kur.insert(0, miktar_metni(DovizService.kur_degeri(_tarih_oku(self.tarih.get()), pb)))
            except Exception:  # noqa: BLE001
                self.kur.insert(0, "")
                self.uyari_lbl.configure(text=f"{pb} kuru bulunamadı; kuru elle girin.")
        self._degisti()

    # ---------------------------------------------------------------- satırlar
    def _kart(self, kod: str):
        if kod not in self._kartlar:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from database.database import get_session
            from database.models.stok import StokKarti

            with get_session() as s:
                self._kartlar[kod] = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod)
                                              .options(selectinload(StokKarti.birimler)))
        return self._kartlar[kod]

    def _birimler(self, kod: str) -> list[str]:
        kart = self._kart(kod)
        if kart is None:
            return ["Adet"]
        return [kart.birim or "Adet"] + [b.birim_adi for b in (kart.birimler or []) if b.birim_adi]

    def _temel(self, s: dict) -> Decimal | None:
        from database.stok_service import StokService

        kart = self._kart(s["urun_kodu"])
        if kart is None:
            return None
        try:
            return _d(s["miktar"]) * StokService.birim_carpani_kesin(kart, s.get("birim") or kart.birim)
        except ValueError:
            return None

    def _kaynak_etiketi(self, s: dict) -> str:
        if s.get("kaynak_etiket"):
            return s["kaynak_etiket"]
        if s.get("kaynak_fatura_satiri_id"):
            return "Kaynaklı"
        durum = s.get("kaynak_durumu")
        if durum == DEVIR:
            return "DEVİR katmanı"
        if durum in (KAYNAKSIZ, BASKA_TEDARIKCI):
            return f"{durum}: {s.get('kaynak_gerekce') or ''}"
        return "SEÇİLMEDİ"

    def _satirlari_ciz(self):
        self.tablo.delete(*self.tablo.get_children())
        for sira, s in enumerate(self.satirlar):
            t = S.satir_tutarlari(s)
            temel = self._temel(s)
            kart = self._kart(s["urun_kodu"])
            isk = "+".join(miktar_metni(s.get(a) or 0) for a in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3")
                           if _d(s.get(a)) > 0) or "0"
            degerler = [s["urun_kodu"], s.get("barkod") or "", s.get("urun_adi") or "", miktar_metni(s["miktar"]),
                        s.get("birim") or "", (f"{miktar_metni(temel)} {kart.birim or 'Adet'}" if temel is not None
                                               and kart is not None else "TANIMSIZ BİRİM"),
                        para(s.get("birim_fiyat")), isk, para(t["net_birim"]), miktar_metni(s.get("kdv_orani") or 0),
                        para(t["net"]), self._kaynak_etiketi(s)]
            if self._maliyet_goster:
                degerler.append(para(s["stok_maliyet"]) if s.get("stok_maliyet") is not None else "—")
            etiket = self._kaynak_etiketi(s)
            tag = ("eksik",) if etiket.startswith("SEÇİLMEDİ") or temel is None else (
                ("kaynaksiz",) if s.get("kaynak_durumu") in (KAYNAKSIZ, BASKA_TEDARIKCI, DEVIR) else ())
            self.tablo.insert("", "end", iid=str(sira), values=degerler, tags=tag)
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self):
        t = S.toplam(self.satirlar) if self.satirlar else {k: SIFIR for k in ("ara_toplam", "iskonto", "kdv",
                                                                              "genel_toplam")}
        iade = getattr(self, "iade", None)
        kdv_tl = getattr(iade, "kdv_tl_toplam", None) if iade is not None and (self._onayli() or self._iptal()) \
            else None
        if kdv_tl is not None and self.satirlar:
            t = {**t, "genel_toplam": t["genel_toplam"] - t["kdv"] + _d(kdv_tl), "kdv": _d(kdv_tl)}
        self.toplam_lbl["brut"].configure(text=para(t["ara_toplam"]))
        self.toplam_lbl["iskonto"].configure(text=para(t["iskonto"]))
        self.toplam_lbl["net"].configure(text=para(t["ara_toplam"] - t["iskonto"]))
        self.toplam_lbl["kdv"].configure(text=para(t["kdv"]))
        self.toplam_lbl["genel"].configure(text=para(t["genel_toplam"]) + " ₺")
        pb = self.para_birimi.get() or "TRY"
        doviz = ""
        if pb != "TRY":
            try:
                kur = _d(self.kur.get())
                doviz = f"{para(t['genel_toplam'] / kur)} {pb}" if kur > 0 else ""
            except ValueError:
                doviz = ""
            doviz = f"{doviz} · {self._kdv_kuru_bilgisi(iade)}".strip(" ·")
        self.toplam_lbl["doviz"].configure(text=doviz)
        if "maliyet" in self.toplam_lbl:
            mal = [s.get("stok_maliyet") for s in self.satirlar]
            self.toplam_lbl["maliyet"].configure(
                text=para(sum((m for m in mal if m is not None), SIFIR)) if mal and all(m is not None for m in mal)
                else "onayda hesaplanır")

    def _kdv_kuru_bilgisi(self, iade) -> str:
        """İç bilgi (tedarikçi çıktısına girmez): belgeye yazılan KDV kuru yöntemi."""
        from database.muhasebe_finans_ayarlari import ALIS_IADE_KDV_KURU_SECENEKLERI

        adlar = dict(ALIS_IADE_KDV_KURU_SECENEKLERI)
        yontem = getattr(iade, "kdv_kur_yontemi", None) if iade is not None else None
        if yontem:
            return f"KDV kuru: {adlar.get(yontem, yontem)}"
        if iade is not None and (self._onayli() or self._iptal()):
            return "KDV kuru: yöntem seçilmeden onaylandı (iade kuru)"
        return "KDV kuru: onayda firma ayarından"

    def _secili_index(self) -> int | None:
        secim = self.tablo.selection()
        return int(secim[0]) if secim else None

    def _urun_bul(self, metin: str):
        """Kod / barkod / ad ile stok kartı; (kart, barkod, birim, miktar) döner."""
        from sqlalchemy import or_, select

        from database.database import get_session
        from database.models.stok import StokKarti
        from database.stok_service import StokService

        metin = (metin or "").strip()
        if not metin:
            return None
        bulunan = StokService.barkod_ile_bul(metin)
        if bulunan:
            return self._kart(bulunan["stok_kodu"]), metin, bulunan.get("birim"), _d(bulunan.get("miktar") or 1)
        kart = self._kart(metin)
        if kart is not None:
            return kart, kart.barkod, None, Decimal("1")
        with get_session() as s:
            adaylar = s.scalars(select(StokKarti).where(
                StokKarti.is_deleted.is_(False), or_(StokKarti.stok_kodu.ilike(f"%{metin}%"),
                                                     StokKarti.stok_adi.ilike(f"%{metin}%"))).limit(50)).all()
        if not adaylar:
            return None
        if len(adaylar) > 1:
            secim = _liste_sec(self, "Ürün seç", [f"{k.stok_kodu} — {k.stok_adi}" for k in adaylar])
            if secim is None:
                return False
            adaylar = [adaylar[secim]]
        kart = self._kart(adaylar[0].stok_kodu)
        return kart, kart.barkod, None, Decimal("1")

    def urun_ekle(self, metin: str | None = None):
        if self._onayli() or self._iptal():
            return
        cari = self._secili_cari()
        if cari is None:
            messagebox.showwarning("Tedarikçi", "Önce tedarikçiyi seçin.", parent=self)
            return
        metin = metin if metin is not None else self.kod_giris.get().strip()
        if not metin:
            metin = simpledialog.askstring("Ürün Ekle", "Ürün kodu, barkod veya adı:", parent=self) or ""
        if not metin.strip():
            return
        sonuc = self._urun_bul(metin)
        if sonuc is False:
            return
        if not sonuc:
            messagebox.showwarning("Ürün", f"'{metin}' ile eşleşen stok kartı yok.", parent=self)
            return
        kart, barkod, birim, miktar = sonuc
        self.kod_giris.delete(0, "end")
        temel_satir = {"urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi, "barkod": barkod or None,
                       "miktar": miktar, "birim": birim or kart.birim or "Adet", "birim_fiyat": SIFIR,
                       "iskonto_orani": SIFIR, "iskonto_orani_2": SIFIR, "iskonto_orani_3": SIFIR,
                       "kdv_orani": _d(getattr(kart, "kdv_orani", 20) or 20)}
        yeni = self._kaynak_belirle(temel_satir, cari)
        if not yeni:
            return
        self.satirlar.extend(yeni)
        self._satirlari_ciz()
        self.tablo.selection_set(str(len(self.satirlar) - 1))
        self._degisti()

    def _kaynak_belirle(self, satir: dict, cari, *, mevcut_miktar_temel: Decimal | None = None) -> list[dict] | None:
        """Kaynaklı adaylar varsa seçim; yoksa Kaynak Seç / Gerekçeyle Devam / Vazgeç. Vazgeç → None."""
        durum = S.urun_kaynak_durumu(int(cari.id), satir["urun_kodu"], self.depo.get())
        kart = self._kart(satir["urun_kodu"])
        if durum["adaylar"]:
            d = KaynakSecDialog(self, satir["urun_kodu"], durum["adaylar"], mevcut_miktar_temel,
                                kart.birim if kart is not None else "Adet")
            self.wait_window(d)
            if not d.result:
                return None
            return [self._kaynakli_satir(satir, a, m) for a, m in d.result]
        d = KaynaksizUyariDialog(self, satir["urun_kodu"], satir.get("urun_adi") or "", durum)
        self.wait_window(d)
        if not d.result:
            return None
        yeni = dict(satir)
        for k in ("kaynak_fatura_satiri_id", "kaynaklar", "kaynak_onay_imza"):
            yeni.pop(k, None)
        yeni.update(d.result)
        if yeni.get("kaynak_durumu") == DEVIR:
            lot = next((x for x in durum["devir_lotlari"] if x["lot_id"] == yeni["kaynak_lot_id"]), None)
            if lot and not _d(yeni.get("birim_fiyat")):
                yeni["birim_fiyat"] = lot["birim_maliyet"]
        yeni["kaynak_etiket"] = None
        return [yeni]

    def _kaynakli_satir(self, satir: dict, a: dict, temel_miktar: Decimal) -> dict:
        carpan = _d(a.get("birim_carpani") or 1) or Decimal("1")
        kaynak_birim_miktar = temel_miktar / carpan
        if kaynak_birim_miktar == kaynak_birim_miktar.to_integral_value():
            miktar, birim, fiyat = kaynak_birim_miktar, a.get("birim") or "Adet", a["birim_fiyat"]
        else:
            kart = self._kart(satir["urun_kodu"])
            miktar, birim, fiyat = temel_miktar, (kart.birim if kart is not None else "Adet"), a["birim_fiyat"] / carpan
        yeni = dict(satir)
        yeni.update({"miktar": miktar, "birim": birim, "birim_fiyat": fiyat, "iskonto_orani": a["iskonto_orani"],
                     "iskonto_orani_2": a["iskonto_orani_2"], "iskonto_orani_3": a["iskonto_orani_3"],
                     "kdv_orani": a["kdv_orani"], "kaynak_fatura_satiri_id": a["satir_id"],
                     "kaynak_etiket": f"{a['fatura_no']} · {a['tarih']:%d.%m.%Y}" if a.get("tarih") else a["fatura_no"]})
        if (self.para_birimi.get() or "TRY") != "TRY" and _d(a.get("birim_fiyat_doviz")) > 0:
            yeni["birim_fiyat_doviz"] = a["birim_fiyat_doviz"] / (carpan if birim != a.get("birim") else 1)
        for k in ("kaynak_durumu", "kaynak_gerekce", "kaynak_lot_id", "kaynaklar", "kaynak_onay_imza"):
            yeni.pop(k, None)
        return yeni

    def satir_kaynagi_sec(self):
        i = self._secili_index()
        cari = self._secili_cari()
        if i is None or cari is None or self._onayli():
            return
        s = self.satirlar[i]
        yeni = self._kaynak_belirle(s, cari, mevcut_miktar_temel=self._temel(s))
        if yeni:
            self.satirlar[i:i + 1] = yeni
            self._satirlari_ciz()
            self._degisti()

    def kaynak_alistan_sec(self):
        cari = self._secili_cari()
        if cari is None:
            messagebox.showwarning("Tedarikçi", "Önce tedarikçiyi seçin.", parent=self)
            return
        faturalar = S.tedarikci_alislari(int(cari.id))
        if not faturalar:
            messagebox.showinfo("Kaynak", "Bu tedarikçinin geçerli (iptal olmayan) alış faturası yok.", parent=self)
            return
        secim = _liste_sec(self, "Kaynak alış faturası",
                           [f"{f.fatura_no} · {f.fatura_tarihi:%d.%m.%Y} · {f.depo or ''} · {len(f.satirlar)} satır"
                            for f in faturalar[:500]])
        if secim is None:
            return
        self._kaynak_faturadan(faturalar[secim], ekle=True)
        self._degisti()

    def _kaynak_faturadan(self, fatura, ekle: bool = False):
        if fatura.cari is not None:
            anahtar = f"{fatura.cari.cari_kodu} - {fatura.cari.unvan}"
            self._ted_map.setdefault(anahtar, fatura.cari)
            self.tedarikci.set(anahtar)
            self._onceki_cari_id = int(fatura.cari.id)
            self._bakiye_guncelle()
        if fatura.depo and fatura.depo in self.depolar:
            self.depo.set(fatura.depo)
        adaylar: dict[int, dict] = {}
        eklenen, atlanan = [], []
        for fs in fatura.satirlar:
            for a in S.kaynak_adaylari(int(fatura.cari_id), fs.urun_kodu, self.depo.get()):
                adaylar[a["satir_id"]] = a
            a = adaylar.get(int(fs.id))
            if a is None or a["iade_edilebilir_temel"] <= 0:
                atlanan.append(fs.urun_kodu)
                continue
            taban = {"urun_kodu": fs.urun_kodu, "urun_adi": fs.urun_adi, "barkod": None}
            eklenen.append(self._kaynakli_satir(taban, a, a["iade_edilebilir_temel"]))
        if not ekle:
            self.satirlar = []
        self.satirlar.extend(eklenen)
        self._satirlari_ciz()
        if atlanan:
            self.uyari_lbl.configure(text="İade edilebilir miktarı kalmayan satırlar eklenmedi: "
                                          + ", ".join(sorted(set(atlanan))[:8]))

    def satir_duzenle(self):
        i = self._secili_index()
        if i is None or self._onayli() or self._iptal():
            return
        s = self.satirlar[i]
        d = SatirDuzenleDialog(self, s, self._birimler(s["urun_kodu"]))
        self.wait_window(d)
        if not d.result:
            return
        eski_temel = self._temel(s)
        s.update(d.result)
        yeni_temel = self._temel(s)
        if yeni_temel is None:
            messagebox.showwarning("Birim", f"{s['urun_kodu']} için '{s['birim']}' biriminin çarpanı tanımlı değil; "
                                            "stok kartında birimi tanımlayın.", parent=self)
        if eski_temel != yeni_temel:
            if s.get("kaynaklar"):
                s.pop("kaynaklar", None)
            if s.get("kaynak_durumu") in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI):
                s.pop("kaynak_durumu", None)
                s["kaynak_etiket"] = "SEÇİLMEDİ (miktar değişti; tercih yenilenmeli)"
        self._satirlari_ciz()
        self.tablo.selection_set(str(i))
        self._degisti()

    def satir_sil(self):
        i = self._secili_index()
        if i is None or self._onayli() or self._iptal():
            return
        del self.satirlar[i]
        self._satirlari_ciz()
        self._degisti()

    def kaynagi_ac(self):
        """Seçili satırın kaynak alış faturasını alış faturası penceresinde açar (birden çoksa seçtirir)."""
        i = self._secili_index()
        if i is None:
            messagebox.showinfo("Kaynağı Aç", "Önce bir iade satırı seçin.", parent=self)
            return
        s = self.satirlar[i]
        kaynak_idler = [k.get("kaynak_fatura_satiri_id") for k in s.get("kaynaklar") or []]
        if s.get("kaynak_fatura_satiri_id"):
            kaynak_idler.append(s["kaynak_fatura_satiri_id"])
        faturalar = S.kaynak_faturalari(satir_id=s.get("_id"), kaynak_satir_idler=kaynak_idler)
        if not faturalar:
            durum = s.get("kaynak_durumu")
            neden = {
                DEVIR: "Bu satır devir / açılış stok katmanından iade ediliyor; bağlı bir alış faturası yok.",
                KAYNAKSIZ: "Bu satır gerekçeyle bağlantısız iade edildi; bağlı bir alış faturası yok.",
                BASKA_TEDARIKCI: "Ürün başka tedarikçiden alınmış; bu tedarikçinin alış faturasına bağlı değil.",
            }.get(durum, "Bu satıra henüz kaynak alış faturası seçilmedi ('Kaynak Seç' ile bağlayabilirsiniz).")
            messagebox.showinfo("Kaynağı Aç", f"{neden}\n\n{self._kaynak_bilgisi(s)}", parent=self)
            return
        secilen = faturalar[0] if len(faturalar) == 1 else self._kaynak_fatura_sec(faturalar)
        if secilen:
            self._alis_faturasi_ac(int(secilen["fatura_id"]))

    def _kaynak_fatura_sec(self, faturalar: list[dict]) -> dict | None:
        pencere = tk.Toplevel(self)
        pencere.title("Kaynak alış faturası seç")
        pencere.transient(self)
        tk.Label(pencere, text="Bu satır birden fazla alış faturasından iade ediliyor. Açılacak faturayı seçin:",
                 anchor="w", padx=10, pady=6).pack(fill="x")
        liste = tk.Listbox(pencere, width=70, height=min(10, len(faturalar)))
        liste.pack(fill="both", expand=True, padx=10)
        for f in faturalar:
            ted = f" · tedarikçi no {f['tedarikci_fatura_no']}" if f.get("tedarikci_fatura_no") else ""
            liste.insert("end", f"{f['fatura_no']} · {f['tarih']:%d.%m.%Y}{ted} · {f.get('durum') or ''}")
        liste.selection_set(0)
        sonuc: dict = {}

        def sec(_e=None):
            secim = liste.curselection()
            if secim:
                sonuc["f"] = faturalar[secim[0]]
            pencere.destroy()

        liste.bind("<Double-1>", sec)
        tk_buton(pencere, "Aç", sec, rol="vurgu").pack(side="left", padx=10, pady=8)
        tk_buton(pencere, "Vazgeç", pencere.destroy, rol="ikincil").pack(side="right", padx=10, pady=8)
        pencere.grab_set()
        self.wait_window(pencere)
        return sonuc.get("f")

    def _alis_faturasi_ac(self, fatura_id: int):
        from alis_ui import AlisFaturasiDialog
        from database.alis_faturasi_service import AlisFaturasiService

        fatura = AlisFaturasiService.getir(int(fatura_id))
        if not fatura:
            messagebox.showerror("Kaynağı Aç", "Kaynak alış faturası bulunamadı.", parent=self)
            return None
        pencere = AlisFaturasiDialog(self, fatura=fatura)
        try:
            self.wait_window(pencere)
        finally:
            try:
                if self.winfo_exists():
                    self.grab_set()
            except tk.TclError:
                pass
        return pencere

    def _kaynak_bilgisi(self, s: dict) -> str:
        satir_id = s.get("_id")
        satir_id = s.get("_id")
        if satir_id:
            bag = S.satir_baglantilari(int(satir_id))
        else:
            bag = {"kaynak_durumu": s.get("kaynak_durumu") or (KAYNAKLI if s.get("kaynak_fatura_satiri_id") else None),
                   "gerekce": s.get("kaynak_gerekce"), "kaynaklar": [], "hareketler": [], "devir": None}
        satirlar = [f"Kaynak durumu: {bag.get('kaynak_durumu') or 'SEÇİLMEDİ'}"]
        if bag.get("gerekce"):
            kim = f" — {bag.get('onaylayan') or ''} {bag['tarih']:%d.%m.%Y %H:%M}" if bag.get("tarih") else ""
            satirlar.append(f"Gerekçe: {bag['gerekce']}{kim}")
        for k in bag.get("kaynaklar") or []:
            if k.get("alis_fatura_no"):
                satirlar.append(f"Alış {k['alis_fatura_no']} · lot {k.get('lot_no') or '—'} · "
                                f"{miktar_metni(k['temel_miktar'])} temel")
            elif k.get("lot_no"):
                satirlar.append(f"Katman {k['lot_no']} · {miktar_metni(k['temel_miktar'])} temel")
        if bag.get("devir"):
            satirlar.append(f"Devir katmanı: {bag['devir']['lot_no']}")
        for h in bag.get("hareketler") or []:
            satirlar.append(f"Stok hareketi #{h['id']} {h['tur']} {miktar_metni(h['miktar'])}")
        if not satir_id and s.get("kaynak_fatura_satiri_id"):
            satirlar.append(f"Kaynak alış satırı #{s['kaynak_fatura_satiri_id']} ({s.get('kaynak_etiket') or ''})")
        return "\n".join(satirlar)

    # ---------------------------------------------------------------- doldurma
    def _doldur(self):
        i = self.iade
        anahtar = f"{i.cari.cari_kodu} - {i.cari.unvan}" if i.cari is not None else ""
        self._ted_map.setdefault(anahtar, i.cari)
        self.tedarikci.set(anahtar)
        self._onceki_cari_id = int(i.cari_id)
        self._bakiye_guncelle()
        self.tarih.delete(0, "end")
        self.tarih.insert(0, f"{i.iade_tarihi:%d.%m.%Y}")
        if i.depo:
            if i.depo not in self.depolar:
                self.depolar.append(i.depo)
                self.depo.configure(values=self.depolar)
            self.depo.set(i.depo)
        if getattr(i, "sube_id", None):
            etiket = next((k for k, v in self._sube_map.items() if v == i.sube_id), None)
            if etiket:
                self.sube.set(etiket)
        self.para_birimi.set(i.para_birimi or "TRY")
        self.kur.delete(0, "end")
        self.kur.insert(0, miktar_metni(i.kur or 1))
        self.iade_nedeni.set(i.iade_nedeni or "")
        self.mahsup.set(MAHSUP_ETIKETLERI.get(i.mahsup_modu or "FIFO", MAHSUP_ETIKETLERI["FIFO"]))
        self.aciklama.delete(0, "end")
        self.aciklama.insert(0, i.aciklama or "")
        self.satirlar = []
        for s in i.satirlar:
            planlar = [d for d in s.dagilimlar if d.lot_id is None and d.kaynak_fatura_satiri_id]
            satir = {
                "_id": int(s.id), "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "barkod": s.barkod,
                "miktar": _d(s.miktar), "birim": s.birim, "birim_fiyat": _d(s.birim_fiyat),
                "birim_fiyat_doviz": _d(s.birim_fiyat_doviz), "iskonto_orani": _d(s.iskonto_orani),
                "iskonto_orani_2": _d(s.iskonto_orani_2), "iskonto_orani_3": _d(s.iskonto_orani_3),
                "kdv_orani": _d(s.kdv_orani), "kaynak_fatura_satiri_id": s.kaynak_fatura_satiri_id,
                "kaynak_durumu": s.kaynak_durumu if not s.kaynak_fatura_satiri_id else None,
                "kaynak_gerekce": s.kaynak_gerekce, "kaynak_lot_id": s.kaynak_lot_id,
                "kaynak_onay_imza": s.kaynak_onay_imza, "kaynak_onaylayan": s.kaynak_onaylayan,
                "kaynak_onay_tarihi": s.kaynak_onay_tarihi,
                "stok_maliyet": _d(s.stok_maliyet_toplam) if self._onayli() or self._iptal() else None,
                "kaynak_etiket": (s.onceki_fatura_no if s.kaynak_fatura_satiri_id else None),
            }
            if len(planlar) > 1:
                satir["kaynaklar"] = [{"kaynak_fatura_satiri_id": d.kaynak_fatura_satiri_id, "miktar": _d(d.miktar)}
                                      for d in planlar]
            self.satirlar.append(satir)
        self._satirlari_ciz()

    # ---------------------------------------------------------------- kayıt / onay
    def _veriler(self) -> dict:
        cari = self._secili_cari()
        if cari is None:
            raise ValueError("Tedarikçi seçin.")
        mod = next((k for k, v in MAHSUP_ETIKETLERI.items() if v == self.mahsup.get()), "FIFO")
        pb = self.para_birimi.get() or "TRY"
        v = {"iade_tarihi": _tarih_oku(self.tarih.get()), "cari_id": int(cari.id), "depo": self.depo.get(),
             "sube_id": self._sube_map.get(self.sube.get()), "aciklama": self.aciklama.get().strip() or None,
             "iade_nedeni": self.iade_nedeni.get().strip() or None, "mahsup_modu": mod, "para_birimi": pb,
             "kur": _d(self.kur.get()) if pb != "TRY" else Decimal("1"), "iade_odeme_tutari": SIFIR}
        if self.iade is not None:
            v["row_version"] = self.iade.row_version
            v["iade_odeme_tutari"] = _d(self.iade.iade_odeme_tutari)
            v["iade_odeme_hesabi"] = self.iade.iade_odeme_hesabi
            v["iade_odeme_sekli"] = self.iade.iade_odeme_sekli
            v["kaynak_fatura_id"] = self.iade.kaynak_fatura_id
        if pb != "TRY" and v["kur"] <= 0:
            raise ValueError("Döviz kuru sıfırdan büyük olmalı.")
        return v

    def _satir_verileri(self) -> list[dict]:
        sonuc = []
        for s in self.satirlar:
            v = {k: s.get(k) for k in ("urun_kodu", "urun_adi", "barkod", "miktar", "birim", "birim_fiyat",
                                       "birim_fiyat_doviz", "iskonto_orani", "iskonto_orani_2", "iskonto_orani_3",
                                       "kdv_orani", "kaynak_fatura_satiri_id", "kaynaklar", "kaynak_durumu",
                                       "kaynak_gerekce", "kaynak_lot_id", "kaynak_onay_imza", "kaynak_onaylayan",
                                       "kaynak_onay_tarihi") if s.get(k) not in (None, "")}
            sonuc.append(v)
        return sonuc

    def kaydet(self, *, sessiz: bool = False) -> bool:
        if self._iptal():
            return False
        if not self.satirlar:
            messagebox.showwarning("Kaydet", "En az bir iade satırı ekleyin.", parent=self)
            return False
        try:
            iade = S.kaydet(self._veriler(), self._satir_verileri(), self.iade.id if self.iade is not None else None)
        except IadeDegisti as hata:
            messagebox.showerror("Kaydet", str(hata), parent=self)
            return False
        except (ValueError, AccessError) as hata:
            birim_hatasi_goster(self, hata) or messagebox.showerror("Kaydet", str(hata), parent=self)
            return False
        self.iade = S.getir(iade.id)
        self.result = True
        self._yukleniyor = True
        try:
            self._doldur()
        finally:
            self._yukleniyor = False
        self._kirli = False
        self._durum_uygula()
        if not sessiz:
            self.uyari_lbl.configure(text=f"{self.iade.iade_no} taslak olarak kaydedildi. Stok/cari etkisi yok.")
        return True

    def onayla(self):
        if self._onayli() or self._iptal():
            return
        if (self._kirli or self.iade is None) and not self.kaydet(sessiz=True):
            return
        for _deneme in range(3):
            try:
                self.iade = S.onayla(self.iade.id, beklenen_versiyon=self.iade.row_version)
                break
            except KaynakTercihiGerekli as hata:
                if not self._tercihleri_sor(hata.satirlar):
                    messagebox.showinfo("Onay", "Onay yapılmadı; stoktan çıkış oluşmadı.", parent=self)
                    return
                if not self.kaydet(sessiz=True):
                    return
            except (ValueError, AccessError) as hata:
                messagebox.showerror("Onay", str(hata), parent=self)
                self.iade = S.getir(self.iade.id)
                self._durum_uygula()
                return
        else:
            return
        self.iade = S.getir(self.iade.id)
        self.result = True
        self._yukleniyor = True
        try:
            self._doldur()
        finally:
            self._yukleniyor = False
        self._kirli = False
        self._durum_uygula()
        self.uyari_lbl.configure(text=f"{self.iade.iade_no} onaylandı: stok çıkışı, tedarikçi alacağı ve "
                                      "muhasebe kaydı oluşturuldu.")

    def _tercihleri_sor(self, satir_idler: list[int]) -> bool:
        cari = self._secili_cari()
        for sid in satir_idler:
            i = next((n for n, s in enumerate(self.satirlar) if s.get("_id") == sid), None)
            if i is None:
                continue
            s = self.satirlar[i]
            yeni = self._kaynak_belirle(s, cari, mevcut_miktar_temel=self._temel(s))
            if not yeni:
                return False
            self.satirlar[i:i + 1] = yeni
        self._satirlari_ciz()
        self._kirli = True
        return True

    def iptal(self):
        if self.iade is None or self._iptal():
            return
        try:
            on = S.iptal_on_kontrol(self.iade.id)
        except ValueError as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return
        ek = ""
        if on.get("tahsilatlar"):
            ek += "\nBağlı tahsilatlar da geri alınacak: " + ", ".join(n for n, _t in on["tahsilatlar"])
        if on.get("kapatmalar"):
            ek += "\nKapatılan borçlar yeniden açılacak: " + ", ".join(sorted({n for n, _t in on["kapatmalar"]}))
        if on.get("kapali_donem"):
            messagebox.showerror("İptal", "İade tarihi kapalı döneme düşüyor; iptal edilemez.", parent=self)
            return
        neden = simpledialog.askstring(
            "İade İptali", f"{self.iade.iade_no} iptal edilecek. Onaylıysa stok çıkışı, tedarikçi alacağı ve "
                           f"muhasebe kaydı ters çevrilir.{ek}\n\nİptal nedeni:", parent=self)
        if neden is None:
            return
        try:
            S.iptal_et(self.iade.id, neden)
        except (ValueError, AccessError) as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return
        self.iade = S.getir(self.iade.id)
        self.result = True
        self._yukleniyor = True
        try:
            self._doldur()
        finally:
            self._yukleniyor = False
        self._kirli = False
        self._durum_uygula()

    def yazdir(self, tur: str | None = None, *, ac: bool = True):
        if self.iade is None:
            return None
        if self._kirli and not self._iptal() and not self.kaydet(sessiz=True):
            return None
        if tur is None:
            secim = messagebox.askyesnocancel("Yazdır", "PDF olarak mı oluşturulsun?\n\nEvet: PDF   Hayır: Word (.docx)",
                                              parent=self)
            if secim is None:
                return None
            tur = "pdf" if secim else "docx"
        try:
            from invoice_print.alis_iade_cikti import cikti_uret

            yol = cikti_uret(self.iade.id, tur)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Yazdır", f"Çıktı oluşturulamadı:\n{hata}", parent=self)
            return None
        if ac:
            try:
                os.startfile(str(yol))  # type: ignore[attr-defined]
            except OSError:
                messagebox.showinfo("Yazdır", f"Çıktı: {yol}", parent=self)
        return yol

    def muhasebe_fisi(self):
        if self.iade is None:
            return
        from muhasebe_durum_ui import fisi_ac

        fisi_ac(self, "alis_iade", int(self.iade.id))

    def liste(self):
        AlisIadeListesiPenceresi(self.master)

    def yeni(self):
        AlisIadeFaturasiPenceresi(self.master)

    def kapat(self):
        if self._kirli:
            cevap = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklik", "Belgede kaydedilmemiş değişiklik var. Kaydedilsin mi?", parent=self)
            if cevap is None:
                return
            if cevap and not self.kaydet(sessiz=True):
                return
        self.destroy()


def _liste_sec(parent, baslik: str, etiketler: list[str]) -> int | None:
    pencere = tk.Toplevel(parent)
    pencere.title(baslik)
    pencere.transient(parent)
    _ekrana_sigdir(pencere, 620, 380, 420, 260)
    sonuc: dict[str, int | None] = {"i": None}
    arama = ttk.Entry(pencere)
    arama.pack(fill="x", padx=10, pady=(10, 4))
    liste = tk.Listbox(pencere, exportselection=False)
    liste.pack(fill="both", expand=True, padx=10)
    gorunen: list[int] = []

    def doldur(_e=None):
        aranan = arama.get().strip().casefold()
        liste.delete(0, "end")
        gorunen.clear()
        for n, e in enumerate(etiketler):
            if aranan in e.casefold():
                gorunen.append(n)
                liste.insert("end", e)
        if gorunen:
            liste.selection_set(0)

    def sec(_e=None):
        s = liste.curselection()
        if s:
            sonuc["i"] = gorunen[s[0]]
            pencere.destroy()

    arama.bind("<KeyRelease>", doldur)
    liste.bind("<Double-1>", sec)
    pencere.bind("<Return>", sec)
    pencere.bind("<Escape>", lambda _e: pencere.destroy())
    ttk.Button(pencere, text="Seç", command=sec).pack(pady=8)
    doldur()
    arama.focus_set()
    parent.wait_window(pencere)
    return sonuc["i"]


# ====================================================================== liste
class AlisIadeListesiCerceve(tk.Frame):
    """Alış iade faturaları listesi (ana içerikte veya ayrı pencerede)."""

    KOLONLAR = (("tarih", "Tarih", 84), ("no", "İade No", 100), ("tedarikci", "Tedarikçi", 220),
                ("depo", "Depo / Şube", 130), ("net", "Net", 96), ("kdv", "KDV", 84), ("genel", "Genel", 100),
                ("pb", "PB", 44), ("kaynak", "Kaynak", 120), ("durum", "Durum", 76), ("muhasebe", "Muhasebe", 120))
    SAYFA = 200

    def __init__(self, parent, *, pencere_ac=None):
        super().__init__(parent, bg=ACIK_BG)
        self._pencere_ac = pencere_ac
        self._limit = self.SAYFA
        self._cari_map = {f"{c.cari_kodu} - {c.unvan}": int(c.id) for c in S.aktif_tedarikcileri()}
        filtre = tk.Frame(self, bg=ACIK_BG)
        filtre.pack(fill="x", pady=(0, 6))
        self.f: dict[str, tk.Widget] = {}

        def alan(metin, w, r, c):
            tk.Label(filtre, text=metin, bg=ACIK_BG, fg=IKINCIL).grid(row=r, column=c, sticky="w", padx=(0, 3))
            w.grid(row=r, column=c + 1, sticky="w", padx=(0, 8), pady=2)
            return w

        self.f["tarih_bas"] = alan("Başlangıç", ttk.Entry(filtre, width=11), 0, 0)
        self.f["tarih_bit"] = alan("Bitiş", ttk.Entry(filtre, width=11), 0, 2)
        self.f["cari"] = alan("Tedarikçi", ttk.Combobox(filtre, values=[""] + list(self._cari_map), width=30), 0, 4)
        self.f["urun"] = alan("Ürün", ttk.Entry(filtre, width=14), 0, 6)
        self.f["arama"] = alan("No / Açıklama", ttk.Entry(filtre, width=16), 0, 8)
        from database.stok_service import StokService

        self.f["depo"] = alan("Depo", ttk.Combobox(filtre, values=[""] + [d.ad for d in StokService.depolar()],
                                                   state="readonly", width=14), 1, 0)
        try:
            from sube_ui import sube_secim_hazirla

            combo, self._sube_map = sube_secim_hazirla(filtre)
            combo.configure(values=[""] + list(self._sube_map))
            combo.set("")
        except Exception:  # noqa: BLE001
            combo, self._sube_map = ttk.Combobox(filtre, values=[""], state="readonly"), {}
        combo.configure(width=18)
        self.f["sube"] = alan("Şube", combo, 1, 2)
        self.f["durum"] = alan("Durum", ttk.Combobox(filtre, values=("", "TASLAK", "ONAYLI", "AÇIK", "KAPALI", "İPTAL"),
                                                     state="readonly", width=10), 1, 4)
        self.f["muhasebe"] = alan("Muhasebe", ttk.Combobox(filtre, values=(
            "", "Muhasebeleştirildi", "Bekliyor", "Hatalı", "İnceleme gerekiyor", "İptal edildi", "Kayıt yok"),
            state="readonly", width=16), 1, 6)
        self.f["kaynak_durumu"] = alan("Kaynak", ttk.Combobox(filtre, values=(
            "", KAYNAKLI, DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI, "BELİRSİZ"), state="readonly", width=16), 1, 8)
        tk_buton(filtre, "Listele", self.yenile, rol="kaydet").grid(row=0, column=10, rowspan=2, padx=6)
        for w in (self.f["arama"], self.f["urun"], self.f["tarih_bas"], self.f["tarih_bit"]):
            w.bind("<Return>", lambda _e: self.yenile())

        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(side="bottom", fill="x", pady=(6, 0))
        for metin, komut, rol in (("Yeni İade", self.yeni, "vurgu"), ("Aç", self.ac, "kaydet"),
                                  ("İptal Et", self.iptal, "tehlike"), ("Muhasebe Fişi", self.fis, "ikincil"),
                                  ("Yazdır (PDF)", lambda: self.yazdir("pdf"), "yazdir"),
                                  ("Daha Fazla", self.daha_fazla, "ikincil")):
            tk_buton(alt, metin, komut, rol=rol).pack(side="left", padx=(0, 6))
        self.toplam_lbl = tk.Label(alt, text="", bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold"))
        self.toplam_lbl.pack(side="right")

        cerceve = tk.Frame(self, bg=ACIK_BG)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(cerceve, columns=[k for k, *_ in self.KOLONLAR], show="headings", selectmode="browse")
        for k, b, w in self.KOLONLAR:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="e" if k in ("net", "kdv", "genel") else "w",
                              stretch=k == "tedarikci")
        ys = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.tablo.pack(side="left", fill="both", expand=True)
        self.tablo.tag_configure("iptal", foreground=KIRMIZI)
        self.tablo.tag_configure("taslak", foreground=IKINCIL)
        self.tablo.bind("<Double-1>", lambda _e: self.ac())
        self.yenile()

    def filtre(self) -> dict:
        f = {}
        for k in ("tarih_bas", "tarih_bit"):
            metin = self.f[k].get().strip()
            if metin:
                f[k] = _tarih_oku(metin)
        cari = self.f["cari"].get().strip()
        if cari:
            f["cari_id"] = self._cari_map.get(cari)
            if f["cari_id"] is None:
                f["cari_id"] = -1
        for k in ("urun", "arama", "depo", "durum", "muhasebe", "kaynak_durumu"):
            v = self.f[k].get().strip()
            if v:
                f[k] = v
        sube = self.f["sube"].get().strip()
        if sube and sube in self._sube_map:
            f["sube_id"] = self._sube_map[sube]
        return f

    def yenile(self):
        try:
            f = self.filtre()
        except ValueError as hata:
            messagebox.showerror("Filtre", str(hata), parent=self)
            return
        kayitlar = S.listele(f, limit=self._limit)
        from muhasebe_durum_ui import toplu_durum

        muhasebe = toplu_durum("alis_iade", [k["iade"].id for k in kayitlar])
        self.tablo.delete(*self.tablo.get_children())
        for k in kayitlar:
            i = k["iade"]
            tag = ("iptal",) if i.durum == "İPTAL" else (("taslak",) if i.durum == "TASLAK" else ())
            self.tablo.insert("", "end", iid=str(i.id), tags=tag, values=(
                f"{i.iade_tarihi:%d.%m.%Y}", i.iade_no, i.cari.unvan if i.cari else "",
                i.depo or "", para(k["net"]), para(k["kdv"]), para(k["genel_toplam"]), i.para_birimi or "TRY",
                k.get("kaynak_ozet", ""), "İPTAL" if i.durum == "İPTAL" else ("TASLAK" if i.durum == "TASLAK"
                                                                              else f"ONAYLI ({i.durum})"),
                muhasebe.get(i.id, "")))
        t = S.liste_toplamlari(kayitlar)
        self.toplam_lbl.configure(text=f"{t['adet']} belge (iptal hariç) · Net {para(t['net'])} · KDV {para(t['kdv'])}"
                                       f" · Genel {para(t['genel_toplam'])} ₺"
                                       + (f"  (ilk {self._limit} kayıt)" if len(kayitlar) >= self._limit else ""))
        self.kayitlar = kayitlar

    def daha_fazla(self):
        self._limit += self.SAYFA
        self.yenile()

    def _secili(self) -> int | None:
        s = self.tablo.selection()
        return int(s[0]) if s else None

    def _ac(self, iade_id=None):
        p = AlisIadeFaturasiPenceresi(self.winfo_toplevel(), iade_id=iade_id)
        p.bind("<Destroy>", lambda e: self.yenile() if e.widget is p and self.winfo_exists() else None, add="+")
        return p

    def yeni(self):
        return self._ac()

    def ac(self):
        iid = self._secili()
        if iid:
            return self._ac(iid)
        return None

    def iptal(self):
        iid = self._secili()
        if not iid:
            return
        neden = simpledialog.askstring("İptal", "İade iptal edilsin mi? İptal nedeni:", parent=self)
        if neden is None:
            return
        try:
            S.iptal_et(iid, neden)
        except (ValueError, AccessError) as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
        self.yenile()

    def fis(self):
        iid = self._secili()
        if iid:
            from muhasebe_durum_ui import fisi_ac

            fisi_ac(self, "alis_iade", iid)

    def yazdir(self, tur: str):
        iid = self._secili()
        if not iid:
            return
        try:
            from invoice_print.alis_iade_cikti import cikti_uret

            os.startfile(str(cikti_uret(iid, tur)))  # type: ignore[attr-defined]
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Yazdır", str(hata), parent=self)


class AlisIadeListesiPenceresi(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        stil_uygula(root=self)
        self.title("ALIŞ İADE FATURALARI LİSTESİ")
        self.configure(bg=ACIK_BG)
        _ekrana_sigdir(self, 1300, 720)
        tk.Label(self, text="ALIŞ İADE FATURALARI LİSTESİ", bg=LACIVERT, fg=BEYAZ, font=font(13, "bold"),
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        self.liste = AlisIadeListesiCerceve(self)
        self.liste.pack(fill="both", expand=True, padx=10, pady=8)


class BagliIadelerDialog(tk.Toplevel):
    """Alış faturasına bağlı iadeler ve satır bazında kalan iade hakkı; seçili iade tek tıkla açılır."""

    def __init__(self, parent, alis_fatura_id: int, *, fatura_no: str = ""):
        super().__init__(parent)
        stil_uygula(root=self)
        self.alis_fatura_id = int(alis_fatura_id)
        self.title(f"Bağlı İadeler — {fatura_no}".rstrip(" —"))
        self.configure(bg=ACIK_BG)
        self.transient(parent)
        _ekrana_sigdir(self, 900, 520)
        tk.Label(self, text=f"BAĞLI İADELER  {fatura_no}", bg=LACIVERT, fg=BEYAZ, font=font(12, "bold"),
                 anchor="w", padx=12, pady=6).pack(fill="x")
        self.iadeler = S.kaynaktan_iadeler(self.alis_fatura_id)
        self.ozet = S.kaynak_iade_ozeti(self.alis_fatura_id)
        ust = ttk.Frame(self, padding=(10, 8, 10, 0))
        ust.pack(fill="both", expand=True)
        ttk.Label(ust, text="İadeler", font=font(10, "bold")).pack(anchor="w")
        self.tablo = ttk.Treeview(ust, columns=("no", "tarih", "durum", "tutar"), show="headings", height=6)
        for k, b, g in (("no", "İade No", 140), ("tarih", "Tarih", 100), ("durum", "Durum", 100),
                        ("tutar", "Genel Toplam", 130)):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=g, anchor="e" if k == "tutar" else "w")
        for r in self.iadeler:
            self.tablo.insert("", "end", iid=str(r["id"]), values=(
                r["no"], f"{r['tarih']:%d.%m.%Y}" if r.get("tarih") else "", r["durum"], f"{r['genel']:,.2f}"))
        self.tablo.pack(fill="both", expand=True)
        self.tablo.bind("<Double-1>", lambda _e: self.iadeyi_ac())
        ttk.Label(ust, text="Kalan iade hakkı (temel birim; yalnız onaylı iadeler düşer)",
                  font=font(10, "bold")).pack(anchor="w", pady=(8, 0))
        self.hak = ttk.Treeview(ust, columns=("urun", "alinan", "iade", "kalan"), show="headings", height=6)
        for k, b, g in (("urun", "Ürün", 330), ("alinan", "Alınan", 110), ("iade", "İade edilen", 110),
                        ("kalan", "Kalan hak", 110)):
            self.hak.heading(k, text=b)
            self.hak.column(k, width=g, anchor="w" if k == "urun" else "e")
        for o in self.ozet:
            birim = o.get("birim") or ""
            self.hak.insert("", "end", values=(
                f"{o['urun_kodu']} — {o['urun_adi']}" + (" (birim çarpanı eksik)" if o["carpan_eksik"] else ""),
                f"{miktar_metni(o['alinan_temel'])} {birim}", f"{miktar_metni(o['iade_temel'])} {birim}",
                f"{miktar_metni(o['kalan_temel'])} {birim}"))
        self.hak.pack(fill="both", expand=True)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "İadeyi Aç", self.iadeyi_ac, rol="vurgu").pack(side="left")
        tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        if not self.iadeler:
            tk.Label(alt, text="Bu alış faturasına bağlı iade yok.", bg=ACIK_BG).pack(side="left", padx=12)

    def iadeyi_ac(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Bağlı İadeler", "Açılacak iadeyi seçin.", parent=self)
            return None
        pencere = AlisIadeFaturasiPenceresi(self, iade_id=int(secim[0]))
        try:
            self.wait_window(pencere)
        finally:
            try:
                if self.winfo_exists():
                    self.grab_set()
            except tk.TclError:
                pass
        return pencere


# Geriye uyumluluk: eski çağıranlar (cari kart, belge önizleme, alış faturası) aynı imzayı kullanır
AlisIadeFaturasiDialog = AlisIadeFaturasiPenceresi
