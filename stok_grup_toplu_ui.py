"""Toplu Stok Grubu Eşleştirme — filtre, çoklu seçim, ön izleme, uygula, geri al."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from database.session_manager import oturum
from database.stok_grup_service import SEVIYE_ALT, SEVIYE_ANA, SEVIYE_TALI, StokGrupService
from database.stok_grup_toplu_service import (
    POLITIKA_DEGISTIR,
    POLITIKA_EKSIK_TAMAMLA,
    POLITIKA_SADECE_GRUPSUZ,
    StokGrupTopluService,
)
from satis_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    IKINCIL,
    LACIVERT,
    font,
    hub_ust_baslik,
    stil_uygula,
    tk_buton,
    treeview_stil,
)


def stok_grup_toplu_eslestirme_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    stil = ttk.Style(app)
    stil.configure("StokGrupToplu.Satis.Treeview.Heading", foreground=LACIVERT, background=ACIK_BG)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "stoklar" else "Menu.TButton"
        )

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    kok.columnconfigure(0, weight=1)
    kok.rowconfigure(2, weight=1)
    baslik_alani = tk.Frame(kok, bg=ACIK_BG)
    baslik_alani.grid(row=0, column=0, sticky="ew")
    baslik_bandi = hub_ust_baslik(
        baslik_alani,
        baslik="TOPLU STOK GRUBU EŞLEŞTİRME",
        alt_baslik="Bul → Seç → Hedef grup → Ön İzle → Gruba Aktar",
        app=app,
        geri_komut=lambda: app.sayfa_goster("stoklar"),
        geri_metin="← Stoklar",
    )

    # Sayaçlar
    sayac_fr = tk.Frame(kok, bg=ACIK_BG)
    sayac_fr.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 0))
    sayaclar = {}
    for baslik in (
        "Toplam Sonuç",
        "Seçili Ürün",
        "Grubu Değişecek",
        "Grupsuz",
        "Hatalı",
    ):
        kutu = tk.Frame(sayac_fr, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        kutu.pack(side="left", fill="x", expand=True, padx=3)
        tk.Label(kutu, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(8, root=app)).pack(
            anchor="w", padx=8, pady=(4, 0)
        )
        deger = tk.Label(kutu, text="0", bg=BEYAZ, fg=LACIVERT, font=font(14, "bold", app))
        deger.pack(anchor="w", padx=8, pady=(0, 6))
        sayaclar[baslik] = deger

    govde = tk.Frame(kok, bg=ACIK_BG)
    govde.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
    govde.columnconfigure(0, weight=3)
    govde.columnconfigure(1, weight=2, minsize=320)
    govde.rowconfigure(0, weight=1)

    # —— Sol: filtre + liste ——
    sol = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    sol.columnconfigure(0, weight=1)
    sol.rowconfigure(2, weight=1)

    filtre = tk.Frame(sol, bg=BEYAZ)
    filtre.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
    for sutun in range(4):
        filtre.columnconfigure(sutun, weight=1, uniform="filtre")
    tk.Label(filtre, text="Ara (kod/ad/barkod)", bg=BEYAZ, fg=IKINCIL).grid(row=0, column=0, sticky="w")
    arama = ttk.Entry(filtre, width=22)
    arama.grid(row=1, column=0, padx=(0, 6), sticky="ew")
    tk.Label(filtre, text="Ad kelime 1/2/3 (OR)", bg=BEYAZ, fg=IKINCIL).grid(
        row=0, column=1, columnspan=3, sticky="w"
    )
    ad1 = ttk.Entry(filtre, width=12)
    ad2 = ttk.Entry(filtre, width=12)
    ad3 = ttk.Entry(filtre, width=12)
    ad1.grid(row=1, column=1, padx=2, sticky="ew")
    ad2.grid(row=1, column=2, padx=2, sticky="ew")
    ad3.grid(row=1, column=3, padx=2, sticky="ew")

    tk.Label(filtre, text="Ana Grup", bg=BEYAZ, fg=IKINCIL).grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Label(filtre, text="Tali Grup", bg=BEYAZ, fg=IKINCIL).grid(row=2, column=1, sticky="w", pady=(6, 0))
    tk.Label(filtre, text="Alt Grup", bg=BEYAZ, fg=IKINCIL).grid(row=2, column=2, sticky="w", pady=(6, 0))
    f_ana = ttk.Combobox(filtre, width=18)
    f_tali = ttk.Combobox(filtre, width=18, state="disabled")
    f_alt = ttk.Combobox(filtre, width=18, state="disabled")
    f_ana.grid(row=3, column=0, sticky="ew", padx=(0, 4))
    f_tali.grid(row=3, column=1, sticky="ew", padx=2)
    f_alt.grid(row=3, column=2, sticky="ew", padx=2)

    tk.Label(filtre, text="Marka", bg=BEYAZ, fg=IKINCIL).grid(row=4, column=0, sticky="w", pady=(6, 0))
    marka = ttk.Entry(filtre, width=16)
    marka.grid(row=5, column=0, sticky="w")
    aktiflik = ttk.Combobox(
        filtre, values=("Aktif", "Pasif", "Tümü"), width=10, state="readonly"
    )
    aktiflik.set("Aktif")
    aktiflik.grid(row=5, column=1, sticky="w")
    grup_durum = ttk.Combobox(
        filtre, values=("Tümü", "Grupsuz", "Gruplu"), width=10, state="readonly"
    )
    grup_durum.set("Tümü")
    grup_durum.grid(row=5, column=2, sticky="w")
    stok_durum = ttk.Combobox(
        filtre,
        values=("Tümü", "Stokta var", "Sıfır", "Eksi"),
        width=12,
        state="readonly",
    )
    stok_durum.set("Tümü")
    stok_durum.grid(row=5, column=3, sticky="w")

    btn_f = tk.Frame(filtre, bg=BEYAZ)
    btn_f.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 0))
    tk_buton(btn_f, "Listele", lambda: _listele(), rol="ara").pack(side="left")
    tk_buton(btn_f, "Temizle", lambda: _filtre_temizle(), rol="ikincil").pack(
        side="left", padx=6
    )
    tk_buton(btn_f, "Grupsuzlar", lambda: _yalniz_grupsuz(), rol="yeni").pack(side="left")
    ayrinti_alanlari = [w for w in filtre.winfo_children() if 2 <= int(w.grid_info().get("row", -1)) <= 5]
    ayrinti_durumu = {"manuel": False, "acik": None}

    def _ayrinti_goster(acik):
        if ayrinti_durumu["acik"] == acik:
            return
        ayrinti_durumu["acik"] = acik
        for widget in ayrinti_alanlari:
            widget.grid() if acik else widget.grid_remove()
        ayrinti_btn.configure(text="Ayrıntılar ▴" if acik else "Ayrıntılar ▾")

    def _ayrinti_degistir():
        ayrinti_durumu["manuel"] = True
        _ayrinti_goster(not ayrinti_durumu["acik"])

    ayrinti_btn = tk_buton(btn_f, "Ayrıntılar ▾", _ayrinti_degistir, rol="ikincil")
    filtre_dugmeleri = [w for w in btn_f.winfo_children() if isinstance(w, tk.Button)]
    for widget in filtre_dugmeleri:
        widget.pack_forget()
    for i, widget in enumerate(filtre_dugmeleri):
        widget.grid(row=0, column=i, sticky="ew", padx=2)
        widget.configure(padx=6)
        btn_f.columnconfigure(i, weight=1, uniform="filtre_dugme")
    baslik_durumu = {"kucuk": None}

    def _ekran_boyut(event):
        kucuk = event.height < 700
        if not ayrinti_durumu["manuel"]:
            _ayrinti_goster(not kucuk)
        if baslik_durumu["kucuk"] == kucuk:
            return
        baslik_durumu["kucuk"] = kucuk
        sol_baslik, sag_baslik = baslik_bandi.winfo_children()
        sol_baslik.pack_configure(pady=2 if kucuk else 16)
        sag_baslik.pack_configure(pady=4 if kucuk else 12)
        sol_baslik.winfo_children()[0].configure(font=font(16 if kucuk else 28, "bold", app))
        sol_baslik.winfo_children()[1].configure(font=font(9 if kucuk else 12, root=app))
        sol_baslik.winfo_children()[2].pack_configure(pady=(2 if kucuk else 10, 0))
        for deger in sayaclar.values():
            deger.configure(font=font(11 if kucuk else 14, "bold", app))
            deger.pack_configure(pady=(0, 3 if kucuk else 6))
        sag_alanlar = sag_baslik.winfo_children()
        for label in sag_alanlar[1:-1]:
            if kucuk:
                label.pack_forget()
            else:
                label.pack(anchor="e", before=sag_alanlar[-1])

    kok.bind("<Configure>", _ekran_boyut)

    sec_fr = tk.Frame(sol, bg=BEYAZ)
    sec_fr.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
    tk_buton(sec_fr, "Sayfayı Seç", lambda: _sayfa_sec(), rol="ikincil").pack(side="left")
    tk_buton(sec_fr, "Tümünü Seç", lambda: _tumunu_sec(), rol="kaydet").pack(
        side="left", padx=6
    )
    tk_buton(sec_fr, "Seçimi Temizle", lambda: _secim_temizle(), rol="ikincil").pack(side="left")
    sadece_secili = tk.BooleanVar(master=app, value=False)
    secim_dugmeleri = [w for w in sec_fr.winfo_children() if isinstance(w, tk.Button)]
    for widget in secim_dugmeleri:
        widget.pack_forget()
    for i, widget in enumerate(secim_dugmeleri):
        widget.grid(row=0, column=i, sticky="ew", padx=2)
        widget.configure(padx=6)
        sec_fr.columnconfigure(i, weight=1, uniform="secim")

    tablo_fr = tk.Frame(sol, bg=BEYAZ)
    tablo_fr.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    kolonlar = (
        "sec",
        "kod",
        "ad",
        "barkod",
        "birim",
        "miktar",
        "ana",
        "tali",
        "alt",
        "durum",
        "uyari",
    )
    tablo = ttk.Treeview(
        tablo_fr, columns=kolonlar, show="headings", selectmode="extended", height=16
    )
    treeview_stil(tablo)
    tablo.configure(style="StokGrupToplu.Satis.Treeview")
    basliklar = {
        "sec": "✓",
        "kod": "Kod",
        "ad": "Ad",
        "barkod": "Barkod",
        "birim": "Birim",
        "miktar": "Mevcut",
        "ana": "Ana",
        "tali": "Tali",
        "alt": "Alt",
        "durum": "Durum",
        "uyari": "Uyarı",
    }
    gen = {
        "sec": 36,
        "kod": 90,
        "ad": 160,
        "barkod": 100,
        "birim": 50,
        "miktar": 70,
        "ana": 90,
        "tali": 90,
        "alt": 90,
        "durum": 60,
        "uyari": 120,
    }
    for k in kolonlar:
        tablo.heading(k, text=basliklar[k])
        tablo.column(k, width=gen[k], anchor="w" if k != "sec" else "center")
    sy = ttk.Scrollbar(tablo_fr, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=sy.set)
    sx = ttk.Scrollbar(tablo_fr, orient="horizontal", command=tablo.xview)
    tablo.configure(xscrollcommand=sx.set)
    tablo_fr.rowconfigure(0, weight=1)
    tablo_fr.columnconfigure(0, weight=1)
    tablo.grid(row=0, column=0, sticky="nsew")
    sy.grid(row=0, column=1, sticky="ns")
    sx.grid(row=1, column=0, sticky="ew")

    sayfa_fr = tk.Frame(sol, bg=BEYAZ)
    sayfa_fr.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
    sayfa_lbl = tk.Label(sayfa_fr, text="Sayfa 1", bg=BEYAZ, fg=IKINCIL)
    sayfa_lbl.pack(side="left")
    tk_buton(sayfa_fr, "◀", lambda: _sayfa(-1), rol="ikincil").pack(side="left", padx=4)
    tk_buton(sayfa_fr, "▶", lambda: _sayfa(1), rol="ikincil").pack(side="left")
    ttk.Checkbutton(
        sayfa_fr, text="Yalnız seçili ürünler", variable=sadece_secili, command=lambda: _listele()
    ).pack(side="right")

    # —— Sağ: hedef + özet + geçmiş ——
    sag_alani = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sag_alani.grid(row=0, column=1, sticky="nsew")
    sag_alani.rowconfigure(0, weight=1)
    sag_alani.columnconfigure(0, weight=1)
    sag_kaydir = tk.Canvas(sag_alani, bg=BEYAZ, highlightthickness=0, width=320)
    sag_cubuk = ttk.Scrollbar(sag_alani, orient="vertical", command=sag_kaydir.yview)
    sag_kaydir.configure(yscrollcommand=sag_cubuk.set)
    sag_kaydir.grid(row=0, column=0, sticky="nsew")
    sag_cubuk.grid(row=0, column=1, sticky="ns")
    sag = tk.Frame(sag_kaydir, bg=BEYAZ)
    sag_pencere = sag_kaydir.create_window((0, 0), window=sag, anchor="nw")
    sag.bind("<Configure>", lambda _e: sag_kaydir.configure(scrollregion=sag_kaydir.bbox("all")))
    sag_kaydir.bind("<Configure>", lambda e: sag_kaydir.itemconfigure(sag_pencere, width=e.width))

    tk.Label(
        sag, text="Hedef Grup", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", app)
    ).pack(anchor="w", padx=12, pady=(10, 4))
    h_ana = ttk.Combobox(sag, width=36, state="readonly")
    h_tali = ttk.Combobox(sag, width=36, state="disabled")
    h_alt = ttk.Combobox(sag, width=36, state="disabled")
    for lbl, w in (("Ana Grup *", h_ana), ("Tali Grup", h_tali), ("Alt Grup", h_alt)):
        tk.Label(sag, text=lbl, bg=BEYAZ, fg=IKINCIL).pack(anchor="w", padx=12)
        w.pack(fill="x", padx=12, pady=(0, 6))
    hedef_yol_lbl = tk.Label(
        sag,
        text="Hedef: —",
        bg=BEYAZ,
        fg=LACIVERT,
        font=font(11, "bold", app),
        wraplength=320,
        justify="left",
    )
    hedef_yol_lbl.pack(anchor="w", padx=12, pady=(4, 8))
    tk_buton(sag, "Yeni Grup Ekle", lambda: _yeni_grup(), rol="yeni").pack(anchor="w", padx=12)

    tk.Label(
        sag, text="İşlem Politikası", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", app)
    ).pack(anchor="w", padx=12, pady=(12, 2))
    politika = tk.StringVar(master=app, value=POLITIKA_SADECE_GRUPSUZ)
    for metin, kod in (
        ("Yalnız grupsuz stoklar (önerilen)", POLITIKA_SADECE_GRUPSUZ),
        ("Seçilenlerin grubunu değiştir", POLITIKA_DEGISTIR),
        ("Eksik seviyeleri tamamla", POLITIKA_EKSIK_TAMAMLA),
    ):
        ttk.Radiobutton(sag, text=metin, variable=politika, value=kod).pack(
            anchor="w", padx=12
        )

    ozet_lbl = tk.Label(
        sag,
        text="Özet: Ön izleme yapılmadı.",
        bg=BEYAZ,
        fg=IKINCIL,
        justify="left",
        wraplength=320,
        font=font(9, root=app),
    )
    ozet_lbl.pack(anchor="w", padx=12, pady=10)

    def _sag_boyut(event):
        sag_kaydir.itemconfigure(sag_pencere, width=event.width)
        for label in (hedef_yol_lbl, ozet_lbl):
            label.configure(wraplength=max(100, event.width - 28))

    sag_kaydir.bind("<Configure>", _sag_boyut)

    tk.Label(
        sag, text="Son Toplu İşlemler", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", app)
    ).pack(anchor="w", padx=12)
    gecmis = ttk.Treeview(
        sag, columns=("no", "tarih", "adet", "durum"), show="headings", height=6
    )
    gecmis.configure(style="StokGrupToplu.Satis.Treeview")
    for k, b, w in (
        ("no", "İşlem No", 120),
        ("tarih", "Tarih", 90),
        ("adet", "Adet", 50),
        ("durum", "Durum", 80),
    ):
        gecmis.heading(k, text=b)
        gecmis.column(k, width=w)
    gecmis.pack(fill="x", padx=12, pady=4)
    tk_buton(sag, "Seçili İşlemi Geri Al", lambda: _geri_al(), rol="tehlike").pack(
        anchor="w", padx=12, pady=(0, 8)
    )

    # Alt şerit
    alt = tk.Frame(kok, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    alt.grid(row=3, column=0, sticky="ew")
    alt_ic = tk.Frame(alt, bg=BEYAZ)
    alt_ic.pack(fill="x", padx=12, pady=6)
    kapat_btn = tk_buton(alt_ic, "Kapat", lambda: app.sayfa_goster("stoklar"), rol="ikincil")
    uygula_btn = tk_buton(
        alt_ic, "Gruba Aktar", lambda: _uygula(), rol="yeni", state="disabled"
    )
    onizle_btn = tk_buton(alt_ic, "Ön İzle", lambda: _onizle(), rol="ikincil")
    temizle_btn = tk_buton(alt_ic, "Seçimi Temizle", lambda: _secim_temizle(), rol="ikincil")
    islem_durumu = tk.Label(
        alt_ic, text="Aktarmak için ürün ve hedef grup seçip Ön İzle'ye basın.",
        bg=BEYAZ, fg=IKINCIL, anchor="w", justify="left", font=font(9, root=app),
    )
    islem_durumu.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(5, 0))

    def _alt_yerlesim(event):
        sutun_sayisi = 2 if event.width < 760 else 4
        for i in range(4):
            alt_ic.columnconfigure(i, weight=1 if i < sutun_sayisi else 0)
        for i, btn in enumerate((temizle_btn, onizle_btn, uygula_btn, kapat_btn)):
            btn.grid(row=i // sutun_sayisi, column=i % sutun_sayisi, sticky="ew", padx=3, pady=2)
        islem_durumu.configure(wraplength=max(100, event.width - 20))

    alt_ic.bind("<Configure>", _alt_yerlesim)

    # State
    state = {
        "sayfa": 0,
        "sayfa_boyu": 80,
        "toplam": 0,
        "secili": set(),  # stok id
        "satir_map": {},  # iid -> id
        "f_ana_map": {},
        "f_tali_map": {},
        "f_alt_map": {},
        "h_ana_map": {},
        "h_tali_map": {},
        "h_alt_map": {},
        "son_onizleme": None,
        "gecmis_map": {},
        "busy": False,
        "filtre_snapshot": {},
    }

    def _onizleme_gecersiz(*_args):
        state["son_onizleme"] = None
        uygula_btn.configure(state="disabled")
        sayaclar["Grubu Değişecek"].configure(text="—")
        ozet_lbl.configure(text="Özet: Seçim değişti. Ön izlemeyi yenileyin.")
        islem_durumu.configure(text=f"Seçili: {len(state['secili'])} · Aktarmak için ön izlemeyi yenileyin.")

    def _etiket(g):
        return g.get("etiket") or f"{g.get('kod')} — {g.get('ad')}"

    def _yukle_hedef_ana():
        state["h_ana_map"].clear()
        try:
            liste = StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True)
        except Exception as exc:
            messagebox.showerror("Grup", str(exc), parent=app)
            return
        vals = []
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["h_ana_map"][et] = g["id"]
        h_ana.configure(values=vals)
        h_tali.configure(values=[], state="disabled")
        h_alt.configure(values=[], state="disabled")
        h_tali.set("")
        h_alt.set("")
        _hedef_yol_guncelle()

    def _yukle_filtre_ana():
        state["f_ana_map"].clear()
        try:
            liste = StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True)
        except Exception:
            liste = []
        vals = ["(Tümü)"]
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["f_ana_map"][et] = g["id"]
        f_ana.configure(values=vals)
        f_ana.set("(Tümü)")
        f_tali.configure(values=[], state="disabled")
        f_alt.configure(values=[], state="disabled")

    def _hedef_ana_ch(_e=None):
        state["h_tali_map"].clear()
        state["h_alt_map"].clear()
        h_tali.set("")
        h_alt.set("")
        aid = state["h_ana_map"].get(h_ana.get())
        if not aid:
            h_tali.configure(values=[], state="disabled")
            h_alt.configure(values=[], state="disabled")
            _hedef_yol_guncelle()
            return
        liste = StokGrupService.listele(seviye=SEVIYE_TALI, parent_id=aid, aktif_only=True)
        vals = []
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["h_tali_map"][et] = g["id"]
        h_tali.configure(values=vals, state="readonly")
        h_alt.configure(values=[], state="disabled")
        _hedef_yol_guncelle()

    def _hedef_tali_ch(_e=None):
        state["h_alt_map"].clear()
        h_alt.set("")
        tid = state["h_tali_map"].get(h_tali.get())
        if not tid:
            h_alt.configure(values=[], state="disabled")
            _hedef_yol_guncelle()
            return
        liste = StokGrupService.listele(seviye=SEVIYE_ALT, parent_id=tid, aktif_only=True)
        vals = []
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["h_alt_map"][et] = g["id"]
        h_alt.configure(values=vals, state="readonly")
        _hedef_yol_guncelle()

    def _hedef_yol_guncelle(_e=None):
        parcalar = []
        for cb, mp in ((h_ana, "h_ana_map"), (h_tali, "h_tali_map"), (h_alt, "h_alt_map")):
            et = cb.get().strip()
            if et and et in state[mp]:
                # ad kısmını al
                ad = et.split("—")[-1].strip() if "—" in et else et
                parcalar.append(ad)
        hedef_yol_lbl.configure(
            text="Hedef: " + (" → ".join(parcalar) if parcalar else "—")
        )
        _onizleme_gecersiz()

    def _filtre_ana_ch(_e=None):
        state["f_tali_map"].clear()
        state["f_alt_map"].clear()
        f_tali.set("")
        f_alt.set("")
        aid = state["f_ana_map"].get(f_ana.get())
        if not aid:
            f_tali.configure(values=[], state="disabled")
            f_alt.configure(values=[], state="disabled")
            return
        liste = StokGrupService.listele(seviye=SEVIYE_TALI, parent_id=aid, aktif_only=True)
        vals = ["(Tümü)"]
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["f_tali_map"][et] = g["id"]
        f_tali.configure(values=vals, state="readonly")
        f_tali.set("(Tümü)")
        f_alt.configure(values=[], state="disabled")

    def _filtre_tali_ch(_e=None):
        state["f_alt_map"].clear()
        f_alt.set("")
        tid = state["f_tali_map"].get(f_tali.get())
        if not tid:
            f_alt.configure(values=[], state="disabled")
            return
        liste = StokGrupService.listele(seviye=SEVIYE_ALT, parent_id=tid, aktif_only=True)
        vals = ["(Tümü)"]
        for g in liste:
            et = _etiket(g)
            vals.append(et)
            state["f_alt_map"][et] = g["id"]
        f_alt.configure(values=vals, state="readonly")
        f_alt.set("(Tümü)")

    def _filtre_kwargs():
        aktif_map = {"Aktif": "aktif", "Pasif": "pasif", "Tümü": "tumu"}
        gd_map = {"Tümü": "tumu", "Grupsuz": "grupsuz", "Gruplu": "gruplu"}
        sd_map = {"Tümü": "tumu", "Stokta var": "var", "Sıfır": "sifir", "Eksi": "eksi"}
        return {
            "arama": arama.get().strip(),
            "ad_kelimeleri": [ad1.get(), ad2.get(), ad3.get()],
            "ana_grup_id": state["f_ana_map"].get(f_ana.get()),
            "tali_grup_id": state["f_tali_map"].get(f_tali.get()),
            "alt_grup_id": state["f_alt_map"].get(f_alt.get()),
            "marka": marka.get().strip(),
            "aktiflik": aktif_map.get(aktiflik.get(), "aktif"),
            "stok_durumu": sd_map.get(stok_durum.get(), "tumu"),
            "grup_durumu": gd_map.get(grup_durum.get(), "tumu"),
        }

    def _sayaclari_guncelle(toplam, satirlar):
        sayaclar["Toplam Sonuç"].configure(text=str(toplam))
        sayaclar["Seçili Ürün"].configure(text=str(len(state["secili"])))
        grupsuz = sum(1 for s in satirlar if s.get("grupsuz"))
        hatali = sum(1 for s in satirlar if s.get("uyari") and "grup" in (s.get("uyari") or "").lower())
        # Daha doğru hatalı: uyarı dolu ve pasif değilse
        hatali = sum(
            1
            for s in satirlar
            if s.get("uyari") and s.get("uyari") not in ("", "Pasif")
        )
        sayaclar["Grupsuz"].configure(text=str(grupsuz))
        sayaclar["Hatalı"].configure(text=str(hatali))
        degisecek = "—"
        if state["son_onizleme"]:
            degisecek = str(state["son_onizleme"]["ozet"].get("guncellenecek", 0))
        sayaclar["Grubu Değişecek"].configure(text=str(degisecek))

    def _listele():
        kwargs = _filtre_kwargs()
        state["filtre_snapshot"] = dict(kwargs)
        try:
            if sadece_secili.get() and not state["secili"]:
                sonuc = {"satirlar": [], "toplam": 0, "gosterilen": 0}
            elif sadece_secili.get():
                sonuc = StokGrupTopluService.aday_listele(
                    id_listesi=sorted(state["secili"]),
                    limit=state["sayfa_boyu"],
                    offset=state["sayfa"] * state["sayfa_boyu"],
                    aktiflik="tumu",
                )
            else:
                sonuc = StokGrupTopluService.aday_listele(
                    **kwargs,
                    limit=state["sayfa_boyu"],
                    offset=state["sayfa"] * state["sayfa_boyu"],
                )
        except Exception as exc:
            messagebox.showerror("Liste", str(exc), parent=app)
            return
        max_sayfa = max(0, (sonuc["toplam"] - 1) // state["sayfa_boyu"])
        if state["sayfa"] > max_sayfa:
            state["sayfa"] = max_sayfa
            _listele()
            return
        for i in tablo.get_children():
            tablo.delete(i)
        state["satir_map"].clear()
        for s in sonuc["satirlar"]:
            iid = str(s["id"])
            state["satir_map"][iid] = s["id"]
            isaret = "☑" if s["id"] in state["secili"] else "☐"
            tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    isaret,
                    s["stok_kodu"],
                    s["stok_adi"],
                    s["barkod"],
                    s["birim"],
                    s["miktar"],
                    s["ana_grup"],
                    s["tali_grup"],
                    s["alt_grup"],
                    "Aktif" if s["aktif"] else "Pasif",
                    s.get("uyari") or "",
                ),
            )
        state["toplam"] = sonuc["toplam"]
        max_sayfa = max(0, (state["toplam"] - 1) // state["sayfa_boyu"])
        if state["sayfa"] > max_sayfa:
            state["sayfa"] = max_sayfa
        sayfa_lbl.configure(
            text=f"Sayfa {state['sayfa'] + 1} / {max_sayfa + 1}  ·  {sonuc['gosterilen']} satır"
        )
        _sayaclari_guncelle(sonuc["toplam"], sonuc["satirlar"])
        gorunen_secili = len(state["secili"].intersection(state["satir_map"].values()))
        if not state["son_onizleme"]:
            islem_durumu.configure(
                text=f"Seçili: {len(state['secili'])} · Bu sayfa dışında seçili: "
                f"{len(state['secili']) - gorunen_secili} · Aktarmak için Ön İzle'ye basın."
            )

    def _toggle_secim(event=None):
        if event is not None and event.keysym != "space":
            if tablo.identify_region(event.x, event.y) != "cell" or tablo.identify_column(event.x) != "#1":
                return
            iid = tablo.identify_row(event.y)
            sec = (iid,) if iid else ()
        else:
            sec = tablo.selection()
        for iid in sec:
            sid = state["satir_map"].get(iid)
            if sid is None:
                continue
            # Pasif varsayılan seçilmesin — kullanıcı bilinçli seçerse izin ver
            vals = list(tablo.item(iid, "values"))
            if sid in state["secili"]:
                state["secili"].discard(sid)
                vals[0] = "☐"
            else:
                state["secili"].add(sid)
                vals[0] = "☑"
            tablo.item(iid, values=vals)
        _onizleme_gecersiz()
        sayaclar["Seçili Ürün"].configure(text=str(len(state["secili"])))
        return "break"

    def _sayfa_sec():
        for iid, sid in state["satir_map"].items():
            vals = list(tablo.item(iid, "values"))
            if vals[9] == "Pasif":
                continue  # varsayılan: pasif seçme
            state["secili"].add(sid)
            vals[0] = "☑"
            tablo.item(iid, values=vals)
        _onizleme_gecersiz()
        sayaclar["Seçili Ürün"].configure(text=str(len(state["secili"])))

    def _tumunu_sec():
        if not messagebox.askyesno(
            "Tüm filtre sonucu",
            "Yalnızca bu sayfa değil; filtreye uyan TÜM stoklar seçilecek.\n"
            "Bu işlem binlerce kayıt seçebilir. Devam?",
            parent=app,
        ):
            return
        try:
            idler = StokGrupTopluService.filtre_tum_idler(**_filtre_kwargs())
        except Exception as exc:
            messagebox.showerror("Seçim", str(exc), parent=app)
            return
        # Pasifleri hariç tutmak için sayfa verisinden kontrol zor; serviste aktiflik=aktif varsayılan
        state["secili"] = set(idler)
        messagebox.showinfo(
            "Seçim",
            f"Filtre sonucundan {len(idler)} stok seçildi.\n"
            "Seçimler sayfa değişince korunur.",
            parent=app,
        )
        _onizleme_gecersiz()
        _listele()

    def _secim_temizle():
        state["secili"].clear()
        _onizleme_gecersiz()
        _listele()

    def _filtre_temizle():
        arama.delete(0, "end")
        for e in (ad1, ad2, ad3, marka):
            e.delete(0, "end")
        aktiflik.set("Aktif")
        grup_durum.set("Tümü")
        stok_durum.set("Tümü")
        _yukle_filtre_ana()
        state["sayfa"] = 0
        _listele()

    def _yalniz_grupsuz():
        grup_durum.set("Grupsuz")
        state["sayfa"] = 0
        _listele()

    def _sayfa(delta):
        max_sayfa = max(0, (state["toplam"] - 1) // state["sayfa_boyu"])
        yeni = max(0, min(state["sayfa"] + delta, max_sayfa))
        if yeni != state["sayfa"]:
            state["sayfa"] = yeni
            _listele()

    def _hedef_idler():
        for cb, key in ((h_ana, "h_ana_map"), (h_tali, "h_tali_map"), (h_alt, "h_alt_map")):
            if cb.get().strip() and cb.get() not in state[key]:
                raise ValueError("Hedef grup geçerli değil. Listeden yeniden seçin.")
        return (
            state["h_ana_map"].get(h_ana.get()),
            state["h_tali_map"].get(h_tali.get()),
            state["h_alt_map"].get(h_alt.get()),
        )

    def _onizle():
        if state["busy"]:
            return
        if not state["secili"]:
            messagebox.showwarning("Ön izleme", "Önce stok seçin.", parent=app)
            return
        try:
            ana, tali, alt = _hedef_idler()
            if not ana:
                raise ValueError("En az Ana Grup seçin.")
            oniz = StokGrupTopluService.onizle(
                sorted(state["secili"]),
                ana_id=ana,
                tali_id=tali,
                alt_id=alt,
                politika=politika.get(),
            )
        except Exception as exc:
            _onizleme_gecersiz()
            messagebox.showerror("Ön izleme", str(exc), parent=app)
            return
        state["son_onizleme"] = oniz
        o = oniz["ozet"]
        ozet_lbl.configure(
            text=(
                f"Hedef: {oniz['hedef_yol']}\n"
                f"Seçilen: {o['secilen']}  ·  Güncellenecek: {o['guncellenecek']}\n"
                f"Değişmeyecek: {o['degismeyecek']}  ·  Atlanacak: {o['atlanacak']}\n"
                f"Hatalı: {o['hatali']}  ·  Yetki yok: {o['yetki_yok']}"
            )
        )
        sayaclar["Grubu Değişecek"].configure(text=str(o["guncellenecek"]))
        uygula_btn.configure(state="normal" if o["guncellenecek"] > 0 else "disabled")
        islem_durumu.configure(
            text=f"Seçili: {o['secilen']} · Değişecek: {o['guncellenecek']} · "
            f"Atlanacak: {o['atlanacak'] + o['degismeyecek']} · Hatalı: {o['hatali'] + o['yetki_yok']}"
        )
        # Ön izleme penceresi
        win = tk.Toplevel(app)
        win.title("Ön İzleme — Toplu Grup Eşleştirme")
        win.geometry("900x520")
        win.transient(app)
        fr = ttk.Frame(win, padding=8)
        fr.pack(fill="both", expand=True)
        altb = ttk.Frame(fr)
        altb.pack(side="bottom", fill="x")
        ttk.Label(fr, text=ozet_lbl.cget("text")).pack(anchor="w")
        tv_fr = ttk.Frame(fr)
        tv_fr.pack(fill="both", expand=True, pady=6)
        tv_fr.rowconfigure(0, weight=1)
        tv_fr.columnconfigure(0, weight=1)
        tv = ttk.Treeview(
            tv_fr,
            columns=("kod", "ad", "eski", "yeni", "durum", "acik"),
            show="headings",
            height=18,
        )
        tv.configure(style="StokGrupToplu.Satis.Treeview")
        for k, b, w in (
            ("kod", "Kod", 90),
            ("ad", "Ad", 160),
            ("eski", "Eski Yol", 180),
            ("yeni", "Yeni Yol", 180),
            ("durum", "Durum", 120),
            ("acik", "Açıklama", 140),
        ):
            tv.heading(k, text=b)
            tv.column(k, width=w)
        tv.grid(row=0, column=0, sticky="nsew")
        tv_sy = ttk.Scrollbar(tv_fr, orient="vertical", command=tv.yview)
        tv_sx = ttk.Scrollbar(tv_fr, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=tv_sy.set, xscrollcommand=tv_sx.set)
        tv_sy.grid(row=0, column=1, sticky="ns")
        tv_sx.grid(row=1, column=0, sticky="ew")
        for s in oniz["satirlar"]:
            tv.insert(
                "",
                "end",
                iid=str(s["stok_id"]),
                values=(
                    s.get("stok_kodu"),
                    s.get("stok_adi"),
                    s.get("eski_yol"),
                    s.get("yeni_yol"),
                    s.get("durum"),
                    s.get("aciklama"),
                ),
            )

        def cikar():
            for iid in tv.selection():
                sid = int(iid)
                state["secili"].discard(sid)
                tv.delete(iid)
            _onizleme_gecersiz()
            _listele()
            messagebox.showinfo(
                "Seçim",
                "Seçimden çıkarıldı. Kaydetmeden önce Ön İzle'yi yeniden çalıştırın.",
                parent=win,
            )

        ttk.Button(altb, text="Seçimden Çıkar", command=cikar).pack(side="left")
        ttk.Button(altb, text="Kapat", command=win.destroy).pack(side="right")

    def _uygula():
        if state["busy"]:
            return
        oniz = state["son_onizleme"]
        if not oniz or oniz["ozet"]["guncellenecek"] <= 0:
            messagebox.showwarning("Ön izleme zorunlu", "Gruba Aktar için önce güncel bir Ön İzle yapın.", parent=app)
            return
        state["busy"] = True
        uygula_btn.configure(state="disabled")
        onizle_btn.configure(state="disabled")
        try:
            politika_adi = {
                POLITIKA_SADECE_GRUPSUZ: "Yalnız grupsuz stoklar",
                POLITIKA_DEGISTIR: "Seçilenlerin grubunu değiştir",
                POLITIKA_EKSIK_TAMAMLA: "Eksik seviyeleri tamamla",
            }[oniz["politika"]]
            if not messagebox.askyesno(
                "Gruba Aktar",
                f"Firma: {oturum.firma_unvan or oturum.firma_kodu or '—'}\n"
                f"Hedef: {oniz['hedef_yol']}\nPolitika: {politika_adi}\n"
                f"Değişecek: {oniz['ozet']['guncellenecek']} ürün\n\nAktarım yapılsın mı?",
                parent=app,
            ):
                return
            if state["son_onizleme"] is not oniz:
                raise ValueError("Seçim değişti. Ön izlemeyi yenileyin.")
            ana, tali, alt = _hedef_idler()
            sonuc = StokGrupTopluService.uygula(
                sorted(state["secili"]), ana_id=ana, tali_id=tali, alt_id=alt,
                politika=politika.get(), onizleme_ozeti=oniz["ozet"], onizleme_kaydi=oniz,
            )
            state["secili"].clear()
            _onizleme_gecersiz()
            _listele()
            _gecmis_yenile()
            messagebox.showinfo(
                "Tamamlandı",
                f"İşlem: {sonuc['islem_no']}\nGüncellenen: {sonuc['guncellenen']}\n"
                f"Hedef: {sonuc['hedef_yol']}", parent=app,
            )
        except Exception as exc:
            _onizleme_gecersiz()
            messagebox.showerror("Gruba Aktar", str(exc), parent=app)
        finally:
            state["busy"] = False
            onizle_btn.configure(state="normal")
            if state["son_onizleme"] is not None:
                uygula_btn.configure(state="normal")

    def _gecmis_yenile():
        for i in gecmis.get_children():
            gecmis.delete(i)
        state["gecmis_map"].clear()
        try:
            for g in StokGrupTopluService.islem_gecmisi(20):
                iid = str(g["id"])
                state["gecmis_map"][iid] = g
                gecmis.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(g["islem_no"], g["tarih"], g["guncellenen"], g["durum"]),
                )
        except Exception:
            pass

    def _geri_al():
        if state["busy"]:
            return
        sec = gecmis.selection()
        if not sec:
            messagebox.showinfo("Geri Al", "İşlem seçin.", parent=app)
            return
        g = state["gecmis_map"].get(sec[0])
        if not g:
            return
        if not messagebox.askyesno(
            "Geri Al",
            f"{g['islem_no']} işlemi geri alınsın mı?\n"
            f"Hedef: {g.get('hedef_yol')}\nGüncellenen: {g.get('guncellenen')}",
            parent=app,
        ):
            return
        try:
            sonuc = StokGrupTopluService.geri_al(g["id"])
            msg = f"Geri alınan: {sonuc['geri_alinan']}"
            if sonuc.get("cakisan"):
                msg += f"\nÇakışan: {len(sonuc['cakisan'])}"
                for c in sonuc["cakisan"][:5]:
                    msg += f"\n- {c.get('stok_kodu')}: {c.get('neden')}"
            messagebox.showinfo("Geri Al", msg, parent=app)
            _onizleme_gecersiz()
            _listele()
            _gecmis_yenile()
        except Exception as exc:
            messagebox.showerror("Geri Al", str(exc), parent=app)

    def _yeni_grup():
        from stok_grup_ui import StokGrupDialog

        ana_id = state["h_ana_map"].get(h_ana.get())
        tali_id = state["h_tali_map"].get(h_tali.get())
        if tali_id:
            sev, pid = SEVIYE_ALT, tali_id
        elif ana_id:
            sev, pid = SEVIYE_TALI, ana_id
        else:
            sev, pid = SEVIYE_ANA, None
        dlg = StokGrupDialog(app, seviye=sev, parent_id=pid)
        app.wait_window(dlg)
        if dlg.result:
            _yukle_hedef_ana()
            _yukle_filtre_ana()
            g = dlg.result
            et = _etiket(g)
            if g["seviye"] == SEVIYE_ANA:
                h_ana.set(et)
                _hedef_ana_ch()
            elif g["seviye"] == SEVIYE_TALI:
                if g.get("parent_id"):
                    for e2, gid in state["h_ana_map"].items():
                        if gid == g["parent_id"]:
                            h_ana.set(e2)
                            break
                    _hedef_ana_ch()
                h_tali.set(et)
                _hedef_tali_ch()
            else:
                # alt
                try:
                    tali = StokGrupService.getir(g["parent_id"])
                    if tali and tali.get("parent_id"):
                        for e2, gid in state["h_ana_map"].items():
                            if gid == tali["parent_id"]:
                                h_ana.set(e2)
                                break
                        _hedef_ana_ch()
                    if tali:
                        for e2, gid in state["h_tali_map"].items():
                            if gid == tali["id"]:
                                h_tali.set(e2)
                                break
                        _hedef_tali_ch()
                except Exception:
                    pass
                h_alt.set(et)
                _hedef_yol_guncelle()

    h_ana.bind("<<ComboboxSelected>>", _hedef_ana_ch)
    h_tali.bind("<<ComboboxSelected>>", _hedef_tali_ch)
    h_alt.bind("<<ComboboxSelected>>", _hedef_yol_guncelle)
    f_ana.bind("<<ComboboxSelected>>", _filtre_ana_ch)
    f_tali.bind("<<ComboboxSelected>>", _filtre_tali_ch)
    tablo.bind("<ButtonRelease-1>", _toggle_secim)
    tablo.bind("<space>", _toggle_secim)
    arama.bind("<Return>", lambda _e: _listele())
    politika.trace_add("write", _onizleme_gecersiz)

    def _sag_teker(event):
        if sag_kaydir.yview() == (0.0, 1.0):
            return None
        if getattr(event, "num", None) in (4, 5):
            adim = -1 if event.num == 4 else 1
        else:
            adim = -1 if event.delta > 0 else 1
        sag_kaydir.yview_scroll(adim * 3, "units")
        return "break"

    def _teker_bagla(widget):
        if isinstance(widget, (ttk.Treeview, ttk.Combobox, ttk.Scrollbar)):
            return
        for olay in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(olay, _sag_teker, add="+")
        for child in widget.winfo_children():
            _teker_bagla(child)

    _teker_bagla(sag_kaydir)

    _yukle_hedef_ana()
    _yukle_filtre_ana()
    _listele()
    _gecmis_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stok_grup_toplu_eslestirme_goster(app))
