"""Genel muhasebe servisleri — hesap planı, fiş, mizan, bilanço, gelir tablosu."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from database.access import AccessError, yazma_zorunlu, yetki_zorunlu
from database.database import get_session
from database.donem_service import DonemService
from database.models.genel_muhasebe import (
    ANA_HESAP_SINIFLARI,
    ESLEME_ANAHTARLARI,
    FIS_DURUMLARI,
    FIS_TURLERI,
    HESAP_TURLERI,
    HesapPlani,
    MuhasebeFisi,
    MuhasebeFisiSatiri,
    MuhasebeHesapEsleme,
    MuhasebeIslemGecmisi,
)
from database.tdhp_hesap_plani import (
    TDHP_ANA_HESAPLAR,
    fis_alt_hesap_zorunlu,
    tdhp_ust_kodu,
)
from database.session_manager import oturum

SIFIR = Decimal("0.00")
IKI = Decimal("0.01")


def decimal(tutar) -> Decimal:
    """Türkçe/İngilizce ondalık girdiyi Decimal'e çevirir."""
    if tutar is None or tutar == "":
        return SIFIR
    if isinstance(tutar, Decimal):
        return tutar.quantize(IKI, rounding=ROUND_HALF_UP)
    if isinstance(tutar, (int, float)):
        return Decimal(str(tutar)).quantize(IKI, rounding=ROUND_HALF_UP)
    s = str(tutar).strip().replace(" ", "")
    if not s:
        return SIFIR
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s).quantize(IKI, rounding=ROUND_HALF_UP)


def para_goster(tutar) -> str:
    d = decimal(tutar)
    isaret = "-" if d < 0 else ""
    d = abs(d)
    tam, kesir = f"{d:.2f}".split(".")
    tam_fmt = f"{int(tam):,}".replace(",", ".")
    return f"{isaret}{tam_fmt},{kesir}"


class MuhasebeService:
    @staticmethod
    def yerel_firma_id(session) -> int:
        return DonemService._yerel_firma_id(session)

    @staticmethod
    def _gecmis(
        session,
        *,
        kayit_turu: str,
        kayit_id: int,
        islem: str,
        detay: str | None = None,
    ) -> None:
        session.add(
            MuhasebeIslemGecmisi(
                firma_id=MuhasebeService.yerel_firma_id(session),
                kayit_turu=kayit_turu,
                kayit_id=kayit_id,
                islem=islem,
                detay=detay,
                kullanici_id=oturum.user_id,
                kullanici_adi=oturum.kullanici_adi or oturum.ad_soyad,
            )
        )

    @staticmethod
    def schema_hazirla() -> None:
        """Mevcut firma DB'de tablolar yoksa oluştur; ana hesapları doldur."""
        from database.database import engine
        from database.models.genel_muhasebe import (
            HesapPlani as HP,
            MuhasebeFisi,
            MuhasebeFisiSatiri,
            MuhasebeHesapEsleme,
            MuhasebeIslemGecmisi,
        )

        for tablo in (
            HP.__table__,
            MuhasebeFisi.__table__,
            MuhasebeFisiSatiri.__table__,
            MuhasebeHesapEsleme.__table__,
            MuhasebeIslemGecmisi.__table__,
        ):
            tablo.create(engine, checkfirst=True)
        MuhasebeService.ana_hesaplari_doldur()
        MuhasebeService.esleme_sablonlarini_doldur()

    @staticmethod
    def ana_hesaplari_doldur() -> int:
        """Türkiye Tek Düzen Hesap Planı ana hesaplarını (sınıf/grup/3 haneli) yükler.

        Mevcut kodlara dokunmaz (ad/tür hariç üst bağ ve seviye düzeltilir);
        yalnızca eksikleri ekler. Dönüş: yeni eklenen adedi.
        """
        eklenen = 0
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            mevcut = {
                h.hesap_kodu: h
                for h in session.scalars(
                    select(HesapPlani).where(HesapPlani.firma_id == firma_id)
                ).all()
            }
            sirali = sorted(
                TDHP_ANA_HESAPLAR,
                key=lambda x: (len(x[0]), x[0]),
            )
            for kod, ad, tur in sirali:
                ust_kod = tdhp_ust_kodu(kod)
                ust_id = None
                seviye = 1
                if ust_kod:
                    ust = mevcut.get(ust_kod)
                    if ust is not None:
                        ust_id = ust.id
                        seviye = int(ust.hesap_seviyesi) + 1
                    else:
                        seviye = min(len(kod), 3)
                if kod in mevcut:
                    h = mevcut[kod]
                    # Hiyerarşiyi tek düzene hizala
                    if h.ust_hesap_id != ust_id:
                        h.ust_hesap_id = ust_id
                    if h.hesap_seviyesi != seviye:
                        h.hesap_seviyesi = seviye
                    if not h.hesap_adi:
                        h.hesap_adi = ad
                    if h.hesap_turu != tur:
                        h.hesap_turu = tur
                    continue
                h = HesapPlani(
                    firma_id=firma_id,
                    hesap_kodu=kod,
                    hesap_adi=ad,
                    ust_hesap_id=ust_id,
                    hesap_seviyesi=seviye,
                    hesap_turu=tur,
                    aktif=True,
                )
                session.add(h)
                session.flush()
                mevcut[kod] = h
                eklenen += 1
        return eklenen

    @staticmethod
    def esleme_sablonlarini_doldur() -> None:
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            for anahtar, aciklama in ESLEME_ANAHTARLARI:
                var = session.scalar(
                    select(MuhasebeHesapEsleme).where(
                        MuhasebeHesapEsleme.firma_id == firma_id,
                        MuhasebeHesapEsleme.anahtar == anahtar,
                    )
                )
                if var is None:
                    session.add(
                        MuhasebeHesapEsleme(
                            firma_id=firma_id,
                            anahtar=anahtar,
                            aciklama=aciklama,
                            hesap_id=None,
                            aktif=True,
                        )
                    )


