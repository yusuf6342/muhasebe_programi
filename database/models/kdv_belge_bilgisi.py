"""Belgenin özel KDV bilgisi: indirilebilirlik, işlem türü (tevkifat / istisna / …), iade kaynak notu.

Fatura tablolarına kolon eklenmez; bilgi belge türü + belge id ile ayrı tabloda tutulur. Kaydı olmayan
belge veya boş alan "Belirtilmemiş" demektir: eski kayıtlar kendiliğinden "indirilebilir" ya da
"normal işlem" sayılmaz. Tablo ilk kayıtta, doğrulanmış yedekten sonra oluşturulur.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

INDIRILECEK = "INDIRILECEK"
KKEG = "KKEG"
MALIYET = "MALIYET"
INDIRILEBILIRLIK_SECENEKLERI = {
    INDIRILECEK: "İndirilecek KDV",
    KKEG: "İndirilemez — KKEG",
    MALIYET: "İndirilemez — maliyete eklenecek",
}

NORMAL = "NORMAL"
TEVKIFAT = "TEVKIFAT"
ISTISNA = "ISTISNA"
OZEL_MATRAH = "OZEL_MATRAH"
IHRAC_KAYITLI = "IHRAC_KAYITLI"
IADE_HAKKI = "IADE_HAKKI"
ISLEM_TURLERI = {
    NORMAL: "Normal işlem",
    TEVKIFAT: "Kısmi tevkifatlı işlem",
    ISTISNA: "İstisna",
    OZEL_MATRAH: "Özel matrah",
    IHRAC_KAYITLI: "İhraç kayıtlı işlem",
    IADE_HAKKI: "İade hakkı doğuran işlem",
}


class KdvBelgeBilgisi(Base):
    __tablename__ = "kdv_belge_bilgileri"
    __table_args__ = (UniqueConstraint("belge_turu", "belge_id", name="uq_kdv_belge_bilgisi"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    belge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    indirilebilirlik: Mapped[str | None] = mapped_column(String(20), nullable=True)
    islem_turu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tevkifat_pay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tevkifat_payda: Mapped[int | None] = mapped_column(Integer, nullable=True)
    istisna_kodu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kaynak_yok_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
