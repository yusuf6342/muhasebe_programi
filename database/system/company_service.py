"""Sistem firma yönetimi — system.db + firma operasyon DB oluşturma."""

from __future__ import annotations

import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database.database import (
    COMPANIES_DIR,
    Base,
    company_db,
    get_system_session,
)
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.models import Company, UserCompany


class CompanyMgmtService:
    @staticmethod
    def _yetki() -> None:
        if not oturum.has_permission("firma_yonetme"):
            raise PermissionError("Firma yönetimi yetkiniz yok.")

    @staticmethod
    def listele(arama: str = "") -> list[dict]:
        CompanyMgmtService._yetki()
        with get_system_session() as session:
            statement = select(Company).order_by(Company.unvan)
            arama = (arama or "").strip()
            if arama:
                ifade = f"%{arama}%"
                statement = statement.where(
                    or_(
                        Company.firma_kodu.ilike(ifade),
                        Company.unvan.ilike(ifade),
                        Company.vergi_no.ilike(ifade),
                    )
                )
            return [
                {
                    "id": f.id,
                    "firma_uid": f.firma_uid,
                    "firma_kodu": f.firma_kodu,
                    "unvan": f.unvan,
                    "kisa_ad": f.kisa_ad,
                    "vergi_dairesi": f.vergi_dairesi,
                    "vergi_no": f.vergi_no,
                    "telefon": f.telefon,
                    "email": f.email,
                    "internet": f.internet,
                    "adres": f.adres,
                    "il": f.il,
                    "ilce": f.ilce,
                    "logo_yolu": f.logo_yolu,
                    "varsayilan_para_birimi": f.varsayilan_para_birimi,
                    "fatura_seri": f.fatura_seri,
                    "aktif": f.aktif,
                    "db_path": f.db_path,
                    "olusturma_tarihi": f.olusturma_tarihi,
                }
                for f in session.scalars(statement).all()
            ]

    @staticmethod
    def getir(company_id: int) -> dict | None:
        CompanyMgmtService._yetki()
        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                return None
            return {
                "id": f.id,
                "firma_uid": f.firma_uid,
                "firma_kodu": f.firma_kodu,
                "unvan": f.unvan,
                "kisa_ad": f.kisa_ad,
                "vergi_dairesi": f.vergi_dairesi,
                "vergi_no": f.vergi_no,
                "telefon": f.telefon,
                "email": f.email,
                "internet": f.internet,
                "adres": f.adres,
                "il": f.il,
                "ilce": f.ilce,
                "logo_yolu": f.logo_yolu,
                "varsayilan_para_birimi": f.varsayilan_para_birimi,
                "fatura_seri": f.fatura_seri,
                "aktif": f.aktif,
                "db_path": f.db_path,
                "olusturma_tarihi": f.olusturma_tarihi,
            }

    @staticmethod
    def ozet_liste_herkese() -> list[tuple[int, str]]:
        """Kullanıcı kartı firma seçimi için (yalnızca id/unvan)."""
        with get_system_session() as session:
            return [
                (f.id, f"{f.firma_kodu} — {f.unvan}")
                for f in session.scalars(
                    select(Company).where(Company.aktif.is_(True)).order_by(Company.unvan)
                ).all()
            ]

    @staticmethod
    def _firma_db_hazirla(db_path: Path, unvan: str, kod: str, firma_uid: str) -> None:
        """Boş operasyon DB + tablolar + yerel firma + varsayılan dönem."""
        from database.models.donem import Donem
        from database.models.firma import Firma
        from database.stok_service import StokService
        from database.finans_service import FinansService
        from database.database import get_session, firma_db_ac

        company_db.firma_db_olustur(Base.metadata, firma_uid=firma_uid, hedef_yol=db_path)

        onceki_id = company_db.company_id
        onceki_yol = company_db.db_path
        try:
            firma_db_ac(0, db_path)
            Base.metadata.create_all(company_db.engine)
            from database.database import cari_kart_schemasini_guncelle

            try:
                cari_kart_schemasini_guncelle()
            except Exception:
                pass
            try:
                from database.deleted_record_service import AuditDeleteService

                AuditDeleteService.schema_hazirla()
            except Exception:
                pass
            with get_session() as session:
                yerel = session.scalar(select(Firma).limit(1))
                if yerel is None:
                    yerel = Firma(firma_kodu=kod[:20], unvan=unvan, aktif=True)
                    session.add(yerel)
                    session.flush()
                yil = date.today().year
                if session.scalar(select(Donem).limit(1)) is None:
                    session.add(
                        Donem(
                            firma_id=yerel.id,
                            donem_adi=str(yil),
                            baslangic_tarihi=date(yil, 1, 1),
                            bitis_tarihi=date(yil, 12, 31),
                            aktif=True,
                            kapali=False,
                            varsayilan=True,
                        )
                    )
            StokService.varsayilanlari_hazirla()
            FinansService.varsayilanlari_hazirla()
        finally:
            if onceki_id is not None and onceki_yol is not None:
                firma_db_ac(onceki_id, onceki_yol)
            else:
                company_db.close()

    @staticmethod
    def ekle(veriler: dict) -> int:
        CompanyMgmtService._yetki()
        uid = str(uuid.uuid4())
        db_path = COMPANIES_DIR / f"company_{uid}.db"
        company_id = None
        try:
            with get_system_session() as session:
                firma = Company(
                    firma_uid=uid,
                    firma_kodu=veriler["firma_kodu"].strip(),
                    unvan=veriler["unvan"].strip(),
                    kisa_ad=(veriler.get("kisa_ad") or "").strip() or None,
                    vergi_dairesi=(veriler.get("vergi_dairesi") or "").strip() or None,
                    vergi_no=(veriler.get("vergi_no") or "").strip() or None,
                    telefon=(veriler.get("telefon") or "").strip() or None,
                    email=(veriler.get("email") or "").strip() or None,
                    internet=(veriler.get("internet") or "").strip() or None,
                    adres=(veriler.get("adres") or "").strip() or None,
                    il=(veriler.get("il") or "").strip() or None,
                    ilce=(veriler.get("ilce") or "").strip() or None,
                    logo_yolu=(veriler.get("logo_yolu") or "").strip() or None,
                    varsayilan_para_birimi=veriler.get("varsayilan_para_birimi") or "TRY",
                    fatura_seri=(veriler.get("fatura_seri") or "").strip() or None,
                    aktif=bool(veriler.get("aktif", True)),
                    db_path=str(db_path.resolve()),
                )
                session.add(firma)
                try:
                    session.flush()
                except IntegrityError as hata:
                    raise ValueError("Firma kodu zaten kullanılıyor.") from hata
                company_id = firma.id
                # Oluşturan yöneticiye yetki ver
                if oturum.user_id:
                    session.add(UserCompany(user_id=oturum.user_id, company_id=firma.id))
                AuthService.audit(
                    session, "yeni_kayit", modul="firma", kayit_id=str(firma.id),
                    yeni_deger=firma.unvan,
                )
            CompanyMgmtService._firma_db_hazirla(
                db_path,
                veriler["unvan"].strip(),
                veriler["firma_kodu"].strip(),
                uid,
            )
            return company_id
        except Exception:
            # Yarım kayıt bırakma
            if company_id is not None:
                try:
                    with get_system_session() as session:
                        f = session.get(Company, company_id)
                        if f:
                            session.delete(f)
                except Exception:
                    pass
            if db_path.exists():
                try:
                    db_path.unlink()
                except OSError:
                    pass
            raise

    @staticmethod
    def guncelle(company_id: int, veriler: dict) -> None:
        CompanyMgmtService._yetki()
        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı.")
            f.firma_kodu = veriler["firma_kodu"].strip()
            f.unvan = veriler["unvan"].strip()
            f.kisa_ad = (veriler.get("kisa_ad") or "").strip() or None
            f.vergi_dairesi = (veriler.get("vergi_dairesi") or "").strip() or None
            f.vergi_no = (veriler.get("vergi_no") or "").strip() or None
            f.telefon = (veriler.get("telefon") or "").strip() or None
            f.email = (veriler.get("email") or "").strip() or None
            f.internet = (veriler.get("internet") or "").strip() or None
            f.adres = (veriler.get("adres") or "").strip() or None
            f.il = (veriler.get("il") or "").strip() or None
            f.ilce = (veriler.get("ilce") or "").strip() or None
            if "logo_yolu" in veriler:
                f.logo_yolu = (veriler.get("logo_yolu") or "").strip() or None
            f.varsayilan_para_birimi = veriler.get("varsayilan_para_birimi") or "TRY"
            f.fatura_seri = (veriler.get("fatura_seri") or "").strip() or None
            f.aktif = bool(veriler.get("aktif", True))
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Firma kodu zaten kullanılıyor.") from hata
            AuthService.audit(
                session, "duzenleme", modul="firma", kayit_id=str(company_id),
                yeni_deger=f.unvan,
            )

    @staticmethod
    def pasife_al(company_id: int) -> None:
        CompanyMgmtService._yetki()
        if oturum.company_id == company_id:
            raise ValueError("Aktif çalıştığınız firmayı pasife alamazsınız. Önce firma değiştirin.")
        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı.")
            f.aktif = False
            AuthService.audit(session, "pasife_alma", modul="firma", kayit_id=str(company_id))

    @staticmethod
    def yedek_al(company_id: int, hedef_klasor: str | Path) -> Path:
        CompanyMgmtService._yetki()
        if not oturum.has_permission("yedek_alma") and oturum.role_kod != "YONETICI":
            raise PermissionError("Yedek alma yetkiniz yok.")
        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı.")
            kaynak = Path(f.db_path)
            if not kaynak.is_file():
                raise FileNotFoundError("Firma veritabanı dosyası yok.")
            klasor = Path(hedef_klasor)
            klasor.mkdir(parents=True, exist_ok=True)
            damga = datetime.now().strftime("%Y%m%d_%H%M%S")
            hedef = klasor / f"{f.firma_kodu}_{damga}.db"
            shutil.copy2(kaynak, hedef)
            for ek in ("-wal", "-shm"):
                k = Path(str(kaynak) + ek)
                if k.is_file():
                    shutil.copy2(k, Path(str(hedef) + ek))
            AuthService.audit(
                session, "yedekleme", modul="firma", kayit_id=str(company_id),
                yeni_deger=str(hedef),
            )
            return hedef
