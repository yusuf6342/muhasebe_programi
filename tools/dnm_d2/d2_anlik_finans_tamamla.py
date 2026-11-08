"""Anlık görüntüdeki boş kasa/banka kartlarını taze API ile tamamla.

Stokjq web oturumundan sonra ws kasa/banka listesi boş kalabiliyor.
Hareket satırları guncel_bakiye ile tamamlandığı için zorunlu değil.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_anlik_finans_tamamla ANLIK.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from entegrasyon.evobulut_client import EvobulutClient, load_credentials


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("anlik")
    a = p.parse_args()
    yol = Path(a.anlik)
    veri = json.loads(yol.read_text(encoding="utf-8-sig"))

    c = EvobulutClient(load_credentials())
    c.login()
    kasalar = c.kasa_kart_listesi()
    bankalar = c.banka_kart_listesi()
    print(f"kasa={len(kasalar)} banka={len(bankalar)}")
    if not kasalar or not bankalar:
        print("Kasa/banka listesi boş — aktarım engeli")
        return 2

    veri["kasalar"] = kasalar
    veri["bankalar"] = bankalar
    veri["finans_kart_tamamlama"] = {
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kasa": len(kasalar),
        "banka": len(bankalar),
        "hareket_yenilenmedi": True,
        "not": "Bakiyeler evo_guncel_bakiye ile alınır",
    }
    ham = json.dumps(veri, ensure_ascii=False, indent=0, default=str).encode("utf-8")
    yol.write_bytes(ham)
    dig = hashlib.sha256(ham).hexdigest()
    yol.with_suffix(".sha256").write_text(f"{dig}  {yol.name}\n", encoding="ascii")
    print(f"guncellendi {yol.name} sha256={dig[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
