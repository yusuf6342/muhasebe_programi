"""Stok sayım fişi servisi — sistem/sayılan farkını GİRİŞ/ÇIKIŞ hareketiyle düzeltir."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import Base, company_db, get_session
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.models.stok_sayim import StokSayimFisi, StokSayimSatiri
from database.satis_siparisi_service import decimal


class StokSayimService:
    @staticmethod
    def schema_hazirla() -> None:
        import database.models.stok_sayim  # noqa: F401

        if company_db.engine is None:
            return
        Base.metadata.create_all(company_db.engine)

    @staticmethod
    def fis_no() -> str:
        StokSayimService.schema_hazirla()
        onek = "SYM"
        with get_session() as session:
            son = session.scalar(
                select(StokSayimFisi.fis_no)
                .where(StokSayimFisi.fis_no.like(f"{onek}%"))
                .order_by(StokSayimFisi.fis_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek) :]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        StokSayimService.schema_hazirla()
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(StokSayimFisi)
                    .options(
                        selectinload(StokSayimFisi.depo),
                        selectinload(StokSayimFisi.satirlar),
                    )
                    .order_by(StokSayimFisi.id.desc())
                ).all()
            )
            return [
                {
                    "id": f.id,
                    "fis_no": f.fis_no,
                    "tarih": f.fis_tarihi,
                    "depo": f.depo.ad if f.depo else "",
                    "durum": f.durum,
                    "satir": len(f.satirlar or []),
                    "aciklama": f.aciklama or "",
                }
                for f in kayitlar
            ]

    @staticmethod
    def depo_stok_listesi(depo_id: int) -> list[dict[str, Any]]:
        """Depodaki stoklar ve sistem miktarları."""
        with get_session() as session:
            satirlar = list(
                session.execute(
                    select(
                        StokLotu.stok_id,
                        func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                    )
                    .where(StokLotu.depo_id == int(depo_id))
                    .group_by(StokLotu.stok_id)
                ).all()
            )
            sonuc = []
            for stok_id, miktar in satirlar:
                stok = session.get(StokKarti, int(stok_id))
                if not stok or not stok.aktif or getattr(stok, "is_deleted", False):
                    continue
                sonuc.append(
                    {
                        "stok_id": int(stok_id),
                        "urun_kodu": stok.stok_kodu,
                        "urun_adi": stok.stok_adi,
                        "birim": stok.birim,
                        "sistem_miktar": Decimal(str(miktar or 0)),
                    }
                )
            sonuc.sort(key=lambda x: x["urun_kodu"])
            return sonuc

    @staticmethod
    def kaydet_ve_onayla(
        depo_id: int,
        fis_tarihi: date,
        satirlar: list[dict[str, Any]],
        aciklama: str | None = None,
    ) -> int:
        """
        Sayım satırlarını kaydeder ve farkları tek transaction içinde stoğa yansıtır.
        Pozitif fark → SAYIM GİRİŞ, negatif → SAYIM ÇIKIŞ (FIFO).
        """
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        StokSayimService.schema_hazirla()
        if not satirlar:
            raise ValueError("Sayım satırı yok.")

        with get_session() as session:
            depo = session.get(Depo, int(depo_id))
            if not depo:
                raise ValueError("Depo bulunamadı.")

            fis = StokSayimFisi(
                fis_no=StokSayimService.fis_no(),
                fis_tarihi=fis_tarihi,
                depo_id=depo.id,
                durum="TASLAK",
                aciklama=aciklama,
            )
            session.add(fis)
            session.flush()

            fark_var = False
            for veri in satirlar:
                sistem = decimal(veri.get("sistem_miktar", 0), "Sistem", Decimal("0"))
                sayilan = decimal(veri["sayilan_miktar"], "Sayılan", Decimal("0"))
                fark = sayilan - sistem
                if fark != 0:
                    fark_var = True
                fis.satirlar.append(
                    StokSayimSatiri(
                        stok_id=int(veri["stok_id"]),
                        sistem_miktar=sistem,
                        sayilan_miktar=sayilan,
                        fark=fark,
                        fark_nedeni=veri.get("fark_nedeni"),
                    )
                )
            session.flush()

            # Stok düzeltmeleri
            for satir in fis.satirlar:
                if satir.fark == 0:
                    continue
                stok = session.get(StokKarti, satir.stok_id)
                if not stok:
                    raise ValueError("Stok kartı bulunamadı.")
                if satir.fark > 0:
                    # Giriş
                    lot = StokLotu(
                        stok_id=stok.id,
                        depo_id=depo.id,
                        lot_no=f"SAYIM-{fis.fis_no}-{stok.id}",
                        tedarikci="SAYIM",
                        giris_tarihi=fis_tarihi,
                        kalan_miktar=satir.fark,
                        birim_maliyet=Decimal("0"),
                    )
                    session.add(lot)
                    session.flush()
                    session.add(
                        StokHareketi(
                            tarih=fis_tarihi,
                            hareket_turu="SAYIM GİRİŞ",
                            belge_no=fis.fis_no,
                            stok_id=stok.id,
                            depo_id=depo.id,
                            lot_id=lot.id,
                            miktar=satir.fark,
                            birim_maliyet=Decimal("0"),
                        )
                    )
                else:
                    # FIFO çıkış
                    gereken = abs(satir.fark)
                    lotlar = list(
                        session.scalars(
                            select(StokLotu)
                            .where(
                                StokLotu.stok_id == stok.id,
                                StokLotu.depo_id == depo.id,
                                StokLotu.kalan_miktar > 0,
                            )
                            .order_by(StokLotu.giris_tarihi, StokLotu.id)
                        ).all()
                    )
                    mevcut = sum((l.kalan_miktar for l in lotlar), Decimal("0"))
                    if mevcut < gereken:
                        raise ValueError(
                            f"{stok.stok_kodu}: sayım çıkışı için stok yetersiz "
                            f"(mevcut {mevcut}, fark {gereken})."
                        )
                    kalan = gereken
                    for lot in lotlar:
                        if kalan <= 0:
                            break
                        cikan = min(kalan, lot.kalan_miktar)
                        lot.kalan_miktar -= cikan
                        kalan -= cikan
                        session.add(
                            StokHareketi(
                                tarih=fis_tarihi,
                                hareket_turu="SAYIM ÇIKIŞ",
                                belge_no=fis.fis_no,
                                stok_id=stok.id,
                                depo_id=depo.id,
                                lot_id=lot.id,
                                miktar=cikan,
                                birim_maliyet=lot.birim_maliyet,
                            )
                        )

            fis.durum = "FARK VAR" if fark_var else "TAMAM"
            session.flush()
            return int(fis.id)
