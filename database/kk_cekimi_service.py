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
                    "belge_no": fis.belge_no,
                    "tarih": fis.tarih,
                    "tutar": fis.tutar,
                    "banka": fis.banka,
                    "cekim_turu": fis.cekim_turu,
                    "taksit_sayisi": fis.taksit_sayisi,
                    "aciklama": fis.aciklama or "",
                    "musteri_id": fis.musteri_id,
                    "tedarikci_id": fis.tedarikci_id,
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
    def getir(belge_no: str) -> dict[str, Any]:
        belge_no = (belge_no or "").strip()
        with get_session() as session:
            fis = session.scalar(
                select(KkCekimi)
                .where(KkCekimi.belge_no == belge_no)
                .options(selectinload(KkCekimi.musteri), selectinload(KkCekimi.tedarikci))
            )
            if not fis:
                raise ValueError("KK çekim fişi bulunamadı.")
            if fis.durum == "İPTAL":
                raise ValueError("İptal edilmiş fiş güncellenemez.")
            musteri = fis.musteri
            tedarikci = fis.tedarikci
            return {
                "belge_no": fis.belge_no,
                "tarih": fis.tarih,
                "tutar": Decimal(str(fis.tutar)),
                "banka": fis.banka,
                "cekim_turu": fis.cekim_turu,
                "taksit_sayisi": int(fis.taksit_sayisi or 1),
                "aciklama": fis.aciklama or "",
                "musteri_id": fis.musteri_id,
                "tedarikci_id": fis.tedarikci_id,
                "musteri_etiket": (
                    f"{musteri.cari_kodu} - {musteri.unvan}" if musteri else ""
                ),
                "tedarikci_etiket": (
                    f"{tedarikci.cari_kodu} - {tedarikci.unvan}" if tedarikci else ""
                ),
                "durum": fis.durum,
            }

    @staticmethod
    def _belge_no(session) -> str:
        """KKC belge no — iptal edilmiş fişler de sayılır (unique çakışmasın)."""
        yil = date.today().year
        like = f"KKC-{yil}-%"
        mevcut = set(
            session.scalars(select(CariIslem.belge_no).where(CariIslem.belge_no.like(like))).all()
        )
        mevcut.update(
            session.scalars(select(KkCekimi.belge_no).where(KkCekimi.belge_no.like(like))).all()
        )
        sira = 1
        for no in mevcut:
            try:
                sira = max(sira, int(str(no).rsplit("-", 1)[-1]) + 1)
            except ValueError:
                pass
        return f"KKC-{yil}-{sira:04d}"

    @staticmethod
    def _musteri_kredi_satiri(session, musteri_id: int, belge_no: str):
        """Müşteri tarafındaki KKC alacak (negatif kalan) SatisHareketi satırı."""
        return session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.belge_no == belge_no,
                SatisHareketi.cari_id == int(musteri_id),
            )
        )

    @staticmethod
    def _etkileri_geri_al(session, belge_no: str) -> None:
        """Açık fişin cari/satış etkilerini geri alır; KkCekimi kaydını siler."""
        fis = session.scalar(select(KkCekimi).where(KkCekimi.belge_no == belge_no))
        if not fis:
            raise ValueError("KK çekim fişi bulunamadı.")
        if fis.durum == "İPTAL":
            raise ValueError("İptal edilmiş fiş güncellenemez.")

        islemler = list(
            session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "KK Çekimi",
                )
            ).all()
        )
        musteri_islem = next((i for i in islemler if i.alacak > 0), None)
        tedarikci_islem = next((i for i in islemler if i.borc > 0), None)
        if musteri_islem is None or tedarikci_islem is None:
            raise ValueError("KK çekim fişi eksik cari kayıtlı; işlem geri alınamaz.")

        tutar = Decimal(str(musteri_islem.alacak))
        tedarikci_hareket = session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.belge_no == belge_no,
                SatisHareketi.cari_id == tedarikci_islem.cari_id,
            )
        )
        if tedarikci_hareket is not None:
            if tedarikci_hareket.kalan_acik_tutar < tedarikci_hareket.satis_tutari:
                raise ValueError(
                    "Tedarikçi bakiyesinde bu çekimin bir kısmı kapanmış; güncellenemez/iptal edilemez."
                )
            session.delete(tedarikci_hareket)

        musteri_kredi = KkCekimiService._musteri_kredi_satiri(
            session, musteri_islem.cari_id, belge_no
        )
        residual = Decimal("0")
        if musteri_kredi is not None:
            kalan = Decimal(str(musteri_kredi.kalan_acik_tutar or 0))
            if kalan < 0:
                residual = -kalan
            session.delete(musteri_kredi)

        uygulanan = tutar - residual
        if uygulanan > 0:
            CariService._aciklara_geri_al(session, musteri_islem.cari_id, uygulanan, belge_no)

        for islem in islemler:
            session.delete(islem)

        from database.models.finans import FinansHareketi

        for hareket in session.scalars(
            select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
        ).all():
            session.delete(hareket)

        session.delete(fis)
        session.flush()

    @staticmethod
    def kaydet(
        musteri_id: int,
        tedarikci_id: int,
        tarih: date,
        tutar,
        banka: str,
        taksit_sayisi: int | str = 1,
        aciklama: str | None = None,
        belge_no: str | None = None,
    ) -> dict[str, Any]:
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
            raise ValueError("Kartın ait olduğu banka adı yazılmalıdır.")
        if taksit_sayisi < 1:
            raise ValueError("Taksit sayısı en az 1 olmalıdır.")
        if taksit_sayisi > 60:
            raise ValueError("Taksit sayısı 60'dan fazla olamaz.")

        cekim_turu = "TEK ÇEKİM" if taksit_sayisi == 1 else "TAKSİTLİ ÇEKİM"
        guncelleme = bool((belge_no or "").strip())

        with get_session() as session:
            if guncelleme:
                belge_no = belge_no.strip()
                KkCekimiService._etkileri_geri_al(session, belge_no)
            else:
                belge_no = KkCekimiService._belge_no(session)

            musteri = session.get(Cari, musteri_id)
            tedarikci = session.get(Cari, tedarikci_id)
            if musteri is None or tedarikci is None:
                raise ValueError("Müşteri veya tedarikçi bulunamadı.")

            taksit_metin = "Tek çekim" if taksit_sayisi == 1 else f"{taksit_sayisi} taksit"
            detay = f"{banka} / {taksit_metin}"
            tam_aciklama = aciklama.strip() if aciklama else ""
            if tam_aciklama:
                tam_aciklama = f"{tam_aciklama} ({detay})"
            else:
                tam_aciklama = detay

            # Açık borçlara FIFO; kalan müşteri alacağı SatisHareketi'nde (negatif) tutulur → listede bakiye görünür.
            kalan = CariService._aciklara_uygula(session, musteri_id, tutar)
            if kalan > 0:
                session.add(
                    SatisHareketi(
                        cari_id=musteri_id,
                        satis_tarihi=tarih,
                        belge_no=belge_no,
                        satis_tutari=Decimal("0"),
                        kalan_acik_tutar=-kalan,
                    )
                )

            session.add(
                SatisHareketi(
                    cari_id=tedarikci_id,
                    satis_tarihi=tarih,
                    belge_no=belge_no,
                    satis_tutari=tutar,
                    kalan_acik_tutar=tutar,
                )
            )
            session.add(
                CariIslem(
                    cari_id=musteri_id,
                    tarih=tarih,
                    islem_turu="KK Çekimi",
                    belge_no=belge_no,
                    aciklama=f"Alacak → {tedarikci.unvan} | {tam_aciklama}",
                    borc=Decimal("0"),
                    alacak=tutar,
                    hesap_adi=None,
                    karsi_cari_id=tedarikci_id,
                )
            )
            session.add(
                CariIslem(
                    cari_id=tedarikci_id,
                    tarih=tarih,
                    islem_turu="KK Çekimi",
                    belge_no=belge_no,
                    aciklama=f"Borç ← {musteri.unvan} | {tam_aciklama}",
                    borc=tutar,
                    alacak=Decimal("0"),
                    hesap_adi=None,
                    karsi_cari_id=musteri_id,
                )
            )

            session.add(
                KkCekimi(
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
            )
            session.flush()
            return {
                "belge_no": belge_no,
                "tutar": tutar,
                "taksit_sayisi": taksit_sayisi,
                "cekim_turu": cekim_turu,
                "kalan_alacak": kalan,
            }

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

            # Soft-iptal: etkileri geri al, fişi İPTAL olarak yeniden yaz (belge no korunur)
            musteri_id = fis.musteri_id
            tedarikci_id = fis.tedarikci_id
            tarih = fis.tarih
            tutar = Decimal(str(fis.tutar))
            banka = fis.banka
            cekim_turu = fis.cekim_turu
            taksit_sayisi = fis.taksit_sayisi
            aciklama = fis.aciklama

            KkCekimiService._etkileri_geri_al(session, belge_no)
            session.add(
                KkCekimi(
                    belge_no=belge_no,
                    tarih=tarih,
                    musteri_id=musteri_id,
                    tedarikci_id=tedarikci_id,
                    tutar=tutar,
                    banka=banka,
                    cekim_turu=cekim_turu,
                    taksit_sayisi=taksit_sayisi,
                    aciklama=aciklama,
                    durum="İPTAL",
                )
            )
            session.flush()

    @staticmethod
    def eksik_alacaklari_onar() -> int:
        """
        Eski AÇIK fişlerde müşteri alacak SatisHareketi yoksa ekler.
        (Açık borçlara uygulanmış kısım zaten düşülmüş; kalan alacak = tam tutar varsayımı
        yalnızca müşteri satırı yokken ve açık borç kalmamışsa güvenli değil —
        bu yüzden: mevcut açık borçlara dokunmadan, fiş tutarının tamamını alacak satırı
        olarak yazmayız; bunun yerine fiş tutarı − o anda uygulanmış gibi davranırız.

        Pratik: müşteri KKC satırı yoksa, fiş tutarının tamamını negatif kalan olarak ekle.
        (Önceki sürüm fazla tutarı hiç yazmıyordu; açık borçlar zaten FIFO ile kapanmışsa
        tamamı alacak kalmalı.)
        """
        adet = 0
        with get_session() as session:
            fisler = session.scalars(
                select(KkCekimi)
                .where(KkCekimi.durum == "AÇIK")
                .order_by(KkCekimi.tarih, KkCekimi.id)
            ).all()
            for fis in fisler:
                mevcut = KkCekimiService._musteri_kredi_satiri(
                    session, fis.musteri_id, fis.belge_no
                )
                if mevcut is not None:
                    continue
                tutar = Decimal(str(fis.tutar))
                # Fiş kaydı sırasında FIFO uygulanmış olabilir; kalan alacak bilinmiyor.
                # Müşterinin hâlâ pozitif açık borcu varsa bu fiş için alacak satırı ekleme
                # (borç zaten düşülmüş demektir, fazla yok veya belirsiz).
                acik = sum(
                    (
                        Decimal(str(h.kalan_acik_tutar))
                        for h in session.scalars(
                            select(SatisHareketi).where(
                                SatisHareketi.cari_id == fis.musteri_id,
                                SatisHareketi.kalan_acik_tutar > 0,
                            )
                        ).all()
                    ),
                    Decimal("0"),
                )
                # Alacak fişlerinin toplamı (bu müşteri, AÇIK, henüz satırı olmayanlar dahil)
                # En güvenlisi: müşteri açık borç 0 ise tüm eksik KKC tutarlarını alacak yaz.
                if acik > 0:
                    continue
                session.add(
                    SatisHareketi(
                        cari_id=fis.musteri_id,
                        satis_tarihi=fis.tarih,
                        belge_no=fis.belge_no,
                        satis_tutari=Decimal("0"),
                        kalan_acik_tutar=-tutar,
                    )
                )
                adet += 1
            session.flush()
        return adet
