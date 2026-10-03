"""Evrak ekranlarından muhasebeleştirme durumu ve bağlı fişe erişim (ortak yardımcılar)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


def durum_metni(evrak: str, kaynak_id: int | None) -> str:
    """Pencere başlığı / etiket için kısa metin (ör. "  ·  Muhasebe: Bekliyor"); kayıt yoksa boş."""
    if not kaynak_id:
        return ""
    from database.muhasebelestirme_service import MuhasebelestirmeService

    return MuhasebelestirmeService.baslik_eki(evrak, int(kaynak_id))


def fisi_ac(parent, evrak: str, kaynak_id: int | None) -> None:
    """Bağlı muhasebe fişini açar; fiş yoksa durumu ve nedenini gösterir."""
    if not kaynak_id:
        messagebox.showinfo("Muhasebe fişi", "Önce evrakı kaydedin.", parent=parent)
        return
    from database.muhasebelestirme_service import MuhasebelestirmeService

    try:
        d = MuhasebelestirmeService.belge_durumu(evrak, int(kaynak_id))
    except Exception as hata:
        messagebox.showerror("Muhasebe fişi", str(hata), parent=parent)
        return
    if d.get("fis_id"):
        from genel_muhasebe_ui import FisDialog

        FisDialog(parent, fis_id=int(d["fis_id"]))
        return
    metin = f"Muhasebe durumu: {d['durum']}"
    if d.get("aciklama"):
        metin += f"\n\n{d['aciklama']}"
    if d["durum"] == "Bekliyor":
        metin += "\n\nFiş, Muhasebeleştirilecek Evraklar ekranından oluşturulur."
    messagebox.showinfo("Muhasebe fişi", metin, parent=parent)


def fis_dugmesi(parent, evrak: str, kaynak_id_al, *, metin: str = "Muhasebe Fişi") -> ttk.Button:
    """``kaynak_id_al()`` çağrıldığında evrakın muhasebe kaynak id'sini veren düğme."""
    return ttk.Button(parent, text=metin, command=lambda: fisi_ac(parent.winfo_toplevel(), evrak, kaynak_id_al()))


def cari_islem_kaynagi(islem_id: int | None) -> tuple[str, int] | None:
    """Cari hareket kartından yapılmış tahsilat/ödeme ise (evrak türü, muhasebe kaynak id)."""
    if not islem_id:
        return None
    from database.cari_service import CariService

    k = CariService.tahsilat_odeme_evraki(int(islem_id))
    return (k["evrak_turu"], int(k["kaynak_id"])) if k else None


def belge_no_kaynagi(evrak: str, belge_no: str | None) -> int | None:
    """Kasa/banka virmanı, havale ve cari virman belgesinin muhasebe kaynak id'si (kimlik yoksa None)."""
    if not belge_no:
        return None
    from database.database import get_session
    from database.finans_evrak_kimligi import kimlik_bul

    with get_session() as s:
        k = kimlik_bul(s, evrak, belge_no)
        return int(k.id) if k else None


MUHASEBE_KOLON = ("muhasebe", "Muhasebe", 130)


def toplu_durum(evrak: str, kaynak_idleri) -> dict[int, str]:
    """Liste ekranı: kaynak id → muhasebe durumu (tek toplu sorgu; kayıt yoksa anahtar yok)."""
    from database.muhasebelestirme_service import MuhasebelestirmeService

    return MuhasebelestirmeService.toplu_durum(evrak, kaynak_idleri)


def toplu_durum_belge(evrak: str, belge_nolari) -> dict[str, str]:
    """Belge no ile listelenen finans evrakları: belge no → muhasebe durumu (tek toplu sorgu)."""
    from database.muhasebelestirme_service import MuhasebelestirmeService

    return MuhasebelestirmeService.toplu_durum_belge(evrak, belge_nolari)


def baslik_guncelle(pencere: tk.Misc, temel_baslik: str, evrak: str, kaynak_id: int | None) -> None:
    try:
        pencere.title(temel_baslik + durum_metni(evrak, kaynak_id))
    except (tk.TclError, Exception):
        pass
