"""Hata sonrası sürdürme — son güvenli aşama / sayfa / belge.

Kaldığı yerden devam ≠ kaynağı yenile. Tekrarlı çalışmada yeni mali etki yok.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]
YOL = KOK / CALISMA_KOK / "plan" / "DEVAM_KAYIT.json"


def _bos() -> dict[str, Any]:
    return {
        "format": "d2-devam-kayit-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "asama": "HAZIRLIK",
        "goruntu_kimligi": None,
        "son_tamamlanan": {
            "modul": None,
            "sayfa": None,
            "belge_id": None,
            "acilis_anahtari": None,
        },
        "hata": None,
        "guvenli_durdur": False,
        "mali_yazim_aktif": False,
        "k05": False,
        "k06": False,
    }


def yukle() -> dict[str, Any]:
    if not YOL.is_file():
        return _bos()
    return json.loads(YOL.read_text(encoding="utf-8"))


def kaydet(veri: dict[str, Any]) -> Path:
    YOL.parent.mkdir(parents=True, exist_ok=True)
    veri = dict(veri)
    veri["zaman"] = datetime.now().astimezone().isoformat(timespec="seconds")
    YOL.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    return YOL


def isaretle_tamam(
    *,
    modul: str,
    sayfa: int | None = None,
    belge_id: str | None = None,
    asama: str | None = None,
) -> dict[str, Any]:
    d = yukle()
    if asama:
        d["asama"] = asama
    d["son_tamamlanan"] = {
        "modul": modul,
        "sayfa": sayfa,
        "belge_id": belge_id,
        "acilis_anahtari": (d.get("son_tamamlanan") or {}).get("acilis_anahtari"),
    }
    d["hata"] = None
    kaydet(d)
    return d


def isaretle_hata(mesaj: str, *, modul: str | None = None) -> dict[str, Any]:
    d = yukle()
    d["hata"] = {
        "mesaj": mesaj[:500],
        "modul": modul,
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    kaydet(d)
    return d
