"""Tek merkezî cari net bakiye hesabı (müşteri listesi + fatura Eski/Yeni).

Resmî yön: net = toplam borç − toplam alacak (CariIslem + çift kayıtsız SatisHareketi).
Taslak / iptal / soft-delete cari hareketleri CariIslem tablosuna yazılmaz; bu servis
yalnızca onaylı/bakiyeye yansıyan kayıtları kullanır.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.cari import CariIslem, SatisHareketi

logger = logging.getLogger("cari_bakiye")

KURUS = Decimal("0.01")

# Defterde SatisHareketi olarak ayrıca gösterilmeyen önekler (CariIslem zaten var)
_DEFTER_ATLA_ONEK = (
    "ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-",
    "IPT-", "FZO-",
)


def _d(deger) -> Decimal:
    if deger is None:
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return Decimal("0")


def _kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def _as_of_date(as_of) -> date | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    return None


def _aktif_company_id(company_id: int | None) -> int | None:
    """API uyumu; cari hareket tablolarında company_id yoksa yalnızca tanı için."""
    if company_id is not None:
        try:
            return int(company_id)
        except (TypeError, ValueError):
            return None
    return None


def _hareket_dahil_mi(
    hareket_tarihi: date | None,
    *,
    as_of: date | None,
    strict_before: bool,
) -> bool:
    if as_of is None:
        return True
    t = hareket_tarihi or date.min
    if strict_before:
        return t < as_of
    return t <= as_of


def _kayitlari_topla(
    session,
    cari_id: int,
    *,
    as_of: date | None,
    strict_before: bool,
    exclude_belge_no: str | None,
    currency: str | None,
) -> list[tuple[date | None, str, Decimal, Decimal]]:
    """(tarih, belge_no, borc, alacak) — müşteri listesi ile aynı kaynak."""
    cid = int(cari_id)
    haric = (exclude_belge_no or "").strip()
    pb_filtre = (currency or "").strip().upper() or None

    islemler = list(
        session.scalars(select(CariIslem).where(CariIslem.cari_id == cid)).all()
    )
    hareketler = list(
        session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cid)).all()
    )
    islem_belgeleri = {(i.belge_no or "") for i in islemler}

    kayitlar: list[tuple[date | None, str, Decimal, Decimal]] = []

    for h in hareketler:
        bn = h.belge_no or ""
        if haric and bn == haric:
            continue
        if bn in islem_belgeleri or bn.startswith(_DEFTER_ATLA_ONEK):
            continue
        if not _hareket_dahil_mi(h.satis_tarihi, as_of=as_of, strict_before=strict_before):
            continue
        if pb_filtre:
            pb = (getattr(h, "para_birimi", None) or "TRY").upper()
            if pb != pb_filtre:
                continue
        kayitlar.append(
            (h.satis_tarihi, bn, _d(h.satis_tutari), Decimal("0"))
        )

    for islem in islemler:
        bn = islem.belge_no or ""
        if haric and bn == haric:
            continue
        if not _hareket_dahil_mi(islem.tarih, as_of=as_of, strict_before=strict_before):
            continue
        if pb_filtre:
            pb = (getattr(islem, "para_birimi", None) or "TRY").upper()
            if pb != pb_filtre:
                continue
        kayitlar.append(
            (islem.tarih, bn, _d(islem.borc), _d(islem.alacak))
        )

    kayitlar.sort(key=lambda x: (x[0] or date.min, x[1] or "", str(x[2]), str(x[3])))
    return kayitlar


def net_bakiye(
    customer_id: int,
    *,
    company_id: int | None = None,
    currency: str | None = None,
    as_of_datetime: date | datetime | None = None,
    strict_before: bool = False,
    exclude_belge_no: str | None = None,
    eklenecek: Decimal | None = None,
    session=None,
    tani_log: bool = False,
) -> dict[str, Any]:
    """Müşteri listesi ile aynı formülde net cari bakiye.

    Parameters
    ----------
    customer_id
        Değişmeyen cari.id
    as_of_datetime
        None → güncel (liste bakiyesi). date/datetime → o ana kadarki hareketler.
    strict_before
        True ise yalnızca as_of tarihinden *önceki* günler (geçmiş fatura Eski Bakiye).
    exclude_belge_no
        Düzenlenen faturanın belge no'su; çift sayımı önlemek için hariç.
    eklenecek
        Bu belgenin cari etkisi (satışta borç artışı, pozitif). Yeni Bakiye = net + eklenecek.
    """
    cid = int(customer_id)
    co_id = _aktif_company_id(company_id)
    as_of = _as_of_date(as_of_datetime)
    ek = _kurus(eklenecek or 0)

    def _hesap(sess) -> dict[str, Any]:
        kayitlar = _kayitlari_topla(
            sess,
            cid,
            as_of=as_of,
            strict_before=strict_before,
            exclude_belge_no=exclude_belge_no,
            currency=currency,
        )
        toplam_borc = _kurus(sum((k[2] for k in kayitlar), Decimal("0")))
        toplam_alacak = _kurus(sum((k[3] for k in kayitlar), Decimal("0")))
        eski = _kurus(toplam_borc - toplam_alacak)
        yeni = _kurus(eski + ek)
        sonuc = {
            "customer_id": cid,
            "company_id": co_id,
            "currency": (currency or "TRY").upper(),
            "as_of": as_of,
            "strict_before": bool(strict_before),
            "exclude_belge_no": (exclude_belge_no or None),
            "hareket_sayisi": len(kayitlar),
            "toplam_borc": toplam_borc,
            "toplam_alacak": toplam_alacak,
            "bakiye": eski,  # Eski / liste net
            "eski_bakiye": eski,
            "yeni_bakiye": yeni,
            "eklenecek": ek,
        }
        if tani_log:
            logger.info(
                "cari_bakiye id=%s co=%s as_of=%s strict=%s haric=%s n=%s borc=%s alacak=%s net=%s ek=%s yeni=%s",
                cid,
                co_id,
                as_of,
                strict_before,
                exclude_belge_no,
                len(kayitlar),
                toplam_borc,
                toplam_alacak,
                eski,
                ek,
                yeni,
            )
        return sonuc

    if session is not None:
        return _hesap(session)
    with get_session() as sess:
        return _hesap(sess)


def liste_bakiyeleri(
    customer_ids: list[int],
    *,
    company_id: int | None = None,
    currency: str | None = None,
) -> dict[int, Decimal]:
    """Toplu liste bakiyesi — müşteri listesi / fatura önbelleği için."""
    ids = [int(i) for i in customer_ids if i is not None]
    if not ids:
        return {}
    sonuc: dict[int, Decimal] = {}
    with get_session() as session:
        for cid in ids:
            ozet = net_bakiye(
                cid,
                company_id=company_id,
                currency=currency,
                session=session,
            )
            sonuc[cid] = ozet["bakiye"]
    return sonuc


def fatura_eski_yeni_bakiye(
    customer_id: int,
    *,
    fatura_tarihi: date | None = None,
    fatura_saati: str | None = None,
    exclude_belge_no: str | None = None,
    belge_etkisi: Decimal | None = None,
    company_id: int | None = None,
    currency: str | None = None,
    tani_log: bool = False,
) -> dict[str, Any]:
    """Fatura Eski / Yeni Bakiye — tek servis.

    Bugün / gelecek tarihli veya tarih yok: güncel liste bakiyesi (strict_before=False, as_of=None).
    Geçmiş tarih: yalnızca fatura gününden önceki hareketler.
    exclude_belge_no: düzenlemede bu belgenin kayıtlı etkisi Eski'ye girmez.
    belge_etkisi: ekrandaki güncel açık tutar (satışta +borç).
    """
    bugun = date.today()
    ft = fatura_tarihi
    strict = bool(ft is not None and ft < bugun)
    as_of = ft if strict else None

    # Saat bilgisi ileride datetime alanına bağlanabilir; şimdilik tarih kuralı yeterli
    _ = fatura_saati

    return net_bakiye(
        customer_id,
        company_id=company_id,
        currency=currency,
        as_of_datetime=as_of,
        strict_before=strict,
        exclude_belge_no=exclude_belge_no,
        eklenecek=belge_etkisi or Decimal("0"),
        tani_log=tani_log,
    )
