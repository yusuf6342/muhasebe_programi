"""Satır İskontoları — satış/alış ortak üçlü iskonto modal penceresi."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.iskonto_hesap_service import (
    iskonto_goster_metin,
    iskonto_oran_metin,
    iskonto_oranlarini_dogrula,
    satir_iskonto_hesapla,
)
from database.satis_siparisi_service import decimal


def _para(tutar) -> str:
    d = Decimal(str(tutar or 0)).quantize(Decimal("0.01"))
    s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} TL"


class SatirIskontolariDialog(tk.Toplevel):
    """1./2./3. iskonto girişi; sonuç kartı; Uygula / Temizle / Vazgeç."""

    def __init__(
        self,
        parent,
        *,
        belge_turu: str = "Satış",
        satir: dict[str, Any] | None = None,
        fiyat_alani: str = "birim_satis_fiyati",
        on_uygula: Callable[[dict[str, Any]], None] | None = None,
        kdv_dahil: bool = False,
        satir_kimlik: Any = None,
    ):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()  # modal — seçim değişince eski satıra yazılmaz
        self.resizing = False
        self._satir = dict(satir or {})
        self._satir_kimlik = satir_kimlik
        self._fiyat_alani = fiyat_alani
        self._on_uygula = on_uygula
        self._kdv_dahil = bool(kdv_dahil)
        self._uygulaniyor = False

        tur = (belge_turu or "Satış").strip()
        self.title(f"Satır İskontoları — {tur} Faturası")
        self.geometry("540x540")
        self.minsize(500, 480)
        self.configure(bg="#F5F7FA")

        kod = (self._satir.get("urun_kodu") or "").strip()
        ad = (self._satir.get("urun_adi") or "").strip()
        miktar = self._satir.get("miktar") or 0
        birim = self._satir.get("birim") or "Adet"
        try:
            fiyat = decimal(
                self._satir.get(fiyat_alani)
                or self._satir.get("birim_fiyat")
                or self._satir.get("birim_alis_fiyati")
                or 0,
                "Fiyat",
                Decimal("0"),
            )
        except ValueError:
            fiyat = Decimal("0")
        try:
            mik = decimal(miktar or 0, "Miktar", Decimal("0"))
        except ValueError:
            mik = Decimal("0")
        brut_satir = mik * fiyat

        ust = ttk.LabelFrame(self, text="Satır bilgisi", padding=10)
        ust.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(ust, text=f"Belge: {tur} Faturası").grid(row=0, column=0, sticky="w")
        ttk.Label(ust, text=f"Ürün: {kod} — {ad}", wraplength=480).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(
            ust,
            text=(
                f"Miktar: {mik} {birim}   |   Brüt birim: {_para(fiyat)}   |   "
                f"Brüt satır: {_para(brut_satir)}"
            ),
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        form = ttk.LabelFrame(self, text="İskonto oranları (%)", padding=12)
        form.pack(fill="x", padx=12, pady=6)
        self._oran_vars: dict[str, tk.StringVar] = {}
        self._oran_entries: dict[str, ttk.Entry] = {}
        for i, (etiket, anahtar) in enumerate(
            (
                ("1. İskonto %", "iskonto_orani"),
                ("2. İskonto %", "iskonto_orani_2"),
                ("3. İskonto %", "iskonto_orani_3"),
            )
        ):
            ttk.Label(form, text=etiket, font=("Segoe UI", 11)).grid(
                row=i, column=0, sticky="w", pady=6, padx=(0, 12)
            )
            # Ham oran — birleşik metinden parse YOK; 10→1 rstrip bug'ı yok
            var = tk.StringVar(value=iskonto_oran_metin(self._satir.get(anahtar) or 0))
            ent = ttk.Entry(
                form,
                textvariable=var,
                width=14,
                font=("Segoe UI", 12),
                justify="right",
            )
            ent.grid(row=i, column=1, sticky="w", pady=6)
            var.trace_add("write", lambda *_a: self._sonuc_yenile())
            self._oran_vars[anahtar] = var
            self._oran_entries[anahtar] = ent
            if i == 0:
                self._ilk_entry = ent

        self._sonuc_frame = ttk.LabelFrame(self, text="Hesaplanan sonuç", padding=12)
        self._sonuc_frame.pack(fill="both", expand=True, padx=12, pady=6)
        self._sonuc_lbl = ttk.Label(
            self._sonuc_frame, text="", justify="left", font=("Segoe UI", 10)
        )
        self._sonuc_lbl.pack(anchor="w")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        self._btn_uygula = tk.Button(
            alt,
            text="Uygula",
            command=self._uygula,
            bg="#1A237E",
            fg="white",
            activebackground="#0D47A1",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=6,
            font=("Segoe UI", 10, "bold"),
        )
        self._btn_uygula.pack(side="left", padx=(0, 8))
        self._btn_temizle = tk.Button(
            alt,
            text="İskontoları Temizle",
            command=self._temizle,
            bg="#FFF8E1",
            fg="#5D4037",
            activebackground="#FFECB3",
            relief="flat",
            padx=12,
            pady=6,
            font=("Segoe UI", 10),
        )
        self._btn_temizle.pack(side="left", padx=(0, 8))
        self._btn_vazgec = tk.Button(
            alt,
            text="Vazgeç",
            command=self.destroy,
            relief="groove",
            padx=12,
            pady=6,
            font=("Segoe UI", 10),
        )
        self._btn_vazgec.pack(side="right")

        self.bind("<Return>", lambda _e: self._uygula())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._sonuc_yenile()
        self.after(50, lambda: self._ilk_entry.focus_set())
        self.after(60, lambda: self._ilk_entry.selection_range(0, "end"))

    def _oranlar(self) -> tuple[Any, Any, Any]:
        return (
            self._oran_vars["iskonto_orani"].get(),
            self._oran_vars["iskonto_orani_2"].get(),
            self._oran_vars["iskonto_orani_3"].get(),
        )

    def _brut_fiyat(self) -> Decimal:
        try:
            return decimal(
                self._satir.get(self._fiyat_alani)
                or self._satir.get("birim_fiyat")
                or self._satir.get("birim_alis_fiyati")
                or 0,
                "Fiyat",
                Decimal("0"),
            )
        except ValueError:
            return Decimal("0")

    def _sonuc_yenile(self):
        try:
            h = satir_iskonto_hesapla(
                miktar=self._satir.get("miktar") or 0,
                brut_birim_fiyat=self._brut_fiyat(),
                iskonto1=self._oran_vars["iskonto_orani"].get() or 0,
                iskonto2=self._oran_vars["iskonto_orani_2"].get() or 0,
                iskonto3=self._oran_vars["iskonto_orani_3"].get() or 0,
                kdv_orani=self._satir.get("kdv_orani") or 0,
                kdv_dahil=self._kdv_dahil,
            )
            metin = (
                f"Etkili iskonto: %{h['etkili_iskonto_orani']}\n"
                f"Toplam iskonto tutarı: {_para(h['iskonto_tutari'])}\n"
                f"İskonto sonrası birim fiyat: {_para(h['iskonto_sonrasi_birim_fiyat'])}\n"
                f"KDV tutarı: {_para(h['kdv_tutari'])}\n"
                f"KDV dahil net birim fiyat: {_para(h['net_birim_fiyat'])}\n"
                f"Net satır tutarı: {_para(h['net_tutar'])}"
            )
        except ValueError as hata:
            metin = str(hata)
        self._sonuc_lbl.configure(text=metin)

    def _pasif_set(self, pasif: bool):
        durum = "disabled" if pasif else "normal"
        for b in (self._btn_uygula, self._btn_temizle, self._btn_vazgec):
            try:
                b.configure(state=durum)
            except tk.TclError:
                pass

    def _temizle(self):
        for var in self._oran_vars.values():
            var.set("0")
        self._sonuc_yenile()
        self._ilk_entry.focus_set()

    def _uygula(self):
        if self._uygulaniyor:
            return
        try:
            i1, i2, i3 = iskonto_oranlarini_dogrula(*self._oranlar())
        except ValueError as hata:
            messagebox.showerror("İskonto", str(hata), parent=self)
            return
        self._uygulaniyor = True
        self._pasif_set(True)
        try:
            sonuc = {
                "iskonto_orani": str(i1),
                "iskonto_orani_2": str(i2),
                "iskonto_orani_3": str(i3),
            }
            if self._on_uygula:
                self._on_uygula(sonuc)
            self.destroy()
        finally:
            self._uygulaniyor = False


def satir_iskontolari_ac(
    parent,
    *,
    belge_turu: str,
    satir: dict[str, Any],
    fiyat_alani: str,
    on_uygula: Callable[[dict[str, Any]], None],
    kdv_dahil: bool = False,
    satir_kimlik: Any = None,
) -> SatirIskontolariDialog:
    return SatirIskontolariDialog(
        parent,
        belge_turu=belge_turu,
        satir=satir,
        fiyat_alani=fiyat_alani,
        on_uygula=on_uygula,
        kdv_dahil=kdv_dahil,
        satir_kimlik=satir_kimlik,
    )


def iskonto_hucre_metni(satir: dict[str, Any]) -> str:
    return iskonto_goster_metin(
        satir.get("iskonto_orani") or 0,
        satir.get("iskonto_orani_2") or 0,
        satir.get("iskonto_orani_3") or 0,
        bos_goster="",
    )
