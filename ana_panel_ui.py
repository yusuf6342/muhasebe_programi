"""Ana panel kabuğu (sol menü / üst bar / durum) ve giriş dashboard UI."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any, Callable

from ana_panel_tema import (
    ACIK_BG,
    BASARI,
    BEYAZ,
    CIZGI,
    FIRMA_ADI,
    FIRMA_KISA,
    FONT_ALT,
    FONT_KUCUK,
    FONT_MENU,
    FONT_MENU_BOLD,
    FONT_SIDEBAR,
    FONT_UI,
    FONT_UI_BOLD,
    KOYU_LACIVERT,
    LACIVERT,
    LACIVERT_HOVER,
    METIN,
    METIN_ACIK,
    PASIF,
    SARI,
    SARI_HOVER,
    SOL_MENU_GENISLIK,
    UYARI,
    para_tr,
    sayi_tr,
)

# (etiket, anahtar, simge, vurgulu)
MENU_OGELERI: tuple[tuple[str, str, str, bool], ...] = (
    ("Giriş Ekranı", "giris", ">", False),
    ("Hızlı Satış", "hizli_satis", "*", True),
    ("Satışlar", "satislar", "+", False),
    ("Satın Alma", "satin_alma", "v", False),
    ("Stoklar", "stoklar", "#", False),
    ("Finans", "finans", "$", False),
    ("Gelir ve Giderler", "gelir_gider", "+/-", False),
    ("Genel Muhasebe", "genel_muhasebe", "=", False),
    ("Çek ve Senet", "cek_senet", "~", False),
    ("Özet Tablolar", "ozet_tablolar", "[]", False),
    ("Raporlar", "raporlar", "R", False),
    ("Kullanıcı ve Firma Yönetimi", "sistem", "@", False),
    ("Servis ve Sistem Kontrolü", "servis", "!", False),
    ("Ayarlar", "ayarlar", "...", False),
)

MODUL_KARTLARI: tuple[tuple[str, str, str, str], ...] = (
    ("Hızlı Satış", "hizli_satis", "*", "Barkodlu anlık satış ve tahsilat ekranı."),
    ("Satışlar", "satislar", "+", "Faturalar, irsaliyeler, siparişler ve müşteri işlemleri."),
    ("Satın Alma", "satin_alma", "v", "Tedarikçi faturaları, sipariş ve irsaliye yönetimi."),
    ("Stoklar", "stoklar", "#", "Stok kartları, depo, barkod ve fiyat işlemleri."),
    ("Finans", "finans", "$", "Kasa, banka ve nakit akışı işlemleri."),
    ("Gelir ve Giderler", "gelir_gider", "+/-", "Gelir / gider kayıtları ve takibi."),
    ("Genel Muhasebe", "genel_muhasebe", "=", "Hesap planı, fişler ve muhasebe entegrasyonu."),
    ("Raporlar", "raporlar", "R", "Satış, stok, finans ve özet raporlara hızlı erişim."),
)

HIZLI_ISLEMLER: tuple[tuple[str, str], ...] = (
    ("Yeni Satış", "yeni_satis"),
    ("Yeni Tahsilat", "yeni_tahsilat"),
    ("Yeni Ödeme", "yeni_odeme"),
    ("Yeni Alış Siparişi", "yeni_alis_siparis"),
    ("Müşteri Kartı Aç", "musteri_karti"),
    ("Stok Sorgula", "stok_sorgula"),
    ("Fiyat Gör", "fiyat_gor"),
    ("Barkodlu Satış", "barkodlu_satis"),
    ("Gün Sonu Özeti", "gun_sonu"),
)


class SolMenuDugme(tk.Frame):
    """Lacivert sol menü satırı — ttk style= uyumluluğu için configure(style=...)."""

    def __init__(
        self,
        parent,
        *,
        etiket: str,
        anahtar: str,
        simge: str,
        vurgulu: bool,
        komut: Callable[[], None],
        **kwargs,
    ):
        super().__init__(parent, bg=LACIVERT, highlightthickness=0, **kwargs)
        self.anahtar = anahtar
        self._varsayilan_vurgulu = vurgulu
        self.vurgulu = vurgulu
        self._komut = komut
        self._aktif = False
        self._hover = False
        self._pasif_gizli = False

        self.accent = tk.Frame(self, width=4, bg=LACIVERT, highlightthickness=0)
        self.accent.pack(side="left", fill="y")
        self.inner = tk.Frame(self, bg=LACIVERT, highlightthickness=0)
        self.inner.pack(side="left", fill="both", expand=True)

        self.lbl_simge = tk.Label(
            self.inner,
            text=simge,
            font=FONT_MENU,
            fg=SARI if vurgulu else METIN_ACIK,
            bg=LACIVERT,
            width=2,
            anchor="center",
        )
        self.lbl_simge.pack(side="left", padx=(8, 4), pady=8)
        self.lbl_text = tk.Label(
            self.inner,
            text=etiket,
            font=FONT_MENU_BOLD if vurgulu else FONT_MENU,
            fg=KOYU_LACIVERT if vurgulu else METIN_ACIK,
            bg=SARI if vurgulu else LACIVERT,
            anchor="w",
        )
        self.lbl_text.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)

        for w in (self, self.inner, self.lbl_simge, self.lbl_text, self.accent):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)
            w.bind("<Return>", self._on_click)
            w.bind("<space>", self._on_click)

        self.configure(takefocus=1)
        self.bind("<FocusIn>", lambda _e: self._set_hover(True))
        self.bind("<FocusOut>", lambda _e: self._set_hover(False))
        self._yenile_renk()

    def configure(self, cnf=None, **kw):  # noqa: A003 — tk API
        if cnf is None:
            cnf = {}
        elif isinstance(cnf, dict):
            kw = {**cnf, **kw}
            cnf = {}
        stil = kw.pop("style", None)
        if stil is not None:
            self._stil_uygula(stil)
        if kw or cnf:
            return super().configure(cnf, **kw)
        return None

    config = configure

    def _stil_uygula(self, stil: str) -> None:
        if stil == "SeciliMenu.TButton":
            self._aktif = True
        else:
            self._aktif = False
            self.vurgulu = bool(
                self._varsayilan_vurgulu or stil == "HizliSatisMenu.TButton"
            )
        self._yenile_renk()

    def set_aktif(self, aktif: bool) -> None:
        self._aktif = aktif
        self._yenile_renk()

    def _on_enter(self, _e=None):
        self._set_hover(True)

    def _on_leave(self, _e=None):
        # Alt widget'a geçişte Leave tetiklenir — pointer hâlâ bizde mi?
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            if widget is not None and (
                widget == self or str(widget).startswith(str(self))
            ):
                return
        except tk.TclError:
            pass
        self._set_hover(False)

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._yenile_renk()

    def _on_click(self, _e=None):
        if self._komut:
            self._komut()
        return "break"

    def _yenile_renk(self) -> None:
        if self._aktif:
            bg, fg, acc = SARI, KOYU_LACIVERT, SARI
            simge_fg = KOYU_LACIVERT
        elif self.vurgulu and not self._aktif:
            # Pasif ama önemli: sarı şerit + açık metin, tam sarı zemin değil
            if self._hover:
                bg, fg, acc = LACIVERT_HOVER, SARI, SARI
                simge_fg = SARI
            else:
                bg, fg, acc = LACIVERT, SARI, SARI
                simge_fg = SARI
        elif self._hover:
            bg, fg, acc = LACIVERT_HOVER, SARI, LACIVERT_HOVER
            simge_fg = SARI
        else:
            bg, fg, acc = LACIVERT, METIN_ACIK, LACIVERT
            simge_fg = METIN_ACIK

        for w in (self, self.inner):
            w.configure(bg=bg)
        self.accent.configure(bg=acc if (self._aktif or self.vurgulu) else bg)
        self.lbl_simge.configure(bg=bg, fg=simge_fg)
        self.lbl_text.configure(bg=bg, fg=fg)


def logo_yukle(parent, *, max_w: int = 120, max_h: int = 40):
    """Mevcut branding logosunu yükler; yoksa sarı RAY yer tutucu döner."""
    try:
        from branding import APP_ICON_PNG, get_brand_image

        img = get_brand_image(APP_ICON_PNG, max_width=max_w, max_height=max_h)
        if img is not None:
            lbl = tk.Label(parent, image=img, bg=KOYU_LACIVERT, borderwidth=0)
            lbl.image = img  # type: ignore[attr-defined]
            return lbl
    except Exception:
        pass
    ph = tk.Frame(parent, bg=SARI, width=56, height=28, highlightthickness=0)
    ph.pack_propagate(False)
    tk.Label(
        ph, text=FIRMA_KISA, bg=SARI, fg=KOYU_LACIVERT, font=FONT_UI_BOLD
    ).pack(expand=True)
    return ph


def ozet_verileri_topla() -> dict[str, Any]:
    """Güvenli özet kart verileri — ham SQL yok, servis + try/except."""
    bugun = date.today()
    sonuc: dict[str, Any] = {
        "bugunku_satis": None,
        "bugunku_tahsilat": None,
        "cari_alacak": None,
        "kritik_stok": None,
        "kritik_aciklama": None,
        "baglanti_ok": True,
        "hata": None,
    }
    try:
        from database.satis_faturasi_service import SatisFaturasiService

        faturalar = SatisFaturasiService.listele_ozet(tarih_bas=bugun, tarih_bit=bugun)
        toplam = Decimal("0")
        for f in faturalar or []:
            toplam += Decimal(str(f.get("genel_toplam") or f.get("tl_genel_toplam") or 0))
        sonuc["bugunku_satis"] = toplam
    except Exception as exc:  # noqa: BLE001
        sonuc["baglanti_ok"] = False
        sonuc["hata"] = str(exc)

    try:
        from database.finans_service import FinansService

        makbuzlar = FinansService.kasa_makbuz_listele(makbuz_turu="TAHSILAT", limit=200)
        tahsil = Decimal("0")
        for m in makbuzlar or []:
            if getattr(m, "tarih", None) == bugun:
                tahsil += Decimal(str(getattr(m, "tutar", 0) or 0))
        sonuc["bugunku_tahsilat"] = tahsil
    except Exception:
        if sonuc["bugunku_tahsilat"] is None:
            sonuc["bugunku_tahsilat"] = None

    try:
        from database.cari_service import CariService

        alacak = Decimal("0")
        for ozet in CariService.listele(cari_turu="Müşteri", hizli=True) or []:
            b = Decimal(str(ozet.get("bakiye") or 0))
            if b > 0:
                alacak += b
        sonuc["cari_alacak"] = alacak
    except Exception:
        sonuc["cari_alacak"] = None

        # Kritik stok alanı yok — hızlı örneklem (ilk 200 kart)
        try:
            from database.stok_service import StokService

            sifir = 0
            for stok in StokService.stoklari_ara("")[:200]:
                mevcut = sum(
                    (lot.kalan_miktar for lot in (getattr(stok, "lotlar", None) or [])),
                    Decimal("0"),
                )
                if mevcut <= 0:
                    sifir += 1
            sonuc["kritik_stok"] = sifir
            sonuc["kritik_aciklama"] = "Örneklemde miktarı 0 olan kart (kritik seviye tanımı yok)"
        except Exception:
            sonuc["kritik_stok"] = None
            sonuc["kritik_aciklama"] = "Veri bağlantısı bekleniyor"

    return sonuc


def son_islemleri_topla(limit: int = 25) -> list[dict[str, str]]:
    """Son işlemler — audit + güncel fatura özeti birleşik (servis üzerinden)."""
    satirlar: list[dict[str, str]] = []
    try:
        from database.database import get_system_session
        from database.system.models import AuditLog
        from sqlalchemy import select

        with get_system_session() as session:
            kayitlar = session.scalars(
                select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
            ).all()
            for a in kayitlar:
                t = a.tarih or datetime.now()
                satirlar.append(
                    {
                        "tarih": t.strftime("%d.%m.%Y"),
                        "saat": t.strftime("%H:%M"),
                        "islem": a.islem_turu or "",
                        "belge": a.kayit_id or "",
                        "cari": a.yeni_deger or "",
                        "tutar": "",
                        "kullanici": str(a.user_id or ""),
                        "modul": a.modul or "",
                    }
                )
    except Exception:
        pass

    if not satirlar:
        try:
            from database.satis_faturasi_service import SatisFaturasiService

            for f in (SatisFaturasiService.listele_ozet() or [])[:limit]:
                ft = f.get("fatura_tarihi")
                tarih = ft.strftime("%d.%m.%Y") if hasattr(ft, "strftime") else str(ft or "")
                satirlar.append(
                    {
                        "tarih": tarih,
                        "saat": str(f.get("islem_saati") or ""),
                        "islem": "Satış Faturası",
                        "belge": str(f.get("fatura_no") or ""),
                        "cari": str(f.get("musteri") or ""),
                        "tutar": para_tr(f.get("genel_toplam") or 0),
                        "kullanici": "",
                        "modul": "satis",
                    }
                )
        except Exception:
            pass
    return satirlar


def son_yedek_metni() -> str:
    try:
        from pathlib import Path
        import os

        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami"
        adaylar = list(base.rglob("*.db.bak")) + list(base.rglob("*yedek*.db"))
        if not adaylar:
            # Geçiş / servis yedek klasörleri
            for p in base.rglob("*"):
                if p.is_file() and "yedek" in p.name.lower():
                    adaylar.append(p)
        if not adaylar:
            return "—"
        son = max(adaylar, key=lambda p: p.stat().st_mtime)
        ts = datetime.fromtimestamp(son.stat().st_mtime)
        return ts.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def db_bagli_mi() -> bool:
    try:
        from database.database import get_session
        from sqlalchemy import text

        with get_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class AnaPanelKabuk:
    """Sol menü + üst başlık + durum çubuğu; app._arayuzu_olustur tarafından kurulur."""

    def __init__(self, app: tk.Tk):
        self.app = app
        self._saat_after = None
        self._menu_sirasi: list[str] = []

    def olustur(self) -> None:
        app = self.app
        app.configure(bg=ACIK_BG)

        # —— Üst başlık ——
        app.oturum_cubugu = tk.Frame(app, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        app.oturum_cubugu.pack(side="top", fill="x")

        sol_h = tk.Frame(app.oturum_cubugu, bg=BEYAZ)
        sol_h.pack(side="left", fill="y", padx=16, pady=10)
        tk.Label(
            sol_h, text="ANA PANEL", bg=BEYAZ, fg=LACIVERT, font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")
        tk.Label(
            sol_h,
            text="Ray Mobilya Aksesuarları yönetim ekranı",
            bg=BEYAZ,
            fg=PASIF,
            font=FONT_ALT,
        ).pack(anchor="w")

        sag_h = tk.Frame(app.oturum_cubugu, bg=BEYAZ)
        sag_h.pack(side="right", padx=12, pady=8)

        app.oturum_firma_label = tk.Label(sag_h, text="", bg=BEYAZ, fg=METIN, font=FONT_ALT, anchor="e")
        app.oturum_firma_label.pack(anchor="e")
        app.oturum_kullanici_label = tk.Label(sag_h, text="", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, anchor="e")
        app.oturum_kullanici_label.pack(anchor="e")
        app.oturum_donem_label = tk.Label(sag_h, text="", bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, anchor="e")
        app.oturum_donem_label.pack(anchor="e")
        app.header_saat_label = tk.Label(sag_h, text="", bg=BEYAZ, fg=LACIVERT, font=FONT_UI_BOLD, anchor="e")
        app.header_saat_label.pack(anchor="e", pady=(2, 0))

        dugmeler = tk.Frame(app.oturum_cubugu, bg=BEYAZ)
        dugmeler.pack(side="right", padx=(0, 4), pady=8)
        for metin, cmd in (
            ("Bildirim", app.bildirimleri_ac),
            ("Firma", app.firma_degistir_ac),
            ("Dönem", app.donem_degistir_ac),
            ("Kullanıcı", app.aktif_kullanici_degistir_ac),
            ("Şifre", app.sifre_degistir_ac),
            ("Çıkış", app.oturumu_kapat),
        ):
            b = tk.Button(
                dugmeler,
                text=metin,
                command=cmd,
                bg=BEYAZ,
                fg=LACIVERT,
                activebackground=ACIK_BG,
                activeforeground=LACIVERT,
                relief="flat",
                bd=0,
                padx=8,
                pady=4,
                font=FONT_ALT,
                cursor="hand2",
                highlightthickness=1,
                highlightbackground=CIZGI,
            )
            b.pack(side="left", padx=3)

        # —— Alt durum çubuğu ——
        app.durum_cubugu = tk.Frame(app, bg=KOYU_LACIVERT, height=28)
        app.durum_cubugu.pack(side="bottom", fill="x")
        app.durum_cubugu.pack_propagate(False)

        app._aktarim_yanip_soner = False
        app.aktarim_gosterge = tk.Canvas(
            app.durum_cubugu, width=14, height=14, highlightthickness=0, bg=KOYU_LACIVERT
        )
        app.aktarim_gosterge.pack(side="left", padx=(10, 6), pady=6)
        app._aktarim_nokta = app.aktarim_gosterge.create_oval(2, 2, 12, 12, fill="#9aa0a6", outline="")

        app.aktarim_durum_label = tk.Label(
            app.durum_cubugu,
            text="EvoBulut aktarımı yok",
            bg=KOYU_LACIVERT,
            fg=METIN_ACIK,
            font=FONT_KUCUK,
            anchor="w",
        )
        app.aktarim_durum_label.pack(side="left", padx=(0, 12))

        app.status_db_label = tk.Label(
            app.durum_cubugu, text="DB: —", bg=KOYU_LACIVERT, fg=METIN_ACIK, font=FONT_KUCUK
        )
        app.status_db_label.pack(side="left", padx=8)
        app.status_firma_label = tk.Label(
            app.durum_cubugu, text="Firma: —", bg=KOYU_LACIVERT, fg=METIN_ACIK, font=FONT_KUCUK
        )
        app.status_firma_label.pack(side="left", padx=8)
        app.status_donem_label = tk.Label(
            app.durum_cubugu, text="Dönem: —", bg=KOYU_LACIVERT, fg=METIN_ACIK, font=FONT_KUCUK
        )
        app.status_donem_label.pack(side="left", padx=8)
        app.status_surum_label = tk.Label(
            app.durum_cubugu, text="v—", bg=KOYU_LACIVERT, fg=METIN_ACIK, font=FONT_KUCUK
        )
        app.status_surum_label.pack(side="right", padx=10)
        app.status_yedek_label = tk.Label(
            app.durum_cubugu, text="Yedek: —", bg=KOYU_LACIVERT, fg=METIN_ACIK, font=FONT_KUCUK
        )
        app.status_yedek_label.pack(side="right", padx=8)

        # —— Gövde: sol menü + içerik ——
        govde = tk.Frame(app, bg=ACIK_BG)
        govde.pack(side="top", fill="both", expand=True)

        app.menu = tk.Frame(govde, bg=LACIVERT, width=SOL_MENU_GENISLIK, highlightthickness=0)
        app.menu.pack(side="left", fill="y")
        app.menu.pack_propagate(False)

        ust_logo = tk.Frame(app.menu, bg=KOYU_LACIVERT, height=72)
        ust_logo.pack(fill="x")
        ust_logo.pack_propagate(False)
        logo_kutu = tk.Frame(ust_logo, bg=KOYU_LACIVERT)
        logo_kutu.pack(expand=True)
        logo_yukle(logo_kutu).pack(side="left", padx=(12, 8), pady=12)
        tk.Label(
            logo_kutu,
            text=FIRMA_ADI,
            bg=KOYU_LACIVERT,
            fg=BEYAZ,
            font=FONT_SIDEBAR,
            wraplength=150,
            justify="left",
        ).pack(side="left", pady=12)

        # Kaydırılabilir menü
        menu_canvas = tk.Canvas(app.menu, bg=LACIVERT, highlightthickness=0, bd=0)
        menu_scroll = ttk.Scrollbar(app.menu, orient="vertical", command=menu_canvas.yview)
        menu_ic = tk.Frame(menu_canvas, bg=LACIVERT)
        menu_ic.bind(
            "<Configure>",
            lambda e: menu_canvas.configure(scrollregion=menu_canvas.bbox("all")),
        )
        menu_canvas.create_window((0, 0), window=menu_ic, anchor="nw", width=SOL_MENU_GENISLIK)
        menu_canvas.configure(yscrollcommand=menu_scroll.set)
        menu_canvas.pack(side="left", fill="both", expand=True)
        menu_scroll.pack(side="right", fill="y")

        app.menu_dugmeleri = {}
        self._menu_sirasi = []
        for etiket, anahtar, simge, vurgulu in MENU_OGELERI:
            dugme = SolMenuDugme(
                menu_ic,
                etiket=etiket,
                anahtar=anahtar,
                simge=simge,
                vurgulu=vurgulu,
                komut=lambda a=anahtar: app.sayfa_goster(a),
            )
            dugme.pack(fill="x", pady=1, padx=0)
            app.menu_dugmeleri[anahtar] = dugme
            self._menu_sirasi.append(anahtar)

        # Sağ alan: geri çubuğu (kalıcı) + içerik (modüller buraya çizilir)
        sag = tk.Frame(govde, bg=ACIK_BG)
        sag.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        app.geri_cubugu = tk.Frame(sag, bg=ACIK_BG)
        # pack/unpack geri_cubugu_guncelle ile yönetilir
        app.geri_dugme = tk.Button(
            app.geri_cubugu,
            text="←  Geri",
            command=lambda: getattr(app, "geri_git", lambda: None)(),
            bg=LACIVERT,
            fg=BEYAZ,
            activebackground=LACIVERT_HOVER,
            activeforeground=BEYAZ,
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            font=FONT_UI_BOLD,
            cursor="hand2",
            highlightthickness=0,
        )
        app.geri_dugme.pack(side="left", padx=(4, 0), pady=(0, 6))
        app.geri_ipucu = tk.Label(
            app.geri_cubugu,
            text="Önceki menüye dön",
            bg=ACIK_BG,
            fg=PASIF,
            font=FONT_ALT,
        )
        app.geri_ipucu.pack(side="left", padx=10, pady=(0, 6))

        app.icerik = tk.Frame(sag, bg=ACIK_BG)
        app.icerik.pack(fill="both", expand=True)

        app._aktif_sayfa = None
        app._nav_gecmis = []
        app._nav_yeniden_ac = None
        app._nav_geri_gidiyor = False
        app._nav_son_push = False
        app._nav_ileri = False
        app._ana_panel_kabuk = self
        self._saat_baslat()
        self._klavye_kisayollari()

        app.bind("<Destroy>", self._on_destroy, add="+")
        if hasattr(app, "geri_cubugu_guncelle"):
            app.geri_cubugu_guncelle()

    def _klavye_kisayollari(self) -> None:
        app = self.app

        def hizli_satis(_e=None):
            app.sayfa_goster("hizli_satis")
            return "break"

        def esc_yut(_e=None):
            # Esc uygulama kapatmasın
            return "break"

        app.bind_all("<Control-Shift-H>", hizli_satis)
        app.bind("<Escape>", esc_yut)

        def menu_ok(delta):
            sirali = [k for k in self._menu_sirasi if app.menu_dugmeleri.get(k) and app.menu_dugmeleri[k].winfo_ismapped()]
            if not sirali:
                return
            aktif = getattr(app, "_aktif_sayfa", None)
            try:
                idx = sirali.index(aktif) if aktif in sirali else 0
            except ValueError:
                idx = 0
            idx = (idx + delta) % len(sirali)
            app.sayfa_goster(sirali[idx])

        app.bind("<Alt-Down>", lambda e: menu_ok(1) or "break")
        app.bind("<Alt-Up>", lambda e: menu_ok(-1) or "break")

    def _saat_baslat(self) -> None:
        self._saat_tick()

    def _saat_tick(self) -> None:
        app = self.app
        try:
            if not app.winfo_exists():
                return
            app.header_saat_label.configure(
                text=datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
            )
        except tk.TclError:
            return
        self._saat_after = app.after(1000, self._saat_tick)

    def _on_destroy(self, event) -> None:
        if event.widget is not self.app:
            return
        if self._saat_after is not None:
            try:
                self.app.after_cancel(self._saat_after)
            except (tk.TclError, ValueError):
                pass
            self._saat_after = None

    def durum_guncelle(self) -> None:
        app = self.app
        try:
            from database.session_manager import oturum
            from branding import APP_VERSION

            bagli = db_bagli_mi()
            app.status_db_label.configure(
                text=("DB: Bağlı" if bagli else "DB: Yok"),
                fg=BASARI if bagli else UYARI,
            )
            firma = oturum.firma_unvan or "—"
            app.status_firma_label.configure(text=f"Firma: {firma}")
            donem = oturum.donem_adi or "—"
            app.status_donem_label.configure(text=f"Dönem: {donem}")
            app.status_surum_label.configure(text=f"v{APP_VERSION}")
            app.status_yedek_label.configure(text=f"Yedek: {son_yedek_metni()}")
        except Exception:
            pass

    def menu_secili_guncelle(self, anahtar: str) -> None:
        for k, dugme in self.app.menu_dugmeleri.items():
            if k == anahtar:
                dugme.set_aktif(True)
            elif k == "hizli_satis":
                dugme.vurgulu = True
                dugme.set_aktif(False)
            else:
                dugme.set_aktif(False)


def giris_dashboard_goster(app) -> None:
    """Ana sayfa (giriş) dashboard içeriği."""
    for w in app.icerik.winfo_children():
        w.destroy()

    # Kaydırılabilir ana içerik
    dis = tk.Frame(app.icerik, bg=ACIK_BG)
    dis.pack(fill="both", expand=True)
    canvas = tk.Canvas(dis, bg=ACIK_BG, highlightthickness=0)
    vsb = ttk.Scrollbar(dis, orient="vertical", command=canvas.yview)
    ic = tk.Frame(canvas, bg=ACIK_BG)
    ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=ic, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    def _genislik(event):
        canvas.itemconfigure(win, width=event.width)

    canvas.bind("<Configure>", _genislik)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    def _tekerlek(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _tekerlek_bagla(_e=None):
        canvas.bind_all("<MouseWheel>", _tekerlek)

    def _tekerlek_coz(_e=None):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _tekerlek_bagla)
    canvas.bind("<Leave>", _tekerlek_coz)
    ic.bind("<Enter>", _tekerlek_bagla)
    ic.bind("<Destroy>", lambda _e: _tekerlek_coz())

    pad = tk.Frame(ic, bg=ACIK_BG)
    pad.pack(fill="both", expand=True, padx=20, pady=16)

    # —— Özet kartlar ——
    ozet_baslik = tk.Frame(pad, bg=ACIK_BG)
    ozet_baslik.pack(fill="x")
    tk.Label(
        ozet_baslik, text="Günün Özeti", bg=ACIK_BG, fg=LACIVERT, font=("Segoe UI", 12, "bold")
    ).pack(side="left")
    tk.Frame(ozet_baslik, bg=SARI, height=2, width=48).pack(side="left", padx=10, pady=8)

    kartlar_f = tk.Frame(pad, bg=ACIK_BG)
    kartlar_f.pack(fill="x", pady=(10, 18))
    for c in range(4):
        kartlar_f.columnconfigure(c, weight=1, uniform="ozet")

    def _kart(parent, col, baslik, deger, alt, renk_cizgi=SARI):
        k = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        k.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)
        tk.Frame(k, bg=renk_cizgi, height=3).pack(fill="x")
        gov = tk.Frame(k, bg=BEYAZ)
        gov.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(gov, text=baslik, bg=BEYAZ, fg=PASIF, font=FONT_ALT).pack(anchor="w")
        deger_lbl = tk.Label(
            gov, text=deger, bg=BEYAZ, fg=LACIVERT, font=("Segoe UI", 16, "bold")
        )
        deger_lbl.pack(anchor="w", pady=(6, 2))
        alt_lbl = tk.Label(
            gov, text=alt, bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, wraplength=180, justify="left"
        )
        alt_lbl.pack(anchor="w")
        return deger_lbl, alt_lbl

    def _deger_para(v):
        if v is None:
            return "—"
        return para_tr(v) + " ₺"

    def _deger_sayi(v):
        if v is None:
            return "—"
        return sayi_tr(v)

    # Önce yer tutucu; ağır sorgu arka planda
    d0, a0 = _kart(kartlar_f, 0, "Bugünkü Satış", "…", "Yükleniyor…")
    d1, a1 = _kart(kartlar_f, 1, "Bugünkü Tahsilat", "…", "Yükleniyor…", BASARI)
    d2, a2 = _kart(kartlar_f, 2, "Toplam Cari Alacak", "…", "Yükleniyor…", UYARI)
    d3, a3 = _kart(kartlar_f, 3, "Kritik Stok", "…", "Yükleniyor…", UYARI)

    def _ozet_doldur(ozet):
        if not app.winfo_exists() or not kartlar_f.winfo_exists():
            return
        bekleyen = "Veri bağlantısı bekleniyor" if not ozet.get("baglanti_ok") else "Bugün"
        d0.configure(text=_deger_para(ozet.get("bugunku_satis")))
        a0.configure(
            text=bekleyen if ozet.get("bugunku_satis") is None else "Onaylı satış faturaları"
        )
        d1.configure(text=_deger_para(ozet.get("bugunku_tahsilat")))
        a1.configure(
            text=(
                "Tahsilat makbuzları"
                if ozet.get("bugunku_tahsilat") is not None
                else "Veri bağlantısı bekleniyor"
            )
        )
        d2.configure(text=_deger_para(ozet.get("cari_alacak")))
        a2.configure(
            text=(
                "Müşteri bakiyeleri (+)"
                if ozet.get("cari_alacak") is not None
                else "Veri bağlantısı bekleniyor"
            )
        )
        d3.configure(text=_deger_sayi(ozet.get("kritik_stok")))
        a3.configure(text=ozet.get("kritik_aciklama") or "Veri bağlantısı bekleniyor")

    from ui_bg import arka_planda

    arka_planda(app, ozet_verileri_topla, on_ok=_ozet_doldur, on_err=lambda _e: _ozet_doldur({}))

    # —— Modül kartları ——
    tk.Label(
        pad, text="Modüller", bg=ACIK_BG, fg=LACIVERT, font=("Segoe UI", 12, "bold")
    ).pack(anchor="w", pady=(4, 8))

    mod_f = tk.Frame(pad, bg=ACIK_BG)
    mod_f.pack(fill="x")
    for c in range(4):
        mod_f.columnconfigure(c, weight=1, uniform="mod")

    def _modul_tikla(anahtar):
        app.sayfa_goster(anahtar)

    for i, (baslik, anahtar, simge, aciklama) in enumerate(MODUL_KARTLARI):
        r, c = divmod(i, 4)
        k = tk.Frame(mod_f, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI, cursor="hand2")
        k.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)
        ust = tk.Frame(k, bg=BEYAZ)
        ust.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(ust, text=simge, bg=BEYAZ, fg=SARI, font=("Segoe UI", 14)).pack(side="left")
        tk.Label(ust, text=baslik, bg=BEYAZ, fg=LACIVERT, font=FONT_UI_BOLD).pack(side="left", padx=8)
        if anahtar == "hizli_satis":
            tk.Frame(k, bg=SARI, height=2).pack(fill="x", padx=12)
        tk.Label(
            k, text=aciklama, bg=BEYAZ, fg=PASIF, font=FONT_KUCUK, wraplength=200, justify="left"
        ).pack(anchor="w", padx=12, pady=(6, 14))

        def _bind_all(widget, a=anahtar):
            widget.bind("<Button-1>", lambda _e, x=a: _modul_tikla(x))
            for ch in widget.winfo_children():
                _bind_all(ch, a)

        _bind_all(k)

    # —— Hızlı işlemler ——
    tk.Label(
        pad, text="Hızlı İşlemler", bg=ACIK_BG, fg=LACIVERT, font=("Segoe UI", 12, "bold")
    ).pack(anchor="w", pady=(16, 8))
    hiz_f = tk.Frame(pad, bg=ACIK_BG)
    hiz_f.pack(fill="x")

    def _hizli(kod: str):
        _hizli_islem_calistir(app, kod)

    for i, (etiket, kod) in enumerate(HIZLI_ISLEMLER):
        onemli = kod in ("yeni_satis", "barkodlu_satis", "gun_sonu", "yeni_alis_siparis")
        b = tk.Button(
            hiz_f,
            text=etiket,
            command=lambda k=kod: _hizli(k),
            bg=SARI if onemli else BEYAZ,
            fg=KOYU_LACIVERT if onemli else LACIVERT,
            activebackground=SARI_HOVER if onemli else ACIK_BG,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            font=FONT_ALT,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=SARI if onemli else CIZGI,
        )
        b.grid(row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
    for c in range(4):
        hiz_f.columnconfigure(c, weight=1)

    # —— Son işlemler ——
    tk.Label(
        pad, text="Son İşlemler", bg=ACIK_BG, fg=LACIVERT, font=("Segoe UI", 12, "bold")
    ).pack(anchor="w", pady=(16, 8))

    tablo_f = tk.Frame(pad, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    tablo_f.pack(fill="both", expand=True)
    kolonlar = ("tarih", "saat", "islem", "belge", "cari", "tutar", "modul")
    tablo = ttk.Treeview(
        tablo_f, columns=kolonlar, show="headings", height=8, style="AnaPanel.Treeview"
    )
    basliklar = {
        "tarih": "Tarih",
        "saat": "Saat",
        "islem": "İşlem",
        "belge": "Belge No",
        "cari": "Cari / Açıklama",
        "tutar": "Tutar",
        "modul": "Modül",
    }
    gen = {"tarih": 90, "saat": 60, "islem": 120, "belge": 110, "cari": 180, "tutar": 90, "modul": 80}
    for k in kolonlar:
        tablo.heading(k, text=basliklar[k])
        tablo.column(k, width=gen[k], anchor="w")
    vsb2 = ttk.Scrollbar(tablo_f, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=vsb2.set)
    tablo.pack(side="left", fill="both", expand=True)
    vsb2.pack(side="right", fill="y")
    tablo.tag_configure("tek", background=BEYAZ)
    tablo.tag_configure("cift", background="#EEF2F6")

    kayitlar = son_islemleri_topla()
    if not kayitlar:
        tablo.insert(
            "",
            "end",
            values=("", "", "Henüz işlem kaydı yok", "", "", "", ""),
            tags=("tek",),
        )
    else:
        for i, s in enumerate(kayitlar):
            tablo.insert(
                "",
                "end",
                values=(
                    s.get("tarih", ""),
                    s.get("saat", ""),
                    s.get("islem", ""),
                    s.get("belge", ""),
                    s.get("cari", ""),
                    s.get("tutar", ""),
                    s.get("modul", ""),
                ),
                tags=("cift" if i % 2 else "tek",),
            )

    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.durum_guncelle()


def _hazirlaniyor(app, ad: str) -> None:
    messagebox.showinfo("Bilgi", f"{ad}\n\nBu özellik hazırlanıyor.", parent=app)


def _hizli_islem_calistir(app, kod: str) -> None:
    if kod == "yeni_satis":
        if hasattr(app, "hizli_fatura_ac"):
            app._menu_islemi(app.hizli_fatura_ac)
        else:
            _hazirlaniyor(app, "Yeni Satış")
    elif kod == "yeni_tahsilat":
        if hasattr(app, "tahsilat_makbuzu_ac"):
            app._menu_islemi(app.tahsilat_makbuzu_ac)
        else:
            _hazirlaniyor(app, "Yeni Tahsilat")
    elif kod == "yeni_odeme":
        if hasattr(app, "odeme_makbuzu_ac"):
            app._menu_islemi(app.odeme_makbuzu_ac)
        else:
            _hazirlaniyor(app, "Yeni Ödeme")
    elif kod == "yeni_alis_siparis":
        if hasattr(app, "hizli_alis_siparis_ac"):
            app._menu_islemi(app.hizli_alis_siparis_ac)
        else:
            _hazirlaniyor(app, "Yeni Alış Siparişi")
    elif kod == "musteri_karti":
        if hasattr(app, "musteri_karti_ac"):
            app._menu_islemi(app.musteri_karti_ac)
        elif hasattr(app, "cariler_goster"):
            # Eski yedek: liste yerine mümkünse boş kart
            try:
                from cari_kart_ui import CariDialog

                app._menu_islemi(lambda: CariDialog(app, cari=None, cari_turu="Müşteri"))
            except Exception:
                app._menu_islemi(lambda: (app._icerigi_temizle(), app.cariler_goster()))
        else:
            _hazirlaniyor(app, "Müşteri Kartı")
    elif kod == "stok_sorgula":
        if hasattr(app, "stok_kartlari_goster"):
            app.sayfa_goster("stoklar")
            app.after(50, lambda: app._menu_islemi(app.stok_kartlari_goster))
        else:
            _hazirlaniyor(app, "Stok Sorgula")
    elif kod == "fiyat_gor":
        _hazirlaniyor(app, "Fiyat Gör")
    elif kod == "barkodlu_satis":
        app.sayfa_goster("hizli_satis")
    elif kod == "gun_sonu":
        try:
            from hizli_satis_gun_sonu_ui import HizliSatisGunSonuDialog

            HizliSatisGunSonuDialog(app)
        except Exception:
            _hazirlaniyor(app, "Gün Sonu Özeti")
    else:
        _hazirlaniyor(app, "İşlem")


def raporlar_menusu_goster(app) -> None:
    """Raporlar hub — mevcut rapor giriş noktalarına yönlendirir."""
    from doviz_kur_ui import doviz_kur_yonetimi_goster
    from doviz_rapor_ui import doviz_raporlari_goster

    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("raporlar")
    ttk.Label(app.icerik, text="RAPORLAR", style="Baslik.TLabel").pack(anchor="w", padx=20, pady=(16, 0))
    ttk.Label(
        app.icerik,
        text="Mevcut rapor ekranlarına buradan ulaşın.",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", padx=20, pady=(8, 0))
    alt = ttk.Frame(app.icerik, style="AnaPanel.TFrame")
    alt.pack(fill="x", padx=20, pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=420)
    ogeler = (
        ("SATIŞ RAPORLARI", getattr(app, "satis_raporlari_goster", None)),
        ("SATIN ALMA RAPORLARI", getattr(app, "alis_raporlari_goster", None)),
        ("STOK RAPORLARI", getattr(app, "stok_raporlari_goster", None)),
        ("DÖVİZ KURLARI", lambda: doviz_kur_yonetimi_goster(app)),
        ("DÖVİZ BAZINDA RAPORLAR", lambda: doviz_raporlari_goster(app)),
        ("ÖZET TABLOLAR", lambda: app.sayfa_goster("ozet_tablolar")),
    )
    for i, (baslik, komut) in enumerate(ogeler):
        if komut is None:
            continue
        app._alt_menu_dugme(alt, baslik, komut, row=i, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: raporlar_menusu_goster(app))


def ayarlar_goster(app) -> None:
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")
    ttk.Label(app.icerik, text="AYARLAR", style="Baslik.TLabel").pack(anchor="w", padx=20, pady=(16, 0))
    ttk.Label(
        app.icerik,
        text="Oturum ve sistem tercihleri.",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", padx=20, pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=420)
    from sistem_ui import hakkinda_goster
    from satis_ayarlari_ui import satis_ayarlari_goster

    for i, (baslik, komut) in enumerate(
        (
            ("SATIŞ AYARLARI", lambda: satis_ayarlari_goster(app)),
            ("FİRMA DEĞİŞTİR", app.firma_degistir_ac),
            ("DÖNEM DEĞİŞTİR", app.donem_degistir_ac),
            ("KULLANICI DEĞİŞTİR", app.aktif_kullanici_degistir_ac),
            ("ŞİFRE DEĞİŞTİR", app.sifre_degistir_ac),
            ("OTOMATİK EKRAN KİLİDİ", app.ekran_kilidi_ayari_ac),
            ("HAKKINDA", lambda: hakkinda_goster(app)),
            ("KULLANICI VE FİRMA YÖNETİMİ", lambda: app.sayfa_goster("sistem")),
        )
    ):
        app._alt_menu_dugme(alt, baslik, komut, row=i, column=0, sticky="ew", pady=4)
