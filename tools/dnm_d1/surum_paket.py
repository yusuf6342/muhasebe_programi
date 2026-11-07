"""Sürümlü kaynak paket + kimlik eşleme + aktarım planı iskeleti.

Mevcut firma DB'lerine yazmaz. K06 beklemede kalır.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.surum_paket
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, ESLEME, KAYNAK, PLAN, SURUMLER, sha256_dosya, yaz_json
from tools.dnm_d1.donem_sabitleri import (
    DONEM_SONU,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    TALIMAT_SHA256,
)


def _dosya_ozet(yol: Path) -> dict[str, Any] | None:
    if not yol.is_file():
        return None
    return {
        "dosya": str(yol.relative_to(CALISMA)).replace("\\", "/"),
        "boyut": yol.stat().st_size,
        "sha256": sha256_dosya(yol),
    }


def _kimlik_esleme() -> dict[str, Any]:
    """Kaynak kimlik → hedef iskeleti (henüz yazım yok; cin_id boş)."""
    cari = []
    stok = []
    kasa = []
    banka = []
    cari_yol = KAYNAK / "D1_20260831_KAYNAK_CARI.json"
    stok_yol = KAYNAK / "D1_20260831_KAYNAK_STOK_MIKTAR.json"
    kasa_yol = KAYNAK / "D1_20260831_KAYNAK_KASA.json"
    banka_yol = KAYNAK / "D1_20260831_KAYNAK_BANKA.json"
    if cari_yol.is_file():
        for r in json.loads(cari_yol.read_text(encoding="utf-8")).get("kayitlar") or []:
            cid = r.get("R.a_id") or r.get("a_id")
            if cid:
                cari.append(
                    {
                        "kaynak_id": str(cid),
                        "kaynak_kod": r.get("R.a_kod") or r.get("a_kod"),
                        "kaynak_unvan": r.get("R.a_adi") or r.get("a_adi"),
                        "cin_id": None,
                    }
                )
    if stok_yol.is_file():
        for r in json.loads(stok_yol.read_text(encoding="utf-8")).get("kayitlar") or []:
            sid = r.get("a_id")
            if sid:
                stok.append(
                    {
                        "kaynak_id": str(sid),
                        "kaynak_kod": r.get("a_kod"),
                        "kaynak_adi": r.get("a_adi"),
                        "cin_id": None,
                    }
                )
    if kasa_yol.is_file():
        for r in json.loads(kasa_yol.read_text(encoding="utf-8")).get("kartlar") or []:
            kasa.append(
                {
                    "kaynak_id": str(r.get("id") or r.get("a_id")),
                    "kaynak_adi": r.get("text") or r.get("a_adi"),
                    "cin_id": None,
                }
            )
    if banka_yol.is_file():
        for r in json.loads(banka_yol.read_text(encoding="utf-8")).get("kartlar") or []:
            banka.append(
                {
                    "kaynak_id": str(r.get("id")),
                    "kaynak_adi": r.get("text"),
                    "a_posmu": r.get("a_posmu"),
                    "cin_id": None,
                }
            )
    return {
        "format": "d1-kimlik-esleme-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "kaynak_firma_no": KAYNAK_FIRMA_NO,
        "kaynak_firma_adi": KAYNAK_FIRMA_ADI,
        "hedef_sistem_db_onerilen": ONERILEN_SISTEM_DB,
        "hedef_firma_db_onerilen": ONERILEN_FIRMA_DB,
        "durum": "ISKELET_CIN_ID_BOS",
        "not": "ANA makinede K06 sonrası cin_id doldurulacak; mevcut firma DB yazımı yok.",
        "adet": {
            "cari": len(cari),
            "stok": len(stok),
            "kasa": len(kasa),
            "banka": len(banka),
        },
        "cari": cari,
        "stok": stok,
        "kasa": kasa,
        "banka": banka,
    }


def _aktarim_plani() -> dict[str, Any]:
    return {
        "format": "d1-aktarim-plani-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "motor": "tam_gecmis_d1 — evo_devir.aktarim KULLANILMAZ (bakiye-only yasak)",
        "mali_yazim": False,
        "k06_beklemede": True,
        "siralar": [
            {
                "adim": 1,
                "is": "Kaynak kapanış paketini sabitle (bu sürüm)",
                "durum": "DEVAM",
            },
            {
                "adim": 2,
                "is": "Eksik kapanışlar: açık kalem/vade, stok-LOT maliyet, kasa-banka başlangıç, POS valör, belge satır",
                "durum": "DEVAM",
            },
            {
                "adim": 3,
                "is": "ANA makinede izole cin_sistem/cin_firma_dnm_d1_20260831 oluştur (K06)",
                "durum": "BEKLIYOR",
            },
            {
                "adim": 4,
                "is": "Kaynak sürümünü yeniden doğrula; kimlik eşlemesini doldur",
                "durum": "BEKLIYOR",
            },
            {
                "adim": 5,
                "is": "Tam birinci dönem geçmişini izole hedefe yaz + kaynak-hedef mutabakat",
                "durum": "BEKLIYOR",
            },
            {
                "adim": 6,
                "is": "EXE / güncelleme paketi",
                "durum": "BEKLIYOR_TUM_ISLER_BITINCE",
            },
        ],
        "korunan_hedefler": [
            "RAY001",
            "cin_sistem",
            "cin_firma_ray",
            "cin_sistem_deneme",
            "cin_firma_deneme",
        ],
        "talimat_sha256": TALIMAT_SHA256,
    }


def main() -> int:
    now = datetime.now().astimezone()
    surum_id = now.strftime("v%Y%m%d_%H%M%S")
    hedef = SURUMLER / surum_id
    hedef.mkdir(parents=True, exist_ok=True)
    (hedef / "kaynak").mkdir(exist_ok=True)

    # Eşleme + plan (çalışma kökünde güncel + sürüm kopyası)
    esleme = _kimlik_esleme()
    plan = _aktarim_plani()
    yaz_json(ESLEME / "D1_20260831_KIMLIK_ESLEME.json", esleme)
    yaz_json(PLAN / "D1_20260831_AKTARIM_PLANI.json", plan)
    yaz_json(hedef / "D1_20260831_KIMLIK_ESLEME.json", esleme)
    yaz_json(hedef / "D1_20260831_AKTARIM_PLANI.json", plan)

    kopyalanan: list[dict[str, Any]] = []
    for yol in sorted(KAYNAK.glob("D1_20260831_KAYNAK_*.json")):
        if yol.name.endswith(".sha256"):
            continue
        dst = hedef / "kaynak" / yol.name
        shutil.copy2(yol, dst)
        sha_yol = yol.with_suffix(".sha256")
        if sha_yol.is_file():
            shutil.copy2(sha_yol, hedef / "kaynak" / sha_yol.name)
        oz = _dosya_ozet(dst)
        if oz:
            kopyalanan.append(oz)

    # kapanış tabloları (json özetler)
    for ad in (
        "D1_20260831_KAYNAK_CARI_EKSTRE_KAPANIS.json",
        "D1_20260831_KAYNAK_KASA_KAPANIS.json",
        "D1_20260831_KAYNAK_BANKA_KAPANIS.json",
        "D1_20260831_KAYNAK_POS_KART_KREDI.json",
    ):
        p = KAYNAK / ad
        if p.is_file() and not any(x["dosya"].endswith(ad) for x in kopyalanan):
            shutil.copy2(p, hedef / "kaynak" / ad)

    manifest = {
        "format": "d1-kaynak-surum-paket-v1",
        "surum_id": surum_id,
        "olusturma": now.isoformat(timespec="seconds"),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "kaynak_firma_no": KAYNAK_FIRMA_NO,
        "mali_yazim": False,
        "k05": False,
        "k06": False,
        "dosya_adet": len(kopyalanan),
        "dosyalar": kopyalanan,
        "esleme_adet": esleme["adet"],
        "plan": str((PLAN / "D1_20260831_AKTARIM_PLANI.json").relative_to(CALISMA)).replace(
            "\\", "/"
        ),
        "not": "Kapanış tamamlanınca yeni sürüm alınır; ANA makinede kaynak SHA yeniden doğrulanır.",
    }
    yaz_json(hedef / "SURUM_MANIFEST.json", manifest)
    yaz_json(SURUMLER / "SON_SURUM.json", {"surum_id": surum_id, "yol": str(hedef)})
    print("SURUM", surum_id, "dosya", len(kopyalanan), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
