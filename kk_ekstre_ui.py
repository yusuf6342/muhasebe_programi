"""Kredi kartı ekstre detay ve ödeme pencereleri — Aylara Göre Ödeme Durumu."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk


def _para(tutar) -> str:
    return (
        f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        + " TL"
    )


def _tarih(d) -> str:
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d or "")


class KkEkstreDetayDialog(tk.Toplevel):
    """Ekstre ana satır detayı + ödeme butonları."""

    def __init__(self, parent, satir: dict, *, yenile_cb=None):
        super().__init__(parent)
        self.satir = satir
        self.yenile_cb = yenile_cb
        self.title("Kredi Kartı Ekstre Detayı")
        self.geometry("820x520")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            if satir.get("ekstre_id"):
                self.detay = KrediKartiEkstreService.ekstre_detay(int(satir["ekstre_id"]))
            else:
                self.detay = KrediKartiEkstreService.ekstre_detay(
                    source_id=str(satir.get("source_id") or "")
                )
        except Exception as exc:
            messagebox.showerror("Ekstre", str(exc), parent=self)
            self.destroy()
            return

        ust = ttk.Frame(self)
        ust.pack(fill="x", padx=10, pady=8)
        ttk.Label(
            ust,
            text=self.detay.get("aciklama") or "Ekstre",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            ust,
            text=(
                f"Son ödeme: {_tarih(self.detay.get('son_odeme_tarihi'))}  ·  "
                f"Kesim: {_tarih(self.detay.get('kesim_tarihi'))}  ·  "
                f"Dönem: {_tarih(self.detay.get('donem_baslangic'))}–"
                f"{_tarih(self.detay.get('donem_bitis'))}"
            ),
        ).pack(anchor="w")
        ttk.Label(
            ust,
            text=(
                f"Toplam: {_para(self.detay.get('tl_tutar'))}  ·  "
                f"Ödenen: {_para(self.detay.get('odenen'))}  ·  "
                f"Kalan: {_para(self.detay.get('kalan'))}  ·  "
                f"{self.detay.get('ekstre_durum') or self.detay.get('durum')}"
            ),
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(4, 0))

        btn = ttk.Frame(self)
        btn.pack(fill="x", padx=10, pady=4)
        ttk.Button(btn, text="Ödeme Yap", command=self._odeme).pack(side="left", padx=2)
        ttk.Button(btn, text="Kısmi Ödeme", command=self._kismi).pack(side="left", padx=2)
        ttk.Button(btn, text="Tamamını Öde", command=self._tamami).pack(side="left", padx=2)
        ttk.Button(btn, text="Yenile", command=self._yenile_detay).pack(side="left", padx=2)
        ttk.Button(btn, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        cols = ("tarih", "aciklama", "tur", "taksit", "borc", "alacak", "etki", "belge")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=14)
        basliklar = (
            ("tarih", "İşlem tarihi", 90),
            ("aciklama", "Açıklama", 200),
            ("tur", "Tür", 90),
            ("taksit", "Taksit", 90),
            ("borc", "Borç", 90),
            ("alacak", "Alacak", 90),
            ("etki", "Etki", 90),
            ("belge", "Evrak", 110),
        )
        for k, b, w in basliklar:
            self.tv.heading(k, text=b)
            self.tv.column(k, width=w, anchor="center" if k != "aciklama" else "w")
        self.tv.pack(fill="both", expand=True, padx=10, pady=6)
        self._doldur()

    def _doldur(self):
        for i in self.tv.get_children():
            self.tv.delete(i)
        for s in self.detay.get("detay_satirlari") or []:
            self.tv.insert(
                "",
                "end",
                values=(
                    _tarih(s.get("islem_tarihi")),
                    s.get("aciklama") or "",
                    s.get("islem_turu") or "",
                    s.get("tek_cekim_taksit") or "",
                    _para(s.get("borc")),
                    _para(s.get("alacak")),
                    _para(s.get("etki")),
                    s.get("kaynak_evrak") or "",
                ),
            )

    def _yenile_detay(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            self.detay = KrediKartiEkstreService.ekstre_detay(int(self.detay["ekstre_id"]))
            self._doldur()
            if self.yenile_cb:
                self.yenile_cb()
        except Exception as exc:
            messagebox.showerror("Ekstre", str(exc), parent=self)

    def _odeme(self):
        KkEkstreOdemeDialog(
            self, self.detay, tamami=False, yenile_cb=self._sonra_yenile
        )

    def _kismi(self):
        self._odeme()

    def _tamami(self):
        KkEkstreOdemeDialog(
            self, self.detay, tamami=True, yenile_cb=self._sonra_yenile
        )

    def _sonra_yenile(self):
        self._yenile_detay()


class KkEkstreOdemeDialog(tk.Toplevel):
    """Ekstre ödeme — banka çıkışı oluşturur."""

    def __init__(self, parent, detay: dict, *, tamami: bool = False, yenile_cb=None):
        super().__init__(parent)
        self.detay = detay
        self.tamami = tamami
        self.yenile_cb = yenile_cb
        self.title("Ekstre Ödeme")
        self.geometry("420x320")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        kalan = Decimal(str(detay.get("kalan") or 0))
        ttk.Label(self, text=detay.get("aciklama") or "", wraplength=380).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        ttk.Label(self, text=f"Kalan borç: {_para(kalan)}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12
        )

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=12, pady=8)
        ttk.Label(frm, text="Ödeme tarihi").grid(row=0, column=0, sticky="w", pady=3)
        self.tarih = ttk.Entry(frm, width=14)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Tutar").grid(row=1, column=0, sticky="w", pady=3)
        self.tutar = ttk.Entry(frm, width=14)
        self.tutar.insert(0, f"{kalan:.2f}".replace(".", ","))
        self.tutar.grid(row=1, column=1, sticky="w", pady=3)
        if tamami:
            self.tutar.configure(state="readonly")

        ttk.Label(frm, text="Dekont no").grid(row=2, column=0, sticky="w", pady=3)
        self.dekont = ttk.Entry(frm, width=20)
        self.dekont.grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Açıklama").grid(row=3, column=0, sticky="w", pady=3)
        self.aciklama = ttk.Entry(frm, width=32)
        self.aciklama.grid(row=3, column=1, sticky="w", pady=3)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="İptal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Kaydet", command=self._kaydet).pack(side="right", padx=4)

    def _kaydet(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            t_raw = self.tarih.get().strip()
            gun, ay, yil = t_raw.replace("/", ".").split(".")
            tarih = date(int(yil), int(ay), int(gun))
        except Exception:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY formatında olmalıdır.", parent=self)
            return
        try:
            sonuc = KrediKartiEkstreService.odeme_yap(
                ekstre_id=int(self.detay["ekstre_id"]),
                tutar=self.tutar.get(),
                tarih=tarih,
                dekont_no=self.dekont.get(),
                aciklama=self.aciklama.get(),
                tamami=self.tamami,
            )
            messagebox.showinfo(
                "Ödeme",
                f"Ödeme kaydedildi: {sonuc['belge_no']}\nTutar: {_para(sonuc['tutar'])}",
                parent=self,
            )
            if self.yenile_cb:
                self.yenile_cb()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Ödeme", str(exc), parent=self)
