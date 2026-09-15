"""Dosya/klasör ve kullanıcı/yetki — salt okunur."""

from __future__ import annotations

import os
from pathlib import Path

from database.servis_sistem.scanners.common import (
    SEVERITY_INFO,
    SEVERITY_KRITIK,
    SEVERITY_UYARI,
    CheckReport,
    item,
    ok_yok,
)
from database.servis_sistem.system_health_service import SystemHealthService


def scan_dosya(rapor: CheckReport) -> None:
    """Branding, yazma, yedek klasörü — SystemHealth alt kontrolleri."""
    SystemHealthService._check_branding(rapor)
    SystemHealthService._check_write_perms(rapor)
    SystemHealthService._check_backup_folder(rapor)

    # Log klasörü derinleştirme
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    log_dirs = []
    if local:
        log_dirs.append(Path(local) / "CinMuhasebe" / "logs")
        log_dirs.append(Path(local) / "MuhasebeProgrami" / "logs")
    try:
        from database.database import PROJE_DATA_DIR

        log_dirs.append(Path(PROJE_DATA_DIR) / "logs")
    except Exception:
        pass

    bulunan = [p for p in log_dirs if p.is_dir()]
    if bulunan:
        for p in bulunan:
            try:
                dosya_say = sum(1 for _ in p.glob("*.log"))
            except OSError:
                dosya_say = -1
            rapor.ekle(
                item(
                    durum=SEVERITY_INFO,
                    modul="dosya_sistemi",
                    hata_kodu="LOG_KLASOR",
                    aciklama=f"Log klasörü: {p} ({dosya_say} .log)",
                    kayit_belge=str(p),
                )
            )
    else:
        rapor.ekle(
            item(
                durum=SEVERITY_UYARI,
                modul="dosya_sistemi",
                hata_kodu="LOG_KLASOR_YOK",
                aciklama="Bilinen log klasörü bulunamadı.",
                onerilen="Seviye 1: log klasörlerini oluşturun (Servis onarım).",
                otomatik="Evet (Seviye 1)",
            )
        )


def scan_kullanici(rapor: CheckReport) -> None:
    """system.db üzerinde hafif kullanıcı/rol kontrolleri."""
    try:
        from sqlalchemy import text

        from database.database import get_system_session
    except Exception as exc:  # noqa: BLE001
        rapor.ekle(
            item(
                durum=SEVERITY_INFO,
                modul="kullanici",
                hata_kodu="SISTEM_DB_ATLANDI",
                aciklama="Sistem DB oturumu açılamadı; kullanıcı taraması atlandı.",
                teknik=str(exc),
            )
        )
        return

    try:
        with get_system_session() as session:
            # Role'süz / geçersiz role
            rows = session.execute(
                text(
                    """
                    SELECT u.id, u.kullanici_adi, u.role_id
                    FROM users u
                    LEFT JOIN roles r ON r.id = u.role_id
                    WHERE r.id IS NULL
                    LIMIT 40
                    """
                )
            ).mappings().all()
            if rows:
                for r in rows:
                    rapor.ekle(
                        item(
                            durum=SEVERITY_KRITIK,
                            modul="kullanici",
                            hata_kodu="USER_ROLE_YOK",
                            aciklama=f"Rolü olmayan/geçersiz kullanıcı: {r['kullanici_adi']}",
                            kayit_belge=f"id={r['id']}",
                            teknik=f"role_id={r['role_id']}",
                            onerilen="Kullanıcıya geçerli rol atayın.",
                        )
                    )
            else:
                ok_yok(rapor, "kullanici", "USER_ROLE_OK", "Tüm kullanıcıların geçerli rolü var.")

            # Aktif kullanıcı firma bağlantısı yok
            rows2 = session.execute(
                text(
                    """
                    SELECT u.id, u.kullanici_adi FROM users u
                    WHERE COALESCE(u.aktif, 1) = 1
                      AND NOT EXISTS (
                        SELECT 1 FROM user_companies uc WHERE uc.user_id = u.id
                      )
                    LIMIT 40
                    """
                )
            ).mappings().all()
            if rows2:
                for r in rows2:
                    rapor.ekle(
                        item(
                            durum=SEVERITY_UYARI,
                            modul="kullanici",
                            hata_kodu="USER_FIRMA_YOK",
                            aciklama=f"Aktif kullanıcıda firma bağlantısı yok: {r['kullanici_adi']}",
                            kayit_belge=f"id={r['id']}",
                            onerilen="Kullanıcı-firma atamasını yapın.",
                        )
                    )
            else:
                ok_yok(
                    rapor,
                    "kullanici",
                    "USER_FIRMA_OK",
                    "Aktif kullanıcıların firma bağlantısı var.",
                )

            # Company db_path dosya kontrolü
            comps = session.execute(
                text(
                    """
                    SELECT id, firma_kodu, unvan, db_path FROM companies
                    WHERE COALESCE(aktif, 1) = 1 AND db_path IS NOT NULL AND TRIM(db_path) != ''
                    LIMIT 50
                    """
                )
            ).mappings().all()
            eksik = []
            for c in comps:
                p = Path(str(c["db_path"]))
                if not p.is_file():
                    eksik.append(c)
            if eksik:
                for c in eksik[:20]:
                    rapor.ekle(
                        item(
                            durum=SEVERITY_UYARI,
                            modul="kullanici",
                            hata_kodu="FIRMA_DB_DOSYA_YOK",
                            aciklama=f"Firma DB dosyası yok: {c['firma_kodu']} — {c['unvan']}",
                            kayit_belge=f"id={c['id']}",
                            teknik=str(c["db_path"]),
                            onerilen="Firma DB yolunu Sistem Yönetimi'nden doğrulayın.",
                        )
                    )
            else:
                ok_yok(rapor, "kullanici", "FIRMA_DB_OK", "Aktif firmaların DB dosyaları mevcut.")
    except Exception as exc:  # noqa: BLE001
        rapor.ekle(
            item(
                durum=SEVERITY_UYARI,
                modul="kullanici",
                hata_kodu="USER_TARAMA_HATA",
                aciklama="Kullanıcı/yetki taraması başarısız.",
                teknik=str(exc),
            )
        )
