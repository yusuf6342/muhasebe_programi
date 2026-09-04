import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from database.cari_service import CariService
from database.firma_service import FirmaService
from database.satis_siparisi_service import (
    MALIYET_YONTEMLERI,
    ODEME_SEKILLERI,
    SIPARIS_DURUMLARI,
    SatisSiparisiService,
    decimal,
)
from product_provider import search_products


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


class FirmaDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, firma=None):
        super().__init__(parent)
        self.firma = firma
        self.result = None
        self.title("Firma Düzenle" if firma else "Yeni Firma")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.degerler = {}
        alanlar = (
            ("Firma Kodu", "firma_kodu"),
            ("Ünvan", "unvan"),
            ("Vergi No", "vergi_no"),
            ("Vergi Dairesi", "vergi_dairesi"),
            ("Telefon", "telefon"),
            ("E-posta", "email"),
            ("Adres", "adres"),
        )
        for satir, (etiket, alan) in enumerate(alanlar):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            if alan == "adres":
                widget = tk.Text(self, width=36, height=3)
                widget.grid(row=satir, column=1, padx=12, pady=6)
            else:
                widget = ttk.Entry(self, width=38)
                widget.grid(row=satir, column=1, padx=12, pady=6)
            self.degerler[alan] = widget

        if firma:
            for alan, widget in self.degerler.items():
                deger = getattr(firma, alan) or ""
                if alan == "adres":
                    widget.insert("1.0", deger)
                else:
                    widget.insert(0, deger)

        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(alanlar), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.degerler["firma_kodu"].focus_set()

    def kaydet(self):
        veriler = {}
        for alan, widget in self.degerler.items():
            if alan == "adres":
                deger = widget.get("1.0", "end").strip()
            else:
                deger = widget.get().strip()
            veriler[alan] = deger or None

        if not veriler["firma_kodu"] or not veriler["unvan"]:
            messagebox.showwarning("Eksik bilgi", "Firma kodu ve ünvan zorunludur.", parent=self)
            return
        veriler["aktif"] = self.firma.aktif if self.firma else True
        try:
            if self.firma:
                self.result = FirmaService.guncelle(self.firma.id, veriler)
            else:
                self.result = FirmaService.ekle(veriler)
        except ValueError as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return
        self.destroy()


class CariDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, cari=None):
        super().__init__(parent)
        self.cari = cari
        self.result = None
        self.title("Müşteri Kartı" if cari else "Yeni Müşteri")
        self.geometry("820x560")
        self.minsize(720, 480)
        self.transient(parent)
        self.grab_set()
        self.degerler = {}
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        genel = ttk.Frame(notebook, padding=12)
        hareketler = ttk.Frame(notebook, padding=12)
        notebook.add(genel, text="GENEL BİLGİLER")
        notebook.add(hareketler, text="CARİ HAREKETLER")

        alanlar = (
            ("Müşteri Kodu", "cari_kodu"),
            ("Müşteri Adı / Ünvanı", "unvan"),
            ("Vergi Dairesi", "vergi_dairesi"),
            ("Vergi Numarası", "vergi_numarasi"),
            ("Telefon", "telefon"),
            ("E-posta", "email"),
            ("Müşteri Grubu", "musteri_grubu"),
            ("Adres", "adres"),
            ("İstihbarat / Özel Notlar", "ozel_notlar"),
        )
        for satir, (etiket, alan) in enumerate(alanlar):
            ttk.Label(genel, text=etiket).grid(row=satir, column=0, padx=8, pady=5, sticky="nw")
            if alan == "musteri_grubu":
                widget = ttk.Combobox(genel, state="readonly", width=47)
                widget.grid(row=satir, column=1, padx=8, pady=5, sticky="ew")
                ttk.Button(genel, text="Yeni Grup Ekle", command=self.yeni_grup_ekle).grid(row=satir, column=2, padx=(0, 8), pady=5)
            else:
                widget = tk.Text(genel, width=48, height=3) if alan in ("adres", "ozel_notlar") else ttk.Entry(genel, width=50)
                widget.grid(row=satir, column=1, padx=8, pady=5, sticky="ew")
            self.degerler[alan] = widget
        genel.columnconfigure(1, weight=1)
        self.musteri_grubu_secimini_hazirla()
        durum = tk.BooleanVar(value=cari.aktif if cari else True)
        self.degerler["aktif"] = durum
        ttk.Checkbutton(genel, text="Aktif", variable=durum).grid(row=len(alanlar), column=1, padx=8, pady=6, sticky="w")
        if cari:
            for alan, widget in self.degerler.items():
                if alan == "aktif":
                    continue
                deger = getattr(cari, alan) or ""
                if isinstance(widget, tk.Text):
                    widget.insert("1.0", deger)
                elif alan == "musteri_grubu":
                    widget.set(deger)
                else:
                    widget.insert(0, deger)
        self._hareket_tablosunu_olustur(hareketler)

        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right", padx=(0, 8))
        self.degerler["cari_kodu"].focus_set()

    def musteri_grubu_secimini_hazirla(self):
        gruplar = CariService.gruplari_listele()
        mevcut_grup = getattr(self.cari, "musteri_grubu", None) if self.cari else None
        if mevcut_grup and mevcut_grup not in gruplar:
            gruplar.append(mevcut_grup)
        self.degerler["musteri_grubu"]["values"] = gruplar
        if mevcut_grup:
            self.degerler["musteri_grubu"].set(mevcut_grup)
        elif gruplar:
            self.degerler["musteri_grubu"].set(gruplar[0])

    def yeni_grup_ekle(self):
        grup_adi = simpledialog.askstring("Yeni Grup Ekle", "Müşteri grup adı:", parent=self)
        if grup_adi is None:
            return
        try:
            eklenen_grup = CariService.grup_ekle(grup_adi)
        except ValueError as hata:
            messagebox.showwarning("Grup eklenemedi", str(hata), parent=self)
            return
        self.musteri_grubu_secimini_hazirla()
        self.degerler["musteri_grubu"].set(eklenen_grup)

    def _hareket_tablosunu_olustur(self, parent):
        bilgi = ttk.Frame(parent)
        bilgi.pack(fill="x", pady=(0, 12))
        bakiye = "0,00 TL"
        agirlikli_ortalama = "0,0"
        if self.cari:
            ozetler = CariService.listele()
            ozet = next((kayit for kayit in ozetler if kayit["cari"].id == self.cari.id), None)
            if ozet:
                bakiye = para_goster(ozet["bakiye"])
                agirlikli_ortalama = f"{ozet['agirlikli_ortalama_gun']:.1f} gün"
        ttk.Label(bilgi, text="Güncel Toplam Bakiye", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(bilgi, text=bakiye, font=("Segoe UI", 10, "bold"), foreground="#1f6aa5").pack(side="left", padx=(8, 28))
        ttk.Label(bilgi, text="Ağırlıklı Ortalama Geçen Gün", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(bilgi, text=agirlikli_ortalama, font=("Segoe UI", 10, "bold"), foreground="#1f6aa5").pack(side="left", padx=8)

        kolonlar = ("tarih", "tur", "belge", "aciklama", "borc", "alacak", "bakiye", "gun")
        tablo_cercevesi = ttk.Frame(parent)
        tablo_cercevesi.pack(fill="both", expand=True)
        tablo = ttk.Treeview(tablo_cercevesi, columns=kolonlar, show="headings")
        basliklar = {"tarih": "Tarih", "tur": "Belge Türü", "belge": "Belge Numarası", "aciklama": "Açıklama", "borc": "Borç", "alacak": "Alacak", "bakiye": "Kalan Bakiye", "gun": "Geçen Gün"}
        genislikler = {"tarih": 95, "tur": 110, "belge": 145, "aciklama": 160, "borc": 115, "alacak": 115, "bakiye": 135, "gun": 115}
        for kolon in kolonlar:
            tablo.heading(kolon, text=basliklar[kolon])
            tablo.column(kolon, width=genislikler[kolon], anchor="w")
        dikey_kaydirma = ttk.Scrollbar(tablo_cercevesi, orient="vertical", command=tablo.yview)
        yatay_kaydirma = ttk.Scrollbar(tablo_cercevesi, orient="horizontal", command=tablo.xview)
        tablo.configure(yscrollcommand=dikey_kaydirma.set, xscrollcommand=yatay_kaydirma.set)
        tablo.grid(row=0, column=0, sticky="nsew")
        dikey_kaydirma.grid(row=0, column=1, sticky="ns")
        yatay_kaydirma.grid(row=1, column=0, sticky="ew")
        tablo_cercevesi.rowconfigure(0, weight=1)
        tablo_cercevesi.columnconfigure(0, weight=1)
        if not self.cari:
            return
        detay = CariService.detay(self.cari.id)
        for hareket in detay["hareketler"] if detay else []:
            gun = (date.today() - hareket.satis_tarihi).days
            tablo.insert("", "end", values=(tarih_goster(hareket.satis_tarihi), "Satış", hareket.belge_no, "", para_goster(hareket.satis_tutari), para_goster(0), para_goster(hareket.kalan_acik_tutar), gun))

    def kaydet(self):
        veriler = {}
        for alan, widget in self.degerler.items():
            if alan == "aktif":
                continue
            deger = widget.get("1.0", "end").strip() if isinstance(widget, tk.Text) else widget.get().strip()
            veriler[alan] = deger or None
        if not veriler["cari_kodu"] or not veriler["unvan"]:
            messagebox.showwarning("Eksik bilgi", "Müşteri kodu ve adı/ünvanı zorunludur.", parent=self)
            return
        veriler["cari_turu"] = self.cari.cari_turu if self.cari else "Müşteri"
        veriler["aktif"] = self.degerler["aktif"].get()
        try:
            self.result = CariService.guncelle(self.cari.id, veriler) if self.cari else CariService.ekle(veriler)
        except ValueError as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return
        self.destroy()


class ProductSelectionDialog(tk.Toplevel):
    def __init__(self, parent, query, on_select):
        super().__init__(parent)
        self.title("Ürün Seçimi")
        self.geometry("780x360")
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text=f"Ürün arama: {query}").pack(anchor="w", padx=12, pady=(12, 6))
        kolonlar = ("kod", "ad", "birim", "stok", "fiyat", "kaynak")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (("kod", "Ürün Kodu", 120), ("ad", "Ürün Adı", 220), ("birim", "Birim", 80), ("stok", "Mevcut Stok", 110), ("fiyat", "Varsayılan Satış Fiyatı", 150), ("kaynak", "Veri Kaynağı", 110)):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik)
        self.tablo.pack(fill="both", expand=True, padx=12, pady=6)
        urunler = search_products(query)
        for sira, urun in enumerate(urunler):
            self.tablo.insert("", "end", iid=str(sira), values=(urun.code, urun.name, urun.unit, urun.stock, urun.default_price, urun.source))
        if not urunler:
            ttk.Label(self, text="Ürün bulunamadı. Ürün verisi sağlayıcısı henüz boş.").pack(anchor="w", padx=12, pady=4)
        self.tablo.bind("<Double-1>", lambda _event: self.sec())
        ttk.Button(self, text="Seç", command=self.sec).pack(anchor="e", padx=12, pady=8)
        self.on_select = on_select

    def sec(self):
        secim = self.tablo.selection()
        if not secim:
            return
        self.on_select(self.tablo.item(secim[0], "values"))
        self.destroy()


