"""Batch oluşturma, yürütme, geçmiş."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.database import get_session
from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.mapping import ColumnMappingService
from excel_aktarim.models import ImportBatch, ImportChange, ImportRow
from excel_aktarim.validation import DogrulamaRaporu, SatirSonuc


def _batch_kodu() -> str:
    return datetime.now().strftime("IMP-%Y%m%d-%H%M%S")


class ImportAuditService:
    @staticmethod
    def batch_olustur(
        *,
        modul: str,
        import_tipi: str,
        dosya_adi: str | None = None,
        dosya_yolu: str | None = None,
        kullanici_id: int | None = None,
        kullanici_adi: str | None = None,
    ) -> ImportBatch:
        with get_session() as session:
            batch = ImportBatch(
                batch_kodu=_batch_kodu(),
                modul=modul,
                import_tipi=import_tipi,
                dosya_adi=dosya_adi,
                dosya_yolu=dosya_yolu,
                durum="taslak",
                kullanici_id=kullanici_id,
                kullanici_adi=kullanici_adi,
                created_at=datetime.now(),
            )
            session.add(batch)
            session.flush()
            session.refresh(batch)
            return batch

    @staticmethod
    def listele(*, modul: str | None = None, limit: int = 50) -> list[ImportBatch]:
        with get_session() as session:
            q = select(ImportBatch).where(ImportBatch.is_deleted.is_(False))
            if modul:
                q = q.where(ImportBatch.modul == modul)
            q = q.order_by(ImportBatch.id.desc()).limit(limit)
            return list(session.scalars(q))

    @staticmethod
    def getir(batch_id: int) -> ImportBatch | None:
        with get_session() as session:
            return session.get(ImportBatch, batch_id)


class ImportExecutor:
    @staticmethod
    def dry_run_kaydet(batch_id: int, rapor: DogrulamaRaporu) -> None:
        with get_session() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            # eski satırları temizle
            for eski in session.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)):
                session.delete(eski)
            for s in rapor.satirlar:
                session.add(
                    ImportRow(
                        batch_id=batch_id,
                        satir_no=s.satir_no,
                        ham_json=json.dumps(s.ham, ensure_ascii=False, default=str),
                        eslenen_json=json.dumps(s.eslenen, ensure_ascii=False, default=str),
                        durum="gecerli" if s.gecerli else "hata",
                        mesaj="; ".join(s.mesajlar) or None,
                        hedef_tablo=s.hedef_tablo,
                        hedef_id=s.hedef_id,
                        islem=s.islem if s.gecerli else None,
                    )
                )
            batch.toplam_satir = len(rapor.satirlar)
            batch.basarili_satir = rapor.gecerli
            batch.hata_satir = rapor.hatali
            batch.eklenen_satir = rapor.eklenecek
            batch.guncellenen_satir = rapor.guncellenecek
            batch.atlanan_satir = rapor.atlanacak
            batch.durum = "dry_run" if rapor.hatali == 0 else "dogrulandi"
            session.flush()

    @staticmethod
    def calistir(
        batch_id: int,
        importer: BaseImporter,
        ham_satirlar: list[dict[str, Any]],
        esleme: dict[str, str],
        *,
        guncelleme_modu: str = "guncelle",
        hatali_satirlari_atla: bool = True,
    ) -> ImportBatch:
        eslenenler = [ColumnMappingService.satir_esle(s, esleme) for s in ham_satirlar]
        rapor = importer.dogrula_satirlar(eslenenler, guncelleme_modu=guncelleme_modu)
        ImportExecutor.dry_run_kaydet(batch_id, rapor)

        with get_session() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            batch.basladi_at = datetime.now()
            batch.durum = "calisiyor"
            session.flush()

        eklenen = guncellenen = atlanan = hata = 0
        for s in rapor.satirlar:
            if not s.gecerli:
                hata += 1
                if not hatali_satirlari_atla:
                    ImportExecutor._batch_bitir(batch_id, "hatali", eklenen, guncellenen, atlanan, hata, "Kritik hata")
                    raise ValueError(f"Satır {s.satir_no}: {'; '.join(s.mesajlar)}")
                continue
            if s.islem == "skip":
                atlanan += 1
                continue
            try:
                change = importer.uygula_satir(s)
                ImportExecutor._change_kaydet(batch_id, s, change)
                if change.get("islem") == "update":
                    guncellenen += 1
                else:
                    eklenen += 1
            except Exception as exc:  # noqa: BLE001
                hata += 1
                ImportExecutor._satir_hata(batch_id, s.satir_no, str(exc))
                if not hatali_satirlari_atla:
                    ImportExecutor._batch_bitir(
                        batch_id, "hatali", eklenen, guncellenen, atlanan, hata, str(exc)
                    )
                    raise

        durum = "basarili" if hata == 0 else ("kismi" if (eklenen + guncellenen) > 0 else "hatali")
        return ImportExecutor._batch_bitir(batch_id, durum, eklenen, guncellenen, atlanan, hata, None)

    @staticmethod
    def _change_kaydet(batch_id: int, s: SatirSonuc, change: dict[str, Any]) -> None:
        with get_session() as session:
            session.add(
                ImportChange(
                    batch_id=batch_id,
                    satir_no=s.satir_no,
                    hedef_tablo=str(change.get("hedef_tablo") or ""),
                    hedef_id=change.get("hedef_id"),
                    islem=str(change.get("islem") or "insert"),
                    onceki_json=json.dumps(change.get("onceki"), ensure_ascii=False, default=str)
                    if change.get("onceki") is not None
                    else None,
                    sonraki_json=json.dumps(change.get("sonraki"), ensure_ascii=False, default=str)
                    if change.get("sonraki") is not None
                    else None,
                    tutar=change.get("tutar"),
                )
            )
            row = session.scalar(
                select(ImportRow).where(
                    ImportRow.batch_id == batch_id,
                    ImportRow.satir_no == s.satir_no,
                )
            )
            if row:
                row.durum = "uygulandi"
                row.hedef_id = change.get("hedef_id")
                row.hedef_tablo = change.get("hedef_tablo")
                row.islem = change.get("islem")
            session.flush()

    @staticmethod
    def _satir_hata(batch_id: int, satir_no: int, mesaj: str) -> None:
        with get_session() as session:
            row = session.scalar(
                select(ImportRow).where(
                    ImportRow.batch_id == batch_id,
                    ImportRow.satir_no == satir_no,
                )
            )
            if row:
                row.durum = "hata"
                row.mesaj = mesaj
            session.flush()

    @staticmethod
    def _batch_bitir(
        batch_id: int,
        durum: str,
        eklenen: int,
        guncellenen: int,
        atlanan: int,
        hata: int,
        hata_ozeti: str | None,
    ) -> ImportBatch:
        with get_session() as session:
            batch = session.get(ImportBatch, batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            batch.durum = durum
            batch.eklenen_satir = eklenen
            batch.guncellenen_satir = guncellenen
            batch.atlanan_satir = atlanan
            batch.hata_satir = hata
            batch.basarili_satir = eklenen + guncellenen
            batch.bitti_at = datetime.now()
            if hata_ozeti:
                batch.hata_ozeti = hata_ozeti
            session.flush()
            session.refresh(batch)
            return batch
