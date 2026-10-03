"""Tanımsız birim hatası: mesaj + 'Stok Kartını Aç' seçeneği (ilgili kartın «Barkod & Birimler» sekmesi)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from database.stok_service import BirimDonusumHatasi


def birim_hatasi_bul(hata: BaseException | None) -> BirimDonusumHatasi | None:
    """Hata zincirinde (sarılmış ValueError dahil) tanımsız birim hatası varsa onu döner."""
    gorulen: set[int] = set()
    while hata is not None and id(hata) not in gorulen:
        if isinstance(hata, BirimDonusumHatasi):
            return hata
        gorulen.add(id(hata))
        hata = hata.__cause__ or hata.__context__
    return None


def stok_karti_birimler_ac(parent, stok_kodu: str):
    """Stok kartını «Barkod & Birimler» sekmesi seçili açar; kart yoksa bilgi verir."""
    from database.models.stok import StokKarti
    from database.database import get_session
    from database.stok_service import StokService
    from sqlalchemy import select

    with get_session() as s:
        stok_id = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == (stok_kodu or "").strip()))
    stok = StokService.stok_getir(int(stok_id)) if stok_id else None
    if stok is None:
        messagebox.showinfo("Stok kartı", f"{stok_kodu} kodlu stok kartı bulunamadı.", parent=parent)
        return None
    from stok_ui import StokKartiDialog

    dlg = StokKartiDialog(parent, stok=stok)
    try:
        for sekme in dlg.sekmeler.tabs():
            if "Birimler" in str(dlg.sekmeler.tab(sekme, "text")):
                dlg.sekmeler.select(sekme)
                break
    except (tk.TclError, AttributeError):
        pass
    return dlg


def birim_hatasi_goster(parent, hata: BaseException, baslik: str = "Tanımsız birim") -> bool:
    """Tanımsız birim hatasıysa gösterir (kart açma seçeneğiyle) ve True döner; değilse False."""
    bh = birim_hatasi_bul(hata)
    if bh is None:
        return False
    kodlar = [k for k in getattr(bh, "urun_kodlari", []) if k]
    mesaj = str(hata)
    if not kodlar:
        messagebox.showerror(baslik, mesaj, parent=parent)
        return True
    if messagebox.askyesno(
            baslik, f"{mesaj}\n\n«{kodlar[0]}» stok kartı «Barkod & Birimler» sekmesinde açılsın mı?",
            icon="warning", parent=parent):
        stok_karti_birimler_ac(parent, kodlar[0])
    return True
