"""Hızlı Satış Aşama 2–9 — bellek sepet + müşteri/fiyat/yetki + §23 smoke (GUI yok).

Çalıştırma: python test_hizli_satis_sepet.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from hizli_satis_sepet import HizliSatisSepet
from hizli_satis_musteri import (
    IZIN_ACIK_HESAP,
    IZIN_FIYAT_DEGISTIRME,
    IZIN_IPTAL,
    IZIN_YUKSEK_ISKONTO,
    VARSAYILAN_FIYAT_LISTESI,
    FiyatDegisiklikGunlugu,
    acik_hesap_risk_degerlendir,
    fiyat_degistirme_izinli,
    fiyat_listesi_coz,
    iskonto_degistirme_sonucu,
)


def _assert(kosul, mesaj):
    if not kosul:
        raise AssertionError(mesaj)


def test_ekle_birlestir_ve_toplam():
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=1,
        stok_kodu="U001",
        stok_adi="Vida",
        birim="Adet",
        miktar=1,
        birim_fiyat="10",
        kdv_orani=20,
    )
    sepet.ekle(
        stok_id=1,
        stok_kodu="U001",
        stok_adi="Vida",
        birim="Adet",
        miktar=2,
        birim_fiyat="10",
        kdv_orani=20,
    )
    _assert(len(sepet) == 1, "Aynı ürün birleşmeli")
    _assert(sepet.satirlar[0].miktar == Decimal("3"), f"Miktar 3 olmalı, {sepet.satirlar[0].miktar}")
    # 3*10=30 net; KDV %20 = 6; genel = 36
    t = sepet.toplamlar()
    _assert(t["ara_toplam"] == Decimal("30.00"), t)
    _assert(t["kdv"] == Decimal("6.00"), t)
    _assert(t["genel_toplam"] == Decimal("36.00"), t)


def test_miktar_delta_ve_sil():
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=2, stok_kodu="U002", stok_adi="Ray", miktar=Decimal("1.5"), birim_fiyat="100")
    sepet.miktar_degistir(0, Decimal("0.5"))
    _assert(sepet.satirlar[0].miktar == Decimal("2.0"), sepet.satirlar[0].miktar)
    sepet.miktar_degistir(0, Decimal("-2.0"))
    _assert(len(sepet) == 0, "Miktar 0 veya altı satırı silmeli")


def test_iskonto_satir():
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=3,
        stok_kodu="U003",
        stok_adi="Paket",
        miktar=1,
        birim_fiyat="100",
        iskonto_orani=10,
        kdv_orani=20,
    )
    s = sepet.satirlar[0]
    _assert(s.brut == Decimal("100.00"), s.brut)
    _assert(s.iskonto_tutari == Decimal("10.00"), s.iskonto_tutari)
    _assert(s.net == Decimal("90.00"), s.net)
    _assert(s.kdv_tutari == Decimal("18.00"), s.kdv_tutari)
    _assert(s.satir_toplam == Decimal("108.00"), s.satir_toplam)


def test_varsayilan_kdv_sifir():
    """Yeni satırda KDV varsayılan %0; stok oranı otomatik gelmez."""
    from hizli_satis_sepet import VARSAYILAN_KDV

    _assert(VARSAYILAN_KDV == Decimal("0"), VARSAYILAN_KDV)
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=1,
        stok_kodu="U001",
        stok_adi="Vida",
        miktar=2,
        birim_fiyat="10",
    )
    s = sepet.satirlar[0]
    _assert(s.kdv_orani == Decimal("0"), s.kdv_orani)
    t = sepet.toplamlar()
    _assert(t["ara_toplam"] == Decimal("20.00"), t)
    _assert(t["kdv"] == Decimal("0.00"), t)
    _assert(t["genel_toplam"] == Decimal("20.00"), t)


def test_kdv_orani_degistir_toplamlari_gunceller():
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=1,
        stok_kodu="U001",
        stok_adi="Vida",
        miktar=1,
        birim_fiyat="100",
    )
    _assert(sepet.toplamlar()["genel_toplam"] == Decimal("100.00"), sepet.toplamlar())
    sepet.kdv_ayarla(0, 20)
    t = sepet.toplamlar()
    _assert(sepet.satirlar[0].kdv_orani == Decimal("20"), sepet.satirlar[0].kdv_orani)
    _assert(t["kdv"] == Decimal("20.00"), t)
    _assert(t["genel_toplam"] == Decimal("120.00"), t)
    sepet.kdv_ayarla(0, 10)
    t2 = sepet.toplamlar()
    _assert(t2["kdv"] == Decimal("10.00"), t2)
    _assert(t2["genel_toplam"] == Decimal("110.00"), t2)


def test_farkli_birim_ayri_satir():
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="U001", stok_adi="X", birim="Adet", miktar=1, birim_fiyat=1)
    sepet.ekle(stok_id=1, stok_kodu="U001", stok_adi="X", birim="Paket", miktar=1, birim_fiyat=10)
    _assert(len(sepet) == 2, "Farklı birimler ayrı satır olmalı")


def test_asama3_grup_sabitleri_ve_import():
    """Aşama 3: servis sabitleri + panel modülü import smoke (DB gerekmez)."""
    from database.stok_service import StokService
    import hizli_satis_urun_panel_ui as panel
    import hizli_satis_ui as ui

    _assert(StokService.SIK_SATILANLAR_KOD == "__SIK_SATILANLAR__", "Sık satılanlar kodu")
    _assert(StokService.GRUP_YOK_KOD == "__GRUP_YOK__", "Grup yok kodu")
    _assert(callable(StokService.hizli_satis_gruplari), "hizli_satis_gruplari")
    _assert(callable(StokService.hizli_satis_urunleri), "hizli_satis_urunleri")
    _assert(hasattr(panel, "HizliSatisUrunPanel"), "panel sınıfı")
    _assert(hasattr(ui, "HizliSatisPencere"), "UI pencere")
    _assert(panel.SAYFA_BOYUTU >= 12, "sayfa boyutu dokunmatik için yeterli")


def test_asama3_kart_metinleri_barkod_ad_depo():
    """Kart metinleri sample dict'ten barkod + ad + depo üretir; 120→12 kırılmaz."""
    import hizli_satis_urun_panel_ui as panel

    _assert(panel._miktar_goster(120) == "120", "120 sıfır kırpılmamalı")
    _assert(panel._miktar_goster(Decimal("1.50")) == "1,5", "ondalık virgül")
    ornek = {
        "stok_id": 1,
        "stok_kodu": "VIDA01",
        "stok_adi": "Selectron 3,5x18 Sunta Vidası Uzun Açıklama",
        "barkod": "8697881202660",
        "mevcut_stok": 120,
        "birim": "Adet",
        "birim_fiyat": Decimal("0.31"),
        "resim_yolu": None,
    }
    m = panel._kart_metinleri(ornek)
    _assert(m["barkod"] == "8697881202660", m)
    _assert("Selectron" in m["ad"] and m["ad"].endswith("…"), m)
    _assert(m["depo"] == "Depo: 120 Adet", m)
    _assert("0,31" in m["fiyat"], m)


