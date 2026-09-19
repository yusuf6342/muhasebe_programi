"""Belge kullanıcı damgası + oturum zorunluluğu + audit yardımcıları.

SessionManager (oturum) üzerinden aktif kullanıcı alınır.
created_by alanları yalnızca ilk kayıtta yazılır; UPDATE ile değiştirilmez.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from database.session_manager import oturum

_LOG = logging.getLogger("user_audit")

ESKI_KAYIT = "Eski Kayıt"


class OturumGerekli(ValueError):
    """Aktif kullanıcı yokken belge kaydı."""


def require_user_session() -> None:
    if not oturum.oturum_acik or not oturum.user_id:
        raise OturumGerekli(
            "İşlemi kaydedebilmek için kullanıcı oturumu açılmalıdır."
        )


def current_actor() -> dict[str, Any]:
    """Aktif oturum anlık görüntüsü (ID + o andaki ad)."""
    require_user_session()
    return {
        "user_id": int(oturum.user_id),
        "username": (oturum.kullanici_adi or "").strip() or str(oturum.user_id),
        "full_name": (oturum.ad_soyad or oturum.kullanici_adi or "").strip()
        or str(oturum.user_id),
        "role": oturum.role_kod,
        "now": datetime.now(),
    }


def display_user(full_name: str | None, user_id: int | None = None) -> str:
    ad = (full_name or "").strip()
    if ad:
        return ad
    if user_id:
        return f"Kullanıcı #{user_id}"
    return ESKI_KAYIT


def format_dt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y %H:%M")
    return str(dt)


def stamp_create(obj) -> None:
    """İlk oluşturma damgası — created_by doluysa dokunma."""
    actor = current_actor()
    if getattr(obj, "created_by_user_id", None) is None:
        obj.created_by_user_id = actor["user_id"]
        obj.created_by_username = actor["username"]
        obj.created_by_full_name = actor["full_name"]
    # olusturma_tarihi modeli zaten default; yoksa yaz
    if hasattr(obj, "olusturma_tarihi") and getattr(obj, "olusturma_tarihi", None) is None:
        obj.olusturma_tarihi = actor["now"]


def stamp_update(obj) -> None:
    actor = current_actor()
    obj.updated_by_user_id = actor["user_id"]
    obj.updated_by_username = actor["username"]
    obj.updated_by_full_name = actor["full_name"]
    obj.updated_at = actor["now"]


def stamp_approve(obj) -> None:
    actor = current_actor()
    obj.approved_by_user_id = actor["user_id"]
    obj.approved_by_full_name = actor["full_name"]
    obj.approved_at = actor["now"]


def stamp_cancel(obj, reason: str) -> None:
    actor = current_actor()
    obj.cancelled_by_user_id = actor["user_id"]
    obj.cancelled_by_full_name = actor["full_name"]
    obj.cancelled_at = actor["now"]
    obj.cancellation_reason = (reason or "").strip() or None


def audit_document(
    islem_turu: str,
    *,
    modul: str,
    kayit_id: str | None = None,
    belge_no: str | None = None,
    eski: dict | None = None,
    yeni: dict | None = None,
    aciklama: str | None = None,
) -> None:
    """system.db audit_logs — başarısızlık belgeyi bozmaz."""
    try:
        from database.database import get_system_session
        from database.system.auth_service import AuthService

        payload_eski = None
        payload_yeni = None
        if eski is not None or yeni is not None or belge_no or aciklama:
            payload_yeni = json.dumps(
                {
                    "belge_no": belge_no,
                    "aciklama": aciklama,
                    "degisen": yeni,
                },
                ensure_ascii=False,
                default=str,
            )
            if eski is not None:
                payload_eski = json.dumps(eski, ensure_ascii=False, default=str)
        with get_system_session() as session:
            AuthService.audit(
                session,
                islem_turu,
                modul=modul,
                kayit_id=str(kayit_id) if kayit_id is not None else None,
                eski_deger=payload_eski,
                yeni_deger=payload_yeni,
            )
            session.commit()
    except Exception as exc:
        _LOG.warning("Audit yazılamadı (%s): %s", islem_turu, exc)


# Soft ALTER kolon tanımları (firma DB)
BELGE_KULLANICI_KOLONLARI: dict[str, str] = {
    "created_by_user_id": "INTEGER",
    "created_by_username": "VARCHAR(80)",
    "created_by_full_name": "VARCHAR(120)",
    "updated_by_user_id": "INTEGER",
    "updated_by_username": "VARCHAR(80)",
    "updated_by_full_name": "VARCHAR(120)",
    "updated_at": "DATETIME",
    "approved_by_user_id": "INTEGER",
    "approved_by_full_name": "VARCHAR(120)",
    "approved_at": "DATETIME",
    "cancelled_by_user_id": "INTEGER",
    "cancelled_by_full_name": "VARCHAR(120)",
    "cancelled_at": "DATETIME",
    "cancellation_reason": "VARCHAR(500)",
}

HIZLI_EK_KOLONLAR: dict[str, str] = {
    "tahsilat_alan_user_id": "INTEGER",
    "tahsilat_alan_full_name": "VARCHAR(120)",
    "kasa_terminal": "VARCHAR(80)",
    "satis_baslangic": "DATETIME",
    "satis_bitis": "DATETIME",
    "sales_person_id": "INTEGER",
    "sales_person_full_name": "VARCHAR(120)",
}


def belge_kullanici_schema_guncelle(engine=None) -> None:
    """satis_siparisleri / satis_faturalari kullanıcı kolonlarını ekler (idempotent).

    Migration öncesi: mevcut company yedekleme (CompanyService.yedek_al / gecis yedek)
    önerilir; ALTER yalnızca eksik kolon ekler, mevcut satır değerlerini değiştirmez.
    """
    from sqlalchemy import inspect, text

    from database.database import engine as default_engine

    eng = engine or default_engine
    if eng is None:
        return
    insp = inspect(eng)

    def _ekle(tablo: str, kolonlar: dict[str, str]) -> None:
        if not insp.has_table(tablo):
            return
        mevcut = {s["name"] for s in insp.get_columns(tablo)}
        eksik = {a: t for a, t in kolonlar.items() if a not in mevcut}
        if not eksik:
            return
        # Soft ALTER — eski kayıtlar NULL kalır (Eski Kayıt gösterimi)
        with eng.begin() as connection:
            for alan, tip in eksik.items():
                connection.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}'))
        # İndeksler (yoksa)
        with eng.begin() as connection:
            for idx, col in (
                (f"ix_{tablo}_created_by", "created_by_user_id"),
                (f"ix_{tablo}_updated_at", "updated_at"),
                (f"ix_{tablo}_sales_person", "sales_person_id"),
            ):
                if col in kolonlar:
                    try:
                        connection.execute(
                            text(
                                f'CREATE INDEX IF NOT EXISTS "{idx}" ON "{tablo}" ("{col}")'
                            )
                        )
                    except Exception:
                        pass

    _ekle("satis_siparisleri", BELGE_KULLANICI_KOLONLARI)
    _ekle("satis_faturalari", {**BELGE_KULLANICI_KOLONLARI, **HIZLI_EK_KOLONLAR})
