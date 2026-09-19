"""Satış faturası — manuel birim fiyat girişi, yetki, maliyet altı kontrol."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.access import yetki_var
from database.session_manager import oturum
from database.stok_service import StokService, decimal


def fiyat_degistirme_yetkisi() -> bool:
    if not oturum.oturum_acik:
        return False
    if (oturum.role_kod or "").upper() == "YONETICI":
        return True
    return yetki_var("satis_fiyat_degistirme", "hizli_satis_fiyat_degistirme")


def maliyet_alti_satis_yasak_mi() -> bool:
    """Firma ayarı: maliyet altı satış engellensin mi?"""
    try:
        from database.database import get_system_session
        from database.system.models import AppSetting
        from sqlalchemy import select

        with get_system_session() as session:
            kayit = session.scalar(
                select(AppSetting).where(
                    AppSetting.anahtar == "maliyet_alti_satis_yasak"
                )
            )
            if kayit is None or kayit.deger is None:
                return False
            return str(kayit.deger).strip().lower() in (
                "1",
                "true",
                "evet",
                "yes",
                "yasak",
            )
    except Exception:
        return False


def maliyet_alti_satis_yasak_ayarla(yasak: bool) -> None:
    """Firma ayarını kaydet (system AppSetting)."""
    from database.database import get_system_session
    from database.system.models import AppSetting
    from sqlalchemy import select

    deger = "1" if yasak else "0"
    with get_system_session() as session:
        kayit = session.scalar(
            select(AppSetting).where(AppSetting.anahtar == "maliyet_alti_satis_yasak")
        )
        if kayit is None:
            session.add(AppSetting(anahtar="maliyet_alti_satis_yasak", deger=deger))
        else:
            kayit.deger = deger
        session.commit()


def fiyat_metnini_coz(metin: str) -> Decimal:
    """Virgül/nokta ondalık ayırıcılarını Decimal'e çevirir."""
    ham = (metin or "").strip()
    if not ham:
        raise ValueError("Fiyat boş olamaz.")
    # TR: 1.234,56 → 1234.56 ; EN: 1,234.56 → 1234.56
    if "," in ham and "." in ham:
        if ham.rfind(",") > ham.rfind("."):
            ham = ham.replace(".", "").replace(",", ".")
        else:
            ham = ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        return Decimal(ham)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geçerli bir fiyat girin.") from exc


def satir_maliyeti(veri: dict, yontem: str | None = None) -> Decimal:
    alan = {
        "FIFO": "fifo_birim_maliyeti",
        "SON ALIŞ FİYATI": "son_alis_birim_maliyeti",
        "ORTALAMA ALIŞ FİYATI": "ortalama_birim_maliyeti",
        "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": "agirlikli_ortalama_birim_maliyeti",
    }.get((yontem or "FIFO").upper(), "fifo_birim_maliyeti")
    try:
        return decimal(veri.get(alan) or 0, "Maliyet", Decimal("0"))
    except Exception:
        return Decimal("0")


