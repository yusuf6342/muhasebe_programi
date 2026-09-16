import json
import os
import re
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.cari_service import CariService
from database.firma_service import FirmaService
from database.kk_cekimi_service import KkCekimiService
from database.rapor_service import RaporService
from database.satis_irsaliyesi_service import SatisIrsaliyesiService
from database.satis_faturasi_service import SatisFaturasiService
from database.alis_faturasi_service import AlisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from database.satis_siparisi_service import (
    MALIYET_YONTEMLERI,
    ODEME_SEKILLERI,
    SIPARIS_DURUMLARI,
    SatisSiparisiService,
    decimal,
)
from product_provider import search_prices, search_products
from database.stok_service import ALIŞ_FIYAT_ADLARI, SATIS_FIYAT_ADLARI, StokService
from database.finans_service import FinansService
from stok_ui import StokKartiDialog
from depo_transfer_ui import depo_transfer_listesini_goster
from stok_birlestir_ui import stok_birlestir_sayfasi_goster
from stok_paket_ui import stok_paket_sayfasi_goster
from stok_barkod_ui import stok_barkod_basimi_goster as barkod_basim_sayfasini_ac
from stok_rapor_ui import stok_raporlari_menusu_goster
from stok_toplu_fiyat_ui import toplu_fiyat_sayfasi_goster
from finans_ui import finans_menusu_goster
from gelir_gider_ui import gelir_gider_menusu_goster
from genel_muhasebe_ui import genel_muhasebe_menusu_goster
from ozet_tablolar_ui import ozet_tablolar_menusu_goster
from doviz_kur_ui import doviz_kur_yonetimi_goster
from doviz_rapor_ui import doviz_raporlari_goster
from satis_ui import (
    cari_hesap_islemleri_goster,
    satis_raporlar_hub_goster,
    satislar_hub_goster,
)
from database.doviz_service import DovizService
from database.models.doviz import PARA_BIRIMLERI
from doviz_fatura_panel import (
    doviz_paneli_kur,
    doviz_para_birimi_degisti,
    doviz_satir_kaydet_oncesi,
    doviz_verilerini_doldur,
    doviz_verilerini_topla,
    doviz_ozet_guncelle,
)
from ui_takvim import saat_dogrula, saat_varsayilan, takvim_butonu
from urun_sec_ui import UrunSecDialog
from ui_bg import arka_planda

# Geriye dönük uyumluluk
ProductSelectionDialog = UrunSecDialog

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")
KDV_ORANLARI = ("0", "1", "8", "10", "18", "20")

# Fatura satır tablosu kolon tanımları: (anahtar, başlık, varsayılan genişlik, varsayılan görünür)
FATURA_SATIR_KOLON_TANIMLARI = (
    ("sira", "No", 40, True),
    ("sec", "👁", 44, True),
    ("barkod", "Barkod", 100, True),
    ("urun_kodu", "Ürün Kodu", 90, True),
    ("urun_adi", "Ürün Adı", 140, True),
    ("aciklama", "Açıklama", 90, True),
    ("miktar", "Miktar", 78, True),
    ("birim", "Birim", 70, True),
    ("fiyat", "Birim Fiyat", 90, True),
    ("iskonto", "İsk.1+2+3", 90, True),
    ("iskonto_tutar", "İsk. Tutar", 90, True),
    ("kdv", "KDV", 60, True),
    ("net_birim_kdv", "Net Br.+KDV", 100, True),
    ("lot", "Lot No", 90, True),
    ("lot_cikisi", "Lot Çıkışı", 90, True),
    ("toplam", "Satır Toplamı", 100, True),
    ("irsaliye", "Siparişten Gelen", 100, True),
    ("fatura", "İrsaliyeden Gelen", 100, True),
    ("acik", "Fatura Miktarı", 100, True),
)

# Fatura giriş satırında hesaplanan (salt okunur) alanlar
FATURA_SATIR_HESAPLANAN_ALANLAR = frozenset({"iskonto_tutari", "net_birim_kdvli"})


def fatura_kolon_ayar_dosyasi() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / "fatura_satir_kolonlari.json"


def fatura_kolon_varsayilan_ayarlari() -> dict:
    return {
        anahtar: {"baslik": baslik, "genislik": genislik, "gorunur": gorunur}
        for anahtar, baslik, genislik, gorunur in FATURA_SATIR_KOLON_TANIMLARI
    }


def fatura_kolon_ayarlari_yukle() -> dict:
    varsayilan = fatura_kolon_varsayilan_ayarlari()
    yol = fatura_kolon_ayar_dosyasi()
    if not yol.exists():
        return varsayilan
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return varsayilan
    birlesik = {}
    for anahtar, varsay in varsayilan.items():
        gelen = kayit.get(anahtar) or {}
        try:
            genislik = int(gelen.get("genislik", varsay["genislik"]))
        except (TypeError, ValueError):
            genislik = varsay["genislik"]
        birlesik[anahtar] = {
            "baslik": varsay["baslik"],
            "genislik": max(20, min(genislik, 600)),
            "gorunur": bool(gelen.get("gorunur", varsay["gorunur"])),
        }
    return birlesik


def fatura_kolon_ayarlari_kaydet(ayarlar: dict) -> None:
    yol = fatura_kolon_ayar_dosyasi()
    temiz = {}
    for anahtar, _, _, _ in FATURA_SATIR_KOLON_TANIMLARI:
        cfg = ayarlar.get(anahtar) or {}
        temiz[anahtar] = {
            "genislik": int(cfg.get("genislik", 90)),
            "gorunur": bool(cfg.get("gorunur", True)),
        }
    yol.write_text(json.dumps(temiz, ensure_ascii=False, indent=2), encoding="utf-8")


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def kurus_yuvarla(tutar, yon="normal") -> Decimal:
    """Tutarı kuruşa (0,01) yuvarlar. yon: normal | yukari | asagi."""
    t = Decimal(str(tutar or 0))
    if yon == "yukari":
        return t.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    if yon == "asagi":
        return t.quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    return t.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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


from cari_kart_ui import (
    NotlarDialog,
    CariUyariDialog,
    cari_uyari_goster,
    CariMuhasebeDialog,
    CariDialog,
)


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
            self.fiyatlar = StokService.satis_fiyatlari(product_code)
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
    def __init__(
        self,
        parent,
        veri=None,
        odeme_sekilleri=None,
        max_tutar=None,
        varsayilan_tutar=None,
    ):
        super().__init__(parent)
        self.result = None
        self.title("Tahsilat")
        self.transient(parent)
        self.grab_set()
        self._odeme_sekilleri = tuple(odeme_sekilleri) if odeme_sekilleri else ODEME_SEKILLERI
        self._max_tutar = None
        if max_tutar is not None:
            try:
                self._max_tutar = decimal(max_tutar, "Kalan tahsilat", Decimal("0"))
            except ValueError:
                self._max_tutar = None
        alanlar = (
            ("Tahsilat Tarihi", "tahsilat_tarihi"),
            ("Tutar", "tutar"),
            ("Ödeme Şekli", "odeme_sekli"),
            ("Hesap", "hesap"),
            ("Açıklama", "aciklama"),
        )
        self.girdiler = {}
        for satir, (baslik, alan) in enumerate(alanlar):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=8, pady=5, sticky="w")
            if alan == "odeme_sekli":
                widget = ttk.Combobox(
                    self, values=self._odeme_sekilleri, state="readonly", width=30
                )
            elif alan == "hesap":
                widget = ttk.Combobox(self, values=(), state="readonly", width=30)
            else:
                widget = ttk.Entry(self, width=32)
            widget.grid(row=satir, column=1, padx=8, pady=5)
            self.girdiler[alan] = widget
        self.girdiler["tahsilat_tarihi"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["odeme_sekli"].set(self._odeme_sekilleri[0])
        self.girdiler["odeme_sekli"].bind("<<ComboboxSelected>>", self._hesaplari_guncelle)
        if veri:
            for alan, widget in self.girdiler.items():
                deger = veri.get(alan, "")
                if alan == "tahsilat_tarihi" and hasattr(deger, "strftime"):
                    deger = deger.strftime("%d.%m.%Y")
                if isinstance(widget, ttk.Combobox):
                    widget.set("" if deger is None else str(deger))
                else:
                    widget.delete(0, "end")
                    widget.insert(0, "" if deger is None else str(deger))
            # Eski kayıtta farklı ödeme şekli adı varsa listeye ekle
            sekil = (veri.get("odeme_sekli") or "").strip()
            if sekil and sekil not in self._odeme_sekilleri:
                self._odeme_sekilleri = self._odeme_sekilleri + (sekil,)
                self.girdiler["odeme_sekli"]["values"] = self._odeme_sekilleri
                self.girdiler["odeme_sekli"].set(sekil)
        elif varsayilan_tutar is not None:
            try:
                onerilen = decimal(varsayilan_tutar, "Tahsilat", Decimal("0"))
                if onerilen > 0:
                    self.girdiler["tutar"].insert(0, f"{onerilen:.2f}".replace(".", ","))
            except ValueError:
                pass
        self._hesaplari_guncelle(koru_secim=bool(veri))
        bilgi_satir = 5
        if self._max_tutar is not None:
            ttk.Label(
                self,
                text=f"En fazla: {para_goster(self._max_tutar)}",
                foreground="#1565c0",
            ).grid(row=bilgi_satir, column=0, columnspan=2, padx=8, pady=(0, 2), sticky="w")
            bilgi_satir += 1
        ttk.Button(self, text="İptal", command=self.destroy).grid(row=bilgi_satir, column=0, padx=8, pady=10)
        ttk.Button(self, text="Ekle", command=self.kaydet).grid(
            row=bilgi_satir, column=1, padx=8, pady=10, sticky="e"
        )

    def _hesaplari_guncelle(self, _event=None, koru_secim=False):
        sekil = self.girdiler["odeme_sekli"].get().strip()
        hesaplar = FinansService.tahsilat_hesaplari(sekil)
        adlar = tuple(h.hesap_adi for h in hesaplar)
        onceki = self.girdiler["hesap"].get().strip() if koru_secim else ""
        self.girdiler["hesap"]["values"] = adlar
        if onceki and onceki in adlar:
            self.girdiler["hesap"].set(onceki)
        elif adlar:
            self.girdiler["hesap"].set(adlar[0])
        else:
            self.girdiler["hesap"].set("")

    def kaydet(self):
        veri = {alan: widget.get().strip() for alan, widget in self.girdiler.items()}
        if not veri["odeme_sekli"]:
            messagebox.showwarning("Eksik bilgi", "Ödeme şekli seçin.", parent=self)
            return
        if not veri["hesap"]:
            messagebox.showwarning(
                "Eksik hesap",
                "Seçilen ödeme şekline uygun kasa/banka/POS hesabı bulunamadı veya seçilmedi.",
                parent=self,
            )
            return
        try:
            veri["tahsilat_tarihi"] = datetime.strptime(veri["tahsilat_tarihi"], "%d.%m.%Y").date()
            tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
            if self._max_tutar is not None and tutar > self._max_tutar:
                raise ValueError(
                    f"Tahsilat tutarı kalan tutarı ({para_goster(self._max_tutar)}) aşamaz."
                )
            veri["tutar"] = tutar
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
        bakiyeler = {o["cari"].id: o["bakiye"] for o in CariService.listele(hizli=True)}
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

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = KkCekimiService.getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title(
            "Kredi Kartı Çekim Fişi — Güncelle" if belge_no else "Yeni Kredi Kartı Çekim Fişi"
        )
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.musteri_map = {}
        self.tedarikci_map = {}
        self._olustur()
        self._mevcutu_yukle()

    def _olustur(self):
        ttk.Label(self, text="KREDİ KARTI ÇEKİM FİŞİ", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 4), sticky="w"
        )
        ttk.Label(
            self,
            text="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit serbest girilir; kasa/banka hesabına işlem düşmez.",
        ).grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        musteriler = list(CariService.aktif_musteriler())
        ekstra = [
            c for c in CariService.aktif_cariler()
            if (c.cari_turu or "").casefold().startswith("muster")
            and c.id not in {m.id for m in musteriler}
        ]
        musteriler.extend(ekstra)
        tedarikciler = CariService.aktif_tedarikciler()
        self.musteri_map = {f"{c.cari_kodu} - {c.unvan}": c for c in musteriler}
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.bakiyeler = {o["cari"].id: o["bakiye"] for o in CariService.listele(hizli=True)}

        self.girdiler = {}
        satir = 2
        for baslik, alan, degerler in (
            ("Müşteri (Alacak)", "musteri", list(self.musteri_map)),
            ("Tedarikçi (Borç)", "tedarikci", list(self.tedarikci_map)),
            ("Tarih", "tarih", None),
            ("Tutar", "tutar", None),
            ("Kartın Ait Olduğu Banka", "banka", None),
            ("Taksit Sayısı", "taksit_sayisi", None),
            ("Açıklama", "aciklama", None),
        ):
            ttk.Label(self, text=baslik).grid(row=satir, column=0, padx=12, pady=5, sticky="w")
            if degerler is not None:
                widget = ttk.Combobox(self, values=degerler, width=48, state="readonly")
            else:
                widget = ttk.Entry(self, width=50)
            widget.grid(row=satir, column=1, padx=12, pady=5, sticky="w")
            self.girdiler[alan] = widget
            satir += 1

        self.girdiler["tarih"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.girdiler["taksit_sayisi"].insert(0, "1")
        if self.musteri_map:
            self.girdiler["musteri"].set(next(iter(self.musteri_map)))
        if self.tedarikci_map:
            self.girdiler["tedarikci"].set(next(iter(self.tedarikci_map)))

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
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Fişi Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        self._guncelle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.girdiler["tarih"].delete(0, "end")
        self.girdiler["tarih"].insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.girdiler["tutar"].delete(0, "end")
        self.girdiler["tutar"].insert(0, str(m["tutar"]))
        self.girdiler["banka"].delete(0, "end")
        self.girdiler["banka"].insert(0, m["banka"] or "")
        self.girdiler["taksit_sayisi"].delete(0, "end")
        self.girdiler["taksit_sayisi"].insert(0, str(m["taksit_sayisi"]))
        self.girdiler["aciklama"].delete(0, "end")
        if m.get("aciklama"):
            self.girdiler["aciklama"].insert(0, m["aciklama"])
        if m.get("musteri_etiket") and m["musteri_etiket"] in self.musteri_map:
            self.girdiler["musteri"].set(m["musteri_etiket"])
        else:
            for etiket, c in self.musteri_map.items():
                if c.id == m.get("musteri_id"):
                    self.girdiler["musteri"].set(etiket)
                    break
        if m.get("tedarikci_etiket") and m["tedarikci_etiket"] in self.tedarikci_map:
            self.girdiler["tedarikci"].set(m["tedarikci_etiket"])
        else:
            for etiket, c in self.tedarikci_map.items():
                if c.id == m.get("tedarikci_id"):
                    self.girdiler["tedarikci"].set(etiket)
                    break
        self._guncelle()

    def _guncelle(self, _event=None):
        musteri = self.musteri_map.get(self.girdiler["musteri"].get())
        tedarikci = self.tedarikci_map.get(self.girdiler["tedarikci"].get())
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
        musteri = self.musteri_map.get(self.girdiler["musteri"].get())
        tedarikci = self.tedarikci_map.get(self.girdiler["tedarikci"].get())
        if not musteri or not tedarikci:
            messagebox.showwarning("Eksik bilgi", "Müşteri ve tedarikçi seçin.", parent=self)
            return
        if musteri.id == tedarikci.id:
            messagebox.showwarning("Geçersiz seçim", "Müşteri ve tedarikçi aynı olamaz.", parent=self)
            return
        banka = self.girdiler["banka"].get().strip()
        if not banka:
            messagebox.showwarning("Eksik banka", "Kartın ait olduğu banka adını yazın.", parent=self)
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
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Çekim kaydedilemedi", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("Çekim kaydedilemedi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "KK çekim fişi",
            f"{'Güncellendi' if self.belge_no else 'Kaydedildi'}: {self.result['belge_no']}\n"
            f"Alacak: {musteri.cari_kodu}  →  Borç: {tedarikci.cari_kodu}\n"
            f"Banka: {banka} / {self.result['taksit_sayisi']} taksit",
            parent=self,
        )
        self.destroy()


class UrunHareketGecmisiDialog(tk.Toplevel):
    """Fatura satırındaki ürün için satış / alış geçmişi."""

    def __init__(self, parent, baslik, urun_kodu, kayitlar, kolonlar, basliklar):
        super().__init__(parent)
        self.title(baslik)
        self.geometry("820x420")
        self.minsize(640, 320)
        self.transient(parent)
        self.grab_set()
        ttk.Label(
            self,
            text=f"{baslik}  |  Ürün: {urun_kodu}",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 6))
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=4)
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for kolon, baslik_kolon in zip(kolonlar, basliklar):
            self.tablo.heading(kolon, text=baslik_kolon)
            self.tablo.column(kolon, width=120, anchor="w")
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        for sira, kayit in enumerate(kayitlar):
            degerler = []
            for kolon in kolonlar:
                deger = kayit.get(kolon, "")
                if kolon == "tarih" and deger:
                    deger = tarih_goster(deger)
                elif kolon in ("miktar", "net_fiyat") and deger not in ("", None):
                    deger = para_goster(deger) if kolon == "net_fiyat" else str(deger)
                degerler.append(deger)
            self.tablo.insert("", "end", iid=str(sira), values=tuple(degerler))
        if not kayitlar:
            ttk.Label(self, text="Kayıt bulunamadı.", foreground="#a33").pack(
                anchor="w", padx=12, pady=4
            )
        ttk.Button(self, text="Kapat", command=self.destroy).pack(
            anchor="e", padx=12, pady=10
        )


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
            ozet = next((o for o in CariService.listele(hizli=True) if o["cari"].id == musteri.id), None); borc = ozet["bakiye"] if ozet else borc
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

    def _secili_urun_kodu(self) -> str:
        kod = ""
        if "urun_kodu" in getattr(self, "satir_girdileri", {}):
            try:
                kod = self.satir_girdileri["urun_kodu"].get().strip()
            except tk.TclError:
                kod = ""
        if kod:
            return kod
        if hasattr(self, "satir_tablosu"):
            secim = self.satir_tablosu.selection()
            if secim:
                try:
                    return (self.satirlar[int(secim[0])].get("urun_kodu") or "").strip()
                except (ValueError, IndexError, AttributeError):
                    pass
        return ""

    def _urun_musteri_satislari_ac(self):
        kod = self._secili_urun_kodu()
        if not kod:
            messagebox.showinfo("Ürün", "Önce fatura satırında bir ürün seçin / girin.", parent=self)
            return
        musteri = self.musteri_map.get(self.musteri.get())
        if not musteri:
            messagebox.showinfo("Müşteri", "Önce müşteri seçin.", parent=self)
            return
        kayitlar = SatisFaturasiService.urun_satis_hareketleri(kod, cari_id=musteri.id)
        UrunHareketGecmisiDialog(
            self,
            "Bu Müşteriye Satışlar",
            kod,
            kayitlar,
            ("tarih", "miktar", "net_fiyat", "belge_no"),
            ("Tarih", "Adet", "Net Satış Fiyatı", "Fatura No"),
        )

    def _urun_genel_satislari_ac(self):
        kod = self._secili_urun_kodu()
        if not kod:
            messagebox.showinfo("Ürün", "Önce fatura satırında bir ürün seçin / girin.", parent=self)
            return
        kayitlar = SatisFaturasiService.urun_satis_hareketleri(kod)
        UrunHareketGecmisiDialog(
            self,
            "Genel Satışlar",
            kod,
            kayitlar,
            ("tarih", "musteri", "miktar", "net_fiyat", "belge_no"),
            ("Tarih", "Müşteri", "Adet", "Net Satış Fiyatı", "Fatura No"),
        )

    def _urun_alislari_ac(self):
        kod = self._secili_urun_kodu()
        if not kod:
            messagebox.showinfo("Ürün", "Önce fatura satırında bir ürün seçin / girin.", parent=self)
            return
        kayitlar = AlisFaturasiService.urun_alis_hareketleri(kod)
        UrunHareketGecmisiDialog(
            self,
            "Alışlar",
            kod,
            kayitlar,
            ("tarih", "tedarikci", "miktar", "net_fiyat", "belge_no"),
            ("Tarih", "Tedarikçi", "Adet", "Net Alış Fiyatı", "Fatura No"),
        )

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


class FaturaKolonAyarDialog(tk.Toplevel):
    """Fatura satır tablosu kolonlarını göster/gizle ve genişlik ayarla."""

    def __init__(self, parent, ayarlar: dict, on_uygula):
        super().__init__(parent)
        self.title("Fatura Kolon Ayarları")
        self.geometry("480x520")
        self.minsize(420, 400)
        self.transient(parent)
        self.grab_set()
        self.on_uygula = on_uygula
        self.ayarlar = {
            k: {"baslik": v["baslik"], "genislik": int(v["genislik"]), "gorunur": bool(v["gorunur"])}
            for k, v in ayarlar.items()
        }
        self._satirlar = {}

        ttk.Label(
            self,
            text="Kolonları göster/gizle ve genişliklerini ayarlayın.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 6))

        ust = ttk.Frame(self)
        ust.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(ust, text="Tümünü Göster", command=self._tumunu_goster).pack(side="left")
        ttk.Button(ust, text="Tümünü Gizle", command=self._tumunu_gizle).pack(side="left", padx=6)
        ttk.Button(ust, text="Varsayılana Dön", command=self._varsayilan).pack(side="left")

        liste = ttk.Frame(self, padding=8)
        liste.pack(fill="both", expand=True, padx=8, pady=4)
        baslik = ttk.Frame(liste)
        baslik.pack(fill="x")
        ttk.Label(baslik, text="Göster", width=8).pack(side="left")
        ttk.Label(baslik, text="Kolon", width=22).pack(side="left")
        ttk.Label(baslik, text="Genişlik (px)", width=14).pack(side="left")

        canvas = tk.Canvas(liste, highlightthickness=0)
        kaydir = ttk.Scrollbar(liste, orient="vertical", command=canvas.yview)
        ic = ttk.Frame(canvas)
        ic.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ic, anchor="nw")
        canvas.configure(yscrollcommand=kaydir.set)
        canvas.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")

        for anahtar, _, _, _ in FATURA_SATIR_KOLON_TANIMLARI:
            cfg = self.ayarlar[anahtar]
            satir = ttk.Frame(ic)
            satir.pack(fill="x", pady=2)
            gorunur = tk.BooleanVar(value=cfg["gorunur"])
            genislik = tk.IntVar(value=int(cfg["genislik"]))
            ttk.Checkbutton(satir, variable=gorunur, width=4).pack(side="left", padx=(4, 8))
            ttk.Label(satir, text=cfg["baslik"], width=22).pack(side="left")
            spin = ttk.Spinbox(satir, from_=20, to=600, textvariable=genislik, width=8)
            spin.pack(side="left", padx=8)
            self._satirlar[anahtar] = (gorunur, genislik)

        alt = ttk.Frame(self, padding=12)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=8)
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right")

    def _mevcut(self) -> dict:
        sonuc = {}
        for anahtar, (gorunur, genislik) in self._satirlar.items():
            try:
                w = int(genislik.get())
            except (tk.TclError, ValueError, TypeError):
                w = self.ayarlar[anahtar]["genislik"]
            sonuc[anahtar] = {
                "baslik": self.ayarlar[anahtar]["baslik"],
                "genislik": max(20, min(w, 600)),
                "gorunur": bool(gorunur.get()),
            }
        return sonuc

    def _tumunu_goster(self):
        for gorunur, _ in self._satirlar.values():
            gorunur.set(True)

    def _tumunu_gizle(self):
        for gorunur, _ in self._satirlar.values():
            gorunur.set(False)

    def _varsayilan(self):
        varsayilan = fatura_kolon_varsayilan_ayarlari()
        for anahtar, (gorunur, genislik) in self._satirlar.items():
            cfg = varsayilan[anahtar]
            gorunur.set(cfg["gorunur"])
            genislik.set(cfg["genislik"])

    def _uygula(self):
        ayar = self._mevcut()
        if not any(v["gorunur"] for v in ayar.values()):
            messagebox.showwarning("Kolon", "En az bir kolon görünür olmalı.", parent=self)
            return
        self.ayarlar = ayar
        if self.on_uygula:
            self.on_uygula(ayar)

    def _kaydet(self):
        self._uygula()
        if any(v["gorunur"] for v in self.ayarlar.values()):
            fatura_kolon_ayarlari_kaydet(self.ayarlar)
            messagebox.showinfo("Kolon", "Kolon ayarları kaydedildi.", parent=self)


