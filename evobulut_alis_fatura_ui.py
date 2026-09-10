"""EvoBulut alış fatura aktarım diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class EvobulutAlisFaturaAktarDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("EvoBulut — Alış Fatura Aktar")
        self.geometry("540x320")
        self.minsize(500, 280)
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="EvoBulut alış faturalarını bu programa aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "API: fatura listesi tur=30. Her fatura için detay çekilir (~1 sn/adet).\n"
                "Stok girişi ve cari borç yazılır. Eksik stok kartları otomatik eklenir.\n"
                "Aynı belge no tekrar yazılmaz."
            ),
            wraplength=500,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="API’den alış faturalarını aktar",
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
        if not self._kimlik_var_mi():
            return
        if not messagebox.askyesno(
            "Alış fatura aktarımı",
            "EvoBulut’taki alış faturaları aktarılacak.\n"
            "İşlem yüzlerce istek sürebilir. Devam?",
            parent=self,
        ):
            return
        self.durum.configure(text="Aktarılıyor…")
        self.update_idletasks()
        try:
            from entegrasyon.alis_fatura_import import aktar_api_den
            from entegrasyon.evobulut_client import EvobulutApiError, EvobulutConfigError

            sonuc = aktar_api_den(
                progress=lambda m: (
                    self.durum.configure(text=m),
                    self.update_idletasks(),
                )
            )
        except (EvobulutConfigError, EvobulutApiError) as exc:
            messagebox.showerror("EvoBulut", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Aktarım", str(exc), parent=self)
            return

        msg = (
            f"Çekilen: {sonuc.cekilen}\n"
            f"Oluşturulan: {sonuc.olusturulan}\n"
            f"Atlanan: {sonuc.atlanan}\n"
            f"Yeni stok kartı: {sonuc.stok_eklenen}\n"
            f"Hata: {len(sonuc.hatalar)}"
        )
        if sonuc.hatalar:
            msg += "\n\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:8])
        self.durum.configure(text=msg.replace("\n", "  |  ")[:200])
        messagebox.showinfo("Aktarım sonucu", msg, parent=self)
        self.result = sonuc
