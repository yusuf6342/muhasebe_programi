"""Kart Türleri ve Grupları — Tanımlar yönetim ekranı."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.kart_turu_service import KAPSAM_CARI, KAPSAM_STOK, KartTuruService
from database.models.kart_turu import KartAltTuru, KartAnaTuru


def kart_turleri_gruplari_goster(app, geri_fn=None) -> None:
    app._icerigi_temizle()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kart_turleri_gruplari_goster(app, geri_fn=geri_fn))

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=16, pady=(12, 0))
    ttk.Label(ust, text="KART TÜRLERİ VE GRUPLARI", style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Geri", command=geri_fn).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Ana tür, bağlı alt tür ve bağımsız grup/sektör tanımları. "
        "Alt türü grup alanına yazmayın; grup tür ağacından bağımsızdır.",
    ).pack(anchor="w", padx=16, pady=(6, 0))

    grid = ttk.Frame(app.icerik)
    grid.pack(fill="both", expand=True, padx=16, pady=16)
    for i in range(2):
        grid.columnconfigure(i, weight=1, uniform="kt")
        grid.rowconfigure(i, weight=1, uniform="kt")

    kartlar = (
        ("Stok Kart Türleri", "Ana stok türleri ve bağlı alt stok türleri", lambda: _tur_yonetim(app, KAPSAM_STOK, geri_fn)),
        ("Cari Kart Türleri", "Ana cari türleri ve bağlı alt cari türleri", lambda: _tur_yonetim(app, KAPSAM_CARI, geri_fn)),
        ("Stok Grupları", "İşlevsel ürün grupları (Ana → Tali → Alt)", lambda: _stok_grup_ac(app, geri_fn)),
        ("Cari Sektör Grupları", "Faaliyet alanı sektörleri", lambda: _sektor_yonetim(app, geri_fn)),
    )
    for i, (baslik, aciklama, cmd) in enumerate(kartlar):
        fr = ttk.LabelFrame(grid, text=baslik, padding=12)
        fr.grid(row=i // 2, column=i % 2, sticky="nsew", padx=8, pady=8)
        ttk.Label(fr, text=aciklama, wraplength=320).pack(anchor="w")
        ttk.Button(fr, text="Aç", command=cmd).pack(anchor="e", pady=(12, 0))


def _stok_grup_ac(app, geri_fn):
    from stok_grup_ui import stok_grup_yonetimi_goster

    stok_grup_yonetimi_goster(app)


def _tur_yonetim(app, kapsam: str, geri_fn) -> None:
    app._icerigi_temizle()
    baslik = "STOK KART TÜRLERİ" if kapsam == KAPSAM_STOK else "CARİ KART TÜRLERİ"
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=12, pady=(10, 0))
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Kart Türleri", command=lambda: kart_turleri_gruplari_goster(app, geri_fn)
    ).pack(side="right")

    govde = ttk.Panedwindow(app.icerik, orient="horizontal")
    govde.pack(fill="both", expand=True, padx=12, pady=10)

    sol = ttk.LabelFrame(govde, text="Ana Kart Türleri", padding=6)
    sag = ttk.LabelFrame(govde, text="Alt Kart Türleri (seçili ana türe bağlı)", padding=6)
    govde.add(sol, weight=1)
    govde.add(sag, weight=1)

    filtre_f = ttk.Frame(sol)
    filtre_f.pack(fill="x")
    ara_var = tk.StringVar()
    aktif_var = tk.StringVar(value="aktif")
    ttk.Entry(filtre_f, textvariable=ara_var, width=18).pack(side="left")
    ttk.Combobox(
        filtre_f, textvariable=aktif_var, values=("aktif", "pasif", "tümü"), width=8, state="readonly"
    ).pack(side="left", padx=4)

    cols = ("kod", "ad", "sira", "bagli", "aktif")
    ana_tv = ttk.Treeview(sol, columns=cols, show="headings", height=16)
    for c, t, w in (
        ("kod", "Kod", 90),
        ("ad", "Ad", 140),
        ("sira", "Sıra", 40),
        ("bagli", "Kart", 50),
        ("aktif", "Aktif", 50),
    ):
        ana_tv.heading(c, text=t)
        ana_tv.column(c, width=w)
    ana_tv.pack(fill="both", expand=True, pady=4)

    alt_tv = ttk.Treeview(sag, columns=cols, show="headings", height=16)
    for c, t, w in (
        ("kod", "Kod", 90),
        ("ad", "Ad", 140),
        ("sira", "Sıra", 40),
        ("bagli", "Kart", 50),
        ("aktif", "Aktif", 50),
    ):
        alt_tv.heading(c, text=t)
        alt_tv.column(c, width=w)
    alt_tv.pack(fill="both", expand=True, pady=4)
    alt_ipucu = ttk.Label(sag, text="Önce bir ana tür seçin.", foreground="#a40")
    alt_ipucu.pack(anchor="w")

    secili_ana: dict[str, Any] = {"id": None}

    def ana_doldur(*_a):
        ana_tv.delete(*ana_tv.get_children())
        sadece = aktif_var.get() != "pasif"
        hepsi = aktif_var.get() == "tümü"
        liste = KartTuruService.ana_turleri_listele(kapsam, sadece_aktif=False if hepsi else sadece)
        if aktif_var.get() == "pasif":
            liste = [x for x in liste if not x.aktif]
        q = (ara_var.get() or "").strip().casefold()
        for a in liste:
            if q and q not in (a.ad or "").casefold() and q not in (a.kod or "").casefold():
                continue
            bagli = KartTuruService.bagli_kart_sayisi(ana_id=a.id)
            ana_tv.insert(
                "",
                "end",
                iid=str(a.id),
                values=(a.kod, a.ad, a.sira, bagli, "Evet" if a.aktif else "Hayır"),
            )

    def alt_doldur(*_a):
        alt_tv.delete(*alt_tv.get_children())
        aid = secili_ana["id"]
        if not aid:
            alt_ipucu.configure(text="Önce bir ana tür seçin — Alt Tür Ekle pasif.")
            return
        ana = KartTuruService.ana_getir(aid)
        alt_ipucu.configure(text=f"Bağlı ana tür: {ana.ad if ana else aid}")
        for a in KartTuruService.alt_turleri_listele(aid, sadece_aktif=False):
            bagli = KartTuruService.bagli_kart_sayisi(alt_id=a.id)
            alt_tv.insert(
                "",
                "end",
                iid=str(a.id),
                values=(a.kod, a.ad, a.sira, bagli, "Evet" if a.aktif else "Hayır"),
            )

    def ana_sec(_e=None):
        sel = ana_tv.selection()
        secili_ana["id"] = int(sel[0]) if sel else None
        alt_doldur()
        alt_ekle_btn.state(["!disabled"] if secili_ana["id"] else ["disabled"])

    ana_tv.bind("<<TreeviewSelect>>", ana_sec)
    ara_var.trace_add("write", lambda *_: ana_doldur())
    aktif_var.trace_add("write", lambda *_: ana_doldur())

    def ana_form(mevcut: KartAnaTuru | None = None):
        _tanim_form(
            app,
            baslik="Ana Kart Türü",
            alanlar=_ana_alanlar(kapsam, mevcut),
            kaydet_fn=lambda v: (
                KartTuruService.ana_kaydet({**v, "kapsam": kapsam, "id": mevcut.id if mevcut else None}),
                ana_doldur(),
            ),
        )

    def alt_form(mevcut: KartAltTuru | None = None):
        if not secili_ana["id"] and not mevcut:
            messagebox.showinfo(
                "Alt tür",
                "Ana tür seçilmeden Alt Tür Ekle çalışmaz. Önce soldan bir ana tür seçin.",
                parent=app,
            )
            return
        ana_id = mevcut.ana_tur_id if mevcut else secili_ana["id"]
        ana = KartTuruService.ana_getir(int(ana_id))
        _tanim_form(
            app,
            baslik=f"Alt Kart Türü — {ana.ad if ana else ''}",
            alanlar=_ortak_alanlar(mevcut),
            kaydet_fn=lambda v: (
                KartTuruService.alt_kaydet(
                    {**v, "ana_tur_id": ana_id, "id": mevcut.id if mevcut else None}
                ),
                alt_doldur(),
            ),
        )

    def ana_duzenle():
        sel = ana_tv.selection()
        if not sel:
            return
        ana_form(KartTuruService.ana_getir(int(sel[0])))

    def alt_duzenle():
        sel = alt_tv.selection()
        if not sel:
            return
        alt_form(KartTuruService.alt_getir(int(sel[0])))

    def ana_pasif():
        sel = ana_tv.selection()
        if not sel:
            return
        if messagebox.askyesno("Pasife al", "Seçili ana tür pasife alınsın mı?", parent=app):
            KartTuruService.pasife_al_ana(int(sel[0]))
            ana_doldur()

    def alt_pasif():
        sel = alt_tv.selection()
        if not sel:
            return
        if messagebox.askyesno("Pasife al", "Seçili alt tür pasife alınsın mı?", parent=app):
            KartTuruService.pasife_al_alt(int(sel[0]))
            alt_doldur()

    btn_sol = ttk.Frame(sol)
    btn_sol.pack(fill="x")
    ttk.Button(btn_sol, text="Ana Tür Ekle", command=lambda: ana_form()).pack(side="left")
    ttk.Button(btn_sol, text="Düzenle", command=ana_duzenle).pack(side="left", padx=4)
    ttk.Button(btn_sol, text="Pasife Al", command=ana_pasif).pack(side="left")

    btn_sag = ttk.Frame(sag)
    btn_sag.pack(fill="x")
    alt_ekle_btn = ttk.Button(btn_sag, text="Alt Tür Ekle", command=lambda: alt_form())
    alt_ekle_btn.pack(side="left")
    alt_ekle_btn.state(["disabled"])
    ttk.Button(btn_sag, text="Düzenle", command=alt_duzenle).pack(side="left", padx=4)
    ttk.Button(btn_sag, text="Pasife Al", command=alt_pasif).pack(side="left")

    ana_doldur()


def _ana_alanlar(kapsam: str, mevcut) -> list[tuple[str, str, str]]:
    alanlar = _ortak_alanlar(mevcut)
    if kapsam == KAPSAM_CARI:
        rol = getattr(mevcut, "muhasebe_rol", "") or ""
        alanlar.append(("muhasebe_rol", "Muhasebe rolü", rol))
    return alanlar


def _ortak_alanlar(mevcut) -> list[tuple[str, str, str]]:
    return [
        ("kod", "Kod", getattr(mevcut, "kod", "") or ""),
        ("ad", "Ad", getattr(mevcut, "ad", "") or ""),
        ("aciklama", "Açıklama", getattr(mevcut, "aciklama", "") or ""),
        ("sira", "Sıra", str(getattr(mevcut, "sira", 100) or 100)),
        ("aktif", "Aktif (1/0)", "1" if getattr(mevcut, "aktif", True) else "0"),
    ]


def _tanim_form(app, *, baslik: str, alanlar, kaydet_fn: Callable) -> None:
    win = tk.Toplevel(app)
    win.title(baslik)
    win.geometry("420x360")
    win.transient(app)
    win.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(win)
    vars_: dict[str, tk.StringVar] = {}
    for key, label, val in alanlar:
        fr = ttk.Frame(win)
        fr.pack(fill="x", padx=12, pady=4)
        ttk.Label(fr, text=label, width=18).pack(side="left")
        var = tk.StringVar(value=val)
        vars_[key] = var
        if key == "muhasebe_rol":
            ttk.Combobox(
                fr,
                textvariable=var,
                values=("MUSTERI", "TEDARIKCI", "PERSONEL", "MUSTERI_TEDARIKCI"),
                state="readonly",
            ).pack(side="left", fill="x", expand=True)
        else:
            ttk.Entry(fr, textvariable=var).pack(side="left", fill="x", expand=True)

    def kaydet():
        try:
            veri = {k: v.get() for k, v in vars_.items()}
            veri["aktif"] = (veri.get("aktif") or "1").strip() not in {"0", "hayır", "Hayır", "false", "False"}
            try:
                veri["sira"] = int(veri.get("sira") or 100)
            except ValueError:
                veri["sira"] = 100
            kaydet_fn(veri)
            win.destroy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kayıt", str(exc), parent=win)

    alt = ttk.Frame(win)
    alt.pack(fill="x", padx=12, pady=12)
    ttk.Button(alt, text="Kaydet", command=kaydet).pack(side="left")
    ttk.Button(alt, text="Vazgeç", command=win.destroy).pack(side="left", padx=8)


def _sektor_yonetim(app, geri_fn) -> None:
    app._icerigi_temizle()
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=12, pady=(10, 0))
    ttk.Label(ust, text="CARİ SEKTÖR GRUPLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Kart Türleri", command=lambda: kart_turleri_gruplari_goster(app, geri_fn)
    ).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Sektör grubu tür ağacından bağımsızdır. Perakende Müşteri / Hizmet Tedarikçisi burada yoktur.",
    ).pack(anchor="w", padx=12, pady=(4, 0))

    cols = ("kod", "ad", "sira", "aktif")
    tv = ttk.Treeview(app.icerik, columns=cols, show="headings", height=18)
    for c, t, w in (("kod", "Kod", 100), ("ad", "Ad", 220), ("sira", "Sıra", 50), ("aktif", "Aktif", 60)):
        tv.heading(c, text=t)
        tv.column(c, width=w)
    tv.pack(fill="both", expand=True, padx=12, pady=8)

    def doldur():
        tv.delete(*tv.get_children())
        for g in KartTuruService.sektor_listele(sadece_aktif=False, sektor_listesinde=True):
            tv.insert(
                "",
                "end",
                iid=str(g["id"]),
                values=(g.get("kod") or "", g["ad"], g.get("sira"), "Evet" if g.get("aktif") else "Hayır"),
            )

    def form(mevcut=None):
        alanlar = [
            ("kod", "Kod", (mevcut or {}).get("kod") or ""),
            ("ad", "Ad", (mevcut or {}).get("ad") or ""),
            ("aciklama", "Açıklama", (mevcut or {}).get("aciklama") or ""),
            ("sira", "Sıra", str((mevcut or {}).get("sira") or 100)),
            ("aktif", "Aktif (1/0)", "1" if (mevcut or {}).get("aktif", True) else "0"),
        ]

        def kaydet(v):
            KartTuruService.sektor_kaydet({**v, "id": (mevcut or {}).get("id")})
            doldur()

        _tanim_form(app, baslik="Sektör Grubu", alanlar=alanlar, kaydet_fn=kaydet)

    def duzenle():
        sel = tv.selection()
        if not sel:
            return
        for g in KartTuruService.sektor_listele(sadece_aktif=False, sektor_listesinde=True):
            if str(g["id"]) == sel[0]:
                form(g)
                return

    def pasif():
        sel = tv.selection()
        if not sel:
            return
        KartTuruService.sektor_kaydet({"id": int(sel[0]), "ad": tv.item(sel[0], "values")[1], "aktif": False})
        doldur()

    btn = ttk.Frame(app.icerik)
    btn.pack(fill="x", padx=12, pady=4)
    ttk.Button(btn, text="Yeni Sektör Grubu", command=lambda: form()).pack(side="left")
    ttk.Button(btn, text="Düzenle", command=duzenle).pack(side="left", padx=4)
    ttk.Button(btn, text="Pasife Al", command=pasif).pack(side="left")
    doldur()


def hizli_tanim_penceresi(parent, *, kapsam: str, tur: str = "alt", ana_tur_id: int | None = None, on_saved=None):
    """Kart içinden hızlı tanım: Vazgeç kaydetmez; kayıtta yalnız liste yenilenir."""
    if tur == "alt" and not ana_tur_id:
        messagebox.showinfo("Alt tür", "Önce ana kart türü seçin.", parent=parent)
        return
    if tur == "sektor":
        alanlar = [
            ("kod", "Kod", ""),
            ("ad", "Ad", ""),
            ("aciklama", "Açıklama", ""),
            ("sira", "Sıra", "100"),
            ("aktif", "Aktif (1/0)", "1"),
        ]

        def kaydet(v):
            sonuc = KartTuruService.sektor_kaydet(v)
            if on_saved:
                on_saved(sonuc)

        _tanim_form(parent, baslik="Yeni Sektör Grubu", alanlar=alanlar, kaydet_fn=kaydet)
        return

    if tur == "ana":
        alanlar = _ana_alanlar(kapsam, None)

        def kaydet(v):
            sonuc = KartTuruService.ana_kaydet({**v, "kapsam": kapsam})
            if on_saved:
                on_saved(sonuc)

        _tanim_form(parent, baslik="Yeni Ana Kart Türü", alanlar=alanlar, kaydet_fn=kaydet)
        return

    ana = KartTuruService.ana_getir(int(ana_tur_id))
    alanlar = _ortak_alanlar(None)

    def kaydet(v):
        sonuc = KartTuruService.alt_kaydet({**v, "ana_tur_id": ana_tur_id})
        if on_saved:
            on_saved(sonuc)

    _tanim_form(
        parent,
        baslik=f"Yeni Alt Tür — {ana.ad if ana else ''}",
        alanlar=alanlar,
        kaydet_fn=kaydet,
    )
