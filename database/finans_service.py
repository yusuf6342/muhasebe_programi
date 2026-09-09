from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import calendar

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import (
    BANKA_ALT_HESAP_TURLERI,
    KK_CEKIM_TURLERI,
    KK_MAX_TAKSIT,
    POS_KART_TIPLERI,
    POS_MAX_TAKSIT,
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
    PosTaksitKomisyon,
    PosValorKaydi,
)

HESAP_TURLERI = ("KASA", "BANKA", "KREDİ KARTI")

# Bakiyeyi artıran hareketler
GIRIS_HAREKETLERI = (
    "FATURA TAHSİLATI",
    "CARİ TAHSİLAT",
    "KASA GİRİŞ",
    "BANKA GİRİŞ",
    "VIRMAN GİRİŞ",
    "AÇILIŞ",
    "KASADAN BANKAYA YATAN",
    "ALINAN HAVALE",
    "BANKADAN NAKİT (KASA)",
    "BANKA VİRMAN GİRİŞ",
    "POS TAHSİLAT",
    "POS → KMH AKTARIM (KMH)",
    "KK ÖDEME",  # kartla ödeme → KK borcu artar
)

# Bakiyeyi azaltan hareketler
CIKIS_HAREKETLERI = (
    "FATURA ÖDEMESİ",
    "CARİ ÖDEME",
    "KASA ÇIKIŞ",
    "BANKA ÇIKIŞ",
    "VIRMAN ÇIKIŞ",
    "KASADAN BANKAYA (KASA)",
    "GÖNDERİLEN HAVALE",
    "BANKADAN NAKİT ÇEKİLEN",
    "BANKA VİRMAN ÇIKIŞ",
    "POS KOMİSYON",
    "POS → KMH AKTARIM (POS)",
    "KK EKSTRE ÖDEME",  # kart borcunu kapatma
)

MEVDUAT_EVRAK_TURLERI = (
    "KASADAN BANKAYA YATAN",
    "ALINAN HAVALE",
    "GÖNDERİLEN HAVALE",
    "BANKADAN NAKİT ÇEKİLEN",
)

# Kasadan bankaya yatırılabilecek banka alt hesap türleri
KBY_HEDEF_ALT_TURLER = ("MEVDUAT", "KMH", "KREDI_KARTI", "VADELI")

POS_VALOR_SAATI = "08:00"


def _decimal(deger, alan="Tutar", minimum=None) -> Decimal:
    try:
        sonuc = Decimal(str(deger).strip().replace(",", "."))
    except (InvalidOperation, AttributeError) as hata:
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from hata
    if minimum is not None and sonuc < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return sonuc


