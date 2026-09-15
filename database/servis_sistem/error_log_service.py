"""Servis sorun / onarım kayıt servisi."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, select

from database.database import engine, get_session
from database.servis_sistem.models import ServiceIssue, ServiceRepair
from database.session_manager import oturum

_log = logging.getLogger("cin_muhasebe.servis")

# Hassas anahtarlar — teknik detaya yazılmaz
_SECRET_FRAGMENTS = (
    "parola",
    "password",
    "secret",
    "token",
    "api_key",
    "api_secret",
    "sifre",
)


def _maskele(metin: str | None) -> str | None:
    if not metin:
        return metin
    lower = metin.lower()
    for f in _SECRET_FRAGMENTS:
        if f in lower:
            return "***"
    return metin


def _issue_to_dict(s: ServiceIssue) -> dict[str, Any]:
    return {
        "id": s.id,
        "module_name": s.module_name,
        "issue_code": s.issue_code,
        "severity": s.severity,
        "title": s.title,
        "user_message": s.user_message,
        "status": s.status,
        "auto_fixable": s.auto_fixable,
        "repair_level": int(s.repair_level or 0),
        "detected_at": s.detected_at,
        "occurrence_count": s.occurrence_count,
        "record_id": s.record_id,
        "document_number": s.document_number,
        "suggested_action": s.suggested_action,
        "technical_detail": s.technical_detail,
        "table_name": s.table_name,
        "expected_value": s.expected_value,
        "actual_value": s.actual_value,
    }


class ErrorLogService:
    @staticmethod
    def schema_hazirla() -> None:
        """service_issues / service_repairs tablolarını oluştur (checkfirst, non-destructive)."""
        import database.servis_sistem.models  # noqa: F401

        eng = engine
        if eng is None:
            return
        ServiceIssue.__table__.create(eng, checkfirst=True)
        ServiceRepair.__table__.create(eng, checkfirst=True)

    @staticmethod
    def tablolar_hazir_mi() -> bool:
        eng = engine
        if eng is None:
            return False
        insp = inspect(eng)
        return insp.has_table("service_issues") and insp.has_table("service_repairs")

    @staticmethod
    def kaydet_sorun(
        *,
        module_name: str,
        issue_code: str,
        severity: str,
        title: str,
        user_message: str = "",
        technical_detail: str | None = None,
        table_name: str | None = None,
        record_id: str | None = None,
        document_number: str | None = None,
        expected_value: str | None = None,
        actual_value: str | None = None,
        suggested_action: str | None = None,
        auto_fixable: bool = False,
        repair_level: int = 0,
        status: str = "open",
    ) -> int | None:
        """Sorunu kaydeder; başarısız olursa None (kontrol akışını bozmaz)."""
        try:
            ErrorLogService.schema_hazirla()
            company_id = int(oturum.company_id or 0)
            with get_session() as session:
                mevcut = session.scalar(
                    select(ServiceIssue).where(
                        ServiceIssue.company_id == company_id,
                        ServiceIssue.issue_code == issue_code,
                        ServiceIssue.module_name == module_name,
                        ServiceIssue.status == "open",
                        ServiceIssue.record_id == (record_id or None),
                    )
                )
                if mevcut is not None:
                    mevcut.occurrence_count = int(mevcut.occurrence_count or 1) + 1
                    mevcut.last_checked_at = datetime.now()
                    mevcut.severity = severity
                    mevcut.title = title
                    mevcut.user_message = user_message
                    mevcut.technical_detail = _maskele(technical_detail)
                    mevcut.auto_fixable = "evet" if auto_fixable else "hayir"
                    mevcut.repair_level = int(repair_level or 0)
                    if suggested_action:
                        mevcut.suggested_action = suggested_action
                    session.flush()
                    return int(mevcut.id)

                kayit = ServiceIssue(
                    company_id=company_id,
                    module_name=module_name,
                    issue_code=issue_code,
                    severity=severity,
                    title=title,
                    user_message=user_message,
                    technical_detail=_maskele(technical_detail),
                    table_name=table_name,
                    record_id=record_id,
                    document_number=document_number,
                    expected_value=expected_value,
                    actual_value=actual_value,
                    suggested_action=suggested_action,
                    auto_fixable="evet" if auto_fixable else "hayir",
                    repair_level=repair_level,
                    status=status,
                    detected_at=datetime.now(),
                    detected_by_user_id=oturum.user_id,
                    last_checked_at=datetime.now(),
                    occurrence_count=1,
                )
                session.add(kayit)
                session.flush()
                return int(kayit.id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("service_issues kaydı başarısız: %s", exc)
            return None

    @staticmethod
    def get_issue(issue_id: int) -> dict[str, Any] | None:
        ErrorLogService.schema_hazirla()
        with get_session() as session:
            s = session.get(ServiceIssue, int(issue_id))
            if s is None:
                return None
            return _issue_to_dict(s)

    @staticmethod
    def sorun_durum_guncelle(
        issue_id: int,
        status: str,
        *,
        last_checked: bool = True,
    ) -> bool:
        """Issue status günceller. Başarısızsa False (sessiz yutma yok — loglanır)."""
        try:
            ErrorLogService.schema_hazirla()
            with get_session() as session:
                s = session.get(ServiceIssue, int(issue_id))
                if s is None:
                    _log.warning("sorun_durum_guncelle: issue_id=%s bulunamadı", issue_id)
                    return False
                s.status = status
                if last_checked:
                    s.last_checked_at = datetime.now()
                session.flush()
                return True
        except Exception as exc:  # noqa: BLE001
            _log.warning("service_issues status güncelleme başarısız: %s", exc)
            return False

    @staticmethod
    def kaydet_onarim(
        *,
        issue_id: int | None,
        repair_action: str,
        preview: dict[str, Any] | None = None,
        before_data: dict[str, Any] | None = None,
        after_data: dict[str, Any] | None = None,
        backup_path: str | None = None,
        status: str = "completed",
        error_message: str | None = None,
        verification_result: str | None = None,
        rollback_status: str | None = None,
        transaction_id: str | None = None,
        started_at: datetime | None = None,
    ) -> int | None:
        """Onarım kaydı — başarısız olursa None + log."""
        try:
            ErrorLogService.schema_hazirla()
            with get_session() as session:
                kayit = ServiceRepair(
                    issue_id=issue_id,
                    company_id=int(oturum.company_id or 0),
                    repair_action=repair_action,
                    preview_json=json.dumps(preview or {}, ensure_ascii=False),
                    before_data_json=json.dumps(before_data or {}, ensure_ascii=False)
                    if before_data is not None
                    else None,
                    after_data_json=json.dumps(after_data or {}, ensure_ascii=False)
                    if after_data is not None
                    else None,
                    backup_path=backup_path,
                    started_at=started_at or datetime.now(),
                    completed_at=datetime.now(),
                    performed_by_user_id=oturum.user_id,
                    status=status,
                    error_message=_maskele(error_message),
                    transaction_id=transaction_id,
                    verification_result=verification_result,
                    rollback_status=rollback_status,
                )
                session.add(kayit)
                session.flush()
                return int(kayit.id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("service_repairs kaydı başarısız: %s", exc)
            return None

    @staticmethod
    def kaydet_onarim_stub(
        *,
        issue_id: int | None,
        repair_action: str,
        preview: dict[str, Any] | None = None,
        status: str = "preview_only",
        error_message: str | None = None,
    ) -> int | None:
        """Geriye uyumluluk — kaydet_onarim'e yönlendirir."""
        return ErrorLogService.kaydet_onarim(
            issue_id=issue_id,
            repair_action=repair_action,
            preview=preview,
            status=status,
            error_message=error_message,
            verification_result="önizleme / uygulanmadı",
        )

    @staticmethod
    def acik_sorunlar(limit: int = 200, *, status: str | None = "open") -> list[dict[str, Any]]:
        ErrorLogService.schema_hazirla()
        company_id = int(oturum.company_id or 0)
        with get_session() as session:
            q = select(ServiceIssue).where(ServiceIssue.company_id == company_id)
            if status:
                q = q.where(ServiceIssue.status == status)
            q = q.order_by(ServiceIssue.detected_at.desc()).limit(limit)
            return [_issue_to_dict(s) for s in session.scalars(q).all()]
