"""Satış faturası — müşterinin faturalanacak irsaliyelerinden seçim diyaloğu."""

from __future__ import annotations

from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

from database.satis_faturasi_service import SatisFaturasiService
from database.turkce_normalize import turkce_normalize


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
    ("irsaliye_no", "İrsaliye No", 120),
    ("tarih", "Tarih", 90),
    ("durum", "Durum", 130),
    ("siparis", "Sipariş", 110),
    ("kalan_satir", "Kalan Satır", 90),
    ("kalan", "Kalan Tutar", 110),
)


class FaturaIrsaliyeSecimDialog(tk.Toplevel):
    """Seçili müşterinin faturalanmaya uygun satış irsaliyeleri."""

    def __init__(self, parent, cari):
        super().__init__(parent)
        if cari is None or getattr(cari, "id", None) is None:
            raise ValueError("Cari gerekli.")
        self.cari = cari
        self.result = None  # irsaliye_id
        self._kayitlar: list[dict] = []
        self._iid_map: dict[str, dict] = {}
        self._sirala_kolon = "tarih"
        self._sirala_ters = True

        self.title(f"İrsaliyeden Getir — {cari.cari_kodu} {cari.unvan}")
        self.geometry("920x480")
        self.minsize(760, 360)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=(12, 10, 12, 6))
        ust.pack(fill="x")
        ttk.Label(ust, text="Faturalanacak Satış İrsaliyeleri", font=("Segoe UI", 12, "bold")).pack(
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
            text="Sevk edilmiş / kısmen faturalanmış irsaliyeler listelenir. Tamamen faturalananlar yoktur.",
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
            self.tablo.heading(anahtar, text=baslik, command=lambda a=anahtar: self._sirala(a))
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
            from database.satis_irsaliyesi_service import faturalanacak_kalan

            irsaliyeler = SatisFaturasiService.acik_irsaliyeler(cari_id=int(self.cari.id))
            self._kayitlar = []
            for ir in irsaliyeler:
                kalan_satir = 0
                kalan_tutar = Decimal("0")
                for s in ir.satirlar or []:
                    k = faturalanacak_kalan(s)
                    if k <= 0:
                        continue
                    kalan_satir += 1
                    fiyat = Decimal(str(getattr(s, "birim_fiyat", 0) or 0))
                    isk = Decimal(str(getattr(s, "iskonto_orani", 0) or 0))
                    net = fiyat * (Decimal("1") - isk / Decimal("100"))
                    kalan_tutar += Decimal(str(k)) * net
                self._kayitlar.append(
                    {
                        "irsaliye_id": int(ir.id),
                        "irsaliye_no": ir.irsaliye_no or "",
                        "tarih": _tarih(getattr(ir, "irsaliye_tarihi", None) or getattr(ir, "tarih", None)),
                        "durum": ir.durum or "",
                        "siparis": (ir.siparis.siparis_no if ir.siparis else "") or "",
                        "kalan_satir": kalan_satir,
                        "kalan": kalan_tutar,
                        "_ara": turkce_normalize(
                            f"{ir.irsaliye_no} {ir.durum} "
                            f"{ir.siparis.siparis_no if ir.siparis else ''}"
                        ),
                    }
                )
        except Exception as hata:
            messagebox.showerror("İrsaliye", f"Liste yüklenemedi:\n{hata}", parent=self)
            self._kayitlar = []
        self._filtrele()

    def _filtrele(self):
        q = turkce_normalize(self.ara.get().strip())
        kayitlar = [k for k in self._kayitlar if not q or q in k.get("_ara", "")]
        self._doldur(kayitlar)

    def _sirala(self, kolon: str):
        if self._sirala_kolon == kolon:
            self._sirala_ters = not self._sirala_ters
        else:
            self._sirala_kolon = kolon
            self._sirala_ters = kolon in ("tarih", "kalan", "kalan_satir")
        self._filtrele()

    def _doldur(self, kayitlar: list[dict]):
        for iid in self.tablo.get_children():
            self.tablo.delete(iid)
        self._iid_map.clear()
        kolon = self._sirala_kolon
        ters = self._sirala_ters

        def anahtar(k):
            v = k.get(kolon)
            if kolon in ("kalan", "kalan_satir"):
                return Decimal(str(v or 0))
            return str(v or "")

        try:
            sirali = sorted(kayitlar, key=anahtar, reverse=ters)
        except Exception:
            sirali = list(kayitlar)
        for k in sirali:
            iid = self.tablo.insert(
                "",
                "end",
                values=(
                    k["irsaliye_no"],
                    k["tarih"],
                    k["durum"],
                    k["siparis"],
                    k["kalan_satir"],
                    _para(k["kalan"]),
                ),
            )
            self._iid_map[iid] = k
        self._ozet.configure(text=f"{len(sirali)} irsaliye")

    def aktar(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("İrsaliye", "Faturaya aktarmak için bir irsaliye seçin.", parent=self)
            return
        kayit = self._iid_map.get(secim[0])
        if not kayit:
            return
        self.result = int(kayit["irsaliye_id"])
        self.destroy()


def fatura_icin_irsaliye_sec(parent, cari) -> int | None:
    """Modal seçim; seçilen irsaliye id veya None."""
    dlg = FaturaIrsaliyeSecimDialog(parent, cari)
    parent.wait_window(dlg)
    return dlg.result
