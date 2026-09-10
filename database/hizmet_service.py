"""Gelir / gider hizmet kartı servisi."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.hizmet import (
    GIDER_SINIF_KODLARI,
    GIDER_SINIF_ONEKLERI,
    HIZMET_BIRIMLERI,
    HIZMET_TURLERI,
    HizmetHareketi,
    HizmetKarti,
)


def _decimal(deger, alan="Tutar", minimum=None) -> Decimal:
    try:
        sonuc = Decimal(str(deger).strip().replace(",", "."))
    except (InvalidOperation, AttributeError) as hata:
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from hata
    if minimum is not None and sonuc < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return sonuc


class HizmetService:
    @staticmethod
    def otomatik_kod(hizmet_turu: str, gider_sinifi: str | None = None) -> str:
        tur = (hizmet_turu or "").upper()
        if tur == "GELIR":
            on_ek = "GHZ"
        else:
            sinif = (gider_sinifi or "ISLETME").strip().upper()
            on_ek = GIDER_SINIF_ONEKLERI.get(sinif, "IGZ")
        with get_session() as session:
            kodlar = session.scalars(
                select(HizmetKarti.hizmet_kodu).where(
                    HizmetKarti.hizmet_kodu.like(f"{on_ek}-%")
                )
            ).all()
            max_no = 0
            for kod in kodlar:
                parca = (kod or "").split("-")[-1]
                if parca.isdigit():
                    max_no = max(max_no, int(parca))
            return f"{on_ek}-{max_no + 1:05d}"

    @staticmethod
    def listele(hizmet_turu=None, aktif_only=True, arama=None, gider_sinifi=None):
        with get_session() as session:
            q = (
                select(HizmetKarti)
                .options(selectinload(HizmetKarti.hareketler))
                .order_by(HizmetKarti.hizmet_kodu)
            )
            if hizmet_turu:
                q = q.where(HizmetKarti.hizmet_turu == str(hizmet_turu).upper())
            if gider_sinifi:
                q = q.where(HizmetKarti.gider_sinifi == str(gider_sinifi).upper())
            if aktif_only:
                q = q.where(HizmetKarti.aktif.is_(True))
            satirlar = list(session.scalars(q).all())
            if arama:
                a = arama.strip().lower()
                satirlar = [
                    h
                    for h in satirlar
                    if a in (h.hizmet_kodu or "").lower()
                    or a in (h.hizmet_adi or "").lower()
                    or a in (h.gider_sinifi or "").lower()
                ]
            return satirlar

    @staticmethod
    def getir(hizmet_id) -> HizmetKarti | None:
        with get_session() as session:
            return session.scalar(
                select(HizmetKarti)
                .where(HizmetKarti.id == int(hizmet_id))
                .options(selectinload(HizmetKarti.hareketler))
            )

    @staticmethod
    def kaydet(veriler: dict) -> HizmetKarti:
        kod = (veriler.get("hizmet_kodu") or "").strip().upper()
        ad = (veriler.get("hizmet_adi") or "").strip()
        tur = (veriler.get("hizmet_turu") or "").strip().upper()
        if not ad:
            raise ValueError("Hizmet adı zorunludur.")
        if tur not in {k for k, _ in HIZMET_TURLERI}:
            raise ValueError("Hizmet türü Gider veya Gelir olmalıdır.")

        gider_sinifi = None
        if tur == "GIDER":
            gider_sinifi = (veriler.get("gider_sinifi") or "").strip().upper()
            if not gider_sinifi:
                raise ValueError("Gider kartı için gider sınıfı zorunludur.")
            if gider_sinifi not in GIDER_SINIF_KODLARI:
                raise ValueError("Geçersiz gider sınıfı.")
        if not kod:
            kod = HizmetService.otomatik_kod(tur, gider_sinifi)

        birim = (veriler.get("birim") or "Adet").strip() or "Adet"
        if birim not in HIZMET_BIRIMLERI:
            # serbest birim de kabul
            pass
        alis = _decimal(veriler.get("alis_fiyati") or 0, "Alış fiyatı", Decimal("0"))
        satis = _decimal(veriler.get("satis_fiyati") or 0, "Satış fiyatı", Decimal("0"))
        kdv = _decimal(veriler.get("kdv_orani") or 20, "KDV oranı", Decimal("0"))
        if kdv > 100:
            raise ValueError("KDV oranı 100'den büyük olamaz.")

        with get_session() as session:
            hizmet_id = veriler.get("hizmet_id")
            mevcut = None
            if hizmet_id:
                mevcut = session.scalar(
                    select(HizmetKarti).where(HizmetKarti.id == int(hizmet_id))
                )
            cakisan = session.scalar(
                select(HizmetKarti).where(HizmetKarti.hizmet_kodu == kod)
            )
            if cakisan and (not mevcut or cakisan.id != mevcut.id):
                raise ValueError(f"Bu hizmet kodu zaten kayıtlı: {kod}")

            if mevcut:
                hizmet = mevcut
            else:
                hizmet = HizmetKarti(hizmet_kodu=kod, hizmet_turu=tur)
                session.add(hizmet)

            hizmet.hizmet_kodu = kod
            hizmet.hizmet_adi = ad
            hizmet.hizmet_turu = tur
            hizmet.gider_sinifi = gider_sinifi
            hizmet.birim = birim
            hizmet.alis_fiyati = alis
            hizmet.satis_fiyati = satis
            hizmet.kdv_orani = kdv
            hizmet.muhasebe_gider_kodu = (veriler.get("muhasebe_gider_kodu") or "").strip() or None
            hizmet.muhasebe_gelir_kodu = (veriler.get("muhasebe_gelir_kodu") or "").strip() or None
            hizmet.muhasebe_kdv_alis_kodu = (
                veriler.get("muhasebe_kdv_alis_kodu") or ""
            ).strip() or None
            hizmet.muhasebe_kdv_satis_kodu = (
                veriler.get("muhasebe_kdv_satis_kodu") or ""
            ).strip() or None
            hizmet.aciklama = (veriler.get("aciklama") or "").strip() or None
            if "aktif" in veriler:
                hizmet.aktif = bool(veriler["aktif"])
            session.flush()
            hid = hizmet.id

        return HizmetService.getir(hid)

    @staticmethod
    def pasif_yap(hizmet_id):
        with get_session() as session:
            h = session.scalar(select(HizmetKarti).where(HizmetKarti.id == int(hizmet_id)))
            if not h:
                raise ValueError("Hizmet bulunamadı.")
            h.aktif = False

    @staticmethod
    def hareketler(hizmet_id, limit=300):
        with get_session() as session:
            q = (
                select(HizmetHareketi)
                .where(HizmetHareketi.hizmet_id == int(hizmet_id))
                .order_by(HizmetHareketi.tarih.desc(), HizmetHareketi.id.desc())
                .limit(limit)
            )
            return list(session.scalars(q).all())

    @staticmethod
    def manuel_hareket_ekle(
        hizmet_id,
        tarih,
        hareket_turu,
        belge_no,
        miktar,
        birim_fiyat,
        isaret=1,
        kdv_orani=None,
        aciklama=None,
        cari_id=None,
    ) -> HizmetHareketi:
        """İskelet: faturalar bağlanana kadar test / manuel kayıt için."""
        miktar = _decimal(miktar, "Miktar", Decimal("0.0001"))
        birim_fiyat = _decimal(birim_fiyat, "Birim fiyat", Decimal("0"))
        tutar = (miktar * birim_fiyat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        with get_session() as session:
            h = session.scalar(select(HizmetKarti).where(HizmetKarti.id == int(hizmet_id)))
            if not h:
                raise ValueError("Hizmet bulunamadı.")
            kdv = (
                _decimal(kdv_orani, "KDV", Decimal("0"))
                if kdv_orani is not None
                else Decimal(str(h.kdv_orani or 0))
            )
            belgeno = (belge_no or "").strip() or f"HM{h.id}-{tarih.strftime('%Y%m%d')}"
            har = HizmetHareketi(
                hizmet_id=h.id,
                tarih=tarih,
                hareket_turu=(hareket_turu or "MANUEL").strip().upper(),
                belge_no=belgeno,
                miktar=miktar,
                birim_fiyat=birim_fiyat,
                kdv_orani=kdv,
                tutar=tutar,
                isaret=1 if int(isaret) >= 0 else -1,
                cari_id=int(cari_id) if cari_id else None,
                aciklama=(aciklama or "").strip() or None,
            )
            session.add(har)
            session.flush()
            return har
