"""Net → fiyatlara dağıtım ve fatura sağlaması testleri."""

from decimal import Decimal

from database.fatura_dagitim_service import (
    fatura_saglama,
    fiyat_snapshot_al,
    fiyat_snapshot_uygula,
    neti_fiyatlara_dagit,
    satir_kdv_dahil_genel,
)


def _satir(miktar, fiyat, kdv=20, **kw):
    return {
        "miktar": Decimal(str(miktar)),
        "birim_satis_fiyati": Decimal(str(fiyat)),
        "birim_fiyat": Decimal(str(fiyat)),
        "iskonto_orani": 0,
        "iskonto_orani_2": 0,
        "iskonto_orani_3": 0,
        "kdv_orani": Decimal(str(kdv)),
        **kw,
    }


def test_tek_satir_yuzde_indirim():
    # KDV dahil 120 → hedef 108 (%10 indirim brüt üzerinden yaklaşık)
    satirlar = [_satir(1, 100, 20)]  # net 100 + kdv 20 = 120
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("120.00")
    s = neti_fiyatlara_dagit(satirlar, Decimal("108.00"))
    assert s["net_toplam"] == Decimal("108.00")
    assert abs(satir_kdv_dahil_genel(satirlar[0]) - Decimal("108.00")) <= Decimal("0.01")


def test_cok_satir_oransal_indirim():
    # 600+300+100 KDV hariç varsayım yerine KDV dahil oran: fiyatlar KDV dahil yapıda
    # A: 500+KDV20%=600, B: 250+50=300, C: 100/1.2... simpler without KDV for ratio demo
    satirlar = [
        _satir(1, 500, 20),  # 600
        _satir(1, 250, 20),  # 300
        _satir(1, Decimal("83.3333"), 20),  # ~100
    ]
    # Normalize C to exactly 100 kdv dahil is hard; use 0 KDV for clean example
    satirlar = [
        _satir(1, 600, 0),
        _satir(1, 300, 0),
        _satir(1, 100, 0),
    ]
    s = neti_fiyatlara_dagit(satirlar, Decimal("900.00"))
    assert s["net_toplam"] == Decimal("900.00")
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("540.00")
    assert satir_kdv_dahil_genel(satirlar[1]) == Decimal("270.00")
    assert satir_kdv_dahil_genel(satirlar[2]) == Decimal("90.00")


def test_net_artis_masraf():
    satirlar = [_satir(2, 50, 0)]  # 100
    s = neti_fiyatlara_dagit(satirlar, Decimal("110.00"))
    assert s["islem_turu"] == "MASRAF"
    assert s["net_toplam"] == Decimal("110.00")


def test_sifir_tutar_katilmaz():
    satirlar = [
        _satir(1, 100, 0),
        _satir(1, 0, 0),
        _satir(0, 50, 0),
    ]
    s = neti_fiyatlara_dagit(satirlar, Decimal("90.00"))
    assert s["dagitilan_satir_sayisi"] == 1
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("90.00")
    assert satirlar[1]["birim_satis_fiyati"] == Decimal("0")


def test_manuel_fiyat_dagitima_dahil():
    # Elle değiştirilen fiyat dağıtıma dâhil edilir
    satirlar = [
        _satir(1, 100, 0, manuel_fiyat=True),
        _satir(1, 100, 0, manuel_fiyat=True),
    ]
    s = neti_fiyatlara_dagit(satirlar, Decimal("180.00"))
    assert s["dagitilan_satir_sayisi"] == 2
    assert s["net_toplam"] == Decimal("180.00")
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("90.00")
    assert satir_kdv_dahil_genel(satirlar[1]) == Decimal("90.00")


def test_dagitima_kapali_haric():
    satirlar = [
        _satir(1, 100, 0),
        _satir(1, 100, 0, dagitima_kapali=True),
    ]
    s = neti_fiyatlara_dagit(satirlar, Decimal("180.00"))
    assert s["dagitilan_satir_sayisi"] == 1
    assert s["net_toplam"] == Decimal("180.00")
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("80.00")
    assert satirlar[1]["birim_satis_fiyati"] == Decimal("100")


def test_tek_satir_684_680_iskonto5():
    """Ekran senaryosu: 2×342 net birim (brüt 360, %5 isk) → hedef 680."""
    satirlar = [
        {
            "miktar": Decimal("2"),
            "birim_satis_fiyati": Decimal("360"),
            "birim_fiyat": Decimal("360"),
            "iskonto_orani": Decimal("5"),
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": Decimal("0"),
            "manuel_fiyat": True,  # elle fiyat — dağıtımı engellememeli
        }
    ]
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("684.00")
    snap = fiyat_snapshot_al(satirlar)
    s = neti_fiyatlara_dagit(satirlar, Decimal("680.00"))
    assert s["net_toplam"] == Decimal("680.00")
    assert s["fark"] == Decimal("-4.00")
    assert s["dagitilan_satir_sayisi"] == 1
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("680.00")
    # Net birim = 680 / 2 = 340; %5 isk korunur → brüt ≈ 340/0.95
    assert satirlar[0]["iskonto_orani"] == Decimal("5")
    net_birim = satir_kdv_dahil_genel(satirlar[0]) / Decimal("2")
    assert net_birim == Decimal("340.00")
    assert abs(satirlar[0]["birim_satis_fiyati"] - Decimal("357.8947")) <= Decimal("0.0001")
    # Geri al
    fiyat_snapshot_uygula(satirlar, snap)
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("684.00")
    assert satirlar[0]["birim_satis_fiyati"] == Decimal("360")


