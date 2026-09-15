"""Hızlı Satış gün sonu özeti — onaylı POS faturalarından (Aşama 8)."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any

from database.hizli_satis_service import HizliSatisService

SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
BEYAZ = "#FFFFFF"
TURUNCU = "#EF6C00"


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_metin(d: date | None) -> str:
    if d is None:
        return ""
    return d.strftime("%d.%m.%Y")


class HizliSatisGunSonuDialog(tk.Toplevel):
    """Günlük satış / tahsilat / iade-iptal özeti (soft-delete bilinçli)."""

    def __init__(self, parent, *, tarih: date | None = None):
        super().__init__(parent)
        self.tarih = tarih or date.today()
        self.title("Hızlı Satış — Gün Sonu")
        self.configure(bg=KOYU_GRI)
        self.geometry("520x560")
        self.minsize(460, 480)
        self.transient(parent)
        self.grab_set()

        ust = tk.Frame(self, bg=KOYU_GRI, padx=12, pady=10)
        ust.pack(fill="x")
        tk.Label(
            ust,
            text="GÜN SONU ÖZETİ",
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        tk.Label(
            ust,
            text=_tarih_metin(self.tarih),
            bg=KOYU_GRI,
            fg=BEYAZ,
            font=("Segoe UI", 11),
        ).pack(side="right")

        govde = tk.Frame(self, bg=ACIK_GRI, padx=14, pady=12)
        govde.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.ozet_frame = tk.Frame(govde, bg=ACIK_GRI)
        self.ozet_frame.pack(fill="both", expand=True)

        alt = tk.Frame(self, bg=KOYU_GRI, padx=12, pady=10)
        alt.pack(fill="x", side="bottom")
        tk.Button(
            alt,
            text="Kapat",
            command=self.destroy,
            bg="#757575",
            fg=BEYAZ,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="right")
        tk.Button(
            alt,
            text="Yenile",
            command=self._yenile,
            bg=TURUNCU,
            fg=BEYAZ,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self.destroy())
        self._yenile()

    def _satir(self, parent, etiket: str, deger: str, *, vurgu: bool = False) -> None:
        f = tk.Frame(parent, bg=ACIK_GRI)
        f.pack(fill="x", pady=3)
        tk.Label(
            f,
            text=etiket,
            bg=ACIK_GRI,
            fg="#555555",
            font=("Segoe UI", 10, "bold" if vurgu else "normal"),
            anchor="w",
        ).pack(side="left")
        tk.Label(
            f,
            text=deger,
            bg=ACIK_GRI,
            fg=KOYU_GRI if not vurgu else YESIL,
            font=("Segoe UI", 11, "bold" if vurgu else "normal"),
            anchor="e",
        ).pack(side="right")

    def _yenile(self) -> None:
        for w in self.ozet_frame.winfo_children():
            w.destroy()
        try:
            ozet = HizliSatisService.gun_sonu_ozeti(self.tarih)
        except Exception as hata:
            messagebox.showerror("Gün sonu", str(hata), parent=self)
            return

        self._satir(self.ozet_frame, "Satış adedi (onaylı)", str(ozet.get("satis_adedi") or 0))
        self._satir(
            self.ozet_frame,
            "Brüt satış toplamı",
            _para(ozet.get("satis_toplami")),
            vurgu=True,
        )
        self._satir(self.ozet_frame, "İskonto toplamı", _para(ozet.get("iskonto_toplami")))
        self._satir(self.ozet_frame, "KDV toplamı", _para(ozet.get("kdv_toplami")))
        self._satir(self.ozet_frame, "Tahsilat toplamı", _para(ozet.get("tahsilat_toplami")))
        self._satir(self.ozet_frame, "Açık hesap kalan", _para(ozet.get("acik_hesap")))

        ttk.Separator(self.ozet_frame, orient="horizontal").pack(fill="x", pady=10)
        tk.Label(
            self.ozet_frame,
            text="Ödeme türleri",
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        odeme: dict[str, Any] = ozet.get("odeme_turleri") or {}
        for etiket, anahtar in (
            ("Nakit", "nakit"),
            ("Kredi kartı / POS", "kredi_karti"),
            ("Havale / EFT", "havale"),
            ("Diğer tahsilat", "diger"),
        ):
            self._satir(self.ozet_frame, etiket, _para(odeme.get(anahtar)))

        ttk.Separator(self.ozet_frame, orient="horizontal").pack(fill="x", pady=10)
        self._satir(self.ozet_frame, "İptal adedi", str(ozet.get("iptal_adedi") or 0))
        self._satir(self.ozet_frame, "İptal tutarı", _para(ozet.get("iptal_toplami")))
        self._satir(self.ozet_frame, "İade adedi", str(ozet.get("iade_adedi") or 0))
        self._satir(self.ozet_frame, "İade tutarı", _para(ozet.get("iade_toplami")))

        ort = ozet.get("ortalama_sepet")
        if ort is not None:
            self._satir(self.ozet_frame, "Ortalama sepet", _para(ort))

        tk.Label(
            self.ozet_frame,
            text="Kaynak: onaylı SatisFaturasi (Hızlı Satış etiketi). Soft-silinenler hariç.",
            bg=ACIK_GRI,
            fg="#888888",
            font=("Segoe UI", 8),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))
