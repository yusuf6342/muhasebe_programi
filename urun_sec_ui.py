"""Fatura/sipariş satırları için ürün seçim diyaloğu."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from database.stok_service import StokService
from stok_ui import StokKartiDialog


def _satis_fiyati_nesneden(stok, varsayilan=Decimal("0")) -> Decimal:
    """Yüklü stok.fiyatlar ilişkisinden SATIŞ FİYATI 1 (ekstra DB yok)."""
    fiyatlar = getattr(stok, "fiyatlar", None) or []
    for fiyat in fiyatlar:
        if (fiyat.fiyat_adi or "").strip().upper() == "SATIŞ FİYATI 1":
            return Decimal(str(fiyat.tutar))
    for fiyat in fiyatlar:
        ad = (fiyat.fiyat_adi or "").strip().upper()
        if ad.startswith("SATIŞ FİYATI"):
            return Decimal(str(fiyat.tutar))
    return Decimal(str(varsayilan))


class UrunSecDialog(tk.Toplevel):
    """Ürün kodu / adı filtreli seçim; bulunamazsa yeni stok kartı açar."""

    def __init__(
        self,
        parent,
        query="",
        on_select=None,
        kod="",
        ad="",
        sadece_stokta=False,
        depo_ad=None,
    ):
        super().__init__(parent)
        self.title("Ürün Seçimi" + (" — Stokta Olanlar" if sadece_stokta else ""))
        self.geometry("860x440")
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        self._urunler = []
        self._arama_after = None
        self.sadece_stokta = bool(sadece_stokta)
        self.depo_ad = (depo_ad or "").strip() or None

        # Tek sorgu geldiyse hem koda hem ada koy (eski çağrılar)
        kod = (kod or "").strip()
        ad = (ad or "").strip()
        query = (query or "").strip()
        if query and not kod and not ad:
            # Kısa / kod benzeri → kod; aksi halde ad
            if " " in query or len(query) >= 3:
                ad = query
            else:
                kod = query

        ust = ttk.Frame(self, padding=(12, 10, 12, 4))
        ust.pack(fill="x")
        ttk.Label(ust, text="Ürün Kodu").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.kod_filtre = ttk.Entry(ust, width=22)
        self.kod_filtre.grid(row=0, column=1, sticky="w", padx=(0, 16))
        self.kod_filtre.insert(0, kod)
        ttk.Label(ust, text="Ürün Adı").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.ad_filtre = ttk.Entry(ust, width=36)
        self.ad_filtre.grid(row=0, column=3, sticky="ew")
        self.ad_filtre.insert(0, ad)
        ust.columnconfigure(3, weight=1)
        ttk.Button(ust, text="Ara", command=self.listeyi_yenile).grid(row=0, column=4, padx=(10, 0))

        self.kod_filtre.bind("<KeyRelease>", self._arama_gecikmeli)
        self.ad_filtre.bind("<KeyRelease>", self._arama_gecikmeli)
        self.kod_filtre.bind("<Return>", lambda _e: self.listeyi_yenile())
        self.ad_filtre.bind("<Return>", lambda _e: self.listeyi_yenile())

        bos_metin = (
            "Stokta ürün bulunamadı. Tüm kartlar için STOK LİSTESİ'ni kullanın."
            if self.sadece_stokta
            else "Ürün bulunamadı. İsterseniz yeni ürün ekleyebilirsiniz."
        )
        self.bos_lbl = ttk.Label(self, text=bos_metin, foreground="#a33")
        self._bilgi_cerceve = ttk.Frame(self)
        self._bilgi_cerceve.pack(fill="x", padx=12)
        if self.sadece_stokta:
            ttk.Label(
                self._bilgi_cerceve,
                text="Yalnızca stoğu olan ürünler listelenir.",
                foreground="#555555",
            ).pack(anchor="w", pady=(0, 2))

        kolonlar = ("kod", "ad", "birim", "stok", "fiyat", "kaynak")
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=4)
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik, genislik in (
            ("kod", "Ürün Kodu", 120),
            ("ad", "Ürün Adı", 260),
            ("birim", "Birim", 80),
            ("stok", "Mevcut Stok", 100),
            ("fiyat", "Fiyat", 110),
            ("kaynak", "Kaynak", 100),
        ):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=genislik)
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self.sec())
        self.tablo.bind("<Return>", lambda _e: self.sec())

        alt = ttk.Frame(self, padding=12)
        alt.pack(fill="x")
        self.yeni_btn = ttk.Button(alt, text="Yeni Ürün Ekle", command=self.yeni_urun)
        if not self.sadece_stokta:
            self.yeni_btn.pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Seç", command=self.sec).pack(side="right", padx=8)

        self.listeyi_yenile()
        if ad and not kod:
            self.ad_filtre.focus_set()
            self.ad_filtre.icursor("end")
        else:
            self.kod_filtre.focus_set()
            self.kod_filtre.icursor("end")

    def _arama_gecikmeli(self, _event=None):
        if self._arama_after is not None:
            try:
                self.after_cancel(self._arama_after)
            except tk.TclError:
                pass
        self._arama_after = self.after(350, self.listeyi_yenile)

    def listeyi_yenile(self):
        self._arama_after = None
        kod = self.kod_filtre.get().strip()
        ad = self.ad_filtre.get().strip()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        self._urunler = StokService.stoklari_filtrele(
            kod=kod,
            ad=ad,
            sadece_stokta=self.sadece_stokta,
            depo_ad=self.depo_ad if self.sadece_stokta else None,
        )
        for sira, stok in enumerate(self._urunler):
            fiyat = _satis_fiyati_nesneden(stok)
            mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
            self.tablo.insert(
                "",
                "end",
                iid=str(sira),
                values=(
                    stok.stok_kodu,
                    stok.stok_adi,
                    stok.birim,
                    f"{mevcut:f}".rstrip("0").rstrip(".") or "0",
                    str(fiyat),
                    "Stok Kartı",
                ),
            )
        try:
            self.bos_lbl.pack_forget()
        except tk.TclError:
            pass
        if self._urunler:
            if hasattr(self, "yeni_btn") and not self.sadece_stokta:
                self.yeni_btn.configure(text="Yeni Ürün Ekle")
        else:
            self.bos_lbl.pack(in_=self._bilgi_cerceve, anchor="w", pady=(0, 4))
            if hasattr(self, "yeni_btn") and not self.sadece_stokta:
                self.yeni_btn.configure(text="Yeni Ürün Ekle (bulunamadı)")

    def sec(self):
        secim = self.tablo.selection()
        if not secim or not self.on_select:
            return
        degerler = self.tablo.item(secim[0], "values")
        callback = self.on_select
        self.on_select = None
        # Önce kapat: grab kalksın, parent Entry'ler odak alabilsin
        self.destroy()
        callback(degerler)

    def yeni_urun(self):
        dialog = StokKartiDialog(
            self,
            baslangic={
                "stok_kodu": self.kod_filtre.get().strip(),
                "stok_adi": self.ad_filtre.get().strip(),
            },
        )
        self.wait_window(dialog)
        if not dialog.result:
            return
        stok = dialog.result
        # Yeni kartı satıra aktar
        stok = StokService.stok_getir(stok.id) or stok
        fiyat = _satis_fiyati_nesneden(stok)
        if fiyat == 0:
            fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
        mevcut = sum((lot.kalan_miktar for lot in getattr(stok, "lotlar", []) or []), Decimal("0"))
        degerler = (
            stok.stok_kodu,
            stok.stok_adi,
            stok.birim or "Adet",
            f"{mevcut:f}".rstrip("0").rstrip(".") or "0",
            str(fiyat),
            "Stok Kartı",
        )
        callback = self.on_select
        self.on_select = None
        self.destroy()
        if callback:
            callback(degerler)
