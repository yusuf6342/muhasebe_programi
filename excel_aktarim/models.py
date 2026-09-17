"""Excel aktarım audit tabloları (firma DB)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_kodu: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    modul: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    import_tipi: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    dosya_adi: Mapped[str | None] = mapped_column(String(260), nullable=True)
    dosya_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="taslak")
    # taslak | dogrulandi | dry_run | basarili | kismi | hatali | geri_alindi
    toplam_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    basarili_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hata_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    atlanan_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    guncellenen_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eklenen_satir: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kullanici_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    hata_ozeti: Mapped[str | None] = mapped_column(Text, nullable=True)
    basladi_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bitti_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    satir_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ham_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    eslenen_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="bekliyor")
    # bekliyor | gecerli | hata | ekle | guncelle | atla | uygulandi | geri_alindi
    mesaj: Mapped[str | None] = mapped_column(Text, nullable=True)
    hedef_tablo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hedef_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    islem: Mapped[str | None] = mapped_column(String(20), nullable=True)  # insert|update|skip


class ImportMapping(Base):
    __tablename__ = "import_mappings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    import_tipi: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    ad: Mapped[str] = mapped_column(String(120), nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    varsayilan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportChange(Base):
    __tablename__ = "import_changes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    satir_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hedef_tablo: Mapped[str] = mapped_column(String(80), nullable=False)
    hedef_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    islem: Mapped[str] = mapped_column(String(20), nullable=False)  # insert|update|soft_delete
    onceki_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sonraki_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    geri_alindi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
