"""PERSONEL → Performans ve Kariyer / Ücret ve Kazanç Dağıtımı ekranları."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from personel_ui import _menu_isaretle, personel_menusu_goster

_DURUM_ETIKET = {
    "PLANLANDI": "Planlandı",
    "BASLADI": "Başlandı",
    "ENGELLENDI": "Engellendi",
    "KONTROL_BEKLIYOR": "Kontrol Bekliyor",
    "TAMAMLANDI": "Tamamlandı",
}
_DURUM_KOD = {v: k for k, v in _DURUM_ETIKET.items()}
_ALAN_ETIKET = {
    "SATIS": "Satış",
    "HAZIRLAMA": "Hazırlama",
    "STOK": "Stok",
    "SEVKIYAT": "Sevkiyat",
    "FINANS": "Finans",
}
_ALAN_KOD = {v: k for k, v in _ALAN_ETIKET.items()}


def _ust(app, baslik: str):
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Personel", command=lambda: personel_menusu_goster(app)).pack(
        side="right"
    )
    return ust


def _personel_etiket_map(secenekler: list[dict]) -> dict[str, int]:
    return {s["etiket"]: s["id"] for s in secenekler}


def _is_formu(app, *, kayit: dict | None, on_ok) -> None:
    """Yeni / düzenle iş formu — 1366×768 ve %125 ölçeğe sığacak boyut."""
    from database.personel_performans_service import PersonelPerformansService

    dlg = tk.Toplevel(app)
    dlg.title("İş düzenle" if kayit else "Yeni iş")
    dlg.transient(app)
    dlg.grab_set()
    dlg.geometry("520x480")
    dlg.minsize(480, 420)

    govde = ttk.Frame(dlg, padding=10)
    govde.pack(fill="both", expand=True)
    govde.columnconfigure(1, weight=1)

    aktifler = PersonelPerformansService.personel_secenekleri(yalniz_aktif=True)
    # Düzenlemede pasif sorumlu da listede olsun
    if kayit and kayit.get("sorumlu_personel_id"):
        sid = int(kayit["sorumlu_personel_id"])
        if not any(s["id"] == sid for s in aktifler):
            try:
                eski = PersonelPerformansService.personel_secenekleri(yalniz_aktif=False)
                for s in eski:
                    if s["id"] == sid:
                        aktifler = [s] + aktifler
                        break
            except Exception:
                pass
    pmap = _personel_etiket_map(aktifler)

    baslik = tk.StringVar(value=(kayit or {}).get("baslik") or "")
    p_etiket = tk.StringVar()
    if kayit and kayit.get("sorumlu_personel_id"):
        for et, pid in pmap.items():
            if pid == kayit["sorumlu_personel_id"]:
                p_etiket.set(et)
                break
        if not p_etiket.get() and kayit.get("sorumlu_etiket"):
            p_etiket.set(kayit["sorumlu_etiket"])
    alan_g = tk.StringVar(
        value=_ALAN_ETIKET.get((kayit or {}).get("gorev_alani") or "HAZIRLAMA", "Hazırlama")
    )
    durum_g = tk.StringVar(
        value=_DURUM_ETIKET.get((kayit or {}).get("durum") or "PLANLANDI", "Planlandı")
    )
    hedef_t = tk.StringVar(value=(kayit or {}).get("hedef_tarih") or date.today().isoformat())
    hedef_s = tk.StringVar(value=(kayit or {}).get("hedef_saat") or "")
    engel = tk.StringVar(value=(kayit or {}).get("dis_engel") or "")

    r = 0
    ttk.Label(govde, text="İş başlığı *").grid(row=r, column=0, sticky="w", pady=2)
    ttk.Entry(govde, textvariable=baslik, width=48).grid(row=r, column=1, sticky="ew", pady=2)
    r += 1
    ttk.Label(govde, text="Sorumlu personel *").grid(row=r, column=0, sticky="nw", pady=2)
    p_frame = ttk.Frame(govde)
    p_frame.grid(row=r, column=1, sticky="ew", pady=2)
    p_frame.columnconfigure(0, weight=1)
    if not aktifler and not (kayit and kayit.get("sorumlu_personel_id")):
        ttk.Label(
            p_frame,
            text="Aktif personel kaydı yok. Önce PERSONEL kartından personel ekleyin.\n"
            "Serbest metin veya sahte personel oluşturulamaz.",
            wraplength=340,
            foreground="#a30",
        ).grid(row=0, column=0, sticky="w")
        p_cb = None
    else:
        p_ara = tk.StringVar()
        ttk.Entry(p_frame, textvariable=p_ara, width=40).grid(row=0, column=0, sticky="ew")
        p_cb = ttk.Combobox(p_frame, textvariable=p_etiket, values=list(pmap), width=48)
        p_cb.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        def _p_filtre(*_a):
            q = (p_ara.get() or "").strip().lower()
            vals = [e for e in pmap if not q or q in e.lower()]
            p_cb["values"] = vals

        p_ara.trace_add("write", _p_filtre)
    r += 1
    ttk.Label(govde, text="Alan / iş türü").grid(row=r, column=0, sticky="w", pady=2)
    ttk.Combobox(
        govde, textvariable=alan_g, values=list(_ALAN_ETIKET.values()), state="readonly", width=46
    ).grid(row=r, column=1, sticky="w", pady=2)
    r += 1
    ttk.Label(govde, text="İş açıklaması").grid(row=r, column=0, sticky="nw", pady=2)
    aciklama = tk.Text(govde, width=46, height=4, wrap="word")
    aciklama.grid(row=r, column=1, sticky="ew", pady=2)
    if kayit and kayit.get("aciklama"):
        aciklama.insert("1.0", kayit["aciklama"])
    r += 1
    ttk.Label(govde, text="Hedef tarih").grid(row=r, column=0, sticky="w", pady=2)
    hf = ttk.Frame(govde)
    hf.grid(row=r, column=1, sticky="w", pady=2)
    ttk.Entry(hf, textvariable=hedef_t, width=14).pack(side="left")
    ttk.Label(hf, text="Saat (SS:DD)").pack(side="left", padx=(8, 2))
    ttk.Entry(hf, textvariable=hedef_s, width=8).pack(side="left")
    r += 1
    ttk.Label(govde, text="Durum").grid(row=r, column=0, sticky="w", pady=2)
    ttk.Combobox(
        govde, textvariable=durum_g, values=list(_DURUM_ETIKET.values()), state="readonly", width=46
    ).grid(row=r, column=1, sticky="w", pady=2)
    r += 1
    ttk.Label(govde, text="Engel / bekleme").grid(row=r, column=0, sticky="w", pady=2)
    ttk.Entry(govde, textvariable=engel, width=48).grid(row=r, column=1, sticky="ew", pady=2)
    r += 1
    ttk.Label(
        govde,
        text="Sorumlu atamak başarı puanı veya prim üretmez. Tamamlandı = otomatik onay/ödeme değil.",
        wraplength=460,
    ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
    r += 1
    dug = ttk.Frame(govde)
    dug.grid(row=r, column=0, columnspan=2, sticky="e", pady=12)

    def kaydet():
        try:
            if p_cb is None and not (kayit and kayit.get("sorumlu_personel_id")):
                raise ValueError(
                    "Aktif personel yok. Önce personel kartı oluşturun; "
                    "personel seçmeden iş kaydedilemez."
                )
            pid = pmap.get(p_etiket.get().strip())
            if pid is None:
                # Pasif personel etiketi düzenlemede korunmuş olabilir
                if kayit and kayit.get("sorumlu_personel_id") and p_etiket.get():
                    pid = kayit["sorumlu_personel_id"]
                else:
                    raise ValueError("Sorumlu personel listeden seçilmelidir.")
            veri = {
                "baslik": baslik.get(),
                "sorumlu_personel_id": pid,
                "gorev_alani": _ALAN_KOD.get(alan_g.get(), alan_g.get()),
                "durum": _DURUM_KOD.get(durum_g.get(), durum_g.get()),
                "aciklama": aciklama.get("1.0", "end").strip(),
                "hedef_tarih": hedef_t.get().strip() or None,
                "hedef_saat": hedef_s.get().strip() or None,
                "dis_engel": engel.get().strip() or None,
            }
            if kayit:
                veri["id"] = kayit["id"]
            PersonelPerformansService.is_kaydet(veri)
            dlg.destroy()
            on_ok()
        except Exception as e:
            messagebox.showerror("İş", str(e), parent=dlg)

    ttk.Button(dug, text="Kaydet", command=kaydet).pack(side="right", padx=4)
    ttk.Button(dug, text="Kapat", command=dlg.destroy).pack(side="right")


def _is_panosu_kur(app, tab_is) -> None:
    from database.personel_performans_service import PersonelPerformansService

    filtre = ttk.Frame(tab_is)
    filtre.pack(fill="x", padx=8, pady=(8, 4))

    personeller = PersonelPerformansService.personel_secenekleri(yalniz_aktif=True)
    # Filtrede pasifler de (eski işler için)
    try:
        tum = PersonelPerformansService.personel_secenekleri(yalniz_aktif=False)
    except Exception:
        tum = personeller
    pmap = _personel_etiket_map(tum)
    filtre_secenek = ["Tüm personel", "Atanmamış işler"] + list(pmap.keys())

    f_personel = tk.StringVar(value="Tüm personel")
    f_durum = tk.StringVar(value="Tümü")
    f_baslik = tk.StringVar()

    ttk.Label(filtre, text="Personel").pack(side="left")
    cb_p = ttk.Combobox(filtre, textvariable=f_personel, values=filtre_secenek, width=28)
    cb_p.pack(side="left", padx=(4, 10))
    ttk.Label(filtre, text="Durum").pack(side="left")
    cb_d = ttk.Combobox(
        filtre,
        textvariable=f_durum,
        values=["Tümü"] + list(_DURUM_ETIKET.values()),
        state="readonly",
        width=16,
    )
    cb_d.pack(side="left", padx=(4, 10))
    ttk.Label(filtre, text="Başlık").pack(side="left")
    ttk.Entry(filtre, textvariable=f_baslik, width=18).pack(side="left", padx=(4, 6))

    orta = ttk.Frame(tab_is)
    orta.pack(fill="both", expand=True, padx=8, pady=4)
    cols = ("personel", "baslik", "alan", "durum", "hedef", "engel")
    tree = ttk.Treeview(orta, columns=cols, show="headings", height=11)
    basliklar = {
        "personel": ("Sorumlu personel", 180),
        "baslik": ("İş başlığı", 160),
        "alan": ("Alan", 90),
        "durum": ("Durum", 110),
        "hedef": ("Hedef", 110),
        "engel": ("Engel / bekleme", 140),
    }
    for k, (b, w) in basliklar.items():
        tree.heading(k, text=b)
        tree.column(k, width=w, minwidth=60)
    ys = ttk.Scrollbar(orta, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ys.set)
    tree.pack(side="left", fill="both", expand=True)
    ys.pack(side="right", fill="y")

    bilgi = ttk.Label(tab_is, text="")
    bilgi.pack(fill="x", padx=8)

    def yenile():
        for i in tree.get_children():
            tree.delete(i)
        try:
            atanmamis = f_personel.get() == "Atanmamış işler"
            pid = None
            if not atanmamis and f_personel.get() not in ("Tüm personel", ""):
                pid = pmap.get(f_personel.get())
            durum_kod = None
            if f_durum.get() != "Tümü":
                durum_kod = _DURUM_KOD.get(f_durum.get())
            kayitlar = PersonelPerformansService.is_panosu(
                personel_id=pid,
                atanmamis=atanmamis,
                durum=durum_kod,
                baslik_arama=f_baslik.get(),
            )
            for k in kayitlar:
                tree.insert(
                    "",
                    "end",
                    iid=str(k["id"]),
                    values=(
                        k.get("sorumlu_etiket") or "Atanmamış",
                        k.get("baslik") or "",
                        _ALAN_ETIKET.get(k.get("gorev_alani") or "", k.get("gorev_alani") or ""),
                        _DURUM_ETIKET.get(k.get("durum") or "", k.get("durum") or ""),
                        k.get("hedef_gosterim") or "",
                        k.get("dis_engel") or "",
                    ),
                )
            eksik = sum(1 for k in kayitlar if k.get("eksik_sorumlu"))
            bilgi.configure(
                text=f"{len(kayitlar)} iş"
                + (f" · {eksik} atanmamış (performansa dahil değil)" if eksik else "")
            )
        except Exception as e:
            messagebox.showerror("İş panosu", str(e), parent=app)

    def secili_id():
        s = tree.selection()
        return int(s[0]) if s else None

    def duzenle(_e=None):
        iid = secili_id()
        if iid is None:
            messagebox.showinfo("İş", "Düzenlemek için bir satır seçin.", parent=app)
            return
        try:
            kayit = PersonelPerformansService.is_getir(iid)
            _is_formu(app, kayit=kayit, on_ok=yenile)
        except Exception as e:
            messagebox.showerror("İş", str(e), parent=app)

    def yeni():
        _is_formu(app, kayit=None, on_ok=yenile)

    dug = ttk.Frame(tab_is)
    dug.pack(fill="x", padx=8, pady=4)
    ttk.Button(dug, text="Yeni İş", command=yeni).pack(side="left", padx=(0, 6))
    ttk.Button(dug, text="Düzenle", command=duzenle).pack(side="left", padx=(0, 6))
    ttk.Button(dug, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(
        dug,
        text="Filtrele",
        command=yenile,
    ).pack(side="left", padx=8)

    tree.bind("<Double-1>", duzenle)
    cb_p.bind("<<ComboboxSelected>>", lambda _e: yenile())
    cb_d.bind("<<ComboboxSelected>>", lambda _e: yenile())
    yenile()


def performans_kariyer_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERFORMANS VE KARİYER")
    ttk.Label(
        app.icerik,
        text="Görevler, katkı, değerlendirme, beceriler ve 90 günlük gelişim. "
        "Standart personel kartına bağlıdır; ayrı sicil yoktur. "
        "Kariyer kademesi ortaklık/hisse devri üretmez.",
        wraplength=780,
    ).pack(anchor="w", pady=(10, 0))

    from database.personel_service import PersonelService
    from database.personel_performans_service import PersonelPerformansService

    PersonelPerformansService.hazirla()
    personeller = PersonelService.listele(limit=500)
    pmap = {f"{p['kod']} — {p['ad_soyad']}": p["id"] for p in personeller}

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, pady=10)
    tab_is = ttk.Frame(nb)
    tab_katki = ttk.Frame(nb)
    tab_deg = ttk.Frame(nb)
    tab_gel = ttk.Frame(nb)
    nb.add(tab_is, text="Günlük iş panosu")
    nb.add(tab_katki, text="Katkı")
    nb.add(tab_deg, text="Değerlendirme")
    nb.add(tab_gel, text="Gelişim / Kariyer")

    _is_panosu_kur(app, tab_is)

    # --- Katkı ---
    pvar = tk.StringVar(value=next(iter(pmap), ""))
    ustk = ttk.Frame(tab_katki)
    ustk.pack(fill="x", padx=8, pady=8)
    ttk.Combobox(ustk, textvariable=pvar, values=list(pmap), width=40, state="readonly").pack(
        side="left"
    )
    ktree = ttk.Treeview(
        tab_katki, columns=("asama", "belge", "pay", "adet", "tarih"), show="headings", height=10
    )
    for k, b in zip(("asama", "belge", "pay", "adet", "tarih"), ("Aşama", "Belge", "Pay%", "Adet", "Tarih")):
        ktree.heading(k, text=b)
    ktree.pack(fill="both", expand=True, padx=8)

    def katki_yenile():
        for i in ktree.get_children():
            ktree.delete(i)
        pid = pmap.get(pvar.get())
        if not pid:
            return
        for o in PersonelPerformansService.katki_raporu(pid):
            ktree.insert(
                "", "end",
                values=(o["asama"], f"{o['kaynak_turu']}:{o['belge_id']}", o["pay_yuzde"], o["adet"], o["tarih"]),
            )

    def katki_ekle():
        pid = pmap.get(pvar.get())
        if not pid:
            return
        dlg = tk.Toplevel(app)
        dlg.title("Katkı olayı")
        dlg.transient(app)
        f = ttk.Frame(dlg, padding=12)
        f.pack()
        asama = tk.StringVar(value="HAZIRLAMA")
        belge = tk.StringVar(value="1")
        pay = tk.StringVar(value="100")
        ttk.Label(f, text="Aşama").grid(row=0, column=0)
        ttk.Combobox(
            f, textvariable=asama,
            values=["SATIS_SAHIBI", "HAZIRLAMA", "KONTROL", "TESLIM", "TAHSILAT_TAKIP"],
            state="readonly",
        ).grid(row=0, column=1)
        ttk.Label(f, text="Belge id").grid(row=1, column=0)
        ttk.Entry(f, textvariable=belge).grid(row=1, column=1)
        ttk.Label(f, text="Pay %").grid(row=2, column=0)
        ttk.Entry(f, textvariable=pay).grid(row=2, column=1)

        def kaydet():
            try:
                PersonelPerformansService.katki_kaydet(
                    {
                        "personel_id": pid,
                        "yapan_personel_id": pid,
                        "asama": asama.get(),
                        "belge_id": int(belge.get()),
                        "pay_yuzde": pay.get(),
                        "adet": 1,
                        "satir_sayisi": 1,
                    }
                )
                dlg.destroy()
                katki_yenile()
            except Exception as e:
                messagebox.showerror("Katkı", str(e), parent=dlg)

        ttk.Button(f, text="Kaydet", command=kaydet).grid(row=3, column=0, columnspan=2, pady=8)

    ttk.Button(ustk, text="Yenile", command=katki_yenile).pack(side="left", padx=6)
    ttk.Button(ustk, text="Katkı Ekle", command=katki_ekle).pack(side="left")
    katki_yenile()

    # --- Değerlendirme ---
    df = ttk.Frame(tab_deg, padding=12)
    df.pack(anchor="nw")
    d_pvar = tk.StringVar(value=next(iter(pmap), ""))
    ttk.Combobox(df, textvariable=d_pvar, values=list(pmap), width=40, state="readonly").grid(
        row=0, column=0, columnspan=2, sticky="w"
    )
    alanlar = {}
    for i, (ad, key) in enumerate(
        (("Görev sonucu", "gorev_sonucu"), ("Kalite", "kalite"),
         ("Ekip katkısı", "ekip_katkisi"), ("Gelişim", "gelisim"), ("Örnek sayısı", "ornek_sayisi")),
        start=1,
    ):
        ttk.Label(df, text=ad).grid(row=i, column=0, sticky="w")
        v = tk.StringVar(value="80" if key != "ornek_sayisi" else "10")
        alanlar[key] = v
        ttk.Entry(df, textvariable=v, width=10).grid(row=i, column=1, sticky="w")

    def deg_kaydet():
        pid = pmap.get(d_pvar.get())
        if not pid:
            return
        try:
            r = PersonelPerformansService.degerlendirme_kaydet(
                {
                    "personel_id": pid,
                    "yil": date.today().year,
                    "ay": date.today().month,
                    **{k: v.get() for k, v in alanlar.items()},
                    "kesin": True,
                }
            )
            messagebox.showinfo(
                "Değerlendirme",
                f"Toplam puan: {r['toplam_puan']} (kesin={r['kesin']})",
                parent=app,
            )
        except Exception as e:
            messagebox.showerror("Değerlendirme", str(e), parent=app)

    ttk.Button(df, text="Kaydet (40/30/20/10)", command=deg_kaydet).grid(
        row=6, column=0, columnspan=2, pady=10
    )

    # --- Gelişim ---
    gf = ttk.Frame(tab_gel, padding=12)
    gf.pack(anchor="nw")
    g_pvar = tk.StringVar(value=next(iter(pmap), ""))
    beceri = tk.StringVar(value="İkinci görev yeterliliği")
    ttk.Combobox(gf, textvariable=g_pvar, values=list(pmap), width=40, state="readonly").grid(
        row=0, column=0, columnspan=2
    )
    ttk.Label(gf, text="90 gün hedef beceri").grid(row=1, column=0, sticky="w")
    ttk.Entry(gf, textvariable=beceri, width=40).grid(row=1, column=1)

    def gel_kaydet():
        pid = pmap.get(g_pvar.get())
        if not pid:
            return
        try:
            r = PersonelPerformansService.gelisim_plani(
                {"personel_id": pid, "hedef_beceri": beceri.get()}
            )
            PersonelPerformansService.kariyer_karari(
                {
                    "personel_id": pid,
                    "kademe": "YETKIN",
                    "yol": "UZMANLIK",
                    "onayli": False,
                    "eksik_kosullar": "Yönetici onayı bekleniyor",
                }
            )
            messagebox.showinfo(
                "Gelişim",
                f"Plan {r['baslangic']} – {r['bitis']}. Kariyer önerisi oluşturuldu (ortaklık değil).",
                parent=app,
            )
        except Exception as e:
            messagebox.showerror("Gelişim", str(e), parent=app)

    ttk.Button(gf, text="90 Günlük Plan + Kademe Önerisi", command=gel_kaydet).grid(
        row=2, column=0, columnspan=2, pady=10
    )
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: performans_kariyer_goster(app))


def ucret_kazanc_goster(app):
    app._icerigi_temizle()
    _ust(app, "ÜCRET VE KAZANÇ DAĞITIMI")
    ttk.Label(
        app.icerik,
        text="Tahsil edilmiş kâr katkısı (H=M×q), giderler, güvence ve prim havuzu. "
        "Örnek oran %%10 / dağıtım 50-30-20 başlangıç önerisidir; canlı politika değildir. "
        "Simülasyon gerçek ödeme veya muhasebe fişi üretmez.",
        wraplength=780,
    ).pack(anchor="w", pady=(10, 0))

    from database.personel_performans_service import PersonelPerformansService
    from database.personel_service import PersonelService

    PersonelPerformansService.hazirla()
    pol = PersonelPerformansService.politika_getir()
    ttk.Label(
        app.icerik,
        text=(
            f"Politika: {pol['kod']} v{pol['surum']} | oran={pol['prim_orani']} | "
            f"güvence={pol['guvence_tutari']:,.0f} | canlı={pol['canli_politika']}"
            if pol else "Politika yok"
        ),
    ).pack(anchor="w", pady=(8, 0))

    form = ttk.Frame(app.icerik)
    form.pack(anchor="w", pady=12)
    tahsil = tk.StringVar(value="300000")
    gider = tk.StringVar(value="180000")
    zarar = tk.StringVar(value="0")
    for i, (etiket, var) in enumerate(
        (("Tahsil kâr katkısı", tahsil), ("Uygun gider", gider), ("Önceki zarar devri", zarar))
    ):
        ttk.Label(form, text=etiket).grid(row=i, column=0, sticky="w")
        ttk.Entry(form, textvariable=var, width=16).grid(row=i, column=1, sticky="w", pady=2)

    personeller = PersonelService.listele(limit=50)
    # Simülasyon için ilk 3 veya örnek
    sonuc_txt = tk.Text(app.icerik, height=16, wrap="word")
    sonuc_txt.pack(fill="both", expand=True, pady=8)

    def simule():
        sonuc_txt.delete("1.0", "end")
        try:
            bugun = date.today()
            donem = PersonelPerformansService.donem_olustur(
                bugun.replace(day=1),
                bugun,
                simulasyon=True,
            )
            kisiler = []
            ornek = [
                (0, 80),
                (2, 90),
                (5, 100),
            ]
            for i, p in enumerate(personeller[:3]):
                hy, pu = ornek[i] if i < 3 else (0, 80)
                kisiler.append(
                    {"personel_id": p["id"], "hizmet_yili": hy, "performans": pu, "katilim": 1}
                )
            if len(kisiler) < 3:
                # Test personeli yoksa motoru doğrudan göster
                from database.personel_prim_motoru import havuz_hesapla, kisi_dagitimi, DagitimKisi
                from decimal import Decimal

                h = havuz_hesapla(
                    tahsil_kar_katkisi_toplam=tahsil.get(),
                    uygun_giderler=gider.get(),
                    onceki_zarar_devri=zarar.get(),
                    guvence_tutari=pol["guvence_tutari"] if pol else 20000,
                    prim_orani=pol["prim_orani"] if pol else "0.10",
                )
                d = kisi_dagitimi(
                    h["prim_butcesi"],
                    [
                        DagitimKisi(1, 0, Decimal(80)),
                        DagitimKisi(2, 2, Decimal(90)),
                        DagitimKisi(3, 5, Decimal(100)),
                    ],
                )
                sonuc_txt.insert("end", f"Havuz: {h}\n\nDağıtım (örnek A/B/C):\n")
                for s in d["kisiler"]:
                    sonuc_txt.insert(
                        "end",
                        f"  P{s['personel_id']}: {s['toplam']} "
                        f"(ekip {s['ekip_payi']} + katkı {s['katki_payi']} + kıdem {s['kidem_payi']})\n",
                    )
                sonuc_txt.insert(
                    "end",
                    f"\nToplam {d['dagitilan']} / bütçe {d['butce']} / dağılmamış {d['dagitilmamis']}\n"
                    "Simülasyon — ödeme yok.\n",
                )
                return

            r = PersonelPerformansService.donem_hesapla(
                donem["id"],
                tahsil_kar=tahsil.get(),
                uygun_gider=gider.get(),
                onceki_zarar=zarar.get(),
                kisiler=kisiler,
            )
            sonuc_txt.insert("end", f"Dönem #{r['donem_id']} durum={r['durum']}\n")
            sonuc_txt.insert("end", f"Havuz: {r['havuz']}\n\nKişi payları (işveren maliyeti bütçesi):\n")
            for s in r["dagitim"]["kisiler"]:
                ad = next((p["ad_soyad"] for p in personeller if p["id"] == s["personel_id"]), s["personel_id"])
                sonuc_txt.insert(
                    "end",
                    f"  {ad}: {s['toplam']:,.2f} TL "
                    f"[ekip {s['ekip_payi']:,.2f} + katkı {s['katki_payi']:,.2f} + kıdem {s['kidem_payi']:,.2f}]\n",
                )
            sonuc_txt.insert(
                "end",
                f"\nDağıtılan {r['dagitim']['dagitilan']:,.2f} | "
                f"Dağılmamış {r['dagitim']['dagitilmamis']:,.2f}\n"
                f"{r.get('uyari') or ''}\n",
            )
        except Exception as e:
            messagebox.showerror("Prim", str(e), parent=app)

    dug = ttk.Frame(app.icerik)
    dug.pack(fill="x")
    ttk.Button(dug, text="Simülasyonu Çalıştır", command=simule).pack(side="left")
    ttk.Button(
        dug,
        text="H = M×q örneği (30.000×%50)",
        command=lambda: messagebox.showinfo(
            "H hesabı",
            "S=100.000 C=70.000 → M=30.000; q=0,50 → H=15.000 TL.\n"
            "Sonraki %50 tahsilatta yalnız ilave 15.000 TL.",
            parent=app,
        ),
    ).pack(side="left", padx=8)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: ucret_kazanc_goster(app))


def performans_kariyer_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: performans_kariyer_goster(app))


def ucret_kazanc_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: ucret_kazanc_goster(app))
