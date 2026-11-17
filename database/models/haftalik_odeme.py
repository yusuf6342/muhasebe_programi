"""Tedarikçi haftalık ödeme planı — belge bazlı sabit 9 Cuma taksiti."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class CariHaftalikOdemeTaksit(Base):
    """Açılış veya alış belgesinin haftalık (Cuma) taksit satırı.

    ``odenen_tutar`` gerçek cari ödemelerin FIFO mahsubudur.
    Mükerrer engeli: ``(cari_id, belge_anahtar, taksit_no)``.
    """

    __tablename__ = "cari_haftalik_odeme_taksitleri"
    __table_args__ = (
        UniqueConstraint(
            "cari_id",
            "belge_anahtar",
            "taksit_no",
            name="uq_cari_haftalik_odeme_belge_taksit",
        ),
        Index("ix_cari_haftalik_odeme_vade", "cari_id", "vade_tarihi"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=False, index=True
    )
    # SH:{satis_hareket_id} | CI:{cari_islem_id}
    belge_anahtar: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    kaynak_tur: Mapped[str] = mapped_column(String(20), nullable=False)  # SATIS_HAREKET|CARI_ISLEM
    kaynak_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fatura_hareket_id: Mapped[int | None] = mapped_column(
        ForeignKey("cari_satis_hareketleri.id"), nullable=True, index=True
    )
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    fatura_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    taksit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    taksit_adet: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    planlanan_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    odenen_tutar: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    ortalama_valor_gun: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )
    olusturma: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
