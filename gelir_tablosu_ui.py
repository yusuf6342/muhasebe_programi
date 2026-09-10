"""Özet Tablolar → Gelir Tablosu — klasik P&L (canlı veri)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.rapor_service import MALIYET_YONTEMLERI_RAPOR, RaporService
from ui_takvim import takvim_butonu


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_oku(entry, *, zorunlu: bool = True) -> date | None:
    metin = (entry.get() or "").strip()
    if not metin:
        if zorunlu:
            raise ValueError("Tarih zorunludur.")
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def gelir_tablosu_sayfasi_goster(app):
    """Tek sütunlu klasik gelir tablosu (başlangıç–bitiş)."""
    from ozet_tablolar_ui import _ozet_tablolar_menu_isaretle, ozet_tablolar_menusu_goster

    app._icerigi_temizle()
    _ozet_tablolar_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GELİR TABLOSU", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Özet Tablolar Menüsü", command=lambda: ozet_tablolar_menusu_goster(app)).pack(
        side="right"
    )

    ttk.Label(
        app.icerik,
        text=(
            "Net satışlar − SMM = brüt kâr; giderler düşülünce net kâr/zarar. "
            "SMM = dönem başı emtia + net alışlar − dönem sonu emtia."
        ),
    ).pack(anchor="w", pady=(8, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(4, 6))

    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    baslangic = ttk.Entry(b_c, width=11)
    baslangic.pack(side="left")
    baslangic.insert(0, date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
    takvim_butonu(b_c, baslangic)

    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(10, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bitis = ttk.Entry(e_c, width=11)
    bitis.pack(side="left")
    bitis.insert(0, date.today().strftime("%d.%m.%Y"))
    takvim_butonu(e_c, bitis)

    ttk.Label(filtre, text="Stok maliyet:").pack(side="left", padx=(10, 0))
    yontem = ttk.Combobox(filtre, values=list(MALIYET_YONTEMLERI_RAPOR), state="readonly", width=28)
    yontem.set("FIFO")
    yontem.pack(side="left", padx=6)

    ozet_etiket = ttk.Label(app.icerik, text="", font=("Segoe UI", 10, "bold"))
    ozet_etiket.pack(anchor="w", pady=(0, 4))

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, pady=(4, 0))
    govde.columnconfigure(0, weight=1)
    govde.rowconfigure(0, weight=1)

    tablo_cerceve, tablo = _gelir_tree(govde)
    tablo_cerceve.grid(row=0, column=0, sticky="nsew")

    stil = ttk.Style()
    stil.configure("GelirTablo.Treeview", font=("Segoe UI", 9), rowheight=24)
    stil.configure("GelirTablo.Treeview.Heading", font=("Segoe UI", 9, "bold"))
    tablo.configure(style="GelirTablo.Treeview")
    tablo.tag_configure("baslik", font=("Segoe UI", 9, "bold"), background="#d9e2ec")
    tablo.tag_configure("ara_toplam", font=("Segoe UI", 9, "bold"), background="#eef2f6")
    tablo.tag_configure("toplam", font=("Segoe UI", 10, "bold"), background="#c5d4e8")
    tablo.tag_configure("kalem", background="#ffffff")
    tablo.tag_configure("kalem_cift", background="#f4f7fa")
    tablo.tag_configure("pozitif", foreground="#1b7a3d")
    tablo.tag_configure("negatif", foreground="#c62828")
    tablo.tag_configure("notr", foreground="#222222")

    not_etiket = ttk.Label(app.icerik, text="", wraplength=900, foreground="#555555")
    not_etiket.pack(anchor="w", pady=(6, 0))

    def doldur():
        try:
            b = _tarih_oku(baslangic, zorunlu=True)
            e = _tarih_oku(bitis, zorunlu=True)
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=app)
            return
        if b > e:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=app)
            return
        try:
            veri = RaporService.gelir_tablosu(
                baslangic=b,
                bitis=e,
                maliyet_yontemi=yontem.get().strip() or "FIFO",
            )
        except Exception as hata:
            messagebox.showerror("Gelir Tablosu", str(hata), parent=app)
            return

        _tabloyu_doldur(tablo, veri["satirlar"])
        o = veri["ozet"]
        net = o["net_kar"]
        net_metin = f"Net kâr: {_para(net)}" if net >= 0 else f"Net zarar: {_para(abs(net))}"
        ozet_etiket.configure(
            text=(
                f"{veri['baslangic'].strftime('%d.%m.%Y')} – {veri['bitis'].strftime('%d.%m.%Y')}  |  "
                f"{veri['maliyet_yontemi']}  |  "
                f"Net satış: {_para(o['net_satislar'])}  |  "
                f"SMM: {_para(o['smm'])}  |  "
                f"Brüt kâr: {_para(o['brut_kar'])}  |  "
                f"{net_metin}"
            )
        )
        not_etiket.configure(text=veri.get("notlar") or "")

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yenile", command=doldur).pack(side="right")
    yontem.bind("<<ComboboxSelected>>", lambda _e: doldur())
    doldur()


def _gelir_tree(parent) -> tuple[ttk.Frame, ttk.Treeview]:
    cerceve = ttk.Frame(parent)
    kolonlar = ("kalem", "tutar")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    tablo.heading("kalem", text="Gelir / Gider kalemi", anchor="w")
    tablo.heading("tutar", text="Tutar", anchor="e")
    tablo.column("kalem", width=480, minwidth=200, anchor="w", stretch=True)
    tablo.column("tutar", width=150, minwidth=110, anchor="e", stretch=False)
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
