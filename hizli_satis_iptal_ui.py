"""Hızlı Satış Aşama 7 — tamamlanmış satış iptal / kısmi iade diyaloğu."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.access import AccessError
from database.hizli_satis_service import HizliSatisService


SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
KIRMIZI = "#C62828"
BEYAZ = "#FFFFFF"

IPTAL_NEDENLERI = (
    "Müşteri vazgeçti",
    "Yanlış ürün / miktar",
    "Yanlış ödeme",
    "Test / eğitim",
    "Diğer",
)


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _miktar_goster(miktar) -> str:
    d = Decimal(str(miktar or 0))
    if d == d.to_integral_value():
        return str(int(d))
    metin = format(d, "f").rstrip("0").rstrip(".")
    return metin or "0"

def _tarih_metin(d) -> str:
    if d is None:
        return ""
    try:
        return d.strftime("%d.%m.%Y")
    except Exception:
        return str(d)


class HizliSatisIptalIadeDialog(tk.Toplevel):
    """Bugünkü / son hızlı satışları listeler; tam iptal veya kısmi iade yapar."""

    def __init__(
        self,
        parent,
        *,
        on_basari: Callable[[dict[str, Any]], None] | None = None,
        on_secili_fatura_id: int | None = None,
    ):
        super().__init__(parent)
        self.title("HIZLI SATIŞ — İptal / İade")
        self.configure(bg=KOYU_GRI)
        self.geometry("920x560")
        self.minsize(800, 480)
        self.transient(parent)
        self.grab_set()

        self.on_basari = on_basari
        self.pref_fatura_id = on_secili_fatura_id
        self.result: dict[str, Any] | None = None
        self._liste: list[dict[str, Any]] = []
        self._ozet: dict[str, Any] | None = None
        self._satir_miktar: dict[int, tk.StringVar] = {}

        self._kur()
        self._yenile()
        self.bind("<Escape>", lambda _e: self._kapat())
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
        kok.columnconfigure(1, weight=1)

        tk.Label(
            kok,
            text="Tamamlanmış hızlı satışlar — soft iptal veya kısmi iade (stok/kasa geri alınır)",
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        # Sol: fatura listesi
        sol = tk.Frame(kok, bg=KOYU_GRI)
        sol.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        sol.rowconfigure(1, weight=1)
        sol.columnconfigure(0, weight=1)

        tk.Label(sol, text="Bugünkü satışlar", bg=KOYU_GRI, fg=BEYAZ, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        kolonlar = ("no", "saat", "musteri", "tutar", "durum")
        self.agac = ttk.Treeview(sol, columns=kolonlar, show="headings", height=14)
        basliklar = {
            "no": "Fatura",
            "saat": "Saat",
            "musteri": "Müşteri",
            "tutar": "Tutar",
            "durum": "Durum",
        }
        gen = {"no": 90, "saat": 55, "musteri": 140, "tutar": 90, "durum": 70}
        for k in kolonlar:
            self.agac.heading(k, text=basliklar[k])
            self.agac.column(k, width=gen[k], anchor="w")
        sy = ttk.Scrollbar(sol, orient="vertical", command=self.agac.yview)
        self.agac.configure(yscrollcommand=sy.set)
        self.agac.grid(row=1, column=0, sticky="nsew")
        sy.grid(row=1, column=1, sticky="ns")
        self.agac.bind("<<TreeviewSelect>>", lambda _e: self._secim_degisti())

        # Sağ: satırlar + neden
        sag = tk.Frame(kok, bg=KOYU_GRI)
        sag.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        sag.rowconfigure(1, weight=1)
        sag.columnconfigure(0, weight=1)

        self.ozet_lbl = tk.Label(
            sag,
            text="Fatura seçin",
            bg=KOYU_GRI,
            fg=BEYAZ,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        )
        self.ozet_lbl.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.satir_cerceve = tk.Frame(sag, bg=ACIK_GRI)
        self.satir_cerceve.grid(row=1, column=0, sticky="nsew")

        neden_fr = tk.Frame(sag, bg=KOYU_GRI)
        neden_fr.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        neden_fr.columnconfigure(1, weight=1)
        tk.Label(neden_fr, text="Neden *", bg=KOYU_GRI, fg=SARİ).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.neden = ttk.Combobox(
            neden_fr, values=list(IPTAL_NEDENLERI), state="readonly", width=28
        )
        self.neden.set(IPTAL_NEDENLERI[0])
        self.neden.grid(row=0, column=1, sticky="ew")
        self.neden.bind("<<ComboboxSelected>>", lambda _e: self._neden_degisti())

        tk.Label(neden_fr, text="Not", bg=KOYU_GRI, fg=BEYAZ).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        self.not_entry = ttk.Entry(neden_fr)
        self.not_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self._neden_degisti()

        # Alt butonlar
        alt = tk.Frame(kok, bg=KOYU_GRI)
        alt.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for i in range(4):
            alt.columnconfigure(i, weight=1)

        tk.Button(
            alt,
            text="Yenile (F5)",
            bg="#555",
            fg=BEYAZ,
            relief="flat",
            command=self._yenile,
            pady=8,
        ).grid(row=0, column=0, sticky="ew", padx=2)

        self.btn_iade = tk.Button(
            alt,
            text="İADE ET (seçili miktar)",
            bg=YESIL,
            fg=BEYAZ,
            relief="flat",
            command=self._iade_et,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        )
        self.btn_iade.grid(row=0, column=1, sticky="ew", padx=2)

        self.btn_iptal = tk.Button(
            alt,
            text="TAM İPTAL",
            bg=KIRMIZI,
            fg=BEYAZ,
            relief="flat",
            command=self._tam_iptal,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        )
        self.btn_iptal.grid(row=0, column=2, sticky="ew", padx=2)

        tk.Button(
            alt,
            text="Kapat",
            bg="#555",
            fg=BEYAZ,
            relief="flat",
            command=self._kapat,
            pady=8,
        ).grid(row=0, column=3, sticky="ew", padx=2)

    def _neden_degisti(self) -> None:
        if self.neden.get() == "Diğer":
            self.not_entry.focus_set()

    def _neden_metin(self) -> str:
        neden = (self.neden.get() or "").strip()
        notu = (self.not_entry.get() or "").strip()
        if neden == "Diğer":
            if not notu:
                raise ValueError("«Diğer» seçildiğinde not zorunludur.")
            return notu
        if notu:
            return f"{neden} — {notu}"
        return neden

    def _agac_odak(self) -> None:
        try:
            self.agac.focus_set()
        except tk.TclError:
            pass

    def _yenile(self) -> None:
        try:
            self._liste = HizliSatisService.list_recent_hizli_satislar(
                sadece_bugun=True, limit=80
            )
            if not self._liste:
                self._liste = HizliSatisService.list_recent_hizli_satislar(
                    sadece_bugun=False, gun=7, limit=80
                )
        except Exception as hata:
            messagebox.showerror("Liste", str(hata), parent=self)
            self._liste = []

        for iid in self.agac.get_children():
            self.agac.delete(iid)
        for kayit in self._liste:
            self.agac.insert(
                "",
                "end",
                iid=str(kayit["fatura_id"]),
                values=(
                    kayit.get("fatura_no") or "",
                    kayit.get("islem_saati") or "",
                    kayit.get("musteri") or "",
                    _para(kayit.get("genel_toplam")),
                    kayit.get("durum") or "",
                ),
            )

        hedef = None
        if self.pref_fatura_id and self.agac.exists(str(self.pref_fatura_id)):
            hedef = str(self.pref_fatura_id)
        elif self._liste:
            hedef = str(self._liste[0]["fatura_id"])
        if hedef:
            self.agac.selection_set(hedef)
            self.agac.see(hedef)
            self._secim_degisti()
        else:
            self._ozet = None
            self._satirlari_ciz([])
            self.ozet_lbl.configure(text="Kayıt yok")

    def _secili_fatura_id(self) -> int | None:
        sec = self.agac.selection()
        if not sec:
            return None
        try:
            return int(sec[0])
        except (TypeError, ValueError):
            return None

    def _secim_degisti(self) -> None:
        fid = self._secili_fatura_id()
        if not fid:
            return
        try:
            self._ozet = HizliSatisService.fatura_iade_ozeti(fid)
        except Exception as hata:
            messagebox.showerror("Fatura", str(hata), parent=self)
            self._ozet = None
            self._satirlari_ciz([])
            return

        o = self._ozet
        ekstra = ""
        if o.get("onceki_iade_var"):
            ekstra = f" · önceki iade: {o.get('onceki_iade_sayisi')}"
        self.ozet_lbl.configure(
            text=(
                f"{o.get('fatura_no')} — {o.get('musteri')} — "
                f"{_tarih_metin(o.get('fatura_tarihi'))} — {_para(o.get('genel_toplam'))}"
                f"{ekstra}"
            )
        )
        self._satirlari_ciz(o.get("satirlar") or [])
        try:
            self.btn_iptal.configure(
                state="normal" if o.get("tam_iptal_uygun") else "disabled"
            )
        except tk.TclError:
            pass

    def _satirlari_ciz(self, satirlar: list[dict]) -> None:
        for w in self.satir_cerceve.winfo_children():
            w.destroy()
        self._satir_miktar.clear()

        baslik = tk.Frame(self.satir_cerceve, bg=ACIK_GRI)
        baslik.pack(fill="x", padx=4, pady=4)
        for i, t in enumerate(("Ürün", "Satılan", "Kalan", "İade miktarı")):
            tk.Label(baslik, text=t, bg=ACIK_GRI, font=("Segoe UI", 8, "bold")).grid(
                row=0, column=i, sticky="w", padx=4
            )

        if not satirlar:
            tk.Label(
                self.satir_cerceve,
                text="Satır yok",
                bg=ACIK_GRI,
                fg="#666",
            ).pack(anchor="w", padx=8, pady=8)
            return

        for s in satirlar:
            sid = int(s["satir_id"])
            kalan = Decimal(str(s.get("kalan_iadeye_uygun") or 0))
            fr = tk.Frame(self.satir_cerceve, bg=ACIK_GRI)
            fr.pack(fill="x", padx=4, pady=2)
            tk.Label(
                fr,
                text=f"{s.get('urun_kodu')} — {s.get('urun_adi')}",
                bg=ACIK_GRI,
                anchor="w",
                width=28,
            ).grid(row=0, column=0, sticky="w", padx=4)
            tk.Label(fr, text=_miktar_goster(s.get("miktar")), bg=ACIK_GRI, width=8).grid(
                row=0, column=1, padx=4
            )
            tk.Label(fr, text=_miktar_goster(kalan), bg=ACIK_GRI, width=8).grid(
                row=0, column=2, padx=4
            )
            var = tk.StringVar(value=_miktar_goster(kalan) if kalan > 0 else "0")
            ent = ttk.Entry(fr, textvariable=var, width=10)
            ent.grid(row=0, column=3, padx=4)
            if kalan <= 0:
                ent.configure(state="disabled")
            self._satir_miktar[sid] = var

    def _iade_satirlari_oku(self) -> list[dict[str, Any]]:
        if not self._ozet:
            raise ValueError("Önce bir fatura seçin.")
        sonuc = []
        for sid, var in self._satir_miktar.items():
            ham = (var.get() or "0").strip().replace(",", ".")
            try:
                miktar = Decimal(ham)
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Geçersiz miktar: {ham}") from exc
            if miktar <= 0:
                continue
            sonuc.append({"satir_id": sid, "miktar": miktar})
        if not sonuc:
            raise ValueError("İade için en az bir satırda miktar girin.")
        return sonuc

    def _tam_iptal(self) -> None:
        fid = self._secili_fatura_id()
        if not fid:
            messagebox.showwarning("Seçim", "İptal edilecek faturayı seçin.", parent=self)
            return
        if self._ozet and not self._ozet.get("tam_iptal_uygun"):
            messagebox.showwarning(
                "Tam iptal",
                "Bu fatura için tam iptal uygun değil (önceki iade var).\n"
                "Kalan miktar için «İade Et» kullanın.",
                parent=self,
            )
            return
        try:
            neden = self._neden_metin()
        except ValueError as hata:
            messagebox.showwarning("Neden", str(hata), parent=self)
            return

        fno = (self._ozet or {}).get("fatura_no") or fid
        if not messagebox.askyesno(
            "Tam iptal",
            f"{fno} numaralı hızlı satış iptal edilsin mi?\n"
            "Stok ve kasa tahsilatı geri alınır (kayıt silinmez).",
            parent=self,
        ):
            return

        try:
            sonuc = HizliSatisService.satisi_iptal(fid, neden=neden)
        except AccessError as hata:
            messagebox.showerror("Yetki", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return

        self.result = sonuc
        messagebox.showinfo(
            "İptal edildi",
            f"{sonuc.get('fatura_no')} iptal edildi.\n{sonuc.get('uyari') or ''}",
            parent=self,
        )
        if self.on_basari:
            try:
                self.on_basari(sonuc)
            except Exception:
                pass
        self._yenile()

    def _iade_et(self) -> None:
        fid = self._secili_fatura_id()
        if not fid:
            messagebox.showwarning("Seçim", "İade edilecek faturayı seçin.", parent=self)
            return
        try:
            neden = self._neden_metin()
            satirlar = self._iade_satirlari_oku()
        except ValueError as hata:
            messagebox.showwarning("İade", str(hata), parent=self)
            return

        if not messagebox.askyesno(
            "İade",
            f"{len(satirlar)} satır iade edilsin mi?\n"
            "Stok girişi ve (varsa) kasa iade ödemesi oluşur.",
            parent=self,
        ):
            return

        try:
            sonuc = HizliSatisService.satisi_iade(
                fid, satirlar=satirlar, neden=neden
            )
        except AccessError as hata:
            messagebox.showerror("Yetki", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("İade", str(hata), parent=self)
            return

        self.result = sonuc
        messagebox.showinfo(
            "İade kaydedildi",
            (
                f"İade: {sonuc.get('iade_no')}\n"
                f"Tutar: {_para(sonuc.get('genel_toplam'))}\n"
                f"{sonuc.get('uyari') or ''}"
            ),
            parent=self,
        )
        if self.on_basari:
            try:
                self.on_basari(sonuc)
            except Exception:
                pass
        self._yenile()

    def _kapat(self) -> None:
        self.destroy()
