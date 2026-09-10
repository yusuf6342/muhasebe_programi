"""Özet Tablolar → Bilanço / Özet Tablo — canlı varlık–kaynak özeti."""

from __future__ import annotations

from decimal import Decimal
from tkinter import messagebox, ttk

from database.rapor_service import MALIYET_YONTEMLERI_RAPOR, RaporService


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def bilanco_sayfasi_goster(app):
    """AKTİF / PASİF iki sütunlu bilanço benzeri özet tablo."""
    from ozet_tablolar_ui import _ozet_tablolar_menu_isaretle, ozet_tablolar_menusu_goster

    app._icerigi_temizle()
    _ozet_tablolar_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BİLANÇO / ÖZET TABLO", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Özet Tablolar Menüsü", command=lambda: ozet_tablolar_menusu_goster(app)).pack(
        side="right"
    )

    ttk.Label(
        app.icerik,
        text=(
            "Kasa, banka (mevduat / POS / KMH), cari alacak–borç, stok ve kredi / KK bakiyeleri. "
            "Özkaynak satırı Aktif − Borçlar farkıdır; iki taraf dengelenir."
        ),
    ).pack(anchor="w", pady=(8, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(4, 6))
    ttk.Label(filtre, text="Stok maliyet yöntemi:").pack(side="left")
    yontem = ttk.Combobox(filtre, values=list(MALIYET_YONTEMLERI_RAPOR), state="readonly", width=28)
    yontem.set("FIFO")
    yontem.pack(side="left", padx=6)

    ozet_etiket = ttk.Label(app.icerik, text="", font=("Segoe UI", 10, "bold"))
    ozet_etiket.pack(anchor="w", pady=(0, 4))

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, pady=(4, 0))
    govde.columnconfigure(0, weight=1, uniform="bilanco")
    govde.columnconfigure(1, weight=1, uniform="bilanco")
    govde.rowconfigure(1, weight=1)

    ttk.Label(govde, text="AKTİF  (Varlıklar)", font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, sticky="w", padx=(0, 8)
    )
    ttk.Label(govde, text="PASİF  (Kaynaklar / Borçlar)", font=("Segoe UI", 11, "bold")).grid(
        row=0, column=1, sticky="w", padx=(8, 0)
    )

    aktif_cerceve, aktif_tablo = _bilanco_tree(govde, "AKTİF")
    aktif_cerceve.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
    pasif_cerceve, pasif_tablo = _bilanco_tree(govde, "PASİF")
    pasif_cerceve.grid(row=1, column=1, sticky="nsew", padx=(8, 0))

    stil = ttk.Style()
    stil.configure("Bilanco.Treeview", font=("Segoe UI", 9), rowheight=24)
    stil.configure("Bilanco.Treeview.Heading", font=("Segoe UI", 9, "bold"))
    for tablo in (aktif_tablo, pasif_tablo):
        tablo.configure(style="Bilanco.Treeview")
        tablo.tag_configure("baslik", font=("Segoe UI", 9, "bold"), background="#d9e2ec")
        tablo.tag_configure("ara_toplam", font=("Segoe UI", 9, "bold"), background="#eef2f6")
        tablo.tag_configure("toplam", font=("Segoe UI", 10, "bold"), background="#c5d4e8")
        tablo.tag_configure("kalem", background="#ffffff")
        tablo.tag_configure("kalem_cift", background="#f4f7fa")
        tablo.tag_configure("pozitif", foreground="#1b7a3d")
        tablo.tag_configure("negatif", foreground="#c62828")
        tablo.tag_configure("notr", foreground="#222222")

    def doldur():
        try:
            veri = RaporService.bilanco_ozeti(maliyet_yontemi=yontem.get().strip() or "FIFO")
        except Exception as hata:
            messagebox.showerror("Bilanço", str(hata), parent=app)
            return
        _tabloyu_doldur(aktif_tablo, veri["aktif"])
        _tabloyu_doldur(pasif_tablo, veri["pasif"])
        o = veri["ozet"]
        tarih = veri["tarih"].strftime("%d.%m.%Y")
        denge = o["denge"]
        denge_metin = "dengeli" if denge == 0 else f"fark {_para(denge)}"
        ozet_etiket.configure(
            text=(
                f"Tarih: {tarih}  |  "
                f"Toplam varlık: {_para(o['toplam_aktif'])}  |  "
                f"Toplam borç: {_para(o['toplam_borclar'])}  |  "
                f"Özkaynak: {_para(o['ozkaynak'])}  |  "
                f"Aktif = Pasif: {denge_metin}"
            )
        )

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yenile", command=doldur).pack(side="right")
    yontem.bind("<<ComboboxSelected>>", lambda _e: doldur())
    doldur()


def _bilanco_tree(parent, baslik: str) -> tuple[ttk.Frame, ttk.Treeview]:
    cerceve = ttk.Frame(parent)
    kolonlar = ("kalem", "tutar")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    tablo.heading("kalem", text=baslik, anchor="w")
    tablo.heading("tutar", text="Tutar", anchor="e")
    tablo.column("kalem", width=320, minwidth=160, anchor="w", stretch=True)
    tablo.column("tutar", width=130, minwidth=100, anchor="e", stretch=False)
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=dikey.set)
    tablo.pack(side="left", fill="both", expand=True)
    dikey.pack(side="right", fill="y")
    return cerceve, tablo


def _tabloyu_doldur(tablo: ttk.Treeview, satirlar: list):
    for item in tablo.get_children():
        tablo.delete(item)
    kalem_sira = 0
    for s in satirlar:
        seviye = s.get("seviye") or "kalem"
        tutar = Decimal(str(s.get("tutar") or 0))
        if seviye == "baslik":
            deger = ""
            tags = ("baslik",)
        else:
            deger = _para(tutar)
            renk = "pozitif" if tutar > 0 else ("negatif" if tutar < 0 else "notr")
            if seviye == "toplam":
                tags = ("toplam", renk)
            elif seviye == "ara_toplam":
                tags = ("ara_toplam", renk)
            else:
                kusak = "kalem" if kalem_sira % 2 == 0 else "kalem_cift"
                kalem_sira += 1
                tags = (kusak, renk)
        tablo.insert("", "end", values=(s.get("etiket") or "", deger), tags=tags)
