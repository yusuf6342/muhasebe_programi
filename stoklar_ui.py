"""Stoklar hub — kurumsal sarı/lacivert kartlar, özet ve alt ekranlar."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from satis_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    HubKart,
    IKINCIL,
    LACIVERT,
    SARI,
    font,
    hub_ust_baslik,
    stil_uygula,
    tk_buton,
    treeview_stil,
)

STOKLAR_HUB_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("STOK KARTLARI / LİSTE", "Arama, filtre, bakiye ve stok kartı işlemleri", "liste"),
    ("STOK GRUBU YÖNETİMİ", "Ana / Tali / Alt grup ağacı ve toplu taşıma", "grup"),
    ("TOPLU GRUP EŞLEŞTİRME", "Çoklu stok seçimi, ön izleme ve güvenli atama", "toplu_grup"),
    ("STOK GİRİŞ", "Manuel stok giriş fişi", "giris"),
    ("DEPOLAR", "Depo kartları ve depo bakiyeleri", "depo"),
    ("DEPO TRANSFERLERİ", "Kaynak depodan hedef depoya aktarım", "transfer"),
    ("STOK SAYIMI", "Sayım, fark önizleme ve düzeltme fişi", "sayim"),
    ("BARKOD / BİRİM", "Barkod basımı ve birim dönüştürücü", "barkod"),
    ("FİYAT VE MALİYET", "Toplu fiyat güncelleme", "fiyat"),
    ("STOK BİRLEŞTİR", "Kaynak stoğu hedefe güvenli aktarma", "birlestir"),
    ("STOK PAKET", "Paket tanımlama ve üretim", "paket"),
    ("EXCEL AKTARIM", "İçe/dışa aktarma ve şablonlar", "excel"),
    ("RAPORLAR", "Bakiye, hareket, maliyet ve kritik stok", "rapor"),
)

RAPOR_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("STOK ENVANTER", "Depo/stok bazlı miktar ve maliyet", "envanter"),
    ("STOK HAREKET", "Giriş/çıkış hareket defteri", "hareket"),
    ("KAR / ZARAR", "Stok kar-zarar analizi", "kar"),
    ("SATILMAYAN ÜRÜNLER", "Hareketsiz / satılmayan stoklar", "satilmayan"),
    ("STOK DEVİR HIZI", "Devir hızı analizi", "devir"),
    ("KRİTİK VE EKSİ STOK", "Sıfır ve negatif bakiyeler", "kritik"),
    ("GRUP ÖZETİ", "Ana → Tali → Alt grup miktar ve değer", "grup"),
    ("FİYATLI STOK EKSTRESİ", "Devir, cari, fiyat ve maliyet ekstresi", "fiyatli_ekstre"),
)

_SIMGELER = ("◎", "▤", "☰", "▸", "⇄", "▣", "◉", "▦", "◇", "◆", "○")


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("stoklar")
        return
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        if anahtar == "stoklar":
            dugme.configure(style="SeciliMenu.TButton")
        elif anahtar == "hizli_satis":
            dugme.configure(style="HizliSatisMenu.TButton")
        else:
            dugme.configure(style="Menu.TButton")


def _nav(app, komut: Callable):
    nav = getattr(app, "nav_ac", None)
    if callable(nav):
        nav(komut)
    else:
        komut()


def _para(tutar) -> str:
    try:
        from ana_panel_tema import para_tr

        return para_tr(tutar)
    except Exception:
        return f"{float(tutar or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(d) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _ozet_serit(parent, ozet: dict, app=None):
    serit = tk.Frame(parent, bg=ACIK_BG)
    serit.pack(fill="x", padx=16, pady=(8, 0))
    kartlar = (
        ("Toplam maliyet", _para(ozet.get("toplam_maliyet", 0)), False),
        ("Kritik (sıfır)", ozet.get("kritik_stok", 0), True),
        ("Eksi stok", ozet.get("eksi_stok", 0), True),
        ("Hareketsiz (90g)", ozet.get("hareketsiz_stok", 0), True),
        ("Bugün giriş", _para(ozet.get("bugun_giris", 0)), False),
        ("Bugün çıkış", _para(ozet.get("bugun_cikis", 0)), False),
        ("Aktif kart", ozet.get("aktif_kart", 0), False),
        ("Depo", ozet.get("depo_adet", 0), False),
    )
    for i, (baslik, deger, uyari) in enumerate(kartlar):
        serit.columnconfigure(i, weight=1, uniform="stok_ozet")
        kutu = tk.Frame(serit, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        kutu.grid(row=0, column=i, sticky="nsew", padx=3, pady=4)
        tk.Label(
            kutu, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(8, root=app), anchor="w"
        ).pack(anchor="w", padx=8, pady=(6, 0))
        uyari_aktif = uyari and str(deger) not in ("0", "0,00")
        tk.Label(
            kutu,
            text=str(deger),
            bg=BEYAZ,
            fg=SARI if uyari_aktif else LACIVERT,
            font=font(13, "bold", app),
            anchor="w",
        ).pack(anchor="w", padx=8, pady=(0, 8))


def _kart_izgara(app, parent, kartlar, komut_haritasi, *, sutun: int = 2):
    ızgara = tk.Frame(parent, bg=ACIK_BG)
    ızgara.pack(fill="both", expand=True, padx=16, pady=16)
    for c in range(sutun):
        ızgara.columnconfigure(c, weight=1, uniform="stok_kart")
    for i, (baslik, aciklama, anahtar) in enumerate(kartlar):
        komut = komut_haritasi.get(anahtar)
        if komut is None:
            continue
        r, c = divmod(i, sutun)
        HubKart(
            ızgara,
            baslik=baslik,
            aciklama=aciklama,
            komut=lambda fn=komut: _nav(app, fn),
            simge=_SIMGELER[i % len(_SIMGELER)],
        ).grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
        ızgara.rowconfigure(r, weight=1, minsize=100)


def _hub_komutlar(app) -> dict[str, Callable]:
    def excel():
        from excel_aktarim_ui import excel_aktarim_hub_goster

        excel_aktarim_hub_goster(
            app,
            modul="stok",
            baslik="STOK — EXCEL VERİ AKTARIM",
            geri_fn=lambda: stoklar_hub_goster(app),
        )

    def giris():
        # Listeye git; kullanıcı satır seçip Stok Girişi kullanır
        app.stok_kartlari_goster()
        messagebox.showinfo(
            "Stok Giriş",
            "Listeden stok seçip alt araç çubuğundaki «Stok Girişi» ile giriş yapın.",
            parent=app,
        )

    return {
        "liste": app.stok_kartlari_goster,
        "grup": lambda: __import__("stok_grup_ui", fromlist=["stok_grup_yonetimi_goster"]).stok_grup_yonetimi_goster(app),
        "toplu_grup": lambda: __import__(
            "stok_grup_toplu_ui", fromlist=["stok_grup_toplu_eslestirme_goster"]
        ).stok_grup_toplu_eslestirme_goster(app),
        "giris": giris,
        "depo": lambda: depolar_goster(app),
        "transfer": app.depo_transfer_fisi_goster,
        "sayim": lambda: stok_sayim_goster(app),
        "barkod": app.stok_barkod_basimi_goster,
        "fiyat": app.toplu_fiyat_degisikligi_goster,
        "birlestir": app.stok_birlestir_goster,
        "paket": app.stok_paket_tanimlama_goster,
        "excel": excel,
        "rapor": lambda: stoklar_raporlar_hub_goster(app),
    }


def stoklar_hub_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok,
        baslik="STOKLAR",
        alt_baslik="Kart, depo, transfer, sayım, fiyat, birleştirme ve raporlar",
        app=app,
        geri_komut=lambda: app.sayfa_goster("giris"),
        geri_metin="Ana Menüye Dön",
    )
    ozet = {}
    try:
        from database.stok_hub_service import StokHubService

        ozet = StokHubService.ozet_kartlar()
    except Exception:
        ozet = {}
    _ozet_serit(kok, ozet, app=app)
    _kart_izgara(app, kok, STOKLAR_HUB_KARTLARI, _hub_komutlar(app), sutun=2)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stoklar_hub_goster(app))


def stoklar_raporlar_hub_goster(app) -> None:
    from fiyatli_stok_ekstresi_ui import fiyatli_stok_ekstresi_goster
    from stok_rapor_ui import (
        rapor_devir,
        rapor_envanter,
        rapor_hareket,
        rapor_kar_zarar,
        rapor_satilmayan,
    )

    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok,
        baslik="STOK RAPORLARI",
        alt_baslik="Envanter, hareket, maliyet ve kritik stok kontrolleri",
        app=app,
        geri_komut=lambda: stoklar_hub_goster(app),
        geri_metin="← Stoklar",
    )
    komutlar = {
        "envanter": lambda: rapor_envanter(app),
        "hareket": lambda: rapor_hareket(app),
        "kar": lambda: rapor_kar_zarar(app),
        "satilmayan": lambda: rapor_satilmayan(app),
        "devir": lambda: rapor_devir(app),
        "kritik": lambda: kritik_eksi_stok_raporu(app),
        "grup": lambda: grup_ozet_raporu(app),
        "fiyatli_ekstre": lambda: fiyatli_stok_ekstresi_goster(app),
    }
    _kart_izgara(app, kok, RAPOR_KARTLARI, komutlar, sutun=2)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stoklar_raporlar_hub_goster(app))


def _liste_ust(app, baslik, alt, geri):
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=geri, geri_metin="← Stoklar"
    )
    return kok


def depolar_goster(app) -> None:
    from database.stok_service import StokService
    from sqlalchemy import func, select
    from database.database import get_session
    from database.models.stok import StokLotu

    kok = _liste_ust(
        app,
        "DEPOLAR",
        "Aktif depolar ve lot bazlı toplam miktar / maliyet",
        lambda: stoklar_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(
        cerceve, columns=("ad", "miktar", "maliyet", "kalem"), show="headings"
    )
    treeview_stil(tablo)
    for k, b, w in (
        ("ad", "Depo", 200),
        ("miktar", "Toplam Miktar", 120),
        ("maliyet", "FIFO Değer", 120),
        ("kalem", "Stok Kalemi", 100),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        with get_session() as session:
            for depo in StokService.depolar():
                miktar, maliyet, kalem = session.execute(
                    select(
                        func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                        func.coalesce(
                            func.sum(StokLotu.kalan_miktar * StokLotu.birim_maliyet), 0
                        ),
                        func.count(func.distinct(StokLotu.stok_id)),
                    ).where(StokLotu.depo_id == depo.id)
                ).one()
                tablo.insert(
                    "",
                    "end",
                    iid=str(depo.id),
                    values=(
                        depo.ad,
                        _para(miktar),
                        _para(maliyet),
                        int(kalem or 0),
                    ),
                )

    def yeni():
        ad = simpledialog.askstring("Yeni Depo", "Depo adı:", parent=app)
        if not ad:
            return
        try:
            StokService.depo_ekle(ad)
        except ValueError as e:
            messagebox.showerror("Depo", str(e), parent=app)
            return
        yenile()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Depo", yeni, rol="yeni").pack(side="left")
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: depolar_goster(app))


def stok_sayim_goster(app) -> None:
    from database.stok_sayim_service import StokSayimService
    from database.stok_service import StokService

    kok = _liste_ust(
        app,
        "STOK SAYIMI",
        "Depo seçin, sayılan miktarları girin; farklar onayda stoğa yansır",
        lambda: stoklar_hub_goster(app),
    )
    StokSayimService.schema_hazirla()

    ust = tk.Frame(kok, bg=ACIK_BG)
    ust.pack(fill="x", padx=16, pady=8)
    tk.Label(ust, text="Depo:", bg=ACIK_BG).pack(side="left")
    depolar = StokService.depolar()
    depo_map = {d.ad: d for d in depolar}
    depo_cb = ttk.Combobox(ust, values=list(depo_map.keys()), state="readonly", width=24)
    if depolar:
        depo_cb.set(depolar[0].ad)
    depo_cb.pack(side="left", padx=6)
    tk.Label(ust, text="Tarih:", bg=ACIK_BG).pack(side="left")
    tarih_e = ttk.Entry(ust, width=12)
    tarih_e.insert(0, date.today().strftime("%d.%m.%Y"))
    tarih_e.pack(side="left", padx=4)

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(
        cerceve,
        columns=("kod", "ad", "sistem", "sayilan", "fark"),
        show="headings",
        selectmode="browse",
    )
    treeview_stil(tablo)
    for k, b, w in (
        ("kod", "Kod", 100),
        ("ad", "Ürün", 220),
        ("sistem", "Sistem", 90),
        ("sayilan", "Sayılan", 90),
        ("fark", "Fark", 90),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    satir_veri: dict[str, dict] = {}

    def yukle():
        satir_veri.clear()
        for i in tablo.get_children():
            tablo.delete(i)
        depo = depo_map.get(depo_cb.get())
        if not depo:
            return
        for r in StokSayimService.depo_stok_listesi(depo.id):
            iid = str(r["stok_id"])
            satir_veri[iid] = {
                "stok_id": r["stok_id"],
                "sistem_miktar": r["sistem_miktar"],
                "sayilan_miktar": r["sistem_miktar"],
            }
            tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    r["urun_kodu"],
                    r["urun_adi"],
                    _para(r["sistem_miktar"]),
                    _para(r["sistem_miktar"]),
                    "0,00",
                ),
            )

    def sayilan_gir():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Satır seçin.", parent=app)
            return
        iid = sec[0]
        veri = satir_veri.get(iid)
        if not veri:
            return
        metin = simpledialog.askstring(
            "Sayılan Miktar",
            f"Sistem: {_para(veri['sistem_miktar'])}\nSayılan miktar:",
            parent=app,
            initialvalue=str(veri["sayilan_miktar"]),
        )
        if metin is None:
            return
        try:
            sayilan = Decimal(metin.replace(",", "."))
        except Exception:
            messagebox.showerror("Miktar", "Geçersiz sayı.", parent=app)
            return
        veri["sayilan_miktar"] = sayilan
        fark = sayilan - veri["sistem_miktar"]
        vals = list(tablo.item(iid, "values"))
        vals[3] = _para(sayilan)
        vals[4] = _para(fark)
        tablo.item(iid, values=vals)

    def onayla():
        depo = depo_map.get(depo_cb.get())
        if not depo:
            messagebox.showerror("Depo", "Depo seçin.", parent=app)
            return
        try:
            tarih = datetime.strptime(tarih_e.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY olmalı.", parent=app)
            return
        satirlar = list(satir_veri.values())
        farkli = [s for s in satirlar if s["sayilan_miktar"] != s["sistem_miktar"]]
        if not messagebox.askyesno(
            "Onay",
            f"{len(farkli)} satırda fark var. Sayım onaylanıp stok güncellensin mi?",
            parent=app,
        ):
            return
        try:
            fis_id = StokSayimService.kaydet_ve_onayla(depo.id, tarih, satirlar)
        except ValueError as e:
            messagebox.showerror("Sayım", str(e), parent=app)
            return
        messagebox.showinfo("Sayım", f"Sayım fişi kaydedildi (id={fis_id}).", parent=app)
        yukle()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Listeyi Yükle", yukle, rol="ara").pack(side="left")
    tk_buton(alt, "Sayılan Gir", sayilan_gir, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Onayla ve Uygula", onayla, rol="kaydet").pack(side="left", padx=6)

    # Önceki fişler
    onceki = ttk.LabelFrame(kok, text="Önceki sayım fişleri", padding=8)
    onceki.pack(fill="x", padx=16, pady=(0, 12))
    onceki_tablo = ttk.Treeview(
        onceki, columns=("no", "tarih", "depo", "durum", "satir"), show="headings", height=5
    )
    treeview_stil(onceki_tablo)
    for k, b, w in (
        ("no", "Fiş No", 110),
        ("tarih", "Tarih", 90),
        ("depo", "Depo", 120),
        ("durum", "Durum", 100),
        ("satir", "Satır", 60),
    ):
        onceki_tablo.heading(k, text=b)
        onceki_tablo.column(k, width=w)
    onceki_tablo.pack(fill="x")
    for r in StokSayimService.listele()[:30]:
        onceki_tablo.insert(
            "",
            "end",
            values=(r["fis_no"], _tarih(r["tarih"]), r["depo"], r["durum"], r["satir"]),
        )

    if depolar:
        yukle()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stok_sayim_goster(app))


def kritik_eksi_stok_raporu(app) -> None:
    from database.database import get_session
    from database.models.stok import StokKarti, StokLotu
    from sqlalchemy import func, select

    kok = _liste_ust(
        app,
        "KRİTİK VE EKSİ STOK",
        "Sıfır veya negatif bakiyeli aktif stok kartları",
        lambda: stoklar_raporlar_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(
        cerceve, columns=("kod", "ad", "birim", "miktar", "durum"), show="headings"
    )
    treeview_stil(tablo)
    for k, b, w in (
        ("kod", "Kod", 110),
        ("ad", "Ad", 260),
        ("birim", "Birim", 70),
        ("miktar", "Miktar", 100),
        ("durum", "Durum", 100),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True)

    with get_session() as session:
        miktarlar = {
            int(r[0]): Decimal(str(r[1] or 0))
            for r in session.execute(
                select(StokLotu.stok_id, func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).group_by(
                    StokLotu.stok_id
                )
            ).all()
        }
        stoklar = list(
            session.scalars(
                select(StokKarti).where(
                    StokKarti.aktif.is_(True), StokKarti.is_deleted.is_(False)
                )
            ).all()
        )
        for s in stoklar:
            m = miktarlar.get(int(s.id), Decimal("0"))
            if m > 0:
                continue
            tablo.insert(
                "",
                "end",
                values=(
                    s.stok_kodu,
                    s.stok_adi,
                    s.birim,
                    _para(m),
                    "EKSİ" if m < 0 else "SIFIR",
                ),
            )

def grup_ozet_raporu(app) -> None:
    """Ana → Tali → Alt grup bazlı stok adedi / miktar / FIFO özet."""
    from database.stok_grup_service import StokGrupService

    kok = _liste_ust(
        app,
        "GRUP ÖZETİ",
        "Ana Grup → Tali Grup → Alt Grup miktar ve değer",
        lambda: stoklar_raporlar_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(
        cerceve,
        columns=("ana", "tali", "alt", "yol", "stok", "miktar", "deger"),
        show="headings",
    )
    treeview_stil(tablo)
    for k, b, w in (
        ("ana", "Ana Grup", 140),
        ("tali", "Tali Grup", 140),
        ("alt", "Alt Grup", 140),
        ("yol", "Tam Yol", 220),
        ("stok", "Stok Adedi", 90),
        ("miktar", "Miktar", 100),
        ("deger", "FIFO Değer", 120),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True)
    try:
        for s in StokGrupService.ozet_rapor():
            tablo.insert(
                "",
                "end",
                values=(
                    s.get("ana"),
                    s.get("tali"),
                    s.get("alt"),
                    s.get("yol"),
                    s.get("stok_adet"),
                    s.get("miktar"),
                    _para(s.get("fifo_deger")),
                ),
            )
    except Exception as exc:
        messagebox.showerror("Grup Özeti", str(exc), parent=app)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: grup_ozet_raporu(app))
