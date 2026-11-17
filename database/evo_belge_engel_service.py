"""Evo Bulut evrak kaynağı engeli — silinen EVB belge yeniden aktarılmasın."""

from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.evo_belge_engel import EvoBelgeEngel

KAYNAK_EVO = "EVOBULUT"

# EVB-AF-14881 | EVB-BN-21157 | EVB-BNC-21807 | EVB-KS-99 | EVB-ACL-12 | EVB-AK-1875-DEVIREN
_EVB_RE = re.compile(
    r"^EVB-(AF|SF|BNC|BN|KS|ACL|AK|GG|GGK|KR|KK|KKD|DEVIR)[-_]?([A-Za-z0-9]+)(?:-.*)?$",
    re.I,
)

_hazir_engine_id: int | None = None


def schema_hazirla(eng=None) -> None:
    global _hazir_engine_id
    from database.database import Base, engine

    bag = eng if eng is not None else engine
    if bag is None:
        return
    if eng is None and _hazir_engine_id == id(bag):
        return
    Base.metadata.create_all(bind=bag, tables=[EvoBelgeEngel.__table__])
    if eng is None or eng is bag:
        _hazir_engine_id = id(bag)


def evo_belge_kimlikleri(belge_no: str | None) -> list[str]:
    """Belge no'dan engel anahtarları: ['AF:14881', 'EVB-AF-14881']."""
    no = (belge_no or "").strip()
    if not no:
        return []
    kimlikler = [no[:80]]
    m = _EVB_RE.match(no)
    if m:
        tur = m.group(1).upper()
        aid = m.group(2)
        kimlikler.append(f"{tur}:{aid}"[:80])
        # Banka hareketi + cari yan kaydı aynı a_id
        if tur == "BN":
            kimlikler.append(f"BNC:{aid}"[:80])
        elif tur == "BNC":
            kimlikler.append(f"BN:{aid}"[:80])
    # Tekrarları koru, sırayı sabitle
    gorulen: set[str] = set()
    sonuc: list[str] = []
    for k in kimlikler:
        if k and k not in gorulen:
            gorulen.add(k)
            sonuc.append(k)
    return sonuc


def evo_belge_engelli_mi(belge_no: str | None = None, *, kaynak_kimlik: str | None = None) -> bool:
    schema_hazirla()
    adaylar = list(evo_belge_kimlikleri(belge_no))
    if kaynak_kimlik and str(kaynak_kimlik).strip():
        adaylar.append(str(kaynak_kimlik).strip()[:80])
    if not adaylar:
        return False
    from database.database import get_session

    with get_session() as session:
        return (
            session.scalar(
                select(EvoBelgeEngel.id).where(
                    EvoBelgeEngel.kaynak_sistem == KAYNAK_EVO,
                    EvoBelgeEngel.kaynak_kimlik.in_(adaylar),
                )
            )
            is not None
        )


def evo_belge_engel_yaz(
    session: Session,
    *,
    belge_no: str | None = None,
    belge_turu: str | None = None,
    neden: str | None = None,
    ekstra_kimlikler: Iterable[str] | None = None,
) -> None:
    """Silinen/iptal edilen EVB kaynağını engelle — mükerrer yazım yok."""
    schema_hazirla()
    kimlikler = list(evo_belge_kimlikleri(belge_no))
    for ek in ekstra_kimlikler or ():
        k = str(ek or "").strip()[:80]
        if k and k not in kimlikler:
            kimlikler.append(k)
    if not kimlikler:
        return
    mevcutlar = {
        r.kaynak_kimlik
        for r in session.scalars(
            select(EvoBelgeEngel).where(
                EvoBelgeEngel.kaynak_sistem == KAYNAK_EVO,
                EvoBelgeEngel.kaynak_kimlik.in_(kimlikler),
            )
        ).all()
    }
    for kimlik in kimlikler:
        if kimlik in mevcutlar:
            continue
        session.add(
            EvoBelgeEngel(
                kaynak_sistem=KAYNAK_EVO,
                kaynak_kimlik=kimlik,
                belge_no=(belge_no or "")[:50] or None,
                belge_turu=(belge_turu or "")[:40] or None,
                neden=(neden or "")[:500] or None,
            )
        )
        mevcutlar.add(kimlik)


def evo_aktarim_engelli_mi(belge_no: str | None) -> bool:
    """Import öncesi: belge zaten var mı diye bakmadan önce engel kontrolü."""
    return evo_belge_engelli_mi(belge_no)
