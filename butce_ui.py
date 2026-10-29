"""BÜTÇE menüsü — Yeni Bütçe, Liste, Gerçekleşen (Bütçe vs Ön Muhasebe), Ayarlar stub.

Bütçe planını açmak / kaydetmek fatura, fiş veya stok hareketi oluşturmaz.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.butce_service import ButceService, dagit_yillik_esit
from database.models.butce import OLCU_GIDER, OLCU_SATIS, OLCU_TURLERI

try:
    from ana_panel_tema import LACIVERT, SARI, BEYAZ, KOYU_LACIVERT, ACIK_BG, PASIF, FONT_UI_BOLD, FONT_ALT
except Exception:  # noqa: BLE001
    LACIVERT = "#102A43"
    SARI = "#F4C542"
    BEYAZ = "#FFFFFF"
    KOYU_LACIVERT = "#081B2C"
    ACIK_BG = "#F3F6F9"
    PASIF = "#627D98"
    FONT_UI_BOLD = ("Segoe UI", 11, "bold")
    FONT_ALT = ("Segoe UI", 9)


def _para(tutar) -> str:
    if tutar is None:
        return "—"
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _menu_isaretle(app, anahtar="butce"):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle(anahtar)
        return
    for dugme_anahtari, dugme in getattr(app, "menu_dugmeleri", {}).items():
        try:
            if dugme_anahtari == anahtar:
                dugme.configure(style="SeciliMenu.TButton")
            elif dugme_anahtari == "hizli_satis":
                dugme.configure(style="HizliSatisMenu.TButton")
            else:
                dugme.configure(style="Menu.TButton")
        except tk.TclError:
            pass


def _alt_isaretle(app, alt_anahtar: str):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None and hasattr(kabuk, "_alt_oge_isaretle"):
        kabuk._alt_oge_isaretle(alt_anahtar)


def _mali_yil_varsayilan() -> int:
    try:
        from database.donem_service import DonemService

        bilgi = DonemService.aktif_veya_varsayilan()
        if bilgi and bilgi.get("baslangic"):
            return int(str(bilgi["baslangic"])[:4])
    except Exception:  # noqa: BLE001
        pass
    return date.today().year


# --------------------------------------------------------------------------- menü hub


def butce_menusu_goster(app):
    """Ana BÜTÇE ekranı — planlama; belge üretmez."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="BÜTÇE", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "Firma satış / gider planı ve Ön Muhasebe gerçekleşme karşılaştırması. "
            "Bütçe açmak fatura veya fiş oluşturmaz."
        ),
    ).pack(anchor="w", pady=(8, 0))

    sari_cubuk = tk.Frame(app.icerik, bg=SARI, height=4)
    sari_cubuk.pack(fill="x", pady=(12, 8))

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    alt.columnconfigure(0, weight=1, minsize=480)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (baslik, komut) in enumerate(
        (
            ("YENİ BÜTÇE", lambda: butce_yeni_goster(app)),
            ("BÜTÇE LİSTESİ", lambda: butce_liste_goster(app)),
            ("BÜTÇE GERÇEKLEŞEN", lambda: butce_gerceklesen_goster(app)),
            ("NAKİT BÜTÇESİ (yakında)", lambda: butce_nakit_stub(app)),
            ("RAPORLAR (yakında)", lambda: butce_raporlar_stub(app)),
            ("AYARLAR", lambda: butce_ayarlar_goster(app)),
        )
    ):
        ttk.Button(
            alt, text=baslik, style="AltMenu.TButton", command=lambda c=komut: nav(c)
        ).grid(row=i, column=0, sticky="ew", pady=4)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_menusu_goster(app))


# Sol menü alt girişleri (ana_panel_ui.alt_menu_ac → butce_ui.*)
def butce_yeni_ac(app):
    _alt_isaretle(app, "butce_yeni_ac")
    butce_yeni_goster(app)


def butce_liste_ac(app):
    _alt_isaretle(app, "butce_liste_ac")
    butce_liste_goster(app)


def butce_gerceklesen_ac(app):
    _alt_isaretle(app, "butce_gerceklesen_ac")
    butce_gerceklesen_goster(app)


def butce_nakit_ac(app):
    _alt_isaretle(app, "butce_nakit_ac")
    butce_nakit_stub(app)


def butce_raporlar_ac(app):
    _alt_isaretle(app, "butce_raporlar_ac")
    butce_raporlar_stub(app)


def butce_ayarlar_ac(app):
    _alt_isaretle(app, "butce_ayarlar_ac")
    butce_ayarlar_goster(app)


