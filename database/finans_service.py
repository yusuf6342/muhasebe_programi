from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import calendar
import re
import time

from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.access import yazma_zorunlu
from database.models.finans import (
    BANKA_ALT_HESAP_TURLERI,
    KK_CEKIM_TURLERI,
    KK_MAX_TAKSIT,
    KREDI_MAX_TAKSIT,
    KREDI_ODEME_HESAP_TURLERI,
    KREDI_TURLERI,
    POS_KART_TIPLERI,
    POS_MAX_TAKSIT,
    BankaKarti,
    BankaKredisi,
    BankaKrediTaksit,
    CariVirmanMakbuzu,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KasaMakbuzu,
    KasaMakbuzSatiri,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
    PosTaksitKomisyon,
    PosValorKaydi,
    SatisFaturaMakbuzBagi,
)

HESAP_TURLERI = ("KASA", "BANKA", "KREDİ KARTI")

# Rapor / UI: borç (yükümlülük) hesapları — varlık bakiyesi olarak eksi (−) ve kırmızı gösterilir
BORC_ALT_HESAP_TURLERI = frozenset({"KREDI_KARTI", "KREDILER"})
BAKIYE_RENK_POZITIF = "#1b7a3d"
BAKIYE_RENK_NEGATIF = "#c62828"
BAKIYE_RENK_SIFIR = "#444444"

# ISO 13616 ülke kodu → IBAN uzunluğu (sık kullanılanlar; TR zorunlu doğrulanır)
_IBAN_ULKE_UZUNLUK = {
    "TR": 26, "DE": 22, "AT": 20, "NL": 18, "GB": 22, "FR": 27,
    "IT": 27, "ES": 24, "CH": 21, "BE": 16, "US": 0,  # US IBAN kullanmaz
}


def iban_normalize(deger) -> str | None:
    """Boşlukları temizle, büyük harfe çevir; boşsa None."""
    if deger is None:
        return None
    s = str(deger).replace(" ", "").replace("-", "").upper()
    return s or None


def iban_dogrula(deger, *, zorunlu: bool = False) -> str | None:
    """
    IBAN biçim doğrulaması. Türkiye: 26 karakter + MOD-97 kontrol basamağı.
    Diğer ülkeler: bilinen uzunluk + MOD-97 (uzunluk tabloda yoksa 15–34).
    Boş değer zorunlu değilse None döner.
    """
    s = iban_normalize(deger)
    if not s:
        if zorunlu:
            raise ValueError("IBAN zorunludur.")
        return None
    if not s.isalnum():
        raise ValueError("IBAN yalnızca harf ve rakam içermelidir.")
    if len(s) < 5 or not s[:2].isalpha() or not s[2:4].isdigit():
        raise ValueError("IBAN ülke kodu ve kontrol basamağı geçersiz.")
    ulke = s[:2]
    beklenen = _IBAN_ULKE_UZUNLUK.get(ulke)
    if ulke == "TR" or beklenen:
        if ulke == "US":
            raise ValueError("ABD IBAN kullanmaz; hesap numarasını IBAN alanına yazmayın.")
        if beklenen and len(s) != beklenen:
            raise ValueError(
                f"{ulke} IBAN {beklenen} karakter olmalıdır (girilen: {len(s)})."
            )
    elif len(s) < 15 or len(s) > 34:
        raise ValueError("IBAN uzunluğu 15–34 karakter olmalıdır.")
    # ISO 13616 MOD-97
    rearranged = s[4:] + s[:4]
    sayisal = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    if int(sayisal) % 97 != 1:
        raise ValueError("IBAN kontrol basamağı geçersiz.")
    return s

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
    "POS → KMH AKTARIM (KMH)",  # eski etiket
    "POS VALÖR AKTARIM (HEDEF)",
    "KK ÖDEME",  # kartla ödeme → KK borcu artar
    "KK EKSTRE ÖDEME İPTAL",  # iptal edilen ekstre ödemesi: ödeme hesabına iade, kart borcu geri gelir
    "KK ÖDEME DÜZELTME EK",  # kayıt düzeltmesi: açık dönem artışı / eksi düzeltmenin tersi → kart borcu artar
    "KK GİDER",  # eski sürümde kart hesabına yazılmış gider fişi (onarımla) → KK borcu artar
    "KREDİ KULLANDIRIM",  # ana para → krediler borcu artar
    "KREDİ KULLANDIRIM (MEVDUAT)",  # ana para mevduat/KMH'ye giriş
    "TAHSİLAT MAKBUZU",
    "ÇEK/SENET TAHSİLAT",
    "ÇEK/SENET ÖDEME İPTAL",  # iptal edilen çek/senet ödemesinin ters hareketi
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
    "BANKA VİRMAN MASRAF",
    "POS KOMİSYON",
    "POS → KMH AKTARIM (POS)",  # eski etiket
    "POS VALÖR AKTARIM (POS)",
    "KK EKSTRE ÖDEME",  # kart borcunu kapatma
    "KREDİ ANAPARA ÖDEME",  # krediler borcu azalır / ödeme hesabından anapara
    "KREDİ FAİZ GİDERİ",
    "KREDİ MASRAF GİDERİ",
    "GİDER FİŞİ",
    "ÖDEME MAKBUZU",
    "ÇEK/SENET ÖDEME",
    "KK İADE",  # banka iadesi → KK borcu azalır
    "KK ÖDEME İPTAL",  # hatalı kart ödemesi kaydının ters hareketi
    "KK ÖDEME DÜZELTME",  # kayıt düzeltmesi: eski kart kaydının ters hareketi / açık dönem azalışı
)

MEVDUAT_EVRAK_TURLERI = (
    "KASADAN BANKAYA YATAN",
    "ALINAN HAVALE",
    "GÖNDERİLEN HAVALE",
    "BANKADAN NAKİT ÇEKİLEN",
)

# Kasadan bankaya yatırılabilecek banka alt hesap türleri
KBY_HEDEF_ALT_TURLER = ("MEVDUAT", "KMH", "KREDI_KARTI", "VADELI")

# Eski sabit; yeni kayıtlarda boş bırakılır (vade yalnız iş/takvim gününe bakar)
POS_VALOR_SAATI = ""
POS_HEDEF_HESAP_TURLERI = ("MEVDUAT", "KMH")


def is_is_gunu(gun: date) -> bool:
    """Hafta içi (Pzt–Cum). Resmi tatil takvimi ayrıca eklenene kadar yalnızca hafta sonu atlanır."""
    return gun.weekday() < 5


def is_gunu_ekle(baslangic: date, gun_sayisi: int) -> date:
    """baslangıçtan sonra N iş günü ekler (N=0 → aynı gün iş günü değilse sonraki iş günü)."""
    n = int(gun_sayisi)
    if n < 0:
        raise ValueError("İş günü sayısı negatif olamaz.")
    gun = baslangic
    if n == 0:
        while not is_is_gunu(gun):
            gun += timedelta(days=1)
        return gun
    kalan = n
    while kalan > 0:
        gun += timedelta(days=1)
        if is_is_gunu(gun):
            kalan -= 1
    return gun


def valor_tarihi_hesapla(tahsilat: date, gun_sayisi: int, *, is_gunu: bool = True) -> date:
    """POS beklenen valör tarihi."""
    if is_gunu:
        return is_gunu_ekle(tahsilat, int(gun_sayisi))
    return tahsilat + timedelta(days=int(gun_sayisi))

# Tahsilat makbuzu numarası: MKB-00001 … (firma veritabanındaki en büyük MKB-n'den devam)
MAKBUZ_NO_ONEK = "MKB"
_MAKBUZ_NO_RE = re.compile(rf"{MAKBUZ_NO_ONEK}-(\d{{1,12}})")
_MAKBUZ_BAGLI_ONEKLER = ("TMK-", "OMK-")


