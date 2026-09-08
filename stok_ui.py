"""Stok kartı diyalogları (Pazartesi stok modülünün geri kurulumu)."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.satis_siparisi_service import decimal
from database.stok_service import (
    ESKI_FIYAT_ESLEME,
    KART_TURLERI,
    SATIS_FIYAT_ADLARI,
    STOK_FIYAT_ADLARI,
    StokService,
    fabrika_fiyati_hesapla,
)

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


class StokAciklamaDialog(tk.Toplevel):
    def __init__(self, parent, metin=""):
        super().__init__(parent)
        self.result = None
        self.title("Stok Açıklama")
        self.geometry("560x360")
        self.transient(parent)
        self.grab_set()
        ttk.Label(self, text="Stok açıklaması").pack(anchor="w", padx=12, pady=(12, 4))
        self.metin = tk.Text(self, wrap="word", width=64, height=14)
        self.metin.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.metin.insert("1.0", metin or "")
        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(butonlar, text="Tamam", command=self.tamam).pack(side="right", padx=(0, 8))

    def tamam(self):
        self.result = self.metin.get("1.0", "end").strip()
        self.destroy()


class StokBirimlerDialog(tk.Toplevel):
    """Birimler birbirine çevrilebilir: 1 Koli = 20 Paket, 1 Paket = 1000 Adet."""

    def __init__(self, parent, ana_birim="Adet", birimler=None):
        super().__init__(parent)
        self.result = None
        self.ana_birim = (ana_birim or "Adet").strip() or "Adet"
        self.title("Stok Birimleri")
        self.geometry("760x460")
        self.transient(parent)
        self.grab_set()
        ttk.Label(
            self,
            text=(
                f"Ana birim: {self.ana_birim} — Örnek: 1 Koli = 20 Paket, 1 Paket = 1000 {self.ana_birim}. "
                "Fatura ve fiyatlandırmada bu çevirimler kullanılır."
            ),
            wraplength=720,
        ).pack(anchor="w", padx=12, pady=(12, 6))
        birim_secenekleri = list(
            dict.fromkeys([*BIRIM_SECENEKLERI, self.ana_birim, *StokService.secenekleri_listele("birim")])
        )
        form = ttk.Frame(self, padding=8)
        form.pack(fill="x", padx=4)
        ttk.Label(form, text="1").grid(row=0, column=0, padx=4)
        self.birim = ttk.Combobox(form, values=birim_secenekleri, width=14)
        self.birim.grid(row=0, column=1, padx=4)
        ttk.Label(form, text="=").grid(row=0, column=2, padx=4)
        self.carpan = ttk.Entry(form, width=12)
        self.carpan.grid(row=0, column=3, padx=4)
        self.hedef = ttk.Combobox(form, values=birim_secenekleri, width=14)
        self.hedef.set(self.ana_birim)
        self.hedef.grid(row=0, column=4, padx=4)
        ttk.Button(form, text="Ekle", command=self.ekle).grid(row=0, column=5, padx=4)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=8)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("birim", "carpan", "hedef", "ana"),
            show="headings",
            selectmode="browse",
        )
        self.tablo.heading("birim", text="Birim")
        self.tablo.heading("carpan", text="Çarpan")
        self.tablo.heading("hedef", text="Hedef Birim")
        self.tablo.heading("ana", text=f"= kaç {self.ana_birim}")
        self.tablo.column("birim", width=120)
        self.tablo.column("carpan", width=90)
        self.tablo.column("hedef", width=120)
        self.tablo.column("ana", width=140)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        for kayit in birimler or []:
            if len(kayit) >= 3:
                birim_adi, carpan, hedef = kayit[0], kayit[1], kayit[2]
            else:
                birim_adi, carpan = kayit[0], kayit[1]
                hedef = self.ana_birim
            self.tablo.insert("", "end", values=(birim_adi, carpan, hedef, ""))
        self._ana_carpanlari_yenile()
        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(alt, text="Seçiliyi Sil", command=self.sil).pack(side="left")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=(0, 8))

    def _donusumler(self):
        satirlar = []
        for item in self.tablo.get_children():
            degerler = self.tablo.item(item, "values")
            satirlar.append((degerler[0], degerler[1], degerler[2], item))
        return satirlar

    def _ana_carpan_haritasi(self):
        """Zincir çevirimleri ana birime indirger."""
        faktor = {self.ana_birim.casefold(): Decimal("1")}
        ad_esleme = {self.ana_birim.casefold(): self.ana_birim}
        donusumler = []
        for birim_adi, carpan, hedef, _item in self._donusumler():
            try:
                carpan_d = decimal(carpan, "Çarpan", Decimal("0.000001"))
            except ValueError:
                continue
            donusumler.append((birim_adi.strip(), carpan_d, hedef.strip()))
            ad_esleme[birim_adi.strip().casefold()] = birim_adi.strip()
            ad_esleme[hedef.strip().casefold()] = hedef.strip()
        # Tekrarlı çözüm: bilinen hedef üzerinden kaynak birimi üret
        for _ in range(len(donusumler) + 2):
            ilerleme = False
            for kaynak, carpan_d, hedef in donusumler:
                k = kaynak.casefold()
                h = hedef.casefold()
                if h in faktor and k not in faktor:
                    faktor[k] = carpan_d * faktor[h]
                    ilerleme = True
                elif k in faktor and h not in faktor and carpan_d != 0:
                    faktor[h] = faktor[k] / carpan_d
                    ilerleme = True
            if not ilerleme:
                break
        return {
            ad_esleme.get(k, k): v
            for k, v in faktor.items()
        }

    def _ana_carpanlari_yenile(self):
        harita = self._ana_carpan_haritasi()
        for item in self.tablo.get_children():
            birim_adi, carpan, hedef, _eski = self.tablo.item(item, "values")
            ana = harita.get(birim_adi.strip())
            metin = ""
            if ana is not None:
                metin = f"{ana:f}".rstrip("0").rstrip(".")
            self.tablo.item(item, values=(birim_adi, carpan, hedef, metin))

    def ekle(self):
        birim = self.birim.get().strip()
        carpan = self.carpan.get().strip()
        hedef = self.hedef.get().strip() or self.ana_birim
        if not birim or not carpan:
            messagebox.showwarning("Eksik bilgi", "Birim ve çarpan girin.", parent=self)
            return
        if birim.casefold() == hedef.casefold():
            messagebox.showwarning("Geçersiz", "Birim ile hedef birim aynı olamaz.", parent=self)
            return
        try:
            decimal(carpan, "Çarpan", Decimal("0.000001"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz çarpan", str(hata), parent=self)
            return
        self.tablo.insert("", "end", values=(birim, carpan, hedef, ""))
        self._ana_carpanlari_yenile()
        self.birim.set("")
        self.carpan.delete(0, "end")

    def sil(self):
        for item in self.tablo.selection():
            self.tablo.delete(item)
        self._ana_carpanlari_yenile()

    def tamam(self):
        harita = self._ana_carpan_haritasi()
        sonuc = []
        for birim_adi, _carpan, _hedef, _item in self._donusumler():
            ana = harita.get(birim_adi.strip())
            if ana is None:
                messagebox.showerror(
                    "Çevirim eksik",
                    f"'{birim_adi}' birimi ana birime ({self.ana_birim}) bağlanamadı.\n"
                    f"Zinciri tamamlayın (ör. 1 Paket = 1000 {self.ana_birim}).",
                    parent=self,
                )
                return
            if birim_adi.strip().casefold() == self.ana_birim.casefold():
                continue
            sonuc.append((birim_adi.strip(), f"{ana:f}".rstrip("0").rstrip(".")))
        self.result = sonuc
        self.destroy()


class StokResimlerDialog(tk.Toplevel):
    def __init__(self, parent, stok_kodu="", resimler=None):
        super().__init__(parent)
        self.result = None
        self.stok_kodu = stok_kodu or "yeni"
        self.title("Stok Resimleri")
        self.geometry("700x420")
        self.transient(parent)
        self.grab_set()
        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Button(ust, text="Resim Ekle", command=self.ekle).pack(side="left")
        ttk.Button(ust, text="Seçiliyi Sil", command=self.sil).pack(side="left", padx=8)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=8)
        self.tablo = ttk.Treeview(cerceve, columns=("yol", "aciklama"), show="headings", selectmode="browse")
        self.tablo.heading("yol", text="Dosya")
        self.tablo.heading("aciklama", text="Açıklama")
        self.tablo.column("yol", width=420)
        self.tablo.column("aciklama", width=180)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        for kayit in (resimler or []):
            self.tablo.insert("", "end", values=(kayit.get("dosya_yolu", ""), kayit.get("aciklama") or ""))
        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=(0, 8))

    def ekle(self):
        yol = filedialog.askopenfilename(
            parent=self,
            title="Stok resmi seç",
            filetypes=[("Resimler", "*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"), ("Tümü", "*.*")],
        )
        if not yol:
            return
        try:
            hedef = StokService.resim_kopyala(self.stok_kodu, yol)
        except ValueError as hata:
            messagebox.showerror("Resim eklenemedi", str(hata), parent=self)
            return
        aciklama = simpledialog.askstring("Açıklama", "Resim açıklaması (opsiyonel):", parent=self) or ""
        self.tablo.insert("", "end", values=(hedef, aciklama))

    def sil(self):
        for item in self.tablo.selection():
            self.tablo.delete(item)

    def tamam(self):
        self.result = [
            {"dosya_yolu": self.tablo.item(i, "values")[0], "aciklama": self.tablo.item(i, "values")[1]}
            for i in self.tablo.get_children()
        ]
        self.destroy()


class StokMuhasebeDialog(tk.Toplevel):
    ALANLAR = (
        ("Stok Hesap Kodu", "muhasebe_stok_kodu"),
        ("Alış Hesap Kodu", "muhasebe_alis_kodu"),
        ("Satış Hesap Kodu", "muhasebe_satis_kodu"),
        ("Maliyet Hesap Kodu", "muhasebe_maliyet_kodu"),
        ("KDV Alış Hesap Kodu", "muhasebe_kdv_alis_kodu"),
        ("KDV Satış Hesap Kodu", "muhasebe_kdv_satis_kodu"),
    )

    def __init__(self, parent, degerler=None):
        super().__init__(parent)
        self.result = None
        self.title("Muhasebe Kodları")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.alanlar = {}
        degerler = degerler or {}
        for satir, (etiket, alan) in enumerate(self.ALANLAR):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            giris = ttk.Entry(self, width=28)
            giris.grid(row=satir, column=1, padx=12, pady=6)
            giris.insert(0, degerler.get(alan) or "")
            self.alanlar[alan] = giris
        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(self.ALANLAR), column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Tamam", command=self.tamam).pack(side="right")

    def tamam(self):
        self.result = {alan: giris.get().strip() for alan, giris in self.alanlar.items()}
        self.destroy()


class StokBarkodlarDialog(tk.Toplevel):
    """Sabit 5 barkod satırı: birim + fiyat görünür; 1. barkod silinmez / üzerine yazılmaz."""

    OZEL_FIYAT = "Özel Fiyat"
    SATIR_SAYISI = 5

    def __init__(
        self,
        parent,
        ana_birim="Adet",
        birimler=None,
        barkodlar=None,
        satis_fiyat_1="0",
        fiyatlar=None,
        ekstra_birimler=None,
    ):
        super().__init__(parent)
        self.result = None
        self.ana_birim = (ana_birim or "Adet").strip() or "Adet"
        self.satis_fiyat_1 = (satis_fiyat_1 or "0").strip() or "0"
        self.fiyatlar = dict(fiyatlar or {})
        if "SATIŞ FİYATI 1" not in self.fiyatlar and self.satis_fiyat_1:
            self.fiyatlar["SATIŞ FİYATI 1"] = self.satis_fiyat_1
        self.title("Barkod Bilgileri — 5 Satır")
        self.geometry("980x420")
        self.minsize(860, 360)
        self.transient(parent)
        self.grab_set()

        self.birim_secenekleri = list(
            dict.fromkeys(
                [
                    *(x for x in [self.ana_birim, *(ekstra_birimler or [])] if x),
                    *[b[0] for b in (birimler or []) if b and b[0]],
                    *BIRIM_SECENEKLERI,
                    *StokService.secenekleri_listele("birim"),
                ]
            )
        )
        self.fiyat_adi_secenekleri = list(
            dict.fromkeys([*SATIS_FIYAT_ADLARI, *STOK_FIYAT_ADLARI, *self.fiyatlar.keys(), self.OZEL_FIYAT])
        )

        ttk.Label(
            self,
            text=(
                "5 ayrı barkod satırı: her satırda barkod, birim ve fiyat görünür. "
                "1. barkod silinemez ve yeni EAN-13 eski 1. barkodu değiştirmez."
            ),
            wraplength=940,
        ).pack(anchor="w", padx=12, pady=(12, 6))

        tablo = ttk.Frame(self, padding=8)
        tablo.pack(fill="both", expand=True, padx=4)
        for kolon, metin, genislik in (
            (0, "No", 4),
            (1, "Barkod", 18),
            (2, "Birim", 12),
            (3, "Fiyat Türü", 16),
            (4, "Fiyat", 12),
            (5, "Açıklama", 22),
        ):
            ttk.Label(tablo, text=metin, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=kolon, padx=4, pady=(0, 6), sticky="w"
            )

        mevcut = list(barkodlar or [])
        self.satirlar = []
        for sira in range(1, self.SATIR_SAYISI + 1):
            kayit = mevcut[sira - 1] if sira - 1 < len(mevcut) else {}
            varsayilan_fiyat_adi = SATIS_FIYAT_ADLARI[sira - 1] if sira <= len(SATIS_FIYAT_ADLARI) else self.OZEL_FIYAT
            fiyat_adi = (kayit.get("fiyat_adi") or "").strip() or varsayilan_fiyat_adi
            fiyat = (kayit.get("fiyat") or "").strip()
            if not fiyat:
                fiyat = (self.fiyatlar.get(fiyat_adi) or self.satis_fiyat_1 if sira == 1 else "0") or "0"
            aciklama = (kayit.get("aciklama") or "").strip() or f"{sira}. Barkod"
            birim = (kayit.get("birim") or self.ana_birim).strip() or self.ana_birim
            barkod_deger = (kayit.get("barkod") or "").strip()

            ttk.Label(tablo, text=str(sira)).grid(row=sira, column=0, padx=4, pady=3, sticky="w")
            barkod_w = ttk.Entry(tablo, width=20)
            barkod_w.insert(0, barkod_deger)
            barkod_w.grid(row=sira, column=1, padx=4, pady=3, sticky="w")
            if sira == 1:
                barkod_w.configure(style="TEntry")

            birim_w = ttk.Combobox(tablo, values=self.birim_secenekleri, width=12)
            birim_w.set(birim)
            birim_w.grid(row=sira, column=2, padx=4, pady=3, sticky="w")

            fiyat_adi_w = ttk.Combobox(tablo, values=self.fiyat_adi_secenekleri, width=18)
            fiyat_adi_w.set(fiyat_adi)
            fiyat_adi_w.grid(row=sira, column=3, padx=4, pady=3, sticky="w")
            fiyat_adi_w.bind(
                "<<ComboboxSelected>>",
                lambda _e, i=sira - 1: self._satir_fiyat_turu_degisti(i),
            )

            fiyat_w = ttk.Entry(tablo, width=12)
            fiyat_w.insert(0, str(fiyat))
            fiyat_w.grid(row=sira, column=4, padx=4, pady=3, sticky="w")

            aciklama_w = ttk.Entry(tablo, width=24)
            aciklama_w.insert(0, aciklama)
            aciklama_w.grid(row=sira, column=5, padx=4, pady=3, sticky="ew")

            self.satirlar.append(
                {
                    "sira": sira,
                    "barkod": barkod_w,
                    "birim": birim_w,
                    "fiyat_adi": fiyat_adi_w,
                    "fiyat": fiyat_w,
                    "aciklama": aciklama_w,
                }
            )

        tablo.columnconfigure(5, weight=1)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(alt, text="1. Barkoda EAN-13 (yalnız boşsa)", command=self.birinciye_ean13).pack(side="left")
        ttk.Button(alt, text="Sonraki Boş Satıra EAN-13", command=self.sonraki_bos_ean13).pack(side="left", padx=8)
        ttk.Button(alt, text="Boş Satırları Doldur (2–5)", command=self.boslari_doldur).pack(side="left", padx=8)
        ttk.Button(alt, text="Seçili Satırı Temizle (2–5)", command=self.satir_temizle).pack(side="left", padx=8)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=(0, 8))

        self._odak_satir = 0
        for i, satir in enumerate(self.satirlar):
            for anahtar in ("barkod", "birim", "fiyat_adi", "fiyat", "aciklama"):
                satir[anahtar].bind("<FocusIn>", lambda _e, idx=i: setattr(self, "_odak_satir", idx))

    def _kart_fiyati(self, fiyat_adi):
        parent = self.master
        if parent is not None and getattr(parent, "fiyat_alanlari", None) and fiyat_adi in parent.fiyat_alanlari:
            tutar = parent.fiyat_alanlari[fiyat_adi].get().strip()
            if tutar:
                return tutar
        return (self.fiyatlar.get(fiyat_adi) or "").strip() or "0"

    def _satir_fiyat_turu_degisti(self, index):
        satir = self.satirlar[index]
        ad = satir["fiyat_adi"].get().strip()
        if not ad or ad == self.OZEL_FIYAT:
            return
        tutar = self._kart_fiyati(ad)
        satir["fiyat"].delete(0, "end")
        satir["fiyat"].insert(0, tutar)

    def _haric_barkodlar(self):
        return [s["barkod"].get().strip() for s in self.satirlar if s["barkod"].get().strip()]

    def _stok_id(self):
        parent = self.master
        if parent is not None and getattr(parent, "stok", None) is not None:
            return parent.stok.id
        return None

    def _ean13_uret(self):
        return StokService.ean13_olustur(stok_id=self._stok_id(), haric_barkodlar=self._haric_barkodlar())

    def birinciye_ean13(self):
        satir = self.satirlar[0]
        if satir["barkod"].get().strip():
            messagebox.showinfo(
                "1. Barkod korumalı",
                "1. barkod zaten dolu. Yeni EAN-13 eski barkodu silmez.\n"
                "İsterseniz 'Sonraki Boş Satıra EAN-13' kullanın.",
                parent=self,
            )
            return
        try:
            barkod = self._ean13_uret()
        except ValueError as hata:
            messagebox.showerror("EAN-13", str(hata), parent=self)
            return
        fiyat_adi = "SATIŞ FİYATI 1"
        satir["barkod"].insert(0, barkod)
        satir["birim"].set(self.ana_birim)
        satir["fiyat_adi"].set(fiyat_adi)
        satir["fiyat"].delete(0, "end")
        satir["fiyat"].insert(0, self._kart_fiyati(fiyat_adi))
        if not satir["aciklama"].get().strip():
            satir["aciklama"].insert(0, "1. Barkod (EAN-13)")
        messagebox.showinfo("EAN-13", f"1. barkod yazıldı:\n{barkod}", parent=self)

    def sonraki_bos_ean13(self):
        hedef = None
        for satir in self.satirlar:
            if not satir["barkod"].get().strip():
                hedef = satir
                break
        if hedef is None:
            messagebox.showinfo(
                "Barkod",
                "5 satırın hepsi dolu. Yeni barkod eklemek için önce 2–5. satırdan birini temizleyin.\n"
                "1. barkod silinemez.",
                parent=self,
            )
            return
        try:
            barkod = self._ean13_uret()
        except ValueError as hata:
            messagebox.showerror("EAN-13", str(hata), parent=self)
            return
        sira = hedef["sira"]
        fiyat_adi = SATIS_FIYAT_ADLARI[sira - 1] if sira <= len(SATIS_FIYAT_ADLARI) else self.OZEL_FIYAT
        hedef["barkod"].insert(0, barkod)
        if not hedef["birim"].get().strip():
            hedef["birim"].set(self.ana_birim)
        if not hedef["fiyat_adi"].get().strip():
            hedef["fiyat_adi"].set(fiyat_adi)
        else:
            fiyat_adi = hedef["fiyat_adi"].get().strip()
        if not hedef["fiyat"].get().strip() or hedef["fiyat"].get().strip() == "0":
            hedef["fiyat"].delete(0, "end")
            hedef["fiyat"].insert(0, self._kart_fiyati(fiyat_adi))
        if not hedef["aciklama"].get().strip():
            hedef["aciklama"].insert(0, f"{sira}. Barkod (EAN-13)")
        messagebox.showinfo("EAN-13", f"{sira}. satıra barkod yazıldı:\n{barkod}", parent=self)

    def boslari_doldur(self):
        """2–5. boş satırlara EAN-13 üretir; 1. satıra dokunmaz."""
        eklenen = 0
        for satir in self.satirlar[1:]:
            if satir["barkod"].get().strip():
                continue
            try:
                barkod = self._ean13_uret()
            except ValueError as hata:
                messagebox.showerror("EAN-13", str(hata), parent=self)
                break
            sira = satir["sira"]
            fiyat_adi = SATIS_FIYAT_ADLARI[sira - 1] if sira <= len(SATIS_FIYAT_ADLARI) else self.OZEL_FIYAT
            satir["barkod"].insert(0, barkod)
            satir["birim"].set(satir["birim"].get().strip() or self.ana_birim)
            if not satir["fiyat_adi"].get().strip():
                satir["fiyat_adi"].set(fiyat_adi)
            else:
                fiyat_adi = satir["fiyat_adi"].get().strip()
            satir["fiyat"].delete(0, "end")
            satir["fiyat"].insert(0, self._kart_fiyati(fiyat_adi))
            if not satir["aciklama"].get().strip():
                satir["aciklama"].insert(0, f"{sira}. Barkod")
            eklenen += 1
        if eklenen:
            messagebox.showinfo("Barkod", f"{eklenen} boş satır EAN-13 ile dolduruldu. 1. barkod korundu.", parent=self)
        else:
            messagebox.showinfo("Barkod", "2–5. satırlarda boş barkod yok (veya 1. satır zaten ayrı).", parent=self)

    def satir_temizle(self):
        index = getattr(self, "_odak_satir", 0)
        if index <= 0:
            messagebox.showwarning(
                "1. Barkod korumalı",
                "1. barkod silinemez / temizlenemez.\n2–5. satırlardan birine tıklayıp temizleyin.",
                parent=self,
            )
            return
        satir = self.satirlar[index]
        satir["barkod"].delete(0, "end")
        satir["fiyat"].delete(0, "end")
        satir["fiyat"].insert(0, "0")
        satir["aciklama"].delete(0, "end")
        satir["aciklama"].insert(0, f"{satir['sira']}. Barkod")

    def tamam(self):
        sonuc = []
        gorulen = set()
        for satir in self.satirlar:
            barkod = satir["barkod"].get().strip()
            if not barkod:
                if satir["sira"] == 1:
                    # 1. satır boş olabilir (henüz üretilmemiş); kaydetme
                    continue
                continue
            if barkod in gorulen:
                messagebox.showerror("Barkod", f"Aynı barkod birden fazla satırda: {barkod}", parent=self)
                return
            gorulen.add(barkod)
            fiyat = satir["fiyat"].get().strip() or "0"
            try:
                decimal(fiyat, "Barkod fiyatı", Decimal("0"))
            except ValueError as hata:
                messagebox.showerror("Fiyat", f"{satir['sira']}. satır: {hata}", parent=self)
                return
            fiyat_adi = satir["fiyat_adi"].get().strip()
            if fiyat_adi == self.OZEL_FIYAT:
                fiyat_adi = ""
            sonuc.append(
                {
                    "barkod": barkod,
                    "birim": satir["birim"].get().strip() or self.ana_birim,
                    "fiyat_adi": fiyat_adi,
                    "fiyat": fiyat,
                    "aciklama": satir["aciklama"].get().strip() or f"{satir['sira']}. Barkod",
                }
            )
        # 1. barkod varsa listenin başında kalsın
        if sonuc and self.satirlar[0]["barkod"].get().strip():
            birinci = self.satirlar[0]["barkod"].get().strip()
            sonuc.sort(key=lambda k: 0 if k["barkod"] == birinci else 1)
        self.result = sonuc
        self.destroy()


class StokFiyatAnalizDialog(tk.Toplevel):
    def __init__(self, parent, stok_id):
        super().__init__(parent)
        self.title("Fiyat Analiz")
        self.geometry("820x480")
        self.transient(parent)
        self.grab_set()
        ttk.Label(
            self,
            text="Bu stok için alış ve satış fiyat değişiklikleri (yeniden eskiye).",
        ).pack(anchor="w", padx=12, pady=(12, 6))

        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=8)
        kolonlar = ("tarih", "fiyat_adi", "eski", "yeni")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (
            ("tarih", "Değişim Tarihi", 160),
            ("fiyat_adi", "Fiyat Adı", 160),
            ("eski", "Eski Tutar", 140),
            ("yeni", "Yeni Tutar", 140),
        ):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        if stok_id:
            for kayit in StokService.fiyat_gecmisi(stok_id):
                self.tablo.insert(
                    "",
                    "end",
                    values=(
                        kayit.degisim_tarihi.strftime("%d.%m.%Y %H:%M"),
                        kayit.fiyat_adi,
                        para_goster(kayit.eski_tutar) if kayit.eski_tutar is not None else "-",
                        para_goster(kayit.yeni_tutar),
                    ),
                )
        else:
            ttk.Label(self, text="Önce stok kartını kaydedin; sonraki fiyat değişiklikleri burada listelenir.").pack(
                anchor="w", padx=12
            )
        ttk.Button(self, text="Kapat", command=self.destroy).pack(anchor="e", padx=12, pady=12)


class StokHareketleriDialog(tk.Toplevel):
    def __init__(self, parent, stok):
        super().__init__(parent)
        self.stok = stok
        self.title(f"Stok Hareketleri — {stok.stok_kodu} / {stok.stok_adi}")
        self.geometry("980x560")
        self.minsize(820, 420)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Başlangıç (gg.aa.yyyy)").pack(side="left")
        self.baslangic = ttk.Entry(ust, width=12)
        self.baslangic.pack(side="left", padx=(6, 12))
        self.baslangic.insert(0, tarih_goster(date.today().replace(month=1, day=1)))
        ttk.Label(ust, text="Bitiş").pack(side="left")
        self.bitis = ttk.Entry(ust, width=12)
        self.bitis.pack(side="left", padx=(6, 12))
        self.bitis.insert(0, tarih_goster(date.today()))
        ttk.Button(ust, text="Listele", command=self.yenile).pack(side="left")
        ttk.Button(ust, text="Tümü", command=self.tumunu_goster).pack(side="left", padx=6)

        cerceve = ttk.Frame(self, padding=(10, 0))
        cerceve.pack(fill="both", expand=True)
        kolonlar = ("tarih", "tur", "belge", "depo", "lot", "miktar", "maliyet", "tutar")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for kolon, baslik, genislik in (
            ("tarih", "Tarih", 90),
            ("tur", "Hareket", 120),
            ("belge", "Belge No", 120),
            ("depo", "Depo", 110),
            ("lot", "Lot", 120),
            ("miktar", "Miktar", 90),
            ("maliyet", "Birim Maliyet", 110),
            ("tutar", "Tutar", 110),
        ):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik, anchor="w")
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        self.tablo.bind("<ButtonRelease-1>", self.evrak_ac)
        self.tablo.bind("<Return>", self.evrak_ac)

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(6, 0))
        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="Evrakı Aç", command=self.evrak_ac).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.yenile()

    def _tarih_oku(self, widget):
        metin = widget.get().strip()
        if not metin:
            return None
        return datetime.strptime(metin, "%d.%m.%Y").date()

    def tumunu_goster(self):
        self.baslangic.delete(0, "end")
        self.bitis.delete(0, "end")
        self.yenile()

    def yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        try:
            baslangic = self._tarih_oku(self.baslangic)
            bitis = self._tarih_oku(self.bitis)
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return
        if baslangic and bitis and baslangic > bitis:
            messagebox.showwarning("Tarih", "Başlangıç tarihi bitişten sonra olamaz.", parent=self)
            return
        hareketler = StokService.stok_hareketleri(self.stok.id, baslangic, bitis)
        giris = Decimal("0")
        cikis = Decimal("0")
        for sira, h in enumerate(hareketler):
            self.tablo.insert(
                "",
                "end",
                iid=f"{sira}:{h['belge_no']}:{h['hareket_turu']}",
                values=(
                    tarih_goster(h["tarih"]),
                    h["hareket_turu"],
                    h["belge_no"],
                    h["depo"],
                    h["lot_no"],
                    h["miktar"],
                    para_goster(h["birim_maliyet"]),
                    para_goster(h["tutar"]),
                ),
            )
            if h["hareket_turu"] in ("GİRİŞ", "FATURA GİRİŞ", "İADE GİRİŞ"):
                giris += h["miktar"]
            elif h["hareket_turu"] in ("FATURA ÇIKIŞ", "ÇIKIŞ", "TRANSFER ÇIKIŞ"):
                cikis += h["miktar"]
        self.ozet.configure(
            text=f"{len(hareketler)} hareket | Toplam giriş: {giris} | Toplam çıkış: {cikis} | Satıra tıklayınca ilgili evrak açılır"
        )

    def evrak_ac(self, _event=None):
        if getattr(self, "_evrak_aciliyor", False):
            return
        secim = self.tablo.selection()
        if not secim:
            return
        degerler = self.tablo.item(secim[0], "values")
        if not degerler or len(degerler) < 3:
            return
        hareket_turu = degerler[1]
        belge_no = degerler[2]
        bulunan = StokService.belge_bul(belge_no, hareket_turu)
        if not bulunan:
            messagebox.showinfo(
                "Evrak",
                f"{hareket_turu} / {belge_no} için açılabilir evrak bulunamadı.",
                parent=self,
            )
            return
        tur, kimlik = bulunan
        self._evrak_aciliyor = True
        try:
            if tur == "satis_fatura":
                from app import CariDialog, SatisFaturasiDialog
                from database.satis_faturasi_service import SatisFaturasiService
                fatura = SatisFaturasiService.getir(kimlik)
                if not fatura:
                    raise ValueError("Satış faturası bulunamadı.")
                dialog = SatisFaturasiDialog(
                    self,
                    fatura=fatura,
                    cari_ac=lambda cari: CariDialog(self, cari),
                )
                self.wait_window(dialog)
            elif tur == "alis_fatura":
                from alis_ui import AlisFaturasiDialog
                from database.alis_faturasi_service import AlisFaturasiService
                fatura = AlisFaturasiService.getir(kimlik)
                if not fatura:
                    raise ValueError("Alış faturası bulunamadı.")
                dialog = AlisFaturasiDialog(
                    self,
                    fatura=fatura,
                    cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"),
                )
                self.wait_window(dialog)
            elif tur == "satis_iade":
                from app import SatisIadeFaturasiDialog
                from database.satis_iade_faturasi_service import SatisIadeFaturasiService
                iade = SatisIadeFaturasiService.getir(kimlik)
                if not iade:
                    raise ValueError("Satış iade faturası bulunamadı.")
                dialog = SatisIadeFaturasiDialog(self, iade=iade)
                self.wait_window(dialog)
            elif tur == "alis_iade":
                from alis_ui import AlisIadeFaturasiDialog
                from database.alis_iade_faturasi_service import AlisIadeFaturasiService
                iade = AlisIadeFaturasiService.getir(kimlik)
                if not iade:
                    raise ValueError("Alış iade faturası bulunamadı.")
                dialog = AlisIadeFaturasiDialog(self, iade=iade)
                self.wait_window(dialog)
            elif tur == "stok_giris":
                messagebox.showinfo(
                    "Stok girişi",
                    f"Bu hareket manuel stok girişidir.\nBelge / Lot: {kimlik}",
                    parent=self,
                )
        except ValueError as hata:
            messagebox.showerror("Evrak açılamadı", str(hata), parent=self)
        finally:
            self._evrak_aciliyor = False


class StokKartiDialog(tk.Toplevel):
    FIYAT_ADLARI = STOK_FIYAT_ADLARI

    def __init__(self, parent, stok=None, baslangic=None):
        super().__init__(parent)
        self.stok = StokService.stok_getir(stok.id) if stok else None
        self.baslangic = baslangic or {}
        self.result = None
        self.title("Stok Kartını Düzenle" if stok else "Yeni Stok Kartı")
        self.geometry("1220x820")
        self.minsize(1020, 700)
        self.transient(parent)
        self.grab_set()

        self.aciklama = (self.stok.aciklama if self.stok else "") or ""
        self.birimler = [
            (b.birim_adi, str(b.carpan)) for b in (self.stok.birimler if self.stok else [])
        ]
        self.resimler = [
            {"dosya_yolu": r.dosya_yolu, "aciklama": r.aciklama or ""}
            for r in (self.stok.resimler if self.stok else [])
        ]
        self.barkodlar = [
            {
                "barkod": b.barkod,
                "birim": b.birim,
                "fiyat_adi": getattr(b, "fiyat_adi", None) or "",
                "fiyat": str(b.fiyat),
                "aciklama": b.aciklama or "",
            }
            for b in (self.stok.barkodlar if self.stok else [])
        ]
        if self.stok and not self.barkodlar and self.stok.barkod:
            self.barkodlar = [
                {
                    "barkod": self.stok.barkod,
                    "birim": self.stok.birim,
                    "fiyat_adi": "SATIŞ FİYATI 1",
                    "fiyat": "0",
                    "aciklama": "",
                }
            ]
        self.muhasebe = {
            "muhasebe_stok_kodu": getattr(self.stok, "muhasebe_stok_kodu", None) if self.stok else "",
            "muhasebe_alis_kodu": getattr(self.stok, "muhasebe_alis_kodu", None) if self.stok else "",
            "muhasebe_satis_kodu": getattr(self.stok, "muhasebe_satis_kodu", None) if self.stok else "",
            "muhasebe_maliyet_kodu": getattr(self.stok, "muhasebe_maliyet_kodu", None) if self.stok else "",
            "muhasebe_kdv_alis_kodu": getattr(self.stok, "muhasebe_kdv_alis_kodu", None) if self.stok else "",
            "muhasebe_kdv_satis_kodu": getattr(self.stok, "muhasebe_kdv_satis_kodu", None) if self.stok else "",
        }

        # Önce alt çubuk: Kaydet her zaman görünür kalsın
        kayit = ttk.Frame(self, padding=(12, 8, 12, 12))
        kayit.pack(side="bottom", fill="x")
        ttk.Button(kayit, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(kayit, text="KAYDET", width=18, command=self.kaydet).pack(side="right")

        ust = ttk.Frame(self, padding=12)
        ust.pack(side="top", fill="both", expand=True)
        sol = ttk.Frame(ust)
        sol.pack(side="left", fill="both", expand=True)
        sag = ttk.LabelFrame(ust, text="ENVANTER ÖZETİ", padding=14)
        sag.pack(side="right", fill="y", padx=(16, 0))

        ttk.Label(sol, text="STOK KARTI", style="Baslik.TLabel").pack(anchor="w", pady=(0, 8))
        form = ttk.LabelFrame(sol, text="Temel Bilgiler", padding=10)
        form.pack(fill="x")
        self.alanlar = {}
        temel_alanlar = (
            ("Stok Kodu", "stok_kodu"),
            ("Stok Adı", "stok_adi"),
            ("Kart Türü", "kart_turu"),
            ("Ana Birim", "birim"),
            ("Marka", "marka"),
            ("Model", "model"),
            ("Renk", "renk"),
            ("Ağırlık", "agirlik"),
            ("Rapor Grubu", "rapor_grubu"),
            ("Raf Yeri", "raf_yeri"),
            ("Raf Ömrü", "raf_omru"),
        )
        for sira, (etiket, alan) in enumerate(temel_alanlar):
            satir = sira // 2
            sutun = (sira % 2) * 3
            ttk.Label(form, text=etiket).grid(row=satir, column=sutun, padx=6, pady=4, sticky="w")
            if alan == "stok_kodu":
                widget = ttk.Combobox(form, width=20)
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="ew")
                ttk.Button(form, text="Yeni", width=6, command=lambda: self.stok_alan_yeni("stok_kodu")).grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=4
                )
                widget.bind("<KeyRelease>", self._stok_kodu_ara)
                widget.bind("<<ComboboxSelected>>", self._stok_kodu_secildi)
                self._stok_kodu_sag_tik_bagla(widget)
            elif alan == "stok_adi":
                widget = ttk.Combobox(form, width=20)
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="ew")
                ttk.Button(form, text="Yeni", width=6, command=lambda: self.stok_alan_yeni("stok_adi")).grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=4
                )
                widget.bind("<KeyRelease>", self._stok_adi_ara)
                widget.bind("<<ComboboxSelected>>", self._stok_adi_secildi)
            elif alan == "agirlik":
                widget = ttk.Entry(form, width=26)
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="ew")
            elif alan == "raf_omru":
                widget = ttk.Combobox(form, values=StokService.raf_omru_secenekleri(), width=20)
                if self.stok and self.stok.raf_omru:
                    widget.set(tarih_goster(self.stok.raf_omru))
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="ew")
                ttk.Button(form, text="Yeni", width=6, command=self.raf_omru_sec).grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=4
                )
            else:
                # Tüm seçmeli alanlar: listeden seç + Yeni ile kalıcı ekle
                if alan == "kart_turu":
                    degerler = StokService.kart_turu_secenekleri(KART_TURLERI)
                elif alan == "birim":
                    degerler = list(dict.fromkeys([*BIRIM_SECENEKLERI, *StokService.secenekleri_listele("birim")]))
                else:
                    degerler = StokService.secenekleri_listele(alan)
                widget = ttk.Combobox(form, values=degerler, width=20)
                if alan == "kart_turu":
                    widget.set((self.stok.kart_turu if self.stok else None) or "Ticari Mal")
                elif alan == "birim":
                    widget.set((self.stok.birim if self.stok else None) or "Adet")
                elif self.stok and getattr(self.stok, alan, None):
                    widget.set(getattr(self.stok, alan))
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="ew")
                kayit_turu = alan
                ttk.Button(
                    form,
                    text="Yeni",
                    width=6,
                    command=lambda a=alan, t=kayit_turu: self.secenek_ekle(a, t),
                ).grid(row=satir, column=sutun + 2, padx=(0, 6), pady=4)
                widget.bind("<Return>", lambda e, a=alan, t=kayit_turu: self.secenek_yazilanı_kaydet(a, t))
            self.alanlar[alan] = widget
        form.columnconfigure(1, weight=1)
        form.columnconfigure(4, weight=1)
        self._stok_kod_eslesme = {}
        self._stok_ad_eslesme = {}

        alis_cerceve = ttk.LabelFrame(sol, text="Alış Fiyatları", padding=10)
        alis_cerceve.pack(fill="x", pady=(12, 0))
        self.fiyat_alanlari = {}

        # Liste → 3 ardışık iskonto → Fabrika
        ttk.Label(alis_cerceve, text="Liste Fiyatı").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.fiyat_alanlari["LİSTE FİYATI"] = ttk.Entry(alis_cerceve, width=16)
        self.fiyat_alanlari["LİSTE FİYATI"].grid(row=0, column=1, padx=6, pady=4, sticky="w")
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<FocusOut>", self._fabrika_fiyati_guncelle)

        self.iskonto_alanlari = {}
        for kolon, (etiket, anahtar) in enumerate(
            (("1. İskonto %", "iskonto_1"), ("2. İskonto %", "iskonto_2"), ("3. İskonto %", "iskonto_3"))
        ):
            ttk.Label(alis_cerceve, text=etiket).grid(row=1, column=kolon * 2, padx=6, pady=4, sticky="w")
            giris = ttk.Entry(alis_cerceve, width=10)
            giris.grid(row=1, column=kolon * 2 + 1, padx=6, pady=4, sticky="w")
            giris.bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
            giris.bind("<FocusOut>", self._fabrika_fiyati_guncelle)
            self.iskonto_alanlari[anahtar] = giris

        ttk.Label(alis_cerceve, text="Fabrika Fiyatı").grid(row=2, column=0, padx=6, pady=4, sticky="w")
        self.fiyat_alanlari["FABRİKA FİYATI"] = ttk.Entry(alis_cerceve, width=16, state="readonly")
        self.fiyat_alanlari["FABRİKA FİYATI"].grid(row=2, column=1, padx=6, pady=4, sticky="w")
        ttk.Label(
            alis_cerceve,
            text="Fabrika = Liste − 1./2./3. iskonto (ardışık / birbirine bağlı)",
            font=("Segoe UI", 8),
        ).grid(row=2, column=2, columnspan=4, padx=6, pady=4, sticky="w")

        diger_alis = (
            ("Alış Fiyatı", "ALIŞ FİYATI"),
            ("Spot Fiyatı", "SPOT FİYATI"),
            ("İnternet Fiyatı", "İNTERNET FİYATI"),
            ("Rakip Fiyatı", "RAKİP FİYATI"),
        )
        for sira, (etiket, fiyat_adi) in enumerate(diger_alis):
            satir = 3 + sira // 2
            sutun = (sira % 2) * 2
            ttk.Label(alis_cerceve, text=etiket).grid(row=satir, column=sutun, padx=6, pady=4, sticky="w")
            if fiyat_adi == "ALIŞ FİYATI":
                giris = ttk.Entry(alis_cerceve, width=16, state="readonly")
            else:
                giris = ttk.Entry(alis_cerceve, width=16)
            giris.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="w")
            self.fiyat_alanlari[fiyat_adi] = giris
        ttk.Label(
            alis_cerceve,
            text="Alış Fiyatı = son alış faturasındaki net iskontolu birim fiyat (otomatik)",
            font=("Segoe UI", 8),
        ).grid(row=5, column=0, columnspan=4, padx=6, pady=(2, 4), sticky="w")

        satis_cerceve = ttk.LabelFrame(sol, text="Satış Fiyatları (10 adet)", padding=10)
        satis_cerceve.pack(fill="both", expand=True, pady=(10, 0))
        for satir, fiyat_adi in enumerate(SATIS_FIYAT_ADLARI):
            kolon = 0 if satir < 5 else 2
            yerel = satir if satir < 5 else satir - 5
            ttk.Label(satis_cerceve, text=fiyat_adi).grid(row=yerel, column=kolon, padx=6, pady=4, sticky="w")
            giris = ttk.Entry(satis_cerceve, width=18)
            giris.grid(row=yerel, column=kolon + 1, padx=6, pady=4, sticky="w")
            self.fiyat_alanlari[fiyat_adi] = giris

        if self.stok:
            self.alanlar["stok_kodu"].set(self.stok.stok_kodu or "")
            self.alanlar["stok_adi"].set(self.stok.stok_adi or "")
            if getattr(self.stok, "agirlik", None):
                self.alanlar["agirlik"].insert(0, self.stok.agirlik)
            for anahtar in ("iskonto_1", "iskonto_2", "iskonto_3"):
                deger = getattr(self.stok, anahtar, None)
                if deger is not None and Decimal(deger) != 0:
                    self.iskonto_alanlari[anahtar].insert(
                        0, f"{Decimal(deger):f}".rstrip("0").rstrip(".")
                    )
            for fiyat in self.stok.fiyatlar:
                if fiyat.fiyat_adi in self.fiyat_alanlari:
                    self._fiyat_yaz(fiyat.fiyat_adi, fiyat.tutar)
                else:
                    hedef = ESKI_FIYAT_ESLEME.get(fiyat.fiyat_adi)
                    if hedef and hedef in self.fiyat_alanlari and not self.fiyat_alanlari[hedef].get():
                        self._fiyat_yaz(hedef, fiyat.tutar)
            # Alış fiyatını son alış faturası net iskontolu fiyatıyla senkronize et
            son_net = StokService.son_alis_faturasi_net(
                stok_kodu=self.stok.stok_kodu, stok_id=self.stok.id
            )
            if son_net is not None:
                self._fiyat_yaz("ALIŞ FİYATI", f"{son_net:f}".rstrip("0").rstrip("."))
            self._fabrika_fiyati_guncelle()
        elif self.baslangic:
            if self.baslangic.get("stok_kodu"):
                self.alanlar["stok_kodu"].set(str(self.baslangic["stok_kodu"]))
            if self.baslangic.get("stok_adi"):
                self.alanlar["stok_adi"].set(str(self.baslangic["stok_adi"]))
            if self.baslangic.get("kart_turu") and "kart_turu" in self.alanlar:
                self.alanlar["kart_turu"].set(str(self.baslangic["kart_turu"]))
            if self.baslangic.get("birim") and "birim" in self.alanlar:
                self.alanlar["birim"].set(str(self.baslangic["birim"]))

        self.ozet_etiketleri = {}
        for etiket in ("Toplam Giriş", "Toplam Çıkış", "Kalan Miktar", "FIFO Envanter Değeri"):
            ttk.Label(sag, text=etiket, font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 0))
            deger = ttk.Label(sag, text="0", font=("Segoe UI", 18, "bold"))
            deger.pack(anchor="w")
            self.ozet_etiketleri[etiket] = deger
        self._ozeti_yenile()

        alt_butonlar = ttk.Frame(sol)
        alt_butonlar.pack(fill="x", pady=(14, 0))
        for metin, komut in (
            ("Stok Açıklama", self.aciklama_ac),
            ("Stok Birimleri", self.birimler_ac),
            ("Stok Resimleri", self.resimler_ac),
            ("Muhasebe Kodları", self.muhasebe_ac),
            ("Barkod Bilgileri", self.barkodlar_ac),
            ("EAN-13 Oluştur", self.ean13_barkod_olustur),
            ("Fiyat Analiz", self.fiyat_analiz_ac),
            ("Stok Hareketleri", self.stok_hareketleri_ac),
        ):
            ttk.Button(alt_butonlar, text=metin, command=komut).pack(side="left", padx=(0, 8), pady=2)

        self.alanlar["stok_kodu"].focus_set()

    def stok_alan_yeni(self, alan):
        if alan == "stok_kodu" and not self.stok:
            # Yeni kartta "Yeni" → otomatik EAN-13 stok kodu
            self._stok_koduna_ean13_yaz(otomatik=True)
            return
        etiket = "Stok kodu" if alan == "stok_kodu" else "Stok adı"
        deger = simpledialog.askstring(
            "Yeni değer",
            f"Yeni {etiket} yazın (mevcut listede olmayan yeni kart için):",
            parent=self,
            initialvalue=self.alanlar[alan].get().strip(),
        )
        if deger is None:
            return
        deger = deger.strip()
        self.alanlar[alan].set(deger)
        if deger:
            mevcut = list(self.alanlar[alan]["values"])
            if deger not in mevcut:
                self.alanlar[alan]["values"] = [deger, *mevcut]

    def _stok_kodu_sag_tik_bagla(self, widget):
        """Stok kodu alanında sağ tık ile EAN-13 üretimini etkinleştirir."""
        def bagla(_event=None):
            for seq in ("<Button-3>", "<Control-Button-1>"):
                try:
                    widget.bind(seq, self._stok_kodu_sag_tik)
                except tk.TclError:
                    pass
            # ttk.Combobox içindeki giriş alanına da bağla (Windows)
            try:
                for cocuk in widget.winfo_children():
                    cocuk.bind("<Button-3>", self._stok_kodu_sag_tik)
                    cocuk.bind("<Control-Button-1>", self._stok_kodu_sag_tik)
            except tk.TclError:
                pass

        bagla()
        widget.bind("<Map>", lambda _e: self.after(30, bagla), add="+")

    def _stok_kodu_sag_tik(self, event):
        """Sağ tık: EAN-13'ü doğrudan stok kodu olarak yazar."""
        self._stok_koduna_ean13_yaz(otomatik=True)
        return "break"

    def _stok_koduna_ean13_yaz(self, otomatik=False):
        """EAN-13 üretir ve stok koduna yazar; boşsa 1. barkoda da koyar."""
        mevcut = self.alanlar["stok_kodu"].get().strip()
        if mevcut and not otomatik:
            if not messagebox.askyesno(
                "Stok kodu",
                f"Stok kodu dolu ({mevcut}).\nEAN-13 ile değiştirilsin mi?",
                parent=self,
            ):
                return
        elif mevcut and otomatik and self.stok:
            # Mevcut kartta sağ tık: onay iste
            if not messagebox.askyesno(
                "Stok kodu",
                f"Stok kodu dolu ({mevcut}).\nEAN-13 ile değiştirilsin mi?",
                parent=self,
            ):
                return
        elif mevcut and otomatik and not self.stok:
            # Yeni kartta dolu alan: sessizce EAN-13 ile değiştir
            pass

        haric = [b.get("barkod") for b in self.barkodlar]
        if mevcut:
            haric.append(mevcut)
        stok_id = self.stok.id if self.stok else None
        try:
            barkod = StokService.ean13_olustur(stok_id=stok_id, haric_barkodlar=haric)
        except ValueError as hata:
            messagebox.showerror("EAN-13", str(hata), parent=self)
            return

        self.alanlar["stok_kodu"].set(barkod)
        try:
            degerler = list(self.alanlar["stok_kodu"]["values"])
            if barkod not in degerler:
                self.alanlar["stok_kodu"]["values"] = [barkod, *degerler]
        except tk.TclError:
            pass

        birim = self.alanlar["birim"].get().strip() or "Adet"
        fiyat = "0"
        if "SATIŞ FİYATI 1" in self.fiyat_alanlari:
            fiyat = self.fiyat_alanlari["SATIŞ FİYATI 1"].get().strip() or "0"
        kayit = {
            "barkod": barkod,
            "birim": birim,
            "fiyat_adi": "SATIŞ FİYATI 1",
            "fiyat": fiyat,
            "aciklama": "1. Barkod (EAN-13)",
        }
        # 1. barkod varsa dokunma; yoksa başa ekle
        if self.barkodlar and (self.barkodlar[0].get("barkod") or "").strip():
            if not otomatik or self.stok:
                messagebox.showinfo(
                    "EAN-13",
                    f"Stok kodu güncellendi:\n{barkod}\n\n1. barkod korundu "
                    f"({self.barkodlar[0].get('barkod')}).",
                    parent=self,
                )
            return
        self.barkodlar.insert(0, kayit)
        self.barkodlar = self.barkodlar[:5]
        if not otomatik or self.stok:
            messagebox.showinfo(
                "EAN-13",
                f"Stok kodu ve 1. barkod:\n{barkod}\n\nKartı kaydedince kalıcı olur.",
                parent=self,
            )

    def _stok_kodu_ara(self, _event=None):
        metin = self.alanlar["stok_kodu"].get().strip()
        if not metin:
            self.alanlar["stok_kodu"]["values"] = ()
            self._stok_kod_eslesme = {}
            return
        bulunan = StokService.stok_kodu_onerileri(metin)
        self._stok_kod_eslesme = {s.stok_kodu: s for s in bulunan}
        self.alanlar["stok_kodu"]["values"] = tuple(self._stok_kod_eslesme.keys())

    def _stok_adi_ara(self, _event=None):
        metin = self.alanlar["stok_adi"].get().strip()
        if len(metin) < 3:
            self.alanlar["stok_adi"]["values"] = ()
            self._stok_ad_eslesme = {}
            return
        bulunan = StokService.stok_adi_onerileri(metin, min_harf=3)
        self._stok_ad_eslesme = {s.stok_adi: s for s in bulunan}
        # Aynı ad birden fazla olabilir; kod ile ayırt et
        if len({s.stok_adi for s in bulunan}) < len(bulunan):
            self._stok_ad_eslesme = {f"{s.stok_adi} [{s.stok_kodu}]": s for s in bulunan}
        self.alanlar["stok_adi"]["values"] = tuple(self._stok_ad_eslesme.keys())

    def _stok_kodu_secildi(self, _event=None):
        kod = self.alanlar["stok_kodu"].get().strip()
        stok = self._stok_kod_eslesme.get(kod)
        if not stok:
            return
        self.alanlar["stok_kodu"].set(stok.stok_kodu)
        self.alanlar["stok_adi"].set(stok.stok_adi)

    def _stok_adi_secildi(self, _event=None):
        ad = self.alanlar["stok_adi"].get().strip()
        stok = self._stok_ad_eslesme.get(ad)
        if not stok:
            return
        self.alanlar["stok_kodu"].set(stok.stok_kodu)
        self.alanlar["stok_adi"].set(stok.stok_adi)

    def _secenek_degerlerini_yenile(self, alan, tur):
        if tur == "kart_turu":
            degerler = StokService.kart_turu_secenekleri(KART_TURLERI)
        elif tur == "birim":
            degerler = list(dict.fromkeys([*BIRIM_SECENEKLERI, *StokService.secenekleri_listele("birim")]))
        else:
            degerler = StokService.secenekleri_listele(tur)
        if alan in self.alanlar:
            self.alanlar[alan]["values"] = degerler
        if tur == "birim" and "birim" in self.alanlar:
            self.alanlar["birim"]["values"] = degerler
        elif tur == "kart_turu" and "kart_turu" in self.alanlar:
            self.alanlar["kart_turu"]["values"] = degerler

    def secenek_ekle(self, alan, tur=None):
        tur = tur or alan
        etiketler = {
            "rapor_grubu": "Rapor grubu",
            "marka": "Marka",
            "model": "Model",
            "renk": "Renk",
            "raf_yeri": "Raf yeri",
            "birim": "Birim",
            "kart_turu": "Kart türü",
        }
        deger = simpledialog.askstring(
            "Yeni seçenek",
            f"Yeni {etiketler.get(tur, tur)} adını yazın:",
            parent=self,
            initialvalue=self.alanlar[alan].get().strip(),
        )
        if not deger:
            return
        try:
            kayit = StokService.secenek_ekle(tur, deger)
        except ValueError as hata:
            messagebox.showerror("Seçenek eklenemedi", str(hata), parent=self)
            return
        self._secenek_degerlerini_yenile(alan, tur)
        self.alanlar[alan].set(kayit)

    def secenek_yazilanı_kaydet(self, alan, tur=None):
        """Combobox'a yazılıp Enter'a basılan yeni değeri kalıcı listeye ekler."""
        tur = tur or alan
        deger = self.alanlar[alan].get().strip()
        if not deger:
            return "break"
        try:
            kayit = StokService.secenek_ekle(tur, deger)
        except ValueError as hata:
            messagebox.showerror("Seçenek eklenemedi", str(hata), parent=self)
            return "break"
        self._secenek_degerlerini_yenile(alan, tur)
        self.alanlar[alan].set(kayit)
        return "break"

    def raf_omru_sec(self):
        deger = simpledialog.askstring(
            "Raf ömrü",
            "Raf ömrü tarihi (gg.aa.yyyy):",
            parent=self,
            initialvalue=self.alanlar["raf_omru"].get() or tarih_goster(date.today()),
        )
        if not deger:
            return
        try:
            datetime.strptime(deger.strip(), "%d.%m.%Y")
        except ValueError:
            messagebox.showerror("Tarih", "Tarihi gg.aa.yyyy formatında girin.", parent=self)
            return
        deger = deger.strip()
        mevcut = list(self.alanlar["raf_omru"]["values"])
        if deger not in mevcut:
            mevcut.insert(0, deger)
            self.alanlar["raf_omru"]["values"] = mevcut
        self.alanlar["raf_omru"].set(deger)

    def _fiyat_yaz(self, fiyat_adi, tutar):
        widget = self.fiyat_alanlari[fiyat_adi]
        durum = str(widget.cget("state"))
        if durum == "readonly":
            widget.configure(state="normal")
        widget.delete(0, "end")
        widget.insert(0, str(tutar))
        if durum == "readonly":
            widget.configure(state="readonly")

    def _fabrika_fiyati_guncelle(self, _event=None):
        liste = self.fiyat_alanlari["LİSTE FİYATI"].get().strip()
        if not liste:
            self._fiyat_yaz("FABRİKA FİYATI", "")
            return
        try:
            fabrika = fabrika_fiyati_hesapla(
                liste,
                self.iskonto_alanlari["iskonto_1"].get(),
                self.iskonto_alanlari["iskonto_2"].get(),
                self.iskonto_alanlari["iskonto_3"].get(),
            )
        except ValueError:
            return
        metin = f"{fabrika:f}".rstrip("0").rstrip(".")
        self._fiyat_yaz("FABRİKA FİYATI", metin)

    def _ozeti_yenile(self):
        if not self.stok:
            for etiket in self.ozet_etiketleri.values():
                etiket.configure(text="0")
            return
        ozet = StokService.stok_ozeti(self.stok.id)
        self.ozet_etiketleri["Toplam Giriş"].configure(text=f"{ozet['toplam_giris']:,.4f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", "."))
        self.ozet_etiketleri["Toplam Çıkış"].configure(text=f"{ozet['toplam_cikis']:,.4f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", "."))
        self.ozet_etiketleri["Kalan Miktar"].configure(text=f"{ozet['kalan']:,.4f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", "."))
        self.ozet_etiketleri["FIFO Envanter Değeri"].configure(text=para_goster(ozet["fifo_deger"]))

    def aciklama_ac(self):
        dialog = StokAciklamaDialog(self, self.aciklama)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.aciklama = dialog.result

    def birimler_ac(self):
        dialog = StokBirimlerDialog(self, self.alanlar["birim"].get(), self.birimler)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.birimler = dialog.result

    def resimler_ac(self):
        dialog = StokResimlerDialog(self, self.alanlar["stok_kodu"].get().strip(), self.resimler)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.resimler = dialog.result

    def muhasebe_ac(self):
        dialog = StokMuhasebeDialog(self, self.muhasebe)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.muhasebe = dialog.result

    def barkodlar_ac(self):
        satis1 = ""
        if "SATIŞ FİYATI 1" in self.fiyat_alanlari:
            satis1 = self.fiyat_alanlari["SATIŞ FİYATI 1"].get().strip()
        fiyatlar = {
            ad: giris.get().strip()
            for ad, giris in self.fiyat_alanlari.items()
            if giris.get().strip()
        }
        dialog = StokBarkodlarDialog(
            self,
            ana_birim=self.alanlar["birim"].get(),
            birimler=self.birimler,
            barkodlar=self.barkodlar,
            satis_fiyat_1=satis1 or "0",
            fiyatlar=fiyatlar,
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.barkodlar = dialog.result

    def ean13_barkod_olustur(self):
        """İlk boş barkod satırına EAN-13 ekler; dolu 1. barkodu silmez."""
        haric = [b.get("barkod") for b in self.barkodlar]
        stok_id = self.stok.id if self.stok else None
        try:
            barkod = StokService.ean13_olustur(stok_id=stok_id, haric_barkodlar=haric)
        except ValueError as hata:
            messagebox.showerror("EAN-13", str(hata), parent=self)
            return
        birim = self.alanlar["birim"].get().strip() or "Adet"
        # 5 satıra pad
        while len(self.barkodlar) < 5:
            sira = len(self.barkodlar) + 1
            fiyat_adi = SATIS_FIYAT_ADLARI[sira - 1] if sira <= len(SATIS_FIYAT_ADLARI) else ""
            fiyat = "0"
            if fiyat_adi and fiyat_adi in self.fiyat_alanlari:
                fiyat = self.fiyat_alanlari[fiyat_adi].get().strip() or "0"
            self.barkodlar.append(
                {
                    "barkod": "",
                    "birim": birim,
                    "fiyat_adi": fiyat_adi,
                    "fiyat": fiyat,
                    "aciklama": f"{sira}. Barkod",
                }
            )
        hedef_index = None
        for i, kayit in enumerate(self.barkodlar[:5]):
            if not (kayit.get("barkod") or "").strip():
                hedef_index = i
                break
        if hedef_index is None:
            messagebox.showinfo(
                "Barkod",
                "5 barkod satırının hepsi dolu.\n1. barkod silinmez; Barkod Bilgileri'nden 2–5. satırı temizleyin.",
                parent=self,
            )
            return
        sira = hedef_index + 1
        fiyat_adi = SATIS_FIYAT_ADLARI[hedef_index] if hedef_index < len(SATIS_FIYAT_ADLARI) else "SATIŞ FİYATI 1"
        fiyat = "0"
        if fiyat_adi in self.fiyat_alanlari:
            fiyat = self.fiyat_alanlari[fiyat_adi].get().strip() or "0"
        self.barkodlar[hedef_index] = {
            "barkod": barkod,
            "birim": birim,
            "fiyat_adi": fiyat_adi,
            "fiyat": fiyat,
            "aciklama": f"{sira}. Barkod (EAN-13)",
        }
        messagebox.showinfo(
            "EAN-13",
            f"{sira}. barkod eklendi:\n{barkod}\n{fiyat_adi}: {fiyat}\n\nMevcut barkodlar korundu.",
            parent=self,
        )

    def fiyat_analiz_ac(self):
        stok_id = self.stok.id if self.stok else None
        dialog = StokFiyatAnalizDialog(self, stok_id)
        self.wait_window(dialog)

    def stok_hareketleri_ac(self):
        if not self.stok:
            messagebox.showinfo(
                "Stok hareketleri",
                "Hareketleri görmek için önce stok kartını kaydedin.",
                parent=self,
            )
            return
        dialog = StokHareketleriDialog(self, self.stok)
        self.wait_window(dialog)

    def kaydet(self):
        self._fabrika_fiyati_guncelle()
        # Alış fiyatını son faturadan tazele (manuel müdahale yok)
        kod = self.alanlar["stok_kodu"].get().strip()
        stok_id = self.stok.id if self.stok else None
        son_net = StokService.son_alis_faturasi_net(stok_kodu=kod, stok_id=stok_id)
        if son_net is not None:
            self._fiyat_yaz("ALIŞ FİYATI", f"{son_net:f}".rstrip("0").rstrip("."))
        veriler = {
            "stok_kodu": self.alanlar["stok_kodu"].get().strip(),
            "stok_adi": self.alanlar["stok_adi"].get().strip(),
            "kart_turu": self.alanlar["kart_turu"].get().strip(),
            "birim": self.alanlar["birim"].get().strip() or "Adet",
            "rapor_grubu": self.alanlar["rapor_grubu"].get().strip(),
            "marka": self.alanlar["marka"].get().strip(),
            "model": self.alanlar["model"].get().strip(),
            "renk": self.alanlar["renk"].get().strip(),
            "agirlik": self.alanlar["agirlik"].get().strip(),
            "raf_yeri": self.alanlar["raf_yeri"].get().strip(),
            "aciklama": self.aciklama,
            "stok_id": self.stok.id if self.stok else None,
            "iskonto_1": self.iskonto_alanlari["iskonto_1"].get().strip() or "0",
            "iskonto_2": self.iskonto_alanlari["iskonto_2"].get().strip() or "0",
            "iskonto_3": self.iskonto_alanlari["iskonto_3"].get().strip() or "0",
        }
        veriler.update({k: (v or "") for k, v in self.muhasebe.items()})
        if not veriler["stok_kodu"] or not veriler["stok_adi"]:
            messagebox.showwarning("Eksik bilgi", "Stok kodu ve stok adı zorunludur.", parent=self)
            return
        raf_omru_metin = self.alanlar["raf_omru"].get().strip()
        if raf_omru_metin:
            try:
                veriler["raf_omru"] = datetime.strptime(raf_omru_metin, "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Raf ömrü", "Raf ömrü tarihini gg.aa.yyyy formatında girin.", parent=self)
                return
        else:
            veriler["raf_omru"] = None
        fiyatlar = [(ad, giris.get().strip()) for ad, giris in self.fiyat_alanlari.items()]
        try:
            self.result = StokService.stok_kaydi(
                veriler,
                fiyatlar,
                birimler=self.birimler,
                barkodlar=self.barkodlar,
                resimler=self.resimler,
            )
        except ValueError as hata:
            messagebox.showerror("Stok kaydedilemedi", str(hata), parent=self)
            return
        self.stok = self.result
        self.title("Stok Kartını Düzenle")
        self._ozeti_yenile()
        messagebox.showinfo("Kaydedildi", "Stok kartı kaydedildi.", parent=self)
