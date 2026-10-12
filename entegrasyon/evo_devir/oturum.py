"""Ayrı veri klasöründe Evo devir firması oturumu.

``database.database`` veri klasörünü import anında seçer; bu yüzden ``veri_klasoru_sec`` o modül
import edilmeden önce çağrılmalıdır. Gerçek kurulum klasörü (%LOCALAPPDATA%\\MuhasebeProgrami)
ve altı reddedilir: deneme firması Ray Mobilya ve diğer firmaların verisine hiç dokunmaz.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from pathlib import Path

FIRMA_KODU = "EVODEVIR"
VARSAYILAN_UNVAN = "Evo Devir Deneme"
KULLANILMAYAN_UNVAN = "Kullanılmayan varsayılan firma (boş)"


def _gercek_kok() -> Path | None:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    return Path(local) / "MuhasebeProgrami" if local else None


def _altinda(yol: Path, kok: Path) -> bool:
    a = os.path.normcase(os.path.abspath(str(yol)))
    k = os.path.normcase(os.path.abspath(str(kok))).rstrip("\\/")
    return a == k or a.startswith(k + os.sep)


def veri_klasoru_sec(veri_klasoru: str | Path) -> Path:
    yol = Path(veri_klasoru).resolve()
    gercek = _gercek_kok()
    if gercek is not None and _altinda(yol, gercek):
        raise SystemExit(f"Gerçek veri klasörü kullanılamaz: {yol}")
    if "database.database" in sys.modules:
        from database import database as db

        if Path(db.DB_DIR).resolve() != yol:
            raise SystemExit(f"database modülü başka klasörle yüklenmiş: {db.DB_DIR}")
    yol.mkdir(parents=True, exist_ok=True)
    os.environ["MUHASEBE_DB_DIR"] = str(yol)
    return yol


def modelleri_yukle() -> None:
    """Uygulamadaki gibi tüm firma modelleri metadata'ya girsin (yeni firma DB'si eksiksiz kurulsun)."""
    import database.models as paket

    for bilgi in pkgutil.iter_modules(paket.__path__):
        importlib.import_module(f"database.models.{bilgi.name}")
    importlib.import_module("excel_aktarim.models")


def firma_oturumu_ac(unvan: str = VARSAYILAN_UNVAN) -> dict:
    """Sistemi başlatır, yönetici oturumu açar, Evo devir firmasını bulur/oluşturur ve açar."""
    from sqlalchemy import select

    from database import database as db
    from database.session_manager import oturum
    from database.system.bootstrap import RAY_KOD
    from database.system.company_service import CompanyMgmtService
    from database.system.models import AppSetting, Company

    gercek = _gercek_kok()
    if gercek is not None and _altinda(Path(db.DB_DIR), gercek):
        raise SystemExit(f"Gerçek veri klasörü açık: {db.DB_DIR}")
    modelleri_yukle()
    sonuc = db.sistem_altyapisini_baslat()
    oturum.set_user(
        user_id=int(sonuc["admin_user_id"]),
        kullanici_adi="admin",
        ad_soyad="Evo devir aktarımı",
        role_kod="YONETICI",
        role_ad="Yönetici",
        permissions=set(),
    )
    with db.get_system_session() as s:
        firma = s.scalar(select(Company).where(Company.firma_kodu == FIRMA_KODU))
        firma_id = firma.id if firma else None
    olusturuldu = False
    if firma_id is None:
        firma_id = CompanyMgmtService.ekle(
            {"firma_kodu": FIRMA_KODU, "unvan": unvan, "kisa_ad": unvan, "varsayilan_para_birimi": "TRY"}
        )
        olusturuldu = True
    with db.get_system_session() as s:
        firma = s.get(Company, firma_id)
        yol = db.firma_db_yolu_coz(firma.db_path) or Path(firma.db_path)
        bilgi = dict(id=firma.id, kod=firma.firma_kodu, unvan=firma.unvan, uid=firma.firma_uid, yol=str(yol))
        varsayilan = s.scalar(select(Company).where(Company.firma_kodu == RAY_KOD))
        if varsayilan is not None and varsayilan.id != firma.id:
            # Bu klasördeki boş varsayılan firma listede görünmesin
            varsayilan.unvan = KULLANILMAYAN_UNVAN
            varsayilan.kisa_ad = None
            varsayilan.aktif = False
        ayar = s.scalar(select(AppSetting).where(AppSetting.anahtar == "son_firma_id"))
        if ayar is None:
            s.add(AppSetting(anahtar="son_firma_id", deger=str(firma.id)))
        else:
            ayar.deger = str(firma.id)
    db.firma_db_ac(bilgi["id"], bilgi["yol"])
    oturum.set_company(
        company_id=bilgi["id"],
        firma_kodu=bilgi["kod"],
        firma_unvan=bilgi["unvan"],
        firma_uid=bilgi["uid"],
        db_path=bilgi["yol"],
    )
    try:
        from database.deleted_record_service import AuditDeleteService

        AuditDeleteService.schema_hazirla()
    except Exception:
        pass
    from database.muhasebelestirme_service import MuhasebelestirmeService

    MuhasebelestirmeService.schema_hazirla()
    bilgi["olusturuldu"] = olusturuldu
    bilgi["veri_klasoru"] = str(db.DB_DIR)
    return bilgi


def firma_unvani_degistir(yeni_unvan: str) -> None:
    from database.database import get_session, get_system_session
    from database.models.firma import Firma
    from database.session_manager import oturum
    from database.system.models import Company
    from sqlalchemy import select

    with get_system_session() as s:
        f = s.get(Company, oturum.company_id)
        f.unvan = yeni_unvan
        f.kisa_ad = yeni_unvan
    with get_session() as s:
        yerel = s.scalar(select(Firma).limit(1))
        if yerel is not None:
            yerel.unvan = yeni_unvan
