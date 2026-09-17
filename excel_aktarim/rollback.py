"""Aktarım geri alma."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select

from database.database import get_session
from excel_aktarim.models import ImportBatch, ImportChange


class ImportRollbackService:
    @staticmethod
    def geri_al(batch_id: int, handler: Callable[[dict[str, Any]], None]) -> ImportBatch:
        with get_session() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            if batch.durum not in {"basarili", "kismi"}:
                raise ValueError("Yalnızca başarılı/kısmi aktarımlar geri alınabilir.")
            changes = list(
                session.scalars(
                    select(ImportChange)
                    .where(
                        ImportChange.batch_id == batch_id,
                        ImportChange.geri_alindi.is_(False),
                    )
                    .order_by(ImportChange.id.desc())
                )
            )

        for ch in changes:
            payload = {
                "hedef_tablo": ch.hedef_tablo,
                "hedef_id": ch.hedef_id,
                "islem": ch.islem,
                "onceki": json.loads(ch.onceki_json) if ch.onceki_json else None,
                "sonraki": json.loads(ch.sonraki_json) if ch.sonraki_json else None,
                "tutar": ch.tutar,
                "satir_no": ch.satir_no,
            }
            handler(payload)
            with get_session() as session:
                kayit = session.get(ImportChange, ch.id)
                if kayit:
                    kayit.geri_alindi = True
                    session.flush()

        with get_session() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            batch.durum = "geri_alindi"
            batch.notlar = ((batch.notlar or "") + "\nGeri alındı: " + datetime.now().isoformat()).strip()
            session.flush()
            session.refresh(batch)
            return batch
