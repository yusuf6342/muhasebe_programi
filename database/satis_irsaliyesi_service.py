"""Satış irsaliyesi servisi — stok çıkışı yalnızca sevk_et ile.

Stok politikası:
  - kaydet (TASLAK) → stok çıkışı YOK
  - sevk_et → StokService.irsaliye_cikisi (İRSALİYE ÇIKIŞ), stok_cikis_yapildi=True
  - iptal_et (sevkedilmiş) → irsaliye_cikis_iptal ile geri al
  - Sipariş irsaliyelenen miktar kaydet'te güncellenir (rezervasyon takibi; stok değil).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.access import yazma_zorunlu
from database.models.cari import Cari
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import decimal

# Canonical status set (Turkish display with spaces where applicable)
IRSALIYE_DURUMLARI = (
    "TASLAK",
    "HAZIRLANIYOR",
    "SEVKİYATA HAZIR",
    "SEVK EDİLDİ",
    "KISMEN TESLİM EDİLDİ",
    "TESLİM EDİLDİ",
    "KISMİ FATURALANDI",
    "FATURALANDI",
    "İPTAL",
    "İADE",
)

# Legacy rows may still have AÇIK — treat as shipped-like editable display, stock not posted
LEGACY_DURUM_MAP = {
    "AÇIK": "SEVK EDİLDİ",  # display compatibility; stok_cikis_yapildi remains False until sevk
    "KISMİ FATURALANDI": "KISMİ FATURALANDI",
}

DUZENLENEBILIR_DURUMLAR = frozenset({"TASLAK", "HAZIRLANIYOR", "SEVKİYATA HAZIR", "AÇIK"})
SEVK_ONCESI = frozenset({"TASLAK", "HAZIRLANIYOR", "SEVKİYATA HAZIR", "AÇIK"})
SEVK_SONRASI = frozenset(
    {
        "SEVK EDİLDİ",
        "KISMEN TESLİM EDİLDİ",
        "TESLİM EDİLDİ",
        "KISMİ FATURALANDI",
        "FATURALANDI",
    }
)


def stok_cikis_gerekli(irsaliye) -> bool:
    """Fatura onayında stok çıkışı gerekir mi?

    İrsaliye zaten stok çıkışı yaptıysa False (fatura satırları için skip).
    Legacy AÇIK / stok_cikis_yapildi=False → True (eski fatura_cikisi davranışı).
    """
    if irsaliye is None:
        return True
    return not bool(getattr(irsaliye, "stok_cikis_yapildi", False))


def faturalanacak_kalan(satir: SatisIrsaliyesiSatiri) -> Decimal:
    return Decimal(str(satir.miktar or 0)) - Decimal(str(satir.faturalanan_miktar or 0))


def durum_gosterim(durum: str | None) -> str:
    """Legacy AÇIK → SEVK EDİLDİ görünen etiket (stok bayrağı ayrı)."""
    d = (durum or "").strip()
    return LEGACY_DURUM_MAP.get(d, d)


class SatisIrsaliyesiService:
    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text

        from database.database import engine

        import database.models.cari  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401

        if engine is None:
            return
        SatisIrsaliyesi.__table__.create(engine, checkfirst=True)
        SatisIrsaliyesiSatiri.__table__.create(engine, checkfirst=True)

        insp = inspect(engine)
        if insp.has_table("satis_irsaliyeleri"):
            mevcut = {c["name"] for c in insp.get_columns("satis_irsaliyeleri")}
            eklenecekler = {
                "belge_turu": "VARCHAR(40) DEFAULT 'SATIS_IRSALIYESI' NOT NULL",
                "depo": "VARCHAR(100) DEFAULT 'ANA DEPO' NOT NULL",
                "is_priced": "BOOLEAN DEFAULT 1 NOT NULL",
                "para_birimi": "VARCHAR(10) DEFAULT 'TRY'",
                "kur": "NUMERIC(18, 6) DEFAULT 1",
                "kur_tarihi": "DATE",
                "sevk_adresi": "VARCHAR(500)",
                "sevk_il": "VARCHAR(80)",
                "sevk_ilce": "VARCHAR(80)",
                "teslim_kisi": "VARCHAR(120)",
                "teslim_telefon": "VARCHAR(40)",
                "sevkiyat_yontemi": "VARCHAR(80)",
                "nakliyeci": "VARCHAR(120)",
                "arac_plaka": "VARCHAR(40)",
                "sofor_adi": "VARCHAR(120)",
                "sofor_telefon": "VARCHAR(40)",
                "takip_no": "VARCHAR(80)",
                "paket_sayisi": "NUMERIC(18, 4)",
                "net_agirlik": "NUMERIC(18, 4)",
                "brut_agirlik": "NUMERIC(18, 4)",
                "planlanan_teslim": "DATE",
                "fiili_sevk_tarihi": "DATE",
                "fiili_sevk_saati": "TIME",
                "fiili_teslim_tarihi": "DATE",
                "musteri_kodu_snap": "VARCHAR(50)",
                "musteri_unvan_snap": "VARCHAR(200)",
                "vergi_dairesi_snap": "VARCHAR(100)",
                "vergi_no_snap": "VARCHAR(40)",
                "musteri_notu": "TEXT",
                "sevk_notu": "TEXT",
                "depo_notu": "TEXT",
                "ic_not": "TEXT",
                "stok_cikis_yapildi": "BOOLEAN DEFAULT 0 NOT NULL",
                "stock_posted_at": "DATETIME",
                "quote_id": "INTEGER",
                "created_by_user_id": "INTEGER",
                "created_by_username": "VARCHAR(80)",
                "created_by_full_name": "VARCHAR(120)",
                "updated_by_user_id": "INTEGER",
                "updated_by_username": "VARCHAR(80)",
                "updated_by_full_name": "VARCHAR(120)",
                "updated_at": "DATETIME",
                "shipped_by_user_id": "INTEGER",
                "shipped_by_username": "VARCHAR(80)",
                "shipped_by_full_name": "VARCHAR(120)",
                "cancelled_by_user_id": "INTEGER",
                "cancelled_by_full_name": "VARCHAR(120)",
                "cancellation_reason": "VARCHAR(500)",
                "cancelled_at": "DATETIME",
                "approved_by_user_id": "INTEGER",
                "approved_by_full_name": "VARCHAR(120)",
                "approved_at": "DATETIME",
                "delivered_by_user_id": "INTEGER",
                "delivered_by_full_name": "VARCHAR(120)",
                "delivered_at": "DATETIME",
            }
            eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
            if eksikler:
                with engine.begin() as connection:
                    for alan, tip in eksikler.items():
                        connection.execute(
                            text(f'ALTER TABLE "satis_irsaliyeleri" ADD COLUMN "{alan}" {tip}')
                        )

        if insp.has_table("satis_irsaliyesi_satirlari"):
            mevcut = {c["name"] for c in insp.get_columns("satis_irsaliyesi_satirlari")}
            eklenecekler = {
                "depo": "VARCHAR(100)",
                "lot_no": "VARCHAR(80)",
                "siparis_miktar": "NUMERIC(18, 4)",
                "onceki_sevk": "NUMERIC(18, 4)",
            }
            eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
            if eksikler:
                with engine.begin() as connection:
                    for alan, tip in eksikler.items():
                        connection.execute(
                            text(
                                f'ALTER TABLE "satis_irsaliyesi_satirlari" ADD COLUMN "{alan}" {tip}'
                            )
                        )
        # Sipariş satırı manuel ürün kolonları — irsaliye açılışında selectinload için gerekli
        from database.satis_siparisi_service import SatisSiparisiService

        SatisSiparisiService.schema_hazirla()

    @staticmethod
    def _siparis_durumunu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        from database.satis_siparisi_service import SatisSiparisiService

        SatisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def _musteri_snap(session, irsaliye: SatisIrsaliyesi, cari_id: int) -> None:
        cari = session.get(Cari, cari_id)
        if not cari:
            return
        irsaliye.musteri_kodu_snap = cari.cari_kodu
        irsaliye.musteri_unvan_snap = cari.unvan
        irsaliye.vergi_dairesi_snap = getattr(cari, "vergi_dairesi", None)
        irsaliye.vergi_no_snap = getattr(cari, "vergi_numarasi", None) or getattr(
            cari, "tc_kimlik", None
        )

    @staticmethod
    def _header_alanlari(irsaliye: SatisIrsaliyesi, veriler: dict[str, Any]) -> None:
        for alan in (
            "depo",
            "sevk_adresi",
            "sevk_il",
            "sevk_ilce",
            "teslim_kisi",
            "teslim_telefon",
            "sevkiyat_yontemi",
            "nakliyeci",
            "arac_plaka",
            "sofor_adi",
            "sofor_telefon",
            "takip_no",
            "musteri_notu",
            "sevk_notu",
            "depo_notu",
            "ic_not",
            "para_birimi",
            "belge_turu",
        ):
            if alan in veriler:
                setattr(irsaliye, alan, veriler.get(alan) or getattr(irsaliye, alan, None))
        if "is_priced" in veriler:
            irsaliye.is_priced = bool(veriler["is_priced"])
        if "kur" in veriler and veriler["kur"] is not None:
            irsaliye.kur = decimal(veriler["kur"], "Kur", Decimal("0"))
        if "kur_tarihi" in veriler:
            irsaliye.kur_tarihi = veriler.get("kur_tarihi")
        if "planlanan_teslim" in veriler:
            irsaliye.planlanan_teslim = veriler.get("planlanan_teslim")
        if "paket_sayisi" in veriler and veriler["paket_sayisi"] not in (None, ""):
            irsaliye.paket_sayisi = decimal(veriler["paket_sayisi"], "Paket sayısı", Decimal("0"))
        if "net_agirlik" in veriler and veriler["net_agirlik"] not in (None, ""):
            irsaliye.net_agirlik = decimal(veriler["net_agirlik"], "Net ağırlık", Decimal("0"))
        if "brut_agirlik" in veriler and veriler["brut_agirlik"] not in (None, ""):
            irsaliye.brut_agirlik = decimal(veriler["brut_agirlik"], "Brüt ağırlık", Decimal("0"))
        if "quote_id" in veriler:
            irsaliye.quote_id = veriler.get("quote_id")
        if not getattr(irsaliye, "depo", None):
            irsaliye.depo = "ANA DEPO"
        if not getattr(irsaliye, "belge_turu", None):
            irsaliye.belge_turu = "SATIS_IRSALIYESI"

    @staticmethod
    def iptal_et(irsaliye_id: int, sebep: str | None = None) -> None:
        yazma_zorunlu("satis_duzenleme", "iptal")
        from database.stok_service import StokService
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_cancel,
        )

        reason = (sebep or "").strip()
        if not reason:
            raise ValueError("İptal nedeni zorunludur.")
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        with get_session() as session:
            irsaliye = session.scalar(
                select(SatisIrsaliyesi)
                .options(selectinload(SatisIrsaliyesi.satirlar))
                .where(SatisIrsaliyesi.id == irsaliye_id)
            )
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            if irsaliye.durum == "İPTAL":
                return
            if any(satir.faturalanan_miktar > 0 for satir in irsaliye.satirlar):
                raise ValueError("Faturalanmış irsaliye iptal edilemez.")
            for satir in irsaliye.satirlar:
                if satir.siparis_satiri_id:
                    siparis_satiri = session.get(SatisSiparisiSatiri, satir.siparis_satiri_id)
                    if siparis_satiri:
                        siparis_satiri.irsaliyelenen_miktar = max(
                            Decimal("0"), siparis_satiri.irsaliyelenen_miktar - satir.miktar
                        )
            if getattr(irsaliye, "stok_cikis_yapildi", False):
                StokService.irsaliye_cikis_iptal(session, irsaliye.irsaliye_no)
                irsaliye.stok_cikis_yapildi = False
                irsaliye.stock_posted_at = None
            irsaliye.durum = "İPTAL"
            stamp_cancel(irsaliye, reason)
            SatisIrsaliyesiService._siparis_durumunu_guncelle(session, irsaliye.siparis_id)
            iid = int(irsaliye.id)
            ino = irsaliye.irsaliye_no
        from database.deleted_record_service import ENTITY_SATIS_IRSALIYE, safe_log_cancel

        safe_log_cancel(ENTITY_SATIS_IRSALIYE, iid, note=f"Satış irsaliyesi iptal: {reason}")
        audit_document(
            "IRSALIYE_IPTAL",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
            aciklama=reason,
        )

    @staticmethod
    def aktif_musterileri() -> list[Cari]:
        with get_session() as session:
            return list(
                session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all()
            )

    @staticmethod
    def acik_siparisler() -> list[SatisSiparisi]:
        # Manuel ürün kolonları soft ALTER ile eklenir; yüklemeden önce şema hazır olmalı
        from database.satis_siparisi_service import SatisSiparisiService

        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            return list(
                session.scalars(
                    select(SatisSiparisi)
                    .where(SatisSiparisi.durum != "İPTAL")
                    .options(
                        selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.cari)
                    )
                    .order_by(SatisSiparisi.id.desc())
                ).all()
            )

    @staticmethod
    def depolar() -> list[str]:
        from database.stok_service import StokService

        try:
            return [d.ad for d in StokService.depolar()]
        except Exception:
            return ["ANA DEPO"]

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        SatisIrsaliyesiService.schema_hazirla()
        with get_session() as session:
            irsaliyeler = session.scalars(
                select(SatisIrsaliyesi)
                .options(
                    selectinload(SatisIrsaliyesi.cari),
                    selectinload(SatisIrsaliyesi.siparis),
                    selectinload(SatisIrsaliyesi.satirlar),
                )
                .order_by(SatisIrsaliyesi.id.desc())
            ).all()
            sonuc = []
            for irsaliye in irsaliyeler:
                toplam = SatisIrsaliyesiService.toplam(irsaliye.satirlar)
                faturalanan = sum(
                    (satir.faturalanan_miktar * satir.birim_fiyat for satir in irsaliye.satirlar),
                    Decimal("0"),
                )
                sevk_miktar = sum(
                    (Decimal(str(satir.miktar or 0)) for satir in irsaliye.satirlar),
                    Decimal("0"),
                )
                fatura_miktar = sum(
                    (Decimal(str(satir.faturalanan_miktar or 0)) for satir in irsaliye.satirlar),
                    Decimal("0"),
                )
                sonuc.append(
                    {
                        "irsaliye": irsaliye,
                        "toplam": toplam["genel_toplam"],
                        "faturalanan": faturalanan,
                        "kalan": toplam["genel_toplam"] - faturalanan,
                        "sevk_miktar": sevk_miktar,
                        "fatura_miktar": fatura_miktar,
                        "fatura_kalani_miktar": sevk_miktar - fatura_miktar,
                    }
                )
            return sonuc

    @staticmethod
    def getir(irsaliye_id: int) -> SatisIrsaliyesi | None:
        SatisIrsaliyesiService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatisIrsaliyesi)
                .options(
                    selectinload(SatisIrsaliyesi.satirlar),
                    selectinload(SatisIrsaliyesi.cari),
                    selectinload(SatisIrsaliyesi.siparis),
                )
                .where(SatisIrsaliyesi.id == irsaliye_id)
            )

    @staticmethod
    def siparis_satirlari(siparis_id: int) -> list[SatisSiparisiSatiri]:
        with get_session() as session:
            siparis = session.get(SatisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            return [satir for satir in siparis.satirlar if satir.miktar - satir.irsaliyelenen_miktar > 0]

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        irsaliye_id: int | None = None,
    ) -> SatisIrsaliyesi:
        """TASLAK kaydı — stok çıkışı yapmaz.

        Sipariş irsaliyelenen miktar burada güncellenir (açık miktar takibi; stok rezervasyonu değil).
        """
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        SatisIrsaliyesiService.schema_hazirla()
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_create,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        irsaliye_tarihi = veriler["irsaliye_tarihi"]
        if irsaliye_tarihi > date.today():
            raise ValueError("İrsaliye tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            if irsaliye_id:
                irsaliye = session.get(SatisIrsaliyesi, irsaliye_id)
                if irsaliye is None:
                    raise ValueError("İrsaliye bulunamadı.")
                if irsaliye.durum == "İPTAL":
                    raise ValueError("İptal edilmiş irsaliye düzenlenemez.")
                if getattr(irsaliye, "stok_cikis_yapildi", False):
                    raise ValueError("Sevk edilmiş irsaliye satırları düzenlenemez. Önce iptal edin.")
                if any(satir.faturalanan_miktar > 0 for satir in irsaliye.satirlar):
                    raise ValueError("Faturalanmış irsaliye satırı düzenlenemez.")
                for eski_satir in irsaliye.satirlar:
                    if eski_satir.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, eski_satir.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.irsaliyelenen_miktar -= eski_satir.miktar
                irsaliye.satirlar.clear()
                yeni = False
            else:
                ozel_no = (veriler.get("irsaliye_no") or "").strip()
                irsaliye = SatisIrsaliyesi(
                    irsaliye_no=ozel_no or SatisIrsaliyesiService.irsaliye_no(),
                    durum="TASLAK",
                    belge_turu="SATIS_IRSALIYESI",
                    depo=veriler.get("depo") or "ANA DEPO",
                    stok_cikis_yapildi=False,
                )
                session.add(irsaliye)
                yeni = True
            irsaliye.irsaliye_tarihi = irsaliye_tarihi
            irsaliye.cari_id = int(veriler["cari_id"])
            irsaliye.siparis_id = veriler.get("siparis_id")
            irsaliye.aciklama = veriler.get("aciklama")
            irsaliye.ayrintili_notlar = veriler.get("ayrintili_notlar")
            SatisIrsaliyesiService._header_alanlari(irsaliye, veriler)
            SatisIrsaliyesiService._musteri_snap(session, irsaliye, irsaliye.cari_id)
            # Taslak / hazırlık durumunda durum korunur veya TASLAK'a çekilir (legacy AÇIK düzenlemede TASLAK)
            if irsaliye.durum in ("AÇIK",) or not irsaliye.durum:
                if not getattr(irsaliye, "stok_cikis_yapildi", False):
                    irsaliye.durum = "TASLAK"
            if irsaliye.durum not in IRSALIYE_DURUMLARI and irsaliye.durum != "AÇIK":
                irsaliye.durum = "TASLAK"

            header_depo = getattr(irsaliye, "depo", None) or "ANA DEPO"
            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "İrsaliye miktarı", Decimal("0.0001"))
                siparis_satiri_id = veri.get("siparis_satiri_id")
                siparis_miktar = None
                onceki_sevk = None
                if siparis_satiri_id:
                    siparis_satiri = session.get(SatisSiparisiSatiri, int(siparis_satiri_id))
                    if siparis_satiri is None:
                        raise ValueError("Bağlı sipariş satırı bulunamadı.")
                    acik = siparis_satiri.miktar - siparis_satiri.irsaliyelenen_miktar
                    if miktar > acik:
                        raise ValueError("İrsaliye miktarı siparişin açık miktarından büyük olamaz.")
                    siparis_satiri.irsaliyelenen_miktar += miktar
                    siparis_miktar = siparis_satiri.miktar
                    onceki_sevk = siparis_satiri.irsaliyelenen_miktar - miktar
                irsaliye.satirlar.append(
                    SatisIrsaliyesiSatiri(
                        irsaliye_id=irsaliye.id if irsaliye.id else None,
                        siparis_satiri_id=siparis_satiri_id,
                        urun_kodu=veri["urun_kodu"],
                        urun_adi=veri["urun_adi"],
                        aciklama=veri.get("aciklama"),
                        miktar=miktar,
                        birim=veri["birim"],
                        birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                        iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")),
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        faturalanan_miktar=Decimal("0"),
                        depo=veri.get("depo") or header_depo,
                        lot_no=(veri.get("lot_no") or "") or None,
                        siparis_miktar=siparis_miktar
                        if siparis_miktar is not None
                        else (
                            decimal(veri["siparis_miktar"], "Sipariş miktar", Decimal("0"))
                            if veri.get("siparis_miktar") not in (None, "")
                            else None
                        ),
                        onceki_sevk=onceki_sevk
                        if onceki_sevk is not None
                        else (
                            decimal(veri["onceki_sevk"], "Önceki sevk", Decimal("0"))
                            if veri.get("onceki_sevk") not in (None, "")
                            else None
                        ),
                    )
                )
            if not irsaliye.satirlar:
                raise ValueError("En az bir irsaliye satırı ekleyin.")
            if yeni:
                stamp_create(irsaliye)
            else:
                stamp_update(irsaliye)
            SatisIrsaliyesiService._siparis_durumunu_guncelle(session, irsaliye.siparis_id)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("İrsaliye kaydedilemedi.") from hata
            iid = int(irsaliye.id)
            ino = irsaliye.irsaliye_no
        audit_document(
            "IRSALIYE_KAYDET",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
            aciklama="TASLAK — stok çıkışı yok",
        )
        return SatisIrsaliyesiService.getir(iid)

    @staticmethod
    def hazirla(irsaliye_id: int, hedef: str = "SEVKİYATA HAZIR") -> SatisIrsaliyesi:
        yazma_zorunlu("satis_duzenleme")
        from database.user_audit import audit_document, stamp_update

        hedef = (hedef or "SEVKİYATA HAZIR").strip()
        if hedef not in ("HAZIRLANIYOR", "SEVKİYATA HAZIR"):
            raise ValueError("Geçersiz hazırlık durumu.")
        with get_session() as session:
            irsaliye = session.scalar(
                select(SatisIrsaliyesi)
                .options(selectinload(SatisIrsaliyesi.satirlar))
                .where(SatisIrsaliyesi.id == irsaliye_id)
            )
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            if irsaliye.durum == "İPTAL":
                raise ValueError("İptal edilmiş irsaliye hazırlanamaz.")
            if getattr(irsaliye, "stok_cikis_yapildi", False):
                raise ValueError("Sevk edilmiş irsaliye tekrar hazırlanamaz.")
            if irsaliye.durum not in SEVK_ONCESI:
                raise ValueError(f"Bu durumda hazırlık yapılamaz: {irsaliye.durum}")
            if not irsaliye.satirlar:
                raise ValueError("Satır olmayan irsaliye hazırlanamaz.")
            irsaliye.durum = hedef
            stamp_update(irsaliye)
            iid = int(irsaliye.id)
            ino = irsaliye.irsaliye_no
        audit_document(
            "IRSALIYE_HAZIRLA",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
            aciklama=hedef,
        )
        return SatisIrsaliyesiService.getir(iid)

    @staticmethod
    def sevk_et(irsaliye_id: int) -> SatisIrsaliyesi:
        """Stok çıkışı oluşturur (İRSALİYE ÇIKIŞ) ve SEVK EDİLDİ yapar."""
        yazma_zorunlu("satis_duzenleme")
        SatisIrsaliyesiService.schema_hazirla()
        from database.stok_service import StokService
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            current_actor,
            require_user_session,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        with get_session() as session:
            irsaliye = session.scalar(
                select(SatisIrsaliyesi)
                .options(selectinload(SatisIrsaliyesi.satirlar))
                .where(SatisIrsaliyesi.id == irsaliye_id)
            )
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            if irsaliye.durum == "İPTAL":
                raise ValueError("İptal edilmiş irsaliye sevk edilemez.")
            if getattr(irsaliye, "stok_cikis_yapildi", False):
                raise ValueError("Bu irsaliye için stok çıkışı zaten yapılmış.")
            if irsaliye.durum in ("FATURALANDI", "KISMİ FATURALANDI") and not getattr(
                irsaliye, "stok_cikis_yapildi", False
            ):
                pass  # legacy faturalı ama stoksuz — allow posting stock once
            elif irsaliye.durum not in SEVK_ONCESI and irsaliye.durum != "SEVK EDİLDİ":
                if irsaliye.durum in SEVK_SONRASI:
                    raise ValueError("Bu irsaliye zaten sevk sürecinde.")
            if not irsaliye.satirlar:
                raise ValueError("Satır olmayan irsaliye sevk edilemez.")
            depo = (getattr(irsaliye, "depo", None) or "ANA DEPO").strip()
            if not depo:
                raise ValueError("Depo seçilmeden sevk yapılamaz.")
            tarih = irsaliye.irsaliye_tarihi
            for satir in irsaliye.satirlar:
                satir_depo = (getattr(satir, "depo", None) or depo).strip()
                kod = (satir.urun_kodu or "").strip()
                line_type = (getattr(satir, "line_type", None) or "").upper()
                # Hizmet / stok takibi yok — stok hareketi oluşturma
                if (
                    bool(getattr(satir, "hizmet_satiri", False))
                    or line_type in ("SERVICE", "NON_STOCK_ITEM")
                    or (satir.birim or "").casefold() == "hizmet"
                ):
                    continue
                # Manuel / stok bekleyen fiziksel ürün — sahte çıkış yok
                if (
                    kod.upper() in ("MANUEL", "OZEL")
                    or bool(getattr(satir, "is_manual_item", False))
                    or bool(getattr(satir, "stock_pending", False))
                ):
                    raise ValueError(
                        f"'{satir.urun_adi or kod}' stok kartına bağlanmamış. "
                        "Sevkiyat ve stok işlemlerinden önce ürünün stok kartına bağlanması gerekir. "
                        "Sahte stok hareketi oluşturulmaz."
                    )
                try:
                    StokService.irsaliye_cikisi(
                        session,
                        irsaliye.irsaliye_no,
                        tarih,
                        satir.urun_kodu.strip(),
                        satir_depo,
                        satir.miktar,
                        getattr(satir, "lot_no", None) or "",
                    )
                except ValueError as hata:
                    mesaj = str(hata)
                    if "yetersiz" in mesaj.casefold():
                        raise ValueError(
                            f"Sevk yapılamadı — eksi stoka izin yok.\n{mesaj}"
                        ) from hata
                    raise ValueError(f"Sevk yapılamadı.\n{mesaj}") from hata
            actor = current_actor()
            irsaliye.stok_cikis_yapildi = True
            irsaliye.stock_posted_at = actor["now"]
            irsaliye.shipped_by_user_id = actor["user_id"]
            irsaliye.shipped_by_username = actor["username"]
            irsaliye.shipped_by_full_name = actor["full_name"]
            irsaliye.fiili_sevk_tarihi = date.today()
            irsaliye.fiili_sevk_saati = datetime.now().time().replace(microsecond=0)
            if irsaliye.durum not in ("KISMİ FATURALANDI", "FATURALANDI"):
                irsaliye.durum = "SEVK EDİLDİ"
            stamp_update(irsaliye)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Sevk kaydedilemedi.") from hata
            iid = int(irsaliye.id)
            ino = irsaliye.irsaliye_no
        audit_document(
            "IRSALIYE_SEVK",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
            aciklama="Stok çıkışı (İRSALİYE ÇIKIŞ)",
        )
        return SatisIrsaliyesiService.getir(iid)

    @staticmethod
    def teslim_et(irsaliye_id: int, kismen: bool = False) -> SatisIrsaliyesi:
        yazma_zorunlu("satis_duzenleme")
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            current_actor,
            require_user_session,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        with get_session() as session:
            irsaliye = session.get(SatisIrsaliyesi, irsaliye_id)
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            if irsaliye.durum == "İPTAL":
                raise ValueError("İptal edilmiş irsaliye teslim edilemez.")
            if not getattr(irsaliye, "stok_cikis_yapildi", False) and irsaliye.durum not in (
                "SEVK EDİLDİ",
                "KISMEN TESLİM EDİLDİ",
                "AÇIK",
            ):
                raise ValueError("Önce sevk işlemi yapılmalıdır.")
            actor = current_actor()
            irsaliye.durum = "KISMEN TESLİM EDİLDİ" if kismen else "TESLİM EDİLDİ"
            irsaliye.fiili_teslim_tarihi = date.today()
            irsaliye.delivered_by_user_id = actor["user_id"]
            irsaliye.delivered_by_full_name = actor["full_name"]
            irsaliye.delivered_at = actor["now"]
            stamp_update(irsaliye)
            iid = int(irsaliye.id)
            ino = irsaliye.irsaliye_no
        audit_document(
            "IRSALIYE_TESLIM",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
        )
        return SatisIrsaliyesiService.getir(iid)

    @staticmethod
    def iade_olustur(
        kaynak_irsaliye_id: int,
        satir_secimleri: list[dict[str, Any]] | None = None,
    ) -> SatisIrsaliyesi:
        """Minimal iade: kaynak irsaliyeden seçili satırlarla İADE belgesi + stok giriş.

        satir_secimleri: [{"irsaliye_satiri_id": int, "miktar": Decimal}, ...]
        Boşsa tüm satırlar tam miktarla iade edilir.
        """
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        SatisIrsaliyesiService.schema_hazirla()
        from database.stok_service import StokService
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_create,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        with get_session() as session:
            kaynak = session.scalar(
                select(SatisIrsaliyesi)
                .options(selectinload(SatisIrsaliyesi.satirlar), selectinload(SatisIrsaliyesi.cari))
                .where(SatisIrsaliyesi.id == kaynak_irsaliye_id)
            )
            if kaynak is None:
                raise ValueError("Kaynak irsaliye bulunamadı.")
            if not getattr(kaynak, "stok_cikis_yapildi", False):
                raise ValueError("Sevk edilmemiş irsaliyeden iade oluşturulamaz.")
            secim_map: dict[int, Decimal] = {}
            if satir_secimleri:
                for s in satir_secimleri:
                    secim_map[int(s["irsaliye_satiri_id"])] = decimal(
                        s["miktar"], "İade miktarı", Decimal("0.0001")
                    )
            iade = SatisIrsaliyesi(
                irsaliye_no=SatisIrsaliyesiService.irsaliye_no("IAD"),
                irsaliye_tarihi=date.today(),
                cari_id=kaynak.cari_id,
                siparis_id=kaynak.siparis_id,
                durum="İADE",
                belge_turu="IADE",
                depo=getattr(kaynak, "depo", None) or "ANA DEPO",
                is_priced=bool(getattr(kaynak, "is_priced", True)),
                stok_cikis_yapildi=False,
                aciklama=f"İade — kaynak {kaynak.irsaliye_no}",
            )
            session.add(iade)
            session.flush()
            SatisIrsaliyesiService._musteri_snap(session, iade, iade.cari_id)
            depo = iade.depo
            for satir in kaynak.satirlar:
                miktar = secim_map.get(satir.id, satir.miktar if not secim_map else None)
                if miktar is None:
                    continue
                if miktar <= 0:
                    continue
                if miktar > satir.miktar:
                    raise ValueError("İade miktarı orijinal miktarı aşamaz.")
                iade.satirlar.append(
                    SatisIrsaliyesiSatiri(
                        irsaliye_id=iade.id,
                        siparis_satiri_id=None,
                        urun_kodu=satir.urun_kodu,
                        urun_adi=satir.urun_adi,
                        aciklama=satir.aciklama,
                        miktar=miktar,
                        birim=satir.birim,
                        birim_fiyat=satir.birim_fiyat,
                        iskonto_orani=satir.iskonto_orani,
                        kdv_orani=satir.kdv_orani,
                        faturalanan_miktar=Decimal("0"),
                        depo=getattr(satir, "depo", None) or depo,
                        lot_no=getattr(satir, "lot_no", None),
                    )
                )
                StokService.irsaliye_iade_girisi(
                    session,
                    iade.irsaliye_no,
                    iade.irsaliye_tarihi,
                    satir.urun_kodu.strip(),
                    getattr(satir, "depo", None) or depo,
                    miktar,
                    lot_no=getattr(satir, "lot_no", None) or "",
                )
            if not iade.satirlar:
                raise ValueError("İade için en az bir satır seçin.")
            stamp_create(iade)
            session.flush()
            iid = int(iade.id)
            ino = iade.irsaliye_no
        audit_document(
            "IRSALIYE_IADE",
            modul="satis_irsaliyesi",
            kayit_id=str(iid),
            belge_no=ino,
            aciklama=f"Kaynak #{kaynak_irsaliye_id}",
        )
        return SatisIrsaliyesiService.getir(iid)

    @staticmethod
    def faturaya_aktarilabilir_miktar(satir: SatisIrsaliyesiSatiri) -> Decimal:
        return faturalanacak_kalan(satir)

    @staticmethod
    def faturalanan_miktar_artir(irsaliye_satiri_id: int, miktar: Decimal, belge_baglantisi: str) -> None:
        with get_session() as session:
            satir = session.get(SatisIrsaliyesiSatiri, irsaliye_satiri_id)
            if satir is None:
                raise ValueError("İrsaliye satırı bulunamadı.")
            miktar = decimal(miktar, "Faturalanan miktar", Decimal("0.0001"))
            if miktar > SatisIrsaliyesiService.faturaya_aktarilabilir_miktar(satir):
                raise ValueError("Faturalanan miktar kalan miktardan büyük olamaz.")
            satir.faturalanan_miktar += miktar
            satir.fatura_belge_baglantisi = belge_baglantisi
            irsaliye = session.get(SatisIrsaliyesi, satir.irsaliye_id)
            if irsaliye:
                irsaliye.durum = (
                    "FATURALANDI"
                    if all(
                        SatisIrsaliyesiService.faturaya_aktarilabilir_miktar(item) <= 0
                        for item in irsaliye.satirlar
                    )
                    else "KISMİ FATURALANDI"
                )

    @staticmethod
    def irsaliye_no(onek: str = "IRS") -> str:
        return f"{onek}-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def toplam(satirlar: list[SatisIrsaliyesiSatiri]) -> dict[str, Decimal]:
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        for satir in satirlar:
            brut = satir.miktar * satir.birim_fiyat
            indirim = brut * satir.iskonto_orani / Decimal("100")
            ara += brut
            iskonto += indirim
            kdv += (brut - indirim) * satir.kdv_orani / Decimal("100")
        return {
            "ara_toplam": ara,
            "iskonto": iskonto,
            "kdv": kdv,
            "genel_toplam": ara - iskonto + kdv,
        }

    @staticmethod
    def mevcut_bakiye(cari_id: int) -> Decimal:
        ozet = next((item for item in CariService.listele(hizli=True) if item["cari"].id == cari_id), None)
        return ozet["bakiye"] if ozet else Decimal("0")