class HesapPlanService:
    @staticmethod
    def kod_oneki_ile_listele(onek: str, *, limit: int = 400) -> list[dict]:
        """Hesap kodu önekiyle (en az 3 hane) TDHP hesaplarını listeler."""
        yetki_zorunlu("muhasebe_goruntuleme", "goruntuleme")
        onek = (onek or "").strip()
        onek_temiz = "".join(c for c in onek if c.isalnum() or c == ".")
        if len(onek_temiz.replace(".", "")) < 3:
            raise ValueError("Listeden seçmek için en az 3 hane yazın (ör. 120).")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            q = (
                select(HesapPlani)
                .where(
                    HesapPlani.firma_id == firma_id,
                    HesapPlani.aktif.is_(True),
                    HesapPlani.hesap_kodu.like(f"{onek_temiz}%"),
                )
                .order_by(HesapPlani.hesap_kodu)
                .limit(int(limit))
            )
            return [
                {
                    "id": h.id,
                    "hesap_kodu": h.hesap_kodu,
                    "hesap_adi": h.hesap_adi,
                    "hesap_seviyesi": h.hesap_seviyesi,
                    "hesap_turu": h.hesap_turu,
                }
                for h in session.scalars(q).all()
            ]

    @staticmethod
    def listele(*, arama: str = "", sadece_aktif: bool = True) -> list[dict]:
        yetki_zorunlu("muhasebe_goruntuleme", "goruntuleme")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            q = select(HesapPlani).where(HesapPlani.firma_id == firma_id)
            if sadece_aktif:
                q = q.where(HesapPlani.aktif.is_(True))
            if arama.strip():
                a = f"%{arama.strip()}%"
                q = q.where(
                    or_(HesapPlani.hesap_kodu.ilike(a), HesapPlani.hesap_adi.ilike(a))
                )
            q = q.order_by(HesapPlani.hesap_kodu)
            satirlar = []
            for h in session.scalars(q).all():
                borc = decimal(h.borc_toplam)
                alacak = decimal(h.alacak_toplam)
                bakiye = borc - alacak
                satirlar.append(
                    {
                        "id": h.id,
                        "hesap_kodu": h.hesap_kodu,
                        "hesap_adi": h.hesap_adi,
                        "ust_hesap_id": h.ust_hesap_id,
                        "hesap_seviyesi": h.hesap_seviyesi,
                        "hesap_turu": h.hesap_turu,
                        "borc_toplam": borc,
                        "alacak_toplam": alacak,
                        "bakiye": bakiye,
                        "aktif": h.aktif,
                    }
                )
            return satirlar

    @staticmethod
    def getir(hesap_id: int) -> dict | None:
        yetki_zorunlu("muhasebe_goruntuleme", "goruntuleme")
        with get_session() as session:
            h = session.get(HesapPlani, hesap_id)
            if h is None:
                return None
            borc = decimal(h.borc_toplam)
            alacak = decimal(h.alacak_toplam)
            return {
                "id": h.id,
                "hesap_kodu": h.hesap_kodu,
                "hesap_adi": h.hesap_adi,
                "ust_hesap_id": h.ust_hesap_id,
                "hesap_seviyesi": h.hesap_seviyesi,
                "hesap_turu": h.hesap_turu,
                "borc_toplam": borc,
                "alacak_toplam": alacak,
                "bakiye": borc - alacak,
                "aktif": h.aktif,
            }

    @staticmethod
    def ekle(veriler: dict) -> int:
        yazma_zorunlu("muhasebe_fis_olusturma", "yeni_kayit", "duzenleme")
        kod = (veriler.get("hesap_kodu") or "").strip()
        ad = (veriler.get("hesap_adi") or "").strip()
        tur = (veriler.get("hesap_turu") or "").strip()
        if not kod or not ad:
            raise ValueError("Hesap kodu ve adı zorunludur.")
        if tur not in HESAP_TURLERI:
            raise ValueError("Geçersiz hesap türü.")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            var = session.scalar(
                select(HesapPlani).where(
                    HesapPlani.firma_id == firma_id, HesapPlani.hesap_kodu == kod
                )
            )
            if var:
                raise ValueError(f"Bu hesap kodu zaten var: {kod}")
            ust_id = veriler.get("ust_hesap_id")
            seviye = 1
            if ust_id:
                ust = session.get(HesapPlani, int(ust_id))
                if ust is None or ust.firma_id != firma_id:
                    raise ValueError("Üst hesap bulunamadı.")
                seviye = int(ust.hesap_seviyesi) + 1
            h = HesapPlani(
                firma_id=firma_id,
                hesap_kodu=kod,
                hesap_adi=ad,
                ust_hesap_id=int(ust_id) if ust_id else None,
                hesap_seviyesi=int(veriler.get("hesap_seviyesi") or seviye),
                hesap_turu=tur,
                aktif=bool(veriler.get("aktif", True)),
            )
            session.add(h)
            session.flush()
            MuhasebeService._gecmis(
                session, kayit_turu="hesap", kayit_id=h.id, islem="ekle", detay=kod
            )
            return h.id

    @staticmethod
    def guncelle(hesap_id: int, veriler: dict) -> None:
        yazma_zorunlu("muhasebe_fis_duzenleme", "duzenleme")
        with get_session() as session:
            h = session.get(HesapPlani, hesap_id)
            if h is None:
                raise ValueError("Hesap bulunamadı.")
            ad = (veriler.get("hesap_adi") or "").strip()
            tur = (veriler.get("hesap_turu") or h.hesap_turu).strip()
            if ad:
                h.hesap_adi = ad
            if tur in HESAP_TURLERI:
                h.hesap_turu = tur
            if "aktif" in veriler:
                h.aktif = bool(veriler["aktif"])
            if "ust_hesap_id" in veriler:
                ust_id = veriler["ust_hesap_id"]
                h.ust_hesap_id = int(ust_id) if ust_id else None
            if veriler.get("hesap_seviyesi"):
                h.hesap_seviyesi = int(veriler["hesap_seviyesi"])
            h.guncelleme_tarihi = datetime.now()
            MuhasebeService._gecmis(
                session,
                kayit_turu="hesap",
                kayit_id=h.id,
                islem="guncelle",
                detay=h.hesap_kodu,
            )

    @staticmethod
    def pasife_al(hesap_id: int) -> None:
        yazma_zorunlu("muhasebe_fis_duzenleme", "duzenleme")
        with get_session() as session:
            h = session.get(HesapPlani, hesap_id)
            if h is None:
                raise ValueError("Hesap bulunamadı.")
            hareket = session.scalar(
                select(func.count())
                .select_from(MuhasebeFisiSatiri)
                .where(MuhasebeFisiSatiri.hesap_id == hesap_id)
            )
            if (hareket or 0) > 0:
                h.aktif = False
                h.guncelleme_tarihi = datetime.now()
                MuhasebeService._gecmis(
                    session,
                    kayit_turu="hesap",
                    kayit_id=h.id,
                    islem="pasif",
                    detay="Hareketli hesap pasife alındı",
                )
                return
            # Hareket yoksa da Word: doğrudan silme yok — pasife al
            h.aktif = False
            h.guncelleme_tarihi = datetime.now()
            MuhasebeService._gecmis(
                session, kayit_turu="hesap", kayit_id=h.id, islem="pasif"
            )


