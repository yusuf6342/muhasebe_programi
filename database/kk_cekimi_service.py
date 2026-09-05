from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.kk_cekimi import KkCekimi


class KkCekimiService:
    @staticmethod
    def listele(arama: str = "") -> list[dict[str, Any]]:
        arama = arama.strip()
        with get_session() as session:
            kayitlar = session.scalars(
                select(KkCekimi)
                .options(selectinload(KkCekimi.musteri), selectinload(KkCekimi.tedarikci))
                .order_by(KkCekimi.tarih.desc(), KkCekimi.id.desc())
            ).all()
            sonuc = []
            for fis in kayitlar:
                if fis.durum == "İPTAL":
                    continue
                kayit = {
                    "fis": fis,
                    "belge_no": fis.belge_no,
                    "tarih": fis.tarih,
                    "tutar": fis.tutar,
                    "banka": fis.banka,
                    "cekim_turu": fis.cekim_turu,
                    "taksit_sayisi": fis.taksit_sayisi,
                    "aciklama": fis.aciklama or "",
                    "musteri_kodu": fis.musteri.cari_kodu if fis.musteri else "",
                    "musteri_unvan": fis.musteri.unvan if fis.musteri else "",
                    "tedarikci_kodu": fis.tedarikci.cari_kodu if fis.tedarikci else "",
                    "tedarikci_unvan": fis.tedarikci.unvan if fis.tedarikci else "",
                }
                if arama:
                    ifade = arama.casefold()
                    metin = " ".join([
                        kayit["belge_no"], kayit["musteri_kodu"], kayit["musteri_unvan"],
                        kayit["tedarikci_kodu"], kayit["tedarikci_unvan"], kayit["banka"],
                        kayit["cekim_turu"], kayit["aciklama"],
                    ]).casefold()
                    if ifade not in metin:
                        continue
                sonuc.append(kayit)
            return sonuc

    @staticmethod
    def getir(belge_no: str) -> KkCekimi | None:
        with get_session() as session:
            return session.scalar(
                select(KkCekimi)
                .where(KkCekimi.belge_no == belge_no)
                .options(selectinload(KkCekimi.musteri), selectinload(KkCekimi.tedarikci))
            )

    @staticmethod
    def kaydet(
        musteri_id: int,
        tedarikci_id: int,
        tarih: date,
        tutar,
        banka: str,
        taksit_sayisi: int | str = 1,
        aciklama: str | None = None,
    ) -> KkCekimi:
        tutar = CariService._tutar(tutar)
        banka = (banka or "").strip()
        try:
            taksit_sayisi = int(str(taksit_sayisi).strip() or "1")
        except ValueError as hata:
            raise ValueError("Taksit sayısı geçerli bir tam sayı olmalıdır.") from hata

        if tutar <= 0:
            raise ValueError("Çekim tutarı pozitif olmalıdır.")
        if musteri_id == tedarikci_id:
            raise ValueError("Müşteri ve tedarikçi aynı olamaz.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek bir tarih olamaz.")
        if not banka:
            raise ValueError("Karın ait olduğu banka adı yazılmalıdır.")
        if taksit_sayisi < 1:
            raise ValueError("Taksit sayısı en az 1 olmalıdır.")
        if taksit_sayisi > 60:
            raise ValueError("Taksit sayısı 60'dan fazla olamaz.")

        cekim_turu = "TEK ÇEKİM" if taksit_sayisi == 1 else "TAKSİTLİ ÇEKİM"

        with get_session() as session:
            musteri = session.get(Cari, musteri_id)
            tedarikci = session.get(Cari, tedarikci_id)
            if musteri is None or tedarikci is None:
                raise ValueError("Müşteri veya tedarikçi bulunamadı.")

            acik_bakiye = sum(
                (
                    h.kalan_acik_tutar
                    for h in session.scalars(
                        select(SatisHareketi).where(
                            SatisHareketi.cari_id == musteri_id,
                            SatisHareketi.kalan_acik_tutar > 0,
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            if tutar > acik_bakiye:
                raise ValueError(
                    "Bakiye veren KK çekim fişi kaydedilemez. "
                    f"Müşteri açık bakiye {acik_bakiye:.2f} TL, girilen tutar {tutar:.2f} TL."
                )

            belge_no = CariService._belge_no(session, "KKC")
            taksit_metin = "Tek çekim" if taksit_sayisi == 1 else f"{taksit_sayisi} taksit"
            detay = f"{banka} / {taksit_metin}"
            tam_aciklama = aciklama.strip() if aciklama else ""
            if tam_aciklama:
                tam_aciklama = f"{tam_aciklama} ({detay})"
            else:
                tam_aciklama = detay

            # Müşteri ALACAK, tedarikçi BORÇ — finans hesabına işlem yazılmaz
            CariService._aciklara_uygula(session, musteri_id, tutar)
            session.add(SatisHareketi(
                cari_id=tedarikci_id, satis_tarihi=tarih, belge_no=belge_no,
                satis_tutari=tutar, kalan_acik_tutar=tutar,
            ))
            session.add(CariIslem(
                cari_id=musteri_id, tarih=tarih, islem_turu="KK Çekimi", belge_no=belge_no,
                aciklama=f"Alacak → {tedarikci.unvan} | {tam_aciklama}",
                borc=Decimal("0"), alacak=tutar,
                hesap_adi=None, karsi_cari_id=tedarikci_id,
            ))
            session.add(CariIslem(
                cari_id=tedarikci_id, tarih=tarih, islem_turu="KK Çekimi", belge_no=belge_no,
                aciklama=f"Borç ← {musteri.unvan} | {tam_aciklama}",
                borc=tutar, alacak=Decimal("0"),
                hesap_adi=None, karsi_cari_id=musteri_id,
            ))

            fis = KkCekimi(
                belge_no=belge_no,
                tarih=tarih,
                musteri_id=musteri_id,
                tedarikci_id=tedarikci_id,
                tutar=tutar,
                banka=banka,
                cekim_turu=cekim_turu,
                taksit_sayisi=taksit_sayisi,
                aciklama=aciklama.strip() if aciklama else None,
                durum="AÇIK",
            )
            session.add(fis)
            session.flush()
            return fis

    @staticmethod
    def iptal_et(belge_no: str) -> None:
        belge_no = (belge_no or "").strip()
        if not belge_no.startswith("KKC-"):
            raise ValueError("Geçersiz KK çekim belge numarası.")
        with get_session() as session:
            fis = session.scalar(select(KkCekimi).where(KkCekimi.belge_no == belge_no))
            if fis is None:
                raise ValueError("KK çekim fişi bulunamadı.")
            if fis.durum == "İPTAL":
                raise ValueError("Fiş zaten iptal edilmiş.")

            islemler = session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "KK Çekimi",
                )
            ).all()
            musteri_islem = next((i for i in islemler if i.alacak > 0), None)
            tedarikci_islem = next((i for i in islemler if i.borc > 0), None)
            if musteri_islem is None or tedarikci_islem is None:
                raise ValueError("KK çekim fişi eksik cari kayıtlı; iptal edilemez.")

            tutar = musteri_islem.alacak
            tedarikci_hareket = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == tedarikci_islem.cari_id,
                )
            )
            if tedarikci_hareket is not None:
                if tedarikci_hareket.kalan_acik_tutar < tedarikci_hareket.satis_tutari:
                    raise ValueError(
                        "Tedarikçi bakiyesinde bu çekimin bir kısmı kapanmış; iptal edilemez."
                    )
                session.delete(tedarikci_hareket)

            CariService._aciklara_geri_al(session, musteri_islem.cari_id, tutar, belge_no)
            for islem in islemler:
                session.delete(islem)

            # Eski kayıtlarda yanlışlıkla düşmüş finans hareketi varsa temizle
            from database.models.finans import FinansHareketi
            for hareket in session.scalars(
                select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
            ).all():
                session.delete(hareket)

            fis.durum = "İPTAL"
            session.flush()
