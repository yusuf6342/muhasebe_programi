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
H_KESIN_AL = "KESIN_AL"
H_FATURA_TASLAK = "FATURA_TASLAK"
H_FATURA_ONAY = "FATURA_ONAY"

KONSINYE_DEPO_ONEK = "KONSİNYE:"
SAHIP_BIZE = "BIZE"
SAHIP_TEDARIKCI = "TEDARIKCI"


def miktar_goster(v) -> str:
    """Tam sayının sondaki sıfırlarını silme; yalnız kesir sıfırlarını temizle."""
    try:
        d = Decimal(str(v if v is not None else 0))
    except Exception:
        return "0"
    if d == d.to_integral_value():
        return format(d.to_integral_value(), "f")
    t = format(d, "f")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t or "0"


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
        from sqlalchemy import inspect, text

        Base.metadata.create_all(
            bind=engine,
            tables=[
                KonsinyeTeslim.__table__,
                KonsinyeTeslimSatiri.__table__,
                KonsinyeHareket.__table__,
            ],
        )
        # Sürümlü / tekrarlanabilir kolon göçü
        insp = inspect(engine)
        ekler = {
            "konsinye_teslim_satirlari": {
                "fifo_birim_maliyet": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
                "taslak_ayrilan_miktar": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
            },
            "konsinye_hareketler": {
                "fatura_turu": "VARCHAR(20)",
                "fatura_satir_id": "INTEGER",
                "islem_anahtari": "VARCHAR(120)",
            },
            "stok_lotlari": {
                "sahip_turu": "VARCHAR(20) DEFAULT 'BIZE' NOT NULL",
                "sahip_cari_id": "INTEGER",
                "kaynak_konsinye_satir_id": "INTEGER",
            },
            "satis_faturasi_satirlari": {
                "konsinye_teslim_satiri_id": "INTEGER",
            },
            "alis_faturasi_satirlari": {
                "konsinye_teslim_satiri_id": "INTEGER",
            },
        }
        with engine.begin() as conn:
            for tablo, kolonlar in ekler.items():
                if not insp.has_table(tablo):
                    continue
                mevcut = {c["name"] for c in insp.get_columns(tablo)}
                for ad, tip in kolonlar.items():
                    if ad not in mevcut:
                        conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{ad}" {tip}'))
        KonsinyeService._schema_hazir = True

    @staticmethod
    def _belge_no(session, yon: str) -> str:
        onek = "KV" if yon == YON_VERILEN else "KA"
        son = session.scalar(
            select(func.max(KonsinyeTeslim.id)).where(KonsinyeTeslim.yon == yon)
        ) or 0
        return f"{onek}{int(son) + 1:06d}"

    @staticmethod
    def konsinye_depo_adi(cari_id: int, yon: str, cari_unvan: str = "") -> str:
        """Kalıcı cari kimliğiyle sanal depo — unvan değişince bağlantı bozulmaz."""
        yon_etiket = "MUSTERI" if yon == YON_VERILEN else "TEDARIKCI"
        # Kısa unvan yalnızca okunabilirlik; benzersizlik cari_id ile
        kisalt = (cari_unvan or "").strip()[:24]
        ek = f":{kisalt}" if kisalt else ""
        return f"{KONSINYE_DEPO_ONEK}{yon_etiket}:C{int(cari_id)}{ek}"

    @staticmethod
    def sanal_depo_mu(depo_ad: str | None) -> bool:
        return (depo_ad or "").strip().upper().startswith(KONSINYE_DEPO_ONEK)

    @staticmethod
    def lot_firma_mulkiyeti_mi(lot) -> bool:
        tur = (getattr(lot, "sahip_turu", None) or SAHIP_BIZE).strip().upper()
        return tur == SAHIP_BIZE

    @staticmethod
    def _konsinye_depo_al_veya_olustur(session, cari, yon: str) -> Depo:
        ad = KonsinyeService.konsinye_depo_adi(
            int(cari.id), yon, getattr(cari, "unvan", "") or ""
        )
        depo = session.scalar(select(Depo).where(Depo.ad == ad))
        if depo is None:
            # Eski unvan-ön ekli depoyu yeniden kullan (göç)
            eski_ad = f"{KONSINYE_DEPO_ONEK}{'MÜŞTERİ' if yon == YON_VERILEN else 'TEDARİKÇİ'}:{(getattr(cari, 'unvan', '') or '').strip()[:40]}"
            depo = session.scalar(select(Depo).where(Depo.ad == eski_ad))
        if depo is None:
            depo = Depo(
                ad=ad,
                aktif=True,
                varsayilan=False,
                aciklama=f"KONSINYE_SANAL cari_id={int(cari.id)} — satılabilir stok sayılmaz",
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
                # Kendi stokumuz → müşteri konsinye konumu; FIFO maliyet korunur (cari borç yok)
                katmanlar = KonsinyeService._kaynaktan_cikis(
                    session,
                    teslim,
                    satir,
                    kaynak,
                    miktar,
                    sadece_firma=True,
                )
                toplam_maliyet = sum(
                    (k["miktar"] * k["birim_maliyet"] for k in katmanlar), Decimal("0")
                )
                # Hedefe katman katman gir (maliyet bozulmasın)
                for k in katmanlar:
                    KonsinyeService._hedefe_giris(
                        session,
                        teslim,
                        satir,
                        hedef,
                        k["miktar"],
                        birim_maliyet=k["birim_maliyet"],
                        sahip_turu=SAHIP_BIZE,
                        sahip_cari_id=None,
                        lot_no_ek=f"-L{k['lot_id']}" if len(katmanlar) > 1 else "",
                    )
                if miktar > 0:
                    satir.fifo_birim_maliyet = (toplam_maliyet / miktar).quantize(Decimal("0.0001"))
            else:
                # Tedarikçi malı fiziksel mağazaya — firma mülkiyeti/borcu yok
                KonsinyeService._hedefe_giris(
                    session,
                    teslim,
                    satir,
                    kaynak,
                    miktar,
                    birim_maliyet=Decimal(str(satir.birim_fiyat or 0)),
                    sahip_turu=SAHIP_TEDARIKCI,
                    sahip_cari_id=int(teslim.cari_id),
                )
                satir.fifo_birim_maliyet = Decimal(str(satir.birim_fiyat or 0))

        teslim.durum = DURUM_ONAYLI
        teslim.onay_tarihi = datetime.now()
        teslim.onaylayan = _kullanici()
        session.flush()

    @staticmethod
    def _kaynaktan_cikis(
        session,
        teslim,
        satir,
        kaynak_depo: Depo,
        miktar: Decimal,
        *,
        sadece_firma: bool = True,
        sahip_turu: str | None = None,
        belge_no: str | None = None,
        tarih: date | None = None,
    ) -> list[dict[str, Any]]:
        """FIFO çıkış; katman listesi döner. ``sadece_firma`` tedarikçi lotlarını atlar."""
        stok = session.get(StokKarti, satir.stok_id)
        if stok is None:
            raise ValueError("Stok bulunamadı.")
        q = select(StokLotu).where(
            StokLotu.stok_id == stok.id,
            StokLotu.depo_id == kaynak_depo.id,
            StokLotu.kalan_miktar > 0,
        )
        if getattr(satir, "lot_no", None):
            q = q.where(StokLotu.lot_no == satir.lot_no)
        if sahip_turu:
            q = q.where(StokLotu.sahip_turu == sahip_turu)
        lotlar = list(session.scalars(q.order_by(StokLotu.giris_tarihi, StokLotu.id)).all())
        if sadece_firma and sahip_turu is None:
            lotlar = [l for l in lotlar if KonsinyeService.lot_firma_mulkiyeti_mi(l)]
        mevcut = sum((Decimal(str(l.kalan_miktar or 0)) for l in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{getattr(satir, 'stok_adi', stok.stok_adi)}: {kaynak_depo.ad} stok yetersiz "
                f"(mevcut {mevcut}, istenen {miktar})."
            )
        kalan = miktar
        katmanlar: list[dict[str, Any]] = []
        bno = belge_no or teslim.belge_no
        htarih = tarih or teslim.belge_tarihi
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, Decimal(str(lot.kalan_miktar or 0)))
            maliyet = Decimal(str(lot.birim_maliyet or 0))
            lot.kalan_miktar = Decimal(str(lot.kalan_miktar)) - cikan
            kalan -= cikan
            session.add(
                StokHareketi(
                    tarih=htarih,
                    hareket_turu="TRANSFER ÇIKIŞ",
                    belge_no=bno,
                    stok_id=stok.id,
                    depo_id=kaynak_depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=maliyet,
                )
            )
            katmanlar.append(
                {"lot_id": int(lot.id), "miktar": cikan, "birim_maliyet": maliyet}
            )
        return katmanlar

    @staticmethod
    def _hedefe_giris(
        session,
        teslim,
        satir,
        hedef_depo: Depo,
        miktar: Decimal,
        *,
        birim_maliyet: Decimal | None = None,
        sahip_turu: str = SAHIP_BIZE,
        sahip_cari_id: int | None = None,
        lot_no_ek: str = "",
        belge_no: str | None = None,
        tarih: date | None = None,
    ) -> StokLotu:
        stok = session.get(StokKarti, satir.stok_id)
        if stok is None:
            raise ValueError("Stok bulunamadı.")
        maliyet = Decimal(
            str(
                birim_maliyet
                if birim_maliyet is not None
                else getattr(satir, "fifo_birim_maliyet", None)
                or 0
            )
        )
        # Satış fiyatını maliyet yapma — verilen konsinyede fifo ile gelmeli
        if maliyet < 0:
            maliyet = Decimal("0")
        taban = (getattr(satir, "lot_no", None) or "").strip() or f"{teslim.belge_no}-{getattr(satir, 'id', 0)}"
        lot_no = f"{taban}{lot_no_ek}"
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
                birim_maliyet=maliyet,
                sahip_turu=sahip_turu,
                sahip_cari_id=sahip_cari_id,
                kaynak_konsinye_satir_id=getattr(satir, "id", None),
            )
            session.add(lot)
            session.flush()
        else:
            # Mevcut lot sahipliği korunur; maliyet ağırlıklı ortalama
            eski_q = Decimal(str(lot.kalan_miktar or 0))
            if eski_q > 0 and miktar > 0:
                lot.birim_maliyet = (
                    (eski_q * Decimal(str(lot.birim_maliyet or 0)) + miktar * maliyet)
                    / (eski_q + miktar)
                ).quantize(Decimal("0.0001"))
            elif miktar > 0:
                lot.birim_maliyet = maliyet
            lot.sahip_turu = sahip_turu
            if sahip_cari_id is not None:
                lot.sahip_cari_id = sahip_cari_id
        lot.kalan_miktar = Decimal(str(lot.kalan_miktar or 0)) + miktar
        session.add(
            StokHareketi(
                tarih=tarih or teslim.belge_tarihi,
                hareket_turu="TRANSFER GİRİŞ",
                belge_no=belge_no or teslim.belge_no,
                stok_id=stok.id,
                depo_id=hedef_depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=maliyet,
            )
        )
        if hasattr(satir, "lot_id"):
            satir.lot_id = lot.id
            satir.lot_no = lot.lot_no
        return lot

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
                # Ana depoya giriş — FIFO maliyet (satış fiyatı değil)
                iade_maliyet = Decimal(str(satir.fifo_birim_maliyet or 0))
                if satir.lot_id:
                    kaynak_lot = session.get(StokLotu, satir.lot_id)
                    if kaynak_lot is not None:
                        iade_maliyet = Decimal(str(kaynak_lot.birim_maliyet or iade_maliyet))
                proxy = type(
                    "S",
                    (),
                    {
                        "stok_id": satir.stok_id,
                        "birim_fiyat": iade_maliyet,
                        "fifo_birim_maliyet": iade_maliyet,
                        "lot_no": (satir.lot_no or "") + "-IADE",
                        "id": satir.id,
                        "lot_id": None,
                    },
                )()
                KonsinyeService._hedefe_giris(
                    session,
                    teslim,
                    proxy,
                    hedef,
                    miktar_d,
                    birim_maliyet=iade_maliyet,
                    sahip_turu=SAHIP_BIZE,
                    belge_no=f"{teslim.belge_no}-IADE",
                    tarih=date.today(),
                )
            else:
                # ALINAN: yalnız tedarikçiye ait lotlardan iade
                kaynak = session.get(Depo, teslim.depo_id)
                if kaynak is None:
                    raise ValueError("Kaynak depo yok.")
                KonsinyeService._kaynaktan_cikis(
                    session,
                    teslim,
                    satir,
                    kaynak,
                    miktar_d,
                    sadece_firma=False,
                    sahip_turu=SAHIP_TEDARIKCI,
                    belge_no=f"{teslim.belge_no}-IADE",
                    tarih=date.today(),
                )

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
        """ALINAN: sahiplik değişir; fiziksel toplam aynı kalır (ÇIKIŞ+GİRİŞ çift). Cari borç yok."""
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
                birim_maliyet
                if birim_maliyet is not None
                else (satir.fifo_birim_maliyet or satir.birim_fiyat),
                "Birim maliyet",
                Decimal("0.0001"),
            )
            hedef = session.get(Depo, teslim.depo_id)
            if hedef is None:
                raise ValueError("Depo bulunamadı.")
            # Tedarikçi lotundan çıkış (hareket kaydı zorunlu — rapor 130 olmasın)
            proxy_cikis = type(
                "S",
                (),
                {
                    "stok_id": satir.stok_id,
                    "stok_adi": satir.stok_adi,
                    "lot_no": satir.lot_no,
                    "id": satir.id,
                },
            )()
            KonsinyeService._kaynaktan_cikis(
                session,
                teslim,
                proxy_cikis,
                hedef,
                miktar_d,
                sadece_firma=False,
                sahip_turu=SAHIP_TEDARIKCI,
                belge_no=f"{teslim.belge_no}-KA",
                tarih=date.today(),
            )
            # Aynı depoda firma mülkiyetli lot
            proxy = type(
                "S",
                (),
                {
                    "stok_id": satir.stok_id,
                    "birim_fiyat": maliyet,
                    "fifo_birim_maliyet": maliyet,
                    "lot_no": f"KA-{teslim.belge_no}-{satir.id}",
                    "id": satir.id,
                    "lot_id": None,
                },
            )()
            KonsinyeService._hedefe_giris(
                session,
                teslim,
                proxy,
                hedef,
                miktar_d,
                birim_maliyet=maliyet,
                sahip_turu=SAHIP_BIZE,
                sahip_cari_id=None,
                belge_no=f"{teslim.belge_no}-KA",
                tarih=date.today(),
            )
            satir.kalan_miktar = kalan - miktar_d
            satir.bildirilen_miktar = Decimal(str(satir.bildirilen_miktar or 0)) + miktar_d
            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_KESIN_AL,
                    miktar=miktar_d,
                    gercek_tarih=date.today(),
                    aciklama=(aciklama or "Kesin alım").strip(),
                    olusturan=_kullanici(),
                    islem_anahtari=f"KA:{satir.id}:{miktar_d}:{date.today().isoformat()}",
                )
            )
            session.flush()
            KonsinyeService._teslim_durum_guncelle(session, teslim)
            return KonsinyeService._satir_ozet(satir)

    @staticmethod
    def _gercek_fatura_dogrula(
        session, *, yon: str, belge_id: int, belge_no: str | None, miktar: Decimal
    ) -> tuple[Any, str]:
        """Gerçek satış/alış faturasını doğrula; iptal/hayali kabul etme."""
        if yon == YON_VERILEN:
            from database.models.satis_faturasi import SatisFaturasi

            fatura = session.get(SatisFaturasi, int(belge_id))
            tur = "SATIS"
        else:
            from database.models.alis_faturasi import AlisFaturasi

            fatura = session.get(AlisFaturasi, int(belge_id))
            tur = "ALIS"
        if fatura is None:
            raise ValueError("Bağlanacak fatura bulunamadı.")
        durum = (getattr(fatura, "durum", None) or "").strip().upper()
        if durum in ("İPTAL", "IPTAL"):
            raise ValueError("İptal fatura bağlanamaz.")
        no = (getattr(fatura, "fatura_no", None) or "").strip()
        if belge_no and no and belge_no.strip() != no:
            raise ValueError(f"Fatura numarası uyuşmuyor (beklenen {no}).")
        return fatura, tur

    @staticmethod
    def fatura_bagla(
        *,
        teslim_satiri_id: int,
        miktar: Decimal | str | float,
        belge_no: str | None = None,
        belge_id: int | None = None,
        fatura_satir_id: int | None = None,
        onayli: bool = True,
    ) -> dict[str, Any]:
        """Bildirilen/kesin alınan miktarı gerçek faturaya bağla (stok tekrar düşmez).

        ``belge_id`` zorunlu — yalnız numara ile hayali bağlama kabul edilmez.
        """
        KonsinyeService.ensure_schema()
        miktar_d = decimal(miktar, "Fatura miktarı", Decimal("0.0001"))
        if not belge_id:
            raise ValueError(
                "Gerçek fatura kimliği (belge_id) zorunlu. "
                "Önce Satış/Alış Faturası Oluştur veya mevcut faturayla eşleştirin."
            )
        with get_session() as session:
            satir = session.get(KonsinyeTeslimSatiri, int(teslim_satiri_id))
            if satir is None:
                raise ValueError("Teslim satırı bulunamadı.")
            teslim = session.get(KonsinyeTeslim, satir.teslim_id)
            if teslim is None or teslim.durum not in (DURUM_ONAYLI, DURUM_KAPALI):
                raise ValueError("Geçersiz teslim durumu.")
            fatura, fatura_turu = KonsinyeService._gercek_fatura_dogrula(
                session,
                yon=teslim.yon,
                belge_id=int(belge_id),
                belge_no=belge_no,
                miktar=miktar_d,
            )
            # Cari uyumu
            fatura_cari = getattr(fatura, "musteri_id", None) or getattr(fatura, "tedarikci_id", None)
            if fatura_cari and int(fatura_cari) != int(teslim.cari_id):
                raise ValueError("Fatura carisi konsinye carisiyle uyuşmuyor.")
            anahtar = f"FB:{satir.id}:{fatura_turu}:{int(belge_id)}:{fatura_satir_id or 0}:{miktar_d}"
            mevcut = session.scalar(
                select(KonsinyeHareket).where(
                    KonsinyeHareket.islem_anahtari == anahtar,
                    KonsinyeHareket.iptal.is_(False),
                )
            )
            if mevcut is not None:
                raise ValueError("Bu fatura bağlantısı zaten kayıtlı (mükerrer engellendi).")
            bekleyen = Decimal(str(satir.bildirilen_miktar or 0)) - Decimal(
                str(satir.faturalanan_miktar or 0)
            ) - Decimal(str(getattr(satir, "taslak_ayrilan_miktar", 0) or 0))
            if onayli:
                # Onaylı bağlama: taslak ayrılanı serbest bırakıp faturalanana ekle
                bekleyen = Decimal(str(satir.bildirilen_miktar or 0)) - Decimal(
                    str(satir.faturalanan_miktar or 0)
                )
            if miktar_d > bekleyen:
                raise ValueError(f"Fatura bekleyen miktarı aşıyor (bekleyen: {bekleyen}).")
            no = (getattr(fatura, "fatura_no", None) or belge_no or "").strip() or None
            if onayli:
                satir.faturalanan_miktar = Decimal(str(satir.faturalanan_miktar or 0)) + miktar_d
            else:
                satir.taslak_ayrilan_miktar = Decimal(
                    str(getattr(satir, "taslak_ayrilan_miktar", 0) or 0)
                ) + miktar_d
            session.add(
                KonsinyeHareket(
                    teslim_satiri_id=satir.id,
                    hareket_turu=H_FATURA_ONAY if onayli else H_FATURA_TASLAK,
                    miktar=miktar_d,
                    gercek_tarih=date.today(),
                    belge_no=no,
                    belge_id=int(belge_id),
                    fatura_turu=fatura_turu,
                    fatura_satir_id=int(fatura_satir_id) if fatura_satir_id else None,
                    olusturan=_kullanici(),
                    islem_anahtari=anahtar,
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
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """limit=None → tüm kayıtlar (rapor/toplam); UI sayfalama için limit verilebilir."""
        KonsinyeService.ensure_schema()
        with get_session() as session:
            q = select(KonsinyeTeslim).order_by(KonsinyeTeslim.id.desc())
            if yon:
                q = q.where(KonsinyeTeslim.yon == yon)
            if durum:
                q = q.where(KonsinyeTeslim.durum == durum)
            else:
                q = q.where(KonsinyeTeslim.durum != DURUM_IPTAL)
            if cari_id:
                q = q.where(KonsinyeTeslim.cari_id == int(cari_id))
            if offset:
                q = q.offset(int(offset))
            if limit is not None:
                q = q.limit(int(limit))
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
        taslak = Decimal(str(getattr(s, "taslak_ayrilan_miktar", 0) or 0))
        fatura_bekleyen = max(Decimal("0"), bildirilen - faturalanan - taslak)
        if kalan > 0:
            adim = "Müşteride Mal Var" if yon != YON_ALINAN else "Tedarikçiye Ait Kalan"
        elif fatura_bekleyen > 0 or taslak > 0:
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
            "fifo_birim_maliyet": Decimal(str(getattr(s, "fifo_birim_maliyet", 0) or 0)),
            "lot_id": s.lot_id,
            "lot_no": s.lot_no,
            "kalan_miktar": kalan,
            "bildirilen_miktar": bildirilen,
            "faturalanan_miktar": faturalanan,
            "taslak_ayrilan_miktar": taslak,
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
        """Ana ekran özet kutuları — tüm belgeler; farklı birimleri birleştirmez."""
        liste = KonsinyeService.listele(yon=yon, limit=None)
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

    @staticmethod
    def stok_sahiplik_ozeti(stok_id: int) -> dict[str, Any]:
        """Fiziksel / bize ait / tedarikçiye ait ayrımı (temel birim + maliyet değeri)."""
        KonsinyeService.ensure_schema()
        with get_session() as session:
            lotlar = list(
                session.scalars(select(StokLotu).where(StokLotu.stok_id == int(stok_id))).all()
            )
            fiziksel = Decimal("0")
            bize = Decimal("0")
            tedarikci = Decimal("0")
            bize_deger = Decimal("0")
            for lot in lotlar:
                q = Decimal(str(lot.kalan_miktar or 0))
                if q <= 0:
                    continue
                fiziksel += q
                if KonsinyeService.lot_firma_mulkiyeti_mi(lot):
                    bize += q
                    bize_deger += q * Decimal(str(lot.birim_maliyet or 0))
                else:
                    tedarikci += q
            return {
                "fiziksel": fiziksel,
                "bize_ait": bize,
                "tedarikciye_ait": tedarikci,
                "bize_ait_deger": bize_deger,
            }

    @staticmethod
    def hareket_net_miktar(stok_id: int) -> Decimal:
        """Hareket esaslı net (giriş − çıkış); kesin alım çifti neti bozmamalı."""
        from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI

        with get_session() as session:
            hareketler = list(
                session.scalars(
                    select(StokHareketi).where(StokHareketi.stok_id == int(stok_id))
                ).all()
            )
            giris = sum(
                (Decimal(str(h.miktar)) for h in hareketler if h.hareket_turu in GIRIS_HAREKETLERI),
                Decimal("0"),
            )
            cikis = sum(
                (Decimal(str(h.miktar)) for h in hareketler if h.hareket_turu in CIKIS_HAREKETLERI),
                Decimal("0"),
            )
            return giris - cikis

    @staticmethod
    def faturalanabilir_satirlar(*, yon: str, cari_id: int | None = None) -> list[dict[str, Any]]:
        """Fatura bekleyen satırlar (tüm kayıtlar)."""
        sonuc = []
        for t in KonsinyeService.listele(yon=yon, cari_id=cari_id, limit=None):
            for s in t["satirlar"]:
                if s["fatura_bekleyen"] > 0:
                    sonuc.append({**s, "teslim_id": t["id"], "belge_no": t["belge_no"],
                                  "cari_id": t["cari_id"], "cari_unvan": t["cari_unvan"],
                                  "yon": t["yon"], "belge_tarihi": t["belge_tarihi"]})
        return sonuc

    @staticmethod
    def satis_faturasi_satirlari_hazirla(satir_idler_miktar: list[tuple[int, Decimal]]) -> dict[str, Any]:
        """Verilen konsinye → satış faturası için cari + satır verisi (UI/servis ortak)."""
        if not satir_idler_miktar:
            raise ValueError("Faturalanacak satır seçin.")
        with get_session() as session:
            satirlar_out = []
            cari_id = None
            for sid, miktar in satir_idler_miktar:
                miktar_d = decimal(miktar, "Miktar", Decimal("0.0001"))
                satir = session.get(KonsinyeTeslimSatiri, int(sid))
                if satir is None:
                    raise ValueError(f"Konsinye satırı yok: {sid}")
                teslim = session.get(KonsinyeTeslim, satir.teslim_id)
                if teslim is None or teslim.yon != YON_VERILEN:
                    raise ValueError("Yalnız verilen konsinye satışı faturalanır.")
                if cari_id is None:
                    cari_id = int(teslim.cari_id)
                elif int(teslim.cari_id) != cari_id:
                    raise ValueError("Farklı cariler tek faturada birleştirilemez.")
                ozet = KonsinyeService._satir_ozet(satir, yon=teslim.yon)
                if miktar_d > ozet["fatura_bekleyen"]:
                    raise ValueError(
                        f"{satir.stok_kodu}: bekleyen {ozet['fatura_bekleyen']}, istenen {miktar_d}"
                    )
                satirlar_out.append(
                    {
                        "stok_id": satir.stok_id,
                        "urun_kodu": satir.stok_kodu,
                        "urun_adi": satir.stok_adi,
                        "birim": satir.birim,
                        "miktar": miktar_d,
                        "birim_fiyat": Decimal(str(satir.birim_fiyat or 0)),
                        "kdv_orani": Decimal("20"),
                        "konsinye_teslim_satiri_id": int(satir.id),
                        "konsinye_stok_cikisi_yapildi": True,
                    }
                )
            return {"cari_id": cari_id, "satirlar": satirlar_out, "yon": YON_VERILEN}

    @staticmethod
    def alis_faturasi_satirlari_hazirla(satir_idler_miktar: list[tuple[int, Decimal]]) -> dict[str, Any]:
        """Alınan konsinye kesin alım → alış faturası satırları."""
        if not satir_idler_miktar:
            raise ValueError("Faturalanacak satır seçin.")
        with get_session() as session:
            satirlar_out = []
            cari_id = None
            for sid, miktar in satir_idler_miktar:
                miktar_d = decimal(miktar, "Miktar", Decimal("0.0001"))
                satir = session.get(KonsinyeTeslimSatiri, int(sid))
                if satir is None:
                    raise ValueError(f"Konsinye satırı yok: {sid}")
                teslim = session.get(KonsinyeTeslim, satir.teslim_id)
                if teslim is None or teslim.yon != YON_ALINAN:
                    raise ValueError("Yalnız alınan konsinye alış faturalanır.")
                if cari_id is None:
                    cari_id = int(teslim.cari_id)
                elif int(teslim.cari_id) != cari_id:
                    raise ValueError("Farklı cariler tek faturada birleştirilemez.")
                ozet = KonsinyeService._satir_ozet(satir, yon=teslim.yon)
                if miktar_d > ozet["fatura_bekleyen"]:
                    raise ValueError(
                        f"{satir.stok_kodu}: bekleyen {ozet['fatura_bekleyen']}, istenen {miktar_d}"
                    )
                satirlar_out.append(
                    {
                        "stok_id": satir.stok_id,
                        "urun_kodu": satir.stok_kodu,
                        "urun_adi": satir.stok_adi,
                        "birim": satir.birim,
                        "miktar": miktar_d,
                        "birim_fiyat": Decimal(
                            str(satir.fifo_birim_maliyet or satir.birim_fiyat or 0)
                        ),
                        "kdv_orani": Decimal("20"),
                        "konsinye_teslim_satiri_id": int(satir.id),
                        "konsinye_stok_girisi_yapildi": True,
                    }
                )
            return {"cari_id": cari_id, "satirlar": satirlar_out, "yon": YON_ALINAN}
