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
    """Ürün kodu / adı filtreli seçim; bulunamazsa yeni stok kartı açar.

    ayrintili=True ise stok listesindeki gibi 5 kelimelik ayrıntılı ürün araması açılır.
    """

    def __init__(
        self,
        parent,
        query="",
        on_select=None,
        kod="",
        ad="",
        sadece_stokta=False,
        depo_ad=None,
        ayrintili=False,
    ):
        super().__init__(parent)
        self.title("Ürün Seçimi" + (" — Stokta Olanlar" if sadece_stokta else ""))
        self.geometry("920x560" if ayrintili else "860x440")
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        self._urunler = []
        self._arama_after = None
        self.sadece_stokta = bool(sadece_stokta)
        self.depo_ad = (depo_ad or "").strip() or None
        self.ayrintili = bool(ayrintili)

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
        if self.ayrintili:
            ttk.Label(ust, text="Hızlı Ara (kod / barkod):").pack(side="left")
            self.kod_filtre = ttk.Entry(ust, width=28)
            self.kod_filtre.pack(side="left", padx=(6, 10))
            self.kod_filtre.insert(0, kod or ad)
            # Ayrıntılı modda tek satır ad filtresi yok; kelime kutuları kullanılır
            self.ad_filtre = ttk.Entry(ust)  # gizli tutulmaz; boş bırakılır (API uyumu)
            ttk.Button(ust, text="Ara", command=self.listeyi_yenile).pack(side="left")
            self.kayit_sayisi = ttk.Label(ust, text="Bulunan: 0")
            self.kayit_sayisi.pack(side="right")

            ayrinti = ttk.LabelFrame(self, text="Ayrıntılı Ürün Arama", padding=10)
            ayrinti.pack(fill="x", padx=12, pady=(0, 4))
            kutular = ttk.Frame(ayrinti)
            kutular.pack(fill="x")
            self._ayrinti_ph = (
                "1. kelimeyi yazın",
                "2. kelimeyi yazın",
                "3. kelimeyi yazın",
                "4. kelimeyi yazın",
                "5. kelimeyi yazın",
            )
            self.ayrinti_kutular = []
            # İlk ad sorgusu 1. kutuya
            ilk_kelimeler = [p for p in (ad or "").split() if p][:5]
            for i, ph in enumerate(self._ayrinti_ph):
                col = ttk.Frame(kutular)
                col.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 6, 0))
                ttk.Label(col, text=f"Ürün Kelimesi {i + 1}").pack(anchor="w")
                e = ttk.Entry(col)
                e.pack(fill="x", pady=(2, 0))
                if i < len(ilk_kelimeler):
                    e.insert(0, ilk_kelimeler[i])
                else:
                    self._placeholder_kur(e, ph)
                e.bind("<Return>", lambda _ev: self.listeyi_yenile())
                e.bind("<KeyRelease>", self._arama_gecikmeli)
                self.ayrinti_kutular.append(e)
            kontrol = ttk.Frame(ayrinti)
            kontrol.pack(fill="x", pady=(8, 0))
            ttk.Label(kontrol, text="Arama Yöntemi:").pack(side="left")
            self.ayrinti_yontem = ttk.Combobox(
                kontrol,
                values=("Tüm kelimeler bulunsun", "Kelimelerden herhangi biri bulunsun"),
                state="readonly",
                width=34,
            )
            self.ayrinti_yontem.set("Tüm kelimeler bulunsun")
            self.ayrinti_yontem.pack(side="left", padx=8)
            self.ayrinti_yontem.bind("<<ComboboxSelected>>", lambda _e: self.listeyi_yenile())
            ttk.Button(kontrol, text="Temizle", command=self._ayrinti_temizle).pack(side="left", padx=4)
            ttk.Label(
                ayrinti,
                text="Kelime sırası önemli değildir; her kutu ürün adının herhangi bir yerinde bağımsız aranır.",
                foreground="#627D98",
            ).pack(anchor="w", pady=(6, 0))
            self.kod_filtre.bind("<KeyRelease>", self._arama_gecikmeli)
            self.kod_filtre.bind("<Return>", lambda _e: self.listeyi_yenile())
        else:
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
            self.kayit_sayisi = None
            self.ayrinti_kutular = []
            self.ayrinti_yontem = None

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

        kolonlar = ("kod", "ad", "birim", "stok", "fiyat", "kaynak", "kdv")
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=4)
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for kolon, baslik, genislik in (
            ("kod", "Ürün Kodu", 120),
            ("ad", "Ürün Adı", 240),
            ("birim", "Birim", 70),
            ("stok", "Mevcut Stok", 100),
            ("fiyat", "Fiyat", 110),
            ("kaynak", "Kaynak", 90),
            ("kdv", "KDV %", 60),
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
        if self.ayrintili:
            self.kod_filtre.focus_set()
            self.kod_filtre.icursor("end")
        elif ad and not kod:
            self.ad_filtre.focus_set()
            self.ad_filtre.icursor("end")
        else:
            self.kod_filtre.focus_set()
            self.kod_filtre.icursor("end")

    def _placeholder_kur(self, entry, placeholder: str):
        entry._ph = placeholder  # type: ignore[attr-defined]
        entry.insert(0, placeholder)
        try:
            entry.configure(foreground="#98A2B3")
        except tk.TclError:
            pass

        def _in(_e=None, w=entry, ph=placeholder):
            if w.get() == ph:
                w.delete(0, "end")
                try:
                    w.configure(foreground="#172B4D")
                except tk.TclError:
                    pass

        def _out(_e=None, w=entry, ph=placeholder):
            if not w.get().strip():
                w.delete(0, "end")
                w.insert(0, ph)
                try:
                    w.configure(foreground="#98A2B3")
                except tk.TclError:
                    pass

        entry.bind("<FocusIn>", _in, add="+")
        entry.bind("<FocusOut>", _out, add="+")

    def _ayrinti_deger(self, entry) -> str:
        metin = (entry.get() or "").strip()
        ph = getattr(entry, "_ph", "")
        if ph and metin == ph:
            return ""
        return metin

    def _ayrinti_kelimeler(self) -> list[str]:
        return [self._ayrinti_deger(e) for e in getattr(self, "ayrinti_kutular", []) or []]

    def _ayrinti_yontem_kod(self) -> str:
        metin = ""
        if getattr(self, "ayrinti_yontem", None):
            metin = (self.ayrinti_yontem.get() or "").strip()
        if "herhangi" in metin.casefold():
            return "or"
        return "and"

    def _ayrinti_temizle(self):
        for e in getattr(self, "ayrinti_kutular", []) or []:
            ph = getattr(e, "_ph", "")
            e.delete(0, "end")
            if ph:
                e.insert(0, ph)
                try:
                    e.configure(foreground="#98A2B3")
                except tk.TclError:
                    pass
        if getattr(self, "ayrinti_yontem", None):
            self.ayrinti_yontem.set("Tüm kelimeler bulunsun")
        if getattr(self, "kod_filtre", None):
            self.kod_filtre.delete(0, "end")
        self.listeyi_yenile()

    def _arama_gecikmeli(self, _event=None):
        if self._arama_after is not None:
            try:
                self.after_cancel(self._arama_after)
            except tk.TclError:
                pass
        self._arama_after = self.after(350, self.listeyi_yenile)

    def listeyi_yenile(self):
        self._arama_after = None
        for item in self.tablo.get_children():
            self.tablo.delete(item)

        if self.ayrintili:
            hizli = self.kod_filtre.get().strip()
            kelimeler = self._ayrinti_kelimeler()
            yontem = self._ayrinti_yontem_kod()
            self._urunler = StokService.stoklari_ayrintili_ara(
                kelimeler,
                yontem=yontem,
                hizli_arama=hizli,
                min_harf=2,
            )
            if self.sadece_stokta:
                depo = self.depo_ad
                filtrelenmis = []
                for stok in self._urunler:
                    mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
                    if depo:
                        mevcut = sum(
                            (
                                lot.kalan_miktar
                                for lot in (stok.lotlar or [])
                                if (getattr(getattr(lot, "depo", None), "ad", None) or "") == depo
                            ),
                            Decimal("0"),
                        )
                    if mevcut > 0:
                        filtrelenmis.append(stok)
                self._urunler = filtrelenmis
        else:
            kod = self.kod_filtre.get().strip()
            ad = self.ad_filtre.get().strip()
            self._urunler = StokService.stoklari_filtrele(
                kod=kod,
                ad=ad,
                sadece_stokta=self.sadece_stokta,
                depo_ad=self.depo_ad if self.sadece_stokta else None,
            )

        for sira, stok in enumerate(self._urunler):
            fiyat = _satis_fiyati_nesneden(stok)
            mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
            kdv = getattr(stok, "kdv_orani", None)
            kdv_metin = (
                f"{Decimal(kdv):f}".rstrip("0").rstrip(".")
                if kdv is not None
                else "20"
            ) or "0"
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
                    kdv_metin,
                ),
            )
        if getattr(self, "kayit_sayisi", None):
            self.kayit_sayisi.configure(text=f"Bulunan: {len(self._urunler)}")
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
        if self.ayrintili:
            kelimeler = [k for k in self._ayrinti_kelimeler() if k]
            baslangic_ad = " ".join(kelimeler)
            baslangic_kod = self.kod_filtre.get().strip()
        else:
            baslangic_kod = self.kod_filtre.get().strip()
            baslangic_ad = self.ad_filtre.get().strip()
        dialog = StokKartiDialog(
            self,
            baslangic={
                "stok_kodu": baslangic_kod,
                "stok_adi": baslangic_ad,
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
