"""Stok kartı diyalogları (Pazartesi stok modülünün geri kurulumu)."""
from __future__ import annotations

import json
import os
import re
import tkinter as tk
from datetime import date, datetime, timedelta
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
    BirimZatenVar,
    StokService,
    aktif_satis_fiyat_kodlari,
    birim_anahtari,
    fabrika_fiyati_hesapla,
    satis_fiyat_gorunen_ad,
)
from database.models.stok import KDV_ORANLARI, VARSAYILAN_KDV_ORANI
from database.session_manager import oturum

import stok_kart_tema as sktema
from stok_kart_tema import (
    ACIK_BG,
    BEYAZ,
    ETIKET_PADX,
    LACIVERT,
    SATIR_PADY,
    baslik_seridi,
    form_etiket,
    stil_uygula as stok_stil_uygula,
    tk_buton as stok_tk_buton,
)

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top", "Küçük Torba")

# Stok kartı açılış: tür/grup/depo/birim/satış listeleri (kartlar arası; yönetim sonrası temizlenir)
_STOK_KART_LISTE_CACHE: dict = {
    "tur": None,
    "grup_ana": None,
    "depolar": None,
    "birimler": None,
    "satis_kodlari": None,
}


def _stok_kart_liste_cache_temizle() -> None:
    _STOK_KART_LISTE_CACHE["tur"] = None
    _STOK_KART_LISTE_CACHE["grup_ana"] = None
    _STOK_KART_LISTE_CACHE["depolar"] = None
    _STOK_KART_LISTE_CACHE["birimler"] = None
    _STOK_KART_LISTE_CACHE["satis_kodlari"] = None


def geometriyi_alana_sigdir(
    geometri: str, alan: tuple[int, int, int, int], *, baslik_payi: int = 40, kenar_payi: int = 16
) -> str:
    """'GxY+X+Y' kaydını görev çubuğu dışı alana sığdırır; başlık/kenar çerçevesi geometriye dahil değildir."""
    eslesme = re.fullmatch(r"(\d+)x(\d+)\+?(-?\d+)\+?(-?\d+)", (geometri or "").strip())
    if not eslesme:
        return geometri
    ax, ay, aw, ah = alan
    w = min(int(eslesme.group(1)), max(200, aw - kenar_payi))
    h = min(int(eslesme.group(2)), max(200, ah - baslik_payi))
    x = min(max(int(eslesme.group(3)), ax), ax + aw - w - kenar_payi // 2)
    y = min(max(int(eslesme.group(4)), ay), ay + ah - h - baslik_payi)
    return f"{w}x{h}+{max(x, ax)}+{max(y, ay)}"

_ALIS_ETIKET_FG = "#C62828"
_SATIS_ETIKET_FG = "#2E7D32"
_HAREKET_GIRIS_FG = "#B71C1C"
_HAREKET_CIKIS_FG = "#1B5E20"
_HAREKET_NOTR_FG = "#627D98"


def _stok_secim_etiketi(stok) -> str:
    return f"{stok.stok_kodu} — {stok.stok_adi}"


def _ana_birim_kaydi(ad: str) -> dict:
    return {
        "birim_adi": ad,
        "carpan": "1",
        "aktif": True,
        "alis_kullanilabilir": True,
        "satis_kullanilabilir": True,
    }


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
    "cari": {"baslik": "Cari Kart", "genislik": 220, "gorunur": True},
    "depo": {"baslik": "Depo", "genislik": 90, "gorunur": True},
    "birim": {"baslik": "Birim", "genislik": 60, "gorunur": True},
    "giris": {"baslik": "Giriş Miktarı", "genislik": 95, "gorunur": True},
    "net_giris_fiyat": {"baslik": "Net Giriş Birim Fiyatı", "genislik": 130, "gorunur": True},
    "giris_tutari": {"baslik": "Giriş Tutarı", "genislik": 100, "gorunur": True},
    "cikis": {"baslik": "Çıkış Miktarı", "genislik": 95, "gorunur": True},
    "net_cikis_fiyat": {"baslik": "Net Çıkış Birim Fiyatı", "genislik": 130, "gorunur": True},
    "cikis_tutari": {"baslik": "Çıkış Tutarı", "genislik": 100, "gorunur": True},
    "kalan": {"baslik": "Kalan Miktar", "genislik": 95, "gorunur": True},
    "fifo": {"baslik": "FIFO Kalan Değeri", "genislik": 120, "gorunur": True},
    "aciklama": {"baslik": "Lot ve Açıklama", "genislik": 160, "gorunur": True},
    "fifo_cikis_maliyeti": {"baslik": "FIFO Çıkış Maliyeti", "genislik": 120, "gorunur": True},
    "kar_zarar": {"baslik": "Kâr/Zarar Tutarı", "genislik": 110, "gorunur": True},
    "kar_marj": {"baslik": "Kâr Marjı % (Satış)", "genislik": 110, "gorunur": True},
}

_HAREKET_SAYISAL_KOLONLAR = {
    "giris",
    "net_giris_fiyat",
    "giris_tutari",
    "cikis",
    "net_cikis_fiyat",
    "cikis_tutari",
    "kalan",
    "fifo",
    "fifo_cikis_maliyeti",
    "kar_zarar",
    "kar_marj",
}


def _hareket_kar_marj(cikis_tutari, cikis_maliyeti):
    """(kâr tutarı metni, marj % metni, kâr Decimal|None). Satış üzerinden marj."""
    if cikis_tutari is None or cikis_maliyeti is None:
        return "—", "—", None
    try:
        satis = Decimal(str(cikis_tutari))
        maliyet = Decimal(str(cikis_maliyeti))
    except Exception:
        return "—", "—", None
    kar = satis - maliyet
    if satis == 0:
        return para_goster(kar), "—", kar
    marj = (kar / satis) * Decimal("100")
    return para_goster(kar), f"{marj:.1f}", kar


def _hareket_satir_degerleri(s: dict, *, ana_birim: str = "", maliyet_ok: bool = True) -> tuple:
    """Kolon sırasına uygun Treeview values (Doc8 FIFO lot kolonları)."""
    tarih = s.get("tarih") or s.get("tarih_saat")
    saat = s.get("saat") or ""
    tarih_metin = ""
    if tarih:
        tarih_metin = tarih_goster(tarih) if hasattr(tarih, "strftime") else str(tarih)
        if saat:
            tarih_metin = f"{tarih_metin} {str(saat)[:5]}"
        elif hasattr(tarih, "hour"):
            tarih_metin = tarih.strftime("%d.%m.%Y %H:%M")
    cari_kod = (s.get("cari_kodu") or "").strip()
    cari_ad = (
        s.get("cari_adi") or s.get("cari_unvan") or s.get("cari") or ""
    ).strip()
    # Sahte etiketleri (eski veri) cari adı sayma
    if cari_ad.casefold() in {
        "manuel stok fişi", "depo transferi", "sayım düzeltmesi", "paket üretimi",
    }:
        cari_ad = ""
    if cari_kod and cari_ad:
        cari = f"{cari_kod} — {cari_ad}"
    elif cari_ad:
        cari = cari_ad
    elif cari_kod:
        cari = cari_kod
    else:
        cari = "—"
    yon = (s.get("yon") or "").lower()
    net_g = s.get("net_giris_birim_fiyat", s.get("giris_birim_fiyat"))
    net_c = s.get("net_cikis_birim_fiyat", s.get("cikis_satis_fiyat"))
    fiyat_yok = bool(s.get("fiyat_yok"))
    fifo_txt = ""
    if maliyet_ok and s.get("kalan_deger") is not None:
        fifo_txt = para_goster(s.get("kalan_deger"))
    elif s.get("fifo_hesaplanamadi"):
        fifo_txt = "—"
    aciklama = s.get("aciklama") or s.get("uyari") or ""
    lot = (s.get("lot") or s.get("lot_no") or "").strip()
    if lot and lot not in aciklama:
        aciklama = f"{lot} | {aciklama}".strip(" |") if aciklama else lot
    kaynak = (s.get("fiyat_kaynak") or "").strip()
    if kaynak and kaynak not in aciklama:
        aciklama = f"{aciklama} | {kaynak}".strip(" |") if aciklama else kaynak
    try:
        if Decimal(str(s.get("kalan") or 0)) < 0 and "⚠" not in aciklama:
            aciklama = f"⚠ Negatif stok | {aciklama}".strip(" |")
    except Exception:
        pass
    giris_t = s.get("giris_tutari")
    cikis_t = s.get("cikis_tutari")
    cikis_mal = s.get("cikis_maliyeti")
    cikan = s.get("cikan")
    kar_txt, marj_txt, _kar = _hareket_kar_marj(
        cikis_t, cikis_mal if maliyet_ok else None
    )
    return (
        tarih_metin,
        s.get("belge_turu") or s.get("hareket_turu") or "",
        s.get("belge_no") or "",
        cari,
        s.get("depo") or "",
        s.get("birim") or ana_birim or "",
        miktar_goster_tr(s.get("giren"), bos_sifir=True),
        _net_fiyat_goster(net_g, fiyat_yok=fiyat_yok and yon == "giris" and net_g is None),
        para_goster(giris_t) if giris_t is not None and maliyet_ok else ("—" if s.get("giren") else ""),
        miktar_goster_tr(cikan, bos_sifir=True),
        _net_fiyat_goster(net_c, fiyat_yok=fiyat_yok and yon == "cikis" and net_c is None),
        para_goster(cikis_t) if cikis_t is not None else ("—" if cikan else ""),
        miktar_goster_tr(s.get("kalan")),
        fifo_txt,
        aciklama,
        para_goster(cikis_mal) if cikis_mal is not None and maliyet_ok else ("—" if cikan else ""),
        kar_txt if cikan else "",
        marj_txt if cikan else "",
    )


FIYAT_KDV_SECENEKLERI = ("KDV belirtilmemiş", "KDV Hariç", "KDV Dahil")
_FIYAT_KDV_KOD = {"KDV Hariç": "HARIC", "KDV Dahil": "DAHIL"}


def fiyat_kdv_kodu(metin) -> str | None:
    return _FIYAT_KDV_KOD.get((metin or "").strip())


def fiyat_kdv_metni(kod) -> str:
    kod = (kod or "").strip().upper()
    for metin, k in _FIYAT_KDV_KOD.items():
        if k == kod:
            return metin
    return FIYAT_KDV_SECENEKLERI[0]


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
    """Birim Dönüştürücü: zincir çevirim + birim bazlı manuel/otomatik fiyatlar."""

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
        self.title("Birim Dönüştürücü")
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
        try:
            oniz = StokService.birim_donusum_onizleme(m, kaynak, hedef, birimler, self.ana_birim)
        except ValueError as hata:
            self.test_sonuc.configure(text=str(hata))
            return
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


