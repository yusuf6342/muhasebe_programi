"""Gerçekleşen kur farkı: dövizli (döviz sabit) borç/alacak kapatılırken kaynak kur ↔ ödeme kuru farkı.

Her kapatma için bir ``KurFarkiKaydi`` yazılır (kaynak belge, kapatma, döviz tutarı, iki kur, TL karşılıkları
ve fark). Fiş üretimi ``muhasebe_hook("kur_farki_fisi")`` üzerinden firmanın otomatik/sonradan ayarına uyar.

- Kur veya kaynak bilgisi eksikse fark hesaplanmaz: kayıt ``INCELEME`` olur, evrak "İnceleme gerekiyor"a düşer.
- Aynı kapatma tekrar işlenirse (değer değişmediyse) yeni kayıt/fiş oluşmaz; değiştiyse eski kayıt iptal
  edilip (fişi ters kayıtla kapanır) yenisi yazılır.
- Kaynak belge veya kapatma iptal edilince kayıt iptal edilir, fişi ters kayıtla kapanır.
- Geçmiş kapatmalar kendiliğinden işlenmez; yalnız bu servisi çağıran akışlar kayıt üretir.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from database.models.genel_muhasebe import (
    KUR_FARKI_HESAPLANDI,
    KUR_FARKI_INCELEME,
    KUR_FARKI_IPTAL,
    KurFarkiKaydi,
)

KURUS = Decimal("0.01")
TOLERANS = Decimal("0.01")
YON_SATIS, YON_ALIS = "SATIS", "ALIS"
KAPATMA_SATIS_FATURA_TAHSILATI = "SATIS_FATURA_TAHSILATI"
# Dövizli alış iadesi: kapatma = iade satırının kaynak alışa ait ilk dağılımı (kaynaksız satırda satırın kendisi)
KAPATMA_ALIS_IADE = "ALIS_IADE"
KAPATMA_ALIS_IADE_KAYNAKSIZ = "ALIS_IADE_KAYNAKSIZ"
ALIS_IADE_KAPATMALARI = (KAPATMA_ALIS_IADE, KAPATMA_ALIS_IADE_KAYNAKSIZ)


def _d(deger) -> Decimal | None:
    if deger is None or deger == "":
        return None
    try:
        return Decimal(str(deger))
    except Exception:
        return None


def _q(deger: Decimal) -> Decimal:
    return deger.quantize(KURUS, rounding=ROUND_HALF_UP)


def _kullanici() -> str | None:
    from database.session_manager import oturum

    return (oturum.kullanici_adi or oturum.ad_soyad or None) if oturum else None


class KurFarkiService:
    @staticmethod
    def etkin_kayit(session, kapatma_turu: str, kapatma_id: int) -> KurFarkiKaydi | None:
        return session.scalar(select(KurFarkiKaydi).where(
            KurFarkiKaydi.kapatma_turu == kapatma_turu, KurFarkiKaydi.kapatma_id == int(kapatma_id),
            KurFarkiKaydi.durum != KUR_FARKI_IPTAL))

    @staticmethod
    def kaynak_kayitlari(session, kaynak_evrak: str, kaynak_id: int, *, etkin: bool = True) -> list[KurFarkiKaydi]:
        q = select(KurFarkiKaydi).where(KurFarkiKaydi.kaynak_evrak == kaynak_evrak,
                                        KurFarkiKaydi.kaynak_id == int(kaynak_id))
        if etkin:
            q = q.where(KurFarkiKaydi.durum != KUR_FARKI_IPTAL)
        return list(session.scalars(q.order_by(KurFarkiKaydi.id)).all())

    @staticmethod
    def hesapla(*, yon: str, doviz_tutar, kaynak_kur, odeme_kuru) -> dict:
        """Kaynak/ödeme TL karşılığı ve işaretli fark (+ gelir, − gider)."""
        d, kk, ok = _d(doviz_tutar), _d(kaynak_kur), _d(odeme_kuru)
        kaynak_tl, odeme_tl = _q(d * kk), _q(d * ok)
        fark = odeme_tl - kaynak_tl if yon == YON_SATIS else kaynak_tl - odeme_tl
        return {"kaynak_tl": kaynak_tl, "odeme_tl": odeme_tl, "kur_farki": fark}

    @staticmethod
    def kaydet(
        session,
        *,
        yon: str,
        cari_id: int | None,
        kaynak_evrak: str,
        kaynak_id: int,
        kaynak_belge_no: str | None,
        kapatma_turu: str,
        kapatma_id: int,
        kapatma_belge_no: str | None,
        tarih: date,
        para_birimi: str,
        doviz_tutar,
        kaynak_kur,
        odeme_kuru,
        doviz_borc=None,
        eksik_neden: str | None = None,
    ) -> KurFarkiKaydi | None:
        """Kapatmanın kur farkını kaydeder ve muhasebeleştirme olayını bildirir (TRY ise None)."""
        from database.muhasebe_entegrasyon import muhasebe_hook
        from database.muhasebe_service import MuhasebeService

        if yon not in (YON_SATIS, YON_ALIS):
            raise ValueError(f"Geçersiz kur farkı yönü: {yon}")
        pb = (para_birimi or "TRY").upper()
        if pb == "TRY":
            return None
        d, kk, ok = _d(doviz_tutar), _d(kaynak_kur), _d(odeme_kuru)
        neden = eksik_neden
        if neden is None and (kk is None or kk <= 0):
            neden = f"{kaynak_belge_no or kaynak_evrak}: kaynak belge kuru yok"
        if neden is None and (ok is None or ok <= 0):
            neden = f"{tarih:%d.%m.%Y} tarihli {pb} ödeme kuru bulunamadı (Döviz Kurları); kur tahmin edilmedi"
        if neden is None and (d is None or d <= 0):
            neden = "kapatılan döviz tutarı belirlenemedi"
        if neden is None and doviz_borc is not None:
            onceki = sum((_d(k.doviz_tutar) or Decimal("0") for k in KurFarkiService.kaynak_kayitlari(
                session, kaynak_evrak, kaynak_id) if not (k.kapatma_turu == kapatma_turu
                                                          and k.kapatma_id == int(kapatma_id))), Decimal("0"))
            if onceki + d > _d(doviz_borc) + TOLERANS:
                neden = (f"kapatılan döviz toplamı ({_q(onceki + d)} {pb}) belgenin döviz tutarını "
                         f"({_q(_d(doviz_borc))} {pb}) aşıyor")
        if neden:
            durum, degerler = KUR_FARKI_INCELEME, {"kaynak_tl": Decimal("0"), "odeme_tl": Decimal("0"),
                                                    "kur_farki": Decimal("0")}
        else:
            durum, degerler = KUR_FARKI_HESAPLANDI, KurFarkiService.hesapla(
                yon=yon, doviz_tutar=d, kaynak_kur=kk, odeme_kuru=ok)

        mevcut = KurFarkiService.etkin_kayit(session, kapatma_turu, kapatma_id)
        if mevcut is not None:
            ayni = (mevcut.durum == durum and mevcut.tarih == tarih and mevcut.para_birimi == pb
                    and _d(mevcut.doviz_tutar) == (_q(d) if d is not None else Decimal("0"))
                    and _d(mevcut.kaynak_kur) == kk and _d(mevcut.odeme_kuru) == ok
                    and _d(mevcut.kur_farki) == degerler["kur_farki"] and (mevcut.aciklama or None) == neden)
            if ayni:
                return mevcut
            KurFarkiService.iptal(session, mevcut, "Kapatma değişti; kur farkı yeniden hesaplandı")

        kayit = KurFarkiKaydi(
            firma_id=MuhasebeService.yerel_firma_id(session), yon=yon, cari_id=cari_id,
            kaynak_evrak=kaynak_evrak, kaynak_id=int(kaynak_id), kaynak_belge_no=kaynak_belge_no,
            kapatma_turu=kapatma_turu, kapatma_id=int(kapatma_id), kapatma_belge_no=kapatma_belge_no,
            tarih=tarih, para_birimi=pb, doviz_tutar=_q(d) if d is not None else Decimal("0"),
            kaynak_kur=kk, odeme_kuru=ok, durum=durum, aciklama=neden, olusturma=datetime.now(),
            olusturan=_kullanici(), **degerler,
        )
        session.add(kayit)
        session.flush()
        MuhasebeService._gecmis(
            session, kayit_turu="kur_farki", kayit_id=int(kayit.id), islem="hesapla",
            detay=(f"{kaynak_evrak}#{kaynak_id} {kaynak_belge_no or ''} / {kapatma_turu}#{kapatma_id}: "
                   f"{kayit.doviz_tutar} {pb} kaynak kur {kk} ödeme kuru {ok} → fark {kayit.kur_farki}"
                   + (f" (İNCELEME: {neden})" if neden else "")))
        muhasebe_hook("kur_farki_fisi", int(kayit.id), session=session)
        return kayit

    @staticmethod
    def iptal(session, kayit: KurFarkiKaydi, neden: str) -> None:
        from database.muhasebe_entegrasyon import muhasebe_hook

        if kayit is None or kayit.durum == KUR_FARKI_IPTAL:
            return
        kayit.durum = KUR_FARKI_IPTAL
        kayit.iptal_zamani = datetime.now()
        kayit.iptal_nedeni = (neden or "İptal")[:300]
        session.flush()
        muhasebe_hook("kur_farki_iptal", int(kayit.id), neden or "Kur farkı iptal", session=session)

    @staticmethod
    def kapatma_iptal(session, kapatma_turu: str, kapatma_id: int, neden: str) -> None:
        KurFarkiService.iptal(session, KurFarkiService.etkin_kayit(session, kapatma_turu, kapatma_id), neden)

    @staticmethod
    def kapatma_belgesi_iptal(session, kapatma_turleri, kapatma_belge_no: str, neden: str) -> int:
        """Kapatma belgesinin (ör. alış iadesi) tüm etkin kayıtlarını iptal eder; fişleri ters kayıtla kapanır."""
        kayitlar = list(session.scalars(select(KurFarkiKaydi).where(
            KurFarkiKaydi.kapatma_turu.in_(tuple(kapatma_turleri)),
            KurFarkiKaydi.kapatma_belge_no == kapatma_belge_no,
            KurFarkiKaydi.durum != KUR_FARKI_IPTAL)).all())
        for k in kayitlar:
            KurFarkiService.iptal(session, k, neden)
        return len(kayitlar)

    @staticmethod
    def kaynak_iptal(session, kaynak_evrak: str, kaynak_id: int, neden: str) -> int:
        kayitlar = KurFarkiService.kaynak_kayitlari(session, kaynak_evrak, kaynak_id)
        for k in kayitlar:
            KurFarkiService.iptal(session, k, neden)
        return len(kayitlar)

    # ---- Satış faturası (döviz sabit) fatura içi tahsilatı ----
    @staticmethod
    def satis_fatura_tahsilati(session, fatura, tahsilat, odeme_kuru) -> KurFarkiKaydi | None:
        """Döviz sabit satış faturasının TL tahsilatı: kapatılan döviz = tahsilat TL ÷ ödeme kuru.

        Kaynak döviz borcu = TL net toplam ÷ fatura kuru (faturanın kendi kuruyla). Kur yoksa incelemeye düşer.
        """
        pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
        if pb == "TRY" or (getattr(fatura, "borc_esasi", None) or "TL_SABIT") != "DOVIZ_SABIT":
            return None
        tutar = _d(tahsilat.tutar) or Decimal("0")
        if tutar <= 0:
            return None
        kk, ok = _d(fatura.kur), _d(odeme_kuru)
        net = _d(getattr(fatura, "tl_genel_toplam", None)) or Decimal("0")
        doviz_borc = _q(net / kk) if kk and kk > 0 and net > 0 else None
        doviz = _q(tutar / ok) if ok and ok > 0 else None
        eksik = None if doviz_borc is not None or not (kk and kk > 0) else "faturanın TL net toplamı yok"
        return KurFarkiService.kaydet(
            session, yon=YON_SATIS, cari_id=fatura.cari_id, kaynak_evrak="satis_faturasi", kaynak_id=int(fatura.id),
            kaynak_belge_no=fatura.fatura_no, kapatma_turu=KAPATMA_SATIS_FATURA_TAHSILATI,
            kapatma_id=int(tahsilat.id), kapatma_belge_no=f"{fatura.fatura_no}/T{int(tahsilat.id)}",
            tarih=tahsilat.tahsilat_tarihi, para_birimi=pb, doviz_tutar=doviz, kaynak_kur=kk, odeme_kuru=ok,
            doviz_borc=doviz_borc, eksik_neden=eksik,
        )


__all__ = ["ALIS_IADE_KAPATMALARI", "KAPATMA_ALIS_IADE", "KAPATMA_ALIS_IADE_KAYNAKSIZ",
           "KAPATMA_SATIS_FATURA_TAHSILATI", "KurFarkiService", "YON_ALIS", "YON_SATIS"]
