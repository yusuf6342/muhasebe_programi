"""Brüt / Net / İndirim-Masraf hesap servisi testleri."""

from decimal import Decimal

from database.fatura_genel_toplam_service import (
    ISLEM_INDIRIM,
    ISLEM_MASRAF,
    eski_kayit_normalize,
    islem_uygula,
    netten_islem,
)


def test_islem_yok_brut_net_esit():
    s = islem_uygula(Decimal("1247.63"))
    assert s["brut_toplam"] == Decimal("1247.63")
    assert s["net_toplam"] == Decimal("1247.63")
    assert s["islem_turu"] == ""
    assert s["islem_tutari"] == Decimal("0.00")


def test_yuzde_10_indirim():
    brut = Decimal("1000.00")
    s = islem_uygula(brut, islem_turu=ISLEM_INDIRIM, islem_orani=Decimal("10"), kaynak="oran")
    assert s["islem_tutari"] == Decimal("100.00")
    assert s["net_toplam"] == Decimal("900.00")


def test_100_tl_indirim_oran_otomatik():
    brut = Decimal("1000.00")
    s = islem_uygula(brut, islem_turu=ISLEM_INDIRIM, islem_tutari=Decimal("100"), kaynak="tutar")
    assert s["islem_orani"] == Decimal("10.0000")
    assert s["net_toplam"] == Decimal("900.00")


def test_yuzde_5_masraf():
    brut = Decimal("1000.00")
    s = islem_uygula(brut, islem_turu=ISLEM_MASRAF, islem_orani=Decimal("5"), kaynak="oran")
    assert s["islem_tutari"] == Decimal("50.00")
    assert s["net_toplam"] == Decimal("1050.00")


def test_net_asagi_indirim():
    s = netten_islem(Decimal("1247.63"), Decimal("1245.00"))
    assert s["islem_turu"] == ISLEM_INDIRIM
    assert s["islem_tutari"] == Decimal("2.63")
    assert s["islem_orani"] == Decimal("0.2108")
    assert s["net_toplam"] == Decimal("1245.00")


def test_net_yukari_masraf():
    s = netten_islem(Decimal("1247.63"), Decimal("1250.00"))
    assert s["islem_turu"] == ISLEM_MASRAF
    assert s["islem_tutari"] == Decimal("2.37")
    assert s["islem_orani"] == Decimal("0.1900")
    assert s["net_toplam"] == Decimal("1250.00")


def test_eski_kayit_normalize():
    s = eski_kayit_normalize(tl_genel_toplam=Decimal("500.00"))
    assert s["brut_toplam"] == Decimal("500.00")
    assert s["net_toplam"] == Decimal("500.00")
    assert s["islem_turu"] == ""
    assert s["islem_tutari"] == Decimal("0.00")


def test_indirim_brut_asim_hata():
    try:
        islem_uygula(
            Decimal("100"),
            islem_turu=ISLEM_INDIRIM,
            islem_tutari=Decimal("150"),
            kaynak="tutar",
        )
        assert False, "beklenen ValueError"
    except ValueError:
        pass


def test_brut_sifir_oran_sifir():
    s = islem_uygula(Decimal("0"), islem_turu=ISLEM_INDIRIM, islem_orani=Decimal("10"), kaynak="oran")
    assert s["islem_orani"] == Decimal("0.0000")
    assert s["islem_tutari"] == Decimal("0.00")
    assert s["net_toplam"] == Decimal("0.00")


def test_kilitli_brut_hedef_net_indirim_ornek():
    """Sabit Brüt 4.281,33 → Hedef Net 3.300,00 → İndirim 981,33 (%22,9211)."""
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    durum = fatura_toplam_durumu(
        satir_net_toplam=Decimal("3300.00"),
        gross_lock_active=True,
        locked_gross_total=Decimal("4281.33"),
        target_net_total=Decimal("3300.00"),
    )
    assert durum["gross_lock_active"] is True
    assert durum["brut_toplam"] == Decimal("4281.33")
    assert durum["calculated_gross_total"] == Decimal("3300.00")
    assert durum["islem_turu"] == ISLEM_INDIRIM
    assert durum["islem_tutari"] == Decimal("981.33")
    assert durum["islem_orani"] == Decimal("22.9211")
    assert durum["net_total"] == Decimal("3300.00")


