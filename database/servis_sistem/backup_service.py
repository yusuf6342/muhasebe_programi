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
    def geri_yukle_dogrula(
        yedek_yolu: str | Path,
        *,
        hedef_kopya: str | Path | None = None,
    ) -> dict:
        """Yedeği geçici kopyaya açıp okunabilirliğini doğrular.

        Canlı firma DB'sine yazmaz / üzerine yazmaz. Yalnızca kopya üzerinde
        SQLite integrity + temel tablo sayımları yapılır.
        """
        import sqlite3
        import tempfile

        kaynak = BackupService.dogrula_yedek(Path(yedek_yolu))
        if hedef_kopya is None:
            tmp = Path(tempfile.gettempdir()) / "cin_devir_yedek_test"
            tmp.mkdir(parents=True, exist_ok=True)
            hedef = tmp / f"restore_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        else:
            hedef = Path(hedef_kopya)
            hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kaynak, hedef)
        for ek in ("-wal", "-shm"):
            k = Path(str(kaynak) + ek)
            if k.is_file():
                shutil.copy2(k, Path(str(hedef) + ek))

        sayimlar: dict[str, int] = {}
        with sqlite3.connect(f"file:{hedef}?mode=ro", uri=True) as conn:
            ok = conn.execute("PRAGMA integrity_check").fetchone()
            if not ok or str(ok[0]).lower() != "ok":
                raise ValueError(f"Yedek integrity_check başarısız: {ok}")
            tablolar = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for ad in (
                "cari_kartlar",
                "cari_satis_hareketleri",
                "finans_hesaplari",
                "finans_hareketleri",
                "stok_kartlari",
                "donemler",
                "devir_isleri",
                "devir_eslesmeler",
            ):
                if ad in tablolar:
                    sayimlar[ad] = int(
                        conn.execute(f'SELECT COUNT(*) FROM "{ad}"').fetchone()[0]
                    )
        return {
            "yedek": str(kaynak),
            "kopya": str(hedef),
            "boyut": kaynak.stat().st_size,
            "integrity": "ok",
            "tablo_sayisi": len(tablolar),
            "sayimlar": sayimlar,
            "canli_db_degismedi": True,
        }

    @staticmethod
    def servis_oncesi_yedek_al(hedef_klasor: str | Path | None = None) -> Path:
        """Onarım öncesi yedek — mevcut kopyalama mantığı, ServisOncesi adı.

        CompanyMgmtService.yedek_al ile aynı kaynak/WAL-SHM kopyası; yalnızca dosya adı farklı.
        Başarısızsa exception (onarım çağıran abort eder).
        """
        if oturum.company_id is None:
            raise ValueError("Aktif firma seçili değil; servis öncesi yedek alınamaz.")

        from database.system.models import Company
        from database.database import firma_db_yolu_coz, get_system_session

        company_id = int(oturum.company_id)
        klasor = Path(hedef_klasor) if hedef_klasor else BackupService.yedek_klasoru_onerisi()
        klasor.mkdir(parents=True, exist_ok=True)

        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı; yedek alınamaz.")
            kaynak = firma_db_yolu_coz(f.db_path) or Path(f.db_path)
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