class PriceSelectionDialog(tk.Toplevel):
    def __init__(self, parent, product_code):
        super().__init__(parent)
        self.title("Fiyat Seçimi")
        self.geometry("620x300")
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text=f"Ürün: {product_code}").pack(anchor="w", padx=12, pady=(12, 6))
        kolonlar = ("ad", "fiyat", "para", "tarih")
        tablo = ttk.Treeview(self, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (("ad", "Fiyat Adı", 180), ("fiyat", "Fiyat", 120), ("para", "Para Birimi", 120), ("tarih", "Geçerlilik Tarihi", 150)):
            tablo.heading(kolon, text=baslik)
            tablo.column(kolon, width=genislik)
        tablo.pack(fill="both", expand=True, padx=12, pady=6)
        ttk.Label(self, text="Bu ürüne ait tanımlı fiyat bulunamadı").pack(anchor="w", padx=12, pady=4)
        ttk.Button(self, text="Kapat", command=self.destroy).pack(anchor="e", padx=12, pady=8)


class SiparisSatiriDialog(tk.Toplevel):
    alanlar = (
        ("Ürün Kodu", "urun_kodu"), ("Ürün Adı", "urun_adi"), ("Açıklama", "aciklama"),
        ("Miktar", "miktar"), ("Birim", "birim"), ("Birim Fiyat", "birim_satis_fiyati"),
        ("İskonto", "iskonto_orani"), ("KDV", "kdv_orani"), ("FIFO Birim Maliyeti", "fifo_birim_maliyeti"),
        ("Son Alış Birim Maliyeti", "son_alis_birim_maliyeti"), ("Ortalama Birim Maliyeti", "ortalama_birim_maliyeti"),
        ("Ağırlıklı Ortalama Birim Maliyeti", "agirlikli_ortalama_birim_maliyeti"),
    )

    def __init__(self, parent, veri=None):
        super().__init__(parent)
        self.result = None
        self.title("Sipariş Satırı")
        self.transient(parent)
        self.grab_set()
        self.girdiler = {}
        self._son_urun_arama = ""
        for satir, (baslik, alan) in enumerate(self.alanlar):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=8, pady=3, sticky="w")
            widget = ttk.Entry(self, width=34)
            widget.grid(row=satir, column=1, padx=8, pady=3)
            self.girdiler[alan] = widget
            if alan in ("urun_kodu", "urun_adi"):
                widget.bind("<KeyRelease>", self.urun_arama_ac)
            if alan == "birim_satis_fiyati":
                widget.bind("<F10>", self.fiyat_secimi_ac)
            if veri:
                widget.insert(0, veri.get(alan, ""))
        if not veri:
            self.girdiler["birim"].insert(0, "Adet")
            self.girdiler["kdv_orani"].insert(0, "20")
        self._tutar_etiketi = ttk.Label(self, text="Tutar: 0,00 TL", font=("Segoe UI", 10, "bold"))
        self._tutar_etiketi.grid(row=len(self.alanlar), column=0, columnspan=2, padx=8, pady=(4, 0), sticky="w")
        for alan in ("miktar", "birim_satis_fiyati", "iskonto_orani"):
            self.girdiler[alan].bind("<KeyRelease>", lambda _event: self.tutar_guncelle())
        ttk.Button(self, text="İptal", command=self.destroy).grid(row=len(self.alanlar) + 1, column=0, padx=8, pady=10)
        ttk.Button(self, text="Ekle", command=self.kaydet).grid(row=len(self.alanlar) + 1, column=1, padx=8, pady=10, sticky="e")
        self.tutar_guncelle()

    def urun_arama_ac(self, _event):
        widget = self.focus_get()
        sorgu = widget.get().strip() if widget in (self.girdiler.get("urun_kodu"), self.girdiler.get("urun_adi")) else ""
        if len(sorgu) < 3 or sorgu == self._son_urun_arama:
            return
        self._son_urun_arama = sorgu
        ProductSelectionDialog(self, sorgu, self.urun_secildi)

    def urun_secildi(self, degerler):
        for alan, deger in (("urun_kodu", degerler[0]), ("urun_adi", degerler[1]), ("birim", degerler[2]), ("birim_satis_fiyati", degerler[4])):
            widget = self.girdiler[alan]
            widget.delete(0, "end")
            widget.insert(0, deger)
        self.tutar_guncelle()

    def fiyat_secimi_ac(self, _event):
        PriceSelectionDialog(self, self.girdiler["urun_kodu"].get().strip())
        return "break"

    def tutar_guncelle(self):
        try:
            miktar = decimal(self.girdiler["miktar"].get() or 0, "Miktar")
            fiyat = decimal(self.girdiler["birim_satis_fiyati"].get() or 0, "Birim fiyat")
            iskonto = decimal(self.girdiler["iskonto_orani"].get() or 0, "İskonto")
            tutar = miktar * fiyat * (Decimal("1") - iskonto / Decimal("100"))
            self._tutar_etiketi.configure(text=f"Tutar: {para_goster(tutar)}")
        except ValueError:
            self._tutar_etiketi.configure(text="Tutar: 0,00 TL")

    def kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.girdiler.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]:
            messagebox.showwarning("Eksik bilgi", "Ürün kodu ve ürün adı zorunludur.", parent=self)
            return
        try:
            for alan in ("miktar", "birim_satis_fiyati", "iskonto_orani", "kdv_orani", "fifo_birim_maliyeti", "son_alis_birim_maliyeti", "ortalama_birim_maliyeti", "agirlikli_ortalama_birim_maliyeti"):
                decimal(veri[alan] or 0, alan, Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        self.result = veri
        self.destroy()


class SiparisTahsilatiDialog(tk.Toplevel):
    def __init__(self, parent, veri=None):
        super().__init__(parent)
        self.result = None
        self.title("Sipariş Tahsilatı")
        self.transient(parent)
        self.grab_set()
        alanlar = (("Tahsilat Tarihi", "tahsilat_tarihi"), ("Tutar", "tutar"), ("Ödeme Şekli", "odeme_sekli"), ("Hesap", "hesap"), ("Açıklama", "aciklama"))
        self.girdiler = {}
        for satir, (baslik, alan) in enumerate(alanlar):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=8, pady=5, sticky="w")
            widget = ttk.Combobox(self, values=ODEME_SEKILLERI, state="readonly", width=30) if alan == "odeme_sekli" else ttk.Entry(self, width=32)
            widget.grid(row=satir, column=1, padx=8, pady=5)
            self.girdiler[alan] = widget
        self.girdiler["tahsilat_tarihi"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["odeme_sekli"].set(ODEME_SEKILLERI[0])
        if veri:
            for alan, widget in self.girdiler.items():
                widget.delete(0, "end")
                deger = veri.get(alan, "")
                if alan == "tahsilat_tarihi" and hasattr(deger, "strftime"):
                    deger = deger.strftime("%d.%m.%Y")
                widget.insert(0, deger)
        ttk.Button(self, text="İptal", command=self.destroy).grid(row=5, column=0, padx=8, pady=10)
        ttk.Button(self, text="Ekle", command=self.kaydet).grid(row=5, column=1, padx=8, pady=10, sticky="e")

    def kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.girdiler.items()}
        try:
            veri["tahsilat_tarihi"] = datetime.strptime(veri["tahsilat_tarihi"], "%d.%m.%Y").date()
            decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz tahsilat", str(hata), parent=self)
            return
        self.result = veri
        self.destroy()


