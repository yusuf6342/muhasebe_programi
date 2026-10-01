"""Kurumsal Satış İrsaliyesi kartı — stok çıkışı yalnızca «Sevk Et» ile.

Kaydet: TASLAK (stok hareketi yok). Sevk Et: İRSALİYE ÇIKIŞ (temel birim).
Faturaya bağlanan irsaliye değiştirilemez / silinemez / iptal edilemez.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from database.satis_irsaliyesi_service import (
    SatisIrsaliyesiService,
    durum_gosterim,
    faturalama_durumu,
)
from database.satis_siparisi_service import decimal
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
    "HAZIRLANIYOR": (TURUNCU, BEYAZ),
    "SEVKİYATA HAZIR": ("#00838F", BEYAZ),
    "SEVK EDİLDİ": (MAVI, BEYAZ),
    "AÇIK": (MAVI, BEYAZ),
    "KISMEN TESLİM EDİLDİ": ("#6A1B9A", BEYAZ),
    "TESLİM EDİLDİ": (YESIL, BEYAZ),
    "KISMİ FATURALANDI": (SARI, KOYU_LACIVERT),
    "FATURALANDI": (YESIL, BEYAZ),
    "İPTAL": (KIRMIZI, BEYAZ),
    "İADE": ("#6D4C41", BEYAZ),
}

YENI_NO_METNI = "Otomatik oluşturulacak"


def _para(tutar) -> str:
    try:
        return f"{float(tutar or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"
    except Exception:
        return "0,00 TL"


def _tarih(d) -> str:
    if d is None:
        return ""
    if isinstance(d, (date, datetime)):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _sayi(deger) -> str:
    try:
        d = Decimal(str(deger if deger not in (None, "") else 0))
    except Exception:
        return str(deger or "")
    metin = f"{d:f}"
    if "." in metin:
        metin = metin.rstrip("0").rstrip(".")
    return (metin or "0").replace(".", ",")


def _tarih_coz(metin: str, alan: str, *, zorunlu: bool = True) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        if zorunlu:
            raise ValueError(f"{alan} girin (GG.AA.YYYY).")
        return None
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"{alan} geçersiz: «{metin}». GG.AA.YYYY biçiminde yazın (ör. {date.today():%d.%m.%Y}).")


def toplam_miktar_ozeti(satirlar) -> str:
    toplamlar: dict[str, Decimal] = {}
    for s in satirlar or []:
        birim = (s.get("birim") or "Adet").strip() or "Adet"
        try:
            miktar = decimal(s.get("miktar") or 0, "Miktar")
        except ValueError:
            continue
        toplamlar[birim] = toplamlar.get(birim, Decimal("0")) + miktar
    return " · ".join(f"{_sayi(m)} {b}" for b, m in toplamlar.items()) or "0"


class _AkisCubugu(tk.Frame):
    """Butonları pencere genişliğine göre satırlara saran araç çubuğu."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._butonlar: list[tk.Widget] = []
        self._son_genislik = 0
        self.bind("<Configure>", self._yerlestir)

    def ekle(self, buton: tk.Widget) -> tk.Widget:
        self._butonlar.append(buton)
        self.after_idle(self._yerlestir)
        return buton

    def _yerlestir(self, _e=None):
        genislik = max(self.winfo_width(), 200)
        if _e is not None and genislik == self._son_genislik:
            return
        self._son_genislik = genislik
        satir = sutun = kullanilan = 0
        for b in self._butonlar:
            b.grid_forget()
        for b in self._butonlar:
            w = b.winfo_reqwidth() + 6
            if kullanilan and kullanilan + w > genislik:
                satir += 1
                sutun = kullanilan = 0
            b.grid(row=satir, column=sutun, padx=3, pady=3, sticky="w")
            sutun += 1
            kullanilan += w


