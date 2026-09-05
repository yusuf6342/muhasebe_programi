"""Satın alma belge diyalogları (satış UI kalıplarının alış karşılığı)."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.alis_faturasi_service import AlisFaturasiService
from database.alis_iade_faturasi_service import AlisIadeFaturasiService
from database.alis_irsaliyesi_service import AlisIrsaliyesiService
from database.alis_siparisi_service import ODEME_SEKILLERI, AlisSiparisiService
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from product_provider import search_prices, search_products

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


def _tedarikci_ekle(tedarikci_map: dict, cari) -> str | None:
    """Pasif/eksik tedarikçiyi haritaya ekler; combobox anahtarını döner."""
    if not cari:
        return None
    anahtar = f"{cari.cari_kodu} - {cari.unvan}"
    if anahtar not in tedarikci_map:
        tedarikci_map[anahtar] = cari
    return anahtar


class _UrunSecDialog(tk.Toplevel):
    def __init__(self, parent, query, on_select):
        super().__init__(parent)
        self.title("Ürün Seçimi")
        self.geometry("780x360")
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        ttk.Label(self, text=f"Ürün arama: {query}").pack(anchor="w", padx=12, pady=(12, 6))
        kolonlar = ("kod", "ad", "birim", "stok", "fiyat", "kaynak")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (
            ("kod", "Ürün Kodu", 120), ("ad", "Ürün Adı", 220), ("birim", "Birim", 80),
            ("stok", "Mevcut Stok", 110), ("fiyat", "Fiyat", 120), ("kaynak", "Kaynak", 110),
        ):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik)
        self.tablo.pack(fill="both", expand=True, padx=12, pady=6)
        for sira, urun in enumerate(search_products(query)):
            self.tablo.insert("", "end", iid=str(sira), values=(
                urun.code, urun.name, urun.unit, urun.stock, urun.default_price, urun.source,
            ))
        self.tablo.bind("<Double-1>", lambda _e: self.sec())
        ttk.Button(self, text="Seç", command=self.sec).pack(anchor="e", padx=12, pady=8)

    def sec(self):
        secim = self.tablo.selection()
        if not secim:
            return
        self.on_select(self.tablo.item(secim[0], "values"))
        self.destroy()


class AlisSiparisSatiriDialog(tk.Toplevel):
    def __init__(self, parent, satir=None):
        super().__init__(parent)
        self.result = None
        self.title("Satın Alma Sipariş Satırı")
        self.geometry("520x360")
        self.transient(parent)
        self.grab_set()
        self.girdiler = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        alanlar = (
            ("Ürün Kodu", "urun_kodu"), ("Ürün Adı", "urun_adi"), ("Açıklama", "aciklama"),
            ("Miktar", "miktar"), ("Birim", "birim"), ("Birim Alış Fiyatı", "birim_alis_fiyati"),
            ("İskonto %", "iskonto_orani"), ("KDV %", "kdv_orani"),
        )
        for sira, (etiket, alan) in enumerate(alanlar):
            ttk.Label(frame, text=etiket).grid(row=sira, column=0, sticky="w", pady=4)
            if alan == "birim":
                w = ttk.Combobox(frame, values=BIRIM_SECENEKLERI, width=28)
                w.set((satir or {}).get(alan) or "Adet")
            else:
                w = ttk.Entry(frame, width=30)
                if satir and satir.get(alan) is not None:
                    w.insert(0, str(satir.get(alan)))
                elif alan == "kdv_orani":
                    w.insert(0, "20")
                elif alan == "iskonto_orani":
                    w.insert(0, "0")
            w.grid(row=sira, column=1, sticky="ew", pady=4, padx=6)
            self.girdiler[alan] = w
        self.girdiler["urun_kodu"].bind("<Return>", self._urun_ara)
        alt = ttk.Frame(frame)
        alt.grid(row=len(alanlar), column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=8)

    def _urun_ara(self, _event=None):
        q = self.girdiler["urun_kodu"].get().strip()
        if len(q) < 2:
            return

        def sec(degerler):
            self.girdiler["urun_kodu"].delete(0, "end")
            self.girdiler["urun_kodu"].insert(0, degerler[0])
            self.girdiler["urun_adi"].delete(0, "end")
            self.girdiler["urun_adi"].insert(0, degerler[1])
            self.girdiler["birim"].set(degerler[2] or "Adet")
            if degerler[4]:
                self.girdiler["birim_alis_fiyati"].delete(0, "end")
                self.girdiler["birim_alis_fiyati"].insert(0, degerler[4])

        dialog = _UrunSecDialog(self, q, sec)
        self.wait_window(dialog)

    def tamam(self):
        try:
            veri = {a: w.get().strip() for a, w in self.girdiler.items()}
            if not veri["urun_kodu"] or not veri["urun_adi"]:
                raise ValueError("Ürün kodu ve adı zorunlu.")
            veri["miktar"] = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
            veri["birim_alis_fiyati"] = decimal(veri["birim_alis_fiyati"], "Birim alış", Decimal("0"))
            veri["iskonto_orani"] = decimal(veri.get("iskonto_orani") or 0, "İskonto", Decimal("0"))
            veri["kdv_orani"] = decimal(veri.get("kdv_orani") or 20, "KDV", Decimal("0"))
            veri["birim"] = veri["birim"] or "Adet"
            self.result = veri
            self.destroy()
        except ValueError as hata:
            messagebox.showerror("Satır", str(hata), parent=self)


class AlisSiparisOdemeDialog(tk.Toplevel):
    def __init__(self, parent, odeme=None):
        super().__init__(parent)
        self.result = None
        self.title("Ödeme")
        self.geometry("420x260")
        self.transient(parent)
        self.grab_set()
        self.girdiler = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        for sira, (etiket, alan) in enumerate((
            ("Ödeme Tarihi", "odeme_tarihi"), ("Tutar", "tutar"),
            ("Ödeme Şekli", "odeme_sekli"), ("Hesap", "hesap"), ("Açıklama", "aciklama"),
        )):
            ttk.Label(frame, text=etiket).grid(row=sira, column=0, sticky="w", pady=4)
            if alan == "odeme_sekli":
                w = ttk.Combobox(frame, values=ODEME_SEKILLERI, state="readonly", width=28)
                w.set((odeme or {}).get(alan) or ODEME_SEKILLERI[0])
            else:
                w = ttk.Entry(frame, width=30)
                if odeme and odeme.get(alan) is not None:
                    deger = odeme[alan]
                    w.insert(0, deger.strftime("%d.%m.%Y") if hasattr(deger, "strftime") else str(deger))
                elif alan == "odeme_tarihi":
                    w.insert(0, date.today().strftime("%d.%m.%Y"))
            w.grid(row=sira, column=1, padx=6, pady=4)
            self.girdiler[alan] = w
        alt = ttk.Frame(frame)
        alt.grid(row=6, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=8)

    def tamam(self):
        try:
            veri = {a: w.get().strip() for a, w in self.girdiler.items()}
            veri["odeme_tarihi"] = datetime.strptime(veri["odeme_tarihi"], "%d.%m.%Y").date()
            veri["tutar"] = decimal(veri["tutar"], "Tutar", Decimal("0.01"))
            self.result = veri
            self.destroy()
        except ValueError as hata:
            messagebox.showerror("Ödeme", str(hata), parent=self)


class AlisSiparisiDialog(tk.Toplevel):
    def __init__(self, parent, siparis=None, cari=None):
        super().__init__(parent)
        self.siparis = siparis
        self.result = None
        self.title("SATIN ALMA SİPARİŞİ")
        self.geometry("1100x700")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.odemeler = []
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        if siparis and siparis.cari and siparis.cari not in tedarikciler:
            tedarikciler.append(siparis.cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.tedarikci = tk.StringVar()
        ust = ttk.LabelFrame(self, text="Sipariş Bilgileri", padding=10)
        ust.pack(fill="x", padx=10, pady=8)
        self.girdiler = {}
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40).grid(
            row=0, column=1, sticky="w", padx=6, pady=3
        )
        for sira, (etiket, alan, varsayilan) in enumerate((
            ("Sipariş Tarihi", "siparis_tarihi", date.today().strftime("%d.%m.%Y")),
            ("Termin Tarihi", "termin_tarihi", date.today().strftime("%d.%m.%Y")),
            ("Açıklama", "aciklama", ""),
        ), start=1):
            ttk.Label(ust, text=etiket).grid(row=sira, column=0, sticky="w")
            e = ttk.Entry(ust, width=42)
            e.insert(0, varsayilan)
            e.grid(row=sira, column=1, sticky="w", padx=6, pady=3)
            self.girdiler[alan] = e

        orta = ttk.LabelFrame(self, text="Satırlar", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=4)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv"),
            show="headings", height=10,
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 200), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Alış Fiyatı", 100), ("isk", "İsk%", 60), ("kdv", "KDV%", 60),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        satir_btn = ttk.Frame(orta)
        satir_btn.pack(fill="x", pady=4)
        ttk.Button(satir_btn, text="Satır Ekle", command=self.satir_ekle).pack(side="left")
        ttk.Button(satir_btn, text="Satır Düzenle", command=self.satir_duzenle).pack(side="left", padx=6)
        ttk.Button(satir_btn, text="Satır Sil", command=self.satir_sil).pack(side="left")

        odeme_cerceve = ttk.LabelFrame(self, text="Ödemeler", padding=8)
        odeme_cerceve.pack(fill="x", padx=10, pady=4)
        self.odeme_tablosu = ttk.Treeview(
            odeme_cerceve, columns=("tarih", "tutar", "sekil", "hesap"), show="headings", height=4,
        )
        for kolon, baslik in (("tarih", "Tarih"), ("tutar", "Tutar"), ("sekil", "Şekil"), ("hesap", "Hesap")):
            self.odeme_tablosu.heading(kolon, text=baslik)
            self.odeme_tablosu.column(kolon, width=120)
        self.odeme_tablosu.pack(fill="x")
        odeme_btn = ttk.Frame(odeme_cerceve)
        odeme_btn.pack(fill="x", pady=4)
        ttk.Button(odeme_btn, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(odeme_btn, text="Ödeme Sil", command=self.odeme_sil).pack(side="left", padx=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if siparis:
            self._doldur()
        elif cari:
            anahtar = f"{cari.cari_kodu} - {cari.unvan}"
            if anahtar in self.tedarikci_map:
                self.tedarikci.set(anahtar)

    def _satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"],
                para_goster(s["birim_alis_fiyati"]), s.get("iskonto_orani", 0), s.get("kdv_orani", 20),
            ))

    def _odeme_listesini_yenile(self):
        for item in self.odeme_tablosu.get_children():
            self.odeme_tablosu.delete(item)
        for sira, o in enumerate(self.odemeler):
            self.odeme_tablosu.insert("", "end", iid=str(sira), values=(
                tarih_goster(o["odeme_tarihi"]), para_goster(o["tutar"]),
                o["odeme_sekli"], o.get("hesap") or "",
            ))

    def satir_ekle(self):
        dialog = AlisSiparisSatiriDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.satirlar.append(dialog.result)
            self._satir_listesini_yenile()

    def satir_duzenle(self):
        secim = self.satir_tablosu.selection()
        if not secim:
            return
        idx = int(secim[0])
        dialog = AlisSiparisSatiriDialog(self, self.satirlar[idx])
        self.wait_window(dialog)
        if dialog.result:
            self.satirlar[idx] = dialog.result
            self._satir_listesini_yenile()

    def satir_sil(self):
        secim = self.satir_tablosu.selection()
        if secim and messagebox.askyesno("Sil", "Satır silinsin mi?", parent=self):
            self.satirlar.pop(int(secim[0]))
            self._satir_listesini_yenile()

    def odeme_ekle(self):
        dialog = AlisSiparisOdemeDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler.append(dialog.result)
            self._odeme_listesini_yenile()

    def odeme_sil(self):
        secim = self.odeme_tablosu.selection()
        if secim:
            self.odemeler.pop(int(secim[0]))
            self._odeme_listesini_yenile()

    def _doldur(self):
        s = self.siparis
        self.tedarikci.set(f"{s.cari.cari_kodu} - {s.cari.unvan}")
        self.girdiler["siparis_tarihi"].delete(0, "end")
        self.girdiler["siparis_tarihi"].insert(0, tarih_goster(s.siparis_tarihi))
        self.girdiler["termin_tarihi"].delete(0, "end")
        self.girdiler["termin_tarihi"].insert(0, tarih_goster(s.termin_tarihi))
        self.girdiler["aciklama"].insert(0, s.aciklama or "")
        for satir in s.satirlar:
            self.satirlar.append({
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "aciklama": satir.aciklama or "", "miktar": satir.miktar, "birim": satir.birim,
                "birim_alis_fiyati": satir.birim_alis_fiyati,
                "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani,
                "irsaliyelenen_miktar": satir.irsaliyelenen_miktar,
                "faturalanan_miktar": satir.faturalanan_miktar,
            })
        for odeme in s.odemeler:
            self.odemeler.append({
                "odeme_tarihi": odeme.odeme_tarihi, "tutar": odeme.tutar,
                "odeme_sekli": odeme.odeme_sekli, "hesap": odeme.hesap or "",
                "aciklama": odeme.aciklama or "",
            })
        self._satir_listesini_yenile()
        self._odeme_listesini_yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showwarning("Eksik", "Tedarikçi seçin.", parent=self)
            return
        if not self.satirlar:
            messagebox.showwarning("Eksik", "En az bir satır ekleyin.", parent=self)
            return
        try:
            veriler = {
                "siparis_tarihi": datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date(),
                "termin_tarihi": datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "aciklama": self.girdiler["aciklama"].get().strip() or None,
            }
            AlisSiparisiService.kaydet(
                veriler, self.satirlar, self.odemeler,
                self.siparis.id if self.siparis else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class AlisIrsaliyesiDialog(tk.Toplevel):
    def __init__(self, parent, irsaliye=None, siparis=None, cari=None):
        super().__init__(parent)
        self.irsaliye = irsaliye
        self.result = None
        self.title("SATIN ALMA İRSALİYESİ")
        self.geometry("1000x620")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        tedarikciler = list(AlisIrsaliyesiService.aktif_tedarikcileri())
        for belge in (irsaliye, siparis):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        acik_siparisler = list(AlisIrsaliyesiService.acik_siparisler())
        if siparis and siparis.siparis_no not in {s.siparis_no for s in acik_siparisler}:
            acik_siparisler.append(siparis)
        if irsaliye and irsaliye.siparis and irsaliye.siparis.siparis_no not in {s.siparis_no for s in acik_siparisler}:
            acik_siparisler.append(irsaliye.siparis)
        self.siparis_map = {s.siparis_no: s for s in acik_siparisler}
        self.tedarikci = tk.StringVar()
        self.siparis_secimi = tk.StringVar()
        ust = ttk.LabelFrame(self, text="İrsaliye", padding=10)
        ust.pack(fill="x", padx=10, pady=8)
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.tedarikci_combo = ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40)
        self.tedarikci_combo.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Sipariş").grid(row=1, column=0, sticky="w")
        self.siparis_combo = ttk.Combobox(
            ust, textvariable=self.siparis_secimi, values=list(self.siparis_map), width=40,
        )
        self.siparis_combo.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(ust, text="Siparişten Doldur", command=self.siparisten_doldur).grid(row=1, column=2, padx=6)
        self.tarih = ttk.Entry(ust, width=18)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="Tarih").grid(row=2, column=0, sticky="w")
        self.tarih.grid(row=2, column=1, sticky="w", padx=6)
        self.aciklama = ttk.Entry(ust, width=42)
        ttk.Label(ust, text="Açıklama").grid(row=3, column=0, sticky="w")
        self.aciklama.grid(row=3, column=1, sticky="w", padx=6)

        orta = ttk.LabelFrame(self, text="Satırlar", padding=8)
        orta.pack(fill="both", expand=True, padx=10)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat"), show="headings",
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 220), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Fiyat", 100),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        btn = ttk.Frame(orta)
        btn.pack(fill="x", pady=4)
        ttk.Button(btn, text="Satır Ekle", command=self.satir_ekle).pack(side="left")
        ttk.Button(btn, text="Satır Sil", command=self.satir_sil).pack(side="left", padx=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if irsaliye:
            self._doldur()
        elif siparis:
            self.siparis_secimi.set(siparis.siparis_no)
            self.siparisten_doldur()
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)

    def _yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"], para_goster(s["birim_fiyat"]),
            ))

    def _siparis_coz(self):
        no = self.siparis_secimi.get().strip()
        if not no:
            return None
        siparis = self.siparis_map.get(no)
        if siparis:
            return siparis
        siparis = next(
            (s for s in AlisIrsaliyesiService.acik_siparisler() if s.siparis_no == no),
            None,
        )
        if siparis:
            self.siparis_map[siparis.siparis_no] = siparis
            self.siparis_combo["values"] = list(self.siparis_map)
        return siparis

    def siparisten_doldur(self):
        siparis = self._siparis_coz()
        if not siparis:
            return
        anahtar = _tedarikci_ekle(self.tedarikci_map, siparis.cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.irsaliyelenen_miktar
            if acik > 0:
                self.satirlar.append({
                    "siparis_satiri_id": satir.id,
                    "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                    "aciklama": satir.aciklama or "", "miktar": acik, "birim": satir.birim,
                    "birim_fiyat": satir.birim_alis_fiyati,
                    "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani,
                })
        self._yenile()

    def satir_ekle(self):
        dialog = AlisSiparisSatiriDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            r = dialog.result
            self.satirlar.append({
                **r,
                "birim_fiyat": r["birim_alis_fiyati"],
            })
            self._yenile()

    def satir_sil(self):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satirlar.pop(int(secim[0]))
            self._yenile()

    def _doldur(self):
        i = self.irsaliye
        anahtar = _tedarikci_ekle(self.tedarikci_map, i.cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)
        self.tarih.delete(0, "end")
        self.tarih.insert(0, tarih_goster(i.irsaliye_tarihi))
        self.aciklama.insert(0, i.aciklama or "")
        if i.siparis:
            self.siparis_map[i.siparis.siparis_no] = i.siparis
            self.siparis_combo["values"] = list(self.siparis_map)
            self.siparis_secimi.set(i.siparis.siparis_no)
        for satir in i.satirlar:
            self.satirlar.append({
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "aciklama": satir.aciklama or "", "miktar": satir.miktar, "birim": satir.birim,
                "birim_fiyat": satir.birim_fiyat, "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
            })
        self._yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showwarning("Eksik", "Tedarikçi seçin.", parent=self)
            return
        siparis = self._siparis_coz()
        siparis_id = siparis.id if siparis else (self.irsaliye.siparis_id if self.irsaliye else None)
        try:
            AlisIrsaliyesiService.kaydet(
                {
                    "irsaliye_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                    "cari_id": tedarikci.id,
                    "siparis_id": siparis_id,
                    "aciklama": self.aciklama.get().strip() or None,
                    "ayrintili_notlar": None,
                },
                self.satirlar,
                self.irsaliye.id if self.irsaliye else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class AlisFaturasiDialog(tk.Toplevel):
    def __init__(self, parent, fatura=None, siparis=None, irsaliye=None, cari=None, cari_ac=None):
        super().__init__(parent)
        self.fatura = fatura
        self.cari_ac = cari_ac
        self.result = None
        self.title("SATIN ALMA FATURASI")
        self.geometry("1100x720")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self._siparis_id = None
        self._irsaliye_id = None
        tedarikciler = list(AlisFaturasiService.aktif_tedarikcileri())
        for belge in (fatura, siparis, irsaliye):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.depolar = [d.ad for d in StokService.depolar()] or ["ANA DEPO"]
        self.tedarikci = tk.StringVar()
        self.depo = tk.StringVar(value=self.depolar[0])
        ust = ttk.LabelFrame(self, text="Fatura Bilgileri", padding=10)
        ust.pack(fill="x", padx=10, pady=8)
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.tedarikci_combo = ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40)
        self.tedarikci_combo.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Depo").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Combobox(ust, textvariable=self.depo, values=self.depolar, width=18).grid(row=0, column=3, padx=6)
        self.girdiler = {}
        for sira, (etiket, alan, deger) in enumerate((
            ("Fatura Tarihi", "fatura_tarihi", date.today().strftime("%d.%m.%Y")),
            ("Vade Tarihi", "vade_tarihi", date.today().strftime("%d.%m.%Y")),
            ("Ödeme Tutarı", "odeme_tutari", "0"),
            ("Ödeme Şekli", "odeme_sekli", AlisFaturasiService and "KASA ÖDEME"),
            ("Ödeme Hesabı", "odeme_hesabi", ""),
            ("Açıklama", "aciklama", ""),
        ), start=1):
            ttk.Label(ust, text=etiket).grid(row=sira, column=0, sticky="w")
            if alan == "odeme_sekli":
                from database.alis_faturasi_service import ODEME_SEKILLERI as FAT_ODEME
                e = ttk.Combobox(ust, values=FAT_ODEME, width=40)
                e.set(FAT_ODEME[0])
            else:
                e = ttk.Entry(ust, width=42)
                e.insert(0, deger)
            e.grid(row=sira, column=1, columnspan=3, sticky="w", padx=6, pady=2)
            self.girdiler[alan] = e

        orta = ttk.LabelFrame(self, text="Satırlar (stok girişi fatura kaydında yapılır)", padding=8)
        orta.pack(fill="both", expand=True, padx=10)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat", "lot"), show="headings",
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 200), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Alış Fiyatı", 100), ("lot", "Lot", 100),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        btn = ttk.Frame(orta)
        btn.pack(fill="x", pady=4)
        ttk.Button(btn, text="Satır Ekle", command=self.satir_ekle).pack(side="left")
        ttk.Button(btn, text="Satır Sil", command=self.satir_sil).pack(side="left", padx=6)
        ttk.Button(btn, text="Siparişten Doldur", command=self.siparisten).pack(side="left", padx=6)
        ttk.Button(btn, text="İrsaliyeden Doldur", command=self.irsaliyeden).pack(side="left")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if fatura:
            self._doldur()
        elif siparis:
            self._siparis_yukle(siparis)
        elif irsaliye:
            self._irsaliye_yukle(irsaliye)
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)

    def _yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"],
                para_goster(s["birim_fiyat"]), s.get("lot_no") or "",
            ))

    def _tedarikci_sec(self, cari):
        anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)

    def satir_ekle(self):
        dialog = AlisSiparisSatiriDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            r = dialog.result
            self.satirlar.append({
                "urun_kodu": r["urun_kodu"], "urun_adi": r["urun_adi"],
                "aciklama": r.get("aciklama") or "", "miktar": r["miktar"], "birim": r["birim"],
                "birim_fiyat": r["birim_alis_fiyati"],
                "iskonto_orani": r.get("iskonto_orani", 0), "kdv_orani": r.get("kdv_orani", 20),
                "lot_no": "",
            })
            self._yenile()

    def satir_sil(self):
        secim = self.satir_tablosu.selection()
        if secim:
            self.satirlar.pop(int(secim[0]))
            self._yenile()

    def _siparis_yukle(self, siparis):
        self._tedarikci_sec(siparis.cari)
        self._siparis_id = siparis.id
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.faturalanan_miktar
            if acik > 0:
                self.satirlar.append({
                    "siparis_satiri_id": satir.id,
                    "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                    "miktar": acik, "birim": satir.birim, "birim_fiyat": satir.birim_alis_fiyati,
                    "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani, "lot_no": "",
                })
        self._yenile()

    def _irsaliye_yukle(self, irsaliye):
        self._tedarikci_sec(irsaliye.cari)
        self._irsaliye_id = irsaliye.id
        self._siparis_id = irsaliye.siparis_id
        self.satirlar.clear()
        for satir in irsaliye.satirlar:
            acik = satir.miktar - satir.faturalanan_miktar
            if acik > 0:
                self.satirlar.append({
                    "irsaliye_satiri_id": satir.id, "siparis_satiri_id": satir.siparis_satiri_id,
                    "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                    "miktar": acik, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                    "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani, "lot_no": "",
                })
        self._yenile()

    def siparisten(self):
        acik = AlisFaturasiService.acik_siparisler()
        if not acik:
            messagebox.showinfo("Sipariş", "Açık sipariş yok.", parent=self)
            return
        sec = _ListeSecDialog(self, "Sipariş seç", [f"{s.siparis_no} - {s.cari.unvan}" for s in acik])
        self.wait_window(sec)
        if sec.result is not None:
            self._siparis_yukle(acik[sec.result])

    def irsaliyeden(self):
        acik = AlisFaturasiService.acik_irsaliyeler()
        if not acik:
            messagebox.showinfo("İrsaliye", "Açık irsaliye yok.", parent=self)
            return
        sec = _ListeSecDialog(self, "İrsaliye seç", [f"{i.irsaliye_no} - {i.cari.unvan}" for i in acik])
        self.wait_window(sec)
        if sec.result is not None:
            self._irsaliye_yukle(acik[sec.result])

    def _doldur(self):
        f = self.fatura
        self._tedarikci_sec(f.cari)
        self.depo.set(f.depo or self.depolar[0])
        self.girdiler["fatura_tarihi"].delete(0, "end")
        self.girdiler["fatura_tarihi"].insert(0, tarih_goster(f.fatura_tarihi))
        self.girdiler["vade_tarihi"].delete(0, "end")
        self.girdiler["vade_tarihi"].insert(0, tarih_goster(f.vade_tarihi))
        self.girdiler["odeme_tutari"].delete(0, "end")
        self.girdiler["odeme_tutari"].insert(0, str(f.odeme_tutari or 0))
        if f.odeme_sekli:
            self.girdiler["odeme_sekli"].set(f.odeme_sekli)
        self.girdiler["odeme_hesabi"].insert(0, f.odeme_hesabi or "")
        self.girdiler["aciklama"].insert(0, f.aciklama or "")
        self._siparis_id = f.siparis_id
        self._irsaliye_id = f.irsaliye_id
        for satir in f.satirlar:
            self.satirlar.append({
                "siparis_satiri_id": satir.siparis_satiri_id,
                "irsaliye_satiri_id": satir.irsaliye_satiri_id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani,
                "lot_no": satir.lot_no or "",
            })
        self._yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showwarning("Eksik", "Tedarikçi seçin.", parent=self)
            return
        if not self.satirlar:
            messagebox.showwarning("Eksik", "Satır ekleyin.", parent=self)
            return
        try:
            veriler = {
                "fatura_tarihi": datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date(),
                "vade_tarihi": datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "siparis_id": getattr(self, "_siparis_id", None),
                "irsaliye_id": getattr(self, "_irsaliye_id", None),
                "depo": self.depo.get(),
                "odeme_tutari": self.girdiler["odeme_tutari"].get(),
                "odeme_sekli": self.girdiler["odeme_sekli"].get(),
                "odeme_hesabi": self.girdiler["odeme_hesabi"].get().strip() or None,
                "aciklama": self.girdiler["aciklama"].get().strip() or None,
            }
            AlisFaturasiService.kaydet(veriler, self.satirlar, self.fatura.id if self.fatura else None)
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class _ListeSecDialog(tk.Toplevel):
    def __init__(self, parent, baslik, etiketler):
        super().__init__(parent)
        self.result = None
        self.title(baslik)
        self.geometry("480x320")
        self.transient(parent)
        self.grab_set()
        self.liste = tk.Listbox(self)
        self.liste.pack(fill="both", expand=True, padx=10, pady=10)
        for e in etiketler:
            self.liste.insert("end", e)
        ttk.Button(self, text="Seç", command=self.sec).pack(pady=8)

    def sec(self):
        secim = self.liste.curselection()
        if secim:
            self.result = secim[0]
            self.destroy()


class AlisIadeFaturasiDialog(tk.Toplevel):
    def __init__(self, parent, iade=None, kaynak_fatura=None):
        super().__init__(parent)
        self.iade = iade
        self.result = None
        self.title("SATIN ALMA İADE FATURASI")
        self.geometry("980x640")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.kaynak = kaynak_fatura
        from database.alis_faturasi_service import ODEME_SEKILLERI as FAT_ODEME
        tedarikciler = list(AlisIadeFaturasiService.aktif_tedarikcileri())
        for belge in (iade, kaynak_fatura):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.depolar = [d.ad for d in StokService.depolar()] or ["ANA DEPO"]
        self.tedarikci = tk.StringVar()
        self.depo = tk.StringVar(value=self.depolar[0])
        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.tedarikci_combo = ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40)
        self.tedarikci_combo.grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(ust, text="Depo").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Combobox(ust, textvariable=self.depo, values=self.depolar, width=18).grid(row=0, column=3, padx=6)
        self.tarih = ttk.Entry(ust, width=16)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="İade Tarihi").grid(row=1, column=0, sticky="w")
        self.tarih.grid(row=1, column=1, sticky="w", padx=6)
        self.aciklama = ttk.Entry(ust, width=42)
        ttk.Label(ust, text="Açıklama").grid(row=2, column=0, sticky="w")
        self.aciklama.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Kaynak Fatura").grid(row=3, column=0, sticky="w")
        self.kaynak_lbl = ttk.Label(ust, text=kaynak_fatura.fatura_no if kaynak_fatura else "-")
        self.kaynak_lbl.grid(row=3, column=1, sticky="w", padx=6)
        ttk.Button(ust, text="Kaynak Fatura Seç", command=self.kaynak_sec).grid(row=3, column=2, padx=6)
        ttk.Label(ust, text="İade Ödeme").grid(row=4, column=0, sticky="w")
        self.iade_odeme_tutari = ttk.Entry(ust, width=16)
        self.iade_odeme_tutari.insert(0, "0")
        self.iade_odeme_tutari.grid(row=4, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Ödeme Şekli").grid(row=5, column=0, sticky="w")
        self.iade_odeme_sekli = ttk.Combobox(ust, values=FAT_ODEME, width=40)
        self.iade_odeme_sekli.set(FAT_ODEME[0])
        self.iade_odeme_sekli.grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Ödeme Hesabı").grid(row=6, column=0, sticky="w")
        self.iade_odeme_hesabi = ttk.Entry(ust, width=42)
        self.iade_odeme_hesabi.grid(row=6, column=1, sticky="w", padx=6)

        orta = ttk.LabelFrame(self, text="İade Satırları", padding=8)
        orta.pack(fill="both", expand=True, padx=10)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "fiyat"), show="headings",
        )
        for kolon, baslik, w in (("kod", "Kod", 100), ("ad", "Ad", 220), ("miktar", "Miktar", 80), ("fiyat", "Fiyat", 100)):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if kaynak_fatura:
            self._kaynaktan_doldur(kaynak_fatura)
        elif iade:
            self._doldur()

    def kaynak_sec(self):
        faturalar = [k["fatura"] for k in AlisFaturasiService.listele() if k["fatura"].durum != "İPTAL"]
        if not faturalar:
            messagebox.showinfo("Fatura", "Alış faturası yok.", parent=self)
            return
        sec = _ListeSecDialog(self, "Kaynak fatura", [f"{f.fatura_no} - {f.cari.unvan}" for f in faturalar])
        self.wait_window(sec)
        if sec.result is not None:
            self._kaynaktan_doldur(faturalar[sec.result])

    def _tedarikci_sec(self, cari):
        anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)

    def _satirlari_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], para_goster(s["birim_fiyat"]),
            ))

    def _kaynaktan_doldur(self, fatura):
        self.kaynak = fatura
        self.kaynak_lbl.configure(text=fatura.fatura_no)
        self._tedarikci_sec(fatura.cari)
        if fatura.depo:
            self.depo.set(fatura.depo)
        self.satirlar = []
        for satir in fatura.satirlar:
            self.satirlar.append({
                "kaynak_fatura_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani,
            })
        self._satirlari_yenile()

    def _doldur(self):
        i = self.iade
        self._tedarikci_sec(i.cari)
        self.tarih.delete(0, "end")
        self.tarih.insert(0, tarih_goster(i.iade_tarihi))
        self.aciklama.insert(0, i.aciklama or "")
        self.depo.set(i.depo or self.depolar[0])
        self.iade_odeme_tutari.delete(0, "end")
        self.iade_odeme_tutari.insert(0, str(i.iade_odeme_tutari or 0))
        if i.iade_odeme_sekli:
            self.iade_odeme_sekli.set(i.iade_odeme_sekli)
        self.iade_odeme_hesabi.insert(0, i.iade_odeme_hesabi or "")
        if i.kaynak_fatura:
            self.kaynak = i.kaynak_fatura
            self.kaynak_lbl.configure(text=i.kaynak_fatura.fatura_no)
        for satir in i.satirlar:
            self.satirlar.append({
                "kaynak_fatura_satiri_id": satir.kaynak_fatura_satiri_id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani, "kdv_orani": satir.kdv_orani,
            })
        self._satirlari_yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci or not self.satirlar:
            messagebox.showwarning("Eksik", "Tedarikçi ve satırlar gerekli.", parent=self)
            return
        try:
            AlisIadeFaturasiService.kaydet(
                {
                    "iade_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                    "cari_id": tedarikci.id,
                    "kaynak_fatura_id": self.kaynak.id if self.kaynak else None,
                    "depo": self.depo.get() or "ANA DEPO",
                    "aciklama": self.aciklama.get().strip() or None,
                    "iade_odeme_tutari": self.iade_odeme_tutari.get(),
                    "iade_odeme_sekli": self.iade_odeme_sekli.get() or None,
                    "iade_odeme_hesabi": self.iade_odeme_hesabi.get().strip() or None,
                },
                self.satirlar,
                self.iade.id if self.iade else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()
