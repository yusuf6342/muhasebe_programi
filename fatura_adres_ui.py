"""Faturadan seçili cariye yeni adres ekleme penceresi."""

import tkinter as tk
from tkinter import messagebox, ttk

from database.cari_service import CariService


class YeniAdresDialog(tk.Toplevel):
    """Cari adres modeline (tür + açık adres + ilçe + il) uygun yeni adres formu.

    ``sonuc`` kayıt başarılıysa eklenen adres numarası, iptalde None olur.
    """

    def __init__(self, parent, cari_id: int, cari_adi: str = "", varsayilan_tip: str = "Fatura"):
        super().__init__(parent)
        self.cari_id = int(cari_id)
        self.sonuc: int | None = None
        self.title("Yeni Adres Ekle")
        self.transient(parent)
        self.resizable(False, False)

        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)
        govde.columnconfigure(1, weight=1)
        ttk.Label(govde, text=cari_adi or "", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(govde, text="Adres Türü *").grid(row=1, column=0, sticky="w", pady=3)
        self.tip = ttk.Combobox(
            govde, values=CariService.ADRES_TIPLERI, state="readonly", width=18
        )
        self.tip.set(varsayilan_tip if varsayilan_tip in CariService.ADRES_TIPLERI else "Fatura")
        self.tip.grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(govde, text="Açık Adres *").grid(row=2, column=0, sticky="nw", pady=3)
        self.adres = tk.Text(govde, width=44, height=3, wrap="word", font=("Segoe UI", 9))
        self.adres.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(govde, text="İlçe").grid(row=3, column=0, sticky="w", pady=3)
        self.ilce = ttk.Entry(govde, width=24)
        self.ilce.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(govde, text="İl").grid(row=4, column=0, sticky="w", pady=3)
        self.il = ttk.Entry(govde, width=24)
        self.il.grid(row=4, column=1, sticky="w", pady=3)
        self.hata_lbl = ttk.Label(govde, text="", foreground="#C62828")
        self.hata_lbl.grid(row=5, column=0, columnspan=2, sticky="w")

        alt = ttk.Frame(govde)
        alt.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="left", padx=(0, 6))
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="left")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.adres.focus_set()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def degerler(self) -> dict:
        return {
            "tip": (self.tip.get() or "").strip(),
            "adres": self.adres.get("1.0", "end").strip(),
            "ilce": (self.ilce.get() or "").strip(),
            "il": (self.il.get() or "").strip(),
        }

    def kaydet(self):
        d = self.degerler()
        if not d["adres"]:
            self.hata_lbl.configure(text="Açık adres zorunludur.")
            self.adres.focus_set()
            return
        try:
            self.sonuc = CariService.adres_ekle(
                self.cari_id, d["tip"], d["adres"], il=d["il"], ilce=d["ilce"]
            )
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("Yeni Adres", str(hata), parent=self)
            return
        self.destroy()


def yeni_adres_sor(parent, cari_id: int, cari_adi: str = "") -> int | None:
    """Pencereyi açar, kapanınca üst pencerenin grab'ını geri verir; eklenen adres no döner."""
    onceki_grab = None
    try:
        onceki_grab = parent.grab_current()
    except tk.TclError:
        pass
    dialog = YeniAdresDialog(parent, cari_id, cari_adi)
    parent.wait_window(dialog)
    if onceki_grab is not None:
        try:
            if onceki_grab.winfo_exists():
                onceki_grab.grab_set()
        except tk.TclError:
            pass
    return dialog.sonuc
