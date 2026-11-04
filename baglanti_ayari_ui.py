"""Yerel ağ / yerel SQLite bağlantı ayarı — sunucu IP, port, Bağlantıyı Sına."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from database.baglanti_modu import (
    BaglantiAyari,
    CalismaKipi,
    OrtamEtiketi,
    ayari_kaydet,
    ayari_yukle,
    baglanti_sina,
    postgres_parola_al,
    postgres_parola_kaydet,
)


class BaglantiAyariDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Bağlantı Ayarları — Yerel / Yerel Ağ")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: BaglantiAyari | None = None
        self.ayar = ayari_yukle()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Çalışma kipi").grid(row=0, column=0, sticky="w", pady=4)
        self.kip = tk.StringVar(value=self.ayar.kipi)
        kip_fr = ttk.Frame(frm)
        kip_fr.grid(row=0, column=1, sticky="w", pady=4)
        ttk.Radiobutton(
            kip_fr,
            text="Yerel tek bilgisayar (SQLite)",
            variable=self.kip,
            value=CalismaKipi.YEREL_SQLITE.value,
            command=self._kip_degisti,
        ).pack(anchor="w")
        ttk.Radiobutton(
            kip_fr,
            text="Yerel ağ (PostgreSQL — ana bilgisayar)",
            variable=self.kip,
            value=CalismaKipi.YEREL_AG_POSTGRES.value,
            command=self._kip_degisti,
        ).pack(anchor="w")

        self.pg_fr = ttk.LabelFrame(frm, text="PostgreSQL (yerel ağ)", padding=8)
        self.pg_fr.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)

        self.host = tk.StringVar(value=self.ayar.postgres.host)
        self.port = tk.StringVar(value=str(self.ayar.postgres.port))
        self.sistem_db = tk.StringVar(value=self.ayar.postgres.sistem_db)
        self.firma_db = tk.StringVar(value=self.ayar.postgres.firma_db or "")
        self.kullanici = tk.StringVar(value=self.ayar.postgres.kullanici)
        self.parola = tk.StringVar(value="")
        self.ortam = tk.StringVar(value=self.ayar.postgres.ortam)
        self.sslmode = tk.StringVar(value=self.ayar.postgres.sslmode)

        satirlar = (
            (0, "Sunucu adı / IP", self.host),
            (1, "Port", self.port),
            (2, "Sistem DB", self.sistem_db),
            (3, "Firma DB", self.firma_db),
            (4, "DB kullanıcısı", self.kullanici),
            (5, "Parola", self.parola),
        )
        for r, etiket, var in satirlar:
            ttk.Label(self.pg_fr, text=etiket).grid(row=r, column=0, sticky="w", pady=2)
            show = "*" if etiket == "Parola" else None
            ttk.Entry(self.pg_fr, textvariable=var, width=36, show=show).grid(
                row=r, column=1, sticky="ew", pady=2, padx=4
            )

        ttk.Label(self.pg_fr, text="Ortam").grid(row=6, column=0, sticky="w", pady=2)
        ttk.Combobox(
            self.pg_fr,
            textvariable=self.ortam,
            values=(OrtamEtiketi.DENEME.value, OrtamEtiketi.GERCEK.value),
            state="readonly",
            width=12,
        ).grid(row=6, column=1, sticky="w", pady=2, padx=4)

        ttk.Label(self.pg_fr, text="SSL (sslmode)").grid(row=7, column=0, sticky="w", pady=2)
        ttk.Combobox(
            self.pg_fr,
            textvariable=self.sslmode,
            values=("require", "verify-full", "prefer"),
            state="readonly",
            width=12,
        ).grid(row=7, column=1, sticky="w", pady=2, padx=4)

        self.durum = ttk.Label(frm, text="", wraplength=420)
        self.durum.grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        btn = ttk.Frame(frm)
        btn.grid(row=3, column=0, columnspan=2, sticky="e", pady=8)
        ttk.Button(btn, text="Bağlantıyı Sına", command=self._sina).pack(side="left", padx=4)
        ttk.Button(btn, text="Kaydet", command=self._kaydet).pack(side="left", padx=4)
        ttk.Button(btn, text="İptal", command=self.destroy).pack(side="left", padx=4)

        self._kip_degisti()
        self.after(50, lambda: self.parola.set("") or None)

    def _kip_degisti(self):
        ag = self.kip.get() == CalismaKipi.YEREL_AG_POSTGRES.value
        state = "normal" if ag else "disabled"
        for child in self.pg_fr.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _ayardan(self) -> BaglantiAyari:
        ayar = BaglantiAyari.from_dict(
            {
                "kipi": self.kip.get(),
                "postgres": {
                    "host": self.host.get().strip(),
                    "port": int(self.port.get() or 5432),
                    "sistem_db": self.sistem_db.get().strip(),
                    "firma_db": self.firma_db.get().strip() or None,
                    "kullanici": self.kullanici.get().strip(),
                    "sslmode": self.sslmode.get().strip() or "require",
                    "ortam": self.ortam.get().strip() or OrtamEtiketi.DENEME.value,
                    "terminal_kimligi": self.ayar.postgres.terminal_kimligi,
                },
            }
        )
        return ayar

    def _sina(self):
        ayar = self._ayardan()
        parola = self.parola.get() or postgres_parola_al()
        sonuc = baglanti_sina(ayar, parola=parola if ayar.ag_mi else None)
        if sonuc.get("ok"):
            self.durum.configure(
                text=f"Tamam: {sonuc.get('ozet')} "
                + (f"| PG {sonuc.get('server_version')}" if sonuc.get("server_version") else ""),
                foreground="#0a7a32",
            )
        else:
            self.durum.configure(
                text=f"Bağlantı başarısız: {sonuc.get('hata')}",
                foreground="#b00020",
            )

    def _kaydet(self):
        try:
            ayar = self._ayardan()
        except ValueError as exc:
            messagebox.showerror("Bağlantı", str(exc), parent=self)
            return
        if ayar.ag_mi and self.parola.get().strip():
            postgres_parola_kaydet(self.parola.get().strip())
        ayari_kaydet(ayar)
        self.result = ayar
        messagebox.showinfo(
            "Bağlantı",
            "Ayar kaydedildi.\n"
            f"Kip: {ayar.kipi}\n"
            f"{'Ağ: ' + ayar.postgres.ozet() if ayar.ag_mi else 'Yerel SQLite'}\n\n"
            "Değişikliğin tam uygulanması için programı yeniden başlatın.",
            parent=self,
        )
        self.destroy()


def baglanti_ayari_ac(parent) -> BaglantiAyari | None:
    dlg = BaglantiAyariDialog(parent)
    parent.wait_window(dlg)
    return dlg.result
