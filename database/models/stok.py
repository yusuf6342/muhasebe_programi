from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class Depo(Base):
    __tablename__ = "depolar"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StokSecenek(Base):
    """Stok kartı seçmeli alanları: rapor_grubu, marka, model, fonksiyon1, fonksiyon2, renk, raf_yeri."""

    __tablename__ = "stok_secenekleri"
    __table_args__ = (UniqueConstraint("tur", "ad", name="uq_stok_secenek_tur_ad"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tur: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)


class StokKarti(Base):
    __tablename__ = "stok_kartlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_kodu: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    stok_adi: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    barkod: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    kart_turu: Mapped[str] = mapped_column(String(50), nullable=False, default="Ticari Mal")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    muhasebe_stok_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_maliyet_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iskonto_1: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    iskonto_2: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    iskonto_3: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    marka: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fonksiyon1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fonksiyon2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    renk: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agirlik: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birim1: Mapped[str | None] = mapped_column(String(30), nullable=True)
    birim2: Mapped[str | None] = mapped_column(String(30), nullable=True)
    birim3: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rapor_grubu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raf_yeri: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raf_omru: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fiyatlar: Mapped[list["StokFiyati"]] = relationship(
        "StokFiyati", back_populates="stok", cascade="all, delete-orphan"
    )
    lotlar: Mapped[list["StokLotu"]] = relationship(
        "StokLotu", back_populates="stok", cascade="all, delete-orphan"
    )
    birimler: Mapped[list["StokBirim"]] = relationship(
        "StokBirim", back_populates="stok", cascade="all, delete-orphan"
    )
    resimler: Mapped[list["StokResmi"]] = relationship(
        "StokResmi", back_populates="stok", cascade="all, delete-orphan"
    )
    barkodlar: Mapped[list["StokBarkod"]] = relationship(
        "StokBarkod", back_populates="stok", cascade="all, delete-orphan"
    )
    fiyat_gecmisi: Mapped[list["StokFiyatGecmisi"]] = relationship(
        "StokFiyatGecmisi", back_populates="stok", cascade="all, delete-orphan"
    )


class StokFiyati(Base):
    __tablename__ = "stok_fiyatlari"
    __table_args__ = (UniqueConstraint("stok_id", "fiyat_adi", name="uq_stok_fiyat_adi"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    fiyat_adi: Mapped[str] = mapped_column(String(100), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(10), nullable=False, default="TL")
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="fiyatlar")


class StokBirim(Base):
    __tablename__ = "stok_birimleri"
    __table_args__ = (UniqueConstraint("stok_id", "birim_adi", name="uq_stok_birim_adi"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    birim_adi: Mapped[str] = mapped_column(String(30), nullable=False)
    carpan: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    # 1 birim_adi = carpan * ana birim (ör. 1 Paket = 1000 Adet)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="birimler")


class StokResmi(Base):
    __tablename__ = "stok_resimleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    dosya_yolu: Mapped[str] = mapped_column(String(500), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="resimler")


class StokBarkod(Base):
    __tablename__ = "stok_barkodlari"
    __table_args__ = (UniqueConstraint("barkod", name="uq_stok_barkod_deger"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    barkod: Mapped[str] = mapped_column(String(100), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    fiyat_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="barkodlar")


class StokFiyatGecmisi(Base):
    __tablename__ = "stok_fiyat_gecmisi"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    fiyat_adi: Mapped[str] = mapped_column(String(100), nullable=False)
    eski_tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    yeni_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    degisim_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="fiyat_gecmisi")


class StokLotu(Base):
    __tablename__ = "stok_lotlari"
    __table_args__ = (UniqueConstraint("stok_id", "depo_id", "lot_no", name="uq_stok_depo_lot"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    lot_no: Mapped[str] = mapped_column(String(100), nullable=False)
    tedarikci: Mapped[str | None] = mapped_column(String(200), nullable=True)
    giris_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    kalan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="lotlar")
    depo: Mapped["Depo"] = relationship("Depo")


class StokHareketi(Base):
    __tablename__ = "stok_hareketleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    hareket_turu: Mapped[str] = mapped_column(String(30), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class DepoTransferFisi(Base):
    __tablename__ = "depo_transfer_fisleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    fis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cikis_depo: Mapped[str] = mapped_column(String(100), nullable=False)
    giris_depo: Mapped[str] = mapped_column(String(100), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    genel_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    satirlar: Mapped[list["DepoTransferFisiSatiri"]] = relationship(
        "DepoTransferFisiSatiri", back_populates="fis", cascade="all, delete-orphan"
    )


class DepoTransferFisiSatiri(Base):
    __tablename__ = "depo_transfer_fisi_satirlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_id: Mapped[int] = mapped_column(ForeignKey("depo_transfer_fisleri.id"), nullable=False, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    lot_cikisi: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lot_girisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fis: Mapped["DepoTransferFisi"] = relationship("DepoTransferFisi", back_populates="satirlar")


class StokPaketBilesen(Base):
    """1 paket stok kartı içindeki ürün ve miktar (örn. 5 dübel, 10 vida)."""

    __tablename__ = "stok_paket_bilesenleri"
    __table_args__ = (UniqueConstraint("paket_stok_id", "bilesen_stok_id", name="uq_paket_bilesen"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paket_stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    bilesen_stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    paket_stok: Mapped["StokKarti"] = relationship("StokKarti", foreign_keys=[paket_stok_id])
    bilesen_stok: Mapped["StokKarti"] = relationship("StokKarti", foreign_keys=[bilesen_stok_id])


class StokPaketUretim(Base):
    """Paket stoğa üretim / birleştirme fişi."""

    __tablename__ = "stok_paket_uretimleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    uretim_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    paket_stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo: Mapped[str] = mapped_column(String(100), nullable=False)
    paket_adedi: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    toplam_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    paket_stok: Mapped["StokKarti"] = relationship("StokKarti", foreign_keys=[paket_stok_id])
