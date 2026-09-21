"""Fatura barkod / işlem mesaj servisi."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.invoice_scan_message import (
    MSG_BARCODE_NOT_FOUND,
    MSG_TECHNICAL_ERROR,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    InvoiceScanMessage,
)
from database.session_manager import oturum

_LOG = logging.getLogger("invoice_scan_message")


def schema_hazirla() -> None:
    from sqlalchemy import inspect, text

    from database.database import engine

    if engine is None:
        return
    InvoiceScanMessage.__table__.create(engine, checkfirst=True)
    insp = inspect(engine)
    if not insp.has_table("invoice_scan_messages"):
        return
    sutunlar = {c["name"] for c in insp.get_columns("invoice_scan_messages")}
    with engine.begin() as conn:
        if "resolved_stok_kodu" not in sutunlar:
            conn.execute(
                text(
                    'ALTER TABLE "invoice_scan_messages" '
                    'ADD COLUMN "resolved_stok_kodu" VARCHAR(80)'
                )
            )
        if "resolved_stok_adi" not in sutunlar:
            conn.execute(
                text(
                    'ALTER TABLE "invoice_scan_messages" '
                    'ADD COLUMN "resolved_stok_adi" VARCHAR(300)'
                )
            )


def _company_id() -> int:
    return int(oturum.company_id or 0)


def _user_id() -> int | None:
    uid = oturum.user_id
    return int(uid) if uid is not None else None


def _now() -> datetime:
    return datetime.now()


def _satir_dict(m: InvoiceScanMessage) -> dict[str, Any]:
    return {
        "id": int(m.id),
        "company_id": int(m.company_id),
        "invoice_id": int(m.invoice_id) if m.invoice_id is not None else None,
        "invoice_no": m.invoice_no or "",
        "session_key": m.session_key or "",
        "user_id": int(m.user_id) if m.user_id is not None else None,
        "barcode": m.barcode or "",
        "message_type": m.message_type,
        "message_text": m.message_text,
        "scan_count": int(m.scan_count or 1),
        "status": m.status,
        "created_at": m.created_at,
        "last_seen_at": m.last_seen_at,
        "closed_at": m.closed_at,
        "closed_by": int(m.closed_by) if m.closed_by is not None else None,
        "resolved_stok_kodu": getattr(m, "resolved_stok_kodu", None) or "",
        "resolved_stok_adi": getattr(m, "resolved_stok_adi", None) or "",
    }


def barkod_bulunamadi_kaydet(
    *,
    barcode: str,
    session_key: str | None = None,
    invoice_id: int | None = None,
    invoice_no: str | None = None,
) -> dict[str, Any] | None:
    """OPEN mesaj oluşturur veya aynı açık barkodun sayacını artırır."""
    barkod = (barcode or "").strip()
    if not barkod:
        return None
    metin = f"{barkod} nolu barkod bulunamadı."
    simdi = _now()
    cid = _company_id()
    try:
        with get_session() as session:
            q = select(InvoiceScanMessage).where(
                InvoiceScanMessage.company_id == cid,
                InvoiceScanMessage.message_type == MSG_BARCODE_NOT_FOUND,
                InvoiceScanMessage.barcode == barkod,
                InvoiceScanMessage.status == STATUS_OPEN,
            )
            if invoice_id is not None:
                q = q.where(InvoiceScanMessage.invoice_id == int(invoice_id))
            elif session_key:
                q = q.where(InvoiceScanMessage.session_key == session_key)
            else:
                q = q.where(InvoiceScanMessage.invoice_id.is_(None))
            mevcut = session.scalar(q.order_by(InvoiceScanMessage.id.desc()).limit(1))
            if mevcut is not None:
                mevcut.scan_count = int(mevcut.scan_count or 1) + 1
                mevcut.last_seen_at = simdi
                if invoice_no and not mevcut.invoice_no:
                    mevcut.invoice_no = invoice_no
                session.flush()
                return _satir_dict(mevcut)
            kayit = InvoiceScanMessage(
                company_id=cid,
                invoice_id=int(invoice_id) if invoice_id is not None else None,
                invoice_no=(invoice_no or None),
                session_key=session_key or None,
                user_id=_user_id(),
                barcode=barkod,
                message_type=MSG_BARCODE_NOT_FOUND,
                message_text=metin,
                scan_count=1,
                status=STATUS_OPEN,
                created_at=simdi,
                last_seen_at=simdi,
            )
            session.add(kayit)
            session.flush()
            return _satir_dict(kayit)
    except Exception:
        _LOG.exception("barkod_bulunamadi_kaydet başarısız | barkod=%s", barkod)
        return None


def teknik_hata_kaydet(
    *,
    message_text: str,
    barcode: str = "",
    session_key: str | None = None,
    invoice_id: int | None = None,
    invoice_no: str | None = None,
) -> dict[str, Any] | None:
    metin = (message_text or "").strip() or "Teknik hata"
    simdi = _now()
    try:
        with get_session() as session:
            kayit = InvoiceScanMessage(
                company_id=_company_id(),
                invoice_id=int(invoice_id) if invoice_id is not None else None,
                invoice_no=(invoice_no or None),
                session_key=session_key or None,
                user_id=_user_id(),
                barcode=(barcode or "").strip(),
                message_type=MSG_TECHNICAL_ERROR,
                message_text=metin[:2000],
                scan_count=1,
                status=STATUS_OPEN,
                created_at=simdi,
                last_seen_at=simdi,
            )
            session.add(kayit)
            session.flush()
            return _satir_dict(kayit)
    except Exception:
        _LOG.exception("teknik_hata_kaydet başarısız")
        return None


def mesaj_cozuldu_isaretle(
    mesaj_id: int, *, stok_kodu: str, stok_adi: str
) -> dict[str, Any] | None:
    """Barkod mesajı → Çözüldü (stok kartı oluşturuldu). Geçmişten silinmez."""
    try:
        with get_session() as session:
            m = session.get(InvoiceScanMessage, int(mesaj_id))
            if m is None or int(m.company_id) != _company_id():
                return None
            m.status = STATUS_RESOLVED
            m.closed_at = _now()
            m.closed_by = _user_id()
            m.resolved_stok_kodu = (stok_kodu or "").strip() or None
            m.resolved_stok_adi = (stok_adi or "").strip() or None
            m.message_text = (
                f"{m.barcode} nolu barkod — Çözüldü – Stok kartı oluşturuldu"
                f" ({m.resolved_stok_kodu or ''} {m.resolved_stok_adi or ''})".strip()
            )
            session.flush()
            return _satir_dict(m)
    except Exception:
        _LOG.exception("mesaj_cozuldu_isaretle başarısız | id=%s", mesaj_id)
        return None


def mesaj_kapat(mesaj_id: int) -> dict[str, Any] | None:
    try:
        with get_session() as session:
            m = session.get(InvoiceScanMessage, int(mesaj_id))
            if m is None or int(m.company_id) != _company_id():
                return None
            if m.status == STATUS_CLOSED:
                return _satir_dict(m)
            m.status = STATUS_CLOSED
            m.closed_at = _now()
            m.closed_by = _user_id()
            session.flush()
            return _satir_dict(m)
    except Exception:
        _LOG.exception("mesaj_kapat başarısız | id=%s", mesaj_id)
        return None


def mesaj_yeniden_ac(mesaj_id: int) -> dict[str, Any] | None:
    try:
        with get_session() as session:
            m = session.get(InvoiceScanMessage, int(mesaj_id))
            if m is None or int(m.company_id) != _company_id():
                return None
            m.status = STATUS_OPEN
            m.closed_at = None
            m.closed_by = None
            m.last_seen_at = _now()
            session.flush()
            return _satir_dict(m)
    except Exception:
        _LOG.exception("mesaj_yeniden_ac başarısız | id=%s", mesaj_id)
        return None


def acik_mesajlari_listele(
    *,
    invoice_id: int | None = None,
    session_key: str | None = None,
) -> list[dict[str, Any]]:
    cid = _company_id()
    with get_session() as session:
        q = select(InvoiceScanMessage).where(
            InvoiceScanMessage.company_id == cid,
            InvoiceScanMessage.status == STATUS_OPEN,
        )
        if invoice_id is not None:
            q = q.where(InvoiceScanMessage.invoice_id == int(invoice_id))
        elif session_key:
            q = q.where(InvoiceScanMessage.session_key == session_key)
        else:
            return []
        q = q.order_by(InvoiceScanMessage.last_seen_at.desc(), InvoiceScanMessage.id.desc())
        return [_satir_dict(m) for m in session.scalars(q).all()]


def fatura_mesajlarini_bagla(
    *,
    session_key: str,
    invoice_id: int,
    invoice_no: str | None = None,
) -> int:
    """Taslak ilk kayıtta session_key → invoice_id."""
    if not session_key or not invoice_id:
        return 0
    cid = _company_id()
    try:
        with get_session() as session:
            kayitlar = session.scalars(
                select(InvoiceScanMessage).where(
                    InvoiceScanMessage.company_id == cid,
                    InvoiceScanMessage.session_key == session_key,
                    InvoiceScanMessage.invoice_id.is_(None),
                )
            ).all()
            n = 0
            for m in kayitlar:
                m.invoice_id = int(invoice_id)
                if invoice_no:
                    m.invoice_no = invoice_no
                n += 1
            session.flush()
            return n
    except Exception:
        _LOG.exception("fatura_mesajlarini_bagla başarısız")
        return 0


def gecmis_listele(
    *,
    baslangic: datetime | None = None,
    bitis: datetime | None = None,
    status: str | None = None,
    barcode: str | None = None,
    invoice_no: str | None = None,
    message_type: str | None = None,
    ara: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    cid = _company_id()
    with get_session() as session:
        q = select(InvoiceScanMessage).where(InvoiceScanMessage.company_id == cid)
        if baslangic is not None:
            q = q.where(InvoiceScanMessage.created_at >= baslangic)
        if bitis is not None:
            q = q.where(InvoiceScanMessage.created_at <= bitis)
        if status in (STATUS_OPEN, STATUS_CLOSED, STATUS_RESOLVED):
            q = q.where(InvoiceScanMessage.status == status)
        if barcode:
            q = q.where(InvoiceScanMessage.barcode.contains(barcode.strip()))
        if invoice_no:
            q = q.where(InvoiceScanMessage.invoice_no.contains(invoice_no.strip()))
        if message_type:
            q = q.where(InvoiceScanMessage.message_type == message_type)
        if ara:
            a = ara.strip()
            if a:
                like = f"%{a}%"
                from sqlalchemy import or_

                q = q.where(
                    or_(
                        InvoiceScanMessage.barcode.ilike(like),
                        InvoiceScanMessage.message_text.ilike(like),
                        InvoiceScanMessage.invoice_no.ilike(like),
                    )
                )
        q = q.order_by(InvoiceScanMessage.created_at.desc()).limit(max(1, min(int(limit), 2000)))
        return [_satir_dict(m) for m in session.scalars(q).all()]
