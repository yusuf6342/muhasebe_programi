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
    ("STOK KARTI", "Boş yeni stok kartı; ada göre arayıp mevcut kartı da açabilirsiniz", "kart"),
    ("STOK UYARILARI / SİPARİŞ İHTİYACI", "Tükenen ve kritik ürünler, öneri ve taslak sipariş", "uyari"),
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
)

RAPOR_GRUPLARI: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Stok Listeleri", (
        ("STOK LİSTESİ", "Arama, filtre, bakiye; seçilen stok kendi kartında açılır", "liste"),
        ("STOK HAREKET DEFTERİ", "Tarih aralığında giriş / çıkış hareketleri", "hareket"),
        ("STOK ENVANTERİ", "Seçilen tarihteki miktar ve maliyet (değerleme)", "envanter"),
    )),
    ("Durum ve Hareket", (
        ("STOK DURUMU / KULLANILABİLİR", "Mevcut, bekleyen alış / satış siparişi, depo ve firma toplamı", "durum"),
        ("ÜRÜN HAREKET EKSTRESİ", "Dönem başı, giriş, çıkış, kalan, fiyat ve kaynak evrak", "fiyatli_ekstre"),
        ("DEPO TRANSFER TAKİBİ", "Gönderilen, alınan, yoldaki miktar ve bekleme günü", "transfer"),
    )),
    ("Stok Planlama", (
        ("KRİTİK VE TÜKENEN STOK", "Minimum altı, sıfır ve negatif; satış hızı ve stoksuz kalma geçmişi", "kritik"),
        ("YENİDEN SİPARİŞ ÖNERİSİ", "Satış hızı, hedef gün ve tedarik süresi varsayımıyla öneri", "siparis"),
        ("YAVAŞ / SATILMAYAN STOK", "Son satıştan beri gün, dönem satışı, yeni alım ayrımı", "satilmayan"),
    )),
    ("Değer ve Verimlilik", (
        ("GRUP BAZLI STOK DEĞERİ", "Ana / Tali / Alt grup miktar ve maliyet", "grup"),
        ("STOK YAŞLANDIRMA", "Katman giriş tarihine göre 0–30 … 365+ gün", "yaslandirma"),
        ("DEVİR HIZI / YETERLİLİK", "Günlük hız, yeterlilik günü ve devir oranı", "devir"),
        ("STOK YATIRIM VERİMLİLİĞİ", "Ürün / grup bazında brüt kâr, GMROI, devir ve stokta kalma", "verimlilik"),
        ("STOK KÂR / ZARAR", "Ürün bazında satış, maliyet ve kâr", "kar"),
    )),
    ("Sayım ve Kontrol", (
        ("SAYIM FARKLARI", "Sistem / sayılan farkı, maliyet etkisi ve düzeltme hareketi", "sayim_fark"),
        ("STOK TUTARLILIK KONTROLÜ", "Salt okunur: negatif, maliyet, birim, barkod, evrak–hareket uyumu", "tutarlilik"),
    )),
)

RAPOR_KARTLARI: tuple[tuple[str, str, str], ...] = tuple(k for _g, kartlar in RAPOR_GRUPLARI for k in kartlar)

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
        "kart": app.yeni_stok,
        "liste": app.stok_kartlari_goster,
        "uyari": lambda: __import__("stok_uyari_ui", fromlist=["stok_uyari_goster"]).stok_uyari_goster(app),
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
    from satin_alma_ui import AcilirMenuGrubu, _bolum_basligi, _tekerlegi_bagla
    from ui_pencere import kaydirilabilir_govde

    govde = kaydirilabilir_govde(kok, bg=ACIK_BG)
    app.stok_raporlari_grubu = AcilirMenuGrubu(
        app, govde, "STOK RAPORLARI", RAPOR_KARTLARI, _rapor_komutlar(app), alt_gruplar=RAPOR_GRUPLARI
    )
    _bolum_basligi(app, govde, "Stok İşlemleri")
    _kart_izgara(app, govde, _hub_kartlari_sayili(), _hub_komutlar(app), sutun=2)
    _tekerlegi_bagla(govde)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stoklar_hub_goster(app))


