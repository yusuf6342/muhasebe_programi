"""Stok kartı diyalogları (Pazartesi stok modülünün geri kurulumu)."""
from __future__ import annotations

import json
import os
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.satis_siparisi_service import decimal
from database.stok_service import (
    CIKIS_HAREKETLERI,
    ESKI_FIYAT_ESLEME,
    GIRIS_HAREKETLERI,
    KART_TURLERI,
    SATIS_FIYAT_ADLARI,
    STOK_FIYAT_ADLARI,
    StokService,
    fabrika_fiyati_hesapla,
)
from database.models.stok import KDV_ORANLARI, VARSAYILAN_KDV_ORANI
from database.session_manager import oturum

import stok_kart_tema as sktema
from stok_kart_tema import (
    ACIK_BG,
    BEYAZ,
    LACIVERT,
    baslik_seridi,
    form_etiket,
    ozet_karti,
    stil_uygula as stok_stil_uygula,
    tk_buton as stok_tk_buton,
)

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top", "Küçük Torba")

_ALIS_ETIKET_FG = "#C62828"
_SATIS_ETIKET_FG = "#2E7D32"
_HAREKET_GIRIS_FG = "#B71C1C"
_HAREKET_CIKIS_FG = "#1B5E20"
_HAREKET_NOTR_FG = "#627D98"


def _birim_adi(kayit) -> str:
    if isinstance(kayit, dict):
        return (kayit.get("birim_adi") or kayit.get("birim") or "").strip()
    if kayit:
        return (kayit[0] or "").strip()
    return ""


def hareket_yon_tag(hareket_turu: str) -> str:
    """Hareket türüne göre Treeview etiket: giris / cikis / notr."""
    tur = hareket_turu or ""
    if tur in GIRIS_HAREKETLERI:
        return "giris"
    if tur in CIKIS_HAREKETLERI:
        return "cikis"
    return "notr"


def _birim_carpan(kayit) -> str:
    if isinstance(kayit, dict):
        return str(kayit.get("carpan") or "1")
    if kayit and len(kayit) > 1:
        return str(kayit[1])
    return "1"


def para_goster(tutar):
    if tutar is None:
        return ""
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def miktar_goster_tr(miktar, bos_sifir=False):
    """Türkçe ondalık miktar; bos_sifir=True ise 0 boş string döner."""
    if miktar is None:
        return ""
    try:
        d = Decimal(str(miktar))
    except Exception:
        return str(miktar)
    if bos_sifir and d == 0:
        return ""
    s = f"{d:,.4f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


def _hareket_kolon_ayar_yolu() -> Path:
    firma = (getattr(oturum, "firma_kodu", None) or "genel").strip() or "genel"
    kullanici = (
        getattr(oturum, "kullanici_adi", None)
        or getattr(oturum, "username", None)
        or getattr(oturum, "user_id", None)
        or "kullanici"
    )
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{firma}_{kullanici}")
    d = Path.home() / ".cin_muhasebe"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"stok_hareket_kolonlar_{safe}.json"


_HAREKET_KOLON_VARSAYILAN = {
    "tarih_saat": {"baslik": "Tarih - Saat", "genislik": 130, "gorunur": True},
    "belge_turu": {"baslik": "Belge Türü", "genislik": 110, "gorunur": True},
    "belge_no": {"baslik": "Belge No", "genislik": 110, "gorunur": True},
    "cari": {"baslik": "Cari Kart", "genislik": 150, "gorunur": True},
    "depo": {"baslik": "Depo", "genislik": 90, "gorunur": True},
    "birim": {"baslik": "Birim", "genislik": 60, "gorunur": True},
    "giris": {"baslik": "Giriş Miktarı", "genislik": 95, "gorunur": True},
    "net_giris_fiyat": {"baslik": "Net Giriş Birim Fiyatı", "genislik": 130, "gorunur": True},
    "cikis": {"baslik": "Çıkış Miktarı", "genislik": 95, "gorunur": True},
    "net_cikis_fiyat": {"baslik": "Net Çıkış Birim Fiyatı", "genislik": 130, "gorunur": True},
    "kalan": {"baslik": "Kalan Miktar", "genislik": 95, "gorunur": True},
    "fifo": {"baslik": "FIFO Kalan Değeri", "genislik": 120, "gorunur": True},
    "aciklama": {"baslik": "Açıklama", "genislik": 160, "gorunur": True},
}

_HAREKET_SAYISAL_KOLONLAR = {
    "giris",
    "net_giris_fiyat",
    "cikis",
    "net_cikis_fiyat",
    "kalan",
    "fifo",
}


def _net_fiyat_goster(deger, *, fiyat_yok: bool = False) -> str:
    """Net birim fiyat gösterimi: kaynak yoksa boş/'Fiyat yok'; gerçek 0 → 0,00."""
    if deger is None:
        return "Fiyat yok" if fiyat_yok else ""
    return para_goster(deger)


def hareket_kolon_ayarlari_yukle() -> dict:
    varsayilan = {k: dict(v) for k, v in _HAREKET_KOLON_VARSAYILAN.items()}
    yol = _hareket_kolon_ayar_yolu()
    if not yol.exists():
        return varsayilan
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return varsayilan
    for anahtar, varsay in varsayilan.items():
        gelen = kayit.get(anahtar) or {}
        try:
            genislik = int(gelen.get("genislik", varsay["genislik"]))
        except (TypeError, ValueError):
            genislik = varsay["genislik"]
        varsay["genislik"] = max(40, min(genislik, 600))
        if "gorunur" in gelen:
            varsay["gorunur"] = bool(gelen["gorunur"])
    # Kalan gizliyse FIFO da gizlensin (anlam kaybı)
    if not varsayilan["kalan"]["gorunur"]:
        varsayilan["fifo"]["gorunur"] = False
    return varsayilan