def test_asama4_fiyat_listesi_coz():
    _assert(
        fiyat_listesi_coz(odeme_niyeti="NAKİT") == "SATIŞ FİYATI 2",
        "NAKİT → SF2",
    )
    _assert(
        fiyat_listesi_coz(odeme_niyeti="AÇIK HESAP") == "SATIŞ FİYATI 3",
        "AÇIK HESAP → SF3",
    )
    _assert(
        fiyat_listesi_coz(odeme_niyeti="KK") == "SATIŞ FİYATI 4",
        "KK → SF4",
    )
    _assert(
        fiyat_listesi_coz(satis_fiyat_listesi="SATIŞ FİYATI 5") == "SATIŞ FİYATI 5",
        "kart listesi öncelikli (niyet yokken)",
    )
    _assert(
        fiyat_listesi_coz(musteri_grubu="PERAKENDE MÜŞTERİ") == VARSAYILAN_FIYAT_LISTESI,
        "perakende grup → SF1",
    )
    _assert(
        fiyat_listesi_coz(odeme_niyeti="NAKİT", satis_fiyat_listesi="SATIŞ FİYATI 1")
        == "SATIŞ FİYATI 2",
        "ödeme niyeti kart listesini ezer",
    )
    _assert(fiyat_listesi_coz() == VARSAYILAN_FIYAT_LISTESI, "varsayılan SF1")


