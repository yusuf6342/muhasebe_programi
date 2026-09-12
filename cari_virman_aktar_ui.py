"""Cari virman Excel/CSV aktarım diyaloğu (EvoBulut REST yok)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_bg import arka_planda


class CariVirmanAktarDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Cari Virman — Dosyadan Aktar")
        self.geometry("540x320")
        self.minsize(500, 280)
        self.transient(parent)
        self.grab_set()
        self._busy = False

        ttk.Label(
            self,
            text="Cari virman fişlerini Excel/CSV ile aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "EvoBulut API’de Cari Virman listesi yok; Excel/CSV kullanın.\n"
                "Sütunlar: kaynak_kodu, hedef_kodu, tarih, tutar, aciklama, belge_no\n"
                "belge_no boşsa EVB-VRM-{satır} üretilir."
            ),
            wraplength=500,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="Excel / CSV dosyasından aktar…",
            command=self._dosyadan,
        ).pack(fill="x", pady=4)
        ttk.Button(dugmeler, text="Kapat", command=self.destroy).pack(fill="x", pady=(12, 0))

        self.durum = ttk.Label(self, text="")
        self.durum.pack(anchor="w", padx=14, pady=(8, 12))

    def _dosyadan(self) -> None:
        if self._busy:
            return
        yol = filedialog.askopenfilename(
            parent=self,
            title="Cari virman Excel/CSV",
            filetypes=[
                ("Excel / CSV", "*.xlsx;*.xlsm;*.csv"),
                ("Excel", "*.xlsx;*.xlsm"),
                ("CSV", "*.csv"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if not yol:
            return
        self._busy = True
        self.durum.configure(text="Aktarılıyor…")

        def _is():
            from entegrasyon.cari_virman_import import aktar_dosyadan

            return aktar_dosyadan(yol)

        def _ok(sonuc):
            self._busy = False
            msg = (
                f"Çekilen: {sonuc.cekilen}  |  Oluşturulan: {sonuc.olusturulan}  |  "
                f"Atlanan: {sonuc.atlanan}"
            )
            if sonuc.hatalar:
                msg += "\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:8])
            self.durum.configure(text=msg.replace("\n", "  |  ")[:200])
            messagebox.showinfo("Aktarım sonucu", msg, parent=self)
            self.result = sonuc

        def _err(exc: BaseException) -> None:
            self._busy = False
            self.durum.configure(text="")
            messagebox.showerror("Aktarım", str(exc), parent=self)

        arka_planda(self, _is, on_ok=_ok, on_err=_err)
