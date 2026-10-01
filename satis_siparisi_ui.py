"""Alınan Sipariş kartı — kurumsal, klavye odaklı.

Kaydetmek stok çıkışı veya cari borç oluşturmaz. Sevk/fatura miktarları irsaliye ve
fatura kayıtlarından gelir; bağlı satırın ürünü/birimi değiştirilemez, miktarı
sevk/fatura edilenin altına indirilemez.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from database.satis_siparisi_service import (
    PARA_BIRIMLERI,
    SatisSiparisiService,
    belge_toplamlari,
    decimal,
    satir_hesapla,
    siparis_ilerleme,
)
from satis_irsaliyesi_ui import YENI_NO_METNI, _AkisCubugu, _sayi, _tarih, _tarih_coz, toplam_miktar_ozeti
from satis_tema import (
    ACIK_BG,
    ACIK_SARI,
    BEYAZ,
    CIZGI,
    IKINCIL,
    KOYU_LACIVERT,
    LACIVERT,
    METIN,
    SARI,
    font,
    stil_uygula,
    tk_buton,
    treeview_stil,
)
YESIL = "#1F9D74"
TURUNCU = "#E07B00"
KIRMIZI = "#D64545"
MAVI = "#1565C0"
GRI = "#627D98"

DURUM_RENK = {
    "TASLAK": (GRI, BEYAZ),
    "AÇIK": (MAVI, BEYAZ),
    "KISMİ İRSALİYELİ": (TURUNCU, BEYAZ),
    "İRSALİYELİ": ("#00838F", BEYAZ),
    "KISMİ FATURALI": (SARI, KOYU_LACIVERT),
    "FATURALI": (YESIL, BEYAZ),
    "İPTAL": (KIRMIZI, BEYAZ),
}
BIRIMLER = ("Adet", "Kg", "Gr", "Metre", "Litre", "Paket", "Koli", "Kutu", "Takım", "Set")
MANUEL_KOD = "MANUEL"
MALIYET_ALANLARI = (
    "fifo_birim_maliyeti", "son_alis_birim_maliyeti", "ortalama_birim_maliyeti",
    "agirlikli_ortalama_birim_maliyeti",
)


def para_metni(tutar, pb: str = "TRY") -> str:
    try:
        metin = f"{Decimal(str(tutar or 0)):,.2f}"
    except Exception:
        metin = "0.00"
    metin = metin.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {'TL' if (pb or 'TRY') == 'TRY' else pb}"


KDV_SECENEKLERI = ("0", "1", "10", "20")


def _satir_iskonto_metni(s: dict[str, Any]) -> str:
    from satir_ici_urun_giris import iskonto_metni

    return iskonto_metni(s)


def _iskonto_metni(s: dict[str, Any]) -> str:
    oranlar = [decimal(s.get(k) or 0, "İskonto") for k in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3")]
    dolu = [f"%{_sayi(o)}" for o in oranlar if o > 0]
    return " + ".join(dolu) or "—"


class SatisSiparisiKarti(tk.Toplevel):
    """Alınan sipariş kartı (yeni / aç / düzenle)."""

    def __init__(self, parent, siparis=None, cari=None):
        super().__init__(parent)
        try:
            self._kur(parent, siparis, cari)
        except Exception:
            try:
                self.grab_release()
                self.destroy()
            except tk.TclError:
                pass
            raise

    def _kur(self, parent, siparis, cari):
        self.withdraw()
        self.siparis = None
        self.result = None
        self.cari = None
        self.satirlar: list[dict[str, Any]] = []
        self.girdiler: dict[str, Any] = {}
        self._kaydediliyor = False
        self._kayit_imzasi: tuple | None = None
        self._durum_var = tk.StringVar(value="TASLAK")
        self._musteri_var = tk.StringVar(value="")
        self._musteri_etiket = ""
        self._avans = Decimal("0")
        self.title("Alınan Sipariş")
        stil_uygula(root=self)
        try:
            from database.satis_irsaliyesi_service import SatisIrsaliyesiService

            self.depolar = SatisIrsaliyesiService.depolar() or ["ANA DEPO"]
        except Exception:
            self.depolar = ["ANA DEPO"]
        try:
            from database.doviz_service import DovizService

            self.para_birimleri = list(DovizService.para_birimleri()) or list(PARA_BIRIMLERI)
        except Exception:
            self.para_birimleri = list(PARA_BIRIMLERI)
        if "TRY" not in self.para_birimleri:
            self.para_birimleri.insert(0, "TRY")

        self.configure(bg=ACIK_BG)
        self._ust_baslik()
        self._arac_cubugu()
        self._kaydirilabilir_govde()
        self._baslik_alanlari()
        self._teslimat_alanlari()
        self._satir_alani()
        self._aciklama_ve_toplam()
        self._kisayollar()

        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self, min_genislik=900, min_yukseklik=560, varsayilan_genislik=1320,
            varsayilan_yukseklik=780, maximize=True,
        )
        self.deiconify()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        if siparis is not None:
            guncel = SatisSiparisiService.getir(int(siparis.id))
            if guncel is None:
                raise ValueError("Sipariş bulunamadı; silinmiş olabilir.")
            self._kayit_yukle(guncel)
            self._satir_ici_giris.odakla()
        else:
            if cari is not None:
                self._musteri_ata(cari)
            self._kayit_imzasi = self._imza()
            self.satir_listesini_yenile()
            self._kilit_uygula()
            try:
                self.musteri.focus_set()
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ düzen
    def _ust_baslik(self):
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="x", expand=True, padx=16, pady=(10, 8))
        tk.Label(sol, text="ALINAN SİPARİŞ", bg=LACIVERT, fg=BEYAZ, font=font(17, "bold", self)).pack(anchor="w")
        self._meta_label = tk.Label(sol, text="Yeni sipariş", bg=LACIVERT, fg=ACIK_SARI, font=font(10, root=self))
        self._meta_label.pack(anchor="w")
        self._badge = tk.Label(ust, text="TASLAK", bg=GRI, fg=BEYAZ, font=font(11, "bold", self), padx=12, pady=5)
        self._badge.pack(side="right", padx=16)
        self._ilerleme_badge = tk.Label(ust, text="", bg=LACIVERT, fg=ACIK_SARI, font=font(10, "bold", self))
        self._ilerleme_badge.pack(side="right", padx=4)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")

    def _arac_cubugu(self):
        cubuk = _AkisCubugu(self, bg=ACIK_BG)
        cubuk.pack(fill="x", padx=10, pady=(6, 0))
        self.btn: dict[str, tk.Button] = {}

        def ekle(anahtar, metin, komut, rol):
            self.btn[anahtar] = cubuk.ekle(tk_buton(cubuk, metin, komut, rol=rol))

        ekle("yeni", "Yeni", self.yeni_belge, "yeni")
        ekle("kaydet", "Kaydet (F2)", self.kaydet, "kaydet")
        ekle("onayla", "Kaydet ve Onayla", self.kaydet_ve_onayla, "kaydet")
        ekle("onay_kaldir", "Onayı Kaldır", self.onay_kaldir, "duzenle")
        ekle("irsaliye", "İrsaliyeye Aktar", self.irsaliyeye_aktar, "yeni")
        ekle("fatura", "Faturaya Aktar", self.faturaya_aktar, "yeni")
        ekle("bagli", "Bağlı Evraklar", self.bagli_evraklari_goster, "duzenle")
        ekle("onizleme", "Önizleme", self.onizleme, "yazdir")
        ekle("yazdir", "Yazdır", self.yazdir, "yazdir")
        ekle("pdf", "PDF Kaydet", self.pdf_kaydet, "yazdir")
        ekle("word", "Word Kaydet", self.word_kaydet, "yazdir")
        ekle("iptal", "İptal Et", self.iptal_et, "iptal")
        ekle("sil", "Sil", self.sil, "iptal")
        ekle("kapat", "Kapat", self.kapat, "geri")

    def _kaydirilabilir_govde(self):
        alan = tk.Frame(self, bg=ACIK_BG)
        alan.pack(fill="both", expand=True, padx=8, pady=6)
        self.canvas = tk.Canvas(alan, highlightthickness=0, bg=ACIK_BG)
        dikey = ttk.Scrollbar(alan, orient="vertical", command=self.canvas.yview)
        yatay = ttk.Scrollbar(alan, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        dikey.pack(side="right", fill="y")
        yatay.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = tk.Frame(self.canvas, bg=ACIK_BG)
        pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(pencere, width=max(e.width, self.icerik.winfo_reqwidth())),
        )
        self.canvas.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._fare_tekerlegi))
        self.canvas.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _fare_tekerlegi(self, event):
        try:
            hedef = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            hedef = None
        if hedef is not None and hedef.winfo_class() in ("Treeview", "Text", "TCombobox", "Listbox"):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _panel(self, baslik: str) -> tk.Frame:
        dis = tk.Frame(self.icerik, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        dis.pack(fill="x", pady=4, padx=2)
        ust = tk.Frame(dis, bg=BEYAZ)
        ust.pack(fill="x")
        tk.Frame(ust, bg=SARI, width=4).pack(side="left", fill="y")
        tk.Label(ust, text=baslik, bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self)).pack(side="left", padx=8, pady=4)
        ic = tk.Frame(dis, bg=BEYAZ)
        ic.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return ic

    def _etiket(self, parent, metin, row, col, zorunlu=False):
        tk.Label(
            parent, text=metin + (" *" if zorunlu else ""), bg=BEYAZ,
            fg=KIRMIZI if zorunlu else METIN, font=font(10, root=self),
        ).grid(row=row, column=col, padx=4, pady=3, sticky="w")

    def _girdi(self, parent, row, col, label, field, value="", width=24, zorunlu=False, colspan=1):
        self._etiket(parent, label, row, col * 2, zorunlu)
        widget = ttk.Entry(parent, width=width)
        widget.grid(row=row, column=col * 2 + 1, columnspan=colspan, padx=4, pady=3, sticky="ew")
        if value:
            widget.insert(0, value)
        self.girdiler[field] = widget
        return widget

    def _baslik_alanlari(self):
        frame = self._panel("Sipariş ve Müşteri")
        self._girdi(frame, 0, 0, "Sipariş No", "siparis_no", YENI_NO_METNI, width=20)
        self._girdi(frame, 0, 1, "Sipariş Tarihi", "siparis_tarihi", date.today().strftime("%d.%m.%Y"), width=14, zorunlu=True)
        self._girdi(frame, 0, 2, "Termin Tarihi", "termin_tarihi", date.today().strftime("%d.%m.%Y"), width=14, zorunlu=True)

        self._etiket(frame, "Müşteri Kodu / Adı", 1, 0, True)
        mf = tk.Frame(frame, bg=BEYAZ)
        mf.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        self.musteri = ttk.Entry(mf, textvariable=self._musteri_var)
        self.musteri.pack(side="left", fill="x", expand=True)
        self.musteri.bind("<Return>", self.musteri_ara)
        self._musteri_btn = tk_buton(mf, "Müşteri Ara (F10)", self.musteri_sec, rol="ara")
        self._musteri_btn.pack(side="left", padx=(6, 0))
        self._girdi(frame, 1, 2, "Bakiye", "bakiye", "0,00 TL", width=16)
        self.girdiler["bakiye"].configure(state="readonly")

        self._etiket(frame, "Depo", 2, 0, True)
        self.depo = ttk.Combobox(frame, values=self.depolar, width=18, state="readonly")
        self.depo.grid(row=2, column=1, padx=4, pady=3, sticky="ew")
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")
        self._etiket(frame, "Para Birimi", 2, 2)
        self.para_birimi = ttk.Combobox(frame, values=self.para_birimleri, width=8, state="readonly")
        self.para_birimi.grid(row=2, column=3, padx=4, pady=3, sticky="w")
        self.para_birimi.set("TRY")
        self.para_birimi.bind("<<ComboboxSelected>>", self._para_birimi_degisti)
        self._girdi(frame, 2, 2, "Kur", "kur", "1", width=12)

        self._girdi(frame, 3, 0, "Müşteri Sipariş No", "musteri_siparis_no", width=20)
        self._girdi(frame, 3, 1, "Alınan Avans", "avans", "", width=14)
        self.girdiler["avans"].configure(state="readonly")
        for c in (1, 3, 5):
            frame.columnconfigure(c, weight=1)
        sira = [self.musteri, self.depo, self.para_birimi, self.girdiler["kur"], self.girdiler["musteri_siparis_no"]]
        self.girdiler["siparis_tarihi"].bind("<Return>", lambda _e: self._odak(self.girdiler["termin_tarihi"]))
        self.girdiler["termin_tarihi"].bind("<Return>", lambda _e: self._odak(self.musteri))
        for onceki, sonraki in zip(sira[1:], sira[2:]):
            onceki.bind("<Return>", lambda _e, s=sonraki: self._odak(s))
        self.girdiler["musteri_siparis_no"].bind("<Return>", lambda _e: self._odak(self.girdiler["teslimat_adresi"]))

    def _teslimat_alanlari(self):
        frame = self._panel("Teslimat ve Koşullar")
        self._girdi(frame, 0, 0, "Teslimat Adresi", "teslimat_adresi", width=50, colspan=3)
        self._girdi(frame, 1, 0, "İl", "teslimat_il", width=16)
        self._girdi(frame, 1, 1, "İlçe", "teslimat_ilce", width=16)
        self._girdi(frame, 2, 0, "Teslim Koşulu", "teslim_kosulu", width=30)
        self._girdi(frame, 2, 1, "Ödeme Koşulu", "odeme_kosulu", width=30)
        for c in (1, 3):
            frame.columnconfigure(c, weight=1)
        sira = ["teslimat_adresi", "teslimat_il", "teslimat_ilce", "teslim_kosulu", "odeme_kosulu"]
        for onceki, sonraki in zip(sira, sira[1:]):
            self.girdiler[onceki].bind("<Return>", lambda _e, s=sonraki: self._odak(self.girdiler[s]))
        self.girdiler["odeme_kosulu"].bind("<Return>", lambda _e: (self._satir_ici_giris.odakla(), "break")[1])

    def _satir_alani(self):
        frame = self._panel("Ürün Satırları")
        ust = tk.Frame(frame, bg=BEYAZ)
        ust.pack(fill="x", pady=(0, 4))
        tk.Label(
            ust,
            text="Son satıra barkod okutun, ürün kodu veya adı yazın · F10 stok listesi · "
            "Enter/Tab alanlar arasında ilerler · sağ tık: satır işlemleri",
            bg=BEYAZ, fg=IKINCIL, font=font(9, root=self),
        ).pack(side="left")
        self._satir_butonlari = [
            tk_buton(ust, "Satırı Sil (Del)", self.satir_kaldir, rol="iptal"),
            tk_buton(ust, "Satırı Çoğalt", self.satir_cogalt, rol="duzenle"),
            tk_buton(ust, "Araya Satır Ekle", self.araya_satir_ekle, rol="duzenle"),
        ]
        for b in reversed(self._satir_butonlari):
            b.pack(side="right", padx=3)

        tablo_alan = tk.Frame(frame, bg=BEYAZ)
        tablo_alan.pack(fill="both", expand=True)
        kolonlar = (
            "sira", "kod", "ad", "miktar", "birim", "fiyat", "iskonto", "kdv", "net", "toplam", "termin",
            "sevk", "fatura", "kalan_sevk", "kalan_fatura", "aciklama",
        )
        basliklar = (
            "#", "Ürün Kodu", "Ürün Adı", "Miktar", "Birim", "Birim Fiyat", "İskonto", "KDV%",
            "Tutar (KDV Hariç)", "Tutar (KDV Dahil)", "Termin", "Sevk Edilen", "Faturalanan",
            "Kalan Sevk", "Kalan Fatura", "Açıklama",
        )
        genislikler = (36, 100, 240, 70, 60, 95, 90, 45, 115, 115, 80, 80, 80, 80, 80, 150)
        self.satir_tablosu = ttk.Treeview(tablo_alan, columns=kolonlar, show="headings", height=10, selectmode="browse")
        treeview_stil(self.satir_tablosu)
        sag = {"miktar", "fiyat", "net", "toplam", "sevk", "fatura", "kalan_sevk", "kalan_fatura"}
        for col, label, gen in zip(kolonlar, basliklar, genislikler):
            self.satir_tablosu.heading(col, text=label)
            self.satir_tablosu.column(col, width=gen, minwidth=36, anchor="e" if col in sag else "w", stretch=(col == "ad"))
        self.satir_tablosu.tag_configure("tamam", foreground=YESIL)
        yatay = ttk.Scrollbar(tablo_alan, orient="horizontal", command=self.satir_tablosu.xview)
        dikey = ttk.Scrollbar(tablo_alan, orient="vertical", command=self.satir_tablosu.yview)
        self.satir_tablosu.configure(xscrollcommand=yatay.set, yscrollcommand=dikey.set)
        self.satir_tablosu.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        tablo_alan.rowconfigure(0, weight=1)
        tablo_alan.columnconfigure(0, weight=1)
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_kaldir())
        self._satir_ici_kur()

    def _satir_ici_kur(self):
        from satir_ici_urun_giris import HucreAlani, SatirHucreDuzenleyici, SatirIciUrunGirisi

        self._satir_ici_giris = SatirIciUrunGirisi(
            self,
            self.satir_tablosu,
            urun_ekle=self._satir_ici_urun_ekle,
            kolonlar={"kod": "kod", "ad": "ad"},
            manuel_ekle=self.manuel_satir_ekle,
            urun_degistir=self._satir_urun_degistir,
            kilitli=lambda: not self._duzenlenebilir(),
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            depo=lambda: self.depo.get() or "",
            satir_menusu=self._satir_menusu,
        )
        manuel = lambda i: bool(self.satirlar[i].get("is_manual_item"))  # noqa: E731
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("ad", "metin", izin=manuel, deger=lambda i: self.satirlar[i].get("urun_adi") or ""),
                HucreAlani("miktar", deger=lambda i: _sayi(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._satir_birimleri, serbest=False),
                HucreAlani("fiyat", deger=lambda i: _sayi(self.satirlar[i].get("birim_fiyat") or 0)),
                HucreAlani("iskonto", "metin", deger=lambda i: _satir_iskonto_metni(self.satirlar[i])),
                HucreAlani("kdv", "secim", secenekler=lambda _i: KDV_SECENEKLERI, serbest=True,
                           deger=lambda i: _sayi(self.satirlar[i].get("kdv_orani") or 0)),
                HucreAlani("termin", "metin", deger=lambda i: _tarih(self.satirlar[i].get("termin"))),
                HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
            ],
            uygula=self.satir_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            kilitli=lambda: not self._duzenlenebilir(),
            bitince=self._satir_ici_giris.odakla,
        )

    def _aciklama_ve_toplam(self):
        frame = self._panel("Açıklama ve Toplamlar")
        sol = tk.Frame(frame, bg=BEYAZ)
        sol.pack(side="left", fill="both", expand=True)
        tk.Label(sol, text="Açıklama (sipariş formunda görünür)", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(anchor="w")
        self.aciklama = tk.Text(sol, height=5, width=60, relief="solid", bd=1, wrap="word")
        self.aciklama.pack(fill="both", expand=True, padx=(0, 10))
        sag = tk.Frame(frame, bg=ACIK_SARI, padx=12, pady=8)
        sag.pack(side="right", fill="y")
        self._toplam_lbl: dict[str, tk.Label] = {}
        for i, (anahtar, metin) in enumerate((
            ("kalem", "Kalem"), ("miktar", "Toplam Miktar"), ("ara", "Ara Toplam"), ("iskonto", "İskonto"),
            ("net", "Matrah"), ("kdv", "KDV"), ("genel", "Genel Toplam"),
        )):
            kalin = anahtar == "genel"
            tk.Label(sag, text=metin, bg=ACIK_SARI, fg=KOYU_LACIVERT, font=font(10, "bold" if kalin else "normal", self)).grid(row=i, column=0, sticky="w")
            lbl = tk.Label(sag, text="", bg=ACIK_SARI, fg=KOYU_LACIVERT, font=font(11 if kalin else 10, "bold", self), anchor="e")
            lbl.grid(row=i, column=1, sticky="e", padx=(16, 0))
            self._toplam_lbl[anahtar] = lbl

    def _kisayollar(self):
        self.bind("<F2>", lambda _e: self.kaydet())
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<F10>", lambda _e: self.musteri_sec())
        self.bind("<F3>", self.urun_arama_ac)
        self.bind("<Escape>", lambda _e: self.kapat())

    def _odak(self, widget):
        try:
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.selection_range(0, "end")
        except tk.TclError:
            pass
        return "break"

    # ------------------------------------------------------------ durum/kilit
    def _durum(self) -> str:
        return (getattr(self.siparis, "durum", None) or "TASLAK") if self.siparis else "TASLAK"

    def _iptal(self) -> bool:
        return self.siparis is not None and self._durum() == "İPTAL"

    def _bagli(self) -> bool:
        return self.siparis is not None and any(
            decimal(s.get("irsaliyelenen") or 0, "S") > 0 or decimal(s.get("faturalanan") or 0, "F") > 0
            for s in self.satirlar
        )

    def _duzenlenebilir(self) -> bool:
        return not self._iptal()

    def _kilit_uygula(self):
        duz = self._duzenlenebilir()
        kayitli = self.siparis is not None
        bagli = self._bagli()
        durum = self._durum()
        durumlar = {
            "kaydet": duz,
            "onayla": duz and durum == "TASLAK",
            "onay_kaldir": kayitli and durum not in ("TASLAK", "İPTAL") and not bagli,
            "irsaliye": kayitli and duz,
            "fatura": kayitli and duz,
            "bagli": kayitli,
            "iptal": kayitli and duz,
            "sil": kayitli and not bagli,
        }
        for anahtar, aktif in durumlar.items():
            try:
                self.btn[anahtar].configure(state="normal" if aktif else "disabled")
            except (KeyError, tk.TclError):
                pass
        giris = "normal" if duz else "disabled"
        for alan, w in self.girdiler.items():
            if alan in ("bakiye", "avans"):
                continue
            if alan == "siparis_no" and kayitli:
                w.configure(state="readonly")
            elif alan == "kur":
                w.configure(state=giris if self.para_birimi.get() != "TRY" else "disabled")
            else:
                w.configure(state=giris)
        self.musteri.configure(state="normal" if duz and not bagli else "disabled")
        self._musteri_btn.configure(state="normal" if duz and not bagli else "disabled")
        self.depo.configure(state="readonly" if duz else "disabled")
        self.para_birimi.configure(state="readonly" if duz and not bagli else "disabled")
        for b in self._satir_butonlari:
            b.configure(state="normal" if duz else "disabled")
        if not duz:
            self._hucre.kapat()
        self._satir_ici_giris.tabloya_ekle()
        self.aciklama.configure(state="normal" if duz else "disabled")
        self._durum_rozet_guncelle()
        self._meta_yenile()

    def _meta_yenile(self):
        if self.siparis is None:
            self._meta_label.configure(text="Yeni sipariş — kaydedilince TASLAK olur; stok ve cari hareketi oluşturmaz")
            self._ilerleme_badge.configure(text="")
            return
        parcalar = [self.siparis.siparis_no or ""]
        if getattr(self.siparis, "musteri_siparis_no", None):
            parcalar.append(f"Müşteri ref: {self.siparis.musteri_siparis_no}")
        if self._iptal():
            parcalar.append("İptal edildi — salt okunur")
        elif self._bagli():
            parcalar.append("Sevk/fatura bağlantısı var — müşteri, para birimi ve bağlı satırların ürünü değiştirilemez")
        else:
            parcalar.append("Stok ve cari hareketi yok")
        self._meta_label.configure(text="  |  ".join(p for p in parcalar if p))
        self._ilerleme_badge.configure(text=siparis_ilerleme(self.siparis))

    def _durum_rozet_guncelle(self):
        d = self._durum()
        bg, fg = DURUM_RENK.get(d, (GRI, BEYAZ))
        self._badge.configure(text=d, bg=bg, fg=fg)

    # --------------------------------------------------------- değişiklik izi
    def _imza(self) -> tuple:
        alanlar = tuple(
            (k, w.get()) for k, w in sorted(self.girdiler.items()) if k not in ("bakiye", "avans", "siparis_no")
        )
        no = self.girdiler["siparis_no"].get() if self.siparis is None else ""
        satirlar = tuple(
            tuple(str(s.get(k) if s.get(k) is not None else "") for k in (
                "id", "urun_kodu", "urun_adi", "miktar", "birim", "birim_fiyat", "iskonto_orani",
                "iskonto_orani_2", "iskonto_orani_3", "kdv_orani", "termin", "aciklama", "is_manual_item",
            ))
            for s in self.satirlar
        )
        return (
            alanlar, no, self.aciklama.get("1.0", "end").strip(), satirlar, self.depo.get(),
            self.para_birimi.get(), getattr(self.cari, "id", None),
        )

    def degisiklik_var(self) -> bool:
        if not self._duzenlenebilir():
            return False
        if self.siparis is None and not self.satirlar and self.cari is None:
            return False
        return self._kayit_imzasi is None or self._imza() != self._kayit_imzasi

    def _kaydetmeyi_sor(self, islem: str) -> bool:
        if not self.degisiklik_var():
            return True
        cevap = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklik",
            f"Siparişte kaydedilmemiş değişiklikler var.\n{islem} önce kaydedilsin mi?\n\n"
            "Evet: kaydet ve devam et   Hayır: kaydetmeden devam et   İptal: geri dön",
            parent=self,
        )
        if cevap is None:
            return False
        if cevap:
            return self.kaydet(sessiz=True)
        return True

    def kapat(self):
        if not self._kaydetmeyi_sor("Kapatmadan"):
            return
        self.destroy()

    def destroy(self):
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()

    # --------------------------------------------------------------- müşteri
    def musteri_ara(self, _event=None):
        """Müşteri kodu tam eşleşirse doğrudan seçer; aksi halde ayrıntılı arama açılır."""
        if not self._duzenlenebilir() or self._bagli():
            return "break"
        metin = self._musteri_var.get().strip()
        if self.cari is not None and metin == self._musteri_etiket:
            return self._odak(self.depo)
        if not metin:
            return self.musteri_sec()
        try:
            from database.cari_service import CariService

            aday = next(
                (c for c in CariService.aktif_musteriler() if (c.cari_kodu or "").casefold() == metin.casefold()),
                None,
            )
        except Exception:
            aday = None
        if aday is not None:
            self._musteri_ata(aday)
            return self._odak(self.depo)
        return self.musteri_sec(ara=metin)

    def musteri_sec(self, ara: str = ""):
        if not self._duzenlenebilir() or self._bagli():
            return "break"
        try:
            from app import MusteriSecimDialog
            from database.cari_service import CariService

            musteriler = sorted(
                CariService.aktif_musteriler(),
                key=lambda c: ((c.unvan or "").casefold(), (c.cari_kodu or "").casefold()),
            )[:80]
            try:
                bakiyeler = CariService.musteri_bakiyeleri_toplu([c.id for c in musteriler])
            except Exception:
                bakiyeler = {}
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Müşteri listesi açılamadı.\n{exc}", parent=self)
            return "break"
        dialog = MusteriSecimDialog(
            self, musteriler=musteriler, bakiyeler=bakiyeler, ara=ara, on_select=self._musteri_ata, canli_arama=True,
        )
        self.wait_window(dialog)
        if self.cari is not None:
            self._odak(self.depo)
        return "break"

    def _musteri_ata(self, cari):
        if cari is None:
            return
        onceki = self.cari
        if onceki is not None and int(onceki.id) != int(cari.id) and self._bagli():
            messagebox.showwarning(
                "Müşteri değiştirilemez",
                "Sevk veya fatura bağlantısı olan siparişin müşterisi değiştirilemez.",
                parent=self,
            )
            return
        self.cari = cari
        self._musteri_etiket = f"{cari.cari_kodu} - {cari.unvan}"
        self._musteri_var.set(self._musteri_etiket)
        self.bakiye_guncelle()
        if onceki is None or int(onceki.id) != int(cari.id):
            zorla = onceki is not None
            for alan, kaynak in (("teslimat_adresi", "adres"), ("teslimat_il", "il"), ("teslimat_ilce", "ilce")):
                w = self.girdiler[alan]
                if zorla or not w.get().strip():
                    w.delete(0, "end")
                    w.insert(0, getattr(cari, kaynak, None) or "")

    def bakiye_guncelle(self):
        try:
            from database.satis_irsaliyesi_service import SatisIrsaliyesiService

            bakiye = SatisIrsaliyesiService.mevcut_bakiye(self.cari.id) if self.cari else Decimal("0")
        except Exception:
            bakiye = Decimal("0")
        w = self.girdiler["bakiye"]
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, para_metni(bakiye))
        w.configure(state="readonly")

    def _para_birimi_degisti(self, _event=None):
        pb = self.para_birimi.get() or "TRY"
        kur = self.girdiler["kur"]
        kur.configure(state="normal")
        kur.delete(0, "end")
        if pb == "TRY":
            kur.insert(0, "1")
        else:
            try:
                from database.doviz_service import DovizService

                tarih = _tarih_coz(self.girdiler["siparis_tarihi"].get(), "Sipariş tarihi", zorunlu=False) or date.today()
                deger = DovizService.kur_degeri(tarih, pb, varsayilan=None)
            except Exception:
                deger = None
            if deger:
                kur.insert(0, _sayi(deger))
        kur.configure(state="normal" if pb != "TRY" else "disabled")
        self.satir_listesini_yenile()
        if pb != "TRY" and not kur.get().strip():
            messagebox.showinfo("Kur", f"{pb} için kayıtlı kur bulunamadı; kuru elle girin.", parent=self)
            self._odak(kur)

    def _kur_degeri(self) -> Decimal:
        if (self.para_birimi.get() or "TRY") == "TRY":
            return Decimal("1")
        try:
            kur = decimal(self.girdiler["kur"].get() or 0, "Kur", Decimal("0"))
        except ValueError:
            return Decimal("0")
        return kur

    def _tl_fiyati_belge_parasina(self, fiyat):
        if fiyat in (None, ""):
            return None
        kur = self._kur_degeri()
        fiyat = decimal(fiyat, "Fiyat", Decimal("0"))
        if (self.para_birimi.get() or "TRY") == "TRY":
            return fiyat
        if kur <= 0:
            return None
        return (fiyat / kur).quantize(Decimal("0.0001"))

    # ----------------------------------------------------------------- ürün
    def urun_arama_ac(self, _event=None):
        if self._duzenlenebilir():
            self._satir_ici_giris.stok_listesi_ac()
        return "break"

    def stok_listesi_ac(self):
        if self._duzenlenebilir():
            self._satir_ici_giris.stok_listesi_ac("")

    def _birim_secenekleri(self, kod: str, zorunlu_birim: str | None = None) -> list[str]:
        if zorunlu_birim:
            return [zorunlu_birim]
        try:
            from fatura_satir_birim_service import stok_aktif_birimleri

            return stok_aktif_birimleri(kod) or ["Adet"]
        except Exception:
            return ["Adet"]

    def _satir_birimleri(self, idx: int) -> list[str]:
        s = self.satirlar[idx]
        if s.get("is_manual_item"):
            return list(BIRIMLER)
        return self._birim_secenekleri(s.get("urun_kodu") or "", s.get("birim") if self._satir_bagli_mi(s) else None)

    def _cari_fiyati(self, kod: str, birim: str, varsayilan=None):
        """Cari fiyat kuralları (belge para birimine çevrilmiş); bulunamazsa varsayılan."""
        fiyat = None
        try:
            from fatura_satir_birim_service import birim_satis_fiyati

            fiyat = birim_satis_fiyati(kod, birim or "Adet", musteri=self.cari, varsayilan=None)
        except Exception:
            fiyat = None
        if fiyat in (None, ""):
            fiyat = varsayilan
        if fiyat in (None, ""):
            return None
        return self._tl_fiyati_belge_parasina(fiyat)

    def _stok_karti(self, kod: str):
        from database.stok_service import StokService

        return next((s for s in StokService.stoklari_ara(kod) if (s.stok_kodu or "") == kod), None)

    def _satir_bagli_mi(self, s: dict[str, Any]) -> bool:
        return decimal(s.get("irsaliyelenen") or 0, "S") > 0 or decimal(s.get("faturalanan") or 0, "F") > 0

    def _degerlerden_satir(self, degerler) -> dict[str, Any]:
        from satir_ici_urun_giris import HIZLI_STOK_KAYNAGI, ondalik

        kod = (degerler[0] if degerler else "") or ""
        ad = (degerler[1] if len(degerler) > 1 else "") or ""
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        ipucu = degerler[4] if len(degerler) > 4 else None
        kaynak = degerler[5] if len(degerler) > 5 else ""
        kdv_metin = degerler[6] if len(degerler) > 6 else None
        if not kod:
            raise ValueError("Ürün kodu boş.")
        if kaynak == HIZLI_STOK_KAYNAGI and ipucu not in (None, ""):
            fiyat = self._tl_fiyati_belge_parasina(ipucu)
        else:
            fiyat = self._cari_fiyati(kod, birim, ipucu)
        try:
            kdv = ondalik(kdv_metin, Decimal("20")) if kdv_metin not in (None, "") else Decimal("20")
        except ValueError:
            kdv = Decimal("20")
        return {
            "urun_kodu": kod, "urun_adi": ad, "birim": birim, "miktar": Decimal("1"),
            "birim_fiyat": fiyat if fiyat is not None else Decimal("0"),
            "iskonto_orani": 0, "iskonto_orani_2": 0, "iskonto_orani_3": 0, "kdv_orani": kdv,
            "termin": None, "aciklama": "", "is_manual_item": False,
        }

    def urun_secildi(self, values):
        """UrunSecDialog geri çağrısı: ürünü yeni satır olarak ekler."""
        self._satir_ici_urun_ekle(values, None)

    def _satir_ici_urun_ekle(self, degerler, konum: int | None) -> int | None:
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni, toplu_ekleme_mi

        if not self._duzenlenebilir():
            return None
        veri = self._degerlerden_satir(degerler)
        if not self._stok_satiri_hazirla(veri):
            return None
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            adaylar = [s if not self._satir_bagli_mi(s) else {**s, "siparis_satiri_id": -1} for s in self.satirlar]
            idx = birlesecek_satir(adaylar, veri, fiyat_alani="birim_fiyat", ek_alanlar=("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"))
            if idx is not None:
                s = self.satirlar[idx]
                s["miktar"] = decimal(s.get("miktar") or 0, "Miktar") + Decimal("1")
                if not toplu_ekleme_mi(self):
                    self.satir_listesini_yenile()
                return idx
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        if not toplu_ekleme_mi(self):
            self.satir_listesini_yenile()
        return idx

    def _satir_toplu_yenile(self):
        self.satir_listesini_yenile()

    def manuel_satir_ekle(self, ad: str = "", konum: int | None = None) -> int | None:
        """Stokta olmayan ürün satırı (ürün adı ve birim zorunlu)."""
        if not self._duzenlenebilir():
            return None
        ad = (ad or "").strip()
        if not ad:
            ad = (simpledialog.askstring("Manuel kalem", "Stokta olmayan ürünün adı:", parent=self) or "").strip()
        if not ad:
            return None
        veri = {
            "urun_kodu": MANUEL_KOD, "urun_adi": ad, "birim": "Adet", "miktar": Decimal("1"),
            "birim_fiyat": Decimal("0"), "iskonto_orani": 0, "iskonto_orani_2": 0, "iskonto_orani_3": 0,
            "kdv_orani": Decimal("20"), "termin": None, "aciklama": "", "is_manual_item": True,
            "stock_pending": True,
        }
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        self.satir_listesini_yenile()
        return idx

    def _satir_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)) or not self._duzenlenebilir():
            return False
        eski = self.satirlar[idx]
        if self._satir_bagli_mi(eski):
            messagebox.showwarning(
                "Bağlı satır",
                "Sevk veya fatura edilmiş satırın ürünü değiştirilemez.\n"
                f"Bağlı evrak: {self._satir_bagli_metni(eski)}",
                parent=self,
            )
            return False
        try:
            veri = self._degerlerden_satir(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        if not self._stok_satiri_hazirla(veri):
            return False
        veri["miktar"] = eski.get("miktar") or Decimal("1")
        veri["termin"] = eski.get("termin")
        veri["aciklama"] = eski.get("aciklama") or ""
        for anahtar in ("id", "delivery_term_days", "delivery_term_note"):
            if anahtar in eski:
                veri[anahtar] = eski[anahtar]
        self.satirlar[idx] = veri
        self.satir_listesini_yenile()
        return True

    def satir_hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        """Hücre editöründen gelen değer; geçersizse ValueError (satır değişmez)."""
        from satir_ici_urun_giris import iskonto_metni_coz

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        bagli = self._satir_bagli_mi(s)
        yeni = dict(s)
        if kolon == "ad":
            if not metin:
                raise ValueError("Stokta olmayan ürün için ürün adı zorunludur.")
            yeni["urun_adi"] = metin
        elif kolon == "miktar":
            miktar = decimal(metin or 0, "Miktar")
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            sevk = decimal(s.get("irsaliyelenen") or 0, "S")
            fat = decimal(s.get("faturalanan") or 0, "F")
            if miktar < max(sevk, fat):
                raise ValueError(
                    f"Miktar {_sayi(max(sevk, fat))} altına indirilemez (sevk edilen {_sayi(sevk)}, "
                    f"faturalanan {_sayi(fat)}).\nBağlı evrak: {self._satir_bagli_metni(s)}"
                )
            yeni["miktar"] = miktar
        elif kolon == "birim":
            birim = (metin or "").strip()
            if not birim:
                raise ValueError("Birim zorunludur.")
            if birim.casefold() == (s.get("birim") or "").casefold():
                return
            if bagli:
                raise ValueError(
                    "Sevk veya fatura edilmiş satırın birimi değiştirilemez.\n"
                    f"Bağlı evrak: {self._satir_bagli_metni(s)}"
                )
            yeni["birim"] = birim
            if not s.get("is_manual_item"):
                fiyat = self._cari_fiyati(s.get("urun_kodu") or "", birim)
                if fiyat is not None:
                    yeni["birim_fiyat"] = fiyat
        elif kolon == "fiyat":
            yeni["birim_fiyat"] = decimal(metin or 0, "Birim fiyat", Decimal("0"))
        elif kolon == "iskonto":
            yeni["iskonto_orani"], yeni["iskonto_orani_2"], yeni["iskonto_orani_3"] = iskonto_metni_coz(metin)
        elif kolon == "kdv":
            yeni["kdv_orani"] = decimal((metin or "0").replace("%", ""), "KDV oranı", Decimal("0"))
        elif kolon == "termin":
            yeni["termin"] = _tarih_coz(metin, "Satır termini", zorunlu=False)
        elif kolon == "aciklama":
            yeni["aciklama"] = metin
        else:
            return
        self.satirlar[idx] = yeni
        self.satir_listesini_yenile()

    def _secili_index(self) -> int | None:
        from satir_ici_urun_giris import satir_indeksi

        secim = self.satir_tablosu.selection()
        return satir_indeksi(self.satir_tablosu, secim[0]) if secim else None

    def satir_cogalt(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Çoğaltılacak satırı seçin.", parent=self)
            return "break"
        kopya = {
            k: v for k, v in self.satirlar[idx].items()
            if k not in ("id", "irsaliyelenen", "faturalanan")
        }
        self.satirlar.insert(idx + 1, kopya)
        self.satir_listesini_yenile()
        self._hucre.duzenle(idx + 1, "miktar")
        return "break"

    def araya_satir_ekle(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            self._satir_ici_giris.odakla()
        else:
            self._satir_ici_giris.araya_ekle(idx)
        return "break"

    def _satir_menusu(self, idx: int) -> list:
        ogeler = [
            ("Satırı Düzenle (F2)", lambda: self._hucre.ilk_alana(idx)),
            ("Satırı Çoğalt", self.satir_cogalt),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_kaldir),
        ]
        s = self.satirlar[idx] if 0 <= idx < len(self.satirlar) else {}
        if s and not s.get("is_manual_item"):
            ogeler.insert(1, ("Fiyat Listesinden Seç…", lambda: self.fiyat_secimi_ac(idx=idx)))
            if not self._satir_bagli_mi(s):
                ogeler.insert(1, ("Ürünü Değiştir…", lambda: self._satir_ici_giris.urun_degistir_baslat(idx)))
        return ogeler

    def fiyat_secimi_ac(self, _event=None, idx: int | None = None):
        from app import PriceSelectionDialog

        if idx is None:
            idx = self._secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)) or self.satirlar[idx].get("is_manual_item"):
            messagebox.showinfo("Fiyat", "Önce stoktan ürün satırı seçin.", parent=self)
            return "break"
        kod = self.satirlar[idx].get("urun_kodu") or ""

        def _secildi(fiyat):
            deger = self._tl_fiyati_belge_parasina(fiyat.tutar)
            if deger is not None:
                self.satir_hucre_uygula(idx, "fiyat", _sayi(deger))

        dialog = PriceSelectionDialog(self, kod, on_select=_secildi, fiyat_turu="satis")
        self.wait_window(dialog)
        return "break"

    # ---------------------------------------------------------------- satırlar
    def _stok_satiri_hazirla(self, veri: dict[str, Any]) -> bool:
        """Stok kartını doğrular; ürün kimliği ve şirket içi maliyetleri (kâr analizi) ekler."""
        try:
            kart = self._stok_karti(veri["urun_kodu"])
        except Exception:
            return True
        if kart is None:
            messagebox.showwarning(
                "Ürün bulunamadı",
                f"«{veri['urun_kodu']}» kodlu stok kartı bulunamadı.\n"
                "Ürünü listeden seçin veya stokta olmayan ürün için «Manuel kalem» kullanın.",
                parent=self,
            )
            return False
        veri["product_id"] = getattr(kart, "id", None)
        try:
            from database.stok_service import StokService

            maliyetler = StokService.maliyetler(veri["urun_kodu"], self.depo.get() or "ANA DEPO")
            for alan, anahtar in zip(MALIYET_ALANLARI, ("fifo", "son_alis", "ortalama", "agirlikli")):
                veri[alan] = maliyetler.get(anahtar, 0)
        except Exception:
            pass
        return True

    def _satir_bagli_metni(self, satir: dict[str, Any]) -> str:
        if self.siparis is None or not satir.get("id"):
            return "-"
        try:
            return SatisSiparisiService.bagli_evrak_metni(self.siparis.id, [satir["id"]])
        except Exception:
            return "-"

    def satir_temizle(self):
        """Açık hücre / giriş editörlerini kapatır (satırlar korunur)."""
        self._hucre.kapat()
        self._satir_ici_giris.kapat()
        try:
            self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        except tk.TclError:
            pass
        self.toplam_guncelle()

    def satir_listesini_yenile(self):
        pb = self.para_birimi.get() or "TRY"
        self.satir_tablosu.delete(*self.satir_tablosu.get_children())
        for index, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            h = satir_hesapla(
                miktar, veri.get("birim_fiyat") or 0, veri.get("iskonto_orani") or 0,
                veri.get("iskonto_orani_2") or 0, veri.get("iskonto_orani_3") or 0, veri.get("kdv_orani") or 0,
            )
            sevk = decimal(veri.get("irsaliyelenen") or 0, "S")
            fat = decimal(veri.get("faturalanan") or 0, "F")
            etiketler = ["cift" if index % 2 else "tek"]
            if miktar > 0 and fat >= miktar:
                etiketler.append("tamam")
            ad = veri.get("urun_adi", "")
            if veri.get("is_manual_item"):
                ad = f"{ad}  [stokta yok]"
            self.satir_tablosu.insert(
                "", "end", iid=str(index), tags=tuple(etiketler),
                values=(
                    index + 1, veri.get("urun_kodu", ""), ad, _sayi(miktar), veri.get("birim") or "Adet",
                    para_metni(veri.get("birim_fiyat") or 0, pb), _iskonto_metni(veri), f"{_sayi(veri.get('kdv_orani') or 0)}%",
                    para_metni(h["net"], pb), para_metni(h["toplam"], pb), _tarih(veri.get("termin")),
                    _sayi(sevk), _sayi(fat), _sayi(miktar - sevk), _sayi(miktar - fat), veri.get("aciklama") or "",
                ),
            )
        self._satir_ici_giris.tabloya_ekle()
        self.toplam_guncelle()

    def toplam_guncelle(self):
        satirlar = [dict(s) for s in self.satirlar]
        pb = self.para_birimi.get() or "TRY"
        t = belge_toplamlari(satirlar)
        degerler = {
            "kalem": str(len(satirlar)),
            "miktar": toplam_miktar_ozeti(satirlar),
            "ara": para_metni(t["ara_toplam"], pb),
            "iskonto": para_metni(t["iskonto"], pb),
            "net": para_metni(t["net"], pb),
            "kdv": para_metni(t["kdv"], pb),
            "genel": para_metni(t["genel_toplam"], pb),
        }
        for anahtar, metin in degerler.items():
            self._toplam_lbl[anahtar].configure(text=metin)
        return t

    def satir_duzenle(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Düzenlenecek satırı seçin.", parent=self)
            return "break"
        self._hucre.ilk_alana(idx)
        return "break"

    def satir_kaldir(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Silinecek satırı seçin.", parent=self)
            return "break"
        veri = self.satirlar[idx]
        sevk = decimal(veri.get("irsaliyelenen") or 0, "S")
        fat = decimal(veri.get("faturalanan") or 0, "F")
        if sevk > 0 or fat > 0:
            messagebox.showwarning(
                "Satır silinemez",
                f"«{veri.get('urun_adi')}» satırı sevk ({_sayi(sevk)}) veya fatura ({_sayi(fat)}) edilmiş; silinemez.\n"
                f"Bağlı evrak: {self._satir_bagli_metni(veri)}\n"
                "Önce bağlı evraktaki satırı silin veya evrakı iptal edin.",
                parent=self,
            )
            return "break"
        from satir_ici_urun_giris import satir_editorlerini_kapat, satir_silme_sonrasi_temizle

        satir_editorlerini_kapat(self)
        if messagebox.askyesno("Satırı sil", f"«{veri.get('urun_adi')}» satırı silinsin mi?", parent=self):
            self.satirlar.pop(idx)
            self.satir_temizle()
            self.satir_listesini_yenile()
            satir_silme_sonrasi_temizle(self, self.satir_tablosu)
        return "break"

    # --------------------------------------------------------------- kayıt
    def _veri_topla(self) -> tuple[dict, list]:
        def g(alan):
            return self.girdiler[alan].get().strip()

        tarih = _tarih_coz(g("siparis_tarihi"), "Sipariş tarihi")
        if tarih > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        termin = _tarih_coz(g("termin_tarihi"), "Termin tarihi")
        if termin < tarih:
            raise ValueError("Termin tarihi sipariş tarihinden önce olamaz.")
        if self.cari is None:
            raise ValueError("Müşteri seçin (müşteri kodunu yazıp Enter, F10 veya «Müşteri Ara»).")
        if self._musteri_var.get().strip() != self._musteri_etiket:
            raise ValueError("Müşteri alanı değiştirildi; Enter ile müşteriyi seçin veya F10 ile arayın.")
        if not (self.depo.get() or "").strip():
            raise ValueError("Depo seçin.")
        if not self._hucre.bekleyeni_uygula():
            raise ValueError("Düzenlenen hücredeki değer geçersiz; düzeltin veya Esc ile vazgeçin.")
        self._satir_ici_giris.bekleyeni_uygula()
        if not self.satirlar:
            raise ValueError("En az bir ürün satırı ekleyin.")
        pb = self.para_birimi.get() or "TRY"
        kur = self._kur_degeri()
        if pb != "TRY" and kur <= 0:
            raise ValueError(f"{pb} sipariş için geçerli bir kur girin.")
        veriler = {
            "siparis_tarihi": tarih,
            "termin_tarihi": termin,
            "cari_id": int(self.cari.id),
            "depo": self.depo.get().strip(),
            "para_birimi": pb,
            "kur": kur,
            "aciklama": self.aciklama.get("1.0", "end").strip(),
        }
        for alan in ("teslimat_adresi", "teslimat_il", "teslimat_ilce", "musteri_siparis_no", "teslim_kosulu", "odeme_kosulu"):
            veriler[alan] = g(alan)
        if self.siparis is None:
            ozel = g("siparis_no")
            if ozel and ozel != YENI_NO_METNI:
                veriler["siparis_no"] = ozel
        satirlar = []
        for s in self.satirlar:
            veri = {
                "id": s.get("id"),
                "urun_kodu": s.get("urun_kodu"),
                "urun_adi": s.get("urun_adi"),
                "aciklama": s.get("aciklama") or "",
                "miktar": s.get("miktar"),
                "birim": s.get("birim") or "Adet",
                "birim_satis_fiyati": s.get("birim_fiyat") or 0,
                "iskonto_orani": s.get("iskonto_orani") or 0,
                "iskonto_orani_2": s.get("iskonto_orani_2") or 0,
                "iskonto_orani_3": s.get("iskonto_orani_3") or 0,
                "kdv_orani": s.get("kdv_orani") if s.get("kdv_orani") not in (None, "") else 20,
                "is_manual_item": bool(s.get("is_manual_item")),
                "line_type": "MANUAL_PRODUCT" if s.get("is_manual_item") else "STOCK_PRODUCT",
                "product_id": s.get("product_id"),
                "estimated_delivery_date": s.get("termin"),
                "delivery_term_days": s.get("delivery_term_days"),
                "delivery_term_note": s.get("delivery_term_note"),
                "stock_pending": s.get("stock_pending", bool(s.get("is_manual_item"))),
            }
            for alan in MALIYET_ALANLARI:
                veri[alan] = s.get(alan) or 0
            satirlar.append(veri)
        return veriler, satirlar

    def kaydet(self, sessiz: bool = False, onayla: bool = False) -> bool:
        if self._kaydediliyor:
            return False
        if not self._duzenlenebilir():
            messagebox.showinfo("Kaydet", "İptal edilmiş sipariş değiştirilemez.", parent=self)
            return False
        try:
            veriler, satirlar = self._veri_topla()
        except ValueError as hata:
            messagebox.showwarning("Eksik / hatalı bilgi", str(hata), parent=self)
            return False
        veriler["onayla"] = bool(onayla)
        self._kaydediliyor = True
        for anahtar in ("kaydet", "onayla"):
            try:
                self.btn[anahtar].configure(state="disabled")
            except tk.TclError:
                pass
        try:
            kayit = SatisSiparisiService.kaydet(veriler, satirlar, None, getattr(self.siparis, "id", None))
        except ValueError as hata:
            messagebox.showerror("Sipariş kaydedilemedi", str(hata), parent=self)
            self._kilit_uygula()
            return False
        except Exception as hata:  # noqa: BLE001
            from uygulama_log import hata_yaz

            yol = hata_yaz("Satış siparişi kaydedilemedi", hata)
            messagebox.showerror(
                "Sipariş kaydedilemedi",
                f"Beklenmeyen hata; kayıt yapılmadı.\n{hata}" + (f"\n\nAyrıntı: {yol}" if yol else ""),
                parent=self,
            )
            self._kilit_uygula()
            return False
        finally:
            self._kaydediliyor = False
        self.result = True
        self._kayit_yukle(SatisSiparisiService.getir(kayit.id) or kayit)
        if not sessiz:
            ek = "Sipariş onaylandı; irsaliye ve faturaya aktarılabilir." if onayla else "Durum: " + self._durum()
            messagebox.showinfo("Kaydedildi", f"{self.siparis.siparis_no} kaydedildi.\n{ek}\nStok veya cari hareketi oluşturulmadı.", parent=self)
        return True

    def kaydet_ve_onayla(self):
        if self.siparis is not None and not self.degisiklik_var() and self._durum() == "TASLAK":
            try:
                SatisSiparisiService.onayla(self.siparis.id)
            except ValueError as hata:
                messagebox.showerror("Onay", str(hata), parent=self)
                return False
            self.result = True
            self._yenile()
            messagebox.showinfo("Onay", f"{self.siparis.siparis_no} onaylandı.", parent=self)
            return True
        return self.kaydet(onayla=True)

    def onay_kaldir(self):
        if self.siparis is None:
            return
        if not messagebox.askyesno("Onayı kaldır", f"{self.siparis.siparis_no} TASLAK durumuna alınsın mı?", parent=self):
            return
        try:
            SatisSiparisiService.onay_kaldir(self.siparis.id)
        except ValueError as hata:
            messagebox.showerror("Onay kaldırılamadı", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def _kayit_yukle(self, sp):
        """Kayıtlı siparişi forma yükler; satır kimlikleri korunur."""
        self.siparis = sp
        self._durum_var.set(sp.durum or "TASLAK")
        self._kilitsiz_ac()
        for alan, deger in (
            ("siparis_no", sp.siparis_no or ""),
            ("siparis_tarihi", _tarih(sp.siparis_tarihi)),
            ("termin_tarihi", _tarih(sp.termin_tarihi)),
            ("musteri_siparis_no", getattr(sp, "musteri_siparis_no", None) or ""),
            ("teslimat_adresi", getattr(sp, "teslimat_adresi", None) or ""),
            ("teslimat_il", getattr(sp, "teslimat_il", None) or ""),
            ("teslimat_ilce", getattr(sp, "teslimat_ilce", None) or ""),
            ("teslim_kosulu", getattr(sp, "teslim_kosulu", None) or ""),
            ("odeme_kosulu", getattr(sp, "odeme_kosulu", None) or ""),
        ):
            w = self.girdiler[alan]
            w.delete(0, "end")
            w.insert(0, deger)
        depo = getattr(sp, "depo", None) or (self.depolar[0] if self.depolar else "ANA DEPO")
        if depo not in self.depolar:
            self.depolar.append(depo)
            self.depo.configure(values=self.depolar)
        self.depo.set(depo)
        pb = (getattr(sp, "para_birimi", None) or "TRY").upper()
        if pb not in self.para_birimleri:
            self.para_birimleri.append(pb)
            self.para_birimi.configure(values=self.para_birimleri)
        self.para_birimi.set(pb)
        kur = self.girdiler["kur"]
        kur.delete(0, "end")
        kur.insert(0, _sayi(getattr(sp, "kur", None) or 1))
        if sp.cari is not None:
            self.cari = None
            self._musteri_ata(sp.cari)
            for alan, deger in (
                ("teslimat_adresi", getattr(sp, "teslimat_adresi", None) or ""),
                ("teslimat_il", getattr(sp, "teslimat_il", None) or ""),
                ("teslimat_ilce", getattr(sp, "teslimat_ilce", None) or ""),
            ):
                self.girdiler[alan].delete(0, "end")
                self.girdiler[alan].insert(0, deger)
        self.aciklama.delete("1.0", "end")
        self.aciklama.insert("1.0", sp.aciklama or "")
        self._avans = sum((decimal(t.tutar or 0, "Avans") for t in (sp.tahsilatlar or [])), Decimal("0"))
        av = self.girdiler["avans"]
        av.configure(state="normal")
        av.delete(0, "end")
        av.insert(0, para_metni(self._avans, pb) if self._avans else "—")
        av.configure(state="readonly")
        self.satirlar = []
        for s in sorted(sp.satirlar, key=lambda x: int(x.id or 0)):
            veri = {
                "id": s.id,
                "urun_kodu": s.urun_kodu,
                "urun_adi": s.urun_adi,
                "aciklama": s.aciklama or "",
                "miktar": decimal(s.miktar or 0, "Miktar"),
                "birim": s.birim,
                "birim_fiyat": decimal(s.birim_satis_fiyati or 0, "Fiyat"),
                "iskonto_orani": s.iskonto_orani or 0,
                "iskonto_orani_2": getattr(s, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(s, "iskonto_orani_3", 0) or 0,
                "kdv_orani": s.kdv_orani if s.kdv_orani is not None else 20,
                "termin": getattr(s, "estimated_delivery_date", None),
                "is_manual_item": bool(getattr(s, "is_manual_item", False)),
                "product_id": getattr(s, "product_id", None),
                "stock_pending": bool(getattr(s, "stock_pending", False)),
                "delivery_term_days": getattr(s, "delivery_term_days", None),
                "delivery_term_note": getattr(s, "delivery_term_note", None),
                "irsaliyelenen": decimal(s.irsaliyelenen_miktar or 0, "S"),
                "faturalanan": decimal(s.faturalanan_miktar or 0, "F"),
            }
            for alan in MALIYET_ALANLARI:
                veri[alan] = getattr(s, alan, 0) or 0
            self.satirlar.append(veri)
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()

    def _kilitsiz_ac(self):
        for alan, w in self.girdiler.items():
            if alan not in ("bakiye", "avans"):
                w.configure(state="normal")
        self.aciklama.configure(state="normal")
        self.musteri.configure(state="normal")

    def yeni_belge(self):
        if not self._kaydetmeyi_sor("Yeni siparişe geçmeden"):
            return
        self.siparis = None
        self.cari = None
        self._musteri_etiket = ""
        self._musteri_var.set("")
        self._durum_var.set("TASLAK")
        self._avans = Decimal("0")
        self._kilitsiz_ac()
        for alan, w in self.girdiler.items():
            if alan in ("bakiye", "avans"):
                w.configure(state="normal")
            w.delete(0, "end")
        self.girdiler["siparis_no"].insert(0, YENI_NO_METNI)
        bugun = date.today().strftime("%d.%m.%Y")
        self.girdiler["siparis_tarihi"].insert(0, bugun)
        self.girdiler["termin_tarihi"].insert(0, bugun)
        self.girdiler["kur"].insert(0, "1")
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")
        self.para_birimi.set("TRY")
        self.aciklama.delete("1.0", "end")
        self.bakiye_guncelle()
        self.girdiler["avans"].configure(state="readonly")
        self.satirlar = []
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()
        self._odak(self.musteri)

    # ---------------------------------------------------------- belge işlemleri
    def _kayitli_ve_guncel(self, islem: str) -> bool:
        if self.siparis is not None and not self.degisiklik_var():
            return True
        mesaj = "Sipariş henüz kaydedilmedi." if self.siparis is None else "Siparişte kaydedilmemiş değişiklikler var."
        if not messagebox.askyesno(islem, f"{mesaj}\n«{islem}» için önce kaydedilmesi gerekir. Kaydedilsin mi?", parent=self):
            return False
        return self.kaydet(sessiz=True)

    def _yenile(self):
        if self.siparis is not None:
            guncel = SatisSiparisiService.getir(self.siparis.id)
            if guncel is not None:
                self._kayit_yukle(guncel)

    def _aktarim_hazirla(self, islem: str):
        """Aktarım öncesi: kayıtlı, güncel, iptal değil; TASLAK ise onay istenir."""
        if not self._kayitli_ve_guncel(islem):
            return None
        sp = SatisSiparisiService.getir(self.siparis.id)
        if sp is None:
            messagebox.showerror(islem, "Sipariş bulunamadı.", parent=self)
            return None
        if (sp.durum or "") == "İPTAL":
            messagebox.showwarning(islem, "İptal edilmiş sipariş aktarılamaz.", parent=self)
            return None
        if (sp.durum or "") == "TASLAK":
            if not messagebox.askyesno(
                islem, f"{sp.siparis_no} onaylanmamış (TASLAK). Aktarım için onaylansın mı?", parent=self
            ):
                return None
            try:
                SatisSiparisiService.onayla(sp.id)
            except ValueError as hata:
                messagebox.showerror(islem, str(hata), parent=self)
                return None
            self.result = True
            self._yenile()
            sp = SatisSiparisiService.getir(sp.id)
        return sp

    def irsaliyeye_aktar(self):
        sp = self._aktarim_hazirla("İrsaliyeye Aktar")
        if sp is None:
            return
        from database.kalan_belge_service import secimden_irsaliye_satirlari, siparis_secim_satirlari
        from kismi_belge_secim_ui import kismi_secim_yap

        adaylar = siparis_secim_satirlari(sp, hedef="irsaliye")
        if not adaylar:
            messagebox.showinfo("İrsaliyeye Aktar", "Bu siparişte sevk edilecek kalan miktar yok.", parent=self)
            return
        secim = kismi_secim_yap(
            self, adaylar, baslik="İrsaliyeye Aktar — sipariş satırları",
            aciklama=(
                f"{sp.siparis_no}: bu irsaliyeye alınacak miktarı girin (en fazla kalan sevk). 0 = satırı alma.\n"
                "İrsaliye kaydedilene kadar sipariş sevk edilmiş sayılmaz."
            ),
            onceki_baslik="Sevk edilen", kalan_baslik="Kalan sevk", bu_belge_baslik="Bu irsaliye",
            siparis_baslik="Sipariş miktarı",
        )
        if not secim:
            return
        try:
            satir_override = secimden_irsaliye_satirlari(secim)
        except ValueError as hata:
            messagebox.showerror("İrsaliyeye Aktar", str(hata), parent=self)
            return
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

        dialog = SatisIrsaliyesiDialog(self, siparis=sp, satir_override=satir_override)
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.result = True
        self._yenile()

    def faturaya_aktar(self):
        sp = self._aktarim_hazirla("Faturaya Aktar")
        if sp is None:
            return
        from database.kalan_belge_service import secimden_fatura_satirlari, siparis_secim_satirlari
        from kismi_belge_secim_ui import kismi_secim_yap

        adaylar = siparis_secim_satirlari(sp, hedef="fatura")
        if not adaylar:
            messagebox.showinfo("Faturaya Aktar", "Bu siparişte faturalanacak kalan miktar yok.", parent=self)
            return
        secim = kismi_secim_yap(
            self, adaylar, baslik="Faturaya Aktar — sipariş satırları",
            aciklama=(
                f"{sp.siparis_no}: bu faturaya alınacak miktarı girin (en fazla kalan fatura). 0 = satırı alma.\n"
                "Fatura kaydedilene kadar sipariş faturalanmış sayılmaz."
            ),
            onceki_baslik="Faturalanan", kalan_baslik="Fatura kalanı", bu_belge_baslik="Bu fatura",
            siparis_baslik="Sipariş miktarı",
        )
        if not secim:
            return
        try:
            satir_override = secimden_fatura_satirlari(secim, kaynak="siparis")
        except ValueError as hata:
            messagebox.showerror("Faturaya Aktar", str(hata), parent=self)
            return
        from app import CariDialog, SatisFaturasiDialog

        dialog = SatisFaturasiDialog(self, siparis=sp, satir_override=satir_override, cari_ac=lambda c: CariDialog(self, c))
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.result = True
        self._yenile()

    def bagli_evraklari_goster(self):
        if self.siparis is None:
            return
        kayitlar = SatisSiparisiService.bagli_evraklar(self.siparis.id)
        if not kayitlar:
            messagebox.showinfo("Bağlı Evraklar", "Bu siparişe bağlı irsaliye veya fatura yok.", parent=self)
            return
        dialog = BagliEvrakDialog(self, self.siparis.siparis_no, kayitlar)
        self.wait_window(dialog)
        if dialog.degisti:
            self.result = True
        self._yenile()

    def iptal_et(self):
        if self.siparis is None:
            return
        aktif = [k for k in SatisSiparisiService.bagli_evraklar(self.siparis.id) if not k["iptal"]]
        ek = ""
        if aktif:
            ek = (
                "\n\nBağlı evraklar iptal edilmez ve geçerli kalır: "
                + ", ".join(f"{k['tur']} {k['no']}" for k in aktif)
                + "\nKalan miktarlar artık sevk/fatura beklemez."
            )
        if not messagebox.askyesno("Siparişi iptal et", f"{self.siparis.siparis_no} iptal edilsin mi?{ek}", parent=self):
            return
        sebep = simpledialog.askstring("İptal nedeni", "İptal nedenini yazın (zorunlu):", parent=self)
        if not (sebep or "").strip():
            messagebox.showwarning("İptal", "İptal nedeni girilmeden iptal yapılmaz.", parent=self)
            return
        try:
            SatisSiparisiService.iptal_et(self.siparis.id, sebep=sebep.strip())
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def sil(self):
        if self.siparis is None:
            return
        no = self.siparis.siparis_no
        if not messagebox.askyesno(
            "Siparişi sil",
            f"{no} numaralı sipariş kalıcı olarak silinsin mi?\nSilinen sipariş «Silinen Kayıtlar» günlüğüne yazılır.",
            icon="warning", parent=self,
        ):
            return
        try:
            SatisSiparisiService.sil(self.siparis.id)
        except ValueError as hata:
            messagebox.showerror("Silinemedi", str(hata), parent=self)
            return
        self.result = True
        messagebox.showinfo("Silindi", f"{no} numaralı sipariş silindi.", parent=self)
        self._kayit_imzasi = None
        self.siparis = None
        self.satirlar = []
        self.destroy()

    # ------------------------------------------------------------- çıktılar
    def _cikti(self, islem: str):
        """Kayıtlı veriden çıktı; kaydedilmemiş değişiklik varsa önce kaydetme sorulur."""
        if not self._kayitli_ve_guncel("Çıktı"):
            return None
        from siparis_cikti_ui import cikti_al

        return cikti_al(self, self.siparis.id, islem)

    def onizleme(self):
        return self._cikti("onizleme")

    def yazdir(self):
        return self._cikti("yazdir")

    def pdf_kaydet(self):
        return self._cikti("pdf")

    def word_kaydet(self):
        return self._cikti("word")


class BagliEvrakDialog(tk.Toplevel):
    """Siparişe bağlı irsaliye/faturalar; çift tık ile evrak açılır."""

    def __init__(self, parent, siparis_no: str, kayitlar: list[dict[str, Any]]):
        super().__init__(parent)
        self.degisti = False
        self._kayitlar = {f"{k['tur']}:{k['id']}": k for k in kayitlar}
        self.title(f"{siparis_no} — bağlı evraklar")
        self.configure(bg=BEYAZ)
        self.geometry("720x320")
        self.transient(parent)
        tk.Label(
            self, text=f"{siparis_no} siparişine bağlı irsaliye ve faturalar", bg=LACIVERT, fg=BEYAZ,
            font=font(11, "bold", self), padx=12, pady=8, anchor="w",
        ).pack(fill="x")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        kolonlar = ("tur", "no", "tarih", "durum", "miktar")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=8, selectmode="browse")
        treeview_stil(self.tablo)
        for col, baslik, gen in (
            ("tur", "Evrak", 90), ("no", "Evrak No", 170), ("tarih", "Tarih", 100), ("durum", "Durum", 180),
            ("miktar", "Siparişten Aktarılan Miktar", 170),
        ):
            self.tablo.heading(col, text=baslik)
            self.tablo.column(col, width=gen, anchor="e" if col == "miktar" else "w")
        self.tablo.tag_configure("iptal", foreground=KIRMIZI)
        for anahtar, k in self._kayitlar.items():
            self.tablo.insert(
                "", "end", iid=anahtar, tags=("iptal",) if k["iptal"] else (),
                values=(k["tur"], k["no"], _tarih(k["tarih"]), k["durum"], _sayi(k["miktar"])),
            )
        self.tablo.pack(fill="both", expand=True, padx=10, pady=8)
        self.tablo.bind("<Double-1>", lambda _e: self._ac())
        self.tablo.bind("<Return>", lambda _e: self._ac())
        alt = tk.Frame(self, bg=BEYAZ)
        alt.pack(fill="x", padx=10, pady=(0, 10))
        tk_buton(alt, "Evrakı Aç", self._ac, rol="kaydet").pack(side="right")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        if self._kayitlar:
            ilk = next(iter(self._kayitlar))
            self.tablo.selection_set(ilk)
            self.tablo.focus(ilk)
        self.tablo.focus_set()

    def _ac(self):
        secim = self.tablo.selection()
        if not secim:
            return
        k = self._kayitlar[secim[0]]
        try:
            if k["tur"] == "İrsaliye":
                from database.satis_irsaliyesi_service import SatisIrsaliyesiService
                from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

                belge = SatisIrsaliyesiService.getir(k["id"])
                if belge is None:
                    raise ValueError("İrsaliye bulunamadı; silinmiş olabilir.")
                dialog = SatisIrsaliyesiDialog(self, irsaliye=belge)
            else:
                from app import CariDialog, SatisFaturasiDialog
                from database.satis_faturasi_service import SatisFaturasiService

                belge = SatisFaturasiService.getir(k["id"])
                if belge is None:
                    raise ValueError("Fatura bulunamadı; silinmiş olabilir.")
                dialog = SatisFaturasiDialog(self, fatura=belge, cari_ac=lambda c: CariDialog(self, c))
        except ValueError as hata:
            messagebox.showerror("Evrak", str(hata), parent=self)
            return
        self.wait_window(dialog)
        self.degisti = True
