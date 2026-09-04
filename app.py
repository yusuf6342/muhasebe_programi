import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk

from database.cari_service import CariService
from database.firma_service import FirmaService


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
        tablo = ttk.Treeview(parent, columns=kolonlar, show="headings")
        basliklar = {"tarih": "Tarih", "tur": "Belge Türü", "belge": "Belge Numarası", "aciklama": "Açıklama", "borc": "Borç", "alacak": "Alacak", "bakiye": "Kalan Bakiye", "gun": "Geçen Gün"}
        genislikler = {"tarih": 85, "tur": 90, "belge": 115, "aciklama": 120, "borc": 100, "alacak": 100, "bakiye": 110, "gun": 105}
        for kolon in kolonlar:
            tablo.heading(kolon, text=basliklar[kolon])
            tablo.column(kolon, width=genislikler[kolon], anchor="w")
        tablo.pack(fill="both", expand=True)
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
            ("SATIŞ SİPARİŞLERİ", lambda: self.satis_alt_sayfasi_goster("SATIŞ SİPARİŞLERİ")),
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

