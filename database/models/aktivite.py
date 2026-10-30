"""Aktivite Yönetimi — görev, sevkiyat, sefer ve rota ortak kaydı."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

SEFER_DURUMLARI = (
    "TASLAK",
    "PLANLANDI",
    "KESINLESTI",
    "YOLDA",
    "TAMAMLANDI",
    "IPTAL",
)

TESLIMAT_TURLERI = (
    "BELIRLENMEDI",
    "KENDI_ARACIMIZ",
    "KARGO",
    "MUSTERI_ALDI",
    "DIGER",
)


class AktiviteTuru(Base):
    __tablename__ = "aktivite_turleri"
    __table_args__ = (UniqueConstraint("kod", name="uq_aktivite_tur_kod"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    ad: Mapped[str] = mapped_column(String(120), nullable=False)
    varsayilan_sure_dk: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    sevkiyat_mi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dis_is_mi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Aktivite(Base):
    __tablename__ = "aktiviteler"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    konu: Mapped[str] = mapped_column(String(200), nullable=False)
    tur_id: Mapped[int] = mapped_column(ForeignKey("aktivite_turleri.id"), nullable=False, index=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="ACIK", index=True)
    # ACIK | DEVAM | BEKLEMEDE | TAMAMLANDI | IPTAL
    oncelik: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    # DUSUK | NORMAL | YUKSEK
    plan_tarih: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    plan_saat: Mapped[str | None] = mapped_column(String(8), nullable=True)
    son_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    tahmini_sure_dk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sorumlu_personel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kaynak_belge_tur: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # SATIS_FATURA | SATIS_IRSALIYE | SATIS_SIPARIS | ...
    kaynak_belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kaynak_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    teslim_partisi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    teslimat_turu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sevkiyat_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # HAZIRLANIYOR | HAZIR | YUKLENDI | YOLDA | KISMI | TESLIM | TESLIM_EDILEMEDI
    adres_metin: Mapped[str | None] = mapped_column(Text, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    tamamlanma_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sonuc_kod: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AktiviteTekillik(Base):
    """Belge olayı → aktivite tekilliği (firma+kaynak+tür+parti)."""

    __tablename__ = "aktivite_tekillik"
    __table_args__ = (
        UniqueConstraint(
            "kaynak_belge_tur",
            "kaynak_belge_id",
            "tur_kod",
            "teslim_partisi",
            name="uq_aktivite_tekillik",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak_belge_tur: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_belge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tur_kod: Mapped[str] = mapped_column(String(40), nullable=False)
    teslim_partisi: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    aktivite_id: Mapped[int] = mapped_column(ForeignKey("aktiviteler.id"), nullable=False)


class AktiviteSefer(Base):
    """Günlük sefer — araç/görevli/çıkış; harita sağlayıcısı ayrı katman."""

    __tablename__ = "aktivite_seferler"
    __table_args__ = (
        UniqueConstraint("sefer_tarih", "sefer_no", name="uq_aktivite_sefer_gun_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sefer_tarih: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sefer_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TASLAK")
    arac_kod: Mapped[str | None] = mapped_column(String(40), nullable=True)
    arac_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gorevli_personel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    baslangic_adres: Mapped[str | None] = mapped_column(Text, nullable=True)
    donus_adres: Mapped[str | None] = mapped_column(Text, nullable=True)
    cikis_saat: Mapped[str | None] = mapped_column(String(8), nullable=True)  # HH:MM
    en_gec_donus_saat: Mapped[str | None] = mapped_column(String(8), nullable=True)
    rota_modu: Mapped[str] = mapped_column(String(20), nullable=False, default="ELLE")
    # ELLE | TEST_VERISI | SAGLAYICI
    rota_ozet: Mapped[str | None] = mapped_column(Text, nullable=True)
    tahmini_yol_dk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tahmini_is_dk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tahmini_toplam_dk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tahmini_donus_saat: Mapped[str | None] = mapped_column(String(8), nullable=True)
    harita_saglayici: Mapped[str | None] = mapped_column(String(40), nullable=True)
    harita_uyari: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AktiviteSeferDurak(Base):
    """Sefer durağı = bir aktivite; sıra kullanıcı veya öneri ile."""

    __tablename__ = "aktivite_sefer_duraklar"
    __table_args__ = (
        UniqueConstraint("sefer_id", "aktivite_id", name="uq_sefer_aktivite"),
        UniqueConstraint("sefer_id", "sira", name="uq_sefer_sira"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sefer_id: Mapped[int] = mapped_column(
        ForeignKey("aktivite_seferler.id"), nullable=False, index=True
    )
    aktivite_id: Mapped[int] = mapped_column(
        ForeignKey("aktiviteler.id"), nullable=False, index=True
    )
    sira: Mapped[int] = mapped_column(Integer, nullable=False)
    yol_dk_onceki: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Önceki noktadan bu durağa yol süresi (dk); None = hesaplanmadı
    is_dk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tahmini_varis: Mapped[str | None] = mapped_column(String(8), nullable=True)
    planlanamadi_neden: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
