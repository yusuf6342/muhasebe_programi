"""Servis sorun ve onarım günlük tabloları (firma DB)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class ServiceIssue(Base):
    """Tespit edilen servis/sistem sorunu — kullanıcı silmez (append-only yaklaşım)."""

    __tablename__ = "service_issues"
    __table_args__ = (
        Index("ix_service_issues_company_status", "company_id", "status"),
        Index("ix_service_issues_module", "module_name", "severity"),
        Index("ix_service_issues_code", "issue_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    module_name: Mapped[str] = mapped_column(String(60), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    user_message: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    technical_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auto_fixable: Mapped[str] = mapped_column(String(10), nullable=False, default="hayir")
    repair_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
    detected_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ServiceRepair(Base):
    """Onarım geçmişi — Aşama 2'de yalnızca kayıt altyapısı (onarım yok)."""

    __tablename__ = "service_repairs"
    __table_args__ = (
        Index("ix_service_repairs_issue", "issue_id"),
        Index("ix_service_repairs_company", "company_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    issue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    repair_action: Mapped[str] = mapped_column(String(120), nullable=False)
    preview_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    performed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_result: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rollback_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
