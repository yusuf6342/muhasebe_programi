"""Kullanıcı girişi, şifre değiştirme ve firma seçim ekranları (AŞAMA 3)."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import firma_db_ac, get_system_session
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.models import AppSetting, Company, User


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


def firma_ozet(f: Company) -> FirmaOzet:
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
        self.title("Kullanıcı Girişi")
        self.resizable(False, False)
        self.result = False
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cikis)

        cerceve = ttk.Frame(self, padding=24)
        cerceve.pack(fill="both", expand=True)

        ttk.Label(cerceve, text="MUHASEBE PROGRAMI", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 16)
        )
        ttk.Label(cerceve, text="Kullanıcı adı:").grid(row=1, column=0, sticky="w", pady=6)
        self.kullanici = ttk.Entry(cerceve, width=28)
        self.kullanici.grid(row=1, column=1, pady=6, padx=(8, 0))
        self.kullanici.insert(0, "admin")
        entry_yapistirma_etkin(self.kullanici)

        ttk.Label(cerceve, text="Şifre:").grid(row=2, column=0, sticky="w", pady=6)
        sifre_satir = ttk.Frame(cerceve)
        sifre_satir.grid(row=2, column=1, sticky="ew", pady=6, padx=(8, 0))
        self.sifre = ttk.Entry(sifre_satir, width=22, show="*")
        self.sifre.pack(side="left")
        entry_yapistirma_etkin(self.sifre)
        self._sifre_gorunur = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            sifre_satir,
            text="Göster",
            variable=self._sifre_gorunur,
            command=self._sifre_goster_gizle,
        ).pack(side="left", padx=(6, 0))

        self.hata = ttk.Label(cerceve, text="", foreground="#c62828")
        self.hata.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 8))

        butonlar = ttk.Frame(cerceve)
        butonlar.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
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
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            w, h = 420, 240
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        except tk.TclError:
            px = (self.winfo_screenwidth() - w) // 2
            py = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")

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
    def __init__(self, parent: tk.Misc, *, yeni_firma_izinli: bool = False):
        super().__init__(parent)
        self.title("Firma Seçimi")
        self.geometry("640x420")
        self.minsize(520, 360)
        self.result: FirmaOzet | None = None
        self.yeni_firma_izinli = yeni_firma_izinli
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._iptal)

        ust = ttk.Frame(self, padding=(16, 12))
        ust.pack(fill="x")
        ttk.Label(ust, text="Firma Seçimi", font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Label(ust, text="Ara:").pack(side="left", padx=(24, 4))
        self.arama = ttk.Entry(ust, width=24)
        self.arama.pack(side="left")
        self.arama.bind("<KeyRelease>", lambda _e: self._listele())

        self.liste = ttk.Treeview(
            self, columns=("kod", "unvan", "para"), show="headings", selectmode="browse"
        )
        self.liste.heading("kod", text="Kod")
        self.liste.heading("unvan", text="Ünvan")
        self.liste.heading("para", text="PB")
        self.liste.column("kod", width=90, anchor="center")
        self.liste.column("unvan", width=380, anchor="w")
        self.liste.column("para", width=50, anchor="center")
        self.liste.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.liste.bind("<Double-1>", lambda _e: self._gir())
        self.liste.bind("<Return>", lambda _e: self._gir())

        alt = ttk.Frame(self, padding=(16, 8))
        alt.pack(fill="x")
        if yeni_firma_izinli:
            ttk.Button(alt, text="Yeni Firma Oluştur", command=self._yeni_firma).pack(side="left")
        ttk.Button(alt, text="İptal", command=self._iptal).pack(side="right")
        ttk.Button(alt, text="Firmaya Gir", command=self._gir).pack(side="right", padx=(0, 8))

        self._firmalar: list[FirmaOzet] = []
        self._listele(ilk=True)

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
            messagebox.showerror("Yeni Firma", str(hata), parent=self)

    def _kullanici_firmalari(self) -> list[FirmaOzet]:
        with get_system_session() as session:
            user = session.scalar(
                select(User)
                .options(selectinload(User.role), selectinload(User.companies))
                .where(User.id == oturum.user_id)
            )
            if user is None:
                return []
            return [firma_ozet(f) for f in AuthService.kullanici_firmalari(session, user)]

    def _listele(self, ilk: bool = False) -> None:
        if ilk or not self._firmalar:
            self._firmalar = self._kullanici_firmalari()

        with get_system_session() as session:
            son_id = _ayar_oku(session, "son_firma_id")
            varsayilan_id = None
            user = session.get(User, oturum.user_id)
            if user and user.varsayilan_firma_id:
                varsayilan_id = user.varsayilan_firma_id

        arama = (self.arama.get() or "").strip().casefold()
        sirali = list(self._firmalar)

        def _anahtar(f: FirmaOzet):
            ust = 0
            if son_id and str(f.id) == str(son_id):
                ust = -2
            elif varsayilan_id and f.id == varsayilan_id:
                ust = -1
            return (ust, (f.unvan or "").casefold())

        sirali.sort(key=_anahtar)
        for item in self.liste.get_children():
            self.liste.delete(item)
        secilecek = None
        for f in sirali:
            if arama and arama not in (f.unvan or "").casefold() and arama not in (
                f.firma_kodu or ""
            ).casefold():
                continue
            iid = str(f.id)
            self.liste.insert(
                "", "end", iid=iid,
                values=(f.firma_kodu, f.unvan, f.varsayilan_para_birimi or "TRY"),
            )
            if secilecek is None:
                if varsayilan_id and f.id == varsayilan_id:
                    secilecek = iid
                elif son_id and str(f.id) == str(son_id):
                    secilecek = iid
        if secilecek is None and self.liste.get_children():
            secilecek = self.liste.get_children()[0]
        if secilecek:
            self.liste.selection_set(secilecek)
            self.liste.focus(secilecek)

    def _gir(self) -> None:
        secim = self.liste.selection()
        if not secim:
            messagebox.showinfo("Firma", "Lütfen bir firma seçin.", parent=self)
            return
        firma_id = int(secim[0])
        try:
            with get_system_session() as session:
                kayit = session.get(Company, firma_id)
                if kayit is None:
                    raise ValueError("Firma bulunamadı.")
                ozet = firma_ozet(kayit)
            firma_oturumu_ac(ozet)
        except PermissionError as hata:
            messagebox.showerror("Yetki", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("Firma", str(hata), parent=self)
            return
        self.result = ozet
        self.destroy()


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
