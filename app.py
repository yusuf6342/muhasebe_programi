import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.cari_service import CariService
from database.firma_service import FirmaService
from database.satis_irsaliyesi_service import SatisIrsaliyesiService
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_siparisi_service import (
    MALIYET_YONTEMLERI,
    ODEME_SEKILLERI,
    SIPARIS_DURUMLARI,
    SatisSiparisiService,
    decimal,
)
from product_provider import search_prices, search_products
from database.stok_service import StokService
from database.finans_service import FinansService

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")


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


class NotlarDialog(tk.Toplevel):
    def __init__(self, parent, cari):
        super().__init__(parent)
        self.parent_kart = parent
        self.cari = cari
        self.orijinal_not = (cari.ozel_notlar or "")
        self.kaydedildi = False
        self.title("İSTİHBARAT VE NOTLAR")
        self.geometry("620x420")
        self.minsize(480, 320)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        ttk.Label(self, text="İstihbarat / Özel Notlar", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.not_alani = tk.Text(self, wrap="word", width=70, height=15)
        self.not_alani.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.not_alani.insert("1.0", self.orijinal_not)
        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(butonlar, text="Kapat", command=self.kapat).pack(side="right")
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right", padx=(0, 8))

    def mevcut_not(self):
        return self.not_alani.get("1.0", "end").strip()

    def kaydet(self):
        try:
            CariService.guncelle(self.cari.id, {"ozel_notlar": self.mevcut_not() or None})
        except ValueError as hata:
            messagebox.showerror("Not kaydedilemedi", str(hata), parent=self)
            return
        self.cari.ozel_notlar = self.mevcut_not()
        self.orijinal_not = self.mevcut_not()
        self.kaydedildi = True
        self.parent_kart.not_durumunu_guncelle()
        messagebox.showinfo("Notlar", "İstihbarat ve özel notlar kaydedildi.", parent=self)

    def kapat(self):
        if self.mevcut_not() != self.orijinal_not:
            devam = messagebox.askyesno(
                "Kaydedilmemiş değişiklik",
                "Kaydedilmemiş değişiklikler var. Kapatmak istiyor musunuz?",
                parent=self,
            )
            if not devam:
                return
        self.destroy()


class CariDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, cari=None):
        super().__init__(parent)
        self.cari = cari
        self.result = None
        self.title("Müşteri Kartı" if cari else "Yeni Müşteri")
        self.geometry("1120x760")
        self.minsize(780, 560)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.transient(parent)
        self.grab_set()
        self.degerler = {}
        self.ozet_degerleri = {}
        self.hareket_tablosu = None

        kaydirma_alani = ttk.Frame(self, padding=10)
        kaydirma_alani.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(kaydirma_alani, highlightthickness=0)
        dikey_kaydirma = ttk.Scrollbar(kaydirma_alani, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=dikey_kaydirma.set)
        dikey_kaydirma.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        icerik = ttk.Frame(self.canvas, padding=8)
        pencere = self.canvas.create_window((0, 0), window=icerik, anchor="nw")
        icerik.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(pencere, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        ttk.Label(icerik, text="MÜŞTERİ BİLGİLERİ", style="Baslik.TLabel").pack(anchor="w", pady=(0, 6))
        genel = ttk.LabelFrame(icerik, text="Müşteri Bilgileri", padding=10)
        genel.pack(fill="x", pady=(0, 10))

        alanlar = (
            ("Müşteri Kodu", "cari_kodu"),
            ("Müşteri Adı / Ünvanı", "unvan"),
            ("Vergi Dairesi", "vergi_dairesi"),
            ("Vergi Numarası", "vergi_numarasi"),
            ("Telefon", "telefon"),
            ("E-posta", "email"),
            ("Müşteri Grubu", "musteri_grubu"),
            ("Adres", "adres"),
        )
        for sira, (etiket, alan) in enumerate(alanlar):
            sutun = (sira % 2) * 2
            satir = sira // 2
            ttk.Label(genel, text=etiket).grid(row=satir, column=sutun, padx=8, pady=5, sticky="nw")
            if alan == "musteri_grubu":
                widget = ttk.Combobox(genel, state="readonly", width=47)
                widget.grid(row=satir, column=sutun + 1, padx=8, pady=5, sticky="ew")
                ttk.Button(genel, text="Yeni Grup Ekle", command=self.yeni_grup_ekle).grid(row=satir, column=sutun + 2, padx=(0, 8), pady=5)
            else:
                widget = tk.Text(genel, width=48, height=3) if alan in ("adres", "ozel_notlar") else ttk.Entry(genel, width=50)
                widget.grid(row=satir, column=sutun + 1, padx=8, pady=5, sticky="ew")
            self.degerler[alan] = widget
        for sutun in (1, 4):
            genel.columnconfigure(sutun, weight=1)
        self.musteri_grubu_secimini_hazirla()
        durum = tk.BooleanVar(value=cari.aktif if cari else True)
        self.degerler["aktif"] = durum
        self.not_butonu = ttk.Button(genel, text="İSTİHBARAT VE NOTLAR", command=self.notlari_ac, state="normal" if cari else "disabled")
        self.not_butonu.grid(row=4, column=0, padx=8, pady=8, sticky="w")
        self.not_durumu = ttk.Label(genel, text="Not mevcut" if cari and cari.ozel_notlar else "")
        self.not_durumu.grid(row=4, column=1, padx=8, pady=8, sticky="w")
        ttk.Checkbutton(genel, text="Aktif", variable=durum).grid(row=5, column=1, padx=8, pady=6, sticky="w")
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
        self._bakiye_ozetini_olustur(icerik)
        self._hizli_islemleri_olustur(icerik)
        self._hareket_tablosunu_olustur(icerik)

        butonlar = ttk.Frame(icerik)
        butonlar.pack(fill="x", pady=(10, 4))
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        if cari:
            ttk.Button(butonlar, text="Pasife Al" if cari.aktif else "Aktif Et", command=self.durumu_degistir).pack(side="right", padx=8)
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.degerler["cari_kodu"].focus_set()

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def notlari_ac(self):
        if self.cari:
            dialog = NotlarDialog(self, self.cari)
            self.wait_window(dialog)

    def not_durumunu_guncelle(self):
        if self.cari and self.cari.ozel_notlar:
            self.not_durumu.configure(text="Not mevcut")
        else:
            self.not_durumu.configure(text="")

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

    def _bakiye_ozetini_olustur(self, parent):
        ozet = ttk.LabelFrame(parent, text="BAKİYE ÖZETİ", padding=10)
        ozet.pack(fill="x", pady=(0, 10))
        bakiye = Decimal("0")
        ortalama = 0
        acik_hareket_sayisi = 0
        if self.cari:
            kayit = next((item for item in CariService.listele() if item["cari"].id == self.cari.id), None)
            if kayit:
                bakiye = kayit["bakiye"]
                ortalama = kayit["agirlikli_ortalama_gun"]
            detay = CariService.detay(self.cari.id)
            acik_hareket_sayisi = sum(1 for hareket in detay["hareketler"] if hareket.kalan_acik_tutar > 0) if detay else 0
        if bakiye > 0:
            durum_metni, renk = "Borçlu", "#c62828"
        elif bakiye < 0:
            durum_metni, renk = "Alacaklı", "#2e7d32"
        else:
            durum_metni, renk = "Sıfır", "#444444"
        bilgiler = (("Güncel Toplam Bakiye", para_goster(bakiye)), ("Borç / Alacak Durumu", durum_metni), ("Ağırlıklı Ortalama Geçen Gün", f"{ortalama:.1f} gün"), ("Açık Hareket Sayısı", str(acik_hareket_sayisi)))
        for sutun, (baslik, deger) in enumerate(bilgiler):
            alan = ttk.Frame(ozet, padding=(8, 2))
            alan.grid(row=0, column=sutun, sticky="w")
            ttk.Label(alan, text=baslik, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            deger_etiketi = ttk.Label(alan, text=deger, foreground=renk if baslik != "Ağırlıklı Ortalama Geçen Gün" and baslik != "Açık Hareket Sayısı" else "#1f6aa5", font=("Segoe UI", 11, "bold"))
            deger_etiketi.pack(anchor="w", pady=(3, 0))
            self.ozet_degerleri[baslik] = deger_etiketi

    def _hizli_islemleri_olustur(self, parent):
        hizli = ttk.LabelFrame(parent, text="HIZLI İŞLEMLER", padding=8)
        hizli.pack(fill="x", pady=(0, 10))
        self.hizli_dugmeleri = []
        komutlar = (
            ("YENİ SİPARİŞ", self.yeni_siparis_ac),
            ("YENİ İRSALİYE", self.yeni_irsaliye_ac),
            ("YENİ FATURA", self.yeni_fatura_ac),
            ("TAHSİLAT GİR", self.tahsilat_gir),
            ("ÖDEME GİR", self.odeme_gir),
        )
        for sutun, (baslik, komut) in enumerate(komutlar):
            hizli.columnconfigure(sutun, weight=1)
            dugme = ttk.Button(hizli, text=baslik, command=komut, state="normal" if self.cari else "disabled")
            dugme.grid(row=0, column=sutun, padx=4, sticky="ew")
            self.hizli_dugmeleri.append(dugme)

        ttk.Button(hizli, text="Yenile", command=self.yenile).grid(row=1, column=4, padx=4, pady=(8, 0), sticky="e")

    def _hareket_tablosunu_olustur(self, parent):
        ttk.Label(parent, text="CARİ HAREKETLER", style="Baslik.TLabel").pack(anchor="w", pady=(0, 6))
        hareket_cercevesi = ttk.LabelFrame(parent, text="Cari Hareketler", padding=8)
        hareket_cercevesi.pack(fill="both", expand=True)

        kolonlar = ("tarih", "tur", "belge", "aciklama", "borc", "alacak", "bakiye", "gun")
        tablo_cercevesi = ttk.Frame(hareket_cercevesi)
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
        self.hareket_tablosu = tablo
        if not self.cari:
            return
        detay = CariService.detay(self.cari.id)
        for hareket in detay["hareketler"] if detay else []:
            gun = (date.today() - hareket.satis_tarihi).days
            tablo.insert("", "end", values=(tarih_goster(hareket.satis_tarihi), "Satış", hareket.belge_no, "", para_goster(hareket.satis_tutari), para_goster(0), para_goster(hareket.kalan_acik_tutar), gun))

    def yenile(self):
        if not self.cari:
            return
        kayit = next((item for item in CariService.listele() if item["cari"].id == self.cari.id), None)
        bakiye = kayit["bakiye"] if kayit else Decimal("0")
        ortalama = kayit["agirlikli_ortalama_gun"] if kayit else 0
        detay = CariService.detay(self.cari.id)
        hareketler = detay["hareketler"] if detay else []
        acik_sayisi = sum(1 for hareket in hareketler if hareket.kalan_acik_tutar > 0)
        durum = "Borçlu" if bakiye > 0 else "Alacaklı" if bakiye < 0 else "Sıfır"
        renk = "#c62828" if bakiye > 0 else "#2e7d32" if bakiye < 0 else "#444444"
        self.ozet_degerleri["Güncel Toplam Bakiye"].configure(text=para_goster(bakiye), foreground=renk)
        self.ozet_degerleri["Borç / Alacak Durumu"].configure(text=durum, foreground=renk)
        self.ozet_degerleri["Ağırlıklı Ortalama Geçen Gün"].configure(text=f"{ortalama:.1f} gün")
        self.ozet_degerleri["Açık Hareket Sayısı"].configure(text=str(acik_sayisi))
        for item in self.hareket_tablosu.get_children():
            self.hareket_tablosu.delete(item)
        for hareket in hareketler:
            gun = (date.today() - hareket.satis_tarihi).days
            self.hareket_tablosu.insert("", "end", values=(tarih_goster(hareket.satis_tarihi), "Satış", hareket.belge_no, "", para_goster(hareket.satis_tutari), para_goster(0), para_goster(hareket.kalan_acik_tutar), gun))

    def yeni_siparis_ac(self):
        if not self.cari:
            return
        siparis = SatisSiparisiDialog(self, cari=self.cari)
        self.wait_window(siparis)
        self.yenile()

    def yeni_irsaliye_ac(self):
        if self.cari:
            dialog = SatisIrsaliyesiDialog(self, cari=self.cari)
            self.wait_window(dialog)
            self.yenile()

    def yeni_fatura_ac(self):
        if self.cari:
            dialog = SatisFaturasiDialog(self, cari=self.cari, cari_ac=lambda cari: CariDialog(self, cari))
            self.wait_window(dialog)
            self.yenile()

    def tahsilat_gir(self):
        if self.cari:
            self.tahsilat_musteri_hazirligi(self.cari.id)

    def odeme_gir(self):
        if self.cari:
            self.odeme_musteri_hazirligi(self.cari.id)

    def irsaliye_musteri_hazirligi(self, cari_id):
        messagebox.showinfo("Yeni İrsaliye", "Satış İrsaliyesi bölümü sonraki aşamada hazırlanacaktır. Müşteri bilgisi otomatik aktarılmaya hazırdır.", parent=self)

    def fatura_musteri_hazirligi(self, cari_id):
        messagebox.showinfo("Yeni Fatura", "Satış Faturası bölümü sonraki aşamada hazırlanacaktır. Müşteri bilgisi otomatik aktarılmaya hazırdır.", parent=self)

    def tahsilat_musteri_hazirligi(self, cari_id):
        messagebox.showinfo("Tahsilat Gir", "Tahsilat işlemi Finans bölümüyle birlikte sonraki aşamada hazırlanacaktır.", parent=self)

    def odeme_musteri_hazirligi(self, cari_id):
        messagebox.showinfo("Ödeme Gir", "Ödeme işlemi Finans bölümüyle birlikte sonraki aşamada hazırlanacaktır.", parent=self)

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

    def durumu_degistir(self):
        yeni_durum = not self.cari.aktif
        try:
            self.result = CariService.guncelle(self.cari.id, {"aktif": yeni_durum})
        except ValueError as hata:
            messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
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
    def __init__(self, parent, product_code, on_select=None):
        super().__init__(parent)
        self.title("Fiyat Seçimi")
        self.geometry("620x300")
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text=f"Ürün: {product_code}").pack(anchor="w", padx=12, pady=(12, 6))
        kolonlar = ("ad", "fiyat", "para", "tarih")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (("ad", "Fiyat Adı", 180), ("fiyat", "Fiyat", 120), ("para", "Para Birimi", 120), ("tarih", "Geçerlilik Tarihi", 150)):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik)
        self.tablo.pack(fill="both", expand=True, padx=12, pady=6)
        self.fiyatlar = search_prices(product_code)
        for sira, fiyat in enumerate(self.fiyatlar):
            self.tablo.insert("", "end", iid=str(sira), values=(fiyat.fiyat_adi, fiyat.tutar, fiyat.para_birimi, "Sürekli"))
        if not self.fiyatlar:
            ttk.Label(self, text="Bu ürüne ait tanımlı fiyat bulunamadı").pack(anchor="w", padx=12, pady=4)
        self.tablo.bind("<Double-1>", lambda _event: self.sec())
        alt = ttk.Frame(self); alt.pack(fill="x", padx=12, pady=8)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Fiyatı Seç", command=self.sec).pack(side="right", padx=8)
        self.on_select = on_select

    def sec(self):
        secim = self.tablo.selection()
        if secim and self.on_select:
            self.on_select(self.fiyatlar[int(secim[0])])
            self.destroy()


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
            if alan == "odeme_sekli":
                widget = ttk.Combobox(self, values=ODEME_SEKILLERI, state="readonly", width=30)
            elif alan == "hesap":
                widget = ttk.Combobox(self, values=tuple(h.hesap_adi for h in FinansService.hesaplar()), state="readonly", width=30)
            else:
                widget = ttk.Entry(self, width=32)
            widget.grid(row=satir, column=1, padx=8, pady=5)
            self.girdiler[alan] = widget
        self.girdiler["tahsilat_tarihi"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["odeme_sekli"].set(ODEME_SEKILLERI[0])
        hesaplar = FinansService.hesaplar()
        if hesaplar: self.girdiler["hesap"].set(hesaplar[0].hesap_adi)
        if veri:
            for alan, widget in self.girdiler.items():
                deger = veri.get(alan, "")
                if alan == "tahsilat_tarihi" and hasattr(deger, "strftime"):
                    deger = deger.strftime("%d.%m.%Y")
                if isinstance(widget, ttk.Combobox):
                    widget.set(deger)
                else:
                    widget.delete(0, "end")
                    widget.insert(0, deger)
        ttk.Button(self, text="İptal", command=self.destroy).grid(row=5, column=0, padx=8, pady=10)
        ttk.Button(self, text="Ekle", command=self.kaydet).grid(row=5, column=1, padx=8, pady=10, sticky="e")

    def kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.girdiler.items()}
        if not veri["hesap"]:
            messagebox.showwarning("Eksik hesap", "Tahsilatın işleneceği kasa/banka hesabını seçin.", parent=self)
            return
        try:
            veri["tahsilat_tarihi"] = datetime.strptime(veri["tahsilat_tarihi"], "%d.%m.%Y").date()
            decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz tahsilat", str(hata), parent=self)
            return
        self.result = veri
        self.destroy()


class KarlilikAnaliziDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_kart = parent
        self.title("KÂRLILIK ANALİZİ")
        self.geometry("1180x620")
        self.minsize(900, 480)
        self.transient(parent)
        self.grab_set()
        self._olustur()

    def _olustur(self):
        siparis = self.parent_kart.siparis
        musteri = self.parent_kart.musteri.get()
        ttk.Label(self, text="KÂRLILIK ANALİZİ", style="Baslik.TLabel").pack(anchor="w", padx=12, pady=(12, 8))
        secimler = ttk.Frame(self)
        secimler.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(secimler, text="Maliyet Yöntemi:").pack(side="left")
        self.yontem_secimi = ttk.Combobox(secimler, values=MALIYET_YONTEMLERI, state="readonly", width=34)
        self.yontem_secimi.set(self.parent_kart.yontem.get())
        self.yontem_secimi.pack(side="left", padx=(6, 18))
        ttk.Label(secimler, text="Hedef Kâr Marjı %:").pack(side="left")
        self.hedef_marji = ttk.Entry(secimler, width=10)
        self.hedef_marji.insert(0, self.parent_kart.hedef_kar_marji.get())
        self.hedef_marji.pack(side="left", padx=6)
        self.bilgi = ttk.Label(self, anchor="w", justify="left")
        self.bilgi.pack(fill="x", padx=12, pady=(0, 8))
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12)
        kolonlar = ("kod", "ad", "miktar", "fiyat", "net", "birim_maliyet", "maliyet", "kar", "marj")
        basliklar = ("Ürün Kodu", "Ürün Adı", "Miktar", "Birim Satış Fiyatı", "KDV Hariç Net Tutar", "Seçili Birim Maliyet", "Toplam Maliyet", "Kâr/Zarar", "Kâr Marjı %")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=130, anchor="w")
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        ttk.Label(self, text="MALİYET YÖNTEMLERİNİ KARŞILAŞTIR", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.karsilastirma = ttk.Frame(self)
        self.karsilastirma.pack(fill="x", padx=12)
        self.uyari = ttk.Label(self, foreground="#b3261e")
        self.uyari.pack(anchor="w", padx=12, pady=6)
        butonlar = ttk.Frame(self); butonlar.pack(fill="x", padx=12, pady=10)
        ttk.Button(butonlar, text="Yenile", command=self.yenile).pack(side="right")
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right", padx=(0, 8))
        self.yenile()

    def _hesapla(self, veri, yontem):
        miktar = decimal(veri.get("miktar", 0), "Miktar")
        fiyat = decimal(veri.get("birim_satis_fiyati", 0), "Birim fiyat")
        iskonto = decimal(veri.get("iskonto_orani", 0), "İskonto")
        net = miktar * fiyat * (Decimal("1") - iskonto / Decimal("100"))
        alan = {"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}[yontem]
        maliyet = decimal(veri.get(alan, 0), "Maliyet")
        return miktar, fiyat, net, maliyet, miktar * maliyet, net - miktar * maliyet

    def yenile(self):
        siparis = self.parent_kart.siparis
        yontem = self.yontem_secimi.get()
        for item in self.tablo.get_children(): self.tablo.delete(item)
        for widget in self.karsilastirma.winfo_children(): widget.destroy()
        net_toplam = Decimal("0"); maliyet_toplam = Decimal("0"); kar_toplam = Decimal("0"); eksik = 0
        for sira, veri in enumerate(self.parent_kart.satirlar):
            miktar, fiyat, net, maliyet, toplam_maliyet, kar = self._hesapla(veri, yontem)
            maliyet_var = maliyet > 0
            net_toplam += net
            if not maliyet_var: eksik += 1
            else: maliyet_toplam += toplam_maliyet; kar_toplam += kar
            marj = kar / net * Decimal("100") if maliyet_var and net else Decimal("0")
            self.tablo.insert("", "end", iid=str(sira), values=(veri["urun_kodu"], veri["urun_adi"], miktar, para_goster(fiyat), para_goster(net), para_goster(maliyet) if maliyet_var else "Maliyet bulunamadı", para_goster(toplam_maliyet) if maliyet_var else "-", para_goster(kar) if maliyet_var else "-", f"{marj:.1f}" if maliyet_var else "-"))
        marj_toplam = kar_toplam / net_toplam * Decimal("100") if net_toplam else Decimal("0")
        self.bilgi.configure(text=f"Sipariş: {siparis.siparis_no if siparis else 'Yeni sipariş'}    Müşteri: {musteri if (musteri := self.parent_kart.musteri.get()) else '-'}    Maliyet yöntemi: {yontem}\nKDV hariç satış toplamı: {para_goster(net_toplam)}    Toplam maliyet: {para_goster(maliyet_toplam)}    Toplam kâr/zarar: {para_goster(kar_toplam)}    Gerçekleşen kâr marjı: {marj_toplam:.1f}%")
        self.bilgi.configure(foreground="#2e7d32" if kar_toplam > 0 else "#c62828" if kar_toplam < 0 else "#444444")
        self.uyari.configure(text=f"Maliyet bulunamadı: {eksik} satır" if eksik else "")
        for yontem_adi in MALIYET_YONTEMLERI:
            bilinen_kar = Decimal("0"); bilinen_net = Decimal("0"); eksik_sayisi = 0
            for veri in self.parent_kart.satirlar:
                _, _, net, maliyet, _, kar = self._hesapla(veri, yontem_adi)
                if maliyet > 0: bilinen_net += net; bilinen_kar += kar
                else: eksik_sayisi += 1
            renk = "#2e7d32" if bilinen_kar > 0 else "#c62828" if bilinen_kar < 0 else "#444444"
            ttk.Label(self.karsilastirma, text=f"{yontem_adi}\n{para_goster(bilinen_kar)}\nEksik: {eksik_sayisi}", foreground=renk, font=("Segoe UI", 10, "bold"), padding=8).pack(side="left", expand=True, fill="x")


class SatisIrsaliyesiDialog(tk.Toplevel):
    def __init__(self, parent, irsaliye=None, siparis=None, cari=None):
        super().__init__(parent)
        self.irsaliye = irsaliye
        self.siparis = siparis
        self.result = None
        self.title("SATIŞ İRSALİYESİ KARTI")
        self.geometry("1180x760")
        self.minsize(900, 560)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.transient(parent); self.grab_set()
        self.satirlar = []; self.musteriler = SatisIrsaliyesiService.aktif_musterileri()
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        if siparis and siparis.cari and siparis.cari not in self.musteriler: self.musteriler.append(siparis.cari)
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self.girdiler = {}
        alan = ttk.Frame(self, padding=10); alan.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(alan, highlightthickness=0); kaydirma = ttk.Scrollbar(alan, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=kaydirma.set); kaydirma.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas, padding=8); pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(pencere, width=event.width)); self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)
        self._baslik_olustur(); self._satir_olustur(); self._notlar_olustur()
        butonlar = ttk.Frame(self.icerik); butonlar.pack(fill="x", pady=10)
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(butonlar, text="İrsaliyeyi İptal Et", command=self.iptal_et).pack(side="right", padx=8)
        ttk.Button(butonlar, text="İrsaliyeyi Kaydet", command=self.kaydet).pack(side="right")
        if irsaliye: self._doldur()
        elif siparis: self._siparisten_doldur(siparis)
        elif cari:
            self.musteri.set(f"{cari.cari_kodu} - {cari.unvan}")
            self.bakiye_guncelle()

    def _fare_tekerlegi(self, event): self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _girdi(self, parent, row, label, field, value=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=6, pady=4, sticky="w")
        widget = ttk.Entry(parent, width=34); widget.grid(row=row, column=1, padx=6, pady=4, sticky="ew"); widget.insert(0, value); self.girdiler[field] = widget
        return widget

    def _baslik_olustur(self):
        ttk.Label(self.icerik, text="İRSALİYE BİLGİLERİ", style="Baslik.TLabel").pack(anchor="w")
        frame = ttk.LabelFrame(self.icerik, text="İrsaliye Bilgileri", padding=8); frame.pack(fill="x", pady=6)
        self._girdi(frame, 0, "İrsaliye Numarası", "irsaliye_no", self.irsaliye.irsaliye_no if self.irsaliye else "Otomatik oluşturulacak")
        self._girdi(frame, 1, "İrsaliye Tarihi", "irsaliye_tarihi", tarih_goster(self.irsaliye.irsaliye_tarihi) if self.irsaliye else date.today().strftime("%d.%m.%Y"))
        ttk.Label(frame, text="Müşteri").grid(row=2, column=0, padx=6, pady=4, sticky="w")
        self.musteri = ttk.Combobox(frame, values=list(self.musteri_map), state="readonly", width=32); self.musteri.grid(row=2, column=1, padx=6, pady=4, sticky="ew"); self.musteri.bind("<<ComboboxSelected>>", lambda _event: self.bakiye_guncelle())
        self._girdi(frame, 3, "Güncel Borç Bakiyesi", "bakiye", "0,00 TL"); self.girdiler["bakiye"].configure(state="readonly")
        ttk.Label(frame, text="Bağlı Sipariş").grid(row=4, column=0, padx=6, pady=4, sticky="w")
        self.siparis_secimi = ttk.Combobox(frame, state="readonly", width=32); self.siparis_secimi.grid(row=4, column=1, padx=6, pady=4, sticky="ew")
        self.siparisler = SatisIrsaliyesiService.acik_siparisler(); self.siparis_map = {s.siparis_no: s for s in self.siparisler}; self.siparis_secimi["values"] = list(self.siparis_map); self.siparis_secimi.bind("<<ComboboxSelected>>", lambda _event: self.siparisi_secildi())
        ttk.Label(frame, text="İrsaliye Durumu").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.durum = ttk.Combobox(frame, values=("AÇIK", "KISMİ FATURALANDI", "FATURALANDI", "İPTAL"), state="readonly", width=24); self.durum.grid(row=0, column=3, padx=6, pady=4, sticky="ew"); self.durum.set(self.irsaliye.durum if self.irsaliye else "AÇIK")
        frame.columnconfigure(1, weight=1); frame.columnconfigure(3, weight=1)

    def _satir_olustur(self):
        self.satir_girdileri = {}; frame = ttk.LabelFrame(self.icerik, text="İRSALİYE SATIRLARI", padding=8); frame.pack(fill="both", expand=True, pady=6)
        alanlar = (("Ürün Kodu", "urun_kodu"), ("Ürün Adı", "urun_adi"), ("Açıklama", "aciklama"), ("Miktar", "miktar"), ("Birim", "birim"), ("Birim Fiyat", "birim_fiyat"), ("İskonto %", "iskonto_orani"), ("KDV %", "kdv_orani"))
        for col, (label, field) in enumerate(alanlar):
            frame.columnconfigure(col, weight={0: 1, 1: 3, 2: 2}.get(col, 0), minsize={0: 100, 1: 300, 2: 200}.get(col, 0))
            ttk.Label(frame, text=label).grid(row=0, column=col, padx=3, pady=3, sticky="w"); widget = ttk.Combobox(frame, values=BIRIM_SECENEKLERI, state="readonly", width=10) if field == "birim" else ttk.Entry(frame, width={0: 12, 1: 36, 2: 24}.get(col, 10)); widget.grid(row=1, column=col, padx=3, pady=3, sticky="ew"); self.satir_girdileri[field] = widget
            if field in ("urun_kodu", "urun_adi"): widget.bind("<KeyRelease>", self.urun_arama_ac)
            if field == "birim_fiyat": widget.bind("<F10>", self.fiyat_secimi_ac)
        self.satir_girdileri["birim"].set("Adet"); self.satir_girdileri["kdv_orani"].insert(0, "20")
        ttk.Button(frame, text="Ekle/Güncelle", command=self.satir_ekle).grid(row=2, column=0, padx=4, pady=6, sticky="w"); ttk.Button(frame, text="Temizle", command=self.satir_temizle).grid(row=2, column=1, padx=4, pady=6, sticky="w")
        kolonlar = ("kod", "ad", "aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv", "toplam", "fatura", "kalan")
        self.satir_tablosu = ttk.Treeview(frame, columns=kolonlar, show="headings")
        basliklar = ("Ürün Kodu", "Ürün Adı", "Açıklama", "Miktar", "Birim", "Birim Fiyat", "İskonto", "KDV", "Satır Toplamı", "Faturalanan Miktar", "Kalan Faturalanabilir Miktar")
        kolon_genislikleri = {"kod": 100, "ad": 300, "aciklama": 200, "miktar": 75, "birim": 65, "fiyat": 110, "iskonto": 75, "kdv": 65, "toplam": 120, "fatura": 135, "kalan": 150}
        for col, label in zip(kolonlar, basliklar):
            self.satir_tablosu.heading(col, text=label)
            self.satir_tablosu.column(col, width=kolon_genislikleri[col], minwidth=220 if col == "ad" else kolon_genislikleri[col], stretch=col == "ad")
        self.satir_tablosu.grid(row=3, column=0, columnspan=8, sticky="nsew"); self.satir_tablosu.bind("<<TreeviewSelect>>", self.satir_secildi)
        ttk.Button(frame, text="Satır Düzenle", command=self.satir_duzenle).grid(row=4, column=0, pady=6, sticky="w"); ttk.Button(frame, text="Satır Kaldır", command=self.satir_kaldir).grid(row=4, column=1, pady=6, sticky="w")
        frame.rowconfigure(3, weight=1); frame.columnconfigure(0, weight=1)

    def _notlar_olustur(self):
        frame = ttk.LabelFrame(self.icerik, text="NOTLAR VE TOPLAMLAR", padding=8); frame.pack(fill="x", pady=6)
        ttk.Label(frame, text="Genel Açıklama").grid(row=0, column=0, padx=6, sticky="w")
        self.girdiler["aciklama"] = ttk.Entry(frame, width=50); self.girdiler["aciklama"].grid(row=1, column=0, padx=6, sticky="ew")
        ttk.Label(frame, text="Ayrıntılı Notlar").grid(row=0, column=1, padx=6, sticky="w")
        self.notlar = tk.Text(frame, height=3, width=50); self.notlar.grid(row=1, column=1, padx=6, sticky="ew")
        self.toplam = ttk.Label(frame, text="Ara Toplam: 0,00 TL | KDV Toplamı: 0,00 TL | Genel Toplam: 0,00 TL"); self.toplam.grid(row=2, column=0, columnspan=2, padx=6, pady=(8, 0), sticky="w"); frame.columnconfigure(0, weight=1); frame.columnconfigure(1, weight=1)

    def urun_arama_ac(self, _event):
        widget = self.focus_get(); query = widget.get().strip()
        if len(query) >= 3: ProductSelectionDialog(self, query, self.urun_secildi)

    def urun_secildi(self, values):
        for field, value in (("urun_kodu", values[0]), ("urun_adi", values[1]), ("birim", values[2] or "Adet"), ("birim_fiyat", values[4])):
            if field == "birim": self.satir_girdileri[field].set(value)
            else: self.satir_girdileri[field].delete(0, "end"); self.satir_girdileri[field].insert(0, value)

    def fiyat_secimi_ac(self, _event): PriceSelectionDialog(self, self.satir_girdileri["urun_kodu"].get()); return "break"

    def satir_ekle(self):
        veri = {field: widget.get().strip() for field, widget in self.satir_girdileri.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]: messagebox.showwarning("Eksik bilgi", "Ürün kodu ve ürün adı zorunludur.", parent=self); return
        try: decimal(veri["miktar"], "Miktar", Decimal("0.0001")); decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
        except ValueError as hata: messagebox.showerror("Geçersiz satır", str(hata), parent=self); return
        secim = self.satir_tablosu.selection(); veri["siparis_satiri_id"] = veri.get("siparis_satiri_id")
        if secim: self.satirlar[int(secim[0])] = veri
        else: self.satirlar.append(veri)
        self.satir_temizle(); self.satir_listesini_yenile()

    def satir_temizle(self):
        for widget in self.satir_girdileri.values(): widget.delete(0, "end")
        self.satir_girdileri["birim"].set("Adet"); self.satir_girdileri["kdv_orani"].insert(0, "20"); self.satir_tablosu.selection_remove(self.satir_tablosu.selection())

    def satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children(): self.satir_tablosu.delete(item)
        for index, veri in enumerate(self.satirlar):
            miktar = decimal(veri["miktar"], "Miktar"); fiyat = decimal(veri["birim_fiyat"], "Birim fiyat"); iskonto = decimal(veri.get("iskonto_orani", 0), "İskonto"); kdv = decimal(veri.get("kdv_orani", 0), "KDV"); net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100)); toplam = net * (Decimal(1) + kdv / Decimal(100)); fatura = decimal(veri.get("faturalanan_miktar", 0), "Faturalanan"); self.satir_tablosu.insert("", "end", iid=str(index), values=(veri["urun_kodu"], veri["urun_adi"], veri.get("aciklama", ""), miktar, veri["birim"], para_goster(fiyat), f"{iskonto}%", f"{kdv}%", para_goster(toplam), fatura, miktar - fatura))
        self.toplam_guncelle()

    def toplam_guncelle(self):
        ara = Decimal("0"); kdv_toplam = Decimal("0")
        for veri in self.satirlar:
            miktar = decimal(veri["miktar"], "Miktar"); fiyat = decimal(veri["birim_fiyat"], "Birim fiyat"); iskonto = decimal(veri.get("iskonto_orani", 0), "İskonto"); kdv = decimal(veri.get("kdv_orani", 0), "KDV"); net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100)); ara += net; kdv_toplam += net * kdv / Decimal(100)
        self.toplam.configure(text=f"Ara Toplam: {para_goster(ara)} | KDV Toplamı: {para_goster(kdv_toplam)} | Genel Toplam: {para_goster(ara + kdv_toplam)}")

    def satir_secildi(self, _event=None):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satir_temizle(); veri = self.satirlar[int(secim[0])]
            for field, widget in self.satir_girdileri.items():
                deger = str(veri.get(field, ""))
                if field == "birim":
                    if deger and deger not in BIRIM_SECENEKLERI: widget["values"] = BIRIM_SECENEKLERI + (deger,)
                    widget.set(deger or "Adet")
                else: widget.insert(0, deger)

    def satir_duzenle(self): self.satir_secildi()
    def satir_kaldir(self):
        secim = self.satir_tablosu.selection()
        if secim and messagebox.askyesno("Satır kaldır", "Seçili satır kaldırılsın mı?", parent=self): self.satirlar.pop(int(secim[0])); self.satir_listesini_yenile()

    def _siparisten_doldur(self, siparis):
        self.siparis_secimi.set(siparis.siparis_no); self.musteri.set(f"{siparis.cari.cari_kodu} - {siparis.cari.unvan}"); self.bakiye_guncelle()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.irsaliyelenen_miktar
            if acik > 0: self.satirlar.append({"siparis_satiri_id": satir.id, "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi, "aciklama": satir.aciklama or "", "miktar": acik, "birim": satir.birim, "birim_fiyat": satir.birim_satis_fiyati, "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani})
        self.satir_listesini_yenile()

    def siparisi_secildi(self):
        siparis = self.siparis_map.get(self.siparis_secimi.get())
        if siparis: self.satirlar.clear(); self._siparisten_doldur(siparis)

    def bakiye_guncelle(self):
        musteri = self.musteri_map.get(self.musteri.get()); bakiye = SatisIrsaliyesiService.mevcut_bakiye(musteri.id) if musteri else Decimal("0"); self.girdiler["bakiye"].configure(state="normal"); self.girdiler["bakiye"].delete(0, "end"); self.girdiler["bakiye"].insert(0, para_goster(bakiye)); self.girdiler["bakiye"].configure(state="readonly")

    def _doldur(self):
        self.musteri.set(f"{self.irsaliye.cari.cari_kodu} - {self.irsaliye.cari.unvan}"); self.bakiye_guncelle(); self.girdiler["irsaliye_tarihi"].delete(0, "end"); self.girdiler["irsaliye_tarihi"].insert(0, tarih_goster(self.irsaliye.irsaliye_tarihi)); self.siparis_secimi.set(self.irsaliye.siparis.siparis_no if self.irsaliye.siparis else "")
        self.girdiler["aciklama"].insert(0, self.irsaliye.aciklama or ""); self.notlar.insert("1.0", self.irsaliye.ayrintili_notlar or "")
        for satir in self.irsaliye.satirlar: self.satirlar.append({"siparis_satiri_id": satir.siparis_satiri_id, "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi, "aciklama": satir.aciklama or "", "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat, "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani, "faturalanan_miktar": satir.faturalanan_miktar})
        self.satir_listesini_yenile()

    def kaydet(self):
        try: tarih = datetime.strptime(self.girdiler["irsaliye_tarihi"].get(), "%d.%m.%Y").date(); musteri = self.musteri_map.get(self.musteri.get())
        except ValueError as hata: messagebox.showerror("Geçersiz tarih", str(hata), parent=self); return
        if not musteri: messagebox.showwarning("Eksik bilgi", "Müşteri seçin.", parent=self); return
        try: SatisIrsaliyesiService.kaydet({"irsaliye_tarihi": tarih, "cari_id": musteri.id, "siparis_id": self.siparis_map.get(self.siparis_secimi.get()).id if self.siparis_secimi.get() else None, "aciklama": self.girdiler.get("aciklama", ""), "ayrintili_notlar": self.notlar.get("1.0", "end").strip()}, self.satirlar, self.irsaliye.id if self.irsaliye else None)
        except ValueError as hata: messagebox.showerror("İrsaliye kaydedilemedi", str(hata), parent=self); return
        self.result = True; self.destroy()

    def iptal_et(self):
        if self.irsaliye and messagebox.askyesno("İrsaliyeyi iptal et", "İrsaliye iptal edilsin mi?", parent=self):
            try: SatisIrsaliyesiService.iptal_et(self.irsaliye.id)
            except ValueError as hata: messagebox.showerror("İşlem yapılamadı", str(hata), parent=self); return
            self.result = True; self.destroy()


class SatisSiparisiDialog(tk.Toplevel):
    def __init__(self, parent, siparis=None, cari=None):
        super().__init__(parent)
        self.siparis = siparis
        self.baslangic_cari = cari
        self.result = None
        self.title("Sipariş Kartı")
        self.geometry("1200x760")
        self.minsize(950, 620)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.tahsilatlar = []
        self.mevcut_borc = Decimal("0")
        self.yontem = tk.StringVar(value=self.siparis.maliyet_yontemi if self.siparis else MALIYET_YONTEMLERI[0])
        self.musteriler = SatisSiparisiService.aktif_musterileri()
        if siparis and siparis.cari and siparis.cari not in self.musteriler:
            self.musteriler.append(siparis.cari)
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self.girdiler = {}
        kaydirma_alani = ttk.Frame(self, padding=10)
        kaydirma_alani.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(kaydirma_alani, highlightthickness=0)
        dikey_kaydirma = ttk.Scrollbar(kaydirma_alani, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=dikey_kaydirma.set)
        dikey_kaydirma.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas, padding=8)
        pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(pencere, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        ttk.Label(self.icerik, text="SİPARİŞ BİLGİLERİ", style="Baslik.TLabel").pack(anchor="w", pady=(0, 6))
        genel = ttk.LabelFrame(self.icerik, text="Sipariş Bilgileri", padding=8)
        genel.pack(fill="x", pady=(0, 8))
        self._genel_olustur(genel)
        satir_sayfasi = ttk.LabelFrame(self.icerik, text="SİPARİŞ SATIRI GİRİŞİ VE SATIRLAR", padding=8)
        satir_sayfasi.pack(fill="both", expand=True, pady=4)
        self._satir_olustur(satir_sayfasi)
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=4)
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=1)
        alt.rowconfigure(0, weight=1)
        self._tahsilat_olustur(alt)
        self._notlar_olustur(alt)
        butonlar = ttk.Frame(self.icerik)
        butonlar.pack(fill="x", pady=(12, 4))
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(butonlar, text="Siparişi İptal Et", command=self.siparisi_iptal_et).pack(side="right", padx=8)
        ttk.Button(butonlar, text="Siparişi Kaydet", command=self.kaydet).pack(side="right", padx=8)
        if siparis:
            self._doldur()
        elif cari:
            musteri_anahtari = f"{cari.cari_kodu} - {cari.unvan}"
            if musteri_anahtari in self.musteri_map:
                self.musteri.set(musteri_anahtari)
                self._bakiye_guncelle()

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

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
        ttk.Label(parent, text="Sipariş Durumu").grid(row=6, column=0, padx=8, pady=5, sticky="w")
        self.durum = ttk.Combobox(parent, values=SIPARIS_DURUMLARI, state="readonly", width=33)
        self.durum.grid(row=6, column=1, padx=8, pady=5, sticky="ew")
        self.durum.set(self.siparis.durum if self.siparis else "AÇIK")
        parent.columnconfigure(1, weight=1)

    def _satir_olustur(self, parent):
        self.satir_girdileri = {}
        giris = ttk.LabelFrame(parent, text="Sipariş Satırı", padding=8)
        giris.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        alanlar = (("Ürün Kodu", "urun_kodu"), ("Ürün Adı", "urun_adi"), ("Açıklama", "aciklama"), ("Miktar", "miktar"), ("Birim", "birim"), ("Birim Satış Fiyatı", "birim_satis_fiyati"), ("İskonto %", "iskonto_orani"), ("KDV %", "kdv_orani"))
        for sutun, (baslik, alan) in enumerate(alanlar):
            giris.columnconfigure(sutun, weight={0: 1, 1: 3, 2: 2}.get(sutun, 0), minsize={0: 100, 1: 300, 2: 200}.get(sutun, 0))
            ttk.Label(giris, text=baslik).grid(row=0, column=sutun, padx=3, pady=3, sticky="w")
            widget = ttk.Combobox(giris, values=BIRIM_SECENEKLERI, state="readonly", width=10) if alan == "birim" else ttk.Entry(giris, width={0: 12, 1: 36, 2: 24}.get(sutun, 10))
            widget.grid(row=1, column=sutun, padx=3, pady=3, sticky="ew")
            self.satir_girdileri[alan] = widget
            if alan in ("urun_kodu", "urun_adi"):
                widget.bind("<KeyRelease>", self.satir_urun_arama_ac)
            if alan == "birim_satis_fiyati":
                widget.bind("<F10>", self.satir_fiyat_secimi_ac)
            if alan in ("miktar", "birim_satis_fiyati", "iskonto_orani"):
                widget.bind("<KeyRelease>", lambda _event: self.satir_tutar_guncelle())
        self.satir_girdileri["birim"].set("Adet")
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        butonlar = ttk.Frame(giris)
        butonlar.grid(row=2, column=0, columnspan=len(alanlar), sticky="w", pady=(5, 0))
        ttk.Button(butonlar, text="Ekle/Güncelle", command=self.satir_kaydet).pack(side="left")
        ttk.Button(butonlar, text="Temizle", command=self.satir_formunu_temizle).pack(side="left", padx=8)
        self.satir_tutar = ttk.Label(butonlar, text="Tutar: 0,00 TL", font=("Segoe UI", 10, "bold"))
        self.satir_tutar.pack(side="left", padx=12)

        kolonlar = ("urun_kodu", "urun_adi", "aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv", "toplam", "irsaliye", "fatura", "acik")
        self.satir_tablosu = ttk.Treeview(parent, columns=kolonlar, show="headings")
        basliklar = {"urun_kodu": "Ürün Kodu", "urun_adi": "Ürün Adı", "aciklama": "Açıklama", "miktar": "Miktar", "birim": "Birim", "fiyat": "Birim Fiyat", "iskonto": "İskonto", "kdv": "KDV", "toplam": "Satır Toplamı", "irsaliye": "İrsaliyelenen Miktar", "fatura": "Faturalanan Miktar", "acik": "Açık Sipariş Miktarı"}
        kolon_genislikleri = {"urun_kodu": 100, "urun_adi": 300, "aciklama": 200, "miktar": 75, "birim": 65, "fiyat": 110, "iskonto": 75, "kdv": 65, "toplam": 120, "irsaliye": 135, "fatura": 135, "acik": 135}
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            self.satir_tablosu.column(kolon, width=kolon_genislikleri[kolon], minwidth=220 if kolon == "urun_adi" else kolon_genislikleri[kolon], stretch=kolon == "urun_adi", anchor="w")
        dikey = ttk.Scrollbar(parent, orient="vertical", command=self.satir_tablosu.yview)
        yatay = ttk.Scrollbar(parent, orient="horizontal", command=self.satir_tablosu.xview)
        self.satir_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.satir_tablosu.grid(row=1, column=0, sticky="nsew")
        dikey.grid(row=1, column=1, sticky="ns")
        yatay.grid(row=2, column=0, sticky="ew")
        parent.rowconfigure(1, weight=1); parent.columnconfigure(0, weight=1)
        self.satir_tablosu.bind("<<TreeviewSelect>>", self.satir_secildi)
        toplamlar = ttk.LabelFrame(parent, text="TOPLAMLAR", padding=6)
        toplamlar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        toplamlar.columnconfigure(0, weight=1)
        self.satir_ozet = ttk.Label(toplamlar, text="Ara Toplam: 0,00 TL | KDV: 0,00 TL | Genel Toplam: 0,00 TL", wraplength=900)
        self.satir_ozet.grid(row=0, column=0, sticky="w")
        ttk.Button(toplamlar, text="KÂRLILIK ANALİZİ", command=self.karlilik_analizi_ac).grid(row=0, column=1, padx=8, sticky="e")

    def _notlar_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="NOTLAR", padding=8)
        cerceve.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(cerceve, text="Genel Açıklama").pack(anchor="w")
        self.girdiler["aciklama"] = ttk.Entry(cerceve)
        self.girdiler["aciklama"].pack(fill="x", pady=(2, 8))
        ttk.Label(cerceve, text="Ayrıntılı Notlar").pack(anchor="w")
        self.ayrintili_notlar = tk.Text(cerceve, height=6, width=45)
        self.ayrintili_notlar.pack(fill="both", expand=True, pady=(2, 0))

    def satir_urun_arama_ac(self, _event):
        widget = self.focus_get()
        sorgu = widget.get().strip() if widget in (self.satir_girdileri["urun_kodu"], self.satir_girdileri["urun_adi"]) else ""
        if len(sorgu) >= 3:
            ProductSelectionDialog(self, sorgu, self.satir_urun_secildi)

    def satir_urun_secildi(self, degerler):
        for alan, deger in (("urun_kodu", degerler[0]), ("urun_adi", degerler[1]), ("birim", degerler[2] or "Adet"), ("birim_satis_fiyati", degerler[4])):
            if alan == "birim":
                self.satir_girdileri[alan].set(deger)
            else:
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, deger)
        self.satir_tutar_guncelle()

    def satir_fiyat_secimi_ac(self, _event):
        PriceSelectionDialog(self, self.satir_girdileri["urun_kodu"].get().strip())
        return "break"

    def satir_tutar_guncelle(self):
        try:
            miktar = decimal(self.satir_girdileri["miktar"].get() or 0, "Miktar")
            fiyat = decimal(self.satir_girdileri["birim_satis_fiyati"].get() or 0, "Birim fiyat")
            iskonto = decimal(self.satir_girdileri["iskonto_orani"].get() or 0, "İskonto")
            self.satir_tutar.configure(text=f"Tutar: {para_goster(miktar * fiyat * (Decimal(1) - iskonto / Decimal(100)))}")
        except ValueError:
            self.satir_tutar.configure(text="Tutar: 0,00 TL")

    def satir_formunu_temizle(self):
        for alan, widget in self.satir_girdileri.items():
            widget.delete(0, "end")
        self.satir_girdileri["birim"].set("Adet")
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        self.satir_tutar_guncelle()
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())

    def satir_formunu_doldur(self, veri):
        self.satir_formunu_temizle()
        for alan, widget in self.satir_girdileri.items():
            deger = veri.get(alan, "")
            widget.delete(0, "end")
            if alan == "birim":
                if deger and deger not in BIRIM_SECENEKLERI:
                    widget["values"] = BIRIM_SECENEKLERI + (str(deger),)
                widget.set(deger or "Adet")
            else:
                widget.insert(0, "" if deger is None else str(deger))
        self.satir_tutar_guncelle()

    def satir_secildi(self, _event=None):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satir_formunu_doldur(self.satirlar[int(secim[0])])

    def satir_kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.satir_girdileri.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]:
            messagebox.showwarning("Eksik bilgi", "Ürün kodu ve ürün adı zorunludur.", parent=self)
            return
        try:
            for alan in ("miktar", "birim_satis_fiyati", "iskonto_orani", "kdv_orani"):
                decimal(veri[alan] or 0, alan, Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        secim = self.satir_tablosu.selection()
        if secim:
            mevcut_veri = self.satirlar[int(secim[0])]
            for alan in ("fifo_birim_maliyeti", "son_alis_birim_maliyeti", "ortalama_birim_maliyeti", "agirlikli_ortalama_birim_maliyeti", "siparis_satiri_id", "irsaliye_satiri_id", "irsaliyelenen_miktar", "faturalanan_miktar"):
                veri[alan] = mevcut_veri.get(alan, "0")
            self.satirlar[int(secim[0])] = veri
        else:
            for alan in ("fifo_birim_maliyeti", "son_alis_birim_maliyeti", "ortalama_birim_maliyeti", "agirlikli_ortalama_birim_maliyeti"):
                veri[alan] = "0"
            self.satirlar.append(veri)
        self.satir_formunu_temizle()
        self._satir_listesini_yenile()

    def _tahsilat_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="TAHSİLATLAR", padding=8)
        cerceve.grid(row=0, column=0, sticky="nsew")
        kolonlar = ("tarih", "tutar", "sekil", "hesap", "aciklama")
        self.tahsilat_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=6)
        for kolon, baslik in zip(kolonlar, ("Tarih", "Tutar", "Ödeme Şekli", "Hesap", "Açıklama")):
            self.tahsilat_tablosu.heading(kolon, text=baslik); self.tahsilat_tablosu.column(kolon, width=160)
        self.tahsilat_tablosu.pack(fill="both", expand=True)
        alt = ttk.Frame(cerceve); alt.pack(fill="x", pady=8)
        ttk.Button(alt, text="Tahsilat Ekle", command=self.tahsilat_ekle).pack(side="left")
        ttk.Button(alt, text="Tahsilat Düzenle", command=self.tahsilat_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Tahsilat Kaldır", command=self.tahsilat_kaldir).pack(side="left")
        self.tahsilat_ozet = ttk.Label(cerceve, text="Tahsil Edilen: 0,00 TL | Kalan Tahsilat: 0,00 TL")
        self.tahsilat_ozet.pack(anchor="w")

    def _doldur(self):
        musteri = next((m for m in self.musteriler if m.id == self.siparis.cari_id), None)
        if musteri: self.musteri.set(f"{musteri.cari_kodu} - {musteri.unvan}")
        self.yontem.set(self.siparis.maliyet_yontemi); self.durum.set(self.siparis.durum)
        self.hedef_kar_marji.set(str(self.siparis.hedef_kar_marji))
        self.girdiler["aciklama"].delete(0, "end"); self.girdiler["aciklama"].insert(0, self.siparis.aciklama or "")
        maliyet_alanlari = {"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}
        for satir in self.siparis.satirlar:
            veri = {alan: getattr(satir, alan) for _, alan in SiparisSatiriDialog.alanlar}
            veri["siparis_satiri_id"] = satir.id
            veri["birim_maliyet"] = getattr(satir, maliyet_alanlari[self.siparis.maliyet_yontemi])
            veri["irsaliyelenen_miktar"] = satir.irsaliyelenen_miktar
            veri["faturalanan_miktar"] = satir.faturalanan_miktar
            self.satirlar.append(veri)
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
            irsaliye = decimal(veri.get("irsaliyelenen_miktar", 0), "İrsaliyelenen miktar")
            fatura = decimal(veri.get("faturalanan_miktar", 0), "Faturalanan miktar")
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(veri["urun_kodu"], veri["urun_adi"], veri.get("aciklama", ""), veri["miktar"], veri["birim"], para_goster(veri["birim_satis_fiyati"]), f"{veri.get('iskonto_orani', 0)}%", f"{veri.get('kdv_orani', 0)}%", para_goster(net), para_goster(net + kdv), irsaliye, fatura, acik - irsaliye))
        self._toplamlari_guncelle()

    def karlilik_analizi_ac(self):
        KarlilikAnaliziDialog(self)

    def _toplamlari_guncelle(self, borc=None):
        toplam = {"ara_toplam": Decimal("0"), "iskonto": Decimal("0"), "net": Decimal("0"), "kdv": Decimal("0"), "genel": Decimal("0"), "maliyet": Decimal("0"), "kar": Decimal("0")}
        for veri in self.satirlar:
            brut, indirim, net, kdv, maliyet, kar, _ = self._satir_hesapla(veri)
            toplam["ara_toplam"] += brut; toplam["iskonto"] += indirim; toplam["net"] += net; toplam["kdv"] += kdv; toplam["maliyet"] += maliyet; toplam["kar"] += kar
        toplam["genel"] = toplam["net"] + toplam["kdv"]; marj = toplam["kar"] / toplam["net"] * 100 if toplam["net"] else Decimal("0")
        tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0")); kalan = toplam["genel"] - tahsilat
        tahmini_bakiye = self.mevcut_borc + toplam["genel"] - tahsilat
        self.satir_ozet.configure(text=f"Ara Toplam: {para_goster(toplam['ara_toplam'])} | KDV Toplamı: {para_goster(toplam['kdv'])} | Genel Toplam: {para_goster(toplam['genel'])}")
        self.tahsilat_ozet.configure(text=f"Tahsil Edilen: {para_goster(tahsilat)} | Kalan Tahsilat: {para_goster(kalan)}")
        if borc is not None: self._readonly_yaz("tahmini_bakiye", para_goster(tahmini_bakiye))

    def _onerilen_fiyat(self, veri):
        maliyet_alanlari = {"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}
        maliyet = decimal(veri.get(maliyet_alanlari[self.yontem.get()], 0), "Maliyet")
        hedef = decimal(self.hedef_kar_marji.get() or 0, "Hedef kâr marjı")
        return maliyet / (Decimal("1") - hedef / Decimal("100")) if hedef < Decimal("100") else Decimal("0")

    def satir_ekle(self):
        self.satir_formunu_temizle()

    def satir_duzenle(self):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satir_formunu_doldur(self.satirlar[int(secim[0])])

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
            ayrintili = self.ayrintili_notlar.get("1.0", "end").strip()
            aciklama = self.girdiler["aciklama"].get().strip()
            if ayrintili:
                aciklama = f"{aciklama}\n{ayrintili}".strip()
            veriler = {"siparis_tarihi": datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date(), "termin_tarihi": datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date(), "cari_id": musteri.id, "maliyet_yontemi": self.yontem.get(), "hedef_kar_marji": self.hedef_kar_marji.get(), "aciklama": aciklama}
            if not self.satirlar: raise ValueError("En az bir sipariş satırı ekleyin.")
            SatisSiparisiService.kaydet(veriler, self.satirlar, self.tahsilatlar, self.siparis.id if self.siparis else None)
        except ValueError as hata: messagebox.showerror("Sipariş kaydedilemedi", str(hata), parent=self); return
        self.result = True; self.destroy()

    def siparisi_iptal_et(self):
        if self.siparis is None:
            self.destroy()
            return
        if messagebox.askyesno("Siparişi iptal et", "Bu sipariş iptal edilsin mi?", parent=self):
            try:
                SatisSiparisiService.iptal_et(self.siparis.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
                return
            self.result = True
            self.destroy()


class SatisFaturasiDialog(SatisSiparisiDialog):
    """Sipariş kartının tek sayfalık düzenini kullanan satış faturası kartı."""

    def __init__(self, parent, fatura=None, cari=None, siparis=None, irsaliye=None, cari_ac=None):
        self._fatura_satirlari_hazir = False
        self.fatura = fatura
        self.kaynak_siparis = siparis
        self.kaynak_irsaliye = irsaliye
        self.cari_ac = cari_ac
        baslangic_cari = fatura.cari if fatura else irsaliye.cari if irsaliye else cari
        super().__init__(parent, siparis=siparis, cari=baslangic_cari)
        self.siparis = None
        self.title("Fatura Kartı")
        self._metinleri_faturaya_cevir(self)
        self.satir_tablosu.heading("irsaliye", text="Siparişten Gelen")
        self.satir_tablosu.heading("fatura", text="İrsaliyeden Gelen")
        self.satir_tablosu.heading("acik", text="Fatura Miktarı")
        self.durum.configure(values=("AÇIK", "KAPALI", "İPTAL"))
        self.durum.set(fatura.durum if fatura else "AÇIK")
        self._ek_fatura_bilgileri()
        self._fatura_satir_baglantilari()
        self._fatura_satirlari_hazir = True
        if fatura:
            self._faturayi_doldur()
        elif irsaliye:
            self._irsaliyeyi_doldur(irsaliye)
        elif siparis:
            self._satirlari_stokla_tamamla()
            self._satir_listesini_yenile()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()

    def _metinleri_faturaya_cevir(self, parent):
        for widget in parent.winfo_children():
            try:
                metin = widget.cget("text")
                yeni = (metin.replace("SİPARİŞ", "FATURA").replace("Sipariş", "Fatura")
                        .replace("sipariş", "fatura").replace("Termin", "Vade"))
                if yeni != metin:
                    widget.configure(text=yeni)
            except tk.TclError:
                pass
            self._metinleri_faturaya_cevir(widget)

    def _ek_fatura_bilgileri(self):
        ek = ttk.LabelFrame(self.icerik, text="FATURA BAĞLANTI BİLGİLERİ", padding=8)
        ek.pack(fill="x", pady=4, before=self.icerik.winfo_children()[-1])
        ttk.Label(ek, text="Sipariş No").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.siparis_no = ttk.Entry(ek, width=28)
        self.siparis_no.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        ttk.Label(ek, text="İrsaliye No").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.irsaliye_no = ttk.Entry(ek, width=28)
        self.irsaliye_no.grid(row=0, column=3, padx=6, pady=4, sticky="ew")
        ttk.Label(ek, text="Depo").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self.depo = ttk.Combobox(ek, values=tuple(d.ad for d in StokService.depolar()), state="readonly", width=26)
        self.depo.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        self.depo.set("ANA DEPO")
        self.depo.bind("<<ComboboxSelected>>", self.depo_degisti)
        ttk.Button(ek, text="Yeni Depo", command=self.depo_ekle).grid(row=1, column=2, padx=6, sticky="w")
        ttk.Label(ek, text="Doküman").grid(row=1, column=3, padx=6, pady=4, sticky="w")
        self.dokuman = ttk.Entry(ek, width=28)
        self.dokuman.grid(row=1, column=4, padx=6, pady=4, sticky="ew")
        ttk.Button(ek, text="Doküman Seç", command=self.dokuman_sec).grid(row=1, column=5, padx=6)
        ttk.Button(ek, text="Cari Kartına Geç", command=self.cariye_git).grid(row=0, column=4, padx=6)
        ttk.Label(ek, text="Fatura Vadesi (Gün)").grid(row=2, column=0, padx=6, pady=4, sticky="w")
        self.vade_gunu = ttk.Entry(ek, width=12)
        self.vade_gunu.grid(row=2, column=1, padx=6, pady=4, sticky="w")
        self.vade_gunu.insert(0, str(self.fatura.vade_gunu if self.fatura else 0))
        self.vade_gunu.bind("<KeyRelease>", self.vade_gun_degisti)
        self.girdiler["termin_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.ortalama_vade_etiket = ttk.Label(ek, text="Bu fatura ile yeni ağırlıklı ortalama vade: -", foreground="#1f6aa5", font=("Segoe UI", 10, "bold"))
        self.ortalama_vade_etiket.grid(row=2, column=2, columnspan=4, padx=6, pady=4, sticky="w")
        for sutun in (1, 4):
            ek.columnconfigure(sutun, weight=1)
        self.girdiler["siparis_no"] = self.siparis_no
        self.girdiler["irsaliye_no"] = self.irsaliye_no
        self.girdiler["depo"] = self.depo
        self.girdiler["dokuman"] = self.dokuman
        if self.kaynak_siparis:
            self.siparis_no.insert(0, self.kaynak_siparis.siparis_no)
        if self.kaynak_irsaliye:
            self.irsaliye_no.insert(0, self.kaynak_irsaliye.irsaliye_no)
            if self.kaynak_irsaliye.siparis:
                self.siparis_no.delete(0, "end")
                self.siparis_no.insert(0, self.kaynak_irsaliye.siparis.siparis_no)

    def _fatura_satir_baglantilari(self):
        butonlar = self.satir_tutar.master
        ttk.Button(butonlar, text="STOK LİSTESİ", command=self.stok_listesi_ac).pack(side="left", padx=6)
        ttk.Label(butonlar, text="Barkod:").pack(side="left", padx=(12, 2))
        self.satir_girdileri["barkod"] = ttk.Entry(butonlar, width=15)
        self.satir_girdileri["barkod"].pack(side="left")
        ttk.Label(butonlar, text="Lot:").pack(side="left", padx=(8, 2))
        self.satir_girdileri["lot_no"] = ttk.Combobox(butonlar, width=18)
        self.satir_girdileri["lot_no"].pack(side="left")
        ttk.Label(butonlar, text="Lot Çıkışı:").pack(side="left", padx=(8, 2))
        self.satir_girdileri["lot_cikisi"] = ttk.Entry(butonlar, width=22)
        self.satir_girdileri["lot_cikisi"].pack(side="left")
        fiyat = self.satir_girdileri["birim_satis_fiyati"]
        fiyat.bind("<KeyPress-y>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<KeyPress-Y>", self.fatura_fiyat_secimi_ac)
        kolonlar = ("barkod", "urun_kodu", "urun_adi", "aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv", "lot", "lot_cikisi", "toplam", "irsaliye", "fatura", "acik")
        self.satir_tablosu.configure(columns=kolonlar)
        basliklar = {
            "barkod":"Barkod", "urun_kodu":"Ürün Kodu", "urun_adi":"Ürün Adı", "aciklama":"Açıklama",
            "miktar":"Miktar", "birim":"Birim", "fiyat":"Birim Fiyat", "iskonto":"İskonto",
            "kdv":"KDV", "lot":"Lot No", "lot_cikisi":"Lot Çıkışı", "toplam":"Satır Toplamı",
            "irsaliye":"Siparişten Gelen", "fatura":"İrsaliyeden Gelen", "acik":"Fatura Miktarı",
        }
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            self.satir_tablosu.column(kolon, width=105, anchor="w")
        self.satir_tablosu.column("urun_adi", width=260)

    def depo_ekle(self):
        ad = simpledialog.askstring("Yeni Depo", "Depo adı:", parent=self)
        if not ad: return
        try: depo = StokService.depo_ekle(ad)
        except ValueError as hata: messagebox.showerror("Depo eklenemedi", str(hata), parent=self); return
        self.depo["values"] = tuple(d.ad for d in StokService.depolar())
        self.depo.set(depo.ad)
        self.depo_degisti()

    def depo_degisti(self, _event=None):
        for veri in self.satirlar:
            veri["lot_no"] = ""
            veri["lot_cikisi"] = ""
        self._satirlari_stokla_tamamla()
        self.lotlari_yukle()
        self._satir_listesini_yenile()

    def vade_gun_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = fatura_tarihi + timedelta(days=int(self.vade_gunu.get() or 0))
        except (ValueError, TypeError):
            return
        self._entry_yaz("termin_tarihi", tarih_goster(vade_tarihi))
        self._toplamlari_guncelle()

    def vade_tarih_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            return
        self.vade_gunu.delete(0, "end")
        self.vade_gunu.insert(0, str((vade_tarihi - fatura_tarihi).days))
        self._toplamlari_guncelle()

    def dokuman_sec(self):
        yol = filedialog.askopenfilename(parent=self, title="Faturaya doküman ekle")
        if yol:
            self.dokuman.delete(0, "end")
            self.dokuman.insert(0, yol)

    def cariye_git(self):
        cari = self.musteri_map.get(self.musteri.get())
        if cari and self.cari_ac:
            self.cari_ac(cari)

    def stok_listesi_ac(self):
        sorgu = self.satir_girdileri["urun_adi"].get().strip() or self.satir_girdileri["urun_kodu"].get().strip()
        ProductSelectionDialog(self, sorgu, self.satir_urun_secildi)

    def satir_urun_secildi(self, degerler):
        super().satir_urun_secildi(degerler)
        self.satir_girdileri["barkod"].delete(0, "end")
        bulunan = StokService.stoklari_ara(degerler[0])
        stok = next((s for s in bulunan if s.stok_kodu == degerler[0]), None)
        if stok and stok.barkod:
            self.satir_girdileri["barkod"].insert(0, stok.barkod)
        self.lotlari_yukle()

    def lotlari_yukle(self):
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        lotlar = StokService.lotlar(kod, self.depo.get()) if kod and self.depo.get() else []
        self.satir_girdileri["lot_no"]["values"] = tuple(lot.lot_no for lot in lotlar)
        if lotlar:
            self.satir_girdileri["lot_no"].set(lotlar[0].lot_no)
            self.satir_girdileri["lot_cikisi"].delete(0, "end")
            self.satir_girdileri["lot_cikisi"].insert(0, lotlar[0].lot_no)
        maliyetler = StokService.maliyetler(kod, self.depo.get()) if kod and self.depo.get() else {}
        for alan, anahtar in (("fifo_birim_maliyeti", "fifo"), ("son_alis_birim_maliyeti", "son_alis"),
                              ("ortalama_birim_maliyeti", "ortalama"),
                              ("agirlikli_ortalama_birim_maliyeti", "agirlikli")):
            if alan in self.satir_girdileri:
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, str(maliyetler.get(anahtar, 0)))

    def _satirlari_stokla_tamamla(self):
        for veri in self.satirlar:
            bulunan = next((s for s in StokService.stoklari_ara(veri.get("urun_kodu", ""))
                            if s.stok_kodu == veri.get("urun_kodu")), None)
            if bulunan:
                veri["barkod"] = veri.get("barkod") or bulunan.barkod or ""
            lotlar = StokService.lotlar(veri.get("urun_kodu", ""), self.depo.get())
            if lotlar and not veri.get("lot_no"):
                veri["lot_no"] = lotlar[0].lot_no
                veri["lot_cikisi"] = lotlar[0].lot_no
            maliyetler = StokService.maliyetler(veri.get("urun_kodu", ""), self.depo.get())
            veri["fifo_birim_maliyeti"] = maliyetler["fifo"]
            veri["son_alis_birim_maliyeti"] = maliyetler["son_alis"]
            veri["ortalama_birim_maliyeti"] = maliyetler["ortalama"]
            veri["agirlikli_ortalama_birim_maliyeti"] = maliyetler["agirlikli"]

    def fatura_fiyat_secimi_ac(self, _event=None):
        PriceSelectionDialog(
            self, self.satir_girdileri["urun_kodu"].get().strip(), self.fatura_fiyati_secildi
        )
        return "break"

    def fatura_fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_satis_fiyati"]
        alan.delete(0, "end"); alan.insert(0, str(fiyat.tutar))
        self.satir_tutar_guncelle()

    def satir_kaydet(self):
        super().satir_kaydet()
        self._satirlari_stokla_tamamla()
        self._satir_listesini_yenile()

    def _satir_listesini_yenile(self):
        if not hasattr(self, "satir_tablosu"):
            return
        if not self._fatura_satirlari_hazir:
            return SatisSiparisiDialog._satir_listesini_yenile(self)
        for item in self.satir_tablosu.get_children(): self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            _, _, net, kdv, _, _, _ = self._satir_hesapla(veri)
            miktar = decimal(veri.get("miktar", 0), "Miktar")
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                veri.get("barkod", ""), veri["urun_kodu"], veri["urun_adi"], veri.get("aciklama", ""),
                miktar, veri["birim"], para_goster(veri["birim_satis_fiyati"]),
                f"{veri.get('iskonto_orani', 0)}%", f"{veri.get('kdv_orani', 0)}%",
                veri.get("lot_no", ""), veri.get("lot_cikisi", ""), para_goster(net + kdv),
                veri.get("irsaliyelenen_miktar", 0), veri.get("faturalanan_miktar", 0), miktar,
            ))
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self, borc=None):
        super()._toplamlari_guncelle(borc)
        if not hasattr(self, "ortalama_vade_etiket"):
            return
        cari = self.musteri_map.get(self.musteri.get())
        if not cari:
            self.ortalama_vade_etiket.configure(text="Bu fatura ile yeni ağırlıklı ortalama vade: -")
            return
        try: vade = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError: vade = date.today()
        toplam = Decimal("0")
        for veri in self.satirlar:
            _, _, net, kdv, _, _, _ = self._satir_hesapla(veri); toplam += net + kdv
        tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0"))
        acik = max(Decimal("0"), toplam - tahsilat)
        ozet = SatisFaturasiService.bakiye_ozeti(
            cari.id, acik, vade, self.fatura.fatura_no if self.fatura else None
        )
        self.ortalama_vade_etiket.configure(
            text=f"Bu fatura ile yeni bakiye: {para_goster(ozet['bakiye'])} | "
                 f"Yeni ağırlıklı ortalama vade: {tarih_goster(ozet['ortalama_vade']) if ozet['ortalama_vade'] else '-'}"
        )

    def _irsaliyeyi_doldur(self, irsaliye):
        self.satirlar.clear()
        self.musteri.set(f"{irsaliye.cari.cari_kodu} - {irsaliye.cari.unvan}")
        for satir in irsaliye.satirlar:
            kalan = satir.miktar - satir.faturalanan_miktar
            if kalan <= 0:
                continue
            self.satirlar.append({
                "irsaliye_satiri_id": satir.id,
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": satir.aciklama or "",
                "miktar": kalan,
                "birim": satir.birim,
                "birim_satis_fiyati": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
                "fifo_birim_maliyeti": 0,
                "son_alis_birim_maliyeti": 0,
                "ortalama_birim_maliyeti": 0,
                "agirlikli_ortalama_birim_maliyeti": 0,
                "lot_no": "",
                "lot_cikisi": "",
                "irsaliyelenen_miktar": kalan,
                "faturalanan_miktar": 0,
            })
        self._satirlari_stokla_tamamla()
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _faturayi_doldur(self):
        self.satirlar.clear()
        fatura = self.fatura
        self.musteri.set(f"{fatura.cari.cari_kodu} - {fatura.cari.unvan}")
        self._entry_yaz("siparis_tarihi", tarih_goster(fatura.fatura_tarihi))
        self._entry_yaz("termin_tarihi", tarih_goster(fatura.vade_tarihi))
        self._entry_yaz("aciklama", fatura.aciklama or "")
        self.siparis_no.insert(0, fatura.siparis.siparis_no if fatura.siparis else "")
        self.irsaliye_no.insert(0, fatura.irsaliye.irsaliye_no if fatura.irsaliye else "")
        self.depo.set(fatura.depo)
        self.dokuman.insert(0, fatura.dokuman_yolu or "")
        for satir in fatura.satirlar:
            self.satirlar.append({
                "irsaliye_satiri_id": satir.irsaliye_satiri_id,
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": satir.barkod or "",
                "aciklama": satir.aciklama or "",
                "miktar": satir.miktar,
                "birim": satir.birim,
                "birim_satis_fiyati": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
                "fifo_birim_maliyeti": satir.fifo_birim_maliyeti,
                "son_alis_birim_maliyeti": satir.son_alis_birim_maliyeti,
                "ortalama_birim_maliyeti": satir.ortalama_birim_maliyeti,
                "agirlikli_ortalama_birim_maliyeti": satir.agirlikli_ortalama_birim_maliyeti,
                "lot_no": satir.lot_no or "",
                "lot_cikisi": satir.lot_cikisi or "",
                "irsaliyelenen_miktar": satir.miktar if satir.irsaliye_satiri_id else 0,
                "faturalanan_miktar": satir.miktar,
            })
        if fatura.tahsilat_tutari:
            self.tahsilatlar[:] = [{
                "tahsilat_tarihi": fatura.fatura_tarihi,
                "tutar": fatura.tahsilat_tutari,
                "odeme_sekli": fatura.tahsilat_sekli or ODEME_SEKILLERI[0],
                "hesap": fatura.tahsilat_hesabi or "",
                "aciklama": "Fatura tahsilatı",
            }]
        self._bakiye_guncelle()
        self._satir_listesini_yenile()
        self._tahsilat_listesini_yenile()

    def _entry_yaz(self, alan, deger):
        self.girdiler[alan].delete(0, "end")
        self.girdiler[alan].insert(0, deger)

    def kaydet(self):
        try:
            musteri = self.musteri_map.get(self.musteri.get())
            if not musteri:
                raise ValueError("Aktif bir müşteri seçin.")
            fatura_tarihi = datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
            satirlar = []
            for satir in self.satirlar:
                veri = dict(satir)
                veri["birim_fiyat"] = veri.get("birim_satis_fiyati", 0)
                satirlar.append(veri)
            tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0"))
            ilk_tahsilat = self.tahsilatlar[0] if self.tahsilatlar else {}
            siparis_id = self.kaynak_siparis.id if self.kaynak_siparis else (self.fatura.siparis_id if self.fatura else None)
            irsaliye_id = self.kaynak_irsaliye.id if self.kaynak_irsaliye else (self.fatura.irsaliye_id if self.fatura else None)
            yazilan_siparis = self.siparis_no.get().strip()
            yazilan_irsaliye = self.irsaliye_no.get().strip()
            if yazilan_siparis and not siparis_id:
                eslesen = next((s for s in SatisFaturasiService.acik_siparisler() if s.siparis_no == yazilan_siparis), None)
                if not eslesen:
                    raise ValueError("Yazılan sipariş numarası bulunamadı.")
                if eslesen.cari_id != musteri.id:
                    raise ValueError("Sipariş numarası seçilen müşteriye ait değil.")
                siparis_id = eslesen.id
            if yazilan_irsaliye and not irsaliye_id:
                eslesen = next((i for i in SatisFaturasiService.acik_irsaliyeler() if i.irsaliye_no == yazilan_irsaliye), None)
                if not eslesen:
                    raise ValueError("Yazılan irsaliye numarası bulunamadı.")
                if eslesen.cari_id != musteri.id:
                    raise ValueError("İrsaliye numarası seçilen müşteriye ait değil.")
                irsaliye_id = eslesen.id
            self.result = SatisFaturasiService.kaydet({
                "fatura_tarihi": fatura_tarihi,
                "vade_tarihi": vade_tarihi,
                "cari_id": musteri.id,
                "siparis_id": siparis_id,
                "irsaliye_id": irsaliye_id,
                "depo": self.depo.get(),
                "tahsilat_tutari": tahsilat,
                "tahsilat_sekli": ilk_tahsilat.get("odeme_sekli"),
                "tahsilat_hesabi": ilk_tahsilat.get("hesap"),
                "aciklama": self.girdiler["aciklama"].get().strip(),
                "dokuman_yolu": self.dokuman.get().strip(),
            }, satirlar, self.fatura.id if self.fatura else None)
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return
        self.destroy()

    def siparisi_iptal_et(self):
        if not self.fatura:
            self.destroy()
            return
        if messagebox.askyesno("Faturayı iptal et", "Bu fatura iptal edilsin mi?", parent=self):
            try:
                SatisFaturasiService.iptal_et(self.fatura.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
                return
            self.result = True
            self.destroy()


class StokKartiDialog(tk.Toplevel):
    FIYAT_ADLARI = ("PERAKENDE", "NAKİT", "AÇIK HESAP", "KREDİ KARTI")

    def __init__(self, parent, stok=None):
        super().__init__(parent)
        self.stok = stok
        self.result = None
        self.title("Stok Kartını Düzenle" if stok else "Yeni Stok Kartı")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.alanlar = {}
        for satir, (etiket, alan) in enumerate((("Stok Kodu", "stok_kodu"), ("Stok Adı", "stok_adi"), ("Barkod", "barkod"))):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            giris = ttk.Entry(self, width=38)
            giris.grid(row=satir, column=1, padx=12, pady=6)
            self.alanlar[alan] = giris
        ttk.Label(self, text="Birim").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.birim = ttk.Combobox(self, values=BIRIM_SECENEKLERI, state="readonly", width=35)
        self.birim.grid(row=3, column=1, padx=12, pady=6)
        self.birim.set("Adet")
        fiyat_cercevesi = ttk.LabelFrame(self, text="Satış Fiyatları", padding=8)
        fiyat_cercevesi.grid(row=4, column=0, columnspan=2, padx=12, pady=8, sticky="ew")
        self.fiyat_alanlari = {}
        for satir, fiyat_adi in enumerate(self.FIYAT_ADLARI):
            ttk.Label(fiyat_cercevesi, text=fiyat_adi).grid(row=satir, column=0, padx=6, pady=4, sticky="w")
            giris = ttk.Entry(fiyat_cercevesi, width=24)
            giris.grid(row=satir, column=1, padx=6, pady=4)
            self.fiyat_alanlari[fiyat_adi] = giris
        if stok:
            for alan in ("stok_kodu", "stok_adi", "barkod"):
                self.alanlar[alan].insert(0, getattr(stok, alan) or "")
            self.birim.set(stok.birim)
            for fiyat in stok.fiyatlar:
                if fiyat.fiyat_adi in self.fiyat_alanlari:
                    self.fiyat_alanlari[fiyat.fiyat_adi].insert(0, str(fiyat.tutar))
        butonlar = ttk.Frame(self)
        butonlar.grid(row=5, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.alanlar["stok_kodu"].focus_set()

    def kaydet(self):
        veriler = {alan: giris.get().strip() for alan, giris in self.alanlar.items()}
        if not veriler["stok_kodu"] or not veriler["stok_adi"]:
            messagebox.showwarning("Eksik bilgi", "Stok kodu ve stok adı zorunludur.", parent=self)
            return
        veriler["birim"] = self.birim.get()
        veriler["stok_id"] = self.stok.id if self.stok else None
        fiyatlar = [(ad, giris.get().strip()) for ad, giris in self.fiyat_alanlari.items()]
        try:
            self.result = StokService.stok_kaydi(veriler, fiyatlar)
        except ValueError as hata:
            messagebox.showerror("Stok kaydedilemedi", str(hata), parent=self)
            return
        self.destroy()


class StokGirisiDialog(tk.Toplevel):
    def __init__(self, parent, stok=None):
        super().__init__(parent)
        self.result = None
        self.title("Stok Girişi")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        stoklar = StokService.stoklari_ara()
        self.stok_map = {f"{s.stok_kodu} - {s.stok_adi}": s for s in stoklar}
        self.stok = ttk.Combobox(self, values=tuple(self.stok_map), state="readonly", width=38)
        self.depo = ttk.Combobox(self, values=tuple(d.ad for d in StokService.depolar()), state="readonly", width=38)
        self.tedarikci = ttk.Entry(self, width=41)
        self.tarih = ttk.Entry(self, width=41)
        self.miktar = ttk.Entry(self, width=41)
        self.maliyet = ttk.Entry(self, width=41)
        self.lot_no = ttk.Entry(self, width=41)
        satirlar = (("Stok", self.stok), ("Depo", self.depo), ("Tedarikçi Firma", self.tedarikci),
                    ("Giriş Tarihi", self.tarih), ("Miktar", self.miktar), ("Birim Maliyet", self.maliyet),
                    ("Otomatik Lot No", self.lot_no))
        for satir, (etiket, widget) in enumerate(satirlar):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            widget.grid(row=satir, column=1, padx=12, pady=6)
        if stok:
            self.stok.set(f"{stok.stok_kodu} - {stok.stok_adi}")
        elif self.stok_map:
            self.stok.current(0)
        if self.depo["values"]:
            self.depo.current(0)
        self.tarih.insert(0, tarih_goster(date.today()))
        self.miktar.insert(0, "1")
        self.maliyet.insert(0, "0")
        self.tedarikci.bind("<KeyRelease>", self.lot_no_guncelle)
        self.tarih.bind("<KeyRelease>", self.lot_no_guncelle)
        self.lot_no_guncelle()
        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(satirlar), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Stok Girişini Kaydet", command=self.kaydet).pack(side="right")

    def lot_no_guncelle(self, _event=None):
        try:
            giris_tarihi = datetime.strptime(self.tarih.get(), "%d.%m.%Y").date()
        except ValueError:
            return
        lot = StokService.otomatik_lot_no(self.tedarikci.get(), giris_tarihi)
        self.lot_no.delete(0, "end")
        self.lot_no.insert(0, lot)

    def kaydet(self):
        stok = self.stok_map.get(self.stok.get())
        if not stok:
            messagebox.showwarning("Eksik bilgi", "Stok kartı seçin.", parent=self)
            return
        try:
            giris_tarihi = datetime.strptime(self.tarih.get(), "%d.%m.%Y").date()
            self.result = StokService.stok_girisi(
                stok.stok_kodu, self.depo.get(), self.tedarikci.get().strip(), giris_tarihi,
                self.miktar.get(), self.maliyet.get(), self.lot_no.get(),
            )
        except ValueError as hata:
            messagebox.showerror("Stok girişi kaydedilemedi", str(hata), parent=self)
            return
        self.destroy()


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
        elif anahtar == "stoklar":
            self.stoklar_goster()
        elif anahtar == "finans":
            self.finans_goster()
        else:
            ttk.Label(self.icerik, text="Bu bölüm sonraki aşamada hazırlanacaktır.").pack(anchor="w", pady=(18, 0))

    def stoklar_goster(self):
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.stok_arama = ttk.Entry(ust, width=32)
        self.stok_arama.pack(side="left", padx=8)
        self.stok_arama.bind("<Return>", lambda _e: self.stok_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.stok_listesini_yenile).pack(side="left")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "ad", "barkod", "birim", "fiyatlar", "miktar")
        basliklar = ("Stok Kodu", "Stok Adı", "Barkod", "Birim", "Tanımlı Fiyatlar", "Toplam Mevcut")
        self.stok_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.stok_tablosu.heading(kolon, text=baslik)
            self.stok_tablosu.column(kolon, width=140, anchor="w")
        self.stok_tablosu.column("ad", width=260)
        self.stok_tablosu.column("fiyatlar", width=320)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.stok_tablosu.yview)
        self.stok_tablosu.configure(yscrollcommand=kaydirma.set)
        self.stok_tablosu.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        self.stok_tablosu.bind("<Double-1>", lambda _e: self.stok_duzenle())
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Stok Kartı", command=self.yeni_stok).pack(side="left")
        ttk.Button(alt, text="Stok Kartını Düzenle", command=self.stok_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Stok Girişi", command=self.stok_girisi).pack(side="left")
        ttk.Button(alt, text="Yeni Depo", command=self.yeni_depo).pack(side="left", padx=8)
        self.stok_listesini_yenile()

    def finans_goster(self):
        ttk.Label(self.icerik, text="Fatura tahsilatları seçilen kasa/banka hesabına otomatik işlenir.").pack(anchor="w", pady=(14, 8))
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("tarih", "hesap", "tur", "belge", "tutar", "aciklama")
        basliklar = ("Tarih", "Hesap", "Hareket", "Belge No", "Tutar", "Açıklama")
        tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for kolon, baslik in zip(kolonlar, basliklar):
            tablo.heading(kolon, text=baslik)
            tablo.column(kolon, width=150, anchor="w")
        tablo.column("aciklama", width=240)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
        tablo.configure(yscrollcommand=kaydirma.set)
        tablo.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        for hareket in FinansService.hareketler():
            tablo.insert("", "end", values=(
                tarih_goster(hareket.tarih), hareket.hesap.hesap_adi, hareket.hareket_turu,
                hareket.belge_no, para_goster(hareket.tutar), hareket.aciklama or "",
            ))

    def stok_listesini_yenile(self):
        if not hasattr(self, "stok_tablosu"):
            return
        for item in self.stok_tablosu.get_children():
            self.stok_tablosu.delete(item)
        for stok in StokService.stoklari_ara(self.stok_arama.get().strip()):
            fiyatlar = " | ".join(f"{f.fiyat_adi}: {para_goster(f.tutar)}" for f in stok.fiyatlar)
            mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
            self.stok_tablosu.insert("", "end", iid=str(stok.id), values=(
                stok.stok_kodu, stok.stok_adi, stok.barkod or "", stok.birim, fiyatlar, mevcut,
            ))

    def _secili_stok(self):
        secim = self.stok_tablosu.selection()
        if not secim:
            messagebox.showinfo("Stok seçimi", "Lütfen bir stok kartı seçin.", parent=self)
            return None
        return next((s for s in StokService.stoklari_ara() if s.id == int(secim[0])), None)

    def yeni_stok(self):
        dialog = StokKartiDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.stok_listesini_yenile()

    def stok_duzenle(self):
        stok = self._secili_stok()
        if stok:
            dialog = StokKartiDialog(self, stok)
            self.wait_window(dialog)
            if dialog.result:
                self.stok_listesini_yenile()

    def stok_girisi(self):
        stok = self._secili_stok()
        if stok:
            dialog = StokGirisiDialog(self, stok)
            self.wait_window(dialog)
            if dialog.result:
                self.stok_listesini_yenile()

    def yeni_depo(self):
        ad = simpledialog.askstring("Yeni Depo", "Depo adı:", parent=self)
        if not ad:
            return
        try:
            depo = StokService.depo_ekle(ad)
        except ValueError as hata:
            messagebox.showerror("Depo eklenemedi", str(hata), parent=self)
            return
        messagebox.showinfo("Depo", f"{depo.ad} kullanıma hazır.", parent=self)

    def satislar_menusu_goster(self):
        alt_menu = ttk.Frame(self.icerik)
        alt_menu.pack(fill="x", pady=(24, 0))
        alt_menu.columnconfigure(0, weight=1)
        alt_menu.columnconfigure(0, minsize=520)

        alt_menu_ogeleri = (
            ("MÜŞTERİ KARTLARI", self.cariler_goster),
            ("SATIŞ SİPARİŞLERİ", self.satis_siparisleri_goster),
            ("SATIŞ İRSALİYELERİ", self.satis_irsaliyeleri_goster),
            ("SATIŞ FATURALARI", self.satis_faturalari_goster),
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

    def satis_faturalari_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIŞ FATURALARI", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(14, 0))
        kolonlar = ("no", "tarih", "vade", "musteri", "siparis", "irsaliye", "depo", "toplam", "tahsilat", "kalan", "durum")
        basliklar = ("Fatura No", "Fatura Tarihi", "Vade Tarihi", "Müşteri", "Sipariş No", "İrsaliye No", "Depo", "Genel Toplam", "Tahsilat", "Kalan", "Durum")
        self.fatura_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.fatura_tablosu.heading(kolon, text=baslik)
            self.fatura_tablosu.column(kolon, width=125)
        self.fatura_tablosu.column("musteri", width=220)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.fatura_tablosu.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.fatura_tablosu.xview)
        self.fatura_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.fatura_tablosu.grid(row=0, column=0, sticky="nsew"); dikey.grid(row=0, column=1, sticky="ns"); yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        self.fatura_tablosu.bind("<Double-1>", lambda _e: self.fatura_ac())
        alt = ttk.Frame(self.icerik); alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Fatura", command=self.yeni_fatura).pack(side="left")
        ttk.Button(alt, text="Faturayı Aç / Düzenle", command=self.fatura_ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal Et", command=self.fatura_iptal).pack(side="left")
        self.fatura_listesini_yenile()

    def fatura_listesini_yenile(self):
        for item in self.fatura_tablosu.get_children(): self.fatura_tablosu.delete(item)
        for kayit in SatisFaturasiService.listele():
            f = kayit["fatura"]; toplam = kayit["genel_toplam"]; tahsilat = f.tahsilat_tutari
            self.fatura_tablosu.insert("", "end", iid=str(f.id), values=(
                f.fatura_no, tarih_goster(f.fatura_tarihi), tarih_goster(f.vade_tarihi), f.cari.unvan,
                f.siparis.siparis_no if f.siparis else "", f.irsaliye.irsaliye_no if f.irsaliye else "",
                f.depo, para_goster(toplam), para_goster(tahsilat), para_goster(toplam - tahsilat), f.durum,
            ))

    def _secili_fatura_id(self):
        secim = self.fatura_tablosu.selection()
        if not secim:
            messagebox.showinfo("Fatura seçimi", "Lütfen bir fatura seçin.", parent=self)
            return None
        return int(secim[0])

    def yeni_fatura(self):
        dialog = SatisFaturasiDialog(self, cari_ac=lambda cari: CariDialog(self, cari))
        self.wait_window(dialog)
        if dialog.result: self.fatura_listesini_yenile()

    def fatura_ac(self):
        fatura_id = self._secili_fatura_id()
        if fatura_id is not None:
            fatura = SatisFaturasiService.getir(fatura_id)
            if fatura:
                dialog = SatisFaturasiDialog(self, fatura=fatura, cari_ac=lambda cari: CariDialog(self, cari))
                self.wait_window(dialog)
                if dialog.result: self.fatura_listesini_yenile()

    def fatura_iptal(self):
        fatura_id = self._secili_fatura_id()
        if fatura_id is not None and messagebox.askyesno("Faturayı iptal et", "Seçili fatura iptal edilsin mi?", parent=self):
            try: SatisFaturasiService.iptal_et(fatura_id)
            except ValueError as hata: messagebox.showerror("İşlem yapılamadı", str(hata), parent=self); return
            self.fatura_listesini_yenile()

    def satis_irsaliyeleri_goster(self):
        self._icerigi_temizle(); ttk.Label(self.icerik, text="SATIŞ İRSALİYELERİ", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik); cerceve.pack(fill="both", expand=True, pady=(14, 0))
        kolonlar = ("no", "tarih", "musteri_kodu", "musteri", "siparis", "toplam", "fatura", "kalan", "durum")
        basliklar = ("İrsaliye Numarası", "İrsaliye Tarihi", "Müşteri Kodu", "Müşteri Adı", "Sipariş Numarası", "Genel Toplam", "Faturalanan Tutar", "Kalan Faturalanabilir Tutar", "Durum")
        self.irsaliye_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar): self.irsaliye_tablosu.heading(kolon, text=baslik); self.irsaliye_tablosu.column(kolon, width=140)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.irsaliye_tablosu.yview); yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.irsaliye_tablosu.xview); self.irsaliye_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set); self.irsaliye_tablosu.grid(row=0, column=0, sticky="nsew"); dikey.grid(row=0, column=1, sticky="ns"); yatay.grid(row=1, column=0, sticky="ew"); cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        alt = ttk.Frame(self.icerik); alt.pack(fill="x", pady=10); ttk.Button(alt, text="Yeni İrsaliye", command=self.yeni_irsaliye).pack(side="left"); ttk.Button(alt, text="İrsaliyeyi Aç / Düzenle", command=self.irsaliye_ac).pack(side="left", padx=8); ttk.Button(alt, text="Faturaya Çevir", command=self.irsaliye_faturaya_cevir).pack(side="left"); ttk.Button(alt, text="İptal Et", command=self.irsaliye_iptal).pack(side="left", padx=8)
        self.irsaliye_listesini_yenile()

    def irsaliye_listesini_yenile(self):
        for item in self.irsaliye_tablosu.get_children(): self.irsaliye_tablosu.delete(item)
        for kayit in SatisIrsaliyesiService.listele():
            irsaliye = kayit["irsaliye"]; musteri = irsaliye.cari; siparis = irsaliye.siparis
            self.irsaliye_tablosu.insert("", "end", iid=str(irsaliye.id), values=(irsaliye.irsaliye_no, tarih_goster(irsaliye.irsaliye_tarihi), musteri.cari_kodu, musteri.unvan, siparis.siparis_no if siparis else "", para_goster(kayit["toplam"]), para_goster(kayit["faturalanan"]), para_goster(kayit["kalan"]), irsaliye.durum))

    def _secili_irsaliye_id(self):
        secim = self.irsaliye_tablosu.selection()
        if not secim: messagebox.showinfo("İrsaliye seçimi", "Lütfen bir irsaliye seçin.", parent=self); return None
        return int(secim[0])

    def yeni_irsaliye(self):
        dialog = SatisIrsaliyesiDialog(self); self.wait_window(dialog)
        if dialog.result: self.irsaliye_listesini_yenile()

    def irsaliye_ac(self):
        irsaliye_id = self._secili_irsaliye_id()
        if irsaliye_id is not None:
            irsaliye = SatisIrsaliyesiService.getir(irsaliye_id)
            if irsaliye:
                dialog = SatisIrsaliyesiDialog(self, irsaliye=irsaliye); self.wait_window(dialog)
                if dialog.result: self.irsaliye_listesini_yenile()

    def irsaliye_faturaya_cevir(self):
        irsaliye_id = self._secili_irsaliye_id()
        if irsaliye_id is not None:
            irsaliye = SatisIrsaliyesiService.getir(irsaliye_id)
            if irsaliye:
                dialog = SatisFaturasiDialog(self, irsaliye=irsaliye, cari_ac=lambda cari: CariDialog(self, cari))
                self.wait_window(dialog)
                if dialog.result: self.irsaliye_listesini_yenile()

    def irsaliye_iptal(self):
        irsaliye_id = self._secili_irsaliye_id()
        if irsaliye_id is not None and messagebox.askyesno("İrsaliyeyi iptal et", "Seçili irsaliye iptal edilsin mi?", parent=self):
            try: SatisIrsaliyesiService.iptal_et(irsaliye_id)
            except ValueError as hata: messagebox.showerror("İşlem yapılamadı", str(hata), parent=self); return
            self.irsaliye_listesini_yenile()

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
        ttk.Button(alt, text="Faturaya Çevir", command=self.siparis_faturaya_cevir).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=self.siparis_iptal).pack(side="left", padx=8)
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

    def siparis_faturaya_cevir(self):
        siparis_id = self._secili_siparis_id()
        if siparis_id is not None:
            siparis = SatisSiparisiService.getir(siparis_id)
            if siparis:
                dialog = SatisFaturasiDialog(self, siparis=siparis, cari_ac=lambda cari: CariDialog(self, cari))
                self.wait_window(dialog)
                if dialog.result:
                    self.siparis_listesini_yenile()

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
