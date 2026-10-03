"""Stok uyarıları ve sipariş ihtiyacı servisi.

Miktarlar (temel birim):
  fiziksel    = ürün–depo açık lot kalanı toplamı (stok hareketleriyle aynı kaynak)
  rezerve     = 0 — programda stok rezervasyon modeli yok (destek sınırı; uydurulmaz)
  satılabilir = fiziksel − rezerve
  beklenen    = kesinleşmiş (taslak/iptal dışı) alış sipariş satırlarında henüz faturalanmamış miktar.
                Stok girişi alış faturasıyla oluştuğu için teslim = faturalanan miktar sayılır;
                irsaliyeli ama faturalanmamış miktar ayrıca gösterilir (stokta da beklenende de iki kez sayılmaz).
  öneri       = maksimum(0, hedef − satılabilir − beklenen) → alım birimine çevrilir, paket katına yukarı yuvarlanır.
                Hedef yoksa öneri yok ("Kullanıcı belirleyecek"). Negatif stok kırpılmaz.

Yeniden değerlendirme: ``yeniden_degerlendir(session, [(stok_id, depo_id), ...])``. Stok hareketi /
lot / alış siparişi / ürün kartı değişen her oturum commit'inden hemen önce aynı işlem içinde
otomatik çağrılır (``before_commit``); hata olursa çift ``stok_uyari_bekleyenler`` kuyruğuna yazılır.
İade, iptal vb. akışlar ek bir şey yapmadan tetiklenir; gerekirse doğrudan da çağrılabilir.
"""

from __future__ import annotations

import logging
import threading
import weakref
from collections import deque
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any, Callable, Iterable

from sqlalchemy import event, func, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.database import get_session
from database.models.stok import Depo, StokBarkod, StokBirim, StokHareketi, StokKarti, StokLotu
from database.models.stok_uyari import (
    StokIhtiyac,
    StokIhtiyacGecmisi,
    StokIhtiyacSiparisBagi,
    StokUyariAyari,
    StokUyariBekleyen,
    StokUyariGenelAyar,
)

logger = logging.getLogger(__name__)

SIFIR = Decimal("0")
NEDEN_TUKENDI = "TUKENDI"
NEDEN_GIRIS_YOK = "GIRIS_YOK"
NEDEN_SATILABILIR_YOK = "SATILABILIR_YOK"
NEDEN_KRITIK = "KRITIK"
NEDEN_ETIKET = {
    NEDEN_TUKENDI: "Tükendi",
    NEDEN_GIRIS_YOK: "Stok girişi yok",
    NEDEN_SATILABILIR_YOK: "Satılabilir stok yok",
    NEDEN_KRITIK: "Kritik seviye",
}
# Sınıflandırma kuralı değiştiğinde artırılır; eski sürümle değerlendirilmiş firmada bir kez yeniden taranır.
SINIFLANDIRMA_SURUMU = "2"

DURUM_INCELENECEK = "İncelenecek"
DURUM_TASLAK_VAR = "Sipariş taslağı var"
DURUM_SIPARIS_VERILDI = "Sipariş verildi"
DURUM_KISMEN = "Kısmen karşılandı"
DURUM_TESLIM_BEKLENIYOR = "Alım karşılanmış, teslim bekleniyor"
DURUM_ERTELENDI = "Ertelendi"
DURUM_KARSILANDI = "Karşılandı"

GENEL_VARSAYILAN = {
    "takip": "1",
    "minimum": "",
    "hedef": "",
    "sesli_bildirim": "0",
    "ilk_tarama": "",
    "siniflandirma_surumu": "",
}

SIPARIS_HARIC = ("TASLAK", "İPTAL")
SATIS_SIPARIS_HARIC = ("TASLAK", "İPTAL", "FATURALI")
REZERVASYON_DESTEK_NOTU = (
    "Programda stok rezervasyonu tutulmuyor; rezerve miktar 0 kabul edilir ve satılabilir = fiziksel stoktur. "
    "Bekleyen müşteri siparişleri ayrıca gösterilir, satılabilir miktardan düşülmez."
)

_BOS_SAYI = {"toplam": 0, "tukenen": 0, "giris_yok": 0, "kritik": 0, "yeni": 0, "rozet": 0}
_son_olaylar: deque = deque(maxlen=200)
_olay_kilidi = threading.Lock()
_tablo_onbellek: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
# Tek işlemde bundan fazla çift etkilenirse (toplu içe aktarma vb.) değerlendirme kuyruğa yazılır.
SATIR_ICI_SINIR = 300
_KART_ALANLARI = ("aktif", "is_deleted", "birlestirildi_hedef_id", "minimum_stok", "birim", "varsayilan_alis_birim")


def _d(v) -> Decimal:
    if v in (None, ""):
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _dn(v) -> Decimal | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _kullanici() -> str:
    try:
        from database.session_manager import oturum

        return str(getattr(oturum, "kullanici_adi", None) or getattr(oturum, "username", None) or "")
    except Exception:
        return ""


def _tr_kucuk(metin: str | None) -> str:
    return (metin or "").strip().replace("İ", "i").replace("I", "ı").lower()


def miktar_metni(v) -> str:
    if v is None:
        return ""
    d = _d(v)
    s = f"{d:,.4f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".") or "0"


