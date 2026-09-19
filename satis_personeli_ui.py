"""Satış personeli seçim kutusu — müşteri kutusu ile uyumlu kurumsal stil."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from branding import COLOR_BG, COLOR_GOLD, COLOR_NAVY
from database.satis_personeli import (
    aktif_satis_personelleri,
    oturum_satis_personeli,
    personel_listesini_etiketle,
    satis_personeli_degistirme_yetkisi,
)


def satis_ve_kayit_paneli(
    parent,
    *,
    fatura: Any | None = None,
    yeni: bool = True,
) -> dict[str, Any]:
    """Sağ bölüm: Satış Personeli + kompakt kayıt bilgileri.

    Döner dict: combo, map, secili_id(), set_id(), uyarilar, etiketler…
    """
    dis = ttk.Frame(parent)
    refs: dict[str, Any] = {"cerceve": dis}

    # —— Satış Personeli kutusu ——
    sp_dis = tk.Frame(dis, bg=COLOR_NAVY, highlightthickness=0)
    sp_dis.pack(fill="x", padx=0, pady=(0, 6))
    tk.Frame(sp_dis, bg=COLOR_GOLD, height=3).pack(fill="x")
    baslik = tk.Label(
        sp_dis,
        text="  Satış Personeli",
        bg=COLOR_NAVY,
        fg=COLOR_GOLD,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    )
    baslik.pack(fill="x", pady=(4, 2))
    ic = tk.Frame(sp_dis, bg=COLOR_BG, padx=8, pady=6)
    ic.pack(fill="x")

    izin_diger = satis_personeli_degistirme_yetkisi()
    try:
        from fatura_acilis_cache import satis_personelleri as _sp_cache

        aktifler = _sp_cache()
    except Exception:
        aktifler = aktif_satis_personelleri()
    ekstra = None
    if fatura and getattr(fatura, "sales_person_id", None):
        ekstra = {
            "id": fatura.sales_person_id,
            "ad_soyad": getattr(fatura, "sales_person_full_name", None) or "",
        }
    liste = personel_listesini_etiketle(aktifler, ekstra=ekstra)
    if not izin_diger:
        uid = None
        try:
            from database.session_manager import oturum

            uid = int(oturum.user_id) if oturum.user_id else None
        except Exception:
            uid = None
        filtreli = [p for p in liste if p.get("aktif") and int(p["id"]) == uid]
        # Eski faturada başka personel varsa görüntü için tut
        if ekstra and int(ekstra["id"]) != uid:
            for p in liste:
                if int(p["id"]) == int(ekstra["id"]):
                    filtreli.append(p)
                    break
        liste = filtreli or liste

    etiket_map = {p["etiket"]: p for p in liste}
    id_map = {int(p["id"]): p for p in liste}
    values = [p["etiket"] for p in liste if p.get("aktif")]
    # Pasif eski kayıt da values'ta olmalı (görüntü)
    for p in liste:
        if not p.get("aktif") and p["etiket"] not in values:
            values.append(p["etiket"])

    combo = ttk.Combobox(ic, values=values, width=36)
    combo.pack(fill="x")
    uyari = tk.Label(ic, text="", bg=COLOR_BG, fg="#B71C1C", font=("Segoe UI", 8), anchor="w")
    uyari.pack(fill="x", pady=(2, 0))

    if not aktifler:
        uyari.configure(
            text="Aktif satış personeli bulunamadı. Kullanıcı yönetimini kontrol edin."
        )

    tum_values = list(values)

    def _filtrele(_event=None):
        yazi = (combo.get() or "").strip().casefold()
        if not yazi:
            combo.configure(values=tum_values)
            return
        filt = [v for v in tum_values if yazi in v.casefold()]
        combo.configure(values=filt or tum_values)

    combo.bind("<KeyRelease>", _filtrele)

    def secili_id() -> int | None:
        etiket = (combo.get() or "").strip()
        p = etiket_map.get(etiket)
        if p:
            return int(p["id"])
        # Kısmi eşleşme
        for e, kayit in etiket_map.items():
            if e.casefold() == etiket.casefold():
                return int(kayit["id"])
        return None

    def set_id(pid: int | None, ad: str | None = None):
        if pid is None:
            combo.set("")
            return
        p = id_map.get(int(pid))
        if p:
            combo.set(p["etiket"])
            return
        # Listede yok — geçici etiket
        from database.satis_personeli import personel_etiketi

        et = personel_etiketi(ad or "", pasif=True)
        etiket_map[et] = {
            "id": int(pid),
            "ad_soyad": ad or "",
            "etiket": et,
            "aktif": False,
        }
        id_map[int(pid)] = etiket_map[et]
        vals = list(combo.cget("values"))
        if et not in vals:
            combo.configure(values=list(vals) + [et])
            tum_values.append(et)
        combo.set(et)

    # Varsayılan seçim
    if fatura and getattr(fatura, "sales_person_id", None):
        set_id(fatura.sales_person_id, getattr(fatura, "sales_person_full_name", None))
    elif yeni:
        oneri = oturum_satis_personeli()
        if oneri and oneri.get("id") in id_map:
            set_id(int(oneri["id"]))
        elif oneri:
            set_id(int(oneri["id"]), oneri.get("ad_soyad"))

    if not izin_diger:
        # Yalnızca kendi + (gerekirse eski pasif görüntü)
        try:
            combo.configure(state="readonly")
        except tk.TclError:
            pass

    refs["combo"] = combo
    refs["secili_id"] = secili_id
    refs["set_id"] = set_id
    refs["uyari"] = uyari
    refs["izin_diger"] = izin_diger
    refs["personel_map"] = id_map

    # —— Kayıt bilgileri ——
    kayit = ttk.LabelFrame(dis, text="Kayıt Bilgileri", padding=6)
    kayit.pack(fill="x")
    from belge_kullanici_ui import belge_kullanici_ozet

    ozet = belge_kullanici_ozet(fatura, yeni=yeni)
    durum_metin = "Taslak"
    if fatura:
        if getattr(fatura, "durum", None) == "İPTAL":
            durum_metin = "İptal"
        elif getattr(fatura, "onaylandi", False):
            durum_metin = "Onaylı"
        else:
            durum_metin = "Taslak"

    satirlar = [
        ("Oluşturan", ozet.get("islem_yapan") or "—"),
        ("Belge durumu", durum_metin),
        ("Oluşturulma", ozet.get("olusturma") or "—"),
        ("Son düzenleyen", ozet.get("son_guncelleyen") or "—"),
    ]
    for i, (etiket, deger) in enumerate(satirlar):
        ttk.Label(kayit, text=f"{etiket}:", foreground=COLOR_NAVY).grid(
            row=i, column=0, sticky="w", padx=(0, 6), pady=1
        )
        lbl = ttk.Label(kayit, text=deger, font=("Segoe UI", 9, "bold"))
        lbl.grid(row=i, column=1, sticky="w", pady=1)
        refs[f"kayit_{i}"] = lbl

    refs["kayit_cerceve"] = kayit
    return refs


def musteri_bilgi_kutusu_stil(frame_parent) -> tk.Frame:
    """Müşteri alanı için aynı dilde dış çerçeve (isteğe bağlı sarmalayıcı)."""
    dis = tk.Frame(frame_parent, bg=COLOR_NAVY)
    tk.Frame(dis, bg=COLOR_GOLD, height=3).pack(fill="x")
    tk.Label(
        dis,
        text="  Müşteri Bilgileri",
        bg=COLOR_NAVY,
        fg=COLOR_GOLD,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(4, 2))
    ic = tk.Frame(dis, bg=COLOR_BG, padx=8, pady=6)
    ic.pack(fill="both", expand=True)
    return ic
