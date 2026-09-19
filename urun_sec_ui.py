"""Fatura/sipariş satırları için ürün seçim diyaloğu — kurumsal liste görünümü."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from database.stok_service import StokService
from stok_ui import StokKartiDialog

# Cin Muhasebe fatura renkleri (yalnız bu diyaloğun Treeview stili)
_LACIVERT = "#0B2A4A"
_ZEBRA = "#EEF3F8"
_HOVER = "#FFF8E1"
_BEYAZ = "#FFFFFF"
_STIL_ADI = "UrunSecKurumsal.Treeview"
_STIL_HEAD = "UrunSecKurumsal.Treeview.Heading"

# Callback sözleşmesi (eski): (kod, ad, birim, stok, fiyat, kaynak[, kdv])
# Görünen kolonlar farklı olabilir; sec() bu sırayı korur.


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


def _para_tr(tutar) -> str:
    try:
        d = Decimal(str(tutar if tutar is not None else 0))
    except Exception:
        d = Decimal("0")
    metin = f"{d:,.2f}"
    return metin.replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def _mik_goster(miktar) -> str:
    try:
        d = Decimal(str(miktar if miktar is not None else 0))
    except Exception:
        return "0"
    return f"{d:f}".rstrip("0").rstrip(".") or "0"


def _barkod_goster(stok) -> str:
    ana = (getattr(stok, "barkod", None) or "").strip()
    if ana:
        return ana
    for b in getattr(stok, "barkodlar", None) or []:
        kod = (getattr(b, "barkod", None) or "").strip()
        if kod:
            return kod
    return ""


def _kurumsal_stil_kur(root) -> None:
    """Yalnız UrunSecKurumsal.* stili — diğer Treeview'lara dokunma."""
    stil = ttk.Style(root)
    try:
        stil.theme_use(stil.theme_use())
    except tk.TclError:
        pass
    stil.configure(
        _STIL_ADI,
        font=("Segoe UI Semibold", 11),
        rowheight=32,
        background=_BEYAZ,
        fieldbackground=_BEYAZ,
        foreground="#172B4D",
        borderwidth=0,
    )
    stil.configure(
        _STIL_HEAD,
        font=("Segoe UI", 12, "bold"),
        background="#E8EEF5",
        foreground=_LACIVERT,
        relief="flat",
    )
    stil.map(
        _STIL_ADI,
        background=[("selected", _LACIVERT)],
        foreground=[("selected", _BEYAZ)],
    )


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
        self.geometry("1040x520" if ayrintili else "980x420")
        self.minsize(720, 280)
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        self._urunler = []
        self._arama_after = None
        self._hover_iid = None
        self.sadece_stokta = bool(sadece_stokta)
        self.depo_ad = (depo_ad or "").strip() or None
        self.ayrintili = bool(ayrintili)

        kod = (kod or "").strip()
        ad = (ad or "").strip()
        query = (query or "").strip()
        if query and not kod and not ad:
            if " " in query or len(query) >= 3:
                ad = query
            else:
                kod = query

        _kurumsal_stil_kur(self)

        ust = ttk.Frame(self, padding=(12, 10, 12, 4))
        ust.pack(fill="x")
        if self.ayrintili:
            ttk.Label(ust, text="Hızlı Ara (kod / barkod):").pack(side="left")
            self.kod_filtre = ttk.Entry(ust, width=28)
            self.kod_filtre.pack(side="left", padx=(6, 10))
            self.kod_filtre.insert(0, kod or ad)
            self.ad_filtre = ttk.Entry(ust)
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
            self.ad_filtre = ttk.Entry(ust, width=40)
            self.ad_filtre.grid(row=0, column=3, sticky="ew")
            self.ad_filtre.insert(0, ad)
            ust.columnconfigure(3, weight=1)
            ttk.Button(ust, text="Ara", command=self.listeyi_yenile).grid(row=0, column=4, padx=(10, 0))
            self.kod_filtre.bind("<KeyRelease>", self._arama_gecikmeli)
            self.ad_filtre.bind("<KeyRelease>", self._arama_gecikmeli)
            self.kod_filtre.bind("<Return>", lambda _e: self.listeyi_yenile())
            self.ad_filtre.bind("<Return>", lambda _e: self.listeyi_yenile())
            self.kayit_sayisi = ttk.Label(ust, text="")
            self.kayit_sayisi.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
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
                text="Yalnızca stoğu olan ürünler listelenir. (En az 3 karakter · kelime sırası serbest)",
                foreground="#555555",
            ).pack(anchor="w", pady=(0, 2))

        kolonlar = ("kod", "ad", "barkod", "birim", "stok", "fiyat")
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=4)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=kolonlar,
            show="headings",
            selectmode="browse",
            style=_STIL_ADI,
            height=8,
        )
        for kolon, baslik, genislik, ank in (
            ("kod", "Stok Kodu", 110, "center"),
            ("ad", "Ürün Adı", 360, "w"),
            ("barkod", "Barkod", 130, "center"),
            ("birim", "Birim", 70, "center"),
            ("stok", "Mevcut Stok", 100, "e"),
            ("fiyat", "Satış Fiyatı", 120, "e"),
        ):
            self.tablo.heading(kolon, text=baslik, anchor=ank)
            self.tablo.column(
                kolon,
                width=genislik,
                minwidth=60 if kolon != "ad" else 180,
                stretch=(kolon == "ad"),
                anchor=ank,
            )
        dikey = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)

        self.tablo.tag_configure("tek", background=_BEYAZ, foreground="#172B4D")
        self.tablo.tag_configure("cift", background=_ZEBRA, foreground="#172B4D")
        self.tablo.tag_configure("hover", background=_HOVER, foreground="#172B4D")

        self.tablo.bind("<Double-1>", self._cift_tik)
        self.tablo.bind("<Button-1>", self._tek_tik, add="+")
        self.tablo.bind("<Return>", lambda _e: self.sec())
        self.tablo.bind("<Escape>", lambda _e: self.destroy())
        self.tablo.bind("<Motion>", self._hover)
        self.tablo.bind("<Leave>", self._hover_temizle)
        self.tablo.bind("<Up>", self._klavye_yukari)
        self.tablo.bind("<Down>", self._klavye_asagi)
        self.bind("<Escape>", lambda _e: self.destroy())
        # Entry'de yazarken ↑↓ imleç hareketi bozulmasın; tablo odaktayken gezin
        for w in (getattr(self, "kod_filtre", None), getattr(self, "ad_filtre", None)):
            if w is None:
                continue
            w.bind("<Down>", self._odak_tabloya)
            w.bind("<Return>", self._entry_enter)

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
        self._arama_after = self.after(280, self.listeyi_yenile)

    def _yukseklik_ayarla(self, kayit_sayisi: int) -> None:
        """Az sonuçta boş alan bırakma; çok sonuçta kaydırma."""
        h = max(4, min(14, kayit_sayisi if kayit_sayisi > 0 else 4))
        try:
            self.tablo.configure(height=h)
        except tk.TclError:
            pass
        # Pencere yüksekliği: üst + satırlar + alt
        try:
            baz = 220 if self.ayrintili else 160
            self.geometry(f"{max(self.winfo_width(), 900)}x{baz + h * 34}")
        except tk.TclError:
            pass

    def listeyi_yenile(self):
        self._arama_after = None
        self._hover_iid = None
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
            from database.search_service import tokenize_query

            birlesik = " ".join(p for p in (kod, ad) if p).strip()
            # Geçerli ≥2 karakterlik blok yoksa listeyi boşalt
            if not tokenize_query(birlesik):
                self._urunler = []
            else:
                self._urunler = StokService.stoklari_filtrele(
                    kod=kod,
                    ad=ad,
                    limit=80,
                    sadece_stokta=self.sadece_stokta,
                    depo_ad=self.depo_ad if self.sadece_stokta else None,
                    kelime_sirasiz=True,
                    min_ad_harf=2,
                )

        for sira, stok in enumerate(self._urunler):
            fiyat = _satis_fiyati_nesneden(stok)
            mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
            tag = "cift" if sira % 2 else "tek"
            self.tablo.insert(
                "",
                "end",
                iid=str(sira),
                tags=(tag,),
                values=(
                    stok.stok_kodu,
                    stok.stok_adi,
                    _barkod_goster(stok),
                    stok.birim or "Adet",
                    _mik_goster(mevcut),
                    _para_tr(fiyat),
                ),
            )

        self._yukseklik_ayarla(len(self._urunler))
        if getattr(self, "kayit_sayisi", None):
            self.kayit_sayisi.configure(text=f"Bulunan: {len(self._urunler)}")
        try:
            self.bos_lbl.pack_forget()
        except tk.TclError:
            pass
        if self._urunler:
            ilk = "0"
            self.tablo.selection_set(ilk)
            self.tablo.focus(ilk)
            self.tablo.see(ilk)
            if hasattr(self, "yeni_btn") and not self.sadece_stokta:
                self.yeni_btn.configure(text="Yeni Ürün Ekle")
        else:
            self.bos_lbl.pack(in_=self._bilgi_cerceve, anchor="w", pady=(0, 4))
            if hasattr(self, "yeni_btn") and not self.sadece_stokta:
                self.yeni_btn.configure(text="Yeni Ürün Ekle (bulunamadı)")

    def _callback_degerleri(self, stok) -> tuple:
        """Eski sözleşme: kod, ad, birim, stok, fiyat, kaynak[, kdv]."""
        fiyat = _satis_fiyati_nesneden(stok)
        mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
        kdv = getattr(stok, "kdv_orani", None)
        kdv_metin = (
            f"{Decimal(kdv):f}".rstrip("0").rstrip(".")
            if kdv is not None
            else "20"
        ) or "0"
        return (
            stok.stok_kodu,
            stok.stok_adi,
            stok.birim or "Adet",
            _mik_goster(mevcut),
            f"{fiyat:f}".rstrip("0").rstrip(".") or "0",
            "Stok Kartı",
            kdv_metin,
        )

    def _tek_tik(self, event):
        """Satırın herhangi bir yerine tıklanınca tüm satır seçilsin."""
        row = self.tablo.identify_row(event.y)
        if row:
            self.tablo.selection_set(row)
            self.tablo.focus(row)

    def _cift_tik(self, _event=None):
        self.sec()
        return "break"

    def _hover(self, event):
        row = self.tablo.identify_row(event.y)
        if row == self._hover_iid:
            return
        self._hover_temizle()
        if not row:
            return
        # Seçili satırda hover uygulama
        if row in self.tablo.selection():
            return
        try:
            tags = list(self.tablo.item(row, "tags") or ())
            if "hover" not in tags:
                self.tablo.item(row, tags=tuple(tags) + ("hover",))
            self._hover_iid = row
        except tk.TclError:
            pass

    def _hover_temizle(self, _event=None):
        if not self._hover_iid:
            return
        try:
            iid = self._hover_iid
            tags = [t for t in (self.tablo.item(iid, "tags") or ()) if t != "hover"]
            if not tags:
                try:
                    sira = int(iid)
                    tags = ["cift" if sira % 2 else "tek"]
                except ValueError:
                    tags = ["tek"]
            self.tablo.item(iid, tags=tuple(tags))
        except tk.TclError:
            pass
        self._hover_iid = None

    def _odak_tabloya(self, _event=None):
        if self.tablo.get_children():
            self.tablo.focus_set()
            secim = self.tablo.selection()
            if not secim:
                ilk = self.tablo.get_children()[0]
                self.tablo.selection_set(ilk)
                self.tablo.focus(ilk)
            return "break"
        return None

    def _entry_enter(self, _event=None):
        """Enter: sonuç varsa seç, yoksa yenile."""
        if self.tablo.selection() and self._urunler:
            self.sec()
            return "break"
        self.listeyi_yenile()
        if self.tablo.selection():
            self.sec()
        return "break"

    def _klavye_asagi(self, _event=None):
        children = self.tablo.get_children()
        if not children:
            return "break"
        secim = self.tablo.selection()
        if not secim:
            self.tablo.selection_set(children[0])
            self.tablo.focus(children[0])
            self.tablo.see(children[0])
            return "break"
        try:
            idx = children.index(secim[0])
        except ValueError:
            idx = 0
        if idx + 1 < len(children):
            nxt = children[idx + 1]
            self.tablo.selection_set(nxt)
            self.tablo.focus(nxt)
            self.tablo.see(nxt)
        return "break"

    def _klavye_yukari(self, _event=None):
        children = self.tablo.get_children()
        if not children:
            return "break"
        secim = self.tablo.selection()
        if not secim:
            self.tablo.selection_set(children[0])
            self.tablo.focus(children[0])
            return "break"
        try:
            idx = children.index(secim[0])
        except ValueError:
            idx = 0
        if idx > 0:
            prv = children[idx - 1]
            self.tablo.selection_set(prv)
            self.tablo.focus(prv)
            self.tablo.see(prv)
        return "break"

    def sec(self):
        secim = self.tablo.selection()
        if not secim or not self.on_select:
            return
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self._urunler)):
            return
        degerler = self._callback_degerleri(self._urunler[idx])
        callback = self.on_select
        self.on_select = None
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
        stok = StokService.stok_getir(stok.id) or stok
        degerler = self._callback_degerleri(stok)
        # fiyat 0 ise servisten dene
        if degerler[4] in ("0", "0.0", ""):
            fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
            degerler = (
                degerler[0],
                degerler[1],
                degerler[2],
                degerler[3],
                f"{fiyat:f}".rstrip("0").rstrip(".") or "0",
                degerler[5],
                degerler[6] if len(degerler) > 6 else "20",
            )
        callback = self.on_select
        self.on_select = None
        self.destroy()
        if callback:
            callback(degerler)