def test_asama4_risk_ve_yetki_kapilari():
    # Limit aşımı — yetkisiz engel
    r = acik_hesap_risk_degerlendir(
        bakiye=80, risk_limiti=100, ek_tutar=50, acik_hesap_yetkisi=False
    )
    _assert(r["durum"] == "engel", r)
    # Aynı durum — yetkili uyarı
    r2 = acik_hesap_risk_degerlendir(
        bakiye=80, risk_limiti=100, ek_tutar=50, acik_hesap_yetkisi=True
    )
    _assert(r2["durum"] == "uyari", r2)
    # Limit içinde
    r3 = acik_hesap_risk_degerlendir(
        bakiye=10, risk_limiti=100, ek_tutar=20, acik_hesap_yetkisi=False
    )
    _assert(r3["durum"] == "ok", r3)

    def yetki_yok(*_kodlar):
        return False

    def yetki_hepsi(*_kodlar):
        return True

    def yetki_sadece_yuksek(*kodlar):
        return IZIN_YUKSEK_ISKONTO in kodlar

    _assert(not fiyat_degistirme_izinli(yetki_yok), "fiyat yetkisiz")
    _assert(fiyat_degistirme_izinli(yetki_hepsi), "fiyat yetkili")

    dusuk = iskonto_degistirme_sonucu(5, yetki_kontrol=yetki_yok)
    _assert(not dusuk["izinli"], dusuk)
    yuksek = iskonto_degistirme_sonucu(15, yetki_kontrol=yetki_sadece_yuksek)
    # yüksek iskonto izni var ama düşük kapı için fiyat/satis da isteniyor —
    # yalnızca YUKSEK varsa yüksek oran geçmeli
    _assert(yuksek["izinli"] and yuksek["yuksek"], yuksek)
    yuksek_engel = iskonto_degistirme_sonucu(15, yetki_kontrol=yetki_yok)
    _assert(not yuksek_engel["izinli"] and yuksek_engel["yuksek"], yuksek_engel)

    _assert(IZIN_FIYAT_DEGISTIRME.startswith("hizli_satis_"), IZIN_FIYAT_DEGISTIRME)
    _assert(IZIN_ACIK_HESAP.startswith("hizli_satis_"), IZIN_ACIK_HESAP)


def test_asama4_sepet_fiyat_iskonto_ve_gunluk():
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="U001", stok_adi="X", miktar=1, birim_fiyat="50")
    sepet.fiyat_ayarla(0, "60")
    _assert(sepet.satirlar[0].birim_fiyat == Decimal("60"), sepet.satirlar[0].birim_fiyat)
    sepet.iskonto_ayarla(0, 5)
    _assert(sepet.satirlar[0].iskonto_orani == Decimal("5"), sepet.satirlar[0].iskonto_orani)
    gunluk = FiyatDegisiklikGunlugu()
    gunluk.ekle(stok_kodu="U001", alan="birim_fiyat", eski=50, yeni=60)
    _assert(len(gunluk) == 1, gunluk.kayitlar)


def test_asama4_bootstrap_izin_katalogu():
    from database.system.bootstrap import IZINLER, ROL_IZINLERI

    kodlar = {k for k, *_ in IZINLER}
    for kod in (IZIN_FIYAT_DEGISTIRME, IZIN_YUKSEK_ISKONTO, IZIN_ACIK_HESAP, IZIN_IPTAL):
        _assert(kod in kodlar, f"IZINLER eksik: {kod}")
    satis = ROL_IZINLERI["SATIS"]
    for kod in (IZIN_FIYAT_DEGISTIRME, IZIN_YUKSEK_ISKONTO, IZIN_ACIK_HESAP, IZIN_IPTAL):
        _assert(kod in satis, f"SATIS rolünde eksik: {kod}")