def _makbuz_sekil_turu(sekil: str | None) -> str | None:
    """Makbuz ödeme şekli → KASA | HAVALE | KART (bilinmeyen eski adlar için None)."""
    s = (sekil or "").replace("İ", "I").replace("ı", "i").upper()
    if "HAVALE" in s:
        return "HAVALE"
    if "KART" in s or "POS" in s:
        return "KART"
    if "KASA" in s or "NAKIT" in s:
        return "KASA"
    return None


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
    def hesaplar(hesap_turu=None, aktif_only=True, *, hareketler: bool = True):
        with get_session() as session:
            q = select(FinansHesabi)
            if hareketler:
                q = q.options(selectinload(FinansHesabi.hareketler))
            if aktif_only:
                q = q.where(FinansHesabi.aktif.is_(True))
            if hesap_turu:
                q = q.where(FinansHesabi.hesap_turu == hesap_turu)
            q = q.order_by(FinansHesabi.hesap_adi)
            return list(session.scalars(q).all())

    @staticmethod
    def tahsilat_hesaplari(odeme_sekli: str | None = None):
        """Ödeme şekline göre tahsilat hesabı listesi.
        - Nakit/Kasa → yalnızca KASA
        - Gelen/Alınan Havale → MEVDUAT + KMH
        - Kredi kartı tahsilat → yalnızca POS (firma KK hesapları tahsilatta yok)

        Yalnız hesap kimliği/adı/türü döner; hareketler yüklenmez.
        """
        tum = FinansService.hesaplar(hareketler=False)
        sekil = (
            (odeme_sekli or "")
            .replace("İ", "I")
            .replace("ı", "i")
            .upper()
        )
        if "HAVALE" in sekil:
            return [
                h
                for h in tum
                if (getattr(h, "alt_hesap_turu", None) or "").upper() in ("MEVDUAT", "KMH")
            ]
        if "KART" in sekil or "POS" in sekil:
            # Firma kredi kartları (ödeme) hariç; sadece POS tahsilat hesapları
            return [
                h
                for h in tum
                if (getattr(h, "alt_hesap_turu", None) or "").upper() == "POS"
            ]
        if "KASA" in sekil or "NAKIT" in sekil:
            return [h for h in tum if (h.hesap_turu or "").upper() == "KASA"]
        return tum

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
    def hesap_pb(hesap) -> str:
        pb = (getattr(hesap, "para_birimi", None) or "TRY").strip().upper()
        return pb if pb in ("TRY", "USD", "EUR") else "TRY"

    @staticmethod
    def bakiye(hesap) -> Decimal:
        """Hesabın kendi para birimindeki bakiyesi (TRY/USD/EUR toplanmaz)."""
        toplam = Decimal(str(hesap.acilis_bakiyesi or 0))
        for h in hesap.hareketler or []:
            toplam += Decimal(str(h.tutar or 0)) * FinansService.hareket_isareti(h.hareket_turu)
        return toplam

    @staticmethod
    def tl_kayit_bakiyesi(hesap) -> Decimal:
        """Açılış + hareketlerin kayıt anındaki TL karşılıkları (rapor kurundan bağımsız)."""
        acilis_tl = getattr(hesap, "acilis_tl_karsiligi", None)
        if acilis_tl is None:
            pb = FinansService.hesap_pb(hesap)
            acilis = Decimal(str(hesap.acilis_bakiyesi or 0))
            if pb == "TRY":
                acilis_tl = acilis
            else:
                kur = getattr(hesap, "acilis_kuru", None)
                if kur is None:
                    acilis_tl = Decimal("0")
                else:
                    acilis_tl = (acilis * Decimal(str(kur))).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
        else:
            acilis_tl = Decimal(str(acilis_tl))
        toplam = acilis_tl
        for h in hesap.hareketler or []:
            isaret = FinansService.hareket_isareti(h.hareket_turu)
            tl = getattr(h, "tl_karsiligi", None)
            if tl is None:
                pb = (getattr(h, "para_birimi", None) or FinansService.hesap_pb(hesap)).upper()
                tutar = Decimal(str(h.tutar or 0))
                if pb == "TRY":
                    tl = tutar
                else:
                    kur = getattr(h, "kur", None)
                    tl = (
                        (tutar * Decimal(str(kur))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if kur is not None
                        else Decimal("0")
                    )
            else:
                tl = Decimal(str(tl))
            toplam += tl * isaret
        return toplam

    @staticmethod
    def _kayit_kuru_coz(
        pb: str,
        tarih: date,
        *,
        kur: Decimal | None = None,
        kur_tarihi: date | None = None,
    ) -> tuple[Decimal, date]:
        """Normalize kur (1 PB = kaç TRY) ve kur tarihi. TRY → (1, tarih)."""
        pb = (pb or "TRY").upper()
        if pb == "TRY":
            return Decimal("1"), tarih
        if kur is not None:
            k = Decimal(str(kur))
            if k <= 0:
                raise ValueError("Kur sıfır veya negatif olamaz.")
            return k.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), kur_tarihi or tarih
        from database.doviz_service import DovizService

        # Nakit: efektif satış tercihi; yoksa forex_selling
        try:
            k = DovizService.kur_degeri(tarih, pb, kur_turu="effective_selling")
        except ValueError:
            k = DovizService.kur_degeri(tarih, pb, kur_turu="forex_selling")
        yakin = DovizService.en_yakin_kur_tarihi(pb, tarih)
        return Decimal(str(k)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), yakin or tarih

    @staticmethod
    def hesap_kaydet(veriler: dict) -> FinansHesabi:
        yazma_zorunlu("finans_duzenleme")
        hesap_adi = (veriler.get("hesap_adi") or "").strip()
        hesap_turu = (veriler.get("hesap_turu") or "").strip().upper()
        if not hesap_adi:
            raise ValueError("Hesap adı zorunludur.")
        if hesap_turu not in HESAP_TURLERI:
            raise ValueError("Geçersiz hesap türü.")
        acilis = _decimal(veriler.get("acilis_bakiyesi") or 0, "Açılış bakiyesi")

        with get_session() as session:
            hesap_id = veriler.get("hesap_id")
            hesap = None
            if hesap_id:
                hesap = session.scalar(
                    select(FinansHesabi)
                    .options(selectinload(FinansHesabi.hareketler))
                    .where(FinansHesabi.id == int(hesap_id))
                )
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

            pb = (veriler.get("para_birimi") or "").strip().upper() or "TRY"
            if pb not in ("TRY", "USD", "EUR"):
                raise ValueError("Para birimi TRY, USD veya EUR olmalıdır.")
            eski_pb = FinansService.hesap_pb(hesap) if hesap.id else None
            if (
                hesap.id
                and eski_pb
                and eski_pb != pb
                and (hesap.hareketler or [])
            ):
                raise ValueError(
                    f"Hareketi olan hesabın para birimi değiştirilemez ({eski_pb}). "
                    "Ayrı PB için yeni kasa/hesap açın."
                )

            hesap.acilis_bakiyesi = acilis
            hesap.para_birimi = pb
            acilis_t = veriler.get("acilis_tarihi")
            if acilis_t is not None and acilis_t != "":
                if isinstance(acilis_t, date):
                    hesap.acilis_tarihi = acilis_t
                else:
                    try:
                        hesap.acilis_tarihi = datetime.strptime(
                            str(acilis_t).strip(), "%d.%m.%Y"
                        ).date()
                    except ValueError as hata:
                        raise ValueError("Açılış tarihi GG.AA.YYYY biçiminde olmalıdır.") from hata
            elif "acilis_tarihi" in veriler:
                hesap.acilis_tarihi = None
            # Açılış kuru: kullanıcı verdiyse sabitle; yoksa kur servisi / TRY=1
            acilis_kur_girdi = veriler.get("acilis_kuru")
            kur_tarihi = hesap.acilis_tarihi or date.today()
            if acilis_kur_girdi is not None and str(acilis_kur_girdi).strip() != "":
                kur, _kt = FinansService._kayit_kuru_coz(
                    pb, kur_tarihi, kur=_decimal(acilis_kur_girdi, "Açılış kuru")
                )
            else:
                kur, _kt = FinansService._kayit_kuru_coz(pb, kur_tarihi)
            hesap.acilis_kuru = kur
            hesap.acilis_tl_karsiligi = (acilis * kur).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
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
        yazma_zorunlu("finans_duzenleme")
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
    def hareket_ekle(
        session,
        belge_no,
        tarih,
        tutar,
        hareket_turu,
        hesap_adi,
        aciklama=None,
        *,
        kur=None,
        kur_tarihi=None,
        tl_karsiligi=None,
        para_birimi=None,
    ):
        """Hesap PB'sinde tutar yazar; kayıt kuru ve TL karşılığını sabitler.

        kur / tl_karsiligi verilmezse DovizService (TRY→1) kullanılır.
        para_birimi hesabın PB'sinden farklı olamaz.
        """
        tutar = Decimal(tutar)
        if tutar <= 0:
            return
        if not hesap_adi:
            raise ValueError("Kasa/banka hesabı seçin.")
        hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi))
        if not hesap:
            raise ValueError("Geçerli bir kasa/banka hesabı seçin.")
        pb = FinansService.hesap_pb(hesap)
        if para_birimi is not None:
            istenen = str(para_birimi).strip().upper()
            if istenen and istenen != pb:
                raise ValueError(
                    f"Hareket PB ({istenen}) hesap PB ({pb}) ile uyuşmuyor. "
                    "Döviz dönüşümü ayrı transfer olarak kaydedilir."
                )
        if isinstance(tarih, datetime):
            tarih = tarih.date()
        if kur is not None and tl_karsiligi is not None:
            k = Decimal(str(kur)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            tl = Decimal(str(tl_karsiligi)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kt = kur_tarihi or tarih
        else:
            k, kt = FinansService._kayit_kuru_coz(
                pb,
                tarih,
                kur=Decimal(str(kur)) if kur is not None else None,
                kur_tarihi=kur_tarihi,
            )
            if tl_karsiligi is not None:
                tl = Decimal(str(tl_karsiligi)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                tl = (tutar * k).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        session.add(
            FinansHareketi(
                hesap_id=hesap.id,
                tarih=tarih,
                hareket_turu=hareket_turu,
                belge_no=belge_no,
                tutar=tutar,
                para_birimi=pb,
                kur=k,
                kur_tarihi=kt,
                tl_karsiligi=tl,
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
        """Banka ana kartında aynı türdeki tüm gerçek alt hesapları topla."""
        sonuc = {kod: Decimal("0") for kod, _etiket in BANKA_ALT_HESAP_TURLERI}
        for hesap in kart.alt_hesaplar or []:
            kod = (hesap.alt_hesap_turu or "").strip().upper()
            if kod in sonuc:
                sonuc[kod] += FinansService.bakiye(hesap)
        return sonuc


    @staticmethod
    def borc_hesabi_mi(alt_tur=None, hesap=None, hesap_turu=None) -> bool:
        """
        Kredi kartı / krediler gibi yükümlülük hesapları mı?
        Tüm raporlarda bu hesaplar eksi (−) ve kırmızı gösterilir.

        Not: KMH borç hesabı değildir — hem + hem − olabilir; eksi olunca
        doğal olarak kırmızı/− gösterilir (limit kadar eksiye düşebilir).
        """
        if hesap is not None:
            alt = (getattr(hesap, "alt_hesap_turu", None) or "").upper()
            tur = (getattr(hesap, "hesap_turu", None) or "").upper()
            if alt in BORC_ALT_HESAP_TURLERI:
                return True
            if tur == "KREDİ KARTI":
                return True
            return False
        alt = (alt_tur or "").strip().upper()
        if alt in BORC_ALT_HESAP_TURLERI:
            return True
        tur = (hesap_turu or "").strip().upper()
        return tur == "KREDİ KARTI"

    @staticmethod
    def kmh_limiti(kart_veya_hesap) -> Decimal:
        """Banka kartı veya KMH hesabından KMH kredi limitini döner (≥ 0)."""
        if kart_veya_hesap is None:
            return Decimal("0")

        # Doğrudan BankaKarti
        if isinstance(kart_veya_hesap, BankaKarti):
            return abs(Decimal(str(kart_veya_hesap.kmh_limiti or 0)))

        # FinansHesabi → bağlı banka kartı
        kart = None
        try:
            kart = getattr(kart_veya_hesap, "banka_karti", None)
        except Exception:
            kart = None
        if isinstance(kart, BankaKarti):
            return abs(Decimal(str(kart.kmh_limiti or 0)))

        kart_id = getattr(kart_veya_hesap, "banka_karti_id", None)
        if not kart_id:
            return Decimal("0")
        with get_session() as session:
            kayit = session.scalar(select(BankaKarti).where(BankaKarti.id == int(kart_id)))
            if not kayit:
                return Decimal("0")
            return abs(Decimal(str(kayit.kmh_limiti or 0)))

    @staticmethod
    def asgari_bakiye(hesap, kart=None) -> Decimal:
        """
        Hesabın düşebileceği en düşük bakiye.
        KMH: -kredi_limiti; diğer hesaplar: 0.
        """
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").upper()
        if alt == "KMH":
            return -FinansService.kmh_limiti(kart if kart is not None else hesap)
        return Decimal("0")

    @staticmethod
    def kullanilabilir_bakiye(hesap, kart=None) -> Decimal:
        """
        Çıkış için kullanılabilir tutar = mevcut bakiye − asgari bakiye.
        KMH örneği: bakiye 100, limit 5000 → kullanılabilir 5100 (1000'e kadar eksiye inebilir).
        """
        bak = FinansService.bakiye(hesap)
        asgari = FinansService.asgari_bakiye(hesap, kart=kart)
        return bak - asgari

    @staticmethod
    def cikis_kontrol(hesap, tutar, kart=None, hesap_etiket="Hesap", *, bakiye_kontrol: bool = True):
        """
        Çıkış sonrası bakiye asgari seviyenin altına düşmesin.
        KMH: kredi limiti kadar eksi bakiyeye izin verilir.
        bakiye_kontrol=False: EvoBulut vb. tarihsel aktarımlarda eksi bakiyeyi gözardı et.
        """
        if not bakiye_kontrol:
            return
        from sqlalchemy.orm import object_session

        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        session = object_session(hesap)
        if session is not None:
            yenilenmis = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hesap.id))
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
            )
            if yenilenmis is not None:
                hesap = yenilenmis
                if kart is None:
                    kart = hesap.banka_karti

        bak = FinansService.bakiye(hesap)
        asgari = FinansService.asgari_bakiye(hesap, kart=kart)
        yeni_bakiye = bak - tutar
        if yeni_bakiye < asgari:
            alt = (getattr(hesap, "alt_hesap_turu", None) or "").upper()
            if alt == "KMH":
                limit = FinansService.kmh_limiti(kart if kart is not None else hesap)
                kullanilabilir = bak - asgari
                raise ValueError(
                    f"KMH kredi limiti aşıldı. Bakiye {_fmt(bak)}, "
                    f"limit {_fmt(limit)} (en fazla {_fmt(asgari)}), "
                    f"kullanılabilir {_fmt(kullanilabilir)}, tutar {_fmt(tutar)}."
                )
            raise ValueError(
                f"{hesap_etiket} bakiyesi yetersiz. Bakiye {_fmt(bak)}, "
                f"tutar {_fmt(tutar)}."
            )

    @staticmethod
    def varlik_bakiyesi(tutar, alt_tur=None, hesap=None, hesap_turu=None) -> Decimal:
        """
        Rapor / özet görünümü: varlık (+), borç hesapları (−).
        Ham borç bakiyesi pozitif borç tutar; burada eksi döner. Fazla ödenmiş kart (ham eksi) kart
        alacağıdır ve artı görünür.
        """
        deger = Decimal(str(tutar or 0))
        if FinansService.borc_hesabi_mi(alt_tur=alt_tur, hesap=hesap, hesap_turu=hesap_turu):
            return -deger if deger != 0 else Decimal("0")
        return deger

    @staticmethod
    def banka_bakiyeler_varlik(kart) -> dict[str, Decimal]:
        """banka_bakiyeler + borç hesapları eksi işaretli (rapor/UI standart görünüm)."""
        ham = FinansService.banka_bakiyeler(kart)
        return {
            kod: FinansService.varlik_bakiyesi(tutar, alt_tur=kod)
            for kod, tutar in ham.items()
        }

    @staticmethod
    def bakiye_renk_kodu(tutar) -> str:
        """Pozitif yeşil, negatif (borç) kırmızı, sıfır nötr — tüm raporlarda aynı."""
        deger = Decimal(str(tutar or 0))
        if deger > 0:
            return BAKIYE_RENK_POZITIF
        if deger < 0:
            return BAKIYE_RENK_NEGATIF
        return BAKIYE_RENK_SIFIR

    @staticmethod
    def banka_karti_kaydet(veriler: dict) -> BankaKarti:
        yazma_zorunlu("finans_duzenleme")
        banka_adi = (veriler.get("banka_adi") or "").strip()
        if not banka_adi:
            raise ValueError("Banka adı zorunludur.")
        # Şube / hesap no / IBAN artık alt hesaptadır; kart alanları yalnız verilirse (eski UI) güncellenir
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
                                if not cakisma and h.hesap_adi == FinansService._alt_hesap_adi(eski_ad, etiket):
                                    h.hesap_adi = yeni_ad
                                h.banka_adi = banka_adi

            if "sube" in veriler:
                kart.sube = (veriler.get("sube") or "").strip() or None
            if "hesap_no" in veriler:
                kart.hesap_no = (veriler.get("hesap_no") or "").strip() or None
            if "iban" in veriler:
                kart.iban = iban_dogrula(veriler.get("iban"))
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
            hedef_tur = (veriler.get("pos_hedef_hesap_turu") or "MEVDUAT").strip().upper()
            if hedef_tur not in POS_HEDEF_HESAP_TURLERI:
                raise ValueError("POS hedef hesabı Mevduat veya KMH olmalıdır.")
            kart.pos_hedef_hesap_turu = hedef_tur
            is_gunu_deger = veriler.get("pos_valor_is_gunu", True)
            if isinstance(is_gunu_deger, str):
                s = is_gunu_deger.strip().casefold()
                # "Takvim günü" → False; "İş günü" / evet / 1 → True
                is_gunu_deger = "takvim" not in s and s not in (
                    "0", "false", "hayır", "hayir", "h", "kapalı", "kapali",
                )
            kart.pos_valor_is_gunu = bool(is_gunu_deger)
            oto = veriler.get("pos_otomatik_mahsup", False)
            if isinstance(oto, str):
                s = oto.strip().casefold()
                oto = s in ("1", "true", "evet", "e", "açık", "acik") or s.startswith("eve")
            kart.pos_otomatik_mahsup = bool(oto)
            kart.kmh_limiti = _decimal(
                veriler.get("kmh_limiti") or 0, "KMH limiti", Decimal("0")
            )
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
                pb = (veriler.get("para_birimi") or "").strip().upper() or "TRY"
                if pb in {"TL", "YTL"}:
                    pb = "TRY"
                session.add(
                    FinansHesabi(
                        hesap_adi=hesap_adi,
                        hesap_turu=finans_turu,
                        acilis_bakiyesi=Decimal("0"),
                        para_birimi=pb,
                        banka_adi=banka_adi,
                        banka_karti_id=kart.id,
                        alt_hesap_turu=kod,
                        aktif=True,
                        varsayilan=(kod == "MEVDUAT"),
                    )
                )
            session.flush()
            kart_id = kart.id

        return FinansService.banka_karti_getir(kart_id)

    @staticmethod
    def alt_hesap_kaydet(veriler: dict) -> FinansHesabi:
        """Banka alt hesabının şube / IBAN / PB / bloke alanlarını kaydeder (Doc5)."""
        yazma_zorunlu("finans_duzenleme")
        hesap_id = veriler.get("hesap_id")
        if not hesap_id:
            raise ValueError("Alt hesap seçilmedi.")
        with get_session() as session:
            hesap = session.scalar(
                select(FinansHesabi)
                .options(selectinload(FinansHesabi.hareketler))
                .where(FinansHesabi.id == int(hesap_id))
            )
            if not hesap or not hesap.banka_karti_id:
                raise ValueError("Banka alt hesabı bulunamadı.")
            if "hesap_adi" in veriler:
                yeni_ad = (veriler.get("hesap_adi") or "").strip()
                if not yeni_ad:
                    raise ValueError("Hesap adı zorunludur.")
                cakisma = session.scalar(
                    select(FinansHesabi).where(
                        FinansHesabi.hesap_adi == yeni_ad,
                        FinansHesabi.id != hesap.id,
                    )
                )
                if cakisma:
                    raise ValueError("Bu hesap adı zaten kayıtlı.")
                hesap.hesap_adi = yeni_ad
            if "sube" in veriler:
                hesap.sube = (veriler.get("sube") or "").strip() or None
            if "sube_kodu" in veriler:
                hesap.sube_kodu = (veriler.get("sube_kodu") or "").strip() or None
            if "hesap_no" in veriler:
                hesap.hesap_no = (veriler.get("hesap_no") or "").strip() or None
            if "iban" in veriler:
                hesap.iban = iban_dogrula(veriler.get("iban"))
            if "aciklama" in veriler:
                hesap.aciklama = (veriler.get("aciklama") or "").strip() or None
            if "para_birimi" in veriler:
                pb = (veriler.get("para_birimi") or "TRY").strip().upper() or "TRY"
                if pb not in ("TRY", "USD", "EUR"):
                    raise ValueError("Para birimi TRY, USD veya EUR olmalıdır.")
                eski_pb = FinansService.hesap_pb(hesap)
                if eski_pb != pb and (hesap.hareketler or []):
                    raise ValueError(
                        f"Hareketi olan hesabın para birimi değiştirilemez ({eski_pb})."
                    )
                hesap.para_birimi = pb
            if "bloke_tutari" in veriler:
                hesap.bloke_tutari = _decimal(
                    veriler.get("bloke_tutari") or 0, "Bloke tutarı", Decimal("0")
                )
            if "varsayilan" in veriler:
                hesap.varsayilan = bool(veriler["varsayilan"])
                if hesap.varsayilan and hesap.banka_karti_id:
                    # Aynı bankada aynı sınıfta tek varsayılan
                    tur = (hesap.alt_hesap_turu or "").upper()
                    for diger in session.scalars(
                        select(FinansHesabi).where(
                            FinansHesabi.banka_karti_id == hesap.banka_karti_id,
                            FinansHesabi.id != hesap.id,
                        )
                    ).all():
                        if (diger.alt_hesap_turu or "").upper() == tur:
                            diger.varsayilan = False
            if "aktif" in veriler:
                hesap.aktif = bool(veriler["aktif"])
            session.flush()
            hid = hesap.id
        return FinansService.hesap_getir(hid)

    @staticmethod
    def kmh_limiti_kaydet(banka_karti_id, kmh_limiti) -> BankaKarti:
        """Sadece KMH kredi limitini günceller."""
        limit = _decimal(kmh_limiti or 0, "KMH limiti", Decimal("0"))
        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti).where(BankaKarti.id == int(banka_karti_id))
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            kart.kmh_limiti = limit
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
    def banka_manuel_hareket(
        hesap_id,
        tarih,
        tutar,
        yon,
        aciklama=None,
        belge_no=None,
        *,
        bakiye_kontrol: bool = True,
    ):
        """yon: 'giris' | 'cikis'. bakiye_kontrol=False ile eksi bakiyeye izin (aktarım)."""
        yazma_zorunlu("finans_duzenleme")
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        yon = (yon or "").strip().lower()
        if yon not in ("giris", "cikis"):
            raise ValueError("İşlem yönü giriş veya çıkış olmalıdır.")
        with get_session() as session:
            hesap = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hesap_id))
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
            )
            if not hesap:
                raise ValueError("Hesap bulunamadı.")
            if yon == "cikis":
                FinansService.cikis_kontrol(
                    hesap,
                    tutar,
                    kart=hesap.banka_karti,
                    bakiye_kontrol=bakiye_kontrol,
                )
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
        mevcut = list(session.scalars(
            select(FinansHareketi.belge_no).where(FinansHareketi.belge_no.like(like))
        ).all())
        # Kartla ödenen gider fişinin ve gider kart ödemesi iadesinin kasa/banka hareketi olmayabilir
        if on_ek == "GDF":
            mevcut += session.scalars(select(GiderFisi.belge_no).where(GiderFisi.belge_no.like(like))).all()
        elif on_ek == "KKO":
            mevcut += session.scalars(
                select(KrediKartiOdeme.belge_no).where(KrediKartiOdeme.belge_no.like(like))
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
    def _muhasebe_evrak(session, evrak_turu: str, belge_no: str, fn: str, yeniden: bool) -> None:
        """Hareket satırlarıyla tutulan evrakın kalıcı kimliğini alır; muhasebeleştirme olayını bildirir."""
        from database.finans_evrak_kimligi import kimlik_al
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook(fn, kimlik_al(session, evrak_turu, belge_no), yeniden=yeniden, session=session)

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
        from database.acik_kalem_service import AcikKalemService

        for islem in islemler:
            tutar = Decimal(str(islem.alacak or 0)) + Decimal(str(islem.borc or 0))
            if (islem.islem_turu or "") == "Tahsilat":
                CariService._aciklara_geri_al(session, islem.cari_id, tutar, belge_no)
            elif (islem.islem_turu or "") == "Ödeme":
                borc_kalemleri = list(
                    session.scalars(
                        select(SatisHareketi).where(
                            SatisHareketi.belge_no == belge_no,
                            SatisHareketi.cari_id == islem.cari_id,
                            SatisHareketi.satis_tutari > 0,
                        )
                    ).all()
                )
                if Decimal(str(islem.borc or 0)) > 0 and borc_kalemleri:
                    # Müşteriye ödeme: açık kalemi aldığı tahsisleri kaynaklarına iade ederek kaldır
                    for sh in borc_kalemleri:
                        AcikKalemService.kalem_kaldir(session, sh, neden=f"Belge geri alındı {belge_no}")
                        if Decimal(str(sh.kalan_acik_tutar)) < Decimal(str(sh.satis_tutari)):
                            raise ValueError(
                                "Bu havaleye bağlı cari açık kısmen kapanmış; güncellenemez."
                            )
                        session.delete(sh)
                    session.flush()
                    AcikKalemService.avanslari_uygula(session, islem.cari_id)
                else:
                    # Tedarikçi ödemesi: tahsisler ve fazla-ödeme avansı merkezde geri alınır
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
                masraf_h = next(
                    (h for h in hareketler if h.hareket_turu == "BANKA VİRMAN MASRAF"),
                    None,
                )
                cikis_id, cikis_kart, _ = _hesap_bilgi(cikis)
                giris_id, giris_kart, _ = _hesap_bilgi(giris)
                masraf_id, _, _ = _hesap_bilgi(masraf_h) if masraf_h else (None, None, None)
                belgeno_tutar = Decimal(str(cikis.tutar))
                ust = acik.upper()
                belge_turu = "HAVALE"
                for onek in ("VIRMAN", "HAVALE", "EFT", "FAST"):
                    if ust.startswith(onek):
                        belge_turu = onek
                        if acik.startswith(f"{onek} | "):
                            acik = acik[len(onek) + 3:].strip()
                        elif acik.upper().startswith(f"{onek}:"):
                            acik = acik.split(":", 1)[-1].strip()
                        break
                return {
                    "tur": "bvr",
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": belgeno_tutar,
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "belge_turu": belge_turu,
                    "cikis_hesap_id": cikis_id,
                    "giris_hesap_id": giris_id,
                    "cikis_banka_karti_id": cikis_kart,
                    "giris_banka_karti_id": giris_kart,
                    "masraf_tutar": Decimal(str(masraf_h.tutar)) if masraf_h else Decimal("0"),
                    "masraf_hesap_id": masraf_id,
                }

            raise ValueError("Bu belge türü banka işlem menüsünden güncellenemez.")

    @staticmethod
    @staticmethod
    def _kapatma_plani_hazirla(veriler: dict, toplam: Decimal) -> dict | None:
        """Kullanıcının açık kalem seçimi: veriler["kapatma_dagitimi"] = [{hareket_id, tutar}],
        veriler["kapatma_fazla"] = "FIFO" | "AVANS". Seçim yoksa None (kayıtta FIFO)."""
        secim = veriler.get("kapatma_dagitimi")
        if not secim:
            return None
        dagitim: dict[int, Decimal] = {}
        for s in secim:
            hid = int(s["hareket_id"])
            t = Decimal(str(s["tutar"])).quantize(Decimal("0.01"))
            if t < 0:
                raise ValueError("Dağıtım tutarı negatif olamaz.")
            if t > 0:
                dagitim[hid] = dagitim.get(hid, Decimal("0")) + t
        if sum(dagitim.values(), Decimal("0")) > toplam:
            raise ValueError("Açık kalem dağıtım toplamı belge tutarını aşamaz.")
        fazla = (veriler.get("kapatma_fazla") or "FIFO").upper()
        if fazla not in ("FIFO", "AVANS"):
            raise ValueError("Kalan tutar için FIFO veya AVANS seçilmelidir.")
        beklenen = {
            int(h): Decimal(str(t)) for h, t in (veriler.get("kapatma_beklenen") or {}).items()
        }
        return {"dagitim": dagitim, "fazla": fazla, "beklenen": beklenen}

    @staticmethod
    def _kapatma_plani_uygula(session, cari_id, tutar, belge_no, tarih, kaynak_tur, plan) -> None:
        """Alacak etkisini açık kalemlere uygular; artanı avans.

        plan (makbuz başına paylaşılan): {"dagitim": {hareket_id: kalan tahsis}, "fazla": "FIFO"|"AVANS"}.
        Satırlar sırayla işlenir; kullanıcı dağıtımı önce tüketilir.
        """
        from database.cari_service import CariService

        tutar = Decimal(str(tutar))
        if tutar <= 0:
            return
        dagitim = []
        fazla = "FIFO"
        if plan:
            fazla = plan.get("fazla") or "FIFO"
            kalan_butce = tutar
            for hid, ayrilan in list((plan.get("dagitim") or {}).items()):
                if kalan_butce <= 0:
                    break
                pay = min(Decimal(str(ayrilan)), kalan_butce)
                if pay > 0:
                    dagitim.append((int(hid), pay))
                    plan["dagitim"][hid] = Decimal(str(ayrilan)) - pay
                    kalan_butce -= pay
        CariService._alacak_uygula(
            session, cari_id, tutar, belge_no, tarih, kaynak_tur=kaynak_tur,
            dagitim=dagitim or None, fazla=fazla,
        )

    @staticmethod
    def _cari_tahsilat_satiri(
        session, cari_id, tarih, tutar, belge_no, hesap_adi, aciklama, oncelikli=None, plan=None
    ):
        """oncelikli: bağlı fatura hedefi — tutar önce o faturanın açığına, kalanı açık kalemlere uygulanır."""
        from database.models.cari import Cari, CariIslem

        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        kalan = Decimal(str(tutar))
        if oncelikli is not None and oncelikli["butce"] > 0:
            from database.acik_kalem_service import AcikKalemService, para_anahtari

            pay = min(kalan, oncelikli["butce"])
            hareket = oncelikli["hareket"]
            if hareket is not None and para_anahtari(hareket) == "TRY":
                # Onaylı faturaya düşen pay kapatma kaydıyla izlenir (Kapatma Detayı tek kaynak).
                pay = AcikKalemService.kapat(
                    session,
                    cari.id,
                    pay,
                    belge_no=belge_no,
                    kaynak_tur="TAHSILAT",
                    tarih=tarih,
                    dagitim=[(int(hareket.id), pay)],
                    fifo=False,
                ).kapanan
            else:
                FinansService._faturaya_uygula(oncelikli["fatura"], hareket, pay)
            oncelikli["butce"] -= pay
            oncelikli["uygulanan"] += pay
            kalan -= pay
        if kalan > 0:
            FinansService._kapatma_plani_uygula(session, cari.id, kalan, belge_no, tarih, "TAHSILAT", plan)
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
    def _cari_odeme_satiri(session, cari_id, tarih, tutar, belge_no, hesap_adi, aciklama, plan=None):
        from database.acik_kalem_service import AcikKalemService
        from database.models.cari import Cari, CariIslem

        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        if (cari.cari_turu or "") == "Tedarikçi":
            # Tedarikçi ödemesi defterde ALACAK (borç azaltır); fazlası açık alacak (avans).
            FinansService._kapatma_plani_uygula(session, cari.id, tutar, belge_no, tarih, "ODEME", plan)
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
            AcikKalemService.borc_etkisi(session, cari.id, tutar, belge_no=belge_no, tarih=tarih)
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
    def alt_hesaplar_listele(
        alt_turler=("MEVDUAT", "KMH", "VADELI"),
        banka_karti_id=None,
        aktif_only=True,
    ):
        """Tüm bankaların seçilen sınıf alt hesapları (Mevduat / KMH / Vadeli sınıf menüsü)."""
        turler = tuple((t or "").strip().upper() for t in (alt_turler or ()) if (t or "").strip())
        if not turler:
            turler = ("MEVDUAT", "KMH", "VADELI")
        with get_session() as session:
            q = (
                select(FinansHesabi)
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
                .where(FinansHesabi.hesap_turu.in_(("BANKA", "KREDİ KARTI")))
                .order_by(FinansHesabi.hesap_adi)
            )
            if aktif_only:
                q = q.where(FinansHesabi.aktif.is_(True))
            if banka_karti_id:
                q = q.where(FinansHesabi.banka_karti_id == int(banka_karti_id))
            sonuc = []
            for h in session.scalars(q).all():
                alt = (h.alt_hesap_turu or "").strip().upper()
                if alt in turler or (alt.startswith("VADELI") and "VADELI" in turler):
                    sonuc.append(h)
            return sonuc

    @staticmethod
    def _karta_ekstre_odemesi(session, *, kaynak, kart_hesap, ekstre_id, tarih, tutar, aciklama, dekont_no,
                              belge_no, istek_anahtari, giris) -> str:
        """Kasa / banka → kredi kartı hesabı: düz giriş yerine seçilen ekstrenin ödemesi (kart borcu bir kez düşer)."""
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from database.models.finans import KrediKartiEkstre

        if belge_no:
            raise ValueError("Kredi kartı hesabına yapılan ödeme ekstre ödemesidir; düzeltmek için ekstre "
                             "detayından ödemeyi iptal edip yeniden girin.")
        if not ekstre_id:
            raise ValueError("Kredi kartı hesabına ödeme için ödenecek ekstreyi seçin.")
        ekstre = session.get(KrediKartiEkstre, int(ekstre_id))
        kart = session.get(KrediKartiTanimi, ekstre.kredi_karti_id) if ekstre else None
        if kart is None or kart.banka_karti_id != kart_hesap.banka_karti_id:
            raise ValueError("Seçilen ekstre bu kredi kartı hesabının bankasına ait değil.")
        sonuc = KrediKartiEkstreService.odeme_yap(
            ekstre_id=int(ekstre_id), tutar=tutar, tarih=tarih, finans_hesap_id=int(kaynak.id),
            dekont_no=dekont_no, aciklama=aciklama, istek_anahtari=istek_anahtari, kaynak=giris,
            bakiye_kontrol=True, session=session)
        return sonuc["belge_no"]

    @staticmethod
    def kasadan_bankaya_yatan(
        kasa_hesap_id,
        banka_hesap_id,
        tarih,
        tutar,
        aciklama=None,
        dekont_no=None,
        belge_no=None,
        ekstre_id=None,
        istek_anahtari=None,
    ) -> str:
        """        yazma_zorunlu("finans_duzenleme")
Kasadan çıkış + banka hesabına (mevduat/KMH/vadeli) giriş. Kredi kartı hesabına yatırma ekstre ödemesidir:
ekstre seçilir, ödeme ekstre ödeme akışıyla (kart borcu ve ekstre bir kez düşer) yazılır, KKE belge no döner."""
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
            if (banka.alt_hesap_turu or "").upper() == "KREDI_KARTI":
                return FinansService._karta_ekstre_odemesi(
                    session, kaynak=kasa, kart_hesap=banka, ekstre_id=ekstre_id, tarih=tarih, tutar=tutar,
                    aciklama=aciklama, dekont_no=dekont_no, belge_no=belge_no, istek_anahtari=istek_anahtari,
                    giris="KASADAN_BANKAYA")
            kasa_pb = FinansService.hesap_pb(kasa)
            banka_pb = FinansService.hesap_pb(banka)
            if kasa_pb != banka_pb:
                raise ValueError(
                    f"Aynı PB transferi gerekir (kasa {kasa_pb}, banka {banka_pb}). "
                    "Farklı PB için döviz dönüşümü kullanın."
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
            FinansService._muhasebe_evrak(session, "kasa_banka_virman", belgeno, "kasa_banka_virman_fisi", bool(belge_no))
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
        """        yazma_zorunlu("finans_duzenleme")
Banka hesabına giriş; gönderen cari zorunlu (tahsilat)."""
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
                from database.odeme_sozu_service import OdemeSozuService

                OdemeSozuService.evrak_tutari_kontrol(session, belge_no, tutar)
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
            FinansService._muhasebe_evrak(session, "banka_havale", belgeno, "banka_havale_fisi", bool(belge_no))
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
        """        yazma_zorunlu("finans_duzenleme")
Banka hesabından çıkış; alıcı cari zorunlu (ödeme)."""
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
                from database.odeme_sozu_service import OdemeSozuService

                OdemeSozuService.evrak_tutari_kontrol(session, belge_no, tutar)
                FinansService._havale_cari_geri_al(session, belge_no)
                FinansService._finans_hareketlerini_sil(session, belge_no)
                session.flush()

            banka = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(banka_hesap_id))
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
            )
            if not banka or not banka.aktif:
                raise ValueError("Banka hesabı bulunamadı veya pasif.")
            if not FinansService._kby_hedef_uygun_mu(banka):
                raise ValueError(
                    "Hesap mevduat, KMH, kredi kartı veya vadeli hesap olmalıdır."
                )
            FinansService.cikis_kontrol(
                banka, tutar, kart=banka.banka_karti, hesap_etiket="Banka hesap"
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
            FinansService._muhasebe_evrak(session, "banka_havale", belgeno, "banka_havale_fisi", bool(belge_no))
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
        ekstre_id=None,
        istek_anahtari=None,
        masraf_tutar=None,
        masraf_hesap_id=None,
    ) -> str:
        """        yazma_zorunlu("finans_duzenleme")
Gönderen banka hesabından alıcı banka hesabına transfer/virman (VIRMAN / HAVALE / EFT / FAST).
İsteğe bağlı banka masrafı aynı fişe bağlı ayrı çıkış hareketidir. Alıcı kredi kartıysa ekstre
ödemesi olarak yazılır (ekstre seçimi zorunlu, KKE belge no döner)."""
        tutar = _decimal(tutar, "Transfer tutarı", Decimal("0.01"))
        masraf = _decimal(masraf_tutar or 0, "Masraf", Decimal("0"))
        if masraf < 0:
            raise ValueError("Masraf tutarı negatif olamaz.")
        if int(kaynak_hesap_id) == int(hedef_hesap_id):
            raise ValueError("Gönderen ve alıcı hesap aynı olamaz.")
        if tarih > date.today():
            raise ValueError("İşlem tarihi gelecek olamaz.")
        tur = (belge_turu or "HAVALE").strip().upper()
        if tur not in ("VIRMAN", "HAVALE", "EFT", "FAST"):
            raise ValueError("İşlem türü Virman, Havale, EFT veya FAST olmalıdır.")
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
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
            )
            hedef = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hedef_hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not kaynak or not kaynak.aktif:
                raise ValueError("Gönderen hesap bulunamadı veya pasif.")
            if not hedef or not hedef.aktif:
                raise ValueError("Alıcı hesap bulunamadı veya pasif.")
            if not FinansService._kby_hedef_uygun_mu(kaynak):
                raise ValueError(
                    "Gönderen hesap mevduat, KMH, kredi kartı veya vadeli olmalıdır."
                )
            if not FinansService._kby_hedef_uygun_mu(hedef):
                raise ValueError(
                    "Alıcı hesap mevduat, KMH, kredi kartı veya vadeli olmalıdır."
                )
            if (hedef.alt_hesap_turu or "").upper() == "KREDI_KARTI":
                if masraf > 0:
                    raise ValueError("Kart ekstre ödemesinde masraf bu ekrandan girilemez.")
                return FinansService._karta_ekstre_odemesi(
                    session, kaynak=kaynak, kart_hesap=hedef, ekstre_id=ekstre_id, tarih=tarih, tutar=tutar,
                    aciklama=aciklama, dekont_no=dekont_no, belge_no=belge_no, istek_anahtari=istek_anahtari,
                    giris="VIRMAN")

            masraf_hesap = kaynak
            if masraf > 0:
                mid = int(masraf_hesap_id) if masraf_hesap_id else int(kaynak.id)
                if mid == int(kaynak.id):
                    masraf_hesap = kaynak
                elif mid == int(hedef.id):
                    masraf_hesap = hedef
                else:
                    masraf_hesap = session.scalar(
                        select(FinansHesabi)
                        .where(FinansHesabi.id == mid)
                        .options(
                            selectinload(FinansHesabi.hareketler),
                            selectinload(FinansHesabi.banka_karti),
                        )
                    )
                    if not masraf_hesap or not masraf_hesap.aktif:
                        raise ValueError("Masraf hesabı bulunamadı veya pasif.")
                    if not FinansService._kby_hedef_uygun_mu(masraf_hesap):
                        raise ValueError("Masraf hesabı uygun bir banka hesabı olmalıdır.")

            cikis_toplam = tutar + (masraf if masraf_hesap.id == kaynak.id else Decimal("0"))
            FinansService.cikis_kontrol(
                kaynak, cikis_toplam, kart=kaynak.banka_karti, hesap_etiket="Gönderen hesap"
            )
            if masraf > 0 and masraf_hesap.id != kaynak.id:
                FinansService.cikis_kontrol(
                    masraf_hesap,
                    masraf,
                    kart=masraf_hesap.banka_karti,
                    hesap_etiket="Masraf hesabı",
                )

            belgeno = belge_no or FinansService._finans_belge_no(session, "BVR")
            acik = aciklama or f"{tur}: {kaynak.hesap_adi} → {hedef.hesap_adi}"
            if not acik.upper().startswith(tur):
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
            if masraf > 0:
                session.add(
                    FinansHareketi(
                        hesap_id=masraf_hesap.id,
                        tarih=tarih,
                        hareket_turu="BANKA VİRMAN MASRAF",
                        belge_no=belgeno,
                        tutar=masraf,
                        aciklama=f"MASRAF | {acik}",
                    )
                )
            session.flush()
            FinansService._muhasebe_evrak(session, "kasa_banka_virman", belgeno, "kasa_banka_virman_fisi", bool(belge_no))
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
            masraflar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(
                        FinansHareketi.hareket_turu == "BANKA VİRMAN MASRAF",
                        FinansHareketi.belge_no.in_(belge_nos),
                    )
                ).all()
            )
            masraf_map = {h.belge_no: h for h in masraflar}
            sonuc = []
            for c in cikislar:
                g = giris_map.get(c.belge_no)
                m = masraf_map.get(c.belge_no)
                acik = c.aciklama or ""
                ust = acik.upper()
                belge_turu = "—"
                for onek in ("VIRMAN", "HAVALE", "EFT", "FAST"):
                    if ust.startswith(onek) or f"| {onek}" in ust or f" {onek} " in f" {ust} ":
                        belge_turu = onek
                        break
                sonuc.append({
                    "belge_no": c.belge_no,
                    "tarih": c.tarih,
                    "tutar": Decimal(str(c.tutar)),
                    "aciklama": acik,
                    "belge_turu": belge_turu,
                    "cikis_hesap": c.hesap.hesap_adi if c.hesap else "—",
                    "giris_hesap": g.hesap.hesap_adi if g and g.hesap else "—",
                    "masraf": Decimal(str(m.tutar)) if m else Decimal("0"),
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
        """        yazma_zorunlu("finans_duzenleme")
Banka hesabından (mevduat/KMH/KK/vadeli) çıkış + kasaya giriş."""
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
                .options(
                    selectinload(FinansHesabi.hareketler),
                    selectinload(FinansHesabi.banka_karti),
                )
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
            FinansService.cikis_kontrol(
                banka, tutar, kart=banka.banka_karti, hesap_etiket="Banka hesap"
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
            FinansService._muhasebe_evrak(session, "kasa_banka_virman", belgeno, "kasa_banka_virman_fisi", bool(belge_no))
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
        yazma_zorunlu("finans_duzenleme")
        POS'a brüt giriş, taksit komisyonuna göre banka masrafı; net beklenen valörde
        hedef hesaba (mevduat veya KMH) planlanır. Otomatik mahsup kart ayarına bağlıdır.
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

        if belge_no and str(belge_no).startswith(_MAKBUZ_BAGLI_ONEKLER):
            raise ValueError("Bu POS tahsilatı bir makbuza bağlı; makbuz ekranından düzenleyin.")
        with get_session() as session:
            if belge_no:
                eski = session.scalar(
                    select(PosValorKaydi).where(PosValorKaydi.belge_no == belge_no)
                )
                if not eski:
                    raise ValueError("Güncellenecek POS tahsilat fişi bulunamadı.")
                if (eski.durum or "") != "BEKLIYOR":
                    raise ValueError("Valöre aktarılmış POS tahsilatı güncellenemez.")
                from database.muhasebe_entegrasyon import muhasebe_hook

                muhasebe_hook("pos_tahsilat_iptal", int(eski.id), "POS tahsilatı güncellendi", session=session)
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
            hedef = FinansService._pos_hedef_hesap(kart)
            if not pos or not hedef:
                raise ValueError(
                    "POS veya hedef hesap (mevduat/KMH) eksik — banka kartını kaydedin."
                )

            oran = FinansService._pos_komisyon_orani(kart, tip, n)
            if oran < 0 or oran > 100:
                raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
            komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            net = brut - komisyon
            if net < 0:
                raise ValueError("Komisyon tutarı brüt tutardan büyük olamaz.")

            valor_gun = int(kart.pos_valor_gun or 1)
            is_gunu = bool(getattr(kart, "pos_valor_is_gunu", True) if getattr(kart, "pos_valor_is_gunu", None) is not None else True)
            valor_tarihi = valor_tarihi_hesapla(tarih, valor_gun, is_gunu=is_gunu)
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
                kmh_hesap_id=hedef.id,
                hedef_hesap_id=hedef.id,
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
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("pos_tahsilat_fisi", int(kayit.id), session=session)
            return {
                "belge_no": belgeno,
                "brut": brut,
                "komisyon": komisyon,
                "komisyon_orani": oran,
                "net": net,
                "taksit_sayisi": n,
                "valor_tarihi": valor_tarihi,
                "valor_saati": POS_VALOR_SAATI,
                "hedef_hesap_id": hedef.id,
                "hedef_hesap_adi": hedef.hesap_adi,
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
    def _pos_hedef_hesap(kart) -> FinansHesabi | None:
        """Kart ayarındaki hedef alt hesap (MEVDUAT varsayılan; yoksa KMH yedek)."""
        tur = (getattr(kart, "pos_hedef_hesap_turu", None) or "MEVDUAT").strip().upper()
        if tur not in POS_HEDEF_HESAP_TURLERI:
            tur = "MEVDUAT"
        hedef = next(
            (h for h in (kart.alt_hesaplar or []) if (h.alt_hesap_turu or "").upper() == tur),
            None,
        )
        if hedef:
            return hedef
        # Yedek: diğer tür
        yedek = "KMH" if tur == "MEVDUAT" else "MEVDUAT"
        return next(
            (h for h in (kart.alt_hesaplar or []) if (h.alt_hesap_turu or "").upper() == yedek),
            None,
        )

    @staticmethod
    def pos_valor_ozet_metni(kart) -> str:
        """UI etiketleri için kısa POS valör özeti."""
        gun = int(getattr(kart, "pos_valor_gun", 1) or 1)
        is_g = getattr(kart, "pos_valor_is_gunu", True)
        if is_g is None:
            is_g = True
        tip = "iş günü" if is_g else "takvim günü"
        hedef = (getattr(kart, "pos_hedef_hesap_turu", None) or "MEVDUAT").upper()
        hedef_etiket = "Mevduat" if hedef == "MEVDUAT" else "KMH"
        oto = bool(getattr(kart, "pos_otomatik_mahsup", False))
        mahsup = "otomatik mahsup açık" if oto else "manuel mahsup"
        return f"Valör {gun} {tip} → {hedef_etiket} · {mahsup}"

    @staticmethod
    def pos_valor_vadesi_geldi_mi(kayit, simdi: datetime | None = None) -> bool:
        """Beklenen valör tarihi gelmiş mi (saat şartı yok; iş günü tarihe gömülü)."""
        simdi = simdi or datetime.now()
        return simdi.date() >= kayit.valor_tarihi

    @staticmethod
    def pos_valor_aktar(kayit_id) -> dict:
        """Bekleyen POS net bakiyesini hedef hesaba (mevduat/KMH) aktarır."""
        with get_session() as session:
            kayit = session.scalar(select(PosValorKaydi).where(PosValorKaydi.id == int(kayit_id)))
            if not kayit:
                raise ValueError("Valör kaydı bulunamadı.")
            if kayit.durum != "BEKLIYOR":
                raise ValueError("Bu kayıt zaten aktarılmış.")
            if not FinansService.pos_valor_vadesi_geldi_mi(kayit):
                raise ValueError(
                    f"Valör henüz gelmedi: {kayit.valor_tarihi.strftime('%d.%m.%Y')}"
                )
            net = Decimal(str(kayit.net_tutar))
            if net <= 0:
                kayit.durum = "AKTARILDI"
                kayit.aktarim_zamani = datetime.now()
                session.flush()
                return {"belge_no": kayit.belge_no, "net": net, "aktarildi": False}

            hedef_id = int(getattr(kayit, "hedef_hesap_id", None) or kayit.kmh_hesap_id)
            belge = kayit.belge_no
            acik = kayit.aciklama or "POS valör aktarımı"
            session.add(
                FinansHareketi(
                    hesap_id=kayit.pos_hesap_id,
                    tarih=date.today(),
                    hareket_turu="POS VALÖR AKTARIM (POS)",
                    belge_no=belge,
                    tutar=net,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=hedef_id,
                    tarih=date.today(),
                    hareket_turu="POS VALÖR AKTARIM (HEDEF)",
                    belge_no=belge,
                    tutar=net,
                    aciklama=acik,
                )
            )
            kayit.hedef_hesap_id = hedef_id
            kayit.kmh_hesap_id = hedef_id
            kayit.durum = "AKTARILDI"
            kayit.aktarim_zamani = datetime.now()
            session.flush()
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("pos_valor_aktarimi_fisi", int(kayit.id), session=session)
            return {"belge_no": belge, "net": net, "aktarildi": True, "hedef_hesap_id": hedef_id}

    @staticmethod
    def pos_valor_vadesi_gelenleri_aktar(
        banka_karti_id=None, *, sadece_otomatik: bool = False, zorla: bool = False
    ) -> list[dict]:
        """Vadesi gelmiş bekleyen valörleri hedef hesaba aktarır.

        sadece_otomatik=True: yalnızca pos_otomatik_mahsup açık kartlar (arka plan döngüsü).
        zorla=True veya manuel UI: otomatik kapalı olsa da aktarır.
        """
        bekleyenler = FinansService.pos_valor_bekleyenler(banka_karti_id=banka_karti_id)
        if not bekleyenler:
            return []
        kart_ids = {int(k.banka_karti_id) for k in bekleyenler}
        with get_session() as session:
            kartlar = {
                int(k.id): k
                for k in session.scalars(
                    select(BankaKarti).where(BankaKarti.id.in_(kart_ids))
                ).all()
            }
        sonuclar = []
        for kayit in bekleyenler:
            if not FinansService.pos_valor_vadesi_geldi_mi(kayit):
                continue
            kart = kartlar.get(int(kayit.banka_karti_id))
            oto = bool(getattr(kart, "pos_otomatik_mahsup", False)) if kart else False
            if sadece_otomatik and not oto and not zorla:
                continue
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
    def kk_ilk_taksit_oner(kart, cekim_tarihi: date) -> date:
        """Kartın ekstre/son ödeme kuralına göre 1. taksit vadesi önerisi; kural yoksa çekim günü."""
        if kart is None:
            return cekim_tarihi
        try:
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            if KrediKartiEkstreService.kesim_gunu(kart) is None:
                return cekim_tarihi
            donem = KrediKartiEkstreService.donem_bilgisi(cekim_tarihi, kart)
            return donem.get("son_odeme_tarihi") or donem.get("kesim_tarihi") or cekim_tarihi
        except Exception:
            return cekim_tarihi

    @staticmethod
    def kk_taksit_plani(
        cekim_tarihi: date,
        taksit_sayisi: int,
        tutar: Decimal,
        ilk_taksit_tarihi: date | None = None,
        kart=None,
    ) -> list[dict]:
        """Taksit planı. 1. vade = ilk_taksit_tarihi veya kart önerisi veya çekim günü.

        Kartın kesim günü varsa her taksite ``ekstre_kesim_tarihi`` yazılır; vade tercihen
        ekstrenin son ödeme tarihidir (gider kart ödemesi ile aynı kural).
        """
        n = int(taksit_sayisi)
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        toplam = Decimal(str(tutar)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        birim = (toplam / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base = ilk_taksit_tarihi or cekim_tarihi
        plan = []
        biriken = Decimal("0")
        ekstre_servis = None
        if kart is not None:
            try:
                from database.kredi_karti_ekstre_service import KrediKartiEkstreService

                if KrediKartiEkstreService.kesim_gunu(kart) is not None:
                    ekstre_servis = KrediKartiEkstreService
            except Exception:
                ekstre_servis = None
        for i in range(1, n + 1):
            if i == n:
                taksit_tutar = toplam - biriken
            else:
                taksit_tutar = birim
                biriken += birim
            kesim = None
            if ekstre_servis is not None:
                donem = ekstre_servis.taksit_donem_bilgisi(cekim_tarihi, i, kart)
                kesim = donem.get("kesim_tarihi")
                if ilk_taksit_tarihi is not None:
                    vade = FinansService._ay_ekle(base, i - 1)
                else:
                    vade = donem.get("son_odeme_tarihi") or donem.get("kesim_tarihi") or FinansService._ay_ekle(base, i - 1)
            else:
                vade = FinansService._ay_ekle(base, i - 1)
            plan.append({
                "taksit_no": i,
                "vade_tarihi": vade,
                "tutar": taksit_tutar,
                "ekstre_kesim_tarihi": kesim,
            })
        return plan

    @staticmethod
    def kredi_kartlari(banka_karti_id=None, aktif_only=True):
        with get_session() as session:
            q = (
                select(KrediKartiTanimi)
                .options(selectinload(KrediKartiTanimi.banka_karti))
                .order_by(KrediKartiTanimi.kart_adi)
            )
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
        yazma_zorunlu("finans_duzenleme")
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
                raise ValueError(f"{etiket} 1-31 arasında olmalıdır.") from hata
            if g < 1 or g > 31:
                raise ValueError(f"{etiket} 1-31 arasında olmalıdır (ayda yoksa son gün kullanılır).")
            return g

        kesim = _gun("hesap_kesim_gunu", "Hesap kesim günü")
        son_odeme = _gun("son_odeme_gunu", "Son ödeme günü")
        kesimden_sonra = veriler.get("kesimden_sonra_odeme_gun")
        if kesimden_sonra in (None, ""):
            kesimden_sonra_val = None
        else:
            try:
                kesimden_sonra_val = int(str(kesimden_sonra).strip())
                if kesimden_sonra_val < 0 or kesimden_sonra_val > 45:
                    raise ValueError("Kesimden sonra ödeme günü 0-45 arasında olmalıdır.")
            except ValueError as hata:
                raise ValueError("Kesimden sonra ödeme günü geçerli bir sayı olmalıdır.") from hata

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
            if hasattr(kart, "kesimden_sonra_odeme_gun"):
                kart.kesimden_sonra_odeme_gun = kesimden_sonra_val
            if hasattr(kart, "para_birimi"):
                kart.para_birimi = (veriler.get("para_birimi") or "TRY").strip() or "TRY"
            if hasattr(kart, "tatil_odeme_kurali"):
                kart.tatil_odeme_kurali = (
                    (veriler.get("tatil_odeme_kurali") or "AYNI_GUN").strip() or "AYNI_GUN"
                )
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
        """Kullanılan limit = toplam kart borcu (ödenen ekstre tutarları düşülmüş, gelecek taksitler dahil)."""
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        return KrediKartiEkstreService.kart_borc_ozeti(int(kredi_karti_id))["kullanilan"]

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
        ilk_taksit_tarihi=None,
    ) -> dict:
        """
        yazma_zorunlu("finans_duzenleme")
        Firma kredi kartı ile cariye ödeme.
        Tek çekim / taksitli: 1. vade = ilk_taksit_tarihi (yoksa kart ekstre önerisi / çekim günü).
        Taksitlere mümkünse ekstre kesim tarihi yazılır (Aylara Göre Ödeme Durumu ile hizalı).
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
        if belge_no and str(belge_no).startswith(_MAKBUZ_BAGLI_ONEKLER):
            raise ValueError("Bu kart ödemesi bir ödeme makbuzuna bağlı; makbuz ekranından düzenleyin.")

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
                if (eski.kaynak_turu or "CARI") != "CARI":
                    raise ValueError("Bu kart ödemesi bir gider ödemesine bağlı. Tutar, kart veya taksit planı "
                                     "değişikliği 'Kartla Gider Ödemeleri' ekranından iptal / banka iadesi ile "
                                     "yapılır; kart planı burada yeniden yazılmaz.")
                # Taksitlerden biri ödendiyse engelle
                if any((t.durum or "") == "ODENDI" for t in (eski.taksitler or [])):
                    raise ValueError("Ödenmiş taksiti olan fiş güncellenemez.")
                from database.muhasebe_entegrasyon import muhasebe_hook

                muhasebe_hook("kart_odeme_iptal", int(eski.id), "Kart ödemesi güncellendi", session=session)
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

            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            KrediKartiEkstreService.limit_kontrol(session, kk, brut)

            plan = FinansService.kk_taksit_plani(
                tarih, n, brut, ilk_taksit_tarihi=ilk_taksit_tarihi, kart=kk
            )
            vade = plan[0]["vade_tarihi"]

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
                        ekstre_kesim_tarihi=satir.get("ekstre_kesim_tarihi"),
                    )
                )
            session.flush()
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("kart_odeme_fisi", int(odeme.id), session=session)
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
            cari = session.get(Cari, o.cari_id) if (o.kaynak_turu or "CARI") == "CARI" else None
            return {
                "kaynak_turu": o.kaynak_turu or "CARI",
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
                    "cari": (cari_map.get(o.cari_id, "") if (o.kaynak_turu or "CARI") == "CARI"
                             else "Gider ödemesi (cari yok)"),
                    "kaynak_turu": o.kaynak_turu or "CARI",
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

    # --- Banka kredileri (ana para / faiz / masraf ayrımı) ---

    @staticmethod
    def _tutar_bol(toplam: Decimal, n: int) -> list[Decimal]:
        """Eşit böl; kuruş farkı son taksite."""
        toplam = Decimal(str(toplam)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if n < 1:
            raise ValueError("Taksit sayısı en az 1 olmalıdır.")
        if toplam == 0:
            return [Decimal("0.00")] * n
        birim = (toplam / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        biriken = Decimal("0")
        sonuc = []
        for i in range(1, n + 1):
            if i == n:
                sonuc.append(toplam - biriken)
            else:
                sonuc.append(birim)
                biriken += birim
        return sonuc

    @staticmethod
    def banka_kredi_taksit_plani(
        ilk_taksit_tarihi: date,
        taksit_sayisi: int,
        ana_para,
        toplam_faiz=0,
        toplam_masraf=0,
    ) -> list[dict]:
        """Ana para / faiz / masraf eşit dağıtılır; vadeler aylık aynı gün."""
        try:
            n = int(str(taksit_sayisi).strip() or "1")
        except ValueError as hata:
            raise ValueError("Taksit sayısı tam sayı olmalıdır.") from hata
        if n < 1 or n > KREDI_MAX_TAKSIT:
            raise ValueError(f"Taksit sayısı 1-{KREDI_MAX_TAKSIT} arasında olmalıdır.")
        ana = _decimal(ana_para, "Ana para", Decimal("0.01"))
        faiz = _decimal(toplam_faiz or 0, "Toplam faiz", Decimal("0"))
        masraf = _decimal(toplam_masraf or 0, "Toplam masraf", Decimal("0"))
        ana_list = FinansService._tutar_bol(ana, n)
        faiz_list = FinansService._tutar_bol(faiz, n)
        masraf_list = FinansService._tutar_bol(masraf, n)
        plan = []
        for i in range(n):
            plan.append({
                "taksit_no": i + 1,
                "vade_tarihi": FinansService._ay_ekle(ilk_taksit_tarihi, i),
                "anapara": ana_list[i],
                "faiz": faiz_list[i],
                "masraf": masraf_list[i],
                "toplam": ana_list[i] + faiz_list[i] + masraf_list[i],
            })
        return plan

    @staticmethod
    def banka_kredileri(banka_karti_id=None, aktif_only=True):
        with get_session() as session:
            q = (
                select(BankaKredisi)
                .options(selectinload(BankaKredisi.taksitler))
                .order_by(BankaKredisi.kullandirim_tarihi.desc(), BankaKredisi.id.desc())
            )
            if banka_karti_id:
                q = q.where(BankaKredisi.banka_karti_id == int(banka_karti_id))
            if aktif_only:
                q = q.where(BankaKredisi.durum == "KULLANDIRILDI")
            return list(session.scalars(q).all())

    @staticmethod
    def banka_kredi_getir(kredi_id) -> dict | None:
        with get_session() as session:
            k = session.scalar(
                select(BankaKredisi)
                .where(BankaKredisi.id == int(kredi_id))
                .options(selectinload(BankaKredisi.taksitler))
            )
            if not k:
                return None
            kalan_anapara = sum(
                (
                    Decimal(str(t.anapara))
                    for t in (k.taksitler or [])
                    if (t.durum or "") == "BEKLIYOR"
                ),
                Decimal("0"),
            )
            return {
                "id": k.id,
                "belge_no": k.belge_no,
                "banka_karti_id": k.banka_karti_id,
                "kredi_adi": k.kredi_adi,
                "kredi_turu": k.kredi_turu,
                "ana_para": Decimal(str(k.ana_para)),
                "toplam_faiz": Decimal(str(k.toplam_faiz or 0)),
                "toplam_masraf": Decimal(str(k.toplam_masraf or 0)),
                "taksit_sayisi": k.taksit_sayisi,
                "kullandirim_tarihi": k.kullandirim_tarihi,
                "ilk_taksit_tarihi": k.ilk_taksit_tarihi,
                "odeme_hesap_turu": k.odeme_hesap_turu,
                "sozlesme_no": k.sozlesme_no or "",
                "aciklama": k.aciklama or "",
                "durum": k.durum,
                "kalan_anapara": kalan_anapara,
                "taksitler": [
                    {
                        "id": t.id,
                        "taksit_no": t.taksit_no,
                        "vade_tarihi": t.vade_tarihi,
                        "anapara": Decimal(str(t.anapara)),
                        "faiz": Decimal(str(t.faiz or 0)),
                        "masraf": Decimal(str(t.masraf or 0)),
                        "toplam": Decimal(str(t.anapara))
                        + Decimal(str(t.faiz or 0))
                        + Decimal(str(t.masraf or 0)),
                        "durum": t.durum,
                        "odeme_tarihi": t.odeme_tarihi,
                        "odeme_belge_no": t.odeme_belge_no,
                        "gider_belge_no": t.gider_belge_no,
                    }
                    for t in (k.taksitler or [])
                ],
            }

    @staticmethod
    def banka_kredi_kullandir(
        banka_karti_id,
        kredi_adi,
        ana_para,
        kullandirim_tarihi,
        ilk_taksit_tarihi,
        taksit_sayisi=1,
        toplam_faiz=0,
        toplam_masraf=0,
        kredi_turu="ISLETME",
        odeme_hesap_turu="MEVDUAT",
        sozlesme_no=None,
        aciklama=None,
        taksit_plani=None,
    ) -> dict:
        """
        yazma_zorunlu("finans_duzenleme")
        Ana para: krediler hesabına borç + mevduat/KMH'ye giriş.
        Faiz ve masraf sadece taksit planında tutulur; ödeme gününde gider fişi kesilir.
        """
        ana = _decimal(ana_para, "Ana para", Decimal("0.01"))
        faiz = _decimal(toplam_faiz or 0, "Toplam faiz", Decimal("0"))
        masraf = _decimal(toplam_masraf or 0, "Toplam masraf", Decimal("0"))
        ad = (kredi_adi or "").strip()
        if not ad:
            raise ValueError("Kredi adı zorunludur.")
        tur = (kredi_turu or "ISLETME").strip().upper()
        if tur not in {k for k, _ in KREDI_TURLERI}:
            raise ValueError("Geçersiz kredi türü.")
        odeme_tur = (odeme_hesap_turu or "MEVDUAT").strip().upper()
        if odeme_tur not in {k for k, _ in KREDI_ODEME_HESAP_TURLERI}:
            raise ValueError("Ödeme / kullandırım hesabı mevduat veya KMH olmalıdır.")
        if kullandirim_tarihi > date.today():
            raise ValueError("Kullandırım tarihi gelecek olamaz.")

        if taksit_plani:
            plan = []
            for satir in taksit_plani:
                plan.append({
                    "taksit_no": int(satir["taksit_no"]),
                    "vade_tarihi": satir["vade_tarihi"],
                    "anapara": _decimal(satir.get("anapara") or 0, "Anapara", Decimal("0")),
                    "faiz": _decimal(satir.get("faiz") or 0, "Faiz", Decimal("0")),
                    "masraf": _decimal(satir.get("masraf") or 0, "Masraf", Decimal("0")),
                })
            plan.sort(key=lambda s: s["taksit_no"])
            if sum((s["anapara"] for s in plan), Decimal("0")) != ana:
                raise ValueError("Taksit anapara toplamı kredi ana parasından farklı.")
            if sum((s["faiz"] for s in plan), Decimal("0")) != faiz:
                raise ValueError("Taksit faiz toplamı toplam faizden farklı.")
            if sum((s["masraf"] for s in plan), Decimal("0")) != masraf:
                raise ValueError("Taksit masraf toplamı toplam masraftan farklı.")
        else:
            plan = FinansService.banka_kredi_taksit_plani(
                ilk_taksit_tarihi, taksit_sayisi, ana, faiz, masraf
            )

        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            kredi_hesap = next(
                (h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "KREDILER"),
                None,
            )
            nakit_hesap = next(
                (h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == odeme_tur),
                None,
            )
            if not kredi_hesap:
                raise ValueError("Krediler hesabı eksik — banka kartını kaydedin.")
            if not nakit_hesap:
                raise ValueError(f"{odeme_tur} hesabı eksik — banka kartını kaydedin.")

            belgeno = FinansService._finans_belge_no(session, "KRK")
            acik = aciklama or f"Kredi kullandırım: {ad}"
            if sozlesme_no:
                acik = f"{acik} | Sözleşme: {sozlesme_no}"

            # Ana para → krediler borcu (+)
            session.add(
                FinansHareketi(
                    hesap_id=kredi_hesap.id,
                    tarih=kullandirim_tarihi,
                    hareket_turu="KREDİ KULLANDIRIM",
                    belge_no=belgeno,
                    tutar=ana,
                    aciklama=acik,
                )
            )
            # Ana para → mevduat / KMH giriş
            session.add(
                FinansHareketi(
                    hesap_id=nakit_hesap.id,
                    tarih=kullandirim_tarihi,
                    hareket_turu="KREDİ KULLANDIRIM (MEVDUAT)",
                    belge_no=belgeno,
                    tutar=ana,
                    aciklama=acik,
                )
            )

            kredi = BankaKredisi(
                belge_no=belgeno,
                banka_karti_id=kart.id,
                kredi_adi=ad,
                kredi_turu=tur,
                ana_para=ana,
                toplam_faiz=faiz,
                toplam_masraf=masraf,
                taksit_sayisi=len(plan),
                kullandirim_tarihi=kullandirim_tarihi,
                ilk_taksit_tarihi=ilk_taksit_tarihi,
                odeme_hesap_turu=odeme_tur,
                sozlesme_no=(sozlesme_no or "").strip() or None,
                aciklama=(aciklama or "").strip() or None,
                durum="KULLANDIRILDI",
            )
            session.add(kredi)
            session.flush()
            for satir in plan:
                session.add(
                    BankaKrediTaksit(
                        kredi_id=kredi.id,
                        taksit_no=satir["taksit_no"],
                        vade_tarihi=satir["vade_tarihi"],
                        anapara=satir["anapara"],
                        faiz=satir["faiz"],
                        masraf=satir["masraf"],
                        durum="BEKLIYOR",
                    )
                )
            session.flush()
            kredi_id = kredi.id
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("banka_kredi_kullandirim_fisi", int(kredi_id), session=session)

        return FinansService.banka_kredi_getir(kredi_id)

    @staticmethod
    def banka_kredi_bekleyen_taksitler(banka_karti_id, limit=300):
        with get_session() as session:
            q = (
                select(BankaKrediTaksit)
                .join(BankaKredisi)
                .where(
                    BankaKredisi.banka_karti_id == int(banka_karti_id),
                    BankaKredisi.durum == "KULLANDIRILDI",
                    BankaKrediTaksit.durum == "BEKLIYOR",
                )
                .options(selectinload(BankaKrediTaksit.kredi))
                .order_by(BankaKrediTaksit.vade_tarihi, BankaKrediTaksit.id)
                .limit(limit)
            )
            sonuc = []
            for t in session.scalars(q).all():
                k = t.kredi
                anapara = Decimal(str(t.anapara))
                faiz = Decimal(str(t.faiz or 0))
                masraf = Decimal(str(t.masraf or 0))
                sonuc.append({
                    "taksit_id": t.id,
                    "kredi_id": k.id if k else None,
                    "belge_no": k.belge_no if k else "",
                    "kredi_adi": k.kredi_adi if k else "",
                    "taksit_no": t.taksit_no,
                    "taksit_sayisi": k.taksit_sayisi if k else 0,
                    "vade_tarihi": t.vade_tarihi,
                    "anapara": anapara,
                    "faiz": faiz,
                    "masraf": masraf,
                    "toplam": anapara + faiz + masraf,
                    "odeme_hesap_turu": k.odeme_hesap_turu if k else "MEVDUAT",
                })
            return sonuc

    @staticmethod
    def banka_kredi_taksit_detay(taksit_id) -> dict:
        with get_session() as session:
            t = session.scalar(
                select(BankaKrediTaksit)
                .where(BankaKrediTaksit.id == int(taksit_id))
                .options(selectinload(BankaKrediTaksit.kredi))
            )
            if not t or not t.kredi:
                raise ValueError("Taksit bulunamadı.")
            anapara = Decimal(str(t.anapara))
            faiz = Decimal(str(t.faiz or 0))
            masraf = Decimal(str(t.masraf or 0))
            return {
                "taksit_id": t.id,
                "kredi_id": t.kredi.id,
                "kredi_adi": t.kredi.kredi_adi,
                "taksit_no": t.taksit_no,
                "taksit_sayisi": t.kredi.taksit_sayisi,
                "vade_tarihi": t.vade_tarihi,
                "anapara": anapara,
                "faiz": faiz,
                "masraf": masraf,
                "toplam": anapara + faiz + masraf,
                "odeme_hesap_turu": t.kredi.odeme_hesap_turu or "MEVDUAT",
                "durum": t.durum,
            }

    @staticmethod
    def banka_kredi_taksit_ode(taksit_id, odeme_tarihi=None, aciklama=None) -> dict:
        """
        Eski UI uyumluluğu — tek banka çıkışlı yeni ödeme akışına yönlendirir.
        Bkz. BankaKrediService.taksit_ode (toplam tutar tek hareket, bileşenler
        gider fişi olarak yazılır).
        """
        from database.banka_kredi_service import BankaKrediService

        return BankaKrediService.taksit_ode(
            taksit_id=taksit_id,
            odeme_tarihi=odeme_tarihi,
            aciklama=aciklama,
            odeme_turu="TAKSIT",
        )

    # --- Gider fişi (cari yok, hizmet kartı zorunlu) ---

    @staticmethod
    def gider_fisi_odeme_hesaplari():
        """Kasa + mevduat / KMH — POS, krediler ve kredi kartı hariç (kartla ödeme ayrı yöntemdir)."""
        with get_session() as session:
            hesaplar = list(
                session.scalars(
                    select(FinansHesabi)
                    .options(selectinload(FinansHesabi.hareketler), selectinload(FinansHesabi.banka_karti))
                    .where(FinansHesabi.aktif.is_(True))
                    .order_by(FinansHesabi.hesap_turu, FinansHesabi.hesap_adi)
                ).all()
            )
            sonuc = []
            for h in hesaplar:
                alt = (h.alt_hesap_turu or "").upper()
                tur = (h.hesap_turu or "").upper()
                if tur == "KASA":
                    sonuc.append(h)
                elif tur == "BANKA" and alt in ("MEVDUAT", "KMH"):
                    sonuc.append(h)
            return sonuc

    @staticmethod
    def gider_fisi_listele(limit=300):
        from database.models.hizmet import HizmetKarti

        with get_session() as session:
            fisler = list(
                session.scalars(
                    select(GiderFisi)
                    .options(selectinload(GiderFisi.finans_hesap))
                    .where(GiderFisi.gider_turu == "HIZMET")
                    .order_by(GiderFisi.tarih.desc(), GiderFisi.id.desc())
                    .limit(limit)
                ).all()
            )
            for fis in fisler:
                if fis.hizmet_id:
                    fis.hizmet = session.get(HizmetKarti, fis.hizmet_id)
                else:
                    fis.hizmet = None
            return fisler

    @staticmethod
    def gider_fisi_getir(fisi_id):
        from database.models.hizmet import HizmetKarti

        with get_session() as session:
            fis = session.scalar(
                select(GiderFisi)
                .options(selectinload(GiderFisi.finans_hesap))
                .where(GiderFisi.id == int(fisi_id))
            )
            if fis and fis.hizmet_id:
                fis.hizmet = session.get(HizmetKarti, fis.hizmet_id)
            elif fis:
                fis.hizmet = None
            return fis

    @staticmethod
    def gider_fisi_kaydet(veriler: dict) -> GiderFisi:
        """        yazma_zorunlu("finans_duzenleme")
Cari olmadan kasa/bankadan gider; hizmet kartı zorunlu."""
        with get_session() as session:
            fis = FinansService._gider_fisi_yaz(session, veriler)
            fis_id = fis.id
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("gider_fisi_fisi", fis_id, session=session)
        return FinansService.gider_fisi_getir(fis_id)

    @staticmethod
    def _gider_fisi_yaz(session, veriler: dict, *, kart_hesabi: FinansHesabi | None = None) -> GiderFisi:
        """Gider fişi satırları (muhasebe olayı hariç). ``kart_hesabi`` verilirse kartla ödenen gider:
        kasa/banka çıkışı ve bakiye denetimi yoktur; kart borcu kart ödemesi hareketinde izlenir."""
        from database.models.hizmet import HizmetHareketi, HizmetKarti
        from database.sube_service import SubeService

        tarih = veriler["tarih"]
        if isinstance(tarih, str):
            raise ValueError("Tarih geçersiz.")
        if tarih > date.today():
            raise ValueError("Tarih gelecek olamaz.")
        tutar = _decimal(veriler.get("tutar"), "Tutar", Decimal("0.01"))
        hizmet_id = int(veriler["hizmet_id"])
        aciklama = (veriler.get("aciklama") or "").strip() or None

        sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
        if kart_hesabi is not None:
            hesap = kart_hesabi
        else:
            hesap = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(veriler["finans_hesap_id"]))
                .options(selectinload(FinansHesabi.hareketler), selectinload(FinansHesabi.banka_karti))
            )
            if not hesap or not hesap.aktif:
                raise ValueError("Ödeme hesabı bulunamadı.")
            if (hesap.alt_hesap_turu or "").upper() == "KREDI_KARTI":
                raise ValueError("Kredi kartıyla ödenen gider için ödeme yöntemi olarak 'Kredi kartı' seçin "
                                 "(kart, taksit planı ve ekstre dönemi girilir).")
        hizmet = session.get(HizmetKarti, hizmet_id)
        if not hizmet or not hizmet.aktif:
            raise ValueError("Gider hizmet kartı seçin.")
        if (hizmet.hizmet_turu or "").upper() != "GIDER":
            raise ValueError("Yalnızca gider hizmet kartı seçilebilir.")

        belge_no = FinansService._finans_belge_no(session, "GDF")
        acik = aciklama or f"{hizmet.hizmet_kodu} — {hizmet.hizmet_adi}"
        if kart_hesabi is None:
            FinansService.cikis_kontrol(hesap, tutar, kart=hesap.banka_karti)
            session.add(
                FinansHareketi(
                    hesap_id=hesap.id,
                    tarih=tarih,
                    hareket_turu="GİDER FİŞİ",
                    belge_no=belge_no,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
        fis = GiderFisi(
            belge_no=belge_no,
            sube_id=sube_id,
            tarih=tarih,
            gider_turu="HIZMET",
            tutar=tutar,
            finans_hesap_id=hesap.id,
            hizmet_id=hizmet.id,
            aciklama=acik,
            durum="AÇIK",
        )
        session.add(fis)
        session.add(
            HizmetHareketi(
                hizmet_id=hizmet.id,
                tarih=tarih,
                hareket_turu="GİDER FİŞİ",
                belge_no=belge_no,
                miktar=Decimal("1"),
                birim_fiyat=tutar,
                kdv_orani=Decimal(str(hizmet.kdv_orani or 0)),
                tutar=tutar,
                isaret=-1,
                cari_id=None,
                aciklama=acik,
            )
        )
        session.flush()
        return fis

    @staticmethod
    def gider_fisi_iptal(fisi_id):
        yazma_zorunlu("finans_duzenleme", "iptal")
        from database.masraf_dagitim_service import KAYNAK_GIDER_FISI, MasrafDagitimService

        MasrafDagitimService.kilit_kontrol(kaynak_id=int(fisi_id), kaynak_turu=KAYNAK_GIDER_FISI)
        with get_session() as session:
            fis = session.get(GiderFisi, int(fisi_id))
            if not fis:
                raise ValueError("Gider fişi bulunamadı.")
            from database.gider_kart_odeme_service import fis_karta_bagli_mi

            if fis_karta_bagli_mi(session, int(fis.id)):
                raise ValueError("Bu gider fişi kredi kartıyla ödendi. Fiş, kart ödemesi ve taksit planı birlikte "
                                 "'Kartla Gider Ödemeleri' ekranından iptal edilir.")
            FinansService._gider_fisi_iptal_yaz(session, fis)
        MasrafDagitimService.sahipsiz_taslaklari_kapat()

    @staticmethod
    def _gider_fisi_iptal_yaz(session, fis: GiderFisi) -> None:
        from database.masraf_dagitim_service import KAYNAK_GIDER_FISI, MasrafDagitimService
        from database.models.hizmet import HizmetHareketi

        if fis.durum == "IPTAL":
            raise ValueError("Fiş zaten iptal.")
        if (fis.gider_turu or "") != "HIZMET":
            raise ValueError("Bu fiş buradan iptal edilemez.")
        session.execute(
            delete(FinansHareketi).where(
                FinansHareketi.belge_no == fis.belge_no,
                FinansHareketi.hareket_turu.in_(("GİDER FİŞİ", "KK GİDER")),
            )
        )
        session.execute(
            delete(HizmetHareketi).where(
                HizmetHareketi.belge_no == fis.belge_no,
                HizmetHareketi.hareket_turu == "GİDER FİŞİ",
            )
        )
        MasrafDagitimService.bagli_taslaklari_iptal(
            session, kaynak_turu=KAYNAK_GIDER_FISI, kaynak_id=int(fis.id),
            neden=f"Kaynak gider fişi {fis.belge_no} iptal edildi.",
        )
        fis.durum = "IPTAL"
        session.flush()
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("gider_fisi_iptal", int(fis.id), f"Gider fişi iptal {fis.belge_no}", session=session)

    # --- Kasa tahsilat / ödeme makbuzu ---

    @staticmethod
    def kasa_hesaplari(aktif_only=True):
        with get_session() as session:
            q = (
                select(FinansHesabi)
                .options(selectinload(FinansHesabi.hareketler))
                .where(FinansHesabi.hesap_turu == "KASA")
                .order_by(FinansHesabi.hesap_adi)
            )
            if aktif_only:
                q = q.where(FinansHesabi.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def kasa_makbuz_getir(makbuz_id):
        from database.models.cari import Cari

        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .options(
                    selectinload(KasaMakbuzu.finans_hesap),
                    selectinload(KasaMakbuzu.satirlar).selectinload(KasaMakbuzSatiri.finans_hesap),
                )
                .where(KasaMakbuzu.id == int(makbuz_id))
            )
            if makbuz:
                makbuz.cari = session.get(Cari, makbuz.cari_id)
                bag = FinansService._fatura_bagi(session, makbuz.id)
                makbuz.bagli_fatura_id = int(bag.fatura_id) if bag else None
                makbuz.bagli_fatura_no = bag.fatura_no if bag else None
            return makbuz

    @staticmethod
    def kasa_makbuz_belge_no_ile(belge_no: str):
        from database.models.cari import Cari

        belge_no = (belge_no or "").strip()
        if not belge_no:
            return None
        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .options(
                    selectinload(KasaMakbuzu.finans_hesap),
                    selectinload(KasaMakbuzu.satirlar).selectinload(KasaMakbuzSatiri.finans_hesap),
                )
                .where(KasaMakbuzu.belge_no == belge_no)
            )
            if makbuz:
                makbuz.cari = session.get(Cari, makbuz.cari_id)
            return makbuz

    @staticmethod
    def gider_fisi_belge_no_ile(belge_no: str):
        from database.models.hizmet import HizmetKarti

        belge_no = (belge_no or "").strip()
        if not belge_no:
            return None
        with get_session() as session:
            fis = session.scalar(
                select(GiderFisi)
                .options(selectinload(GiderFisi.finans_hesap))
                .where(GiderFisi.belge_no == belge_no)
            )
            if fis and fis.hizmet_id:
                fis.hizmet = session.get(HizmetKarti, fis.hizmet_id)
            elif fis:
                fis.hizmet = None
            return fis

    @staticmethod
    def kasa_makbuz_listele(
        makbuz_turu=None,
        limit=300,
        *,
        arama: str | None = None,
        baslangic: date | None = None,
        bitis: date | None = None,
        durum: str | None = None,
        odeme_sekli: str | None = None,
    ):
        """Makbuz listesi. arama: makbuz no / belge no / cari / açıklama (I/ı duyarsız, herhangi bir yer).

        odeme_sekli: yalnız bu ödeme yöntemiyle en az bir satırı olan makbuzlar.
        """
        from database.models.cari import Cari
        from database.turkce_normalize import turkce_normalize

        with get_session() as session:
            q = (
                select(KasaMakbuzu)
                .options(
                    selectinload(KasaMakbuzu.finans_hesap),
                    selectinload(KasaMakbuzu.satirlar).selectinload(KasaMakbuzSatiri.finans_hesap),
                )
                .order_by(KasaMakbuzu.tarih.desc(), KasaMakbuzu.id.desc())
            )
            if makbuz_turu:
                q = q.where(KasaMakbuzu.makbuz_turu == str(makbuz_turu).upper())
            if baslangic:
                q = q.where(KasaMakbuzu.tarih >= baslangic)
            if bitis:
                q = q.where(KasaMakbuzu.tarih <= bitis)
            if durum:
                q = q.where(KasaMakbuzu.durum == durum)
            if odeme_sekli:
                q = q.where(KasaMakbuzu.satirlar.any(KasaMakbuzSatiri.odeme_sekli == odeme_sekli))
            aranan = turkce_normalize(arama or "").strip()
            if not aranan:
                q = q.limit(limit)
            makbuzlar = list(session.scalars(q).all())
            cari_ids = {m.cari_id for m in makbuzlar if m.cari_id}
            cari_map = {}
            if cari_ids:
                for c in session.scalars(select(Cari).where(Cari.id.in_(cari_ids))).all():
                    cari_map[c.id] = c
            for m in makbuzlar:
                m.cari = cari_map.get(m.cari_id)
            if aranan:
                def _eslesir(m) -> bool:
                    cari = m.cari
                    metin = " ".join(
                        str(x or "")
                        for x in (
                            m.makbuz_no,
                            m.belge_no,
                            getattr(cari, "cari_kodu", ""),
                            getattr(cari, "unvan", ""),
                            m.aciklama,
                        )
                    )
                    return aranan in turkce_normalize(metin)

                makbuzlar = [m for m in makbuzlar if _eslesir(m)][:limit]
            return makbuzlar

    @staticmethod
    def kasa_tahsilat_makbuzu_kaydet(veriler: dict) -> KasaMakbuzu:
        """Cari tahsilat makbuzu. Belge: TMK-YYYY-#### — tek veya çok satır (kasa/havale/POS)."""
        return FinansService._kasa_makbuz_kaydet(veriler, makbuz_turu="TAHSILAT")

    @staticmethod
    def kasa_odeme_makbuzu_kaydet(veriler: dict) -> KasaMakbuzu:
        """Cari ödeme makbuzu. Belge: OMK-YYYY-#### — tek veya çok satır."""
        return FinansService._kasa_makbuz_kaydet(veriler, makbuz_turu="ODEME")

    @staticmethod
    def _makbuz_satirlarini_normalize(veriler: dict, makbuz_turu: str) -> list[dict]:
        """satirlar listesi veya eski tek satır alanlarından normalize satır listesi üretir."""
        ham = veriler.get("satirlar")
        satirlar: list[dict] = []
        if ham:
            for i, s in enumerate(ham, start=1):
                if not isinstance(s, dict):
                    continue
                tutar = _decimal(s.get("tutar"), f"Satır {i} tutarı", Decimal("0.01"))
                sekil = (s.get("odeme_sekli") or "").strip()
                hesap_adi = (s.get("hesap") or s.get("hesap_adi") or "").strip()
                hesap_id = s.get("finans_hesap_id")
                if not sekil:
                    raise ValueError(f"Satır {i}: ödeme şekli seçin.")
                satir_tarih = s.get("tarih") or s.get("tahsilat_tarihi")
                kk_id = s.get("kredi_karti_id")
                sekil_turu = _makbuz_sekil_turu(sekil)
                if makbuz_turu == "ODEME" and sekil_turu == "KART":
                    if not kk_id:
                        raise ValueError(f"Satır {i}: ödeme yapılacak şirket kredi kartını seçin.")
                elif not hesap_adi and not hesap_id:
                    raise ValueError(f"Satır {i}: hesap seçin.")
                try:
                    taksit = int(str(s.get("taksit_sayisi") or 1).strip() or "1")
                except ValueError as hata:
                    raise ValueError(f"Satır {i}: taksit sayısı tam sayı olmalıdır.") from hata
                satirlar.append(
                    {
                        "sira_no": int(s.get("sira_no") or i),
                        "tarih": satir_tarih,
                        "odeme_sekli": sekil,
                        "sekil_turu": sekil_turu,
                        "hesap_adi": hesap_adi or None,
                        "finans_hesap_id": int(hesap_id) if hesap_id else None,
                        "tutar": tutar,
                        "aciklama": (s.get("aciklama") or "").strip() or None,
                        "kart_tipi": (s.get("kart_tipi") or "").strip().upper() or None,
                        "taksit_sayisi": taksit,
                        "kredi_karti_id": int(kk_id) if kk_id else None,
                    }
                )
        if not satirlar:
            if not veriler.get("finans_hesap_id"):
                raise ValueError(
                    "En az bir tahsilat satırı ekleyin."
                    if makbuz_turu == "TAHSILAT"
                    else "En az bir ödeme satırı ekleyin."
                )
            tutar = _decimal(veriler.get("tutar"), "Tutar", Decimal("0.01"))
            satirlar.append(
                {
                    "sira_no": 1,
                    "tarih": veriler.get("tarih"),
                    "odeme_sekli": "NAKİT / KASA",
                    "sekil_turu": "KASA",
                    "hesap_adi": None,
                    "finans_hesap_id": int(veriler["finans_hesap_id"]),
                    "tutar": tutar,
                    "aciklama": (veriler.get("aciklama") or "").strip() or None,
                    "kart_tipi": None,
                    "taksit_sayisi": 1,
                    "kredi_karti_id": None,
                }
            )
        return satirlar

    @staticmethod
    def kasa_makbuz_guncelle(makbuz_id, veriler: dict) -> KasaMakbuzu:
        """Kayıtlı makbuzu aynı belge no ile yeniden yazar (eski cari/finans/kart etkileri geri alınır)."""
        with get_session() as session:
            makbuz = session.get(KasaMakbuzu, int(makbuz_id))
            if not makbuz:
                raise ValueError("Makbuz bulunamadı.")
            tur = makbuz.makbuz_turu
        return FinansService._kasa_makbuz_kaydet(veriler, makbuz_turu=tur, makbuz_id=int(makbuz_id))

    @staticmethod
    def makbuz_no_oner() -> str:
        """Sıradaki MKB numarası — yalnız öneri; numara kayıt anında kesinleşir."""
        with get_session() as session:
            return FinansService._makbuz_no_sonraki(session)

    @staticmethod
    def makbuz_no_kullanimda_mi(makbuz_no: str, haric_makbuz_id=None, haric_virman_id=None) -> bool:
        with get_session() as session:
            return FinansService._makbuz_no_var(session, makbuz_no, haric_makbuz_id, haric_virman_id)

    @staticmethod
    def _virman_tablosu_var(session) -> bool:
        from sqlalchemy import inspect as sa_inspect

        return sa_inspect(session.connection()).has_table(CariVirmanMakbuzu.__tablename__)

    @staticmethod
    def _makbuz_no_sonraki(session) -> str:
        """Kasa makbuzları ve cari virman makbuzları ortak MKB serisini kullanır."""
        en_buyuk = 0
        sorgular = [select(KasaMakbuzu.makbuz_no).where(KasaMakbuzu.makbuz_no.like(f"{MAKBUZ_NO_ONEK}-%"))]
        if FinansService._virman_tablosu_var(session):
            sorgular.append(
                select(CariVirmanMakbuzu.makbuz_no).where(CariVirmanMakbuzu.makbuz_no.like(f"{MAKBUZ_NO_ONEK}-%"))
            )
        for sorgu in sorgular:
            for no in session.scalars(sorgu).all():
                eslesme = _MAKBUZ_NO_RE.fullmatch((no or "").strip().upper())
                if eslesme:
                    en_buyuk = max(en_buyuk, int(eslesme.group(1)))
        # 5 hane dolunca biçim kendiliğinden genişler (MKB-100000)
        return f"{MAKBUZ_NO_ONEK}-{en_buyuk + 1:05d}"

    @staticmethod
    def _makbuz_no_var(session, makbuz_no: str, haric_makbuz_id=None, haric_virman_id=None) -> bool:
        anahtar = (makbuz_no or "").strip().upper()
        if not anahtar:
            return False
        q = select(KasaMakbuzu.id).where(func.upper(func.trim(KasaMakbuzu.makbuz_no)) == anahtar)
        if haric_makbuz_id:
            q = q.where(KasaMakbuzu.id != int(haric_makbuz_id))
        if session.scalar(q.limit(1)) is not None:
            return True
        if not FinansService._virman_tablosu_var(session):
            return False
        q = select(CariVirmanMakbuzu.id).where(func.upper(func.trim(CariVirmanMakbuzu.makbuz_no)) == anahtar)
        if haric_virman_id:
            q = q.where(CariVirmanMakbuzu.id != int(haric_virman_id))
        return session.scalar(q.limit(1)) is not None

    @staticmethod
    def cari_bakiye_ozeti(cari_id) -> dict:
        """Makbuz ekranı: güncel net bakiye ve yönü (borç − alacak; firma veritabanına göre)."""
        from database.cari_bakiye_service import net_bakiye
        from database.cari_ortalama_valor_service import _yon_etiket

        bakiye = Decimal(str(net_bakiye(int(cari_id))["bakiye"]))
        return {"bakiye": bakiye, "tutar": abs(bakiye), "yon": _yon_etiket(bakiye)[2]}

    @staticmethod
    def sirket_kredi_kartlari() -> list[dict]:
        """Tedarikçi ödemesinde seçilebilecek aktif şirket kredi kartları."""
        with get_session() as session:
            kartlar = session.scalars(
                select(KrediKartiTanimi)
                .where(KrediKartiTanimi.aktif.is_(True))
                .options(selectinload(KrediKartiTanimi.banka_karti))
                .order_by(KrediKartiTanimi.kart_adi)
            ).all()
            sonuc = []
            for k in kartlar:
                banka = k.banka_karti.banka_adi if k.banka_karti else ""
                son4 = f" ****{k.son_dort_hane}" if k.son_dort_hane else ""
                sonuc.append(
                    {
                        "id": k.id,
                        "etiket": f"{k.kart_adi}{son4} — {banka}".strip(" —"),
                        "banka_karti_id": k.banka_karti_id,
                    }
                )
            return sonuc

    @staticmethod
    def _kasa_makbuz_kaydet(veriler: dict, makbuz_turu: str, makbuz_id=None) -> KasaMakbuzu:
        yazma_zorunlu("finans_duzenleme")
        FinansService.fatura_makbuz_bag_tablosu_hazirla()
        otomatik = bool(veriler.get("makbuz_no_otomatik"))
        son_hata = None
        for deneme in range(8):
            try:
                kayit_id = FinansService._kasa_makbuz_yaz(
                    veriler, makbuz_turu, otomatik=otomatik, makbuz_id=makbuz_id
                )
                return FinansService.kasa_makbuz_getir(kayit_id)
            except IntegrityError as hata:
                metin = str(getattr(hata, "orig", hata))
                if "ux_kasa_makbuz_no" in metin and not otomatik:
                    no = (veriler.get("makbuz_no") or "").strip()
                    raise ValueError(
                        f"{no} numaralı makbuz bu firmada zaten var. Farklı bir numara girin."
                    ) from hata
                son_hata = hata
            except OperationalError as hata:
                if "locked" not in str(hata).lower():
                    raise
                son_hata = hata
            # Eş zamanlı kayıt: numara/belge çakıştı veya yazma kilidi — yeniden numara alınır
            time.sleep(0.05 * (deneme + 1))
        raise ValueError(
            "Makbuz kaydedilemedi: başka bir kullanıcıyla numara çakışması sürüyor. Tekrar deneyin."
        ) from son_hata

    @staticmethod
    def _kasa_makbuz_yaz(veriler: dict, makbuz_turu: str, *, otomatik: bool, makbuz_id=None) -> int:
        from database.models.cari import Cari

        tarih = veriler.get("tarih")
        if isinstance(tarih, str) or tarih is None:
            raise ValueError("Tarih geçersiz.")
        if tarih > date.today():
            raise ValueError("Tarih gelecek olamaz.")
        raw_cari = veriler.get("cari_id")
        if raw_cari in (None, "", 0, "0"):
            raise ValueError("Cari hesap seçin.")
        try:
            cari_id = int(raw_cari)
        except (TypeError, ValueError) as hata:
            raise ValueError("Cari hesap seçin.") from hata
        if cari_id <= 0:
            raise ValueError("Cari hesap seçin.")
        makbuz_no = (veriler.get("makbuz_no") or "").strip() or None
        aciklama = (veriler.get("aciklama") or "").strip() or None
        tur = makbuz_turu.upper()
        if tur not in ("TAHSILAT", "ODEME"):
            raise ValueError("Makbuz türü geçersiz.")

        satir_verileri = FinansService._makbuz_satirlarini_normalize(veriler, tur)
        toplam = sum((s["tutar"] for s in satir_verileri), Decimal("0"))
        if toplam <= 0:
            raise ValueError("Toplam tutar sıfırdan büyük olmalı.")
        kapatma_plani = FinansService._kapatma_plani_hazirla(veriler, toplam)

        with get_session() as session:
            from database.sube_service import SubeService

            sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari hesap seçin.")

            mevcut = None
            if makbuz_id:
                mevcut = session.get(KasaMakbuzu, int(makbuz_id))
                if not mevcut:
                    raise ValueError("Makbuz bulunamadı.")
                if (mevcut.makbuz_turu or "") != tur:
                    raise ValueError("Makbuz türü değiştirilemez.")
                if mevcut.durum == "IPTAL":
                    raise ValueError("İptal edilmiş makbuz düzenlenemez.")
                from database.odeme_sozu_service import OdemeSozuService

                OdemeSozuService.evrak_tutari_kontrol(session, mevcut.belge_no, toplam)
                FinansService._makbuz_etkilerini_geri_al(session, mevcut, iptal=False)
                mevcut.satirlar.clear()
                session.flush()

            fatura_hedefi, bag = (
                FinansService._makbuz_fatura_hedefi(session, veriler.get("fatura_id"), mevcut, cari_id)
                if tur == "TAHSILAT"
                else (None, None)
            )
            if kapatma_plani and kapatma_plani.get("beklenen"):
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.beklenen_dogrula(session, cari_id, kapatma_plani["beklenen"])

            if otomatik:
                makbuz_no = FinansService._makbuz_no_sonraki(session)
            elif makbuz_no and FinansService._makbuz_no_var(
                session, makbuz_no, mevcut.id if mevcut else None
            ):
                raise ValueError(
                    f"{makbuz_no} numaralı makbuz bu firmada zaten var. Farklı bir numara girin."
                )

            cozulmus: list[tuple[dict, FinansHesabi, str, object]] = []
            for s in satir_verileri:
                satir_tarih = s.get("tarih") or tarih
                if isinstance(satir_tarih, str):
                    raise ValueError(f"Satır {s['sira_no']}: tarih geçersiz.")
                if satir_tarih > date.today():
                    raise ValueError(f"Satır {s['sira_no']}: tarih gelecek olamaz.")
                s = dict(s)
                s["tarih"] = satir_tarih
                sekil_turu = s.get("sekil_turu")

                if tur == "ODEME" and sekil_turu == "KART":
                    kk = session.get(KrediKartiTanimi, int(s["kredi_karti_id"]))
                    if not kk or not kk.aktif:
                        raise ValueError(
                            f"Satır {s['sira_no']}: şirket kredi kartı bulunamadı veya pasif."
                        )
                    kk_hesap = session.scalar(
                        select(FinansHesabi).where(
                            FinansHesabi.banka_karti_id == kk.banka_karti_id,
                            FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                        )
                    )
                    if not kk_hesap or not kk_hesap.aktif:
                        raise ValueError(
                            f"Satır {s['sira_no']}: kartın bankasında kredi kartı hesabı yok — banka kartını kaydedin."
                        )
                    cozulmus.append((s, kk_hesap, "KK", kk))
                    continue

                hesap = None
                if s.get("finans_hesap_id"):
                    hesap = session.scalar(
                        select(FinansHesabi)
                        .where(FinansHesabi.id == int(s["finans_hesap_id"]))
                        .options(selectinload(FinansHesabi.hareketler))
                    )
                elif s.get("hesap_adi"):
                    hesap = session.scalar(
                        select(FinansHesabi)
                        .where(FinansHesabi.hesap_adi == s["hesap_adi"])
                        .options(selectinload(FinansHesabi.hareketler))
                    )
                if not hesap or not hesap.aktif:
                    raise ValueError(f"Satır {s['sira_no']}: hesap bulunamadı.")
                tek_eski = (
                    not veriler.get("satirlar")
                    and len(satir_verileri) == 1
                    and s.get("finans_hesap_id")
                    and not s.get("hesap_adi")
                )
                if tek_eski and (hesap.hesap_turu or "").upper() != "KASA":
                    raise ValueError("Yalnızca kasa hesabı seçilebilir.")
                FinansService._makbuz_hesap_uyumu(s, hesap, tur)

                if tur == "TAHSILAT" and sekil_turu == "KART":
                    kart = session.scalar(
                        select(BankaKarti)
                        .where(BankaKarti.id == int(hesap.banka_karti_id))
                        .options(
                            selectinload(BankaKarti.alt_hesaplar),
                            selectinload(BankaKarti.pos_taksit_komisyonlari),
                        )
                    )
                    kmh = next(
                        (h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "KMH"), None
                    ) if kart else None
                    if not kart or not kmh:
                        raise ValueError(
                            f"Satır {s['sira_no']}: POS hesabının KMH hesabı eksik — banka kartını kaydedin."
                        )
                    cozulmus.append((s, hesap, "POS", (kart, kmh)))
                    continue

                if tur == "ODEME":
                    FinansService.cikis_kontrol(hesap, s["tutar"])
                cozulmus.append((s, hesap, "NORMAL", None))

            if mevcut is not None:
                belge_no = mevcut.belge_no
            else:
                on_ek = "TMK" if tur == "TAHSILAT" else "OMK"
                belge_no = FinansService._finans_belge_no(session, on_ek)
                # İptal edilen makbuzun finans hareketi silinir ama belge numarası makbuzda kalır
                kullanilan = set(
                    session.scalars(
                        select(KasaMakbuzu.belge_no).where(
                            KasaMakbuzu.belge_no.like(belge_no.rsplit("-", 1)[0] + "-%")
                        )
                    ).all()
                )
                while belge_no in kullanilan:
                    kok, sira = belge_no.rsplit("-", 1)
                    belge_no = f"{kok}-{int(sira) + 1:04d}"
            hareket_turu = "TAHSİLAT MAKBUZU" if tur == "TAHSILAT" else "ÖDEME MAKBUZU"
            varsayilan = "Tahsilat makbuzu" if tur == "TAHSILAT" else "Ödeme makbuzu"
            ust_acik = aciklama or varsayilan
            if makbuz_no:
                ust_acik = f"{ust_acik} | Makbuz: {makbuz_no}"

            ilk_hesap = cozulmus[0][1]
            if mevcut is not None:
                makbuz = mevcut
                makbuz.sube_id = sube_id
                makbuz.tarih = tarih
                makbuz.tutar = toplam
                makbuz.finans_hesap_id = ilk_hesap.id
                makbuz.cari_id = cari_id
                makbuz.makbuz_no = makbuz_no
                makbuz.aciklama = aciklama
            else:
                makbuz = KasaMakbuzu(
                    belge_no=belge_no,
                    sube_id=sube_id,
                    tarih=tarih,
                    makbuz_turu=tur,
                    tutar=toplam,
                    finans_hesap_id=ilk_hesap.id,
                    cari_id=cari_id,
                    makbuz_no=makbuz_no,
                    aciklama=aciklama,
                    durum="AÇIK",
                )
                session.add(makbuz)
            session.flush()

            for s, hesap, kod, ek in cozulmus:
                satir_acik = s.get("aciklama") or ust_acik
                if s.get("odeme_sekli"):
                    satir_acik = f"{s['odeme_sekli']} | {satir_acik}"
                satir = KasaMakbuzSatiri(
                    makbuz_id=makbuz.id,
                    sira_no=s["sira_no"],
                    tarih=s["tarih"],
                    odeme_sekli=s["odeme_sekli"],
                    finans_hesap_id=hesap.id,
                    tutar=s["tutar"],
                    aciklama=s.get("aciklama"),
                )
                if kod == "POS":
                    kart, kmh = ek
                    kayit = FinansService._makbuz_pos_yaz(
                        session, s, hesap, kart, kmh, belge_no, cari_id, sube_id, satir_acik
                    )
                    satir.kart_tipi = kayit.kart_tipi
                    satir.taksit_sayisi = kayit.taksit_sayisi
                    satir.pos_valor_id = kayit.id
                elif kod == "KK":
                    odeme = FinansService._makbuz_kk_yaz(
                        session, s, hesap, ek, belge_no, cari_id, sube_id, satir_acik
                    )
                    satir.kredi_karti_id = ek.id
                    satir.taksit_sayisi = odeme.taksit_sayisi
                    satir.kk_odeme_id = odeme.id
                else:
                    session.add(
                        FinansHareketi(
                            hesap_id=hesap.id,
                            sube_id=sube_id,
                            tarih=s["tarih"],
                            hareket_turu=hareket_turu,
                            belge_no=belge_no,
                            tutar=s["tutar"],
                            aciklama=satir_acik,
                        )
                    )
                if tur == "TAHSILAT":
                    FinansService._cari_tahsilat_satiri(
                        session, cari_id, s["tarih"], s["tutar"], belge_no, hesap.hesap_adi, satir_acik,
                        oncelikli=fatura_hedefi, plan=kapatma_plani,
                    )
                else:
                    FinansService._cari_odeme_satiri(
                        session, cari_id, s["tarih"], s["tutar"], belge_no, hesap.hesap_adi, satir_acik,
                        plan=kapatma_plani,
                    )
                session.add(satir)

            if fatura_hedefi is not None:
                if bag is None:
                    bag = SatisFaturaMakbuzBagi(
                        makbuz_id=makbuz.id,
                        fatura_id=fatura_hedefi["fatura"].id,
                        fatura_no=fatura_hedefi["fatura"].fatura_no,
                    )
                    session.add(bag)
                bag.fatura_kapanan = fatura_hedefi["uygulanan"]

            session.flush()
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("kasa_makbuzu_fisi", int(makbuz.id), yeniden=mevcut is not None, session=session)
            return makbuz.id

    # --- Satış faturasına bağlı tahsilat makbuzu ---
    _bag_hazir_motor = None

    @classmethod
    def fatura_makbuz_bag_tablosu_hazirla(cls) -> None:
        """Eski firma veritabanlarında bağ tablosu yoksa ekler (yalnız CREATE TABLE; mevcut veriye dokunmaz)."""
        import database.database as veritabani

        motor = veritabani.engine
        if motor is None or motor is cls._bag_hazir_motor:
            return
        SatisFaturaMakbuzBagi.__table__.create(bind=motor, checkfirst=True)
        cls._bag_hazir_motor = motor

    @staticmethod
    def _bag_tablosu_var(session) -> bool:
        from sqlalchemy import inspect as sa_inspect

        return sa_inspect(session.connection()).has_table(SatisFaturaMakbuzBagi.__tablename__)

    @staticmethod
    def _fatura_bagi(session, makbuz_id) -> SatisFaturaMakbuzBagi | None:
        if not makbuz_id or not FinansService._bag_tablosu_var(session):
            return None
        return session.scalar(
            select(SatisFaturaMakbuzBagi).where(SatisFaturaMakbuzBagi.makbuz_id == int(makbuz_id))
        )

    @staticmethod
    def _fatura_genel_toplami(fatura) -> Decimal:
        """Onayda cari borca yazılan tutarla aynı kaynak (uzlaşma sonrası Net)."""
        from database.satis_faturasi_service import SatisFaturasiService

        return Decimal(str(SatisFaturasiService.net_toplam(fatura)))

    @staticmethod
    def _fatura_cari_hareketi(session, fatura):
        """Faturanın açık borç satırı (Talimat V2: kaydet sonrası da vardır; iptalde yok)."""
        from database.models.cari import SatisHareketi

        if (fatura.durum or "") == "İPTAL":
            return None
        return session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.belge_no == fatura.fatura_no,
                SatisHareketi.cari_id == fatura.cari_id,
            )
        )

    @staticmethod
    def _fatura_acik_tutari(session, fatura) -> tuple[Decimal, object]:
        """(faturanın ödenmemiş kalanı, açık borç satırı). Onaysız faturada kalan = toplam − tahsil edilen."""
        if (fatura.durum or "") == "İPTAL":
            return Decimal("0"), None
        hareket = FinansService._fatura_cari_hareketi(session, fatura)
        if hareket is not None:
            return max(Decimal("0"), Decimal(str(hareket.kalan_acik_tutar or 0))), hareket
        toplam = FinansService._fatura_genel_toplami(fatura)
        return max(Decimal("0"), toplam - Decimal(str(fatura.tahsilat_tutari or 0))), None

    @staticmethod
    def _fatura_odeme_durumu(fatura) -> None:
        """Onaylı satış faturasının evrak durumu AÇIK kalır; ödenme tahsilat_tutari ile izlenir."""
        if not fatura.onaylandi or (fatura.durum or "") == "İPTAL":
            return
        fatura.durum = "AÇIK"

    @staticmethod
    def _faturaya_uygula(fatura, hareket, tutar: Decimal) -> None:
        if hareket is not None:
            hareket.kalan_acik_tutar = Decimal(str(hareket.kalan_acik_tutar or 0)) - tutar
        fatura.tahsilat_tutari = Decimal(str(fatura.tahsilat_tutari or 0)) + tutar
        FinansService._fatura_odeme_durumu(fatura)

    @staticmethod
    def _faturadan_geri_al(session, fatura, tutar: Decimal) -> None:
        hareket = FinansService._fatura_cari_hareketi(session, fatura)
        if hareket is not None:
            kapasite = Decimal(str(hareket.satis_tutari or 0)) - Decimal(str(hareket.kalan_acik_tutar or 0))
            hareket.kalan_acik_tutar = Decimal(str(hareket.kalan_acik_tutar or 0)) + min(
                max(kapasite, Decimal("0")), tutar
            )
        fatura.tahsilat_tutari = max(Decimal("0"), Decimal(str(fatura.tahsilat_tutari or 0)) - tutar)
        FinansService._fatura_odeme_durumu(fatura)

    @staticmethod
    def _makbuz_fatura_hedefi(session, fatura_id, mevcut, cari_id):
        """Bağlı fatura hedefi (öncelikli uygulama bütçesi) ve varsa mevcut bağ kaydı."""
        from database.models.satis_faturasi import SatisFaturasi

        bag = FinansService._fatura_bagi(session, mevcut.id) if mevcut is not None else None
        if bag is not None and fatura_id and int(fatura_id) != int(bag.fatura_id):
            raise ValueError("Makbuzun bağlı olduğu fatura değiştirilemez.")
        hedef_id = int(bag.fatura_id) if bag is not None else (int(fatura_id) if fatura_id else None)
        if hedef_id is None:
            return None, None
        fatura = session.get(SatisFaturasi, hedef_id)
        if fatura is None or getattr(fatura, "is_deleted", False):
            raise ValueError("Bağlı satış faturası bulunamadı.")
        if int(fatura.cari_id) != int(cari_id):
            raise ValueError(
                f"Makbuz {fatura.fatura_no} numaralı faturaya bağlı; cari hesap faturanın müşterisi olmalıdır."
            )
        if bag is None and (fatura.durum or "") == "İPTAL":
            raise ValueError("İptal edilmiş faturaya tahsilat makbuzu bağlanamaz.")
        butce, hareket = FinansService._fatura_acik_tutari(session, fatura)
        return {"fatura": fatura, "hareket": hareket, "butce": butce, "uygulanan": Decimal("0")}, bag

    @staticmethod
    def _fatura_bagli_cari_geri_al(session, makbuz, bag) -> None:
        """Bağlı makbuzun cari etkisi: faturaya uygulanan kısım faturaya, kalanı LIFO ile geri açılır."""
        from database.cari_service import CariService
        from database.models.cari import CariIslem
        from database.models.satis_faturasi import SatisFaturasi

        from database.acik_kalem_service import AcikKalemService

        islemler = list(session.scalars(select(CariIslem).where(CariIslem.belge_no == makbuz.belge_no)).all())
        toplam = sum(
            (Decimal(str(i.alacak or 0)) + Decimal(str(i.borc or 0)) for i in islemler), Decimal("0")
        )
        fatura_payi = min(Decimal(str(bag.fatura_kapanan or 0)), toplam)
        if AcikKalemService.belge_kayitli_mi(session, makbuz.cari_id, makbuz.belge_no):
            # Kayıtlı tahsisler + kendi avansı geri alınır; kalan fark faturaya eski yolla yazılmış paydır.
            kayitli = AcikKalemService.belge_geri_al(
                session, makbuz.cari_id, makbuz.belge_no, neden=f"Makbuz geri alındı {makbuz.belge_no}"
            )
            eski = min(max(toplam - kayitli, Decimal("0")), fatura_payi)
            if eski > 0:
                fatura = session.get(SatisFaturasi, int(bag.fatura_id))
                if fatura is not None:
                    FinansService._faturadan_geri_al(session, fatura, eski)
        else:
            if fatura_payi > 0:
                fatura = session.get(SatisFaturasi, int(bag.fatura_id))
                if fatura is not None:
                    FinansService._faturadan_geri_al(session, fatura, fatura_payi)
            if toplam - fatura_payi > 0:
                CariService._aciklara_geri_al(
                    session, makbuz.cari_id, toplam - fatura_payi, makbuz.belge_no
                )
        for islem in islemler:
            session.delete(islem)
        bag.fatura_kapanan = Decimal("0")

    @staticmethod
    def bagli_makbuz_paylarini_faturada_tut(session, fatura, *, neden: str) -> Decimal:
        """Onay kaldırmadan önce: bağlı makbuzların bu faturaya kayıtlı tahsislerini iptal eder.

        Pay faturanın tahsil edilen tutarında kalır (taslakta da makbuza bağlı kalır); avansa
        dönüp başka faturalara dağılmaz. Yeniden onayda açık tutar toplam − tahsil edilen olur.
        """
        from database.acik_kalem_service import AcikKalemService, _kurus
        from database.models.cari import CariKapatma

        hareket = FinansService._fatura_cari_hareketi(session, fatura)
        if (
            hareket is None
            or not AcikKalemService._tablo_var(session)
            or not FinansService._bag_tablosu_var(session)
        ):
            return Decimal("0")
        makbuz_idleri = [
            b.makbuz_id
            for b in session.scalars(
                select(SatisFaturaMakbuzBagi).where(SatisFaturaMakbuzBagi.fatura_id == fatura.id)
            ).all()
        ]
        if not makbuz_idleri:
            return Decimal("0")
        belgeler = [
            m.belge_no
            for m in session.scalars(
                select(KasaMakbuzu).where(KasaMakbuzu.id.in_(makbuz_idleri))
            ).all()
            if m.belge_no
        ]
        if not belgeler:
            return Decimal("0")
        import uuid

        kimlik = str(uuid.uuid4())
        toplam = Decimal("0")
        for kayit in session.scalars(
            select(CariKapatma).where(
                CariKapatma.hedef_hareket_id == int(hareket.id),
                CariKapatma.kaynak_belge_no.in_(belgeler),
                CariKapatma.iptal.is_(False),
            )
        ).all():
            AcikKalemService._kaydi_iptal_et(kayit, neden, kimlik)
            toplam += Decimal(str(kayit.tutar or 0))
        if toplam > 0:
            AcikKalemService._ekle(session, hareket, toplam)
        session.flush()
        return _kurus(toplam)

    @staticmethod
    def makbuz_fatura_bagi(makbuz_id) -> dict | None:
        """Makbuzun bağlı olduğu satış faturası (yoksa None)."""
        FinansService.fatura_makbuz_bag_tablosu_hazirla()
        with get_session() as session:
            bag = FinansService._fatura_bagi(session, makbuz_id)
            if bag is None:
                return None
            return {
                "fatura_id": int(bag.fatura_id),
                "fatura_no": bag.fatura_no,
                "fatura_kapanan": Decimal(str(bag.fatura_kapanan or 0)),
            }

    @staticmethod
    def fatura_tahsilat_ozeti(fatura_id) -> dict:
        """Satış faturası tahsilat özeti: toplam, tahsil edilen, kalan ve bağlı tahsilat makbuzları."""
        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService

        FinansService.fatura_makbuz_bag_tablosu_hazirla()
        with get_session() as session:
            fatura = session.scalar(
                select(SatisFaturasi)
                .options(selectinload(SatisFaturasi.satirlar))
                .where(SatisFaturasi.id == int(fatura_id))
            )
            if fatura is None or getattr(fatura, "is_deleted", False):
                raise ValueError("Satış faturası bulunamadı.")
            hareket = FinansService._fatura_cari_hareketi(session, fatura)
            genel = (
                Decimal(str(hareket.satis_tutari or 0))
                if hareket is not None
                else FinansService._fatura_genel_toplami(fatura)
            )
            kalan, _ = FinansService._fatura_acik_tutari(session, fatura)
            makbuzlar = []
            baglar = list(
                session.scalars(
                    select(SatisFaturaMakbuzBagi)
                    .where(SatisFaturaMakbuzBagi.fatura_id == fatura.id)
                    .order_by(SatisFaturaMakbuzBagi.id)
                ).all()
            )
            if baglar:
                kayitlar = {
                    m.id: m
                    for m in session.scalars(
                        select(KasaMakbuzu).where(KasaMakbuzu.id.in_([b.makbuz_id for b in baglar]))
                    ).all()
                }
                for b in baglar:
                    m = kayitlar.get(b.makbuz_id)
                    if m is None:
                        continue
                    makbuzlar.append(
                        {
                            "makbuz_id": int(m.id),
                            "makbuz_no": (m.makbuz_no or "").strip(),
                            "belge_no": m.belge_no,
                            "tarih": m.tarih,
                            "tutar": Decimal(str(m.tutar or 0)),
                            "fatura_kapanan": Decimal(str(b.fatura_kapanan or 0)),
                            "durum": m.durum or "AÇIK",
                        }
                    )
            acik = [m for m in makbuzlar if m["durum"] != "IPTAL"]
            cari = session.get(Cari, int(fatura.cari_id))
            return {
                "fatura_id": int(fatura.id),
                "fatura_no": fatura.fatura_no,
                "cari_id": int(fatura.cari_id),
                "cari_kodu": getattr(cari, "cari_kodu", "") or "",
                "cari_unvan": getattr(cari, "unvan", "") or "",
                "sube_id": fatura.sube_id,
                "onayli": bool(fatura.onaylandi),
                "iptal": (fatura.durum or "") == "İPTAL",
                "durum": fatura.durum or "",
                "genel_toplam": genel,
                "brut_toplam": Decimal(
                    str(SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"])
                ),
                "tahsil_edilen": max(Decimal("0"), genel - kalan),
                "kalan": kalan,
                "makbuzlar": makbuzlar,
                "makbuz_tahsilati": sum((m["fatura_kapanan"] for m in acik), Decimal("0")),
            }

    @staticmethod
    def fatura_bagli_makbuz_toplami(session, fatura_id) -> Decimal:
        """Açık bağlı makbuzların bu faturaya uyguladığı toplam (iptal edilmişlerde 0)."""
        if not fatura_id or not FinansService._bag_tablosu_var(session):
            return Decimal("0")
        toplam = session.scalar(
            select(func.coalesce(func.sum(SatisFaturaMakbuzBagi.fatura_kapanan), 0)).where(
                SatisFaturaMakbuzBagi.fatura_id == int(fatura_id)
            )
        )
        return Decimal(str(toplam or 0))

    @staticmethod
    def _makbuz_hesap_uyumu(s: dict, hesap: FinansHesabi, tur: str) -> None:
        """Ödeme şekli ile hesap türü eşleşmeli (kart tahsilatı kasaya/bankaya yazılmaz)."""
        sekil_turu = s.get("sekil_turu")
        alt = (hesap.alt_hesap_turu or "").upper()
        hesap_turu = (hesap.hesap_turu or "").upper()
        no = s["sira_no"]
        if sekil_turu == "KASA" and hesap_turu != "KASA":
            raise ValueError(f"Satır {no}: nakit satırı için kasa hesabı seçin.")
        if sekil_turu == "HAVALE" and alt not in ("MEVDUAT", "KMH"):
            raise ValueError(f"Satır {no}: havale satırı için mevduat veya KMH hesabı seçin.")
        if sekil_turu == "KART" and tur == "TAHSILAT":
            if alt != "POS" or not hesap.banka_karti_id:
                raise ValueError(
                    f"Satır {no}: kredi kartı tahsilatı yalnızca POS hesabına işlenebilir."
                )

    @staticmethod
    def _makbuz_pos_yaz(session, s, pos, kart, kmh, belge_no, cari_id, sube_id, aciklama) -> PosValorKaydi:
        """Makbuzdaki kart tahsilatı: POS brüt girişi, taksit komisyonu ve valör → KMH kaydı."""
        brut = s["tutar"]
        tip = (s.get("kart_tipi") or "KREDI_KARTI").upper()
        if tip not in {k for k, _ in POS_KART_TIPLERI}:
            raise ValueError(f"Satır {s['sira_no']}: kart tipi kredi kartı veya banka kartı olmalıdır.")
        n = 1 if tip == "BANKA_KARTI" else int(s.get("taksit_sayisi") or 1)
        if n < 1 or n > POS_MAX_TAKSIT:
            raise ValueError(f"Satır {s['sira_no']}: POS taksit sayısı 1-{POS_MAX_TAKSIT} arasında olmalıdır.")
        oran = FinansService._pos_komisyon_orani(kart, tip, n)
        if oran < 0 or oran > 100:
            raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
        komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net = brut - komisyon
        tarih = s["tarih"]
        taksit_metin = "Tek çekim" if n == 1 else f"{n} taksit"
        session.add(
            FinansHareketi(
                hesap_id=pos.id,
                sube_id=sube_id,
                tarih=tarih,
                hareket_turu="POS TAHSİLAT",
                belge_no=belge_no,
                tutar=brut,
                aciklama=aciklama,
            )
        )
        if komisyon > 0:
            session.add(
                FinansHareketi(
                    hesap_id=pos.id,
                    sube_id=sube_id,
                    tarih=tarih,
                    hareket_turu="POS KOMİSYON",
                    belge_no=belge_no,
                    tutar=komisyon,
                    aciklama=f"Komisyon %{oran:g} ({taksit_metin})",
                )
            )
        hedef = FinansService._pos_hedef_hesap(kart) or kmh
        if not hedef:
            raise ValueError("POS hedef hesabı (mevduat/KMH) bulunamadı.")
        is_gunu = bool(
            getattr(kart, "pos_valor_is_gunu", True)
            if getattr(kart, "pos_valor_is_gunu", None) is not None
            else True
        )
        valor_tarihi = valor_tarihi_hesapla(
            tarih, int(kart.pos_valor_gun or 1), is_gunu=is_gunu
        )
        kayit = PosValorKaydi(
            banka_karti_id=kart.id,
            pos_hesap_id=pos.id,
            kmh_hesap_id=hedef.id,
            hedef_hesap_id=hedef.id,
            belge_no=belge_no,
            tahsilat_tarihi=tarih,
            valor_tarihi=valor_tarihi,
            valor_saati=POS_VALOR_SAATI,
            kart_tipi=tip,
            taksit_sayisi=n,
            brut_tutar=brut,
            komisyon_orani=oran,
            komisyon_tutari=komisyon,
            net_tutar=net,
            cari_id=int(cari_id),
            durum="BEKLIYOR",
            aciklama=aciklama,
        )
        session.add(kayit)
        session.flush()
        return kayit

    @staticmethod
    def _makbuz_kk_yaz(session, s, kk_hesap, kk, belge_no, cari_id, sube_id, aciklama) -> KrediKartiOdeme:
        """Makbuzdaki şirket kartıyla ödeme: kart borcu (KK ÖDEME) + taksit planı; limit kontrolü."""
        brut = s["tutar"]
        n = int(s.get("taksit_sayisi") or 1)
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Satır {s['sira_no']}: taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            KrediKartiEkstreService.limit_kontrol(session, kk, brut)
        except ValueError as hata:
            raise ValueError(f"{kk.kart_adi}: {hata}") from hata
        tarih = s["tarih"]
        plan = FinansService.kk_taksit_plani(tarih, n, brut, kart=kk)
        session.add(
            FinansHareketi(
                hesap_id=kk_hesap.id,
                sube_id=sube_id,
                tarih=tarih,
                hareket_turu="KK ÖDEME",
                belge_no=belge_no,
                tutar=brut,
                aciklama=aciklama,
            )
        )
        odeme = KrediKartiOdeme(
            belge_no=f"{belge_no}-K{s['sira_no']}",
            tarih=tarih,
            vade_tarihi=plan[0]["vade_tarihi"],
            banka_karti_id=kk.banka_karti_id,
            kredi_karti_id=kk.id,
            cari_id=int(cari_id),
            cekim_turu="TEK_CEKIM" if n == 1 else "TAKSITLI",
            taksit_sayisi=n,
            tutar=brut,
            aciklama=aciklama[:500] if aciklama else None,
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
                    ekstre_kesim_tarihi=satir.get("ekstre_kesim_tarihi"),
                )
            )
        return odeme

    @staticmethod
    def _makbuz_bagli_kayitlar(session, makbuz) -> tuple[list[PosValorKaydi], list[KrediKartiOdeme]]:
        satirlar = list(makbuz.satirlar or [])
        pv_ids = [s.pos_valor_id for s in satirlar if s.pos_valor_id]
        ko_ids = [s.kk_odeme_id for s in satirlar if s.kk_odeme_id]
        pos_kayitlari = (
            list(session.scalars(select(PosValorKaydi).where(PosValorKaydi.id.in_(pv_ids))).all())
            if pv_ids
            else []
        )
        kk_odemeleri = (
            list(
                session.scalars(
                    select(KrediKartiOdeme)
                    .where(KrediKartiOdeme.id.in_(ko_ids))
                    .options(selectinload(KrediKartiOdeme.taksitler))
                ).all()
            )
            if ko_ids
            else []
        )
        return pos_kayitlari, kk_odemeleri

    @staticmethod
    def makbuz_kilit_nedeni(makbuz_id) -> str | None:
        """Makbuz düzenlenemez/iptal edilemezse nedeni (valörü aktarılmış POS, ödenmiş kart taksiti)."""
        with get_session() as session:
            makbuz = session.get(KasaMakbuzu, int(makbuz_id))
            if not makbuz:
                return "Makbuz bulunamadı."
            if makbuz.durum == "IPTAL":
                return "Makbuz iptal edilmiş."
            pos_kayitlari, kk_odemeleri = FinansService._makbuz_bagli_kayitlar(session, makbuz)
            return FinansService._makbuz_kilit_metni(pos_kayitlari, kk_odemeleri)

    @staticmethod
    def _makbuz_kilit_metni(pos_kayitlari, kk_odemeleri) -> str | None:
        for pv in pos_kayitlari:
            if (pv.durum or "") == "AKTARILDI":
                return (
                    "Makbuzdaki kart tahsilatının net tutarı valörde KMH hesabına aktarıldı; "
                    "makbuz artık değiştirilemez veya iptal edilemez."
                )
        for ko in kk_odemeleri:
            if any((t.durum or "") == "ODENDI" for t in (ko.taksitler or [])):
                return (
                    "Makbuzdaki şirket kartı ödemesinin taksiti ekstrede ödendi; "
                    "makbuz artık değiştirilemez veya iptal edilemez."
                )
        return None

    @staticmethod
    def _makbuz_etkilerini_geri_al(session, makbuz, *, iptal: bool) -> None:
        pos_kayitlari, kk_odemeleri = FinansService._makbuz_bagli_kayitlar(session, makbuz)
        kilit = FinansService._makbuz_kilit_metni(pos_kayitlari, kk_odemeleri)
        if kilit:
            raise ValueError(kilit)
        bag = FinansService._fatura_bagi(session, makbuz.id) if makbuz.makbuz_turu == "TAHSILAT" else None
        if bag is not None:
            FinansService._fatura_bagli_cari_geri_al(session, makbuz, bag)
        else:
            FinansService._havale_cari_geri_al(session, makbuz.belge_no)
        FinansService._finans_hareketlerini_sil(session, makbuz.belge_no)
        for pv in pos_kayitlari:
            if iptal:
                pv.durum = "IPTAL"
            else:
                session.delete(pv)
        for ko in kk_odemeleri:
            if iptal:
                ko.durum = "İPTAL"
            else:
                session.delete(ko)
        session.flush()

    @staticmethod
    def kasa_makbuz_iptal(makbuz_id):
        yazma_zorunlu("finans_duzenleme", "iptal")
        FinansService.fatura_makbuz_bag_tablosu_hazirla()
        with get_session() as session:
            makbuz = session.get(KasaMakbuzu, int(makbuz_id))
            if not makbuz:
                raise ValueError("Makbuz bulunamadı.")
            if makbuz.durum == "IPTAL":
                raise ValueError("Makbuz zaten iptal.")
            # Eş zamanlı ikinci iptal: durum koşullu güncellenir, yalnız biri etki üretir
            if not session.execute(
                update(KasaMakbuzu).where(KasaMakbuzu.id == makbuz.id, KasaMakbuzu.durum != "IPTAL")
                .values(durum="IPTAL").execution_options(synchronize_session=False)
            ).rowcount:
                raise ValueError("Makbuz zaten iptal.")
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("kasa_makbuzu_iptal", int(makbuz.id), f"Makbuz iptal {makbuz.belge_no}", session=session)
            FinansService._makbuz_etkilerini_geri_al(session, makbuz, iptal=True)
            makbuz.durum = "IPTAL"
            from database.odeme_sozu_service import OdemeSozuService

            OdemeSozuService.evrak_baglantilarini_iptal(
                session, makbuz.belge_no, neden=f"Makbuz iptal edildi {makbuz.belge_no}"
            )
            session.flush()


def _fmt(tutar) -> str:
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@event.listens_for(FinansHareketi, "before_insert", propagate=True)
def _finans_hareketi_kur_doldur(mapper, connection, target):
    """Doğrudan FinansHareketi ekleyen yollarda PB/kur/TL boş kalmasın (TRY=1)."""
    if target.hesap_id is None or target.tutar is None:
        return
    pb = (target.para_birimi or "").strip().upper()
    ihtiyac = (not pb) or target.kur is None or target.tl_karsiligi is None
    if not ihtiyac:
        return
    row = connection.execute(
        text('SELECT "para_birimi" FROM "finans_hesaplari" WHERE "id" = :id'),
        {"id": int(target.hesap_id)},
    ).first()
    hesap_pb = ((row[0] if row else None) or "TRY").strip().upper() or "TRY"
    if hesap_pb not in ("TRY", "USD", "EUR"):
        hesap_pb = "TRY"
    if not pb:
        target.para_birimi = hesap_pb
        pb = hesap_pb
    if target.kur is not None and target.tl_karsiligi is not None:
        return
    tarih = target.tarih or date.today()
    if pb == "TRY":
        if target.kur is None:
            target.kur = Decimal("1")
        if target.kur_tarihi is None:
            target.kur_tarihi = tarih
        if target.tl_karsiligi is None:
            target.tl_karsiligi = Decimal(str(target.tutar)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return
    # Döviz: kayıt kuru zorunlu — sessizce 1 yazma
    if target.kur is None:
        k, kt = FinansService._kayit_kuru_coz(pb, tarih)
        target.kur = k
        if target.kur_tarihi is None:
            target.kur_tarihi = kt
    elif target.kur_tarihi is None:
        target.kur_tarihi = tarih
    if target.tl_karsiligi is None:
        target.tl_karsiligi = (
            Decimal(str(target.tutar)) * Decimal(str(target.kur))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

