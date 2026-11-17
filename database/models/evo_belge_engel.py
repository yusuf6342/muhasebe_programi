"""Evo Bulut evrak kaynağı engeli — silinen/düzeltilen EVB belge yeniden oluşmasın."""

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class EvoBelgeEngel(Base):
    """Manuel silinen veya düzeltme sonrası yeniden aktarımı engellenen Evo evrakı."""

    __tablename__ = "evo_belge_engelleri"
    __table_args__ = (
        UniqueConstraint("kaynak_sistem", "kaynak_kimlik", name="uq_evo_belge_engel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak_sistem: Mapped[str] = mapped_column(String(40), nullable=False, default="EVOBULUT")
    # Örn. AF:14881 | BN:21157 | BNC:21807 | AK:1875 | ACL:99 | belge_no
    kaynak_kimlik: Mapped[str] = mapped_column(String(80), nullable=False)
    belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    belge_turu: Mapped[str | None] = mapped_column(String(40), nullable=True)
    neden: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
