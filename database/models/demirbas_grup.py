"""Dönen sermaye bilançosunda stok toplamından hariç tutulan demirbaş stok grupları.

Grup kimliğiyle saklanır; işaretli grubun tüm alt grupları ve bu gruplara bağlı kartlar da hariçtir.
Grup adına bakılarak tahmin yapılmaz.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class DemirbasStokGrubu(Base):
    __tablename__ = "demirbas_stok_gruplari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    grup_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
