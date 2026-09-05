from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.finans import FinansHareketi
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
from database.alis_faturasi_service import AlisFaturasiService
from database.satis_siparisi_service import decimal
from database.stok_service import StokService


class AlisIadeFaturasiService:
    @staticmethod
    def aktif_tedarikcileri():
        from database.alis_siparisi_service import AlisSiparisiService
        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def iade_no() -> str:
        return f"AIAD-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            kayitlar = session.scalars(
                select(AlisIadeFaturasi)
                .options(
                    selectinload(AlisIadeFaturasi.cari),
                    selectinload(AlisIadeFaturasi.kaynak_fatura),
                    selectinload(AlisIadeFaturasi.satirlar),
                )
                .order_by(AlisIadeFaturasi.id.desc())
            ).all()
            return [{"iade": i, **AlisIadeFaturasiService.toplam(i.satirlar)} for i in kayitlar]

    @staticmethod
    def getir(iade_id: int) -> AlisIadeFaturasi | None:
        with get_session() as session:
            return session.scalar(
                select(AlisIadeFaturasi)
                .options(
                    selectinload(AlisIadeFaturasi.cari),
                    selectinload(AlisIadeFaturasi.kaynak_fatura),
                    selectinload(AlisIadeFaturasi.satirlar),
                )
                .where(AlisIadeFaturasi.id == iade_id)
            )

    @staticmethod
    def tedarikci_urun_gecmisi(cari_id: int, urun_kodu: str) -> dict[str, Any]:
        """Tedarikçiden bu ürünün daha önce alınıp alınmadığını ve kaçtan alındığını döner."""
        urun_kodu = (urun_kodu or "").strip()
        with get_session() as session:
            satirlar = session.scalars(
                select(AlisFaturasiSatiri)
                .join(AlisFaturasi)
                .where(
                    AlisFaturasi.cari_id == cari_id,
                    AlisFaturasi.durum != "İPTAL",
                    AlisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(selectinload(AlisFaturasiSatiri.fatura))
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasiSatiri.id.desc())
            ).all()
            gecmis = []
            for satir in satirlar:
                indirim = satir.birim_fiyat * satir.iskonto_orani / Decimal("100")
                net_fiyat = satir.birim_fiyat - indirim
                gecmis.append({
                    "fatura_no": satir.fatura.fatura_no,
                    "tarih": satir.fatura.fatura_tarihi,
                    "miktar": satir.miktar,
                    "birim": satir.birim,
                    "birim_fiyat": satir.birim_fiyat,
                    "iskonto_orani": satir.iskonto_orani,
                    "net_fiyat": net_fiyat,
                    "fifo_birim_maliyeti": satir.fifo_birim_maliyeti,
                    "satir_id": satir.id,
                })
            aldi = bool(gecmis)
            son_fiyat = gecmis[0]["net_fiyat"] if gecmis else None
            ortalama = (
                sum((g["net_fiyat"] for g in gecmis), Decimal("0")) / Decimal(len(gecmis))
                if gecmis else None
            )
            return {
                "aldi": aldi,
                "adet": len(gecmis),
                "son_fiyat": son_fiyat,
                "ortalama_fiyat": ortalama,
                "gecmis": gecmis,
            }

    @staticmethod
    def tedarikci_alislari(cari_id: int) -> list[AlisFaturasi]:
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisFaturasi)
                    .where(AlisFaturasi.cari_id == cari_id, AlisFaturasi.durum != "İPTAL")
                    .options(selectinload(AlisFaturasi.satirlar), selectinload(AlisFaturasi.cari))
                    .order_by(AlisFaturasi.fatura_tarihi.desc())
                ).all()
            )

    @staticmethod
    def kaydet(veriler, satir_verileri, iade_id=None):
        tarih = veriler["iade_tarihi"]
        if tarih > date.today():
            raise ValueError("İade tarihi gelecek bir tarih olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir iade satırı ekleyin.")
        with get_session() as session:
            if iade_id:
                iade = session.get(AlisIadeFaturasi, iade_id)
                if not iade:
                    raise ValueError("İade faturası bulunamadı.")
                if iade.durum == "İPTAL":
                    raise ValueError("İptal edilmiş iade düzenlenemez.")
                StokService.fatura_cikislarini_geri_al(session, iade.iade_no)
                session.execute(delete(FinansHareketi).where(FinansHareketi.belge_no == iade.iade_no))
                session.execute(delete(CariIslem).where(CariIslem.belge_no == iade.iade_no))
                session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == iade.iade_no))
                iade.satirlar.clear()
            else:
                iade = AlisIadeFaturasi(iade_no=AlisIadeFaturasiService.iade_no())
                session.add(iade)

            iade.iade_tarihi = tarih
            iade.cari_id = int(veriler["cari_id"])
            iade.kaynak_fatura_id = veriler.get("kaynak_fatura_id")
            iade.depo = veriler.get("depo") or "ANA DEPO"
            iade.aciklama = veriler.get("aciklama")
            iade.iade_odeme_tutari = decimal(veriler.get("iade_odeme_tutari", 0), "İade ödeme", Decimal("0"))
            iade.iade_odeme_sekli = veriler.get("iade_odeme_sekli")
            iade.iade_odeme_hesabi = veriler.get("iade_odeme_hesabi")

            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                onceki = veri.get("onceki_alis_fiyati")
                kaynak_id = veri.get("kaynak_fatura_satiri_id")
                kaynak_satiri = session.get(AlisFaturasiSatiri, int(kaynak_id)) if kaynak_id else None
                tercih_lot = ""
                if kaynak_satiri and kaynak_satiri.lot_girisi:
                    tercih_lot = kaynak_satiri.lot_girisi.split(":")[0].strip()
                if veri.get("lot_no"):
                    tercih_lot = str(veri["lot_no"]).strip()

                stok_cikisi = StokService.fatura_cikisi(
                    session,
                    iade.iade_no,
                    tarih,
                    veri["urun_kodu"].strip(),
                    iade.depo,
                    miktar,
                    tercih_lot,
                )
                fifo = stok_cikisi["fifo_birim_maliyeti"]
                if kaynak_satiri is not None and kaynak_satiri.fifo_birim_maliyeti is not None:
                    fifo = Decimal(kaynak_satiri.fifo_birim_maliyeti)

                iade.satirlar.append(
                    AlisIadeFaturasiSatiri(
                        kaynak_fatura_satiri_id=kaynak_id or (kaynak_satiri.id if kaynak_satiri else None),
                        urun_kodu=veri["urun_kodu"].strip(),
                        urun_adi=veri["urun_adi"].strip(),
                        miktar=miktar,
                        birim=veri.get("birim") or "Adet",
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")),
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        onceki_alis_fiyati=(
                            decimal(onceki, "Önceki alış", Decimal("0"))
                            if onceki not in (None, "") else None
                        ),
                        onceki_fatura_no=veri.get("onceki_fatura_no") or None,
                        fifo_birim_maliyeti=fifo,
                        lot_no=veri.get("lot_no") or None,
                        lot_cikisi=stok_cikisi["lot_cikisi"],
                    )
                )

            toplam = AlisIadeFaturasiService.toplam(iade.satirlar)["genel_toplam"]
            if iade.iade_odeme_tutari > toplam:
                raise ValueError("İade ödeme tutarı iade toplamından büyük olamaz.")
            iade.durum = "KAPALI" if iade.iade_odeme_tutari >= toplam else "AÇIK"
            session.flush()

            # Cari: alış iadesi tedarikçiye olan borcu azaltır (alacak + açık bakiyeden düşüş)
            session.add(CariIslem(
                cari_id=iade.cari_id,
                tarih=tarih,
                islem_turu="Alış İadesi",
                belge_no=iade.iade_no,
                aciklama=iade.aciklama or "Alış iade faturası",
                borc=Decimal("0"),
                alacak=toplam,
                hesap_adi=iade.iade_odeme_hesabi,
            ))
            CariService._aciklara_uygula(session, iade.cari_id, toplam)
            if iade.iade_odeme_tutari > 0:
                FinansService.hareket_ekle(
                    session,
                    iade.iade_no,
                    tarih,
                    iade.iade_odeme_tutari,
                    "ALIŞ İADE TAHSİLATI",
                    iade.iade_odeme_hesabi,
                    iade.iade_odeme_sekli,
                )

            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("İade faturası kaydedilemedi.") from hata
            return iade

    @staticmethod
    def iptal_et(iade_id: int) -> None:
        with get_session() as session:
            iade = session.scalar(
                select(AlisIadeFaturasi)
                .options(selectinload(AlisIadeFaturasi.satirlar))
                .where(AlisIadeFaturasi.id == iade_id)
            )
            if not iade:
                raise ValueError("İade faturası bulunamadı.")
            if iade.durum == "İPTAL":
                return
            StokService.fatura_cikislarini_geri_al(session, iade.iade_no)
            session.execute(delete(FinansHareketi).where(FinansHareketi.belge_no == iade.iade_no))
            session.execute(delete(CariIslem).where(CariIslem.belge_no == iade.iade_no))
            session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == iade.iade_no))
            iade.durum = "İPTAL"

    @staticmethod
    def toplam(satirlar) -> dict[str, Decimal]:
        return AlisFaturasiService.toplam(
            [
                {
                    "miktar": getattr(s, "miktar", s.get("miktar") if isinstance(s, dict) else 0),
                    "birim_fiyat": getattr(s, "birim_fiyat", s.get("birim_fiyat") if isinstance(s, dict) else 0),
                    "iskonto_orani": getattr(
                        s, "iskonto_orani", s.get("iskonto_orani", 0) if isinstance(s, dict) else 0
                    ),
                    "kdv_orani": getattr(
                        s, "kdv_orani", s.get("kdv_orani", 20) if isinstance(s, dict) else 20
                    ),
                }
                for s in satirlar
            ]
        )
