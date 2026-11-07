"""D2 kaynak filtre yardımcısı — etki tarihi ölçütü; alma zamanı ayrı.

  from tools.dnm_d2.kaynak_filtre import kayit_d2_kapsaminda_mi
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from tools.dnm_d1._ortak import parse_tarih
from tools.dnm_d2.donem_sabitleri import (
    D2_ACILIS_YEREL,
    D2_BITIS_DAHIL,
    D2_HARIC_UST_SINIR,
    ISTANBUL,
    etki_d2_hareket_mi,
    kapsama_karari,
)


def parse_etki(v: Any) -> date | datetime | None:
    """Belge/hareket etki tarihi (alma zamanı değil)."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=ISTANBUL)
    if isinstance(v, date):
        return v
    if v is None or v == "":
        return None
    s = str(v).strip()
    if "T" in s or " " in s:
        try:
            # fromisoformat: 2026-11-07T14:00:00+03:00
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ISTANBUL)
            return dt
        except ValueError:
            pass
        try:
            dt = datetime.strptime(s[:19], "%d.%m.%Y %H:%M:%S")
            return dt.replace(tzinfo=ISTANBUL)
        except ValueError:
            pass
    return parse_tarih(v)


def kayit_d2_kapsaminda_mi(
    *,
    etki_tarihi: Any,
    alma_zamani: Any = None,
) -> dict[str, Any]:
    etki = parse_etki(etki_tarihi)
    alma = None
    if alma_zamani:
        alma = parse_etki(alma_zamani)
        if isinstance(alma, date) and not isinstance(alma, datetime):
            alma = datetime(alma.year, alma.month, alma.day, tzinfo=ISTANBUL)
    karar = kapsama_karari(
        etki_tarihi=etki,
        alma_zamani=alma if isinstance(alma, datetime) else None,
    )
    karar["filtre"] = {
        "baslangic": D2_ACILIS_YEREL.isoformat(),
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat(),
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat(),
    }
    karar["dahil"] = karar["etki_d2"] is True
    return karar
