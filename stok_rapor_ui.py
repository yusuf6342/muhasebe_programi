"""Stoklar → Raporlar alt menüsü ve rapor ekranları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.cari_service import CariService
from database.rapor_service import MALIYET_YONTEMLERI_RAPOR, RaporService
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService
from ui_takvim import takvim_butonu


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _tarih_oku(entry, zorunlu=False):
    metin = entry.get().strip()
    if not metin:
        if zorunlu:
            raise ValueError("Tarih zorunludur.")
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def _stok_menu_isaretle(app):
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")


def _tablo(parent, kolonlar, basliklar, genislikler=None):
    cerceve = ttk.Frame(parent)
    cerceve.pack(fill="both", expand=True, pady=(8, 0))
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings")
    for i, (kolon, baslik) in enumerate(zip(kolonlar, basliklar)):
        tablo.heading(kolon, text=baslik)
        tablo.column(kolon, width=(genislikler[i] if genislikler else 120), anchor="w")
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)
    return tablo


def stok_raporlari_menusu_goster(app):
    app._icerigi_temizle()
    _stok_menu_isaretle(app)
    ttk.Label(app.icerik, text="STOK RAPORLARI", style="Baslik.TLabel").pack(anchor="w")
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("STOK ENVANTER RAPORU", lambda: rapor_envanter(app)),
        ("STOKLAR KAR / ZARAR RAPORU", lambda: rapor_kar_zarar(app)),
        ("SATILMAYAN ÜRÜNLER RAPORU", lambda: rapor_satilmayan(app)),
        ("STOK DEVİR HIZI", lambda: rapor_devir(app)),
        ("STOK HAREKET RAPORU", lambda: rapor_hareket(app)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )
    ttk.Button(app.icerik, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).pack(
        anchor="w", pady=(16, 0)
    )


def _rapor_ust(app, baslik):
    app._icerigi_temizle()
    _stok_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Stok Raporları", command=lambda: stok_raporlari_menusu_goster(app)).pack(
        side="right"
    )
    return ust


def rapor_envanter(app):
    _rapor_ust(app, "STOK ENVANTER RAPORU")
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(10, 4))

    ttk.Label(filtre, text="Tarih:").pack(side="left")
    tarih_c = ttk.Frame(filtre)
    tarih_c.pack(side="left", padx=4)
    tarih = ttk.Entry(tarih_c, width=12)
    tarih.pack(side="left")
    tarih.insert(0, _tarih(date.today()))
    takvim_butonu(tarih_c, tarih)

    ttk.Label(filtre, text="Maliyet:").pack(side="left", padx=(10, 2))
    maliyet = ttk.Combobox(filtre, values=MALIYET_YONTEMLERI_RAPOR, state="readonly", width=28)
    maliyet.set("FIFO")
    maliyet.pack(side="left", padx=4)

    depolar = ["(Tümü)"] + [d.ad for d in StokService.depolar()]
    ttk.Label(filtre, text="Depo:").pack(side="left", padx=(10, 2))
    depo = ttk.Combobox(filtre, values=depolar, state="readonly", width=16)
    depo.set("(Tümü)")
    depo.pack(side="left", padx=4)

    ttk.Label(filtre, text="Stok:").pack(side="left", padx=(10, 2))
    stok = ttk.Entry(filtre, width=14)
    stok.pack(side="left", padx=4)

    ozet = ttk.Label(app.icerik, text="Tarih ve maliyet yöntemini seçip raporu getirin.")
    ozet.pack(anchor="w", pady=4)
    tablo = _tablo(
        app.icerik,
        ("kod", "ad", "tur", "depo", "birim", "miktar", "maliyet", "tutar"),
        ("Stok Kodu", "Stok Adı", "Tür", "Depo", "Birim", "Miktar", "Birim Maliyet", "Tutar"),
        (100, 200, 90, 100, 60, 80, 110, 110),
    )

    def getir():
        try:
            t = _tarih_oku(tarih, zorunlu=True)
        except ValueError as hata:
            messagebox.showerror("Tarih", str(hata), parent=app)
            return
        depo_adi = None if depo.get() == "(Tümü)" else depo.get()
        rapor = RaporService.stok_envanter(
            tarih=t,
            maliyet_yontemi=maliyet.get(),
            depo_adi=depo_adi,
            stok_filtre=stok.get().strip() or None,
        )
        ozet.configure(
            text=(
                f"Tarih: {_tarih(rapor['tarih'])}  |  {rapor['maliyet_yontemi']}  |  "
                f"Satır: {len(rapor['satirlar'])}  |  "
                f"Toplam tutar: {_para(rapor['toplam_tutar'])}"
            )
        )
        for item in tablo.get_children():
            tablo.delete(item)
        for s in rapor["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    s["stok_kodu"], s["stok_adi"], s["kart_turu"], s["depo"], s["birim"],
                    s["miktar"], _para(s["birim_maliyet"]), _para(s["tutar"]),
                ),
            )

    ttk.Button(filtre, text="Raporu Getir", command=getir).pack(side="left", padx=10)
    getir()


def rapor_kar_zarar(app):
    _rapor_ust(app, "STOKLAR KAR / ZARAR RAPORU")
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(10, 4))

    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    baslangic = ttk.Entry(b_c, width=11)
    baslangic.pack(side="left")
    baslangic.insert(0, _tarih(date.today().replace(day=1)))
    takvim_butonu(b_c, baslangic)

    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(8, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bitis = ttk.Entry(e_c, width=11)
    bitis.pack(side="left")
    bitis.insert(0, _tarih(date.today()))
    takvim_butonu(e_c, bitis)

    filtre2 = ttk.Frame(app.icerik)
    filtre2.pack(fill="x", pady=4)

    musteriler = CariService.listele(cari_turu="Müşteri")
    cari_map = {"(Tümü)": None}
    cari_map.update({f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in musteriler})
    ttk.Label(filtre2, text="Cari:").pack(side="left")
    cari = ttk.Combobox(filtre2, values=list(cari_map), width=28, state="readonly")
    cari.set("(Tümü)")
    cari.pack(side="left", padx=4)

    ttk.Label(filtre2, text="Stok:").pack(side="left", padx=(8, 2))
    stoklar = StokService.stoklari_ara()
    stok_degerler = ["(Tümü)"] + [f"{s.stok_kodu} - {s.stok_adi}" for s in stoklar]
    stok_kod_map = {"(Tümü)": None}
    stok_kod_map.update({f"{s.stok_kodu} - {s.stok_adi}": s.stok_kodu for s in stoklar})
    stok = ttk.Combobox(filtre2, values=stok_degerler, width=22)
    stok.set("(Tümü)")
    stok.pack(side="left", padx=2)

    ttk.Label(filtre2, text="Lot:").pack(side="left", padx=(8, 2))
    lot = ttk.Combobox(filtre2, width=14)
    lot.pack(side="left", padx=2)
    ttk.Label(filtre2, text="Tedarikçi:").pack(side="left", padx=(8, 2))
    tedarikci = ttk.Combobox(filtre2, width=18)
    tedarikci.pack(side="left", padx=2)

    def _filtre_listelerini_yenile(_e=None):
        kod = stok_kod_map.get(stok.get())
        if kod is None and stok.get() and stok.get() != "(Tümü)":
            # Elle yazılmış kod / kısmi metin
            metin = stok.get().strip()
            kod = metin.split(" - ", 1)[0].strip() if " - " in metin else metin
        secenek = RaporService.stok_rapor_filtre_secenekleri(kod)
        onceki_lot = lot.get()
        onceki_ted = tedarikci.get()
        lot["values"] = ["(Tümü)"] + secenek["lotlar"]
        tedarikci["values"] = ["(Tümü)"] + secenek["tedarikciler"]
        if onceki_lot in lot["values"]:
            lot.set(onceki_lot)
        else:
            lot.set("(Tümü)")
        if onceki_ted in tedarikci["values"]:
            tedarikci.set(onceki_ted)
        else:
            tedarikci.set("(Tümü)")

    stok.bind("<<ComboboxSelected>>", _filtre_listelerini_yenile)
    stok.bind("<FocusOut>", _filtre_listelerini_yenile)
    _filtre_listelerini_yenile()

    ttk.Label(filtre2, text="Maliyet:").pack(side="left", padx=(8, 2))
    maliyet = ttk.Combobox(filtre2, values=MALIYET_YONTEMLERI_RAPOR, state="readonly", width=22)
    maliyet.set("FIFO")
    maliyet.pack(side="left")

    ozet = ttk.Label(app.icerik, text="Filtreleyip raporu getirin.")
    ozet.pack(anchor="w", pady=4)
    tablo = _tablo(
        app.icerik,
        ("fatura", "tarih", "cari", "urun", "adi", "lot", "miktar", "net", "maliyet", "kar", "marj"),
        ("Fatura", "Tarih", "Cari", "Kod", "Ad", "Lot", "Miktar", "Net Satış", "Maliyet", "Kâr", "Marj %"),
        (100, 85, 140, 80, 140, 90, 70, 95, 95, 90, 70),
    )

    def _secim_veya_bos(kutu):
        deger = (kutu.get() or "").strip()
        if not deger or deger == "(Tümü)":
            return None
        return deger

    def getir():
        try:
            b = _tarih_oku(baslangic)
            e = _tarih_oku(bitis)
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy girin.", parent=app)
            return
        stok_sec = stok_kod_map.get(stok.get())
        if stok_sec is None and stok.get() and stok.get() != "(Tümü)":
            metin = stok.get().strip()
            stok_sec = metin.split(" - ", 1)[0].strip() if " - " in metin else metin
        rapor = RaporService.stok_kar_zarar(
            baslangic=b,
            bitis=e,
            stok=stok_sec,
            cari_id=cari_map.get(cari.get()),
            lot=_secim_veya_bos(lot),
            tedarikci=_secim_veya_bos(tedarikci),
            maliyet_yontemi=maliyet.get(),
        )
        ozet.configure(
            text=(
                f"{rapor['maliyet_yontemi']}  |  Satır: {len(rapor['satirlar'])}  |  "
                f"Satış: {_para(rapor['toplam_satis'])}  |  "
                f"Maliyet: {_para(rapor['toplam_maliyet'])}  |  "
                f"Kâr: {_para(rapor['toplam_kar'])}  |  Marj: {rapor['toplam_marj']:.1f}%"
            )
        )
        for item in tablo.get_children():
            tablo.delete(item)
        for s in rapor["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    s["fatura_no"], _tarih(s["tarih"]),
                    f"{s['cari_kodu']} - {s['cari_unvan']}"[:28],
                    s["urun_kodu"], s["urun_adi"][:24], s["lot"][:18],
                    s["miktar"], _para(s["net_satis"]), _para(s["toplam_maliyet"]),
                    _para(s["kar"]), f"{s['marj']:.1f}",
                ),
            )

    ttk.Button(filtre2, text="Raporu Getir", command=getir).pack(side="left", padx=10)
    getir()


def rapor_satilmayan(app):
    _rapor_ust(app, "SATILMAYAN ÜRÜNLER RAPORU")
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(10, 4))
    ttk.Label(filtre, text="En az kaç gündür satılmadı:").pack(side="left")
    gun = ttk.Spinbox(filtre, from_=0, to=9999, width=8)
    gun.set("30")
    gun.pack(side="left", padx=6)
    ttk.Label(filtre, text="Stok:").pack(side="left", padx=(10, 2))
    stok = ttk.Entry(filtre, width=16)
    stok.pack(side="left")
    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)
    tablo = _tablo(
        app.icerik,
        ("kod", "ad", "birim", "mevcut", "son", "gun"),
        ("Stok Kodu", "Stok Adı", "Birim", "Mevcut", "Son Satış", "Gün"),
        (110, 280, 70, 90, 110, 80),
    )

    def getir():
        try:
            min_gun = int(gun.get())
        except ValueError:
            messagebox.showerror("Gün", "Geçerli gün sayısı girin.", parent=app)
            return
        rapor = RaporService.satilmayan_urunler(min_gun, stok.get().strip() or None)
        ozet.configure(
            text=f"Eşik: {rapor['min_gun']} gün  |  {len(rapor['satirlar'])} ürün  |  {_tarih(rapor['tarih'])}"
        )
        for item in tablo.get_children():
            tablo.delete(item)
        for s in rapor["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    s["stok_kodu"], s["stok_adi"], s["birim"], s["mevcut"],
                    "Hiç satılmadı" if s["hic_satilmadi"] else _tarih(s["son_satis"]),
                    "—" if s["hic_satilmadi"] else s["gun"],
                ),
            )

    ttk.Button(filtre, text="Raporu Getir", command=getir).pack(side="left", padx=10)
    getir()


def rapor_devir(app):
    _rapor_ust(app, "STOK DEVİR HIZI")
    ttk.Label(
        app.icerik,
        text=(
            "Devir Hızı = Dönem Satış Maliyeti (COGS) / Ortalama Stok Değeri. "
            "Ortalama Stok = (Dönem Başı + Dönem Sonu) / 2. "
            "Stokta Kalma (gün) = Dönem Gün Sayısı / Devir Hızı."
        ),
        wraplength=900,
        justify="left",
    ).pack(anchor="w", pady=(8, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=4)
    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    baslangic = ttk.Entry(b_c, width=11)
    baslangic.pack(side="left")
    baslangic.insert(0, _tarih(date(date.today().year, 1, 1)))
    takvim_butonu(b_c, baslangic)

    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(8, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bitis = ttk.Entry(e_c, width=11)
    bitis.pack(side="left")
    bitis.insert(0, _tarih(date.today()))
    takvim_butonu(e_c, bitis)

    ttk.Label(filtre, text="Stok:").pack(side="left", padx=(10, 2))
    stok = ttk.Entry(filtre, width=12)
    stok.pack(side="left")
    ttk.Label(filtre, text="Maliyet:").pack(side="left", padx=(8, 2))
    maliyet = ttk.Combobox(filtre, values=MALIYET_YONTEMLERI_RAPOR, state="readonly", width=24)
    maliyet.set("FIFO")
    maliyet.pack(side="left")

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)
    tablo = _tablo(
        app.icerik,
        ("kod", "ad", "bas", "son", "ort", "cogs", "devir", "gun"),
        ("Kod", "Ad", "Başı Miktar", "Sonu Miktar", "Ort. Değer", "COGS", "Devir Hızı", "Gün Stokta"),
        (90, 180, 90, 90, 100, 100, 90, 90),
    )

    def getir():
        try:
            b = _tarih_oku(baslangic, zorunlu=True)
            e = _tarih_oku(bitis, zorunlu=True)
            rapor = RaporService.stok_devir_hizi(b, e, stok.get().strip() or None, maliyet.get())
        except ValueError as hata:
            messagebox.showerror("Rapor", str(hata), parent=app)
            return
        ozet.configure(
            text=(
                f"{_tarih(rapor['baslangic'])} – {_tarih(rapor['bitis'])}  "
                f"({rapor['gun_sayisi']} gün)  |  {rapor['maliyet_yontemi']}  |  "
                f"{len(rapor['satirlar'])} stok"
            )
        )
        for item in tablo.get_children():
            tablo.delete(item)
        for s in rapor["satirlar"]:
            gun = f"{s['gun_stokta']:.1f}" if s["gun_stokta"] is not None else "—"
            tablo.insert(
                "",
                "end",
                values=(
                    s["stok_kodu"], s["stok_adi"][:28],
                    s["bas_miktar"], s["son_miktar"],
                    _para(s["ort_deger"]), _para(s["cogs"]),
                    f"{s['devir_hizi']:.2f}", gun,
                ),
            )

    ttk.Button(filtre, text="Raporu Getir", command=getir).pack(side="left", padx=10)
    getir()


def rapor_hareket(app):
    _rapor_ust(app, "STOK HAREKET RAPORU")
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(10, 4))

    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    baslangic = ttk.Entry(b_c, width=11)
    baslangic.pack(side="left")
    baslangic.insert(0, _tarih(date.today().replace(day=1)))
    takvim_butonu(b_c, baslangic)

    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(6, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bitis = ttk.Entry(e_c, width=11)
    bitis.pack(side="left")
    bitis.insert(0, _tarih(date.today()))
    takvim_butonu(e_c, bitis)

    filtre2 = ttk.Frame(app.icerik)
    filtre2.pack(fill="x", pady=4)
    ttk.Label(filtre2, text="Stok:").pack(side="left")
    stok = ttk.Entry(filtre2, width=12)
    stok.pack(side="left", padx=4)

    depolar = ["(Tümü)"] + [d.ad for d in StokService.depolar()]
    ttk.Label(filtre2, text="Depo:").pack(side="left", padx=(8, 2))
    depo = ttk.Combobox(filtre2, values=depolar, state="readonly", width=14)
    depo.set("(Tümü)")
    depo.pack(side="left")

    turler = ["(Tümü)"] + sorted(set(GIRIS_HAREKETLERI + CIKIS_HAREKETLERI))
    ttk.Label(filtre2, text="Hareket:").pack(side="left", padx=(8, 2))
    tur = ttk.Combobox(filtre2, values=turler, state="readonly", width=16)
    tur.set("(Tümü)")
    tur.pack(side="left")

    ttk.Label(filtre2, text="Belge:").pack(side="left", padx=(8, 2))
    belge = ttk.Entry(filtre2, width=12)
    belge.pack(side="left")
    ttk.Label(filtre2, text="Lot:").pack(side="left", padx=(8, 2))
    lot = ttk.Entry(filtre2, width=10)
    lot.pack(side="left")

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)
    tablo = _tablo(
        app.icerik,
        ("tarih", "tur", "belge", "kod", "ad", "depo", "lot", "yon", "miktar", "maliyet", "tutar"),
        ("Tarih", "Hareket", "Belge", "Kod", "Ad", "Depo", "Lot", "+/−", "Miktar", "Br. Maliyet", "Tutar"),
        (85, 110, 100, 80, 150, 90, 90, 40, 70, 95, 95),
    )

    def getir():
        try:
            b = _tarih_oku(baslangic)
            e = _tarih_oku(bitis)
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy girin.", parent=app)
            return
        rapor = RaporService.stok_hareket_raporu(
            baslangic=b,
            bitis=e,
            stok=stok.get().strip() or None,
            depo_adi=None if depo.get() == "(Tümü)" else depo.get(),
            hareket_turu=None if tur.get() == "(Tümü)" else tur.get(),
            belge_no=belge.get().strip() or None,
            lot=lot.get().strip() or None,
        )
        ozet.configure(text=f"{len(rapor['satirlar'])} hareket")
        for item in tablo.get_children():
            tablo.delete(item)
        for s in rapor["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    _tarih(s["tarih"]), s["hareket_turu"], s["belge_no"],
                    s["stok_kodu"], s["stok_adi"][:22], s["depo"], s["lot_no"],
                    s["yon"], s["miktar"], _para(s["birim_maliyet"]), _para(s["tutar"]),
                ),
            )

    ttk.Button(filtre2, text="Raporu Getir", command=getir).pack(side="left", padx=10)
    getir()
