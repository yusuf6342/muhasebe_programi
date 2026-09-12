"""EvoBulut Gelir/Gider aktarım diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ui_bg import arka_planda


class EvobulutGelirGiderAktarDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("EvoBulut — Gelir / Gider Aktar")
        self.geometry("540x300")
        self.minsize(500, 260)
        self.transient(parent)
        self.grab_set()
        self._busy = False

        ttk.Label(
            self,
            text="EvoBulut gelir/gider işlemlerini cari deftere ve faturalara aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "API: GelirGider/base (tur 40=Gider, 41=Gelir).\n"
                "Belge: EVB-GG-{id} — Hizmet Alış/Satış fatura listelerinde görünür.\n"
                "Cari defter + kapama (EVB-GGK) korunur; çift bakiye yazılmaz."
            ),
            wraplength=500,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="API’den gelir/gider aktar",
            command=self._apiden,
        ).pack(fill="x", pady=4)
        ttk.Button(dugmeler, text="Kapat", command=self.destroy).pack(fill="x", pady=(12, 0))

        self.durum = ttk.Label(self, text="")
        self.durum.pack(anchor="w", padx=14, pady=(8, 12))

    def _kimlik_var_mi(self) -> bool:
        from entegrasyon.evobulut_client import credentials_available

        if credentials_available():
            return True
        messagebox.showwarning(
            "EvoBulut API",
            "Kimlik bilgisi yok (entegrasyon/evobulut.env).",
            parent=self,
        )
        return False

    def _apiden(self) -> None:
        if self._busy:
            return
        if not self._kimlik_var_mi():
            return
        if not messagebox.askyesno(
            "Gelir/Gider aktarımı",
            "EvoBulut gelir/gider kayıtları cari deftere ve Gelir/Gider faturalarına yazılacak.\n"
            "İşlem birkaç dakika sürebilir. Devam?",
            parent=self,
        ):
            return
        self._busy = True
        self.durum.configure(text="Aktarılıyor…")

        def _is():
            from entegrasyon.gelir_gider_import import aktar_api_den

            return aktar_api_den(
                progress=lambda m: self.after(0, lambda msg=m: self.durum.configure(text=msg[:120]))
            )

        def _ok(sonuc):
            self._busy = False
            msg = (
                f"Çekilen: {sonuc.cekilen}\n"
                f"Oluşturulan: {sonuc.olusturulan}\n"
                f"Atlanan: {sonuc.atlanan}\n"
                f"Hata: {len(sonuc.hatalar)}"
            )
            if sonuc.hatalar:
                msg += "\n\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:8])
            self.durum.configure(text=msg.replace("\n", "  |  ")[:200])
            messagebox.showinfo("Aktarım sonucu", msg, parent=self)
            self.result = sonuc

        def _err(exc: BaseException) -> None:
            self._busy = False
            self.durum.configure(text="")
            messagebox.showerror("Aktarım", str(exc), parent=self)

        arka_planda(self, _is, on_ok=_ok, on_err=_err)
