"""Satın Alma hub özet metrikleri — mevcut sipariş/irsaliye/fatura tablolarından."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.alis_faturasi import AlisFaturasi
from database.models.alis_irsaliyesi import AlisIrsaliyesiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri


class SatinAlmaHubService:
    @staticmethod
    def schema_hazirla() -> None:
        """İlgili yeni tabloları oluşturur (talep / teklif / fiyat / masraf)."""
        from database.database import company_db, Base
        import database.models.satin_alma_talep  # noqa: F401
        import database.models.tedarikci_teklif  # noqa: F401
        import database.models.tedarikci_fiyat  # noqa: F401
        import database.models.alis_masraf  # noqa: F401

        if company_db.engine is None:
            return
        Base.metadata.create_all(company_db.engine)

    @staticmethod
    def ozet_kartlar() -> dict:
        """Ana hub hızlı özet kartları."""
        SatinAlmaHubService.schema_hazirla()
        bugun = date.today()
        ay_basi = bugun.replace(day=1)
        vade_siniri = bugun + timedelta(days=7)

        with get_session() as session:
            bekleyen_talep = 0
            try:
                from database.models.satin_alma_talep import SatinAlmaTalep

                bekleyen_talep = int(
                    session.scalar(
                        select(func.count())
                        .select_from(SatinAlmaTalep)
                        .where(
                            SatinAlmaTalep.durum.in_(
                                ("TASLAK", "ONAY BEKLİYOR", "ONAYLANDI")
                            )
                        )
                    )
                    or 0
                )
            except Exception:
                bekleyen_talep = 0

            acik_siparis = int(
                session.scalar(
                    select(func.count())
                    .select_from(AlisSiparisi)
                    .where(
                        AlisSiparisi.durum.notin_(("İPTAL", "FATURALI", "İRSALİYELİ"))
                    )
                )
                or 0
            )

            geciken_siparis = int(
                session.scalar(
                    select(func.count())
                    .select_from(AlisSiparisi)
                    .where(
                        AlisSiparisi.durum.notin_(("İPTAL", "FATURALI", "İRSALİYELİ")),
                        AlisSiparisi.termin_tarihi < bugun,
                    )
                )
                or 0
            )

            # Faturalanmamış irsaliye: satırda faturalanan < miktar
            irsaliye_idler = set(
                session.scalars(
                    select(AlisIrsaliyesiSatiri.irsaliye_id)
                    .where(
                        AlisIrsaliyesiSatiri.faturalanan_miktar
                        < AlisIrsaliyesiSatiri.miktar
                    )
                    .distinct()
                ).all()
            )
            faturalanmamis_irsaliye = len(irsaliye_idler)

            # Bu ay alış tutarı
            bu_ay_tutar = session.scalar(
                select(func.coalesce(func.sum(AlisFaturasi.tl_genel_toplam), 0)).where(
                    AlisFaturasi.fatura_tarihi >= ay_basi,
                    AlisFaturasi.fatura_tarihi <= bugun,
                    AlisFaturasi.durum != "İPTAL",
                )
            )
            bu_ay_tutar = Decimal(str(bu_ay_tutar or 0))

            yaklasan_borc = int(
                session.scalar(
                    select(func.count())
                    .select_from(AlisFaturasi)
                    .where(
                        AlisFaturasi.vade_tarihi >= bugun,
                        AlisFaturasi.vade_tarihi <= vade_siniri,
                        AlisFaturasi.durum != "İPTAL",
                    )
                )
                or 0
            )

            # Açık sipariş satır kalan miktar (teslim bekleyen)
            kalan_satir = 0
            for satir in session.scalars(
                select(AlisSiparisiSatiri)
                .join(AlisSiparisi)
                .where(AlisSiparisi.durum.notin_(("İPTAL", "FATURALI", "İRSALİYELİ")))
            ).all():
                kalan = (satir.miktar or Decimal("0")) - (
                    satir.irsaliyelenen_miktar or Decimal("0")
                )
                if kalan > 0:
                    kalan_satir += 1

        return {
            "bekleyen_talep": bekleyen_talep,
            "acik_siparis": acik_siparis,
            "geciken_siparis": geciken_siparis,
            "faturalanmamis_irsaliye": faturalanmamis_irsaliye,
            "yaklasan_borc": yaklasan_borc,
            "bu_ay_alis": bu_ay_tutar,
            "teslim_bekleyen_satir": kalan_satir,
        }

    @staticmethod
    def aylik_alis_analizi(yil: int | None = None) -> list[dict]:
        """Seçilen yıl (varsayılan: bugün) için aylık alış tutarı / fatura sayısı."""
        from database.models.alis_faturasi import AlisFaturasiSatiri

        bugun = date.today()
        yil = int(yil or bugun.year)
        with get_session() as session:
            faturalar = list(
                session.scalars(
                    select(AlisFaturasi)
                    .options(selectinload(AlisFaturasi.cari))
                    .where(
                        AlisFaturasi.durum != "İPTAL",
                        AlisFaturasi.fatura_tarihi >= date(yil, 1, 1),
                        AlisFaturasi.fatura_tarihi <= date(yil, 12, 31),
                    )
                ).all()
            )
            aylar: dict[str, dict] = {}
            for f in faturalar:
                anahtar = f"{f.fatura_tarihi.year:04d}-{f.fatura_tarihi.month:02d}"
                kayit = aylar.setdefault(
                    anahtar,
                    {
                        "ay": anahtar,
                        "fatura_sayisi": 0,
                        "tutar": Decimal("0"),
                        "tedarikci_sayisi": set(),
                    },
                )
                kayit["fatura_sayisi"] += 1
                kayit["tutar"] += Decimal(str(f.tl_genel_toplam or 0))
                if f.cari_id:
                    kayit["tedarikci_sayisi"].add(f.cari_id)

            # Satır miktar toplamı (adet)
            satirlar = list(
                session.scalars(
                    select(AlisFaturasiSatiri)
                    .options(selectinload(AlisFaturasiSatiri.fatura))
                    .join(AlisFaturasi)
                    .where(
                        AlisFaturasi.durum != "İPTAL",
                        AlisFaturasi.fatura_tarihi >= date(yil, 1, 1),
                        AlisFaturasi.fatura_tarihi <= date(yil, 12, 31),
                    )
                ).all()
            )
            miktar_ay: dict[str, Decimal] = {}
            for s in satirlar:
                f = s.fatura
                if f is None:
                    continue
                anahtar = f"{f.fatura_tarihi.year:04d}-{f.fatura_tarihi.month:02d}"
                miktar_ay[anahtar] = miktar_ay.get(anahtar, Decimal("0")) + Decimal(
                    str(s.miktar or 0)
                )

            sonuc = []
            for anahtar in sorted(aylar.keys()):
                k = aylar[anahtar]
                sonuc.append(
                    {
                        "ay": anahtar,
                        "fatura_sayisi": k["fatura_sayisi"],
                        "tutar": k["tutar"],
                        "tedarikci_sayisi": len(k["tedarikci_sayisi"]),
                        "miktar": miktar_ay.get(anahtar, Decimal("0")),
                    }
                )
            return sonuc

    @staticmethod
    def stok_yenileme_onerileri() -> list[dict]:
        """minimum_stok > mevcut olan aktif kartlar için sipariş önerisi."""
        from database.models.stok import StokKarti, StokLotu

        with get_session() as session:
            kartlar = list(
                session.scalars(
                    select(StokKarti).where(
                        StokKarti.aktif.is_(True),
                        StokKarti.is_deleted.is_(False),
                    )
                ).all()
            )
            oneriler = []
            for stok in kartlar:
                min_stok = Decimal(str(getattr(stok, "minimum_stok", 0) or 0))
                if min_stok <= 0:
                    continue
                mevcut = session.scalar(
                    select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                        StokLotu.stok_id == stok.id
                    )
                )
                mevcut_d = Decimal(str(mevcut or 0))
                if mevcut_d >= min_stok:
                    continue
                oneriler.append(
                    {
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "birim": stok.birim,
                        "mevcut": mevcut_d,
                        "minimum_stok": min_stok,
                        "onerilen_miktar": (min_stok - mevcut_d).quantize(
                            Decimal("0.0001")
                        ),
                    }
                )
            oneriler.sort(key=lambda x: x["onerilen_miktar"], reverse=True)
            return oneriler
