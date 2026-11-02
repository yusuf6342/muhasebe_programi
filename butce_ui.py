"""BÜTÇE menüsü — plan, gerçekleşen (Ön/GM/Yan yana), nakit, Excel, raporlar.

Bütçe planını açmak / kaydetmek fatura, fiş veya stok hareketi oluşturmaz.
Ön Muhasebe ile Genel Muhasebe toplanmaz.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from database.butce_service import (
    ButceAyarService,
    ButceService,
    GIRIS_DAGITIM,
    GIRIS_MANUEL,
    KAYNAK_GENEL_MUHASEBE,
    KAYNAK_ON_MUHASEBE,
    KAYNAK_YAN_YANA,
    ay_adi,
    dagit_yillik_esit,
    parse_tr_tutar,
)
from database.models.butce import (
    DURUM_ARSIV,
    DURUM_INCELEMEDE,
    DURUM_KILITLI,
    DURUM_ONAYLI,
    DURUM_TASLAK,
    OLCU_GIDER,
    OLCU_NAKIT,
    OLCU_SATIS,
    OLCU_TURLERI,
    SENARYO_IYIMSER,
    SENARYO_TEMKINLI,
    SENARYO_TEMEL,
    SENARYOLAR,
)

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


def _sari_dugme(parent, text, command):
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=SARI,
        fg=KOYU_LACIVERT,
        activebackground=SARI,
        relief="flat",
        padx=16,
        pady=6,
        font=FONT_UI_BOLD,
        cursor="hand2",
    )


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
            "Firma satış / gider / nakit planı; Ön Muhasebe veya Genel Muhasebe ile karşılaştırma. "
            "Bütçe açmak fatura veya fiş oluşturmaz. Kaynaklar toplanmaz."
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
            ("NAKİT BÜTÇESİ", lambda: butce_nakit_goster(app)),
            ("RAPORLAR / EXCEL", lambda: butce_raporlar_goster(app)),
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
    butce_nakit_goster(app)


def butce_raporlar_ac(app):
    _alt_isaretle(app, "butce_raporlar_ac")
    butce_raporlar_goster(app)


def butce_ayarlar_ac(app):
    _alt_isaretle(app, "butce_ayarlar_ac")
    butce_ayarlar_goster(app)


# Geriye uyumluluk (eski stub adları)
def butce_nakit_stub(app):
    butce_nakit_goster(app)


def butce_raporlar_stub(app):
    butce_raporlar_goster(app)


# --------------------------------------------------------------------------- ekranlar


def butce_yeni_goster(app, plan_id: int | None = None):
    """Yeni bütçe veya kayıtlı planı düzenle — yalnız plan tutarları; gerçekleşen değiştirilmez."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)

    plan = ButceService.plan_getir(plan_id) if plan_id else None
    duzenleme = plan is not None
    kayitli_yil = int(plan["mali_yil"]) if plan else None
    kayitli_pb = (plan["para_birimi"] if plan else "TRY") or "TRY"

    izin_ok, izin_neden = (True, "")
    if plan:
        izin_ok, izin_neden = ButceService.plan_duzenlenebilir(plan["id"])

    # Aylık plan belleği: None = eksik, Decimal = girilmiş (0 dahil)
    # Çoklu ölçü: her (ölçü, kategori) için ayrı tampon — geçişte kayıp yok
    aylik_plan: list[Decimal | None] = [None] * 12
    aylik_kaynak: list[str | None] = [None] * 12
    kirli = {"v": False}
    olcu_tampon: dict[tuple[str, str], dict] = {}
    aktif_olcu_anahtar: dict[str, tuple[str, str] | None] = {"k": None}
    giris_modu = tk.StringVar(value="manuel" if duzenleme else "yillik")
    olcu_ozet_lbl = tk.StringVar(value="")

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(
        ust,
        text=("BÜTÇEYİ DÜZENLE" if duzenleme else "YENİ BÜTÇE"),
        style="Baslik.TLabel",
    ).pack(side="left")
    ttk.Button(ust, text="← Liste", command=lambda: _vazgec_git(lambda: butce_liste_goster(app))).pack(
        side="right"
    )
    ttk.Button(ust, text="← Bütçe", command=lambda: _vazgec_git(lambda: butce_menusu_goster(app))).pack(
        side="right", padx=4
    )

    if plan and not izin_ok:
        ttk.Label(app.icerik, text=izin_neden, foreground="#B91C1C").pack(anchor="w", pady=(8, 0))

    # Kaydırılabilir gövde + sabit alt çubuk (Kaydet görev çubuğunun arkasında kalmasın)
    govde_dis = ttk.Frame(app.icerik)
    govde_dis.pack(fill="both", expand=True, pady=(8, 0))
    canvas = tk.Canvas(govde_dis, bg=ACIK_BG, highlightthickness=0)
    sb = ttk.Scrollbar(govde_dis, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    govde = ttk.Frame(canvas)
    win_id = canvas.create_window((0, 0), window=govde, anchor="nw")

    def _scroll_cfg(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _canvas_genislik(e):
        canvas.itemconfigure(win_id, width=e.width)

    govde.bind("<Configure>", _scroll_cfg)
    canvas.bind("<Configure>", _canvas_genislik)

    form = ttk.Frame(govde)
    form.pack(fill="x", padx=4)
    ad_var = tk.StringVar(value=(plan["ad"] if plan else ""))
    yil_var = tk.StringVar(value=str(plan["mali_yil"] if plan else _mali_yil_varsayilan()))
    pb_var = tk.StringVar(value=kayitli_pb)
    proje_var = tk.StringVar(value=(plan.get("proje_kodu") or "") if plan else "")
    senaryo_var = tk.StringVar(value=(plan.get("senaryo") or SENARYO_TEMEL) if plan else SENARYO_TEMEL)
    olcu_var = tk.StringVar(value=OLCU_SATIS)
    kat_var = tk.StringVar(value="GENEL")
    yillik_var = tk.StringVar(value="")
    yillik_toplam_lbl = tk.StringVar(value="Yıllık toplam: —")
    durum_lbl = tk.StringVar(value="")
    eksik_lbl = tk.StringVar(value="")

    def _form_satir(r, etiket, widget):
        ttk.Label(form, text=etiket).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    form.columnconfigure(1, weight=1, minsize=280)
    _form_satir(0, "Ad *", ttk.Entry(form, textvariable=ad_var, width=40))
    yil_entry = ttk.Entry(form, textvariable=yil_var, width=12)
    pb_entry = ttk.Entry(form, textvariable=pb_var, width=8)
    _form_satir(1, "Mali yıl *", yil_entry)
    _form_satir(2, "Para birimi", pb_entry)
    _form_satir(3, "Proje kodu", ttk.Entry(form, textvariable=proje_var, width=16))
    _form_satir(
        4,
        "Senaryo",
        ttk.Combobox(
            form, textvariable=senaryo_var, values=list(SENARYOLAR), width=14, state="readonly"
        ),
    )
    if plan:
        ttk.Label(form, text="Kod / durum").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Label(
            form,
            text=f"{plan['kod']} | {plan['durum']} | s{plan.get('surum')}",
            foreground=LACIVERT,
        ).grid(row=5, column=1, sticky="w")
        if duzenleme:
            # Yıl / PB değişince sessiz taşıma yok — salt okunur
            yil_entry.configure(state="readonly")
            pb_entry.configure(state="readonly")
            ttk.Label(
                form,
                text="Mali yıl ve para birimi kayıtlı planda değiştirilemez (otomatik kur yok).",
                foreground=PASIF,
            ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 4))

    ttk.Separator(govde).pack(fill="x", pady=12)
    ttk.Label(govde, text="Plan tutarları (gerçekleşen buradan değişmez)", style="Baslik.TLabel").pack(
        anchor="w", padx=4
    )

    yontem = ttk.LabelFrame(govde, text="Giriş yöntemi", padding=8)
    yontem.pack(fill="x", padx=4, pady=(8, 0))
    ttk.Radiobutton(
        yontem,
        text="Yıllık tutardan aylara dağıt",
        value="yillik",
        variable=giris_modu,
        command=lambda: _modu_uygula(),
    ).pack(anchor="w")
    ttk.Radiobutton(
        yontem,
        text="Aylık tutarları manuel gir",
        value="manuel",
        variable=giris_modu,
        command=lambda: _modu_uygula(),
    ).pack(anchor="w")

    dag = ttk.Frame(govde)
    dag.pack(fill="x", padx=4, pady=(8, 0))
    ttk.Label(dag, text="Ölçü").pack(side="left")
    olcu_cb = ttk.Combobox(
        dag, textvariable=olcu_var, values=list(OLCU_TURLERI), width=12, state="readonly"
    )
    olcu_cb.pack(side="left", padx=8)
    ttk.Label(dag, text="Kategori").pack(side="left", padx=(12, 0))
    kat_entry = ttk.Entry(dag, textvariable=kat_var, width=16)
    kat_entry.pack(side="left", padx=8)
    ttk.Label(
        govde,
        textvariable=olcu_ozet_lbl,
        foreground=PASIF,
    ).pack(anchor="w", padx=4, pady=(4, 0))
    ttk.Label(dag, text="Yıllık tutar").pack(side="left", padx=(12, 0))
    yillik_entry = ttk.Entry(dag, textvariable=yillik_var, width=16)
    yillik_entry.pack(side="left", padx=8)

    tablo_fr = ttk.Frame(govde)
    tablo_fr.pack(fill="both", expand=True, padx=4, pady=(10, 0))
    onizleme = ttk.Treeview(
        tablo_fr,
        columns=("ay", "tutar", "durum", "kaynak"),
        show="headings",
        height=12,
        selectmode="browse",
    )
    onizleme.heading("ay", text="Ay")
    onizleme.heading("tutar", text="Plan tutarı")
    onizleme.heading("durum", text="Durum")
    onizleme.heading("kaynak", text="Giriş")
    onizleme.column("ay", width=110, anchor="w")
    onizleme.column("tutar", width=140, anchor="e")
    onizleme.column("durum", width=90, anchor="center")
    onizleme.column("kaynak", width=90, anchor="center")
    onizleme.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(tablo_fr, orient="vertical", command=onizleme.yview).pack(side="right", fill="y")
    onizleme.configure(yscrollcommand=lambda *a: None)

    ttk.Label(govde, textvariable=eksik_lbl, foreground="#B45309").pack(anchor="w", padx=4, pady=(4, 0))
    ttk.Label(
        govde,
        text="Hücre: çift tık veya F2 · Enter uygular · Esc iptal · Tab sonraki ay. Kaydet ayrı işlemdir.",
        foreground=PASIF,
    ).pack(anchor="w", padx=4)

    def _kirli_yap():
        kirli["v"] = True
        durum_lbl.set("● Kaydedilmemiş değişiklikler var")

    def _kirli_temizle():
        kirli["v"] = False
        durum_lbl.set("Kaydedildi" if plan else "")

    def _yillik_toplam_guncelle():
        dolu = [t for t in aylik_plan if t is not None]
        if not dolu and all(t is None for t in aylik_plan):
            yillik_toplam_lbl.set("Yıllık toplam: — (ay girilmedi)")
        else:
            top = sum((t for t in dolu), Decimal("0"))
            yillik_toplam_lbl.set(f"Yıllık toplam: {_para(top)} {pb_var.get() or 'TRY'}")
        eksik = [ay_adi(i + 1) for i, t in enumerate(aylik_plan) if t is None]
        if eksik:
            eksik_lbl.set(
                f"Eksik aylar ({len(eksik)}): {', '.join(eksik)} — taslak olarak kaydedilebilir."
            )
        else:
            eksik_lbl.set("12 ayın tümü dolu.")

    def _tablo_yenile():
        onizleme.delete(*onizleme.get_children())
        for i in range(12):
            t = aylik_plan[i]
            if t is None:
                durum, tutar_g = "Eksik", "—"
            elif t == 0:
                durum, tutar_g = "Sıfır", _para(t)
            else:
                durum, tutar_g = "Dolu", _para(t)
            kg = aylik_kaynak[i] or ""
            onizleme.insert(
                "",
                "end",
                iid=str(i + 1),
                values=(ay_adi(i + 1), tutar_g, durum, kg),
            )
        _yillik_toplam_guncelle()

    def _modu_uygula():
        manuel = giris_modu.get() == "manuel"
        # Manuelde yıllık alan salt okunur (aylardan türetilir)
        try:
            yillik_entry.configure(state=("readonly" if manuel else "normal"))
        except tk.TclError:
            pass
        if manuel:
            dolu = [t for t in aylik_plan if t is not None]
            if dolu:
                yillik_var.set(_para(sum(dolu, Decimal("0"))))
            else:
                yillik_var.set("")
        _tablo_yenile()

    def _olcu_anahtar() -> tuple[str, str]:
        return (olcu_var.get(), kat_var.get().strip() or "GENEL")

    def _tampona_yaz() -> None:
        k = aktif_olcu_anahtar["k"]
        if k is None:
            return
        olcu_tampon[k] = {
            "plan": list(aylik_plan),
            "kaynak": list(aylik_kaynak),
            "modu": giris_modu.get(),
            "kirli": bool(kirli["v"]),
        }

    def _olcu_ozet_yenile() -> None:
        """Plandaki / tampondeki ölçüler — çoklu ölçü görünür özeti."""
        sayac: dict[str, int] = {}
        for s in (plan or {}).get("satirlar") or []:
            sayac[s["olcu_turu"]] = sayac.get(s["olcu_turu"], 0) + 1
        for (olcu, _kat), buf in olcu_tampon.items():
            if any(t is not None for t in buf.get("plan") or []):
                sayac.setdefault(olcu, 0)
        if not sayac:
            olcu_ozet_lbl.set("Ölçü özeti: henüz satır yok (SATIS / GIDER / NAKIT… ayrı ayrı girilir).")
            return
        parcalar = [f"{o}: {n} ay" for o, n in sorted(sayac.items())]
        aktif = _olcu_anahtar()[0]
        olcu_ozet_lbl.set(
            f"Ölçü özeti ({aktif} düzenleniyor): " + " · ".join(parcalar)
        )

    def _olcu_kat_yukle(*_a):
        """Ölçü/kategori değişince kayıtlı ayları yükle; diğer ölçü tamponda kalır."""
        nonlocal aylik_plan, aylik_kaynak
        yeni = _olcu_anahtar()
        eski = aktif_olcu_anahtar["k"]
        if eski is not None and eski != yeni:
            _tampona_yaz()
        if yeni in olcu_tampon:
            buf = olcu_tampon[yeni]
            aylik_plan = list(buf["plan"])
            aylik_kaynak = list(buf["kaynak"])
            giris_modu.set(buf.get("modu") or "manuel")
            if buf.get("kirli"):
                _kirli_yap()
            else:
                # Başka ölçüde kirli varsa üst durumu koru
                baska_kirli = any(
                    b.get("kirli") for ak, b in olcu_tampon.items() if ak != yeni
                )
                if not baska_kirli:
                    _kirli_temizle()
                else:
                    durum_lbl.set("● Kaydedilmemiş değişiklikler var (diğer ölçü)")
        else:
            aylik_plan = [None] * 12
            aylik_kaynak = [None] * 12
            if plan:
                for s in plan.get("satirlar") or []:
                    if s["olcu_turu"] == yeni[0] and s["kategori"] == yeni[1]:
                        ay = int(s["ay"])
                        if 1 <= ay <= 12:
                            aylik_plan[ay - 1] = Decimal(str(s["tutar"]))
                            aylik_kaynak[ay - 1] = s.get("kaynak_giris") or ""
                if any(t is not None for t in aylik_plan):
                    giris_modu.set("manuel")
        aktif_olcu_anahtar["k"] = yeni
        _olcu_ozet_yenile()
        _modu_uygula()

    def _dagitimi_onizle_uygula(*, kaydet_mi: bool = False):
        """Yıllık tutarı eşit dağıt; önizleme veya açık onayla uygula."""
        try:
            yillik = parse_tr_tutar(yillik_var.get())
        except ValueError as hata:
            messagebox.showerror("Bütçe", str(hata), parent=app)
            return
        assert yillik is not None
        yeni = dagit_yillik_esit(yillik, 12)
        if any(t is not None for t in aylik_plan) and giris_modu.get() == "manuel":
            ozet = "\n".join(f"  {ay_adi(i + 1)}: {_para(yeni[i])}" for i in range(12))
            if not messagebox.askyesno(
                "Eşit dağıtım",
                "Mevcut manuel aylık değerler değişecek.\n\n"
                f"Yıllık {_para(yillik)} → 12 ay:\n{ozet}\n\nUygulansın mı?",
                parent=app,
            ):
                return
        for i, t in enumerate(yeni):
            aylik_plan[i] = t
            aylik_kaynak[i] = GIRIS_DAGITIM
        giris_modu.set("yillik")
        _kirli_yap()
        _modu_uygula()
        if kaydet_mi:
            _kaydet()

    def _ay_duzenle(ay_no: int | None = None):
        if not izin_ok and plan:
            messagebox.showwarning("Bütçe", izin_neden, parent=app)
            return
        if ay_no is None:
            sec = onizleme.selection()
            if not sec:
                messagebox.showinfo("Bütçe", "Düzenlemek için bir ay seçin.", parent=app)
                return
            ay_no = int(sec[0])
        idx = ay_no - 1
        dlg = tk.Toplevel(app)
        dlg.title(f"Plan tutarı — {ay_adi(ay_no)}")
        dlg.transient(app)
        dlg.grab_set()
        fr = ttk.Frame(dlg, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"{ay_adi(ay_no)} plan tutarı").pack(anchor="w")
        ttk.Label(
            fr,
            text="Gerçekleşen tutar buradan değişmez.",
            foreground=PASIF,
        ).pack(anchor="w")
        val = tk.StringVar(
            value=("" if aylik_plan[idx] is None else _para(aylik_plan[idx]).replace("—", ""))
        )
        if aylik_plan[idx] is not None:
            # _para binlik noktalı; giriş için düzgün göster
            val.set(_para(aylik_plan[idx]))
        ent = ttk.Entry(fr, textvariable=val, width=20)
        ent.pack(fill="x", pady=8)
        ent.focus_set()
        ent.selection_range(0, "end")

        def uygula(_e=None):
            raw = val.get().strip()
            try:
                if raw == "":
                    aylik_plan[idx] = None
                    aylik_kaynak[idx] = None
                else:
                    t = parse_tr_tutar(raw)
                    assert t is not None
                    if olcu_var.get() != OLCU_NAKIT and t < 0:
                        raise ValueError("Bu ölçüde negatif plan tutarı kabul edilmez.")
                    aylik_plan[idx] = t
                    aylik_kaynak[idx] = GIRIS_MANUEL
            except ValueError as hata:
                messagebox.showerror("Bütçe", str(hata), parent=dlg)
                return "break"
            # Dağıtılmış ay elle değişti → manuel moda geç; diğer aylar korunur
            if giris_modu.get() == "yillik":
                giris_modu.set("manuel")
            _kirli_yap()
            _modu_uygula()
            dlg.destroy()
            # Sonraki aya odak (Tab benzeri)
            nxt = str(min(ay_no + 1, 12))
            if onizleme.exists(nxt):
                onizleme.selection_set(nxt)
                onizleme.focus(nxt)
            return "break"

        def iptal(_e=None):
            dlg.destroy()
            return "break"

        def sonraki(_e=None):
            uygula()
            return "break"

        alt = ttk.Frame(fr)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula (Enter)", command=uygula).pack(side="right")
        ttk.Button(alt, text="İptal (Esc)", command=iptal).pack(side="right", padx=6)
        dlg.bind("<Return>", uygula)
        dlg.bind("<Escape>", iptal)
        dlg.bind("<Tab>", sonraki)

    def _vazgec_git(hedef_fn):
        if not kirli["v"]:
            hedef_fn()
            return
        sec = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklik",
            "Kaydet / Kaydetmeden çık / Ekrana dön\n\n"
            "Evet = Kaydet\nHayır = Kaydetmeden çık\nİptal = Ekrana dön",
            parent=app,
        )
        if sec is True:
            if _kaydet(listeye=False):
                hedef_fn()
        elif sec is False:
            hedef_fn()
        # Cancel → ekranda kal

    def _kaydet(listeye: bool = True) -> bool:
        nonlocal plan
        if plan and not izin_ok:
            messagebox.showwarning("Bütçe", izin_neden, parent=app)
            return False
        ad = ad_var.get().strip()
        if not ad:
            messagebox.showwarning("Bütçe", "Ad zorunludur.", parent=app)
            return False
        try:
            yil = int(yil_var.get().strip())
        except ValueError:
            messagebox.showerror("Bütçe", "Mali yıl geçersiz.", parent=app)
            return False
        pb = pb_var.get().strip() or "TRY"
        if plan and kayitli_yil is not None and (yil != kayitli_yil or pb != kayitli_pb):
            messagebox.showerror(
                "Bütçe",
                "Kayıtlı planda mali yıl veya para birimi değiştirilemez; "
                "tutarlar başka döneme taşınmaz ve kur dönüşümü yapılmaz.",
                parent=app,
            )
            return False
        _tampona_yaz()
        satirlar = []
        for (olcu, kat), buf in olcu_tampon.items():
            for i, t in enumerate(buf.get("plan") or []):
                if t is None:
                    continue
                kaynaklar = buf.get("kaynak") or []
                satirlar.append(
                    {
                        "olcu_turu": olcu,
                        "kategori": kat,
                        "ay": i + 1,
                        "tutar": t,
                        "kaynak_giris": (kaynaklar[i] if i < len(kaynaklar) else None)
                        or GIRIS_MANUEL,
                    }
                )
        eksik_n = sum(1 for t in aylik_plan if t is None)
        if eksik_n and any(t is not None for t in aylik_plan):
            if not messagebox.askyesno(
                "Eksik aylar",
                f"Aktif ölçüde {eksik_n} ay eksik. Taslak olarak kaydedilsin mi?\n"
                "(Eksik aylar tamamlanmış yıllık plan sayılmaz. Diğer ölçüler tamponda korunur.)",
                parent=app,
            ):
                return False
        try:
            if plan is None:
                plan = ButceService.plan_olustur(
                    ad=ad,
                    mali_yil=yil,
                    para_birimi=pb,
                )
            ButceService.plan_meta_guncelle(
                plan["id"],
                ad=ad,
                proje_kodu=proje_var.get().strip() or None,
                senaryo=senaryo_var.get(),
            )
            if satirlar:
                ButceService.satirlar_kaydet(
                    plan["id"],
                    satirlar,
                    beklenen_surum=int(plan.get("surum") or 1),
                )
            plan = ButceService.plan_getir(plan["id"]) or plan
            for buf in olcu_tampon.values():
                buf["kirli"] = False
            _kirli_temizle()
            _olcu_ozet_yenile()
            olcu_adet = len({s["olcu_turu"] for s in satirlar}) if satirlar else 0
            messagebox.showinfo(
                "Bütçe",
                f"Kaydedildi: {plan['kod']}\n"
                f"{'Düzenleme — ikinci plan oluşturulmadı.' if duzenleme else 'Yeni plan.'}\n"
                f"Ölçü sayısı bu kayıtta: {olcu_adet or '—'}\n"
                "(Fatura / fiş / gerçekleşen değişmedi.)",
                parent=app,
            )
            if listeye:
                butce_liste_goster(app)
            return True
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bütçe", str(hata), parent=app)
            return False

    def _excel_aktar():
        nonlocal plan
        if plan is None:
            if not _kaydet(listeye=False):
                return
        if plan is None:
            return
        _excel_aktar_dialog(app, plan["id"])
        # Yeniden yükle — manuel satırlar silinmesin (aktarım kullanıcı seçimli)
        yen = ButceService.plan_getir(plan["id"])
        if yen:
            plan.clear()
            plan.update(yen)
            _olcu_kat_yukle()

    def _vazgec():
        _vazgec_git(lambda: butce_liste_goster(app) if duzenleme else butce_menusu_goster(app))

    arac = ttk.Frame(govde)
    arac.pack(fill="x", padx=4, pady=(8, 0))
    ttk.Button(arac, text="Dağıtımı önizle / uygula", command=_dagitimi_onizle_uygula).pack(
        side="left"
    )
    ttk.Button(arac, text="Seçili Ayı Düzenle", command=lambda: _ay_duzenle()).pack(
        side="left", padx=8
    )
    ttk.Button(arac, text="Excel'den aktar…", command=_excel_aktar).pack(side="left", padx=4)

    onizleme.bind("<Double-1>", lambda e: _ay_duzenle())
    onizleme.bind("<F2>", lambda e: _ay_duzenle())
    olcu_cb.bind("<<ComboboxSelected>>", _olcu_kat_yukle)
    kat_entry.bind("<FocusOut>", _olcu_kat_yukle)
    kat_entry.bind("<Return>", _olcu_kat_yukle)

    # Alt sabit çubuk
    alt = tk.Frame(app.icerik, bg=SARI, pady=8, padx=10)
    alt.pack(fill="x", side="bottom")
    tk.Label(alt, textvariable=yillik_toplam_lbl, bg=SARI, fg=KOYU_LACIVERT, font=FONT_UI_BOLD).pack(
        side="left"
    )
    tk.Label(alt, textvariable=durum_lbl, bg=SARI, fg=KOYU_LACIVERT).pack(side="left", padx=16)
    ttk.Button(alt, text="Vazgeç", command=_vazgec).pack(side="right", padx=4)
    kaydet_btn = _sari_dugme(alt, "Kaydet", lambda: _kaydet(True))
    kaydet_btn.pack(side="right", padx=8)
    if plan and not izin_ok:
        try:
            kaydet_btn.configure(state="disabled")
        except tk.TclError:
            pass

    # İlk yükleme (yeni planda da aktif ölçü anahtarı kurulur — Kaydet tampondan yazar)
    if plan:
        satirlar0 = plan.get("satirlar") or []
        if satirlar0:
            olcu_var.set(satirlar0[0]["olcu_turu"])
            kat_var.set(satirlar0[0]["kategori"])
    _olcu_kat_yukle()

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
        columns=("kod", "ad", "yil", "durum", "senaryo", "pb", "surum", "proje"),
        show="headings",
        height=14,
    )
    for c, b, w in (
        ("kod", "Kod", 110),
        ("ad", "Ad", 180),
        ("yil", "Yıl", 50),
        ("durum", "Durum", 90),
        ("senaryo", "Senaryo", 80),
        ("pb", "PB", 40),
        ("surum", "Sürüm", 50),
        ("proje", "Proje", 80),
    ):
        tree.heading(c, text=b)
        tree.column(c, width=w, anchor="w" if c in ("kod", "ad", "durum", "senaryo", "proje") else "center")
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
                values=(
                    p["kod"],
                    p["ad"],
                    p["mali_yil"],
                    p["durum"],
                    p.get("senaryo") or SENARYO_TEMEL,
                    p["para_birimi"],
                    p["surum"],
                    p.get("proje_kodu") or "",
                ),
            )

    def _secili_id():
        sec = tree.selection()
        if not sec:
            messagebox.showinfo("Bütçe", "Listeden bir plan seçin.", parent=app)
            return None
        return int(sec[0])

    def ac_secili(_event=None):
        pid = _secili_id()
        if pid:
            butce_yeni_goster(app, plan_id=pid)

    def gerceklesen_secili():
        pid = _secili_id()
        if pid:
            butce_gerceklesen_goster(app, plan_id=pid)

    def excel_secili():
        pid = _secili_id()
        if pid:
            _excel_aktar_dialog(app, pid)

    def durum_degistir(hedef: str):
        pid = _secili_id()
        if not pid:
            return
        try:
            ButceService.plan_durum_degistir(pid, hedef)
            yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Durum", str(hata), parent=app)

    def senaryo_kopyala(sen: str):
        pid = _secili_id()
        if not pid:
            return
        try:
            yeni = ButceService.plan_senaryo_kopyala(pid, sen)
            messagebox.showinfo(
                "Senaryo",
                f"Kopya oluşturuldu: {yeni.get('kod')} ({yeni.get('senaryo')})",
                parent=app,
            )
            yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Senaryo", str(hata), parent=app)

    def revizyon():
        pid = _secili_id()
        if not pid:
            return
        try:
            yeni = ButceService.plan_revizyon_olustur(pid, gerekce="UI revizyon")
            messagebox.showinfo(
                "Revizyon",
                f"Yeni sürüm taslağı: {yeni.get('kod')} s{yeni.get('surum')}",
                parent=app,
            )
            yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Revizyon", str(hata), parent=app)

    def pdf_secili():
        pid = _secili_id()
        if not pid:
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            title="Bütçe PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"butce_{pid}.pdf",
        )
        if not yol:
            return
        try:
            ButceService.pdf_rapor_yaz(pid, yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("PDF", str(hata), parent=app)

    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="left", padx=4)
    _sari_dugme(filtre, "Düzenle", ac_secili).pack(side="left", padx=8)
    ttk.Button(filtre, text="Aç", command=ac_secili).pack(side="left", padx=4)
    ttk.Button(filtre, text="Gerçekleşen", command=gerceklesen_secili).pack(side="left", padx=4)
    ttk.Button(filtre, text="Excel…", command=excel_secili).pack(side="left", padx=4)
    ttk.Button(filtre, text="PDF…", command=pdf_secili).pack(side="left", padx=4)

    aksiyon = ttk.Frame(app.icerik)
    aksiyon.pack(fill="x", pady=(6, 0))
    ttk.Label(aksiyon, text="Onay:").pack(side="left")
    ttk.Button(aksiyon, text="İncelemede", command=lambda: durum_degistir(DURUM_INCELEMEDE)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Onayla", command=lambda: durum_degistir(DURUM_ONAYLI)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Kilitle", command=lambda: durum_degistir(DURUM_KILITLI)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Arşiv", command=lambda: durum_degistir(DURUM_ARSIV)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Taslağa al", command=lambda: durum_degistir(DURUM_TASLAK)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Revizyon", command=revizyon).pack(side="left", padx=(12, 2))
    ttk.Label(aksiyon, text="Senaryo kopya:").pack(side="left", padx=(12, 2))
    ttk.Button(aksiyon, text="İyimser", command=lambda: senaryo_kopyala(SENARYO_IYIMSER)).pack(
        side="left", padx=2
    )
    ttk.Button(aksiyon, text="Temkinli", command=lambda: senaryo_kopyala(SENARYO_TEMKINLI)).pack(
        side="left", padx=2
    )

    tree.bind("<Double-1>", ac_secili)
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_liste_goster(app))


