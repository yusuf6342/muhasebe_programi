from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.stok import Depo, StokFiyati, StokHareketi, StokKarti, StokLotu
from database.satis_siparisi_service import decimal


class StokService:
    @staticmethod
    def varsayilanlari_hazirla():
        with get_session() as session:
            if not session.scalar(select(Depo).where(Depo.ad == "ANA DEPO")):
                session.add(Depo(ad="ANA DEPO"))

    @staticmethod
    def depolar():
        with get_session() as session:
            return list(session.scalars(select(Depo).where(Depo.aktif.is_(True)).order_by(Depo.ad)).all())

    @staticmethod
    def depo_ekle(ad):
        ad = ad.strip().upper()
        if not ad: raise ValueError("Depo adı boş olamaz.")
        with get_session() as session:
            mevcut = session.scalar(select(Depo).where(func.lower(Depo.ad) == ad.lower()))
            if mevcut: return mevcut
            depo = Depo(ad=ad); session.add(depo); session.flush(); return depo

    @staticmethod
    def stoklari_ara(arama=""):
        with get_session() as session:
            q = select(StokKarti).where(StokKarti.aktif.is_(True)).options(
                selectinload(StokKarti.fiyatlar), selectinload(StokKarti.lotlar)
            ).order_by(StokKarti.stok_adi)
            if arama:
                ifade = f"%{arama}%"
                q = q.where(or_(StokKarti.stok_kodu.ilike(ifade), StokKarti.stok_adi.ilike(ifade), StokKarti.barkod.ilike(ifade)))
            return list(session.scalars(q).all())

    @staticmethod
    def stok_kaydi(veriler, fiyatlar):
        with get_session() as session:
            stok_id = veriler.get("stok_id")
            stok = session.get(StokKarti, int(stok_id)) if stok_id else None
            if not stok:
                stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == veriler["stok_kodu"].strip()))
            if not stok:
                stok = StokKarti(stok_kodu=veriler["stok_kodu"].strip()); session.add(stok)
            stok.stok_kodu = veriler["stok_kodu"].strip()
            stok.stok_adi = veriler["stok_adi"].strip()
            stok.barkod = veriler.get("barkod") or None
            stok.birim = veriler.get("birim") or "Adet"
            stok.fiyatlar.clear()
            for ad, tutar in fiyatlar:
                if str(tutar).strip():
                    stok.fiyatlar.append(StokFiyati(fiyat_adi=ad, tutar=decimal(tutar, ad, Decimal("0")), para_birimi="TL"))
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Stok kodu veya barkod başka bir stok kartında kullanılıyor.") from hata
            return stok

    @staticmethod
    def fiyatlar(stok_kodu):
        with get_session() as session:
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu).options(selectinload(StokKarti.fiyatlar)))
            return list(stok.fiyatlar) if stok else []

    @staticmethod
    def lotlar(stok_kodu, depo_adi):
        with get_session() as session:
            return list(session.scalars(select(StokLotu).join(StokKarti).join(Depo).where(
                StokKarti.stok_kodu == stok_kodu, Depo.ad == depo_adi, StokLotu.kalan_miktar > 0
            ).order_by(StokLotu.giris_tarihi, StokLotu.id)).all())

    @staticmethod
    def maliyetler(stok_kodu, depo_adi):
        lotlar = StokService.lotlar(stok_kodu, depo_adi)
        if not lotlar:
            sifir = Decimal("0")
            return {"fifo": sifir, "son_alis": sifir, "ortalama": sifir, "agirlikli": sifir}
        toplam_miktar = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        agirlikli = sum((lot.kalan_miktar * lot.birim_maliyet for lot in lotlar), Decimal("0"))
        return {
            "fifo": lotlar[0].birim_maliyet,
            "son_alis": lotlar[-1].birim_maliyet,
            "ortalama": sum((lot.birim_maliyet for lot in lotlar), Decimal("0")) / Decimal(len(lotlar)),
            "agirlikli": agirlikli / toplam_miktar if toplam_miktar else Decimal("0"),
        }

    @staticmethod
    def otomatik_lot_no(tedarikci, tarih):
        onek = "".join(c for c in (tedarikci or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{tarih:%Y%m%d}"

    @staticmethod
    def stok_girisi(stok_kodu, depo_adi, tedarikci, tarih, miktar, maliyet, lot_no=""):
        miktar = decimal(miktar, "Miktar", Decimal("0.0001")); maliyet = decimal(maliyet, "Birim maliyet", Decimal("0"))
        with get_session() as session:
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
            depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
            if not stok: raise ValueError("Stok kartı bulunamadı.")
            if not depo: raise ValueError("Depo bulunamadı.")
            temel = lot_no.strip() or StokService.otomatik_lot_no(tedarikci, tarih)
            lot_adi, sira = temel, 1
            while session.scalar(select(StokLotu).where(StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.lot_no == lot_adi)):
                sira += 1; lot_adi = f"{temel}-{sira}"
            lot = StokLotu(stok_id=stok.id, depo_id=depo.id, lot_no=lot_adi, tedarikci=tedarikci or None, giris_tarihi=tarih, kalan_miktar=miktar, birim_maliyet=maliyet)
            session.add(lot); session.flush()
            session.add(StokHareketi(tarih=tarih, hareket_turu="GİRİŞ", belge_no=lot_adi, stok_id=stok.id, depo_id=depo.id, lot_id=lot.id, miktar=miktar, birim_maliyet=maliyet))
            return lot

    @staticmethod
    def fatura_cikislarini_geri_al(session, belge_no):
        hareketler = session.scalars(select(StokHareketi).where(StokHareketi.belge_no == belge_no, StokHareketi.hareket_turu == "FATURA ÇIKIŞ")).all()
        for hareket in hareketler:
            if hareket.lot_id:
                lot = session.get(StokLotu, hareket.lot_id)
                if lot: lot.kalan_miktar += hareket.miktar
            session.delete(hareket)

    @staticmethod
    def fatura_cikisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, tercih_lot=""):
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok: raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo: raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Çıkış miktarı", Decimal("0.0001"))
        q = select(StokLotu).where(StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.kalan_miktar > 0)
        if tercih_lot: q = q.where(StokLotu.lot_no == tercih_lot)
        lotlar = list(session.scalars(q.order_by(StokLotu.giris_tarihi, StokLotu.id)).all())
        mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        if mevcut < miktar: raise ValueError(f"{stok.stok_adi} için {depo.ad} stok yetersiz. Mevcut: {mevcut}, istenen: {miktar}")
        kalan, maliyet, kullanilan = miktar, Decimal("0"), []
        for lot in lotlar:
            if kalan <= 0: break
            cikan = min(kalan, lot.kalan_miktar); lot.kalan_miktar -= cikan; kalan -= cikan
            maliyet += cikan * lot.birim_maliyet; kullanilan.append(f"{lot.lot_no}:{cikan}")
            session.add(StokHareketi(tarih=tarih, hareket_turu="FATURA ÇIKIŞ", belge_no=belge_no, stok_id=stok.id, depo_id=depo.id, lot_id=lot.id, miktar=cikan, birim_maliyet=lot.birim_maliyet))
        return {"lot_cikisi": ", ".join(kullanilan), "fifo_birim_maliyeti": maliyet / miktar}
