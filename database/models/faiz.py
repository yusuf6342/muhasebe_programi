"""Günlük faiz oran tanımları, ürün kuralları ve tahakkuk kayıtları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class FaizOranTanimi(Base):
    __tablename__ = "faiz_oran_tanimlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # KK | KREDI | KMH
    urun_turu: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    urun_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # AKDI | GECIKME | NAKIT_AVANS
    faiz_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="AKDI")
    oran_yuzde: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    # AYLIK | YILLIK
    donem: Mapped[str] = mapped_column(String(10), nullable=False, default="YILLIK")
    # 360 | 365 | GERCEK
    gun_esasi: Mapped[str] = mapped_column(String(10), nullable=False, default="360")
    baslangic_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    bitis_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kaynak_not: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class FaizUrunKurali(Base):
    """Ürün düzeyinde tatil / valör / aynı-gün kullanım-kapanış kuralları (DOC2-18).

    Kural yoksa gerçek tahakkuk için tatil/valör varsayımı uydurulmaz → KURAL_EKSIK.
    """

    __tablename__ = "faiz_urun_kurallari"
    __table_args__ = (
        UniqueConstraint("urun_turu", "urun_id", name="uq_faiz_urun_kurali"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    urun_turu: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    urun_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # BANKA | RESMI | OZEL — kaynak kimliği; boş = tanımsız
    tatil_takvim_kaynagi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Aynı gün kullanım+kapanışta en az faiz günü (banka kuralı)
    ayni_gun_min_gun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Valör kaydırma: iş günü / takvim / tatil atlama
    # IS_GUNU | TAKVIM | TATIL_ATLA
    valor_mod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valor_kaydir_gun: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class GunlukFaizKaydi(Base):
    __tablename__ = "gunluk_faiz_kayitlari"
    __table_args__ = (
        # DOC2-21: firma + kalıcı borç kimliği + gün + bileşen + faiz türü
        UniqueConstraint(
            "firma_id",
            "borc_kimligi",
            "gun",
            "borc_bilesen",
            "faiz_turu",
            name="uq_gunluk_faiz_borc_gun",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, default=0)
    urun_turu: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    urun_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Kalıcı borç kimliği — ekstre/dönem devrinde aynı borç (DOC2-21)
    borc_kimligi: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    borc_bilesen: Mapped[str] = mapped_column(String(60), nullable=False, default="ANAPARA")
    gun: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    matrah: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    faiz_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="AKDI")
    oran_yuzde: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    gun_esasi: Mapped[str] = mapped_column(String(10), nullable=False, default="360")
    ham_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    yuvarlanmis_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # TAHMIN | TAHAKKUK | IPTAL | ORAN_EKSIK
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TAHAKKUK")
    gider_belge_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
