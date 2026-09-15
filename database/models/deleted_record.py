"""Silinen kayıt merkezi — append-only silme günlüğü."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class DeletedRecordLog(Base):
    """Firma DB içinde soft-delete / iptal günlüğü.

    UI üzerinden satır silinmez (append-only). integrity_hash ile bütünlük doğrulanır.
    """

    __tablename__ = "deleted_record_logs"
    __table_args__ = (
        Index("ix_deleted_logs_company_deleted_at", "company_id", "deleted_at"),
        Index("ix_deleted_logs_entity", "entity_type", "record_id"),
        Index("ix_deleted_logs_module_status", "module", "restore_status"),
        Index("ix_deleted_logs_deleted_by", "deleted_by_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    record_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    deletion_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="soft"
    )  # soft | cancel | reverse_log
    deletion_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    deletion_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_restore: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    related_records_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    accounting_impact_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    stock_impact_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cari_impact_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    parent_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    restore_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="none"
    )  # none | restored | failed | partial
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    restored_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restored_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    restore_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)
