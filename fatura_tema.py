"""Satış Faturası Kartı — kurumsal renk, tipografi ve chrome (Tkinter).

İş mantığı yok; yalnızca görsel sabitler ve tekrar kullanılabilir üst/alt çubuk.
Palet: cari_kart_tema / satis_tema ile uyumlu (lacivert + sarı).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

# Kurumsal palet
LACIVERT = "#0B2A4A"
LACIVERT_ORTA = "#163E66"
LACIVERT_HOVER = "#1A4068"
SARI = "#F5B700"
SARI_HOVER = "#FFD54F"
ACIK_BG = "#F4F6F8"
BEYAZ = "#FFFFFF"
METIN = "#1F2937"
IKINCIL = "#667085"
BASARI = "#15803D"
BASARI_HOVER = "#166534"
UYARI = "#D97706"
UYARI_HOVER = "#B45309"
IPTAL = "#DC2626"
IPTAL_HOVER = "#B91C1C"
CIZGI = "#D7DEE7"
SECIM = "#FFE082"
STRIPE = "#F0F3F7"

# Durum rozetleri
DURUM_RENKLERI = {
    "TASLAK": ("#64748B", BEYAZ),
    "ONAYLANDI": (BASARI, BEYAZ),
    "ONAYLI": (BASARI, BEYAZ),
    "ONAYSIZ": ("#B45309", BEYAZ),
    "AÇIK": (BASARI, BEYAZ),
    "KAPALI": (LACIVERT_ORTA, BEYAZ),
    "İPTAL": (IPTAL, BEYAZ),
    "MUHASEBELEŞTİ": ("#0E7490", BEYAZ),
    "E-FATURA": ("#1D4ED8", BEYAZ),
    "HATA": (IPTAL, BEYAZ),
}

FONT_ADAYLARI = ("Segoe UI", "Aptos", "Calibri", "Arial")
_font_aile: str | None = None

# Satır yüksekliği — sabit katsayı (açılışta tekrar büyümez); tek satır ≈ +%10
SATIR_YUKSEKLIK_KATSAYI = 1.1
FORM_SATIR_TABAN_PX = 18
TABLO_SATIR_TABAN_PX = 26
TABLO_BASLIK_PAD_TABAN = 3
HUCRE_EDITOR_TABAN_PX = 20
# Üst form satır arası hedef (mm) — DPI ile piksele çevrilir
FORM_SATIR_ARALIK_MM = 1.5


def scale_height(eski: float | int, katsayi: float = SATIR_YUKSEKLIK_KATSAYI) -> int:
    """yeni = round(mevcut × katsayı)."""
    return max(1, int(round(float(eski) * float(katsayi))))


def tablo_satir_rowheight(
    root: tk.Misc | None = None,
    *,
    font_spec=None,
    vurgulu_font_spec=None,
    dikey_pay: int = 12,
) -> int:
    """Treeview ürün satırı yüksekliği — yazı linespace + pay (ızgara metni kesmez).

    Windows ölçeğinde punto büyür; sabit px yetmez. Font metrics ile hesaplanır.
    Fatura vurgulu ürün adı (12 bold) overlay'i de aynı satıra sığmalıdır.
    """
    from tkinter import font as tkfont

    def _linespace(spec) -> int:
        try:
            if root is not None:
                fnt = tkfont.Font(root=root, font=spec)
            else:
                fnt = tkfont.Font(font=spec)
            return max(1, int(fnt.metrics("linespace") or 0))
        except Exception:
            return 0

    if font_spec is None:
        font_spec = font(10, root=root)
    if vurgulu_font_spec is None:
        vurgulu_font_spec = font(12, "bold", root=root)
    ls = max(_linespace(font_spec), _linespace(vurgulu_font_spec), 16)
    taban = scale_height(TABLO_SATIR_TABAN_PX)
    return max(taban, ls + max(6, int(dikey_pay)))


def form_ipady(taban: int = FORM_SATIR_TABAN_PX) -> int:
    """Entry/düğme dikey iç boşluk — sabit hedef yükseklik (yeniden açılışta artmaz)."""
    hedef = scale_height(taban)
    # clam Entry içerik ~14 px; ipady ile dikey ortalama
    return max(1, (hedef - 14) // 2)


def form_satir_dis_yukseklik(taban: int = FORM_SATIR_TABAN_PX) -> int:
    """Tek satırlık Entry/Combobox/düğme dış yüksekliği (içerik + ipady×2)."""
    return scale_height(taban)


def _ekran_dpi() -> float:
    try:
        root = tk._default_root  # type: ignore[attr-defined]
        if root is not None:
            return float(root.winfo_fpixels("1i"))
    except Exception:
        pass
    return 96.0


def form_pady(taban: int = 1) -> int:
    """Grid pady (her kenar); bitişik satırlar arası toplam ≈ FORM_SATIR_ARALIK_MM.

    Her kenara FORM_SATIR_ARALIK_MM koyulmaz — toplam boşluk bir kez bölünür
    (üst+alt = ~1,5 mm; çift uygulamada ~3 mm olmaz).
    """
    import math

    _ = taban  # API uyumu
    toplam = max(2, int(round(FORM_SATIR_ARALIK_MM / 25.4 * _ekran_dpi())))
    return max(1, int(math.ceil(toplam / 2.0)))


def form_cok_satir_text_yukseklik(satir_sayisi: int) -> int:
    """Çok satırlı Text için satır sayısı (Adres=2, Açıklama=3); panel büyütmez."""
    return max(2, int(satir_sayisi))

def resolve_ui_font(root: tk.Misc | None = None) -> str:
    global _font_aile
    if _font_aile:
        return _font_aile
    families: set[str] = set()
    try:
        probe = root if root is not None else tk._default_root  # type: ignore[attr-defined]
        if probe is not None:
            families = {str(f).lower() for f in probe.tk.call("font", "families")}
    except Exception:
        families = set()
    for name in FONT_ADAYLARI:
        if not families or name.lower() in families:
            _font_aile = name
            return name
    _font_aile = "Arial"
    return _font_aile


def font(size: int, weight: str = "normal", root: tk.Misc | None = None) -> tuple:
    aile = resolve_ui_font(root)
    if weight in ("bold", "semibold"):
        return (aile, size, "bold")
    return (aile, size)


_STIL_ISARET = "::fatura_tema_uygulanan"


def stil_uygula(stil: ttk.Style | None = None, root: tk.Misc | None = None) -> ttk.Style:
    """Fatura stillerini kaydeder; aynı temada ikinci kez uygulamaz.

    Her ``theme_use`` / ``style configure`` açık tüm ttk pencerelerini yeniden yerleştirir;
    büyük fatura ekranı açıkken (ör. tahsilat makbuzu açılırken) bu saniyeler sürer.
    """
    stil = stil or ttk.Style(root)
    hedef = None
    try:
        adlar = stil.theme_names()
        hedef = "clam" if "clam" in adlar else ("vista" if "vista" in adlar else None)
        mevcut = stil.theme_use()
        if hedef and mevcut == hedef:
            if str(stil.tk.call("info", "exists", _STIL_ISARET)) == "1" and stil.tk.globalgetvar(
                _STIL_ISARET
            ) == hedef:
                return stil
        elif hedef:
            stil.theme_use(hedef)
    except tk.TclError:
        pass

    f_ui = font(10, root=root)
    f_bold = font(10, "bold", root=root)
    f_baslik = font(13, "bold", root=root)
    f_alt = font(9, root=root)
    f_btn = font(10, "bold", root=root)
    f_toplam = font(12, "bold", root=root)

    stil.configure("Fatura.TFrame", background=ACIK_BG)
    stil.configure("FaturaPanel.TFrame", background=BEYAZ)
    stil.configure("Fatura.TLabel", background=ACIK_BG, foreground=METIN, font=f_ui)
    stil.configure("FaturaMuted.TLabel", background=ACIK_BG, foreground=IKINCIL, font=f_alt)
    stil.configure("FaturaPanel.TLabel", background=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("FaturaPanelMuted.TLabel", background=BEYAZ, foreground=IKINCIL, font=f_alt)
    stil.configure("FaturaBaslik.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_baslik)
    stil.configure("FaturaBolum.TLabel", background=BEYAZ, foreground=LACIVERT, font=f_bold)
    stil.configure(
        "FaturaToplam.TLabel",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_toplam,
    )
    stil.configure(
        "FaturaGenelToplam.TLabel",
        background=BEYAZ,
        foreground=LACIVERT,
        font=font(14, "bold", root),
    )

    stil.configure(
        "Fatura.TLabelframe",
        background=BEYAZ,
        foreground=LACIVERT,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "Fatura.TLabelframe.Label",
        background=BEYAZ,
        foreground=LACIVERT,
        font=f_bold,
    )
    stil.configure("Fatura.TEntry", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    stil.configure("Fatura.TCombobox", fieldbackground=BEYAZ, foreground=METIN, font=f_ui)
    # Üst form: dikey padding stil içinde; grid/pack ipady EKLENMEZ (çift yükseklik olmasın).
    # Hedef ≈ Borç/Alacak özet kutusunun gerçek dış yüksekliği (~23 px; cfg 20 + çerçeve).
    _ip = max(0, form_ipady(FORM_SATIR_TABAN_PX) - 1)  # ~2 → Entry/Combobox ≈ özet kutusu
    stil.configure(
        "FaturaUst.TEntry",
        fieldbackground=BEYAZ,
        foreground=METIN,
        font=font(9, root=root),
        padding=(4, _ip),
    )
    stil.configure(
        "FaturaMusteriAd.TEntry",
        fieldbackground=BEYAZ,
        foreground=METIN,
        font=font(10, "bold", root),
        padding=(4, _ip),
    )
    stil.configure(
        "FaturaUst.TCombobox",
        fieldbackground=BEYAZ,
        foreground=METIN,
        font=font(9, root=root),
        padding=(4, _ip),
    )
    stil.configure(
        "FaturaUst.TButton",
        font=font(9, "bold", root),
        padding=(8, _ip),
    )

    _satir_font = font(10, root=root)
    stil.configure(
        "FaturaSatir.Treeview",
        font=_satir_font,
        rowheight=tablo_satir_rowheight(root, font_spec=_satir_font),
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        # solid relief Windows'ta satır ortasından yatay çizgi çizebiliyor; ızgara overlay'de
        borderwidth=0,
        relief="flat",
    )
    # Açık zemin + lacivert yazı: Windows/clam'da lacivert+beyaz bazen görünmez kalır
    stil.configure(
        "FaturaSatir.Treeview.Heading",
        font=f_bold,
        background="#E8EEF5",
        foreground=LACIVERT,
        # solid/raised + Treeheading.border metnin ortasından çizgi çizer;
        # ızgara yalnızca treeview_excel_cizgi overlay ile çizilir.
        relief="flat",
        borderwidth=0,
        padding=(6, scale_height(TABLO_BASLIK_PAD_TABAN)),
    )
    # clam varsayılan layout'taki Treeheading.border orta çizgiyi üretir — kaldır
    try:
        stil.layout(
            "FaturaSatir.Treeview.Heading",
            [
                ("Treeheading.cell", {"sticky": "nswe"}),
                (
                    "Treeheading.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("Treeheading.image", {"side": "right", "sticky": ""}),
                            ("Treeheading.text", {"sticky": "we"}),
                        ],
                    },
                ),
            ],
        )
    except tk.TclError:
        pass
    stil.map(
        "FaturaSatir.Treeview",
        background=[("selected", SECIM)],
        foreground=[("selected", LACIVERT)],
    )
    stil.map(
        "FaturaSatir.Treeview.Heading",
        background=[("active", SARI), ("pressed", SARI)],
        foreground=[("active", LACIVERT), ("pressed", LACIVERT)],
    )

    stil.configure(
        "FaturaKaydet.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=LACIVERT,
    )
    stil.map(
        "FaturaKaydet.TButton",
        background=[("active", LACIVERT_HOVER), ("!disabled", LACIVERT)],
        foreground=[("!disabled", BEYAZ)],
    )
    stil.configure(
        "FaturaOnay.TButton",
        font=f_btn,
        padding=(12, 6),
        foreground=BEYAZ,
        background=BASARI,
    )
    stil.map(
        "FaturaOnay.TButton",
        background=[("active", BASARI_HOVER), ("!disabled", BASARI)],
        foreground=[("!disabled", BEYAZ)],
    )
    if hedef:
        try:
            stil.tk.globalsetvar(_STIL_ISARET, hedef)
        except tk.TclError:
            pass
    return stil


# ─── Satış faturası oval 3D işlem butonları (eşit boyut + sakin palet) ───
# Onayla/Onaylı kırmızı/yeşil özel; diğerleri aşağıdaki gruplar.

BUTON_PALET = {
    # A) Kaydet
    "kaydet": {
        "zemin": "#365F7D",
        "hover": "#2D526D",
        "basili": "#25465F",
        "yazi": "#FFFFFF",
        "kenar": "#284A64",
    },
    # B) Ana Yeni / Tahsilat / Fiyatları Düzenle
    "petrol": {
        "zemin": "#3F6D6A",
        "hover": "#345C59",
        "basili": "#2D4F4C",
        "yazi": "#FFFFFF",
        "kenar": "#315653",
    },
    # C) Yardımcı işlemler — açık paneller (Müşteri/Depo vb.)
    "yardimci": {
        "zemin": "#E7EDF3",
        "hover": "#D8E3ED",
        "basili": "#CCD9E5",
        "yazi": "#24374A",
        "kenar": "#BBC8D4",
    },
    # C2) Lacivert şerit üzerinde yardımcı — açık «sticker» plaka yok
    "yardimci_koyu": {
        "zemin": "#163E66",
        "hover": "#1A4A78",
        "basili": "#0F2F52",
        "yazi": "#FFFFFF",
        "kenar": "#2A5A8A",
    },
    # D) Sil / iptal
    "sil": {
        "zemin": "#F3E3E4",
        "hover": "#EBD2D5",
        "basili": "#E2C1C6",
        "yazi": "#8B3540",
        "kenar": "#CFADB2",
    },
    "sil_koyu": {
        "zemin": "#5C2A32",
        "hover": "#6E323C",
        "basili": "#4A2229",
        "yazi": "#F7D6DA",
        "kenar": "#7A3E48",
    },
    # Devre dışı (Onayla/Onaylı hariç)
    "disabled": {
        "zemin": "#E3E7EB",
        "hover": "#E3E7EB",
        "basili": "#E3E7EB",
        "yazi": "#5D6874",
        "kenar": "#CDD5DD",
    },
    "disabled_koyu": {
        "zemin": "#143250",
        "hover": "#143250",
        "basili": "#143250",
        "yazi": "#7A8FA8",
        "kenar": "#1E4060",
    },
    # Onayla (kırmızı — genel palet uygulanmaz)
    "onayla": {
        "zemin": IPTAL,
        "hover": IPTAL_HOVER,
        "basili": "#9B1C1C",
        "yazi": BEYAZ,
        "kenar": "#9B1C1C",
    },
    # Onaylı (yeşil)
    "onayli": {
        "zemin": BASARI,
        "hover": BASARI_HOVER,
        "basili": "#14532D",
        "yazi": BEYAZ,
        "kenar": "#14532D",
    },
}

# Geriye uyumluluk: eski rol adları → yeni palet
_BUTON_ROL_ESLE = {
    "kaydet": "kaydet",
    "onay": "petrol",  # Yeni vb.; Onayla için açıkça "onayla" kullan
    "vurgu": "petrol",
    "ikincil": "yardimci",
    "uyari": "yardimci",
    "tehlike": "onayla",
    "yazdir": "yardimci",
    "petrol": "petrol",
    "yardimci": "yardimci",
    "sil": "sil",
    "onayla": "onayla",
    "onayli": "onayli",
}

# İki kompakt ölçü grubu (birbirine eşit olmak zorunda değil)
# Panel içi: Yeni / Ara / Cari Kart — boyutlar korunur (~60–76 × 22–24)
FATURA_PANEL_BUTON_ETIKETLER = ("Yeni", "Ara", "Cari Kart")
# Panel dışı (üst şerit + satır araçları): eşit kompakt ölçü (~90–112 × 24–26)
FATURA_DIS_BUTON_ETIKETLER = (
    "Fatura Listesi (F3)",
    "Kaydet (F1)",
    "Güncelle (F1)",
    "Onayla (F4)",
    "Onayla",
    "Onayı Kaldır",
    "Onaylı",
    "Yeni",
    "Yazdır / PDF ▾",
    "Önizleme",
    "PDF",
    "Masraflar",
    "İadeler",
    "Tahsilat Makbuzu",
    "Analiz ▾",
    "Diğer İşlemler ▾",
    "Sevkiyat",
    "Dosyadan Aktar",
    "İptal Et",
    "Listeye Git",
    "Kapat (Esc)",
    "Yeni Stok Kartı (F6)",
    "Siparişten Getir (Alt+S)",
    "İrsaliyeden Getir (Alt+I)",
    "Fiyatları Düzenle",
    "Dağıtımı Geri Al",
    "Satır Sil",
    "Satır İşlemleri ▾",
)

# Geriye uyumluluk
FATURA_BUTON_OLCU_ETIKETLER = FATURA_DIS_BUTON_ETIKETLER

_BUTON_OLCU_ONBELLEK: dict[str, tuple[int, int]] = {}
ODAK_CERCVE = "#3D7AA6"


def _buton_olcu_hesapla(
    root: tk.Misc | None,
    etiketler: tuple[str, ...],
    *,
    font_pt: int,
    h_min: int,
    h_max: int,
    h_hedef: int,
    w_min: int,
    w_max: int,
    pad_x: int,
) -> tuple[int, int]:
    try:
        h_taban = max(h_min, min(h_max, int(round(scale_height(h_hedef)))))
    except Exception:
        h_taban = h_hedef
    fnt = font(font_pt, "bold", root)
    max_w = w_min - pad_x
    try:
        from tkinter import font as tkfont

        olcu = tkfont.Font(font=fnt, root=root) if root is not None else tkfont.Font(font=fnt)
        for etiket in etiketler:
            max_w = max(max_w, int(olcu.measure(etiket)))
    except Exception:
        max_w = max(max_w, w_min)
    genislik = max(w_min, min(w_max, max_w + pad_x))
    # Etiket w_max'ı aşıyorsa okunabilirlik için biraz serbest bırak (max +%8)
    if max_w + pad_x > w_max:
        genislik = min(max_w + pad_x, int(w_max * 1.08))
    return genislik, h_taban


def fatura_buton_olculeri(
    root: tk.Misc | None = None, *, grup: str = "dis"
) -> tuple[int, int]:
    """Kompakt ölçü: grup='panel' (iç) veya 'dis' (şerit/araç)."""
    anahtar = "panel" if grup == "panel" else "dis"
    if anahtar in _BUTON_OLCU_ONBELLEK:
        return _BUTON_OLCU_ONBELLEK[anahtar]
    if anahtar == "panel":
        olcu = _buton_olcu_hesapla(
            root,
            FATURA_PANEL_BUTON_ETIKETLER,
            font_pt=9,
            h_min=22,
            h_max=24,
            h_hedef=23,
            w_min=60,
            w_max=76,
            pad_x=14,
        )
    else:
        olcu = _buton_olcu_hesapla(
            root,
            FATURA_DIS_BUTON_ETIKETLER,
            font_pt=9,
            h_min=24,
            h_max=26,
            h_hedef=25,
            w_min=90,
            w_max=112,
            pad_x=12,
        )
    _BUTON_OLCU_ONBELLEK[anahtar] = olcu
    return olcu


def fatura_buton_olcu_sifirla() -> None:
    """Ölçü önbelleğini temizle (test / DPI değişimi)."""
    _BUTON_OLCU_ONBELLEK.clear()


def _palet_rol(rol: str) -> dict:
    anahtar = _BUTON_ROL_ESLE.get(rol, "yardimci")
    return BUTON_PALET.get(anahtar, BUTON_PALET["yardimci"])


def _renk_koyu_mu(bg: str) -> bool:
    """Lacivert toolbar / koyu zemin: açık gri oval plaka kullanılmasın."""
    s = (bg or "").strip().lstrip("#").lower()
    if not s:
        return False
    koyu_sabit = {
        LACIVERT.lstrip("#").lower(),
        LACIVERT_ORTA.lstrip("#").lower(),
        LACIVERT_HOVER.lstrip("#").lower(),
        "1b2a4a",
        "0b2a4a",
        "163e66",
    }
    if s in koyu_sabit:
        return True
    if len(s) == 6:
        try:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            # Göreli parlaklık
            return (0.299 * r + 0.587 * g + 0.114 * b) < 90
        except ValueError:
            return False
    return False


class FaturaOvalButon(tk.Frame):
    """Kompakt oval/kapsül 3D işlem butonu — grup: panel | dis."""

    def __init__(
        self,
        parent,
        metin: str,
        komut: Callable | None = None,
        *,
        rol: str = "yardimci",
        state: str = "normal",
        menu: tk.Menu | None = None,
        grup: str = "dis",
        genislik: int | None = None,
        yukseklik: int | None = None,
        **_kwargs,
    ):
        root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
        self._grup = "panel" if grup == "panel" else "dis"
        gw, gh = fatura_buton_olculeri(root, grup=self._grup)
        if genislik is not None:
            gw = int(genislik)
        if yukseklik is not None:
            gh = int(yukseklik)
        # Toolbar lacivert üzerinde şeffaf görünüm için parent bg
        try:
            bg_parent = str(parent.cget("bg") or ACIK_BG)
        except tk.TclError:
            bg_parent = ACIK_BG
        super().__init__(parent, bg=bg_parent, highlightthickness=0, bd=0)
        self._bg_parent = bg_parent
        self._koyu_ust = _renk_koyu_mu(bg_parent)
        self._metin = metin
        self._komut = komut
        self._rol = rol
        self._menu = menu
        self._enabled = state != "disabled"
        self._basili = False
        self._hover = False
        self._odak = False
        self._gw = gw
        self._gh = gh
        self._font = font(9 if self._grup == "panel" else 9, "bold", root)
        self._canvas = tk.Canvas(
            self,
            width=gw,
            height=gh,
            highlightthickness=0,
            bd=0,
            bg=bg_parent,
            cursor="hand2" if self._enabled else "arrow",
            takefocus=1,
        )
        self._canvas.pack()
        self._ciz()
        self._canvas.bind("<ButtonPress-1>", self._bas)
        self._canvas.bind("<ButtonRelease-1>", self._birak)
        self._canvas.bind("<Enter>", self._gir)
        self._canvas.bind("<Leave>", self._cik)
        self._canvas.bind("<FocusIn>", self._odak_gir)
        self._canvas.bind("<FocusOut>", self._odak_cik)
        self._canvas.bind("<Return>", self._klavye_tetikle)
        self._canvas.bind("<space>", self._klavye_tetikle)
        # Dış API uyumu
        self.configure = self._configure_api  # type: ignore[method-assign]
        self.cget = self._cget_api  # type: ignore[method-assign]

    def _renkler(self) -> dict:
        eslenen = _BUTON_ROL_ESLE.get(self._rol, "yardimci")
        if not self._enabled and self._rol not in ("onayla", "onayli", "tehlike"):
            return BUTON_PALET["disabled_koyu" if self._koyu_ust else "disabled"]
        # Lacivert şeritte yardımcı/sil: paneldeki açık plaka yerine koyu kapsül
        if self._koyu_ust:
            if eslenen == "yardimci":
                return BUTON_PALET["yardimci_koyu"]
            if eslenen == "sil":
                return BUTON_PALET["sil_koyu"]
        # Onaylı/onayla disabled olsa bile durum rengi korunsun
        return _palet_rol(self._rol)

    def _kapsul(self, x1, y1, x2, y2, dolgu, kenar=None):
        c = self._canvas
        r = max((y2 - y1) // 2, 1)
        if kenar:
            c.create_oval(x1, y1, x1 + 2 * r, y2, fill=kenar, outline="")
            c.create_oval(x2 - 2 * r, y1, x2, y2, fill=kenar, outline="")
            c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=kenar, outline="")
            x1, y1, x2, y2 = x1 + 1, y1 + 1, x2 - 1, y2 - 1
            r = max((y2 - y1) // 2, 1)
        c.create_oval(x1, y1, x1 + 2 * r, y2, fill=dolgu, outline="")
        c.create_oval(x2 - 2 * r, y1, x2, y2, fill=dolgu, outline="")
        c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=dolgu, outline="")

    def _ciz(self) -> None:
        c = self._canvas
        c.delete("all")
        r = self._renkler()
        w, h = self._gw, self._gh
        # Lacivert şerit: tek katmanlı kapsül (çift kenar / beyaz highlight yok → yama izi kalkar)
        if self._koyu_ust:
            if self._basili and self._enabled:
                dolgu = r["basili"]
                self._kapsul(1, 1, w - 1, h - 1, dolgu, r["kenar"])
                ty = h // 2 + 1
            else:
                dolgu = r["hover"] if (self._hover and self._enabled) else r["zemin"]
                self._kapsul(0, 0, w - 1, h - 1, dolgu, r["kenar"])
                ty = h // 2
            yazi = r["yazi"]
            if self._odak and self._enabled:
                self._kapsul(1, 1, w - 2, h - 2, dolgu, ODAK_CERCVE)
        else:
            if self._basili and self._enabled:
                self._kapsul(1, 2, w - 1, h - 1, r["basili"], r["kenar"])
                ty = h // 2 + 1
                yazi = r["yazi"]
            else:
                self._kapsul(1, 2, w - 1, h - 1, r["kenar"])
                dolgu = r["hover"] if (self._hover and self._enabled) else r["zemin"]
                self._kapsul(0, 0, w - 2, h - 2, dolgu, r["kenar"])
                isik = "#FFFFFF" if r["yazi"] in (BEYAZ, "#FFFFFF") else "#F7FAFC"
                c.create_line(6, 1, w - 6, 1, fill=isik, width=1)
                ty = h // 2 - 1
                yazi = r["yazi"]
            if self._odak and self._enabled:
                c.create_rectangle(0, 0, w - 1, h - 1, outline=ODAK_CERCVE, width=1)
        c.create_text(w // 2, ty, text=self._metin, fill=yazi, font=self._font)

    def _bas(self, _e=None):
        if not self._enabled:
            return
        self._basili = True
        self._ciz()

    def _birak(self, _e=None):
        if not self._enabled:
            return
        self._basili = False
        self._ciz()
        if self._menu is not None:
            try:
                self._menu.tk_popup(
                    self.winfo_rootx(),
                    self.winfo_rooty() + self._gh,
                )
            finally:
                try:
                    self._menu.grab_release()
                except tk.TclError:
                    pass
            return
        if self._komut:
            self._komut()

    def _gir(self, _e=None):
        self._hover = True
        self._ciz()

    def _cik(self, _e=None):
        self._hover = False
        self._basili = False
        self._ciz()

    def _odak_gir(self, _e=None):
        self._odak = True
        self._ciz()

    def _odak_cik(self, _e=None):
        self._odak = False
        self._ciz()

    def _klavye_tetikle(self, _e=None):
        self._birak()
        return "break"

    def set_text(self, metin: str) -> None:
        self._metin = metin
        self._ciz()

    def set_rol(self, rol: str) -> None:
        self._rol = rol
        self._ciz()

    def set_enabled(self, aktif: bool) -> None:
        self._enabled = bool(aktif)
        try:
            self._canvas.configure(cursor="hand2" if self._enabled else "arrow")
        except tk.TclError:
            pass
        self._ciz()

    def _configure_api(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        elif cnf is not None and not kw:
            # configure("text") tarzı
            return self._cget_api(cnf)
        if "text" in kw:
            self.set_text(str(kw.pop("text")))
        if "state" in kw:
            st = str(kw.pop("state")).lower()
            self.set_enabled(st != "disabled")
        if "rol" in kw:
            self.set_rol(str(kw.pop("rol")))
        if "menu" in kw:
            self._menu = kw.pop("menu")
        if "command" in kw:
            self._komut = kw.pop("command")
        # bg/fg gibi tk.Button alanları yok sayılır (oval çizim yönetir)
        for k in (
            "bg",
            "fg",
            "activebackground",
            "activeforeground",
            "disabledforeground",
            "cursor",
        ):
            kw.pop(k, None)
        if kw:
            return tk.Frame.configure(self, **kw)
        return None

    def _cget_api(self, key):
        if key == "text":
            return self._metin
        if key == "state":
            return "normal" if self._enabled else "disabled"
        if key == "menu":
            return self._menu
        return tk.Frame.cget(self, key)


def oval_buton(
    parent,
    metin: str,
    komut: Callable | None = None,
    *,
    rol: str = "yardimci",
    state: str = "normal",
    menu: tk.Menu | None = None,
    grup: str = "dis",
    **kwargs,
) -> FaturaOvalButon:
    """Satış faturası oval 3D buton. grup='panel' | 'dis'."""
    return FaturaOvalButon(
        parent, metin, komut, rol=rol, state=state, menu=menu, grup=grup, **kwargs
    )


def tk_buton(
    parent,
    metin: str,
    komut: Callable | None = None,
    *,
    rol: str = "kaydet",
    state: str = "normal",
    **kwargs,
) -> tk.Button | FaturaOvalButon:
    """Düz düğme (varsayılan). Satış faturasında `oval=True` veya `oval_buton` kullan.

    İlgisiz ekranlara oval stil yayılmaz.
    """
    oval = bool(kwargs.pop("oval", False))
    menu = kwargs.pop("menu", None)
    if oval:
        return oval_buton(
            parent, metin, komut, rol=rol, state=state, menu=menu, **kwargs
        )
    stiller = {
        "kaydet": (LACIVERT, BEYAZ, LACIVERT_HOVER),
        "onay": (BASARI, BEYAZ, BASARI_HOVER),
        "vurgu": (SARI, LACIVERT, SARI_HOVER),
        "ikincil": (BEYAZ, LACIVERT, ACIK_BG),
        "uyari": (UYARI, BEYAZ, UYARI_HOVER),
        "tehlike": (IPTAL, BEYAZ, IPTAL_HOVER),
        "yazdir": (LACIVERT_ORTA, BEYAZ, LACIVERT),
    }
    bg, fg, active = stiller.get(rol, stiller["kaydet"])
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    return tk.Button(
        parent,
        text=metin,
        command=komut,
        bg=bg,
        fg=fg,
        activebackground=active,
        activeforeground=fg,
        relief="flat",
        bd=0,
        padx=10,
        pady=5,
        font=font(10, "bold", root),
        cursor="hand2" if state == "normal" else "arrow",
        state=state,
        highlightthickness=1 if rol == "ikincil" else 0,
        highlightbackground=CIZGI if rol == "ikincil" else bg,
        disabledforeground=IKINCIL,
        **kwargs,
    )


def beyaz_kart(parent, *, padx: int = 10, pady: int = 8) -> tuple[tk.Frame, tk.Frame]:
    dis = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    ic = tk.Frame(dis, bg=BEYAZ)
    ic.pack(fill="both", expand=True, padx=padx, pady=pady)
    return dis, ic


def durum_rozet(parent, metin: str) -> tk.Label:
    """Durum rozeti; metne göre renk seçilir."""
    anahtar = (metin or "TASLAK").strip().upper()
    bg, fg = DURUM_RENKLERI.get(anahtar, DURUM_RENKLERI["TASLAK"])
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    return tk.Label(
        parent,
        text=anahtar,
        bg=bg,
        fg=fg,
        font=font(9, "bold", root),
        padx=10,
        pady=3,
    )


def rozet_guncelle(label: tk.Label, metin: str) -> None:
    anahtar = (metin or "TASLAK").strip().upper()
    bg, fg = DURUM_RENKLERI.get(anahtar, DURUM_RENKLERI["TASLAK"])
    try:
        label.configure(text=anahtar, bg=bg, fg=fg)
    except tk.TclError:
        pass


def ust_toolbar(
    parent,
    *,
    baslik: str = "SATIŞ FATURASI",
    fatura_no: str = "",
    musteri_kisa: str = "",
    durum: str = "TASLAK",
) -> dict:
    """Sabit üst araç çubuğu iskeleti. Dönen dict widget referansları içerir."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    cubuk = tk.Frame(parent, bg=LACIVERT, highlightthickness=0)
    cubuk.pack(side="top", fill="x")

    sol = tk.Frame(cubuk, bg=LACIVERT)
    sol.pack(side="left", fill="y", padx=(10, 6), pady=4)

    tk.Label(
        sol,
        text=baslik,
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(14, "bold", root),
        anchor="w",
    ).pack(anchor="w")

    meta = tk.Frame(sol, bg=LACIVERT)
    meta.pack(anchor="w", pady=(4, 0))

    no_lbl = tk.Label(
        meta,
        text=fatura_no or "—",
        bg=LACIVERT,
        fg=SARI,
        font=font(11, "bold", root),
    )
    no_lbl.pack(side="left", padx=(0, 10))

    rozet = durum_rozet(meta, durum)
    rozet.pack(side="left", padx=(0, 10))

    musteri_lbl = tk.Label(
        meta,
        text=(musteri_kisa or "")[:48],
        bg=LACIVERT,
        fg=BEYAZ,
        font=font(10, root=root),
    )
    musteri_lbl.pack(side="left")

    # Sağ: dar pencerede 2–3 satıra sarılabilir kompakt işlem butonları
    sag_dis = tk.Frame(cubuk, bg=LACIVERT)
    sag_dis.pack(side="right", padx=6, pady=3)
    sag = tk.Frame(sag_dis, bg=LACIVERT)
    sag.pack(side="top", anchor="e")
    sag2 = tk.Frame(sag_dis, bg=LACIVERT)
    sag3 = tk.Frame(sag_dis, bg=LACIVERT)
    # sag2/sag3 yalnızca taşan butonlar olduğunda pack edilir

    # Sarı ayırıcı çizgi
    tk.Frame(cubuk, bg=SARI, height=2).pack(side="bottom", fill="x")

    return {
        "cubuk": cubuk,
        "sol": sol,
        "sag": sag,
        "sag2": sag2,
        "sag3": sag3,
        "sag_dis": sag_dis,
        "fatura_no": no_lbl,
        "rozet": rozet,
        "musteri": musteri_lbl,
    }


