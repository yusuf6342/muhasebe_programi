"""Uzlaşılan tutar → Net; farkı satır fiyatlarına dağıtım."""

from __future__ import annotations

from decimal import Decimal

from database.uzlasilan_tutar_service import (
    hedef_satir_genelden_birim_fiyat,
    satir_hedefleri_orantili,
    uzlasilan_fiyatlara_dagit,
    uzlasilan_indirim_masraf,
)


def test_840_800_indirim():
    s = uzlasilan_indirim_masraf(Decimal("840.00"), Decimal("800.00"))
    assert s["brut"] == Decimal("840.00")
    assert s["net"] == Decimal("800.00")
    assert s["indirim_tutari"] == Decimal("40.00")
    assert s["masraf_tutari"] == Decimal("0.00")
    assert s["islem_turu"] == "INDIRIM"


def test_840_850_masraf():
    s = uzlasilan_indirim_masraf(Decimal("840.00"), Decimal("850.00"))
    assert s["masraf_tutari"] == Decimal("10.00")
    assert s["indirim_tutari"] == Decimal("0.00")
    assert s["net"] == Decimal("850.00")
    assert s["islem_turu"] == "MASRAF"


def test_esit_net_brut():
    s = uzlasilan_indirim_masraf(Decimal("100.00"), Decimal("100.00"))
    assert s["net"] == Decimal("100.00")
    assert s["indirim_tutari"] == Decimal("0.00")
    assert s["masraf_tutari"] == Decimal("0.00")
    assert s["islem_turu"] == ""


def test_bos_uzlasilan_brut():
    s = uzlasilan_indirim_masraf(Decimal("123.45"), None)
    assert s["net"] == Decimal("123.45")


def test_kurus_net_uzlasilana_yuvarlanir():
    s = uzlasilan_indirim_masraf(Decimal("100.00"), Decimal("99.99"))
    assert s["net"] == Decimal("99.99")
    assert s["indirim_tutari"] == Decimal("0.01")


def test_satir_hedefleri_2580_3000():
    """Ekran örneği: Brüt 2580 → Uzlaşılan 3000 orantılı."""
    mevcut = [Decimal("900.00"), Decimal("1200.00"), Decimal("480.00")]
    hedefler = satir_hedefleri_orantili(mevcut, Decimal("3000.00"))
    assert sum(hedefler, Decimal("0")) == Decimal("3000.00")
    assert hedefler[0] == Decimal("1046.51")  # 900/2580*3000
    assert hedefler[1] == Decimal("1395.35")  # 1200/2580*3000
    assert hedefler[2] == Decimal("558.14")  # kalan


def test_birim_fiyat_geri_hesap_kdv20():
    # 50 adet, %20 KDV, iskonto yok → hedef genel 1046.51
    # net = 1046.51/1.2, fiyat = net/50
    f = hedef_satir_genelden_birim_fiyat(
        miktar=Decimal("50"),
        kdv_orani=Decimal("20"),
        hedef_satir_genel=Decimal("1046.51"),
    )
    assert f == Decimal("17.4418")


def test_uzlasilan_fiyatlara_dagit_ekran_ornegi():
    satirlar = [
        {
            "miktar": Decimal("50"),
            "birim_satis_fiyati": Decimal("15"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
        {
            "miktar": Decimal("10"),
            "birim_satis_fiyati": Decimal("100"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
        {
            "miktar": Decimal("500"),
            "birim_satis_fiyati": Decimal("0.80"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
    ]

    def genel(v):
        miktar = Decimal(str(v["miktar"]))
        fiyat = Decimal(str(v["birim_satis_fiyati"]))
        kdv = Decimal(str(v["kdv_orani"]))
        net = (miktar * fiyat).quantize(Decimal("0.01"))
        kdv_t = (net * kdv / Decimal("100")).quantize(Decimal("0.01"))
        return (net + kdv_t).quantize(Decimal("0.01"))

    assert sum((genel(s) for s in satirlar), Decimal("0")) == Decimal("2580.00")
    sonuc = uzlasilan_fiyatlara_dagit(satirlar, Decimal("3000.00"), satir_genel_fn=genel)
    assert sonuc["degisti"] is True
    assert sonuc["yeni_toplam"] == Decimal("3000.00")
    assert sum((genel(s) for s in satirlar), Decimal("0")) == Decimal("3000.00")
    # Masraf pad'i kalmamalı: fiyatlar yükselmiş olmalı
    assert Decimal(str(satirlar[0]["birim_satis_fiyati"])) > Decimal("15")
    assert Decimal(str(satirlar[1]["birim_satis_fiyati"])) > Decimal("100")


def test_uzlasilan_fiyatlara_dagit_5196_5000():
    """SF örneği: Brüt 5196 → Net 5000 indirim dağıtımı."""
    satirlar = [
        {
            "miktar": Decimal("1000"),
            "birim_satis_fiyati": Decimal("0.80"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
        {
            "miktar": Decimal("4"),
            "birim_satis_fiyati": Decimal("360"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
        {
            "miktar": Decimal("22"),
            "birim_satis_fiyati": Decimal("95"),
            "kdv_orani": Decimal("20"),
            "iskonto_orani": 0,
        },
    ]

    def genel(v):
        miktar = Decimal(str(v["miktar"]))
        fiyat = Decimal(str(v["birim_satis_fiyati"]))
        kdv = Decimal(str(v["kdv_orani"]))
        net = (miktar * fiyat).quantize(Decimal("0.01"))
        kdv_t = (net * kdv / Decimal("100")).quantize(Decimal("0.01"))
        return (net + kdv_t).quantize(Decimal("0.01"))

    assert sum((genel(s) for s in satirlar), Decimal("0")) == Decimal("5196.00")
    sonuc = uzlasilan_fiyatlara_dagit(satirlar, Decimal("5000.00"), satir_genel_fn=genel)
    assert sonuc["yeni_toplam"] == Decimal("5000.00")
    assert sonuc["kalan_fark"] == Decimal("0.00")
    assert Decimal(str(satirlar[0]["birim_satis_fiyati"])) < Decimal("0.80")
    assert Decimal(str(satirlar[1]["birim_satis_fiyati"])) < Decimal("360")


def test_dagitima_kapali_korunur():
    satirlar = [
        {
            "miktar": Decimal("1"),
            "birim_satis_fiyati": Decimal("100"),
            "kdv_orani": Decimal("0"),
            "dagitima_kapali": True,
        },
        {
            "miktar": Decimal("1"),
            "birim_satis_fiyati": Decimal("100"),
            "kdv_orani": Decimal("0"),
            "dagitima_kapali": False,
        },
    ]

    def genel(v):
        return (
            Decimal(str(v["miktar"])) * Decimal(str(v["birim_satis_fiyati"]))
        ).quantize(Decimal("0.01"))

    uzlasilan_fiyatlara_dagit(satirlar, Decimal("250.00"), satir_genel_fn=genel)
    assert Decimal(str(satirlar[0]["birim_satis_fiyati"])) == Decimal("100")
    assert Decimal(str(satirlar[1]["birim_satis_fiyati"])) == Decimal("150.0000")
    assert genel(satirlar[0]) + genel(satirlar[1]) == Decimal("250.00")