def test_uygun_satir_yok_uyari():
    satirlar = [
        _satir(1, 100, 0, dagitima_kapali=True),
        _satir(0, 50, 0),
    ]
    try:
        neti_fiyatlara_dagit(satirlar, Decimal("90.00"))
        assert False, "uyarı beklenirdi"
    except ValueError as e:
        assert "uygun satır yok" in str(e).lower() or "Uygun" in str(e) or "uygun" in str(e)


def test_kurus_fark_sifir():
    satirlar = [
        _satir(3, Decimal("33.33"), 0),
        _satir(1, Decimal("0.01"), 0),
    ]
    hedef = Decimal("50.00")
    s = neti_fiyatlara_dagit(satirlar, hedef)
    assert s["net_toplam"] == hedef
    sag = fatura_saglama(satirlar, hedef_net=hedef)
    assert sag["ok"], sag["sorunlar"]


def test_residual_1850_05_miktar1_oncelikli():
    """Tam TL satır yuvarlaması: 1×1050,05 → 1050; 800+1050=1850 (residual yok).

    Eski kuruş senaryosu (1850,05) satır matrahı tam TL olunca kendiliğinden
    1850,00'a iner; fark İndirim/Masraf yerine satır yuvarlamasında erir.
    """
    from database.fatura_dagitim_service import satir_kdv_dahil_genel

    satirlar = [
        _satir(1000, Decimal("0.80"), 0),
        _satir(1, Decimal("1050.05"), 0),
    ]
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("800.00")
    assert satir_kdv_dahil_genel(satirlar[1]) == Decimal("1050.00")
    assert sum((satir_kdv_dahil_genel(s) for s in satirlar), Decimal("0")) == Decimal(
        "1850.00"
    )

    hedef = Decimal("1850.00")
    s = neti_fiyatlara_dagit(satirlar, hedef)
    assert s["net_toplam"] == hedef
    assert s.get("residual", Decimal("0.00")) == Decimal("0.00")
    assert sum((satir_kdv_dahil_genel(x) for x in satirlar), Decimal("0")) == hedef
    sag = fatura_saglama(satirlar, hedef_net=hedef)
    assert sag["ok"], sag["sorunlar"]
    assert sag["fark"] == Decimal("0.00")


def test_residual_son_satira_zorlanmaz():
    """Tam TL: 50,05→50 + 1000 = 1050; hedefte residual düzeltilmez."""
    satirlar = [
        _satir(1, Decimal("50.05"), 0),
        _satir(1000, Decimal("1.00"), 0),  # son satır
    ]
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("50.00")
    s = neti_fiyatlara_dagit(satirlar, Decimal("1050.00"))
    assert s["net_toplam"] == Decimal("1050.00")
    assert s.get("residual_duzeltilen_satir") is None
    assert s.get("residual", Decimal("0.00")) == Decimal("0.00")


def test_geri_al_snapshot():
    satirlar = [_satir(1, 100, 0), _satir(1, 50, 0)]
    snap = fiyat_snapshot_al(satirlar)
    neti_fiyatlara_dagit(satirlar, Decimal("120.00"))
    fiyat_snapshot_uygula(satirlar, snap)
    assert satirlar[0]["birim_satis_fiyati"] == Decimal("100")
    assert satirlar[1]["birim_satis_fiyati"] == Decimal("50")


def test_saglama_basarisiz():
    satirlar = [_satir(1, 100, 0)]
    sag = fatura_saglama(satirlar, hedef_net=Decimal("50.00"))
    assert not sag["ok"]
    assert sag["fark"] == Decimal("50.00")


def test_farkli_miktarlar():
    satirlar = [
        _satir(2, 100, 0),  # 200
        _satir(5, 40, 0),  # 200
    ]
    s = neti_fiyatlara_dagit(satirlar, Decimal("360.00"))
    assert s["net_toplam"] == Decimal("360.00")
    assert satir_kdv_dahil_genel(satirlar[0]) == Decimal("180.00")
    assert satir_kdv_dahil_genel(satirlar[1]) == Decimal("180.00")
    # Birim fiyat = satır tutarı / miktar
    assert satirlar[0]["birim_satis_fiyati"] == Decimal("90.0000")
    assert satirlar[1]["birim_satis_fiyati"] == Decimal("36.0000")


def test_farkli_kdv_oranlari():
    satirlar = [
        _satir(1, 100, 20),  # 120
        _satir(1, 100, 10),  # 110
    ]
    hedef = Decimal("207.00")  # %10 indirim kabaca
    s = neti_fiyatlara_dagit(satirlar, hedef)
    assert abs(s["net_toplam"] - hedef) <= Decimal("0.01")
    sag = fatura_saglama(satirlar, hedef_net=hedef)
    assert sag["ok"], sag["sorunlar"]
    # Her satır kendi KDV oranıyla tutarlı kalmalı
    assert abs(satir_kdv_dahil_genel(satirlar[0]) + satir_kdv_dahil_genel(satirlar[1]) - hedef) <= Decimal(
        "0.01"
    )
