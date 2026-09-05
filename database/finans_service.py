from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import FinansHareketi, FinansHesabi


class FinansService:
    @staticmethod
    def varsayilanlari_hazirla():
        varsayilanlar = (("ANA KASA", "KASA"), ("BANKA HESABI", "BANKA"), ("KREDİ KARTI POS", "KREDİ KARTI"))
        with get_session() as session:
            mevcut = set(session.scalars(select(FinansHesabi.hesap_adi)).all())
            for ad, tur in varsayilanlar:
                if ad not in mevcut: session.add(FinansHesabi(hesap_adi=ad, hesap_turu=tur))

    @staticmethod
    def hesaplar():
        with get_session() as session:
            return list(session.scalars(select(FinansHesabi).where(FinansHesabi.aktif.is_(True)).order_by(FinansHesabi.hesap_adi)).all())

    @staticmethod
    def hareketler():
        with get_session() as session:
            return list(session.scalars(select(FinansHareketi).options(
                selectinload(FinansHareketi.hesap)
            ).order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())).all())

    @staticmethod
    def fatura_tahsilatini_geri_al(session, belge_no):
        session.execute(delete(FinansHareketi).where(FinansHareketi.belge_no == belge_no, FinansHareketi.hareket_turu == "FATURA TAHSİLATI"))

    @staticmethod
    def fatura_tahsilati(session, belge_no, tarih, tutar, odeme_sekli, hesap_adi):
        FinansService.hareket_ekle(session, belge_no, tarih, tutar, "FATURA TAHSİLATI", hesap_adi, odeme_sekli)

    @staticmethod
    def fatura_odemesini_geri_al(session, belge_no):
        session.execute(delete(FinansHareketi).where(
            FinansHareketi.belge_no == belge_no,
            FinansHareketi.hareket_turu.in_(("FATURA ÖDEMESİ", "CARİ ÖDEME")),
        ))

    @staticmethod
    def fatura_odemesi(session, belge_no, tarih, tutar, odeme_sekli, hesap_adi):
        FinansService.hareket_ekle(session, belge_no, tarih, tutar, "FATURA ÖDEMESİ", hesap_adi, odeme_sekli)

    @staticmethod
    def hareket_ekle(session, belge_no, tarih, tutar, hareket_turu, hesap_adi, aciklama=None):
        tutar = Decimal(tutar)
        if tutar <= 0:
            return
        if not hesap_adi:
            raise ValueError("Kasa/banka hesabı seçin.")
        hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi))
        if not hesap:
            raise ValueError("Geçerli bir kasa/banka hesabı seçin.")
        session.add(FinansHareketi(
            hesap_id=hesap.id, tarih=tarih, hareket_turu=hareket_turu,
            belge_no=belge_no, tutar=tutar, aciklama=aciklama,
        ))
