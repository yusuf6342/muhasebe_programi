import tkinter as tk
from tkinter import messagebox, ttk

from database.sube_service import SubeService


def sube_secim_hazirla(parent, mevcut_id=None):
    """Belge basliklarinda firma kapsamli aktif sube combobox'i olusturur."""
    from database.database import get_session
    from database.models.firma import Firma
    from sqlalchemy import select

    with get_session() as session:
        firma_id = session.scalar(select(Firma.id).order_by(Firma.id))
    if not firma_id:
        raise ValueError("Şube seçimi için firma bulunamadı.")
    merkez = SubeService.merkez(int(firma_id))
    secili_id = int(mevcut_id or merkez.id)
    harita = {}
    degerler = []
    for sube in SubeService.listele(int(firma_id), aktif_sadece=True):
        etiket = f"{sube.sube_kodu} - {sube.sube_adi}"
        harita[etiket] = int(sube.id)
        degerler.append(etiket)
    combo = ttk.Combobox(parent, values=degerler, state="readonly", width=25)
    combo.set(next((k for k, v in harita.items() if v == secili_id), degerler[0]))
    return combo, harita


class SubeDialog(tk.Toplevel):
    def __init__(self, parent, firma_id: int, sube=None):
        super().__init__(parent)
        self.firma_id = int(firma_id)
        self.sube = sube
        self.result = None
        self.title("Şube Düzenle" if sube else "Yeni Şube")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.alanlar = {}
        for row, (label, key) in enumerate(
            (("Şube Kodu", "sube_kodu"), ("Şube Adı", "sube_adi"), ("Adres", "adres"), ("Telefon", "telefon"))
        ):
            ttk.Label(self, text=label).grid(row=row, column=0, padx=10, pady=5, sticky="w")
            widget = ttk.Entry(self, width=42)
            widget.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
            self.alanlar[key] = widget
            if sube:
                widget.insert(0, getattr(sube, key, None) or "")
        butonlar = ttk.Frame(self)
        butonlar.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")
        self.alanlar["sube_kodu"].focus_set()

    def kaydet(self):
        veriler = {key: widget.get().strip() for key, widget in self.alanlar.items()}
        try:
            self.result = (
                SubeService.guncelle(self.sube.id, self.firma_id, veriler)
                if self.sube
                else SubeService.ekle(self.firma_id, veriler)
            )
        except ValueError as exc:
            messagebox.showerror("Şube", str(exc), parent=self)
            return
        self.destroy()


class SubeYonetimDialog(tk.Toplevel):
    def __init__(self, parent, firma_id: int):
        super().__init__(parent)
        self.firma_id = int(firma_id)
        self.title("Şubeler")
        self.geometry("720x420")
        self.minsize(560, 320)
        self.transient(parent)
        self.grab_set()

        self.tablo = ttk.Treeview(
            self,
            columns=("kod", "ad", "merkez", "durum", "telefon"),
            show="headings",
            selectmode="browse",
        )
        for key, label, width in (
            ("kod", "Kod", 110),
            ("ad", "Şube Adı", 220),
            ("merkez", "Merkez", 90),
            ("durum", "Durum", 90),
            ("telefon", "Telefon", 140),
        ):
            self.tablo.heading(key, text=label)
            self.tablo.column(key, width=width, anchor="w")
        self.tablo.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(butonlar, text="Yeni Şube", command=self.yeni).pack(side="left")
        ttk.Button(butonlar, text="Düzenle", command=self.duzenle).pack(side="left", padx=6)
        ttk.Button(butonlar, text="Pasife Al", command=self.pasife_al).pack(side="left")
        ttk.Button(butonlar, text="Kapat", command=self.destroy).pack(side="right")
        self.yenile()

    def yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        SubeService.merkez(self.firma_id)
        for sube in SubeService.listele(self.firma_id):
            self.tablo.insert(
                "",
                "end",
                iid=str(sube.id),
                values=(sube.sube_kodu, sube.sube_adi, "Evet" if sube.merkez else "", "Aktif" if sube.aktif else "Pasif", sube.telefon or ""),
            )

    def _secili(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Şube", "Önce bir şube seçin.", parent=self)
            return None
        return SubeService.getir(int(secim[0]), self.firma_id)

    def yeni(self):
        dialog = SubeDialog(self, self.firma_id)
        self.wait_window(dialog)
        if dialog.result:
            self.yenile()

    def duzenle(self):
        sube = self._secili()
        if sube is None:
            return
        dialog = SubeDialog(self, self.firma_id, sube=sube)
        self.wait_window(dialog)
        if dialog.result:
            self.yenile()

    def pasife_al(self):
        sube = self._secili()
        if sube is None:
            return
        try:
            SubeService.pasife_al(sube.id, self.firma_id)
        except ValueError as exc:
            messagebox.showerror("Şube", str(exc), parent=self)
            return
        self.yenile()