def butce_gerceklesen_goster(app, plan_id: int | None = None):
    """Kaynak seçici: Ön Muhasebe | Genel Muhasebe | Yan Yana — toplanmaz."""
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
    kaynak_etiketleri = {
        "Ön Muhasebe": KAYNAK_ON_MUHASEBE,
        "Genel Muhasebe": KAYNAK_GENEL_MUHASEBE,
        "Yan Yana Karşılaştırma": KAYNAK_YAN_YANA,
    }
    kaynak_var = tk.StringVar(value="Ön Muhasebe")

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(12, 0))
    ttk.Label(filtre, text="Plan").pack(side="left")
    ttk.Combobox(
        filtre,
        textvariable=plan_var,
        values=list(plan_map.keys()),
        width=36,
        state="readonly",
    ).pack(side="left", padx=8)
    ttk.Label(filtre, text="Ölçü").pack(side="left", padx=(8, 0))
    ttk.Combobox(
        filtre,
        textvariable=olcu_var,
        values=[OLCU_SATIS, OLCU_GIDER],
        width=10,
        state="readonly",
    ).pack(side="left", padx=8)
    ttk.Label(filtre, text="Kaynak").pack(side="left", padx=(8, 0))
    ttk.Combobox(
        filtre,
        textvariable=kaynak_var,
        values=list(kaynak_etiketleri.keys()),
        width=24,
        state="readonly",
    ).pack(side="left", padx=8)

    kaynak_lbl = ttk.Label(app.icerik, text="", foreground=LACIVERT)
    kaynak_lbl.pack(anchor="w", pady=(8, 0))
    meta_lbl = ttk.Label(app.icerik, text="", foreground=PASIF)
    meta_lbl.pack(anchor="w")
    uyari_cerceve = tk.Frame(app.icerik, bg=ACIK_BG, padx=8, pady=6)
    uyari_cerceve.pack(fill="x", pady=(6, 0))
    uyari_lbl = tk.Label(
        uyari_cerceve,
        text="",
        bg=ACIK_BG,
        fg=LACIVERT,
        font=FONT_ALT,
        justify="left",
        anchor="w",
    )
    uyari_lbl.pack(fill="x")

    tree_frame = ttk.Frame(app.icerik)
    tree_frame.pack(fill="both", expand=True, pady=(10, 0))

    tree_holder = {"tree": None}

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=(8, 0))

    def _tree_kur(yan_yana: bool):
        if tree_holder["tree"] is not None:
            tree_holder["tree"].destroy()
        if yan_yana:
            kolonlar = (
                ("ay", "Ay", 40),
                ("butce", "Bütçe", 100),
                ("on", "Ön Muh.", 100),
                ("gm", "Genel Muh.", 100),
                ("fark_on", "Sapma Ön", 100),
                ("fark_gm", "Sapma GM", 100),
                ("kf", "Kaynak farkı (GM−Ön)", 140),
                ("uyari", "Uyarı", 80),
            )
        else:
            kolonlar = (
                ("ay", "Ay", 50),
                ("butce", "Bütçe", 110),
                ("ger", "Gerçekleşen", 110),
                ("fark", "Fark (Gerç. − Bütçe)", 130),
                ("uyari", "Uyarı", 90),
            )
        tree = ttk.Treeview(
            tree_frame,
            columns=[c[0] for c in kolonlar],
            show="headings",
            height=14,
        )
        for c, b, w in kolonlar:
            tree.heading(c, text=b)
            tree.column(c, width=w, anchor="e" if c not in ("ay", "uyari") else "center")
        tree.tag_configure("ASIM", background="#FDE8E8")
        tree.tag_configure("UYARI", background="#FFF4CE")
        tree.tag_configure("BILGI", background="#E8F1FB")
        tree.tag_configure("BUTCESIZ", background="#F5E6FF")
        tree.pack(fill="both", expand=True)
        tree_holder["tree"] = tree

    def yenile():
        p = plan_map.get(plan_var.get())
        if not p:
            return
        kaynak_kod = kaynak_etiketleri.get(kaynak_var.get(), KAYNAK_ON_MUHASEBE)
        yan = kaynak_kod == KAYNAK_YAN_YANA
        _tree_kur(yan)
        tree = tree_holder["tree"]
        try:
            veri = ButceService.karsilastirma(
                p["id"], olcu_turu=olcu_var.get(), kaynak=kaynak_kod
            )
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bütçe", str(hata), parent=app)
            return

        esikler = ButceAyarService.esikler_oku()
        olcu = olcu_var.get()
        uyarilar = []
        kaynak_lbl.configure(
            text=(
                f"Kaynak: {veri['kaynak_etiket']} — Ön + Genel toplanmaz. | "
                f"Plan {p.get('kod')} s{p.get('surum')} {p.get('senaryo') or SENARYO_TEMEL} "
                f"({p.get('durum')})"
            )
        )
        for s in veri["satirlar"]:
            ger_on = s.get("on_muhasebe")
            ger_gm = s.get("genel_muhasebe")
            ger = ger_on if kaynak_kod == KAYNAK_ON_MUHASEBE else (
                ger_gm if kaynak_kod == KAYNAK_GENEL_MUHASEBE else ger_on
            )
            uy = ButceService.asim_uyari_hesapla(
                s.get("butce"), ger, olcu_turu=olcu, esikler=esikler
            )
            seviye = uy.get("seviye") or "YOK"
            if seviye in ("ASIM", "UYARI", "BUTCESIZ", "BILGI"):
                oran = uy.get("oran")
                uyarilar.append(
                    f"Ay {s['ay']}: {seviye}"
                    + (f" %{oran}" if oran is not None else "")
                )
            tag = seviye if seviye in ("ASIM", "UYARI", "BILGI", "BUTCESIZ") else ""
            if yan:
                tree.insert(
                    "",
                    "end",
                    values=(
                        s["ay"],
                        _para(s["butce"]),
                        _para(s["on_muhasebe"]),
                        _para(s["genel_muhasebe"]),
                        _para(s["fark_on"]),
                        _para(s["fark_gm"]),
                        _para(s["kaynak_farki"]),
                        seviye if seviye != "NORMAL" else "",
                    ),
                    tags=(tag,) if tag else (),
                )
            else:
                fark = (
                    s["fark_on"]
                    if kaynak_kod == KAYNAK_ON_MUHASEBE
                    else s["fark_gm"]
                )
                tree.insert(
                    "",
                    "end",
                    values=(
                        s["ay"],
                        _para(s["butce"]),
                        _para(ger),
                        _para(fark),
                        seviye if seviye != "NORMAL" else "",
                    ),
                    tags=(tag,) if tag else (),
                )

        if uyarilar:
            renk = "#8B1A1A" if any("ASIM" in u or "BUTCESIZ" in u for u in uyarilar) else LACIVERT
            uyari_lbl.configure(
                text="Eşik uyarıları (bilgilendirme; kayıt engellenmez): " + " · ".join(uyarilar[:8]),
                fg=renk,
            )
        else:
            uyari_lbl.configure(text="Eşik uyarısı yok.", fg=PASIF)

        meta = veri.get("gerceklesen_meta") or {}
        parcalar = []
        if meta.get("on"):
            m = meta["on"]
            parcalar.append(
                f"Ön: {m.get('durum')} / belge {m.get('belge_sayisi')} / "
                f"boş aylar {m.get('bos_aylar') or '—'}"
            )
            if m.get("mesaj"):
                parcalar.append(f"Ön not: {m['mesaj']}")
        if meta.get("gm"):
            m = meta["gm"]
            parcalar.append(
                f"GM: {m.get('durum')} / fiş {m.get('belge_sayisi')} / "
                f"boş aylar {m.get('bos_aylar') or '—'}"
            )
            if m.get("mesaj"):
                parcalar.append(f"GM not: {m['mesaj']}")
        if not meta.get("on") and not meta.get("gm"):
            parcalar.append(
                f"Durum: {meta.get('durum')} | Belge: {meta.get('belge_sayisi')}"
            )
        meta_lbl.configure(text=" | ".join(parcalar))

        if yan:
            ozet.configure(
                text=(
                    f"Bütçe: {_para(veri.get('butce_toplam'))}   |   "
                    f"Ön: {_para(veri.get('on_muhasebe_toplam'))}   |   "
                    f"GM: {_para(veri.get('genel_muhasebe_toplam'))}   |   "
                    f"Kaynak farkı (GM−Ön): {_para(veri.get('kaynak_farki_toplam'))}"
                )
            )
        elif kaynak_kod == KAYNAK_GENEL_MUHASEBE:
            ozet.configure(
                text=(
                    f"Bütçe toplam: {_para(veri.get('butce_toplam'))}   |   "
                    f"Genel Muhasebe toplam: {_para(veri.get('genel_muhasebe_toplam'))}"
                )
            )
        else:
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


