"""Toplu Stok Grubu Eşleştirme — filtre, çoklu seçim, ön izleme, uygula, geri al."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

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
    hub_ust_baslik(
        kok,
        baslik="TOPLU STOK GRUBU EŞLEŞTİRME",
        alt_baslik="Bul → Seç → Hedef grup → Ön izle → Uygula",
        app=app,
        geri_komut=lambda: app.sayfa_goster("stoklar"),
        geri_metin="← Stoklar",
    )

    # Sayaçlar
    sayac_fr = tk.Frame(kok, bg=ACIK_BG)
    sayac_fr.pack(fill="x", padx=16, pady=(4, 0))
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
    govde.pack(fill="both", expand=True, padx=16, pady=8)
    govde.columnconfigure(0, weight=3)
    govde.columnconfigure(1, weight=2)
    govde.rowconfigure(0, weight=1)

    # —— Sol: filtre + liste ——
    sol = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    filtre = tk.Frame(sol, bg=BEYAZ)
    filtre.pack(fill="x", padx=8, pady=8)
    tk.Label(filtre, text="Ara (kod/ad/barkod)", bg=BEYAZ, fg=IKINCIL).grid(row=0, column=0, sticky="w")
    arama = ttk.Entry(filtre, width=22)
    arama.grid(row=1, column=0, padx=(0, 6), sticky="ew")
    tk.Label(filtre, text="Ad kelime 1/2/3 (OR)", bg=BEYAZ, fg=IKINCIL).grid(
        row=0, column=1, columnspan=3, sticky="w"
    )
    ad1 = ttk.Entry(filtre, width=12)
    ad2 = ttk.Entry(filtre, width=12)
    ad3 = ttk.Entry(filtre, width=12)
    ad1.grid(row=1, column=1, padx=2)
    ad2.grid(row=1, column=2, padx=2)
    ad3.grid(row=1, column=3, padx=2)

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
    tk_buton(btn_f, "Filtreyi Temizle", lambda: _filtre_temizle(), rol="ikincil").pack(
        side="left", padx=6
    )
    tk_buton(btn_f, "Yalnız Grupsuz", lambda: _yalniz_grupsuz(), rol="yeni").pack(side="left")

    sec_fr = tk.Frame(sol, bg=BEYAZ)
    sec_fr.pack(fill="x", padx=8, pady=(0, 4))
    tk_buton(sec_fr, "Sayfadakileri Seç", lambda: _sayfa_sec(), rol="ikincil").pack(side="left")
    tk_buton(sec_fr, "Tüm Filtre Sonucunu Seç", lambda: _tumunu_sec(), rol="kaydet").pack(
        side="left", padx=6
    )
    tk_buton(sec_fr, "Seçimi Temizle", lambda: _secim_temizle(), rol="ikincil").pack(side="left")
    sadece_secili = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        sec_fr, text="Yalnız seçili ürünler", variable=sadece_secili, command=lambda: _listele()
    ).pack(side="right")

    tablo_fr = tk.Frame(sol, bg=BEYAZ)
    tablo_fr.pack(fill="both", expand=True, padx=8, pady=(0, 8))
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
    tablo.pack(side="left", fill="both", expand=True)
    sy.pack(side="right", fill="y")

    sayfa_fr = tk.Frame(sol, bg=BEYAZ)
    sayfa_fr.pack(fill="x", padx=8, pady=(0, 8))
    sayfa_lbl = tk.Label(sayfa_fr, text="Sayfa 1", bg=BEYAZ, fg=IKINCIL)
    sayfa_lbl.pack(side="left")
    tk_buton(sayfa_fr, "◀", lambda: _sayfa(-1), rol="ikincil").pack(side="left", padx=4)
    tk_buton(sayfa_fr, "▶", lambda: _sayfa(1), rol="ikincil").pack(side="left")

    # —— Sağ: hedef + özet + geçmiş ——
    sag = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sag.grid(row=0, column=1, sticky="nsew")

    tk.Label(
        sag, text="Hedef Grup", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", app)
    ).pack(anchor="w", padx=12, pady=(10, 4))
    h_ana = ttk.Combobox(sag, width=36)
    h_tali = ttk.Combobox(sag, width=36, state="disabled")
    h_alt = ttk.Combobox(sag, width=36, state="disabled")
    for lbl, w in (("Ana Grup *", h_ana), ("Tali Grup", h_tali), ("Alt Grup", h_alt)):
        tk.Label(sag, text=lbl, bg=BEYAZ, fg=IKINCIL).pack(anchor="w", padx=12)
        w.pack(anchor="w", padx=12, pady=(0, 6))
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
    politika = tk.StringVar(value=POLITIKA_SADECE_GRUPSUZ)
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

    tk.Label(
        sag, text="Son Toplu İşlemler", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", app)
    ).pack(anchor="w", padx=12)
    gecmis = ttk.Treeview(
        sag, columns=("no", "tarih", "adet", "durum"), show="headings", height=6
    )
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
    alt.pack(side="bottom", fill="x")
    alt_ic = tk.Frame(alt, bg=BEYAZ)
    alt_ic.pack(fill="x", padx=12, pady=10)
    tk_buton(alt_ic, "Kapat", lambda: app.sayfa_goster("stoklar"), rol="ikincil").pack(
        side="right"
    )
    uygula_btn = tk_buton(
        alt_ic, "Grupla Eşleştir", lambda: _uygula(), rol="kaydet"
    )
    uygula_btn.pack(side="right", padx=(0, 8))
    tk_buton(alt_ic, "Ön İzle", lambda: _onizle(), rol="ara").pack(side="right", padx=(0, 8))
    tk_buton(alt_ic, "Seçimi Temizle", lambda: _secim_temizle(), rol="ikincil").pack(
        side="left"
    )

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
        state["son_onizleme"] = None

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
        state["son_onizleme"] = None

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
        state["son_onizleme"] = None

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
            if sadece_secili.get() and state["secili"]:
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

    def _toggle_secim(_event=None):
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
        state["son_onizleme"] = None
        sayaclar["Seçili Ürün"].configure(text=str(len(state["secili"])))

    def _sayfa_sec():
        for iid, sid in state["satir_map"].items():
            vals = list(tablo.item(iid, "values"))
            if vals[9] == "Pasif":
                continue  # varsayılan: pasif seçme
            state["secili"].add(sid)
            vals[0] = "☑"
            tablo.item(iid, values=vals)
        state["son_onizleme"] = None
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
        state["son_onizleme"] = None
        _listele()

    def _secim_temizle():
        state["secili"].clear()
        state["son_onizleme"] = None
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
        return (
            state["h_ana_map"].get(h_ana.get()),
            state["h_tali_map"].get(h_tali.get()),
            state["h_alt_map"].get(h_alt.get()),
        )

    def _onizle():
        if not state["secili"]:
            messagebox.showwarning("Ön izleme", "Önce stok seçin.", parent=app)
            return
        ana, tali, alt = _hedef_idler()
        if not ana:
            messagebox.showwarning("Hedef", "En az Ana Grup seçin.", parent=app)
            return
        try:
            oniz = StokGrupTopluService.onizle(
                sorted(state["secili"]),
                ana_id=ana,
                tali_id=tali,
                alt_id=alt,
                politika=politika.get(),
            )
        except Exception as exc:
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
        # Ön izleme penceresi
        win = tk.Toplevel(app)
        win.title("Ön İzleme — Toplu Grup Eşleştirme")
        win.geometry("900x520")
        win.transient(app)
        fr = ttk.Frame(win, padding=8)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=ozet_lbl.cget("text")).pack(anchor="w")
        tv = ttk.Treeview(
            fr,
            columns=("kod", "ad", "eski", "yeni", "durum", "acik"),
            show="headings",
            height=18,
        )
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
        tv.pack(fill="both", expand=True, pady=6)
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
            state["son_onizleme"] = None
            sayaclar["Seçili Ürün"].configure(text=str(len(state["secili"])))
            messagebox.showinfo(
                "Seçim",
                "Seçimden çıkarıldı. Kaydetmeden önce Ön İzle'yi yeniden çalıştırın.",
                parent=win,
            )

        altb = ttk.Frame(fr)
        altb.pack(fill="x")
        ttk.Button(altb, text="Seçimden Çıkar", command=cikar).pack(side="left")
        ttk.Button(altb, text="Kapat", command=win.destroy).pack(side="right")

    def _uygula():
        if state["busy"]:
            return
        if not state["son_onizleme"]:
            messagebox.showwarning(
                "Ön izleme zorunlu",
                "Grupla Eşleştirmeden önce Ön İzle yapın.",
                parent=app,
            )
            return
        oniz = state["son_onizleme"]
        gunc = oniz["ozet"]["guncellenecek"]
        if gunc <= 0:
            messagebox.showinfo("Eşleştirme", "Güncellenecek stok yok.", parent=app)
            return
        if politika.get() == POLITIKA_DEGISTIR:
            if not messagebox.askyesno(
                "Mevcut gruplar değişecek",
                f"{gunc} stokun mevcut grubu değiştirilecek.\n"
                f"Hedef: {oniz['hedef_yol']}\n\nEmin misiniz?",
                parent=app,
            ):
                return
        onay = tk.Toplevel(app)
        onay.title("Son Onay")
        onay.transient(app)
        onay.grab_set()
        ttk.Label(
            onay,
            text=(
                f"Hedef grup:\n{oniz['hedef_yol']}\n\n"
                f"Değişecek stok sayısı: {gunc}\n\n"
                "İşlemi uygulamak istiyor musunuz?"
            ),
            justify="left",
            padding=16,
        ).pack()
        sonuc_kutusu = {"ok": False}

        def iptal():
            onay.destroy()

        def uygula_ok():
            sonuc_kutusu["ok"] = True
            onay.destroy()

        bf = ttk.Frame(onay, padding=8)
        bf.pack(fill="x")
        ttk.Button(bf, text="Vazgeç", command=iptal).pack(side="right")
        ttk.Button(bf, text="İşlemi Uygula", command=uygula_ok).pack(side="right", padx=8)
        app.wait_window(onay)
        if not sonuc_kutusu["ok"]:
            return

        state["busy"] = True
        try:
            uygula_btn.configure(state="disabled")
        except Exception:
            pass
        ana, tali, alt = _hedef_idler()
        try:
            sonuc = StokGrupTopluService.uygula(
                sorted(state["secili"]),
                ana_id=ana,
                tali_id=tali,
                alt_id=alt,
                politika=politika.get(),
                onizleme_ozeti=oniz["ozet"],
            )
            messagebox.showinfo(
                "Tamamlandı",
                f"İşlem: {sonuc['islem_no']}\n"
                f"Güncellenen: {sonuc['guncellenen']}\n"
                f"Hedef: {sonuc['hedef_yol']}",
                parent=app,
            )
            state["secili"].clear()
            state["son_onizleme"] = None
            _listele()
            _gecmis_yenile()
        except Exception as exc:
            messagebox.showerror("Eşleştirme", str(exc), parent=app)
        finally:
            state["busy"] = False
            try:
                uygula_btn.configure(state="normal")
            except Exception:
                pass

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
    politika.trace_add("write", lambda *_a: state.__setitem__("son_onizleme", None))

    _yukle_hedef_ana()
    _yukle_filtre_ana()
    _listele()
    _gecmis_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stok_grup_toplu_eslestirme_goster(app))
