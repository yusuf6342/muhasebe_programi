"""Fatura/fiş türleri 30–37 + gelir/gider — tarih filtreli tam çekim.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_belge_cek
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"
BAS = "01.01.2015"
SON = DONEM_SONU.strftime("%d.%m.%Y")


def _yaz(ad: str, veri) -> None:
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    ham = json.dumps(veri, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{sha}  {yol.name}\n", encoding="ascii")
    print("YAZILDI", yol.name, len(ham), flush=True)


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    t0 = time.time()
    alim = datetime.now().astimezone().isoformat(timespec="seconds")
    c = EvobulutClient(load_credentials())
    c.login()

    print("... gelir/gider", flush=True)
    gg = c.tum_gelir_giderleri_cek(bas_tar=BAS, son_tar=SON)
    print("    ", len(gg), flush=True)
    _yaz(
        "GIDER_GELIR",
        {
            "format": "d1-kaynak-gider-gelir-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "aralik": {"bas": BAS, "son": SON},
            "adet": len(gg),
            "kayitlar": gg,
        },
    )

    belgeler = {}
    for tur in ("30", "31", "32", "33", "34", "35", "36", "37"):
        print(f"... fatura tur={tur}", flush=True)
        liste = c.tum_faturalari_cek(tur=tur, tarih_bas=BAS, tarih_son=SON)
        belgeler[tur] = liste
        print(f"    {len(liste)}", flush=True)

    _yaz(
        "BELGE",
        {
            "format": "d1-kaynak-belge-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "aralik": {"bas": BAS, "son": SON},
            "tur_adetleri": {k: len(v) for k, v in belgeler.items()},
            "toplam": sum(len(v) for v in belgeler.values()),
            "belgeler": belgeler,
            "uyari": "Başlık listesi; satır detayları ayrıca sql ile alınacak.",
        },
    )
    print("SURE", round(time.time() - t0, 1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
