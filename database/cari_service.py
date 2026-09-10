from datetime import date
from decimal import Decimal, InvalidOperation
import unicodedata
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem, SatisHareketi
# SatisFaturasi ilişkileri — önce hedef sınıflar kayda alınmalı
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
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
        from sqlalchemy.orm import selectinload

        arama = CariService._arama_kontrol(arama)
        with get_session() as session:
            statement = (
                select(Cari)
                .options(selectinload(Cari.satis_hareketleri))
                .order_by(Cari.cari_kodu)
            )
            if cari_turu:
                # "Müşteri" / "Musteri" gibi yazım farklarını kapsar
                tur = (cari_turu or "").strip()
                if tur.casefold().startswith("muster") or tur.casefold().startswith("müşter"):
                    statement = statement.where(
                        or_(
                            Cari.cari_turu == "Müşteri",
                            Cari.cari_turu == "Musteri",
                            Cari.cari_turu.ilike("müster%"),
                            Cari.cari_turu.ilike("muster%"),
                        )
                    )
                elif tur.casefold().startswith("tedarik"):
                    statement = statement.where(
                        or_(
                            Cari.cari_turu == "Tedarikçi",
                            Cari.cari_turu.ilike("tedarik%"),
                        )
                    )
                else:
                    statement = statement.where(Cari.cari_turu == tur)
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
            return [CariService._ozet(cari, session=session) for cari in cariler]

    @staticmethod
    def getir(cari_id: int) -> Cari | None:
        with get_session() as session:
            return session.get(Cari, cari_id)

    @staticmethod
    def kod_ile_getir(cari_kodu: str) -> Cari | None:
        kod = (cari_kodu or "").strip()
        if not kod:
            return None
        with get_session() as session:
            return session.scalar(select(Cari).where(Cari.cari_kodu == kod))

    @staticmethod
    def detay(cari_id: int) -> dict[str, Any] | None:
        from sqlalchemy.orm import selectinload

        with get_session() as session:
            cari = session.scalar(
                select(Cari)
                .where(Cari.id == int(cari_id))
                .options(selectinload(Cari.satis_hareketleri))
            )
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
        islemler = list(
            session.scalars(select(CariIslem).where(CariIslem.cari_id == cari_id)).all()
        )
        islem_belgeleri = {i.belge_no for i in islemler}

        for h in session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cari_id)):
            # Aynı belge CariIslem'de varsa çift kayıt olmasın (GHV/KKC/ODM vb.)
            if h.belge_no in islem_belgeleri:
                continue
            if h.belge_no.startswith(
                ("ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-", "IPT-", "FZO-")
            ):
                continue
            if h.belge_no.startswith(("AFAT-", "ARAY")):
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
                "kalan": None,
            })
        for islem in islemler:
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
        # Kronolojik çalışan bakiye → Kalan Bakiye kolonu
        kayitlar.sort(key=lambda item: (item["tarih"], item["belge_no"], item["tur"]))
        calisan = Decimal("0")
        for kayit in kayitlar:
            calisan += Decimal(str(kayit["borc"] or 0)) - Decimal(str(kayit["alacak"] or 0))
            kayit["kalan"] = calisan
        kayitlar.reverse()  # ekranda yeniden eskiye
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
        """Açık borçlara FIFO uygular: ilk alacak → en eski açık borç (tarih, id).

        Müşteri: satış/borç satırları; tedarikçi: alış/borç satırları.
        Faturaların tahsilat/ödeme tutarını senkronlar. Eşleşmeyen tutarı döner.
        """
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
            # Tedarikçi: ödeme borcu düşürür (alacak) + fazla ödeme kredisi.
            # Müşteri: ödeme müşteriye borç yazar.
            if (cari.cari_turu or "") == "Tedarikçi":
                kalan = CariService._aciklara_uygula(session, cari_id, tutar)
                if kalan > 0:
                    session.add(SatisHareketi(
                        cari_id=cari_id, satis_tarihi=tarih, belge_no=belge_no,
                        satis_tutari=Decimal("0"), kalan_acik_tutar=-kalan,
                    ))
                islem = CariIslem(
                    cari_id=cari_id, tarih=tarih, islem_turu="Ödeme", belge_no=belge_no,
                    aciklama=aciklama or odeme_sekli, borc=Decimal("0"), alacak=tutar, hesap_adi=hesap_adi,
                )
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
    def acilis_fisi_ekle(
        cari_id: int,
        tarih: date,
        *,
        borc=0,
        alacak=0,
        belge_no: str,
        aciklama: str | None = None,
    ) -> CariIslem:
        """Cari açılış / devir fişi (borç veya alacak; ikisi birden olmaz).

        Borç satırında SatisHareketi de yazılır ki FIFO açık borç kuyruğuna girsin.
        """
        borc_t = borc if isinstance(borc, Decimal) else CariService._tutar(borc)
        alacak_t = alacak if isinstance(alacak, Decimal) else CariService._tutar(alacak)
        if not isinstance(borc_t, Decimal):
            borc_t = Decimal(str(borc_t))
        if not isinstance(alacak_t, Decimal):
            alacak_t = Decimal(str(alacak_t))
        borc_t = borc_t.quantize(Decimal("0.01"))
        alacak_t = alacak_t.quantize(Decimal("0.01"))
        if borc_t < 0 or alacak_t < 0:
            raise ValueError("Açılış tutarları negatif olamaz.")
        if (borc_t > 0) == (alacak_t > 0):
            raise ValueError("Açılış fişinde yalnızca borç veya yalnızca alacak olmalıdır.")
        belge = (belge_no or "").strip()
        if not belge:
            raise ValueError("Belge numarası zorunludur.")
        if len(belge) > 50:
            raise ValueError("Belge numarası 50 karakteri aşamaz.")
        if tarih > date.today():
            raise ValueError("Açılış tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            mevcut = session.scalar(select(CariIslem).where(CariIslem.belge_no == belge))
            if mevcut is not None:
                raise ValueError(f"Belge no zaten var: {belge}")
            if borc_t > 0:
                session.add(
                    SatisHareketi(
                        cari_id=cari_id,
                        satis_tarihi=tarih,
                        belge_no=belge,
                        satis_tutari=borc_t,
                        kalan_acik_tutar=borc_t,
                    )
                )
            islem = CariIslem(
                cari_id=cari_id,
                tarih=tarih,
                islem_turu="Açılış",
                belge_no=belge,
                aciklama=aciklama or "Açılış / dönem devir",
                borc=borc_t,
                alacak=alacak_t,
            )
            session.add(islem)
            session.flush()
            return islem

    @staticmethod
    def islem_belge_var_mi(belge_no: str) -> bool:
        belge = (belge_no or "").strip()
        if not belge:
            return False
        with get_session() as session:
            return (
                session.scalar(select(CariIslem.id).where(CariIslem.belge_no == belge))
                is not None
            )

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
            belge_no = CariService._belge_no(session, "VRM")
            # Çift kayıt: kaynak ALACAK, karşı cari (hedef) aynı tutarda BORÇ
            # Açık bakiye şartı yok; varsa FIFO uygulanır, yoksa yalnızca cari işlem yazılır.
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
    def islemler_belge_no_ile(belge_no: str) -> list:
        """Belge numarasına bağlı cari işlem(ler); cari ilişkisi yüklü."""
        belge_no = (belge_no or "").strip()
        if not belge_no:
            return []
        with get_session() as session:
            islemler = list(
                session.scalars(
                    select(CariIslem)
                    .options(selectinload(CariIslem.cari))
                    .where(CariIslem.belge_no == belge_no)
                    .order_by(CariIslem.id)
                ).all()
            )
            return islemler

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
                select(CariIslem).where(CariIslem.belge_no == fis["belge_no"])
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
        return CariService.aktif_cariler(cari_turu="Tedarikçi")

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
    def vergi_no_dogrula(deger: object) -> None:
        """Boş serbest; doluysa 10 haneli VKN algoritması."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("Vergi numarası yalnızca rakam olmalıdır.")
        if len(ham) != 10:
            raise ValueError("Vergi kimlik numarası (VKN) 10 hane olmalıdır.")
        CariService._vkn_dogrula(ham)

    @staticmethod
    def tc_kimlik_dogrula(deger: object) -> None:
        """Boş serbest; doluysa 11 haneli TCKN algoritması."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("TC kimlik numarası yalnızca rakam olmalıdır.")
        if len(ham) != 11:
            raise ValueError("TC kimlik numarası 11 hane olmalıdır.")
        CariService._tc_kimlik_dogrula(ham)

    @staticmethod
    def vergi_veya_tc_dogrula(deger: object) -> None:
        """Geriye dönük: boş serbest; 10 hane VKN, 11 hane TCKN."""
        ham = str(deger or "").strip().replace(" ", "")
        if not ham:
            return
        if not ham.isdigit():
            raise ValueError("Vergi / TC kimlik numarası yalnızca rakam olmalıdır.")
        if len(ham) == 11:
            CariService._tc_kimlik_dogrula(ham)
        elif len(ham) == 10:
            CariService._vkn_dogrula(ham)
        else:
            raise ValueError(
                "Vergi kimlik no 10 hane (VKN) veya TC kimlik no 11 hane olmalıdır."
            )

    @staticmethod
    def _tc_kimlik_dogrula(no: str) -> None:
        if len(no) != 11 or not no.isdigit() or no[0] == "0":
            raise ValueError("Geçersiz TC kimlik numarası.")
        d = [int(c) for c in no]
        # 10. hane: ((1+3+5+7+9)*7 - (2+4+6+8)) mod 10
        o1 = sum(d[i] for i in range(0, 9, 2))
        o2 = sum(d[i] for i in range(1, 8, 2))
        if ((o1 * 7) - o2) % 10 != d[9]:
            raise ValueError("TC kimlik numarası algoritma kontrolünden geçemedi.")
        if (sum(d[:10]) % 10) != d[10]:
            raise ValueError("TC kimlik numarası algoritma kontrolünden geçemedi.")

    @staticmethod
    def _vkn_dogrula(no: str) -> None:
        if len(no) != 10 or not no.isdigit():
            raise ValueError("Geçersiz vergi kimlik numarası (VKN).")
        d = [int(c) for c in no]
        toplam = 0
        for i in range(9):
            tmp = (d[i] + 9 - i) % 10
            if tmp == 0:
                continue
            contrib = (tmp * (2 ** (9 - i))) % 9
            toplam += 9 if contrib == 0 else contrib
        check = (10 - (toplam % 10)) % 10
        if check != d[9]:
            raise ValueError("Vergi kimlik numarası (VKN) algoritma kontrolünden geçemedi.")

    @staticmethod
    def _tutar(deger: object) -> Decimal:
        try:
            return Decimal(str(deger).replace(".", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            raise ValueError("Tutar geçerli bir sayı olmalıdır.") from None

    @staticmethod
    def _borc_vade_haritasi(session, belge_nolari: list[str] | set[str]) -> dict[str, date]:
        """Belge no → borç vade tarihi (Satış/Alış faturası.vade_tarihi).

        SatisHareketi'nde vade kolonu yok; fatura_no ile eşleşen faturadan alınır.
        """
        nos = [n for n in {str(n or "").strip() for n in belge_nolari} if n]
        if not nos:
            return {}
        harita: dict[str, date] = {}
        for fatura_no, vade in session.execute(
            select(SatisFaturasi.fatura_no, SatisFaturasi.vade_tarihi).where(
                SatisFaturasi.fatura_no.in_(nos)
            )
        ):
            if fatura_no and vade:
                harita[str(fatura_no)] = vade
        from database.models.alis_faturasi import AlisFaturasi

        eksik = [n for n in nos if n not in harita]
        if eksik:
            for fatura_no, vade in session.execute(
                select(AlisFaturasi.fatura_no, AlisFaturasi.vade_tarihi).where(
                    AlisFaturasi.fatura_no.in_(eksik)
                )
            ):
                if fatura_no and vade:
                    harita[str(fatura_no)] = vade
        return harita

    @staticmethod
    def _hareket_vade(h: SatisHareketi, vade_harita: dict[str, date] | None = None) -> date:
        """Borç vadesi: fatura vade_tarihi, yoksa belge tarihi (satis_tarihi)."""
        if vade_harita:
            vade = vade_harita.get(h.belge_no or "")
            if vade:
                return vade
        return h.satis_tarihi

    @staticmethod
    def _agirlikli_gun_ortalama(dilimler: list[dict[str, Any]]) -> float:
        """Σ(tutar × gün) / Σ(tutar); boşsa 0."""
        toplam = Decimal("0")
        agirlik = 0.0
        for d in dilimler:
            tutar = Decimal(str(d.get("tutar") or 0))
            if tutar <= 0:
                continue
            toplam += tutar
            agirlik += float(tutar) * int(d.get("gun") or 0)
        return agirlik / float(toplam) if toplam else 0.0

    @staticmethod
    def _basit_gun_ortalama(dilimler: list[dict[str, Any]]) -> float:
        """Σ(gün) / adet; boşsa 0."""
        if not dilimler:
            return 0.0
        return sum(int(d.get("gun") or 0) for d in dilimler) / len(dilimler)

    # Borç kuyruğuna alınmayan belgeler (kredi/tahsilat/ödeme fişleri).
    # Valör borçları = satış/alış faturaları (ve benzeri belge borçları);
    # ODM/THS vb. cari fişleri fatura borcu sayılmaz.
    _VALOR_BORC_HARIC_ONEK = (
        "VRM-", "KKC-", "THS-", "AHV-", "POS-", "BNC-", "KBY-", "KKO-", "IPT-", "FZO-",
        "ODM-", "GHV-",
    )

    @staticmethod
    def _odeme_borc_dusurur_mu(islem: CariIslem, tedarikci: bool) -> Decimal:
        """Bakiyeyi düşüren alacak tutarı (FIFO eşleştirme kaynağı).

        Müşteri: Tahsilat / virman / KK çekimi → alacak.
        Tedarikçi: Ödeme → alacak (BİRR polarite düzeltmesi sonrası);
        eski yanlış kayıtlar için Ödeme+borc yedeklenir.
        """
        dusen = Decimal(str(islem.alacak or 0))
        if dusen <= 0 and tedarikci and (islem.islem_turu or "") == "Ödeme":
            dusen = Decimal(str(islem.borc or 0))
        return dusen if dusen > 0 else Decimal("0")

    @staticmethod
    def _fifo_valor_dilimleri(
        session,
        cari_id: int,
        cari_turu: str | None = None,
        referans: date | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """FIFO valör: (tamamen_kapanan_faturalar, açık_kalan, kapanan_dilimler).

        Eşleştirme: alacaklar en eski açık borçtan düşülür (FIFO).
        Tamamen kapanan fatura:
          kapanma_günü = son_kapatan_ödeme_tarihi − vade; tutar = fatura tutarı
        Kapanan dilim (her ödeme parçası):
          gün = ödeme_tarihi − vade; tutar = kapanan parça
        Açık: gecikme = referans − vade; tutar = kalan açık
        Vade: fatura.vade_tarihi, yoksa belge tarihi. Peşinat uydurulmaz.
        """
        bugun = referans or date.today()
        hareketler = list(
            session.scalars(
                select(SatisHareketi)
                .where(SatisHareketi.cari_id == cari_id)
                .order_by(SatisHareketi.satis_tarihi, SatisHareketi.id)
            ).all()
        )
        vade_harita = CariService._borc_vade_haritasi(
            session, [h.belge_no for h in hareketler]
        )
        # [vade, belge_tarih, kalan, orijinal, belge_no, son_odeme_tarihi]
        kuyruk: list[list] = []
        for h in hareketler:
            tutar = Decimal(str(h.satis_tutari or 0))
            if tutar <= 0:
                continue
            no = h.belge_no or ""
            if no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
                continue
            vade = CariService._hareket_vade(h, vade_harita)
            kuyruk.append([vade, h.satis_tarihi, tutar, tutar, no, None])

        kapanan_dilimler: list[dict[str, Any]] = []
        if kuyruk:
            islemler = list(
                session.scalars(
                    select(CariIslem)
                    .where(CariIslem.cari_id == cari_id)
                    .order_by(CariIslem.tarih, CariIslem.id)
                ).all()
            )
            tedarikci = (cari_turu or "").casefold().startswith("tedarik")
            for islem in islemler:
                kalan_odeme = CariService._odeme_borc_dusurur_mu(islem, tedarikci)
                if kalan_odeme <= 0:
                    continue
                for dilim_satir in kuyruk:
                    if kalan_odeme <= 0:
                        break
                    vade, belge_tarih, kalan_dilim, _orj, borc_no, _son = dilim_satir
                    if kalan_dilim <= 0:
                        continue
                    if belge_tarih > islem.tarih:
                        continue
                    dilim = min(kalan_dilim, kalan_odeme)
                    dilim_satir[2] = kalan_dilim - dilim
                    dilim_satir[5] = islem.tarih
                    kapanan_dilimler.append(
                        {
                            "odeme_belge_no": islem.belge_no,
                            "odeme_tarihi": islem.tarih,
                            "borc_belge_no": borc_no,
                            "borc_tarihi": belge_tarih,
                            "borc_vadesi": vade,
                            "tutar": dilim,
                            "gun": (islem.tarih - vade).days,
                        }
                    )
                    kalan_odeme -= dilim

        kapanan: list[dict[str, Any]] = []
        acik: list[dict[str, Any]] = []
        for vade, belge_tarih, kalan_dilim, orijinal, borc_no, son_odeme in kuyruk:
            if kalan_dilim <= 0 and son_odeme is not None:
                kapanan.append(
                    {
                        "borc_belge_no": borc_no,
                        "borc_tarihi": belge_tarih,
                        "borc_vadesi": vade,
                        "kapanma_tarihi": son_odeme,
                        "tutar": orijinal,
                        "gun": (son_odeme - vade).days,
                    }
                )
            elif kalan_dilim > 0:
                acik.append(
                    {
                        "borc_belge_no": borc_no,
                        "borc_tarihi": belge_tarih,
                        "borc_vadesi": vade,
                        "tutar": kalan_dilim,
                        "gun": (bugun - vade).days,
                    }
                )
        return kapanan, acik, kapanan_dilimler

    @staticmethod
    def _fifo_odeme_borc_eslesmeleri(
        session, cari_id: int, cari_turu: str | None = None
    ) -> list[dict[str, Any]]:
        """FIFO kapanış dilimleri (geriye dönük API)."""
        _tam, _acik, dilimler = CariService._fifo_valor_dilimleri(session, cari_id, cari_turu)
        return dilimler

    @staticmethod
    def _odenen_ortalama_valor_fifo(session, cari_id: int, cari_turu: str | None = None) -> float:
        """Kapanan borcun tutar-ağırlıklı ortalama valörü (gün).

        Öncelik: tamamen kapanan faturalar (son ödeme − vade).
        Yoksa: kapanan dilimler (ödeme − vade) — kısmi tahsilatta boş kalmasın.
        """
        tam, _acik, dilimler = CariService._fifo_valor_dilimleri(session, cari_id, cari_turu)
        kaynak = tam if tam else dilimler
        return CariService._agirlikli_gun_ortalama(kaynak)

    @staticmethod
    def _acik_ortalama_valor_fifo(
        session, cari_id: int, cari_turu: str | None = None, referans: date | None = None
    ) -> float:
        """Açık bakiyenin tutar-ağırlıklı ortalama valörü (gün = bugün − vade)."""
        _tam, acik, _dilimler = CariService._fifo_valor_dilimleri(
            session, cari_id, cari_turu, referans=referans
        )
        return CariService._agirlikli_gun_ortalama(acik)

    @staticmethod
    def _ozet(cari: Cari, session=None) -> dict[str, Any]:
        """Cari hesap özeti.

        Toplam borç/alacak: defter sütun toplamları (hareket genel toplam ile aynı).
        Bakiye: toplam_borç − toplam_alacak (defter kalan konvansiyonu).
        Bakiye durumu: Borçlu / Alacaklı / Bakiye yok.

        Kapanan borcun ort. valörü (tutar ağırlıklı):
          1) Tamamen kapanan faturalar: gün = son_kapatan_ödeme − vade;
             Σ(fatura_tutarı × gün) / Σ(kapanan fatura tutarları).
          2) Hiç tam kapanan yoksa: FIFO kapanan dilimler;
             Σ(dilim × (ödeme − vade)) / Σ(dilim).

        Bakiyenin ort. valörü:
          Açık kalan; gün = bugün − vade;
          Σ(kalan_açık × gün) / Σ(kalan_açık).
        """
        bugun = date.today()
        hareketler = list(cari.satis_hareketleri or [])
        borclar = [h for h in hareketler if Decimal(str(h.kalan_acik_tutar or 0)) > 0]
        alacaklar = [h for h in hareketler if Decimal(str(h.kalan_acik_tutar or 0)) < 0]
        acik_borc = sum((Decimal(str(h.kalan_acik_tutar)) for h in borclar), Decimal("0"))
        acik_alacak = sum((-Decimal(str(h.kalan_acik_tutar)) for h in alacaklar), Decimal("0"))

        odenen_valor = 0.0
        odenen_valor_basit = 0.0
        bakiye_valor = 0.0
        if session is not None:
            defter = CariService._defter(session, cari.id)
            toplam_borc = sum((Decimal(str(k.get("borc") or 0)) for k in defter), Decimal("0"))
            toplam_alacak = sum((Decimal(str(k.get("alacak") or 0)) for k in defter), Decimal("0"))
            bakiye = toplam_borc - toplam_alacak
            kapanan_tam, acik_dilimler, kapanan_dilimler = CariService._fifo_valor_dilimleri(
                session, cari.id, cari_turu=cari.cari_turu, referans=bugun
            )
            kapanan_kaynak = kapanan_tam if kapanan_tam else kapanan_dilimler
            odenen_valor = CariService._agirlikli_gun_ortalama(kapanan_kaynak)
            odenen_valor_basit = CariService._basit_gun_ortalama(kapanan_kaynak)
            bakiye_valor = CariService._agirlikli_gun_ortalama(acik_dilimler)
        else:
            toplam_borc = sum(
                (Decimal(str(h.satis_tutari or 0)) for h in hareketler if Decimal(str(h.satis_tutari or 0)) > 0),
                Decimal("0"),
            )
            toplam_alacak = Decimal("0")
            bakiye = sum((Decimal(str(h.kalan_acik_tutar or 0)) for h in hareketler), Decimal("0"))

        if bakiye > 0:
            bakiye_durumu = "Borçlu"
        elif bakiye < 0:
            bakiye_durumu = "Alacaklı"
        else:
            bakiye_durumu = "Bakiye yok"

        borc_valor = bakiye_valor
        alacak_valor = 0.0
        vade_harita: dict[str, date] | None = None
        if session is not None:
            vade_harita = CariService._borc_vade_haritasi(
                session, [h.belge_no for h in hareketler]
            )
        if alacaklar:
            toplam_a = Decimal("0")
            agirlik_a = 0.0
            for h in alacaklar:
                tutar = -Decimal(str(h.kalan_acik_tutar or 0))
                if tutar <= 0:
                    continue
                toplam_a += tutar
                vade = CariService._hareket_vade(h, vade_harita)
                agirlik_a += float(tutar) * (bugun - vade).days
            alacak_valor = agirlik_a / float(toplam_a) if toplam_a else 0.0

        ortalama = (
            sum(
                (bugun - CariService._hareket_vade(h, vade_harita)).days for h in borclar
            )
            / len(borclar)
            if borclar
            else 0.0
        )
        return {
            "cari": cari,
            "bakiye": bakiye,
            "bakiye_durumu": bakiye_durumu,
            "toplam_borc": toplam_borc,
            "toplam_alacak": toplam_alacak,
            "odenen_ortalama_valor_gun": odenen_valor,
            "odenen_ortalama_valor_basit_gun": odenen_valor_basit,
            "bakiye_ortalama_valor_gun": bakiye_valor,
            "borc_tutar": acik_borc,
            "alacak_tutar": acik_alacak,
            "borc_valor_gun": borc_valor,
            "alacak_valor_gun": alacak_valor,
            "ortalama_gun": ortalama,
            "agirlikli_ortalama_gun": bakiye_valor if bakiye >= 0 else alacak_valor,
            "acik_hareket_sayisi": len(borclar) + len(alacaklar),
        }
