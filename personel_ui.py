"""PERSONEL ana menüsü ve alt ekranlar."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from ana_panel_tema import LACIVERT, SARI, BEYAZ, FONT_UI, FONT_UI_BOLD, METIN


def _menu_isaretle(app, anahtar="personel"):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle(anahtar)
        return
    for dugme_anahtari, dugme in getattr(app, "menu_dugmeleri", {}).items():
        if dugme_anahtari == anahtar:
            dugme.configure(style="SeciliMenu.TButton")
        elif dugme_anahtari == "hizli_satis":
            dugme.configure(style="HizliSatisMenu.TButton")
        else:
            dugme.configure(style="Menu.TButton")


def personel_menusu_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="PERSONEL", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Personel kartı, özlük arşivi, maaş/avans, puantaj/izin ve SGK–beyan kanıt takibi. "
        "Resmî portal gönderimi yoktur; durumlar hazırlık ve onay belgesi kaydıdır.",
        wraplength=780,
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (baslik, komut) in enumerate((
        ("PERSONEL KARTLARI", lambda: personel_kartlari_goster(app)),
        ("PERSONEL LİSTESİ", lambda: personel_listesi_goster(app)),
        ("ÖZLÜK DOSYALARI", lambda: ozluk_dosyalari_goster(app)),
        ("PUANTAJ VE İZİNLER", lambda: puantaj_izinler_goster(app)),
        ("MAAŞ VE BORDRO TAKİBİ", lambda: maas_bordro_goster(app)),
        ("AVANS VE PERSONEL ÖDEMELERİ", lambda: avans_odeme_goster(app)),
        ("PERSONEL MASRAFLARI", lambda: masraf_goster(app)),
        ("SGK VE BEYAN TAKİBİ", lambda: sgk_beyan_goster(app)),
        ("PERFORMANS VE KARİYER", lambda: _performans_ac(app)),
        ("ÜCRET VE KAZANÇ DAĞITIMI", lambda: _ucret_kazanc_ac(app)),
        ("PERSONEL RAPORLARI", lambda: raporlar_goster(app)),
        ("PERSONEL FORMLARI", lambda: formlar_goster(app)),
        ("PERSONEL AYARLARI", lambda: ayarlar_goster(app)),
    )):
        ttk.Button(
            alt, text=baslik, style="AltMenu.TButton",
            command=lambda c=komut: nav(c),
        ).grid(row=i, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: personel_menusu_goster(app))


def _ust(app, baslik: str, geri=None):
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Personel",
        command=lambda: (geri or personel_menusu_goster)(app),
    ).pack(side="right")
    return ust


# --- Kartlar / Liste ---------------------------------------------------------

def _performans_ac(app):
    from personel_performans_ui import performans_kariyer_goster

    performans_kariyer_goster(app)


def _ucret_kazanc_ac(app):
    from personel_performans_ui import ucret_kazanc_goster

    ucret_kazanc_goster(app)


def personel_kartlari_goster(app):
    from personel_kart_ui import PersonelKartDialog

    PersonelKartDialog(app)


def personel_listesi_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERSONEL LİSTESİ")
    from database.personel_service import PersonelService
    from database.models.personel import CALISMA_DURUMLARI

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(12, 0))
    arama_var = tk.StringVar()
    durum_var = tk.StringVar(value="")
    ttk.Label(filtre, text="Ara").pack(side="left")
    ttk.Entry(filtre, textvariable=arama_var, width=28).pack(side="left", padx=6)
    ttk.Label(filtre, text="Durum").pack(side="left", padx=(12, 0))
    durum_cb = ttk.Combobox(
        filtre,
        textvariable=durum_var,
        values=[""] + [f"{k}|{v}" for k, v in CALISMA_DURUMLARI],
        width=22,
        state="readonly",
    )
    durum_cb.pack(side="left", padx=6)

    tablo_cerceve = ttk.Frame(app.icerik)
    tablo_cerceve.pack(fill="both", expand=True, pady=(10, 0))
    kolonlar = ("kod", "ad_soyad", "gorev", "sube", "durum", "giris")
    tree = ttk.Treeview(tablo_cerceve, columns=kolonlar, show="headings", height=18)
    for k, b in zip(kolonlar, ("Kod", "Ad Soyad", "Görev", "Şube", "Durum", "Giriş")):
        tree.heading(k, text=b)
        tree.column(k, width=110 if k != "ad_soyad" else 180, anchor="w")
    scroll = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    ozet = ttk.Label(alt, text="")
    ozet.pack(side="left")

    def yenile():
        for i in tree.get_children():
            tree.delete(i)
        d = durum_var.get()
        durum = d.split("|", 1)[0] if d else None
        try:
            satirlar = PersonelService.listele(arama=arama_var.get(), durum=durum or None)
        except Exception as e:
            messagebox.showerror("Personel", str(e), parent=app)
            return
        for s in satirlar:
            tree.insert(
                "", "end", iid=str(s["id"]),
                values=(
                    s["kod"], s["ad_soyad"], s.get("gorev") or "",
                    s.get("sube") or "", s.get("calisma_durumu") or "",
                    s.get("giris_tarihi") or "",
                ),
            )
        ozet.configure(text=f"Toplam: {len(satirlar)}")

    def kart_ac(_e=None):
        sec = tree.selection()
        if not sec:
            return
        from personel_kart_ui import PersonelKartDialog

        PersonelKartDialog(app, personel_id=int(sec[0]))

    ttk.Button(filtre, text="Listele", command=yenile).pack(side="left", padx=8)
    ttk.Button(filtre, text="Yeni Kart", command=lambda: personel_kartlari_goster(app)).pack(
        side="left"
    )
    ttk.Button(filtre, text="Kartı Aç", command=kart_ac).pack(side="left", padx=4)
    tree.bind("<Double-1>", kart_ac)
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: personel_listesi_goster(app))


# --- Özlük -------------------------------------------------------------------

def ozluk_dosyalari_goster(app):
    app._icerigi_temizle()
    _ust(app, "ÖZLÜK DOSYALARI")
    ttk.Label(
        app.icerik,
        text="Belgeleri personel ve kategori bazında yükleyin. Sağlık ve adli sicil ayrı yetki ister. "
        "Yükleme resmî onay anlamına gelmez.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))

    from database.personel_service import PersonelService
    from database.personel_belge_service import PersonelBelgeService

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", pady=(12, 0))
    ttk.Label(ust, text="Personel").pack(side="left")
    personeller = PersonelService.listele(limit=1000)
    pmap = {f"{p['kod']} — {p['ad_soyad']}": p["id"] for p in personeller}
    pvar = tk.StringVar(value=next(iter(pmap), ""))
    ttk.Combobox(ust, textvariable=pvar, values=list(pmap), width=40, state="readonly").pack(
        side="left", padx=6
    )

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, pady=(10, 0))
    sol = ttk.Frame(govde, width=220)
    sol.pack(side="left", fill="y", padx=(0, 8))
    orta = ttk.Frame(govde)
    orta.pack(side="left", fill="both", expand=True)

    kat_list = tk.Listbox(sol, height=16, exportselection=False)
    kat_list.pack(fill="both", expand=True)
    kategoriler = PersonelBelgeService.kategoriler()
    for k in kategoriler:
        etiket = k["ad"] + ("" if k.get("erisim", True) else " (yetki yok)")
        kat_list.insert("end", etiket)

    kolonlar = ("tur", "durum", "gecerlilik", "surum")
    tree = ttk.Treeview(orta, columns=kolonlar, show="headings", height=14)
    for k, b in zip(kolonlar, ("Tür / Belge", "Durum", "Geçerlilik", "Sürüm")):
        tree.heading(k, text=b)
        tree.column(k, width=140 if k != "tur" else 220)
    tree.pack(fill="both", expand=True)

    def yenile(_e=None):
        for i in tree.get_children():
            tree.delete(i)
        pid = pmap.get(pvar.get())
        if not pid:
            return
        try:
            for b in PersonelBelgeService.personel_belgeleri(pid):
                if b.get("erisim_yok"):
                    tree.insert("", "end", values=(b["tur_ad"], "Yetki yok", "", ""))
                else:
                    tree.insert(
                        "", "end", iid=str(b["id"]),
                        values=(
                            b.get("belge_adi") or b["tur_ad"],
                            b["durum"],
                            b.get("gecerlilik_tarihi") or "",
                            b.get("surum_sayisi") or 0,
                        ),
                    )
            eksik = PersonelBelgeService.eksik_listesi(pid)
            for e in eksik:
                tree.insert(
                    "", "end",
                    values=(f"[Eksik] {e['tur_ad']}", e["durum"], "", ""),
                    tags=("eksik",),
                )
            tree.tag_configure("eksik", foreground="#B45309")
        except Exception as exc:
            messagebox.showerror("Özlük", str(exc), parent=app)

    def yukle():
        pid = pmap.get(pvar.get())
        if not pid:
            messagebox.showwarning("Özlük", "Personel seçin.", parent=app)
            return
        ki = kat_list.curselection()
        if not ki:
            messagebox.showwarning("Özlük", "Kategori seçin.", parent=app)
            return
        kat = kategoriler[ki[0]]
        if not kat.get("erisim", True):
            messagebox.showerror("Özlük", "Bu kategori için yetkiniz yok.", parent=app)
            return
        turler = PersonelBelgeService.turler(kat["id"])
        if not turler:
            messagebox.showinfo("Özlük", "Bu kategoride tür yok.", parent=app)
            return
        # Tür seç
        sec = _basit_secim(app, "Belge türü", [f"{t['id']}|{t['ad']}" for t in turler])
        if not sec:
            return
        tur_id = int(sec.split("|", 1)[0])
        yol = filedialog.askopenfilename(
            parent=app,
            filetypes=[
                ("Belgeler", "*.pdf *.jpg *.jpeg *.png *.docx"),
                ("Tümü", "*.*"),
            ],
        )
        if not yol:
            return
        try:
            PersonelBelgeService.yukle(pid, tur_id, yol)
            messagebox.showinfo("Özlük", "Belge arşive kopyalandı.", parent=app)
            yenile()
        except ValueError as e:
            if "hash" in str(e).lower() or "aynı dosya" in str(e).lower():
                if messagebox.askyesno("Özlük", f"{e}\n\nYine de yüklensin mi?", parent=app):
                    try:
                        PersonelBelgeService.yukle(pid, tur_id, yol, hash_uyari_yoksay=True)
                        yenile()
                    except Exception as e2:
                        messagebox.showerror("Özlük", str(e2), parent=app)
            else:
                messagebox.showerror("Özlük", str(e), parent=app)
        except Exception as e:
            messagebox.showerror("Özlük", str(e), parent=app)

    dugme = ttk.Frame(app.icerik)
    dugme.pack(fill="x", pady=8)
    ttk.Button(dugme, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(dugme, text="Dosya Seç / Yükle", command=yukle).pack(side="left", padx=6)
    pvar.trace_add("write", lambda *_: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: ozluk_dosyalari_goster(app))


def _basit_secim(app, baslik, secenekler: list[str]) -> str | None:
    dlg = tk.Toplevel(app)
    dlg.title(baslik)
    dlg.transient(app)
    dlg.grab_set()
    sonuc = {"v": None}
    lb = tk.Listbox(dlg, width=50, height=min(12, len(secenekler)))
    for s in secenekler:
        lb.insert("end", s.split("|", 1)[-1] if "|" in s else s)
    lb.pack(padx=12, pady=12)

    def ok():
        i = lb.curselection()
        if i:
            sonuc["v"] = secenekler[i[0]]
        dlg.destroy()

    ttk.Button(dlg, text="Seç", command=ok).pack(pady=(0, 12))
    lb.bind("<Double-1>", lambda _e: ok())
    dlg.wait_window()
    return sonuc["v"]


# --- Puantaj / İzin ----------------------------------------------------------

def puantaj_izinler_goster(app):
    app._icerigi_temizle()
    _ust(app, "PUANTAJ VE İZİNLER")
    from database.personel_service import PersonelService
    from database.personel_puantaj_service import PersonelIzinService

    personeller = PersonelService.listele(limit=1000)
    pmap = {f"{p['kod']} — {p['ad_soyad']}": p["id"] for p in personeller}
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", pady=(12, 0))
    pvar = tk.StringVar(value=next(iter(pmap), ""))
    ttk.Label(ust, text="Personel").pack(side="left")
    ttk.Combobox(ust, textvariable=pvar, values=list(pmap), width=40, state="readonly").pack(
        side="left", padx=6
    )
    yil_var = tk.IntVar(value=date.today().year)
    ttk.Label(ust, text="Yıl").pack(side="left", padx=(12, 0))
    ttk.Spinbox(ust, from_=2020, to=2040, textvariable=yil_var, width=6).pack(side="left", padx=4)

    ozet_lbl = ttk.Label(app.icerik, text="", justify="left")
    ozet_lbl.pack(anchor="w", pady=(10, 0))

    tree = ttk.Treeview(
        app.icerik, columns=("tur", "durum", "bas", "bit", "gun"), show="headings", height=12
    )
    for k, b in zip(("tur", "durum", "bas", "bit", "gun"), ("Tür", "Durum", "Başlangıç", "Bitiş", "Gün")):
        tree.heading(k, text=b)
        tree.column(k, width=110)
    tree.pack(fill="both", expand=True, pady=(8, 0))

    def yenile():
        for i in tree.get_children():
            tree.delete(i)
        pid = pmap.get(pvar.get())
        if not pid:
            return
        try:
            o = PersonelIzinService.ozet(pid, yil_var.get())
        except Exception as e:
            messagebox.showerror("İzin", str(e), parent=app)
            return
        ozet_lbl.configure(
            text=(
                f"Hak edilen: {o['hak_edilen']}  |  Önceki devir: {o['onceki_devir']}  |  "
                f"Kullanılan: {o['kullanilan']}  |  Kalan: {o['kalan']}\n"
                f"Kural: {o.get('kural_surum') or '—'}  Kaynak: {o.get('kural_kaynak') or '—'}"
            )
        )
        for iz in o["izinler"]:
            tree.insert(
                "", "end", iid=str(iz["id"]),
                values=(iz["izin_turu"], iz["durum"], iz["baslangic"], iz["bitis"], iz["gun"]),
            )

    def izin_ekle():
        pid = pmap.get(pvar.get())
        if not pid:
            return
        dlg = tk.Toplevel(app)
        dlg.title("İzin talebi")
        dlg.transient(app)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=12)
        f.pack(fill="both", expand=True)
        bas = tk.StringVar(value=date.today().isoformat())
        bit = tk.StringVar(value=date.today().isoformat())
        ttk.Label(f, text="Başlangıç (YYYY-AA-GG)").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=bas, width=16).grid(row=0, column=1)
        ttk.Label(f, text="Bitiş").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=bit, width=16).grid(row=1, column=1)

        def kaydet():
            try:
                PersonelIzinService.talep(
                    {"personel_id": pid, "baslangic": bas.get(), "bitis": bit.get()}
                )
                dlg.destroy()
                yenile()
            except Exception as e:
                messagebox.showerror("İzin", str(e), parent=dlg)

        ttk.Button(f, text="Kaydet", command=kaydet).grid(row=2, column=0, columnspan=2, pady=10)

    def onayla():
        sec = tree.selection()
        if not sec:
            return
        try:
            PersonelIzinService.onayla(int(sec[0]))
            PersonelIzinService.kullanima_al(int(sec[0]))
            yenile()
        except Exception as e:
            messagebox.showerror("İzin", str(e), parent=app)

    dug = ttk.Frame(app.icerik)
    dug.pack(fill="x", pady=8)
    ttk.Button(dug, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(dug, text="İzin Talebi", command=izin_ekle).pack(side="left", padx=6)
    ttk.Button(dug, text="Onayla ve Kullanıma Al", command=onayla).pack(side="left")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: puantaj_izinler_goster(app))


# --- Maaş / Avans / Masraf ---------------------------------------------------

def maas_bordro_goster(app):
    app._icerigi_temizle()
    _ust(app, "MAAŞ VE BORDRO TAKİBİ")
    ttk.Label(
        app.icerik,
        text="Onaylı net hakediş takibi. Bu ekran resmî bordro hesabı değildir; "
        "muhasebecinin onaylı tutarlarını izler.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))
    _finans_form(app, mod="hakedis")
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: maas_bordro_goster(app))


def avans_odeme_goster(app):
    app._icerigi_temizle()
    _ust(app, "AVANS VE PERSONEL ÖDEMELERİ")
    ttk.Label(
        app.icerik,
        text="Avans maaş gideri yaratmaz. Maaş ödemesi mevcut kasa/banka belgesine bağlanır.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))
    _finans_form(app, mod="avans")
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: avans_odeme_goster(app))


def masraf_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERSONEL MASRAFLARI")
    ttk.Label(
        app.icerik,
        text="Personelin iş için ödediği gider ve geri ödeme. Geri ödeme ikinci gider/maaş sayılmaz.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))
    _finans_form(app, mod="masraf")
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: masraf_goster(app))


def _finans_form(app, *, mod: str):
    from database.personel_service import PersonelService
    from database.personel_finans_service import PersonelFinansService

    personeller = PersonelService.listele(limit=1000)
    pmap = {f"{p['kod']} — {p['ad_soyad']}": p["id"] for p in personeller}
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", pady=(12, 0))
    pvar = tk.StringVar(value=next(iter(pmap), ""))
    ttk.Combobox(ust, textvariable=pvar, values=list(pmap), width=40, state="readonly").pack(
        side="left"
    )
    ozet = ttk.Label(app.icerik, text="", justify="left")
    ozet.pack(anchor="w", pady=(8, 0))

    tree = ttk.Treeview(
        app.icerik, columns=("tur", "tarih", "tutar", "belge", "iptal"), show="headings", height=10
    )
    for k, b in zip(
        ("tur", "tarih", "tutar", "belge", "iptal"),
        ("Tür", "Tarih", "Tutar", "Belge", "İptal"),
    ):
        tree.heading(k, text=b)
        tree.column(k, width=120)
    tree.pack(fill="both", expand=True, pady=8)

    def yenile():
        for i in tree.get_children():
            tree.delete(i)
        pid = pmap.get(pvar.get())
        if not pid:
            return
        try:
            oz = PersonelFinansService.ay_ozeti(pid)
            if not oz.get("finans_gorur"):
                ozet.configure(text="Finans tutarlarını görme yetkiniz yok.")
                return
            ozet.configure(
                text=(
                    f"Bu ay onaylı net: {oz['onayli_net_hakedis']:,.2f}  |  "
                    f"Mahsup avans: {oz['mahsup_edilecek_avans']:,.2f}  |  "
                    f"Ödenen: {oz['yapilan_maas_odemesi']:,.2f}  |  "
                    f"Kalan: {oz['kalan_odeme']:,.2f}\n"
                    f"Avans bakiyesi: {oz['avans_bakiyesi']:,.2f}  |  "
                    f"Masraf alacağı: {oz['masraf_alacagi']:,.2f}  — {oz.get('aciklama')}"
                )
            )
            for h in PersonelFinansService.hareketler(pid):
                tree.insert(
                    "", "end", iid=str(h["id"]),
                    values=(
                        h["hareket_turu"], h["tarih"], f"{h['tutar']:,.2f}",
                        f"{h.get('belge_turu') or ''} {h.get('belge_no') or ''}".strip(),
                        "Evet" if h["iptal"] else "",
                    ),
                )
        except Exception as e:
            ozet.configure(text=str(e))

    def hakedis_olustur():
        pid = pmap.get(pvar.get())
        if not pid:
            return
        try:
            kart = PersonelService.getir(pid)
            donem = next((d for d in kart["donemler"] if d.get("aktif")), None)
            if not donem:
                raise ValueError("Aktif çalışma dönemi yok.")
            ucret = (donem.get("ucretler") or [{}])[0]
            tutar = ucret.get("tutar")
            if tutar is None:
                raise ValueError("Ücret bilgisi yok veya finans yetkisi yok.")
            bugun = date.today()
            r = PersonelFinansService.hakedis_kaydet(
                {
                    "personel_id": pid,
                    "donem_id": donem["id"],
                    "yil": bugun.year,
                    "ay": bugun.month,
                    "temel_ucret": tutar,
                    "net_hakedis": tutar,
                    "bordro_kaynagi": "Manuel net takip (resmî motor değil)",
                }
            )
            PersonelFinansService.hakedis_onayla(r["id"])
            messagebox.showinfo("Hakediş", f"Onaylı hakediş: {tutar}", parent=app)
            yenile()
        except Exception as e:
            messagebox.showerror("Hakediş", str(e), parent=app)

    def tutar_dialog(baslik, kaydet_fn):
        pid = pmap.get(pvar.get())
        if not pid:
            return
        dlg = tk.Toplevel(app)
        dlg.title(baslik)
        dlg.transient(app)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=12)
        f.pack()
        t = tk.StringVar(value="0")
        belge_tur = tk.StringVar(value="KASA")
        belge_id = tk.StringVar(value="")
        belge_no = tk.StringVar(value="")
        ttk.Label(f, text="Tutar").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=t, width=14).grid(row=0, column=1)
        ttk.Label(f, text="Belge türü").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=belge_tur, width=14).grid(row=1, column=1)
        ttk.Label(f, text="Belge id").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=belge_id, width=14).grid(row=2, column=1)
        ttk.Label(f, text="Belge no").grid(row=3, column=0, sticky="w")
        ttk.Entry(f, textvariable=belge_no, width=14).grid(row=3, column=1)

        def ok():
            try:
                kaydet_fn(pid, t.get(), belge_tur.get(), belge_id.get(), belge_no.get())
                dlg.destroy()
                yenile()
            except Exception as e:
                messagebox.showerror(baslik, str(e), parent=dlg)

        ttk.Button(f, text="Kaydet", command=ok).grid(row=4, column=0, columnspan=2, pady=10)

    dug = ttk.Frame(app.icerik)
    dug.pack(fill="x")
    ttk.Button(dug, text="Yenile", command=yenile).pack(side="left")
    if mod == "hakedis":
        ttk.Button(dug, text="Bu Ay Hakediş Onayla", command=hakedis_olustur).pack(side="left", padx=6)
    if mod == "avans":
        ttk.Button(
            dug, text="Avans",
            command=lambda: tutar_dialog(
                "Avans",
                lambda pid, t, bt, bi, bn: PersonelFinansService.avans_kaydet(
                    {
                        "personel_id": pid, "tutar": t,
                        "belge_turu": bt or None,
                        "belge_id": int(bi) if bi else None,
                        "belge_no": bn or None,
                    }
                ),
            ),
        ).pack(side="left", padx=6)

        def maas_ode():
            pid = pmap.get(pvar.get())
            if not pid:
                return
            oz = PersonelFinansService.ay_ozeti(pid)
            if not oz.get("hakedis_id"):
                messagebox.showwarning("Ödeme", "Önce onaylı hakediş oluşturun.", parent=app)
                return

            def kaydet(pid, t, bt, bi, bn):
                PersonelFinansService.maas_odeme_kaydet(
                    {
                        "personel_id": pid,
                        "hakedis_id": oz["hakedis_id"],
                        "tutar": t,
                        "belge_turu": bt,
                        "belge_id": int(bi),
                        "belge_no": bn or None,
                    }
                )

            tutar_dialog("Maaş ödemesi", kaydet)

        ttk.Button(dug, text="Maaş Ödemesi", command=maas_ode).pack(side="left", padx=6)

        def mahsup():
            pid = pmap.get(pvar.get())
            if not pid:
                return
            oz = PersonelFinansService.ay_ozeti(pid)
            if oz["mahsup_edilecek_avans"] <= 0:
                messagebox.showinfo("Mahsup", "Mahsup edilecek avans yok.", parent=app)
                return
            try:
                PersonelFinansService.avans_mahsup(
                    {
                        "personel_id": pid,
                        "tutar": oz["mahsup_edilecek_avans"],
                        "hakedis_id": oz.get("hakedis_id"),
                    }
                )
                yenile()
            except Exception as e:
                messagebox.showerror("Mahsup", str(e), parent=app)

        ttk.Button(dug, text="Avans Mahsup", command=mahsup).pack(side="left", padx=6)
    if mod == "masraf":
        ttk.Button(
            dug, text="Masraf",
            command=lambda: tutar_dialog(
                "Masraf",
                lambda pid, t, bt, bi, bn: PersonelFinansService.masraf_kaydet(
                    {
                        "personel_id": pid, "tutar": t,
                        "belge_turu": bt or None,
                        "belge_id": int(bi) if bi else None,
                        "belge_no": bn or None,
                    }
                ),
            ),
        ).pack(side="left", padx=6)
        ttk.Button(
            dug, text="Masraf İade",
            command=lambda: tutar_dialog(
                "Masraf iade",
                lambda pid, t, bt, bi, bn: PersonelFinansService.masraf_iade(
                    {
                        "personel_id": pid, "tutar": t,
                        "belge_turu": bt or None,
                        "belge_id": int(bi) if bi else None,
                        "belge_no": bn or None,
                    }
                ),
            ),
        ).pack(side="left", padx=6)
    yenile()


# --- SGK ---------------------------------------------------------------------

def sgk_beyan_goster(app):
    app._icerigi_temizle()
    _ust(app, "SGK VE BEYAN TAKİBİ")
    ttk.Label(
        app.icerik,
        text="Resmî portal entegrasyonu YOKTUR. Taslak dosya ‘beyan verildi’ sayılmaz. "
        "MPHB işyeri+dönem tek ana kayıttır; personeller bağlantı ile eklenir.",
        wraplength=780,
    ).pack(anchor="w", pady=(10, 0))

    from database.personel_sgk_service import PersonelSgkService, son_tarih_hesapla
    from database.models.personel import SGK_ISLEM_TURLERI, SGK_DURUMLARI

    tree = ttk.Treeview(
        app.icerik,
        columns=("tur", "isyeri", "donem", "durum", "son", "onay"),
        show="headings",
        height=14,
    )
    for k, b in zip(
        ("tur", "isyeri", "donem", "durum", "son", "onay"),
        ("İşlem", "İşyeri", "Dönem", "Durum", "Son tarih", "Onay no"),
    ):
        tree.heading(k, text=b)
        tree.column(k, width=120)
    tree.pack(fill="both", expand=True, pady=(10, 0))

    def yenile():
        for i in tree.get_children():
            tree.delete(i)
        try:
            for s in PersonelSgkService.listele():
                donem = (
                    f"{s['donem_yil']}-{s['donem_ay']:02d}"
                    if s.get("donem_yil") and s.get("donem_ay")
                    else ""
                )
                tree.insert(
                    "", "end", iid=str(s["id"]),
                    values=(
                        s["islem_turu"], s.get("isyeri_kodu") or "",
                        donem, s["durum"], s.get("son_tarih") or "",
                        s.get("onay_no") or "",
                    ),
                )
        except Exception as e:
            messagebox.showerror("SGK", str(e), parent=app)

    def yeni_mphb():
        dlg = tk.Toplevel(app)
        dlg.title("MPHB dönem kaydı")
        dlg.transient(app)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=12)
        f.pack()
        isyeri = tk.StringVar(value="MERKEZ")
        yil = tk.IntVar(value=date.today().year)
        ay = tk.IntVar(value=date.today().month)
        ttk.Label(f, text="İşyeri kodu").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=isyeri).grid(row=0, column=1)
        ttk.Label(f, text="Yıl / Ay").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(f, from_=2020, to=2040, textvariable=yil, width=6).grid(row=1, column=1, sticky="w")
        ttk.Spinbox(f, from_=1, to=12, textvariable=ay, width=4).grid(row=1, column=1, sticky="e")

        def kaydet():
            try:
                PersonelSgkService.kaydet(
                    {
                        "islem_turu": "MPHB",
                        "isyeri_kodu": isyeri.get(),
                        "donem_yil": yil.get(),
                        "donem_ay": ay.get(),
                        "nitelik": "ASIL",
                        "durum": "HAZIRLANACAK",
                    }
                )
                dlg.destroy()
                yenile()
            except Exception as e:
                messagebox.showerror("SGK", str(e), parent=dlg)

        ttk.Button(f, text="Oluştur", command=kaydet).grid(row=2, column=0, columnspan=2, pady=10)

    def resmi_onay():
        sec = tree.selection()
        if not sec:
            return
        dlg = tk.Toplevel(app)
        dlg.title("Resmî onay belgesi kaydı")
        dlg.transient(app)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=12)
        f.pack()
        onay = tk.StringVar()
        ttk.Label(f, text="Onay no").grid(row=0, column=0)
        ttk.Entry(f, textvariable=onay, width=24).grid(row=0, column=1)

        def kaydet():
            try:
                PersonelSgkService.durum_guncelle(
                    int(sec[0]),
                    "RESMI_ONAY_BELGESI_KAYDEDILDI",
                    onay_no=onay.get(),
                    onay_tarihi=date.today().isoformat(),
                    islem_turu=tree.item(sec[0])["values"][0],
                )
                dlg.destroy()
                yenile()
            except Exception as e:
                messagebox.showerror("SGK", str(e), parent=dlg)

        ttk.Button(f, text="Kaydet", command=kaydet).grid(row=1, column=0, columnspan=2, pady=10)

    dug = ttk.Frame(app.icerik)
    dug.pack(fill="x", pady=8)
    ttk.Button(dug, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(dug, text="Yeni MPHB", command=yeni_mphb).pack(side="left", padx=6)
    ttk.Button(dug, text="Resmî Onay Belgesi Kaydet", command=resmi_onay).pack(side="left")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: sgk_beyan_goster(app))


# --- Rapor / Form / Ayar -----------------------------------------------------

def raporlar_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERSONEL RAPORLARI")
    from database.personel_service import PersonelService
    from database.personel_belge_service import PersonelBelgeService
    from database.personel_sgk_service import PersonelSgkService

    ttk.Label(
        app.icerik,
        text="Genel raporlar sağlık/adli sicil içeriği taşımaz. PDF/Excel mevcut altyapıyla genişletilebilir.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))

    text = tk.Text(app.icerik, height=22, wrap="word")
    text.pack(fill="both", expand=True, pady=10)

    def doldur():
        text.delete("1.0", "end")
        try:
            satirlar = PersonelService.listele(limit=200)
            text.insert("end", f"=== Personel listesi ({len(satirlar)}) ===\n")
            for s in satirlar:
                text.insert(
                    "end",
                    f"{s['kod']}\t{s['ad_soyad']}\t{s.get('gorev') or ''}\t"
                    f"{s.get('sube') or ''}\t{s['calisma_durumu']}\n",
                )
            text.insert("end", "\n=== Özlük belge eksiği ===\n")
            for s in satirlar:
                eksik = PersonelBelgeService.eksik_listesi(s["id"])
                if eksik:
                    text.insert("end", f"{s['kod']} {s['ad_soyad']}: ")
                    text.insert("end", ", ".join(e["tur_ad"] for e in eksik) + "\n")
            text.insert("end", "\n=== SGK / beyan takvimi ===\n")
            for g in PersonelSgkService.listele():
                text.insert(
                    "end",
                    f"{g['islem_turu']} {g.get('isyeri_kodu') or ''} "
                    f"{g.get('donem_yil') or ''}/{g.get('donem_ay') or ''} "
                    f"durum={g['durum']} son={g.get('son_tarih') or ''} "
                    f"[{g.get('son_tarih_kaynak') or ''}]\n",
                )
        except Exception as e:
            text.insert("end", str(e))

    ttk.Button(app.icerik, text="Raporu Yenile", command=doldur).pack(anchor="w")
    doldur()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: raporlar_goster(app))


def formlar_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERSONEL FORMLARI")
    ttk.Label(
        app.icerik,
        text="Şablonlar: iş sözleşmesi/çalışma koşulu, izin talep, zimmet, hesap dökümü, "
        "ücret hesap pusulası. Elektronik çıktı otomatik imzalı sayılmaz. "
        "SGK/GİB/hekim/adli resmî evraklar iç şablonla taklit edilmez.",
        wraplength=760,
    ).pack(anchor="w", pady=(16, 0))
    for ad in (
        "İş sözleşmesi / çalışma koşulu (şablon)",
        "İzin talep ve kayıt belgesi",
        "Zimmet / teslim tutanağı",
        "Personel hesap dökümü",
        "Ücret hesap pusulası (net takip)",
    ):
        ttk.Button(
            app.icerik, text=ad, style="AltMenu.TButton",
            command=lambda a=ad: messagebox.showinfo(
                "Form",
                f"‘{a}’ şablonu sonraki sürümde PDF/Word üretecek. "
                "İmzalı tarama özlük arşivine yüklenebilir.",
                parent=app,
            ),
        ).pack(fill="x", pady=4, padx=(0, 200))
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: formlar_goster(app))


def ayarlar_goster(app):
    app._icerigi_temizle()
    _ust(app, "PERSONEL AYARLARI")
    from database.database import get_session
    from database.models.personel import PersonelMevzuatParametre, PersonelBelgeTuru
    from database.personel_sema import schema_hazirla
    from sqlalchemy import select

    schema_hazirla()
    ttk.Label(
        app.icerik,
        text="Yetki, belge kuralları ve yürürlük tarihli mevzuat parametreleri. "
        "Süre/oranlar kaynak göstermeden sabitlenmez. Hassas erişim ayrı izin ister.",
        wraplength=760,
    ).pack(anchor="w", pady=(10, 0))

    text = tk.Text(app.icerik, height=20, wrap="word")
    text.pack(fill="both", expand=True, pady=10)
    with get_session() as session:
        text.insert("end", "=== Mevzuat parametreleri ===\n")
        for p in session.scalars(select(PersonelMevzuatParametre).order_by(PersonelMevzuatParametre.kod)):
            text.insert(
                "end",
                f"{p.kod} v{p.surum} | {p.kapsam} | kaynak: {p.resmi_kaynak} | "
                f"kontrol: {p.kontrol_tarihi} | yürürlük: {p.yururluk_baslangic}\n"
                f"  {p.deger_json}\n",
            )
        text.insert("end", "\n=== Belge türleri ===\n")
        for t in session.scalars(select(PersonelBelgeTuru).order_by(PersonelBelgeTuru.kod)):
            text.insert(
                "end",
                f"{t.kod}: {t.ad} [{t.sinif}] gizlilik={t.gizlilik} "
                f"koşul={t.uygulanma_kosulu or '—'} dayanak={t.hukuki_dayanak or '—'}\n",
            )
    text.configure(state="disabled")
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: ayarlar_goster(app))


# Sol menü alt kısayolları (ana_panel alt_menu_ac)
def personel_kartlari_ac(app):
    personel_menusu_goster(app)
    personel_kartlari_goster(app)


def personel_listesi_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: personel_listesi_goster(app))


def ozluk_dosyalari_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: ozluk_dosyalari_goster(app))


def puantaj_izinler_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: puantaj_izinler_goster(app))


def maas_bordro_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: maas_bordro_goster(app))


def avans_odeme_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: avans_odeme_goster(app))


def personel_masraf_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: masraf_goster(app))


def sgk_beyan_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: sgk_beyan_goster(app))


def personel_rapor_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: raporlar_goster(app))


def personel_form_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: formlar_goster(app))


def personel_ayar_ac(app):
    app.sayfa_goster("personel", ust_duzey=True)
    app.nav_ac(lambda: ayarlar_goster(app))