# --------------------------------------------------------------------------- ekranlar


def butce_yeni_goster(app, plan_id: int | None = None):
    """Yeni bütçe kartı veya mevcut planı düzenle — belge üretmez."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)

    plan = ButceService.plan_getir(plan_id) if plan_id else None
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(
        ust,
        text=("BÜTÇE DÜZENLE" if plan else "YENİ BÜTÇE"),
        style="Baslik.TLabel",
    ).pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")

    form = ttk.Frame(app.icerik)
    form.pack(fill="x", pady=(16, 0))

    ad_var = tk.StringVar(value=(plan["ad"] if plan else ""))
    yil_var = tk.StringVar(value=str(plan["mali_yil"] if plan else _mali_yil_varsayilan()))
    pb_var = tk.StringVar(value=(plan["para_birimi"] if plan else "TRY"))
    olcu_var = tk.StringVar(value=OLCU_SATIS)
    kat_var = tk.StringVar(value="GENEL")
    yillik_var = tk.StringVar(value="")

    def satir(r, etiket, widget):
        ttk.Label(form, text=etiket).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    form.columnconfigure(1, weight=1, minsize=280)
    satir(0, "Ad *", ttk.Entry(form, textvariable=ad_var, width=40))
    satir(1, "Mali yıl *", ttk.Entry(form, textvariable=yil_var, width=12))
    satir(2, "Para birimi", ttk.Entry(form, textvariable=pb_var, width=8))
    if plan:
        ttk.Label(form, text="Kod").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Label(form, text=plan["kod"], foreground=LACIVERT).grid(row=3, column=1, sticky="w")

    ttk.Separator(app.icerik).pack(fill="x", pady=16)
    ttk.Label(
        app.icerik,
        text="Yıllık tutarı 12 aya eşit dağıt (kuruş farkı son ayda)",
        style="Baslik.TLabel",
    ).pack(anchor="w")

    dag = ttk.Frame(app.icerik)
    dag.pack(fill="x", pady=(8, 0))
    ttk.Label(dag, text="Ölçü").pack(side="left")
    ttk.Combobox(
        dag, textvariable=olcu_var, values=list(OLCU_TURLERI), width=12, state="readonly"
    ).pack(side="left", padx=8)
    ttk.Label(dag, text="Kategori").pack(side="left", padx=(12, 0))
    ttk.Entry(dag, textvariable=kat_var, width=16).pack(side="left", padx=8)
    ttk.Label(dag, text="Yıllık tutar").pack(side="left", padx=(12, 0))
    ttk.Entry(dag, textvariable=yillik_var, width=14).pack(side="left", padx=8)

    onizleme = ttk.Treeview(
        app.icerik,
        columns=("ay", "tutar"),
        show="headings",
        height=12,
    )
    onizleme.heading("ay", text="Ay")
    onizleme.heading("tutar", text="Plan tutarı")
    onizleme.column("ay", width=80, anchor="center")
    onizleme.column("tutar", width=140, anchor="e")
    onizleme.pack(fill="x", pady=(12, 0))

    def _onizle():
        onizleme.delete(*onizleme.get_children())
        try:
            yillik = Decimal((yillik_var.get() or "0").replace(",", "."))
        except Exception:
            messagebox.showerror("Bütçe", "Yıllık tutar sayı olmalı.", parent=app)
            return
        for i, t in enumerate(dagit_yillik_esit(yillik, 12), start=1):
            onizleme.insert("", "end", values=(i, _para(t)))

    def _kaydet():
        nonlocal plan
        ad = ad_var.get().strip()
        if not ad:
            messagebox.showwarning("Bütçe", "Ad zorunludur.", parent=app)
            return
        try:
            yil = int(yil_var.get().strip())
        except ValueError:
            messagebox.showerror("Bütçe", "Mali yıl geçersiz.", parent=app)
            return
        try:
            if plan is None:
                plan = ButceService.plan_olustur(
                    ad=ad,
                    mali_yil=yil,
                    para_birimi=pb_var.get().strip() or "TRY",
                )
            raw = (yillik_var.get() or "").strip()
            if raw:
                yillik = Decimal(raw.replace(",", "."))
                ButceService.yillik_dagit_ve_kaydet(
                    plan["id"],
                    yillik,
                    olcu_turu=olcu_var.get(),
                    kategori=kat_var.get().strip() or "GENEL",
                )
            messagebox.showinfo(
                "Bütçe",
                f"Kaydedildi: {plan['kod']}\n(Fatura / fiş oluşturulmadı.)",
                parent=app,
            )
            butce_liste_goster(app)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bütçe", str(hata), parent=app)

    dugmeler = ttk.Frame(app.icerik)
    dugmeler.pack(fill="x", pady=(12, 0))
    ttk.Button(dugmeler, text="Dağıtımı önizle", command=_onizle).pack(side="left")
    tk.Button(
        dugmeler,
        text="Kaydet",
        command=_kaydet,
        bg=SARI,
        fg=KOYU_LACIVERT,
        activebackground=SARI,
        relief="flat",
        padx=16,
        pady=6,
        font=FONT_UI_BOLD,
        cursor="hand2",
    ).pack(side="left", padx=12)

    # Mevcut satırları yükle
    if plan:
        mevcut = [
            s
            for s in (plan.get("satirlar") or [])
            if s["olcu_turu"] == OLCU_SATIS and s["kategori"] == "GENEL"
        ]
        if mevcut:
            toplam = sum((s["tutar"] for s in mevcut), Decimal("0"))
            yillik_var.set(str(toplam))
            _onizle()

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_yeni_goster(app, plan_id))


def butce_liste_goster(app):
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BÜTÇE LİSTESİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")
    ttk.Button(ust, text="Yeni", command=lambda: butce_yeni_goster(app)).pack(side="right", padx=8)

    yil_var = tk.StringVar(value=str(_mali_yil_varsayilan()))
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(12, 0))
    ttk.Label(filtre, text="Mali yıl").pack(side="left")
    ttk.Entry(filtre, textvariable=yil_var, width=8).pack(side="left", padx=8)

    tree = ttk.Treeview(
        app.icerik,
        columns=("kod", "ad", "yil", "durum", "pb", "surum"),
        show="headings",
        height=16,
    )
    for c, b, w in (
        ("kod", "Kod", 120),
        ("ad", "Ad", 220),
        ("yil", "Yıl", 60),
        ("durum", "Durum", 100),
        ("pb", "PB", 50),
        ("surum", "Sürüm", 60),
    ):
        tree.heading(c, text=b)
        tree.column(c, width=w, anchor="w" if c in ("kod", "ad", "durum") else "center")
    tree.pack(fill="both", expand=True, pady=(10, 0))

    def yenile():
        tree.delete(*tree.get_children())
        try:
            yil = int(yil_var.get().strip()) if yil_var.get().strip() else None
        except ValueError:
            yil = None
        for p in ButceService.planlari_listele(mali_yil=yil):
            tree.insert(
                "",
                "end",
                iid=str(p["id"]),
                values=(p["kod"], p["ad"], p["mali_yil"], p["durum"], p["para_birimi"], p["surum"]),
            )

    def ac_secili(_event=None):
        sec = tree.selection()
        if not sec:
            return
        butce_yeni_goster(app, plan_id=int(sec[0]))

    def gerceklesen_secili():
        sec = tree.selection()
        if not sec:
            messagebox.showinfo("Bütçe", "Listeden bir plan seçin.", parent=app)
            return
        butce_gerceklesen_goster(app, plan_id=int(sec[0]))

    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="left", padx=4)
    ttk.Button(filtre, text="Aç / düzenle", command=ac_secili).pack(side="left", padx=4)
    ttk.Button(filtre, text="Gerçekleşen", command=gerceklesen_secili).pack(side="left", padx=4)
    tree.bind("<Double-1>", ac_secili)
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_liste_goster(app))


def butce_gerceklesen_goster(app, plan_id: int | None = None):
    """Yan yana: Bütçe | Ön Muhasebe — kaynaklar toplanmaz."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BÜTÇE GERÇEKLEŞEN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")

    planlar = ButceService.planlari_listele()
    if not planlar:
        ttk.Label(
            app.icerik,
            text="Henüz bütçe yok. Önce Yeni Bütçe ile plan oluşturun.",
        ).pack(anchor="w", pady=16)
        return

    plan_map = {f"{p['kod']} — {p['ad']}": p for p in planlar}
    varsayilan = None
    if plan_id:
        for p in planlar:
            if p["id"] == plan_id:
                varsayilan = f"{p['kod']} — {p['ad']}"
                break
    if varsayilan is None:
        varsayilan = next(iter(plan_map))

    plan_var = tk.StringVar(value=varsayilan)
    olcu_var = tk.StringVar(value=OLCU_SATIS)

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(12, 0))
    ttk.Label(filtre, text="Plan").pack(side="left")
    ttk.Combobox(
        filtre,
        textvariable=plan_var,
        values=list(plan_map.keys()),
        width=40,
        state="readonly",
    ).pack(side="left", padx=8)
    ttk.Label(filtre, text="Ölçü").pack(side="left", padx=(12, 0))
    ttk.Combobox(
        filtre,
        textvariable=olcu_var,
        values=[OLCU_SATIS, OLCU_GIDER],
        width=10,
        state="readonly",
    ).pack(side="left", padx=8)

    kaynak_lbl = ttk.Label(
        app.icerik,
        text="Kaynak: Ön Muhasebe (genel muhasebe toplanmaz)",
        foreground=LACIVERT,
    )
    kaynak_lbl.pack(anchor="w", pady=(8, 0))
    meta_lbl = ttk.Label(app.icerik, text="", foreground=PASIF)
    meta_lbl.pack(anchor="w")

    tree = ttk.Treeview(
        app.icerik,
        columns=("ay", "butce", "on", "fark"),
        show="headings",
        height=14,
    )
    for c, b, w in (
        ("ay", "Ay", 50),
        ("butce", "Bütçe", 120),
        ("on", "Ön Muhasebe", 120),
        ("fark", "Fark (Ön − Bütçe)", 140),
    ):
        tree.heading(c, text=b)
        tree.column(c, width=w, anchor="e" if c != "ay" else "center")
    tree.pack(fill="both", expand=True, pady=(10, 0))

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=(8, 0))

    # Genel muhasebe yan sütunu — paket yoksa bilgilendirme
    gm_not = ttk.Label(
        app.icerik,
        text="Genel Muhasebe sütunu: henüz bağlanmadı (MVP — Ön Muhasebe ile toplanmaz).",
        foreground=PASIF,
    )
    gm_not.pack(anchor="w", pady=(4, 0))

    def yenile():
        tree.delete(*tree.get_children())
        p = plan_map.get(plan_var.get())
        if not p:
            return
        try:
            veri = ButceService.karsilastirma(p["id"], olcu_turu=olcu_var.get())
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bütçe", str(hata), parent=app)
            return
        for s in veri["satirlar"]:
            tree.insert(
                "",
                "end",
                values=(
                    s["ay"],
                    _para(s["butce"]),
                    _para(s["on_muhasebe"]),
                    _para(s["fark"]),
                ),
            )
        meta = veri.get("gerceklesen_meta") or {}
        meta_lbl.configure(
            text=(
                f"Durum: {meta.get('durum')} | Belge: {meta.get('belge_sayisi')} | "
                f"Boş aylar (sıfır uydurulmadı): {meta.get('bos_aylar') or '—'}"
            )
        )
        if meta.get("mesaj"):
            meta_lbl.configure(text=meta_lbl.cget("text") + f" — {meta['mesaj']}")
        ozet.configure(
            text=(
                f"Bütçe toplam: {_para(veri.get('butce_toplam'))}   |   "
                f"Ön Muhasebe toplam: {_para(veri.get('on_muhasebe_toplam'))}"
            )
        )

    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="left", padx=12)
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_gerceklesen_goster(app, plan_id))


