"""TL işlemlerinin döviz bazında raporlanması."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.doviz_service import DovizService
from database.models.satis_faturasi import SatisFaturasi
from database.satis_faturasi_service import SatisFaturasiService

KURUS = Decimal("0.01")


class DovizRaporService:
    @staticmethod
    def _kur_al(
        yontem: str,
        para_birimi: str,
        islem_tarihi: date,
        tahsilat_tarihi: date | None,
        rapor_tarihi: date,
        sabit_kur: Decimal | None,
        fatura_kuru: Decimal | None = None,
    ) -> Decimal:
        code = (para_birimi or "USD").upper()
        if code == "TRY":
            return Decimal("1")
        if yontem == "sabit_kur":
            if not sabit_kur or sabit_kur <= 0:
                raise ValueError("Sabit kur yöntemi için geçerli bir kur girin.")
            return Decimal(str(sabit_kur))
        if yontem == "islem_tarihi":
            if fatura_kuru and fatura_kuru > 0:
                return Decimal(str(fatura_kuru))
            tarih = islem_tarihi
        elif yontem == "tahsilat_tarihi":
            tarih = tahsilat_tarihi or islem_tarihi
        else:
            tarih = rapor_tarihi
        return DovizService.kur_degeri(tarih, code)

    @staticmethod
    def satis_fatura_doviz_raporu(
        baslangic: date | None = None,
        bitis: date | None = None,
        rapor_para_birimi: str = "USD",
        kur_yontemi: str = "islem_tarihi",
        rapor_tarihi: date | None = None,
        sabit_kur: Decimal | None = None,
    ) -> list[dict[str, Any]]:
        """Onaylı satış faturalarını seçilen döviz cinsinden raporlar."""
        rapor_tarihi = rapor_tarihi or date.today()
        rapor_pb = (rapor_para_birimi or "USD").upper()
        satirlar: list[dict[str, Any]] = []

        with get_session() as session:
            stmt = (
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL", SatisFaturasi.onaylandi.is_(True))
                .options(selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.satirlar))
                .order_by(SatisFaturasi.fatura_tarihi.desc())
            )
            if baslangic:
                stmt = stmt.where(SatisFaturasi.fatura_tarihi >= baslangic)
            if bitis:
                stmt = stmt.where(SatisFaturasi.fatura_tarihi <= bitis)
            faturalar = list(session.scalars(stmt).all())

        for fatura in faturalar:
            toplam = SatisFaturasiService.toplam(fatura.satirlar)
            tl_matrah = Decimal(str(getattr(fatura, "tl_matrah", 0) or 0))
            if tl_matrah <= 0:
                tl_matrah = toplam["ara_toplam"] - toplam["iskonto"]
            tl_kdv = Decimal(str(getattr(fatura, "tl_kdv", 0) or 0)) or toplam["kdv"]
            tl_genel = Decimal(str(getattr(fatura, "tl_genel_toplam", 0) or 0)) or toplam["genel_toplam"]

            fatura_pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
            fatura_kuru = Decimal(str(getattr(fatura, "kur", 1) or 1))
            doviz_ara = Decimal(str(getattr(fatura, "doviz_ara_toplam", 0) or 0))

            try:
                rapor_kuru = DovizRaporService._kur_al(
                    kur_yontemi,
                    rapor_pb,
                    fatura.fatura_tarihi,
                    fatura.fatura_tarihi,
                    rapor_tarihi,
                    sabit_kur,
                    fatura_kuru if fatura_pb != "TRY" else None,
                )
            except ValueError:
                rapor_kuru = None

            if rapor_kuru and rapor_kuru > 0:
                doviz_matrah = DovizService.tl_den_dovize(tl_matrah, rapor_kuru)
                doviz_kdv = DovizService.tl_den_dovize(tl_kdv, rapor_kuru)
                doviz_genel = DovizService.tl_den_dovize(tl_genel, rapor_kuru)
            else:
                doviz_matrah = doviz_kdv = doviz_genel = None

            cari = fatura.cari
            satirlar.append(
                {
                    "fatura_no": fatura.fatura_no,
                    "fatura_tarihi": fatura.fatura_tarihi,
                    "cari_kodu": cari.cari_kodu if cari else "",
                    "unvan": cari.unvan if cari else "",
                    "fatura_para_birimi": fatura_pb,
                    "fatura_kuru": fatura_kuru,
                    "doviz_ara_toplam": doviz_ara,
                    "tl_matrah": tl_matrah.quantize(KURUS, rounding=ROUND_HALF_UP),
                    "tl_kdv": tl_kdv.quantize(KURUS, rounding=ROUND_HALF_UP),
                    "tl_genel_toplam": tl_genel.quantize(KURUS, rounding=ROUND_HALF_UP),
                    "rapor_para_birimi": rapor_pb,
                    "rapor_kuru": rapor_kuru,
                    "rapor_kur_yontemi": kur_yontemi,
                    "doviz_matrah": doviz_matrah,
                    "doviz_kdv": doviz_kdv,
                    "doviz_genel_toplam": doviz_genel,
                    "borc_esasi": getattr(fatura, "borc_esasi", "TL_SABIT") or "TL_SABIT",
                }
            )
        return satirlar

    @staticmethod
    def cari_doviz_bakiye_ozeti(cari_id: int) -> dict[str, Any]:
        """Cari açık bakiyesinin TL ve döviz karşılıkları."""
        from database.satis_faturasi_service import SatisFaturasiService

        ozet = SatisFaturasiService.bakiye_ozeti(cari_id)
        tl_bakiye = Decimal(str(ozet.get("bakiye") or 0))
        bugun = date.today()
        sonuc: dict[str, Decimal | None] = {"tl_bakiye": tl_bakiye}
        for pb in ("USD", "EUR"):
            try:
                kur = DovizService.kur_degeri(bugun, pb)
                sonuc[f"{pb.lower()}_bakiye"] = DovizService.tl_den_dovize(tl_bakiye, kur)
            except ValueError:
                sonuc[f"{pb.lower()}_bakiye"] = None
        return sonuc
