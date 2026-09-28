"""Yuvarlama kolon migration öncesi DB yedekleme."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def yuvarlama_oncesi_db_yedekle(hedef_kok: Path | None = None) -> Path:
    """Aktif company DB + system DB + companies/*.db kopyalarını backup/ altına alır.

    Eski faturaları yeniden hesaplamaz; yalnız dosya kopyası.
    """
    from database.database import BASE_DIR, COMPANIES_DIR, DB_PATH, SYSTEM_DB_PATH, company_db

    damga = datetime.now().strftime("%Y%m%d_%H%M%S")
    kok = Path(hedef_kok) if hedef_kok else (BASE_DIR / "backup" / f"db_pre_yuvarlama_{damga}")
    kok.mkdir(parents=True, exist_ok=True)

    def _kopyala(kaynak: Path, ad: str | None = None) -> None:
        if not kaynak or not Path(kaynak).is_file():
            return
        kaynak = Path(kaynak)
        hedef = kok / (ad or kaynak.name)
        shutil.copy2(kaynak, hedef)
        for ek in ("-wal", "-shm"):
            yan = Path(str(kaynak) + ek)
            if yan.is_file():
                shutil.copy2(yan, Path(str(hedef) + ek))

    _kopyala(DB_PATH, "muhasebe.db")
    _kopyala(SYSTEM_DB_PATH, "system.db")
    aktif = getattr(company_db, "db_path", None)
    if aktif:
        _kopyala(Path(aktif), Path(aktif).name)
    if COMPANIES_DIR.is_dir():
        hedef_co = kok / "companies"
        hedef_co.mkdir(exist_ok=True)
        for db in COMPANIES_DIR.glob("*.db"):
            _kopyala(db, f"companies/{db.name}")

    (kok / "README.txt").write_text(
        "Yuvarlama / onay kolon migration öncesi yedek.\n"
        f"Zaman: {damga}\n"
        "Eski faturalar toplu yeniden hesaplanmadı.\n",
        encoding="utf-8",
    )
    return kok
