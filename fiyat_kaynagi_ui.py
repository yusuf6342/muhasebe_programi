"""Alış evraklarında otomatik fiyatın kaynağı, elle fiyat koruması ve bilgi notu.

Fiyatı ``database.fiyat_kaynagi_service`` bulur; bu modül yalnız evrak penceresinden
bağlamı (tedarikçi, tarih, para birimi, kur) okur ve satır üzerinde kalıcı olmayan
``fiyat_kaynagi`` / ``fiyat_uyari`` / ``fiyat_elle`` anahtarlarını yönetir.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from tkinter import messagebox

from database.fiyat_kaynagi_service import FiyatSonucu, son_alis_fiyati_getir

NOT_RENK = "#1F3A5F"
UYARI_RENK = "#9C2A00"


def _tarih_oku(metin) -> date | None:
    try:
        return datetime.strptime((metin or "").strip(), "%d.%m.%Y").date()
    except (ValueError, AttributeError):
        return None


def belge_tarihi(dialog) -> date:
    girdiler = getattr(dialog, "girdiler", None) or {}
    for alan in ("fatura_tarihi", "siparis_tarihi", "iade_tarihi", "teklif_tarihi", "talep_tarihi"):
        w = girdiler.get(alan)
        if w is not None:
            try:
                t = _tarih_oku(w.get())
            except tk.TclError:
                t = None
            if t:
                return t
    w = getattr(dialog, "tarih", None)
    if w is not None and hasattr(w, "get"):
        try:
            t = _tarih_oku(w.get())
        except tk.TclError:
            t = None
        if t:
            return t
    return date.today()


def belge_tedarikcisi(dialog):
    """Belgenin cari kartı (id ile eşleştirme için); seçili değilse None."""
    harita = getattr(dialog, "tedarikci_map", None)
    deger = getattr(dialog, "tedarikci", None)
    if isinstance(harita, dict) and deger is not None and hasattr(deger, "get"):
        try:
            cari = harita.get(deger.get())
        except tk.TclError:
            cari = None
        if cari is not None:
            return cari
    for ad in ("_secili_tedarikci", "_secili_cari"):
        fn = getattr(dialog, ad, None)
        if callable(fn):
            try:
                cari = fn()
            except Exception:
                cari = None
            if cari is not None:
                return cari
    return None


def belge_para_birimi(dialog) -> tuple[str, Decimal | None]:
    """(para birimi, kur); TL belgede kur 1. Kur okunamazsa None (tahmin edilmez)."""
    pb_var = getattr(dialog, "_doviz_para_birimi", None)
    try:
        pb = ((pb_var.get() if pb_var is not None else "") or "TRY").strip().upper()
    except tk.TclError:
        pb = "TRY"
    if pb in ("TL", "TRY", ""):
        return "TRY", Decimal("1")
    kur_var = getattr(dialog, "_doviz_kur", None)
    try:
        kur = Decimal(str(kur_var.get()).replace(",", ".")) if kur_var is not None else None
    except (InvalidOperation, ValueError, tk.TclError):
        kur = None
    if kur is not None and kur <= 0:
        kur = None
    return pb, kur


def alis_fiyati_coz(dialog, urun_kodu: str, birim: str, kdv_orani=None) -> FiyatSonucu:
    cari = belge_tedarikcisi(dialog)
    pb, kur = belge_para_birimi(dialog)
    fatura = getattr(dialog, "fatura", None)
    haric = getattr(fatura, "id", None) if fatura is not None and hasattr(dialog, "_alis_fatura_satiri") else None
    try:
        return son_alis_fiyati_getir(
            urun_kodu,
            birim,
            cari_id=getattr(cari, "id", None),
            belge_tarihi=belge_tarihi(dialog),
            belge_pb=pb,
            belge_kur=kur,
            haric_fatura_id=haric,
            kdv_orani=kdv_orani,
        )
    except Exception as hata:  # noqa: BLE001 — fiyat bulunamaması satır eklemeyi engellemez
        return FiyatSonucu(None, uyari=f"Fiyat okunamadı: {hata}")


def sonucu_satira_yaz(satir: dict, sonuc: FiyatSonucu) -> dict:
    satir["fiyat_elle"] = False
    if sonuc.fiyat is None:
        satir["fiyat_kaynagi"] = sonuc.aciklama or "Fiyat bulunamadı; birim fiyatı girin."
    else:
        satir["fiyat_kaynagi"] = sonuc.aciklama
    satir["fiyat_uyari"] = sonuc.uyari or ("Fiyat bulunamadı; birim fiyatı girin." if sonuc.fiyat is None else "")
    return satir


def elle_isaretle(satir: dict) -> dict:
    satir["fiyat_elle"] = True
    satir["fiyat_kaynagi"] = "Elle girilen fiyat"
    satir["fiyat_uyari"] = ""
    return satir


def elle_fiyat_mi(satir: dict) -> bool:
    return bool(satir.get("fiyat_elle"))


def birim_degisiminde_yeniden_fiyat(dialog, satir: dict) -> bool | None:
    """Elle fiyatlı satırda birim değişince sor: True yeniden getir, False koru, None vazgeç."""
    if not elle_fiyat_mi(satir):
        return True
    return messagebox.askyesnocancel(
        "Elle girilmiş fiyat",
        "Bu satırın fiyatı elle girilmiş.\n\n"
        "Evet: Yeni birim için fiyatı yeniden getir\n"
        "Hayır: Girilen fiyatı koru\n"
        "İptal: Birim değişikliğinden vazgeç",
        parent=dialog,
    )


def yenileme_onayi(dialog, satir: dict) -> bool:
    if not elle_fiyat_mi(satir):
        return True
    return messagebox.askyesno(
        "Fiyatı Yenile",
        "Bu satırın fiyatı elle girilmiş. Otomatik fiyatla değiştirilsin mi?",
        parent=dialog,
    )


def fiyat_yok_bildir(dialog, urun_kodu: str, metin: str | None = None) -> None:
    """Fiyatı bulunamayan ürün için bir kez, pencereyi kilitlemeyen kısa bildirim."""
    bildirilen = getattr(dialog, "_fiyat_yok_bildirilen", None)
    if bildirilen is None:
        bildirilen = set()
        try:
            dialog._fiyat_yok_bildirilen = bildirilen
        except Exception:
            return
    kod = (urun_kodu or "").strip()
    if not kod or kod in bildirilen:
        return
    bildirilen.add(kod)
    bildirim_goster(dialog, metin or f"{kod}: geçerli fiyat bulunamadı; birim fiyatı girin.")


def bildirim_goster(dialog, metin: str, sure_ms: int = 4500) -> None:
    try:
        ust = dialog.winfo_toplevel()
        pen = tk.Toplevel(ust)
        pen.overrideredirect(True)
        pen.attributes("-topmost", True)
        tk.Label(
            pen, text=metin, font=("Segoe UI", 9, "bold"), bg="#FFF4CE", fg=UYARI_RENK,
            bd=1, relief="solid", padx=10, pady=6, wraplength=420, justify="left",
        ).pack()
        pen.update_idletasks()
        x = ust.winfo_rootx() + max(10, ust.winfo_width() - pen.winfo_reqwidth() - 20)
        y = ust.winfo_rooty() + max(10, ust.winfo_height() - pen.winfo_reqheight() - 60)
        pen.geometry(f"+{x}+{y}")
        pen.after(sure_ms, lambda: pen.winfo_exists() and pen.destroy())
        pen.bind("<Button-1>", lambda _e: pen.destroy())
    except (tk.TclError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Bilgi notu (tablonun sağ alt köşesinde küçük etiket)
# ---------------------------------------------------------------------------

def _etiket(dialog, tablo):
    lbl = getattr(dialog, "_fiyat_kaynagi_lbl", None)
    try:
        if lbl is not None and lbl.winfo_exists():
            return lbl
    except tk.TclError:
        pass
    lbl = tk.Label(tablo, text="", font=("Segoe UI", 8), bg="#FFF8DC", fg=NOT_RENK, bd=1, relief="solid", padx=4)
    dialog._fiyat_kaynagi_lbl = lbl
    return lbl


def fiyat_notu_goster(dialog, tablo, satir: dict | None) -> None:
    if tablo is None:
        return
    try:
        lbl = _etiket(dialog, tablo)
    except tk.TclError:
        return
    metin = ""
    uyari = False
    if satir:
        metin = satir.get("fiyat_kaynagi") or ""
        if satir.get("fiyat_uyari"):
            metin = f"{metin} — {satir['fiyat_uyari']}" if metin else satir["fiyat_uyari"]
            uyari = True
    try:
        if not metin:
            lbl.place_forget()
            return
        lbl.configure(text=f"Fiyat: {metin}", fg=UYARI_RENK if uyari else NOT_RENK)
        lbl.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-2)
        lbl.lift()
    except tk.TclError:
        pass


def fiyat_notu_bagla(dialog, tablo, satirlar_getir) -> None:
    """Satır seçilince o satırın fiyat kaynağını göster."""
    from satir_ici_urun_giris import satir_indeksi

    def _secim(_e=None):
        try:
            secim = tablo.selection()
            idx = satir_indeksi(tablo, secim[0]) if secim else None
        except (tk.TclError, Exception):
            idx = None
        satirlar = satirlar_getir() or []
        fiyat_notu_goster(dialog, tablo, satirlar[idx] if idx is not None and 0 <= idx < len(satirlar) else None)

    tablo.bind("<<TreeviewSelect>>", _secim, add="+")
