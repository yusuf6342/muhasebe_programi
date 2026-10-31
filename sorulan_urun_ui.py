"""Sorulan Ürünler — liste, hızlı kayıt, fotoğraf ve tarih odaklı takip."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from database.database import DB_DIR
from database.models.sorulan_urun import (
    FOTOGRAF_ETIKETLERI,
    MUADIL_ETIKET,
    MUADIL_SECENEKLERI,
    NIYET_ETIKET,
    NIYETLER,
    TALEP_NEDENI_ETIKET,
    TALEP_NEDENLERI,
)
from database.sorulan_urun_service import (
    SorulanUrunService,
    bugun_tr,
    etiket_neden,
    etiket_niyet,
    tarih_goster,
)
from database.session_manager import oturum
from fatura_tema import ACIK_BG, stil_uygula, tk_buton
from ui_pencere import calisma_alani, is_alanina_sigdir
from ui_takvim import takvim_entry_bagla


def sorulan_urunler_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("satislar")
        try:
            kabuk._alt_oge_isaretle("sorulan_urunler")
        except Exception:
            pass
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    SorulanUrunService.ensure_schema()

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(ust, text="SORULAN ÜRÜNLER", font=("Segoe UI", 16, "bold")).pack(side="left")
    tk_buton(ust, "Yeni Kayıt", lambda: sorulan_urun_hizli_kayit(app), rol="yeni").pack(
        side="right", padx=4
    )
    tk_buton(ust, "Yenile", lambda: _yenile(), rol="ara").pack(side="right")
    tk_buton(ust, "Ayarlar", lambda: _sorulan_ayarlar(app), rol="ikincil").pack(side="right", padx=4)

    ttk.Label(
        app.icerik,
        text="Müşteri talebi stok/cari/fatura hareketi oluşturmaz. Sorulduğu tarih raporların temelidir.",
        foreground="#64748B",
    ).pack(anchor="w", padx=16)

    arama_fr = ttk.Frame(app.icerik)
    arama_fr.pack(fill="x", padx=16, pady=8)
    ttk.Label(arama_fr, text="Ara").pack(side="left")
    arama_var = tk.StringVar()
    ttk.Entry(arama_fr, textvariable=arama_var, width=28).pack(side="left", padx=8)
    ttk.Label(arama_fr, text="Sorulma dönemi").pack(side="left", padx=(12, 0))
    donem_var = tk.StringVar(value="30")
    donem_cb = ttk.Combobox(
        arama_fr,
        textvariable=donem_var,
        values=("BUGUN", "7", "30", "90", "BU_AY", "TUM", "OZEL"),
        width=10,
        state="readonly",
    )
    donem_cb.pack(side="left", padx=4)
    ttk.Label(arama_fr, text="Baş").pack(side="left")
    bas_e = ttk.Entry(arama_fr, width=11)
    bas_e.pack(side="left", padx=2)
    takvim_entry_bagla(bas_e)
    ttk.Label(arama_fr, text="Bit").pack(side="left")
    bit_e = ttk.Entry(arama_fr, width=11)
    bit_e.pack(side="left", padx=2)
    takvim_entry_bagla(bit_e)

    btn_fr = ttk.Frame(app.icerik)
    btn_fr.pack(fill="x", padx=16, pady=(0, 6))
    tk_buton(btn_fr, "Öncelik raporu", lambda: _oncelik(app, donem_var), rol="ara").pack(
        side="left", padx=2
    )
    tk_buton(btn_fr, "Açık / geciken", lambda: _acik_geciken(app), rol="ara").pack(
        side="left", padx=2
    )
    tk_buton(btn_fr, "Dönüşüm (30g)", lambda: _donusum(app), rol="ara").pack(side="left", padx=2)

    paned = ttk.Panedwindow(app.icerik, orient="vertical")
    paned.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    ust_p = ttk.Frame(paned)
    alt_p = ttk.Frame(paned)
    paned.add(ust_p, weight=2)
    paned.add(alt_p, weight=1)

    cols = (
        "urun",
        "tarif",
        "ilk",
        "son",
        "bagimsiz",
        "toplam",
        "musteri",
        "bekleme",
        "tanim",
        "tedarik",
        "sorumlu",
    )
    tablo = ttk.Treeview(ust_p, columns=cols, show="headings", height=12)
    for c, b, w in (
        ("urun", "Ürün / geçici ad", 180),
        ("tarif", "Tarif", 140),
        ("ilk", "İlk sorulma", 90),
        ("son", "Son sorulma", 90),
        ("bagimsiz", "Bağ. talep", 70),
        ("toplam", "Toplam soru", 80),
        ("musteri", "Müşteri", 60),
        ("bekleme", "Max bekleme", 80),
        ("tanim", "Tanım", 100),
        ("tedarik", "Tedarik", 90),
        ("sorumlu", "Sorumlu", 80),
    ):
        tablo.heading(c, text=b)
        tablo.column(c, width=w, anchor="w")
    tablo.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(ust_p, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")

    alt_bar = ttk.Frame(alt_p)
    alt_bar.pack(fill="x")
    ttk.Label(alt_bar, text="Müşteri talepleri", font=("Segoe UI", 10, "bold")).pack(
        side="left"
    )
    tk_buton(alt_bar, "Tekrar soruldu", lambda: _tekrar(app, talep_tablo, _talep_yukle), rol="yeni").pack(
        side="right", padx=2
    )
    tk_buton(alt_bar, "Olay geçmişi", lambda: _olay(app, talep_tablo), rol="ara").pack(
        side="right", padx=2
    )

    tcols = (
        "tarih",
        "tekrar",
        "bekleme",
        "musteri",
        "tel",
        "miktar",
        "ihtiyac",
        "niyet",
        "durum",
        "sorumlu",
    )
    talep_tablo = ttk.Treeview(alt_p, columns=tcols, show="headings", height=8)
    for c, b, w in (
        ("tarih", "Sorulduğu tarih", 100),
        ("tekrar", "Son tekrar", 90),
        ("bekleme", "Bekleme g.", 70),
        ("musteri", "Müşteri", 120),
        ("tel", "Telefon", 90),
        ("miktar", "Miktar", 60),
        ("ihtiyac", "İhtiyaç", 90),
        ("niyet", "Niyet", 100),
        ("durum", "Durum", 110),
        ("sorumlu", "Sorumlu", 80),
    ):
        talep_tablo.heading(c, text=b)
        talep_tablo.column(c, width=w, anchor="w")
    talep_tablo.pack(fill="both", expand=True, pady=4)
    ozet_lbl = ttk.Label(alt_p, text="", foreground="#64748B")
    ozet_lbl.pack(anchor="w")

    def _yenile(_e=None):
        for i in tablo.get_children():
            tablo.delete(i)
        bas, bit = SorulanUrunService.donem_filtre_coz(
            donem_var.get(), bas_e.get(), bit_e.get()
        )
        bilinmeyen_toplam = 0
        for r in SorulanUrunService.urun_ozet_listesi(
            arama=arama_var.get(), tarih_bas=bas, tarih_bit=bit
        ):
            bilinmeyen_toplam += int(r.get("bilinmeyen_tarih") or 0)
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["urun_adi"],
                    r.get("tarif") or "",
                    r.get("ilk_sorulma") or "",
                    r.get("son_sorulma") or "",
                    r.get("bagimsiz_talep"),
                    r.get("toplam_sorulma"),
                    r["farkli_musteri"],
                    r.get("max_bekleme") if r.get("max_bekleme") is not None else "—",
                    r.get("tanim_durumu") or "",
                    r["tedarik_durumu"],
                    r["sorumlu"],
                ),
            )
        ozet_lbl.configure(
            text=(
                f"Filtre: sorulma tarihi · bilinmeyen tarihli kayıt: {bilinmeyen_toplam} "
                "(dönem toplamlarına dahil edilmez)"
            )
        )

    def _talep_yukle(_e=None):
        for i in talep_tablo.get_children():
            talep_tablo.delete(i)
        sec = tablo.selection()
        if not sec:
            return
        for t in SorulanUrunService.talepler(int(sec[0])):
            if t.get("gecersiz"):
                continue
            bg = t.get("bekleme_gun")
            talep_tablo.insert(
                "",
                "end",
                iid=str(t["id"]),
                values=(
                    t["tarih"],
                    t.get("son_tekrar") or "",
                    "—" if bg is None else bg,
                    t["musteri"],
                    t["telefon"],
                    t["miktar"],
                    t.get("ihtiyac_tarihi") or "",
                    t.get("niyet_etiket") or etiket_niyet(t.get("niyet") or ""),
                    t.get("durum_etiket") or t.get("durum") or "",
                    t.get("sorumlu") or "",
                ),
            )

    tablo.bind("<<TreeviewSelect>>", _talep_yukle)
    tablo.bind("<Double-1>", lambda _e: _detay_ac(app, tablo))
    arama_var.trace_add("write", lambda *_a: _yenile())
    donem_cb.bind("<<ComboboxSelected>>", lambda _e: _yenile())
    _yenile()

    # Yerel yenile referansı (üst düğme)
    sorulan_urunler_goster._yenile = _yenile  # type: ignore[attr-defined]


def _detay_ac(app, tablo):
    sec = tablo.selection()
    if not sec:
        return
    aday = SorulanUrunService.aday_getir(int(sec[0]))
    if not aday:
        return
    sorulan_urun_hizli_kayit(app, urun_adi=aday.get("urun_adi") or "", kaynak="LISTE_DETAY")


def _tekrar(app, talep_tablo, yenile_fn):
    sec = talep_tablo.selection()
    if not sec:
        messagebox.showinfo("Tekrar", "Listeden bir talep seçin.", parent=app)
        return
    try:
        SorulanUrunService.tekrar_soruldu(int(sec[0]), notlar="Tekrar soruldu")
        messagebox.showinfo(
            "Tekrar",
            "Tekrar sorulma eklendi. Bağımsız talep sayısı artmadı.",
            parent=app,
        )
        yenile_fn()
    except Exception as exc:
        messagebox.showerror("Tekrar", str(exc), parent=app)


def _olay(app, talep_tablo):
    sec = talep_tablo.selection()
    if not sec:
        messagebox.showinfo("Geçmiş", "Talep seçin.", parent=app)
        return
    olaylar = SorulanUrunService.olay_gecmisi(int(sec[0]))
    metin = "\n".join(f"{o['tarih']}: {o['aciklama']}" for o in olaylar) or "Kayıt yok."
    messagebox.showinfo("Olay geçmişi", metin, parent=app)


def _oncelik(app, donem_var):
    gun = 30
    try:
        if donem_var.get() not in ("TUM", "OZEL", "BUGUN", "BU_AY"):
            gun = int(donem_var.get())
    except ValueError:
        gun = 30
    satirlar = SorulanUrunService.oncelik_raporu(gun=gun if donem_var.get() != "TUM" else 3650)
    if not satirlar:
        messagebox.showinfo("Öncelik", "Eşik üstü ürün yok.", parent=app)
        return
    metin = "\n".join(
        f"{s['urun_adi']}: {s['farkli_musteri']} müşteri, {s['sorulma']} sorulma"
        for s in satirlar[:30]
    )
    messagebox.showinfo("Ürün öncelik (sorulma tarihi)", metin, parent=app)


def _acik_geciken(app):
    satirlar = SorulanUrunService.acik_geciken(min_bekleme=0)
    if not satirlar:
        messagebox.showinfo("Açık talepler", "Açık talep yok.", parent=app)
        return
    metin = "\n".join(
        f"{s['urun']} | {s['musteri']} | sorulma {s['sorulma']} | {s['bekleme_gun']}g | {s['durum']}"
        for s in satirlar[:40]
    )
    messagebox.showinfo("Açık / geciken (ilk sorulmadan)", metin, parent=app)


def _donusum(app):
    r = SorulanUrunService.donusum_raporu(gun=30)
    messagebox.showinfo(
        "Dönüşüm (sorulma tarihi, 30g)",
        f"Bağımsız talepler: {r['payda']}\nKarşılanan: {r['pay']}\nOran: {r['etiket']}\n"
        f"Anonim: {r['anonim']} (ayrı)\nTekrar sorulmalar paydada yeni talep sayılmaz.",
        parent=app,
    )


def _sorulan_ayarlar(app) -> None:
    win = tk.Toplevel(app)
    win.title("Sorulan Ürünler — Ayarlar")
    win.transient(app)
    win.grab_set()
    uid = int(getattr(oturum, "user_id", 0) or 0)
    yol = Path(DB_DIR) / "kullanici_tercihleri" / f"sorulan_u{uid}.json"
    veri = {"min_musteri": 3, "gun": 30}
    if yol.is_file():
        try:
            veri.update(json.loads(yol.read_text(encoding="utf-8")))
        except Exception:
            pass
    fr = ttk.Frame(win, padding=12)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Öncelik: min. farklı müşteri").grid(row=0, column=0, sticky="w")
    min_e = ttk.Entry(fr, width=8)
    min_e.insert(0, str(veri.get("min_musteri", 3)))
    min_e.grid(row=0, column=1, sticky="w")
    ttk.Label(fr, text="Öncelik gün").grid(row=1, column=0, sticky="w")
    gun_e = ttk.Entry(fr, width=8)
    gun_e.insert(0, str(veri.get("gun", 30)))
    gun_e.grid(row=1, column=1, sticky="w")

    def _kaydet():
        try:
            veri["min_musteri"] = int(min_e.get())
            veri["gun"] = int(gun_e.get())
        except ValueError:
            messagebox.showerror("Ayarlar", "Sayı girin.", parent=win)
            return
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        win.destroy()

    tk_buton(fr, "Kaydet", _kaydet, rol="kaydet").grid(row=2, column=1, sticky="e", pady=12)


def sorulan_urun_hizli_kayit(
    parent,
    *,
    urun_adi: str = "",
    cari_id=None,
    musteri_adi: str = "",
    stok_id=None,
    birim: str = "",
    kaynak: str = "LISTE",
) -> None:
    """Büyütülebilir hızlı kayıt: solda tanım+talep, sağda fotoğraf."""
    win = tk.Toplevel(parent)
    win.title("Sorulan Ürün — Hızlı Kayıt")
    win.transient(parent)
    win.grab_set()
    try:
        ax, ay, aw, ah = calisma_alani(win)
        is_alanina_sigdir(win, min(980, aw - 40), min(640, ah - 40), ax, ay, aw, ah)
    except Exception:
        win.geometry("960x620")
    win.minsize(720, 480)

    govde = ttk.Frame(win, padding=10)
    govde.pack(fill="both", expand=True)
    govde.columnconfigure(0, weight=3)
    govde.columnconfigure(1, weight=2)
    govde.rowconfigure(0, weight=1)

    sol = ttk.Frame(govde)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    sag = ttk.LabelFrame(govde, text="Fotoğraflar", padding=6)
    sag.grid(row=0, column=1, sticky="nsew")

    # ── Sol: tanım + talep ──
    ttk.Label(sol, text="Ürün adı / müşterinin tarifi", font=("Segoe UI", 9, "bold")).grid(
        row=0, column=0, sticky="w", pady=(0, 2)
    )
    urun = ttk.Entry(sol)
    urun.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
    if urun_adi:
        urun.insert(0, urun_adi)

    ttk.Label(sol, text="Müşterinin kendi sözleriyle tarif").grid(row=2, column=0, sticky="w")
    tarif = tk.Text(sol, height=3, wrap="word", font=("Segoe UI", 9))
    tarif.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)

    ttk.Label(sol, text="Ürün grubu").grid(row=4, column=0, sticky="w")
    grup = ttk.Combobox(
        sol,
        values=("Mobilya parçası", "Mekanizma", "Aksesuar", "Diğer / Bilinmiyor"),
        width=28,
    )
    grup.set("Diğer / Bilinmiyor")
    grup.grid(row=4, column=1, sticky="w", pady=2)

    ttk.Label(sol, text="Marka / Model").grid(row=5, column=0, sticky="w")
    marka_fr = ttk.Frame(sol)
    marka_fr.grid(row=5, column=1, sticky="ew", pady=2)
    marka = ttk.Entry(marka_fr, width=14)
    marka.pack(side="left")
    model = ttk.Entry(marka_fr, width=14)
    model.pack(side="left", padx=4)

    ttk.Label(sol, text="Kullanım amacı").grid(row=6, column=0, sticky="nw")
    kullanim = tk.Text(sol, height=2, wrap="word", font=("Segoe UI", 9))
    kullanim.grid(row=6, column=1, sticky="ew", pady=2)

    # Talep bloğu
    ttk.Separator(sol).grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)
    ttk.Label(sol, text="Müşteri talebi", font=("Segoe UI", 10, "bold")).grid(
        row=8, column=0, sticky="w"
    )

    ttk.Label(sol, text="Sorulduğu tarih *").grid(row=9, column=0, sticky="w")
    tarih_fr = ttk.Frame(sol)
    tarih_fr.grid(row=9, column=1, sticky="w", pady=2)
    tarih_e = ttk.Entry(tarih_fr, width=12)
    tarih_e.insert(0, tarih_goster(bugun_tr()))
    tarih_e.pack(side="left")
    takvim_entry_bagla(tarih_e)
    ttk.Label(tarih_fr, text="Saat").pack(side="left", padx=(8, 2))
    saat_e = ttk.Entry(tarih_fr, width=6)
    saat_e.pack(side="left")
    ttk.Label(tarih_fr, text="(opsiyonel)").pack(side="left", padx=2)

    ttk.Label(sol, text="Talep nedeni").grid(row=10, column=0, sticky="w")
    neden = ttk.Combobox(
        sol,
        values=[TALEP_NEDENI_ETIKET[k] for k in TALEP_NEDENLERI],
        state="readonly",
        width=28,
    )
    neden.set(TALEP_NEDENI_ETIKET["CESITTE_YOK"])
    neden.grid(row=10, column=1, sticky="w", pady=2)

    ttk.Label(sol, text="Niyet").grid(row=11, column=0, sticky="w")
    niyet = ttk.Combobox(
        sol, values=[NIYET_ETIKET[k] for k in NIYETLER], state="readonly", width=28
    )
    niyet.set(NIYET_ETIKET["SADECE_SORDU"])
    niyet.grid(row=11, column=1, sticky="w", pady=2)

    ttk.Label(sol, text="Müşteri (boş = anonim)").grid(row=12, column=0, sticky="w")
    musteri = ttk.Entry(sol)
    musteri.grid(row=12, column=1, sticky="ew", pady=2)
    if musteri_adi:
        musteri.insert(0, musteri_adi)

    ttk.Label(sol, text="Telefon").grid(row=13, column=0, sticky="w")
    tel = ttk.Entry(sol)
    tel.grid(row=13, column=1, sticky="ew", pady=2)

    ttk.Label(sol, text="Miktar / Birim").grid(row=14, column=0, sticky="w")
    mb = ttk.Frame(sol)
    mb.grid(row=14, column=1, sticky="w", pady=2)
    miktar = ttk.Entry(mb, width=10)
    miktar.pack(side="left")
    birim_e = ttk.Entry(mb, width=10)
    birim_e.pack(side="left", padx=4)
    if birim:
        birim_e.insert(0, birim)

    ttk.Label(sol, text="Muadil").grid(row=15, column=0, sticky="w")
    muadil = ttk.Combobox(
        sol,
        values=[MUADIL_ETIKET[k] for k in MUADIL_SECENEKLERI],
        state="readonly",
        width=28,
    )
    muadil.set(MUADIL_ETIKET["SORULMADI"])
    muadil.grid(row=15, column=1, sticky="w", pady=2)

    ttk.Label(sol, text="İhtiyaç tarihi").grid(row=16, column=0, sticky="w")
    ihtiyac = ttk.Entry(sol, width=12)
    ihtiyac.grid(row=16, column=1, sticky="w", pady=2)
    takvim_entry_bagla(ihtiyac)

    ttk.Label(sol, text="Sorumlu / Sonraki takip").grid(row=17, column=0, sticky="w")
    sr = ttk.Frame(sol)
    sr.grid(row=17, column=1, sticky="ew", pady=2)
    sorumlu = ttk.Entry(sr, width=14)
    sorumlu.pack(side="left")
    takip = ttk.Entry(sr, width=12)
    takip.pack(side="left", padx=4)
    takvim_entry_bagla(takip)

    ttk.Label(sol, text="Talep açıklaması").grid(row=18, column=0, sticky="nw")
    talep_ack = tk.Text(sol, height=2, wrap="word", font=("Segoe UI", 9))
    talep_ack.grid(row=18, column=1, sticky="ew", pady=2)

    sol.columnconfigure(1, weight=1)

    # ── Sağ: fotoğraflar ──
    fotograflar: list[str] = []
    liste = tk.Listbox(sag, height=12)
    liste.pack(fill="both", expand=True)

    def _foto_ekle():
        yollar = filedialog.askopenfilenames(
            parent=win,
            title="Fotoğraf / ek seç",
            filetypes=[
                ("Görseller", "*.jpg;*.jpeg;*.png;*.gif;*.webp"),
                ("PDF", "*.pdf"),
                ("Tümü", "*.*"),
            ],
        )
        for y in yollar:
            fotograflar.append(y)
            liste.insert("end", Path(y).name)

    def _yapistir(_e=None):
        try:
            from PIL import ImageGrab

            img = ImageGrab.grabclipboard()
            if img is None:
                return
            tmp = Path(DB_DIR) / "tmp_clipboard"
            tmp.mkdir(parents=True, exist_ok=True)
            yol = tmp / f"pano_{len(fotograflar)}.png"
            img.save(yol)
            fotograflar.append(str(yol))
            liste.insert("end", yol.name)
        except Exception as exc:
            messagebox.showwarning("Pano", f"Yapıştırılamadı:\n{exc}", parent=win)

    bf = ttk.Frame(sag)
    bf.pack(fill="x", pady=4)
    ttk.Button(bf, text="Dosyadan ekle", command=_foto_ekle).pack(side="left", padx=2)
    ttk.Button(bf, text="Panodan yapıştır", command=_yapistir).pack(side="left", padx=2)
    win.bind("<Control-v>", _yapistir)

    # Alt düğmeler — her zaman görünür
    alt = ttk.Frame(win, padding=(10, 0, 10, 10))
    alt.pack(fill="x", side="bottom")
    kaydediliyor = {"v": False}

    def _neden_kod():
        et = neden.get()
        for k, v in TALEP_NEDENI_ETIKET.items():
            if v == et:
                return k
        return "CESITTE_YOK"

    def _niyet_kod():
        et = niyet.get()
        for k, v in NIYET_ETIKET.items():
            if v == et:
                return k
        return "SADECE_SORDU"

    def _muadil_kod():
        et = muadil.get()
        for k, v in MUADIL_ETIKET.items():
            if v == et:
                return k
        return "SORULMADI"

    def _kaydet(yeni: bool = False):
        if kaydediliyor["v"]:
            return
        kaydediliyor["v"] = True
        try:
            SorulanUrunService.hizli_kaydet(
                {
                    "urun_adi": urun.get(),
                    "musteri_tarifi": tarif.get("1.0", "end-1c").strip(),
                    "urun_grubu": grup.get(),
                    "marka": marka.get().strip() or None,
                    "model": model.get().strip() or None,
                    "kullanim_amaci": kullanim.get("1.0", "end-1c").strip() or None,
                    "talep_nedeni": _neden_kod(),
                    "niyet": _niyet_kod(),
                    "musteri_adi": musteri.get(),
                    "telefon": tel.get(),
                    "miktar": miktar.get().strip() or None,
                    "birim": birim_e.get().strip() or None,
                    "talep_tarihi": tarih_e.get().strip(),
                    "sorulma_saati": saat_e.get().strip() or None,
                    "talep_aciklama": talep_ack.get("1.0", "end-1c").strip() or None,
                    "ihtiyac_tarihi": ihtiyac.get().strip() or None,
                    "muadil": _muadil_kod(),
                    "sorumlu_personel": sorumlu.get().strip() or None,
                    "sonraki_takip": takip.get().strip() or None,
                    "fotograf_yollari": list(fotograflar),
                    "cari_id": cari_id,
                    "stok_id": stok_id,
                    "kaynak": kaynak,
                }
            )
        except Exception as exc:
            messagebox.showerror("Sorulan Ürün", str(exc), parent=win)
            kaydediliyor["v"] = False
            return
        if yeni:
            urun.delete(0, "end")
            tarif.delete("1.0", "end")
            miktar.delete(0, "end")
            fotograflar.clear()
            liste.delete(0, "end")
            tarih_e.delete(0, "end")
            tarih_e.insert(0, tarih_goster(bugun_tr()))
            kaydediliyor["v"] = False
            urun.focus_set()
            return
        win.destroy()
        try:
            if hasattr(sorulan_urunler_goster, "_yenile"):
                sorulan_urunler_goster._yenile()  # type: ignore[attr-defined]
        except Exception:
            pass

    tk_buton(alt, "Kaydet ve Yeni", lambda: _kaydet(True), rol="yeni").pack(side="right", padx=4)
    tk_buton(alt, "Kaydet", lambda: _kaydet(False), rol="kaydet").pack(side="right")
    tk_buton(alt, "Vazgeç", win.destroy, rol="ikincil").pack(side="left")
    win.after_idle(urun.focus_set)