class StokUyariService:
    # ------------------------------------------------------------------ altyapı
    @staticmethod
    def tablolar_var(session) -> bool:
        try:
            bind = session.get_bind()
            motor = getattr(bind, "engine", bind)
        except Exception:
            return False
        try:
            if motor not in _tablo_onbellek:
                # Motor yerine oturumun kendi bağlantısı: tek bağlantılı havuzda (bellek içi SQLite)
                # ayrı bağlantı açıp bırakmak açık işlemi geri alır.
                _tablo_onbellek[motor] = inspect(session.connection()).has_table("stok_ihtiyaclari")
            return _tablo_onbellek[motor]
        except Exception:
            return False

    @staticmethod
    def schema_hazirla() -> None:
        from database.database import Base, engine

        Base.metadata.create_all(engine, tables=[
            StokUyariAyari.__table__, StokUyariGenelAyar.__table__, StokIhtiyac.__table__,
            StokIhtiyacGecmisi.__table__, StokIhtiyacSiparisBagi.__table__, StokUyariBekleyen.__table__,
        ])
        _tablo_onbellek.clear()

    @staticmethod
    def olaylari_al() -> list[dict]:
        """Ekran içi bildirim için son yeni/kritik olayları döndürür ve kuyruğu boşaltır."""
        with _olay_kilidi:
            olaylar = list(_son_olaylar)
            _son_olaylar.clear()
        return olaylar

    # ------------------------------------------------------------------ ayarlar
    @staticmethod
    def genel_ayarlar(session=None) -> dict[str, str]:
        def _oku(s):
            sonuc = dict(GENEL_VARSAYILAN)
            if StokUyariService.tablolar_var(s):
                for a in s.scalars(select(StokUyariGenelAyar)).all():
                    sonuc[a.anahtar] = a.deger if a.deger is not None else ""
            return sonuc

        if session is not None:
            return _oku(session)
        with get_session() as s:
            return _oku(s)

    @staticmethod
    def genel_ayar_kaydet(degerler: dict[str, Any]) -> None:
        from database.access import yazma_zorunlu

        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        for anahtar in ("minimum", "hedef"):
            if anahtar in degerler and str(degerler[anahtar] or "").strip():
                if Decimal(str(degerler[anahtar]).replace(",", ".")) < 0:
                    raise ValueError("Minimum / hedef negatif olamaz.")
        mn, hd = degerler.get("minimum"), degerler.get("hedef")
        if str(mn or "").strip() and str(hd or "").strip():
            if Decimal(str(hd).replace(",", ".")) < Decimal(str(mn).replace(",", ".")):
                raise ValueError("Hedef stok minimumdan küçük olamaz.")
        with get_session() as session:
            for anahtar, deger in degerler.items():
                if anahtar not in GENEL_VARSAYILAN:
                    continue
                metin = str(deger if deger is not None else "").strip().replace(",", ".")
                kayit = session.get(StokUyariGenelAyar, anahtar)
                if kayit is None:
                    session.add(StokUyariGenelAyar(anahtar=anahtar, deger=metin))
                else:
                    kayit.deger = metin

    @staticmethod
    def _genel_yaz(session, anahtar: str, deger: str) -> None:
        kayit = session.get(StokUyariGenelAyar, anahtar)
        if kayit is None:
            session.add(StokUyariGenelAyar(anahtar=anahtar, deger=deger))
        else:
            kayit.deger = deger

    @staticmethod
    def ayar_getir(stok_id: int, depo_id: int | None = None) -> dict[str, Any]:
        with get_session() as session:
            kayit = StokUyariService._ayar_kaydi(session, stok_id, depo_id)
            kart = session.get(StokKarti, stok_id)
            depo = session.get(Depo, depo_id) if depo_id else None
            depo = depo or session.get(Depo, StokUyariService._varsayilan_depo_id(session))
            etkin = StokUyariService.etkin_ayar(session, kart, depo.id if depo else None) if kart else {}
            return {
                "kayit": {
                    k: getattr(kayit, k, None)
                    for k in ("takip", "minimum", "hedef", "alim_birimi", "paket_kati", "tercih_tedarikci_id")
                } if kayit else {},
                "etkin": etkin,
                "birimler": StokUyariService._birim_secenekleri(kart) if kart else [],
            }

    @staticmethod
    def _birim_secenekleri(kart) -> list[str]:
        sonuc = [kart.birim or "Adet"]
        for b in getattr(kart, "birimler", None) or []:
            if getattr(b, "aktif", True) is not False and b.birim_adi not in sonuc:
                sonuc.append(b.birim_adi)
        return sonuc

    @staticmethod
    def _ayar_kaydi(session, stok_id: int, depo_id: int | None):
        q = select(StokUyariAyari).where(StokUyariAyari.stok_id == stok_id)
        q = q.where(StokUyariAyari.depo_id.is_(None)) if depo_id is None else q.where(StokUyariAyari.depo_id == depo_id)
        return session.scalar(q)

    @staticmethod
    def ayar_kaydet(stok_id: int, depo_id: int | None, veriler: dict[str, Any]) -> None:
        """Ürün (depo_id None) veya ürün–depo ayarı. Boş değer = üst seviyeden gelsin."""
        from database.access import yazma_zorunlu

        yazma_zorunlu("stok_duzenleme", "yeni_kayit")

        def _sayi(ad):
            v = veriler.get(ad)
            if v in (None, ""):
                return None
            d = Decimal(str(v).replace(",", "."))
            if d < 0:
                raise ValueError(f"{ad.capitalize()} negatif olamaz.")
            return d

        minimum, hedef, paket = _sayi("minimum"), _sayi("hedef"), _sayi("paket_kati")
        if paket is not None and paket <= 0:
            raise ValueError("Paket/koli katı sıfırdan büyük olmalı (boş bırakılabilir).")
        with get_session() as session:
            kart = session.get(StokKarti, stok_id)
            if kart is None:
                raise ValueError("Stok kartı bulunamadı.")
            alim = (veriler.get("alim_birimi") or "").strip() or None
            if alim:
                from database.stok_service import StokService

                StokService.birim_carpani_kesin(kart, alim)
            ust = StokUyariService._ayar_kaydi(session, stok_id, None) if depo_id else None
            etkin_min = minimum if minimum is not None else (_dn(ust.minimum) if ust else None)
            etkin_hedef = hedef if hedef is not None else (_dn(ust.hedef) if ust else None)
            if etkin_min is None and _d(kart.minimum_stok) > 0:
                etkin_min = _d(kart.minimum_stok)
            if etkin_min is not None and etkin_hedef is not None and etkin_hedef < etkin_min:
                raise ValueError("Hedef stok minimum stoktan küçük olamaz.")
            kayit = StokUyariService._ayar_kaydi(session, stok_id, depo_id)
            if kayit is None:
                kayit = StokUyariAyari(stok_id=stok_id, depo_id=depo_id)
                session.add(kayit)
            takip = veriler.get("takip")
            kayit.takip = None if takip is None else bool(takip)
            kayit.minimum = minimum
            kayit.hedef = hedef
            kayit.alim_birimi = alim
            kayit.paket_kati = paket
            ted = veriler.get("tercih_tedarikci_id")
            kayit.tercih_tedarikci_id = int(ted) if ted else None
            kayit.guncelleme_tarihi = datetime.now()
            kayit.guncelleyen = _kullanici()
            session.flush()
            StokUyariService.yeniden_degerlendir(session, StokUyariService._urun_ciftleri(session, stok_id))

    @staticmethod
    def etkin_ayar(session, kart, depo_id: int | None, genel: dict | None = None,
                   ayarlar: dict | None = None) -> dict[str, Any]:
        """Geçerli ayar + kaynağı (Depo / Ürün / Stok kartı / Firma)."""
        genel = genel or StokUyariService.genel_ayarlar(session)
        if ayarlar is None:
            satirlar = session.scalars(select(StokUyariAyari).where(StokUyariAyari.stok_id == kart.id)).all()
            ayarlar = {a.depo_id: a for a in satirlar}
        urun = ayarlar.get(None)
        depo = ayarlar.get(depo_id) if depo_id is not None else None
        sonuc: dict[str, Any] = {"kaynak": {}}

        def _sec(alan, ek=None):
            for etiket, kayit in (("Depo", depo), ("Ürün", urun)):
                v = getattr(kayit, alan, None) if kayit is not None else None
                if v not in (None, ""):
                    sonuc[alan] = v
                    sonuc["kaynak"][alan] = etiket
                    return
            if ek is not None:
                etiket, v = ek
                if v not in (None, ""):
                    sonuc[alan] = v
                    sonuc["kaynak"][alan] = etiket
                    return
            sonuc[alan] = None
            sonuc["kaynak"][alan] = ""

        _sec("takip", ("Firma", genel.get("takip", "1") not in ("0", "", "false", "False")))
        kart_min = _d(getattr(kart, "minimum_stok", 0))
        _sec("minimum", ("Stok kartı", kart_min) if kart_min > 0 else ("Firma", _dn(genel.get("minimum"))))
        _sec("hedef", ("Firma", _dn(genel.get("hedef"))))
        _sec("alim_birimi", ("Stok kartı", getattr(kart, "varsayilan_alis_birim", None) or kart.birim or "Adet"))
        _sec("paket_kati")
        _sec("tercih_tedarikci_id")
        sonuc["takip"] = bool(sonuc["takip"]) if sonuc["takip"] is not None else True
        sonuc["minimum"] = _dn(sonuc["minimum"])
        sonuc["hedef"] = _dn(sonuc["hedef"])
        sonuc["paket_kati"] = _dn(sonuc["paket_kati"])
        return sonuc

    # ------------------------------------------------------------------ miktarlar
    @staticmethod
    def _varsayilan_depo_id(session) -> int | None:
        depo = session.scalar(select(Depo).where(Depo.varsayilan.is_(True), Depo.aktif.is_(True)).limit(1))
        if depo is None:
            depo = session.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
        if depo is None:
            depo = session.scalar(select(Depo).where(Depo.aktif.is_(True)).order_by(Depo.id).limit(1))
        return depo.id if depo else None

    @staticmethod
    def _carpan(kart, birim: str | None) -> Decimal | None:
        from database.stok_service import BirimDonusumHatasi, StokService

        try:
            return StokService.birim_carpani_kesin(kart, birim or kart.birim)
        except BirimDonusumHatasi:
            return None

    @staticmethod
    def _fiziksel(session, stok_id: int, depo_id: int) -> Decimal:
        return _d(session.scalar(
            select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
            .where(StokLotu.stok_id == stok_id, StokLotu.depo_id == depo_id)
        ))

    @staticmethod
    def _giris_gormus(session, stok_id: int, depo_id: int) -> bool:
        """Ürün bu depoda daha önce stoğa girmiş mi (lot veya giriş hareketi)."""
        from database.stok_service import GIRIS_HAREKETLERI

        if session.scalar(select(StokLotu.id).where(
                StokLotu.stok_id == stok_id, StokLotu.depo_id == depo_id).limit(1)) is not None:
            return True
        return session.scalar(select(StokHareketi.id).where(
            StokHareketi.stok_id == stok_id, StokHareketi.depo_id == depo_id,
            StokHareketi.hareket_turu.in_(GIRIS_HAREKETLERI)).limit(1)) is not None

    @staticmethod
    def _diger_depolar(session, stok_id: int, depo_id: int) -> list[tuple[str, Decimal]]:
        rows = session.execute(
            select(Depo.ad, func.sum(StokLotu.kalan_miktar))
            .join(Depo, Depo.id == StokLotu.depo_id)
            .where(StokLotu.stok_id == stok_id, StokLotu.depo_id != depo_id)
            .group_by(Depo.ad)
        ).all()
        return [(ad, _d(m)) for ad, m in rows if _d(m) > 0]

    @staticmethod
    def _beklenen(session, kart, depo_adi: str, varsayilan_adi: str | None) -> dict[str, Any]:
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        depo_ifadesi = func.coalesce(AlisSiparisi.teslim_depo, varsayilan_adi or "")
        rows = session.execute(
            select(AlisSiparisiSatiri, AlisSiparisi.termin_tarihi)
            .join(AlisSiparisi, AlisSiparisi.id == AlisSiparisiSatiri.siparis_id)
            .where(AlisSiparisiSatiri.urun_kodu == kart.stok_kodu,
                   AlisSiparisi.durum.notin_(SIPARIS_HARIC), depo_ifadesi == depo_adi)
        ).all()
        beklenen = irsaliyeli = SIFIR
        birim_sorunu = False
        termin = None
        for ss, sip_termin in rows:
            c = StokUyariService._carpan(kart, ss.birim)
            if c is None:
                birim_sorunu = True
                c = Decimal("1")
            acik = max(SIFIR, _d(ss.miktar) - _d(ss.faturalanan_miktar))
            beklenen += acik * c
            irsaliyeli += max(SIFIR, _d(ss.irsaliyelenen_miktar) - _d(ss.faturalanan_miktar)) * c
            if acik > 0 and sip_termin and (termin is None or sip_termin < termin):
                termin = sip_termin
        return {"beklenen": beklenen, "irsaliyeli_faturasiz": irsaliyeli, "birim_sorunu": birim_sorunu,
                "en_yakin_termin": termin}

    @staticmethod
    def _musteri_talebi(session, kart, depo_adi: str, varsayilan_adi: str | None) -> Decimal:
        from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri

        depo_ifadesi = func.coalesce(SatisSiparisi.depo, varsayilan_adi or "")
        toplam = SIFIR
        for ss in session.scalars(
            select(SatisSiparisiSatiri)
            .join(SatisSiparisi, SatisSiparisi.id == SatisSiparisiSatiri.siparis_id)
            .where(SatisSiparisiSatiri.urun_kodu == kart.stok_kodu,
                   SatisSiparisi.durum.notin_(SATIS_SIPARIS_HARIC), depo_ifadesi == depo_adi)
        ).all():
            acik = max(SIFIR, _d(ss.miktar) - max(_d(ss.irsaliyelenen_miktar), _d(ss.faturalanan_miktar)))
            toplam += acik * (StokUyariService._carpan(kart, ss.birim) or Decimal("1"))
        return toplam

    @staticmethod
    def oneri_hesapla(hedef: Decimal | None, satilabilir: Decimal, beklenen: Decimal,
                      alim_carpani: Decimal, paket_kati: Decimal | None) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        """(ham_temel, öneri_alım_birimi, öneri_temel). Hedef yoksa (None, None, None)."""
        if hedef is None:
            return None, None, None
        ham = max(SIFIR, hedef - satilabilir - beklenen)
        if ham <= 0:
            return ham, SIFIR, SIFIR
        c = alim_carpani if alim_carpani and alim_carpani > 0 else Decimal("1")
        adet = ham / c
        if c != 1 or paket_kati:
            adet = adet.to_integral_value(rounding=ROUND_CEILING)
        if paket_kati and paket_kati > 0:
            adet = (adet / paket_kati).to_integral_value(rounding=ROUND_CEILING) * paket_kati
        return ham, adet, adet * c

    @staticmethod
    def hesapla(session, kart, depo, genel: dict | None = None, ayarlar: dict | None = None,
                varsayilan_adi: str | None = None) -> dict[str, Any]:
        genel = genel or StokUyariService.genel_ayarlar(session)
        if varsayilan_adi is None:
            vid = StokUyariService._varsayilan_depo_id(session)
            varsayilan_adi = session.get(Depo, vid).ad if vid else None
        ayar = StokUyariService.etkin_ayar(session, kart, depo.id, genel, ayarlar)
        fiziksel = StokUyariService._fiziksel(session, kart.id, depo.id)
        rezerve = SIFIR
        satilabilir = fiziksel - rezerve
        bek = StokUyariService._beklenen(session, kart, depo.ad, varsayilan_adi)
        minimum, hedef = ayar["minimum"], ayar["hedef"]
        nedenler: list[str] = []
        if fiziksel <= 0:
            nedenler.append(NEDEN_TUKENDI if StokUyariService._giris_gormus(session, kart.id, depo.id)
                            else NEDEN_GIRIS_YOK)
        elif satilabilir <= 0:
            nedenler.append(NEDEN_SATILABILIR_YOK)
        # Minimum tanımlı üründe sipariş ihtiyacı, tükenme / hiç giriş olmama durumundan ayrıca işaretlenir.
        if minimum is not None and minimum > 0 and satilabilir <= minimum:
            nedenler.append(NEDEN_KRITIK)
        alim_birimi = ayar["alim_birimi"] or kart.birim
        c_alim = StokUyariService._carpan(kart, alim_birimi)
        if c_alim is None:
            alim_birimi, c_alim = kart.birim, Decimal("1")
        ham, oneri_alim, oneri_temel = StokUyariService.oneri_hesapla(
            hedef, satilabilir, bek["beklenen"], c_alim, ayar["paket_kati"])
        diger = StokUyariService._diger_depolar(session, kart.id, depo.id)
        aktif_kart = bool(kart.aktif) and not bool(getattr(kart, "is_deleted", False)) \
            and not getattr(kart, "birlestirildi_hedef_id", None)
        return {
            "ayar": ayar, "fiziksel": fiziksel, "rezerve": rezerve, "satilabilir": satilabilir,
            "beklenen": bek["beklenen"], "irsaliyeli_faturasiz": bek["irsaliyeli_faturasiz"],
            "beklenen_birim_sorunu": bek["birim_sorunu"], "en_yakin_termin": bek["en_yakin_termin"],
            "minimum": minimum, "hedef": hedef, "nedenler": nedenler, "ham_ihtiyac": ham,
            "oneri_alim": oneri_alim, "oneri_temel": oneri_temel, "alim_birimi": alim_birimi,
            "alim_carpani": c_alim, "diger_depolar": diger,
            "diger_depo_stok": sum((m for _a, m in diger), SIFIR),
            "musteri_talebi": StokUyariService._musteri_talebi(session, kart, depo.ad, varsayilan_adi),
            "takip": ayar["takip"], "aktif_kart": aktif_kart,
        }

    # ------------------------------------------------------------------ yeniden değerlendirme
    @staticmethod
    def _gecmis(session, ihtiyac_id: int, islem: str, detay: str | None = None) -> None:
        session.add(StokIhtiyacGecmisi(ihtiyac_id=ihtiyac_id, islem=islem, detay=detay, kullanici=_kullanici()))

    @staticmethod
    def _urun_ciftleri(session, stok_id: int) -> list[tuple[int, int]]:
        ciftler = {(stok_id, d) for (d,) in session.execute(
            select(StokLotu.depo_id).where(StokLotu.stok_id == stok_id).distinct())}
        ciftler |= {(stok_id, d) for (d,) in session.execute(
            select(StokIhtiyac.depo_id).where(StokIhtiyac.stok_id == stok_id, StokIhtiyac.aktif.is_(True)))}
        if not ciftler:
            vid = StokUyariService._varsayilan_depo_id(session)
            if vid:
                ciftler.add((stok_id, vid))
        ayar_depolari = session.execute(
            select(StokUyariAyari.depo_id).where(StokUyariAyari.stok_id == stok_id,
                                                 StokUyariAyari.depo_id.is_not(None))).all()
        ciftler |= {(stok_id, d) for (d,) in ayar_depolari}
        return sorted(ciftler)

    @staticmethod
    def yeniden_degerlendir(session, ciftler: Iterable[tuple[int, int]]) -> list[dict]:
        """Ürün–depo çiftlerini değerlendirir; aynı oturum/işlem içinde ihtiyaç kaydını oluşturur/günceller/kapatır."""
        if not StokUyariService.tablolar_var(session):
            return []
        ciftler = sorted({(int(s), int(d)) for s, d in ciftler if s is not None and d is not None})
        if not ciftler:
            return []
        genel = StokUyariService.genel_ayarlar(session)
        vid = StokUyariService._varsayilan_depo_id(session)
        varsayilan_adi = session.get(Depo, vid).ad if vid else None
        olaylar: list[dict] = []
        simdi = datetime.now()
        for stok_id, depo_id in ciftler:
            kart = session.get(StokKarti, stok_id)
            depo = session.get(Depo, depo_id)
            if kart is None or depo is None:
                continue
            h = StokUyariService.hesapla(session, kart, depo, genel, None, varsayilan_adi)
            aktif = session.scalar(select(StokIhtiyac).where(
                StokIhtiyac.stok_id == stok_id, StokIhtiyac.depo_id == depo_id, StokIhtiyac.aktif.is_(True)))
            gerekli = bool(h["nedenler"]) and h["takip"] and h["aktif_kart"]
            if not gerekli:
                if aktif is not None:
                    neden = ("Ürün pasif" if not h["aktif_kart"] else "Takip kapalı" if not h["takip"]
                             else "Stok yeterli")
                    aktif.aktif = False
                    aktif.kapanma_tarihi = simdi
                    aktif.kapanma_nedeni = neden
                    StokUyariService._degerleri_yaz(aktif, h, simdi)
                    aktif.row_version = int(aktif.row_version or 1) + 1
                    StokUyariService._gecmis(session, aktif.id, "KAPANDI",
                                             f"{neden}; satılabilir {miktar_metni(h['satilabilir'])}")
                    olaylar.append({"tur": "KAPANDI", "stok_kodu": kart.stok_kodu, "depo": depo.ad})
                continue
            if aktif is None:
                onceki = session.scalar(select(func.count(StokIhtiyac.id)).where(
                    StokIhtiyac.stok_id == stok_id, StokIhtiyac.depo_id == depo_id)) or 0
                yeni = StokIhtiyac(stok_id=stok_id, depo_id=depo_id, aktif=True, olay_no=int(onceki) + 1,
                                   ilk_olusma=simdi, goruldu=False, row_version=1)
                StokUyariService._degerleri_yaz(yeni, h, simdi)
                try:
                    with session.begin_nested():
                        session.add(yeni)
                        session.flush()
                except IntegrityError:
                    aktif = session.scalar(select(StokIhtiyac).where(
                        StokIhtiyac.stok_id == stok_id, StokIhtiyac.depo_id == depo_id,
                        StokIhtiyac.aktif.is_(True)))
                    if aktif is None:
                        raise
                else:
                    StokUyariService._gecmis(session, yeni.id, "OLUŞTU", StokUyariService._ozet(h))
                    olay = {"tur": "YENI", "stok_kodu": kart.stok_kodu, "stok_adi": kart.stok_adi,
                            "depo": depo.ad, "nedenler": list(h["nedenler"])}
                    olaylar.append(olay)
                    continue
            eski = set(filter(None, (aktif.nedenler or "").split(",")))
            # Miktar değişmeden neden değiştiyse (sınıflandırma kuralı / minimum ayarı) yeni olay sayılmaz.
            yalniz_sinif = _d(aktif.fiziksel) == _d(h["fiziksel"])
            StokUyariService._degerleri_yaz(aktif, h, simdi)
            yeni_nedenler = set(h["nedenler"])
            if yeni_nedenler != eski and yalniz_sinif:
                aktif.row_version = int(aktif.row_version or 1) + 1
                StokUyariService._gecmis(session, aktif.id, "YENİDEN SINIFLANDIRILDI",
                                         f"{','.join(sorted(eski))} → {','.join(h['nedenler'])}")
            elif yeni_nedenler != eski:
                aktif.row_version = int(aktif.row_version or 1) + 1
                eklenen = yeni_nedenler - eski
                if eklenen:
                    aktif.goruldu = False
                    olaylar.append({"tur": "NEDEN", "stok_kodu": kart.stok_kodu, "stok_adi": kart.stok_adi,
                                    "depo": depo.ad, "nedenler": sorted(eklenen)})
                StokUyariService._gecmis(session, aktif.id, "NEDEN DEĞİŞTİ",
                                         f"{','.join(sorted(eski))} → {','.join(h['nedenler'])}")
        if olaylar:
            with _olay_kilidi:
                _son_olaylar.extend(o for o in olaylar if o["tur"] in ("YENI", "NEDEN")
                                    and o.get("nedenler") != [NEDEN_GIRIS_YOK])
        return olaylar

    @staticmethod
    def _ozet(h: dict) -> str:
        return (f"nedenler={','.join(h['nedenler'])}; fiziksel={miktar_metni(h['fiziksel'])}; "
                f"satılabilir={miktar_metni(h['satilabilir'])}; beklenen={miktar_metni(h['beklenen'])}; "
                f"hedef={miktar_metni(h['hedef'])}; öneri={miktar_metni(h['oneri_temel'])}")

    @staticmethod
    def _degerleri_yaz(kayit: StokIhtiyac, h: dict, simdi: datetime) -> None:
        if h["nedenler"]:
            kayit.nedenler = ",".join(h["nedenler"])
        kayit.fiziksel = h["fiziksel"]
        kayit.rezerve = h["rezerve"]
        kayit.satilabilir = h["satilabilir"]
        kayit.beklenen = h["beklenen"]
        kayit.minimum = h["minimum"]
        kayit.hedef = h["hedef"]
        kayit.oneri_temel = h["oneri_temel"]
        kayit.oneri_alim = h["oneri_alim"]
        kayit.alim_birimi = h["alim_birimi"]
        kayit.musteri_talebi = h["musteri_talebi"]
        kayit.diger_depo_stok = h["diger_depo_stok"]
        kayit.son_degerlendirme = simdi

    @staticmethod
    def bekleyenleri_isle(limit: int = 500) -> int:
        """Kuyruğa düşmüş çiftleri yeniden dener; başarılıları kuyruktan siler."""
        with get_session() as session:
            if not StokUyariService.tablolar_var(session):
                return 0
            kayitlar = session.scalars(select(StokUyariBekleyen).order_by(StokUyariBekleyen.id).limit(limit)).all()
            if not kayitlar:
                return 0
            session.info["_stok_uyari_calisiyor"] = True
            StokUyariService.yeniden_degerlendir(session, [(k.stok_id, k.depo_id) for k in kayitlar])
            for k in kayitlar:
                session.delete(k)
            return len(kayitlar)

    # ------------------------------------------------------------------ toplu tarama
    @staticmethod
    def tarama_ciftleri(session) -> list[tuple[int, int]]:
        """Aktif kartlar × hareket/lot görülen depolar; hiç hareketi olmayan kart → varsayılan depo."""
        aktif_idler = {i for (i,) in session.execute(select(StokKarti.id).where(
            StokKarti.aktif.is_(True), StokKarti.is_deleted.is_(False)))}
        ciftler = {(s, d) for s, d in session.execute(
            select(StokLotu.stok_id, StokLotu.depo_id).distinct()) if s in aktif_idler}
        ciftler |= {(s, d) for s, d in session.execute(
            select(StokHareketi.stok_id, StokHareketi.depo_id).distinct()) if s in aktif_idler}
        hareketli = {s for s, _d in ciftler}
        vid = StokUyariService._varsayilan_depo_id(session)
        if vid:
            ciftler |= {(s, vid) for s in aktif_idler - hareketli}
        ciftler |= {(s, d) for s, d in session.execute(
            select(StokUyariAyari.stok_id, StokUyariAyari.depo_id).where(StokUyariAyari.depo_id.is_not(None)))
            if s in aktif_idler}
        # Pasifleşmiş ürünlerin açık kayıtları da kapanabilsin
        ciftler |= {(s, d) for s, d in session.execute(
            select(StokIhtiyac.stok_id, StokIhtiyac.depo_id).where(StokIhtiyac.aktif.is_(True)))}
        return sorted(ciftler)

    @staticmethod
    def toplu_degerlendir(ilerleme: Callable[[int, int], None] | None = None,
                          iptal: Callable[[], bool] | None = None, parca: int = 300,
                          ilk_tarama: bool = False) -> dict[str, Any]:
        """İlk tarama / elle 'Yeniden değerlendir'. Stok, hareket ve siparişlere dokunmaz; tekrar çalıştırılabilir."""
        t0 = datetime.now()
        with get_session() as session:
            if not StokUyariService.tablolar_var(session):
                StokUyariService.schema_hazirla()
            ciftler = StokUyariService.tarama_ciftleri(session)
        toplam = len(ciftler)
        yeni = kapanan = 0
        for i in range(0, toplam, parca):
            if iptal and iptal():
                break
            with get_session() as session:
                session.info["_stok_uyari_calisiyor"] = True
                for o in StokUyariService.yeniden_degerlendir(session, ciftler[i:i + parca]):
                    if o["tur"] == "YENI":
                        yeni += 1
                    elif o["tur"] == "KAPANDI":
                        kapanan += 1
            if ilerleme:
                ilerleme(min(i + parca, toplam), toplam)
        with get_session() as session:
            StokUyariService._genel_yaz(session, "ilk_tarama", datetime.now().isoformat(timespec="seconds"))
            if not (iptal and iptal()):
                StokUyariService._genel_yaz(session, "siniflandirma_surumu", SINIFLANDIRMA_SURUMU)
            if ilk_tarama:
                # Mevcut durumun ilk dökümü "yeni uyarı" sayılmaz; sonraki değişiklikler yeni görünür.
                session.execute(update(StokIhtiyac).where(
                    StokIhtiyac.aktif.is_(True), StokIhtiyac.goruldu.is_(False), StokIhtiyac.ilk_olusma >= t0,
                ).values(goruldu=True))
        with _olay_kilidi:
            if ilk_tarama:
                _son_olaylar.clear()
        return {"cift": toplam, "yeni": yeni, "kapanan": kapanan,
                "sure_sn": round((datetime.now() - t0).total_seconds(), 2)}

    @staticmethod
    def ilk_tarama_gerekli() -> bool:
        with get_session() as session:
            if not StokUyariService.tablolar_var(session):
                return True
            genel = StokUyariService.genel_ayarlar(session)
            return not genel.get("ilk_tarama") or genel.get("siniflandirma_surumu") != SINIFLANDIRMA_SURUMU

    @staticmethod
    def aktif_sayisi() -> dict[str, int]:
        try:
            with get_session() as session:
                if not StokUyariService.tablolar_var(session):
                    return dict(_BOS_SAYI)
                bugun = date.today()
                gorunur = (StokIhtiyac.aktif.is_(True),
                           or_(StokIhtiyac.erteleme_bitis.is_(None), StokIhtiyac.erteleme_bitis < bugun))

                def say(*kosul) -> int:
                    return int(session.scalar(select(func.count(StokIhtiyac.id)).where(*gorunur, *kosul)) or 0)

                toplam = say()
                yalniz_giris_yok = say(StokIhtiyac.nedenler == NEDEN_GIRIS_YOK)
                return {
                    "toplam": toplam,
                    "tukenen": say(StokIhtiyac.nedenler.like(f"%{NEDEN_TUKENDI}%")),
                    "giris_yok": say(StokIhtiyac.nedenler.like(f"%{NEDEN_GIRIS_YOK}%")),
                    "kritik": say(StokIhtiyac.nedenler.like(f"%{NEDEN_KRITIK}%")),
                    "yeni": say(StokIhtiyac.goruldu.is_(False)),
                    # Menü rozeti: yalnız "stok girişi yok" olan (sipariş ihtiyacı tanımsız) kartlar sayılmaz.
                    "rozet": toplam - yalniz_giris_yok,
                }
        except Exception:
            logger.exception("Stok uyarı sayısı okunamadı")
            return dict(_BOS_SAYI)

    # ------------------------------------------------------------------ kullanıcı işlemleri
    @staticmethod
    def ertele(ihtiyac_id: int, bitis: date, neden: str) -> None:
        from database.access import yazma_zorunlu

        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Erteleme gerekçesi zorunludur.")
        if bitis <= date.today():
            raise ValueError("Erteleme bitiş tarihi bugünden sonra olmalıdır.")
        with get_session() as session:
            k = session.get(StokIhtiyac, ihtiyac_id)
            if k is None or not k.aktif:
                raise ValueError("Etkin ihtiyaç kaydı bulunamadı.")
            k.erteleme_bitis = bitis
            k.erteleme_nedeni = neden[:300]
            k.row_version = int(k.row_version or 1) + 1
            StokUyariService._gecmis(session, k.id, "ERTELENDİ", f"{bitis:%d.%m.%Y} — {neden}")

    @staticmethod
    def ertelemeyi_kaldir(ihtiyac_id: int) -> None:
        from database.access import yazma_zorunlu

        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        with get_session() as session:
            k = session.get(StokIhtiyac, ihtiyac_id)
            if k is None or k.erteleme_bitis is None:
                return
            k.erteleme_bitis = None
            k.erteleme_nedeni = None
            k.row_version = int(k.row_version or 1) + 1
            StokUyariService._gecmis(session, k.id, "ERTELEME KALDIRILDI")

    @staticmethod
    def takibi_kapat(stok_id: int) -> None:
        """'Bu ürünü takip etme' — ürün ayarı; stok/sipariş değişmez, etkin ihtiyaç kapanır."""
        mevcut = StokUyariService.ayar_getir(stok_id, None)["kayit"]
        veriler = {k: mevcut.get(k) for k in ("minimum", "hedef", "alim_birimi", "paket_kati", "tercih_tedarikci_id")}
        veriler["takip"] = False
        StokUyariService.ayar_kaydet(stok_id, None, veriler)

    @staticmethod
    def goruldu_isaretle(ihtiyac_idler: Iterable[int]) -> None:
        idler = [int(i) for i in ihtiyac_idler]
        if not idler:
            return
        with get_session() as session:
            session.execute(update(StokIhtiyac).where(StokIhtiyac.id.in_(idler)).values(goruldu=True))

    @staticmethod
    def gecmis(ihtiyac_id: int) -> list[dict]:
        with get_session() as session:
            k = session.get(StokIhtiyac, ihtiyac_id)
            if k is None:
                return []
            idler = [i for (i,) in session.execute(select(StokIhtiyac.id).where(
                StokIhtiyac.stok_id == k.stok_id, StokIhtiyac.depo_id == k.depo_id))]
            return [
                {"ihtiyac_id": g.ihtiyac_id, "tarih": g.tarih, "islem": g.islem, "detay": g.detay,
                 "kullanici": g.kullanici}
                for g in session.scalars(select(StokIhtiyacGecmisi).where(
                    StokIhtiyacGecmisi.ihtiyac_id.in_(idler)).order_by(StokIhtiyacGecmisi.id.desc())).all()
            ]

    # ------------------------------------------------------------------ sipariş bağlantıları
    @staticmethod
    def _bag_ozeti(session, ihtiyac_idler: list[int]) -> dict[int, dict]:
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        sonuc: dict[int, dict] = {}
        if not ihtiyac_idler:
            return sonuc
        for i in range(0, len(ihtiyac_idler), 500):
            parca = ihtiyac_idler[i:i + 500]
            for bag, ss, sip in session.execute(
                select(StokIhtiyacSiparisBagi, AlisSiparisiSatiri, AlisSiparisi)
                .join(AlisSiparisiSatiri, AlisSiparisiSatiri.id == StokIhtiyacSiparisBagi.siparis_satiri_id)
                .join(AlisSiparisi, AlisSiparisi.id == StokIhtiyacSiparisBagi.siparis_id)
                .where(StokIhtiyacSiparisBagi.ihtiyac_id.in_(parca))
            ).all():
                o = sonuc.setdefault(int(bag.ihtiyac_id), {"taslak": 0, "kesin": 0, "siparis": SIFIR,
                                                           "teslim": SIFIR, "siparisler": []})
                if sip.durum == "İPTAL":
                    continue
                oran = _d(bag.miktar_temel) / _d(ss.miktar) if _d(ss.miktar) else Decimal("1")
                teslim = min(_d(bag.miktar_temel), _d(ss.faturalanan_miktar) * oran)
                if sip.durum == "TASLAK":
                    o["taslak"] += 1
                else:
                    o["kesin"] += 1
                    o["siparis"] += _d(bag.miktar_temel)
                    o["teslim"] += teslim
                o["siparisler"].append({"siparis_id": sip.id, "siparis_no": sip.siparis_no, "durum": sip.durum,
                                        "miktar_temel": _d(bag.miktar_temel), "teslim_temel": teslim,
                                        "termin": sip.termin_tarihi})
        return sonuc

    @staticmethod
    def durum_metni(k: StokIhtiyac, bag: dict | None) -> str:
        if not k.aktif:
            return DURUM_KARSILANDI
        if k.erteleme_bitis and k.erteleme_bitis >= date.today():
            return DURUM_ERTELENDI
        if bag:
            if bag["kesin"]:
                if bag["teslim"] > 0 and bag["teslim"] < bag["siparis"]:
                    return DURUM_KISMEN
                if bag["teslim"] <= 0:
                    return DURUM_SIPARIS_VERILDI
            elif bag["taslak"]:
                return DURUM_TASLAK_VAR
        if _d(k.beklenen) > 0 and k.hedef is not None and _d(k.oneri_temel) <= 0:
            return DURUM_TESLIM_BEKLENIYOR
        if _d(k.beklenen) > 0 and k.hedef is None:
            return DURUM_TESLIM_BEKLENIYOR
        return DURUM_INCELENECEK

    # ------------------------------------------------------------------ alış / satış geçmişi
    @staticmethod
    def _net_fiyat(fiyat, *iskontolar) -> Decimal:
        net = _d(fiyat)
        for isk in iskontolar:
            net = net * (Decimal("1") - _d(isk) / Decimal("100"))
        return net.quantize(Decimal("0.0001"))

    @staticmethod
    def alis_gecmisi(session, kodlar: list[str], bas: date | None = None, bit: date | None = None,
                     tedarikci_id: int | None = None) -> dict[str, list[dict]]:
        """Kesinleşmiş (iptal dışı) alış fatura satırları; yeni → eski, eşit tarihte belge id azalan."""
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.cari import Cari

        sonuc: dict[str, list[dict]] = {}
        for i in range(0, len(kodlar), 500):
            q = (select(AlisFaturasiSatiri, AlisFaturasi, Cari.unvan)
                 .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                 .join(Cari, Cari.id == AlisFaturasi.cari_id)
                 .where(AlisFaturasiSatiri.urun_kodu.in_(kodlar[i:i + 500]), AlisFaturasi.durum != "İPTAL"))
            if bas:
                q = q.where(AlisFaturasi.fatura_tarihi >= bas)
            if bit:
                q = q.where(AlisFaturasi.fatura_tarihi <= bit)
            if tedarikci_id:
                q = q.where(AlisFaturasi.cari_id == tedarikci_id)
            q = q.order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc(), AlisFaturasiSatiri.id.desc())
            for s, f, unvan in session.execute(q).all():
                pb = (f.para_birimi or "TRY").upper()
                fiyat = _d(s.birim_fiyat_doviz) if pb != "TRY" and _d(s.birim_fiyat_doviz) > 0 else _d(s.birim_fiyat)
                sonuc.setdefault(s.urun_kodu, []).append({
                    "fatura_id": f.id, "belge_no": f.fatura_no, "tarih": f.fatura_tarihi, "cari_id": f.cari_id,
                    "cari": unvan, "miktar": _d(s.miktar), "birim": s.birim,
                    "birim_carpani": _dn(getattr(s, "birim_carpani", None)),
                    "net_fiyat": StokUyariService._net_fiyat(fiyat, s.iskonto_orani,
                                                             getattr(s, "iskonto_orani_2", 0),
                                                             getattr(s, "iskonto_orani_3", 0)),
                    "para_birimi": pb, "kur": _d(f.kur or 1), "kdv_orani": _d(s.kdv_orani),
                    "stok_maliyeti_temel": _d(s.fifo_birim_maliyeti),
                })
        return sonuc

    @staticmethod
    def satis_gecmisi(session, kodlar: list[str], bas: date | None = None,
                      bit: date | None = None) -> dict[str, list[dict]]:
        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri

        sonuc: dict[str, list[dict]] = {}
        for i in range(0, len(kodlar), 500):
            q = (select(SatisFaturasiSatiri, SatisFaturasi, Cari.unvan)
                 .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiSatiri.fatura_id)
                 .join(Cari, Cari.id == SatisFaturasi.cari_id)
                 .where(SatisFaturasiSatiri.urun_kodu.in_(kodlar[i:i + 500]),
                        SatisFaturasi.durum.notin_(("İPTAL", "TASLAK")),
                        SatisFaturasi.onaylandi.is_(True),
                        SatisFaturasi.is_deleted.is_(False)))
            if bas:
                q = q.where(SatisFaturasi.fatura_tarihi >= bas)
            if bit:
                q = q.where(SatisFaturasi.fatura_tarihi <= bit)
            q = q.order_by(SatisFaturasi.fatura_tarihi.desc(), SatisFaturasi.id.desc(), SatisFaturasiSatiri.id.desc())
            for s, f, unvan in session.execute(q).all():
                pb = (f.para_birimi or "TRY").upper()
                fiyat = _d(getattr(s, "birim_fiyat_doviz", 0)) if pb != "TRY" and _d(getattr(s, "birim_fiyat_doviz", 0)) > 0 \
                    else _d(s.birim_fiyat)
                sonuc.setdefault(s.urun_kodu, []).append({
                    "fatura_id": f.id, "belge_no": f.fatura_no, "tarih": f.fatura_tarihi, "cari": unvan,
                    "miktar": _d(s.miktar), "birim": s.birim, "birim_carpani": _dn(getattr(s, "birim_carpani", None)),
                    "net_fiyat": StokUyariService._net_fiyat(fiyat, s.iskonto_orani,
                                                             getattr(s, "iskonto_orani_2", 0),
                                                             getattr(s, "iskonto_orani_3", 0)),
                    "para_birimi": pb,
                })
        return sonuc

    @staticmethod
    def tedarikci_karsilastirma(stok_id: int, alim_birimi: str | None = None) -> dict[str, Any]:
        """Ürünün tüm kesinleşmiş alışları + tedarikçi bazlı son net fiyat (alım birimine çevrilmiş).
        Döviz faturaları kendi para biriminde kalır; teklif değil, geçmiş alış bilgisidir."""
        with get_session() as session:
            kart = session.get(StokKarti, int(stok_id))
            if kart is None:
                return {"satirlar": [], "tedarikciler": []}
            _ = list(kart.birimler)
            birim = alim_birimi or kart.varsayilan_alis_birim or kart.birim
            satirlar = StokUyariService.alis_gecmisi(session, [kart.stok_kodu]).get(kart.stok_kodu, [])
            ozet: dict[int, dict] = {}
            for a in satirlar:
                o = ozet.get(a["cari_id"])
                if o is None:
                    fiyat = StokUyariService._tahmini_fiyat(kart, satirlar, a["cari_id"], birim)
                    o = ozet[a["cari_id"]] = {
                        "cari_id": a["cari_id"], "cari": a["cari"], "son_tarih": a["tarih"],
                        "son_belge": a["belge_no"], "son_fiyat": fiyat["fiyat"] if fiyat else None,
                        "para_birimi": a["para_birimi"], "birim": birim, "alis_sayisi": 0,
                        "toplam_temel": SIFIR,
                    }
                o["alis_sayisi"] += 1
                o["toplam_temel"] += StokUyariService._temel(kart, a["miktar"], a["birim"], a["birim_carpani"])
            return {"satirlar": satirlar, "tedarikciler": list(ozet.values()), "birim": birim,
                    "temel_birim": kart.birim or "Adet"}

    @staticmethod
    def _iade_toplamlari(session, kodlar: list[str], bas: date, bit: date,
                         kartlar: dict[str, Any]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
        from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri

        def _topla(baslik, satir, fk) -> dict[str, Decimal]:
            t: dict[str, Decimal] = {}
            for i in range(0, len(kodlar), 500):
                for s in session.scalars(
                    select(satir).join(baslik, baslik.id == getattr(satir, fk))
                    .where(satir.urun_kodu.in_(kodlar[i:i + 500]), baslik.durum.not_in(("İPTAL", "TASLAK")),
                           baslik.iade_tarihi >= bas, baslik.iade_tarihi <= bit)
                ).all():
                    t[s.urun_kodu] = t.get(s.urun_kodu, SIFIR) + StokUyariService._temel(
                        kartlar.get(s.urun_kodu), s.miktar, s.birim, getattr(s, "birim_carpani", None))
            return t

        return (_topla(AlisIadeFaturasi, AlisIadeFaturasiSatiri, "iade_id"),
                _topla(SatisIadeFaturasi, SatisIadeFaturasiSatiri, "iade_id"))

    @staticmethod
    def _temel(kart, miktar, birim, kayitli_carpan=None) -> Decimal:
        c = _dn(kayitli_carpan)
        if c is None or c <= 0:
            c = StokUyariService._carpan(kart, birim) if kart is not None else None
        return _d(miktar) * (c if c else Decimal("1"))

    # ------------------------------------------------------------------ liste
    @staticmethod
    def listele(filtre: dict[str, Any] | None = None) -> dict[str, Any]:
        """İhtiyaç listesi. filtre: depo_id, arama, marka, grup, tedarikci, neden, durum,
        ertelenenler (bool), kapananlar (bool), donem_gun (30/60/90) veya bas/bit."""
        from database.access import maliyet_izinli
        from database.models.cari import Cari

        filtre = filtre or {}
        bit = filtre.get("bit") or date.today()
        bas = filtre.get("bas") or (bit - timedelta(days=int(filtre.get("donem_gun") or 30) - 1))
        maliyet_goster = True
        try:
            maliyet_goster = maliyet_izinli()
        except Exception:
            pass
        with get_session() as session:
            if not StokUyariService.tablolar_var(session):
                return {"satirlar": [], "bas": bas, "bit": bit, "toplam_bedel": {}, "not": REZERVASYON_DESTEK_NOTU}
            q = select(StokIhtiyac, StokKarti, Depo).join(StokKarti, StokKarti.id == StokIhtiyac.stok_id) \
                .join(Depo, Depo.id == StokIhtiyac.depo_id)
            if not filtre.get("kapananlar"):
                q = q.where(StokIhtiyac.aktif.is_(True))
            if filtre.get("depo_id"):
                q = q.where(StokIhtiyac.depo_id == int(filtre["depo_id"]))
            if filtre.get("marka"):
                q = q.where(StokKarti.marka == filtre["marka"])
            if filtre.get("grup"):
                q = q.where(StokKarti.rapor_grubu.like(f"%{filtre['grup']}%"))
            neden = filtre.get("neden")
            if neden in NEDEN_ETIKET:
                q = q.where(StokIhtiyac.nedenler.like(f"%{neden}%"))
            arama = _tr_kucuk(filtre.get("arama"))
            kayitlar = session.execute(q).all()
            if arama:
                barkodlu = {sid for (sid,) in session.execute(
                    select(StokBarkod.stok_id).where(func.lower(StokBarkod.barkod).like(f"%{arama}%")))}
                kayitlar = [r for r in kayitlar if arama in _tr_kucuk(r[1].stok_kodu) or arama in _tr_kucuk(r[1].stok_adi)
                            or arama in _tr_kucuk(r[1].barkod) or r[1].id in barkodlu]
            kodlar = sorted({r[1].stok_kodu for r in kayitlar})
            kartlar = {r[1].stok_kodu: r[1] for r in kayitlar}
            for kart in kartlar.values():
                _ = list(kart.birimler)
            ayarlar_tum: dict[int, dict] = {}
            for i in range(0, len(kartlar), 500):
                idler = [k.id for k in list(kartlar.values())[i:i + 500]]
                for a in session.scalars(select(StokUyariAyari).where(StokUyariAyari.stok_id.in_(idler))).all():
                    ayarlar_tum.setdefault(a.stok_id, {})[a.depo_id] = a
            genel = StokUyariService.genel_ayarlar(session)
            alislar = StokUyariService.alis_gecmisi(session, kodlar)
            satislar = StokUyariService.satis_gecmisi(session, kodlar)
            donem_alis = StokUyariService.alis_gecmisi(session, kodlar, bas, bit)
            donem_satis = StokUyariService.satis_gecmisi(session, kodlar, bas, bit)
            alis_iade, satis_iade = StokUyariService._iade_toplamlari(session, kodlar, bas, bit, kartlar)
            baglar = StokUyariService._bag_ozeti(session, [r[0].id for r in kayitlar])
            cariler = {c.id: c.unvan for c in session.scalars(select(Cari)).all()} if kayitlar else {}
            satirlar = []
            toplam_bedel: dict[str, Decimal] = {}
            bugun = date.today()
            for k, kart, depo in kayitlar:
                ertelendi = bool(k.erteleme_bitis and k.erteleme_bitis >= bugun)
                if ertelendi and not filtre.get("ertelenenler") and _d(k.musteri_talebi) <= 0:
                    continue
                bag = baglar.get(k.id)
                durum = StokUyariService.durum_metni(k, bag)
                if filtre.get("durum") and filtre["durum"] != durum:
                    continue
                ayar = StokUyariService.etkin_ayar(session, kart, depo.id, genel, ayarlar_tum.get(kart.id, {}))
                son_alis = (alislar.get(kart.stok_kodu) or [None])[0]
                son_satis = (satislar.get(kart.stok_kodu) or [None])[0]
                tercih = ayar.get("tercih_tedarikci_id")
                if tercih:
                    ted_id, ted_kaynak = int(tercih), "Tercih edilen"
                elif son_alis:
                    ted_id, ted_kaynak = son_alis["cari_id"], "Son alış"
                else:
                    ted_id, ted_kaynak = None, "Tedarikçi seçilecek"
                ted_adi = cariler.get(ted_id, "") if ted_id else "Tedarikçi seçilecek"
                if filtre.get("tedarikci") and _tr_kucuk(filtre["tedarikci"]) not in _tr_kucuk(ted_adi):
                    continue
                fiyat = StokUyariService._tahmini_fiyat(kart, alislar.get(kart.stok_kodu) or [], ted_id,
                                                         k.alim_birimi or kart.birim)
                bedel = None
                if fiyat and k.oneri_alim is not None and _d(k.oneri_alim) > 0:
                    bedel = (fiyat["fiyat"] * _d(k.oneri_alim)).quantize(Decimal("0.01"))
                    toplam_bedel[fiyat["para_birimi"]] = toplam_bedel.get(fiyat["para_birimi"], SIFIR) + bedel
                d_alis = sum((StokUyariService._temel(kart, a["miktar"], a["birim"], a["birim_carpani"])
                              for a in donem_alis.get(kart.stok_kodu, [])), SIFIR)
                d_satis = sum((StokUyariService._temel(kart, a["miktar"], a["birim"], a["birim_carpani"])
                               for a in donem_satis.get(kart.stok_kodu, [])), SIFIR)
                nedenler = [n for n in (k.nedenler or "").split(",") if n]
                if NEDEN_TUKENDI in nedenler and _d(k.musteri_talebi) > 0:
                    oncelik, oncelik_neden = 1, "Tükendi + bekleyen müşteri siparişi"
                elif NEDEN_TUKENDI in nedenler or NEDEN_SATILABILIR_YOK in nedenler:
                    oncelik, oncelik_neden = 2, "Tükendi"
                elif NEDEN_KRITIK in nedenler:
                    oncelik, oncelik_neden = 3, "Kritik seviye"
                elif NEDEN_GIRIS_YOK in nedenler:
                    oncelik, oncelik_neden = 5, "Stok girişi yok"
                else:
                    oncelik, oncelik_neden = 4, ""
                d_son_alis = (donem_alis.get(kart.stok_kodu) or [None])[0]
                d_son_satis = (donem_satis.get(kart.stok_kodu) or [None])[0]
                satirlar.append({
                    "id": k.id, "stok_id": kart.id, "depo_id": depo.id, "row_version": k.row_version,
                    "stok_kodu": kart.stok_kodu, "stok_adi": kart.stok_adi, "marka": kart.marka or "",
                    "grup": kart.rapor_grubu or "", "depo": depo.ad, "temel_birim": kart.birim or "Adet",
                    "fiziksel": _d(k.fiziksel), "rezerve": _d(k.rezerve), "satilabilir": _d(k.satilabilir),
                    "beklenen": _d(k.beklenen), "minimum": k.minimum, "hedef": k.hedef,
                    "nedenler": nedenler, "neden_metni": ", ".join(NEDEN_ETIKET.get(n, n) for n in nedenler),
                    "oneri_alim": k.oneri_alim, "oneri_temel": k.oneri_temel, "alim_birimi": k.alim_birimi,
                    "oneri_metni": ("Kullanıcı belirleyecek" if k.hedef is None
                                    else f"{miktar_metni(k.oneri_alim)} {k.alim_birimi or kart.birim}"),
                    "takip": "Ertelendi" if ertelendi else ("Açık" if k.aktif else "Kapandı"),
                    "durum": durum, "bag": bag, "aktif": bool(k.aktif),
                    "tedarikci_id": ted_id, "tedarikci": ted_adi, "tedarikci_kaynak": ted_kaynak,
                    "son_tedarikci": son_alis["cari"] if son_alis else "",
                    "son_alis": son_alis, "son_satis": son_satis,
                    "donem_son_alis": d_son_alis, "donem_son_satis": d_son_satis,
                    "donem_alis": d_alis, "donem_alis_iade": alis_iade.get(kart.stok_kodu, SIFIR),
                    "donem_satis": d_satis, "donem_satis_iade": satis_iade.get(kart.stok_kodu, SIFIR),
                    "donem_net_alis": d_alis - alis_iade.get(kart.stok_kodu, SIFIR),
                    "donem_net_satis": d_satis - satis_iade.get(kart.stok_kodu, SIFIR),
                    "tahmini_fiyat": fiyat if maliyet_goster else None,
                    "tahmini_bedel": bedel if maliyet_goster else None,
                    "musteri_talebi": _d(k.musteri_talebi), "diger_depo_stok": _d(k.diger_depo_stok),
                    "ilk_olusma": k.ilk_olusma, "son_degerlendirme": k.son_degerlendirme,
                    "erteleme_bitis": k.erteleme_bitis, "erteleme_nedeni": k.erteleme_nedeni,
                    "goruldu": bool(k.goruldu), "olay_no": k.olay_no, "kapanma_tarihi": k.kapanma_tarihi,
                    "oncelik": oncelik, "oncelik_neden": oncelik_neden, "ayar_kaynak": ayar["kaynak"],
                })
            satirlar.sort(key=lambda s: (not s["aktif"], s["oncelik"], -float(s["musteri_talebi"]),
                                         s["stok_kodu"], s["depo"]))
            return {"satirlar": satirlar, "bas": bas, "bit": bit,
                    "toplam_bedel": toplam_bedel if maliyet_goster else {},
                    "maliyet_goster": maliyet_goster, "not": REZERVASYON_DESTEK_NOTU}

    @staticmethod
    def _tahmini_fiyat(kart, alislar: list[dict], tedarikci_id: int | None, alim_birimi: str) -> dict | None:
        """Seçilen tedarikçinin son alış net fiyatı, alım birimine çevrilmiş (teklif değildir)."""
        aday = next((a for a in alislar if tedarikci_id and a["cari_id"] == tedarikci_id), None)
        if aday is None:
            return None
        c_belge = aday["birim_carpani"] or StokUyariService._carpan(kart, aday["birim"])
        c_alim = StokUyariService._carpan(kart, alim_birimi)
        if not c_belge or not c_alim:
            return None
        fiyat = (aday["net_fiyat"] / c_belge * c_alim).quantize(Decimal("0.0001"))
        return {"fiyat": fiyat, "para_birimi": aday["para_birimi"], "kur": aday["kur"], "tarih": aday["tarih"],
                "belge_no": aday["belge_no"], "birim": alim_birimi}

    # ------------------------------------------------------------------ sipariş hazırlama
    @staticmethod
    def siparis_hazirla(secimler: list[dict[str, Any]], termin: date | None = None) -> list[dict]:
        """Seçili ihtiyaçlardan TASLAK alış siparişleri oluşturur (mevcut sipariş tablosu ve numaralandırması).

        secim: ihtiyac_id, row_version, tedarikci_id, miktar (alım birimi), birim, fiyat (TL, KDV hariç),
               iskonto, kdv, teslim_depo. Aynı tedarikçi + teslim deposu tek belgede toplanır.
        Taslak beklenen alıma girmez; ihtiyaç açık kalır. Satır sürümü değişmişse (başka kullanıcı) işlem durur.
        """
        from database.access import yazma_zorunlu
        from database.alis_siparisi_service import DURUM_TASLAK, AlisSiparisiService
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        yazma_zorunlu("alis_siparis_duzenleme", "alis_duzenleme", "yeni_kayit")
        if not secimler:
            raise ValueError("Sipariş için ihtiyaç satırı seçin.")
        termin = termin or (date.today() + timedelta(days=7))
        gruplar: dict[tuple[int, str], list[dict]] = {}
        for s in secimler:
            if not s.get("tedarikci_id"):
                raise ValueError("Her satır için tedarikçi seçin (Tedarikçi seçilecek).")
            m = Decimal(str(s.get("miktar") or 0).replace(",", "."))
            if m <= 0:
                raise ValueError("Sipariş miktarı sıfırdan büyük olmalı.")
            gruplar.setdefault((int(s["tedarikci_id"]), (s.get("teslim_depo") or "").strip()), []).append(s)
        olusan: list[dict] = []
        with get_session() as session:
            session.info["_stok_uyari_calisiyor"] = True
            for s in secimler:
                n = session.execute(
                    update(StokIhtiyac)
                    .where(StokIhtiyac.id == int(s["ihtiyac_id"]), StokIhtiyac.aktif.is_(True),
                           StokIhtiyac.row_version == int(s["row_version"]))
                    .values(row_version=StokIhtiyac.row_version + 1)
                ).rowcount
                if n != 1:
                    raise ValueError("İhtiyaç kaydı başka bir işlemle değişti veya kapandı. "
                                     "Listeyi yenileyip tekrar deneyin (mükerrer sipariş önlendi).")
                taslak_var = session.scalar(
                    select(func.count(StokIhtiyacSiparisBagi.id))
                    .join(AlisSiparisi, AlisSiparisi.id == StokIhtiyacSiparisBagi.siparis_id)
                    .where(StokIhtiyacSiparisBagi.ihtiyac_id == int(s["ihtiyac_id"]),
                           AlisSiparisi.durum == DURUM_TASLAK))
                if taslak_var and not s.get("ek_siparis"):
                    raise ValueError("Bu ihtiyaç için zaten taslak sipariş var; önce onu kesinleştirin veya silin.")
            for (ted_id, teslim_depo), liste in gruplar.items():
                siparis = AlisSiparisi(siparis_no=AlisSiparisiService.siparis_no(), siparis_tarihi=date.today(),
                                       termin_tarihi=termin, cari_id=ted_id, durum=DURUM_TASLAK, row_version=1,
                                       teslim_depo=teslim_depo or None,
                                       aciklama="Stok uyarıları ve sipariş ihtiyacı ekranından hazırlandı (taslak).")
                from database.sube_service import SubeService

                siparis.sube_id = SubeService.transaction_subesi(session, None)
                session.add(siparis)
                session.flush()
                for s in liste:
                    k = session.get(StokIhtiyac, int(s["ihtiyac_id"]))
                    kart = session.get(StokKarti, k.stok_id)
                    depo = session.get(Depo, k.depo_id)
                    if teslim_depo and teslim_depo != depo.ad:
                        raise ValueError(f"{kart.stok_kodu}: teslim deposu ihtiyacın deposuyla aynı olmalı ({depo.ad}).")
                    if not teslim_depo:
                        siparis.teslim_depo = depo.ad
                    birim = s.get("birim") or k.alim_birimi or kart.birim
                    from database.stok_service import StokService

                    carpan = StokService.birim_carpani_kesin(kart, birim)
                    miktar = Decimal(str(s["miktar"]).replace(",", "."))
                    satir = AlisSiparisiSatiri(
                        siparis_id=siparis.id, urun_kodu=kart.stok_kodu, urun_adi=kart.stok_adi,
                        aciklama=s.get("aciklama"), miktar=miktar, birim=birim,
                        birim_alis_fiyati=Decimal(str(s.get("fiyat") or 0).replace(",", ".")),
                        iskonto_orani=Decimal(str(s.get("iskonto") or 0).replace(",", ".")),
                        kdv_orani=Decimal(str(s.get("kdv") if s.get("kdv") is not None else kart.kdv_orani or 20)),
                        irsaliyelenen_miktar=SIFIR, faturalanan_miktar=SIFIR,
                    )
                    session.add(satir)
                    session.flush()
                    session.add(StokIhtiyacSiparisBagi(ihtiyac_id=k.id, siparis_id=siparis.id,
                                                       siparis_satiri_id=satir.id, miktar_temel=miktar * carpan,
                                                       olusturan=_kullanici()))
                    StokUyariService._gecmis(session, k.id, "SİPARİŞ TASLAĞI",
                                             f"{siparis.siparis_no}: {miktar_metni(miktar)} {birim}")
                olusan.append({"siparis_id": siparis.id, "siparis_no": siparis.siparis_no, "tedarikci_id": ted_id,
                               "satir": len(liste)})
            session.flush()
            ciftler = [(session.get(StokIhtiyac, int(s["ihtiyac_id"])).stok_id,
                        session.get(StokIhtiyac, int(s["ihtiyac_id"])).depo_id) for s in secimler]
            StokUyariService.yeniden_degerlendir(session, ciftler)
        return olusan

    @staticmethod
    def guncel_kontrol(ihtiyac_idler: list[int]) -> list[dict]:
        """Sipariş öncesi: güncel stok/beklenen yeniden hesaplanır, kayıt güncellenir, satırlar döner."""
        with get_session() as session:
            ciftler = [(k.stok_id, k.depo_id) for k in session.scalars(
                select(StokIhtiyac).where(StokIhtiyac.id.in_([int(i) for i in ihtiyac_idler]))).all()]
            session.info["_stok_uyari_calisiyor"] = True
            StokUyariService.yeniden_degerlendir(session, ciftler)
        return [s for s in StokUyariService.listele({"kapananlar": True, "ertelenenler": True})["satirlar"]
                if s["id"] in set(int(i) for i in ihtiyac_idler)]


# ---------------------------------------------------------------------- otomatik tetikleme
def _kuyruk(session) -> dict:
    return session.info.setdefault("_stok_uyari", {"ciftler": set(), "kodlar": set(), "siparisler": set(),
                                                   "stoklar": set()})


@event.listens_for(Session, "after_flush")
def _flush_sonrasi(session, _ctx) -> None:
    if session.info.get("_stok_uyari_calisiyor"):
        return
    try:
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
        from database.models.satis_siparisi import SatisSiparisiSatiri

        k = None
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if isinstance(obj, (StokHareketi, StokLotu)):
                k = k or _kuyruk(session)
                if obj.stok_id is not None and obj.depo_id is not None:
                    k["ciftler"].add((int(obj.stok_id), int(obj.depo_id)))
            elif isinstance(obj, (AlisSiparisiSatiri, SatisSiparisiSatiri)):
                k = k or _kuyruk(session)
                if obj.urun_kodu:
                    k["kodlar"].add(obj.urun_kodu)
            elif isinstance(obj, AlisSiparisi):
                k = k or _kuyruk(session)
                if obj.id is not None:
                    k["siparisler"].add(int(obj.id))
            elif isinstance(obj, StokKarti):
                durum = inspect(obj)
                if obj in session.new or obj in session.deleted or any(
                        durum.attrs[a].history.has_changes() for a in _KART_ALANLARI):
                    k = k or _kuyruk(session)
                    if obj.id is not None:
                        k["stoklar"].add(int(obj.id))
            elif isinstance(obj, (StokUyariAyari, StokBirim)):
                k = k or _kuyruk(session)
                if obj.stok_id is not None:
                    k["stoklar"].add(int(obj.stok_id))
    except Exception:
        logger.exception("Stok uyarı kuyruğu toplanamadı")


@event.listens_for(Session, "before_commit")
def _commit_oncesi(session) -> None:
    if session.info.get("_stok_uyari_calisiyor"):
        return
    # Commit'in kendi flush'ı bu olaydan sonra çalışır; bekleyen değişiklikler kuyruğa önce alınsın.
    # İş verisinin flush hatası burada yutulmaz; commit'i durdurmalıdır.
    if session.new or session.dirty or session.deleted:
        session.flush()
    k = session.info.pop("_stok_uyari", None)
    if not k or not any(k.values()) or not StokUyariService.tablolar_var(session):
        return
    session.info["_stok_uyari_calisiyor"] = True
    ciftler = set(k["ciftler"])
    try:
        from database.models.alis_siparisi import AlisSiparisiSatiri

        kodlar = set(k["kodlar"])
        if k["siparisler"]:
            kodlar |= {kod for (kod,) in session.execute(select(AlisSiparisiSatiri.urun_kodu).where(
                AlisSiparisiSatiri.siparis_id.in_(sorted(k["siparisler"])))).all()}
        stoklar = set(k["stoklar"])
        if kodlar:
            stoklar |= {i for (i,) in session.execute(select(StokKarti.id).where(
                StokKarti.stok_kodu.in_(sorted(kodlar)))).all()}
        for sid in stoklar:
            ciftler |= set(StokUyariService._urun_ciftleri(session, sid))
        if len(ciftler) > SATIR_ICI_SINIR:
            for stok_id, depo_id in sorted(ciftler):
                session.add(StokUyariBekleyen(stok_id=stok_id, depo_id=depo_id, hata="toplu işlem — sırada"))
            session.flush()
            return
        with session.begin_nested():
            StokUyariService.yeniden_degerlendir(session, ciftler)
    except Exception as hata:
        logger.exception("Stok uyarısı değerlendirilemedi; yeniden deneme kuyruğuna alındı")
        try:
            for stok_id, depo_id in ciftler:
                session.add(StokUyariBekleyen(stok_id=stok_id, depo_id=depo_id, hata=str(hata)[:500]))
            session.flush()
        except Exception:
            logger.exception("Stok uyarı kuyruğu yazılamadı")
    finally:
        session.info.pop("_stok_uyari_calisiyor", None)
        session.info.pop("_stok_uyari", None)


@event.listens_for(Session, "after_rollback")
def _geri_alindi(session) -> None:
    session.info.pop("_stok_uyari", None)
