"""Doğal fatura toplamları — satır hesaplarından, override yok."""

from __future__ import annotations

from decimal import Decimal

from database.alis_faturasi_service import AlisFaturasiService
from database.satis_faturasi_service import SatisFaturasiService


def _satir(miktar, fiyat, kdv=20, isk=0, isk2=0, isk3=0):
    return {
        "miktar": miktar,
        "birim_fiyat": fiyat,
        "birim_satis_fiyati": fiyat,
        "iskonto_orani": isk,
        "iskonto_orani_2": isk2,
        "iskonto_orani_3": isk3,
        "kdv_orani": kdv,
    }


def test_iki_satir_dogal_toplam():
    """Talimat §10/3: iki satırlı fatura doğal hesaplarla doğru toplam verir."""
    satirlar = [
        _satir("2", "100.00", kdv=20),
        _satir("1", "50.00", kdv=10),
    ]
    t = SatisFaturasiService.toplam(satirlar)
    # 2*100=200 + KDV%20=40 → 240; 1*50=50 + KDV%10=5 → 55; genel=295
    assert t["ara_toplam"] == Decimal("250.00")
    assert t["iskonto"] == Decimal("0.00")
    assert t["kdv"] == Decimal("45.00")
    assert t["genel_toplam"] == Decimal("295.00")


def test_satir_ekleme_toplamlari_gunceller():
    """Talimat §10/4: satır eklenince toplamlar güncellenir."""
    satirlar = [_satir("1", "100.00", kdv=20)]
    t1 = SatisFaturasiService.toplam(satirlar)
    assert t1["genel_toplam"] == Decimal("120.00")
    satirlar.append(_satir("1", "100.00", kdv=20))
    t2 = SatisFaturasiService.toplam(satirlar)
    assert t2["genel_toplam"] == Decimal("240.00")
    assert t2["kdv"] == Decimal("40.00")


def test_satir_silme_toplamlari_gunceller():
    """Talimat §10/5: satır silinince toplamlar yeniden hesaplanır."""
    satirlar = [
        _satir("1", "100.00", kdv=20),
        _satir("1", "200.00", kdv=20),
    ]
    t = SatisFaturasiService.toplam(satirlar)
    assert t["genel_toplam"] == Decimal("360.00")
    del satirlar[1]
    t2 = SatisFaturasiService.toplam(satirlar)
    assert t2["genel_toplam"] == Decimal("120.00")


def test_miktar_fiyat_degisimi():
    """Talimat §10/6: miktar veya birim fiyat değişince toplamlar doğru değişir."""
    satirlar = [_satir("2", "10.00", kdv=20)]
    assert SatisFaturasiService.toplam(satirlar)["genel_toplam"] == Decimal("24.00")
    satirlar[0]["miktar"] = "3"
    assert SatisFaturasiService.toplam(satirlar)["genel_toplam"] == Decimal("36.00")
    satirlar[0]["birim_fiyat"] = "20.00"
    satirlar[0]["birim_satis_fiyati"] = "20.00"
    assert SatisFaturasiService.toplam(satirlar)["genel_toplam"] == Decimal("72.00")


def test_iskonto_ve_farkli_kdv():
    """Talimat §10/7: satır iskontosu ve farklı KDV oranları doğru çalışır."""
    satirlar = [
        _satir("1", "100.00", kdv=20, isk=10),  # net 90 + KDV 18 = 108
        _satir("1", "100.00", kdv=10, isk=0),   # net 100 + KDV 10 = 110
    ]
    t = SatisFaturasiService.toplam(satirlar)
    assert t["ara_toplam"] == Decimal("200.00")
    assert t["iskonto"] == Decimal("10.00")
    assert t["kdv"] == Decimal("28.00")
    assert t["genel_toplam"] == Decimal("218.00")


def test_brut_esittir_genel_override_yok():
    """Override kaldırıldı: genel = ara − iskonto + KDV (satırlardan)."""
    satirlar = [_satir("1", "100.00", kdv=20)]
    t = SatisFaturasiService.toplam(satirlar)
    assert t["genel_toplam"] == Decimal("120.00")
    assert t["genel_toplam"] == (t["ara_toplam"] - t["iskonto"] + t["kdv"])


def test_alis_dogal_toplam_ayni_motor():
    satirlar = [
        {
            "miktar": "2",
            "birim_fiyat": "100",
            "iskonto_orani": 0,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": 20,
        }
    ]
    t = AlisFaturasiService.toplam(satirlar)
    assert t["genel_toplam"] == Decimal("240.00")