def test_asama5_servis_ve_tahsilat_import():
    from database.hizli_satis_service import HizliSatisService, HIZLI_ODEME_SEKILLERI
    import hizli_satis_tahsilat_ui as tahsilat

    _assert(callable(HizliSatisService.satisi_tamamla), "satisi_tamamla")
    _assert(callable(HizliSatisService.yeni_idempotency_token), "idempotency")
    _assert("NAKİT / KASA" in HIZLI_ODEME_SEKILLERI, "nakit şekli")
    _assert("AÇIK HESAP" in HIZLI_ODEME_SEKILLERI, "açık hesap")
    _assert(hasattr(tahsilat, "HizliSatisTahsilatDialog"), "tahsilat diyalog")


def test_asama6_beklet_api_ve_ui_import():
    from database.hizli_satis_service import HizliSatisService
    from database.models.hizli_satis import (
        DURUM_BEKLIYOR,
        HizliSatisBekleyen,
        HizliSatisBekleyenSatiri,
    )
    import hizli_satis_bekleyen_ui as bekleyen

    for ad in ("schema_hazirla", "save_hold", "list_holds", "load_hold", "delete_hold"):
        _assert(callable(getattr(HizliSatisService, ad)), ad)
    _assert(DURUM_BEKLIYOR == "BEKLIYOR", "durum sabiti")
    _assert(HizliSatisBekleyen.__tablename__ == "hizli_satis_bekleyenler", "header tablo")
    _assert(
        HizliSatisBekleyenSatiri.__tablename__ == "hizli_satis_bekleyen_satirlari",
        "satır tablo",
    )
    _assert(hasattr(bekleyen, "HizliSatisBekleyenDialog"), "bekleyen diyalog")


def test_asama7_iptal_iade_api_ve_ui_import():
    from database.hizli_satis_service import HizliSatisService, HIZLI_SATIS_ETIKET
    from hizli_satis_musteri import iptal_iade_izinli
    import hizli_satis_iptal_ui as iptal_ui

    for ad in (
        "list_recent_hizli_satislar",
        "fatura_iade_ozeti",
        "satisi_iptal",
        "satisi_iade",
    ):
        _assert(callable(getattr(HizliSatisService, ad)), ad)
    _assert(HIZLI_SATIS_ETIKET == "Hızlı Satış", "etiket")
    _assert(IZIN_IPTAL == "hizli_satis_iptal", IZIN_IPTAL)
    _assert(callable(iptal_iade_izinli), "iptal_iade_izinli")
    _assert(hasattr(iptal_ui, "HizliSatisIptalIadeDialog"), "iptal diyalog")


