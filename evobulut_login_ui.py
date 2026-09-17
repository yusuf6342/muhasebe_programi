"""EvoBulut API kimlik / şifre girişi diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from entegrasyon.evobulut_client import (
    DEFAULT_BASE,
    EvobulutApiError,
    EvobulutClient,
    EvobulutCredentials,
    peek_credentials,
    save_credentials,
)


class EvobulutLoginDialog(tk.Toplevel):
    """Kullanıcı kodu + şifre; isteğe bağlı kayıt; giriş denemesi."""

    def __init__(self, parent, *, baslik: str = "EvoBulut API girişi", zorunlu: bool = True):
        super().__init__(parent)
        self.result: EvobulutCredentials | None = None
        self.title(baslik)
        self.geometry("460x320")
        self.minsize(420, 300)
        self.transient(parent)
        self.grab_set()
        self._zorunlu = zorunlu

        onceki = peek_credentials()

        ttk.Label(self, text="EvoBulut hesabı", style="Baslik.TLabel").pack(
            anchor="w", padx=14, pady=(14, 4)
        )
        ttk.Label(
            self,
            text="API için kullanıcı kodu ve şifrenizi girin. Kaydederseniz sonraki çağrılarda hazır gelir.",
            wraplength=420,
        ).pack(anchor="w", padx=14, pady=(0, 10))

        form = ttk.Frame(self)
        form.pack(fill="x", padx=14)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Kullanıcı kodu:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=5)
        self.kullanici = ttk.Entry(form, width=32)
        self.kullanici.grid(row=0, column=1, sticky="ew", pady=5)
        if onceki.get("kullanici_kodu"):
            self.kullanici.insert(0, onceki["kullanici_kodu"])

        ttk.Label(form, text="Şifre:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=5)
        sifre_satir = ttk.Frame(form)
        sifre_satir.grid(row=1, column=1, sticky="ew", pady=5)
        sifre_satir.columnconfigure(0, weight=1)
        self.sifre = ttk.Entry(sifre_satir, width=28, show="*")
        self.sifre.grid(row=0, column=0, sticky="ew")
        if onceki.get("sifre"):
            self.sifre.insert(0, onceki["sifre"])
        self._sifre_gorunur = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            sifre_satir,
            text="Göster",
            variable=self._sifre_gorunur,
            command=lambda: self.sifre.configure(show="" if self._sifre_gorunur.get() else "*"),
        ).grid(row=0, column=1, padx=(6, 0))

        ttk.Label(form, text="Uygulama (app):").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=5)
        self.app_adi = ttk.Entry(form, width=32)
        self.app_adi.grid(row=2, column=1, sticky="ew", pady=5)
        self.app_adi.insert(0, onceki.get("app") or "muhasebe_programi")

        self.kaydet = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self,
            text="Bilgileri kaydet (evobulut.env)",
            variable=self.kaydet,
        ).pack(anchor="w", padx=14, pady=(8, 4))

        self.durum = ttk.Label(self, text="", foreground="#8B0000", wraplength=420)
        self.durum.pack(anchor="w", padx=14, pady=(4, 0))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=14)
        ttk.Button(dugmeler, text="Bağlan", command=self._baglan).pack(side="right")
        ttk.Button(dugmeler, text="İptal", command=self._iptal).pack(side="right", padx=(0, 8))

        self.sifre.bind("<Return>", lambda _e: self._baglan())
        self.kullanici.bind("<Return>", lambda _e: self.sifre.focus_set())
        (self.sifre if onceki.get("kullanici_kodu") else self.kullanici).focus_set()

        self.protocol("WM_DELETE_WINDOW", self._iptal)

    def _iptal(self) -> None:
        self.result = None
        self.destroy()

    def _baglan(self) -> None:
        kullanici = self.kullanici.get().strip()
        sifre = self.sifre.get()
        app = self.app_adi.get().strip() or "muhasebe_programi"
        if not kullanici or not sifre.strip():
            self.durum.configure(text="Kullanıcı kodu ve şifre gerekli.")
            return
        creds = EvobulutCredentials(
            kullanici_kodu=kullanici,
            sifre=sifre,
            app=app,
            base_url=DEFAULT_BASE,
        )
        self.durum.configure(text="Bağlanılıyor…", foreground="#333333")
        self.update_idletasks()
        try:
            EvobulutClient(creds).login()
        except EvobulutApiError as exc:
            self.durum.configure(text=str(exc), foreground="#8B0000")
            messagebox.showerror("EvoBulut giriş", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            self.durum.configure(text=str(exc), foreground="#8B0000")
            messagebox.showerror("EvoBulut giriş", str(exc), parent=self)
            return

        if self.kaydet.get():
            try:
                yol = save_credentials(creds)
                self.durum.configure(text=f"Kaydedildi: {yol.name}", foreground="#1B5E20")
            except OSError as exc:
                messagebox.showwarning(
                    "Kayıt",
                    f"Giriş başarılı ama dosyaya yazılamadı:\n{exc}",
                    parent=self,
                )

        self.result = creds
        self.destroy()


def ensure_evobulut_credentials(parent) -> EvobulutCredentials | None:
    """API öncesi şifre ekranı açar; iptalde None."""
    dlg = EvobulutLoginDialog(parent)
    parent.wait_window(dlg)
    return dlg.result
