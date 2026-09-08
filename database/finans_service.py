from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import (
    BANKA_ALT_HESAP_TURLERI,
    POS_KART_TIPLERI,
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
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
)

MEVDUAT_EVRAK_TURLERI = (
    "KASADAN BANKAYA YATAN",
    "ALINAN HAVALE",
    "GÖNDERİLEN HAVALE",
    "BANKADAN NAKİT ÇEKİLEN",
)

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
                    selectinload(BankaKarti.alt_hesaplar).selectinload(FinansHesabi.hareketler)
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
            CariService._aciklara_uygula(session, cari.id, tutar)
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
    def kasadan_bankaya_yatan(kasa_hesap_id, mevduat_hesap_id, tarih, tutar, aciklama=None) -> str:
        """Kasadan çıkış + mevduat girişi."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            kasa = FinansService._hesap_bul(session, kasa_hesap_id)
            mevduat = FinansService._hesap_bul(session, mevduat_hesap_id)
            if (kasa.hesap_turu or "").upper() != "KASA":
                raise ValueError("Kaynak hesap bir kasa olmalıdır.")
            belge_no = FinansService._finans_belge_no(session, "KBY")
            acik = aciklama or f"{kasa.hesap_adi} → {mevduat.hesap_adi}"
            session.add(
                FinansHareketi(
                    hesap_id=kasa.id,
                    tarih=tarih,
                    hareket_turu="KASADAN BANKAYA (KASA)",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=mevduat.id,
                    tarih=tarih,
                    hareket_turu="KASADAN BANKAYA YATAN",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belge_no

    @staticmethod
    def alinan_havale(mevduat_hesap_id, tarih, tutar, cari_id=None, aciklama=None) -> str:
        """Mevduata giriş; cari zorunlu (tahsilat)."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if not cari_id:
            raise ValueError("Alınan havale için cari seçimi zorunludur.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            mevduat = FinansService._hesap_bul(session, mevduat_hesap_id)
            belge_no = FinansService._finans_belge_no(session, "AHV")
            acik = aciklama or "Alınan havale"
            session.add(
                FinansHareketi(
                    hesap_id=mevduat.id,
                    tarih=tarih,
                    hareket_turu="ALINAN HAVALE",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            FinansService._cari_tahsilat_satiri(
                session, cari_id, tarih, tutar, belge_no, mevduat.hesap_adi, acik
            )
            session.flush()
            return belge_no

    @staticmethod
    def gonderilen_havale(mevduat_hesap_id, tarih, tutar, cari_id=None, aciklama=None) -> str:
        """Mevduattan çıkış; isteğe bağlı cari ödeme."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            mevduat = FinansService._hesap_bul(session, mevduat_hesap_id)
            belge_no = FinansService._finans_belge_no(session, "GHV")
            acik = aciklama or "Gönderilen havale"
            session.add(
                FinansHareketi(
                    hesap_id=mevduat.id,
                    tarih=tarih,
                    hareket_turu="GÖNDERİLEN HAVALE",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            if cari_id:
                FinansService._cari_odeme_satiri(
                    session, cari_id, tarih, tutar, belge_no, mevduat.hesap_adi, acik
                )
            session.flush()
            return belge_no

    @staticmethod
    def banka_hesaplari_arasi_virman(
        kaynak_hesap_id, hedef_hesap_id, tarih, tutar, aciklama=None
    ) -> str:
        """İki banka (mevduat) hesabı arasında virman."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if int(kaynak_hesap_id) == int(hedef_hesap_id):
            raise ValueError("Kaynak ve hedef hesap aynı olamaz.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            kaynak = FinansService._hesap_bul(session, kaynak_hesap_id)
            hedef = FinansService._hesap_bul(session, hedef_hesap_id)
            if (kaynak.hesap_turu or "").upper() not in ("BANKA", "KREDİ KARTI"):
                raise ValueError("Kaynak hesap bir banka hesabı olmalıdır.")
            if (hedef.hesap_turu or "").upper() not in ("BANKA", "KREDİ KARTI"):
                raise ValueError("Hedef hesap bir banka hesabı olmalıdır.")
            belge_no = FinansService._finans_belge_no(session, "BVR")
            acik = aciklama or f"{kaynak.hesap_adi} → {hedef.hesap_adi}"
            session.add(
                FinansHareketi(
                    hesap_id=kaynak.id,
                    tarih=tarih,
                    hareket_turu="BANKA VİRMAN ÇIKIŞ",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=hedef.id,
                    tarih=tarih,
                    hareket_turu="BANKA VİRMAN GİRİŞ",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belge_no

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
    def bankadan_nakit_cekilen(mevduat_hesap_id, kasa_hesap_id, tarih, tutar, aciklama=None) -> str:
        """Mevduattan çıkış + kasaya giriş."""
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        with get_session() as session:
            mevduat = FinansService._hesap_bul(session, mevduat_hesap_id)
            kasa = FinansService._hesap_bul(session, kasa_hesap_id)
            if (kasa.hesap_turu or "").upper() != "KASA":
                raise ValueError("Hedef hesap bir kasa olmalıdır.")
            belge_no = FinansService._finans_belge_no(session, "BNC")
            acik = aciklama or f"{mevduat.hesap_adi} → {kasa.hesap_adi}"
            session.add(
                FinansHareketi(
                    hesap_id=mevduat.id,
                    tarih=tarih,
                    hareket_turu="BANKADAN NAKİT ÇEKİLEN",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=kasa.id,
                    tarih=tarih,
                    hareket_turu="BANKADAN NAKİT (KASA)",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            return belge_no

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
    def _pos_komisyon_orani(kart: BankaKarti, kart_tipi: str) -> Decimal:
        tip = (kart_tipi or "").upper()
        if tip == "BANKA_KARTI":
            return Decimal(str(kart.banka_karti_komisyon_orani or 0))
        return Decimal(str(kart.kk_komisyon_orani or 0))

    @staticmethod
    def pos_tahsilat(
        banka_karti_id,
        tarih,
        brut_tutar,
        kart_tipi="KREDI_KARTI",
        cari_id=None,
        aciklama=None,
    ) -> dict:
        """
        POS'a brüt giriş, komisyon çıkışı; net tutar valör gününde KMH'ye aktarılmak üzere bekler.
        valor_gun=1 → ertesi gün 08:00.
        """
        brut = _decimal(brut_tutar, "Tahsilat tutarı", Decimal("0.01"))
        tip = (kart_tipi or "KREDI_KARTI").strip().upper()
        if tip not in {k for k, _ in POS_KART_TIPLERI}:
            raise ValueError("Kart tipi kredi kartı veya banka kartı olmalıdır.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")

        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            pos = next((h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "POS"), None)
            kmh = next((h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "KMH"), None)
            if not pos or not kmh:
                raise ValueError("POS veya KMH hesabı eksik — banka kartını kaydedin.")

            oran = FinansService._pos_komisyon_orani(kart, tip)
            if oran < 0 or oran > 100:
                raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
            komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            net = brut - komisyon
            if net < 0:
                raise ValueError("Komisyon tutarı brüt tutardan büyük olamaz.")

            valor_gun = int(kart.pos_valor_gun or 1)
            valor_tarihi = tarih + timedelta(days=valor_gun)
            belge_no = FinansService._finans_belge_no(session, "POS")
            tip_etiket = dict(POS_KART_TIPLERI).get(tip, tip)
            acik = aciklama or f"POS tahsilat ({tip_etiket})"

            # Brüt POS girişi
            session.add(
                FinansHareketi(
                    hesap_id=pos.id,
                    tarih=tarih,
                    hareket_turu="POS TAHSİLAT",
                    belge_no=belge_no,
                    tutar=brut,
                    aciklama=acik,
                )
            )
            # Komisyon düşümü
            if komisyon > 0:
                session.add(
                    FinansHareketi(
                        hesap_id=pos.id,
                        tarih=tarih,
                        hareket_turu="POS KOMİSYON",
                        belge_no=belge_no,
                        tutar=komisyon,
                        aciklama=f"Komisyon %{oran:g}",
                    )
                )
            if cari_id:
                FinansService._cari_tahsilat_satiri(
                    session, cari_id, tarih, brut, belge_no, pos.hesap_adi, acik
                )

            kayit = PosValorKaydi(
                banka_karti_id=kart.id,
                pos_hesap_id=pos.id,
                kmh_hesap_id=kmh.id,
                belge_no=belge_no,
                tahsilat_tarihi=tarih,
                valor_tarihi=valor_tarihi,
                valor_saati=POS_VALOR_SAATI,
                kart_tipi=tip,
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
                "belge_no": belge_no,
                "brut": brut,
                "komisyon": komisyon,
                "net": net,
                "valor_tarihi": valor_tarihi,
                "valor_saati": POS_VALOR_SAATI,
                "kayit_id": kayit.id,
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
