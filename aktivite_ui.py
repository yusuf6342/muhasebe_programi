"""Aktivite Yönetimi hub — liste, dış işler, günlük sefer / rota."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database.aktivite_service import AktiviteService
from fatura_tema import ACIK_BG, stil_uygula, tk_buton


def aktivite_hub_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("aktivite")
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    AktiviteService.ensure_schema()

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(ust, text="AKTİVİTE YÖNETİMİ", font=("Segoe UI", 16, "bold")).pack(side="left")

    filtre_var = tk.StringVar(value="acik")
    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", padx=16, pady=4)
    for etiket, kod in (
        ("Açık işler", "acik"),
        ("Bugün", "bugun"),
        ("Gecikenler", "geciken"),
        ("Dış işler", "dis"),
        ("Tamamlanan", "tamamlanan"),
    ):
        ttk.Radiobutton(arac, text=etiket, value=kod, variable=filtre_var).pack(side="left", padx=4)

    tablo_frame = ttk.Frame(app.icerik)
    tablo_frame.pack(fill="both", expand=True, padx=16, pady=8)
    cols = ("konu", "tur", "durum", "plan", "belge", "teslimat", "oncelik")
    tablo = ttk.Treeview(tablo_frame, columns=cols, show="headings", height=18)
    for c, b, w in (
        ("konu", "Konu", 220),
        ("tur", "Tür", 120),
        ("durum", "Durum", 90),
        ("plan", "Plan", 110),
        ("belge", "Belge", 100),
        ("teslimat", "Teslimat", 100),
        ("oncelik", "Öncelik", 70),
    ):
        tablo.heading(c, text=b)
        tablo.column(c, width=w, anchor="w")
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(tablo_frame, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        f = filtre_var.get()
        if f == "dis":
            kayitlar = AktiviteService.dis_isler()
        elif f == "bugun":
            kayitlar = AktiviteService.listele(filtre="acik", bugun=True)
        else:
            kayitlar = AktiviteService.listele(filtre=f if f != "bugun" else "acik")
        for a in kayitlar:
            plan = ""
            if a.get("plan_tarih"):
                plan = a["plan_tarih"].strftime("%d.%m.%Y")
                if a.get("plan_saat"):
                    plan += f" {a['plan_saat']}"
            tablo.insert(
                "",
                "end",
                iid=str(a["id"]),
                values=(
                    a["konu"],
                    a["tur_ad"],
                    a["durum"],
                    plan,
                    a.get("kaynak_belge_no") or "",
                    a.get("teslimat_turu") or "",
                    a["oncelik"],
                ),
            )

    filtre_var.trace_add("write", lambda *_: yenile())
    yenile()

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=16, pady=(0, 16))
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="left", padx=2)
    tk_buton(alt, "Yeni Aktivite", lambda: _yeni_dialog(app, yenile), rol="yeni").pack(
        side="left", padx=2
    )

    def tamamla():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Aktivite", "Kayıt seçin.", parent=app)
            return
        try:
            AktiviteService.tamamla(int(sec[0]))
            yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Aktivite", str(exc), parent=app)

    def ertele():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Aktivite", "Kayıt seçin.", parent=app)
            return
        dlg = tk.Toplevel(app)
        dlg.title("Ertele")
        dlg.transient(app)
        dlg.grab_set()
        fr = ttk.Frame(dlg, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Yeni plan tarihi (GG.AA.YYYY)").pack(anchor="w")
        tarih_e = ttk.Entry(fr, width=16)
        tarih_e.insert(0, date.today().strftime("%d.%m.%Y"))
        tarih_e.pack(anchor="w", pady=4)
        ttk.Label(fr, text="Gerekçe").pack(anchor="w")
        ger = ttk.Entry(fr, width=40)
        ger.pack(anchor="w", pady=4)

        def _ok():
            from fatura_belge_aktarim.normalize import tarih_tr

            try:
                AktiviteService.ertele(
                    int(sec[0]),
                    yeni_tarih=tarih_tr(tarih_e.get()),
                    gerekce=ger.get().strip(),
                )
                dlg.destroy()
                yenile()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Ertele", str(exc), parent=dlg)

        tk_buton(fr, "Kaydet", _ok, rol="kaydet").pack(anchor="e", pady=8)

    def ata():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Aktivite", "Kayıt seçin.", parent=app)
            return
        dlg = tk.Toplevel(app)
        dlg.title("Başkasına ata")
        dlg.transient(app)
        dlg.grab_set()
        fr = ttk.Frame(dlg, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Yeni sorumlu personel id (boş = atamasız)").pack(anchor="w")
        pid_e = ttk.Entry(fr, width=12)
        pid_e.pack(anchor="w", pady=4)
        ttk.Label(fr, text="Gerekçe").pack(anchor="w")
        ger = ttk.Entry(fr, width=40)
        ger.pack(anchor="w", pady=4)

        def _ok():
            raw = pid_e.get().strip()
            try:
                yeni = int(raw) if raw else None
                AktiviteService.ata(int(sec[0]), yeni_sorumlu_id=yeni, gerekce=ger.get().strip())
                dlg.destroy()
                yenile()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Ata", str(exc), parent=dlg)

        tk_buton(fr, "Kaydet", _ok, rol="kaydet").pack(anchor="e", pady=8)

    tk_buton(alt, "Tamamla", tamamla, rol="onay").pack(side="left", padx=2)
    tk_buton(alt, "Ertele…", ertele, rol="ikincil").pack(side="left", padx=2)
    tk_buton(alt, "Ata…", ata, rol="ikincil").pack(side="left", padx=2)
    tk_buton(alt, "Günlük Sefer / Rota…", lambda: sefer_ekrani_goster(app), rol="yeni").pack(
        side="left", padx=8
    )
    harita = AktiviteService.harita_saglayici_durumu()
    ttk.Label(
        alt,
        text=(
            "Tamamlama stok/finans üretmez · "
            + (
                f"Harita: {harita['saglayici']}"
                if harita["bagli"]
                else "Harita sağlayıcı yok — sahte mesafe yok"
            )
        ),
        foreground="#64748B",
    ).pack(side="right")


def sefer_ekrani_goster(app) -> None:
    """Günlük sefer: önce liste, sonra test/elle rota; harita anahtarı yoksa açık uyarı."""
    app._icerigi_temizle()
    stil_uygula(root=app)
    AktiviteService.ensure_schema()
    harita = AktiviteService.harita_saglayici_durumu()

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(ust, text="GÜNLÜK SEFER / ROTA", font=("Segoe UI", 16, "bold")).pack(side="left")
    tk_buton(ust, "← Aktivite", lambda: aktivite_hub_goster(app), rol="ikincil").pack(
        side="right"
    )

    ttk.Label(
        app.icerik,
        text=harita["uyari"] or f"Harita bağlı: {harita.get('saglayici')}",
        foreground="#B45309" if not harita["bagli"] else "#15803D",
        wraplength=900,
    ).pack(anchor="w", padx=16)

    form = ttk.LabelFrame(app.icerik, text="Sefer", padding=8)
    form.pack(fill="x", padx=16, pady=8)
    tarih_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
    no_var = tk.StringVar(value="1")
    arac_var = tk.StringVar(value="ARAC-1")
    cikis_var = tk.StringVar(value="09:00")
    sefer_id_var = tk.IntVar(value=0)

    ttk.Label(form, text="Tarih").grid(row=0, column=0, sticky="w")
    ttk.Entry(form, textvariable=tarih_var, width=12).grid(row=0, column=1, sticky="w", padx=4)
    ttk.Label(form, text="Sefer no").grid(row=0, column=2, sticky="w", padx=(12, 0))
    ttk.Entry(form, textvariable=no_var, width=6).grid(row=0, column=3, sticky="w", padx=4)
    ttk.Label(form, text="Araç kod").grid(row=0, column=4, sticky="w", padx=(12, 0))
    ttk.Entry(form, textvariable=arac_var, width=12).grid(row=0, column=5, sticky="w", padx=4)
    ttk.Label(form, text="Çıkış").grid(row=0, column=6, sticky="w", padx=(12, 0))
    ttk.Entry(form, textvariable=cikis_var, width=8).grid(row=0, column=7, sticky="w", padx=4)

    ozet_var = tk.StringVar(value="")
    ttk.Label(app.icerik, textvariable=ozet_var, wraplength=900).pack(anchor="w", padx=16)

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, padx=16, pady=8)
    sol = ttk.LabelFrame(govde, text="Dış işler (rotaya aday)", padding=4)
    sol.pack(side="left", fill="both", expand=True, padx=(0, 8))
    sag = ttk.LabelFrame(govde, text="Sefer durakları", padding=4)
    sag.pack(side="left", fill="both", expand=True)

    aday = ttk.Treeview(sol, columns=("konu", "adres"), show="headings", height=14)
    aday.heading("konu", text="Konu")
    aday.heading("adres", text="Adres")
    aday.column("konu", width=160)
    aday.column("adres", width=200)
    aday.pack(fill="both", expand=True)

    durak = ttk.Treeview(
        sag, columns=("sira", "konu", "yol", "is", "varis"), show="headings", height=14
    )
    for c, b, w in (
        ("sira", "#", 36),
        ("konu", "Konu", 160),
        ("yol", "Yol dk", 60),
        ("is", "İş dk", 60),
        ("varis", "Varış", 70),
    ):
        durak.heading(c, text=b)
        durak.column(c, width=w)
    durak.pack(fill="both", expand=True)

    def _tarih():
        from fatura_belge_aktarim.normalize import tarih_tr

        return tarih_tr(tarih_var.get())

    def aday_yenile():
        for i in aday.get_children():
            aday.delete(i)
        for a in AktiviteService.dis_isler():
            aday.insert(
                "",
                "end",
                iid=str(a["id"]),
                values=(a["konu"], (a.get("adres_metin") or "—")[:60]),
            )

    def durak_yenile():
        for i in durak.get_children():
            durak.delete(i)
        sid = sefer_id_var.get()
        if not sid:
            ozet_var.set("Sefer seçilmedi / oluşturulmadı.")
            return
        s = AktiviteService.sefer_getir(sid)
        if not s:
            return
        for d in s.get("duraklar") or []:
            durak.insert(
                "",
                "end",
                iid=str(d["aktivite_id"]),
                values=(
                    d["sira"],
                    d["konu"],
                    d.get("yol_dk_onceki") if d.get("yol_dk_onceki") is not None else "—",
                    d.get("is_dk") if d.get("is_dk") is not None else "—",
                    d.get("tahmini_varis") or "—",
                ),
            )
        ozet_var.set(
            f"Sefer #{s['sefer_no']} · {s['durum']} · mod={s.get('rota_modu')} · "
            f"yol={s.get('tahmini_yol_dk') or '—'} · iş={s.get('tahmini_is_dk') or '—'} · "
            f"toplam={s.get('tahmini_toplam_dk') or '—'} · dönüş≈{s.get('tahmini_donus_saat') or '—'} · "
            f"{s.get('rota_ozet') or ''}"
        )

    def sefer_ac_veya_olustur():
        try:
            gun = _tarih()
            liste = AktiviteService.sefer_listele(sefer_tarih=gun)
            no = int(no_var.get() or 1)
            mevcut = next((x for x in liste if int(x["sefer_no"]) == no), None)
            if mevcut:
                sefer_id_var.set(int(mevcut["id"]))
            else:
                s = AktiviteService.sefer_olustur(
                    {
                        "sefer_tarih": gun,
                        "sefer_no": no,
                        "arac_kod": arac_var.get().strip(),
                        "cikis_saat": cikis_var.get().strip() or "09:00",
                    }
                )
                sefer_id_var.set(int(s["id"]))
            durak_yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sefer", str(exc), parent=app)

    def ekle():
        if not sefer_id_var.get():
            sefer_ac_veya_olustur()
        sec = aday.selection()
        if not sec:
            messagebox.showinfo("Sefer", "Dış iş seçin.", parent=app)
            return
        try:
            AktiviteService.sefer_durak_ekle(sefer_id_var.get(), int(sec[0]))
            durak_yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sefer", str(exc), parent=app)

    def cikar():
        sec = durak.selection()
        if not sec or not sefer_id_var.get():
            return
        try:
            AktiviteService.sefer_durak_cikar(sefer_id_var.get(), int(sec[0]))
            durak_yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sefer", str(exc), parent=app)

    def yukari():
        sid = sefer_id_var.get()
        if not sid:
            return
        s = AktiviteService.sefer_getir(sid)
        ids = [int(d["aktivite_id"]) for d in (s or {}).get("duraklar") or []]
        sec = durak.selection()
        if not sec or not ids:
            return
        aid = int(sec[0])
        i = ids.index(aid)
        if i <= 0:
            return
        ids[i - 1], ids[i] = ids[i], ids[i - 1]
        try:
            AktiviteService.sefer_durak_sirala(sid, ids)
            durak_yenile()
            durak.selection_set(str(aid))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sıra", str(exc), parent=app)

    def rota_test():
        if not sefer_id_var.get():
            messagebox.showinfo("Rota", "Önce sefer oluşturun.", parent=app)
            return
        try:
            AktiviteService.sefer_rota_hesapla(sefer_id_var.get(), mod="TEST_VERISI")
            durak_yenile()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rota", str(exc), parent=app)

    def kesinlestir():
        if not sefer_id_var.get():
            return
        try:
            AktiviteService.sefer_kesinlestir(sefer_id_var.get())
            durak_yenile()
            messagebox.showinfo("Sefer", "Sefer kesinleştirildi (stok hareketi yok).", parent=app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Sefer", str(exc), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=16, pady=(0, 16))
    tk_buton(alt, "Sefer aç / oluştur", sefer_ac_veya_olustur, rol="yeni").pack(side="left", padx=2)
    tk_buton(alt, "→ Durak ekle", ekle, rol="kaydet").pack(side="left", padx=2)
    tk_buton(alt, "Durak çıkar", cikar, rol="ikincil").pack(side="left", padx=2)
    tk_buton(alt, "Yukarı", yukari, rol="ikincil").pack(side="left", padx=2)
    tk_buton(alt, "Rota (test verisi)", rota_test, rol="ara").pack(side="left", padx=8)
    tk_buton(alt, "Kesinleştir", kesinlestir, rol="onay").pack(side="left", padx=2)
    aday_yenile()


def _yeni_dialog(app, yenile_cb) -> None:
    dlg = tk.Toplevel(app)
    dlg.title("Yeni aktivite")
    dlg.transient(app)
    dlg.grab_set()
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    turler = AktiviteService.tur_listesi()
    tur_map = {t["ad"]: t["kod"] for t in turler}

    ttk.Label(frm, text="Konu").grid(row=0, column=0, sticky="w")
    konu = ttk.Entry(frm, width=42)
    konu.grid(row=0, column=1, sticky="ew", pady=2)

    ttk.Label(frm, text="Tür").grid(row=1, column=0, sticky="w")
    tur_cb = ttk.Combobox(frm, values=list(tur_map.keys()), state="readonly", width=40)
    tur_cb.grid(row=1, column=1, sticky="ew", pady=2)
    if tur_map:
        tur_cb.current(0)

    ttk.Label(frm, text="Plan tarih (GG.AA.YYYY)").grid(row=2, column=0, sticky="w")
    tarih_e = ttk.Entry(frm, width=16)
    tarih_e.insert(0, date.today().strftime("%d.%m.%Y"))
    tarih_e.grid(row=2, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Teslimat türü").grid(row=3, column=0, sticky="w")
    teslim_cb = ttk.Combobox(
        frm, values=list(AktiviteService.teslimat_turleri()), state="readonly", width=24
    )
    teslim_cb.set("BELIRLENMEDI")
    teslim_cb.grid(row=3, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Adres").grid(row=4, column=0, sticky="nw")
    adres = tk.Text(frm, width=40, height=3)
    adres.grid(row=4, column=1, sticky="ew", pady=2)

    def kaydet():
        from fatura_belge_aktarim.normalize import tarih_tr

        try:
            AktiviteService.kaydet(
                {
                    "konu": konu.get().strip(),
                    "tur_kod": tur_map.get(tur_cb.get()),
                    "plan_tarih": tarih_tr(tarih_e.get()),
                    "teslimat_turu": teslim_cb.get() or "BELIRLENMEDI",
                    "adres_metin": adres.get("1.0", "end").strip(),
                    "durum": "ACIK",
                }
            )
            dlg.destroy()
            yenile_cb()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Aktivite", str(exc), parent=dlg)

    tk_buton(frm, "Kaydet", kaydet, rol="kaydet").grid(row=5, column=1, sticky="e", pady=8)
