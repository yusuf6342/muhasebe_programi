"""Kısmi sipariş/irsaliye → belge miktar seçim diyaloğu."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable


def _parse_miktar(metin: str) -> Decimal:
    t = (metin or "").strip().replace(" ", "")
    if not t:
        return Decimal("0")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geçersiz miktar.") from exc


def _fmt(deger: object) -> str:
    try:
        d = Decimal(str(deger))
    except Exception:
        return str(deger or "0")
    if d == d.to_integral_value():
        return f"{d:.0f}"
    return f"{d.normalize()}"


class KismiBelgeSecimDialog(tk.Toplevel):
    """Satır bazında bu belgeye alınacak miktarı seçtirir.

    result: seçim satırları listesi (bu_belge_miktar güncellenmiş) veya None (iptal).
    """

    def __init__(
        self,
        parent,
        *,
        baslik: str,
        aciklama: str,
        satirlar: list[dict[str, Any]],
        onceki_baslik: str = "Daha önce",
        kalan_baslik: str = "Kalan",
        bu_belge_baslik: str = "Bu belge",
        siparis_baslik: str = "Sipariş / İrsaliye",
    ):
        super().__init__(parent)
        self.result: list[dict[str, Any]] | None = None
        self._satirlar = [dict(s) for s in satirlar]
        self.title(baslik)
        self.transient(parent)
        self.grab_set()
        self.geometry("920x420")
        self.minsize(760, 320)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text=baslik, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(ust, text=aciklama, wraplength=860).pack(anchor="w", pady=(4, 0))

        orta = ttk.Frame(self, padding=(10, 0))
        orta.pack(fill="both", expand=True)
        kolonlar = ("kod", "ad", "birim", "siparis", "onceki", "kalan", "bu")
        self.tablo = ttk.Treeview(orta, columns=kolonlar, show="headings", height=12)
        basliklar = {
            "kod": "Ürün Kodu",
            "ad": "Ürün Adı",
            "birim": "Birim",
            "siparis": siparis_baslik,
            "onceki": onceki_baslik,
            "kalan": kalan_baslik,
            "bu": bu_belge_baslik,
        }
        gen = {"kod": 100, "ad": 220, "birim": 60, "siparis": 90, "onceki": 90, "kalan": 90, "bu": 90}
        for k in kolonlar:
            self.tablo.heading(k, text=basliklar[k])
            self.tablo.column(k, width=gen[k], anchor="center" if k != "ad" else "w")
        dikey = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")

        self._miktar_editor: ttk.Entry | None = None
        self.tablo.bind("<Double-1>", self._miktar_duzenle)
        self.tablo.bind("<Return>", self._miktar_duzenle)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Label(
            alt,
            text="Çift tık / Enter: bu belge miktarını düzenle. 0 = satırı dışarıda bırak.",
        ).pack(side="left")
        ttk.Button(alt, text="Tüm kalanı seç", command=self._tum_kalan).pack(side="right", padx=4)
        ttk.Button(alt, text="İptal", command=self._iptal).pack(side="right", padx=4)
        ttk.Button(alt, text="Devam", command=self._onayla).pack(side="right", padx=4)

        self._yenile()
        self.protocol("WM_DELETE_WINDOW", self._iptal)
        try:
            self.focus_set()
        except tk.TclError:
            pass

    def _yenile(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        for idx, s in enumerate(self._satirlar):
            self.tablo.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    s.get("urun_kodu", ""),
                    s.get("urun_adi", ""),
                    s.get("birim", ""),
                    _fmt(s.get("siparis_miktar", 0)),
                    _fmt(s.get("onceki_miktar", 0)),
                    _fmt(s.get("kalan_miktar", 0)),
                    _fmt(s.get("bu_belge_miktar", 0)),
                ),
            )

    def _tum_kalan(self):
        for s in self._satirlar:
            s["bu_belge_miktar"] = s.get("kalan_miktar") or Decimal("0")
        self._yenile()

    def _miktar_duzenle(self, event=None):
        if self._miktar_editor is not None:
            return
        secim = self.tablo.selection()
        if not secim:
            return
        iid = secim[0]
        bbox = self.tablo.bbox(iid, "bu")
        if not bbox:
            return
        x, y, w, h = bbox
        idx = int(iid)
        mevcut = _fmt(self._satirlar[idx].get("bu_belge_miktar", 0))
        editor = ttk.Entry(self.tablo)
        editor.insert(0, mevcut)
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=w, height=h)
        self._miktar_editor = editor

        def bitir(_e=None):
            if self._miktar_editor is None:
                return
            try:
                m = _parse_miktar(editor.get())
                kalan = Decimal(str(self._satirlar[idx].get("kalan_miktar") or 0))
                if m < 0:
                    raise ValueError("Miktar negatif olamaz.")
                if m > kalan:
                    raise ValueError(f"Miktar kalanı ({_fmt(kalan)}) aşamaz.")
                self._satirlar[idx]["bu_belge_miktar"] = m
            except ValueError as hata:
                messagebox.showerror("Miktar", str(hata), parent=self)
            editor.destroy()
            self._miktar_editor = None
            self._yenile()

        editor.bind("<Return>", bitir)
        editor.bind("<FocusOut>", bitir)
        editor.bind("<Escape>", lambda _e: (editor.destroy(), setattr(self, "_miktar_editor", None)))
        editor.focus_set()

    def _iptal(self):
        self.result = None
        self.destroy()

    def _onayla(self):
        if self._miktar_editor is not None:
            try:
                self._miktar_editor.event_generate("<FocusOut>")
            except tk.TclError:
                pass
        try:
            from database.kalan_belge_service import miktar_kalani_dogrula

            secilen = 0
            for s in self._satirlar:
                m = miktar_kalani_dogrula(
                    s.get("bu_belge_miktar", 0),
                    s.get("kalan_miktar", 0),
                    sifir_izinli=True,
                )
                s["bu_belge_miktar"] = m
                if m > 0:
                    secilen += 1
            if secilen == 0:
                raise ValueError("En az bir satırda sıfırdan büyük miktar girin.")
        except ValueError as hata:
            messagebox.showerror("Seçim", str(hata), parent=self)
            return
        self.result = self._satirlar
        self.destroy()


def kismi_secim_yap(
    parent,
    satirlar: list[dict[str, Any]],
    *,
    baslik: str,
    aciklama: str,
    onceki_baslik: str,
    kalan_baslik: str,
    bu_belge_baslik: str,
    siparis_baslik: str = "Sipariş miktarı",
) -> list[dict[str, Any]] | None:
    if not satirlar:
        messagebox.showinfo(baslik, "Aktarılacak açık miktar kalmadı.", parent=parent)
        return None
    dlg = KismiBelgeSecimDialog(
        parent,
        baslik=baslik,
        aciklama=aciklama,
        satirlar=satirlar,
        onceki_baslik=onceki_baslik,
        kalan_baslik=kalan_baslik,
        bu_belge_baslik=bu_belge_baslik,
        siparis_baslik=siparis_baslik,
    )
    parent.wait_window(dlg)
    return dlg.result
