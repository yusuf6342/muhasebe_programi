from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

PARA_BIRIMLERI = ("TRY", "USD", "EUR")
KUR_TURLERI = (
    ("forex_selling", "Döviz Satış"),
    ("forex_buying", "Döviz Alış"),
    ("effective_selling", "Efektif Satış"),
    ("effective_buying", "Efektif Alış"),
)
KUR_KAYNAKLARI = ("TCMB", "MANUEL", "OZEL")
BORC_ESASLARI = (
    ("TL_SABIT", "TL Sabit"),
    ("DOVIZ_SABIT", "Döviz Sabit"),
)
RAPOR_KUR_YONTEMLERI = (
    ("islem_tarihi", "İşlem Tarihi Kuru"),
    ("tahsilat_tarihi", "Tahsilat Tarihi Kuru"),
    ("rapor_tarihi", "Bugünkü Kur"),
    ("sabit_kur", "Sabit Yönetim Kuru"),
)


class DovizKuru(Base):
    """Günlük USD/EUR kur kayıtları."""

    __tablename__ = "doviz_kurlari"
    __table_args__ = (UniqueConstraint("rate_date", "currency_code", name="uq_doviz_kur_tarih_para"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    forex_buying: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    forex_selling: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    effective_buying: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    effective_selling: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="TCMB")
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
