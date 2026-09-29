"""Tahsilat makbuzu — Cari Virman işlemi.

Müşteriden olan alacak ile tedarikçiye olan borç aynı tutarda mahsup edilir:
- müşteri: alacak kaydı (islem_turu "Virman Tahsilat", belge {CVR}-T), açık borçlarına FIFO
- tedarikçi: alacak kaydı (islem_turu "Virman Ödeme", belge {CVR}-O), açık borçlarına FIFO;
  kapanmayan kısım tedarikçi ödemesindeki gibi alacak satırı olarak kalır
Kasa, banka, POS veya kredi kartı hareketi oluşmaz. Makbuz ve iki cari hareket tek veritabanı
işleminde yazılır; düzenleme ve iptal iki tarafı birlikte geri alır (aynı belge numaralarıyla).
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.finans import CariVirmanMakbuzu
from database.turkce_normalize import turkce_normalize

BELGE_ONEK = "CVR"
ISLEM_TAHSILAT = "Virman Tahsilat"
ISLEM_ODEME = "Virman Ödeme"
VIRMAN_METNI = (
    "Belirtilen tutar, müşteri cari hesabından tedarikçi cari hesabına virman yoluyla mahsup edilmiştir."
)
_TL = "TRY"


def musteri_mi(cari_turu: str | None) -> bool:
    return "musteri" in turkce_normalize(cari_turu or "")


def tedarikci_mi(cari_turu: str | None) -> bool:
    return "tedarikci" in turkce_normalize(cari_turu or "")


def _tutar(deger) -> Decimal:
    try:
        tutar = Decimal(str(deger)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as hata:
        raise ValueError("Virman tutarı geçerli bir sayı olmalıdır.") from hata
    if tutar <= 0:
        raise ValueError("Virman tutarı sıfırdan büyük olmalıdır.")
    return tutar


def _cari_id(deger, alan: str) -> int:
    try:
        cari_id = int(deger)
    except (TypeError, ValueError) as hata:
        raise ValueError(f"{alan} seçin.") from hata
    if cari_id <= 0:
        raise ValueError(f"{alan} seçin.")
    return cari_id


class CariVirmanMakbuzService:
    _hazir_motor = None

    @classmethod
    def tablo_hazirla(cls) -> None:
        """Eski firma veritabanlarında tablo yoksa ekler (yalnız CREATE TABLE; mevcut veriye dokunmaz)."""
        import database.database as veritabani

        motor = veritabani.engine
        if motor is None or motor is cls._hazir_motor:
            return
        CariVirmanMakbuzu.__table__.create(bind=motor, checkfirst=True)
        # İfade tabanlı indeks yansıtılamadığı için checkfirst güvenilmez; IF NOT EXISTS kullanılır
        with motor.begin() as baglanti:
            baglanti.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_cari_virman_makbuz_no ON cari_virman_makbuzlari "
                    "(upper(trim(makbuz_no))) WHERE makbuz_no IS NOT NULL AND trim(makbuz_no) <> ''"
                )
            )
        cls._hazir_motor = motor

    # ─── Okuma ──────────────────────────────────────────────────
    @staticmethod
    def _carileri_bagla(session, kayitlar) -> None:
        idler = {k.musteri_id for k in kayitlar} | {k.tedarikci_id for k in kayitlar}
        cariler = {c.id: c for c in session.scalars(select(Cari).where(Cari.id.in_(idler))).all()} if idler else {}
        for k in kayitlar:
            k.musteri = cariler.get(k.musteri_id)
            k.tedarikci = cariler.get(k.tedarikci_id)

    @classmethod
    def getir(cls, virman_id) -> CariVirmanMakbuzu | None:
        cls.tablo_hazirla()
        with get_session() as session:
            kayit = session.get(CariVirmanMakbuzu, int(virman_id))
            if kayit is not None:
                cls._carileri_bagla(session, [kayit])
            return kayit

    @classmethod
    def belge_no_ile(cls, belge_no: str) -> CariVirmanMakbuzu | None:
        """CVR-… belge numarası veya bağlı -T / -O evrak numarasıyla makbuz."""
        belge_no = (belge_no or "").strip()
        if not belge_no:
            return None
        cls.tablo_hazirla()
        with get_session() as session:
            kayit = session.scalar(
                select(CariVirmanMakbuzu).where(
                    or_(
                        CariVirmanMakbuzu.belge_no == belge_no,
                        CariVirmanMakbuzu.tahsilat_belge_no == belge_no,
                        CariVirmanMakbuzu.odeme_belge_no == belge_no,
                    )
                )
            )
            if kayit is not None:
                cls._carileri_bagla(session, [kayit])
            return kayit

    @classmethod
    def listele(
        cls,
        limit: int = 300,
        *,
        arama: str | None = None,
        baslangic: date | None = None,
        bitis: date | None = None,
        durum: str | None = None,
    ) -> list[CariVirmanMakbuzu]:
        cls.tablo_hazirla()
        with get_session() as session:
            q = select(CariVirmanMakbuzu).order_by(CariVirmanMakbuzu.tarih.desc(), CariVirmanMakbuzu.id.desc())
            if baslangic:
                q = q.where(CariVirmanMakbuzu.tarih >= baslangic)
            if bitis:
                q = q.where(CariVirmanMakbuzu.tarih <= bitis)
            if durum:
                q = q.where(CariVirmanMakbuzu.durum == durum)
            aranan = turkce_normalize(arama or "").strip()
            if not aranan:
                q = q.limit(limit)
            kayitlar = list(session.scalars(q).all())
            cls._carileri_bagla(session, kayitlar)
        if aranan:
            def _eslesir(k) -> bool:
                parcalar = [k.makbuz_no, k.belge_no, k.tahsilat_belge_no, k.odeme_belge_no, k.aciklama, "cari virman"]
                for c in (k.musteri, k.tedarikci):
                    parcalar += [getattr(c, "cari_kodu", ""), getattr(c, "unvan", "")]
                return aranan in turkce_normalize(" ".join(str(x or "") for x in parcalar))

            kayitlar = [k for k in kayitlar if _eslesir(k)][:limit]
        return kayitlar

    # ─── Kayıt ──────────────────────────────────────────────────
    @classmethod
    def kaydet(cls, veriler: dict) -> CariVirmanMakbuzu:
        return cls._kaydet(veriler, virman_id=None)

    @classmethod
    def guncelle(cls, virman_id, veriler: dict) -> CariVirmanMakbuzu:
        """Aynı belge ve evrak numaralarıyla yeniden yazar; eski iki cari hareket önce geri alınır."""
        return cls._kaydet(veriler, virman_id=int(virman_id))

    @classmethod
    def _kaydet(cls, veriler: dict, virman_id: int | None) -> CariVirmanMakbuzu:
        yazma_zorunlu("finans_duzenleme")
        cls.tablo_hazirla()
        otomatik = bool(veriler.get("makbuz_no_otomatik")) and virman_id is None
        son_hata = None
        for deneme in range(8):
            try:
                kayit_id = cls._yaz(veriler, otomatik=otomatik, virman_id=virman_id)
                return cls.getir(kayit_id)
            except IntegrityError as hata:
                metin = str(getattr(hata, "orig", hata))
                if "makbuz_no" in metin and not otomatik:
                    no = (veriler.get("makbuz_no") or "").strip()
                    raise ValueError(f"{no} numaralı makbuz bu firmada zaten var. Farklı bir numara girin.") from hata
                son_hata = hata
            except OperationalError as hata:
                if "locked" not in str(hata).lower():
                    raise
                son_hata = hata
            time.sleep(0.05 * (deneme + 1))
        raise ValueError(
            "Cari virman kaydedilemedi: başka bir kullanıcıyla numara çakışması sürüyor. Tekrar deneyin."
        ) from son_hata

    @staticmethod
    def _belge_no_sonraki(session, tarih: date) -> str:
        onek = f"{BELGE_ONEK}-{tarih.year}-"
        en_buyuk = 0
        for no in session.scalars(
            select(CariVirmanMakbuzu.belge_no).where(CariVirmanMakbuzu.belge_no.like(f"{onek}%"))
        ).all():
            try:
                en_buyuk = max(en_buyuk, int(no[len(onek):]))
            except ValueError:
                continue
        return f"{onek}{en_buyuk + 1:04d}"

    @staticmethod
    def _para_birimi_engeli(session, cari: Cari) -> str | None:
        """TL dışı hareketi olan caride virman yapılmaz: kur farkı / döviz mahsubu için güvenli kural yok."""
        for model in (CariIslem, SatisHareketi):
            birim = session.scalar(
                select(model.para_birimi)
                .where(model.cari_id == cari.id, func.upper(func.coalesce(model.para_birimi, _TL)) != _TL)
                .limit(1)
            )
            if birim:
                return (
                    f"{cari.cari_kodu} - {cari.unvan} carisinde {birim} para birimli hareket var. "
                    "Cari virman yalnız TL ile çalışan cariler arasında yapılabilir; farklı para birimleri "
                    "için güvenli bir mahsup/kur kuralı tanımlı değil. İşlem kaydedilmedi."
                )
        return None

    @classmethod
    def _yaz(cls, veriler: dict, *, otomatik: bool, virman_id: int | None) -> int:
        from database.finans_service import FinansService
        from database.sube_service import SubeService

        tarih = veriler.get("tarih")
        if not isinstance(tarih, date):
            raise ValueError("Tarih geçersiz.")
        if tarih > date.today():
            raise ValueError("Tarih gelecek olamaz.")
        musteri_id = _cari_id(veriler.get("musteri_id"), "Tahsilat yapılan müşteriyi")
        tedarikci_id = _cari_id(veriler.get("tedarikci_id"), "Ödeme yapılan tedarikçiyi")
        if musteri_id == tedarikci_id:
            raise ValueError("Müşteri ve tedarikçi aynı cari olamaz.")
        tutar = _tutar(veriler.get("tutar"))
        makbuz_no = (veriler.get("makbuz_no") or "").strip() or None
        if makbuz_no and len(makbuz_no) > 50:
            raise ValueError("Makbuz numarası en fazla 50 karakter olabilir.")
        aciklama = (veriler.get("aciklama") or "").strip() or None

        with get_session() as session:
            sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            musteri = session.get(Cari, musteri_id)
            tedarikci = session.get(Cari, tedarikci_id)
            if musteri is None or musteri.is_deleted:
                raise ValueError("Tahsilat yapılan müşteri bulunamadı.")
            if tedarikci is None or tedarikci.is_deleted:
                raise ValueError("Ödeme yapılan tedarikçi bulunamadı.")
            if not musteri_mi(musteri.cari_turu):
                raise ValueError(f"{musteri.cari_kodu} - {musteri.unvan} bir müşteri carisi değil.")
            if not tedarikci_mi(tedarikci.cari_turu):
                raise ValueError(f"{tedarikci.cari_kodu} - {tedarikci.unvan} bir tedarikçi carisi değil.")
            for cari in (musteri, tedarikci):
                engel = cls._para_birimi_engeli(session, cari)
                if engel:
                    raise ValueError(engel)

            kayit = None
            if virman_id:
                kayit = session.get(CariVirmanMakbuzu, int(virman_id))
                if kayit is None:
                    raise ValueError("Cari virman makbuzu bulunamadı.")
                if kayit.durum == "IPTAL":
                    raise ValueError("İptal edilmiş cari virman düzenlenemez.")
                cls._cari_etkilerini_geri_al(session, kayit)

            if otomatik:
                makbuz_no = FinansService._makbuz_no_sonraki(session)
            elif makbuz_no and FinansService._makbuz_no_var(
                session, makbuz_no, haric_virman_id=kayit.id if kayit else None
            ):
                raise ValueError(f"{makbuz_no} numaralı makbuz bu firmada zaten var. Farklı bir numara girin.")

            if kayit is None:
                belge_no = cls._belge_no_sonraki(session, tarih)
                kayit = CariVirmanMakbuzu(
                    belge_no=belge_no,
                    tahsilat_belge_no=f"{belge_no}-T",
                    odeme_belge_no=f"{belge_no}-O",
                    durum="AÇIK",
                )
                session.add(kayit)
            kayit.sube_id = sube_id
            kayit.makbuz_no = makbuz_no
            kayit.tarih = tarih
            kayit.tutar = tutar
            kayit.musteri_id = musteri_id
            kayit.tedarikci_id = tedarikci_id
            kayit.aciklama = aciklama
            cls._cari_etkilerini_yaz(session, kayit, musteri, tedarikci)
            session.flush()
            return int(kayit.id)

    @staticmethod
    def _cari_etkilerini_yaz(session, kayit: CariVirmanMakbuzu, musteri: Cari, tedarikci: Cari) -> None:
        from database.cari_service import CariService

        tutar = Decimal(str(kayit.tutar))
        metin = f"Cari virman {kayit.makbuz_no or kayit.belge_no}"
        if kayit.aciklama:
            metin = f"{metin} · {kayit.aciklama}"

        kayit.musteri_kapanan = CariService._alacak_uygula(
            session, musteri.id, tutar, kayit.tahsilat_belge_no, kayit.tarih, kaynak_tur="VIRMAN"
        )["kapanan"]
        session.add(
            CariIslem(
                cari_id=musteri.id,
                tarih=kayit.tarih,
                islem_turu=ISLEM_TAHSILAT,
                belge_no=kayit.tahsilat_belge_no,
                aciklama=f"{metin} → {tedarikci.cari_kodu} {tedarikci.unvan}"[:500],
                borc=Decimal("0"),
                alacak=tutar,
                karsi_cari_id=tedarikci.id,
                para_birimi=_TL,
            )
        )

        kayit.tedarikci_kapanan = CariService._alacak_uygula(
            session, tedarikci.id, tutar, kayit.odeme_belge_no, kayit.tarih, kaynak_tur="VIRMAN"
        )["kapanan"]
        session.add(
            CariIslem(
                cari_id=tedarikci.id,
                tarih=kayit.tarih,
                islem_turu=ISLEM_ODEME,
                belge_no=kayit.odeme_belge_no,
                aciklama=f"{metin} ← {musteri.cari_kodu} {musteri.unvan}"[:500],
                borc=Decimal("0"),
                alacak=tutar,
                karsi_cari_id=musteri.id,
                para_birimi=_TL,
            )
        )

    @staticmethod
    def _cari_etkilerini_geri_al(session, kayit: CariVirmanMakbuzu) -> None:
        from database.acik_kalem_service import AcikKalemService
        from database.cari_service import CariService

        for belge_no, cari_id, kapanan in (
            (kayit.tahsilat_belge_no, kayit.musteri_id, kayit.musteri_kapanan),
            (kayit.odeme_belge_no, kayit.tedarikci_id, kayit.tedarikci_kapanan),
        ):
            if AcikKalemService.belge_kayitli_mi(session, cari_id, belge_no):
                # Tahsis kayıtlı belge: kapattıkları ve avansı denetim iziyle geri alınır
                CariService._aciklara_geri_al(session, cari_id, Decimal(str(kayit.tutar)), belge_no)
                for islem in session.scalars(select(CariIslem).where(CariIslem.belge_no == belge_no)).all():
                    session.delete(islem)
                session.flush()
                continue
            for sh in session.scalars(
                select(SatisHareketi).where(SatisHareketi.cari_id == cari_id, SatisHareketi.belge_no == belge_no)
            ).all():
                session.delete(sh)
            for islem in session.scalars(select(CariIslem).where(CariIslem.belge_no == belge_no)).all():
                session.delete(islem)
            session.flush()
            kapanan = Decimal(str(kapanan or 0))
            if kapanan > 0:
                CariService._aciklara_geri_al(session, cari_id, kapanan, belge_no, yalniz_borc_satirlari=True)
        kayit.musteri_kapanan = Decimal("0")
        kayit.tedarikci_kapanan = Decimal("0")
        session.flush()

    # ─── İptal ──────────────────────────────────────────────────
    @classmethod
    def iptal(cls, virman_id) -> None:
        """İki cari hareketi birlikte geri alır; makbuz ve numarası İPTAL olarak kalır."""
        yazma_zorunlu("finans_duzenleme", "iptal")
        cls.tablo_hazirla()
        with get_session() as session:
            kayit = session.get(CariVirmanMakbuzu, int(virman_id))
            if kayit is None:
                raise ValueError("Cari virman makbuzu bulunamadı.")
            if kayit.durum == "IPTAL":
                raise ValueError("Cari virman makbuzu zaten iptal.")
            cls._cari_etkilerini_geri_al(session, kayit)
            kayit.durum = "IPTAL"
            session.flush()
