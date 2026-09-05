from datetime import date
from decimal import Decimal, InvalidOperation
import unicodedata
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi


class CariService:
    @staticmethod
    def _grup_anahtari(ad: str) -> str:
        normal = unicodedata.normalize("NFKD", ad.strip())
        return "".join(karakter for karakter in normal if not unicodedata.combining(karakter)).casefold()

    @staticmethod
    def gruplari_listele() -> list[str]:
        from database.models.cari import MusteriGrubu

        with get_session() as session:
            return list(session.scalars(select(MusteriGrubu.ad).order_by(MusteriGrubu.ad)).all())

    @staticmethod
    def grup_ekle(ad: str) -> str:
        from database.models.cari import MusteriGrubu

        ad = ad.strip()
        if not ad:
            raise ValueError("Müşteri grup adı boş olamaz.")
        with get_session() as session:
            mevcut = next(
                (grup for grup in session.scalars(select(MusteriGrubu)) if CariService._grup_anahtari(grup.ad) == CariService._grup_anahtari(ad)),
                None,
            )
            if mevcut:
                raise ValueError("Bu müşteri grubu zaten mevcut.")
            session.add(MusteriGrubu(ad=ad))
            session.flush()
            return ad

    @staticmethod
    def _arama_kontrol(arama: str) -> str:
        arama = arama.strip()
        if arama and len(arama) < 3:
            raise ValueError("Arama için en az 3 karakter girin.")
        return arama

    @staticmethod
    def listele(arama: str = "", cari_turu: str | None = None) -> list[dict[str, Any]]:
        arama = CariService._arama_kontrol(arama)
        with get_session() as session:
            statement = select(Cari).order_by(Cari.cari_kodu)
            if cari_turu:
                statement = statement.where(Cari.cari_turu == cari_turu)
            if arama:
                ifade = f"%{arama}%"
                statement = statement.where(
                    or_(
                        Cari.cari_kodu.ilike(ifade),
                        Cari.unvan.ilike(ifade),
                        Cari.telefon.ilike(ifade),
                    )
                )
            cariler = session.scalars(statement).all()
            return [CariService._ozet(cari) for cari in cariler]

    @staticmethod
    def getir(cari_id: int) -> Cari | None:
        with get_session() as session:
            return session.get(Cari, cari_id)

    @staticmethod
    def detay(cari_id: int) -> dict[str, Any] | None:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                return None
            return {
                "cari": cari,
                "hareketler": CariService._defter(session, cari_id),
                "acik_hareketler": sorted(
                    [h for h in cari.satis_hareketleri if h.kalan_acik_tutar > 0],
                    key=lambda item: item.satis_tarihi,
                ),
            }

    @staticmethod
    def _defter(session, cari_id: int) -> list[dict[str, Any]]:
        kayitlar: list[dict[str, Any]] = []
        for h in session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cari_id)):
            if h.belge_no.startswith(("ODM-", "VRM-", "KKC-", "THS-")):
                continue
            if h.belge_no.startswith("AFAT-"):
                tur = "Alış"
            elif h.belge_no.startswith(("AIAD-", "IAD-")):
                tur = "Alış İadesi" if h.belge_no.startswith("AIAD-") else "Satış"
            else:
                tur = "Satış"
            kayitlar.append({
                "tarih": h.satis_tarihi,
                "tur": tur,
                "belge_no": h.belge_no,
                "aciklama": "",
                "borc": h.satis_tutari,
                "alacak": Decimal("0"),
                "kalan": h.kalan_acik_tutar,
            })
        for islem in session.scalars(select(CariIslem).where(CariIslem.cari_id == cari_id)):
            aciklama = islem.aciklama or ""
            if islem.karsi_cari_id:
                karsi = session.get(Cari, islem.karsi_cari_id)
                if karsi is not None:
                    if islem.alacak > 0:
                        ek = f"Karşı cariye borç: {karsi.cari_kodu}"
                    elif islem.borc > 0:
                        ek = f"Karşı cariden alacak: {karsi.cari_kodu}"
                    else:
                        ek = f"Karşı: {karsi.cari_kodu}"
                    if ek not in aciklama:
                        aciklama = f"{aciklama} | {ek}".strip(" |")
            kayitlar.append({
                "tarih": islem.tarih,
                "tur": islem.islem_turu,
                "belge_no": islem.belge_no,
                "aciklama": aciklama,
                "borc": islem.borc,
                "alacak": islem.alacak,
                "kalan": None,
            })
        kayitlar.sort(key=lambda item: (item["tarih"], item["belge_no"]), reverse=True)
        return kayitlar

    @staticmethod
    def _belge_no(session, on_ek: str) -> str:
        yil = date.today().year
        like = f"{on_ek}-{yil}-%"
        mevcut = session.scalars(select(CariIslem.belge_no).where(CariIslem.belge_no.like(like))).all()
        sira = 1
        for no in mevcut:
            try:
                sira = max(sira, int(no.rsplit("-", 1)[-1]) + 1)
            except ValueError:
                pass
        return f"{on_ek}-{yil}-{sira:04d}"

    @staticmethod
    def _aciklara_uygula(session, cari_id: int, tutar: Decimal) -> Decimal:
        """Açık satış hareketlerine FIFO tahsilat uygular; faturaları senkronlar. Kalan tutarı döner."""
        kalan = tutar
        aciklar = session.scalars(
            select(SatisHareketi)
            .where(SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar > 0)
            .order_by(SatisHareketi.satis_tarihi, SatisHareketi.id)
        ).all()
        for hareket in aciklar:
            if kalan <= 0:
                break
            dusulecek = min(hareket.kalan_acik_tutar, kalan)
            hareket.kalan_acik_tutar -= dusulecek
            kalan -= dusulecek
            fatura = session.scalar(select(SatisFaturasi).where(SatisFaturasi.fatura_no == hareket.belge_no))
            if fatura and fatura.durum != "İPTAL":
                fatura.tahsilat_tutari = (fatura.tahsilat_tutari or Decimal("0")) + dusulecek
                from database.satis_faturasi_service import SatisFaturasiService
                toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
                fatura.durum = "KAPALI" if fatura.tahsilat_tutari >= toplam else "AÇIK"
            else:
                from database.models.alis_faturasi import AlisFaturasi
                alis = session.scalar(select(AlisFaturasi).where(AlisFaturasi.fatura_no == hareket.belge_no))
                if alis and alis.durum != "İPTAL":
                    alis.odeme_tutari = (alis.odeme_tutari or Decimal("0")) + dusulecek
                    from database.alis_faturasi_service import AlisFaturasiService
                    toplam = AlisFaturasiService.toplam(alis.satirlar)["genel_toplam"]
                    alis.durum = "KAPALI" if alis.odeme_tutari >= toplam else "AÇIK"
        return kalan

    @staticmethod
    def tahsilat_yap(cari_id: int, tarih: date, tutar, odeme_sekli: str, hesap_adi: str, aciklama: str | None = None) -> CariIslem:
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Tahsilat tutarı pozitif olmalıdır.")
        if tarih > date.today():
            raise ValueError("Tahsilat tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            belge_no = CariService._belge_no(session, "THS")
            CariService._aciklara_uygula(session, cari_id, tutar)
            islem = CariIslem(
                cari_id=cari_id, tarih=tarih, islem_turu="Tahsilat", belge_no=belge_no,
                aciklama=aciklama or odeme_sekli, borc=Decimal("0"), alacak=tutar, hesap_adi=hesap_adi,
            )
            session.add(islem)
            FinansService.hareket_ekle(session, belge_no, tarih, tutar, "CARİ TAHSİLAT", hesap_adi, odeme_sekli)
            session.flush()
            return islem

    @staticmethod
    def odeme_yap(cari_id: int, tarih: date, tutar, odeme_sekli: str, hesap_adi: str, aciklama: str | None = None) -> CariIslem:
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Ödeme tutarı pozitif olmalıdır.")
        if tarih > date.today():
            raise ValueError("Ödeme tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            belge_no = CariService._belge_no(session, "ODM")
            # Tedarikçi ödemesi açık alış bakiyesini düşer; müşteri ödemesi açık borç yaratır.
            if (cari.cari_turu or "") == "Tedarikçi":
                CariService._aciklara_uygula(session, cari_id, tutar)
            else:
                session.add(SatisHareketi(
                    cari_id=cari_id, satis_tarihi=tarih, belge_no=belge_no,
                    satis_tutari=tutar, kalan_acik_tutar=tutar,
                ))
            islem = CariIslem(
                cari_id=cari_id, tarih=tarih, islem_turu="Ödeme", belge_no=belge_no,
                aciklama=aciklama or odeme_sekli, borc=tutar, alacak=Decimal("0"), hesap_adi=hesap_adi,
            )
            session.add(islem)
            FinansService.hareket_ekle(session, belge_no, tarih, tutar, "CARİ ÖDEME", hesap_adi, odeme_sekli)
            session.flush()
            return islem

    @staticmethod
    def virman_yap(kaynak_id: int, hedef_id: int, tarih: date, tutar, aciklama: str | None = None) -> tuple[CariIslem, CariIslem]:
        tutar = CariService._tutar(tutar)
        if tutar <= 0:
            raise ValueError("Virman tutarı pozitif olmalıdır.")
        if kaynak_id == hedef_id:
            raise ValueError("Kaynak ve hedef cari aynı olamaz.")
        if tarih > date.today():
            raise ValueError("Virman tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            kaynak = session.get(Cari, kaynak_id)
            hedef = session.get(Cari, hedef_id)
            if kaynak is None or hedef is None:
                raise ValueError("Kaynak veya hedef cari bulunamadı.")
            acik_bakiye = sum(
                (
                    h.kalan_acik_tutar
                    for h in session.scalars(
                        select(SatisHareketi).where(
                            SatisHareketi.cari_id == kaynak_id,
                            SatisHareketi.kalan_acik_tutar > 0,
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            if tutar > acik_bakiye:
                raise ValueError(
                    "Bakiye veren virman fişi kaydedilemez. "
                    f"Kaynak açık bakiye {acik_bakiye:.2f} TL, girilen tutar {tutar:.2f} TL."
                )
            belge_no = CariService._belge_no(session, "VRM")
            # Çift kayıt: kaynak ALACAK, karşı cari (hedef) aynı tutarda BORÇ
            CariService._aciklara_uygula(session, kaynak_id, tutar)
            session.add(SatisHareketi(
                cari_id=hedef_id, satis_tarihi=tarih, belge_no=belge_no,
                satis_tutari=tutar, kalan_acik_tutar=tutar,
            ))
            kaynak_islem = CariIslem(
                cari_id=kaynak_id, tarih=tarih, islem_turu="Cari Virman", belge_no=belge_no,
                aciklama=aciklama or f"Alacak → borç: {hedef.cari_kodu} {hedef.unvan}",
                borc=Decimal("0"), alacak=tutar,
                karsi_cari_id=hedef_id,
            )
            hedef_islem = CariIslem(
                cari_id=hedef_id, tarih=tarih, islem_turu="Cari Virman", belge_no=belge_no,
                aciklama=aciklama or f"Borç ← alacak: {kaynak.cari_kodu} {kaynak.unvan}",
                borc=tutar, alacak=Decimal("0"),
                karsi_cari_id=kaynak_id,
            )
            session.add(kaynak_islem)
            session.add(hedef_islem)
            session.flush()
            return kaynak_islem, hedef_islem

    @staticmethod
    def virman_listele(arama: str = "") -> list[dict[str, Any]]:
        """Cari virman fişlerini belge no bazında listeler (kaynak alacak satırı üzerinden)."""
        arama = arama.strip()
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem)
                .where(CariIslem.islem_turu == "Cari Virman", CariIslem.alacak > 0)
                .order_by(CariIslem.tarih.desc(), CariIslem.id.desc())
            ).all()
            sonuc = []
            for islem in islemler:
                kaynak = session.get(Cari, islem.cari_id)
                hedef = session.get(Cari, islem.karsi_cari_id) if islem.karsi_cari_id else None
                kayit = {
                    "belge_no": islem.belge_no,
                    "tarih": islem.tarih,
                    "tutar": islem.alacak,
                    "aciklama": islem.aciklama or "",
                    "kaynak_id": islem.cari_id,
                    "hedef_id": islem.karsi_cari_id,
                    "kaynak_kodu": kaynak.cari_kodu if kaynak else "",
                    "kaynak_unvan": kaynak.unvan if kaynak else "",
                    "hedef_kodu": hedef.cari_kodu if hedef else "",
                    "hedef_unvan": hedef.unvan if hedef else "",
                }
                if arama:
                    ifade = arama.casefold()
                    metin = " ".join([
                        kayit["belge_no"], kayit["kaynak_kodu"], kayit["kaynak_unvan"],
                        kayit["hedef_kodu"], kayit["hedef_unvan"], kayit["aciklama"],
                    ]).casefold()
                    if ifade not in metin:
                        continue
                sonuc.append(kayit)
            return sonuc

    @staticmethod
    def _aciklara_geri_al(session, cari_id: int, tutar: Decimal, belge_no: str = "") -> None:
        """FIFO uygulanan açık bakiyeyi LIFO ile geri açar; fatura tahsilatını senkronlar."""
        kalan = tutar
        hareketler = session.scalars(
            select(SatisHareketi)
            .where(
                SatisHareketi.cari_id == cari_id,
                SatisHareketi.kalan_acik_tutar < SatisHareketi.satis_tutari,
            )
            .order_by(SatisHareketi.satis_tarihi.desc(), SatisHareketi.id.desc())
        ).all()
        for hareket in hareketler:
            if kalan <= 0:
                break
            if hareket.belge_no.startswith(("ODM-", "VRM-", "KKC-", "THS-")):
                continue
            kapasite = hareket.satis_tutari - hareket.kalan_acik_tutar
            if kapasite <= 0:
                continue
            eklenecek = min(kapasite, kalan)
            hareket.kalan_acik_tutar += eklenecek
            kalan -= eklenecek
            fatura = session.scalar(select(SatisFaturasi).where(SatisFaturasi.fatura_no == hareket.belge_no))
            if fatura and fatura.durum != "İPTAL":
                fatura.tahsilat_tutari = max(Decimal("0"), (fatura.tahsilat_tutari or Decimal("0")) - eklenecek)
                from database.satis_faturasi_service import SatisFaturasiService
                toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
                fatura.durum = "KAPALI" if fatura.tahsilat_tutari >= toplam else "AÇIK"
            else:
                from database.models.alis_faturasi import AlisFaturasi
                alis = session.scalar(select(AlisFaturasi).where(AlisFaturasi.fatura_no == hareket.belge_no))
                if alis and alis.durum != "İPTAL":
                    alis.odeme_tutari = max(Decimal("0"), (alis.odeme_tutari or Decimal("0")) - eklenecek)
                    from database.alis_faturasi_service import AlisFaturasiService
                    toplam = AlisFaturasiService.toplam(alis.satirlar)["genel_toplam"]
                    alis.durum = "KAPALI" if alis.odeme_tutari >= toplam else "AÇIK"
        if kalan > 0:
            session.add(SatisHareketi(
                cari_id=cari_id,
                satis_tarihi=date.today(),
                belge_no=f"IPT-{belge_no}" if belge_no else f"IPT-VRM-{cari_id}",
                satis_tutari=kalan,
                kalan_acik_tutar=kalan,
            ))

    @staticmethod
    def virman_iptal(belge_no: str) -> None:
        belge_no = (belge_no or "").strip()
        if not belge_no.startswith("VRM-"):
            raise ValueError("Geçersiz virman belge numarası.")
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).where(
                    CariIslem.belge_no == belge_no,
                    CariIslem.islem_turu == "Cari Virman",
                )
            ).all()
            if not islemler:
                raise ValueError("Virman fişi bulunamadı.")
            kaynak_islem = next((i for i in islemler if i.alacak > 0), None)
            hedef_islem = next((i for i in islemler if i.borc > 0), None)
            if kaynak_islem is None or hedef_islem is None:
                raise ValueError("Virman fişi eksik kayıtlı; iptal edilemez.")
            tutar = kaynak_islem.alacak
            hedef_hareket = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == hedef_islem.cari_id,
                )
            )
            if hedef_hareket is not None:
                if hedef_hareket.kalan_acik_tutar < hedef_hareket.satis_tutari:
                    raise ValueError(
                        "Hedef caride bu virman tutarının bir kısmı tahsil edilmiş; iptal edilemez."
                    )
                session.delete(hedef_hareket)
            CariService._aciklara_geri_al(session, kaynak_islem.cari_id, tutar, belge_no)
            for islem in islemler:
                session.delete(islem)
            session.flush()

    @staticmethod
    def kk_cekimi_yap(musteri_id: int, tedarikci_id: int, tarih: date, tutar, hesap_adi: str, aciklama: str | None = None) -> tuple[CariIslem, CariIslem]:
        """Geriye dönük uyumluluk: yeni KkCekimiService.kaydet kullanılır."""
        from database.kk_cekimi_service import KkCekimiService
        fis = KkCekimiService.kaydet(
            musteri_id, tedarikci_id, tarih, tutar,
            banka=hesap_adi or "Belirtilmedi",
            taksit_sayisi=1,
            aciklama=aciklama,
        )
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).where(CariIslem.belge_no == fis.belge_no)
            ).all()
            musteri_islem = next(i for i in islemler if i.alacak > 0)
            tedarikci_islem = next(i for i in islemler if i.borc > 0)
            return musteri_islem, tedarikci_islem

    @staticmethod
    def aktif_cariler(cari_turu: str | None = None) -> list[Cari]:
        with get_session() as session:
            statement = select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)
            if cari_turu:
                statement = statement.where(Cari.cari_turu == cari_turu)
            return list(session.scalars(statement).all())

    @staticmethod
    def aktif_tedarikciler() -> list[Cari]:
        tedarikciler = CariService.aktif_cariler(cari_turu="Tedarikçi")
        if tedarikciler:
            return tedarikciler
        return CariService.aktif_cariler()

    @staticmethod
    def aktif_musteriler() -> list[Cari]:
        return CariService.aktif_cariler(cari_turu="Müşteri")

    @staticmethod
    def satis_raporu() -> dict[str, Any]:
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService
        from sqlalchemy.orm import selectinload

        with get_session() as session:
            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.satirlar))
                .order_by(SatisFaturasi.fatura_tarihi.desc())
            ).all()
            toplam_ciro = Decimal("0")
            toplam_tahsilat = Decimal("0")
            musteri_cirasi: dict[str, Decimal] = {}
            aylik: dict[str, Decimal] = {}
            satirlar = []
            for fatura in faturalar:
                genel = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
                toplam_ciro += genel
                toplam_tahsilat += fatura.tahsilat_tutari or Decimal("0")
                unvan = fatura.cari.unvan if fatura.cari else "-"
                musteri_cirasi[unvan] = musteri_cirasi.get(unvan, Decimal("0")) + genel
                ay = fatura.fatura_tarihi.strftime("%Y-%m")
                aylik[ay] = aylik.get(ay, Decimal("0")) + genel
                satirlar.append({
                    "fatura_no": fatura.fatura_no,
                    "tarih": fatura.fatura_tarihi,
                    "musteri": unvan,
                    "toplam": genel,
                    "tahsilat": fatura.tahsilat_tutari or Decimal("0"),
                    "kalan": genel - (fatura.tahsilat_tutari or Decimal("0")),
                    "durum": fatura.durum,
                })
            acik_bakiye = sum(
                (h.kalan_acik_tutar for h in session.scalars(select(SatisHareketi)).all()),
                Decimal("0"),
            )
            top_musteriler = sorted(musteri_cirasi.items(), key=lambda x: x[1], reverse=True)[:10]
            return {
                "toplam_ciro": toplam_ciro,
                "toplam_tahsilat": toplam_tahsilat,
                "acik_bakiye": acik_bakiye,
                "fatura_sayisi": len(faturalar),
                "aylik": sorted(aylik.items()),
                "top_musteriler": top_musteriler,
                "satirlar": satirlar,
            }

    @staticmethod
    def tahsilat_odeme_raporu() -> dict[str, Any]:
        """Cari hareketlerden tahsilat (alacak) ve ödeme (borç) raporları."""
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).order_by(CariIslem.tarih.desc(), CariIslem.id.desc())
            ).all()
            tahsilatlar = []
            odemeler = []
            toplam_tahsilat = Decimal("0")
            toplam_odeme = Decimal("0")
            for islem in islemler:
                cari = session.get(Cari, islem.cari_id)
                karsi = session.get(Cari, islem.karsi_cari_id) if islem.karsi_cari_id else None
                kayit = {
                    "tarih": islem.tarih,
                    "tur": islem.islem_turu,
                    "belge_no": islem.belge_no,
                    "cari_kodu": cari.cari_kodu if cari else "",
                    "cari_unvan": cari.unvan if cari else "",
                    "karsi_kodu": karsi.cari_kodu if karsi else "",
                    "karsi_unvan": karsi.unvan if karsi else "",
                    "hesap": islem.hesap_adi or "",
                    "aciklama": islem.aciklama or "",
                    "borc": islem.borc or Decimal("0"),
                    "alacak": islem.alacak or Decimal("0"),
                }
                if kayit["alacak"] > 0:
                    tahsilatlar.append(kayit)
                    toplam_tahsilat += kayit["alacak"]
                if kayit["borc"] > 0:
                    odemeler.append(kayit)
                    toplam_odeme += kayit["borc"]
            return {
                "tahsilatlar": tahsilatlar,
                "odemeler": odemeler,
                "toplam_tahsilat": toplam_tahsilat,
                "toplam_odeme": toplam_odeme,
                "tahsilat_sayisi": len(tahsilatlar),
                "odeme_sayisi": len(odemeler),
            }

    @staticmethod
    def sonraki_kod(cari_turu: str = "Müşteri") -> str:
        """Müşteri: M00001… — Tedarikçi: T00001… (5 haneli sıra)."""
        onek = "T" if (cari_turu or "").strip() == "Tedarikçi" else "M"
        with get_session() as session:
            kodlar = session.scalars(
                select(Cari.cari_kodu).where(Cari.cari_kodu.like(f"{onek}%"))
            ).all()
            max_no = 0
            for kod in kodlar:
                if not kod:
                    continue
                kuyruk = kod[1:]
                if len(kod) >= 2 and kod[0].upper() == onek and kuyruk.isdigit():
                    max_no = max(max_no, int(kuyruk))
            return f"{onek}{max_no + 1:05d}"

    @staticmethod
    def ekle(veriler: dict[str, object]) -> Cari:
        veriler = dict(veriler)
        cari_turu = str(veriler.get("cari_turu") or "Müşteri")
        veriler["cari_turu"] = cari_turu
        son_hata: Exception | None = None
        for _ in range(25):
            if not (str(veriler.get("cari_kodu") or "").strip()):
                veriler["cari_kodu"] = CariService.sonraki_kod(cari_turu)
            try:
                with get_session() as session:
                    cari = Cari(**veriler)
                    session.add(cari)
                    session.flush()
                    return cari
            except IntegrityError as hata:
                son_hata = hata
                veriler["cari_kodu"] = CariService.sonraki_kod(cari_turu)
        raise ValueError("Cari kodu üretilemedi.") from son_hata

    @staticmethod
    def guncelle(cari_id: int, veriler: dict[str, object]) -> Cari:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            for alan, deger in veriler.items():
                setattr(cari, alan, deger)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Cari kodu zaten kullanılıyor.") from hata
            return cari

    @staticmethod
    def pasife_al(cari_id: int) -> None:
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            cari.aktif = False
            session.flush()

    @staticmethod
    def satis_ekle(cari_id: int, veriler: dict[str, object]) -> SatisHareketi:
        satis_tarihi = veriler.get("satis_tarihi")
        satis_tutari = CariService._tutar(veriler.get("satis_tutari"))
        kalan = CariService._tutar(veriler.get("kalan_acik_tutar"))
        if not isinstance(satis_tarihi, date) or satis_tarihi > date.today():
            raise ValueError("Satış tarihi gelecek bir tarih olamaz.")
        if satis_tutari <= 0 or kalan < 0:
            raise ValueError("Satış tutarı pozitif, kalan tutar sıfır veya daha büyük olmalıdır.")
        if kalan > satis_tutari:
            raise ValueError("Kalan açık tutar satış tutarından büyük olamaz.")
        with get_session() as session:
            if session.get(Cari, cari_id) is None:
                raise ValueError("Cari bulunamadı.")
            hareket = SatisHareketi(
                cari_id=cari_id,
                satis_tarihi=satis_tarihi,
                belge_no=str(veriler.get("belge_no", "")).strip(),
                satis_tutari=satis_tutari,
                kalan_acik_tutar=kalan,
            )
            if not hareket.belge_no:
                raise ValueError("Belge/fatura numarası zorunludur.")
            session.add(hareket)
            session.flush()
            return hareket

    @staticmethod
    def _tutar(deger: object) -> Decimal:
        try:
            return Decimal(str(deger).replace(".", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValueError("Tutar geçerli bir sayı olmalıdır.") from None

    @staticmethod
    def _ozet(cari: Cari) -> dict[str, Any]:
        bugun = date.today()
        aciklar = [
            hareket for hareket in cari.satis_hareketleri if hareket.kalan_acik_tutar > 0
        ]
        gunler = [
            (bugun - hareket.satis_tarihi).days
            for hareket in aciklar
        ]
        bakiye = sum((hareket.kalan_acik_tutar for hareket in cari.satis_hareketleri), Decimal("0"))
        ortalama = sum(gunler) / len(gunler) if gunler else 0
        pozitif_bakiye = sum((h.kalan_acik_tutar for h in aciklar), Decimal("0"))
        agirlikli = (
            sum((float(hareket.kalan_acik_tutar) * gun for hareket, gun in zip(aciklar, gunler)), 0.0) / float(pozitif_bakiye)
            if pozitif_bakiye else 0
        )
        return {
            "cari": cari,
            "bakiye": bakiye,
            "ortalama_gun": ortalama,
            "agirlikli_ortalama_gun": agirlikli,
        }
