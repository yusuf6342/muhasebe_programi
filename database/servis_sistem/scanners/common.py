"""Salt okunur tarama yardımcıları — mutasyon yok."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from database.servis_sistem.system_health_service import (
    SEVERITY_INFO,
    SEVERITY_KRITIK,
    SEVERITY_OK,
    SEVERITY_UYARI,
    CheckItem,
    CheckReport,
)

# Tek tarama başına aynı koddan en fazla N kayıt satırı (büyük DB’de UI/performans sınırı)
MAX_ORNEK = 40
# Finans bakiye örneklemesi — tam tablo taraması değil
MAX_FINANS_BAKIYE_ORNEK = 200
TOL = 0.02


def get_engine() -> Engine | None:
    from database.database import engine

    return engine


def has_table(eng: Engine, name: str) -> bool:
    try:
        return inspect(eng).has_table(name)
    except Exception:
        return False


def table_columns(eng: Engine, name: str) -> set[str]:
    try:
        return {c["name"] for c in inspect(eng).get_columns(name)}
    except Exception:
        return set()

def onem_from(durum: str) -> str:
    return {
        SEVERITY_OK: "OK",
        SEVERITY_INFO: "Bilgi",
        SEVERITY_UYARI: "Uyarı",
        SEVERITY_KRITIK: "Kritik",
    }.get(durum, "Bilgi")


def item(
    *,
    durum: str,
    modul: str,
    hata_kodu: str,
    aciklama: str,
    kayit_belge: str = "",
    teknik: str = "",
    onerilen: str = "",
    otomatik: str = "Hayır",
) -> CheckItem:
    return CheckItem(
        durum=durum,
        onem=onem_from(durum),
        modul=modul,
        hata_kodu=hata_kodu,
        aciklama=aciklama,
        kayit_belge=kayit_belge,
        otomatik_duzeltme=otomatik,
        teknik=teknik,
        onerilen=onerilen,
    )


def ok_yok(rapor: CheckReport, modul: str, kod: str, aciklama: str) -> None:
    rapor.ekle(item(durum=SEVERITY_OK, modul=modul, hata_kodu=kod, aciklama=aciklama))


def tablo_yok(rapor: CheckReport, modul: str, tablo: str) -> None:
    rapor.ekle(
        item(
            durum=SEVERITY_INFO,
            modul=modul,
            hata_kodu="TABLO_YOK",
            aciklama=f"Tablo bulunamadı, tarama atlandı: {tablo}",
            teknik=tablo,
            onerilen="Firma şemasını / migration'ı kontrol edin.",
        )
    )


def persist_rapor(rapor: CheckReport) -> None:
    """Uyarı/kritik maddeleri service_issues'a upsert eder (iş verisine dokunmaz)."""
    try:
        from database.servis_sistem.error_log_service import ErrorLogService
        from database.servis_sistem.repair_service import LEVEL1_ACTIONS, LEVEL2_ACTIONS

        ErrorLogService.schema_hazirla()
        for m in rapor.maddeler:
            if m.durum not in (SEVERITY_UYARI, SEVERITY_KRITIK):
                continue
            code = m.hata_kodu or ""
            if code in LEVEL1_ACTIONS:
                repair_level = 1
                auto_fixable = True
            elif code in LEVEL2_ACTIONS:
                repair_level = 2
                auto_fixable = True
            else:
                repair_level = 0
                auto_fixable = (m.otomatik_duzeltme or "").lower().startswith("e")
            ErrorLogService.kaydet_sorun(
                module_name=m.modul,
                issue_code=code,
                severity=m.durum,
                title=(m.aciklama or "")[:300],
                user_message=m.aciklama or "",
                technical_detail=m.teknik or None,
                document_number=(m.kayit_belge or None)[:100] if m.kayit_belge else None,
                record_id=_record_id_from_kayit(m.kayit_belge),
                suggested_action=m.onerilen or None,
                auto_fixable=auto_fixable,
                repair_level=repair_level,
            )
    except Exception:
        pass


def _record_id_from_kayit(kayit: str) -> str | None:
    if not kayit:
        return None
    # "id=12" veya "SF-001 / id=5" kalıpları
    for part in str(kayit).replace(",", " ").split():
        if part.lower().startswith("id="):
            return part.split("=", 1)[1].strip()[:64]
    return str(kayit)[:64]


def fetchall(eng: Engine, sql: str, params: dict[str, Any] | None = None) -> list:
    with eng.connect() as conn:
        return list(conn.execute(text(sql), params or {}).mappings().all())


def fetchone_val(eng: Engine, sql: str, params: dict[str, Any] | None = None) -> Any:
    with eng.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()
