"""Hızlı Satış ve Tahsilat — Aşama 8: çıktı / gün sonu / log (+ 5–7).

Sepet bellekte; Ödeme/Tamamla → tahsilat → HizliSatisService (tek transaction).
Başarıda fiş/A4/PDF diyalogu (yazıcı hatası satışı bozmaz).
F8 beklet / F9 çağır; İPTAL; GÜN SONU.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from birim_hatasi_ui import birim_hatasi_goster

from database.access import AccessError, yetki_var
from database.cari_service import CariService
from database.hizli_satis_service import HizliSatisService, VARSAYILAN_DEPO
from database.session_manager import oturum
from database.stok_service import StokService
from hizli_satis_bekleyen_ui import HizliSatisBekleyenDialog
from hizli_satis_cikti_ui import a4_yazdir, basari_dialog_goster, fis_yazdir, pdf_kaydet
from hizli_satis_gun_sonu_ui import HizliSatisGunSonuDialog
from hizli_satis_iptal_ui import HizliSatisIptalIadeDialog
from hizli_satis_log import islem_yaz
from cari_arama_alani import CariAramaAlani
from hizli_satis_musteri import (
    IZIN_ACIK_HESAP,
    IZIN_IPTAL,
    PERAKENDE_MUSTERI_UNVAN,
    FiyatDegisiklikGunlugu,
    acik_hesap_risk_degerlendir,
    cari_ozet_coz,
    cari_ozet_dict,
    fiyat_degistirme_izinli,
    fiyat_listesi_coz,
    iptal_iade_izinli,
    iskonto_degistirme_sonucu,
    varsayilan_cari_coz,
)
from hizli_satis_sepet import HizliSatisSepet, KDV_ORANLARI, VARSAYILAN_KDV
from hizli_satis_tahsilat_ui import HizliSatisTahsilatDialog
from hizli_satis_urun_panel_ui import HizliSatisUrunPanel
from stok_arama_alani import StokAramaAlani
from urun_sec_ui import UrunSecDialog

# Talimat renkleri: sarı / koyu gri; tamamla yeşil; iptal kırmızı; beklet turuncu
SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
KIRMIZI = "#C62828"
TURUNCU = "#EF6C00"
BEYAZ = "#FFFFFF"


def _para(tutar) -> str:
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _para_alani_metni(tutar) -> str:
    """Entry için TL'siz tutar metni (1.234,56)."""
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _para_parse(metin: str) -> Decimal:
    """Türkçe tutar metnini Decimal'e çevirir (1.050,00 / 1050,5 / 1050)."""
    ham = (metin or "").strip().replace("TL", "").replace("tl", "").strip()
    if not ham:
        return Decimal("0")
    if "," in ham and "." in ham:
        ham = ham.replace(".", "").replace(",", ".")
    elif "," in ham:
        ham = ham.replace(",", ".")
    return Decimal(ham)


