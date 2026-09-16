"""Kullanıcı girişi, şifre değiştirme ve firma seçim ekranları (AŞAMA 3)."""

from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import firma_db_ac, get_system_session
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.models import AppSetting, Company, User
from firma_secim_theme import (
    COLOR_BG,
    COLOR_DANGER,
    COLOR_MUTED,
    COLOR_NAVY,
    COLOR_NAVY_DEEP,
    COLOR_NAVY_MID,
    COLOR_OK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_YELLOW_SOFT,
    aktif_donem_oku,
    firmalari_filtrele,
    kart_sutun_sayisi,
    konum_metni,
    ui_font,
    varsayilan_secim_id,
)

_log = logging.getLogger("cin_muhasebe.auth_ui")


@dataclass
class FirmaOzet:
    id: int
    firma_uid: str
    firma_kodu: str
    unvan: str
    db_path: str
    aktif: bool = True
    varsayilan_para_birimi: str = "TRY"
    kisa_ad: str | None = None
    logo_yolu: str | None = None
    vergi_no: str | None = None
    vergi_dairesi: str | None = None
    adres: str | None = None
    il: str | None = None
    ilce: str | None = None
    aktif_donem: str | None = None


def firma_ozet(f: Company, *, donem_yukle: bool = True) -> FirmaOzet:
    donem = aktif_donem_oku(f.db_path) if donem_yukle else None
    return FirmaOzet(
        id=f.id,
        firma_uid=f.firma_uid,
        firma_kodu=f.firma_kodu,
        unvan=f.unvan,
        db_path=f.db_path,
        aktif=bool(f.aktif),
        varsayilan_para_birimi=f.varsayilan_para_birimi or "TRY",
        kisa_ad=f.kisa_ad,
        logo_yolu=f.logo_yolu,
        vergi_no=f.vergi_no,
        vergi_dairesi=f.vergi_dairesi,
        adres=f.adres,
        il=f.il,
        ilce=f.ilce,
        aktif_donem=donem,
    )


def _ayar_oku(session, anahtar: str, varsayilan: str | None = None) -> str | None:
    kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
    if kayit is None:
        return varsayilan
    return kayit.deger


def _ayar_yaz(session, anahtar: str, deger: str) -> None:
    kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
    if kayit is None:
        session.add(AppSetting(anahtar=anahtar, deger=deger))
    else:
        kayit.deger = deger


def entry_yapistirma_etkin(entry: ttk.Entry | tk.Entry) -> None:
    """Windows/Tk'ta Ctrl+V ve sağ tık ile panodan yapıştırmayı garanti eder."""

    def _yapistir(_event=None):
        try:
            metin = entry.clipboard_get()
        except tk.TclError:
            return "break"
        if not metin:
            return "break"
        try:
            entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        entry.insert("insert", metin.replace("\r", "").replace("\n", ""))
        return "break"

    def _sag_tik(event):
        menu = tk.Menu(entry, tearoff=0)
        menu.add_command(label="Yapıştır", command=lambda: _yapistir())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    for seq in ("<Control-v>", "<Control-V>", "<Shift-Insert>", "<<Paste>>"):
        entry.bind(seq, _yapistir)
    entry.bind("<Button-3>", _sag_tik)


def firma_oturumu_ac(firma: Company | FirmaOzet) -> None:
    """Yetki kontrolü + firma DB aç + oturum bilgisi."""
    if not firma.aktif:
        raise PermissionError("Bu firma pasif durumda.")
    if oturum.role_kod != "YONETICI":
        with get_system_session() as session:
            user = session.scalar(
                select(User)
                .options(selectinload(User.companies))
                .where(User.id == oturum.user_id)
            )
            if user is None:
                raise PermissionError("Oturum geçersiz.")
            yetkili = {uc.company_id for uc in user.companies}
            if firma.id not in yetkili:
                raise PermissionError("Bu firmaya erişim yetkiniz yok.")

    yol = Path(firma.db_path)
    if not yol.is_file():
        raise FileNotFoundError(f"Firma veritabanı bulunamadı:\n{yol}")

    firma_db_ac(firma.id, yol)
    oturum.set_company(
        company_id=firma.id,
        firma_kodu=firma.firma_kodu,
        firma_unvan=firma.unvan,
        firma_uid=firma.firma_uid,
        db_path=str(yol.resolve()),
    )
    try:
        from database.deleted_record_service import AuditDeleteService

        AuditDeleteService.schema_hazirla()
    except Exception:
        pass
    with get_system_session() as session:
        _ayar_yaz(session, "son_firma_id", str(firma.id))
        AuthService.audit(
            session,
            "firma_secimi",
            modul="sistem",
            kayit_id=str(firma.id),
            yeni_deger=firma.unvan,
        )


class GirisDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        from branding import APP_ICON_PNG, APP_NAME, APP_TAGLINE, LOGO_FILE, SPLASH_FILE, get_brand_image

        self.title(f"{APP_NAME} — Kullanıcı Girişi")
        self.resizable(False, False)
        self.result = False
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cikis)

        cerceve = ttk.Frame(self, padding=(28, 24))
        cerceve.pack(fill="both", expand=True)
        cerceve.columnconfigure(0, weight=1)

        # --- Marka / başlık ---
        ust = ttk.Frame(cerceve)
        ust.grid(row=0, column=0, sticky="ew")
        ust.columnconfigure(0, weight=1)

        self._logo_ref = get_brand_image(SPLASH_FILE, max_width=320, max_height=110)
        if self._logo_ref is None:
            self._logo_ref = get_brand_image(LOGO_FILE, max_width=320, max_height=110)
        if self._logo_ref is None:
            self._logo_ref = get_brand_image(APP_ICON_PNG, max_width=96, max_height=96)
        if self._logo_ref is not None:
            tk.Label(ust, image=self._logo_ref).grid(row=0, column=0, pady=(0, 10))

        ttk.Label(ust, text=APP_NAME, font=("Segoe UI", 16, "bold")).grid(
            row=1, column=0, pady=(0, 2)
        )
        ttk.Label(ust, text=APP_TAGLINE, font=("Segoe UI", 9)).grid(
            row=2, column=0, pady=(0, 18)
        )

        # --- Form: etiketler sağa, girişler aynı genişlikte ---
        form = ttk.Frame(cerceve)
        form.grid(row=1, column=0)
        form.columnconfigure(0, minsize=108)
        form.columnconfigure(1, minsize=220)

        ttk.Label(form, text="Kullanıcı adı:").grid(
            row=0, column=0, sticky="e", padx=(0, 12), pady=6
        )
        self.kullanici = ttk.Entry(form, width=28)
        self.kullanici.grid(row=0, column=1, sticky="ew", pady=6)
        self.kullanici.insert(0, "admin")
        entry_yapistirma_etkin(self.kullanici)

        ttk.Label(form, text="Şifre:").grid(
            row=1, column=0, sticky="e", padx=(0, 12), pady=6
        )
        self.sifre = ttk.Entry(form, width=28, show="*")
        self.sifre.grid(row=1, column=1, sticky="ew", pady=6)
        entry_yapistirma_etkin(self.sifre)
        self._sifre_gorunur = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text="Göster",
            variable=self._sifre_gorunur,
            command=self._sifre_goster_gizle,
        ).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=6)

        # --- Hata + butonlar (form ile aynı hizada) ---
        alt = ttk.Frame(cerceve)
        alt.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        alt.columnconfigure(0, weight=1)

        self.hata = ttk.Label(alt, text="", foreground="#c62828", anchor="center")
        self.hata.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        butonlar = ttk.Frame(alt)
        butonlar.grid(row=1, column=0)
        ttk.Button(butonlar, text="Programdan Çık", command=self._cikis).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(butonlar, text="Giriş Yap", command=self._giris).pack(side="left")

        self.kullanici.bind("<Return>", lambda _e: self.sifre.focus_set())
        self.sifre.bind("<Return>", lambda _e: self._giris())
        self.sifre.focus_set()
        self.update_idletasks()
        self._ortala(parent)

    def _ortala(self, parent: tk.Misc) -> None:
        from branding import center_toplevel_on_screen

        # Ana pencere withdraw iken parent kök koordinatları güvenilir değil → ekran ortası
        try:
            mapped = bool(parent.winfo_viewable())
        except tk.TclError:
            mapped = False
        if not mapped:
            center_toplevel_on_screen(self)
            return
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            w, h = 420, 280
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
            if px < -50 or py < -50:
                center_toplevel_on_screen(self)
                return
            self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
            self.lift()
            self.focus_force()
        except tk.TclError:
            center_toplevel_on_screen(self)

    def _sifre_goster_gizle(self) -> None:
        self.sifre.configure(show="" if self._sifre_gorunur.get() else "*")

    def _cikis(self) -> None:
        self.result = False
        self.destroy()

    def _giris(self) -> None:
        self.hata.configure(text="")
        try:
            with get_system_session() as session:
                AuthService.giris(session, self.kullanici.get(), self.sifre.get())
        except ValueError as hata:
            self.hata.configure(text=str(hata))
            self.sifre.delete(0, "end")
            self.sifre.focus_set()
            return
        except Exception as hata:
            messagebox.showerror("Giriş", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class SifreDegistirDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, zorunlu: bool = False):
        super().__init__(parent)
        self.title("Şifre Değiştir")
        self.resizable(False, False)
        self.result = False
        self.zorunlu = zorunlu
        self.transient(parent)
        self.grab_set()
        if zorunlu:
            self.protocol("WM_DELETE_WINDOW", self._zorunlu_iptal)
        else:
            self.protocol("WM_DELETE_WINDOW", self.destroy)

        cerceve = ttk.Frame(self, padding=20)
        cerceve.pack(fill="both", expand=True)
        if zorunlu:
            ttk.Label(
                cerceve,
                text="İlk girişte şifrenizi değiştirmeniz zorunludur.",
                foreground="#b71c1c",
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(cerceve, text="Mevcut şifre:").grid(row=1, column=0, sticky="w", pady=5)
        self.eski = ttk.Entry(cerceve, width=28, show="*")
        self.eski.grid(row=1, column=1, pady=5, padx=8)
        entry_yapistirma_etkin(self.eski)
        ttk.Label(cerceve, text="Yeni şifre:").grid(row=2, column=0, sticky="w", pady=5)
        self.yeni = ttk.Entry(cerceve, width=28, show="*")
        self.yeni.grid(row=2, column=1, pady=5, padx=8)
        entry_yapistirma_etkin(self.yeni)
        ttk.Label(cerceve, text="Yeni şifre (tekrar):").grid(row=3, column=0, sticky="w", pady=5)
        self.yeni2 = ttk.Entry(cerceve, width=28, show="*")
        self.yeni2.grid(row=3, column=1, pady=5, padx=8)
        entry_yapistirma_etkin(self.yeni2)

        butonlar = ttk.Frame(cerceve)
        butonlar.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        if not zorunlu:
            ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(butonlar, text="Kaydet", command=self._kaydet).pack(side="left")
        self.eski.focus_set()

    def _zorunlu_iptal(self) -> None:
        messagebox.showwarning(
            "Şifre",
            "İlk girişte şifre değiştirmeden devam edemezsiniz.",
            parent=self,
        )

    def _kaydet(self) -> None:
        yeni = self.yeni.get()
        if yeni != self.yeni2.get():
            messagebox.showwarning("Şifre", "Yeni şifreler eşleşmiyor.", parent=self)
            return
        try:
            with get_system_session() as session:
                AuthService.sifre_degistir(session, oturum.user_id, self.eski.get(), yeni)
                AuthService.audit(session, "sifre_degistirme", modul="sistem")
        except ValueError as hata:
            messagebox.showerror("Şifre", str(hata), parent=self)
            return
        messagebox.showinfo("Şifre", "Şifreniz güncellendi.", parent=self)
        self.result = True
        self.destroy()


class FirmaSecimDialog(tk.Toplevel):
    """Modern kurumsal firma seçim ekranı — mevcut açılış / yetki akışı korunur."""

    _MSG_SECIM = "Devam etmek için bir firma seçmelisiniz."

    def __init__(self, parent: tk.Misc, *, yeni_firma_izinli: bool = False):
        super().__init__(parent)
        from branding import APP_NAME, APP_VERSION, APP_ICON_PNG, LOGO_FILE, apply_window_icon, center_toplevel_on_screen, get_brand_image

        self.title("Firma Seçimi")
        self.configure(bg=COLOR_BG)
        self.result: FirmaOzet | None = None
        self.yeni_firma_izinli = yeni_firma_izinli
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._iptal)

        self._firmalar: list[FirmaOzet] = []
        self._gorunen: list[FirmaOzet] = []
        self._secili_id: int | None = None
        self._kartlar: dict[int, dict] = {}
        self._logo_refs: list = []
        self._aciliyor = False
        self._filtre_job: str | None = None
        self._son_id: str | None = None
        self._varsayilan_id: int | None = None

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1100, max(900, int(sw * 0.72)))
        h = min(720, max(560, int(sh * 0.78)))
        self.geometry(f"{w}x{h}")
        self.minsize(780, 520)

        apply_window_icon(self)
        self._build_ui(APP_NAME, APP_VERSION, APP_ICON_PNG, LOGO_FILE, get_brand_image)
        self.bind("<Escape>", lambda _e: self._iptal())
        self.bind("<Return>", lambda _e: self._gir())
        self.arama.bind("<Return>", lambda _e: self._gir())
        self.bind("<Up>", lambda e: self._okla(-1))
        self.bind("<Down>", lambda e: self._okla(1))
        self.bind("<Left>", lambda e: self._okla(-1))
        self.bind("<Right>", lambda e: self._okla(1))
        self.bind("<Configure>", self._on_resize)

        self._listele(ilk=True)
        self.update_idletasks()
        center_toplevel_on_screen(self)
        self.after(80, lambda: self.arama.focus_set() if self.winfo_exists() else None)

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self, app_name, app_version, icon_png, logo_file, get_brand_image) -> None:
        root = tk.Frame(self, bg=COLOR_BG)
        root.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(root, bg=COLOR_NAVY, height=96)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_inner = tk.Frame(header, bg=COLOR_NAVY)
        header_inner.pack(fill="both", expand=True, padx=28, pady=14)

        self._header_logo = get_brand_image(icon_png, max_width=56, max_height=56)
        if self._header_logo is None:
            self._header_logo = get_brand_image(logo_file, max_width=120, max_height=48)
        if self._header_logo is not None:
            self._logo_refs.append(self._header_logo)
            tk.Label(header_inner, image=self._header_logo, bg=COLOR_NAVY).pack(
                side="left", padx=(0, 16)
            )

        baslik_kutu = tk.Frame(header_inner, bg=COLOR_NAVY)
        baslik_kutu.pack(side="left", fill="y")
        tk.Label(
            baslik_kutu,
            text="FİRMA SEÇİMİ",
            font=ui_font(30, "bold", self),
            fg=COLOR_WHITE,
            bg=COLOR_NAVY,
        ).pack(anchor="w")
        tk.Label(
            baslik_kutu,
            text="Çalışmak istediğiniz firmayı seçiniz",
            font=ui_font(11, root=self),
            fg=COLOR_YELLOW_SOFT,
            bg=COLOR_NAVY,
        ).pack(anchor="w", pady=(2, 0))

        tk.Frame(root, bg=COLOR_YELLOW, height=4).pack(fill="x")

        # Welcome
        hos = tk.Frame(root, bg=COLOR_BG)
        hos.pack(fill="x", padx=28, pady=(16, 4))
        kullanici = oturum.ad_soyad or oturum.kullanici_adi or ""
        hos_metin = (
            f"Hoş geldiniz{', ' + kullanici if kullanici else ''}."
            " Aşağıdaki listeden firmayı seçerek devam edin."
        )
        tk.Label(
            hos,
            text=hos_metin,
            font=ui_font(11, root=self),
            fg=COLOR_NAVY_MID,
            bg=COLOR_BG,
            wraplength=900,
            justify="left",
        ).pack(anchor="w")

        # Search
        ara_satir = tk.Frame(root, bg=COLOR_BG)
        ara_satir.pack(fill="x", padx=28, pady=(12, 8))
        tk.Label(
            ara_satir,
            text="Firma Ara",
            font=ui_font(10, "bold", self),
            fg=COLOR_NAVY,
            bg=COLOR_BG,
        ).pack(side="left", padx=(0, 10))
        self.arama = ttk.Entry(ara_satir, width=42, font=ui_font(11, root=self))
        self.arama.pack(side="left", fill="x", expand=True)
        entry_yapistirma_etkin(self.arama)
        self.arama.bind("<KeyRelease>", self._arama_degisti)
        self._sonuc_etiket = tk.Label(
            ara_satir,
            text="",
            font=ui_font(9, root=self),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
        )
        self._sonuc_etiket.pack(side="left", padx=(12, 0))

        # Cards scroll area
        kart_dis = tk.Frame(root, bg=COLOR_BG)
        kart_dis.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        self._canvas = tk.Canvas(kart_dis, bg=COLOR_BG, highlightthickness=0, bd=0)
        self._scroll = ttk.Scrollbar(kart_dis, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._kart_host = tk.Frame(self._canvas, bg=COLOR_BG)
        self._kart_window = self._canvas.create_window((0, 0), window=self._kart_host, anchor="nw")
        self._kart_host.bind("<Configure>", self._scroll_region)
        self._canvas.bind("<Configure>", self._canvas_boyut)
        for w in (self, self._canvas, self._kart_host):
            w.bind("<MouseWheel>", self._mousewheel)

        self._durum = tk.Label(
            root,
            text="",
            font=ui_font(10, root=self),
            fg=COLOR_NAVY,
            bg=COLOR_BG,
        )
        self._durum.pack(fill="x", padx=28)

        # Buttons
        alt = tk.Frame(root, bg=COLOR_BG)
        alt.pack(fill="x", padx=28, pady=(4, 8))

        self._btn_cikis = tk.Button(
            alt,
            text="ÇIKIŞ",
            command=self._iptal,
            font=ui_font(10, "bold", self),
            bg="#E8EEF4",
            fg=COLOR_DANGER,
            activebackground="#DDE5EE",
            activeforeground=COLOR_DANGER,
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
        )
        self._btn_cikis.pack(side="left")

        sag = tk.Frame(alt, bg=COLOR_BG)
        sag.pack(side="right")

        self._btn_devam = tk.Button(
            sag,
            text="SEÇİLİ FİRMAYLA DEVAM ET",
            command=self._gir,
            font=ui_font(11, "bold", self),
            bg=COLOR_YELLOW,
            fg=COLOR_NAVY_DEEP,
            activebackground=COLOR_YELLOW_SOFT,
            activeforeground=COLOR_NAVY_DEEP,
            relief="flat",
            bd=0,
            padx=22,
            pady=11,
            cursor="hand2",
        )
        self._btn_devam.pack(side="right")

        if self.yeni_firma_izinli:
            self._btn_duzenle = tk.Button(
                sag,
                text="FİRMA DÜZENLE",
                command=self._firma_duzenle,
                font=ui_font(10, "bold", self),
                bg=COLOR_NAVY,
                fg=COLOR_WHITE,
                activebackground=COLOR_NAVY_MID,
                activeforeground=COLOR_WHITE,
                relief="flat",
                bd=0,
                padx=16,
                pady=11,
                cursor="hand2",
            )
            self._btn_duzenle.pack(side="right", padx=(0, 10))

            self._btn_yeni = tk.Button(
                sag,
                text="YENİ FİRMA OLUŞTUR",
                command=self._yeni_firma,
                font=ui_font(10, "bold", self),
                bg=COLOR_NAVY_MID,
                fg=COLOR_WHITE,
                activebackground=COLOR_NAVY,
                activeforeground=COLOR_WHITE,
                relief="flat",
                bd=0,
                padx=16,
                pady=11,
                cursor="hand2",
            )
            self._btn_yeni.pack(side="right", padx=(0, 10))

        # Footer
        footer = tk.Frame(root, bg=COLOR_NAVY_DEEP, height=36)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        foot_inner = tk.Frame(footer, bg=COLOR_NAVY_DEEP)
        foot_inner.pack(fill="both", expand=True, padx=20)

        parcalar = [app_name]
        if app_version:
            parcalar.append(f"v{app_version}")
        if kullanici:
            parcalar.append(kullanici)
        parcalar.append(datetime.now().strftime("%d.%m.%Y"))
        tk.Label(
            foot_inner,
            text="  ·  ".join(parcalar),
            font=ui_font(9, root=self),
            fg=COLOR_YELLOW_SOFT,
            bg=COLOR_NAVY_DEEP,
            anchor="w",
        ).pack(side="left", pady=8)

        self._app_name = app_name
        self._app_version = app_version

    # ── Scroll / resize ───────────────────────────────────────

    def _scroll_region(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _canvas_boyut(self, event) -> None:
        self._canvas.itemconfigure(self._kart_window, width=event.width)

    def _mousewheel(self, event) -> str:
        try:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass
        return "break"

    def _on_resize(self, event) -> None:
        if event.widget is not self:
            return
        sutun = kart_sutun_sayisi(
            len(self._gorunen),
            max(event.width - 80, 400),
        )
        if sutun == getattr(self, "_son_sutun", None):
            return
        self._son_sutun = sutun
        if getattr(self, "_resize_job", None):
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(150, self._kartlari_ciz)

    # ── Data ──────────────────────────────────────────────────

    def _iptal(self) -> None:
        self.result = None
        self.destroy()

    def _yeni_firma(self) -> None:
        try:
            from sistem_ui import SistemFirmaDialog

            dlg = SistemFirmaDialog(self)
            self.wait_window(dlg)
            if dlg.result:
                self._firmalar = []
                self._listele(ilk=True)
        except Exception as hata:
            _log.exception("Yeni firma açılamadı")
            messagebox.showerror("Yeni Firma", str(hata), parent=self)

    def _firma_duzenle(self) -> None:
        if self._secili_id is None:
            messagebox.showinfo("Firma", self._MSG_SECIM, parent=self)
            return
        try:
            from sistem_ui import SistemFirmaDialog

            dlg = SistemFirmaDialog(self, company_id=self._secili_id)
            self.wait_window(dlg)
            if dlg.result:
                self._firmalar = []
                self._listele(ilk=True)
        except Exception as hata:
            _log.exception("Firma düzenleme açılamadı")
            messagebox.showerror("Firma Düzenle", str(hata), parent=self)

    def _kullanici_firmalari(self) -> list[FirmaOzet]:
        try:
            with get_system_session() as session:
                user = session.scalar(
                    select(User)
                    .options(selectinload(User.role), selectinload(User.companies))
                    .where(User.id == oturum.user_id)
                )
                if user is None:
                    return []
                return [firma_ozet(f) for f in AuthService.kullanici_firmalari(session, user)]
        except Exception as hata:
            _log.exception("Firma listesi alınamadı: %s", hata)
            return []

    def _listele(self, ilk: bool = False) -> None:
        if ilk or not self._firmalar:
            self._firmalar = self._kullanici_firmalari()

        self._son_id = None
        self._varsayilan_id = None
        try:
            with get_system_session() as session:
                self._son_id = _ayar_oku(session, "son_firma_id")
                user = session.get(User, oturum.user_id) if oturum.user_id else None
                if user and user.varsayilan_firma_id:
                    self._varsayilan_id = user.varsayilan_firma_id
        except Exception as hata:
            _log.warning("Son firma ayarı okunamadı: %s", hata)

        self._filtre_uygula(secimi_koru=not ilk)
        if ilk:
            hedef = varsayilan_secim_id(
                self._gorunen,
                son_id=self._son_id,
                varsayilan_id=self._varsayilan_id,
            )
            self._secili_id = hedef
            self._kartlari_ciz()

    def _arama_degisti(self, _event=None) -> None:
        if self._filtre_job:
            try:
                self.after_cancel(self._filtre_job)
            except tk.TclError:
                pass
        self._filtre_job = self.after(120, lambda: self._filtre_uygula(secimi_koru=True))

    def _filtre_uygula(self, *, secimi_koru: bool = True) -> None:
        onceki = self._secili_id if secimi_koru else None
        sirali = list(self._firmalar)

        def _anahtar(f: FirmaOzet):
            ust = 0
            if self._son_id and str(f.id) == str(self._son_id):
                ust = -2
            elif self._varsayilan_id and f.id == self._varsayilan_id:
                ust = -1
            return (ust, (f.unvan or "").casefold())

        sirali.sort(key=_anahtar)
        self._gorunen = firmalari_filtrele(sirali, self.arama.get() if hasattr(self, "arama") else "")
        n = len(self._gorunen)
        self._sonuc_etiket.configure(
            text=f"{n} firma" if n else "Sonuç yok"
        )
        if onceki and any(f.id == onceki for f in self._gorunen):
            self._secili_id = onceki
        elif self._gorunen:
            self._secili_id = varsayilan_secim_id(
                self._gorunen,
                son_id=self._son_id,
                varsayilan_id=self._varsayilan_id,
            )
        else:
            self._secili_id = None
        self._kartlari_ciz()

    # ── Cards ─────────────────────────────────────────────────

    def _kartlari_ciz(self) -> None:
        if getattr(self, "_ciziliyor", False):
            return
        self._ciziliyor = True
        try:
            for child in self._kart_host.winfo_children():
                child.destroy()
            self._kartlar.clear()

            if not self._gorunen:
                tk.Label(
                    self._kart_host,
                    text="Gösterilecek firma bulunamadı.",
                    font=ui_font(12, root=self),
                    fg=COLOR_MUTED,
                    bg=COLOR_BG,
                ).pack(pady=40)
                return

            self.update_idletasks()
            genislik = max(self._canvas.winfo_width(), self.winfo_width() - 80, 600)
            sutun = kart_sutun_sayisi(len(self._gorunen), genislik)
            self._son_sutun = sutun
            for c in range(sutun):
                self._kart_host.columnconfigure(c, weight=1, uniform="kart")

            for i, firma in enumerate(self._gorunen):
                r, c = divmod(i, sutun)
                kart = self._kart_olustur(self._kart_host, firma)
                kart.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
                self._kartlar[firma.id] = {"frame": kart, "firma": firma}

            self.after(10, self._scroll_region)
        finally:
            self._ciziliyor = False

    def _kart_olustur(self, parent: tk.Misc, firma: FirmaOzet) -> tk.Frame:
        secili = self._secili_id == firma.id
        bg = COLOR_NAVY if secili else COLOR_WHITE
        border = COLOR_YELLOW if secili else COLOR_NAVY
        dis = tk.Frame(parent, bg=border, bd=0, highlightthickness=0)
        ic = tk.Frame(dis, bg=bg, padx=14, pady=12)
        ic.pack(fill="both", expand=True, padx=2, pady=2)

        ust = tk.Frame(ic, bg=bg)
        ust.pack(fill="x")

        logo_img = self._firma_logo_yukle(firma.logo_yolu)
        if logo_img is not None:
            tk.Label(ust, image=logo_img, bg=bg).pack(side="left", padx=(0, 10))

        baslik_fg = COLOR_WHITE if secili else COLOR_NAVY
        baslik = tk.Label(
            ust,
            text=firma.unvan or "—",
            font=ui_font(13, "bold", self),
            fg=baslik_fg,
            bg=bg,
            anchor="w",
            justify="left",
            wraplength=260,
        )
        baslik.pack(side="left", fill="x", expand=True)

        check = tk.Label(
            ust,
            text="✓" if secili else "",
            font=ui_font(14, "bold", self),
            fg=COLOR_YELLOW,
            bg=bg,
            width=2,
        )
        check.pack(side="right")

        tk.Frame(ic, bg=COLOR_YELLOW, height=3).pack(fill="x", pady=(10, 8))

        muted = COLOR_YELLOW_SOFT if secili else COLOR_MUTED
        body_fg = COLOR_WHITE if secili else COLOR_NAVY_MID

        def satir(etiket: str, deger: str) -> None:
            if not deger:
                return
            s = tk.Frame(ic, bg=bg)
            s.pack(fill="x", pady=1)
            tk.Label(
                s, text=etiket, font=ui_font(9, root=self), fg=muted, bg=bg, width=12, anchor="w"
            ).pack(side="left")
            tk.Label(
                s,
                text=deger,
                font=ui_font(10, root=self),
                fg=body_fg,
                bg=bg,
                anchor="w",
                wraplength=220,
                justify="left",
            ).pack(side="left", fill="x", expand=True)

        satir("Kod", firma.firma_kodu or "")
        if firma.vergi_no:
            satir("Vergi No", firma.vergi_no)
        konum = konum_metni(il=firma.il, ilce=firma.ilce, adres=firma.adres)
        if konum:
            satir("Konum", konum)
        if firma.aktif_donem:
            satir("Aktif dönem", firma.aktif_donem)
        if firma.varsayilan_para_birimi:
            satir("Para birimi", firma.varsayilan_para_birimi)

        durum_fg = COLOR_YELLOW if secili else (COLOR_OK if firma.aktif else COLOR_DANGER)
        tk.Label(
            ic,
            text=("Aktif" if firma.aktif else "Pasif"),
            font=ui_font(9, "bold", self),
            fg=durum_fg,
            bg=bg,
            anchor="w",
        ).pack(anchor="w", pady=(8, 0))

        def sec(_e=None, fid=firma.id):
            self._sec(fid)

        def ac(_e=None, fid=firma.id):
            self._secili_id = fid
            self._gir()

        def hover_in(_e=None, frame=dis, fid=firma.id):
            if self._secili_id != fid:
                frame.configure(bg=COLOR_YELLOW_SOFT)

        def hover_out(_e=None, frame=dis, fid=firma.id):
            if self._secili_id != fid:
                frame.configure(bg=COLOR_NAVY)

        def bagla(w: tk.Misc) -> None:
            w.bind("<Button-1>", sec)
            w.bind("<Double-Button-1>", ac)
            w.bind("<MouseWheel>", self._mousewheel)
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass

        for w in (dis, ic, ust, baslik, check):
            bagla(w)
            w.bind("<Enter>", hover_in)
            w.bind("<Leave>", hover_out)

        for child in ic.winfo_children():
            bagla(child)
            for sub in child.winfo_children():
                bagla(sub)

        return dis

    def _firma_logo_yukle(self, logo_yolu: str | None):
        if not logo_yolu:
            return None
        yol = Path(logo_yolu)
        if not yol.is_file():
            return None
        try:
            from PIL import Image, ImageTk  # type: ignore

            with Image.open(yol) as im:
                im = im.convert("RGBA")
                im.thumbnail((40, 40), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
            self._logo_refs.append(photo)
            return photo
        except Exception:
            try:
                photo = tk.PhotoImage(file=str(yol))
                self._logo_refs.append(photo)
                return photo
            except tk.TclError:
                return None

    def _sec(self, firma_id: int) -> None:
        if self._secili_id == firma_id:
            return
        self._secili_id = firma_id
        if getattr(self, "_sec_job", None):
            try:
                self.after_cancel(self._sec_job)
            except tk.TclError:
                pass
        self._sec_job = self.after(30, self._kartlari_ciz)

    def _okla(self, delta: int) -> str:
        if not self._gorunen:
            return "break"
        ids = [f.id for f in self._gorunen]
        if self._secili_id in ids:
            idx = ids.index(self._secili_id)
        else:
            idx = 0
        idx = max(0, min(len(ids) - 1, idx + delta))
        self._sec(ids[idx])
        return "break"

    # ── Open firm ─────────────────────────────────────────────

    def _gir(self) -> None:
        if self._aciliyor:
            return
        if self._secili_id is None:
            messagebox.showinfo("Firma", self._MSG_SECIM, parent=self)
            return
        firma_id = int(self._secili_id)
        self._aciliyor = True
        self._durum.configure(text="Firma açılıyor…")
        self._btn_devam.configure(state="disabled")
        self.update_idletasks()
        try:
            with get_system_session() as session:
                kayit = session.get(Company, firma_id)
                if kayit is None:
                    raise ValueError("Firma bulunamadı.")
                ozet = firma_ozet(kayit)
            firma_oturumu_ac(ozet)
        except PermissionError as hata:
            _log.warning("Firma yetki hatası: %s", hata)
            messagebox.showerror("Yetki", str(hata), parent=self)
            self._acma_sifirla()
            return
        except Exception as hata:
            _log.exception("Firma açılamadı")
            messagebox.showerror("Firma", str(hata), parent=self)
            self._acma_sifirla()
            return
        self.result = ozet
        self.destroy()

    def _acma_sifirla(self) -> None:
        self._aciliyor = False
        self._durum.configure(text="")
        try:
            self._btn_devam.configure(state="normal")
        except tk.TclError:
            pass


def oturum_akisi_calistir(parent: tk.Tk) -> bool:
    """Giriş → (zorunlu şifre) → firma seçimi. Başarılıysa True."""
    AuthService.cikis()
    while True:
        giris = GirisDialog(parent)
        parent.wait_window(giris)
        if not giris.result:
            return False

        if oturum.sifre_degistirmeli:
            sifre = SifreDegistirDialog(parent, zorunlu=True)
            parent.wait_window(sifre)
            if not sifre.result:
                AuthService.cikis()
                continue

        with get_system_session() as session:
            user = session.scalar(
                select(User)
                .options(selectinload(User.role), selectinload(User.companies))
                .where(User.id == oturum.user_id)
            )
            firmalar = (
                [firma_ozet(f) for f in AuthService.kullanici_firmalari(session, user)]
                if user else []
            )
            otomatik = (_ayar_oku(session, "tek_firma_otomatik_giris", "1") or "1") == "1"
            yeni_izin = oturum.has_permission("firma_yonetme")

        if len(firmalar) == 1 and otomatik:
            try:
                firma_oturumu_ac(firmalar[0])
                return True
            except Exception as hata:
                messagebox.showerror("Firma", str(hata), parent=parent)
                AuthService.cikis()
                continue

        if not firmalar:
            messagebox.showwarning(
                "Firma",
                "Erişebileceğiniz aktif firma yok. Yönetici ile görüşün.",
                parent=parent,
            )
            AuthService.cikis()
            continue

        secim = FirmaSecimDialog(parent, yeni_firma_izinli=yeni_izin)
        parent.wait_window(secim)
        if secim.result is None:
            AuthService.cikis()
            continue
        return True