class SatisIrsaliyesiDialog(tk.Toplevel):
    """Kurumsal satış irsaliyesi kartı (yeni / aç / düzenle)."""

    def __init__(self, parent, irsaliye=None, siparis=None, cari=None, satir_override=None):
        super().__init__(parent)
        try:
            self._kur(parent, irsaliye, siparis, cari, satir_override)
        except Exception:
            try:
                self.grab_release()
                self.destroy()
            except tk.TclError:
                pass
            raise

    def _kur(self, parent, irsaliye, siparis, cari, satir_override):
        self.withdraw()
        self.irsaliye = None
        self.result = None
        self.cari = None
        self.musteri_map: dict[str, Any] = {}
        self.satirlar: list[dict[str, Any]] = []
        self.girdiler: dict[str, Any] = {}
        self._kaydediliyor = False
        self._kayit_imzasi: tuple | None = None
        self._durum_var = tk.StringVar(value="TASLAK")
        self._is_priced = tk.BooleanVar(value=True)
        self._fiyatli_cikti = tk.BooleanVar(value=False)
        self._musteri_var = tk.StringVar(value="")
        self._siparis_var = tk.StringVar(value="")
        self.title("Satış İrsaliyesi")
        stil_uygula(root=self)
        try:
            self.depolar = SatisIrsaliyesiService.depolar() or ["ANA DEPO"]
        except Exception as exc:
            messagebox.showerror("Satış İrsaliyesi", f"İrsaliye kartı açılamadı.\n\n{exc}", parent=parent)
            self.destroy()
            return

        self.configure(bg=ACIK_BG)
        self._ust_baslik()
        self._arac_cubugu()
        self._kaydirilabilir_govde()
        self._baslik_alanlari()
        self._sevk_adres_alanlari()
        self._satir_alani()
        self._notlar_ve_toplam()
        self._kisayollar()

        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self,
            min_genislik=900,
            min_yukseklik=560,
            varsayilan_genislik=1280,
            varsayilan_yukseklik=760,
            maximize=True,
        )
        self.deiconify()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        if irsaliye is not None:
            self._kayit_yukle(SatisIrsaliyesiService.getir(irsaliye.id) or irsaliye)
        else:
            if siparis is not None and getattr(siparis, "cari", None) is not None:
                self._musteri_ata(siparis.cari, sessiz=True)
            elif cari is not None:
                self._musteri_ata(cari, sessiz=True)
            if satir_override is not None:
                for veri in satir_override:
                    satir = dict(veri)
                    satir.setdefault("siparis_no", getattr(siparis, "siparis_no", "") if siparis else "")
                    satir.setdefault("siparis_id", getattr(siparis, "id", None) if siparis else None)
                    satir.pop("depo", None)
                    self.satirlar.append(satir)
            self._kayit_imzasi = self._imza() if satir_override is None else None
            self.satir_listesini_yenile()
            self._kilit_uygula()
        self._satir_ici_giris.odakla()

    # ------------------------------------------------------------------ düzen
    def _ust_baslik(self):
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="x", expand=True, padx=16, pady=(10, 8))
        tk.Label(
            sol, text="SATIŞ İRSALİYESİ", bg=LACIVERT, fg=BEYAZ, font=font(17, "bold", self)
        ).pack(anchor="w")
        self._meta_label = tk.Label(
            sol, text="Yeni irsaliye", bg=LACIVERT, fg=ACIK_SARI, font=font(10, root=self)
        )
        self._meta_label.pack(anchor="w")
        self._badge = tk.Label(
            ust, text="TASLAK", bg=GRI, fg=BEYAZ, font=font(11, "bold", self), padx=12, pady=5
        )
        self._badge.pack(side="right", padx=16)
        self._fatura_badge = tk.Label(
            ust, text="", bg=LACIVERT, fg=ACIK_SARI, font=font(10, "bold", self)
        )
        self._fatura_badge.pack(side="right", padx=4)
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")

    def _arac_cubugu(self):
        cubuk = _AkisCubugu(self, bg=ACIK_BG)
        cubuk.pack(fill="x", padx=10, pady=(6, 0))
        self.btn: dict[str, tk.Button] = {}

        def ekle(anahtar, metin, komut, rol):
            self.btn[anahtar] = cubuk.ekle(tk_buton(cubuk, metin, komut, rol=rol))

        ekle("yeni", "Yeni", self.yeni_belge, "yeni")
        ekle("kaydet", "Kaydet (F2)", self.kaydet, "kaydet")
        ekle("siparis", "Siparişten Aktar", self.siparisten_aktar, "ara")
        ekle("hazirla", "Sevkiyata Hazırla", self.hazirla, "duzenle")
        ekle("sevk", "Sevk Et (Onayla)", self.sevk_et, "kaydet")
        ekle("sevk_geri", "Sevki Geri Al", self.sevk_geri_al, "duzenle")
        ekle("teslim", "Teslim Edildi", self.teslim_et, "duzenle")
        ekle("fatura", "Faturaya Aktar", self.fatura_olustur, "yeni")
        ekle("faturalar", "Bağlı Faturalar", self.bagli_faturalari_goster, "duzenle")
        ekle("onizleme", "Önizleme", self.onizleme, "yazdir")
        ekle("yazdir", "Yazdır", self.yazdir, "yazdir")
        ekle("pdf", "PDF Kaydet", self.pdf_kaydet, "yazdir")
        ekle("word", "Word Kaydet", self.word_kaydet, "yazdir")
        cubuk.ekle(
            tk.Checkbutton(
                cubuk, text="Fiyatlı çıktı", variable=self._fiyatli_cikti, bg=ACIK_BG, fg=METIN,
                activebackground=ACIK_BG, font=font(9, root=self),
            )
        )
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

        def _bolge(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _genislik(e):
            self.canvas.itemconfigure(pencere, width=max(e.width, self.icerik.winfo_reqwidth()))

        self.icerik.bind("<Configure>", _bolge)
        self.canvas.bind("<Configure>", _genislik)
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
        tk.Label(
            ust, text=baslik, bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self)
        ).pack(side="left", padx=8, pady=4)
        ic = tk.Frame(dis, bg=BEYAZ)
        ic.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return ic

    def _etiket(self, parent, metin, row, col, zorunlu=False):
        tk.Label(
            parent,
            text=metin + (" *" if zorunlu else ""),
            bg=BEYAZ,
            fg=KIRMIZI if zorunlu else METIN,
            font=font(10, root=self),
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
        frame = self._panel("Belge ve Müşteri")
        self._girdi(frame, 0, 0, "İrsaliye No", "irsaliye_no", YENI_NO_METNI, width=20)
        self._girdi(
            frame, 0, 1, "İrsaliye Tarihi", "irsaliye_tarihi", date.today().strftime("%d.%m.%Y"),
            width=14, zorunlu=True,
        )
        self._etiket(frame, "Depo", 0, 4, True)
        self.depo = ttk.Combobox(frame, values=self.depolar, width=18, state="readonly")
        self.depo.grid(row=0, column=5, padx=4, pady=3, sticky="ew")
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")

        self._etiket(frame, "Müşteri", 1, 0, True)
        mf = tk.Frame(frame, bg=BEYAZ)
        mf.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        self.musteri = ttk.Entry(mf, textvariable=self._musteri_var, state="readonly")
        self.musteri.pack(side="left", fill="x", expand=True)
        self.musteri.bind("<Double-1>", lambda _e: self.musteri_sec())
        self._musteri_btn = tk_buton(mf, "Müşteri Ara (F10)", self.musteri_sec, rol="ara")
        self._musteri_btn.pack(side="left", padx=(6, 0))
        self._girdi(frame, 1, 2, "Bakiye", "bakiye", "0,00 TL", width=16)
        self.girdiler["bakiye"].configure(state="readonly")

        self._etiket(frame, "Bağlı Sipariş", 2, 0)
        self.siparis_secimi = ttk.Entry(frame, textvariable=self._siparis_var, state="readonly")
        self.siparis_secimi.grid(row=2, column=1, columnspan=3, padx=4, pady=3, sticky="ew")
        for c in (1, 3, 5):
            frame.columnconfigure(c, weight=1)

    def _sevk_adres_alanlari(self):
        frame = self._panel("Teslimat / Sevk Bilgileri")
        self._girdi(frame, 0, 0, "Teslimat Adresi", "sevk_adresi", width=40, colspan=3)
        self._girdi(frame, 1, 0, "İl", "sevk_il", width=16)
        self._girdi(frame, 1, 1, "İlçe", "sevk_ilce", width=16)
        self._girdi(frame, 1, 2, "Planlanan Teslim", "planlanan_teslim", width=14)
        self._girdi(frame, 2, 0, "Teslim Alacak Kişi", "teslim_kisi")
        self._girdi(frame, 2, 1, "Telefon", "teslim_telefon")
        self._girdi(frame, 2, 2, "Sevkiyat Yöntemi", "sevkiyat_yontemi")
        self._girdi(frame, 3, 0, "Nakliyeci", "nakliyeci")
        self._girdi(frame, 3, 1, "Plaka", "arac_plaka", width=14)
        self._girdi(frame, 3, 2, "Şoför", "sofor_adi")
        self._girdi(frame, 4, 0, "Şoför Telefonu", "sofor_telefon")
        self._girdi(frame, 4, 1, "Takip No", "takip_no")
        for c in (1, 3, 5):
            frame.columnconfigure(c, weight=1)

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
            "sira", "kod", "ad", "miktar", "birim", "fiyat", "iskonto", "kdv", "toplam",
            "siparis", "fatura", "kalan", "lot", "aciklama",
        )
        basliklar = (
            "#", "Ürün Kodu", "Ürün Adı", "Miktar", "Birim", "Birim Fiyat", "İsk%", "KDV%",
            "Tutar", "Sipariş", "Faturalanan", "Fatura Kalanı", "Lot", "Açıklama",
        )
        genislikler = (40, 110, 240, 80, 70, 100, 55, 55, 110, 110, 90, 90, 80, 150)
        self.satir_tablosu = ttk.Treeview(
            tablo_alan, columns=kolonlar, show="headings", height=10, selectmode="browse"
        )
        treeview_stil(self.satir_tablosu)
        for col, label, gen in zip(kolonlar, basliklar, genislikler):
            self.satir_tablosu.heading(col, text=label)
            anchor = "e" if col in ("miktar", "fiyat", "toplam", "fatura", "kalan") else "w"
            self.satir_tablosu.column(col, width=gen, minwidth=40, anchor=anchor, stretch=(col == "ad"))
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
            urun_degistir=self._satir_urun_degistir,
            kilitli=lambda: not self._duzenlenebilir(),
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            depo=lambda: self.depo.get() or "",
            sadece_stokta_ad=True,
            satir_menusu=self._satir_menusu,
        )
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("miktar", deger=lambda i: _sayi(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._satir_birimleri),
                HucreAlani("fiyat", deger=lambda i: _sayi(self.satirlar[i].get("birim_fiyat") or 0)),
                HucreAlani("iskonto", deger=lambda i: _sayi(self.satirlar[i].get("iskonto_orani") or 0)),
                HucreAlani("kdv", "secim", secenekler=lambda _i: ("0", "1", "10", "20"), serbest=True,
                           deger=lambda i: _sayi(self.satirlar[i].get("kdv_orani") or 0)),
                HucreAlani("lot", "metin", deger=lambda i: self.satirlar[i].get("lot_no") or ""),
                HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
            ],
            uygula=self.satir_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            kilitli=lambda: not self._duzenlenebilir(),
            bitince=self._satir_ici_giris.odakla,
        )

    def _notlar_ve_toplam(self):
        frame = self._panel("Açıklama, Notlar ve Toplamlar")
        self._girdi(frame, 0, 0, "Açıklama", "aciklama", width=60, colspan=5)
        for i, metin in enumerate(("Müşteri Notu (çıktıda)", "Sevk Notu (çıktıda)", "İç Not (müşteriye gitmez)")):
            tk.Label(frame, text=metin, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).grid(
                row=1, column=i * 2, columnspan=2, sticky="w", padx=4
            )
        self.musteri_notu = tk.Text(frame, height=3, width=30, relief="solid", bd=1)
        self.sevk_notu = tk.Text(frame, height=3, width=30, relief="solid", bd=1)
        self.ic_not = tk.Text(frame, height=3, width=30, relief="solid", bd=1)
        for i, w in enumerate((self.musteri_notu, self.sevk_notu, self.ic_not)):
            w.grid(row=2, column=i * 2, columnspan=2, padx=4, sticky="ew")
        self.toplam = tk.Label(
            frame, text="", bg=ACIK_SARI, fg=KOYU_LACIVERT, font=font(11, "bold", self),
            anchor="w", padx=10, pady=6,
        )
        self.toplam.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(8, 0), padx=4)
        for c in range(6):
            frame.columnconfigure(c, weight=1)

    def _kisayollar(self):
        self.bind("<F2>", lambda _e: self.kaydet())
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<F10>", lambda _e: self.musteri_sec())
        self.bind("<Escape>", lambda _e: self.kapat())

    # ------------------------------------------------------------ durum/kilit
    def _duzenlenebilir(self) -> bool:
        ir = self.irsaliye
        if ir is None:
            return True
        if (ir.durum or "") == "İPTAL" or getattr(ir, "stok_cikis_yapildi", False):
            return False
        return not any(decimal(s.faturalanan_miktar or 0, "Fatura") > 0 for s in ir.satirlar)

    def _faturali(self) -> bool:
        ir = self.irsaliye
        return bool(ir) and any(decimal(s.faturalanan_miktar or 0, "Fatura") > 0 for s in ir.satirlar)

    def _kilit_uygula(self):
        duz = self._duzenlenebilir()
        ir = self.irsaliye
        kayitli = ir is not None
        iptal = kayitli and (ir.durum or "") == "İPTAL"
        sevkli = kayitli and bool(getattr(ir, "stok_cikis_yapildi", False))
        faturali = self._faturali()
        kalan_var = kayitli and any(
            decimal(s.miktar or 0, "M") - decimal(s.faturalanan_miktar or 0, "F") > 0 for s in ir.satirlar
        )
        durumlar = {
            "kaydet": duz,
            "siparis": duz,
            "hazirla": kayitli and duz and (ir.durum or "") in ("TASLAK", "HAZIRLANIYOR", "AÇIK"),
            "sevk": not iptal and not sevkli,
            "sevk_geri": sevkli and not faturali and not iptal,
            "teslim": sevkli and not iptal and not getattr(ir, "fiili_teslim_tarihi", None),
            "fatura": kayitli and not iptal and kalan_var,
            "faturalar": kayitli,
            "iptal": kayitli and not iptal and not faturali,
            "sil": kayitli and not faturali,
        }
        for anahtar, aktif in durumlar.items():
            try:
                self.btn[anahtar].configure(state="normal" if aktif else "disabled")
            except (KeyError, tk.TclError):
                pass
        giris_durumu = "normal" if duz else "disabled"
        for alan, w in self.girdiler.items():
            if alan == "bakiye":
                continue
            if alan == "irsaliye_no" and kayitli:
                w.configure(state="readonly")
                continue
            w.configure(state=giris_durumu)
        self.depo.configure(state="readonly" if duz else "disabled")
        self._musteri_btn.configure(state="normal" if duz else "disabled")
        for b in self._satir_butonlari:
            b.configure(state="normal" if duz else "disabled")
        if not duz:
            self._hucre.kapat()
        self._satir_ici_giris.tabloya_ekle()
        for t in (self.musteri_notu, self.sevk_notu, self.ic_not):
            t.configure(state="normal" if duz else "disabled")
        self._durum_rozet_guncelle()
        self._meta_yenile()

    def _meta_yenile(self):
        ir = self.irsaliye
        if ir is None:
            self._meta_label.configure(text="Yeni irsaliye — kaydedilince TASLAK olur, stok «Sevk Et» ile düşer")
            self._fatura_badge.configure(text="")
            return
        parcalar = [ir.irsaliye_no or ""]
        if getattr(ir, "stok_cikis_yapildi", False):
            parcalar.append("Stok çıkışı yapıldı")
        else:
            parcalar.append("Stok çıkışı yok")
        if not self._duzenlenebilir():
            if (ir.durum or "") == "İPTAL":
                parcalar.append("İptal edildi — salt okunur")
            elif self._faturali():
                parcalar.append("Faturaya bağlı — değiştirilemez")
            else:
                parcalar.append("Sevk edildi — düzenlemek için «Sevki Geri Al»")
        self._meta_label.configure(text="  |  ".join(p for p in parcalar if p))
        self._fatura_badge.configure(text=faturalama_durumu(ir.satirlar))

    def _durum_rozet_guncelle(self):
        d = self._durum_var.get() or "TASLAK"
        goster = durum_gosterim(d)
        bg, fg = DURUM_RENK.get(d, DURUM_RENK.get(goster, (GRI, BEYAZ)))
        self._badge.configure(text=goster, bg=bg, fg=fg)

    # --------------------------------------------------------- değişiklik izi
    def _imza(self) -> tuple:
        alanlar = tuple(
            (k, w.get()) for k, w in sorted(self.girdiler.items()) if k not in ("bakiye", "irsaliye_no")
        )
        notlar = tuple(t.get("1.0", "end").strip() for t in (self.musteri_notu, self.sevk_notu, self.ic_not))
        satirlar = tuple(
            tuple(str(s.get(k) or "") for k in (
                "irsaliye_satiri_id", "siparis_satiri_id", "urun_kodu", "urun_adi", "miktar", "birim",
                "birim_fiyat", "iskonto_orani", "kdv_orani", "aciklama", "lot_no",
            ))
            for s in self.satirlar
        )
        return (
            alanlar, notlar, satirlar, self.depo.get(), getattr(self.cari, "id", None),
            bool(self._is_priced.get()),
        )

    def degisiklik_var(self) -> bool:
        if not self._duzenlenebilir():
            return False
        if self.irsaliye is None and not self.satirlar and self.cari is None:
            return False
        return self._kayit_imzasi is None or self._imza() != self._kayit_imzasi

    def _kaydetmeyi_sor(self, islem: str) -> bool:
        """True: devam edilebilir. Kaydedilmemiş değişiklik için Evet/Hayır/Vazgeç."""
        if not self.degisiklik_var():
            return True
        cevap = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklik",
            f"İrsaliyede kaydedilmemiş değişiklikler var.\n{islem} önce kaydedilsin mi?\n\n"
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
    def musteri_sec(self):
        if not self._duzenlenebilir():
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
            self,
            musteriler=musteriler,
            bakiyeler=bakiyeler,
            on_select=self._musteri_ata,
            canli_arama=True,
        )
        self.wait_window(dialog)
        return "break"

    def _musteri_ata(self, cari, sessiz: bool = False):
        if cari is None:
            return
        onceki = self.cari
        if onceki is not None and int(onceki.id) != int(cari.id):
            bagli = [s for s in self.satirlar if s.get("siparis_satiri_id")]
            if bagli:
                messagebox.showwarning(
                    "Müşteri değiştirilemez",
                    "Bu irsaliyede başka müşterinin siparişinden aktarılmış satırlar var.\n"
                    "Müşteriyi değiştirmek için önce siparişe bağlı satırları silin.",
                    parent=self,
                )
                return
        self.cari = cari
        etiket = f"{cari.cari_kodu} - {cari.unvan}"
        self.musteri_map = {etiket: cari}
        self._musteri_var.set(etiket)
        self.bakiye_guncelle()
        if onceki is None or int(onceki.id) != int(cari.id):
            self._sevk_adres_cari_doldur(cari, zorla=onceki is not None)

    def _sevk_adres_cari_doldur(self, cari, zorla: bool = False):
        for alan, kaynak in (("sevk_adresi", "adres"), ("sevk_il", "il"), ("sevk_ilce", "ilce")):
            w = self.girdiler[alan]
            if zorla or not w.get().strip():
                w.delete(0, "end")
                w.insert(0, getattr(cari, kaynak, None) or "")

    def bakiye_guncelle(self):
        try:
            bakiye = SatisIrsaliyesiService.mevcut_bakiye(self.cari.id) if self.cari else Decimal("0")
        except Exception:
            bakiye = Decimal("0")
        w = self.girdiler["bakiye"]
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, _para(bakiye))
        w.configure(state="readonly")

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
        return self._birim_secenekleri(s.get("urun_kodu") or "", s.get("birim") if s.get("siparis_satiri_id") else None)

    def _cari_fiyati(self, kod: str, birim: str, varsayilan=None):
        try:
            from fatura_satir_birim_service import birim_satis_fiyati

            fiyat = birim_satis_fiyati(kod, birim or "Adet", musteri=self.cari, varsayilan=None)
        except Exception:
            fiyat = None
        if fiyat in (None, ""):
            fiyat = varsayilan
        if fiyat in (None, ""):
            return None
        return decimal(fiyat, "Fiyat", Decimal("0"))

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
            fiyat = decimal(ipucu, "Fiyat", Decimal("0"))
        else:
            fiyat = self._cari_fiyati(kod, birim, ipucu)
        try:
            kdv = ondalik(kdv_metin, Decimal("20")) if kdv_metin not in (None, "") else Decimal("20")
        except ValueError:
            kdv = Decimal("20")
        return {
            "urun_kodu": kod, "urun_adi": ad, "birim": birim, "miktar": Decimal("1"),
            "birim_fiyat": fiyat if fiyat is not None else Decimal("0"), "iskonto_orani": Decimal("0"),
            "kdv_orani": kdv, "aciklama": "", "lot_no": "", "siparis_satiri_id": None,
        }

    def urun_secildi(self, values):
        """UrunSecDialog geri çağrısı: ürünü yeni satır olarak ekler."""
        self._satir_ici_urun_ekle(values, None)

    def _satir_ici_urun_ekle(self, degerler, konum: int | None) -> int | None:
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni, toplu_ekleme_mi

        if not self._duzenlenebilir():
            return None
        veri = self._degerlerden_satir(degerler)
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            idx = birlesecek_satir(self.satirlar, veri, fiyat_alani="birim_fiyat", ek_alanlar=("iskonto_orani", "lot_no"))
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

    def _satir_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)) or not self._duzenlenebilir():
            return False
        eski = self.satirlar[idx]
        if eski.get("siparis_satiri_id"):
            messagebox.showwarning(
                "Siparişe bağlı satır",
                "Siparişten aktarılan satırın ürünü değiştirilemez.\nSatırı silip yeni ürün ekleyin.",
                parent=self,
            )
            return False
        try:
            veri = self._degerlerden_satir(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        veri["miktar"] = eski.get("miktar") or Decimal("1")
        veri["aciklama"] = eski.get("aciklama") or ""
        veri["lot_no"] = eski.get("lot_no") or ""
        if eski.get("irsaliye_satiri_id"):
            veri["irsaliye_satiri_id"] = eski["irsaliye_satiri_id"]
        self.satirlar[idx] = veri
        self.satir_listesini_yenile()
        return True

    def satir_hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        """Hücre editöründen gelen değer; geçersizse ValueError (satır değişmez)."""
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        yeni = dict(s)
        if kolon == "miktar":
            miktar = decimal(metin or 0, "Miktar")
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            yeni["miktar"] = miktar
        elif kolon == "birim":
            birim = (metin or "").strip()
            if not birim:
                raise ValueError("Birim zorunludur.")
            if birim.casefold() == (s.get("birim") or "").casefold():
                return
            if s.get("siparis_satiri_id"):
                raise ValueError("Siparişten aktarılan satırın birimi değiştirilemez.")
            yeni["birim"] = birim
            fiyat = self._cari_fiyati(s.get("urun_kodu") or "", birim)
            if fiyat is not None:
                yeni["birim_fiyat"] = fiyat
        elif kolon == "fiyat":
            yeni["birim_fiyat"] = decimal(metin or 0, "Birim fiyat", Decimal("0"))
        elif kolon == "iskonto":
            iskonto = decimal((metin or "0").replace("%", ""), "İskonto", Decimal("0"))
            if iskonto > 100:
                raise ValueError("İskonto %100'den büyük olamaz.")
            yeni["iskonto_orani"] = iskonto
        elif kolon == "kdv":
            yeni["kdv_orani"] = decimal((metin or "0").replace("%", ""), "KDV", Decimal("0"))
        elif kolon == "lot":
            yeni["lot_no"] = metin
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
            if k not in ("irsaliye_satiri_id", "siparis_satiri_id", "siparis_id", "siparis_no",
                         "siparis_miktar", "onceki_sevk", "faturalanan_miktar")
        }
        kopya["siparis_satiri_id"] = None
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
            ("Fiyat Listesinden Seç…", lambda: self.fiyat_secimi_ac(idx=idx)),
            ("Satırı Çoğalt", self.satir_cogalt),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_kaldir),
        ]
        if 0 <= idx < len(self.satirlar) and not self.satirlar[idx].get("siparis_satiri_id"):
            ogeler.insert(1, ("Ürünü Değiştir…", lambda: self._satir_ici_giris.urun_degistir_baslat(idx)))
        return ogeler

    def fiyat_secimi_ac(self, _event=None, idx: int | None = None):
        from app import PriceSelectionDialog

        if idx is None:
            idx = self._secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)):
            messagebox.showinfo("Fiyat", "Önce ürün satırı seçin.", parent=self)
            return "break"
        kod = self.satirlar[idx].get("urun_kodu") or ""

        def _secildi(fiyat):
            self.satir_hucre_uygula(idx, "fiyat", _sayi(fiyat.tutar))

        dialog = PriceSelectionDialog(self, kod, on_select=_secildi, fiyat_turu="satis")
        self.wait_window(dialog)
        return "break"

    # ---------------------------------------------------------------- satırlar
    def satir_temizle(self):
        """Açık hücre / giriş editörlerini kapatır (satırlar korunur)."""
        self._hucre.kapat()
        self._satir_ici_giris.kapat()
        try:
            self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        except tk.TclError:
            pass

    def satir_listesini_yenile(self):
        self.satir_tablosu.delete(*self.satir_tablosu.get_children())
        for index, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            fiyat = decimal(veri.get("birim_fiyat") or 0, "Birim fiyat")
            iskonto = decimal(veri.get("iskonto_orani") or 0, "İskonto")
            kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
            net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100))
            toplam = net * (Decimal(1) + kdv / Decimal(100))
            fatura = decimal(veri.get("faturalanan_miktar") or 0, "Faturalanan")
            self.satir_tablosu.insert(
                "", "end", iid=str(index), tags=("cift" if index % 2 else "tek",),
                values=(
                    index + 1, veri.get("urun_kodu", ""), veri.get("urun_adi", ""), _sayi(miktar),
                    veri.get("birim") or "Adet", _para(fiyat), f"{_sayi(iskonto)}%", f"{_sayi(kdv)}%",
                    _para(toplam), veri.get("siparis_no") or "", _sayi(fatura), _sayi(miktar - fatura),
                    veri.get("lot_no") or "", veri.get("aciklama") or "",
                ),
            )
        self._satir_ici_giris.tabloya_ekle()
        self._siparis_var.set(
            ", ".join(dict.fromkeys(s.get("siparis_no") for s in self.satirlar if s.get("siparis_no")))
        )
        self.toplam_guncelle()

    def toplam_guncelle(self):
        ara = kdv_toplam = Decimal("0")
        for veri in self.satirlar:
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            fiyat = decimal(veri.get("birim_fiyat") or 0, "Birim fiyat")
            iskonto = decimal(veri.get("iskonto_orani") or 0, "İskonto")
            kdv = decimal(veri.get("kdv_orani") or 0, "KDV")
            net = miktar * fiyat * (Decimal(1) - iskonto / Decimal(100))
            ara += net
            kdv_toplam += net * kdv / Decimal(100)
        self.toplam.configure(
            text=(
                f"Kalem: {len(self.satirlar)}   |   Toplam Miktar: {toplam_miktar_ozeti(self.satirlar)}   |   "
                f"Ara: {_para(ara)}   KDV: {_para(kdv_toplam)}   Genel: {_para(ara + kdv_toplam)}"
            )
        )

    def satir_duzenle(self):
        if not self._duzenlenebilir():
            return
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Düzenlenecek satırı seçin.", parent=self)
            return
        self._hucre.ilk_alana(idx)

    def satir_kaldir(self):
        if not self._duzenlenebilir():
            return
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Silinecek satırı seçin.", parent=self)
            return
        veri = self.satirlar[idx]
        ek = ""
        if veri.get("siparis_satiri_id"):
            ek = f"\n\nSatır {veri.get('siparis_no') or 'sipariş'} siparişine bağlı; kayıttan sonra miktar siparişte yeniden sevk bekler."
        if messagebox.askyesno("Satırı sil", f"«{veri.get('urun_adi')}» satırı silinsin mi?{ek}", parent=self):
            self.satirlar.pop(idx)
            self.satir_temizle()
            self.satir_listesini_yenile()

    # ----------------------------------------------------- siparişten aktarım
    def siparisten_aktar(self):
        if not self._duzenlenebilir():
            return
        if self.cari is None:
            messagebox.showwarning("Siparişten Aktar", "Önce müşteri seçin (F10).", parent=self)
            return
        try:
            adaylar = SatisIrsaliyesiService.siparis_aktarim_adaylari(
                self.cari.id, irsaliye_id=getattr(self.irsaliye, "id", None)
            )
        except Exception as exc:
            messagebox.showerror("Siparişten Aktar", str(exc), parent=self)
            return
        if not adaylar:
            messagebox.showinfo(
                "Siparişten Aktar",
                f"{self.cari.unvan} için sevk bekleyen onaylı sipariş yok.\n"
                "(Taslak ve iptal edilmiş siparişler listelenmez.)",
                parent=self,
            )
            return
        secilen = SiparisAktarimDialog.sec(self, adaylar)
        if not secilen:
            return
        from database.kalan_belge_service import secimden_irsaliye_satirlari, siparis_irsaliye_secim_satirlari
        from database.satis_siparisi_service import SatisSiparisiService
        from kismi_belge_secim_ui import kismi_secim_yap

        db_satirlari = list(getattr(self.irsaliye, "satirlar", None) or [])
        secim_satirlari: list[dict[str, Any]] = []
        siparis_bilgi: dict[int, tuple[int, str]] = {}
        for siparis_id in secilen:
            siparis = SatisSiparisiService.getir(siparis_id)
            if siparis is None:
                continue
            for s in siparis_irsaliye_secim_satirlari(
                siparis, form_satirlar=self.satirlar, bu_irsaliye_db_satirlar=db_satirlari
            ):
                s["aciklama"] = f"{siparis.siparis_no}" + (f" · {s['aciklama']}" if s.get("aciklama") else "")
                siparis_bilgi[int(s["siparis_satiri_id"])] = (int(siparis.id), siparis.siparis_no)
                secim_satirlari.append(s)
        secim = kismi_secim_yap(
            self,
            secim_satirlari,
            baslik="Siparişten Aktar — sevk miktarları",
            aciklama=(
                "Satır bazında bu irsaliyeye alınacak miktarı girin (en fazla kalan sevk miktarı). "
                "0 = satırı alma. Kalan miktar siparişte sevk bekler; aktarım kaydedilene kadar sevk sayılmaz."
            ),
            onceki_baslik="Sevk edilen",
            kalan_baslik="Kalan sevk",
            bu_belge_baslik="Bu irsaliye",
            siparis_baslik="Sipariş miktarı",
        )
        if not secim:
            return
        try:
            yeni_satirlar = secimden_irsaliye_satirlari(secim)
        except ValueError as hata:
            messagebox.showerror("Siparişten Aktar", str(hata), parent=self)
            return
        for yeni in yeni_satirlar:
            ssid = int(yeni["siparis_satiri_id"])
            sid, sno = siparis_bilgi.get(ssid, (None, ""))
            yeni["siparis_id"], yeni["siparis_no"] = sid, sno
            yeni["aciklama"] = ""
            mevcut = next((s for s in self.satirlar if s.get("siparis_satiri_id") and int(s["siparis_satiri_id"]) == ssid), None)
            if mevcut is not None:
                mevcut["miktar"] = decimal(mevcut.get("miktar") or 0, "Miktar") + decimal(yeni["miktar"], "Miktar")
            else:
                self.satirlar.append(yeni)
        self.satir_listesini_yenile()

    # --------------------------------------------------------------- kayıt
    def _veri_topla(self) -> tuple[dict, list]:
        tarih = _tarih_coz(self.girdiler["irsaliye_tarihi"].get(), "İrsaliye tarihi")
        if tarih > date.today():
            raise ValueError("İrsaliye tarihi gelecek bir tarih olamaz.")
        if self.cari is None:
            raise ValueError("Müşteri seçin (F10 veya «Müşteri Ara»).")
        if not (self.depo.get() or "").strip():
            raise ValueError("Depo seçin.")
        if not self._hucre.bekleyeni_uygula():
            raise ValueError("Düzenlenen hücredeki değer geçersiz; düzeltin veya Esc ile vazgeçin.")
        self._satir_ici_giris.bekleyeni_uygula()
        if not self.satirlar:
            raise ValueError("En az bir ürün satırı ekleyin.")
        planlanan = _tarih_coz(self.girdiler["planlanan_teslim"].get(), "Planlanan teslim tarihi", zorunlu=False)

        def g(alan):
            return self.girdiler[alan].get().strip()

        siparis_idleri = sorted({int(s["siparis_id"]) for s in self.satirlar if s.get("siparis_id")})
        veriler = {
            "irsaliye_tarihi": tarih,
            "cari_id": int(self.cari.id),
            "siparis_id": siparis_idleri[0] if siparis_idleri else getattr(self.irsaliye, "siparis_id", None),
            "aciklama": g("aciklama"),
            "ayrintili_notlar": self.musteri_notu.get("1.0", "end").strip(),
            "musteri_notu": self.musteri_notu.get("1.0", "end").strip(),
            "sevk_notu": self.sevk_notu.get("1.0", "end").strip(),
            "ic_not": self.ic_not.get("1.0", "end").strip(),
            "depo": self.depo.get().strip() or "ANA DEPO",
            "is_priced": bool(self._is_priced.get()),
            "planlanan_teslim": planlanan,
        }
        for alan in (
            "sevk_adresi", "sevk_il", "sevk_ilce", "teslim_kisi", "teslim_telefon", "sevkiyat_yontemi",
            "nakliyeci", "arac_plaka", "sofor_adi", "sofor_telefon", "takip_no",
        ):
            veriler[alan] = g(alan)
        if self.irsaliye is None:
            ozel = g("irsaliye_no")
            if ozel and ozel != YENI_NO_METNI:
                veriler["irsaliye_no"] = ozel
        satirlar = []
        for s in self.satirlar:
            satirlar.append(
                {
                    "irsaliye_satiri_id": s.get("irsaliye_satiri_id"),
                    "siparis_satiri_id": s.get("siparis_satiri_id"),
                    "urun_kodu": s.get("urun_kodu"),
                    "urun_adi": s.get("urun_adi"),
                    "aciklama": s.get("aciklama") or "",
                    "miktar": s.get("miktar"),
                    "birim": s.get("birim") or "Adet",
                    "birim_fiyat": s.get("birim_fiyat") or 0,
                    "iskonto_orani": s.get("iskonto_orani") or 0,
                    "kdv_orani": s.get("kdv_orani") if s.get("kdv_orani") not in (None, "") else 20,
                    "lot_no": s.get("lot_no") or "",
                    "siparis_miktar": s.get("siparis_miktar"),
                    "onceki_sevk": s.get("onceki_sevk"),
                }
            )
        return veriler, satirlar

    def kaydet(self, sessiz: bool = False) -> bool:
        if self._kaydediliyor:
            return False
        if not self._duzenlenebilir():
            messagebox.showinfo("Kaydet", "Bu irsaliye bu durumda değiştirilemez.", parent=self)
            return False
        try:
            veriler, satirlar = self._veri_topla()
        except ValueError as hata:
            messagebox.showwarning("Eksik / hatalı bilgi", str(hata), parent=self)
            return False
        self._kaydediliyor = True
        self.btn["kaydet"].configure(state="disabled")
        try:
            kayit = SatisIrsaliyesiService.kaydet(veriler, satirlar, getattr(self.irsaliye, "id", None))
        except ValueError as hata:
            messagebox.showerror("İrsaliye kaydedilemedi", str(hata), parent=self)
            return False
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("İrsaliye kaydedilemedi", f"Beklenmeyen hata; kayıt yapılmadı.\n{hata}", parent=self)
            return False
        finally:
            self._kaydediliyor = False
            try:
                self.btn["kaydet"].configure(state="normal")
            except tk.TclError:
                pass
        self.result = True
        self._kayit_yukle(kayit)
        if not sessiz:
            messagebox.showinfo(
                "Kaydedildi",
                f"{kayit.irsaliye_no} kaydedildi (TASLAK — stok çıkışı yok).\n"
                "Stoktan düşmek için «Sevk Et (Onayla)» kullanın.",
                parent=self,
            )
        return True

    def _kayit_yukle(self, ir):
        """Kayıtlı irsaliyeyi forma yükler; satır kimlikleri korunur."""
        self.irsaliye = ir
        self._durum_var.set(ir.durum or "TASLAK")
        self._kilitsiz_ac()
        no = self.girdiler["irsaliye_no"]
        no.delete(0, "end")
        no.insert(0, ir.irsaliye_no or "")
        self.girdiler["irsaliye_tarihi"].delete(0, "end")
        self.girdiler["irsaliye_tarihi"].insert(0, _tarih(ir.irsaliye_tarihi))
        if getattr(ir, "depo", None):
            if ir.depo not in self.depolar:
                self.depolar.append(ir.depo)
                self.depo.configure(values=self.depolar)
            self.depo.set(ir.depo)
        self._is_priced.set(bool(getattr(ir, "is_priced", True)))
        if ir.cari is not None:
            self.cari = None
            self._musteri_ata(ir.cari, sessiz=True)
        for alan in (
            "sevk_adresi", "sevk_il", "sevk_ilce", "teslim_kisi", "teslim_telefon", "sevkiyat_yontemi",
            "nakliyeci", "arac_plaka", "sofor_adi", "sofor_telefon", "takip_no", "aciklama",
        ):
            w = self.girdiler[alan]
            w.delete(0, "end")
            w.insert(0, getattr(ir, alan, None) or "")
        self.girdiler["planlanan_teslim"].delete(0, "end")
        self.girdiler["planlanan_teslim"].insert(0, _tarih(getattr(ir, "planlanan_teslim", None)))
        for t, deger in (
            (self.musteri_notu, getattr(ir, "musteri_notu", None) or ir.ayrintili_notlar or ""),
            (self.sevk_notu, getattr(ir, "sevk_notu", None) or ""),
            (self.ic_not, getattr(ir, "ic_not", None) or ""),
        ):
            t.delete("1.0", "end")
            t.insert("1.0", deger)
        siparis_nolari = self._siparis_nolari([s.siparis_satiri_id for s in ir.satirlar if s.siparis_satiri_id])
        self.satirlar = []
        for satir in ir.satirlar:
            sid, sno = siparis_nolari.get(int(satir.siparis_satiri_id), (None, "")) if satir.siparis_satiri_id else (None, "")
            self.satirlar.append(
                {
                    "irsaliye_satiri_id": satir.id,
                    "siparis_satiri_id": satir.siparis_satiri_id,
                    "siparis_id": sid,
                    "siparis_no": sno,
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "aciklama": satir.aciklama or "",
                    "miktar": satir.miktar,
                    "birim": satir.birim,
                    "birim_fiyat": satir.birim_fiyat,
                    "iskonto_orani": satir.iskonto_orani,
                    "kdv_orani": satir.kdv_orani,
                    "faturalanan_miktar": satir.faturalanan_miktar,
                    "siparis_miktar": getattr(satir, "siparis_miktar", None),
                    "onceki_sevk": getattr(satir, "onceki_sevk", None),
                    "lot_no": getattr(satir, "lot_no", None) or "",
                }
            )
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()

    def _kilitsiz_ac(self):
        """Yükleme öncesi alanları yazılabilir yap (kilit en sonda yeniden uygulanır)."""
        for alan, w in self.girdiler.items():
            if alan != "bakiye":
                w.configure(state="normal")
        for t in (self.musteri_notu, self.sevk_notu, self.ic_not):
            t.configure(state="normal")

    @staticmethod
    def _siparis_nolari(siparis_satiri_idleri) -> dict[int, tuple[int, str]]:
        if not siparis_satiri_idleri:
            return {}
        from sqlalchemy import select

        from database.database import get_session
        from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri

        with get_session() as session:
            satirlar = session.execute(
                select(SatisSiparisiSatiri.id, SatisSiparisi.id, SatisSiparisi.siparis_no)
                .join(SatisSiparisi, SatisSiparisiSatiri.siparis_id == SatisSiparisi.id)
                .where(SatisSiparisiSatiri.id.in_([int(i) for i in siparis_satiri_idleri]))
            ).all()
        return {int(ssid): (int(sid), sno or "") for ssid, sid, sno in satirlar}

    def yeni_belge(self):
        if not self._kaydetmeyi_sor("Yeni irsaliyeye geçmeden"):
            return
        self.irsaliye = None
        self.cari = None
        self.musteri_map = {}
        self._musteri_var.set("")
        self._durum_var.set("TASLAK")
        self._is_priced.set(True)
        self._kilitsiz_ac()
        for alan, w in self.girdiler.items():
            if alan == "bakiye":
                continue
            w.delete(0, "end")
        self.girdiler["irsaliye_no"].insert(0, YENI_NO_METNI)
        self.girdiler["irsaliye_tarihi"].insert(0, date.today().strftime("%d.%m.%Y"))
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")
        for t in (self.musteri_notu, self.sevk_notu, self.ic_not):
            t.delete("1.0", "end")
        self.bakiye_guncelle()
        self.satirlar = []
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()

    # ---------------------------------------------------------- belge işlemleri
    def _kayitli_ve_guncel(self, islem: str) -> bool:
        """İşlem öncesi: yeni/değişmiş belge kaydedilir; kaydedilemezse işlem yapılmaz."""
        if self.irsaliye is not None and not self.degisiklik_var():
            return True
        mesaj = (
            "İrsaliye henüz kaydedilmedi."
            if self.irsaliye is None
            else "İrsaliyede kaydedilmemiş değişiklikler var."
        )
        if not messagebox.askyesno(islem, f"{mesaj}\n«{islem}» için önce kaydedilmesi gerekir. Kaydedilsin mi?", parent=self):
            return False
        return self.kaydet(sessiz=True)

    def _yenile(self):
        if self.irsaliye is not None:
            guncel = SatisIrsaliyesiService.getir(self.irsaliye.id)
            if guncel is not None:
                self._kayit_yukle(guncel)

    def hazirla(self):
        if not self._kayitli_ve_guncel("Sevkiyata Hazırla"):
            return
        try:
            SatisIrsaliyesiService.hazirla(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Hazırlık", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def sevk_et(self):
        if not self._kayitli_ve_guncel("Sevk Et"):
            return
        if not messagebox.askyesno(
            "Sevk Et (Onayla)",
            f"{self.irsaliye.irsaliye_no} için {self.depo.get()} deposundan stok çıkışı yapılacak "
            f"({toplam_miktar_ozeti(self.satirlar)}).\nSevk sonrası satırlar kilitlenir. Devam edilsin mi?",
            parent=self,
        ):
            return
        try:
            SatisIrsaliyesiService.sevk_et(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Sevk yapılamadı", str(hata), parent=self)
            return
        self.result = True
        self._yenile()
        messagebox.showinfo("Sevk", "İrsaliye sevk edildi; stok çıkışı kaydedildi.", parent=self)

    def sevk_geri_al(self):
        if self.irsaliye is None:
            return
        if not messagebox.askyesno(
            "Sevki Geri Al",
            f"{self.irsaliye.irsaliye_no} stok çıkışı geri alınacak ve belge TASLAK'a dönecek. Devam edilsin mi?",
            parent=self,
        ):
            return
        try:
            SatisIrsaliyesiService.sevk_geri_al(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Sevk geri alınamadı", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def teslim_et(self):
        if self.irsaliye is None:
            return
        try:
            SatisIrsaliyesiService.teslim_et(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Teslim", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def fatura_olustur(self):
        if not self._kayitli_ve_guncel("Faturaya Aktar"):
            return
        irsaliye = SatisIrsaliyesiService.getir(self.irsaliye.id)
        if irsaliye is None or (irsaliye.durum or "") == "İPTAL":
            messagebox.showwarning("Fatura", "İptal edilmiş irsaliye faturaya aktarılamaz.", parent=self)
            return
        from database.kalan_belge_service import irsaliye_secim_satirlari, secimden_fatura_satirlari
        from kismi_belge_secim_ui import kismi_secim_yap

        secim = kismi_secim_yap(
            self,
            irsaliye_secim_satirlari(irsaliye),
            baslik="Faturaya Aktar — irsaliye satırları",
            aciklama=(
                f"{irsaliye.irsaliye_no}: bu faturaya alınacak miktarı seçin. 0 = satırı alma. "
                "Faturalanan miktar tekrar faturalanamaz; kalan sonraki faturaya aktarılabilir."
            ),
            onceki_baslik="Faturalanan",
            kalan_baslik="Fatura kalanı",
            bu_belge_baslik="Bu fatura",
            siparis_baslik="İrsaliye miktarı",
        )
        if not secim:
            return
        try:
            satir_override = secimden_fatura_satirlari(secim, kaynak="irsaliye")
        except ValueError as hata:
            messagebox.showerror("Fatura", str(hata), parent=self)
            return
        try:
            from app import CariDialog, SatisFaturasiDialog
        except Exception as exc:
            messagebox.showerror("Fatura", f"Fatura ekranı açılamadı.\n{exc}", parent=self)
            return
        dialog = SatisFaturasiDialog(
            self, irsaliye=irsaliye, satir_override=satir_override, cari_ac=lambda c: CariDialog(self, c)
        )
        self.wait_window(dialog)
        self.result = True
        self._yenile()

    def bagli_faturalari_goster(self):
        if self.irsaliye is None:
            return
        faturalar = SatisIrsaliyesiService.bagli_faturalar(self.irsaliye.id)
        if not faturalar:
            messagebox.showinfo("Bağlı Faturalar", "Bu irsaliyeye bağlı (iptal edilmemiş) fatura yok.", parent=self)
            return
        BagliFaturaDialog(self, self.irsaliye.irsaliye_no, faturalar)

    def iptal_et(self):
        if self.irsaliye is None:
            return
        if not messagebox.askyesno(
            "İrsaliyeyi iptal et",
            f"{self.irsaliye.irsaliye_no} numaralı irsaliye iptal edilsin mi?\n"
            "Stok çıkışı yapıldıysa geri alınır; siparişteki sevk miktarı geri açılır.",
            parent=self,
        ):
            return
        sebep = simpledialog.askstring("İptal nedeni", "İptal nedenini yazın (zorunlu):", parent=self)
        if not (sebep or "").strip():
            messagebox.showwarning("İptal", "İptal nedeni girilmeden iptal yapılmaz.", parent=self)
            return
        try:
            SatisIrsaliyesiService.iptal_et(self.irsaliye.id, sebep=sebep.strip())
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def sil(self):
        if self.irsaliye is None:
            return
        no = self.irsaliye.irsaliye_no
        if not messagebox.askyesno(
            "İrsaliyeyi sil",
            f"{no} numaralı irsaliye kalıcı olarak silinsin mi?\n\n"
            "Stok çıkışı yapıldıysa geri alınır, siparişteki sevk miktarı geri açılır. "
            "Silinen belge «Silinen Kayıtlar» günlüğüne yazılır.",
            icon="warning",
            parent=self,
        ):
            return
        try:
            SatisIrsaliyesiService.sil(self.irsaliye.id)
        except ValueError as hata:
            messagebox.showerror("Silinemedi", str(hata), parent=self)
            return
        self.result = True
        messagebox.showinfo("Silindi", f"{no} numaralı irsaliye silindi.", parent=self)
        self._kayit_imzasi = None
        self.irsaliye = None
        self.satirlar = []
        self.destroy()

    # ------------------------------------------------------------- çıktılar
    def _cikti(self, islem: str):
        """Kayıtlı veriden çıktı; kaydedilmemiş değişiklik varsa önce kaydetme sorulur."""
        if not self._kayitli_ve_guncel("Çıktı"):
            return None
        from irsaliye_cikti_ui import cikti_al

        return cikti_al(self, self.irsaliye.id, islem, fiyatli=bool(self._fiyatli_cikti.get()))

    def onizleme(self):
        return self._cikti("onizleme")

    def yazdir(self):
        return self._cikti("yazdir")

    def pdf_kaydet(self):
        return self._cikti("pdf")

    def word_kaydet(self):
        return self._cikti("word")


class SiparisAktarimDialog(tk.Toplevel):
    """Müşterinin sevk bekleyen siparişlerinden seçim (çoklu)."""

    def __init__(self, parent, adaylar: list[dict[str, Any]]):
        super().__init__(parent)
        self.result: list[int] | None = None
        self.title("Siparişten Aktar — bekleyen siparişler")
        self.configure(bg=BEYAZ)
        self.geometry("980x420")
        self.minsize(640, 300)
        self.transient(parent)
        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=980, yukseklik=420)
        except Exception:
            pass
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(
            ust, text="Sevk bekleyen siparişler — birden fazla seçebilirsiniz (Ctrl/Shift)",
            bg=LACIVERT, fg=BEYAZ, font=font(11, "bold", self), padx=12, pady=8,
        ).pack(anchor="w")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        alan = tk.Frame(self, bg=BEYAZ)
        alan.pack(fill="both", expand=True, padx=10, pady=8)
        kolonlar = ("no", "tarih", "termin", "urunler", "siparis", "kalan", "durum")
        self.tablo = ttk.Treeview(alan, columns=kolonlar, show="headings", selectmode="extended")
        treeview_stil(self.tablo)
        for col, baslik, gen, anc in (
            ("no", "Sipariş No", 120, "w"), ("tarih", "Tarih", 90, "w"), ("termin", "Termin", 90, "w"),
            ("urunler", "Ürünler (kalanı olan)", 330, "w"), ("siparis", "Sipariş Miktarı", 110, "e"),
            ("kalan", "Kalan Sevk", 100, "e"), ("durum", "Durum", 110, "w"),
        ):
            self.tablo.heading(col, text=baslik)
            self.tablo.column(col, width=gen, anchor=anc, stretch=(col == "urunler"))
        dikey = ttk.Scrollbar(alan, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        for i, a in enumerate(adaylar):
            self.tablo.insert(
                "", "end", iid=str(a["siparis_id"]), tags=("cift" if i % 2 else "tek",),
                values=(
                    a["siparis_no"], _tarih(a["siparis_tarihi"]), _tarih(a.get("termin_tarihi")), a["urunler"],
                    _sayi(a["siparis_miktar"]), _sayi(a["kalan_miktar"]), a["durum"],
                ),
            )
        if adaylar:
            self.tablo.selection_set(str(adaylar[0]["siparis_id"]))
        self.tablo.bind("<Double-1>", lambda _e: self._tamam())
        alt = tk.Frame(self, bg=BEYAZ)
        alt.pack(fill="x", padx=10, pady=(0, 10))
        tk_buton(alt, "Seçilenleri Aktar", self._tamam, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._tamam())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.tablo.focus_set()

    def _tamam(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Sipariş", "En az bir sipariş seçin.", parent=self)
            return
        self.result = [int(i) for i in secim]
        self.destroy()

    @classmethod
    def sec(cls, parent, adaylar) -> list[int] | None:
        dlg = cls(parent, adaylar)
        parent.wait_window(dlg)
        return dlg.result


class BagliFaturaDialog(tk.Toplevel):
    """İrsaliyeye bağlı satış faturaları; çift tık ile fatura açılır."""

    def __init__(self, parent, irsaliye_no: str, faturalar: list[dict[str, Any]]):
        super().__init__(parent)
        self.title(f"{irsaliye_no} — bağlı faturalar")
        self.configure(bg=BEYAZ)
        self.geometry("620x280")
        self.transient(parent)
        tk.Label(
            self, text=f"{irsaliye_no} irsaliyesine bağlı faturalar", bg=LACIVERT, fg=BEYAZ,
            font=font(11, "bold", self), padx=12, pady=8, anchor="w",
        ).pack(fill="x")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        kolonlar = ("no", "tarih", "durum", "miktar")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=6, selectmode="browse")
        treeview_stil(self.tablo)
        for col, baslik, gen in (
            ("no", "Fatura No", 160), ("tarih", "Tarih", 100), ("durum", "Durum", 160), ("miktar", "Faturalanan Miktar", 150),
        ):
            self.tablo.heading(col, text=baslik)
            self.tablo.column(col, width=gen)
        for f in faturalar:
            durum = f["durum"] or ""
            if f.get("onaylandi"):
                durum = f"{durum} (onaylı)"
            self.tablo.insert(
                "", "end", iid=str(f["fatura_id"]),
                values=(f["fatura_no"], _tarih(f["fatura_tarihi"]), durum, _sayi(f["miktar"])),
            )
        self.tablo.pack(fill="both", expand=True, padx=10, pady=8)
        self.tablo.bind("<Double-1>", lambda _e: self._ac())
        alt = tk.Frame(self, bg=BEYAZ)
        alt.pack(fill="x", padx=10, pady=(0, 10))
        tk_buton(alt, "Faturayı Aç", self._ac, rol="kaydet").pack(side="right")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right", padx=6)
        self.grab_set()

    def _ac(self):
        secim = self.tablo.selection()
        if not secim:
            return
        from database.satis_faturasi_service import SatisFaturasiService

        fatura = SatisFaturasiService.getir(int(secim[0]))
        if fatura is None:
            messagebox.showerror("Fatura", "Fatura bulunamadı.", parent=self)
            return
        from app import CariDialog, SatisFaturasiDialog

        dialog = SatisFaturasiDialog(self, fatura=fatura, cari_ac=lambda c: CariDialog(self, c))
        self.wait_window(dialog)