def test_kilit_kdv_degisince_brut_sabit_kalir():
    """Kilit açıkken satır (calculated) değişse bile ekran Brüt sabit kalır."""
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    locked = Decimal("4281.33")
    hedef = Decimal("3300.00")
    d1 = fatura_toplam_durumu(
        satir_net_toplam=Decimal("4281.33"),
        gross_lock_active=True,
        locked_gross_total=locked,
        target_net_total=hedef,
    )
    d2 = fatura_toplam_durumu(
        satir_net_toplam=Decimal("3500.00"),
        gross_lock_active=True,
        locked_gross_total=locked,
        target_net_total=hedef,
    )
    assert d1["brut_toplam"] == locked
    assert d2["brut_toplam"] == locked
    assert d1["islem_tutari"] == d2["islem_tutari"] == Decimal("981.33")
    assert d2["calculated_gross_total"] == Decimal("3500.00")
    assert d2["islem_turu"] == ISLEM_INDIRIM


def test_kilit_kapali_brut_satirdan():
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    durum = fatura_toplam_durumu(
        satir_net_toplam=Decimal("1200.00"),
        gross_lock_active=False,
    )
    assert durum["brut_toplam"] == Decimal("1200.00")
    assert durum["gross_lock_active"] is False
    assert durum["islem_turu"] == ""


def test_hedef_esit_islem_yok():
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    durum = fatura_toplam_durumu(
        satir_net_toplam=Decimal("1000.00"),
        gross_lock_active=True,
        locked_gross_total=Decimal("1000.00"),
        target_net_total=Decimal("1000.00"),
    )
    assert durum["islem_turu"] == ""
    assert durum["islem_tutari"] == Decimal("0.00")
    assert durum["islem_orani"] == Decimal("0.0000")


def test_hedef_yuksek_masraf():
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    durum = fatura_toplam_durumu(
        satir_net_toplam=Decimal("1000.00"),
        gross_lock_active=True,
        locked_gross_total=Decimal("1000.00"),
        target_net_total=Decimal("1100.00"),
    )
    assert durum["islem_turu"] == ISLEM_MASRAF
    assert durum["islem_tutari"] == Decimal("100.00")
    assert durum["islem_orani"] == Decimal("10.0000")


def test_calculated_gross_her_zaman_satirdan():
    """calculated_gross satırdan; kilit açıksa ekran Brüt sabit + İndirim korunur."""
    from database.fatura_genel_toplam_service import (
        calculated_gross_guncelle,
        fatura_toplam_durumu,
        kdv_brut_net_satir_saglama,
    )

    eski_brut = Decimal("4281.33")
    hedef = Decimal("3300.00")
    satir_kdv0 = Decimal("3300.00")
    brut = calculated_gross_guncelle(
        satir_net_toplam=satir_kdv0,
        dagitim_uygulandi=True,
        dagitim_oncesi_brut=eski_brut,
        hedef_net=hedef,
    )
    assert brut == Decimal("3300.00")

    durum = fatura_toplam_durumu(
        satir_net_toplam=satir_kdv0,
        dagitim_uygulandi=True,
        dagitim_oncesi_brut=eski_brut,
        hedef_net=hedef,
        gross_lock_active=True,
        locked_gross_total=eski_brut,
        target_net_total=hedef,
    )
    assert durum["calculated_gross_total"] == Decimal("3300.00")
    assert durum["brut_toplam"] == Decimal("4281.33")
    assert durum["net_total"] == Decimal("3300.00")
    assert durum["islem_turu"] == ISLEM_INDIRIM
    assert durum["islem_tutari"] == Decimal("981.33")

    sag = kdv_brut_net_satir_saglama(
        kdv_matrahi=Decimal("3300.00"),
        kdv_toplami=Decimal("0.00"),
        brut_toplam=Decimal("4281.33"),
        islem_turu=ISLEM_INDIRIM,
        islem_tutari=Decimal("981.33"),
        net_toplam=Decimal("3300.00"),
        gross_lock_active=True,
        calculated_gross_total=Decimal("3300.00"),
    )
    assert sag["ok"], sag["sorunlar"]