def hareket_kolon_ayarlari_kaydet(ayarlar: dict) -> None:
    temiz = {}
    for anahtar in _HAREKET_KOLON_VARSAYILAN:
        cfg = ayarlar.get(anahtar) or {}
        temiz[anahtar] = {
            "genislik": int(cfg.get("genislik", _HAREKET_KOLON_VARSAYILAN[anahtar]["genislik"])),
            "gorunur": bool(cfg.get("gorunur", True)),
        }
    if not temiz.get("kalan", {}).get("gorunur", True):
        temiz.setdefault("fifo", {})["gorunur"] = False
    _hareket_kolon_ayar_yolu().write_text(
        json.dumps(temiz, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
    """Barkod Birim Dönüştürücü: zincir çevirim + birim bazlı manuel/otomatik fiyatlar."""

    def __init__(
        self,
        parent,
        ana_birim="Adet",
        birimler=None,
        ana_fiyatlar=None,
        *,
        stok_id=None,
        on_saved=None,
    ):
        super().__init__(parent)
        self.result = None
        self.stok_id = int(stok_id) if stok_id else None
        self.on_saved = on_saved
        self._kayit_devam = False
        self._f1_kilit = False
        self._kapatiliyor = False
        self._hata_widgetleri: list = []
        self.ana_birim = (ana_birim or "Adet").strip() or "Adet"
        self.ana_fiyatlar = {
            (k or "").strip().upper(): v for k, v in (ana_fiyatlar or {}).items() if str(v).strip() != ""
        }
        self.title("Barkod Birim Dönüştürücü")
        self.geometry("980x680")
        self.minsize(900, 560)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._kapat_istegi)
        try:
            self.configure(bg=ACIK_BG)
            stok_stil_uygula(root=self)
        except Exception:
            pass

        # Sabit alt işlem çubuğu — önce pack edilir; kaydırma/ölçeklemede kaybolmaz
        self._alt_cubuk = tk.Frame(
            self,
            bg=BEYAZ,
            highlightthickness=1,
            highlightbackground=sktema.CIZGI,
        )
        self._alt_cubuk.pack(side="bottom", fill="x")
        alt_ic = tk.Frame(self._alt_cubuk, bg=BEYAZ)
        alt_ic.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt_ic, text="Pasife Al / Sil", command=self.sil).pack(side="left")
        tk.Label(
            alt_ic,
            text="F1: Kaydet  ·  Esc: Vazgeç",
            bg=BEYAZ,
            fg="#627D98",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=16)
        self.btn_vazgec = stok_tk_buton(alt_ic, "Vazgeç", self._kapat_istegi, rol="ikincil")
        self.btn_vazgec.configure(padx=18, pady=10)
        self.btn_vazgec.pack(side="right", padx=(6, 0))
        self.btn_kaydet_kapat = stok_tk_buton(
            alt_ic, "Kaydet ve Kapat", self._kaydet_ve_kapat, rol="vurgu"
        )
        self.btn_kaydet_kapat.configure(padx=18, pady=10)
        self.btn_kaydet_kapat.pack(side="right", padx=(6, 0))
        self.btn_kaydet = stok_tk_buton(
            alt_ic, "Kaydet (F1)", self._kaydet_acik_kal, rol="kaydet"
        )
        self.btn_kaydet.configure(padx=18, pady=10)
        self.btn_kaydet.pack(side="right", padx=(6, 0))

        # İçerik alanı (alt çubuğun üstünde genişler)
        self._icerik = tk.Frame(self, bg=ACIK_BG)
        self._icerik.pack(side="top", fill="both", expand=True)

        ust = ttk.Frame(self._icerik, padding=10)
        ust.pack(fill="x")
        ttk.Label(
            ust,
            text=(
                f"Temel birim: {self.ana_birim}. Tüm stok hareketleri temel birimde saklanır. "
                "Her birime bağımsız Alış + Satış 1–10 fiyatı girilebilir (Manuel) veya katsayıdan hesaplanır (Otomatik)."
            ),
            wraplength=920,
        ).pack(anchor="w")

        varsayilan = ttk.LabelFrame(self._icerik, text="Varsayılan birimler", padding=8)
        varsayilan.pack(fill="x", padx=12, pady=(0, 6))
        self.v_goruntu = ttk.Combobox(varsayilan, width=16, state="readonly")
        self.v_alis = ttk.Combobox(varsayilan, width=16, state="readonly")
        self.v_satis = ttk.Combobox(varsayilan, width=16, state="readonly")
        ttk.Label(varsayilan, text="Görüntüleme").grid(row=0, column=0, sticky="w", padx=4)
        self.v_goruntu.grid(row=0, column=1, padx=4)
        ttk.Label(varsayilan, text="Alış").grid(row=0, column=2, sticky="w", padx=4)
        self.v_alis.grid(row=0, column=3, padx=4)
        ttk.Label(varsayilan, text="Satış").grid(row=0, column=4, sticky="w", padx=4)
        self.v_satis.grid(row=0, column=5, padx=4)

        birim_secenekleri = list(
            dict.fromkeys(
                [
                    *BIRIM_SECENEKLERI,
                    "Küçük Torba",
                    self.ana_birim,
                    *StokService.secenekleri_listele("birim"),
                ]
            )
        )
        form = ttk.LabelFrame(self._icerik, text="Dönüşüm ekle", padding=8)
        form.pack(fill="x", padx=12, pady=4)
        ttk.Label(form, text="1").grid(row=0, column=0, padx=2)
        self.birim = ttk.Combobox(form, values=birim_secenekleri, width=14)
        self.birim.grid(row=0, column=1, padx=2)
        ttk.Label(form, text="=").grid(row=0, column=2, padx=2)
        self.carpan = ttk.Entry(form, width=10)
        self.carpan.grid(row=0, column=3, padx=2)
        self.hedef = ttk.Combobox(form, values=birim_secenekleri, width=14)
        self.hedef.set(self.ana_birim)
        self.hedef.grid(row=0, column=4, padx=2)
        ttk.Button(form, text="Dönüşüm Ekle", command=self.ekle).grid(row=0, column=5, padx=6)

        orta = ttk.Panedwindow(self._icerik, orient="horizontal")
        orta.pack(fill="both", expand=True, padx=12, pady=6)

        sol = ttk.Frame(orta)
        sag = ttk.Frame(orta)
        orta.add(sol, weight=3)
        orta.add(sag, weight=2)

        self.tablo = ttk.Treeview(
            sol,
            columns=("birim", "carpan", "hedef", "ana", "modu", "aktif"),
            show="headings",
            selectmode="browse",
            height=14,
        )
        for kolon, baslik, w in (
            ("birim", "Birim", 110),
            ("carpan", "Katsayı", 70),
            ("hedef", "Referans", 100),
            ("ana", f"= {self.ana_birim}", 100),
            ("modu", "Fiyat modu", 80),
            ("aktif", "Aktif", 50),
        ):
            self.tablo.heading(kolon, text=baslik)
            self.tablo.column(kolon, width=w)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(sol, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        self.tablo.bind("<<TreeviewSelect>>", self._satir_secildi)

        self._kayitlar: dict[str, dict] = {}  # iid -> dict

        fiyat_cer = ttk.LabelFrame(sag, text="Seçili birim fiyatları", padding=8)
        fiyat_cer.pack(fill="both", expand=True)
        self._secili_lbl = ttk.Label(fiyat_cer, text="Bir satır seçin", font=("Segoe UI", 10, "bold"))
        self._secili_lbl.pack(anchor="w", pady=(0, 6))

        self.fiyat_modu = ttk.Combobox(
            fiyat_cer, values=("Manuel", "Katsayıdan Otomatik"), state="readonly", width=22
        )
        self.fiyat_modu.set("Manuel")
        self.fiyat_modu.pack(anchor="w")
        self.fiyat_modu.bind("<<ComboboxSelected>>", lambda _e: self._fiyat_formundan_yaz())

        ttk.Label(fiyat_cer, text="Manuel Alış Fiyatı (TL)").pack(anchor="w", pady=(8, 0))
        self.alis_fiyat = ttk.Entry(fiyat_cer, width=18)
        self.alis_fiyat.pack(anchor="w")
        self.alis_fiyat.bind("<FocusOut>", lambda _e: self._fiyat_formundan_yaz())

        ttk.Label(fiyat_cer, text="Satış Fiyatı 1–10 (yatay kaydır)").pack(anchor="w", pady=(8, 0))
        sf_cer = ttk.Frame(fiyat_cer)
        sf_cer.pack(fill="both", expand=True)
        sf_canvas = tk.Canvas(sf_cer, height=160, highlightthickness=0)
        sf_scroll = ttk.Scrollbar(sf_cer, orient="horizontal", command=sf_canvas.xview)
        sf_ic = ttk.Frame(sf_canvas)
        sf_ic.bind("<Configure>", lambda _e: sf_canvas.configure(scrollregion=sf_canvas.bbox("all")))
        sf_canvas.create_window((0, 0), window=sf_ic, anchor="nw")
        sf_canvas.configure(xscrollcommand=sf_scroll.set)
        sf_canvas.pack(fill="both", expand=True)
        sf_scroll.pack(fill="x")
        self.satis_girisleri = {}
        for i, ad in enumerate(SATIS_FIYAT_ADLARI):
            col = ttk.Frame(sf_ic, padding=4)
            col.grid(row=0, column=i, sticky="n")
            ttk.Label(col, text=ad.replace("SATIŞ FİYATI ", "SF")).pack()
            e = ttk.Entry(col, width=10)
            e.pack()
            e.bind("<FocusOut>", lambda _ev: self._fiyat_formundan_yaz())
            self.satis_girisleri[ad] = e

        bayrak = ttk.Frame(fiyat_cer)
        bayrak.pack(fill="x", pady=6)
        self.var_alis_kul = tk.BooleanVar(value=True)
        self.var_satis_kul = tk.BooleanVar(value=True)
        self.var_v_gor = tk.BooleanVar(value=False)
        self.var_v_alis = tk.BooleanVar(value=False)
        self.var_v_satis = tk.BooleanVar(value=False)
        self.var_aktif = tk.BooleanVar(value=True)
        ttk.Checkbutton(bayrak, text="Alışta", variable=self.var_alis_kul, command=self._fiyat_formundan_yaz).pack(
            side="left"
        )
        ttk.Checkbutton(bayrak, text="Satışta", variable=self.var_satis_kul, command=self._fiyat_formundan_yaz).pack(
            side="left"
        )
        ttk.Checkbutton(bayrak, text="Aktif", variable=self.var_aktif, command=self._fiyat_formundan_yaz).pack(
            side="left"
        )
        ttk.Label(fiyat_cer, text="Birim barkodu").pack(anchor="w")
        self.birim_barkod = ttk.Entry(fiyat_cer, width=22)
        self.birim_barkod.pack(anchor="w")
        self.birim_barkod.bind("<FocusOut>", lambda _e: self._fiyat_formundan_yaz())
        self.formül_lbl = ttk.Label(fiyat_cer, text="", foreground="#627D98", wraplength=280)
        self.formül_lbl.pack(anchor="w", pady=4)

        # Test paneli
        test = ttk.LabelFrame(self._icerik, text="Dönüşüm önizleme / Test Et", padding=8)
        test.pack(fill="x", padx=12, pady=4)
        ttk.Label(test, text="Miktar").pack(side="left")
        self.test_miktar = ttk.Entry(test, width=10)
        self.test_miktar.insert(0, "1")
        self.test_miktar.pack(side="left", padx=4)
        self.test_kaynak = ttk.Combobox(test, width=14, state="readonly")
        self.test_kaynak.pack(side="left", padx=4)
        ttk.Label(test, text="→").pack(side="left")
        self.test_hedef = ttk.Combobox(test, width=14, state="readonly")
        self.test_hedef.pack(side="left", padx=4)
        ttk.Button(test, text="Test Et", command=self._test_et).pack(side="left", padx=8)
        self.test_sonuc = ttk.Label(test, text="")
        self.test_sonuc.pack(side="left", padx=8)

        # Yükle
        from database.stok_service import _birim_kayit_normalize

        for kayit in birimler or []:
            d = _birim_kayit_normalize(kayit, ana_birim=self.ana_birim)
            if not d["birim_adi"]:
                continue
            self._satir_ekle(d)

        self._ana_carpanlari_yenile()
        self._varsayilan_listeleri_yenile()
        # Kart varsayılanlarını işaretle
        for iid, d in self._kayitlar.items():
            if d.get("varsayilan_goruntuleme"):
                self.v_goruntu.set(d["birim_adi"])
            if d.get("varsayilan_alis"):
                self.v_alis.set(d["birim_adi"])
            if d.get("varsayilan_satis"):
                self.v_satis.set(d["birim_adi"])
        if not self.v_goruntu.get():
            self.v_goruntu.set(self.ana_birim)
        if not self.v_alis.get():
            self.v_alis.set(self.ana_birim)
        if not self.v_satis.get():
            self.v_satis.set(self.ana_birim)

        self._baslangic_ozet = self._durum_ozeti()
        self.bind("<Escape>", lambda _e: self._kapat_istegi())
        self.bind("<F1>", self._f1_kaydet)
        self.bind_all("<F1>", self._f1_kaydet)
        self._hata_stili_hazirla()

    def _satir_ekle(self, d: dict):
        iid = self.tablo.insert(
            "",
            "end",
            values=(
                d["birim_adi"],
                d.get("referans_carpan") or d.get("carpan") or "",
                d.get("referans_birim") or self.ana_birim,
                d.get("carpan") or "",
                "Otomatik" if str(d.get("fiyat_modu", "")).startswith("oto") else "Manuel",
                "Evet" if d.get("aktif", True) else "Hayır",
            ),
        )
        self._kayitlar[iid] = d

    def _donusumler(self):
        satirlar = []
        for item in self.tablo.get_children():
            degerler = self.tablo.item(item, "values")
            satirlar.append((degerler[0], degerler[1], degerler[2], item))
        return satirlar

    def _ana_carpan_haritasi(self):
        faktor = {self.ana_birim.casefold(): Decimal("1")}
        ad_esleme = {self.ana_birim.casefold(): self.ana_birim}
        donusumler = []
        for birim_adi, carpan, hedef, _item in self._donusumler():
            try:
                carpan_d = decimal(carpan, "Çarpan", Decimal("0.000001"))
            except ValueError:
                continue
            if carpan_d <= 0:
                continue
            donusumler.append((birim_adi.strip(), carpan_d, hedef.strip()))
            ad_esleme[birim_adi.strip().casefold()] = birim_adi.strip()
            ad_esleme[hedef.strip().casefold()] = hedef.strip()
        for _ in range(len(donusumler) + 4):
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
        return {ad_esleme.get(k, k): v for k, v in faktor.items()}

    def _ana_carpanlari_yenile(self):
        harita = self._ana_carpan_haritasi()
        for item in self.tablo.get_children():
            birim_adi, carpan, hedef, _eski_ana, modu, aktif = self.tablo.item(item, "values")
            ana = harita.get(birim_adi.strip())
            metin = f"{ana:f}".rstrip("0").rstrip(".") if ana is not None else ""
            self.tablo.item(item, values=(birim_adi, carpan, hedef, metin, modu, aktif))
            if item in self._kayitlar and ana is not None:
                self._kayitlar[item]["carpan"] = metin
                self._kayitlar[item]["referans_carpan"] = carpan
                self._kayitlar[item]["referans_birim"] = hedef
        self._varsayilan_listeleri_yenile()

    def _varsayilan_listeleri_yenile(self):
        adlar = [self.ana_birim]
        for item in self.tablo.get_children():
            ad = self.tablo.item(item, "values")[0]
            if ad and ad not in adlar:
                adlar.append(ad)
        for cb in (self.v_goruntu, self.v_alis, self.v_satis, self.test_kaynak, self.test_hedef):
            onceki = cb.get()
            cb.configure(values=adlar)
            if onceki in adlar:
                cb.set(onceki)
            elif not cb.get() and adlar:
                cb.set(adlar[0])
        if not self.test_hedef.get():
            self.test_hedef.set(self.ana_birim)

    def ekle(self):
        birim = self.birim.get().strip()
        carpan = self.carpan.get().strip()
        hedef = self.hedef.get().strip() or self.ana_birim
        if not birim or not carpan:
            messagebox.showwarning("Eksik bilgi", "Birim ve katsayı girin.", parent=self)
            return
        if birim.casefold() == hedef.casefold():
            messagebox.showwarning("Geçersiz", "Birim ile referans birim aynı olamaz (döngü).", parent=self)
            return
        if birim.casefold() == self.ana_birim.casefold():
            messagebox.showwarning("Geçersiz", "Temel birim dönüşüm satırı olarak eklenmez.", parent=self)
            return
        try:
            c = decimal(carpan, "Katsayı", Decimal("0.000001"))
            if c <= 0:
                raise ValueError("Dönüşüm katsayısı sıfırdan büyük olmalıdır.")
        except ValueError as hata:
            messagebox.showerror("Geçersiz katsayı", str(hata), parent=self)
            return
        for item in self.tablo.get_children():
            if self.tablo.item(item, "values")[0].casefold() == birim.casefold():
                messagebox.showwarning("Mükerrer", f"'{birim}' zaten tanımlı.", parent=self)
                return
        # Geçici ekle, zincir çözülemezse geri al
        d = {
            "birim_adi": birim,
            "carpan": carpan,
            "referans_birim": hedef,
            "referans_carpan": carpan,
            "fiyat_modu": "manuel",
            "alis_fiyati": "",
            "satis_fiyatlari": {},
            "alis_kullanilabilir": True,
            "satis_kullanilabilir": True,
            "varsayilan_goruntuleme": False,
            "varsayilan_alis": False,
            "varsayilan_satis": False,
            "birim_barkod": "",
            "ondalik": 0,
            "aktif": True,
        }
        self._satir_ekle(d)
        harita = self._ana_carpan_haritasi()
        if birim.strip() not in harita and birim.strip().casefold() not in {
            k.casefold() for k in harita
        }:
            # sil son eklenen
            items = self.tablo.get_children()
            son = items[-1]
            self.tablo.delete(son)
            self._kayitlar.pop(son, None)
            messagebox.showerror(
                "Döngü / eksik zincir",
                f"'{birim}' temel birime ({self.ana_birim}) bağlanamadı. Referans birimi kontrol edin.",
                parent=self,
            )
            return
        self._ana_carpanlari_yenile()
        self.birim.set("")
        self.carpan.delete(0, "end")

    def sil(self):
        for item in self.tablo.selection():
            self.tablo.delete(item)
            self._kayitlar.pop(item, None)
        self._ana_carpanlari_yenile()

    def _satir_secildi(self, _e=None):
        secim = self.tablo.selection()
        if not secim:
            return
        iid = secim[0]
        d = self._kayitlar.get(iid) or {}
        self._secili_lbl.configure(text=d.get("birim_adi") or "—")
        mod = d.get("fiyat_modu") or "manuel"
        self.fiyat_modu.set("Katsayıdan Otomatik" if str(mod).startswith("oto") else "Manuel")
        self.alis_fiyat.delete(0, "end")
        if d.get("alis_fiyati") not in (None, ""):
            self.alis_fiyat.insert(0, str(d.get("alis_fiyati")))
        for ad, e in self.satis_girisleri.items():
            e.delete(0, "end")
            v = (d.get("satis_fiyatlari") or {}).get(ad)
            if v not in (None, ""):
                e.insert(0, str(v))
        self.var_alis_kul.set(bool(d.get("alis_kullanilabilir", True)))
        self.var_satis_kul.set(bool(d.get("satis_kullanilabilir", True)))
        self.var_aktif.set(bool(d.get("aktif", True)))
        self.birim_barkod.delete(0, "end")
        if d.get("birim_barkod"):
            self.birim_barkod.insert(0, d["birim_barkod"])
        self._formül_guncelle(d)

    def _formül_guncelle(self, d: dict):
        try:
            carpan = Decimal(str(d.get("carpan") or 1))
        except Exception:
            carpan = Decimal("1")
        temel = self.ana_fiyatlar.get("SATIŞ FİYATI 1")
        if temel is not None:
            try:
                t = Decimal(str(temel).replace(",", "."))
                oto = (t * carpan).quantize(Decimal("0.0001"))
                self.formül_lbl.configure(
                    text=f"Otomatik öneri SF1: {temel} × {carpan} = {oto} TL (kaydetmek için Otomatik mod)"
                )
                return
            except Exception:
                pass
        self.formül_lbl.configure(text=f"Temel karşılık: 1 {d.get('birim_adi')} = {carpan} {self.ana_birim}")

    def _fiyat_formundan_yaz(self):
        secim = self.tablo.selection()
        if not secim:
            return
        iid = secim[0]
        d = self._kayitlar.setdefault(iid, {})
        d["fiyat_modu"] = "otomatik" if self.fiyat_modu.get().startswith("Katsayı") else "manuel"
        d["alis_fiyati"] = self.alis_fiyat.get().strip()
        satis = {}
        for ad, e in self.satis_girisleri.items():
            v = e.get().strip()
            if v:
                satis[ad] = v
        d["satis_fiyatlari"] = satis
        d["alis_kullanilabilir"] = bool(self.var_alis_kul.get())
        d["satis_kullanilabilir"] = bool(self.var_satis_kul.get())
        d["aktif"] = bool(self.var_aktif.get())
        d["birim_barkod"] = self.birim_barkod.get().strip()
        # Otomatik modda fiyatları öneriyle doldur (manuel alanları ezme — yalnızca boşsa)
        if d["fiyat_modu"] == "otomatik":
            try:
                carpan = Decimal(str(d.get("carpan") or 1))
            except Exception:
                carpan = Decimal("1")
            for ad, e in self.satis_girisleri.items():
                if e.get().strip():
                    continue
                temel = self.ana_fiyatlar.get(ad.upper())
                if temel is None:
                    continue
                try:
                    oto = (Decimal(str(temel).replace(",", ".")) * carpan).quantize(Decimal("0.0001"))
                    e.insert(0, f"{oto:f}".rstrip("0").rstrip("."))
                    satis[ad] = e.get()
                except Exception:
                    pass
            d["satis_fiyatlari"] = satis
        degerler = list(self.tablo.item(iid, "values"))
        degerler[4] = "Otomatik" if d["fiyat_modu"] == "otomatik" else "Manuel"
        degerler[5] = "Evet" if d["aktif"] else "Hayır"
        self.tablo.item(iid, values=tuple(degerler))
        self._formül_guncelle(d)

    def _test_et(self):
        self._fiyat_formundan_yaz()
        self._ana_carpanlari_yenile()
        try:
            m = decimal(self.test_miktar.get(), "Test miktar", Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Test", str(hata), parent=self)
            return
        kaynak = self.test_kaynak.get().strip() or self.ana_birim
        hedef = self.test_hedef.get().strip() or self.ana_birim
        birimler = list(self._kayitlar.values())
        oniz = StokService.birim_donusum_onizleme(m, kaynak, hedef, birimler, self.ana_birim)
        self.test_sonuc.configure(
            text=(
                f"{m} {kaynak} = {oniz['temel_miktar']} {self.ana_birim} "
                f"| {oniz['hedef_miktar']} {hedef}"
            )
        )

    def _hata_stili_hazirla(self):
        try:
            stil = ttk.Style(self)
            stil.configure("BirimHata.TEntry", fieldbackground="#FEE2E2")
            stil.configure("BirimHata.TCombobox", fieldbackground="#FEE2E2")
        except tk.TclError:
            pass

    def _hata_temizle(self):
        for w in self._hata_widgetleri:
            try:
                if isinstance(w, ttk.Entry):
                    w.configure(style="TEntry")
                elif isinstance(w, ttk.Combobox):
                    w.configure(style="TCombobox")
                elif isinstance(w, tk.Widget):
                    w.configure(highlightthickness=0)
            except tk.TclError:
                pass
        self._hata_widgetleri = []

    def _hata_isaretle(self, widget):
        if widget is None:
            return
        try:
            if isinstance(widget, ttk.Entry):
                widget.configure(style="BirimHata.TEntry")
            elif isinstance(widget, ttk.Combobox):
                widget.configure(style="BirimHata.TCombobox")
            else:
                widget.configure(highlightthickness=2, highlightbackground="#DC2626", highlightcolor="#DC2626")
            self._hata_widgetleri.append(widget)
            widget.focus_set()
        except tk.TclError:
            pass

    def _durum_ozeti(self) -> str:
        self._fiyat_formundan_yaz()
        birimler = []
        for item in self.tablo.get_children():
            d = dict(self._kayitlar.get(item) or {})
            birimler.append(
                {
                    "birim_adi": d.get("birim_adi"),
                    "carpan": d.get("carpan"),
                    "referans_birim": d.get("referans_birim"),
                    "referans_carpan": d.get("referans_carpan"),
                    "birim_barkod": d.get("birim_barkod"),
                    "alis_fiyati": d.get("alis_fiyati"),
                    "satis_fiyatlari": d.get("satis_fiyatlari") or {},
                    "fiyat_modu": d.get("fiyat_modu"),
                    "aktif": d.get("aktif", True),
                }
            )
        return json.dumps(
            {
                "birimler": birimler,
                "v_goruntu": self.v_goruntu.get(),
                "v_alis": self.v_alis.get(),
                "v_satis": self.v_satis.get(),
                "ana_birim": self.ana_birim,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    def _kirli_mi(self) -> bool:
        try:
            return self._durum_ozeti() != getattr(self, "_baslangic_ozet", "")
        except Exception:
            return True

    def _sonuc_hazirla(self):
        """Doğrulayıp birim listesini döndürür; hata varsa ValueError."""
        self._hata_temizle()
        self._fiyat_formundan_yaz()
        harita = self._ana_carpan_haritasi()
        sonuc = []
        gorulen_ad = set()
        gorulen_barkod = set()

        # Formdaki henüz eklenmemiş satır (boş bırakılabilir)
        form_birim = self.birim.get().strip()
        form_carpan = self.carpan.get().strip()
        if form_birim or form_carpan:
            if not form_birim:
                self._hata_isaretle(self.birim)
                raise ValueError("Birim adı boş olamaz.")
            if not form_carpan:
                self._hata_isaretle(self.carpan)
                raise ValueError("Dönüşüm katsayısı girilmelidir.")

        for item in self.tablo.get_children():
            d = dict(self._kayitlar.get(item) or {})
            birim_adi = (d.get("birim_adi") or self.tablo.item(item, "values")[0] or "").strip()
            if not birim_adi:
                self._hata_isaretle(self.birim)
                raise ValueError("Birim adı boş olamaz.")
            if birim_adi.casefold() in gorulen_ad:
                raise ValueError(f"Aynı stokta «{birim_adi}» birimi birden fazla tanımlı.")
            gorulen_ad.add(birim_adi.casefold())

            if birim_adi.casefold() == self.ana_birim.casefold():
                try:
                    c_ana = decimal(
                        d.get("carpan") or self.tablo.item(item, "values")[1] or "1",
                        "Ana birim katsayısı",
                        Decimal("0"),
                    )
                except ValueError as exc:
                    self._hata_isaretle(self.carpan)
                    raise ValueError(str(exc)) from None
                if c_ana != 1:
                    self._hata_isaretle(self.carpan)
                    raise ValueError("Ana birim dönüşüm katsayısı 1 olmalıdır.")
                continue

            ana = harita.get(birim_adi)
            if ana is None:
                for k, v in harita.items():
                    if k.casefold() == birim_adi.casefold():
                        ana = v
                        break
            if ana is None:
                raise ValueError(
                    f"«{birim_adi}» birimi ana birime ({self.ana_birim}) bağlanamadı. "
                    "Zinciri tamamlayın."
                )
            if ana <= 0:
                self._hata_isaretle(self.carpan)
                raise ValueError(f"«{birim_adi}» dönüşüm katsayısı sıfır veya negatif olamaz.")

            ref_c = d.get("referans_carpan") or self.tablo.item(item, "values")[1]
            if ref_c not in (None, ""):
                try:
                    rc = decimal(ref_c, f"{birim_adi} katsayısı", Decimal("0.000001"))
                except ValueError as exc:
                    self._hata_isaretle(self.carpan)
                    raise ValueError(str(exc)) from None
                if rc <= 0:
                    self._hata_isaretle(self.carpan)
                    raise ValueError(f"«{birim_adi}» dönüşüm katsayısı sıfır veya negatif olamaz.")

            bb = (d.get("birim_barkod") or "").strip()
            if bb:
                if bb.casefold() in gorulen_barkod:
                    self._hata_isaretle(self.birim_barkod)
                    raise ValueError(f"Birim barkodu mükerrer: {bb}")
                gorulen_barkod.add(bb.casefold())

            if d.get("alis_fiyati") not in (None, ""):
                try:
                    alis = decimal(d["alis_fiyati"], f"{birim_adi} alış", Decimal("0"))
                except ValueError as exc:
                    self._hata_isaretle(self.alis_fiyat)
                    raise ValueError(str(exc)) from None
                if alis < 0:
                    self._hata_isaretle(self.alis_fiyat)
                    raise ValueError(f"«{birim_adi}» alış fiyatı negatif olamaz.")

            satis = dict(d.get("satis_fiyatlari") or {})
            for fiyat_adi, ham in list(satis.items()):
                if ham in (None, ""):
                    continue
                try:
                    tutar = decimal(ham, fiyat_adi, Decimal("0"))
                except ValueError as exc:
                    w = self.satis_girisleri.get(fiyat_adi)
                    self._hata_isaretle(w)
                    raise ValueError(str(exc)) from None
                if tutar < 0:
                    w = self.satis_girisleri.get(fiyat_adi)
                    self._hata_isaretle(w)
                    raise ValueError(f"{fiyat_adi} negatif olamaz.")

            d["birim_adi"] = birim_adi
            d["carpan"] = f"{ana:f}".rstrip("0").rstrip(".")
            d["varsayilan_goruntuleme"] = self.v_goruntu.get().casefold() == birim_adi.casefold()
            d["varsayilan_alis"] = self.v_alis.get().casefold() == birim_adi.casefold()
            d["varsayilan_satis"] = self.v_satis.get().casefold() == birim_adi.casefold()
            sonuc.append(d)

        return {
            "birimler": sonuc,
            "varsayilan_goruntuleme_birim": self.v_goruntu.get().strip() or self.ana_birim,
            "varsayilan_alis_birim": self.v_alis.get().strip() or self.ana_birim,
            "varsayilan_satis_birim": self.v_satis.get().strip() or self.ana_birim,
        }

    def _kayit_aktif_mi(self) -> bool:
        if self._kayit_devam or self._f1_kilit or self._kapatiliyor:
            return False
        try:
            return str(self.btn_kaydet.cget("state")) != "disabled"
        except tk.TclError:
            return False

    def _kayit_pasiflestir(self, pasif: bool):
        durum = "disabled" if pasif else "normal"
        for btn in (
            getattr(self, "btn_kaydet", None),
            getattr(self, "btn_kaydet_kapat", None),
            getattr(self, "btn_vazgec", None),
        ):
            if btn is None:
                continue
            try:
                btn.configure(state=durum)
            except tk.TclError:
                pass
        self._kayit_devam = pasif
        self._f1_kilit = pasif

    def _kaydet_acik_kal(self):
        """Kaydet (F1) — kayıt sonrası pencere açık kalır."""
        return self.kaydet(kapat=False)

    def _kaydet_ve_kapat(self):
        """Kaydet ve Kapat — yalnızca başarıda kapanır."""
        return self.kaydet(kapat=True)

    def _f1_kaydet(self, _event=None):
        """F1 = Kaydet (F1) düğmesiyle aynı; pencere açık kalır."""
        try:
            if not self.winfo_exists():
                return "break"
            if not self._kayit_aktif_mi():
                return "break"
            odak = self.focus_get()
            if odak is None:
                return "break"
            w = odak
            while w is not None:
                if w == self:
                    self._f1_kilit = True
                    try:
                        self.kaydet(kapat=False)
                    finally:
                        try:
                            if self.winfo_exists():
                                self.after(400, self._f1_kilidi_ac)
                        except tk.TclError:
                            pass
                    return "break"
                w = w.master if hasattr(w, "master") else None
        except tk.TclError:
            return "break"
        return "break"

    def _f1_kilidi_ac(self):
        try:
            if self.winfo_exists() and not self._kayit_devam:
                self._f1_kilit = False
        except tk.TclError:
            pass

    def _tabloyu_paketten_yenile(self, paket: dict):
        """Kayıt sonrası sol birim listesini günceller."""
        from database.stok_service import _birim_kayit_normalize

        for item in self.tablo.get_children():
            self.tablo.delete(item)
        self._kayitlar.clear()
        for kayit in paket.get("birimler") or []:
            d = _birim_kayit_normalize(kayit, ana_birim=self.ana_birim)
            if not d.get("birim_adi"):
                continue
            self._satir_ekle(d)
        self._ana_carpanlari_yenile()
        self._varsayilan_listeleri_yenile()
        vg = (paket.get("varsayilan_goruntuleme_birim") or "").strip()
        va = (paket.get("varsayilan_alis_birim") or "").strip()
        vs = (paket.get("varsayilan_satis_birim") or "").strip()
        if vg:
            self.v_goruntu.set(vg)
        if va:
            self.v_alis.set(va)
        if vs:
            self.v_satis.set(vs)

    def kaydet(self, kapat: bool = False) -> bool:
        """Birimleri doğrula ve kaydet. Varsayılan: pencere açık kalır (Kaydet F1)."""
        if self._kayit_devam:
            return False
        self._kayit_pasiflestir(True)
        try:
            try:
                paket = self._sonuc_hazirla()
            except ValueError as hata:
                messagebox.showerror("Doğrulama", str(hata), parent=self)
                return False

            if self.stok_id:
                try:
                    kayit = StokService.stok_birimleri_kaydet(
                        self.stok_id,
                        paket["birimler"],
                        varsayilan_goruntuleme_birim=paket["varsayilan_goruntuleme_birim"],
                        varsayilan_alis_birim=paket["varsayilan_alis_birim"],
                        varsayilan_satis_birim=paket["varsayilan_satis_birim"],
                        ana_birim=self.ana_birim,
                    )
                except Exception as hata:
                    messagebox.showerror("Kayıt hatası", str(hata), parent=self)
                    return False
                paket = {
                    "birimler": kayit.get("birimler") or paket["birimler"],
                    "varsayilan_goruntuleme_birim": kayit.get("varsayilan_goruntuleme_birim")
                    or paket["varsayilan_goruntuleme_birim"],
                    "varsayilan_alis_birim": kayit.get("varsayilan_alis_birim")
                    or paket["varsayilan_alis_birim"],
                    "varsayilan_satis_birim": kayit.get("varsayilan_satis_birim")
                    or paket["varsayilan_satis_birim"],
                }
                messagebox.showinfo(
                    "Kayıt",
                    "Birim bilgileri başarıyla kaydedildi",
                    parent=self,
                )
            else:
                messagebox.showinfo(
                    "Kayıt",
                    "Birim bilgileri başarıyla kaydedildi\n"
                    "(Stok kartı henüz kaydedilmediği için birimler kart kaydında kalıcılaşacak.)",
                    parent=self,
                )

            self.result = paket
            self._tabloyu_paketten_yenile(paket)
            self._baslangic_ozet = self._durum_ozeti()
            if callable(self.on_saved):
                try:
                    self.on_saved(paket)
                except Exception:
                    pass
            if kapat:
                self._kapatiliyor = True
                self.destroy()
            return True
        finally:
            if not self._kapatiliyor:
                self._kayit_pasiflestir(False)

    def tamam(self):
        """Geriye dönük uyumluluk — Kaydet ve Kapat."""
        self.kaydet(kapat=True)

    def _kapat_istegi(self):
        if self._kapatiliyor or self._kayit_devam:
            return
        if not self._kirli_mi():
            self.destroy()
            return
        secim = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklikler var",
            "Kaydedilmemiş değişiklikler var.\n\n"
            "Evet: Kaydet ve Kapat\n"
            "Hayır: Kaydetmeden Kapat\n"
            "İptal: Vazgeç",
            parent=self,
        )
        if secim is True:
            self.kaydet(kapat=True)
        elif secim is False:
            self.result = None
            self._kapatiliyor = True
            self.destroy()
        # None = Vazgeç — ekranda kal

    def destroy(self):
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        super().destroy()


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
        from hesap_kodu_sec_ui import muhasebe_hesap_entry_bagla

        ttk.Label(
            self,
            text="3 hane yazın veya sağ tık / F2 / … ile TDHP hesap planından seçin.",
            foreground="#555",
            wraplength=420,
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 4), sticky="w")
        for satir, (etiket, alan) in enumerate(self.ALANLAR, start=1):
            ttk.Label(self, text=etiket).grid(row=satir, column=0, padx=12, pady=6, sticky="w")
            giris = ttk.Entry(self, width=28)
            giris.grid(row=satir, column=1, padx=(12, 4), pady=6, sticky="w")
            giris.insert(0, degerler.get(alan) or "")
            self.alanlar[alan] = giris
            muhasebe_hesap_entry_bagla(self, giris)
            ttk.Button(
                self,
                text="…",
                width=3,
                command=lambda g=giris: self._hesap_sec(g),
            ).grid(row=satir, column=2, padx=(0, 12), pady=6)
        butonlar = ttk.Frame(self)
        butonlar.grid(row=len(self.ALANLAR) + 1, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Tamam", command=self.tamam).pack(side="right")

    def _hesap_sec(self, giris):
        from hesap_kodu_sec_ui import HesapKoduSecDialog

        dlg = HesapKoduSecDialog(self, onek=(giris.get() or "").strip())
        self.wait_window(dlg)
        if dlg.result:
            giris.delete(0, "end")
            giris.insert(0, dlg.result)

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
                    *[ _birim_adi(b) for b in (birimler or []) if _birim_adi(b) ],
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
    """Stok hareket ekstresi: Giriş / Çıkış / Kalan + satır FIFO kalan değeri."""

    def __init__(self, parent, stok):
        super().__init__(parent)
        self.stok = stok
        self._sonuc = None
        self._evrak_aciliyor = False
        self.title(f"Stok Hareketleri — {stok.stok_kodu} / {stok.stok_adi}")
        self.geometry("1280x620")
        self.minsize(980, 480)
        self.transient(parent)
        self.grab_set()
        try:
            self.configure(bg=ACIK_BG)
            stok_stil_uygula(root=self)
        except Exception:
            pass

        ust = tk.Frame(self, bg=BEYAZ, padx=10, pady=8)
        ust.pack(fill="x")
        tk.Label(ust, text="Başlangıç", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.baslangic = ttk.Entry(ust, width=12)
        self.baslangic.pack(side="left", padx=(4, 10))
        self.baslangic.insert(0, tarih_goster(date.today().replace(month=1, day=1)))
        tk.Label(ust, text="Bitiş", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.bitis = ttk.Entry(ust, width=12)
        self.bitis.pack(side="left", padx=(4, 10))
        self.bitis.insert(0, tarih_goster(date.today()))
        tk.Label(ust, text="Depo", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.depo_var = tk.StringVar(value="(Tümü)")
        depolar = ["(Tümü)"]
        try:
            depolar += [d.ad for d in StokService.depolar(aktif_only=True)]
        except Exception:
            pass
        self.depo_cb = ttk.Combobox(
            ust, textvariable=self.depo_var, values=depolar, width=16, state="readonly"
        )
        self.depo_cb.pack(side="left", padx=(4, 10))
        tk.Label(ust, text="Ara", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.arama = ttk.Entry(ust, width=14)
        self.arama.pack(side="left", padx=(4, 10))
        stok_tk_buton(ust, "Listele", self.yenile, rol="ara").pack(side="left")
        stok_tk_buton(ust, "Tümü", self.tumunu_goster, rol="ikincil").pack(side="left", padx=6)
        stok_tk_buton(ust, "Excel", self._excel_aktar, rol="ikincil").pack(side="right")
        stok_tk_buton(ust, "PDF", self._pdf_aktar, rol="ikincil").pack(side="right", padx=(0, 6))

        cerceve = tk.Frame(self, bg=BEYAZ, padx=10)
        cerceve.pack(fill="both", expand=True)
        self._kolon_ayarlari = hareket_kolon_ayarlari_yukle()
        self._kolon_idler = tuple(self._kolon_ayarlari.keys())
        self.tablo = ttk.Treeview(
            cerceve, columns=self._kolon_idler, show="headings", selectmode="browse"
        )
        self._kolonlari_uygula()
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        kaydirma.pack(side="right", fill="y")
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(xscrollcommand=xscroll.set)
        xscroll.pack(fill="x", padx=10)
        self.tablo.tag_configure("giris", foreground=_HAREKET_GIRIS_FG)
        self.tablo.tag_configure("cikis", foreground=_HAREKET_CIKIS_FG)
        self.tablo.tag_configure("devri", foreground=LACIVERT)
        self.tablo.tag_configure("notr", foreground=_HAREKET_NOTR_FG)
        self.tablo.tag_configure("negatif", background="#FFCDD2", foreground="#B71C1C")
        self.tablo.tag_configure("zebra", background="#F7F9FC")
        self.tablo.bind("<Double-1>", self.evrak_ac)
        self.tablo.bind("<ButtonRelease-1>", self._kolon_genislik_kaydet)
        self.tablo.bind("<Return>", self.evrak_ac)

        self.ozet = tk.Label(self, text="", bg=ACIK_BG, fg=LACIVERT, anchor="w", justify="left")
        self.ozet.pack(anchor="w", padx=12, pady=(6, 0), fill="x")
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=12, pady=10)
        stok_tk_buton(alt, "Evrakı Aç", self.evrak_ac, rol="ara").pack(side="left")
        stok_tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        self.yenile()

    def _kolonlari_uygula(self):
        ayar = self._kolon_ayarlari
        for kolon in self._kolon_idler:
            cfg = ayar[kolon]
            baslik = cfg["baslik"]
            sayisal = kolon in _HAREKET_SAYISAL_KOLONLAR
            self.tablo.heading(kolon, text=baslik, anchor="e" if sayisal else "w")
            gorunur = cfg.get("gorunur", True)
            self.tablo.column(
                kolon,
                width=cfg["genislik"] if gorunur else 0,
                minwidth=0 if not gorunur else 40,
                stretch=gorunur,
                anchor="e" if sayisal else "w",
            )

    def _kolon_genislik_kaydet(self, _event=None):
        for kolon in self._kolon_idler:
            try:
                self._kolon_ayarlari[kolon]["genislik"] = int(self.tablo.column(kolon, "width"))
            except Exception:
                pass
        try:
            hareket_kolon_ayarlari_kaydet(self._kolon_ayarlari)
        except Exception:
            pass

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
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService

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
        depo = self.depo_var.get()
        if depo in ("(Tümü)", ""):
            depo = None
        arama = self.arama.get().strip() or None
        tum = baslangic is None and bitis is None
        try:
            self._sonuc = FiyatliStokEkstreService.hareket_ekstresi(
                self.stok.id,
                baslangic=baslangic,
                bitis=bitis,
                depo_adi=depo,
                belge_arama=arama,
                tum_gecmis=tum,
            )
        except Exception as exc:
            messagebox.showerror("Hareketler", str(exc), parent=self)
            return

        maliyet_ok = self._sonuc.get("maliyet_gorunur", True)
        for sira, s in enumerate(self._sonuc.get("satirlar") or []):
            tarih = s.get("tarih")
            saat = s.get("saat") or ""
            tarih_metin = ""
            if tarih:
                tarih_metin = tarih_goster(tarih)
                if saat:
                    tarih_metin = f"{tarih_metin} {saat[:5]}"
            cari = " ".join(
                x for x in ((s.get("cari_kodu") or "").strip(), (s.get("cari_adi") or "").strip()) if x
            )
            yon = s.get("yon") or "notr"
            tags = [yon]
            if sira % 2 == 1:
                tags.append("zebra")
            kalan = s.get("kalan")
            try:
                if Decimal(str(kalan or 0)) < 0:
                    tags = ["negatif"]
            except Exception:
                pass
            fifo_txt = ""
            if maliyet_ok and s.get("kalan_deger") is not None:
                fifo_txt = para_goster(s.get("kalan_deger"))
            elif s.get("fifo_hesaplanamadi"):
                fifo_txt = "—"
            aciklama = s.get("aciklama") or s.get("uyari") or ""
            kaynak = (s.get("fiyat_kaynak") or "").strip()
            if kaynak and kaynak not in aciklama:
                aciklama = f"{aciklama} | {kaynak}".strip(" |") if aciklama else kaynak
            try:
                if Decimal(str(kalan or 0)) < 0 and "⚠" not in aciklama:
                    aciklama = f"⚠ Negatif stok | {aciklama}".strip(" |")
            except Exception:
                pass
            net_g = s.get("net_giris_birim_fiyat", s.get("giris_birim_fiyat"))
            net_c = s.get("net_cikis_birim_fiyat", s.get("cikis_satis_fiyat"))
            fiyat_yok = bool(s.get("fiyat_yok"))
            self.tablo.insert(
                "",
                "end",
                iid=f"{sira}:{s.get('belge_no')}:{s.get('hareket_turu')}",
                values=(
                    tarih_metin,
                    s.get("belge_turu") or s.get("hareket_turu") or "",
                    s.get("belge_no") or "",
                    cari,
                    s.get("depo") or "",
                    s.get("birim") or self._sonuc.get("ana_birim") or "",
                    miktar_goster_tr(s.get("giren"), bos_sifir=True),
                    _net_fiyat_goster(
                        net_g, fiyat_yok=fiyat_yok and yon == "giris" and net_g is None
                    ),
                    miktar_goster_tr(s.get("cikan"), bos_sifir=True),
                    _net_fiyat_goster(
                        net_c, fiyat_yok=fiyat_yok and yon == "cikis" and net_c is None
                    ),
                    miktar_goster_tr(kalan),
                    fifo_txt,
                    aciklama,
                ),
                tags=tuple(tags),
            )
        o = self._sonuc.get("ozet") or {}
        uyari_txt = ""
        if self._sonuc.get("uyarilar"):
            uyari_txt = f"  ·  Uyarı: {len(self._sonuc['uyarilar'])}"
        self.ozet.configure(
            text=(
                f"Kayıt: {len(self._sonuc.get('satirlar') or [])}  ·  "
                f"Toplam Giriş: {miktar_goster_tr(o.get('giren_miktar'))}  ·  "
                f"Toplam Çıkış: {miktar_goster_tr(o.get('cikan_miktar'))}  ·  "
                f"Son Kalan: {miktar_goster_tr(o.get('kalan_miktar'))}  ·  "
                f"Son FIFO: {para_goster(o.get('fifo_kalan_degeri') or o.get('kalan_stok_degeri'))}"
                f"{uyari_txt}"
            )
        )

    def _excel_aktar(self):
        if not self._sonuc:
            messagebox.showinfo("Excel", "Önce listeleyin.", parent=self)
            return
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService

        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"stok_hareket_{self.stok.stok_kodu}.xlsx",
        )
        if not yol:
            return
        try:
            FiyatliStokEkstreService.excel_aktar(self._sonuc, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)

    def _pdf_aktar(self):
        if not self._sonuc:
            messagebox.showinfo("PDF", "Önce listeleyin.", parent=self)
            return
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService

        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"stok_hareket_{self.stok.stok_kodu}.pdf",
        )
        if not yol:
            return
        try:
            FiyatliStokEkstreService.pdf_aktar(self._sonuc, yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def evrak_ac(self, _event=None):
        if getattr(self, "_evrak_aciliyor", False):
            return
        secim = self.tablo.selection()
        if not secim:
            return
        degerler = self.tablo.item(secim[0], "values")
        if not degerler or len(degerler) < 3:
            return
        belge_no = degerler[2]
        iid = secim[0]
        parts = str(iid).split(":")
        hareket_turu = parts[2] if len(parts) >= 3 else degerler[1]
        if (hareket_turu or "").upper() in ("DEVRİ", "DEVRI", "DEVİR"):
            return
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

    def __init__(self, parent, stok=None, baslangic=None, rapor_grubu_zorunlu=False):
        super().__init__(parent)
        self.stok = StokService.stok_getir(stok.id) if stok else None
        self.baslangic = baslangic or {}
        self.result = None
        self.rapor_grubu_zorunlu = bool(rapor_grubu_zorunlu)
        self.title("Stok Kartını Düzenle" if stok else "Yeni Stok Kartı")
        self.minsize(1100, 720)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        self.protocol("WM_DELETE_WINDOW", self._kapat_istegi)
        stok_stil_uygula(root=self)
        self._pencere_boyutunu_ayarla()

        self.aciklama = (self.stok.aciklama if self.stok else "") or ""
        self.birimler = StokService.birimleri_dict_listesi(self.stok) if self.stok else []
        # Eski kartlar: ana birim var ama stok_birimleri boşsa UI listesine ekle (sessiz DB yazımı yok)
        if self.stok and self.stok.birim:
            adlar = {_birim_adi(b).lower() for b in self.birimler}
            if self.stok.birim.lower() not in adlar:
                self.birimler = [
                    {
                        "birim_adi": self.stok.birim,
                        "carpan": "1",
                        "aktif": True,
                        "alis_kullanilabilir": True,
                        "satis_kullanilabilir": True,
                    },
                    *self.birimler,
                ]
        self.varsayilan_goruntuleme_birim = (
            (getattr(self.stok, "varsayilan_goruntuleme_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else "Adet")
            or "Adet"
        )
        self.varsayilan_alis_birim = (
            (getattr(self.stok, "varsayilan_alis_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else "Adet")
            or "Adet"
        )
        self.varsayilan_satis_birim = (
            (getattr(self.stok, "varsayilan_satis_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else "Adet")
            or "Adet"
        )
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

        kod_metin = (self.stok.stok_kodu if self.stok else "") or "Yeni kart"
        ad_metin = (self.stok.stok_adi if self.stok else "") or ""
        durum = "Aktif" if (not self.stok or getattr(self.stok, "aktif", True)) else "Pasif"
        self._baslik = baslik_seridi(
            self,
            baslik="Stok Kartı",
            alt=f"{kod_metin}" + (f"  ·  {ad_metin}" if ad_metin else ""),
            durum=durum,
        )

        # Özet rozetleri — soldan sağa: Giriş → Çıkış → Kalan → FIFO
        ozet_serit = tk.Frame(self, bg=ACIK_BG)
        ozet_serit.pack(fill="x", padx=12, pady=(10, 0))
        for col in range(4):
            ozet_serit.columnconfigure(col, weight=1, uniform="stok_ozet")
        self.ozet_kartlari = {}
        self.ozet_etiketleri = {}
        self.ozet_alt_etiketleri = {}
        _OZET_SIRA = (
            "Toplam Giriş",
            "Toplam Çıkış",
            "Kalan Miktar",
            "FIFO Envanter Değeri",
        )
        for i, baslik in enumerate(_OZET_SIRA):
            kart = ozet_karti(ozet_serit, baslik, deger="0")
            kart["frame"].grid(row=0, column=i, sticky="nsew", padx=4, pady=0)
            self.ozet_kartlari[baslik] = kart
            self.ozet_etiketleri[baslik] = kart["deger"]
            self.ozet_alt_etiketleri[baslik] = kart["alt"]

        # Alt işlem çubuğu (sabit)
        kayit = tk.Frame(self, bg=BEYAZ, highlightthickness=1, highlightbackground=sktema.CIZGI)
        kayit.pack(side="bottom", fill="x")
        kayit_ic = tk.Frame(kayit, bg=BEYAZ)
        kayit_ic.pack(fill="x", padx=12, pady=10)
        stok_tk_buton(kayit_ic, "Vazgeç", self._kapat_istegi, rol="ikincil").pack(side="right")
        stok_tk_buton(kayit_ic, "Kaydet", self.kaydet, rol="kaydet").pack(side="right", padx=(0, 8))
        stok_tk_buton(kayit_ic, "Yeni Grup Ekle", self._yeni_grup_ekle, rol="yeni").pack(
            side="left"
        )
        if self.stok:
            stok_tk_buton(kayit_ic, "Hareketler", self._hareketler_sekmesine_gec, rol="ara").pack(
                side="left", padx=(8, 0)
            )
            stok_tk_buton(kayit_ic, "Fiyat Analiz", self.fiyat_analiz_ac, rol="ikincil").pack(
                side="left", padx=(8, 0)
            )

        # Orta: sekmeler
        govde = tk.Frame(self, bg=ACIK_BG)
        govde.pack(side="top", fill="both", expand=True, padx=12, pady=10)
        self.sekmeler = ttk.Notebook(govde, style="StokKart.TNotebook")
        self.sekmeler.pack(fill="both", expand=True)

        tab_genel = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_barkod = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_fiyat = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_depo = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_hareket = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_notlar = tk.Frame(self.sekmeler, bg=BEYAZ)
        self.sekmeler.add(tab_genel, text="  Genel  ")
        self.sekmeler.add(tab_barkod, text="  Barkod & Birimler  ")
        self.sekmeler.add(tab_fiyat, text="  Fiyat & Maliyet  ")
        self.sekmeler.add(tab_depo, text="  Depo & Stok  ")
        self.sekmeler.add(tab_hareket, text="  Hareketler  ")
        self.sekmeler.add(tab_notlar, text="  Notlar  ")

        # --- Genel ---
        form = ttk.LabelFrame(tab_genel, text="Temel Bilgiler", padding=12, style="StokKart.TLabelframe")
        form.pack(fill="x", padx=10, pady=10)
        self.alanlar = {}
        temel_alanlar = (
            ("Stok Kodu", "stok_kodu", True),
            ("Stok Adı", "stok_adi", True),
            ("Kart Türü", "kart_turu", True),
            ("Ana Birim", "birim", True),
            ("KDV %", "kdv_orani", False),
            ("Marka", "marka", False),
            ("Model", "model", False),
            ("Renk", "renk", False),
            ("Ağırlık", "agirlik", False),
            ("Raf Yeri", "raf_yeri", False),
            ("Raf Ömrü", "raf_omru", False),
            ("Minimum Stok", "minimum_stok", False),
        )
        for sira, (etiket, alan, zorunlu) in enumerate(temel_alanlar):
            satir = sira // 2
            sutun = (sira % 2) * 3
            form_etiket(form, etiket, zorunlu=zorunlu).grid(
                row=satir, column=sutun, padx=6, pady=(6, 0), sticky="w"
            )
            if alan == "stok_kodu":
                widget = ttk.Combobox(form, width=22, style="StokKart.TCombobox")
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                stok_tk_buton(form, "Yeni", lambda: self.stok_alan_yeni("stok_kodu"), rol="yeni").grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=(0, 4)
                )
                widget.bind("<KeyRelease>", self._stok_kodu_keyrelease)
                widget.bind("<<ComboboxSelected>>", self._stok_kodu_secildi)
                self._stok_kodu_sag_tik_bagla(widget)
            elif alan == "stok_adi":
                widget = ttk.Combobox(form, width=22, style="StokKart.TCombobox")
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                stok_tk_buton(form, "Yeni", lambda: self.stok_alan_yeni("stok_adi"), rol="yeni").grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=(0, 4)
                )
                widget.bind("<KeyRelease>", self._stok_adi_ara)
                widget.bind("<<ComboboxSelected>>", self._stok_adi_secildi)
            elif alan == "agirlik":
                widget = ttk.Entry(form, width=26, style="StokKart.TEntry")
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
            elif alan == "kdv_orani":
                widget = ttk.Combobox(form, values=KDV_ORANLARI, width=20, state="readonly")
                mevcut_kdv = getattr(self.stok, "kdv_orani", None) if self.stok else None
                if mevcut_kdv is None:
                    widget.set(str(int(VARSAYILAN_KDV_ORANI)))
                else:
                    from database.fatura_kdv_service import satir_kdv_metin_sayisal

                    metin = satir_kdv_metin_sayisal(mevcut_kdv)
                    if metin not in KDV_ORANLARI:
                        widget.configure(values=KDV_ORANLARI + (metin,), state="normal")
                    widget.set(metin)
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
            elif alan == "raf_omru":
                widget = ttk.Combobox(form, values=StokService.raf_omru_secenekleri(), width=20)
                if self.stok and self.stok.raf_omru:
                    widget.set(tarih_goster(self.stok.raf_omru))
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                stok_tk_buton(form, "Yeni", self.raf_omru_sec, rol="yeni").grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=(0, 4)
                )
            elif alan == "minimum_stok":
                widget = ttk.Entry(form, width=26, style="StokKart.TEntry")
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                if self.stok and getattr(self.stok, "minimum_stok", None) is not None:
                    ms = Decimal(str(self.stok.minimum_stok or 0))
                    if ms != 0:
                        widget.insert(0, f"{ms:f}".rstrip("0").rstrip("."))
            elif alan == "birim":
                degerler = self._ana_birim_secenekleri()
                widget = ttk.Combobox(form, values=degerler, width=20)
                mevcut_birim = (self.stok.birim if self.stok else None) or (
                    degerler[0] if degerler else ""
                )
                if mevcut_birim:
                    widget.set(mevcut_birim)
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                widget.bind("<FocusIn>", lambda _e: self._ana_birim_listesini_yenile())
                stok_tk_buton(form, "Birimler…", self.birimler_ac, rol="yeni").grid(
                    row=satir, column=sutun + 2, padx=(0, 6), pady=(0, 4)
                )
            else:
                if alan == "kart_turu":
                    degerler = StokService.kart_turu_secenekleri(KART_TURLERI)
                else:
                    degerler = StokService.secenekleri_listele(alan)
                widget = ttk.Combobox(form, values=degerler, width=20)
                if alan == "kart_turu":
                    widget.set((self.stok.kart_turu if self.stok else None) or "Ticari Mal")
                elif self.stok and getattr(self.stok, alan, None):
                    widget.set(getattr(self.stok, alan))
                widget.grid(row=satir, column=sutun + 1, padx=6, pady=(0, 4), sticky="ew")
                kayit_turu = alan
                stok_tk_buton(
                    form,
                    "Yeni",
                    lambda a=alan, t=kayit_turu: self.secenek_ekle(a, t),
                    rol="yeni",
                ).grid(row=satir, column=sutun + 2, padx=(0, 6), pady=(0, 4))
                widget.bind("<Return>", lambda e, a=alan, t=kayit_turu: self.secenek_yazilanı_kaydet(a, t))
            self.alanlar[alan] = widget
        form.columnconfigure(1, weight=1)
        form.columnconfigure(4, weight=1)
        self._stok_kod_eslesme = {}
        self._stok_ad_eslesme = {}

        # Üç seviyeli stok grubu
        grup_cer = ttk.LabelFrame(
            tab_genel, text="Stok Grubu (Ana → Tali → Alt)", padding=12, style="StokKart.TLabelframe"
        )
        grup_cer.pack(fill="x", padx=10, pady=(0, 10))
        self._grup_id_map = {"ana": {}, "tali": {}, "alt": {}}
        self.grup_alanlari = {}
        for kol, (etiket, anahtar) in enumerate(
            (("Ana Grup", "ana"), ("Tali Grup", "tali"), ("Alt Grup", "alt"))
        ):
            form_etiket(grup_cer, etiket).grid(row=0, column=kol * 2, padx=6, pady=(0, 2), sticky="w")
            cb = ttk.Combobox(grup_cer, width=28)
            cb.grid(row=1, column=kol * 2, columnspan=2, padx=6, pady=(0, 4), sticky="ew")
            self.grup_alanlari[anahtar] = cb
            grup_cer.columnconfigure(kol * 2, weight=1)
        self.grup_pasif_lbl = tk.Label(
            grup_cer, text="", bg=BEYAZ, fg="#C62828", font=sktema.font(9, root=self)
        )
        self.grup_pasif_lbl.grid(row=2, column=0, columnspan=6, sticky="w", padx=6)
        self.grup_alanlari["ana"].bind("<<ComboboxSelected>>", lambda _e: self._grup_ana_degisti())
        self.grup_alanlari["tali"].bind("<<ComboboxSelected>>", lambda _e: self._grup_tali_degisti())
        self.grup_alanlari["ana"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("ana"))
        self.grup_alanlari["tali"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("tali"))
        self.grup_alanlari["alt"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("alt"))
        self._grup_listelerini_yukle(ilk=True)

        genel_aksiyon = tk.Frame(tab_genel, bg=BEYAZ)
        genel_aksiyon.pack(fill="x", padx=10, pady=(0, 10))
        stok_tk_buton(genel_aksiyon, "Muhasebe Kodları", self.muhasebe_ac, rol="ikincil").pack(side="left")
        stok_tk_buton(genel_aksiyon, "Stok Resimleri", self.resimler_ac, rol="ikincil").pack(
            side="left", padx=(8, 0)
        )

        # --- Barkod & Birimler ---
        bb_ust = tk.Frame(tab_barkod, bg=BEYAZ)
        bb_ust.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(
            bb_ust,
            text="Barkodlar firma içinde benzersizdir. Birim dönüşüm katsayısı 0 olamaz; ana birim katsayısı 1 kabul edilir.",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
            wraplength=980,
            justify="left",
        ).pack(anchor="w")

        barkod_cerceve = ttk.LabelFrame(
            tab_barkod, text="Barkod Bilgileri", padding=8, style="StokKart.TLabelframe"
        )
        barkod_cerceve.pack(fill="both", expand=True, padx=10, pady=(4, 4))
        bb_btn = tk.Frame(barkod_cerceve, bg=BEYAZ)
        bb_btn.pack(fill="x", pady=(0, 6))
        stok_tk_buton(bb_btn, "Yeni Barkod", self.barkodlar_ac, rol="kaydet").pack(side="left")
        stok_tk_buton(bb_btn, "Barkodu Düzenle", self.barkodlar_ac, rol="ikincil").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(bb_btn, "Barkodu Sil", self._barkod_satir_sil, rol="tehlike").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(bb_btn, "Birincil Yap", self._barkod_birincil_yap, rol="vurgu").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(bb_btn, "EAN-13 Oluştur", self.ean13_barkod_olustur, rol="ara").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(bb_btn, "Etiket Yazdır", self._barkod_etiket_yazdir, rol="ikincil").pack(
            side="left", padx=(6, 0)
        )

        barkod_tablo_cer = tk.Frame(barkod_cerceve, bg=BEYAZ)
        barkod_tablo_cer.pack(fill="both", expand=True)
        self.barkod_tablo = ttk.Treeview(
            barkod_tablo_cer,
            columns=("birincil", "barkod", "tur", "birim", "carpan", "fiyat", "aktif"),
            show="headings",
            height=5,
            style="StokKart.Treeview",
            selectmode="browse",
        )
        for kolon, baslik, w, ank in (
            ("birincil", "Birincil", 60, "center"),
            ("barkod", "Barkod", 140, "w"),
            ("tur", "Barkod Türü", 100, "w"),
            ("birim", "Birim", 80, "w"),
            ("carpan", "Dönüşüm", 80, "e"),
            ("fiyat", "Fiyat", 90, "e"),
            ("aktif", "Aktiflik", 70, "center"),
        ):
            self.barkod_tablo.heading(kolon, text=baslik, anchor=ank)
            self.barkod_tablo.column(kolon, width=w, anchor=ank)
        bb_scroll = ttk.Scrollbar(barkod_tablo_cer, orient="vertical", command=self.barkod_tablo.yview)
        self.barkod_tablo.configure(yscrollcommand=bb_scroll.set)
        self.barkod_tablo.pack(side="left", fill="both", expand=True)
        bb_scroll.pack(side="right", fill="y")
        self.barkod_tablo.bind("<Double-1>", lambda _e: self.barkodlar_ac())
        self.barkod_bos_lbl = tk.Label(
            barkod_cerceve,
            text="",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
            justify="left",
        )
        self.barkod_bos_lbl.pack(anchor="w", pady=(4, 0))

        birim_cerceve = ttk.LabelFrame(
            tab_barkod, text="Alternatif Birimler", padding=8, style="StokKart.TLabelframe"
        )
        birim_cerceve.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        bu_btn = tk.Frame(birim_cerceve, bg=BEYAZ)
        bu_btn.pack(fill="x", pady=(0, 6))
        stok_tk_buton(bu_btn, "Barkod Birim Dönüştürücü", self.birimler_ac, rol="kaydet").pack(
            side="left"
        )
        stok_tk_buton(bu_btn, "Düzenle", self.birimler_ac, rol="ikincil").pack(side="left", padx=(6, 0))
        stok_tk_buton(bu_btn, "Sil", self._birim_satir_sil, rol="tehlike").pack(side="left", padx=(6, 0))

        birim_tablo_cer = tk.Frame(birim_cerceve, bg=BEYAZ)
        birim_tablo_cer.pack(fill="both", expand=True)
        self.birim_tablo = ttk.Treeview(
            birim_tablo_cer,
            columns=("birim", "carpan", "alis", "satis", "aktif"),
            show="headings",
            height=4,
            style="StokKart.Treeview",
            selectmode="browse",
        )
        for kolon, baslik, w, ank in (
            ("birim", "Birim", 120, "w"),
            ("carpan", "Ana Birim Karşılığı", 140, "e"),
            ("alis", "Varsayılan Alış", 110, "center"),
            ("satis", "Varsayılan Satış", 110, "center"),
            ("aktif", "Aktiflik", 70, "center"),
        ):
            self.birim_tablo.heading(kolon, text=baslik, anchor=ank)
            self.birim_tablo.column(kolon, width=w, anchor=ank)
        bu_scroll = ttk.Scrollbar(birim_tablo_cer, orient="vertical", command=self.birim_tablo.yview)
        self.birim_tablo.configure(yscrollcommand=bu_scroll.set)
        self.birim_tablo.pack(side="left", fill="both", expand=True)
        bu_scroll.pack(side="right", fill="y")
        self.birim_tablo.bind("<Double-1>", lambda _e: self.birimler_ac())
        self.birim_bos_lbl = tk.Label(
            birim_cerceve,
            text="",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        )
        self.birim_bos_lbl.pack(anchor="w", pady=(4, 0))
        self._barkod_birim_tablolari_yenile()

        # --- Fiyat & Maliyet ---
        alis_cerceve = ttk.LabelFrame(
            tab_fiyat, text="Alış Fiyatları", padding=10, style="StokKart.TLabelframe"
        )
        alis_cerceve.pack(fill="x", padx=10, pady=(10, 0))
        self.fiyat_alanlari = {}

        ttk.Label(alis_cerceve, text="Liste Fiyatı", style="StokKartPanel.TLabel").grid(
            row=0, column=0, padx=6, pady=4, sticky="w"
        )
        self.fiyat_alanlari["LİSTE FİYATI"] = ttk.Entry(alis_cerceve, width=16)
        self.fiyat_alanlari["LİSTE FİYATI"].grid(row=0, column=1, padx=6, pady=4, sticky="w")
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<FocusOut>", self._fabrika_fiyati_guncelle)

        self.iskonto_alanlari = {}
        for kolon, (etiket, anahtar) in enumerate(
            (("1. İskonto %", "iskonto_1"), ("2. İskonto %", "iskonto_2"), ("3. İskonto %", "iskonto_3"))
        ):
            ttk.Label(alis_cerceve, text=etiket, style="StokKartPanel.TLabel").grid(
                row=1, column=kolon * 2, padx=6, pady=4, sticky="w"
            )
            giris = ttk.Entry(alis_cerceve, width=10)
            giris.grid(row=1, column=kolon * 2 + 1, padx=6, pady=4, sticky="w")
            giris.bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
            giris.bind("<FocusOut>", self._fabrika_fiyati_guncelle)
            self.iskonto_alanlari[anahtar] = giris

        ttk.Label(alis_cerceve, text="Fabrika Fiyatı", style="StokKartPanel.TLabel").grid(
            row=2, column=0, padx=6, pady=4, sticky="w"
        )
        self.fiyat_alanlari["FABRİKA FİYATI"] = ttk.Entry(alis_cerceve, width=16, state="readonly")
        self.fiyat_alanlari["FABRİKA FİYATI"].grid(row=2, column=1, padx=6, pady=4, sticky="w")
        ttk.Label(
            alis_cerceve,
            text="Fabrika = Liste − 1./2./3. iskonto (ardışık)",
            style="StokKartPanelMuted.TLabel",
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
            tk.Label(
                alis_cerceve,
                text=etiket,
                bg=BEYAZ,
                fg=_ALIS_ETIKET_FG,
                font=sktema.font(10, "bold", root=self),
            ).grid(row=satir, column=sutun, padx=6, pady=4, sticky="w")
            if fiyat_adi == "ALIŞ FİYATI":
                giris = ttk.Entry(alis_cerceve, width=16, state="readonly")
            else:
                giris = ttk.Entry(alis_cerceve, width=16)
            giris.grid(row=satir, column=sutun + 1, padx=6, pady=4, sticky="w")
            self.fiyat_alanlari[fiyat_adi] = giris
        ttk.Label(
            alis_cerceve,
            text="Alış Fiyatı = son alış faturasındaki net iskontolu birim fiyat (otomatik)",
            style="StokKartPanelMuted.TLabel",
        ).grid(row=5, column=0, columnspan=4, padx=6, pady=(2, 4), sticky="w")

        satis_cerceve = ttk.LabelFrame(
            tab_fiyat, text="Satış Fiyatları (10 adet)", padding=10, style="StokKart.TLabelframe"
        )
        satis_cerceve.pack(fill="both", expand=True, padx=10, pady=10)
        for satir, fiyat_adi in enumerate(SATIS_FIYAT_ADLARI):
            kolon = 0 if satir < 5 else 2
            yerel = satir if satir < 5 else satir - 5
            tk.Label(
                satis_cerceve,
                text=fiyat_adi,
                bg=BEYAZ,
                fg=_SATIS_ETIKET_FG,
                font=sktema.font(10, "bold", root=self),
            ).grid(row=yerel, column=kolon, padx=6, pady=4, sticky="w")
            giris = ttk.Entry(satis_cerceve, width=18)
            giris.grid(row=yerel, column=kolon + 1, padx=6, pady=4, sticky="w")
            self.fiyat_alanlari[fiyat_adi] = giris
        fiyat_aksiyon = tk.Frame(tab_fiyat, bg=BEYAZ)
        fiyat_aksiyon.pack(fill="x", padx=10, pady=(0, 10))
        stok_tk_buton(fiyat_aksiyon, "Fiyat Analiz / Geçmiş", self.fiyat_analiz_ac, rol="ara").pack(
            side="left"
        )

        # --- Depo & Stok ---
        depo_bilgi = tk.Frame(tab_depo, bg=BEYAZ)
        depo_bilgi.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(
            depo_bilgi,
            text="Depo bazlı miktarlar lot/hareketlerden türetilir; bakiye elle değiştirilemez. Depo açma/silme bu sekmeden yapılır.",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        ).pack(anchor="w", pady=(0, 8))
        depo_aksiyon = tk.Frame(depo_bilgi, bg=BEYAZ)
        depo_aksiyon.pack(fill="x", pady=(0, 6))
        stok_tk_buton(depo_aksiyon, "Yeni Depo", self._yeni_depo_ac, rol="yeni").pack(side="left")
        stok_tk_buton(depo_aksiyon, "Depoyu Sil", self._depo_sil, rol="ikincil").pack(
            side="left", padx=(8, 0)
        )
        stok_tk_buton(depo_aksiyon, "Pasife Al", self._depo_pasife, rol="ikincil").pack(
            side="left", padx=(8, 0)
        )
        depo_tablo_cer = tk.Frame(depo_bilgi, bg=BEYAZ)
        depo_tablo_cer.pack(fill="both", expand=True)
        self.depo_tablo = ttk.Treeview(
            depo_tablo_cer,
            columns=("kod", "depo", "mevcut", "fifo", "raf", "durum"),
            show="headings",
            height=10,
            style="StokKart.Treeview",
            selectmode="browse",
        )
        for kolon, baslik, w, ank in (
            ("kod", "Kod", 80, "w"),
            ("depo", "Depo", 180, "w"),
            ("mevcut", "Mevcut / Kullanılabilir", 150, "e"),
            ("fifo", "FIFO Değer", 120, "e"),
            ("raf", "Raf / Lokasyon", 120, "w"),
            ("durum", "Durum", 90, "w"),
        ):
            self.depo_tablo.heading(kolon, text=baslik, anchor=ank)
            self.depo_tablo.column(kolon, width=w, anchor=ank)
        depo_scroll = ttk.Scrollbar(depo_tablo_cer, orient="vertical", command=self.depo_tablo.yview)
        self.depo_tablo.configure(yscrollcommand=depo_scroll.set)
        self.depo_tablo.pack(side="left", fill="both", expand=True)
        depo_scroll.pack(side="right", fill="y")
        self.depo_tablo.bind("<Button-3>", self._depo_sag_tik)
        self.depo_ozet_detay = tk.Label(
            depo_bilgi,
            text="",
            bg=BEYAZ,
            fg=LACIVERT,
            font=sktema.font(10, root=self),
            justify="left",
            anchor="nw",
        )
        self.depo_ozet_detay.pack(anchor="w", pady=(8, 0))
        self.depo_bos_lbl = tk.Label(
            depo_bilgi,
            text="",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        )
        self.depo_bos_lbl.pack(anchor="w", pady=(4, 0))

        # --- Hareketler ---
        self._tab_hareket = tab_hareket
        hrk = tk.Frame(tab_hareket, bg=BEYAZ)
        hrk.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(
            hrk,
            text="Giriş / Çıkış / Kalan ve satır bazlı FIFO kalan değeri. Belge satırına çift tıklayınca evrak açılır.",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        ).pack(anchor="w", pady=(0, 6))
        hrk_ust = tk.Frame(hrk, bg=BEYAZ)
        hrk_ust.pack(fill="x", pady=(0, 6))
        tk.Label(hrk_ust, text="Başlangıç", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_baslangic = ttk.Entry(hrk_ust, width=12)
        self.hrk_baslangic.pack(side="left", padx=(4, 8))
        self.hrk_baslangic.insert(0, tarih_goster(date.today().replace(month=1, day=1)))
        tk.Label(hrk_ust, text="Bitiş", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_bitis = ttk.Entry(hrk_ust, width=12)
        self.hrk_bitis.pack(side="left", padx=(4, 8))
        self.hrk_bitis.insert(0, tarih_goster(date.today()))
        tk.Label(hrk_ust, text="Depo", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_depo_var = tk.StringVar(value="(Tümü)")
        _depolar = ["(Tümü)"]
        try:
            _depolar += [d.ad for d in StokService.depolar(aktif_only=True)]
        except Exception:
            pass
        self.hrk_depo_cb = ttk.Combobox(
            hrk_ust, textvariable=self.hrk_depo_var, values=_depolar, width=14, state="readonly"
        )
        self.hrk_depo_cb.pack(side="left", padx=(4, 8))
        tk.Label(hrk_ust, text="Ara", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_arama = ttk.Entry(hrk_ust, width=12)
        self.hrk_arama.pack(side="left", padx=(4, 8))
        stok_tk_buton(hrk_ust, "Listele", self._hareketler_yukle, rol="ara").pack(side="left")
        stok_tk_buton(hrk_ust, "Tümü", self._hareketler_tumunu_goster, rol="ikincil").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(hrk_ust, "Excel", self._hareketler_excel, rol="ikincil").pack(
            side="left", padx=(6, 0)
        )
        stok_tk_buton(
            hrk_ust,
            "Fiyatlı Ekstre",
            self._fiyatli_ekstre_ac,
            rol="ikincil",
        ).pack(side="right")
        stok_tk_buton(hrk_ust, "Ayrı Pencerede Aç", self.stok_hareketleri_ac, rol="ikincil").pack(
            side="right", padx=(0, 6)
        )
        hrk_tablo_cer = tk.Frame(hrk, bg=BEYAZ)
        hrk_tablo_cer.pack(fill="both", expand=True)
        self._hrk_kolon_ayarlari = hareket_kolon_ayarlari_yukle()
        self._hrk_kolon_idler = tuple(self._hrk_kolon_ayarlari.keys())
        self.hareket_tablo = ttk.Treeview(
            hrk_tablo_cer,
            columns=self._hrk_kolon_idler,
            show="headings",
            style="StokKart.Treeview",
            selectmode="browse",
        )
        for kolon in self._hrk_kolon_idler:
            cfg = self._hrk_kolon_ayarlari[kolon]
            sayisal = kolon in _HAREKET_SAYISAL_KOLONLAR
            self.hareket_tablo.heading(kolon, text=cfg["baslik"], anchor="e" if sayisal else "w")
            gorunur = cfg.get("gorunur", True)
            self.hareket_tablo.column(
                kolon,
                width=cfg["genislik"] if gorunur else 0,
                minwidth=0 if not gorunur else 40,
                stretch=gorunur,
                anchor="e" if sayisal else "w",
            )
        hrk_scroll = ttk.Scrollbar(hrk_tablo_cer, orient="vertical", command=self.hareket_tablo.yview)
        self.hareket_tablo.configure(yscrollcommand=hrk_scroll.set)
        self.hareket_tablo.pack(side="left", fill="both", expand=True)
        hrk_scroll.pack(side="right", fill="y")
        self.hareket_tablo.tag_configure("giris", foreground=_HAREKET_GIRIS_FG)
        self.hareket_tablo.tag_configure("cikis", foreground=_HAREKET_CIKIS_FG)
        self.hareket_tablo.tag_configure("devri", foreground=LACIVERT)
        self.hareket_tablo.tag_configure("notr", foreground=_HAREKET_NOTR_FG)
        self.hareket_tablo.tag_configure("negatif", background="#FFCDD2", foreground="#B71C1C")
        self.hareket_tablo.tag_configure("zebra", background="#F7F9FC")
        self.hareket_tablo.bind("<Double-1>", self._hareket_evrak_ac)
        self.hareket_tablo.bind("<ButtonRelease-1>", self._hareket_kolon_genislik_kaydet)
        self.hareket_ozet_lbl = tk.Label(
            hrk, text="", bg=BEYAZ, fg=LACIVERT, font=sktema.font(9, root=self)
        )
        self.hareket_ozet_lbl.pack(anchor="w", pady=(6, 0))
        self.hareket_bos_lbl = tk.Label(
            hrk, text="", bg=BEYAZ, fg=sktema.IKINCIL, font=sktema.font(9, root=self)
        )
        self.hareket_bos_lbl.pack(anchor="w")
        self._hareketler_yuklendi = False
        self._hareket_sonuc = None
        self.sekmeler.bind("<<NotebookTabChanged>>", self._sekme_degisti)

        # --- Notlar ---
        nt = tk.Frame(tab_notlar, bg=BEYAZ)
        nt.pack(fill="both", expand=True, padx=12, pady=12)
        form_etiket(nt, "Stok açıklaması / iç not").pack(anchor="w")
        self.aciklama_alani = tk.Text(nt, wrap="word", height=14, font=sktema.font(10, root=self))
        self.aciklama_alani.pack(fill="both", expand=True, pady=(6, 8))
        self.aciklama_alani.insert("1.0", self.aciklama or "")
        stok_tk_buton(nt, "Açıklamayı Diyalogda Düzenle", self.aciklama_ac, rol="ikincil").pack(
            anchor="w"
        )
        self.not_bos_lbl = tk.Label(
            nt,
            text="" if (self.aciklama or "").strip() else "Bu stok için henüz not girilmemiş. Yukarıdaki alana yazabilirsiniz.",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        )
        self.not_bos_lbl.pack(anchor="w", pady=(6, 0))

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

        self._ozeti_yenile()
        self._depo_tablosu_yenile()
        self._ean_uyari_gosterildi = False
        self._stok_kodu_barkod_live_after = None
        self.alanlar["stok_kodu"].focus_set()
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<Escape>", lambda _e: self._kapat_istegi())
        self.bind("<F8>", lambda _e: self._hareketler_sekmesine_gec())
        self.bind("<F6>", lambda _e: self.barkodlar_ac())
        self.bind("<F10>", lambda _e: self.fiyat_analiz_ac())
        # Mevcut kart: 13 haneli stok kodu → barkod öner / sor
        if self.stok:
            self.after(80, self._mevcut_kart_stok_kodu_barkod_kontrol)
        elif self.baslangic.get("stok_kodu"):
            self.after(80, lambda: self._stok_kodu_barkod_senkron(live=True))

    def _stok_kodu_keyrelease(self, event=None):
        self._stok_kodu_ara(event)
        if self.stok:
            return
        if getattr(self, "_stok_kodu_barkod_live_after", None):
            try:
                self.after_cancel(self._stok_kodu_barkod_live_after)
            except Exception:
                pass
        self._stok_kodu_barkod_live_after = self.after(
            250, lambda: self._stok_kodu_barkod_senkron(live=True)
        )

    def _stok_kodu_barkod_sor(self, kod: str) -> str | None:
        """Dönüş: 'ekle' | 'atla' | None (vazgeç)."""
        win = tk.Toplevel(self)
        win.title("Stok kodu barkod")
        win.transient(self)
        win.grab_set()
        ttk.Label(
            win,
            text=(
                "Stok kodu geçerli 13 haneli barkod biçimindedir. "
                "Barkodlar listesine eklemek ister misiniz?\n\n"
                f"Kod: {kod}"
            ),
            wraplength=420,
            justify="left",
        ).pack(padx=14, pady=12)
        secim = {"v": None}

        def _sec(v):
            secim["v"] = v
            win.destroy()

        alt = ttk.Frame(win)
        alt.pack(fill="x", pady=8, padx=12)
        ttk.Button(alt, text="Barkod Olarak Ekle", command=lambda: _sec("ekle")).pack(
            fill="x", pady=2
        )
        ttk.Button(alt, text="Ekleme", command=lambda: _sec("atla")).pack(fill="x", pady=2)
        ttk.Button(alt, text="Vazgeç", command=lambda: _sec(None)).pack(fill="x", pady=2)
        self.wait_window(win)
        return secim["v"]

    def _mukerrer_barkod_dialog(self, dup: dict) -> None:
        kod = (dup or {}).get("stok_kodu") or "—"
        ad = (dup or {}).get("stok_adi") or "—"
        stok_id = (dup or {}).get("stok_id")
        msg = (
            f"Bu barkod başka bir stok kartında kayıtlı.\n\n"
            f"Stok kodu: {kod}\nÜrün adı: {ad}"
        )
        if stok_id and messagebox.askyesno(
            "Mükerrer barkod",
            msg + "\n\nMevcut stok kartını açmak ister misiniz?",
            parent=self,
        ):
            try:
                mevcut = StokService.stok_getir(int(stok_id))
                if mevcut is not None:
                    StokKartiDialog(self.master, stok=mevcut)
            except Exception as exc:
                messagebox.showerror("Stok", str(exc), parent=self)
        else:
            messagebox.showwarning("Mükerrer barkod", msg, parent=self)

    def _stok_kodu_barkod_senkron(self, *, live: bool = False, ask_if_needed: bool = False):
        """Stok kodundan otomatik barkod; yalnızca AUTO_MARKER satırlarını günceller."""
        from database.stok_kodu_barkod_service import sync_primary_barcode_from_stock_code

        kod = (self.alanlar["stok_kodu"].get() or "").strip()
        birim = (self.alanlar["birim"].get() or "").strip() or "Adet"
        exclude = int(self.stok.id) if self.stok else None
        ask_cb = self._stok_kodu_barkod_sor if ask_if_needed else None
        try:
            rapor = sync_primary_barcode_from_stock_code(
                self.barkodlar,
                kod,
                birim=birim,
                exclude_stock_id=exclude,
                ask_add=ask_if_needed,
                ask_callback=ask_cb,
                check_duplicate=True,
            )
        except Exception:
            return

        uyari = rapor.get("uyari_ean")
        if uyari and not getattr(self, "_ean_uyari_gosterildi", False):
            self._ean_uyari_gosterildi = True
            messagebox.showwarning("EAN-13", uyari, parent=self)

        if rapor.get("aksiyon") == "duplicate" and rapor.get("duplicate"):
            if live or ask_if_needed:
                self._mukerrer_barkod_dialog(rapor["duplicate"])
            return

        if rapor.get("aksiyon") in ("set", "update", "remove") or rapor.get("eklendi") or rapor.get(
            "guncellendi"
        ) or rapor.get("kaldirildi"):
            self.barkodlar = rapor.get("barkodlar") or []
            self._barkod_birim_tablolari_yenile()

    def _mevcut_kart_stok_kodu_barkod_kontrol(self):
        from database.stok_kodu_barkod_service import (
            is_13_digit_barcode,
            normalize_stock_code_as_text,
        )

        kod = normalize_stock_code_as_text(self.alanlar["stok_kodu"].get())
        if not is_13_digit_barcode(kod):
            return
        mevcut = {
            normalize_stock_code_as_text(b.get("barkod"))
            for b in (self.barkodlar or [])
            if normalize_stock_code_as_text(b.get("barkod"))
        }
        if kod in mevcut:
            # Yalnızca EAN uyarısı (geçersiz kontrol basamağı)
            self._stok_kodu_barkod_senkron(live=False, ask_if_needed=False)
            return
        birinci = (self.barkodlar or [None])[0] if self.barkodlar else None
        birinci_dolu = bool(
            birinci and normalize_stock_code_as_text(birinci.get("barkod"))
        )
        if not birinci_dolu:
            self._stok_kodu_barkod_senkron(live=False, ask_if_needed=False)
        else:
            self._stok_kodu_barkod_senkron(live=False, ask_if_needed=True)

    def _barkod_birim_tablolari_yenile(self):
        if hasattr(self, "barkod_tablo"):
            for item in self.barkod_tablo.get_children():
                self.barkod_tablo.delete(item)
            dolu = [b for b in (self.barkodlar or []) if (b.get("barkod") or "").strip()]
            for i, b in enumerate(dolu):
                carpan = "1"
                birim = (b.get("birim") or "").strip()
                ana = (self.alanlar.get("birim").get().strip() if self.alanlar.get("birim") else "") or "Adet"
                for kayit in self.birimler or []:
                    if _birim_adi(kayit).casefold() == birim.casefold():
                        carpan = _birim_carpan(kayit)
                        break
                if birim.casefold() == ana.casefold():
                    carpan = "1"
                self.barkod_tablo.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        "★" if i == 0 else "",
                        b.get("barkod") or "",
                        "EAN/İç" if (b.get("aciklama") or "").upper().find("EAN") >= 0 else "Barkod",
                        birim,
                        carpan,
                        b.get("fiyat") or "",
                        "Aktif",
                    ),
                )
            if hasattr(self, "barkod_bos_lbl"):
                if dolu:
                    self.barkod_bos_lbl.configure(text="")
                else:
                    self.barkod_bos_lbl.configure(
                        text="Bu stok için henüz barkod tanımlanmamış. «Yeni Barkod» veya «EAN-13 Oluştur» ile ekleyin."
                    )
        if hasattr(self, "birim_tablo"):
            for item in self.birim_tablo.get_children():
                self.birim_tablo.delete(item)
            for i, kayit in enumerate(self.birimler or []):
                ad = _birim_adi(kayit)
                if not ad:
                    continue
                if isinstance(kayit, dict):
                    alis = "✓" if kayit.get("alis_kullanilabilir", True) else ""
                    satis = "✓" if kayit.get("satis_kullanilabilir", True) else ""
                    aktif = "Aktif" if kayit.get("aktif", True) else "Pasif"
                    carpan = _birim_carpan(kayit)
                else:
                    alis = satis = ""
                    aktif = "Aktif"
                    carpan = _birim_carpan(kayit)
                self.birim_tablo.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(ad, carpan, alis, satis, aktif),
                )
            if hasattr(self, "birim_bos_lbl"):
                if self.birimler:
                    self.birim_bos_lbl.configure(text="")
                else:
                    self.birim_bos_lbl.configure(
                        text="Alternatif birim yok. «Barkod Birim Dönüştürücü» ile 1 koli = 100 adet gibi tanımlayın."
                    )
        # Eski özet etiket varsa sessizce güncelle
        if hasattr(self, "barkod_ozet_lbl"):
            try:
                self.barkod_ozet_lbl.configure(text="")
            except tk.TclError:
                pass

    def _barkod_birim_ozet_yenile(self):
        self._barkod_birim_tablolari_yenile()

    def _barkod_satir_sil(self):
        secim = self.barkod_tablo.selection() if hasattr(self, "barkod_tablo") else ()
        if not secim:
            messagebox.showinfo("Barkod", "Silmek için tablodan bir barkod satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        dolu = [b for b in (self.barkodlar or []) if (b.get("barkod") or "").strip()]
        if idx == 0 and dolu:
            messagebox.showwarning(
                "Barkod",
                "1. (birincil) barkod silinemez. Önce başka barkodu birincil yapın veya Barkod Bilgileri'nden düzenleyin.",
                parent=self,
            )
            return
        if idx < 0 or idx >= len(dolu):
            return
        if not messagebox.askyesno("Barkod sil", f"'{dolu[idx].get('barkod')}' silinsin mi?", parent=self):
            return
        hedef = dolu[idx].get("barkod")
        self.barkodlar = [b for b in self.barkodlar if (b.get("barkod") or "").strip() != hedef]
        self._barkod_birim_tablolari_yenile()

    def _barkod_birincil_yap(self):
        secim = self.barkod_tablo.selection() if hasattr(self, "barkod_tablo") else ()
        if not secim:
            messagebox.showinfo("Birincil barkod", "Birincil yapmak için bir satır seçin.", parent=self)
            return
        idx = int(secim[0])
        dolu = [b for b in (self.barkodlar or []) if (b.get("barkod") or "").strip()]
        if idx <= 0 or idx >= len(dolu):
            messagebox.showinfo("Birincil barkod", "Seçili satır zaten birincil veya geçersiz.", parent=self)
            return
        secilen = dolu[idx]
        diger = [b for i, b in enumerate(dolu) if i != idx]
        # Boş satırları koru
        boslar = [b for b in (self.barkodlar or []) if not (b.get("barkod") or "").strip()]
        self.barkodlar = [secilen, *diger, *boslar][:5]
        self._barkod_birim_tablolari_yenile()

    def _barkod_etiket_yazdir(self):
        try:
            from stok_barkod_ui import stok_barkod_basimi_goster

            stok_barkod_basimi_goster(self.master)
        except Exception as exc:
            messagebox.showinfo(
                "Etiket",
                f"Barkod etiket yazdırma ekranı açılamadı.\n{exc}",
                parent=self,
            )

    def _birim_satir_sil(self):
        secim = self.birim_tablo.selection() if hasattr(self, "birim_tablo") else ()
        if not secim:
            messagebox.showinfo("Birim", "Silmek için bir birim satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        if idx < 0 or idx >= len(self.birimler or []):
            return
        ad = _birim_adi(self.birimler[idx])
        if not messagebox.askyesno("Birim sil", f"'{ad}' dönüşümü silinsin mi?", parent=self):
            return
        self.birimler = [b for i, b in enumerate(self.birimler) if i != idx]
        self._barkod_birim_tablolari_yenile()

    def _depo_tablosu_yenile(self):
        if not hasattr(self, "depo_tablo"):
            return
        for item in self.depo_tablo.get_children():
            self.depo_tablo.delete(item)
        try:
            depolar = StokService.depolar(aktif_only=False)
        except Exception as exc:
            if hasattr(self, "depo_bos_lbl"):
                self.depo_bos_lbl.configure(text=f"Depo listesi yüklenemedi: {exc}")
            return
        ozet_map = {}
        if self.stok:
            try:
                for s in StokService.stok_depo_ozeti(self.stok.id):
                    ozet_map[(s.get("depo") or "").upper()] = s
            except Exception:
                ozet_map = {}
        secili = getattr(self, "_secili_depo_id", None)
        for d in depolar:
            oz = ozet_map.get((d.ad or "").upper()) or {}
            durum = []
            if getattr(d, "varsayilan", False):
                durum.append("Varsayılan")
            durum.append("Aktif" if d.aktif else "Pasif")
            iid = str(d.id)
            self.depo_tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    getattr(d, "kod", None) or "",
                    d.ad or "",
                    f"{oz.get('mevcut') or 0}",
                    para_goster(oz.get("fifo_deger") or 0),
                    oz.get("raf") or (getattr(self.stok, "raf_yeri", None) if self.stok else "") or "",
                    " / ".join(durum),
                ),
            )
        if secili and str(secili) in self.depo_tablo.get_children():
            self.depo_tablo.selection_set(str(secili))
            self.depo_tablo.see(str(secili))
        if hasattr(self, "depo_bos_lbl"):
            if depolar:
                self.depo_bos_lbl.configure(text="")
            else:
                self.depo_bos_lbl.configure(text="Henüz depo yok. «Yeni Depo» ile ekleyin.")

    def _yeni_depo_ac(self):
        from stok_depo_ui import YeniDepoDialog

        dialog = YeniDepoDialog(self)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._secili_depo_id = getattr(dialog.result, "id", None)
            self._depo_tablosu_yenile()

    def _secili_depo_id_al(self) -> int | None:
        if not hasattr(self, "depo_tablo"):
            return None
        sec = self.depo_tablo.selection()
        if not sec:
            return None
        try:
            return int(sec[0])
        except (TypeError, ValueError):
            return None

    def _depo_sil(self):
        depo_id = self._secili_depo_id_al()
        if not depo_id:
            messagebox.showinfo("Depo", "Silmek için bir depo seçin.", parent=self)
            return
        try:
            ozet = StokService.depo_kullanim_ozeti(depo_id)
        except Exception as exc:
            messagebox.showerror("Depo", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Depo Sil",
            f"«{ozet['kod']} / {ozet['ad']}» deposu silinsin mi?",
            parent=self,
        ):
            return
        try:
            StokService.depo_sil(depo_id)
            self._secili_depo_id = None
            self._depo_tablosu_yenile()
        except ValueError as exc:
            if "pasife" in str(exc).lower() or "silinemez" in str(exc).lower():
                if messagebox.askyesno(
                    "Depo Silinemedi",
                    f"{exc}\n\nDepoyu pasife almak ister misiniz?",
                    parent=self,
                ):
                    try:
                        StokService.depo_pasife_al(depo_id)
                        self._depo_tablosu_yenile()
                    except Exception as e2:
                        messagebox.showerror("Depo", str(e2), parent=self)
            else:
                messagebox.showerror("Depo", str(exc), parent=self)

    def _depo_pasife(self):
        depo_id = self._secili_depo_id_al()
        if not depo_id:
            messagebox.showinfo("Depo", "Pasife almak için depo seçin.", parent=self)
            return
        try:
            ozet = StokService.depo_kullanim_ozeti(depo_id)
            if not messagebox.askyesno(
                "Pasife Al",
                f"«{ozet['kod']} / {ozet['ad']}» pasife alınsın mı?",
                parent=self,
            ):
                return
            StokService.depo_pasife_al(depo_id)
            self._depo_tablosu_yenile()
        except Exception as exc:
            messagebox.showerror("Depo", str(exc), parent=self)

    def _depo_sag_tik(self, event):
        iid = self.depo_tablo.identify_row(event.y)
        if iid:
            self.depo_tablo.selection_set(iid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Yeni Depo", command=self._yeni_depo_ac)
        menu.add_command(label="Depoyu Sil", command=self._depo_sil)
        menu.add_command(label="Pasife Al", command=self._depo_pasife)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _sekme_degisti(self, _event=None):
        try:
            secili = self.sekmeler.index(self.sekmeler.select())
        except tk.TclError:
            return
        # 0 Genel, 1 Barkod, 2 Fiyat, 3 Depo, 4 Hareketler, 5 Notlar
        if secili == 1:
            self._barkod_birim_tablolari_yenile()
        elif secili == 3:
            self._depo_tablosu_yenile()
            self._ozeti_yenile()
        elif secili == 4 and not self._hareketler_yuklendi:
            self._hareketler_yukle()

    def _hareketler_sekmesine_gec(self):
        try:
            self.sekmeler.select(4)
        except tk.TclError:
            pass
        self._hareketler_yukle()

    def _hareketler_tumunu_goster(self):
        if hasattr(self, "hrk_baslangic"):
            self.hrk_baslangic.delete(0, "end")
            self.hrk_bitis.delete(0, "end")
        self._hareketler_yukle()

    def _hareket_kolon_genislik_kaydet(self, _event=None):
        if not hasattr(self, "hareket_tablo"):
            return
        for kolon in getattr(self, "_hrk_kolon_idler", ()):
            try:
                self._hrk_kolon_ayarlari[kolon]["genislik"] = int(
                    self.hareket_tablo.column(kolon, "width")
                )
            except Exception:
                pass
        try:
            hareket_kolon_ayarlari_kaydet(self._hrk_kolon_ayarlari)
        except Exception:
            pass

    def _hareketler_excel(self):
        if not getattr(self, "_hareket_sonuc", None):
            messagebox.showinfo("Excel", "Önce hareketleri listeleyin.", parent=self)
            return
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService

        kod = getattr(self.stok, "stok_kodu", "stok") if self.stok else "stok"
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"stok_hareket_{kod}.xlsx",
        )
        if not yol:
            return
        try:
            FiyatliStokEkstreService.excel_aktar(self._hareket_sonuc, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)

    def _hareketler_yukle(self):
        if not hasattr(self, "hareket_tablo"):
            return
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService
        from ui_bg import arka_planda

        for item in self.hareket_tablo.get_children():
            self.hareket_tablo.delete(item)
        if not self.stok:
            self.hareket_bos_lbl.configure(
                text="Hareketleri görmek için önce stok kartını kaydedin."
            )
            self.hareket_ozet_lbl.configure(text="")
            self._hareket_sonuc = None
            return
        try:
            bas = None
            bit = None
            if self.hrk_baslangic.get().strip():
                bas = datetime.strptime(self.hrk_baslangic.get().strip(), "%d.%m.%Y").date()
            if self.hrk_bitis.get().strip():
                bit = datetime.strptime(self.hrk_bitis.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return
        depo = None
        if hasattr(self, "hrk_depo_var"):
            d = self.hrk_depo_var.get()
            if d and d not in ("(Tümü)",):
                depo = d
        arama = None
        if hasattr(self, "hrk_arama"):
            arama = self.hrk_arama.get().strip() or None
        tum = bas is None and bit is None
        stok_id = int(self.stok.id)
        self.hareket_bos_lbl.configure(text="Hareketler yükleniyor…")
        self.hareket_ozet_lbl.configure(text="")
        if getattr(self, "_hareket_yukle_token", None) is None:
            self._hareket_yukle_token = 0
        self._hareket_yukle_token += 1
        token = self._hareket_yukle_token

        def _is():
            return FiyatliStokEkstreService.hareket_ekstresi(
                stok_id,
                baslangic=bas,
                bitis=bit,
                depo_adi=depo,
                belge_arama=arama,
                tum_gecmis=tum,
            )

        def _ok(sonuc):
            if token != getattr(self, "_hareket_yukle_token", 0):
                return
            self._hareket_sonuc = sonuc
            self._hareketler_tabloyu_doldur()

        def _err(exc):
            if token != getattr(self, "_hareket_yukle_token", 0):
                return
            self.hareket_bos_lbl.configure(text=f"Hareketler yüklenemedi: {exc}")
            self._hareket_sonuc = None

        arka_planda(self, _is, on_ok=_ok, on_err=_err)

    def _hareketler_tabloyu_doldur(self):
        if not hasattr(self, "hareket_tablo") or not self._hareket_sonuc:
            return
        for item in self.hareket_tablo.get_children():
            self.hareket_tablo.delete(item)
        maliyet_ok = self._hareket_sonuc.get("maliyet_gorunur", True)
        satirlar = self._hareket_sonuc.get("satirlar") or []
        for sira, s in enumerate(satirlar):
            tarih = s.get("tarih")
            saat = s.get("saat") or ""
            tarih_metin = ""
            if tarih:
                tarih_metin = tarih_goster(tarih)
                if saat:
                    tarih_metin = f"{tarih_metin} {saat[:5]}"
            cari = " ".join(
                x for x in ((s.get("cari_kodu") or "").strip(), (s.get("cari_adi") or "").strip()) if x
            )
            yon = s.get("yon") or "notr"
            tags = [yon]
            if sira % 2 == 1:
                tags.append("zebra")
            kalan = s.get("kalan")
            try:
                if Decimal(str(kalan or 0)) < 0:
                    tags = ["negatif"]
            except Exception:
                pass
            fifo_txt = ""
            if maliyet_ok and s.get("kalan_deger") is not None:
                fifo_txt = para_goster(s.get("kalan_deger"))
            elif s.get("fifo_hesaplanamadi"):
                fifo_txt = "—"
            aciklama = s.get("aciklama") or s.get("uyari") or ""
            kaynak = (s.get("fiyat_kaynak") or "").strip()
            if kaynak and kaynak not in aciklama:
                aciklama = f"{aciklama} | {kaynak}".strip(" |") if aciklama else kaynak
            try:
                if Decimal(str(kalan or 0)) < 0 and "⚠" not in aciklama:
                    aciklama = f"⚠ Negatif stok | {aciklama}".strip(" |")
            except Exception:
                pass
            net_g = s.get("net_giris_birim_fiyat", s.get("giris_birim_fiyat"))
            net_c = s.get("net_cikis_birim_fiyat", s.get("cikis_satis_fiyat"))
            fiyat_yok = bool(s.get("fiyat_yok"))
            self.hareket_tablo.insert(
                "",
                "end",
                iid=f"{sira}:{s.get('belge_no')}:{s.get('hareket_turu')}",
                values=(
                    tarih_metin,
                    s.get("belge_turu") or s.get("hareket_turu") or "",
                    s.get("belge_no") or "",
                    cari,
                    s.get("depo") or "",
                    s.get("birim") or self._hareket_sonuc.get("ana_birim") or "",
                    miktar_goster_tr(s.get("giren"), bos_sifir=True),
                    _net_fiyat_goster(
                        net_g, fiyat_yok=fiyat_yok and yon == "giris" and net_g is None
                    ),
                    miktar_goster_tr(s.get("cikan"), bos_sifir=True),
                    _net_fiyat_goster(
                        net_c, fiyat_yok=fiyat_yok and yon == "cikis" and net_c is None
                    ),
                    miktar_goster_tr(kalan),
                    fifo_txt,
                    aciklama,
                ),
                tags=tuple(tags),
            )
        self._hareketler_yuklendi = True
        o = self._hareket_sonuc.get("ozet") or {}
        self.hareket_ozet_lbl.configure(
            text=(
                f"Kayıt: {len(satirlar)}  ·  "
                f"Toplam Giriş: {miktar_goster_tr(o.get('giren_miktar'))}  ·  "
                f"Toplam Çıkış: {miktar_goster_tr(o.get('cikan_miktar'))}  ·  "
                f"Son Kalan: {miktar_goster_tr(o.get('kalan_miktar'))}  ·  "
                f"Son FIFO: {para_goster(o.get('fifo_kalan_degeri') or o.get('kalan_stok_degeri'))}"
            )
        )
        if satirlar:
            self.hareket_bos_lbl.configure(text="")
        else:
            self.hareket_bos_lbl.configure(
                text="Bu dönem için hareket yok. Tarih aralığını genişletin veya «Tümü»ne basın."
            )
        uyarilar = self._hareket_sonuc.get("uyarilar") or []
        kritik = [u for u in uyarilar if "uyuşmuyor" in u.lower() or "negatif" in u.lower()]
        if kritik:
            messagebox.showwarning("FIFO / mutabakat", "\n".join(kritik[:8]), parent=self)
        self._ozeti_yenile()

    def _hareket_evrak_ac(self, _event=None):
        if not hasattr(self, "hareket_tablo"):
            return
        if getattr(self, "_evrak_aciliyor", False):
            return
        secim = self.hareket_tablo.selection()
        if not secim:
            return
        degerler = self.hareket_tablo.item(secim[0], "values")
        if not degerler or len(degerler) < 3:
            return
        belge_no = degerler[2]
        parts = str(secim[0]).split(":")
        hareket_turu = parts[2] if len(parts) >= 3 else degerler[1]
        if (hareket_turu or "").upper() in ("DEVRİ", "DEVRI", "DEVİR"):
            return
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
                    self, fatura=fatura, cari_ac=lambda cari: CariDialog(self, cari)
                )
                self.wait_window(dialog)
            elif tur == "alis_fatura":
                from alis_ui import AlisFaturasiDialog
                from app import CariDialog
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
            self._ozeti_yenile()
            self._hareketler_yuklendi = False

    def _pencere_ayar_dosyasi(self) -> Path:
        firma = str(oturum.company_id or oturum.firma_kodu or "0")
        kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"stok_karti_pencere_f{firma}_u{kullanici}.json"

    def _pencere_boyutunu_ayarla(self):
        """İlk açılışta büyütülmüş; sonraki açılışlarda kullanıcı boyutu."""
        yol = self._pencere_ayar_dosyasi()
        kayit = None
        if yol.exists():
            try:
                kayit = json.loads(yol.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                kayit = None
        if kayit and kayit.get("geometry"):
            try:
                self.geometry(str(kayit["geometry"]))
                if kayit.get("zoomed"):
                    self.state("zoomed")
            except tk.TclError:
                self.state("zoomed")
        else:
            try:
                self.state("zoomed")
            except tk.TclError:
                self.geometry("1280x860")
        self.bind("<Configure>", self._pencere_boyut_kaydet_debounce, add="+")
        self._pencere_kaydet_after = None

    def _pencere_boyut_kaydet_debounce(self, _event=None):
        if getattr(self, "_pencere_kaydet_after", None):
            try:
                self.after_cancel(self._pencere_kaydet_after)
            except Exception:
                pass
        self._pencere_kaydet_after = self.after(600, self._pencere_boyut_kaydet)

    def _pencere_boyut_kaydet(self):
        try:
            zoomed = False
            try:
                zoomed = bool(self.state() == "zoomed")
            except tk.TclError:
                zoomed = False
            veri = {"geometry": self.geometry(), "zoomed": zoomed}
            self._pencere_ayar_dosyasi().write_text(
                json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _ana_birim_secenekleri(self) -> list[str]:
        adlar = []
        for b in self.birimler or []:
            if isinstance(b, dict) and not b.get("aktif", True):
                continue
            ad = _birim_adi(b)
            if ad and ad not in adlar:
                adlar.append(ad)
        return adlar

    def _ana_birim_listesini_yenile(self):
        if "birim" not in getattr(self, "alanlar", {}):
            return
        widget = self.alanlar["birim"]
        degerler = self._ana_birim_secenekleri()
        mevcut = (widget.get() or "").strip()
        if mevcut and mevcut not in degerler:
            # Mevcut ana birim listede yoksa veri kaybı yapmadan listede tut + uyar
            degerler = [mevcut, *degerler]
            if not getattr(self, "_ana_birim_uyari_verildi", False):
                self._ana_birim_uyari_verildi = True
                messagebox.showwarning(
                    "Ana Birim",
                    f"Ana birim «{mevcut}» bu stoğun birim tanımlarında yok.\n"
                    "Barkod ve Birimler sekmesinden tanımlayın veya listeden geçerli bir birim seçin.",
                    parent=self,
                )
        widget.configure(values=degerler)

    def _grup_listelerini_yukle(self, *, ilk: bool = False):
        from database.stok_grup_service import SEVIYE_ANA, StokGrupService

        try:
            ana_liste = StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True)
        except Exception:
            ana_liste = []
        self._grup_id_map = {"ana": {}, "tali": {}, "alt": {}}
        ana_vals = []
        for g in ana_liste:
            et = g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}"
            ana_vals.append(et)
            self._grup_id_map["ana"][et] = g["id"]
        if hasattr(self, "grup_pasif_lbl"):
            self.grup_pasif_lbl.configure(text="")
        if self.stok and getattr(self.stok, "ana_grup_id", None):
            try:
                d = StokGrupService.getir(self.stok.ana_grup_id)
                if d and not d.get("aktif"):
                    et = (d.get("etiket") or f"{d.get('kod')} — {d.get('ad')}") + " (Pasif)"
                    if et not in self._grup_id_map["ana"]:
                        ana_vals.append(et)
                        self._grup_id_map["ana"][et] = d["id"]
                    if hasattr(self, "grup_pasif_lbl"):
                        self.grup_pasif_lbl.configure(
                            text="Kayıtlı grup(lar) pasif. Aktif bir gruba taşımanız önerilir."
                        )
            except Exception:
                pass
        self.grup_alanlari["ana"].configure(values=ana_vals)
        if ilk and self.stok and getattr(self.stok, "ana_grup_id", None):
            for et, gid in self._grup_id_map["ana"].items():
                if gid == self.stok.ana_grup_id:
                    self.grup_alanlari["ana"].set(et)
                    break
            self._grup_ana_degisti(temizle=False)
            if getattr(self.stok, "tali_grup_id", None):
                for et, gid in self._grup_id_map["tali"].items():
                    if gid == self.stok.tali_grup_id:
                        self.grup_alanlari["tali"].set(et)
                        break
                self._grup_tali_degisti(temizle=False)
                if getattr(self.stok, "alt_grup_id", None):
                    for et, gid in self._grup_id_map["alt"].items():
                        if gid == self.stok.alt_grup_id:
                            self.grup_alanlari["alt"].set(et)
                            break
        else:
            self.grup_alanlari["tali"].configure(values=[], state="disabled")
            self.grup_alanlari["alt"].configure(values=[], state="disabled")
            if ilk:
                self.grup_alanlari["tali"].set("")
                self.grup_alanlari["alt"].set("")

    def _grup_secili_id(self, anahtar: str) -> int | None:
        et = (self.grup_alanlari[anahtar].get() or "").strip()
        return self._grup_id_map.get(anahtar, {}).get(et)

    def _grup_ana_degisti(self, temizle: bool = True):
        from database.stok_grup_service import SEVIYE_TALI, StokGrupService

        ana_id = self._grup_secili_id("ana")
        if temizle:
            self.grup_alanlari["tali"].set("")
            self.grup_alanlari["alt"].set("")
        self._grup_id_map["tali"] = {}
        self._grup_id_map["alt"] = {}
        if not ana_id:
            self.grup_alanlari["tali"].configure(values=[], state="disabled")
            self.grup_alanlari["alt"].configure(values=[], state="disabled")
            return
        try:
            tali_liste = StokGrupService.listele(
                seviye=SEVIYE_TALI, parent_id=ana_id, aktif_only=True
            )
        except Exception:
            tali_liste = []
        vals = []
        for g in tali_liste:
            et = g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}"
            vals.append(et)
            self._grup_id_map["tali"][et] = g["id"]
        self.grup_alanlari["tali"].configure(values=vals, state="normal")
        self.grup_alanlari["alt"].configure(values=[], state="disabled")
        if temizle:
            self.grup_alanlari["alt"].set("")

    def _grup_tali_degisti(self, temizle: bool = True):
        from database.stok_grup_service import SEVIYE_ALT, StokGrupService

        tali_id = self._grup_secili_id("tali")
        if temizle:
            self.grup_alanlari["alt"].set("")
        self._grup_id_map["alt"] = {}
        if not tali_id:
            self.grup_alanlari["alt"].configure(values=[], state="disabled")
            return
        try:
            alt_liste = StokGrupService.listele(
                seviye=SEVIYE_ALT, parent_id=tali_id, aktif_only=True
            )
        except Exception:
            alt_liste = []
        vals = []
        for g in alt_liste:
            et = g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}"
            vals.append(et)
            self._grup_id_map["alt"][et] = g["id"]
        self.grup_alanlari["alt"].configure(values=vals, state="normal")

    def _grup_filtre_yaz(self, anahtar: str):
        pass

    def _yeni_grup_ekle(self):
        from database.stok_grup_service import SEVIYE_ALT, SEVIYE_ANA, SEVIYE_TALI
        from stok_grup_ui import StokGrupDialog

        ana_id = self._grup_secili_id("ana")
        tali_id = self._grup_secili_id("tali")
        if tali_id:
            seviye, parent_id = SEVIYE_ALT, tali_id
        elif ana_id:
            seviye, parent_id = SEVIYE_TALI, ana_id
        else:
            seviye, parent_id = SEVIYE_ANA, None
        dlg = StokGrupDialog(self, seviye=seviye, parent_id=parent_id)
        self.wait_window(dlg)
        if not dlg.result:
            return
        g = dlg.result
        sev = int(g.get("seviye") or 0)
        et = g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}"
        if sev == SEVIYE_ANA:
            self._grup_listelerini_yukle(ilk=False)
            self._grup_id_map["ana"][et] = g["id"]
            vals = list(self.grup_alanlari["ana"].cget("values") or [])
            if et not in vals:
                vals = list(vals) + [et]
            self.grup_alanlari["ana"].configure(values=vals)
            self.grup_alanlari["ana"].set(et)
            self._grup_ana_degisti()
        elif sev == SEVIYE_TALI:
            if g.get("parent_id"):
                for e2, gid in list(self._grup_id_map["ana"].items()):
                    if gid == g["parent_id"]:
                        self.grup_alanlari["ana"].set(e2)
                        break
                self._grup_ana_degisti(temizle=False)
            self._grup_id_map["tali"][et] = g["id"]
            vals = list(self.grup_alanlari["tali"].cget("values") or [])
            if et not in vals:
                vals = list(vals) + [et]
            self.grup_alanlari["tali"].configure(values=vals, state="normal")
            self.grup_alanlari["tali"].set(et)
            self._grup_tali_degisti()
        elif sev == SEVIYE_ALT:
            try:
                from database.stok_grup_service import StokGrupService

                tali = StokGrupService.getir(g["parent_id"]) if g.get("parent_id") else None
                if tali and tali.get("parent_id"):
                    for e2, gid in list(self._grup_id_map["ana"].items()):
                        if gid == tali["parent_id"]:
                            self.grup_alanlari["ana"].set(e2)
                            break
                    self._grup_ana_degisti(temizle=False)
                if tali:
                    for e2, gid in list(self._grup_id_map["tali"].items()):
                        if gid == tali["id"]:
                            self.grup_alanlari["tali"].set(e2)
                            break
                    self._grup_tali_degisti(temizle=False)
            except Exception:
                pass
            self._grup_id_map["alt"][et] = g["id"]
            vals = list(self.grup_alanlari["alt"].cget("values") or [])
            if et not in vals:
                vals = list(vals) + [et]
            self.grup_alanlari["alt"].configure(values=vals, state="normal")
            self.grup_alanlari["alt"].set(et)

    def _kapat_istegi(self):
        self._pencere_boyut_kaydet()
        # Notlar sekmesindeki metni belleğe al
        if hasattr(self, "aciklama_alani"):
            self.aciklama = self.aciklama_alani.get("1.0", "end").strip()
        cevap = messagebox.askyesnocancel(
            "Stok kartı",
            "Değişiklikler kaydedilsin mi?\n\nEvet = Kaydet  |  Hayır = Kaydetmeden çık  |  İptal",
            parent=self,
        )
        if cevap is None:
            return
        if cevap:
            self.kaydet()
            if self.result is not None:
                self.destroy()
            return
        self.destroy()

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
        if getattr(self, "_stok_kod_ara_after", None):
            try:
                self.after_cancel(self._stok_kod_ara_after)
            except Exception:
                pass
        self._stok_kod_ara_after = self.after(300, self._stok_kodu_ara_calistir)

    def _stok_kodu_ara_calistir(self):
        self._stok_kod_ara_after = None
        metin = self.alanlar["stok_kodu"].get().strip()
        if not metin:
            self.alanlar["stok_kodu"]["values"] = ()
            self._stok_kod_eslesme = {}
            return
        bulunan = StokService.stok_kodu_onerileri(metin)
        self._stok_kod_eslesme = {s.stok_kodu: s for s in bulunan}
        self.alanlar["stok_kodu"]["values"] = tuple(self._stok_kod_eslesme.keys())

    def _stok_adi_ara(self, _event=None):
        if getattr(self, "_stok_ad_ara_after", None):
            try:
                self.after_cancel(self._stok_ad_ara_after)
            except Exception:
                pass
        self._stok_ad_ara_after = self.after(300, self._stok_adi_ara_calistir)

    def _stok_adi_ara_calistir(self):
        self._stok_ad_ara_after = None
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
        def _fmt_miktar(v):
            return (
                f"{Decimal(str(v or 0)):,.4f}".rstrip("0").rstrip(".")
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

        ana_birim = (
            (self.alanlar.get("birim").get().strip() if self.alanlar.get("birim") else "")
            or (self.stok.birim if self.stok else "")
            or "Adet"
        )
        gosterim = (
            (getattr(self, "varsayilan_goruntuleme_birim", None) or "").strip()
            or ana_birim
        )

        def _birime_cevir(miktar):
            m = Decimal(str(miktar or 0))
            if gosterim.casefold() == ana_birim.casefold():
                return m
            try:
                o = StokService.birim_donusum_onizleme(
                    m, ana_birim, gosterim, getattr(self, "birimler", None) or [], ana_birim
                )
                return Decimal(str(o.get("hedef_miktar") or m))
            except Exception:
                return m

        if not self.stok:
            for etiket in self.ozet_etiketleri.values():
                etiket.configure(text="0")
            for alt in getattr(self, "ozet_alt_etiketleri", {}).values():
                alt.configure(text="")
            if hasattr(self, "depo_ozet_detay"):
                self.depo_ozet_detay.configure(
                    text="Kart kaydedildikten sonra envanter özeti burada görünür."
                )
            return
        ozet = StokService.stok_ozeti(self.stok.id)
        giris_m = _birime_cevir(ozet["toplam_giris"])
        cikis_m = _birime_cevir(ozet["toplam_cikis"])
        kalan_m = _birime_cevir(ozet["kalan"])
        # Doğrulama: kalan = giriş − çıkış (gösterim biriminde)
        if kalan_m != giris_m - cikis_m:
            kalan_m = giris_m - cikis_m
        giris = f"{_fmt_miktar(giris_m)} {gosterim}"
        cikis = f"{_fmt_miktar(cikis_m)} {gosterim}"
        kalan = f"{_fmt_miktar(kalan_m)} {gosterim}"
        fifo = para_goster(ozet["fifo_deger"])
        self.ozet_etiketleri["Toplam Giriş"].configure(text=giris)
        self.ozet_etiketleri["Toplam Çıkış"].configure(text=cikis)
        self.ozet_etiketleri["Kalan Miktar"].configure(text=kalan)
        self.ozet_etiketleri["FIFO Envanter Değeri"].configure(text=fifo)
        for baslik, alt_metin in (
            ("Toplam Giriş", "Hareket girişi"),
            ("Toplam Çıkış", "Hareket çıkışı"),
            ("Kalan Miktar", "Giriş − çıkış"),
            ("FIFO Envanter Değeri", "Lot maliyeti"),
        ):
            alt = getattr(self, "ozet_alt_etiketleri", {}).get(baslik)
            if alt is not None:
                alt.configure(text=alt_metin)
        if hasattr(self, "depo_ozet_detay"):
            self.depo_ozet_detay.configure(
                text=(
                    f"Kalan: {kalan}\n"
                    f"Toplam giriş: {giris}\n"
                    f"Toplam çıkış: {cikis}\n"
                    f"FIFO envanter değeri: {fifo}\n\n"
                    f"Raf yeri: {self.alanlar['raf_yeri'].get().strip() or '—'}"
                )
            )

    def aciklama_ac(self):
        if hasattr(self, "aciklama_alani"):
            self.aciklama = self.aciklama_alani.get("1.0", "end").strip()
        dialog = StokAciklamaDialog(self, self.aciklama)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.aciklama = dialog.result
            if hasattr(self, "aciklama_alani"):
                self.aciklama_alani.delete("1.0", "end")
                self.aciklama_alani.insert("1.0", self.aciklama or "")
            if hasattr(self, "not_bos_lbl"):
                self.not_bos_lbl.configure(
                    text=""
                    if (self.aciklama or "").strip()
                    else "Bu stok için henüz not girilmemiş. Yukarıdaki alana yazabilirsiniz."
                )

    def birimler_ac(self):
        ana_fiyatlar = {
            ad: giris.get().strip()
            for ad, giris in (getattr(self, "fiyat_alanlari", None) or {}).items()
            if giris.get().strip()
        }
        stok_id = self.stok.id if self.stok else None

        def _aninda_yenile(paket):
            if isinstance(paket, dict):
                self.birimler = paket.get("birimler") or []
                self.varsayilan_goruntuleme_birim = (
                    paket.get("varsayilan_goruntuleme_birim") or self.alanlar["birim"].get()
                )
                self.varsayilan_alis_birim = (
                    paket.get("varsayilan_alis_birim") or self.alanlar["birim"].get()
                )
                self.varsayilan_satis_birim = (
                    paket.get("varsayilan_satis_birim") or self.alanlar["birim"].get()
                )
            else:
                self.birimler = paket or []
            self._barkod_birim_ozet_yenile()
            self._ana_birim_listesini_yenile()
            self._ozeti_yenile()

        dialog = StokBirimlerDialog(
            self,
            self.alanlar["birim"].get(),
            self.birimler,
            ana_fiyatlar=ana_fiyatlar,
            stok_id=stok_id,
            on_saved=_aninda_yenile,
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            _aninda_yenile(dialog.result)

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
            self._barkod_birim_ozet_yenile()

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
        self._barkod_birim_ozet_yenile()

    def fiyat_analiz_ac(self):
        stok_id = self.stok.id if self.stok else None
        dialog = StokFiyatAnalizDialog(self, stok_id)
        self.wait_window(dialog)

    def _fiyatli_ekstre_ac(self):
        if not self.stok:
            messagebox.showinfo(
                "Fiyatlı Ekstre",
                "Fiyatlı ekstreyi açmak için önce stok kartını kaydedin.",
                parent=self,
            )
            return
        from fiyatli_stok_ekstresi_ui import FiyatliStokEkstreDialog

        dialog = FiyatliStokEkstreDialog(self, stok_id=self.stok.id if self.stok else None)
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
        if hasattr(self, "aciklama_alani"):
            self.aciklama = self.aciklama_alani.get("1.0", "end").strip()
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
            "kdv_orani": self.alanlar["kdv_orani"].get().strip() or str(int(VARSAYILAN_KDV_ORANI)),
            "rapor_grubu": "",
            "ana_grup_id": self._grup_secili_id("ana") if hasattr(self, "grup_alanlari") else None,
            "tali_grup_id": self._grup_secili_id("tali") if hasattr(self, "grup_alanlari") else None,
            "alt_grup_id": self._grup_secili_id("alt") if hasattr(self, "grup_alanlari") else None,
            "marka": self.alanlar["marka"].get().strip(),
            "model": self.alanlar["model"].get().strip(),
            "renk": self.alanlar["renk"].get().strip(),
            "agirlik": self.alanlar["agirlik"].get().strip(),
            "raf_yeri": self.alanlar["raf_yeri"].get().strip(),
            "minimum_stok": self.alanlar["minimum_stok"].get().strip() or "0",
            "aciklama": self.aciklama,
            "stok_id": self.stok.id if self.stok else None,
            "iskonto_1": self.iskonto_alanlari["iskonto_1"].get().strip() or "0",
            "iskonto_2": self.iskonto_alanlari["iskonto_2"].get().strip() or "0",
            "iskonto_3": self.iskonto_alanlari["iskonto_3"].get().strip() or "0",
            "varsayilan_goruntuleme_birim": getattr(self, "varsayilan_goruntuleme_birim", None)
            or self.alanlar["birim"].get().strip(),
            "varsayilan_alis_birim": getattr(self, "varsayilan_alis_birim", None)
            or self.alanlar["birim"].get().strip(),
            "varsayilan_satis_birim": getattr(self, "varsayilan_satis_birim", None)
            or self.alanlar["birim"].get().strip(),
        }
        veriler.update({k: (v or "") for k, v in self.muhasebe.items()})
        if not veriler["stok_kodu"] or not veriler["stok_adi"]:
            messagebox.showwarning("Eksik bilgi", "Stok kodu ve stok adı zorunludur.", parent=self)
            return
        # Grup hiyerarşisi doğrula + pasif uyarısı
        if hasattr(self, "grup_alanlari"):
            try:
                from database.stok_grup_service import StokGrupService

                dog = StokGrupService.hiyerarsi_dogrula(
                    veriler.get("ana_grup_id"),
                    veriler.get("tali_grup_id"),
                    veriler.get("alt_grup_id"),
                )
                veriler["rapor_grubu"] = dog.get("rapor_grubu") or ""
                if dog.get("pasif_uyari"):
                    if not messagebox.askyesno(
                        "Pasif grup",
                        "Seçili grup(lar) pasif: "
                        + ", ".join(dog["pasif_uyari"])
                        + "\nYine de kaydedilsin mi?",
                        parent=self,
                    ):
                        return
            except ValueError as exc:
                messagebox.showwarning("Stok grubu", str(exc), parent=self)
                return
        aktif_birimler = self._ana_birim_secenekleri()
        if not aktif_birimler:
            messagebox.showwarning(
                "Birim",
                "Bu stok için en az bir birim tanımlayın (Barkod ve Birimler).",
                parent=self,
            )
            return
        if veriler["birim"] not in aktif_birimler:
            messagebox.showwarning(
                "Ana Birim",
                f"Ana birim «{veriler['birim']}» tanımlı aktif birimler arasında değil.\n"
                f"Geçerli birimler: {', '.join(aktif_birimler)}",
                parent=self,
            )
            return
        if getattr(self, "rapor_grubu_zorunlu", False) and not (
            veriler.get("ana_grup_id") or veriler.get("rapor_grubu")
        ):
            messagebox.showwarning(
                "Stok grubu",
                "Ürünü kaydetmek için bir stok grubu (Ana Grup) seçmelisiniz.",
                parent=self,
            )
            try:
                self.grup_alanlari["ana"].focus_set()
            except Exception:
                pass
            return
        # Satış fiyatı yoksa uyar (engelleme yok)
        try:
            sf1 = None
            for ad, giris in self.fiyat_alanlari.items():
                if (ad or "").strip().upper() == "SATIŞ FİYATI 1":
                    sf1 = (giris.get() or "").strip()
                    break
            if not sf1 or float(sf1.replace(",", ".")) <= 0:
                if not messagebox.askyesno(
                    "Satış fiyatı",
                    "Satış fiyatı tanımlı değil veya 0. Yine de kaydedilsin mi?",
                    parent=self,
                ):
                    return
        except Exception:
            pass
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
            from database.stok_kodu_barkod_service import sync_for_save

            birim = veriler["birim"] or "Adet"
            exclude = int(self.stok.id) if self.stok else None
            self.barkodlar, _rapor = sync_for_save(
                self.barkodlar,
                veriler["stok_kodu"],
                birim=birim,
                exclude_stock_id=exclude,
            )
            self._barkod_birim_tablolari_yenile()
        except ValueError as hata:
            messagebox.showerror("Barkod", str(hata), parent=self)
            return
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
        self._depo_tablosu_yenile()
        self._hareketler_yuklendi = False
        self._barkod_birim_tablolari_yenile()
        messagebox.showinfo("Kaydedildi", "Stok kartı kaydedildi.", parent=self)