def alt_ozet_cubugu(parent, *, pack: bool = True) -> dict:
    """Sabit alt özet: dar Notlar | Fiyat Analiz çalışma | sağ toplamlar.

    pack=False ise çağıran sticky_footer_layout ile grid'e yerleştirir.
    """
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis = tk.Frame(parent, bg=ACIK_BG, highlightthickness=0)
    if pack:
        dis.pack(side="bottom", fill="x")

    kart_dis, kart = beyaz_kart(dis, padx=8, pady=4)
    kart_dis.pack(fill="x", padx=6, pady=(2, 4))

    # Notlar dar (sol) · Analiz çalışma (orta) · Toplamlar (sağ)
    kart.columnconfigure(0, weight=0, minsize=140)
    kart.columnconfigure(1, weight=1, minsize=200)
    kart.columnconfigure(2, weight=0)

    sol = tk.Frame(kart, bg=BEYAZ)
    sol.grid(row=0, column=0, sticky="nsw", padx=(0, 8))

    tk.Label(
        sol,
        text="Notlar",
        bg=BEYAZ,
        fg=LACIVERT,
        font=font(8, "bold", root),
        anchor="w",
    ).pack(anchor="w", pady=(4, 0))
    not_alani = tk.Text(
        sol,
        height=5,
        width=18,
        wrap="word",
        font=font(8, root=root),
        relief="solid",
        bd=1,
    )
    not_alani.pack(fill="y", expand=False, pady=(2, 0), anchor="w")

    # ——— Fiyat Analiz çalışma ekranı (İşlem Türü / % / Tutar) ———
    analiz = tk.Frame(kart, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    analiz.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=2)
    islem = tk.Frame(analiz, bg=BEYAZ)
    islem.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 2))
    tk.Label(
        analiz,
        text="Fiyat Analiz / Çalışma",
        bg=BEYAZ,
        fg=LACIVERT,
        font=font(8, "bold", root),
        anchor="w",
    ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 2))

    degerler: dict[str, tk.Widget] = {}
    ttk.Label(analiz, text="İşlem Türü").grid(row=2, column=0, sticky="w", padx=6, pady=2)
    islem_turu = ttk.Combobox(
        analiz,
        values=("—", "İndirim", "Masraf"),
        state="readonly",
        width=12,
        font=font(9, root=root),
    )
    islem_turu.set("—")
    islem_turu.grid(row=2, column=1, sticky="w", padx=(0, 6), pady=2)
    degerler["islem_turu"] = islem_turu

    ttk.Label(analiz, text="İşlem % (yüzde)").grid(row=3, column=0, sticky="w", padx=6, pady=2)
    islem_oran = ttk.Entry(analiz, width=12, justify="right", font=font(9, root=root))
    islem_oran.insert(0, "0")
    islem_oran.grid(row=3, column=1, sticky="w", padx=(0, 6), pady=2)
    degerler["islem_oran"] = islem_oran

    ttk.Label(analiz, text="İşlem Tutarı").grid(row=4, column=0, sticky="w", padx=6, pady=2)
    islem_tutar = ttk.Entry(analiz, width=12, justify="right", font=font(9, root=root))
    islem_tutar.insert(0, "0,00")
    islem_tutar.grid(row=4, column=1, sticky="w", padx=(0, 6), pady=2)
    degerler["islem_tutar"] = islem_tutar

    tk.Label(
        analiz,
        text="İndirim veya Masraf seç → % veya tutar gir → Net/Uzlaşılan güncellenir",
        bg=BEYAZ,
        fg=IKINCIL,
        font=font(7, root=root),
        wraplength=280,
        justify="left",
        anchor="w",
    ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 4))

    sag = tk.Frame(kart, bg=BEYAZ)
    sag.grid(row=0, column=2, sticky="ne")

    # Ara → KDV → Brüt → İndirim/Masraf (%+tutar) → Net
    satirlar = (
        ("ara_toplam", "Ara Toplam", False, False),
        ("iskonto", "Toplam İskonto", False, False),
        ("matrah", "KDV Matrahı", False, False),
        ("kdv", "KDV Toplamı", False, False),
        ("brut", "Brüt Toplam", False, False),
        ("indirim", "İndirim", False, True),
        ("masraf", "Masraf", False, True),
        ("genel", "Net Toplam", True, False),
        ("doviz", "Döviz Karşılığı", False, False),
    )
    tk.Label(sag, text="%", bg=BEYAZ, fg=IKINCIL, font=font(7, root=root), anchor="e").grid(
        row=0, column=1, sticky="e", padx=(0, 6)
    )
    tk.Label(sag, text="Tutar", bg=BEYAZ, fg=IKINCIL, font=font(7, root=root), anchor="e").grid(
        row=0, column=2, sticky="e"
    )
    for i, (anahtar, baslik, vurgulu, yuzde_var) in enumerate(satirlar, start=1):
        fg = LACIVERT if vurgulu else IKINCIL
        fnt = font(12 if vurgulu else 9, "bold" if vurgulu else "normal", root)
        pad_y = 2 if vurgulu else 0
        tk.Label(sag, text=baslik, bg=BEYAZ, fg=fg, font=fnt, anchor="e").grid(
            row=i, column=0, sticky="e", padx=(0, 8), pady=pad_y
        )
        if yuzde_var:
            oran_lbl = tk.Label(
                sag,
                text="%0,00",
                bg=BEYAZ,
                fg=METIN,
                font=font(9, root=root),
                anchor="e",
                width=7,
            )
            oran_lbl.grid(row=i, column=1, sticky="e", padx=(0, 6), pady=pad_y)
            degerler[f"{anahtar}_oran"] = oran_lbl
        else:
            tk.Label(sag, text="", bg=BEYAZ, width=7).grid(row=i, column=1, pady=pad_y)
        lbl = tk.Label(
            sag,
            text="0,00 TL" if anahtar != "doviz" else "—",
            bg=BEYAZ,
            fg=LACIVERT if vurgulu else METIN,
            font=font(12 if vurgulu else 9, "bold", root),
            anchor="e",
            width=12,
        )
        lbl.grid(row=i, column=2, sticky="e", pady=pad_y)
        degerler[anahtar] = lbl

    ipucu = tk.Label(
        sag,
        text="Brüt sabit (ölçüm) · Net = Uzlaşılan · Fiyat uydur Brüt’ü bozmaz",
        bg=BEYAZ,
        fg=IKINCIL,
        font=font(7, root=root),
        anchor="e",
    )
    ipucu.grid(row=len(satirlar) + 1, column=0, columnspan=3, sticky="e", pady=(1, 0))

    return {
        "dis": dis,
        "kart": kart,
        "not_alani": not_alani,
        "degerler": degerler,
        "sag": sag,
        "sol": sol,
        "analiz": analiz,
        "islem": islem,
    }