def _hub_kartlari_sayili() -> tuple[tuple[str, str, str], ...]:
    try:
        from database.stok_uyari_service import StokUyariService

        sayi = StokUyariService.aktif_sayisi()
    except Exception:
        return STOKLAR_HUB_KARTLARI
    if not sayi.get("toplam"):
        return STOKLAR_HUB_KARTLARI
    ek = (f"Etkin ihtiyaç: {sayi['toplam']} (tükenen {sayi['tukenen']}, kritik {sayi['kritik']}, "
          f"stok girişi yok {sayi.get('giris_yok', 0)})")
    return tuple(
        (f"{b} ({sayi['toplam']})", ek, a) if a == "uyari" else (b, ac, a)
        for b, ac, a in STOKLAR_HUB_KARTLARI
    )


def _rapor_komutlar(app) -> dict[str, Callable]:
    import stok_raporlari_ui as sr
    from fiyatli_stok_ekstresi_ui import fiyatli_stok_ekstresi_goster
    from satin_alma_rapor_ui import yeniden_siparis_onerisi_goster
    from stok_rapor_ui import rapor_hareket, rapor_kar_zarar

    return {
        "liste": app.stok_kartlari_goster,
        "hareket": lambda: rapor_hareket(app),
        "envanter": lambda: sr.degerleme_goster(app),
        "durum": lambda: sr.stok_durumu_goster(app),
        "fiyatli_ekstre": lambda: fiyatli_stok_ekstresi_goster(app),
        "transfer": lambda: sr.transfer_takibi_goster(app),
        "kritik": lambda: sr.kritik_tukenen_goster(app),
        "siparis": lambda: yeniden_siparis_onerisi_goster(app, ust=sr._ust),
        "satilmayan": lambda: sr.yavas_satilmayan_goster(app),
        "grup": lambda: sr.degerleme_goster(app, sekme="gruplar"),
        "yaslandirma": lambda: sr.yaslandirma_goster(app),
        "devir": lambda: sr.devir_yeterlilik_goster(app),
        "verimlilik": lambda: sr.yatirim_verimliligi_goster(app),
        "kar": lambda: rapor_kar_zarar(app),
        "sayim_fark": lambda: sr.sayim_farklari_goster(app),
        "tutarlilik": lambda: sr.tutarlilik_kontrolu_goster(app),
    }


def stoklar_raporlar_hub_goster(app) -> None:
    from satin_alma_ui import _bolum_basligi, _tekerlegi_bagla
    from satin_alma_ui import _kart_izgara as _grup_izgara
    from ui_pencere import kaydirilabilir_govde

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
        alt_baslik="Stok listeleri, durum ve hareket, planlama, değer ve verimlilik, sayım ve kontrol",
        app=app,
        geri_komut=lambda: stoklar_hub_goster(app),
        geri_metin="← Stoklar",
    )
    govde = kaydirilabilir_govde(kok, bg=ACIK_BG)
    komutlar = _rapor_komutlar(app)
    for grup, kartlar in RAPOR_GRUPLARI:
        _bolum_basligi(app, govde, grup)
        _grup_izgara(app, govde, kartlar, komutlar, sutun=3, min_yukseklik=86, pady=6)
    _tekerlegi_bagla(govde)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stoklar_raporlar_hub_goster(app))


