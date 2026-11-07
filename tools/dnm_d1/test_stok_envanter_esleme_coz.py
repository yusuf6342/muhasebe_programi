"""Eşleme çözüm birim testleri.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_envanter_esleme_coz
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

from tools.dnm_d1.stok_envanter_esleme_coz import _api_hizmet_mi, _q2


def test_hizmet_kod() -> None:
    assert _api_hizmet_mi("GDR000001", "x")
    assert _api_hizmet_mi("KRG", "x")
    assert not _api_hizmet_mi("2406718343282", "Smart")


def test_yuvarlama_q2() -> None:
    assert _q2(Decimal("17.457")) == Decimal("17.46")
    assert _q2(Decimal("6.51428571428572")) == Decimal("6.51")
    assert _q2(Decimal("0.002")) == Decimal("0.00")


def main() -> int:
    test_hizmet_kod()
    test_yuvarlama_q2()
    print(json.dumps({"ok": True}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
