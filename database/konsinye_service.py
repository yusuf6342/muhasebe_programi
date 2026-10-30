"""Konsinye teslim / bildirim / iade servisi.

Teslim tek başına cari borç yazmaz. Stok, onayda kaynak depodan
konsinye sanal konumuna (VERILEN) veya tersine (ALINAN) taşınır.
Yeniden baskı / liste stok miktarını değiştirmez.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from database.database import Base, engine, get_session
from database.models.konsinye import KonsinyeHareket, KonsinyeTeslim, KonsinyeTeslimSatiri
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.stok_service import StokService, decimal

logger = logging.getLogger(__name__)

YON_VERILEN = "VERILEN"
YON_ALINAN = "ALINAN"
DURUM_TASLAK = "TASLAK"
DURUM_ONAYLI = "ONAYLI"
DURUM_KAPALI = "KAPALI"
DURUM_IPTAL = "IPTAL"

H_SATIS = "SATIS_BILDIRIM"
H_IADE = "IADE"
H_FATURA_TASLAK = "FATURA_TASLAK"
H_FATURA_ONAY = "FATURA_ONAY"

KONSINYE_DEPO_ONEK = "KONSİNYE:"


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.kullanici_adi or oturum.ad_soyad or None
    except Exception:  # noqa: BLE001
        return None


class KonsinyeService:
    _schema_hazir = False

    @staticmethod
    def ensure_schema() -> None:
        if KonsinyeService._schema_hazir:
            return
        if engine is None:
            return
        import database.models.konsinye  # noqa: F401

        Base.metadata.create_all(
            bind=engine,
            tables=[
                KonsinyeTeslim.__table__,
                KonsinyeTeslimSatiri.__table__,
                KonsinyeHareket.__table__,
            ],
        )
        KonsinyeService._schema_hazir = True

    @staticmethod
    def _belge_no(session, yon: str) -> str:
        onek = "KV" if yon == YON_VERILEN else "KA"
        son = session.scalar(
            select(func.max(KonsinyeTeslim.id)).where(KonsinyeTeslim.yon == yon)
        ) or 0
        return f"{onek}{int(son) + 1:06d}"

    @staticmethod
    def konsinye_depo_adi(cari_unvan: str, yon: str) -> str:
        kisalt = (cari_unvan or "CARİ").strip()[:40]
        yon_etiket = "MÜŞTERİ" if yon == YON_VERILEN else "TEDARİKÇİ"
        return f"{KONSINYE_DEPO_ONEK}{yon_etiket}:{kisalt}"

    @staticmethod
    def sanal_depo_mu(depo_ad: str | None) -> bool:
        return (depo_ad or "").strip().upper().startswith(KONSINYE_DEPO_ONEK)

    @staticmethod
    def _konsinye_depo_al_veya_olustur(session, cari, yon: str) -> Depo:
        ad = KonsinyeService.konsinye_depo_adi(getattr(cari, "unvan", "") or "", yon)
        depo = session.scalar(select(Depo).where(Depo.ad == ad))
        if depo is None:
            depo = Depo(
                ad=ad,
                aktif=True,
                varsayilan=False,
                aciklama="KONSINYE_SANAL — satılabilir stok sayılmaz",
            )
            session.add(depo)
            session.flush()
        return depo

    @staticmethod
    def teslim_kaydet(
        *,
        yon: str,
        cari_id: int,
        depo_id: int,
        belge_tarihi: date,
        satirlar: list[dict[str, Any]],
        aciklama: str | None = None,
        teslim_id: int | None = None,
        onayla: bool = False,
    ) -> dict[str, Any]:
        """Taslak kaydet; onayla=True ise stok hareketi üretir (cari borç yok)."""
        KonsinyeService.ensure_schema()
        if yon not in (YON_VERILEN, YON_ALINAN):
            raise ValueError("Yön VERILEN veya ALINAN olmalı.")
        if not satirlar:
            raise ValueError("En az bir satır ekleyin.")
        with get_session() as session:
            from database.models.cari import Cari

            cari = session.get(Cari, int(cari_id))
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            kaynak_depo = session.get(Depo, int(depo_id))
            if kaynak_depo is None:
                raise ValueError("Depo bulunamadı.")

            if teslim_id:
                teslim = session.get(KonsinyeTeslim, int(teslim_id))
                if teslim is None:
                    raise ValueError("Teslim bulunamadı.")
                if teslim.durum != DURUM_TASLAK:
                    raise ValueError("Yalnız taslak teslim düzenlenebilir.")
                teslim.satirlar.clear()
            else:
                teslim = KonsinyeTeslim(
                    belge_no=KonsinyeService._belge_no(session, yon),
                    yon=yon,
                    durum=DURUM_TASLAK,
                    belge_tarihi=belge_tarihi,
                    cari_id=int(cari_id),
                    depo_id=int(depo_id),
                    olusturan=_kullanici(),
                )
                session.add(teslim)
                session.flush()

            teslim.belge_tarihi = belge_tarihi
            teslim.cari_id = int(cari_id)
            teslim.depo_id = int(depo_id)
            teslim.aciklama = (aciklama or "").strip() or None

            for s in satirlar:
                stok = session.scalar(
                    select(StokKarti).where(StokKarti.stok_kodu == (s.get("stok_kodu") or "").strip())
                )
                if stok is None:
                    raise ValueError(f"Stok yok: {s.get('stok_kodu')}")
                birim = (s.get("birim") or stok.birim or "Adet").strip() or "Adet"
                carpan = Decimal(str(StokService.birim_carpani_kesin(stok, birim) or 1))
                miktar = decimal(s.get("miktar") or 0, "Miktar", Decimal("0.0001"))
                temel = (miktar * carpan).quantize(Decimal("0.0001"))
                teslim.satirlar.append(
                    KonsinyeTeslimSatiri(
                        stok_id=int(stok.id),
                        stok_kodu=stok.stok_kodu,
                        stok_adi=stok.stok_adi or stok.stok_kodu,
                        birim=birim,
                        birim_carpani=carpan,
                        miktar=miktar,
                        temel_miktar=temel,
                        birim_fiyat=decimal(s.get("birim_fiyat") or 0, "Fiyat", Decimal("0")),
                        lot_id=s.get("lot_id"),
                        lot_no=(s.get("lot_no") or None),
                        kalan_miktar=temel,
                        bildirilen_miktar=Decimal("0"),
                        faturalanan_miktar=Decimal("0"),
                        iade_miktar=Decimal("0"),
                    )
                )
            session.flush()

            if onayla:
                KonsinyeService._teslim_onayla(session, teslim)
            return KonsinyeService._teslim_ozet(session, teslim)

    @staticmethod
    def _teslim_onayla(session, teslim: KonsinyeTeslim) -> None:
        from database.models.cari import Cari

        if teslim.durum != DURUM_TASLAK:
            raise ValueError("Teslim zaten onaylı veya kapalı.")
        cari = session.get(Cari, teslim.cari_id)
        kaynak = session.get(Depo, teslim.depo_id)
        hedef = KonsinyeService._konsinye_depo_al_veya_olustur(session, cari, teslim.yon)

        for satir in teslim.satirlar:
            miktar = Decimal(str(satir.temel_miktar))
            if teslim.yon == YON_VERILEN:
                # Kendi stokumuz → müşteri konsinye konumu (cari borç yok)
                KonsinyeService._kaynaktan_cikis(
                    session, teslim, satir, kaynak, miktar
                )
                KonsinyeService._hedefe_giris(session, teslim, satir, hedef, miktar)
            else:
                # Tedarikçi malı mağazamıza (konsinye alınan) — tedarikçiye borç yok
                KonsinyeService._hedefe_giris(session, teslim, satir, kaynak, miktar)

        teslim.durum = DURUM_ONAYLI
        teslim.onay_tarihi = datetime.now()
        teslim.onaylayan = _kullanici()
        session.flush()

    @staticmethod
    def _kaynaktan_cikis(session, teslim, satir, kaynak_depo: Depo, miktar: Decimal) -> None:
        stok = session.get(StokKarti, satir.stok_id)
        if stok is None:
            raise ValueError("Stok bulunamadı.")
        q = select(StokLotu).where(
            StokLotu.stok_id == stok.id,
            StokLotu.depo_id == kaynak_depo.id,
            StokLotu.kalan_miktar > 0,
        )
        if satir.lot_no:
            q = q.where(StokLotu.lot_no == satir.lot_no)
        lotlar = list(session.scalars(q.order_by(StokLotu.giris_tarihi, StokLotu.id)).all())
        mevcut = sum((Decimal(str(l.kalan_miktar or 0)) for l in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{satir.stok_adi}: {kaynak_depo.ad} stok yetersiz "
                f"(mevcut {mevcut}, istenen {miktar})."
            )
        kalan = miktar
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, Decimal(str(lot.kalan_miktar or 0)))
            lot.kalan_miktar = Decimal(str(lot.kalan_miktar)) - cikan
            kalan -= cikan
            session.add(
                StokHareketi(
                    tarih=teslim.belge_tarihi,
                    hareket_turu="TRANSFER ÇIKIŞ",
                    belge_no=teslim.belge_no,
                    stok_id=stok.id,
                    depo_id=kaynak_depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=lot.birim_maliyet,
                )
            )

    @staticmethod
    def _hedefe_giris(session, teslim, satir, hedef_depo: Depo, miktar: Decimal) -> None:
        stok = session.get(StokKarti, satir.stok_id)
        if stok is None:
            raise ValueError("Stok bulunamadı.")
        lot_no = (satir.lot_no or "").strip() or f"{teslim.belge_no}-{satir.id}"
        lot = session.scalar(
            select(StokLotu).where(
                StokLotu.stok_id == stok.id,
                StokLotu.depo_id == hedef_depo.id,
                StokLotu.lot_no == lot_no,
            )
        )
        if lot is None:
            lot = StokLotu(
                stok_id=stok.id,
                depo_id=hedef_depo.id,
                lot_no=lot_no,
                tedarikci=f"KONSİNYE {teslim.belge_no}",
                giris_tarihi=teslim.belge_tarihi,
                kalan_miktar=Decimal("0"),
                birim_maliyet=Decimal(str(satir.birim_fiyat or 0)),
            )
            session.add(lot)
            session.flush()
        lot.kalan_miktar = Decimal(str(lot.kalan_miktar or 0)) + miktar
        session.add(
            StokHareketi(
                tarih=teslim.belge_tarihi,
                hareket_turu="TRANSFER GİRİŞ",
                belge_no=teslim.belge_no,
                stok_id=stok.id,
                depo_id=hedef_depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=lot.birim_maliyet,
            )
        )
        satir.lot_id = lot.id
        satir.lot_no = lot.lot_no

    @staticmethod
    def teslim_onayla(teslim_id: int) -> dict[str, Any]:
        KonsinyeService.ensure_schema()
        with get_session() as session:
            teslim = session.get(KonsinyeTeslim, int(teslim_id))
            if teslim is None:
                raise ValueError("Teslim bulunamadı.")
            KonsinyeService._teslim_onayla(session, teslim)
            return KonsinyeService._teslim_ozet(session, teslim)

    @staticmethod
    def satis_bildir(
        *,
        teslim_satiri_id: int,
        miktar: Decimal | str | float,
        gercek_tarih: date | None = None,
        aciklama: str | None = None,
    ) -> dict[str, Any]:
        """Müşteri satıldığını bildirdi — kalan ↓, bildirilen ↑; cari borç yok."""
        KonsinyeService.ensure_schema()
        miktar_d = decimal(miktar, "Bildirim miktarı", Decimal("0.0001"))
        with get_session() as session:
            satir = session.get(KonsinyeTeslimSatiri, int(teslim_satiri_id))
            if satir is None:
                raise ValueError("Teslim satırı bulunamadı.")
            teslim = session.get(KonsinyeTeslim, satir.teslim_id)
            if teslim is None or teslim.durum != DURUM_ONAYLI:
                raise ValueError("Yalnız onaylı teslimde bildirim yapılır.")
            if teslim.yon != YON_VERILEN:
                raise ValueError("Satış bildirimi yalnız verilen konsinyede.")
            kalan = Decimal(str(satir.kalan_miktar or 0))
            if miktar_d > kalan:
                raise ValueError(f"Bildirim kalanı aşıyor (kalan: {kalan}).")
            satir.kalan_miktar = kalan - miktar_d
            satir.bildirilen_miktar = Decimal(str(satir.bildirilen_miktar or 0)) + miktar_d
            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_SATIS,
                    miktar=miktar_d,
                    gercek_tarih=gercek_tarih or date.today(),
                    aciklama=(aciklama or "").strip() or None,
                    olusturan=_kullanici(),
                )
            )
            # Fiziksel: konsinye depodan düş (satıldı)
            if satir.lot_id:
                lot = session.get(StokLotu, satir.lot_id)
                if lot is not None:
                    if Decimal(str(lot.kalan_miktar or 0)) < miktar_d:
                        raise ValueError("Konsinye konumunda stok yetersiz.")
                    lot.kalan_miktar = Decimal(str(lot.kalan_miktar)) - miktar_d
                    session.add(
                        StokHareketi(
                            tarih=gercek_tarih or date.today(),
                            hareket_turu="ÇIKIŞ",
                            belge_no=f"{teslim.belge_no}-BILDIR",
                            stok_id=satir.stok_id,
                            depo_id=lot.depo_id,
                            lot_id=lot.id,
                            miktar=miktar_d,
                            birim_maliyet=lot.birim_maliyet,
                        )
                    )
            session.flush()
            KonsinyeService._teslim_durum_guncelle(session, teslim)
            return KonsinyeService._satir_ozet(satir)

    @staticmethod
    def iade_al(
        *,
        teslim_satiri_id: int,
        miktar: Decimal | str | float,
        hedef_depo_id: int | None = None,
        aciklama: str | None = None,
    ) -> dict[str, Any]:
        """Satılmamış malın geri alınması — bildirilen/faturalanan iade edilemez.

        VERILEN: müşteri konsinye konumundan bizim depoya.
        ALINAN: mağazadaki tedarikçi malını tedarikçiye iade (fiziksel çıkış).
        """
        KonsinyeService.ensure_schema()
        miktar_d = decimal(miktar, "İade miktarı", Decimal("0.0001"))
        with get_session() as session:
            satir = session.get(KonsinyeTeslimSatiri, int(teslim_satiri_id))
            if satir is None:
                raise ValueError("Teslim satırı bulunamadı.")
            teslim = session.get(KonsinyeTeslim, satir.teslim_id)
            if teslim is None or teslim.durum != DURUM_ONAYLI:
                raise ValueError("Yalnız onaylı teslimde iade yapılır.")
            kalan = Decimal(str(satir.kalan_miktar or 0))
            if miktar_d > kalan:
                raise ValueError(f"İade kalanı aşıyor (kalan: {kalan}).")
            satir.kalan_miktar = kalan - miktar_d
            satir.iade_miktar = Decimal(str(satir.iade_miktar or 0)) + miktar_d

            if teslim.yon == YON_VERILEN:
                hedef_id = int(hedef_depo_id or teslim.depo_id)
                hedef = session.get(Depo, hedef_id)
                if hedef is None:
                    raise ValueError("Hedef depo yok.")
                if satir.lot_id:
                    lot = session.get(StokLotu, satir.lot_id)
                    if lot is not None:
                        if Decimal(str(lot.kalan_miktar or 0)) < miktar_d:
                            raise ValueError("Konsinye konumunda stok yetersiz.")
                        lot.kalan_miktar = Decimal(str(lot.kalan_miktar)) - miktar_d
                        session.add(
                            StokHareketi(
                                tarih=date.today(),
                                hareket_turu="TRANSFER ÇIKIŞ",
                                belge_no=f"{teslim.belge_no}-IADE",
                                stok_id=satir.stok_id,
                                depo_id=lot.depo_id,
                                lot_id=lot.id,
                                miktar=miktar_d,
                                birim_maliyet=lot.birim_maliyet,
                            )
                        )
                # Ana depoya giriş — satır lot bağlantısını bozmamak için proxy
                proxy = type(
                    "S",
                    (),
                    {
                        "stok_id": satir.stok_id,
                        "birim_fiyat": satir.birim_fiyat,
                        "lot_no": (satir.lot_no or "") + "-IADE",
                        "id": satir.id,
                        "lot_id": None,
                    },
                )()
                KonsinyeService._hedefe_giris(session, teslim, proxy, hedef, miktar_d)
            else:
                # ALINAN: fiziksel depodaki tedarikçi lotundan düş
                kaynak = session.get(Depo, teslim.depo_id)
                if kaynak is None:
                    raise ValueError("Kaynak depo yok.")
                KonsinyeService._kaynaktan_cikis(session, teslim, satir, kaynak, miktar_d)

            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_IADE,
                    miktar=miktar_d,
                    gercek_tarih=date.today(),
                    aciklama=(aciklama or "").strip() or None,
                    olusturan=_kullanici(),
                )
            )
            session.flush()
            KonsinyeService._teslim_durum_guncelle(session, teslim)
            return KonsinyeService._satir_ozet(satir)

    @staticmethod
    def kesin_al(
        *,
        teslim_satiri_id: int,
        miktar: Decimal | str | float,
        birim_maliyet: Decimal | str | float | None = None,
        aciklama: str | None = None,
    ) -> dict[str, Any]:
        """ALINAN konsinyede tedarikçi malını kendi stoğumuza geçir (cari borç yazılmaz; fatura sonra)."""
        KonsinyeService.ensure_schema()
        miktar_d = decimal(miktar, "Kesin alım miktarı", Decimal("0.0001"))
        with get_session() as session:
            satir = session.get(KonsinyeTeslimSatiri, int(teslim_satiri_id))
            if satir is None:
                raise ValueError("Teslim satırı bulunamadı.")
            teslim = session.get(KonsinyeTeslim, satir.teslim_id)
            if teslim is None or teslim.durum != DURUM_ONAYLI:
                raise ValueError("Yalnız onaylı teslimde kesin alım yapılır.")
            if teslim.yon != YON_ALINAN:
                raise ValueError("Kesin alım yalnız alınan konsinyede.")
            kalan = Decimal(str(satir.kalan_miktar or 0))
            if miktar_d > kalan:
                raise ValueError(f"Kesin alım kalanı aşıyor (kalan: {kalan}).")
            maliyet = decimal(
                birim_maliyet if birim_maliyet is not None else satir.birim_fiyat,
                "Birim maliyet",
                Decimal("0.0001"),
            )
            satir.kalan_miktar = kalan - miktar_d
            satir.bildirilen_miktar = Decimal(str(satir.bildirilen_miktar or 0)) + miktar_d
            # Fiziksel lokasyon aynı; maliyet/lot sahipliği güncellenir
            if satir.lot_id:
                lot = session.get(StokLotu, satir.lot_id)
                if lot is not None and Decimal(str(lot.kalan_miktar or 0)) >= miktar_d:
                    lot.kalan_miktar = Decimal(str(lot.kalan_miktar)) - miktar_d
            proxy = type(
                "S",
                (),
                {
                    "stok_id": satir.stok_id,
                    "birim_fiyat": maliyet,
                    "lot_no": f"KA-{teslim.belge_no}-{satir.id}",
                    "id": satir.id,
                    "lot_id": None,
                },
            )()
            hedef = session.get(Depo, teslim.depo_id)
            KonsinyeService._hedefe_giris(session, teslim, proxy, hedef, miktar_d)
            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_FATURA_TASLAK,
                    miktar=miktar_d,
                    gercek_tarih=date.today(),
                    aciklama=(aciklama or "Kesin alım").strip(),
                    olusturan=_kullanici(),
                )
            )
            session.flush()
            KonsinyeService._teslim_durum_guncelle(session, teslim)
            return KonsinyeService._satir_ozet(satir)

    @staticmethod
    def fatura_bagla(
        *,
        teslim_satiri_id: int,
        miktar: Decimal | str | float,
        belge_no: str | None = None,
        belge_id: int | None = None,
        onayli: bool = True,
    ) -> dict[str, Any]:
        """Bildirilen/kesin alınan miktarı faturalanan olarak işaretle (fiziksel stok tekrar düşmez)."""
        KonsinyeService.ensure_schema()
        miktar_d = decimal(miktar, "Fatura miktarı", Decimal("0.0001"))
        with get_session() as session:
            satir = session.get(KonsinyeTeslimSatiri, int(teslim_satiri_id))
            if satir is None:
                raise ValueError("Teslim satırı bulunamadı.")
            teslim = session.get(KonsinyeTeslim, satir.teslim_id)
            if teslim is None or teslim.durum not in (DURUM_ONAYLI, DURUM_KAPALI):
                raise ValueError("Geçersiz teslim durumu.")
            bekleyen = Decimal(str(satir.bildirilen_miktar or 0)) - Decimal(
                str(satir.faturalanan_miktar or 0)
            )
            if miktar_d > bekleyen:
                raise ValueError(f"Fatura bekleyen miktarı aşıyor (bekleyen: {bekleyen}).")
            if onayli:
                satir.faturalanan_miktar = Decimal(str(satir.faturalanan_miktar or 0)) + miktar_d
            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_FATURA_ONAY if onayli else H_FATURA_TASLAK,
                    miktar=miktar_d,
                    gercek_tarih=date.today(),
                    belge_no=(belge_no or "").strip() or None,
                    belge_id=belge_id,
                    olusturan=_kullanici(),
                )
            )
            session.flush()
            KonsinyeService._teslim_durum_guncelle(session, teslim)
            return KonsinyeService._satir_ozet(satir)

    @staticmethod
    def _teslim_durum_guncelle(session, teslim: KonsinyeTeslim) -> None:
        if not teslim.satirlar:
            return
        if all(
            Decimal(str(s.kalan_miktar or 0)) <= 0
            and Decimal(str(s.bildirilen_miktar or 0))
            <= Decimal(str(s.faturalanan_miktar or 0))
            for s in teslim.satirlar
        ):
            teslim.durum = DURUM_KAPALI

    @staticmethod
    def listele(
        *,
        yon: str | None = None,
        durum: str | None = None,
        cari_id: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        KonsinyeService.ensure_schema()
        with get_session() as session:
            q = select(KonsinyeTeslim).order_by(KonsinyeTeslim.id.desc()).limit(limit)
            if yon:
                q = q.where(KonsinyeTeslim.yon == yon)
            if durum:
                q = q.where(KonsinyeTeslim.durum == durum)
            else:
                q = q.where(KonsinyeTeslim.durum != DURUM_IPTAL)
            if cari_id:
                q = q.where(KonsinyeTeslim.cari_id == int(cari_id))
            return [KonsinyeService._teslim_ozet(session, t) for t in session.scalars(q).all()]

    @staticmethod
    def getir(teslim_id: int) -> dict[str, Any] | None:
        KonsinyeService.ensure_schema()
        with get_session() as session:
            t = session.get(KonsinyeTeslim, int(teslim_id))
            if t is None:
                return None
            return KonsinyeService._teslim_ozet(session, t)

    @staticmethod
    def _satir_ozet(s: KonsinyeTeslimSatiri, *, yon: str | None = None) -> dict[str, Any]:
        kalan = Decimal(str(s.kalan_miktar or 0))
        bildirilen = Decimal(str(s.bildirilen_miktar or 0))
        faturalanan = Decimal(str(s.faturalanan_miktar or 0))
        fatura_bekleyen = max(Decimal("0"), bildirilen - faturalanan)
        if kalan > 0:
            adim = "Müşteride Mal Var" if yon != YON_ALINAN else "Tedarikçiye Ait Kalan"
        elif fatura_bekleyen > 0:
            adim = "Fatura Bekliyor"
        else:
            adim = "Tamamlandı"
        return {
            "id": s.id,
            "stok_id": s.stok_id,
            "stok_kodu": s.stok_kodu,
            "stok_adi": s.stok_adi,
            "birim": s.birim,
            "miktar": Decimal(str(s.miktar)),
            "temel_miktar": Decimal(str(s.temel_miktar)),
            "birim_fiyat": Decimal(str(s.birim_fiyat or 0)),
            "lot_no": s.lot_no,
            "kalan_miktar": kalan,
            "bildirilen_miktar": bildirilen,
            "faturalanan_miktar": faturalanan,
            "fatura_bekleyen": fatura_bekleyen,
            "iade_miktar": Decimal(str(s.iade_miktar or 0)),
            "adim": adim,
        }

    @staticmethod
    def _teslim_ozet(session, t: KonsinyeTeslim) -> dict[str, Any]:
        from database.models.cari import Cari

        cari = session.get(Cari, t.cari_id)
        depo = session.get(Depo, t.depo_id)
        satirlar = [KonsinyeService._satir_ozet(s, yon=t.yon) for s in (t.satirlar or [])]
        return {
            "id": t.id,
            "belge_no": t.belge_no,
            "yon": t.yon,
            "durum": t.durum,
            "belge_tarihi": t.belge_tarihi,
            "cari_id": t.cari_id,
            "cari_unvan": getattr(cari, "unvan", "") if cari else "",
            "cari_kodu": getattr(cari, "cari_kodu", "") if cari else "",
            "depo_id": t.depo_id,
            "depo": depo.ad if depo else "",
            "aciklama": t.aciklama,
            "satirlar": satirlar,
            "satir_sayisi": len(satirlar),
            "kalan_toplam": sum((s["kalan_miktar"] for s in satirlar), Decimal("0")),
            "fatura_bekleyen_toplam": sum((s["fatura_bekleyen"] for s in satirlar), Decimal("0")),
        }

    @staticmethod
    def ozet_kutulari(yon: str) -> dict[str, Any]:
        """Ana ekran özet kutuları — belge/satır sayısı; farklı birimleri birleştirmez."""
        liste = KonsinyeService.listele(yon=yon, limit=500)
        acik = [t for t in liste if t["durum"] in (DURUM_ONAYLI, DURUM_TASLAK)]
        fatura_bek = sum(1 for t in liste if t["fatura_bekleyen_toplam"] > 0)
        kalan_satir = sum(
            1 for t in liste for s in t["satirlar"] if s["kalan_miktar"] > 0
        )
        return {
            "acik_teslim": len(acik),
            "fatura_bekleyen_belge": fatura_bek,
            "kalan_satir": kalan_satir,
            "toplam_belge": len(liste),
        }