def _liste_ust(app, baslik, alt, geri, geri_metin: str = "← Stoklar"):
    temizle = getattr(app, "_icerigi_temizle", None)
    if callable(temizle):
        temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=geri, geri_metin=geri_metin
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
    from sube_ui import sube_secim_hazirla

    tk.Label(ust, text="Şube:", bg=ACIK_BG).pack(side="left")
    sube_cb, sube_map = sube_secim_hazirla(ust)
    sube_cb.pack(side="left", padx=6)
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
        columns=("kod", "ad", "sistem", "sayilan", "fark", "maliyet", "kaynak"),
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
        ("maliyet", "Fazla Birim Maliyet", 120),
        ("kaynak", "Maliyet Kaynağı", 200),
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
                    "",
                    "",
                ),
            )

    def fazla_maliyeti_sor(iid: str, veri: dict) -> bool:
        """Sayım fazlasında maliyet + kaynağı belirler; iptalde False (sessiz 0 maliyet yok)."""
        from database.satis_siparisi_service import decimal as sayi_coz
        from database.stok_sayim_service import MALIYET_KULLANICI

        depo = depo_map.get(depo_cb.get())
        oneri = StokSayimService.maliyet_onerisi(veri["stok_id"], depo.id if depo else None)
        if oneri:
            bilgi = (f"Önerilen birim maliyet: {_para(oneri['birim_maliyet'])}\n"
                     f"Kaynak: {oneri['kaynak']} — {oneri['aciklama']}\n\n"
                     "Öneriyi kabul edin veya başka bir maliyet girin:")
            ilk = f"{oneri['birim_maliyet']:f}"
        else:
            bilgi = ("Bu ürün için geçerli maliyet bulunamadı (lot / alış yok).\n"
                     "Sayım fazlası için birim maliyet girmeniz zorunludur:")
            ilk = ""
        while True:
            metin = simpledialog.askstring("Sayım Fazlası Maliyeti", bilgi, parent=app, initialvalue=ilk)
            if metin is None:
                return False
            try:
                maliyet = sayi_coz(metin, "Birim maliyet")
            except ValueError as hata:
                messagebox.showerror("Maliyet", str(hata), parent=app)
                continue
            if maliyet <= 0:
                messagebox.showerror("Maliyet", "Sayım fazlası 0 maliyetle stoğa alınamaz.", parent=app)
                continue
            break
        if oneri and maliyet == oneri["birim_maliyet"]:
            kaynak, etiket = oneri["kaynak"], f"{oneri['kaynak']} — {oneri['aciklama']}"
        else:
            kaynak = etiket = MALIYET_KULLANICI
        veri["birim_maliyet"] = maliyet
        veri["maliyet_kaynagi"] = kaynak
        vals = list(tablo.item(iid, "values"))
        vals[5] = _para(maliyet)
        vals[6] = etiket
        tablo.item(iid, values=vals)
        return True

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
        if fark <= 0:
            veri.pop("birim_maliyet", None)
            veri.pop("maliyet_kaynagi", None)
            vals[5] = vals[6] = ""
        tablo.item(iid, values=vals)
        if fark > 0:
            fazla_maliyeti_sor(iid, veri)

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
        for iid, s in satir_veri.items():
            if s["sayilan_miktar"] > s["sistem_miktar"] and not s.get("birim_maliyet"):
                tablo.selection_set(iid)
                tablo.see(iid)
                if not fazla_maliyeti_sor(iid, s):
                    messagebox.showwarning(
                        "Sayım", "Sayım fazlası satırlarında birim maliyet belirlenmeden onaylanamaz.", parent=app
                    )
                    return
        if not messagebox.askyesno(
            "Onay",
            f"{len(farkli)} satırda fark var. Sayım onaylanıp stok güncellensin mi?",
            parent=app,
        ):
            return
        try:
            fis_id = StokSayimService.kaydet_ve_onayla(
                depo.id, tarih, satirlar, sube_id=sube_map.get(sube_cb.get())
            )
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
    from stok_raporlari_ui import kritik_tukenen_goster

    kritik_tukenen_goster(app)


def grup_ozet_raporu(app) -> None:
    from stok_raporlari_ui import degerleme_goster

    degerleme_goster(app, sekme="gruplar")
