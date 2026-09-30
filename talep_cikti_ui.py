"""Satın alma talep formu çıktı işlemleri (Önizleme, Yazdır, PDF, Word).

Çıktı her zaman kayıtlı talepten üretilir; çıktı almak talep kaydını değiştirmez.
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
        title=f"Talep formunu {tur[0]} olarak kaydet",
        defaultextension=f".{uzanti}",
        filetypes=[tur],
        initialfile=oneri,
        confirmoverwrite=True,
    )
    return yol or None


def fiyatli_mi(parent) -> bool:
    from database.access import yetki_var

    if not yetki_var("alis_talep_fiyat_gorme", "maliyet_gorma"):
        return False
    return bool(messagebox.askyesno("Talep Çıktısı", "Tahmini fiyatlar çıktıda gösterilsin mi?", parent=parent))


def cikti_al(parent, talep_id: int, islem: str, fiyatli: bool | None = None,
             hedef: str | Path | None = None, yazici: str | None = None) -> Path | None:
    """Kayıtlı talepten çıktı üretir. Dönüş: oluşan dosya (vazgeçilirse/hata olursa None)."""
    from invoice_print import talep_cikti as tc

    basliklar = {"onizleme": "Önizleme", "yazdir": "Yazdırma", "pdf": "PDF kaydetme", "word": "Word kaydetme"}
    baslik = basliklar[islem]
    try:
        if fiyatli is None:
            fiyatli = fiyatli_mi(parent)
        _mesgul(parent, True)
        vm = tc.cikti_modeli(talep_id, fiyatli=fiyatli)
        if not vm.satirlar:
            raise ValueError("Talepte ürün satırı yok; çıktı alınamaz.")
        if islem == "onizleme":
            pdf = tc.gecici_pdf(vm)
            os.startfile(str(pdf))  # noqa: S606 — varsayılan PDF görüntüleyici
            return pdf
        if islem == "yazdir":
            pdf = tc.gecici_pdf(vm)
            _mesgul(parent, False)
            yazici = yazici or yazici_sec(parent, f"{vm.belge_baslik} {vm.talep_no}")
            if not yazici:
                return None
            from invoice_print.yazici import pdf_yazdir

            _mesgul(parent, True)
            sayfa = pdf_yazdir(pdf, yazici, belge_adi=f"{vm.belge_baslik} {vm.talep_no}")
            _mesgul(parent, False)
            messagebox.showinfo("Yazdır", f"{sayfa} sayfa «{yazici}» yazıcısına gönderildi.", parent=parent)
            return pdf
        uzanti = "pdf" if islem == "pdf" else "docx"
        _mesgul(parent, False)
        yol = hedef or kayit_yeri_sor(parent, tc.varsayilan_dosya_adi(vm, uzanti), uzanti)
        if not yol:
            return None
        _mesgul(parent, True)
        sonuc = tc.pdf_olustur(vm, Path(yol)) if uzanti == "pdf" else tc.docx_olustur(vm, Path(yol))
        _mesgul(parent, False)
        if hedef is None:
            messagebox.showinfo(baslik, f"Talep formu kaydedildi:\n{sonuc}", parent=parent)
        return sonuc
    except Exception as hata:  # noqa: BLE001 — kullanıcıya mesaj, ayrıntı günlüğe
        _mesgul(parent, False)
        _hata(parent, baslik, hata, f"Talep çıktısı ({islem}) talep_id={talep_id}")
        return None
    finally:
        _mesgul(parent, False)
