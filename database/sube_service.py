from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.models.firma import Firma
from database.models.sube import Sube


class SubeService:
    """Firma kapsamli sube yonetimi ve belge secim yardimcilari."""

    MERKEZ_KODU = "MERKEZ"
    MERKEZ_ADI = "Merkez Sube"

    @classmethod
    def transaction_subesi(cls, session, sube_id: int | None = None) -> int:
        """Aktif subeyi transaction icinde dogrular; yoksa Merkez'i olusturur."""
        if sube_id:
            sube = session.scalar(
                select(Sube).where(Sube.id == int(sube_id), Sube.aktif.is_(True))
            )
            if sube is not None:
                return int(sube.id)
            raise ValueError("Seçilen şube aktif değil veya bulunamadı.")
        merkez = session.scalar(select(Sube).where(Sube.merkez.is_(True), Sube.aktif.is_(True)))
        if merkez is not None:
            return int(merkez.id)
        firma_id = session.scalar(select(Firma.id).order_by(Firma.id))
        if not firma_id:
            raise ValueError("Şube için firma bulunamadı.")
        merkez = Sube(
            firma_id=int(firma_id),
            sube_kodu=cls.MERKEZ_KODU,
            sube_adi=cls.MERKEZ_ADI,
            merkez=True,
            aktif=True,
        )
        session.add(merkez)
        session.flush()
        return int(merkez.id)

    @classmethod
    def merkez_hazirla(cls, firma_id: int) -> Sube:
        with get_session() as session:
            firma = session.get(Firma, int(firma_id))
            if firma is None:
                raise ValueError("Firma bulunamadı.")
            merkezler = list(
                session.scalars(
                    select(Sube).where(
                        Sube.firma_id == firma.id, Sube.merkez.is_(True)
                    )
                )
            )
            if merkezler:
                merkez = merkezler[0]
                if not merkez.aktif:
                    merkez.aktif = True
                return merkez
            merkez = session.scalar(
                select(Sube).where(
                    Sube.firma_id == firma.id, Sube.sube_kodu == cls.MERKEZ_KODU
                )
            )
            if merkez is None:
                merkez = Sube(
                    firma_id=firma.id,
                    sube_kodu=cls.MERKEZ_KODU,
                    sube_adi=cls.MERKEZ_ADI,
                    merkez=True,
                    aktif=True,
                )
                session.add(merkez)
            else:
                merkez.merkez = True
                merkez.aktif = True
            session.flush()
            return merkez

    @classmethod
    def migration_hazirla(cls) -> None:
        """Eski DB'ye tabloyu ve firma basina tam bir Merkez subeyi ekler."""
        from database.database import Base, engine

        Sube.__table__.create(bind=engine, checkfirst=True)
        with get_session() as session:
            firma_ids = list(session.scalars(select(Firma.id)))
        for firma_id in firma_ids:
            cls.merkez_hazirla(int(firma_id))

    @classmethod
    def listele(cls, firma_id: int, *, aktif_sadece: bool = False) -> Sequence[Sube]:
        with get_session() as session:
            statement = select(Sube).where(Sube.firma_id == int(firma_id))
            if aktif_sadece:
                statement = statement.where(Sube.aktif.is_(True))
            return session.scalars(
                statement.order_by(Sube.merkez.desc(), Sube.sube_adi, Sube.sube_kodu)
            ).all()

    @classmethod
    def merkez(cls, firma_id: int) -> Sube:
        return cls.merkez_hazirla(int(firma_id))

    @classmethod
    def getir(cls, sube_id: int, firma_id: int) -> Sube | None:
        with get_session() as session:
            return session.scalar(
                select(Sube).where(
                    Sube.id == int(sube_id), Sube.firma_id == int(firma_id)
                )
            )

    @classmethod
    def ekle(cls, firma_id: int, veriler: dict[str, object]) -> Sube:
        kod = str(veriler.get("sube_kodu") or "").strip().upper()
        ad = str(veriler.get("sube_adi") or "").strip()
        if not kod or not ad:
            raise ValueError("Şube kodu ve şube adı zorunludur.")
        with get_session() as session:
            sube = Sube(
                firma_id=int(firma_id),
                sube_kodu=kod,
                sube_adi=ad,
                merkez=False,
                aktif=True,
                adres=veriler.get("adres") or None,
                telefon=veriler.get("telefon") or None,
                vergi_no=veriler.get("vergi_no") or None,
                vergi_dairesi=veriler.get("vergi_dairesi") or None,
            )
            session.add(sube)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError("Bu firma içinde şube kodu zaten kullanılıyor.") from exc
            return sube

    @classmethod
    def guncelle(cls, sube_id: int, firma_id: int, veriler: dict[str, object]) -> Sube:
        with get_session() as session:
            sube = session.scalar(
                select(Sube).where(Sube.id == int(sube_id), Sube.firma_id == int(firma_id))
            )
            if sube is None:
                raise ValueError("Şube bulunamadı.")
            if sube.merkez and veriler.get("aktif") is False:
                raise ValueError("Merkez Şube pasife alınamaz.")
            for alan in ("sube_kodu", "sube_adi", "adres", "telefon", "vergi_no", "vergi_dairesi"):
                if alan in veriler:
                    deger = veriler[alan]
                    setattr(sube, alan, str(deger).strip() if deger else None)
            if "sube_kodu" in veriler and sube.sube_kodu:
                sube.sube_kodu = sube.sube_kodu.upper()
            if "aktif" in veriler and not sube.merkez:
                sube.aktif = bool(veriler["aktif"])
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError("Bu firma içinde şube kodu zaten kullanılıyor.") from exc
            return sube

    @classmethod
    def pasife_al(cls, sube_id: int, firma_id: int) -> None:
        with get_session() as session:
            sube = session.scalar(
                select(Sube).where(Sube.id == int(sube_id), Sube.firma_id == int(firma_id))
            )
            if sube is None:
                raise ValueError("Şube bulunamadı.")
            if sube.merkez:
                raise ValueError("Merkez Şube pasife alınamaz.")
            sube.aktif = False
            session.flush()

    @classmethod
    def secimi_dogrula(cls, sube_id: int | None, firma_id: int) -> Sube:
        if not sube_id:
            raise ValueError("Şube seçimi zorunludur.")
        sube = cls.getir(int(sube_id), int(firma_id))
        if sube is None or not sube.aktif:
            raise ValueError("Seçilen şube bu firmaya ait değil veya aktif değil.")
        return sube
