"""Satış faturası — müşterinin bekleyen siparişlerinden seçim diyaloğu."""

from __future__ import annotations

from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

from database.cari_bekleyen_siparis_service import cari_bekleyen_siparisleri


def _para(tutar) -> str:
    d = Decimal(str(tutar or 0))
    return f"{float(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    if not t:
        return ""
    if isinstance(t, str):
        return t
    return t.strftime("%d.%m.%Y")


KOLONLAR = (
    ("siparis_no", "Sipariş No", 110),
    ("tarih", "Tarih", 90),
    ("termin", "Termin", 90),
    ("durum", "Durum", 130),
    ("pb", "Döviz", 55),
    ("kalan_satir", "Kalan Satır", 90),
    ("kalan", "Kalan Tutar", 110),
)


class FaturaSiparisSecimDialog(tk.Toplevel):
    """Seçili müşterinin açık / kısmen faturalanmış satış siparişleri."""

    def __init__(self, parent, cari):
        super().__init__(parent)
        if cari is None or getattr(cari, "id", None) is None:
            raise ValueError("Cari gerekli.")
        self.cari = cari
        self.result = None  # siparis_id
        self._kayitlar: list[dict] = []
        self._iid_map: dict[str, dict] = {}
        self._sirala_kolon = "tarih"
        self._sirala_ters = True

        self.title(f"Siparişten Getir — {cari.cari_kodu} {cari.unvan}")
        self.geometry("920x480")
        self.minsize(760, 360)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=(12, 10, 12, 6))
        ust.pack(fill="x")
        ttk.Label(ust, text="Bekleyen Satış Siparişleri", font=("Segoe UI", 12, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            ust,
            text=f"{cari.cari_kodu} — {cari.unvan}",
            font=("Segoe UI", 10),
            foreground="#1a237e",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            ust,
            text="Açık veya kısmen faturalanmış siparişler listelenir. Tamamlanan / iptal edilenler varsayılan listede yoktur.",
            font=("Segoe UI", 9),
            foreground="#475569",
        ).pack(anchor="w", pady=(4, 0))

        filtre = ttk.Frame(self, padding=(12, 0, 12, 6))
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Ara:").pack(side="left")
        self.ara = ttk.Entry(filtre, width=28)
        self.ara.pack(side="left", padx=4)
        self.ara.bind("<KeyRelease>", lambda _e: self._filtrele())
        self.ara.bind("<Return>", lambda _e: self._filtrele())
        ttk.Button(filtre, text="Yenile", command=self.yenile).pack(side="left", padx=(8, 4))

        tablo_f = ttk.Frame(self, padding=(12, 0, 12, 4))
        tablo_f.pack(fill="both", expand=True)
        kolonlar = tuple(k[0] for k in KOLONLAR)
        self.tablo = ttk.Treeview(tablo_f, columns=kolonlar, show="headings", selectmode="browse")
        for anahtar, baslik, genislik in KOLONLAR:
            self.tablo.heading(
                anahtar,
                text=baslik,
                command=lambda a=anahtar: self._sirala(a),
            )
            anchor = "e" if anahtar in ("kalan", "kalan_satir") else "w"
            self.tablo.column(anahtar, width=genislik, anchor=anchor, stretch=True)
        sy = ttk.Scrollbar(tablo_f, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sy.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self.aktar())
        self.tablo.bind("<Return>", lambda _e: self.aktar())

        alt = ttk.Frame(self, padding=(12, 6, 12, 12))
        alt.pack(fill="x")
        self._ozet = ttk.Label(alt, text="")
        self._ozet.pack(side="left")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(alt, text="Faturaya Aktar", command=self.aktar).pack(side="right", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(30, self.ara.focus_set)
        self.yenile()

    def yenile(self):
        try:
            data = cari_bekleyen_siparisleri(
                int(self.cari.id),
                yon="satis",
                dahil_tamamlanan=False,
                dahil_iptal=False,
                ara=None,
            )
        except Exception as hata:
            messagebox.showerror("Sipariş", str(hata), parent=self)
            return
        self._kayitlar = [k for k in data.get("kayitlar") or [] if k.get("acik")]
        self._filtrele()

    def _filtrele(self):
        ara = (self.ara.get() or "").strip().casefold()
        satirlar = self._kayitlar
        if ara:
            satirlar = [
                k
                for k in satirlar
                if ara
                in " ".join(
                    [
                        str(k.get("siparis_no") or ""),
                        str(k.get("durum") or ""),
                        str(k.get("para_birimi") or ""),
                    ]
                ).casefold()
            ]
        satirlar = self._siralanmis(satirlar)
        self.tablo.delete(*self.tablo.get_children())
        self._iid_map.clear()
        for k in satirlar:
            iid = str(k["siparis_id"])
            self._iid_map[iid] = k
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    k.get("siparis_no") or "",
                    _tarih(k.get("siparis_tarihi")),
                    _tarih(k.get("termin_tarihi")),
                    k.get("durum") or "",
                    k.get("para_birimi") or "TRY",
                    str(int(k.get("kalan_satir_sayisi") or 0)),
                    _para(k.get("kalan_tutar")),
                ),
            )
        self._ozet.configure(text=f"{len(satirlar)} sipariş")

    def _siralanmis(self, kayitlar: list[dict]) -> list[dict]:
        kolon = self._sirala_kolon
        ters = self._sirala_ters

        def anahtar(k: dict):
            if kolon == "tarih":
                return k.get("siparis_tarihi") or ""
            if kolon == "termin":
                return k.get("termin_tarihi") or ""
            if kolon == "kalan":
                return Decimal(str(k.get("kalan_tutar") or 0))
            if kolon == "kalan_satir":
                return int(k.get("kalan_satir_sayisi") or 0)
            if kolon == "siparis_no":
                return (k.get("siparis_no") or "").casefold()
            if kolon == "durum":
                return (k.get("durum") or "").casefold()
            if kolon == "pb":
                return (k.get("para_birimi") or "").casefold()
            return ""

        try:
            return sorted(kayitlar, key=anahtar, reverse=ters)
        except TypeError:
            return kayitlar

    def _sirala(self, kolon: str):
        if self._sirala_kolon == kolon:
            self._sirala_ters = not self._sirala_ters
        else:
            self._sirala_kolon = kolon
            self._sirala_ters = kolon in ("tarih", "termin", "kalan", "kalan_satir")
        self._filtrele()

    def aktar(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Sipariş", "Faturaya aktarmak için bir sipariş seçin.", parent=self)
            return
        kayit = self._iid_map.get(secim[0])
        if not kayit:
            return
        self.result = int(kayit["siparis_id"])
        self.destroy()


def fatura_icin_siparis_sec(parent, cari) -> int | None:
    """Modal seçim; seçilen sipariş id veya None."""
    dlg = FaturaSiparisSecimDialog(parent, cari)
    parent.wait_window(dlg)
    return dlg.result
