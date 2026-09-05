from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class KkCekimi(Base):
    """Müşteriden tedarikçiye kredi kartı çekimi fişi."""

    __tablename__ = "kk_cekimleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    musteri_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    tedarikci_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    banka: Mapped[str] = mapped_column(String(100), nullable=False)  # serbest metin (kar bankası adı)
    cekim_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="TEK ÇEKİM")
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")

    musteri = relationship("Cari", foreign_keys=[musteri_id])
    tedarikci = relationship("Cari", foreign_keys=[tedarikci_id])