def maliyet_alti_kontrol(
    yeni_fiyat: Decimal,
    veri: dict,
    *,
    yontem: str | None = None,
    parent=None,
    hedef_marj: Decimal | None = None,
) -> bool:
    """True = devam edilebilir. Yasak + maliyet altıysa False.

    Uyarılar: alış maliyeti altı, hedef kâr marjı altı.
    """
    maliyet = satir_maliyeti(veri, yontem)
    marj = Decimal("0")
    if maliyet > 0:
        marj = (yeni_fiyat - maliyet) / maliyet * 100

    # Hedef kâr marjı uyarısı — engellemez
    if (
        hedef_marj is not None
        and hedef_marj > 0
        and maliyet > 0
        and marj < hedef_marj
        and yeni_fiyat >= maliyet
    ):
        if not messagebox.askyesno(
            "Kâr marjı",
            f"Girilen fiyat hedef kâr marjının altında.\n"
            f"Hedef: %{hedef_marj}\nGerçekleşen: %{marj:.1f}\n\nDevam edilsin mi?",
            parent=parent,
        ):
            return False

    if maliyet <= 0 or yeni_fiyat >= maliyet:
        return True

    mesaj = (
        f"Girilen fiyat alış maliyetinin altında.\n"
        f"Maliyet: {maliyet}\nFiyat: {yeni_fiyat}\nMarj: {marj:.1f}%\n\n"
    )
    if maliyet_alti_satis_yasak_mi():
        if yetki_var("satis_fiyat_degistirme") or (
            (oturum.role_kod or "").upper() == "YONETICI"
        ):
            return bool(
                messagebox.askyesno(
                    "Maliyet altı satış",
                    mesaj
                    + "Firma ayarında maliyet altı satış yasak.\n"
                    "Yetkili olarak yine de uygulansın mı?",
                    parent=parent,
                )
            )
        messagebox.showerror(
            "Maliyet altı satış",
            mesaj + "Firma ayarında maliyet altı satış engellenmiştir.",
            parent=parent,
        )
        return False
    return bool(
        messagebox.askyesno(
            "Maliyet altı uyarı",
            mesaj + "Devam edilsin mi?",
            parent=parent,
        )
    )


