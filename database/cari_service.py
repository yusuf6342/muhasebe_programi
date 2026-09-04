from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.models.cari import Cari, SatisHareketi


class CariService:
    @staticmethod
    def _arama_kontrol(arama: str) -> str:
        arama = arama.strip()
        if arama and len(arama) < 3:
            raise ValueError("Arama için en az 3 karakter girin.")
        return arama

    @staticmethod
    def listele(arama: str = "") -> list[dict[str, Any]]:
        arama = CariService._arama_kontrol(arama)
        with get_session() as session:
            statement = select(Cari).order_by(Cari.cari_kodu)
            if arama:
                ifade = f"%{arama}%"
                statement = statement.where(
                    or_(
                        Cari.cari_kodu.ilike(ifade),
                        Cari.unvan.ilike(ifade),
                        Cari.telefon.ilike(ifade),
                    )
                )
            cariler = session.scalars(statement).all()
            return [CariService._ozet(cari) for cari in cariler]

    @staticmethod
    def getir(cari_id: int) -> Cari | None:
        with get_session() as session:
            return session.get(Cari, cari_id)

    @staticmethod
    def detay(cari_id: int) -> dict[str, Any] | None:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                return None
            return {
                "cari": cari,
                "hareketler": [
                    hareket
                    for hareket in sorted(cari.satis_hareketleri, key=lambda item: item.satis_tarihi, reverse=True)
                    if hareket.kalan_acik_tutar > 0
                ],
            }

    @staticmethod
    def ekle(veriler: dict[str, object]) -> Cari:
        with get_session() as session:
            cari = Cari(**veriler)
            session.add(cari)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Cari kodu zaten kullanılıyor.") from hata
            return cari

    @staticmethod
    def guncelle(cari_id: int, veriler: dict[str, object]) -> Cari:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            for alan, deger in veriler.items():
                setattr(cari, alan, deger)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Cari kodu zaten kullanılıyor.") from hata
            return cari

    @staticmethod
    def pasife_al(cari_id: int) -> None:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            cari.aktif = False
            session.flush()

    @staticmethod
    def satis_ekle(cari_id: int, veriler: dict[str, object]) -> SatisHareketi:
        satis_tarihi = veriler.get("satis_tarihi")
        satis_tutari = CariService._tutar(veriler.get("satis_tutari"))
        kalan = CariService._tutar(veriler.get("kalan_acik_tutar"))
        if not isinstance(satis_tarihi, date) or satis_tarihi > date.today():
            raise ValueError("Satış tarihi gelecek bir tarih olamaz.")
        if satis_tutari <= 0 or kalan < 0:
            raise ValueError("Satış tutarı pozitif, kalan tutar sıfır veya daha büyük olmalıdır.")
        if kalan > satis_tutari:
            raise ValueError("Kalan açık tutar satış tutarından büyük olamaz.")
        with get_session() as session:
            if session.get(Cari, cari_id) is None:
                raise ValueError("Cari bulunamadı.")
            hareket = SatisHareketi(
                cari_id=cari_id,
                satis_tarihi=satis_tarihi,
                belge_no=str(veriler.get("belge_no", "")).strip(),
                satis_tutari=satis_tutari,
                kalan_acik_tutar=kalan,
            )
            if not hareket.belge_no:
                raise ValueError("Belge/fatura numarası zorunludur.")
            session.add(hareket)
            session.flush()
            return hareket

    @staticmethod
    def _tutar(deger: object) -> Decimal:
        try:
            return Decimal(str(deger).replace(".", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValueError("Tutar geçerli bir sayı olmalıdır.") from None

    @staticmethod
    def _ozet(cari: Cari) -> dict[str, Any]:
        bugun = date.today()
        aciklar = [
            hareket for hareket in cari.satis_hareketleri if hareket.kalan_acik_tutar > 0
        ]
        gunler = [
            (bugun - hareket.satis_tarihi).days
            for hareket in aciklar
        ]
        bakiye = sum((hareket.kalan_acik_tutar for hareket in aciklar), Decimal("0"))
        ortalama = sum(gunler) / len(gunler) if gunler else 0
        agirlikli = (
            sum((float(hareket.kalan_acik_tutar) * gun for hareket, gun in zip(aciklar, gunler)), 0.0) / float(bakiye)
            if bakiye else 0
        )
        return {
            "cari": cari,
            "bakiye": bakiye,
            "ortalama_gun": ortalama,
            "agirlikli_ortalama_gun": agirlikli,
        }