class FinansService:
    @staticmethod
    def varsayilanlari_hazirla():
        varsayilanlar = (
            ("ANA KASA", "KASA"),
            ("BANKA HESABI", "BANKA"),
            ("KREDİ KARTI POS", "KREDİ KARTI"),
        )
        with get_session() as session:
            mevcut = set(session.scalars(select(FinansHesabi.hesap_adi)).all())
            for ad, tur in varsayilanlar:
                if ad not in mevcut:
                    session.add(FinansHesabi(hesap_adi=ad, hesap_turu=tur))

    @staticmethod
    def hesaplar(hesap_turu=None, aktif_only=True):
        with get_session() as session:
            q = select(FinansHesabi).options(selectinload(FinansHesabi.hareketler))
            if aktif_only:
                q = q.where(FinansHesabi.aktif.is_(True))
            if hesap_turu:
                q = q.where(FinansHesabi.hesap_turu == hesap_turu)
            q = q.order_by(FinansHesabi.hesap_adi)
            return list(session.scalars(q).all())

    @staticmethod
    def hesap_getir(hesap_id):
        with get_session() as session:
            return session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )

    @staticmethod
    def hareket_isareti(hareket_turu: str) -> int:
        tur = (hareket_turu or "").strip().upper()
        if tur in {t.upper() for t in GIRIS_HAREKETLERI} or "TAHSİLAT" in tur or tur.endswith("GİRİŞ"):
            return 1
        if tur in {t.upper() for t in CIKIS_HAREKETLERI} or "ÖDEME" in tur or tur.endswith("ÇIKIŞ"):
            return -1
        return 1

    @staticmethod
    def bakiye(hesap) -> Decimal:
        toplam = Decimal(str(hesap.acilis_bakiyesi or 0))
        for h in hesap.hareketler or []:
            toplam += Decimal(str(h.tutar or 0)) * FinansService.hareket_isareti(h.hareket_turu)
        return toplam

    @staticmethod
    def hesap_kaydet(veriler: dict) -> FinansHesabi:
        hesap_adi = (veriler.get("hesap_adi") or "").strip()
        hesap_turu = (veriler.get("hesap_turu") or "").strip().upper()
        if not hesap_adi:
            raise ValueError("Hesap adı zorunludur.")
        if hesap_turu not in HESAP_TURLERI:
            raise ValueError("Geçersiz hesap türü.")
        acilis = _decimal(veriler.get("acilis_bakiyesi") or 0, "Açılış bakiyesi", Decimal("0"))

        with get_session() as session:
            hesap_id = veriler.get("hesap_id")
            hesap = None
            if hesap_id:
                hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.id == int(hesap_id)))
            if not hesap:
                ayni = session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi))
                if ayni:
                    raise ValueError("Bu hesap adı zaten kayıtlı.")
                hesap = FinansHesabi(hesap_adi=hesap_adi, hesap_turu=hesap_turu)
                session.add(hesap)
            else:
                ayni = session.scalar(
                    select(FinansHesabi).where(
                        FinansHesabi.hesap_adi == hesap_adi,
                        FinansHesabi.id != hesap.id,
                    )
                )
                if ayni:
                    raise ValueError("Bu hesap adı zaten kayıtlı.")
                hesap.hesap_adi = hesap_adi
                hesap.hesap_turu = hesap_turu

            hesap.acilis_bakiyesi = acilis
            hesap.banka_adi = (veriler.get("banka_adi") or "").strip() or None
            hesap.sube = (veriler.get("sube") or "").strip() or None
            hesap.iban = (veriler.get("iban") or "").strip() or None
            hesap.aciklama = (veriler.get("aciklama") or "").strip() or None
            if "aktif" in veriler:
                hesap.aktif = bool(veriler["aktif"])
            session.flush()
            hesap_id = hesap.id

        return FinansService.hesap_getir(hesap_id)

    @staticmethod
    def hesap_pasif_yap(hesap_id):
        with get_session() as session:
            hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.id == int(hesap_id)))
            if not hesap:
                raise ValueError("Hesap bulunamadı.")
            hesap.aktif = False

    @staticmethod
    def hareketler(hesap_id=None, hesap_turu=None, limit=500):
        with get_session() as session:
            q = (
                select(FinansHareketi)
                .options(selectinload(FinansHareketi.hesap))
                .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
            )
            if hesap_id:
                q = q.where(FinansHareketi.hesap_id == int(hesap_id))
            elif hesap_turu:
                q = q.join(FinansHesabi).where(FinansHesabi.hesap_turu == hesap_turu)
            if limit:
                q = q.limit(limit)
            return list(session.scalars(q).all())

    @staticmethod
    def fatura_tahsilatini_geri_al(session, belge_no):
        session.execute(
            delete(FinansHareketi).where(
                FinansHareketi.belge_no == belge_no,
                FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
            )
        )

    @staticmethod
    def fatura_tahsilati(session, belge_no, tarih, tutar, odeme_sekli, hesap_adi):
        FinansService.hareket_ekle(session, belge_no, tarih, tutar, "FATURA TAHSİLATI", hesap_adi, odeme_sekli)

    @staticmethod
    def fatura_odemesini_geri_al(session, belge_no):
        session.execute(
            delete(FinansHareketi).where(
                FinansHareketi.belge_no == belge_no,
                FinansHareketi.hareket_turu.in_(("FATURA ÖDEMESİ", "CARİ ÖDEME")),
            )
        )

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
        session.add(
            FinansHareketi(
                hesap_id=hesap.id,
                tarih=tarih,
                hareket_turu=hareket_turu,
                belge_no=belge_no,
                tutar=tutar,
                aciklama=aciklama,
            )
        )

    # --- Banka ana kartı ---

    @staticmethod
    def banka_kartlari(aktif_only=True):
        with get_session() as session:
            q = (
                select(BankaKarti)
                .options(
                    selectinload(BankaKarti.alt_hesaplar).selectinload(FinansHesabi.hareketler)
                )
                .order_by(BankaKarti.banka_adi, BankaKarti.sube)
            )
            if aktif_only:
                q = q.where(BankaKarti.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def banka_adi_listesi():
        """Kayıtlı banka adları (seçim listesi)."""
        with get_session() as session:
            adlar = session.scalars(
                select(BankaKarti.banka_adi)
                .where(BankaKarti.aktif.is_(True))
                .order_by(BankaKarti.banka_adi)
            ).all()
        # Benzersiz, sıralı
        return sorted({(a or "").strip() for a in adlar if (a or "").strip()}, key=str.casefold)

    @staticmethod
    def banka_karti_getir(kart_id):
        with get_session() as session:
            return session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(kart_id))
                .options(
                    selectinload(BankaKarti.alt_hesaplar).selectinload(FinansHesabi.hareketler),
                    selectinload(BankaKarti.pos_taksit_komisyonlari),
                )
            )

    @staticmethod
    def _alt_hesap_adi(banka_adi: str, alt_etiket: str) -> str:
        return f"{banka_adi} — {alt_etiket}"

    @staticmethod
    def banka_alt_hesap(kart, alt_tur: str):
        for h in kart.alt_hesaplar or []:
            if (h.alt_hesap_turu or "").upper() == alt_tur.upper():
                return h
        return None

    @staticmethod
    def banka_bakiyeler(kart) -> dict[str, Decimal]:
        """{MEVDUAT: Decimal, KMH: ..., ...}"""
        sonuc = {}
        for kod, _etiket in BANKA_ALT_HESAP_TURLERI:
            hesap = FinansService.banka_alt_hesap(kart, kod)
            sonuc[kod] = FinansService.bakiye(hesap) if hesap else Decimal("0")
        return sonuc

    @staticmethod
    def banka_karti_kaydet(veriler: dict) -> BankaKarti:
        banka_adi = (veriler.get("banka_adi") or "").strip()
        if not banka_adi:
            raise ValueError("Banka adı zorunludur.")
        sube = (veriler.get("sube") or "").strip() or None
        hesap_no = (veriler.get("hesap_no") or "").strip() or None
        iban = (veriler.get("iban") or "").strip().replace(" ", "").upper() or None
        aciklama = (veriler.get("aciklama") or "").strip() or None

        with get_session() as session:
            kart_id = veriler.get("kart_id")
            kart = None
            if kart_id:
                kart = session.scalar(
                    select(BankaKarti)
                    .where(BankaKarti.id == int(kart_id))
                    .options(selectinload(BankaKarti.alt_hesaplar))
                )
            if not kart:
                kart = BankaKarti(banka_adi=banka_adi)
                session.add(kart)
                session.flush()
            else:
                eski_ad = kart.banka_adi
                kart.banka_adi = banka_adi
                # Alt hesap adlarını banka adı değişince güncelle
                if eski_ad != banka_adi:
                    for kod, etiket in BANKA_ALT_HESAP_TURLERI:
                        for h in kart.alt_hesaplar:
                            if (h.alt_hesap_turu or "").upper() == kod:
                                yeni_ad = FinansService._alt_hesap_adi(banka_adi, etiket)
                                cakisma = session.scalar(
                                    select(FinansHesabi).where(
                                        FinansHesabi.hesap_adi == yeni_ad,
                                        FinansHesabi.id != h.id,
                                    )
                                )
                                if not cakisma:
                                    h.hesap_adi = yeni_ad
                                h.banka_adi = banka_adi

            kart.sube = sube
            kart.hesap_no = hesap_no
            kart.iban = iban
            kart.aciklama = aciklama
            kart.kk_komisyon_orani = _decimal(
                veriler.get("kk_komisyon_orani") or 0, "KK komisyon %", Decimal("0")
            )
            kart.banka_karti_komisyon_orani = _decimal(
                veriler.get("banka_karti_komisyon_orani") or 0, "Banka kartı komisyon %", Decimal("0")
            )
            try:
                valor_gun = int(str(veriler.get("pos_valor_gun") or 1).strip())
            except ValueError as hata:
                raise ValueError("POS valör günü tam sayı olmalıdır.") from hata
            if valor_gun < 0:
                raise ValueError("POS valör günü negatif olamaz.")
            kart.pos_valor_gun = valor_gun
            if "aktif" in veriler:
                kart.aktif = bool(veriler["aktif"])
            session.flush()

            # POS taksit komisyon oranları (1-12)
            if "pos_taksit_komisyonlari" in veriler:
                oranlar = veriler.get("pos_taksit_komisyonlari") or {}
                mevcut = {
                    r.taksit_sayisi: r
                    for r in session.scalars(
                        select(PosTaksitKomisyon).where(
                            PosTaksitKomisyon.banka_karti_id == kart.id
                        )
                    ).all()
                }
                for n in range(1, POS_MAX_TAKSIT + 1):
                    oran = _decimal(
                        oranlar.get(n, oranlar.get(str(n), 0)) or 0,
                        f"{n}. taksit komisyon %",
                        Decimal("0"),
                    )
                    if oran < 0 or oran > 100:
                        raise ValueError(f"{n}. taksit komisyon oranı 0-100 arasında olmalıdır.")
                    if n in mevcut:
                        mevcut[n].komisyon_orani = oran
                    else:
                        session.add(
                            PosTaksitKomisyon(
                                banka_karti_id=kart.id,
                                taksit_sayisi=n,
                                komisyon_orani=oran,
                            )
                        )

            mevcut_turler = {(h.alt_hesap_turu or "").upper() for h in kart.alt_hesaplar}
            for kod, etiket in BANKA_ALT_HESAP_TURLERI:
                if kod in mevcut_turler:
                    for h in kart.alt_hesaplar:
                        if (h.alt_hesap_turu or "").upper() == kod:
                            h.banka_adi = banka_adi
                            h.sube = sube
                            h.iban = iban if kod == "MEVDUAT" else h.iban
                            h.aktif = True
                    continue
                hesap_adi = FinansService._alt_hesap_adi(banka_adi, etiket)
                # Benzersiz ad
                baz = hesap_adi
                sira = 2
                while session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi)):
                    hesap_adi = f"{baz} ({sira})"
                    sira += 1
                finans_turu = "KREDİ KARTI" if kod == "KREDI_KARTI" else "BANKA"
                session.add(
                    FinansHesabi(
                        hesap_adi=hesap_adi,
                        hesap_turu=finans_turu,
                        acilis_bakiyesi=Decimal("0"),
                        banka_adi=banka_adi,
                        sube=sube,
                        iban=iban if kod == "MEVDUAT" else None,
                        banka_karti_id=kart.id,
                        alt_hesap_turu=kod,
                        aktif=True,
                    )
                )
            session.flush()
            kart_id = kart.id

        return FinansService.banka_karti_getir(kart_id)

    @staticmethod
    def banka_karti_pasif_yap(kart_id):
        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(kart_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            kart.aktif = False
            for h in kart.alt_hesaplar:
                h.aktif = False

    @staticmethod
    def banka_manuel_hareket(hesap_id, tarih, tutar, yon, aciklama=None, belge_no=None):
        """yon: 'giris' | 'cikis' — alt hesap işlem menüsü."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        yon = (yon or "").strip().lower()
        if yon not in ("giris", "cikis"):
            raise ValueError("İşlem yönü giriş veya çıkış olmalıdır.")
        with get_session() as session:
            hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.id == int(hesap_id)))
            if not hesap:
                raise ValueError("Hesap bulunamadı.")
            if hesap.hesap_turu == "KASA":
                tur = "KASA GİRİŞ" if yon == "giris" else "KASA ÇIKIŞ"
            else:
                tur = "BANKA GİRİŞ" if yon == "giris" else "BANKA ÇIKIŞ"
            belge = (belge_no or "").strip() or f"BH{hesap.id}-{tarih.strftime('%Y%m%d')}"
            session.add(
                FinansHareketi(
                    hesap_id=hesap.id,
                    tarih=tarih,
                    hareket_turu=tur,
                    belge_no=belge,
                    tutar=tutar,
                    aciklama=aciklama,
                )
            )
            session.flush()
            return hesap.id

    # --- Mevduat evrakları ---

    @staticmethod
    def _finans_belge_no(session, on_ek: str) -> str:
        yil = date.today().year
        like = f"{on_ek}-{yil}-%"
        mevcut = session.scalars(
            select(FinansHareketi.belge_no).where(FinansHareketi.belge_no.like(like))
        ).all()
        sira = 1
        for no in mevcut:
            try:
                sira = max(sira, int(str(no).rsplit("-", 1)[-1]) + 1)
            except ValueError:
                pass
        return f"{on_ek}-{yil}-{sira:04d}"

    @staticmethod
    def _hesap_bul(session, hesap_id: int) -> FinansHesabi:
        hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.id == int(hesap_id)))
        if not hesap or not hesap.aktif:
            raise ValueError("Hesap bulunamadı veya pasif.")
        return hesap

    @staticmethod
    def _aciklama_dekont_ayir(aciklama: str | None) -> tuple[str, str | None]:
        acik = (aciklama or "").strip()
        ayir = " | Dekont: "
        if ayir in acik:
            base, dek = acik.rsplit(ayir, 1)
            return base.strip(), (dek.strip() or None)
        return acik, None

    @staticmethod
    def _finans_hareketlerini_sil(session, belge_no: str) -> int:
        hareketler = list(
            session.scalars(
                select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
            ).all()
        )
        for h in hareketler:
            session.delete(h)
        return len(hareketler)

    @staticmethod
    def _havale_cari_geri_al(session, belge_no: str) -> None:
        """AHV/GHV cari etkisini geri alır."""
        from database.cari_service import CariService
        from database.models.cari import CariIslem, SatisHareketi

        islemler = list(
            session.scalars(select(CariIslem).where(CariIslem.belge_no == belge_no)).all()
        )
        if not islemler:
            return
        for islem in islemler:
            tutar = Decimal(str(islem.alacak or 0)) + Decimal(str(islem.borc or 0))
            if (islem.islem_turu or "") == "Tahsilat":
                CariService._aciklara_geri_al(session, islem.cari_id, tutar, belge_no)
            elif (islem.islem_turu or "") == "Ödeme":
                from database.models.cari import Cari as CariModel

                cari = session.get(CariModel, islem.cari_id)
                sh = session.scalar(
                    select(SatisHareketi).where(
                        SatisHareketi.belge_no == belge_no,
                        SatisHareketi.cari_id == islem.cari_id,
                    )
                )
                if (cari is not None) and (cari.cari_turu or "") == "Tedarikçi":
                    # Fazla-ödeme kredi satırı varsa sil; FIFO uygulanan kısmı geri aç.
                    if sh is not None:
                        session.delete(sh)
                    CariService._aciklara_geri_al(session, islem.cari_id, tutar, belge_no)
                elif sh is not None:
                    if Decimal(str(sh.kalan_acik_tutar)) < Decimal(str(sh.satis_tutari)):
                        raise ValueError(
                            "Bu havaleye bağlı cari açık kısmen kapanmış; güncellenemez."
                        )
                    session.delete(sh)
                else:
                    CariService._aciklara_geri_al(session, islem.cari_id, tutar, belge_no)
            session.delete(islem)

    @staticmethod
    def banka_islem_fis_getir(belge_no: str) -> dict:
        """KBY/BNC/AHV/GHV/BVR fiş detayı (güncelleme için)."""
        belge_no = (belge_no or "").strip()
        if not belge_no:
            raise ValueError("Belge numarası gerekli.")
        with get_session() as session:
            hareketler = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.belge_no == belge_no)
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.id)
                ).all()
            )
            if not hareketler:
                raise ValueError("Fiş bulunamadı.")
            turler = {h.hareket_turu for h in hareketler}
            acik_ham = hareketler[0].aciklama or ""
            acik, dekont = FinansService._aciklama_dekont_ayir(acik_ham)
            tarih = hareketler[0].tarih
            tutar = Decimal(str(hareketler[0].tutar))

            def _hesap_bilgi(h):
                if not h or not h.hesap:
                    return None, None, None
                return h.hesap.id, h.hesap.banka_karti_id, h.hesap.hesap_adi

            if "KASADAN BANKAYA YATAN" in turler:
                banka_h = next(h for h in hareketler if h.hareket_turu == "KASADAN BANKAYA YATAN")
                kasa_h = next(
                    (h for h in hareketler if h.hareket_turu == "KASADAN BANKAYA (KASA)"),
                    None,
                )
                kasa_id, _, kasa_ad = _hesap_bilgi(kasa_h)
                banka_id, banka_kart, banka_ad = _hesap_bilgi(banka_h)
                # Dekont öncesi açıklamada varsayılan metni temizle
                if acik.startswith(f"{kasa_ad} →") if kasa_ad else False:
                    pass
                return {
                    "tur": "kby",
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": tutar,
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "kasa_id": kasa_id,
                    "banka_hesap_id": banka_id,
                    "banka_karti_id": banka_kart,
                }

            if "BANKADAN NAKİT ÇEKİLEN" in turler:
                banka_h = next(h for h in hareketler if h.hareket_turu == "BANKADAN NAKİT ÇEKİLEN")
                kasa_h = next(
                    (h for h in hareketler if h.hareket_turu == "BANKADAN NAKİT (KASA)"),
                    None,
                )
                kasa_id, _, _ = _hesap_bilgi(kasa_h)
                banka_id, banka_kart, _ = _hesap_bilgi(banka_h)
                return {
                    "tur": "bnc",
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": tutar,
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "kasa_id": kasa_id,
                    "banka_hesap_id": banka_id,
                    "banka_karti_id": banka_kart,
                }

            if "ALINAN HAVALE" in turler or "GÖNDERİLEN HAVALE" in turler:
                from database.models.cari import Cari, CariIslem

                banka_h = hareketler[0]
                banka_id, banka_kart, _ = _hesap_bilgi(banka_h)
                islem = session.scalar(
                    select(CariIslem).where(CariIslem.belge_no == belge_no)
                )
                cari_id = islem.cari_id if islem else None
                cari_etiket = ""
                if cari_id:
                    cari = session.get(Cari, cari_id)
                    if cari:
                        cari_etiket = f"{cari.cari_kodu} - {cari.unvan}"
                # EFT/HAVALE önekini açıklamadan ayır (virman değil ama tutarlılık)
                for onek in ("EFT | ", "HAVALE | ", "EFT: ", "HAVALE: "):
                    if acik.upper().startswith(onek.upper()[:3]) and acik.startswith(onek[:1]):
                        break
                fis_tur = "ahv" if "ALINAN HAVALE" in turler else "ghv"
                return {
                    "tur": fis_tur,
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": tutar,
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "banka_hesap_id": banka_id,
                    "banka_karti_id": banka_kart,
                    "cari_id": cari_id,
                    "cari_etiket": cari_etiket,
                }

            if "BANKA VİRMAN ÇIKIŞ" in turler:
                cikis = next(h for h in hareketler if h.hareket_turu == "BANKA VİRMAN ÇIKIŞ")
                giris = next(
                    (h for h in hareketler if h.hareket_turu == "BANKA VİRMAN GİRİŞ"),
                    None,
                )
                cikis_id, cikis_kart, _ = _hesap_bilgi(cikis)
                giris_id, giris_kart, _ = _hesap_bilgi(giris)
                ust = acik.upper()
                if ust.startswith("EFT"):
                    belge_turu = "EFT"
                    if acik.startswith("EFT | "):
                        acik = acik[6:].strip()
                    elif acik.upper().startswith("EFT:"):
                        acik = acik.split(":", 1)[-1].strip()
                elif ust.startswith("HAVALE"):
                    belge_turu = "HAVALE"
                    if acik.startswith("HAVALE | "):
                        acik = acik[9:].strip()
                    elif acik.upper().startswith("HAVALE:"):
                        acik = acik.split(":", 1)[-1].strip()
                else:
                    belge_turu = "HAVALE"
                return {
                    "tur": "bvr",
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": tutar,
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "belge_turu": belge_turu,
                    "cikis_hesap_id": cikis_id,
                    "giris_hesap_id": giris_id,
                    "cikis_banka_karti_id": cikis_kart,
                    "giris_banka_karti_id": giris_kart,
                }

            raise ValueError("Bu belge türü banka işlem menüsünden güncellenemez.")

    @staticmethod
    def _cari_tahsilat_satiri(session, cari_id, tarih, tutar, belge_no, hesap_adi, aciklama):
        from database.cari_service import CariService
        from database.models.cari import Cari, CariIslem

        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        CariService._aciklara_uygula(session, cari.id, tutar)
        session.add(
            CariIslem(
                cari_id=cari.id,
                tarih=tarih,
                islem_turu="Tahsilat",
                belge_no=belge_no,
                aciklama=aciklama or "Alınan havale",
                borc=Decimal("0"),
                alacak=tutar,
                hesap_adi=hesap_adi,
            )
        )

    @staticmethod
    def _cari_odeme_satiri(session, cari_id, tarih, tutar, belge_no, hesap_adi, aciklama):
        from database.cari_service import CariService
        from database.models.cari import Cari, CariIslem, SatisHareketi

        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        if (cari.cari_turu or "") == "Tedarikçi":
            # Tedarikçi ödemesi defterde ALACAK (borç azaltır); fazlası açık alacak (negatif kalan).
            kalan = CariService._aciklara_uygula(session, cari.id, tutar)
            if kalan > 0:
                session.add(
                    SatisHareketi(
                        cari_id=cari.id,
                        satis_tarihi=tarih,
                        belge_no=belge_no,
                        satis_tutari=Decimal("0"),
                        kalan_acik_tutar=-kalan,
                    )
                )
            session.add(
                CariIslem(
                    cari_id=cari.id,
                    tarih=tarih,
                    islem_turu="Ödeme",
                    belge_no=belge_no,
                    aciklama=aciklama or "Gönderilen havale",
                    borc=Decimal("0"),
                    alacak=tutar,
                    hesap_adi=hesap_adi,
                )
            )
        else:
            session.add(
                SatisHareketi(
                    cari_id=cari.id,
                    satis_tarihi=tarih,
                    belge_no=belge_no,
                    satis_tutari=tutar,
                    kalan_acik_tutar=tutar,
                )
            )
            session.add(
                CariIslem(
                    cari_id=cari.id,
                    tarih=tarih,
                    islem_turu="Ödeme",
                    belge_no=belge_no,
                    aciklama=aciklama or "Gönderilen havale",
                    borc=tutar,
                    alacak=Decimal("0"),
                    hesap_adi=hesap_adi,
                )
            )

    @staticmethod
    def _kby_hedef_uygun_mu(hesap: FinansHesabi) -> bool:
        """Mevduat / KMH / kredi kartı / vadeli (ve klasik BANKA) hesaplara yatırma."""
        tur = (hesap.hesap_turu or "").upper()
        if tur not in ("BANKA", "KREDİ KARTI"):
            return False
        alt = (hesap.alt_hesap_turu or "").strip().upper()
        if not alt:
            # Eski bağımsız banka hesabı
            return True
        if alt in KBY_HEDEF_ALT_TURLER:
            return True
        return alt.startswith("VADELI")

    @staticmethod
    def banka_yatirim_hesaplari(banka_karti_id=None):
        """Kasadan yatırma hedefi: seçilen bankanın uygun alt hesapları."""
        with get_session() as session:
            q = (
                select(FinansHesabi)
                .options(selectinload(FinansHesabi.hareketler))
                .where(
                    FinansHesabi.aktif.is_(True),
                    FinansHesabi.hesap_turu.in_(("BANKA", "KREDİ KARTI")),
                )
                .order_by(FinansHesabi.hesap_adi)
            )
            if banka_karti_id:
                q = q.where(FinansHesabi.banka_karti_id == int(banka_karti_id))
            hesaplar = list(session.scalars(q).all())
            return [h for h in hesaplar if FinansService._kby_hedef_uygun_mu(h)]

    @staticmethod
    def kasadan_bankaya_yatan(
        kasa_hesap_id,
        banka_hesap_id,
        tarih,
        tutar,
        aciklama=None,
        dekont_no=None,
        belge_no=None,
    ) -> str:
        """Kasadan çıkış + banka hesabına (mevduat/KMH/KK/vadeli) giriş."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            if belge_no:
                mevcut = session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).first()
                if not mevcut:
                    raise ValueError("Güncellenecek fiş bulunamadı.")
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            kasa = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(kasa_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            banka = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(banka_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not kasa or not kasa.aktif:
                raise ValueError("Kasa bulunamadı veya pasif.")
            if not banka or not banka.aktif:
                raise ValueError("Banka hesabı bulunamadı veya pasif.")
            if (kasa.hesap_turu or "").upper() != "KASA":
                raise ValueError("Kaynak hesap bir kasa olmalıdır.")
            if not FinansService._kby_hedef_uygun_mu(banka):
                raise ValueError(
                    "Hedef hesap mevduat, KMH, kredi kartı veya vadeli hesap olmalıdır."
                )
            kasa_bak = FinansService.bakiye(kasa)
            if kasa_bak < tutar:
                raise ValueError(
                    f"Kasa bakiyesi yetersiz. Bakiye {_fmt(kasa_bak)}, tutar {_fmt(tutar)}."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "KBY")
            acik = aciklama or f"{kasa.hesap_adi} → {banka.hesap_adi}"
            dekont = (dekont_no or "").strip()
            if dekont:
                acik = f"{acik} | Dekont: {dekont}"
            session.add(
                FinansHareketi(
                    hesap_id=kasa.id,
                    tarih=tarih,
                    hareket_turu="KASADAN BANKAYA (KASA)",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=banka.id,
                    tarih=tarih,
                    hareket_turu="KASADAN BANKAYA YATAN",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belgeno

    @staticmethod
    def kasadan_bankaya_yatan_listele(limit=300):
        """KBY fişleri (banka tarafı satırı + eşleşen kasa)."""
        with get_session() as session:
            banka_satirlar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hareket_turu == "KASADAN BANKAYA YATAN")
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                    .limit(limit)
                ).all()
            )
            if not banka_satirlar:
                return []
            belge_nos = {h.belge_no for h in banka_satirlar}
            kasa_satirlar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(
                        FinansHareketi.hareket_turu == "KASADAN BANKAYA (KASA)",
                        FinansHareketi.belge_no.in_(belge_nos),
                    )
                    .options(selectinload(FinansHareketi.hesap))
                ).all()
            )
            kasa_map = {h.belge_no: h for h in kasa_satirlar}
            sonuc = []
            for h in banka_satirlar:
                kasa_h = kasa_map.get(h.belge_no)
                sonuc.append({
                    "belge_no": h.belge_no,
                    "tarih": h.tarih,
                    "tutar": Decimal(str(h.tutar)),
                    "aciklama": h.aciklama or "",
                    "kasa": kasa_h.hesap.hesap_adi if kasa_h and kasa_h.hesap else "—",
                    "banka_hesap": h.hesap.hesap_adi if h.hesap else "—",
                    "banka_karti_id": h.hesap.banka_karti_id if h.hesap else None,
                })
            return sonuc

    @staticmethod
    def alinan_havale(
        banka_hesap_id,
        tarih,
        tutar,
        cari_id=None,
        aciklama=None,
        dekont_no=None,
        belge_no=None,
    ) -> str:
        """Banka hesabına giriş; gönderen cari zorunlu (tahsilat)."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if not cari_id:
            raise ValueError("Alınan havale için gönderen cari seçimi zorunludur.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            if belge_no:
                mevcut = session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).first()
                if not mevcut:
                    raise ValueError("Güncellenecek fiş bulunamadı.")
                FinansService._havale_cari_geri_al(session, belge_no)
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            banka = FinansService._hesap_bul(session, banka_hesap_id)
            if not FinansService._kby_hedef_uygun_mu(banka):
                raise ValueError(
                    "Hesap mevduat, KMH, kredi kartı veya vadeli hesap olmalıdır."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "AHV")
            acik = aciklama or "Alınan havale"
            dekont = (dekont_no or "").strip()
            if dekont:
                acik = f"{acik} | Dekont: {dekont}"
            session.add(
                FinansHareketi(
                    hesap_id=banka.id,
                    tarih=tarih,
                    hareket_turu="ALINAN HAVALE",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            FinansService._cari_tahsilat_satiri(
                session, cari_id, tarih, tutar, belgeno, banka.hesap_adi, acik
            )
            session.flush()
            return belgeno

    @staticmethod
    def gonderilen_havale(
        banka_hesap_id,
        tarih,
        tutar,
        cari_id=None,
        aciklama=None,
        dekont_no=None,
        belge_no=None,
    ) -> str:
        """Banka hesabından çıkış; alıcı cari zorunlu (ödeme)."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if not cari_id:
            raise ValueError("Gönderilen havale için alıcı cari seçimi zorunludur.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            if belge_no:
                mevcut = session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).first()
                if not mevcut:
                    raise ValueError("Güncellenecek fiş bulunamadı.")
                FinansService._havale_cari_geri_al(session, belge_no)
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            banka = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(banka_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not banka or not banka.aktif:
                raise ValueError("Banka hesabı bulunamadı veya pasif.")
            if not FinansService._kby_hedef_uygun_mu(banka):
                raise ValueError(
                    "Hesap mevduat, KMH, kredi kartı veya vadeli hesap olmalıdır."
                )
            banka_bak = FinansService.bakiye(banka)
            if banka_bak < tutar:
                raise ValueError(
                    f"Banka hesap bakiyesi yetersiz. Bakiye {_fmt(banka_bak)}, "
                    f"tutar {_fmt(tutar)}."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "GHV")
            acik = aciklama or "Gönderilen havale"
            dekont = (dekont_no or "").strip()
            if dekont:
                acik = f"{acik} | Dekont: {dekont}"
            session.add(
                FinansHareketi(
                    hesap_id=banka.id,
                    tarih=tarih,
                    hareket_turu="GÖNDERİLEN HAVALE",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            FinansService._cari_odeme_satiri(
                session, cari_id, tarih, tutar, belgeno, banka.hesap_adi, acik
            )
            session.flush()
            return belgeno

    @staticmethod
    def _havale_listele(hareket_turu: str, limit=300):
        """AHV / GHV fiş listesi (banka satırı + cari)."""
        from database.models.cari import Cari, CariIslem

        with get_session() as session:
            satirlar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hareket_turu == hareket_turu)
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                    .limit(limit)
                ).all()
            )
            if not satirlar:
                return []
            belge_nos = {h.belge_no for h in satirlar}
            cari_map: dict[str, str] = {}
            rows = session.execute(
                select(CariIslem.belge_no, Cari.cari_kodu, Cari.unvan)
                .join(Cari, Cari.id == CariIslem.cari_id)
                .where(CariIslem.belge_no.in_(belge_nos))
                .order_by(CariIslem.id.desc())
            ).all()
            for belge_no, kod, unvan in rows:
                if belge_no not in cari_map:
                    cari_map[belge_no] = f"{kod} - {unvan}"
            sonuc = []
            for h in satirlar:
                sonuc.append({
                    "belge_no": h.belge_no,
                    "tarih": h.tarih,
                    "tutar": Decimal(str(h.tutar)),
                    "aciklama": h.aciklama or "",
                    "cari": cari_map.get(h.belge_no, "—"),
                    "banka_hesap": h.hesap.hesap_adi if h.hesap else "—",
                    "banka_karti_id": h.hesap.banka_karti_id if h.hesap else None,
                })
            return sonuc

    @staticmethod
    def alinan_havale_listele(limit=300):
        return FinansService._havale_listele("ALINAN HAVALE", limit)

    @staticmethod
    def gonderilen_havale_listele(limit=300):
        return FinansService._havale_listele("GÖNDERİLEN HAVALE", limit)

    @staticmethod
    def banka_hesaplari_arasi_virman(
        kaynak_hesap_id,
        hedef_hesap_id,
        tarih,
        tutar,
        aciklama=None,
        belge_turu="HAVALE",
        dekont_no=None,
        belge_no=None,
    ) -> str:
        """Çıkış banka hesabından giriş banka hesabına virman (EFT / Havale)."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if int(kaynak_hesap_id) == int(hedef_hesap_id):
            raise ValueError("Çıkış ve giriş hesabı aynı olamaz.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        tur = (belge_turu or "HAVALE").strip().upper()
        if tur not in ("EFT", "HAVALE"):
            raise ValueError("Belge türü EFT veya Havale olmalıdır.")
        with get_session() as session:
            if belge_no:
                mevcut = session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).first()
                if not mevcut:
                    raise ValueError("Güncellenecek fiş bulunamadı.")
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            kaynak = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(kaynak_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            hedef = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hedef_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not kaynak or not kaynak.aktif:
                raise ValueError("Çıkış hesabı bulunamadı veya pasif.")
            if not hedef or not hedef.aktif:
                raise ValueError("Giriş hesabı bulunamadı veya pasif.")
            if not FinansService._kby_hedef_uygun_mu(kaynak):
                raise ValueError(
                    "Çıkış hesabı mevduat, KMH, kredi kartı veya vadeli olmalıdır."
                )
            if not FinansService._kby_hedef_uygun_mu(hedef):
                raise ValueError(
                    "Giriş hesabı mevduat, KMH, kredi kartı veya vadeli olmalıdır."
                )
            kaynak_bak = FinansService.bakiye(kaynak)
            if kaynak_bak < tutar:
                raise ValueError(
                    f"Çıkış hesabı bakiyesi yetersiz. Bakiye {_fmt(kaynak_bak)}, "
                    f"tutar {_fmt(tutar)}."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "BVR")
            acik = aciklama or f"{tur}: {kaynak.hesap_adi} → {hedef.hesap_adi}"
            if tur not in acik.upper():
                acik = f"{tur} | {acik}"
            dekont = (dekont_no or "").strip()
            if dekont:
                acik = f"{acik} | Dekont: {dekont}"
            session.add(
                FinansHareketi(
                    hesap_id=kaynak.id,
                    tarih=tarih,
                    hareket_turu="BANKA VİRMAN ÇIKIŞ",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=hedef.id,
                    tarih=tarih,
                    hareket_turu="BANKA VİRMAN GİRİŞ",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belgeno

    @staticmethod
    def bankalar_arasi_virman_listele(limit=300):
        """BVR fişleri (çıkış + giriş hesap eşlemesi)."""
        with get_session() as session:
            cikislar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hareket_turu == "BANKA VİRMAN ÇIKIŞ")
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                    .limit(limit)
                ).all()
            )
            if not cikislar:
                return []
            belge_nos = {h.belge_no for h in cikislar}
            girisler = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(
                        FinansHareketi.hareket_turu == "BANKA VİRMAN GİRİŞ",
                        FinansHareketi.belge_no.in_(belge_nos),
                    )
                    .options(selectinload(FinansHareketi.hesap))
                ).all()
            )
            giris_map = {h.belge_no: h for h in girisler}
            sonuc = []
            for c in cikislar:
                g = giris_map.get(c.belge_no)
                acik = c.aciklama or ""
                ust = acik.upper()
                if ust.startswith("EFT"):
                    belge_turu = "EFT"
                elif ust.startswith("HAVALE"):
                    belge_turu = "HAVALE"
                elif "EFT" in ust:
                    belge_turu = "EFT"
                elif "HAVALE" in ust:
                    belge_turu = "HAVALE"
                else:
                    belge_turu = "—"
                sonuc.append({
                    "belge_no": c.belge_no,
                    "tarih": c.tarih,
                    "tutar": Decimal(str(c.tutar)),
                    "aciklama": acik,
                    "belge_turu": belge_turu,
                    "cikis_hesap": c.hesap.hesap_adi if c.hesap else "—",
                    "giris_hesap": g.hesap.hesap_adi if g and g.hesap else "—",
                })
            return sonuc

    @staticmethod
    def banka_mevduat_hesaplari(haric_hesap_id=None):
        """Virman hedefi için diğer banka/mevduat hesapları."""
        with get_session() as session:
            q = (
                select(FinansHesabi)
                .where(
                    FinansHesabi.aktif.is_(True),
                    FinansHesabi.hesap_turu.in_(("BANKA", "KREDİ KARTI")),
                )
                .order_by(FinansHesabi.hesap_adi)
            )
            if haric_hesap_id:
                q = q.where(FinansHesabi.id != int(haric_hesap_id))
            return list(session.scalars(q).all())

    @staticmethod
    def bankadan_nakit_cekilen(
        banka_hesap_id,
        kasa_hesap_id,
        tarih,
        tutar,
        aciklama=None,
        dekont_no=None,
        belge_no=None,
    ) -> str:
        """Banka hesabından (mevduat/KMH/KK/vadeli) çıkış + kasaya giriş."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            if belge_no:
                mevcut = session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).first()
                if not mevcut:
                    raise ValueError("Güncellenecek fiş bulunamadı.")
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            banka = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(banka_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            kasa = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(kasa_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not banka or not banka.aktif:
                raise ValueError("Banka hesabı bulunamadı veya pasif.")
            if not kasa or not kasa.aktif:
                raise ValueError("Kasa bulunamadı veya pasif.")
            if (kasa.hesap_turu or "").upper() != "KASA":
                raise ValueError("Hedef hesap bir kasa olmalıdır.")
            if not FinansService._kby_hedef_uygun_mu(banka):
                raise ValueError(
                    "Kaynak hesap mevduat, KMH, kredi kartı veya vadeli hesap olmalıdır."
                )
            banka_bak = FinansService.bakiye(banka)
            if banka_bak < tutar:
                raise ValueError(
                    f"Banka hesap bakiyesi yetersiz. Bakiye {_fmt(banka_bak)}, "
                    f"tutar {_fmt(tutar)}."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "BNC")
            acik = aciklama or f"{banka.hesap_adi} → {kasa.hesap_adi}"
            dekont = (dekont_no or "").strip()
            if dekont:
                acik = f"{acik} | Dekont: {dekont}"
            session.add(
                FinansHareketi(
                    hesap_id=banka.id,
                    tarih=tarih,
                    hareket_turu="BANKADAN NAKİT ÇEKİLEN",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=kasa.id,
                    tarih=tarih,
                    hareket_turu="BANKADAN NAKİT (KASA)",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belgeno

    @staticmethod
    def bankadan_nakit_cekilen_listele(limit=300):
        """BNC fişleri (banka çıkış satırı + eşleşen kasa)."""
        with get_session() as session:
            banka_satirlar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hareket_turu == "BANKADAN NAKİT ÇEKİLEN")
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                    .limit(limit)
                ).all()
            )
            if not banka_satirlar:
                return []
            belge_nos = {h.belge_no for h in banka_satirlar}
            kasa_satirlar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(
                        FinansHareketi.hareket_turu == "BANKADAN NAKİT (KASA)",
                        FinansHareketi.belge_no.in_(belge_nos),
                    )
                    .options(selectinload(FinansHareketi.hesap))
                ).all()
            )
            kasa_map = {h.belge_no: h for h in kasa_satirlar}
            sonuc = []
            for h in banka_satirlar:
                kasa_h = kasa_map.get(h.belge_no)
                sonuc.append({
                    "belge_no": h.belge_no,
                    "tarih": h.tarih,
                    "tutar": Decimal(str(h.tutar)),
                    "aciklama": h.aciklama or "",
                    "kasa": kasa_h.hesap.hesap_adi if kasa_h and kasa_h.hesap else "—",
                    "banka_hesap": h.hesap.hesap_adi if h.hesap else "—",
                    "banka_karti_id": h.hesap.banka_karti_id if h.hesap else None,
                })
            return sonuc

    @staticmethod
    def mevduat_hareketleri(mevduat_hesap_id, limit=500):
        """Mevduat hesabının tüm hareketleri (giriş/çıkış/bakiye + cari)."""
        from database.models.cari import Cari, CariIslem

        with get_session() as session:
            hesap = session.scalar(
                select(FinansHesabi).where(FinansHesabi.id == int(mevduat_hesap_id))
            )
            if not hesap:
                return []
            acilis = Decimal(str(hesap.acilis_bakiyesi or 0))

            # Bakiye için eskiden yeniye
            tum = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hesap_id == int(mevduat_hesap_id))
                    .order_by(FinansHareketi.tarih.asc(), FinansHareketi.id.asc())
                ).all()
            )
            belge_nolar = {h.belge_no for h in tum if h.belge_no}
            cari_map: dict[str, str] = {}
            if belge_nolar:
                satirlar = session.execute(
                    select(CariIslem.belge_no, Cari.cari_kodu, Cari.unvan)
                    .join(Cari, Cari.id == CariIslem.cari_id)
                    .where(CariIslem.belge_no.in_(belge_nolar))
                    .order_by(CariIslem.id.desc())
                ).all()
                for belge_no, kod, unvan in satirlar:
                    if belge_no not in cari_map:
                        cari_map[belge_no] = f"{kod} - {unvan}"

            bakiye = acilis
            sonuc_eski_yeni = []
            for har in tum:
                isaret = FinansService.hareket_isareti(har.hareket_turu)
                giris = Decimal(str(har.tutar)) if isaret > 0 else Decimal("0")
                cikis = Decimal(str(har.tutar)) if isaret < 0 else Decimal("0")
                bakiye = bakiye + giris - cikis
                sonuc_eski_yeni.append({
                    "id": har.id,
                    "tarih": har.tarih,
                    "hareket_turu": har.hareket_turu,
                    "belge_no": har.belge_no,
                    "cari": cari_map.get(har.belge_no, ""),
                    "tutar": Decimal(str(har.tutar)),
                    "giris": giris,
                    "cikis": cikis,
                    "bakiye": bakiye,
                    "aciklama": har.aciklama or "",
                })

            # Listede yeniler üstte
            sonuc_eski_yeni.reverse()
            if limit:
                return sonuc_eski_yeni[:limit]
            return sonuc_eski_yeni

    # --- POS tahsilat / valör → KMH ---

    @staticmethod
    def pos_taksit_komisyonlari(banka_karti_id) -> dict[int, Decimal]:
        """{taksit_sayisi: oran} — eksik taksitler 0."""
        with get_session() as session:
            satirlar = session.scalars(
                select(PosTaksitKomisyon).where(
                    PosTaksitKomisyon.banka_karti_id == int(banka_karti_id)
                )
            ).all()
            sonuc = {n: Decimal("0") for n in range(1, POS_MAX_TAKSIT + 1)}
            for s in satirlar:
                if 1 <= int(s.taksit_sayisi) <= POS_MAX_TAKSIT:
                    sonuc[int(s.taksit_sayisi)] = Decimal(str(s.komisyon_orani or 0))
            # Tabloda yoksa tek çekim (1) için eski kk_komisyon_orani yedek
            if sonuc[1] == 0:
                kart = session.scalar(
                    select(BankaKarti).where(BankaKarti.id == int(banka_karti_id))
                )
                if kart and Decimal(str(kart.kk_komisyon_orani or 0)) > 0:
                    sonuc[1] = Decimal(str(kart.kk_komisyon_orani or 0))
            return sonuc

    @staticmethod
    def _pos_komisyon_orani(kart: BankaKarti, kart_tipi: str, taksit_sayisi: int = 1) -> Decimal:
        tip = (kart_tipi or "").upper()
        if tip == "BANKA_KARTI":
            return Decimal(str(kart.banka_karti_komisyon_orani or 0))
        # Kredi kartı: taksit tablosu
        n = int(taksit_sayisi or 1)
        if n < 1:
            n = 1
        if n > POS_MAX_TAKSIT:
            n = POS_MAX_TAKSIT
        for r in kart.pos_taksit_komisyonlari or []:
            if int(r.taksit_sayisi) == n:
                return Decimal(str(r.komisyon_orani or 0))
        # Yedek: tek çekim için eski alan
        if n == 1:
            return Decimal(str(kart.kk_komisyon_orani or 0))
        return Decimal("0")

    @staticmethod
    def pos_tahsilat(
        banka_karti_id,
        tarih,
        brut_tutar,
        kart_tipi="KREDI_KARTI",
        cari_id=None,
        aciklama=None,
        taksit_sayisi=1,
        referans_no=None,
        belge_no=None,
    ) -> dict:
        """
        POS'a brüt giriş, taksit komisyonuna göre banka masrafı; net valörde KMH'ye aktarılır.
        Kredi kartı taksit: 1-12; komisyon banka kartındaki taksit oran tablosundan.
        """
        brut = _decimal(brut_tutar, "Tahsilat tutarı", Decimal("0.01"))
        tip = (kart_tipi or "KREDI_KARTI").strip().upper()
        if tip not in {k for k, _ in POS_KART_TIPLERI}:
            raise ValueError("Kart tipi kredi kartı veya banka kartı olmalıdır.")
        try:
            n = int(str(taksit_sayisi).strip() or "1")
        except ValueError as hata:
            raise ValueError("Taksit sayısı tam sayı olmalıdır.") from hata
        if tip == "KREDI_KARTI" and (n < 1 or n > POS_MAX_TAKSIT):
            raise ValueError(f"POS taksit sayısı 1-{POS_MAX_TAKSIT} arasında olmalıdır.")
        if tip == "BANKA_KARTI":
            n = 1
        if tip == "KREDI_KARTI" and not cari_id:
            raise ValueError("Kredi kartı POS tahsilatı için cari seçimi zorunludur.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")

        with get_session() as session:
            if belge_no:
                eski = session.scalar(
                    select(PosValorKaydi).where(PosValorKaydi.belge_no == belge_no)
                )
                if not eski:
                    raise ValueError("Güncellenecek POS tahsilat fişi bulunamadı.")
                if (eski.durum or "") != "BEKLIYOR":
                    raise ValueError("Valöre aktarılmış POS tahsilatı güncellenemez.")
                FinansService._havale_cari_geri_al(session, belge_no)
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.delete(eski)
                session.flush()

            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(
                    selectinload(BankaKarti.alt_hesaplar),
                    selectinload(BankaKarti.pos_taksit_komisyonlari),
                )
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            pos = next((h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "POS"), None)
            kmh = next((h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "KMH"), None)
            if not pos or not kmh:
                raise ValueError("POS veya KMH hesabı eksik — banka kartını kaydedin.")

            oran = FinansService._pos_komisyon_orani(kart, tip, n)
            if oran < 0 or oran > 100:
                raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
            komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            net = brut - komisyon
            if net < 0:
                raise ValueError("Komisyon tutarı brüt tutardan büyük olamaz.")

            valor_gun = int(kart.pos_valor_gun or 1)
            valor_tarihi = tarih + timedelta(days=valor_gun)
            belgeno = belge_no or FinansService._finans_belge_no(session, "POS")
            tip_etiket = dict(POS_KART_TIPLERI).get(tip, tip)
            taksit_metin = "Tek çekim" if n == 1 else f"{n} taksit"
            acik = aciklama or f"POS tahsilat ({tip_etiket} / {taksit_metin})"
            ref = (referans_no or "").strip()
            if ref:
                acik = f"{acik} | Ref: {ref}"

            session.add(
                FinansHareketi(
                    hesap_id=pos.id,
                    tarih=tarih,
                    hareket_turu="POS TAHSİLAT",
                    belge_no=belgeno,
                    tutar=brut,
                    aciklama=acik,
                )
            )
            if komisyon > 0:
                session.add(
                    FinansHareketi(
                        hesap_id=pos.id,
                        tarih=tarih,
                        hareket_turu="POS KOMİSYON",
                        belge_no=belgeno,
                        tutar=komisyon,
                        aciklama=f"Komisyon %{oran:g} ({taksit_metin})",
                    )
                )
            if cari_id:
                FinansService._cari_tahsilat_satiri(
                    session, cari_id, tarih, brut, belgeno, pos.hesap_adi, acik
                )

            kayit = PosValorKaydi(
                banka_karti_id=kart.id,
                pos_hesap_id=pos.id,
                kmh_hesap_id=kmh.id,
                belge_no=belgeno,
                tahsilat_tarihi=tarih,
                valor_tarihi=valor_tarihi,
                valor_saati=POS_VALOR_SAATI,
                kart_tipi=tip,
                taksit_sayisi=n,
                brut_tutar=brut,
                komisyon_orani=oran,
                komisyon_tutari=komisyon,
                net_tutar=net,
                cari_id=int(cari_id) if cari_id else None,
                durum="BEKLIYOR",
                aciklama=acik,
            )
            session.add(kayit)
            session.flush()
            return {
                "belge_no": belgeno,
                "brut": brut,
                "komisyon": komisyon,
                "komisyon_orani": oran,
                "net": net,
                "taksit_sayisi": n,
                "valor_tarihi": valor_tarihi,
                "valor_saati": POS_VALOR_SAATI,
                "kayit_id": kayit.id,
            }

    @staticmethod
    def pos_tahsilat_listele(limit=300, sadece_kk=True):
        from database.models.cari import Cari

        with get_session() as session:
            q = (
                select(PosValorKaydi)
                .order_by(PosValorKaydi.tahsilat_tarihi.desc(), PosValorKaydi.id.desc())
                .limit(limit)
            )
            if sadece_kk:
                q = q.where(PosValorKaydi.kart_tipi == "KREDI_KARTI")
            kayitlar = list(session.scalars(q).all())
            if not kayitlar:
                return []
            cari_ids = {k.cari_id for k in kayitlar if k.cari_id}
            cari_map = {}
            if cari_ids:
                for c in session.scalars(select(Cari).where(Cari.id.in_(cari_ids))).all():
                    cari_map[c.id] = f"{c.cari_kodu} - {c.unvan}"
            banka_ids = {k.banka_karti_id for k in kayitlar}
            banka_map = {}
            if banka_ids:
                for b in session.scalars(select(BankaKarti).where(BankaKarti.id.in_(banka_ids))).all():
                    banka_map[b.id] = b.banka_adi
            sonuc = []
            for k in kayitlar:
                n = int(getattr(k, "taksit_sayisi", None) or 1)
                sonuc.append({
                    "belge_no": k.belge_no,
                    "tarih": k.tahsilat_tarihi,
                    "cari": cari_map.get(k.cari_id, "—"),
                    "banka": banka_map.get(k.banka_karti_id, ""),
                    "taksit_sayisi": n,
                    "cekim": "Tek çekim" if n == 1 else f"{n} taksit",
                    "brut": Decimal(str(k.brut_tutar)),
                    "komisyon": Decimal(str(k.komisyon_tutari)),
                    "komisyon_orani": Decimal(str(k.komisyon_orani)),
                    "net": Decimal(str(k.net_tutar)),
                    "valor_tarihi": k.valor_tarihi,
                    "durum": k.durum,
                    "aciklama": k.aciklama or "",
                    "banka_karti_id": k.banka_karti_id,
                    "cari_id": k.cari_id,
                })
            return sonuc

    @staticmethod
    def pos_tahsilat_getir(belge_no: str) -> dict:
        from database.models.cari import Cari

        belge_no = (belge_no or "").strip()
        with get_session() as session:
            k = session.scalar(
                select(PosValorKaydi).where(PosValorKaydi.belge_no == belge_no)
            )
            if not k:
                raise ValueError("POS tahsilat fişi bulunamadı.")
            cari = session.get(Cari, k.cari_id) if k.cari_id else None
            return {
                "belge_no": k.belge_no,
                "tarih": k.tahsilat_tarihi,
                "tutar": Decimal(str(k.brut_tutar)),
                "banka_karti_id": k.banka_karti_id,
                "cari_id": k.cari_id,
                "cari_etiket": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                "taksit_sayisi": int(getattr(k, "taksit_sayisi", None) or 1),
                "kart_tipi": k.kart_tipi,
                "komisyon_orani": Decimal(str(k.komisyon_orani)),
                "komisyon_tutari": Decimal(str(k.komisyon_tutari)),
                "net": Decimal(str(k.net_tutar)),
                "durum": k.durum,
                "aciklama": k.aciklama or "",
            }

    @staticmethod
    def pos_valor_bekleyenler(banka_karti_id=None):
        with get_session() as session:
            q = (
                select(PosValorKaydi)
                .where(PosValorKaydi.durum == "BEKLIYOR")
                .order_by(PosValorKaydi.valor_tarihi, PosValorKaydi.id)
            )
            if banka_karti_id:
                q = q.where(PosValorKaydi.banka_karti_id == int(banka_karti_id))
            return list(session.scalars(q).all())

    @staticmethod
    def pos_valor_vadesi_geldi_mi(kayit, simdi: datetime | None = None) -> bool:
        simdi = simdi or datetime.now()
        saat_parca = (kayit.valor_saati or POS_VALOR_SAATI).split(":")
        saat = int(saat_parca[0]) if saat_parca else 8
        dakika = int(saat_parca[1]) if len(saat_parca) > 1 else 0
        valor_dt = datetime.combine(
            kayit.valor_tarihi,
            datetime.min.time().replace(hour=saat, minute=dakika),
        )
        return simdi >= valor_dt

    @staticmethod
    def pos_valor_aktar(kayit_id) -> dict:
        """Bekleyen POS net bakiyesini KMH'ye aktarır."""
        with get_session() as session:
            kayit = session.scalar(select(PosValorKaydi).where(PosValorKaydi.id == int(kayit_id)))
            if not kayit:
                raise ValueError("Valör kaydı bulunamadı.")
            if kayit.durum != "BEKLIYOR":
                raise ValueError("Bu kayıt zaten aktarılmış.")
            if not FinansService.pos_valor_vadesi_geldi_mi(kayit):
                raise ValueError(
                    f"Valör henüz gelmedi: {kayit.valor_tarihi.strftime('%d.%m.%Y')} "
                    f"{kayit.valor_saati}"
                )
            net = Decimal(str(kayit.net_tutar))
            if net <= 0:
                kayit.durum = "AKTARILDI"
                kayit.aktarim_zamani = datetime.now()
                session.flush()
                return {"belge_no": kayit.belge_no, "net": net, "aktarildi": False}

            belge = kayit.belge_no
            acik = kayit.aciklama or "POS valör aktarımı"
            session.add(
                FinansHareketi(
                    hesap_id=kayit.pos_hesap_id,
                    tarih=date.today(),
                    hareket_turu="POS → KMH AKTARIM (POS)",
                    belge_no=belge,
                    tutar=net,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=kayit.kmh_hesap_id,
                    tarih=date.today(),
                    hareket_turu="POS → KMH AKTARIM (KMH)",
                    belge_no=belge,
                    tutar=net,
                    aciklama=acik,
                )
            )
            kayit.durum = "AKTARILDI"
            kayit.aktarim_zamani = datetime.now()
            session.flush()
            return {"belge_no": belge, "net": net, "aktarildi": True}

    @staticmethod
    def pos_valor_vadesi_gelenleri_aktar(banka_karti_id=None) -> list[dict]:
        """Vadesi/saati gelmiş tüm bekleyen valör kayıtlarını KMH'ye aktarır."""
        bekleyenler = FinansService.pos_valor_bekleyenler(banka_karti_id=banka_karti_id)
        sonuclar = []
        for kayit in bekleyenler:
            if FinansService.pos_valor_vadesi_geldi_mi(kayit):
                try:
                    sonuclar.append(FinansService.pos_valor_aktar(kayit.id))
                except ValueError:
                    continue
        return sonuclar

    @staticmethod
    def pos_hareketleri(pos_hesap_id, limit=400):
        """POS hesabı hareketleri (cari eşlemeli)."""
        from database.models.cari import Cari, CariIslem

        with get_session() as session:
            hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.id == int(pos_hesap_id)))
            if not hesap:
                return []
            acilis = Decimal(str(hesap.acilis_bakiyesi or 0))
            tum = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hesap_id == int(pos_hesap_id))
                    .order_by(FinansHareketi.tarih.asc(), FinansHareketi.id.asc())
                ).all()
            )
            belge_nolar = {h.belge_no for h in tum if h.belge_no}
            cari_map: dict[str, str] = {}
            if belge_nolar:
                for belge_no, kod, unvan in session.execute(
                    select(CariIslem.belge_no, Cari.cari_kodu, Cari.unvan)
                    .join(Cari, Cari.id == CariIslem.cari_id)
                    .where(CariIslem.belge_no.in_(belge_nolar))
                    .order_by(CariIslem.id.desc())
                ).all():
                    if belge_no not in cari_map:
                        cari_map[belge_no] = f"{kod} - {unvan}"
            bakiye = acilis
            sonuc = []
            for har in tum:
                isaret = FinansService.hareket_isareti(har.hareket_turu)
                giris = Decimal(str(har.tutar)) if isaret > 0 else Decimal("0")
                cikis = Decimal(str(har.tutar)) if isaret < 0 else Decimal("0")
                bakiye = bakiye + giris - cikis
                sonuc.append({
                    "tarih": har.tarih,
                    "hareket_turu": har.hareket_turu,
                    "belge_no": har.belge_no,
                    "cari": cari_map.get(har.belge_no, ""),
                    "giris": giris,
                    "cikis": cikis,
                    "bakiye": bakiye,
                    "aciklama": har.aciklama or "",
                })
            sonuc.reverse()
            return sonuc[:limit] if limit else sonuc

    # --- Kredi kartı tanımı / ödeme evrakı ---

    @staticmethod
    def _ay_ekle(baslangic: date, aylar: int) -> date:
        """Aynı gün kuralı; ay sonunda yoksa o ayın son günü (31 → 28/29/30)."""
        yil = baslangic.year
        ay = baslangic.month + aylar
        while ay > 12:
            ay -= 12
            yil += 1
        while ay < 1:
            ay += 12
            yil -= 1
        son_gun = calendar.monthrange(yil, ay)[1]
        return date(yil, ay, min(baslangic.day, son_gun))

    @staticmethod
    def kk_taksit_plani(cekim_tarihi: date, taksit_sayisi: int, tutar: Decimal) -> list[dict]:
        """1. taksit = çekim günü; sonrakiler her ay aynı gün. Kuruş farkı son taksite."""
        n = int(taksit_sayisi)
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        toplam = Decimal(str(tutar)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        birim = (toplam / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        plan = []
        biriken = Decimal("0")
        for i in range(1, n + 1):
            if i == n:
                taksit_tutar = toplam - biriken
            else:
                taksit_tutar = birim
                biriken += birim
            plan.append({
                "taksit_no": i,
                "vade_tarihi": FinansService._ay_ekle(cekim_tarihi, i - 1),
                "tutar": taksit_tutar,
            })
        return plan

    @staticmethod
    def kredi_kartlari(banka_karti_id=None, aktif_only=True):
        with get_session() as session:
            q = select(KrediKartiTanimi).order_by(KrediKartiTanimi.kart_adi)
            if banka_karti_id:
                q = q.where(KrediKartiTanimi.banka_karti_id == int(banka_karti_id))
            if aktif_only:
                q = q.where(KrediKartiTanimi.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def kredi_karti_getir(kart_id):
        with get_session() as session:
            return session.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.id == int(kart_id))
            )

    @staticmethod
    def kredi_karti_kaydet(veriler: dict) -> KrediKartiTanimi:
        kart_adi = (veriler.get("kart_adi") or "").strip()
        if not kart_adi:
            raise ValueError("Kart adı zorunludur.")
        banka_karti_id = veriler.get("banka_karti_id")
        if not banka_karti_id:
            raise ValueError("Banka kartı seçilmelidir.")

        kart_bankasi = (veriler.get("kart_bankasi") or "").strip() or None
        kart_sahibi = (veriler.get("kart_sahibi") or "").strip() or None
        kart_markasi = (veriler.get("kart_markasi") or "").strip() or None
        if kart_markasi == "(Seçiniz)":
            kart_markasi = None

        # Kart numarası: boşluk/tire temizle, sadece rakam sakla
        ham_no = (veriler.get("kart_numarasi") or "").strip()
        kart_no = "".join(ch for ch in ham_no if ch.isdigit())
        if kart_no and (len(kart_no) < 13 or len(kart_no) > 19):
            raise ValueError("Kart numarası 13-19 rakam olmalıdır.")
        son4 = (veriler.get("son_dort_hane") or "").strip()
        if kart_no:
            son4 = kart_no[-4:]
        elif son4 and (not son4.isdigit() or len(son4) != 4):
            raise ValueError("Son 4 hane 4 rakam olmalıdır.")

        son_kullanim = (veriler.get("son_kullanim") or "").strip().replace(" ", "")
        if son_kullanim:
            if len(son_kullanim) == 4 and son_kullanim.isdigit():
                son_kullanim = f"{son_kullanim[:2]}/{son_kullanim[2:]}"
            try:
                ay_s, yil_s = son_kullanim.split("/")
                ay = int(ay_s)
                yil = int(yil_s)
                if ay < 1 or ay > 12:
                    raise ValueError
                if yil < 100:
                    yil += 2000
                son_kullanim = f"{ay:02d}/{str(yil)[-2:]}"
            except ValueError as hata:
                raise ValueError("Son kullanım AA/YY formatında olmalıdır (ör. 09/28).") from hata

        cvv = (veriler.get("guvenlik_kodu") or "").strip()
        if cvv and (not cvv.isdigit() or len(cvv) not in (3, 4)):
            raise ValueError("Güvenlik kodu (CVV) 3 veya 4 rakam olmalıdır.")

        limit = _decimal(veriler.get("kart_limiti") or 0, "Kart limiti", Decimal("0"))

        def _gun(alan, etiket):
            ham = veriler.get(alan)
            if ham in (None, ""):
                return None
            try:
                g = int(str(ham).strip())
            except ValueError as hata:
                raise ValueError(f"{etiket} 1-28 arasında olmalıdır.") from hata
            if g < 1 or g > 28:
                raise ValueError(f"{etiket} 1-28 arasında olmalıdır.")
            return g

        kesim = _gun("hesap_kesim_gunu", "Hesap kesim günü")
        son_odeme = _gun("son_odeme_gunu", "Son ödeme günü")

        with get_session() as session:
            banka = session.scalar(select(BankaKarti).where(BankaKarti.id == int(banka_karti_id)))
            if not banka:
                raise ValueError("Banka kartı bulunamadı.")
            kart_id = veriler.get("kart_id")
            if kart_id:
                kart = session.scalar(
                    select(KrediKartiTanimi).where(KrediKartiTanimi.id == int(kart_id))
                )
                if not kart:
                    raise ValueError("Kredi kartı bulunamadı.")
            else:
                kart = KrediKartiTanimi(banka_karti_id=banka.id)
                session.add(kart)
            kart.kart_bankasi = kart_bankasi or banka.banka_adi
            kart.kart_adi = kart_adi
            kart.kart_sahibi = kart_sahibi
            kart.kart_markasi = kart_markasi
            kart.kart_numarasi = kart_no or None
            kart.son_dort_hane = son4 or None
            kart.son_kullanim = son_kullanim or None
            kart.guvenlik_kodu = cvv or None
            kart.kart_limiti = limit
            kart.hesap_kesim_gunu = kesim
            kart.son_odeme_gunu = son_odeme
            kart.aciklama = (veriler.get("aciklama") or "").strip() or None
            if "aktif" in veriler:
                kart.aktif = bool(veriler["aktif"])
            session.flush()
            return kart

    @staticmethod
    def kredi_karti_pasif_yap(kart_id):
        with get_session() as session:
            kart = session.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.id == int(kart_id))
            )
            if not kart:
                raise ValueError("Kredi kartı bulunamadı.")
            kart.aktif = False

    @staticmethod
    def kredi_karti_kullanilan(kredi_karti_id) -> Decimal:
        """Açık KK ödemelerinin toplamı (basit kullanılan limit)."""
        with get_session() as session:
            odemeler = session.scalars(
                select(KrediKartiOdeme).where(
                    KrediKartiOdeme.kredi_karti_id == int(kredi_karti_id),
                    KrediKartiOdeme.durum == "AÇIK",
                )
            ).all()
            return sum((Decimal(str(o.tutar)) for o in odemeler), Decimal("0"))

    @staticmethod
    def kredi_karti_odeme(
        banka_karti_id,
        kredi_karti_id,
        cari_id,
        tarih,
        tutar,
        cekim_turu="TEK_CEKIM",
        taksit_sayisi=1,
        referans_no=None,
        aciklama=None,
        belge_no=None,
    ) -> dict:
        """
        Firma kredi kartı ile cariye ödeme.
        Tek çekim: vade = çekim günü.
        Taksitli: 1. taksit = çekim günü, sonrakiler her ay aynı gün (max 24).
        """
        brut = _decimal(tutar, "Ödeme tutarı", Decimal("0.01"))
        tur = (cekim_turu or "TEK_CEKIM").strip().upper()
        if tur not in {k for k, _ in KK_CEKIM_TURLERI}:
            raise ValueError("Çekim türü tek çekim veya taksitli olmalıdır.")
        try:
            n = int(str(taksit_sayisi).strip() or "1")
        except ValueError as hata:
            raise ValueError("Taksit sayısı tam sayı olmalıdır.") from hata
        if tur == "TEK_CEKIM":
            n = 1
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")

        plan = FinansService.kk_taksit_plani(tarih, n, brut)
        vade = plan[0]["vade_tarihi"]

        with get_session() as session:
            if belge_no:
                eski = session.scalar(
                    select(KrediKartiOdeme)
                    .where(
                        KrediKartiOdeme.belge_no == belge_no,
                        KrediKartiOdeme.durum == "AÇIK",
                    )
                    .options(selectinload(KrediKartiOdeme.taksitler))
                )
                if not eski:
                    raise ValueError("Güncellenecek KK ödeme fişi bulunamadı.")
                # Taksitlerden biri ödendiyse engelle
                if any((t.durum or "") == "ODENDI" for t in (eski.taksitler or [])):
                    raise ValueError("Ödenmiş taksiti olan fiş güncellenemez.")
                FinansService._havale_cari_geri_al(session, belge_no)
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.delete(eski)
                session.flush()

            kart_banka = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart_banka:
                raise ValueError("Banka kartı bulunamadı.")
            kk_hesap = next(
                (h for h in kart_banka.alt_hesaplar if (h.alt_hesap_turu or "") == "KREDI_KARTI"),
                None,
            )
            if not kk_hesap:
                raise ValueError("Kredi kartı hesabı eksik — banka kartını kaydedin.")

            kk = session.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.id == int(kredi_karti_id))
            )
            if not kk or not kk.aktif:
                raise ValueError("Ödeme yapılacak kredi kartı bulunamadı veya pasif.")
            if kk.banka_karti_id != kart_banka.id:
                raise ValueError("Seçilen kart bu bankaya ait değil.")

            kullanilan = sum(
                (
                    Decimal(str(o.tutar))
                    for o in session.scalars(
                        select(KrediKartiOdeme).where(
                            KrediKartiOdeme.kredi_karti_id == kk.id,
                            KrediKartiOdeme.durum == "AÇIK",
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            limit = Decimal(str(kk.kart_limiti or 0))
            if limit > 0 and kullanilan + brut > limit:
                kalan = limit - kullanilan
                raise ValueError(
                    f"Kart limiti yetersiz. Limit {_fmt(limit)}, "
                    f"kullanılan {_fmt(kullanilan)}, kalan {_fmt(kalan)}."
                )

            belgeno = belge_no or FinansService._finans_belge_no(session, "KKO")
            tip_etiket = dict(KK_CEKIM_TURLERI).get(tur, tur)
            taksit_metin = "Tek çekim" if n == 1 else f"{n} taksit"
            acik = aciklama or f"KK ödeme ({kk.kart_adi} / {taksit_metin})"
            if referans_no:
                acik = f"{acik} | Ref: {referans_no}"

            FinansService._cari_odeme_satiri(
                session, cari_id, tarih, brut, belgeno, kk_hesap.hesap_adi, acik
            )
            session.add(
                FinansHareketi(
                    hesap_id=kk_hesap.id,
                    tarih=tarih,
                    hareket_turu="KK ÖDEME",
                    belge_no=belgeno,
                    tutar=brut,
                    aciklama=acik,
                )
            )

            odeme = KrediKartiOdeme(
                belge_no=belgeno,
                tarih=tarih,
                vade_tarihi=vade,
                banka_karti_id=kart_banka.id,
                kredi_karti_id=kk.id,
                cari_id=int(cari_id),
                cekim_turu=tur,
                taksit_sayisi=n,
                tutar=brut,
                referans_no=(referans_no or "").strip() or None,
                aciklama=(aciklama or "").strip() or None,
                durum="AÇIK",
            )
            session.add(odeme)
            session.flush()
            for satir in plan:
                session.add(
                    KrediKartiOdemeTaksit(
                        odeme_id=odeme.id,
                        taksit_no=satir["taksit_no"],
                        vade_tarihi=satir["vade_tarihi"],
                        tutar=satir["tutar"],
                        durum="BEKLIYOR",
                    )
                )
            session.flush()
            return {
                "belge_no": belgeno,
                "tutar": brut,
                "cekim_turu": tip_etiket,
                "taksit_sayisi": n,
                "vade_tarihi": vade,
                "plan": plan,
                "odeme_id": odeme.id,
            }

    @staticmethod
    def kredi_karti_odeme_getir(belge_no: str) -> dict:
        from database.models.cari import Cari

        belge_no = (belge_no or "").strip()
        with get_session() as session:
            o = session.scalar(
                select(KrediKartiOdeme)
                .where(
                    KrediKartiOdeme.belge_no == belge_no,
                    KrediKartiOdeme.durum == "AÇIK",
                )
                .options(
                    selectinload(KrediKartiOdeme.kredi_karti),
                    selectinload(KrediKartiOdeme.taksitler),
                )
            )
            if not o:
                raise ValueError("KK ödeme fişi bulunamadı.")
            cari = session.get(Cari, o.cari_id)
            return {
                "belge_no": o.belge_no,
                "tarih": o.tarih,
                "vade_tarihi": o.vade_tarihi,
                "tutar": Decimal(str(o.tutar)),
                "banka_karti_id": o.banka_karti_id,
                "kredi_karti_id": o.kredi_karti_id,
                "cari_id": o.cari_id,
                "cari_etiket": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                "cekim_turu": o.cekim_turu,
                "taksit_sayisi": o.taksit_sayisi,
                "referans_no": o.referans_no or "",
                "aciklama": o.aciklama or "",
                "kart_adi": o.kredi_karti.kart_adi if o.kredi_karti else "",
            }

    @staticmethod
    def kredi_karti_odemeleri(banka_karti_id=None, limit=300):
        from database.models.cari import Cari

        with get_session() as session:
            q = (
                select(KrediKartiOdeme)
                .where(KrediKartiOdeme.durum == "AÇIK")
                .options(
                    selectinload(KrediKartiOdeme.kredi_karti),
                    selectinload(KrediKartiOdeme.taksitler),
                )
                .order_by(KrediKartiOdeme.tarih.desc(), KrediKartiOdeme.id.desc())
                .limit(limit)
            )
            if banka_karti_id:
                q = q.where(KrediKartiOdeme.banka_karti_id == int(banka_karti_id))
            odemeler = list(session.scalars(q).all())
            cari_ids = {o.cari_id for o in odemeler}
            cari_map = {}
            if cari_ids:
                for c in session.scalars(select(Cari).where(Cari.id.in_(cari_ids))).all():
                    cari_map[c.id] = f"{c.cari_kodu} - {c.unvan}"
            banka_ids = {o.banka_karti_id for o in odemeler}
            banka_map = {}
            if banka_ids:
                for b in session.scalars(select(BankaKarti).where(BankaKarti.id.in_(banka_ids))).all():
                    banka_map[b.id] = b.banka_adi
            sonuc = []
            for o in odemeler:
                sonuc.append({
                    "id": o.id,
                    "belge_no": o.belge_no,
                    "tarih": o.tarih,
                    "vade_tarihi": o.vade_tarihi,
                    "cari": cari_map.get(o.cari_id, ""),
                    "banka": banka_map.get(o.banka_karti_id, ""),
                    "kart": o.kredi_karti.kart_adi if o.kredi_karti else "",
                    "cekim_turu": dict(KK_CEKIM_TURLERI).get(o.cekim_turu, o.cekim_turu),
                    "taksit_sayisi": o.taksit_sayisi,
                    "tutar": Decimal(str(o.tutar)),
                    "referans_no": o.referans_no or "",
                    "aciklama": o.aciklama or "",
                    "banka_karti_id": o.banka_karti_id,
                    "kredi_karti_id": o.kredi_karti_id,
                    "cari_id": o.cari_id,
                    "taksitler": [
                        {
                            "taksit_no": t.taksit_no,
                            "vade_tarihi": t.vade_tarihi,
                            "tutar": Decimal(str(t.tutar)),
                            "durum": t.durum,
                        }
                        for t in (o.taksitler or [])
                    ],
                })
            return sonuc

    @staticmethod
    def kredi_karti_bekleyen_taksitler(banka_karti_id, limit=200):
        with get_session() as session:
            q = (
                select(KrediKartiOdemeTaksit)
                .join(KrediKartiOdeme)
                .where(
                    KrediKartiOdeme.banka_karti_id == int(banka_karti_id),
                    KrediKartiOdeme.durum == "AÇIK",
                    KrediKartiOdemeTaksit.durum == "BEKLIYOR",
                )
                .options(selectinload(KrediKartiOdemeTaksit.odeme).selectinload(KrediKartiOdeme.kredi_karti))
                .order_by(KrediKartiOdemeTaksit.vade_tarihi, KrediKartiOdemeTaksit.id)
                .limit(limit)
            )
            sonuc = []
            for t in session.scalars(q).all():
                o = t.odeme
                sonuc.append({
                    "belge_no": o.belge_no if o else "",
                    "kart": o.kredi_karti.kart_adi if o and o.kredi_karti else "",
                    "taksit_no": t.taksit_no,
                    "taksit_sayisi": o.taksit_sayisi if o else 0,
                    "vade_tarihi": t.vade_tarihi,
                    "tutar": Decimal(str(t.tutar)),
                })
            return sonuc


def _fmt(tutar) -> str:
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

