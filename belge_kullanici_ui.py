"""Belge ekranlarında salt okunur «İşlemi Yapan» bilgi paneli."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from database.session_manager import oturum
from database.user_audit import display_user, format_dt


def aktif_kullanici_adi() -> str:
    if not oturum.oturum_acik:
        return "—"
    return (oturum.ad_soyad or oturum.kullanici_adi or "—").strip() or "—"


def belge_kullanici_ozet(obj: Any | None = None, *, yeni: bool = False) -> dict[str, str]:
    """Kart üst bilgi metinleri — Oluşturan vs Aktif Kullanıcı ayrı."""
    aktif = aktif_kullanici_adi()
    if yeni or obj is None:
        return {
            "islem_yapan": aktif,
            "aktif_kullanici": aktif,
            "olusturma": "—",
            "son_guncelleyen": "—",
            "son_guncelleme": "—",
            "onaylayan": "—",
            "onay_tarihi": "—",
            "iptal_eden": "—",
            "iptal_tarihi": "—",
            "siparis_olusturan": "—",
        }
    return {
        "islem_yapan": display_user(
            getattr(obj, "created_by_full_name", None),
            getattr(obj, "created_by_user_id", None),
        ),
        "aktif_kullanici": aktif,
        "olusturma": format_dt(getattr(obj, "olusturma_tarihi", None)),
        "son_guncelleyen": display_user(
            getattr(obj, "updated_by_full_name", None),
            getattr(obj, "updated_by_user_id", None),
        )
        if getattr(obj, "updated_by_user_id", None) or getattr(obj, "updated_by_full_name", None)
        else "—",
        "son_guncelleme": format_dt(getattr(obj, "updated_at", None)),
        "onaylayan": display_user(
            getattr(obj, "approved_by_full_name", None),
            getattr(obj, "approved_by_user_id", None),
        )
        if getattr(obj, "approved_by_user_id", None) or getattr(obj, "approved_by_full_name", None)
        else "—",
        "onay_tarihi": format_dt(getattr(obj, "approved_at", None)),
        "iptal_eden": display_user(
            getattr(obj, "cancelled_by_full_name", None),
            getattr(obj, "cancelled_by_user_id", None),
        )
        if getattr(obj, "cancelled_by_user_id", None) or getattr(obj, "cancelled_by_full_name", None)
        else "—",
        "iptal_tarihi": format_dt(getattr(obj, "cancelled_at", None)),
        "siparis_olusturan": "—",
    }


def kullanici_bilgi_paneli(
    parent,
    *,
    baslik: str = "İşlem Bilgisi",
    alanlar: list[tuple[str, str]] | None = None,
) -> dict[str, ttk.Label]:
    """Salt okunur etiket paneli. Döner: anahtar → değer Label."""
    cerceve = ttk.LabelFrame(parent, text=baslik, padding=6)
    refs: dict[str, ttk.Label] = {"cerceve": cerceve}  # type: ignore[assignment]
    satirlar = alanlar or [
        ("islem_yapan", "Oluşturan"),
        ("aktif_kullanici", "Aktif Kullanıcı"),
        ("olusturma", "Oluşturma"),
        ("son_guncelleyen", "Son Güncelleyen"),
        ("son_guncelleme", "Son Güncelleme"),
    ]
    for i, (anahtar, etiket) in enumerate(satirlar):
        ttk.Label(cerceve, text=f"{etiket}:").grid(row=i, column=0, sticky="w", padx=(0, 8), pady=1)
        deger = ttk.Label(cerceve, text="—", font=("Segoe UI", 9, "bold"))
        deger.grid(row=i, column=1, sticky="w", pady=1)
        refs[anahtar] = deger
    return refs


def panel_doldur(refs: dict[str, ttk.Label], ozet: dict[str, str]) -> None:
    for anahtar, deger in ozet.items():
        lbl = refs.get(anahtar)
        if lbl is None:
            continue
        try:
            lbl.configure(text=deger or "—")
        except tk.TclError:
            pass
