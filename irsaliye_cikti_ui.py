"""Satış irsaliyesi çıktı işlemleri — ekran ve liste ortak (Önizleme, Yazdır, PDF, Word).

Çıktı her zaman kayıtlı irsaliyeden üretilir; kaydedilmemiş değişiklik kontrolü
çağıran ekranın sorumluluğundadır. Çıktı almak stok, cari veya sipariş kaydı değiştirmez.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from satis_tema import BEYAZ, LACIVERT, SARI, font, tk_buton

ISLEMLER = ("onizleme", "yazdir", "pdf", "word")


def _hata(parent, baslik: str, hata: BaseException, baglam: str) -> None:
    from uygulama_log import hata_yaz

    if isinstance(hata, ValueError):
        messagebox.showerror(baslik, str(hata), parent=parent)
        return
    yol = hata_yaz(baglam, hata)
    ek = f"\n\nTeknik ayrıntı günlüğe kaydedildi:\n{yol}" if yol else ""
    messagebox.showerror(baslik, f"{baslik} tamamlanamadı: {hata}{ek}", parent=parent)


def _mesgul(parent, aktif: bool) -> None:
    try:
        parent.configure(cursor="watch" if aktif else "")
        parent.update_idletasks()
    except tk.TclError:
        pass


class YaziciSecDialog(tk.Toplevel):
    """Yazıcı seçimi — varsayılan yazıcı önseçili. ``sonuc``: yazıcı adı veya None."""

    def __init__(self, parent, yazicilar: list[str], varsayilan: str | None, belge: str):
        super().__init__(parent)
        self.sonuc: str | None = None
        self.title("Yazdır")
        self.configure(bg=BEYAZ)
        self.resizable(False, False)
        self.transient(parent)
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(ust, text="Yazıcı seçin", bg=LACIVERT, fg=BEYAZ, font=font(11, "bold", self), padx=12, pady=8).pack(anchor="w")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        govde = tk.Frame(self, bg=BEYAZ, padx=14, pady=10)
        govde.pack(fill="both")
        tk.Label(govde, text=belge, bg=BEYAZ, anchor="w", font=font(10, root=self)).pack(fill="x")
        tk.Label(govde, text="A4 dikey, gerçek boyut", bg=BEYAZ, fg="#627D98", anchor="w").pack(fill="x", pady=(0, 6))
        self.secim = ttk.Combobox(govde, values=yazicilar, state="readonly", width=46)
        self.secim.pack(fill="x")
        if varsayilan in yazicilar:
            self.secim.set(varsayilan)
        elif yazicilar:
            self.secim.set(yazicilar[0])
        alt = tk.Frame(govde, bg=BEYAZ)
        alt.pack(fill="x", pady=(10, 0))
        tk_buton(alt, "Yazdır", self._tamam, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._tamam())
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=420, yukseklik=200)
        except Exception:
            pass
        self.grab_set()
        self.secim.focus_set()

    def _tamam(self):
        self.sonuc = self.secim.get() or None
        self.destroy()


def yazici_sec(parent, belge: str) -> str | None:
    from invoice_print.yazici import varsayilan_yazici, yazicilar

    liste = yazicilar()
    if not liste:
        raise ValueError("Bu bilgisayarda tanımlı yazıcı bulunamadı.")
    dialog = YaziciSecDialog(parent, liste, varsayilan_yazici(), belge)
    parent.wait_window(dialog)
    return dialog.sonuc


def kayit_yeri_sor(parent, oneri: str, uzanti: str) -> str | None:
    tur = {"pdf": ("PDF belgesi", "*.pdf"), "docx": ("Word belgesi", "*.docx")}[uzanti]
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title=f"İrsaliyeyi {tur[0]} olarak kaydet",
        defaultextension=f".{uzanti}",
        filetypes=[tur],
        initialfile=oneri,
        confirmoverwrite=True,
    )
    return yol or None


def cikti_al(parent, irsaliye_id: int, islem: str, *, fiyatli: bool = False) -> Path | None:
    """Kayıtlı irsaliyeden çıktı üretir. Dönüş: oluşan dosya (vazgeçilirse/hata olursa None)."""
    from invoice_print import irsaliye_cikti as ic

    basliklar = {"onizleme": "Önizleme", "yazdir": "Yazdırma", "pdf": "PDF kaydetme", "word": "Word kaydetme"}
    baslik = basliklar[islem]
    try:
        _mesgul(parent, True)
        vm = ic.cikti_modeli(irsaliye_id, fiyatli=fiyatli)
        if not vm.satirlar:
            raise ValueError("İrsaliyede ürün satırı yok; çıktı alınamaz.")
        if islem == "onizleme":
            pdf = ic.gecici_pdf(vm)
            os.startfile(str(pdf))  # noqa: S606 — varsayılan PDF görüntüleyici
            return pdf
        if islem == "yazdir":
            pdf = ic.gecici_pdf(vm)
            _mesgul(parent, False)
            yazici = yazici_sec(parent, f"{vm.belge_baslik} {vm.irsaliye_no}")
            if not yazici:
                return None
            from invoice_print.yazici import pdf_yazdir

            _mesgul(parent, True)
            sayfa = pdf_yazdir(pdf, yazici, belge_adi=f"{vm.belge_baslik} {vm.irsaliye_no}")
            _mesgul(parent, False)
            messagebox.showinfo("Yazdır", f"{sayfa} sayfa «{yazici}» yazıcısına gönderildi.", parent=parent)
            return pdf
        uzanti = "pdf" if islem == "pdf" else "docx"
        _mesgul(parent, False)
        yol = kayit_yeri_sor(parent, ic.varsayilan_dosya_adi(vm, uzanti), uzanti)
        if not yol:
            return None
        _mesgul(parent, True)
        hedef = ic.pdf_olustur(vm, Path(yol)) if uzanti == "pdf" else ic.docx_olustur(vm, Path(yol))
        _mesgul(parent, False)
        messagebox.showinfo(baslik, f"İrsaliye kaydedildi:\n{hedef}", parent=parent)
        return hedef
    except Exception as hata:  # noqa: BLE001 — kullanıcıya mesaj, ayrıntı günlüğe
        _mesgul(parent, False)
        _hata(parent, baslik, hata, f"İrsaliye çıktısı ({islem}) irsaliye_id={irsaliye_id}")
        return None
    finally:
        _mesgul(parent, False)