def maliyet_alti_ayar_dialogu(parent) -> None:
    """Firma ayarı: maliyet altı satış yasağı."""
    from database.access import yetki_var

    if not (
        yetki_var("firma_yonetme", "sistem_ayarlari")
        or (oturum.role_kod or "").upper() == "YONETICI"
    ):
        messagebox.showwarning(
            "Yetki",
            "Firma satış ayarlarını değiştirme yetkiniz yok.",
            parent=parent,
        )
        return

    win = tk.Toplevel(parent)
    win.title("Satış Fiyat Ayarları")
    win.transient(parent)
    win.grab_set()
    win.geometry("420x160")

    var = tk.BooleanVar(value=maliyet_alti_satis_yasak_mi())
    ttk.Label(
        win,
        text="Maliyet altı satış politikası",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", padx=14, pady=(14, 6))
    ttk.Checkbutton(
        win,
        text="Maliyet altı satışı yasakla (yetkili onayı olmadan kayıt yapılamaz)",
        variable=var,
    ).pack(anchor="w", padx=14, pady=4)

    def _kaydet():
        try:
            maliyet_alti_satis_yasak_ayarla(bool(var.get()))
        except Exception as hata:
            messagebox.showerror("Ayar", str(hata), parent=win)
            return
        messagebox.showinfo("Ayarlar", "Satış fiyat ayarı kaydedildi.", parent=win)
        win.destroy()

    alt = ttk.Frame(win)
    alt.pack(fill="x", padx=14, pady=16)
    ttk.Button(alt, text="İptal", command=win.destroy).pack(side="right")
    ttk.Button(alt, text="Kaydet", command=_kaydet).pack(side="right", padx=6)


def fiyat_degisikligi_audit(
    *,
    fatura_no: str | None,
    urun_kodu: str,
    eski: Decimal,
    yeni: Decimal,
    kayit_id: str | None = None,
) -> None:
    try:
        from database.user_audit import audit_document

        audit_document(
            "SATIR_FIYAT_DEGISTI",
            modul="satis_faturasi",
            kayit_id=kayit_id,
            belge_no=fatura_no,
            eski={"urun_kodu": urun_kodu, "birim_fiyat": str(eski)},
            yeni={"urun_kodu": urun_kodu, "birim_fiyat": str(yeni)},
            aciklama="Manuel birim fiyat",
        )
    except Exception:
        pass


def varsayilan_satis_fiyati(urun_kodu: str, musteri=None) -> Decimal:
    liste = None
    try:
        if musteri is not None:
            from hizli_satis_musteri import fiyat_listesi_coz

            liste = fiyat_listesi_coz(
                satis_fiyat_listesi=getattr(musteri, "satis_fiyat_listesi", None),
                musteri_grubu=getattr(musteri, "musteri_grubu", None),
            )
    except Exception:
        liste = None
    try:
        return StokService.satis_fiyati_adi_ile(urun_kodu, liste, varsayilan=0)
    except Exception:
        return StokService.satis_fiyati_1(urun_kodu, varsayilan=Decimal("0"))


def varsayilan_satis_fiyati(urun_kodu: str, musteri=None) -> Decimal:
    liste = None
    try:
        if musteri is not None:
            from hizli_satis_musteri import fiyat_listesi_coz

            liste = fiyat_listesi_coz(
                satis_fiyat_listesi=getattr(musteri, "satis_fiyat_listesi", None),
                musteri_grubu=getattr(musteri, "musteri_grubu", None),
            )
    except Exception:
        liste = None
    try:
        return StokService.satis_fiyati_adi_ile(urun_kodu, liste, varsayilan=0)
    except Exception:
        return StokService.satis_fiyati_1(urun_kodu, varsayilan=Decimal("0"))


def manuel_fiyat_dialogu(
    parent,
    *,
    urun_kodu: str,
    urun_adi: str,
    mevcut_fiyat: Decimal,
    on_ok: Callable[[Decimal], None],
    on_liste: Callable[[], None] | None = None,
) -> None:
    """Manuel birim fiyat giriş penceresi."""
    if not fiyat_degistirme_yetkisi():
        messagebox.showwarning(
            "Yetki",
            "Birim fiyatı değiştirme yetkiniz yok.\n"
            "Yöneticinizden «Satış faturasında birim fiyatı manuel değiştirme» "
            "iznini isteyin.",
            parent=parent,
        )
        return

    win = tk.Toplevel(parent)
    win.title("Manuel Birim Fiyat")
    win.transient(parent)
    win.grab_set()
    win.geometry("360x180")

    ttk.Label(
        win,
        text=f"{urun_kodu} — {urun_adi}",
        font=("Segoe UI", 9, "bold"),
        wraplength=330,
    ).pack(padx=12, pady=(12, 4), anchor="w")

    satir = ttk.Frame(win)
    satir.pack(fill="x", padx=12, pady=8)
    ttk.Label(satir, text="Birim Fiyat").pack(side="left")
    var = tk.StringVar(
        value=str(mevcut_fiyat).replace(".", ",") if mevcut_fiyat is not None else "0"
    )
    entry = ttk.Entry(satir, textvariable=var, width=18, font=("Segoe UI", 11))
    entry.pack(side="left", padx=8)
    entry.focus_set()
    entry.selection_range(0, "end")

    def _uygula(_event=None):
        try:
            yeni = fiyat_metnini_coz(var.get())
        except ValueError as hata:
            messagebox.showerror("Fiyat", str(hata), parent=win)
            return
        if yeni < 0:
            messagebox.showerror("Fiyat", "Fiyat sıfırdan küçük olamaz.", parent=win)
            return
        if yeni == 0:
            if not messagebox.askyesno(
                "Sıfır fiyat",
                "Birim fiyat 0 olarak kaydedilsin mi?",
                parent=win,
            ):
                return
        win.destroy()
        on_ok(yeni)

    def _liste():
        win.destroy()
        if on_liste:
            on_liste()

    alt = ttk.Frame(win)
    alt.pack(fill="x", padx=12, pady=10)
    if on_liste:
        ttk.Button(alt, text="Listeden Seç", command=_liste).pack(side="left")
    ttk.Button(alt, text="İptal", command=win.destroy).pack(side="right")
    ttk.Button(alt, text="Uygula", command=_uygula).pack(side="right", padx=6)
    entry.bind("<Return>", _uygula)
    win.bind("<Escape>", lambda _e: win.destroy())