def test_asama8_gun_sonu_ve_log():
    import tempfile
    from decimal import Decimal
    from pathlib import Path

    from database.hizli_satis_service import (
        HizliSatisService,
        gun_sonu_ozet_hesapla,
        _odeme_kovasi,
    )
    import hizli_satis_cikti_ui as cikti
    import hizli_satis_gun_sonu_ui as gun_sonu
    import hizli_satis_log as hslog

    _assert(_odeme_kovasi("NAKİT / KASA") == "nakit", "nakit kova")
    _assert(_odeme_kovasi("KREDİ KARTIYLA TAHSİLAT") == "kredi_karti", "kk kova")
    _assert(_odeme_kovasi("GELEN HAVALE") == "havale", "havale kova")

    ozet = gun_sonu_ozet_hesapla(
        [
            {
                "genel_toplam": Decimal("120.00"),
                "tahsilat_tutari": Decimal("100.00"),
                "iskonto": Decimal("5.00"),
                "kdv": Decimal("20.00"),
                "tahsilatlar": [
                    {"odeme_sekli": "NAKİT / KASA", "tutar": Decimal("60.00")},
                    {"odeme_sekli": "KREDİ KARTIYLA TAHSİLAT", "tutar": Decimal("40.00")},
                ],
            },
            {
                "genel_toplam": Decimal("50.00"),
                "tahsilat_tutari": Decimal("50.00"),
                "iskonto": Decimal("0"),
                "kdv": Decimal("8.33"),
                "tahsilatlar": [{"odeme_sekli": "GELEN HAVALE", "tutar": Decimal("50.00")}],
            },
        ],
        iptaller=[{"genel_toplam": Decimal("30.00")}],
        iadeler=[{"genel_toplam": Decimal("10.00")}],
    )
    _assert(ozet["satis_adedi"] == 2, ozet)
    _assert(ozet["satis_toplami"] == Decimal("170.00"), ozet["satis_toplami"])
    _assert(ozet["acik_hesap"] == Decimal("20.00"), ozet["acik_hesap"])
    _assert(ozet["odeme_turleri"]["nakit"] == Decimal("60.00"), ozet["odeme_turleri"])
    _assert(ozet["odeme_turleri"]["kredi_karti"] == Decimal("40.00"), ozet["odeme_turleri"])
    _assert(ozet["odeme_turleri"]["havale"] == Decimal("50.00"), ozet["odeme_turleri"])
    _assert(ozet["iptal_adedi"] == 1 and ozet["iade_adedi"] == 1, ozet)
    _assert(callable(HizliSatisService.gun_sonu_ozeti), "gun_sonu_ozeti")
    _assert(callable(HizliSatisService.fatura_cikti_verisi), "fatura_cikti_verisi")
    _assert(hasattr(gun_sonu, "HizliSatisGunSonuDialog"), "gun sonu ui")
    _assert(hasattr(cikti, "HizliSatisBasariDialog"), "basari dialog")
    _assert(callable(cikti.fis_html) and callable(cikti.pdf_metin_satirlari), "html/pdf")

    with tempfile.TemporaryDirectory() as tmp:
        eski = hslog.log_dizini
        yol = Path(tmp)
        hslog.log_dizini = lambda: yol  # type: ignore
        try:
            satir = hslog.kayit_satiri("SATIS", "test", detay={"a": 1}, kullanici="t")
            _assert('"tur": "SATIS"' in satir and "test" in satir, satir)
            yazilan = hslog.fiyat_degisikliklerini_yaz(
                [{"stok_kodu": "U1", "alan": "birim_fiyat", "eski": "1", "yeni": "2"}]
            )
            _assert(yazilan == 1, yazilan)
            dosya = yol / "hizli_satis_islem.log"
            _assert(dosya.is_file() and dosya.stat().st_size > 0, "log dosyası")
        finally:
            hslog.log_dizini = eski


def test_s23_barkod_cift_okutma_miktar_birlestir():
    """§23: aynı barkod tekrar → yeni satır değil miktar +1."""
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=10,
        stok_kodu="BRK1",
        stok_adi="Menteşe",
        miktar=1,
        birim_fiyat="25",
        barkod="8690001",
    )
    sepet.ekle(
        stok_id=10,
        stok_kodu="BRK1",
        stok_adi="Menteşe",
        miktar=1,
        birim_fiyat="25",
        barkod="8690001",
    )
    _assert(len(sepet) == 1, "çift barkod birleşmeli")
    _assert(sepet.satirlar[0].miktar == Decimal("2"), sepet.satirlar[0].miktar)
    _assert(sepet.satirlar[0].barkod == "8690001", sepet.satirlar[0].barkod)


