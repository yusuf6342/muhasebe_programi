"""Açık kalem geçişinde oluşturulan "Geçiş Devir Farkı" kalemlerinin açıklama / denetim kaydı."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class AcikKalemGecisKaydi(Base):
    """Her cari için en fazla bir devir farkı kaydı; kalem gerçek fatura/tahsilat değildir.

    İlgili açık kalem ``cari_satis_hareketleri`` içinde ``DVF-`` önekli, ``satis_tutari=0``
    satırdır; cari bakiyeyi değiştirmez.
    """

    __tablename__ = "acik_kalem_gecis_kayitlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    hareket_id: Mapped[int] = mapped_column(Integer, nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    onceki_bakiye: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    onceki_acik_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    haric_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aciklama: Mapped[str] = mapped_column(String(500), nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    yedek_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
