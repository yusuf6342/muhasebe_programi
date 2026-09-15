"""Veritabanı bütünlüğü — salt okunur kontroller (DROP/CREATE yok)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy import inspect, text

from database.servis_sistem.system_health_service import (
    SEVERITY_INFO,
    SEVERITY_KRITIK,
    SEVERITY_OK,
    SEVERITY_UYARI,
    CheckItem,
    CheckReport,
)

ProgressCb = Callable[[int, str], None] | None


class DatabaseIntegrityService:
    @staticmethod
    def run_readonly_check(
        progress: ProgressCb = None,
        *,
        kaydet: bool = True,
    ) -> dict[str, Any]:
        """PRAGMA integrity_check, foreign_keys, model vs tablo — mutasyon yok."""
        rapor = CheckReport(
            baslik="Veritabanı Salt Okunur Kontrol",
            baslangic=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            mutasyon_yapildi=False,
        )

        def _p(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        _p(10, "Bağlantı...")
        try:
            from database.database import engine

            if engine is None:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="veritabani",
                        hata_kodu="DB_ENGINE_YOK",
                        aciklama="Aktif engine yok; kontrol yapılamadı.",
                    )
                )
                rapor.ozeti_hesapla()
                return rapor.to_dict()

            _p(25, "PRAGMA integrity_check...")
            DatabaseIntegrityService._integrity_check(engine, rapor)

            _p(45, "Foreign keys pragma...")
            DatabaseIntegrityService._foreign_keys_pragma(engine, rapor)

            _p(70, "Model / tablo karşılaştırması...")
            DatabaseIntegrityService._missing_tables(engine, rapor)

            _p(90, "Kayıt...")
            if kaydet:
                DatabaseIntegrityService._persist(rapor)

        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_KRITIK,
                    onem="Kritik",
                    modul="veritabani",
                    hata_kodu="DB_READONLY_HATA",
                    aciklama="Salt okunur DB kontrolü başarısız.",
                    teknik=str(exc),
                )
            )

        rapor.ozeti_hesapla()
        _p(100, "Tamamlandı")
        return rapor.to_dict()

    @staticmethod
    def _integrity_check(engine, rapor: CheckReport) -> None:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("PRAGMA integrity_check")).fetchall()
            sonuc = [str(r[0]) for r in rows] if rows else []
            if sonuc == ["ok"] or (len(sonuc) == 1 and sonuc[0].lower() == "ok"):
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="veritabani",
                        hata_kodu="INTEGRITY_OK",
                        aciklama="SQLite integrity_check: ok",
                    )
                )
            else:
                ozet = "; ".join(sonuc[:5])
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="veritabani",
                        hata_kodu="INTEGRITY_FAIL",
                        aciklama="SQLite integrity_check sorun bildirdi.",
                        teknik=ozet,
                        onerilen="Yedek alın; bozulma için uzman müdahalesi gerekir (otomatik onarım yok).",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="veritabani",
                    hata_kodu="INTEGRITY_CALISTIRILAMADI",
                    aciklama="integrity_check çalıştırılamadı.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _foreign_keys_pragma(engine, rapor: CheckReport) -> None:
        try:
            with engine.connect() as conn:
                row = conn.execute(text("PRAGMA foreign_keys")).fetchone()
                deger = int(row[0]) if row is not None else -1
            if deger == 1:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="veritabani",
                        hata_kodu="FK_PRAGMA_ON",
                        aciklama="PRAGMA foreign_keys = ON",
                    )
                )
            elif deger == 0:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_UYARI,
                        onem="Uyarı",
                        modul="veritabani",
                        hata_kodu="FK_PRAGMA_OFF",
                        aciklama="PRAGMA foreign_keys = OFF (bu bağlantıda).",
                        onerilen="Bağlantı ayarlarında FK açılması önerilir; Aşama 2'de otomatik değiştirilmez.",
                    )
                )
            else:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_INFO,
                        onem="Bilgi",
                        modul="veritabani",
                        hata_kodu="FK_PRAGMA_BILINMIYOR",
                        aciklama="foreign_keys pragma değeri okunamadı.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="veritabani",
                    hata_kodu="FK_PRAGMA_HATA",
                    aciklama="foreign_keys pragma okunamadı.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _missing_tables(engine, rapor: CheckReport) -> None:
        """Base.metadata tabloları ile DB karşılaştırması — create/drop yok."""
        try:
            # Modelleri metadata'ya yükle
            import database.models.cari  # noqa: F401
            import database.models.stok  # noqa: F401
            import database.models.finans  # noqa: F401
            import database.models.satis_faturasi  # noqa: F401
            import database.models.donem  # noqa: F401
            import database.models.deleted_record  # noqa: F401
            import database.servis_sistem.models  # noqa: F401

            from database.database import Base

            insp = inspect(engine)
            model_tablolari = sorted(Base.metadata.tables.keys())
            eksik = [t for t in model_tablolari if not insp.has_table(t)]
            if not eksik:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="veritabani",
                        hata_kodu="MODEL_TABLO_OK",
                        aciklama=f"Model tabloları mevcut ({len(model_tablolari)} kayıtlı).",
                    )
                )
            else:
                # Çok fazla eksik olabilir (henüz kullanılmayan modüller) — uyarı
                goster = ", ".join(eksik[:15])
                fazla = f" (+{len(eksik) - 15} daha)" if len(eksik) > 15 else ""
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_UYARI,
                        onem="Uyarı",
                        modul="veritabani",
                        hata_kodu="MODEL_TABLO_EKSIK",
                        aciklama=f"Modellerde tanımlı, DB'de olmayan tablolar: {goster}{fazla}",
                        teknik="; ".join(eksik),
                        onerilen="İlgili modülün schema_hazirla / create(checkfirst) akışını kullanın; DROP yapılmaz.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="veritabani",
                    hata_kodu="MODEL_TABLO_KONTROL_HATA",
                    aciklama="Model-tablo karşılaştırması yapılamadı.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _persist(rapor: CheckReport) -> None:
        try:
            from database.servis_sistem.error_log_service import ErrorLogService

            for m in rapor.maddeler:
                if m.durum not in (SEVERITY_UYARI, SEVERITY_KRITIK):
                    continue
                ErrorLogService.kaydet_sorun(
                    module_name=m.modul,
                    issue_code=m.hata_kodu,
                    severity=m.durum,
                    title=m.aciklama[:300],
                    user_message=m.aciklama,
                    technical_detail=m.teknik or None,
                    suggested_action=m.onerilen or None,
                )
        except Exception:
            pass
