"""Lot barkodu üretimi, çözümleme ve etiket baskı kuyruğu.

Code 128 kayıt kodu: L + 8 hane (örn. L00001234). Genel stok barkoduna yazılmaz;
ayrı ``stok_lot_barkodlari`` tablosunda ürün+lot+birim ilişkisi tutulur.
Yeniden baskı stok/cari/muhasebe hareketi üretmez.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.models.stok import StokBarkod, StokBirim, StokKarti, StokLotu
from database.models.stok_lot_barkod import (
    StokEtiketIsi,
    StokEtiketIsSatiri,
    StokLotBarkodu,
    StokLotBarkodSayac,
)

logger = logging.getLogger(__name__)

ONEK = "L"
DURUM_BEKLIYOR = "ETIKET_BEKLIYOR"
DURUM_HAZIR = "BASKI_HAZIR"
DURUM_GONDERILDI = "YAZICIYA_GONDERILDI"
DURUM_TAMAMLANDI = "ETIKETLEME_TAMAMLANDI"
DURUM_HATA = "HATA_YENIDEN_BASIM"


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.kullanici_adi or oturum.ad_soyad or None
    except Exception:  # noqa: BLE001
        return None


class LotBarkodService:
    _schema_hazir = False

    @staticmethod
    def ensure_schema() -> None:
        if LotBarkodService._schema_hazir:
            return
        from database.database import Base, engine

        if engine is None:
            return
        import database.models.stok_lot_barkod  # noqa: F401

        Base.metadata.create_all(
            bind=engine,
            tables=[
                StokLotBarkodu.__table__,
                StokLotBarkodSayac.__table__,
                StokEtiketIsi.__table__,
                StokEtiketIsSatiri.__table__,
            ],
        )
        LotBarkodService._schema_hazir = True

    @staticmethod
    def _sonraki_kod(session) -> str:
        sayac = session.scalar(select(StokLotBarkodSayac).limit(1))
        if sayac is None:
            sayac = StokLotBarkodSayac(son_no=0)
            session.add(sayac)
            session.flush()
        for _ in range(20):
            sayac.son_no = int(sayac.son_no or 0) + 1
            session.flush()
            kod = f"{ONEK}{sayac.son_no:08d}"
            var = session.scalar(select(StokLotBarkodu.id).where(StokLotBarkodu.barkod == kod))
            genel = session.scalar(select(StokBarkod.id).where(StokBarkod.barkod == kod))
            kart = session.scalar(select(StokKarti.id).where(StokKarti.barkod == kod))
            birim_b = session.scalar(select(StokBirim.id).where(StokBirim.birim_barkod == kod))
            if not any((var, genel, kart, birim_b)):
                return kod
        raise RuntimeError("Lot barkod kodu üretilemedi (çakışma).")

    @staticmethod
    def _carpan(session, stok: StokKarti, birim: str) -> Decimal:
        from database.stok_service import StokService

        return Decimal(str(StokService.birim_carpani_kesin(stok, birim) or 1))

    @staticmethod
    def lot_barkodu_al_veya_olustur(
        session,
        *,
        stok_id: int,
        lot_id: int,
        birim: str | None = None,
    ) -> StokLotBarkodu:
        """Aynı ürün+lot+birim için tek aktif barkod; yoksa üretir."""
        LotBarkodService.ensure_schema()
        stok = session.get(StokKarti, int(stok_id))
        lot = session.get(StokLotu, int(lot_id))
        if stok is None or lot is None:
            raise ValueError("Ürün veya lot bulunamadı.")
        if int(lot.stok_id) != int(stok.id):
            raise ValueError("Lot bu ürüne ait değil.")
        birim_ad = (birim or stok.birim or "Adet").strip() or "Adet"
        carpan = LotBarkodService._carpan(session, stok, birim_ad)
        mevcut = session.scalar(
            select(StokLotBarkodu).where(
                StokLotBarkodu.stok_id == stok.id,
                StokLotBarkodu.lot_id == lot.id,
                StokLotBarkodu.birim == birim_ad,
                StokLotBarkodu.aktif.is_(True),
            )
        )
        if mevcut is not None:
            return mevcut
        kod = LotBarkodService._sonraki_kod(session)
        kayit = StokLotBarkodu(
            barkod=kod,
            stok_id=stok.id,
            lot_id=lot.id,
            birim=birim_ad,
            birim_carpani=carpan,
            katsayi_surum=1,
            aktif=True,
            olusturan=_kullanici(),
        )
        try:
            with session.begin_nested():
                session.add(kayit)
                session.flush()
        except IntegrityError:
            mevcut = session.scalar(
                select(StokLotBarkodu).where(
                    StokLotBarkodu.stok_id == stok.id,
                    StokLotBarkodu.lot_id == lot.id,
                    StokLotBarkodu.birim == birim_ad,
                    StokLotBarkodu.aktif.is_(True),
                )
            )
            if mevcut is None:
                raise
            return mevcut
        return kayit

    @staticmethod
    def coz(barkod: str) -> dict[str, Any] | None:
        """Lot barkodunu çözümler; bulunamazsa None (genel barkod akışına bırakılır)."""
        from database.barkod_okut_service import barkod_temizle
        from database.stok_service import StokService

        LotBarkodService.ensure_schema()
        kod = barkod_temizle(barkod)
        if not kod or not kod.upper().startswith(ONEK):
            # Lot kodları L ile başlar; yine de tam eşleşme dene
            pass
        with get_session() as session:
            kayit = session.scalar(
                select(StokLotBarkodu).where(StokLotBarkodu.barkod == kod, StokLotBarkodu.aktif.is_(True))
            )
            if kayit is None and kod != kod.upper():
                kayit = session.scalar(
                    select(StokLotBarkodu).where(
                        StokLotBarkodu.barkod == kod.upper(), StokLotBarkodu.aktif.is_(True)
                    )
                )
            if kayit is None:
                return None
            stok = session.get(StokKarti, kayit.stok_id)
            lot = session.get(StokLotu, kayit.lot_id)
            if stok is None or lot is None:
                return {
                    "durum": "bulunamadi",
                    "mesaj": "Barkod bağlı ürün/lot silinmiş.",
                    "barkod": kod,
                }
            if not stok.aktif or getattr(stok, "is_deleted", False):
                return {
                    "durum": "pasif",
                    "mesaj": f"{stok.stok_adi}: ürün pasif.",
                    "barkod": kod,
                    "stok_id": stok.id,
                }
            fiyat = StokService.satis_fiyati_1(stok.stok_kodu, Decimal("0"))
            depo_adi = lot.depo.ad if lot.depo is not None else ""
            return {
                "durum": "ok",
                "lot_barkod": True,
                "barkod": kayit.barkod,
                "stok_id": int(stok.id),
                "stok_kodu": stok.stok_kodu,
                "stok_adi": stok.stok_adi,
                "lot_id": int(lot.id),
                "lot_no": lot.lot_no,
                "depo_id": int(lot.depo_id),
                "depo": depo_adi,
                "birim": kayit.birim,
                "birim_carpani": Decimal(str(kayit.birim_carpani or 1)),
                "miktar": Decimal("1"),  # 1 etiket birimi
                "birim_fiyat": fiyat,
                "mevcut_stok": Decimal(str(lot.kalan_miktar or 0)),
                "kdv_orani": Decimal(str(stok.kdv_orani or 20)),
                "aktif": True,
                "satis_kapali": False,
            }

    @staticmethod
    def satis_fiyati(stok_id: int, birim: str | None = None) -> Decimal | None:
        """Etiket satış fiyatı; yoksa None (sıfır basılmaz)."""
        from database.stok_service import StokService

        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if stok is None:
                return None
            fiyat = StokService.satis_fiyati_1(stok.stok_kodu, Decimal("0"))
            if fiyat is None or Decimal(str(fiyat)) <= 0:
                return None
            return Decimal(str(fiyat))

    @staticmethod
    def giristen_etiket_isi_olustur(
        *,
        kaynak_tur: str,
        kaynak_belge_no: str,
        kaynak_belge_id: int | None,
        lotlar: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Mal girişi sonrası barkod + etiket işi. lotlar: lot_id, stok_id, birim?, miktar.

        Aynı belge için ikinci çağrı mevcut bekleyen işi döndürür (mükerrer yok).
        """
        LotBarkodService.ensure_schema()
        if not lotlar:
            return None
        with get_session() as session:
            mevcut = session.scalar(
                select(StokEtiketIsi).where(
                    StokEtiketIsi.kaynak_tur == kaynak_tur,
                    StokEtiketIsi.kaynak_belge_no == kaynak_belge_no,
                    StokEtiketIsi.durum != DURUM_TAMAMLANDI,
                )
            )
            if mevcut is not None:
                return LotBarkodService.is_ozeti(session, mevcut)

            is_ = StokEtiketIsi(
                kaynak_tur=kaynak_tur,
                kaynak_belge_no=kaynak_belge_no,
                kaynak_belge_id=kaynak_belge_id,
                durum=DURUM_BEKLIYOR,
                olusturan=_kullanici(),
            )
            session.add(is_)
            session.flush()
            for L in lotlar:
                lot_id = int(L["lot_id"])
                stok_id = int(L["stok_id"])
                stok = session.get(StokKarti, stok_id)
                birim = (L.get("birim") or (stok.birim if stok else None) or "Adet").strip()
                barkod = LotBarkodService.lot_barkodu_al_veya_olustur(
                    session, stok_id=stok_id, lot_id=lot_id, birim=birim
                )
                fiyat = LotBarkodService.satis_fiyati(stok_id, birim)
                miktar = Decimal(str(L.get("miktar") or 0))
                # Varsayılan: satır başına 1 etiket (kullanıcı adedi değiştirir)
                adet = max(1, int(L.get("etiket_adedi") or 1))
                session.add(
                    StokEtiketIsSatiri(
                        is_id=is_.id,
                        lot_barkod_id=barkod.id,
                        stok_id=stok_id,
                        lot_id=lot_id,
                        birim=birim,
                        giren_miktar=miktar,
                        etiket_adedi=adet,
                        urun_adi=(stok.stok_adi if stok else None),
                        satis_fiyati=fiyat,
                        para_birimi="TRY",
                        kdv_dahil=True,
                        durum=DURUM_BEKLIYOR,
                    )
                )
            session.flush()
            return LotBarkodService.is_ozeti(session, is_)

    @staticmethod
    def is_ozeti(session, is_: StokEtiketIsi) -> dict[str, Any]:
        satirlar = []
        for s in is_.satirlar or []:
            lb = session.get(StokLotBarkodu, s.lot_barkod_id)
            lot = session.get(StokLotu, s.lot_id)
            stok = session.get(StokKarti, s.stok_id)
            satirlar.append({
                "id": s.id,
                "barkod": lb.barkod if lb else "",
                "lot_barkod_id": s.lot_barkod_id,
                "stok_id": s.stok_id,
                "stok_kodu": stok.stok_kodu if stok else "",
                "stok_adi": s.urun_adi or (stok.stok_adi if stok else ""),
                "lot_id": s.lot_id,
                "lot_no": lot.lot_no if lot else "",
                "depo": lot.depo.ad if lot and lot.depo else "",
                "birim": s.birim,
                "giren_miktar": Decimal(str(s.giren_miktar or 0)),
                "etiket_adedi": int(s.etiket_adedi or 1),
                "satis_fiyati": s.satis_fiyati,
                "para_birimi": s.para_birimi or "TRY",
                "kdv_dahil": bool(s.kdv_dahil),
                "durum": s.durum,
                "basilan_adet": int(s.basilan_adet or 0),
            })
        return {
            "id": is_.id,
            "kaynak_tur": is_.kaynak_tur,
            "kaynak_belge_no": is_.kaynak_belge_no,
            "kaynak_belge_id": is_.kaynak_belge_id,
            "durum": is_.durum,
            "olusturma_tarihi": is_.olusturma_tarihi,
            "satirlar": satirlar,
        }

    @staticmethod
    def is_getir(is_id: int) -> dict[str, Any] | None:
        LotBarkodService.ensure_schema()
        with get_session() as session:
            is_ = session.get(StokEtiketIsi, int(is_id))
            if is_ is None:
                return None
            return LotBarkodService.is_ozeti(session, is_)

    @staticmethod
    def bekleyenler(*, durum: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        LotBarkodService.ensure_schema()
        with get_session() as session:
            q = select(StokEtiketIsi).order_by(StokEtiketIsi.id.desc()).limit(limit)
            if durum:
                q = q.where(StokEtiketIsi.durum == durum)
            else:
                q = q.where(StokEtiketIsi.durum != DURUM_TAMAMLANDI)
            return [LotBarkodService.is_ozeti(session, i) for i in session.scalars(q).all()]

    @staticmethod
    def basim_kaydet(is_id: int, satir_adetleri: dict[int, int] | None = None) -> dict[str, Any]:
        """Yazıcıya gönderildi işaretle; stok miktarını değiştirmez."""
        LotBarkodService.ensure_schema()
        with get_session() as session:
            is_ = session.get(StokEtiketIsi, int(is_id))
            if is_ is None:
                raise ValueError("Etiket işi bulunamadı.")
            simdi = datetime.now()
            for s in is_.satirlar or []:
                adet = int((satir_adetleri or {}).get(s.id, s.etiket_adedi) or 1)
                s.etiket_adedi = max(1, adet)
                s.basilan_adet = int(s.basilan_adet or 0) + s.etiket_adedi
                s.son_baski_tarihi = simdi
                s.durum = DURUM_GONDERILDI
                if s.satis_fiyati is None or Decimal(str(s.satis_fiyati)) <= 0:
                    fiyat = LotBarkodService.satis_fiyati(s.stok_id, s.birim)
                    if fiyat is None:
                        raise ValueError(
                            f"{s.urun_adi or s.stok_id}: satış fiyatı yok; etiket basılamaz."
                        )
                    s.satis_fiyati = fiyat
            is_.durum = DURUM_GONDERILDI
            session.flush()
            return LotBarkodService.is_ozeti(session, is_)

    @staticmethod
    def etiketleme_tamamla(is_id: int) -> dict[str, Any]:
        LotBarkodService.ensure_schema()
        with get_session() as session:
            is_ = session.get(StokEtiketIsi, int(is_id))
            if is_ is None:
                raise ValueError("Etiket işi bulunamadı.")
            is_.durum = DURUM_TAMAMLANDI
            is_.tamamlayan = _kullanici()
            is_.tamamlanma_tarihi = datetime.now()
            for s in is_.satirlar or []:
                s.durum = DURUM_TAMAMLANDI
            session.flush()
            return LotBarkodService.is_ozeti(session, is_)

    @staticmethod
    def belge_giris_lotlari(session, belge_no: str, hareket_turu: str = "FATURA GİRİŞ") -> list[dict]:
        from database.models.stok import StokHareketi

        sonuc = []
        for h in session.scalars(
            select(StokHareketi).where(
                StokHareketi.belge_no == belge_no,
                StokHareketi.hareket_turu == hareket_turu,
                StokHareketi.lot_id.is_not(None),
            )
        ).all():
            sonuc.append({
                "lot_id": int(h.lot_id),
                "stok_id": int(h.stok_id),
                "miktar": Decimal(str(h.miktar or 0)),
            })
        return sonuc

    @staticmethod
    def alis_faturasi_sonrasi(fatura) -> dict[str, Any] | None:
        """Alış faturası kaydından sonra etiket işi oluştur."""
        if fatura is None:
            return None
        LotBarkodService.ensure_schema()
        with get_session() as session:
            lotlar = LotBarkodService.belge_giris_lotlari(session, fatura.fatura_no, "FATURA GİRİŞ")
            from database.models.alis_faturasi import AlisFaturasiSatiri

            satirlar = list(
                session.scalars(
                    select(AlisFaturasiSatiri).where(AlisFaturasiSatiri.fatura_id == fatura.id)
                ).all()
            )
            # lot_no → satır birimi (mümkünse)
            lot_birim: dict[str, str] = {}
            for sat in satirlar:
                ln = (getattr(sat, "lot_girisi", None) or "").strip()
                if ln:
                    lot_birim[ln] = (sat.birim or "Adet").strip() or "Adet"
            for L in lotlar:
                lot = session.get(StokLotu, L["lot_id"])
                stok = session.get(StokKarti, L["stok_id"])
                birim = None
                if lot is not None:
                    birim = lot_birim.get((lot.lot_no or "").strip())
                if not birim and stok is not None:
                    birim = stok.birim or "Adet"
                L["birim"] = (birim or "Adet").strip() or "Adet"
            if not lotlar:
                return None
        return LotBarkodService.giristen_etiket_isi_olustur(
            kaynak_tur="ALIS_FATURA",
            kaynak_belge_no=fatura.fatura_no,
            kaynak_belge_id=int(fatura.id),
            lotlar=lotlar,
        )
