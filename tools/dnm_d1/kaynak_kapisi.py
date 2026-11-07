"""Kaynak kapanış kapısı (K05) — mali yazımdan önce zorunlu.

Boş rapor / eksik modül / SHA yokken yazımı reddeder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK

# Talimat Modül 01–19 için asgari beklenen kaynak rapor kök adları
ASGARI_MODULLER = (
    "FIRMA_DONEM",
    "CARI",
    "ACIK_KALEM",
    "STOK_MIKTAR",
    "STOK_MALIYET_LOT",
    "KASA",
    "BANKA",
    "POS",
    "KART_KREDI",
    "GIDER_GELIR",
    "BELGE",
    "MANIFEST",
)


def _manifest_oku() -> dict[str, Any]:
    yol = CALISMA / "CALISMA_MANIFESTI.json"
    if not yol.is_file():
        raise FileNotFoundError(f"Çalışma manifesti yok: {yol}")
    return json.loads(yol.read_text(encoding="utf-8"))


def kaynak_raporlari_tara() -> dict[str, Any]:
    klasor = CALISMA / "kaynak"
    klasor.mkdir(parents=True, exist_ok=True)
    bulunan: dict[str, list[str]] = {m: [] for m in ASGARI_MODULLER}
    diger: list[str] = []
    for p in sorted(klasor.glob(f"{RAPOR_ONEKI_KAYNAK}*")):
        if p.suffix.lower() not in {".json", ".csv", ".xlsx", ".txt", ".sha256"}:
            continue
        ad = p.name
        eslesti = False
        for m in ASGARI_MODULLER:
            if f"{RAPOR_ONEKI_KAYNAK}{m}" in ad.upper().replace("-", "_"):
                bulunan[m].append(ad)
                eslesti = True
                break
        if not eslesti:
            diger.append(ad)
    return {"bulunan": bulunan, "diger": diger, "klasor": str(klasor)}


def mali_yazim_izinli_mi() -> tuple[bool, list[str]]:
    """True yalnız K05 kapısı ve hedef izolasyonu işaretliyse."""
    engeller: list[str] = []
    try:
        m = _manifest_oku()
    except FileNotFoundError as exc:
        return False, [str(exc)]

    kapilar = m.get("uygulama_kapilari") or {}
    if not kapilar.get("K05_kaynak_kapanis_tamam"):
        engeller.append("K05 kaynak kapanışı tamamlanmadı")
    if not kapilar.get("K06_hedef_izolasyonu"):
        engeller.append("K06 hedef izolasyonu tamamlanmadı")
    if not kapilar.get("mali_yazim_izinli"):
        engeller.append("mali_yazim_izinli=false (manifest)")
    if (m.get("kaynak") or {}).get("gercek_bakiyeler") != "ALINDI":
        engeller.append("gercek_bakiyeler henüz ALINDI değil")
    if (m.get("hedef") or {}).get("uygulama_durumu") != "OLUSTURULDU":
        engeller.append("hedef veritabanı HENÜZ OLUŞTURULMADI / OLUŞTURULDU değil")

    tarama = kaynak_raporlari_tara()
    eksik = [k for k, v in tarama["bulunan"].items() if not v]
    if eksik:
        engeller.append("eksik kaynak raporları: " + ", ".join(eksik))

    return (len(engeller) == 0), engeller


def main() -> int:
    ok, engeller = mali_yazim_izinli_mi()
    tarama = kaynak_raporlari_tara()
    print("KAYNAK_KLASOR", tarama["klasor"], flush=True)
    for m, dosyalar in tarama["bulunan"].items():
        print(f"  {m}: {len(dosyalar)}", flush=True)
    print("MALI_YAZIM", "IZINLI" if ok else "ENGELLI", flush=True)
    for e in engeller:
        print("ENGEL", e, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
