"""Satış sipariş formu çıktı işlemleri — kart ve liste ortak (Önizleme, Yazdır, PDF, Word).

Çıktı her zaman kayıtlı siparişten üretilir; kaydedilmemiş değişiklik kontrolü çağıran
ekranın sorumluluğundadır. Çıktı almak sipariş, stok veya cari kaydı değiştirmez.
"""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox

from irsaliye_cikti_ui import _hata, _mesgul, yazici_sec

ISLEMLER = ("onizleme", "yazdir", "pdf", "word")


def kayit_yeri_sor(parent, oneri: str, uzanti: str) -> str | None:
    tur = {"pdf": ("PDF belgesi", "*.pdf"), "docx": ("Word belgesi", "*.docx")}[uzanti]
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title=f"Sipariş formunu {tur[0]} olarak kaydet",
        defaultextension=f".{uzanti}",
        filetypes=[tur],
        initialfile=oneri,
        confirmoverwrite=True,
    )
    return yol or None


def cikti_al(parent, siparis_id: int, islem: str) -> Path | None:
    """Kayıtlı siparişten çıktı üretir. Dönüş: oluşan dosya (vazgeçilirse/hata olursa None)."""
    from invoice_print import siparis_cikti as sc

    basliklar = {"onizleme": "Önizleme", "yazdir": "Yazdırma", "pdf": "PDF kaydetme", "word": "Word kaydetme"}
    baslik = basliklar[islem]
    try:
        _mesgul(parent, True)
        vm = sc.cikti_modeli(siparis_id)
        if not vm.satirlar:
            raise ValueError("Siparişte ürün satırı yok; çıktı alınamaz.")
        if islem == "onizleme":
            pdf = sc.gecici_pdf(vm)
            os.startfile(str(pdf))  # noqa: S606 — varsayılan PDF görüntüleyici
            return pdf
        if islem == "yazdir":
            pdf = sc.gecici_pdf(vm)
            _mesgul(parent, False)
            yazici = yazici_sec(parent, f"{vm.belge_baslik} {vm.siparis_no}")
            if not yazici:
                return None
            from invoice_print.yazici import pdf_yazdir

            _mesgul(parent, True)
            sayfa = pdf_yazdir(pdf, yazici, belge_adi=f"{vm.belge_baslik} {vm.siparis_no}")
            _mesgul(parent, False)
            messagebox.showinfo("Yazdır", f"{sayfa} sayfa «{yazici}» yazıcısına gönderildi.", parent=parent)
            return pdf
        uzanti = "pdf" if islem == "pdf" else "docx"
        _mesgul(parent, False)
        yol = kayit_yeri_sor(parent, sc.varsayilan_dosya_adi(vm, uzanti), uzanti)
        if not yol:
            return None
        _mesgul(parent, True)
        hedef = sc.pdf_olustur(vm, Path(yol)) if uzanti == "pdf" else sc.docx_olustur(vm, Path(yol))
        _mesgul(parent, False)
        messagebox.showinfo(baslik, f"Sipariş formu kaydedildi:\n{hedef}", parent=parent)
        return hedef
    except Exception as hata:  # noqa: BLE001 — kullanıcıya mesaj, ayrıntı günlüğe
        _mesgul(parent, False)
        _hata(parent, baslik, hata, f"Sipariş çıktısı ({islem}) siparis_id={siparis_id}")
        return None
    finally:
        _mesgul(parent, False)
