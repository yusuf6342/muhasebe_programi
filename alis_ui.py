"""Satın alma belge diyalogları (satış UI kalıplarının alış karşılığı)."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.alis_faturasi_service import ODEME_SEKILLERI, AlisFaturasiService
from database.alis_iade_faturasi_service import AlisIadeFaturasiService
from database.alis_irsaliyesi_service import AlisIrsaliyesiService
from database.alis_siparisi_service import AlisSiparisiService
from database.fatura_kdv_service import kdv_oran_metni, satir_kdv_metin
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from doviz_fatura_panel import (
    doviz_ozet_guncelle,
    doviz_paneli_kur,
    doviz_satir_kaydet_oncesi,
    doviz_verilerini_doldur,
    doviz_verilerini_topla,
)
from product_provider import search_prices, search_products
from ui_takvim import saat_dogrula, saat_varsayilan, tarih_alani
from urun_sec_ui import UrunSecDialog

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
                    w.insert(0, satir_kdv_metin())
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

        dialog = UrunSecDialog(self, kod=q, on_select=sec)
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
        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=420, yukseklik=260)
        except Exception:
            pass
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
                "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
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
                "row_version": int(getattr(self.siparis, "row_version", 1) or 1) if self.siparis else None,
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
                    "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
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
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
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
                    "row_version": int(getattr(self.irsaliye, "row_version", 1) or 1)
                    if self.irsaliye
                    else None,
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
    """Satış faturası kartına denk, satın alma (alış) faturası kartı."""

    def __init__(self, parent, fatura=None, siparis=None, irsaliye=None, cari=None, cari_ac=None):
        super().__init__(parent)
        self.fatura = fatura
        self.kaynak_siparis = siparis
        self.kaynak_irsaliye = irsaliye
        self.cari_ac = cari_ac
        self.result = None
        self._fatura_form_kirli = False
        self._fatura_yukleniyor = True
        self.title("Alış Fatura Kartı")
        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self,
            min_genislik=900,
            min_yukseklik=520,
            varsayilan_genislik=1200,
            varsayilan_yukseklik=720,
            maximize=True,
        )
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.odemeler = []
        self.mevcut_borc = Decimal("0")
        self._duzenlenen_satir = None

        tedarikciler = list(AlisFaturasiService.aktif_tedarikcileri())
        for belge in (fatura, siparis, irsaliye):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.girdiler = {}
        self.satir_girdileri = {}

        # Üstte sabit kayıt çubuğu
        butonlar = ttk.Frame(self, padding=(8, 6, 8, 4))
        butonlar.pack(side="top", fill="x")
        self._alis_ust_butonlar = butonlar
        ttk.Label(
            butonlar,
            text="Kayıt: F1",
            font=("Segoe UI", 10, "bold"),
            foreground="#1f6aa5",
        ).pack(side="left", padx=(0, 12))
        ttk.Button(butonlar, text="Kaydet (F1)", width=16, command=self.kaydet).pack(
            side="right", padx=4
        )
        liste_btn = ttk.Button(
            butonlar, text="Fatura Listesi (F3)", command=self._fatura_listesini_ac
        )
        liste_btn.pack(side="right", padx=4)
        self._tooltip_bagla(liste_btn, "Alış Fatura Listesini Aç")
        ttk.Button(butonlar, text="PDF", command=self._alis_pdf_kaydet).pack(
            side="right", padx=4
        )
        ttk.Button(butonlar, text="Ön İzleme", command=self._alis_onizleme_ac).pack(
            side="right", padx=4
        )
        ttk.Button(butonlar, text="İptal Et", command=self.faturayi_iptal_et).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right", padx=4)
        self.bind("<F1>", self._f1_kaydet)
        self.bind("<F3>", self._f3_fatura_listesi)
        self.bind_all("<F1>", self._f1_kaydet)

        kaydirma_alani = ttk.Frame(self, padding=(6, 4))
        kaydirma_alani.pack(fill="both", expand=True)
        self._kaydirma_alani = kaydirma_alani
        self.canvas = tk.Canvas(kaydirma_alani, highlightthickness=0)
        dikey_kaydirma = ttk.Scrollbar(kaydirma_alani, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=dikey_kaydirma.set)
        dikey_kaydirma.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas, padding=6)
        pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(pencere, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        self._fatura_bilgileri_olustur()
        self._depo_bar_olustur()
        self._baglanti_olustur()
        doviz_cerceve = ttk.LabelFrame(self.icerik, text="DÖVİZ / KUR", padding=6)
        doviz_cerceve.pack(fill="x", pady=4)
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, doviz_cerceve)
        satir_sayfasi = ttk.LabelFrame(self.icerik, text="FATURA SATIRI GİRİŞİ VE SATIRLAR", padding=8)
        satir_sayfasi.pack(fill="both", expand=True, pady=4)
        self._satir_olustur(satir_sayfasi)
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=4)
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=1)
        self._odeme_olustur(alt)
        self._notlar_olustur(alt)

        if fatura:
            self._faturayi_doldur()
        elif irsaliye:
            self._irsaliyeyi_doldur(irsaliye)
        elif siparis:
            self._siparis_yukle(siparis)
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)
                self._bakiye_guncelle()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()
        self._alis_sticky_footer_kur()
        self._fatura_yukleniyor = False
        self._fatura_form_kirli = False

    def _tooltip_bagla(self, widget, metin: str):
        tip = {"win": None}

        def _goster(_e=None):
            if tip["win"] is not None:
                return
            try:
                x = widget.winfo_rootx() + 8
                y = widget.winfo_rooty() + widget.winfo_height() + 4
            except tk.TclError:
                return
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            tk.Label(
                win,
                text=metin,
                bg="#fff8dc",
                fg="#1a1a1a",
                relief="solid",
                bd=1,
                padx=6,
                pady=3,
                font=("Segoe UI", 9),
            ).pack()
            tip["win"] = win

        def _gizle(_e=None):
            win = tip["win"]
            tip["win"] = None
            if win is not None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass

        widget.bind("<Enter>", _goster)
        widget.bind("<Leave>", _gizle)

    def _alis_sticky_footer_kur(self):
        """Üst butonlar + orta kaydırma + alt Brüt/Net sabit."""
        from ui_pencere import sticky_footer_layout, calisma_alani

        footer = getattr(self, "_alis_toplam_cerceve", None)
        if footer is None:
            return
        # Satır grid'inden çıkar, alt banda taşı
        try:
            footer.grid_forget()
        except tk.TclError:
            try:
                footer.pack_forget()
            except tk.TclError:
                pass
        alt = ttk.Frame(self, padding=(6, 2, 6, 4))
        footer.pack(in_=alt, fill="x")
        # Alt banda Kaydet/Kapat tekrarı (kaydırırken de erişilebilir)
        btn = ttk.Frame(alt)
        btn.pack(fill="x", pady=(4, 0))
        ttk.Button(btn, text="Kapat", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btn, text="Kaydet (F1)", command=self.kaydet).pack(side="right", padx=4)
        sticky_footer_layout(
            self,
            ust=getattr(self, "_alis_ust_butonlar", None),
            orta=getattr(self, "_kaydirma_alani", None),
            alt=alt,
        )
        try:
            _, _, _, ah = calisma_alani(self)
            if hasattr(self, "satir_tablosu"):
                self.satir_tablosu.configure(height=10 if ah < 800 else 14)
            if hasattr(self, "odeme_tablosu"):
                self.odeme_tablosu.configure(height=3 if ah < 800 else 5)
            if hasattr(self, "ayrintili_notlar"):
                self.ayrintili_notlar.configure(height=3 if ah < 800 else 5)
        except Exception:
            pass

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _f1_kaydet(self, _event=None):
        """F1 = Kaydet (alan odaktayken de)."""
        try:
            if not self.winfo_exists():
                return
            odak = self.focus_get()
            if odak is None:
                return
            # Bu diyaloğun parçası değilse yok say
            w = odak
            while w is not None:
                if w == self:
                    self.kaydet()
                    return "break"
                w = w.master if hasattr(w, "master") else None
        except tk.TclError:
            return
        return "break"

    def _f3_fatura_listesi(self, _event=None):
        self._fatura_listesini_ac()
        return "break"

    def _fatura_listesini_ac(self):
        from fatura_liste_pencere import DOC_ALIS, fatura_listesi_ac

        fatura_listesi_ac(self, document_type=DOC_ALIS)

    def _alis_onizleme_ac(self):
        """Geçici PDF önizleme — kalıcı kayıt yok."""
        try:
            if hasattr(self, "_toplamlari_guncelle"):
                self._toplamlari_guncelle()
            from invoice_print.service import InvoicePrintService

            InvoicePrintService.open_pdf_preview(kart=self)
        except ValueError as hata:
            messagebox.showerror("Ön İzleme", str(hata), parent=self)
        except Exception as hata:
            messagebox.showerror(
                "Ön İzleme",
                f"PDF önizleme oluşturulamadı:\n{hata}",
                parent=self,
            )

    def _alis_pdf_kaydet(self):
        """Kalıcı PDF kaydı (kullanıcı klasör seçer)."""
        from pathlib import Path
        from tkinter import filedialog

        from invoice_print.pdf_service import render_invoice_to_pdf, safe_pdf_filename
        from invoice_print.service import InvoicePrintService
        from invoice_print.settings import load_print_settings, save_print_settings

        try:
            if hasattr(self, "_toplamlari_guncelle"):
                self._toplamlari_guncelle()
            vm = InvoicePrintService.build_from_kart(self)
        except ValueError as exc:
            messagebox.showerror("PDF", str(exc), parent=self)
            return
        ayar = load_print_settings()
        baslangic = ayar.get("son_pdf_klasoru") or str(Path.home() / "Documents")
        yol = filedialog.asksaveasfilename(
            parent=self,
            title="PDF Kaydet",
            initialdir=baslangic,
            initialfile=safe_pdf_filename(vm),
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            render_invoice_to_pdf(vm, Path(yol))
            ayar["son_pdf_klasoru"] = str(Path(yol).parent)
            save_print_settings(ayar)
            messagebox.showinfo("PDF", f"PDF kaydedildi:\n{yol}", parent=self)
        except ValueError as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _fatura_kirli_mi(self) -> bool:
        if getattr(self, "_fatura_form_kirli", False):
            return True
        if self.fatura is None:
            return bool(self.satirlar) or bool((self.tedarikci.get() or "").strip())
        return False

    def _kaydet_kapatmadan(self) -> bool:
        """Liste geçişi için kaydet; destroy yok."""
        try:
            tedarikci = self.tedarikci_map.get(self.tedarikci.get())
            if not tedarikci:
                raise ValueError("Aktif bir tedarikçi seçin.")
            if not self.satirlar:
                raise ValueError("En az bir fatura satırı ekleyin.")
            satirlar_hesap = [
                {
                    **dict(s),
                    "birim_fiyat": s.get("birim_alis_fiyati", s.get("birim_fiyat", 0)),
                }
                for s in self.satirlar
            ]
            satir_genel = AlisFaturasiService.toplam(satirlar_hesap)["genel_toplam"]
            self._alis_satir_brut = satir_genel
            self._alis_net_toplam = satir_genel
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get())
            satirlar = []
            for satir in self.satirlar:
                veri = dict(satir)
                if not veri.get("lot_no"):
                    veri["lot_no"] = StokService.otomatik_lot_no(tedarikci.unvan, fatura_tarihi)
                veri["birim_fiyat"] = veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0))
                if veri.get("birim_fiyat_doviz") in (None, "", 0, "0"):
                    pb = getattr(self, "_doviz_para_birimi", None)
                    if pb and (pb.get() or "TRY").upper() != "TRY":
                        veri["birim_fiyat_doviz"] = veri["birim_fiyat"]
                satirlar.append(veri)
            odeme_tutari = sum((decimal(o["tutar"], "Ödeme") for o in self.odemeler), Decimal("0"))
            ilk_odeme = self.odemeler[0] if self.odemeler else {}
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
                eslesen = next(
                    (s for s in AlisFaturasiService.acik_siparisler() if s.siparis_no == yazilan_siparis),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan sipariş numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("Sipariş numarası seçilen tedarikçiye ait değil.")
                siparis_id = eslesen.id
            if yazilan_irsaliye and not irsaliye_id:
                eslesen = next(
                    (i for i in AlisFaturasiService.acik_irsaliyeler() if i.irsaliye_no == yazilan_irsaliye),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan irsaliye numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("İrsaliye numarası seçilen tedarikçiye ait değil.")
                irsaliye_id = eslesen.id
            notlar = self.ayrintili_notlar.get("1.0", "end").strip()
            aciklama = self.girdiler["aciklama"].get().strip()
            if notlar:
                aciklama = f"{aciklama}\n{notlar}".strip() if aciklama else notlar
            veriler = {
                "fatura_no": self.girdiler["fatura_no"].get().strip(),
                "fatura_tarihi": fatura_tarihi,
                "islem_saati": islem_saati,
                "vade_tarihi": vade_tarihi,
                "cari_id": tedarikci.id,
                "siparis_id": siparis_id,
                "irsaliye_id": irsaliye_id,
                "depo": self.depo.get(),
                "odeme_tutari": odeme_tutari,
                "odeme_sekli": ilk_odeme.get("odeme_sekli"),
                "odeme_hesabi": ilk_odeme.get("hesap"),
                "aciklama": aciklama or None,
                "dokuman_yolu": self.dokuman.get().strip() or None,
                "row_version": int(getattr(self.fatura, "row_version", 1) or 1)
                if self.fatura
                else None,
                "tl_brut_toplam": getattr(self, "_alis_satir_brut", Decimal("0")),
                "tl_genel_toplam": getattr(self, "_alis_net_toplam", Decimal("0")),
                "genel_islem_turu": None,
                "genel_islem_orani": Decimal("0"),
                "genel_islem_tutari": Decimal("0"),
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            self.result = AlisFaturasiService.kaydet(
                veriler,
                satirlar,
                self.fatura.id if self.fatura else None,
            )
            self.fatura = AlisFaturasiService.getir(self.result.id) or self.result
            self._fatura_form_kirli = False
            return True
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return False

    def bagli_listeden_fatura_ac(self, fatura_id: int, *, document_type: str):
        from fatura_liste_pencere import DOC_ALIS
        from database.alis_faturasi_service import AlisFaturasiService

        if document_type != DOC_ALIS:
            raise ValueError("Alış faturası ekranına yalnız alış faturası açılabilir.")
        if self.fatura is not None and getattr(self.fatura, "id", None) == fatura_id:
            return
        if self._fatura_kirli_mi():
            dlg = tk.Toplevel(self)
            dlg.title("Kaydedilmemiş değişiklikler")
            dlg.transient(self)
            dlg.grab_set()
            ttk.Label(
                dlg,
                text="Açık faturada kaydedilmemiş değişiklikler var.\nNe yapmak istersiniz?",
                padding=12,
            ).pack()
            sonuc = {"secim": None}

            def _sec(s):
                sonuc["secim"] = s
                dlg.destroy()

            alt = ttk.Frame(dlg, padding=8)
            alt.pack(fill="x")
            ttk.Button(alt, text="Kaydet ve Aç", command=lambda: _sec("kaydet")).pack(
                side="left", padx=4
            )
            ttk.Button(alt, text="Değişiklikleri At ve Aç", command=lambda: _sec("at")).pack(
                side="left", padx=4
            )
            ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(
                side="left", padx=4
            )
            dlg.wait_window()
            if sonuc["secim"] in (None, "vazgec"):
                return
            if sonuc["secim"] == "kaydet":
                if not self._kaydet_kapatmadan():
                    return
        fatura = AlisFaturasiService.getir(fatura_id)
        if not fatura:
            raise ValueError("Fatura bulunamadı.")
        self.fatura = fatura
        self._fatura_form_kirli = False
        self._faturayi_doldur()

    def destroy(self):
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        super().destroy()

    def _girdi(self, parent, satir, baslik, alan, deger="", sutun=0, genislik=35, readonly=False):
        ttk.Label(parent, text=baslik).grid(row=satir, column=sutun, padx=8, pady=5, sticky="w")
        widget = ttk.Entry(parent, width=genislik)
        widget.grid(row=satir, column=sutun + 1, padx=8, pady=5, sticky="ew")
        widget.insert(0, deger)
        if readonly:
            widget.configure(state="readonly")
        self.girdiler[alan] = widget
        return widget

    def _fatura_bilgileri_olustur(self):
        ttk.Label(self.icerik, text="FATURA BİLGİLERİ", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        genel = ttk.LabelFrame(self.icerik, text="Fatura Bilgileri", padding=8)
        genel.pack(fill="x", pady=(0, 8))
        fatura_no = self.fatura.fatura_no if self.fatura else AlisFaturasiService.fatura_no()
        self._girdi(genel, 0, "Fatura Numarası", "fatura_no", fatura_no, readonly=True)
        tarih_alani(
            genel, 1, "Fatura Tarihi", "fatura_tarihi",
            tarih_goster(self.fatura.fatura_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            on_select=self.vade_gun_degisti,
        )
        saat_deger = saat_varsayilan(
            self.fatura.islem_saati if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        self._girdi(genel, 2, "İşlem Saati", "islem_saati", saat_deger)
        tarih_alani(
            genel, 3, "Vade Tarihi", "vade_tarihi",
            tarih_goster(self.fatura.vade_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            on_select=self.vade_tarih_degisti,
        )
        self._girdi(
            genel, 4, "Vade Günü", "vade_gunu",
            str(self.fatura.vade_gunu if self.fatura else 0),
        )
        self.girdiler["fatura_tarihi"].bind("<FocusOut>", self.vade_gun_degisti)
        self.girdiler["vade_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.girdiler["vade_gunu"].bind("<KeyRelease>", self.vade_gun_degisti)

        ttk.Label(genel, text="Tedarikçi").grid(row=5, column=0, padx=8, pady=5, sticky="w")
        self.tedarikci = tk.StringVar()
        self.tedarikci_combo = ttk.Combobox(
            genel, textvariable=self.tedarikci, values=list(self.tedarikci_map), state="readonly", width=33,
        )
        self.tedarikci_combo.grid(row=5, column=1, padx=8, pady=5, sticky="ew")
        self.tedarikci_combo.bind("<<ComboboxSelected>>", lambda _e: self._bakiye_guncelle())

        self._girdi(genel, 6, "Mevcut Borç Bakiyesi", "mevcut_bakiye", "0,00 TL", readonly=True)
        self._girdi(genel, 7, "Tahmini Yeni Bakiye", "tahmini_bakiye", "0,00 TL", readonly=True)

        ttk.Label(genel, text="Durum").grid(row=0, column=2, padx=8, pady=5, sticky="w")
        self.durum = ttk.Combobox(genel, values=("AÇIK", "KAPALI", "İPTAL"), state="readonly", width=28)
        self.durum.grid(row=0, column=3, padx=8, pady=5, sticky="ew")
        self.durum.set(self.fatura.durum if self.fatura else "AÇIK")
        self.durum.configure(state="disabled")
        genel.columnconfigure(1, weight=1)
        genel.columnconfigure(3, weight=1)

    def _depo_bar_olustur(self):
        depo_bar = ttk.LabelFrame(self.icerik, text="STOK GİRİŞ DEPOSU", padding=8)
        depo_bar.pack(fill="x", pady=4)
        ttk.Label(depo_bar, text="Ürün hangi depoya girsin?").pack(side="left", padx=(0, 10))
        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        self.depo = ttk.Combobox(depo_bar, values=depolar, state="readonly", width=32)
        self.depo.pack(side="left")
        if self.fatura and self.fatura.depo in depolar:
            self.depo.set(self.fatura.depo)
        else:
            self.depo.set(depolar[0])
        ttk.Button(depo_bar, text="Yeni Depo Aç", command=self.depo_ekle).pack(side="left", padx=10)
        ttk.Label(
            depo_bar,
            text="Satır kaydında stok girişi ve lot bu depoya yazılır.",
            foreground="#666666",
        ).pack(side="left", padx=8)
        self.girdiler["depo"] = self.depo

    def _baglanti_olustur(self):
        ek = ttk.LabelFrame(self.icerik, text="FATURA BAĞLANTI BİLGİLERİ", padding=8)
        ek.pack(fill="x", pady=4)
        ttk.Label(ek, text="Sipariş Numarası").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.siparis_no = ttk.Entry(ek, width=28)
        self.siparis_no.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        ttk.Label(ek, text="İrsaliye Numarası").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.irsaliye_no = ttk.Entry(ek, width=28)
        self.irsaliye_no.grid(row=0, column=3, padx=6, pady=4, sticky="ew")
        ttk.Button(ek, text="Cari Kartına Geç", command=self.cariye_git).grid(row=0, column=4, padx=6, sticky="w")

        ttk.Label(ek, text="Doküman Ekle").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self.dokuman = ttk.Entry(ek, width=28)
        self.dokuman.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        ttk.Button(ek, text="Doküman Seç", command=self.dokuman_sec).grid(row=1, column=2, padx=6, sticky="w")

        ozet = ttk.Frame(ek)
        ozet.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 0))
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
        for sutun in (1, 3):
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

    def _satir_olustur(self, parent):
        giris = ttk.LabelFrame(parent, text="Fatura Satırı", padding=8)
        giris.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        # İki satır: miktar / alış fiyatı her zaman görünür ve tıklanabilir kalsın
        ust_alanlar = (
            ("Ürün Kodu", "urun_kodu", 14),
            ("Ürün Adı", "urun_adi", 36),
            ("Açıklama", "aciklama", 24),
            ("Miktar", "miktar", 12),
            ("Birim", "birim", 10),
        )
        alt_alanlar = (
            ("Alış Fiyatı", "birim_fiyat", 14),
            ("İskonto %", "iskonto_orani", 10),
            ("KDV %", "kdv_orani", 10),
        )
        for sutun, (baslik, alan, genislik) in enumerate(ust_alanlar):
            giris.columnconfigure(sutun, weight={0: 1, 1: 3, 2: 2, 3: 1}.get(sutun, 0), minsize={0: 110, 1: 220, 2: 140, 3: 90, 4: 80}.get(sutun, 80))
            ttk.Label(giris, text=baslik).grid(row=0, column=sutun, padx=3, pady=3, sticky="w")
            if alan == "birim":
                widget = ttk.Combobox(giris, values=BIRIM_SECENEKLERI, state="readonly", width=genislik)
            else:
                widget = ttk.Entry(giris, width=genislik)
            widget.grid(row=1, column=sutun, padx=3, pady=3, sticky="ew")
            self.satir_girdileri[alan] = widget
            if alan in ("urun_kodu", "urun_adi"):
                widget.bind("<KeyRelease>", self.satir_urun_arama_ac)
            if alan == "miktar":
                widget.bind("<KeyRelease>", lambda _e: self.satir_tutar_guncelle())
        for sutun, (baslik, alan, genislik) in enumerate(alt_alanlar):
            ttk.Label(giris, text=baslik).grid(row=2, column=sutun, padx=3, pady=3, sticky="w")
            widget = ttk.Entry(giris, width=genislik)
            widget.grid(row=3, column=sutun, padx=3, pady=3, sticky="ew")
            self.satir_girdileri[alan] = widget
            if alan == "birim_fiyat":
                widget.configure(state="normal")
                widget.bind("<F10>", self.satir_fiyat_secimi_ac)
            if alan == "iskonto_orani":
                widget.bind("<Double-1>", self._alis_iskonto_ac)
                widget.bind("<F2>", self._alis_iskonto_ac)
            if alan in ("birim_fiyat", "kdv_orani"):
                widget.bind("<KeyRelease>", lambda _e: self.satir_tutar_guncelle())
        # F10: Treeview vb. odaktayken de çalışsın (Entry bindtags → Toplevel)
        self.bind("<F10>", self.satir_fiyat_secimi_ac)
        self.satir_girdileri["birim"].set("Adet")
        self.satir_girdileri["kdv_orani"].insert(0, satir_kdv_metin())
        self.satir_girdileri["iskonto_orani"].insert(0, "")
        self._form_iskonto_2 = "0"
        self._form_iskonto_3 = "0"
        self._alis_form_enter_bagla()

        butonlar = ttk.Frame(giris)
        butonlar.grid(row=4, column=0, columnspan=5, sticky="w", pady=(5, 0))
        ttk.Button(butonlar, text="Satır Ekle", command=self.satir_kaydet).pack(side="left")
        ttk.Button(butonlar, text="Çoklu İskonto", command=self._alis_iskonto_ac).pack(side="left", padx=6)
        ttk.Button(butonlar, text="Kolon Ayarları", command=self._alis_kolon_ayarlari_ac).pack(
            side="left", padx=6
        )
        ttk.Button(butonlar, text="Temizle", command=self.satir_formunu_temizle).pack(side="left", padx=8)
        ttk.Button(butonlar, text="STOK LİSTESİ", command=self.stok_listesi_ac).pack(side="left", padx=6)
        ttk.Label(butonlar, text="Barkod:").pack(side="left", padx=(12, 2))
        self.satir_girdileri["barkod"] = ttk.Entry(butonlar, width=16)
        self.satir_girdileri["barkod"].pack(side="left")
        self.satir_girdileri["barkod"].bind("<Return>", self.barkoddan_satir_bul)
        ttk.Label(butonlar, text="Lot:").pack(side="left", padx=(8, 2))
        self.satir_girdileri["lot_no"] = ttk.Entry(butonlar, width=18)
        self.satir_girdileri["lot_no"].pack(side="left")
        self.satir_girdileri["lot_no"].bind("<KeyRelease>", self.lot_girisi_senkron)
        self.satir_tutar = ttk.Label(butonlar, text="Tutar: 0,00 TL", font=("Segoe UI", 10, "bold"))
        self.satir_tutar.pack(side="left", padx=12)
        ttk.Label(butonlar, text="(Alış Fiyatı: F10)", foreground="#666666").pack(side="left", padx=8)

        kolonlar = (
            "barkod", "kod", "ad", "aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv",
            "net_birim", "lot", "lot_girisi", "toplam", "siparis_miktar", "irsaliye_miktar", "fatura_miktar",
        )
        self.satir_tablosu = ttk.Treeview(parent, columns=kolonlar, show="headings", height=10)
        basliklar = {
            "barkod": "Barkod", "kod": "Ürün Kodu", "ad": "Ürün Adı", "aciklama": "Açıklama",
            "miktar": "Miktar", "birim": "Birim", "fiyat": "Alış Fiyatı", "iskonto": "İskonto",
            "kdv": "KDV", "net_birim": "Net Birim Fiyat", "lot": "Lot No", "lot_girisi": "Lot Girişi",
            "toplam": "Net Tutar",
            "siparis_miktar": "Sipariş Miktarı", "irsaliye_miktar": "İrsaliye Miktarı",
            "fatura_miktar": "Fatura Miktarı",
        }
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            w = 110 if kolon in ("net_birim", "toplam", "ad") else 100
            if kolon == "ad":
                w = 220
            if kolon == "iskonto":
                w = 160
            if kolon == "kdv":
                w = 70
            self.satir_tablosu.column(
                kolon,
                width=w,
                minwidth=40 if kolon == "iskonto" else 20,
                anchor="e" if kolon in ("net_birim", "toplam", "fiyat") else "w",
            )
        # Firma/kullanıcı kolon tercihleri (displaycolumns; values kesilmez)
        try:
            from fatura_satir_kolon_prefs import (
                EKRAN_ALIS,
                ayarlari_yukle,
                resize_bagla,
                tabloya_uygula,
            )

            self._alis_kolon_ayarlari = ayarlari_yukle(EKRAN_ALIS)
            self._alis_kolon_ayarlari = tabloya_uygula(
                self.satir_tablosu, EKRAN_ALIS, self._alis_kolon_ayarlari
            )

            def _alis_set_ayar(a):
                self._alis_kolon_ayarlari = a

            resize_bagla(
                self.satir_tablosu,
                EKRAN_ALIS,
                ayar_getter=lambda: getattr(self, "_alis_kolon_ayarlari", {}),
                ayar_setter=_alis_set_ayar,
                parent=self,
            )
        except Exception:
            self._alis_kolon_ayarlari = None
        dikey = ttk.Scrollbar(parent, orient="vertical", command=self.satir_tablosu.yview)
        yatay = ttk.Scrollbar(parent, orient="horizontal", command=self.satir_tablosu.xview)
        self.satir_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.satir_tablosu.grid(row=1, column=0, sticky="nsew")
        dikey.grid(row=1, column=1, sticky="ns")
        yatay.grid(row=2, column=0, sticky="ew")
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self.satir_tablosu.bind("<<TreeviewSelect>>", self.satir_secildi)
        self.satir_tablosu.bind("<Double-1>", self._alis_satir_cift_tik)
        self.satir_tablosu.bind("<F2>", self._alis_iskonto_ac)
        self.satir_tablosu.bind("<Button-3>", self._alis_satir_sag_tik)

        toplamlar = ttk.LabelFrame(parent, text="TOPLAMLAR", padding=6)
        toplamlar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        # Sabit footer'a taşı (kaydırma dışında her zaman görünür)
        self._alis_toplam_cerceve = toplamlar
        self.satir_ozet = ttk.Label(
            toplamlar,
            text="Ara Toplam: 0,00 TL | İskonto: 0,00 TL | KDV: 0,00 TL | Genel: 0,00 TL",
            wraplength=1000,
        )
        self.satir_ozet.pack(anchor="w")
        islem_satir = ttk.Frame(toplamlar)
        islem_satir.pack(anchor="e", fill="x", pady=(4, 0))
        self._alis_satir_brut = Decimal("0")
        self._alis_net_toplam = Decimal("0")
        self._fatura_persisted = bool(
            getattr(self, "fatura", None) and getattr(self.fatura, "id", None)
        )
        ttk.Label(islem_satir, text="Brüt:").pack(side="left", padx=(0, 4))
        self._alis_brut_lbl = ttk.Label(islem_satir, text="0,00 TL", width=12, anchor="e")
        self._alis_brut_lbl.pack(side="left", padx=(0, 12))
        ttk.Label(islem_satir, text="Genel Toplam:").pack(side="left", padx=(12, 2))
        self._alis_net_lbl = ttk.Label(islem_satir, text="0,00 TL", width=14, anchor="e")
        self._alis_net_lbl.pack(side="left")

    def _odeme_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="ÖDEMELER", padding=8)
        cerceve.grid(row=0, column=0, sticky="nsew")
        kolonlar = ("tarih", "tutar", "sekil", "hesap", "aciklama")
        self.odeme_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=6)
        for kolon, baslik in zip(kolonlar, ("Tarih", "Tutar", "Ödeme Şekli", "Hesap", "Açıklama")):
            self.odeme_tablosu.heading(kolon, text=baslik)
            self.odeme_tablosu.column(kolon, width=140)
        self.odeme_tablosu.pack(fill="both", expand=True)
        alt = ttk.Frame(cerceve)
        alt.pack(fill="x", pady=8)
        ttk.Button(alt, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(alt, text="Ödeme Düzenle", command=self.odeme_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Ödeme Kaldır", command=self.odeme_kaldir).pack(side="left")
        self.odeme_ozet = ttk.Label(cerceve, text="Ödenen: 0,00 TL | Kalan: 0,00 TL")
        self.odeme_ozet.pack(anchor="w")

    def _notlar_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="AÇIKLAMA / NOTLAR", padding=8)
        cerceve.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(cerceve, text="Genel Açıklama").pack(anchor="w")
        self.girdiler["aciklama"] = ttk.Entry(cerceve)
        self.girdiler["aciklama"].pack(fill="x", pady=(2, 8))
        ttk.Label(cerceve, text="Ayrıntılı Notlar").pack(anchor="w")
        self.ayrintili_notlar = tk.Text(cerceve, height=6, width=45)
        self.ayrintili_notlar.pack(fill="both", expand=True, pady=(2, 0))

    def _readonly_yaz(self, alan, deger):
        w = self.girdiler[alan]
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, deger)
        w.configure(state="readonly")

    def _entry_yaz(self, alan, deger):
        self.girdiler[alan].delete(0, "end")
        self.girdiler[alan].insert(0, deger)

    def _tedarikci_sec(self, cari):
        anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)

    def depo_ekle(self):
        ad = simpledialog.askstring("Yeni Depo", "Depo adı:", parent=self)
        if not ad:
            return
        try:
            depo = StokService.depo_ekle(ad)
        except ValueError as hata:
            messagebox.showerror("Depo eklenemedi", str(hata), parent=self)
            return
        self.depo["values"] = tuple(d.ad for d in StokService.depolar())
        self.depo.set(depo.ad)

    def vade_gun_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = fatura_tarihi + timedelta(days=int(self.girdiler["vade_gunu"].get() or 0))
        except (ValueError, TypeError):
            return
        self._entry_yaz("vade_tarihi", tarih_goster(vade_tarihi))
        self._toplamlari_guncelle()

    def vade_tarih_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            return
        self.girdiler["vade_gunu"].delete(0, "end")
        self.girdiler["vade_gunu"].insert(0, str((vade_tarihi - fatura_tarihi).days))
        self._toplamlari_guncelle()

    def dokuman_sec(self):
        yol = filedialog.askopenfilename(parent=self, title="Faturaya doküman ekle")
        if yol:
            self.dokuman.delete(0, "end")
            self.dokuman.insert(0, yol)

    def cariye_git(self):
        cari = self.tedarikci_map.get(self.tedarikci.get())
        if not cari:
            messagebox.showinfo("Cari", "Önce tedarikçi seçin.", parent=self)
            return
        if self.cari_ac:
            self.cari_ac(cari)
        else:
            messagebox.showinfo("Cari", "Cari kartı bu ekrandan açılamıyor.", parent=self)

    def _onerilen_lot(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        adi = tedarikci.unvan if tedarikci else ""
        try:
            tarih = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            tarih = date.today()
        return StokService.otomatik_lot_no(adi, tarih)

    def lot_girisi_senkron(self, _event=None):
        lot = self.satir_girdileri["lot_no"].get().strip()
        return lot

    def lot_oner(self):
        if not self.satir_girdileri["lot_no"].get().strip():
            self.satir_girdileri["lot_no"].insert(0, self._onerilen_lot())

    def stok_listesi_ac(self):
        if getattr(self, "_urun_sec_pencere", None) and self._urun_sec_pencere.winfo_exists():
            return
        dialog = UrunSecDialog(
            self,
            on_select=self.satir_urun_secildi,
            kod=self.satir_girdileri["urun_kodu"].get().strip(),
            ad=self.satir_girdileri["urun_adi"].get().strip(),
        )
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None
        self._satir_odakla("miktar")

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
        dialog = UrunSecDialog(self, on_select=self.satir_urun_secildi, kod=kod, ad=ad)
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None
        self._satir_odakla("miktar")

    def _satir_alanlarini_aktif_et(self):
        """Miktar / alış fiyatı ve diğer satır Entry'lerini yazılabilir bırakır."""
        for alan, widget in self.satir_girdileri.items():
            if isinstance(widget, ttk.Combobox):
                continue
            try:
                widget.configure(state="normal")
            except tk.TclError:
                pass

    def _alis_form_enter_bagla(self):
        """Enter ile form alanları arasında gezin; son alandan satırı kaydet / barkoda dön."""
        sira = ("miktar", "birim", "birim_fiyat", "iskonto_orani", "kdv_orani")

        def _ilerle(mevcut, geri=False):
            try:
                i = sira.index(mevcut)
            except ValueError:
                return "break"
            j = i - 1 if geri else i + 1
            if 0 <= j < len(sira):
                self._satir_odakla(sira[j])
                return "break"
            if geri:
                return "break"
            # Son alan: satırı kaydet (varsa), barkoda odak
            try:
                self.satir_kaydet(formu_temizle=False)
            except Exception:
                pass
            w = self.satir_girdileri.get("barkod")
            if w is not None:
                try:
                    w.focus_set()
                except tk.TclError:
                    pass
            return "break"

        for alan in sira:
            w = self.satir_girdileri.get(alan)
            if w is None:
                continue
            w.bind("<Return>", lambda e, a=alan: _ilerle(a))
            w.bind("<KP_Enter>", lambda e, a=alan: _ilerle(a))
            w.bind("<Shift-Return>", lambda e, a=alan: _ilerle(a, geri=True))

    def _satir_odakla(self, odak="miktar"):
        widget = self.satir_girdileri.get(odak) or self.satir_girdileri.get("birim_fiyat")
        if widget is None:
            return
        self._satir_alanlarini_aktif_et()
        try:
            self.lift()
            widget.focus_force()
            if isinstance(widget, ttk.Entry) and widget.get():
                widget.selection_range(0, "end")
        except tk.TclError:
            try:
                widget.focus_set()
            except tk.TclError:
                pass

    def _satiri_duzenlemeye_al(self, idx, odak="miktar"):
        """Tablo satırını seçer, formu doldurur, miktar/fiyatı aktif eder."""
        if idx is None or idx < 0 or idx >= len(self.satirlar):
            return
        iid = str(idx)
        self._duzenlenen_satir = idx
        try:
            self.satir_tablosu.selection_set(iid)
            self.satir_tablosu.see(iid)
        except tk.TclError:
            pass
        self.satir_formunu_doldur(self.satirlar[idx])
        self._satir_alanlarini_aktif_et()
        self.after_idle(lambda: self._satir_odakla(odak))

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
                self.satir_girdileri[alan].configure(state="normal")
                self.satir_girdileri[alan].delete(0, "end")
                self.satir_girdileri[alan].insert(0, deger)

        # Son alış fiyatını satıra yaz (satış fiyatı değil)
        fiyat = StokService.son_alis_fiyati(kod)
        if fiyat == 0 and len(degerler) > 4 and str(degerler[4]).strip():
            try:
                fiyat = decimal(degerler[4], "Fiyat", Decimal("0"))
            except ValueError:
                pass
        self._satir_alanlarini_aktif_et()
        self.satir_girdileri["birim_fiyat"].delete(0, "end")
        self.satir_girdileri["birim_fiyat"].insert(0, f"{fiyat:f}".rstrip("0").rstrip(".") or "0")

        self.satir_girdileri["barkod"].delete(0, "end")
        bulunan = StokService.stoklari_ara(kod)
        stok = next((s for s in bulunan if s.stok_kodu == kod), None)
        if stok and stok.barkod:
            self.satir_girdileri["barkod"].insert(0, stok.barkod)
        if not self.satir_girdileri["miktar"].get().strip():
            self.satir_girdileri["miktar"].insert(0, "1")
        if not getattr(self, "_form_iskonto_1", None) and not self.satir_girdileri["iskonto_orani"].get().strip():
            self._form_iskonto_yaz("0", "0", "0")
        if not self.satir_girdileri["kdv_orani"].get().strip():
            stok_kdv = getattr(stok, "kdv_orani", None) if stok else None
            self.satir_girdileri["kdv_orani"].insert(
                0, satir_kdv_metin(stok_kdv=stok_kdv)
            )
        self.lot_oner()
        self.satir_tutar_guncelle()
        # Yeni satır ekle; formu temizleme — miktar/fiyat hemen düzenlenebilsin
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        self._duzenlenen_satir = None
        self.satir_kaydet(formu_temizle=False)
        if self.satirlar:
            self._satiri_duzenlemeye_al(len(self.satirlar) - 1, odak="miktar")

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
        fiyat = StokService.son_alis_fiyati(stok.stok_kodu)
        self.satir_urun_secildi((stok.stok_kodu, stok.stok_adi, stok.birim, "", str(fiyat)))
        return "break"

    def satir_fiyat_secimi_ac(self, _event=None):
        """Alış Fiyatı alanında F10: stok kartındaki ALIŞ fiyatlarını listeler."""
        if getattr(self, "_fiyat_sec_pencere", None):
            try:
                if self._fiyat_sec_pencere.winfo_exists():
                    return "break"
            except tk.TclError:
                self._fiyat_sec_pencere = None
        kod = self.satir_girdileri["urun_kodu"].get().strip()
        if not kod:
            messagebox.showinfo("Alış Fiyatı", "Önce ürün kodu girin veya satır seçin.", parent=self)
            return "break"
        from app import PriceSelectionDialog
        self._satir_alanlarini_aktif_et()
        dialog = PriceSelectionDialog(
            self,
            kod,
            on_select=self.satir_fiyati_secildi,
            fiyat_turu="alis",
        )
        self._fiyat_sec_pencere = dialog
        self.wait_window(dialog)
        self._fiyat_sec_pencere = None
        self._satir_odakla("birim_fiyat")
        return "break"

    def satir_fiyati_secildi(self, fiyat):
        alan = self.satir_girdileri["birim_fiyat"]
        alan.configure(state="normal")
        alan.delete(0, "end")
        tutar = f"{Decimal(str(fiyat.tutar)):f}".rstrip("0").rstrip(".") or "0"
        alan.insert(0, tutar)
        self.satir_tutar_guncelle()
        self.after_idle(lambda: self._satir_odakla("birim_fiyat"))

    def _alis_satir_cift_tik(self, event=None):
        if event is not None and hasattr(self, "satir_tablosu"):
            try:
                tablo = self.satir_tablosu
                if tablo.identify_region(event.x, event.y) == "cell":
                    kolon_id = tablo.identify_column(event.x)
                    kolon_sira = int(kolon_id.replace("#", "")) - 1
                    kolonlar = tablo["columns"]
                    if 0 <= kolon_sira < len(kolonlar) and kolonlar[kolon_sira] == "iskonto":
                        row = tablo.identify_row(event.y)
                        if row:
                            tablo.selection_set(row)
                            self._duzenlenen_satir = int(row)
                            self._alis_iskonto_ac()
                            return "break"
            except (tk.TclError, TypeError, ValueError):
                pass
        self.satir_secildi(event)

    def _alis_satir_sag_tik(self, event):
        row = self.satir_tablosu.identify_row(event.y)
        if row:
            self.satir_tablosu.selection_set(row)
            try:
                self._duzenlenen_satir = int(row)
            except (TypeError, ValueError):
                pass
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Çoklu İskonto Düzenle", command=self._alis_iskonto_ac)
        menu.add_command(label="İskontoları Temizle", command=self._alis_iskonto_temizle)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _alis_iskonto_temizle(self):
        idx = self._duzenlenen_satir
        secim = self.satir_tablosu.selection()
        if secim:
            try:
                idx = int(secim[0])
            except (TypeError, ValueError):
                pass
        if idx is None or not (0 <= idx < len(self.satirlar)):
            self._form_iskonto_yaz("0", "0", "0")
            self.satir_tutar_guncelle()
            return
        self.satirlar[idx]["iskonto_orani"] = "0"
        self.satirlar[idx]["iskonto_orani_2"] = "0"
        self.satirlar[idx]["iskonto_orani_3"] = "0"
        self.satir_formunu_doldur(self.satirlar[idx])
        self._satir_listesini_yenile()

    def _form_iskonto_yaz(self, i1, i2, i3):
        from database.iskonto_hesap_service import iskonto_goster_metin

        self._form_iskonto_2 = str(i2 or "0")
        self._form_iskonto_3 = str(i3 or "0")
        w = self.satir_girdileri.get("iskonto_orani")
        if w is None:
            return
        metin = iskonto_goster_metin(i1, i2, i3, bos_goster="")
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, metin)
        # İlk oranı da sakla (kaydet için)
        self._form_iskonto_1 = str(i1 or "0")

    def _alis_kolon_ayarlari_ac(self):
        from fatura_satir_kolon_prefs import (
            EKRAN_ALIS,
            FaturaSatirKolonAyarDialog,
            ayarlari_yukle,
            tabloya_uygula,
        )

        mevcut = getattr(self, "_alis_kolon_ayarlari", None) or ayarlari_yukle(EKRAN_ALIS)

        def _uygula(ayar):
            self._alis_kolon_ayarlari = tabloya_uygula(self.satir_tablosu, EKRAN_ALIS, ayar)

        FaturaSatirKolonAyarDialog(
            self,
            EKRAN_ALIS,
            mevcut,
            on_uygula=_uygula,
            baslik="Alış Faturası — Kolon Ayarları",
        )

    def _alis_iskonto_ac(self, _event=None):
        from fatura_iskonto_ui import satir_iskontolari_ac

        idx = self._duzenlenen_satir
        secim = self.satir_tablosu.selection() if hasattr(self, "satir_tablosu") else ()
        if secim:
            try:
                idx = int(secim[0])
            except (TypeError, ValueError):
                pass

        if idx is not None and 0 <= idx < len(self.satirlar):
            satir = dict(self.satirlar[idx])
        else:
            # Form taslağı
            satir = {
                alan: widget.get().strip()
                for alan, widget in self.satir_girdileri.items()
            }
            satir["iskonto_orani"] = getattr(self, "_form_iskonto_1", satir.get("iskonto_orani") or "0")
            satir["iskonto_orani_2"] = getattr(self, "_form_iskonto_2", "0")
            satir["iskonto_orani_3"] = getattr(self, "_form_iskonto_3", "0")
            # Görünen metin yüzde değilse form değerlerini kullan
            try:
                decimal(satir["iskonto_orani"] or 0, "İskonto", Decimal("0"))
            except ValueError:
                satir["iskonto_orani"] = getattr(self, "_form_iskonto_1", "0")

        def _uygula(oranlar):
            if idx is not None and 0 <= idx < len(self.satirlar):
                self.satirlar[idx].update(oranlar)
                self.satir_formunu_doldur(self.satirlar[idx])
                self._satir_listesini_yenile()
            else:
                self._form_iskonto_yaz(
                    oranlar["iskonto_orani"],
                    oranlar["iskonto_orani_2"],
                    oranlar["iskonto_orani_3"],
                )
                self.satir_tutar_guncelle()

        satir_iskontolari_ac(
            self,
            belge_turu="Alış",
            satir=satir,
            fiyat_alani="birim_fiyat",
            on_uygula=_uygula,
            satir_kimlik=idx,
        )
        return "break"

    def satir_tutar_guncelle(self):
        try:
            from database.iskonto_hesap_service import satir_iskonto_hesapla

            miktar = decimal(self.satir_girdileri["miktar"].get() or 0, "Miktar")
            fiyat = decimal(self.satir_girdileri["birim_fiyat"].get() or 0, "Birim fiyat")
            kdv = decimal(self.satir_girdileri["kdv_orani"].get() or 0, "KDV")
            i1 = getattr(self, "_form_iskonto_1", None)
            if i1 is None:
                try:
                    i1 = decimal(self.satir_girdileri["iskonto_orani"].get() or 0, "İskonto")
                except ValueError:
                    i1 = Decimal("0")
            h = satir_iskonto_hesapla(
                miktar=miktar,
                brut_birim_fiyat=fiyat,
                iskonto1=i1,
                iskonto2=getattr(self, "_form_iskonto_2", 0),
                iskonto3=getattr(self, "_form_iskonto_3", 0),
                kdv_orani=kdv,
            )
            self.satir_tutar.configure(text=f"Tutar: {para_goster(h['net_tutar'])}")
        except ValueError:
            self.satir_tutar.configure(text="Tutar: 0,00 TL")

    def satir_formunu_temizle(self):
        for alan, widget in self.satir_girdileri.items():
            if isinstance(widget, ttk.Combobox):
                widget.set("Adet" if alan == "birim" else "")
            else:
                widget.configure(state="normal")
                widget.delete(0, "end")
        self.satir_girdileri["kdv_orani"].insert(0, satir_kdv_metin())
        self._form_iskonto_yaz("0", "0", "0")
        self._duzenlenen_satir = None
        self.satir_tutar_guncelle()
        self.satir_tablosu.selection_remove(self.satir_tablosu.selection())

    def satir_formunu_doldur(self, veri):
        self._satir_alanlarini_aktif_et()
        for alan, widget in self.satir_girdileri.items():
            if alan == "iskonto_orani":
                continue
            deger = veri.get(alan, "")
            if alan == "birim_fiyat" and deger in ("", None):
                deger = veri.get("birim_alis_fiyati", "")
            if isinstance(widget, ttk.Combobox):
                if alan == "birim" and deger and deger not in BIRIM_SECENEKLERI:
                    widget["values"] = BIRIM_SECENEKLERI + (str(deger),)
                widget.set("" if deger is None else str(deger) or ("Adet" if alan == "birim" else ""))
            else:
                widget.configure(state="normal")
                widget.delete(0, "end")
                widget.insert(0, "" if deger is None else str(deger))
        self._form_iskonto_yaz(
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
        )
        self.satir_tutar_guncelle()

    def satir_secildi(self, _event=None):
        secim = self.satir_tablosu.selection()
        if not secim:
            return
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return
        if idx < 0 or idx >= len(self.satirlar):
            return
        self._duzenlenen_satir = idx
        self.satir_formunu_doldur(self.satirlar[idx])
        self._satir_alanlarini_aktif_et()
        # Treeview odak çalmasın; miktar düzenlenebilir kalsın
        self.after_idle(lambda: self._satir_odakla("miktar"))

    def satir_kaydet(self, formu_temizle=True):
        self._satir_alanlarini_aktif_et()
        veri = {alan: widget.get().strip() for alan, widget in self.satir_girdileri.items()}
        if not veri["urun_kodu"] or not veri["urun_adi"]:
            messagebox.showwarning("Eksik bilgi", "Ürün kodu ve ürün adı zorunludur.", parent=self)
            return
        veri["iskonto_orani"] = getattr(self, "_form_iskonto_1", "0")
        veri["iskonto_orani_2"] = getattr(self, "_form_iskonto_2", "0")
        veri["iskonto_orani_3"] = getattr(self, "_form_iskonto_3", "0")
        try:
            for alan in ("miktar", "birim_fiyat", "iskonto_orani", "iskonto_orani_2", "iskonto_orani_3", "kdv_orani"):
                decimal(veri.get(alan) or 0, alan, Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        if not veri.get("lot_no"):
            veri["lot_no"] = self._onerilen_lot()
        veri["lot_girisi"] = veri["lot_no"]
        veri["birim_alis_fiyati"] = veri["birim_fiyat"]
        secim = self.satir_tablosu.selection()
        if secim or self._duzenlenen_satir is not None:
            idx = int(secim[0]) if secim else self._duzenlenen_satir
            mevcut = self.satirlar[idx]
            for alan in (
                "siparis_satiri_id", "irsaliye_satiri_id",
                "siparis_miktar", "irsaliye_miktar", "faturalanan_miktar",
                "birim_fiyat_doviz",
            ):
                if alan in mevcut and alan not in veri:
                    veri[alan] = mevcut[alan]
            self.satirlar[idx] = doviz_satir_kaydet_oncesi(self, {**mevcut, **veri})
        else:
            self.satirlar.append(doviz_satir_kaydet_oncesi(self, veri))
        self._satir_listesini_yenile()
        if hasattr(self, "_doviz_para_birimi"):
            doviz_ozet_guncelle(self)
        if formu_temizle:
            self.satir_formunu_temizle()
        elif self.satirlar and self._duzenlenen_satir is None and not secim:
            # Yeni eklenen satırı düzenleme modunda tut
            self._duzenlenen_satir = len(self.satirlar) - 1
            try:
                self.satir_tablosu.selection_set(str(self._duzenlenen_satir))
            except tk.TclError:
                pass

    def _satir_listesini_yenile(self):
        from database.iskonto_hesap_service import iskonto_goster_metin, satir_iskonto_hesapla

        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar", 0), "Miktar")
            fiyat = decimal(veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0)), "Fiyat")
            h = satir_iskonto_hesapla(
                miktar=miktar,
                brut_birim_fiyat=fiyat,
                iskonto1=veri.get("iskonto_orani", 0),
                iskonto2=veri.get("iskonto_orani_2", 0),
                iskonto3=veri.get("iskonto_orani_3", 0),
                kdv_orani=veri.get("kdv_orani", 0),
            )
            lot = veri.get("lot_no") or ""
            lot_girisi = veri.get("lot_girisi") or lot
            isk_metin = iskonto_goster_metin(
                veri.get("iskonto_orani", 0),
                veri.get("iskonto_orani_2", 0),
                veri.get("iskonto_orani_3", 0),
                bos_goster="",
            )
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                veri.get("barkod", ""),
                veri["urun_kodu"],
                veri["urun_adi"],
                veri.get("aciklama", ""),
                miktar,
                veri.get("birim", "Adet"),
                para_goster(fiyat),
                isk_metin,
                kdv_oran_metni(veri.get("kdv_orani", 0)),
                para_goster(h["net_birim_fiyat"]),
                lot,
                lot_girisi,
                para_goster(h["net_tutar"]),
                veri.get("siparis_miktar", 0),
                veri.get("irsaliye_miktar", 0),
                miktar,
            ))
        self._toplamlari_guncelle()

    def _bakiye_guncelle(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            self.mevcut_borc = Decimal("0")
            self._readonly_yaz("mevcut_bakiye", "0,00 TL")
            self._toplamlari_guncelle(Decimal("0"))
            return
        ozet = AlisFaturasiService.bakiye_ozeti(
            tedarikci.id, Decimal("0"), None, self.fatura.fatura_no if self.fatura else None
        )
        self.mevcut_borc = ozet["bakiye"]
        self._readonly_yaz("mevcut_bakiye", para_goster(self.mevcut_borc))
        self._toplamlari_guncelle(self.mevcut_borc)
        self.lot_oner()

    def _alis_odeme_ozet_yenile(self):
        odeme = sum((decimal(o["tutar"], "Ödeme") for o in self.odemeler), Decimal("0"))
        net = getattr(self, "_alis_net_toplam", Decimal("0"))
        kalan = net - odeme
        if hasattr(self, "odeme_ozet"):
            self.odeme_ozet.configure(
                text=f"Ödenen: {para_goster(odeme)} | Kalan: {para_goster(kalan)}"
            )

    def _toplamlari_guncelle(self, borc=None):
        """Satırlardan doğal alış fatura toplamlarını yeniden hesapla."""
        if not getattr(self, "_fatura_yukleniyor", False):
            self._fatura_form_kirli = True
        satirlar_hesap = []
        for veri in self.satirlar:
            satirlar_hesap.append({
                "miktar": veri.get("miktar", 0),
                "birim_fiyat": veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0)),
                "iskonto_orani": veri.get("iskonto_orani", 0),
                "iskonto_orani_2": veri.get("iskonto_orani_2", 0),
                "iskonto_orani_3": veri.get("iskonto_orani_3", 0),
                "kdv_orani": veri.get("kdv_orani", 0),
            })
        toplam = AlisFaturasiService.toplam(satirlar_hesap)
        satir_genel = toplam["genel_toplam"]
        self._alis_satir_brut = satir_genel
        self._alis_net_toplam = satir_genel
        if hasattr(self, "satir_ozet"):
            self.satir_ozet.configure(
                text=(
                    f"Ara Toplam: {para_goster(toplam['ara_toplam'])} | "
                    f"İskonto: {para_goster(toplam['iskonto'])} | "
                    f"KDV: {para_goster(toplam['kdv'])} | "
                    f"Genel: {para_goster(satir_genel)}"
                )
            )
        if getattr(self, "_alis_brut_lbl", None) is not None:
            try:
                self._alis_brut_lbl.configure(text=para_goster(satir_genel))
            except tk.TclError:
                pass
        if getattr(self, "_alis_net_lbl", None) is not None:
            try:
                self._alis_net_lbl.configure(text=para_goster(satir_genel))
            except tk.TclError:
                pass
        try:
            self._alis_odeme_ozet_yenile()
        except Exception:
            pass

    def odeme_ekle(self):
        dialog = AlisSiparisOdemeDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler.append(dialog.result)
            self._odeme_listesini_yenile()

    def odeme_duzenle(self):
        secim = self.odeme_tablosu.selection()
        if not secim:
            return
        idx = int(secim[0])
        dialog = AlisSiparisOdemeDialog(self, self.odemeler[idx])
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler[idx] = dialog.result
            self._odeme_listesini_yenile()

    def odeme_kaldir(self):
        secim = self.odeme_tablosu.selection()
        if secim:
            self.odemeler.pop(int(secim[0]))
            self._odeme_listesini_yenile()

    def _odeme_listesini_yenile(self):
        for item in self.odeme_tablosu.get_children():
            self.odeme_tablosu.delete(item)
        for sira, o in enumerate(self.odemeler):
            self.odeme_tablosu.insert("", "end", iid=str(sira), values=(
                o["odeme_tarihi"].strftime("%d.%m.%Y"),
                para_goster(decimal(o["tutar"], "Tutar")),
                o["odeme_sekli"],
                o.get("hesap", ""),
                o.get("aciklama", ""),
            ))
        self._toplamlari_guncelle()

    def _siparis_yukle(self, siparis):
        self.kaynak_siparis = siparis
        self._tedarikci_sec(siparis.cari)
        self.siparis_no.delete(0, "end")
        self.siparis_no.insert(0, siparis.siparis_no)
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.faturalanan_miktar
            if acik <= 0:
                continue
            self.satirlar.append({
                "siparis_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": satir.aciklama or "",
                "miktar": acik,
                "birim": satir.birim,
                "birim_fiyat": satir.birim_alis_fiyati,
                "birim_alis_fiyati": satir.birim_alis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
                "lot_no": "",
                "lot_girisi": "",
                "siparis_miktar": satir.miktar,
                "irsaliye_miktar": satir.irsaliyelenen_miktar,
                "faturalanan_miktar": satir.faturalanan_miktar,
            })
        if not self.satirlar:
            messagebox.showinfo("Fatura", "Bu siparişte faturalanacak açık miktar kalmadı.", parent=self)
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _irsaliyeyi_doldur(self, irsaliye):
        self.kaynak_irsaliye = irsaliye
        self._tedarikci_sec(irsaliye.cari)
        self.irsaliye_no.delete(0, "end")
        self.irsaliye_no.insert(0, irsaliye.irsaliye_no)
        if irsaliye.siparis:
            self.kaynak_siparis = irsaliye.siparis
            self.siparis_no.delete(0, "end")
            self.siparis_no.insert(0, irsaliye.siparis.siparis_no)
        self.satirlar.clear()
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
                "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
                "lot_no": "",
                "lot_girisi": "",
                "siparis_miktar": 0,
                "irsaliye_miktar": kalan,
                "faturalanan_miktar": 0,
            })
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _faturayi_doldur(self):
        self._fatura_yukleniyor = True
        try:
            fatura = self.fatura
            self._tedarikci_sec(fatura.cari)
            self._entry_yaz("fatura_tarihi", tarih_goster(fatura.fatura_tarihi))
            self._entry_yaz(
                "islem_saati",
                saat_varsayilan(fatura.islem_saati or fatura.olusturma_tarihi.strftime("%H:%M")),
            )
            self._entry_yaz("vade_tarihi", tarih_goster(fatura.vade_tarihi))
            self.girdiler["vade_gunu"].delete(0, "end")
            self.girdiler["vade_gunu"].insert(0, str(fatura.vade_gunu or 0))
            self.durum.configure(state="readonly")
            self.durum.set(fatura.durum)
            self.durum.configure(state="disabled")
            self._entry_yaz("aciklama", fatura.aciklama or "")
            self.siparis_no.delete(0, "end")
            self.siparis_no.insert(0, fatura.siparis.siparis_no if fatura.siparis else "")
            self.irsaliye_no.delete(0, "end")
            self.irsaliye_no.insert(0, fatura.irsaliye.irsaliye_no if fatura.irsaliye else "")
            if fatura.depo:
                self.depo.set(fatura.depo)
            self.dokuman.delete(0, "end")
            self.dokuman.insert(0, fatura.dokuman_yolu or "")
            self.satirlar.clear()
            fatura_pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
            for satir in fatura.satirlar:
                bf = satir.birim_fiyat
                bf_doviz = getattr(satir, "birim_fiyat_doviz", None) or 0
                if fatura_pb != "TRY" and bf_doviz:
                    bf = bf_doviz
                self.satirlar.append({
                    "siparis_satiri_id": satir.siparis_satiri_id,
                    "irsaliye_satiri_id": satir.irsaliye_satiri_id,
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "barkod": satir.barkod or "",
                    "aciklama": satir.aciklama or "",
                    "miktar": satir.miktar,
                    "birim": satir.birim,
                    "birim_fiyat": bf,
                    "birim_alis_fiyati": bf,
                    "birim_fiyat_doviz": bf_doviz or None,
                    "iskonto_orani": satir.iskonto_orani,
                    "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                    "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                    "kdv_orani": satir.kdv_orani,
                    "lot_no": satir.lot_no or "",
                    "lot_girisi": satir.lot_girisi or satir.lot_no or "",
                    "siparis_miktar": satir.miktar if satir.siparis_satiri_id else 0,
                    "irsaliye_miktar": satir.miktar if satir.irsaliye_satiri_id else 0,
                    "faturalanan_miktar": satir.miktar,
                })
            self.odemeler.clear()
            if fatura.odeme_tutari:
                self.odemeler.append({
                    "odeme_tarihi": fatura.fatura_tarihi,
                    "tutar": fatura.odeme_tutari,
                    "odeme_sekli": fatura.odeme_sekli or ODEME_SEKILLERI[0],
                    "hesap": fatura.odeme_hesabi or "",
                    "aciklama": "Fatura ödemesi",
                })
            self._bakiye_guncelle()
            self._satir_listesini_yenile()
            self._odeme_listesini_yenile()
            # Legacy override yok; toplam satırlardan
            self._toplamlari_guncelle()
        finally:
            self._fatura_yukleniyor = False
            self._fatura_form_kirli = False

    def kaydet(self):
        try:
            tedarikci = self.tedarikci_map.get(self.tedarikci.get())
            if not tedarikci:
                raise ValueError("Aktif bir tedarikçi seçin.")
            if not self.satirlar:
                raise ValueError("En az bir fatura satırı ekleyin.")
            satirlar_hesap = [
                {
                    **dict(s),
                    "birim_fiyat": s.get("birim_alis_fiyati", s.get("birim_fiyat", 0)),
                }
                for s in self.satirlar
            ]
            satir_genel = AlisFaturasiService.toplam(satirlar_hesap)["genel_toplam"]
            self._alis_satir_brut = satir_genel
            self._alis_net_toplam = satir_genel
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get())
            satirlar = []
            for satir in self.satirlar:
                veri = dict(satir)
                if not veri.get("lot_no"):
                    veri["lot_no"] = StokService.otomatik_lot_no(tedarikci.unvan, fatura_tarihi)
                veri["birim_fiyat"] = veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0))
                if veri.get("birim_fiyat_doviz") in (None, "", 0, "0"):
                    pb = getattr(self, "_doviz_para_birimi", None)
                    if pb and (pb.get() or "TRY").upper() != "TRY":
                        veri["birim_fiyat_doviz"] = veri["birim_fiyat"]
                satirlar.append(veri)
            odeme_tutari = sum((decimal(o["tutar"], "Ödeme") for o in self.odemeler), Decimal("0"))
            ilk_odeme = self.odemeler[0] if self.odemeler else {}
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
                eslesen = next(
                    (s for s in AlisFaturasiService.acik_siparisler() if s.siparis_no == yazilan_siparis),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan sipariş numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("Sipariş numarası seçilen tedarikçiye ait değil.")
                siparis_id = eslesen.id
            if yazilan_irsaliye and not irsaliye_id:
                eslesen = next(
                    (i for i in AlisFaturasiService.acik_irsaliyeler() if i.irsaliye_no == yazilan_irsaliye),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan irsaliye numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("İrsaliye numarası seçilen tedarikçiye ait değil.")
                irsaliye_id = eslesen.id
            notlar = self.ayrintili_notlar.get("1.0", "end").strip()
            aciklama = self.girdiler["aciklama"].get().strip()
            if notlar:
                aciklama = f"{aciklama}\n{notlar}".strip() if aciklama else notlar
            veriler = {
                "fatura_no": self.girdiler["fatura_no"].get().strip(),
                "fatura_tarihi": fatura_tarihi,
                "islem_saati": islem_saati,
                "vade_tarihi": vade_tarihi,
                "cari_id": tedarikci.id,
                "siparis_id": siparis_id,
                "irsaliye_id": irsaliye_id,
                "depo": self.depo.get(),
                "odeme_tutari": odeme_tutari,
                "odeme_sekli": ilk_odeme.get("odeme_sekli"),
                "odeme_hesabi": ilk_odeme.get("hesap"),
                "aciklama": aciklama or None,
                "dokuman_yolu": self.dokuman.get().strip() or None,
                "row_version": int(getattr(self.fatura, "row_version", 1) or 1)
                if self.fatura
                else None,
                "tl_brut_toplam": getattr(self, "_alis_satir_brut", Decimal("0")),
                "tl_genel_toplam": getattr(self, "_alis_net_toplam", Decimal("0")),
                "genel_islem_turu": None,
                "genel_islem_orani": Decimal("0"),
                "genel_islem_tutari": Decimal("0"),
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            self.result = AlisFaturasiService.kaydet(
                veriler,
                satirlar,
                self.fatura.id if self.fatura else None,
            )
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return
        self.destroy()

    def faturayi_iptal_et(self):
        if not self.fatura:
            self.destroy()
            return
        if messagebox.askyesno("Faturayı iptal et", "Bu fatura iptal edilsin mi?", parent=self):
            try:
                AlisFaturasiService.iptal_et(self.fatura.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
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

        self.girdiler = {"iade_tarihi": self.tarih}
        doviz_cerceve = ttk.LabelFrame(self, text="DÖVİZ / KUR", padding=6)
        doviz_cerceve.pack(fill="x", padx=10, pady=4)
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, doviz_cerceve)
        if iade:
            doviz_verilerini_doldur(self, iade)
        elif kaynak_fatura:
            doviz_verilerini_doldur(self, kaynak_fatura)

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
                "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
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
                "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
            })
        self._satirlari_yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci or not self.satirlar:
            messagebox.showwarning("Eksik", "Tedarikçi ve satırlar gerekli.", parent=self)
            return
        try:
            veriler = {
                "iade_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "kaynak_fatura_id": self.kaynak.id if self.kaynak else None,
                "depo": self.depo.get() or "ANA DEPO",
                "aciklama": self.aciklama.get().strip() or None,
                "iade_odeme_tutari": self.iade_odeme_tutari.get(),
                "iade_odeme_sekli": self.iade_odeme_sekli.get() or None,
                "iade_odeme_hesabi": self.iade_odeme_hesabi.get().strip() or None,
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            AlisIadeFaturasiService.kaydet(
                veriler,
                self.satirlar,
                self.iade.id if self.iade else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()
