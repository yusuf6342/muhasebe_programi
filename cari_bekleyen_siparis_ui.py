"""Cari kart — Bekleyen Siparişler listesi diyalogu."""

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
    ("cari", "Cari", 180),
    ("termin", "Termin", 90),
    ("durum", "Durum", 120),
    ("pb", "PB", 50),
    ("brut", "Brüt", 100),
    ("net", "Net", 100),
    ("sevk", "Sevk tutar", 100),
    ("fatura", "Fatura tutar", 100),
    ("iptal", "İptal tutar", 90),
    ("kalan", "Kalan tutar", 110),
)


class CariBekleyenSiparislerDialog(tk.Toplevel):
    """Cari kimliği ile filtrelenmiş açık sipariş listesi."""

    def __init__(self, parent, cari, *, yon: str = "satis"):
        super().__init__(parent)
        if cari is None or getattr(cari, "id", None) is None:
            raise ValueError("Cari gerekli.")
        self.cari = cari
        self.yon = "alis" if yon == "alis" else "satis"
        self.parent_kart = parent
        self._kayitlar: list[dict] = []
        self._iid_map: dict[str, dict] = {}

        baslik = (
            "Bekleyen Satış Siparişleri"
            if self.yon == "satis"
            else "Bekleyen Satın Alma Siparişleri"
        )
        self.title(f"{baslik} — {cari.cari_kodu} {cari.unvan}")
        self.geometry("1100x520")
        self.minsize(900, 400)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=(12, 10, 12, 6))
        ust.pack(fill="x")
        ttk.Label(ust, text=baslik, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            ust,
            text=f"{cari.cari_kodu} — {cari.unvan}",
            font=("Segoe UI", 10),
            foreground="#1a237e",
        ).pack(anchor="w", pady=(2, 0))

        filtre = ttk.Frame(self, padding=(12, 0, 12, 6))
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Ara:").pack(side="left")
        self.ara = ttk.Entry(filtre, width=22)
        self.ara.pack(side="left", padx=4)
        self.ara.bind("<Return>", lambda _e: self.yenile())

        self.var_tamam = tk.BooleanVar(value=False)
        self.var_iptal = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtre,
            text="Tamamlananları göster",
            variable=self.var_tamam,
            command=self.yenile,
        ).pack(side="left", padx=(12, 4))
        ttk.Checkbutton(
            filtre,
            text="İptal edilenleri göster",
            variable=self.var_iptal,
            command=self.yenile,
        ).pack(side="left", padx=4)
        ttk.Button(filtre, text="Yenile", command=self.yenile).pack(side="left", padx=(12, 4))
        ttk.Button(filtre, text="Kapat", command=self.destroy).pack(side="right")

        tablo_f = ttk.Frame(self, padding=(12, 0, 12, 4))
        tablo_f.pack(fill="both", expand=True)
        ids = [k[0] for k in KOLONLAR]
        self.tablo = ttk.Treeview(tablo_f, columns=ids, show="headings", selectmode="browse")
        for kid, bas, gen in KOLONLAR:
            anchor = "e" if kid in ("brut", "net", "sevk", "fatura", "iptal", "kalan") else "w"
            self.tablo.heading(kid, text=bas, command=lambda c=kid: self._sirala(c))
            self.tablo.column(kid, width=gen, anchor=anchor, stretch=True)
        sy = ttk.Scrollbar(tablo_f, orient="vertical", command=self.tablo.yview)
        sx = ttk.Scrollbar(tablo_f, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        tablo_f.rowconfigure(0, weight=1)
        tablo_f.columnconfigure(0, weight=1)
        self.tablo.bind("<Double-1>", self._cift_tik)
        self._sira_kolon = "tarih"
        self._sira_ters = True

        alt = ttk.Frame(self, padding=(12, 4, 12, 10))
        alt.pack(fill="x")
        self.durum_lbl = ttk.Label(alt, text="", foreground="#455a64")
        self.durum_lbl.pack(side="left")
        self.toplam_lbl = ttk.Label(alt, text="", font=("Segoe UI", 10, "bold"))
        self.toplam_lbl.pack(side="right")

        self.after(50, self.yenile)

    def yenile(self):
        try:
            data = cari_bekleyen_siparisleri(
                int(self.cari.id),
                yon=self.yon,
                dahil_tamamlanan=bool(self.var_tamam.get()),
                dahil_iptal=bool(self.var_iptal.get()),
                ara=(self.ara.get() or "").strip() or None,
            )
        except Exception as hata:
            messagebox.showerror("Bekleyen Siparişler", str(hata), parent=self)
            return
        self._kayitlar = list(data.get("kayitlar") or [])
        self._doldur()

    def _sirala(self, kolon: str):
        if self._sira_kolon == kolon:
            self._sira_ters = not self._sira_ters
        else:
            self._sira_kolon = kolon
            self._sira_ters = kolon in ("tarih", "termin", "kalan", "brut", "net")
        self._doldur()

    def _anahtar(self, kayit: dict):
        c = self._sira_kolon
        if c == "siparis_no":
            return (kayit.get("siparis_no") or "").casefold()
        if c == "tarih":
            return kayit.get("siparis_tarihi") or ""
        if c == "termin":
            return kayit.get("termin_tarihi") or ""
        if c == "cari":
            return (kayit.get("cari_unvan") or "").casefold()
        if c == "durum":
            return (kayit.get("durum") or "").casefold()
        if c == "pb":
            return kayit.get("para_birimi") or ""
        harita = {
            "brut": "siparis_brut",
            "net": "siparis_net",
            "sevk": "sevk_tutar",
            "fatura": "fatura_tutar",
            "iptal": "iptal_tutar",
            "kalan": "kalan_tutar",
        }
        return Decimal(str(kayit.get(harita.get(c, "kalan_tutar")) or 0))

    def _doldur(self):
        for iid in self.tablo.get_children():
            self.tablo.delete(iid)
        self._iid_map.clear()
        kayitlar = sorted(self._kayitlar, key=self._anahtar, reverse=self._sira_ters)
        for k in kayitlar:
            cari_yazi = f"{k.get('cari_kodu') or ''} {k.get('cari_unvan') or ''}".strip()
            degerler = (
                k.get("siparis_no") or "",
                _tarih(k.get("siparis_tarihi")),
                cari_yazi,
                _tarih(k.get("termin_tarihi")),
                k.get("durum") or "",
                k.get("para_birimi") or "TRY",
                _para(k.get("siparis_brut")),
                _para(k.get("siparis_net")),
                _para(k.get("sevk_tutar")),
                _para(k.get("fatura_tutar")),
                _para(k.get("iptal_tutar")),
                _para(k.get("kalan_tutar")),
            )
            iid = self.tablo.insert("", "end", values=degerler)
            self._iid_map[iid] = k

        aciklar = [k for k in kayitlar if k.get("acik")]
        if not kayitlar:
            self.durum_lbl.configure(text="Bekleyen sipariş yok")
            self.toplam_lbl.configure(text="")
            return

        pb_toplam: dict[str, Decimal] = {}
        for k in aciklar:
            pb = k.get("para_birimi") or "TRY"
            pb_toplam[pb] = pb_toplam.get(pb, Decimal("0")) + Decimal(str(k.get("kalan_tutar") or 0))
        parcalar = [f"{_para(v)} {pb}" for pb, v in sorted(pb_toplam.items())]
        self.durum_lbl.configure(
            text=f"{len(kayitlar)} kayıt · {len(aciklar)} açık"
            + ("" if aciklar else " · Bekleyen sipariş yok")
        )
        self.toplam_lbl.configure(
            text=("Kalan toplam: " + " · ".join(parcalar)) if parcalar else "Kalan toplam: 0,00 TRY"
        )

    def _secili(self) -> dict | None:
        sec = self.tablo.selection()
        if not sec:
            return None
        return self._iid_map.get(sec[0])

    def _cift_tik(self, _event=None):
        kayit = self._secili()
        if not kayit:
            return
        sid = kayit.get("siparis_id")
        if not sid:
            return
        try:
            if self.yon == "alis":
                from alis_ui import AlisSiparisiDialog
                from database.alis_siparisi_service import AlisSiparisiService

                siparis = AlisSiparisiService.getir(int(sid))
                if siparis is None:
                    messagebox.showwarning("Sipariş", "Sipariş bulunamadı.", parent=self)
                    return
                dlg = AlisSiparisiDialog(self, siparis=siparis)
            else:
                from app import SatisSiparisiDialog
                from database.satis_siparisi_service import SatisSiparisiService

                siparis = SatisSiparisiService.getir(int(sid))
                if siparis is None:
                    messagebox.showwarning("Sipariş", "Sipariş bulunamadı.", parent=self)
                    return
                dlg = SatisSiparisiDialog(self, siparis=siparis)
            self.wait_window(dlg)
            self.yenile()
            parent = self.parent_kart
            if parent is not None and hasattr(parent, "yenile"):
                try:
                    parent.yenile()
                except Exception:
                    pass
        except Exception as hata:
            messagebox.showerror("Sipariş", str(hata), parent=self)
