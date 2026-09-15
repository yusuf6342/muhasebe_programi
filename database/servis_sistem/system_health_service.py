"""Sistem sağlık — hızlı / salt okunur kontroller."""

from __future__ import annotations

import importlib
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import inspect, text

SEVERITY_OK = "ok"
SEVERITY_INFO = "info"
SEVERITY_UYARI = "uyari"
SEVERITY_KRITIK = "kritik"


@dataclass
class CheckItem:
    durum: str  # ok | uyari | kritik | info
    onem: str
    modul: str
    hata_kodu: str
    aciklama: str
    kayit_belge: str = ""
    otomatik_duzeltme: str = "Hayır"
    son_kontrol: str = ""
    teknik: str = ""
    onerilen: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckReport:
    baslik: str
    baslangic: str
    bitis: str = ""
    ozet: dict[str, int] = field(default_factory=dict)
    maddeler: list[CheckItem] = field(default_factory=list)
    mutasyon_yapildi: bool = False
    sure_ms: int | None = None
    _t0: float = field(default_factory=time.monotonic, repr=False, compare=False)

    def ekle(self, item: CheckItem) -> None:
        if not item.son_kontrol:
            item.son_kontrol = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        self.maddeler.append(item)

    def ozeti_hesapla(self) -> None:
        sayac = {"ok": 0, "info": 0, "uyari": 0, "kritik": 0}
        for m in self.maddeler:
            sayac[m.durum if m.durum in sayac else "info"] = (
                sayac.get(m.durum if m.durum in sayac else "info", 0) + 1
            )
        self.ozet = sayac
        self.bitis = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        self.sure_ms = max(0, int((time.monotonic() - self._t0) * 1000))

    def to_dict(self) -> dict[str, Any]:
        self.ozeti_hesapla()
        return {
            "baslik": self.baslik,
            "baslangic": self.baslangic,
            "bitis": self.bitis,
            "sure_ms": self.sure_ms,
            "ozet": dict(self.ozet),
            "maddeler": [m.to_dict() for m in self.maddeler],
            "mutasyon_yapildi": self.mutasyon_yapildi,
        }


ProgressCb = Callable[[int, str], None] | None


# Kritik işletim tabloları (eksikse uyarı/kritik)
ZORUNLU_TABLOLAR: tuple[str, ...] = (
    "cari_kartlar",
    "stok_kartlari",
    "satis_faturalari",
    "finans_hesaplari",
    "finans_hareketleri",
    "donemler",
)

KRITIK_IMPORTLAR: tuple[str, ...] = (
    "sqlalchemy",
    "tkinter",
    "database.database",
    "database.session_manager",
    "branding",
    "app",
)


