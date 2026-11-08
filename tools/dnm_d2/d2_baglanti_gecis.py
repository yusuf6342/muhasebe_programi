"""Aktif baglanti_ayari.json ↔ D2 profil geçişi (yedekli).

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_baglanti_gecis d2
  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_baglanti_gecis geri
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from database.baglanti_modu import ayar_dosya_yolu
from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    PROFIL_ADI,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
YEDEK_DIR = CALISMA / "esleme"
ONCEKI = YEDEK_DIR / "BAGLANTI_AYARI_ONCEKI_KABUL.json"


def _aktif() -> Path:
    return ayar_dosya_yolu()


def d2_yap() -> dict:
    aktif = _aktif()
    YEDEK_DIR.mkdir(parents=True, exist_ok=True)
    if not ONCEKI.exists():
        shutil.copy2(aktif, ONCEKI)
    onceki = json.loads(aktif.read_text(encoding="utf-8-sig"))
    pg = dict(onceki.get("postgres") or {})
    pg["sistem_db"] = ONERILEN_SISTEM_DB
    pg["firma_db"] = ONERILEN_FIRMA_DB
    pg["ortam"] = "DENEME"
    pg["terminal_kimligi"] = f"DNM-D2-20260901-{datetime.now():%Y%m%d}"
    yeni = {
        "kipi": "yerel_ag_postgres",
        "schema_surum": onceki.get("schema_surum", 1),
        "postgres": pg,
    }
    aktif.write_text(json.dumps(yeni, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "durum": "D2",
        "sistem_db": ONERILEN_SISTEM_DB,
        "firma_db": ONERILEN_FIRMA_DB,
        "profil": PROFIL_ADI,
        "onceki_yedek": str(ONCEKI),
    }


def geri_yap() -> dict:
    aktif = _aktif()
    if not ONCEKI.exists():
        raise SystemExit(f"Önceki yedek yok: {ONCEKI}")
    shutil.copy2(ONCEKI, aktif)
    onceki = json.loads(ONCEKI.read_text(encoding="utf-8-sig"))
    pg = onceki.get("postgres") or {}
    return {
        "durum": "GERI_KABUL",
        "sistem_db": pg.get("sistem_db"),
        "firma_db": pg.get("firma_db"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("komut", choices=("d2", "geri", "durum"))
    a = p.parse_args()
    if a.komut == "d2":
        o = d2_yap()
    elif a.komut == "geri":
        o = geri_yap()
    else:
        aktif = json.loads(_aktif().read_text(encoding="utf-8-sig"))
        pg = aktif.get("postgres") or {}
        o = {
            "durum": "DURUM",
            "sistem_db": pg.get("sistem_db"),
            "firma_db": pg.get("firma_db"),
            "onceki_yedek_var": ONCEKI.exists(),
        }
    print(json.dumps(o, ensure_ascii=False, indent=2))
    (CALISMA / "D2_BAGLANTI_GECIS_OZET.json").write_text(
        json.dumps({**o, "zaman": datetime.now().astimezone().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
