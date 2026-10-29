"""Tahsilat ve Mahsup Esaslı Kâr Gerçekleşme Raporu."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

from ui_takvim import takvim_butonu


def _para(v) -> str:
    if v is None:
        return "—"
    try:
        from ana_panel_tema import para_tr

        return para_tr(Decimal(str(v)))
    except Exception:
        return f"{Decimal(str(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def kar_gerceklesme_raporu_goster(app):
    app._icerigi_temizle()
    try:
        from ozet_tablolar_ui import _ozet_tablolar_menu_isaretle

        _ozet_tablolar_menu_isaretle(app)
    except Exception:
        pass

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(
        ust,
        text="TAHSİLAT VE MAHSUP ESASLI KÂR GERÇEKLEŞME RAPORU",
        style="Baslik.TLabel",
    ).pack(side="left")
    ttk.Button(
        ust,
        text="← Özet Tablolar",
        command=lambda: __import__("ozet_tablolar_ui").ozet_tablolar_menusu_goster(app),
    ).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Hesap esası: Kesin tahsilat ve mahsup. Brüt satış kârı; genel giderler düşülmez.",
    ).pack(anchor="w", pady=(8, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(4, 8))
    bugun = date.today()
    bas_def = bugun.replace(day=1)
    ttk.Label(filtre, text="Satış dönemi").pack(side="left")
    bas_e = ttk.Entry(filtre, width=12)
    bas_e.pack(side="left", padx=(6, 2))
    bas_e.insert(0, bas_def.strftime("%d.%m.%Y"))
    takvim_butonu(filtre, bas_e)
    ttk.Label(filtre, text="—").pack(side="left", padx=4)
    bit_e = ttk.Entry(filtre, width=12)
    bit_e.pack(side="left", padx=(2, 2))
    bit_e.insert(0, bugun.strftime("%d.%m.%Y"))
    takvim_butonu(filtre, bit_e)

    ozet_frm = ttk.Frame(app.icerik)
    ozet_frm.pack(fill="x", pady=(0, 8))
    ozet_lbls: dict[str, ttk.Label] = {}
    for i, (k, baslik) in enumerate(
        (
            ("toplam_brut_kar", "Toplam brüt satış kârı"),
            ("gerceklesen_brut_kar", "Gerçekleşen brüt kâr"),
            ("bekleyen_brut_kar", "Bekleyen brüt kâr"),
            ("hesap_disi", "Hesap dışı belge"),
        )
    ):
        kutu = ttk.LabelFrame(ozet_frm, text=baslik, padding=6)
        kutu.grid(row=0, column=i, padx=4, sticky="ew")
        ozet_frm.columnconfigure(i, weight=1)
        lbl = ttk.Label(kutu, text="—", font=("Segoe UI", 12, "bold"))
        lbl.pack()
        ozet_lbls[k] = lbl

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    cols = (
        "tarih",
        "belge",
        "musteri",
        "net",
        "kar",
        "alacak",
        "karsilanan",
        "oran",
        "gerceklesen",
        "bekleyen",
        "durum",
    )
    tablo = ttk.Treeview(cerceve, columns=cols, show="headings", selectmode="browse")
    basliklar = (
        ("tarih", "Tarih", 90),
        ("belge", "Fatura", 110),
        ("musteri", "İlk satış müşterisi", 180),
        ("net", "Net satış", 100),
        ("kar", "Brüt kâr", 100),
        ("alacak", "Alacak (F)", 100),
        ("karsilanan", "Karşılanan (S)", 110),
        ("oran", "Oran", 60),
        ("gerceklesen", "Gerçekleşen", 100),
        ("bekleyen", "Bekleyen", 100),
        ("durum", "Durum", 130),
    )
    for k, b, w in basliklar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")

    def _temizle():
        for i in tablo.get_children():
            tablo.delete(i)

    def _getir():
        from datetime import datetime

        from database.kar_gerceklesme_service import fatura_kar_gerceklesme

        try:
            bas = datetime.strptime(bas_e.get().strip(), "%d.%m.%Y").date()
            bit = datetime.strptime(bit_e.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy biçiminde girin.", parent=app)
            return
        if bas > bit:
            messagebox.showerror("Tarih", "Başlangıç bitişten sonra olamaz.", parent=app)
            return
        try:
            sonuc = fatura_kar_gerceklesme(bas, bit)
        except Exception as hata:
            messagebox.showerror("Rapor", str(hata), parent=app)
            return
        _temizle()
        oz = sonuc["ozet"]
        ozet_lbls["toplam_brut_kar"].configure(text=_para(oz["toplam_brut_kar"]))
        ozet_lbls["gerceklesen_brut_kar"].configure(text=_para(oz["gerceklesen_brut_kar"]))
        ozet_lbls["bekleyen_brut_kar"].configure(text=_para(oz["bekleyen_brut_kar"]))
        ozet_lbls["hesap_disi"].configure(text=str(oz["hesap_disi"]))
        for s in sonuc["satirlar"]:
            oran = s["oran"]
            oran_txt = f"%{float(oran) * 100:.0f}" if oran is not None else "—"
            tablo.insert(
                "",
                "end",
                iid=str(s["fatura_id"]),
                values=(
                    _tarih(s["tarih"]),
                    s["fatura_no"],
                    s["musteri"],
                    _para(s["net_satis"]),
                    _para(s["brut_kar"]),
                    _para(s["alacak_f"]),
                    _para(s["karsilanan_s"]),
                    oran_txt,
                    _para(s["gerceklesen"]),
                    _para(s["bekleyen"]),
                    s["durum"],
                ),
            )

    ttk.Button(filtre, text="Raporu getir", command=_getir).pack(side="left", padx=(12, 4))
    ttk.Button(filtre, text="Yenile", command=_getir).pack(side="left", padx=4)
    ttk.Button(
        filtre,
        text="Filtreyi temizle",
        command=lambda: (
            bas_e.delete(0, "end"),
            bas_e.insert(0, bas_def.strftime("%d.%m.%Y")),
            bit_e.delete(0, "end"),
            bit_e.insert(0, bugun.strftime("%d.%m.%Y")),
            _temizle(),
        ),
    ).pack(side="left", padx=4)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kar_gerceklesme_raporu_goster(app))
    _getir()
