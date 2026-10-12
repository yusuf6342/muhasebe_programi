"""Devreden KDV kaydı: yetkili kullanıcının dönem başına girdiği önceki dönemden devreden KDV.

Program beyanname vermez ve vergi kaydı oluşturmaz; bu tablo yalnızca KDV raporundaki ön hesap için
kullanıcının beyan ettiği devreden tutarı saklar. Değişiklikte eski kayıt silinmez, ``durum=IPTAL``
olur; kesinleşmiş kayıt ancak açık gerekçeyle değiştirilebilir.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

DURUM_AKTIF = "AKTIF"
DURUM_IPTAL = "IPTAL"


class KdvDevredenKaydi(Base):
    __tablename__ = "kdv_devreden_kayitlari"
    __table_args__ = (Index("ix_kdv_devreden_donem", "yil", "ay", "durum"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    ay: Mapped[int] = mapped_column(Integer, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kaynak: Mapped[str] = mapped_column(String(60), nullable=False)
    aciklama: Mapped[str] = mapped_column(Text, nullable=False)
    kesinlesti: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    durum: Mapped[str] = mapped_column(String(10), nullable=False, default=DURUM_AKTIF)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    iptal_gerekcesi: Mapped[str | None] = mapped_column(Text, nullable=True)
    iptal_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
