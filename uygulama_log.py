"""Uygulama hata günlüğü — kullanıcıya kısa mesaj, teknik ayrıntı dosyaya.

Konum: %LOCALAPPDATA%/CinMuhasebe/logs/uygulama_hata.log
"""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

_LOG_ADI = "uygulama_hata.log"


def log_dosya_yolu() -> Path:
    from hizli_satis_log import log_dizini

    return log_dizini() / _LOG_ADI


def hata_yaz(baglam: str, hata: BaseException) -> Path | None:
    """İstisnayı yığın izi ile günlüğe ekler; yazılamazsa None (akışı bozmaz)."""
    try:
        yol = log_dosya_yolu()
        iz = "".join(traceback.format_exception(type(hata), hata, hata.__traceback__))
        with yol.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {baglam}\n{iz}\n")
        return yol
    except OSError:
        return None
