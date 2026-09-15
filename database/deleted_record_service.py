"""Silinen kayıtlar — soft delete, günlük, geri yükleme ve arama servisleri.

Phase A: cari, stok kartı, satış faturası (taslak soft-delete / onaylı iptal log).
Phase B: belge iptal noktaları → log_cancel_only (sipariş/irsaliye/fatura/iade/çek/KK/hizmet).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, inspect, or_, select, text
from sqlalchemy.orm import Session, selectinload

from database.access import yazma_zorunlu, yetki_zorunlu
from database.database import engine, get_session
from database.models.deleted_record import DeletedRecordLog
from database.session_manager import oturum

_log = logging.getLogger(__name__)

SECRET_KEYS = frozenset(
    {
        "parola",
        "password",
        "parola_hash",
        "password_hash",
        "secret",
        "token",
        "api_key",
        "api_secret",
        "pin",
        "sifre",
    }
)

SILME_NEDENLERI = (
    "Yanlış kayıt",
    "Mükerrer kayıt",
    "Test verisi",
    "İptal / vazgeçme",
    "Düzeltme sonrası yeniden oluşturma",
    "Cari/stok birleştirme",
    "Diğer",
)

ENTITY_CARI = "cari"
ENTITY_STOK = "stok_karti"
ENTITY_SATIS_FATURA = "satis_faturasi"
ENTITY_SATIS_SIPARIS = "satis_siparisi"
ENTITY_SATIS_IRSALIYE = "satis_irsaliyesi"
ENTITY_SATIS_IADE = "satis_iade_faturasi"
ENTITY_ALIS_SIPARIS = "alis_siparisi"
ENTITY_ALIS_IRSALIYE = "alis_irsaliyesi"
ENTITY_ALIS_FATURA = "alis_faturasi"
ENTITY_ALIS_IADE = "alis_iade_faturasi"
ENTITY_HIZMET_FATURA = "hizmet_faturasi"
ENTITY_CEK_SENET = "cek_senet_evrak"
ENTITY_KK_CEKIMI = "kk_cekimi"
ENTITY_CARI_VIRMAN = "cari_virman"
ENTITY_MUHASEBE_FIS = "muhasebe_fisi"
ENTITY_STOK_BIRLESTIR = "stok_birlestir"


class SoftDeleteError(ValueError):
    """Silme / geri yükleme iş kuralı hatası."""


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat(sep=" ", timespec="seconds")
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return None
    if hasattr(obj, "hex"):
        return str(obj)
    raise TypeError(f"JSON serileştirilemez: {type(obj)!r}")


def sanitize_snapshot(data: Any) -> Any:
    """Parola / secret alanlarını JSON anlık görüntüden çıkarır."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            key = str(k).lower()
            if key in SECRET_KEYS or any(s in key for s in ("parola", "password", "secret", "token")):
                out[k] = "***"
            else:
                out[k] = sanitize_snapshot(v)
        return out
    if isinstance(data, list):
        return [sanitize_snapshot(x) for x in data]
    return data


def dumps_safe(data: Any) -> str:
    return json.dumps(sanitize_snapshot(data), ensure_ascii=False, default=_json_default, sort_keys=True)


