"""Hızlı Satış Aşama 6 — bekleyen sepet listesi / geri çağır / iptal."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable


SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
KIRMIZI = "#C62828"
TURUNCU = "#EF6C00"
BEYAZ = "#FFFFFF"


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_metin(dt) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(dt)


class HizliSatisBekleyenDialog(tk.Toplevel):
    """Bekleyen sepetleri listeler; geri çağır veya iptal eder."""

    def __init__(
        self,
        parent,
        *,
        on_cagir: Callable[[dict[str, Any]], None] | None = None,
        on_onay_oncesi: Callable[[], bool] | None = None,
    ):
        super().__init__(parent)
        self.title("BEKLEYEN SEPETLER — Geri Çağır")
        self.configure(bg=KOYU_GRI)
        self.geometry("820x480")
        self.minsize(700, 400)
        self.transient(parent)
        self.grab_set()

        self.on_cagir = on_cagir
        self.on_onay_oncesi = on_onay_oncesi
        self.result: dict[str, Any] | None = None
        self._kayitlar: list[dict[str, Any]] = []

        self._kur()
        self._yenile()
        self.bind("<Escape>", lambda _e: self._kapat())
        self.bind("<Return>", lambda _e: self._cagir())
        self.bind("<F5>", lambda _e: self._yenile())
        self.after(80, self._agac_odak)

        try:
            self.wait_visibility()
            self.focus_force()
        except tk.TclError:
            pass

    def _kur(self) -> None:
        kok = tk.Frame(self, bg=KOYU_GRI, padx=10, pady=10)
        kok.pack(fill="both", expand=True)
        kok.rowconfigure(1, weight=1)
        kok.columnconfigure(0, weight=1)

        tk.Label(
            kok,
            text="Bekleyen sepetler (stok rezervasyonu yok)",
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        orta = tk.Frame(kok, bg=ACIK_GRI)
        orta.grid(row=1, column=0, sticky="nsew")
        orta.rowconfigure(0, weight=1)
        orta.columnconfigure(0, weight=1)

        sutunlar = ("id", "saat", "musteri", "satir", "toplam", "etiket", "kullanici")
        self.agac = ttk.Treeview(
            orta,
            columns=sutunlar,
            show="headings",
            selectmode="browse",
        )
        self.agac.heading("id", text="#")
        self.agac.heading("saat", text="Saat")
        self.agac.heading("musteri", text="Müşteri")
        self.agac.heading("satir", text="Satır")
        self.agac.heading("toplam", text="Toplam")
        self.agac.heading("etiket", text="Etiket / Not")
        self.agac.heading("kullanici", text="Kullanıcı")
        self.agac.column("id", width=50, anchor="e")
        self.agac.column("saat", width=120, anchor="center")
        self.agac.column("musteri", width=180, anchor="w")
        self.agac.column("satir", width=50, anchor="center")
        self.agac.column("toplam", width=100, anchor="e")
        self.agac.column("etiket", width=160, anchor="w")
        self.agac.column("kullanici", width=100, anchor="w")
        self.agac.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(orta, orient="vertical", command=self.agac.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.agac.configure(yscrollcommand=sb.set)
        self.agac.bind("<Double-1>", lambda _e: self._cagir())

        alt = tk.Frame(kok, bg=KOYU_GRI, pady=8)
        alt.grid(row=2, column=0, sticky="ew")
        for i in range(4):
            alt.columnconfigure(i, weight=1)

        tk.Button(
            alt,
            text="Yenile (F5)",
            bg=KOYU_GRI,
            fg=SARİ,
            activebackground="#1a1d20",
            activeforeground=SARİ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            command=self._yenile,
        ).grid(row=0, column=0, sticky="ew", padx=3)

        tk.Button(
            alt,
            text="İptal Et",
            bg=KIRMIZI,
            fg=BEYAZ,
            activebackground="#8E0000",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            command=self._iptal_et,
        ).grid(row=0, column=1, sticky="ew", padx=3)

        tk.Button(
            alt,
            text="Kapat",
            bg="#555555",
            fg=BEYAZ,
            activebackground="#333333",
            activeforeground=BEYAZ,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            command=self._kapat,
        ).grid(row=0, column=2, sticky="ew", padx=3)

        tk.Button(
            alt,
            text="GERİ ÇAĞIR (Enter)",
            bg=TURUNCU,
            fg=BEYAZ,
            activebackground="#E65100",
            activeforeground=BEYAZ,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=10,
            pady=10,
            command=self._cagir,
        ).grid(row=0, column=3, sticky="ew", padx=3)

        self.durum_lbl = tk.Label(
            kok,
            text="",
            bg=KOYU_GRI,
            fg="#CCCCCC",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.durum_lbl.grid(row=3, column=0, sticky="ew", pady=(4, 0))

    def _agac_odak(self) -> None:
        try:
            self.agac.focus_set()
            cocuklar = self.agac.get_children()
            if cocuklar:
                self.agac.selection_set(cocuklar[0])
                self.agac.focus(cocuklar[0])
        except tk.TclError:
            pass

    def _yenile(self) -> None:
        from database.hizli_satis_service import HizliSatisService

        for i in self.agac.get_children():
            self.agac.delete(i)
        try:
            self._kayitlar = HizliSatisService.list_holds()
        except Exception as hata:
            self._kayitlar = []
            messagebox.showerror("Bekleyenler", str(hata), parent=self)
            self.durum_lbl.configure(text="Liste alınamadı.")
            return

        for k in self._kayitlar:
            musteri = k.get("cari_unvan") or k.get("cari_kodu") or "—"
            etiket = (k.get("etiket") or k.get("not") or "") or ""
            self.agac.insert(
                "",
                "end",
                iid=str(k["id"]),
                values=(
                    k["id"],
                    _tarih_metin(k.get("olusturma_tarihi")),
                    musteri,
                    k.get("satir_sayisi") or 0,
                    _para(k.get("genel_toplam")),
                    etiket,
                    k.get("kullanici_adi") or "",
                ),
            )
        n = len(self._kayitlar)
        self.durum_lbl.configure(
            text=f"{n} bekleyen sepet" if n else "Bekleyen sepet yok."
        )
        self._agac_odak()

    def _secili_id(self) -> int | None:
        sec = self.agac.selection()
        if not sec:
            return None
        try:
            return int(sec[0])
        except (TypeError, ValueError):
            return None

    def _cagir(self) -> None:
        from database.hizli_satis_service import HizliSatisService

        hid = self._secili_id()
        if hid is None:
            messagebox.showwarning("Seçim", "Geri çağırılacak sepeti seçin.", parent=self)
            return
        # Sepet doluysa önce onay — hold CAGIRILDI olmadan önce
        if self.on_onay_oncesi is not None:
            try:
                if not self.on_onay_oncesi():
                    return
            except Exception as hata:
                messagebox.showerror("Geri çağır", str(hata), parent=self)
                return
        try:
            veri = HizliSatisService.load_hold(hid, cagirildi_isaretle=True)
        except Exception as hata:
            messagebox.showerror("Geri çağır", str(hata), parent=self)
            self._yenile()
            return

        self.result = veri
        if self.on_cagir is not None:
            try:
                self.on_cagir(veri)
            except Exception as hata:
                messagebox.showerror("Geri çağır", str(hata), parent=self)
                return
        self.destroy()

    def _iptal_et(self) -> None:
        from database.hizli_satis_service import HizliSatisService

        hid = self._secili_id()
        if hid is None:
            messagebox.showwarning("Seçim", "İptal edilecek sepeti seçin.", parent=self)
            return
        if not messagebox.askyesno(
            "İptal",
            f"#{hid} numaralı bekleyen sepet iptal edilsin mi?\n(Stok etkilenmez.)",
            parent=self,
        ):
            return
        try:
            HizliSatisService.delete_hold(hid)
        except Exception as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return
        self._yenile()

    def _kapat(self) -> None:
        self.destroy()
