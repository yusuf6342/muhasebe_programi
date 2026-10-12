"""inceleme\\ altına rapor yazan araçlar için önceki raporu ezmeyen dosya adı.

Ad: ``<ad>_<db kısaltması>_<YYYYmmdd_HHMMSS><uzantı>``; aynı ad varsa ``_2``, ``_3``... soneki eklenir.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def db_kisaltma(db) -> str:
    """Hedef DB dosya adı kökü: ``muhasebe.db`` → ``muhasebe``, ``company_8943108a-bbc5-...db`` → ``company_8943108a``."""
    kok = Path(str(db)).stem
    return kok.split("-")[0] if kok.startswith("company_") else kok


def benzersiz_kok(klasor, ad: str, db=None, uzantilar=(".json",), zaman: datetime | None = None) -> Path:
    """Uzantısız yol döner; verilen uzantıların hiçbiriyle mevcut dosya çakışmaz."""
    parcalar = [ad] + ([db_kisaltma(db)] if db else []) + [(zaman or datetime.now()).strftime("%Y%m%d_%H%M%S")]
    kok = Path(klasor) / "_".join(parcalar)
    aday, n = kok, 2
    while any(aday.with_name(aday.name + u).exists() for u in uzantilar):
        aday = kok.with_name(f"{kok.name}_{n}")
        n += 1
    return aday


def benzersiz_rapor_yolu(klasor, ad: str, db=None, uzanti: str = ".json", zaman: datetime | None = None) -> Path:
    kok = benzersiz_kok(klasor, ad, db, (uzanti,), zaman)
    return kok.with_name(kok.name + uzanti)
