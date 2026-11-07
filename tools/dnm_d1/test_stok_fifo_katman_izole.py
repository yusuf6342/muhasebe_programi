"""İzole FIFO: kart maliyetinden uydurma yok; negatif/bedelsiz/bilinmeyen; tüketim.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_fifo_katman_izole
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from tools.dnm_d1.stok_fifo_katman_izole import (
    fifo_alis_only,
    fifo_consume,
    _maliyet_sinif,
)


def test_bedelsiz_bilinmeyen() -> None:
    assert _maliyet_sinif(Decimal("0")) == "BEDELSIZ_SIFIR"
    assert _maliyet_sinif(None) == "BILINMEYEN"
    assert _maliyet_sinif(Decimal("10")) == "KANITLI"


def test_alis_only_fifo() -> None:
    girisler = [
        {
            "belge_id": "1",
            "belge_tur": "30",
            "belge_tarih": "2026-01-01",
            "satir_index": 0,
            "depo_id": "1",
            "birim": "Adet",
            "miktar": Decimal("10"),
            "birim_fiyat": Decimal("100"),
        },
        {
            "belge_id": "2",
            "belge_tur": "30",
            "belge_tarih": "2026-02-01",
            "satir_index": 0,
            "depo_id": "1",
            "birim": "Adet",
            "miktar": Decimal("5"),
            "birim_fiyat": Decimal("200"),
        },
    ]
    son = fifo_alis_only(
        "X",
        kart_kalan=Decimal("15"),
        hareket_net=Decimal("15"),
        girisler=girisler,
        kaynak_fifo=Decimal("999"),  # uydurma engeli: sonuç karttan gelmez
        kaynak_ort=Decimal("50"),
    )
    assert son.durum == "FIFO_IZOLE_TAM"
    assert son.fifo_birim_izole == Decimal("2000") / Decimal("15")
    assert son.fifo_birim_izole != Decimal("999")
    assert len(son.katmanlar) == 2
    assert son.katmanlar[0].birim_maliyet == Decimal("100")
    assert son.yontem_fark_birim == Decimal("949")


def test_miktar_esit_degil_yontem_sayilmaz() -> None:
    son = fifo_alis_only(
        "Y",
        kart_kalan=Decimal("10"),
        hareket_net=Decimal("8"),
        girisler=[],
        kaynak_fifo=Decimal("1"),
        kaynak_ort=Decimal("2"),
    )
    assert son.durum == "MIKTAR_ESIT_DEGIL"
    assert "yöntem farkı sayılmaz" in son.aciklama or "yontem" in son.aciklama.casefold()


def test_consume_fifo_order() -> None:
    girisler = [
        {
            "stok_id": "Z",
            "belge_id": "1",
            "belge_tur": "30",
            "belge_tarih": "2026-01-01",
            "satir_index": 0,
            "depo_id": "1",
            "birim": "Adet",
            "miktar": Decimal("10"),
            "birim_fiyat": Decimal("100"),
        },
        {
            "stok_id": "Z",
            "belge_id": "2",
            "belge_tur": "30",
            "belge_tarih": "2026-02-01",
            "satir_index": 0,
            "depo_id": "1",
            "birim": "Adet",
            "miktar": Decimal("10"),
            "birim_fiyat": Decimal("200"),
        },
    ]
    kalan = fifo_consume(girisler, [(date(2026, 3, 1), Decimal("12"), "c1")])
    assert len(kalan) == 1
    assert kalan[0].birim_maliyet == Decimal("200")
    assert kalan[0].kalan_miktar == Decimal("8")


def test_negatif_uydurma_yok() -> None:
    girisler = [
        {
            "stok_id": "N",
            "belge_id": "1",
            "belge_tur": "30",
            "belge_tarih": "2026-01-01",
            "satir_index": 0,
            "depo_id": "1",
            "birim": "Adet",
            "miktar": Decimal("5"),
            "birim_fiyat": Decimal("10"),
        }
    ]
    kalan = fifo_consume(girisler, [(date(2026, 2, 1), Decimal("8"), "c")])
    assert kalan == []  # stok bitti; negatif katman uydurulmaz


def main() -> int:
    test_bedelsiz_bilinmeyen()
    test_alis_only_fifo()
    test_miktar_esit_degil_yontem_sayilmaz()
    test_consume_fifo_order()
    test_negatif_uydurma_yok()
    print(
        json.dumps(
            {
                "ok": True,
                "kart_maliyetinden_uydurma_yok": True,
                "negatif_korundu": True,
                "bedelsiz_bilinmeyen_ayri": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