class MuhasebeFisService:
    @staticmethod
    def _sonraki_fis_no(session, firma_id: int, mali_yil: int) -> str:
        like = f"MF-{mali_yil}-%"
        mevcut = session.scalars(
            select(MuhasebeFisi.fis_no).where(
                MuhasebeFisi.firma_id == firma_id,
                MuhasebeFisi.mali_yil == mali_yil,
                MuhasebeFisi.fis_no.like(like),
            )
        ).all()
        max_n = 0
        for no in mevcut:
            try:
                max_n = max(max_n, int(str(no).split("-")[-1]))
            except ValueError:
                pass
        return f"MF-{mali_yil}-{max_n + 1:05d}"

    @staticmethod
    def listele(
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        durum: str | None = None,
    ) -> list[dict]:
        yetki_zorunlu("muhasebe_goruntuleme", "goruntuleme")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            q = select(MuhasebeFisi).where(MuhasebeFisi.firma_id == firma_id)
            if baslangic:
                q = q.where(MuhasebeFisi.fis_tarihi >= baslangic)
            if bitis:
                q = q.where(MuhasebeFisi.fis_tarihi <= bitis)
            if durum:
                q = q.where(MuhasebeFisi.durum == durum)
            q = q.order_by(MuhasebeFisi.fis_tarihi.desc(), MuhasebeFisi.id.desc())
            return [
                {
                    "id": f.id,
                    "fis_no": f.fis_no,
                    "fis_tarihi": f.fis_tarihi,
                    "fis_turu": f.fis_turu,
                    "aciklama": f.aciklama or "",
                    "belge_no": f.belge_no or "",
                    "durum": f.durum,
                    "toplam_borc": decimal(f.toplam_borc),
                    "toplam_alacak": decimal(f.toplam_alacak),
                    "mali_yil": f.mali_yil,
                }
                for f in session.scalars(q).all()
            ]

    @staticmethod
    def getir(fis_id: int) -> dict | None:
        yetki_zorunlu("muhasebe_goruntuleme", "goruntuleme")
        with get_session() as session:
            f = session.scalar(
                select(MuhasebeFisi)
                .options(selectinload(MuhasebeFisi.satirlar))
                .where(MuhasebeFisi.id == fis_id)
            )
            if f is None:
                return None
            return {
                "id": f.id,
                "fis_no": f.fis_no,
                "fis_tarihi": f.fis_tarihi,
                "fis_turu": f.fis_turu,
                "aciklama": f.aciklama or "",
                "belge_no": f.belge_no or "",
                "durum": f.durum,
                "toplam_borc": decimal(f.toplam_borc),
                "toplam_alacak": decimal(f.toplam_alacak),
                "mali_yil": f.mali_yil,
                "donem_id": f.donem_id,
                "kaynak_turu": f.kaynak_turu,
                "kaynak_id": f.kaynak_id,
                "satirlar": [
                    {
                        "id": s.id,
                        "sira_no": s.sira_no,
                        "hesap_id": s.hesap_id,
                        "hesap_kodu": s.hesap_kodu,
                        "hesap_adi": s.hesap_adi,
                        "aciklama": s.aciklama or "",
                        "borc": decimal(s.borc),
                        "alacak": decimal(s.alacak),
                        "belge_tarihi": s.belge_tarihi,
                        "belge_no": s.belge_no or "",
                    }
                    for s in f.satirlar
                ],
            }

    @staticmethod
    def kaydet(veriler: dict, fis_id: int | None = None, *, otomatik: bool = False) -> int:
        durum = (veriler.get("durum") or "Taslak").strip()
        if durum not in FIS_DURUMLARI:
            raise ValueError("Geçersiz fiş durumu.")
        if not otomatik:
            if fis_id:
                yazma_zorunlu("muhasebe_fis_duzenleme", "duzenleme")
            else:
                yazma_zorunlu("muhasebe_fis_olusturma", "yeni_kayit")
            if durum == "Kesinleşmiş":
                yazma_zorunlu("muhasebe_fis_kesinlestirme", "duzenleme")
        else:
            from database.access import aktif_firma_zorunlu

            aktif_firma_zorunlu()

        fis_turu = (veriler.get("fis_turu") or "").strip()
        if fis_turu not in FIS_TURLERI:
            raise ValueError("Geçersiz fiş türü.")
        fis_tarihi = veriler.get("fis_tarihi")
        if not isinstance(fis_tarihi, date):
            raise ValueError("Fiş tarihi zorunludur.")
        satirlar = veriler.get("satirlar") or []
        if not satirlar:
            raise ValueError("En az bir fiş satırı gerekli.")

        toplam_borc = SIFIR
        toplam_alacak = SIFIR
        temiz_satirlar = []
        for i, s in enumerate(satirlar, start=1):
            borc = decimal(s.get("borc"))
            alacak = decimal(s.get("alacak"))
            if borc < 0 or alacak < 0:
                raise ValueError("Borç/alacak negatif olamaz.")
            if borc > 0 and alacak > 0:
                raise ValueError("Aynı satırda hem borç hem alacak olamaz.")
            if borc == 0 and alacak == 0:
                continue
            hesap_id = int(s["hesap_id"])
            temiz_satirlar.append(
                {
                    "sira_no": i,
                    "hesap_id": hesap_id,
                    "aciklama": (s.get("aciklama") or "").strip() or None,
                    "borc": borc,
                    "alacak": alacak,
                    "belge_tarihi": s.get("belge_tarihi"),
                    "belge_no": (s.get("belge_no") or "").strip() or None,
                }
            )
            toplam_borc += borc
            toplam_alacak += alacak

        if not temiz_satirlar:
            raise ValueError("Geçerli fiş satırı yok.")
        fark = (toplam_borc - toplam_alacak).quantize(IKI)
        if durum == "Kesinleşmiş" and fark != SIFIR:
            raise ValueError(
                f"Borç ve alacak eşit değil (fark: {para_goster(fark)}). "
                "Fiş kesinleştirilemez."
            )

        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            mali_yil = int(veriler.get("mali_yil") or fis_tarihi.year)

            if fis_id:
                fis = session.get(MuhasebeFisi, fis_id)
                if fis is None or fis.firma_id != firma_id:
                    raise ValueError("Fiş bulunamadı.")
                if fis.durum == "Kesinleşmiş":
                    raise AccessError(
                        "Kesinleşmiş fiş doğrudan değiştirilemez. İptal veya ters kayıt kullanın."
                    )
                if fis.durum == "İptal":
                    raise AccessError("İptal edilmiş fiş düzenlenemez.")
                # Eski satırları sil (taslak)
                for eski in list(fis.satirlar):
                    session.delete(eski)
                session.flush()
            else:
                fis = MuhasebeFisi(
                    firma_id=firma_id,
                    donem_id=oturum.period_id,
                    mali_yil=mali_yil,
                    fis_no=MuhasebeFisService._sonraki_fis_no(session, firma_id, mali_yil),
                    fis_tarihi=fis_tarihi,
                    fis_turu=fis_turu,
                    aciklama=(veriler.get("aciklama") or "").strip() or None,
                    belge_no=(veriler.get("belge_no") or "").strip() or None,
                    durum=durum,
                    toplam_borc=toplam_borc,
                    toplam_alacak=toplam_alacak,
                    olusturan_kullanici_id=oturum.user_id,
                )
                session.add(fis)
                session.flush()

            fis.fis_tarihi = fis_tarihi
            fis.fis_turu = fis_turu
            fis.aciklama = (veriler.get("aciklama") or "").strip() or None
            fis.belge_no = (veriler.get("belge_no") or "").strip() or None
            fis.durum = durum
            fis.toplam_borc = toplam_borc
            fis.toplam_alacak = toplam_alacak
            fis.guncelleyen_kullanici_id = oturum.user_id
            fis.guncelleme_tarihi = datetime.now()
            if veriler.get("kaynak_turu"):
                fis.kaynak_turu = veriler["kaynak_turu"]
                fis.kaynak_id = veriler.get("kaynak_id")

            # Yeni fişte satırlar zaten yok; güncellemede eski satırlar silindi
            for s in temiz_satirlar:
                hesap = session.get(HesapPlani, s["hesap_id"])
                if hesap is None or hesap.firma_id != firma_id:
                    raise ValueError("Hesap bulunamadı.")
                if not hesap.aktif:
                    raise ValueError(f"Pasif hesap kullanılamaz: {hesap.hesap_kodu}")
                fis_alt_hesap_zorunlu(hesap.hesap_kodu)
                session.add(
                    MuhasebeFisiSatiri(
                        fis_id=fis.id,
                        firma_id=firma_id,
                        sira_no=s["sira_no"],
                        hesap_id=hesap.id,
                        hesap_kodu=hesap.hesap_kodu,
                        hesap_adi=hesap.hesap_adi,
                        aciklama=s["aciklama"],
                        borc=s["borc"],
                        alacak=s["alacak"],
                        belge_tarihi=s["belge_tarihi"],
                        belge_no=s["belge_no"],
                    )
                )

            if durum == "Kesinleşmiş":
                session.flush()
                MuhasebeFisService._bakiye_uygula(session, fis.id, yon=1)

            MuhasebeService._gecmis(
                session,
                kayit_turu="fis",
                kayit_id=fis.id,
                islem="kaydet" if fis_id else "olustur",
                detay=f"{fis.fis_no} / {durum}",
            )
            return fis.id

    @staticmethod
    def _bakiye_uygula(session, fis_id: int, *, yon: int) -> None:
        """yon=1 kesinleştir, yon=-1 geri al / iptal."""
        fis = session.scalar(
            select(MuhasebeFisi)
            .options(selectinload(MuhasebeFisi.satirlar))
            .where(MuhasebeFisi.id == fis_id)
        )
        if fis is None:
            return
        for s in fis.satirlar:
            hesap = session.get(HesapPlani, s.hesap_id)
            if hesap is None:
                continue
            hesap.borc_toplam = decimal(hesap.borc_toplam) + (decimal(s.borc) * yon)
            hesap.alacak_toplam = decimal(hesap.alacak_toplam) + (decimal(s.alacak) * yon)
            hesap.guncelleme_tarihi = datetime.now()

    @staticmethod
    def iptal(fis_id: int, neden: str = "", *, otomatik: bool = False) -> int | None:
        """Kesinleşmiş fişi iptal eder; tercihen ters kayıt oluşturur. Ters fiş id döner."""
        if not otomatik:
            yazma_zorunlu("muhasebe_fis_iptal", "iptal")
        else:
            from database.access import aktif_firma_zorunlu

            aktif_firma_zorunlu()
        ters_id: int | None = None
        with get_session() as session:
            fis = session.scalar(
                select(MuhasebeFisi)
                .options(selectinload(MuhasebeFisi.satirlar))
                .where(MuhasebeFisi.id == fis_id)
            )
            if fis is None:
                raise ValueError("Fiş bulunamadı.")
            if fis.durum == "İptal":
                raise ValueError("Fiş zaten iptal.")
            if fis.durum == "Taslak":
                fis.durum = "İptal"
                fis.iptal_nedeni = neden or "Taslak iptal"
                fis.kaynak_turu = None
                fis.kaynak_id = None
                MuhasebeService._gecmis(
                    session, kayit_turu="fis", kayit_id=fis.id, islem="iptal", detay=neden
                )
            else:
                # Kesinleşmiş → ters fiş
                MuhasebeFisService._bakiye_uygula(session, fis.id, yon=-1)
                eski_kaynak = f"{fis.kaynak_turu or ''}:{fis.kaynak_id or ''}"
                fis.durum = "İptal"
                fis.iptal_nedeni = (neden or "İptal") + (f" [{eski_kaynak}]" if eski_kaynak != ":" else "")
                # Aynı kaynaktan yeni fiş açılabilsin
                fis.kaynak_turu = None
                fis.kaynak_id = None
                mali_yil = fis.mali_yil
                ters = MuhasebeFisi(
                    firma_id=fis.firma_id,
                    donem_id=oturum.period_id,
                    mali_yil=mali_yil,
                    fis_no=MuhasebeFisService._sonraki_fis_no(session, fis.firma_id, mali_yil),
                    fis_tarihi=date.today(),
                    fis_turu=fis.fis_turu,
                    aciklama=f"Ters kayıt: {fis.fis_no}" + (f" — {neden}" if neden else ""),
                    belge_no=fis.belge_no,
                    durum="Kesinleşmiş",
                    toplam_borc=fis.toplam_alacak,
                    toplam_alacak=fis.toplam_borc,
                    olusturan_kullanici_id=oturum.user_id,
                )
                session.add(ters)
                session.flush()
                fis.ters_fis_id = ters.id
                for s in fis.satirlar:
                    session.add(
                        MuhasebeFisiSatiri(
                            fis_id=ters.id,
                            firma_id=fis.firma_id,
                            sira_no=s.sira_no,
                            hesap_id=s.hesap_id,
                            hesap_kodu=s.hesap_kodu,
                            hesap_adi=s.hesap_adi,
                            aciklama=s.aciklama,
                            borc=s.alacak,
                            alacak=s.borc,
                            belge_tarihi=s.belge_tarihi,
                            belge_no=s.belge_no,
                        )
                    )
                session.flush()
                MuhasebeFisService._bakiye_uygula(session, ters.id, yon=1)
                MuhasebeService._gecmis(
                    session,
                    kayit_turu="fis",
                    kayit_id=fis.id,
                    islem="iptal_ters",
                    detay=f"ters={ters.fis_no}",
                )
                ters_id = int(ters.id)

        from database.deleted_record_service import ENTITY_MUHASEBE_FIS, safe_log_cancel

        if not otomatik:
            safe_log_cancel(
                ENTITY_MUHASEBE_FIS,
                fis_id,
                note=neden or "Muhasebe fişi iptal",
            )
        return ters_id


