"""Firma veritabanında modül bazlı, sürümlü ve tekrar çalıştırılabilir şema geçişleri."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import DateTime, Integer, String, inspect, select, text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class ModulSemaSurumu(Base):
    __tablename__ = "modul_sema_surumleri"

    modul: Mapped[str] = mapped_column(String(60), primary_key=True)
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uygulama_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


def eksik_kolonlari_ekle(engine, tablo: str, kolonlar: dict[str, str]) -> list[str]:
    """Tabloda olmayan kolonları ``ALTER TABLE ADD COLUMN`` ile ekler; eklenenleri döner."""
    insp = inspect(engine)
    if not insp.has_table(tablo):
        return []
    mevcut = {c["name"] for c in insp.get_columns(tablo)}
    eksik = [(ad, tip) for ad, tip in kolonlar.items() if ad not in mevcut]
    if eksik:
        with engine.begin() as baglanti:
            for ad, tip in eksik:
                baglanti.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{ad}" {tip}'))
    return [ad for ad, _ in eksik]


def surum_uygula(engine, modul: str, surum: int, gecis: Callable[[object], None]) -> bool:
    """Kayıtlı sürüm hedeften küçükse ``gecis(engine)`` çalışır ve sürüm yazılır.

    Geçiş fonksiyonları idempotent olmalıdır: yarıda kalan bir geçiş tekrar
    çalıştırıldığında aynı sonuca ulaşır.
    """
    ModulSemaSurumu.__table__.create(engine, checkfirst=True)
    with engine.begin() as baglanti:
        mevcut = baglanti.execute(
            select(ModulSemaSurumu.surum).where(ModulSemaSurumu.modul == modul)
        ).scalar()
    if mevcut is not None and int(mevcut) >= surum:
        return False
    gecis(engine)
    with engine.begin() as baglanti:
        if mevcut is None:
            baglanti.execute(
                ModulSemaSurumu.__table__.insert().values(
                    modul=modul, surum=surum, uygulama_tarihi=datetime.now()
                )
            )
        else:
            baglanti.execute(
                ModulSemaSurumu.__table__.update()
                .where(ModulSemaSurumu.modul == modul)
                .values(surum=surum, uygulama_tarihi=datetime.now())
            )
    return True
