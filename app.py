import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.cari_service import CariService
from database.firma_service import FirmaService
from database.kk_cekimi_service import KkCekimiService
from database.rapor_service import RaporService
from database.satis_irsaliyesi_service import SatisIrsaliyesiService
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
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
from stok_ui import StokKartiDialog
from depo_transfer_ui import depo_transfer_listesini_goster
from stok_birlestir_ui import stok_birlestir_sayfasi_goster
from stok_paket_ui import stok_paket_sayfasi_goster
from stok_barkod_ui import stok_barkod_basimi_goster as barkod_basim_sayfasini_ac
from stok_rapor_ui import stok_raporlari_menusu_goster
from stok_toplu_fiyat_ui import toplu_fiyat_sayfasi_goster
from finans_ui import finans_menusu_goster
from ui_takvim import saat_dogrula, saat_varsayilan, takvim_butonu
from urun_sec_ui import UrunSecDialog

# Geriye dönük uyumluluk
ProductSelectionDialog = UrunSecDialog

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
    def __init__(self, parent: tk.Misc, cari=None, cari_turu: str = "Müşteri"):
        super().__init__(parent)
        self.cari = cari
        self.result = None
        self.cari_turu = (cari.cari_turu if cari else cari_turu) or "Müşteri"
        self.tedarikci_modu = self.cari_turu == "Tedarikçi"
        etiket = "Tedarikçi" if self.tedarikci_modu else "Müşteri"
        self.title(f"{etiket} Cari Hesap Kartı" if cari else f"Yeni {etiket}")
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

        ttk.Label(icerik, text=f"{etiket.upper()} CARİ HESAP BİLGİLERİ", style="Baslik.TLabel").pack(anchor="w", pady=(0, 6))
        genel = ttk.LabelFrame(icerik, text=f"{etiket} Bilgileri", padding=10)
        genel.pack(fill="x", pady=(0, 10))

        alanlar = (
            (f"{etiket} Kodu", "cari_kodu"),
            (f"{etiket} Adı / Ünvanı", "unvan"),
            ("Vergi Dairesi", "vergi_dairesi"),
            ("Vergi Numarası", "vergi_numarasi"),
            ("Telefon", "telefon"),
            ("E-posta", "email"),
            (f"{etiket} Grubu", "musteri_grubu"),
            ("Adres", "adres"),
        )
        for sira, (etiket_alan, alan) in enumerate(alanlar):
            sutun = (sira % 2) * 2
            satir = sira // 2
            ttk.Label(genel, text=etiket_alan).grid(row=satir, column=sutun, padx=8, pady=5, sticky="nw")
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
        else:
            otomatik_kod = CariService.sonraki_kod(self.cari_turu)
            self.degerler["cari_kodu"].insert(0, otomatik_kod)
        self.degerler["cari_kodu"].configure(state="readonly")
        self._bakiye_ozetini_olustur(icerik)
        self._hizli_islemleri_olustur(icerik)
        self._hareket_tablosunu_olustur(icerik)

        butonlar = ttk.Frame(icerik)
        butonlar.pack(fill="x", pady=(10, 4))
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        if cari:
            ttk.Button(butonlar, text="Pasife Al" if cari.aktif else "Aktif Et", command=self.durumu_degistir).pack(side="right", padx=8)
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.degerler["unvan"].focus_set()

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
        if self.tedarikci_modu:
            komutlar = (
                ("YENİ SATIN ALMA SİPARİŞİ", self.yeni_alis_siparis_ac),
                ("YENİ SATIN ALMA İRSALİYESİ", self.yeni_alis_irsaliye_ac),
                ("YENİ SATIN ALMA FATURASI", self.yeni_alis_fatura_ac),
                ("ÖDEME GİR", self.odeme_gir),
                ("TAHSİLAT GİR", self.tahsilat_gir),
            )
        else:
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
        if self.cari:
            self.yenile()

    def _hareket_satirini_ekle(self, hareket):
        gun = (date.today() - hareket["tarih"]).days
        kalan = para_goster(hareket["kalan"]) if hareket.get("kalan") is not None else ""
        self.hareket_tablosu.insert("", "end", values=(
            tarih_goster(hareket["tarih"]), hareket["tur"], hareket["belge_no"],
            hareket.get("aciklama", ""), para_goster(hareket["borc"]),
            para_goster(hareket["alacak"]), kalan, gun,
        ))

    def yenile(self):
        if not self.cari:
            return
        kayit = next((item for item in CariService.listele() if item["cari"].id == self.cari.id), None)
        bakiye = kayit["bakiye"] if kayit else Decimal("0")
        ortalama = kayit["agirlikli_ortalama_gun"] if kayit else 0
        detay = CariService.detay(self.cari.id)
        hareketler = detay["hareketler"] if detay else []
        acik_sayisi = len(detay["acik_hareketler"]) if detay else 0
        durum = "Borçlu" if bakiye > 0 else "Alacaklı" if bakiye < 0 else "Sıfır"
        renk = "#c62828" if bakiye > 0 else "#2e7d32" if bakiye < 0 else "#444444"
        self.ozet_degerleri["Güncel Toplam Bakiye"].configure(text=para_goster(bakiye), foreground=renk)
        self.ozet_degerleri["Borç / Alacak Durumu"].configure(text=durum, foreground=renk)
        self.ozet_degerleri["Ağırlıklı Ortalama Geçen Gün"].configure(text=f"{ortalama:.1f} gün")
        self.ozet_degerleri["Açık Hareket Sayısı"].configure(text=str(acik_sayisi))
        for item in self.hareket_tablosu.get_children():
            self.hareket_tablosu.delete(item)
        for hareket in hareketler:
            self._hareket_satirini_ekle(hareket)

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

    def yeni_alis_siparis_ac(self):
        if not self.cari:
            return
        from alis_ui import AlisSiparisiDialog
        dialog = AlisSiparisiDialog(self, cari=self.cari)
        self.wait_window(dialog)
        self.yenile()

    def yeni_alis_irsaliye_ac(self):
        if self.cari:
            from alis_ui import AlisIrsaliyesiDialog
            dialog = AlisIrsaliyesiDialog(self, cari=self.cari)
            self.wait_window(dialog)
            self.yenile()

    def yeni_alis_fatura_ac(self):
        if self.cari:
            from alis_ui import AlisFaturasiDialog
            dialog = AlisFaturasiDialog(self, cari=self.cari, cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"))
            self.wait_window(dialog)
            self.yenile()

    def tahsilat_gir(self):
        if self.cari:
            dialog = CariTahsilatOdemeDialog(self, self.cari, tur="tahsilat")
            self.wait_window(dialog)
            if dialog.result:
                self.yenile()

    def odeme_gir(self):
        if self.cari:
            dialog = CariTahsilatOdemeDialog(self, self.cari, tur="odeme")
            self.wait_window(dialog)
            if dialog.result:
                self.yenile()


    def kaydet(self):
        veriler = {}
        for alan, widget in self.degerler.items():
            if alan == "aktif":
                continue
            # readonly Entry için state geçici aç
            onceki_durum = None
            if alan == "cari_kodu" and isinstance(widget, ttk.Entry):
                onceki_durum = str(widget.cget("state"))
                widget.configure(state="normal")
            deger = widget.get("1.0", "end").strip() if isinstance(widget, tk.Text) else widget.get().strip()
            if onceki_durum is not None:
                widget.configure(state=onceki_durum)
            veriler[alan] = deger or None
        if not veriler["unvan"]:
            messagebox.showwarning(
                "Eksik bilgi",
                ("Tedarikçi" if self.tedarikci_modu else "Müşteri") + " adı/ünvanı zorunludur.",
                parent=self,
            )
            return
        veriler["cari_turu"] = self.cari.cari_turu if self.cari else self.cari_turu
        veriler["aktif"] = self.degerler["aktif"].get()
        if not self.cari:
            # Kayıt anında güncel sırayı al (ekran açıkken başka kayıt yapılmış olabilir)
            veriler["cari_kodu"] = CariService.sonraki_kod(veriler["cari_turu"])
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


class PriceSelectionDialog(tk.Toplevel):
    def __init__(self, parent, product_code, on_select=None, fiyat_turu=None):
        """fiyat_turu: None=tümü, 'alis'=ALIŞ fiyatları, 'satis'=SATIŞ fiyatları."""
        super().__init__(parent)
        baslik = "Fiyat Seçimi"
        if fiyat_turu == "alis":
            baslik = "Alış Fiyatı Seçimi"
        elif fiyat_turu == "satis":
            baslik = "Satış Fiyatı Seçimi"
        self.title(baslik)
        self.geometry("620x300")
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        self._son_secim = None
        ttk.Label(self, text=f"Ürün: {product_code}").pack(anchor="w", padx=12, pady=(12, 6))
        kolonlar = ("ad", "fiyat", "para", "tarih")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings")
        for kolon, baslik_kolon, genislik in (("ad", "Fiyat Adı", 180), ("fiyat", "Fiyat", 120), ("para", "Para Birimi", 120), ("tarih", "Geçerlilik Tarihi", 150)):
            self.tablo.heading(kolon, text=baslik_kolon)
            self.tablo.column(kolon, width=genislik)
        self.tablo.pack(fill="both", expand=True, padx=12, pady=6)
        if fiyat_turu == "alis":
            self.fiyatlar = StokService.alis_fiyatlari(product_code)
        elif fiyat_turu == "satis":
            from database.stok_service import SATIS_FIYAT_ADLARI
            satis_adlari = {(ad or "").strip().upper() for ad in SATIS_FIYAT_ADLARI}
            self.fiyatlar = [
                f for f in search_prices(product_code)
                if (f.fiyat_adi or "").strip().upper() in satis_adlari
            ]
        else:
            self.fiyatlar = search_prices(product_code)
        for sira, fiyat in enumerate(self.fiyatlar):
            self.tablo.insert("", "end", iid=str(sira), values=(fiyat.fiyat_adi, fiyat.tutar, fiyat.para_birimi, "Sürekli"))
        if not self.fiyatlar:
            mesaj = "Bu ürüne ait tanımlı fiyat bulunamadı"
            if fiyat_turu == "alis":
                mesaj = "Bu ürüne ait tanımlı alış fiyatı bulunamadı"
            elif fiyat_turu == "satis":
                mesaj = "Bu ürüne ait tanımlı satış fiyatı bulunamadı"
            ttk.Label(self, text=mesaj).pack(anchor="w", padx=12, pady=4)
        else:
            ilk = "0"
            self.tablo.selection_set(ilk)
            self.tablo.focus(ilk)
            self.tablo.see(ilk)
            self._son_secim = ilk
        self.tablo.bind("<<TreeviewSelect>>", self._secim_kaydet)
        self.tablo.bind("<Double-1>", lambda _event: self.sec())
        self.tablo.bind("<Return>", lambda _event: self.sec())
        alt = ttk.Frame(self); alt.pack(fill="x", padx=12, pady=8)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Fiyat Seç", command=self.sec).pack(side="right", padx=8)

    def _secim_kaydet(self, _event=None):
        secim = self.tablo.selection()
        if secim:
            self._son_secim = secim[0]

    def _secili_iid(self):
        secim = self.tablo.selection()
        if secim:
            return secim[0]
        odak = self.tablo.focus()
        if odak:
            return odak
        return self._son_secim

    def sec(self):
        if not self.on_select:
            self.destroy()
            return
        iid = self._secili_iid()
        if iid is None or not self.fiyatlar:
            messagebox.showinfo("Fiyat", "Lütfen listeden bir fiyat seçin.", parent=self)
            return
        try:
            fiyat = self.fiyatlar[int(iid)]
            tutar = fiyat.tutar
        except (ValueError, IndexError, TypeError, AttributeError):
            messagebox.showinfo("Fiyat", "Lütfen listeden bir fiyat seçin.", parent=self)
            return
        # Düz değer: destroy sonrası ORM / grab kaynaklı sessiz hataları önle
        secilen = type("_Fiyat", (), {"tutar": tutar})()
        callback = self.on_select
        self.on_select = None
        self.destroy()
        callback(secilen)


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
        if widget not in (self.girdiler.get("urun_kodu"), self.girdiler.get("urun_adi")):
            return
        sorgu = widget.get().strip()
        if len(sorgu) < 2 or sorgu == self._son_urun_arama:
            return
        self._son_urun_arama = sorgu
        if widget is self.girdiler.get("urun_kodu"):
            ProductSelectionDialog(self, on_select=self.urun_secildi, kod=sorgu)
        else:
            ProductSelectionDialog(self, on_select=self.urun_secildi, ad=sorgu)

    def urun_secildi(self, degerler):
        for alan, deger in (("urun_kodu", degerler[0]), ("urun_adi", degerler[1]), ("birim", degerler[2]), ("birim_satis_fiyati", degerler[4])):
            widget = self.girdiler[alan]
            widget.delete(0, "end")
            widget.insert(0, deger)
        self.tutar_guncelle()

    def fiyat_secimi_ac(self, _event):
        kod = self.girdiler["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(
            self, kod, on_select=self.fiyati_secildi, fiyat_turu="satis"
        )
        self.wait_window(dialog)
        try:
            self.girdiler["birim_satis_fiyati"].focus_set()
        except tk.TclError:
            pass
        return "break"

    def fiyati_secildi(self, fiyat):
        alan = self.girdiler["birim_satis_fiyati"]
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)
        self.tutar_guncelle()

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


