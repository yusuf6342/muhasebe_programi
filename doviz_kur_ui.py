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
    try:
        from satis_tema import ekran_ust_cubugu, stil_uygula, treeview_stil
        from satis_ui import satis_raporlar_hub_goster

        stil_uygula(root=uygulama)
        govde = ekran_ust_cubugu(
            uygulama,
            "DÖVİZ KURLARI",
            alt_baslik="USD ve EUR günlük kurları (döviz alış/satış + efektif). TCMB veya manuel.",
            geri_komut=lambda: satis_raporlar_hub_goster(uygulama),
            geri_metin="← Raporlar",
        )
    except Exception:
        govde = uygulama.icerik
        ttk.Label(govde, text="DÖVİZ KURLARI", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(
            govde,
            text=(
                "USD ve EUR günlük kurları (döviz alış/satış + efektif alış/satış). "
                "TCMB'den çekilebilir veya manuel girilebilir."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(8, 12))

    ust = ttk.LabelFrame(govde, text="Kur İşlemleri", padding=8)
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

    aralik = ttk.LabelFrame(govde, text="Tarih aralığı (TCMB arşiv)", padding=8)
    aralik.pack(fill="x", pady=(0, 8))
    bas_var = tk.StringVar(value="01.01.2025")
    bit_var = tk.StringVar(value=datetime.now().strftime("%d.%m.%Y"))
    ttk.Label(aralik, text="Başlangıç:").grid(row=0, column=0, padx=4, pady=4, sticky="w")
    bas_giris = ttk.Entry(aralik, textvariable=bas_var, width=12)
    bas_giris.grid(row=0, column=1, padx=4, pady=4, sticky="w")
    takvim_butonu(aralik, bas_giris, bas_var)
    ttk.Label(aralik, text="Bitiş:").grid(row=0, column=2, padx=4, pady=4, sticky="w")
    bit_giris = ttk.Entry(aralik, textvariable=bit_var, width=12)
    bit_giris.grid(row=0, column=3, padx=4, pady=4, sticky="w")
    takvim_butonu(aralik, bit_giris, bit_var)
    durum_lbl = ttk.Label(aralik, text="")
    durum_lbl.grid(row=1, column=0, columnspan=6, sticky="w", padx=4)

    def _aralik_calistir(yalniz_eksik: bool):
        try:
            bas = datetime.strptime(bas_var.get(), "%d.%m.%Y").date()
            bit = datetime.strptime(bit_var.get(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihler GG.AA.YYYY formatında olmalı.", parent=uygulama)
            return

        def _ilerleme(sira, toplam, mesaj):
            durum_lbl.configure(text=f"{sira}/{toplam}: {mesaj}")
            durum_lbl.update_idletasks()

        try:
            if yalniz_eksik:
                sonuc = DovizService.eksik_gunleri_tamamla(bas, bit, ilerleme_cb=_ilerleme)
            else:
                sonuc = DovizService.tcmb_aralik_cek(bas, bit, ilerleme_cb=_ilerleme)
            tabloyu_yenile()
            messagebox.showinfo(
                "TCMB aralık",
                f"Başarı: {sonuc['basari']} · Atlandı: {sonuc['atlandi']} · Hata: {sonuc['hata']}",
                parent=uygulama,
            )
        except ValueError as hata:
            messagebox.showerror("TCMB aralık", str(hata), parent=uygulama)

    ttk.Button(
        aralik, text="Aralığı TCMB'den Çek", command=lambda: _aralik_calistir(False)
    ).grid(row=0, column=4, padx=8, pady=4)
    ttk.Button(
        aralik, text="Eksik günleri tamamla", command=lambda: _aralik_calistir(True)
    ).grid(row=0, column=5, padx=4, pady=4)

    manuel = ttk.LabelFrame(govde, text="Manuel Kur Girişi", padding=8)
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

    tablo_cerceve = ttk.Frame(govde)
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
    baslik_map = {k: b for k, b, _w in basliklar}
    for k, b, w in basliklar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center" if k in ("tarih", "pb", "kaynak") else "e")
    kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    from liste_filtre_ui import satir_kolon_filtre_uygun, treeview_filtre_bagla

    _liste_filtre: dict = {}
    _ham_satirlar: list = []

    def tabloyu_yenile():
        tablo.delete(*tablo.get_children())
        _ham_satirlar.clear()
        for kayit in DovizService.kur_listele():
            values = (
                kayit.rate_date.strftime("%d.%m.%Y"),
                kayit.currency_code,
                _para(kayit.forex_buying),
                _para(kayit.forex_selling),
                _para(kayit.effective_buying),
                _para(kayit.effective_selling),
                kayit.source,
            )
            _ham_satirlar.append({"values": values})
            if not satir_kolon_filtre_uygun(values, kolonlar, _liste_filtre):
                continue
            tablo.insert("", "end", values=values)
        _filtre_bag["guncelle_basliklar"]()

    _filtre_bag = treeview_filtre_bagla(
        tablo,
        baslik_map,
        get_filtre_dict=lambda: _liste_filtre,
        set_filtre_dict=None,
        yenile_cb=tabloyu_yenile,
        deger_listesi_cb=lambda: _ham_satirlar,
        parent=uygulama,
        kolonlar=kolonlar,
    )
    tabloyu_yenile()
