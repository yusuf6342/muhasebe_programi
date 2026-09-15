"""Modül tarayıcıları — Aşama 3 salt okunur."""

from __future__ import annotations

from typing import Callable

from database.servis_sistem.scanners.cari import scan_cari
from database.servis_sistem.scanners.cek_senet import scan_cek_senet
from database.servis_sistem.scanners.dosya_kullanici import scan_dosya, scan_kullanici
from database.servis_sistem.scanners.fatura import scan_fatura
from database.servis_sistem.scanners.finans import scan_finans
from database.servis_sistem.scanners.muhasebe import scan_muhasebe
from database.servis_sistem.scanners.stok import scan_stok
from database.servis_sistem.system_health_service import CheckReport

ScanFn = Callable[[CheckReport], None]

# Sol panel kodu → tarayıcı(lar)
SCANNERS: dict[str, list[ScanFn]] = {
    "cari": [scan_cari],
    "stok": [scan_stok],
    "satis": [lambda r: scan_fatura(r, yon="satis")],
    "alis": [lambda r: scan_fatura(r, yon="alis")],
    "finans": [scan_finans],
    "cek_senet": [scan_cek_senet],
    "muhasebe": [scan_muhasebe],
    "branding": [scan_dosya],
    "yedekleme": [scan_dosya],
    "sistem": [scan_dosya, scan_kullanici],
}

# Ayrıntılı / tüm tarama sırası
DEEP_ORDER: list[str] = [
    "sistem",
    "cari",
    "stok",
    "satis",
    "alis",
    "finans",
    "cek_senet",
    "muhasebe",
]


def run_scanners(modul_kod: str, rapor: CheckReport) -> bool:
    """Modül tarayıcılarını çalıştırır. Bilinen modül ise True."""
    fns = SCANNERS.get(modul_kod)
    if not fns:
        return False
    for fn in fns:
        fn(rapor)
    return True