class SatisSiparisiDialog(tk.Toplevel):
    def __init__(self, parent, siparis=None):
        super().__init__(parent)
        self.siparis = siparis
        self.result = None
        self.title("Sipariş Kartı")
        self.geometry("1200x760")
        self.minsize(950, 620)
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.tahsilatlar = []
        self.mevcut_borc = Decimal("0")
        self.musteriler = SatisSiparisiService.aktif_musterileri()
        if siparis and siparis.cari and siparis.cari not in self.musteriler:
            self.musteriler.append(siparis.cari)
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self.girdiler = {}
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        genel = ttk.Frame(notebook, padding=10)
        satir_sayfasi = ttk.Frame(notebook, padding=10)
        tahsilat_sayfasi = ttk.Frame(notebook, padding=10)
        notebook.add(genel, text="GENEL BİLGİLER")
        notebook.add(satir_sayfasi, text="SİPARİŞ SATIRLARI")
        notebook.add(tahsilat_sayfasi, text="TAHSİLATLAR")
        self._genel_olustur(genel)
        self._satir_olustur(satir_sayfasi)
        self._tahsilat_olustur(tahsilat_sayfasi)
        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(butonlar, text="Siparişi Kaydet", command=self.kaydet).pack(side="right", padx=8)
        if siparis:
            self._doldur()

    def _girdi(self, parent, satir, baslik, alan, deger=""):
        ttk.Label(parent, text=baslik).grid(row=satir, column=0, padx=8, pady=5, sticky="w")
        widget = ttk.Entry(parent, width=35)
        widget.grid(row=satir, column=1, padx=8, pady=5, sticky="ew")
        widget.insert(0, deger)
        self.girdiler[alan] = widget
        return widget

    def _genel_olustur(self, parent):
        self._girdi(parent, 0, "Sipariş Numarası", "siparis_no", self.siparis.siparis_no if self.siparis else "Otomatik oluşturulacak")
        self._girdi(parent, 1, "Sipariş Tarihi", "siparis_tarihi", tarih_goster(self.siparis.siparis_tarihi) if self.siparis else date.today().strftime("%d.%m.%Y"))
        self._girdi(parent, 2, "Termin Tarihi", "termin_tarihi", tarih_goster(self.siparis.termin_tarihi) if self.siparis else date.today().strftime("%d.%m.%Y"))
        ttk.Label(parent, text="Müşteri").grid(row=3, column=0, padx=8, pady=5, sticky="w")
        self.musteri = ttk.Combobox(parent, values=list(self.musteri_map), state="readonly", width=33)
        self.musteri.grid(row=3, column=1, padx=8, pady=5, sticky="ew")
        self.musteri.bind("<<ComboboxSelected>>", lambda _event: self._bakiye_guncelle())
        self._girdi(parent, 4, "Mevcut Borç Bakiyesi", "mevcut_bakiye", "0,00 TL")
        self.girdiler["mevcut_bakiye"].configure(state="readonly")
        self._girdi(parent, 5, "Tahmini Yeni Bakiye", "tahmini_bakiye", "0,00 TL")
        self.girdiler["tahmini_bakiye"].configure(state="readonly")
        ttk.Label(parent, text="Maliyet Hesaplama Yöntemi").grid(row=6, column=0, padx=8, pady=5, sticky="w")
        self.yontem = ttk.Combobox(parent, values=MALIYET_YONTEMLERI, state="readonly", width=33)
        self.yontem.grid(row=6, column=1, padx=8, pady=5, sticky="ew")
        self.yontem.set(MALIYET_YONTEMLERI[0])
        self.yontem.bind("<<ComboboxSelected>>", lambda _event: self._satir_listesini_yenile())
        self._girdi(parent, 7, "Hedef Kâr Marjı %", "hedef_kar_marji", "0")
        self.girdiler["hedef_kar_marji"].bind("<FocusOut>", lambda _event: self._satir_listesini_yenile())
        self._girdi(parent, 8, "Genel Açıklama / Notlar", "aciklama", "")
        ttk.Label(parent, text="Sipariş Durumu").grid(row=9, column=0, padx=8, pady=5, sticky="w")
        self.durum = ttk.Combobox(parent, values=SIPARIS_DURUMLARI, state="readonly", width=33)
        self.durum.grid(row=9, column=1, padx=8, pady=5, sticky="ew")
        self.durum.set(self.siparis.durum if self.siparis else "AÇIK")
        parent.columnconfigure(1, weight=1)

    def _satir_olustur(self, parent):
        kolonlar = ("urun_kodu", "urun_adi", "miktar", "fiyat", "onerilen", "net", "maliyet", "kar", "marj", "irsaliye", "fatura", "acik")
        self.satir_tablosu = ttk.Treeview(parent, columns=kolonlar, show="headings")
        basliklar = {"urun_kodu": "Ürün Kodu", "urun_adi": "Ürün Adı", "miktar": "Miktar", "fiyat": "Birim Fiyat", "onerilen": "Önerilen Satış Fiyatı", "net": "KDV Hariç Net", "maliyet": "Toplam Maliyet", "kar": "Kâr", "marj": "Kâr Marjı %", "irsaliye": "İrsaliyelenen Miktar", "fatura": "Faturalanan Miktar", "acik": "Açık Sipariş Miktarı"}
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            self.satir_tablosu.column(kolon, width=115, anchor="w")
        dikey = ttk.Scrollbar(parent, orient="vertical", command=self.satir_tablosu.yview)
        yatay = ttk.Scrollbar(parent, orient="horizontal", command=self.satir_tablosu.xview)
        self.satir_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.satir_tablosu.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1); parent.columnconfigure(0, weight=1)
        alt = ttk.Frame(parent); alt.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Button(alt, text="Satır Ekle", command=self.satir_ekle).pack(side="left")
        ttk.Button(alt, text="Satır Düzenle", command=self.satir_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Satır Kaldır", command=self.satir_kaldir).pack(side="left")
        self.satir_ozet = ttk.Label(parent, text="Ara Toplam: 0,00 TL | Genel Toplam: 0,00 TL | Toplam Maliyet: 0,00 TL | Toplam Kâr: 0,00 TL | Gerçekleşen Kâr Marjı: 0,0%")
        self.satir_ozet.grid(row=3, column=0, columnspan=2, sticky="w")

    def _tahsilat_olustur(self, parent):
        kolonlar = ("tarih", "tutar", "sekil", "hesap", "aciklama")
        self.tahsilat_tablosu = ttk.Treeview(parent, columns=kolonlar, show="headings")
        for kolon, baslik in zip(kolonlar, ("Tarih", "Tutar", "Ödeme Şekli", "Hesap", "Açıklama")):
            self.tahsilat_tablosu.heading(kolon, text=baslik); self.tahsilat_tablosu.column(kolon, width=160)
        self.tahsilat_tablosu.pack(fill="both", expand=True)
        alt = ttk.Frame(parent); alt.pack(fill="x", pady=8)
        ttk.Button(alt, text="Tahsilat Ekle", command=self.tahsilat_ekle).pack(side="left")
        ttk.Button(alt, text="Tahsilat Düzenle", command=self.tahsilat_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Tahsilat Kaldır", command=self.tahsilat_kaldir).pack(side="left")
        self.tahsilat_ozet = ttk.Label(parent, text="Tahsil Edilen: 0,00 TL | Kalan Tahsilat: 0,00 TL")
        self.tahsilat_ozet.pack(anchor="w")

    def _doldur(self):
        musteri = next((m for m in self.musteriler if m.id == self.siparis.cari_id), None)
        if musteri: self.musteri.set(f"{musteri.cari_kodu} - {musteri.unvan}")
        self.yontem.set(self.siparis.maliyet_yontemi); self.durum.set(self.siparis.durum)
        self.girdiler["hedef_kar_marji"].delete(0, "end"); self.girdiler["hedef_kar_marji"].insert(0, self.siparis.hedef_kar_marji)
        self.girdiler["aciklama"].delete(0, "end"); self.girdiler["aciklama"].insert(0, self.siparis.aciklama or "")
        for satir in self.siparis.satirlar: self.satirlar.append({alan: getattr(satir, alan) for _, alan in SiparisSatiriDialog.alanlar})
        for tahsilat in self.siparis.tahsilatlar: self.tahsilatlar.append({"tahsilat_tarihi": tahsilat.tahsilat_tarihi, "tutar": tahsilat.tutar, "odeme_sekli": tahsilat.odeme_sekli, "hesap": tahsilat.hesap or "", "aciklama": tahsilat.aciklama or ""})
        self._bakiye_guncelle(); self._satir_listesini_yenile(); self._tahsilat_listesini_yenile()

    def _bakiye_guncelle(self):
        musteri = self.musteri_map.get(self.musteri.get())
        borc = Decimal("0")
        if musteri:
            ozet = next((o for o in CariService.listele() if o["cari"].id == musteri.id), None); borc = ozet["bakiye"] if ozet else borc
        self.mevcut_borc = borc
        self._readonly_yaz("mevcut_bakiye", para_goster(borc)); self._toplamlari_guncelle(borc)

    def _readonly_yaz(self, alan, deger):
        self.girdiler[alan].configure(state="normal"); self.girdiler[alan].delete(0, "end"); self.girdiler[alan].insert(0, deger); self.girdiler[alan].configure(state="readonly")

    def _satir_hesapla(self, veri):
        miktar = decimal(veri.get("miktar", 0), "Miktar"); fiyat = decimal(veri.get("birim_satis_fiyati", 0), "Fiyat"); iskonto = decimal(veri.get("iskonto_orani", 0), "İskonto"); kdv = decimal(veri.get("kdv_orani", 0), "KDV")
        maliyet = decimal(veri.get({"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}[self.yontem.get()], 0), "Maliyet")
        brut = miktar * fiyat; indirim = brut * iskonto / 100; net = brut - indirim; toplam_maliyet = miktar * maliyet; kar = net - toplam_maliyet
        return brut, indirim, net, net * kdv / 100, toplam_maliyet, kar, kar / net * 100 if net else Decimal("0")

    def _satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children(): self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            brut, indirim, net, kdv, maliyet, kar, marj = self._satir_hesapla(veri)
            acik = decimal(veri.get("miktar", 0), "Miktar")
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(veri["urun_kodu"], veri["urun_adi"], veri["miktar"], veri["birim_satis_fiyati"], para_goster(self._onerilen_fiyat(veri)), para_goster(net), para_goster(maliyet), para_goster(kar), f"{marj:.1f}", "0", "0", acik))
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self, borc=None):
        toplam = {"ara_toplam": Decimal("0"), "iskonto": Decimal("0"), "net": Decimal("0"), "kdv": Decimal("0"), "genel": Decimal("0"), "maliyet": Decimal("0"), "kar": Decimal("0")}
        for veri in self.satirlar:
            brut, indirim, net, kdv, maliyet, kar, _ = self._satir_hesapla(veri)
            toplam["ara_toplam"] += brut; toplam["iskonto"] += indirim; toplam["net"] += net; toplam["kdv"] += kdv; toplam["maliyet"] += maliyet; toplam["kar"] += kar
        toplam["genel"] = toplam["net"] + toplam["kdv"]; marj = toplam["kar"] / toplam["net"] * 100 if toplam["net"] else Decimal("0")
        tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0")); kalan = toplam["genel"] - tahsilat
        tahmini_bakiye = self.mevcut_borc + toplam["genel"] - tahsilat
        self.satir_ozet.configure(text=f"Ara Toplam: {para_goster(toplam['ara_toplam'])} | İskonto: {para_goster(toplam['iskonto'])} | KDV: {para_goster(toplam['kdv'])} | Genel Toplam: {para_goster(toplam['genel'])} | Maliyet: {para_goster(toplam['maliyet'])} | Kâr: {para_goster(toplam['kar'])} | Marj: {marj:.1f}% | Tahsilat: {para_goster(tahsilat)} | Kalan: {para_goster(kalan)} | Tahmini Yeni Bakiye: {para_goster(tahmini_bakiye)}")
        self.tahsilat_ozet.configure(text=f"Tahsil Edilen: {para_goster(tahsilat)} | Kalan Tahsilat: {para_goster(kalan)}")
        if borc is not None: self._readonly_yaz("tahmini_bakiye", para_goster(tahmini_bakiye))

    def _onerilen_fiyat(self, veri):
        maliyet_alanlari = {"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}
        maliyet = decimal(veri.get(maliyet_alanlari[self.yontem.get()], 0), "Maliyet")
        hedef = decimal(self.girdiler["hedef_kar_marji"].get() or 0, "Hedef kâr marjı")
        return maliyet / (Decimal("1") - hedef / Decimal("100")) if hedef < Decimal("100") else Decimal("0")

    def satir_ekle(self):
        dialog = SiparisSatiriDialog(self); self.wait_window(dialog)
        if dialog.result: self.satirlar.append(dialog.result); self._satir_listesini_yenile()

    def satir_duzenle(self):
        secim = self.satir_tablosu.selection()
        if secim:
            dialog = SiparisSatiriDialog(self, self.satirlar[int(secim[0])]); self.wait_window(dialog)
            if dialog.result: self.satirlar[int(secim[0])] = dialog.result; self._satir_listesini_yenile()

    def satir_kaldir(self):
        secim = self.satir_tablosu.selection()
        if secim and messagebox.askyesno("Satır kaldır", "Seçili satır kaldırılsın mı?", parent=self): self.satirlar.pop(int(secim[0])); self._satir_listesini_yenile()

    def tahsilat_ekle(self):
        dialog = SiparisTahsilatiDialog(self); self.wait_window(dialog)
        if dialog.result: self.tahsilatlar.append(dialog.result); self._tahsilat_listesini_yenile()

    def _tahsilat_listesini_yenile(self):
        for item in self.tahsilat_tablosu.get_children(): self.tahsilat_tablosu.delete(item)
        for sira, t in enumerate(self.tahsilatlar): self.tahsilat_tablosu.insert("", "end", iid=str(sira), values=(t["tahsilat_tarihi"].strftime("%d.%m.%Y"), para_goster(decimal(t["tutar"], "Tutar")), t["odeme_sekli"], t.get("hesap", ""), t.get("aciklama", "")))
        self._toplamlari_guncelle()

    def tahsilat_duzenle(self):
        secim = self.tahsilat_tablosu.selection()
        if secim:
            dialog = SiparisTahsilatiDialog(self, self.tahsilatlar[int(secim[0])]); self.wait_window(dialog)
            if dialog.result: self.tahsilatlar[int(secim[0])] = dialog.result; self._tahsilat_listesini_yenile()

    def tahsilat_kaldir(self):
        secim = self.tahsilat_tablosu.selection()
        if secim and messagebox.askyesno("Tahsilat kaldır", "Seçili tahsilat kaldırılsın mı?", parent=self): self.tahsilatlar.pop(int(secim[0])); self._tahsilat_listesini_yenile()

    def kaydet(self):
        try:
            musteri = self.musteri_map.get(self.musteri.get())
            if not musteri: raise ValueError("Aktif bir müşteri seçin.")
            veriler = {"siparis_tarihi": datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date(), "termin_tarihi": datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date(), "cari_id": musteri.id, "maliyet_yontemi": self.yontem.get(), "hedef_kar_marji": self.girdiler["hedef_kar_marji"].get(), "aciklama": self.girdiler["aciklama"].get()}
            if not self.satirlar: raise ValueError("En az bir sipariş satırı ekleyin.")
            SatisSiparisiService.kaydet(veriler, self.satirlar, self.tahsilatlar, self.siparis.id if self.siparis else None)
        except ValueError as hata: messagebox.showerror("Sipariş kaydedilemedi", str(hata), parent=self); return
        self.result = True; self.destroy()


class MuhasebeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Muhasebe Programı")
        self.geometry("1250x680")
        self.minsize(950, 560)
        self._stil_ayarla()
        self._arayuzu_olustur()
        self.ana_sayfa_goster()

    def _stil_ayarla(self):
        stil = ttk.Style(self)
        if "vista" in stil.theme_names():
            stil.theme_use("vista")
        stil.configure("Baslik.TLabel", font=("Segoe UI", 18, "bold"))
        stil.configure("Menu.TButton", anchor="w", padding=(14, 10))
        stil.configure("AltMenu.TButton", anchor="w", padding=(16, 12))
        stil.configure("SeciliMenu.TButton", anchor="w", padding=(14, 10), foreground="#ffffff", background="#1f6aa5")
        stil.map(
            "SeciliMenu.TButton",
            background=[("active", "#185582"), ("!disabled", "#1f6aa5")],
            foreground=[("!disabled", "#ffffff")],
        )

    def _arayuzu_olustur(self):
        self.menu = ttk.Frame(self, padding=(12, 18))
        self.menu.pack(side="left", fill="y")
        ttk.Label(self.menu, text="MUHASEBE", font=("Segoe UI", 14, "bold")).pack(pady=(4, 22))

        menu_ogeleri = (
            ("GİRİŞ EKRANI", "giris"),
            ("SATIŞLAR", "satislar"),
            ("SATIN ALMA", "satin_alma"),
            ("STOKLAR", "stoklar"),
            ("FİNANS", "finans"),
            ("GELİR VE GİDERLER", "gelir_gider"),
            ("ÖZET TABLOLAR", "ozet_tablolar"),
        )
        self.menu_dugmeleri = {}
        for baslik, anahtar in menu_ogeleri:
            dugme = ttk.Button(
                self.menu,
                text=baslik,
                style="Menu.TButton",
                command=lambda secim=anahtar: self.sayfa_goster(secim),
            )
            dugme.pack(fill="x", pady=3)
            self.menu_dugmeleri[anahtar] = dugme

        self.icerik = ttk.Frame(self, padding=(24, 20))
        self.icerik.pack(side="right", fill="both", expand=True)

    def _icerigi_temizle(self):
        for widget in self.icerik.winfo_children():
            widget.destroy()

    def ana_sayfa_goster(self):
        self.sayfa_goster("giris")

    def sayfa_goster(self, anahtar):
        self._icerigi_temizle()
        for dugme_anahtari, dugme in self.menu_dugmeleri.items():
            dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == anahtar else "Menu.TButton")

        basliklar = {
            "giris": "GİRİŞ EKRANI",
            "satislar": "SATIŞLAR",
            "satin_alma": "SATIN ALMA",
            "stoklar": "STOKLAR",
            "finans": "FİNANS",
            "gelir_gider": "GELİR VE GİDERLER",
            "ozet_tablolar": "ÖZET TABLOLAR",
        }
        ttk.Label(self.icerik, text=basliklar[anahtar], style="Baslik.TLabel").pack(anchor="w")
        if anahtar == "giris":
            ttk.Label(self.icerik, text="Muhasebe programına hoş geldiniz.").pack(anchor="w", pady=(18, 8))
            ttk.Label(
                self.icerik,
                text="İşletmenizin satış, satın alma, stok, finans ve gelir-gider süreçlerini bu uygulamadan yönetebilirsiniz.",
                wraplength=760,
                justify="left",
            ).pack(anchor="w")
        elif anahtar == "satislar":
            self.satislar_menusu_goster()
        else:
            ttk.Label(self.icerik, text="Bu bölüm sonraki aşamada hazırlanacaktır.").pack(anchor="w", pady=(18, 0))

    def satislar_menusu_goster(self):
        alt_menu = ttk.Frame(self.icerik)
        alt_menu.pack(fill="x", pady=(24, 0))
        alt_menu.columnconfigure(0, weight=1)
        alt_menu.columnconfigure(0, minsize=520)

        alt_menu_ogeleri = (
            ("MÜŞTERİ KARTLARI", self.cariler_goster),
            ("SATIŞ SİPARİŞLERİ", self.satis_siparisleri_goster),
            ("SATIŞ İRSALİYELERİ", lambda: self.satis_alt_sayfasi_goster("SATIŞ İRSALİYELERİ")),
            ("SATIŞ FATURALARI", lambda: self.satis_alt_sayfasi_goster("SATIŞ FATURALARI")),
            ("CARİ VİRMAN", lambda: self.satis_alt_sayfasi_goster("CARİ VİRMAN")),
            ("MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", lambda: self.satis_alt_sayfasi_goster("MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ")),
            ("RAPORLAR", lambda: self.satis_alt_sayfasi_goster("RAPORLAR")),
        )
        for satir, (baslik, komut) in enumerate(alt_menu_ogeleri):
            ttk.Button(
                alt_menu,
                text=baslik,
                style="AltMenu.TButton",
                command=komut,
            ).grid(row=satir, column=0, sticky="ew", pady=4)

    def satis_alt_sayfasi_goster(self, baslik):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(self.icerik, text="Bu bölüm sonraki aşamada hazırlanacaktır.").pack(anchor="w", pady=(18, 0))

    def satis_siparisleri_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIŞ SİPARİŞLERİ", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(14, 0))
        kolonlar = ("no", "siparis_tarihi", "termin", "musteri_kodu", "musteri", "toplam", "tahsilat", "kalan", "durum")
        basliklar = {"no": "Sipariş Numarası", "siparis_tarihi": "Sipariş Tarihi", "termin": "Termin Tarihi", "musteri_kodu": "Müşteri Kodu", "musteri": "Müşteri Adı", "toplam": "Sipariş Toplamı", "tahsilat": "Tahsil Edilen", "kalan": "Kalan Tahsilat", "durum": "Durum"}
        self.siparis_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon in kolonlar:
            self.siparis_tablosu.heading(kolon, text=basliklar[kolon])
            self.siparis_tablosu.column(kolon, width=125, anchor="w")
        self.siparis_tablosu.column("no", width=190)
        self.siparis_tablosu.column("musteri", width=190)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.siparis_tablosu.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.siparis_tablosu.xview)
        self.siparis_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.siparis_tablosu.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        self.siparis_tablosu.bind("<Double-1>", lambda _event: self.siparis_ac())
        alt = ttk.Frame(self.icerik); alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Sipariş", command=self.yeni_siparis).pack(side="left")
        ttk.Button(alt, text="Siparişi Aç / Düzenle", command=self.siparis_ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal Et", command=self.siparis_iptal).pack(side="left")
        self.siparis_listesini_yenile()

    def siparis_listesini_yenile(self):
        for item in self.siparis_tablosu.get_children(): self.siparis_tablosu.delete(item)
        for kayit in SatisSiparisiService.listele():
            siparis = kayit["siparis"]; musteri = kayit["musteri"]
            self.siparis_tablosu.insert("", "end", iid=str(siparis.id), values=(siparis.siparis_no, tarih_goster(siparis.siparis_tarihi), tarih_goster(siparis.termin_tarihi), musteri.cari_kodu if musteri else "", musteri.unvan if musteri else "", para_goster(kayit["toplam"]), para_goster(kayit["tahsilat"]), para_goster(kayit["kalan"]), siparis.durum))

    def _secili_siparis_id(self):
        secim = self.siparis_tablosu.selection()
        if not secim:
            messagebox.showinfo("Sipariş seçimi", "Lütfen bir sipariş seçin.", parent=self)
            return None
        return int(secim[0])

    def yeni_siparis(self):
        dialog = SatisSiparisiDialog(self); self.wait_window(dialog)
        if dialog.result: self.siparis_listesini_yenile()

    def siparis_ac(self):
        siparis_id = self._secili_siparis_id()
        if siparis_id is not None:
            siparis = SatisSiparisiService.getir(siparis_id)
            if siparis:
                dialog = SatisSiparisiDialog(self, siparis); self.wait_window(dialog)
                if dialog.result: self.siparis_listesini_yenile()

    def siparis_iptal(self):
        siparis_id = self._secili_siparis_id()
        if siparis_id is not None and messagebox.askyesno("Siparişi iptal et", "Seçili sipariş iptal edilsin mi?", parent=self):
            try: SatisSiparisiService.iptal_et(siparis_id)
            except ValueError as hata: messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
            self.siparis_listesini_yenile()

    def firmalar_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="Firmalar", style="Baslik.TLabel").pack(anchor="w")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=35)
        self.arama.pack(side="left", padx=8)
        self.arama.bind("<Return>", lambda _event: self.firma_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.firma_listesini_yenile).pack(side="left")
        ttk.Button(ust, text="Yeni Firma", command=self.yeni_firma).pack(side="right")

        tablo_cerceve = ttk.Frame(self.icerik)
        tablo_cerceve.pack(fill="both", expand=True)
        kolonlar = ("id", "kod", "unvan", "vergi", "telefon", "durum")
        self.firma_tablosu = ttk.Treeview(tablo_cerceve, columns=kolonlar, show="headings", selectmode="browse")
        basliklar = {"id": "ID", "kod": "Firma Kodu", "unvan": "Ünvan", "vergi": "Vergi No", "telefon": "Telefon", "durum": "Durum"}
        genislikler = {"id": 55, "kod": 120, "unvan": 280, "vergi": 130, "telefon": 130, "durum": 90}
        for kolon in kolonlar:
            self.firma_tablosu.heading(kolon, text=basliklar[kolon])
            self.firma_tablosu.column(kolon, width=genislikler[kolon], anchor="w")
        kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.firma_tablosu.yview)
        self.firma_tablosu.configure(yscrollcommand=kaydirma.set)
        self.firma_tablosu.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=(10, 0))
        ttk.Button(alt, text="Düzenle", command=self.firma_duzenle).pack(side="left")
        ttk.Button(alt, text="Pasife Al", command=self.firma_pasife_al).pack(side="left", padx=8)
        self.firma_listesini_yenile()

    def firma_listesini_yenile(self):
        if not hasattr(self, "firma_tablosu"):
            return
        for item in self.firma_tablosu.get_children():
            self.firma_tablosu.delete(item)
        arama = self.arama.get() if hasattr(self, "arama") else ""
        for firma in FirmaService.listele(arama):
            durum = "Aktif" if firma.aktif else "Pasif"
            self.firma_tablosu.insert("", "end", iid=str(firma.id), values=(firma.id, firma.firma_kodu, firma.unvan, firma.vergi_no or "", firma.telefon or "", durum))

    def _secili_firma(self):
        secim = self.firma_tablosu.selection()
        if not secim:
            messagebox.showinfo("Firma seçimi", "Lütfen bir firma seçin.", parent=self)
            return None
        return FirmaService.getir(int(secim[0]))

    def yeni_firma(self):
        dialog = FirmaDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.firma_listesini_yenile()

    def firma_duzenle(self):
        firma = self._secili_firma()
        if firma:
            dialog = FirmaDialog(self, firma)
            self.wait_window(dialog)
            if dialog.result:
                self.firma_listesini_yenile()

    def firma_pasife_al(self):
        firma = self._secili_firma()
        if firma and firma.aktif and messagebox.askyesno("Pasife al", f"'{firma.unvan}' pasife alınsın mı?", parent=self):
            try:
                FirmaService.pasife_al(firma.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
            self.firma_listesini_yenile()

    def donemler_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="Dönemler", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(self.icerik, text="Dönem yönetimi bir sonraki geliştirme adımında eklenecektir.").pack(anchor="w", pady=14)

    def cariler_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="MÜŞTERİ KARTLARI", style="Baslik.TLabel").pack(anchor="w")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara (en az 3 karakter):").pack(side="left")
        self.cari_arama = ttk.Entry(ust, width=30)
        self.cari_arama.pack(side="left", padx=8)
        self.cari_arama.bind("<Return>", lambda _event: self.cari_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.cari_listesini_yenile).pack(side="left")
        ttk.Button(ust, text="Yeni Müşteri", command=self.yeni_cari).pack(side="right")

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "unvan", "grup", "telefon", "email", "bakiye", "agirlikli", "durum")
        basliklar = {"kod": "Müşteri Kodu", "unvan": "Müşteri Adı", "grup": "Müşteri Grubu", "telefon": "Telefon", "email": "E-posta", "bakiye": "Yekûn Bakiye", "agirlikli": "Ağırlıklı Ortalama Geçen Gün", "durum": "Durum"}
        genislikler = {"kod": 110, "unvan": 210, "grup": 135, "telefon": 115, "email": 180, "bakiye": 125, "agirlikli": 180, "durum": 75}
        self.cari_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon in kolonlar:
            self.cari_tablosu.heading(kolon, text=basliklar[kolon])
            self.cari_tablosu.column(kolon, width=genislikler[kolon], anchor="w")
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.cari_tablosu.yview)
        self.cari_tablosu.configure(yscrollcommand=kaydirma.set)
        self.cari_tablosu.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        self.cari_tablosu.bind("<Double-1>", lambda _event: self.cari_detay())

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=(10, 0))
        ttk.Button(alt, text="Müşteri Kartını Aç", command=self.cari_detay).pack(side="left")
        ttk.Button(alt, text="Düzenle", command=self.cari_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Pasife Al", command=self.cari_pasife_al).pack(side="left")
        self.cari_listesini_yenile()

    def cari_listesini_yenile(self):
        if not hasattr(self, "cari_tablosu"):
            return
        for item in self.cari_tablosu.get_children():
            self.cari_tablosu.delete(item)
        try:
            cariler = CariService.listele(self.cari_arama.get())
        except ValueError as hata:
            messagebox.showwarning("Arama", str(hata), parent=self)
            return
        for ozet in cariler:
            cari = ozet["cari"]
            self.cari_tablosu.insert("", "end", iid=str(cari.id), values=(cari.cari_kodu, cari.unvan, cari.musteri_grubu or "", cari.telefon or "", cari.email or "", para_goster(ozet["bakiye"]), f"{ozet['agirlikli_ortalama_gun']:.1f}", "Aktif" if cari.aktif else "Pasif"))

    def _secili_cari(self):
        secim = self.cari_tablosu.selection()
        if not secim:
            messagebox.showinfo("Cari seçimi", "Lütfen bir cari seçin.", parent=self)
            return None
        return CariService.getir(int(secim[0]))

    def yeni_cari(self):
        dialog = CariDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.cari_listesini_yenile()

    def cari_duzenle(self):
        cari = self._secili_cari()
        if cari:
            dialog = CariDialog(self, cari)
            self.wait_window(dialog)
            if dialog.result:
                self.cari_listesini_yenile()

    def cari_pasife_al(self):
        cari = self._secili_cari()
        if cari and cari.aktif and messagebox.askyesno("Pasife al", f"'{cari.unvan}' pasife alınsın mı?", parent=self):
            try:
                CariService.pasife_al(cari.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
            self.cari_listesini_yenile()

    def cari_detay(self):
        cari = self._secili_cari()
        if not cari:
            return
        kart = CariDialog(self, cari)
        self.wait_window(kart)
        if kart.result:
            self.cari_listesini_yenile()

