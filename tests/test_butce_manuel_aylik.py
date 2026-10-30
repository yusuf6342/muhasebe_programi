"""Bütçe manuel aylık giriş / dağıtım / idempotent düzenleme kabul testleri."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

pytest_plugins = ["test_butce_mvp"]

from database.butce_service import (
    ButceService,
    GIRIS_MANUEL,
    dagit_yillik_esit,
    parse_tr_tutar,
)
from database.models.butce import ButceSatir, OLCU_SATIS, OLCU_NAKIT


def test_satir_kaydet_surum_cakisma(butce_db):
    plan = ButceService.plan_olustur("Surum Test", 2026, firma_id=1)
    ButceService.satirlar_kaydet(
        plan["id"],
        [{"olcu_turu": OLCU_SATIS, "kategori": "GENEL", "ay": 1, "tutar": Decimal("100")}],
        firma_id=1,
        beklenen_surum=1,
    )
    guncel = ButceService.plan_getir(plan["id"], firma_id=1)
    assert int(guncel["surum"]) == 2
    with pytest.raises(ValueError, match="başka bir oturumda"):
        ButceService.satirlar_kaydet(
            plan["id"],
            [{"olcu_turu": OLCU_SATIS, "kategori": "GENEL", "ay": 1, "tutar": Decimal("200")}],
            firma_id=1,
            beklenen_surum=1,
        )


def test_parse_tr_tutar_esdeger():
    assert parse_tr_tutar("1250000") == Decimal("1250000.00")
    assert parse_tr_tutar("1.250.000,00") == Decimal("1250000.00")
    assert parse_tr_tutar("1.250.000") == Decimal("1250000.00")
    assert parse_tr_tutar("15.000.000") == Decimal("15000000.00")
    with pytest.raises(ValueError):
        parse_tr_tutar("")
    assert parse_tr_tutar("  ", bos_izinli=True) is None
    with pytest.raises(ValueError):
        parse_tr_tutar("abc")


def test_dagitim_15_milyon_ve_100_tl():
    aylar = dagit_yillik_esit(Decimal("15000000"), 12)
    assert len(aylar) == 12
    assert all(a == Decimal("1250000.00") for a in aylar)
    assert sum(aylar, Decimal("0")) == Decimal("15000000.00")

    yuz = dagit_yillik_esit(Decimal("100.00"), 12)
    assert sum(yuz, Decimal("0")) == Decimal("100.00")
    assert yuz[11] == Decimal("100.00") - yuz[0] * 11


def test_manuel_ocak_digerleri_koru_ve_yeniden_ac(butce_db):
    plan = ButceService.plan_olustur("Manuel Test", 2026, firma_id=1)
    ButceService.yillik_dagit_ve_kaydet(
        plan["id"], Decimal("15000000"), olcu_turu=OLCU_SATIS, firma_id=1
    )
    # Ocak 1.500.000 — diğerleri aynı kalsın
    ButceService.satirlar_kaydet(
        plan["id"],
        [
            {
                "olcu_turu": OLCU_SATIS,
                "kategori": "GENEL",
                "ay": 1,
                "tutar": Decimal("1500000"),
                "kaynak_giris": GIRIS_MANUEL,
            }
        ],
        firma_id=1,
    )
    satirlar = ButceService.plan_satirlari(
        plan["id"], olcu_turu=OLCU_SATIS, kategori="GENEL", firma_id=1
    )
    by_ay = {int(s["ay"]): s["tutar"] for s in satirlar}
    assert by_ay[1] == Decimal("1500000.00")
    assert by_ay[2] == Decimal("1250000.00")
    assert sum(by_ay.values(), Decimal("0")) == Decimal("15250000.00")

    # Yeniden aç — aynı değerler
    yeniden = ButceService.plan_getir(plan["id"], firma_id=1)
    assert yeniden is not None
    by2 = {
        int(s["ay"]): s["tutar"]
        for s in yeniden["satirlar"]
        if s["olcu_turu"] == OLCU_SATIS and s["kategori"] == "GENEL"
    }
    assert by2 == by_ay

    # Düzenleme ikinci plan oluşturmaz
    ButceService.plan_meta_guncelle(plan["id"], ad="Manuel Test Güncel", firma_id=1)
    Session = butce_db["Session"]
    with Session() as s:
        n = len(list(s.scalars(select(ButceSatir).where(ButceSatir.plan_id == plan["id"])).all()))
        from database.models.butce import ButcePlan

        plan_n = len(list(s.scalars(select(ButcePlan).where(ButcePlan.firma_id == 1)).all()))
    assert n == 12
    assert plan_n == 1


def test_kilitli_duzenlenemez(butce_db):
    from database.models.butce import DURUM_ONAYLI, DURUM_KILITLI

    plan = ButceService.plan_olustur("Kilit", 2026, firma_id=1)
    ButceService.yillik_dagit_ve_kaydet(plan["id"], 1200, olcu_turu=OLCU_SATIS, firma_id=1)
    ButceService.plan_durum_degistir(plan["id"], DURUM_ONAYLI, firma_id=1)
    ButceService.plan_durum_degistir(plan["id"], DURUM_KILITLI, firma_id=1)
    ok, neden = ButceService.plan_duzenlenebilir(plan["id"], firma_id=1)
    assert ok is False
    assert "kilit" in neden.lower()
    with pytest.raises(ValueError):
        ButceService.satirlar_kaydet(
            plan["id"],
            [{"olcu_turu": OLCU_SATIS, "kategori": "GENEL", "ay": 1, "tutar": 1}],
            firma_id=1,
        )


def test_nakit_negatif_izinli_satis_degil(butce_db):
    plan = ButceService.plan_olustur("Nakit", 2026, firma_id=1)
    ButceService.satirlar_kaydet(
        plan["id"],
        [
            {
                "olcu_turu": OLCU_NAKIT,
                "kategori": "GENEL",
                "ay": 1,
                "tutar": Decimal("-500.00"),
                "kaynak_giris": GIRIS_MANUEL,
            }
        ],
        firma_id=1,
    )
    with pytest.raises(ValueError):
        ButceService.satirlar_kaydet(
            plan["id"],
            [
                {
                    "olcu_turu": OLCU_SATIS,
                    "kategori": "GENEL",
                    "ay": 1,
                    "tutar": Decimal("-1"),
                }
            ],
            firma_id=1,
        )
