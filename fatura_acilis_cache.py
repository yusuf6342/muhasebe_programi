"""Satış faturası açılış — küçük tanım listeleri için firma bazlı önbellek.

TTL dolunca veya invalidate() ile yenilenir; süresiz eski veri tutulmaz.
"""

from __future__ import annotations

import time
from typing import Any, Callable

# saniye
_TTL = 120.0
_store: dict[str, tuple[float, Any]] = {}


def _firma_anahtar(ek: str) -> str:
    firma = "genel"
    try:
        from database.session_manager import oturum

        if getattr(oturum, "company_id", None):
            firma = str(oturum.company_id)
        elif getattr(oturum, "firma_kodu", None):
            firma = str(oturum.firma_kodu)
    except Exception:
        pass
    return f"{firma}:{ek}"


def get(anahtar: str, uretici: Callable[[], Any], *, ttl: float = _TTL) -> Any:
    """Önbellekten al; yoksa veya süresi dolduysa uretici() çağır."""
    k = _firma_anahtar(anahtar)
    simdi = time.monotonic()
    kayit = _store.get(k)
    if kayit is not None:
        ts, deger = kayit
        if simdi - ts < ttl:
            return deger
    deger = uretici()
    _store[k] = (simdi, deger)
    return deger


def invalidate(*anahtarlar: str) -> None:
    """Belirtilen anahtarları (veya tümünü) geçersiz kıl."""
    if not anahtarlar:
        _store.clear()
        return
    for a in anahtarlar:
        _store.pop(_firma_anahtar(a), None)


def depolar(*, aktif_only: bool = True) -> list:
    from database.stok_service import StokService

    return get(
        f"depolar:{aktif_only}",
        lambda: list(StokService.depolar(aktif_only=aktif_only)),
    )


def satis_personelleri() -> list:
    from database.satis_personeli import aktif_satis_personelleri

    return get("satis_personelleri", lambda: list(aktif_satis_personelleri()))


def para_birimleri() -> tuple:
    from database.models.doviz import PARA_BIRIMLERI

    return get("para_birimleri", lambda: tuple(PARA_BIRIMLERI), ttl=600.0)
