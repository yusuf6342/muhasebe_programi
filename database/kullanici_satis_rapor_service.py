"""Kullanıcı bazlı satış / işlem / iptal raporları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select

from database.database import get_session
from database.models.satis_faturasi import SatisFaturasi
from database.models.satis_siparisi import SatisSiparisi
from database.session_manager import oturum
from database.user_audit import display_user, format_dt


def _hizli_mi(aciklama: str | None) -> bool:
    a = (aciklama or "").casefold()
    return "hızlı satış" in a or "hizli satis" in a


def _kar_gorunsun() -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    return oturum.has_permission("kar_raporu") or oturum.has_permission("maliyet_goruntuleme")


def kullanici_bazli_satis_raporu(
    *,
    user_id: int | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
) -> list[dict[str, Any]]:
    """Kullanıcı başına sipariş/fatura/hızlı satış özeti."""
    # Satış personeli yalnızca kendi kaydını görür
    if oturum.role_kod not in ("YONETICI", "FINANS") and not oturum.has_permission("rapor_tum_kullanicilar"):
        user_id = oturum.user_id

    with get_session() as session:
        siparisler = list(session.scalars(select(SatisSiparisi)).all())
        faturalar = list(
            session.scalars(
                select(SatisFaturasi).where(
                    or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None))
                )
            ).all()
        )

    bucket: dict[int | None, dict[str, Any]] = {}

    def _b(uid: int | None, ad: str | None) -> dict[str, Any]:
        if uid not in bucket:
            bucket[uid] = {
                "user_id": uid,
                "kullanici": display_user(ad, uid),
                "siparis_adedi": 0,
                "fatura_adedi": 0,
                "hizli_satis_adedi": 0,
                "brut_satis": Decimal("0"),
                "iskonto": Decimal("0"),
                "iade": Decimal("0"),
                "net_satis": Decimal("0"),
                "tahsilat": Decimal("0"),
                "kar": Decimal("0"),
            }
        return bucket[uid]

    for s in siparisler:
        if user_id is not None and s.created_by_user_id != user_id:
            continue
        if tarih_bas and s.siparis_tarihi and s.siparis_tarihi < tarih_bas:
            continue
        if tarih_bit and s.siparis_tarihi and s.siparis_tarihi > tarih_bit:
            continue
        b = _b(s.created_by_user_id, s.created_by_full_name)
        b["siparis_adedi"] += 1

    for f in faturalar:
        if user_id is not None and f.created_by_user_id != user_id:
            continue
        if tarih_bas and f.fatura_tarihi and f.fatura_tarihi < tarih_bas:
            continue
        if tarih_bit and f.fatura_tarihi and f.fatura_tarihi > tarih_bit:
            continue
        if f.durum == "İPTAL":
            continue
        b = _b(f.created_by_user_id, f.created_by_full_name)
        tutar = Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0))
        tahsil = Decimal(str(f.tahsilat_tutari or 0))
        if _hizli_mi(f.aciklama):
            b["hizli_satis_adedi"] += 1
        else:
            b["fatura_adedi"] += 1
        b["brut_satis"] += tutar
        b["net_satis"] += tutar
        b["tahsilat"] += tahsil

    sonuc = list(bucket.values())
    for row in sonuc:
        net = row["net_satis"] or Decimal("0")
        row["kar_marji"] = (
            (row["kar"] / net * 100).quantize(Decimal("0.01")) if net else Decimal("0")
        )
        if not _kar_gorunsun():
            row["kar"] = None
            row["kar_marji"] = None
    sonuc.sort(key=lambda r: (r["kullanici"] or "").casefold())
    return sonuc


def kullanici_islem_detay_raporu(
    *,
    user_id: int | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
    belge_turu: str | None = None,
) -> list[dict[str, Any]]:
    if oturum.role_kod not in ("YONETICI", "FINANS") and not oturum.has_permission("rapor_tum_kullanicilar"):
        user_id = oturum.user_id

    satirlar: list[dict[str, Any]] = []
    with get_session() as session:
        if belge_turu in (None, "", "SIPARIS", "Tümü"):
            for s in session.scalars(select(SatisSiparisi)).all():
                if user_id is not None and s.created_by_user_id != user_id:
                    continue
                if tarih_bas and s.siparis_tarihi and s.siparis_tarihi < tarih_bas:
                    continue
                if tarih_bit and s.siparis_tarihi and s.siparis_tarihi > tarih_bit:
                    continue
                satirlar.append(
                    {
                        "tarih": format_dt(getattr(s, "olusturma_tarihi", None) or s.siparis_tarihi),
                        "kullanici": display_user(s.created_by_full_name, s.created_by_user_id),
                        "belge_turu": "Sipariş",
                        "belge_no": s.siparis_no,
                        "musteri": s.cari.unvan if s.cari else "",
                        "tutar": Decimal("0"),
                        "islem_turu": "OLUŞTURMA",
                        "durum": s.durum,
                    }
                )
        if belge_turu in (None, "", "FATURA", "HIZLI", "Tümü"):
            for f in session.scalars(
                select(SatisFaturasi).where(
                    or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None))
                )
            ).all():
                if user_id is not None and f.created_by_user_id != user_id:
                    continue
                if tarih_bas and f.fatura_tarihi and f.fatura_tarihi < tarih_bas:
                    continue
                if tarih_bit and f.fatura_tarihi and f.fatura_tarihi > tarih_bit:
                    continue
                hizli = _hizli_mi(f.aciklama)
                if belge_turu == "HIZLI" and not hizli:
                    continue
                if belge_turu == "FATURA" and hizli:
                    continue
                satirlar.append(
                    {
                        "tarih": format_dt(getattr(f, "olusturma_tarihi", None))
                        or f"{f.fatura_tarihi} {f.islem_saati or ''}".strip(),
                        "kullanici": display_user(f.created_by_full_name, f.created_by_user_id),
                        "belge_turu": "Hızlı Satış" if hizli else "Fatura",
                        "belge_no": f.fatura_no,
                        "musteri": f.cari.unvan if f.cari else "",
                        "tutar": Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0)),
                        "islem_turu": "OLUŞTURMA",
                        "durum": f.durum,
                    }
                )
    satirlar.sort(key=lambda r: str(r.get("tarih") or ""), reverse=True)
    return satirlar


def iptal_iade_raporu(
    *,
    user_id: int | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
) -> list[dict[str, Any]]:
    satirlar: list[dict[str, Any]] = []
    with get_session() as session:
        for s in session.scalars(select(SatisSiparisi).where(SatisSiparisi.durum == "İPTAL")).all():
            if user_id is not None and s.cancelled_by_user_id != user_id and s.created_by_user_id != user_id:
                continue
            ct = s.cancelled_at
            if isinstance(ct, datetime):
                cd = ct.date()
            else:
                cd = None
            if tarih_bas and cd and cd < tarih_bas:
                continue
            if tarih_bit and cd and cd > tarih_bit:
                continue
            satirlar.append(
                {
                    "belge_no": s.siparis_no,
                    "belge_turu": "Sipariş",
                    "ilk_yapan": display_user(s.created_by_full_name, s.created_by_user_id),
                    "iptal_yapan": display_user(s.cancelled_by_full_name, s.cancelled_by_user_id),
                    "iptal_tarihi": format_dt(s.cancelled_at),
                    "neden": s.cancellation_reason or "",
                    "tutar": Decimal("0"),
                }
            )
        for f in session.scalars(
            select(SatisFaturasi).where(
                SatisFaturasi.durum == "İPTAL",
                or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)),
            )
        ).all():
            if user_id is not None and f.cancelled_by_user_id != user_id and f.created_by_user_id != user_id:
                continue
            ct = f.cancelled_at
            cd = ct.date() if isinstance(ct, datetime) else None
            if tarih_bas and cd and cd < tarih_bas:
                continue
            if tarih_bit and cd and cd > tarih_bit:
                continue
            satirlar.append(
                {
                    "belge_no": f.fatura_no,
                    "belge_turu": "Hızlı Satış" if _hizli_mi(f.aciklama) else "Fatura",
                    "ilk_yapan": display_user(f.created_by_full_name, f.created_by_user_id),
                    "iptal_yapan": display_user(f.cancelled_by_full_name, f.cancelled_by_user_id),
                    "iptal_tarihi": format_dt(f.cancelled_at),
                    "neden": f.cancellation_reason or "",
                    "tutar": Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0)),
                }
            )
    return satirlar
