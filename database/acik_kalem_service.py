"""Açık borç / alacak kalemleri ve kapatma (tahsis) altyapısı — tek merkez.

Açık kalem deposu ``cari_satis_hareketleri`` (SatisHareketi):
  * kalan_acik_tutar > 0  → belge yönünde açık kalem (satış/alış faturası, devir, borç dekontu…)
  * kalan_acik_tutar < 0 ve satis_tutari = 0 → avans / açık kredi (fazla tahsilat veya ödeme)

Her kapatma ``cari_kapatmalar`` tablosuna yazılır (kaynak evrak, hedef kalem, tutar, tarih,
kullanıcı, işlem kimliği). Geri alma kayıtları silmez; ``iptal`` işaretler.

Varsayılan dağıtım FIFO: işlem tarihi → evrak no → değişmeyen kayıt kimliği.
Para birimleri ayrı çalışır (döviz sabit kalem yalnız kendi para biriminden kapanır).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm.attributes import set_committed_value

from database.models.cari import CariKapatma, SatisHareketi

KURUS = Decimal("0.01")
TOLERANS = Decimal("0.005")

# Kaynak evrak (tahsilat/ödeme/virman) önekleri: bunlar hedef açık kalem sayılmaz.
_KAYNAK_ONEKLERI = ("ODM-", "VRM-", "KKC-", "THS-")
# Geçişte eşleştirilemeyen net farkın açıklamalı devir kalemi (satis_tutari=0 → bakiyeyi değiştirmez).
GECIS_DEVIR_ONEKI = "DVF-"


def _d(deger) -> Decimal:
    if deger is None:
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return Decimal("0")


def _kurus(deger) -> Decimal:
    return _d(deger).quantize(KURUS, rounding=ROUND_HALF_UP)


def para_anahtari(hareket) -> str:
    """Kalemin kapanabileceği para birimi: döviz sabitte kendi dövizi, aksi halde TRY."""
    pb = (getattr(hareket, "para_birimi", None) or "TRY").upper()
    esas = (getattr(hareket, "borc_esasi", None) or "TL_SABIT").upper()
    return pb if esas == "DOVIZ_SABIT" and pb != "TRY" else "TRY"


def tedarikci_mi(cari_turu: str | None) -> bool:
    """Cari türü tedarikçi / satıcı yönünde mi?"""
    t = (cari_turu or "").strip().casefold()
    return t.startswith("tedarik") or t in {"satıcı", "satici"}


def kalem_sinifi(hareket) -> str:
    """Açık kalem sınıfı: BORC (belge açığı), AVANS (fazla tahsil/ödeme), DIGER."""
    kalan = _d(getattr(hareket, "kalan_acik_tutar", None))
    tutar = _d(getattr(hareket, "satis_tutari", None))
    if tutar < 0 and kalan < 0:
        return "BORC"  # tedarikçi açık alış (|kalan|)
    if kalan > 0:
        bn = getattr(hareket, "belge_no", None) or ""
        if bn.startswith(_KAYNAK_ONEKLERI) and tutar <= 0:
            return "DIGER"
        return "BORC"
    if tutar == 0 and kalan < 0:
        return "AVANS"
    return "DIGER"


def odeme_durumu(toplam, kapanan) -> str:
    """Evrak durumundan bağımsız ödeme durumu metni."""
    toplam = _kurus(toplam)
    kapanan = _kurus(kapanan)
    if toplam <= 0:
        return ""
    if kapanan <= 0:
        return "Ödenmedi"
    if kapanan + TOLERANS >= toplam:
        return ODEME_KAPANDI
    return ODEME_KISMEN


ODEME_ODENMEDI = "Ödenmedi"
ODEME_KISMEN = "Kısmen Ödendi"
ODEME_KAPANDI = "Kapandı"
ODEME_DURUMLARI = (ODEME_ODENMEDI, ODEME_KISMEN, ODEME_KAPANDI)


DAGITIM_FIFO = "Otomatik FIFO"
DAGITIM_SECILI = "Seçilen Belgeler"
KALEM_ACIK = "Açık"
KALEM_KISMEN = "Kısmen Kapalı"
KALEM_KAPALI = "Kapalı"


def _onizleme_sirasi(k: dict) -> tuple:
    return (k.get("tarih") or date.min, k.get("evrak_no") or "", int(k.get("hareket_id") or 0))


def dagitim_onizleme(kalemler: list[dict], tutar, secili: Iterable[int] = (), *,
                     artani_fifo: bool = False, sabit: dict | None = None) -> dict:
    """Tahsilatın açık kalemlere dağıtım önerisi (kayıt yapmaz).

    Seçim yoksa tüm kalemlere belge tarihine göre FIFO; seçim varsa yalnız seçilenlere aynı FIFO
    sırasıyla (tıklama sırası önemsiz). Her satırda kapanacak = min(açık, kalan dağıtılabilir).
    Seçili kalemlerden artan tutar, ``artani_fifo`` açıkça istenmedikçe avans olarak kalır.
    ``sabit`` {hareket_id: tutar}: kayıtlı belgenin dağıtımı aynen kullanılır (seçili kalemler için).
    """
    tutar = _kurus(tutar) if _kurus(tutar) > 0 else Decimal("0.00")
    secili_set = {int(i) for i in secili}
    sirali = sorted(kalemler, key=_onizleme_sirasi)
    mod = DAGITIM_SECILI if secili_set else DAGITIM_FIFO
    kalan = tutar
    paylar: dict[int, Decimal] = {}

    def _dagit(adaylar):
        nonlocal kalan
        for k in adaylar:
            if kalan <= 0:
                break
            acik = _kurus(k.get("kalan"))
            pay = min(acik, kalan)
            if pay > 0:
                hid = int(k["hareket_id"])
                paylar[hid] = paylar.get(hid, Decimal("0")) + pay
                kalan -= pay

    if secili_set and sabit:
        for k in sirali:
            hid = int(k["hareket_id"])
            if hid not in secili_set or kalan <= 0:
                continue
            pay = min(_kurus(k.get("kalan")), _kurus(sabit.get(hid, 0)), kalan)
            if pay > 0:
                paylar[hid] = pay
                kalan -= pay
        if artani_fifo:
            _dagit([k for k in sirali if int(k["hareket_id"]) not in secili_set])
    elif secili_set:
        _dagit([k for k in sirali if int(k["hareket_id"]) in secili_set])
        if artani_fifo:
            _dagit([k for k in sirali if int(k["hareket_id"]) not in secili_set])
    else:
        _dagit(sirali)
    satirlar = {}
    for k in sirali:
        hid = int(k["hareket_id"])
        acik = _kurus(k.get("kalan"))
        pay = _kurus(paylar.get(hid, 0))
        sonra = acik - pay
        if pay > 0:
            durum = KALEM_KAPALI if sonra <= TOLERANS else KALEM_KISMEN
        else:
            durum = KALEM_KISMEN if _kurus(k.get("kapanan")) > 0 else KALEM_ACIK
        satirlar[hid] = {"kapanacak": pay, "sonra": sonra, "durum": durum}
    secilen_toplam = _kurus(sum((_kurus(k.get("kalan")) for k in sirali
                                 if int(k["hareket_id"]) in secili_set), Decimal("0")))
    dagitilan = _kurus(sum(paylar.values(), Decimal("0")))
    return {
        "mod": mod,
        "tutar": tutar,
        "secilen_toplam": secilen_toplam,
        "dagitilan": dagitilan,
        "artan": _kurus(tutar - dagitilan),
        "satirlar": satirlar,
        "dagitim": [(int(k["hareket_id"]), satirlar[int(k["hareket_id"])]["kapanacak"]) for k in sirali
                    if satirlar[int(k["hareket_id"])]["kapanacak"] > 0],
    }


def _kullanici() -> tuple[int | None, str | None]:
    try:
        from database.session_manager import oturum

        return oturum.user_id, (oturum.kullanici_adi or oturum.ad_soyad)
    except Exception:
        return None, None


class AcikKalemDegisti(ValueError):
    """Seçilen kalemin açık tutarı başka bir işlemle değişti."""


@dataclass
class KapatmaSonucu:
    kapanan: Decimal
    kalan: Decimal
    islem_kimligi: str
    kayitlar: list[CariKapatma]


class AcikKalemService:
    _hazir_motor = None

    # --- Şema ---
    @classmethod
    def schema_hazirla(cls, motor=None) -> None:
        """cari_kapatmalar tablosu yoksa ekler (yalnız CREATE TABLE; veriye dokunmaz)."""
        import database.database as veritabani

        motor = motor or veritabani.engine
        if motor is None or motor is cls._hazir_motor:
            return
        CariKapatma.__table__.create(bind=motor, checkfirst=True)
        cls._hazir_motor = motor

    @staticmethod
    def _tablo_var(session) -> bool:
        from sqlalchemy import inspect as sa_inspect

        motor = session.get_bind()
        if motor is not None and motor is AcikKalemService._hazir_motor:
            return True
        var = sa_inspect(session.connection()).has_table(CariKapatma.__tablename__)
        if var:
            AcikKalemService._hazir_motor = motor
        return var

    # --- Sorgular ---
    @staticmethod
    def fifo_sirasi(hareket) -> tuple:
        return (hareket.satis_tarihi or date.min, hareket.belge_no or "", int(hareket.id or 0))

    @staticmethod
    def acik_kalemler(
        session,
        cari_id: int,
        *,
        yon: str = "BORC",
        para_birimi: str | None = "TRY",
        haric_ids: Iterable[int] = (),
    ) -> list[SatisHareketi]:
        """yon BORC: kapanmamış belge kalemleri; AVANS: açık kredi (kalan<0, tutar=0).

        Tedarikçi alış (satis_tutari<0, kalan<0) BORÇ kuyruğuna alınır — ödeme/iade |kalan| azaltır.
        """
        from sqlalchemy import and_, or_

        if yon == "BORC":
            kosul = or_(
                SatisHareketi.kalan_acik_tutar > 0,
                and_(SatisHareketi.satis_tutari < 0, SatisHareketi.kalan_acik_tutar < 0),
            )
        else:
            # Avans: fazla tahsil/ödeme (tutar 0, kalan negatif)
            kosul = and_(SatisHareketi.satis_tutari == 0, SatisHareketi.kalan_acik_tutar < 0)
        haric = {int(i) for i in haric_ids}
        kalemler = [
            h
            for h in session.scalars(
                select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id), kosul)
            ).all()
            if int(h.id) not in haric
            and (para_birimi is None or para_anahtari(h) == para_birimi.upper())
            and abs(_d(h.kalan_acik_tutar)) > TOLERANS
        ]
        if yon == "BORC":
            kalemler = [
                h
                for h in kalemler
                if not (h.belge_no or "").startswith(_KAYNAK_ONEKLERI)
                or _d(h.satis_tutari) != 0
            ]
        kalemler.sort(key=AcikKalemService.fifo_sirasi)
        return kalemler

    @staticmethod
    def kalem_kapanan(session, hareket_id: int) -> Decimal:
        if not AcikKalemService._tablo_var(session):
            return Decimal("0")
        toplam = session.scalar(
            select(func.coalesce(func.sum(CariKapatma.tutar), 0)).where(
                CariKapatma.hedef_hareket_id == int(hareket_id), CariKapatma.iptal.is_(False)
            )
        )
        return _kurus(toplam)

    # --- Çekirdek düşüm (iyimser eşzamanlılık) ---
    @staticmethod
    def _kalan_guncelle(session, hareket: SatisHareketi, eski: Decimal, yeni: Decimal) -> bool:
        sonuc = session.execute(
            update(SatisHareketi)
            .where(
                SatisHareketi.id == hareket.id,
                func.abs(SatisHareketi.kalan_acik_tutar - float(eski)) < float(TOLERANS),
            )
            .values(kalan_acik_tutar=yeni)
            .execution_options(synchronize_session=False)
        )
        if sonuc.rowcount != 1:
            return False
        set_committed_value(hareket, "kalan_acik_tutar", yeni)
        return True

    @staticmethod
    def _guncel_kalan(session, hareket: SatisHareketi) -> Decimal:
        # autoflush kapalı: bekleyen ORM değişikliği okunan değerle ezilmesin
        session.flush()
        deger = session.execute(
            select(SatisHareketi.kalan_acik_tutar).where(SatisHareketi.id == hareket.id)
        ).scalar()
        deger = _kurus(deger)
        set_committed_value(hareket, "kalan_acik_tutar", deger)
        return deger

    @staticmethod
    def _dus(session, hareket: SatisHareketi, istenen: Decimal, *, kesin: bool) -> Decimal:
        """Kalemden en çok ``istenen`` kadar düşer; gerçekten düşülen tutarı döner.

        kesin=True (manuel seçim): güncel açık yetmezse AcikKalemDegisti fırlatır.
        Tedarikçi alış (negatif kalan): kalan sıfıra yaklaşır (ör. -1200 + 360 → -840).
        """
        for _ in range(5):
            eski = AcikKalemService._guncel_kalan(session, hareket)
            tedarik_alis = eski < 0 and _d(hareket.satis_tutari) < 0
            acik = -eski if tedarik_alis else eski
            if kesin and istenen > acik + TOLERANS:
                raise AcikKalemDegisti(
                    f"{hareket.belge_no} kaleminin açık tutarı {acik} — ayrılan {istenen} bunu aşıyor. "
                    "Kalem başka bir işlemle kapanmış olabilir; seçimi yenileyin."
                )
            miktar = min(acik, istenen)
            if miktar <= 0:
                return Decimal("0")
            yeni = _kurus(eski + miktar) if tedarik_alis else _kurus(eski - miktar)
            if AcikKalemService._kalan_guncelle(session, hareket, eski, yeni):
                return miktar
        raise AcikKalemDegisti(f"{hareket.belge_no} kalemi eşzamanlı güncelleniyor; tekrar deneyin.")

    @staticmethod
    def _ekle(session, hareket: SatisHareketi, miktar: Decimal) -> None:
        for _ in range(5):
            eski = AcikKalemService._guncel_kalan(session, hareket)
            if AcikKalemService._kalan_guncelle(session, hareket, eski, _kurus(eski + miktar)):
                return
        raise AcikKalemDegisti(f"{hareket.belge_no} kalemi eşzamanlı güncelleniyor; tekrar deneyin.")

    @staticmethod
    def beklenen_dogrula(session, cari_id: int, beklenen: dict | None) -> None:
        """Ekran açıldıktan sonra seçilen kalemlerin açık tutarı değiştiyse kaydı durdurur.

        Eski önizleme sessizce kaydedilmez; kullanıcı güncel dağıtımı görüp yeniden onaylar.
        """
        if not beklenen:
            return
        session.flush()
        for hid, tutar in beklenen.items():
            h = session.get(SatisHareketi, int(hid))
            if h is None or int(h.cari_id) != int(cari_id):
                raise AcikKalemDegisti("Seçilen açık kalem bulunamadı; liste yenilenmeli.")
            guncel = AcikKalemService._guncel_kalan(session, h)
            if abs(guncel - _kurus(tutar)) > TOLERANS:
                raise AcikKalemDegisti(
                    f"{h.belge_no} belgesinin açık tutarı ekran açıldıktan sonra değişti "
                    f"({_kurus(tutar)} → {guncel})."
                )

    # --- Belge senkronu (fatura tahsil/ödeme tutarı) ---
    @staticmethod
    def belge_senkron(session, hareket: SatisHareketi, delta: Decimal) -> None:
        """delta>0: kalemden kapandı; <0: yeniden açıldı. Satış faturası evrak durumu AÇIK kalır."""
        if delta == 0 or not hareket.belge_no:
            return
        from database.models.satis_faturasi import SatisFaturasi

        fatura = session.scalar(
            select(SatisFaturasi).where(
                SatisFaturasi.fatura_no == hareket.belge_no,
                SatisFaturasi.cari_id == hareket.cari_id,
            )
        )
        if fatura is not None:
            if (fatura.durum or "") == "İPTAL":
                return
            fatura.tahsilat_tutari = max(Decimal("0"), _d(fatura.tahsilat_tutari) + delta)
            if fatura.onaylandi and (fatura.durum or "") == "KAPALI":
                fatura.durum = "AÇIK"
            return
        from database.models.alis_faturasi import AlisFaturasi

        alis = session.scalar(
            select(AlisFaturasi).where(
                AlisFaturasi.fatura_no == hareket.belge_no,
                AlisFaturasi.cari_id == hareket.cari_id,
            )
        )
        if alis is not None and (alis.durum or "") != "İPTAL":
            alis.odeme_tutari = max(Decimal("0"), _d(alis.odeme_tutari) + delta)
            from database.alis_faturasi_service import AlisFaturasiService

            toplam = AlisFaturasiService.toplam(alis.satirlar)["genel_toplam"]
            alis.durum = "KAPALI" if alis.odeme_tutari >= toplam else "AÇIK"

    # --- Kapatma ---
    @staticmethod
    def kapat(
        session,
        cari_id: int,
        tutar,
        *,
        belge_no: str,
        kaynak_tur: str = "TAHSILAT",
        tarih: date | None = None,
        dagitim: list[tuple[int, Any]] | None = None,
        fifo: bool = True,
        para_birimi: str = "TRY",
        kaynak_hareket_id: int | None = None,
        haric_ids: Iterable[int] = (),
        islem_kimligi: str | None = None,
        dagitim_yontem: str = "MANUEL",
    ) -> KapatmaSonucu:
        """Tutarı açık kalemlere uygular. Önce ``dagitim`` (hareket_id, tutar), kalan FIFO (fifo=True).

        ``dagitim_yontem``: seçimli satırlar için kayıt etiketi (MANUEL / BAGLI).
        Toplam tahsis belge tutarını, kalem tahsisi kalemin açık kalanını aşamaz.
        Dönüş: kapanan / kapanmayan kalan ve yazılan tahsis kayıtları.
        """
        tutar = _kurus(tutar)
        kimlik = islem_kimligi or str(uuid.uuid4())
        sonuc = KapatmaSonucu(Decimal("0"), tutar, kimlik, [])
        if tutar <= 0:
            return sonuc
        session.flush()
        kayit_yaz = AcikKalemService._tablo_var(session)
        kid, kadi = _kullanici()
        tarih = tarih or date.today()
        pb = (para_birimi or "TRY").upper()
        secim_yontem = (dagitim_yontem or "MANUEL").upper()
        if secim_yontem not in ("MANUEL", "BAGLI", "SIPARIS"):
            secim_yontem = "MANUEL"

        def _kaydet(h: SatisHareketi, miktar: Decimal, yontem: str) -> None:
            AcikKalemService.belge_senkron(session, h, miktar)
            if not kayit_yaz or not belge_no:
                return
            kayit = CariKapatma(
                islem_kimligi=kimlik,
                cari_id=int(cari_id),
                kaynak_belge_no=belge_no,
                kaynak_tur=kaynak_tur,
                kaynak_hareket_id=kaynak_hareket_id,
                hedef_hareket_id=int(h.id),
                hedef_belge_no=h.belge_no or "",
                tutar=miktar,
                para_birimi=pb,
                tarih=tarih,
                yontem=yontem,
                kullanici_id=kid,
                kullanici_adi=kadi,
                olusturma=datetime.now(),
                iptal=False,
            )
            session.add(kayit)
            sonuc.kayitlar.append(kayit)

        kalan = tutar
        haric = {int(i) for i in haric_ids}
        if dagitim:
            satirlar = [(int(hid), _kurus(t)) for hid, t in dagitim if _kurus(t) > 0]
            if sum((t for _, t in satirlar), Decimal("0")) > tutar + TOLERANS:
                raise ValueError("Dağıtım toplamı belge tutarını aşamaz.")
            for hid, miktar in satirlar:
                h = session.get(SatisHareketi, hid)
                if h is None or int(h.cari_id) != int(cari_id):
                    raise AcikKalemDegisti("Seçilen açık kalem bulunamadı; seçimi yenileyin.")
                if para_anahtari(h) != pb:
                    raise ValueError(
                        f"{h.belge_no} kalemi {para_anahtari(h)} cinsinden; {pb} ile kapatılamaz."
                    )
                dusulen = AcikKalemService._dus(session, h, min(miktar, kalan), kesin=True)
                if dusulen > 0:
                    kalan -= dusulen
                    _kaydet(h, dusulen, secim_yontem)
                haric.add(hid)
        if fifo and kalan > 0:
            for h in AcikKalemService.acik_kalemler(
                session, cari_id, yon="BORC", para_birimi=pb, haric_ids=haric
            ):
                if kalan <= 0:
                    break
                dusulen = AcikKalemService._dus(session, h, kalan, kesin=False)
                if dusulen > 0:
                    kalan -= dusulen
                    _kaydet(h, dusulen, "FIFO")
        session.flush()
        sonuc.kalan = _kurus(kalan)
        sonuc.kapanan = _kurus(tutar - kalan)
        return sonuc

    @staticmethod
    def avans_ekle(session, cari_id: int, tutar, *, belge_no: str, tarih: date, para_birimi="TRY"):
        """Fazla tahsilat/ödeme: açık kredi satırı (aynı belgeninki varsa büyütülür)."""
        tutar = _kurus(tutar)
        if tutar <= 0:
            return None
        pb = (para_birimi or "TRY").upper()
        mevcut = session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.cari_id == int(cari_id),
                SatisHareketi.belge_no == belge_no,
                SatisHareketi.satis_tutari == 0,
            )
        )
        if mevcut is not None and _d(mevcut.kalan_acik_tutar) <= 0:
            AcikKalemService._ekle(session, mevcut, -tutar)
            return mevcut
        satir = SatisHareketi(
            cari_id=int(cari_id),
            satis_tarihi=tarih,
            belge_no=belge_no,
            satis_tutari=Decimal("0"),
            kalan_acik_tutar=-tutar,
            para_birimi=pb,
            borc_esasi="DOVIZ_SABIT" if pb != "TRY" else "TL_SABIT",
        )
        session.add(satir)
        session.flush()
        return satir

    @staticmethod
    def alacak_etkisi(
        session,
        cari_id: int,
        tutar,
        *,
        belge_no: str,
        tarih: date,
        kaynak_tur: str = "TAHSILAT",
        dagitim: list[tuple[int, Any]] | None = None,
        fazla: str = "FIFO",
        para_birimi: str = "TRY",
    ) -> dict:
        """Tahsilat (müşteri) / ödeme (tedarikçi) / iade / alacak dekontu etkisi.

        fazla: dağıtım sonrası kalan için "FIFO" (kalan eskiden yeniye kapanır, artanı avans)
        veya "AVANS" (dağıtım dışı kalan doğrudan avans).
        """
        sonuc = AcikKalemService.kapat(
            session,
            cari_id,
            tutar,
            belge_no=belge_no,
            kaynak_tur=kaynak_tur,
            tarih=tarih,
            dagitim=dagitim,
            fifo=(fazla != "AVANS"),
            para_birimi=para_birimi,
        )
        avans = sonuc.kalan
        if avans > 0:
            AcikKalemService.avans_ekle(
                session, cari_id, avans, belge_no=belge_no, tarih=tarih, para_birimi=para_birimi
            )
        return {"kapanan": sonuc.kapanan, "avans": avans, "islem_kimligi": sonuc.islem_kimligi}

    @staticmethod
    def _siparis_avansi_mi(session, belge_no: str | None) -> bool:
        """Belge no açık/kısmi satış siparişine ait rezerv avans mı?"""
        bn = (belge_no or "").strip()
        if not bn:
            return False
        from database.models.satis_siparisi import SatisSiparisi

        durum = session.scalar(
            select(SatisSiparisi.durum).where(SatisSiparisi.siparis_no == bn)
        )
        if durum is None:
            return False
        return (durum or "").upper() not in ("İPTAL", "IPTAL")

    @staticmethod
    def avanslari_uygula(session, cari_id: int, *, para_birimi: str | None = None) -> Decimal:
        """Açık krediyi (avans) açık belge kalemlerine FIFO ile uygular; uygulanan toplamı döner.

        Satış siparişi rezerv avansı atlanır — yalnız ilgili faturaya BAGLI/SIPARIS ile taşınır.
        """
        session.flush()
        toplam = Decimal("0")
        birimler = (
            [para_birimi.upper()]
            if para_birimi
            else sorted({para_anahtari(h) for h in AcikKalemService.acik_kalemler(
                session, cari_id, yon="AVANS", para_birimi=None)})
        )
        for pb in birimler:
            for avans in AcikKalemService.acik_kalemler(session, cari_id, yon="AVANS", para_birimi=pb):
                if AcikKalemService._siparis_avansi_mi(session, avans.belge_no):
                    continue
                mevcut = -AcikKalemService._guncel_kalan(session, avans)
                if mevcut <= 0:
                    continue
                sonuc = AcikKalemService.kapat(
                    session,
                    cari_id,
                    mevcut,
                    belge_no=avans.belge_no,
                    kaynak_tur="AVANS",
                    tarih=date.today(),
                    para_birimi=pb,
                    kaynak_hareket_id=int(avans.id),
                    haric_ids=[int(avans.id)],
                )
                if sonuc.kapanan > 0:
                    AcikKalemService._ekle(session, avans, sonuc.kapanan)
                    toplam += sonuc.kapanan
                if sonuc.kalan > 0:
                    break
        return _kurus(toplam)

    @staticmethod
    def siparis_avansini_faturaya_tasi(session, fatura) -> Decimal:
        """Bağlı siparişin rezerv avansını bu faturaya uygular (kasa yazmaz). Taşınan tutarı döner."""
        siparis_id = getattr(fatura, "siparis_id", None)
        if not siparis_id:
            return Decimal("0")
        from database.models.satis_siparisi import SatisSiparisi

        siparis = session.get(SatisSiparisi, int(siparis_id))
        if siparis is None:
            return Decimal("0")
        belge = (siparis.siparis_no or "").strip()
        if not belge:
            return Decimal("0")
        session.flush()
        avans = session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.cari_id == int(fatura.cari_id),
                SatisHareketi.belge_no == belge,
                SatisHareketi.satis_tutari == 0,
                SatisHareketi.kalan_acik_tutar < 0,
            )
        )
        if avans is None:
            return Decimal("0")
        rezerv = -_kurus(avans.kalan_acik_tutar)
        if rezerv <= 0:
            return Decimal("0")
        hareket = session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.belge_no == fatura.fatura_no,
                SatisHareketi.satis_tutari > 0,
            )
        )
        if hareket is None:
            return Decimal("0")
        acik = _kurus(hareket.kalan_acik_tutar)
        pay = min(rezerv, acik)
        if pay <= 0:
            return Decimal("0")
        if getattr(hareket, "id", None) is None:
            session.flush()
        sonuc = AcikKalemService.kapat(
            session,
            int(fatura.cari_id),
            pay,
            belge_no=belge,
            kaynak_tur="AVANS",
            tarih=getattr(fatura, "fatura_tarihi", None) or date.today(),
            dagitim=[(int(hareket.id), pay)],
            fifo=False,
            dagitim_yontem="SIPARIS",
            kaynak_hareket_id=int(avans.id),
            para_birimi=para_anahtari(hareket),
        )
        if sonuc.kapanan > 0:
            AcikKalemService._ekle(session, avans, sonuc.kapanan)
        return _kurus(sonuc.kapanan)

    @staticmethod
    def borc_etkisi(
        session,
        cari_id: int,
        tutar,
        *,
        belge_no: str,
        tarih: date,
        para_birimi: str = "TRY",
        kur=None,
    ) -> SatisHareketi:
        """Müşteriye ödeme / borç dekontu / virman hedefi: yeni açık kalem, varsa avans ona uygulanır."""
        tutar = _kurus(tutar)
        pb = (para_birimi or "TRY").upper()
        kalem = SatisHareketi(
            cari_id=int(cari_id),
            satis_tarihi=tarih,
            belge_no=belge_no,
            satis_tutari=tutar,
            kalan_acik_tutar=tutar,
            para_birimi=pb,
            kur=_d(kur or 1),
            borc_esasi="DOVIZ_SABIT" if pb != "TRY" else "TL_SABIT",
        )
        session.add(kalem)
        session.flush()
        AcikKalemService.avanslari_uygula(session, cari_id, para_birimi=pb)
        return kalem

    # --- Geri alma ---
    @staticmethod
    def _kaydi_iptal_et(kayit: CariKapatma, neden: str, kimlik: str) -> None:
        _, kadi = _kullanici()
        kayit.iptal = True
        kayit.iptal_zamani = datetime.now()
        kayit.iptal_kullanici = kadi
        kayit.iptal_nedeni = (neden or "")[:300] or None
        kayit.iptal_islem_kimligi = kimlik

    @staticmethod
    def _kaydi_bol(session, kayit: CariKapatma, geri: Decimal, neden: str, kimlik: str) -> None:
        """Kaydın ``geri`` kadarını iptal eder; kalan kısım yeni aktif kayıt olarak sürer."""
        kalan = _kurus(_d(kayit.tutar) - geri)
        AcikKalemService._kaydi_iptal_et(kayit, neden, kimlik)
        if kalan > 0:
            session.add(
                CariKapatma(
                    islem_kimligi=kayit.islem_kimligi,
                    cari_id=kayit.cari_id,
                    kaynak_belge_no=kayit.kaynak_belge_no,
                    kaynak_tur=kayit.kaynak_tur,
                    kaynak_hareket_id=kayit.kaynak_hareket_id,
                    hedef_hareket_id=kayit.hedef_hareket_id,
                    hedef_belge_no=kayit.hedef_belge_no,
                    tutar=kalan,
                    para_birimi=kayit.para_birimi,
                    tarih=kayit.tarih,
                    yontem=kayit.yontem,
                    kullanici_id=kayit.kullanici_id,
                    kullanici_adi=kayit.kullanici_adi,
                    olusturma=kayit.olusturma,
                    iptal=False,
                )
            )

    @staticmethod
    def belge_kayitli_mi(session, cari_id: int, belge_no: str) -> bool:
        """Belge yeni altyapıyla işlenmiş mi (tahsis kaydı veya kendi avans satırı var)."""
        if not belge_no:
            return False
        if AcikKalemService._tablo_var(session) and session.scalar(
            select(CariKapatma.id).where(
                CariKapatma.cari_id == int(cari_id), CariKapatma.kaynak_belge_no == belge_no
            ).limit(1)
        ):
            return True
        return False

    @staticmethod
    def belge_geri_al(
        session, cari_id: int, belge_no: str, tutar=None, *, neden: str = "Belge iptal/düzeltme"
    ) -> Decimal:
        """Kaynak belgenin tahsislerini (LIFO) ve kendi avansını geri alır; geri alınan toplamı döner."""
        if not belge_no:
            return Decimal("0")
        session.flush()
        sinir = None if tutar is None else _kurus(tutar)
        geri_toplam = Decimal("0")
        kimlik = str(uuid.uuid4())

        def _kalan_sinir() -> Decimal | None:
            return None if sinir is None else sinir - geri_toplam

        if AcikKalemService._tablo_var(session):
            kayitlar = list(
                session.scalars(
                    select(CariKapatma)
                    .where(
                        CariKapatma.cari_id == int(cari_id),
                        CariKapatma.kaynak_belge_no == belge_no,
                        CariKapatma.iptal.is_(False),
                    )
                    .order_by(CariKapatma.id.desc())
                ).all()
            )
            for kayit in kayitlar:
                ks = _kalan_sinir()
                if ks is not None and ks <= 0:
                    break
                miktar = _d(kayit.tutar) if ks is None else min(_d(kayit.tutar), ks)
                hedef = session.get(SatisHareketi, int(kayit.hedef_hareket_id))
                if hedef is not None:
                    AcikKalemService._ekle(session, hedef, miktar)
                    AcikKalemService.belge_senkron(session, hedef, -miktar)
                if kayit.kaynak_hareket_id:
                    kaynak = session.get(SatisHareketi, int(kayit.kaynak_hareket_id))
                    if kaynak is not None:
                        AcikKalemService._ekle(session, kaynak, -miktar)
                if miktar >= _d(kayit.tutar):
                    AcikKalemService._kaydi_iptal_et(kayit, neden, kimlik)
                else:
                    AcikKalemService._kaydi_bol(session, kayit, miktar, neden, kimlik)
                geri_toplam += miktar
            session.flush()

        # Belgenin kendi avans satırı: tahsis edilmemiş (kalan) kısmı kaldır
        avanslar = list(
            session.scalars(
                select(SatisHareketi)
                .where(
                    SatisHareketi.cari_id == int(cari_id),
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.satis_tutari == 0,
                )
                .order_by(SatisHareketi.id.desc())
            ).all()
        )
        for avans in avanslar:
            mevcut = -AcikKalemService._guncel_kalan(session, avans)
            ks = _kalan_sinir()
            miktar = mevcut if ks is None else min(mevcut, max(ks, Decimal("0")))
            if miktar > 0:
                AcikKalemService._ekle(session, avans, miktar)
                geri_toplam += miktar
            if AcikKalemService._guncel_kalan(session, avans) == 0:
                session.delete(avans)
        session.flush()
        return _kurus(geri_toplam)

    @staticmethod
    def kalem_kaldir(session, hareket: SatisHareketi, *, neden: str = "Belge onayı kaldırıldı/iptal") -> Decimal:
        """Açık kalem silinmeden önce: ona yapılan tahsisleri iptal edip kaynaklara avans olarak iade eder."""
        if hareket is None or not AcikKalemService._tablo_var(session):
            return Decimal("0")
        session.flush()
        kimlik = str(uuid.uuid4())
        toplam = Decimal("0")
        kayitlar = list(
            session.scalars(
                select(CariKapatma).where(
                    CariKapatma.hedef_hareket_id == int(hareket.id), CariKapatma.iptal.is_(False)
                )
            ).all()
        )
        for kayit in kayitlar:
            miktar = _d(kayit.tutar)
            kaynak = (
                session.get(SatisHareketi, int(kayit.kaynak_hareket_id))
                if kayit.kaynak_hareket_id
                else None
            )
            if kaynak is not None:
                AcikKalemService._ekle(session, kaynak, -miktar)
            else:
                AcikKalemService.avans_ekle(
                    session,
                    kayit.cari_id,
                    miktar,
                    belge_no=kayit.kaynak_belge_no,
                    tarih=kayit.tarih,
                    para_birimi=kayit.para_birimi,
                )
            AcikKalemService._kaydi_iptal_et(kayit, neden, kimlik)
            toplam += miktar
        if toplam > 0:
            AcikKalemService._ekle(session, hareket, toplam)
            AcikKalemService.belge_senkron(session, hareket, -toplam)
        session.flush()
        return _kurus(toplam)

    @staticmethod
    def belge_kalemlerini_sil(
        session, belge_no: str, cari_id: int | None = None, *, neden: str = "Belge geri alındı"
    ) -> None:
        """Belgenin açık kalem satırlarını denetim izini koruyarak kaldırır.

        Belge kaynak olarak kapattıklarını geri açar, hedef olarak aldığı tahsisleri kaynaklarına
        avans olarak iade eder; ardından serbest kalan avanslar FIFO ile yeniden uygulanır.
        """
        if not belge_no:
            return
        session.flush()
        sorgu = select(SatisHareketi).where(SatisHareketi.belge_no == belge_no)
        if cari_id is not None:
            sorgu = sorgu.where(SatisHareketi.cari_id == int(cari_id))
        satirlar = list(session.scalars(sorgu).all())
        cariler = {int(h.cari_id) for h in satirlar}
        if cari_id is not None:
            cariler.add(int(cari_id))
        for cid in cariler:
            AcikKalemService.belge_geri_al(session, cid, belge_no, neden=neden)
        for h in session.scalars(sorgu).all():
            if _d(h.satis_tutari) > 0:
                AcikKalemService.kalem_kaldir(session, h, neden=neden)
            session.delete(h)
        session.flush()
        for cid in cariler:
            AcikKalemService.avanslari_uygula(session, cid)

    # --- Raporlama / mutabakat ---
    @staticmethod
    def _evrak_turu(session, hareket: SatisHareketi) -> str:
        bn = hareket.belge_no or ""
        if bn.startswith(GECIS_DEVIR_ONEKI):
            return "Geçiş Devir Farkı"
        if _d(hareket.satis_tutari) == 0 and _d(hareket.kalan_acik_tutar) < 0:
            return "Avans / Açık Kredi"
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.cari import CariIslem
        from database.models.satis_faturasi import SatisFaturasi

        if session.scalar(select(SatisFaturasi.id).where(SatisFaturasi.fatura_no == bn)):
            return "Satış Faturası"
        if session.scalar(select(AlisFaturasi.id).where(AlisFaturasi.fatura_no == bn)):
            return "Alış Faturası"
        islem = session.scalar(select(CariIslem.islem_turu).where(CariIslem.belge_no == bn).limit(1))
        if islem:
            return "Devir" if islem == "Açılış" else islem
        if bn.startswith("IPT-"):
            return "İptal Karşılığı"
        return "Diğer"

    @staticmethod
    def _vade(session, hareket: SatisHareketi) -> date | None:
        """Esas vade: özgün vade; yoksa belge tarihi."""
        return AcikKalemService._esas_vade(session, hareket)[0]

    @staticmethod
    def _esas_vade(session, hareket: SatisHareketi) -> tuple[date | None, str | None]:
        """(esas_vade, vade_kaynak) — VADE | BELGE_TARIHI."""
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.satis_faturasi import SatisFaturasi

        bn = hareket.belge_no or ""
        vade = session.scalar(select(SatisFaturasi.vade_tarihi).where(SatisFaturasi.fatura_no == bn))
        if vade is None:
            vade = session.scalar(select(AlisFaturasi.vade_tarihi).where(AlisFaturasi.fatura_no == bn))
        if isinstance(vade, date):
            return vade, "VADE"
        if isinstance(hareket.satis_tarihi, date):
            return hareket.satis_tarihi, "BELGE_TARIHI"
        return None, None

    @staticmethod
    def belge_tahsisleri(session, cari_id: int, belge_no: str | None) -> dict:
        """Kaynak belgenin aktif tahsisleri.

        ``dogrudan``: belgenin kendi kapattıkları {hareket_id: tutar}; ``yontem``: {hareket_id: {"MANUEL","FIFO"}};
        ``tum``: geri almada açılacak toplam (belge avansının sonradan kapattıkları dahil).
        """
        sonuc = {"dogrudan": {}, "yontem": {}, "tum": {}}
        if not belge_no or not AcikKalemService._tablo_var(session):
            return sonuc
        session.flush()
        for k in session.scalars(
            select(CariKapatma).where(
                CariKapatma.cari_id == int(cari_id),
                CariKapatma.kaynak_belge_no == belge_no,
                CariKapatma.iptal.is_(False),
            ).order_by(CariKapatma.id)
        ).all():
            hid = int(k.hedef_hareket_id)
            tutar = _d(k.tutar)
            sonuc["tum"][hid] = _kurus(sonuc["tum"].get(hid, Decimal("0")) + tutar)
            if k.kaynak_hareket_id is None:
                sonuc["dogrudan"][hid] = _kurus(sonuc["dogrudan"].get(hid, Decimal("0")) + tutar)
                sonuc["yontem"].setdefault(hid, set()).add((k.yontem or "FIFO").upper())
        return sonuc

    @staticmethod
    def _secim_satiri(session, h: SatisHareketi, geri: Decimal = Decimal("0"), kayitli: Decimal = Decimal("0")):
        ilk = _kurus(h.satis_tutari)
        kalan = _kurus(_d(h.kalan_acik_tutar) + geri)
        esas, vade_kaynak = AcikKalemService._esas_vade(session, h)
        if isinstance(esas, date) and vade_kaynak == "BELGE_TARIHI":
            vade_etiket = f"{esas.strftime('%d.%m.%Y')} (belge)"
        elif isinstance(esas, date):
            vade_etiket = esas.strftime("%d.%m.%Y")
        else:
            vade_etiket = ""
        return {
            "hareket_id": int(h.id),
            "tarih": h.satis_tarihi,
            "tur": AcikKalemService._evrak_turu(session, h),
            "evrak_no": h.belge_no or "",
            "ilk_tutar": ilk,
            "kapanan": max(Decimal("0"), ilk - kalan),
            "kalan": kalan,
            "vade": esas,
            "esas_vade": esas,
            "vade_kaynak": vade_kaynak,
            "vade_etiket": vade_etiket,
            "para_birimi": para_anahtari(h),
            "kayitli_dagitim": _kurus(kayitli),
        }

    @staticmethod
    def secim_listesi(session, cari_id: int, *, para_birimi: str = "TRY",
                      haric_belge_no: str | None = None) -> list[dict]:
        """Tahsilat/Ödeme seçim penceresi satırları (açık belge kalemleri, FIFO sıralı).

        ``haric_belge_no`` (kayıtlı makbuz düzenlemesi): o belgenin tahsisleri geri alınmış gibi gösterilir;
        yalnız o belgeyle kapanmış kalemler de listeye girer. Kayıtta servis aynı geri almayı yapar.
        """
        tahsis = AcikKalemService.belge_tahsisleri(session, cari_id, haric_belge_no)
        tum, dogrudan = tahsis["tum"], tahsis["dogrudan"]
        satirlar = []
        gorulen = set()
        for h in AcikKalemService.acik_kalemler(session, cari_id, yon="BORC", para_birimi=para_birimi):
            gorulen.add(int(h.id))
            satirlar.append(AcikKalemService._secim_satiri(
                session, h, tum.get(int(h.id), Decimal("0")), dogrudan.get(int(h.id), Decimal("0"))))
        pb = (para_birimi or "TRY").upper()
        for hid, geri in tum.items():
            if hid in gorulen or geri <= 0:
                continue
            h = session.get(SatisHareketi, hid)
            if h is None or int(h.cari_id) != int(cari_id) or _d(h.satis_tutari) <= 0 or para_anahtari(h) != pb:
                continue
            satirlar.append(AcikKalemService._secim_satiri(session, h, geri, dogrudan.get(hid, Decimal("0"))))
        satirlar.sort(key=lambda s: (s["tarih"] or date.min, s["evrak_no"], s["hareket_id"]))
        return [s for s in satirlar if s["kalan"] > 0]

    @staticmethod
    def secim_listesi_getir(cari_id: int, *, para_birimi: str = "TRY", haric_belge_no: str | None = None) -> list[dict]:
        from database.database import get_session

        with get_session() as session:
            return AcikKalemService.secim_listesi(session, int(cari_id), para_birimi=para_birimi,
                                                  haric_belge_no=haric_belge_no)

    @staticmethod
    def belge_secim_durumu(cari_id: int, belge_no: str, *, para_birimi: str = "TRY") -> dict:
        """Kayıtlı belgenin düzenleme ekranına yüklenecek kapatma seçimi.

        ``secili``: kullanıcının seçtiği (MANUEL) kalemler; boşsa belge otomatik FIFO ile kaydedilmiştir.
        ``dagitim``: seçili kalemlere kayıtlı tutarlar; ``fazla``: seçim dışı kısım FIFO mu avans mı.
        ``kalemler``: belge geri alınmış gibi açık tutarlar (``beklenen`` doğrulaması bunlarla yapılır).
        """
        from database.database import get_session

        with get_session() as session:
            tahsis = AcikKalemService.belge_tahsisleri(session, int(cari_id), belge_no)
            kalemler = AcikKalemService.secim_listesi(session, int(cari_id), para_birimi=para_birimi,
                                                      haric_belge_no=belge_no)
        listede = {int(k["hareket_id"]) for k in kalemler}
        secili = [hid for hid, y in tahsis["yontem"].items() if "MANUEL" in y and hid in listede]
        fifo_var = any("FIFO" in y for y in tahsis["yontem"].values())
        return {
            "kalemler": kalemler,
            "secili": secili,
            "dagitim": {hid: tahsis["dogrudan"][hid] for hid in secili},
            "fazla": "FIFO" if (fifo_var or not secili) else "AVANS",
        }

    @staticmethod
    def diger_para_kalemleri(cari_id: int, *, para_birimi: str = "TRY") -> dict[str, int]:
        """Seçim listesine girmeyen (başka para birimli) açık kalem sayıları: {para_birimi: adet}."""
        from database.database import get_session

        sonuc: dict[str, int] = {}
        with get_session() as session:
            for h in AcikKalemService.acik_kalemler(session, int(cari_id), yon="BORC", para_birimi=None):
                pb = para_anahtari(h)
                if pb != (para_birimi or "TRY").upper():
                    sonuc[pb] = sonuc.get(pb, 0) + 1
        return sonuc

    @staticmethod
    def acik_kalem_raporu(session, cari_id: int | None = None, *, bugun: date | None = None) -> list[dict]:
        """Açık Borçlar ve Faturalar raporu için sorgulanabilir veri (açık belge + avans kalemleri).

        Tedarikçi açık alış (satis_tutari<0, kalan<0) pozitif ``acik`` / ``orijinal`` ile BORÇ
        satırı olarak döner; yalnız tutar=0 kalan<0 avans (negatif ``acik``) sayılır.
        """
        from database.models.cari import Cari

        bugun = bugun or date.today()
        sorgu = select(SatisHareketi).where(func.abs(SatisHareketi.kalan_acik_tutar) > float(TOLERANS))
        if cari_id is not None:
            sorgu = sorgu.where(SatisHareketi.cari_id == int(cari_id))
        kalemler = sorted(session.scalars(sorgu).all(), key=lambda h: (h.cari_id,) + AcikKalemService.fifo_sirasi(h))
        tahsis_var = AcikKalemService._tablo_var(session)
        cariler: dict[int, Any] = {}
        sonuc = []
        for h in kalemler:
            sinif = kalem_sinifi(h)
            if sinif == "DIGER":
                continue
            cari = cariler.get(h.cari_id)
            if cari is None:
                cari = cariler[h.cari_id] = session.get(Cari, h.cari_id)
            vade = AcikKalemService._vade(session, h)
            ham_tutar = _kurus(h.satis_tutari)
            ham_kalan = _kurus(h.kalan_acik_tutar)
            if sinif == "BORC" and ham_tutar < 0 and ham_kalan < 0:
                orijinal = _kurus(-ham_tutar)
                acik = _kurus(-ham_kalan)
            elif sinif == "AVANS":
                orijinal = Decimal("0")
                acik = ham_kalan  # negatif — UI avans olarak toplar
            else:
                orijinal = ham_tutar if ham_tutar > 0 else Decimal("0")
                acik = ham_kalan
            tahsisler = []
            if tahsis_var:
                tahsisler = [
                    {"kaynak_belge_no": k.kaynak_belge_no, "tutar": _kurus(k.tutar), "tarih": k.tarih,
                     "yontem": k.yontem}
                    for k in session.scalars(
                        select(CariKapatma)
                        .where(CariKapatma.hedef_hareket_id == h.id, CariKapatma.iptal.is_(False))
                        .order_by(CariKapatma.id)
                    ).all()
                ]
            kapanan = Decimal("0")
            if orijinal > 0 and acik >= 0:
                kapanan = max(Decimal("0"), _kurus(orijinal - acik))
            sonuc.append(
                {
                    "cari_id": int(h.cari_id),
                    "cari_kodu": getattr(cari, "cari_kodu", "") or "",
                    "cari_unvan": getattr(cari, "unvan", "") or "",
                    "evrak_turu": AcikKalemService._evrak_turu(session, h),
                    "evrak_no": h.belge_no or "",
                    "evrak_tarihi": h.satis_tarihi,
                    "vade": vade,
                    "orijinal": orijinal,
                    "kapanan": kapanan,
                    "acik": acik,
                    "sinif": sinif,
                    "para_birimi": para_anahtari(h),
                    "tahsisler": tahsisler,
                    "gecikme_gunu": max(0, (bugun - vade).days) if (vade and acik > 0) else 0,
                }
            )
        return sonuc

    @staticmethod
    def _cari_yon(session, cari_id: int) -> str:
        from database.models.cari import Cari

        cari = session.get(Cari, int(cari_id))
        return "TEDARIKCI" if tedarikci_mi(getattr(cari, "cari_turu", None)) else "MUSTERI"

    @staticmethod
    def _acik_net_hesapla(session, cari_id: int) -> dict:
        """TRY açık belge / avans toplamları; müşteri ve tedarikçi işaretine göre net."""
        yon = AcikKalemService._cari_yon(session, cari_id)
        acik_borc = Decimal("0")
        avans = Decimal("0")
        for h in session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id))).all():
            if para_anahtari(h) != "TRY":
                continue
            sinif = kalem_sinifi(h)
            k = _kurus(h.kalan_acik_tutar)
            if sinif == "BORC":
                acik_borc += abs(k)
            elif sinif == "AVANS":
                avans += -k
        if yon == "TEDARIKCI":
            # Açık alış borcumuz (−); fazla ödeme avansı varlık (+)
            acik_net = _kurus(-acik_borc + avans)
        else:
            acik_net = _kurus(acik_borc - avans)
        return {
            "yon": yon,
            "acik_borc": _kurus(acik_borc),
            "avans": _kurus(avans),
            "acik_net": acik_net,
        }

    @staticmethod
    def kaynak_tahsis_aciklari(session, cari_id: int) -> list[dict]:
        """Deftere yansıyan CI hareketlerinin açık kalem tahsis açığı (belge bazında).

        Müşteri alacağı / tedarikçi ödemesi → kapatma+avans ile karşılanmalı.
        Müşteri borcu / tedarikçi alacağı → karşılık SatisHareketi açık kalemi olmalı.
        """
        from database.models.cari import CariIslem

        yon = AcikKalemService._cari_yon(session, cari_id)
        kayit_yaz = AcikKalemService._tablo_var(session)
        sonuc: list[dict] = []
        islemler = list(session.scalars(select(CariIslem).where(CariIslem.cari_id == int(cari_id))).all())
        # Aynı belge_no birden fazla CI satırı olabilir (KK çekimi vb.) — belge bazında topla
        belge_ozet: dict[str, dict] = {}
        for i in islemler:
            bn = (i.belge_no or "").strip()
            if not bn:
                continue
            o = belge_ozet.setdefault(
                bn,
                {
                    "belge_no": bn,
                    "tarih": i.tarih,
                    "islem_turu": i.islem_turu or "",
                    "borc": Decimal("0"),
                    "alacak": Decimal("0"),
                    "aciklama": (i.aciklama or "")[:120],
                },
            )
            o["borc"] = _kurus(o["borc"] + _d(i.borc))
            o["alacak"] = _kurus(o["alacak"] + _d(i.alacak))
            if i.tarih and (o["tarih"] is None or i.tarih < o["tarih"]):
                o["tarih"] = i.tarih
            if i.islem_turu:
                o["islem_turu"] = i.islem_turu

        for bn, o in sorted(belge_ozet.items(), key=lambda x: (x[1]["tarih"] or date.min, x[0])):
            kap = Decimal("0")
            if kayit_yaz:
                kap = _kurus(
                    session.scalar(
                        select(func.coalesce(func.sum(CariKapatma.tutar), 0)).where(
                            CariKapatma.cari_id == int(cari_id),
                            CariKapatma.kaynak_belge_no == bn,
                            CariKapatma.iptal.is_(False),
                        )
                    )
                )
            avans_sh = _kurus(
                sum(
                    (
                        -_kurus(h.kalan_acik_tutar)
                        for h in session.scalars(
                            select(SatisHareketi).where(
                                SatisHareketi.cari_id == int(cari_id),
                                SatisHareketi.belge_no == bn,
                                SatisHareketi.satis_tutari == 0,
                                SatisHareketi.kalan_acik_tutar < 0,
                            )
                        ).all()
                    ),
                    Decimal("0"),
                )
            )
            sh_borc = list(
                session.scalars(
                    select(SatisHareketi).where(
                        SatisHareketi.cari_id == int(cari_id),
                        SatisHareketi.belge_no == bn,
                    )
                ).all()
            )
            sh_acik_borc = _kurus(
                sum(
                    (abs(_kurus(h.kalan_acik_tutar)) for h in sh_borc if kalem_sinifi(h) == "BORC"),
                    Decimal("0"),
                )
            )
            # Belgeye ait tutarlı SH (fatura/açılış kalemi; avans satırı hariç)
            sh_belge_tutar = Decimal("0")
            for h in sh_borc:
                t = _kurus(h.satis_tutari)
                if t != 0:
                    sh_belge_tutar += abs(t)

            alacak, borc = o["alacak"], o["borc"]
            # Kapatıcı hareket: müşteri alacağı veya tedarikçi ödemesi (borç)
            if yon == "TEDARIKCI":
                kapatacak = borc
                acacak = alacak
            else:
                kapatacak = alacak
                acacak = borc

            tahsisli = _kurus(kap + avans_sh)
            tahsis_acik = _kurus(kapatacak - tahsisli) if kapatacak > 0 else Decimal("0")
            if tahsis_acik < 0:
                tahsis_acik = Decimal("0")

            # Defter borcu / açılış: karşılık açık kalem SH yoksa
            kalemsiz = Decimal("0")
            if acacak > 0 and sh_belge_tutar + TOLERANS < acacak:
                kalemsiz = _kurus(acacak - sh_belge_tutar)

            if tahsis_acik <= TOLERANS and kalemsiz <= TOLERANS:
                continue
            sonuc.append(
                {
                    "belge_no": bn,
                    "tarih": o["tarih"],
                    "islem_turu": o["islem_turu"],
                    "aciklama": o["aciklama"],
                    "borc": borc,
                    "alacak": alacak,
                    "kapatacak": _kurus(kapatacak),
                    "tahsisli": tahsisli,
                    "tahsis_acik": tahsis_acik,
                    "kalemsiz_borc": kalemsiz,
                    "sh_acik_borc": sh_acik_borc,
                    "tur": (
                        "TAHSIS_EKSIK"
                        if tahsis_acik > TOLERANS
                        else "KALEMSIZ_BORC"
                    ),
                }
            )
        return sonuc

    @staticmethod
    def mutabakat(session, cari_id: int) -> dict:
        """cari bakiye ↔ açık kalem neti (TRY); müşteri/tedarikçi yönüne göre işaret."""
        from database.cari_bakiye_service import net_bakiye

        bakiye = _kurus(net_bakiye(int(cari_id), session=session)["bakiye"])
        ozet = AcikKalemService._acik_net_hesapla(session, int(cari_id))
        acik_net = ozet["acik_net"]
        return {
            "cari_id": int(cari_id),
            "yon": ozet["yon"],
            "bakiye": bakiye,
            "acik_borc": ozet["acik_borc"],
            "avans": ozet["avans"],
            "acik_net": acik_net,
            "fark": _kurus(bakiye - acik_net),
            "uyumlu": abs(bakiye - acik_net) <= TOLERANS,
        }

    @staticmethod
    def mutabakat_detay(session, cari_id: int) -> dict:
        """Mutabakat + farkı açıklayan belgeler (tahsis eksiği / kalemsiz defter borcu).

        Müşteri: tahsis eksiği açığı yüksek bırakır (fark −); kalemsiz borc bakiyeyi yükseltir (fark +).
        Tedarikçi: tahsis eksiği (ödeme bağlanmamış) açık borcu yüksek bırakır → acik_net daha (−),
        fark +; kalemsiz alacak bakiyeyi düşürür (fark −).
        """
        base = AcikKalemService.mutabakat(session, int(cari_id))
        belgeler = AcikKalemService.kaynak_tahsis_aciklari(session, int(cari_id))
        aciklanan = Decimal("0")
        for b in belgeler:
            if base["yon"] == "MUSTERI":
                aciklanan += -b["tahsis_acik"] + b["kalemsiz_borc"]
            else:
                aciklanan += b["tahsis_acik"] - b["kalemsiz_borc"]
        aciklanan = _kurus(aciklanan)
        return {
            **base,
            "belgeler": belgeler,
            "aciklanan_fark": aciklanan,
            "kalan_fark": _kurus(base["fark"] - aciklanan),
        }

    @staticmethod
    def eksik_tahsisleri_onar(session, cari_id: int, *, dry_run: bool = False) -> dict:
        """Deftere yansıyan ama açık kaleme bağlanmamış CI hareketlerini FIFO ile onarır.

        - Kapatıcı tutar (müşteri alacağı / tedarikçi ödemesi) → ``alacak_etkisi``
        - Kalemsiz defter borcu (müşteri) / kalemsiz alacak (tedarikçi açılış) → ``borc_etkisi``
          (aynı belge_no ile SH; net_bakiye CI'yi saydığı için çift sayılmaz)
        """
        detay = AcikKalemService.mutabakat_detay(session, int(cari_id))
        uygulanan: list[dict] = []
        if detay["uyumlu"] and not detay["belgeler"]:
            return {"cari_id": int(cari_id), "dry_run": dry_run, "uygulanan": [], "once": detay, "sonra": detay}

        for b in detay["belgeler"]:
            bn = b["belge_no"]
            tarih = b["tarih"] or date.today()
            tur = (b["islem_turu"] or "").strip()
            if b["tahsis_acik"] > TOLERANS:
                kaynak = "ODEME" if detay["yon"] == "TEDARIKCI" else "TAHSILAT"
                if tur.upper() in ("KK ÇEKİMİ", "KK CEKIMI", "KK_CEKIMI") or bn.startswith("KKC-"):
                    kaynak = "KK_CEKIMI"
                elif tur == "43" or bn.startswith("EVB-EX-"):
                    kaynak = "TAHSILAT"
                uygulanan.append(
                    {
                        "belge_no": bn,
                        "islem": "ALACAK_ETKISI",
                        "tutar": b["tahsis_acik"],
                        "kaynak_tur": kaynak,
                        "tarih": tarih,
                    }
                )
                if not dry_run:
                    AcikKalemService.alacak_etkisi(
                        session,
                        int(cari_id),
                        b["tahsis_acik"],
                        belge_no=bn,
                        tarih=tarih if isinstance(tarih, date) else date.today(),
                        kaynak_tur=kaynak,
                    )
            if b["kalemsiz_borc"] > TOLERANS:
                uygulanan.append(
                    {
                        "belge_no": bn,
                        "islem": "BORC_ETKISI",
                        "tutar": b["kalemsiz_borc"],
                        "kaynak_tur": tur or "AÇILIŞ",
                        "tarih": tarih,
                    }
                )
                if not dry_run:
                    # Belgede kısmi SH varsa yalnız eksiği ekle
                    mevcut = session.scalar(
                        select(SatisHareketi).where(
                            SatisHareketi.cari_id == int(cari_id),
                            SatisHareketi.belge_no == bn,
                            SatisHareketi.satis_tutari != 0,
                        )
                    )
                    if mevcut is None:
                        AcikKalemService.borc_etkisi(
                            session,
                            int(cari_id),
                            b["kalemsiz_borc"],
                            belge_no=bn,
                            tarih=tarih if isinstance(tarih, date) else date.today(),
                        )
                    else:
                        # Mevcut SH tutarını yükseltmek riskli; tanıya bırak
                        uygulanan[-1]["atlandi"] = "mevcut_sh_var"

        session.flush()
        sonra = AcikKalemService.mutabakat_detay(session, int(cari_id)) if not dry_run else detay
        return {
            "cari_id": int(cari_id),
            "dry_run": dry_run,
            "uygulanan": uygulanan,
            "once": {k: detay[k] for k in ("bakiye", "acik_borc", "avans", "acik_net", "fark", "uyumlu", "yon")},
            "sonra": {k: sonra[k] for k in ("bakiye", "acik_borc", "avans", "acik_net", "fark", "uyumlu", "yon")},
            "kalan_belgeler": sonra.get("belgeler") or [],
        }

    @staticmethod
    def eksik_tahsisleri_onar_toplu(
        session, *, dry_run: bool = False, sadece_uyumsuz: bool = True
    ) -> dict:
        """Tüm aktif carilerde ``eksik_tahsisleri_onar``; müşteri/tedarikçi yönü belge bazında."""
        from database.models.cari import Cari

        cariler = list(
            session.scalars(
                select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)
            ).all()
        )
        ozet = {
            "dry_run": dry_run,
            "cari_adet": len(cariler),
            "onarilan": 0,
            "uyumlu": 0,
            "uyumsuz_kalan": 0,
            "satirlar": [],
        }
        for c in cariler:
            once = AcikKalemService.mutabakat_detay(session, int(c.id))
            if sadece_uyumsuz and once["uyumlu"] and not once["belgeler"]:
                ozet["uyumlu"] += 1
                continue
            sonuc = AcikKalemService.eksik_tahsisleri_onar(
                session, int(c.id), dry_run=dry_run
            )
            sonra = sonuc["sonra"]
            if sonuc["uygulanan"]:
                ozet["onarilan"] += 1
            if sonra.get("uyumlu"):
                ozet["uyumlu"] += 1
            else:
                ozet["uyumsuz_kalan"] += 1
            ozet["satirlar"].append(
                {
                    "cari_id": int(c.id),
                    "kod": c.cari_kodu,
                    "unvan": c.unvan,
                    "yon": once.get("yon"),
                    "once_fark": once["fark"],
                    "sonra_fark": sonra["fark"],
                    "uygulanan": len(sonuc["uygulanan"]),
                    "uyumlu": sonra.get("uyumlu"),
                    "kalan_belgeler": [
                        {
                            "belge_no": b["belge_no"],
                            "tur": b.get("tur") or b.get("islem_turu"),
                            "tahsis_acik": b.get("tahsis_acik"),
                            "kalemsiz_borc": b.get("kalemsiz_borc"),
                        }
                        for b in (sonuc.get("kalan_belgeler") or [])
                    ],
                }
            )
        return ozet
