"""Banka altındaki fiziksel hesaplar — her satır ayrı hesap; IBAN/şube alt hesaptadır."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

from database.finans_service import FinansService

LABELS = {
    "MEVDUAT": "Mevduat",
    "KMH": "KMH",
    "POS": "POS",
    "KREDI_KARTI": "Kredi kartı",
    "KREDILER": "Kredi",
    "VADELI": "Vadeli",
}


def money(v):
    return (
        f"{Decimal(str(v or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        + " TL"
    )


class BankaAltHesapDetayDialog(tk.Toplevel):
    def __init__(self, parent, kart_id):
        super().__init__(parent)
        self.parent_dlg = parent
        self.title("Banka Hesapları")
        self.geometry("1250x740")
        self.minsize(1000, 600)
        self.transient(parent)
        self.kart = FinansService.banka_karti_getir(kart_id)
        if not self.kart:
            self.destroy()
            return
        self.title(f"Banka Hesapları — {self.kart.banka_adi}")
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"{self.kart.banka_adi} · Banka Hesapları",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Her satır ayrı bir hesaptır. IBAN / şube / hesap no hesap satırındadır.",
        ).pack(anchor="w", pady=8)
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        cols = ("kind", "name", "branch", "account_no", "iban", "balance")
        self.table = ttk.Treeview(box, columns=cols, show="headings", height=10)
        for key, label, width in (
            ("kind", "Tür", 100),
            ("name", "Hesap adı", 280),
            ("branch", "Şube", 120),
            ("account_no", "Hesap no", 130),
            ("iban", "IBAN", 220),
            ("balance", "Bakiye", 140),
        ):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, anchor="e" if key == "balance" else "w")
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.info = tk.StringVar()
        ttk.Label(frame, textvariable=self.info, wraplength=1180).pack(anchor="w", pady=8)
        ttk.Label(frame, text="Seçilen hesabın hareketleri", font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        low = ttk.Frame(frame)
        low.pack(fill="both", expand=True, pady=8)
        self.moves = ttk.Treeview(
            low, columns=("date", "kind", "number", "amount", "note"), show="headings", height=10
        )
        for key, label, width in (
            ("date", "Tarih", 100),
            ("kind", "İşlem", 180),
            ("number", "Belge no", 190),
            ("amount", "Tutar", 130),
            ("note", "Açıklama", 500),
        ):
            self.moves.heading(key, text=label)
            self.moves.column(key, width=width, anchor="e" if key == "amount" else "w")
        self.moves.pack(side="left", fill="both", expand=True)
        scroll2 = ttk.Scrollbar(low, orient="vertical", command=self.moves.yview)
        scroll2.pack(side="right", fill="y")
        self.moves.configure(yscrollcommand=scroll2.set)
        self.table.bind("<<TreeviewSelect>>", self.show_movements)
        self.table.bind("<Double-1>", lambda _e: self._duzenle())
        alt = ttk.Frame(frame)
        alt.pack(fill="x")
        ttk.Button(alt, text="Düzenle", command=self._duzenle).pack(side="left")
        ttk.Button(alt, text="Yenile", command=self._yenile).pack(side="left", padx=8)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self._yenile()

    def _yenile(self):
        self.kart = FinansService.banka_karti_getir(self.kart.id)
        self.accounts = {h.id: h for h in (self.kart.alt_hesaplar or [])}
        for item in self.table.get_children():
            self.table.delete(item)
        for h in sorted(self.accounts.values(), key=lambda a: ((a.alt_hesap_turu or ""), a.hesap_adi)):
            value = FinansService.varlik_bakiyesi(FinansService.bakiye(h), hesap=h)
            self.table.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    LABELS.get(h.alt_hesap_turu, h.alt_hesap_turu or ""),
                    h.hesap_adi,
                    h.sube or "—",
                    getattr(h, "hesap_no", None) or "—",
                    h.iban or "—",
                    money(value),
                ),
            )
        self.info.set(f"{len(self.accounts)} ayrı hesap")
        if self.accounts:
            first = self.table.get_children()[0]
            self.table.selection_set(first)
            self.show_movements()

    def show_movements(self, event=None):
        selected = self.table.selection()
        if not selected:
            return
        h = self.accounts[int(selected[0])]
        for item in self.moves.get_children():
            self.moves.delete(item)
        for m in sorted(h.hareketler or [], key=lambda x: (str(x.tarih), x.id), reverse=True):
            self.moves.insert(
                "",
                "end",
                values=(
                    m.tarih.strftime("%d.%m.%Y") if m.tarih else "",
                    m.hareket_turu,
                    m.belge_no,
                    money(m.tutar),
                    m.aciklama or "",
                ),
            )
        self.info.set(
            f"{h.hesap_adi} · Açılış: {money(h.acilis_bakiyesi)} · "
            f"Hareket: {len(h.hareketler or [])}"
        )

    def _duzenle(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("Hesap", "Düzenlemek için bir hesap seçin.", parent=self)
            return
        from finans_ui import AltHesapDuzenleDialog

        dialog = AltHesapDuzenleDialog(self, int(selected[0]))
        self.wait_window(dialog)
        if dialog.result:
            self._yenile()
            if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
                self.parent_dlg.bakiyeleri_yenile()
            if hasattr(self.parent_dlg, "_hesaplari_yenile"):
                self.parent_dlg._hesaplari_yenile()
