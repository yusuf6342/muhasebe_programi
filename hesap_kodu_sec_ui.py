"""Muhasebe hesap kodu seçimi — TDHP hesap planından önek ile arama."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class HesapKoduSecDialog(tk.Toplevel):
    """En az 3 hane önek ile hesap planı listesi; çift tık / Enter ile seç."""

    def __init__(self, parent, onek: str = "", baslik: str = "Hesap Planı — Seç"):
        super().__init__(parent)
        self.result = None
        self.title(baslik)
        self.geometry("560x420")
        self.minsize(480, 320)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Önek (en az 3 hane):").pack(side="left")
        self.arama = ttk.Entry(ust, width=18)
        self.arama.pack(side="left", padx=8)
        self.arama.insert(0, (onek or "").strip())
        self.arama.bind("<KeyRelease>", self._filtrele)
        self.arama.bind("<Return>", self._sec)
        self.arama.bind("<Down>", self._listeye_in)
        ttk.Button(ust, text="Listele", command=self._filtrele).pack(side="left", padx=4)
        ttk.Label(
            ust,
            text="TDHP hesap planı · kod ile başlar",
            foreground="#555",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(8, 0))

        orta = ttk.Frame(self, padding=(10, 0))
        orta.pack(fill="both", expand=True)
        orta.columnconfigure(0, weight=1)
        orta.rowconfigure(0, weight=1)
        self.tablo = ttk.Treeview(
            orta,
            columns=("kod", "ad", "seviye"),
            show="headings",
            selectmode="browse",
        )
        self.tablo.heading("kod", text="Hesap kodu")
        self.tablo.heading("ad", text="Hesap adı")
        self.tablo.heading("seviye", text="Sv")
        self.tablo.column("kod", width=140, anchor="w")
        self.tablo.column("ad", width=320, anchor="w")
        self.tablo.column("seviye", width=40, anchor="center")
        kaydir = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")
        self.tablo.bind("<Double-1>", self._sec)
        self.tablo.bind("<Return>", self._sec)

        self.bilgi = ttk.Label(self, text="", padding=(10, 4))
        self.bilgi.pack(anchor="w")

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Seç", width=12, command=self._sec).pack(side="right")

        self._sonuclar: list[dict] = []
        self._filtrele()
        self.after(40, lambda: (self.arama.focus_set(), self.arama.icursor("end")))

    def _filtrele(self, _event=None):
        from database.muhasebe_service import HesapPlanService

        onek = (self.arama.get() or "").strip()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        self._sonuclar = []
        if len("".join(c for c in onek if c.isalnum())) < 3 and len(onek) < 3:
            self.bilgi.configure(text="En az 3 hane yazın (ör. 120) — sağ tık veya Listele.")
            return
        try:
            self._sonuclar = HesapPlanService.kod_oneki_ile_listele(onek)
        except ValueError as hata:
            self.bilgi.configure(text=str(hata))
            return
        except Exception as hata:
            self.bilgi.configure(text=f"Liste alınamadı: {hata}")
            return
        for i, h in enumerate(self._sonuclar):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(h["hesap_kodu"], h["hesap_adi"], h.get("hesap_seviyesi") or ""),
            )
        if not self._sonuclar:
            self.bilgi.configure(text=f"«{onek}» ile başlayan hesap yok. Hesap planını kontrol edin.")
        else:
            self.bilgi.configure(text=f"{len(self._sonuclar)} hesap")
            ilk = self.tablo.get_children()
            if ilk:
                self.tablo.selection_set(ilk[0])
                self.tablo.focus(ilk[0])

    def _listeye_in(self, _event=None):
        cocuklar = self.tablo.get_children()
        if cocuklar:
            self.tablo.focus_set()
            self.tablo.selection_set(cocuklar[0])
            self.tablo.focus(cocuklar[0])
        return "break"

    def _sec(self, _event=None):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Listeden hesap seçin.", parent=self)
            return
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return
        if idx < 0 or idx >= len(self._sonuclar):
            return
        self.result = self._sonuclar[idx]["hesap_kodu"]
        self.destroy()


def muhasebe_hesap_entry_bagla(parent, giris: ttk.Entry) -> None:
    """Entry: sağ tık / F2 / 3. haneden sonra hesap planı seçimi."""

    def _onek():
        return (giris.get() or "").strip()

    def _ac(_event=None):
        onek = _onek()
        # Sağ tıkta 3 hane yoksa yine aç; kullanıcı diyalogda yazar
        dlg = HesapKoduSecDialog(parent, onek=onek)
        parent.wait_window(dlg)
        if dlg.result:
            giris.delete(0, "end")
            giris.insert(0, dlg.result)
            giris.icursor("end")
            giris.focus_set()
        return "break"

    def _tus(event=None):
        if event and getattr(event, "keysym", "") in (
            "Up", "Down", "Left", "Right", "Return", "Tab", "Escape",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "F2",
        ):
            return
        metin = _onek()
        rakam = "".join(c for c in metin if c.isdigit())
        # Tam 3. rakam yazıldığında otomatik aç (debounce)
        if len(rakam) < 3:
            after_id = getattr(giris, "_hesap_sec_after", None)
            if after_id:
                try:
                    parent.after_cancel(after_id)
                except tk.TclError:
                    pass
                giris._hesap_sec_after = None
            return
        # Yalnızca 3 hane civarında otomatik aç; uzun kod yazarken tekrar açma
        if len(rakam) > 3 or "." in metin:
            return
        after_id = getattr(giris, "_hesap_sec_after", None)
        if after_id:
            try:
                parent.after_cancel(after_id)
            except tk.TclError:
                pass

        def _gecikmeli():
            giris._hesap_sec_after = None
            if "".join(c for c in (giris.get() or "") if c.isdigit()) != rakam:
                return
            _ac()

        giris._hesap_sec_after = parent.after(350, _gecikmeli)

    giris.bind("<Button-3>", _ac)
    giris.bind("<F2>", _ac)
    giris.bind("<KeyRelease>", _tus)
