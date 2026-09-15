"""Mevcut yedekleme altyapısını saran servis — paralel yedek yığını yok."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from database.session_manager import oturum
from database.system.company_service import CompanyMgmtService


class BackupService:
    """Sistem → Veritabanı Yedekleme ile aynı kopyalama yolunu kullanır."""

    @staticmethod
    def yedek_al(hedef_klasor: str | Path | None = None) -> Path:
        if oturum.company_id is None:
            raise ValueError("Aktif firma seçili değil; yedek alınamaz.")
        if hedef_klasor is None:
            raise ValueError("Hedef klasör gerekli (UI dosya diyaloğu kullanın).")
        return CompanyMgmtService.yedek_al(int(oturum.company_id), hedef_klasor)

    @staticmethod
    def yedek_klasoru_onerisi() -> Path:
        import os

        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            yol = Path(local) / "MuhasebeProgrami" / "yedekler"
        else:
            from database.database import PROJE_DATA_DIR

            yol = PROJE_DATA_DIR / "yedekler"
        yol.mkdir(parents=True, exist_ok=True)
        return yol

    @staticmethod
    def servis_oncesi_yedek_adi(damga: datetime | None = None) -> str:
        d = damga or datetime.now()
        return f"CinMuhasebe_ServisOncesi_{d.strftime('%Y-%m-%d_%H%M%S')}.db"

    @staticmethod
    def dogrula_yedek(yol: Path) -> Path:
        """Dosya var ve boyut > 0; aksi halde ValueError."""
        p = Path(yol)
        if not p.is_file():
            raise ValueError(f"Yedek dosyası oluşmadı: {p}")
        size = p.stat().st_size
        if size <= 0:
            raise ValueError(f"Yedek dosyası boş (0 bayt): {p}")
        return p

    @staticmethod
    def servis_oncesi_yedek_al(hedef_klasor: str | Path | None = None) -> Path:
        """Onarım öncesi yedek — mevcut kopyalama mantığı, ServisOncesi adı.

        CompanyMgmtService.yedek_al ile aynı kaynak/WAL-SHM kopyası; yalnızca dosya adı farklı.
        Başarısızsa exception (onarım çağıran abort eder).
        """
        if oturum.company_id is None:
            raise ValueError("Aktif firma seçili değil; servis öncesi yedek alınamaz.")

        from database.system.models import Company
        from database.database import get_system_session

        company_id = int(oturum.company_id)
        klasor = Path(hedef_klasor) if hedef_klasor else BackupService.yedek_klasoru_onerisi()
        klasor.mkdir(parents=True, exist_ok=True)

        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı; yedek alınamaz.")
            kaynak = Path(f.db_path)
            if not kaynak.is_file():
                raise FileNotFoundError(f"Firma veritabanı dosyası yok: {kaynak}")

            hedef = klasor / BackupService.servis_oncesi_yedek_adi()
            if hedef.exists():
                hedef = klasor / (
                    f"CinMuhasebe_ServisOncesi_"
                    f"{datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')}.db"
                )

            shutil.copy2(kaynak, hedef)
            for ek in ("-wal", "-shm"):
                k = Path(str(kaynak) + ek)
                if k.is_file():
                    shutil.copy2(k, Path(str(hedef) + ek))

            try:
                from database.system.auth_service import AuthService

                AuthService.audit(
                    session,
                    "servis_oncesi_yedekleme",
                    modul="servis",
                    kayit_id=str(company_id),
                    yeni_deger=str(hedef),
                )
            except Exception:
                # Audit başarısız olsa bile yedek dosyası doğrulanır
                pass

        return BackupService.dogrula_yedek(hedef)
