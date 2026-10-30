"""GELİR VE GİDERLER → Giderler → Gider Raporları (R01–R08) ve ayarlar."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

from ui_takvim import takvim_butonu
from database.gider_rapor_service import GiderRaporService, onceki_es_donem, ay_araligi
from database.rapor_service import MALIYET_YONTEMLERI_RAPOR


def _para(tutar) -> str:
    if tutar is None:
        return "—"
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _yuz(v) -> str:
    if v is None:
        return "—"
    return f"%{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_oku(entry) -> date:
    return datetime.strptime((entry.get() or "").strip(), "%d.%m.%Y").date()


def _ay_basi() -> date:
    t = date.today()
    return date(t.year, t.month, 1)


# --------------------------------------------------------------------------- menü
def gider_raporlari_merkezi_goster(app):
    from gelir_gider_ui import _menu_isaretle, giderler_menusu_goster

    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GİDER RAPORLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Giderler", command=lambda: giderler_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Dönem gideri, dağılım, bütçe, ödeme, finansman ve başa baş — salt okunur yönetim analizi.",
    ).pack(anchor="w", pady=(8, 0))

    raporlar = (
        ("R01", "Gider Genel Bakış", r01_goster),
        ("R02", "Gider Dağılımı ve Oranlar", r02_goster),
        ("R03", "Dönem Karşılaştırması ve Eğilim", r03_goster),
        ("R04", "Bütçe ve Sapma Analizi", r04_goster),
        ("R05", "Ödeme ve Vade Analizi", r05_goster),
        ("R06", "Finansman ve POS Maliyetleri", r06_goster),
        ("R07", "Sabit Gider ve Başa Baş Analizi", r07_goster),
        ("R08", "Gider Detayı ve Belge Kontrolü", r08_goster),
    )
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(16, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (kod, ad, fn) in enumerate(raporlar):
        ttk.Button(
            alt,
            text=f"{kod} — {ad}",
            style="AltMenu.TButton",
            command=lambda f=fn: nav(lambda: f(app)),
        ).grid(row=i, column=0, sticky="ew", pady=3)
    ttk.Button(
        alt,
        text="GİDER RAPOR AYARLARI",
        style="AltMenu.TButton",
        command=lambda: nav(lambda: gider_rapor_ayarlari_goster(app)),
    ).grid(row=len(raporlar), column=0, sticky="ew", pady=(12, 3))
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: gider_raporlari_merkezi_goster(app))


def gider_rapor_ayarlari_goster(app):
    from gelir_gider_ui import _menu_isaretle

    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GİDER RAPOR AYARLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Raporlar", command=lambda: gider_raporlari_merkezi_goster(app)).pack(
        side="right"
    )

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, pady=8)

    # Sınıflandırma
    f1 = ttk.Frame(nb, padding=8)
    nb.add(f1, text="Sınıflandırma")
    ttk.Label(f1, text="Ana grup › alt grup hiyerarşisi (mevcut dört kart sınıfı korunur).").pack(anchor="w")
    tree = ttk.Treeview(f1, columns=("kod", "ad", "yer"), show="headings", height=16)
    for k, b, w in (("kod", "Kod", 100), ("ad", "Ad", 320), ("yer", "Sonuç", 80)):
        tree.heading(k, text=b)
        tree.column(k, width=w)
    tree.pack(fill="both", expand=True, pady=6)

    def yenile_grup():
        for i in tree.get_children():
            tree.delete(i)
        for g in GiderRaporService.ana_gruplari_listele():
            tree.insert("", "end", values=(g["kod"], g["ad"], g["sonuc_yeri"]))
            for a in g["alt_gruplar"]:
                tree.insert("", "end", values=(f"  {a['kod']}", a["ad"], ""))

    yenile_grup()

    # Dağıtım
    f2 = ttk.Frame(nb, padding=8)
    nb.add(f2, text="Dağıtım Kuralları")
    ttk.Label(
        f2,
        text="Ortak gider dağıtım anahtarları. Anahtar yoksa tutar «Dağıtılmamış» kalır; "
        "şube kârı tam sunulmaz. Rapor dağıtım fişi üretmez.",
        wraplength=700,
    ).pack(anchor="w")

    # Bütçe
    f3 = ttk.Frame(nb, padding=8)
    nb.add(f3, text="Bütçe Planları")
    satir = ttk.Frame(f3)
    satir.pack(fill="x", pady=4)
    ttk.Label(satir, text="Yıl:").pack(side="left")
    yil_e = ttk.Entry(satir, width=6)
    yil_e.insert(0, str(date.today().year))
    yil_e.pack(side="left", padx=4)
    ttk.Label(satir, text="Ay:").pack(side="left")
    ay_e = ttk.Entry(satir, width=4)
    ay_e.insert(0, str(date.today().month))
    ay_e.pack(side="left", padx=4)
    ttk.Label(satir, text="Ana grup kod:").pack(side="left", padx=(8, 0))
    grup_e = ttk.Combobox(
        satir, values=[g["kod"] for g in GiderRaporService.ana_gruplari_listele()], width=14
    )
    grup_e.pack(side="left", padx=4)
    ttk.Label(satir, text="Tutar:").pack(side="left")
    tutar_e = ttk.Entry(satir, width=12)
    tutar_e.pack(side="left", padx=4)

    def butce_kaydet():
        try:
            GiderRaporService.butce_kaydet(
                int(yil_e.get()),
                int(ay_e.get()),
                (grup_e.get() or "").strip().upper(),
                tutar_e.get().replace(".", "").replace(",", ".") or "0",
                durum="ONAYLI",
            )
            messagebox.showinfo("Bütçe", "Onaylı bütçe satırı kaydedildi.", parent=app)
        except Exception as exc:
            messagebox.showerror("Bütçe", str(exc), parent=app)

    ttk.Button(satir, text="Onaylı kaydet", command=butce_kaydet).pack(side="left", padx=8)
    ttk.Label(
        f3,
        text="Bütçesi olmayan satır «tanımlı değil» olur; sıfır bütçeye gider gelirse plansız harcama.",
        wraplength=700,
    ).pack(anchor="w", pady=8)

    # Rapor tanımları
    f4 = ttk.Frame(nb, padding=8)
    nb.add(f4, text="Rapor Tanımları")
    ttk.Label(
        f4,
        text=(
            "R01–R08 kimlikleri sabittir. Varsayılan esas: kayıtlı dönem gideri (KDV hariç). "
            "Ödeme ve kapatma ayrı ölçülerdir. Rapor açmak ekonomik kayıt üretmez."
        ),
        wraplength=700,
    ).pack(anchor="w")


# --------------------------------------------------------------------------- ortak rapor kabuğu
def _rapor_kabuk(app, baslik: str, aciklama: str, hesapla_fn, kolonlar, doldur_fn, *, karsilastirma=False):
    from gelir_gider_ui import _menu_isaretle

    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Raporlar", command=lambda: gider_raporlari_merkezi_goster(app)).pack(
        side="right"
    )
    ttk.Label(app.icerik, text=aciklama, wraplength=900).pack(anchor="w", pady=(6, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x")
    ttk.Label(filtre, text="Başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    bas = ttk.Entry(b_c, width=11)
    bas.insert(0, _ay_basi().strftime("%d.%m.%Y"))
    bas.pack(side="left")
    takvim_butonu(b_c, bas)
    ttk.Label(filtre, text="Bitiş:").pack(side="left", padx=(8, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bit = ttk.Entry(e_c, width=11)
    bit.insert(0, date.today().strftime("%d.%m.%Y"))
    bit.pack(side="left")
    takvim_butonu(e_c, bit)

    ob = oe = None
    if karsilastirma:
        ttk.Label(filtre, text="B başlangıç:").pack(side="left", padx=(12, 0))
        ob_c = ttk.Frame(filtre)
        ob_c.pack(side="left")
        ob = ttk.Entry(ob_c, width=11)
        ob.pack(side="left")
        takvim_butonu(ob_c, ob)
        ttk.Label(filtre, text="B bitiş:").pack(side="left", padx=(8, 0))
        oe_c = ttk.Frame(filtre)
        oe_c.pack(side="left")
        oe = ttk.Entry(oe_c, width=11)
        oe.pack(side="left")
        takvim_butonu(oe_c, oe)

        def _es_doldur():
            try:
                a, z = onceki_es_donem(_tarih_oku(bas), _tarih_oku(bit))
                ob.delete(0, "end")
                ob.insert(0, a.strftime("%d.%m.%Y"))
                oe.delete(0, "end")
                oe.insert(0, z.strftime("%d.%m.%Y"))
            except Exception:
                pass

        ttk.Button(filtre, text="Önceki eş dönem", command=_es_doldur).pack(side="left", padx=6)
        _es_doldur()

    ttk.Label(filtre, text="Maliyet:").pack(side="left", padx=(10, 0))
    yontem = ttk.Combobox(filtre, values=list(MALIYET_YONTEMLERI_RAPOR), state="readonly", width=22)
    yontem.set("FIFO")
    yontem.pack(side="left", padx=4)

    ozet = ttk.Label(app.icerik, text="", font=("Segoe UI", 10, "bold"))
    ozet.pack(anchor="w", pady=4)

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True)
    kolon_idler = [c[0] for c in kolonlar]
    baslik_map = {c[0]: c[1] for c in kolonlar}
    tablo = ttk.Treeview(govde, columns=kolon_idler, show="headings", selectmode="browse")
    for kid, baslik_k, w, anc in kolonlar:
        tablo.heading(kid, text=baslik_k)
        tablo.column(kid, width=w, anchor=anc)
    sy = ttk.Scrollbar(govde, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=sy.set)
    tablo.pack(side="left", fill="both", expand=True)
    sy.pack(side="right", fill="y")

    durum = {"istek": 0, "son": None}
    _liste_filtre: dict = {}
    _ham_satirlar: list = []

    def _gorunumu_uygula():
        from liste_filtre_ui import basliklari_filtre_isaretle

        for i in tablo.get_children():
            tablo.delete(i)
        for s in _ham_satirlar:
            vals = s.get("values") or ()
            atla = False
            for ki, kolon in enumerate(kolon_idler):
                secim = _liste_filtre.get(kolon)
                if isinstance(secim, set) and (ki >= len(vals) or vals[ki] not in secim):
                    atla = True
                    break
            if not atla:
                tablo.insert("", "end", values=vals)
        basliklari_filtre_isaretle(tablo, baslik_map, _liste_filtre)

    def yenile(_e=None):
        durum["istek"] += 1
        istek = durum["istek"]
        try:
            b = _tarih_oku(bas)
            e = _tarih_oku(bit)
            if b > e:
                raise ValueError("Başlangıç bitişten sonra olamaz.")
            kwargs = {"maliyet_yontemi": yontem.get() or "FIFO"}
            if karsilastirma and ob and oe and (ob.get() or "").strip() and (oe.get() or "").strip():
                kwargs["onceki_bas"] = _tarih_oku(ob)
                kwargs["onceki_bit"] = _tarih_oku(oe)
        except ValueError as exc:
            messagebox.showwarning("Tarih", str(exc), parent=app)
            return
        ozet.configure(text="Hesaplanıyor…")

        def _yukle():
            return hesapla_fn(b, e, **kwargs)

        def _ok(veri):
            if istek != durum["istek"] or not app.winfo_exists():
                return
            durum["son"] = veri
            for i in tablo.get_children():
                tablo.delete(i)
            doldur_fn(tablo, ozet, veri)
            _ham_satirlar.clear()
            for iid in tablo.get_children():
                _ham_satirlar.append({"values": tablo.item(iid, "values")})
            _gorunumu_uygula()

        def _err(exc):
            if istek == durum["istek"] and app.winfo_exists():
                ozet.configure(text="Güncel değil — hata")
                messagebox.showerror(baslik, str(exc), parent=app)

        from ui_bg import arka_planda

        arka_planda(app, _yukle, on_ok=_ok, on_err=_err)

    from liste_filtre_ui import treeview_filtre_bagla

    treeview_filtre_bagla(
        tablo,
        baslik_map,
        get_filtre_dict=lambda: _liste_filtre,
        set_filtre_dict=None,
        yenile_cb=_gorunumu_uygula,
        deger_listesi_cb=lambda: _ham_satirlar,
        parent=app,
        kolonlar=kolon_idler,
    )

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=6)
    ttk.Button(alt, text="Yenile", command=yenile).pack(side="right")
    for w in (bas, bit):
        w.bind("<FocusOut>", lambda _e: yenile())
        w.bind("<Return>", lambda _e: yenile())
    if ob and oe:
        for w in (ob, oe):
            w.bind("<FocusOut>", lambda _e: yenile())
            w.bind("<Return>", lambda _e: yenile())
    yontem.bind("<<ComboboxSelected>>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: _rapor_kabuk(app, baslik, aciklama, hesapla_fn, kolonlar, doldur_fn, karsilastirma=karsilastirma))


def r01_goster(app):
    def doldur(tablo, ozet, v):
        ozet.configure(
            text=(
                f"{v['baslangic'].strftime('%d.%m.%Y')}–{v['bitis'].strftime('%d.%m.%Y')}  |  "
                f"E {_para(v['E'])}  |  E/S {_yuz(v['oran_e_s'])}  |  E/B {_yuz(v['oran_e_b'])}  |  "
                f"Vergi öncesi yönetim sonucu K {_para(v['K'])}"
            )
        )
        for etiket, tutar in (
            ("Net satışlar (S)", v["S"]),
            ("Satılan mal maliyeti (M)", v["M"]),
            ("Brüt kâr (B)", v["B"]),
            ("Faaliyet giderleri (O)", v["O"]),
            ("Finansman giderleri (F)", v["F"]),
            ("Toplam dönem gideri (E)", v["E"]),
            ("Diğer faaliyet geliri (I)", v["I"]),
            ("Vergi öncesi yönetim sonucu (K)", v["K"]),
            ("Sınıflandırılmamış gider", v["siniflandirilmamis"]),
        ):
            tablo.insert("", "end", values=(etiket, _para(tutar)))
        if v.get("fark"):
            fy = v["fark"]["E_yuzde"]
            tablo.insert(
                "",
                "end",
                values=(
                    "Önceki eş döneme göre E farkı",
                    f"{_para(v['fark']['E'])}  ({_yuz(fy[0]) if fy[0] is not None else fy[1]})",
                ),
            )

    _rapor_kabuk(
        app,
        "R01 — Gider Genel Bakış",
        "Dönem giderinin işletme sonucuna etkisi. Net kâr etiketi kullanılmaz.",
        lambda b, e, **kw: GiderRaporService.r01_genel_bakis(b, e, **kw),
        (("kalem", "Kalem", 420, "w"), ("tutar", "Tutar", 220, "e")),
        doldur,
    )


def r02_goster(app):
    def doldur(tablo, ozet, v):
        ozet.configure(text=f"E {_para(v['E'])}  |  S {_para(v['S'])}  |  B {_para(v['B'])}")
        for s in v.get("dagilim_satirlari") or []:
            on = "  " if s["seviye"] == "alt" else ""
            tablo.insert(
                "",
                "end",
                values=(
                    on + s["ad"],
                    _para(s["net"]),
                    _yuz(s.get("pay_e")),
                    _yuz(s.get("pay_ana")) if s["seviye"] == "alt" else "",
                    _yuz(s.get("oran_s")),
                    _yuz(s.get("oran_b")),
                ),
            )

    _rapor_kabuk(
        app,
        "R02 — Gider Dağılımı ve Oranlar",
        "Ana/alt grup payları. Alt grup payı %100 genel giderin tamamı demek değildir.",
        lambda b, e, **kw: GiderRaporService.r02_dagilim(b, e, **kw),
        (
            ("ad", "Grup", 260, "w"),
            ("net", "Net gider", 110, "e"),
            ("pay_e", "E payı", 80, "e"),
            ("pay_ana", "Ana pay", 80, "e"),
            ("oran_s", "S oranı", 80, "e"),
            ("oran_b", "B oranı", 80, "e"),
        ),
        doldur,
    )


def r03_goster(app):
    def doldur(tablo, ozet, v):
        a, b = v["A"], v["B"]
        f = v["ozet_fark"]
        ey = f["E_yuzde"]
        ozet.configure(
            text=(
                f"A {a['baslangic'].strftime('%d.%m.%Y')}–{a['bitis'].strftime('%d.%m.%Y')}  |  "
                f"B {b['baslangic'].strftime('%d.%m.%Y')}–{b['bitis'].strftime('%d.%m.%Y')}  |  "
                f"E fark {_para(f['E'])} ({_yuz(ey[0]) if ey[0] is not None else ey[1]})  |  "
                f"E/S yp {_yuz(f['oran_e_s_yp'])}"
            )
        )
        for s in v["satirlar"]:
            y = _yuz(s["yuzde"]) if s["yuzde"] is not None else {
                "yeni": "Yeni gider",
                "yok": "—",
                "yeni_negatif": "Yeni negatif",
                "uygun_degil": "Uygun değil",
            }.get(s["yuzde_etiket"], "—")
            tablo.insert(
                "",
                "end",
                values=(s["ad"], _para(s["b"]), _para(s["a"]), _para(s["fark"]), y),
            )

    _rapor_kabuk(
        app,
        "R03 — Dönem Karşılaştırması",
        "B karşılaştırma, A ana dönem. Sıfır bazda sonsuz yüzde üretilmez.",
        lambda b, e, **kw: GiderRaporService.r03_karsilastirma(b, e, **kw),
        (
            ("ad", "Grup", 240, "w"),
            ("b", "B tutarı", 110, "e"),
            ("a", "A tutarı", 110, "e"),
            ("fark", "Fark", 110, "e"),
            ("yuzde", "Değişim", 100, "e"),
        ),
        doldur,
        karsilastirma=True,
    )


def r04_goster(app):
    def doldur(tablo, ozet, v):
        tb = v.get("toplam_butce")
        ozet.configure(
            text=f"Gerçekleşen E {_para(v['E'])}  |  Onaylı bütçe {_para(tb) if tb is not None else 'tanımlı değil'}"
        )
        for s in v.get("butce_satirlari") or []:
            if s["durum"] == "tanimli_degil":
                sapma, yuz = "Tanımlı değil", "—"
            elif s["durum"] == "plansiz":
                sapma, yuz = _para(s["sapma"]), "Plansız harcama"
            else:
                sapma, yuz = _para(s["sapma"]), _yuz(s["sapma_yuzde"])
            tablo.insert(
                "",
                "end",
                values=(
                    s["ad"],
                    _para(s["butce"]) if s["butce"] is not None else "—",
                    _para(s["gerceklesen"]),
                    sapma,
                    yuz,
                ),
            )

    _rapor_kabuk(
        app,
        "R04 — Bütçe ve Sapma",
        "Sapma = gerçekleşen − bütçe (pozitif = aşım). Rapor bütçe veya plan üretmez.",
        lambda b, e, **kw: GiderRaporService.r04_butce(b, e, **kw),
        (
            ("ad", "Grup", 240, "w"),
            ("butce", "Bütçe", 110, "e"),
            ("gercek", "Gerçekleşen", 110, "e"),
            ("sapma", "Sapma", 120, "e"),
            ("yuzde", "%", 120, "e"),
        ),
        doldur,
    )


def r05_goster(app):
    def doldur(tablo, ozet, v):
        ozet.configure(
            text=(
                f"Dönem gideri (net) {_para(v['donem_gider_net'])}  |  "
                f"Açık borç (brüt) {_para(v['acik_borc_brut'])}  |  "
                f"Rapor tarihi {v['rapor_tarihi'].strftime('%d.%m.%Y')}"
            )
        )
        etiket = {
            "gecikmis": "Gecikmiş",
            "bugun": "Bugün",
            "1_7": "1–7 gün",
            "8_30": "8–30 gün",
            "31_90": "31–90 gün",
            "90_plus": "90+ gün",
            "bilinmeyen": "Vade bilinmeyen",
        }
        for kova, liste in (v.get("vade_kovalar") or {}).items():
            for k in liste:
                tablo.insert(
                    "",
                    "end",
                    values=(
                        etiket.get(kova, kova),
                        k["belge_no"],
                        k["cari"],
                        k["vade"].strftime("%d.%m.%Y") if k.get("vade") else "—",
                        _para(k["kalan"]),
                    ),
                )

    _rapor_kabuk(
        app,
        "R05 — Ödeme ve Vade",
        "Dönem gideri, açık borç ve vade ayrı ölçülerdir; birbirine eşit zorlanmaz.",
        lambda b, e, **kw: GiderRaporService.r05_odeme_vade(b, e, **kw),
        (
            ("kova", "Kova", 110, "w"),
            ("belge", "Belge", 110, "w"),
            ("cari", "Cari", 260, "w"),
            ("vade", "Vade", 90, "w"),
            ("kalan", "Kalan", 110, "e"),
        ),
        doldur,
    )


def r06_goster(app):
    def doldur(tablo, ozet, v):
        f = v["finansman"]
        ozet.configure(
            text=(
                f"F {_para(f['toplam_f'])}  |  Faiz {_para(f['faiz'])}  |  "
                f"Masraf {_para(f['masraf'])}  |  POS {_para(f['pos'])}  |  "
                f"Efektif oran: {_yuz(f['pos_efektif_oran']) if f['pos_efektif_oran'] is not None else f['pos_efektif_neden']}"
            )
        )
        for s in f.get("detay") or []:
            tablo.insert(
                "",
                "end",
                values=(
                    s.get("belge_no"),
                    s.get("ana_grup_ad"),
                    s.get("tarih").strftime("%d.%m.%Y") if s.get("tarih") else "",
                    _para(s["net"]),
                    s.get("sonuc_yeri"),
                ),
            )

    _rapor_kabuk(
        app,
        "R06 — Finansman ve POS",
        "İnceleme görünümü F'ye ikinci kez eklemez. Rapor faiz tahakkuku üretmez.",
        lambda b, e, **kw: GiderRaporService.r06_finansman_pos(b, e, **kw),
        (
            ("belge", "Belge", 120, "w"),
            ("grup", "Grup", 200, "w"),
            ("tarih", "Tarih", 90, "w"),
            ("net", "Net", 110, "e"),
            ("yer", "Yer", 50, "c"),
        ),
        doldur,
    )


def r07_goster(app):
    def doldur(tablo, ozet, v):
        b = v["basabas"]
        notu = " (kısmi senaryo)" if b["kismi"] else ""
        ozet.configure(
            text=(
                f"Katkı oranı {_yuz(b['t'])}  |  Faaliyet eşiği {_para(b['faaliyet_esik'])}  |  "
                f"Finansman dahil {_para(b['finansman_dahil_esik'])}{notu}"
            )
        )
        for etiket, val in (
            ("Doğrulanmış sabit faaliyet", b["sabit"]),
            ("Değişken faaliyet", b["degisken_faaliyet"]),
            ("Belirsiz davranış", b["belirsiz"]),
            ("Değişken toplam V (M + değişken)", b["V"]),
            ("Katkı tutarı T", b["T"]),
            ("Faaliyet başa baş satışı", b["faaliyet_esik"]),
            ("Finansman dahil başa baş", b["finansman_dahil_esik"]),
            ("Güvenlik payı", b["guvenlik_payi"]),
            ("Güvenlik oranı", b["guvenlik_oran"]),
        ):
            tablo.insert(
                "",
                "end",
                values=(etiket, _yuz(val) if "oran" in etiket.lower() or etiket.startswith("Katkı oranı") else _para(val)),
            )
        if b["neden"]:
            tablo.insert("", "end", values=("Açıklama", b["neden"]))

    _rapor_kabuk(
        app,
        "R07 — Sabit Gider ve Başa Baş",
        "Belirsiz sınıf kesin başa başa zorlanmaz. Resmî bütçe/fiyat değişmez.",
        lambda b, e, **kw: GiderRaporService.r07_basabas(b, e, **kw),
        (("kalem", "Kalem", 360, "w"), ("deger", "Değer", 200, "e")),
        doldur,
    )


def r08_goster(app):
    def doldur(tablo, ozet, v):
        k = v["kontrol"]
        ozet.configure(
            text=(
                f"Kaynak {_para(k['kaynak_toplam'])} = rapor {_para(k['rapor_toplam'])}  |  "
                f"Sınıflandırılmamış {_para(k['siniflandirilmamis'])} "
                f"({k['siniflandirilmamis_adet']} satır)  |  "
                f"Mükerrer aday grup {len(k['mukerrer_aday'])}"
            )
        )
        for s in v["satirlar"]:
            tablo.insert(
                "",
                "end",
                values=(
                    s.get("belge_no"),
                    s.get("tarih").strftime("%d.%m.%Y") if s.get("tarih") else "",
                    s.get("ana_grup_ad"),
                    s.get("hizmet_adi") or s.get("cari_ad"),
                    _para(s["net"]),
                    "Evet" if s.get("siniflandirilmamis") else "",
                    s.get("kaynak"),
                ),
            )

    _rapor_kabuk(
        app,
        "R08 — Gider Detayı ve Belge Kontrolü",
        "Kaynak–rapor mutabakatı. Benzerlik otomatik silme değildir.",
        lambda b, e, **kw: GiderRaporService.r08_belge_kontrol(b, e, **kw),
        (
            ("belge", "Belge", 110, "w"),
            ("tarih", "Tarih", 90, "w"),
            ("grup", "Grup", 160, "w"),
            ("kart", "Kart / açıklama", 220, "w"),
            ("net", "Net", 100, "e"),
            ("sinif", "Sınıfsız", 70, "c"),
            ("kaynak", "Kaynak", 100, "w"),
        ),
        doldur,
    )
