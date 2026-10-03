"""Kasa / banka kartlarının muhasebe hesapları (kart bazında hesap seçimi) ve finans ↔ muhasebe bakiye karşılaştırması."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from tkinter import messagebox, ttk

from database.muhasebe_service import para_goster

_HESAP_BOS = "— Kartta seçili değil (firma varsayılanı) —"
_KOMISYON_BOS = "— Kartta seçili değil (firma varsayılanı) —"
_ALT_ADI = {"KASA": "Kasa", "MEVDUAT": "Mevduat", "KMH": "KMH", "POS": "POS", "KREDI_KARTI": "Kredi kartı",
            "KREDILER": "Krediler"}


def _uygun(alt_tur: str, kod: str, *, komisyon: bool = False) -> bool:
    from database.muhasebe_finans_ayarlari import kart_hesap_uyumsuzlugu

    fh = SimpleNamespace(hesap_turu="KASA" if alt_tur == "KASA" else "BANKA", alt_hesap_turu=alt_tur)
    return kart_hesap_uyumsuzlugu(fh, kod, komisyon=komisyon) is None


class KartMuhasebeHesaplariDialog(tk.Toplevel):
    """Kartların muhasebe hesabı: seçilmezse firma varsayılanı kullanılır; ikisi de yoksa evrak incelemeye düşer."""

    KOLONLAR = (("hesap_adi", "Kart / alt hesap", 230), ("alt", "Tür", 80), ("hareket", "Hareket", 60),
                ("hesap", "Muhasebe hesabı", 230), ("komisyon", "POS komisyon hesabı", 190),
                ("durum", "Durum", 220))

    def __init__(self, parent, *, banka_karti_id: int | None = None, baslik: str | None = None):
        super().__init__(parent)
        from database import muhasebe_finans_ayarlari as fa

        self.fa = fa
        self.banka_karti_id = banka_karti_id
        self.title(baslik or "Kasa / Banka Kartı Muhasebe Hesapları")
        self.geometry("1100x620")
        self.transient(parent)
        try:
            adaylar = fa.ekran_verisi()["adaylar"]
        except Exception as hata:
            messagebox.showerror(self.title(), str(hata), parent=parent)
            self.destroy()
            return
        self._adaylar = adaylar
        self._etiket_id = {f"{a['kod']} — {a['ad']}": a["id"] for a in adaylar}
        self._satirlar: dict[str, dict] = {}

        ttk.Label(self, padding=(10, 8, 10, 0), wraplength=1060, justify="left", text=(
            "Her kasa ve banka alt hesabı (mevduat, KMH, POS, kredi kartı, krediler) kendi muhasebe hesabına bağlanabilir. "
            "Kartta hesap seçilmezse firma varsayılanı (Finans İşlem Ayarları) kullanılır; ikisi de yoksa evrak kaydedilir "
            "ama fiş üretmez, 'İnceleme gerekiyor' olarak bekler. Listede yalnız fişe uygun alt hesaplar bulunur. "
            "Değişiklik yalnız bundan sonraki fişleri etkiler; geçmiş fişler değişmez.")).pack(fill="x")

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        self.agac = ttk.Treeview(govde, columns=[k for k, _b, _g in self.KOLONLAR], show="headings", height=14)
        for k, b, g in self.KOLONLAR:
            self.agac.heading(k, text=b)
            self.agac.column(k, width=g, anchor="w" if k != "hareket" else "e")
        self.agac.tag_configure("inceleme", foreground="#c62828")
        self.agac.tag_configure("kart", foreground="#2e7d32")
        kay = ttk.Scrollbar(govde, orient="vertical", command=self.agac.yview)
        self.agac.configure(yscrollcommand=kay.set)
        self.agac.pack(side="left", fill="both", expand=True)
        kay.pack(side="right", fill="y")
        self.agac.bind("<<TreeviewSelect>>", lambda _e: self._secildi())

        duzen = ttk.LabelFrame(self, text="Seçili kart", padding=10)
        duzen.pack(fill="x", padx=10)
        self.secili_lbl = ttk.Label(duzen, text="Listeden bir kart seçin.")
        self.secili_lbl.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(duzen, text="Muhasebe hesabı").grid(row=1, column=0, sticky="w", pady=4)
        self.hesap_var = tk.StringVar(value=_HESAP_BOS)
        self.hesap_cb = ttk.Combobox(duzen, textvariable=self.hesap_var, state="disabled", width=60)
        self.hesap_cb.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(duzen, text="POS komisyon gideri").grid(row=2, column=0, sticky="w", pady=4)
        self.komisyon_var = tk.StringVar(value=_KOMISYON_BOS)
        self.komisyon_cb = ttk.Combobox(duzen, textvariable=self.komisyon_var, state="disabled", width=60)
        self.komisyon_cb.grid(row=2, column=1, sticky="w", padx=6)
        self.neden_lbl = ttk.Label(duzen, text="", foreground="#c62828", wraplength=1040, justify="left")
        self.neden_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.kaydet_btn = ttk.Button(duzen, text="Kaydet", command=self._kaydet, state="disabled")
        self.kaydet_btn.grid(row=1, column=2, rowspan=2, padx=12)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Finans ↔ Muhasebe Bakiye Karşılaştırması",
                   command=lambda: BakiyeKarsilastirmaDialog(self)).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.yenile()

    def yenile(self, sec: str | None = None):
        self.agac.delete(*self.agac.get_children())
        self._satirlar.clear()
        for k in self.fa.kart_hesaplari(banka_karti_id=self.banka_karti_id):
            iid = str(k["id"])
            self._satirlar[iid] = k
            etiket = "inceleme" if k["durum"] == "İnceleme gerekiyor" else ("kart" if k["muhasebe_hesap_id"] else "")
            self.agac.insert("", "end", iid=iid, tags=(etiket,), values=(
                k["hesap_adi"], _ALT_ADI.get(k["alt_tur"], k["alt_tur"]), k["hareket"], k["muhasebe_hesap"] or "—",
                k["komisyon_hesap"] or ("—" if k["alt_tur"] == "POS" else ""), k["durum"]))
        if sec and sec in self._satirlar:
            self.agac.selection_set(sec)
            self.agac.see(sec)

    def _secildi(self):
        secim = self.agac.selection()
        if not secim:
            return
        k = self._satirlar[secim[0]]
        alt = k["alt_tur"]
        self.secili_lbl.configure(text=f"{k['hesap_adi']} ({_ALT_ADI.get(alt, alt)}) — {k['durum']}")
        self.hesap_cb.configure(state="readonly", values=[_HESAP_BOS, *(
            f"{a['kod']} — {a['ad']}" for a in self._adaylar if _uygun(alt, a["kod"]))])
        self.hesap_var.set(k["muhasebe_hesap"] or _HESAP_BOS)
        if alt == "POS":
            self.komisyon_cb.configure(state="readonly", values=[_KOMISYON_BOS, *(
                f"{a['kod']} — {a['ad']}" for a in self._adaylar if _uygun(alt, a["kod"], komisyon=True))])
            self.komisyon_var.set(k["komisyon_hesap"] or _KOMISYON_BOS)
        else:
            self.komisyon_cb.configure(state="disabled", values=[])
            self.komisyon_var.set(_KOMISYON_BOS)
        self.neden_lbl.configure(text=k["neden"] or "")
        self.kaydet_btn.configure(state="normal")

    def _kaydet(self):
        secim = self.agac.selection()
        if not secim:
            return
        k = self._satirlar[secim[0]]
        komisyon = self._etiket_id.get(self.komisyon_var.get()) if k["alt_tur"] == "POS" else False
        try:
            self.fa.kart_hesabi_kaydet(k["id"], self._etiket_id.get(self.hesap_var.get()), komisyon_hesap_id=komisyon)
        except Exception as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            return
        self.yenile(sec=secim[0])
        self._secildi()


class BakiyeKarsilastirmaDialog(tk.Toplevel):
    """Muhasebe hesabı başına bağlı kartların finans bakiyesi ile hesabın muhasebe bakiyesi."""

    def __init__(self, parent):
        super().__init__(parent)
        from database.muhasebe_finans_ayarlari import finans_muhasebe_mutabakati

        self.title("Finans ↔ Muhasebe Bakiye Karşılaştırması")
        self.geometry("1000x480")
        self.transient(parent)
        ttk.Label(self, padding=(10, 8, 10, 0), wraplength=960, justify="left", text=(
            "Fark; açılış bakiyelerinden, genel muhasebe kullanılmadan önceki hareketlerden veya henüz "
            "muhasebeleştirilmemiş evraklardan kaynaklanabilir. Fark kendiliğinden düzeltilmez.")).pack(fill="x")
        kol = (("hesap", "Muhasebe hesabı", 260), ("kartlar", "Bağlı kartlar", 330), ("finans", "Finans bakiyesi", 120),
               ("muhasebe", "Muhasebe bakiyesi", 120), ("fark", "Fark", 110))
        agac = ttk.Treeview(self, columns=[k for k, _b, _g in kol], show="headings")
        for k, b, g in kol:
            agac.heading(k, text=b)
            agac.column(k, width=g, anchor="e" if k in ("finans", "muhasebe", "fark") else "w")
        agac.tag_configure("fark", foreground="#c62828")
        agac.pack(fill="both", expand=True, padx=10, pady=8)
        try:
            satirlar = finans_muhasebe_mutabakati()
        except Exception as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            satirlar = []
        for r in satirlar:
            agac.insert("", "end", tags=("fark",) if r["fark"] else (), values=(
                f"{r['hesap_kodu']} — {r['hesap_adi']}", ", ".join(r["kartlar"]), para_goster(r["finans_bakiye"]),
                para_goster(r["muhasebe_bakiye"]), para_goster(r["fark"])))
        self.agac = agac
        ttk.Button(self, text="Kapat", command=self.destroy).pack(anchor="e", padx=10, pady=(0, 10))


class KasaMuhasebeHesabiAlani:
    """Kasa kartı ekranındaki 'Muhasebe Hesabı' seçimi (kart kaydedildikten sonra yazılır)."""

    def __init__(self, ust, satir: int, hesap=None):
        from database import muhasebe_finans_ayarlari as fa

        self.fa = fa
        self.ilk_id = getattr(hesap, "muhasebe_hesap_id", None) if hesap else None
        try:
            adaylar = [a for a in fa.ekran_verisi()["adaylar"] if _uygun("KASA", a["kod"])]
        except Exception:
            adaylar = []
        self._etiket_id = {f"{a['kod']} — {a['ad']}": a["id"] for a in adaylar}
        id_etiket = {v: k for k, v in self._etiket_id.items()}
        ttk.Label(ust, text="Muhasebe Hesabı").grid(row=satir, column=0, padx=12, pady=5, sticky="w")
        self.var = tk.StringVar(value=id_etiket.get(self.ilk_id, _HESAP_BOS))
        self.cb = ttk.Combobox(ust, textvariable=self.var, state="readonly", width=48,
                               values=[_HESAP_BOS, *self._etiket_id])
        self.cb.grid(row=satir, column=1, padx=12, pady=5, sticky="w")
        ttk.Label(ust, text="Seçilmezse firma varsayılanı (Finans İşlem Ayarları → Kasa) kullanılır.",
                  foreground="#555").grid(row=satir + 1, column=1, padx=12, sticky="w")

    def secili_id(self) -> int | None:
        return self._etiket_id.get(self.var.get())

    def kaydet(self, finans_hesap_id: int) -> None:
        yeni = self.secili_id()
        if yeni != self.ilk_id:
            self.fa.kart_hesabi_kaydet(int(finans_hesap_id), yeni)
            self.ilk_id = yeni