def loads_json(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def compute_integrity_hash(
    *,
    company_id: int,
    entity_type: str,
    record_id: str,
    deleted_at: datetime,
    snapshot_json: str,
    deletion_reason: str,
    deleted_by_user_id: int | None,
) -> str:
    payload = "|".join(
        [
            str(company_id),
            entity_type,
            str(record_id),
            deleted_at.isoformat(sep=" ", timespec="seconds"),
            snapshot_json,
            deletion_reason,
            str(deleted_by_user_id or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _orm_to_dict(obj: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    data: dict[str, Any] = {}
    mapper = inspect(obj).mapper
    for col in mapper.column_attrs:
        if col.key in exclude:
            continue
        data[col.key] = getattr(obj, col.key)
    return data


def _company_id() -> int:
    cid = oturum.company_id
    if cid is None:
        # Tek firma / test: company_db id veya 0
        from database.database import company_db

        if company_db.company_id is not None:
            return int(company_db.company_id)
        raise SoftDeleteError("Aktif firma seçilmedi.")
    return int(cid)


def _user_meta() -> tuple[int | None, str | None]:
    return oturum.user_id, oturum.kullanici_adi or oturum.ad_soyad


class DeletedRecordRepository:
    """deleted_record_logs CRUD (append-only UI kuralı serviste de korunur)."""

    @staticmethod
    def add(session: Session, log: DeletedRecordLog) -> DeletedRecordLog:
        session.add(log)
        session.flush()
        return log

    @staticmethod
    def get(session: Session, log_id: int) -> DeletedRecordLog | None:
        return session.get(DeletedRecordLog, log_id)

    @staticmethod
    def find_active_for_record(
        session: Session, entity_type: str, record_id: str, company_id: int
    ) -> DeletedRecordLog | None:
        return session.scalar(
            select(DeletedRecordLog)
            .where(
                DeletedRecordLog.company_id == company_id,
                DeletedRecordLog.entity_type == entity_type,
                DeletedRecordLog.record_id == str(record_id),
                DeletedRecordLog.restore_status == "none",
            )
            .order_by(DeletedRecordLog.id.desc())
            .limit(1)
        )

    @staticmethod
    def search(
        session: Session,
        *,
        company_id: int,
        module: str | None = None,
        entity_type: str | None = None,
        restore_status: str | None = None,
        reason: str | None = None,
        q: str | None = None,
        baslangic: date | None = None,
        bitis: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DeletedRecordLog], int]:
        page = max(1, int(page or 1))
        page_size = min(200, max(1, int(page_size or 50)))
        kosullar = [DeletedRecordLog.company_id == company_id]
        if module:
            kosullar.append(DeletedRecordLog.module == module)
        if entity_type:
            kosullar.append(DeletedRecordLog.entity_type == entity_type)
        if restore_status:
            kosullar.append(DeletedRecordLog.restore_status == restore_status)
        if reason:
            kosullar.append(DeletedRecordLog.deletion_reason == reason)
        if baslangic:
            kosullar.append(DeletedRecordLog.deleted_at >= datetime.combine(baslangic, datetime.min.time()))
        if bitis:
            kosullar.append(DeletedRecordLog.deleted_at <= datetime.combine(bitis, datetime.max.time()))
        if q:
            ifade = f"%{q.strip()}%"
            kosullar.append(
                or_(
                    DeletedRecordLog.record_code.ilike(ifade),
                    DeletedRecordLog.record_title.ilike(ifade),
                    DeletedRecordLog.deletion_note.ilike(ifade),
                    DeletedRecordLog.deleted_by_username.ilike(ifade),
                )
            )
        where = and_(*kosullar)
        toplam = session.scalar(select(func.count()).select_from(DeletedRecordLog).where(where)) or 0
        kayitlar = list(
            session.scalars(
                select(DeletedRecordLog)
                .where(where)
                .order_by(DeletedRecordLog.deleted_at.desc(), DeletedRecordLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return kayitlar, int(toplam)


class AuditDeleteService:
    """Merkezi soft-delete / iptal loglama."""

    @staticmethod
    def schema_hazirla() -> None:
        """Tablo + soft-delete kolonlarını mevcut firma DB'ye ekler."""
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.deleted_record  # noqa: F401

        eng = engine
        if eng is None:
            return
        DeletedRecordLog.__table__.create(eng, checkfirst=True)

        soft_cols = {
            "is_deleted": "BOOLEAN DEFAULT 0 NOT NULL",
            "deleted_at": "DATETIME",
            "deleted_by_user_id": "INTEGER",
            "deletion_log_id": "INTEGER",
        }
        for tablo in ("cari_kartlar", "stok_kartlari", "satis_faturalari"):
            if not inspect(eng).has_table(tablo):
                continue
            mevcut = {c["name"] for c in inspect(eng).get_columns(tablo)}
            with eng.begin() as conn:
                for alan, tip in soft_cols.items():
                    if alan not in mevcut:
                        conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}'))

    @staticmethod
    def create_deletion_snapshot(entity_type: str, obj: Any, session: Session) -> dict[str, Any]:
        """Varlık + ilişkili özet anlık görüntü."""
        base = _orm_to_dict(obj)
        related = AuditDeleteService.collect_related_records(entity_type, obj, session)
        return {"entity": base, "related": related}

    @staticmethod
    def collect_related_records(entity_type: str, obj: Any, session: Session) -> list[dict[str, Any]]:
        related: list[dict[str, Any]] = []
        if entity_type == ENTITY_CARI:
            from database.models.cari import CariIslem, SatisHareketi

            n_islem = session.scalar(
                select(func.count()).select_from(CariIslem).where(CariIslem.cari_id == obj.id)
            ) or 0
            n_hareket = session.scalar(
                select(func.count()).select_from(SatisHareketi).where(SatisHareketi.cari_id == obj.id)
            ) or 0
            related.append({"type": "cari_islemleri", "count": int(n_islem)})
            related.append({"type": "cari_satis_hareketleri", "count": int(n_hareket)})
        elif entity_type == ENTITY_STOK:
            from database.models.stok import StokHareketi, StokLotu

            n_h = session.scalar(
                select(func.count()).select_from(StokHareketi).where(StokHareketi.stok_id == obj.id)
            ) or 0
            n_l = session.scalar(
                select(func.count()).select_from(StokLotu).where(StokLotu.stok_id == obj.id)
            ) or 0
            related.append({"type": "stok_hareketleri", "count": int(n_h)})
            related.append({"type": "stok_lotlari", "count": int(n_l)})
        elif entity_type in (
            ENTITY_SATIS_FATURA,
            ENTITY_SATIS_SIPARIS,
            ENTITY_SATIS_IRSALIYE,
            ENTITY_SATIS_IADE,
            ENTITY_ALIS_SIPARIS,
            ENTITY_ALIS_IRSALIYE,
            ENTITY_ALIS_FATURA,
            ENTITY_ALIS_IADE,
            ENTITY_HIZMET_FATURA,
        ):
            related.append({"type": "satirlar", "count": len(getattr(obj, "satirlar", []) or [])})
            if hasattr(obj, "tahsilatlar"):
                related.append({"type": "tahsilatlar", "count": len(getattr(obj, "tahsilatlar", []) or [])})
            if getattr(obj, "siparis_id", None):
                related.append({"type": "siparis_id", "id": obj.siparis_id})
            if getattr(obj, "irsaliye_id", None):
                related.append({"type": "irsaliye_id", "id": obj.irsaliye_id})
        elif entity_type == ENTITY_CEK_SENET:
            related.append({"type": "durum", "value": getattr(obj, "durum", None)})
            related.append({"type": "cari_id", "id": getattr(obj, "cari_id", None)})
        elif entity_type == ENTITY_KK_CEKIMI:
            related.append({"type": "musteri_id", "id": getattr(obj, "musteri_id", None)})
            related.append({"type": "tedarikci_id", "id": getattr(obj, "tedarikci_id", None)})
        return related

    @staticmethod
    def validate_delete(entity_type: str, obj: Any, session: Session) -> None:
        if obj is None:
            raise SoftDeleteError("Kayıt bulunamadı.")
        if bool(getattr(obj, "is_deleted", False)):
            raise SoftDeleteError("Kayıt zaten silinmiş.")
        if entity_type == ENTITY_CARI:
            from database.models.cari import CariIslem, SatisHareketi
            from database.models.satis_faturasi import SatisFaturasi

            acik = session.scalar(
                select(func.count())
                .select_from(SatisFaturasi)
                .where(
                    SatisFaturasi.cari_id == obj.id,
                    SatisFaturasi.durum.notin_(("İPTAL",)),
                    or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)),
                )
            ) or 0
            if acik:
                raise SoftDeleteError(
                    f"Bu carinin {acik} açık/aktif satış faturası var. Önce belgeleri iptal edin."
                )
            # Hareketli cari silinebilir (soft) ama kritik sayılır — engelleme yok
            _ = session.scalar(select(func.count()).select_from(CariIslem).where(CariIslem.cari_id == obj.id))
            _ = session.scalar(
                select(func.count()).select_from(SatisHareketi).where(SatisHareketi.cari_id == obj.id)
            )
        elif entity_type == ENTITY_STOK:
            from database.models.stok import StokLotu

            kalan = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(StokLotu.stok_id == obj.id)
            ) or 0
            if Decimal(str(kalan)) > 0:
                raise SoftDeleteError(
                    "Stok kartında kalan miktar var. Önce stokları boşaltın veya birleştirin."
                )
        elif entity_type == ENTITY_SATIS_FATURA:
            durum = (getattr(obj, "durum", "") or "").upper()
            onay = bool(getattr(obj, "onaylandi", False))
            if durum == "İPTAL":
                raise SoftDeleteError("Fatura zaten iptal edilmiş.")
            if onay or durum != "TASLAK":
                raise SoftDeleteError(
                    "Onaylı/işlem görmüş fatura silinemez. İptal işlemini kullanın."
                )

    @staticmethod
    def _impacts(entity_type: str, obj: Any, related: list[dict[str, Any]]) -> tuple[dict, dict, dict]:
        muh: dict[str, Any] = {"action": "soft_hide", "note": "Muhasebe fişi otomatik ters kayıt yazılmadı."}
        stok: dict[str, Any] = {}
        cari: dict[str, Any] = {}
        if entity_type == ENTITY_CARI:
            cari = {"cari_id": obj.id, "cari_kodu": obj.cari_kodu, "related": related}
            muh["note"] = "Cari soft-delete; mevcut hareketler korunur, yeni belge engellenir (aktif=False)."
        elif entity_type == ENTITY_STOK:
            stok = {"stok_id": obj.id, "stok_kodu": obj.stok_kodu, "related": related}
        elif entity_type == ENTITY_SATIS_FATURA:
            muh = {
                "action": "draft_soft_delete" if not getattr(obj, "onaylandi", False) else "cancel_log",
                "fatura_no": obj.fatura_no,
                "durum": obj.durum,
            }
            cari = {"cari_id": obj.cari_id}
        elif entity_type in (
            ENTITY_SATIS_SIPARIS,
            ENTITY_SATIS_IRSALIYE,
            ENTITY_SATIS_IADE,
            ENTITY_ALIS_SIPARIS,
            ENTITY_ALIS_IRSALIYE,
            ENTITY_ALIS_FATURA,
            ENTITY_ALIS_IADE,
            ENTITY_HIZMET_FATURA,
            ENTITY_CEK_SENET,
            ENTITY_KK_CEKIMI,
        ):
            muh = {"action": "cancel", "entity_type": entity_type, "durum": getattr(obj, "durum", None)}
            if getattr(obj, "cari_id", None):
                cari = {"cari_id": obj.cari_id}
            elif getattr(obj, "musteri_id", None):
                cari = {"musteri_id": obj.musteri_id, "tedarikci_id": getattr(obj, "tedarikci_id", None)}
        return muh, stok, cari

    @staticmethod
    def delete_record(
        entity_type: str,
        record_id: int | str,
        *,
        reason: str,
        note: str | None = None,
        deletion_type: str = "soft",
        critical_confirm: str | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Kaydı soft-delete eder ve silme günlüğü oluşturur (tek transaction)."""
        yazma_zorunlu("silme")
        AuditDeleteService.schema_hazirla()
        reason = (reason or "").strip()
        note = (note or "").strip() or None
        if not reason:
            raise SoftDeleteError("Silme nedeni zorunludur.")
        if reason == "Diğer" and not note:
            raise SoftDeleteError("'Diğer' seçildiğinde açıklama zorunludur.")

        def _calis(sess: Session) -> dict[str, Any]:
            obj = AuditDeleteService._load(sess, entity_type, record_id)
            AuditDeleteService.validate_delete(entity_type, obj, sess)
            is_critical = AuditDeleteService._is_critical(entity_type, obj, sess)
            beklenen = str(
                getattr(obj, "cari_kodu", None)
                or getattr(obj, "stok_kodu", None)
                or getattr(obj, "fatura_no", None)
                or record_id
            )
            # Kart / belge soft-delete her zaman kod yeniden yazımı ister
            if (critical_confirm or "").strip() != beklenen:
                raise SoftDeleteError(
                    f"Onay için kodu/numarayı tekrar yazın ({beklenen})."
                )
            if is_critical and not (critical_confirm or "").strip():
                raise SoftDeleteError(
                    f"Kritik silme: onay için kodu/numarayı tekrar yazın ({beklenen})."
                )

            company_id = _company_id()
            uid, uname = _user_meta()
            existing = DeletedRecordRepository.find_active_for_record(
                sess, entity_type, str(getattr(obj, "id", record_id)), company_id
            )
            if existing is not None:
                raise SoftDeleteError("Bu kayıt için açık bir silme günlüğü zaten var.")

            snap = AuditDeleteService.create_deletion_snapshot(entity_type, obj, sess)
            related = snap.get("related") or []
            muh, stok_i, cari_i = AuditDeleteService._impacts(entity_type, obj, related)
            now = datetime.now()
            snapshot_json = dumps_safe(snap)
            related_json = dumps_safe(related)
            code, title, amount, currency, module = AuditDeleteService._labels(entity_type, obj)

            log = DeletedRecordLog(
                company_id=company_id,
                module=module,
                entity_type=entity_type,
                record_id=str(obj.id),
                record_code=code,
                record_title=title,
                deletion_type=deletion_type,
                deletion_reason=reason,
                deletion_note=note,
                is_critical=is_critical,
                can_restore=True,
                deleted_at=now,
                deleted_by_user_id=uid,
                deleted_by_username=uname,
                snapshot_json=snapshot_json,
                related_records_json=related_json,
                accounting_impact_json=dumps_safe(muh),
                stock_impact_json=dumps_safe(stok_i),
                cari_impact_json=dumps_safe(cari_i),
                amount=amount,
                currency=currency,
                restore_status="none",
            )
            log.integrity_hash = compute_integrity_hash(
                company_id=company_id,
                entity_type=entity_type,
                record_id=str(obj.id),
                deleted_at=now,
                snapshot_json=snapshot_json,
                deletion_reason=reason,
                deleted_by_user_id=uid,
            )
            DeletedRecordRepository.add(sess, log)

            # Soft flags — log olmadan silme olmaz (önce log flush edildi)
            obj.is_deleted = True
            obj.deleted_at = now
            obj.deleted_by_user_id = uid
            obj.deletion_log_id = log.id
            if hasattr(obj, "aktif"):
                obj.aktif = False
            if entity_type == ENTITY_SATIS_FATURA and (obj.durum or "").upper() == "TASLAK":
                obj.durum = "İPTAL"
            sess.flush()
            return AuditDeleteService._log_dict(log)

        if session is not None:
            return _calis(session)
        with get_session() as sess:
            return _calis(sess)

    @staticmethod
    def log_cancel_only(
        entity_type: str,
        record_id: int | str,
        *,
        reason: str,
        note: str | None = None,
        snapshot: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Fiziksel soft-delete yapmadan iptal işlemini günlüğe yazar (onaylı fatura vb.)."""
        yazma_zorunlu("iptal", "silme")
        AuditDeleteService.schema_hazirla()

        def _calis(sess: Session) -> dict[str, Any]:
            obj = AuditDeleteService._load(sess, entity_type, record_id)
            if obj is None:
                raise SoftDeleteError("Kayıt bulunamadı.")
            company_id = _company_id()
            uid, uname = _user_meta()
            now = datetime.now()
            snap = snapshot or AuditDeleteService.create_deletion_snapshot(entity_type, obj, sess)
            related = snap.get("related") or []
            muh, stok_i, cari_i = AuditDeleteService._impacts(entity_type, obj, related)
            muh["action"] = "cancel"
            snapshot_json = dumps_safe(snap)
            code, title, amount, currency, module = AuditDeleteService._labels(entity_type, obj)
            rid_str = (
                str(getattr(obj, "belge_no", None) or obj.id)
                if entity_type == ENTITY_KK_CEKIMI
                else str(obj.id)
            )
            log = DeletedRecordLog(
                company_id=company_id,
                module=module,
                entity_type=entity_type,
                record_id=rid_str,
                record_code=code,
                record_title=title,
                deletion_type="cancel",
                deletion_reason=reason or "İptal / vazgeçme",
                deletion_note=note,
                is_critical=True,
                can_restore=False,
                deleted_at=now,
                deleted_by_user_id=uid,
                deleted_by_username=uname,
                snapshot_json=snapshot_json,
                related_records_json=dumps_safe(related),
                accounting_impact_json=dumps_safe(muh),
                stock_impact_json=dumps_safe(stok_i),
                cari_impact_json=dumps_safe(cari_i),
                amount=amount,
                currency=currency,
                restore_status="none",
            )
            log.integrity_hash = compute_integrity_hash(
                company_id=company_id,
                entity_type=entity_type,
                record_id=rid_str,
                deleted_at=now,
                snapshot_json=snapshot_json,
                deletion_reason=log.deletion_reason,
                deleted_by_user_id=uid,
            )
            DeletedRecordRepository.add(sess, log)
            if hasattr(obj, "deletion_log_id"):
                obj.deletion_log_id = log.id
            sess.flush()
            return AuditDeleteService._log_dict(log)

        if session is not None:
            return _calis(session)
        with get_session() as sess:
            return _calis(sess)

    @staticmethod
    def log_cancel_snapshot(
        entity_type: str,
        record_id: int | str,
        *,
        reason: str,
        note: str | None = None,
        snapshot: dict[str, Any],
        record_code: str | None = None,
        record_title: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        module: str = "genel",
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Fiziksel silinen / anlık görüntüsü hazır kayıtlar için iptal günlüğü (load gerekmez)."""
        yazma_zorunlu("iptal", "silme")
        AuditDeleteService.schema_hazirla()
        reason = (reason or "İptal / vazgeçme").strip()
        note = (note or "").strip() or None
        snap = snapshot if isinstance(snapshot, dict) else {"entity": snapshot}
        related = snap.get("related") if isinstance(snap.get("related"), list) else []

        def _calis(sess: Session) -> dict[str, Any]:
            company_id = _company_id()
            uid, uname = _user_meta()
            now = datetime.now()
            snapshot_json = dumps_safe(snap)
            rid_str = str(record_id)
            log = DeletedRecordLog(
                company_id=company_id,
                module=module,
                entity_type=entity_type,
                record_id=rid_str,
                record_code=record_code or rid_str,
                record_title=record_title or f"{entity_type} {rid_str}",
                deletion_type="cancel",
                deletion_reason=reason,
                deletion_note=note,
                is_critical=True,
                can_restore=False,
                deleted_at=now,
                deleted_by_user_id=uid,
                deleted_by_username=uname,
                snapshot_json=snapshot_json,
                related_records_json=dumps_safe(related),
                accounting_impact_json=dumps_safe({"action": "cancel", "entity_type": entity_type}),
                stock_impact_json="{}",
                cari_impact_json="{}",
                amount=amount,
                currency=currency,
                restore_status="none",
            )
            log.integrity_hash = compute_integrity_hash(
                company_id=company_id,
                entity_type=entity_type,
                record_id=rid_str,
                deleted_at=now,
                snapshot_json=snapshot_json,
                deletion_reason=reason,
                deleted_by_user_id=uid,
            )
            DeletedRecordRepository.add(sess, log)
            sess.flush()
            return AuditDeleteService._log_dict(log)

        if session is not None:
            return _calis(session)
        with get_session() as sess:
            return _calis(sess)

    @staticmethod
    def purge_old_logs(
        *,
        before_date: date,
        confirm_phrase: str,
        expected_count: int | None = None,
    ) -> dict[str, Any]:
        """Eski iptal / geri yüklenmiş logları fiziksel siler (yalnızca yönetici).

        Aktif soft-delete (restore_status=none ve can_restore=True) asla silinmez.
        confirm_phrase: ``SİL`` olmalı. expected_count verilirse adet uyuşmazsa iptal.
        """
        if oturum.role_kod != "YONETICI":
            raise SoftDeleteError("Fiziksel log temizliği yalnızca yönetici tarafından yapılabilir.")
        if (confirm_phrase or "").strip() != "SİL":
            raise SoftDeleteError("Onay için SİL yazılmalıdır.")
        AuditDeleteService.schema_hazirla()
        cutoff = datetime.combine(before_date, datetime.max.time())
        company_id = _company_id()
        with get_session() as session:
            adaylar = list(
                session.scalars(
                    select(DeletedRecordLog).where(
                        DeletedRecordLog.company_id == company_id,
                        DeletedRecordLog.deleted_at <= cutoff,
                        or_(
                            DeletedRecordLog.restore_status == "restored",
                            and_(
                                DeletedRecordLog.deletion_type == "cancel",
                                DeletedRecordLog.can_restore.is_(False),
                            ),
                        ),
                    )
                ).all()
            )
            adet = len(adaylar)
            if expected_count is not None and int(expected_count) != adet:
                raise SoftDeleteError(
                    f"Beklenen adet ({expected_count}) ile bulunan ({adet}) uyuşmuyor. İşlem iptal."
                )
            # Temizleme işleminin kendisi için sistem logu (append-only kaydı önce yaz)
            meta = {
                "action": "physical_purge",
                "before_date": before_date.isoformat(),
                "purged_ids": [a.id for a in adaylar],
                "count": adet,
            }
            uid, uname = _user_meta()
            now = datetime.now()
            snap_json = dumps_safe(meta)
            audit = DeletedRecordLog(
                company_id=company_id,
                module="sistem",
                entity_type="deleted_record_purge",
                record_id=f"purge-{now:%Y%m%d%H%M%S}",
                record_code="PURGE",
                record_title=f"{adet} eski silme günlüğü temizlendi",
                deletion_type="physical_delete",
                deletion_reason="Fiziksel log temizliği",
                deletion_note=f"before_date={before_date.isoformat()}",
                is_critical=True,
                can_restore=False,
                deleted_at=now,
                deleted_by_user_id=uid,
                deleted_by_username=uname,
                snapshot_json=snap_json,
                related_records_json="[]",
                accounting_impact_json="{}",
                stock_impact_json="{}",
                cari_impact_json="{}",
                restore_status="none",
            )
            audit.integrity_hash = compute_integrity_hash(
                company_id=company_id,
                entity_type=audit.entity_type,
                record_id=audit.record_id,
                deleted_at=now,
                snapshot_json=snap_json,
                deletion_reason=audit.deletion_reason,
                deleted_by_user_id=uid,
            )
            DeletedRecordRepository.add(session, audit)
            session.flush()
            for kayit in adaylar:
                session.delete(kayit)
            session.flush()
            return {"purged": adet, "audit_log_id": audit.id, "before_date": before_date.isoformat()}

    @staticmethod
    def count_purge_candidates(*, before_date: date) -> int:
        """Purge öncesi aday sayısı (yönetici)."""
        if oturum.role_kod != "YONETICI":
            raise SoftDeleteError("Yalnızca yönetici.")
        AuditDeleteService.schema_hazirla()
        cutoff = datetime.combine(before_date, datetime.max.time())
        company_id = _company_id()
        with get_session() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(DeletedRecordLog)
                    .where(
                        DeletedRecordLog.company_id == company_id,
                        DeletedRecordLog.deleted_at <= cutoff,
                        or_(
                            DeletedRecordLog.restore_status == "restored",
                            and_(
                                DeletedRecordLog.deletion_type == "cancel",
                                DeletedRecordLog.can_restore.is_(False),
                            ),
                        ),
                    )
                )
                or 0
            )

    @staticmethod
    def _load(session: Session, entity_type: str, record_id: int | str) -> Any:
        if entity_type == ENTITY_KK_CEKIMI:
            from database.models.kk_cekimi import KkCekimi

            return session.scalar(
                select(KkCekimi)
                .where(KkCekimi.belge_no == str(record_id))
                .order_by(KkCekimi.id.desc())
                .limit(1)
            )

        rid = int(record_id)
        if entity_type == ENTITY_CARI:
            from database.models.cari import Cari

            return session.get(Cari, rid)
        if entity_type == ENTITY_STOK:
            from database.models.stok import StokKarti

            return session.get(StokKarti, rid)
        if entity_type == ENTITY_SATIS_FATURA:
            from database.models.satis_faturasi import SatisFaturasi

            return session.scalar(
                select(SatisFaturasi)
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
                .where(SatisFaturasi.id == rid)
            )
        if entity_type == ENTITY_SATIS_SIPARIS:
            from database.models.satis_siparisi import SatisSiparisi

            return session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar))
                .where(SatisSiparisi.id == rid)
            )
        if entity_type == ENTITY_SATIS_IRSALIYE:
            from database.models.satis_irsaliyesi import SatisIrsaliyesi

            return session.scalar(
                select(SatisIrsaliyesi)
                .options(selectinload(SatisIrsaliyesi.satirlar))
                .where(SatisIrsaliyesi.id == rid)
            )
        if entity_type == ENTITY_SATIS_IADE:
            from database.models.satis_iade_faturasi import SatisIadeFaturasi

            return session.scalar(
                select(SatisIadeFaturasi)
                .options(selectinload(SatisIadeFaturasi.satirlar))
                .where(SatisIadeFaturasi.id == rid)
            )
        if entity_type == ENTITY_ALIS_SIPARIS:
            from database.models.alis_siparisi import AlisSiparisi

            return session.scalar(
                select(AlisSiparisi)
                .options(selectinload(AlisSiparisi.satirlar))
                .where(AlisSiparisi.id == rid)
            )
        if entity_type == ENTITY_ALIS_IRSALIYE:
            from database.models.alis_irsaliyesi import AlisIrsaliyesi

            return session.scalar(
                select(AlisIrsaliyesi)
                .options(selectinload(AlisIrsaliyesi.satirlar))
                .where(AlisIrsaliyesi.id == rid)
            )
        if entity_type == ENTITY_ALIS_FATURA:
            from database.models.alis_faturasi import AlisFaturasi

            return session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar))
                .where(AlisFaturasi.id == rid)
            )
        if entity_type == ENTITY_ALIS_IADE:
            from database.models.alis_iade_faturasi import AlisIadeFaturasi

            return session.scalar(
                select(AlisIadeFaturasi)
                .options(selectinload(AlisIadeFaturasi.satirlar))
                .where(AlisIadeFaturasi.id == rid)
            )
        if entity_type == ENTITY_HIZMET_FATURA:
            from database.models.hizmet_faturasi import HizmetFaturasi

            return session.scalar(
                select(HizmetFaturasi)
                .options(selectinload(HizmetFaturasi.satirlar))
                .where(HizmetFaturasi.id == rid)
            )
        if entity_type == ENTITY_CEK_SENET:
            from database.models.cek_senet import CekSenetEvrak

            return session.get(CekSenetEvrak, rid)
        if entity_type == ENTITY_MUHASEBE_FIS:
            from database.models.genel_muhasebe import MuhasebeFisi

            return session.scalar(
                select(MuhasebeFisi)
                .options(selectinload(MuhasebeFisi.satirlar))
                .where(MuhasebeFisi.id == rid)
            )
        raise SoftDeleteError(f"Desteklenmeyen varlık türü: {entity_type}")

    @staticmethod
    def _is_critical(entity_type: str, obj: Any, session: Session) -> bool:
        if entity_type == ENTITY_SATIS_FATURA:
            return True
        if entity_type == ENTITY_CARI:
            from database.models.cari import CariIslem

            n = session.scalar(
                select(func.count()).select_from(CariIslem).where(CariIslem.cari_id == obj.id)
            ) or 0
            return int(n) > 0
        if entity_type == ENTITY_STOK:
            from database.models.stok import StokHareketi

            n = session.scalar(
                select(func.count()).select_from(StokHareketi).where(StokHareketi.stok_id == obj.id)
            ) or 0
            return int(n) > 0
        return False

    @staticmethod
    def _labels(entity_type: str, obj: Any) -> tuple[str, str, Decimal | None, str | None, str]:
        if entity_type == ENTITY_CARI:
            return obj.cari_kodu, obj.unvan, None, None, "cari"
        if entity_type == ENTITY_STOK:
            return obj.stok_kodu, obj.stok_adi, None, None, "stok"
        if entity_type == ENTITY_SATIS_FATURA:
            tutar = getattr(obj, "tl_genel_toplam", None) or Decimal("0")
            return obj.fatura_no, f"Satış faturası {obj.fatura_no}", tutar, getattr(obj, "para_birimi", "TRY"), "satis"
        if entity_type == ENTITY_SATIS_SIPARIS:
            return (
                obj.siparis_no,
                f"Satış siparişi {obj.siparis_no}",
                None,
                None,
                "satis",
            )
        if entity_type == ENTITY_SATIS_IRSALIYE:
            return (
                obj.irsaliye_no,
                f"Satış irsaliyesi {obj.irsaliye_no}",
                None,
                None,
                "satis",
            )
        if entity_type == ENTITY_SATIS_IADE:
            return (
                obj.iade_no,
                f"Satış iade {obj.iade_no}",
                None,
                None,
                "satis",
            )
        if entity_type == ENTITY_ALIS_SIPARIS:
            return (
                obj.siparis_no,
                f"Alış siparişi {obj.siparis_no}",
                None,
                None,
                "alis",
            )
        if entity_type == ENTITY_ALIS_IRSALIYE:
            return (
                obj.irsaliye_no,
                f"Alış irsaliyesi {obj.irsaliye_no}",
                None,
                None,
                "alis",
            )
        if entity_type == ENTITY_ALIS_FATURA:
            tutar = getattr(obj, "tl_genel_toplam", None)
            return (
                obj.fatura_no,
                f"Alış faturası {obj.fatura_no}",
                tutar,
                getattr(obj, "para_birimi", "TRY"),
                "alis",
            )
        if entity_type == ENTITY_ALIS_IADE:
            return (
                obj.iade_no,
                f"Alış iade {obj.iade_no}",
                None,
                None,
                "alis",
            )
        if entity_type == ENTITY_HIZMET_FATURA:
            return (
                obj.fatura_no,
                f"Hizmet faturası {obj.fatura_no}",
                getattr(obj, "tl_genel_toplam", None),
                getattr(obj, "para_birimi", "TRY"),
                "finans",
            )
        if entity_type == ENTITY_CEK_SENET:
            kod = getattr(obj, "portfoy_no", None) or str(obj.id)
            return (
                kod,
                f"Çek/Senet {kod}",
                getattr(obj, "tutar", None),
                getattr(obj, "para_birimi", "TRY"),
                "finans",
            )
        if entity_type == ENTITY_KK_CEKIMI:
            return (
                obj.belge_no,
                f"KK çekimi {obj.belge_no}",
                getattr(obj, "tutar", None),
                "TRY",
                "finans",
            )
        if entity_type == ENTITY_MUHASEBE_FIS:
            return (
                getattr(obj, "fis_no", None) or str(obj.id),
                f"Muhasebe fişi {getattr(obj, 'fis_no', obj.id)}",
                getattr(obj, "toplam_borc", None),
                "TRY",
                "muhasebe",
            )
        return str(getattr(obj, "id", "")), entity_type, None, None, "genel"

    @staticmethod
    def _log_dict(log: DeletedRecordLog) -> dict[str, Any]:
        return {
            "id": log.id,
            "company_id": log.company_id,
            "module": log.module,
            "entity_type": log.entity_type,
            "record_id": log.record_id,
            "record_code": log.record_code,
            "record_title": log.record_title,
            "deletion_type": log.deletion_type,
            "deletion_reason": log.deletion_reason,
            "deletion_note": log.deletion_note,
            "is_critical": log.is_critical,
            "can_restore": log.can_restore,
            "deleted_at": log.deleted_at,
            "deleted_by_user_id": log.deleted_by_user_id,
            "deleted_by_username": log.deleted_by_username,
            "amount": log.amount,
            "currency": log.currency,
            "restore_status": log.restore_status,
            "restored_at": log.restored_at,
            "integrity_hash": log.integrity_hash,
            "snapshot_json": log.snapshot_json,
            "related_records_json": log.related_records_json,
            "accounting_impact_json": log.accounting_impact_json,
            "stock_impact_json": log.stock_impact_json,
            "cari_impact_json": log.cari_impact_json,
            "restore_note": log.restore_note,
        }

    @staticmethod
    def search_deleted_records(**kwargs: Any) -> dict[str, Any]:
        yetki_zorunlu("silinen_kayit_goruntuleme", "silme", "sistem_ayarlari")
        AuditDeleteService.schema_hazirla()
        company_id = kwargs.pop("company_id", None) or _company_id()
        with get_session() as session:
            kayitlar, toplam = DeletedRecordRepository.search(session, company_id=company_id, **kwargs)
            return {
                "items": [AuditDeleteService._log_dict(k) for k in kayitlar],
                "total": toplam,
                "page": kwargs.get("page", 1),
                "page_size": kwargs.get("page_size", 50),
            }

    @staticmethod
    def get_deleted_record_detail(log_id: int) -> dict[str, Any]:
        yetki_zorunlu("silinen_kayit_goruntuleme", "silme", "sistem_ayarlari")
        AuditDeleteService.schema_hazirla()
        with get_session() as session:
            log = DeletedRecordRepository.get(session, log_id)
            if log is None:
                raise SoftDeleteError("Silme günlüğü bulunamadı.")
            if log.company_id != _company_id() and oturum.role_kod != "YONETICI":
                raise SoftDeleteError("Bu kayıt başka firmaya ait.")
            detay = AuditDeleteService._log_dict(log)
            detay["snapshot"] = loads_json(log.snapshot_json, {})
            detay["related"] = loads_json(log.related_records_json, [])
            detay["accounting_impact"] = loads_json(log.accounting_impact_json, {})
            detay["stock_impact"] = loads_json(log.stock_impact_json, {})
            detay["cari_impact"] = loads_json(log.cari_impact_json, {})
            detay["integrity_ok"] = AuditDeleteService.verify_log_integrity(log)
            return detay

    @staticmethod
    def verify_log_integrity(log: DeletedRecordLog | int) -> bool:
        AuditDeleteService.schema_hazirla()
        if isinstance(log, int):
            with get_session() as session:
                kayit = DeletedRecordRepository.get(session, log)
                if kayit is None:
                    return False
                return AuditDeleteService.verify_log_integrity(kayit)
        expected = compute_integrity_hash(
            company_id=log.company_id,
            entity_type=log.entity_type,
            record_id=log.record_id,
            deleted_at=log.deleted_at,
            snapshot_json=log.snapshot_json or "{}",
            deletion_reason=log.deletion_reason,
            deleted_by_user_id=log.deleted_by_user_id,
        )
        return hmac_compare(expected, log.integrity_hash or "")

    @staticmethod
    def get_deletion_statistics(company_id: int | None = None) -> dict[str, Any]:
        yetki_zorunlu("silinen_kayit_goruntuleme", "silme", "sistem_ayarlari")
        AuditDeleteService.schema_hazirla()
        cid = company_id or _company_id()
        with get_session() as session:
            toplam = session.scalar(
                select(func.count()).select_from(DeletedRecordLog).where(DeletedRecordLog.company_id == cid)
            ) or 0
            bekleyen = session.scalar(
                select(func.count())
                .select_from(DeletedRecordLog)
                .where(
                    DeletedRecordLog.company_id == cid,
                    DeletedRecordLog.restore_status == "none",
                )
            ) or 0
            geri = session.scalar(
                select(func.count())
                .select_from(DeletedRecordLog)
                .where(
                    DeletedRecordLog.company_id == cid,
                    DeletedRecordLog.restore_status == "restored",
                )
            ) or 0
            kritik = session.scalar(
                select(func.count())
                .select_from(DeletedRecordLog)
                .where(DeletedRecordLog.company_id == cid, DeletedRecordLog.is_critical.is_(True))
            ) or 0
            by_module = dict(
                session.execute(
                    select(DeletedRecordLog.module, func.count())
                    .where(DeletedRecordLog.company_id == cid)
                    .group_by(DeletedRecordLog.module)
                ).all()
            )
            return {
                "total": int(toplam),
                "pending_restore": int(bekleyen),
                "restored": int(geri),
                "critical": int(kritik),
                "by_module": {str(k): int(v) for k, v in by_module.items()},
            }

    @staticmethod
    def export_deleted_records(
        *,
        format: str = "rows",
        **search_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Excel/PDF için satır listesi döner."""
        data = AuditDeleteService.search_deleted_records(page=1, page_size=5000, **search_kwargs)
        rows = []
        for it in data["items"]:
            rows.append(
                {
                    "id": it["id"],
                    "modul": it["module"],
                    "tur": it["entity_type"],
                    "kod": it["record_code"],
                    "baslik": it["record_title"],
                    "neden": it["deletion_reason"],
                    "not": it["deletion_note"] or "",
                    "silen": it["deleted_by_username"] or "",
                    "tarih": it["deleted_at"].strftime("%d.%m.%Y %H:%M")
                    if isinstance(it["deleted_at"], datetime)
                    else str(it["deleted_at"] or ""),
                    "durum": it["restore_status"],
                    "tutar": str(it["amount"] or ""),
                    "tip": it["deletion_type"],
                }
            )
        return rows


def hmac_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode("utf-8"), b.encode("utf-8")):
        result |= x ^ y
    return result == 0


class RestoreService:
    """Soft-delete geri yükleme."""

    @staticmethod
    def preview_restore(log_id: int) -> dict[str, Any]:
        yetki_zorunlu("silinen_kayit_geri_yukleme", "sistem_ayarlari")
        detay = AuditDeleteService.get_deleted_record_detail(log_id)
        uyarilar: list[str] = []
        if not detay.get("can_restore"):
            uyarilar.append("Bu kayıt geri yüklenemez olarak işaretlenmiş.")
        if detay.get("restore_status") == "restored":
            uyarilar.append("Kayıt zaten geri yüklenmiş.")
        if not detay.get("integrity_ok"):
            uyarilar.append("Bütünlük hash doğrulaması başarısız — veri değiştirilmiş olabilir.")
        if detay.get("deletion_type") == "cancel":
            uyarilar.append("İptal günlüğü: belge durumunu manuel kontrol edin; otomatik muhasebe ters kayıt yok.")
        from database.donem_service import DonemService

        if not DonemService.kayit_izinli_mi():
            uyarilar.append("Mali dönem kapalı — geri yükleme engellenir (yalnızca yönetici açabilir).")
        donem_ok = DonemService.kayit_izinli_mi()
        return {
            "log_id": log_id,
            "can_proceed": bool(
                detay.get("can_restore")
                and detay.get("restore_status") == "none"
                and detay.get("integrity_ok")
                and donem_ok
            ),
            "warnings": uyarilar,
            "detail": detay,
        }

    @staticmethod
    def validate_restore(log: DeletedRecordLog, session: Session) -> None:
        if not log.can_restore:
            raise SoftDeleteError("Bu kayıt geri yüklenemez.")
        if log.restore_status == "restored":
            raise SoftDeleteError("Kayıt zaten geri yüklenmiş; ikinci kez geri yüklenemez.")
        if not AuditDeleteService.verify_log_integrity(log):
            raise SoftDeleteError("Günlük bütünlüğü bozulmuş; geri yükleme engellendi.")
        if log.company_id != _company_id():
            raise SoftDeleteError("Firma uyuşmazlığı.")
        if log.deletion_type == "cancel":
            raise SoftDeleteError(
                "İptal edilen muhasebe belgeleri bu ekrandan otomatik geri yüklenmez."
            )
        from database.donem_service import DonemService

        if not DonemService.kayit_izinli_mi():
            raise SoftDeleteError("Mali dönem kapalı; geri yükleme yapılamaz.")

    @staticmethod
    def restore_record(log_id: int, *, note: str | None = None) -> dict[str, Any]:
        yazma_zorunlu("silinen_kayit_geri_yukleme", "sistem_ayarlari")
        AuditDeleteService.schema_hazirla()
        with get_session() as session:
            log = DeletedRecordRepository.get(session, log_id)
            if log is None:
                raise SoftDeleteError("Silme günlüğü bulunamadı.")
            RestoreService.validate_restore(log, session)
            obj = AuditDeleteService._load(session, log.entity_type, log.record_id)
            if obj is None:
                raise SoftDeleteError("Kaynak kayıt bulunamadı; geri yükleme yapılamaz.")
            if not bool(getattr(obj, "is_deleted", False)):
                raise SoftDeleteError("Kayıt silinmiş görünmüyor.")

            # Kod çakışması basit kontrol (aynı kod aktif başka kayıt)
            if log.entity_type == ENTITY_CARI:
                from database.models.cari import Cari

                cakisan = session.scalar(
                    select(Cari).where(
                        Cari.cari_kodu == obj.cari_kodu,
                        Cari.id != obj.id,
                        or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                    )
                )
                if cakisan:
                    raise SoftDeleteError(f"Cari kodu başka aktif kayıtta kullanılıyor: {obj.cari_kodu}")
            if log.entity_type == ENTITY_STOK:
                from database.models.stok import StokKarti

                cakisan = session.scalar(
                    select(StokKarti).where(
                        StokKarti.stok_kodu == obj.stok_kodu,
                        StokKarti.id != obj.id,
                        or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                    )
                )
                if cakisan:
                    raise SoftDeleteError(f"Stok kodu başka aktif kayıtta: {obj.stok_kodu}")

            obj.is_deleted = False
            obj.deleted_at = None
            obj.deleted_by_user_id = None
            if hasattr(obj, "aktif"):
                obj.aktif = True
            if log.entity_type == ENTITY_SATIS_FATURA and (obj.durum or "") == "İPTAL":
                # Taslak soft-delete iptale çekilmişti
                obj.durum = "TASLAK"
                obj.onaylandi = False

            uid, uname = _user_meta()
            log.restore_status = "restored"
            log.restored_at = datetime.now()
            log.restored_by_user_id = uid
            log.restored_by_username = uname
            log.restore_note = (note or "").strip() or None
            session.flush()
            return AuditDeleteService._log_dict(log)

    @staticmethod
    def restore_related_records(log_id: int) -> dict[str, Any]:
        """Phase A: bağlı kayıtlar soft-delete edilmedi; bilgi amaçlı stub."""
        preview = RestoreService.preview_restore(log_id)
        related = (preview.get("detail") or {}).get("related") or []
        return {
            "log_id": log_id,
            "restored_related": [],
            "skipped": related,
            "note": "Phase A: bağlı hareketler soft-delete edilmedi; ana kayıt geri yüklenir.",
        }


# Servis API alias'ları (spec isimleri)
delete_record = AuditDeleteService.delete_record
create_deletion_snapshot = AuditDeleteService.create_deletion_snapshot
collect_related_records = AuditDeleteService.collect_related_records
validate_delete = AuditDeleteService.validate_delete
search_deleted_records = AuditDeleteService.search_deleted_records
get_deleted_record_detail = AuditDeleteService.get_deleted_record_detail
preview_restore = RestoreService.preview_restore
validate_restore = RestoreService.validate_restore
restore_record = RestoreService.restore_record
restore_related_records = RestoreService.restore_related_records
verify_log_integrity = AuditDeleteService.verify_log_integrity
export_deleted_records = AuditDeleteService.export_deleted_records
get_deletion_statistics = AuditDeleteService.get_deletion_statistics
purge_old_logs = AuditDeleteService.purge_old_logs
count_purge_candidates = AuditDeleteService.count_purge_candidates


def safe_log_cancel(
    entity_type: str,
    record_id: int | str,
    *,
    note: str,
    reason: str = "İptal / vazgeçme",
) -> dict[str, Any] | None:
    """Belge iptali sonrası günlük yazar; hata iptali bozmaz (log'a yazılır)."""
    try:
        return AuditDeleteService.log_cancel_only(
            entity_type,
            record_id,
            reason=reason,
            note=note,
        )
    except Exception as exc:  # noqa: BLE001 — iptal başarılıysa log hatası kullanıcıya yansımasın
        _log.exception("Silinen kayıt günlüğü yazılamadı (%s/%s): %s", entity_type, record_id, exc)
        return None


def safe_log_cancel_snapshot(
    entity_type: str,
    record_id: int | str,
    *,
    note: str,
    snapshot: dict[str, Any],
    reason: str = "İptal / vazgeçme",
    record_code: str | None = None,
    record_title: str | None = None,
    amount: Decimal | None = None,
    module: str = "genel",
) -> dict[str, Any] | None:
    try:
        return AuditDeleteService.log_cancel_snapshot(
            entity_type,
            record_id,
            reason=reason,
            note=note,
            snapshot=snapshot,
            record_code=record_code,
            record_title=record_title,
            amount=amount,
            module=module,
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("Snapshot iptal günlüğü yazılamadı (%s/%s): %s", entity_type, record_id, exc)
        return None
