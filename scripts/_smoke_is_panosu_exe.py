"""Geçici DB kopyasında iş panosu akışını doğrula (EXE ile aynı kod yolu)."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="cin_smoke_is_"))
os.environ["MUHASEBE_DB_DIR"] = str(tmp)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base, get_session
from database.personel_performans_sema import schema_hazirla
from database.personel_performans_service import PersonelPerformansService
from database.personel_service import PersonelService
from database.session_manager import oturum
from unittest.mock import patch


def main() -> None:
    db = tmp / "smoke.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    schema_hazirla(engine)
    sf = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    class CM:
        def __enter__(self):
            self.s = sf()
            return self.s

        def __exit__(self, exc_type, exc, tb):
            if exc_type:
                self.s.rollback()
            else:
                self.s.commit()
            self.s.close()
            return False

    oturum.user_id = 1
    oturum.kullanici_adi = "smoke_user"
    oturum.ad_soyad = "Smoke"
    oturum.role_kod = "YONETICI"
    oturum.permissions = set()

    with (
        patch("database.personel_service.get_session", CM),
        patch("database.personel_performans_service.get_session", CM),
        patch("database.personel_service.schema_hazirla"),
        patch("database.personel_performans_service.schema_hazirla"),
        patch("database.access.yetki_var", return_value=True),
        patch("database.access.yetki_zorunlu"),
        patch("database.access.yazma_zorunlu"),
        patch("database.access.aktif_firma_zorunlu"),
        patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
    ):
        p1 = PersonelService.kaydet(
            {
                "kod": "SMK1",
                "ad": "Alpha",
                "soyad": "Personel",
                "kimlik_turu": "DIGER",
                "donem": {"giris_tarihi": "2025-01-01"},
            }
        )
        p2 = PersonelService.kaydet(
            {
                "kod": "SMK2",
                "ad": "Beta",
                "soyad": "Personel",
                "kimlik_turu": "DIGER",
                "donem": {"giris_tarihi": "2025-01-01"},
            }
        )
        i1 = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Smoke A",
                "sorumlu_personel_id": p1["id"],
                "gorev_alani": "HAZIRLAMA",
                "durum": "PLANLANDI",
                "hedef_saat": "09:15",
            }
        )
        i2 = PersonelPerformansService.is_kaydet(
            {
                "baslik": "Smoke B",
                "sorumlu_personel_id": p2["id"],
                "gorev_alani": "SEVKIYAT",
                "durum": "BASLADI",
            }
        )
        assert PersonelPerformansService.is_getir(i1["id"])["sorumlu_kod"] == "SMK1"
        assert len(PersonelPerformansService.is_panosu(personel_id=p2["id"])) == 1
        PersonelPerformansService.is_kaydet(
            {
                "id": i1["id"],
                "baslik": "Smoke A",
                "sorumlu_personel_id": p2["id"],
                "gorev_alani": "HAZIRLAMA",
                "durum": "ENGELLENDI",
                "dis_engel": "Bekleme",
            }
        )
        g = PersonelPerformansService.is_gecmis(i1["id"])
        assert any(x["alan"] == "sorumlu_personel_id" for x in g)
        print("SMOKE_OK", db, "is1", i1["id"], "is2", i2["id"], "gecmis", len(g))


if __name__ == "__main__":
    main()
