"""Satışlar hub ve alt menü ekranları — mevcut açıcıları yeniden bağlar."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from satis_tema import (
    ACIK_BG,
    HubKart,
    hub_ust_baslik,
    stil_uygula,
)

# Menü sırası ve kart metinleri (test / dokümantasyon için sabit)
SATIS_HUB_KARTLARI: tuple[tuple[str, str, str], ...] = (
    (
        "MÜŞTERİ KARTLARI",
        "Müşteri bilgileri, cari hareketler ve bakiye takibi",
        "musteri",
    ),
    (
        "SATIŞ FATURALARI",
        "Satış faturalarını oluşturun, düzenleyin ve inceleyin",
        "fatura",
    ),
    (
        "ALINAN SİPARİŞLER",
        "Müşteri siparişlerini ve teslimat sürecini yönetin",
        "siparis",
    ),
    (
        "TEKLİFLER",
        "Müşteri teklifi, fiyatlandırma ve siparişe dönüştürme",
        "teklif",
    ),
    (
        "SATIŞ İRSALİYELERİ",
        "Sevk ve teslimat irsaliyelerini yönetin",
        "irsaliye",
    ),
    (
        "CARİ HESAP İŞLEMLERİ",
        "Tahsilat, virman, gelir ve gider işlemleri",
        "cari",
    ),
    (
        "RAPORLAR",
        "Satış, döviz kuru ve döviz bazında raporlar",
        "rapor",
    ),
    (
        "EXCEL VERİ AKTARIM",
        "Müşteri cari ve virman Excel şablonları, doğrulama ve aktarım",
        "excel_aktarim",
    ),
)

CARI_ISLEM_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("TAHSİLAT MAKBUZU", "Nakit, havale ve POS tahsilat makbuzları", "tahsilat"),
    ("CARİ VİRMAN", "Cariler arası borç / alacak virman fişleri", "virman"),
    (
        "MÜŞTERİDEN TEDARİKÇİYE\nKREDİ KARTI ÇEKİM EVRAKI",
        "Müşteri alacağı → tedarikçi borcu; finans hesabına düşmez",
        "kk",
    ),
    ("GELİR FİŞİ", "Hizmet satış (gelir) faturaları ve fişler", "gelir"),
    ("GİDER FİŞİ", "Kasa/banka gider fişleri", "gider"),
)

RAPOR_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("SATIŞ KÂR ANALİZİ", "Maliyet yöntemi, marj, zararına satış ve dönem karşılaştırması", "kar_analiz"),
    ("SATIŞ RAPORLARI", "Müşteri bakiye, ekstre, tahsilat ve satış özeti", "satis_rapor"),
    ("DÖVİZ KURLARI", "USD/EUR günlük kur yönetimi (TCMB / manuel)", "doviz_kur"),
    ("DÖVİZ BAZINDA RAPORLAR", "TL faturaların USD/EUR karşılık raporları", "doviz_rapor"),
)

_SIMGELER = ("◎", "▤", "☰", "▸", "⇄", "▣", "◉", "▦")


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("satislar")
        return
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        if anahtar == "satislar":
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


def _hub_komutlar(app) -> dict[str, Callable]:
    def excel_aktarim():
        from excel_aktarim_ui import excel_aktarim_hub_goster

        excel_aktarim_hub_goster(
            app,
            modul="satis",
            baslik="SATIŞ — EXCEL VERİ AKTARIM",
            geri_fn=lambda: satislar_hub_goster(app),
        )

    return {
        "musteri": app.cariler_goster,
        "fatura": app.satis_faturalari_alt_menusu_goster,
        "siparis": app.satis_siparisleri_goster,
        "teklif": lambda: __import__("teklif_ui", fromlist=["teklifler_hub_goster"]).teklifler_hub_goster(app),
        "irsaliye": app.satis_irsaliyeleri_goster,
        "cari": lambda: cari_hesap_islemleri_goster(app),
        "rapor": lambda: satis_raporlar_hub_goster(app),
        "excel_aktarim": excel_aktarim,
    }


def _cari_komutlar(app) -> dict[str, Callable]:
    def tahsilat():
        from kasa_makbuz_ui import kasa_makbuzlari_sayfasi

        kasa_makbuzlari_sayfasi(
            app,
            makbuz_turu="TAHSILAT",
            geri_fn=lambda a=app: cari_hesap_islemleri_goster(a),
        )

    def gelir():
        from gelir_gider_ui import hizmet_faturalari_sayfasi

        hizmet_faturalari_sayfasi(
            app,
            "GELIR",
            geri_fn=lambda a=app: cari_hesap_islemleri_goster(a),
        )

    def gider():
        from gider_fisi_ui import gider_fisleri_sayfasi

        gider_fisleri_sayfasi(
            app,
            geri_fn=lambda a=app: cari_hesap_islemleri_goster(a),
        )

    return {
        "tahsilat": tahsilat,
        "virman": app.cari_virman_goster,
        "kk": app.kk_cekimi_goster,
        "gelir": gelir,
        "gider": gider,
    }


def _rapor_komutlar(app) -> dict[str, Callable]:
    from doviz_kur_ui import doviz_kur_yonetimi_goster
    from doviz_rapor_ui import doviz_raporlari_goster

    def kar_analiz():
        from satis_kar_analiz_ui import satis_kar_analizi_goster

        satis_kar_analizi_goster(app)

    return {
        "kar_analiz": kar_analiz,
        "satis_rapor": app.satis_raporlari_goster,
        "doviz_kur": lambda: doviz_kur_yonetimi_goster(app),
        "doviz_rapor": lambda: doviz_raporlari_goster(app),
    }


def _kart_izgara(app, parent, kartlar, komut_haritasi: dict[str, Callable], *, sutun: int = 2):
    ızgara = tk.Frame(parent, bg=ACIK_BG)
    ızgara.pack(fill="both", expand=True, padx=16, pady=16)
    for c in range(sutun):
        ızgara.columnconfigure(c, weight=1, uniform="satis_kart")

    for i, (baslik, aciklama, anahtar) in enumerate(kartlar):
        komut = komut_haritasi.get(anahtar)
        if komut is None:
            continue
        r, c = divmod(i, sutun)
        wrap = 260 if "\n" in baslik else 0
        kart = HubKart(
            ızgara,
            baslik=baslik,
            aciklama=aciklama,
            komut=lambda fn=komut: _nav(app, fn),
            wrap_baslik=wrap,
            simge=_SIMGELER[i % len(_SIMGELER)],
        )
        kart.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
        ızgara.rowconfigure(r, weight=1, minsize=120)


def satislar_hub_goster(app) -> None:
    """Satışlar ana hub — büyük kartlar."""
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
        baslik="SATIŞLAR",
        alt_baslik="Müşteri, sipariş, irsaliye, fatura ve cari işlemler",
        app=app,
        geri_komut=lambda: app.sayfa_goster("giris"),
        geri_metin="Ana Menüye Dön",
    )
    _kart_izgara(app, kok, SATIS_HUB_KARTLARI, _hub_komutlar(app), sutun=2)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satislar_hub_goster(app))


def cari_hesap_islemleri_goster(app) -> None:
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
        baslik="CARİ HESAP İŞLEMLERİ",
        alt_baslik="Tahsilat, virman, kredi kartı çekim, gelir ve gider fişleri",
        app=app,
        geri_komut=lambda: satislar_hub_goster(app),
        geri_metin="← Satışlar",
    )
    _kart_izgara(app, kok, CARI_ISLEM_KARTLARI, _cari_komutlar(app), sutun=2)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: cari_hesap_islemleri_goster(app))


def satis_raporlar_hub_goster(app) -> None:
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
        baslik="RAPORLAR",
        alt_baslik="Satış raporları, döviz kurları ve döviz bazında analizler",
        app=app,
        geri_komut=lambda: satislar_hub_goster(app),
        geri_metin="← Satışlar",
    )
    _kart_izgara(app, kok, RAPOR_KARTLARI, _rapor_komutlar(app), sutun=2)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satis_raporlar_hub_goster(app))


def navigasyon_haritasi() -> dict:
    """Smoke / birim test için menü anahtar → hedef özeti."""
    return {
        "hub": [k[0] for k in SATIS_HUB_KARTLARI],
        "cari": [k[0].replace("\n", " ") for k in CARI_ISLEM_KARTLARI],
        "rapor": [k[0] for k in RAPOR_KARTLARI],
        "acici_anahtarlar": {
            "hub": [k[2] for k in SATIS_HUB_KARTLARI],
            "cari": [k[2] for k in CARI_ISLEM_KARTLARI],
            "rapor": [k[2] for k in RAPOR_KARTLARI],
        },
    }