class CariTahsilatOdemeDialog(tk.Toplevel):
    def __init__(self, parent, cari, tur="tahsilat"):
        super().__init__(parent)
        self.cari = cari
        self.tur = tur
        self.result = None
        self.title("Tahsilat Gir" if tur == "tahsilat" else "Ödeme Gir")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        ttk.Label(self, text=f"{cari.cari_kodu} - {cari.unvan}", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 4), sticky="w"
        )
        alanlar = (("Tarih", "tarih"), ("Tutar", "tutar"), ("Ödeme Şekli", "odeme_sekli"), ("Hesap", "hesap"), ("Açıklama", "aciklama"))
        self.girdiler = {}
        for satir, (baslik, alan) in enumerate(alanlar, start=1):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=12, pady=5, sticky="w")
            if alan == "odeme_sekli":
                widget = ttk.Combobox(self, values=ODEME_SEKILLERI, state="readonly", width=32)
            elif alan == "hesap":
                widget = ttk.Combobox(self, values=tuple(h.hesap_adi for h in FinansService.hesaplar()), state="readonly", width=32)
            else:
                widget = ttk.Entry(self, width=34)
            widget.grid(row=satir, column=1, padx=12, pady=5)
            self.girdiler[alan] = widget
        self.girdiler["tarih"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["odeme_sekli"].set(ODEME_SEKILLERI[0])
        hesaplar = FinansService.hesaplar()
        if hesaplar:
            self.girdiler["hesap"].set(hesaplar[0].hesap_adi)
        butonlar = ttk.Frame(self)
        butonlar.grid(row=6, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.girdiler.items()}
        if not veri["hesap"]:
            messagebox.showwarning("Eksik hesap", "Kasa/banka hesabı seçin.", parent=self)
            return
        try:
            tarih = datetime.strptime(veri["tarih"], "%d.%m.%Y").date()
            if self.tur == "tahsilat":
                self.result = CariService.tahsilat_yap(
                    self.cari.id, tarih, veri["tutar"], veri["odeme_sekli"], veri["hesap"], veri["aciklama"] or None
                )
            else:
                self.result = CariService.odeme_yap(
                    self.cari.id, tarih, veri["tutar"], veri["odeme_sekli"], veri["hesap"], veri["aciklama"] or None
                )
        except ValueError as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return
        self.destroy()


class CariVirmanDialog(tk.Toplevel):
    """Herhangi iki cari hesap arasında virman fişi oluşturur."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Yeni Cari Virman Fişi")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.cari_map = {}
        self._olustur()

    def _olustur(self):
        ttk.Label(self, text="CARİ VİRMAN FİŞİ", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 4), sticky="w"
        )
        ttk.Label(
            self,
            text="Alacak yazılan tutar, seçilen karşı cariye aynı miktarda otomatik borç yazılır.",
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        cariler = CariService.aktif_cariler()
        etiketler = [f"{c.cari_kodu} - {c.unvan} ({c.cari_turu})" for c in cariler]
        self.cari_map = {f"{c.cari_kodu} - {c.unvan} ({c.cari_turu})": c for c in cariler}
        bakiyeler = {o["cari"].id: o["bakiye"] for o in CariService.listele()}
        self.bakiyeler = bakiyeler

        self.girdiler = {}
        satir = 2
        for baslik, alan in (
            ("Alacak yazılacak cari", "kaynak"),
            ("Borç yazılacak karşı cari", "hedef"),
            ("Tarih", "tarih"),
            ("Tutar", "tutar"),
            ("Açıklama", "aciklama"),
        ):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=12, pady=5, sticky="w")
            if alan in ("kaynak", "hedef"):
                widget = ttk.Combobox(self, values=etiketler, width=48)
            else:
                widget = ttk.Entry(self, width=50)
            widget.grid(row=satir, column=1, padx=12, pady=5, sticky="w")
            self.girdiler[alan] = widget
            satir += 1

        self.girdiler["tarih"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.kaynak_bakiye = ttk.Label(self, text="Alacak cari bakiyesi: -")
        self.kaynak_bakiye.grid(row=satir, column=0, columnspan=2, padx=12, pady=(2, 0), sticky="w")
        satir += 1
        self.hedef_bakiye = ttk.Label(self, text="Borç (karşı) cari bakiyesi: -")
        self.hedef_bakiye.grid(row=satir, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        satir += 1
        self.onizleme = ttk.Label(
            self,
            text="Önizleme: —",
            font=("Segoe UI", 9, "bold"),
            foreground="#1f6aa5",
        )
        self.onizleme.grid(row=satir, column=0, columnspan=2, padx=12, pady=(4, 6), sticky="w")
        satir += 1

        self.girdiler["kaynak"].bind("<<ComboboxSelected>>", self._bakiye_goster)
        self.girdiler["hedef"].bind("<<ComboboxSelected>>", self._bakiye_goster)
        self.girdiler["kaynak"].bind("<KeyRelease>", self._kaynak_filtrele)
        self.girdiler["hedef"].bind("<KeyRelease>", self._hedef_filtrele)
        self.girdiler["tutar"].bind("<KeyRelease>", self._bakiye_goster)

        butonlar = ttk.Frame(self)
        butonlar.grid(row=satir, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Fişi Kaydet", command=self.kaydet).pack(side="right")
        self._tum_etiketler = etiketler

    def _filtrele(self, widget, metin):
        metin = metin.casefold()
        if not metin:
            widget["values"] = self._tum_etiketler
            return
        widget["values"] = [e for e in self._tum_etiketler if metin in e.casefold()]

    def _kaynak_filtrele(self, _event=None):
        self._filtrele(self.girdiler["kaynak"], self.girdiler["kaynak"].get())
        self._bakiye_goster()

    def _hedef_filtrele(self, _event=None):
        self._filtrele(self.girdiler["hedef"], self.girdiler["hedef"].get())
        self._bakiye_goster()

    def _bakiye_goster(self, _event=None):
        kaynak = self.cari_map.get(self.girdiler["kaynak"].get())
        hedef = self.cari_map.get(self.girdiler["hedef"].get())
        if kaynak:
            self.kaynak_bakiye.configure(
                text=f"Alacak cari bakiyesi: {para_goster(self.bakiyeler.get(kaynak.id, Decimal('0')))} ({kaynak.cari_turu})"
            )
        if hedef:
            self.hedef_bakiye.configure(
                text=f"Borç (karşı) cari bakiyesi: {para_goster(self.bakiyeler.get(hedef.id, Decimal('0')))} ({hedef.cari_turu})"
            )
        tutar_metin = self.girdiler["tutar"].get().strip()
        try:
            tutar = CariService._tutar(tutar_metin) if tutar_metin else Decimal("0")
        except ValueError:
            tutar = Decimal("0")
        if kaynak and hedef and tutar > 0:
            self.onizleme.configure(
                text=(
                    f"Önizleme: {para_goster(tutar)} ALACAK → {kaynak.cari_kodu}  |  "
                    f"{para_goster(tutar)} BORÇ → {hedef.cari_kodu} (otomatik)"
                )
            )
        else:
            self.onizleme.configure(text="Önizleme: Alacak cari + karşı cari + tutar girince çift kayıt görünür.")

    def kaydet(self):
        kaynak = self.cari_map.get(self.girdiler["kaynak"].get())
        hedef = self.cari_map.get(self.girdiler["hedef"].get())
        if not kaynak or not hedef:
            messagebox.showwarning("Eksik bilgi", "Kaynak ve hedef cari seçin.", parent=self)
            return
        if kaynak.id == hedef.id:
            messagebox.showwarning("Geçersiz seçim", "Kaynak ve hedef cari aynı olamaz.", parent=self)
            return
        tutar_metin = self.girdiler["tutar"].get().strip()
        try:
            tutar = CariService._tutar(tutar_metin)
        except ValueError as hata:
            messagebox.showerror("Geçersiz tutar", str(hata), parent=self)
            return
        if tutar <= 0:
            messagebox.showerror("Geçersiz tutar", "Virman tutarı pozitif olmalıdır.", parent=self)
            return
        try:
            tarih = datetime.strptime(self.girdiler["tarih"].get().strip(), "%d.%m.%Y").date()
            self.result = CariService.virman_yap(
                kaynak.id,
                hedef.id,
                tarih,
                tutar_metin,
                self.girdiler["aciklama"].get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("Virman kaydedilemedi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "Virman fişi",
            f"Çift kayıt oluşturuldu.\n"
            f"Alacak: {kaynak.cari_kodu}  →  Borç: {hedef.cari_kodu}\n"
            f"Tutar: {para_goster(tutar)}",
            parent=self,
        )
        self.destroy()


class KkCekimiDialog(tk.Toplevel):
    """Müşteriden tedarikçiye kredi kartı çekim fişi."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Yeni Kredi Kartı Çekim Fişi")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.cari_map = {}
        self._olustur()

    def _olustur(self):
        ttk.Label(self, text="KREDİ KARTI ÇEKİM FİŞİ", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 4), sticky="w"
        )
        ttk.Label(
            self,
            text="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit serbest girilir; kasa/banka hesabına işlem düşmez.",
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        cariler = CariService.aktif_cariler()
        etiketler = [f"{c.cari_kodu} - {c.unvan} ({c.cari_turu})" for c in cariler]
        self.cari_map = {etiket: c for etiket, c in zip(etiketler, cariler)}
        self.bakiyeler = {o["cari"].id: o["bakiye"] for o in CariService.listele()}

        self.girdiler = {}
        satir = 2
        for baslik, alan in (
            ("Müşteri (Alacak)", "musteri"),
            ("Tedarikçi (Borç)", "tedarikci"),
            ("Tarih", "tarih"),
            ("Tutar", "tutar"),
            ("Karın Ait Olduğu Banka", "banka"),
            ("Taksit Sayısı", "taksit_sayisi"),
            ("Açıklama", "aciklama"),
        ):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=12, pady=5, sticky="w")
            if alan in ("musteri", "tedarikci"):
                widget = ttk.Combobox(self, values=etiketler, width=48)
            else:
                widget = ttk.Entry(self, width=50)
            widget.grid(row=satir, column=1, padx=12, pady=5, sticky="w")
            self.girdiler[alan] = widget
            satir += 1

        self.girdiler["tarih"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["taksit_sayisi"].insert(0, "1")

        self.musteri_bakiye = ttk.Label(self, text="Müşteri bakiyesi: -")
        self.musteri_bakiye.grid(row=satir, column=0, columnspan=2, padx=12, pady=(2, 0), sticky="w")
        satir += 1
        self.tedarikci_bakiye = ttk.Label(self, text="Tedarikçi bakiyesi: -")
        self.tedarikci_bakiye.grid(row=satir, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="w")
        satir += 1
        self.onizleme = ttk.Label(self, text="Önizleme: —", font=("Segoe UI", 9, "bold"), foreground="#1f6aa5")
        self.onizleme.grid(row=satir, column=0, columnspan=2, padx=12, pady=(4, 6), sticky="w")
        satir += 1

        self.girdiler["musteri"].bind("<<ComboboxSelected>>", self._guncelle)
        self.girdiler["tedarikci"].bind("<<ComboboxSelected>>", self._guncelle)
        self.girdiler["tutar"].bind("<KeyRelease>", self._guncelle)
        self.girdiler["banka"].bind("<KeyRelease>", self._guncelle)
        self.girdiler["taksit_sayisi"].bind("<KeyRelease>", self._guncelle)

        butonlar = ttk.Frame(self)
        butonlar.grid(row=satir, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Fişi Kaydet", command=self.kaydet).pack(side="right")

    def _guncelle(self, _event=None):
        musteri = self.cari_map.get(self.girdiler["musteri"].get())
        tedarikci = self.cari_map.get(self.girdiler["tedarikci"].get())
        if musteri:
            self.musteri_bakiye.configure(
                text=f"Müşteri bakiyesi: {para_goster(self.bakiyeler.get(musteri.id, Decimal('0')))}"
            )
        if tedarikci:
            self.tedarikci_bakiye.configure(
                text=f"Tedarikçi bakiyesi: {para_goster(self.bakiyeler.get(tedarikci.id, Decimal('0')))}"
            )
        tutar_metin = self.girdiler["tutar"].get().strip()
        try:
            tutar = CariService._tutar(tutar_metin) if tutar_metin else Decimal("0")
        except ValueError:
            tutar = Decimal("0")
        banka = self.girdiler["banka"].get().strip() or "?"
        taksit = self.girdiler["taksit_sayisi"].get().strip() or "1"
        try:
            taksit_n = int(taksit)
        except ValueError:
            taksit_n = 0
        if musteri and tedarikci and tutar > 0:
            taksit_metin = "tek çekim" if taksit_n == 1 else f"{taksit} taksit"
            self.onizleme.configure(
                text=(
                    f"Önizleme: {para_goster(tutar)} ALACAK → {musteri.cari_kodu}  |  "
                    f"{para_goster(tutar)} BORÇ → {tedarikci.cari_kodu}  |  "
                    f"Banka: {banka} ({taksit_metin})"
                )
            )
        else:
            self.onizleme.configure(text="Önizleme: Müşteri, tedarikçi ve tutar girince çift kayıt görünür.")

    def kaydet(self):
        musteri = self.cari_map.get(self.girdiler["musteri"].get())
        tedarikci = self.cari_map.get(self.girdiler["tedarikci"].get())
        if not musteri or not tedarikci:
            messagebox.showwarning("Eksik bilgi", "Müşteri ve tedarikçi seçin.", parent=self)
            return
        if musteri.id == tedarikci.id:
            messagebox.showwarning("Geçersiz seçim", "Müşteri ve tedarikçi aynı olamaz.", parent=self)
            return
        banka = self.girdiler["banka"].get().strip()
        if not banka:
            messagebox.showwarning("Eksik banka", "Karın ait olduğu banka adını yazın.", parent=self)
            return
        try:
            tarih = datetime.strptime(self.girdiler["tarih"].get().strip(), "%d.%m.%Y").date()
            self.result = KkCekimiService.kaydet(
                musteri.id,
                tedarikci.id,
                tarih,
                self.girdiler["tutar"].get().strip(),
                banka,
                self.girdiler["taksit_sayisi"].get().strip(),
                self.girdiler["aciklama"].get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("Çekim kaydedilemedi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "KK çekim fişi",
            f"Fiş kaydedildi: {self.result.belge_no}\n"
            f"Alacak: {musteri.cari_kodu}  →  Borç: {tedarikci.cari_kodu}\n"
            f"Banka: {banka} / {self.result.taksit_sayisi} taksit",
            parent=self,
        )
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
        self.bilgi.pack(fill="x", padx=12, pady=(0, 4))
        ozet = ttk.Frame(self)
        ozet.pack(fill="x", padx=12, pady=(0, 8))
        self.toplam_kar_etiket = ttk.Label(ozet, text="Toplam Kâr: 0,00 TL", font=("Segoe UI", 11, "bold"))
        self.toplam_kar_etiket.pack(side="left", padx=(0, 24))
        self.kar_yuzdesi_etiket = ttk.Label(ozet, text="Kâr Yüzdesi: 0,0%", font=("Segoe UI", 11, "bold"))
        self.kar_yuzdesi_etiket.pack(side="left")
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

    def _belge_ozeti(self):
        fatura = getattr(self.parent_kart, "fatura", None)
        if fatura is not None:
            return f"Fatura: {fatura.fatura_no}"
        fatura_no = getattr(self.parent_kart, "fatura_no_alani", None)
        if fatura_no is not None:
            try:
                no = fatura_no.get().strip()
            except tk.TclError:
                no = ""
            return f"Fatura: {no or 'Yeni fatura'}"
        siparis = getattr(self.parent_kart, "siparis", None)
        return f"Sipariş: {siparis.siparis_no if siparis else 'Yeni sipariş'}"

    def _hesapla(self, veri, yontem):
        miktar = decimal(veri.get("miktar", 0), "Miktar")
        fiyat = decimal(veri.get("birim_satis_fiyati", 0), "Birim fiyat")
        iskonto = decimal(veri.get("iskonto_orani", 0), "İskonto")
        net = miktar * fiyat * (Decimal("1") - iskonto / Decimal("100"))
        alan = {"FIFO": "fifo_birim_maliyeti", "SON ALIŞ FİYATI": "son_alis_birim_maliyeti", "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti", "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti"}[yontem]
        maliyet = decimal(veri.get(alan, 0), "Maliyet")
        return miktar, fiyat, net, maliyet, miktar * maliyet, net - miktar * maliyet

    def yenile(self):
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
        renk = "#2e7d32" if kar_toplam > 0 else "#c62828" if kar_toplam < 0 else "#444444"
        musteri = self.parent_kart.musteri.get() if hasattr(self.parent_kart, "musteri") else ""
        self.bilgi.configure(
            text=(
                f"{self._belge_ozeti()}    Müşteri: {musteri or '-'}    Maliyet yöntemi: {yontem}\n"
                f"KDV hariç satış toplamı: {para_goster(net_toplam)}    Toplam maliyet: {para_goster(maliyet_toplam)}"
            ),
            foreground=renk,
        )
        self.toplam_kar_etiket.configure(text=f"Toplam Kâr: {para_goster(kar_toplam)}", foreground=renk)
        self.kar_yuzdesi_etiket.configure(text=f"Kâr Yüzdesi: {marj_toplam:.1f}%", foreground=renk)
        self.uyari.configure(text=f"Maliyet bulunamadı: {eksik} satır" if eksik else "")
        for yontem_adi in MALIYET_YONTEMLERI:
            bilinen_kar = Decimal("0"); bilinen_net = Decimal("0"); eksik_sayisi = 0
            for veri in self.parent_kart.satirlar:
                _, _, net, maliyet, _, kar = self._hesapla(veri, yontem_adi)
                if maliyet > 0: bilinen_net += net; bilinen_kar += kar
                else: eksik_sayisi += 1
            yontem_marj = bilinen_kar / bilinen_net * Decimal("100") if bilinen_net else Decimal("0")
            yontem_renk = "#2e7d32" if bilinen_kar > 0 else "#c62828" if bilinen_kar < 0 else "#444444"
            ttk.Label(
                self.karsilastirma,
                text=f"{yontem_adi}\nToplam Kâr: {para_goster(bilinen_kar)}\nKâr Yüzdesi: {yontem_marj:.1f}%\nEksik: {eksik_sayisi}",
                foreground=yontem_renk,
                font=("Segoe UI", 10, "bold"),
                padding=8,
            ).pack(side="left", expand=True, fill="x")


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
        widget = self.focus_get()
        query = widget.get().strip()
        if len(query) < 2:
            return
        if widget is self.satir_girdileri.get("urun_kodu"):
            ProductSelectionDialog(self, on_select=self.urun_secildi, kod=query)
        elif widget is self.satir_girdileri.get("urun_adi"):
            ProductSelectionDialog(self, on_select=self.urun_secildi, ad=query)
        else:
            ProductSelectionDialog(self, query, self.urun_secildi)

    def urun_secildi(self, values):
        for field, value in (("urun_kodu", values[0]), ("urun_adi", values[1]), ("birim", values[2] or "Adet"), ("birim_fiyat", values[4])):
            if field == "birim": self.satir_girdileri[field].set(value)
            else: self.satir_girdileri[field].delete(0, "end"); self.satir_girdileri[field].insert(0, value)

    def fiyat_secimi_ac(self, _event):
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(
            self, kod, on_select=self.fiyati_secildi, fiyat_turu="satis"
        )
        self.wait_window(dialog)
        try:
            self.satir_girdileri["birim_fiyat"].focus_set()
        except tk.TclError:
            pass
        return "break"

    def fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_fiyat"]
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)

    def satir_ekle(self):
        veri = {field: widget.get().strip() for field, widget in self.satir_girdileri.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]: messagebox.showwarning("Eksik bilgi", "Ürün kodu ve ürün adı zorunludur.", parent=self); return
        try: decimal(veri["miktar"], "Miktar", Decimal("0.0001")); decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
        except ValueError as hata: messagebox.showerror("Geçersiz satır", str(hata), parent=self); return
        secim = self.satir_tablosu.selection()
        if secim:
            eski = self.satirlar[int(secim[0])]
            veri["siparis_satiri_id"] = eski.get("siparis_satiri_id")
            veri["faturalanan_miktar"] = eski.get("faturalanan_miktar", 0)
            self.satirlar[int(secim[0])] = veri
        else:
            veri["siparis_satiri_id"] = None
            self.satirlar.append(veri)
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
        try: SatisIrsaliyesiService.kaydet({"irsaliye_tarihi": tarih, "cari_id": musteri.id, "siparis_id": self.siparis_map.get(self.siparis_secimi.get()).id if self.siparis_secimi.get() else None, "aciklama": self.girdiler["aciklama"].get().strip(), "ayrintili_notlar": self.notlar.get("1.0", "end").strip()}, self.satirlar, self.irsaliye.id if self.irsaliye else None)
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

        # Üstte sabit kayıt çubuğu + F1
        butonlar = ttk.Frame(self, padding=(10, 8, 10, 8))
        butonlar.pack(side="top", fill="x")
        ttk.Label(
            butonlar,
            text="Kayıt: F1",
            font=("Segoe UI", 10, "bold"),
            foreground="#1f6aa5",
        ).pack(side="left", padx=(0, 12))
        self.kaydet_btn = ttk.Button(butonlar, text="Kaydet (F1)", width=16, command=self.kaydet)
        self.kaydet_btn.pack(side="right", padx=4)
        ttk.Button(butonlar, text="Siparişi İptal Et", command=self.siparisi_iptal_et).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right", padx=4)
        self.bind("<F1>", self._f1_kaydet)
        self.bind_all("<F1>", self._f1_kaydet)

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
        if siparis:
            self._doldur()
        elif cari:
            musteri_anahtari = f"{cari.cari_kodu} - {cari.unvan}"
            if musteri_anahtari in self.musteri_map:
                self.musteri.set(musteri_anahtari)
                self._bakiye_guncelle()

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _f1_kaydet(self, _event=None):
        try:
            if not self.winfo_exists():
                return
            odak = self.focus_get()
            if odak is None:
                return
            w = odak
            while w is not None:
                if w == self:
                    self.kaydet()
                    return "break"
                w = w.master if hasattr(w, "master") else None
        except tk.TclError:
            return
        return "break"

    def destroy(self):
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        super().destroy()

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
        ttk.Label(parent, text="Maliyet Yöntemi").grid(row=0, column=2, padx=8, pady=5, sticky="w")
        yontem = ttk.Combobox(parent, textvariable=self.yontem, values=MALIYET_YONTEMLERI, state="readonly", width=28)
        yontem.grid(row=0, column=3, padx=8, pady=5, sticky="ew")
        ttk.Label(parent, text="Hedef Kâr Marjı %").grid(row=1, column=2, padx=8, pady=5, sticky="w")
        self.hedef_kar_marji = ttk.Entry(parent, width=30)
        self.hedef_kar_marji.grid(row=1, column=3, padx=8, pady=5, sticky="ew")
        self.hedef_kar_marji.insert(0, str(self.siparis.hedef_kar_marji if self.siparis else "0"))
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(3, weight=1)

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
        if widget not in (self.satir_girdileri["urun_kodu"], self.satir_girdileri["urun_adi"]):
            return
        sorgu = widget.get().strip()
        if len(sorgu) < 2:
            return
        if getattr(self, "_urun_arama_after", None):
            try:
                self.after_cancel(self._urun_arama_after)
            except tk.TclError:
                pass
        kod = sorgu if widget is self.satir_girdileri["urun_kodu"] else ""
        ad = sorgu if widget is self.satir_girdileri["urun_adi"] else ""
        self._urun_arama_after = self.after(350, lambda: self._urun_arama_ac(kod=kod, ad=ad))

    def _urun_arama_ac(self, kod="", ad=""):
        self._urun_arama_after = None
        if getattr(self, "_urun_sec_pencere", None) and self._urun_sec_pencere.winfo_exists():
            return
        dialog = ProductSelectionDialog(self, on_select=self.satir_urun_secildi, kod=kod, ad=ad)
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None

    def satir_urun_secildi(self, degerler):
        for alan, deger in (("urun_kodu", degerler[0]), ("urun_adi", degerler[1]), ("birim", degerler[2] or "Adet"), ("birim_satis_fiyati", degerler[4])):
            if alan == "birim":
                self.satir_girdileri[alan].set(deger)
            else:
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, deger)
        self.satir_tutar_guncelle()

    def satir_fiyat_secimi_ac(self, _event):
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(
            self, kod, on_select=self.satir_fiyati_secildi, fiyat_turu="satis"
        )
        self.wait_window(dialog)
        try:
            self.satir_girdileri["birim_satis_fiyati"].focus_set()
        except tk.TclError:
            pass
        return "break"

    def satir_fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_satis_fiyati"]
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)
        self.satir_tutar_guncelle()

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
            if isinstance(widget, ttk.Combobox):
                if alan == "birim":
                    widget.set("Adet")
                else:
                    widget.set("")
            else:
                widget.delete(0, "end")
        if "kdv_orani" in self.satir_girdileri:
            self.satir_girdileri["kdv_orani"].insert(0, "20")
        self.satir_tutar_guncelle()
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())

    def satir_formunu_doldur(self, veri):
        self.satir_formunu_temizle()
        for alan, widget in self.satir_girdileri.items():
            deger = veri.get(alan, "")
            if isinstance(widget, ttk.Combobox):
                if alan == "birim" and deger and deger not in BIRIM_SECENEKLERI:
                    widget["values"] = BIRIM_SECENEKLERI + (str(deger),)
                widget.set("" if deger is None else str(deger) or ("Adet" if alan == "birim" else ""))
            else:
                widget.delete(0, "end")
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
        self.hedef_kar_marji.delete(0, "end")
        self.hedef_kar_marji.insert(0, str(self.siparis.hedef_kar_marji))
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
        miktar = decimal(veri.get("miktar") or 0, "Miktar")
        fiyat = decimal(veri.get("birim_satis_fiyati") or 0, "Fiyat")
        iskonto = decimal(veri.get("iskonto_orani") or 0, "İskonto")
        kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
        maliyet_alan = {
            "FIFO": "fifo_birim_maliyeti",
            "SON ALIŞ FİYATI": "son_alis_birim_maliyeti",
            "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti",
            "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti",
        }[self.yontem.get()]
        maliyet = decimal(veri.get(maliyet_alan) or 0, "Maliyet")
        brut = miktar * fiyat
        indirim = brut * iskonto / 100
        net = brut - indirim
        toplam_maliyet = miktar * maliyet
        kar = net - toplam_maliyet
        return brut, indirim, net, net * kdv / 100, toplam_maliyet, kar, kar / net * 100 if net else Decimal("0")

    def _satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children(): self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            brut, indirim, net, kdv, maliyet, kar, marj = self._satir_hesapla(veri)
            acik = decimal(veri.get("miktar") or 0, "Miktar")
            irsaliye = decimal(veri.get("irsaliyelenen_miktar") or 0, "İrsaliyelenen miktar")
            fatura = decimal(veri.get("faturalanan_miktar") or 0, "Faturalanan miktar")
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(veri["urun_kodu"], veri["urun_adi"], veri.get("aciklama", ""), veri.get("miktar") or 0, veri["birim"], para_goster(veri.get("birim_satis_fiyati") or 0), f"{veri.get('iskonto_orani') or 0}%", f"{veri.get('kdv_orani') or 0}%", para_goster(net + kdv), irsaliye, fatura, acik - irsaliye))
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
        try:
            self._fatura_satir_baglantilari()
            self._fatura_satirlari_hazir = True
        except Exception as hata:
            messagebox.showerror(
                "Fatura satırları",
                f"Satır araçları kurulurken hata oluştu:\n{hata}",
                parent=self,
            )
        if fatura:
            self._faturayi_doldur()
        elif irsaliye:
            self._irsaliyeyi_doldur(irsaliye)
        elif siparis:
            self._siparis_kalanlarini_hazirla()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()

    def _siparis_kalanlarini_hazirla(self):
        """Siparişten faturaya çevirirken yalnızca faturalanmamış kalan miktarları alır."""
        kalan_satirlar = []
        for veri in self.satirlar:
            miktar = decimal(veri.get("miktar", 0), "Miktar")
            faturalanan = decimal(veri.get("faturalanan_miktar", 0), "Faturalanan miktar")
            kalan = miktar - faturalanan
            if kalan <= 0:
                continue
            yeni = dict(veri)
            yeni["miktar"] = kalan
            yeni["irsaliyelenen_miktar"] = decimal(veri.get("irsaliyelenen_miktar", 0), "İrsaliyelenen")
            yeni["faturalanan_miktar"] = Decimal("0")
            kalan_satirlar.append(yeni)
        self.satirlar = kalan_satirlar
        if not self.satirlar:
            messagebox.showinfo("Fatura", "Bu siparişte faturalanacak açık miktar kalmadı.", parent=self)
        self._satirlari_stokla_tamamla()
        self._satir_listesini_yenile()

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
        # Depo seçimini fatura satırlarının hemen üstüne yerleştir
        satir_cerceve = None
        for widget in self.icerik.winfo_children():
            try:
                baslik = str(widget.cget("text")).upper()
            except tk.TclError:
                continue
            if isinstance(widget, ttk.LabelFrame) and "SATIR" in baslik:
                satir_cerceve = widget
                break

        depo_bar = ttk.LabelFrame(self.icerik, text="STOK ÇIKIŞ DEPOSU", padding=8)
        if satir_cerceve is not None:
            depo_bar.pack(fill="x", pady=(4, 2), before=satir_cerceve)
        else:
            depo_bar.pack(fill="x", pady=4)

        ttk.Label(depo_bar, text="Ürün hangi depodan çıksın?").pack(side="left", padx=(0, 10))
        depolar = tuple(d.ad for d in StokService.depolar())
        self.depo = ttk.Combobox(depo_bar, values=depolar, state="readonly", width=32)
        self.depo.pack(side="left")
        if depolar:
            mevcut = self.fatura.depo if self.fatura and self.fatura.depo in depolar else depolar[0]
            self.depo.set(mevcut)
        else:
            self.depo.set("ANA DEPO")
        self.depo.bind("<<ComboboxSelected>>", self.depo_degisti)
        ttk.Button(depo_bar, text="Yeni Depo Aç", command=self.depo_ekle).pack(side="left", padx=10)
        ttk.Label(
            depo_bar,
            text="Satır eklerken lot ve stok bu depodan düşülür.",
            foreground="#666666",
        ).pack(side="left", padx=8)
        self.girdiler["depo"] = self.depo

        ek = ttk.LabelFrame(self.icerik, text="FATURA BAĞLANTI BİLGİLERİ", padding=8)
        onceki = [w for w in self.icerik.winfo_children() if w is not ek]
        if onceki:
            ek.pack(fill="x", pady=4, before=onceki[-1])
        else:
            ek.pack(fill="x", pady=4)

        # Otomatik satış fatura numarası (SRAY000001)
        ttk.Label(ek, text="Fatura Numarası").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.fatura_no_alani = ttk.Entry(ek, width=28, state="readonly")
        self.fatura_no_alani.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        otomatik_no = self.fatura.fatura_no if self.fatura else SatisFaturasiService.fatura_no()
        self.fatura_no_alani.configure(state="normal")
        self.fatura_no_alani.delete(0, "end")
        self.fatura_no_alani.insert(0, otomatik_no)
        self.fatura_no_alani.configure(state="readonly")

        ttk.Label(ek, text="İşlem Saati").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.islem_saati_alani = ttk.Entry(ek, width=12)
        self.islem_saati_alani.grid(row=0, column=3, padx=6, pady=4, sticky="w")
        saat_deger = saat_varsayilan(
            self.fatura.islem_saati if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        self.islem_saati_alani.insert(0, saat_deger)
        self.girdiler["islem_saati"] = self.islem_saati_alani

        # Sipariş / irsaliye numaraları
        ttk.Label(ek, text="Sipariş Numarası").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self.siparis_no = ttk.Entry(ek, width=28)
        self.siparis_no.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        ttk.Label(ek, text="İrsaliye Numarası").grid(row=1, column=2, padx=6, pady=4, sticky="w")
        self.irsaliye_no = ttk.Entry(ek, width=28)
        self.irsaliye_no.grid(row=1, column=3, padx=6, pady=4, sticky="ew")
        ttk.Button(ek, text="Cari Kartına Geç", command=self.cariye_git).grid(row=1, column=4, padx=6, sticky="w")

        # Doküman
        ttk.Label(ek, text="Doküman Ekle").grid(row=2, column=0, padx=6, pady=4, sticky="w")
        self.dokuman = ttk.Entry(ek, width=28)
        self.dokuman.grid(row=2, column=1, padx=6, pady=4, sticky="ew")
        ttk.Button(ek, text="Doküman Seç", command=self.dokuman_sec).grid(row=2, column=2, padx=6, sticky="w")

        # Vade gün
        ttk.Label(ek, text="Fatura Vadesi (Gün)").grid(row=3, column=0, padx=6, pady=4, sticky="w")
        self.vade_gunu = ttk.Entry(ek, width=12)
        self.vade_gunu.grid(row=3, column=1, padx=6, pady=4, sticky="w")
        self.vade_gunu.insert(0, str(self.fatura.vade_gunu if self.fatura else 0))
        self.vade_gunu.bind("<KeyRelease>", self.vade_gun_degisti)
        for widget in self.icerik.winfo_children():
            self._etiketi_degistir(widget, "Vade Tarihi", "Fatura Vadesi Tarihi")
            self._etiketi_degistir(widget, "Termin Tarihi", "Fatura Vadesi Tarihi")
        self._takvimli_tarih_yap("siparis_tarihi", self.vade_gun_degisti)
        self._takvimli_tarih_yap("termin_tarihi", self.vade_tarih_degisti)
        self.girdiler["termin_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.girdiler["siparis_tarihi"].bind("<FocusOut>", self.vade_gun_degisti)

        ozet = ttk.Frame(ek)
        ozet.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        self.yeni_bakiye_etiket = ttk.Label(
            ozet, text="Bu fatura ile yeni bakiye toplamı: -",
            foreground="#1f6aa5", font=("Segoe UI", 10, "bold"),
        )
        self.yeni_bakiye_etiket.pack(side="left", padx=(0, 24))
        self.ortalama_vade_etiket = ttk.Label(
            ozet, text="Bu fatura ile yeni bakiye ağırlıklı ortalama vadesi: -",
            foreground="#1f6aa5", font=("Segoe UI", 10, "bold"),
        )
        self.ortalama_vade_etiket.pack(side="left")

        for sutun in (1, 4):
            ek.columnconfigure(sutun, weight=1)
        self.girdiler["siparis_no"] = self.siparis_no
        self.girdiler["irsaliye_no"] = self.irsaliye_no
        self.girdiler["dokuman"] = self.dokuman
        if self.kaynak_siparis:
            self.siparis_no.insert(0, self.kaynak_siparis.siparis_no)
        if self.kaynak_irsaliye:
            self.irsaliye_no.insert(0, self.kaynak_irsaliye.irsaliye_no)
            if self.kaynak_irsaliye.siparis:
                self.siparis_no.delete(0, "end")
                self.siparis_no.insert(0, self.kaynak_irsaliye.siparis.siparis_no)

    def _takvimli_tarih_yap(self, alan, on_select=None):
        eski = self.girdiler.get(alan)
        if eski is None:
            return
        info = eski.grid_info()
        if not info:
            return
        parent = eski.master
        deger = eski.get()
        eski.destroy()
        cerceve = ttk.Frame(parent)
        cerceve.grid(
            row=int(info["row"]),
            column=int(info["column"]),
            sticky=info.get("sticky") or "ew",
            padx=info.get("padx") or 8,
            pady=info.get("pady") or 5,
        )
        entry = ttk.Entry(cerceve, width=28)
        entry.pack(side="left", fill="x", expand=True)
        entry.insert(0, deger)
        takvim_butonu(cerceve, entry, on_select=on_select)
        self.girdiler[alan] = entry
        return entry

    def _etiketi_degistir(self, parent, eski, yeni):
        try:
            if parent.cget("text") == eski:
                parent.configure(text=yeni)
        except tk.TclError:
            pass
        for cocuk in parent.winfo_children():
            self._etiketi_degistir(cocuk, eski, yeni)

    def _fatura_satir_baglantilari(self):
        butonlar = self.satir_tutar.master
        # Satır ekle butonunu net isimle göster
        for cocuk in butonlar.winfo_children():
            try:
                if cocuk.cget("text") == "Ekle/Güncelle":
                    cocuk.configure(text="Satır Ekle")
            except tk.TclError:
                pass

        # Barkod/lot önce oluşturulsun (ürün seçimi bunlara bağlı)
        ttk.Label(butonlar, text="Barkod:").pack(side="left", padx=(12, 2))
        self.satir_girdileri["barkod"] = ttk.Entry(butonlar, width=16)
        self.satir_girdileri["barkod"].pack(side="left")
        self.satir_girdileri["barkod"].bind("<Return>", self.barkoddan_satir_bul)
        ttk.Label(butonlar, text="Lot:").pack(side="left", padx=(8, 2))
        self.satir_girdileri["lot_no"] = ttk.Combobox(butonlar, width=18)
        self.satir_girdileri["lot_no"].pack(side="left")
        self.satir_girdileri["lot_no"].bind("<<ComboboxSelected>>", self.lot_cikis_otomatik)
        ttk.Label(butonlar, text="Lot Çıkışı:").pack(side="left", padx=(8, 2))
        self.satir_girdileri["lot_cikisi"] = ttk.Entry(butonlar, width=22)
        self.satir_girdileri["lot_cikisi"].pack(side="left")

        ttk.Button(butonlar, text="Satır Sil", command=self.satir_sil).pack(side="left", padx=6)
        ttk.Label(butonlar, text="Silinecek satır:").pack(side="left", padx=(10, 2))
        self.satir_sil_secim = ttk.Combobox(butonlar, state="readonly", width=36)
        self.satir_sil_secim.pack(side="left", padx=(0, 6))
        ttk.Button(butonlar, text="STOK LİSTESİ", command=self.stok_listesi_ac).pack(side="left", padx=6)
        self._satir_isaretleri = set()
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        if hasattr(self, "_satir_secim_kutusu_tikla"):
            self.satir_tablosu.bind("<Button-1>", self._satir_secim_kutusu_tikla, add="+")

        fiyat = self.satir_girdileri["birim_satis_fiyati"]
        fiyat.bind("<F10>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<KeyPress-y>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<KeyPress-Y>", self.fatura_fiyat_secimi_ac)
        ttk.Label(butonlar, text="(Fiyat: F10 / Y | Kayıt satırı: Satır Ekle)", foreground="#666666").pack(side="left", padx=8)

        # Varsayılan iskonto
        if "iskonto_orani" in self.satir_girdileri and not self.satir_girdileri["iskonto_orani"].get().strip():
            self.satir_girdileri["iskonto_orani"].insert(0, "0")

        # Kâr analizi butonunu netleştir
        if hasattr(self, "satir_ozet"):
            for cocuk in self.satir_ozet.master.winfo_children():
                try:
                    if "KÂRLILIK" in cocuk.cget("text") or "KAR" in cocuk.cget("text").upper():
                        cocuk.configure(text="KAR ANALİZİ")
                except tk.TclError:
                    pass

        kolonlar = (
            "sec", "barkod", "urun_kodu", "urun_adi", "aciklama", "miktar", "birim", "fiyat",
            "iskonto", "kdv", "lot", "lot_cikisi", "toplam", "irsaliye", "fatura", "acik",
        )
        self.satir_tablosu.configure(columns=kolonlar, selectmode="browse")
        basliklar = {
            "sec": "Seç", "barkod": "Barkod", "urun_kodu": "Ürün Kodu", "urun_adi": "Ürün Adı",
            "aciklama": "Açıklama", "miktar": "Miktar", "birim": "Birim", "fiyat": "Birim Fiyat",
            "iskonto": "İskonto", "kdv": "KDV", "lot": "Lot No", "lot_cikisi": "Lot Çıkışı",
            "toplam": "Satır Toplamı", "irsaliye": "Siparişten Gelen", "fatura": "İrsaliyeden Gelen",
            "acik": "Fatura Miktarı",
        }
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            self.satir_tablosu.column(kolon, width=105, anchor="w")
        self.satir_tablosu.column("sec", width=45, anchor="center", stretch=False)
        self.satir_tablosu.column("urun_adi", width=260)
        self.satir_tablosu.column("barkod", width=120)
        self._satir_sil_listesini_yenile()

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
        if not cari:
            messagebox.showinfo("Cari", "Önce müşteri seçin.", parent=self)
            return
        if self.cari_ac:
            self.cari_ac(cari)
        else:
            dialog = CariDialog(self, cari)
            self.wait_window(dialog)

    def barkoddan_satir_bul(self, _event=None):
        barkod = self.satir_girdileri["barkod"].get().strip()
        if not barkod:
            return "break"
        bulunan = [s for s in StokService.stoklari_ara(barkod) if (s.barkod or "").strip() == barkod]
        if not bulunan:
            bulunan = StokService.stoklari_ara(barkod)
        if not bulunan:
            messagebox.showinfo("Barkod", "Bu barkoda ait stok bulunamadı.", parent=self)
            return "break"
        stok = bulunan[0]
        fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
        self.satir_urun_secildi((stok.stok_kodu, stok.stok_adi, stok.birim, "", str(fiyat)))
        return "break"

    def lot_cikis_otomatik(self, _event=None):
        lot = self.satir_girdileri["lot_no"].get().strip()
        self.satir_girdileri["lot_cikisi"].delete(0, "end")
        if lot:
            self.satir_girdileri["lot_cikisi"].insert(0, lot)

    def stok_listesi_ac(self):
        ProductSelectionDialog(
            self,
            on_select=self.satir_urun_secildi,
            kod=self.satir_girdileri["urun_kodu"].get().strip(),
            ad=self.satir_girdileri["urun_adi"].get().strip(),
        )

    def satir_urun_secildi(self, degerler):
        kod = (degerler[0] or "").strip()
        for alan, deger in (
            ("urun_kodu", kod),
            ("urun_adi", degerler[1]),
            ("birim", degerler[2] or "Adet"),
        ):
            if alan == "birim":
                self.satir_girdileri[alan].set(deger)
            else:
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, deger)

        fiyat = StokService.satis_fiyati_1(kod)
        if fiyat == 0 and len(degerler) > 4 and str(degerler[4]).strip():
            try:
                fiyat = decimal(degerler[4], "Fiyat", Decimal("0"))
            except ValueError:
                fiyat = Decimal("0")
        self.satir_girdileri["birim_satis_fiyati"].delete(0, "end")
        self.satir_girdileri["birim_satis_fiyati"].insert(0, f"{fiyat:f}".rstrip("0").rstrip(".") or "0")

        if "barkod" in self.satir_girdileri:
            self.satir_girdileri["barkod"].delete(0, "end")
            bulunan = StokService.stoklari_ara(kod)
            stok = next((s for s in bulunan if s.stok_kodu == kod), None)
            if stok and stok.barkod:
                self.satir_girdileri["barkod"].insert(0, stok.barkod)
        if not self.satir_girdileri["miktar"].get().strip():
            self.satir_girdileri["miktar"].insert(0, "1")
        if "iskonto_orani" in self.satir_girdileri and not self.satir_girdileri["iskonto_orani"].get().strip():
            self.satir_girdileri["iskonto_orani"].insert(0, "0")
        if "kdv_orani" in self.satir_girdileri and not self.satir_girdileri["kdv_orani"].get().strip():
            self.satir_girdileri["kdv_orani"].insert(0, "20")
        if "lot_no" in self.satir_girdileri:
            self.lotlari_yukle()
            self.lot_cikis_otomatik()
        self.satir_tutar_guncelle()
        # Forma doldur; satıra aktarım yalnızca "Satır Ekle" ile (yeni satır)
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        try:
            self.satir_girdileri["miktar"].focus_set()
        except tk.TclError:
            pass

    def lotlari_yukle(self):
        if "lot_no" not in self.satir_girdileri:
            return
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        lotlar = StokService.lotlar(kod, self.depo.get()) if kod and self.depo.get() else []
        self.satir_girdileri["lot_no"]["values"] = tuple(lot.lot_no for lot in lotlar)
        if lotlar:
            self.satir_girdileri["lot_no"].set(lotlar[0].lot_no)
            self.lot_cikis_otomatik()
        else:
            self.satir_girdileri["lot_no"].set("")
            if "lot_cikisi" in self.satir_girdileri:
                self.satir_girdileri["lot_cikisi"].delete(0, "end")
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
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(
            self, kod, on_select=self.fatura_fiyati_secildi, fiyat_turu="satis"
        )
        self.wait_window(dialog)
        try:
            self.satir_girdileri["birim_satis_fiyati"].focus_set()
        except tk.TclError:
            pass
        return "break"

    def fatura_fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_satis_fiyati"]
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)
        self.satir_tutar_guncelle()
        self.after_idle(lambda: self.satir_girdileri["birim_satis_fiyati"].focus_set())

    def satir_kaydet(self):
        """Satır Ekle: her zaman yeni satır ekler (seçim güncelleme yapmaz)."""
        def _bos_ise_yaz(alan, varsayilan):
            if alan in self.satir_girdileri and not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, varsayilan)

        _bos_ise_yaz("miktar", "1")
        _bos_ise_yaz("iskonto_orani", "0")
        _bos_ise_yaz("kdv_orani", "20")

        veri = {alan: widget.get().strip() for alan, widget in self.satir_girdileri.items()}
        if not veri.get("urun_kodu") or not veri.get("urun_adi"):
            messagebox.showwarning("Eksik bilgi", "Önce stok seçin, sonra Satır Ekle'ye basın.", parent=self)
            return
        varsayilanlar = {
            "miktar": "1",
            "birim_satis_fiyati": "0",
            "iskonto_orani": "0",
            "kdv_orani": "20",
        }
        for alan, varsayilan in varsayilanlar.items():
            if not str(veri.get(alan, "")).strip():
                veri[alan] = varsayilan
            try:
                veri[alan] = str(decimal(veri[alan] or 0, alan, Decimal("0")))
            except ValueError as hata:
                messagebox.showerror("Geçersiz satır", str(hata), parent=self)
                return
        for alan in (
            "fifo_birim_maliyeti",
            "son_alis_birim_maliyeti",
            "ortalama_birim_maliyeti",
            "agirlikli_ortalama_birim_maliyeti",
        ):
            veri[alan] = veri.get(alan) or "0"
        veri.setdefault("barkod", "")
        veri.setdefault("lot_no", "")
        veri.setdefault("lot_cikisi", "")
        veri.setdefault("irsaliyelenen_miktar", 0)
        veri.setdefault("faturalanan_miktar", 0)

        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        self.satirlar.append(veri)
        self._satirlari_stokla_tamamla()
        self.satir_formunu_temizle()
        _bos_ise_yaz("iskonto_orani", "0")
        _bos_ise_yaz("kdv_orani", "20")
        self._fatura_satirlari_hazir = True
        self._satir_listesini_yenile()
        self._toplamlari_guncelle()

    def _satir_sil_listesini_yenile(self):
        if not hasattr(self, "satir_sil_secim"):
            return
        degerler = []
        for sira, veri in enumerate(self.satirlar):
            degerler.append(f"{sira + 1}) {veri.get('urun_kodu', '')} - {veri.get('urun_adi', '')}")
        self.satir_sil_secim["values"] = degerler
        if degerler:
            mevcut = self.satir_sil_secim.get()
            if mevcut not in degerler:
                self.satir_sil_secim.set(degerler[-1])
        else:
            self.satir_sil_secim.set("")

    def _satir_secim_kutusu_tikla(self, event):
        """Seç sütununa tıklayınca satırı işaretle / kaldır."""
        tablo = self.satir_tablosu
        if tablo.identify_region(event.x, event.y) != "cell":
            return
        if tablo.identify_column(event.x) != "#1":
            return
        satir = tablo.identify_row(event.y)
        if not satir:
            return
        idx = int(satir)
        if not hasattr(self, "_satir_isaretleri"):
            self._satir_isaretleri = set()
        if idx in self._satir_isaretleri:
            self._satir_isaretleri.discard(idx)
        else:
            self._satir_isaretleri.add(idx)
        self._satir_listesini_yenile()
        try:
            tablo.selection_set(satir)
            tablo.focus(satir)
        except tk.TclError:
            pass
        if hasattr(self, "satir_sil_secim") and 0 <= idx < len(self.satirlar):
            self.satir_sil_secim.set(
                f"{idx + 1}) {self.satirlar[idx].get('urun_kodu', '')} - {self.satirlar[idx].get('urun_adi', '')}"
            )
        return "break"

    def satir_sil(self):
        indeksler = set()
        # 1) İşaretli satırlar
        if getattr(self, "_satir_isaretleri", None):
            indeksler |= {i for i in self._satir_isaretleri if 0 <= i < len(self.satirlar)}
        # 2) Üstteki seçim kutusu
        if hasattr(self, "satir_sil_secim"):
            metin = self.satir_sil_secim.get().strip()
            if metin and ")" in metin:
                try:
                    indeksler.add(int(metin.split(")", 1)[0]) - 1)
                except ValueError:
                    pass
        # 3) Tabloda seçili satır
        for iid in self.satir_tablosu.selection():
            try:
                indeksler.add(int(iid))
            except ValueError:
                pass
        indeksler = {i for i in indeksler if 0 <= i < len(self.satirlar)}
        if not indeksler:
            messagebox.showinfo(
                "Satır sil",
                "Silmek için satırın başındaki Seç kutusunu işaretleyin veya üstteki 'Silinecek satır' listesinden seçin.",
                parent=self,
            )
            return
        adet = len(indeksler)
        if not messagebox.askyesno("Satır sil", f"{adet} satır silinsin mi?", parent=self):
            return
        for idx in sorted(indeksler, reverse=True):
            self.satirlar.pop(idx)
        self._satir_isaretleri = set()
        self.satir_formunu_temizle()
        self._satir_listesini_yenile()
        self._toplamlari_guncelle()

    def _satir_listesini_yenile(self):
        if not hasattr(self, "satir_tablosu"):
            return
        if not self._fatura_satirlari_hazir:
            return SatisSiparisiDialog._satir_listesini_yenile(self)
        if not hasattr(self, "_satir_isaretleri"):
            self._satir_isaretleri = set()
        # Geçersiz işaretleri temizle
        self._satir_isaretleri = {i for i in self._satir_isaretleri if 0 <= i < len(self.satirlar)}
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            _, _, net, kdv, _, _, _ = self._satir_hesapla(veri)
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            isaret = "☑" if sira in self._satir_isaretleri else "☐"
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                isaret,
                veri.get("barkod", ""),
                veri.get("urun_kodu", ""),
                veri.get("urun_adi", ""),
                veri.get("aciklama", ""),
                miktar,
                veri.get("birim", ""),
                para_goster(veri.get("birim_satis_fiyati") or 0),
                f"{veri.get('iskonto_orani') or 0}%",
                f"{veri.get('kdv_orani') or 0}%",
                veri.get("lot_no", ""),
                veri.get("lot_cikisi", ""),
                para_goster(net + kdv),
                veri.get("irsaliyelenen_miktar") or 0,
                veri.get("faturalanan_miktar") or 0,
                miktar,
            ))
        self._satir_sil_listesini_yenile()
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self, borc=None):
        super()._toplamlari_guncelle(borc)
        if not hasattr(self, "ortalama_vade_etiket"):
            return
        cari = self.musteri_map.get(self.musteri.get())
        if not cari:
            self.yeni_bakiye_etiket.configure(text="Bu fatura ile yeni bakiye toplamı: -")
            self.ortalama_vade_etiket.configure(text="Bu fatura ile yeni bakiye ağırlıklı ortalama vadesi: -")
            return
        try:
            vade = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            vade = date.today()
        toplam = Decimal("0")
        for veri in self.satirlar:
            _, _, net, kdv, _, _, _ = self._satir_hesapla(veri)
            toplam += net + kdv
        tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0"))
        acik = max(Decimal("0"), toplam - tahsilat)
        ozet = SatisFaturasiService.bakiye_ozeti(
            cari.id, acik, vade, self.fatura.fatura_no if self.fatura else None
        )
        self.yeni_bakiye_etiket.configure(
            text=f"Bu fatura ile yeni bakiye toplamı: {para_goster(ozet['bakiye'])}"
        )
        self.ortalama_vade_etiket.configure(
            text=(
                "Bu fatura ile yeni bakiye ağırlıklı ortalama vadesi: "
                f"{tarih_goster(ozet['ortalama_vade']) if ozet['ortalama_vade'] else '-'}"
            )
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
        self._entry_yaz(
            "islem_saati",
            saat_varsayilan(fatura.islem_saati or fatura.olusturma_tarihi.strftime("%H:%M")),
        )
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
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get() if "islem_saati" in self.girdiler else "")
            satirlar = []
            for satir in self.satirlar:
                veri = dict(satir)
                veri["birim_fiyat"] = veri.get("birim_satis_fiyati", 0)
                satirlar.append(veri)
            tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0"))
            ilk_tahsilat = self.tahsilatlar[0] if self.tahsilatlar else {}
            siparis_id = self.kaynak_siparis.id if self.kaynak_siparis else (self.fatura.siparis_id if self.fatura else None)
            irsaliye_id = self.kaynak_irsaliye.id if self.kaynak_irsaliye else (self.fatura.irsaliye_id if self.fatura else None)
            if not siparis_id and self.kaynak_irsaliye and self.kaynak_irsaliye.siparis_id:
                siparis_id = self.kaynak_irsaliye.siparis_id
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
                "fatura_no": self.fatura_no_alani.get().strip() if hasattr(self, "fatura_no_alani") else None,
                "fatura_tarihi": fatura_tarihi,
                "islem_saati": islem_saati,
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