class HareketKolonAyarDialog(tk.Toplevel):
    """Hareket tablosu kolon görünürlüğü — kullanıcı bazında kalıcı."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.title("Kolon Ayarları")
        self.transient(parent)
        self.grab_set()
        self.geometry("420x520")
        self.minsize(360, 400)
        ttk.Label(
            self,
            text="Görünür kolonları seçin. Genişlikler tabloda sürüklenerek saklanır.",
        ).pack(anchor="w", padx=12, pady=(12, 6))
        self._ayar = hareket_kolon_ayarlari_yukle()
        kutu = ttk.Frame(self)
        kutu.pack(fill="both", expand=True, padx=12, pady=4)
        canvas = tk.Canvas(kutu, highlightthickness=0)
        scroll = ttk.Scrollbar(kutu, orient="vertical", command=canvas.yview)
        ic = ttk.Frame(canvas)
        ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ic, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._vars = {}
        for anahtar, cfg in self._ayar.items():
            var = tk.BooleanVar(value=bool(cfg.get("gorunur", True)))
            self._vars[anahtar] = var
            ttk.Checkbutton(ic, text=cfg["baslik"], variable=var).pack(anchor="w", pady=2)
        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=12)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")

    def _kaydet(self):
        for anahtar, var in self._vars.items():
            self._ayar[anahtar]["gorunur"] = bool(var.get())
        # Kalan gizliyse FIFO da gizlensin
        if not self._ayar.get("kalan", {}).get("gorunur", True):
            self._ayar["fifo"]["gorunur"] = False
            if "fifo" in self._vars:
                self._vars["fifo"].set(False)
        hareket_kolon_ayarlari_kaydet(self._ayar)
        self.result = True
        self.destroy()


class LotKarZararDialog(tk.Toplevel):
    """Seçili stok için lot bazlı gerçekleşen kâr/zarar (FIFO)."""

    def __init__(self, parent, stok):
        super().__init__(parent)
        self.title(f"Lot Kâr/Zarar — {stok.stok_kodu}")
        self.transient(parent)
        self.geometry("980x560")
        self.minsize(800, 420)
        ttk.Label(
            self,
            text=f"{stok.stok_kodu} — {stok.stok_adi}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))
        self.ozet = ttk.Label(self, text="Hesaplanıyor…")
        self.ozet.pack(anchor="w", padx=12)
        cerceve = ttk.Frame(self)
        cerceve.pack(fill="both", expand=True, padx=12, pady=8)
        kolonlar = ("fatura", "tarih", "cari", "lot", "miktar", "net", "maliyet", "kar", "marj")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
        for k, b, w in (
            ("fatura", "Fatura", 100),
            ("tarih", "Tarih", 90),
            ("cari", "Cari", 160),
            ("lot", "Lot", 100),
            ("miktar", "Miktar", 70),
            ("net", "Net Satış", 95),
            ("maliyet", "FIFO Maliyet", 100),
            ("kar", "Kâr/Zarar", 95),
            ("marj", "Marj %", 70),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="e" if k in ("miktar", "net", "maliyet", "kar", "marj") else "w")
        scroll = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=scroll.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        ttk.Button(self, text="Kapat", command=self.destroy).pack(anchor="e", padx=12, pady=10)
        try:
            from database.rapor_service import RaporService

            rapor = RaporService.stok_kar_zarar(stok=stok.stok_kodu, maliyet_yontemi="FIFO")
        except Exception as hata:
            self.ozet.configure(text=f"Rapor alınamadı: {hata}")
            return
        self.ozet.configure(
            text=(
                f"Satır: {len(rapor['satirlar'])} · Satış: {para_goster(rapor['toplam_satis'])} · "
                f"Maliyet: {para_goster(rapor['toplam_maliyet'])} · "
                f"Kâr: {para_goster(rapor['toplam_kar'])} · Marj: {rapor['toplam_marj']:.1f}%"
            )
        )
        for s in rapor["satirlar"]:
            self.tablo.insert(
                "",
                "end",
                values=(
                    s.get("fatura_no") or "",
                    tarih_goster(s["tarih"]) if s.get("tarih") else "",
                    f"{s.get('cari_kodu') or ''} - {s.get('cari_unvan') or ''}"[:40],
                    s.get("lot") or "",
                    miktar_goster_tr(s.get("miktar")),
                    para_goster(s.get("net_satis") or s.get("net")),
                    para_goster(s.get("toplam_maliyet") or s.get("maliyet")),
                    para_goster(s.get("kar")),
                    f"{float(s.get('marj') or 0):.1f}",
                ),
            )


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

        from liste_filtre_ui import tutar_aralik_ekle
        from ui_takvim import takvim_butonu

        ust = tk.Frame(self, bg=BEYAZ, padx=10, pady=8)
        ust.pack(fill="x")
        tk.Label(ust, text="Başlangıç", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        bas_c = tk.Frame(ust, bg=BEYAZ)
        bas_c.pack(side="left", padx=(4, 10))
        self.baslangic = ttk.Entry(bas_c, width=12)
        self.baslangic.pack(side="left")
        self.baslangic.insert(0, tarih_goster(date.today().replace(month=1, day=1)))
        takvim_butonu(bas_c, self.baslangic, on_select=self.yenile, text="▾", width=2)
        tk.Label(ust, text="Bitiş", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        bit_c = tk.Frame(ust, bg=BEYAZ)
        bit_c.pack(side="left", padx=(4, 10))
        self.bitis = ttk.Entry(bit_c, width=12)
        self.bitis.pack(side="left")
        self.bitis.insert(0, tarih_goster(date.today()))
        takvim_butonu(bit_c, self.bitis, on_select=self.yenile, text="▾", width=2)
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
        self.fifo_min, self.fifo_max = tutar_aralik_ekle(
            ust, etiket="FIFO:", on_change=self._listeyi_goster
        )
        stok_tk_buton(ust, "Listele", self.yenile, rol="ara").pack(side="left")
        stok_tk_buton(ust, "Tümü", self.tumunu_goster, rol="ikincil").pack(side="left", padx=6)
        stok_tk_buton(ust, "Filtreleri Temizle", self._filtreleri_temizle, rol="ikincil").pack(
            side="left", padx=4
        )
        stok_tk_buton(ust, "Excel", self._excel_aktar, rol="ikincil").pack(side="right")
        stok_tk_buton(ust, "PDF", self._pdf_aktar, rol="ikincil").pack(side="right", padx=(0, 6))

        cerceve = tk.Frame(self, bg=BEYAZ, padx=10)
        cerceve.pack(fill="both", expand=True)
        self._kolon_ayarlari = hareket_kolon_ayarlari_yukle()
        self._kolon_idler = tuple(self._kolon_ayarlari.keys())
        self._liste_filtre = {}
        self._liste_ham = []
        self._liste_siralama = None
        self._filtre_popup = None
        self._liste_basliklar = {
            k: self._kolon_ayarlari[k]["baslik"] for k in self._kolon_idler
        }
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
        self.tablo.bind("<Button-3>", self._baslik_sag_tik)
        self.tablo.bind("<Return>", self.evrak_ac)

        self.ozet = tk.Label(self, text="", bg=ACIK_BG, fg=LACIVERT, anchor="w", justify="left")
        self.ozet.pack(anchor="w", padx=12, pady=(6, 0), fill="x")
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=12, pady=10)
        stok_tk_buton(alt, "Evrakı Aç", self.evrak_ac, rol="ara").pack(side="left")
        self.filtre_ozet = tk.Label(alt, text="", bg=ACIK_BG, fg="#555555", anchor="w")
        self.filtre_ozet.pack(side="left", padx=12)
        stok_tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        self.yenile()

    def _kolonlari_uygula(self):
        from liste_filtre_ui import baslik_filtre_metni

        ayar = self._kolon_ayarlari
        filtre = getattr(self, "_liste_filtre", {}) or {}
        siralama = getattr(self, "_liste_siralama", None)
        for kolon in self._kolon_idler:
            cfg = ayar[kolon]
            baslik = cfg["baslik"]
            sayisal = kolon in _HAREKET_SAYISAL_KOLONLAR
            self.tablo.heading(
                kolon,
                text=baslik_filtre_metni(
                    baslik,
                    filtre_aktif=kolon in filtre,
                    siralama=siralama,
                    kolon=kolon,
                ),
                anchor="e" if sayisal else "w",
                command=lambda c=kolon: self._kolon_sirala(c),
            )
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

    def _filtreleri_temizle(self):
        self._liste_filtre = {}
        for w in (getattr(self, "fifo_min", None), getattr(self, "fifo_max", None)):
            if w is None:
                continue
            try:
                w.delete(0, "end")
            except tk.TclError:
                pass
        self._listeyi_goster()

    def yenile(self):
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService

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
        self._liste_ham = []
        ana_birim = self._sonuc.get("ana_birim") or ""
        for sira, s in enumerate(self._sonuc.get("satirlar") or []):
            yon = s.get("yon") or "notr"
            tags = [yon]
            kalan = s.get("kalan")
            try:
                if Decimal(str(kalan or 0)) < 0:
                    tags = ["negatif"]
            except Exception:
                pass
            fifo_val = None
            if maliyet_ok and s.get("kalan_deger") is not None:
                fifo_val = Decimal(str(s.get("kalan_deger") or 0))
            values = _hareket_satir_degerleri(s, ana_birim=ana_birim, maliyet_ok=maliyet_ok)
            self._liste_ham.append(
                {
                    "iid": f"{sira}:{s.get('belge_no')}:{s.get('hareket_turu')}",
                    "values": values,
                    "tags": tags,
                    "fifo": fifo_val,
                    "giren": Decimal(str(s.get("giren") or 0)),
                    "cikan": Decimal(str(s.get("cikan") or 0)),
                    "ham": s,
                }
            )
        self._listeyi_goster()

    def _filtreli_satirlar(self):
        from liste_filtre_ui import tutar_aralik_uygun, tutar_oku

        filtre = getattr(self, "_liste_filtre", {}) or {}
        kolonlar = self._kolon_idler
        tmin = tutar_oku(getattr(self, "fifo_min", None))
        tmax = tutar_oku(getattr(self, "fifo_max", None))
        sonuc = []
        for satir in getattr(self, "_liste_ham", []):
            values = satir["values"]
            uygun = True
            for i, kolon in enumerate(kolonlar):
                if kolon not in filtre:
                    continue
                deger = "" if i >= len(values) or values[i] is None else str(values[i])
                if deger not in filtre[kolon]:
                    uygun = False
                    break
            if not uygun:
                continue
            if tmin is not None or tmax is not None:
                if not tutar_aralik_uygun(satir.get("fifo") or 0, tmin, tmax):
                    continue
            sonuc.append(satir)
        siralama = getattr(self, "_liste_siralama", None)
        if siralama:
            kolon, reverse = siralama
            try:
                idx = kolonlar.index(kolon)
            except ValueError:
                return sonuc
            if kolon == "fifo":
                sonuc.sort(
                    key=lambda s: (s.get("fifo") is None, s.get("fifo") or Decimal("0")),
                    reverse=reverse,
                )
            else:
                sonuc.sort(
                    key=lambda s: (
                        s["values"][idx] is None,
                        str(s["values"][idx] or "").casefold(),
                    ),
                    reverse=reverse,
                )
        return sonuc

    def _listeyi_goster(self):
        from liste_filtre_ui import filtre_ozet_metni

        for item in self.tablo.get_children():
            self.tablo.delete(item)
        filtreli = self._filtreli_satirlar()
        for sira, satir in enumerate(filtreli):
            tags = list(satir.get("tags") or [])
            if sira % 2 == 1 and "negatif" not in tags and "zebra" not in tags:
                tags.append("zebra")
            self.tablo.insert(
                "",
                "end",
                iid=satir["iid"],
                values=satir["values"],
                tags=tuple(tags),
            )
        self._kolonlari_uygula()
        o = (self._sonuc or {}).get("ozet") or {}
        uyari_txt = ""
        if (self._sonuc or {}).get("uyarilar"):
            uyari_txt = f"  ·  Uyarı: {len(self._sonuc['uyarilar'])}"
        giren = sum((s.get("giren") or 0) for s in filtreli)
        cikan = sum((s.get("cikan") or 0) for s in filtreli)
        self.ozet.configure(
            text=(
                f"Kayıt: {len(filtreli)} / {len(getattr(self, '_liste_ham', []))}  ·  "
                f"Σ Giriş: {miktar_goster_tr(giren)}  ·  "
                f"Σ Çıkış: {miktar_goster_tr(cikan)}  ·  "
                f"Son Kalan: {miktar_goster_tr(o.get('kalan_miktar'))}  ·  "
                f"Son FIFO: {para_goster(o.get('fifo_kalan_degeri') or o.get('kalan_stok_degeri'))}"
                f"{uyari_txt}"
            )
        )
        aktif = len(getattr(self, "_liste_filtre", {}) or {})
        from liste_filtre_ui import tutar_oku as _to

        if _to(getattr(self, "fifo_min", None)) is not None or _to(
            getattr(self, "fifo_max", None)
        ) is not None:
            aktif += 1
        if hasattr(self, "filtre_ozet"):
            self.filtre_ozet.configure(
                text=filtre_ozet_metni(
                    gorunen=len(filtreli),
                    toplam=len(getattr(self, "_liste_ham", [])),
                    aktif_filtre=aktif,
                )
            )

    def _kolon_sirala(self, kolon):
        mevcut = getattr(self, "_liste_siralama", None)
        if mevcut and mevcut[0] == kolon:
            self._liste_siralama = (kolon, not mevcut[1])
        else:
            self._liste_siralama = (kolon, False)
        self._listeyi_goster()

    def _baslik_sag_tik(self, event):
        if self.tablo.identify_region(event.x, event.y) != "heading":
            return
        kolon_id = self.tablo.identify_column(event.x)
        try:
            idx = int(kolon_id.replace("#", "")) - 1
            kolon = self._kolon_idler[idx]
        except (ValueError, IndexError):
            return
        self._kolon_filtre_ac(kolon)
        return "break"

    def _kolon_filtre_ac(self, kolon):
        from liste_filtre_ui import TreeviewKolonFiltrePopup

        eski = getattr(self, "_filtre_popup", None)
        if eski is not None:
            try:
                if eski.winfo_exists():
                    eski.destroy()
            except tk.TclError:
                pass
        try:
            idx = self._kolon_idler.index(kolon)
        except ValueError:
            return
        diger = {
            k: v for k, v in (self._liste_filtre or {}).items() if k != kolon and v is not None
        }
        onceki = self._liste_filtre
        self._liste_filtre = diger
        adaylar = self._filtreli_satirlar()
        self._liste_filtre = onceki
        kaynak = adaylar or getattr(self, "_liste_ham", [])
        degerler = set()
        for s in kaynak:
            vals = s["values"]
            degerler.add("" if idx >= len(vals) or vals[idx] is None else str(vals[idx]))
        mevcut = self._liste_filtre.get(kolon)
        baslik = self._liste_basliklar.get(kolon, kolon)
        pop = TreeviewKolonFiltrePopup(
            self,
            baslik,
            degerler,
            secili=mevcut,
            uygula_cb=lambda secilen, c=kolon: self._kolon_filtre_uygula(c, secilen),
            temizle_cb=lambda c=kolon: self._kolon_filtre_temizle(c),
        )
        try:
            x = self.tablo.winfo_rootx() + 40
            y = self.tablo.winfo_rooty() + 28
            pop.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        self._filtre_popup = pop

    def _kolon_filtre_uygula(self, kolon, secilen):
        try:
            idx = self._kolon_idler.index(kolon)
        except ValueError:
            return
        diger = {
            k: v for k, v in (self._liste_filtre or {}).items() if k != kolon and v is not None
        }
        onceki = self._liste_filtre
        self._liste_filtre = diger
        adaylar = self._filtreli_satirlar()
        self._liste_filtre = onceki
        tum = set()
        for s in adaylar or getattr(self, "_liste_ham", []):
            vals = s["values"]
            tum.add("" if idx >= len(vals) or vals[idx] is None else str(vals[idx]))
        if not secilen:
            self._liste_filtre[kolon] = set()
        elif tum and secilen >= tum:
            self._liste_filtre.pop(kolon, None)
        else:
            self._liste_filtre[kolon] = set(secilen)
        self._listeyi_goster()

    def _kolon_filtre_temizle(self, kolon):
        self._liste_filtre.pop(kolon, None)
        self._listeyi_goster()

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


class YeniBirimDialog(tk.Toplevel):
    """Yeni Birim (+): ad, isteğe bağlı kısa kod; alternatif birimde dönüşüm katsayısı zorunlu (tahmin yok).

    result = {"birim_adi", "kullanim": "ana"|"alternatif", "carpan": str|None}
    """

    def __init__(self, parent, *, ana_birim: str, ana_secilebilir: bool):
        super().__init__(parent)
        self.result = None
        self.ana_birim = ana_birim
        self.title("Yeni Birim")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=BEYAZ)
        govde = tk.Frame(self, bg=BEYAZ)
        govde.pack(fill="both", expand=True, padx=14, pady=12)

        form_etiket(govde, "Birim Adı", zorunlu=True).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.ad = ttk.Entry(govde, width=28)
        self.ad.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        form_etiket(govde, "Kısa Kod (isteğe bağlı)").grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.kisa = ttk.Entry(govde, width=12)
        self.kisa.grid(row=3, column=0, sticky="w", pady=(0, 8))

        self.kullanim = tk.StringVar(value="ana" if ana_secilebilir else "alternatif")
        rb_ana = ttk.Radiobutton(
            govde, text="Bu kartın ana birimi olsun", variable=self.kullanim, value="ana",
            command=self._kullanim_degisti,
        )
        rb_ana.grid(row=4, column=0, columnspan=3, sticky="w")
        if not ana_secilebilir:
            rb_ana.configure(state="disabled")
        ttk.Radiobutton(
            govde, text="Alternatif birim olarak ekle", variable=self.kullanim, value="alternatif",
            command=self._kullanim_degisti,
        ).grid(row=5, column=0, columnspan=3, sticky="w")

        satir = tk.Frame(govde, bg=BEYAZ)
        satir.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.carpan_on = tk.Label(satir, text="1 (yeni birim) =", bg=BEYAZ)
        self.carpan_on.pack(side="left")
        self.carpan = ttk.Entry(satir, width=10)
        self.carpan.pack(side="left", padx=4)
        tk.Label(satir, text=ana_birim, bg=BEYAZ).pack(side="left")
        if not ana_secilebilir:
            tk.Label(
                govde,
                text="Kayıtlı kartın ana birimi buradan değiştirilmez.",
                bg=BEYAZ,
                fg=sktema.IKINCIL,
                font=sktema.font(9, root=self),
            ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))

        alt = tk.Frame(govde, bg=BEYAZ)
        alt.grid(row=8, column=0, columnspan=3, sticky="e", pady=(12, 0))
        stok_tk_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        stok_tk_buton(alt, "Ekle", self._tamam, rol="kaydet").pack(side="right", padx=(0, 8))
        self.ad.bind("<KeyRelease>", lambda _e: self._kullanim_degisti())
        self.bind("<Return>", lambda _e: self._tamam())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._kullanim_degisti()
        self.ad.focus_set()
        self.grab_set()

    def _kullanim_degisti(self):
        ad = " ".join(self.ad.get().split()) or "(yeni birim)"
        self.carpan_on.configure(text=f"1 {ad} =")
        self.carpan.configure(state="normal" if self.kullanim.get() == "alternatif" else "disabled")

    def _tamam(self):
        ad = " ".join(self.ad.get().split())
        kullanim = self.kullanim.get()
        carpan = None
        if not ad:
            messagebox.showwarning("Yeni Birim", "Birim adını yazın.", parent=self)
            return
        if kullanim == "alternatif":
            if birim_anahtari(ad) == birim_anahtari(self.ana_birim):
                messagebox.showwarning(
                    "Yeni Birim", f"«{ad}» zaten bu kartın ana birimi.", parent=self
                )
                return
            kayitli = getattr(self.master, "birimler", None) or []
            if any(birim_anahtari(_birim_adi(b)) == birim_anahtari(ad) for b in kayitli):
                messagebox.showwarning(
                    "Yeni Birim",
                    f"«{ad}» bu kartta zaten tanımlı. Katsayıyı «Birimler…» ekranından düzenleyin.",
                    parent=self,
                )
                return
            metin = self.carpan.get().strip()
            try:
                deger = decimal(metin, "Dönüşüm katsayısı", None) if metin else None
            except ValueError:
                deger = None
            if deger is None or deger <= 0:
                messagebox.showwarning(
                    "Dönüşüm katsayısı",
                    f"1 {ad} kaç {self.ana_birim}? Sıfırdan büyük katsayıyı girin "
                    f"(ör. 1 Koli = 12 Adet). Katsayı tahmin edilmez.",
                    parent=self,
                )
                self.carpan.focus_set()
                return
            carpan = format(deger.normalize(), "f")
        try:
            ad = StokService.birim_tanimi_ekle(ad, self.kisa.get(), BIRIM_SECENEKLERI)
        except BirimZatenVar as hata:
            if not messagebox.askyesno(
                "Yeni Birim", f"{hata}\n\nMevcut «{hata.mevcut_ad}» birimi kullanılsın mı?", parent=self
            ):
                return
            ad = hata.mevcut_ad
        except ValueError as hata:
            messagebox.showerror("Yeni Birim", str(hata), parent=self)
            return
        self.result = {"birim_adi": ad, "kullanim": kullanim, "carpan": carpan}
        self.destroy()


class StokKartiDialog(tk.Toplevel):
    FIYAT_ADLARI = STOK_FIYAT_ADLARI

    def __init__(self, parent, stok=None, baslangic=None, rapor_grubu_zorunlu=False, on_saved=None):
        super().__init__(parent)
        self.stok = (
            StokService.stok_getir(stok.id, kart_acilis=True) if stok else None
        )
        self.baslangic = baslangic or {}
        self.result = None
        self._on_saved = on_saved
        self._kaydediliyor = False
        self._kapaniyor = False
        self._ozet_token = 0
        self._depo_token = 0
        self.rapor_grubu_zorunlu = bool(rapor_grubu_zorunlu)
        self.title("Stok Kartını Düzenle" if stok else "Yeni Stok Kartı")
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.configure(bg=ACIK_BG)
        self.protocol("WM_DELETE_WINDOW", self._kapat_istegi)
        stok_stil_uygula(root=self)
        # minsize iş alanına göre — sabit 720px görev çubuğu altında taşırır
        self._minsize_alana_gore()
        self._pencere_boyutunu_ayarla()

        self.aciklama = (self.stok.aciklama if self.stok else "") or ""
        if not self.stok and (self.baslangic.get("aciklama") or "").strip():
            self.aciklama = str(self.baslangic.get("aciklama") or "").strip()
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
        # Yeni boş kart: ana birim Adet (başlangıçta birim verildiyse o) katsayı 1
        self._yeni_kart_ana_birim = None
        if not self.stok:
            self._yeni_kart_ana_birim = " ".join(str(self.baslangic.get("birim") or "Adet").split()) or "Adet"
            self.birimler = [_ana_birim_kaydi(self._yeni_kart_ana_birim)]
        self.varsayilan_goruntuleme_birim = (
            (getattr(self.stok, "varsayilan_goruntuleme_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else self._yeni_kart_ana_birim)
            or "Adet"
        )
        self.varsayilan_alis_birim = (
            (getattr(self.stok, "varsayilan_alis_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else self._yeni_kart_ana_birim)
            or "Adet"
        )
        self.varsayilan_satis_birim = (
            (getattr(self.stok, "varsayilan_satis_birim", None) if self.stok else None)
            or (self.stok.birim if self.stok else self._yeni_kart_ana_birim)
            or "Adet"
        )
        # Resimler sekme açılınca yüklenir (kart_acilis ORM'de selectinload yok)
        self.resimler: list[dict] = []
        self._resimler_db_yuklu = not bool(self.stok)
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
        elif not self.stok:
            barkod_oneri = (self.baslangic.get("barkod") or "").strip()
            if barkod_oneri:
                self.barkodlar = [
                    {
                        "barkod": barkod_oneri,
                        "birim": self._yeni_kart_ana_birim or "Adet",
                        "fiyat_adi": "SATIŞ FİYATI 1",
                        "fiyat": "0",
                        "aciklama": "Fatura barkodu",
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
        # Üst blok sticky footer ust alanı; baslik_seridi parent'a pack eder
        self._ust_blok = tk.Frame(self, bg=ACIK_BG)
        self._baslik = baslik_seridi(
            self._ust_blok,
            baslik="Stok Kartı",
            alt=f"{kod_metin}" + (f"  ·  {ad_metin}" if ad_metin else ""),
            durum=durum,
        )
        ref_bilgi = (self.baslangic.get("referans_bilgi") or "").strip() if self.baslangic else ""
        if ref_bilgi and not self.stok:
            tk.Label(
                self._ust_blok,
                text=ref_bilgi,
                bg=ACIK_BG,
                fg="#334155",
                font=sktema.font(9, root=self),
                wraplength=1000,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=14, pady=(6, 0))

        # Üst özet şeridi kaldırıldı — değerler Depo ve Stok Durumu panelinde
        self.ozet_kartlari = {}
        self.ozet_etiketleri = {}
        self.ozet_alt_etiketleri = {}

        # Alt işlem şeridi — kaydırılan içeriğin dışında, pack side=bottom (sticky footer)
        self._alt_islem_seridi = tk.Frame(
            self, bg=BEYAZ, highlightthickness=1, highlightbackground=sktema.CIZGI
        )
        kayit_ic = tk.Frame(self._alt_islem_seridi, bg=BEYAZ)
        kayit_ic.pack(fill="x", padx=12, pady=8)
        stok_tk_buton(kayit_ic, "Vazgeç", self._kapat_istegi, rol="ikincil").pack(side="right")
        self.kaydet_btn = stok_tk_buton(kayit_ic, "Kaydet", self.kaydet, rol="kaydet_3d")
        self.kaydet_btn.pack(side="right", padx=(0, 8))
        stok_tk_buton(kayit_ic, "Yeni Kart", self._yeni_kart, rol="yeni").pack(side="left")
        stok_tk_buton(kayit_ic, "Yeni Grup Ekle", self._yeni_grup_ekle, rol="yeni").pack(
            side="left", padx=(8, 0)
        )
        stok_tk_buton(kayit_ic, "Birim Dönüştürücü", self.birimler_ac, rol="kaydet").pack(
            side="left", padx=(8, 0)
        )
        if self.stok:
            stok_tk_buton(kayit_ic, "Hareketler", self._hareketler_sekmesine_gec, rol="ara").pack(
                side="left", padx=(8, 0)
            )
            stok_tk_buton(kayit_ic, "Fiyat Analiz", self.fiyat_analiz_ac, rol="ikincil").pack(
                side="left", padx=(8, 0)
            )
            stok_tk_buton(kayit_ic, "Lot Kâr/Zarar", self._lot_kar_zarar_ac, rol="ikincil").pack(
                side="left", padx=(8, 0)
            )
            stok_tk_buton(kayit_ic, "Kolon Ayarları", self._hareket_kolon_ayarlari_ac, rol="ikincil").pack(
                side="left", padx=(8, 0)
            )

        # Orta: sekmeler + hareketler (kalan yükseklik; daralınca önce hareket küçülür)
        # Not: sash, pencere henüz 1×1 iken ayarlanırsa 0'da kalır ve üst form kaybolur.
        self._govde = tk.Frame(self, bg=ACIK_BG)
        self._dikey_bolme = ttk.PanedWindow(self._govde, orient="vertical")
        self._dikey_bolme.pack(fill="both", expand=True, padx=8, pady=(4, 6))
        self.sekmeler = ttk.Notebook(self._dikey_bolme, style="StokKart.TNotebook")
        tab_hareket = ttk.LabelFrame(
            self._dikey_bolme, text="Stok Hareketleri", padding=0, style="StokKart.TLabelframe"
        )
        self._dikey_bolme.add(self.sekmeler, weight=2)
        self._dikey_bolme.add(tab_hareket, weight=3)
        self._sash_ayarlandi = False
        self._sash_retry = 0
        # Üst pane çökmesin (ttk destekliyorsa)
        try:
            self._dikey_bolme.pane(self.sekmeler, weight=2, minsize=240)
        except (tk.TclError, TypeError, AttributeError):
            try:
                self._dikey_bolme.pane(self.sekmeler, weight=2)
            except (tk.TclError, TypeError, AttributeError):
                pass
        self._dikey_bolme.bind("<Configure>", self._dikey_bolme_configure, add="+")
        # Sash/genişlet: odak verildikten sonra (_odak_sonrasi_agir_isler) — açılışı kilitlemesin
        self._hareket_genislet_acilista_planlandi = False

        tab_genel = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_barkod = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_fiyat = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_depo = tk.Frame(self.sekmeler, bg=BEYAZ)
        tab_notlar = tk.Frame(self.sekmeler, bg=BEYAZ)
        self.sekmeler.add(tab_genel, text="  Genel  ")
        self.sekmeler.add(tab_barkod, text="  Barkod & Birimler  ")
        self.sekmeler.add(tab_fiyat, text="  Fiyat & Maliyet  ")
        self.sekmeler.add(tab_depo, text="  Depo & Stok  ")
        self.sekmeler.add(tab_notlar, text="  Notlar  ")
        # Fon / muhasebe / resimler: ilk seçimde kur (açılış __init__ yükünü kısar)
        self._tab_fon = tk.Frame(self.sekmeler, bg=BEYAZ)
        self.sekmeler.add(self._tab_fon, text="  Fonlar  ")
        self._tab_muhasebe = tk.Frame(self.sekmeler, bg=BEYAZ)
        self._tab_resimler = tk.Frame(self.sekmeler, bg=BEYAZ)
        self.sekmeler.add(self._tab_muhasebe, text="  Muhasebe Kodları  ")
        self.sekmeler.add(self._tab_resimler, text="  Stok Resimleri  ")
        self._fon_sekme_kuruldu = False
        self._muhasebe_sekme_kuruldu = False
        self._resimler_sekme_kuruldu = False
        self.muhasebe_alanlari = {}
        # Notebook varsayılanı en yüksek sekmeyi baz alır; seçili olmayanları daralt
        self.sekmeler.bind("<<NotebookTabChanged>>", self._sekme_yukseklik_sinirla, add="+")
        self.after_idle(self._sekme_yukseklik_sinirla)

        # --- Genel: kompakt üç panel + tür/grup satırı ---
        self.alanlar = {}
        self._stok_ana_tur_map: dict[str, int] = {}
        self._stok_alt_tur_map: dict[str, int] = {}
        _EW = 11  # hizalı etiket sütun genişliği (karakter)

        uc = tk.Frame(tab_genel, bg=BEYAZ)
        uc.pack(fill="x", padx=6, pady=(4, 1))
        for col, w in enumerate((38, 30, 32)):
            uc.columnconfigure(col, weight=w, uniform="stok_uc")
        panel_kimlik = ttk.LabelFrame(
            uc, text="Stok Kimliği", padding=3, style="StokKartKompakt.TLabelframe"
        )
        panel_ozellik = ttk.LabelFrame(
            uc, text="Özellikler", padding=3, style="StokKartKompakt.TLabelframe"
        )
        panel_depo = ttk.LabelFrame(
            uc, text="Depo ve Stok Durumu", padding=3, style="StokKartKompakt.TLabelframe"
        )
        panel_kimlik.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        panel_ozellik.grid(row=0, column=1, sticky="nsew", padx=3)
        panel_depo.grid(row=0, column=2, sticky="nsew", padx=(3, 0))
        panel_kimlik.columnconfigure(1, weight=1)
        panel_ozellik.columnconfigure(1, weight=1)
        panel_ozellik.columnconfigure(3, weight=1)
        panel_depo.columnconfigure(1, weight=1)

        def _sol_etiket(parent, metin, row, *, zorunlu=False, col=0):
            form_etiket(parent, metin, zorunlu=zorunlu, genislik=_EW).grid(
                row=row, column=col, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )

        # Kimlik: etiket | alan aynı satırda
        _sol_etiket(panel_kimlik, "Stok Adı", 0, zorunlu=True)
        ad_w = ttk.Combobox(panel_kimlik, width=26, style="StokKartAd.TCombobox")
        # ttk clam: constructor font= stil tarafından ezilir; configure zorunlu (11 bold)
        ad_w.configure(font=sktema.font(11, "bold", self))
        ad_w.grid(row=0, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        stok_tk_buton(
            panel_kimlik, "Yeni", lambda: self.stok_alan_yeni("stok_adi"), rol="yeni", kompakt=True
        ).grid(row=0, column=2, padx=(0, 2), pady=SATIR_PADY)
        ad_w.bind("<KeyRelease>", self._stok_adi_ara)
        ad_w.bind("<<ComboboxSelected>>", self._stok_adi_secildi)
        from stok_arama_alani import StokAramaAlani

        self._stok_ad_arama = StokAramaAlani(
            self,
            ad_w,
            on_secim=self._stok_listeden_secildi,
            secili_ad=lambda: (getattr(self.stok, "stok_adi", None) or "") if self.stok else "",
        )
        self.alanlar["stok_adi"] = ad_w

        _sol_etiket(panel_kimlik, "Stok Kodu", 1, zorunlu=True)
        kod_w = ttk.Combobox(panel_kimlik, width=26, style="StokKart.TCombobox")
        kod_w.grid(row=1, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        stok_tk_buton(
            panel_kimlik, "Yeni", lambda: self.stok_alan_yeni("stok_kodu"), rol="yeni", kompakt=True
        ).grid(row=1, column=2, padx=(0, 2), pady=SATIR_PADY)
        kod_w.bind("<KeyRelease>", self._stok_kodu_keyrelease)
        kod_w.bind("<<ComboboxSelected>>", self._stok_kodu_secildi)
        self._stok_kodu_sag_tik_bagla(kod_w)
        self.alanlar["stok_kodu"] = kod_w

        _sol_etiket(panel_kimlik, "Ana Birim", 2, zorunlu=True)
        # Açılışta DB birim listesi yok — sabit/önbellek; tam liste odaktan sonra
        birim_degerler = self._ana_birim_secenekleri(db_izinli=False)
        birim_w = ttk.Combobox(panel_kimlik, values=birim_degerler, width=12, style="StokKart.TCombobox")
        mevcut_birim = (self.stok.birim if self.stok else None) or (birim_degerler[0] if birim_degerler else "")
        if mevcut_birim:
            birim_w.set(mevcut_birim)
        birim_w.grid(row=2, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        birim_w.bind("<FocusIn>", lambda _e: self._ana_birim_listesini_yenile())
        birim_w.bind("<<ComboboxSelected>>", self._yeni_kart_ana_birimi_esitle, add="+")
        birim_w.bind("<FocusOut>", self._yeni_kart_ana_birimi_esitle, add="+")
        self.alanlar["birim"] = birim_w
        stok_tk_buton(panel_kimlik, "Birimler…", self.birimler_ac, rol="yeni", kompakt=True).grid(
            row=2, column=2, padx=(0, 2), pady=SATIR_PADY
        )

        _sol_etiket(panel_kimlik, "KDV %", 3)
        kdv_satir = tk.Frame(panel_kimlik, bg=BEYAZ)
        kdv_satir.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        kdv_w = ttk.Combobox(kdv_satir, values=KDV_ORANLARI, width=8, state="readonly", style="StokKart.TCombobox")
        mevcut_kdv = getattr(self.stok, "kdv_orani", None) if self.stok else None
        if mevcut_kdv is None:
            kdv_w.set(str(int(VARSAYILAN_KDV_ORANI)))
        else:
            from database.fatura_kdv_service import satir_kdv_metin_sayisal

            metin = satir_kdv_metin_sayisal(mevcut_kdv)
            if metin not in KDV_ORANLARI:
                kdv_w.configure(values=KDV_ORANLARI + (metin,), state="normal")
            kdv_w.set(metin)
        kdv_w.pack(side="left")
        self.alanlar["kdv_orani"] = kdv_w
        form_etiket(kdv_satir, "Durum", genislik=6).pack(side="left", padx=(8, 4))
        durum_w = ttk.Combobox(
            kdv_satir, values=("Aktif", "Pasif"), width=8, state="readonly", style="StokKart.TCombobox"
        )
        durum_w.set("Aktif" if (not self.stok or getattr(self.stok, "aktif", True)) else "Pasif")
        durum_w.pack(side="left")
        self.alanlar["kart_durumu"] = durum_w

        _sol_etiket(panel_kimlik, "Ağırlık", 4)
        ag_w = ttk.Entry(panel_kimlik, width=14, style="StokKart.TEntry")
        ag_w.grid(row=4, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        self.alanlar["agirlik"] = ag_w
        _sol_etiket(panel_kimlik, "Raf Ömrü", 5)
        raf_satir = tk.Frame(panel_kimlik, bg=BEYAZ)
        raf_satir.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        raf_omru_w = ttk.Combobox(
            raf_satir, values=StokService.raf_omru_secenekleri(), width=12, style="StokKart.TCombobox"
        )
        if self.stok and self.stok.raf_omru:
            raf_omru_w.set(tarih_goster(self.stok.raf_omru))
        raf_omru_w.pack(side="left", fill="x", expand=True)
        stok_tk_buton(raf_satir, "…", self.raf_omru_sec, rol="yeni", kompakt=True).pack(
            side="left", padx=(2, 0)
        )
        self.alanlar["raf_omru"] = raf_omru_w

        # Özellikler: Marka/Model, Renk/Raf — etiket solda
        for r, (e1, a1, e2, a2) in enumerate((
            ("Marka", "marka", "Model", "model"),
            ("Renk", "renk", "Raf Yeri", "raf_yeri"),
        )):
            form_etiket(panel_ozellik, e1, genislik=8).grid(
                row=r, column=0, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )
            w1 = ttk.Combobox(
                panel_ozellik, values=StokService.secenekleri_listele(a1), width=12, style="StokKart.TCombobox"
            )
            if self.stok and getattr(self.stok, a1, None):
                w1.set(getattr(self.stok, a1))
            w1.grid(row=r, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
            w1.bind("<Return>", lambda e, a=a1: self.secenek_yazilanı_kaydet(a, a))
            self.alanlar[a1] = w1
            form_etiket(panel_ozellik, e2, genislik=8).grid(
                row=r, column=2, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )
            w2 = ttk.Combobox(
                panel_ozellik, values=StokService.secenekleri_listele(a2), width=12, style="StokKart.TCombobox"
            )
            if self.stok and getattr(self.stok, a2, None):
                w2.set(getattr(self.stok, a2))
            w2.grid(row=r, column=3, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
            w2.bind("<Return>", lambda e, a=a2: self.secenek_yazilanı_kaydet(a, a))
            self.alanlar[a2] = w2
        stok_tk_buton(
            panel_ozellik, "Yeni…", lambda: self.secenek_ekle("marka", "marka"), rol="yeni", kompakt=True
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=2, pady=SATIR_PADY)

        # Depo: çerçeveli salt okunur alanlar (etiket solda)
        self._panel_depo_lbl = {}
        for r, (baslik, anahtar) in enumerate((
            ("Toplam Giriş", "Toplam Giriş"),
            ("Toplam Çıkış", "Toplam Çıkış"),
            ("Mevcut Miktar", "Kalan Miktar"),
            ("FIFO Envanter", "FIFO Envanter Değeri"),
        )):
            form_etiket(panel_depo, baslik, genislik=_EW).grid(
                row=r, column=0, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )
            ent = ttk.Entry(panel_depo, width=18, style="StokKartReadonly.TEntry")
            ent.insert(0, "—")
            ent.configure(state="readonly")
            ent.grid(row=r, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
            self._panel_depo_lbl[anahtar] = ent
        form_etiket(panel_depo, "Minimum Stok", genislik=_EW).grid(
            row=4, column=0, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
        )
        min_satir = tk.Frame(panel_depo, bg=BEYAZ)
        min_satir.grid(row=4, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        min_w = ttk.Entry(min_satir, width=12, style="StokKart.TEntry")
        min_w.pack(side="left", fill="x", expand=True)
        if self.stok and getattr(self.stok, "minimum_stok", None) is not None:
            ms = Decimal(str(self.stok.minimum_stok or 0))
            if ms != 0:
                min_w.insert(0, f"{ms:f}".rstrip("0").rstrip("."))
        self.alanlar["minimum_stok"] = min_w
        if self.stok and getattr(self.stok, "id", None):
            stok_tk_buton(min_satir, "Uyarı…", self._stok_uyari_ayari_ac, rol="yeni", kompakt=True).pack(
                side="left", padx=(2, 0)
            )

        # Tür + Ana/Tali/Alt grup — tek satır, dört alan yan yana
        tur_grup = ttk.LabelFrame(
            tab_genel, text="Stok Kart Türü ve Gruplar", padding=3, style="StokKartKompakt.TLabelframe"
        )
        tur_grup.pack(fill="x", padx=6, pady=(1, 1))
        for c in range(12):
            tur_grup.columnconfigure(c, weight=1 if c % 3 == 1 else 0)
        self._grup_id_map = {"ana": {}, "tali": {}, "alt": {}}
        self.grup_alanlari = {}

        form_etiket(tur_grup, "Stok Kart Türü", zorunlu=True, genislik=14).grid(
            row=0, column=0, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
        )
        self.alanlar["ana_kart_turu"] = ttk.Combobox(
            tur_grup, width=16, state="readonly", style="StokKart.TCombobox"
        )
        self.alanlar["ana_kart_turu"].grid(row=0, column=1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
        stok_tk_buton(tur_grup, "Yönet", self._stok_ana_tur_yonet, rol="yeni", kompakt=True).grid(
            row=0, column=2, padx=(0, 8), pady=SATIR_PADY
        )
        # Gizli uyumluluk: alt tür UI yok; eski kayıt değeri korunur
        self.alanlar["alt_kart_turu"] = ttk.Combobox(tur_grup)
        self._stok_tur_uyari = tk.Label(tur_grup, text="", bg=BEYAZ, fg="#C62828", font=sktema.font(8, root=self))
        self.alanlar["ana_kart_turu"].bind("<<ComboboxSelected>>", lambda _e: self._stok_ana_tur_degisti())
        # Tür/grup DB listeleri — ilk boyamadan sonra (açılışı kilitlemesin)
        self._stok_ana_tur_map = {}
        self._stok_alt_tur_map = {}

        for col0, (etiket, anahtar) in enumerate(
            (("Ana Grup", "ana"), ("Tali Grup", "tali"), ("Alt Grup", "alt")), start=1
        ):
            c_et = col0 * 3
            form_etiket(tur_grup, etiket, genislik=9).grid(
                row=0, column=c_et, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )
            cb = ttk.Combobox(tur_grup, width=14, style="StokKart.TCombobox")
            cb.grid(row=0, column=c_et + 1, sticky="ew", padx=(0, 2), pady=SATIR_PADY)
            self.grup_alanlari[anahtar] = cb
            stok_tk_buton(
                tur_grup, "+", lambda a=anahtar: self._grup_yeni_ekle(a), rol="yeni", kompakt=True
            ).grid(row=0, column=c_et + 2, padx=(0, 6), pady=SATIR_PADY)
        self.grup_pasif_lbl = tk.Label(
            tur_grup, text="", bg=BEYAZ, fg="#C62828", font=sktema.font(8, root=self)
        )
        # Boş uyarı satırı yer kaplamasın; metin gelince grid edilir
        self.grup_alanlari["ana"].bind("<<ComboboxSelected>>", lambda _e: self._grup_ana_degisti())
        self.grup_alanlari["tali"].bind("<<ComboboxSelected>>", lambda _e: self._grup_tali_degisti())
        self.grup_alanlari["ana"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("ana"))
        self.grup_alanlari["tali"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("tali"))
        self.grup_alanlari["alt"].bind("<KeyRelease>", lambda _e: self._grup_filtre_yaz("alt"))
        self.grup_alanlari["tali"].configure(values=[], state="disabled")
        self.grup_alanlari["alt"].configure(values=[], state="disabled")

        self._stok_kod_eslesme = {}
        self._stok_ad_eslesme = {}

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
        self.etiket_btn = stok_tk_buton(bb_btn, "Etiket Yazdır", self._barkod_etiket_yazdir, rol="ikincil")
        self.etiket_btn.pack(side="left", padx=(6, 0))
        self.etiket_neden_lbl = tk.Label(
            bb_btn, text="", bg=BEYAZ, fg="#C62828", font=sktema.font(9, root=self)
        )
        self.etiket_neden_lbl.pack(side="left", padx=(8, 0))

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
        stok_tk_buton(bu_btn, "Birim Dönüştürücü", self.birimler_ac, rol="kaydet").pack(
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
        # Barkod/birim tablosu: Genel sekmesinde görünmez; ilk Barkod sekmesinde doldurulur

        # --- Fiyat & Maliyet: sol alış (kompakt) | sağ satış tablosu ---
        fiyat_ust = tk.Frame(tab_fiyat, bg=BEYAZ)
        fiyat_ust.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        fiyat_ust.columnconfigure(0, weight=2, minsize=260)
        fiyat_ust.columnconfigure(1, weight=3, minsize=360)
        fiyat_ust.rowconfigure(0, weight=1)

        alis_cerceve = ttk.LabelFrame(
            fiyat_ust, text="Alış Fiyatları", padding=6, style="StokKart.TLabelframe"
        )
        alis_cerceve.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.fiyat_alanlari = {}

        ttk.Label(alis_cerceve, text="Liste Fiyatı", style="StokKartPanel.TLabel").grid(
            row=0, column=0, padx=4, pady=2, sticky="w"
        )
        self.fiyat_alanlari["LİSTE FİYATI"] = ttk.Entry(alis_cerceve, width=14)
        self.fiyat_alanlari["LİSTE FİYATI"].grid(row=0, column=1, padx=4, pady=2, sticky="w")
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
        self.fiyat_alanlari["LİSTE FİYATI"].bind("<FocusOut>", self._fabrika_fiyati_guncelle)

        self.iskonto_alanlari = {}
        for kolon, (etiket, anahtar) in enumerate(
            (("1. İsk. %", "iskonto_1"), ("2. İsk. %", "iskonto_2"), ("3. İsk. %", "iskonto_3"))
        ):
            ttk.Label(alis_cerceve, text=etiket, style="StokKartPanel.TLabel").grid(
                row=1 + kolon, column=0, padx=4, pady=1, sticky="w"
            )
            giris = ttk.Entry(alis_cerceve, width=10)
            giris.grid(row=1 + kolon, column=1, padx=4, pady=1, sticky="w")
            giris.bind("<KeyRelease>", self._fabrika_fiyati_guncelle)
            giris.bind("<FocusOut>", self._fabrika_fiyati_guncelle)
            self.iskonto_alanlari[anahtar] = giris

        ttk.Label(alis_cerceve, text="Fabrika Fiyatı", style="StokKartPanel.TLabel").grid(
            row=4, column=0, padx=4, pady=2, sticky="w"
        )
        self.fiyat_alanlari["FABRİKA FİYATI"] = ttk.Entry(alis_cerceve, width=14, state="readonly")
        self.fiyat_alanlari["FABRİKA FİYATI"].grid(row=4, column=1, padx=4, pady=2, sticky="w")
        ttk.Label(
            alis_cerceve,
            text="Fabrika = Liste − ardışık alış iskontoları",
            style="StokKartPanelMuted.TLabel",
        ).grid(row=5, column=0, columnspan=2, padx=4, pady=(0, 2), sticky="w")

        diger_alis = (
            ("Alış Fiyatı", "ALIŞ FİYATI"),
            ("Spot Fiyatı", "SPOT FİYATI"),
            ("İnternet Fiyatı", "İNTERNET FİYATI"),
            ("Rakip Fiyatı", "RAKİP FİYATI"),
        )
        for sira, (etiket, fiyat_adi) in enumerate(diger_alis):
            satir = 6 + sira
            tk.Label(
                alis_cerceve,
                text=etiket,
                bg=BEYAZ,
                fg=_ALIS_ETIKET_FG,
                font=sktema.font(9, "bold", root=self),
            ).grid(row=satir, column=0, padx=4, pady=1, sticky="w")
            if fiyat_adi == "ALIŞ FİYATI":
                giris = ttk.Entry(alis_cerceve, width=14, state="readonly")
            else:
                giris = ttk.Entry(alis_cerceve, width=14)
            giris.grid(row=satir, column=1, padx=4, pady=1, sticky="w")
            self.fiyat_alanlari[fiyat_adi] = giris
        ttk.Label(
            alis_cerceve,
            text="Alış = son alış faturası net birim fiyatı",
            style="StokKartPanelMuted.TLabel",
        ).grid(row=10, column=0, columnspan=2, padx=4, pady=(2, 0), sticky="w")

        satis_cerceve = ttk.LabelFrame(
            fiyat_ust, text="Satış Fiyatları", padding=4, style="StokKart.TLabelframe"
        )
        satis_cerceve.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        satis_cerceve.rowconfigure(1, weight=1)
        satis_cerceve.columnconfigure(0, weight=1)

        satis_ust_bar = tk.Frame(satis_cerceve, bg=BEYAZ)
        satis_ust_bar.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        stok_tk_buton(
            satis_ust_bar,
            "Fiyat Listelerini Yönet",
            self._fiyat_listelerini_yonet,
            rol="ikincil",
        ).pack(side="left")
        ttk.Label(
            satis_ust_bar,
            text="Listeye bağlı: Liste × (1 − satış iskonto %)",
            style="StokKartPanelMuted.TLabel",
        ).pack(side="left", padx=(10, 0))

        satis_scroll_dis = tk.Frame(satis_cerceve, bg=BEYAZ)
        satis_scroll_dis.grid(row=1, column=0, sticky="nsew")
        satis_scroll_dis.rowconfigure(0, weight=1)
        satis_scroll_dis.columnconfigure(0, weight=1)
        self._satis_canvas = tk.Canvas(satis_scroll_dis, bg=BEYAZ, highlightthickness=0, height=180)
        satis_sb = ttk.Scrollbar(satis_scroll_dis, orient="vertical", command=self._satis_canvas.yview)
        self._satis_canvas.configure(yscrollcommand=satis_sb.set)
        self._satis_canvas.grid(row=0, column=0, sticky="nsew")
        satis_sb.grid(row=0, column=1, sticky="ns")
        self._satis_ic = tk.Frame(self._satis_canvas, bg=BEYAZ)
        self._satis_canvas_win = self._satis_canvas.create_window((0, 0), window=self._satis_ic, anchor="nw")

        def _satis_scroll_region(_e=None):
            self._satis_canvas.configure(scrollregion=self._satis_canvas.bbox("all"))
            try:
                self._satis_canvas.itemconfigure(self._satis_canvas_win, width=self._satis_canvas.winfo_width())
            except tk.TclError:
                pass

        self._satis_ic.bind("<Configure>", _satis_scroll_region)
        self._satis_canvas.bind("<Configure>", _satis_scroll_region)

        baslik_satir = tk.Frame(self._satis_ic, bg="#E8F5E9")
        baslik_satir.pack(fill="x", pady=(0, 2))
        for metin, w in (
            ("Liste", 18),
            ("Hesaplama", 16),
            ("İsk. %", 7),
            ("Satış fiyatı", 12),
            ("KDV", 12),
        ):
            tk.Label(
                baslik_satir,
                text=metin,
                bg="#E8F5E9",
                fg=_SATIS_ETIKET_FG,
                font=sktema.font(8, "bold", root=self),
                width=w,
                anchor="w",
            ).pack(side="left", padx=2)

        self.fiyat_kdv_alanlari = {}
        self.fiyat_hesap_alanlari = {}
        self._satis_satir_frame = {}
        self._satis_uyari_lbl = None
        # Açılışta DB şema/sorgu yok — önbellek veya sabit liste; tam liste odaktan sonra
        cached_satis = _STOK_KART_LISTE_CACHE.get("satis_kodlari")
        if cached_satis:
            satis_kodlar = list(cached_satis)
        else:
            satis_kodlar = list(SATIS_FIYAT_ADLARI)
        self._satis_fiyat_kodlari = satis_kodlar
        self._satis_tablosunu_kur(satis_kodlar)

        self._satis_uyari_lbl = ttk.Label(
            satis_cerceve,
            text="",
            style="StokKartPanelMuted.TLabel",
        )
        self._satis_uyari_lbl.grid(row=2, column=0, sticky="w", padx=2, pady=(2, 0))

        yk_cerceve = ttk.LabelFrame(
            tab_fiyat, text="Yerine Koyma / Analiz", padding=4, style="StokKart.TLabelframe"
        )
        yk_cerceve.pack(fill="x", padx=8, pady=(4, 2))
        yk_satir = tk.Frame(yk_cerceve, bg=BEYAZ)
        yk_satir.pack(fill="x")
        self._yerine_koyma_ozet = ttk.Label(
            yk_satir,
            text="Yerine koyma maliyeti analiz raporu stok/FIFO maliyetini değiştirmez.",
            style="StokKartPanelMuted.TLabel",
        )
        self._yerine_koyma_ozet.pack(side="left", padx=(0, 8))
        ttk.Button(
            yk_satir,
            text="Yerine Koyma Raporu",
            command=self._yerine_koyma_raporu_ac,
        ).pack(side="left")

        fiyat_aksiyon = tk.Frame(tab_fiyat, bg=BEYAZ)
        fiyat_aksiyon.pack(fill="x", padx=8, pady=(0, 6))
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
        hrk.pack(fill="both", expand=True, padx=8, pady=6)
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
        # Açılışta yıl başı yerine son 90 gün — ağır FIFO/ekstre yükünü kısar; «Tümü» ile genişletilir
        self.hrk_baslangic.insert(0, tarih_goster(date.today() - timedelta(days=90)))
        tk.Label(hrk_ust, text="Bitiş", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_bitis = ttk.Entry(hrk_ust, width=12)
        self.hrk_bitis.pack(side="left", padx=(4, 8))
        self.hrk_bitis.insert(0, tarih_goster(date.today()))
        tk.Label(hrk_ust, text="Depo", bg=BEYAZ, fg=sktema.IKINCIL).pack(side="left")
        self.hrk_depo_var = tk.StringVar(value="(Tümü)")
        # Depo listesi açılışta senkron sorgulanmaz — ikincil yüklemede doldurulur
        self.hrk_depo_cb = ttk.Combobox(
            hrk_ust, textvariable=self.hrk_depo_var, values=["(Tümü)"], width=14, state="readonly"
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
                if fiyat.fiyat_adi in self.fiyat_kdv_alanlari:
                    self.fiyat_kdv_alanlari[fiyat.fiyat_adi].set(
                        fiyat_kdv_metni(getattr(fiyat, "kdv_durumu", None))
                    )
                if fiyat.fiyat_adi in self.fiyat_alanlari:
                    self._fiyat_yaz(fiyat.fiyat_adi, self._fiyat_metni_tr(fiyat.tutar))
                else:
                    hedef = ESKI_FIYAT_ESLEME.get(fiyat.fiyat_adi)
                    if hedef and hedef in self.fiyat_alanlari and not self.fiyat_alanlari[hedef].get():
                        self._fiyat_yaz(hedef, self._fiyat_metni_tr(fiyat.tutar))
                h = (getattr(self, "fiyat_hesap_alanlari", None) or {}).get(fiyat.fiyat_adi)
                if h:
                    h["modu"].set(
                        self._satis_modu_kod_metin(
                            getattr(fiyat, "hesaplama_modu", None) or "MANUEL"
                        )
                    )
                    h["iskonto"].configure(state="normal")
                    h["iskonto"].delete(0, "end")
                    isk = getattr(fiyat, "satis_iskonto", None)
                    if isk is not None and Decimal(str(isk)) != 0:
                        h["iskonto"].insert(0, self._fiyat_metni_tr(isk))
                    self._satis_modu_degisti(fiyat.fiyat_adi, onizleme=False)
            # Son alış net fiyatı ağır sorgu olabilir — ilk boyamadan sonra
            if "ALIŞ FİYATI" in self.fiyat_alanlari:
                self._fiyat_yaz("ALIŞ FİYATI", "…")
            self._fabrika_fiyati_guncelle()
        elif self.baslangic:
            if self.baslangic.get("stok_kodu"):
                self.alanlar["stok_kodu"].set(str(self.baslangic["stok_kodu"]))
            if self.baslangic.get("stok_adi"):
                self.alanlar["stok_adi"].set(str(self.baslangic["stok_adi"]))
            if self.baslangic.get("kart_turu") and "ana_kart_turu" in self.alanlar:
                # Tür listesi after_idle yüklenir — seçimi orada uygula
                self._bekleyen_baslangic_kart_turu = str(self.baslangic["kart_turu"])
            if self.baslangic.get("birim") and "birim" in self.alanlar:
                self.alanlar["birim"].set(str(self.baslangic["birim"]))
            if self.baslangic.get("kdv_orani") is not None and "kdv_orani" in self.alanlar:
                try:
                    from database.fatura_kdv_service import satir_kdv_metin_sayisal

                    metin = satir_kdv_metin_sayisal(self.baslangic.get("kdv_orani"))
                except Exception:
                    metin = str(self.baslangic.get("kdv_orani")).strip()
                if metin:
                    degerler = tuple(self.alanlar["kdv_orani"].cget("values") or ())
                    if metin not in degerler:
                        self.alanlar["kdv_orani"].configure(values=degerler + (metin,), state="normal")
                    self.alanlar["kdv_orani"].set(metin)
            for alan in ("marka", "model"):
                if self.baslangic.get(alan) and alan in self.alanlar:
                    self.alanlar[alan].set(str(self.baslangic[alan]))
            if self.baslangic.get("aciklama"):
                self.aciklama = str(self.baslangic.get("aciklama") or "")

        # Sabit alt işlem şeridi: Kaydet/Vazgeç kaydırılan içeriğin dışında
        from ui_pencere import sticky_footer_layout

        sticky_footer_layout(
            self,
            ust=self._ust_blok,
            orta=self._govde,
            alt=self._alt_islem_seridi,
        )
        self.after(50, self._pencereyi_alana_sigdir)
        self.after(200, self._pencereyi_alana_sigdir)
        # Configure → _pencere_boyut_kaydet_debounce (görev çubuğu üstü Kaydet)

        # Özet/depo: önce «…» göster, ağır sorguyu arka plana al (sıfır uydurma yok)
        self._ozet_yer_tutucu()
        self._ean_uyari_gosterildi = False
        self._stok_kodu_barkod_live_after = None
        # Açılış odağı: Stok Adı (kod/barkod/hareket değil). Sonraki yüklemeler çalmaz.
        self._acilista_odak_bekleniyor = True
        self._kullanici_odak_aldı = False
        self._stok_adi_kullanici_dokundu = False
        ad_w = self.alanlar.get("stok_adi")
        if ad_w is not None:
            ad_w.bind("<KeyPress>", self._stok_adi_kullanici_dokundu_isaretle, add="+")
            ad_w.bind("<<ComboboxSelected>>", self._stok_adi_kullanici_dokundu_isaretle, add="+")
            ad_w.bind("<FocusOut>", self._acilista_odak_baska_alana, add="+")
        for _alan_ad, _w in list(self.alanlar.items()):
            if _alan_ad == "stok_adi" or _w is None:
                continue
            try:
                _w.bind("<FocusIn>", self._acilista_odak_baska_alana, add="+")
            except tk.TclError:
                pass
        # Odak en önde (after(0)); ağır işler ancak odak sonrası
        self.bind("<Map>", self._acilista_map_odak, add="+")
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<Escape>", lambda _e: self._kapat_istegi())
        self.bind("<F8>", lambda _e: self._hareketler_sekmesine_gec())
        self.bind("<F6>", lambda _e: self.barkodlar_ac())
        self.bind("<F10>", lambda _e: self.fiyat_analiz_ac())
        self._ilk_durum = self._durum_ozeti()
        # Yeni kart: boş hareket mesajı senkron (hafif). Mevcut: odaktan sonra.
        if not self.stok:
            self._hareketler_yukle()
        try:
            self._stok_adi_odak_ver()
        except Exception:
            pass
        self.after(0, self._stok_adi_odak_ver)
        self.after(0, self._odak_sonrasi_agir_isler)
        if self.stok:
            self.after(800, lambda: self._stok_kodu_barkod_senkron(live=False, ask_if_needed=False))
        elif self.baslangic.get("stok_kodu"):
            self.after(500, lambda: self._stok_kodu_barkod_senkron(live=True, ask_if_needed=False))
    def _stok_adi_kullanici_dokundu_isaretle(self, _event=None):
        self._stok_adi_kullanici_dokundu = True

    def _acilista_map_odak(self, _event=None):
        """İlk görünürlikte Stok Adı odağı — tekrarlayan Map olaylarında no-op."""
        if getattr(self, "_stok_adi_odak_verildi", False):
            return
        if not getattr(self, "_acilista_odak_bekleniyor", False):
            return
        if getattr(self, "_acilista_map_odak_planlandi", False):
            return
        self._acilista_map_odak_planlandi = True
        self.after_idle(self._stok_adi_odak_ver)

    def _acilista_odak_baska_alana(self, _event=None):
        """Kullanıcı Stok Adı dışına geçtiyse açılış odağını bir daha zorlama.

        Tk oluşturma sırasında otomatik FocusIn'leri yok say — yalnızca açılış
        odağı verildikten sonraki gerçek geçişler sayılır.
        """
        if not getattr(self, "_stok_adi_odak_verildi", False):
            return
        self._kullanici_odak_aldı = True
        self._acilista_odak_bekleniyor = False

    def _stok_adi_odak_ver(self):
        """Tek seferlik açılış odağı — Stok Adı. Zamanlayıcı döngüsü yok."""
        if getattr(self, "_stok_adi_odak_verildi", False):
            self._acilista_odak_bekleniyor = False
            return
        if not getattr(self, "_acilista_odak_bekleniyor", False):
            return
        if getattr(self, "_kullanici_odak_aldı", False) or getattr(self, "_kapaniyor", False):
            self._acilista_odak_bekleniyor = False
            return
        ad = self.alanlar.get("stok_adi")
        if ad is None:
            self._acilista_odak_bekleniyor = False
            return
        try:
            ad.focus_set()
            try:
                ad.selection_clear()
            except tk.TclError:
                pass
            try:
                ad.icursor("end")
            except tk.TclError:
                pass
            # focus_set başarılı sayılır; withdrawn parent'ta focus_get kökte kalabilir
            self._stok_adi_odak_verildi = True
            self._acilista_odak_bekleniyor = False
        except tk.TclError:
            # Başarısız — Map sonrası bir kez daha denenecek
            self._acilista_map_odak_planlandi = False
            return

    def _hareketler_yukle_acilista(self):
        """Odak verildikten hemen sonra hareket sorgusu — yazmayı bloke etmez."""
        if getattr(self, "_kapaniyor", False) or not self.stok:
            return
        if getattr(self, "_hareket_acilista_basladi", False):
            return
        self._hareket_acilista_basladi = True
        self._hareketler_yukle()

    def _odak_sonrasi_agir_isler(self):
        """Tür/grup/özet/sash/birim-satış listesi — Stok Adı yazılabilir olduktan sonra."""
        if getattr(self, "_kapaniyor", False):
            return
        if not getattr(self, "_stok_adi_odak_verildi", False):
            # Odak henüz yoksa kısa süre sonra tekrar dene (Map bekleniyor olabilir)
            if not getattr(self, "_odak_sonrasi_deneme", 0):
                self._odak_sonrasi_deneme = 0
            self._odak_sonrasi_deneme += 1
            if self._odak_sonrasi_deneme <= 40:
                self.after(25, self._odak_sonrasi_agir_isler)
            else:
                # Odak olmasa da kartı işlevsel bırak
                self._odak_sonrasi_agir_isler_calistir()
            return
        self._odak_sonrasi_agir_isler_calistir()

    def _odak_sonrasi_agir_isler_calistir(self):
        if getattr(self, "_odak_sonrasi_basladi", False) or getattr(self, "_kapaniyor", False):
            return
        self._odak_sonrasi_basladi = True
        if self.stok:
            self._hareketler_yukle_acilista()
        self.after(1, self._kart_acilista_ikincil_yukle)
        self.after(1, self._acilista_birim_satis_listelerini_yenile)
        if not getattr(self, "_hareket_genislet_acilista_planlandi", False):
            self._hareket_genislet_acilista_planlandi = True
            self.after(60, self._hareket_alanini_genislet)
            self.bind(
                "<Map>",
                lambda _e: self.after(30, self._hareket_alanini_genislet),
                add="+",
            )

    def _acilista_birim_satis_listelerini_yenile(self):
        """Açılışta atlanan birim/satış listelerini arka planda tamamla."""
        if getattr(self, "_kapaniyor", False):
            return
        from ui_bg import arka_planda

        def _is():
            birimler = StokService.birim_listesi(BIRIM_SECENEKLERI)
            try:
                satis = list(aktif_satis_fiyat_kodlari())
            except Exception:
                satis = list(SATIS_FIYAT_ADLARI)
            return birimler, satis

        def _ok(sonuc):
            if getattr(self, "_kapaniyor", False):
                return
            birimler, satis = sonuc
            _STOK_KART_LISTE_CACHE["birimler"] = list(birimler or [])
            _STOK_KART_LISTE_CACHE["satis_kodlari"] = list(satis or SATIS_FIYAT_ADLARI)
            # Birim combobox: kullanıcı yazıyorsa ezme; yalnız values güncelle
            if "birim" in self.alanlar and not self.stok:
                try:
                    mevcut = (self.alanlar["birim"].get() or "").strip()
                    degerler = self._ana_birim_secenekleri(db_izinli=True)
                    if mevcut and mevcut not in degerler:
                        degerler = [mevcut, *degerler]
                    self.alanlar["birim"].configure(values=degerler)
                except tk.TclError:
                    pass
            # Satış kodları önbelleğe alındı; tablo açılışta sabit 10 liste ile kuruldu.
            # Farklı aktif liste yönetimi «Fiyat Listelerini Yönet» ile zaten yenilenir.

        arka_planda(self, _is, on_ok=_ok, on_err=lambda _e: None)

    def _stok_adi_guvenli_yaz(self, metin: str) -> None:
        """Kullanıcı yazdıysa sonradan gelen veri Stok Adı'nı ezmesin."""
        if getattr(self, "_stok_adi_kullanici_dokundu", False):
            return
        w = self.alanlar.get("stok_adi")
        if w is None:
            return
        try:
            w.set(str(metin or ""))
        except tk.TclError:
            pass

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
            250, lambda: self._stok_kodu_barkod_senkron(live=True, ask_if_needed=False)
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
                        text="Alternatif birim yok. «Birim Dönüştürücü» ile 1 koli = 100 adet gibi tanımlayın."
                    )
        self._etiket_durumu_guncelle()
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

    def _etiket_kayitlari(self) -> tuple[list[dict], str | None]:
        """Kartta etikete basılabilir barkodlar ve (hiç yoksa) nedeni."""
        from stok_barkod_ui import etiket_barkod_durumu

        satis1 = ""
        if "SATIŞ FİYATI 1" in getattr(self, "fiyat_alanlari", {}):
            satis1 = self.fiyat_alanlari["SATIŞ FİYATI 1"].get().strip()
        dolu = [b for b in (self.barkodlar or []) if (b.get("barkod") or "").strip()]
        gecerli = []
        for b in dolu:
            if etiket_barkod_durumu(b["barkod"]) is not None:
                continue
            try:
                fiyat = decimal(b.get("fiyat") or "0", "Fiyat")
                if fiyat <= 0:
                    fiyat = decimal(satis1 or "0", "Fiyat")
            except ValueError:
                fiyat = Decimal("0")
            gecerli.append(
                {
                    "barkod": b["barkod"].strip(),
                    "stok_kodu": self.alanlar["stok_kodu"].get().strip(),
                    "stok_adi": self.alanlar["stok_adi"].get().strip(),
                    "birim": (b.get("birim") or self.alanlar["birim"].get().strip() or "Adet"),
                    "fiyat": fiyat,
                }
            )
        if gecerli:
            return gecerli, None
        return [], etiket_barkod_durumu(dolu[0]["barkod"] if dolu else "")

    def _etiket_durumu_guncelle(self):
        if not hasattr(self, "etiket_btn"):
            return
        gecerli, neden = self._etiket_kayitlari()
        try:
            self.etiket_btn.configure(state="normal" if gecerli else "disabled")
            self.etiket_neden_lbl.configure(text="" if gecerli else f"Etiket basılamaz: {neden}")
        except tk.TclError:
            pass

    def _barkod_etiket_yazdir(self):
        from stok_barkod_ui import EtiketYazdirDialog

        gecerli, neden = self._etiket_kayitlari()
        if not gecerli:
            messagebox.showwarning("Etiket Yazdır", f"Etiket basılamaz: {neden}", parent=self)
            return
        self.wait_window(EtiketYazdirDialog(self, gecerli))

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

    def _depo_tablosu_yenile_arka(self):
        """Depo satırlarını arka planda yükle — açılışı kilitlemez."""
        if not hasattr(self, "depo_tablo") or getattr(self, "_kapaniyor", False):
            return
        from ui_bg import arka_planda

        self._depo_token = int(getattr(self, "_depo_token", 0) or 0) + 1
        token = self._depo_token
        stok_id = int(self.stok.id) if self.stok else None
        if hasattr(self, "depo_bos_lbl"):
            self.depo_bos_lbl.configure(text="Depo bakiyeleri yükleniyor…")

        def _is():
            depolar = list(StokService.depolar(aktif_only=False))
            ozet_map = {}
            if stok_id:
                for s in StokService.stok_depo_ozeti(stok_id):
                    ozet_map[(s.get("depo") or "").upper()] = s
            return depolar, ozet_map

        def _ok(sonuc):
            if token != getattr(self, "_depo_token", 0) or getattr(self, "_kapaniyor", False):
                return
            depolar, ozet_map = sonuc
            self._depo_listesi_cache = depolar
            self._depo_tablosu_doldur(depolar, ozet_map)

        def _err(exc):
            if token != getattr(self, "_depo_token", 0):
                return
            if hasattr(self, "depo_bos_lbl"):
                self.depo_bos_lbl.configure(text=f"Depo listesi yüklenemedi: {exc}")

        arka_planda(self, _is, on_ok=_ok, on_err=_err)

    def _depo_tablosu_yenile(self):
        """Senkron yenileme (kayıt sonrası); mümkünse arka plan kullan."""
        if getattr(self, "_kapaniyor", False):
            return
        self._depo_tablosu_yenile_arka()

    def _depo_tablosu_doldur(self, depolar, ozet_map):
        if not hasattr(self, "depo_tablo"):
            return
        for item in self.depo_tablo.get_children():
            self.depo_tablo.delete(item)
        secili = getattr(self, "_secili_depo_id", None)
        for d in depolar:
            oz = ozet_map.get((d.ad or "").upper()) or {}
            durum = []
            if getattr(d, "varsayilan", False):
                durum.append("Varsayılan")
            durum.append("Aktif" if d.aktif else "Pasif")
            iid = str(d.id)
            mevcut = oz.get("mevcut")
            fifo = oz.get("fifo_deger")
            self.depo_tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    getattr(d, "kod", None) or "",
                    d.ad or "",
                    "…" if (self.stok and mevcut is None and not ozet_map) else f"{mevcut if mevcut is not None else 0}",
                    para_goster(fifo or 0) if fifo is not None or ozet_map else ("…" if self.stok else para_goster(0)),
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
        # 0 Genel, 1 Barkod, 2 Fiyat, 3 Depo, 4 Notlar, 5 Fon, 6 Muhasebe, 7 Resimler
        if secili == 1:
            self._barkod_birim_tablolari_yenile()
        elif secili == 3:
            self._depo_tablosu_yenile()
            self._ozeti_yenile()
        elif secili == 5:
            self._fon_sekmesini_lazy_kur()
        elif secili == 6:
            self._muhasebe_sekmesini_lazy_kur()
        elif secili == 7:
            self._resimler_sekmesini_lazy_kur()

    def _hareketler_sekmesine_gec(self):
        self._hareketler_yukle()
        try:
            self.hareket_tablo.focus_set()
        except tk.TclError:
            pass

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
        try:
            if not self.hareket_tablo.winfo_exists():
                return
        except tk.TclError:
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
        if getattr(self, "_kapaniyor", False):
            return
        for item in self.hareket_tablo.get_children():
            self.hareket_tablo.delete(item)
        maliyet_ok = self._hareket_sonuc.get("maliyet_gorunur", True)
        satirlar = self._hareket_sonuc.get("satirlar") or []
        # Özet satırları (filtre kapsamı) — sayfa diliminden değil tüm sonuçtan
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
        if not satirlar:
            self.hareket_bos_lbl.configure(
                text="Bu dönem için hareket yok. Tarih aralığını genişletin veya «Tümü»ne basın."
            )
            self._hareketler_yuklendi = True
            self._hareket_ilk_satirlar_hazir = True
            return
        self._hareket_ilk_satirlar_hazir = False
        self.hareket_bos_lbl.configure(
            text=f"Hareket satırları yükleniyor (0/{len(satirlar)})…"
        )
        ana_birim = self._hareket_sonuc.get("ana_birim") or ""
        self._hrk_doldur_token = int(getattr(self, "_hrk_doldur_token", 0) or 0) + 1
        token = self._hrk_doldur_token
        # Küçük dilim + ~1 frame ara → UI ping / kaydırma donması azalır
        chunk = 30
        dilim_ara_ms = 16

        def _dilim(bas: int):
            if token != getattr(self, "_hrk_doldur_token", 0) or getattr(self, "_kapaniyor", False):
                return
            try:
                if not self.hareket_tablo.winfo_exists():
                    return
            except tk.TclError:
                return
            # İlk dilim daha geniş — kullanıcı hemen satır görsün
            adim = 60 if bas == 0 else chunk
            bit = min(bas + adim, len(satirlar))
            for sira in range(bas, bit):
                s = satirlar[sira]
                yon = s.get("yon") or "notr"
                tags = [yon]
                if sira % 2 == 1:
                    tags.append("zebra")
                try:
                    if Decimal(str(s.get("kalan") or 0)) < 0:
                        tags = ["negatif"]
                except Exception:
                    pass
                self.hareket_tablo.insert(
                    "",
                    "end",
                    iid=f"{sira}:{s.get('belge_no')}:{s.get('hareket_turu')}",
                    values=_hareket_satir_degerleri(
                        s, ana_birim=ana_birim, maliyet_ok=maliyet_ok
                    ),
                    tags=tuple(tags),
                )
            if bas == 0 and bit > 0:
                self._hareket_ilk_satirlar_hazir = True
                self.hareket_bos_lbl.configure(text="")
            if bit < len(satirlar):
                if bas > 0:
                    self.hareket_bos_lbl.configure(
                        text=f"Hareket satırları yükleniyor ({bit}/{len(satirlar)})…"
                    )
                self.after(dilim_ara_ms, lambda: _dilim(bit))
            else:
                self._hareketler_yuklendi = True
                self._hareket_ilk_satirlar_hazir = True
                self.hareket_bos_lbl.configure(text="")
                uyarilar = self._hareket_sonuc.get("uyarilar") or []
                kritik = [
                    u for u in uyarilar if "uyuşmuyor" in u.lower() or "negatif" in u.lower()
                ]
                if kritik:
                    messagebox.showwarning(
                        "FIFO / mutabakat", "\n".join(kritik[:8]), parent=self
                    )
                # Özet açılışta ayrı yüklendi; mükerrer ağır yenilemeyi atla
                if not getattr(self, "_ozet_acilista_yuklendi", False):
                    self.after(50, self._ozeti_yenile_arka)

        _dilim(0)

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
            self._hareketler_yukle()

    def _pencere_ayar_dosyasi(self) -> Path:
        firma = str(oturum.company_id or oturum.firma_kodu or "0")
        kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"stok_karti_pencere_f{firma}_u{kullanici}.json"

    def _minsize_alana_gore(self):
        """minsize iş alanını aşmasın (yüksek DPI / küçük ekran)."""
        from ui_pencere import calisma_alani, pencere_cerceve_payi

        _ax, _ay, aw, ah = calisma_alani(self)
        cx, cy = pencere_cerceve_payi(self)
        kullanilabilir_h = max(400, ah - cy)
        kullanilabilir_w = max(600, aw - cx)
        min_w = max(720, min(1100, kullanilabilir_w))
        min_h = max(480, min(720, kullanilabilir_h))
        # Küçük ekranda minsize iş alanını zorlamasın
        min_w = min(min_w, kullanilabilir_w)
        min_h = min(min_h, kullanilabilir_h)
        try:
            self.minsize(max(640, min_w), max(400, min_h))
            self.resizable(True, True)
        except tk.TclError:
            pass

    def _pencereyi_alana_sigdir(self, _event=None):
        """Pencere + Kaydet şeridi görev çubuğu arkasına taşmasın (SPI iş alanı).

        Tk geometry istemci alanıdır; çerçeve payı düşülmeden ah verilirse alt
        şerit görev çubuğunun altında kalır. Önce çerçeve paylı sığdır, sonra
        Kaydet düğmesinin ekran altını doğrula.
        """
        from ui_pencere import calisma_alani, is_alanina_sigdir

        if getattr(self, "_alana_sigdir_kilit", False):
            return
        try:
            self.update_idletasks()
            ax, ay, _aw, ah = calisma_alani(self)
            rh = int(self.winfo_height())
            rw = int(self.winfo_width())
        except tk.TclError:
            return
        if rh < 80 or rw < 80:
            return

        work_bottom = ay + ah
        self._alana_sigdir_kilit = True
        try:
            # Zoomed transient bazen tam ekrana taşar — iş alanına zorla
            tasiyor = False
            try:
                ry = int(self.winfo_rooty())
                rx = int(self.winfo_rootx())
                tasiyor = ry + rh > work_bottom + 2 or ry < ay - 2
                if str(self.state()) == "zoomed" and tasiyor:
                    self.state("normal")
            except tk.TclError:
                pass

            btn = getattr(self, "kaydet_btn", None)
            btn_alt = None
            if btn is not None:
                try:
                    if btn.winfo_ismapped():
                        btn_alt = int(btn.winfo_rooty()) + int(btn.winfo_height())
                except tk.TclError:
                    btn_alt = None

            if tasiyor or (btn_alt is not None and btn_alt > work_bottom - 2):
                is_alanina_sigdir(self, maximize=False)
                self.update_idletasks()
                # Hâlâ taşan Kaydet varsa yüksekliği kıs
                if btn is not None:
                    try:
                        if btn.winfo_ismapped():
                            btn_alt = int(btn.winfo_rooty()) + int(btn.winfo_height())
                            if btn_alt > work_bottom - 2:
                                fazla = btn_alt - (work_bottom - 4)
                                yeni_h = max(400, int(self.winfo_height()) - fazla)
                                ax2, ay2, aw2, _ah2 = calisma_alani(self)
                                self.geometry(
                                    f"{min(int(self.winfo_width()), aw2)}x{yeni_h}+{ax2}+{ay2}"
                                )
                                self.update_idletasks()
                    except tk.TclError:
                        pass

            try:
                self._alt_islem_seridi.lift()
            except (tk.TclError, AttributeError):
                pass
            self.after(30, self._hareket_alanini_genislet)
        except tk.TclError:
            pass
        finally:
            self._alana_sigdir_kilit = False

    def _pencere_boyutunu_ayarla(self):
        """Kayıtlı boyut veya iş alanına sığdırılmış tam pencere; zoom taşmasını engelle."""
        from ui_pencere import calisma_alani, is_alanina_sigdir

        self._minsize_alana_gore()
        yol = self._pencere_ayar_dosyasi()
        kayit = None
        if yol.exists():
            try:
                kayit = json.loads(yol.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                kayit = None
        if kayit and kayit.get("geometry") and not kayit.get("zoomed"):
            try:
                alan = calisma_alani(self)
                self.geometry(geometriyi_alana_sigdir(str(kayit["geometry"]), alan))
            except tk.TclError:
                is_alanina_sigdir(self, maximize=False)
        else:
            # zoomed kayıt veya ilk açılış: çerçeve paylı iş alanı (zoom kullanma —
            # transient + zoom görev çubuğunun altına taşıyabiliyor)
            is_alanina_sigdir(self, maximize=False)
        self.bind("<Configure>", self._pencere_boyut_kaydet_debounce, add="+")
        self._pencere_kaydet_after = None
        self.after(80, self._pencereyi_alana_sigdir)
        self.after(250, self._pencereyi_alana_sigdir)
        self.after(600, self._pencereyi_alana_sigdir)

    def _pencere_boyut_kaydet_debounce(self, _event=None):
        # Büyüt/küçült veya taşıma sonrası iş alanına sığdır
        if _event is not None and getattr(_event, "widget", None) is self:
            if getattr(self, "_alana_sigdir_after", None):
                try:
                    self.after_cancel(self._alana_sigdir_after)
                except Exception:
                    pass
            self._alana_sigdir_after = self.after(120, self._pencereyi_alana_sigdir)
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

    def _ana_birim_secenekleri(self, *, genel: bool = True, db_izinli: bool = True) -> list[str]:
        """Kartın aktif birimleri; yeni kartta (genel=True) genel birim listesi de eklenir."""
        adlar = []
        for b in self.birimler or []:
            if isinstance(b, dict) and not b.get("aktif", True):
                continue
            ad = _birim_adi(b)
            if ad and ad not in adlar:
                adlar.append(ad)
        if genel and not self.stok:
            anahtarlar = {birim_anahtari(a) for a in adlar}
            for ad in self._genel_birimler(db_izinli=db_izinli):
                if birim_anahtari(ad) not in anahtarlar:
                    anahtarlar.add(birim_anahtari(ad))
                    adlar.append(ad)
        return adlar

    @staticmethod
    def _genel_birimler(*, db_izinli: bool = True) -> list[str]:
        """Açılışta db_izinli=False → sabit/önbellek (DB beklemez)."""
        cached = _STOK_KART_LISTE_CACHE.get("birimler")
        if cached is not None:
            return list(cached)
        if not db_izinli:
            return list(BIRIM_SECENEKLERI)
        try:
            liste = StokService.birim_listesi(BIRIM_SECENEKLERI)
            _STOK_KART_LISTE_CACHE["birimler"] = list(liste)
            return list(liste)
        except Exception:
            return list(BIRIM_SECENEKLERI)

    def _yeni_kart_ana_birimi_esitle(self, _event=None):
        """Yeni kartta ana birim değişince katsayı 1 olan ana birim kaydını yenisiyle değiştirir."""
        if self.stok or "birim" not in self.alanlar:
            return
        yeni = " ".join(self.alanlar["birim"].get().split())
        eski = self._yeni_kart_ana_birim or "Adet"
        if not yeni or birim_anahtari(yeni) == birim_anahtari(eski):
            return
        for b in self.birimler or []:
            if birim_anahtari(_birim_adi(b)) == birim_anahtari(yeni) and _birim_carpan(b) not in ("1", ""):
                messagebox.showwarning(
                    "Ana Birim",
                    f"«{_birim_adi(b)}» bu kartta alternatif birim (1 {_birim_adi(b)} = "
                    f"{_birim_carpan(b)} {eski}). Ana birim yapmak için önce alternatif birimden kaldırın.",
                    parent=self,
                )
                self.alanlar["birim"].set(eski)
                return
        self.birimler = [
            b
            for b in (self.birimler or [])
            if birim_anahtari(_birim_adi(b)) not in (birim_anahtari(eski), birim_anahtari(yeni))
        ]
        self.birimler.insert(0, _ana_birim_kaydi(yeni))
        for alan in ("varsayilan_goruntuleme_birim", "varsayilan_alis_birim", "varsayilan_satis_birim"):
            if birim_anahtari(getattr(self, alan, "")) == birim_anahtari(eski):
                setattr(self, alan, yeni)
        self._yeni_kart_ana_birim = yeni
        self.alanlar["birim"].set(yeni)
        self._barkod_birim_tablolari_yenile()
        if len(self.birimler) > 1:
            messagebox.showinfo(
                "Ana Birim",
                f"Ana birim «{yeni}» oldu. Alternatif birim katsayıları ana birime göredir; "
                "Birimler… ekranından kontrol edin.",
                parent=self,
            )

    def _yeni_birim_ekle(self):
        """Yeni Birim (+): genel listeye ekler ve karta seçer; alternatif birimde katsayı kullanıcıdan alınır."""
        ana = " ".join(self.alanlar["birim"].get().split()) or "Adet"
        dlg = YeniBirimDialog(self, ana_birim=ana, ana_secilebilir=not self.stok)
        self.wait_window(dlg)
        sonuc = dlg.result
        if not sonuc:
            return
        ad = sonuc["birim_adi"]
        if sonuc["kullanim"] == "ana":
            self.alanlar["birim"].set(ad)
            self._yeni_kart_ana_birimi_esitle()
        else:
            self.birimler = [*(self.birimler or []), {**_ana_birim_kaydi(ad), "carpan": sonuc["carpan"]}]
            self._barkod_birim_tablolari_yenile()
            for iid in self.birim_tablo.get_children():
                if (self.birim_tablo.item(iid, "values") or [""])[0] == ad:
                    self.birim_tablo.selection_set(iid)
                    self.birim_tablo.see(iid)
        self.alanlar["birim"].configure(values=self._ana_birim_secenekleri())

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

    def _stok_tur_listelerini_yukle(self):
        from database.kart_turu_service import KAPSAM_STOK, KartTuruService

        self._stok_ana_tur_map = {}
        try:
            cached = _STOK_KART_LISTE_CACHE.get("tur")
            if cached:
                analar = [type("T", (), {"ad": ad, "id": aid})() for ad, aid in cached]
            else:
                analar = KartTuruService.ana_turleri_listele(KAPSAM_STOK, sadece_aktif=True)
                _STOK_KART_LISTE_CACHE["tur"] = [(a.ad, int(a.id)) for a in analar]
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("stok kart tür listesi")
            if "ana_kart_turu" in self.alanlar:
                self.alanlar["ana_kart_turu"].configure(values=())
            if hasattr(self, "_stok_tur_uyari"):
                self._stok_tur_uyari.configure(text=f"Kart türü tanımları yüklenemedi: {exc}")
            return
        vals = []
        for a in analar:
            vals.append(a.ad)
            self._stok_ana_tur_map[a.ad] = a.id
        self.alanlar["ana_kart_turu"].configure(values=vals)
        sec_ana = None
        if self.stok and getattr(self.stok, "ana_kart_turu_id", None):
            ana = KartTuruService.ana_getir(self.stok.ana_kart_turu_id)
            if ana:
                sec_ana = ana.ad
                if ana.ad not in self._stok_ana_tur_map:
                    vals.append(ana.ad)
                    self._stok_ana_tur_map[ana.ad] = ana.id
                    self.alanlar["ana_kart_turu"].configure(values=vals)
        elif self.stok and (self.stok.kart_turu or "").strip():
            # Geçiş öncesi: eski kart_turu metninden eşle
            for ad, aid in self._stok_ana_tur_map.items():
                if ad.casefold() == (self.stok.kart_turu or "").strip().casefold():
                    sec_ana = ad
                    break
        if not sec_ana and "Ticari Mal" in self._stok_ana_tur_map:
            sec_ana = "Ticari Mal"
        elif not sec_ana and vals:
            sec_ana = vals[0]
        if sec_ana:
            self.alanlar["ana_kart_turu"].set(sec_ana)
        # Alt tür UI kaldırıldı; harita boş tutulur, kayıtta mevcut ID korunur
        self._stok_alt_tur_map = {}

    def _stok_alt_tur_doldur(self, secili_alt_id: int | None = None):
        """Geriye uyumluluk — alt tür alanı UI'da yok; no-op."""
        return

    def _stok_ana_tur_degisti(self):
        if hasattr(self, "_stok_tur_uyari"):
            self._stok_tur_uyari.configure(text="")

    def _stok_ana_tur_yonet(self):
        from kart_turleri_gruplari_ui import hizli_tanim_penceresi
        from database.kart_turu_service import KAPSAM_STOK

        def on_saved(sonuc):
            _stok_kart_liste_cache_temizle()
            self._stok_tur_listelerini_yukle()
            if getattr(sonuc, "ad", None):
                self.alanlar["ana_kart_turu"].set(sonuc.ad)
                self._stok_ana_tur_degisti()

        hizli_tanim_penceresi(self, kapsam=KAPSAM_STOK, tur="ana", on_saved=on_saved)

    def _stok_alt_tur_yonet(self):
        """Alt tür UI kaldırıldı — çağrılırsa ana tür yönetimine yönlendir."""
        self._stok_ana_tur_yonet()

    def _stok_tur_secili_idler(self) -> tuple[int | None, int | None, str]:
        """Ana tür UI'dan; alt tür eski kayıttan korunur (silinmez / zorunlu değil)."""
        ana_ad = (self.alanlar["ana_kart_turu"].get() or "").strip()
        ana_id = self._stok_ana_tur_map.get(ana_ad)
        alt_id = None
        if self.stok and getattr(self.stok, "alt_kart_turu_id", None):
            alt_id = int(self.stok.alt_kart_turu_id)
        return ana_id, alt_id, ana_ad or "Ticari Mal"

    def _sekme_yukseklik_sinirla(self, _event=None):
        """Seçili olmayan sekmeleri daralt — Notebook max-yükseklik boşluğu bırakmasın."""
        try:
            secili = self.sekmeler.select()
        except tk.TclError:
            return
        for tab_id in self.sekmeler.tabs():
            try:
                fr = self.nametowidget(tab_id)
            except tk.TclError:
                continue
            if str(tab_id) == str(secili):
                try:
                    fr.configure(height=0)
                except tk.TclError:
                    pass
                try:
                    fr.pack_propagate(True)
                except tk.TclError:
                    pass
            else:
                try:
                    fr.configure(height=1)
                    fr.pack_propagate(False)
                except tk.TclError:
                    pass
        self.update_idletasks()
        self._sash_ayarlandi = False
        self.after_idle(self._hareket_alanini_genislet)

    def _dikey_bolme_configure(self, event=None):
        """Pencere gerçek boyuta gelince sash bir kez (veya üst çöktüyse yeniden) ayarlansın."""
        if event is not None and event.widget is not self._dikey_bolme:
            return
        try:
            pw_h = int(event.height) if event is not None else self._dikey_bolme.winfo_height()
        except (tk.TclError, TypeError, ValueError):
            return
        if pw_h < 200:
            return
        try:
            sash = self._dikey_bolme.sashpos(0)
        except tk.TclError:
            sash = 0
        # İlk yerleşim veya üst pane çökmüş (sash ~0) → düzelt
        if not self._sash_ayarlandi or sash < 120:
            self._hareket_alanini_genislet()

    def _hareket_alanini_genislet(self, _event=None):
        """Üst formu seçili sekmenin ihtiyacı kadar bırak; kalanı hareketlere ver.

        after_idle sırasında pencere hâlâ 1×1 olabiliyor; o durumda sashpos
        etkisiz kalır / 0'da kalır ve yalnızca Stok Hareketleri görünür.
        Gerçek paned yüksekliği gelene kadar yeniden dener.
        """
        if getattr(self, "_kapaniyor", False):
            return
        # Map/Configure yağmurunu debounce et
        if _event is not None:
            aid = getattr(self, "_sash_debounce_after", None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
            self._sash_debounce_after = self.after(40, lambda: self._hareket_alanini_genislet())
            return
        try:
            self.update_idletasks()
            pw_h = self._dikey_bolme.winfo_height()
            dlg_h = self.winfo_height()
            if pw_h < 200 or dlg_h < 200:
                self._sash_retry += 1
                if self._sash_retry <= 40:
                    self.after(50, self._hareket_alanini_genislet)
                return
            # Seçili sekmenin gerçek ihtiyacı (+ sekme şeridi payı)
            try:
                secili = self.nametowidget(self.sekmeler.select())
                icerik_h = max(int(secili.winfo_reqheight()), 180)
            except tk.TclError:
                icerik_h = 220
            try:
                # Sekme başlık şeridi yaklaşık yüksekliği
                tab_pay = max(28, int(self.sekmeler.winfo_reqheight()) - icerik_h)
                tab_pay = min(tab_pay, 48)
            except tk.TclError:
                tab_pay = 36
            ust_req = icerik_h + tab_pay
            # Dar alanda önce Stok Hareketleri küçülür; alt Kaydet şeridi pack'te ayrı kalır
            hareket_min = 100 if pw_h < 480 else (160 if pw_h < 620 else 220)
            hedef = ust_req + 8
            hedef = max(200, min(hedef, int(pw_h * 0.55), pw_h - hareket_min))
            self._dikey_bolme.sashpos(0, hedef)
            # Doğrula — hâlâ çökmüşse bir kez daha (zoom gecikmesi)
            self.update_idletasks()
            if self._dikey_bolme.sashpos(0) < 120 and self._sash_retry < 40:
                self._sash_retry += 1
                self.after(50, self._hareket_alanini_genislet)
                return
            self._sash_ayarlandi = True
            self._sash_retry = 0
        except tk.TclError:
            self._sash_retry += 1
            if self._sash_retry <= 40:
                self.after(50, self._hareket_alanini_genislet)

    def _grup_listelerini_yukle(self, *, ilk: bool = False):
        from database.stok_grup_service import SEVIYE_ANA, StokGrupService

        try:
            cached = _STOK_KART_LISTE_CACHE.get("grup_ana")
            if cached:
                ana_liste = [
                    {"id": g["id"], "etiket": g["etiket"], "aktif": g.get("aktif", True)}
                    for g in cached
                ]
            else:
                ana_liste = StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True)
                _STOK_KART_LISTE_CACHE["grup_ana"] = [
                    {
                        "id": g["id"],
                        "etiket": g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}",
                        "aktif": bool(g.get("aktif", True)),
                    }
                    for g in ana_liste
                ]
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
            try:
                self.grup_pasif_lbl.grid_remove()
            except tk.TclError:
                pass
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
                        self.grup_pasif_lbl.grid(
                            row=1, column=0, columnspan=12, sticky="w", padx=4
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
        if dlg.result:
            _STOK_KART_LISTE_CACHE["grup_ana"] = None
            self._grup_sonucu_uygula(dlg.result)

    def _grup_yeni_ekle(self, anahtar: str):
        """Seviye düğmesi: Ana üstsüz; Tali seçili Ana'ya, Alt seçili Tali'ye bağlı açılır."""
        from database.stok_grup_service import SEVIYE_ALT, SEVIYE_ANA, SEVIYE_TALI
        from stok_grup_ui import StokGrupDialog

        if anahtar == "ana":
            seviye, parent_id = SEVIYE_ANA, None
        elif anahtar == "tali":
            seviye, parent_id = SEVIYE_TALI, self._grup_secili_id("ana")
            if not parent_id:
                messagebox.showwarning("Tali Grup", "Önce bir Ana Grup seçin.", parent=self)
                return
        else:
            seviye, parent_id = SEVIYE_ALT, self._grup_secili_id("tali")
            if not parent_id:
                messagebox.showwarning("Alt Grup", "Önce bir Tali Grup seçin.", parent=self)
                return
        dlg = StokGrupDialog(self, seviye=seviye, parent_id=parent_id, seviye_sabit=True)
        self.wait_window(dlg)
        if dlg.result:
            _STOK_KART_LISTE_CACHE["grup_ana"] = None
            self._grup_sonucu_uygula(dlg.result)

    def _grup_sonucu_uygula(self, g: dict):
        from database.stok_grup_service import SEVIYE_ALT, SEVIYE_ANA, SEVIYE_TALI

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

    def _durum_ozeti(self) -> str:
        """Kaydedilmemiş değişiklik karşılaştırması için formun anlık görüntüsü."""

        def _deger(w):
            try:
                return (w.get() or "").strip()
            except (tk.TclError, AttributeError):
                return ""

        self._muhasebe_sekmeden_oku()
        self._resimler_sekmeden_oku()
        aciklama = (
            self.aciklama_alani.get("1.0", "end").strip()
            if hasattr(self, "aciklama_alani")
            else (self.aciklama or "")
        )
        return json.dumps(
            {
                "alan": {k: _deger(w) for k, w in self.alanlar.items()},
                "fiyat": {k: _deger(w) for k, w in self.fiyat_alanlari.items()},
                "fiyat_kdv": {k: _deger(w) for k, w in getattr(self, "fiyat_kdv_alanlari", {}).items()},
                "iskonto": {k: _deger(w) for k, w in self.iskonto_alanlari.items()},
                "grup": {k: _deger(w) for k, w in getattr(self, "grup_alanlari", {}).items()},
                "aciklama": aciklama,
                "birimler": self.birimler,
                "barkodlar": self.barkodlar,
                "resimler": self.resimler,
                "muhasebe": self.muhasebe,
                "varsayilan": [
                    self.varsayilan_goruntuleme_birim,
                    self.varsayilan_alis_birim,
                    self.varsayilan_satis_birim,
                ],
            },
            default=str,
            sort_keys=True,
            ensure_ascii=False,
        )

    def _degisti_mi(self) -> bool:
        return self._durum_ozeti() != getattr(self, "_ilk_durum", None)

    def _kaydedilmemis_onay(self) -> bool:
        """Değişiklik yoksa True; varsa Kaydet / Kaydetmeden devam / İptal sorar."""
        if hasattr(self, "aciklama_alani"):
            self.aciklama = self.aciklama_alani.get("1.0", "end").strip()
        if not self._degisti_mi():
            return True
        cevap = messagebox.askyesnocancel(
            "Stok kartı",
            "Kaydedilmemiş değişiklikler var. Kaydedilsin mi?\n\n"
            "Evet = Kaydet  |  Hayır = Kaydetmeden devam  |  İptal = Kartta kal",
            parent=self,
        )
        if cevap is None:
            return False
        if cevap:
            return bool(self.kaydet())
        return True

    def _kapat_istegi(self):
        self._pencere_boyut_kaydet()
        if self._kaydedilmemis_onay():
            self._kapaniyor = True
            # Gecikmiş arka plan sonuçlarının yeni karta yazılmasını engelle
            self._ozet_token = int(getattr(self, "_ozet_token", 0) or 0) + 1
            self._depo_token = int(getattr(self, "_depo_token", 0) or 0) + 1
            self._hareket_yukle_token = int(getattr(self, "_hareket_yukle_token", 0) or 0) + 1
            self._hrk_doldur_token = int(getattr(self, "_hrk_doldur_token", 0) or 0) + 1
            self._alis_fiyat_token = int(getattr(self, "_alis_fiyat_token", 0) or 0) + 1
            self.destroy()

    def _karti_degistir(self, stok=None) -> bool:
        """Bu pencereyi kapatıp verilen stoğu (None → boş yeni kart) temiz bir kartta açar."""
        if not self._kaydedilmemis_onay():
            return False
        parent = self.master
        self._pencere_boyut_kaydet()
        self._kapaniyor = True
        self._ozet_token = int(getattr(self, "_ozet_token", 0) or 0) + 1
        self._depo_token = int(getattr(self, "_depo_token", 0) or 0) + 1
        self._hareket_yukle_token = int(getattr(self, "_hareket_yukle_token", 0) or 0) + 1
        self._hrk_doldur_token = int(getattr(self, "_hrk_doldur_token", 0) or 0) + 1
        self._alis_fiyat_token = int(getattr(self, "_alis_fiyat_token", 0) or 0) + 1
        self.destroy()
        StokKartiDialog(
            parent,
            stok,
            rapor_grubu_zorunlu=self.rapor_grubu_zorunlu,
            on_saved=self._on_saved,
        )
        return True

    def _yeni_kart(self):
        self._karti_degistir(None)

    def stok_alan_yeni(self, alan):
        if self.stok:
            # Mevcut kartta "Yeni" bu kartı yeniden adlandırmaz; boş yeni kart açar
            self._yeni_kart()
            return
        if alan == "stok_kodu":
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
        self._kod_yazilan = metin
        bulunan = StokService.stok_kodu_onerileri(metin)
        self._stok_kod_eslesme = {_stok_secim_etiketi(s): s for s in bulunan}
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
        if metin in self._stok_ad_eslesme:
            return
        if len(metin) < 2:
            self.alanlar["stok_adi"]["values"] = ()
            self._stok_ad_eslesme = {}
            return
        self._ad_yazilan = metin
        bulunan = StokService.stok_adi_onerileri(metin, min_harf=2)
        self._stok_ad_eslesme = {_stok_secim_etiketi(s): s for s in bulunan}
        self.alanlar["stok_adi"]["values"] = tuple(self._stok_ad_eslesme.keys())

    def _stok_secimini_ac(self, alan: str, eslesme: dict, yazilan: str):
        """Öneriden seçilen stoğu kendi kartında açar.

        Arama metni mevcut kartın adı/kodu olarak kaydedilmesin diye alan önce geri alınır:
        mevcut kartta kayıtlı değere, yeni kartta kullanıcının yazdığı metne.
        """
        stok = eslesme.get(self.alanlar[alan].get().strip())
        if not stok:
            return
        self.alanlar[alan].set((getattr(self.stok, alan, None) or "") if self.stok else yazilan)
        if self.stok and stok.id == self.stok.id:
            return
        self._karti_degistir(stok)

    def _stok_listeden_secildi(self, stok):
        """Ad kutusunun açılır listesinden seçilen stoğu kendi kartında açar."""
        alan = self.alanlar["stok_adi"]
        yazilan = alan.get()
        alan.set((getattr(self.stok, "stok_adi", None) or "") if self.stok else "")
        if self.stok and stok.id == self.stok.id:
            return
        if not self._karti_degistir(stok):
            alan.set(yazilan)

    def _stok_kodu_secildi(self, _event=None):
        self._stok_secimini_ac("stok_kodu", self._stok_kod_eslesme, getattr(self, "_kod_yazilan", ""))

    def _stok_adi_secildi(self, _event=None):
        self._stok_secimini_ac("stok_adi", self._stok_ad_eslesme, getattr(self, "_ad_yazilan", ""))

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

    def _yerine_koyma_raporu_ac(self):
        parent = self.master if self.master is not None else self
        try:
            from stok_raporlari_ui import yatirim_verimliligi_goster

            yatirim_verimliligi_goster(parent)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Yerine Koyma", str(exc), parent=self)

    def _fiyat_metni_tr(self, tutar) -> str:
        """Türkçe ondalık; hassasiyet korunur (trailing sıfırlar kırpılır)."""
        if tutar is None or str(tutar).strip() == "":
            return ""
        try:
            d = Decimal(str(tutar).replace(",", "."))
        except Exception:
            return str(tutar)
        s = f"{d:f}".rstrip("0").rstrip(".")
        if "." in s:
            tam, kes = s.split(".", 1)
            return f"{tam},{kes}"
        return s

    def _satis_tablosunu_kur(self, kodlar: list[str]):
        """Satış fiyatı satırlarını (yeniden) oluşturur; mevcut tutarları korumaya çalışır."""
        onceki_tutar = {}
        onceki_kdv = {}
        onceki_hesap = {}
        for kod, giris in list((getattr(self, "fiyat_alanlari", None) or {}).items()):
            if kod in (getattr(self, "_satis_fiyat_kodlari", None) or []) or (
                str(kod).upper().startswith("SATIŞ FİYATI")
            ):
                try:
                    onceki_tutar[kod] = giris.get().strip()
                except Exception:
                    pass
        for kod, sec in list((getattr(self, "fiyat_kdv_alanlari", None) or {}).items()):
            try:
                onceki_kdv[kod] = sec.get()
            except Exception:
                pass
        for kod, h in list((getattr(self, "fiyat_hesap_alanlari", None) or {}).items()):
            try:
                onceki_hesap[kod] = {
                    "modu": h["modu"].get(),
                    "iskonto": h["iskonto"].get().strip(),
                }
            except Exception:
                pass
        # Eski satış widget'larını temizle
        for kod in list(getattr(self, "_satis_fiyat_kodlari", []) or []):
            self.fiyat_alanlari.pop(kod, None)
            self.fiyat_kdv_alanlari.pop(kod, None)
            self.fiyat_hesap_alanlari.pop(kod, None)
        for child in list(self._satis_ic.winfo_children()):
            # başlık satırını koru (ilk child)
            if getattr(child, "_satis_baslik", False):
                continue
            # başlık frame ilk pack edilen; yeniden kurarken hepsini silip başlığı tekrar ekle
            child.destroy()
        # Başlık yeniden
        for child in list(self._satis_ic.winfo_children()):
            child.destroy()
        baslik_satir = tk.Frame(self._satis_ic, bg="#E8F5E9")
        baslik_satir._satis_baslik = True  # type: ignore[attr-defined]
        baslik_satir.pack(fill="x", pady=(0, 2))
        for metin, w in (
            ("Liste", 18),
            ("Hesaplama", 16),
            ("İsk. %", 7),
            ("Satış fiyatı", 12),
            ("KDV", 12),
        ):
            tk.Label(
                baslik_satir,
                text=metin,
                bg="#E8F5E9",
                fg=_SATIS_ETIKET_FG,
                font=sktema.font(8, "bold", root=self),
                width=w,
                anchor="w",
            ).pack(side="left", padx=2)

        self._satis_fiyat_kodlari = list(kodlar)
        self.fiyat_hesap_alanlari = {}
        _HESAP_SECENEK = ("Manuel", "Liste Fiyatına Bağlı")
        for kod in kodlar:
            satir = tk.Frame(self._satis_ic, bg=BEYAZ)
            satir.pack(fill="x", pady=1)
            self._satis_satir_frame[kod] = satir
            gorunen = satis_fiyat_gorunen_ad(kod) or kod
            tk.Label(
                satir,
                text=gorunen,
                bg=BEYAZ,
                fg=_SATIS_ETIKET_FG,
                font=sktema.font(9, "bold", root=self),
                width=18,
                anchor="w",
            ).pack(side="left", padx=2)
            modu = ttk.Combobox(satir, values=_HESAP_SECENEK, width=16, state="readonly")
            modu.set(_HESAP_SECENEK[0])
            modu.pack(side="left", padx=2)
            isk = ttk.Entry(satir, width=7)
            isk.pack(side="left", padx=2)
            giris = ttk.Entry(satir, width=12)
            giris.pack(side="left", padx=2)
            kdv_sec = ttk.Combobox(
                satir, values=FIYAT_KDV_SECENEKLERI, width=12, state="readonly"
            )
            kdv_sec.set(onceki_kdv.get(kod) or FIYAT_KDV_SECENEKLERI[0])
            kdv_sec.pack(side="left", padx=2)
            self.fiyat_alanlari[kod] = giris
            self.fiyat_kdv_alanlari[kod] = kdv_sec
            self.fiyat_hesap_alanlari[kod] = {"modu": modu, "iskonto": isk, "satir": satir}
            if kod in onceki_tutar and onceki_tutar[kod]:
                giris.insert(0, onceki_tutar[kod])
            if kod in onceki_hesap:
                h = onceki_hesap[kod]
                if h.get("modu"):
                    modu.set(h["modu"])
                if h.get("iskonto"):
                    isk.insert(0, h["iskonto"])
            modu.bind(
                "<<ComboboxSelected>>",
                lambda _e, k=kod: self._satis_modu_degisti(k),
            )
            isk.bind("<KeyRelease>", lambda _e, k=kod: self._satis_bagli_fiyatlari_guncelle(k))
            isk.bind("<FocusOut>", lambda _e, k=kod: self._satis_bagli_fiyatlari_guncelle(k))
            giris.bind("<KeyRelease>", lambda _e, k=kod: self._satis_manuel_fiyat_duzenlendi(k))
            self._satis_modu_degisti(kod, onizleme=False)

    def _satis_modu_metin_kod(self, metin: str) -> str:
        return "LISTE" if (metin or "").strip().startswith("Liste") else "MANUEL"

    def _satis_modu_kod_metin(self, kod: str) -> str:
        return "Liste Fiyatına Bağlı" if (kod or "").upper() == "LISTE" else "Manuel"

    def _satis_modu_degisti(self, fiyat_kodu: str, *, onizleme: bool = True):
        h = (self.fiyat_hesap_alanlari or {}).get(fiyat_kodu)
        if not h:
            return
        liste_mi = self._satis_modu_metin_kod(h["modu"].get()) == "LISTE"
        satir = h.get("satir")
        bg = "#FFF8E1" if liste_mi else BEYAZ
        if satir is not None:
            try:
                satir.configure(bg=bg)
                for ch in satir.winfo_children():
                    if isinstance(ch, tk.Label):
                        ch.configure(bg=bg)
            except tk.TclError:
                pass
        try:
            h["iskonto"].configure(state="normal" if liste_mi else "disabled")
        except tk.TclError:
            pass
        giris = self.fiyat_alanlari.get(fiyat_kodu)
        if giris is not None:
            try:
                giris.configure(state="readonly" if liste_mi else "normal")
            except tk.TclError:
                pass
        if onizleme and liste_mi:
            self._satis_bagli_fiyatlari_guncelle(fiyat_kodu)

    def _satis_manuel_fiyat_duzenlendi(self, fiyat_kodu: str):
        h = (self.fiyat_hesap_alanlari or {}).get(fiyat_kodu)
        if not h:
            return
        if self._satis_modu_metin_kod(h["modu"].get()) == "LISTE":
            # Readonly iken gelmemeli; yine de Manuel'e çek
            h["modu"].set("Manuel")
            self._satis_modu_degisti(fiyat_kodu, onizleme=False)

    def _satis_bagli_fiyatlari_guncelle(self, sadece_kod: str | None = None):
        """Liste fiyatı / satış iskontosu değişince bağlı satış fiyatlarını güncelle."""
        from database.satis_fiyat_listesi_service import liste_bagli_satis_fiyati

        liste = ""
        if "LİSTE FİYATI" in self.fiyat_alanlari:
            liste = self.fiyat_alanlari["LİSTE FİYATI"].get().strip()
        uyarilar = []
        hedefler = (
            [sadece_kod]
            if sadece_kod
            else list((self.fiyat_hesap_alanlari or {}).keys())
        )
        for kod in hedefler:
            if not kod:
                continue
            h = (self.fiyat_hesap_alanlari or {}).get(kod)
            if not h:
                continue
            if self._satis_modu_metin_kod(h["modu"].get()) != "LISTE":
                continue
            gorunen = satis_fiyat_gorunen_ad(kod) or kod
            if not liste:
                uyarilar.append(f"{gorunen}: Liste Fiyatı boş")
                self._fiyat_yaz(kod, "")
                continue
            try:
                hesap = liste_bagli_satis_fiyati(liste, h["iskonto"].get())
            except ValueError as exc:
                uyarilar.append(f"{gorunen}: {exc}")
                self._fiyat_yaz(kod, "")
                continue
            self._fiyat_yaz(kod, self._fiyat_metni_tr(hesap))
        if self._satis_uyari_lbl is not None:
            self._satis_uyari_lbl.configure(
                text=(" · ".join(uyarilar[:3]) if uyarilar else "")
            )

    def _fiyat_listelerini_yonet(self):
        from database.satis_fiyat_listesi_service import SatisFiyatListesiService

        try:
            SatisFiyatListesiService.ensure_schema()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Fiyat listeleri", str(exc), parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Fiyat Listelerini Yönet")
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("560x420")
        ttk.Label(
            dlg,
            text="Liste adı firma genelinde ortaktır. Kimlik (kod) değişmez; stok fiyatları ve cari bağlantıları korunur.",
            wraplength=520,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        tablo_cer = tk.Frame(dlg)
        tablo_cer.pack(fill="both", expand=True, padx=10, pady=4)
        tree = ttk.Treeview(
            tablo_cer,
            columns=("kod", "ad", "sira", "durum"),
            show="headings",
            selectmode="browse",
            height=12,
        )
        for c, b, w in (
            ("kod", "Kod (kimlik)", 140),
            ("ad", "Görünen ad", 200),
            ("sira", "Sıra", 50),
            ("durum", "Durum", 70),
        ):
            tree.heading(c, text=b)
            tree.column(c, width=w, anchor="w" if c != "sira" else "center")
        sb = ttk.Scrollbar(tablo_cer, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.tag_configure("pasif", foreground="#9CA3AF")

        def yenile():
            tree.delete(*tree.get_children())
            for r in SatisFiyatListesiService.listele(aktif_only=False):
                tree.insert(
                    "",
                    "end",
                    iid=r["kod"],
                    values=(
                        r["kod"],
                        r["ad"],
                        r["sira_no"],
                        "Aktif" if r["aktif"] else "Pasif",
                    ),
                    tags=(() if r["aktif"] else ("pasif",)),
                )

        def secili_kod():
            sec = tree.selection()
            return sec[0] if sec else None

        def ekle():
            ad = simpledialog.askstring("Yeni liste", "Liste adı:", parent=dlg)
            if not ad:
                return
            try:
                SatisFiyatListesiService.ekle(ad)
            except ValueError as exc:
                messagebox.showerror("Yeni liste", str(exc), parent=dlg)
                return
            yenile()

        def yeniden_adlandir():
            kod = secili_kod()
            if not kod:
                return
            mevcut = tree.set(kod, "ad")
            ad = simpledialog.askstring(
                "Yeniden adlandır",
                f"«{kod}» için yeni görünen ad:\n(Kimlik ve fiyat bağlantıları değişmez)",
                initialvalue=mevcut,
                parent=dlg,
            )
            if not ad:
                return
            try:
                SatisFiyatListesiService.yeniden_adlandir(kod, ad)
            except ValueError as exc:
                messagebox.showerror("Yeniden adlandır", str(exc), parent=dlg)
                return
            yenile()

        def kaldir():
            kod = secili_kod()
            if not kod:
                return
            bagli = SatisFiyatListesiService.bagli_cariler(kod)
            stok_adet = SatisFiyatListesiService.stok_fiyat_adet(kod)
            ad = tree.set(kod, "ad")
            if bagli or stok_adet:
                cari_ozet = ", ".join(
                    f"{c.get('kod')} {c.get('unvan')}" for c in bagli[:5]
                )
                if len(bagli) > 5:
                    cari_ozet += f" … (+{len(bagli) - 5})"
                msg = (
                    f"«{ad}» ({kod}) silinemez; geçmiş/bağlantılar bozulmasın diye "
                    f"pasife alınacak.\n\n"
                    f"Bağlı müşteri: {len(bagli)}"
                    + (f"\n{cari_ozet}" if cari_ozet else "")
                    + f"\nStok fiyat kaydı: {stok_adet}\n\n"
                    "Pasife alınan liste fiyat seçiminde görünmez. "
                    "Bağlı müşteriler için başka aktif liste seçin."
                )
                if not messagebox.askyesno("Listeyi kullanımdan kaldır", msg, parent=dlg):
                    return
                if bagli:
                    aktifler = [
                        r
                        for r in SatisFiyatListesiService.listele(aktif_only=True)
                        if r["kod"] != kod
                    ]
                    if not aktifler:
                        messagebox.showwarning(
                            "Liste",
                            "Başka aktif liste yok; önce yeni liste ekleyin.",
                            parent=dlg,
                        )
                        return
                    secenek = "\n".join(f"{r['kod']} — {r['ad']}" for r in aktifler[:12])
                    hedef = simpledialog.askstring(
                        "Müşteri listesi değiştir",
                        "Bağlı müşteriler için yeni aktif liste kodu girin:\n" + secenek,
                        initialvalue=aktifler[0]["kod"],
                        parent=dlg,
                    )
                    if not hedef:
                        return
                    try:
                        for c in bagli:
                            SatisFiyatListesiService.cari_liste_degistir(c["id"], hedef)
                    except ValueError as exc:
                        messagebox.showerror("Cari güncelleme", str(exc), parent=dlg)
                        return
                try:
                    SatisFiyatListesiService.pasife_al(kod)
                except ValueError as exc:
                    messagebox.showerror("Pasife al", str(exc), parent=dlg)
                    return
            else:
                if not messagebox.askyesno(
                    "Listeyi sil",
                    f"«{ad}» ({kod}) hiçbir cari/stokta kullanılmıyor.\nKalıcı silinsin mi?",
                    parent=dlg,
                ):
                    return
                try:
                    SatisFiyatListesiService.sil(kod, zorla_pasif=False)
                except ValueError as exc:
                    messagebox.showerror("Sil", str(exc), parent=dlg)
                    return
            yenile()

        def aktifle():
            kod = secili_kod()
            if not kod:
                return
            try:
                SatisFiyatListesiService.aktifle(kod)
            except ValueError as exc:
                messagebox.showerror("Aktifleştir", str(exc), parent=dlg)
                return
            yenile()

        def tasi(yon: int):
            kod = secili_kod()
            if not kod:
                return
            sirali = [tree.item(i)["values"][0] for i in tree.get_children()]
            try:
                idx = sirali.index(kod)
            except ValueError:
                return
            yeni = idx + yon
            if yeni < 0 or yeni >= len(sirali):
                return
            sirali[idx], sirali[yeni] = sirali[yeni], sirali[idx]
            SatisFiyatListesiService.sira_ayarla(sirali)
            yenile()
            tree.selection_set(kod)
            tree.see(kod)

        btn = tk.Frame(dlg)
        btn.pack(fill="x", padx=10, pady=8)
        ttk.Button(btn, text="Ekle", command=ekle).pack(side="left")
        ttk.Button(btn, text="Yeniden Adlandır", command=yeniden_adlandir).pack(
            side="left", padx=4
        )
        ttk.Button(btn, text="Kullanımdan Kaldır / Sil", command=kaldir).pack(
            side="left", padx=4
        )
        ttk.Button(btn, text="Aktifleştir", command=aktifle).pack(side="left", padx=4)
        ttk.Button(btn, text="▲", width=3, command=lambda: tasi(-1)).pack(side="left", padx=4)
        ttk.Button(btn, text="▼", width=3, command=lambda: tasi(1)).pack(side="left")
        ttk.Button(btn, text="Kapat", command=dlg.destroy).pack(side="right")

        yenile()
        dlg.wait_window()
        # Stok kartı satış tablosunu güncel aktif listelerle yenile
        try:
            kodlar = list(aktif_satis_fiyat_kodlari())
        except Exception:
            kodlar = list(SATIS_FIYAT_ADLARI)
        self._satis_tablosunu_kur(kodlar)
        if self.stok:
            for fiyat in self.stok.fiyatlar or []:
                if fiyat.fiyat_adi in self.fiyat_alanlari:
                    if not self.fiyat_alanlari[fiyat.fiyat_adi].get():
                        self._fiyat_yaz(fiyat.fiyat_adi, self._fiyat_metni_tr(fiyat.tutar))
                    h = self.fiyat_hesap_alanlari.get(fiyat.fiyat_adi)
                    if h:
                        h["modu"].set(
                            self._satis_modu_kod_metin(
                                getattr(fiyat, "hesaplama_modu", None) or "MANUEL"
                            )
                        )
                        h["iskonto"].delete(0, "end")
                        isk = getattr(fiyat, "satis_iskonto", None)
                        if isk is not None and Decimal(str(isk)) != 0:
                            h["iskonto"].insert(0, self._fiyat_metni_tr(isk))
                        self._satis_modu_degisti(fiyat.fiyat_adi, onizleme=False)
        self._satis_bagli_fiyatlari_guncelle()

    def _fabrika_fiyati_guncelle(self, _event=None):
        liste = self.fiyat_alanlari["LİSTE FİYATI"].get().strip()
        if not liste:
            self._fiyat_yaz("FABRİKA FİYATI", "")
            self._satis_bagli_fiyatlari_guncelle()
            return
        try:
            fabrika = fabrika_fiyati_hesapla(
                liste,
                self.iskonto_alanlari["iskonto_1"].get(),
                self.iskonto_alanlari["iskonto_2"].get(),
                self.iskonto_alanlari["iskonto_3"].get(),
            )
        except ValueError:
            self._satis_bagli_fiyatlari_guncelle()
            return
        metin = self._fiyat_metni_tr(fabrika)
        self._fiyat_yaz("FABRİKA FİYATI", metin)
        self._satis_bagli_fiyatlari_guncelle()

    def _kart_acilista_ikincil_yukle(self):
        """İlk boyamadan sonra tür/grup; son alış/özet arka planda — usable yolu temiz kalır."""
        if getattr(self, "_kapaniyor", False):
            return
        from ui_bg import arka_planda

        # after_idle içinde ağır sync yok; 1 ms sonra (cache varsa çok kısa) doldur
        self._tur_grup_yukleniyor = True
        self.after(1, self._tur_grup_depo_listelerini_doldur)

        if self.stok and "ALIŞ FİYATI" in getattr(self, "fiyat_alanlari", {}):
            stok_id = int(self.stok.id)
            kod = (self.stok.stok_kodu or "").strip()
            alis_token = int(getattr(self, "_alis_fiyat_token", 0) or 0) + 1
            self._alis_fiyat_token = alis_token

            def _alis_is():
                return StokService.son_alis_faturasi_net(stok_kodu=kod, stok_id=stok_id)

            def _alis_ok(son_net):
                if alis_token != getattr(self, "_alis_fiyat_token", 0) or getattr(self, "_kapaniyor", False):
                    return
                if son_net is not None:
                    self._fiyat_yaz("ALIŞ FİYATI", self._fiyat_metni_tr(son_net))
                else:
                    w = self.fiyat_alanlari.get("ALIŞ FİYATI")
                    if w and (w.get() or "").strip() in ("…", "..."):
                        self._fiyat_yaz("ALIŞ FİYATI", "")
                self._fabrika_fiyati_guncelle()

            def _alis_err(_exc):
                if alis_token != getattr(self, "_alis_fiyat_token", 0):
                    return
                w = self.fiyat_alanlari.get("ALIŞ FİYATI")
                if w and (w.get() or "").strip() in ("…", "..."):
                    self._fiyat_yaz("ALIŞ FİYATI", "")

            arka_planda(self, _alis_is, on_ok=_alis_ok, on_err=_alis_err)
        self._ozeti_yenile_arka()
        self._depo_tablosu_yenile_arka()

    def _tur_grup_depo_listelerini_doldur(self):
        """Tür/grup/depo combobox — usable boyama sonrası; süreç önbelleği ile hızlanır."""
        if getattr(self, "_kapaniyor", False):
            return
        try:
            self._stok_tur_listelerini_yukle()
        except Exception:
            pass
        bek_tur = getattr(self, "_bekleyen_baslangic_kart_turu", None)
        if bek_tur and "ana_kart_turu" in self.alanlar:
            if bek_tur in getattr(self, "_stok_ana_tur_map", {}):
                self.alanlar["ana_kart_turu"].set(bek_tur)
                self._stok_ana_tur_degisti()
            self._bekleyen_baslangic_kart_turu = None
        try:
            self._grup_listelerini_yukle(ilk=True)
        except Exception:
            pass
        try:
            kayit = _STOK_KART_LISTE_CACHE.get("depolar")
            if kayit is None:
                ham_d = list(StokService.depolar(aktif_only=False))
                kayit = [
                    {"ad": d.ad, "aktif": bool(getattr(d, "aktif", True))}
                    for d in ham_d
                ]
                _STOK_KART_LISTE_CACHE["depolar"] = kayit
                self._depo_listesi_cache = ham_d
            depolar_ad = [d["ad"] for d in kayit if d.get("aktif")]
            if hasattr(self, "hrk_depo_cb"):
                self.hrk_depo_cb.configure(values=["(Tümü)", *depolar_ad])
        except Exception:
            pass
        self._tur_grup_yukleniyor = False
        try:
            self._ilk_durum = self._durum_ozeti()
        except Exception:
            pass

    def _ozet_yer_tutucu(self):
        """Henüz hesaplanmamış özet — sıfır yazılmaz."""
        def _depo_yaz(widget, metin: str):
            if isinstance(widget, ttk.Entry):
                widget.configure(state="normal")
                widget.delete(0, "end")
                widget.insert(0, metin)
                widget.configure(state="readonly")
            else:
                widget.configure(text=metin)

        if not self.stok:
            for etiket in getattr(self, "ozet_etiketleri", {}).values():
                etiket.configure(text="0")
            for lbl in getattr(self, "_panel_depo_lbl", {}).values():
                _depo_yaz(lbl, "—")
            return
        for etiket in getattr(self, "ozet_etiketleri", {}).values():
            etiket.configure(text="…")
        for lbl in getattr(self, "_panel_depo_lbl", {}).values():
            _depo_yaz(lbl, "…")
        if hasattr(self, "depo_ozet_detay"):
            self.depo_ozet_detay.configure(text="Envanter özeti hesaplanıyor…")

    def _ozet_verisi_hesapla(self) -> dict:
        """stok_ozeti + birim dönüşümü — UI thread veya arka plan worker'da çağrılabilir."""
        stok_id = int(self.stok.id)
        ana_birim = (
            (self.alanlar.get("birim").get().strip() if self.alanlar.get("birim") else "")
            or (self.stok.birim if self.stok else "")
            or "Adet"
        )
        gosterim = (
            (getattr(self, "varsayilan_goruntuleme_birim", None) or "").strip()
            or ana_birim
        )
        birimler = list(getattr(self, "birimler", None) or [])
        ozet = StokService.stok_ozeti(stok_id)

        def _birime_cevir(miktar):
            m = Decimal(str(miktar or 0))
            if gosterim.casefold() == ana_birim.casefold():
                return m
            try:
                o = StokService.birim_donusum_onizleme(
                    m, ana_birim, gosterim, birimler, ana_birim
                )
                return Decimal(str(o.get("hedef_miktar") or m))
            except Exception:
                return m

        giris_m = _birime_cevir(ozet["toplam_giris"])
        cikis_m = _birime_cevir(ozet["toplam_cikis"])
        kalan_m = _birime_cevir(ozet["kalan"])
        if kalan_m != giris_m - cikis_m:
            kalan_m = giris_m - cikis_m
        return {
            "giris_m": giris_m,
            "cikis_m": cikis_m,
            "kalan_m": kalan_m,
            "fifo": ozet["fifo_deger"],
            "gosterim": gosterim,
        }

    def _ozeti_yenile_arka(self):
        if getattr(self, "_kapaniyor", False):
            return
        if not self.stok:
            self._ozeti_yenile()
            return
        from ui_bg import arka_planda

        self._ozet_token = int(getattr(self, "_ozet_token", 0) or 0) + 1
        token = self._ozet_token
        # Worker'a yalnızca id/birim kopyası — self Tk'ye dokunulmaz
        stok_id = int(self.stok.id)
        ana_birim = (
            (self.alanlar.get("birim").get().strip() if self.alanlar.get("birim") else "")
            or (self.stok.birim if self.stok else "")
            or "Adet"
        )
        gosterim = (
            (getattr(self, "varsayilan_goruntuleme_birim", None) or "").strip()
            or ana_birim
        )
        birimler = list(getattr(self, "birimler", None) or [])

        def _is():
            ozet = StokService.stok_ozeti(stok_id)

            def _birime_cevir(miktar):
                m = Decimal(str(miktar or 0))
                if gosterim.casefold() == ana_birim.casefold():
                    return m
                try:
                    o = StokService.birim_donusum_onizleme(
                        m, ana_birim, gosterim, birimler, ana_birim
                    )
                    return Decimal(str(o.get("hedef_miktar") or m))
                except Exception:
                    return m

            giris_m = _birime_cevir(ozet["toplam_giris"])
            cikis_m = _birime_cevir(ozet["toplam_cikis"])
            kalan_m = _birime_cevir(ozet["kalan"])
            if kalan_m != giris_m - cikis_m:
                kalan_m = giris_m - cikis_m
            return {
                "giris_m": giris_m,
                "cikis_m": cikis_m,
                "kalan_m": kalan_m,
                "fifo": ozet["fifo_deger"],
                "gosterim": gosterim,
            }

        def _ok(veri):
            if token != getattr(self, "_ozet_token", 0) or getattr(self, "_kapaniyor", False):
                return
            self._ozeti_uygula(veri)
            self._ozet_acilista_yuklendi = True

        def _err(_exc):
            if token != getattr(self, "_ozet_token", 0):
                return
            if hasattr(self, "depo_ozet_detay"):
                self.depo_ozet_detay.configure(text="Envanter özeti yüklenemedi.")

        arka_planda(self, _is, on_ok=_ok, on_err=_err)

    def _ozeti_uygula(self, veri: dict):
        def _fmt_miktar(v):
            return (
                f"{Decimal(str(v or 0)):,.4f}".rstrip("0").rstrip(".")
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

        def _depo_yaz(widget, metin: str):
            if isinstance(widget, ttk.Entry):
                widget.configure(state="normal")
                widget.delete(0, "end")
                widget.insert(0, metin)
                widget.configure(state="readonly")
            else:
                widget.configure(text=metin)

        gosterim = veri.get("gosterim") or "Adet"
        giris = f"{_fmt_miktar(veri['giris_m'])} {gosterim}"
        cikis = f"{_fmt_miktar(veri['cikis_m'])} {gosterim}"
        kalan = f"{_fmt_miktar(veri['kalan_m'])} {gosterim}"
        fifo = para_goster(veri["fifo"])
        for baslik, metin in (
            ("Toplam Giriş", giris),
            ("Toplam Çıkış", cikis),
            ("Kalan Miktar", kalan),
            ("FIFO Envanter Değeri", fifo),
        ):
            if baslik in getattr(self, "ozet_etiketleri", {}):
                self.ozet_etiketleri[baslik].configure(text=metin)
        panel_deger = {
            "Toplam Giriş": giris,
            "Toplam Çıkış": cikis,
            "Kalan Miktar": kalan,
            "FIFO Envanter Değeri": fifo,
        }
        for anahtar, lbl in getattr(self, "_panel_depo_lbl", {}).items():
            _depo_yaz(lbl, panel_deger.get(anahtar, "—"))
        if hasattr(self, "depo_ozet_detay"):
            raf = ""
            try:
                raf = self.alanlar["raf_yeri"].get().strip() or "—"
            except Exception:
                raf = "—"
            self.depo_ozet_detay.configure(
                text=(
                    f"Kalan (tüm depolar toplamı): {kalan}\n"
                    f"Depo bazlı kullanılabilir miktar üstteki tabloda.\n"
                    f"Toplam giriş: {giris}\n"
                    f"Toplam çıkış: {cikis}\n"
                    f"FIFO envanter değeri: {fifo}\n\n"
                    f"Raf yeri: {raf}"
                )
            )

    def _ozeti_yenile(self):
        """Senkron özet (kayıt sonrası / test). Açılışta _ozeti_yenile_arka kullanılır."""
        if not self.stok:
            self._ozet_yer_tutucu()
            for etiket in getattr(self, "ozet_etiketleri", {}).values():
                etiket.configure(text="0")
            if hasattr(self, "depo_ozet_detay"):
                self.depo_ozet_detay.configure(
                    text="Kart kaydedildikten sonra envanter özeti burada görünür."
                )
            return
        self._ozeti_uygula(self._ozet_verisi_hesapla())

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

    def _stok_uyari_ayari_ac(self):
        """Stok uyarısı ürün/depo ayarı (minimum, hedef, alım birimi, paket katı, tercih tedarikçi)."""
        from stok_uyari_ui import AyarDialog

        try:
            from database.stok_uyari_service import StokUyariService
            from database.database import get_session

            with get_session() as session:
                depo_id = StokUyariService._varsayilan_depo_id(session)
            depo = StokService.depo_getir(depo_id) if depo_id else None
            dlg = AyarDialog(self, int(self.stok.id), depo_id,
                             f"{self.stok.stok_kodu} — {self.stok.stok_adi}", depo.ad if depo else None)
            self.wait_window(dlg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Stok uyarısı", str(exc), parent=self)

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

    def _fon_sekmesini_lazy_kur(self):
        if getattr(self, "_fon_sekme_kuruldu", False):
            return
        self._fon_sekme_kuruldu = True
        parent = getattr(self, "_tab_fon", None)
        if parent is None:
            return
        try:
            from fon_ui import StokFonlariCercevesi

            StokFonlariCercevesi(parent, getattr(self.stok, "id", None)).pack(
                fill="both", expand=True
            )
        except Exception as hata:  # noqa: BLE001 — fon bölümü kartın açılmasını engellemez
            tk.Label(parent, text=f"Fon bilgileri yüklenemedi: {hata}", bg=BEYAZ).pack(
                anchor="w", padx=10
            )
        self.after_idle(self._sekme_yukseklik_sinirla)

    def _muhasebe_sekmesini_lazy_kur(self):
        if getattr(self, "_muhasebe_sekme_kuruldu", False):
            return
        self._muhasebe_sekme_kuruldu = True
        parent = getattr(self, "_tab_muhasebe", None)
        if parent is None:
            return
        self._muhasebe_sekmesini_kur(parent)
        self.after_idle(self._sekme_yukseklik_sinirla)

    def _resimleri_db_den_yukle(self):
        """Kart açılışında atlanan resimleri ihtiyaç anında (sekme/kayıt) çeker."""
        if getattr(self, "_resimler_db_yuklu", False):
            return
        self._resimler_db_yuklu = True
        if not self.stok:
            self.resimler = []
            return
        try:
            from sqlalchemy import select

            from database.database import get_session
            from database.models.stok import StokResmi

            with get_session() as session:
                rows = session.scalars(
                    select(StokResmi).where(StokResmi.stok_id == int(self.stok.id))
                ).all()
                self.resimler = [
                    {"dosya_yolu": r.dosya_yolu, "aciklama": r.aciklama or ""}
                    for r in rows
                ]
        except Exception:
            self.resimler = []

    def _resimler_sekmesini_lazy_kur(self):
        if getattr(self, "_resimler_sekme_kuruldu", False):
            return
        self._resimler_sekme_kuruldu = True
        parent = getattr(self, "_tab_resimler", None)
        if parent is None:
            return
        self._resimleri_db_den_yukle()
        self._resimler_sekmesini_kur(parent)
        self.after_idle(self._sekme_yukseklik_sinirla)

    def _muhasebe_sekmesini_kur(self, parent):
        """Üst şerit: Muhasebe Kodları sekmesi (eski diyalog alanları)."""
        from hesap_kodu_sec_ui import muhasebe_hesap_entry_bagla

        self.muhasebe_alanlari = {}
        tk.Label(
            parent,
            text="3 hane yazın veya … ile TDHP hesap planından seçin.",
            bg=BEYAZ,
            fg=sktema.IKINCIL,
            font=sktema.font(9, root=self),
        ).pack(anchor="w", padx=12, pady=(10, 6))
        form = tk.Frame(parent, bg=BEYAZ)
        form.pack(fill="x", padx=12, pady=4)
        for satir, (etiket, alan) in enumerate(StokMuhasebeDialog.ALANLAR):
            form_etiket(form, etiket, genislik=18).grid(
                row=satir, column=0, sticky="e", padx=ETIKET_PADX, pady=SATIR_PADY
            )
            satir_f = tk.Frame(form, bg=BEYAZ)
            satir_f.grid(row=satir, column=1, sticky="w", pady=SATIR_PADY)
            giris = ttk.Entry(satir_f, width=28, style="StokKart.TEntry")
            giris.pack(side="left")
            giris.insert(0, self.muhasebe.get(alan) or "")
            muhasebe_hesap_entry_bagla(self, giris)
            stok_tk_buton(
                satir_f,
                "…",
                lambda g=giris: self._muhasebe_hesap_sec(g),
                rol="ikincil",
                kompakt=True,
            ).pack(side="left", padx=(4, 0))
            self.muhasebe_alanlari[alan] = giris

    def _muhasebe_hesap_sec(self, giris):
        from hesap_kodu_sec_ui import HesapKoduSecDialog

        dlg = HesapKoduSecDialog(self, onek=(giris.get() or "").strip())
        self.wait_window(dlg)
        if dlg.result:
            giris.delete(0, "end")
            giris.insert(0, dlg.result)

    def _muhasebe_sekmeden_oku(self):
        if getattr(self, "muhasebe_alanlari", None):
            self.muhasebe = {
                alan: giris.get().strip() for alan, giris in self.muhasebe_alanlari.items()
            }

    def _resimler_sekmesini_kur(self, parent):
        """Üst şerit: Stok Resimleri sekmesi."""
        ust = tk.Frame(parent, bg=BEYAZ)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        stok_tk_buton(ust, "Resim Ekle", self._resim_ekle, rol="kaydet", kompakt=True).pack(
            side="left"
        )
        stok_tk_buton(ust, "Seçiliyi Sil", self._resim_sil, rol="tehlike", kompakt=True).pack(
            side="left", padx=6
        )
        cerceve = tk.Frame(parent, bg=BEYAZ)
        cerceve.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.resim_tablo = ttk.Treeview(
            cerceve, columns=("yol", "aciklama"), show="headings", selectmode="browse", height=5
        )
        self.resim_tablo.heading("yol", text="Dosya")
        self.resim_tablo.heading("aciklama", text="Açıklama")
        self.resim_tablo.column("yol", width=480)
        self.resim_tablo.column("aciklama", width=180)
        self.resim_tablo.pack(side="left", fill="both", expand=True)
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.resim_tablo.yview)
        self.resim_tablo.configure(yscrollcommand=kaydir.set)
        kaydir.pack(side="right", fill="y")
        for kayit in self.resimler or []:
            self.resim_tablo.insert(
                "",
                "end",
                values=(kayit.get("dosya_yolu", ""), kayit.get("aciklama") or ""),
            )

    def _resim_ekle(self):
        yol = filedialog.askopenfilename(
            parent=self,
            title="Stok resmi seç",
            filetypes=[("Resimler", "*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp"), ("Tümü", "*.*")],
        )
        if not yol:
            return
        kod = ""
        if "stok_kodu" in self.alanlar:
            kod = self.alanlar["stok_kodu"].get().strip()
        try:
            hedef = StokService.resim_kopyala(kod or "yeni", yol)
        except ValueError as hata:
            messagebox.showerror("Resim eklenemedi", str(hata), parent=self)
            return
        aciklama = simpledialog.askstring("Açıklama", "Resim açıklaması (opsiyonel):", parent=self) or ""
        self.resim_tablo.insert("", "end", values=(hedef, aciklama))
        self._resimler_sekmeden_oku()

    def _resim_sil(self):
        for item in self.resim_tablo.selection():
            self.resim_tablo.delete(item)
        self._resimler_sekmeden_oku()

    def _resimler_sekmeden_oku(self):
        if not getattr(self, "resim_tablo", None):
            # Sekme açılmadan kaydet: DB'deki resimleri ezme
            self._resimleri_db_den_yukle()
            return
        self.resimler = [
            {
                "dosya_yolu": self.resim_tablo.item(i, "values")[0],
                "aciklama": self.resim_tablo.item(i, "values")[1],
            }
            for i in self.resim_tablo.get_children()
        ]
        self._resimler_db_yuklu = True

    def resimler_ac(self):
        """Geriye uyumluluk — Stok Resimleri sekmesine geç."""
        try:
            for i in range(self.sekmeler.index("end")):
                if "Resim" in self.sekmeler.tab(i, "text"):
                    self.sekmeler.select(i)
                    return
        except tk.TclError:
            pass

    def muhasebe_ac(self):
        """Geriye uyumluluk — Muhasebe Kodları sekmesine geç."""
        try:
            for i in range(self.sekmeler.index("end")):
                if "Muhasebe" in self.sekmeler.tab(i, "text"):
                    self.sekmeler.select(i)
                    return
        except tk.TclError:
            pass

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

    def _lot_kar_zarar_ac(self):
        if not self.stok:
            messagebox.showinfo("Lot Kâr/Zarar", "Önce stok kartını kaydedin.", parent=self)
            return
        LotKarZararDialog(self, self.stok)

    def _hareket_kolon_ayarlari_ac(self):
        dlg = HareketKolonAyarDialog(self)
        self.wait_window(dlg)
        if not dlg.result or not hasattr(self, "hareket_tablo"):
            return
        self._hrk_kolon_ayarlari = hareket_kolon_ayarlari_yukle()
        self._hrk_kolon_idler = tuple(self._hrk_kolon_ayarlari.keys())
        for kolon in self._hrk_kolon_idler:
            cfg = self._hrk_kolon_ayarlari[kolon]
            sayisal = kolon in _HAREKET_SAYISAL_KOLONLAR
            gorunur = cfg.get("gorunur", True)
            try:
                self.hareket_tablo.heading(kolon, text=cfg["baslik"], anchor="e" if sayisal else "w")
                self.hareket_tablo.column(
                    kolon,
                    width=cfg["genislik"] if gorunur else 0,
                    minwidth=0 if not gorunur else 40,
                    stretch=gorunur,
                    anchor="e" if sayisal else "w",
                )
            except tk.TclError:
                pass
        self._hareketler_tabloyu_doldur()

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

    def kaydet(self) -> bool:
        """Yeni kartta oluşturur, mevcut kartta günceller; başarıda True.

        Kayıt sürerken gelen ikinci tıklama yok sayılır (mükerrer kart oluşmaz).
        """
        if self._kaydediliyor:
            return False
        self._kaydediliyor = True
        try:
            self.kaydet_btn.configure(state="disabled")
        except (tk.TclError, AttributeError):
            pass
        try:
            return self._kaydet()
        finally:
            self._kaydediliyor = False
            try:
                self.kaydet_btn.configure(state="normal")
            except (tk.TclError, AttributeError):
                pass

    def _kaydet(self) -> bool:
        if hasattr(self, "aciklama_alani"):
            self.aciklama = self.aciklama_alani.get("1.0", "end").strip()
        self._fabrika_fiyati_guncelle()
        # Alış fiyatını son faturadan tazele (manuel müdahale yok)
        kod = self.alanlar["stok_kodu"].get().strip()
        stok_id = self.stok.id if self.stok else None
        son_net = StokService.son_alis_faturasi_net(stok_kodu=kod, stok_id=stok_id)
        if son_net is not None:
            self._fiyat_yaz("ALIŞ FİYATI", f"{son_net:f}".rstrip("0").rstrip("."))
        if getattr(self, "_tur_grup_yukleniyor", False) and not getattr(
            self, "_stok_ana_tur_map", None
        ):
            messagebox.showinfo(
                "Stok",
                "Kart türü listesi hâlâ yükleniyor. Bir saniye sonra tekrar Kaydet’e basın.",
                parent=self,
            )
            return False
        ana_id, alt_id, ana_ad = self._stok_tur_secili_idler()
        if not ana_id:
            messagebox.showerror("Stok", "Stok Kart Türü seçin.", parent=self)
            return False
        from database.kart_turu_service import KartTuruService

        try:
            # Alt tür zorunlu değil; uyumsuzsa temizle ama bilinçli silme yok
            ana_id, alt_id, _uyari = KartTuruService.stok_tur_dogrula(ana_id, alt_id)
        except ValueError as exc:
            messagebox.showerror("Stok türü", str(exc), parent=self)
            return False
        veriler = {
            "stok_kodu": self.alanlar["stok_kodu"].get().strip(),
            "stok_adi": self.alanlar["stok_adi"].get().strip(),
            "kart_turu": ana_ad,
            "ana_kart_turu_id": ana_id,
            "alt_kart_turu_id": alt_id,
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
            "aktif": (self.alanlar.get("kart_durumu").get() if self.alanlar.get("kart_durumu") else "Aktif")
            != "Pasif",
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
        self._muhasebe_sekmeden_oku()
        self._resimler_sekmeden_oku()
        veriler.update({k: (v or "") for k, v in self.muhasebe.items()})
        veriler["yalniz_yeni"] = self.stok is None
        eksik = [ad for alan, ad in (("stok_kodu", "Stok Kodu"), ("stok_adi", "Stok Adı")) if not veriler[alan]]
        if eksik:
            messagebox.showwarning(
                "Eksik bilgi",
                "Kaydetmek için şu zorunlu alanları doldurun:\n• " + "\n• ".join(eksik),
                parent=self,
            )
            self.alanlar["stok_kodu" if "Stok Kodu" in eksik else "stok_adi"].focus_set()
            return False
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
                        return False
            except ValueError as exc:
                messagebox.showwarning("Stok grubu", str(exc), parent=self)
                return False
        self._yeni_kart_ana_birimi_esitle()
        veriler["birim"] = self.alanlar["birim"].get().strip() or "Adet"
        aktif_birimler = self._ana_birim_secenekleri(genel=False)
        if not aktif_birimler:
            messagebox.showwarning(
                "Birim",
                "Bu stok için en az bir birim tanımlayın (Barkod ve Birimler).",
                parent=self,
            )
            return False
        if veriler["birim"] not in aktif_birimler:
            messagebox.showwarning(
                "Ana Birim",
                f"Ana birim «{veriler['birim']}» tanımlı aktif birimler arasında değil.\n"
                f"Geçerli birimler: {', '.join(aktif_birimler)}",
                parent=self,
            )
            return False
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
            return False
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
                    return False
        except Exception:
            pass
        raf_omru_metin = self.alanlar["raf_omru"].get().strip()
        if raf_omru_metin:
            try:
                veriler["raf_omru"] = datetime.strptime(raf_omru_metin, "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Raf ömrü", "Raf ömrü tarihini gg.aa.yyyy formatında girin.", parent=self)
                return False
        else:
            veriler["raf_omru"] = None
        # Bağlı satış fiyatlarını kayıttan önce güncelle
        self._satis_bagli_fiyatlari_guncelle()
        fiyatlar = [(ad, giris.get().strip()) for ad, giris in self.fiyat_alanlari.items()]
        fiyat_hesaplamalari = {}
        for ad, h in (getattr(self, "fiyat_hesap_alanlari", None) or {}).items():
            fiyat_hesaplamalari[ad] = {
                "hesaplama_modu": self._satis_modu_metin_kod(h["modu"].get()),
                "satis_iskonto": h["iskonto"].get().strip() or "0",
            }
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
            return False
        try:
            self.result = StokService.stok_kaydi(
                veriler,
                fiyatlar,
                birimler=self.birimler,
                barkodlar=self.barkodlar,
                resimler=self.resimler,
                kdv_durumlari={
                    ad: fiyat_kdv_kodu(sec.get())
                    for ad, sec in getattr(self, "fiyat_kdv_alanlari", {}).items()
                },
                fiyat_hesaplamalari=fiyat_hesaplamalari,
            )
        except ValueError as hata:
            messagebox.showerror("Stok kaydedilemedi", str(hata), parent=self)
            return False
        yeni_mi = self.stok is None
        self.stok = self.result
        self.title("Stok Kartını Düzenle")
        self._ozeti_yenile()
        self._depo_tablosu_yenile()
        self._barkod_birim_tablolari_yenile()
        self._hareketler_yukle()
        self._ilk_durum = self._durum_ozeti()
        mesaj = (
            f"Yeni stok kartı oluşturuldu: {self.stok.stok_kodu} — {self.stok.stok_adi}"
            if yeni_mi
            else f"Stok kartı güncellendi: {self.stok.stok_kodu} — {self.stok.stok_adi}"
        )
        if _rapor.get("uyari_ean"):
            mesaj += f"\n\nBarkod: {_rapor['uyari_ean']}"
        messagebox.showinfo("Kaydedildi", mesaj, parent=self)
        if self._on_saved is not None:
            try:
                self._on_saved(self.result)
            except Exception:
                pass
        return True

def birim_donusturucu_urun_sec(app) -> None:
    """STOKLAR hub: ürün seç → Birim Dönüştürücü (tek pencere ailesi)."""
    from tkinter import messagebox

    from urun_sec_ui import UrunSecDialog

    parent = app

    def _ac(_kod, _ad, _birim, stok, *_rest):
        if stok is None:
            messagebox.showwarning("Birim Dönüştürücü", "Ürün seçilmedi.", parent=parent)
            return
        ana = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
        birimler = []
        for b in getattr(stok, "birimler", None) or []:
            if not getattr(b, "aktif", True):
                continue
            birimler.append(
                {
                    "birim": b.birim_adi,
                    "carpan": str(b.carpan),
                    "referans_birim": getattr(b, "referans_birim", None) or ana,
                    "referans_carpan": str(getattr(b, "referans_carpan", None) or b.carpan),
                    "fiyat_modu": getattr(b, "fiyat_modu", None) or "manuel",
                    "birim_barkod": getattr(b, "birim_barkod", None) or "",
                    "alis_fiyati": str(getattr(b, "alis_fiyati", None) or ""),
                    "satis_fiyati": str(getattr(b, "satis_fiyati", None) or ""),
                    "aktif": True,
                }
            )
        ana_fiyatlar = {}
        for f in getattr(stok, "fiyatlar", None) or []:
            ad = (f.fiyat_adi or "").strip().upper()
            if ad:
                ana_fiyatlar[ad] = str(f.tutar)
        StokBirimlerDialog(
            parent,
            ana,
            birimler,
            ana_fiyatlar=ana_fiyatlar,
            stok_id=int(stok.id),
        )

    UrunSecDialog(parent, query="", on_select=_ac)