class MusteriSecimDialog(tk.Toplevel):
    """Fatura müşteri satırı: ünvan/kod içinde arama, alfabetik seçim ekranı.

    baslik / kayit_adi ile çek-senet vb. cari seçiminde de yeniden kullanılır.
    """

    def __init__(
        self,
        parent,
        musteriler,
        bakiyeler=None,
        ara="",
        on_select=None,
        baslik="Müşteri Seçimi",
        kayit_adi="müşteri",
    ):
        super().__init__(parent)
        self.on_select = on_select
        self.result = None
        self._musteriler = list(musteriler or [])
        self._bakiyeler = bakiyeler or {}
        self._kayit_adi = (kayit_adi or "müşteri").strip() or "müşteri"
        self.title(baslik or "Müşteri Seçimi")
        self.geometry("640x420")
        self.minsize(520, 320)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara (ünvan / kod):").pack(side="left")
        self.arama = ttk.Entry(ust, width=40)
        self.arama.pack(side="left", padx=8, fill="x", expand=True)
        self.arama.insert(0, (ara or "").strip())
        self.arama.bind("<KeyRelease>", self._filtrele)
        self.arama.bind("<Return>", self._sec)
        self.arama.bind("<Down>", self._listeye_in)
        ttk.Label(
            ust,
            text="İsim içinde arar · alfabetik",
            foreground="#555",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(4, 0))

        orta = ttk.Frame(self, padding=(10, 0))
        orta.pack(fill="both", expand=True)
        orta.columnconfigure(0, weight=1)
        orta.rowconfigure(0, weight=1)
        self.tablo = ttk.Treeview(
            orta,
            columns=("kod", "unvan", "bakiye"),
            show="headings",
            selectmode="browse",
        )
        self.tablo.heading("kod", text="Kod")
        self.tablo.heading("unvan", text="Ünvan")
        self.tablo.heading("bakiye", text="Bakiye")
        self.tablo.column("kod", width=100, anchor="w")
        self.tablo.column("unvan", width=360, anchor="w")
        self.tablo.column("bakiye", width=120, anchor="e")
        kaydir = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")
        self.tablo.bind("<Double-1>", self._sec)
        self.tablo.bind("<Return>", self._sec)

        self.bilgi = ttk.Label(self, text="", padding=(10, 4))
        self.bilgi.pack(anchor="w")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Seç", width=12, command=self._sec).pack(side="right")

        self._sonuclar = []
        self._filtrele()
        self.after(50, lambda: (self.arama.focus_set(), self.arama.icursor("end")))

    def _filtrele(self, _event=None):
        ara = (self.arama.get() or "").strip()
        ara_cf = ara.casefold()
        bulunan = []
        for cari in self._musteriler:
            unvan = (cari.unvan or "").strip()
            kod = (cari.cari_kodu or "").strip()
            etiket = f"{kod} - {unvan}"
            if ara_cf and (
                ara_cf not in unvan.casefold()
                and ara_cf not in kod.casefold()
                and ara_cf not in etiket.casefold()
            ):
                continue
            bulunan.append(cari)
        bulunan.sort(
            key=lambda c: ((c.unvan or "").casefold(), (c.cari_kodu or "").casefold())
        )
        self._sonuclar = bulunan
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for i, cari in enumerate(bulunan[:200]):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    cari.cari_kodu or "",
                    cari.unvan or "",
                    para_goster(self._bakiyeler.get(cari.id, Decimal("0"))),
                ),
            )
        if ara and len(ara) < 3:
            self.bilgi.configure(text="En az 3 harf yazın.")
        elif not bulunan:
            self.bilgi.configure(text="Sonuç yok.")
        else:
            self.bilgi.configure(text=f"{len(bulunan)} {self._kayit_adi} (alfabetik)")
        if bulunan:
            ilk = self.tablo.get_children()
            if ilk:
                self.tablo.selection_set(ilk[0])
                self.tablo.focus(ilk[0])

    def _listeye_in(self, _event=None):
        cocuklar = self.tablo.get_children()
        if cocuklar:
            self.tablo.focus_set()
            self.tablo.selection_set(cocuklar[0])
            self.tablo.focus(cocuklar[0])
        return "break"

    def _sec(self, _event=None):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo(
                "Seçim", f"Listeden {self._kayit_adi} seçin.", parent=self
            )
            return
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return
        if idx < 0 or idx >= len(self._sonuclar):
            return
        cari = self._sonuclar[idx]
        self.result = cari
        if self.on_select:
            self.on_select(cari)
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
        self.durum.configure(values=("TASLAK", "AÇIK", "KAPALI", "İPTAL"))
        self.durum.set(fatura.durum if fatura else "TASLAK")
        self._ek_fatura_bilgileri()
        self._fatura_onay_cubugu_olustur()
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
        elif not self._secili_musteri():
            self._musteri_alana_yaz("")
            self.mevcut_borc = Decimal("0")
            self._bakiye_guncelle()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()
        self._fatura_gorunumu_sikistir()
        self._onay_butonu_guncelle()
        self._son_uyari_cari_id = None
        # Açılışta seçili müşteri uyarısı
        self.after(250, self._fatura_musteri_uyari_goster)

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

    def _fatura_onay_cubugu_olustur(self):
        """Kayıt butonlarının altına sağda ONAYLA ve Onay Kaldır butonları."""
        cubuk = tk.Frame(self, bg="#eceff1")
        slaves = self.pack_slaves()
        if slaves:
            cubuk.pack(side="top", fill="x", after=slaves[0], padx=10, pady=(0, 6))
        else:
            cubuk.pack(side="top", fill="x", padx=10, pady=(0, 6))
        self.onay_durum_etiket = tk.Label(
            cubuk,
            text="",
            bg="#eceff1",
            fg="#455a64",
            font=("Segoe UI", 10, "bold"),
            anchor="e",
        )
        self.onay_durum_etiket.pack(side="right", padx=(8, 12))
        self.onay_btn = tk.Button(
            cubuk,
            text="ONAYLA",
            command=self.onayla,
            bg="#2e7d32",
            fg="#ffffff",
            activebackground="#1b5e20",
            activeforeground="#ffffff",
            disabledforeground="#e8f5e9",
            relief=tk.RAISED,
            borderwidth=3,
            font=("Segoe UI", 13, "bold"),
            cursor="hand2",
            padx=18,
            pady=6,
            highlightthickness=0,
        )
        self.onay_btn.pack(side="right", padx=4, pady=4)
        self.onay_kaldir_btn = tk.Button(
            cubuk,
            text="Onay Kaldır",
            command=self.onay_kaldir,
            bg="#c62828",
            fg="#ffffff",
            activebackground="#b71c1c",
            activeforeground="#ffffff",
            disabledforeground="#ffcdd2",
            relief=tk.RAISED,
            borderwidth=3,
            font=("Segoe UI", 13, "bold"),
            cursor="hand2",
            padx=18,
            pady=6,
            highlightthickness=0,
        )
        self.onay_kaldir_btn.pack(side="right", padx=4, pady=4)

        def _bas(_e, b):
            if str(b["state"]) != "disabled":
                b.configure(relief=tk.SUNKEN)

        def _birak(_e, b):
            b.configure(relief=tk.RAISED)

        for btn in (self.onay_btn, self.onay_kaldir_btn):
            btn.bind("<ButtonPress-1>", lambda e, b=btn: _bas(e, b))
            btn.bind("<ButtonRelease-1>", lambda e, b=btn: _birak(e, b))

    def _onay_butonu_guncelle(self):
        if not hasattr(self, "onay_btn"):
            return
        onayli = bool(self.fatura and getattr(self.fatura, "onaylandi", False))
        iptal = bool(self.fatura and (self.fatura.durum or "") == "İPTAL")
        if iptal:
            self.onay_btn.configure(state="disabled", bg="#9e9e9e")
            if hasattr(self, "onay_kaldir_btn"):
                self.onay_kaldir_btn.configure(state="disabled", bg="#9e9e9e")
            self.onay_durum_etiket.configure(text="İptal edilmiş", fg="#c62828")
        elif onayli:
            self.onay_btn.configure(state="disabled", bg="#81c784")
            if hasattr(self, "onay_kaldir_btn"):
                self.onay_kaldir_btn.configure(state="normal", bg="#c62828")
            self.onay_durum_etiket.configure(text="Onaylı", fg="#2e7d32")
            if hasattr(self, "durum"):
                try:
                    self.durum.set(self.fatura.durum or "AÇIK")
                except tk.TclError:
                    pass
        else:
            self.onay_btn.configure(state="normal", bg="#2e7d32")
            if hasattr(self, "onay_kaldir_btn"):
                self.onay_kaldir_btn.configure(state="disabled", bg="#e57373")
            self.onay_durum_etiket.configure(text="Onaysız (taslak)", fg="#c62828")
            if hasattr(self, "durum") and self.fatura:
                try:
                    self.durum.set(self.fatura.durum or "TASLAK")
                except tk.TclError:
                    pass

    def _ek_fatura_bilgileri(self):
        # Üstteki Fatura Numarası (Sipariş Numarası alanından dönüşmüş): aktif + SF-#####
        self.fatura_no_alani = self.girdiler["siparis_no"]
        otomatik_no = self.fatura.fatura_no if self.fatura else SatisFaturasiService.fatura_no()
        self.fatura_no_alani.configure(state="normal")
        self.fatura_no_alani.delete(0, "end")
        self.fatura_no_alani.insert(0, otomatik_no)

        # Maliyet yöntemi / hedef kâr marjı UI kaldırılır; stub'lar kârlılık analizi için kalır
        genel = self.hedef_kar_marji.master
        try:
            genel.configure(padding=4)
        except tk.TclError:
            pass
        for satir in (0, 1):
            for sutun in (2, 3):
                for w in genel.grid_slaves(row=satir, column=sutun):
                    w.grid_remove()
        self.hedef_kar_marji.delete(0, "end")
        self.hedef_kar_marji.insert(0, "0")

        # Genel alan sağ sütun: KAR + geçmiş butonları, sonra işlem saati / vade / bağlar
        px, py = 6, 2
        aksiyon = ttk.Frame(genel)
        aksiyon.grid(row=0, column=2, columnspan=2, padx=px, pady=py, sticky="ew")
        self._fatura_mavi_oval_buton(aksiyon, "KAR ANALİZİ", self.karlilik_analizi_ac, padx=(0, 4))
        self._fatura_mavi_oval_buton(
            aksiyon, "Bu Müşteriye Satışlar", self._urun_musteri_satislari_ac, padx=3
        )
        self._fatura_mavi_oval_buton(
            aksiyon, "Genel Satışlar", self._urun_genel_satislari_ac, padx=3
        )
        self._fatura_mavi_oval_buton(aksiyon, "Alışlar", self._urun_alislari_ac, padx=3)

        ttk.Label(genel, text="İşlem Saati").grid(row=1, column=2, padx=px, pady=py, sticky="w")
        self.islem_saati_alani = ttk.Entry(genel, width=22)
        self.islem_saati_alani.grid(row=1, column=3, padx=px, pady=py, sticky="ew")
        saat_deger = saat_varsayilan(
            self.fatura.islem_saati if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        self.islem_saati_alani.insert(0, saat_deger)
        self.girdiler["islem_saati"] = self.islem_saati_alani

        ttk.Label(genel, text="Fatura Vadesi (Gün)").grid(row=2, column=2, padx=px, pady=py, sticky="w")
        self.vade_gunu = ttk.Entry(genel, width=22)
        self.vade_gunu.grid(row=2, column=3, padx=px, pady=py, sticky="ew")
        self.vade_gunu.insert(0, str(self.fatura.vade_gunu if self.fatura else 0))
        self.vade_gunu.bind("<KeyRelease>", self.vade_gun_degisti)

        ttk.Label(genel, text="Sipariş Numarası").grid(row=3, column=2, padx=px, pady=py, sticky="w")
        self.bagli_siparis_map = {}
        self.bagli_irsaliye_map = {}
        self.siparis_no = ttk.Combobox(
            genel, width=22, postcommand=self._fatura_siparis_listesini_doldur
        )
        self.siparis_no.grid(row=3, column=3, padx=px, pady=py, sticky="ew")
        self.siparis_no.bind("<<ComboboxSelected>>", self._fatura_siparis_secildi)

        ttk.Label(genel, text="İrsaliye Numarası").grid(row=4, column=2, padx=px, pady=py, sticky="w")
        self.irsaliye_no = ttk.Combobox(
            genel, width=22, postcommand=self._fatura_irsaliye_listesini_doldur
        )
        self.irsaliye_no.grid(row=4, column=3, padx=px, pady=py, sticky="ew")
        self.irsaliye_no.bind("<<ComboboxSelected>>", self._fatura_irsaliye_secildi)

        ttk.Label(genel, text="Doküman Ekle").grid(row=5, column=2, padx=px, pady=py, sticky="w")
        dok_cerceve = ttk.Frame(genel)
        dok_cerceve.grid(row=5, column=3, padx=px, pady=py, sticky="ew")
        self.dokuman = ttk.Entry(dok_cerceve, width=18)
        self.dokuman.pack(side="left", fill="x", expand=True)
        ttk.Button(dok_cerceve, text="Seç", command=self.dokuman_sec, width=4).pack(side="left", padx=(4, 0))

        self.girdiler["siparis_no"] = self.siparis_no
        self.girdiler["irsaliye_no"] = self.irsaliye_no
        self.girdiler["dokuman"] = self.dokuman
        # Müşteri listesi bakiyeli; en az 3 harf ile ünvan/kod arama
        self._fatura_musteri_listesini_bakiyeli_kur()
        # Müşteri satırının yanına Yeni butonu (combobox frame içinde kalır, seçim bozulmaz)
        musteri_bilgi = self.musteri.grid_info()
        if musteri_bilgi:
            genel = self.musteri.master
            onceki_deger = (self.musteri.get() or "").strip()
            onceki_degerler = self.musteri.cget("values")
            musteri_satir = ttk.Frame(genel)
            musteri_satir.grid(
                row=int(musteri_bilgi["row"]),
                column=int(musteri_bilgi["column"]),
                padx=musteri_bilgi.get("padx") or 8,
                pady=musteri_bilgi.get("pady") or 5,
                sticky=musteri_bilgi.get("sticky") or "ew",
            )
            musteri_satir.columnconfigure(0, weight=1)
            self.musteri.destroy()
            # Entry: yazarak arama Combobox'tan daha güvenilir (KeyRelease)
            self.musteri = ttk.Entry(musteri_satir, width=56)
            self.musteri.pack(side="left", fill="x", expand=True)
            if onceki_deger and "  |  " not in onceki_deger:
                try:
                    self.musteri.insert(0, onceki_deger)
                except tk.TclError:
                    pass
            ttk.Button(
                musteri_satir,
                text="Ara",
                width=5,
                command=lambda: self._musteri_secim_penceresi_ac(zorla=True),
            ).pack(side="left", padx=(6, 0))
            ttk.Button(
                musteri_satir,
                text="Yeni",
                width=6,
                command=self.yeni_musteri_ekle,
            ).pack(side="left", padx=(6, 0))
            ttk.Label(
                musteri_satir,
                text="≥3 harf veya Ara / F2",
                foreground="#666",
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(8, 0))
        else:
            self.musteri.configure(state="normal", width=56)
        self.musteri.bind("<KeyRelease>", self._musteri_filtrele)
        self.musteri.bind("<<ComboboxSelected>>", self._fatura_cari_degisti)
        self.musteri.bind("<FocusOut>", self._fatura_cari_odak_cikti)
        self.musteri.bind("<F2>", lambda _e: self._musteri_secim_penceresi_ac(zorla=True))
        self.bind("<F2>", lambda _e: self._musteri_secim_penceresi_ac(zorla=True))
        if self.kaynak_siparis:
            self.siparis_no.set(self.kaynak_siparis.siparis_no)
        if self.kaynak_irsaliye:
            self.irsaliye_no.set(self.kaynak_irsaliye.irsaliye_no)
            if self.kaynak_irsaliye.siparis:
                self.siparis_no.set(self.kaynak_irsaliye.siparis.siparis_no)
        self._fatura_baglanti_listelerini_yenile(
            otomatik_sec=not bool(self.kaynak_siparis or self.kaynak_irsaliye or self.fatura)
        )

        for widget in self.icerik.winfo_children():
            self._etiketi_degistir(widget, "Vade Tarihi", "Fatura Vadesi Tarihi")
            self._etiketi_degistir(widget, "Termin Tarihi", "Fatura Vadesi Tarihi")
        self._takvimli_tarih_yap("siparis_tarihi", self.vade_gun_degisti)
        self._takvimli_tarih_yap("termin_tarihi", self.vade_tarih_degisti)
        self.girdiler["termin_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.girdiler["siparis_tarihi"].bind("<FocusOut>", self.vade_gun_degisti)

        # Depo + özet tek satırda (ayrı blokları birleştir)
        satir_cerceve = None
        for widget in self.icerik.winfo_children():
            try:
                baslik = str(widget.cget("text")).upper()
            except tk.TclError:
                continue
            if isinstance(widget, ttk.LabelFrame) and "SATIR" in baslik:
                satir_cerceve = widget
                break

        ek = ttk.LabelFrame(self.icerik, text="ÖZET / DEPO", padding=4)
        if satir_cerceve is not None:
            ek.pack(fill="x", pady=(2, 2), before=satir_cerceve)
        else:
            ek.pack(fill="x", pady=2)

        ttk.Label(ek, text="Depo").pack(side="left", padx=(0, 4))
        depolar = tuple(d.ad for d in StokService.depolar())
        self.depo = ttk.Combobox(ek, values=depolar, state="readonly", width=18)
        self.depo.pack(side="left")
        if depolar:
            mevcut = self.fatura.depo if self.fatura and self.fatura.depo in depolar else depolar[0]
            self.depo.set(mevcut)
        else:
            self.depo.set("ANA DEPO")
        self.depo.bind("<<ComboboxSelected>>", self.depo_degisti)
        ttk.Button(ek, text="Yeni Depo", command=self.depo_ekle, width=10).pack(side="left", padx=(4, 10))
        self.girdiler["depo"] = self.depo

        ttk.Button(ek, text="Cari Kart", command=self.cariye_git, width=10).pack(side="left", padx=(0, 14))

        # Fatura adresi: müşteri adreslerinden seçim + seçili adres görünümü
        adres_kutu = ttk.LabelFrame(self.icerik, text="FATURA ADRESİ", padding=4)
        if satir_cerceve is not None:
            adres_kutu.pack(fill="x", pady=(2, 2), before=satir_cerceve)
        else:
            adres_kutu.pack(fill="x", pady=2)
        ttk.Label(adres_kutu, text="Adres seçimi").pack(side="left", padx=(0, 4))
        self.adres_secimi = ttk.Combobox(adres_kutu, state="readonly", width=28)
        self.adres_secimi.pack(side="left", padx=(0, 10))
        self.adres_secimi.bind("<<ComboboxSelected>>", self._fatura_adres_secildi)
        ttk.Label(adres_kutu, text="Seçili adres").pack(side="left", padx=(0, 4))
        self.adres_gorunum = tk.Text(
            adres_kutu, height=2, width=56, wrap="word", font=("Segoe UI", 9)
        )
        self.adres_gorunum.pack(side="left", fill="x", expand=True)
        self.adres_gorunum.configure(state="disabled")
        self._fatura_adres_map = {}
        self._fatura_adreslerini_yukle(
            kayitli_no=getattr(self.fatura, "adres_no", None) if self.fatura else None,
            kayitli_metin=getattr(self.fatura, "adres_metni", None) if self.fatura else None,
        )

        # Eski bakiye | Yeni bakiye | Ağırlıklı ort. — yan yana
        yazi = ("Segoe UI", 9, "bold")
        self.eski_bakiye_etiket = ttk.Label(
            ek, text="Eski bakiye: -", foreground="#1f6aa5", font=yazi
        )
        self.eski_bakiye_etiket.pack(side="left", padx=(0, 16))
        self.yeni_bakiye_etiket = ttk.Label(
            ek, text="Yeni bakiye: -", foreground="#1f6aa5", font=yazi
        )
        self.yeni_bakiye_etiket.pack(side="left", padx=(0, 16))
        self.ortalama_vade_etiket = ttk.Label(
            ek, text="Ağırlıklı ort.: -", foreground="#1f6aa5", font=yazi
        )
        self.ortalama_vade_etiket.pack(side="left")

        # Dövizli fatura paneli
        doviz_cerceve = ttk.LabelFrame(self.icerik, text="DÖVİZ / KUR", padding=6)
        if satir_cerceve is not None:
            doviz_cerceve.pack(fill="x", pady=(2, 2), before=satir_cerceve)
        else:
            doviz_cerceve.pack(fill="x", pady=2)
        self._doviz_fiyat_alani = "birim_satis_fiyati"
        doviz_paneli_kur(self, doviz_cerceve)
        if self.fatura:
            doviz_verilerini_doldur(self, self.fatura)

    def _fatura_musteri_listesini_bakiyeli_kur(self):
        """Müşteri listesi + bakiyeler; alana yalnızca kod-ünvan yazılır."""
        bakiyeler = {}
        for ozet in CariService.listele(hizli=True):
            cari = ozet.get("cari")
            if cari is not None:
                bakiyeler[cari.id] = ozet.get("bakiye", Decimal("0"))
        self._musteri_bakiyeleri = bakiyeler
        temiz_map = {}
        for cari in self.musteriler:
            temiz = f"{cari.cari_kodu} - {cari.unvan}"
            temiz_map[temiz] = cari
        self.musteri_map = temiz_map
        self._musteri_liste_map = {}
        self._tum_musteri_etiketleri = list(temiz_map.keys())
        # Yeni faturada alan boş kalsın; mevcut seçim varsa yalnızca temiz etiket yaz
        secili = self._secili_musteri()
        if secili:
            self._musteri_alana_yaz(f"{secili.cari_kodu} - {secili.unvan}")
        else:
            self._musteri_alana_yaz("")

    def _musteri_alana_yaz(self, metin: str):
        """Entry veya Combobox müşteri alanına yazar."""
        metin = metin or ""
        try:
            if isinstance(self.musteri, ttk.Combobox):
                self.musteri.set(metin)
            else:
                self.musteri.delete(0, "end")
                if metin:
                    self.musteri.insert(0, metin)
        except tk.TclError:
            pass

    def _fatura_musteriyi_sec(self, cari):
        """Alana yalnızca kod - ünvan yazar."""
        if not cari:
            return
        temiz = f"{cari.cari_kodu} - {cari.unvan}"
        if temiz not in self.musteri_map:
            self.musteri_map[temiz] = cari
            self._tum_musteri_etiketleri = list(getattr(self, "_tum_musteri_etiketleri", [])) + [temiz]
        self._musteri_alana_yaz(temiz)

    def _secili_musteri(self):
        """Müşteri combobox metninden cari kaydını çözer."""
        etiket = (self.musteri.get() or "").strip()
        if not etiket:
            return None
        # Liste satırından (bakiyeli) seçilmiş olabilir
        liste_map = getattr(self, "_musteri_liste_map", {}) or {}
        if etiket in liste_map:
            return liste_map[etiket]
        musteri = self.musteri_map.get(etiket)
        if musteri:
            return musteri
        # "kod - unvan | Bakiye: ..." biçimini temizle
        if "  |  " in etiket:
            temiz = etiket.split("  |  ", 1)[0].strip()
            if temiz in self.musteri_map:
                return self.musteri_map[temiz]
            etiket = temiz
        for anahtar, cari in self.musteri_map.items():
            if anahtar.casefold() == etiket.casefold():
                return cari
            kod_unvan = f"{cari.cari_kodu} - {cari.unvan}".strip()
            if kod_unvan.casefold() == etiket.casefold():
                return cari
        return None

    def _musteri_listeyi_ac(self, imlec=None):
        """Filtrelenmiş müşteri listesini otomatik açar; yazılan metni korur."""
        try:
            self.musteri.focus_set()
            self.musteri.tk.call("ttk::combobox::Post", self.musteri)
            if imlec is not None:
                try:
                    self.musteri.icursor(imlec)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _musteri_listeyi_kapat(self):
        try:
            self.musteri.tk.call("ttk::combobox::Unpost", self.musteri)
        except tk.TclError:
            pass

    def _musteri_filtre_ara(self, metin: str) -> list:
        """Ünvan/kod içinde ara; ünvan alfabetik. En az 3 harf."""
        ara = (metin or "").strip()
        if "  |  " in ara:
            ara = ara.split("  |  ", 1)[0].strip()
        if len(ara) < 3:
            return []
        ara_cf = ara.casefold()
        bakiyeler = getattr(self, "_musteri_bakiyeleri", {}) or {}
        bulunan = []
        for cari in getattr(self, "musteriler", []) or []:
            unvan = (cari.unvan or "").strip()
            kod = (cari.cari_kodu or "").strip()
            if ara_cf not in unvan.casefold() and ara_cf not in kod.casefold():
                continue
            bulunan.append(
                {
                    "cari": cari,
                    "kod": kod,
                    "unvan": unvan,
                    "etiket": f"{kod} - {unvan}" if kod else unvan,
                    "bakiye": bakiyeler.get(cari.id, Decimal("0")),
                }
            )
        bulunan.sort(key=lambda x: ((x["unvan"] or "").casefold(), (x["kod"] or "").casefold()))
        return bulunan

    def _musteri_secildi_callback(self, cari):
        self._fatura_musteriyi_sec(cari)
        self._fatura_cari_degisti()

    def _musteri_secim_penceresi_ac(self, ara=None, zorla=False):
        """Ürün araması gibi modal müşteri seçim ekranı."""
        if getattr(self, "_musteri_sec_pencere", None):
            try:
                if self._musteri_sec_pencere.winfo_exists():
                    try:
                        self._musteri_sec_pencere.lift()
                        self._musteri_sec_pencere.focus_force()
                    except tk.TclError:
                        pass
                    return
            except tk.TclError:
                pass
        if ara is None:
            ara = (self.musteri.get() or "").strip()
            if "  |  " in ara:
                ara = ara.split("  |  ", 1)[0].strip()
        if not zorla:
            secili = self._secili_musteri()
            if secili:
                tam = f"{secili.cari_kodu} - {secili.unvan}"
                if (ara or "").strip() == tam:
                    return
            if len((ara or "").strip()) < 3:
                return
        dialog = MusteriSecimDialog(
            self,
            musteriler=getattr(self, "musteriler", []) or [],
            bakiyeler=getattr(self, "_musteri_bakiyeleri", {}) or {},
            ara=ara or "",
            on_select=self._musteri_secildi_callback,
        )
        self._musteri_sec_pencere = dialog
        self.wait_window(dialog)
        self._musteri_sec_pencere = None
        try:
            self.musteri.focus_set()
            self.musteri.icursor("end")
        except tk.TclError:
            pass

    def _musteri_filtrele(self, event=None):
        """En az 3 harf yazılınca (debounce) müşteri seçim ekranını aç."""
        if event and getattr(event, "keysym", "") in (
            "Up", "Down", "Return", "Escape", "Tab", "Left", "Right",
            "Prior", "Next", "Shift_L", "Shift_R", "Control_L", "Control_R",
            "Alt_L", "Alt_R", "Caps_Lock", "F2",
        ):
            return
        # KeyPress'te metin henüz güncellenmemiş olabilir
        if event is not None:
            try:
                if int(event.type) == 2:  # KeyPress
                    return
            except (TypeError, ValueError):
                pass
        metin = (self.musteri.get() or "").strip()
        if "  |  " in metin:
            metin = metin.split("  |  ", 1)[0].strip()
        if len(metin) < 3:
            if getattr(self, "_musteri_arama_after", None):
                try:
                    self.after_cancel(self._musteri_arama_after)
                except tk.TclError:
                    pass
                self._musteri_arama_after = None
            return
        secili = self._secili_musteri()
        if secili and metin == f"{secili.cari_kodu} - {secili.unvan}":
            return
        if getattr(self, "_musteri_arama_after", None):
            try:
                self.after_cancel(self._musteri_arama_after)
            except tk.TclError:
                pass
        self._musteri_arama_after = self.after(
            280, lambda m=metin: self._musteri_secim_ac_gecikmeli(m)
        )

    def _musteri_secim_ac_gecikmeli(self, metin):
        self._musteri_arama_after = None
        guncel = (self.musteri.get() or "").strip()
        if "  |  " in guncel:
            guncel = guncel.split("  |  ", 1)[0].strip()
        if guncel != metin or len(guncel) < 3:
            return
        self._musteri_secim_penceresi_ac(ara=guncel)

    def _fatura_cari_alani_temizle(self):
        """Seçimden sonra alana yalnızca kod - ünvan bırakır."""
        musteri = self._secili_musteri()
        if not musteri:
            return
        temiz = f"{musteri.cari_kodu} - {musteri.unvan}"
        if (self.musteri.get() or "").strip() != temiz:
            self._musteri_alana_yaz(temiz)

    def _bakiye_guncelle(self):
        """Eski bakiyeyi günceller; yeni bakiye / ağırlıklı ort. toplam hesabında yazılır.

        Eski bakiye, düzenlenen faturanın açık tutarı hariç hesaplanır (alış faturasıyla aynı mantık).
        """
        musteri = self._secili_musteri()
        borc = Decimal("0")
        if musteri:
            haric = self.fatura.fatura_no if self.fatura else None
            try:
                ozet = SatisFaturasiService.bakiye_ozeti(
                    musteri.id, Decimal("0"), None, haric
                )
                borc = Decimal(str(ozet.get("bakiye") or 0))
            except Exception:
                # Yedek: hızlı cari listesi
                bakiyeler = getattr(self, "_musteri_bakiyeleri", None)
                if bakiyeler is not None and musteri.id in bakiyeler:
                    borc = bakiyeler[musteri.id]
                else:
                    ozet = next(
                        (o for o in CariService.listele(hizli=True) if o["cari"].id == musteri.id),
                        None,
                    )
                    borc = ozet["bakiye"] if ozet else borc
        self.mevcut_borc = borc
        if "mevcut_bakiye" in getattr(self, "girdiler", {}):
            try:
                self._readonly_yaz("mevcut_bakiye", para_goster(borc))
            except (tk.TclError, AttributeError, KeyError):
                pass
        if hasattr(self, "eski_bakiye_etiket"):
            try:
                self.eski_bakiye_etiket.configure(text=f"Eski bakiye: {para_goster(borc)}")
            except tk.TclError:
                pass
        self._toplamlari_guncelle(borc)

    def _fatura_musteri_uyari_goster(self, _event=None):
        """Seçili müşterinin uyarı notunu bir kez gösterir."""
        musteri = self._secili_musteri()
        if not musteri:
            self._son_uyari_cari_id = None
            return
        if getattr(self, "_son_uyari_cari_id", None) == musteri.id:
            return
        self._son_uyari_cari_id = musteri.id
        cari_uyari_goster(self, musteri)

    def _fatura_cari_degisti(self, _event=None):
        self._fatura_cari_alani_temizle()
        # Müşteri değişince uyarıyı yeniden değerlendir
        onceki = getattr(self, "_son_uyari_cari_id", None)
        musteri = self._secili_musteri()
        if musteri is None or (musteri and onceki != musteri.id):
            self._son_uyari_cari_id = None
        self._bakiye_guncelle()
        self._fatura_baglanti_listelerini_yenile(otomatik_sec=True)
        self._fatura_adreslerini_yukle()
        self._fatura_musteri_uyari_goster()

    def _fatura_cari_odak_cikti(self, _event=None):
        # Seçim diyaloğu açıkken alanı bozma
        if getattr(self, "_musteri_sec_pencere", None):
            try:
                if self._musteri_sec_pencere.winfo_exists():
                    return
            except tk.TclError:
                pass
        self.after(150, self._fatura_cari_odak_cikti_gecikmeli)

    def _fatura_cari_odak_cikti_gecikmeli(self):
        if getattr(self, "_musteri_sec_pencere", None):
            try:
                if self._musteri_sec_pencere.winfo_exists():
                    return
            except tk.TclError:
                pass
        self._fatura_cari_alani_temizle()
        self._bakiye_guncelle()
        self._fatura_baglanti_listelerini_yenile(otomatik_sec=False)
        self._fatura_adreslerini_yukle()

    @staticmethod
    def _cari_adres_listesi(cari):
        """Cari kartındaki dolu adresleri (1-3) etiket + metin olarak döner."""
        if not cari:
            return []
        slots = (
            (1, "adres", "il", "ilce", "adres_tipi", "Merkez"),
            (2, "adres2", "il2", "ilce2", "adres_tipi2", "Fatura"),
            (3, "adres3", "il3", "ilce3", "adres_tipi3", "Sevk"),
        )
        sonuc = []
        for no, adres_alan, il_alan, ilce_alan, tip_alan, varsayilan_tip in slots:
            adres = (getattr(cari, adres_alan, None) or "").strip()
            il = (getattr(cari, il_alan, None) or "").strip()
            ilce = (getattr(cari, ilce_alan, None) or "").strip()
            tip = (getattr(cari, tip_alan, None) or "").strip() or varsayilan_tip
            if not adres and not il and not ilce:
                continue
            parcalar = [p for p in (adres, ilce, il) if p]
            metin = ", ".join(parcalar)
            etiket = f"{no}. {tip}"
            sonuc.append({"no": no, "tip": tip, "etiket": etiket, "metin": metin})
        return sonuc

    def _fatura_adres_gorunum_yaz(self, metin: str):
        if not hasattr(self, "adres_gorunum"):
            return
        try:
            self.adres_gorunum.configure(state="normal")
            self.adres_gorunum.delete("1.0", "end")
            if metin:
                self.adres_gorunum.insert("1.0", metin)
            self.adres_gorunum.configure(state="disabled")
        except tk.TclError:
            pass

    def _fatura_adreslerini_yukle(self, kayitli_no=None, kayitli_metin=None):
        """Seçili müşterinin adreslerini combobox'a yükler."""
        if not hasattr(self, "adres_secimi"):
            return
        musteri = self._secili_musteri()
        cari = CariService.getir(musteri.id) if musteri else None
        adresler = self._cari_adres_listesi(cari)
        self._fatura_adres_map = {a["etiket"]: a for a in adresler}
        try:
            self.adres_secimi.configure(values=list(self._fatura_adres_map.keys()))
        except tk.TclError:
            return
        if not adresler:
            try:
                self.adres_secimi.set("")
            except tk.TclError:
                pass
            self._fatura_adres_gorunum_yaz(kayitli_metin or "")
            return
        secilecek = None
        if kayitli_no is not None:
            for a in adresler:
                if a["no"] == int(kayitli_no):
                    secilecek = a
                    break
        if secilecek is None:
            for tercih in ("Fatura", "Merkez", "Sevk"):
                for a in adresler:
                    if (a["tip"] or "").casefold() == tercih.casefold():
                        secilecek = a
                        break
                if secilecek:
                    break
        if secilecek is None:
            secilecek = adresler[0]
        try:
            self.adres_secimi.set(secilecek["etiket"])
        except tk.TclError:
            pass
        self._fatura_adres_gorunum_yaz(secilecek["metin"])

    def _fatura_adres_secildi(self, _event=None):
        etiket = (self.adres_secimi.get() or "").strip()
        adres = (getattr(self, "_fatura_adres_map", {}) or {}).get(etiket)
        self._fatura_adres_gorunum_yaz(adres["metin"] if adres else "")

    def _fatura_secili_adres(self):
        """Kayıt için seçili adres bilgisi."""
        etiket = ""
        if hasattr(self, "adres_secimi"):
            etiket = (self.adres_secimi.get() or "").strip()
        adres = (getattr(self, "_fatura_adres_map", {}) or {}).get(etiket)
        if adres:
            return adres
        metin = ""
        if hasattr(self, "adres_gorunum"):
            try:
                metin = self.adres_gorunum.get("1.0", "end").strip()
            except tk.TclError:
                metin = ""
        return {"no": None, "tip": None, "etiket": "", "metin": metin}

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
        """Ürün adından aramada yalnızca stoğu olanlar; kod / STOK LİSTESİ tüm kartlar."""
        self._urun_arama_after = None
        if getattr(self, "_urun_sec_pencere", None) and self._urun_sec_pencere.winfo_exists():
            return
        sadece_stokta = bool((ad or "").strip()) and not (kod or "").strip()
        depo = ""
        if sadece_stokta and hasattr(self, "depo"):
            try:
                depo = self.depo.get().strip()
            except tk.TclError:
                depo = ""
        dialog = ProductSelectionDialog(
            self,
            on_select=self.satir_urun_secildi,
            kod=kod,
            ad=ad,
            sadece_stokta=sadece_stokta,
            depo_ad=depo or None,
        )
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None

    def _urun_musteri_satislari_ac(self):
        kod = self._secili_urun_kodu()
        if not kod:
            messagebox.showinfo("Ürün", "Önce fatura satırında bir ürün seçin / girin.", parent=self)
            return
        musteri = self._secili_musteri()
        if not musteri:
            messagebox.showinfo("Müşteri", "Önce müşteri seçin.", parent=self)
            return
        kayitlar = SatisFaturasiService.urun_satis_hareketleri(kod, cari_id=musteri.id)
        UrunHareketGecmisiDialog(
            self,
            "Bu Müşteriye Satışlar",
            kod,
            kayitlar,
            ("tarih", "miktar", "net_fiyat", "belge_no"),
            ("Tarih", "Adet", "Net Satış Fiyatı", "Fatura No"),
        )

    def _fatura_siparis_listesini_doldur(self):
        """Combobox açılmadan hemen önce yalnızca seçili müşterinin siparişleri."""
        musteri = self._secili_musteri()
        if not musteri:
            self.bagli_siparis_map = {}
            self.siparis_no["values"] = ()
            return
        self.bagli_siparis_map = {
            s.siparis_no: s
            for s in SatisFaturasiService.acik_siparisler(cari_id=musteri.id)
        }
        # Düzenleme / kaynak sipariş aynı carininse listede kalsın
        if self.kaynak_siparis and self.kaynak_siparis.cari_id == musteri.id:
            self.bagli_siparis_map[self.kaynak_siparis.siparis_no] = self.kaynak_siparis
        if self.fatura and self.fatura.siparis and self.fatura.siparis.cari_id == musteri.id:
            self.bagli_siparis_map[self.fatura.siparis.siparis_no] = self.fatura.siparis
        self.siparis_no["values"] = list(self.bagli_siparis_map.keys())

    def _fatura_irsaliye_listesini_doldur(self):
        """Combobox açılmadan hemen önce yalnızca seçili müşterinin irsaliyeleri."""
        musteri = self._secili_musteri()
        if not musteri:
            self.bagli_irsaliye_map = {}
            self.irsaliye_no["values"] = ()
            return
        self.bagli_irsaliye_map = {
            i.irsaliye_no: i
            for i in SatisFaturasiService.acik_irsaliyeler(cari_id=musteri.id)
        }
        if self.kaynak_irsaliye and self.kaynak_irsaliye.cari_id == musteri.id:
            self.bagli_irsaliye_map[self.kaynak_irsaliye.irsaliye_no] = self.kaynak_irsaliye
        if self.fatura and self.fatura.irsaliye and self.fatura.irsaliye.cari_id == musteri.id:
            self.bagli_irsaliye_map[self.fatura.irsaliye.irsaliye_no] = self.fatura.irsaliye
        self.irsaliye_no["values"] = list(self.bagli_irsaliye_map.keys())

    def _fatura_baglanti_listelerini_yenile(self, otomatik_sec=False):
        """Seçili cariye ait açık sipariş / irsaliye numaralarını filtreler."""
        musteri = self._secili_musteri()
        onceki_siparis = self.siparis_no.get().strip() if hasattr(self, "siparis_no") else ""
        onceki_irsaliye = self.irsaliye_no.get().strip() if hasattr(self, "irsaliye_no") else ""

        self.bagli_siparis_map = {}
        self.bagli_irsaliye_map = {}
        if not musteri:
            self.siparis_no["values"] = ()
            self.irsaliye_no["values"] = ()
            self.siparis_no.set("")
            self.irsaliye_no.set("")
            self.kaynak_siparis = None
            self.kaynak_irsaliye = None
            return

        for siparis in SatisFaturasiService.acik_siparisler(cari_id=musteri.id):
            self.bagli_siparis_map[siparis.siparis_no] = siparis
        for irsaliye in SatisFaturasiService.acik_irsaliyeler(cari_id=musteri.id):
            self.bagli_irsaliye_map[irsaliye.irsaliye_no] = irsaliye

        # Düzenleme / kaynak belgeler yalnızca aynı müşterideyse listede kalsın
        if self.kaynak_siparis and self.kaynak_siparis.cari_id == musteri.id:
            self.bagli_siparis_map[self.kaynak_siparis.siparis_no] = self.kaynak_siparis
        if self.fatura and self.fatura.siparis and self.fatura.siparis.cari_id == musteri.id:
            self.bagli_siparis_map[self.fatura.siparis.siparis_no] = self.fatura.siparis
        if self.kaynak_irsaliye and self.kaynak_irsaliye.cari_id == musteri.id:
            self.bagli_irsaliye_map[self.kaynak_irsaliye.irsaliye_no] = self.kaynak_irsaliye
        if self.fatura and self.fatura.irsaliye and self.fatura.irsaliye.cari_id == musteri.id:
            self.bagli_irsaliye_map[self.fatura.irsaliye.irsaliye_no] = self.fatura.irsaliye

        siparis_nolari = list(self.bagli_siparis_map.keys())
        irsaliye_nolari = list(self.bagli_irsaliye_map.keys())
        self.siparis_no["values"] = siparis_nolari
        self.irsaliye_no["values"] = irsaliye_nolari

        if onceki_siparis in self.bagli_siparis_map:
            self.siparis_no.set(onceki_siparis)
        else:
            self.siparis_no.set("")
            if self.kaynak_siparis and self.kaynak_siparis.cari_id != musteri.id:
                self.kaynak_siparis = None
            elif self.kaynak_siparis and self.kaynak_siparis.siparis_no not in self.bagli_siparis_map:
                self.kaynak_siparis = None

        if onceki_irsaliye in self.bagli_irsaliye_map:
            self.irsaliye_no.set(onceki_irsaliye)
        else:
            self.irsaliye_no.set("")
            if self.kaynak_irsaliye and self.kaynak_irsaliye.cari_id != musteri.id:
                self.kaynak_irsaliye = None
            elif self.kaynak_irsaliye and self.kaynak_irsaliye.irsaliye_no not in self.bagli_irsaliye_map:
                self.kaynak_irsaliye = None

        if not otomatik_sec:
            return

        # Tek kayıt varsa otomatik bağla
        if not self.siparis_no.get().strip() and len(siparis_nolari) == 1:
            self.siparis_no.set(siparis_nolari[0])
            self._fatura_siparis_secildi(otomatik=True)
            return
        if not self.irsaliye_no.get().strip() and len(irsaliye_nolari) == 1:
            self.irsaliye_no.set(irsaliye_nolari[0])
            self._fatura_irsaliye_secildi(otomatik=True)

    def _fatura_siparis_secildi(self, _event=None, otomatik=False):
        no = self.siparis_no.get().strip()
        siparis = self.bagli_siparis_map.get(no)
        if not siparis:
            # Elle yazılmış numara — kaydet sırasında doğrulanır
            return
        self.kaynak_siparis = siparis

        # Bu siparişe bağlı irsaliyeleri öne al
        ilgili = {
            n: i for n, i in self.bagli_irsaliye_map.items()
            if i.siparis_id == siparis.id
        }
        if ilgili:
            self.irsaliye_no["values"] = list(ilgili.keys()) + [
                n for n in self.bagli_irsaliye_map if n not in ilgili
            ]
            if len(ilgili) == 1 and (otomatik or not self.irsaliye_no.get().strip()):
                self.irsaliye_no.set(next(iter(ilgili)))
                self._fatura_irsaliye_secildi(otomatik=True)
                return
        else:
            self.irsaliye_no["values"] = list(self.bagli_irsaliye_map.keys())

        # İrsaliye yoksa sipariş kalan satırlarını bağla
        if self.satirlar and not otomatik:
            if not messagebox.askyesno(
                "Sipariş bağla",
                f"{siparis.siparis_no} siparişinin kalan satırları faturaya aktarılsın mı?\n"
                "Mevcut satırlar değişebilir.",
                parent=self,
            ):
                return
        self.kaynak_irsaliye = None
        self._siparis_kalanlarini_hazirla_from(siparis)

    def _fatura_irsaliye_secildi(self, _event=None, otomatik=False):
        no = self.irsaliye_no.get().strip()
        irsaliye = self.bagli_irsaliye_map.get(no)
        if not irsaliye:
            return
        self.kaynak_irsaliye = irsaliye
        if irsaliye.siparis:
            self.kaynak_siparis = irsaliye.siparis
            self.siparis_no.set(irsaliye.siparis.siparis_no)
            if irsaliye.siparis.siparis_no not in self.bagli_siparis_map:
                self.bagli_siparis_map[irsaliye.siparis.siparis_no] = irsaliye.siparis
                self.siparis_no["values"] = list(self.bagli_siparis_map.keys())
        if self.satirlar and not otomatik:
            if not messagebox.askyesno(
                "İrsaliye bağla",
                f"{irsaliye.irsaliye_no} irsaliyesinin kalan satırları faturaya aktarılsın mı?\n"
                "Mevcut satırlar değişebilir.",
                parent=self,
            ):
                return
        self._irsaliyeyi_doldur(irsaliye)

    def _siparis_kalanlarini_hazirla_from(self, siparis):
        """Seçilen siparişin faturalanmamış kalan miktarlarını satırlara aktarır."""
        self.kaynak_siparis = siparis
        kalan_satirlar = []
        for satir in siparis.satirlar or []:
            miktar = decimal(satir.miktar or 0, "Miktar")
            faturalanan = decimal(satir.faturalanan_miktar or 0, "Faturalanan miktar")
            kalan = miktar - faturalanan
            if kalan <= 0:
                continue
            kalan_satirlar.append({
                "siparis_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": satir.aciklama or "",
                "miktar": kalan,
                "birim": satir.birim,
                "birim_satis_fiyati": satir.birim_satis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": 0,
                "iskonto_orani_3": 0,
                "kdv_orani": satir.kdv_orani,
                "fifo_birim_maliyeti": 0,
                "son_alis_birim_maliyeti": 0,
                "ortalama_birim_maliyeti": 0,
                "agirlikli_ortalama_birim_maliyeti": 0,
                "lot_no": "",
                "lot_cikisi": "",
                "irsaliyelenen_miktar": satir.irsaliyelenen_miktar or 0,
                "faturalanan_miktar": 0,
            })
        self.satirlar = kalan_satirlar
        if not self.satirlar:
            messagebox.showinfo(
                "Sipariş",
                "Bu siparişte faturalanacak açık miktar kalmadı.",
                parent=self,
            )
        self._satirlari_stokla_tamamla()
        self._satir_listesini_yenile()
        self._toplamlari_guncelle()

    def _fatura_gorunumu_sikistir(self):
        """Fatura bilgilerini yukarı alır; satır hareketlerinde 15 satır gösterir."""
        self.title("Fatura Kartı")
        self.geometry("1280x820")
        self.minsize(1000, 700)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

        # Büyük başlık satırını kaldır
        for w in list(self.icerik.winfo_children()):
            try:
                if isinstance(w, ttk.Label) and "BİLGİLERİ" in str(w.cget("text")).upper():
                    w.pack_forget()
            except tk.TclError:
                pass

        # Mevcut / tahmini bakiye satırları özet çubuğunda; genelden gizle
        for alan in ("mevcut_bakiye", "tahmini_bakiye"):
            widget = self.girdiler.get(alan)
            if widget is None:
                continue
            info = widget.grid_info()
            if not info:
                continue
            parent = widget.master
            for child in parent.grid_slaves(row=int(info["row"])):
                child.grid_remove()

        # Genel alan boşlukları — mümkün olduğunca yukarı / sıkı
        genel = self.hedef_kar_marji.master
        try:
            genel.configure(padding=(4, 2))
        except tk.TclError:
            pass
        for child in genel.winfo_children():
            info = child.grid_info()
            if info:
                child.grid_configure(pady=1, padx=3)

        # Üst kayıt çubuğu ve kaydırma payı
        for w in self.winfo_children():
            try:
                if isinstance(w, ttk.Frame):
                    w.configure(padding=(4, 2, 4, 2))
            except tk.TclError:
                pass
        try:
            self.icerik.configure(padding=2)
        except tk.TclError:
            pass

        # Pack sırası: bilgiler en üstte, satırlar genişlesin
        satir_cerceve = None
        alt_cerceve = None
        ozet_cerceve = None
        for w in list(self.icerik.winfo_children()):
            try:
                metin = str(w.cget("text")) if hasattr(w, "cget") else ""
            except tk.TclError:
                metin = ""
            if isinstance(w, ttk.LabelFrame) and "SATIR" in metin.upper():
                satir_cerceve = w
            elif isinstance(w, ttk.LabelFrame) and ("ÖZET" in metin.upper() or "DEPO" in metin.upper()):
                ozet_cerceve = w
            elif isinstance(w, ttk.Frame) and w is not genel and "LabelFrame" not in type(w).__name__:
                # tahsilat+notlar alt frame
                if any(isinstance(c, ttk.LabelFrame) for c in w.winfo_children()):
                    alt_cerceve = w

        if genel.winfo_manager() == "pack":
            genel.pack_configure(fill="x", pady=(0, 2), expand=False)
        if ozet_cerceve is not None and ozet_cerceve.winfo_manager() == "pack":
            ozet_cerceve.configure(padding=2)
            ozet_cerceve.pack_configure(fill="x", pady=(0, 2), expand=False)
        if satir_cerceve is not None and satir_cerceve.winfo_manager() == "pack":
            satir_cerceve.configure(text="FATURA SATIRLARI", padding=2)
            satir_cerceve.pack_configure(fill="both", expand=True, pady=(0, 2))
            for cocuk in satir_cerceve.winfo_children():
                try:
                    if isinstance(cocuk, ttk.LabelFrame):
                        cocuk.configure(padding=2)
                except tk.TclError:
                    pass
        if alt_cerceve is not None and alt_cerceve.winfo_manager() == "pack":
            alt_cerceve.pack_configure(fill="x", expand=False, pady=(0, 0))

        # Satır tablosu: Excel benzeri çizgili görünüm + şerit
        stil = ttk.Style(self)
        stil.configure(
            "FaturaSatir.Treeview",
            rowheight=22,
            font=("Segoe UI", 9),
            borderwidth=1,
            relief="solid",
            columnseparatorwidth=1,
            columnseparatorcolor="#bdbdbd",
            fieldbackground="#ffffff",
            background="#ffffff",
        )
        stil.configure(
            "FaturaSatir.Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            relief="solid",
            borderwidth=1,
        )
        try:
            stil.map(
                "FaturaSatir.Treeview",
                background=[("selected", "#90caf9")],
                foreground=[("selected", "#000000")],
            )
        except tk.TclError:
            pass
        if hasattr(self, "satir_tablosu"):
            self.satir_tablosu.configure(style="FaturaSatir.Treeview", height=15)
            self.satir_tablosu.tag_configure("tek", background="#ffffff")
            self.satir_tablosu.tag_configure("cift", background="#e8f5e9")
            self.satir_tablosu.tag_configure("isaretli", background="#fff59d")
            self._fatura_kolon_ayarlari_uygula()
            self._tree_excel_cizgileri_kur(
                self.satir_tablosu,
                "satir",
                style_name="FaturaSatir.Treeview",
            )
        if hasattr(self, "tahsilat_tablosu"):
            self._fatura_tahsilat_tablosunu_duzenle()
            self._fatura_tahsilat_butonlarini_ayarla()
            self._tree_excel_cizgileri_kur(
                self.tahsilat_tablosu,
                "tahsilat",
                style_name="FaturaTahsilat.Treeview",
            )
        if hasattr(self, "ayrintili_notlar"):
            self.ayrintili_notlar.configure(height=2, width=36)

        # Fatura bilgileri çerçevesi
        for w in self.icerik.winfo_children():
            try:
                metin = str(w.cget("text"))
            except tk.TclError:
                continue
            if isinstance(w, ttk.LabelFrame) and (
                "Sipariş Bilgileri" in metin
                or ("Fatura" in metin and "Bilgi" in metin)
            ):
                try:
                    w.configure(text="Fatura Bilgileri", padding=(4, 2))
                except tk.TclError:
                    pass

        # Durum satırını yukarı kaydır (gizlenen bakiye satırlarının yerine)
        if hasattr(self, "durum"):
            info = self.durum.grid_info()
            if info and int(info.get("row", 6)) > 4:
                for child in self.durum.master.grid_slaves(row=int(info["row"])):
                    child.grid_configure(row=4)

        # Canvas scrollregion güncelle; satır alanına öncelik
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(0)
        except tk.TclError:
            pass

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
        entry = ttk.Entry(cerceve, width=18)
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

    def _fatura_tahsilat_tablosunu_duzenle(self):
        """Tahsilat listesini üst başlıklı, hizalı ve şeritli tablo yapar."""
        if not hasattr(self, "tahsilat_tablosu"):
            return
        stil = ttk.Style(self)
        stil.configure(
            "FaturaTahsilat.Treeview",
            rowheight=22,
            font=("Segoe UI", 9),
            borderwidth=1,
            relief="solid",
            fieldbackground="#ffffff",
            background="#ffffff",
        )
        stil.configure(
            "FaturaTahsilat.Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            relief="solid",
            borderwidth=1,
        )
        try:
            stil.map(
                "FaturaTahsilat.Treeview",
                background=[("selected", "#a5d6a7")],
                foreground=[("selected", "#000000")],
            )
        except tk.TclError:
            pass

        kolonlar = ("sira", "tarih", "tutar", "sekil", "hesap", "aciklama")
        basliklar = {
            "sira": "No",
            "tarih": "Tahsilat Tarihi",
            "tutar": "Tutar",
            "sekil": "Ödeme Şekli",
            "hesap": "Hesap",
            "aciklama": "Açıklama",
        }
        genislikler = {
            "sira": 44,
            "tarih": 110,
            "tutar": 110,
            "sekil": 170,
            "hesap": 150,
            "aciklama": 220,
        }
        hizalar = {
            "sira": "center",
            "tarih": "center",
            "tutar": "e",
            "sekil": "w",
            "hesap": "w",
            "aciklama": "w",
        }
        self.tahsilat_tablosu.configure(
            style="FaturaTahsilat.Treeview",
            columns=kolonlar,
            show="headings",
            height=4,
            selectmode="browse",
        )
        for kolon in kolonlar:
            self.tahsilat_tablosu.heading(kolon, text=basliklar[kolon], anchor=hizalar[kolon])
            self.tahsilat_tablosu.column(
                kolon,
                width=genislikler[kolon],
                minwidth=36,
                stretch=(kolon == "aciklama"),
                anchor=hizalar[kolon],
            )
        self.tahsilat_tablosu.tag_configure("tek", background="#ffffff")
        self.tahsilat_tablosu.tag_configure("cift", background="#e8f5e9")
        # Mevcut satırları yeni kolon düzeniyle yenile
        if hasattr(self, "_tahsilat_listesini_yenile"):
            self._tahsilat_listesini_yenile()

    def _fatura_tahsilat_butonlarini_ayarla(self):
        """Tahsilat butonlarını tablonun üstüne alır; yeşil 3D oval yapar."""
        if getattr(self, "_tahsilat_yesil_butonlar_hazir", False):
            return
        if not hasattr(self, "tahsilat_tablosu"):
            return
        cerceve = self.tahsilat_tablosu.master
        try:
            cerceve.configure(text="TAHSİLATLAR", padding=4)
        except tk.TclError:
            pass

        alt = None
        for child in cerceve.winfo_children():
            if isinstance(child, (ttk.Frame, tk.Frame)) and any(
                isinstance(c, ttk.Button) for c in child.winfo_children()
            ):
                alt = child
                break
        if alt is None:
            return

        for child in list(alt.winfo_children()):
            child.destroy()

        self.tahsilat_tablosu.pack_forget()
        alt.pack_forget()
        if hasattr(self, "tahsilat_ozet"):
            self.tahsilat_ozet.pack_forget()

        alt.pack(fill="x", pady=(0, 4), anchor="w")
        self._fatura_yesil_oval_buton(alt, "Tahsilat Ekle", self.tahsilat_ekle, padx=(0, 8))
        self._fatura_yesil_oval_buton(alt, "Tahsilat Düzenle", self.tahsilat_duzenle, padx=(0, 8))
        self._fatura_yesil_oval_buton(alt, "Tahsilat Kaldır", self.tahsilat_kaldir, padx=0)
        self.tahsilat_tablosu.pack(fill="both", expand=True)
        if hasattr(self, "tahsilat_ozet"):
            self.tahsilat_ozet.pack(anchor="w", pady=(2, 0))
        self._tahsilat_yesil_butonlar_hazir = True

    def _fatura_yesil_oval_buton(self, parent, text, command, padx=4):
        """Yeşil zemin, beyaz yazı, oval 3D tahsilat butonu."""
        return self._fatura_oval_buton(
            parent,
            text,
            command,
            padx=padx,
            zemin="#43a047",
            koyu="#1b5e20",
            acik="#81c784",
            yazi_renk="#ffffff",
        )

    def _fatura_mavi_oval_buton(self, parent, text, command, padx=4):
        """Sarı zemin, siyah yazı, oval (pill) 3D aksiyon butonu."""
        return self._fatura_oval_buton(
            parent,
            text,
            command,
            padx=padx,
            zemin="#f9a825",
            koyu="#f57f17",
            acik="#ffee58",
            yazi_renk="#000000",
        )

    def _fatura_oval_buton(
        self,
        parent,
        text,
        command,
        padx=4,
        zemin="#f9a825",
        koyu="#f57f17",
        acik="#ffee58",
        yazi_renk="#000000",
    ):
        """Oval (pill) 3D aksiyon butonu."""
        yazi = ("Segoe UI", 9, "bold")

        olcu = tk.Label(parent, text=text, font=yazi)
        olcu.update_idletasks()
        tw = max(olcu.winfo_reqwidth(), 40)
        th = max(olcu.winfo_reqheight(), 12)
        olcu.destroy()

        pad_x, pad_y = 16, 5
        genislik = tw + pad_x * 2
        yukseklik = max(th + pad_y * 2, 28)

        try:
            cerceve_renk = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        except tk.TclError:
            cerceve_renk = "#f0f0f0"

        canvas = tk.Canvas(
            parent,
            width=genislik,
            height=yukseklik,
            highlightthickness=0,
            bd=0,
            bg=cerceve_renk,
            cursor="hand2",
        )

        def _kapsul(x1, y1, x2, y2, dolgu):
            r = max((y2 - y1) // 2, 1)
            canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=dolgu, outline="")
            canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=dolgu, outline="")
            canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=dolgu, outline="")

        def _ciz(basili=False):
            canvas.delete("all")
            if basili:
                _kapsul(2, 3, genislik - 2, yukseklik - 1, koyu)
                ty = yukseklik // 2 + 1
            else:
                _kapsul(3, 4, genislik - 1, yukseklik - 1, koyu)
                _kapsul(1, 1, genislik - 3, yukseklik - 3, acik)
                _kapsul(2, 2, genislik - 4, yukseklik - 4, zemin)
                ty = yukseklik // 2
            canvas.create_text(
                genislik // 2, ty, text=text, fill=yazi_renk, font=yazi
            )

        def _bas(_event):
            _ciz(basili=True)

        def _birak(_event):
            _ciz(basili=False)
            if command:
                command()

        def _ayril(_event):
            _ciz(basili=False)

        _ciz()
        canvas.bind("<ButtonPress-1>", _bas)
        canvas.bind("<ButtonRelease-1>", _birak)
        canvas.bind("<Leave>", _ayril)
        canvas.pack(side="left", padx=padx)
        return canvas

    def _fatura_mavi_cark_buton(self, parent, command, padx=6):
        """Mavi zemin, çark amblemli 3D kolon ayar butonu."""
        btn = tk.Button(
            parent,
            text="⚙",
            command=command,
            bg="#1565c0",
            fg="#ffffff",
            activebackground="#0d47a1",
            activeforeground="#ffffff",
            relief=tk.RAISED,
            borderwidth=3,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
            padx=8,
            pady=2,
            highlightthickness=0,
            width=3,
        )

        def _bas(_e, b=btn):
            b.configure(relief=tk.SUNKEN)

        def _birak(_e, b=btn):
            b.configure(relief=tk.RAISED)

        btn.bind("<ButtonPress-1>", _bas)
        btn.bind("<ButtonRelease-1>", _birak)
        btn.pack(side="left", padx=padx)
        return btn

    def _fatura_kirmizi_buton(self, parent, text, command, padx=6):
        """Kırmızı zemin, beyaz yazı, raised 3D görünümlü aksiyon butonu."""
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg="#c62828",
            fg="#ffffff",
            activebackground="#8e0000",
            activeforeground="#ffffff",
            disabledforeground="#ffcdd2",
            relief=tk.RAISED,
            borderwidth=3,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            padx=10,
            pady=3,
            highlightthickness=0,
        )

        def _bas(_e, b=btn):
            b.configure(relief=tk.SUNKEN)

        def _birak(_e, b=btn):
            b.configure(relief=tk.RAISED)

        btn.bind("<ButtonPress-1>", _bas)
        btn.bind("<ButtonRelease-1>", _birak)
        btn.pack(side="left", padx=padx)
        return btn

    def _fatura_satir_baglantilari(self):
        self._fatura_giris_satirini_yeniden_kur()
        butonlar = getattr(self, "_satir_buton_cerceve", None)
        if butonlar is None:
            butonlar = self.satir_tutar.master

        # Eski Ekle/Güncelle ve Temizle ttk butonlarını kaldır
        for cocuk in list(butonlar.winfo_children()):
            try:
                metin = cocuk.cget("text")
            except tk.TclError:
                continue
            if metin in ("Ekle/Güncelle", "Satır Ekle", "Temizle"):
                cocuk.destroy()

        # Kırmızı 3D aksiyon butonları — en başa (görünür)
        self._duzenlenen_satir = None
        self._satir_ekle_btn = self._fatura_kirmizi_buton(
            butonlar, "Satır Ekle", self.satir_kaydet, padx=(0, 6)
        )
        self._fatura_kirmizi_buton(butonlar, "Temizle", self.satir_formunu_temizle, padx=6)
        self._fatura_mavi_cark_buton(butonlar, self._fatura_kolon_ayarlari_ac, padx=6)
        try:
            slaves = butonlar.pack_slaves()
            if slaves and slaves[0] is not self._satir_ekle_btn:
                self._satir_ekle_btn.pack_forget()
                self._satir_ekle_btn.pack(side="left", padx=(0, 6), before=slaves[0])
        except tk.TclError:
            pass

        # Barkod/lot
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

        self._fatura_kirmizi_buton(butonlar, "Satır Sil", self.satir_sil, padx=6)
        ttk.Label(butonlar, text="Silinecek satır:").pack(side="left", padx=(10, 2))
        self.satir_sil_secim = ttk.Combobox(butonlar, state="readonly", width=36)
        self.satir_sil_secim.pack(side="left", padx=(0, 6))
        self._fatura_kirmizi_buton(butonlar, "STOK LİSTESİ", self.stok_listesi_ac, padx=6)
        self._satir_isaretleri = set()
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        self.satir_tablosu.bind("<<TreeviewSelect>>", self.satir_secildi)
        if hasattr(self, "_satir_secim_kutusu_tikla"):
            self.satir_tablosu.bind("<Button-1>", self._satir_secim_kutusu_tikla, add="+")
        self._satir_ekle_buton_guncelle()

        fiyat = self.satir_girdileri["birim_satis_fiyati"]
        self._fiyat_sec_pencere = None
        self._fiyat_sec_atla = False
        self._fiyat_odak_after = None
        fiyat.bind("<F10>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<KeyPress-y>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<KeyPress-Y>", self.fatura_fiyat_secimi_ac)
        fiyat.bind("<FocusIn>", self._fatura_fiyat_odak_geldi)
        fiyat.bind("<FocusOut>", self._fatura_fiyat_odak_cikti)
        # Treeview vb. odaktayken de F10 çalışsın
        self.bind("<F10>", self.fatura_fiyat_secimi_ac)
        ttk.Label(
            butonlar,
            text="(Birim Fiyat: odak / F10 → satış fiyatları | Satır Ekle)",
            foreground="#666666",
        ).pack(side="left", padx=8)

        # Varsayılan iskontolar
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            if alan in self.satir_girdileri and not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].insert(0, "0")

        self._fatura_toplamlari_klasik_kur()
        if hasattr(self, "_doviz_para_birimi"):
            try:
                self._doviz_para_birimi.trace_add("write", self._doviz_satir_pb_guncelle)
            except tk.TclError:
                pass

        kolonlar = tuple(anahtar for anahtar, _, _, _ in FATURA_SATIR_KOLON_TANIMLARI)
        self.satir_tablosu.configure(columns=kolonlar, selectmode="browse", height=15)
        for anahtar, baslik, _, _ in FATURA_SATIR_KOLON_TANIMLARI:
            self.satir_tablosu.heading(anahtar, text=baslik)
            self.satir_tablosu.column(anahtar, width=90, anchor="w")
        self._fatura_kolon_ayarlari = fatura_kolon_ayarlari_yukle()
        self._fatura_kolon_ayarlari_uygula(self._fatura_kolon_ayarlari)
        self._satir_sil_listesini_yenile()

    def _fatura_kolon_ayarlari_uygula(self, ayarlar=None):
        """Kayıtlı kolon görünürlük ve genişliklerini satır tablosuna uygular."""
        if not hasattr(self, "satir_tablosu"):
            return
        ayarlar = ayarlar or getattr(self, "_fatura_kolon_ayarlari", None) or fatura_kolon_ayarlari_yukle()
        self._fatura_kolon_ayarlari = ayarlar
        # Üst başlığa göre hizalar
        sag = {"fiyat", "toplam", "miktar", "irsaliye", "fatura", "acik", "iskonto_tutar", "net_birim_kdv"}
        orta = {"sira", "sec", "birim", "iskonto", "kdv"}
        gorunen = []
        for anahtar, baslik, _, _ in FATURA_SATIR_KOLON_TANIMLARI:
            cfg = ayarlar.get(anahtar) or {"genislik": 90, "gorunur": True, "baslik": baslik}
            genislik = max(20, int(cfg.get("genislik", 90)))
            if anahtar in sag:
                anchor = "e"
            elif anahtar in orta:
                anchor = "center"
            else:
                anchor = "w"
            self.satir_tablosu.heading(anahtar, text=cfg.get("baslik") or baslik, anchor=anchor)
            self.satir_tablosu.column(
                anahtar,
                width=genislik,
                minwidth=20,
                stretch=False,
                anchor=anchor,
            )
            try:
                self.satir_tablosu.column(anahtar, separator=False)
            except tk.TclError:
                pass
            if cfg.get("gorunur", True):
                gorunen.append(anahtar)
        if not gorunen:
            gorunen = [anahtar for anahtar, _, _, _ in FATURA_SATIR_KOLON_TANIMLARI]
        self.satir_tablosu["displaycolumns"] = gorunen
        try:
            self.satir_tablosu.tag_configure("tek", background="#ffffff")
            self.satir_tablosu.tag_configure("cift", background="#e8f5e9")
            self.satir_tablosu.tag_configure("isaretli", background="#fff59d")
        except tk.TclError:
            pass
        if hasattr(self, "_fatura_excel_cizgileri_yenile"):
            self.after_idle(self._fatura_excel_cizgileri_yenile)

    def _fatura_kolon_ayarlari_ac(self):
        mevcut = getattr(self, "_fatura_kolon_ayarlari", None) or fatura_kolon_ayarlari_yukle()
        FaturaKolonAyarDialog(self, mevcut, on_uygula=self._fatura_kolon_ayarlari_uygula)

    def _fatura_giris_satirini_yeniden_kur(self):
        """Alanları orantılı küçültür; tutarı (KDV dahil) üst satıra alır."""
        if "urun_kodu" not in self.satir_girdileri:
            return
        giris = self.satir_girdileri["urun_kodu"].master
        butonlar = getattr(self, "_satir_buton_cerceve", None)
        if butonlar is None:
            butonlar = self.satir_tutar.master
        self._satir_buton_cerceve = butonlar

        eski_degerler = {}
        for alan, widget in list(self.satir_girdileri.items()):
            try:
                eski_degerler[alan] = widget.get()
            except tk.TclError:
                pass

        for cocuk in list(giris.winfo_children()):
            if cocuk is butonlar:
                continue
            cocuk.destroy()
        self.satir_girdileri = {}

        # Eski tutar etiketini buton satırından kaldır (üste taşınacak)
        try:
            self.satir_tutar.pack_forget()
        except tk.TclError:
            pass
        try:
            self.satir_tutar.destroy()
        except tk.TclError:
            pass

        stil = ttk.Style(self)
        yazi = ("Segoe UI", 10, "bold")
        stil.configure("FaturaGiris.TLabel", font=yazi)
        stil.configure("FaturaGiris.TEntry", font=yazi)
        stil.configure("FaturaGiris.TCombobox", font=yazi)
        try:
            stil.map("FaturaGiris.TCombobox", fieldbackground=[("readonly", "white")])
        except tk.TclError:
            pass

        # Ürün adı/açıklama %30 büyüt; PB sütunu için diğerleri orantılı küçültülür
        baz = {
            "urun_kodu": 6,
            "urun_adi": 16,
            "aciklama": 12,
            "miktar": 4,
            "birim": 4,
            "birim_satis_fiyati": 5,
            "satir_para_birimi": 3,
            "iskonto_orani": 4,
            "iskonto_orani_2": 4,
            "iskonto_orani_3": 4,
            "iskonto_tutari": 6,
            "kdv_orani": 4,
            "net_birim_kdvli": 7,
        }
        tutar_baz = 10
        toplam = sum(baz.values()) + tutar_baz
        urun_adi_w = max(round(baz["urun_adi"] * 1.20), 1)
        aciklama_w = max(round(baz["aciklama"] * 1.20), 1)
        diger_eski = toplam - baz["urun_adi"] - baz["aciklama"]
        kalan = max(toplam - urun_adi_w - aciklama_w, 1)
        olcek = kalan / diger_eski

        def _w(alan: str) -> int:
            return max(round(baz[alan] * olcek), 1)

        tutar_w = max(round(tutar_baz * olcek), 1)
        alanlar = (
            ("Kod", "urun_kodu", _w("urun_kodu")),
            ("Ürün Adı", "urun_adi", urun_adi_w),
            ("Açıklama", "aciklama", aciklama_w),
            ("Miktar", "miktar", _w("miktar")),
            ("Birim", "birim", _w("birim")),
            ("Fiyat", "birim_satis_fiyati", _w("birim_satis_fiyati")),
            ("PB", "satir_para_birimi", _w("satir_para_birimi")),
            ("İsk.1 %", "iskonto_orani", _w("iskonto_orani")),
            ("İsk.2 %", "iskonto_orani_2", _w("iskonto_orani_2")),
            ("İsk.3 %", "iskonto_orani_3", _w("iskonto_orani_3")),
            ("İsk. Tutar", "iskonto_tutari", _w("iskonto_tutari")),
            ("KDV %", "kdv_orani", _w("kdv_orani")),
            ("Net Br.+KDV", "net_birim_kdvli", _w("net_birim_kdvli")),
        )
        for sutun, (baslik, alan, genislik) in enumerate(alanlar):
            giris.columnconfigure(sutun, weight=max(genislik, 1), minsize=0)
            ttk.Label(giris, text=baslik, style="FaturaGiris.TLabel").grid(
                row=0, column=sutun, padx=0, pady=1, sticky="w"
            )
            if alan == "birim":
                widget = ttk.Combobox(
                    giris,
                    values=BIRIM_SECENEKLERI,
                    state="readonly",
                    width=genislik,
                    style="FaturaGiris.TCombobox",
                    font=yazi,
                )
            elif alan == "kdv_orani":
                widget = ttk.Combobox(
                    giris,
                    values=KDV_ORANLARI,
                    state="readonly",
                    width=genislik,
                    style="FaturaGiris.TCombobox",
                    font=yazi,
                )
            elif alan == "satir_para_birimi":
                widget = ttk.Combobox(
                    giris,
                    values=PARA_BIRIMLERI,
                    state="readonly",
                    width=genislik,
                    style="FaturaGiris.TCombobox",
                    font=yazi,
                )
                baslangic_pb = "TRY"
                if hasattr(self, "_doviz_para_birimi"):
                    baslangic_pb = (self._doviz_para_birimi.get() or "TRY").upper()
                widget.set(baslangic_pb)
            elif alan in FATURA_SATIR_HESAPLANAN_ALANLAR:
                widget = ttk.Entry(
                    giris,
                    width=genislik,
                    style="FaturaGiris.TEntry",
                    font=yazi,
                    justify="right",
                )
                widget.insert(0, para_goster(Decimal("0")))
                widget.configure(state="readonly")
            else:
                widget = ttk.Entry(
                    giris,
                    width=genislik,
                    style="FaturaGiris.TEntry",
                    font=yazi,
                )
            widget.grid(row=1, column=sutun, padx=0, pady=1, sticky="ew")
            self.satir_girdileri[alan] = widget
            if alan in ("urun_kodu", "urun_adi"):
                widget.bind("<KeyRelease>", self.satir_urun_arama_ac)
            if alan in (
                "miktar",
                "birim_satis_fiyati",
                "iskonto_orani",
                "iskonto_orani_2",
                "iskonto_orani_3",
                "kdv_orani",
            ):
                widget.bind("<KeyRelease>", lambda _e: self.satir_tutar_guncelle())
            if alan == "kdv_orani":
                widget.bind("<<ComboboxSelected>>", lambda _e: self.satir_tutar_guncelle())
            if alan == "satir_para_birimi":
                widget.bind("<<ComboboxSelected>>", lambda _e: self._satir_para_birimi_degisti())

        # Tutar (KDV dahil) — KDV kutusu ile aynı Entry çerçevesi
        tutar_sutun = len(alanlar)
        giris.columnconfigure(tutar_sutun, weight=max(tutar_w, 1), minsize=0)
        ttk.Label(giris, text="Tutar (KDV Dahil)", style="FaturaGiris.TLabel").grid(
            row=0, column=tutar_sutun, padx=0, pady=1, sticky="w"
        )
        self.satir_tutar = ttk.Entry(
            giris,
            width=tutar_w,
            style="FaturaGiris.TEntry",
            font=yazi,
            justify="right",
        )
        self.satir_tutar.grid(row=1, column=tutar_sutun, padx=0, pady=1, sticky="ew")
        self.satir_tutar.insert(0, para_goster(Decimal("0")))
        self.satir_tutar.configure(state="readonly")

        self.satir_girdileri["birim"].set(eski_degerler.get("birim") or "Adet")
        if "satir_para_birimi" in self.satir_girdileri:
            pb = eski_degerler.get("satir_para_birimi")
            if not pb and hasattr(self, "_doviz_para_birimi"):
                pb = (self._doviz_para_birimi.get() or "TRY").upper()
            self.satir_girdileri["satir_para_birimi"].set((pb or "TRY").upper())
        for alan, deger in eski_degerler.items():
            if alan in ("birim", "kdv_orani", "satir_para_birimi") or alan not in self.satir_girdileri:
                continue
            if alan in FATURA_SATIR_HESAPLANAN_ALANLAR:
                continue
            self.satir_girdileri[alan].delete(0, "end")
            self.satir_girdileri[alan].insert(0, deger)
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            if not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].insert(0, "0")
        self.satir_girdileri["kdv_orani"].set("0")

        butonlar.grid(row=2, column=0, columnspan=tutar_sutun + 1, sticky="w", pady=(4, 0))
        self.satir_tutar_guncelle()

    def _fatura_kur_al(self) -> Decimal:
        try:
            return Decimal(str((getattr(self, "_doviz_kur", None) and self._doviz_kur.get() or "1").replace(",", ".")))
        except (ValueError, AttributeError):
            return Decimal("1")

    def _satir_para_birimi_get(self) -> str:
        widget = self.satir_girdileri.get("satir_para_birimi")
        if widget is None:
            return "TRY"
        return (widget.get() or "TRY").upper()

    def _satir_fiyat_yaz(self, tutar):
        alan = self.satir_girdileri.get("birim_satis_fiyati")
        if alan is None:
            return
        metin = f"{Decimal(str(tutar or 0)):f}".rstrip("0").rstrip(".") or "0"
        alan.delete(0, "end")
        alan.insert(0, metin)

    def _satir_giris_fiyat_tl(self) -> Decimal:
        fiyat = decimal(self.satir_girdileri["birim_satis_fiyati"].get() or 0, "Birim fiyat")
        if self._satir_para_birimi_get() == "TRY":
            return fiyat
        kur = self._fatura_kur_al()
        if kur <= 0:
            return fiyat
        return DovizService.dovizden_tle(fiyat, kur)

    def _satir_fiyat_para_birimine_cevir(self, eski_pb: str, yeni_pb: str):
        eski_pb = (eski_pb or "TRY").upper()
        yeni_pb = (yeni_pb or "TRY").upper()
        if eski_pb == yeni_pb:
            return
        try:
            fiyat = decimal(self.satir_girdileri["birim_satis_fiyati"].get() or 0, "Birim fiyat")
        except ValueError:
            fiyat = Decimal("0")
        kur = self._fatura_kur_al()
        if eski_pb != "TRY":
            tl = DovizService.dovizden_tle(fiyat, kur) if kur > 0 else fiyat
        else:
            tl = fiyat
        if yeni_pb != "TRY":
            yeni = DovizService.tl_den_dovize(tl, kur) if kur > 0 else tl
        else:
            yeni = tl
        self._satir_fiyat_yaz(yeni)

    def _satir_para_birimi_degisti(self, _event=None):
        if getattr(self, "_pb_senkron", False):
            return
        widget = self.satir_girdileri.get("satir_para_birimi")
        if widget is None:
            return
        yeni_pb = (widget.get() or "TRY").upper()
        eski_pb = (
            getattr(self, "_doviz_para_birimi", None) and self._doviz_para_birimi.get() or "TRY"
        ).upper()
        self._pb_senkron = True
        try:
            if eski_pb != yeni_pb:
                self._satir_fiyat_para_birimine_cevir(eski_pb, yeni_pb)
            if hasattr(self, "_doviz_para_birimi") and self._doviz_para_birimi.get().upper() != yeni_pb:
                self._doviz_para_birimi.set(yeni_pb)
                doviz_para_birimi_degisti(self)
        finally:
            self._pb_senkron = False
        self.satir_tutar_guncelle()

    def _doviz_satir_pb_guncelle(self, *_args):
        if getattr(self, "_pb_senkron", False):
            return
        widget = self.satir_girdileri.get("satir_para_birimi")
        if widget is None:
            return
        pb = (
            getattr(self, "_doviz_para_birimi", None) and self._doviz_para_birimi.get() or "TRY"
        ).upper()
        if widget.get().upper() == pb:
            return
        eski_pb = widget.get().upper()
        self._pb_senkron = True
        try:
            widget.set(pb)
            if eski_pb != pb:
                self._satir_fiyat_para_birimine_cevir(eski_pb, pb)
        finally:
            self._pb_senkron = False
        self.satir_tutar_guncelle()

    def _tl_fiyati_satir_pb_ile_goster(self, fiyat_tl: Decimal):
        pb = self._satir_para_birimi_get()
        if pb == "TRY":
            self._satir_fiyat_yaz(fiyat_tl)
            return
        kur = self._fatura_kur_al()
        if kur > 0:
            self._satir_fiyat_yaz(DovizService.tl_den_dovize(fiyat_tl, kur))
        else:
            self._satir_fiyat_yaz(fiyat_tl)

    def _iskonto_goster(self, veri) -> str:
        degerler = []
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            try:
                oran = decimal(veri.get(alan) or 0, "İskonto", Decimal("0"))
            except ValueError:
                oran = Decimal("0")
            degerler.append(f"{oran:f}".rstrip("0").rstrip(".") or "0")
        return "+".join(f"{d}%" for d in degerler)

    def _satir_hesapla(self, veri):
        miktar = decimal(veri.get("miktar") or 0, "Miktar")
        fiyat = decimal(veri.get("birim_satis_fiyati") or 0, "Fiyat")
        kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
        maliyet_alan = {
            "FIFO": "fifo_birim_maliyeti",
            "SON ALIŞ FİYATI": "son_alis_birim_maliyeti",
            "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti",
            "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti",
        }.get(self.yontem.get(), "fifo_birim_maliyeti")
        maliyet = decimal(veri.get(maliyet_alan) or 0, "Maliyet")
        brut, indirim, net = SatisFaturasiService._satir_net(
            miktar,
            fiyat,
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
        )
        yon = getattr(self, "_fatura_kurus_yon", "normal")
        brut = kurus_yuvarla(brut, yon)
        indirim = kurus_yuvarla(indirim, yon)
        net = kurus_yuvarla(net, yon)
        kdv_tutar = kurus_yuvarla(net * kdv / 100, yon)
        toplam_maliyet = kurus_yuvarla(miktar * maliyet, yon)
        kar = kurus_yuvarla(net - toplam_maliyet, yon)
        return brut, indirim, net, kdv_tutar, toplam_maliyet, kar, kar / net * 100 if net else Decimal("0")

    def _hesaplanan_alan_yaz(self, alan, metin):
        widget = self.satir_girdileri.get(alan)
        if widget is None:
            return
        try:
            widget.configure(state="normal")
            widget.delete(0, "end")
            widget.insert(0, metin)
            widget.configure(state="readonly")
        except tk.TclError:
            pass

    def satir_tutar_guncelle(self):
        sifir = para_goster(Decimal("0"))
        try:
            miktar = decimal(self.satir_girdileri["miktar"].get() or 0, "Miktar")
            fiyat = self._satir_giris_fiyat_tl()
            kdv = decimal(self.satir_girdileri["kdv_orani"].get() or 0, "KDV")
            brut, indirim, net = SatisFaturasiService._satir_net(
                miktar,
                fiyat,
                self.satir_girdileri.get("iskonto_orani").get() if "iskonto_orani" in self.satir_girdileri else 0,
                self.satir_girdileri.get("iskonto_orani_2").get() if "iskonto_orani_2" in self.satir_girdileri else 0,
                self.satir_girdileri.get("iskonto_orani_3").get() if "iskonto_orani_3" in self.satir_girdileri else 0,
            )
            yon = getattr(self, "_fatura_kurus_yon", "normal")
            indirim = kurus_yuvarla(indirim, yon)
            net = kurus_yuvarla(net, yon)
            genel = kurus_yuvarla(net * (Decimal("1") + kdv / Decimal("100")), yon)
            if miktar > 0:
                net_birim_kdvli = kurus_yuvarla(
                    (net / miktar) * (Decimal("1") + kdv / Decimal("100")),
                    yon,
                )
            else:
                net_birim_kdvli = Decimal("0")
            metin = para_goster(genel)
            iskonto_metin = para_goster(indirim)
            net_birim_metin = para_goster(net_birim_kdvli)
        except (ValueError, AttributeError, ZeroDivisionError):
            metin = sifir
            iskonto_metin = sifir
            net_birim_metin = sifir
        try:
            self.satir_tutar.configure(state="normal")
            self.satir_tutar.delete(0, "end")
            self.satir_tutar.insert(0, metin)
            self.satir_tutar.configure(state="readonly")
        except tk.TclError:
            pass
        self._hesaplanan_alan_yaz("iskonto_tutari", iskonto_metin)
        self._hesaplanan_alan_yaz("net_birim_kdvli", net_birim_metin)

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
        cari = self._secili_musteri()
        if not cari:
            messagebox.showinfo("Cari", "Önce müşteri seçin.", parent=self)
            return
        if self.cari_ac:
            self.cari_ac(cari)
        else:
            dialog = CariDialog(self, cari)
            self.wait_window(dialog)
            self._musteri_listesini_yenile()
            self._bakiye_guncelle()

    def yeni_musteri_ekle(self):
        """Fatura kartından yeni müşteri cari kartı açar ve kayıttan sonra seçer."""
        dialog = CariDialog(self, cari_turu="Müşteri")
        self.wait_window(dialog)
        yeni = dialog.result
        if not yeni:
            return
        self._musteri_listesini_yenile()
        self._fatura_musteriyi_sec(yeni)
        self._fatura_cari_degisti()
        self._fatura_adreslerini_yukle()

    def _musteri_listesini_yenile(self):
        """Aktif müşteri listesini yeniden yükler (yeni cari sonrası)."""
        try:
            self.musteriler = list(SatisFaturasiService.aktif_musterileri())
        except Exception:
            self.musteriler = list(CariService.aktif_musteriler())
        self._fatura_musteri_listesini_bakiyeli_kur()

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
        dialog = ProductSelectionDialog(
            self,
            on_select=self._stok_listesinden_satira_aktar,
            kod=self.satir_girdileri["urun_kodu"].get().strip(),
            ad=self.satir_girdileri["urun_adi"].get().strip(),
        )
        self.wait_window(dialog)

    def _stok_listesinden_satira_aktar(self, degerler):
        """Stok listesinden seçilen ürünü forma doldurup fatura satırlarına ekler."""
        self._duzenlenen_satir = None
        try:
            self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        except tk.TclError:
            pass
        self._satir_ekle_buton_guncelle()
        self._fiyat_sec_atla = True
        self.satir_urun_secildi(degerler)
        self.satir_kaydet()
        try:
            self.satir_girdileri["urun_kodu"].focus_set()
        except tk.TclError:
            pass

    def _satir_ekle_buton_guncelle(self):
        btn = getattr(self, "_satir_ekle_btn", None)
        if btn is None or not str(btn):
            # Yedek: metinden bul
            cerceve = getattr(self, "_satir_buton_cerceve", None)
            if cerceve is not None:
                for w in cerceve.winfo_children():
                    try:
                        if w.cget("text") in ("Satır Ekle", "Satır Güncelle"):
                            btn = w
                            self._satir_ekle_btn = w
                            break
                    except tk.TclError:
                        continue
        if btn is None:
            return
        duzenle = getattr(self, "_duzenlenen_satir", None) is not None
        try:
            if duzenle:
                btn.configure(
                    text="Satır Güncelle",
                    bg="#ef6c00",
                    activebackground="#e65100",
                )
            else:
                btn.configure(
                    text="Satır Ekle",
                    bg="#c62828",
                    activebackground="#8e0000",
                )
        except tk.TclError:
            pass

    def satir_secildi(self, _event=None):
        if getattr(self, "_satir_secim_isleniyor", False):
            return
        secim = self.satir_tablosu.selection()
        if not secim:
            return
        try:
            idx = int(secim[0])
        except (ValueError, TypeError):
            return
        if not (0 <= idx < len(self.satirlar)):
            return
        # Aynı satır zaten düzenleniyorsa formu tekrar doldurma (olay döngüsü / kilitlenme)
        if getattr(self, "_duzenlenen_satir", None) == idx:
            self._satir_ekle_buton_guncelle()
            return
        self._satir_secim_isleniyor = True
        self._fiyat_sec_atla = True  # form doldurulurken fiyat penceresi açılmasın
        try:
            self._duzenlenen_satir = idx
            self.satir_formunu_doldur(self.satirlar[idx])
            self._duzenlenen_satir = idx
            self._satir_ekle_buton_guncelle()
        finally:
            # Seçim olayları idle'a kadar bastırılsın (selection_remove/set döngüsü)
            self.after_idle(self._satir_secim_kilidi_ac)

    def _satir_secim_kilidi_ac(self):
        self._satir_secim_isleniyor = False
        self._fiyat_sec_atla = False

    def satir_formunu_temizle(self):
        # Üst sınıftaki selection_remove, <<TreeviewSelect>> döngüsü ve kilitlenme yapıyor;
        # düzenleme/doldurma sırasında seçimi elleme.
        for alan, widget in self.satir_girdileri.items():
            if alan in FATURA_SATIR_HESAPLANAN_ALANLAR:
                continue
            if isinstance(widget, ttk.Combobox):
                if alan == "birim":
                    widget.set("Adet")
                elif alan == "satir_para_birimi":
                    pb = "TRY"
                    if hasattr(self, "_doviz_para_birimi"):
                        pb = (self._doviz_para_birimi.get() or "TRY").upper()
                    widget.set(pb)
                else:
                    widget.set("")
            else:
                widget.delete(0, "end")
        if not getattr(self, "_duzenleme_koru", False):
            self._duzenlenen_satir = None
            self._satir_ekle_buton_guncelle()
            try:
                self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
            except tk.TclError:
                pass
        if "kdv_orani" in self.satir_girdileri:
            widget = self.satir_girdileri["kdv_orani"]
            if isinstance(widget, ttk.Combobox):
                if "0" not in widget["values"]:
                    widget["values"] = tuple(dict.fromkeys(("0",) + tuple(widget["values"])))
                widget.set("0")
            else:
                widget.delete(0, "end")
                widget.insert(0, "0")
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            if alan in self.satir_girdileri and not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].insert(0, "0")
        self.satir_tutar_guncelle()

    def satir_formunu_doldur(self, veri):
        onceki = getattr(self, "_duzenlenen_satir", None)
        self._duzenleme_koru = True
        self._fiyat_sec_atla = True
        try:
            # Üst sınıf temizle+doldur selection_remove çağırıyor; kendi temizlememizi kullan
            self.satir_formunu_temizle()
            pb = "TRY"
            if hasattr(self, "_doviz_para_birimi"):
                pb = (self._doviz_para_birimi.get() or "TRY").upper()
            for alan, widget in self.satir_girdileri.items():
                if alan in FATURA_SATIR_HESAPLANAN_ALANLAR:
                    continue
                if alan == "satir_para_birimi":
                    widget.set(pb)
                    continue
                if alan == "birim_satis_fiyati":
                    if pb != "TRY" and veri.get("birim_fiyat_doviz"):
                        bf = veri.get("birim_fiyat_doviz")
                    else:
                        bf = veri.get("birim_satis_fiyati", "")
                    self._satir_fiyat_yaz(decimal(bf or 0, "Fiyat", Decimal("0")))
                    continue
                deger = veri.get(alan, "")
                if isinstance(widget, ttk.Combobox):
                    if alan == "birim" and deger and deger not in BIRIM_SECENEKLERI:
                        widget["values"] = BIRIM_SECENEKLERI + (str(deger),)
                    widget.set(
                        "" if deger is None else str(deger) or ("Adet" if alan == "birim" else "")
                    )
                else:
                    widget.delete(0, "end")
                    widget.insert(0, "" if deger is None else str(deger))
        finally:
            self._duzenleme_koru = False
        self._duzenlenen_satir = onceki
        if "kdv_orani" in self.satir_girdileri:
            widget = self.satir_girdileri["kdv_orani"]
            deger = str(veri.get("kdv_orani") or "0").strip()
            deger = f"{decimal(deger, 'KDV', Decimal('0')):f}".rstrip("0").rstrip(".") or "0"
            if isinstance(widget, ttk.Combobox):
                if deger not in widget["values"]:
                    widget["values"] = tuple(widget["values"]) + (deger,)
                widget.set(deger)
            else:
                widget.delete(0, "end")
                widget.insert(0, deger)
        self.satir_tutar_guncelle()
        self._satir_ekle_buton_guncelle()

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

        fiyat_tl = StokService.satis_fiyati_1(kod)
        if fiyat_tl == 0 and len(degerler) > 4 and str(degerler[4]).strip():
            try:
                fiyat_tl = decimal(degerler[4], "Fiyat", Decimal("0"))
            except ValueError:
                fiyat_tl = Decimal("0")
        self._tl_fiyati_satir_pb_ile_goster(fiyat_tl)

        if "barkod" in self.satir_girdileri:
            self.satir_girdileri["barkod"].delete(0, "end")
        bulunan = StokService.stoklari_ara(kod)
        stok = next((s for s in bulunan if s.stok_kodu == kod), None)
        if "barkod" in self.satir_girdileri and stok and stok.barkod:
            self.satir_girdileri["barkod"].insert(0, stok.barkod)
        if not self.satir_girdileri["miktar"].get().strip():
            self.satir_girdileri["miktar"].insert(0, "1")
        if "iskonto_orani" in self.satir_girdileri and not self.satir_girdileri["iskonto_orani"].get().strip():
            self.satir_girdileri["iskonto_orani"].insert(0, "0")
        for alan in ("iskonto_orani_2", "iskonto_orani_3"):
            if alan in self.satir_girdileri and not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].insert(0, "0")
        if "kdv_orani" in self.satir_girdileri:
            widget = self.satir_girdileri["kdv_orani"]
            kdv_ham = getattr(stok, "kdv_orani", None) if stok else None
            deger = (
                f"{decimal(kdv_ham if kdv_ham is not None else 20, 'KDV', Decimal('20')):f}"
                .rstrip("0")
                .rstrip(".")
                or "0"
            )
            if isinstance(widget, ttk.Combobox):
                if deger not in widget["values"]:
                    widget["values"] = tuple(widget["values"]) + (deger,)
                widget.set(deger)
            else:
                widget.delete(0, "end")
                widget.insert(0, deger)
        if "lot_no" in self.satir_girdileri:
            self.lotlari_yukle()
            self.lot_cikis_otomatik()
        self.satir_tutar_guncelle()
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

    def _fatura_fiyat_odak_geldi(self, _event=None):
        """Birim fiyat alanına gelince ürünün satış fiyat listesini aç."""
        if getattr(self, "_fiyat_sec_atla", False):
            return
        if getattr(self, "_satir_secim_isleniyor", False) or getattr(self, "_duzenleme_koru", False):
            return
        if getattr(self, "_fiyat_sec_pencere", None):
            try:
                if self._fiyat_sec_pencere.winfo_exists():
                    return
            except tk.TclError:
                self._fiyat_sec_pencere = None
        if not self.satir_girdileri["urun_kodu"].get().strip():
            return
        if getattr(self, "_fiyat_odak_after", None):
            try:
                self.after_cancel(self._fiyat_odak_after)
            except tk.TclError:
                pass
        self._fiyat_odak_after = self.after(40, self._fatura_fiyat_odak_ac)

    def _fatura_fiyat_odak_ac(self):
        self._fiyat_odak_after = None
        try:
            if self.focus_get() is not self.satir_girdileri["birim_satis_fiyati"]:
                return
        except tk.TclError:
            return
        self.fatura_fiyat_secimi_ac()

    def _fatura_fiyat_odak_cikti(self, _event=None):
        if getattr(self, "_fiyat_sec_pencere", None):
            try:
                if self._fiyat_sec_pencere.winfo_exists():
                    return
            except tk.TclError:
                self._fiyat_sec_pencere = None
        self._fiyat_sec_atla = False

    def fatura_fiyat_secimi_ac(self, _event=None):
        if getattr(self, "_fiyat_sec_pencere", None):
            try:
                if self._fiyat_sec_pencere.winfo_exists():
                    return "break"
            except tk.TclError:
                self._fiyat_sec_pencere = None
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Fiyat", "Önce ürün kodu girin.", parent=self)
            return "break"
        dialog = PriceSelectionDialog(
            self, kod, on_select=self.fatura_fiyati_secildi, fiyat_turu="satis"
        )
        self._fiyat_sec_pencere = dialog
        self.wait_window(dialog)
        self._fiyat_sec_pencere = None
        self._fiyat_sec_atla = True
        try:
            self.satir_girdileri["birim_satis_fiyati"].focus_set()
        except tk.TclError:
            pass
        return "break"

    def fatura_fiyati_secildi(self, fiyat):
        fiyat_tl = Decimal(str(fiyat.tutar))
        pb_fiyat = (getattr(fiyat, "para_birimi", None) or "TRY").upper()
        pb_satir = self._satir_para_birimi_get()
        if pb_fiyat == pb_satir:
            self._satir_fiyat_yaz(fiyat_tl)
        elif pb_satir == "TRY":
            self._satir_fiyat_yaz(fiyat_tl)
        else:
            kur = self._fatura_kur_al()
            if pb_fiyat == "TRY" and kur > 0:
                self._satir_fiyat_yaz(DovizService.tl_den_dovize(fiyat_tl, kur))
            else:
                self._satir_fiyat_yaz(fiyat_tl)
        self.satir_tutar_guncelle()
        self._fiyat_sec_atla = True
        self.after_idle(lambda: self.satir_girdileri["birim_satis_fiyati"].focus_set())

    def satir_kaydet(self):
        """Seçili satır varsa günceller; yoksa yeni satır ekler."""
        def _bos_ise_yaz(alan, varsayilan):
            if alan in self.satir_girdileri and not self.satir_girdileri[alan].get().strip():
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, varsayilan)

        _bos_ise_yaz("miktar", "1")
        _bos_ise_yaz("iskonto_orani", "0")
        _bos_ise_yaz("iskonto_orani_2", "0")
        _bos_ise_yaz("iskonto_orani_3", "0")
        _bos_ise_yaz("kdv_orani", "0")

        veri = {alan: widget.get().strip() for alan, widget in self.satir_girdileri.items()}
        for alan in FATURA_SATIR_HESAPLANAN_ALANLAR:
            veri.pop(alan, None)
        veri.pop("satir_para_birimi", None)
        pb = self._satir_para_birimi_get()
        if hasattr(self, "_doviz_para_birimi") and self._doviz_para_birimi.get().upper() != pb:
            self._doviz_para_birimi.set(pb)
            doviz_para_birimi_degisti(self)
        if not veri.get("urun_kodu") or not veri.get("urun_adi"):
            messagebox.showwarning("Eksik bilgi", "Önce stok seçin, sonra Satır Ekle'ye basın.", parent=self)
            return
        varsayilanlar = {
            "miktar": "1",
            "birim_satis_fiyati": "0",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "0",
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

        idx = getattr(self, "_duzenlenen_satir", None)
        if idx is None:
            secim = self.satir_tablosu.selection()
            if secim:
                try:
                    idx = int(secim[0])
                except (ValueError, TypeError):
                    idx = None

        if idx is not None and 0 <= idx < len(self.satirlar):
            mevcut = self.satirlar[idx]
            for alan in (
                "siparis_satiri_id",
                "irsaliye_satiri_id",
                "irsaliyelenen_miktar",
                "faturalanan_miktar",
                "fifo_birim_maliyeti",
                "son_alis_birim_maliyeti",
                "ortalama_birim_maliyeti",
                "agirlikli_ortalama_birim_maliyeti",
            ):
                if not veri.get(alan) or veri.get(alan) in ("0", ""):
                    if mevcut.get(alan) not in (None, ""):
                        veri[alan] = mevcut.get(alan)
            self.satirlar[idx] = veri
        else:
            self.satirlar.append(veri)

        if hasattr(self, "_doviz_para_birimi"):
            idx_hedef = idx if idx is not None and 0 <= idx < len(self.satirlar) else len(self.satirlar) - 1
            self.satirlar[idx_hedef] = doviz_satir_kaydet_oncesi(self, self.satirlar[idx_hedef])

        self._duzenlenen_satir = None
        self._satirlari_stokla_tamamla()
        self.satir_formunu_temizle()
        _bos_ise_yaz("iskonto_orani", "0")
        _bos_ise_yaz("iskonto_orani_2", "0")
        _bos_ise_yaz("iskonto_orani_3", "0")
        _bos_ise_yaz("kdv_orani", "0")
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
        """👁 / Seç sütununa tıklayınca satırı işaretle / kaldır."""
        tablo = self.satir_tablosu
        if tablo.identify_region(event.x, event.y) != "cell":
            return
        kolon_id = tablo.identify_column(event.x)
        try:
            kolon_sira = int(kolon_id.replace("#", "")) - 1
            gorunen = tablo["displaycolumns"]
            if not gorunen or gorunen == ("#all",):
                gorunen = tablo["columns"]
            kolon_adi = gorunen[kolon_sira]
        except (ValueError, IndexError, KeyError, TypeError):
            return
        if kolon_adi != "sec":
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
                "Silmek için satırın başındaki 👁 kutusunu işaretleyin veya üstteki 'Silinecek satır' listesinden seçin.",
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
            _, indirim, net, kdv, _, _, _ = self._satir_hesapla(veri)
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            kdv_oran = decimal(veri.get("kdv_orani") or 0, "KDV")
            if miktar > 0:
                net_birim_kdvli = kurus_yuvarla(
                    (net / miktar) * (Decimal("1") + kdv_oran / Decimal("100")),
                    getattr(self, "_fatura_kurus_yon", "normal"),
                )
            else:
                net_birim_kdvli = Decimal("0")
            isaret = "☑" if sira in self._satir_isaretleri else "☐"
            if sira in self._satir_isaretleri:
                etiketler = ("isaretli",)
            else:
                etiketler = ("cift",) if sira % 2 else ("tek",)
            # Değer sırası üst başlık kolon sırasıyla birebir
            self.satir_tablosu.insert(
                "",
                "end",
                iid=str(sira),
                tags=etiketler,
                values=(
                    sira + 1,
                    isaret,
                    veri.get("barkod", ""),
                    veri.get("urun_kodu", ""),
                    veri.get("urun_adi", ""),
                    veri.get("aciklama", ""),
                    miktar,
                    veri.get("birim", ""),
                    para_goster(veri.get("birim_satis_fiyati") or 0),
                    self._iskonto_goster(veri),
                    para_goster(indirim),
                    f"{veri.get('kdv_orani') or 0}%",
                    para_goster(net_birim_kdvli),
                    veri.get("lot_no", ""),
                    veri.get("lot_cikisi", ""),
                    para_goster(net + kdv),
                    veri.get("irsaliyelenen_miktar") or 0,
                    veri.get("faturalanan_miktar") or 0,
                    miktar,
                ),
            )
        self._satir_sil_listesini_yenile()
        self._toplamlari_guncelle()
        if hasattr(self, "_tree_excel_cizgileri_yenile"):
            self.after_idle(
                lambda: self._tree_excel_cizgileri_yenile(
                    self.satir_tablosu, "satir", "FaturaSatir.Treeview"
                )
            )

    def _fatura_excel_cizgileri_kur(self):
        """Geriye uyumluluk: satır tablosu ızgarası."""
        if hasattr(self, "satir_tablosu"):
            self._tree_excel_cizgileri_kur(
                self.satir_tablosu, "satir", style_name="FaturaSatir.Treeview"
            )

    def _fatura_excel_cizgileri_yenile(self):
        """Geriye uyumluluk: satır tablosu ızgarası yenile."""
        if hasattr(self, "satir_tablosu"):
            self._tree_excel_cizgileri_yenile(
                self.satir_tablosu, "satir", "FaturaSatir.Treeview"
            )

    def _tree_excel_cizgileri_kur(self, tree, bag_adi, style_name="FaturaSatir.Treeview"):
        """Treeview'a Excel benzeri yatay/dikey çizgi katmanı bağlar."""
        flag = f"_{bag_adi}_excel_kurulu"
        if getattr(self, flag, False):
            self._tree_excel_cizgileri_yenile(tree, bag_adi, style_name)
            return
        parent = tree.master
        setattr(self, f"_{bag_adi}_excel_cizgiler", [])
        setattr(self, f"_{bag_adi}_excel_after", None)

        dikey = yatay = None
        for w in parent.winfo_children():
            if not isinstance(w, ttk.Scrollbar):
                continue
            try:
                orient = str(w.cget("orient"))
            except tk.TclError:
                continue
            if orient == "vertical":
                dikey = w
            elif orient == "horizontal":
                yatay = w

        def planla(_event=None, _tree=tree, _bag=bag_adi, _stil=style_name):
            aid = getattr(self, f"_{_bag}_excel_after", None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except tk.TclError:
                    pass
            setattr(
                self,
                f"_{_bag}_excel_after",
                self.after(
                    15,
                    lambda: self._tree_excel_cizgileri_yenile(_tree, _bag, _stil),
                ),
            )

        def yset(*args, _planla=planla):
            if dikey is not None:
                dikey.set(*args)
            _planla()

        def xset(*args, _planla=planla):
            if yatay is not None:
                yatay.set(*args)
            _planla()

        tree.configure(yscrollcommand=yset, xscrollcommand=xset)
        tree.bind("<Configure>", planla, add="+")
        tree.bind("<MouseWheel>", planla, add="+")
        tree.bind("<ButtonRelease-1>", planla, add="+")
        parent.bind("<Configure>", planla, add="+")
        setattr(self, flag, True)
        planla()

    def _tree_excel_cizgileri_yenile(self, tree, bag_adi, style_name="FaturaSatir.Treeview"):
        """Görünür hücrelerin kenarlarına ince yatay/dikey çizgiler çizer."""
        setattr(self, f"_{bag_adi}_excel_after", None)
        if tree is None:
            return
        parent = tree.master
        lines_attr = f"_{bag_adi}_excel_cizgiler"
        for w in getattr(self, lines_attr, []):
            try:
                w.destroy()
            except tk.TclError:
                pass
        setattr(self, lines_attr, [])
        try:
            if not tree.winfo_ismapped():
                return
        except tk.TclError:
            return

        renk = "#bdbdbd"
        dcols = tree["displaycolumns"]
        if not dcols or dcols in ("#all", ("#all",)):
            dcols = tree["columns"]
        dcols = list(dcols)
        if not dcols:
            return

        try:
            tx, ty = tree.winfo_x(), tree.winfo_y()
        except tk.TclError:
            return

        cizgiler = getattr(self, lines_attr)

        def cizgi(**kwargs):
            fr = tk.Frame(parent, bg=renk, **kwargs)
            cizgiler.append(fr)
            return fr

        def hucre(x, y, w, h, sol=False, ust=False):
            if w <= 1 or h <= 1:
                return
            if ust:
                cizgi(height=1, width=w).place(x=tx + x, y=ty + y)
            cizgi(height=1, width=w).place(x=tx + x, y=ty + y + h - 1)
            if sol:
                cizgi(width=1, height=h).place(x=tx + x, y=ty + y)
            cizgi(width=1, height=h).place(x=tx + x + w - 1, y=ty + y)

        stil = ttk.Style(self)
        try:
            rh = int(float(stil.lookup(style_name, "rowheight") or 22))
        except (TypeError, ValueError):
            rh = 22

        children = list(tree.get_children())
        kolon_xw = None
        baslik_h = None
        son_alt = None
        ilk_veri_y = None

        for item in children:
            for sira, col in enumerate(dcols):
                box = tree.bbox(item, col)
                if not box:
                    continue
                x, y, w, h = box
                if ilk_veri_y is None:
                    ilk_veri_y = y
                hucre(x, y, w, h, sol=(sira == 0), ust=(y == ilk_veri_y))
                if kolon_xw is None:
                    kolon_xw = []
                    for c2 in dcols:
                        b2 = tree.bbox(item, c2)
                        if b2:
                            kolon_xw.append((b2[0], b2[2]))
                    baslik_h = y
                    rh = h
                son_alt = y + h

        if kolon_xw is None:
            toplam_w = sum(max(20, int(tree.column(c, "width") or 20)) for c in dcols) or 1
            try:
                sol = float(tree.xview()[0]) * toplam_w
            except (tk.TclError, ValueError, IndexError):
                sol = 0.0
            kolon_xw = []
            cum = 0
            for col in dcols:
                w = max(20, int(tree.column(col, "width") or 20))
                kolon_xw.append((int(cum - sol), w))
                cum += w
            baslik_h = 26
            son_alt = baslik_h

        if baslik_h and baslik_h > 2 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, 0, w, baslik_h, sol=(sira == 0), ust=True)

        try:
            tablo_h = tree.winfo_height()
        except tk.TclError:
            return
        y = son_alt if son_alt is not None else (baslik_h or 26)
        guvenlik = 0
        while y + rh <= tablo_h and guvenlik < 40 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, y, w, rh, sol=(sira == 0), ust=False)
            y += rh
            guvenlik += 1

    def _fatura_toplamlari_klasik_kur(self):
        """TOPLAMLAR: sağa hizalı klasik blok; sol satır özeti kaldırılır."""
        if not hasattr(self, "satir_ozet"):
            return
        toplamlar = self.satir_ozet.master
        for cocuk in list(toplamlar.winfo_children()):
            cocuk.destroy()

        toplamlar.columnconfigure(0, weight=1)
        toplamlar.columnconfigure(1, weight=0)

        yazi = ("Segoe UI", 11, "bold")
        blok = ttk.Frame(toplamlar)
        blok.grid(row=0, column=1, sticky="e", padx=(8, 4), pady=2)

        self.fatura_toplam_degerleri = {}
        self._fatura_kurus_yon = getattr(self, "_fatura_kurus_yon", "normal")
        self._genel_toplam_duzenleniyor = False
        self._hesaplanan_genel = Decimal("0")
        satirlar = (
            ("ara_toplam", "ARA TOPLAM"),
            ("iskonto", "TOPLAM İSKONTO"),
            ("kdv", "KDV"),
            ("genel", "GENEL TOPLAM"),
        )
        for sira, (anahtar, baslik) in enumerate(satirlar):
            ttk.Label(blok, text=baslik, font=yazi, anchor="e").grid(
                row=sira, column=0, sticky="e", padx=(0, 16), pady=1
            )
            if anahtar == "genel":
                genel_cerceve = ttk.Frame(blok)
                genel_cerceve.grid(row=sira, column=1, sticky="e", pady=1)
                deger = ttk.Entry(
                    genel_cerceve,
                    font=yazi,
                    width=14,
                    justify="right",
                )
                deger.insert(0, "0,00")
                deger.pack(side="left")
                deger.bind("<Return>", self._genel_toplam_uygula)
                deger.bind("<FocusIn>", self._genel_toplam_odak)
                deger.bind("<FocusOut>", self._genel_toplam_odak_cikti)
                ttk.Button(
                    genel_cerceve,
                    text="Fiyatlara Yansıt",
                    width=14,
                    command=self._genel_toplam_uygula,
                ).pack(side="left", padx=(6, 0))
            else:
                deger = ttk.Label(
                    blok, text=para_goster(Decimal("0")), font=yazi, anchor="e", width=16
                )
                deger.grid(row=sira, column=1, sticky="e", pady=1)
            self.fatura_toplam_degerleri[anahtar] = deger

        ttk.Label(
            blok,
            text="GENEL TOPLAM değiştirilince Enter / Fiyatlara Yansıt → birim fiyatlara orantılı dağıtılır",
            foreground="#555555",
            font=("Segoe UI", 8),
        ).grid(row=len(satirlar), column=0, columnspan=2, sticky="e", pady=(2, 0))

        # Üst sınıf güncellemesi için stub (sol tek satır kullanılmaz)
        self.satir_ozet = ttk.Label(toplamlar)
        self.satir_ozet.grid_remove()

    def _para_alani_metni(self, tutar) -> str:
        """Entry için TL'siz tutar metni (1.234,56)."""
        return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def _genel_toplam_alani_yaz(self, tutar):
        widget = (getattr(self, "fatura_toplam_degerleri", {}) or {}).get("genel")
        if widget is None or not isinstance(widget, ttk.Entry):
            return
        if getattr(self, "_genel_toplam_duzenleniyor", False):
            return
        metin = self._para_alani_metni(tutar)
        try:
            if widget.get().strip() == metin:
                return
            widget.delete(0, "end")
            widget.insert(0, metin)
        except tk.TclError:
            pass

    def _genel_toplam_odak(self, _event=None):
        self._genel_toplam_duzenleniyor = True

    def _genel_toplam_odak_cikti(self, _event=None):
        self._genel_toplam_duzenleniyor = False
        widget = (getattr(self, "fatura_toplam_degerleri", {}) or {}).get("genel")
        if widget is None or not isinstance(widget, ttk.Entry):
            return
        try:
            ham = widget.get().strip().replace("TL", "").replace("tl", "").strip()
            yazilan = kurus_yuvarla(decimal(ham or 0, "Genel toplam", Decimal("0")), "normal")
        except ValueError:
            self._genel_toplam_alani_yaz(getattr(self, "_hesaplanan_genel", Decimal("0")))
            return
        mevcut = kurus_yuvarla(getattr(self, "_hesaplanan_genel", Decimal("0")), "normal")
        if yazilan != mevcut:
            self._genel_toplam_uygula()
        else:
            self._genel_toplam_alani_yaz(mevcut)

    def _iskonto_carpani(self, veri) -> Decimal:
        carpani = Decimal("1")
        for sira, alan in enumerate(("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"), start=1):
            oran = decimal(veri.get(alan) or 0, f"İskonto {sira}", Decimal("0"))
            if oran < 0 or oran > 100:
                raise ValueError(f"İskonto {sira} 0-100 arasında olmalıdır.")
            carpani *= Decimal("1") - oran / Decimal("100")
        return carpani

    def _hedef_satir_genelden_fiyat(self, veri, hedef_satir_genel: Decimal) -> Decimal:
        """KDV dahil satır tutarından liste birim fiyatını geri hesaplar."""
        miktar = decimal(veri.get("miktar") or 0, "Miktar")
        kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
        if miktar <= 0:
            raise ValueError("Miktarı olmayan satıra fiyat yansıtılamaz.")
        carpani = self._iskonto_carpani(veri)
        if carpani <= 0:
            raise ValueError("%100 iskontolu satıra fiyat yansıtılamaz.")
        net = Decimal(str(hedef_satir_genel)) / (Decimal("1") + kdv / Decimal("100"))
        fiyat = net / (miktar * carpani)
        return fiyat.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def _genel_toplam_uygula(self, _event=None):
        """Manuel GENEL TOPLAM'ı satır birim fiyatlarına orantılı yansıtır."""
        widget = (getattr(self, "fatura_toplam_degerleri", {}) or {}).get("genel")
        if widget is None or not isinstance(widget, ttk.Entry):
            return
        if not self.satirlar:
            messagebox.showwarning("Genel toplam", "Önce fatura satırı ekleyin.", parent=self)
            self._genel_toplam_alani_yaz(getattr(self, "_hesaplanan_genel", Decimal("0")))
            return
        try:
            ham = widget.get().strip().replace("TL", "").replace("tl", "").strip()
            hedef = kurus_yuvarla(decimal(ham or 0, "Genel toplam", Decimal("0")), "normal")
        except ValueError as hata:
            messagebox.showerror("Geçersiz tutar", str(hata), parent=self)
            self._genel_toplam_alani_yaz(getattr(self, "_hesaplanan_genel", Decimal("0")))
            return
        if hedef < 0:
            messagebox.showwarning("Genel toplam", "Genel toplam negatif olamaz.", parent=self)
            self._genel_toplam_alani_yaz(getattr(self, "_hesaplanan_genel", Decimal("0")))
            return

        mevcut = getattr(self, "_hesaplanan_genel", None)
        if mevcut is None:
            mevcut = self._fatura_genel_toplam()
        mevcut = kurus_yuvarla(mevcut, "normal")
        if hedef == mevcut:
            self._genel_toplam_duzenleniyor = False
            self._genel_toplam_alani_yaz(mevcut)
            return

        try:
            self._genel_toplami_fiyatlara_yansit(hedef)
        except ValueError as hata:
            messagebox.showerror("Fiyatlara yansıtılamadı", str(hata), parent=self)
            self._genel_toplam_duzenleniyor = False
            self._genel_toplam_alani_yaz(mevcut)
            return

        self._genel_toplam_duzenleniyor = False
        self._satir_listesini_yenile()
        # Formda seçili satır varsa fiyatı tazele
        if getattr(self, "_duzenlenen_satir", None) is not None:
            try:
                idx = int(self._duzenlenen_satir)
                if 0 <= idx < len(self.satirlar):
                    self.satir_formunu_doldur(self.satirlar[idx])
            except (TypeError, ValueError, tk.TclError):
                pass
        return "break"

    def _genel_toplami_fiyatlara_yansit(self, hedef_genel: Decimal):
        yon = getattr(self, "_fatura_kurus_yon", "normal")
        hedef = kurus_yuvarla(hedef_genel, yon)
        satir_ozet = []
        mevcut_toplam = Decimal("0")
        for sira, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            if miktar <= 0:
                continue
            _, _, net, kdv_tutar, _, _, _ = self._satir_hesapla(veri)
            satir_genel = kurus_yuvarla(net + kdv_tutar, yon)
            satir_ozet.append((sira, satir_genel, miktar))
            mevcut_toplam += satir_genel

        if not satir_ozet:
            raise ValueError("Fiyat yansıtmak için miktarı olan en az bir satır gerekli.")

        # Hedef satır tutarlarını orantılı (veya miktara göre) dağıt; son satıra kalanı ver
        hedefler = {}
        if mevcut_toplam > 0:
            biriken = Decimal("0")
            for sira, satir_genel, _miktar in satir_ozet[:-1]:
                pay = kurus_yuvarla(hedef * (satir_genel / mevcut_toplam), yon)
                hedefler[sira] = pay
                biriken += pay
            son_sira, _sg, _m = satir_ozet[-1]
            hedefler[son_sira] = kurus_yuvarla(hedef - biriken, yon)
        else:
            toplam_miktar = sum((m for _s, _g, m in satir_ozet), Decimal("0"))
            biriken = Decimal("0")
            for sira, _sg, miktar in satir_ozet[:-1]:
                pay = kurus_yuvarla(hedef * (miktar / toplam_miktar), yon)
                hedefler[sira] = pay
                biriken += pay
            son_sira, _sg, _m = satir_ozet[-1]
            hedefler[son_sira] = kurus_yuvarla(hedef - biriken, yon)

        for sira, hedef_satir in hedefler.items():
            if hedef_satir < 0:
                raise ValueError("Hesaplanan satır tutarı negatif olamaz.")
            veri = self.satirlar[sira]
            yeni_fiyat = self._hedef_satir_genelden_fiyat(veri, hedef_satir)
            if yeni_fiyat < 0:
                raise ValueError("Hesaplanan birim fiyat negatif olamaz.")
            veri["birim_satis_fiyati"] = yeni_fiyat

        # Kuruş farkını son satırda bir kez daha kapat
        yeni_genel = self._fatura_genel_toplam()
        fark = kurus_yuvarla(hedef - yeni_genel, "normal")
        if fark != 0 and satir_ozet:
            son_sira = satir_ozet[-1][0]
            _, _, net, kdv_tutar, _, _, _ = self._satir_hesapla(self.satirlar[son_sira])
            son_hedef = kurus_yuvarla(net + kdv_tutar + fark, "normal")
            if son_hedef < 0:
                raise ValueError("Yuvarlama sonrası satır tutarı negatif kaldı.")
            self.satirlar[son_sira]["birim_satis_fiyati"] = self._hedef_satir_genelden_fiyat(
                self.satirlar[son_sira], son_hedef
            )

    def _toplamlari_guncelle(self, borc=None):
        yon = getattr(self, "_fatura_kurus_yon", "normal")
        toplam = {
            "ara_toplam": Decimal("0"),
            "iskonto": Decimal("0"),
            "net": Decimal("0"),
            "kdv": Decimal("0"),
            "genel": Decimal("0"),
            "maliyet": Decimal("0"),
            "kar": Decimal("0"),
        }
        for veri in self.satirlar:
            brut, indirim, net, kdv, maliyet, kar, _ = self._satir_hesapla(veri)
            toplam["ara_toplam"] += kurus_yuvarla(brut, yon)
            toplam["iskonto"] += kurus_yuvarla(indirim, yon)
            toplam["net"] += kurus_yuvarla(net, yon)
            toplam["kdv"] += kurus_yuvarla(kdv, yon)
            toplam["maliyet"] += kurus_yuvarla(maliyet, yon)
            toplam["kar"] += kurus_yuvarla(kar, yon)
        for anahtar in ("ara_toplam", "iskonto", "net", "kdv", "maliyet", "kar"):
            toplam[anahtar] = kurus_yuvarla(toplam[anahtar], yon)
        toplam["genel"] = kurus_yuvarla(toplam["net"] + toplam["kdv"], yon)
        tahsilat = kurus_yuvarla(
            sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0")),
            yon,
        )
        kalan = kurus_yuvarla(toplam["genel"] - tahsilat, yon)
        acik = kurus_yuvarla(max(Decimal("0"), toplam["genel"] - tahsilat), yon)
        tahmini_bakiye = kurus_yuvarla(self.mevcut_borc + acik, yon)

        if hasattr(self, "fatura_toplam_degerleri"):
            self.fatura_toplam_degerleri["ara_toplam"].configure(
                text=para_goster(toplam["ara_toplam"])
            )
            self.fatura_toplam_degerleri["iskonto"].configure(
                text=para_goster(toplam["iskonto"])
            )
            self.fatura_toplam_degerleri["kdv"].configure(text=para_goster(toplam["kdv"]))
            self._hesaplanan_genel = toplam["genel"]
            self._genel_toplam_alani_yaz(toplam["genel"])
        elif hasattr(self, "satir_ozet"):
            self.satir_ozet.configure(
                text=(
                    f"Ara Toplam: {para_goster(toplam['ara_toplam'])} | "
                    f"KDV Toplamı: {para_goster(toplam['kdv'])} | "
                    f"Genel Toplam: {para_goster(toplam['genel'])}"
                )
            )

        if hasattr(self, "tahsilat_ozet"):
            self.tahsilat_ozet.configure(
                text=(
                    f"Tahsil Edilen: {para_goster(tahsilat)} | "
                    f"Kalan Tahsilat: {para_goster(kalan)}"
                )
            )
        if borc is not None:
            try:
                self._readonly_yaz("tahmini_bakiye", para_goster(tahmini_bakiye))
            except (tk.TclError, AttributeError, KeyError):
                pass

        if not hasattr(self, "ortalama_vade_etiket"):
            return
        cari = self._secili_musteri()
        if not cari:
            if hasattr(self, "eski_bakiye_etiket"):
                self.eski_bakiye_etiket.configure(text="Eski bakiye: -")
            self.yeni_bakiye_etiket.configure(text="Yeni bakiye: -")
            self.ortalama_vade_etiket.configure(text="Ağırlıklı ort.: -")
            return
        if hasattr(self, "eski_bakiye_etiket"):
            self.eski_bakiye_etiket.configure(text=f"Eski bakiye: {para_goster(self.mevcut_borc)}")
        try:
            vade = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            vade = date.today()
        haric = self.fatura.fatura_no if self.fatura else None
        ozet = SatisFaturasiService.bakiye_ozeti(cari.id, acik, vade, haric)
        # Yeni bakiye = eski (hariç) + bu faturanın açığı — tek kaynaktan
        self.yeni_bakiye_etiket.configure(
            text=f"Yeni bakiye: {para_goster(ozet['bakiye'])}"
        )
        ort = ozet.get("ortalama_vade")
        self.ortalama_vade_etiket.configure(
            text=f"Ağırlıklı ort.: {tarih_goster(ort) if ort else '-'}"
        )

    def _irsaliyeyi_doldur(self, irsaliye):
        self.satirlar.clear()
        self._fatura_musteriyi_sec(irsaliye.cari)
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
                "iskonto_orani_2": 0,
                "iskonto_orani_3": 0,
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
        if hasattr(self, "_doviz_para_birimi"):
            doviz_ozet_guncelle(self)

    def _faturayi_doldur(self):
        self.satirlar.clear()
        fatura = self.fatura
        self._fatura_musteriyi_sec(fatura.cari)
        self._entry_yaz("siparis_tarihi", tarih_goster(fatura.fatura_tarihi))
        self._entry_yaz("termin_tarihi", tarih_goster(fatura.vade_tarihi))
        self._entry_yaz(
            "islem_saati",
            saat_varsayilan(fatura.islem_saati or fatura.olusturma_tarihi.strftime("%H:%M")),
        )
        self._entry_yaz("aciklama", fatura.aciklama or "")
        self.siparis_no.set(fatura.siparis.siparis_no if fatura.siparis else "")
        self.irsaliye_no.set(fatura.irsaliye.irsaliye_no if fatura.irsaliye else "")
        self.depo.set(fatura.depo)
        self.dokuman.delete(0, "end")
        self.dokuman.insert(0, fatura.dokuman_yolu or "")
        self._fatura_baglanti_listelerini_yenile(otomatik_sec=False)
        self._fatura_adreslerini_yukle(
            kayitli_no=getattr(fatura, "adres_no", None),
            kayitli_metin=getattr(fatura, "adres_metni", None),
        )
        fatura_pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
        for satir in fatura.satirlar:
            bf_goster = satir.birim_fiyat
            if fatura_pb != "TRY" and getattr(satir, "birim_fiyat_doviz", 0):
                bf_goster = satir.birim_fiyat_doviz
            self.satirlar.append({
                "irsaliye_satiri_id": satir.irsaliye_satiri_id,
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": satir.barkod or "",
                "aciklama": satir.aciklama or "",
                "miktar": satir.miktar,
                "birim": satir.birim,
                "birim_satis_fiyati": bf_goster,
                "birim_fiyat_doviz": getattr(satir, "birim_fiyat_doviz", 0) or bf_goster,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
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
        if fatura.tahsilatlar:
            self.tahsilatlar[:] = [
                {
                    "tahsilat_tarihi": th.tahsilat_tarihi,
                    "tutar": th.tutar,
                    "odeme_sekli": th.odeme_sekli or ODEME_SEKILLERI[0],
                    "hesap": th.hesap or "",
                    "aciklama": th.aciklama or "",
                }
                for th in fatura.tahsilatlar
            ]
        elif fatura.tahsilat_tutari:
            self.tahsilatlar[:] = [{
                "tahsilat_tarihi": fatura.fatura_tarihi,
                "tutar": fatura.tahsilat_tutari,
                "odeme_sekli": fatura.tahsilat_sekli or ODEME_SEKILLERI[0],
                "hesap": fatura.tahsilat_hesabi or "",
                "aciklama": "Fatura tahsilatı",
            }]
        else:
            self.tahsilatlar[:] = []
        self._bakiye_guncelle()
        self._satir_listesini_yenile()
        self._tahsilat_listesini_yenile()
        doviz_verilerini_doldur(self, fatura)

    def _entry_yaz(self, alan, deger):
        self.girdiler[alan].delete(0, "end")
        self.girdiler[alan].insert(0, deger)

    def _fatura_genel_toplam(self):
        yon = getattr(self, "_fatura_kurus_yon", "normal")
        genel = Decimal("0")
        for veri in self.satirlar:
            _, _, net, kdv, _, _, _ = self._satir_hesapla(veri)
            genel += kurus_yuvarla(net, yon) + kurus_yuvarla(kdv, yon)
        return kurus_yuvarla(genel, yon)

    def _tahsilat_kalan(self, haric_index=None):
        """Fatura genel toplamından diğer tahsilat satırları düşülmüş kalan."""
        yon = getattr(self, "_fatura_kurus_yon", "normal")
        tahsil_edilen = Decimal("0")
        for sira, t in enumerate(self.tahsilatlar):
            if haric_index is not None and sira == haric_index:
                continue
            tahsil_edilen += decimal(t["tutar"], "Tahsilat")
        kalan = self._fatura_genel_toplam() - kurus_yuvarla(tahsil_edilen, yon)
        return kurus_yuvarla(kalan, yon)

    def _tahsilat_listesini_yenile(self):
        if not hasattr(self, "tahsilat_tablosu"):
            return
        for item in self.tahsilat_tablosu.get_children():
            self.tahsilat_tablosu.delete(item)
        for sira, t in enumerate(self.tahsilatlar):
            tarih = t.get("tahsilat_tarihi")
            if hasattr(tarih, "strftime"):
                tarih_metin = tarih.strftime("%d.%m.%Y")
            else:
                tarih_metin = str(tarih or "")
            etiket = ("cift",) if sira % 2 else ("tek",)
            self.tahsilat_tablosu.insert(
                "",
                "end",
                iid=str(sira),
                tags=etiket,
                values=(
                    sira + 1,
                    tarih_metin,
                    para_goster(decimal(t.get("tutar") or 0, "Tutar")),
                    t.get("odeme_sekli") or "",
                    t.get("hesap") or "",
                    t.get("aciklama") or "",
                ),
            )
        self._toplamlari_guncelle()
        if getattr(self, "_tahsilat_excel_kurulu", False):
            self.after_idle(
                lambda: self._tree_excel_cizgileri_yenile(
                    self.tahsilat_tablosu, "tahsilat", "FaturaTahsilat.Treeview"
                )
            )

    def tahsilat_ekle(self):
        kalan = self._tahsilat_kalan()
        if not self.satirlar or self._fatura_genel_toplam() <= 0:
            messagebox.showwarning(
                "Tahsilat",
                "Önce fatura satırı ekleyin; genel toplam oluşmadan tahsilat girilemez.",
                parent=self,
            )
            return
        if kalan <= 0:
            messagebox.showwarning(
                "Tahsilat",
                "Fatura tutarı kadar tahsilat zaten girilmiş. Yeni satır eklenemez.",
                parent=self,
            )
            return
        dialog = SiparisTahsilatiDialog(
            self,
            odeme_sekilleri=ODEME_SEKILLERI,
            max_tutar=kalan,
            varsayilan_tutar=kalan,
        )
        self.wait_window(dialog)
        if dialog.result:
            self.tahsilatlar.append(dialog.result)
            self._tahsilat_listesini_yenile()

    def tahsilat_duzenle(self):
        secim = self.tahsilat_tablosu.selection()
        if not secim:
            return
        index = int(secim[0])
        kalan = self._tahsilat_kalan(haric_index=index)
        if kalan < 0:
            kalan = Decimal("0")
        dialog = SiparisTahsilatiDialog(
            self,
            self.tahsilatlar[index],
            odeme_sekilleri=ODEME_SEKILLERI,
            max_tutar=kalan,
        )
        self.wait_window(dialog)
        if dialog.result:
            self.tahsilatlar[index] = dialog.result
            self._tahsilat_listesini_yenile()

    def _fatura_kayit_verilerini_topla(self):
        """Formdan kaydet/onay için ortak veri paketini üretir."""
        musteri = self._secili_musteri()
        if not musteri:
            raise ValueError("Aktif bir müşteri seçin.")
        fatura_tarihi = datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date()
        vade_tarihi = datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date()
        islem_saati = saat_dogrula(
            self.girdiler["islem_saati"].get() if "islem_saati" in self.girdiler else ""
        )
        satirlar = []
        for satir in self.satirlar:
            veri = dict(satir)
            veri["birim_fiyat"] = veri.get("birim_satis_fiyati", 0)
            satirlar.append(veri)
        tahsilat = sum((decimal(t["tutar"], "Tahsilat") for t in self.tahsilatlar), Decimal("0"))
        genel = self._fatura_genel_toplam()
        if tahsilat > genel:
            raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")
        ilk_tahsilat = self.tahsilatlar[0] if self.tahsilatlar else {}
        siparis_id = self.kaynak_siparis.id if self.kaynak_siparis else (
            self.fatura.siparis_id if self.fatura else None
        )
        irsaliye_id = self.kaynak_irsaliye.id if self.kaynak_irsaliye else (
            self.fatura.irsaliye_id if self.fatura else None
        )
        if not siparis_id and self.kaynak_irsaliye and self.kaynak_irsaliye.siparis_id:
            siparis_id = self.kaynak_irsaliye.siparis_id
        yazilan_siparis = self.siparis_no.get().strip()
        yazilan_irsaliye = self.irsaliye_no.get().strip()
        if yazilan_siparis and not siparis_id:
            eslesen = self.bagli_siparis_map.get(yazilan_siparis)
            if not eslesen:
                eslesen = next(
                    (
                        s
                        for s in SatisFaturasiService.acik_siparisler(cari_id=musteri.id)
                        if s.siparis_no == yazilan_siparis
                    ),
                    None,
                )
            if not eslesen:
                raise ValueError(
                    "Yazılan sipariş numarası bu müşteriye ait açık siparişlerde bulunamadı."
                )
            if eslesen.cari_id != musteri.id:
                raise ValueError("Sipariş numarası seçilen müşteriye ait değil.")
            siparis_id = eslesen.id
            self.kaynak_siparis = eslesen
        if yazilan_irsaliye and not irsaliye_id:
            eslesen = self.bagli_irsaliye_map.get(yazilan_irsaliye)
            if not eslesen:
                eslesen = next(
                    (
                        i
                        for i in SatisFaturasiService.acik_irsaliyeler(cari_id=musteri.id)
                        if i.irsaliye_no == yazilan_irsaliye
                    ),
                    None,
                )
            if not eslesen:
                raise ValueError(
                    "Yazılan irsaliye numarası bu müşteriye ait açık irsaliyelerde bulunamadı."
                )
            if eslesen.cari_id != musteri.id:
                raise ValueError("İrsaliye numarası seçilen müşteriye ait değil.")
            irsaliye_id = eslesen.id
            self.kaynak_irsaliye = eslesen
            if not siparis_id and eslesen.siparis_id:
                siparis_id = eslesen.siparis_id
        veriler = {
            "fatura_no": (
                self.fatura.fatura_no
                if self.fatura
                else (
                    self.fatura_no_alani.get().strip()
                    if hasattr(self, "fatura_no_alani")
                    else None
                )
            ),
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
        }
        adres = self._fatura_secili_adres()
        veriler["adres_no"] = adres.get("no")
        veriler["adres_tipi"] = adres.get("tip")
        veriler["adres_metni"] = adres.get("metin")
        if hasattr(self, "_doviz_para_birimi"):
            veriler.update(doviz_verilerini_topla(self))
        return veriler, satirlar

    def kaydet(self):
        if self.fatura and getattr(self.fatura, "onaylandi", False):
            messagebox.showwarning(
                "Düzenleme kilitli",
                "Düzenlemek için önce Onay Kaldır yapın.",
                parent=self,
            )
            return
        if self.fatura and (self.fatura.durum or "") == "İPTAL":
            messagebox.showerror("Kayıt", "İptal edilmiş fatura kaydedilemez.", parent=self)
            return
        try:
            veriler, satirlar = self._fatura_kayit_verilerini_topla()
            self.result = SatisFaturasiService.kaydet(
                veriler,
                satirlar,
                self.fatura.id if self.fatura else None,
                tahsilat_verileri=self.tahsilatlar,
            )
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "Taslak kaydedildi",
            "Fatura taslak olarak kaydedildi.\n"
            "Stok ve cari hareketleri ONAYLA ile oluşur.",
            parent=self,
        )
        self.destroy()

    def onayla(self):
        if self.fatura and getattr(self.fatura, "onaylandi", False):
            messagebox.showinfo("Onay", "Bu fatura zaten onaylanmış.", parent=self)
            return
        if self.fatura and (self.fatura.durum or "") == "İPTAL":
            messagebox.showerror("Onay", "İptal edilmiş fatura onaylanamaz.", parent=self)
            return
        if not messagebox.askyesno(
            "Faturayı onayla",
            "Fatura onaylansın mı?\n"
            "Stok çıkışı, cari borç ve tahsilat hareketleri oluşturulacak.",
            parent=self,
        ):
            return
        try:
            veriler, satirlar = self._fatura_kayit_verilerini_topla()
            kayit = SatisFaturasiService.kaydet(
                veriler,
                satirlar,
                self.fatura.id if self.fatura else None,
                tahsilat_verileri=self.tahsilatlar,
            )
            fatura_id = kayit.id
            self.fatura = SatisFaturasiService.getir(fatura_id) or kayit
            self.result = SatisFaturasiService.onayla(fatura_id)
        except ValueError as hata:
            if self.fatura and getattr(self.fatura, "id", None):
                try:
                    self.fatura = SatisFaturasiService.getir(self.fatura.id) or self.fatura
                except Exception:
                    pass
                self._onay_butonu_guncelle()
            messagebox.showerror("Fatura onaylanamadı", str(hata), parent=self)
            return
        messagebox.showinfo("Onaylandı", "Fatura onaylandı; hareketler oluşturuldu.", parent=self)
        self.destroy()

    def onay_kaldir(self):
        if not self.fatura or not getattr(self.fatura, "id", None):
            messagebox.showinfo("Onay Kaldır", "Önce faturayı kaydedin.", parent=self)
            return
        if (self.fatura.durum or "") == "İPTAL":
            messagebox.showerror("Onay Kaldır", "İptal edilmiş faturanın onayı kaldırılamaz.", parent=self)
            return
        if not getattr(self.fatura, "onaylandi", False):
            messagebox.showinfo("Onay Kaldır", "Bu fatura zaten onaysız (taslak).", parent=self)
            return
        if not messagebox.askyesno(
            "Onay Kaldır",
            "Fatura onayı kaldırılsın mı?\n"
            "Stok çıkışı, cari borç ve tahsilat hareketleri geri alınacak.\n"
            "Fatura satırları korunur; ardından düzenleyebilirsiniz.",
            parent=self,
        ):
            return
        try:
            SatisFaturasiService.onay_kaldir(self.fatura.id)
            self.fatura = SatisFaturasiService.getir(self.fatura.id) or self.fatura
        except ValueError as hata:
            messagebox.showerror("Onay kaldırılamadı", str(hata), parent=self)
            return
        self.result = self.fatura
        if hasattr(self, "durum"):
            try:
                self.durum.set(self.fatura.durum or "TASLAK")
            except tk.TclError:
                pass
        self._onay_butonu_guncelle()
        messagebox.showinfo(
            "Onay kaldırıldı",
            "Fatura onaysız (taslak) duruma alındı.\n"
            "Artık düzenleyip kaydedebilir veya yeniden onaylayabilirsiniz.",
            parent=self,
        )

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

        self.girdiler = {"iade_tarihi": self.tarih}
        doviz_cerceve = ttk.LabelFrame(self, text="DÖVİZ / KUR", padding=6)
        doviz_cerceve.pack(fill="x", padx=12, pady=4)
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, doviz_cerceve)
        if iade:
            doviz_verilerini_doldur(self, iade)
        elif kaynak_fatura:
            doviz_verilerini_doldur(self, kaynak_fatura)

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
        self.satirlar.append(doviz_satir_kaydet_oncesi(self, {
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
        }))
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
            veriler = {
                "iade_tarihi": tarih,
                "cari_id": musteri.id,
                "kaynak_fatura_id": kaynak.id if kaynak else None,
                "depo": self.depo.get() or "ANA DEPO",
                "aciklama": self.aciklama.get().strip() or None,
                "iade_odeme_tutari": 0,
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            self.result = SatisIadeFaturasiService.kaydet(
                veriler, self.satirlar, self.iade.id if self.iade else None
            )
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


class TreeviewKolonFiltrePopup(tk.Toplevel):
    """Excel benzeri kolon başlığı seçim filtresi (çoklu seçim + ara)."""

    BOS_ETIKET = "(Boş)"

    def __init__(self, parent, baslik, degerler, secili=None, uygula_cb=None, temizle_cb=None):
        super().__init__(parent)
        self.title(f"Filtre: {baslik}")
        self.transient(parent)
        self.resizable(False, True)
        self.uygula_cb = uygula_cb
        self.temizle_cb = temizle_cb
        self._tum_degerler = sorted(degerler, key=lambda d: (d == "", str(d).casefold()))
        self._degiskenler = {}
        self._satirlar = []  # (deger, frame)

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=28)
        self.arama.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.arama.bind("<KeyRelease>", self._ara)

        btn_ust = ttk.Frame(self, padding=(8, 0))
        btn_ust.pack(fill="x")
        ttk.Button(btn_ust, text="Tümünü seç", command=self._hepsini_sec).pack(side="left")
        ttk.Button(btn_ust, text="Hiçbirini seçme", command=self._hicbirini_sec).pack(side="left", padx=6)

        orta = ttk.Frame(self, padding=8)
        orta.pack(fill="both", expand=True)
        canvas = tk.Canvas(orta, width=280, height=260, highlightthickness=0)
        scroll = ttk.Scrollbar(orta, orient="vertical", command=canvas.yview)
        self.liste = ttk.Frame(canvas)
        self.liste.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.liste, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        baslangic = set(secili) if secili is not None else set(self._tum_degerler)
        for deger in self._tum_degerler:
            var = tk.BooleanVar(value=deger in baslangic)
            self._degiskenler[deger] = var
            satir = ttk.Frame(self.liste)
            satir.pack(fill="x", anchor="w")
            etiket = self.BOS_ETIKET if deger == "" else str(deger)
            ttk.Checkbutton(satir, text=etiket, variable=var).pack(side="left", anchor="w")
            self._satirlar.append((deger, satir))

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="left")
        ttk.Button(alt, text="Bu Kolonu Temizle", command=self._temizle).pack(side="left", padx=6)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.arama.focus_set()

    def _ara(self, _event=None):
        q = self.arama.get().strip().casefold()
        for deger, satir in self._satirlar:
            etiket = self.BOS_ETIKET if deger == "" else str(deger)
            if not q or q in etiket.casefold():
                satir.pack(fill="x", anchor="w")
            else:
                satir.pack_forget()

    def _hepsini_sec(self):
        for var in self._degiskenler.values():
            var.set(True)

    def _hicbirini_sec(self):
        for var in self._degiskenler.values():
            var.set(False)

    def _uygula(self):
        secilen = {d for d, var in self._degiskenler.items() if var.get()}
        if self.uygula_cb:
            self.uygula_cb(secilen)
        self.destroy()

    def _temizle(self):
        if self.temizle_cb:
            self.temizle_cb()
        self.destroy()


