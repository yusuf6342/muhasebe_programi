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


def odeme_durumu(toplam, kapanan) -> str:
    """Evrak durumundan bağımsız ödeme durumu metni."""
    toplam = _kurus(toplam)
    kapanan = _kurus(kapanan)
    if toplam <= 0:
        return ""
    if kapanan <= 0:
        return "Ödenmedi"
    if kapanan + TOLERANS >= toplam:
        return "Ödendi"
    return "Kısmi Ödendi"


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
        """yon BORC: kapanmamış belge kalemleri (kalan>0); AVANS: açık kredi (kalan<0). FIFO sıralı."""
        kosul = (
            SatisHareketi.kalan_acik_tutar > 0
            if yon == "BORC"
            else SatisHareketi.kalan_acik_tutar < 0
        )
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
            kalemler = [h for h in kalemler if not (h.belge_no or "").startswith(_KAYNAK_ONEKLERI)
                        or _d(h.satis_tutari) > 0]
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
        """
        for _ in range(5):
            eski = AcikKalemService._guncel_kalan(session, hareket)
            if kesin and istenen > eski + TOLERANS:
                raise AcikKalemDegisti(
                    f"{hareket.belge_no} kaleminin açık tutarı {eski} — ayrılan {istenen} bunu aşıyor. "
                    "Kalem başka bir işlemle kapanmış olabilir; seçimi yenileyin."
                )
            miktar = min(eski, istenen)
            if miktar <= 0:
                return Decimal("0")
            if AcikKalemService._kalan_guncelle(session, hareket, eski, _kurus(eski - miktar)):
                return miktar
        raise AcikKalemDegisti(f"{hareket.belge_no} kalemi eşzamanlı güncelleniyor; tekrar deneyin.")

    @staticmethod
    def _ekle(session, hareket: SatisHareketi, miktar: Decimal) -> None:
        for _ in range(5):
            eski = AcikKalemService._guncel_kalan(session, hareket)
            if AcikKalemService._kalan_guncelle(session, hareket, eski, _kurus(eski + miktar)):
                return
        raise AcikKalemDegisti(f"{hareket.belge_no} kalemi eşzamanlı güncelleniyor; tekrar deneyin.")

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
    ) -> KapatmaSonucu:
        """Tutarı açık kalemlere uygular. Önce ``dagitim`` (hareket_id, tutar), kalan FIFO (fifo=True).

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
                    _kaydet(h, dusulen, "MANUEL")
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
    def avanslari_uygula(session, cari_id: int, *, para_birimi: str | None = None) -> Decimal:
        """Açık krediyi (avans) açık belge kalemlerine FIFO ile uygular; uygulanan toplamı döner."""
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
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.satis_faturasi import SatisFaturasi

        bn = hareket.belge_no or ""
        vade = session.scalar(select(SatisFaturasi.vade_tarihi).where(SatisFaturasi.fatura_no == bn))
        if vade is None:
            vade = session.scalar(select(AlisFaturasi.vade_tarihi).where(AlisFaturasi.fatura_no == bn))
        return vade or hareket.satis_tarihi

    @staticmethod
    def secim_listesi(session, cari_id: int, *, para_birimi: str = "TRY") -> list[dict]:
        """Tahsilat/Ödeme seçim penceresi satırları (açık belge kalemleri, FIFO sıralı)."""
        satirlar = []
        for h in AcikKalemService.acik_kalemler(session, cari_id, yon="BORC", para_birimi=para_birimi):
            ilk = _kurus(h.satis_tutari)
            kalan = _kurus(h.kalan_acik_tutar)
            satirlar.append(
                {
                    "hareket_id": int(h.id),
                    "tarih": h.satis_tarihi,
                    "tur": AcikKalemService._evrak_turu(session, h),
                    "evrak_no": h.belge_no or "",
                    "ilk_tutar": ilk,
                    "kapanan": max(Decimal("0"), ilk - kalan),
                    "kalan": kalan,
                    "vade": AcikKalemService._vade(session, h),
                    "para_birimi": para_anahtari(h),
                }
            )
        return satirlar

    @staticmethod
    def secim_listesi_getir(cari_id: int, *, para_birimi: str = "TRY") -> list[dict]:
        from database.database import get_session

        with get_session() as session:
            return AcikKalemService.secim_listesi(session, int(cari_id), para_birimi=para_birimi)

    @staticmethod
    def acik_kalem_raporu(session, cari_id: int | None = None, *, bugun: date | None = None) -> list[dict]:
        """Açık Borçlar ve Faturalar raporu için sorgulanabilir veri (açık belge + avans kalemleri)."""
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
            if _d(h.kalan_acik_tutar) > 0 and (h.belge_no or "").startswith(_KAYNAK_ONEKLERI) \
                    and _d(h.satis_tutari) <= 0:
                continue
            cari = cariler.get(h.cari_id)
            if cari is None:
                cari = cariler[h.cari_id] = session.get(Cari, h.cari_id)
            vade = AcikKalemService._vade(session, h)
            orijinal = _kurus(h.satis_tutari)
            acik = _kurus(h.kalan_acik_tutar)
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
                    "kapanan": max(Decimal("0"), orijinal - acik) if orijinal > 0 else Decimal("0"),
                    "acik": acik,
                    "para_birimi": para_anahtari(h),
                    "tahsisler": tahsisler,
                    "gecikme_gunu": max(0, (bugun - vade).days) if (vade and acik > 0) else 0,
                }
            )
        return sonuc

    @staticmethod
    def mutabakat(session, cari_id: int) -> dict:
        """cari bakiye = açık borç − açık alacak − avans kontrolü (TRY kalemleri)."""
        from database.cari_bakiye_service import net_bakiye

        bakiye = _kurus(net_bakiye(int(cari_id), session=session)["bakiye"])
        acik_borc = Decimal("0")
        avans = Decimal("0")
        for h in session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id))).all():
            if para_anahtari(h) != "TRY":
                continue
            k = _kurus(h.kalan_acik_tutar)
            if k > 0:
                acik_borc += k
            elif k < 0:
                avans += -k
        acik_net = _kurus(acik_borc - avans)
        return {
            "cari_id": int(cari_id),
            "bakiye": bakiye,
            "acik_borc": _kurus(acik_borc),
            "avans": _kurus(avans),
            "acik_net": acik_net,
            "fark": _kurus(bakiye - acik_net),
            "uyumlu": abs(bakiye - acik_net) <= TOLERANS,
        }
