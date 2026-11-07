"""DNM D1 ek kaynak modülleri — gelir/gider + fatura/fiş (≤31.08.2026).

Salt okuma. Tam K05 için ekstre/LOT/POS ayrı tamamlanır.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_modul_cek
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"
BAS = "01.01.2015"
SON = DONEM_SONU.strftime("%d.%m.%Y")


def _yaz(ad: str, veri: Any) -> Path:
    KAYNAK.mkdir(parents=True, exist_ok=True)
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    ham = json.dumps(veri, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")
    print("YAZILDI", yol.name, len(ham), "sha", ozet[:16], flush=True)
    return yol


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    t0 = time.time()
    alim = datetime.now().astimezone().isoformat(timespec="seconds")
    c = EvobulutClient(load_credentials())
    c.login()

    print("... gelir/gider", flush=True)
    gg = c.tum_gelir_giderleri_cek(bas_tar=BAS, son_tar=SON)
    print("    gg", len(gg), flush=True)
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

    belgeler: dict[str, list] = {}
    # 30..37 alış/satış fatura/fiş/iade
    for tur in (30, 31, 32, 33, 34, 35, 36, 37):
        print(f"... fatura tur={tur}", flush=True)
        try:
            if hasattr(c, "tum_faturalari_cek"):
                # satış ağırlıklı API; alış ayrı olabilir
                liste = c.tum_faturalari_cek(
                    tur=str(tur), tarih_bas=BAS, tarih_son=SON
                )
            else:
                liste = []
        except Exception as exc:  # noqa: BLE001
            print("  HATA", tur, type(exc).__name__, str(exc)[:100], flush=True)
            liste = []
        belgeler[str(tur)] = liste
        print(f"    tur={tur} adet={len(liste)}", flush=True)

    # Alış özel yol
    if hasattr(c, "tum_alis_faturalari_cek"):
        print("... alis faturalari", flush=True)
        try:
            alis = c.tum_alis_faturalari_cek(tarih_bas=BAS, tarih_son=SON)
            belgeler["alis_ozel"] = alis
            print("    alis", len(alis), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("  alis HATA", type(exc).__name__, str(exc)[:100], flush=True)

    toplam = sum(len(v) for v in belgeler.values())
    _yaz(
        "BELGE",
        {
            "format": "d1-kaynak-belge-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "aralik": {"bas": BAS, "son": SON},
            "tur_adetleri": {k: len(v) for k, v in belgeler.items()},
            "toplam": toplam,
            "belgeler": belgeler,
            "uyari": "Başlık listesi; satır detayları ayrı sql çekimi gerektirir.",
        },
    )

    # Manifest güncelle (kısmi)
    man_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}MANIFEST.json"
    if man_yol.is_file():
        man = json.loads(man_yol.read_text(encoding="utf-8"))
        man.setdefault("ozet", {})
        man["ozet"]["gider_gelir"] = len(gg)
        man["ozet"]["belge_baslik"] = toplam
        eksik = set(man.get("eksik_moduller") or [])
        eksik.discard("GIDER_GELIR")
        eksik.discard("BELGE")
        man["eksik_moduller"] = sorted(eksik)
        man["alim_zamani_modul_cek"] = alim
        man["sure_modul_cek_sn"] = round(time.time() - t0, 1)
        man_yol.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("SURE", round(time.time() - t0, 1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
