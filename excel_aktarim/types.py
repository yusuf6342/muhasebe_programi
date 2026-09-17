"""Import tipi tanımı ve kayıt defteri."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AlanTanimi:
    kod: str
    baslik: str
    zorunlu: bool = False
    ornek: str = ""
    aciklama: str = ""


@dataclass
class ImportTipi:
    kod: str
    ad: str
    modul: str  # satis | satin_alma | stok | finans | gelir_gider
    alanlar: list[AlanTanimi]
    importer_factory: Callable[[], Any]
    izinler: tuple[str, ...] = ("excel_aktarim", "excel_pdf")
    aciklama: str = ""
    sablon_sayfa: str = "Veriler"
    eslesen_basliklar: dict[str, str] = field(default_factory=dict)
    # normalize_baslik -> alan.kod


_REGISTRY: dict[str, ImportTipi] = {}


def kaydet(tip: ImportTipi) -> ImportTipi:
    _REGISTRY[tip.kod] = tip
    return tip


def getir(kod: str) -> ImportTipi:
    tip = _REGISTRY.get(kod)
    if tip is None:
        raise KeyError(f"Bilinmeyen import tipi: {kod}")
    return tip


def modul_tipleri(modul: str) -> list[ImportTipi]:
    return [t for t in _REGISTRY.values() if t.modul == modul]


def tum_tipler() -> list[ImportTipi]:
    return list(_REGISTRY.values())
