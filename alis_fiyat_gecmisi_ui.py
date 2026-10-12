"""Geçmiş alış fiyatları penceresi (salt okunur; tüm satın alma evraklarında ortak).

Fiyat hücresine (fiyat sütunu olmayan evrakta ürün satırına) sağ tıklanınca açılır.
Veri ``database.fiyat_kaynagi_service.alis_fiyat_gecmisi`` ile ürün + firma (+ tedarikçi)
kısıtlı sorgudan, sayfa sayfa okunur. Pencere evraktaki hiçbir değeri değiştirmez.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.fiyat_kaynagi_service import alis_fiyat_gecmisi

SAYFA = 50

KOLONLAR = (
    ("tarih", "Tarih", 82, "center"),
    ("belge_no", "Belge No", 110, "w"),
    ("tedarikci", "Tedarikçi", 190, "w"),
    ("miktar", "Miktar", 70, "e"),
    ("birim", "Birim", 60, "center"),
    ("brut", "Brüt Fiyat", 90, "e"),
    ("pb", "PB", 42, "center"),
    ("iskonto", "İskonto %", 90, "center"),
    ("net", "Net Birim (KDV hariç)", 130, "e"),
    ("kdv", "KDV %", 52, "center"),
    ("kdv_durumu", "KDV", 56, "center"),
    ("tur", "Tür", 52, "center"),
)


def _sayi(d, basamak: int = 2) -> str:
    try:
        metin = f"{Decimal(str(d)):,.{basamak}f}"
    except Exception:
        return ""
    return metin.replace(",", "X").replace(".", ",").replace("X", ".")


def _miktar(d) -> str:
    try:
        v = Decimal(str(d)).normalize()
    except Exception:
        return ""
    metin = f"{v:f}"
    return metin.replace(".", ",")


def _iskonto(k: dict) -> str:
    parcalar = [_miktar(k[a]) for a in ("iskonto_1", "iskonto_2", "iskonto_3") if k.get(a)]
    return " + ".join(parcalar) if parcalar else "-"


def _tarih_coz(metin: str):
    metin = (metin or "").strip()
    if not metin:
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


class AlisFiyatGecmisiPenceresi(tk.Toplevel):
    def __init__(self, dialog):
        super().__init__(dialog.winfo_toplevel())
        self.dialog = dialog
        self.title("Geçmiş Alış Fiyatları")
        self.transient(dialog.winfo_toplevel())
        self.minsize(820, 360)
        self.urun_kodu = ""
        self.urun_adi = ""
        self.cari_id = None
        self.cari_adi = ""
        self._offset = 0
        self._kayit_sayisi = 0

        self.kapsam = tk.StringVar(value="tedarikci")
        self.iade = tk.BooleanVar(value=False)

        ust = ttk.Frame(self, padding=(10, 8, 10, 4))
        ust.pack(fill="x")
        self.urun_lbl = ttk.Label(ust, text="", font=("Segoe UI", 10, "bold"))
        self.urun_lbl.pack(anchor="w")
        self.tedarikci_lbl = ttk.Label(ust, text="", foreground="#1F3A5F")
        self.tedarikci_lbl.pack(anchor="w")

        filtre = ttk.Frame(self, padding=(10, 0, 10, 4))
        filtre.pack(fill="x")
        self.rb_tedarikci = ttk.Radiobutton(
            filtre, text="Bu tedarikçiden alışlar", value="tedarikci", variable=self.kapsam, command=self.yenile
        )
        self.rb_tedarikci.pack(side="left")
        ttk.Radiobutton(
            filtre, text="Tüm tedarikçilerden alışlar", value="tumu", variable=self.kapsam, command=self.yenile
        ).pack(side="left", padx=(10, 0))
        ttk.Checkbutton(filtre, text="İadeleri ayrı tür olarak göster", variable=self.iade,
                        command=self.yenile).pack(side="left", padx=(14, 0))
        ttk.Label(filtre, text="Tarih:").pack(side="left", padx=(18, 4))
        self.tarih_bas = ttk.Entry(filtre, width=11)
        self.tarih_bas.pack(side="left")
        ttk.Label(filtre, text="–").pack(side="left", padx=2)
        self.tarih_bit = ttk.Entry(filtre, width=11)
        self.tarih_bit.pack(side="left")
        ttk.Button(filtre, text="Uygula", command=self.yenile).pack(side="left", padx=(6, 0))
        for e in (self.tarih_bas, self.tarih_bit):
            e.bind("<Return>", lambda _e: self.yenile())

        govde = ttk.Frame(self, padding=(10, 0, 10, 0))
        govde.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(govde, columns=[k[0] for k in KOLONLAR], show="headings", selectmode="browse")
        for cid, baslik, gen, hiza in KOLONLAR:
            self.tablo.heading(cid, text=baslik)
            self.tablo.column(cid, width=gen, minwidth=40, anchor=hiza, stretch=(cid == "tedarikci"))
        sy = ttk.Scrollbar(govde, orient="vertical", command=self.tablo.yview)
        sx = ttk.Scrollbar(govde, orient="horizontal", command=self.tablo.xview)
        self.tablo.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        govde.rowconfigure(0, weight=1)
        govde.columnconfigure(0, weight=1)
        self.tablo.tag_configure("iade", foreground="#9C2A00")
        self.tablo.tag_configure("cift", background="#F5F8FC")

        alt = ttk.Frame(self, padding=(10, 4, 10, 8))
        alt.pack(fill="x")
        self.durum_lbl = ttk.Label(alt, text="")
        self.durum_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.daha_btn = ttk.Button(alt, text="Daha fazla", command=self.daha_fazla)
        self.daha_btn.pack(side="right", padx=6)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<FocusIn>", self._odak, add="+")
        self.geometry("1040x420")

    # ─── bağlam
    def baglam(self, urun_kodu: str, urun_adi: str, cari) -> None:
        kod = (urun_kodu or "").strip()
        cari_id = getattr(cari, "id", None)
        degisti = kod != self.urun_kodu or cari_id != self.cari_id
        self.urun_kodu, self.urun_adi = kod, urun_adi or ""
        self.cari_id, self.cari_adi = cari_id, (getattr(cari, "unvan", "") or "")
        self.urun_lbl.configure(text=f"{kod} — {self.urun_adi}" if kod else "Ürün seçiniz")
        if cari_id:
            self.rb_tedarikci.state(["!disabled"])
            self.tedarikci_lbl.configure(text=f"Belge tedarikçisi: {self.cari_adi}")
        else:
            self.rb_tedarikci.state(["disabled"])
            self.kapsam.set("tumu")
            self.tedarikci_lbl.configure(
                text="Belgede tedarikçi seçilmedi; tüm tedarikçilerden alışlar gösteriliyor."
            )
        if degisti:
            self.yenile()

    def _odak(self, event=None):
        if event is not None and event.widget is not self:
            return
        if not (hasattr(self.dialog, "tedarikci_map") or hasattr(self.dialog, "_secili_cari")):
            return
        from fiyat_kaynagi_ui import belge_tedarikcisi

        cari = belge_tedarikcisi(self.dialog)
        if getattr(cari, "id", None) != self.cari_id:
            self.baglam(self.urun_kodu, self.urun_adi, cari)

    # ─── veri
    def _filtre(self) -> dict | None:
        try:
            bas = _tarih_coz(self.tarih_bas.get())
            bit = _tarih_coz(self.tarih_bit.get())
        except ValueError:
            messagebox.showwarning("Tarih", "Tarihi GG.AA.YYYY biçiminde girin.", parent=self)
            return None
        return {
            "cari_id": self.cari_id if self.kapsam.get() == "tedarikci" and self.cari_id else None,
            "tarih_bas": bas,
            "tarih_bit": bit,
            "iade_dahil": bool(self.iade.get()),
        }

    def yenile(self) -> None:
        self._offset = 0
        self._kayit_sayisi = 0
        self.tablo.delete(*self.tablo.get_children())
        self._yukle()

    def daha_fazla(self) -> None:
        self._yukle()

    def _yukle(self) -> None:
        if not self.urun_kodu:
            self.durum_lbl.configure(text="Ürün seçiniz.")
            self.daha_btn.state(["disabled"])
            return
        filtre = self._filtre()
        if filtre is None:
            return
        try:
            sonuc = alis_fiyat_gecmisi(self.urun_kodu, limit=SAYFA, offset=self._offset, **filtre)
        except Exception as hata:  # noqa: BLE001
            self.durum_lbl.configure(text=f"Geçmiş okunamadı: {hata}")
            return
        for k in sonuc["kayitlar"]:
            i = self._kayit_sayisi
            etiket = ["iade"] if k["tur"] == "İADE" else []
            if i % 2:
                etiket.append("cift")
            self.tablo.insert("", "end", values=(
                k["tarih"].strftime("%d.%m.%Y") if k["tarih"] else "",
                k["belge_no"],
                k["tedarikci"],
                _miktar(k["miktar"]),
                k["birim"],
                _sayi(k["brut_fiyat"], 4 if k["brut_fiyat"] != k["brut_fiyat"].quantize(Decimal("0.01")) else 2),
                k["para_birimi"],
                _iskonto(k),
                _sayi(k["net_fiyat"], 4 if k["net_fiyat"] != k["net_fiyat"].quantize(Decimal("0.01")) else 2),
                _miktar(k["kdv_orani"]),
                k["kdv_durumu"],
                "İade" if k["tur"] == "İADE" else "Alış",
            ), tags=tuple(etiket))
            self._kayit_sayisi += 1
        self._offset += len(sonuc["kayitlar"])
        if self._kayit_sayisi == 0:
            self.durum_lbl.configure(text="Kayıt bulunamadı.")
        else:
            self.durum_lbl.configure(
                text=f"{self._kayit_sayisi} / {sonuc['toplam']} kayıt · en yeni üstte · "
                     "fiyatlar belgede kaydedildiği birim ve para biriminde"
            )
        self.daha_btn.state(["!disabled"] if sonuc["daha_var"] else ["disabled"])


def fiyat_gecmisi_ac(dialog, urun_kodu: str, urun_adi: str = "", cari=None) -> AlisFiyatGecmisiPenceresi | None:
    if not (urun_kodu or "").strip():
        messagebox.showinfo("Geçmiş Alış Fiyatları", "Ürün seçiniz.", parent=dialog)
        return None
    pen = getattr(dialog, "_fiyat_gecmisi_pen", None)
    try:
        if pen is None or not pen.winfo_exists():
            pen = AlisFiyatGecmisiPenceresi(dialog)
            dialog._fiyat_gecmisi_pen = pen
    except tk.TclError:
        pen = AlisFiyatGecmisiPenceresi(dialog)
        dialog._fiyat_gecmisi_pen = pen
    pen.baglam(urun_kodu, urun_adi, cari)
    try:
        pen.deiconify()
        pen.lift()
    except tk.TclError:
        pass
    return pen


def satirdan_fiyat_gecmisi(dialog, satirlar, idx: int, tablo=None) -> AlisFiyatGecmisiPenceresi | None:
    """Evrak satırından (ürün) ve belge cari kartından (tedarikçi id) pencereyi açar/günceller."""
    from fiyat_kaynagi_ui import belge_tedarikcisi

    satir = satirlar[idx] if 0 <= idx < len(satirlar) else {}
    kod = (satir.get("urun_kodu") or "").strip()
    pen = fiyat_gecmisi_ac(dialog, kod, satir.get("urun_adi") or "", satir_tedarikcisi(dialog, satir))
    if pen is not None and tablo is not None and not getattr(dialog, "_fiyat_gecmisi_bagli", False):
        dialog._fiyat_gecmisi_bagli = True
        _secimi_izle(dialog, tablo, lambda: getattr(dialog, "satirlar", satirlar))
    return pen


def satir_tedarikcisi(dialog, satir: dict):
    """Teklifte tedarikçi satırdadır (cari_id); diğer evraklarda belge başlığındadır."""
    from fiyat_kaynagi_ui import belge_tedarikcisi

    cari_id = satir.get("cari_id") if isinstance(satir, dict) else None
    if cari_id:
        try:
            from database.cari_service import CariService

            cari = CariService.getir(int(cari_id))
            if cari is not None:
                return cari
        except Exception:
            from types import SimpleNamespace

            return SimpleNamespace(id=int(cari_id), unvan="")
    return belge_tedarikcisi(dialog)


def _secimi_izle(dialog, tablo, satirlar_getir) -> None:
    from satir_ici_urun_giris import satir_indeksi

    def _secim(_e=None):
        pen = getattr(dialog, "_fiyat_gecmisi_pen", None)
        try:
            if pen is None or not pen.winfo_exists():
                return
            secim = tablo.selection()
            idx = satir_indeksi(tablo, secim[0]) if secim else None
        except tk.TclError:
            return
        satirlar = satirlar_getir() or []
        if idx is None or not (0 <= idx < len(satirlar)):
            return
        s = satirlar[idx]
        if (s.get("urun_kodu") or "").strip():
            pen.baglam(s.get("urun_kodu"), s.get("urun_adi") or "", satir_tedarikcisi(dialog, s))

    tablo.bind("<<TreeviewSelect>>", _secim, add="+")
