"""Hızlı Satış işlem günlüğü — dosyaya ekleme (Aşama 8).

Konum: %LOCALAPPDATA%/CinMuhasebe/logs/hizli_satis_islem.log
(yedek: proje data/logs). Yazıcı / WhatsApp SDK yok; yalnızca denetim satırları.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from database.session_manager import oturum

_LOG_ADI = "hizli_satis_islem.log"


def log_dizini() -> Path:
    """Öncelik: LOCALAPPDATA/CinMuhasebe/logs; yoksa proje altı data/logs."""
    adaylar = [
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CinMuhasebe" / "logs",
        Path(__file__).resolve().parent / "data" / "logs",
    ]
    for d in adaylar:
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            continue
    return Path.cwd()


def log_dosya_yolu() -> Path:
    return log_dizini() / _LOG_ADI


def _kullanici() -> str | None:
    return (
        getattr(oturum, "kullanici_adi", None)
        or getattr(oturum, "ad_soyad", None)
        or None
    )


def kayit_satiri(
    tur: str,
    mesaj: str,
    *,
    detay: dict[str, Any] | None = None,
    kullanici: str | None = None,
    zaman: datetime | None = None,
) -> str:
    """Tek satır JSON (test edilebilir / denetlenebilir)."""
    payload = {
        "zaman": (zaman or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "tur": (tur or "BILGI").strip().upper() or "BILGI",
        "kullanici": kullanici if kullanici is not None else _kullanici(),
        "mesaj": (mesaj or "").strip(),
        "detay": detay or {},
    }
    return json.dumps(payload, ensure_ascii=False)


def islem_yaz(
    tur: str,
    mesaj: str,
    *,
    detay: dict[str, Any] | None = None,
    kullanici: str | None = None,
) -> Path | None:
    """Dosyaya bir satır ekler. Hata olursa None (satışı bozmaz)."""
    try:
        yol = log_dosya_yolu()
        satir = kayit_satiri(tur, mesaj, detay=detay, kullanici=kullanici)
        with yol.open("a", encoding="utf-8") as f:
            f.write(satir + "\n")
        return yol
    except OSError:
        return None


def fiyat_degisikliklerini_yaz(
    kayitlar: list[dict[str, Any]],
    *,
    fatura_no: str | None = None,
) -> int:
    """Bellek içi fiyat/iskonto kayıtlarını dosyaya yazar. Dönüş: yazılan adet."""
    yazilan = 0
    for k in kayitlar or []:
        detay = {
            "stok_kodu": k.get("stok_kodu"),
            "alan": k.get("alan"),
            "eski": k.get("eski"),
            "yeni": k.get("yeni"),
            "not": k.get("not"),
            "fatura_no": fatura_no,
        }
        if islem_yaz(
            "FIYAT_DEGISIKLIK",
            f"{k.get('stok_kodu') or '?'} {k.get('alan')}: {k.get('eski')} → {k.get('yeni')}",
            detay=detay,
            kullanici=k.get("kullanici"),
        ):
            yazilan += 1
    return yazilan