def butce_nakit_goster(app, plan_id: int | None = None):
    """Nakit bütçesi: başlangıç kullanılabilir, plan/gerçek giriş-çıkış, dönem sonu."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="NAKİT BÜTÇESİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text=(
            "Kullanılabilir kasa + banka (mevduat/KMH). POS alacağı, kredi kartı borcu ve "
            "KMH limiti hazır nakde eklenmez. İç virman firma nakdini artırmaz."
        ),
        foreground=PASIF,
    ).pack(anchor="w", pady=(8, 0))

    yil_var = tk.StringVar(value=str(_mali_yil_varsayilan()))
    ay_var = tk.StringVar(value="Tümü (yıllık)")
    planlar = ButceService.planlari_listele()
    plan_map = {"— plansız —": None}
    plan_map.update({f"{p['kod']} — {p['ad']}": p for p in planlar})
    plan_sec = None
    if plan_id:
        for etiket, p in plan_map.items():
            if p and p["id"] == plan_id:
                plan_sec = etiket
                break
    plan_var = tk.StringVar(value=plan_sec or "— plansız —")

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(12, 0))
    ttk.Label(filtre, text="Mali yıl").pack(side="left")
    ttk.Entry(filtre, textvariable=yil_var, width=8).pack(side="left", padx=8)
    ttk.Label(filtre, text="Ay").pack(side="left", padx=(8, 0))
    ttk.Combobox(
        filtre,
        textvariable=ay_var,
        values=["Tümü (yıllık)"] + [str(i) for i in range(1, 13)],
        width=14,
        state="readonly",
    ).pack(side="left", padx=8)
    ttk.Label(filtre, text="Plan (NAKIT satırları)").pack(side="left", padx=(8, 0))
    ttk.Combobox(
        filtre,
        textvariable=plan_var,
        values=list(plan_map.keys()),
        width=32,
        state="readonly",
    ).pack(side="left", padx=8)

    ozet_frame = tk.Frame(app.icerik, bg=ACIK_BG, padx=12, pady=10)
    ozet_frame.pack(fill="x", pady=(12, 0))
    ozet_lbls = {}
    for i, (anahtar, baslik) in enumerate(
        (
            ("baslangic", "Başlangıç kullanılabilir"),
            ("plan_giris", "Planlanan giriş"),
            ("plan_cikis", "Planlanan çıkış"),
            ("gercek_giris", "Gerçek giriş"),
            ("gercek_cikis", "Gerçek çıkış"),
            ("donem_sonu", "Dönem sonu"),
            ("kk", "KK taksit planı"),
            ("virman", "İç virman (bilgi)"),
        )
    ):
        kutu = tk.Frame(ozet_frame, bg=BEYAZ, padx=8, pady=6)
        kutu.grid(row=0, column=i, padx=4, sticky="nsew")
        ozet_frame.columnconfigure(i, weight=1)
        tk.Label(kutu, text=baslik, bg=BEYAZ, fg=PASIF, font=FONT_ALT).pack(anchor="w")
        deger = tk.Label(kutu, text="—", bg=BEYAZ, fg=LACIVERT, font=FONT_UI_BOLD)
        deger.pack(anchor="w")
        ozet_lbls[anahtar] = deger

    meta_lbl = ttk.Label(app.icerik, text="", foreground=PASIF)
    meta_lbl.pack(anchor="w", pady=(8, 0))
    ttk.Label(
        app.icerik,
        text="KK taksit planı vade aylarına göre bilgilendirme; gerçek banka çıkışı ödeme tarihinde sayılır.",
        foreground=PASIF,
    ).pack(anchor="w")

    tree = ttk.Treeview(
        app.icerik,
        columns=(
            "ay",
            "bas",
            "p_gir",
            "p_cik",
            "g_gir",
            "g_cik",
            "son",
            "kk",
            "virman",
        ),
        show="headings",
        height=14,
    )
    for c, b, w in (
        ("ay", "Ay", 40),
        ("bas", "Başlangıç", 90),
        ("p_gir", "Plan giriş", 80),
        ("p_cik", "Plan çıkış", 80),
        ("g_gir", "Gerçek giriş", 90),
        ("g_cik", "Gerçek çıkış", 90),
        ("son", "Dönem sonu", 90),
        ("kk", "KK taksit plan", 100),
        ("virman", "İç virman net", 90),
    ):
        tree.heading(c, text=b)
        tree.column(c, width=w, anchor="e" if c != "ay" else "center")
    tree.pack(fill="both", expand=True, pady=(10, 0))

    def yenile():
        tree.delete(*tree.get_children())
        try:
            yil = int(yil_var.get().strip())
        except ValueError:
            messagebox.showerror("Nakit", "Mali yıl geçersiz.", parent=app)
            return
        ay_raw = ay_var.get()
        ay = None if ay_raw.startswith("Tümü") else int(ay_raw)
        p = plan_map.get(plan_var.get())
        pid = p["id"] if p else None
        try:
            veri = ButceService.nakit_butcesi(yil, ay=ay, plan_id=pid)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Nakit", str(hata), parent=app)
            return

        ozet_lbls["baslangic"].configure(text=_para(veri["baslangic_kullanilabilir"]))
        ozet_lbls["plan_giris"].configure(text=_para(veri.get("planlanan_giris")))
        ozet_lbls["plan_cikis"].configure(text=_para(veri.get("planlanan_cikis")))
        ozet_lbls["gercek_giris"].configure(text=_para(veri["gercek_giris"]))
        ozet_lbls["gercek_cikis"].configure(text=_para(veri["gercek_cikis"]))
        ozet_lbls["donem_sonu"].configure(text=_para(veri["donem_sonu"]))
        ozet_lbls["kk"].configure(text=_para(veri.get("kk_taksit_plan")))
        ozet_lbls["virman"].configure(
            text=f"{_para(veri['ic_virman_net'])} (nakde etkisi yok)"
        )
        meta_lbl.configure(
            text=(
                f"Dönem: {veri['donem_etiket']} | Bakiye kaynağı: {veri['bakiye_kaynak']} | "
                f"Dış hareket: {veri['hareket_sayisi']} | İç virman: {veri['ic_virman_sayisi']} | "
                f"Durum: {veri['durum']}"
                + (f" — {veri['mesaj']}" if veri.get("mesaj") else "")
            )
        )

        aylik = veri.get("aylik")
        if aylik:
            for s in aylik:
                tree.insert(
                    "",
                    "end",
                    values=(
                        s["ay"],
                        _para(s["baslangic_kullanilabilir"]),
                        _para(s.get("planlanan_giris")),
                        _para(s.get("planlanan_cikis")),
                        _para(s["gercek_giris"]),
                        _para(s["gercek_cikis"]),
                        _para(s["donem_sonu"]),
                        _para(s.get("kk_taksit_plan")),
                        _para(s["ic_virman_net"]),
                    ),
                )
        else:
            tree.insert(
                "",
                "end",
                values=(
                    ay or "Yıl",
                    _para(veri["baslangic_kullanilabilir"]),
                    _para(veri.get("planlanan_giris")),
                    _para(veri.get("planlanan_cikis")),
                    _para(veri["gercek_giris"]),
                    _para(veri["gercek_cikis"]),
                    _para(veri["donem_sonu"]),
                    _para(veri.get("kk_taksit_plan")),
                    _para(veri["ic_virman_net"]),
                ),
            )

    ttk.Button(filtre, text="Yenile", command=yenile).pack(side="left", padx=12)
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_nakit_goster(app, plan_id))


def butce_raporlar_goster(app):
    """Rapor / Excel hub — şablon, aktarım, gerçekleşen ve nakit kısayolları."""
    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BÜTÇE RAPORLARI / EXCEL", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text=(
            "Excel şablonu (kategori, ölçü türü, para birimi, ay, tutar). "
            "Önizleme ve doğrulama; hata halinde yarım aktarım yok. "
            "Tekrar aktarımda güncelle veya atla."
        ),
    ).pack(anchor="w", pady=(12, 0))

    sari_cubuk = tk.Frame(app.icerik, bg=SARI, height=4)
    sari_cubuk.pack(fill="x", pady=(12, 8))

    planlar = ButceService.planlari_listele()
    plan_map = {f"{p['kod']} — {p['ad']}": p for p in planlar}
    plan_var = tk.StringVar(value=next(iter(plan_map), ""))

    satir = ttk.Frame(app.icerik)
    satir.pack(fill="x", pady=(8, 0))
    ttk.Label(satir, text="Hedef plan").pack(side="left")
    ttk.Combobox(
        satir,
        textvariable=plan_var,
        values=list(plan_map.keys()) or ["(plan yok)"],
        width=40,
        state="readonly",
    ).pack(side="left", padx=8)

    def sablon():
        yol = filedialog.asksaveasfilename(
            parent=app,
            title="Excel şablonu kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="butce_satir_sablonu.xlsx",
        )
        if not yol:
            return
        try:
            ButceService.excel_sablon_olustur(yol)
            messagebox.showinfo("Excel", f"Şablon kaydedildi:\n{yol}", parent=app)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Excel", str(hata), parent=app)

    def aktar():
        p = plan_map.get(plan_var.get())
        if not p:
            messagebox.showinfo("Excel", "Önce bir bütçe planı seçin veya oluşturun.", parent=app)
            return
        _excel_aktar_dialog(app, p["id"])

    def pdf_yaz():
        p = plan_map.get(plan_var.get())
        if not p:
            messagebox.showinfo("PDF", "Önce bir bütçe planı seçin.", parent=app)
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            title="Bütçe PDF kaydet",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"{p['kod']}_rapor.pdf",
        )
        if not yol:
            return
        try:
            ButceService.pdf_rapor_yaz(p["id"], yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("PDF", str(hata), parent=app)

    dug = ttk.Frame(app.icerik)
    dug.pack(fill="x", pady=(16, 0))
    ttk.Button(dug, text="Şablon indir…", command=sablon).pack(side="left")
    _sari_dugme(dug, "Excel aktar…", aktar).pack(side="left", padx=12)
    ttk.Button(dug, text="PDF…", command=pdf_yaz).pack(side="left", padx=4)
    ttk.Button(
        dug, text="Gerçekleşen", command=lambda: butce_gerceklesen_goster(app)
    ).pack(side="left", padx=4)
    ttk.Button(dug, text="Nakit bütçesi", command=lambda: butce_nakit_goster(app)).pack(
        side="left", padx=4
    )

    ttk.Label(
        app.icerik,
        text=(
            "PDF, Excel ve ekran aynı karşılaştırma sonucunu kullanır. "
            "Geniş yıllık paket (çoklu rapor demeti) isteğe bağlı genişletilebilir."
        ),
        foreground=PASIF,
    ).pack(anchor="w", pady=(20, 0))

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_raporlar_goster(app))


def butce_ayarlar_goster(app):
    from database.session_manager import oturum

    ButceService.ensure_schema()
    app._icerigi_temizle()
    _menu_isaretle(app)
    firma_id = int(getattr(oturum, "firma_id", None) or 0)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BÜTÇE AYARLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Bütçe", command=lambda: butce_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text=(
            "Aşım eşikleri, kategori/hesap eşleştirme, bilanço hedefleri ve senaryo notları. "
            "Proje modülü yoksa proje_kodu alanı boş bırakılabilir."
        ),
    ).pack(anchor="w", pady=(8, 4))

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, pady=(8, 0))

    # —— Eşikler ——
    fr_e = ttk.Frame(nb, padding=8)
    nb.add(fr_e, text="Aşım eşikleri")
    esik = ButceAyarService.esikler_oku(firma_id)
    satir = ttk.Frame(fr_e)
    satir.pack(anchor="w", pady=4)
    ttk.Label(satir, text="Bilgi %").grid(row=0, column=0, sticky="w", padx=(0, 6))
    bilgi_v = tk.StringVar(value=str(esik["bilgi_yuzde"]))
    ttk.Entry(satir, textvariable=bilgi_v, width=6).grid(row=0, column=1, padx=(0, 16))
    ttk.Label(satir, text="Uyarı %").grid(row=0, column=2, sticky="w", padx=(0, 6))
    uyari_v = tk.StringVar(value=str(esik["uyari_yuzde"]))
    ttk.Entry(satir, textvariable=uyari_v, width=6).grid(row=0, column=3, padx=(0, 16))
    ttk.Label(satir, text="Aşım %").grid(row=0, column=4, sticky="w", padx=(0, 6))
    asim_v = tk.StringVar(value=str(esik["asim_yuzde"]))
    ttk.Entry(satir, textvariable=asim_v, width=6).grid(row=0, column=5)

    def _esik_kaydet():
        try:
            ButceAyarService.esikler_kaydet(
                firma_id,
                int(bilgi_v.get().strip()),
                int(uyari_v.get().strip()),
                int(asim_v.get().strip()),
            )
            messagebox.showinfo("Bütçe", "Eşikler kaydedildi.", parent=app)
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bütçe", str(hata), parent=app)

    ttk.Button(fr_e, text="Eşikleri Kaydet", command=_esik_kaydet).pack(anchor="w", pady=(8, 0))
    ttk.Label(
        fr_e,
        text=(
            "Varsayılan: bilgi 80, uyarı 100, aşım 100. "
            "Satış hedef aşımı gider aşımı gibi olumsuz sayılmaz. "
            "Uyarı bilgilendirmedir; satış/fatura/ödeme engellenmez."
        ),
        wraplength=720,
    ).pack(anchor="w", pady=(8, 0))

    # —— Eşleştirme ——
    fr_m = ttk.Frame(nb, padding=8)
    nb.add(fr_m, text="Kategori / hesap eşleştirme")
    tab = ttk.Treeview(
        fr_m,
        columns=("olcu", "kategori", "kaynak", "kod", "aciklama"),
        show="headings",
        height=12,
    )
    for c, h, w in (
        ("olcu", "Ölçü", 90),
        ("kategori", "Kategori", 120),
        ("kaynak", "Kaynak", 120),
        ("kod", "Hesap/kod", 100),
        ("aciklama", "Açıklama", 200),
    ):
        tab.heading(c, text=h)
        tab.column(c, width=w)
    tab.pack(fill="both", expand=True)

    def _eslesme_yenile():
        for i in tab.get_children():
            tab.delete(i)
        for e in ButceAyarService.eslesme_listele(firma_id):
            if not e.get("aktif"):
                continue
            tab.insert(
                "",
                "end",
                iid=str(e["id"]),
                values=(e["olcu_turu"], e["kategori"], e["kaynak"], e["kaynak_kod"], e["aciklama"]),
            )

    form = ttk.Frame(fr_m)
    form.pack(fill="x", pady=(8, 0))
    olcu_v = tk.StringVar(value="GIDER")
    kat_v = tk.StringVar(value="GENEL")
    kay_v = tk.StringVar(value=KAYNAK_ON_MUHASEBE)
    kod_v = tk.StringVar()
    ack_v = tk.StringVar()
    ttk.Label(form, text="Ölçü").grid(row=0, column=0, sticky="w")
    ttk.Combobox(
        form, textvariable=olcu_v, values=list(OLCU_TURLERI), width=12
    ).grid(row=0, column=1, padx=4)
    ttk.Label(form, text="Kategori").grid(row=0, column=2, sticky="w")
    ttk.Entry(form, textvariable=kat_v, width=14).grid(row=0, column=3, padx=4)
    ttk.Label(form, text="Kaynak").grid(row=0, column=4, sticky="w")
    ttk.Combobox(
        form, textvariable=kay_v, values=(KAYNAK_ON_MUHASEBE, KAYNAK_GENEL_MUHASEBE), width=16
    ).grid(row=0, column=5, padx=4)
    ttk.Label(form, text="Kod").grid(row=1, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(form, textvariable=kod_v, width=14).grid(row=1, column=1, padx=4, pady=(4, 0))
    ttk.Label(form, text="Açıklama").grid(row=1, column=2, sticky="w", pady=(4, 0))
    ttk.Entry(form, textvariable=ack_v, width=28).grid(
        row=1, column=3, columnspan=3, sticky="ew", padx=4, pady=(4, 0)
    )

    def _eslesme_ekle():
        try:
            ButceAyarService.eslesme_kaydet(
                firma_id=firma_id,
                olcu_turu=olcu_v.get(),
                kategori=kat_v.get(),
                kaynak=kay_v.get(),
                kaynak_kod=kod_v.get(),
                aciklama=ack_v.get(),
            )
            _eslesme_yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Eşleştirme", str(hata), parent=app)

    def _eslesme_sil():
        sec = tab.selection()
        if not sec:
            return
        try:
            ButceAyarService.eslesme_pasiflestir(int(sec[0]), firma_id=firma_id)
            _eslesme_yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Eşleştirme", str(hata), parent=app)

    btn = ttk.Frame(fr_m)
    btn.pack(fill="x", pady=(6, 0))
    ttk.Button(btn, text="Ekle / Kaydet", command=_eslesme_ekle).pack(side="left")
    ttk.Button(btn, text="Seçiliyi Pasifleştir", command=_eslesme_sil).pack(side="left", padx=8)
    _eslesme_yenile()

    # —— Bilanço hedefleri ——
    fr_b = ttk.Frame(nb, padding=8)
    nb.add(fr_b, text="Bilanço hedefleri")
    ttk.Label(
        fr_b,
        text="Dönem sonu bakiye hedefi (STOK / ALACAK / BORC / …). Hareket toplamı değildir.",
        wraplength=720,
    ).pack(anchor="w")
    planlar_b = ButceService.planlari_listele()
    plan_b_map = {f"{p['kod']} — {p['ad']}": p for p in planlar_b}
    plan_b_var = tk.StringVar(value=next(iter(plan_b_map), ""))
    ust_b = ttk.Frame(fr_b)
    ust_b.pack(fill="x", pady=(8, 0))
    ttk.Label(ust_b, text="Plan").pack(side="left")
    ttk.Combobox(
        ust_b,
        textvariable=plan_b_var,
        values=list(plan_b_map.keys()) or ["(plan yok)"],
        width=40,
        state="readonly",
    ).pack(side="left", padx=8)
    bil_tab = ttk.Treeview(
        fr_b,
        columns=("grup", "ay", "hedef", "ack"),
        show="headings",
        height=8,
    )
    for c, h, w in (
        ("grup", "Hesap grubu", 120),
        ("ay", "Kesim ay", 70),
        ("hedef", "Hedef tutar", 120),
        ("ack", "Açıklama", 220),
    ):
        bil_tab.heading(c, text=h)
        bil_tab.column(c, width=w)
    bil_tab.pack(fill="both", expand=True, pady=(8, 0))

    def _bilanco_yenile():
        for i in bil_tab.get_children():
            bil_tab.delete(i)
        p = plan_b_map.get(plan_b_var.get())
        if not p:
            return
        for h in ButceService.bilanco_hedefleri(p["id"], firma_id=firma_id):
            bil_tab.insert(
                "",
                "end",
                values=(h["hesap_grubu"], h["ay"], _para(h["hedef_tutar"]), h.get("aciklama") or ""),
            )

    form_b = ttk.Frame(fr_b)
    form_b.pack(fill="x", pady=(6, 0))
    grup_v = tk.StringVar(value="STOK")
    ay_b_v = tk.StringVar(value="12")
    hedef_v = tk.StringVar(value="0")
    bil_ack_v = tk.StringVar()
    ttk.Label(form_b, text="Grup").grid(row=0, column=0)
    ttk.Combobox(
        form_b,
        textvariable=grup_v,
        values=("STOK", "ALACAK", "BORC", "NAKIT", "DIGER"),
        width=12,
    ).grid(row=0, column=1, padx=4)
    ttk.Label(form_b, text="Ay").grid(row=0, column=2)
    ttk.Entry(form_b, textvariable=ay_b_v, width=4).grid(row=0, column=3, padx=4)
    ttk.Label(form_b, text="Hedef").grid(row=0, column=4)
    ttk.Entry(form_b, textvariable=hedef_v, width=12).grid(row=0, column=5, padx=4)
    ttk.Entry(form_b, textvariable=bil_ack_v, width=24).grid(row=0, column=6, padx=4)

    def _bilanco_kaydet():
        p = plan_b_map.get(plan_b_var.get())
        if not p:
            messagebox.showinfo("Bilanço", "Plan seçin.", parent=app)
            return
        try:
            ButceService.bilanco_hedef_kaydet(
                p["id"],
                [
                    {
                        "hesap_grubu": grup_v.get(),
                        "ay": int(ay_b_v.get()),
                        "hedef_tutar": hedef_v.get().replace(",", "."),
                        "aciklama": bil_ack_v.get(),
                    }
                ],
                firma_id=firma_id,
            )
            _bilanco_yenile()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Bilanço", str(hata), parent=app)

    ttk.Button(form_b, text="Hedef Kaydet", command=_bilanco_kaydet).grid(row=0, column=7, padx=8)
    ttk.Button(ust_b, text="Yenile", command=_bilanco_yenile).pack(side="left", padx=4)
    _bilanco_yenile()

    # —— Senaryo / proje ——
    fr_s = ttk.Frame(nb, padding=8)
    nb.add(fr_s, text="Senaryo / proje")
    ttk.Label(
        fr_s,
        text=(
            f"Senaryolar: {', '.join(SENARYOLAR)}. "
            "Liste ekranından İyimser/Temkinli kopya ve Revizyon üretin; "
            "toplamda yalnız seçili senaryo kullanılır. "
            "Proje kodu plan kartına yazılır; Proje Takip yoksa firma bütçesi bağımsız çalışır."
        ),
        wraplength=720,
    ).pack(anchor="w")
    ttk.Button(
        fr_s, text="Bütçe listesine git", command=lambda: butce_liste_goster(app)
    ).pack(anchor="w", pady=(12, 0))

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: butce_ayarlar_goster(app))


# --------------------------------------------------------------------------- Excel dialog


def _excel_aktar_dialog(app, plan_id: int):
    yol = filedialog.askopenfilename(
        parent=app,
        title="Bütçe satırları Excel",
        filetypes=[("Excel", "*.xlsx"), ("Tüm dosyalar", "*.*")],
    )
    if not yol:
        return
    try:
        onizleme = ButceService.excel_onizle(yol, plan_id=plan_id)
    except Exception as hata:  # noqa: BLE001
        messagebox.showerror("Excel", str(hata), parent=app)
        return

    dlg = tk.Toplevel(app)
    dlg.title("Excel önizleme / aktarım")
    dlg.transient(app)
    dlg.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(dlg)
    ttk.Label(
        dlg,
        text=(
            f"Satır: {onizleme['satir_sayisi']} | "
            f"Yeni: {onizleme.get('yeni_sayisi', 0)} | "
            f"Çakışan: {onizleme.get('cakisma_sayisi', 0)} | "
            f"Hata: {len(onizleme['hatalar'])} | "
            f"Geçerli: {'Evet' if onizleme['gecerli'] else 'Hayır'}"
        ),
    ).pack(anchor="w", padx=12, pady=(12, 4))

    tree = ttk.Treeview(
        dlg,
        columns=("no", "kat", "olcu", "pb", "ay", "tutar", "mevcut", "durum", "hata"),
        show="headings",
        height=12,
    )
    for c, b, w in (
        ("no", "#", 40),
        ("kat", "Kategori", 90),
        ("olcu", "Ölçü", 70),
        ("pb", "PB", 40),
        ("ay", "Ay", 36),
        ("tutar", "Excel", 90),
        ("mevcut", "Mevcut", 90),
        ("durum", "Önizleme", 110),
        ("hata", "Hata", 180),
    ):
        tree.heading(c, text=b)
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, padx=12, pady=4)
    for s in onizleme["satirlar"]:
        durum = s.get("cakisma_durum") or "yeni"
        etiket = "Yeni" if durum == "yeni" else "Güncellenecek"
        tree.insert(
            "",
            "end",
            values=(
                s["satir_no"],
                s["kategori"],
                s["olcu_turu"],
                s["para_birimi"],
                s["ay"],
                _para(s["tutar"]),
                _para(s.get("mevcut_tutar")),
                etiket,
                "; ".join(s.get("hatalar") or []) or "—",
            ),
        )

    cakisma_var = tk.StringVar(value="guncelle")
    sec = ttk.Frame(dlg)
    sec.pack(fill="x", padx=12, pady=8)
    ttk.Label(sec, text="Çakışan satırlar:").pack(side="left")
    ttk.Radiobutton(
        sec,
        text="Güncelle (üzerine yaz)",
        variable=cakisma_var,
        value="guncelle",
    ).pack(side="left", padx=8)
    ttk.Radiobutton(
        sec,
        text="Atla (mevcut kalsın)",
        variable=cakisma_var,
        value="atla",
    ).pack(side="left")
    ttk.Label(
        dlg,
        text="Aktarım öncesi önizleme — hata varsa hiçbir satır yazılmaz.",
        foreground=PASIF,
    ).pack(anchor="w", padx=12)

    def aktar():
        if not onizleme["gecerli"]:
            messagebox.showerror(
                "Excel",
                "Doğrulama hatalı — aktarım yapılmadı (yarım kayıt yok).",
                parent=dlg,
            )
            return
        try:
            sonuc = ButceService.excel_aktar(
                plan_id, yol, cakisma=cakisma_var.get()
            )
            messagebox.showinfo(
                "Excel",
                (
                    f"Aktarım tamam: eklenen {sonuc['eklenen']}, "
                    f"güncellenen {sonuc['guncellenen']}, atlanan {sonuc['atlanan']}."
                ),
                parent=dlg,
            )
            dlg.destroy()
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Excel", str(hata), parent=dlg)

    alt = ttk.Frame(dlg)
    alt.pack(fill="x", padx=12, pady=(0, 12))
    ttk.Button(alt, text="İptal", command=dlg.destroy).pack(side="right")
    _sari_dugme(alt, "Aktar", aktar).pack(side="right", padx=8)
