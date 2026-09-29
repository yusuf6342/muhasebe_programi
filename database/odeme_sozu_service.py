"""Ödeme sözleri takibi — finansal etkisi olmayan ayrı planlama sistemi.

* Söz; cari bakiye, fatura, kasa/banka veya muhasebe fişine hiçbir kayıt yazmaz.
* Gerçekleşen / kalan tutar yalnız gerçek ödeme evraklarına bağlantılardan hesaplanır.
* Değişiklikler (erteleme, tutar, yöntem, iptal, görüşme notu, düzeltme) geçmişe eklenir.
* Tarihler yerel tarihtir (``date.today()``); "yaklaşıyor" eşiği firma ayarıdır (varsayılan 3 gün).
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.odeme_sozu import (
    OdemeSozu,
    OdemeSozuAyar,
    OdemeSozuBaglanti,
    OdemeSozuFatura,
    OdemeSozuGecmis,
)

ALINAN = "ALINAN"
VERILEN = "VERILEN"
YONLER = (ALINAN, VERILEN)
YON_ADLARI = {ALINAN: "Alınan Söz (Müşteri)", VERILEN: "Verilen Söz (Tedarikçi)"}
YONTEMLER = ("Havale/EFT", "Nakit", "Kredi Kartı", "Çek", "Senet", "Diğer")

D_BEKLENIYOR = "Bekleniyor"
D_YAKLASIYOR = "Yaklaşıyor"
D_BUGUN = "Bugün"
D_GECIKTI = "Gecikti"
D_KISMEN = "Kısmen Karşılandı"
D_TAMAM = "Tamamlandı"
D_ERTELENDI = "Ertelendi"
D_IPTAL = "İptal"
DURUMLAR = (D_BEKLENIYOR, D_YAKLASIYOR, D_BUGUN, D_GECIKTI, D_KISMEN, D_TAMAM, D_ERTELENDI, D_IPTAL)

VARSAYILAN_ESIK = 3
KURUS = Decimal("0.01")
TOLERANS = Decimal("0.005")


def _d(deger) -> Decimal:
    if deger is None or deger == "":
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger).strip().replace(" ", ""))
    except (InvalidOperation, ValueError):
        raise ValueError("Tutar geçersiz.")


def _kurus(deger) -> Decimal:
    return _d(deger).quantize(KURUS)


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.kullanici_adi or oturum.ad_soyad
    except Exception:
        return None


class OdemeSozuService:
    _hazir_motor = None

    # --- Şema / ayar ---
    @classmethod
    def schema_hazirla(cls, motor=None) -> None:
        import database.database as veritabani

        motor = motor or veritabani.engine
        if motor is None or motor is cls._hazir_motor:
            return
        for model in (OdemeSozu, OdemeSozuFatura, OdemeSozuBaglanti, OdemeSozuGecmis, OdemeSozuAyar):
            model.__table__.create(bind=motor, checkfirst=True)
        cls._hazir_motor = motor

    @staticmethod
    def _tablo_var(session) -> bool:
        from sqlalchemy import inspect as sa_inspect

        motor = session.get_bind()
        if motor is not None and motor is OdemeSozuService._hazir_motor:
            return True
        return sa_inspect(session.connection()).has_table(OdemeSozu.__tablename__)

    @staticmethod
    def esik_gun() -> int:
        OdemeSozuService.schema_hazirla()
        with get_session() as session:
            ayar = session.get(OdemeSozuAyar, "yaklasiyor_esik_gun")
            try:
                return max(0, int(ayar.deger)) if ayar else VARSAYILAN_ESIK
            except ValueError:
                return VARSAYILAN_ESIK

    @staticmethod
    def esik_gun_ayarla(gun: int) -> None:
        yazma_zorunlu("finans_duzenleme")
        gun = int(gun)
        if gun < 0 or gun > 60:
            raise ValueError("Eşik 0–60 gün arasında olmalıdır.")
        OdemeSozuService.schema_hazirla()
        with get_session() as session:
            ayar = session.get(OdemeSozuAyar, "yaklasiyor_esik_gun")
            if ayar is None:
                session.add(OdemeSozuAyar(anahtar="yaklasiyor_esik_gun", deger=str(gun)))
            else:
                ayar.deger = str(gun)

    # --- Yardımcılar ---
    @staticmethod
    def _gecmis(session, soz: OdemeSozu, islem: str, *, eski=None, yeni=None, aciklama=None) -> None:
        session.add(
            OdemeSozuGecmis(
                soz_id=soz.id,
                zaman=datetime.now(),
                kullanici=_kullanici(),
                islem=islem,
                eski_deger=None if eski is None else str(eski)[:200],
                yeni_deger=None if yeni is None else str(yeni)[:200],
                aciklama=(aciklama or "").strip()[:500] or None,
            )
        )

    @staticmethod
    def _getir_kilitli(session, soz_id: int) -> OdemeSozu:
        soz = session.get(OdemeSozu, int(soz_id))
        if soz is None:
            raise ValueError("Ödeme sözü bulunamadı.")
        return soz

    @staticmethod
    def _evrak_gecerli(session, belge_no: str) -> bool:
        """Bağlı ödeme evrakı hâlâ geçerli mi (iptal/silinmiş evrak sözü karşılamaz)."""
        from database.models.cari import CariIslem
        from database.models.finans import CariVirmanMakbuzu, KasaMakbuzu

        makbuz = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == belge_no))
        if makbuz is not None:
            return (makbuz.durum or "") != "IPTAL"
        virman = session.scalar(
            select(CariVirmanMakbuzu).where(
                (CariVirmanMakbuzu.belge_no == belge_no)
                | (CariVirmanMakbuzu.tahsilat_belge_no == belge_no)
                | (CariVirmanMakbuzu.odeme_belge_no == belge_no)
            )
        )
        if virman is not None:
            return (getattr(virman, "durum", "") or "") != "IPTAL"
        return session.scalar(select(CariIslem.id).where(CariIslem.belge_no == belge_no).limit(1)) is not None

    @staticmethod
    def _aktif_baglantilar(session, soz: OdemeSozu) -> list[OdemeSozuBaglanti]:
        return [
            b for b in soz.baglantilar
            if not b.iptal and OdemeSozuService._evrak_gecerli(session, b.evrak_belge_no)
        ]

    @staticmethod
    def durum_hesapla(soz_ozet: dict, bugun: date | None = None, esik: int = VARSAYILAN_ESIK) -> dict:
        """Durum etiketleri: ana durum + (Kısmen Karşılandı / Ertelendi)."""
        bugun = bugun or date.today()
        tutar = soz_ozet["tutar"]
        gerceklesen = soz_ozet["gerceklesen"]
        kapanis = soz_ozet.get("kapanis")
        etiketler: list[str] = []
        if kapanis == "IPTAL":
            ana = D_IPTAL
        elif gerceklesen + TOLERANS >= tutar or kapanis == "TAMAMLANDI":
            ana = D_TAMAM
        else:
            gun = (soz_ozet["vade_tarihi"] - bugun).days
            if gun < 0:
                ana = D_GECIKTI
            elif gun == 0:
                ana = D_BUGUN
            elif gun <= esik:
                ana = D_YAKLASIYOR
            else:
                ana = D_BEKLENIYOR
            if gerceklesen > 0:
                etiketler.append(D_KISMEN)
            if soz_ozet.get("ertelendi"):
                etiketler.append(D_ERTELENDI)
        acik = ana not in (D_IPTAL, D_TAMAM)
        return {
            "durum": ana,
            "etiketler": etiketler,
            "durum_metni": " · ".join(etiketler + [ana]) if etiketler else ana,
            "acik": acik,
            "gecikme_gunu": max(0, (bugun - soz_ozet["vade_tarihi"]).days) if acik else 0,
        }

    @staticmethod
    def _ozet(session, soz: OdemeSozu, bugun: date, esik: int, cari=None) -> dict[str, Any]:
        aktif = OdemeSozuService._aktif_baglantilar(session, soz)
        gerceklesen = _kurus(sum((_d(b.tutar) for b in aktif), Decimal("0")))
        tutar = _kurus(soz.tutar)
        ozet = {
            "id": int(soz.id),
            "cari_id": int(soz.cari_id),
            "cari_kodu": getattr(cari, "cari_kodu", "") or "",
            "cari_unvan": getattr(cari, "unvan", "") or "",
            "yon": soz.yon,
            "yon_adi": YON_ADLARI.get(soz.yon, soz.yon),
            "soz_tarihi": soz.soz_tarihi,
            "vade_tarihi": soz.vade_tarihi,
            "tutar": tutar,
            "gerceklesen": gerceklesen,
            "kalan": max(_kurus(tutar - gerceklesen), Decimal("0")) if soz.kapanis is None else Decimal("0"),
            "para_birimi": soz.para_birimi or "TRY",
            "yontem": soz.yontem,
            "gorusulen_kisi": soz.gorusulen_kisi or "",
            "aciklama": soz.aciklama or "",
            "sorumlu": soz.sorumlu or "",
            "kapanis": soz.kapanis,
            "ertelendi": bool(soz.ertelendi),
            "son_not": soz.son_not or "",
            "son_not_tarihi": soz.son_not_tarihi,
            "hatirlat_tarihi": soz.hatirlat_tarihi,
            "olusturan": soz.olusturan or "",
            "olusturma": soz.olusturma,
            "faturalar": [(f.belge_no, _kurus(f.tutar)) for f in soz.faturalar],
        }
        ozet.update(OdemeSozuService.durum_hesapla(ozet, bugun, esik))
        if soz.kapanis == "TAMAMLANDI":
            ozet["kalan"] = Decimal("0")
        return ozet

    # --- Kayıt ---
    @staticmethod
    def _dogrula(veriler: dict) -> dict:
        yon = (veriler.get("yon") or "").upper()
        if yon not in YONLER:
            raise ValueError("Söz yönü seçin (Alınan / Verilen).")
        soz_tarihi = veriler.get("soz_tarihi")
        vade = veriler.get("vade_tarihi")
        if not isinstance(soz_tarihi, date):
            raise ValueError("Söz tarihi zorunludur.")
        if not isinstance(vade, date):
            raise ValueError("Vaat edilen ödeme tarihi zorunludur.")
        tutar = _kurus(veriler.get("tutar"))
        if tutar <= 0:
            raise ValueError("Tutar sıfırdan büyük olmalıdır.")
        yontem = veriler.get("yontem") or "Havale/EFT"
        if yontem not in YONTEMLER:
            raise ValueError("Ödeme yöntemi geçersiz.")
        pb = (veriler.get("para_birimi") or "TRY").upper()[:3]
        return {
            "yon": yon,
            "soz_tarihi": soz_tarihi,
            "vade_tarihi": vade,
            "tutar": tutar,
            "yontem": yontem,
            "para_birimi": pb,
            "gorusulen_kisi": (veriler.get("gorusulen_kisi") or "").strip()[:120] or None,
            "aciklama": (veriler.get("aciklama") or "").strip()[:500] or None,
            "sorumlu": (veriler.get("sorumlu") or "").strip()[:120] or None,
        }

    @staticmethod
    def olustur(veriler: dict, faturalar: Iterable[tuple[str, Any]] = ()) -> int:
        """Yeni söz. faturalar: [(fatura_no, tutar)] — isteğe bağlı; faturasız (avans) söz serbest."""
        yazma_zorunlu("cari_duzenleme")
        temiz = OdemeSozuService._dogrula(veriler)
        cari_id = veriler.get("cari_id")
        if not cari_id:
            raise ValueError("Cari seçin.")
        fatura_satirlari = []
        for belge_no, tutar in faturalar or ():
            belge_no = (belge_no or "").strip()
            t = _kurus(tutar)
            if not belge_no or t <= 0:
                raise ValueError("Bağlı fatura satırında fatura no ve pozitif tutar zorunludur.")
            fatura_satirlari.append((belge_no, t))
        if sum((t for _, t in fatura_satirlari), Decimal("0")) > temiz["tutar"] + TOLERANS:
            raise ValueError("Bağlı fatura tutarları söz tutarını aşamaz.")
        OdemeSozuService.schema_hazirla()
        from database.models.cari import Cari

        with get_session() as session:
            cari = session.get(Cari, int(cari_id))
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            soz = OdemeSozu(cari_id=int(cari_id), olusturan=_kullanici(), olusturma=datetime.now(),
                            ertelendi=False, **temiz)
            for belge_no, t in fatura_satirlari:
                soz.faturalar.append(OdemeSozuFatura(belge_no=belge_no, tutar=t))
            session.add(soz)
            session.flush()
            OdemeSozuService._gecmis(
                session, soz, "OLUSTURMA",
                yeni=f"{temiz['tutar']} {temiz['para_birimi']} · {temiz['vade_tarihi']:%d.%m.%Y} · {temiz['yontem']}",
                aciklama=temiz["aciklama"],
            )
            return int(soz.id)

    @staticmethod
    def _acik_olmali(soz: OdemeSozu) -> None:
        if soz.kapanis == "IPTAL":
            raise ValueError("İptal edilmiş söz değiştirilemez.")
        if soz.kapanis == "TAMAMLANDI":
            raise ValueError("Tamamlanmış söz değiştirilemez.")

    @staticmethod
    def ertele(soz_id: int, yeni_vade: date, aciklama: str) -> None:
        yazma_zorunlu("cari_duzenleme")
        if not isinstance(yeni_vade, date):
            raise ValueError("Yeni ödeme tarihi zorunludur.")
        if not (aciklama or "").strip():
            raise ValueError("Erteleme açıklaması zorunludur.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            OdemeSozuService._acik_olmali(soz)
            if yeni_vade == soz.vade_tarihi:
                raise ValueError("Yeni tarih mevcut tarihle aynı.")
            eski = soz.vade_tarihi
            soz.vade_tarihi = yeni_vade
            soz.ertelendi = True
            soz.guncelleyen, soz.guncelleme = _kullanici(), datetime.now()
            OdemeSozuService._gecmis(session, soz, "ERTELEME", eski=f"{eski:%d.%m.%Y}",
                                     yeni=f"{yeni_vade:%d.%m.%Y}", aciklama=aciklama)

    @staticmethod
    def tutar_degistir(soz_id: int, yeni_tutar, aciklama: str) -> None:
        yazma_zorunlu("cari_duzenleme")
        yeni = _kurus(yeni_tutar)
        if yeni <= 0:
            raise ValueError("Tutar sıfırdan büyük olmalıdır.")
        if not (aciklama or "").strip():
            raise ValueError("Değişiklik açıklaması zorunludur.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            OdemeSozuService._acik_olmali(soz)
            gerceklesen = sum((_d(b.tutar) for b in OdemeSozuService._aktif_baglantilar(session, soz)),
                              Decimal("0"))
            if yeni + TOLERANS < gerceklesen:
                raise ValueError(f"Yeni tutar gerçekleşen tutarın ({_kurus(gerceklesen)}) altına inemez.")
            eski = _kurus(soz.tutar)
            soz.tutar = yeni
            soz.guncelleyen, soz.guncelleme = _kullanici(), datetime.now()
            OdemeSozuService._gecmis(session, soz, "TUTAR", eski=eski, yeni=yeni, aciklama=aciklama)

    @staticmethod
    def yontem_degistir(soz_id: int, yeni_yontem: str, aciklama: str) -> None:
        yazma_zorunlu("cari_duzenleme")
        if yeni_yontem not in YONTEMLER:
            raise ValueError("Ödeme yöntemi geçersiz.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            OdemeSozuService._acik_olmali(soz)
            if soz.yontem == yeni_yontem:
                return
            eski = soz.yontem
            soz.yontem = yeni_yontem
            soz.guncelleyen, soz.guncelleme = _kullanici(), datetime.now()
            OdemeSozuService._gecmis(session, soz, "YONTEM", eski=eski, yeni=yeni_yontem, aciklama=aciklama)

    @staticmethod
    def gorusme_notu(soz_id: int, not_metni: str, *, hatirlat_tarihi: date | None = None) -> None:
        """Görüşme notu ("görüştüm", "yarın ara"…); hatırlatma tarihi isteğe bağlı."""
        yazma_zorunlu("cari_duzenleme")
        metin = (not_metni or "").strip()
        if not metin:
            raise ValueError("Not boş olamaz.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            soz.son_not = metin[:500]
            soz.son_not_tarihi = datetime.now()
            if hatirlat_tarihi is not None:
                soz.hatirlat_tarihi = hatirlat_tarihi
            OdemeSozuService._gecmis(
                session, soz, "GORUSME",
                yeni=f"Hatırlat: {hatirlat_tarihi:%d.%m.%Y}" if hatirlat_tarihi else None,
                aciklama=metin,
            )

    @staticmethod
    def iptal_et(soz_id: int, neden: str) -> None:
        yazma_zorunlu("cari_duzenleme")
        if not (neden or "").strip():
            raise ValueError("İptal nedeni zorunludur.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            OdemeSozuService._acik_olmali(soz)
            soz.kapanis = "IPTAL"
            soz.kapanis_nedeni = neden.strip()[:300]
            soz.guncelleyen, soz.guncelleme = _kullanici(), datetime.now()
            OdemeSozuService._gecmis(session, soz, "IPTAL", aciklama=neden)

    @staticmethod
    def elle_tamamla(soz_id: int, neden: str) -> None:
        """Yetkili düzeltme: sözü tamamlandı sayar; hiçbir para hareketi oluşturmaz."""
        yazma_zorunlu("finans_duzenleme", mesaj="Sözü elle tamamlamak için finans düzenleme yetkisi gerekir.")
        if not (neden or "").strip():
            raise ValueError("Düzeltme gerekçesi zorunludur.")
        with get_session() as session:
            soz = OdemeSozuService._getir_kilitli(session, soz_id)
            OdemeSozuService._acik_olmali(soz)
            soz.kapanis = "TAMAMLANDI"
            soz.kapanis_nedeni = neden.strip()[:300]
            soz.guncelleyen, soz.guncelleme = _kullanici(), datetime.now()
            OdemeSozuService._gecmis(session, soz, "DUZELTME", yeni="Elle tamamlandı (para hareketi yok)",
                                     aciklama=neden)

    # --- Evrak bağlantısı ---
    @staticmethod
    def baglanti_ekle(
        soz_id: int,
        *,
        evrak_turu: str,
        evrak_belge_no: str,
        tutar,
        evrak_tutari,
        para_birimi: str = "TRY",
        tarih: date | None = None,
        evrak_id: int | None = None,
        sonradan: bool = False,
    ) -> int:
        """Gerçek ödeme evrakını söze bağlar. Söz kalanını ve evrak tutarını aşamaz."""
        if sonradan:
            yazma_zorunlu("finans_duzenleme", mesaj="Sonradan söz bağlamak için finans düzenleme yetkisi gerekir.")
        else:
            yazma_zorunlu("cari_duzenleme")
        OdemeSozuService.schema_hazirla()
        with get_session() as session:
            return OdemeSozuService.baglanti_ekle_oturum(
                session, soz_id, evrak_turu=evrak_turu, evrak_belge_no=evrak_belge_no, tutar=tutar,
                evrak_tutari=evrak_tutari, para_birimi=para_birimi, tarih=tarih, evrak_id=evrak_id,
            )

    @staticmethod
    def baglanti_ekle_oturum(session, soz_id, *, evrak_turu, evrak_belge_no, tutar, evrak_tutari,
                             para_birimi="TRY", tarih=None, evrak_id=None) -> int:
        tutar = _kurus(tutar)
        evrak_tutari = _kurus(evrak_tutari)
        belge = (evrak_belge_no or "").strip()
        if not belge:
            raise ValueError("Evrak numarası yok; önce evrakı kaydedin.")
        if tutar <= 0:
            raise ValueError("Bağlantı tutarı sıfırdan büyük olmalıdır.")
        soz = OdemeSozuService._getir_kilitli(session, soz_id)
        OdemeSozuService._acik_olmali(soz)
        if (para_birimi or "TRY").upper() != (soz.para_birimi or "TRY").upper():
            raise ValueError("Farklı para birimindeki evrak bu söze bağlanamaz.")
        if not OdemeSozuService._evrak_gecerli(session, belge):
            raise ValueError(f"{belge} geçerli (iptal edilmemiş) bir ödeme evrakı değil.")
        gerceklesen = sum((_d(b.tutar) for b in OdemeSozuService._aktif_baglantilar(session, soz)), Decimal("0"))
        kalan = _kurus(_d(soz.tutar) - gerceklesen)
        if tutar > kalan + TOLERANS:
            raise ValueError(f"Bağlantı tutarı sözün kalanını ({kalan}) aşamaz.")
        evrak_bagli = sum(
            (_d(b.tutar) for b in session.scalars(
                select(OdemeSozuBaglanti).where(
                    OdemeSozuBaglanti.evrak_belge_no == belge, OdemeSozuBaglanti.iptal.is_(False)
                )
            ).all()),
            Decimal("0"),
        )
        if evrak_tutari > 0 and evrak_bagli + tutar > evrak_tutari + TOLERANS:
            raise ValueError(
                f"{belge} evrakının sözlere bağlanan toplamı evrak tutarını ({evrak_tutari}) aşamaz."
            )
        b = OdemeSozuBaglanti(
            soz_id=soz.id, evrak_turu=evrak_turu[:40], evrak_belge_no=belge, evrak_id=evrak_id,
            evrak_tutari=evrak_tutari, tutar=tutar, para_birimi=(para_birimi or "TRY").upper(),
            tarih=tarih or date.today(), kullanici=_kullanici(), olusturma=datetime.now(), iptal=False,
        )
        session.add(b)
        session.flush()
        OdemeSozuService._gecmis(session, soz, "BAGLANTI", yeni=f"{belge} · {tutar}",
                                 aciklama=f"{evrak_turu} bağlandı")
        return int(b.id)

    @staticmethod
    def evrak_baglantilarini_iptal(session, evrak_belge_no: str, *, neden: str) -> int:
        """Evrak iptalinde söz bağlantılarını geri alır (kayıt silinmez, iptal işaretlenir)."""
        if not evrak_belge_no or not OdemeSozuService._tablo_var(session):
            return 0
        sayi = 0
        for b in session.scalars(
            select(OdemeSozuBaglanti).where(
                OdemeSozuBaglanti.evrak_belge_no == evrak_belge_no, OdemeSozuBaglanti.iptal.is_(False)
            )
        ).all():
            b.iptal = True
            b.iptal_zamani = datetime.now()
            b.iptal_kullanici = _kullanici()
            b.iptal_nedeni = (neden or "")[:300] or None
            soz = session.get(OdemeSozu, b.soz_id)
            if soz is not None:
                OdemeSozuService._gecmis(session, soz, "BAGLANTI_IPTAL", eski=f"{b.evrak_belge_no} · {b.tutar}",
                                         aciklama=neden)
            sayi += 1
        return sayi

    @staticmethod
    def evrak_tutari_kontrol(session, evrak_belge_no: str, yeni_tutar) -> None:
        if not evrak_belge_no or not OdemeSozuService._tablo_var(session):
            return
        bagli = sum(
            (_d(b.tutar) for b in session.scalars(
                select(OdemeSozuBaglanti).where(
                    OdemeSozuBaglanti.evrak_belge_no == evrak_belge_no, OdemeSozuBaglanti.iptal.is_(False)
                )
            ).all()),
            Decimal("0"),
        )
        if bagli > _d(yeni_tutar) + TOLERANS:
            raise ValueError(
                f"Bu evrak ödeme sözlerine {_kurus(bagli)} bağlı; yeni tutar bunun altına inemez. "
                "Önce söz bağlantısını kaldırın."
            )

    @staticmethod
    def evrak_bilgisi(belge_no: str, cari_id: int | None = None) -> dict[str, Any] | None:
        """Sonradan bağlama için kayıtlı ödeme evrakının türü/tutarı (bulunamazsa None)."""
        from database.models.cari import CariIslem
        from database.models.finans import KasaMakbuzu

        belge = (belge_no or "").strip()
        if not belge:
            return None
        with get_session() as session:
            makbuz = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == belge))
            if makbuz is not None:
                if cari_id is not None and int(makbuz.cari_id) != int(cari_id):
                    return None
                return {
                    "evrak_turu": "Tahsilat Makbuzu" if makbuz.makbuz_turu == "TAHSILAT" else "Ödeme Makbuzu",
                    "tutar": _kurus(makbuz.tutar),
                    "para_birimi": (getattr(makbuz, "para_birimi", None) or "TRY").upper(),
                    "tarih": makbuz.tarih,
                    "evrak_id": int(makbuz.id),
                    "gecerli": (makbuz.durum or "") != "IPTAL",
                }
            sorgu = select(CariIslem).where(CariIslem.belge_no == belge)
            if cari_id is not None:
                sorgu = sorgu.where(CariIslem.cari_id == int(cari_id))
            islemler = session.scalars(sorgu).all()
            if not islemler:
                return None
            ilk = islemler[0]
            dovizli = (ilk.para_birimi or "TRY").upper() != "TRY"
            borc = sum((_d(i.doviz_borc if dovizli else i.borc) for i in islemler), Decimal("0"))
            alacak = sum((_d(i.doviz_alacak if dovizli else i.alacak) for i in islemler), Decimal("0"))
            return {
                "evrak_turu": ilk.islem_turu or "Ödeme Evrakı",
                "tutar": _kurus(max(borc, alacak)),
                "para_birimi": (ilk.para_birimi or "TRY").upper(),
                "tarih": ilk.tarih,
                "evrak_id": None,
                "gecerli": True,
            }

    @staticmethod
    def baglanti_kaldir(baglanti_id: int, neden: str) -> None:
        yazma_zorunlu("finans_duzenleme", mesaj="Söz bağlantısını kaldırmak için finans düzenleme yetkisi gerekir.")
        if not (neden or "").strip():
            raise ValueError("Gerekçe zorunludur.")
        with get_session() as session:
            b = session.get(OdemeSozuBaglanti, int(baglanti_id))
            if b is None or b.iptal:
                raise ValueError("Bağlantı bulunamadı.")
            b.iptal = True
            b.iptal_zamani = datetime.now()
            b.iptal_kullanici = _kullanici()
            b.iptal_nedeni = neden.strip()[:300]
            soz = session.get(OdemeSozu, b.soz_id)
            OdemeSozuService._gecmis(session, soz, "BAGLANTI_IPTAL", eski=f"{b.evrak_belge_no} · {b.tutar}",
                                     aciklama=neden)

    # --- Sorgular ---
    @staticmethod
    def _sorgu(session, *, cari_id=None, yon=None):
        sorgu = select(OdemeSozu).options(
            selectinload(OdemeSozu.faturalar), selectinload(OdemeSozu.baglantilar)
        )
        if cari_id is not None:
            sorgu = sorgu.where(OdemeSozu.cari_id == int(cari_id))
        if yon:
            sorgu = sorgu.where(OdemeSozu.yon == yon)
        return sorgu.order_by(OdemeSozu.vade_tarihi, OdemeSozu.id)

    @staticmethod
    def liste(
        *,
        cari_id: int | None = None,
        yon: str | None = None,
        sorumlu: str | None = None,
        vade_bas: date | None = None,
        vade_bit: date | None = None,
        durum: str | None = None,
        yontem: str | None = None,
        para_birimi: str | None = None,
        sadece_acik: bool = False,
        bugun: date | None = None,
    ) -> list[dict[str, Any]]:
        from database.models.cari import Cari

        OdemeSozuService.schema_hazirla()
        bugun = bugun or date.today()
        esik = OdemeSozuService.esik_gun()
        sonuc = []
        with get_session() as session:
            cariler: dict[int, Any] = {}
            for soz in session.scalars(OdemeSozuService._sorgu(session, cari_id=cari_id, yon=yon)).all():
                if vade_bas and soz.vade_tarihi < vade_bas:
                    continue
                if vade_bit and soz.vade_tarihi > vade_bit:
                    continue
                if yontem and soz.yontem != yontem:
                    continue
                if para_birimi and (soz.para_birimi or "TRY") != para_birimi:
                    continue
                if sorumlu and (sorumlu.casefold() not in (soz.sorumlu or "").casefold()):
                    continue
                if soz.cari_id not in cariler:
                    cariler[soz.cari_id] = session.get(Cari, soz.cari_id)
                oz = OdemeSozuService._ozet(session, soz, bugun, esik, cariler[soz.cari_id])
                if sadece_acik and not oz["acik"]:
                    continue
                if durum and durum != oz["durum"] and durum not in oz["etiketler"]:
                    continue
                sonuc.append(oz)
        return sonuc

    @staticmethod
    def getir(soz_id: int, bugun: date | None = None) -> dict[str, Any]:
        from database.models.cari import Cari

        OdemeSozuService.schema_hazirla()
        with get_session() as session:
            soz = session.get(OdemeSozu, int(soz_id))
            if soz is None:
                raise ValueError("Ödeme sözü bulunamadı.")
            oz = OdemeSozuService._ozet(session, soz, bugun or date.today(), OdemeSozuService.esik_gun(),
                                        session.get(Cari, soz.cari_id))
            oz["kapanis_nedeni"] = soz.kapanis_nedeni or ""
            oz["gecmis"] = [
                {"zaman": g.zaman, "kullanici": g.kullanici or "", "islem": g.islem,
                 "eski": g.eski_deger or "", "yeni": g.yeni_deger or "", "aciklama": g.aciklama or ""}
                for g in soz.gecmis
            ]
            oz["baglantilar"] = [
                {"id": int(b.id), "evrak_turu": b.evrak_turu, "evrak_no": b.evrak_belge_no,
                 "tutar": _kurus(b.tutar), "evrak_tutari": _kurus(b.evrak_tutari),
                 "para_birimi": b.para_birimi, "tarih": b.tarih, "kullanici": b.kullanici or "",
                 "iptal": bool(b.iptal) or not OdemeSozuService._evrak_gecerli(session, b.evrak_belge_no),
                 "iptal_nedeni": b.iptal_nedeni or ("" if not b.iptal else "")}
                for b in soz.baglantilar
            ]
            return oz

    @staticmethod
    def acik_sozler(cari_id: int, yon: str, para_birimi: str = "TRY") -> list[dict[str, Any]]:
        return [
            s for s in OdemeSozuService.liste(cari_id=cari_id, yon=yon, para_birimi=para_birimi, sadece_acik=True)
            if s["kalan"] > 0
        ]

    @staticmethod
    def cari_ozeti(cari_id: int, bugun: date | None = None) -> dict[str, Any]:
        """Cari kart özeti: yaklaşan adet/tutar, bugün vadesi gelen, geciken tutar (açık sözler)."""
        bugun = bugun or date.today()
        sozler = OdemeSozuService.liste(cari_id=cari_id, sadece_acik=True, bugun=bugun)
        yaklasan = [s for s in sozler if s["durum"] == D_YAKLASIYOR]
        bugunku = [s for s in sozler if s["durum"] == D_BUGUN]
        geciken = [s for s in sozler if s["durum"] == D_GECIKTI]

        oz = {
            "acik_adet": len(sozler),
            "yaklasan_adet": len(yaklasan),
            "yaklasan_tutar": _para_toplam(yaklasan),
            "bugun_adet": len(bugunku),
            "bugun_tutar": _para_toplam(bugunku),
            "geciken_adet": len(geciken),
            "geciken_tutar": _para_toplam(geciken),
            "acik_tutar": _para_toplam(sozler),
        }
        if sozler:
            oz["metin"] = (
                f"Ödeme sözleri: {len(sozler)} açık"
                f"  |  Yaklaşan {len(yaklasan)} / {para_toplam_metni(oz['yaklasan_tutar'])}"
                f"  |  Bugün {len(bugunku)} / {para_toplam_metni(oz['bugun_tutar'])}"
                f"  |  Geciken {para_toplam_metni(oz['geciken_tutar'])}"
            )
        else:
            oz["metin"] = ""
        return oz

    @staticmethod
    def takvim_ozeti(bugun: date | None = None) -> dict[str, Any]:
        """Tahmini nakit akışı (kasa bakiyesine eklenmez): 7/14/30 gün giriş/çıkış ve günlük özetler."""
        bugun = bugun or date.today()
        sozler = OdemeSozuService.liste(sadece_acik=True, bugun=bugun)
        araliklar = {}
        for gun in (7, 14, 30):
            bitis = bugun + timedelta(days=gun)
            giris = [s for s in sozler if s["yon"] == ALINAN and s["vade_tarihi"] <= bitis]
            cikis = [s for s in sozler if s["yon"] == VERILEN and s["vade_tarihi"] <= bitis]
            araliklar[gun] = {
                "giris": _para_toplam(giris),
                "cikis": _para_toplam(cikis),
            }
        return {
            "araliklar": araliklar,
            "bugun_giris": _para_toplam([s for s in sozler if s["yon"] == ALINAN and s["durum"] == D_BUGUN]),
            "bugun_cikis": _para_toplam([s for s in sozler if s["yon"] == VERILEN and s["durum"] == D_BUGUN]),
            "geciken_musteri": _para_toplam([s for s in sozler if s["yon"] == ALINAN and s["durum"] == D_GECIKTI]),
            "geciken_tedarikci": _para_toplam(
                [s for s in sozler if s["yon"] == VERILEN and s["durum"] == D_GECIKTI]
            ),
            "not": "Tahmini nakit akışıdır; kasa/banka bakiyesine eklenmez.",
        }

    @staticmethod
    def gunluk_liste(gun: date) -> list[dict[str, Any]]:
        return [s for s in OdemeSozuService.liste(sadece_acik=True, bugun=date.today()) if s["vade_tarihi"] == gun]

    @staticmethod
    def hatirlatmalar(bugun: date | None = None) -> list[dict[str, Any]]:
        """Uygulama içi hatırlatmalar: vadesi gelen/geçen veya hatırlatma tarihi gelen açık sözler."""
        bugun = bugun or date.today()
        return [
            s for s in OdemeSozuService.liste(sadece_acik=True, bugun=bugun)
            if s["vade_tarihi"] <= bugun or (s["hatirlat_tarihi"] and s["hatirlat_tarihi"] <= bugun)
        ]

    @staticmethod
    def hatirlatma_metni(bugun: date | None = None) -> str:
        """Ana panel için kısa hatırlatma; hatırlatılacak söz yoksa boş metin."""
        bugun = bugun or date.today()
        liste = OdemeSozuService.hatirlatmalar(bugun)
        if not liste:
            return ""
        oz = OdemeSozuService.takvim_ozeti(bugun)
        parcalar = [f"{len(liste)} söz takip bekliyor"]
        for etiket, anahtar in (
            ("Bugün beklenen giriş", "bugun_giris"),
            ("Bugün söz verilen çıkış", "bugun_cikis"),
            ("Geciken müşteri sözleri", "geciken_musteri"),
            ("Geciken tedarikçi sözleri", "geciken_tedarikci"),
        ):
            if oz[anahtar]:
                parcalar.append(f"{etiket}: {para_toplam_metni(oz[anahtar])}")
        return "  |  ".join(parcalar)

    @staticmethod
    def csv_yaz(satirlar: list[dict[str, Any]], yol: str) -> None:
        basliklar = ("Cari Kodu", "Cari", "Yön", "Söz Tarihi", "Vade", "Tutar", "Gerçekleşen", "Kalan",
                     "Döviz", "Yöntem", "Durum", "Sorumlu", "Son Not")
        with open(yol, "w", newline="", encoding="utf-8-sig") as dosya:
            yazici = csv.writer(dosya, delimiter=";")
            yazici.writerow(basliklar)
            for s in satirlar:
                yazici.writerow([
                    s["cari_kodu"], s["cari_unvan"], s["yon_adi"], f"{s['soz_tarihi']:%d.%m.%Y}",
                    f"{s['vade_tarihi']:%d.%m.%Y}", _para(s["tutar"]), _para(s["gerceklesen"]),
                    _para(s["kalan"]), s["para_birimi"], s["yontem"], s["durum_metni"], s["sorumlu"],
                    s["son_not"],
                ])


def _para_toplam(sozler: list[dict]) -> dict[str, Decimal]:
    """Para birimi bazında kalan toplamı (dövizler birbirine eklenmez)."""
    toplam: dict[str, Decimal] = {}
    for s in sozler:
        toplam[s["para_birimi"]] = toplam.get(s["para_birimi"], Decimal("0")) + s["kalan"]
    return {k: _kurus(v) for k, v in sorted(toplam.items())}


def _para(deger) -> str:
    try:
        d = Decimal(str(deger))
    except Exception:
        return str(deger)
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def para_toplam_metni(toplam: dict[str, Decimal]) -> str:
    if not toplam:
        return "0,00"
    return " + ".join(f"{_para(v)} {k}" for k, v in toplam.items())