_LACIVERT_TONLARI = frozenset(
    c.lower() for c in (LACIVERT, LACIVERT_ORTA, LACIVERT_HOVER, "#1B2A4A")
)
_SARI_TONLARI = frozenset(c.lower() for c in (SARI, SARI_HOVER))


def _ters_zemin(renk: str) -> str | None:
    r = (renk or "").lower()
    if r in _LACIVERT_TONLARI:
        return SARI_HOVER if r == LACIVERT_HOVER.lower() else SARI
    if r in _SARI_TONLARI:
        return LACIVERT_HOVER if r == SARI_HOVER.lower() else LACIVERT
    return None


def _ters_yazi(zemin_eski: str, yazi: str) -> str | None:
    """Sarıya dönen zeminde yazı lacivert, laciverte dönen zeminde sarı olur."""
    z = (zemin_eski or "").lower()
    y = (yazi or "").lower()
    if z in _LACIVERT_TONLARI and y in {BEYAZ.lower(), "#ffffff", "white"} | _SARI_TONLARI:
        return LACIVERT
    if z in _SARI_TONLARI and y in _LACIVERT_TONLARI | {METIN.lower()}:
        return SARI
    return None


def renkleri_tersle(kok, *, haric=()) -> None:
    """Kurumsal lacivert/sarı zeminli tk widget'larında renkleri yer değiştirir.

    ttk widget'ları ve durum renkleri (yeşil/kırmızı vb.) değişmez; her widget bir kez işlenir.
    """
    haric_idler = {str(w) for w in haric if w is not None}
    yigin = [kok]
    while yigin:
        w = yigin.pop()
        try:
            yigin.extend(w.winfo_children())
        except tk.TclError:
            continue
        if str(w) in haric_idler or getattr(w, "_ters_renk_uygulandi", False):
            continue
        try:
            bg = str(w.cget("bg"))
        except (tk.TclError, AttributeError):
            continue
        yeni_bg = _ters_zemin(bg)
        ayar: dict[str, str] = {}
        if yeni_bg:
            ayar["bg"] = yeni_bg
            for anahtar in ("fg", "activeforeground"):
                try:
                    yeni = _ters_yazi(bg, str(w.cget(anahtar)))
                except tk.TclError:
                    continue
                if yeni:
                    ayar[anahtar] = yeni
        for anahtar in ("activebackground", "highlightbackground"):
            try:
                yeni = _ters_zemin(str(w.cget(anahtar)))
            except tk.TclError:
                continue
            if yeni:
                ayar[anahtar] = yeni
        if not ayar:
            continue
        try:
            w.configure(**ayar)
            w._ters_renk_uygulandi = True
        except tk.TclError:
            pass


def validation_panel(parent) -> dict:
    """Onay öncesi kısa doğrulama paneli (gizlenebilir)."""
    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis = tk.Frame(parent, bg="#FEF3C7", highlightthickness=1, highlightbackground=UYARI)
    metin = tk.Label(
        dis,
        text="",
        bg="#FEF3C7",
        fg="#92400E",
        font=font(9, root=root),
        justify="left",
        anchor="w",
        wraplength=900,
    )
    metin.pack(fill="x", padx=10, pady=6)
    return {"dis": dis, "metin": metin}
