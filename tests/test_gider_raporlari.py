"""Gider raporları R01–R08 ve gelir tablosu karşılaştırma temel kabul testleri."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from database.gider_rapor_service import GiderRaporService, _degisim_yuzde, onceki_es_donem


def test_g01_oran_tanimlari():
    """S 1M, M 700k, O 180k, F 30k → B/E/P/K ve oranlar."""
    S = Decimal("1000000")
    M = Decimal("700000")
    O = Decimal("180000")
    F = Decimal("30000")
    B = S - M
    E = O + F
    P = B - O
    K = B - O - F
    assert B == Decimal("300000")
    assert E == Decimal("210000")
    assert P == Decimal("120000")
    assert K == Decimal("90000")
    assert (E / S * 100).quantize(Decimal("0.01")) == Decimal("21.00")
    assert (E / B * 100).quantize(Decimal("0.01")) == Decimal("70.00")


def test_gt25_yonetim_sonucu():
    S, M, O, F, I, J = (
        Decimal("1000000"),
        Decimal("600000"),
        Decimal("180000"),
        Decimal("30000"),
        Decimal("10000"),
        Decimal("5000"),
    )
    BK = S - M
    E = O + F
    K = BK + I + J - O - F
    assert BK == Decimal("400000")
    assert E == Decimal("210000")
    assert K == Decimal("205000")


def test_degisim_yuzde_yeni_ve_sifir():
    y, et = _degisim_yuzde(Decimal("2000"), Decimal("0"))
    assert y is None and et == "yeni"
    y, et = _degisim_yuzde(Decimal("0"), Decimal("0"))
    assert et == "yok"
    y, et = _degisim_yuzde(Decimal("36000"), Decimal("30000"))
    assert y == Decimal("20.00")


def test_onceki_es_donem():
    a, z = onceki_es_donem(date(2026, 10, 1), date(2026, 10, 23))
    assert a == date(2026, 9, 8)
    assert z == date(2026, 9, 30)
    assert (z - a).days == 22


def test_r01_calisir():
    GiderRaporService.ensure_schema()
    bugun = date.today()
    ozet = GiderRaporService.r01_genel_bakis(date(bugun.year, 1, 1), bugun)
    assert "E" in ozet and "K" in ozet and "gruplar" in ozet
    assert ozet["E"] == ozet["O"] + ozet["F"]


def test_gelir_tablosu_karsilastirma_ve_etiket():
    from database.rapor_service import RaporService

    bugun = date.today()
    bas = date(bugun.year, 1, 1)
    b_bas, b_bit = onceki_es_donem(bas, bugun)
    veri = RaporService.gelir_tablosu(
        bas,
        bugun,
        maliyet_yontemi="FIFO",
        karsilastirma_baslangic=b_bas,
        karsilastirma_bitis=b_bit,
    )
    assert veri["ozet"]["yonetim_sonucu"] == veri["ozet"]["net_kar"]
    assert any("Vergi öncesi yönetim sonucu" in (s.get("etiket") or "") for s in veri["satirlar"])
    assert "karsilastirma" in veri
    assert not any((s.get("etiket") or "").startswith("Net kâr") for s in veri["satirlar"])
