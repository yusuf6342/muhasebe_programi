"""Alınan Sipariş Kartı — kurumsal chrome (fatura_tema üzerine)."""

from __future__ import annotations

import tkinter as tk
from typing import Any

import fatura_tema as ft


ACIK_BG = ft.ACIK_BG
BEYAZ = ft.BEYAZ
LACIVERT = ft.LACIVERT

# Sipariş durum renkleri (mevcut operasyonel durumlar)
SIPARIS_DURUM_RENKLERI = {
    "TASLAK": ("#64748B", ft.BEYAZ),
    "AÇIK": (ft.BASARI, ft.BEYAZ),
    "ONAYLANDI": (ft.BASARI, ft.BEYAZ),
    "KISMİ İRSALİYELİ": (ft.UYARI, ft.BEYAZ),
    "İRSALİYELİ": (ft.LACIVERT_ORTA, ft.BEYAZ),
    "KISMİ FATURALI": ("#EA580C", ft.BEYAZ),
    "FATURALI": ("#0E7490", ft.BEYAZ),
    "TAMAMLANDI": (ft.LACIVERT, ft.BEYAZ),
    "İPTAL": (ft.IPTAL, ft.BEYAZ),
}

ONCELIK_RENKLERI = {
    "Normal": ("#E5E7EB", "#374151"),
    "Acil": (ft.UYARI, ft.BEYAZ),
    "Çok Acil": (ft.IPTAL, ft.BEYAZ),
}


def stil_uygula(root=None):
    # Durum paletini genişlet
    ft.DURUM_RENKLERI.update(SIPARIS_DURUM_RENKLERI)
    stil = ft.stil_uygula(root=root)
    # Üst panel: etiketler kompakt/normal; değer alanları 12pt bold (+1)
    f_etiket = ft.font(9, root=root)
    f_deger = ft.font(12, "bold", root=root)
    stil.configure(
        "SiparisUst.TLabel",
        background=LACIVERT,
        foreground=BEYAZ,
        font=f_etiket,
    )
    stil.configure(
        "SiparisUstAcik.TLabel",
        background="#FFF7CC",
        foreground=ft.METIN,
        font=f_etiket,
    )
    stil.configure(
        "SiparisUst.TEntry",
        fieldbackground=BEYAZ,
        foreground=ft.METIN,
        font=f_deger,
        padding=(4, 4),
    )
    stil.configure(
        "SiparisUst.TCombobox",
        fieldbackground=BEYAZ,
        foreground=ft.METIN,
        font=f_deger,
        padding=(4, 4),
    )
    # Readonly/disabled değerler de koyu kalsın (Windows clam)
    stil.map(
        "SiparisUst.TEntry",
        foreground=[
            ("readonly", ft.METIN),
            ("disabled", ft.METIN),
            ("!disabled", ft.METIN),
        ],
        fieldbackground=[
            ("readonly", BEYAZ),
            ("disabled", BEYAZ),
            ("!disabled", BEYAZ),
        ],
    )
    stil.map(
        "SiparisUst.TCombobox",
        foreground=[
            ("readonly", ft.METIN),
            ("disabled", ft.METIN),
            ("!disabled", ft.METIN),
        ],
        fieldbackground=[
            ("readonly", BEYAZ),
            ("disabled", BEYAZ),
            ("!disabled", BEYAZ),
        ],
    )
    stil.configure(
        "SiparisUst.TButton",
        font=ft.font(9, "bold", root=root),
        padding=(6, 3),
    )
    # Ürün satır yüksekliği = yazı metrics + pay (ızgara metni kesmez; Teklif ile aynı formül)
    f_satir = ft.font(12, "bold", root=root)
    f_baslik = ft.font(10, "bold", root=root)
    satir_rh = ft.tablo_satir_rowheight(root, font_spec=f_satir, vurgulu_font_spec=f_satir)
    stil.configure(
        "SiparisSatir.Treeview",
        font=f_satir,
        rowheight=satir_rh,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=ft.METIN,
        borderwidth=0,
        relief="flat",
    )
    stil.configure(
        "SiparisSatir.Treeview.Heading",
        font=f_baslik,
        background="#E8EEF5",
        foreground=LACIVERT,
        relief="solid",
        borderwidth=1,
        padding=(6, ft.scale_height(ft.TABLO_BASLIK_PAD_TABAN)),
    )
    stil.map(
        "SiparisSatir.Treeview",
        background=[("selected", ft.SECIM)],
        foreground=[("selected", LACIVERT)],
    )
    stil.map(
        "SiparisSatir.Treeview.Heading",
        background=[("active", ft.SARI), ("pressed", ft.SARI)],
        foreground=[("active", LACIVERT), ("pressed", LACIVERT)],
    )
    return stil