class SatisIadeFaturasiDialog(tk.Toplevel):
    """Satış iade faturası — müşterinin önceki alış fiyatını gösterir."""

    def __init__(self, parent, iade=None, kaynak_fatura=None):
        super().__init__(parent)
        self.iade = iade
        self.kaynak_fatura = kaynak_fatura
        self.result = None
        self.satirlar = []
        self.title("Satış İade Faturası")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.transient(parent)
        self.grab_set()

        self.musteriler = SatisIadeFaturasiService.aktif_musterileri()
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}

        ust = ttk.LabelFrame(self, text="İADE BİLGİLERİ", padding=10)
        ust.pack(fill="x", padx=12, pady=8)
        ttk.Label(ust, text="İade No").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.iade_no = ttk.Entry(ust, width=28)
        self.iade_no.grid(row=0, column=1, padx=4, pady=4)
        self.iade_no.insert(0, iade.iade_no if iade else "Otomatik")
        self.iade_no.configure(state="readonly")
        ttk.Label(ust, text="İade Tarihi").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.tarih = ttk.Entry(ust, width=16)
        self.tarih.grid(row=0, column=3, padx=4, pady=4)
        self.tarih.insert(0, tarih_goster(iade.iade_tarihi if iade else date.today()))
        ttk.Label(ust, text="Müşteri").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.musteri = ttk.Combobox(ust, values=list(self.musteri_map), state="readonly", width=40)
        self.musteri.grid(row=1, column=1, columnspan=2, padx=4, pady=4, sticky="ew")
        self.musteri.bind("<<ComboboxSelected>>", self.musteri_degisti)
        ttk.Label(ust, text="Kaynak Satış Faturası").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.kaynak = ttk.Combobox(ust, state="readonly", width=40)
        self.kaynak.grid(row=2, column=1, columnspan=2, padx=4, pady=4, sticky="ew")
        self.kaynak.bind("<<ComboboxSelected>>", self.kaynak_fatura_secildi)
        ttk.Button(ust, text="Faturadan Satırları Getir", command=self.kaynak_satirlari_yukle).grid(row=2, column=3, padx=4)
        ttk.Label(ust, text="Depo").grid(row=3, column=0, sticky="w", padx=4, pady=4)
        depolar = tuple(d.ad for d in StokService.depolar())
        self.depo = ttk.Combobox(ust, values=depolar, state="readonly", width=26)
        self.depo.grid(row=3, column=1, padx=4, pady=4, sticky="w")
        if depolar:
            self.depo.set(iade.depo if iade else depolar[0])
        ttk.Label(ust, text="Açıklama").grid(row=3, column=2, sticky="w", padx=4, pady=4)
        self.aciklama = ttk.Entry(ust, width=36)
        self.aciklama.grid(row=3, column=3, padx=4, pady=4, sticky="ew")
        if iade and iade.aciklama:
            self.aciklama.insert(0, iade.aciklama)

        gecmis = ttk.LabelFrame(self, text="MÜŞTERİ ÜRÜN GEÇMİŞİ (daha önce aldı mı / kaçtan?)", padding=8)
        gecmis.pack(fill="x", padx=12, pady=4)
        self.gecmis_bilgi = ttk.Label(gecmis, text="Ürün seçince müşterinin önceki alışları burada görünür.", foreground="#1f6aa5")
        self.gecmis_bilgi.pack(anchor="w", pady=(0, 4))
        self.gecmis_tablo = ttk.Treeview(
            gecmis, columns=("fatura", "tarih", "miktar", "fiyat", "net", "fifo"), show="headings", height=4
        )
        for kolon, baslik, genislik in (
            ("fatura", "Fatura No", 130), ("tarih", "Tarih", 85),
            ("miktar", "Miktar", 70), ("fiyat", "Birim Fiyat", 100),
            ("net", "Net Alış", 100), ("fifo", "FIFO Maliyet", 100),
        ):
            self.gecmis_tablo.heading(kolon, text=baslik)
            self.gecmis_tablo.column(kolon, width=genislik)
        self.gecmis_tablo.pack(fill="x")
        self.gecmis_tablo.bind("<Double-1>", self.gecmisten_fiyat_al)
        ttk.Label(
            gecmis,
            text="İade stoğa FIFO ile girer: önce satıştaki lotlara geri yazılır; olmazsa satış FIFO maliyetiyle yeni lot açılır.",
            foreground="#666666",
        ).pack(anchor="w", pady=(4, 0))

        satir_frame = ttk.LabelFrame(self, text="İADE SATIRLARI", padding=8)
        satir_frame.pack(fill="both", expand=True, padx=12, pady=4)
        form = ttk.Frame(satir_frame)
        form.pack(fill="x")
        self.satir_girdileri = {}
        for sutun, (etiket, alan) in enumerate((
            ("Ürün Kodu", "urun_kodu"), ("Ürün Adı", "urun_adi"), ("Miktar", "miktar"),
            ("Birim", "birim"), ("İade Fiyatı", "birim_fiyat"), ("KDV %", "kdv_orani"),
        )):
            ttk.Label(form, text=etiket).grid(row=0, column=sutun, padx=3, sticky="w")
            widget = ttk.Combobox(form, values=BIRIM_SECENEKLERI, state="readonly", width=8) if alan == "birim" else ttk.Entry(form, width=14 if alan != "urun_adi" else 28)
            widget.grid(row=1, column=sutun, padx=3, pady=2)
            self.satir_girdileri[alan] = widget
            if alan in ("urun_kodu", "urun_adi"):
                widget.bind("<KeyRelease>", self.urun_arama)
                widget.bind("<FocusOut>", self.urun_gecmisini_goster)
        self.satir_girdileri["birim"].set("Adet")
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        self.satir_girdileri["miktar"].insert(0, "1")
        ttk.Button(form, text="Satır Ekle", command=self.satir_ekle).grid(row=1, column=6, padx=8)
        ttk.Button(form, text="Stok Listesi", command=self.stok_listesi).grid(row=1, column=7, padx=4)

        self.satir_tablosu = ttk.Treeview(
            satir_frame,
            columns=("kod", "ad", "miktar", "birim", "fiyat", "onceki", "fifo", "kaynak", "kdv", "toplam"),
            show="headings",
        )
        for kolon, baslik, genislik in (
            ("kod", "Ürün Kodu", 95), ("ad", "Ürün Adı", 180), ("miktar", "Miktar", 65),
            ("birim", "Birim", 55), ("fiyat", "İade Fiyatı", 95), ("onceki", "Önceki Alış", 95),
            ("fifo", "FIFO Maliyet", 95), ("kaynak", "Kaynak Fatura", 120),
            ("kdv", "KDV", 55), ("toplam", "Toplam", 100),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=genislik)
        self.satir_tablosu.pack(fill="both", expand=True, pady=6)
        ttk.Button(satir_frame, text="Seçili Satırı Kaldır", command=self.satir_kaldir).pack(anchor="w")

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=8)
        self.toplam_etiket = ttk.Label(alt, text="Genel Toplam: 0,00 TL", font=("Segoe UI", 11, "bold"))
        self.toplam_etiket.pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="İade Faturasını Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if iade:
            self._iadeyi_doldur()
        elif kaynak_fatura:
            anahtar = f"{kaynak_fatura.cari.cari_kodu} - {kaynak_fatura.cari.unvan}"
            if anahtar in self.musteri_map:
                self.musteri.set(anahtar)
            self.musteri_degisti()
            self.kaynak.set(kaynak_fatura.fatura_no)
            self.kaynak_satirlari_yukle()

    def musteri_degisti(self, _event=None):
        musteri = self.musteri_map.get(self.musteri.get())
        self.kaynak.set("")
        if not musteri:
            self.kaynak["values"] = ()
            return
        faturalar = SatisIadeFaturasiService.musteri_satislari(musteri.id)
        self.kaynak_map = {f.fatura_no: f for f in faturalar}
        self.kaynak["values"] = list(self.kaynak_map)

    def kaynak_fatura_secildi(self, _event=None):
        pass

    def kaynak_satirlari_yukle(self):
        fatura = getattr(self, "kaynak_map", {}).get(self.kaynak.get())
        if not fatura:
            messagebox.showinfo("Kaynak fatura", "Önce müşteri ve satış faturası seçin.", parent=self)
            return
        self.satirlar.clear()
        for satir in fatura.satirlar:
            indirim = satir.birim_fiyat * satir.iskonto_orani / Decimal("100")
            net = satir.birim_fiyat - indirim
            self.satirlar.append({
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "miktar": satir.miktar,
                "birim": satir.birim,
                "birim_fiyat": net,
                "iskonto_orani": 0,
                "kdv_orani": satir.kdv_orani,
                "onceki_alis_fiyati": net,
                "onceki_fatura_no": fatura.fatura_no,
                "kaynak_fatura_satiri_id": satir.id,
                "fifo_birim_maliyeti": satir.fifo_birim_maliyeti,
            })
        self.satir_listesini_yenile()
        self.gecmis_bilgi.configure(
            text=f"{fatura.fatura_no} faturasından {len(self.satirlar)} satır iade için yüklendi."
        )

    def urun_arama(self, _event=None):
        widget = self.focus_get()
        if widget not in (self.satir_girdileri["urun_kodu"], self.satir_girdileri["urun_adi"]):
            return
        sorgu = widget.get().strip()
        if len(sorgu) < 2:
            return
        if widget is self.satir_girdileri["urun_kodu"]:
            ProductSelectionDialog(self, on_select=self.urun_secildi, kod=sorgu)
        else:
            ProductSelectionDialog(self, on_select=self.urun_secildi, ad=sorgu)

    def stok_listesi(self):
        ProductSelectionDialog(
            self,
            on_select=self.urun_secildi,
            kod=self.satir_girdileri["urun_kodu"].get().strip(),
            ad=self.satir_girdileri["urun_adi"].get().strip(),
        )

    def urun_secildi(self, degerler):
        for alan, deger in (("urun_kodu", degerler[0]), ("urun_adi", degerler[1]), ("birim", degerler[2] or "Adet"), ("birim_fiyat", degerler[4])):
            if alan == "birim":
                self.satir_girdileri[alan].set(deger)
            else:
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, deger)
        self.urun_gecmisini_goster()

    def urun_gecmisini_goster(self, _event=None):
        musteri = self.musteri_map.get(self.musteri.get())
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        for item in self.gecmis_tablo.get_children():
            self.gecmis_tablo.delete(item)
        if not musteri or not kod:
            self.gecmis_bilgi.configure(text="Ürün seçince müşterinin önceki alışları burada görünür.")
            return
        ozet = SatisIadeFaturasiService.musteri_urun_gecmisi(musteri.id, kod)
        if not ozet["aldi"]:
            self.gecmis_bilgi.configure(
                text=f"⚠ Bu müşteri '{kod}' ürününü daha önce satın almamış.",
                foreground="#c62828",
            )
            return
        self.gecmis_bilgi.configure(
            text=(
                f"✓ Bu müşteri bu ürünü {ozet['adet']} kez almış. "
                f"Son alış: {para_goster(ozet['son_fiyat'])} | "
                f"Ortalama: {para_goster(ozet['ortalama_fiyat'])} | "
                f"Son FIFO maliyet: {para_goster(ozet['gecmis'][0]['fifo_birim_maliyeti'])}  "
                f"(Çift tıkla → iade fiyatı + FIFO maliyet uygula)"
            ),
            foreground="#2e7d32",
        )
        self._gecmis_kayitlari = ozet["gecmis"]
        for sira, g in enumerate(ozet["gecmis"]):
            self.gecmis_tablo.insert("", "end", iid=str(sira), values=(
                g["fatura_no"], tarih_goster(g["tarih"]), g["miktar"],
                para_goster(g["birim_fiyat"]), para_goster(g["net_fiyat"]),
                para_goster(g["fifo_birim_maliyeti"]),
            ))
        if not self.satir_girdileri["birim_fiyat"].get().strip() or self.satir_girdileri["birim_fiyat"].get() in ("0", "0.0"):
            self.satir_girdileri["birim_fiyat"].delete(0, "end")
            self.satir_girdileri["birim_fiyat"].insert(0, str(ozet["son_fiyat"]))
        self._secili_gecmis = ozet["gecmis"][0]

    def gecmisten_fiyat_al(self, _event=None):
        secim = self.gecmis_tablo.selection()
        if not secim or not hasattr(self, "_gecmis_kayitlari"):
            return
        g = self._gecmis_kayitlari[int(secim[0])]
        self.satir_girdileri["birim_fiyat"].delete(0, "end")
        self.satir_girdileri["birim_fiyat"].insert(0, str(g["net_fiyat"]))
        self._secili_gecmis = g

    def satir_ekle(self):
        musteri = self.musteri_map.get(self.musteri.get())
        if not musteri:
            messagebox.showwarning("Eksik bilgi", "Önce müşteri seçin.", parent=self)
            return
        veri = {alan: w.get().strip() for alan, w in self.satir_girdileri.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]:
            messagebox.showwarning("Eksik bilgi", "Ürün kodu ve adı zorunlu.", parent=self)
            return
        try:
            decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
            decimal(veri["birim_fiyat"], "Fiyat", Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        ozet = SatisIadeFaturasiService.musteri_urun_gecmisi(musteri.id, veri["urun_kodu"])
        onceki = None
        onceki_no = None
        fifo = None
        kaynak_satir_id = None
        if hasattr(self, "_secili_gecmis"):
            onceki = self._secili_gecmis["net_fiyat"]
            onceki_no = self._secili_gecmis["fatura_no"]
            fifo = self._secili_gecmis.get("fifo_birim_maliyeti")
            kaynak_satir_id = self._secili_gecmis.get("satir_id")
        elif ozet["aldi"]:
            onceki = ozet["son_fiyat"]
            onceki_no = ozet["gecmis"][0]["fatura_no"]
            fifo = ozet["gecmis"][0].get("fifo_birim_maliyeti")
            kaynak_satir_id = ozet["gecmis"][0].get("satir_id")
        if fifo in (None, ""):
            fifo = StokService.maliyetler(veri["urun_kodu"], self.depo.get() or "ANA DEPO").get("fifo", 0)
        self.satirlar.append({
            "urun_kodu": veri["urun_kodu"],
            "urun_adi": veri["urun_adi"],
            "miktar": veri["miktar"],
            "birim": veri["birim"] or "Adet",
            "birim_fiyat": veri["birim_fiyat"],
            "iskonto_orani": 0,
            "kdv_orani": veri["kdv_orani"] or 20,
            "onceki_alis_fiyati": onceki,
            "onceki_fatura_no": onceki_no,
            "kaynak_fatura_satiri_id": kaynak_satir_id,
            "fifo_birim_maliyeti": fifo,
        })
        self.satir_listesini_yenile()
        for alan, w in self.satir_girdileri.items():
            if alan == "birim":
                w.set("Adet")
            else:
                w.delete(0, "end")
        self.satir_girdileri["kdv_orani"].insert(0, "20")
        self.satir_girdileri["miktar"].insert(0, "1")
        if hasattr(self, "_secili_gecmis"):
            del self._secili_gecmis

    def satir_kaldir(self):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satirlar.pop(int(secim[0]))
            self.satir_listesini_yenile()

    def satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        genel = Decimal("0")
        for sira, veri in enumerate(self.satirlar):
            miktar = decimal(veri["miktar"], "Miktar")
            fiyat = decimal(veri["birim_fiyat"], "Fiyat")
            kdv = decimal(veri.get("kdv_orani", 20), "KDV")
            net = miktar * fiyat
            toplam = net * (Decimal("1") + kdv / Decimal("100"))
            genel += toplam
            onceki = veri.get("onceki_alis_fiyati")
            fifo = veri.get("fifo_birim_maliyeti")
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                veri["urun_kodu"], veri["urun_adi"], miktar, veri["birim"],
                para_goster(fiyat),
                para_goster(onceki) if onceki not in (None, "") else "—",
                para_goster(fifo) if fifo not in (None, "") else "—",
                veri.get("onceki_fatura_no") or "",
                f"{kdv}%", para_goster(toplam),
            ))
        self.toplam_etiket.configure(text=f"Genel Toplam: {para_goster(genel)}")

    def _iadeyi_doldur(self):
        iade = self.iade
        anahtar = f"{iade.cari.cari_kodu} - {iade.cari.unvan}"
        if anahtar in self.musteri_map:
            self.musteri.set(anahtar)
        self.musteri_degisti()
        if iade.kaynak_fatura:
            self.kaynak.set(iade.kaynak_fatura.fatura_no)
        self.depo.set(iade.depo)
        for satir in iade.satirlar:
            self.satirlar.append({
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "miktar": satir.miktar,
                "birim": satir.birim,
                "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
                "onceki_alis_fiyati": satir.onceki_alis_fiyati,
                "onceki_fatura_no": satir.onceki_fatura_no,
                "kaynak_fatura_satiri_id": satir.kaynak_fatura_satiri_id,
                "fifo_birim_maliyeti": satir.fifo_birim_maliyeti,
            })
        self.satir_listesini_yenile()

    def kaydet(self):
        musteri = self.musteri_map.get(self.musteri.get())
        if not musteri:
            messagebox.showwarning("Eksik bilgi", "Müşteri seçin.", parent=self)
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            kaynak = getattr(self, "kaynak_map", {}).get(self.kaynak.get())
            self.result = SatisIadeFaturasiService.kaydet({
                "iade_tarihi": tarih,
                "cari_id": musteri.id,
                "kaynak_fatura_id": kaynak.id if kaynak else None,
                "depo": self.depo.get() or "ANA DEPO",
                "aciklama": self.aciklama.get().strip() or None,
                "iade_odeme_tutari": 0,
            }, self.satirlar, self.iade.id if self.iade else None)
        except ValueError as hata:
            messagebox.showerror("İade kaydedilemedi", str(hata), parent=self)
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
        self.after(500, self._pos_valor_kontrol)
        self.after(60_000, self._pos_valor_dongu)

    def _pos_valor_kontrol(self):
        """Valör günü + 08:00 şartı dolmuş POS net bakiyelerini KMH'ye aktarır."""
        try:
            FinansService.pos_valor_vadesi_gelenleri_aktar()
        except Exception:
            pass

    def _pos_valor_dongu(self):
        self._pos_valor_kontrol()
        self.after(60_000, self._pos_valor_dongu)

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
        elif anahtar == "satin_alma":
            self.satin_alma_menusu_goster()
        elif anahtar == "stoklar":
            self.stoklar_menusu_goster()
        elif anahtar == "finans":
            self.finans_goster()
        else:
            ttk.Label(self.icerik, text="Bu bölüm sonraki aşamada hazırlanacaktır.").pack(anchor="w", pady=(18, 0))

    def stoklar_menusu_goster(self):
        alt_menu = ttk.Frame(self.icerik)
        alt_menu.pack(fill="x", pady=(24, 0))
        alt_menu.columnconfigure(0, weight=1)
        alt_menu.columnconfigure(0, minsize=520)
        alt_menu_ogeleri = (
            ("STOK KARTLARI", self.stok_kartlari_goster),
            ("DEPO TRANSFER FİŞİ", self.depo_transfer_fisi_goster),
            ("STOK BİRLEŞTİR", self.stok_birlestir_goster),
            ("STOK PAKET TANIMLAMA", self.stok_paket_tanimlama_goster),
            ("TOPLU FİYAT DEĞİŞİKLİĞİ", self.toplu_fiyat_degisikligi_goster),
            ("STOK BARKOD BASIMI", self.stok_barkod_basimi_goster),
            ("RAPORLAR", self.stok_raporlari_goster),
        )
        for satir, (baslik, komut) in enumerate(alt_menu_ogeleri):
            ttk.Button(
                alt_menu,
                text=baslik,
                style="AltMenu.TButton",
                command=komut,
            ).grid(row=satir, column=0, sticky="ew", pady=4)

    def stok_alt_sayfasi_goster(self, baslik, aciklama="Bu bölüm sonraki aşamada hazırlanacaktır."):
        self._icerigi_temizle()
        for dugme_anahtari, dugme in self.menu_dugmeleri.items():
            dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")
        ttk.Label(self.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(self.icerik, text=aciklama).pack(anchor="w", pady=(18, 0))
        ttk.Button(self.icerik, text="← Stoklar Menüsü", command=lambda: self.sayfa_goster("stoklar")).pack(
            anchor="w", pady=(16, 0)
        )

    def stok_kartlari_goster(self):
        self._icerigi_temizle()
        for dugme_anahtari, dugme in self.menu_dugmeleri.items():
            dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")
        ttk.Label(self.icerik, text="STOK KARTLARI", style="Baslik.TLabel").pack(anchor="w")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.stok_arama = ttk.Entry(ust, width=32)
        self.stok_arama.pack(side="left", padx=8)
        self.stok_arama.bind("<Return>", lambda _e: self.stok_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.stok_listesini_yenile).pack(side="left")
        ttk.Button(ust, text="← Stoklar Menüsü", command=lambda: self.sayfa_goster("stoklar")).pack(side="right")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "ad", "tur", "barkod", "birim", "fiyatlar", "miktar")
        basliklar = ("Stok Kodu", "Stok Adı", "Kart Türü", "Barkod", "Birim", "Tanımlı Fiyatlar", "Toplam Mevcut")
        self.stok_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.stok_tablosu.heading(kolon, text=baslik)
            self.stok_tablosu.column(kolon, width=120, anchor="w")
        self.stok_tablosu.column("ad", width=240)
        self.stok_tablosu.column("fiyatlar", width=280)
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

    def depo_transfer_fisi_goster(self):
        depo_transfer_listesini_goster(self)

    def stok_birlestir_goster(self):
        stok_birlestir_sayfasi_goster(self)

    def stok_paket_tanimlama_goster(self):
        stok_paket_sayfasi_goster(self)

    def toplu_fiyat_degisikligi_goster(self):
        toplu_fiyat_sayfasi_goster(self)

    def stok_barkod_basimi_goster(self):
        barkod_basim_sayfasini_ac(self)

    def stok_raporlari_goster(self):
        stok_raporlari_menusu_goster(self)

    def finans_goster(self):
        finans_menusu_goster(self)

    def stok_listesini_yenile(self):
        if not hasattr(self, "stok_tablosu"):
            return
        for item in self.stok_tablosu.get_children():
            self.stok_tablosu.delete(item)
        for stok in StokService.stoklari_ara(self.stok_arama.get().strip()):
            fiyatlar = " | ".join(f"{f.fiyat_adi}: {para_goster(f.tutar)}" for f in stok.fiyatlar)
            mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
            self.stok_tablosu.insert("", "end", iid=str(stok.id), values=(
                stok.stok_kodu, stok.stok_adi, getattr(stok, "kart_turu", "") or "",
                stok.barkod or "", stok.birim, fiyatlar, mevcut,
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
            ("SATIŞ İADE FATURALARI", self.satis_iade_faturalari_goster),
            ("CARİ VİRMAN FİŞLERİ", self.cari_virman_goster),
            ("MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", self.kk_cekimi_goster),
            ("RAPORLAR", self.satis_raporlari_goster),
        )
        for satir, (baslik, komut) in enumerate(alt_menu_ogeleri):
            ttk.Button(
                alt_menu,
                text=baslik,
                style="AltMenu.TButton",
                command=komut,
            ).grid(row=satir, column=0, sticky="ew", pady=4)

    def satin_alma_menusu_goster(self):
        alt_menu = ttk.Frame(self.icerik)
        alt_menu.pack(fill="x", pady=(24, 0))
        alt_menu.columnconfigure(0, weight=1)
        alt_menu.columnconfigure(0, minsize=520)
        alt_menu_ogeleri = (
            ("TEDARİKÇİ CARİ HESAP KARTLARI", self.tedarikciler_goster),
            ("SATIN ALMA SİPARİŞLERİ", self.alis_siparisleri_goster),
            ("SATIN ALMA İRSALİYELERİ", self.alis_irsaliyeleri_goster),
            ("SATIN ALMA FATURALARI", self.alis_faturalari_goster),
            ("SATIN ALMA İADE FATURALARI", self.alis_iade_faturalari_goster),
            ("CARİ VİRMAN FİŞLERİ", self.cari_virman_goster),
            ("RAPORLAR", self.alis_raporlari_goster),
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

    def _cari_secenekleri(self, cari_turu: str | None = None):
        cariler = CariService.aktif_cariler(cari_turu=cari_turu)
        etiketler = [f"{c.cari_kodu} - {c.unvan}" for c in cariler]
        eslesme = {f"{c.cari_kodu} - {c.unvan}": c for c in cariler}
        return etiketler, eslesme

    def cari_virman_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="CARİ VİRMAN FİŞLERİ", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(
            self.icerik,
            text="Alacak yazılan tutar karşı cariye aynı miktarda otomatik borç yazılır.",
        ).pack(anchor="w", pady=(8, 10))

        arama_cerceve = ttk.Frame(self.icerik)
        arama_cerceve.pack(fill="x", pady=(0, 8))
        ttk.Label(arama_cerceve, text="Ara:").pack(side="left")
        self.virman_arama = ttk.Entry(arama_cerceve, width=36)
        self.virman_arama.pack(side="left", padx=6)
        ttk.Button(arama_cerceve, text="Listele", command=self.virman_listesini_yenile).pack(side="left")

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("belge", "tarih", "kaynak", "hedef", "tutar", "aciklama")
        basliklar = ("Belge No", "Tarih", "Alacak Cari", "Borç (Karşı) Cari", "Tutar", "Açıklama")
        self.virman_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.virman_tablosu.heading(kolon, text=baslik)
            self.virman_tablosu.column(kolon, width=140)
        self.virman_tablosu.column("kaynak", width=220)
        self.virman_tablosu.column("hedef", width=220)
        self.virman_tablosu.column("aciklama", width=200)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.virman_tablosu.yview)
        self.virman_tablosu.configure(yscrollcommand=dikey.set)
        self.virman_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Virman Fişi", command=self.yeni_virman).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=self.virman_iptal).pack(side="left", padx=8)
        self.virman_listesini_yenile()

    def virman_listesini_yenile(self):
        if not hasattr(self, "virman_tablosu"):
            return
        for item in self.virman_tablosu.get_children():
            self.virman_tablosu.delete(item)
        arama = self.virman_arama.get().strip() if hasattr(self, "virman_arama") else ""
        for kayit in CariService.virman_listele(arama):
            self.virman_tablosu.insert("", "end", iid=kayit["belge_no"], values=(
                kayit["belge_no"],
                tarih_goster(kayit["tarih"]),
                f"{kayit['kaynak_kodu']} - {kayit['kaynak_unvan']}",
                f"{kayit['hedef_kodu']} - {kayit['hedef_unvan']}",
                para_goster(kayit["tutar"]),
                kayit["aciklama"],
            ))

    def yeni_virman(self):
        dialog = CariVirmanDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.virman_listesini_yenile()

    def virman_iptal(self):
        secim = self.virman_tablosu.selection() if hasattr(self, "virman_tablosu") else ()
        if not secim:
            messagebox.showinfo("Virman seçimi", "Lütfen iptal edilecek virman fişini seçin.", parent=self)
            return
        belge_no = secim[0]
        if not messagebox.askyesno(
            "Virman iptal",
            f"{belge_no} numaralı virman fişi iptal edilsin mi?\nKaynak ve hedef bakiyeler geri alınır.",
            parent=self,
        ):
            return
        try:
            CariService.virman_iptal(belge_no)
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=self)
            return
        self.virman_listesini_yenile()

    def kk_cekimi_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="KREDİ KARTI ÇEKİM FİŞLERİ", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(
            self.icerik,
            text="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit sayısı serbest girilir; finans hesabına işlem düşmez.",
        ).pack(anchor="w", pady=(8, 10))

        arama_cerceve = ttk.Frame(self.icerik)
        arama_cerceve.pack(fill="x", pady=(0, 8))
        ttk.Label(arama_cerceve, text="Ara:").pack(side="left")
        self.kk_arama = ttk.Entry(arama_cerceve, width=36)
        self.kk_arama.pack(side="left", padx=6)
        ttk.Button(arama_cerceve, text="Listele", command=self.kk_listesini_yenile).pack(side="left")

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("belge", "tarih", "musteri", "tedarikci", "tutar", "banka", "cekim", "taksit", "aciklama")
        basliklar = (
            "Belge No", "Tarih", "Müşteri (Alacak)", "Tedarikçi (Borç)",
            "Tutar", "Banka", "Çekim Türü", "Taksit", "Açıklama",
        )
        self.kk_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.kk_tablosu.heading(kolon, text=baslik)
            self.kk_tablosu.column(kolon, width=120)
        self.kk_tablosu.column("musteri", width=180)
        self.kk_tablosu.column("tedarikci", width=180)
        self.kk_tablosu.column("aciklama", width=160)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.kk_tablosu.yview)
        self.kk_tablosu.configure(yscrollcommand=dikey.set)
        self.kk_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni KK Çekim Fişi", command=self.yeni_kk_cekimi).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=self.kk_cekimi_iptal).pack(side="left", padx=8)
        self.kk_listesini_yenile()

    def kk_listesini_yenile(self):
        if not hasattr(self, "kk_tablosu"):
            return
        for item in self.kk_tablosu.get_children():
            self.kk_tablosu.delete(item)
        arama = self.kk_arama.get().strip() if hasattr(self, "kk_arama") else ""
        for kayit in KkCekimiService.listele(arama):
            self.kk_tablosu.insert("", "end", iid=kayit["belge_no"], values=(
                kayit["belge_no"],
                tarih_goster(kayit["tarih"]),
                f"{kayit['musteri_kodu']} - {kayit['musteri_unvan']}",
                f"{kayit['tedarikci_kodu']} - {kayit['tedarikci_unvan']}",
                para_goster(kayit["tutar"]),
                kayit["banka"],
                kayit["cekim_turu"],
                kayit["taksit_sayisi"],
                kayit["aciklama"],
            ))

    def yeni_kk_cekimi(self):
        dialog = KkCekimiDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.kk_listesini_yenile()

    def kk_cekimi_iptal(self):
        secim = self.kk_tablosu.selection() if hasattr(self, "kk_tablosu") else ()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen iptal edilecek KK çekim fişini seçin.", parent=self)
            return
        belge_no = secim[0]
        if not messagebox.askyesno(
            "KK çekim iptal",
            f"{belge_no} numaralı fiş iptal edilsin mi?\nMüşteri alacağı ve tedarikçi borcu geri alınır.",
            parent=self,
        ):
            return
        try:
            KkCekimiService.iptal_et(belge_no)
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=self)
            return
        self.kk_listesini_yenile()

    def satis_raporlari_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="RAPORLAR", style="Baslik.TLabel").pack(anchor="w")
        alt_menu = ttk.Frame(self.icerik)
        alt_menu.pack(fill="x", pady=(24, 0))
        alt_menu.columnconfigure(0, weight=1)
        alt_menu.columnconfigure(0, minsize=520)
        for satir, (baslik, komut) in enumerate((
            ("MÜŞTERİ BAKİYE DURUM (ORTALAMA VADELİ)", self.rapor_musteri_bakiye_durum),
            ("MÜŞTERİ EKSTRESİ (ORTALAMA VALÖRLÜ / AĞIRLIKLI)", self.rapor_musteri_ekstresi),
            ("STOK DETAYLI MÜŞTERİ EKSTRESİ", self.rapor_stok_detayli_ekstre),
            ("TARİH ARALIKLI ÖDEME VE TAHSİLAT RAPORU", self.rapor_tahsilat_odeme),
            ("MÜŞTERİ SEÇİMLİ KAR / ZARAR RAPORU", self.rapor_kar_zarar),
            ("SATIŞ ÖZETİ", self.rapor_satis_ozeti),
        )):
            ttk.Button(alt_menu, text=baslik, style="AltMenu.TButton", command=komut).grid(
                row=satir, column=0, sticky="ew", pady=4
            )

    def _rapor_baslik(self, baslik, geri=True):
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x")
        ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
        if geri:
            ttk.Button(ust, text="← Raporlar", command=self.satis_raporlari_goster).pack(side="right")
        return ust

    def _rapor_tablo(self, parent, kolonlar, basliklar, genislikler=None):
        cerceve = ttk.Frame(parent)
        cerceve.pack(fill="both", expand=True, pady=(8, 0))
        tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for i, (kolon, baslik) in enumerate(zip(kolonlar, basliklar)):
            tablo.heading(kolon, text=baslik)
            tablo.column(kolon, width=(genislikler[i] if genislikler else 130))
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
        tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        return tablo

    def _rapor_cari_secim(self, parent, komut):
        etiketler, eslesme = self._cari_secenekleri()
        cerceve = ttk.Frame(parent)
        cerceve.pack(fill="x", pady=(10, 6))
        ttk.Label(cerceve, text="Müşteri:").pack(side="left")
        secim = ttk.Combobox(cerceve, values=etiketler, width=48)
        secim.pack(side="left", padx=6)
        ttk.Button(cerceve, text="Raporu Getir", command=lambda: komut(eslesme.get(secim.get()), secim)).pack(side="left")
        return secim, eslesme

    def rapor_musteri_bakiye_durum(self):
        self._icerigi_temizle()
        self._rapor_baslik("MÜŞTERİ BAKİYE DURUM (ORTALAMA VADELİ)")
        ttk.Label(
            self.icerik,
            text="Açık bakiyeler, ağırlıklı ortalama gün, ortalama vade ve geciken gün.",
        ).pack(anchor="w", pady=(8, 0))

        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(10, 4))
        ttk.Label(filtre, text="Bakiye:").pack(side="left")
        self.bakiye_filtre_op = ttk.Combobox(
            filtre, values=("Tümü", "Şu bakiyeden büyük", "Şu bakiyeden küçük", "Şu bakiyeye eşit"),
            state="readonly", width=18,
        )
        self.bakiye_filtre_op.set("Tümü")
        self.bakiye_filtre_op.pack(side="left", padx=4)
        self.bakiye_filtre_tutar = ttk.Entry(filtre, width=10)
        self.bakiye_filtre_tutar.insert(0, "0")
        self.bakiye_filtre_tutar.pack(side="left", padx=(0, 12))

        ttk.Label(filtre, text="Geciken gün:").pack(side="left")
        self.geciken_filtre_op = ttk.Combobox(
            filtre,
            values=("Tümü", "Şu günden büyük", "Şu günden küçük", "Şu güne eşit", "Sadece gecikenler"),
            state="readonly", width=18,
        )
        self.geciken_filtre_op.set("Tümü")
        self.geciken_filtre_op.pack(side="left", padx=4)
        self.geciken_filtre_gun = ttk.Entry(filtre, width=8)
        self.geciken_filtre_gun.insert(0, "0")
        self.geciken_filtre_gun.pack(side="left", padx=(0, 12))

        filtre2 = ttk.Frame(self.icerik)
        filtre2.pack(fill="x", pady=(0, 6))
        ttk.Label(filtre2, text="Sıralama:").pack(side="left")
        self.bakiye_siralama = ttk.Combobox(
            filtre2,
            values=(
                "Bakiye (büyükten küçüğe)",
                "Bakiye (küçükten büyüğe)",
                "Ort. geçen gün (büyükten küçüğe)",
                "Ort. geçen gün (küçükten büyüğe)",
                "Ağırlıklı gün (büyükten küçüğe)",
                "Ağırlıklı gün (küçükten büyüğe)",
                "Geciken gün (büyükten küçüğe)",
                "Geciken gün (küçükten büyüğe)",
                "Cari kodu (A-Z)",
            ),
            state="readonly",
            width=32,
        )
        self.bakiye_siralama.set("Bakiye (büyükten küçüğe)")
        self.bakiye_siralama.pack(side="left", padx=4)
        ttk.Button(filtre2, text="Uygula", command=self._bakiye_durum_yenile).pack(side="left", padx=10)
        self.bakiye_durum_ozet = ttk.Label(self.icerik, text="")
        self.bakiye_durum_ozet.pack(anchor="w", pady=(0, 4))
        self.bakiye_durum_tablo = self._rapor_tablo(
            self.icerik,
            ("kod", "unvan", "tur", "bakiye", "ort_gun", "agirlikli", "ort_vade", "geciken"),
            ("Cari Kodu", "Ünvan", "Tür", "Bakiye", "Ort. Gün", "Ağırlıklı Gün", "Ortalama Vade", "Geciken Gün"),
            (100, 220, 80, 110, 80, 100, 110, 100),
        )
        self._bakiye_durum_yenile()

    def _bakiye_durum_yenile(self):
        if not hasattr(self, "bakiye_durum_tablo"):
            return
        kayitlar = list(RaporService.musteri_bakiye_durum(cari_turu="Müşteri"))
        op = self.bakiye_filtre_op.get()
        if op != "Tümü":
            try:
                esik = CariService._tutar(self.bakiye_filtre_tutar.get().strip() or "0")
            except ValueError as hata:
                messagebox.showerror("Tutar", str(hata), parent=self)
                return
            if op == "Şu bakiyeden büyük":
                kayitlar = [k for k in kayitlar if k["bakiye"] > esik]
            elif op == "Şu bakiyeden küçük":
                kayitlar = [k for k in kayitlar if k["bakiye"] < esik]
            elif op == "Şu bakiyeye eşit":
                kayitlar = [k for k in kayitlar if k["bakiye"] == esik]

        geciken_op = self.geciken_filtre_op.get()
        if geciken_op == "Sadece gecikenler":
            kayitlar = [k for k in kayitlar if k["geciken_gun"] > 0]
        elif geciken_op != "Tümü":
            try:
                gun_esik = int(str(self.geciken_filtre_gun.get()).strip() or "0")
            except ValueError:
                messagebox.showerror("Gün", "Geciken gün sayısı tam sayı olmalıdır.", parent=self)
                return
            if geciken_op == "Şu günden büyük":
                kayitlar = [k for k in kayitlar if k["geciken_gun"] > gun_esik]
            elif geciken_op == "Şu günden küçük":
                kayitlar = [k for k in kayitlar if k["geciken_gun"] < gun_esik]
            elif geciken_op == "Şu güne eşit":
                kayitlar = [k for k in kayitlar if k["geciken_gun"] == gun_esik]

        siralama = self.bakiye_siralama.get()
        if siralama == "Bakiye (büyükten küçüğe)":
            kayitlar.sort(key=lambda k: k["bakiye"], reverse=True)
        elif siralama == "Bakiye (küçükten büyüğe)":
            kayitlar.sort(key=lambda k: k["bakiye"])
        elif siralama == "Ort. geçen gün (büyükten küçüğe)":
            kayitlar.sort(key=lambda k: k["ortalama_gun"], reverse=True)
        elif siralama == "Ort. geçen gün (küçükten büyüğe)":
            kayitlar.sort(key=lambda k: k["ortalama_gun"])
        elif siralama == "Ağırlıklı gün (büyükten küçüğe)":
            kayitlar.sort(key=lambda k: k["agirlikli_ortalama_gun"], reverse=True)
        elif siralama == "Ağırlıklı gün (küçükten büyüğe)":
            kayitlar.sort(key=lambda k: k["agirlikli_ortalama_gun"])
        elif siralama == "Geciken gün (büyükten küçüğe)":
            kayitlar.sort(key=lambda k: k["geciken_gun"], reverse=True)
        elif siralama == "Geciken gün (küçükten büyüğe)":
            kayitlar.sort(key=lambda k: k["geciken_gun"])
        elif siralama == "Cari kodu (A-Z)":
            kayitlar.sort(key=lambda k: k["cari_kodu"])

        for item in self.bakiye_durum_tablo.get_children():
            self.bakiye_durum_tablo.delete(item)
        toplam = sum((k["bakiye"] for k in kayitlar), Decimal("0"))
        geciken_sayisi = sum(1 for k in kayitlar if k["geciken_gun"] > 0)
        self.bakiye_durum_ozet.configure(
            text=(
                f"{len(kayitlar)} cari  |  Toplam bakiye: {para_goster(toplam)}  |  "
                f"Geciken cari: {geciken_sayisi}"
            )
        )
        for s in kayitlar:
            self.bakiye_durum_tablo.insert("", "end", values=(
                s["cari_kodu"], s["unvan"], s["cari_turu"],
                para_goster(s["bakiye"]),
                f"{s['ortalama_gun']:.1f}",
                f"{s['agirlikli_ortalama_gun']:.1f}",
                tarih_goster(s["ortalama_vade"]) if s["ortalama_vade"] else "-",
                s["geciken_gun"],
            ))

    def rapor_musteri_ekstresi(self):
        self._icerigi_temizle()
        self._rapor_baslik("MÜŞTERİ EKSTRESİ (ORTALAMA VALÖRLÜ / AĞIRLIKLI)")
        self.ekstre_ozet = ttk.Label(self.icerik, text="Müşteri seçip raporu getirin.")
        self.ekstre_ozet.pack(anchor="w", pady=(8, 0))
        self._ekstre_ham = None
        self._ekstre_cari = None

        etiketler, eslesme = self._cari_secenekleri()
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=(10, 4))
        ttk.Label(ust, text="Müşteri:").pack(side="left")
        self.ekstre_musteri = ttk.Combobox(ust, values=etiketler, width=36)
        self.ekstre_musteri.pack(side="left", padx=6)

        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(0, 6))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        self.ekstre_baslangic = ttk.Entry(filtre, width=11)
        self.ekstre_baslangic.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        self.ekstre_bitis = ttk.Entry(filtre, width=11)
        self.ekstre_bitis.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Belge no:").pack(side="left")
        self.ekstre_belge = ttk.Entry(filtre, width=14)
        self.ekstre_belge.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Belge türü:").pack(side="left")
        self.ekstre_tur = ttk.Combobox(
            filtre,
            values=("Tümü", "Satış", "Tahsilat", "Ödeme", "Cari Virman", "KK Çekimi", "Satış İadesi"),
            state="readonly",
            width=14,
        )
        self.ekstre_tur.set("Tümü")
        self.ekstre_tur.pack(side="left", padx=(4, 10))
        ttk.Button(filtre, text="Raporu Getir / Uygula", command=lambda: self._ekstre_yenile(eslesme)).pack(
            side="left", padx=4
        )

        self.ekstre_tablo = self._rapor_tablo(
            self.icerik,
            ("tarih", "tur", "belge", "aciklama", "borc", "alacak", "bakiye", "gun"),
            ("Tarih", "Tür", "Belge No", "Açıklama", "Borç", "Alacak", "Bakiye", "Gün"),
            (90, 110, 130, 200, 110, 110, 120, 70),
        )

    def _ekstre_yenile(self, eslesme):
        cari = eslesme.get(self.ekstre_musteri.get())
        if not cari:
            messagebox.showwarning("Cari", "Lütfen listeden cari seçin.", parent=self)
            return
        # Cari değiştiyse veya henüz yüklenmediyse yeniden çek
        if self._ekstre_cari is None or self._ekstre_cari.id != cari.id or self._ekstre_ham is None:
            try:
                rapor = RaporService.musteri_ekstresi(cari.id)
            except ValueError as hata:
                messagebox.showerror("Rapor", str(hata), parent=self)
                return
            self._ekstre_cari = cari
            self._ekstre_ham = rapor
            # Bu müşterideki belge türlerini combobox'a ekle
            turler = sorted({s["tur"] for s in rapor["satirlar"] if s.get("tur")})
            self.ekstre_tur.configure(values=("Tümü", *turler))
            if self.ekstre_tur.get() not in ("Tümü", *turler):
                self.ekstre_tur.set("Tümü")

        rapor = self._ekstre_ham
        baslangic = bitis = None
        try:
            if self.ekstre_baslangic.get().strip():
                baslangic = datetime.strptime(self.ekstre_baslangic.get().strip(), "%d.%m.%Y").date()
            if self.ekstre_bitis.get().strip():
                bitis = datetime.strptime(self.ekstre_bitis.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return
        if baslangic and bitis and baslangic > bitis:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
            return

        belge_filtre = self.ekstre_belge.get().strip().casefold()
        tur_filtre = self.ekstre_tur.get().strip()
        satirlar = []
        for s in rapor["satirlar"]:
            if baslangic and s["tarih"] < baslangic:
                continue
            if bitis and s["tarih"] > bitis:
                continue
            if belge_filtre and belge_filtre not in (s["belge_no"] or "").casefold():
                continue
            if tur_filtre and tur_filtre != "Tümü" and s.get("tur") != tur_filtre:
                continue
            satirlar.append(s)

        vade = tarih_goster(rapor["ortalama_vade"]) if rapor["ortalama_vade"] else "-"
        borc_t = sum((s["borc"] for s in satirlar), Decimal("0"))
        alacak_t = sum((s["alacak"] for s in satirlar), Decimal("0"))
        self.ekstre_ozet.configure(
            text=(
                f"{rapor['cari'].cari_kodu} - {rapor['cari'].unvan}  |  "
                f"Genel bakiye: {para_goster(rapor['bakiye'])}  |  "
                f"Ağırlıklı valör: {rapor['agirlikli_ortalama_gun']:.1f} gün  |  "
                f"Ort. vade: {vade}  |  "
                f"Filtre: {len(satirlar)} hareket  |  Borç: {para_goster(borc_t)}  |  Alacak: {para_goster(alacak_t)}"
            )
        )
        for item in self.ekstre_tablo.get_children():
            self.ekstre_tablo.delete(item)
        for s in satirlar:
            self.ekstre_tablo.insert("", "end", values=(
                tarih_goster(s["tarih"]), s["tur"], s["belge_no"], s["aciklama"],
                para_goster(s["borc"]), para_goster(s["alacak"]), para_goster(s["bakiye"]), s["gun"],
            ))

    def rapor_stok_detayli_ekstre(self):
        self._icerigi_temizle()
        self._rapor_baslik("STOK DETAYLI MÜŞTERİ EKSTRESİ")
        self.stok_ekstre_ozet = ttk.Label(
            self.icerik,
            text="Fatura toplamları + stok satırları; borç / alacak / bakiye net görünür.",
        )
        self.stok_ekstre_ozet.pack(anchor="w", pady=(8, 0))
        self._stok_ekstre_ham = None
        self._stok_ekstre_cari = None

        etiketler, eslesme = self._cari_secenekleri()
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=(10, 4))
        ttk.Label(ust, text="Müşteri:").pack(side="left")
        self.stok_ekstre_musteri = ttk.Combobox(ust, values=etiketler, width=36)
        self.stok_ekstre_musteri.pack(side="left", padx=6)

        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(0, 6))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        self.stok_ekstre_bas = ttk.Entry(filtre, width=11)
        self.stok_ekstre_bas.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        self.stok_ekstre_bit = ttk.Entry(filtre, width=11)
        self.stok_ekstre_bit.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Stok:").pack(side="left")
        self.stok_ekstre_stok = ttk.Entry(filtre, width=16)
        self.stok_ekstre_stok.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Belge türü:").pack(side="left")
        self.stok_ekstre_tur = ttk.Combobox(
            filtre,
            values=("Tümü", "Satış Faturası", "Tahsilat", "Ödeme", "Cari Virman", "KK Çekimi", "Satış İadesi"),
            state="readonly",
            width=14,
        )
        self.stok_ekstre_tur.set("Tümü")
        self.stok_ekstre_tur.pack(side="left", padx=(4, 8))
        ttk.Button(
            filtre, text="Raporu Getir / Uygula",
            command=lambda: self._stok_ekstre_yenile(eslesme),
        ).pack(side="left", padx=4)

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(8, 0))
        kolonlar = (
            "tarih", "tur", "belge", "aciklama", "urun", "miktar", "fiyat",
            "satir_tutar", "lot", "borc", "alacak", "bakiye",
        )
        self.stok_ekstre_tablo = ttk.Treeview(cerceve, columns=kolonlar, show="tree headings")
        basliklar = {
            "tarih": "Tarih", "tur": "Belge Türü", "belge": "Belge No", "aciklama": "Açıklama",
            "urun": "Stok", "miktar": "Miktar", "fiyat": "Birim Fiyat", "satir_tutar": "Satır Tutarı",
            "lot": "Lot", "borc": "Borç", "alacak": "Alacak", "bakiye": "Bakiye",
        }
        genislikler = {
            "tarih": 85, "tur": 110, "belge": 120, "aciklama": 150, "urun": 170, "miktar": 70,
            "fiyat": 90, "satir_tutar": 95, "lot": 120, "borc": 100, "alacak": 100, "bakiye": 110,
        }
        self.stok_ekstre_tablo.heading("#0", text="")
        self.stok_ekstre_tablo.column("#0", width=22, stretch=False)
        for kolon in kolonlar:
            self.stok_ekstre_tablo.heading(kolon, text=basliklar[kolon])
            self.stok_ekstre_tablo.column(kolon, width=genislikler[kolon])
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.stok_ekstre_tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.stok_ekstre_tablo.xview)
        self.stok_ekstre_tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.stok_ekstre_tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        self.stok_ekstre_tablo.tag_configure("belge", font=("Segoe UI", 9, "bold"))
        self.stok_ekstre_tablo.tag_configure("stok", foreground="#333333")

    def _stok_ekstre_yenile(self, eslesme):
        cari = eslesme.get(self.stok_ekstre_musteri.get())
        if not cari:
            messagebox.showwarning("Cari", "Lütfen listeden cari seçin.", parent=self)
            return
        if self._stok_ekstre_cari is None or self._stok_ekstre_cari.id != cari.id or self._stok_ekstre_ham is None:
            try:
                rapor = RaporService.stok_detayli_ekstre(cari.id)
            except ValueError as hata:
                messagebox.showerror("Rapor", str(hata), parent=self)
                return
            self._stok_ekstre_cari = cari
            self._stok_ekstre_ham = rapor
            turler = rapor.get("belge_turleri") or []
            self.stok_ekstre_tur.configure(values=("Tümü", *turler))
            if self.stok_ekstre_tur.get() not in ("Tümü", *turler):
                self.stok_ekstre_tur.set("Tümü")

        rapor = self._stok_ekstre_ham
        baslangic = bitis = None
        try:
            if self.stok_ekstre_bas.get().strip():
                baslangic = datetime.strptime(self.stok_ekstre_bas.get().strip(), "%d.%m.%Y").date()
            if self.stok_ekstre_bit.get().strip():
                bitis = datetime.strptime(self.stok_ekstre_bit.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return
        if baslangic and bitis and baslangic > bitis:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
            return

        stok_filtre = self.stok_ekstre_stok.get().strip().casefold()
        tur_filtre = self.stok_ekstre_tur.get().strip()

        for item in self.stok_ekstre_tablo.get_children():
            self.stok_ekstre_tablo.delete(item)

        gosterilen = 0
        borc_t = Decimal("0")
        alacak_t = Decimal("0")
        for belge in rapor["belgeler"]:
            if baslangic and belge["tarih"] < baslangic:
                continue
            if bitis and belge["tarih"] > bitis:
                continue
            if tur_filtre and tur_filtre != "Tümü" and belge["tur"] != tur_filtre:
                continue

            stok_satirlari = list(belge.get("stok_satirlari") or [])
            stoklu_tur = belge["tur"] in ("Satış Faturası", "Satış İadesi", "Alış Faturası", "Alış İadesi")
            if stok_filtre:
                stok_satirlari = [
                    s for s in stok_satirlari
                    if stok_filtre in (s["urun_kodu"] or "").casefold()
                    or stok_filtre in (s["urun_adi"] or "").casefold()
                ]
                # Stok filtresi varken tahsilat vb. gizlenir; stoklu belgede eşleşme yoksa belge de gizlenir.
                if stoklu_tur and not stok_satirlari:
                    continue
                if not stoklu_tur:
                    continue

            parent = self.stok_ekstre_tablo.insert(
                "", "end",
                values=(
                    tarih_goster(belge["tarih"]),
                    belge["tur"],
                    belge["belge_no"],
                    belge.get("aciklama") or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    para_goster(belge["borc"]) if belge["borc"] else "",
                    para_goster(belge["alacak"]) if belge["alacak"] else "",
                    para_goster(belge["bakiye"]),
                ),
                tags=("belge",),
                open=True,
            )
            gosterilen += 1
            borc_t += belge["borc"] or Decimal("0")
            alacak_t += belge["alacak"] or Decimal("0")

            for s in stok_satirlari:
                self.stok_ekstre_tablo.insert(
                    parent, "end",
                    values=(
                        "",
                        "",
                        "",
                        "",
                        f"{s['urun_kodu']} - {s['urun_adi']}",
                        f"{s['miktar']} {s['birim']}",
                        para_goster(s["birim_fiyat"]),
                        para_goster(s["genel"]),
                        s.get("lot_cikisi") or "",
                        "",
                        "",
                        "",
                    ),
                    tags=("stok",),
                )

        self.stok_ekstre_ozet.configure(
            text=(
                f"{rapor['cari'].cari_kodu} - {rapor['cari'].unvan}  |  "
                f"Genel bakiye: {para_goster(rapor['bakiye'])}  |  "
                f"Gösterilen belge: {gosterilen}  |  "
                f"Borç: {para_goster(borc_t)}  |  Alacak: {para_goster(alacak_t)}"
            )
        )

    def rapor_tahsilat_odeme(self):
        self._icerigi_temizle()
        self._rapor_baslik("TARİH ARALIKLI ÖDEME VE TAHSİLAT RAPORU")
        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(10, 6))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        baslangic = ttk.Entry(filtre, width=12)
        baslangic.insert(0, date.today().replace(day=1).strftime("%d.%m.%Y"))
        baslangic.pack(side="left", padx=(4, 12))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        bitis = ttk.Entry(filtre, width=12)
        bitis.insert(0, date.today().strftime("%d.%m.%Y"))
        bitis.pack(side="left", padx=(4, 12))
        ttk.Label(filtre, text="Tür:").pack(side="left")
        tur = ttk.Combobox(filtre, values=("Hepsi", "Tahsilat", "Ödeme"), state="readonly", width=12)
        tur.set("Hepsi")
        tur.pack(side="left", padx=4)
        self.tahsilat_odeme_ozet = ttk.Label(self.icerik, text="")
        self.tahsilat_odeme_ozet.pack(anchor="w", pady=(4, 0))
        self.tahsilat_odeme_tablo = self._rapor_tablo(
            self.icerik,
            ("tarih", "tur", "belge", "cari", "karsi", "hesap", "borc", "alacak", "aciklama"),
            ("Tarih", "Tür", "Belge", "Cari", "Karşı Cari", "Hesap", "Borç", "Alacak", "Açıklama"),
            (90, 110, 120, 180, 160, 100, 100, 100, 180),
        )

        def getir():
            try:
                b = datetime.strptime(baslangic.get().strip(), "%d.%m.%Y").date()
                e = datetime.strptime(bitis.get().strip(), "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
                return
            if b > e:
                messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
                return
            tur_kod = {"Hepsi": "hepsi", "Tahsilat": "tahsilat", "Ödeme": "odeme"}[tur.get()]
            rapor = RaporService.tarih_aralikli_tahsilat_odeme(b, e, tur_kod)
            self.tahsilat_odeme_ozet.configure(
                text=(
                    f"{tarih_goster(b)} – {tarih_goster(e)}  |  "
                    f"Tahsilat: {para_goster(rapor['toplam_tahsilat'])}  |  "
                    f"Ödeme: {para_goster(rapor['toplam_odeme'])}  |  "
                    f"Kayıt: {len(rapor['satirlar'])}"
                )
            )
            for item in self.tahsilat_odeme_tablo.get_children():
                self.tahsilat_odeme_tablo.delete(item)
            for s in rapor["satirlar"]:
                karsi = f"{s['karsi_kodu']} - {s['karsi_unvan']}".strip(" -") if s["karsi_kodu"] else ""
                self.tahsilat_odeme_tablo.insert("", "end", values=(
                    tarih_goster(s["tarih"]), s["tur"], s["belge_no"],
                    f"{s['cari_kodu']} - {s['cari_unvan']}", karsi, s["hesap"],
                    para_goster(s["borc"]), para_goster(s["alacak"]), s["aciklama"],
                ))

        ttk.Button(filtre, text="Raporu Getir", command=getir).pack(side="left", padx=10)
        getir()

    def rapor_kar_zarar(self):
        self._icerigi_temizle()
        self._rapor_baslik("MÜŞTERİ SEÇİMLİ KAR / ZARAR RAPORU")
        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(10, 6))
        etiketler, eslesme = self._cari_secenekleri()
        ttk.Label(filtre, text="Müşteri:").pack(side="left")
        secim = ttk.Combobox(filtre, values=etiketler, width=32)
        secim.pack(side="left", padx=6)
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        baslangic = ttk.Entry(filtre, width=11)
        baslangic.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        bitis = ttk.Entry(filtre, width=11)
        bitis.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Stok:").pack(side="left")
        stok = ttk.Entry(filtre, width=16)
        stok.pack(side="left", padx=(4, 8))
        self.kar_ozet = ttk.Label(
            self.icerik,
            text="Müşteri seçip raporu getirin. Tarih ve stok (kod/ad) ile filtreleyebilirsiniz. (FIFO maliyet)",
        )
        self.kar_ozet.pack(anchor="w", pady=(4, 0))
        self.kar_tablo = self._rapor_tablo(
            self.icerik,
            ("fatura", "tarih", "urun", "adi", "miktar", "net", "fifo", "maliyet", "kar", "marj"),
            ("Fatura", "Tarih", "Ürün", "Adı", "Miktar", "Net Satış", "FIFO Br.", "Maliyet", "Kâr", "Marj %"),
            (120, 90, 90, 160, 70, 100, 90, 100, 100, 80),
        )

        def getir():
            cari = eslesme.get(secim.get())
            if not cari:
                messagebox.showwarning("Müşteri", "Müşteri seçin.", parent=self)
                return
            b = e = None
            try:
                if baslangic.get().strip():
                    b = datetime.strptime(baslangic.get().strip(), "%d.%m.%Y").date()
                if bitis.get().strip():
                    e = datetime.strptime(bitis.get().strip(), "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
                return
            if b and e and b > e:
                messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
                return
            try:
                rapor = RaporService.musteri_kar_zarar(cari.id, b, e, stok.get().strip() or None)
            except ValueError as hata:
                messagebox.showerror("Rapor", str(hata), parent=self)
                return
            self.kar_ozet.configure(
                text=(
                    f"{rapor['cari'].cari_kodu} - {rapor['cari'].unvan}  |  "
                    f"Satır: {len(rapor['satirlar'])}  |  "
                    f"Satış: {para_goster(rapor['toplam_satis'])}  |  "
                    f"Maliyet: {para_goster(rapor['toplam_maliyet'])}  |  "
                    f"Kâr: {para_goster(rapor['toplam_kar'])}  |  "
                    f"Marj: {rapor['toplam_marj']:.1f}%"
                )
            )
            for item in self.kar_tablo.get_children():
                self.kar_tablo.delete(item)
            for s in rapor["satirlar"]:
                self.kar_tablo.insert("", "end", values=(
                    s["fatura_no"], tarih_goster(s["tarih"]), s["urun_kodu"], s["urun_adi"],
                    s["miktar"], para_goster(s["net_satis"]), para_goster(s["fifo_birim_maliyeti"]),
                    para_goster(s["toplam_maliyet"]), para_goster(s["kar"]), f"{s['marj']:.1f}",
                ))

        ttk.Button(filtre, text="Raporu Getir", command=getir).pack(side="left", padx=4)

    def rapor_satis_ozeti(self):
        self._icerigi_temizle()
        self._rapor_baslik("SATIŞ ÖZETİ")
        self._satis_ozet_raporu_doldur(self.icerik)

    def _satis_ozet_raporu_doldur(self, parent):
        rapor = CariService.satis_raporu()
        ozet = ttk.Frame(parent)
        ozet.pack(fill="x", pady=(8, 8))
        for baslik, deger in (
            ("Fatura Sayısı", str(rapor["fatura_sayisi"])),
            ("Toplam Ciro", para_goster(rapor["toplam_ciro"])),
            ("Fatura Tahsilatı", para_goster(rapor["toplam_tahsilat"])),
            ("Açık Cari Bakiye", para_goster(rapor["acik_bakiye"])),
        ):
            kutu = ttk.LabelFrame(ozet, text=baslik, padding=10)
            kutu.pack(side="left", expand=True, fill="x", padx=4)
            ttk.Label(kutu, text=deger, font=("Segoe UI", 12, "bold")).pack()

        orta = ttk.Frame(parent)
        orta.pack(fill="x", pady=8)
        aylik = ttk.LabelFrame(orta, text="Aylık Ciro", padding=8)
        aylik.pack(side="left", fill="both", expand=True, padx=(0, 4))
        aylik_tablo = ttk.Treeview(aylik, columns=("ay", "tutar"), show="headings", height=8)
        aylik_tablo.heading("ay", text="Ay")
        aylik_tablo.heading("tutar", text="Ciro")
        aylik_tablo.column("ay", width=100)
        aylik_tablo.column("tutar", width=140)
        aylik_tablo.pack(fill="both", expand=True)
        for ay, tutar in rapor["aylik"]:
            aylik_tablo.insert("", "end", values=(ay, para_goster(tutar)))

        musteriler = ttk.LabelFrame(orta, text="En Çok Ciro Yapan Müşteriler", padding=8)
        musteriler.pack(side="left", fill="both", expand=True, padx=(4, 0))
        m_tablo = ttk.Treeview(musteriler, columns=("musteri", "tutar"), show="headings", height=8)
        m_tablo.heading("musteri", text="Müşteri")
        m_tablo.heading("tutar", text="Ciro")
        m_tablo.column("musteri", width=260)
        m_tablo.column("tutar", width=140)
        m_tablo.pack(fill="both", expand=True)
        for unvan, tutar in rapor["top_musteriler"]:
            m_tablo.insert("", "end", values=(unvan, para_goster(tutar)))

        faturalar = ttk.LabelFrame(parent, text="Fatura Listesi", padding=8)
        faturalar.pack(fill="both", expand=True, pady=(8, 0))
        kolonlar = ("no", "tarih", "musteri", "toplam", "tahsilat", "kalan", "durum")
        tablo = ttk.Treeview(faturalar, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (
            ("no", "Fatura No", 130), ("tarih", "Tarih", 90), ("musteri", "Müşteri", 220),
            ("toplam", "Toplam", 110), ("tahsilat", "Tahsilat", 110), ("kalan", "Kalan", 110), ("durum", "Durum", 90),
        ):
            tablo.heading(kolon, text=baslik)
            tablo.column(kolon, width=genislik)
        kaydirma = ttk.Scrollbar(faturalar, orient="vertical", command=tablo.yview)
        tablo.configure(yscrollcommand=kaydirma.set)
        tablo.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        for s in rapor["satirlar"]:
            tablo.insert("", "end", values=(
                s["fatura_no"], tarih_goster(s["tarih"]), s["musteri"],
                para_goster(s["toplam"]), para_goster(s["tahsilat"]), para_goster(s["kalan"]), s["durum"],
            ))

    def satis_faturalari_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIŞ FATURALARI", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(14, 0))
        kolonlar = ("no", "tarih", "saat", "vade", "musteri", "siparis", "irsaliye", "depo", "toplam", "tahsilat", "kalan", "durum")
        basliklar = ("Fatura No", "Fatura Tarihi", "Saat", "Vade Tarihi", "Müşteri", "Sipariş No", "İrsaliye No", "Depo", "Genel Toplam", "Tahsilat", "Kalan", "Durum")
        self.fatura_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.fatura_tablosu.heading(kolon, text=baslik)
            self.fatura_tablosu.column(kolon, width=125)
        self.fatura_tablosu.column("musteri", width=220)
        self.fatura_tablosu.column("saat", width=70)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.fatura_tablosu.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.fatura_tablosu.xview)
        self.fatura_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.fatura_tablosu.grid(row=0, column=0, sticky="nsew"); dikey.grid(row=0, column=1, sticky="ns"); yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        self.fatura_tablosu.bind("<Double-1>", lambda _e: self.fatura_ac())
        alt = ttk.Frame(self.icerik); alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Fatura", command=self.yeni_fatura).pack(side="left")
        ttk.Button(alt, text="Faturayı Aç / Düzenle", command=self.fatura_ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İade Faturası Oluştur", command=self.faturadan_iade_olustur).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=self.fatura_iptal).pack(side="left", padx=8)
        self.fatura_listesini_yenile()

    def fatura_listesini_yenile(self):
        for item in self.fatura_tablosu.get_children(): self.fatura_tablosu.delete(item)
        for kayit in SatisFaturasiService.listele():
            f = kayit["fatura"]; toplam = kayit["genel_toplam"]; tahsilat = f.tahsilat_tutari
            self.fatura_tablosu.insert("", "end", iid=str(f.id), values=(
                f.fatura_no, tarih_goster(f.fatura_tarihi), f.islem_saati or "", tarih_goster(f.vade_tarihi), f.cari.unvan,
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

    def faturadan_iade_olustur(self):
        fatura_id = self._secili_fatura_id()
        if fatura_id is None:
            return
        fatura = SatisFaturasiService.getir(fatura_id)
        if not fatura:
            return
        if fatura.durum == "İPTAL":
            messagebox.showwarning("İade", "İptal faturalardan iade oluşturulamaz.", parent=self)
            return
        dialog = SatisIadeFaturasiDialog(self, kaynak_fatura=fatura)
        self.wait_window(dialog)
        if dialog.result:
            messagebox.showinfo("İade", "Satış iade faturası kaydedildi.", parent=self)
            self.satis_iade_faturalari_goster()

    def satis_iade_faturalari_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIŞ İADE FATURALARI", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(14, 0))
        kolonlar = ("no", "tarih", "musteri", "kaynak", "depo", "toplam", "durum")
        basliklar = ("İade No", "İade Tarihi", "Müşteri", "Kaynak Fatura", "Depo", "Genel Toplam", "Durum")
        self.iade_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.iade_tablosu.heading(kolon, text=baslik)
            self.iade_tablosu.column(kolon, width=140)
        self.iade_tablosu.column("musteri", width=220)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.iade_tablosu.yview)
        self.iade_tablosu.configure(yscrollcommand=dikey.set)
        self.iade_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.iade_tablosu.bind("<Double-1>", lambda _e: self.iade_ac())
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni İade Faturası", command=self.yeni_iade).pack(side="left")
        ttk.Button(alt, text="İadeyi Aç", command=self.iade_ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal Et", command=self.iade_iptal).pack(side="left")
        self.iade_listesini_yenile()

    def iade_listesini_yenile(self):
        for item in self.iade_tablosu.get_children():
            self.iade_tablosu.delete(item)
        for kayit in SatisIadeFaturasiService.listele():
            i = kayit["iade"]
            self.iade_tablosu.insert("", "end", iid=str(i.id), values=(
                i.iade_no, tarih_goster(i.iade_tarihi), i.cari.unvan if i.cari else "",
                i.kaynak_fatura.fatura_no if i.kaynak_fatura else "",
                i.depo, para_goster(kayit["genel_toplam"]), i.durum,
            ))

    def _secili_iade_id(self):
        secim = self.iade_tablosu.selection()
        if not secim:
            messagebox.showinfo("İade seçimi", "Lütfen bir iade faturası seçin.", parent=self)
            return None
        return int(secim[0])

    def yeni_iade(self):
        dialog = SatisIadeFaturasiDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.iade_listesini_yenile()

    def iade_ac(self):
        iade_id = self._secili_iade_id()
        if iade_id is not None:
            iade = SatisIadeFaturasiService.getir(iade_id)
            if iade:
                dialog = SatisIadeFaturasiDialog(self, iade=iade)
                self.wait_window(dialog)
                if dialog.result:
                    self.iade_listesini_yenile()

    def iade_iptal(self):
        iade_id = self._secili_iade_id()
        if iade_id is not None and messagebox.askyesno("İadeyi iptal et", "Seçili iade faturası iptal edilsin mi?", parent=self):
            try:
                SatisIadeFaturasiService.iptal_et(iade_id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
                return
            self.iade_listesini_yenile()

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
        ttk.Button(alt, text="İrsaliyeye Çevir", command=self.siparis_irsaliyeye_cevir).pack(side="left")
        ttk.Button(alt, text="Faturaya Çevir", command=self.siparis_faturaya_cevir).pack(side="left", padx=8)
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

    def siparis_irsaliyeye_cevir(self):
        siparis_id = self._secili_siparis_id()
        if siparis_id is not None:
            siparis = SatisSiparisiService.getir(siparis_id)
            if siparis:
                if siparis.durum == "İPTAL":
                    messagebox.showwarning("İrsaliye", "İptal edilmiş sipariş irsaliyeye çevrilemez.", parent=self)
                    return
                acik = any(s.miktar - s.irsaliyelenen_miktar > 0 for s in siparis.satirlar)
                if not acik:
                    messagebox.showinfo("İrsaliye", "Bu siparişte irsaliyelenecek açık miktar kalmadı.", parent=self)
                    return
                dialog = SatisIrsaliyesiDialog(self, siparis=siparis)
                self.wait_window(dialog)
                if dialog.result:
                    self.siparis_listesini_yenile()

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
        self._cariler_goster(cari_turu="Müşteri")

    def tedarikciler_goster(self):
        self._cariler_goster(cari_turu="Tedarikçi")

    def _cariler_goster(self, cari_turu="Müşteri"):
        self._icerigi_temizle()
        self._cari_liste_turu = cari_turu
        tedarikci = cari_turu == "Tedarikçi"
        baslik = "TEDARİKÇİ CARİ HESAP KARTLARI" if tedarikci else "MÜŞTERİ KARTLARI"
        etiket = "Tedarikçi" if tedarikci else "Müşteri"
        ttk.Label(self.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=14)
        ttk.Label(ust, text="Ara (en az 3 karakter):").pack(side="left")
        self.cari_arama = ttk.Entry(ust, width=30)
        self.cari_arama.pack(side="left", padx=8)
        self.cari_arama.bind("<Return>", lambda _event: self.cari_listesini_yenile())
        ttk.Button(ust, text="Ara", command=self.cari_listesini_yenile).pack(side="left")
        ttk.Button(ust, text=f"Yeni {etiket}", command=self.yeni_cari).pack(side="right")

        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "unvan", "grup", "telefon", "email", "bakiye", "agirlikli", "durum")
        basliklar = {
            "kod": f"{etiket} Kodu", "unvan": f"{etiket} Adı", "grup": f"{etiket} Grubu",
            "telefon": "Telefon", "email": "E-posta", "bakiye": "Yekûn Bakiye",
            "agirlikli": "Ağırlıklı Ortalama Geçen Gün", "durum": "Durum",
        }
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
        ttk.Button(alt, text=f"{etiket} Kartını Aç", command=self.cari_detay).pack(side="left")
        ttk.Button(alt, text="Düzenle", command=self.cari_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Pasife Al", command=self.cari_pasife_al).pack(side="left")
        self.cari_listesini_yenile()

    def cari_listesini_yenile(self):
        if not hasattr(self, "cari_tablosu"):
            return
        for item in self.cari_tablosu.get_children():
            self.cari_tablosu.delete(item)
        tur = getattr(self, "_cari_liste_turu", "Müşteri")
        try:
            cariler = CariService.listele(self.cari_arama.get(), cari_turu=tur)
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
        tur = getattr(self, "_cari_liste_turu", "Müşteri")
        dialog = CariDialog(self, cari_turu=tur)
        self.wait_window(dialog)
        if dialog.result:
            self.cari_listesini_yenile()

    def cari_duzenle(self):
        cari = self._secili_cari()
        if cari:
            dialog = CariDialog(self, cari, cari_turu=cari.cari_turu or "Müşteri")
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
        kart = CariDialog(self, cari, cari_turu=cari.cari_turu or "Müşteri")
        self.wait_window(kart)
        if kart.result:
            self.cari_listesini_yenile()

    # --- Satın Alma belgeler ---

    def alis_raporlari_goster(self):
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIN ALMA RAPORLARI", style="Baslik.TLabel").pack(anchor="w")
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=(24, 0))
        alt.columnconfigure(0, weight=1)
        for satir, (baslik, komut) in enumerate((
            ("TEDARİKÇİ BAKİYE DURUM (ORTALAMA VADELİ)", self.rapor_tedarikci_bakiye_durum),
            ("TEDARİKÇİ EKSTRESİ", self.rapor_tedarikci_ekstresi),
            ("STOK DETAYLI TEDARİKÇİ EKSTRESİ", self.rapor_stok_detayli_tedarikci_ekstre),
            ("TARİH ARALIKLI ÖDEME VE TAHSİLAT RAPORU", self.rapor_tahsilat_odeme),
            ("SATIN ALMA ÖZETİ", self.rapor_alis_ozeti),
        )):
            ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
                row=satir, column=0, sticky="ew", pady=4
            )

    def _alis_rapor_baslik(self, metin):
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x")
        ttk.Label(ust, text=metin, style="Baslik.TLabel").pack(side="left")
        ttk.Button(ust, text="← Raporlar", command=self.alis_raporlari_goster).pack(side="right")

    def rapor_tedarikci_bakiye_durum(self):
        self._icerigi_temizle()
        self._alis_rapor_baslik("TEDARİKÇİ BAKİYE DURUM (ORTALAMA VADELİ)")
        satirlar = RaporService.musteri_bakiye_durum(cari_turu="Tedarikçi")
        self.kar_ozet = ttk.Label(self.icerik, text=f"{len(satirlar)} tedarikçi")
        self.kar_ozet.pack(anchor="w", pady=(8, 0))
        tablo = self._rapor_tablo(
            self.icerik,
            ("kod", "unvan", "bakiye", "ort", "agirlikli", "geciken"),
            ("Kod", "Ünvan", "Bakiye", "Ort. Gün", "Ağırlıklı Gün", "Geciken Gün"),
            (90, 220, 110, 90, 110, 100),
        )
        for s in satirlar:
            tablo.insert("", "end", values=(
                s["cari_kodu"], s["unvan"], para_goster(s["bakiye"]),
                f"{s['ortalama_gun']:.1f}", f"{s['agirlikli_ortalama_gun']:.1f}", s["geciken_gun"],
            ))

    def rapor_tedarikci_ekstresi(self):
        self._icerigi_temizle()
        self._alis_rapor_baslik("TEDARİKÇİ EKSTRESİ (ORTALAMA VALÖRLÜ / AĞIRLIKLI)")
        self.ekstre_ozet = ttk.Label(self.icerik, text="Tedarikçi seçip raporu getirin.")
        self.ekstre_ozet.pack(anchor="w", pady=(8, 0))
        self._ekstre_ham = None
        self._ekstre_cari = None
        etiketler, eslesme = self._cari_secenekleri(cari_turu="Tedarikçi")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=(10, 4))
        ttk.Label(ust, text="Tedarikçi:").pack(side="left")
        self.ekstre_musteri = ttk.Combobox(ust, values=etiketler, width=36)
        self.ekstre_musteri.pack(side="left", padx=6)
        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(0, 6))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        self.ekstre_baslangic = ttk.Entry(filtre, width=11)
        self.ekstre_baslangic.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        self.ekstre_bitis = ttk.Entry(filtre, width=11)
        self.ekstre_bitis.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Belge no:").pack(side="left")
        self.ekstre_belge = ttk.Entry(filtre, width=14)
        self.ekstre_belge.pack(side="left", padx=(4, 10))
        ttk.Label(filtre, text="Belge türü:").pack(side="left")
        self.ekstre_tur = ttk.Combobox(
            filtre,
            values=("Tümü", "Alış", "Tahsilat", "Ödeme", "Cari Virman", "KK Çekimi", "Alış İadesi"),
            state="readonly",
            width=14,
        )
        self.ekstre_tur.set("Tümü")
        self.ekstre_tur.pack(side="left", padx=(4, 10))
        ttk.Button(filtre, text="Raporu Getir / Uygula", command=lambda: self._ekstre_yenile(eslesme)).pack(
            side="left", padx=4
        )
        self.ekstre_tablo = self._rapor_tablo(
            self.icerik,
            ("tarih", "tur", "belge", "aciklama", "borc", "alacak", "bakiye", "gun"),
            ("Tarih", "Tür", "Belge No", "Açıklama", "Borç", "Alacak", "Bakiye", "Gün"),
            (90, 110, 130, 200, 110, 110, 120, 70),
        )

    def rapor_stok_detayli_tedarikci_ekstre(self):
        self._icerigi_temizle()
        self._alis_rapor_baslik("STOK DETAYLI TEDARİKÇİ EKSTRESİ")
        self.stok_ekstre_ozet = ttk.Label(
            self.icerik,
            text="Alış fatura toplamları + stok satırları; borç / alacak / bakiye net görünür.",
        )
        self.stok_ekstre_ozet.pack(anchor="w", pady=(8, 0))
        self._stok_ekstre_ham = None
        self._stok_ekstre_cari = None
        etiketler, eslesme = self._cari_secenekleri(cari_turu="Tedarikçi")
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", pady=(10, 4))
        ttk.Label(ust, text="Tedarikçi:").pack(side="left")
        self.stok_ekstre_musteri = ttk.Combobox(ust, values=etiketler, width=36)
        self.stok_ekstre_musteri.pack(side="left", padx=6)
        filtre = ttk.Frame(self.icerik)
        filtre.pack(fill="x", pady=(0, 6))
        ttk.Label(filtre, text="Başlangıç:").pack(side="left")
        self.stok_ekstre_bas = ttk.Entry(filtre, width=11)
        self.stok_ekstre_bas.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Bitiş:").pack(side="left")
        self.stok_ekstre_bit = ttk.Entry(filtre, width=11)
        self.stok_ekstre_bit.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Stok:").pack(side="left")
        self.stok_ekstre_stok = ttk.Entry(filtre, width=16)
        self.stok_ekstre_stok.pack(side="left", padx=(4, 8))
        ttk.Label(filtre, text="Belge türü:").pack(side="left")
        self.stok_ekstre_tur = ttk.Combobox(
            filtre,
            values=("Tümü", "Alış Faturası", "Tahsilat", "Ödeme", "Cari Virman", "KK Çekimi", "Alış İadesi"),
            state="readonly",
            width=14,
        )
        self.stok_ekstre_tur.set("Tümü")
        self.stok_ekstre_tur.pack(side="left", padx=(4, 8))
        ttk.Button(
            filtre, text="Raporu Getir / Uygula",
            command=lambda: self._stok_ekstre_yenile(eslesme),
        ).pack(side="left", padx=4)
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(8, 0))
        kolonlar = (
            "tarih", "tur", "belge", "aciklama", "urun", "miktar", "fiyat",
            "satir_tutar", "lot", "borc", "alacak", "bakiye",
        )
        self.stok_ekstre_tablo = ttk.Treeview(cerceve, columns=kolonlar, show="tree headings")
        basliklar = {
            "tarih": "Tarih", "tur": "Belge Türü", "belge": "Belge No", "aciklama": "Açıklama",
            "urun": "Stok", "miktar": "Miktar", "fiyat": "Birim Fiyat", "satir_tutar": "Satır Tutarı",
            "lot": "Lot", "borc": "Borç", "alacak": "Alacak", "bakiye": "Bakiye",
        }
        genislikler = {
            "tarih": 85, "tur": 110, "belge": 120, "aciklama": 150, "urun": 170, "miktar": 70,
            "fiyat": 90, "satir_tutar": 95, "lot": 120, "borc": 100, "alacak": 100, "bakiye": 110,
        }
        self.stok_ekstre_tablo.heading("#0", text="")
        self.stok_ekstre_tablo.column("#0", width=22, stretch=False)
        for kolon in kolonlar:
            self.stok_ekstre_tablo.heading(kolon, text=basliklar[kolon])
            self.stok_ekstre_tablo.column(kolon, width=genislikler[kolon])
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.stok_ekstre_tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.stok_ekstre_tablo.xview)
        self.stok_ekstre_tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.stok_ekstre_tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        self.stok_ekstre_tablo.tag_configure("belge", font=("Segoe UI", 9, "bold"))
        self.stok_ekstre_tablo.tag_configure("stok", foreground="#333333")

    def rapor_alis_ozeti(self):
        self._icerigi_temizle()
        self._alis_rapor_baslik("SATIN ALMA ÖZETİ")
        from database.alis_faturasi_service import AlisFaturasiService
        kayitlar = AlisFaturasiService.listele()
        aktif = [k for k in kayitlar if k["fatura"].durum != "İPTAL"]
        ciro = sum((k["genel_toplam"] for k in aktif), Decimal("0"))
        odeme = sum((k["fatura"].odeme_tutari or Decimal("0") for k in aktif), Decimal("0"))
        ozet = ttk.Frame(self.icerik)
        ozet.pack(fill="x", pady=10)
        for baslik, deger in (
            ("Fatura Sayısı", str(len(aktif))),
            ("Toplam Alış", para_goster(ciro)),
            ("Ödenen", para_goster(odeme)),
            ("Açık", para_goster(ciro - odeme)),
        ):
            kutu = ttk.LabelFrame(ozet, text=baslik, padding=10)
            kutu.pack(side="left", expand=True, fill="x", padx=4)
            ttk.Label(kutu, text=deger, font=("Segoe UI", 12, "bold")).pack()
        tablo = self._rapor_tablo(
            self.icerik,
            ("no", "tarih", "tedarikci", "genel", "odeme", "durum"),
            ("Fatura No", "Tarih", "Tedarikçi", "Genel Toplam", "Ödeme", "Durum"),
            (140, 90, 220, 110, 110, 90),
        )
        for k in aktif:
            f = k["fatura"]
            tablo.insert("", "end", values=(
                f.fatura_no, tarih_goster(f.fatura_tarihi),
                f.cari.unvan if f.cari else "",
                para_goster(k["genel_toplam"]), para_goster(f.odeme_tutari or 0), f.durum,
            ))

    def alis_siparisleri_goster(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from alis_ui import AlisSiparisiDialog
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIN ALMA SİPARİŞLERİ", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(10, 0))
        kolonlar = ("no", "tarih", "termin", "kod", "tedarikci", "toplam", "odeme", "kalan", "durum")
        basliklar = {
            "no": "Sipariş No", "tarih": "Tarih", "termin": "Termin", "kod": "Kod",
            "tedarikci": "Tedarikçi", "toplam": "Toplam", "odeme": "Ödeme", "kalan": "Kalan", "durum": "Durum",
        }
        self.alis_siparis_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon in kolonlar:
            self.alis_siparis_tablosu.heading(kolon, text=basliklar[kolon])
            self.alis_siparis_tablosu.column(kolon, width=120)
        self.alis_siparis_tablosu.column("tedarikci", width=200)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.alis_siparis_tablosu.yview)
        self.alis_siparis_tablosu.configure(yscrollcommand=dikey.set)
        self.alis_siparis_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.alis_siparis_tablosu.bind("<Double-1>", lambda _e: self.alis_siparis_ac())

        def yenile():
            for item in self.alis_siparis_tablosu.get_children():
                self.alis_siparis_tablosu.delete(item)
            for kayit in AlisSiparisiService.listele():
                s = kayit["siparis"]
                t = kayit["tedarikci"]
                self.alis_siparis_tablosu.insert("", "end", iid=str(s.id), values=(
                    s.siparis_no, tarih_goster(s.siparis_tarihi), tarih_goster(s.termin_tarihi),
                    t.cari_kodu if t else "", t.unvan if t else "",
                    para_goster(kayit["toplam"]), para_goster(kayit["odeme"]),
                    para_goster(kayit["kalan"]), s.durum,
                ))
        self._alis_siparis_yenile = yenile

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)

        def yeni():
            dialog = AlisSiparisiDialog(self)
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        def ac():
            secim = self.alis_siparis_tablosu.selection()
            if not secim:
                messagebox.showinfo("Seçim", "Sipariş seçin.", parent=self)
                return
            siparis = AlisSiparisiService.getir(int(secim[0]))
            if siparis:
                dialog = AlisSiparisiDialog(self, siparis=siparis)
                self.wait_window(dialog)
                if dialog.result:
                    yenile()

        def iptal():
            secim = self.alis_siparis_tablosu.selection()
            if not secim:
                return
            if messagebox.askyesno("İptal", "Sipariş iptal edilsin mi?", parent=self):
                try:
                    AlisSiparisiService.iptal_et(int(secim[0]))
                except ValueError as hata:
                    messagebox.showerror("İptal", str(hata), parent=self)
                yenile()

        def irsaliyeye():
            secim = self.alis_siparis_tablosu.selection()
            if not secim:
                return
            from alis_ui import AlisIrsaliyesiDialog
            siparis = AlisSiparisiService.getir(int(secim[0]))
            if not siparis:
                return
            if siparis.durum == "İPTAL":
                messagebox.showwarning("İrsaliye", "İptal edilmiş sipariş irsaliyeye çevrilemez.", parent=self)
                return
            acik = any(s.miktar - s.irsaliyelenen_miktar > 0 for s in siparis.satirlar)
            if not acik:
                messagebox.showinfo("İrsaliye", "Bu siparişte irsaliyelenecek açık miktar kalmadı.", parent=self)
                return
            dialog = AlisIrsaliyesiDialog(self, siparis=siparis)
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        def faturaya():
            secim = self.alis_siparis_tablosu.selection()
            if not secim:
                return
            from alis_ui import AlisFaturasiDialog
            siparis = AlisSiparisiService.getir(int(secim[0]))
            if not siparis:
                return
            if siparis.durum == "İPTAL":
                messagebox.showwarning("Fatura", "İptal edilmiş sipariş faturaya çevrilemez.", parent=self)
                return
            acik = any(s.miktar - s.faturalanan_miktar > 0 for s in siparis.satirlar)
            if not acik:
                messagebox.showinfo("Fatura", "Bu siparişte faturalanacak açık miktar kalmadı.", parent=self)
                return
            dialog = AlisFaturasiDialog(
                self, siparis=siparis,
                cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"),
            )
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        self.alis_siparis_ac = ac
        ttk.Button(alt, text="Yeni Sipariş", command=yeni).pack(side="left")
        ttk.Button(alt, text="Aç / Düzenle", command=ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İrsaliyeye Çevir", command=irsaliyeye).pack(side="left")
        ttk.Button(alt, text="Faturaya Çevir", command=faturaya).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal Et", command=iptal).pack(side="left")
        yenile()

    def alis_irsaliyeleri_goster(self):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from alis_ui import AlisIrsaliyesiDialog, AlisFaturasiDialog
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIN ALMA İRSALİYELERİ", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(10, 0))
        kolonlar = ("no", "tarih", "kod", "tedarikci", "siparis", "toplam", "fatura", "kalan", "durum")
        self.alis_irs_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik, w in (
            ("no", "İrsaliye No", 140), ("tarih", "Tarih", 90), ("kod", "Kod", 80),
            ("tedarikci", "Tedarikçi", 180), ("siparis", "Sipariş", 130),
            ("toplam", "Toplam", 100), ("fatura", "Faturalanan", 100), ("kalan", "Kalan", 100),
            ("durum", "Durum", 110),
        ):
            self.alis_irs_tablosu.heading(kolon, text=baslik)
            self.alis_irs_tablosu.column(kolon, width=w)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.alis_irs_tablosu.yview)
        self.alis_irs_tablosu.configure(yscrollcommand=dikey.set)
        self.alis_irs_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.alis_irs_tablosu.bind("<Double-1>", lambda _e: ac())

        def yenile():
            for item in self.alis_irs_tablosu.get_children():
                self.alis_irs_tablosu.delete(item)
            for kayit in AlisIrsaliyesiService.listele():
                i = kayit["irsaliye"]
                cari = i.cari
                siparis = i.siparis
                self.alis_irs_tablosu.insert("", "end", iid=str(i.id), values=(
                    i.irsaliye_no, tarih_goster(i.irsaliye_tarihi),
                    cari.cari_kodu if cari else "", cari.unvan if cari else "",
                    siparis.siparis_no if siparis else "",
                    para_goster(kayit["toplam"]), para_goster(kayit["faturalanan"]),
                    para_goster(kayit["kalan"]), i.durum,
                ))

        def yeni():
            dialog = AlisIrsaliyesiDialog(self)
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        def ac():
            secim = self.alis_irs_tablosu.selection()
            if not secim:
                messagebox.showinfo("Seçim", "İrsaliye seçin.", parent=self)
                return
            irs = AlisIrsaliyesiService.getir(int(secim[0]))
            if irs:
                dialog = AlisIrsaliyesiDialog(self, irsaliye=irs)
                self.wait_window(dialog)
                if dialog.result:
                    yenile()

        def faturaya():
            secim = self.alis_irs_tablosu.selection()
            if not secim:
                messagebox.showinfo("Seçim", "İrsaliye seçin.", parent=self)
                return
            irs = AlisIrsaliyesiService.getir(int(secim[0]))
            if irs:
                dialog = AlisFaturasiDialog(
                    self, irsaliye=irs,
                    cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"),
                )
                self.wait_window(dialog)
                if dialog.result:
                    yenile()

        def iptal():
            secim = self.alis_irs_tablosu.selection()
            if secim and messagebox.askyesno("İptal", "İrsaliye iptal edilsin mi?", parent=self):
                try:
                    AlisIrsaliyesiService.iptal_et(int(secim[0]))
                except ValueError as hata:
                    messagebox.showerror("İptal", str(hata), parent=self)
                yenile()

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni İrsaliye", command=yeni).pack(side="left")
        ttk.Button(alt, text="Aç / Düzenle", command=ac).pack(side="left", padx=8)
        ttk.Button(alt, text="Faturaya Çevir", command=faturaya).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=iptal).pack(side="left", padx=8)
        yenile()

    def alis_faturalari_goster(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from alis_ui import AlisFaturasiDialog, AlisIadeFaturasiDialog
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIN ALMA FATURALARI", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(10, 0))
        kolonlar = ("no", "tarih", "saat", "vade", "tedarikci", "siparis", "irsaliye", "depo", "genel", "odeme", "kalan", "durum")
        self.alis_fat_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik, w in (
            ("no", "Fatura No", 130), ("tarih", "Tarih", 85), ("saat", "Saat", 60), ("vade", "Vade", 85),
            ("tedarikci", "Tedarikçi", 170), ("siparis", "Sipariş", 110), ("irsaliye", "İrsaliye", 110),
            ("depo", "Depo", 90), ("genel", "Genel", 95), ("odeme", "Ödeme", 95),
            ("kalan", "Kalan", 95), ("durum", "Durum", 80),
        ):
            self.alis_fat_tablosu.heading(kolon, text=baslik)
            self.alis_fat_tablosu.column(kolon, width=w)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.alis_fat_tablosu.yview)
        self.alis_fat_tablosu.configure(yscrollcommand=dikey.set)
        self.alis_fat_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.alis_fat_tablosu.bind("<Double-1>", lambda _e: ac())

        def yenile():
            for item in self.alis_fat_tablosu.get_children():
                self.alis_fat_tablosu.delete(item)
            for kayit in AlisFaturasiService.listele():
                f = kayit["fatura"]
                toplam = kayit["genel_toplam"]
                odeme = f.odeme_tutari or Decimal("0")
                self.alis_fat_tablosu.insert("", "end", iid=str(f.id), values=(
                    f.fatura_no, tarih_goster(f.fatura_tarihi), f.islem_saati or "", tarih_goster(f.vade_tarihi),
                    f.cari.unvan if f.cari else "",
                    f.siparis.siparis_no if f.siparis else "",
                    f.irsaliye.irsaliye_no if f.irsaliye else "",
                    f.depo, para_goster(toplam), para_goster(odeme),
                    para_goster(toplam - odeme), f.durum,
                ))

        def yeni():
            dialog = AlisFaturasiDialog(self, cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"))
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        def ac():
            secim = self.alis_fat_tablosu.selection()
            if not secim:
                messagebox.showinfo("Seçim", "Fatura seçin.", parent=self)
                return
            fatura = AlisFaturasiService.getir(int(secim[0]))
            if fatura:
                dialog = AlisFaturasiDialog(
                    self, fatura=fatura,
                    cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"),
                )
                self.wait_window(dialog)
                if dialog.result:
                    yenile()

        def iptal():
            secim = self.alis_fat_tablosu.selection()
            if secim and messagebox.askyesno("İptal", "Fatura iptal edilsin mi? Stok girişi geri alınır.", parent=self):
                try:
                    AlisFaturasiService.iptal_et(int(secim[0]))
                except ValueError as hata:
                    messagebox.showerror("İptal", str(hata), parent=self)
                yenile()

        def iade():
            secim = self.alis_fat_tablosu.selection()
            if not secim:
                messagebox.showinfo("Seçim", "İade için fatura seçin.", parent=self)
                return
            fatura = AlisFaturasiService.getir(int(secim[0]))
            if not fatura:
                return
            if fatura.durum == "İPTAL":
                messagebox.showwarning("İade", "İptal faturalardan iade oluşturulamaz.", parent=self)
                return
            dialog = AlisIadeFaturasiDialog(self, kaynak_fatura=fatura)
            self.wait_window(dialog)
            if dialog.result:
                messagebox.showinfo("İade", "Satın alma iade faturası kaydedildi.", parent=self)
                self.alis_iade_faturalari_goster()

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Fatura", command=yeni).pack(side="left")
        ttk.Button(alt, text="Aç / Düzenle", command=ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İade Faturası", command=iade).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=iptal).pack(side="left", padx=8)
        yenile()

    def alis_iade_faturalari_goster(self):
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from alis_ui import AlisIadeFaturasiDialog
        self._icerigi_temizle()
        ttk.Label(self.icerik, text="SATIN ALMA İADE FATURALARI", style="Baslik.TLabel").pack(anchor="w")
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True, pady=(10, 0))
        kolonlar = ("no", "tarih", "tedarikci", "genel", "durum")
        self.alis_iade_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik, w in (
            ("no", "İade No", 150), ("tarih", "Tarih", 100), ("tedarikci", "Tedarikçi", 240),
            ("genel", "Genel", 120), ("durum", "Durum", 100),
        ):
            self.alis_iade_tablosu.heading(kolon, text=baslik)
            self.alis_iade_tablosu.column(kolon, width=w)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.alis_iade_tablosu.yview)
        self.alis_iade_tablosu.configure(yscrollcommand=dikey.set)
        self.alis_iade_tablosu.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")

        def yenile():
            for item in self.alis_iade_tablosu.get_children():
                self.alis_iade_tablosu.delete(item)
            for kayit in AlisIadeFaturasiService.listele():
                i = kayit["iade"]
                self.alis_iade_tablosu.insert("", "end", iid=str(i.id), values=(
                    i.iade_no, tarih_goster(i.iade_tarihi),
                    i.cari.unvan if i.cari else "",
                    para_goster(kayit.get("genel_toplam", 0)), i.durum,
                ))

        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=10)

        def yeni():
            dialog = AlisIadeFaturasiDialog(self)
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        def ac():
            secim = self.alis_iade_tablosu.selection()
            if not secim:
                return
            iade = AlisIadeFaturasiService.getir(int(secim[0]))
            if iade:
                dialog = AlisIadeFaturasiDialog(self, iade=iade)
                self.wait_window(dialog)
                if dialog.result:
                    yenile()

        def iptal():
            secim = self.alis_iade_tablosu.selection()
            if secim and messagebox.askyesno("İptal", "İade iptal edilsin mi?", parent=self):
                try:
                    AlisIadeFaturasiService.iptal_et(int(secim[0]))
                except ValueError as hata:
                    messagebox.showerror("İptal", str(hata), parent=self)
                yenile()

        ttk.Button(alt, text="Yeni İade", command=yeni).pack(side="left")
        ttk.Button(alt, text="Aç / Düzenle", command=ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal Et", command=iptal).pack(side="left")
        yenile()