class MuhasebeRaporService:
    @staticmethod
    def mizan(baslangic: date, bitis: date) -> dict:
        yetki_zorunlu("muhasebe_mizan", "muhasebe_goruntuleme", "goruntuleme")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            hesaplar = session.scalars(
                select(HesapPlani)
                .where(HesapPlani.firma_id == firma_id, HesapPlani.aktif.is_(True))
                .order_by(HesapPlani.hesap_kodu)
            ).all()

            # Dönem hareketleri
            satirlar_q = (
                select(
                    MuhasebeFisiSatiri.hesap_id,
                    func.coalesce(func.sum(MuhasebeFisiSatiri.borc), 0),
                    func.coalesce(func.sum(MuhasebeFisiSatiri.alacak), 0),
                )
                .join(MuhasebeFisi, MuhasebeFisi.id == MuhasebeFisiSatiri.fis_id)
                .where(
                    MuhasebeFisi.firma_id == firma_id,
                    MuhasebeFisi.durum == "Kesinleşmiş",
                    MuhasebeFisi.fis_tarihi >= baslangic,
                    MuhasebeFisi.fis_tarihi <= bitis,
                )
                .group_by(MuhasebeFisiSatiri.hesap_id)
            )
            donem = {hid: (decimal(b), decimal(a)) for hid, b, a in session.execute(satirlar_q)}

            onceki_q = (
                select(
                    MuhasebeFisiSatiri.hesap_id,
                    func.coalesce(func.sum(MuhasebeFisiSatiri.borc), 0),
                    func.coalesce(func.sum(MuhasebeFisiSatiri.alacak), 0),
                )
                .join(MuhasebeFisi, MuhasebeFisi.id == MuhasebeFisiSatiri.fis_id)
                .where(
                    MuhasebeFisi.firma_id == firma_id,
                    MuhasebeFisi.durum == "Kesinleşmiş",
                    MuhasebeFisi.fis_tarihi < baslangic,
                )
                .group_by(MuhasebeFisiSatiri.hesap_id)
            )
            onceki = {hid: (decimal(b), decimal(a)) for hid, b, a in session.execute(onceki_q)}

            satirlar = []
            t_ob = t_oa = t_db = t_da = t_bb = t_ab = SIFIR
            for h in hesaplar:
                ob, oa = onceki.get(h.id, (SIFIR, SIFIR))
                db, da = donem.get(h.id, (SIFIR, SIFIR))
                if ob == 0 and oa == 0 and db == 0 and da == 0:
                    continue
                net_b = (ob + db) - (oa + da)
                bb = net_b if net_b > 0 else SIFIR
                ab = -net_b if net_b < 0 else SIFIR
                satirlar.append(
                    {
                        "hesap_kodu": h.hesap_kodu,
                        "hesap_adi": h.hesap_adi,
                        "onceki_borc": ob,
                        "onceki_alacak": oa,
                        "donem_borc": db,
                        "donem_alacak": da,
                        "borc_bakiyesi": bb,
                        "alacak_bakiyesi": ab,
                    }
                )
                t_ob += ob
                t_oa += oa
                t_db += db
                t_da += da
                t_bb += bb
                t_ab += ab

            dengeli = t_bb == t_ab
            return {
                "satirlar": satirlar,
                "toplamlar": {
                    "onceki_borc": t_ob,
                    "onceki_alacak": t_oa,
                    "donem_borc": t_db,
                    "donem_alacak": t_da,
                    "borc_bakiyesi": t_bb,
                    "alacak_bakiyesi": t_ab,
                },
                "dengeli": dengeli,
            }

    @staticmethod
    def bilanco(bitis: date) -> dict:
        yetki_zorunlu("muhasebe_bilanco", "muhasebe_goruntuleme", "goruntuleme")
        mizan = MuhasebeRaporService.mizan(date(1900, 1, 1), bitis)
        aktif_gruplar: dict[str, list] = {"1": [], "2": []}
        pasif_gruplar: dict[str, list] = {"3": [], "4": [], "5": []}
        grup_adlari = {k: v for k, v, _ in ANA_HESAP_SINIFLARI}

        for s in mizan["satirlar"]:
            kod = s["hesap_kodu"]
            net = s["borc_bakiyesi"] - s["alacak_bakiyesi"]
            if kod.startswith("1"):
                aktif_gruplar["1"].append({**s, "bakiye": net})
            elif kod.startswith("2"):
                aktif_gruplar["2"].append({**s, "bakiye": net})
            elif kod.startswith("3"):
                pasif_gruplar["3"].append({**s, "bakiye": -net})
            elif kod.startswith("4"):
                pasif_gruplar["4"].append({**s, "bakiye": -net})
            elif kod.startswith("5"):
                pasif_gruplar["5"].append({**s, "bakiye": -net})

        def _grp(kod, hesaplar):
            top = sum((h["bakiye"] for h in hesaplar), SIFIR)
            return {
                "kod": kod,
                "ad": grup_adlari.get(kod, kod),
                "toplam": top,
                "hesaplar": hesaplar,
            }

        aktif = [_grp("1", aktif_gruplar["1"]), _grp("2", aktif_gruplar["2"])]
        pasif = [
            _grp("3", pasif_gruplar["3"]),
            _grp("4", pasif_gruplar["4"]),
            _grp("5", pasif_gruplar["5"]),
        ]
        aktif_toplam = sum((g["toplam"] for g in aktif), SIFIR)
        pasif_toplam = sum((g["toplam"] for g in pasif), SIFIR)
        fark = (aktif_toplam - pasif_toplam).quantize(IKI)
        return {
            "aktif": aktif,
            "pasif": pasif,
            "aktif_toplam": aktif_toplam,
            "pasif_toplam": pasif_toplam,
            "fark": fark,
            "dengeli": fark == SIFIR,
        }

    @staticmethod
    def gelir_tablosu(baslangic: date, bitis: date) -> dict:
        yetki_zorunlu("muhasebe_gelir_tablosu", "muhasebe_goruntuleme", "goruntuleme")
        mizan = MuhasebeRaporService.mizan(baslangic, bitis)
        gelir = SIFIR
        gider = SIFIR
        maliyet = SIFIR
        detay = []
        for s in mizan["satirlar"]:
            kod = s["hesap_kodu"]
            # Gelir: alacak ağırlıklı (6), Gider/maliyet: borç (6xx maliyet / 7)
            donem_net = s["donem_alacak"] - s["donem_borc"]
            if kod.startswith("7"):
                maliyet += s["donem_borc"] - s["donem_alacak"]
                detay.append({**s, "kalem": "maliyet", "tutar": s["donem_borc"] - s["donem_alacak"]})
            elif kod.startswith("6"):
                # Basit ayrım: 60x satış benzeri gelir, 62-68 gider
                if kod.startswith("60") or kod.startswith("64") or kod.startswith("67"):
                    gelir += donem_net
                    detay.append({**s, "kalem": "gelir", "tutar": donem_net})
                else:
                    gider += s["donem_borc"] - s["donem_alacak"]
                    detay.append(
                        {
                            **s,
                            "kalem": "gider",
                            "tutar": s["donem_borc"] - s["donem_alacak"],
                        }
                    )

        brut_satislar = gelir
        satis_indirimleri = SIFIR
        net_satislar = brut_satislar - satis_indirimleri
        brut_kar = net_satislar - maliyet
        faaliyet_giderleri = gider
        faaliyet_kar = brut_kar - faaliyet_giderleri
        diger_gelir = SIFIR
        diger_gider = SIFIR
        finansman = SIFIR
        donem_kar = faaliyet_kar + diger_gelir - diger_gider - finansman
        vergiler = SIFIR
        net_kar = donem_kar - vergiler

        return {
            "kalemler": [
                ("Brüt Satışlar", brut_satislar, "gelir"),
                ("Satış İndirimleri ve İadeleri", satis_indirimleri, "gider"),
                ("Net Satışlar", net_satislar, "ara"),
                ("Satışların Maliyeti", maliyet, "gider"),
                ("Brüt Satış Kârı/Zararı", brut_kar, "ara"),
                ("Faaliyet Giderleri", faaliyet_giderleri, "gider"),
                ("Faaliyet Kârı/Zararı", faaliyet_kar, "ara"),
                ("Diğer Gelirler", diger_gelir, "gelir"),
                ("Diğer Giderler", diger_gider, "gider"),
                ("Finansman Giderleri", finansman, "gider"),
                ("Dönem Kârı/Zararı", donem_kar, "ara"),
                ("Vergiler", vergiler, "gider"),
                ("Dönem Net Kârı/Zararı", net_kar, "net"),
            ],
            "net_kar": net_kar,
            "detay": detay,
        }

    @staticmethod
    def excel_aktar(baslik: str, sutunlar: list[str], satirlar: list[list], yol: Path) -> Path:
        yetki_zorunlu("muhasebe_disa_aktarma", "excel_pdf")
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = baslik[:31] or "Rapor"
        ws.append(sutunlar)
        for satir in satirlar:
            ws.append(satir)
        yol.parent.mkdir(parents=True, exist_ok=True)
        wb.save(yol)
        return yol

    @staticmethod
    def pdf_olustur(baslik: str, satirlar: list[str], yol: Path) -> Path:
        """Bağımlılıksız basit metin PDF (Helvetica)."""
        yetki_zorunlu("muhasebe_disa_aktarma", "excel_pdf")
        yol.parent.mkdir(parents=True, exist_ok=True)
        icerik_satirlari = [baslik, ""] + list(satirlar)
        # PDF string escape
        def esc(t: str) -> str:
            return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        y = 800
        content = ["BT", "/F1 10 Tf", "50 800 Td"]
        first = True
        for line in icerik_satirlari:
            safe = esc(line[:120])
            if first:
                content.append(f"({safe}) Tj")
                first = False
            else:
                content.append("0 -14 Td")
                content.append(f"({safe}) Tj")
                y -= 14
                if y < 50:
                    break
        content.append("ET")
        stream = "\n".join(content).encode("latin-1", errors="replace")

        objs = []
        objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
        objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
        objs.append(
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        )
        objs.append(
            f"4 0 obj<< /Length {len(stream)} >>stream\n".encode()
            + stream
            + b"\nendstream\nendobj\n"
        )
        objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj in objs:
            offsets.append(len(out))
            out.extend(obj)
        xref_pos = len(out)
        out.extend(f"xref\n0 {len(offsets)}\n".encode())
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode())
        out.extend(
            f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
        )
        yol.write_bytes(out)
        return yol
