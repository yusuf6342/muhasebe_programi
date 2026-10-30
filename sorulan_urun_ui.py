"""Sorulan Ürünler — liste + hızlı kayıt (sprint 1 iskelet)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from database.models.sorulan_urun import ARAMA_SONUCLARI, NIYETLER, TALEP_NEDENLERI
from database.sorulan_urun_service import SorulanUrunService
from fatura_tema import ACIK_BG, stil_uygula, tk_buton
from ui_pencere import calisma_alani, is_alanina_sigdir


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
    tk_buton(ust, "Yenile", lambda: sorulan_urunler_goster(app), rol="ara").pack(side="right")
    tk_buton(ust, "Ayarlar", lambda: _sorulan_ayarlar(app), rol="ikincil").pack(side="right", padx=4)

    ttk.Label(
        app.icerik,
        text="Müşteri talebi kaydı stok/fatura hareketi oluşturmaz. Amaç tedarik önceliğidir.",
        foreground="#64748B",
    ).pack(anchor="w", padx=16)

    arama_fr = ttk.Frame(app.icerik)
    arama_fr.pack(fill="x", padx=16, pady=8)
    ttk.Label(arama_fr, text="Ara").pack(side="left")
    arama_var = tk.StringVar()
    ttk.Entry(arama_fr, textvariable=arama_var, width=32).pack(side="left", padx=8)
    ttk.Label(arama_fr, text="Dönem").pack(side="left", padx=(12, 0))
    donem_var = tk.StringVar(value="30")
    ttk.Combobox(
        arama_fr,
        textvariable=donem_var,
        values=("30", "60", "90", "TUM"),
        width=6,
        state="readonly",
    ).pack(side="left", padx=4)

    paned = ttk.Panedwindow(app.icerik, orient="vertical")
    paned.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    ust_p = ttk.Frame(paned)
    alt_p = ttk.Frame(paned)
    paned.add(ust_p, weight=2)
    paned.add(alt_p, weight=1)

    cols = (
        "urun",
        "neden",
        "son",
        "adet",
        "musteri",
        "anonim",
        "tedarik",
        "sorumlu",
    )
    tablo = ttk.Treeview(ust_p, columns=cols, show="headings", height=12)
    for c, b, w in (
        ("urun", "Ürün", 220),
        ("neden", "Neden", 100),
        ("son", "Son sorulma", 100),
        ("adet", "Soru", 50),
        ("musteri", "Müşteri", 70),
        ("anonim", "Anonim", 60),
        ("tedarik", "Tedarik", 100),
        ("sorumlu", "Sorumlu", 90),
    ):
        tablo.heading(c, text=b)
        tablo.column(c, width=w, anchor="w")
    tablo.pack(side="left", fill="both", expand=True)
    sb = ttk.Scrollbar(ust_p, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")

    ttk.Label(alt_p, text="Seçilen ürün — müşteri talepleri", font=("Segoe UI", 10, "bold")).pack(
        anchor="w"
    )
    tcols = ("tarih", "musteri", "tel", "miktar", "kalan", "niyet", "durum")
    talep_tablo = ttk.Treeview(alt_p, columns=tcols, show="headings", height=8)
    for c, b, w in (
        ("tarih", "Tarih", 90),
        ("musteri", "Müşteri", 140),
        ("tel", "Telefon", 100),
        ("miktar", "Miktar", 70),
        ("kalan", "Kalan", 70),
        ("niyet", "Niyet", 110),
        ("durum", "Durum", 90),
    ):
        talep_tablo.heading(c, text=b)
        talep_tablo.column(c, width=w, anchor="w")
    talep_tablo.pack(fill="both", expand=True, pady=4)

    def _doldur():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in SorulanUrunService.urun_ozet_listesi(arama=arama_var.get()):
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["urun_adi"],
                    r["talep_nedeni"],
                    r["son_sorulma"],
                    r["sorulma_sayisi"],
                    r["farkli_musteri"],
                    r["anonim"],
                    r["tedarik_durumu"],
                    r["sorumlu"],
                ),
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
            talep_tablo.insert(
                "",
                "end",
                iid=str(t["id"]),
                values=(
                    t["tarih"],
                    t["musteri"],
                    t["telefon"],
                    t["miktar"],
                    t["kalan"],
                    t["niyet"],
                    t["durum"],
                ),
            )

    def _arama_sonucu():
        sec_t = talep_tablo.selection()
        if not sec_t:
            messagebox.showinfo("Arama sonucu", "Alt listeden bir müşteri talebi seçin.", parent=app)
            return
        talep_id = int(sec_t[0])
        dlg = tk.Toplevel(app)
        dlg.title("Arama sonucu kaydet")
        dlg.transient(app)
        dlg.grab_set()
        fr = ttk.Frame(dlg, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(
            fr,
            text="Otomatik SMS/WhatsApp yok. Sonuç yalnızca personel kaydıdır; satış doğmaz.",
            wraplength=360,
        ).pack(anchor="w")
        ttk.Label(fr, text="Sonuç *").pack(anchor="w", pady=(10, 0))
        sonuc_cb = ttk.Combobox(fr, values=list(ARAMA_SONUCLARI), state="readonly", width=28)
        sonuc_cb.set("ULASILDI")
        sonuc_cb.pack(anchor="w")
        ttk.Label(fr, text="Sonraki arama (GG.AA.YYYY, isteğe bağlı)").pack(anchor="w", pady=(8, 0))
        tarih_e = ttk.Entry(fr, width=16)
        tarih_e.pack(anchor="w")
        ttk.Label(fr, text="Not").pack(anchor="w", pady=(8, 0))
        not_e = ttk.Entry(fr, width=40)
        not_e.pack(anchor="w")

        def _ok():
            from datetime import date as _date

            sonraki = None
            raw = tarih_e.get().strip()
            if raw:
                try:
                    from fatura_belge_aktarim.normalize import tarih_tr

                    sonraki = tarih_tr(raw)
                except Exception:
                    messagebox.showerror("Tarih", "Geçerli tarih girin (GG.AA.YYYY).", parent=dlg)
                    return
            try:
                SorulanUrunService.arama_sonucu_kaydet(
                    talep_id,
                    sonuc_kod=sonuc_cb.get(),
                    sonraki_arama=sonraki,
                    notlar=not_e.get().strip() or None,
                )
            except Exception as exc:
                messagebox.showerror("Arama sonucu", str(exc), parent=dlg)
                return
            dlg.destroy()
            _talep_yukle()
            _doldur()

        tk_buton(fr, "Kaydet", _ok, rol="kaydet").pack(anchor="e", pady=12)
        tk_buton(fr, "Vazgeç", dlg.destroy, rol="ikincil").pack(anchor="e")

    def _oncelik():
        try:
            gun = 30 if donem_var.get() == "TUM" else int(donem_var.get())
        except ValueError:
            gun = 30
        try:
            from database.session_manager import oturum

            # Ayar eşiği (varsayılan 3) — kullanıcı tercihi JSON
            min_m = 3
            try:
                from pathlib import Path
                import json
                from database.database import DB_DIR

                yol = Path(DB_DIR) / "kullanici_tercihleri" / f"sorulan_u{int(oturum.user_id or 0)}.json"
                if yol.is_file():
                    min_m = int(json.loads(yol.read_text(encoding="utf-8")).get("min_musteri", 3))
            except Exception:
                pass
            satirlar = SorulanUrunService.oncelik_raporu(gun=gun if donem_var.get() != "TUM" else 3650, min_musteri=min_m)
        except Exception as exc:
            messagebox.showerror("Rapor", str(exc), parent=app)
            return
        if not satirlar:
            messagebox.showinfo(
                "Öncelik",
                f"Son {donem_var.get()} günde eşik (≥{min_m} bilinen müşteri) aşılmadı.",
                parent=app,
            )
            return
        metin = "\n".join(
            f"• {s['urun_adi']} — {s['farkli_musteri']} müşteri, {s['sorulma']} soru"
            for s in satirlar[:40]
        )
        messagebox.showinfo("Tedarik önceliği", metin, parent=app)

    def _satin_alma_aktar():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Aktarım", "Önce ürün seçin.", parent=app)
            return
        aday_id = int(sec[0])
        aday = SorulanUrunService.aday_getir(aday_id)
        if not aday:
            messagebox.showerror("Aktarım", "Kayıt bulunamadı.", parent=app)
            return
        dlg = tk.Toplevel(app)
        dlg.title("Satınalma taslağına aktar")
        dlg.transient(app)
        dlg.grab_set()
        fr = ttk.Frame(dlg, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(
            fr,
            text=(
                f"Ürün: {aday['urun_adi']}\n"
                "Miktarı siz seçin — müşteri talebi toplamı otomatik alınmaz.\n"
                "Taslak oluşur; onay ve sipariş mevcut satınalma kurallarındadır."
            ),
            justify="left",
        ).pack(anchor="w")
        ttk.Label(fr, text="Alım miktarı *").pack(anchor="w", pady=(10, 0))
        mik = ttk.Entry(fr, width=16)
        mik.pack(anchor="w")
        mik.focus_set()

        def _ok():
            try:
                sonuc = SorulanUrunService.satin_alma_taslagina_aktar(
                    [aday_id], miktarlar={aday_id: mik.get()}
                )
            except Exception as exc:
                messagebox.showerror("Aktarım", str(exc), parent=dlg)
                return
            dlg.destroy()
            messagebox.showinfo(
                "Aktarım",
                f"Satınalma talebi taslağı oluşturuldu (id={sonuc['talep_id']}).\n"
                "Otomatik sipariş / e-posta gönderilmedi.",
                parent=app,
            )
            _doldur()

        tk_buton(fr, "Taslak oluştur", _ok, rol="kaydet").pack(anchor="e", pady=12)
        tk_buton(fr, "Vazgeç", dlg.destroy, rol="ikincil").pack(anchor="e")

    def _stok_kontrol():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Stok kontrol", "Önce ürün seçin.", parent=app)
            return
        aday_id = int(sec[0])
        aday = SorulanUrunService.aday_getir(aday_id)
        if not aday:
            messagebox.showerror("Stok kontrol", "Kayıt bulunamadı.", parent=app)
            return
        try:
            kwargs = {"aday_id": aday_id}
            if aday.get("stok_id"):
                kwargs["stok_id"] = int(aday["stok_id"])
            sonuc = SorulanUrunService.stok_geldiginde_degerlendir(**kwargs)
        except Exception as exc:
            messagebox.showerror("Stok kontrol", str(exc), parent=app)
            return
        messagebox.showinfo(
            "Stok kontrol",
            (
                f"Kullanılabilir: {sonuc.get('mevcut_miktar', '?')}\n"
                f"Oluşturulan görev: {sonuc.get('olusturulan', 0)}\n"
                f"Güncellenen: {sonuc.get('guncellenen', 0)}\n"
                f"Atlanan: {sonuc.get('atlanan', 0)}"
                + (
                    f"\n({sonuc.get('neden')})"
                    if sonuc.get("neden")
                    else ""
                )
            ),
            parent=app,
        )
        _doldur()
        _talep_yukle()

    tablo.bind("<<TreeviewSelect>>", _talep_yukle)
    tk_buton(arama_fr, "Listele", _doldur, rol="ara").pack(side="left")
    def _donusum():
        try:
            r = SorulanUrunService.donusum_raporu(gun=30)
            messagebox.showinfo(
                "Dönüşüm (30 gün)",
                f"Satışa dönüşen talep: {r['pay']}\n"
                f"Geçerli talep (payda): {r['payda']}\n"
                f"Oran: {r['etiket']}\n"
                f"Anonim: {r['anonim']} | Bilinen: {r['bilinen']}\n"
                "(Kısmi satışlar payda dahildir.)",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Dönüşüm", str(exc), parent=app)

    tk_buton(arama_fr, "Öncelik raporu", _oncelik, rol="ara").pack(side="left", padx=4)
    tk_buton(arama_fr, "Dönüşüm raporu", _donusum, rol="ara").pack(side="left", padx=4)
    tk_buton(arama_fr, "Satınalmaya aktar…", _satin_alma_aktar, rol="yeni").pack(side="left", padx=4)
    tk_buton(arama_fr, "Stok durumunu kontrol et", _stok_kontrol, rol="ara").pack(
        side="left", padx=4
    )
    tk_buton(arama_fr, "Arama sonucu…", _arama_sonucu, rol="yeni").pack(side="left", padx=4)
    _doldur()


def _sorulan_ayarlar(app) -> None:
    """Eşik ve süre — kullanıcı tercihi (firma değil)."""
    import json
    from pathlib import Path

    from database.database import DB_DIR
    from database.session_manager import oturum

    uid = int(oturum.user_id or 0)
    yol = Path(DB_DIR) / "kullanici_tercihleri" / f"sorulan_u{uid}.json"
    veri = {"min_musteri": 3, "gun": 30}
    try:
        if yol.is_file():
            veri.update(json.loads(yol.read_text(encoding="utf-8")))
    except Exception:
        pass
    win = tk.Toplevel(app)
    win.title("Sorulan Ürünler — Ayarlar")
    win.transient(app)
    win.grab_set()
    fr = ttk.Frame(win, padding=12)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Öncelik eşiği: bilinen farklı müşteri (anonim sayılmaz)").pack(anchor="w")
    m_var = tk.StringVar(value=str(veri.get("min_musteri", 3)))
    ttk.Entry(fr, textvariable=m_var, width=8).pack(anchor="w", pady=4)
    ttk.Label(fr, text="Varsayılan dönem (gün)").pack(anchor="w")
    g_var = tk.StringVar(value=str(veri.get("gun", 30)))
    ttk.Entry(fr, textvariable=g_var, width=8).pack(anchor="w", pady=4)

    def _kaydet():
        try:
            veri["min_musteri"] = max(1, int(m_var.get()))
            veri["gun"] = max(1, int(g_var.get()))
        except ValueError:
            messagebox.showerror("Ayarlar", "Sayı girin.", parent=win)
            return
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        win.destroy()

    tk_buton(fr, "Kaydet", _kaydet, rol="kaydet").pack(anchor="e", pady=12)


def sorulan_urun_hizli_kayit(parent, *, urun_adi: str = "", cari_id=None, musteri_adi: str = "", stok_id=None, birim: str = "", kaynak: str = "LISTE") -> None:
    """Hızlı kayıt diyaloğu — ilk odak ürün adı."""
    win = tk.Toplevel(parent)
    win.title("Sorulan Ürün Ekle")
    win.transient(parent)
    win.grab_set()
    try:
        ax, ay, aw, ah = calisma_alani(win)
        is_alanina_sigdir(win, 480, 360, ax, ay, aw, ah)
    except Exception:
        win.geometry("480x360")

    fr = ttk.Frame(win, padding=12)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Ürün adı *").grid(row=0, column=0, sticky="e", pady=4)
    urun = ttk.Entry(fr, width=40)
    urun.grid(row=0, column=1, sticky="ew", pady=4)
    if urun_adi:
        urun.insert(0, urun_adi)

    ttk.Label(fr, text="Talep nedeni *").grid(row=1, column=0, sticky="e", pady=4)
    neden = ttk.Combobox(fr, values=list(TALEP_NEDENLERI), state="readonly", width=37)
    neden.set("CESITTE_YOK")
    neden.grid(row=1, column=1, sticky="w", pady=4)

    ttk.Label(fr, text="Niyet").grid(row=2, column=0, sticky="e", pady=4)
    niyet = ttk.Combobox(fr, values=list(NIYETLER), state="readonly", width=37)
    niyet.set("SADECE_SORDU")
    niyet.grid(row=2, column=1, sticky="w", pady=4)

    ttk.Label(fr, text="Müşteri").grid(row=3, column=0, sticky="e", pady=4)
    musteri = ttk.Entry(fr, width=40)
    musteri.grid(row=3, column=1, sticky="ew", pady=4)
    if musteri_adi:
        musteri.insert(0, musteri_adi)

    ttk.Label(fr, text="Telefon").grid(row=4, column=0, sticky="e", pady=4)
    tel = ttk.Entry(fr, width=40)
    tel.grid(row=4, column=1, sticky="ew", pady=4)

    ttk.Label(fr, text="Miktar").grid(row=5, column=0, sticky="e", pady=4)
    miktar = ttk.Entry(fr, width=16)
    miktar.grid(row=5, column=1, sticky="w", pady=4)

    ttk.Label(fr, text="Birim").grid(row=6, column=0, sticky="e", pady=4)
    birim_e = ttk.Entry(fr, width=16)
    birim_e.grid(row=6, column=1, sticky="w", pady=4)
    if birim:
        birim_e.insert(0, birim)

    kaydediliyor = {"v": False}

    def _kaydet(yeni: bool = False):
        if kaydediliyor["v"]:
            return
        kaydediliyor["v"] = True
        try:
            SorulanUrunService.hizli_kaydet(
                {
                    "urun_adi": urun.get(),
                    "talep_nedeni": neden.get(),
                    "niyet": niyet.get(),
                    "musteri_adi": musteri.get(),
                    "telefon": tel.get(),
                    "miktar": miktar.get().strip() or None,
                    "birim": birim_e.get().strip() or None,
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
            miktar.delete(0, "end")
            kaydediliyor["v"] = False
            urun.focus_set()
            return
        win.destroy()

    alt = ttk.Frame(fr)
    alt.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(16, 0))
    tk_buton(alt, "Kaydet ve Yeni", lambda: _kaydet(True), rol="yeni").pack(side="right", padx=4)
    tk_buton(alt, "Kaydet", lambda: _kaydet(False), rol="kaydet").pack(side="right")
    tk_buton(alt, "Vazgeç", win.destroy, rol="ikincil").pack(side="left")
    fr.columnconfigure(1, weight=1)
    win.after_idle(urun.focus_set)
