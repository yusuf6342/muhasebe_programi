"""Stoklar hub özet metrikleri — lot ve hareket tablolarından."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select

from database.database import get_session
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI


class StokHubService:
    @staticmethod
    def ozet_kartlar() -> dict:
        bugun = date.today()
        hareketsiz_sinir = bugun - timedelta(days=90)

        with get_session() as session:
            # Lot bazlı miktar / maliyet
            lot_satirlar = list(
                session.execute(
                    select(
                        StokLotu.stok_id,
                        func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                        func.coalesce(
                            func.sum(StokLotu.kalan_miktar * StokLotu.birim_maliyet), 0
                        ),
                    ).group_by(StokLotu.stok_id)
                ).all()
            )
            miktar_map = {int(r[0]): Decimal(str(r[1] or 0)) for r in lot_satirlar}
            maliyet_map = {int(r[0]): Decimal(str(r[2] or 0)) for r in lot_satirlar}
            toplam_maliyet = sum(maliyet_map.values(), Decimal("0"))

            aktif_stok_idler = set(
                session.scalars(
                    select(StokKarti.id).where(
                        StokKarti.aktif.is_(True),
                        or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                    )
                ).all()
            )

            eksi = 0
            sifir_kritik = 0
            for sid in aktif_stok_idler:
                m = miktar_map.get(int(sid), Decimal("0"))
                if m < 0:
                    eksi += 1
                elif m == 0:
                    sifir_kritik += 1

            # Bugün giriş / çıkış
            bugun_giris = session.scalar(
                select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                    StokHareketi.tarih == bugun,
                    StokHareketi.hareket_turu.in_(GIRIS_HAREKETLERI),
                )
            )
            bugun_cikis = session.scalar(
                select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                    StokHareketi.tarih == bugun,
                    StokHareketi.hareket_turu.in_(CIKIS_HAREKETLERI),
                )
            )

            # Hareketsiz: son 90 günde hareketi olmayan ve miktarı > 0
            son_hareket = {
                int(r[0]): r[1]
                for r in session.execute(
                    select(StokHareketi.stok_id, func.max(StokHareketi.tarih)).group_by(
                        StokHareketi.stok_id
                    )
                ).all()
            }
            hareketsiz = 0
            for sid in aktif_stok_idler:
                m = miktar_map.get(int(sid), Decimal("0"))
                if m <= 0:
                    continue
                son = son_hareket.get(int(sid))
                if son is None or son < hareketsiz_sinir:
                    hareketsiz += 1

            depo_adet = int(
                session.scalar(select(func.count()).select_from(Depo).where(Depo.aktif.is_(True)))
                or 0
            )
            aktif_kart = len(aktif_stok_idler)

            # Sayım farkı / aktarım hatası — henüz ayrı sayım tablosu yoksa 0
            sayim_farki = 0
            try:
                from database.models.stok_sayim import StokSayimFisi

                sayim_farki = int(
                    session.scalar(
                        select(func.count())
                        .select_from(StokSayimFisi)
                        .where(StokSayimFisi.durum == "FARK VAR")
                    )
                    or 0
                )
            except Exception:
                sayim_farki = 0

        return {
            "toplam_maliyet": toplam_maliyet,
            "kritik_stok": sifir_kritik,
            "eksi_stok": eksi,
            "hareketsiz_stok": hareketsiz,
            "bugun_giris": Decimal(str(bugun_giris or 0)),
            "bugun_cikis": Decimal(str(bugun_cikis or 0)),
            "sayim_farki": sayim_farki,
            "depo_adet": depo_adet,
            "aktif_kart": aktif_kart,
        }
