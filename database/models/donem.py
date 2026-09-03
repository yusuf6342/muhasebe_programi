from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class Donem(Base):
    __tablename__ = "donemler"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    firma_id: Mapped[int] = mapped_column(
        ForeignKey("firmalar.id"),
        nullable=False
    )

    donem_adi: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    baslangic_tarihi: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    bitis_tarihi: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    aktif: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False
    )