SEPET_SUTUNLARI = ("sıra", "kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "toplam")


def _hedef_metni_coz(metin: str) -> Decimal | None:
    """Yeni Toplam girişi: boş/eksik → None (hesap yok); negatif / sayısal olmayan → ValueError."""
    ham = (metin or "").replace("TL", "").replace("tl", "").strip()
    if not ham or ham in ("-", "+") or ham[-1] in ",.":
        return None
    if ham.startswith("-"):
        raise ValueError("Yeni toplam negatif olamaz.")
    try:
        deger = _para_parse(ham)
    except Exception as exc:
        raise ValueError("Yeni toplam sayısal bir tutar olmalıdır.") from exc
    if not deger.is_finite():
        raise ValueError("Yeni toplam sayısal bir tutar olmalıdır.")
    return deger.quantize(Decimal("0.01"))


def _fiyat_metni(tutar) -> str:
    """Birim fiyat (en çok 4 ondalık, en az 2) — 1.234,5678 / 12,50."""
    d = Decimal(str(tutar)).quantize(Decimal("0.0001"))
    metin = f"{d:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
    tam, _, kesir = metin.partition(",")
    kesir = kesir.rstrip("0")
    return f"{tam},{kesir.ljust(2, '0')}"


def _miktar_goster(miktar: Decimal) -> str:
    d = Decimal(str(miktar))
    if d == d.to_integral_value():
        return str(int(d))
    metin = format(d, "f").rstrip("0").rstrip(".")
    return metin or "0"


def _dialog_hucre_altina(
    dialog: tk.Toplevel,
    tree: ttk.Treeview,
    *,
    item: str | None = None,
    column: str = "miktar",
    event=None,
    gap: int = 4,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """Diyaloğu treeview hücresinin hemen altına yerleştirir; bbox yoksa üst pencere ortası."""
    try:
        dialog.update_idletasks()
        w = width or dialog.winfo_reqwidth() or dialog.winfo_width()
        h = height or dialog.winfo_reqheight() or dialog.winfo_height()
        if w < 2:
            w = 280
        if h < 2:
            h = 120

        x = y = None
        hedef = item
        if event is not None and not hedef:
            try:
                hedef = tree.identify_row(event.y)
            except tk.TclError:
                hedef = None
        if not hedef:
            secim = tree.selection()
            hedef = secim[0] if secim else None

        box = None
        if hedef:
            try:
                box = tree.bbox(hedef, column)
            except tk.TclError:
                box = None
            if not box and event is not None:
                try:
                    col_id = tree.identify_column(event.x)
                    if col_id:
                        box = tree.bbox(hedef, col_id)
                except tk.TclError:
                    box = None

        if box:
            bx, by, bw, bh = box
            x = tree.winfo_rootx() + bx
            y = tree.winfo_rooty() + by + bh + gap
        else:
            parent = dialog.master
            try:
                pw = max(parent.winfo_width(), 1)
                ph = max(parent.winfo_height(), 1)
                x = parent.winfo_rootx() + (pw - w) // 2
                y = parent.winfo_rooty() + (ph - h) // 2
            except tk.TclError:
                x = y = None

        if x is None or y is None:
            sw = dialog.winfo_screenwidth()
            sh = dialog.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
        else:
            sw = dialog.winfo_screenwidth()
            sh = dialog.winfo_screenheight()
            x = min(max(0, int(x)), max(0, sw - w))
            y = min(max(0, int(y)), max(0, sh - h))

        dialog.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        pass

def _uyari_sesi() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        try:
            import winsound

            winsound.Beep(880, 180)
        except Exception:
            pass


def _yetki_hizli_satis(parent) -> bool:
    """Aşama 1/2: mevcut satış görüntüleme/düzenleme yetkisini yeniden kullan."""
    if oturum.role_kod == "YONETICI":
        return True
    if yetki_var("satis_duzenleme", "satis_goruntuleme", "goruntuleme"):
        return True
    messagebox.showwarning(
        "Yetki",
        "Hızlı Satış ekranına erişim için satış yetkisi gerekir.",
        parent=parent,
    )
    return False


def hizli_satis_goster(app) -> None:
    """Ana menü → HIZLI SATIŞ: içerik özeti + geniş POS penceresi."""
    if not _yetki_hizli_satis(app):
        app.sayfa_goster("giris")
        return

    for anahtar, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "hizli_satis" else "Menu.TButton"
        )

    app._icerigi_temizle()
    ttk.Label(app.icerik, text="HIZLI SATIŞ", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
            text=(
            "Tahsilat, beklet, iptal/iade, fiş/PDF ve gün sonu (Aşama 8). "
            "Klasik «Hızlı Satış Faturası»ndan ayrıdır."
        ),
    ).pack(anchor="w", pady=(8, 12))
    ttk.Button(
        app.icerik,
        text="Hızlı Satış Ekranını Aç",
        style="AltMenu.TButton",
        command=lambda: _pencere_ac(app),
    ).pack(anchor="w")

    _pencere_ac(app)


def _pencere_ac(app) -> None:
    mevcut = getattr(app, "_hizli_satis_pencere", None)
    if mevcut is not None:
        try:
            if mevcut.winfo_exists():
                mevcut.lift()
                mevcut.focus_force()
                return
        except tk.TclError:
            pass
    app._hizli_satis_pencere = HizliSatisPencere(app)


class HizliSatisStokArama(StokAramaAlani):
    """Kasada Enter en iyi eşleşmeyi sepete atsın diye ilk sonuç seçili gelir."""

    ILK_SONUC_SECILI = True


class HizliSatisPencere(tk.Toplevel):
    """5 bölgeli Hızlı Satış; Aşama 5: tahsilat + fatura kaydı."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("HIZLI SATIŞ")
        self.configure(bg=KOYU_GRI)
        self.geometry("1280x760")
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        self.minsize(1100, 650)
        self.transient(parent)

        self.sepet_model = HizliSatisSepet()
        self.secili_cari: dict | None = None
        self.odeme_niyeti: str | None = None  # NAKİT / AÇIK HESAP / KK…
        self.fiyat_gunlugu = FiyatDegisiklikGunlugu()
        self._kayit_devam = False
        self._son_fatura_id: int | None = None
        self._stil_ayarla()
        self._iskelet_kur()
        self._kisayollar_bagla()
        self._varsayilan_musteri_yukle()
        self.protocol("WM_DELETE_WINDOW", self._kapat)
        self.bind("<Escape>", lambda _e: self._kapat())

    def _stil_ayarla(self) -> None:
        stil = ttk.Style(self)
        stil.configure(
            "HsBaslik.TLabel",
            font=("Segoe UI", 14, "bold"),
            foreground=SARİ,
            background=KOYU_GRI,
        )
        stil.configure("HsBolum.TLabelframe", background=ACIK_GRI)
        stil.configure(
            "HsBolum.TLabelframe.Label",
            font=("Segoe UI", 10, "bold"),
            foreground=KOYU_GRI,
        )
        stil.configure("HsPlaceholder.TLabel", foreground="#6B7280", background=ACIK_GRI)
        stil.configure(
            "HsDurum.TLabel",
            foreground=KOYU_GRI,
            background=ACIK_GRI,
            font=("Segoe UI", 9),
        )
        stil.configure(
            "HsTamamla.TButton",
            font=("Segoe UI", 11, "bold"),
            foreground=BEYAZ,
            background=YESIL,
            padding=(16, 12),
        )
        stil.map("HsTamamla.TButton", background=[("active", "#1B5E20"), ("!disabled", YESIL)])
        stil.configure(
            "HsIptal.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground=BEYAZ,
            background=KIRMIZI,
            padding=(12, 10),
        )
        stil.map("HsIptal.TButton", background=[("active", "#8E0000"), ("!disabled", KIRMIZI)])
        stil.configure(
            "HsBeklet.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground=BEYAZ,
            background=TURUNCU,
            padding=(12, 10),
        )
        stil.map("HsBeklet.TButton", background=[("active", "#E65100"), ("!disabled", TURUNCU)])

    def _iskelet_kur(self) -> None:
        kok = tk.Frame(self, bg=KOYU_GRI, padx=8, pady=8)
        kok.pack(fill="both", expand=True)
        kok.rowconfigure(1, weight=1)
        kok.columnconfigure(0, weight=1)

        # —— Üst: barkod + arama + müşteri ——
        ust = tk.LabelFrame(
            kok,
            text=" Barkod / Arama / Müşteri ",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            padx=8,
            pady=8,
        )
        ust.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ust.columnconfigure(1, weight=1)
        ust.columnconfigure(3, weight=1)

        tk.Label(ust, text="Barkod", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.barkod_entry = ttk.Entry(ust, width=28)
        self.barkod_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.barkod_entry.bind("<Return>", self._barkod_okut)

        from belge_kullanici_ui import aktif_kullanici_adi

        tk.Label(ust, text="Kasiyer / İşlemi Yapan", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.kasiyer_label = tk.Label(
            ust,
            text=aktif_kullanici_adi(),
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self.kasiyer_label.grid(row=1, column=1, sticky="w", pady=(6, 0))

        def _hs_dirty():
            if self.sepet_model.satirlar:
                return "unsaved"
            return "empty"

        def _hs_meta():
            return ("hizli_satis", getattr(self, "_son_fatura_id", None))

        def _hs_yenile(_yeni=None):
            try:
                from belge_kullanici_ui import aktif_kullanici_adi as _ad

                self.kasiyer_label.configure(text=_ad())
            except Exception:
                pass
            # Yetkileri yeniden uygula
            try:
                from database.access import maliyet_izinli

                _ = maliyet_izinli()
            except Exception:
                pass
            parent = self.master
            while parent and not hasattr(parent, "_oturum_cubugunu_guncelle"):
                parent = getattr(parent, "master", None)
            if parent and hasattr(parent, "_oturum_cubugunu_guncelle"):
                try:
                    parent._oturum_cubugunu_guncelle()
                except Exception:
                    pass

        try:
            from kullanici_degistir_ui import aktif_kullanici_cubugu
            from database.session_manager import oturum as _oturum

            cubuk = aktif_kullanici_cubugu(
                ust,
                active_screen="HIZLI_SATIS",
                get_document_meta=_hs_meta,
                dirty_check=_hs_dirty,
                on_changed=_hs_yenile,
                bg=ACIK_GRI,
            )
            cubuk["cerceve"].grid(row=1, column=2, columnspan=2, sticky="w", padx=(12, 0), pady=(6, 0))
            self._aktif_kullanici_cubugu = cubuk
            _oturum.on_user_changed(lambda o, n: _hs_yenile(n))
        except Exception:
            pass

        tk.Label(ust, text="Ürün Ara", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        self.arama_entry = ttk.Entry(ust, width=28)
        self.arama_entry.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        self._urun_arama = HizliSatisStokArama(
            self,
            self.arama_entry,
            on_secim=self._stok_karti_secildi,
            secili_ad=lambda: "",
        )
        self.arama_entry.bind("<Return>", self._urun_arama_enter)
        self.arama_entry.bind("<KP_Enter>", self._urun_arama_enter)
        ttk.Button(ust, text="Ara (F1)", command=self._manuel_arama_ac).grid(
            row=0, column=4, padx=(0, 12)
        )

        tk.Label(ust, text="Müşteri", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=0, column=5, sticky="w", padx=(0, 6)
        )
        self.musteri_entry = ttk.Entry(ust, width=28)
        self.musteri_entry.grid(row=0, column=6, sticky="ew")
        self.musteri_entry.insert(0, PERAKENDE_MUSTERI_UNVAN)
        self._musteri_arama = CariAramaAlani(
            self,
            self.musteri_entry,
            cari_turu="Müşteri",
            on_secim=self._musteri_aramadan_secildi,
            on_temizle=lambda: None,
            secili_ad=self._musteri_gorunen_metin,
            kayit_adi="Müşteri",
        )
        self.musteri_entry.bind(
            "<FocusIn>", lambda _e: self.musteri_entry.selection_range(0, "end"), add="+"
        )
        self.musteri_entry.bind(
            "<FocusOut>", lambda _e: self.after(250, self._musteri_metin_geri_yukle), add="+"
        )
        ttk.Button(ust, text="Seç (F2)", command=self._musteri_sec_ac).grid(
            row=0, column=7, padx=(6, 0)
        )
        ust.columnconfigure(6, weight=1)

        # Müşteri adının altı: bakiye · valör (sol) | fiyat listesi (sağ)
        musteri_alt = tk.Frame(ust, bg=ACIK_GRI)
        musteri_alt.grid(row=1, column=6, columnspan=2, sticky="ew", pady=(6, 0))
        self.bakiye_lbl = tk.Label(
            musteri_alt, text="", bg=ACIK_GRI, fg=KOYU_GRI, font=("Segoe UI", 9, "bold"), anchor="w"
        )
        self.bakiye_lbl.pack(side="left")
        self.valor_lbl = tk.Label(
            musteri_alt, text="", bg=ACIK_GRI, fg=KOYU_GRI, font=("Segoe UI", 9), anchor="w"
        )
        self.valor_lbl.pack(side="left", padx=(10, 0))
        self._bakiye_seq = 0

        self.fiyat_grup_lbl = ttk.Label(
            musteri_alt,
            text="Fiyat: SATIŞ FİYATI 1",
            style="HsDurum.TLabel",
        )
        self.fiyat_grup_lbl.pack(side="right")

        self.durum_lbl = ttk.Label(
            ust,
            text=(
                "Barkod okutun, grup seçin veya ürün / müşteri adından 2 harf yazın. "
                "F1: ara · F2: müşteri."
            ),
            style="HsDurum.TLabel",
        )
        self.durum_lbl.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        # —— Orta: sol gruplar | orta kartlar | sağ sepet ——
        orta = tk.Frame(kok, bg=KOYU_GRI)
        orta.grid(row=1, column=0, sticky="nsew")
        orta.columnconfigure(0, weight=0, minsize=180)
        orta.columnconfigure(1, weight=3)
        orta.columnconfigure(2, weight=2, minsize=320)
        orta.rowconfigure(0, weight=1)

        sol = tk.LabelFrame(
            orta,
            text=" Ürün Grupları ",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            padx=6,
            pady=6,
        )
        sol.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        merkez = tk.LabelFrame(
            orta,
            text=" Ürün Kartları ",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            padx=6,
            pady=6,
        )
        merkez.grid(row=0, column=1, sticky="nsew", padx=(0, 6))

        self.urun_panel = HizliSatisUrunPanel(
            sol,
            merkez,
            on_urun_sec=self._karttan_sepete,
            bg=ACIK_GRI,
            parent_for_dialog=self,
        )

        sag = tk.LabelFrame(
            orta,
            text=" Sepet ",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            padx=6,
            pady=6,
        )
        sag.grid(row=0, column=2, sticky="nsew")
        sag.rowconfigure(0, weight=1)
        sag.columnconfigure(0, weight=1)

        sutunlar = SEPET_SUTUNLARI
        self.sepet = ttk.Treeview(sag, columns=sutunlar, show="headings", height=12, selectmode="browse")
        basliklar = {
            "sıra": "Sıra",
            "kod": "Kod",
            "ad": "Ürün",
            "miktar": "Miktar",
            "birim": "Birim",
            "fiyat": "Fiyat",
            "isk": "İsk %",
            "kdv": "KDV %",
            "toplam": "Toplam",
        }
        genislik = {
            "sıra": 36,
            "kod": 64,
            "ad": 110,
            "miktar": 52,
            "birim": 48,
            "fiyat": 64,
            "isk": 44,
            "kdv": 48,
            "toplam": 72,
        }
        for c in sutunlar:
            self.sepet.heading(c, text=basliklar[c])
            self.sepet.column(c, width=genislik[c], anchor="center" if c != "ad" else "w")
        dikey = ttk.Scrollbar(sag, orient="vertical", command=self.sepet.yview)
        self.sepet.configure(yscrollcommand=dikey.set)
        self.sepet.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        self.sepet.bind("<Delete>", self._satir_sil)
        self.sepet.bind("<Double-1>", self._sepet_cift_tik)
        self.sepet.bind("<Button-1>", self._sepet_tik, add="+")
        self.sepet.bind("<Button-3>", self._sepet_sag_tik)
        self.sepet.bind("<Left>", lambda _e: self._sepet_sutun_kaydir(-1))
        self.sepet.bind("<Right>", lambda _e: self._sepet_sutun_kaydir(1))
        self.sepet.bind("<Return>", self._sepet_enter)
        self._sepet_basliklar = dict(basliklar)
        self._sepet_odak_sutun: str | None = None

        dugmeler = tk.Frame(sag, bg=ACIK_GRI)
        dugmeler.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(dugmeler, text="−", width=3, command=lambda: self._miktar_delta(-1)).pack(
            side="left", padx=2
        )
        ttk.Button(dugmeler, text="+", width=3, command=lambda: self._miktar_delta(1)).pack(
            side="left", padx=2
        )
        ttk.Button(dugmeler, text="Sil (Del)", command=self._satir_sil).pack(side="left", padx=8)
        ttk.Button(dugmeler, text="Fiyat", command=self._fiyat_dialog).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="Birim", command=self._birim_sec).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="İsk %", command=self._iskonto_dialog).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="KDV %", command=self._kdv_dialog).pack(side="left", padx=4)

        self.ozet_lbl = tk.Label(
            sag,
            text="Ara: 0,00  |  İsk: 0,00  |  KDV: 0,00",
            bg=ACIK_GRI,
            fg="#555555",
            font=("Segoe UI", 9),
            anchor="e",
        )
        self.ozet_lbl.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))

        toplam_satir = tk.Frame(sag, bg=ACIK_GRI)
        toplam_satir.grid(row=3, column=0, columnspan=2, sticky="e", pady=(4, 0))

        self.toplam_lbl = tk.Label(
            toplam_satir,
            text="GENEL TOPLAM  0,00 TL",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 16, "bold"),
            anchor="e",
        )
        self.toplam_lbl.pack(side="left", padx=(0, 12))

        self._hedef_toplam_duzenleniyor = False
        tk.Label(
            toplam_satir,
            text="Yeni toplam:",
            bg=ACIK_GRI,
            fg="#555555",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 4))
        self.hedef_toplam_var = tk.StringVar(value="0,00")
        self.hedef_toplam_entry = ttk.Entry(
            toplam_satir,
            textvariable=self.hedef_toplam_var,
            width=12,
            justify="right",
            font=("Segoe UI", 11),
        )
        self.hedef_toplam_entry.pack(side="left")
        self.hedef_toplam_entry.bind("<Return>", self._hedef_toplam_uygula)
        self.hedef_toplam_entry.bind("<FocusIn>", self._hedef_toplam_odak)
        self.hedef_toplam_entry.bind("<FocusOut>", self._hedef_toplam_odak_cikti)
        self._hedef_canli_is = None
        self.hedef_toplam_var.trace_add("write", self._hedef_toplam_yazildi)
        ttk.Button(
            toplam_satir,
            text="Uygula",
            width=8,
            command=self._hedef_toplam_uygula,
        ).pack(side="left", padx=(6, 0))
        self.duzeltme_lbl = tk.Label(
            sag, text="", bg=ACIK_GRI, fg="#6B7280", font=("Segoe UI", 8), anchor="e"
        )
        self.duzeltme_lbl.grid(row=4, column=0, columnspan=2, sticky="e")
        self.odenecek_lbl = tk.Label(
            sag, text="", bg=ACIK_GRI, fg="#1F4E79", font=("Segoe UI", 12, "bold"), anchor="e"
        )
        self.odenecek_lbl.grid(row=5, column=0, columnspan=2, sticky="e")
        self._ek_fon_bedeli = {"tutar": Decimal("0"), "kdv": Decimal("0"), "fonlar": [], "eksik_ayar": ""}

        # —— Alt: beklet / çağır / iptal / gün sonu / tahsilat / tamamla ——
        alt = tk.Frame(kok, bg=KOYU_GRI, pady=6)
        alt.grid(row=2, column=0, sticky="ew")
        for i in range(7):
            alt.columnconfigure(i, weight=1)

        self.btn_beklet = tk.Button(
            alt,
            text="BEKLET (F8)",
            bg=TURUNCU,
            fg=BEYAZ,
            activebackground="#E65100",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=8,
            pady=12,
            command=self._beklet,
        )
        self.btn_beklet.grid(row=0, column=0, sticky="ew", padx=2)

        self.btn_cagir = tk.Button(
            alt,
            text="ÇAĞIR (F9)",
            bg="#FB8C00",
            fg=BEYAZ,
            activebackground="#EF6C00",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=8,
            pady=12,
            command=self._geri_cagir_ac,
        )
        self.btn_cagir.grid(row=0, column=1, sticky="ew", padx=2)

        self.btn_iptal = tk.Button(
            alt,
            text="İPTAL",
            bg=KIRMIZI,
            fg=BEYAZ,
            activebackground="#8E0000",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=8,
            pady=12,
            command=self._iptal_aksiyon,
        )
        self.btn_iptal.grid(row=0, column=2, sticky="ew", padx=2)

        self.btn_gun_sonu = tk.Button(
            alt,
            text="GÜN SONU",
            bg="#455A64",
            fg=BEYAZ,
            activebackground="#37474F",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=8,
            pady=12,
            command=self._gun_sonu_ac,
        )
        self.btn_gun_sonu.grid(row=0, column=3, sticky="ew", padx=2)

        self.btn_odeme = tk.Button(
            alt,
            text="ÖDEME AL (F10)",
            bg=KOYU_GRI,
            fg=SARİ,
            activebackground="#1a1d20",
            activeforeground=SARİ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            highlightbackground=SARİ,
            highlightthickness=2,
            padx=8,
            pady=12,
            command=self._odeme_al,
        )
        self.btn_odeme.grid(row=0, column=4, sticky="ew", padx=2)

        self.btn_tamamla = tk.Button(
            alt,
            text="SATIŞI TAMAMLA (F12)",
            bg=YESIL,
            fg=BEYAZ,
            activebackground="#1B5E20",
            activeforeground=BEYAZ,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=8,
            pady=12,
            command=self._odeme_al,
        )
        self.btn_tamamla.grid(row=0, column=5, columnspan=2, sticky="ew", padx=2)

        alt2 = tk.Frame(kok, bg=KOYU_GRI)
        alt2.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        tk.Button(
            alt2,
            text="Son fişi yazdır",
            bg="#546E7A",
            fg=BEYAZ,
            activebackground="#455A64",
            activeforeground=BEYAZ,
            font=("Segoe UI", 9),
            relief="flat",
            padx=8,
            pady=4,
            command=self._son_fisi_yazdir,
        ).pack(side="left", padx=2)
        tk.Button(
            alt2,
            text="Son A4",
            bg="#546E7A",
            fg=BEYAZ,
            relief="flat",
            padx=8,
            pady=4,
            command=self._son_a4_yazdir,
        ).pack(side="left", padx=2)
        tk.Button(
            alt2,
            text="Son PDF",
            bg="#546E7A",
            fg=BEYAZ,
            relief="flat",
            padx=8,
            pady=4,
            command=self._son_pdf_kaydet,
        ).pack(side="left", padx=2)

        tk.Label(
            kok,
            text=(
                "Esc: kapat · F1: ara · F2: müşteri · F8: beklet · F9: çağır · F10/F12: ödeme · "
                "Sepette ←/→ hücre · Fiyat hücresi F10/sağ tık: fiyat listesi · "
                "Ürün hücresi F10/sağ tık: stok hareketleri · Birim hücresi çift tık: birim"
            ),
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 9),
        ).grid(row=4, column=0, sticky="w", pady=(4, 0))

        self.after(100, lambda: self.barkod_entry.focus_set())
        # Kart ızgarası genişlik hesaplaması için bir kez yenile
        self.after(200, lambda: getattr(self, "urun_panel", None) and self.urun_panel.kartlari_yenile())

    def _kisayollar_bagla(self) -> None:
        self.bind("<F1>", lambda _e: self._manuel_arama_ac())
        self.bind("<F2>", lambda _e: self._musteri_sec_ac())
        self.bind("<F7>", lambda _e: self._satir_sil())
        self.bind("<F8>", lambda _e: self._beklet())
        self.bind("<F9>", lambda _e: self._geri_cagir_ac())
        self.bind("<F10>", self._f10_tusu)
        self.bind("<F12>", lambda _e: self._odeme_al())
        # Ürün / müşteri kutusuna yazarken Delete, + ve − metni düzenler; sepete dokunmaz
        self.bind("<Delete>", lambda e: None if self._arama_alaninda() else self._satir_sil(e))
        for tus, delta in (
            ("<plus>", 1),
            ("<KP_Add>", 1),
            ("<minus>", -1),
            ("<KP_Subtract>", -1),
            # Numpad / ana klavye +/− bazı sistemlerde farklı
            ("<KeyPress-plus>", 1),
            ("<KeyPress-minus>", -1),
        ):
            self.bind(
                tus, lambda _e, d=delta: None if self._arama_alaninda() else self._miktar_delta(d)
            )

    def _arama_alaninda(self) -> bool:
        try:
            odak = self.focus_get()
        except (tk.TclError, KeyError):
            return False
        return odak is not None and odak in (self.arama_entry, self.musteri_entry)

    # —— Müşteri / fiyat grubu ——

    def _aktif_fiyat_listesi(self) -> str:
        cari = self.secili_cari or {}
        return fiyat_listesi_coz(
            satis_fiyat_listesi=cari.get("satis_fiyat_listesi"),
            musteri_grubu=cari.get("musteri_grubu"),
            odeme_niyeti=self.odeme_niyeti,
        )

    def _fiyat_grup_etiket_guncelle(self) -> None:
        liste = self._aktif_fiyat_listesi()
        self.fiyat_grup_lbl.configure(text=f"Fiyat: {liste}")
        if getattr(self, "urun_panel", None) is not None:
            self.urun_panel.fiyat_adi = liste

    def _musteri_gorunen_metin(self) -> str:
        cari = self.secili_cari or {}
        metin = cari.get("unvan") or PERAKENDE_MUSTERI_UNVAN
        kod = cari.get("cari_kodu") or ""
        return f"{kod} — {metin}" if kod else metin

    def _musteri_alani_goster(self) -> None:
        self.musteri_entry.delete(0, "end")
        self.musteri_entry.insert(0, self._musteri_gorunen_metin())

    def _musteri_metin_geri_yukle(self) -> None:
        """Listeden seçim yapılmadan çıkılırsa kutu seçili müşteriyi göstermeye döner."""
        try:
            if not self.musteri_entry.winfo_exists() or self._musteri_arama.acik_mi():
                return
            if self.focus_get() is self.musteri_entry:
                return
        except (tk.TclError, KeyError):
            return
        if self.musteri_entry.get().strip() != self._musteri_gorunen_metin():
            self._musteri_alani_goster()

    def _musteri_aramadan_secildi(self, cari) -> None:
        try:
            ozet = cari_ozet_coz(int(cari.id))
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Müşteri bilgisi alınamadı:\n{exc}", parent=self)
            ozet = None
        if not ozet or not self._musteri_uygula(ozet, risk_kontrol=True, uyari_goster=True):
            self._musteri_alani_goster()
        else:
            try:
                from cari_kart_ui import cari_uyari_goster

                cari_uyari_goster(self, cari)
            except Exception:
                pass
        self.after_idle(self._barkod_odak)

    def _varsayilan_musteri_yukle(self) -> None:
        try:
            from database.database import perakende_cari_hazirla

            perakende_cari_hazirla()
        except Exception:
            pass
        ozet = None
        try:
            ozet = varsayilan_cari_coz()
        except Exception:
            ozet = None
        if ozet:
            self._musteri_uygula(ozet, risk_kontrol=False, uyari_goster=False)
        else:
            self.secili_cari = {
                "id": 0,
                "cari_kodu": "",
                "unvan": PERAKENDE_MUSTERI_UNVAN,
                "musteri_grubu": PERAKENDE_MUSTERI_UNVAN,
                "satis_fiyat_listesi": "SATIŞ FİYATI 1",
                "acik_hesap_risk_limiti": None,
                "bakiye": Decimal("0"),
            }
            self._musteri_alani_goster()
            self._bakiye_valor_yenile()
            self._fiyat_grup_etiket_guncelle()
            self.durum_lbl.configure(
                text="Varsayılan perakende cari bulunamadı — görünen ad kullanılıyor."
            )

    def _musteri_sec_ac(self, _event=None):
        try:
            from app import MusteriSecimDialog, cari_uyari_goster
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Müşteri seçim ekranı açılamadı:\n{exc}", parent=self)
            return "break"

        try:
            musteriler = CariService.aktif_musteriler()
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Müşteri listesi alınamadı:\n{exc}", parent=self)
            return "break"

        bakiyeler: dict = {}
        try:
            ozetler = CariService.listele(arama="", hizli=True, cari_turu="Müşteri")
            for sat in ozetler or []:
                cari_obj = sat.get("cari")
                if cari_obj is not None:
                    bakiyeler[int(cari_obj.id)] = sat.get("bakiye") or Decimal("0")
        except Exception:
            bakiyeler = {}

        def _secildi(cari):
            if cari is None:
                return
            bakiye = bakiyeler.get(int(cari.id), Decimal("0"))
            from hizli_satis_musteri import cari_ozet_dict

            ozet = cari_ozet_dict(cari, bakiye=bakiye)
            if not self._musteri_uygula(ozet, risk_kontrol=True, uyari_goster=True):
                return
            try:
                cari_uyari_goster(self, cari)
            except Exception:
                pass

        MusteriSecimDialog(
            self,
            musteriler=musteriler,
            bakiyeler=bakiyeler,
            on_select=_secildi,
            baslik="Hızlı Satış — Müşteri Seçimi",
            kayit_adi="müşteri",
        )
        return "break"

    def _musteri_uygula(
        self, ozet: dict, *, risk_kontrol: bool = True, uyari_goster: bool = True
    ) -> bool:
        if not ozet:
            return False
        if risk_kontrol:
            sepet_toplam = self.sepet_model.toplamlar()["genel_toplam"]
            sonuc = acik_hesap_risk_degerlendir(
                bakiye=ozet.get("bakiye") or 0,
                risk_limiti=ozet.get("acik_hesap_risk_limiti"),
                ek_tutar=sepet_toplam,
                acik_hesap_yetkisi=yetki_var(IZIN_ACIK_HESAP),
            )
            if sonuc["durum"] == "engel":
                messagebox.showerror("Risk limiti", sonuc["mesaj"], parent=self)
                return False
            if sonuc["durum"] == "uyari" and uyari_goster:
                if not messagebox.askyesno(
                    "Risk uyarısı",
                    sonuc["mesaj"] + "\n\nBu müşteriyi yine de seçmek istiyor musunuz?",
                    parent=self,
                ):
                    return False

        self.secili_cari = ozet
        self._musteri_alani_goster()
        self._bakiye_valor_yenile()
        self._fiyat_grup_etiket_guncelle()
        self._sepet_fiyatlari_yenile()
        if getattr(self, "urun_panel", None) is not None:
            self.urun_panel.kartlari_yenile()
        liste = self._aktif_fiyat_listesi()
        self.durum_lbl.configure(
            text=(
                f"Müşteri: {ozet.get('unvan') or ''}  |  "
                f"Fiyat listesi: {liste}"
            )
        )
        return True

    def _sepet_fiyatlari_yenile(self) -> None:
        """Seçili fiyat listesine göre sepet satır birim fiyatlarını günceller."""
        liste = self._aktif_fiyat_listesi()
        for i, satir in enumerate(self.sepet_model.satirlar):
            try:
                yeni = self._satir_liste_fiyati(satir, liste)
            except Exception:
                continue
            if yeni is None:
                continue
            eski = satir.referans_fiyat
            if Decimal(str(eski)) != Decimal(str(yeni)):
                self.fiyat_gunlugu.ekle(
                    stok_kodu=satir.stok_kodu,
                    alan="birim_fiyat",
                    eski=eski,
                    yeni=yeni,
                    kullanici=getattr(oturum, "kullanici_adi", None),
                    not_=f"müşteri/fiyat listesi → {liste}",
                )
                self.sepet_model.fiyat_ayarla(i, Decimal(str(yeni)))
        self._sepet_yenile()

    @staticmethod
    def _satir_liste_fiyati(satir, liste: str) -> Decimal | None:
        """Satır biriminde liste fiyatı; ana birimde mevcut kural (kart fiyatı)."""
        from types import SimpleNamespace

        from database.stok_service import birim_anahtari
        from fatura_satir_birim_service import _stok_yukle, birim_satis_fiyati_tl

        stok = _stok_yukle(satir.stok_kodu)
        ana = (getattr(stok, "birim", None) or satir.birim or "Adet") if stok else satir.birim
        if stok is None or birim_anahtari(satir.birim) == birim_anahtari(ana):
            return StokService.satis_fiyati_adi_ile(satir.stok_kodu, liste)
        from database.hizli_satis_satir_service import fiyat_adi_normalle

        musteri = SimpleNamespace(satis_fiyat_listesi=fiyat_adi_normalle(liste), musteri_grubu=None)
        return birim_satis_fiyati_tl(satir.stok_kodu, satir.birim, musteri=musteri)

    # —— Barkod / arama ——

    def _barkod_odak(self) -> None:
        try:
            self.barkod_entry.focus_set()
            self.barkod_entry.selection_range(0, "end")
        except tk.TclError:
            pass

    def _barkod_okut(self, _event=None):
        barkod = self.barkod_entry.get().strip()
        self.barkod_entry.delete(0, "end")
        if not barkod:
            self._barkod_odak()
            return "break"
        bulunan = StokService.barkod_ile_bul(barkod)
        if not bulunan:
            _uyari_sesi()
            self.durum_lbl.configure(text=f"Barkod bulunamadı: {barkod}")
            if messagebox.askyesno(
                "Barkod bulunamadı",
                f"«{barkod}» stokta yok.\nManuel ürün araması açılsın mı?",
                parent=self,
            ):
                self.arama_entry.delete(0, "end")
                self.arama_entry.insert(0, barkod)
                self._manuel_arama_ac()
            else:
                self._barkod_odak()
            return "break"
        if bulunan.get("birim_hatasi"):
            _uyari_sesi()
            self.durum_lbl.configure(text=f"Birim tanımsız: {barkod}")
            messagebox.showwarning("Birim", bulunan["birim_hatasi"], parent=self)
            self._barkod_odak()
            return "break"

        self._sepete_ekle_kayit(bulunan)
        self.durum_lbl.configure(
            text=(
                f"{bulunan['stok_kodu']} — {bulunan['stok_adi']}  |  "
                f"+{_miktar_goster(bulunan['miktar'])} {bulunan['birim']}  |  "
                f"Stok: {_miktar_goster(bulunan['mevcut_stok'])}  |  "
                f"{_para(bulunan['birim_fiyat'])}"
            )
        )
        self._barkod_odak()
        return "break"

    def _manuel_arama_ac(self, _event=None):
        self._urun_arama.kapat()
        sorgu = self.arama_entry.get().strip()
        UrunSecDialog(self, query=sorgu, on_select=self._urun_secildi)
        return "break"

    def _urun_arama_enter(self, event=None):
        if self._urun_arama._enter(event) == "break":
            return "break"
        return self._manuel_arama_ac()

    def _stok_karti_secildi(self, stok) -> None:
        """Yazarken açılan listeden seçilen stok kartını sepete ekler."""
        kod = (stok.stok_kodu or "").strip()
        ad = stok.stok_adi or kod
        try:
            mevcut = sum(
                (Decimal(str(lot.kalan_miktar or 0)) for lot in (stok.lotlar or [])), Decimal("0")
            )
        except Exception:
            mevcut = Decimal("0")
        self._sepete_ekle_kayit(
            {
                "stok_id": int(stok.id),
                "stok_kodu": kod,
                "stok_adi": ad,
                "birim": (stok.birim or "Adet").strip() or "Adet",
                "miktar": Decimal("1"),
                "birim_fiyat": StokService.satis_fiyati_1(kod),
                "carpan": Decimal("1"),
                "barkod": None,
                "mevcut_stok": mevcut,
            }
        )
        self.arama_entry.delete(0, "end")
        self.durum_lbl.configure(
            text=f"{kod} — {ad} sepete eklendi  |  Stok: {_miktar_goster(mevcut)}"
        )
        self.after_idle(self._barkod_odak)

    def _urun_secildi(self, degerler) -> None:
        # UrunSecDialog: (kod, ad, birim, stok, fiyat, kaynak)
        if not degerler:
            self._barkod_odak()
            return
        kod = str(degerler[0]).strip()
        ad = str(degerler[1]).strip() if len(degerler) > 1 else kod
        birim = str(degerler[2]).strip() if len(degerler) > 2 else "Adet"
        fiyat = Decimal(str(degerler[4])) if len(degerler) > 4 and str(degerler[4]).strip() else Decimal("0")
        stok_id = 0
        mevcut = Decimal("0")
        # Tam kart bilgisi (id / güncel fiyat)
        for s in StokService.stoklari_filtrele(kod=kod, ad="", limit=5):
            if (s.stok_kodu or "").strip() == kod:
                stok_id = int(s.id)
                ad = s.stok_adi or ad
                birim = (s.birim or birim or "Adet").strip() or "Adet"
                mevcut = sum((lot.kalan_miktar for lot in (s.lotlar or [])), Decimal("0"))
                if fiyat <= 0:
                    fiyat = StokService.satis_fiyati_1(kod)
                break
        if not stok_id:
            messagebox.showwarning("Ürün", "Seçilen stok kartı bulunamadı.", parent=self)
            self._barkod_odak()
            return
        self._sepete_ekle_kayit(
            {
                "stok_id": stok_id,
                "stok_kodu": kod,
                "stok_adi": ad,
                "birim": birim,
                "miktar": Decimal("1"),
                "birim_fiyat": fiyat,
                "carpan": Decimal("1"),
                "barkod": None,
                "mevcut_stok": mevcut,
            }
        )
        self.arama_entry.delete(0, "end")
        self.durum_lbl.configure(
            text=f"{kod} — {ad} sepete eklendi  |  Stok: {_miktar_goster(mevcut)}"
        )
        self._barkod_odak()

    def _karttan_sepete(self, urun: dict) -> None:
        """Ürün kartı tıklanınca bellek sepetine 1 birim ekle."""
        if not urun or not urun.get("stok_id"):
            return
        self._sepete_ekle_kayit(urun)
        self.durum_lbl.configure(
            text=(
                f"{urun.get('stok_kodu')} — {urun.get('stok_adi')} sepete eklendi  |  "
                f"{_para(urun.get('birim_fiyat') or 0)}"
            )
        )
        self._barkod_odak()

    def _sepete_ekle_kayit(self, kayit: dict) -> None:
        fiyat = kayit.get("birim_fiyat")
        liste = self._aktif_fiyat_listesi()
        # Barkod özel fiyatı varsa koru; aksi halde müşteri fiyat listesi
        if kayit.get("barkod") and fiyat is not None and Decimal(str(fiyat)) > 0:
            birim_fiyat = Decimal(str(fiyat))
        else:
            try:
                birim_fiyat = StokService.satis_fiyati_adi_ile(
                    kayit.get("stok_kodu"), liste, varsayilan=fiyat or 0
                )
            except Exception:
                birim_fiyat = Decimal(str(fiyat or 0))
        self.sepet_model.ekle(
            stok_id=int(kayit["stok_id"]),
            stok_kodu=kayit["stok_kodu"],
            stok_adi=kayit["stok_adi"],
            birim=kayit.get("birim") or "Adet",
            miktar=kayit.get("miktar") or Decimal("1"),
            birim_fiyat=birim_fiyat,
            kdv_orani=(
                kayit["kdv_orani"]
                if kayit.get("kdv_orani") is not None
                else VARSAYILAN_KDV
            ),
            carpan=kayit.get("carpan") or Decimal("1"),
            barkod=kayit.get("barkod"),
        )
        self._sepet_yenile()

    # —— Sepet UI ——

    def _secili_index(self) -> int | None:
        secim = self.sepet.selection()
        if not secim:
            return None
        try:
            return int(secim[0])
        except (TypeError, ValueError):
            return None

    def _sepet_yenile(self, secili: int | None = None) -> None:
        onceki = self._secili_index() if secili is None else secili
        for item in self.sepet.get_children():
            self.sepet.delete(item)
        for i, s in enumerate(self.sepet_model.satirlar):
            self.sepet.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    i + 1,
                    s.stok_kodu,
                    s.stok_adi,
                    _miktar_goster(s.miktar),
                    s.birim,
                    f"{float(s.birim_fiyat):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    _miktar_goster(s.iskonto_orani),
                    _miktar_goster(s.kdv_orani),
                    f"{float(s.satir_toplam):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                ),
            )
        if onceki is not None and 0 <= onceki < len(self.sepet_model):
            iid = str(onceki)
            self.sepet.selection_set(iid)
            self.sepet.focus(iid)
            self.sepet.see(iid)
        toplam = self.sepet_model.toplamlar()
        self.ozet_lbl.configure(
            text=(
                f"Ara: {_para(toplam['ara_toplam'])}  |  "
                f"İsk: {_para(toplam['iskonto'])}  |  "
                f"KDV: {_para(toplam['kdv'])}"
                + self._fon_onizleme_metni(toplam["genel_toplam"])
            )
        )
        # Genel Toplam = referans; Yeni Toplam = son satış tutarı (cariye işlenen)
        self.toplam_lbl.configure(text=f"GENEL TOPLAM  {_para(toplam['referans_toplam'])}")
        self._hedef_toplam_alani_yaz(toplam["genel_toplam"])
        fark = toplam["genel_toplam"] - toplam["referans_toplam"]
        try:
            self.duzeltme_lbl.configure(
                text=(
                    f"Yeni Toplam düzeltmesi: {_para(fark)} — satır fiyatları referanstan dağıtıldı"
                    if self.sepet_model.duzeltme_aktif
                    else ""
                )
            )
        except (tk.TclError, AttributeError):
            pass
        self._ek_fon_bedeli_yenile(toplam["genel_toplam"])
        if self.sepet_model.son_degisiklik_duzeltme_kaldirdi:
            self.sepet_model.son_degisiklik_duzeltme_kaldirdi = False
            self.durum_lbl.configure(
                text=(
                    "Sepet değişti — önceki Yeni Toplam düzeltmesi kaldırıldı; "
                    "Genel Toplam yeniden hesaplandı."
                )
            )

    def _sepet_fon_satirlari(self) -> list[dict]:
        return [
            {"urun_kodu": s.stok_kodu, "miktar": s.miktar, "birim_fiyat": s.birim_fiyat,
             "iskonto_orani": s.iskonto_orani, "kdv_orani": s.kdv_orani, "birim_carpani": s.carpan}
            for s in self.sepet_model.satirlar
        ]

    def _ek_fon_bedeli_yenile(self, yeni_toplam) -> None:
        """Faturaya ek fon bedeli: Yeni Toplam ürün toplamıdır; Ödenecek = ürün + bedel + bedel KDV'si."""
        bos = {"tutar": Decimal("0"), "kdv": Decimal("0"), "fonlar": [], "eksik_ayar": ""}
        ozet = HizliSatisService.ek_fon_bedeli_onizleme(self._sepet_fon_satirlari(), yeni_toplam) \
            if len(self.sepet_model) else bos
        self._ek_fon_bedeli = ozet
        lbl = getattr(self, "odenecek_lbl", None)
        if lbl is None:
            return
        try:
            if ozet["tutar"] > 0:
                odenecek = Decimal(str(yeni_toplam)) + ozet["tutar"] + ozet["kdv"]
                lbl.configure(text=(f"Ek fon bedeli: {_para(ozet['tutar'])}  ·  KDV: {_para(ozet['kdv'])}  ·  "
                                    f"ÖDENECEK TOPLAM  {_para(odenecek)} TL"), fg="#1F4E79")
            elif ozet["eksik_ayar"]:
                lbl.configure(text=f"Ek fon bedeli ayarı eksik: {ozet['eksik_ayar']}", fg="#B00020")
            else:
                lbl.configure(text="")
            if ozet["eksik_ayar"] and ozet["tutar"] > 0:
                lbl.configure(text=lbl.cget("text") + f"  ·  Ayar eksik: {ozet['eksik_ayar']}", fg="#B00020")
        except tk.TclError:
            pass

    def _odenecek_toplam(self) -> Decimal:
        urun = self.sepet_model.toplamlar()["genel_toplam"]
        ek = getattr(self, "_ek_fon_bedeli", None) or {}
        return urun + (ek.get("tutar") or Decimal("0")) + (ek.get("kdv") or Decimal("0"))

    def _fon_onizleme_metni(self, yeni_toplam) -> str:
        """Taslak sepet için fon payı önizlemesi; kalıcı kayıt oluşturmaz, fişe yazdırılmaz."""
        if not len(self.sepet_model):
            return ""
        try:
            from database.fon_service import FonService

            paylar = FonService.belge_onizleme([
                {"urun_kodu": s.stok_kodu, "miktar": s.miktar, "birim_fiyat": s.birim_fiyat,
                 "iskonto_orani": s.iskonto_orani, "kdv_orani": s.kdv_orani, "birim_carpani": s.carpan}
                for s in self.sepet_model.satirlar
            ], yeni_toplam)
        except Exception:  # noqa: BLE001
            return ""
        toplam = sum((p["tutar"] for p in paylar), Decimal("0"))
        return f"  |  Fon payı (iç takip): {_para(toplam)}" if toplam > 0 else ""

    def _hedef_toplam_alani_yaz(self, tutar) -> None:
        entry = getattr(self, "hedef_toplam_entry", None)
        if entry is None:
            return
        if getattr(self, "_hedef_toplam_duzenleniyor", False):
            return
        metin = _para_alani_metni(tutar)
        try:
            if self.hedef_toplam_var.get().strip() == metin:
                return
            self.hedef_toplam_var.set(metin)
        except tk.TclError:
            pass

    def _hedef_toplam_odak(self, _event=None):
        self._hedef_toplam_duzenleniyor = True

    def _hedef_canli_iptal(self) -> None:
        if self._hedef_canli_is is not None:
            try:
                self.after_cancel(self._hedef_canli_is)
            except tk.TclError:
                pass
            self._hedef_canli_is = None

    def _hedef_toplam_yazildi(self, *_args) -> None:
        """Yazarken geçerli tutarı kısa bekleme sonrası otomatik uygular."""
        if not getattr(self, "_hedef_toplam_duzenleniyor", False):
            return
        self._hedef_canli_iptal()
        try:
            self._hedef_canli_is = self.after(700, self._hedef_canli_uygula)
        except tk.TclError:
            self._hedef_canli_is = None

    def _hedef_canli_uygula(self) -> None:
        self._hedef_canli_is = None
        if not getattr(self, "_hedef_toplam_duzenleniyor", False) or not self.sepet_model.satirlar:
            return
        try:
            hedef = _hedef_metni_coz(self.hedef_toplam_var.get())
        except ValueError as hata:
            self.durum_lbl.configure(text=f"Yeni Toplam: {hata}")
            return
        if hedef is None or hedef == self.sepet_model.toplamlar()["genel_toplam"]:
            return
        try:
            self.sepet_model.hedef_toplam_uygula(hedef)
        except ValueError as hata:
            self.durum_lbl.configure(text=f"Yeni Toplam uygulanamadı: {hata}")
            return
        self._sepet_yenile()

    def _hedef_toplam_odak_cikti(self, _event=None):
        self._hedef_canli_iptal()
        self._hedef_toplam_duzenleniyor = False
        mevcut = self.sepet_model.toplamlar()["genel_toplam"]
        try:
            yazilan = _hedef_metni_coz(self.hedef_toplam_var.get())
        except ValueError as hata:
            self.durum_lbl.configure(text=f"Yeni Toplam reddedildi: {hata}")
            self._hedef_toplam_alani_yaz(mevcut)
            return
        if yazilan is None or yazilan == mevcut:
            self._hedef_toplam_alani_yaz(mevcut)
            return
        self._hedef_toplam_uygula(odak_barkoda=False)

    def _hedef_toplam_uygula(self, _event=None, *, odak_barkoda: bool = True):
        """Yeni Toplamı referans satır tutarlarına orantılı dağıtır (Genel Toplam sabit)."""
        self._hedef_canli_iptal()
        if not self.sepet_model.satirlar:
            messagebox.showwarning("Yeni toplam", "Önce sepete ürün ekleyin.", parent=self)
            self._hedef_toplam_duzenleniyor = False
            self._hedef_toplam_alani_yaz(Decimal("0"))
            return "break"
        mevcut = self.sepet_model.toplamlar()["genel_toplam"]
        try:
            hedef = _hedef_metni_coz(self.hedef_toplam_var.get())
        except ValueError as hata:
            messagebox.showwarning("Yeni toplam", str(hata), parent=self)
            self._hedef_toplam_duzenleniyor = False
            self._hedef_toplam_alani_yaz(mevcut)
            return "break"
        if hedef is None:
            messagebox.showwarning("Yeni toplam", "Geçerli bir tutar girin.", parent=self)
            self._hedef_toplam_duzenleniyor = False
            self._hedef_toplam_alani_yaz(mevcut)
            return "break"
        if hedef != mevcut:
            try:
                self.sepet_model.hedef_toplam_uygula(hedef)
            except ValueError as hata:
                messagebox.showerror("Yeni toplam", str(hata), parent=self)
                self._hedef_toplam_duzenleniyor = False
                self._hedef_toplam_alani_yaz(mevcut)
                return "break"
        self._hedef_toplam_duzenleniyor = False
        self._sepet_yenile()
        if odak_barkoda:
            self._barkod_odak()
        return "break"

    # —— Müşteri bakiye / valör (Cari kart ile aynı kaynak) ——

    def _bakiye_etiketleri(self, bakiye: str, valor: str, renk: str) -> None:
        try:
            self.bakiye_lbl.configure(text=bakiye, fg=renk)
            self.valor_lbl.configure(text=valor, fg=KIRMIZI if renk == KIRMIZI else KOYU_GRI)
        except (tk.TclError, AttributeError):
            pass

    def _bakiye_valor_yenile(self) -> None:
        """Seçili müşterinin bakiye + valörünü arka planda yükler; geç gelen eski sonuç yazılmaz."""
        import queue
        import threading

        self._bakiye_seq = getattr(self, "_bakiye_seq", 0) + 1
        seq = self._bakiye_seq
        cari_id = int((self.secili_cari or {}).get("id") or 0)
        if cari_id <= 0:
            self._bakiye_etiketleri("", "", KOYU_GRI)
            return
        self._bakiye_etiketleri("Bakiye yükleniyor…", "", "#6B7280")
        kutu: queue.Queue = queue.Queue(maxsize=1)

        def isci() -> None:
            try:
                kutu.put(("ok", CariService.kart_ozet_metrikleri(cari_id)))
            except Exception as exc:  # noqa: BLE001
                kutu.put(("hata", str(exc)))

        threading.Thread(target=isci, daemon=True).start()
        try:
            self.after(60, lambda: self._bakiye_valor_bekle(seq, cari_id, kutu))
        except tk.TclError:
            pass

    def _bakiye_valor_bekle(self, seq: int, cari_id: int, kutu) -> None:
        import queue

        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if seq != self._bakiye_seq:
            return
        try:
            durum, veri = kutu.get_nowait()
        except queue.Empty:
            try:
                self.after(80, lambda: self._bakiye_valor_bekle(seq, cari_id, kutu))
            except tk.TclError:
                pass
            return
        if int((self.secili_cari or {}).get("id") or 0) != cari_id:
            return
        if durum != "ok" or veri is None:
            neden = veri if durum != "ok" else "cari kaydı bulunamadı"
            self._bakiye_etiketleri("Bakiye/valör alınamadı", f"({str(neden)[:80]})", KIRMIZI)
            return
        from cari_borc_alacak_ozet import kisa_bakiye_valor_metni

        bakiye_metni, valor_metni, renk = kisa_bakiye_valor_metni(veri)
        self._bakiye_etiketleri(bakiye_metni, valor_metni, renk)
        if self.secili_cari is not None and veri.get("bakiye") is not None:
            self.secili_cari["bakiye"] = veri.get("bakiye")

    # —— Sepet hücre hedefleme (sağ tık / F10 / ←→) ——

    def _sepet_hucre(self, event) -> tuple[int | None, str | None]:
        try:
            satir = self.sepet.identify_row(event.y)
            kolon = self.sepet.identify_column(event.x)
        except tk.TclError:
            return None, None
        idx = int(satir) if str(satir).strip().isdigit() else None
        try:
            sutun = SEPET_SUTUNLARI[int(str(kolon).lstrip("#")) - 1]
        except (ValueError, IndexError):
            sutun = None
        return idx, sutun

    def _sepet_odak_ayarla(self, sutun: str | None) -> None:
        self._sepet_odak_sutun = sutun
        for c, baslik in self._sepet_basliklar.items():
            try:
                self.sepet.heading(c, text=f"▸{baslik}" if c == sutun else baslik)
            except tk.TclError:
                pass

    def _sepet_tik(self, event):
        try:
            if self.sepet.identify_region(event.x, event.y) != "cell":
                return None
        except tk.TclError:
            return None
        _idx, sutun = self._sepet_hucre(event)
        if sutun:
            self._sepet_odak_ayarla(sutun)
        return None

    def _sepet_sutun_kaydir(self, yon: int):
        mevcut = self._sepet_odak_sutun if self._sepet_odak_sutun in SEPET_SUTUNLARI else "ad"
        i = SEPET_SUTUNLARI.index(mevcut)
        if self._sepet_odak_sutun is not None:
            i = max(0, min(len(SEPET_SUTUNLARI) - 1, i + yon))
        self._sepet_odak_ayarla(SEPET_SUTUNLARI[i])
        return "break"

    def _sepet_satiri_sec(self, idx: int) -> None:
        iid = str(idx)
        try:
            self.sepet.selection_set(iid)
            self.sepet.focus(iid)
            self.sepet.see(iid)
        except tk.TclError:
            pass

    def _sepet_odaga_don(self, idx: int | None) -> None:
        """Satır diyaloğu kapanınca odak hedef satıra döner."""
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if idx is None or not (0 <= idx < len(self.sepet_model.satirlar)):
            self._barkod_odak()
            return
        self._sepet_satiri_sec(idx)
        try:
            self.sepet.focus_set()
        except tk.TclError:
            pass

    def _gecerli_satir(self, idx: int | None, baslik: str) -> int | None:
        if idx is None:
            idx = self._secili_index()
        if idx is None or not (0 <= idx < len(self.sepet_model.satirlar)):
            messagebox.showinfo(baslik, "Önce bir sepet satırı seçin.", parent=self)
            return None
        return idx

    def _sepet_sag_tik(self, event):
        idx, sutun = self._sepet_hucre(event)
        if idx is None or sutun is None:
            return "break"
        self._sepet_satiri_sec(idx)
        self._sepet_odak_ayarla(sutun)
        if sutun == "fiyat":
            self._fiyat_listesi_ac(idx, event)
        elif sutun == "ad":
            self._stok_hareketleri_ac(idx)
        elif sutun == "birim":
            self._birim_sec(idx, event)
        return "break"

    def _sepet_cift_tik(self, event):
        idx, sutun = self._sepet_hucre(event)
        if sutun == "birim" and idx is not None:
            self._sepet_satiri_sec(idx)
            self._birim_sec(idx, event)
            return "break"
        return self._miktar_dialog(event)

    def _sepet_enter(self, _event=None):
        idx = self._secili_index()
        if idx is None:
            return "break"
        if self._sepet_odak_sutun == "birim":
            self._birim_sec(idx)
        else:
            self._miktar_dialog()
        return "break"

    def _f10_tusu(self, _event=None):
        """Fiyat hücresinde fiyat listesi, ürün hücresinde hareketler; aksi halde ödeme."""
        try:
            odak = self.focus_get()
        except (tk.TclError, KeyError):
            odak = None
        if odak is self.sepet:
            idx = self._secili_index()
            if idx is not None and 0 <= idx < len(self.sepet_model.satirlar):
                if self._sepet_odak_sutun == "fiyat":
                    self._fiyat_listesi_ac(idx)
                    return "break"
                if self._sepet_odak_sutun == "ad":
                    self._stok_hareketleri_ac(idx)
                    return "break"
        return self._odeme_al()

    # —— Satır birimi ——

    def _birim_sec(self, idx: int | None = None, event=None):
        idx = self._gecerli_satir(idx, "Birim")
        if idx is None:
            return "break"
        satir = self.sepet_model.satirlar[idx]
        from database.hizli_satis_satir_service import birim_degisimi_hesapla, satis_birim_secenekleri
        from database.stok_service import birim_anahtari

        try:
            secenekler = satis_birim_secenekleri(satir.stok_kodu)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Birim", f"Birimler alınamadı:\n{exc}", parent=self)
            return "break"
        if not secenekler:
            messagebox.showwarning("Birim", "Stok kartı bulunamadı; birim listelenemedi.", parent=self)
            return "break"
        ana = next((s["birim"] for s in secenekler if s["ana"]), satir.birim)

        dialog = tk.Toplevel(self)
        dialog.title(f"Birim — {satir.stok_kodu}")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text=f"{satir.stok_kodu} — {satir.stok_adi}").pack(
            padx=10, pady=(10, 4), anchor="w"
        )
        liste = tk.Listbox(
            dialog,
            height=min(8, max(3, len(secenekler))),
            exportselection=False,
            font=("Segoe UI", 10),
        )
        liste.pack(fill="both", expand=True, padx=10)
        for i, s in enumerate(secenekler):
            if not s["kullanilabilir"]:
                metin = f"{s['birim']}  — {s['sebep']}"
            elif s["ana"]:
                metin = f"{s['birim']}  (temel birim)"
            else:
                metin = f"{s['birim']}  (1 {s['birim']} = {_miktar_goster(s['carpan'])} {ana})"
            liste.insert("end", metin)
            if not s["kullanilabilir"]:
                liste.itemconfigure(i, foreground="#9CA3AF")
            if birim_anahtari(s["birim"]) == birim_anahtari(satir.birim):
                liste.selection_set(i)
                liste.activate(i)
                liste.see(i)
        ttk.Label(
            dialog,
            text="Yalnız stok kartındaki satış birimleri · Enter: seç · Esc: vazgeç",
        ).pack(padx=10, pady=(4, 0), anchor="w")

        def kapat(_e=None):
            dialog.destroy()
            self._sepet_odaga_don(idx)
            return "break"

        def uygula(_e=None):
            secim = liste.curselection()
            if not secim:
                return "break"
            s = secenekler[secim[0]]
            if not s["kullanilabilir"]:
                messagebox.showwarning("Birim", f"«{s['birim']}» seçilemez: {s['sebep']}", parent=dialog)
                return "break"
            if birim_anahtari(s["birim"]) == birim_anahtari(satir.birim):
                return kapat()
            try:
                sonuc = birim_degisimi_hesapla(
                    stok_kodu=satir.stok_kodu,
                    eski_birim=satir.birim,
                    yeni_birim=s["birim"],
                    miktar=satir.miktar,
                    referans_fiyat=satir.referans_fiyat,
                    fiyat_adi=satir.fiyat_adi or self._aktif_fiyat_listesi(),
                )
                eski = f"{_miktar_goster(satir.miktar)} {satir.birim} × {satir.referans_fiyat}"
                self.sepet_model.birim_uygula(
                    idx,
                    birim=sonuc["birim"],
                    miktar=sonuc["miktar"],
                    birim_fiyat=sonuc["birim_fiyat"],
                    carpan=sonuc["carpan"],
                )
            except ValueError as hata:
                messagebox.showwarning("Birim", str(hata), parent=dialog)
                return "break"
            self.fiyat_gunlugu.ekle(
                stok_kodu=satir.stok_kodu,
                alan="birim",
                eski=eski,
                yeni=f"{_miktar_goster(sonuc['miktar'])} {sonuc['birim']} × {sonuc['birim_fiyat']}",
                kullanici=getattr(oturum, "kullanici_adi", None),
                not_="satır birimi",
            )
            dialog.destroy()
            kaldirildi = self.sepet_model.son_degisiklik_duzeltme_kaldirdi
            self._sepet_yenile(secili=idx)
            self.durum_lbl.configure(
                text=(
                    f"{satir.stok_kodu}: birim {sonuc['birim']} · {_miktar_goster(sonuc['miktar'])} "
                    f"{sonuc['birim']} = {_miktar_goster(sonuc['temel_miktar'])} {ana} stoktan düşer"
                    + (" · önceki Yeni Toplam düzeltmesi kaldırıldı" if kaldirildi else "")
                )
            )
            self._sepet_odaga_don(idx)
            return "break"

        liste.bind("<Return>", uygula)
        liste.bind("<KP_Enter>", uygula)
        liste.bind("<Double-1>", uygula)
        dialog.bind("<Escape>", kapat)
        dialog.protocol("WM_DELETE_WINDOW", kapat)
        dugmeler = ttk.Frame(dialog)
        dugmeler.pack(pady=8)
        ttk.Button(dugmeler, text="Seç", command=uygula).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="Vazgeç", command=kapat).pack(side="left", padx=4)
        _dialog_hucre_altina(
            dialog, self.sepet, item=str(idx), column="birim", event=event, width=380,
            height=150 + 20 * min(8, max(3, len(secenekler))),
        )
        liste.focus_set()
        return "break"

    # —— Fiyat listesi (fiyat hücresi) ——

    def _fiyat_kdv_cozumle(self, secenek: dict, satir, parent) -> tuple[Decimal | None, str]:
        """Satıra yazılacak KDV hariç fiyat; KDV durumu kayıtsızsa kullanıcıya sorulur (varsayım yok)."""
        from database.hizli_satis_satir_service import kdv_dahilden_net

        if not secenek.get("kdv_onay_gerekli"):
            return secenek["uygulanacak"], secenek["kdv"]
        ham = secenek.get("uygulanacak_ham", secenek["uygulanacak"])
        oran = satir.kdv_orani.normalize()
        net = kdv_dahilden_net(ham, satir.kdv_orani)
        cevap = messagebox.askyesnocancel(
            "KDV durumu belirtilmemiş",
            f"«{secenek['fiyat_adi']}» fiyatının KDV dahil mi hariç mi olduğu stok kartında kayıtlı değil.\n\n"
            f"Evet: KDV hariç — satıra {_fiyat_metni(ham)} TL yazılır, %{oran:f} KDV üstüne eklenir.\n"
            f"Hayır: KDV dahil — KDV ayrıştırılır, satıra {_fiyat_metni(net)} TL yazılır.\n"
            "İptal: Fiyat uygulanmaz.",
            parent=parent,
        )
        if cevap is None:
            return None, ""
        if cevap:
            return ham, "KDV hariç (kullanıcı onayı)"
        return net, f"KDV dahil → net %{oran:f} (kullanıcı onayı)"

    def _fiyat_listesi_ac(self, idx: int | None = None, event=None):
        idx = self._gecerli_satir(idx, "Fiyat listesi")
        if idx is None:
            return "break"
        satir = self.sepet_model.satirlar[idx]
        from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService
        from database.hizli_satis_satir_service import fiyat_secenekleri

        izin = fiyat_degistirme_izinli()
        try:
            secenekler = fiyat_secenekleri(
                satir.stok_kodu,
                satir.birim,
                fiyat_degistirme_izni=izin,
                maliyet_izni=FiyatliStokEkstreService.maliyet_gorunsun_mu(),
                aktif_liste=self._aktif_fiyat_listesi(),
                satir_kdv_orani=satir.kdv_orani,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Fiyat listesi", f"Fiyatlar alınamadı:\n{exc}", parent=self)
            return "break"

        dialog = tk.Toplevel(self)
        dialog.title(f"Fiyat Listesi — {satir.stok_kodu}")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text=(
                f"{satir.stok_kodu} — {satir.stok_adi}  ·  Satır birimi: {satir.birim}  ·  "
                f"Satırdaki fiyat: {_fiyat_metni(satir.birim_fiyat)} TL"
            ),
        ).pack(padx=10, pady=(10, 2), anchor="w")
        if not izin:
            tk.Label(
                dialog,
                text="Satır fiyatı değiştirme yetkiniz yok — liste yalnızca görüntülenir.",
                fg=KIRMIZI,
            ).pack(padx=10, anchor="w")

        kolonlar = ("ad", "tutar", "birim", "pb", "kdv", "satira", "not")
        tree = ttk.Treeview(dialog, columns=kolonlar, show="headings", height=8, selectmode="browse")
        for c, baslik, gen, hiza in (
            ("ad", "Fiyat Türü", 150, "w"),
            ("tutar", "Tutar", 90, "e"),
            ("birim", "Birim", 60, "center"),
            ("pb", "Para Birimi", 70, "center"),
            ("kdv", "KDV", 70, "center"),
            ("satira", f"Satıra (TL/{satir.birim})", 120, "e"),
            ("not", "Not", 260, "w"),
        ):
            tree.heading(c, text=baslik)
            tree.column(c, width=gen, anchor=hiza)
        tree.tag_configure("pasif", foreground="#9CA3AF")
        tree.tag_configure("musteri", font=("Segoe UI", 9, "bold"))
        tree.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        ilk_secilecek = None
        for i, s in enumerate(secenekler):
            if s["kullanilabilir"]:
                notu = s["kaynak"] + (" · müşteri fiyat listesi" if s["aktif_liste"] else "")
                if s.get("kdv_onay_gerekli"):
                    notu += " · KDV dahil/hariç seçimde sorulur"
            else:
                notu = s["sebep"]
            etiketler = []
            if not s["kullanilabilir"]:
                etiketler.append("pasif")
            if s["aktif_liste"]:
                etiketler.append("musteri")
            tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    s["fiyat_adi"],
                    _fiyat_metni(s["tutar"]) if s["tutar"] is not None else "—",
                    s["birim"],
                    s["para_birimi"],
                    s["kdv"],
                    _fiyat_metni(s["uygulanacak"]) if s["uygulanacak"] is not None else "—",
                    notu,
                ),
                tags=tuple(etiketler),
            )
            if s["kullanilabilir"] and (ilk_secilecek is None or s["aktif_liste"]):
                ilk_secilecek = i
        alt_bilgi = ttk.Label(
            dialog,
            text=(
                "Bu stok kartında kayıtlı fiyat yok."
                if not secenekler
                else f"Satır fiyatı KDV hariç yazılır, satır KDV'si (%{satir.kdv_orani.normalize():f}) "
                "üstüne eklenir. KDV dahil fiyat ayrıştırılır; KDV durumu belirtilmemiş fiyatta "
                "seçim sırasında sorulur. Seçim yalnız bu satırı değiştirir, stok kartı fiyatı değişmez."
            ),
        )
        alt_bilgi.pack(padx=10, pady=(4, 0), anchor="w")
        if ilk_secilecek is not None:
            tree.selection_set(str(ilk_secilecek))
            tree.focus(str(ilk_secilecek))
            tree.see(str(ilk_secilecek))

        def kapat(_e=None):
            dialog.destroy()
            self._sepet_odaga_don(idx)
            return "break"

        def uygula(_e=None):
            secim = tree.selection()
            if not secim:
                return "break"
            s = secenekler[int(secim[0])]
            if not s["kullanilabilir"]:
                messagebox.showwarning("Fiyat listesi", f"Seçilemez: {s['sebep']}", parent=dialog)
                return "break"
            yeni, kdv_notu = self._fiyat_kdv_cozumle(s, satir, dialog)
            if yeni is None:
                return "break"
            eski = satir.birim_fiyat
            self.sepet_model.fiyat_ayarla(idx, yeni)
            satir.fiyat_adi = s["fiyat_adi"]
            self.fiyat_gunlugu.ekle(
                stok_kodu=satir.stok_kodu,
                alan="birim_fiyat",
                eski=eski,
                yeni=yeni,
                kullanici=getattr(oturum, "kullanici_adi", None),
                not_=f"fiyat listesi → {s['fiyat_adi']} ({s['para_birimi']}, {kdv_notu})",
            )
            dialog.destroy()
            kaldirildi = self.sepet_model.son_degisiklik_duzeltme_kaldirdi
            self._sepet_yenile(secili=idx)
            self.durum_lbl.configure(
                text=(
                    f"{satir.stok_kodu}: {s['fiyat_adi']} uygulandı ({_fiyat_metni(yeni)} TL/"
                    f"{satir.birim}, {kdv_notu})"
                    + (" · önceki Yeni Toplam düzeltmesi kaldırıldı" if kaldirildi else "")
                )
            )
            self._sepet_odaga_don(idx)
            return "break"

        tree.bind("<Return>", uygula)
        tree.bind("<KP_Enter>", uygula)
        tree.bind("<Double-1>", uygula)
        dialog.bind("<Escape>", kapat)
        dialog.protocol("WM_DELETE_WINDOW", kapat)
        dugmeler = ttk.Frame(dialog)
        dugmeler.pack(pady=8)
        ttk.Button(dugmeler, text="Uygula", command=uygula).pack(side="left", padx=4)
        ttk.Button(dugmeler, text="Vazgeç", command=kapat).pack(side="left", padx=4)
        _dialog_hucre_altina(
            dialog, self.sepet, item=str(idx), column="fiyat", event=event, width=860, height=330
        )
        tree.focus_set()
        return "break"

    # —— Stok hareketleri (ürün hücresi) ——

    def _stok_hareketleri_ac(self, idx: int | None = None):
        idx = self._gecerli_satir(idx, "Stok hareketleri")
        if idx is None:
            return "break"
        satir = self.sepet_model.satirlar[idx]
        cari = dict(self.secili_cari or {})
        cari_id = int(cari.get("id") or 0) or None
        cari_adi = cari.get("unvan") or ""
        from database.hizli_satis_satir_service import hareket_donem_secenekleri, stok_hareketleri

        win = tk.Toplevel(self)
        win.title(f"Stok Hareketleri — {satir.stok_kodu}")
        win.transient(self)
        win.grab_set()
        win.geometry("1060x470")
        filtre_lbl = ttk.Label(win, text="", font=("Segoe UI", 10, "bold"))
        filtre_lbl.pack(padx=10, pady=(10, 4), anchor="w")

        try:
            donemler = hareket_donem_secenekleri()
        except Exception:  # noqa: BLE001
            donemler = []
        ozel_etiket = "Özel tarih aralığı"
        donem_satiri = ttk.Frame(win)
        donem_satiri.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(donem_satiri, text="Dönem:").pack(side="left")
        donem_var = tk.StringVar(value=donemler[0]["etiket"] if donemler else ozel_etiket)
        donem_cb = ttk.Combobox(
            donem_satiri,
            textvariable=donem_var,
            values=[d["etiket"] for d in donemler] + [ozel_etiket],
            state="readonly",
            width=42,
        )
        donem_cb.pack(side="left", padx=(4, 10))
        ttk.Label(donem_satiri, text="Başlangıç:").pack(side="left")
        bas_var = tk.StringVar()
        bas_ent = ttk.Entry(donem_satiri, textvariable=bas_var, width=11)
        bas_ent.pack(side="left", padx=(4, 8))
        ttk.Label(donem_satiri, text="Bitiş:").pack(side="left")
        bit_var = tk.StringVar()
        bit_ent = ttk.Entry(donem_satiri, textvariable=bit_var, width=11)
        bit_ent.pack(side="left", padx=(4, 8))

        def _donem_tarihleri_yaz(_e=None):
            secili = next((d for d in donemler if d["etiket"] == donem_var.get()), None)
            if secili is not None:
                bas_var.set(secili["baslangic"].strftime("%d.%m.%Y"))
                bit_var.set(secili["bitis"].strftime("%d.%m.%Y"))
                yukle()

        def _tarih_oku(metin: str, alan: str):
            from datetime import datetime as _dt

            if not (metin or "").strip():
                return None  # servis aktif döneme düşer
            try:
                return _dt.strptime((metin or "").strip(), "%d.%m.%Y").date()
            except ValueError as exc:
                raise ValueError(f"{alan} tarihi GG.AA.YYYY biçiminde olmalı.") from exc

        def _aralik_uygula(_e=None):
            donem_var.set(ozel_etiket)
            yukle()
            return "break"

        donem_cb.bind("<<ComboboxSelected>>", _donem_tarihleri_yaz)
        bas_ent.bind("<Return>", _aralik_uygula)
        bit_ent.bind("<Return>", _aralik_uygula)
        ttk.Button(donem_satiri, text="Aralığı Uygula", command=_aralik_uygula).pack(side="left")
        if donemler:
            bas_var.set(donemler[0]["baslangic"].strftime("%d.%m.%Y"))
            bit_var.set(donemler[0]["bitis"].strftime("%d.%m.%Y"))
        kolonlar = (
            "tarih", "saat", "belge", "tur", "cari", "yon", "miktar", "birim", "fiyat", "tutar", "pb",
        )
        cerceve = ttk.Frame(win)
        cerceve.pack(fill="both", expand=True, padx=10)
        tree = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
        for c, baslik, gen, hiza in (
            ("tarih", "Tarih", 80, "center"),
            ("saat", "Saat", 50, "center"),
            ("belge", "Belge No", 110, "w"),
            ("tur", "Belge Türü", 120, "w"),
            ("cari", "Müşteri / Cari", 220, "w"),
            ("yon", "Giriş/Çıkış", 75, "center"),
            ("miktar", "Miktar", 70, "e"),
            ("birim", "Birim", 60, "center"),
            ("fiyat", "Birim Fiyat", 90, "e"),
            ("tutar", "Tutar", 95, "e"),
            ("pb", "PB", 40, "center"),
        ):
            tree.heading(c, text=baslik)
            tree.column(c, width=gen, anchor=hiza)
        kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=kaydirma.set)
        tree.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        alt_lbl = tk.Label(win, text="", anchor="w", justify="left", fg="#374151")
        alt_lbl.pack(fill="x", padx=10, pady=(4, 0))
        durum = {"tum": False}

        dugmeler = ttk.Frame(win)
        dugmeler.pack(fill="x", padx=10, pady=8)

        def yukle() -> None:
            tree.delete(*tree.get_children())
            tum = durum["tum"]
            btn_tum.configure(state="disabled" if tum else "normal")
            btn_musteri.configure(state="normal" if (tum and cari_id) else "disabled")
            if tum:
                filtre_lbl.configure(text=f"Filtre: Stok = {satir.stok_kodu} — {satir.stok_adi} (tüm cariler)")
            else:
                filtre_lbl.configure(
                    text=f"Filtre: Müşteri = {cari_adi or '—'}  ·  Stok = {satir.stok_kodu} — {satir.stok_adi}"
                )
            if not tum and not cari_id:
                alt_lbl.configure(
                    text=(
                        "Müşteri seçilmedi — müşteriye ait hareketler için önce müşteri seçin (F2). "
                        "Tüm carilerin hareketleri için «Bu stokun tüm hareketleri»ni kullanın."
                    ),
                    fg=KIRMIZI,
                )
                return
            try:
                baslangic = _tarih_oku(bas_var.get(), "Başlangıç")
                bitis = _tarih_oku(bit_var.get(), "Bitiş")
            except ValueError as exc:
                alt_lbl.configure(text=str(exc), fg=KIRMIZI)
                return
            try:
                win.configure(cursor="watch")
                win.update_idletasks()
                sonuc = stok_hareketleri(
                    int(satir.stok_id),
                    cari_id=None if tum else cari_id,
                    baslangic=baslangic,
                    bitis=bitis,
                )
            except Exception as exc:  # noqa: BLE001
                alt_lbl.configure(text=f"Hareketler alınamadı: {exc}", fg=KIRMIZI)
                return
            finally:
                try:
                    win.configure(cursor="")
                except tk.TclError:
                    pass
            yon_metni = {"giris": "Giriş", "cikis": "Çıkış"}
            for r in sonuc["satirlar"]:
                tree.insert(
                    "",
                    "end",
                    values=(
                        r["tarih"].strftime("%d.%m.%Y") if r.get("tarih") else "",
                        r.get("saat") or "",
                        r.get("belge_no") or "",
                        r.get("belge_turu") or "",
                        r.get("cari") or "",
                        yon_metni.get(r.get("yon"), "—"),
                        _miktar_goster(r["miktar"]) if r.get("miktar") is not None else "",
                        r.get("birim") or "",
                        _fiyat_metni(r["birim_fiyat"]) if r.get("birim_fiyat") is not None else (r.get("fiyat_notu") or "—"),
                        _para_alani_metni(r["tutar"]) if r.get("tutar") is not None else "—",
                        r.get("para_birimi") or "",
                    ),
                )
            donem = f"{sonuc['baslangic'].strftime('%d.%m.%Y')}–{sonuc['bitis'].strftime('%d.%m.%Y')}"
            if not sonuc["satirlar"]:
                metin = f"Bu filtrede hareket yok (dönem {donem})."
            else:
                metin = (
                    f"{sonuc['toplam_kayit']} hareket · dönem {donem} · yeniden eskiye · "
                    "fiyat/tutar belge satırından, iskonto sonrası KDV hariç TL · salt okunur"
                )
                if sonuc["kesildi"]:
                    metin += f" · en yeni {len(sonuc['satirlar'])} kayıt gösteriliyor"
            alt_lbl.configure(text=metin, fg="#374151")

        def tumunu_goster():
            durum["tum"] = True
            yukle()

        def musteriye_don():
            durum["tum"] = False
            yukle()

        def kapat(_e=None):
            win.destroy()
            self._sepet_odaga_don(idx)
            return "break"

        btn_tum = ttk.Button(dugmeler, text="Bu stokun tüm hareketleri", command=tumunu_goster)
        btn_tum.pack(side="left")
        btn_musteri = ttk.Button(dugmeler, text="Yalnız seçili müşteri", command=musteriye_don)
        btn_musteri.pack(side="left", padx=6)
        ttk.Button(dugmeler, text="Kapat", command=kapat).pack(side="right")
        win.bind("<Escape>", kapat)
        win.protocol("WM_DELETE_WINDOW", kapat)
        yukle()
        tree.focus_set()
        return "break"

    def _miktar_delta(self, delta: int | float | Decimal, _event=None):
        idx = self._secili_index()
        if idx is None:
            if self.sepet_model:
                idx = len(self.sepet_model) - 1
                self.sepet.selection_set(str(idx))
            else:
                return "break"
        self.sepet_model.miktar_degistir(idx, delta)
        # Silindiyse bir üst satırı seç
        yeni = min(idx, len(self.sepet_model) - 1) if self.sepet_model else None
        self._sepet_yenile(secili=yeni)
        self._barkod_odak()
        return "break"

    def _satir_sil(self, _event=None):
        idx = self._secili_index()
        if idx is None:
            return "break"
        self.sepet_model.sil(idx)
        yeni = min(idx, len(self.sepet_model) - 1) if self.sepet_model else None
        self._sepet_yenile(secili=yeni)
        self._barkod_odak()
        return "break"

    def _miktar_dialog(self, event=None):
        idx = self._secili_index()
        if event is not None:
            try:
                item = self.sepet.identify_row(event.y)
                if item is not None and str(item).strip() != "":
                    idx = int(item)
            except (tk.TclError, TypeError, ValueError):
                pass
        if idx is None or not (0 <= idx < len(self.sepet_model.satirlar)):
            return
        satir = self.sepet_model.satirlar[idx]
        dialog = tk.Toplevel(self)
        dialog.title("Miktar")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("280x120")
        ttk.Label(dialog, text=f"{satir.stok_kodu} — {satir.stok_adi}").pack(padx=12, pady=(12, 4))
        satir_frame = ttk.Frame(dialog)
        satir_frame.pack(padx=12, pady=4)
        ttk.Label(satir_frame, text="Miktar").pack(side="left", padx=(0, 8))
        miktar_var = tk.StringVar(value=_miktar_goster(satir.miktar))
        entry = ttk.Entry(satir_frame, textvariable=miktar_var, width=14)
        entry.pack(side="left")
        entry.focus_set()
        entry.selection_range(0, "end")

        def uygula(_e=None):
            ham = miktar_var.get().strip().replace(",", ".")
            try:
                yeni = Decimal(ham)
            except Exception:
                messagebox.showerror("Miktar", "Geçersiz miktar.", parent=dialog)
                return
            if yeni <= 0:
                self.sepet_model.sil(idx)
                self._sepet_yenile()
            else:
                self.sepet_model.miktar_ayarla(idx, yeni)
                self._sepet_yenile(secili=idx)
            dialog.destroy()
            self._barkod_odak()

        entry.bind("<Return>", uygula)
        ttk.Button(dialog, text="Tamam", command=uygula).pack(pady=8)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        _dialog_hucre_altina(
            dialog,
            self.sepet,
            item=str(idx),
            column="miktar",
            event=event,
            width=280,
            height=120,
        )

    def _fiyat_dialog(self, _event=None):
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Fiyat", "Önce bir sepet satırı seçin.", parent=self)
            return
        if not fiyat_degistirme_izinli():
            messagebox.showwarning(
                "Yetki",
                "Satır fiyatı değiştirme yetkiniz yok.",
                parent=self,
            )
            return
        satir = self.sepet_model.satirlar[idx]
        dialog = tk.Toplevel(self)
        dialog.title("Birim Fiyat")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("300x130")
        ttk.Label(dialog, text=f"{satir.stok_kodu} — {satir.stok_adi}").pack(
            padx=12, pady=(12, 4)
        )
        satir_frame = ttk.Frame(dialog)
        satir_frame.pack(padx=12, pady=4)
        ttk.Label(satir_frame, text="Fiyat").pack(side="left", padx=(0, 8))
        fiyat_var = tk.StringVar(
            value=f"{float(satir.birim_fiyat):,.4f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
            .rstrip("0")
            .rstrip(",")
        )
        entry = ttk.Entry(satir_frame, textvariable=fiyat_var, width=14)
        entry.pack(side="left")
        entry.focus_set()
        entry.selection_range(0, "end")

        def uygula(_e=None):
            ham = fiyat_var.get().strip().replace(",", ".")
            try:
                yeni = Decimal(ham)
            except Exception:
                messagebox.showerror("Fiyat", "Geçersiz fiyat.", parent=dialog)
                return
            if yeni < 0:
                messagebox.showerror("Fiyat", "Fiyat negatif olamaz.", parent=dialog)
                return
            eski = satir.birim_fiyat
            self.sepet_model.fiyat_ayarla(idx, yeni)
            self.fiyat_gunlugu.ekle(
                stok_kodu=satir.stok_kodu,
                alan="birim_fiyat",
                eski=eski,
                yeni=yeni,
                kullanici=getattr(oturum, "kullanici_adi", None),
                not_="manuel",
            )
            self._sepet_yenile(secili=idx)
            dialog.destroy()
            self._barkod_odak()

        entry.bind("<Return>", uygula)
        ttk.Button(dialog, text="Tamam", command=uygula).pack(pady=8)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def _iskonto_dialog(self, _event=None):
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("İskonto", "Önce bir sepet satırı seçin.", parent=self)
            return
        satir = self.sepet_model.satirlar[idx]
        dialog = tk.Toplevel(self)
        dialog.title("İskonto %")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("280x130")
        ttk.Label(dialog, text=f"{satir.stok_kodu} — {satir.stok_adi}").pack(
            padx=12, pady=(12, 4)
        )
        satir_frame = ttk.Frame(dialog)
        satir_frame.pack(padx=12, pady=4)
        ttk.Label(satir_frame, text="İsk %").pack(side="left", padx=(0, 8))
        isk_var = tk.StringVar(value=_miktar_goster(satir.iskonto_orani))
        entry = ttk.Entry(satir_frame, textvariable=isk_var, width=14)
        entry.pack(side="left")
        entry.focus_set()
        entry.selection_range(0, "end")

        def uygula(_e=None):
            ham = isk_var.get().strip().replace(",", ".")
            try:
                yeni = Decimal(ham)
            except Exception:
                messagebox.showerror("İskonto", "Geçersiz oran.", parent=dialog)
                return
            kapı = iskonto_degistirme_sonucu(yeni)
            if not kapı["izinli"]:
                messagebox.showwarning("Yetki", kapı["mesaj"], parent=dialog)
                return
            eski = satir.iskonto_orani
            try:
                self.sepet_model.iskonto_ayarla(idx, yeni)
            except ValueError as exc:
                messagebox.showerror("İskonto", str(exc), parent=dialog)
                return
            self.fiyat_gunlugu.ekle(
                stok_kodu=satir.stok_kodu,
                alan="iskonto_orani",
                eski=eski,
                yeni=yeni,
                kullanici=getattr(oturum, "kullanici_adi", None),
                not_="manuel" + (" · yüksek" if kapı["yuksek"] else ""),
            )
            self._sepet_yenile(secili=idx)
            dialog.destroy()
            self._barkod_odak()

        entry.bind("<Return>", uygula)
        ttk.Button(dialog, text="Tamam", command=uygula).pack(pady=8)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def _kdv_dialog(self, _event=None):
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("KDV", "Önce bir sepet satırı seçin.", parent=self)
            return
        satir = self.sepet_model.satirlar[idx]
        dialog = tk.Toplevel(self)
        dialog.title("KDV %")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("300x140")
        ttk.Label(dialog, text=f"{satir.stok_kodu} — {satir.stok_adi}").pack(
            padx=12, pady=(12, 4)
        )
        satir_frame = ttk.Frame(dialog)
        satir_frame.pack(padx=12, pady=4)
        ttk.Label(satir_frame, text="KDV %").pack(side="left", padx=(0, 8))
        mevcut = f"{float(satir.kdv_orani):g}"
        kdv_var = tk.StringVar(value=mevcut if mevcut in KDV_ORANLARI else mevcut)
        combo = ttk.Combobox(
            satir_frame,
            textvariable=kdv_var,
            values=list(KDV_ORANLARI),
            width=10,
            state="readonly",
        )
        combo.pack(side="left")
        combo.focus_set()

        def uygula(_e=None):
            ham = kdv_var.get().strip().replace(",", ".")
            try:
                yeni = Decimal(ham)
            except Exception:
                messagebox.showerror("KDV", "Geçersiz oran.", parent=dialog)
                return
            try:
                self.sepet_model.kdv_ayarla(idx, yeni)
            except ValueError as exc:
                messagebox.showerror("KDV", str(exc), parent=dialog)
                return
            self._sepet_yenile(secili=idx)
            dialog.destroy()
            self._barkod_odak()

        combo.bind("<Return>", uygula)
        ttk.Button(dialog, text="Tamam", command=uygula).pack(pady=8)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    # —— Beklet / geri çağır (Aşama 6) ——

    def _beklet(self, _event=None):
        if self._kayit_devam:
            return "break"
        if not self.sepet_model.satirlar:
            messagebox.showwarning("Sepet boş", "Bekletmek için sepete ürün ekleyin.", parent=self)
            return "break"

        etiket = simpledialog.askstring(
            "Beklet",
            "Etiket / not (isteğe bağlı):",
            parent=self,
        )
        if etiket is None:
            # İptal
            return "break"
        etiket = (etiket or "").strip() or None

        cari = self.secili_cari or {}
        try:
            sonuc = HizliSatisService.save_hold(
                self.sepet_model,
                cari_id=int(cari.get("id") or 0) or None,
                cari_kodu=cari.get("cari_kodu"),
                cari_unvan=cari.get("unvan"),
                etiket=etiket,
                odeme_niyeti=self.odeme_niyeti,
            )
        except AccessError as hata:
            messagebox.showerror("Yetki / dönem", str(hata), parent=self)
            return "break"
        except Exception as hata:
            messagebox.showerror("Beklet", str(hata), parent=self)
            return "break"

        self.sepet_model.temizle()
        self.fiyat_gunlugu.temizle()
        self._sepet_yenile()
        self.durum_lbl.configure(
            text=(
                f"Sepet bekletildi #{sonuc.get('id')} — "
                f"{sonuc.get('satir_sayisi')} satır / {_para(sonuc.get('genel_toplam'))}"
            )
        )
        self._barkod_odak()
        return "break"

    def _geri_cagir_ac(self, _event=None):
        if self._kayit_devam:
            return "break"

        def _onay() -> bool:
            if not self.sepet_model.satirlar:
                return True
            return bool(
                messagebox.askyesno(
                    "Sepet dolu",
                    "Mevcut sepet silinip bekleyen sepet yüklenecek. Devam?",
                    parent=self,
                )
            )

        dlg = HizliSatisBekleyenDialog(
            self,
            on_cagir=self._bekleyeni_uygula,
            on_onay_oncesi=_onay,
        )
        self.wait_window(dlg)
        return "break"

    def _bekleyeni_uygula(self, veri: dict) -> None:
        """Geri çağırılan bekleyeni sepete yükler (fiyatlar korunur)."""
        satirlar = list(veri.get("satirlar") or [])
        if not satirlar:
            raise ValueError("Bekleyen sepet satırı boş.")

        yeni = HizliSatisSepet()
        for s in satirlar:
            yeni.ekle(
                stok_id=int(s["stok_id"]),
                stok_kodu=s.get("stok_kodu") or "",
                stok_adi=s.get("stok_adi") or "",
                birim=s.get("birim") or "Adet",
                miktar=s.get("miktar") or 1,
                birim_fiyat=s.get("birim_fiyat") or 0,
                iskonto_orani=s.get("iskonto_orani") or 0,
                kdv_orani=s.get("kdv_orani") if s.get("kdv_orani") is not None else VARSAYILAN_KDV,
                carpan=s.get("carpan") or 1,
                barkod=s.get("barkod"),
                birlestir=False,
                referans_birim_fiyat=s.get("referans_birim_fiyat"),
                geri_yukleme=True,
            )
        if yeni.duzeltme_aktif:
            yeni.hedef_toplam = yeni.toplamlar()["genel_toplam"]

        self.sepet_model = yeni
        self.fiyat_gunlugu.temizle()
        self.odeme_niyeti = veri.get("odeme_niyeti") or None

        cari_id = veri.get("cari_id")
        if cari_id:
            try:
                cari = CariService.getir(int(cari_id))
                if cari is not None:
                    ozet = cari_ozet_dict(cari)
                    # Beklenen fiyatları koru — müşteri değişiminde fiyat yenileme yok
                    self.secili_cari = ozet
                    self._musteri_alani_goster()
                    self._bakiye_valor_yenile()
                    self._fiyat_grup_etiket_guncelle()
                else:
                    self._varsayilan_musteri_yukle()
            except Exception:
                self._varsayilan_musteri_yukle()
        else:
            self._varsayilan_musteri_yukle()

        self._sepet_yenile()
        if getattr(self, "urun_panel", None) is not None:
            try:
                self.urun_panel.kartlari_yenile()
            except Exception:
                pass
        self.durum_lbl.configure(
            text=(
                f"Bekleyen #{veri.get('id')} geri çağrıldı — "
                f"{len(yeni)} satır / {_para(yeni.toplamlar()['genel_toplam'])}"
            )
        )
        self._barkod_odak()

    # —— Tahsilat / satış tamamlama (Aşama 5) ——

    def _odeme_al(self, _event=None):
        if self._kayit_devam:
            return "break"
        if not self.sepet_model.satirlar:
            messagebox.showwarning("Sepet boş", "Önce sepete ürün ekleyin.", parent=self)
            return "break"
        cari = self.secili_cari or {}
        cari_id = int(cari.get("id") or 0)
        if cari_id <= 0:
            messagebox.showwarning(
                "Müşteri",
                "Satış için müşteri seçin (F2).",
                parent=self,
            )
            return "break"

        toplam = self.sepet_model.toplamlar()["genel_toplam"]
        if toplam <= 0:
            messagebox.showwarning("Tutar", "Satış tutarı sıfır olamaz.", parent=self)
            return "break"

        # UI stok kontrolü
        hatalar = HizliSatisService.stok_yeterlilik_kontrol(
            self.sepet_model.satirlar, depo=VARSAYILAN_DEPO
        )
        if hatalar:
            messagebox.showerror(
                "Stok yetersiz",
                "Eksi stoka izin yok.\n\n" + "\n".join(hatalar),
                parent=self,
            )
            return "break"

        self._ek_fon_bedeli_yenile(toplam)
        eksik = (self._ek_fon_bedeli or {}).get("eksik_ayar")
        if eksik:
            messagebox.showerror(
                "Ek fon bedeli",
                "Faturaya ek fon bedeli hesaplanamıyor; Finans → Fon Yönetimi → Fon Tanımları'nda "
                f"ayarı tamamlayın: {eksik}.",
                parent=self,
            )
            return "break"
        token = HizliSatisService.yeni_idempotency_token()
        dlg = HizliSatisTahsilatDialog(
            self,
            genel_toplam=self._odenecek_toplam(),
            musteri_unvan=cari.get("unvan") or "",
            musteri_bakiye=cari.get("bakiye"),
            risk_limiti=cari.get("acik_hesap_risk_limiti"),
        )
        self.wait_window(dlg)
        if dlg.result is None:
            return "break"

        self._satis_kaydet(dlg.result, token)
        return "break"

    def _satis_kaydet(self, tahsilatlar: list, token: str) -> None:
        if self._kayit_devam:
            return
        self._kayit_devam = True
        try:
            for btn in (getattr(self, "btn_odeme", None), getattr(self, "btn_tamamla", None)):
                if btn is not None:
                    btn.configure(state="disabled")
        except tk.TclError:
            pass

        cari = self.secili_cari or {}
        try:
            sonuc = HizliSatisService.satisi_tamamla(
                sepet=self.sepet_model,
                cari_id=int(cari["id"]),
                tahsilatlar=tahsilatlar,
                idempotency_token=token,
                depo=VARSAYILAN_DEPO,
                aciklama="Hızlı Satış",
                musteri_bakiye=cari.get("bakiye"),
                risk_limiti=cari.get("acik_hesap_risk_limiti"),
            )
        except AccessError as hata:
            messagebox.showerror("Yetki / dönem", str(hata), parent=self)
            self._kayit_devam = False
            self._odeme_butonlari_ac()
            return
        except ValueError as hata:
            birim_hatasi_goster(self, hata) or messagebox.showerror("Satış kaydı", str(hata), parent=self)
            self._kayit_devam = False
            self._odeme_butonlari_ac()
            return
        except Exception as hata:
            messagebox.showerror("Satış kaydı", str(hata), parent=self)
            self._kayit_devam = False
            self._odeme_butonlari_ac()
            return

        # Başarı: sepet temizle + log + çıktı diyaloğu (yazıcı satışı bozmaz)
        self._son_fatura_id = int(sonuc.get("fatura_id") or 0) or None
        try:
            islem_yaz(
                "SATIS",
                f"Satış tamamlandı: {sonuc.get('fatura_no')}",
                detay={
                    "fatura_id": sonuc.get("fatura_id"),
                    "fatura_no": sonuc.get("fatura_no"),
                    "genel_toplam": str(sonuc.get("genel_toplam")),
                    "tahsilat_tutari": str(sonuc.get("tahsilat_tutari")),
                    "kalan": str(sonuc.get("kalan")),
                    "fiyat_degisiklik_sayisi": len(self.fiyat_gunlugu),
                },
            )
        except Exception:
            pass
        self.sepet_model.temizle()
        self.fiyat_gunlugu.temizle()
        self.odeme_niyeti = None
        self._sepet_yenile()
        self._bakiye_valor_yenile()
        if getattr(self, "urun_panel", None) is not None:
            try:
                self.urun_panel.kartlari_yenile()
            except Exception:
                pass

        basari_dialog_goster(self, sonuc)
        self._kayit_devam = False
        self._odeme_butonlari_ac()
        self._barkod_odak()

    def _odeme_butonlari_ac(self) -> None:
        for btn in (getattr(self, "btn_odeme", None), getattr(self, "btn_tamamla", None)):
            if btn is None:
                continue
            try:
                btn.configure(state="normal")
            except tk.TclError:
                pass

    def _iptal_aksiyon(self, _event=None):
        """Sepet doluysa bellek temizle (DB yok); boşsa tamamlanmış satış iptal/iade."""
        if self._kayit_devam:
            return "break"

        if self.sepet_model.satirlar:
            if not messagebox.askyesno(
                "Sepeti temizle",
                "Sepetteki ürünler silinsin mi?\n(Veritabanına kayıt yazılmaz.)",
                parent=self,
            ):
                return "break"
            self.sepet_model.temizle()
            self.fiyat_gunlugu.temizle()
            self._sepet_yenile()
            self.durum_lbl.configure(text="Sepet temizlendi")
            self._barkod_odak()
            return "break"

        if not iptal_iade_izinli():
            messagebox.showerror(
                "Yetki",
                f"Satış iptal / iade için «{IZIN_IPTAL}» yetkisi gerekir.",
                parent=self,
            )
            return "break"

        def _yenile_stok(_sonuc: dict) -> None:
            if getattr(self, "urun_panel", None) is not None:
                try:
                    self.urun_panel.kartlari_yenile()
                except Exception:
                    pass
            self._bakiye_valor_yenile()
            self.durum_lbl.configure(
                text=(
                    f"İptal/iade: {_sonuc.get('fatura_no') or _sonuc.get('iade_no') or ''}"
                )
            )
            try:
                tur = "IPTAL" if (_sonuc.get("mod") or "") == "tam_iptal" else "IADE"
                islem_yaz(
                    tur,
                    f"{tur}: {_sonuc.get('fatura_no') or ''} {_sonuc.get('iade_no') or ''}",
                    detay={
                        "fatura_id": _sonuc.get("fatura_id"),
                        "fatura_no": _sonuc.get("fatura_no"),
                        "iade_no": _sonuc.get("iade_no"),
                        "neden": _sonuc.get("neden"),
                        "mod": _sonuc.get("mod"),
                    },
                )
            except Exception:
                pass

        dlg = HizliSatisIptalIadeDialog(
            self,
            on_basari=_yenile_stok,
            on_secili_fatura_id=self._son_fatura_id,
        )
        self.wait_window(dlg)
        self._barkod_odak()
        return "break"

    def _gun_sonu_ac(self) -> None:
        dlg = HizliSatisGunSonuDialog(self)
        self.wait_window(dlg)
        self._barkod_odak()

    def _son_fatura_gerekli(self) -> int | None:
        fid = self._son_fatura_id
        if not fid:
            messagebox.showinfo(
                "Yeniden yazdır",
                "Bu oturumda henüz tamamlanmış satış yok.\n"
                "(İptal listesinden seçim Aşama 9’da genişletilebilir.)",
                parent=self,
            )
            return None
        return int(fid)

    def _son_fisi_yazdir(self) -> None:
        fid = self._son_fatura_gerekli()
        if fid:
            fis_yazdir(self, fid)

    def _son_a4_yazdir(self) -> None:
        fid = self._son_fatura_gerekli()
        if fid:
            a4_yazdir(self, fid)

    def _son_pdf_kaydet(self) -> None:
        fid = self._son_fatura_gerekli()
        if fid:
            pdf_kaydet(self, fid)

    def _kapat(self) -> None:
        try:
            parent = self.master
            if getattr(parent, "_hizli_satis_pencere", None) is self:
                parent._hizli_satis_pencere = None
        except Exception:
            pass
        self.destroy()
