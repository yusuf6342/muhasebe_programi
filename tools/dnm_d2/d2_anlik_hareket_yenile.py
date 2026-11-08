"""Anlığa kasa/banka hareketlerini taze oturumla yeniden yaz.

Stokjq web oturumu sonrası ws hareket çekimi boş kalabiliyor.
Bakiye hesabı için hareket toplamı + guncel_bakiye birlikte kullanılır.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_anlik_hareket_yenile ANLIK.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from entegrasyon.evo_devir.anlik_goruntu import _yillik
from entegrasyon.evobulut_client import EvobulutClient, load_credentials


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("anlik")
    a = p.parse_args()
    yol = Path(a.anlik)
    veri = json.loads(yol.read_text(encoding="utf-8-sig"))

    c = EvobulutClient(load_credentials())
    c.login()
    # Kartlar da taze
    veri["kasalar"] = c.kasa_kart_listesi()
    veri["bankalar"] = c.banka_kart_listesi()
    print(f"kart kasa={len(veri['kasalar'])} banka={len(veri['bankalar'])}", flush=True)

    bugun = date.today()
    print("banka hareketleri:", flush=True)
    veri["banka_hareketleri"] = _yillik(
        lambda b, s: c.tum_banka_islemlerini_cek(bas_tar=b, son_tar=s), bugun
    )
    print("kasa hareketleri:", flush=True)
    veri["kasa_hareketleri"] = _yillik(
        lambda b, s: c.tum_kasa_islemlerini_cek(bas_tar=b, son_tar=s), bugun
    )
    veri["hareket_yenileme"] = {
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "banka_hareket": len(veri["banka_hareketleri"]),
        "kasa_hareket": len(veri["kasa_hareketleri"]),
    }
    print(
        f"banka_h={len(veri['banka_hareketleri'])} kasa_h={len(veri['kasa_hareketleri'])}",
        flush=True,
    )
    ham = json.dumps(veri, ensure_ascii=False, indent=0, default=str).encode("utf-8")
    yol.write_bytes(ham)
    dig = hashlib.sha256(ham).hexdigest()
    yol.with_suffix(".sha256").write_text(f"{dig}  {yol.name}\n", encoding="ascii")
    print(f"yazildi sha256={dig[:16]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
