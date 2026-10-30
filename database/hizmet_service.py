"""Gelir / gider hizmet kartı servisi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import Base, engine, get_session
from database.models.hizmet import (
    GIDER_SINIF_KODLARI,
    GIDER_SINIF_ONEKLERI,
    HIZMET_BIRIMLERI,
    HIZMET_TURLERI,
    HizmetHareketi,
    HizmetKarti,
    HizmetKaynakEngel,
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
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.hizmet  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[HizmetKarti.__table__, HizmetHareketi.__table__, HizmetKaynakEngel.__table__],
        )
        # Mevcut DB'de kolon ekle
        try:
            from sqlalchemy import inspect, text

            if inspect(bag).has_table("hizmet_kartlari"):
                sutunlar = {c["name"] for c in inspect(bag).get_columns("hizmet_kartlari")}
                ekler = {
                    "kaynak_sistem": "VARCHAR(40)",
                    "kaynak_kimlik": "VARCHAR(80)",
                    "kullanici_duzenledi": "BOOLEAN DEFAULT 0",
                }
                with bag.begin() as conn:
                    for alan, tip in ekler.items():
                        if alan not in sutunlar:
                            conn.execute(
                                text(f'ALTER TABLE "hizmet_kartlari" ADD COLUMN "{alan}" {tip}')
                            )
        except Exception:
            pass
        cls._schema_hazir = True

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
    def listele(
        hizmet_turu=None,
        aktif_only=True,
        arama=None,
        gider_sinifi=None,
        durum_filtre: str | None = None,
    ):
        """durum_filtre: aktif | pasif | tumu (None + aktif_only uyumu korunur)."""
        HizmetService.ensure_schema()
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
            df = (durum_filtre or "").strip().lower()
            if df == "aktif":
                q = q.where(HizmetKarti.aktif.is_(True))
            elif df == "pasif":
                q = q.where(HizmetKarti.aktif.is_(False))
            elif df in ("tumu", "all", ""):
                if not df and aktif_only:
                    q = q.where(HizmetKarti.aktif.is_(True))
            elif aktif_only:
                q = q.where(HizmetKarti.aktif.is_(True))
            satirlar = list(session.scalars(q).all())
            if arama:
                from database.turkce_normalize import tr_iceriyor

                satirlar = [
                    h
                    for h in satirlar
                    if tr_iceriyor(arama, h.hizmet_kodu, h.hizmet_adi, h.gider_sinifi)
                ]
            return satirlar

    @staticmethod
    def getir(hizmet_id) -> HizmetKarti | None:
        HizmetService.ensure_schema()
        with get_session() as session:
            return session.scalar(
                select(HizmetKarti)
                .where(HizmetKarti.id == int(hizmet_id))
                .options(selectinload(HizmetKarti.hareketler))
            )

    @staticmethod
    def kaydet(veriler: dict, *, kullanici_islemi: bool = True) -> HizmetKarti:
        yazma_zorunlu()
        HizmetService.ensure_schema()
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
                if mevcut is None:
                    raise ValueError("Hizmet kartı bulunamadı.")
            cakisan = session.scalar(
                select(HizmetKarti).where(HizmetKarti.hizmet_kodu == kod)
            )
            if cakisan and (not mevcut or cakisan.id != mevcut.id):
                raise ValueError(f"Bu hizmet kodu zaten kayıtlı: {kod}")

            if mevcut:
                hizmet = mevcut
                # Sabit kimlik / kaynak izi korunur
            else:
                hizmet = HizmetKarti(hizmet_kodu=kod, hizmet_turu=tur)
                session.add(hizmet)
                if veriler.get("kaynak_sistem"):
                    hizmet.kaynak_sistem = str(veriler["kaynak_sistem"]).strip() or None
                if veriler.get("kaynak_kimlik"):
                    hizmet.kaynak_kimlik = str(veriler["kaynak_kimlik"]).strip() or None

            hizmet.hizmet_kodu = kod
            hizmet.hizmet_adi = ad
            hizmet.hizmet_turu = tur
            hizmet.gider_sinifi = gider_sinifi
            hizmet.rapor_ana_grup = (veriler.get("rapor_ana_grup") or "").strip().upper() or None
            hizmet.rapor_alt_grup = (veriler.get("rapor_alt_grup") or "").strip().upper() or None
            hizmet.sonuc_yeri = (veriler.get("sonuc_yeri") or "").strip().upper() or None
            hizmet.maliyet_davranisi = (veriler.get("maliyet_davranisi") or "").strip().upper() or None
            hizmet.duzenlilik = (veriler.get("duzenlilik") or "").strip().upper() or None
            hizmet.dagitim_anahtar_kod = (veriler.get("dagitim_anahtar_kod") or "").strip() or None
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
            if kullanici_islemi:
                # Kullanıcı kaydı: sonraki aktarım ad/sınıf ezmesin
                if mevcut is not None:
                    hizmet.kullanici_duzenledi = True
            elif "kullanici_duzenledi" in veriler:
                hizmet.kullanici_duzenledi = bool(veriler["kullanici_duzenledi"])
            session.flush()
            hid = int(hizmet.id)

        return HizmetService.getir(hid)

    @staticmethod
    def kullanim_ozeti(hizmet_id: int) -> dict[str, Any]:
        """Kartın tüm ilişkileri — ekran tarih aralığına bakılmaz."""
        HizmetService.ensure_schema()
        hid = int(hizmet_id)
        with get_session() as session:
            h = session.get(HizmetKarti, hid)
            if h is None:
                raise ValueError("Hizmet bulunamadı.")
            hareket_n = int(
                session.scalar(
                    select(func.count())
                    .select_from(HizmetHareketi)
                    .where(HizmetHareketi.hizmet_id == hid)
                )
                or 0
            )
            fatura_satir_n = 0
            try:
                from database.models.hizmet_faturasi import HizmetFaturasiSatiri

                fatura_satir_n = int(
                    session.scalar(
                        select(func.count())
                        .select_from(HizmetFaturasiSatiri)
                        .where(HizmetFaturasiSatiri.hizmet_id == hid)
                    )
                    or 0
                )
            except Exception:
                fatura_satir_n = 0
            gider_fisi_n = 0
            try:
                from database.models.finans import GiderFisi

                gider_fisi_n = int(
                    session.scalar(
                        select(func.count())
                        .select_from(GiderFisi)
                        .where(GiderFisi.hizmet_id == hid)
                    )
                    or 0
                )
            except Exception:
                gider_fisi_n = 0
            toplam = hareket_n + fatura_satir_n + gider_fisi_n
            return {
                "hizmet_id": hid,
                "hizmet_kodu": h.hizmet_kodu,
                "hizmet_adi": h.hizmet_adi,
                "hareket": hareket_n,
                "fatura_satir": fatura_satir_n,
                "gider_fisi": gider_fisi_n,
                "toplam": toplam,
                "silinebilir": toplam == 0,
            }

    @staticmethod
    def sil(hizmet_id: int, *, onaylandi: bool = False) -> dict[str, Any]:
        """Yalnızca hiç kullanılmamış kartı siler. Bağlı belge/hareket silinmez."""
        yazma_zorunlu()
        HizmetService.ensure_schema()
        ozet = HizmetService.kullanim_ozeti(int(hizmet_id))
        if not ozet["silinebilir"]:
            raise ValueError(
                f"«{ozet['hizmet_kodu']} — {ozet['hizmet_adi']}» silinemez: "
                f"{ozet['hareket']} hareket, {ozet['fatura_satir']} fatura satırı, "
                f"{ozet['gider_fisi']} gider fişi bağlı. "
                "Geçmiş kayıtlar korunur; Sil yerine Pasif Yap veya Hareketler kullanın."
            )
        if not onaylandi:
            raise ValueError("Silme onayı gerekli.")
        with get_session() as session:
            h = session.get(HizmetKarti, int(hizmet_id))
            if h is None:
                raise ValueError("Hizmet bulunamadı.")
            # Kaynak engeli — sonraki aktarım sessizce yeniden açmasın
            if h.kaynak_sistem and h.kaynak_kimlik:
                mevcut_engel = session.scalar(
                    select(HizmetKaynakEngel).where(
                        HizmetKaynakEngel.kaynak_sistem == h.kaynak_sistem,
                        HizmetKaynakEngel.kaynak_kimlik == h.kaynak_kimlik,
                    )
                )
                if mevcut_engel is None:
                    session.add(
                        HizmetKaynakEngel(
                            kaynak_sistem=h.kaynak_sistem,
                            kaynak_kimlik=h.kaynak_kimlik,
                            hizmet_kodu=h.hizmet_kodu,
                            hizmet_adi=h.hizmet_adi,
                            neden="Kullanıcı sildi",
                        )
                    )
            # Hareket yok; orphan cascade güvenli
            session.delete(h)
            session.flush()
        return {"silindi": True, **ozet}

    @staticmethod
    def pasif_yap(hizmet_id):
        yazma_zorunlu()
        HizmetService.ensure_schema()
        with get_session() as session:
            h = session.scalar(select(HizmetKarti).where(HizmetKarti.id == int(hizmet_id)))
            if not h:
                raise ValueError("Hizmet bulunamadı.")
            h.aktif = False
            h.kullanici_duzenledi = True
            session.flush()

    @staticmethod
    def aktif_yap(hizmet_id):
        yazma_zorunlu()
        HizmetService.ensure_schema()
        with get_session() as session:
            h = session.scalar(select(HizmetKarti).where(HizmetKarti.id == int(hizmet_id)))
            if not h:
                raise ValueError("Hizmet bulunamadı.")
            # Engel varsa kaldır (yeniden aktif = kullanıcı onayı)
            if h.kaynak_sistem and h.kaynak_kimlik:
                engel = session.scalar(
                    select(HizmetKaynakEngel).where(
                        HizmetKaynakEngel.kaynak_sistem == h.kaynak_sistem,
                        HizmetKaynakEngel.kaynak_kimlik == h.kaynak_kimlik,
                    )
                )
                if engel is not None:
                    session.delete(engel)
            h.aktif = True
            h.kullanici_duzenledi = True
            session.flush()

    @staticmethod
    def kaynak_engelli_mi(kaynak_sistem: str, kaynak_kimlik: str) -> bool:
        HizmetService.ensure_schema()
        with get_session() as session:
            return (
                session.scalar(
                    select(HizmetKaynakEngel).where(
                        HizmetKaynakEngel.kaynak_sistem == kaynak_sistem,
                        HizmetKaynakEngel.kaynak_kimlik == kaynak_kimlik,
                    )
                )
                is not None
            )

    @staticmethod
    def kaynak_ile_bul(kaynak_sistem: str, kaynak_kimlik: str) -> HizmetKarti | None:
        HizmetService.ensure_schema()
        with get_session() as session:
            return session.scalar(
                select(HizmetKarti).where(
                    HizmetKarti.kaynak_sistem == kaynak_sistem,
                    HizmetKarti.kaynak_kimlik == kaynak_kimlik,
                )
            )

    @staticmethod
    def hareketler(hizmet_id, limit=300):
        HizmetService.ensure_schema()
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
        yazma_zorunlu()
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
