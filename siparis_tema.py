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
    # Sipariş hareket satırları (ürün Treeview hücreleri): 12pt koyu/bold
    f_satir = ft.font(12, "bold", root=root)
    f_baslik = ft.font(10, "bold", root=root)
    # 12pt bold: satır yüksekliği fonta yakın — hücre metni dikeyde daha ortalı hisseder
    # (Tk Treeview dikey anchor desteklemez; aşırı rowheight metni üste yapıştırır)
    satir_rh = max(ft.scale_height(28), 36)
    stil.configure(
        "SiparisSatir.Treeview",
        font=f_satir,
        rowheight=satir_rh,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=ft.METIN,
        borderwidth=1,
        relief="solid",
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
    """Alınan sipariş alt özeti — Fiyat Analiz paneli yok (Notlar + toplamlar).

    pack=False (varsayılan): çağıran sticky_footer_layout ile yerleştirir (fatura gibi).
    """
    refs = ft.alt_ozet_cubugu(parent, pack=pack)
    analiz = refs.get("analiz")
    if analiz is not None:
        try:
            analiz.destroy()
        except tk.TclError:
            pass
        refs["analiz"] = None
        refs["islem"] = None

    kart = refs.get("kart")
    sol = refs.get("sol")
    sag = refs.get("sag")
    if kart is not None and sol is not None and sag is not None:
        try:
            # Notlar geniş (sipariş ayrıntıları) | Toplamlar sağda
            kart.columnconfigure(0, weight=1, minsize=360)
            kart.columnconfigure(1, weight=0)
            kart.columnconfigure(2, weight=0)
            kart.rowconfigure(0, weight=1)
            sol.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
            sag.grid(row=0, column=1, sticky="ne")
        except tk.TclError:
            pass
        not_w = refs.get("not_alani")
        try:
            for w in list(sol.winfo_children()):
                if isinstance(w, tk.Text):
                    w.pack_forget()
            if not_w is not None:
                not_w.configure(height=7, width=1, wrap="word")
                not_w.pack(fill="both", expand=True, pady=(2, 0))
        except tk.TclError:
            pass

    # Görev çubuğu altında kalmasın: footer içeriğini bir satır yukarı çek
    dis = refs.get("dis")
    if dis is not None:
        try:
            for cocuk in dis.winfo_children():
                if cocuk.winfo_manager() == "pack":
                    cocuk.pack_configure(pady=(2, 28))
                    break
        except tk.TclError:
            pass

    # Döviz satırı siparişte yok; İndirim/Masraf/Uzlaşılan ipucu fatura ile aynı kalsın
    degerler = refs.get("degerler") or {}
    w = degerler.get("doviz")
    if w is not None and sag is not None:
        try:
            row = int(w.grid_info().get("row") or 0)
            for cocuk in sag.grid_slaves(row=row):
                try:
                    cocuk.grid_remove()
                except tk.TclError:
                    pass
        except (tk.TclError, ValueError, TypeError):
            pass
    return refs


def tk_buton(parent, metin, komut, *, rol="kaydet", state="normal", **kwargs):
    return ft.tk_buton(parent, metin, komut, rol=rol, state=state, **kwargs)
