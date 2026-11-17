"""Gelir tablosu net/SMM/brüt = Satış Kâr Analizi; stok denklemi mutabakatta."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from database.rapor_service import RaporService
from database.satis_kar_analiz_service import KarAnalizFiltre, SatisKarAnalizService


def test_gelir_tablosu_smm_satis_kar_analizi_ile_esit():
    bugun = date.today()
    bas = bugun
    gt = RaporService.gelir_tablosu(bas, bugun, maliyet_yontemi="FIFO")
    ka_filtre = KarAnalizFiltre(
        baslangic=bas, bitis=bugun, maliyet_yontemi="FIFO", iadeleri_dahil=True
    )
    ka = SatisKarAnalizService._derle(
        ka_filtre, SatisKarAnalizService._satirlari_yukle(ka_filtre)
    )
    oz = gt["ozet"]
    assert "smm_stok_denklemi" in oz
    assert "smm_mutabakat" in oz
    assert "satis_belge_duzeltme" in oz
    assert Decimal(str(oz["smm"])) == Decimal(str(ka.ozet["maliyet"]))
    assert Decimal(str(oz["net_satislar"])) == Decimal(str(ka.ozet["net_satis"]))
    assert Decimal(str(oz["brut_kar"])) == Decimal(str(ka.ozet["brut_kar"]))
    assert Decimal(str(oz["brut_kar"])) == (
        Decimal(str(oz["net_satislar"])) - Decimal(str(oz["smm"]))
    )
    assert Decimal(str(oz["smm_stok_denklemi"])) - Decimal(str(oz["smm"])) == Decimal(
        str(oz["smm_mutabakat"])
    )
    assert any(s.get("kaynak") == "smm_stok_denklemi" for s in gt["satirlar"])
    assert any(s.get("kaynak") == "smm" for s in gt["satirlar"])
    # Belge düzeltmesi varsa tabloda görünür; net = satır bazlı + düzeltme
    duz = Decimal(str(oz["satis_belge_duzeltme"]))
    if duz != 0:
        assert any(s.get("kaynak") == "satis_belge_duzeltme" for s in gt["satirlar"])
