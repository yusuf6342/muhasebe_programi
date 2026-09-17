"""SATIŞLAR > RAPORLAR > SATIŞ KÂR ANALİZİ ekranı."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import filedialog, messagebox, ttk
from typing import Any

from database.access import kar_izinli, maliyet_izinli
from database.satis_kar_analiz_service import (
    MALIYET_YONTEMLERI,
    KarAnalizFiltre,
    SatisKarAnalizService,
)
from satis_tema import (
    ACIK_BG,
    BASARI,
    BEYAZ,
    CIZGI,
    IKINCIL,
    LACIVERT,
    METIN,
    SARI,
    UYARI,
    font,
    stil_uygula,
    tk_buton,
)


def _para(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _yuzde(v) -> str:
    if v is None:
        return "N/A"
    return f"%{_para(v)}"


def _tarih_parse(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def _ay_basi(d: date | None = None) -> date:
    d = d or date.today()
    return d.replace(day=1)


def _onceki_ay(d: date | None = None) -> tuple[date, date]:
    d = d or date.today()
    bitis = _ay_basi(d) - timedelta(days=1)
    return bitis.replace(day=1), bitis


def satis_kar_analizi_goster(app) -> None:
    if not (maliyet_izinli() and kar_izinli()):
        messagebox.showwarning(
            "Yetki",
            "Satış kâr analizi için maliyet ve kâr görme yetkisi gerekir.",
            parent=app,
        )
        return

    app._icerigi_temizle()
    stil_uygula(root=app)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satis_kar_analizi_goster(app))

    durum: dict[str, Any] = {"sonuc": None}

    ust = tk.Frame(app.icerik, bg=LACIVERT)
    ust.pack(fill="x")
    sol = tk.Frame(ust, bg=LACIVERT)
    sol.pack(side="left", fill="both", expand=True, padx=14, pady=10)
    tk.Label(sol, text="Satış Kâr Analizi", bg=LACIVERT, fg=BEYAZ, font=font(16, "bold", app), anchor="w").pack(
        anchor="w"
    )
    tk.Label(
        sol,
        text="Satışların maliyet, kâr, marj ve dönemsel değişimini analiz edin",
        bg=LACIVERT,
        fg=ACIK_BG,
        font=font(9, root=app),
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    tk.Frame(ust, bg=SARI, height=3).pack(fill="x")
    sag = tk.Frame(ust, bg=LACIVERT)
    sag.pack(side="right", padx=10, pady=8)
    tk_buton(sag, "← Raporlar", getattr(app, "satis_raporlari_goster", lambda: None), rol="geri").pack()

    arac = tk.Frame(app.icerik, bg=ACIK_BG)
    arac.pack(fill="x", padx=8, pady=(8, 0))

    bas_var = tk.StringVar(value=_ay_basi().strftime("%d.%m.%Y"))
    bit_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
    kbas_var = tk.StringVar(value="")
    kbit_var = tk.StringVar(value="")
    yontem_var = tk.StringVar(value="FIFO")
    karlilik_var = tk.StringVar(value="tumu")
    urun_var = tk.StringVar()
    depo_var = tk.StringVar()
    iade_var = tk.BooleanVar(value=True)
    dusuk_var = tk.StringVar(value="10")
    ozet_var = tk.StringVar(value="Filtreleri seçip Raporu Getir’e basın.")

    def _set_donem(b: date, e: date):
        bas_var.set(b.strftime("%d.%m.%Y"))
        bit_var.set(e.strftime("%d.%m.%Y"))

    for metin, fn in (
        ("Bu ay", lambda: _set_donem(_ay_basi(), date.today())),
        ("Geçen ay", lambda: _set_donem(*_onceki_ay())),
        (
            "Bu çeyrek",
            lambda: _set_donem(
                date.today().replace(month=((date.today().month - 1) // 3) * 3 + 1, day=1),
                date.today(),
            ),
        ),
        ("Bu yıl", lambda: _set_donem(date.today().replace(month=1, day=1), date.today())),
    ):
        tk_buton(arac, metin, fn, rol="ara").pack(side="left", padx=2)

    ttk.Label(arac, text="Yöntem:").pack(side="left", padx=(12, 4))
    ttk.Combobox(arac, textvariable=yontem_var, values=list(MALIYET_YONTEMLERI), width=28, state="readonly").pack(
        side="left"
    )

    filtre = tk.LabelFrame(app.icerik, text="Filtreler", bg=ACIK_BG, fg=METIN, padx=8, pady=6)
    filtre.pack(fill="x", padx=8, pady=8)

    def _satir(parent):
        f = tk.Frame(parent, bg=ACIK_BG)
        f.pack(fill="x", pady=2)
        return f

    s1 = _satir(filtre)
    ttk.Label(s1, text="Ana dönem:").pack(side="left")
    ttk.Entry(s1, textvariable=bas_var, width=11).pack(side="left", padx=4)
    ttk.Label(s1, text="—").pack(side="left")
    ttk.Entry(s1, textvariable=bit_var, width=11).pack(side="left", padx=4)
    ttk.Label(s1, text="Karşılaştırma:").pack(side="left", padx=(16, 4))
    ttk.Entry(s1, textvariable=kbas_var, width=11).pack(side="left", padx=4)
    ttk.Entry(s1, textvariable=kbit_var, width=11).pack(side="left", padx=4)

    def onceki_oner():
        try:
            b = _tarih_parse(bas_var.get())
            e = _tarih_parse(bit_var.get())
            if not b or not e:
                raise ValueError("Ana dönem gerekli")
            kb, ke = SatisKarAnalizService.onceki_es_donem(b, e)
            kbas_var.set(kb.strftime("%d.%m.%Y"))
            kbit_var.set(ke.strftime("%d.%m.%Y"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("Tarih", str(exc), parent=app)

    ttk.Button(s1, text="Önceki eş dönem", command=onceki_oner).pack(side="left", padx=6)

    s2 = _satir(filtre)
    ttk.Label(s2, text="Ürün:").pack(side="left")
    ttk.Entry(s2, textvariable=urun_var, width=18).pack(side="left", padx=4)
    ttk.Label(s2, text="Depo:").pack(side="left", padx=(8, 4))
    ttk.Entry(s2, textvariable=depo_var, width=14).pack(side="left", padx=4)
    ttk.Label(s2, text="Kârlılık:").pack(side="left", padx=(8, 4))
    ttk.Combobox(
        s2,
        textvariable=karlilik_var,
        values=("tumu", "karli", "dusuk_marj", "basa_bas", "zararina", "sifir_maliyet", "eksik_maliyet"),
        width=14,
        state="readonly",
    ).pack(side="left")
    ttk.Label(s2, text="Düşük marj %:").pack(side="left", padx=(8, 4))
    ttk.Entry(s2, textvariable=dusuk_var, width=6).pack(side="left")
    ttk.Checkbutton(s2, text="İadeleri dahil", variable=iade_var).pack(side="left", padx=10)

    s3 = _satir(filtre)
    tk_buton(s3, "Raporu Getir", lambda: _getir(), rol="kaydet").pack(side="left", padx=2)
    tk_buton(s3, "Karşılaştır", lambda: _getir(kars=True), rol="duzenle").pack(side="left", padx=2)
    tk_buton(s3, "Yenile", lambda: _getir(), rol="ara").pack(side="left", padx=2)
    tk_buton(s3, "Filtreleri Temizle", lambda: _temizle(), rol="geri").pack(side="left", padx=2)
    tk_buton(s3, "Excel", lambda: _excel(), rol="yeni").pack(side="left", padx=2)

    tk.Label(app.icerik, textvariable=ozet_var, bg=ACIK_BG, fg=IKINCIL, anchor="w", font=font(9, root=app)).pack(
        fill="x", padx=12
    )

    kpi = tk.Frame(app.icerik, bg=ACIK_BG)
    kpi.pack(fill="x", padx=8, pady=8)
    kpi_labels: dict[str, tk.Label] = {}

    def _kpi_kart(parent, anahtar, baslik):
        kart = tk.Frame(parent, bg=BEYAZ, highlightbackground=CIZGI, highlightthickness=1)
        kart.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(kart, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(8, root=app)).pack(anchor="w", padx=8, pady=(6, 0))
        lbl = tk.Label(kart, text="—", bg=BEYAZ, fg=LACIVERT, font=font(12, "bold", app))
        lbl.pack(anchor="w", padx=8, pady=(0, 6))
        kpi_labels[anahtar] = lbl

    for k, t in (
        ("net", "Net satış"),
        ("maliyet", "Satışların maliyeti"),
        ("kar", "Brüt kâr"),
        ("marj", "Kâr marjı"),
        ("markup", "Maliyet üzerine kâr"),
        ("miktar", "Net miktar"),
    ):
        _kpi_kart(kpi, k, t)

    uyari_cerceve = tk.Frame(app.icerik, bg=ACIK_BG)
    uyari_cerceve.pack(fill="x", padx=12)
    zarar_btn = tk.Button(
        uyari_cerceve, text="Zararına: 0", bg=BEYAZ, fg=UYARI, relief="groove", command=lambda: _sekme_ac("Zararına")
    )
    zarar_btn.pack(side="left", padx=4)
    sifir_btn = tk.Button(
        uyari_cerceve,
        text="Sıfır/eksik maliyet: 0",
        bg=BEYAZ,
        fg="#B26A00",
        relief="groove",
        command=lambda: _sekme_ac("Sıfır Maliyet"),
    )
    sifir_btn.pack(side="left", padx=4)

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, padx=8, pady=8)
    tablolar: dict[str, ttk.Treeview] = {}

    ozet_f = ttk.Frame(nb)
    nb.add(ozet_f, text="Özet")
    bulgu_lbl = tk.Label(ozet_f, text="", justify="left", anchor="nw", bg=ACIK_BG, fg=METIN, font=font(9, root=app))
    bulgu_lbl.pack(fill="x", padx=8, pady=8)
    grafik = tk.Canvas(ozet_f, height=180, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    grafik.pack(fill="x", padx=8, pady=(0, 8))

    def _tablo_sayfa(ad: str, kolonlar: list[tuple[str, str, int]]) -> None:
        f = ttk.Frame(nb)
        nb.add(f, text=ad)
        cols = [c[0] for c in kolonlar]
        tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        for kod, baslik, w in kolonlar:
            tree.heading(kod, text=baslik)
            tree.column(kod, width=w, anchor="w")
        sy = ttk.Scrollbar(f, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sy.set)
        tree.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        tablolar[ad] = tree

    _tablo_sayfa(
        "Ürünler",
        [
            ("kod", "Ürün kodu", 90),
            ("ad", "Ürün adı", 160),
            ("marka", "Marka", 80),
            ("mik", "Net miktar", 80),
            ("net", "Net satış", 90),
            ("mal", "Maliyet", 90),
            ("kar", "Brüt kâr", 90),
            ("marj", "Marj %", 70),
            ("markup", "Maliyet üzeri %", 90),
            ("durum", "Durum", 90),
        ],
    )
    _tablo_sayfa(
        "Müşteriler",
        [
            ("kod", "Cari kodu", 90),
            ("unvan", "Ünvan", 180),
            ("net", "Net satış", 90),
            ("mal", "Maliyet", 90),
            ("kar", "Kâr", 90),
            ("marj", "Marj %", 70),
            ("belge", "Belge", 60),
        ],
    )
    _tablo_sayfa(
        "Belgeler",
        [
            ("tur", "Tür", 60),
            ("no", "Belge no", 110),
            ("tarih", "Tarih", 90),
            ("cari", "Müşteri", 160),
            ("net", "Net", 90),
            ("mal", "Maliyet", 90),
            ("kar", "Kâr", 90),
            ("marj", "Marj %", 70),
        ],
    )
    _tablo_sayfa(
        "Zararına",
        [
            ("tarih", "Tarih", 90),
            ("belge", "Belge", 110),
            ("urun", "Ürün", 100),
            ("ad", "Ad", 140),
            ("net", "Net", 90),
            ("mal", "Maliyet", 90),
            ("zarar", "Zarar", 90),
            ("marj", "Marj %", 70),
        ],
    )
    _tablo_sayfa(
        "Sıfır Maliyet",
        [
            ("tarih", "Tarih", 90),
            ("belge", "Belge", 110),
            ("urun", "Ürün", 100),
            ("ad", "Ad", 140),
            ("net", "Net satış", 90),
            ("kod", "Hata kodu", 100),
            ("kaynak", "Kaynak", 140),
        ],
    )
    _tablo_sayfa(
        "Karşılaştırma",
        [
            ("gosterge", "Gösterge", 140),
            ("d1", "Dönem 1", 100),
            ("d2", "Dönem 2", 100),
            ("fark", "Fark", 100),
            ("degisim", "Değişim", 100),
            ("yon", "Yön", 80),
            ("g1", "Günlük D1", 90),
            ("g2", "Günlük D2", 90),
        ],
    )
    _tablo_sayfa(
        "Veri Kalitesi",
        [
            ("tarih", "Tarih", 90),
            ("belge", "Belge", 110),
            ("urun", "Ürün", 100),
            ("kod", "Hata", 100),
            ("net", "Net", 90),
            ("aciklama", "Açıklama", 200),
        ],
    )

    durum_cubugu = tk.Label(app.icerik, text="", anchor="w", bg=ACIK_BG, fg=IKINCIL, font=font(8, root=app))
    durum_cubugu.pack(fill="x", padx=10, pady=(0, 6))

    def _sekme_ac(ad: str):
        for i in range(nb.index("end")):
            if nb.tab(i, "text") == ad:
                nb.select(i)
                break

    def _temizle():
        _set_donem(_ay_basi(), date.today())
        kbas_var.set("")
        kbit_var.set("")
        urun_var.set("")
        depo_var.set("")
        karlilik_var.set("tumu")
        yontem_var.set("FIFO")
        iade_var.set(True)
        dusuk_var.set("10")

    def _filtre_olustur(*, kars: bool = False) -> KarAnalizFiltre:
        b = _tarih_parse(bas_var.get())
        e = _tarih_parse(bit_var.get())
        if not b or not e:
            raise ValueError("Ana dönem başlangıç ve bitiş zorunludur (gg.aa.yyyy).")
        kb = kb2 = None
        if kars or (kbas_var.get().strip() and kbit_var.get().strip()):
            kb = _tarih_parse(kbas_var.get())
            kb2 = _tarih_parse(kbit_var.get())
            if not kb or not kb2:
                raise ValueError("Karşılaştırma dönemi için iki tarih girin.")
        try:
            esik = Decimal(dusuk_var.get().replace(",", ".") or "10")
        except InvalidOperation as exc:
            raise ValueError("Düşük marj eşiği sayısal olmalı.") from exc
        return KarAnalizFiltre(
            baslangic=b,
            bitis=e,
            maliyet_yontemi=yontem_var.get(),
            kars_baslangic=kb,
            kars_bitis=kb2,
            urun=urun_var.get().strip() or None,
            depo=depo_var.get().strip() or None,
            karlilik=karlilik_var.get(),
            dusuk_marj_esigi=esik,
            iadeleri_dahil=bool(iade_var.get()),
        )

    def _grafik_ciz(sonuc):
        grafik.delete("all")
        data = sonuc.gunluk[-30:]
        if not data:
            grafik.create_text(20, 20, anchor="nw", text="Grafik için veri yok.", fill=IKINCIL)
            return
        w = max(grafik.winfo_width(), 600)
        h = 180
        pad = 30
        max_v = max((float(abs(d["net"])) for d in data), default=1) or 1
        n = len(data)
        bw = max(4, (w - 2 * pad) // max(n, 1) - 2)
        for i, d in enumerate(data):
            x = pad + i * (bw + 2)
            nh = int((float(d["net"]) / max_v) * (h - 50))
            kh = int((float(d["kar"]) / max_v) * (h - 50))
            grafik.create_rectangle(x, h - 20 - nh, x + bw // 2, h - 20, fill=LACIVERT, outline="")
            renk = BASARI if d["kar"] >= 0 else UYARI
            grafik.create_rectangle(x + bw // 2, h - 20 - kh, x + bw, h - 20, fill=renk, outline="")
        grafik.create_text(8, 8, anchor="nw", text="Son günler: lacivert=net satış, yeşil/kırmızı=kâr", fill=IKINCIL)

    def _doldur(sonuc):
        durum["sonuc"] = sonuc
        o = sonuc.ozet
        kpi_labels["net"].configure(text=f"{_para(o['net_satis'])} TL")
        kpi_labels["maliyet"].configure(text=f"{_para(o['maliyet'])} TL")
        kpi_labels["kar"].configure(
            text=f"{_para(o['brut_kar'])} TL",
            fg=BASARI if o["brut_kar"] >= 0 else UYARI,
        )
        kpi_labels["marj"].configure(text=_yuzde(o["kar_marji"]))
        kpi_labels["markup"].configure(text=_yuzde(o["maliyet_uzeri_kar"]))
        kpi_labels["miktar"].configure(text=_para(o["net_miktar"]))
        zarar_btn.configure(text=f"Zararına: {o['zarar_adet']} / {_para(o['zarar_toplam'])} TL")
        sifir_btn.configure(text=f"Sıfır/eksik maliyet: {o['sifir_satir']} satır ({o['sifir_urun']} ürün)")
        ozet_var.set(
            f"Dönem {sonuc.filtre.baslangic:%d.%m.%Y}–{sonuc.filtre.bitis:%d.%m.%Y}  |  "
            f"Yöntem: {sonuc.filtre.maliyet_yontemi}  |  "
            f"Belgeler: {o['belge_sayisi']}  |  Satırlar: {o['satir_sayisi']}"
        )
        bulgu_lbl.configure(text="\n".join(f"• {b}" for b in sonuc.bulgular) or "Belirgin bulgu yok.")
        app.after(50, lambda: _grafik_ciz(sonuc))

        def clear(ad):
            t = tablolar[ad]
            for i in t.get_children():
                t.delete(i)

        clear("Ürünler")
        for u in sonuc.urunler:
            tablolar["Ürünler"].insert(
                "",
                "end",
                values=(
                    u["urun_kodu"],
                    u["urun_adi"],
                    u["marka"],
                    _para(u["net_miktar"]),
                    _para(u["net"]),
                    _para(u["maliyet"]),
                    _para(u["kar"]),
                    _yuzde(u["kar_marji"]),
                    _yuzde(u["maliyet_uzeri_kar"]),
                    u["durum"],
                ),
            )
        clear("Müşteriler")
        for m in sonuc.musteriler:
            tablolar["Müşteriler"].insert(
                "",
                "end",
                values=(
                    m["cari_kodu"],
                    m["unvan"],
                    _para(m["net"]),
                    _para(m["maliyet"]),
                    _para(m["kar"]),
                    _yuzde(m["kar_marji"]),
                    m["belge_sayisi"],
                ),
            )
        clear("Belgeler")
        for b in sonuc.belgeler:
            tablolar["Belgeler"].insert(
                "",
                "end",
                values=(
                    b["belge_turu"],
                    b["belge_no"],
                    b["tarih"].strftime("%d.%m.%Y"),
                    b["cari_unvan"],
                    _para(b["net"]),
                    _para(b["maliyet"]),
                    _para(b["kar"]),
                    _yuzde(b["kar_marji"]),
                ),
            )
        clear("Zararına")
        for s in sonuc.zararina:
            tablolar["Zararına"].insert(
                "",
                "end",
                values=(
                    s.tarih.strftime("%d.%m.%Y"),
                    s.belge_no,
                    s.urun_kodu,
                    s.urun_adi,
                    _para(s.net_satis),
                    _para(s.toplam_maliyet),
                    _para(s.brut_kar),
                    _yuzde(s.kar_marji),
                ),
            )
        clear("Sıfır Maliyet")
        for s in sonuc.sifir_maliyet:
            tablolar["Sıfır Maliyet"].insert(
                "",
                "end",
                values=(
                    s.tarih.strftime("%d.%m.%Y"),
                    s.belge_no,
                    s.urun_kodu,
                    s.urun_adi,
                    _para(s.net_satis),
                    s.maliyet_kodu,
                    s.maliyet_kaynagi,
                ),
            )
        clear("Veri Kalitesi")
        for s in sonuc.veri_kalitesi:
            tablolar["Veri Kalitesi"].insert(
                "",
                "end",
                values=(
                    s.tarih.strftime("%d.%m.%Y"),
                    s.belge_no,
                    s.urun_kodu,
                    s.maliyet_kodu,
                    _para(s.net_satis),
                    s.maliyet_kaynagi,
                ),
            )
        clear("Karşılaştırma")
        if sonuc.karsilastirma:
            if sonuc.karsilastirma.get("uyari"):
                ozet_var.set(ozet_var.get() + "  |  " + sonuc.karsilastirma["uyari"])
            for ad, g in sonuc.karsilastirma["gostergeler"].items():
                tablolar["Karşılaştırma"].insert(
                    "",
                    "end",
                    values=(
                        ad,
                        _para(g.get("donem1")) if isinstance(g.get("donem1"), Decimal) else g.get("donem1"),
                        _para(g.get("donem2")) if isinstance(g.get("donem2"), Decimal) else g.get("donem2"),
                        _para(g.get("fark")) if isinstance(g.get("fark"), Decimal) else g.get("fark"),
                        g.get("etiket"),
                        g.get("yon"),
                        _para(g.get("gunluk1")) if g.get("gunluk1") is not None else "",
                        _para(g.get("gunluk2")) if g.get("gunluk2") is not None else "",
                    ),
                )

        durum_cubugu.configure(
            text=(
                f"Kayıt: {o['satir_sayisi']}  |  Sorgu: {sonuc.sorgu_ms} ms  |  "
                f"Yenileme: {sonuc.yenileme.strftime('%d.%m.%Y %H:%M:%S') if sonuc.yenileme else ''}"
            )
        )

    def _getir(*, kars: bool = False):
        try:
            filtre = _filtre_olustur(kars=kars)
            sonuc = SatisKarAnalizService.analiz(filtre)
            _doldur(sonuc)
            if kars and sonuc.karsilastirma:
                _sekme_ac("Karşılaştırma")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Satış Kâr Analizi", str(exc), parent=app)

    def _excel():
        sonuc = durum.get("sonuc")
        if not sonuc:
            messagebox.showinfo("Excel", "Önce raporu getirin.", parent=app)
            return
        yol = filedialog.asksaveasfilename(
            title="Excel kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"satis_kar_analizi_{date.today():%Y%m%d}.xlsx",
        )
        if not yol:
            return
        try:
            SatisKarAnalizService.excel_aktar(sonuc, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Excel", str(exc), parent=app)