def test_kdv_20_den_brut():
    """100 TL matrah %20 → KDV 20, Brüt 120."""
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    matrah = Decimal("100.00")
    kdv = Decimal("20.00")
    satir = matrah + kdv
    durum = fatura_toplam_durumu(satir_net_toplam=satir, gross_lock_active=False)
    assert durum["calculated_gross_total"] == Decimal("120.00")
    assert durum["net_total"] == Decimal("120.00")


def test_yuzdesel_islem_kdv_sonrasi_yenilenir():
    """Kilit kapalıyken brüt değişince yüzde işlem tutarı yeni tabana göre yenilenir."""
    from database.fatura_genel_toplam_service import fatura_toplam_durumu

    d1 = fatura_toplam_durumu(
        satir_net_toplam=Decimal("120.00"),
        islem_turu=ISLEM_INDIRIM,
        islem_orani=Decimal("10"),
        islem_kaynak="oran",
        gross_lock_active=False,
    )
    assert d1["islem_tutari"] == Decimal("12.00")
    assert d1["net_total"] == Decimal("108.00")
    d0 = fatura_toplam_durumu(
        satir_net_toplam=Decimal("100.00"),
        islem_turu=ISLEM_INDIRIM,
        islem_orani=Decimal("10"),
        islem_kaynak="oran",
        gross_lock_active=False,
    )
    assert d0["calculated_gross_total"] == Decimal("100.00")
    assert d0["islem_tutari"] == Decimal("10.00")
    assert d0["net_total"] == Decimal("90.00")


def test_calculated_gross_yeni_satir_yansir():
    """Dağıtım sonrası yeni satır calculated'a yansır; kilit açıksa ekran Brüt sabit."""
    from database.fatura_genel_toplam_service import (
        brut_net_esitlik_saglama,
        calculated_gross_guncelle,
        fatura_toplam_durumu,
    )

    brut0 = Decimal("1042.06")
    hedef = Decimal("1000.00")
    satir_yeni = Decimal("1050.00")
    brut = calculated_gross_guncelle(
        satir_net_toplam=satir_yeni,
        dagitim_uygulandi=True,
        dagitim_oncesi_brut=brut0,
        hedef_net=hedef,
    )
    assert brut == Decimal("1050.00")

    durum = fatura_toplam_durumu(
        satir_net_toplam=satir_yeni,
        dagitim_uygulandi=True,
        dagitim_oncesi_brut=brut0,
        hedef_net=hedef,
        gross_lock_active=True,
        locked_gross_total=brut0,
        target_net_total=hedef,
    )
    assert durum["calculated_gross_total"] == Decimal("1050.00")
    assert durum["brut_toplam"] == brut0
    assert durum["net_total"] == hedef
    assert durum["hedef_sapma"] == Decimal("50.00")
    assert durum["islem_turu"] == ISLEM_INDIRIM

    durum2 = fatura_toplam_durumu(
        satir_net_toplam=hedef,
        dagitim_uygulandi=True,
        dagitim_oncesi_brut=brut0,
        hedef_net=hedef,
        gross_lock_active=True,
        locked_gross_total=brut0,
        target_net_total=hedef,
    )
    esit = brut_net_esitlik_saglama(
        brut=durum2["brut_toplam"],
        islem_turu=durum2["islem_turu"],
        islem_tutari=durum2["islem_tutari"],
        net=durum2["net_total"],
        satir_net=hedef,
    )
    assert esit["ok"], esit["sorunlar"]
    assert durum2["brut_toplam"] == brut0
