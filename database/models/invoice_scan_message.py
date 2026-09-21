"""Fatura barkod / işlem mesajları — kalıcı kayıt modeli."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

MSG_BARCODE_NOT_FOUND = "BARCODE_NOT_FOUND"
MSG_TECHNICAL_ERROR = "TECHNICAL_ERROR"
STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUS_RESOLVED = "RESOLVED"


class InvoiceScanMessage(Base):
    """Satış faturası barkod/işlem mesajları (append-only geçmiş)."""

    __tablename__ = "invoice_scan_messages"
    __table_args__ = (
        Index("ix_inv_scan_msg_company_status", "company_id", "status"),
        Index("ix_inv_scan_msg_invoice", "invoice_id", "status"),
        Index("ix_inv_scan_msg_session", "session_key", "status"),
        Index("ix_inv_scan_msg_barcode", "barcode"),
        Index("ix_inv_scan_msg_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    invoice_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("satis_faturalari.id", ondelete="SET NULL"),
        nullable=True,
    )
    invoice_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    session_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    scan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_stok_kodu: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_stok_adi: Mapped[str | None] = mapped_column(String(300), nullable=True)
