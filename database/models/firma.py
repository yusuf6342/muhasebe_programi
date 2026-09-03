from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class Firma(Base):
    __tablename__ = "firmalar"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    firma_kodu: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False
    )

    unvan: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    vergi_no: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    vergi_dairesi: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    telefon: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True
    )

    email: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True
    )

    adres: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
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
