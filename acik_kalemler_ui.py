"""Cari kart "Açık Kalemler" görünümü — Açık Borçlar raporu ile aynı kaynak (salt okunur)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

from database.kapatma_izleme_service import acik_kalemler_listesi, tutarsizlik_raporu
from kapatma_detay_ui import _para, _tarih, kapatma_detayi_ac


class CariAcikKalemlerDialog(tk.Toplevel):
    KOLONLAR = (
        ("tur", "Evrak Türü", 150, "w"),
        ("no", "Evrak No", 120, "w"),
        ("tarih", "Evrak Tarihi", 85, "center"),
        ("vade", "Vade", 85, "center"),
        ("gecikme", "Gecikme (gün)", 90, "e"),
        ("ilk", "Asıl Tutar", 105, "e"),
        ("kapanan", "Kapatılan", 105, "e"),
        ("kalan", "Kalan", 105, "e"),
        ("durum", "Ödeme Durumu", 105, "center"),
        ("pb", "Döviz", 50, "center"),
    )

    def __init__(self, parent, cari_id: int, cari_adi: str = ""):
        super().__init__(parent)
        self.cari_id = int(cari_id)
        self.title(f"Açık Kalemler — {cari_adi}")
        self.transient(parent)
        self.geometry("1020x480")
        self.minsize(640, 320)
        self._satirlar: dict[str, dict] = {}

        ust = ttk.Frame(self, padding=(10, 8))
        ust.pack(fill="x")
        self.vadesi_gecen = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ust, text="Yalnız vadesi geçenler", variable=self.vadesi_gecen, command=self.yenile
        ).pack(side="left")
        ttk.Button(ust, text="Yenile", command=self.yenile).pack(side="left", padx=6)
        ttk.Button(ust, text="Tutarlılık Kontrolü", command=self.tutarlilik).pack(side="left")
        self.ozet_lbl = ttk.Label(ust, text="", font=("Segoe UI", 10, "bold"))
        self.ozet_lbl.pack(side="right")

        orta = ttk.Frame(self, padding=(10, 0))
        orta.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            orta, columns=[k for k, *_ in self.KOLONLAR], show="headings", selectmode="browse"
        )
        for kolon, baslik, genislik, hiza in self.KOLONLAR:
            self.tablo.heading(kolon, text=baslik, anchor=hiza)
            self.tablo.column(kolon, width=genislik, minwidth=50, anchor=hiza, stretch=(hiza == "w"))
        dikey = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.tablo.tag_configure("gecikmis", foreground="#C62828")
        self.tablo.tag_configure("avans", foreground="#2E7D32")
        self.tablo.bind("<Double-1>", lambda _e: self.detay())

        alt = ttk.Frame(self, padding=(10, 8))
        alt.pack(fill="x")
        ttk.Label(
            alt,
            text="Cari bakiye ile evrak bazlı açık tutar ayrıdır; burada yalnız açık evrak kalemleri listelenir.",
            foreground="#666666",
        ).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kapatma Detayı", command=self.detay).pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yenile()

    def yenile(self):
        from database.acik_kalem_service import odeme_durumu

        self.tablo.delete(*self.tablo.get_children())
        self._satirlar.clear()
        try:
            satirlar = acik_kalemler_listesi(self.cari_id, sadece_vadesi_gecen=self.vadesi_gecen.get())
        except Exception as hata:
            messagebox.showerror("Açık Kalemler", str(hata), parent=self)
            return
        acik = Decimal("0")
        avans = Decimal("0")
        gecikmis = Decimal("0")
        for i, s in enumerate(satirlar):
            iid = str(i)
            self._satirlar[iid] = s
            if s["acik"] < 0:
                etiket = "avans"
                avans += -s["acik"]
            else:
                acik += s["acik"]
                etiket = "gecikmis" if s["gecikme_gunu"] > 0 else ""
                if s["gecikme_gunu"] > 0:
                    gecikmis += s["acik"]
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                tags=(etiket,) if etiket else (),
                values=(
                    s["evrak_turu"],
                    s["evrak_no"],
                    _tarih(s["evrak_tarihi"]),
                    _tarih(s["vade"]),
                    s["gecikme_gunu"] or "",
                    _para(s["orijinal"]) if s["orijinal"] > 0 else "",
                    _para(s["kapanan"]) if s["orijinal"] > 0 else "",
                    _para(s["acik"]),
                    odeme_durumu(s["orijinal"], s["kapanan"]) if s["orijinal"] > 0 else "Avans",
                    s["para_birimi"],
                ),
            )
        self.ozet_lbl.configure(
            text=f"Açık: {_para(acik)}   Vadesi geçen: {_para(gecikmis)}   Avans: {_para(avans)}"
        )

    def detay(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Kapatma Detayı", "Bir satır seçin.", parent=self)
            return
        s = self._satirlar.get(secim[0]) or {}
        kapatma_detayi_ac(self, s.get("evrak_no") or "", self.cari_id)
        self.yenile()

    def tutarlilik(self):
        try:
            sorunlar = tutarsizlik_raporu(self.cari_id)
        except Exception as hata:
            messagebox.showerror("Tutarlılık", str(hata), parent=self)
            return
        if not sorunlar:
            messagebox.showinfo(
                "Tutarlılık", "Tüm kalemlerde kapatma payları + kalan = evrak tutarı.", parent=self
            )
            return
        satirlar = "\n".join(
            f"{s['belge_no']}: pay {_para(s['aktif_pay'])} + kalan {_para(s['kalan'])} "
            f"≠ tutar {_para(s['esas'])}"
            for s in sorunlar[:30]
        )
        messagebox.showwarning(
            "Tutarlılık",
            f"{len(sorunlar)} kalemde tutarsızlık var (otomatik düzeltilmedi, tanı günlüğüne yazıldı):\n\n"
            f"{satirlar}",
            parent=self,
        )
