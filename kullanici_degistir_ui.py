"""Aktif kullanıcı değiştirme modalı + üst çubuk + isteğe bağlı ekran kilidi."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from database.session_manager import oturum
from database.user_switch import aktif_kullanici_secenekleri, switch_user
from belge_kullanici_ui import aktif_kullanici_adi

LACIVERT = "#1B2A4A"
SARI = "#F5C518"
BEYAZ = "#FFFFFF"
ACIK_GRI = "#F3F4F6"
KOYU = "#2B2F33"


def _kaydedilmemis_uyari(parent) -> str:
    """Döner: 'degistir' | 'taslak' | 'vazgec'."""
    dlg = tk.Toplevel(parent)
    dlg.title("Kaydedilmemiş değişiklikler")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)
    dlg.configure(bg=ACIK_GRI)
    sonuc = {"v": "vazgec"}
    tk.Label(
        dlg,
        text=(
            "Bu belgede kaydedilmemiş değişiklikler bulunmaktadır.\n"
            "Kullanıcı değiştirildiğinde belge yeni kullanıcı adına kaydedilecektir.\n"
            "Devam etmek istiyor musunuz?"
        ),
        bg=ACIK_GRI,
        fg=KOYU,
        justify="left",
        wraplength=420,
        font=("Segoe UI", 10),
    ).pack(padx=16, pady=(16, 12), anchor="w")
    alt = tk.Frame(dlg, bg=ACIK_GRI)
    alt.pack(fill="x", padx=12, pady=(0, 14))

    def _sec(v):
        sonuc["v"] = v
        dlg.destroy()

    ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(side="right", padx=4)
    ttk.Button(alt, text="Önce Taslak Kaydet", command=lambda: _sec("taslak")).pack(
        side="right", padx=4
    )
    tk.Button(
        alt,
        text="Kullanıcıyı Değiştir",
        command=lambda: _sec("degistir"),
        bg=SARI,
        fg=LACIVERT,
        relief="flat",
        font=("Segoe UI", 9, "bold"),
        padx=10,
        pady=4,
        cursor="hand2",
    ).pack(side="right", padx=4)
    dlg.wait_window()
    return sonuc["v"]


def kullanici_degistir_dialog(
    parent,
    *,
    active_screen: str = "",
    document_type: str | None = None,
    document_id: int | None = None,
    dirty_check: Callable[[], str] | None = None,
    on_success: Callable[[dict], None] | None = None,
) -> bool:
    """
    dirty_check → '' | 'empty' | 'unsaved' | 'saved'
    Dönüş: True ise geçiş yapıldı.
    """
    durum = dirty_check() if dirty_check else "empty"
    if durum == "unsaved":
        if (active_screen or "").upper().startswith("HIZLI"):
            # Sepet dolu uyarısı
            dlg = tk.Toplevel(parent)
            dlg.title("Sepette ürün var")
            dlg.transient(parent)
            dlg.grab_set()
            dlg.resizable(False, False)
            dlg.configure(bg=ACIK_GRI)
            sec = {"v": "vazgec"}
            tk.Label(
                dlg,
                text=(
                    "Sepette ürün bulunmaktadır.\n"
                    "Kullanıcı değiştirildiğinde satış, yeni aktif kullanıcı adına tamamlanır.\n"
                    "Devam etmek istiyor musunuz?"
                ),
                bg=ACIK_GRI,
                fg=KOYU,
                justify="left",
                wraplength=420,
                font=("Segoe UI", 10),
            ).pack(padx=16, pady=(16, 12), anchor="w")
            alt = tk.Frame(dlg, bg=ACIK_GRI)
            alt.pack(fill="x", padx=12, pady=(0, 14))

            def _sec(v):
                sec["v"] = v
                dlg.destroy()

            ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(
                side="right", padx=4
            )
            tk.Button(
                alt,
                text="Kullanıcıyı Değiştir",
                command=lambda: _sec("degistir"),
                bg=SARI,
                fg=LACIVERT,
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                padx=10,
                pady=4,
                cursor="hand2",
            ).pack(side="right", padx=4)
            dlg.wait_window()
            if sec["v"] != "degistir":
                return False
        else:
            secim = _kaydedilmemis_uyari(parent)
            if secim != "degistir":
                if secim == "taslak":
                    messagebox.showinfo(
                        "Taslak Kaydet",
                        "Lütfen önce belgedeki Kaydet / Taslak Kaydet ile kaydedin,\n"
                        "ardından tekrar Kullanıcı Değiştir’i kullanın.",
                        parent=parent,
                    )
                return False

    dlg = tk.Toplevel(parent)
    dlg.title("Aktif Kullanıcıyı Değiştir")
    dlg.configure(bg=ACIK_GRI)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("440x360")
    dlg.resizable(False, False)

    sonuc = {"ok": False}

    tk.Label(
        dlg,
        text="Aktif Kullanıcıyı Değiştir",
        bg=ACIK_GRI,
        fg=LACIVERT,
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w", padx=16, pady=(14, 8))

    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Mevcut kullanıcı:").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Label(frm, text=aktif_kullanici_adi(), font=("Segoe UI", 10, "bold")).grid(
        row=0, column=1, sticky="w", pady=4
    )

    kullanicilar = aktif_kullanici_secenekleri()
    # Mevcut kullanıcıyı listede tut ama seçim yeni kullanıcı olmalı
    adlar = [
        f"{u['ad_soyad']}  ({u['role_ad']})"
        for u in kullanicilar
        if u["id"] != oturum.user_id
    ]
    id_map = {
        f"{u['ad_soyad']}  ({u['role_ad']})": u
        for u in kullanicilar
        if u["id"] != oturum.user_id
    }
    if not adlar:
        # Tek kullanıcı varsa yine kendi hesabına doğrulama ile "yenile" izin verme — boş
        ttk.Label(frm, text="Geçiş yapılabilecek başka aktif kullanıcı yok.").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=8
        )
        ttk.Button(frm, text="Kapat", command=dlg.destroy).grid(row=2, column=1, sticky="e")
        dlg.wait_window()
        return False

    ttk.Label(frm, text="Yeni kullanıcı:").grid(row=1, column=0, sticky="w", pady=4)
    cmb = ttk.Combobox(frm, values=adlar, state="readonly", width=36)
    cmb.grid(row=1, column=1, sticky="ew", pady=4)
    cmb.current(0)

    rol_lbl = ttk.Label(frm, text="")
    rol_lbl.grid(row=2, column=1, sticky="w")

    def _rol_goster(_e=None):
        u = id_map.get(cmb.get())
        if u:
            pin = " · Hızlı PIN tanımlı" if u.get("pin_tanimli") else ""
            rol_lbl.configure(text=f"Rol: {u.get('role_ad') or '—'}{pin}")

    cmb.bind("<<ComboboxSelected>>", _rol_goster)
    _rol_goster()

    ttk.Label(frm, text="Şifre veya hızlı PIN:").grid(row=3, column=0, sticky="w", pady=4)
    sifre = ttk.Entry(frm, show="*", width=28)
    sifre.grid(row=3, column=1, sticky="w", pady=4)
    sifre.focus_set()

    ttk.Label(
        frm,
        text="Geçiş, seçilen kullanıcının kendi şifresi veya PIN’i ile yapılır.",
        wraplength=360,
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))

    def _temizle():
        try:
            sifre.delete(0, "end")
        except tk.TclError:
            pass

    def _uygula():
        u = id_map.get(cmb.get())
        if not u:
            messagebox.showwarning("Seçim", "Kullanıcı seçin.", parent=dlg)
            return
        try:
            yeni = switch_user(
                int(u["id"]),
                sifre.get(),
                active_screen=active_screen,
                document_type=document_type,
                document_id=document_id,
            )
        except ValueError as hata:
            _temizle()
            messagebox.showerror("Kullanıcı Değiştir", str(hata), parent=dlg)
            return
        except Exception as hata:
            _temizle()
            messagebox.showerror("Kullanıcı Değiştir", str(hata), parent=dlg)
            return
        _temizle()
        sonuc["ok"] = True
        messagebox.showinfo(
            "Kullanıcı Değiştirildi",
            f"Aktif kullanıcı {yeni.get('ad_soyad')} olarak değiştirildi.",
            parent=dlg,
        )
        dlg.destroy()
        if on_success:
            try:
                on_success(yeni)
            except Exception:
                pass

    alt = ttk.Frame(frm)
    alt.grid(row=5, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(alt, text="Vazgeç", command=dlg.destroy).pack(side="right", padx=4)
    ttk.Button(alt, text="Kullanıcı Değiştir", command=_uygula).pack(side="right")
    sifre.bind("<Return>", lambda _e: _uygula())
    dlg.wait_window()
    return bool(sonuc["ok"])


def aktif_kullanici_cubugu(
    parent,
    *,
    active_screen: str = "",
    get_document_meta: Callable[[], tuple[str | None, int | None]] | None = None,
    dirty_check: Callable[[], str] | None = None,
    on_changed: Callable[[dict], None] | None = None,
    bg: str | None = None,
) -> dict[str, Any]:
    """Üst çubuk: Aktif kullanıcı adı + Kullanıcı Değiştir butonu."""
    bg = bg or ACIK_GRI
    cerceve = tk.Frame(parent, bg=bg)
    tk.Label(cerceve, text="Aktif Kullanıcı:", bg=bg, fg=KOYU, font=("Segoe UI", 9)).pack(
        side="left", padx=(0, 4)
    )
    ad_lbl = tk.Label(
        cerceve,
        text=aktif_kullanici_adi(),
        bg=bg,
        fg=LACIVERT,
        font=("Segoe UI", 10, "bold"),
    )
    ad_lbl.pack(side="left", padx=(0, 8))

    def _yenile(_old=None, _new=None):
        try:
            ad_lbl.configure(text=aktif_kullanici_adi())
        except tk.TclError:
            oturum.off_user_changed(_yenile)

    def _ac():
        doc_type, doc_id = (None, None)
        if get_document_meta:
            try:
                doc_type, doc_id = get_document_meta()
            except Exception:
                pass
        ok = kullanici_degistir_dialog(
            parent.winfo_toplevel(),
            active_screen=active_screen,
            document_type=doc_type,
            document_id=doc_id,
            dirty_check=dirty_check,
            on_success=on_changed,
        )
        if ok:
            _yenile()

    btn = tk.Button(
        cerceve,
        text="Kullanıcı Değiştir",
        command=_ac,
        bg=SARI,
        fg=LACIVERT,
        relief="flat",
        font=("Segoe UI", 9, "bold"),
        padx=8,
        pady=3,
        cursor="hand2",
    )
    btn.pack(side="left")
    oturum.on_user_changed(_yenile)
    return {"cerceve": cerceve, "ad_label": ad_lbl, "yenile": _yenile, "ac": _ac}


class EkranKilidi:
    """İsteğe bağlı idle kilidi — belgeyi kapatmaz."""

    def __init__(self, root, *, dakika_getir: Callable[[], int] | None = None):
        self.root = root
        self._dakika_getir = dakika_getir or (lambda: 0)
        self._after_id = None
        self._kilitli = False
        self._overlay = None
        for seq in ("<Key>", "<Button>", "<Motion>"):
            try:
                root.bind_all(seq, self._aktivite, add="+")
            except tk.TclError:
                pass
        self._planla()

    def _dakika(self) -> int:
        try:
            return int(self._dakika_getir() or 0)
        except Exception:
            return 0

    def _aktivite(self, _e=None):
        if self._kilitli:
            return
        self._planla()

    def _planla(self):
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        dk = self._dakika()
        if dk <= 0:
            return
        self._after_id = self.root.after(dk * 60_000, self._kilitle)

    def _kilitle(self):
        if self._kilitli or not oturum.oturum_acik:
            return
        self._kilitli = True
        ov = tk.Toplevel(self.root)
        self._overlay = ov
        ov.title("Ekran Kilitli")
        ov.attributes("-topmost", True)
        try:
            ov.state("zoomed")
        except tk.TclError:
            ov.geometry("500x280")
        ov.configure(bg=LACIVERT)
        ov.grab_set()
        tk.Label(
            ov,
            text="Ekran kilitlendi",
            bg=LACIVERT,
            fg=BEYAZ,
            font=("Segoe UI", 16, "bold"),
        ).pack(pady=(40, 8))
        tk.Label(
            ov,
            text=f"Aktif: {aktif_kullanici_adi()}\nŞifre veya hızlı PIN ile açın.\n"
            "Başka kullanıcı kendi PIN/şifresiyle oturumu devralabilir.",
            bg=LACIVERT,
            fg=SARI,
            justify="center",
        ).pack(pady=8)
        frm = tk.Frame(ov, bg=LACIVERT)
        frm.pack(pady=12)
        ttk.Label(frm, text="Kullanıcı:").grid(row=0, column=0, sticky="w")
        kullanicilar = aktif_kullanici_secenekleri()
        adlar = [f"{u['ad_soyad']}  ({u['role_ad']})" for u in kullanicilar]
        id_map = {f"{u['ad_soyad']}  ({u['role_ad']})": u for u in kullanicilar}
        cmb = ttk.Combobox(frm, values=adlar, state="readonly", width=32)
        cmb.grid(row=0, column=1, padx=6)
        # Varsayılan: mevcut kullanıcı
        for a, u in id_map.items():
            if u["id"] == oturum.user_id:
                cmb.set(a)
                break
        if not cmb.get() and adlar:
            cmb.current(0)
        ttk.Label(frm, text="Şifre / PIN:").grid(row=1, column=0, sticky="w", pady=6)
        sifre = ttk.Entry(frm, show="*", width=24)
        sifre.grid(row=1, column=1, sticky="w", pady=6)
        sifre.focus_set()

        def _ac():
            u = id_map.get(cmb.get())
            if not u:
                return
            try:
                if u["id"] == oturum.user_id:
                    # Aynı kullanıcı — doğrula ama switch_user aynı kişiye de çalışır
                    switch_user(int(u["id"]), sifre.get(), active_screen="EKRAN_KILIDI")
                else:
                    switch_user(int(u["id"]), sifre.get(), active_screen="EKRAN_KILIDI")
            except ValueError as hata:
                sifre.delete(0, "end")
                messagebox.showerror("Kilit", str(hata), parent=ov)
                return
            sifre.delete(0, "end")
            self._kilitli = False
            try:
                ov.grab_release()
                ov.destroy()
            except tk.TclError:
                pass
            self._overlay = None
            self._planla()

        ttk.Button(frm, text="Kilidi Aç", command=_ac).grid(row=2, column=1, sticky="e", pady=10)
        sifre.bind("<Return>", lambda _e: _ac())
        ov.protocol("WM_DELETE_WINDOW", lambda: None)