def test_s23_ondalik_miktar_ve_genel_iskonto():
    """§23: ondalık miktar + satır/genel iskonto (genel = tüm satırlara oran)."""
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=1,
        stok_kodu="KG1",
        stok_adi="Silikon",
        birim="Kg",
        miktar=Decimal("0.25"),
        birim_fiyat="40",
        kdv_orani=20,
    )
    sepet.ekle(
        stok_id=2,
        stok_kodu="M1",
        stok_adi="Profil",
        birim="Metre",
        miktar=Decimal("1.5"),
        birim_fiyat="100",
        iskonto_orani=10,
        kdv_orani=20,
    )
    _assert(len(sepet) == 2, "iki satır")
    # Genel iskonto %5 — her satıra uygula (UI F5 benzeri)
    for i in range(len(sepet)):
        sepet.iskonto_ayarla(i, 5)
    t = sepet.toplamlar()
    # 0.25*40=10 → %5 isk=0.5 → net 9.5 → KDV 1.90 → 11.40
    # 1.5*100=150 → %5 isk=7.5 → net 142.5 → KDV 28.50 → 171.00
    _assert(t["ara_toplam"] == Decimal("160.00"), t)
    _assert(t["iskonto"] == Decimal("8.00"), t)
    _assert(t["genel_toplam"] == Decimal("182.40"), t)


def test_s23_para_ustu_kuralı():
    """§23: nakit fazla girilirse kayıt tutarı = kalan (para üstü = fark)."""
    genel = Decimal("36.00")
    alinan = Decimal("50.00")
    kalan = genel
    kayit_tutar = kalan if alinan > kalan else alinan
    para_ustu = alinan - kalan if alinan > kalan else Decimal("0")
    _assert(kayit_tutar == Decimal("36.00"), kayit_tutar)
    _assert(para_ustu == Decimal("14.00"), para_ustu)


def test_asama9_cikti_html_pdf_smoke():
    """§23 yardımcı: fiş/PDF üreticileri örnek veriyle (GUI yok)."""
    import hizli_satis_cikti_ui as cikti

    veri = {
        "firma": "Test",
        "fatura_no": "SF-00001",
        "fatura_tarihi": "2026-09-15",
        "islem_saati": "12:00",
        "musteri": "PERAKENDE MÜŞTERİ",
        "kasiyer": "admin",
        "satirlar": [
            {
                "urun_kodu": "U1",
                "urun_adi": "Vida",
                "miktar": Decimal("2"),
                "birim": "Adet",
                "birim_fiyat": Decimal("10"),
                "iskonto_orani": Decimal("0"),
                "satir_toplam": Decimal("24.00"),
            }
        ],
        "ara_toplam": Decimal("20.00"),
        "iskonto": Decimal("0"),
        "kdv": Decimal("4.00"),
        "genel_toplam": Decimal("24.00"),
        "tahsilat_tutari": Decimal("24.00"),
        "kalan": Decimal("0"),
        "tahsilatlar": [{"odeme_sekli": "NAKİT / KASA", "tutar": Decimal("24.00")}],
    }
    html = cikti.fis_html(veri)
    _assert("SF-00001" in html and "Vida" in html, "fiş html")
    a4 = cikti.a4_html(veri)
    _assert("SF-00001" in a4, "a4 html")
    satirlar = cikti.pdf_metin_satirlari(veri)
    _assert(any("SF-00001" in s for s in satirlar), satirlar)


def test_hedef_toplam_1050_1000():
    """Örnek: 1050 → 1000; genel toplam ve satır oranları korunur."""
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="525")
    sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=1, birim_fiyat="525")
    _assert(sepet.toplamlar()["genel_toplam"] == Decimal("1050.00"), sepet.toplamlar())
    t = sepet.hedef_toplam_uygula(Decimal("1000"))
    _assert(t["genel_toplam"] == Decimal("1000.00"), t)
    # Oranlar eşit kalmalı (525:525 → 500:500)
    _assert(sepet.satirlar[0].satir_toplam == Decimal("500.00"), sepet.satirlar[0].satir_toplam)
    _assert(sepet.satirlar[1].satir_toplam == Decimal("500.00"), sepet.satirlar[1].satir_toplam)


def test_hedef_toplam_yukari_olcekle():
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=2, birim_fiyat="100")
    sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=1, birim_fiyat="50")
    _assert(sepet.toplamlar()["genel_toplam"] == Decimal("250.00"), sepet.toplamlar())
    t = sepet.hedef_toplam_uygula("300")
    _assert(t["genel_toplam"] == Decimal("300.00"), t)
    # 200:50 → 240:60
    _assert(sepet.satirlar[0].satir_toplam == Decimal("240.00"), sepet.satirlar[0].satir_toplam)
    _assert(sepet.satirlar[1].satir_toplam == Decimal("60.00"), sepet.satirlar[1].satir_toplam)


