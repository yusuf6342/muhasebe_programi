from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.models.firma import Firma


class FirmaService:
    @staticmethod
    def listele(arama: str = "") -> Sequence[Firma]:
        with get_session() as session:
            statement = select(Firma).order_by(Firma.firma_kodu)
            arama = arama.strip()
            if arama:
                ifade = f"%{arama}%"
                statement = statement.where(
                    or_(
                        Firma.firma_kodu.ilike(ifade),
                        Firma.unvan.ilike(ifade),
                        Firma.vergi_no.ilike(ifade),
                    )
                )
            return session.scalars(statement).all()

    @staticmethod
    def getir(firma_id: int) -> Firma | None:
        with get_session() as session:
            return session.get(Firma, firma_id)

    @staticmethod
    def ekle(veriler: dict[str, object]) -> Firma:
        with get_session() as session:
            firma = Firma(**veriler)
            session.add(firma)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Firma kodu zaten kullanılıyor.") from hata
            return firma

    @staticmethod
    def guncelle(firma_id: int, veriler: dict[str, object]) -> Firma:
        with get_session() as session:
            firma = session.get(Firma, firma_id)
            if firma is None:
                raise ValueError("Firma bulunamadı.")
            for alan, deger in veriler.items():
                setattr(firma, alan, deger)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Firma kodu zaten kullanılıyor.") from hata
            return firma

    @staticmethod
    def pasife_al(firma_id: int) -> None:
        with get_session() as session:
            firma = session.get(Firma, firma_id)
            if firma is None:
                raise ValueError("Firma bulunamadı.")
            firma.aktif = False
            session.flush()
