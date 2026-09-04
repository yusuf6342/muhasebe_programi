import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

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
        self.title("Cari Düzenle" if cari else "Yeni Cari")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.degerler = {}
        alanlar = (("Cari Kodu", "cari_kodu"), ("Ünvan", "unvan"), ("Cari Türü", "cari_turu"), ("Telefon", "telefon"), ("E-posta", "email"), ("Adres", "adres"))
        for satir, (etiket, alan) in enumerate(alanlar):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            if alan == "cari_turu":
                widget = ttk.Combobox(self, values=("Müşteri", "Tedarikçi"), state="readonly", width=35)
            elif alan == "adres":
                widget = tk.Text(self, width=36, height=3)
            else:
                widget = ttk.Entry(self, width=38)
            widget.grid(row=satir, column=1, padx=12, pady=6)
            self.degerler[alan] = widget
        if cari:
            for alan, widget in self.degerler.items():
                deger = getattr(cari, alan) or ""
                if alan == "adres":
                    widget.insert("1.0", deger)
                elif alan == "cari_turu":
                    widget.set(deger)
                else:
                    widget.insert(0, deger)
        else:
            self.degerler["cari_turu"].set("Müşteri")
        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(alanlar), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.degerler["cari_kodu"].focus_set()

    def kaydet(self):
        veriler = {}
        for alan, widget in self.degerler.items():
            deger = widget.get("1.0", "end").strip() if alan == "adres" else widget.get().strip()
            veriler[alan] = deger or None
        if not veriler["cari_kodu"] or not veriler["unvan"] or not veriler["cari_turu"]:
            messagebox.showwarning("Eksik bilgi", "Cari kodu, ünvan ve cari türü zorunludur.", parent=self)
            return
        veriler["aktif"] = self.cari.aktif if self.cari else True
        try:
            self.result = CariService.guncelle(self.cari.id, veriler) if self.cari else CariService.ekle(veriler)
        except ValueError as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return
        self.destroy()


class SatisDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, cari_id: int):
        super().__init__(parent)
        self.cari_id = cari_id
        self.result = None
        self.title("Yeni Satış Hareketi")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        alanlar = (("Satış Tarihi", "satis_tarihi"), ("Belge/Fatura No", "belge_no"), ("Satış Tutarı", "satis_tutari"), ("Kalan Açık Tutar", "kalan_acik_tutar"))
        self.degerler = {}
        for satir, (etiket, alan) in enumerate(alanlar):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=7, sticky="w")
            widget = ttk.Entry(self, width=32)
            widget.grid(row=satir, column=1, padx=12, pady=7)
            self.degerler[alan] = widget
        self.degerler["satis_tarihi"].insert(0, date.today().strftime("%d.%m.%Y"))
        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(alanlar), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            satis_tarihi = datetime.strptime(self.degerler["satis_tarihi"].get().strip(), "%d.%m.%Y").date()
            veriler = {alan: widget.get().strip() for alan, widget in self.degerler.items()}
            veriler["satis_tarihi"] = satis_tarihi
            self.result = CariService.satis_ekle(self.cari_id, veriler)
        except (ValueError, TypeError) as hata:
            messagebox.showerror("Hareket kaydedilemedi", str(hata), parent=self)
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
        else:
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
        ttk.Label(self.icerik, text="Cari Kartlar", style="Baslik.TLabel").pack(anchor="w")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara (en az 3 karakter):").pack(side="left")
        self.cari_arama = ttk.Entry(ust, width=30)
        self.cari_arama.pack(side="left", padx=8)
        self.cari_arama.bind("<Return>", lambda _event: self.cari_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.cari_listesini_yenile).pack(side="left")
        ttk.Button(ust, text="Yeni Cari", command=self.yeni_cari).pack(side="right")

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "unvan", "tur", "telefon", "bakiye", "ortalama", "agirlikli", "durum")
        basliklar = {"kod": "Cari Kodu", "unvan": "Ünvan", "tur": "Cari Türü", "telefon": "Telefon", "bakiye": "Yekûn Bakiye", "ortalama": "Ortalama Geçen Gün", "agirlikli": "Ağırlıklı Ortalama Geçen Gün", "durum": "Durum"}
        genislikler = {"kod": 105, "unvan": 210, "tur": 100, "telefon": 115, "bakiye": 125, "ortalama": 135, "agirlikli": 175, "durum": 75}
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
        ttk.Button(alt, text="Detay / Satışlar", command=self.cari_detay).pack(side="left")
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
            self.cari_tablosu.insert("", "end", iid=str(cari.id), values=(cari.cari_kodu, cari.unvan, cari.cari_turu, cari.telefon or "", para_goster(ozet["bakiye"]), f"{ozet['ortalama_gun']:.1f}", f"{ozet['agirlikli_ortalama_gun']:.1f}", "Aktif" if cari.aktif else "Pasif"))

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
        detay = CariService.detay(cari.id)
        if not detay:
            return
        pencere = tk.Toplevel(self)
        pencere.title(f"Cari Detayı - {cari.unvan}")
        pencere.geometry("850x430")
        ttk.Label(pencere, text=f"{cari.cari_kodu} - {cari.unvan}", style="Baslik.TLabel").pack(anchor="w", padx=16, pady=12)
        ttk.Button(pencere, text="Satış Hareketi Ekle", command=lambda: self.satis_ekle(pencere, cari.id)).pack(anchor="e", padx=16, pady=(0, 8))
        kolonlar = ("tarih", "belge", "satis", "kalan", "gun")
        tablo = ttk.Treeview(pencere, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (("tarih", "Tarih", 110), ("belge", "Belge No", 180), ("satis", "Satış Tutarı", 140), ("kalan", "Kalan Tutar", 140), ("gun", "Geçen Gün", 110)):
            tablo.heading(kolon, text=baslik)
            tablo.column(kolon, width=genislik)
        tablo.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        for hareket in detay["hareketler"]:
            gun = (date.today() - hareket.satis_tarihi).days
            tablo.insert("", "end", values=(tarih_goster(hareket.satis_tarihi), hareket.belge_no, para_goster(hareket.satis_tutari), para_goster(hareket.kalan_acik_tutar), gun))

    def satis_ekle(self, detay_penceresi, cari_id):
        dialog = SatisDialog(self, cari_id)
        self.wait_window(dialog)
        if dialog.result:
            detay_penceresi.destroy()
            self.cari_listesini_yenile()