def test_hedef_toplam_kurus_yuvarlama():
    """Üç satırda kuruş farkı son satırda kapanır."""
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="10")
    sepet.ekle(stok_id=2, stok_kodu="B", stok_adi="B", miktar=1, birim_fiyat="10")
    sepet.ekle(stok_id=3, stok_kodu="C", stok_adi="C", miktar=1, birim_fiyat="10")
    t = sepet.hedef_toplam_uygula(Decimal("10.00"))
    _assert(t["genel_toplam"] == Decimal("10.00"), t)
    satir_sum = sum((s.satir_toplam for s in sepet.satirlar), Decimal("0"))
    _assert(_kurus_check(satir_sum) == Decimal("10.00"), satir_sum)


def _kurus_check(tutar) -> Decimal:
    from decimal import ROUND_HALF_UP

    return Decimal(str(tutar)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_hedef_toplam_kdv_dahil():
    """KDV'li satırlarda da genel (KDV dahil) hedefe eşitlenir."""
    sepet = HizliSatisSepet()
    sepet.ekle(
        stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="100", kdv_orani=20
    )
    sepet.ekle(
        stok_id=2, stok_kodu="B", stok_adi="B", miktar=1, birim_fiyat="50", kdv_orani=10
    )
    # 120 + 55 = 175
    _assert(sepet.toplamlar()["genel_toplam"] == Decimal("175.00"), sepet.toplamlar())
    t = sepet.hedef_toplam_uygula(Decimal("140"))
    _assert(t["genel_toplam"] == Decimal("140.00"), t)


def test_hedef_toplam_bos_sepet():
    sepet = HizliSatisSepet()
    try:
        sepet.hedef_toplam_uygula(100)
        raise AssertionError("Boş sepet ValueError fırlatmalı")
    except ValueError:
        pass


def test_hedef_toplam_negatif():
    sepet = HizliSatisSepet()
    sepet.ekle(stok_id=1, stok_kodu="A", stok_adi="A", miktar=1, birim_fiyat="10")
    try:
        sepet.hedef_toplam_uygula(Decimal("-1"))
        raise AssertionError("Negatif hedef ValueError fırlatmalı")
    except ValueError:
        pass


def main():
    testler = [
        test_ekle_birlestir_ve_toplam,
        test_miktar_delta_ve_sil,
        test_iskonto_satir,
        test_varsayilan_kdv_sifir,
        test_kdv_orani_degistir_toplamlari_gunceller,
        test_farkli_birim_ayri_satir,
        test_asama3_grup_sabitleri_ve_import,
        test_asama3_kart_metinleri_barkod_ad_depo,
        test_asama4_fiyat_listesi_coz,
        test_asama4_risk_ve_yetki_kapilari,
        test_asama4_sepet_fiyat_iskonto_ve_gunluk,
        test_asama4_bootstrap_izin_katalogu,
        test_asama5_servis_ve_tahsilat_import,
        test_asama6_beklet_api_ve_ui_import,
        test_asama7_iptal_iade_api_ve_ui_import,
        test_asama8_gun_sonu_ve_log,
        test_s23_barkod_cift_okutma_miktar_birlestir,
        test_s23_ondalik_miktar_ve_genel_iskonto,
        test_s23_para_ustu_kuralı,
        test_asama9_cikti_html_pdf_smoke,
        test_hedef_toplam_1050_1000,
        test_hedef_toplam_yukari_olcekle,
        test_hedef_toplam_kurus_yuvarlama,
        test_hedef_toplam_kdv_dahil,
        test_hedef_toplam_bos_sepet,
        test_hedef_toplam_negatif,
    ]
    for fn in testler:
        fn()
    print(f"OK — test_hizli_satis_sepet: {len(testler)} test geçti")


if __name__ == "__main__":
    main()
