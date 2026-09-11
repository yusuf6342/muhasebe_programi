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
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_siparisi_service import decimal


class SatisIadeFaturasiService:
    @staticmethod
    def aktif_musterileri():
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def iade_no() -> str:
        return f"IAD-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            kayitlar = session.scalars(
                select(SatisIadeFaturasi)
                .options(
                    selectinload(SatisIadeFaturasi.cari),
                    selectinload(SatisIadeFaturasi.kaynak_fatura),
                    selectinload(SatisIadeFaturasi.satirlar),
                )
                .order_by(SatisIadeFaturasi.id.desc())
            ).all()
            return [{"iade": i, **SatisIadeFaturasiService.toplam(i.satirlar)} for i in kayitlar]

    @staticmethod
    def getir(iade_id: int) -> SatisIadeFaturasi | None:
        with get_session() as session:
            return session.scalar(
                select(SatisIadeFaturasi)
                .options(
                    selectinload(SatisIadeFaturasi.cari),
                    selectinload(SatisIadeFaturasi.kaynak_fatura),
                    selectinload(SatisIadeFaturasi.satirlar),
                )
                .where(SatisIadeFaturasi.id == iade_id)
            )

    @staticmethod
    def musteri_urun_gecmisi(cari_id: int, urun_kodu: str) -> dict[str, Any]:
        """Müşterinin bu ürünü daha önce alıp almadığını ve kaçtan aldığını döner."""
        urun_kodu = (urun_kodu or "").strip()
        with get_session() as session:
            satirlar = session.scalars(
                select(SatisFaturasiSatiri)
                .join(SatisFaturasi)
                .where(
                    SatisFaturasi.cari_id == cari_id,
                    SatisFaturasi.durum != "İPTAL",
                    SatisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(selectinload(SatisFaturasiSatiri.fatura))
                .order_by(SatisFaturasi.fatura_tarihi.desc(), SatisFaturasiSatiri.id.desc())
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
    def musteri_satislari(cari_id: int) -> list[SatisFaturasi]:
        with get_session() as session:
            return list(
                session.scalars(
                    select(SatisFaturasi)
                    .where(SatisFaturasi.cari_id == cari_id, SatisFaturasi.durum != "İPTAL")
                    .options(selectinload(SatisFaturasi.satirlar), selectinload(SatisFaturasi.cari))
                    .order_by(SatisFaturasi.fatura_tarihi.desc())
                ).all()
            )

    @staticmethod
    def _fifo_maliyet_coz(session, veri, depo_adi: str) -> tuple[Decimal, SatisFaturasiSatiri | None]:
        """İade stoğuna yazılacak FIFO birim maliyeti.
        Öncelik: satırda verilen → kaynak fatura satırı → güncel depo FIFO.
        """
        kaynak = None
        kaynak_id = veri.get("kaynak_fatura_satiri_id")
        if kaynak_id:
            kaynak = session.get(SatisFaturasiSatiri, int(kaynak_id))
        verilen = veri.get("fifo_birim_maliyeti")
        if verilen not in (None, "", 0, "0"):
            return decimal(verilen, "FIFO maliyet", Decimal("0")), kaynak
        if kaynak is not None and kaynak.fifo_birim_maliyeti is not None:
            return Decimal(kaynak.fifo_birim_maliyeti), kaynak
        from database.stok_service import StokService
        maliyetler = StokService.maliyetler(veri["urun_kodu"].strip(), depo_adi)
        return Decimal(maliyetler.get("fifo") or 0), kaynak

    @staticmethod
    def _iade_girisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, birim_maliyet, lot_no="", kaynak_satiri=None):
        """FIFO iade girişi:
        1) Kaynak faturadaki lot çıkışları varsa aynı lotlara geri yazılır (asıl FIFO tersine çevirme).
        2) Kalan miktar, satıştaki FIFO birim maliyetiyle yeni iade lotuna girer.
        """
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "İade miktarı", Decimal("0.0001"))
        maliyet = decimal(birim_maliyet, "FIFO birim maliyet", Decimal("0"))
        if kaynak_satiri is not None and kaynak_satiri.fifo_birim_maliyeti is not None:
            maliyet = Decimal(kaynak_satiri.fifo_birim_maliyeti)

        kalan = miktar
        kullanilan = []

        # 1) Orijinal satış lotlarına geri koy (lot_cikisi: "LOT-A:2, LOT-B:1")
        if kaynak_satiri and kaynak_satiri.lot_cikisi:
            for parca in kaynak_satiri.lot_cikisi.split(","):
                if kalan <= 0:
                    break
                parca = parca.strip()
                if ":" not in parca:
                    continue
                lot_adi, mik_str = parca.rsplit(":", 1)
                try:
                    orijinal_cikan = Decimal(str(mik_str).strip())
                except Exception:
                    continue
                if orijinal_cikan <= 0:
                    continue
                eklenecek = min(kalan, orijinal_cikan)
                lot = session.scalar(
                    select(StokLotu).where(
                        StokLotu.stok_id == stok.id,
                        StokLotu.depo_id == depo.id,
                        StokLotu.lot_no == lot_adi.strip(),
                    )
                )
                if not lot:
                    continue
                lot.kalan_miktar += eklenecek
                session.add(StokHareketi(
                    tarih=tarih, hareket_turu="İADE GİRİŞ", belge_no=belge_no,
                    stok_id=stok.id, depo_id=depo.id, lot_id=lot.id,
                    miktar=eklenecek, birim_maliyet=lot.birim_maliyet,
                ))
                kullanilan.append(f"{lot.lot_no}:{eklenecek}")
                kalan -= eklenecek

        # 2) Kalanı FIFO maliyetli yeni iade lotuna yaz
        if kalan > 0:
            temel = (lot_no or "").strip() or f"IADE-{tarih:%Y%m%d}"
            lot_adi, sira = temel, 1
            while session.scalar(
                select(StokLotu).where(
                    StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.lot_no == lot_adi
                )
            ):
                sira += 1
                lot_adi = f"{temel}-{sira}"
            lot = StokLotu(
                stok_id=stok.id, depo_id=depo.id, lot_no=lot_adi, tedarikci="SATIŞ İADESİ",
                giris_tarihi=tarih, kalan_miktar=kalan, birim_maliyet=maliyet,
            )
            session.add(lot)
            session.flush()
            session.add(StokHareketi(
                tarih=tarih, hareket_turu="İADE GİRİŞ", belge_no=belge_no,
                stok_id=stok.id, depo_id=depo.id, lot_id=lot.id, miktar=kalan, birim_maliyet=maliyet,
            ))
            kullanilan.append(f"{lot_adi}:{kalan}")

        return {"lot_girisi": ", ".join(kullanilan), "fifo_birim_maliyeti": maliyet}

    @staticmethod
    def _iade_girislerini_geri_al(session, belge_no):
        hareketler = session.scalars(
            select(StokHareketi).where(
                StokHareketi.belge_no == belge_no, StokHareketi.hareket_turu == "İADE GİRİŞ"
            )
        ).all()
        for hareket in hareketler:
            if hareket.lot_id:
                lot = session.get(StokLotu, hareket.lot_id)
                if lot:
                    lot.kalan_miktar = max(Decimal("0"), lot.kalan_miktar - hareket.miktar)
                    # Bu iade için açılmış yeni lot boşaldıysa sil
                    if (lot.tedarikci or "") == "SATIŞ İADESİ" and lot.kalan_miktar <= 0:
                        session.delete(lot)
            session.delete(hareket)

    @staticmethod
    def kaydet(veriler, satir_verileri, iade_id=None):
        tarih = veriler["iade_tarihi"]
        if tarih > date.today():
            raise ValueError("İade tarihi gelecek bir tarih olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir iade satırı ekleyin.")
        with get_session() as session:
            if iade_id:
                iade = session.get(SatisIadeFaturasi, iade_id)
                if not iade:
                    raise ValueError("İade faturası bulunamadı.")
                if iade.durum == "İPTAL":
                    raise ValueError("İptal edilmiş iade düzenlenemez.")
                SatisIadeFaturasiService._iade_girislerini_geri_al(session, iade.iade_no)
                session.execute(delete(FinansHareketi).where(FinansHareketi.belge_no == iade.iade_no))
                session.execute(delete(CariIslem).where(CariIslem.belge_no == iade.iade_no))
                session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == iade.iade_no))
                iade.satirlar.clear()
            else:
                ozel_no = (veriler.get("iade_no") or "").strip()
                iade = SatisIadeFaturasi(
                    iade_no=ozel_no or SatisIadeFaturasiService.iade_no()
                )
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
                fifo_maliyet, kaynak_satiri = SatisIadeFaturasiService._fifo_maliyet_coz(
                    session, veri, iade.depo
                )
                stok_sonuc = SatisIadeFaturasiService._iade_girisi(
                    session, iade.iade_no, tarih, veri["urun_kodu"].strip(), iade.depo,
                    miktar, fifo_maliyet, veri.get("lot_no") or "", kaynak_satiri,
                )
                iade.satirlar.append(SatisIadeFaturasiSatiri(
                    kaynak_fatura_satiri_id=veri.get("kaynak_fatura_satiri_id") or (
                        kaynak_satiri.id if kaynak_satiri else None
                    ),
                    urun_kodu=veri["urun_kodu"].strip(),
                    urun_adi=veri["urun_adi"].strip(),
                    miktar=miktar,
                    birim=veri.get("birim") or "Adet",
                    birim_fiyat=birim_fiyat,
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                    onceki_alis_fiyati=decimal(onceki, "Önceki alış", Decimal("0")) if onceki not in (None, "") else None,
                    onceki_fatura_no=veri.get("onceki_fatura_no") or None,
                    fifo_birim_maliyeti=stok_sonuc["fifo_birim_maliyeti"],
                    lot_no=stok_sonuc["lot_girisi"],
                ))

            toplam = SatisIadeFaturasiService.toplam(iade.satirlar)["genel_toplam"]
            if iade.iade_odeme_tutari > toplam:
                raise ValueError("İade ödeme tutarı iade toplamından büyük olamaz.")
            iade.durum = "KAPALI" if iade.iade_odeme_tutari >= toplam else "AÇIK"
            session.flush()

            # Cari: iade müşteri borcunu azaltır (alacak + açık bakiyeden düşüş)
            session.add(CariIslem(
                cari_id=iade.cari_id, tarih=tarih, islem_turu="Satış İadesi",
                belge_no=iade.iade_no, aciklama=iade.aciklama or "Satış iade faturası",
                borc=Decimal("0"), alacak=toplam, hesap_adi=iade.iade_odeme_hesabi,
            ))
            CariService._aciklara_uygula(session, iade.cari_id, toplam)
            if iade.iade_odeme_tutari > 0:
                FinansService.hareket_ekle(
                    session, iade.iade_no, tarih, iade.iade_odeme_tutari,
                    "SATIŞ İADE ÖDEMESİ", iade.iade_odeme_hesabi, iade.iade_odeme_sekli,
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
                select(SatisIadeFaturasi)
                .options(selectinload(SatisIadeFaturasi.satirlar))
                .where(SatisIadeFaturasi.id == iade_id)
            )
            if not iade:
                raise ValueError("İade faturası bulunamadı.")
            if iade.durum == "İPTAL":
                return
            toplam = SatisIadeFaturasiService.toplam(iade.satirlar)["genel_toplam"]
            CariService._aciklara_geri_al(session, iade.cari_id, toplam, iade.iade_no)
            SatisIadeFaturasiService._iade_girislerini_geri_al(session, iade.iade_no)
            session.execute(delete(FinansHareketi).where(FinansHareketi.belge_no == iade.iade_no))
            session.execute(delete(CariIslem).where(CariIslem.belge_no == iade.iade_no))
            session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == iade.iade_no))
            iade.durum = "İPTAL"

    @staticmethod
    def toplam(satirlar) -> dict[str, Decimal]:
        return SatisFaturasiService.toplam(
            [
                {
                    "miktar": getattr(s, "miktar", s.get("miktar") if isinstance(s, dict) else 0),
                    "birim_fiyat": getattr(s, "birim_fiyat", s.get("birim_fiyat") if isinstance(s, dict) else 0),
                    "iskonto_orani": getattr(s, "iskonto_orani", s.get("iskonto_orani", 0) if isinstance(s, dict) else 0),
                    "kdv_orani": getattr(s, "kdv_orani", s.get("kdv_orani", 20) if isinstance(s, dict) else 20),
                }
                for s in satirlar
            ]
        )
