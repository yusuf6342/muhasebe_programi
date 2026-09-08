"""Toplu fiyat değişikliği — baz fiyata ±% ile satış fiyatı güncelleme."""

from __future__ import annotations

from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.satis_siparisi_service import decimal
from database.stok_service import SATIS_FIYAT_ADLARI, STOK_FIYAT_ADLARI, StokService


def _para(tutar):
    if tutar is None:
        return "—"
    t = Decimal(str(tutar))
    if t >= 1:
        return f"{int(t):,} TL".replace(",", ".")
    return f"{t:.3f} TL".replace(".", ",")


def _degisim_ozet(degisimler):
    parcalar = []
    for d in degisimler:
        kisa = d["fiyat_adi"].replace("SATIŞ FİYATI ", "SF")
        parcalar.append(f"{kisa} {_para(d['eski'])}→{_para(d['yeni'])} (%{d['yuzde']:g})")
    return " · ".join(parcalar)


def toplu_fiyat_sayfasi_goster(app):
    app._icerigi_temizle()
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")

    ttk.Label(app.icerik, text="TOPLU FİYAT DEĞİŞİKLİĞİ", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "Rapor grubu ve stok adı aralığı ile filtreleyin (boş = tüm stoklar). "
            "Önizlemede işaretlenen stoklara yüzde uygulanır. "
            "≥1 TL → kuruş yok (yukarı yuvarlama); <1 TL → 3 ondalık."
        ),
        wraplength=960,
        justify="left",
    ).pack(anchor="w", pady=(10, 6))

    # --- Arama kriterleri ---
    filtre = ttk.LabelFrame(app.icerik, text="Arama kriterleri", padding=10)
    filtre.pack(fill="x", pady=4)

    rapor_listesi = ["(Tümü)"] + StokService.secenekleri_listele("rapor_grubu")
    stok_adlari = sorted(
        {(s.stok_adi or "").strip() for s in StokService.stoklari_ara() if (s.stok_adi or "").strip()},
        key=lambda a: a.casefold(),
    )
    ad_degerleri = ["(Tümü)"] + stok_adlari

    ttk.Label(filtre, text="Rapor grubu:").grid(row=0, column=0, sticky="w")
    rapor_grubu = ttk.Combobox(filtre, values=rapor_listesi, state="readonly", width=16)
    rapor_grubu.set("(Tümü)")
    rapor_grubu.grid(row=0, column=1, sticky="w", padx=(4, 16))

    ttk.Label(filtre, text="Stok adı (başlangıç):").grid(row=0, column=2, sticky="w")
    ad_baslangic = ttk.Combobox(filtre, values=ad_degerleri, width=28)
    ad_baslangic.set("(Tümü)")
    ad_baslangic.grid(row=0, column=3, sticky="w", padx=(4, 16))

    ttk.Label(filtre, text="Stok adı (bitiş):").grid(row=0, column=4, sticky="w")
    ad_bitis = ttk.Combobox(filtre, values=ad_degerleri, width=28)
    ad_bitis.set("(Tümü)")
    ad_bitis.grid(row=0, column=5, sticky="w", padx=4)

    ttk.Label(filtre, text="Kod / barkod ara:").grid(row=1, column=0, sticky="w", pady=(8, 0))
    arama = ttk.Entry(filtre, width=18)
    arama.grid(row=1, column=1, sticky="w", padx=(4, 16), pady=(8, 0))

    ttk.Label(filtre, text="Baz fiyat:").grid(row=1, column=2, sticky="w", pady=(8, 0))
    baz = ttk.Combobox(filtre, values=list(STOK_FIYAT_ADLARI), state="readonly", width=22)
    baz.set("ALIŞ FİYATI")
    baz.grid(row=1, column=3, sticky="w", padx=(4, 16), pady=(8, 0))

    ttk.Button(filtre, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).grid(
        row=1, column=5, sticky="e", pady=(8, 0)
    )

    # --- Yüzde ayarı ---
    ayar = ttk.LabelFrame(app.icerik, text="Yüzde ayarı (±)", padding=10)
    ayar.pack(fill="x", padx=0, pady=6)

    mod = tk.StringVar(value="tek")
    ttk.Radiobutton(ayar, text="Tek yüzde → tüm seçili satış fiyatlarına", variable=mod, value="tek").grid(
        row=0, column=0, columnspan=4, sticky="w"
    )
    ttk.Label(ayar, text="Yüzde %:").grid(row=1, column=0, sticky="w", pady=4)
    tek_yuzde = ttk.Entry(ayar, width=10)
    tek_yuzde.insert(0, "20")
    tek_yuzde.grid(row=1, column=1, sticky="w", padx=4)
    ttk.Label(ayar, text="(Örn. 20 = +%20,  -10 = −%10)", foreground="#666").grid(
        row=1, column=2, sticky="w", padx=8
    )

    ttk.Radiobutton(
        ayar, text="Her satış fiyatına ayrı yüzde", variable=mod, value="ayri"
    ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 2))

    yuzde_alanlari = {}
    secim_var = {}
    for i, ad in enumerate(SATIS_FIYAT_ADLARI):
        r, c = 3 + i // 5, (i % 5) * 3
        var = tk.BooleanVar(value=(i < 4))
        secim_var[ad] = var
        ttk.Checkbutton(ayar, text=ad.replace("SATIŞ FİYATI ", "SF"), variable=var).grid(
            row=r, column=c, sticky="w", padx=2, pady=2
        )
        ent = ttk.Entry(ayar, width=7)
        ent.insert(0, "20")
        ent.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=2)
        yuzde_alanlari[ad] = ent

    def _mod_guncelle(*_a):
        tek = mod.get() == "tek"
        tek_yuzde.configure(state="normal" if tek else "disabled")
        for ent in yuzde_alanlari.values():
            ent.configure(state="disabled" if tek else "normal")

    mod.trace_add("write", _mod_guncelle)
    _mod_guncelle()

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=4)
    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w")

    # --- Önizleme tablosu (stok bazında seçim) ---
    orta = ttk.Frame(app.icerik)
    orta.pack(fill="both", expand=True, pady=6)
    kolonlar = ("sec", "kod", "ad", "grup", "baz", "degisim")
    tablo = ttk.Treeview(orta, columns=kolonlar, show="headings", height=14, selectmode="extended")
    for k, b, w in (
        ("sec", "Seç", 45),
        ("kod", "Stok Kodu", 100),
        ("ad", "Stok Adı", 200),
        ("grup", "Rapor Grubu", 100),
        ("baz", "Baz Fiyat", 90),
        ("degisim", "Fiyat değişimi", 420),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    tablo.column("sec", width=45, anchor="center", stretch=False)
    kaydirma = ttk.Scrollbar(orta, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    app._toplu_fiyat_onizleme = []
    secimler: dict[int, dict] = {}  # stok_id -> kayit

    def _filtre_deger(kutu):
        deger = (kutu.get() or "").strip()
        return "" if deger in ("", "(Tümü)") else deger

    def _yuzdeleri_al():
        secilen = [ad for ad, v in secim_var.items() if v.get()]
        if not secilen:
            raise ValueError("En az bir satış fiyatı işaretleyin.")
        if mod.get() == "tek":
            y = decimal(tek_yuzde.get() or 0, "Yüzde", Decimal("0"))
            return {ad: y for ad in secilen}
        sonuc = {}
        for ad in secilen:
            sonuc[ad] = decimal(yuzde_alanlari[ad].get() or 0, f"{ad} %", Decimal("0"))
        return sonuc

    def _secim_guncelle(stok_id, isaretli):
        kayit = next((k for k in app._toplu_fiyat_onizleme if k["stok_id"] == stok_id), None)
        if not kayit:
            return
        iid = str(stok_id)
        if isaretli:
            secimler[stok_id] = kayit
            tablo.set(iid, "sec", "☑")
        else:
            secimler.pop(stok_id, None)
            tablo.set(iid, "sec", "☐")

    def _secim_tikla(event):
        if tablo.identify_region(event.x, event.y) != "cell":
            return
        if tablo.identify_column(event.x) != "#1":
            return
        satir = tablo.identify_row(event.y)
        if not satir:
            return
        stok_id = int(satir)
        _secim_guncelle(stok_id, stok_id not in secimler)
        return "break"

    tablo.bind("<Button-1>", _secim_tikla)

    def tumunu_sec():
        for k in app._toplu_fiyat_onizleme:
            _secim_guncelle(k["stok_id"], True)
        ozet_guncelle()

    def secimi_temizle():
        for k in list(secimler):
            _secim_guncelle(k, False)
        ozet_guncelle()

    def ozet_guncelle():
        toplam = len(app._toplu_fiyat_onizleme)
        secili = len(secimler)
        ozet.configure(
            text=(
                f"{toplam} stok listelendi · {secili} seçili · Baz: {baz.get()} · "
                "Yuvarlama: ≥1 TL tam TL↑, <1 TL 3 hane"
            )
        )

    def onizle():
        try:
            yuzdeler = _yuzdeleri_al()
            kayitlar = StokService.toplu_fiyat_onizle(
                baz.get(),
                yuzdeler,
                stok_filtre=arama.get(),
                rapor_grubu=_filtre_deger(rapor_grubu),
                ad_baslangic=_filtre_deger(ad_baslangic),
                ad_bitis=_filtre_deger(ad_bitis),
            )
        except ValueError as hata:
            messagebox.showerror("Önizleme", str(hata), parent=app)
            return
        app._toplu_fiyat_onizleme = kayitlar
        secimler.clear()
        for item in tablo.get_children():
            tablo.delete(item)
        for k in kayitlar:
            iid = str(k["stok_id"])
            tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    "☑",
                    k["stok_kodu"],
                    (k["stok_adi"] or "")[:40],
                    k.get("rapor_grubu") or "—",
                    _para(k["baz_fiyat"]),
                    _degisim_ozet(k["degisimler"]),
                ),
            )
            secimler[k["stok_id"]] = k
        ozet_guncelle()

    def uygula():
        if not getattr(app, "_toplu_fiyat_onizleme", None):
            onizle()
        if not getattr(app, "_toplu_fiyat_onizleme", None):
            return
        if not secimler:
            messagebox.showwarning(
                "Seçim",
                "Uygulanacak stok seçin (satır başındaki kutuya tıklayın).",
                parent=app,
            )
            return
        if not messagebox.askyesno(
            "Onay",
            f"{len(secimler)} seçili stok kartında satış fiyatları güncellensin mi?\n"
            "İşlem fiyat geçmişine yazılır.",
            parent=app,
        ):
            return
        try:
            yuzdeler = _yuzdeleri_al()
            sonuc = StokService.toplu_fiyat_uygula(
                baz.get(),
                yuzdeler,
                stok_filtre=arama.get(),
                rapor_grubu=_filtre_deger(rapor_grubu),
                ad_baslangic=_filtre_deger(ad_baslangic),
                ad_bitis=_filtre_deger(ad_bitis),
                stok_idler=list(secimler.keys()),
            )
        except ValueError as hata:
            messagebox.showerror("Uygulama", str(hata), parent=app)
            return
        messagebox.showinfo(
            "Tamam",
            f"{sonuc['stok_adet']} stok kartı güncellendi.",
            parent=app,
        )
        onizle()

    ttk.Button(butonlar, text="Önizle", command=onizle).pack(side="left")
    ttk.Button(butonlar, text="Tümünü Seç", command=tumunu_sec).pack(side="left", padx=6)
    ttk.Button(butonlar, text="Seçimi Temizle", command=secimi_temizle).pack(side="left")
    ttk.Button(butonlar, text="Seçilenleri Uygula", command=uygula).pack(side="left", padx=12)