def butce_ayarlar_goster(app):
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BÜTÇE AYARLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text=(
            "Eşik uyarıları, hesap/kategori eşleştirme ve bilanço hedefleri sonraki aşamada.\n"
            "TODO: ButceEslesme UI, genel muhasebe adaptörü, nakit bütçe ayarları."
        ),
    ).pack(anchor="w", pady=(16, 0))
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_ayarlar_goster(app))


def butce_nakit_stub(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="NAKİT BÜTÇESİ", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="TODO: Kasa/banka giriş-çıkış planı ve likidite (bu MVP kapsamı dışı).",
    ).pack(anchor="w", pady=(12, 0))
    ttk.Button(app.icerik, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(
        anchor="w", pady=16
    )


def butce_raporlar_stub(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="BÜTÇE RAPORLARI", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="TODO: Yıllık/aylık Excel-PDF çıktıları (bu MVP kapsamı dışı). Şimdilik Gerçekleşen ekranını kullanın.",
    ).pack(anchor="w", pady=(12, 0))
    ttk.Button(
        app.icerik, text="Gerçekleşen'e git", command=lambda: butce_gerceklesen_goster(app)
    ).pack(anchor="w", pady=(12, 0))
    ttk.Button(app.icerik, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(
        anchor="w", pady=8
    )
