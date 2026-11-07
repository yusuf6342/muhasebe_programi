"""Stok envanter Excel — TR parse, kuruş, sıfır maliyet sınıfları.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_envanter_excel_devir1
"""

from __future__ import annotations

import json
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from tools.dnm_d1.stok_envanter_excel_devir1 import (
    _q2,
    _sinif_sifir_maliyet,
    tr_dec,
)


def test_tr_dec() -> None:
    assert tr_dec("80,00") == Decimal("80.00")
    assert tr_dec("11,49") == Decimal("11.49")
    assert tr_dec("1.234,56") == Decimal("1234.56")
    assert tr_dec(172.8) == Decimal(str(172.8))
    assert tr_dec("Toplam3.731.181,36") is None
    assert tr_dec(None) is None


def test_kurus_half_up_vs_down() -> None:
    ham = Decimal("3731181.366566732549555986842")
    assert _q2(ham, ROUND_HALF_UP) == Decimal("3731181.37")
    assert _q2(ham, ROUND_DOWN) == Decimal("3731181.36")


def test_sifir_maliyet_sinif() -> None:
    bed = _sinif_sifir_maliyet(
        "1",
        [{"birim_fiyat": "0"}, {"birim_fiyat": "0"}],
        {"maliyet_fifo": "0", "maliyet_ort": "10"},
    )
    assert bed["sinif"] == "BEDELSIZ_SIFIR_KANITLI"
    assert bed["kart_fifo_doldurma_yok"] is True

    eksik = _sinif_sifir_maliyet(
        "2",
        [{"birim_fiyat": "45"}],
        {"maliyet_fifo": "0", "maliyet_ort": "12"},
    )
    assert eksik["sinif"] == "EXSIK_MALIYET_GOSTERIM"

    yok = _sinif_sifir_maliyet("3", [], {"maliyet_fifo": "0"})
    assert yok["sinif"] == "BILINMEYEN_ALIS_YOK"


def main() -> int:
    test_tr_dec()
    test_kurus_half_up_vs_down()
    test_sifir_maliyet_sinif()
    print(
        json.dumps(
            {
                "ok": True,
                "tr_parse": True,
                "kurus_half_up_vs_down": True,
                "sifir_maliyet_ayrim": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
