"""Tedarikçi kartı — sipariş, irsaliye, alış faturası, iade evrakları ve bağlı satın alma talepleri."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

from database.alis_faturasi_service import AlisFaturasiService

SEKMELER: tuple[tuple[str, str, tuple[tuple[str, str, int], ...]], ...] = (
    (
        "siparis",
        "Alış Siparişleri",
        (
            ("no", "Sipariş No", 150),
            ("tarih", "Tarih", 95),
            ("termin", "Termin", 95),
            ("satir", "Satır", 70),
            ("acik_satir", "Teslim Bekleyen Satır", 150),
            ("durum", "Durum", 140),
        ),
    ),
    (
        "irsaliye",
        "Faturalanmamış İrsaliyeler",
        (
            ("no", "İrsaliye No", 190),
            ("tarih", "Tarih", 95),
            ("siparis", "Sipariş No", 150),
            ("miktar", "İrsaliye Miktarı", 120),
            ("kalan", "Faturalanacak Kalan", 140),
            ("durum", "Durum", 140),
        ),
    ),
    (
        "fatura",
        "Alış Faturaları",
        (
            ("no", "Kayıt No", 120),
            ("ted_no", "Tedarikçi Fatura No", 150),
            ("tarih", "Tarih", 95),
            ("siparis", "Sipariş No", 140),
            ("irsaliye", "İrsaliye No", 170),
            ("genel", "Genel Toplam", 120),
            ("durum", "Durum", 90),
        ),
    ),
    (
        "iade",
        "Alış İade Faturaları",
        (
            ("no", "İade No", 150),
            ("tarih", "Tarih", 95),
            ("genel", "Genel Toplam", 120),
            ("durum", "Durum", 90),
        ),
    ),
    (
        "talep",
        "Bağlı Satın Alma Talepleri",
        (
            ("no", "Talep No", 120),
            ("tarih", "Tarih", 95),
            ("termin", "İhtiyaç Tarihi", 110),
            ("isteyen", "Talep Eden", 160),
            ("durum", "Durum", 190),
        ),
    ),
)
_SAYISAL = frozenset({"miktar", "kalan", "genel", "satir", "acik_satir"})


def _hucre(kolon: str, deger) -> str:
    if deger is None:
        return ""
    if kolon in ("tarih", "termin") and hasattr(deger, "strftime"):
        return deger.strftime("%d.%m.%Y")
    if kolon in _SAYISAL:
        d = Decimal(str(deger or 0))
        if kolon == "genel":
            return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{d.normalize():f}".replace(".", ",")
    return str(deger)


class TedarikciEvraklariDialog(tk.Toplevel):
    """Yalnız bu tedarikçinin alış evrakları; çift tık evrakı açar."""

    def __init__(self, parent, cari, *, sekme: str = "fatura"):
        super().__init__(parent)
        if cari is None or getattr(cari, "id", None) is None:
            raise ValueError("Cari gerekli.")
        self.cari = cari
        self.parent_kart = parent
        self.title(f"Alış Evrakları — {cari.cari_kodu} {cari.unvan}")
        from ui_pencere import evrak_penceresi_boyutlandir

        evrak_penceresi_boyutlandir(self, genislik=1100, yukseklik=560, min_genislik=720, min_yukseklik=360)
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=(12, 10, 12, 6))
        ust.pack(fill="x")
        ttk.Label(ust, text="TEDARİKÇİ ALIŞ EVRAKLARI", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            ust, text=f"{cari.cari_kodu} — {cari.unvan}", font=("Segoe UI", 12, "bold"), foreground="#0B2A4A"
        ).pack(anchor="w", pady=(2, 0))

        self.defter = ttk.Notebook(self)
        self.defter.pack(fill="both", expand=True, padx=12, pady=4)
        self.tablolar: dict[str, ttk.Treeview] = {}
        for anahtar, baslik, kolonlar in SEKMELER:
            cerceve = ttk.Frame(self.defter, padding=4)
            self.defter.add(cerceve, text=baslik)
            tablo = ttk.Treeview(
                cerceve, columns=[k for k, _, _ in kolonlar], show="headings", selectmode="browse"
            )
            for kolon, kbaslik, genislik in kolonlar:
                tablo.heading(kolon, text=kbaslik)
                tablo.column(kolon, width=genislik, anchor="e" if kolon in _SAYISAL else "w")
            kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
            tablo.configure(yscrollcommand=kaydir.set)
            tablo.pack(side="left", fill="both", expand=True)
            kaydir.pack(side="right", fill="y")
            tablo.bind("<Double-1>", lambda _e, a=anahtar: self.seciliyi_ac(a))
            self.tablolar[anahtar] = tablo
        sira = [a for a, _, _ in SEKMELER]
        if sekme in sira:
            self.defter.select(sira.index(sekme))

        alt = ttk.Frame(self, padding=(12, 4, 12, 10))
        alt.pack(fill="x")
        ttk.Button(alt, text="Seçili Evrakı Aç", command=lambda: self.seciliyi_ac()).pack(side="left")
        ttk.Button(alt, text="İrsaliyeyi Faturala", command=self.irsaliyeyi_faturala).pack(side="left", padx=6)
        ttk.Button(alt, text="Faturadan İade Oluştur", command=self.faturadan_iade).pack(side="left")
        ttk.Button(alt, text="Yenile", command=self.yenile).pack(side="left", padx=6)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.yenile()

    def yenile(self):
        try:
            veriler = AlisFaturasiService.tedarikci_evraklari(int(self.cari.id))
        except Exception as hata:
            messagebox.showerror("Alış Evrakları", str(hata), parent=self)
            return
        for anahtar, baslik, kolonlar in SEKMELER:
            tablo = self.tablolar[anahtar]
            tablo.delete(*tablo.get_children())
            kayitlar = veriler.get(anahtar, [])
            for kayit in kayitlar:
                tablo.insert(
                    "", "end", iid=str(kayit["id"]),
                    values=[_hucre(k, kayit.get(k)) for k, _, _ in kolonlar],
                )
            self.defter.tab(self.tablolar[anahtar].master, text=f"{baslik} ({len(kayitlar)})")

    @staticmethod
    def _sekme_indeksi(anahtar: str) -> int:
        return [a for a, _, _ in SEKMELER].index(anahtar)

    def _aktif_sekme(self) -> str:
        indeks = self.defter.index(self.defter.select())
        return SEKMELER[indeks][0]

    def _secili_id(self, anahtar: str) -> int | None:
        secim = self.tablolar[anahtar].selection()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen bir evrak seçin.", parent=self)
            return None
        return int(secim[0])

    def _ac_bekle(self, dialog):
        self.wait_window(dialog)
        self.yenile()

    def seciliyi_ac(self, anahtar: str | None = None):
        anahtar = anahtar or self._aktif_sekme()
        evrak_id = self._secili_id(anahtar)
        if evrak_id is None:
            return
        from alis_ui import AlisFaturasiDialog, AlisIadeFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog

        if anahtar == "siparis":
            from database.alis_siparisi_service import AlisSiparisiService

            siparis = AlisSiparisiService.getir(evrak_id)
            if siparis:
                self._ac_bekle(AlisSiparisiDialog(self, siparis=siparis))
        elif anahtar == "talep":
            from satin_alma_talep_ui import SatinAlmaTalepDialog

            self._ac_bekle(SatinAlmaTalepDialog(self, talep_id=evrak_id))
        elif anahtar == "irsaliye":
            from database.alis_irsaliyesi_service import AlisIrsaliyesiService

            irsaliye = AlisIrsaliyesiService.getir(evrak_id)
            if irsaliye:
                self._ac_bekle(AlisIrsaliyesiDialog(self, irsaliye=irsaliye))
        elif anahtar == "fatura":
            fatura = AlisFaturasiService.getir(evrak_id)
            if fatura:
                self._ac_bekle(AlisFaturasiDialog(self, fatura=fatura))
        else:
            from database.alis_iade_faturasi_service import AlisIadeFaturasiService

            iade = AlisIadeFaturasiService.getir(evrak_id)
            if iade:
                self._ac_bekle(AlisIadeFaturasiDialog(self, iade=iade))

    def irsaliyeyi_faturala(self):
        if self._aktif_sekme() != "irsaliye":
            self.defter.select(self._sekme_indeksi("irsaliye"))
            messagebox.showinfo("İrsaliye", "Faturalanacak irsaliyeyi seçin.", parent=self)
            return
        evrak_id = self._secili_id("irsaliye")
        if evrak_id is None:
            return
        from alis_ui import AlisFaturasiDialog
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        irsaliye = AlisIrsaliyesiService.getir(evrak_id)
        if irsaliye:
            self._ac_bekle(AlisFaturasiDialog(self, irsaliye=irsaliye, cari=self.cari))

    def faturadan_iade(self):
        if self._aktif_sekme() != "fatura":
            self.defter.select(self._sekme_indeksi("fatura"))
            messagebox.showinfo("İade", "İade edilecek alış faturasını seçin.", parent=self)
            return
        evrak_id = self._secili_id("fatura")
        if evrak_id is None:
            return
        fatura = AlisFaturasiService.getir(evrak_id)
        if fatura is None:
            return
        if fatura.durum == "İPTAL":
            messagebox.showwarning("İade", "İptal edilmiş faturadan iade oluşturulamaz.", parent=self)
            return
        from alis_ui import AlisIadeFaturasiDialog

        self._ac_bekle(AlisIadeFaturasiDialog(self, kaynak_fatura=fatura))
