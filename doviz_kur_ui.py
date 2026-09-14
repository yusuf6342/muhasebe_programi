"""Döviz kuru yönetimi ekranı."""

from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from database.doviz_service import (
    DovizService,
    doviz_ayarlari_kaydet,
    doviz_ayarlari_yukle,
)
from ui_takvim import takvim_butonu


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.6f}".replace(",", "X").replace(".", ",").replace("X", ".")


def doviz_kur_yonetimi_goster(uygulama) -> None:
    uygulama._icerigi_temizle()
    ttk.Label(uygulama.icerik, text="DÖVİZ KURLARI", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        uygulama.icerik,
        text=(
            "USD ve EUR günlük kurları (döviz alış/satış + efektif alış/satış). "
            "TCMB'den çekilebilir veya manuel girilebilir."
        ),
        wraplength=760,
    ).pack(anchor="w", pady=(8, 12))

    ust = ttk.LabelFrame(uygulama.icerik, text="Kur İşlemleri", padding=8)
    ust.pack(fill="x", pady=(0, 8))

    tarih_var = tk.StringVar(value=datetime.now().strftime("%d.%m.%Y"))
    ttk.Label(ust, text="Tarih:").grid(row=0, column=0, padx=4, pady=4, sticky="w")
    tarih_giris = ttk.Entry(ust, textvariable=tarih_var, width=12)
    tarih_giris.grid(row=0, column=1, padx=4, pady=4, sticky="w")
    takvim_butonu(ust, tarih_giris, tarih_var)

    def tcmb_cek(bugun: bool = False):
        try:
            if bugun:
                tarih = datetime.now().date()
                tarih_var.set(tarih.strftime("%d.%m.%Y"))
            else:
                tarih = datetime.strptime(tarih_var.get(), "%d.%m.%Y").date()
            kayitlar = DovizService.tcmb_kurlari_cek(tarih)
            tabloyu_yenile()
            tcmb_t = kayitlar[0].get("tcmb_tarih") if kayitlar else tarih
            ekstra = ""
            if tcmb_t and tcmb_t != tarih:
                ekstra = (
                    f"\nTCMB bu gün için yayın yapmamış; "
                    f"{tcmb_t:%d.%m.%Y} kurları kullanıldı (hedef güne de kopyalandı)."
                )
            messagebox.showinfo(
                "TCMB",
                f"{len(kayitlar)} kur kaydı alındı ({tarih:%d.%m.%Y}).\n"
                f"Efektif alış/satış (Banknote) alanları da güncellendi.{ekstra}",
                parent=uygulama,
            )
        except ValueError as hata:
            messagebox.showerror("TCMB", str(hata), parent=uygulama)

    ttk.Button(ust, text="Bugünkü Kurları Çek", command=lambda: tcmb_cek(True)).grid(
        row=0, column=2, padx=8, pady=4
    )
    ttk.Button(ust, text="TCMB'den Güncelle", command=lambda: tcmb_cek(False)).grid(
        row=0, column=3, padx=4, pady=4
    )

    ayar = doviz_ayarlari_yukle()
    otomatik_var = tk.BooleanVar(value=bool(ayar.get("otomatik_tcmb_cek", True)))

    def otomatik_degisti():
        doviz_ayarlari_kaydet({"otomatik_tcmb_cek": otomatik_var.get()})

    ttk.Checkbutton(
        ust,
        text="Açılışta otomatik çek (bugün yoksa)",
        variable=otomatik_var,
        command=otomatik_degisti,
    ).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=4)

    manuel = ttk.LabelFrame(uygulama.icerik, text="Manuel Kur Girişi", padding=8)
    manuel.pack(fill="x", pady=(0, 8))

    pb_var = tk.StringVar(value="USD")
    ttk.Label(manuel, text="Para Birimi:").grid(row=0, column=0, padx=4, pady=4)
    ttk.Combobox(manuel, textvariable=pb_var, values=("USD", "EUR"), state="readonly", width=8).grid(
        row=0, column=1, padx=4, pady=4
    )
    alanlar = {}
    for i, (etiket, anahtar) in enumerate(
        (
            ("Döviz Alış", "forex_buying"),
            ("Döviz Satış", "forex_selling"),
            ("Efektif Alış", "effective_buying"),
            ("Efektif Satış", "effective_selling"),
        ),
        start=2,
    ):
        ttk.Label(manuel, text=etiket + ":").grid(row=0, column=i, padx=4, pady=4)
        alanlar[anahtar] = ttk.Entry(manuel, width=12)
        alanlar[anahtar].grid(row=0, column=i, padx=4, pady=4, sticky="w")

    def manuel_kaydet():
        try:
            from decimal import Decimal

            tarih = datetime.strptime(tarih_var.get(), "%d.%m.%Y").date()
            DovizService.kur_kaydet(
                tarih,
                pb_var.get(),
                Decimal(alanlar["forex_buying"].get().replace(",", ".") or "0"),
                Decimal(alanlar["forex_selling"].get().replace(",", ".") or "0"),
                Decimal(alanlar["effective_buying"].get().replace(",", ".") or "0"),
                Decimal(alanlar["effective_selling"].get().replace(",", ".") or "0"),
                source="MANUEL",
                manuel_koru=False,
            )
            tabloyu_yenile()
            messagebox.showinfo("Kur", "Manuel kur kaydedildi.", parent=uygulama)
        except ValueError as hata:
            messagebox.showerror("Kur", str(hata), parent=uygulama)

    ttk.Button(manuel, text="Kaydet", command=manuel_kaydet).grid(row=0, column=6, padx=8, pady=4)

    tablo_cerceve = ttk.Frame(uygulama.icerik)
    tablo_cerceve.pack(fill="both", expand=True, pady=8)
    kolonlar = ("tarih", "pb", "alis", "satis", "ef_alis", "ef_satis", "kaynak")
    tablo = ttk.Treeview(tablo_cerceve, columns=kolonlar, show="headings", height=18)
    basliklar = (
        ("tarih", "Tarih", 90),
        ("pb", "PB", 50),
        ("alis", "Döviz Alış", 110),
        ("satis", "Döviz Satış", 110),
        ("ef_alis", "Ef. Alış", 110),
        ("ef_satis", "Ef. Satış", 110),
        ("kaynak", "Kaynak", 80),
    )
    for k, b, w in basliklar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center" if k in ("tarih", "pb", "kaynak") else "e")
    kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    def tabloyu_yenile():
        tablo.delete(*tablo.get_children())
        for kayit in DovizService.kur_listele():
            tablo.insert(
                "",
                "end",
                values=(
                    kayit.rate_date.strftime("%d.%m.%Y"),
                    kayit.currency_code,
                    _para(kayit.forex_buying),
                    _para(kayit.forex_selling),
                    _para(kayit.effective_buying),
                    _para(kayit.effective_selling),
                    kayit.source,
                ),
            )

    tabloyu_yenile()
