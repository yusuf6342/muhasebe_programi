"""Satın Alma hub — kurumsal sarı/lacivert kartlar, özet ve alt ekranlar."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Callable

from satis_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    HubKart,
    IKINCIL,
    LACIVERT,
    LACIVERT_HOVER,
    METIN,
    SARI,
    font,
    hub_ust_baslik,
    resolve_ui_font,
    stil_uygula,
    tk_buton,
    treeview_stil,
)

SATIN_ALMA_HUB_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("TEDARİKÇİ KARTLARI", "Cari, iletişim, risk, vade ve alış geçmişi", "tedarikci"),
    ("SATIN ALMA TALEPLERİ", "İç ihtiyaç ve yeniden sipariş talepleri", "talep"),
    ("TEDARİKÇİ TEKLİFLERİ", "Çoklu tedarikçi fiyat ve şart karşılaştırması", "teklif"),
    ("SATIN ALMA SİPARİŞLERİ", "Sipariş, termin ve kısmi teslim takibi", "siparis"),
    ("ALIŞ İRSALİYELERİ", "Mal kabul ve faturalanmamış irsaliyeler", "irsaliye"),
    ("ALIŞ FATURALARI", "Borç, stok, maliyet, KDV ve ödeme", "fatura"),
    ("ALIŞ İADELERİ", "Kaynak belgeye bağlı iade faturaları", "iade"),
    ("MASRAF DAĞITIMI", "Nakliye ve diğer giderleri maliyete dağıt", "masraf"),
    ("TEDARİKÇİ FİYAT LİSTELERİ", "Güncel alış fiyatı ve iskonto koşulları", "fiyat"),
    ("RAPORLAR VE KONTROL", "Teslimat, borç, maliyet ve performans", "rapor"),
    ("PDF / E-FATURA AKTARIM", "PDF/OCR ve gelen e-faturalar", "belge"),
    ("EXCEL VERİ AKTARIM", "Tedarikçi cari ve virman aktarımı", "excel"),
)

RAPOR_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("TEDARİKÇİ BAKİYE DURUM", "Ortalama vadeli tedarikçi bakiyeleri", "bakiye"),
    ("TEDARİKÇİ EKSTRESİ", "Valörlü / ağırlıklı ekstre", "ekstre"),
    ("STOK DETAYLI EKSTRE", "Stok satırlı tedarikçi ekstresi", "stok_ekstre"),
    ("ÖDEME VE TAHSİLAT", "Tarih aralıklı ödeme raporu", "odeme"),
    ("SATIN ALMA ÖZETİ", "Dönemsel alış özeti", "ozet"),
    ("AYLIK ALIŞ ANALİZİ", "Aylara göre alış tutarı ve fatura sayısı", "aylik"),
    ("STOK YENİLEME ÖNERİSİ", "Minimum stok altına düşen ürünler", "yenileme"),
    ("FATURALANMAMIŞ İRSALİYELER", "Mal kabulü yapılmış, faturası bekleyen", "bekleyen_irs"),
)

_SIMGELER = ("◎", "▤", "☰", "▸", "⇄", "▣", "◉", "▦", "◇", "◆", "○", "●")


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("satin_alma")
        return
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        if anahtar == "satin_alma":
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
        ("Bekleyen talep", ozet.get("bekleyen_talep", 0), False),
        ("Açık sipariş", ozet.get("acik_siparis", 0), False),
        ("Geciken teslim", ozet.get("geciken_siparis", 0), True),
        ("Faturalanmamış irs.", ozet.get("faturalanmamis_irsaliye", 0), True),
        ("Yaklaşan borç (7g)", ozet.get("yaklasan_borc", 0), True),
        ("Bu ay alış", _para(ozet.get("bu_ay_alis", 0)), False),
    )
    for i, (baslik, deger, uyari) in enumerate(kartlar):
        serit.columnconfigure(i, weight=1, uniform="ozet")
        kutu = tk.Frame(serit, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        kutu.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
        tk.Label(
            kutu, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(9, root=app), anchor="w"
        ).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(
            kutu,
            text=str(deger),
            bg=BEYAZ,
            fg=SARI if uyari and str(deger) not in ("0", "0,00") else LACIVERT,
            font=font(16, "bold", app),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(2, 10))
    return serit


def _kart_izgara(app, parent, kartlar, komut_haritasi: dict[str, Callable], *, sutun: int = 2):
    ızgara = tk.Frame(parent, bg=ACIK_BG)
    ızgara.pack(fill="both", expand=True, padx=16, pady=16)
    for c in range(sutun):
        ızgara.columnconfigure(c, weight=1, uniform="sa_kart")
    for i, (baslik, aciklama, anahtar) in enumerate(kartlar):
        komut = komut_haritasi.get(anahtar)
        if komut is None:
            continue
        r, c = divmod(i, sutun)
        kart = HubKart(
            ızgara,
            baslik=baslik,
            aciklama=aciklama,
            komut=lambda fn=komut: _nav(app, fn),
            simge=_SIMGELER[i % len(_SIMGELER)],
        )
        kart.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
        ızgara.rowconfigure(r, weight=1, minsize=110)


def _hub_komutlar(app) -> dict[str, Callable]:
    def belge():
        from fatura_belge_aktarim_ui import fatura_belge_aktarim_goster

        fatura_belge_aktarim_goster(
            app, yon="ALIS", geri_fn=lambda: satin_alma_hub_goster(app)
        )

    def excel():
        from excel_aktarim_ui import excel_aktarim_hub_goster

        excel_aktarim_hub_goster(
            app,
            modul="satin_alma",
            baslik="SATIN ALMA — EXCEL VERİ AKTARIM",
            geri_fn=lambda: satin_alma_hub_goster(app),
        )

    return {
        "tedarikci": app.tedarikciler_goster,
        "talep": lambda: satin_alma_talepleri_goster(app),
        "teklif": lambda: tedarikci_teklifleri_goster(app),
        "siparis": app.alis_siparisleri_goster,
        "irsaliye": app.alis_irsaliyeleri_goster,
        "fatura": app.alis_faturalari_goster,
        "iade": app.alis_iade_faturalari_goster,
        "masraf": lambda: masraf_dagitimi_goster(app),
        "fiyat": lambda: tedarikci_fiyat_listeleri_goster(app),
        "rapor": lambda: satin_alma_raporlar_hub_goster(app),
        "belge": belge,
        "excel": excel,
    }


def satin_alma_hub_goster(app) -> None:
    """Satın Alma ana hub — özet kartlar + menü."""
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
        baslik="SATIN ALMA",
        alt_baslik="Tedarikçi, talep, teklif, sipariş, irsaliye, fatura ve masraf",
        app=app,
        geri_komut=lambda: app.sayfa_goster("giris"),
        geri_metin="Ana Menüye Dön",
    )

    ozet = {}
    try:
        from database.satin_alma_hub_service import SatinAlmaHubService

        ozet = SatinAlmaHubService.ozet_kartlar()
    except Exception:
        ozet = {}
    _ozet_serit(kok, ozet, app=app)
    _kart_izgara(app, kok, SATIN_ALMA_HUB_KARTLARI, _hub_komutlar(app), sutun=2)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_hub_goster(app))


def satin_alma_raporlar_hub_goster(app) -> None:
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
        baslik="SATIN ALMA RAPORLARI",
        alt_baslik="Bakiye, ekstre, ödeme ve faturalanmamış irsaliye kontrolleri",
        app=app,
        geri_komut=lambda: satin_alma_hub_goster(app),
        geri_metin="← Satın Alma",
    )

    def bekleyen_irs():
        faturalanmamis_irsaliye_raporu_goster(app)

    komutlar = {
        "bakiye": app.rapor_tedarikci_bakiye_durum,
        "ekstre": app.rapor_tedarikci_ekstresi,
        "stok_ekstre": app.rapor_stok_detayli_tedarikci_ekstre,
        "odeme": app.rapor_tahsilat_odeme,
        "ozet": app.rapor_alis_ozeti,
        "aylik": getattr(app, "rapor_aylik_alis_analizi", app.rapor_alis_ozeti),
        "yenileme": getattr(app, "rapor_stok_yenileme_onerisi", app.rapor_alis_ozeti),
        "bekleyen_irs": bekleyen_irs,
    }
    _kart_izgara(app, kok, RAPOR_KARTLARI, komutlar, sutun=2)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_raporlar_hub_goster(app))


# --- Liste ekranları ---


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
        kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=geri, geri_metin="← Satın Alma"
    )
    return kok


def satin_alma_talepleri_goster(app) -> None:
    from database.satin_alma_talep_service import DURUMLAR, SatinAlmaTalepService

    kok = _liste_ust(
        app,
        "SATIN ALMA TALEPLERİ",
        "İç ihtiyaç talepleri; onay sonrası teklife veya siparişe aktarılır",
        lambda: satin_alma_hub_goster(app),
    )
    arac = tk.Frame(kok, bg=ACIK_BG)
    arac.pack(fill="x", padx=16, pady=8)
    tk.Label(arac, text="Durum:", bg=ACIK_BG, fg=LACIVERT).pack(side="left")
    durum = ttk.Combobox(arac, values=("Tümü",) + DURUMLAR, state="readonly", width=18)
    durum.set("Tümü")
    durum.pack(side="left", padx=6)

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("no", "tarih", "ihtiyac", "isteyen", "depo", "oncelik", "durum", "satir")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w in (
        ("no", "Talep No", 110),
        ("tarih", "Tarih", 90),
        ("ihtiyac", "İhtiyaç", 90),
        ("isteyen", "İsteyen", 140),
        ("depo", "Depo", 100),
        ("oncelik", "Öncelik", 80),
        ("durum", "Durum", 120),
        ("satir", "Satır", 60),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in SatinAlmaTalepService.listele(durum.get()):
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["talep_no"],
                    _tarih(r["talep_tarihi"]),
                    _tarih(r["ihtiyac_tarihi"]),
                    r["isteyen"],
                    r["depo"],
                    r["oncelik"],
                    r["durum"],
                    r["satir_adet"],
                ),
            )

    def yeni():
        dlg = SatinAlmaTalepDialog(app)
        app.wait_window(dlg)
        yenile()

    def duzenle():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Talep seçin.", parent=app)
            return
        dlg = SatinAlmaTalepDialog(app, talep_id=int(sec[0]))
        app.wait_window(dlg)
        yenile()

    def onaya_gonder():
        sec = tablo.selection()
        if not sec:
            return
        try:
            SatinAlmaTalepService.durum_degistir(int(sec[0]), "ONAY BEKLİYOR")
        except ValueError as e:
            messagebox.showerror("Durum", str(e), parent=app)
            return
        yenile()

    def onayla():
        sec = tablo.selection()
        if not sec:
            return
        try:
            SatinAlmaTalepService.durum_degistir(int(sec[0]), "ONAYLANDI")
        except ValueError as e:
            messagebox.showerror("Durum", str(e), parent=app)
            return
        yenile()

    def teklife():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Talep seçin.", parent=app)
            return
        from database.alis_siparisi_service import AlisSiparisiService
        from database.tedarikci_teklif_service import TedarikciTeklifService

        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        if not tedarikciler:
            messagebox.showerror("Teklif", "Aktif tedarikçi yok.", parent=app)
            return
        # İlk 3 tedarikçiye varsayılan (dialog ile seçim basit tutuldu)
        dlg = TedarikciSecDialog(app, tedarikciler)
        app.wait_window(dlg)
        if not dlg.result:
            return
        try:
            tid = TedarikciTeklifService.talepden_olustur(int(sec[0]), dlg.result)
            SatinAlmaTalepService.durum_degistir(int(sec[0]), "ONAYLANDI")
        except ValueError as e:
            messagebox.showerror("Teklif", str(e), parent=app)
            return
        messagebox.showinfo("Teklif", f"Teklif oluşturuldu (id={tid}).", parent=app)
        tedarikci_teklifleri_goster(app)

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni", yeni, rol="yeni").pack(side="left")
    tk_buton(alt, "Düzenle", duzenle, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Onaya Gönder", onaya_gonder, rol="ara").pack(side="left", padx=6)
    tk_buton(alt, "Onayla", onayla, rol="kaydet").pack(side="left", padx=6)
    tk_buton(alt, "Teklife Aktar", teklife, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    durum.bind("<<ComboboxSelected>>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_talepleri_goster(app))


def tedarikci_teklifleri_goster(app) -> None:
    from database.tedarikci_teklif_service import TedarikciTeklifService

    kok = _liste_ust(
        app,
        "TEDARİKÇİ TEKLİFLERİ",
        "Fiyat, vade, termin ve nakliye ile toplam edinme maliyeti karşılaştırması",
        lambda: satin_alma_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("no", "tarih", "talep", "durum", "satir", "aciklama")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w in (
        ("no", "Teklif No", 110),
        ("tarih", "Tarih", 90),
        ("talep", "Talep Id", 80),
        ("durum", "Durum", 140),
        ("satir", "Satır", 60),
        ("aciklama", "Açıklama", 240),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in TedarikciTeklifService.listele():
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["teklif_no"],
                    _tarih(r["teklif_tarihi"]),
                    r["talep_id"] or "",
                    r["durum"],
                    r["satir_adet"],
                    r["aciklama"],
                ),
            )

    def karsilastir():
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Teklif seçin.", parent=app)
            return
        TeklifKarsilastirmaDialog(app, int(sec[0]))
        yenile()

    def yeni():
        dlg = TedarikciTeklifDialog(app)
        app.wait_window(dlg)
        yenile()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Teklif", yeni, rol="yeni").pack(side="left")
    tk_buton(alt, "Karşılaştır / Seç", karsilastir, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_teklifleri_goster(app))


def tedarikci_fiyat_listeleri_goster(app) -> None:
    from database.alis_siparisi_service import AlisSiparisiService
    from database.tedarikci_fiyat_service import TedarikciFiyatService

    kok = _liste_ust(
        app,
        "TEDARİKÇİ FİYAT LİSTELERİ",
        "Tedarikçi + stok bazında güncel alış fiyatı ve iskonto",
        lambda: satin_alma_hub_goster(app),
    )
    arac = tk.Frame(kok, bg=ACIK_BG)
    arac.pack(fill="x", padx=16, pady=8)
    tk.Label(arac, text="Ara:", bg=ACIK_BG).pack(side="left")
    arama = ttk.Entry(arac, width=28)
    arama.pack(side="left", padx=6)

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("tedarikci", "kod", "ad", "birim", "fiyat", "isk", "pb", "bas", "bit")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w in (
        ("tedarikci", "Tedarikçi", 180),
        ("kod", "Stok Kodu", 100),
        ("ad", "Stok Adı", 180),
        ("birim", "Birim", 70),
        ("fiyat", "Fiyat", 90),
        ("isk", "İsk %", 60),
        ("pb", "PB", 50),
        ("bas", "Başlangıç", 90),
        ("bit", "Bitiş", 90),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in TedarikciFiyatService.listele(arama=arama.get()):
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["tedarikci"],
                    r["urun_kodu"],
                    r["urun_adi"],
                    r["birim"],
                    _para(r["birim_fiyat"]),
                    _para(r["iskonto_orani"]),
                    r["para_birimi"],
                    _tarih(r["baslangic"]),
                    _tarih(r["bitis"]),
                ),
            )

    def yeni():
        dlg = TedarikciFiyatDialog(app)
        app.wait_window(dlg)
        yenile()

    def pasif():
        sec = tablo.selection()
        if not sec:
            return
        if not messagebox.askyesno("Pasif", "Kayıt pasife alınsın mı?", parent=app):
            return
        try:
            TedarikciFiyatService.pasif_et(int(sec[0]))
        except ValueError as e:
            messagebox.showerror("Hata", str(e), parent=app)
            return
        yenile()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Fiyat", yeni, rol="yeni").pack(side="left")
    tk_buton(alt, "Pasife Al", pasif, rol="iptal").pack(side="left", padx=6)
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    arama.bind("<Return>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_fiyat_listeleri_goster(app))


def masraf_dagitimi_goster(app) -> None:
    from database.alis_masraf_service import MASRAF_TURLERI, YONTEMLER, AlisMasrafService

    kok = _liste_ust(
        app,
        "MASRAF DAĞITIMI",
        "Alış faturasına nakliye/hamaliye vb. ekleyip satırlara dağıtın",
        lambda: satin_alma_hub_goster(app),
    )
    ust = ttk.Panedwindow(kok, orient="horizontal")
    ust.pack(fill="both", expand=True, padx=16, pady=8)
    sol = ttk.Frame(ust)
    sag = ttk.Frame(ust)
    ust.add(sol, weight=2)
    ust.add(sag, weight=2)

    fatura_tablo = ttk.Treeview(
        sol,
        columns=("no", "tarih", "tedarikci", "toplam", "masraf"),
        show="headings",
        selectmode="browse",
        height=16,
    )
    treeview_stil(fatura_tablo)
    for k, b, w in (
        ("no", "Fatura No", 110),
        ("tarih", "Tarih", 90),
        ("tedarikci", "Tedarikçi", 160),
        ("toplam", "Toplam", 90),
        ("masraf", "Masraf", 90),
    ):
        fatura_tablo.heading(k, text=b)
        fatura_tablo.column(k, width=w)
    fatura_tablo.pack(fill="both", expand=True)

    masraf_tablo = ttk.Treeview(
        sag,
        columns=("tur", "tutar", "yontem", "dagitim", "dahil"),
        show="headings",
        selectmode="browse",
        height=12,
    )
    treeview_stil(masraf_tablo)
    for k, b, w in (
        ("tur", "Tür", 100),
        ("tutar", "Tutar", 90),
        ("yontem", "Yöntem", 80),
        ("dagitim", "Dağıtılan", 90),
        ("dahil", "Maliyet", 70),
    ):
        masraf_tablo.heading(k, text=b)
        masraf_tablo.column(k, width=w)
    masraf_tablo.pack(fill="both", expand=True)

    form = tk.Frame(sag, bg=ACIK_BG)
    form.pack(fill="x", pady=8)
    tk.Label(form, text="Tür", bg=ACIK_BG).grid(row=0, column=0, sticky="w")
    tur = ttk.Combobox(form, values=MASRAF_TURLERI, state="readonly", width=14)
    tur.set("NAKLİYE")
    tur.grid(row=0, column=1, padx=4)
    tk.Label(form, text="Tutar", bg=ACIK_BG).grid(row=0, column=2, sticky="w")
    tutar = ttk.Entry(form, width=12)
    tutar.grid(row=0, column=3, padx=4)
    tk.Label(form, text="Yöntem", bg=ACIK_BG).grid(row=1, column=0, sticky="w", pady=4)
    yontem = ttk.Combobox(form, values=YONTEMLER, state="readonly", width=14)
    yontem.set("TUTAR")
    yontem.grid(row=1, column=1, padx=4, pady=4)

    def faturalari_yenile():
        for i in fatura_tablo.get_children():
            fatura_tablo.delete(i)
        for r in AlisMasrafService.fatura_liste_ozet():
            fatura_tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["fatura_no"],
                    _tarih(r["tarih"]),
                    r["tedarikci"],
                    _para(r["genel_toplam"]),
                    _para(r["masraf_toplam"]),
                ),
            )

    def masraflari_yenile(_e=None):
        for i in masraf_tablo.get_children():
            masraf_tablo.delete(i)
        sec = fatura_tablo.selection()
        if not sec:
            return
        for r in AlisMasrafService.masraflari(int(sec[0])):
            masraf_tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["masraf_turu"],
                    _para(r["tutar"]),
                    r["dagitim_yontemi"],
                    _para(r["dagitim_toplam"]),
                    "Evet" if r["maliyete_dahil"] else "Hayır",
                ),
            )

    def ekle():
        sec = fatura_tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Fatura seçin.", parent=app)
            return
        try:
            AlisMasrafService.kaydet_ve_dagit(
                int(sec[0]),
                tur.get(),
                tutar.get(),
                yontem=yontem.get(),
                maliyete_dahil=True,
            )
        except ValueError as e:
            messagebox.showerror("Masraf", str(e), parent=app)
            return
        tutar.delete(0, "end")
        faturalari_yenile()
        fatura_tablo.selection_set(sec[0])
        masraflari_yenile()

    def sil():
        sec = masraf_tablo.selection()
        if not sec:
            return
        try:
            AlisMasrafService.sil(int(sec[0]))
        except ValueError as e:
            messagebox.showerror("Sil", str(e), parent=app)
            return
        faturalari_yenile()
        masraflari_yenile()

    tk_buton(form, "Ekle ve Dağıt", ekle, rol="yeni").grid(row=1, column=2, columnspan=2, padx=4)
    tk_buton(form, "Masraf Sil", sil, rol="iptal").grid(row=2, column=0, columnspan=2, pady=6, sticky="w")
    fatura_tablo.bind("<<TreeviewSelect>>", masraflari_yenile)
    faturalari_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: masraf_dagitimi_goster(app))


def faturalanmamis_irsaliye_raporu_goster(app) -> None:
    from database.alis_irsaliyesi_service import AlisIrsaliyesiService
    from database.database import get_session
    from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    kok = _liste_ust(
        app,
        "FATURALANMAMIŞ İRSALİYELER",
        "Kabul edilmiş fakat faturası gelmemiş mal girişleri",
        lambda: satin_alma_raporlar_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    tablo = ttk.Treeview(
        cerceve,
        columns=("no", "tarih", "tedarikci", "urun", "miktar", "faturalanan", "kalan"),
        show="headings",
    )
    treeview_stil(tablo)
    for k, b, w in (
        ("no", "İrsaliye", 110),
        ("tarih", "Tarih", 90),
        ("tedarikci", "Tedarikçi", 160),
        ("urun", "Ürün", 180),
        ("miktar", "Miktar", 80),
        ("faturalanan", "Faturalanan", 90),
        ("kalan", "Kalan", 80),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True)

    with get_session() as session:
        irsaliyeler = session.scalars(
            select(AlisIrsaliyesi)
            .options(
                selectinload(AlisIrsaliyesi.satirlar),
                selectinload(AlisIrsaliyesi.cari),
            )
            .order_by(AlisIrsaliyesi.id.desc())
        ).all()
        for irs in irsaliyeler:
            for s in irs.satirlar or []:
                kalan = (s.miktar or Decimal("0")) - (s.faturalanan_miktar or Decimal("0"))
                if kalan <= 0:
                    continue
                tablo.insert(
                    "",
                    "end",
                    values=(
                        irs.irsaliye_no,
                        _tarih(irs.irsaliye_tarihi),
                        irs.cari.unvan if irs.cari else "",
                        f"{s.urun_kodu} {s.urun_adi}",
                        _para(s.miktar),
                        _para(s.faturalanan_miktar),
                        _para(kalan),
                    ),
                )


# --- Dialoglar ---


class TedarikciSecDialog(tk.Toplevel):
    def __init__(self, parent, tedarikciler):
        super().__init__(parent)
        self.result = None
        self.title("Tedarikçi Seç")
        self.geometry("420x360")
        self.transient(parent)
        self.grab_set()
        self.vars = []
        ttk.Label(self, text="Teklife dahil edilecek tedarikçiler:").pack(anchor="w", padx=12, pady=8)
        kutu = ttk.Frame(self)
        kutu.pack(fill="both", expand=True, padx=12)
        for t in tedarikciler:
            v = tk.BooleanVar(value=False)
            self.vars.append((int(t.id), v))
            ttk.Checkbutton(kutu, text=f"{t.cari_kodu} — {t.unvan}", variable=v).pack(anchor="w")

        def tamam():
            self.result = [cid for cid, v in self.vars if v.get()]
            if not self.result:
                messagebox.showwarning("Seçim", "En az bir tedarikçi işaretleyin.", parent=self)
                return
            self.destroy()

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="Tamam", command=tamam).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)


class SatinAlmaTalepDialog(tk.Toplevel):
    def __init__(self, parent, talep_id=None):
        super().__init__(parent)
        self.talep_id = talep_id
        self.title("Satın Alma Talebi")
        self.geometry("720x480")
        self.transient(parent)
        self.grab_set()
        from database.satin_alma_talep_service import ONCELIKLER, SatinAlmaTalepService
        from database.stok_service import StokService

        self.StokService = StokService
        self.SatinAlmaTalepService = SatinAlmaTalepService

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Talep No").grid(row=0, column=0, sticky="w")
        self.no = ttk.Entry(ust, width=16)
        self.no.grid(row=0, column=1, padx=4)
        self.no.insert(0, SatinAlmaTalepService.talep_no() if not talep_id else "")
        ttk.Label(ust, text="Tarih (GG.AA.YYYY)").grid(row=0, column=2, sticky="w")
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.grid(row=0, column=3, padx=4)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="İhtiyaç").grid(row=1, column=0, sticky="w", pady=4)
        self.ihtiyac = ttk.Entry(ust, width=12)
        self.ihtiyac.grid(row=1, column=1, padx=4)
        ttk.Label(ust, text="Depo").grid(row=1, column=2, sticky="w")
        self.depo = ttk.Entry(ust, width=16)
        self.depo.grid(row=1, column=3, padx=4)
        self.depo.insert(0, "ANA DEPO")
        ttk.Label(ust, text="Öncelik").grid(row=2, column=0, sticky="w")
        self.oncelik = ttk.Combobox(ust, values=ONCELIKLER, state="readonly", width=14)
        self.oncelik.set("NORMAL")
        self.oncelik.grid(row=2, column=1, padx=4)
        ttk.Label(ust, text="Açıklama").grid(row=2, column=2, sticky="w")
        self.aciklama = ttk.Entry(ust, width=28)
        self.aciklama.grid(row=2, column=3, padx=4)

        satir_fr = ttk.LabelFrame(self, text="Satırlar", padding=8)
        satir_fr.pack(fill="both", expand=True, padx=10, pady=8)
        self.satirlar = []
        self.liste = tk.Listbox(satir_fr, height=10)
        self.liste.pack(fill="both", expand=True)

        ekle_fr = ttk.Frame(satir_fr)
        ekle_fr.pack(fill="x", pady=6)
        ttk.Label(ekle_fr, text="Stok kodu").pack(side="left")
        self.kod = ttk.Entry(ekle_fr, width=12)
        self.kod.pack(side="left", padx=4)
        ttk.Label(ekle_fr, text="Miktar").pack(side="left")
        self.miktar = ttk.Entry(ekle_fr, width=8)
        self.miktar.pack(side="left", padx=4)
        ttk.Button(ekle_fr, text="Satır Ekle", command=self._satir_ekle).pack(side="left", padx=6)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=8)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)

        if talep_id:
            self._yukle(talep_id)

    def _parse_tarih(self, metin):
        metin = (metin or "").strip()
        if not metin:
            return None
        return datetime.strptime(metin, "%d.%m.%Y").date()

    def _satir_ekle(self):
        kod = self.kod.get().strip()
        if not kod:
            return
        stoklar = self.StokService.stoklari_ara(kod)
        stok = next((s for s in stoklar if s.stok_kodu == kod), None)
        if not stok and stoklar:
            stok = stoklar[0]
        if not stok:
            messagebox.showerror("Stok", "Stok bulunamadı.", parent=self)
            return
        try:
            miktar = Decimal(self.miktar.get().replace(",", ".") or "0")
        except Exception:
            messagebox.showerror("Miktar", "Geçersiz miktar.", parent=self)
            return
        if miktar <= 0:
            messagebox.showerror("Miktar", "Miktar 0'dan büyük olmalı.", parent=self)
            return
        self.satirlar.append(
            {
                "urun_kodu": stok.stok_kodu,
                "urun_adi": stok.stok_adi,
                "birim": stok.birim or "Adet",
                "miktar": miktar,
            }
        )
        self.liste.insert("end", f"{stok.stok_kodu} — {stok.stok_adi}  x {miktar} {stok.birim}")
        self.kod.delete(0, "end")
        self.miktar.delete(0, "end")

    def _yukle(self, talep_id):
        t = self.SatinAlmaTalepService.getir(talep_id)
        if not t:
            return
        self.no.delete(0, "end")
        self.no.insert(0, t.talep_no)
        self.tarih.delete(0, "end")
        self.tarih.insert(0, _tarih(t.talep_tarihi))
        if t.ihtiyac_tarihi:
            self.ihtiyac.insert(0, _tarih(t.ihtiyac_tarihi))
        self.depo.delete(0, "end")
        self.depo.insert(0, t.depo or "ANA DEPO")
        self.oncelik.set(t.oncelik or "NORMAL")
        self.aciklama.insert(0, t.aciklama or "")
        for s in t.satirlar or []:
            self.satirlar.append(
                {
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "birim": s.birim,
                    "miktar": s.miktar,
                    "aciklama": s.aciklama,
                    "depo": s.depo,
                }
            )
            self.liste.insert("end", f"{s.urun_kodu} — {s.urun_adi}  x {s.miktar} {s.birim}")

    def _kaydet(self):
        try:
            veriler = {
                "talep_no": self.no.get().strip(),
                "talep_tarihi": self._parse_tarih(self.tarih.get()),
                "ihtiyac_tarihi": self._parse_tarih(self.ihtiyac.get()),
                "depo": self.depo.get().strip(),
                "oncelik": self.oncelik.get(),
                "aciklama": self.aciklama.get().strip(),
                "durum": "TASLAK",
            }
            if not veriler["talep_tarihi"]:
                raise ValueError("Talep tarihi zorunlu.")
            self.SatinAlmaTalepService.kaydet(veriler, self.satirlar, self.talep_id)
        except Exception as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return
        self.destroy()


class TedarikciTeklifDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Yeni Tedarikçi Teklifi")
        self.geometry("780x520")
        self.transient(parent)
        self.grab_set()
        from database.alis_siparisi_service import AlisSiparisiService
        from database.stok_service import StokService
        from database.tedarikci_teklif_service import TedarikciTeklifService

        self.TedarikciTeklifService = TedarikciTeklifService
        self.StokService = StokService
        self.tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        self.eslesme = {f"{t.cari_kodu} — {t.unvan}": t for t in self.tedarikciler}
        self.satirlar = []

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Tarih").grid(row=0, column=0)
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.grid(row=0, column=1, padx=4)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="Açıklama").grid(row=0, column=2)
        self.aciklama = ttk.Entry(ust, width=36)
        self.aciklama.grid(row=0, column=3, padx=4)

        satir_fr = ttk.LabelFrame(self, text="Teklif satırı", padding=8)
        satir_fr.pack(fill="both", expand=True, padx=10, pady=8)
        self.liste = tk.Listbox(satir_fr, height=12)
        self.liste.pack(fill="both", expand=True)

        ekle = ttk.Frame(satir_fr)
        ekle.pack(fill="x", pady=6)
        ttk.Label(ekle, text="Tedarikçi").pack(side="left")
        self.cari = ttk.Combobox(ekle, values=list(self.eslesme.keys()), width=28)
        self.cari.pack(side="left", padx=4)
        ttk.Label(ekle, text="Stok").pack(side="left")
        self.kod = ttk.Entry(ekle, width=10)
        self.kod.pack(side="left", padx=2)
        ttk.Label(ekle, text="Miktar").pack(side="left")
        self.miktar = ttk.Entry(ekle, width=7)
        self.miktar.pack(side="left", padx=2)
        ttk.Label(ekle, text="Fiyat").pack(side="left")
        self.fiyat = ttk.Entry(ekle, width=8)
        self.fiyat.pack(side="left", padx=2)
        ttk.Label(ekle, text="Vade").pack(side="left")
        self.vade = ttk.Entry(ekle, width=5)
        self.vade.insert(0, "0")
        self.vade.pack(side="left", padx=2)
        ttk.Label(ekle, text="Termin").pack(side="left")
        self.termin = ttk.Entry(ekle, width=5)
        self.termin.insert(0, "7")
        self.termin.pack(side="left", padx=2)
        ttk.Label(ekle, text="Nakliye").pack(side="left")
        self.nakliye = ttk.Entry(ekle, width=8)
        self.nakliye.insert(0, "0")
        self.nakliye.pack(side="left", padx=2)
        ttk.Button(ekle, text="Ekle", command=self._ekle).pack(side="left", padx=6)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=8)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)

    def _ekle(self):
        cari = self.eslesme.get(self.cari.get())
        if not cari:
            messagebox.showerror("Tedarikçi", "Tedarikçi seçin.", parent=self)
            return
        kod = self.kod.get().strip()
        stoklar = self.StokService.stoklari_ara(kod)
        stok = next((s for s in stoklar if s.stok_kodu == kod), None) or (
            stoklar[0] if stoklar else None
        )
        if not stok:
            messagebox.showerror("Stok", "Stok bulunamadı.", parent=self)
            return
        try:
            miktar = Decimal(self.miktar.get().replace(",", ".") or "0")
            fiyat = Decimal(self.fiyat.get().replace(",", ".") or "0")
            nakliye = Decimal(self.nakliye.get().replace(",", ".") or "0")
            vade = int(self.vade.get() or 0)
            termin = int(self.termin.get() or 0)
        except Exception:
            messagebox.showerror("Veri", "Sayısal alanlar hatalı.", parent=self)
            return
        self.satirlar.append(
            {
                "cari_id": cari.id,
                "urun_kodu": stok.stok_kodu,
                "urun_adi": stok.stok_adi,
                "birim": stok.birim or "Adet",
                "miktar": miktar,
                "birim_fiyat": fiyat,
                "vade_gun": vade,
                "termin_gun": termin,
                "nakliye_tutari": nakliye,
            }
        )
        self.liste.insert(
            "end",
            f"{cari.unvan} | {stok.stok_kodu} x{miktar} @ {fiyat}  vade={vade} termin={termin}",
        )

    def _kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            self.TedarikciTeklifService.kaydet(
                {"teklif_tarihi": tarih, "aciklama": self.aciklama.get().strip()},
                self.satirlar,
            )
        except Exception as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return
        self.destroy()


class TeklifKarsilastirmaDialog(tk.Toplevel):
    def __init__(self, parent, teklif_id: int):
        super().__init__(parent)
        self.teklif_id = teklif_id
        self.title("Teklif Karşılaştırma")
        self.geometry("900x480")
        self.transient(parent)
        self.grab_set()
        from database.tedarikci_teklif_service import TedarikciTeklifService

        self.svc = TedarikciTeklifService
        ttk.Label(
            self,
            text="Toplam edinme maliyeti = net tutar + vade maliyeti + nakliye. En uygun satırları seçip siparişe aktarın.",
            wraplength=860,
        ).pack(anchor="w", padx=10, pady=8)

        self.tablo = ttk.Treeview(
            self,
            columns=(
                "tedarikci",
                "urun",
                "miktar",
                "fiyat",
                "isk",
                "vade",
                "termin",
                "nakliye",
                "maliyet",
            ),
            show="headings",
            selectmode="extended",
        )
        for k, b, w in (
            ("tedarikci", "Tedarikçi", 160),
            ("urun", "Ürün", 180),
            ("miktar", "Miktar", 70),
            ("fiyat", "Fiyat", 80),
            ("isk", "İsk", 50),
            ("vade", "Vade", 50),
            ("termin", "Termin", 60),
            ("nakliye", "Nakliye", 70),
            ("maliyet", "Edinme Mal.", 100),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        self.tablo.pack(fill="both", expand=True, padx=10, pady=6)

        for r in self.svc.karsilastirma(teklif_id):
            self.tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["tedarikci"],
                    f"{r['urun_kodu']} {r['urun_adi']}",
                    _para(r["miktar"]),
                    _para(r["birim_fiyat"]),
                    _para(r["iskonto"]),
                    r["vade_gun"],
                    r["termin_gun"],
                    _para(r["nakliye"]),
                    _para(r["edinme_maliyeti"]),
                ),
            )

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=10)

        def aktar():
            sec = [int(x) for x in self.tablo.selection()]
            if not sec:
                messagebox.showinfo("Seçim", "En az bir satır seçin.", parent=self)
                return
            try:
                self.svc.satir_sec(self.teklif_id, sec)
                idler = self.svc.secilenleri_siparise_aktar(self.teklif_id)
            except ValueError as e:
                messagebox.showerror("Aktarım", str(e), parent=self)
                return
            messagebox.showinfo(
                "Sipariş",
                f"{len(idler)} sipariş oluşturuldu: {', '.join(str(i) for i in idler)}",
                parent=self,
            )
            self.destroy()

        ttk.Button(alt, text="Seçilenleri Siparişe Aktar", command=aktar).pack(side="right")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right", padx=6)


class TedarikciFiyatDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Tedarikçi Fiyatı")
        self.geometry("520x320")
        self.transient(parent)
        self.grab_set()
        from database.alis_siparisi_service import AlisSiparisiService
        from database.stok_service import StokService
        from database.tedarikci_fiyat_service import TedarikciFiyatService

        self.svc = TedarikciFiyatService
        self.StokService = StokService
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        self.eslesme = {f"{t.cari_kodu} — {t.unvan}": t for t in tedarikciler}

        fr = ttk.Frame(self, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.cari = ttk.Combobox(fr, values=list(self.eslesme.keys()), width=40)
        self.cari.grid(row=0, column=1, pady=4)
        ttk.Label(fr, text="Stok kodu").grid(row=1, column=0, sticky="w")
        self.kod = ttk.Entry(fr, width=20)
        self.kod.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="Birim fiyat").grid(row=2, column=0, sticky="w")
        self.fiyat = ttk.Entry(fr, width=16)
        self.fiyat.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="İskonto %").grid(row=3, column=0, sticky="w")
        self.isk = ttk.Entry(fr, width=10)
        self.isk.insert(0, "0")
        self.isk.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="Başlangıç").grid(row=4, column=0, sticky="w")
        self.bas = ttk.Entry(fr, width=12)
        self.bas.insert(0, date.today().strftime("%d.%m.%Y"))
        self.bas.grid(row=4, column=1, sticky="w", pady=4)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)

    def _kaydet(self):
        cari = self.eslesme.get(self.cari.get())
        if not cari:
            messagebox.showerror("Tedarikçi", "Tedarikçi seçin.", parent=self)
            return
        kod = self.kod.get().strip()
        stoklar = self.StokService.stoklari_ara(kod)
        stok = next((s for s in stoklar if s.stok_kodu == kod), None) or (
            stoklar[0] if stoklar else None
        )
        if not stok:
            messagebox.showerror("Stok", "Stok bulunamadı.", parent=self)
            return
        try:
            self.svc.kaydet(
                {
                    "cari_id": cari.id,
                    "urun_kodu": stok.stok_kodu,
                    "urun_adi": stok.stok_adi,
                    "birim": stok.birim or "Adet",
                    "birim_fiyat": self.fiyat.get(),
                    "iskonto_orani": self.isk.get(),
                    "gecerlilik_baslangic": datetime.strptime(
                        self.bas.get().strip(), "%d.%m.%Y"
                    ).date(),
                }
            )
        except Exception as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return
        self.destroy()


# --- Tedarikçi Bakiye Durum listesi (görünüm + hizalama; hesaplama yok) ---

_TB_STRIPE = "#E8EEF4"  # açık mavi-gri
_TB_HOVER = "#FFF4CC"  # hafif sarı
_TB_STIL = "TedarikciBakiye.Treeview"

_TB_KOLONLAR = ("kod", "unvan", "bakiye", "ort", "agirlikli", "geciken")
_TB_BASLIKLAR = {
    "kod": "Kod",
    "unvan": "Ünvan",
    "bakiye": "Bakiye",
    "ort": "Ort. Gün",
    "agirlikli": "Ağırlıklı Gün",
    "geciken": "Geciken Gün",
}
# width, minwidth, stretch, anchor
_TB_KOLON_AYAR = {
    "kod": (78, 56, False, "w"),
    "unvan": (360, 200, True, "w"),
    "bakiye": (160, 130, False, "e"),
    "ort": (100, 80, False, "e"),
    "agirlikli": (110, 90, False, "e"),
    "geciken": (110, 90, False, "e"),
}
_TB_SAYISAL = frozenset({"bakiye", "ort", "agirlikli", "geciken"})


def _tb_gun_goster(deger) -> str:
    """Görüntü biçimi: tam sayıysa ondalıksız; değilse en fazla 1 ondalık."""
    try:
        d = Decimal(str(deger if deger is not None else 0))
    except Exception:
        return "0"
    if d == d.to_integral_value():
        return str(int(d))
    q = d.quantize(Decimal("0.1"))
    metin = f"{q:f}".rstrip("0").rstrip(".")
    return metin.replace(".", ",")


def _tb_bakiye_goster(tutar) -> str:
    try:
        v = float(tutar if tutar is not None else 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f} TL"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def tedarikci_bakiye_treeview_stil(tablo: ttk.Treeview, root: tk.Misc | None = None) -> None:
    """Yalnızca Tedarikçi Bakiye listesi — diğer satın alma tablolarına dokunmaz."""
    stil = ttk.Style(root)
    try:
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
    except tk.TclError:
        pass

    aile = resolve_ui_font(root)
    f_govde: tuple = (aile, 11, "bold")
    try:
        families = {str(x).lower() for x in (root or tk._default_root).tk.call("font", "families")}  # type: ignore[attr-defined]
        if "segoe ui semibold" in families:
            f_govde = ("Segoe UI Semibold", 11)
    except Exception:
        pass
    f_baslik = font(12, "bold", root=root)

    stil.configure(
        _TB_STIL,
        font=f_govde,
        rowheight=36,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=0,
        relief="flat",
    )
    stil.configure(
        f"{_TB_STIL}.Heading",
        font=f_baslik,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        borderwidth=0,
        padding=(10, 10),
    )
    stil.map(
        _TB_STIL,
        background=[("selected", LACIVERT)],
        foreground=[("selected", BEYAZ)],
    )
    stil.map(
        f"{_TB_STIL}.Heading",
        background=[("active", LACIVERT_HOVER), ("pressed", LACIVERT_HOVER)],
        foreground=[("active", BEYAZ), ("pressed", BEYAZ)],
    )
    tablo.configure(style=_TB_STIL)
    tablo.tag_configure("tek", background=BEYAZ, foreground=METIN)
    tablo.tag_configure("cift", background=_TB_STRIPE, foreground=METIN)
    tablo.tag_configure("hover", background=_TB_HOVER, foreground=METIN)


def tedarikci_bakiye_durum_goster(app) -> None:
    """Satın Alma → Tedarikçi Bakiye Durum (Ortalama Vadeli) — yalnızca görünüm."""
    from database.rapor_service import RaporService

    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="TEDARİKÇİ BAKİYE DURUM (ORTALAMA VADELİ)", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(ust, text="← Raporlar", command=app.alis_raporlari_goster).pack(side="right")

    ham = list(RaporService.musteri_bakiye_durum(cari_turu="Tedarikçi"))
    ttk.Label(
        app.icerik,
        text=f"{len(ham)} tedarikçi",
        font=font(11, root=app),
        foreground=IKINCIL,
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=(4, 0))
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)

    tablo = ttk.Treeview(
        cerceve,
        columns=_TB_KOLONLAR,
        show="headings",
        selectmode="browse",
    )
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")

    tedarikci_bakiye_treeview_stil(tablo, root=app)

    durum = {
        "kayitlar": ham,
        "sira_kolon": "bakiye",
        "sira_ters": True,
        "secili_kod": None,
        "hover_iid": None,
    }

    def _sirala_anahtar(kayit: dict, kolon: str):
        if kolon == "kod":
            return (kayit.get("cari_kodu") or "").lower()
        if kolon == "unvan":
            return (kayit.get("unvan") or "").lower()
        if kolon == "bakiye":
            return Decimal(str(kayit.get("bakiye") or 0))
        if kolon == "ort":
            return Decimal(str(kayit.get("ortalama_gun") or 0))
        if kolon == "agirlikli":
            return Decimal(str(kayit.get("agirlikli_ortalama_gun") or 0))
        if kolon == "geciken":
            return int(kayit.get("geciken_gun") or 0)
        return 0

    def _degerler(kayit: dict) -> tuple:
        return (
            kayit.get("cari_kodu") or "",
            kayit.get("unvan") or "",
            _tb_bakiye_goster(kayit.get("bakiye")),
            _tb_gun_goster(kayit.get("ortalama_gun")),
            _tb_gun_goster(kayit.get("agirlikli_ortalama_gun")),
            _tb_gun_goster(kayit.get("geciken_gun")),
        )

    def _kolonlari_kur():
        for kolon in _TB_KOLONLAR:
            w, mn, stretch, anc = _TB_KOLON_AYAR[kolon]
            tablo.heading(
                kolon,
                text=_TB_BASLIKLAR[kolon],
                anchor=anc,
                command=lambda k=kolon: _baslik_sirala(k),
            )
            tablo.column(
                kolon,
                width=w,
                minwidth=mn,
                stretch=stretch,
                anchor=anc,
            )

    def _doldur():
        secili = durum["secili_kod"]
        if not secili:
            sec = tablo.selection()
            if sec:
                vals = tablo.item(sec[0], "values")
                if vals:
                    secili = vals[0]

        for item in tablo.get_children():
            tablo.delete(item)

        kayitlar = list(durum["kayitlar"])
        kolon = durum["sira_kolon"]
        ters = durum["sira_ters"]
        kayitlar.sort(key=lambda k: _sirala_anahtar(k, kolon), reverse=ters)

        hedef_iid = None
        for i, kayit in enumerate(kayitlar):
            tag = "cift" if i % 2 else "tek"
            iid = tablo.insert("", "end", values=_degerler(kayit), tags=(tag,))
            kod = kayit.get("cari_kodu") or ""
            if secili and kod == secili:
                hedef_iid = iid

        if hedef_iid:
            tablo.selection_set(hedef_iid)
            tablo.focus(hedef_iid)
            tablo.see(hedef_iid)
        durum["hover_iid"] = None
        _yatay_gerekli_mi()

    def _baslik_sirala(kolon: str):
        if durum["sira_kolon"] == kolon:
            durum["sira_ters"] = not durum["sira_ters"]
        else:
            durum["sira_kolon"] = kolon
            durum["sira_ters"] = kolon in _TB_SAYISAL
        sec = tablo.selection()
        if sec:
            vals = tablo.item(sec[0], "values")
            durum["secili_kod"] = vals[0] if vals else None
        _doldur()

    def _yatay_gerekli_mi(_e=None):
        try:
            genislik = max(int(tablo.winfo_width()), 1)
            toplam = sum(int(tablo.column(k, "width") or 0) for k in _TB_KOLONLAR)
            if toplam > genislik + 8:
                yatay.grid()
            else:
                yatay.grid_remove()
        except tk.TclError:
            pass

    def _hover(event):
        satir = tablo.identify_row(event.y)
        onceki = durum["hover_iid"]
        if onceki and onceki != satir and onceki in tablo.get_children():
            try:
                idx = tablo.index(onceki)
                tablo.item(onceki, tags=("cift" if idx % 2 else "tek",))
            except tk.TclError:
                pass
        durum["hover_iid"] = satir or None
        if not satir:
            return
        if satir in tablo.selection():
            return
        tablo.item(satir, tags=("hover",))

    def _leave(_e=None):
        onceki = durum["hover_iid"]
        if onceki and onceki in tablo.get_children():
            try:
                idx = tablo.index(onceki)
                tablo.item(onceki, tags=("cift" if idx % 2 else "tek",))
            except tk.TclError:
                pass
        durum["hover_iid"] = None

    def _secim(_e=None):
        sec = tablo.selection()
        if sec:
            vals = tablo.item(sec[0], "values")
            durum["secili_kod"] = vals[0] if vals else None

    _kolonlari_kur()
    tablo.bind("<Motion>", _hover)
    tablo.bind("<Leave>", _leave)
    tablo.bind("<<TreeviewSelect>>", _secim)
    tablo.bind("<Configure>", _yatay_gerekli_mi)
    cerceve.bind("<Configure>", _yatay_gerekli_mi)

    _doldur()
    app._tedarikci_bakiye_tablo = tablo
    app._tedarikci_bakiye_yenile = _doldur
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_bakiye_durum_goster(app))
