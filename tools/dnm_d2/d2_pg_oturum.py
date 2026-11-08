"""D2 PostgreSQL firma oturumu — evo_devir SQLite klasör yolunu kullanmaz.

baglanti_ayari.json D2 sistem/firma DB göstermeli.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from database.baglanti_modu import ayari_yukle
from database.engine_factory import sistem_engine_olustur
from tools.dnm_d2.donem_sabitleri import ONERILEN_FIRMA_DB, ONERILEN_SISTEM_DB


def d2_pg_oturum_ac(*, firma_kodu: str = "DNM_D2") -> dict:
    from database import database as db
    from database.session_manager import oturum
    from database.system.models import Company, User

    ayar = ayari_yukle()
    if not ayar.ag_mi:
        raise SystemExit("baglanti_ayari yerel_ag_postgres olmalı")
    if ayar.postgres.sistem_db != ONERILEN_SISTEM_DB:
        raise SystemExit(
            f"sistem_db {ayar.postgres.sistem_db} ≠ {ONERILEN_SISTEM_DB}; "
            "önce d2_baglanti_gecis d2"
        )
    if ayar.postgres.firma_db != ONERILEN_FIRMA_DB:
        raise SystemExit(
            f"firma_db {ayar.postgres.firma_db} ≠ {ONERILEN_FIRMA_DB}; "
            "önce d2_baglanti_gecis d2"
        )

    # modeller
    from entegrasyon.evo_devir.oturum import modelleri_yukle

    modelleri_yukle()

    db.system_engine = sistem_engine_olustur(ayar, sqlite_path=None)
    db.SystemSessionLocal = sessionmaker(
        bind=db.system_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    with db.get_system_session() as s:
        firma = s.scalar(select(Company).where(Company.firma_kodu == firma_kodu, Company.aktif.is_(True)))
        if firma is None:
            raise SystemExit(f"Firma yok: {firma_kodu}")
        user = s.scalar(select(User).where(User.kullanici_adi == "admin", User.aktif.is_(True)))
        if user is None:
            user = s.scalar(select(User).where(User.aktif.is_(True)).order_by(User.id).limit(1))
        if user is None:
            raise SystemExit("Aktif kullanıcı yok")
        bilgi = {
            "id": firma.id,
            "kod": firma.firma_kodu,
            "unvan": firma.unvan,
            "uid": firma.firma_uid,
            "yol": firma.db_path,
            "user_id": user.id,
            "kullanici_adi": user.kullanici_adi,
        }

    oturum.set_user(
        user_id=int(bilgi["user_id"]),
        kullanici_adi=str(bilgi["kullanici_adi"]),
        ad_soyad="D2 aktarım",
        role_kod="YONETICI",
        role_ad="Yönetici",
        permissions=set(),
    )
    db.firma_db_ac(int(bilgi["id"]), bilgi["yol"])
    oturum.set_company(
        company_id=int(bilgi["id"]),
        firma_kodu=bilgi["kod"],
        firma_unvan=bilgi["unvan"],
        firma_uid=bilgi["uid"],
        db_path=str(bilgi["yol"]),
    )
    try:
        from database.muhasebelestirme_service import MuhasebelestirmeService

        MuhasebelestirmeService.schema_hazirla()
    except Exception:
        pass
    return bilgi