class SystemHealthService:
    @staticmethod
    def run_quick_check(
        progress: ProgressCb = None,
        *,
        kaydet: bool = True,
    ) -> dict[str, Any]:
        """Salt okunur hızlı sistem kontrolü — veri mutasyonu yok."""
        rapor = CheckReport(
            baslik="Hızlı Sistem Kontrolü",
            baslangic=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            mutasyon_yapildi=False,
        )

        def _p(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        _p(5, "Veritabanı bağlantısı...")
        SystemHealthService._check_db_connection(rapor)

        _p(20, "Zorunlu tablolar...")
        SystemHealthService._check_required_tables(rapor)

        _p(40, "Branding / logo...")
        SystemHealthService._check_branding(rapor)

        _p(55, "Yazma izinleri...")
        SystemHealthService._check_write_perms(rapor)

        _p(70, "Yedek klasörü...")
        SystemHealthService._check_backup_folder(rapor)

        _p(85, "Kritik importlar...")
        SystemHealthService._check_imports(rapor)

        _p(95, "Kayıt...")
        if kaydet:
            SystemHealthService._persist_findings(rapor)

        rapor.ozeti_hesapla()
        _p(100, "Tamamlandı")
        return rapor.to_dict()

    @staticmethod
    def run_detailed_check_stub(progress: ProgressCb = None) -> dict[str, Any]:
        """Ayrıntılı kontrol — Aşama 3: tüm modül derin taramaları."""
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        return ModuleDiagnosticService.scan_all_modules(
            progress=progress, kaydet=True, include_quick=True
        )
    @staticmethod
    def _check_db_connection(rapor: CheckReport) -> None:
        try:
            from database.database import DB_PATH, engine

            if engine is None:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="veritabani",
                        hata_kodu="DB_ENGINE_YOK",
                        aciklama="Aktif veritabanı motoru yok.",
                        onerilen="Firma seçimini ve oturumu kontrol edin.",
                    )
                )
                return
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            yol = Path(str(DB_PATH)) if DB_PATH else None
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_OK,
                    onem="OK",
                    modul="veritabani",
                    hata_kodu="DB_BAGLANTI_OK",
                    aciklama="Veritabanı bağlantısı başarılı.",
                    kayit_belge=str(yol) if yol else "",
                )
            )
            if yol and not yol.is_file():
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_UYARI,
                        onem="Uyarı",
                        modul="veritabani",
                        hata_kodu="DB_DOSYA_YOK",
                        aciklama=f"DB yolu dosya olarak görünmüyor: {yol}",
                        onerilen="Firma DB yolunu Sistem Yönetimi'nden doğrulayın.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_KRITIK,
                    onem="Kritik",
                    modul="veritabani",
                    hata_kodu="DB_BAGLANTI_HATA",
                    aciklama="Veritabanına bağlanılamadı.",
                    teknik=str(exc),
                    onerilen="Dosya kilidi, OneDrive senkronu veya yolu kontrol edin.",
                )
            )

    @staticmethod
    def _check_required_tables(rapor: CheckReport) -> None:
        try:
            from database.database import engine

            if engine is None:
                return
            insp = inspect(engine)
            eksik = [t for t in ZORUNLU_TABLOLAR if not insp.has_table(t)]
            if not eksik:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="veritabani",
                        hata_kodu="TABLOLAR_OK",
                        aciklama=f"Zorunlu tablolar mevcut ({len(ZORUNLU_TABLOLAR)}).",
                    )
                )
            else:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="veritabani",
                        hata_kodu="TABLO_EKSIK",
                        aciklama=f"Eksik tablolar: {', '.join(eksik)}",
                        teknik=", ".join(eksik),
                        onerilen="Şema migration / firma DB oluşturma akışını çalıştırın (otomatik DROP yok).",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="veritabani",
                    hata_kodu="TABLO_KONTROL_HATA",
                    aciklama="Tablo listesi okunamadı.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _check_branding(rapor: CheckReport) -> None:
        try:
            from branding import (
                APP_ICON_PNG,
                ICO_FILE,
                LOGO_FILE,
                SPLASH_FILE,
                branding_path,
                resource_exists,
            )

            dosyalar = {
                "logo/splash": SPLASH_FILE,
                "logo_yedek": LOGO_FILE,
                "ikon_png": APP_ICON_PNG,
                "ikon_ico": ICO_FILE,
            }
            eksik = []
            for etiket, ad in dosyalar.items():
                if not resource_exists(Path("assets") / "branding" / ad):
                    # branding_path de dene
                    if not branding_path(ad).is_file():
                        eksik.append(f"{etiket}:{ad}")
            if not eksik:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="branding",
                        hata_kodu="BRANDING_OK",
                        aciklama="Logo ve ikon dosyaları bulundu.",
                    )
                )
            else:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_UYARI,
                        onem="Uyarı",
                        modul="branding",
                        hata_kodu="BRANDING_EKSIK",
                        aciklama=f"Eksik marka dosyaları: {', '.join(eksik)}",
                        teknik="; ".join(eksik),
                        onerilen="assets/branding altına dosyaları ekleyin veya EXE'yi yeniden paketleyin.",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="branding",
                    hata_kodu="BRANDING_KONTROL_HATA",
                    aciklama="Branding kontrolü başarısız.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _check_write_perms(rapor: CheckReport) -> None:
        hedefler: list[Path] = []
        try:
            from database.database import DB_DIR, PROJE_DATA_DIR

            hedefler.append(Path(DB_DIR))
            hedefler.append(Path(PROJE_DATA_DIR))
        except Exception:
            pass
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            hedefler.append(Path(local) / "MuhasebeProgrami")
            hedefler.append(Path(local) / "CinMuhasebe" / "logs")

        for klasor in hedefler:
            try:
                klasor.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=str(klasor), prefix=".servis_yaz_", delete=True
                ) as tf:
                    tf.write(b"ok")
                    tf.flush()
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="dosya_sistemi",
                        hata_kodu="YAZMA_OK",
                        aciklama=f"Yazma izni var: {klasor}",
                        kayit_belge=str(klasor),
                    )
                )
            except OSError as exc:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="dosya_sistemi",
                        hata_kodu="YAZMA_YOK",
                        aciklama=f"Yazma izni yok veya klasör oluşturulamadı: {klasor}",
                        teknik=str(exc),
                        onerilen="Klasör izinlerini ve antivirüs kilidini kontrol edin.",
                    )
                )

    @staticmethod
    def _check_backup_folder(rapor: CheckReport) -> None:
        try:
            from database.servis_sistem.backup_service import BackupService

            yol = BackupService.yedek_klasoru_onerisi()
            if yol.is_dir():
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="yedekleme",
                        hata_kodu="YEDEK_KLASOR_OK",
                        aciklama=f"Yedek klasörü hazır: {yol}",
                        kayit_belge=str(yol),
                    )
                )
            else:
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_UYARI,
                        onem="Uyarı",
                        modul="yedekleme",
                        hata_kodu="YEDEK_KLASOR_YOK",
                        aciklama="Yedek klasörü oluşturulamadı.",
                        kayit_belge=str(yol),
                        otomatik_duzeltme="Evet (Seviye 1)",
                        onerilen="Seviye 1: yedek klasörünü oluşturun (Servis onarım).",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                CheckItem(
                    durum=SEVERITY_UYARI,
                    onem="Uyarı",
                    modul="yedekleme",
                    hata_kodu="YEDEK_KLASOR_HATA",
                    aciklama="Yedek klasörü kontrol edilemedi.",
                    teknik=str(exc),
                )
            )

    @staticmethod
    def _check_imports(rapor: CheckReport) -> None:
        for mod in KRITIK_IMPORTLAR:
            try:
                importlib.import_module(mod)
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_OK,
                        onem="OK",
                        modul="import",
                        hata_kodu="IMPORT_OK",
                        aciklama=f"Modül yüklendi: {mod}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                rapor.ekle(
                    CheckItem(
                        durum=SEVERITY_KRITIK,
                        onem="Kritik",
                        modul="import",
                        hata_kodu="IMPORT_HATA",
                        aciklama=f"Kritik modül yüklenemedi: {mod}",
                        teknik=str(exc),
                        onerilen="Kurulum / PyInstaller paketini kontrol edin.",
                    )
                )

    @staticmethod
    def _persist_findings(rapor: CheckReport) -> None:
        try:
            from database.servis_sistem.error_log_service import ErrorLogService

            ErrorLogService.schema_hazirla()
            for m in rapor.maddeler:
                if m.durum not in (SEVERITY_UYARI, SEVERITY_KRITIK):
                    continue
                from database.servis_sistem.repair_service import LEVEL1_ACTIONS

                level1 = m.hata_kodu in LEVEL1_ACTIONS
                ErrorLogService.kaydet_sorun(
                    module_name=m.modul,
                    issue_code=m.hata_kodu,
                    severity=m.durum,
                    title=m.aciklama[:300],
                    user_message=m.aciklama,
                    technical_detail=m.teknik or None,
                    suggested_action=m.onerilen or None,
                    auto_fixable=level1,
                    repair_level=1 if level1 else 0,
                )
        except Exception:
            # Kayıt başarısız olsa bile rapor döner
            pass
