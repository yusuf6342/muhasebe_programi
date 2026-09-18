"""Alış fatura ek masraf kayıt ve satırlara dağıtım."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.alis_faturasi import AlisFaturasi
from database.models.alis_masraf import AlisMasraf, AlisMasrafDagitim
from database.satis_siparisi_service import decimal
from database.satin_alma_hub_service import SatinAlmaHubService

MASRAF_TURLERI = (
    "NAKLİYE",
    "HAMALİYE",
    "SİGORTA",
    "GÜMRÜK",
    "BANKA",
    "KUR FARKI",
    "DİĞER",
)
YONTEMLER = ("TUTAR", "MIKTAR", "MANUEL")


class AlisMasrafService:
    @staticmethod
    def schema_hazirla() -> None:
        SatinAlmaHubService.schema_hazirla()

    @staticmethod
    def fatura_liste_ozet() -> list[dict[str, Any]]:
        """Masraf eklenebilecek faturalar."""
        AlisMasrafService.schema_hazirla()
        with get_session() as session:
            faturalar = list(
                session.scalars(
                    select(AlisFaturasi)
                    .options(selectinload(AlisFaturasi.cari))
                    .where(AlisFaturasi.durum != "İPTAL")
                    .order_by(AlisFaturasi.id.desc())
                    .limit(200)
                ).all()
            )
            sonuc = []
            for f in faturalar:
                masraf_toplam = session.scalar(
                    select(func.coalesce(func.sum(AlisMasraf.tutar), 0)).where(
                        AlisMasraf.fatura_id == f.id
                    )
                )
                sonuc.append(
                    {
                        "id": f.id,
                        "fatura_no": f.fatura_no,
                        "tarih": f.fatura_tarihi,
                        "tedarikci": f.cari.unvan if f.cari else "",
                        "genel_toplam": f.tl_genel_toplam,
                        "masraf_toplam": Decimal(str(masraf_toplam or 0)),
                    }
                )
            return sonuc

    @staticmethod
    def masraflari(fatura_id: int) -> list[dict[str, Any]]:
        AlisMasrafService.schema_hazirla()
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(AlisMasraf)
                    .options(selectinload(AlisMasraf.dagitimlar))
                    .where(AlisMasraf.fatura_id == int(fatura_id))
                    .order_by(AlisMasraf.id)
                ).all()
            )
            return [
                {
                    "id": m.id,
                    "masraf_turu": m.masraf_turu,
                    "tutar": m.tutar,
                    "dagitim_yontemi": m.dagitim_yontemi,
                    "maliyete_dahil": m.maliyete_dahil,
                    "aciklama": m.aciklama or "",
                    "dagitim_adet": len(m.dagitimlar or []),
                    "dagitim_toplam": sum(
                        (d.tutar for d in (m.dagitimlar or [])), Decimal("0")
                    ),
                }
                for m in kayitlar
            ]

    @staticmethod
    def kaydet_ve_dagit(
        fatura_id: int,
        masraf_turu: str,
        tutar,
        yontem: str = "TUTAR",
        maliyete_dahil: bool = True,
        aciklama: str | None = None,
        manuel_dagitim: dict[int, Decimal] | None = None,
    ) -> int:
        yazma_zorunlu("alis_masraf_duzenleme", "alis_duzenleme", "yeni_kayit")
        AlisMasrafService.schema_hazirla()
        tutar_d = decimal(tutar, "Masraf tutarı", Decimal("0.01"))
        yontem = (yontem or "TUTAR").upper()
        if yontem not in YONTEMLER:
            raise ValueError("Geçersiz dağıtım yöntemi.")

        with get_session() as session:
            fatura = session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar))
                .where(AlisFaturasi.id == int(fatura_id))
            )
            if fatura is None:
                raise ValueError("Fatura bulunamadı.")
            satirlar = list(fatura.satirlar or [])
            if not satirlar:
                raise ValueError("Faturada satır yok; masraf dağıtılamaz.")

            masraf = AlisMasraf(
                fatura_id=fatura.id,
                masraf_turu=(masraf_turu or "DİĞER").strip().upper(),
                tutar=tutar_d,
                dagitim_yontemi=yontem,
                maliyete_dahil=bool(maliyete_dahil),
                aciklama=aciklama,
            )
            session.add(masraf)
            session.flush()

            if yontem == "MANUEL" and manuel_dagitim:
                toplam = sum(manuel_dagitim.values(), Decimal("0"))
                if abs(toplam - tutar_d) > Decimal("0.05"):
                    raise ValueError(
                        f"Manuel dağıtım toplamı ({toplam}) masraf tutarına ({tutar_d}) eşit olmalı."
                    )
                for satir_id, pay in manuel_dagitim.items():
                    masraf.dagitimlar.append(
                        AlisMasrafDagitim(
                            fatura_satiri_id=int(satir_id),
                            tutar=pay,
                            oran=(pay / tutar_d) if tutar_d else Decimal("0"),
                        )
                    )
            else:
                if yontem == "MIKTAR":
                    agirliklar = [s.miktar or Decimal("0") for s in satirlar]
                else:
                    agirliklar = [
                        (s.miktar or Decimal("0")) * (s.birim_fiyat or Decimal("0"))
                        for s in satirlar
                    ]
                toplam_agirlik = sum(agirliklar, Decimal("0"))
                if toplam_agirlik <= 0:
                    agirliklar = [Decimal("1")] * len(satirlar)
                    toplam_agirlik = Decimal(len(satirlar))

                dagitilan = Decimal("0")
                for i, satir in enumerate(satirlar):
                    if i == len(satirlar) - 1:
                        pay = tutar_d - dagitilan  # kuruş farkı son satıra
                    else:
                        pay = (tutar_d * agirliklar[i] / toplam_agirlik).quantize(
                            Decimal("0.0001")
                        )
                        dagitilan += pay
                    masraf.dagitimlar.append(
                        AlisMasrafDagitim(
                            fatura_satiri_id=satir.id,
                            tutar=pay,
                            oran=(agirliklar[i] / toplam_agirlik)
                            if toplam_agirlik
                            else Decimal("0"),
                        )
                    )

            session.flush()
            kontrol = sum((d.tutar for d in masraf.dagitimlar), Decimal("0"))
            if abs(kontrol - tutar_d) > Decimal("0.01"):
                raise ValueError(
                    f"Dağıtım toplamı ({kontrol}) masraf tutarına ({tutar_d}) eşit değil."
                )
            if masraf.maliyete_dahil:
                AlisMasrafService._fifo_lot_maliyetine_yansit(session, fatura, masraf, yon=1)
            return int(masraf.id)

    @staticmethod
    def _fifo_lot_maliyetine_yansit(session, fatura: AlisFaturasi, masraf: AlisMasraf, yon: int = 1) -> None:
        """Dağıtılan masraf payını ilgili FIFO lot ve hareket birim maliyetine ekler/çıkarır."""
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.stok import StokHareketi, StokKarti, StokLotu

        isaret = Decimal(1 if yon >= 0 else -1)
        for dag in masraf.dagitimlar or []:
            satir = session.get(AlisFaturasiSatiri, int(dag.fatura_satiri_id))
            if satir is None or not satir.lot_girisi:
                continue
            miktar = Decimal(str(satir.miktar or 0))
            if miktar <= 0:
                continue
            ek_birim = (Decimal(str(dag.tutar or 0)) / miktar * isaret).quantize(Decimal("0.0001"))
            stok = session.scalar(
                select(StokKarti).where(StokKarti.stok_kodu == satir.urun_kodu)
            )
            if stok is None:
                continue
            lot = session.scalar(
                select(StokLotu).where(
                    StokLotu.stok_id == stok.id,
                    StokLotu.lot_no == satir.lot_girisi,
                )
            )
            if lot is None:
                continue
            yeni = (Decimal(str(lot.birim_maliyet or 0)) + ek_birim).quantize(Decimal("0.0001"))
            if yeni < 0:
                yeni = Decimal("0")
            lot.birim_maliyet = yeni
            satir.fifo_birim_maliyeti = yeni
            hareket = session.scalar(
                select(StokHareketi).where(
                    StokHareketi.lot_id == lot.id,
                    StokHareketi.belge_no == fatura.fatura_no,
                    StokHareketi.hareket_turu == "FATURA GİRİŞ",
                )
            )
            if hareket is not None:
                hareket.birim_maliyet = yeni

    @staticmethod
    def sil(masraf_id: int) -> None:
        yazma_zorunlu("alis_masraf_duzenleme", "alis_duzenleme")
        with get_session() as session:
            masraf = session.scalar(
                select(AlisMasraf)
                .options(
                    selectinload(AlisMasraf.dagitimlar),
                    selectinload(AlisMasraf.fatura),
                )
                .where(AlisMasraf.id == int(masraf_id))
            )
            if masraf is None:
                raise ValueError("Masraf bulunamadı.")
            if masraf.maliyete_dahil and masraf.fatura is not None:
                AlisMasrafService._fifo_lot_maliyetine_yansit(
                    session, masraf.fatura, masraf, yon=-1
                )
            session.delete(masraf)
