"""TL işlemlerinin döviz bazında rapor ekranı."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.doviz_rapor_service import DovizRaporService
from database.models.doviz import RAPOR_KUR_YONTEMLERI
from ui_takvim import takvim_butonu


def _para(tutar, pb="") -> str:
    if tutar is None:
        return "—"
    metin = f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {pb}".strip()


def doviz_raporlari_goster(uygulama) -> None:
    uygulama._icerigi_temizle()
    try:
        from satis_tema import ekran_ust_cubugu, stil_uygula, treeview_stil
        from satis_ui import satis_raporlar_hub_goster

        stil_uygula(root=uygulama)
        govde = ekran_ust_cubugu(
            uygulama,
            "DÖVİZ BAZINDA RAPORLAR",
            alt_baslik="TL yekünlü faturaların USD/EUR karşılığı. Kur yöntemi sonucu etkiler.",
            geri_komut=lambda: satis_raporlar_hub_goster(uygulama),
            geri_metin="← Raporlar",
        )
    except Exception:
        govde = uygulama.icerik
        ttk.Label(govde, text="DÖVİZ BAZINDA RAPORLAR", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(
            govde,
            text="TL yekünlü faturaların USD/EUR karşılığı. Kur yöntemi rapor sonucunu doğrudan etkiler.",
            wraplength=760,
        ).pack(anchor="w", pady=(8, 12))

    filtre = ttk.LabelFrame(govde, text="Filtreler", padding=8)
    filtre.pack(fill="x", pady=(0, 8))

    bas_var = tk.StringVar()
    bit_var = tk.StringVar()
    rapor_pb = tk.StringVar(value="USD")
    kur_yontem = tk.StringVar(value="islem_tarihi")
    sabit_kur = tk.StringVar()

    ttk.Label(filtre, text="Başlangıç:").grid(row=0, column=0, padx=4, pady=4)
    bas_giris = ttk.Entry(filtre, textvariable=bas_var, width=12)
    bas_giris.grid(row=0, column=1, padx=4, pady=4)
    takvim_butonu(filtre, bas_giris, bas_var)

    ttk.Label(filtre, text="Bitiş:").grid(row=0, column=2, padx=4, pady=4)
    bit_giris = ttk.Entry(filtre, textvariable=bit_var, width=12)
    bit_giris.grid(row=0, column=3, padx=4, pady=4)
    takvim_butonu(filtre, bit_giris, bit_var)

    ttk.Label(filtre, text="Rapor PB:").grid(row=0, column=4, padx=4, pady=4)
    ttk.Combobox(filtre, textvariable=rapor_pb, values=("USD", "EUR"), state="readonly", width=8).grid(
        row=0, column=5, padx=4, pady=4
    )

    ttk.Label(filtre, text="Kur Yöntemi:").grid(row=1, column=0, padx=4, pady=4, sticky="w")
    yontem_kutu = ttk.Combobox(
        filtre,
        textvariable=kur_yontem,
        values=[k for k, _ in RAPOR_KUR_YONTEMLERI],
        state="readonly",
        width=22,
    )
    yontem_kutu.grid(row=1, column=1, columnspan=2, padx=4, pady=4, sticky="w")

    ttk.Label(filtre, text="Sabit Kur:").grid(row=1, column=3, padx=4, pady=4)
    ttk.Entry(filtre, textvariable=sabit_kur, width=12).grid(row=1, column=4, padx=4, pady=4)

    tablo_cerceve = ttk.Frame(govde)
    tablo_cerceve.pack(fill="both", expand=True, pady=8)
    kolonlar = (
        "fatura_no",
        "tarih",
        "cari",
        "f_pb",
        "f_kur",
        "tl_genel",
        "rapor_kur",
        "doviz_genel",
    )
    tablo = ttk.Treeview(tablo_cerceve, columns=kolonlar, show="headings", height=20)
    basliklar = (
        ("fatura_no", "Fatura No", 100),
        ("tarih", "Tarih", 90),
        ("cari", "Cari", 200),
        ("f_pb", "Fatura PB", 70),
        ("f_kur", "Fatura Kuru", 90),
        ("tl_genel", "TL Yekün", 100),
        ("rapor_kur", "Rapor Kuru", 90),
        ("doviz_genel", "Döviz Yekün", 100),
    )
    for k, b, w in basliklar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="e" if k not in ("fatura_no", "tarih", "cari", "f_pb") else "w")
    kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    ozet = ttk.Label(govde, text="", foreground="#1565c0")
    ozet.pack(anchor="w", pady=4)

    def raporla():
        tablo.delete(*tablo.get_children())
        try:
            bas = datetime.strptime(bas_var.get(), "%d.%m.%Y").date() if bas_var.get().strip() else None
            bit = datetime.strptime(bit_var.get(), "%d.%m.%Y").date() if bit_var.get().strip() else None
            sk = Decimal(sabit_kur.get().replace(",", ".")) if sabit_kur.get().strip() else None
            if kur_yontem.get() == "sabit_kur" and (not sk or sk <= 0):
                raise ValueError("Sabit kur yöntemi için geçerli bir kur girin.")
            satirlar = DovizRaporService.satis_fatura_doviz_raporu(
                baslangic=bas,
                bitis=bit,
                rapor_para_birimi=rapor_pb.get(),
                kur_yontemi=kur_yontem.get(),
                sabit_kur=sk,
            )
        except ValueError as hata:
            messagebox.showerror("Rapor", str(hata), parent=uygulama)
            return

        tl_toplam = Decimal("0")
        doviz_toplam = Decimal("0")
        for s in satirlar:
            tablo.insert(
                "",
                "end",
                values=(
                    s["fatura_no"],
                    s["fatura_tarihi"].strftime("%d.%m.%Y"),
                    f"{s['cari_kodu']} — {s['unvan']}",
                    s["fatura_para_birimi"],
                    _para(s["fatura_kuru"]),
                    _para(s["tl_genel_toplam"], "TL"),
                    _para(s["rapor_kuru"]) if s["rapor_kuru"] else "—",
                    _para(s["doviz_genel_toplam"], s["rapor_para_birimi"])
                    if s["doviz_genel_toplam"] is not None
                    else "—",
                ),
            )
            tl_toplam += s["tl_genel_toplam"]
            if s["doviz_genel_toplam"] is not None:
                doviz_toplam += s["doviz_genel_toplam"]
        ozet.configure(
            text=(
                f"{len(satirlar)} fatura | TL toplam: {_para(tl_toplam, 'TL')} | "
                f"{rapor_pb.get()} toplam: {_para(doviz_toplam, rapor_pb.get())}"
            )
        )

    ttk.Button(filtre, text="Raporla", command=raporla).grid(row=1, column=5, padx=8, pady=4)
    raporla()
