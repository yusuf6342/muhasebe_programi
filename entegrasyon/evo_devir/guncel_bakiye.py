"""Evo Bulut'un kendi hesapladığı kasa/banka bakiyeleri (salt okuma, hesap başına tek çağrı).

Evo'da ayrı bir bakiye servisi yoktur; hareket listesinin ilk sayfası, hesap ve son tarih
filtresiyle istendiğinde sunucu o hesabın toplam giriş/çıkış/fark değerini döner
(kasa: ``GRP_TOP``, banka: ``ExData``). Bu değerler bakiye kaynağı olarak kullanılır.

Kullanım:
    python -m entegrasyon.evo_devir.guncel_bakiye --devir 06.10.2026 --cikti C:\\CinMuhasebeEvoDevir\\kaynak
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from entegrasyon.evobulut_client import EvobulutClient, _ana_listesi, load_credentials

DOVIZ_ALAN = {"TL": "tl", "USD": "dolar", "EUR": "euro"}


def _toplam_blogu(veri: dict, anahtar: str) -> dict:
    blok = veri.get(anahtar)
    if isinstance(blok, list):
        blok = blok[0] if blok else {}
    return {k: str(v) for k, v in (blok or {}).items()}


def cek(devir: str, cikti_klasoru: Path) -> Path:
    t0 = time.time()
    c = EvobulutClient(load_credentials())
    c.login()
    sonuc = {
        "kaynak": "Evo Bulut API hareket listesi özet toplamı (GRP_TOP / ExData)",
        "cekilme_zamani": datetime.now().isoformat(timespec="seconds"),
        "son_tarih": devir,
        "kasalar": [],
        "bankalar": [],
    }
    kasalar = _ana_listesi(c._post("KasaHareketleri/base/", {"cmd": "kasa_listesi", "UID": c.uid, "ara": ""}))
    for k in kasalar:
        y = c._post("KasaHareketleri/base/", {
            "cmd": "jq_list", "UID": c.uid, "sayfa": "0", "cari_id": "", "bas_tar": "",
            "son_tar": devir, "kasa_id": str(k["id"]), "ara": "",
        })
        veri = y.get("veri") or {}
        sat = _ana_listesi(y)
        sonuc["kasalar"].append({
            "id": str(k["id"]), "ad": k.get("text"), "doviz": k.get("doviz_kodu") or "TL",
            "toplam": _toplam_blogu(veri, "GRP_TOP"),
            "hareket_adedi": _toplam_blogu(veri, "sayfa").get("ADET"),
            "filtre_dogru": all(str(s.get("G.a_kasa_id")) == str(k["id"]) for s in sat),
        })
    bankalar = _ana_listesi(c._post("BankHareketleri/base/", {"cmd": "banka_listesi", "UID": c.uid, "ara": ""}))
    for b in bankalar:
        y = c._post("BankHareketleri/base/", {
            "cmd": "jq_list", "UID": c.uid, "sayfa": "0", "cari_id": "", "bas_tar": " ", "vbas_tar": " ",
            "son_tar": devir, "vson_tar": "", "kasa_id": "", "ara": "", "pos_bloke": "",
            "a_banka_id": str(b["id"]),
        })
        veri = y.get("veri") or {}
        sat = _ana_listesi(y)
        sonuc["bankalar"].append({
            "id": str(b["id"]), "ad_uzunluk": len(b.get("text") or ""), "doviz": b.get("DOV_Kodu") or "TL",
            "toplam": _toplam_blogu(veri, "ExData"),
            "hareket_adedi": _toplam_blogu(veri, "sayfa").get("ADET"),
            "filtre_dogru": all(str(s.get("G.a_banka_id")) == str(b["id"]) for s in sat),
        })
    cikti_klasoru.mkdir(parents=True, exist_ok=True)
    yol = cikti_klasoru / f"evo_guncel_bakiye_{datetime.now():%Y%m%d_%H%M%S}.json"
    ham = json.dumps(sonuc, ensure_ascii=False, indent=1).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")
    print(f"{len(sonuc['kasalar'])} kasa, {len(sonuc['bankalar'])} banka; {yol} ({time.time() - t0:.0f} sn)")
    return yol


def bakiye(kayit: dict) -> str | None:
    alan = DOVIZ_ALAN.get((kayit.get("doviz") or "TL").strip().upper())
    if not alan:
        return None
    return kayit.get("toplam", {}).get(f"{alan}_Fark")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--devir", required=True, help="GG.AA.YYYY")
    p.add_argument("--cikti", default=r"C:\CinMuhasebeEvoDevir\kaynak")
    a = p.parse_args()
    cek(a.devir, Path(a.cikti))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