class MuhasebeApp(tk.Tk):
    def __init__(self, startup_bootstrap=None):
        super().__init__()
        from branding import (
            APP_NAME,
            APP_VERSION,
            apply_window_icon,
            run_startup_with_splash,
        )

        self._cin_basarili = False
        self.withdraw()
        self.title(APP_NAME)
        self.geometry("1360x760")
        self.minsize(1024, 620)
        apply_window_icon(self)

        if startup_bootstrap is not None:
            try:
                run_startup_with_splash(self, startup_bootstrap)
            except Exception:
                try:
                    self.destroy()
                except tk.TclError:
                    pass
                raise

        self._stil_ayarla()
        self._arayuzu_olustur()
        self.protocol("WM_DELETE_WINDOW", self.pencere_kapat_istegi)

        # Giriş diyaloğu: withdrawn kök pencere Windows'ta Toplevel'i gizleyebiliyor.
        # Şeffaf ama mapped root ile diyalog görünür kalsın.
        try:
            self.deiconify()
            self.attributes("-alpha", 0.0)
            self.update_idletasks()
        except tk.TclError:
            pass

        from auth_ui import oturum_akisi_calistir

        if not oturum_akisi_calistir(self):
            try:
                from tkinter import messagebox
                from branding import APP_NAME

                messagebox.showinfo(
                    APP_NAME,
                    "Giriş yapılmadı. Program kapatılıyor.",
                    parent=self,
                )
            except Exception:
                pass
            self.destroy()
            return

        try:
            self.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        self._aktif_donemi_yukle()
        self._sistem_menu_gorunurluk_guncelle()
        self._oturum_cubugunu_guncelle()
        self.ana_sayfa_goster()
        self.deiconify()
        self.lift()
        self.focus_force()
        self._cin_basarili = True
        self.after(500, self._pos_valor_kontrol)
        self.after(60_000, self._pos_valor_dongu)
        self.after(800, self._aktarim_durum_guncelle)
        # Hakkında için sürüm referansı
        self.app_version = APP_VERSION

    def _sistem_menu_gorunurluk_guncelle(self):
        """Sistem Yönetimi ve modül menüleri yetkiye göre görünsün."""
        from database.session_manager import oturum
        from database.access import yetki_var

        esleme = {
            "sistem": lambda: (
                oturum.role_kod == "YONETICI"
                or yetki_var("kullanici_yonetme", "firma_yonetme", "sistem_ayarlari")
            ),
            "servis": lambda: (
                oturum.role_kod == "YONETICI"
                or yetki_var(
                    "servis_goruntuleme",
                    "servis_kontrol",
                    "sistem_ayarlari",
                )
            ),
            "satislar": lambda: yetki_var("satis_goruntuleme", "goruntuleme"),
            "satin_alma": lambda: yetki_var("alis_goruntuleme"),
            "stoklar": lambda: yetki_var("stok_goruntuleme", "goruntuleme"),
            "finans": lambda: yetki_var("finans_goruntuleme", "goruntuleme"),
            "gelir_gider": lambda: yetki_var("finans_goruntuleme", "goruntuleme"),
            "genel_muhasebe": lambda: yetki_var("muhasebe_goruntuleme", "goruntuleme"),
            "cek_senet": lambda: yetki_var("finans_goruntuleme", "goruntuleme"),
            "ozet_tablolar": lambda: yetki_var(
                "finans_goruntuleme", "satis_goruntuleme", "goruntuleme"
            ),
            "raporlar": lambda: yetki_var(
                "finans_goruntuleme", "satis_goruntuleme", "stok_goruntuleme", "goruntuleme"
            ),
            "hizli_satis": lambda: yetki_var(
                "satis_duzenleme", "satis_goruntuleme", "goruntuleme"
            ),
            "giris": lambda: True,
            "ayarlar": lambda: True,
        }
        # Pack sırasını korumak için hepsini unut / yeniden paketle
        for anahtar, dugme in self.menu_dugmeleri.items():
            try:
                dugme.pack_forget()
            except tk.TclError:
                pass
        for anahtar, dugme in self.menu_dugmeleri.items():
            kontrol = esleme.get(anahtar, lambda: True)
            try:
                if kontrol():
                    dugme.pack(fill="x", pady=1)
            except tk.TclError:
                pass

    def _aktif_donemi_yukle(self):
        try:
            from database.donem_service import DonemService

            bilgi = DonemService.aktif_veya_varsayilan()
            if bilgi:
                from database.session_manager import oturum

                oturum.set_period(bilgi["id"], bilgi["donem_adi"])
        except Exception:
            pass

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
        from ana_panel_tema import stil_uygula

        stil = ttk.Style(self)
        stil_uygula(stil)

    def _arayuzu_olustur(self):
        from ana_panel_ui import AnaPanelKabuk

        kabuk = AnaPanelKabuk(self)
        kabuk.olustur()
        self._sistem_menu_gorunurluk_guncelle()
        try:
            kabuk.durum_guncelle()
        except Exception:
            pass

    def _oturum_cubugunu_guncelle(self):
        from database.session_manager import oturum

        firma = oturum.firma_unvan or "—"
        kod = oturum.firma_kodu or ""
        donem = oturum.donem_adi or "Dönem: —"
        kullanici = oturum.ad_soyad or oturum.kullanici_adi or "—"
        rol = oturum.role_ad or oturum.role_kod or ""
        try:
            self.oturum_firma_label.configure(text=f"Firma: {firma}" + (f" ({kod})" if kod else ""))
            self.oturum_donem_label.configure(text=donem if donem.startswith("Dönem") else f"Dönem: {donem}")
            self.oturum_kullanici_label.configure(
                text=f"Kullanıcı: {kullanici}" + (f" — {rol}" if rol else "")
            )
            from branding import APP_NAME

            self.title(f"{APP_NAME} — {firma}")
        except tk.TclError:
            pass

    def _acik_belge_var_mi(self) -> bool:
        """Kaydedilmemiş olabilecek açık belge pencereleri."""
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and w.winfo_exists():
                try:
                    if int(w.winfo_viewable()):
                        return True
                except tk.TclError:
                    continue
        return False

    def _ekranlari_temizle(self):
        self._nav_gecmis = []
        self._nav_yeniden_ac = None
        self._nav_son_push = False
        self._nav_geri_gidiyor = True
        try:
            self._icerigi_temizle()
        finally:
            self._nav_geri_gidiyor = False
        self.geri_cubugu_guncelle()
        # Açık diyalogları kapat
        for w in list(self.winfo_children()):
            if isinstance(w, tk.Toplevel) and w.winfo_exists():
                try:
                    w.destroy()
                except tk.TclError:
                    pass

    def firma_degistir_ac(self):
        from database.session_manager import oturum
        from database.system.auth_service import AuthService
        from auth_ui import FirmaSecimDialog

        if not oturum.has_permission("firma_degistirme") and oturum.role_kod != "YONETICI":
            messagebox.showwarning("Yetki", "Firma değiştirme yetkiniz yok.", parent=self)
            return
        if self._acik_belge_var_mi():
            messagebox.showwarning(
                "Firma Değiştir",
                "Açık belge penceresi var. Önce kaydedin veya kapatın.",
                parent=self,
            )
            return
        onceki = oturum.company_id
        secim = FirmaSecimDialog(
            self, yeni_firma_izinli=oturum.has_permission("firma_yonetme")
        )
        self.wait_window(secim)
        if secim.result is None:
            return
        if oturum.company_id != onceki:
            self._ekranlari_temizle()
            self._aktif_donemi_yukle()
            self._oturum_cubugunu_guncelle()
            self.ana_sayfa_goster()
            try:
                from database.database import get_system_session

                with get_system_session() as session:
                    AuthService.audit(
                        session,
                        "firma_degisimi",
                        modul="sistem",
                        kayit_id=str(oturum.company_id),
                        yeni_deger=oturum.firma_unvan,
                    )
            except Exception:
                pass

    def donem_degistir_ac(self):
        from database.session_manager import oturum
        from database.donem_service import DonemService

        if not oturum.has_permission("donem_degistirme") and oturum.role_kod != "YONETICI":
            messagebox.showwarning("Yetki", "Dönem değiştirme yetkiniz yok.", parent=self)
            return
        donemler = DonemService.listele()
        if not donemler:
            if messagebox.askyesno(
                "Dönem",
                "Henüz dönem yok. Çalışma dönemleri ekranına gidelim mi?",
                parent=self,
            ):
                self.sayfa_goster("sistem")
                from sistem_ui import donemler_yonet_goster

                donemler_yonet_goster(self)
            return
        win = tk.Toplevel(self)
        win.title("Dönem Seç")
        win.transient(self)
        win.grab_set()
        ttk.Label(win, text="Çalışma dönemi seçin:", padding=10).pack(anchor="w")
        liste = tk.Listbox(win, height=min(12, len(donemler)), width=40)
        liste.pack(padx=10, pady=4, fill="both", expand=True)
        for d in donemler:
            etiket = d["donem_adi"]
            if d.get("varsayilan"):
                etiket += " (varsayılan)"
            if d.get("kapali"):
                etiket += " [kapalı]"
            liste.insert("end", etiket)
        def sec():
            s = liste.curselection()
            if not s:
                return
            d = donemler[s[0]]
            oturum.set_period(d["id"], d["donem_adi"])
            self._oturum_cubugunu_guncelle()
            win.destroy()
        ttk.Button(win, text="Seç", command=sec).pack(pady=8)
        liste.bind("<Double-1>", lambda _e: sec())


    def sifre_degistir_ac(self):
        from auth_ui import SifreDegistirDialog

        dlg = SifreDegistirDialog(self, zorunlu=False)
        self.wait_window(dlg)

    def oturumu_kapat(self):
        from database.system.auth_service import AuthService
        from database.database import get_system_session
        from auth_ui import oturum_akisi_calistir

        if self._acik_belge_var_mi():
            if not messagebox.askyesno(
                "Oturumu Kapat",
                "Açık belge pencereleri var. Yine de oturumu kapatmak istiyor musunuz?",
                parent=self,
            ):
                return
        try:
            with get_system_session() as session:
                AuthService.audit(session, "oturum_kapatma", modul="sistem")
        except Exception:
            pass
        self._ekranlari_temizle()
        AuthService.cikis()
        if not oturum_akisi_calistir(self):
            self.destroy()
            return
        self._aktif_donemi_yukle()
        self._sistem_menu_gorunurluk_guncelle()
        self._oturum_cubugunu_guncelle()
        self.ana_sayfa_goster()

    def _aktarim_durum_guncelle(self):
        """Alt çubukta EvoBulut aktarım logunu canlı gösterir."""
        try:
            from evobulut_aktarim_durum import durum_oku

            d = durum_oku()
            if d.aktif:
                self._aktarim_yanip_soner = not self._aktarim_yanip_soner
                # Yeşil = çalışıyor (süreç veya taze log)
                renk = "#2e7d32" if self._aktarim_yanip_soner else "#81c784"
            elif d.bitti:
                renk = "#1565c0"  # mavi
            elif d.log_var:
                renk = "#9e9e9e"  # gri — durdu (kırmızı değil)
            else:
                renk = "#bdbdbd"
            self.aktarim_gosterge.itemconfigure(self._aktarim_nokta, fill=renk)
            self.aktarim_durum_label.configure(text=d.metin)
        except Exception:
            pass
        self.after(2000, self._aktarim_durum_guncelle)

    def _icerigi_temizle(self):
        # Yalnızca ileri navigasyonda geçmişe yaz (← butonları / geri / sayfa_goster hariç)
        if (
            getattr(self, "_nav_ileri", False)
            and not getattr(self, "_sayfa_yukleniyor", False)
            and not getattr(self, "_nav_geri_gidiyor", False)
            and getattr(self, "_aktif_sayfa", "giris") not in (None, "giris")
        ):
            self._nav_push_mevcut()
        self._nav_ileri = False
        self._nav_son_push = False
        for widget in self.icerik.winfo_children():
            widget.destroy()
        self.geri_cubugu_guncelle()

    def nav_sayfa_isaretle(self, yeniden_ac):
        """Mevcut içeriği yeniden açmak için geri yükleme fonksiyonunu kaydeder."""
        self._nav_yeniden_ac = yeniden_ac
        self.geri_cubugu_guncelle()

    def nav_ac(self, komut):
        """Alt sayfa açar; geçmişe yazar (Toplevel diyaloglar için kullanmayın)."""
        self._nav_ileri = True
        if getattr(self, "_busy_pending", False) or not hasattr(self, "_menu_islemi"):
            try:
                komut()
            finally:
                self._nav_ileri = False
            return
        self._menu_islemi(komut)

    def _nav_push_mevcut(self):
        if getattr(self, "_nav_geri_gidiyor", False):
            return
        fn = getattr(self, "_nav_yeniden_ac", None)
        if fn is None:
            aktif = getattr(self, "_aktif_sayfa", None)
            if not aktif or aktif == "giris":
                return
            fn = lambda a=aktif: self.sayfa_goster(a)
        if self._nav_gecmis and self._nav_gecmis[-1] is fn:
            return
        self._nav_gecmis.append(fn)

    def geri_cubugu_guncelle(self):
        cubuk = getattr(self, "geri_cubugu", None)
        if cubuk is None:
            return
        goster = (
            bool(getattr(self, "_nav_gecmis", None))
            or getattr(self, "_aktif_sayfa", "giris") not in (None, "giris")
        )
        try:
            if goster:
                if not cubuk.winfo_ismapped():
                    cubuk.pack(fill="x", before=self.icerik)
            else:
                cubuk.pack_forget()
        except tk.TclError:
            pass

    def geri_git(self):
        """Önceki menü/sayfaya döner. Dönüş yapıldıysa True."""
        gecmis = getattr(self, "_nav_gecmis", None)
        if gecmis:
            fn = gecmis.pop()
            self._nav_geri_gidiyor = True
            try:
                fn()
            finally:
                self._nav_geri_gidiyor = False
                self.geri_cubugu_guncelle()
            return True
        aktif = getattr(self, "_aktif_sayfa", "giris")
        if aktif and aktif != "giris":
            self._nav_geri_gidiyor = True
            try:
                self.sayfa_goster("giris")
            finally:
                self._nav_geri_gidiyor = False
            return True
        return False

    def pencere_kapat_istegi(self):
        """Ana pencere X: alt sayfadaysa geri dön; Ana Panel'deyse çıkışı onayla."""
        # Açık Toplevel varken ana pencereyi kapatma / sayfa değiştirme
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and w.winfo_exists():
                try:
                    if int(w.winfo_viewable()):
                        w.lift()
                        try:
                            w.focus_force()
                        except tk.TclError:
                            pass
                        return
                except tk.TclError:
                    continue
        if self.geri_git():
            return
        if self._acik_belge_var_mi():
            if not messagebox.askyesno(
                "Çıkış",
                "Açık belge pencereleri var. Yine de uygulamadan çıkmak istiyor musunuz?",
                parent=self,
            ):
                return
        elif not messagebox.askyesno(
            "Çıkış",
            "Uygulamadan çıkmak istiyor musunuz?",
            parent=self,
        ):
            return
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _menu_islemi(self, komut):
        """Menü komutunu çalıştırır; 2 sn'yi aşarsa 'Yükleniyor' göstergesi açar."""
        if getattr(self, "_busy_pending", False):
            # İç içe menü çağrısı — mevcut yükleme göstergesini paylaş
            try:
                komut()
            finally:
                if getattr(self, "_nav_ileri", False):
                    self._nav_ileri = False
            self._busy_nabiz()
            return
        self._busy_baslat()

        def calistir():
            try:
                komut()
            finally:
                self._busy_bitir()
                # Diyalog vb. içerik değiştirmediyse ileri bayrağını temizle
                if getattr(self, "_nav_ileri", False):
                    self._nav_ileri = False

        # Kısa gecikme: after(2000) zamanlayıcısının kuyruğa girmesini sağlar
        try:
            self.after(10, calistir)
        except tk.TclError:
            calistir()

    def _busy_baslat(self):
        self._busy_pending = True
        self._busy_t0 = time.monotonic()
        self._busy_gosterildi = False
        self._busy_after_id = None
        try:
            self.configure(cursor="watch")
        except tk.TclError:
            pass
        self.update_idletasks()
        try:
            self._busy_after_id = self.after(2000, self._busy_goster_belki)
        except tk.TclError:
            self._busy_after_id = None

    def _busy_nabiz(self):
        """Bekleyen after(2000) göstergesini işler; uzun servis beklerken çağrılır."""
        if not getattr(self, "_busy_pending", False):
            return
        if (
            not getattr(self, "_busy_gosterildi", False)
            and time.monotonic() - getattr(self, "_busy_t0", 0) >= 2.0
        ):
            self._busy_goster()
        try:
            self.update()
        except tk.TclError:
            pass

    def _busy_servis(self, fn, *args, **kwargs):
        """Yavaş servis çağrısını arka planda çalıştırır; 2 sn sonra gösterge görünür."""
        if not getattr(self, "_busy_pending", False):
            return fn(*args, **kwargs)
        sonuc: dict = {}
        hata: dict = {}
        bitti = threading.Event()

        def worker():
            try:
                sonuc["v"] = fn(*args, **kwargs)
            except Exception as exc:
                hata["e"] = exc
            finally:
                bitti.set()

        threading.Thread(target=worker, daemon=True).start()
        while not bitti.wait(0.05):
            self._busy_nabiz()
        if "e" in hata:
            raise hata["e"]
        return sonuc.get("v")

    def _busy_goster_belki(self):
        self._busy_after_id = None
        if not getattr(self, "_busy_pending", False):
            return
        if time.monotonic() - getattr(self, "_busy_t0", 0) < 1.9:
            return
        self._busy_goster()

    def _busy_goster(self):
        if getattr(self, "_busy_gosterildi", False):
            return
        self._busy_gosterildi = True
        try:
            if getattr(self, "_busy_overlay", None) is not None:
                try:
                    if self._busy_overlay.winfo_exists():
                        self._busy_overlay.lift()
                        self.update_idletasks()
                        return
                except tk.TclError:
                    pass
            overlay = tk.Frame(self, bg="#1a1a1a", highlightthickness=0)
            overlay.place(relx=0.5, rely=0.45, anchor="center")
            kutu = tk.Frame(overlay, bg="#ffffff", padx=28, pady=18,
                            highlightbackground="#1f6aa5", highlightthickness=2)
            kutu.pack()
            self._busy_label = tk.Label(
                kutu,
                text="Yükleniyor…",
                font=("Segoe UI", 12, "bold"),
                fg="#1f6aa5",
                bg="#ffffff",
            )
            self._busy_label.pack()
            tk.Label(
                kutu,
                text="İşlem devam ediyor, lütfen bekleyin",
                font=("Segoe UI", 9),
                fg="#555555",
                bg="#ffffff",
            ).pack(pady=(4, 0))
            self._busy_overlay = overlay
            self._busy_anim_adim = 0
            self._busy_anim_tick()
            self.update_idletasks()
        except tk.TclError:
            pass

    def _busy_anim_tick(self):
        if not getattr(self, "_busy_gosterildi", False):
            return
        label = getattr(self, "_busy_label", None)
        if label is None:
            return
        try:
            self._busy_anim_adim = (getattr(self, "_busy_anim_adim", 0) + 1) % 4
            label.configure(text="Yükleniyor" + "." * self._busy_anim_adim)
            self._busy_anim_after = self.after(400, self._busy_anim_tick)
        except tk.TclError:
            pass

    def _busy_bitir(self):
        self._busy_pending = False
        after_id = getattr(self, "_busy_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except (tk.TclError, ValueError):
                pass
            self._busy_after_id = None
        anim = getattr(self, "_busy_anim_after", None)
        if anim is not None:
            try:
                self.after_cancel(anim)
            except (tk.TclError, ValueError):
                pass
            self._busy_anim_after = None
        self._busy_gosterildi = False
        overlay = getattr(self, "_busy_overlay", None)
        if overlay is not None:
            try:
                overlay.destroy()
            except tk.TclError:
                pass
            self._busy_overlay = None
        self._busy_label = None
        try:
            self.configure(cursor="")
        except tk.TclError:
            pass
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _alt_menu_dugme(self, parent, baslik, komut, **grid_kwargs):
        """Alt menü butonu — yavaş açılışta yükleniyor göstergesi ile."""
        def calistir(c=komut):
            self._nav_ileri = True
            self._menu_islemi(c)

        ttk.Button(
            parent,
            text=baslik,
            style="AltMenu.TButton",
            command=calistir,
        ).grid(**grid_kwargs)

    def ana_sayfa_goster(self):
        self.sayfa_goster("giris")

    def sayfa_goster(self, anahtar):
        from database.access import yetki_var

        # Sol menüden üst düzey geçiş: geçmişi sıfırla (geri ile dönüşte koru)
        if not getattr(self, "_nav_geri_gidiyor", False):
            self._nav_gecmis = []
            self._nav_son_push = False

        # Aynı ekranın mükerrer açılmasını engelle (giriş hariç yenilenebilir)
        if (
            anahtar == getattr(self, "_aktif_sayfa", None)
            and anahtar not in ("giris",)
            and getattr(self, "_sayfa_yukleniyor", False) is False
            and not getattr(self, "_nav_geri_gidiyor", False)
        ):
            # İçerik zaten bu sayfa — tekrar çizme
            if self.icerik.winfo_children():
                self.geri_cubugu_guncelle()
                return

        gerekli = {
            "satislar": ("satis_goruntuleme", "goruntuleme"),
            "satin_alma": ("alis_goruntuleme",),
            "stoklar": ("stok_goruntuleme", "goruntuleme"),
            "finans": ("finans_goruntuleme", "goruntuleme"),
            "gelir_gider": ("finans_goruntuleme", "goruntuleme"),
            "genel_muhasebe": ("muhasebe_goruntuleme", "goruntuleme"),
            "cek_senet": ("finans_goruntuleme", "goruntuleme"),
            "ozet_tablolar": ("finans_goruntuleme", "satis_goruntuleme", "goruntuleme"),
            "raporlar": ("finans_goruntuleme", "satis_goruntuleme", "stok_goruntuleme", "goruntuleme"),
            "hizli_satis": ("satis_duzenleme", "satis_goruntuleme", "goruntuleme"),
            "sistem": ("kullanici_yonetme", "firma_yonetme", "sistem_ayarlari"),
            "servis": ("servis_goruntuleme", "servis_kontrol", "sistem_ayarlari"),
        }
        kodlar = gerekli.get(anahtar)
        if kodlar and not yetki_var(*kodlar):
            messagebox.showwarning("Yetki", "Bu bölüme erişim yetkiniz yok.", parent=self)
            return
        self._menu_islemi(lambda: self._sayfa_goster_icerik(anahtar))

    def _sayfa_goster_icerik(self, anahtar):
        self._sayfa_yukleniyor = True
        try:
            self._icerigi_temizle()
            self._busy_nabiz()
            kabuk = getattr(self, "_ana_panel_kabuk", None)
            if kabuk is not None:
                kabuk.menu_secili_guncelle(anahtar)
            else:
                for dugme_anahtari, dugme in self.menu_dugmeleri.items():
                    if dugme_anahtari == anahtar:
                        dugme.configure(style="SeciliMenu.TButton")
                    elif dugme_anahtari == "hizli_satis":
                        dugme.configure(style="HizliSatisMenu.TButton")
                    else:
                        dugme.configure(style="Menu.TButton")

            self._aktif_sayfa = anahtar
            self._nav_yeniden_ac = lambda a=anahtar: self.sayfa_goster(a)

            basliklar = {
                "giris": "ANA PANEL",
                "satislar": "SATIŞLAR",
                "satin_alma": "SATIN ALMA",
                "stoklar": "STOKLAR",
                "finans": "FİNANS",
                "gelir_gider": "GELİR VE GİDERLER",
                "genel_muhasebe": "GENEL MUHASEBE",
                "cek_senet": "ÇEK VE SENET",
                "ozet_tablolar": "ÖZET TABLOLAR",
                "raporlar": "RAPORLAR",
                "hizli_satis": "HIZLI SATIŞ",
                "sistem": "KULLANICI VE FİRMA YÖNETİMİ",
                "servis": "SERVİS VE SİSTEM KONTROLÜ",
                "ayarlar": "AYARLAR",
            }
            if anahtar not in (
                "hizli_satis",
                "giris",
                "finans",
                "gelir_gider",
                "genel_muhasebe",
                "ozet_tablolar",
                "cek_senet",
                "raporlar",
                "ayarlar",
                "sistem",
                "servis",
                "satislar",
            ):
                ttk.Label(
                    self.icerik, text=basliklar.get(anahtar, anahtar.upper()), style="Baslik.TLabel"
                ).pack(anchor="w", padx=20, pady=(16, 0))
            if anahtar == "giris":
                from ana_panel_ui import giris_dashboard_goster

                giris_dashboard_goster(self)
            elif anahtar == "satislar":
                satislar_hub_goster(self)
            elif anahtar == "satin_alma":
                self.satin_alma_menusu_goster()
            elif anahtar == "stoklar":
                self.stoklar_menusu_goster()
            elif anahtar == "finans":
                self.finans_goster()
            elif anahtar == "gelir_gider":
                gelir_gider_menusu_goster(self)
            elif anahtar == "genel_muhasebe":
                genel_muhasebe_menusu_goster(self)
            elif anahtar == "cek_senet":
                from finans_ui import cek_senet_menusu_goster

                cek_senet_menusu_goster(self)
                if kabuk is not None:
                    kabuk.menu_secili_guncelle("cek_senet")
            elif anahtar == "ozet_tablolar":
                ozet_tablolar_menusu_goster(self)
            elif anahtar == "raporlar":
                from ana_panel_ui import raporlar_menusu_goster

                raporlar_menusu_goster(self)
            elif anahtar == "hizli_satis":
                from hizli_satis_ui import hizli_satis_goster

                hizli_satis_goster(self)
            elif anahtar == "sistem":
                from sistem_ui import sistem_menusu_goster

                sistem_menusu_goster(self)
            elif anahtar == "servis":
                from servis_sistem_ui import servis_sistem_goster

                servis_sistem_goster(self)
            elif anahtar == "ayarlar":
                from ana_panel_ui import ayarlar_goster

                ayarlar_goster(self)
            else:
                ttk.Label(
                    self.icerik, text="Bu bölüm sonraki aşamada hazırlanacaktır."
                ).pack(anchor="w", pady=(18, 0), padx=20)
            self._busy_nabiz()
            kabuk = getattr(self, "_ana_panel_kabuk", None)
            if kabuk is not None:
                try:
                    kabuk.durum_guncelle()
                except Exception:
                    pass
            self.geri_cubugu_guncelle()
        finally:
            self._sayfa_yukleniyor = False

    def odeme_makbuzu_ac(self):
        """Hızlı giriş: ödeme makbuzu."""
        if getattr(self, "_busy_pending", False):
            self._busy_bitir()
        from kasa_makbuz_ui import KasaMakbuzDialog

        dialog = KasaMakbuzDialog(self, makbuz_turu="ODEME")
        self.wait_window(dialog)

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
            self._alt_menu_dugme(
                alt_menu, baslik, komut,
                row=satir, column=0, sticky="ew", pady=4,
            )

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
        ttk.Button(ust, text="EvoBulut’tan Aktar", command=self.evobulut_stok_aktar).pack(side="right", padx=(0, 8))
        cerceve = ttk.Frame(self.icerik)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "ad", "tur", "barkod", "birim", "kdv", "fiyatlar", "miktar")
        basliklar = ("Stok Kodu", "Stok Adı", "Kart Türü", "Barkod", "Birim", "KDV %", "Tanımlı Fiyatlar", "Toplam Mevcut")
        self.stok_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik in zip(kolonlar, basliklar):
            self.stok_tablosu.heading(kolon, text=baslik)
            self.stok_tablosu.column(kolon, width=120, anchor="w")
        self.stok_tablosu.column("ad", width=240)
        self.stok_tablosu.column("kdv", width=70, anchor="center")
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
        ttk.Button(alt, text="Sil", command=self.stok_soft_sil).pack(side="left")
        ttk.Button(alt, text="Stok Girişi", command=self.stok_girisi).pack(side="left", padx=8)
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
        arama = self.stok_arama.get().strip()

        def _yukle():
            satirlar = []
            for stok in StokService.stoklari_ara(arama):
                fiyatlar = " | ".join(
                    f"{f.fiyat_adi}: {para_goster(f.tutar)}" for f in stok.fiyatlar
                )
                mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
                kdv = getattr(stok, "kdv_orani", None)
                kdv_metin = (
                    f"{Decimal(kdv):f}".rstrip("0").rstrip(".")
                    if kdv is not None
                    else "20"
                ) or "0"
                satirlar.append((
                    stok.id,
                    (
                        stok.stok_kodu,
                        stok.stok_adi,
                        getattr(stok, "kart_turu", "") or "",
                        stok.barkod or "",
                        stok.birim,
                        kdv_metin,
                        fiyatlar,
                        mevcut,
                    ),
                ))
            return satirlar

        satirlar = self._busy_servis(_yukle) or []
        for i, (stok_id, values) in enumerate(satirlar):
            if i % 40 == 0:
                self._busy_nabiz()
            self.stok_tablosu.insert("", "end", iid=str(stok_id), values=values)

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

    def evobulut_stok_aktar(self):
        from evobulut_stok_ui import EvobulutStokAktarDialog

        dialog = EvobulutStokAktarDialog(self)
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

    def stok_soft_sil(self):
        stok = self._secili_stok()
        if not stok:
            return
        from silinen_kayitlar_ui import stok_soft_sil

        if stok_soft_sil(self, stok):
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
        """Satışlar hub (kurumsal kartlar) — geriye dönük alias."""
        satislar_hub_goster(self)

    def cari_hesap_islemleri_menusu_goster(self):
        cari_hesap_islemleri_goster(self)

    def satis_raporlar_alt_menusu_goster(self):
        satis_raporlar_hub_goster(self)

    def satis_faturalari_alt_menusu_goster(self):
        """Satış faturaları listesi, hızlı fatura ve iade faturaları alt menüsü."""
        self._icerigi_temizle()
        from satis_tema import HubKart, ekran_ust_cubugu, stil_uygula

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "SATIŞ FATURALARI",
            alt_baslik="Satış faturaları listesi, hızlı fatura ve satış iade faturaları",
            geri_komut=lambda: satislar_hub_goster(self),
            geri_metin="← Satışlar",
        )
        ızgara = tk.Frame(govde)
        ızgara.pack(fill="both", expand=True, pady=8)
        ızgara.columnconfigure(0, weight=1)
        ogeler = (
            ("SATIŞ FATURALARI LİSTESİ", "Kayıtlı satış faturalarını inceleyin ve düzenleyin", self.satis_faturalari_goster),
            ("HIZLI FATURA", "Boş satış faturası kartını hemen açın", self.hizli_fatura_ac),
            ("SATIŞ İADE FATURALARI", "Satış iade faturalarını yönetin", self.satis_iade_faturalari_goster),
        )
        for i, (baslik, aciklama, komut) in enumerate(ogeler):
            HubKart(
                ızgara,
                baslik=baslik,
                aciklama=aciklama,
                komut=lambda c=komut: self.nav_ac(c),
            ).grid(row=i, column=0, sticky="ew", pady=6, padx=4)
        self.nav_sayfa_isaretle(self.satis_faturalari_alt_menusu_goster)

    def hizli_fatura_ac(self):
        """Listeye gitmeden boş satış faturası kartını açar (Satış Faturaları → Yeni Fatura ile aynı şablon)."""
        # Modal diyalog açılmadan önce yükleniyor göstergesini kapat
        if getattr(self, "_busy_pending", False):
            self._busy_bitir()
        dialog = SatisFaturasiDialog(self, cari_ac=lambda cari: CariDialog(self, cari))
        self.wait_window(dialog)

    def tahsilat_makbuzu_ac(self):
        """Hızlı giriş: çok satırlı tahsilat makbuzu (nakit / havale / POS)."""
        if getattr(self, "_busy_pending", False):
            self._busy_bitir()
        from kasa_makbuz_ui import KasaMakbuzDialog

        dialog = KasaMakbuzDialog(self, makbuz_turu="TAHSILAT")
        self.wait_window(dialog)

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
            self._alt_menu_dugme(
                alt_menu, baslik, komut,
                row=satir, column=0, sticky="ew", pady=4,
            )

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
        from satis_tema import ekran_ust_cubugu, stil_uygula, tk_buton, treeview_stil

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "CARİ VİRMAN",
            alt_baslik="Alacak yazılan tutar karşı cariye aynı miktarda otomatik borç yazılır.",
            geri_komut=lambda: cari_hesap_islemleri_goster(self),
            geri_metin="← Cari İşlemler",
        )

        arama_cerceve = ttk.Frame(govde)
        arama_cerceve.pack(fill="x", pady=(0, 8))
        ttk.Label(arama_cerceve, text="Ara:").pack(side="left")
        self.virman_arama = ttk.Entry(arama_cerceve, width=36)
        self.virman_arama.pack(side="left", padx=6)
        tk_buton(arama_cerceve, "Listele", self.virman_listesini_yenile, rol="ara").pack(side="left")

        cerceve = ttk.Frame(govde)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("belge", "tarih", "kaynak", "hedef", "tutar", "aciklama")
        basliklar = ("Belge No", "Tarih", "Alacak Cari", "Borç (Karşı) Cari", "Tutar", "Açıklama")
        self.virman_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.virman_tablosu)
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

        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=10)
        tk_buton(alt, "Yeni Virman Fişi", self.yeni_virman, rol="yeni").pack(side="left")
        tk_buton(alt, "Dosyadan Aktar", self.virman_dosyadan_aktar, rol="duzenle").pack(side="left", padx=8)
        tk_buton(alt, "İptal Et", self.virman_iptal, rol="iptal").pack(side="left", padx=8)
        self.virman_listesini_yenile()
        self.nav_sayfa_isaretle(self.cari_virman_goster)

    def virman_dosyadan_aktar(self):
        from cari_virman_aktar_ui import CariVirmanAktarDialog

        dialog = CariVirmanAktarDialog(self)
        self.wait_window(dialog)
        if dialog.result:
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
        from satis_tema import ekran_ust_cubugu, stil_uygula, tk_buton, treeview_stil

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİM EVRAKI",
            alt_baslik="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit serbest; finans hesabına düşmez.",
            geri_komut=lambda: cari_hesap_islemleri_goster(self),
            geri_metin="← Cari İşlemler",
        )

        arama_cerceve = ttk.Frame(govde)
        arama_cerceve.pack(fill="x", pady=(0, 8))
        ttk.Label(arama_cerceve, text="Ara:").pack(side="left")
        self.kk_arama = ttk.Entry(arama_cerceve, width=36)
        self.kk_arama.pack(side="left", padx=6)
        tk_buton(arama_cerceve, "Listele", self.kk_listesini_yenile, rol="ara").pack(side="left")

        cerceve = ttk.Frame(govde)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("belge", "tarih", "musteri", "tedarikci", "tutar", "banka", "cekim", "taksit", "aciklama")
        basliklar = (
            "Belge No", "Tarih", "Müşteri (Alacak)", "Tedarikçi (Borç)",
            "Tutar", "Banka", "Çekim Türü", "Taksit", "Açıklama",
        )
        self.kk_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.kk_tablosu)
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

        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=10)
        tk_buton(alt, "Yeni KK Çekim Fişi", self.yeni_kk_cekimi, rol="yeni").pack(side="left")
        tk_buton(alt, "Güncelle", self.kk_cekimi_guncelle, rol="duzenle").pack(side="left", padx=8)
        tk_buton(alt, "İptal Et", self.kk_cekimi_iptal, rol="iptal").pack(side="left", padx=8)
        self.kk_tablosu.bind("<Double-1>", lambda _e: self.kk_cekimi_guncelle())
        self.kk_listesini_yenile()
        self.nav_sayfa_isaretle(self.kk_cekimi_goster)

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
        if dialog.winfo_exists():
            self.wait_window(dialog)
        if dialog.result:
            self.kk_listesini_yenile()

    def kk_cekimi_guncelle(self):
        secim = self.kk_tablosu.selection() if hasattr(self, "kk_tablosu") else ()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen güncellenecek KK çekim fişini seçin.", parent=self)
            return
        dialog = KkCekimiDialog(self, belge_no=secim[0])
        if dialog.winfo_exists():
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
        from satis_tema import HubKart, ekran_ust_cubugu, stil_uygula

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "SATIŞ RAPORLARI",
            alt_baslik="Müşteri bakiye, ekstre, tahsilat/ödeme, kar-zarar ve satış özeti",
            geri_komut=lambda: satis_raporlar_hub_goster(self),
            geri_metin="← Raporlar",
        )
        ızgara = tk.Frame(govde)
        ızgara.pack(fill="both", expand=True, pady=8)
        ızgara.columnconfigure(0, weight=1)
        for i, (baslik, komut) in enumerate((
            ("MÜŞTERİ BAKİYE DURUM (ORTALAMA VADELİ)", self.rapor_musteri_bakiye_durum),
            ("MÜŞTERİ EKSTRESİ (ORTALAMA VALÖRLÜ / AĞIRLIKLI)", self.rapor_musteri_ekstresi),
            ("STOK DETAYLI MÜŞTERİ EKSTRESİ", self.rapor_stok_detayli_ekstre),
            ("TARİH ARALIKLI ÖDEME VE TAHSİLAT RAPORU", self.rapor_tahsilat_odeme),
            ("MÜŞTERİ SEÇİMLİ KAR / ZARAR RAPORU", self.rapor_kar_zarar),
            ("SATIŞ ÖZETİ", self.rapor_satis_ozeti),
        )):
            HubKart(
                ızgara,
                baslik=baslik,
                aciklama="Satış rapor ekranını açar",
                komut=lambda c=komut: self.nav_ac(c),
            ).grid(row=i, column=0, sticky="ew", pady=4, padx=4)
        self.nav_sayfa_isaretle(self.satis_raporlari_goster)

    def _rapor_baslik(self, baslik, geri=True):
        from satis_tema import BEYAZ, LACIVERT, SARI, font, stil_uygula, tk_buton

        stil_uygula(root=self)
        ust = tk.Frame(self.icerik, bg=LACIVERT)
        ust.pack(fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(sol, text=baslik, bg=LACIVERT, fg=BEYAZ, font=font(16, "bold", self), anchor="w").pack(
            anchor="w"
        )
        tk.Frame(ust, bg=SARI, height=3).pack(fill="x")
        if geri:
            sag = tk.Frame(ust, bg=LACIVERT)
            sag.pack(side="right", padx=10, pady=8)
            tk_buton(sag, "← Raporlar", self.satis_raporlari_goster, rol="geri").pack()
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
            ("tarih", "tur", "belge", "aciklama", "pb", "doviz", "kur", "borc", "alacak", "bakiye", "gun"),
            ("Tarih", "Tür", "Belge No", "Açıklama", "PB", "Döviz", "Kur", "Borç", "Alacak", "Bakiye", "Gün"),
            (85, 95, 120, 150, 40, 85, 75, 100, 100, 110, 55),
        )
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
            pb = (s.get("para_birimi") or "TRY").upper()
            doviz = s.get("doviz_tutari") or 0
            kur = s.get("kur") or 1
            doviz_metin = (
                f"{float(doviz):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if pb != "TRY" and Decimal(str(doviz or 0)) != 0
                else ""
            )
            kur_metin = (
                f"{float(kur):,.6f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if pb != "TRY"
                else ""
            )
            self.ekstre_tablo.insert("", "end", values=(
                tarih_goster(s["tarih"]), s["tur"], s["belge_no"], s["aciklama"],
                pb if pb != "TRY" else "",
                doviz_metin,
                kur_metin,
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
        from satis_tema import ekran_ust_cubugu, stil_uygula, treeview_stil

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "SATIŞ FATURALARI",
            alt_baslik="Varsayılan: son 2 gün  |  Sol tık: sırala  |  Sağ tık: filtre  |  Eski faturalar için tarih aralığını genişletip Uygula",
            geri_komut=self.satis_faturalari_alt_menusu_goster,
            geri_metin="← Satış Faturaları",
        )
        # İçerik govde üzerine kurulur
        self._satis_fatura_govde = govde

        # Tarih / vade takvim filtreleri
        tarih_filtre = ttk.Frame(govde)
        tarih_filtre.pack(fill="x", pady=(0, 0))
        ttk.Label(tarih_filtre, text="Fatura Tarihi:").pack(side="left")
        ft_bas = ttk.Frame(tarih_filtre)
        ft_bas.pack(side="left", padx=(4, 2))
        self.fatura_tarih_bas = ttk.Entry(ft_bas, width=10)
        self.fatura_tarih_bas.pack(side="left")
        takvim_butonu(ft_bas, self.fatura_tarih_bas, on_select=self.fatura_listesini_yenile)
        ttk.Label(tarih_filtre, text="–").pack(side="left", padx=2)
        ft_bit = ttk.Frame(tarih_filtre)
        ft_bit.pack(side="left", padx=(2, 10))
        self.fatura_tarih_bit = ttk.Entry(ft_bit, width=10)
        self.fatura_tarih_bit.pack(side="left")
        takvim_butonu(ft_bit, self.fatura_tarih_bit, on_select=self.fatura_listesini_yenile)

        ttk.Label(tarih_filtre, text="Vade:").pack(side="left")
        vd_bas = ttk.Frame(tarih_filtre)
        vd_bas.pack(side="left", padx=(4, 2))
        self.fatura_vade_bas = ttk.Entry(vd_bas, width=10)
        self.fatura_vade_bas.pack(side="left")
        takvim_butonu(vd_bas, self.fatura_vade_bas, on_select=self._fatura_listeyi_goster)
        ttk.Label(tarih_filtre, text="–").pack(side="left", padx=2)
        vd_bit = ttk.Frame(tarih_filtre)
        vd_bit.pack(side="left", padx=(2, 8))
        self.fatura_vade_bit = ttk.Entry(vd_bit, width=10)
        self.fatura_vade_bit.pack(side="left")
        takvim_butonu(vd_bit, self.fatura_vade_bit, on_select=self._fatura_listeyi_goster)
        ttk.Button(tarih_filtre, text="Uygula", command=self.fatura_listesini_yenile).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(tarih_filtre, text="Tarihleri Temizle", command=self._fatura_tarih_filtre_temizle).pack(
            side="left", padx=6
        )
        # Varsayılan: son 2 gün (bugün-2 … bugün)
        self._fatura_tarih_varsayilan_yaz()

        cerceve = ttk.Frame(govde)
        cerceve.pack(fill="both", expand=True, pady=(10, 0))
        kolonlar = ("no", "tarih", "saat", "vade", "musteri", "siparis", "irsaliye", "depo", "toplam", "tahsilat", "kalan", "durum", "onay")
        basliklar = ("Fatura No", "Fatura Tarihi", "Saat", "Vade Tarihi", "Müşteri", "Sipariş No", "İrsaliye No", "Depo", "Genel Toplam", "Tahsilat", "Kalan", "Durum", "Onay")
        self._fatura_liste_kolonlar = kolonlar
        self._fatura_liste_basliklar = dict(zip(kolonlar, basliklar))
        self._fatura_liste_filtre = {}
        self._fatura_liste_ham = []
        self._fatura_liste_siralama = None  # (kolon, reverse:bool) reverse=False → küçükten büyüğe
        self._fatura_filtre_popup = None
        self._fatura_para_kolonlari = ("toplam", "tahsilat", "kalan")
        # Kolon genişlik / hiza (nizami görünüm)
        self._fatura_kolon_duzen = {
            "no": (108, "center"),
            "tarih": (100, "center"),
            "saat": (58, "center"),
            "vade": (100, "center"),
            "musteri": (240, "w"),
            "siparis": (108, "center"),
            "irsaliye": (108, "center"),
            "depo": (88, "center"),
            "toplam": (118, "e"),
            "tahsilat": (110, "e"),
            "kalan": (110, "e"),
            "durum": (88, "center"),
            "onay": (90, "center"),
        }
        self.fatura_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.fatura_tablosu)
        for kolon, baslik in zip(kolonlar, basliklar):
            genislik, hiza = self._fatura_kolon_duzen[kolon]
            self.fatura_tablosu.heading(
                kolon,
                text=f"{baslik} ▾",
                command=lambda c=kolon: self._fatura_kolon_sirala(c),
                anchor="center",
            )
            self.fatura_tablosu.column(
                kolon,
                width=genislik,
                minwidth=50,
                anchor=hiza,
                stretch=(kolon == "musteri"),
            )
        # Onay satır renkleri (en sağdaki Onay kolonuna göre tüm satır)
        self.fatura_tablosu.tag_configure("onaysiz", background="#c62828", foreground="#ffffff")
        self.fatura_tablosu.tag_configure("onayli", background="#c8e6c9", foreground="#000000")

        # Kolon altına hizalı toplam satırı
        self.fatura_toplam_satiri = ttk.Treeview(
            cerceve, columns=kolonlar, show="headings", height=1, selectmode="none"
        )
        for kolon in kolonlar:
            genislik, hiza = self._fatura_kolon_duzen[kolon]
            self.fatura_toplam_satiri.heading(kolon, text="", anchor="center")
            self.fatura_toplam_satiri.column(kolon, width=genislik, minwidth=50, anchor=hiza, stretch=(kolon == "musteri"))
        self.fatura_toplam_satiri.heading("depo", text="Σ Filtre")
        self.fatura_toplam_satiri.heading("toplam", text="Σ Genel Toplam")
        self.fatura_toplam_satiri.heading("tahsilat", text="Σ Tahsilat")
        self.fatura_toplam_satiri.heading("kalan", text="Σ Kalan")
        self.fatura_toplam_satiri.tag_configure("toplam", background="#fff8e1", font=("Segoe UI", 9, "bold"))

        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.fatura_tablosu.yview)
        self._fatura_yatay_scroll = ttk.Scrollbar(cerceve, orient="horizontal", command=self._fatura_xview)
        self.fatura_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=self._fatura_xscroll_set)
        self.fatura_tablosu.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        self.fatura_toplam_satiri.grid(row=1, column=0, sticky="ew")
        self._fatura_yatay_scroll.grid(row=2, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        self.fatura_tablosu.bind("<Double-1>", lambda _e: self.fatura_ac())
        self.fatura_tablosu.bind("<Button-3>", self._fatura_baslik_sag_tik)
        self.fatura_tablosu.bind("<Configure>", lambda _e: self._fatura_toplam_genislikleri_esitle())
        alt = ttk.Frame(govde); alt.pack(fill="x", pady=10)
        ttk.Button(alt, text="Yeni Fatura", command=self.yeni_fatura).pack(side="left")
        ttk.Button(alt, text="Faturayı Aç / Düzenle", command=self.fatura_ac).pack(side="left", padx=8)
        ttk.Button(alt, text="İade Faturası Oluştur", command=self.faturadan_iade_olustur).pack(side="left")
        ttk.Button(alt, text="İptal Et", command=self.fatura_iptal).pack(side="left", padx=8)
        ttk.Button(alt, text="Taslak Sil", command=self.fatura_taslak_sil).pack(side="left")
        ttk.Button(alt, text="Filtreleri Temizle", command=self._fatura_filtreleri_temizle).pack(side="left", padx=8)
        ttk.Label(alt, text="Σ Kuruş:").pack(side="left", padx=(12, 2))
        self._fatura_liste_kurus_yon = "normal"
        self.fatura_liste_kurus_etiket = ttk.Label(alt, text="Normal", foreground="#555555")
        self.fatura_liste_kurus_etiket.pack(side="left", padx=(0, 4))
        ttk.Button(alt, text="↑", width=3, command=lambda: self._fatura_liste_kurus_ayarla("yukari")).pack(side="left")
        ttk.Button(alt, text="↓", width=3, command=lambda: self._fatura_liste_kurus_ayarla("asagi")).pack(side="left", padx=2)
        ttk.Button(alt, text="½", width=3, command=lambda: self._fatura_liste_kurus_ayarla("normal")).pack(side="left")
        self.fatura_filtre_ozet = ttk.Label(alt, text="", foreground="#555555")
        self.fatura_filtre_ozet.pack(side="left", padx=8)
        self._fatura_toplam_temizle()
        self.fatura_listesini_yenile()
        self.nav_sayfa_isaretle(self.satis_faturalari_goster)
    def _fatura_xview(self, *args):
        self.fatura_tablosu.xview(*args)
        if hasattr(self, "fatura_toplam_satiri"):
            self.fatura_toplam_satiri.xview(*args)

    def _fatura_xscroll_set(self, first, last):
        if hasattr(self, "_fatura_yatay_scroll"):
            self._fatura_yatay_scroll.set(first, last)
        if hasattr(self, "fatura_toplam_satiri"):
            try:
                self.fatura_toplam_satiri.xview_moveto(first)
            except tk.TclError:
                pass

    def fatura_listesini_yenile(self):
        if not hasattr(self, "fatura_tablosu"):
            return
        # Boş tarih → varsayılan son 2 gün (9 bin satırı yanlışlıkla yüklememek için)
        tarih_bas = self._fatura_entry_tarih(getattr(self, "fatura_tarih_bas", None))
        tarih_bit = self._fatura_entry_tarih(getattr(self, "fatura_tarih_bit", None))
        if tarih_bas is None and tarih_bit is None:
            self._fatura_tarih_varsayilan_yaz()
            tarih_bas = self._fatura_entry_tarih(self.fatura_tarih_bas)
            tarih_bit = self._fatura_entry_tarih(self.fatura_tarih_bit)
        elif tarih_bas is None:
            tarih_bas = (tarih_bit - timedelta(days=2)) if tarih_bit else (date.today() - timedelta(days=2))
            try:
                self.fatura_tarih_bas.delete(0, "end")
                self.fatura_tarih_bas.insert(0, tarih_goster(tarih_bas))
            except tk.TclError:
                pass
        elif tarih_bit is None:
            tarih_bit = date.today()
            try:
                self.fatura_tarih_bit.delete(0, "end")
                self.fatura_tarih_bit.insert(0, tarih_goster(tarih_bit))
            except tk.TclError:
                pass

        if hasattr(self, "fatura_filtre_ozet"):
            try:
                self.fatura_filtre_ozet.configure(text="Liste yükleniyor…")
            except tk.TclError:
                pass
        token = getattr(self, "_fatura_yenile_token", 0) + 1
        self._fatura_yenile_token = token
        yukle_bas, yukle_bit = tarih_bas, tarih_bit

        def _yukle():
            ham = []
            for o in SatisFaturasiService.listele_ozet(tarih_bas=yukle_bas, tarih_bit=yukle_bit):
                toplam = o["genel_toplam"] or Decimal("0")
                tahsilat = o["tahsilat_tutari"] or Decimal("0")
                kalan = toplam - tahsilat
                onayli = bool(o.get("onaylandi"))
                onay_metin = "Onaylı" if onayli else "Onaysız"
                unvan = o.get("musteri") or ""
                ham.append({
                    "id": o["id"],
                    "onaylandi": onayli,
                    "values": (
                        o.get("fatura_no") or "",
                        tarih_goster(o["fatura_tarihi"]) if o.get("fatura_tarihi") else "",
                        o.get("islem_saati") or "",
                        tarih_goster(o["vade_tarihi"]) if o.get("vade_tarihi") else "",
                        unvan,
                        o.get("siparis_no") or "",
                        o.get("irsaliye_no") or "",
                        o.get("depo") or "",
                        para_goster(toplam),
                        para_goster(tahsilat),
                        para_goster(kalan),
                        o.get("durum") or "",
                        onay_metin,
                    ),
                    "sort": (
                        (o.get("fatura_no") or "").casefold(),
                        o.get("fatura_tarihi") or date.min,
                        o.get("islem_saati") or "",
                        o.get("vade_tarihi") or date.min,
                        unvan.casefold(),
                        (o.get("siparis_no") or "").casefold(),
                        (o.get("irsaliye_no") or "").casefold(),
                        (o.get("depo") or "").casefold(),
                        Decimal(toplam or 0),
                        Decimal(tahsilat),
                        Decimal(kalan),
                        (o.get("durum") or "").casefold(),
                        onay_metin.casefold(),
                    ),
                })
            return ham

        def _doldur(ham):
            if getattr(self, "_fatura_yenile_token", 0) != token:
                return
            if not hasattr(self, "fatura_tablosu"):
                return
            self._fatura_liste_ham = ham or []
            self._fatura_listeyi_goster()

        def _hata(exc):
            if getattr(self, "_fatura_yenile_token", 0) != token:
                return
            messagebox.showerror("Fatura listesi", str(exc), parent=self)
            if hasattr(self, "fatura_filtre_ozet"):
                try:
                    self.fatura_filtre_ozet.configure(text="")
                except tk.TclError:
                    pass

        arka_planda(self, _yukle, on_ok=_doldur, on_err=_hata)

    def _fatura_tarih_varsayilan_yaz(self):
        """Fatura tarihi filtresini son 2 güne (bugün-2 … bugün) ayarlar."""
        bitis = date.today()
        baslangic = bitis - timedelta(days=2)
        for alan, deger in (
            ("fatura_tarih_bas", baslangic),
            ("fatura_tarih_bit", bitis),
        ):
            w = getattr(self, alan, None)
            if w is None:
                continue
            try:
                w.delete(0, "end")
                w.insert(0, tarih_goster(deger))
            except tk.TclError:
                pass

    def _fatura_filtreli_satirlar(self):
        kolonlar = getattr(self, "_fatura_liste_kolonlar", ())
        filtre = getattr(self, "_fatura_liste_filtre", {}) or {}
        tarih_bas = self._fatura_entry_tarih(getattr(self, "fatura_tarih_bas", None))
        tarih_bit = self._fatura_entry_tarih(getattr(self, "fatura_tarih_bit", None))
        vade_bas = self._fatura_entry_tarih(getattr(self, "fatura_vade_bas", None))
        vade_bit = self._fatura_entry_tarih(getattr(self, "fatura_vade_bit", None))
        idx_tarih = kolonlar.index("tarih") if "tarih" in kolonlar else None
        idx_vade = kolonlar.index("vade") if "vade" in kolonlar else None
        sonuc = []
        for satir in getattr(self, "_fatura_liste_ham", []):
            values = satir["values"]
            sort = satir["sort"]
            uygun = True
            for i, kolon in enumerate(kolonlar):
                if kolon not in filtre:
                    continue
                secilen = filtre[kolon]
                deger = "" if i >= len(values) or values[i] is None else str(values[i])
                if deger not in secilen:
                    uygun = False
                    break
            if not uygun:
                continue
            if idx_tarih is not None and (tarih_bas or tarih_bit):
                t = sort[idx_tarih]
                if not isinstance(t, date) or t == date.min:
                    uygun = False
                elif tarih_bas and t < tarih_bas:
                    uygun = False
                elif tarih_bit and t > tarih_bit:
                    uygun = False
            if not uygun:
                continue
            if idx_vade is not None and (vade_bas or vade_bit):
                v = sort[idx_vade]
                if not isinstance(v, date) or v == date.min:
                    uygun = False
                elif vade_bas and v < vade_bas:
                    uygun = False
                elif vade_bit and v > vade_bit:
                    uygun = False
            if uygun:
                sonuc.append(satir)
        siralama = getattr(self, "_fatura_liste_siralama", None)
        if siralama:
            kolon, reverse = siralama
            try:
                idx = kolonlar.index(kolon)
            except ValueError:
                return sonuc
            sonuc.sort(
                key=lambda s: (
                    s["sort"][idx] is None,
                    s["sort"][idx] if s["sort"][idx] is not None else "",
                ),
                reverse=reverse,
            )
        return sonuc

    def _fatura_entry_tarih(self, entry):
        if entry is None:
            return None
        try:
            metin = entry.get().strip()
        except tk.TclError:
            return None
        if not metin:
            return None
        try:
            return datetime.strptime(metin, "%d.%m.%Y").date()
        except ValueError:
            return None

    def _fatura_tarih_filtre_temizle(self):
        for ad in ("fatura_vade_bas", "fatura_vade_bit"):
            w = getattr(self, ad, None)
            if w is None:
                continue
            try:
                w.delete(0, "end")
            except tk.TclError:
                pass
        # Fatura tarihini boş bırakma — varsayılan son 2 güne dön (tüm listeyi yükleme)
        self._fatura_tarih_varsayilan_yaz()
        self.fatura_listesini_yenile()
    def _fatura_listeyi_goster(self):
        if not hasattr(self, "fatura_tablosu"):
            return
        for item in self.fatura_tablosu.get_children():
            self.fatura_tablosu.delete(item)
        gorunen = self._fatura_filtreli_satirlar()
        for sira, satir in enumerate(gorunen):
            if satir.get("onaylandi"):
                etiket = "onayli"
            else:
                etiket = "onaysiz"
            self.fatura_tablosu.insert(
                "", "end", iid=str(satir["id"]), values=satir["values"], tags=(etiket,)
            )
        self._fatura_basliklari_guncelle()
        self._fatura_filtreli_satirlari_topla()
        toplam = len(getattr(self, "_fatura_liste_ham", []))
        if hasattr(self, "fatura_filtre_ozet"):
            aktif = len(getattr(self, "_fatura_liste_filtre", {}) or {})
            tarih_aktif = any(
                self._fatura_entry_tarih(getattr(self, ad, None))
                for ad in ("fatura_tarih_bas", "fatura_tarih_bit", "fatura_vade_bas", "fatura_vade_bit")
            )
            siralama = getattr(self, "_fatura_liste_siralama", None)
            parcalar = [
                f"Gösterilen: {len(gorunen)} / {toplam}"
                if (aktif or tarih_aktif)
                else f"Toplam: {toplam}"
            ]
            if aktif:
                parcalar.append(f"Aktif filtre: {aktif}")
            if tarih_aktif:
                parcalar.append("Tarih/vade filtresi açık")
            if siralama:
                yon = "Z→A" if siralama[1] else "A→Z"
                ad = self._fatura_liste_basliklar.get(siralama[0], siralama[0])
                parcalar.append(f"Sıra: {ad} ({yon})")
            self.fatura_filtre_ozet.configure(text="  |  ".join(parcalar))

    def _fatura_basliklari_guncelle(self):
        basliklar = getattr(self, "_fatura_liste_basliklar", {})
        filtre = getattr(self, "_fatura_liste_filtre", {}) or {}
        siralama = getattr(self, "_fatura_liste_siralama", None)
        for kolon, baslik in basliklar.items():
            parcalar = [baslik]
            if siralama and siralama[0] == kolon:
                parcalar.append("↓" if siralama[1] else "↑")
            parcalar.append("▼" if kolon in filtre else "▾")
            try:
                self.fatura_tablosu.heading(kolon, text=" ".join(parcalar))
            except tk.TclError:
                pass

    def _fatura_kolon_sirala(self, kolon):
        """Sol tık: küçükten büyüğe ↔ büyükten küçüğe."""
        mevcut = getattr(self, "_fatura_liste_siralama", None)
        if mevcut and mevcut[0] == kolon:
            self._fatura_liste_siralama = (kolon, not mevcut[1])
        else:
            self._fatura_liste_siralama = (kolon, False)  # önce A→Z / küçükten büyüğe
        self._fatura_listeyi_goster()

    def _fatura_baslik_sag_tik(self, event):
        """Sağ tık: para kolonlarında filtrelenmiş satır toplamı; diğerlerinde filtre."""
        tablo = self.fatura_tablosu
        if tablo.identify_region(event.x, event.y) != "heading":
            return
        kolon_id = tablo.identify_column(event.x)
        try:
            idx = int(kolon_id.replace("#", "")) - 1
            kolon = self._fatura_liste_kolonlar[idx]
        except (ValueError, IndexError, AttributeError):
            return
        if kolon in getattr(self, "_fatura_para_kolonlari", ()):
            # Shift+sağ tık → filtre; düz sağ tık → görünen (filtrelenmiş) satır toplamı
            if event.state & 0x0001:  # Shift
                self._fatura_kolon_filtre_ac(kolon)
            else:
                self._fatura_filtreli_satirlari_topla()
        else:
            self._fatura_kolon_filtre_ac(kolon)
        return "break"

    def _fatura_toplam_genislikleri_esitle(self):
        if not hasattr(self, "fatura_toplam_satiri") or not hasattr(self, "fatura_tablosu"):
            return
        duzen = getattr(self, "_fatura_kolon_duzen", {})
        for kolon in getattr(self, "_fatura_liste_kolonlar", ()):
            try:
                genislik = self.fatura_tablosu.column(kolon, "width")
                hiza = duzen.get(kolon, (genislik, "w"))[1]
                self.fatura_toplam_satiri.column(kolon, width=genislik, anchor=hiza)
            except tk.TclError:
                pass

    def _fatura_toplam_temizle(self):
        if not hasattr(self, "fatura_toplam_satiri"):
            return
        for item in self.fatura_toplam_satiri.get_children():
            self.fatura_toplam_satiri.delete(item)
        kolonlar = getattr(self, "_fatura_liste_kolonlar", ())
        degerler = [""] * len(kolonlar)
        if "depo" in kolonlar:
            degerler[kolonlar.index("depo")] = "—"
        self.fatura_toplam_satiri.insert("", "end", iid="toplam", values=tuple(degerler), tags=("toplam",))

    def _fatura_liste_kurus_ayarla(self, yon):
        self._fatura_liste_kurus_yon = yon if yon in ("yukari", "asagi", "normal") else "normal"
        etiket = getattr(self, "fatura_liste_kurus_etiket", None)
        if etiket is not None:
            metin = {"yukari": "Yukarı", "asagi": "Aşağı", "normal": "Normal"}.get(
                self._fatura_liste_kurus_yon, "Normal"
            )
            try:
                etiket.configure(text=metin)
            except tk.TclError:
                pass
        self._fatura_filtreli_satirlari_topla()

    def _fatura_filtreli_satirlari_topla(self):
        """Listede görünen (filtrelenmiş) faturaların tutar toplamını alt satıra yazar."""
        if not hasattr(self, "fatura_tablosu") or not hasattr(self, "fatura_toplam_satiri"):
            return
        satirlar = self._fatura_filtreli_satirlar()
        kolonlar = self._fatura_liste_kolonlar
        idx_toplam = kolonlar.index("toplam")
        idx_tahsilat = kolonlar.index("tahsilat")
        idx_kalan = kolonlar.index("kalan")
        yon = getattr(self, "_fatura_liste_kurus_yon", "normal")
        t_toplam = Decimal("0")
        t_tahsilat = Decimal("0")
        t_kalan = Decimal("0")
        for satir in satirlar:
            sort = satir["sort"]
            t_toplam += kurus_yuvarla(sort[idx_toplam] or 0, yon)
            t_tahsilat += kurus_yuvarla(sort[idx_tahsilat] or 0, yon)
            t_kalan += kurus_yuvarla(sort[idx_kalan] or 0, yon)
        t_toplam = kurus_yuvarla(t_toplam, yon)
        t_tahsilat = kurus_yuvarla(t_tahsilat, yon)
        t_kalan = kurus_yuvarla(t_kalan, yon)
        adet = len(satirlar)
        degerler = [""] * len(kolonlar)
        degerler[kolonlar.index("depo")] = f"{adet} satır"
        degerler[idx_toplam] = para_goster(t_toplam)
        degerler[idx_tahsilat] = para_goster(t_tahsilat)
        degerler[idx_kalan] = para_goster(t_kalan)
        for item in self.fatura_toplam_satiri.get_children():
            self.fatura_toplam_satiri.delete(item)
        self.fatura_toplam_satiri.insert("", "end", iid="toplam", values=tuple(degerler), tags=("toplam",))
        self._fatura_toplam_genislikleri_esitle()

    def _fatura_kolon_filtre_ac(self, kolon):
        if not hasattr(self, "fatura_tablosu"):
            return
        eski = getattr(self, "_fatura_filtre_popup", None)
        if eski is not None:
            try:
                if eski.winfo_exists():
                    eski.destroy()
            except tk.TclError:
                pass
        kolonlar = self._fatura_liste_kolonlar
        try:
            idx = kolonlar.index(kolon)
        except ValueError:
            return
        # Diğer kolon filtreleri uygulanmış satırlardan benzersiz değerler
        diger_filtre = {
            k: v for k, v in (self._fatura_liste_filtre or {}).items() if k != kolon and v is not None
        }
        onceki = self._fatura_liste_filtre
        self._fatura_liste_filtre = diger_filtre
        adaylar = self._fatura_filtreli_satirlar()
        self._fatura_liste_filtre = onceki
        kaynak = adaylar or getattr(self, "_fatura_liste_ham", [])
        degerler = set()
        for s in kaynak:
            vals = s["values"]
            degerler.add("" if idx >= len(vals) or vals[idx] is None else str(vals[idx]))

        mevcut = self._fatura_liste_filtre.get(kolon)
        baslik = self._fatura_liste_basliklar.get(kolon, kolon)
        pop = TreeviewKolonFiltrePopup(
            self,
            baslik,
            degerler,
            secili=mevcut,
            uygula_cb=lambda secilen, c=kolon: self._fatura_kolon_filtre_uygula(c, secilen),
            temizle_cb=lambda c=kolon: self._fatura_kolon_filtre_temizle(c),
        )
        try:
            x = self.fatura_tablosu.winfo_rootx() + 40
            y = self.fatura_tablosu.winfo_rooty() + 28
            pop.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        self._fatura_filtre_popup = pop

    def _fatura_kolon_filtre_uygula(self, kolon, secilen):
        try:
            idx = self._fatura_liste_kolonlar.index(kolon)
        except ValueError:
            return
        diger = {
            k: v for k, v in (self._fatura_liste_filtre or {}).items() if k != kolon and v is not None
        }
        onceki = self._fatura_liste_filtre
        self._fatura_liste_filtre = diger
        adaylar = self._fatura_filtreli_satirlar()
        self._fatura_liste_filtre = onceki
        tum = set()
        for s in adaylar or getattr(self, "_fatura_liste_ham", []):
            vals = s["values"]
            tum.add("" if idx >= len(vals) or vals[idx] is None else str(vals[idx]))
        if not secilen:
            self._fatura_liste_filtre[kolon] = set()
        elif tum and secilen >= tum:
            self._fatura_liste_filtre.pop(kolon, None)
        else:
            self._fatura_liste_filtre[kolon] = set(secilen)
        self._fatura_listeyi_goster()

    def _fatura_kolon_filtre_temizle(self, kolon):
        self._fatura_liste_filtre.pop(kolon, None)
        self._fatura_listeyi_goster()

    def _fatura_filtreleri_temizle(self):
        self._fatura_liste_filtre = {}
        for ad in ("fatura_tarih_bas", "fatura_tarih_bit", "fatura_vade_bas", "fatura_vade_bit"):
            w = getattr(self, ad, None)
            if w is None:
                continue
            try:
                w.delete(0, "end")
            except tk.TclError:
                pass
        self._fatura_listeyi_goster()

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

    def fatura_taslak_sil(self):
        fatura_id = self._secili_fatura_id()
        if fatura_id is None:
            return
        fatura = SatisFaturasiService.getir(fatura_id)
        if not fatura:
            return
        from silinen_kayitlar_ui import fatura_taslak_sil

        if fatura_taslak_sil(self, fatura):
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
        self._icerigi_temizle()
        from satis_tema import ekran_ust_cubugu, stil_uygula, tk_buton, treeview_stil

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "SATIŞ İRSALİYELERİ",
            alt_baslik="Sevk ve teslimat irsaliyelerini yönetin",
            geri_komut=lambda: satislar_hub_goster(self),
            geri_metin="← Satışlar",
        )
        cerceve = ttk.Frame(govde); cerceve.pack(fill="both", expand=True, pady=(4, 0))
        kolonlar = ("no", "tarih", "musteri_kodu", "musteri", "siparis", "toplam", "fatura", "kalan", "durum")
        basliklar = ("İrsaliye Numarası", "İrsaliye Tarihi", "Müşteri Kodu", "Müşteri Adı", "Sipariş Numarası", "Genel Toplam", "Faturalanan Tutar", "Kalan Faturalanabilir Tutar", "Durum")
        self.irsaliye_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.irsaliye_tablosu)
        for kolon, baslik in zip(kolonlar, basliklar): self.irsaliye_tablosu.heading(kolon, text=baslik); self.irsaliye_tablosu.column(kolon, width=140)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.irsaliye_tablosu.yview); yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.irsaliye_tablosu.xview); self.irsaliye_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set); self.irsaliye_tablosu.grid(row=0, column=0, sticky="nsew"); dikey.grid(row=0, column=1, sticky="ns"); yatay.grid(row=1, column=0, sticky="ew"); cerceve.rowconfigure(0, weight=1); cerceve.columnconfigure(0, weight=1)
        alt = ttk.Frame(govde); alt.pack(fill="x", pady=10)
        tk_buton(alt, "Yeni İrsaliye", self.yeni_irsaliye, rol="yeni").pack(side="left")
        tk_buton(alt, "İrsaliyeyi Aç / Düzenle", self.irsaliye_ac, rol="duzenle").pack(side="left", padx=8)
        tk_buton(alt, "Faturaya Çevir", self.irsaliye_faturaya_cevir, rol="kaydet").pack(side="left")
        tk_buton(alt, "İptal Et", self.irsaliye_iptal, rol="iptal").pack(side="left", padx=8)
        self.irsaliye_listesini_yenile()
        self.nav_sayfa_isaretle(self.satis_irsaliyeleri_goster)
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
        from satis_tema import ekran_ust_cubugu, stil_uygula, tk_buton, treeview_stil

        stil_uygula(root=self)
        govde = ekran_ust_cubugu(
            self,
            "ALINAN SİPARİŞLER",
            alt_baslik="Müşteri siparişlerini ve teslimat sürecini yönetin",
            geri_komut=lambda: satislar_hub_goster(self),
            geri_metin="← Satışlar",
        )
        cerceve = ttk.Frame(govde)
        cerceve.pack(fill="both", expand=True, pady=(4, 0))
        kolonlar = ("no", "siparis_tarihi", "termin", "musteri_kodu", "musteri", "toplam", "tahsilat", "kalan", "durum")
        basliklar = {"no": "Sipariş Numarası", "siparis_tarihi": "Sipariş Tarihi", "termin": "Termin Tarihi", "musteri_kodu": "Müşteri Kodu", "musteri": "Müşteri Adı", "toplam": "Sipariş Toplamı", "tahsilat": "Tahsil Edilen", "kalan": "Kalan Tahsilat", "durum": "Durum"}
        self.siparis_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.siparis_tablosu)
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
        alt = ttk.Frame(govde); alt.pack(fill="x", pady=10)
        tk_buton(alt, "Yeni Sipariş", self.yeni_siparis, rol="yeni").pack(side="left")
        tk_buton(alt, "Siparişi Aç / Düzenle", self.siparis_ac, rol="duzenle").pack(side="left", padx=8)
        tk_buton(alt, "İrsaliyeye Çevir", self.siparis_irsaliyeye_cevir, rol="kaydet").pack(side="left")
        tk_buton(alt, "Faturaya Çevir", self.siparis_faturaya_cevir, rol="kaydet").pack(side="left", padx=8)
        tk_buton(alt, "İptal Et", self.siparis_iptal, rol="iptal").pack(side="left")
        self.siparis_listesini_yenile()
        self.nav_sayfa_isaretle(self.satis_siparisleri_goster)
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
        from satis_tema import ekran_ust_cubugu, stil_uygula, tk_buton, treeview_stil

        stil_uygula(root=self)
        geri = (
            (lambda: self.sayfa_goster("satin_alma"))
            if tedarikci
            else (lambda: satislar_hub_goster(self))
        )
        govde = ekran_ust_cubugu(
            self,
            baslik,
            alt_baslik=f"{etiket} bilgileri, cari hareketler ve bakiye takibi",
            geri_komut=geri,
            geri_metin="← Satın Alma" if tedarikci else "← Satışlar",
        )
        ust = ttk.Frame(govde)
        ust.pack(fill="x", pady=(0, 10))
        ttk.Label(ust, text="Ara (en az 3 karakter):").pack(side="left")
        self.cari_arama = ttk.Entry(ust, width=30)
        self.cari_arama.pack(side="left", padx=8)
        self.cari_arama.bind("<Return>", lambda _event: self.cari_listesini_yenile())
        tk_buton(ust, "Ara", self.cari_listesini_yenile, rol="ara").pack(side="left")
        tk_buton(ust, "EvoBulut’tan Aktar", self.evobulut_cari_aktar, rol="duzenle").pack(
            side="right", padx=(0, 8)
        )
        tk_buton(ust, f"Yeni {etiket}", self.yeni_cari, rol="yeni").pack(side="right")

        cerceve = ttk.Frame(govde)
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("kod", "unvan", "grup", "telefon", "email", "bakiye", "agirlikli", "durum")
        basliklar = {
            "kod": f"{etiket} Kodu", "unvan": f"{etiket} Adı", "grup": f"{etiket} Grubu",
            "telefon": "Telefon", "email": "E-posta", "bakiye": "Yekûn Bakiye",
            "agirlikli": "Ağırlıklı Ortalama Geçen Gün", "durum": "Durum",
        }
        genislikler = {"kod": 110, "unvan": 210, "grup": 135, "telefon": 115, "email": 180, "bakiye": 125, "agirlikli": 180, "durum": 75}
        self.cari_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        treeview_stil(self.cari_tablosu)
        for kolon in kolonlar:
            self.cari_tablosu.heading(kolon, text=basliklar[kolon])
            self.cari_tablosu.column(kolon, width=genislikler[kolon], anchor="w")
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.cari_tablosu.yview)
        self.cari_tablosu.configure(yscrollcommand=kaydirma.set)
        self.cari_tablosu.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        self.cari_tablosu.bind("<Double-1>", lambda _event: self.cari_detay())

        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=(10, 0))
        tk_buton(alt, f"{etiket} Kartını Aç", self.cari_detay, rol="duzenle").pack(side="left")
        tk_buton(alt, "Düzenle", self.cari_duzenle, rol="kaydet").pack(side="left", padx=8)
        tk_buton(alt, "Pasife Al", self.cari_pasife_al, rol="ara").pack(side="left")
        tk_buton(alt, "Sil", self.cari_soft_sil, rol="iptal").pack(side="left", padx=8)
        self.cari_listesini_yenile()
        self.nav_sayfa_isaretle(lambda: self._cariler_goster(cari_turu=cari_turu))

    def cari_listesini_yenile(self):
        if not hasattr(self, "cari_tablosu"):
            return
        tur = getattr(self, "_cari_liste_turu", "Müşteri")
        arama = self.cari_arama.get()
        try:
            CariService._arama_kontrol(arama)
        except ValueError as hata:
            messagebox.showwarning("Arama", str(hata), parent=self)
            return
        for item in self.cari_tablosu.get_children():
            self.cari_tablosu.delete(item)
        token = getattr(self, "_cari_yenile_token", 0) + 1
        self._cari_yenile_token = token

        def _yukle():
            return CariService.listele(arama, cari_turu=tur, hizli=True)

        def _doldur(cariler):
            if getattr(self, "_cari_yenile_token", 0) != token:
                return
            if not hasattr(self, "cari_tablosu"):
                return
            for ozet in cariler:
                cari = ozet["cari"]
                self.cari_tablosu.insert(
                    "",
                    "end",
                    iid=str(cari.id),
                    values=(
                        cari.cari_kodu,
                        cari.unvan,
                        cari.musteri_grubu or "",
                        cari.telefon or "",
                        cari.email or "",
                        para_goster(ozet["bakiye"]),
                        f"{ozet['agirlikli_ortalama_gun']:.1f}",
                        "Aktif" if cari.aktif else "Pasif",
                    ),
                )

        def _hata(exc):
            if getattr(self, "_cari_yenile_token", 0) != token:
                return
            messagebox.showerror("Cari listesi", str(exc), parent=self)

        arka_planda(self, _yukle, on_ok=_doldur, on_err=_hata)

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

    def evobulut_cari_aktar(self):
        from evobulut_cari_ui import EvobulutCariAktarDialog

        tur = getattr(self, "_cari_liste_turu", "Müşteri")
        dialog = EvobulutCariAktarDialog(self, varsayilan_tur=tur)
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

    def cari_soft_sil(self):
        cari = self._secili_cari()
        if not cari:
            return
        from silinen_kayitlar_ui import cari_soft_sil

        if cari_soft_sil(self, cari):
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
            self._alt_menu_dugme(
                alt, baslik, komut,
                row=satir, column=0, sticky="ew", pady=4,
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
            ("tarih", "tur", "belge", "aciklama", "pb", "doviz", "kur", "borc", "alacak", "bakiye", "gun"),
            ("Tarih", "Tür", "Belge No", "Açıklama", "PB", "Döviz", "Kur", "Borç", "Alacak", "Bakiye", "Gün"),
            (85, 95, 120, 150, 40, 85, 75, 100, 100, 110, 55),
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

        def evobulut_aktar():
            from evobulut_alis_fatura_ui import EvobulutAlisFaturaAktarDialog

            dialog = EvobulutAlisFaturaAktarDialog(self)
            self.wait_window(dialog)
            if dialog.result:
                yenile()

        ttk.Button(alt, text="EvoBulut’tan Aktar", command=evobulut_aktar).pack(
            side="left", padx=8
        )
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
