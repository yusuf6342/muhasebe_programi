from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.models.firma import Firma  # noqa: F401
from database.models.donem import Donem  # noqa: F401


class Sube(Base):
    __tablename__ = "subeler"
    __table_args__ = (
        UniqueConstraint("firma_id", "sube_kodu", name="uq_sube_firma_kodu"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(
        ForeignKey("firmalar.id"), nullable=False, index=True
    )
    sube_kodu: Mapped[str] = mapped_column(String(30), nullable=False)
    sube_adi: Mapped[str] = mapped_column(String(120), nullable=False)
    merkez: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    adres: Mapped[str | None] = mapped_column(Text, nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vergi_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    firma = relationship("Firma", back_populates="subeler")