def siparis_ust_toolbar(
    parent,
    *,
    siparis_no: str = "Yeni",
    musteri_kisa: str = "",
    durum: str = "TASLAK",
) -> dict[str, Any]:
    ft.DURUM_RENKLERI.update(SIPARIS_DURUM_RENKLERI)
    refs = ft.ust_toolbar(
        parent,
        baslik="ALINAN SİPARİŞ",
        fatura_no=siparis_no or "Yeni",
        musteri_kisa=musteri_kisa,
        durum=durum,
    )
    if refs.get("rozet"):
        ft.rozet_guncelle(refs["rozet"], durum)
    return refs


def siparis_alt_ozet(parent, *, pack: bool = False) -> dict[str, Any]:
    """Alınan sipariş alt özeti — Satış Faturası ile aynı iki sütunlu toplamlar.

    Sol: Notlar + kalem/miktar özeti · Sağ: fatura_yerlesim._toplamlar_kur
    pack=False (varsayılan): çağıran sticky_footer_layout / pack ile yerleştirir.
    """
    from fatura_yerlesim import _toplamlar_kur

    root = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else None
    dis = tk.Frame(parent, bg=ACIK_BG, highlightthickness=0)
    if pack:
        dis.pack(side="bottom", fill="x")

    kart_dis, kart = ft.beyaz_kart(dis, padx=8, pady=4)
    kart_dis.pack(fill="x", padx=6, pady=(2, 4))
    kart.columnconfigure(0, weight=1, minsize=280)
    kart.columnconfigure(1, weight=0)
    kart.rowconfigure(0, weight=1)

    sol = tk.Frame(kart, bg=BEYAZ)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

    tk.Label(
        sol,
        text="Notlar",
        bg=BEYAZ,
        fg=LACIVERT,
        font=ft.font(8, "bold", root),
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    not_alani = tk.Text(
        sol,
        height=5,
        width=1,
        wrap="word",
        font=ft.font(8, root=root),
        relief="solid",
        bd=1,
    )
    not_alani.pack(fill="both", expand=True, pady=(2, 4))

    ozet_satir = tk.Frame(sol, bg=BEYAZ)
    ozet_satir.pack(fill="x", pady=(0, 2))
    kalem_lbl = tk.Label(
        ozet_satir,
        text="Kalem: 0",
        bg=BEYAZ,
        fg=ft.IKINCIL,
        font=ft.font(9, "bold", root),
        anchor="w",
    )
    kalem_lbl.pack(side="left", padx=(0, 16))
    miktar_lbl = tk.Label(
        ozet_satir,
        text="Miktar: —",
        bg=BEYAZ,
        fg=ft.IKINCIL,
        font=ft.font(9, "bold", root),
        anchor="w",
    )
    miktar_lbl.pack(side="left")

    sag, degerler = _toplamlar_kur(kart)
    sag.grid(row=0, column=1, sticky="ne", padx=(0, 4), pady=(2, 2))

    # Görev çubuğu altında kalmasın
    try:
        for cocuk in dis.winfo_children():
            if cocuk.winfo_manager() == "pack":
                cocuk.pack_configure(pady=(2, 18))
                break
    except tk.TclError:
        pass

    return {
        "dis": dis,
        "kart": kart,
        "not_alani": not_alani,
        "degerler": degerler,
        "sag": sag,
        "sol": sol,
        "analiz": None,
        "islem": None,
        "kalem_lbl": kalem_lbl,
        "miktar_lbl": miktar_lbl,
    }


def tk_buton(parent, metin, komut, *, rol="kaydet", state="normal", **kwargs):
    return ft.tk_buton(parent, metin, komut, rol=rol, state=state, **kwargs)
