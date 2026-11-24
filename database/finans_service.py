from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import calendar
import re
import time

from sqlalchemy import delete, event, func, or_, select, text, update
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
    PosValorDegisiklik,
    PosValorKaydi,
    SatisFaturaMakbuzBagi,
)

HESAP_TURLERI = ("KASA", "BANKA", "KREDİ KARTI")

# Rapor / UI: borç (yükümlülük) hesapları — işletme görünümünde eksi (−) ve kırmızı
BORC_ALT_HESAP_TURLERI = frozenset({"KREDI_KARTI", "KREDILER"})
BAKIYE_RENK_POZITIF = "#15803D"
BAKIYE_RENK_NEGATIF = "#B91C1C"
BAKIYE_RENK_SIFIR = "#475569"

# Native Cin hareketleri: borç büyüklüğü ledger'da pozitif artar
_NATIVE_BORC_HAREKET_KOK = (
    "KK ÖDEME",
    "KK GİDER",
    "KK İADE",
    "KK EKSTRE",
    "KK NAKİT AVANS",
    "KREDİ KULLANDIRIM",
    "KREDİ ANAPARA",
    "KREDİ FAİZ",
    "KREDİ MASRAF",
)

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
    "KK NAKİT AVANS",  # nakit avans taksitinin karta yansıması (anapara+faiz+masraf toplamı)
    "KK EKSTRE ÖDEME İPTAL",  # iptal edilen ekstre ödemesi: ödeme hesabına iade, kart borcu geri gelir
    "KK ÖDEME DÜZELTME EK",  # kayıt düzeltmesi: açık dönem artışı / eksi düzeltmenin tersi → kart borcu artar
    "KK GİDER",  # eski sürümde kart hesabına yazılmış gider fişi (onarımla) → KK borcu artar
    "KREDİ KULLANDIRIM",  # ana para → krediler borcu artar
    "KREDİ KULLANDIRIM (MEVDUAT)",  # ana para mevduat/KMH'ye giriş
    "NAKİT AVANS GİRİŞ",  # nakit avans net tutarın kasa/mevduata girişi
    "TAHSİLAT MAKBUZU",
    "ÇEK/SENET TAHSİLAT",
    "ÇEK/SENET ÖDEME İPTAL",  # iptal edilen çek/senet ödemesinin ters hareketi
    "KASA VİRMAN GİRİŞ",
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
    "KK NAKİT AVANS İPTAL",  # nakit avans taksit iptal/düzeltme tersi → KK borcu azalır
    "KASA VİRMAN ÇIKIŞ",
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
# Kredi kartı tek çekimde sözleşmede özel oran yoksa kullanılan yedek
POS_KK_TEK_CEKIM_YEDEK_ORAN = Decimal("1.99")
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
    if "HAVALE" in s or "EFT" in s or "FAST" in s:
        return "HAVALE"
    if "KART" in s or "POS" in s:
        return "KART"
    if "KASA" in s or "NAKIT" in s:
        return "KASA"
    return None


def _makbuz_odeme_mi(sekil: str | None) -> bool:
    """Şekil adı ödeme (gönderilen/firma kartı) yönünde mi? Tahsilat şekilleri False."""
    s = (sekil or "").replace("İ", "I").replace("ı", "i").upper()
    if "TAHSILAT" in s or "GELEN" in s or "ALINAN" in s:
        return False
    if "GONDERILEN" in s or "GIDEN" in s or "ODEME" in s:
        return True
    if ("FIRMA" in s or "SIRKET" in s) and "KART" in s:
        return True
    return False


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
        """Boş (yerel test) kurulum için iskelet hesaplar.

        AG/PostgreSQL canlı firmada zaten hesap varsa örnek «BANKA HESABI» vb. eklenmez.
        Ödeme/tahsilat/kredi örneği yazılmaz.
        """
        varsayilanlar = (
            ("ANA KASA", "KASA"),
            ("BANKA HESABI", "BANKA"),
            ("KREDİ KARTI POS", "KREDİ KARTI"),
        )
        with get_session() as session:
            mevcut_ad = set(session.scalars(select(FinansHesabi.hesap_adi)).all())
            try:
                from database.baglanti_modu import ayari_yukle

                ag_mi = bool(ayari_yukle().ag_mi)
            except Exception:
                ag_mi = False
            if ag_mi and mevcut_ad:
                # Canlı firma: mevcut hesapları koru, iskelet ekleme
                return
            for ad, tur in varsayilanlar:
                if ad not in mevcut_ad:
                    session.add(FinansHesabi(hesap_adi=ad, hesap_turu=tur))

    @staticmethod
    def hesaplar(hesap_turu=None, aktif_only=True, *, hareketler: bool = True):
        from database.hesap_siralama import hesaplari_sirala

        with get_session() as session:
            q = select(FinansHesabi)
            if hareketler:
                q = q.options(selectinload(FinansHesabi.hareketler))
            if aktif_only:
                q = q.where(FinansHesabi.aktif.is_(True))
            if hesap_turu:
                q = q.where(FinansHesabi.hesap_turu == hesap_turu)
            # SQL sırası geçici; nihai sıra sınıf + ad (Türkçe/doğal)
            q = q.order_by(FinansHesabi.id)
            return hesaplari_sirala(session.scalars(q).all())

    @staticmethod
    def odeme_sekil_ascii(odeme_sekli: str | None) -> str:
        """Ödeme/tahsilat şekli karşılaştırması için Türkçe → ASCII (Ö→O, İ→I, …)."""
        t = (odeme_sekli or "").replace("İ", "I").replace("ı", "i").upper()
        for a, b in (("Ö", "O"), ("Ü", "U"), ("Ş", "S"), ("Ğ", "G"), ("Ç", "C")):
            t = t.replace(a, b)
        return t

    @staticmethod
    def odeme_sekil_turu(odeme_sekli: str | None, *, gelir_mi: bool = False) -> str | None:
        """Şekil sınıfı: ``KASA`` | ``HAVALE`` | ``KART`` | None (görünen addan değil, koddan)."""
        s = FinansService.odeme_sekil_ascii(odeme_sekli)
        if not s:
            return None
        if "HAVALE" in s or "EFT" in s or "FAST" in s:
            return "HAVALE"
        if gelir_mi:
            if "KART" in s or "POS" in s:
                return "KART"
        else:
            # Ödeme: kredi kartı hesabı; POS tahsilat hesapları dahil edilmez
            if "KART" in s and "TAHSILAT" not in s:
                return "KART"
            if ("FIRMA" in s or "SIRKET" in s) and "KART" in s:
                return "KART"
        if "KASA" in s or "NAKIT" in s:
            return "KASA"
        return None

    @staticmethod
    def tahsilat_hesaplari(odeme_sekli: str | None = None):
        """Tahsilat şekline göre hesap listesi.
        - Nakit/Kasa → yalnızca KASA
        - Gelen/Alınan Havale → MEVDUAT + KMH
        - Kredi kartı tahsilat → yalnızca POS (firma KK hesapları tahsilatta yok)

        Yalnız hesap kimliği/adı/türü döner; hareketler yüklenmez.
        Bilinmeyen şekilde tüm hesapları döndürmez.
        """
        from database.hesap_siralama import hesaplari_sirala

        tum = FinansService.hesaplar(hareketler=False)
        tur = FinansService.odeme_sekil_turu(odeme_sekli, gelir_mi=True)
        if tur == "HAVALE":
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True)
                and (getattr(h, "alt_hesap_turu", None) or "").upper() in ("MEVDUAT", "KMH")
            )
        if tur == "KART":
            # Firma kredi kartları (ödeme) hariç; sadece POS tahsilat hesapları
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True)
                and (getattr(h, "alt_hesap_turu", None) or "").upper() == "POS"
            )
        if tur == "KASA":
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True) and (h.hesap_turu or "").upper() == "KASA"
            )
        return []

    @staticmethod
    def odeme_hesaplari(odeme_sekli: str | None = None):
        """Ödeme (çıkış) şekline göre hesap listesi — tahsilat POS karışmaz.
        - Nakit ödeme → KASA
        - Gönderilen havale/EFT/FAST → MEVDUAT + KMH
        - Kredi kartıyla ödeme → yalnız ``alt_hesap_turu=KREDI_KARTI`` (POS yok)

        Sıra: sınıf adı A–Z, hesap adı A–Z. Bilinmeyen şekilde tüm hesapları döndürmez.
        Bakiye/limit burada süzülmez.
        """
        from database.hesap_siralama import hesaplari_sirala

        tum = FinansService.hesaplar(hareketler=False)
        tur = FinansService.odeme_sekil_turu(odeme_sekli, gelir_mi=False)
        if tur == "KART":
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True)
                and (getattr(h, "alt_hesap_turu", None) or "").upper() == "KREDI_KARTI"
            )
        if tur == "HAVALE":
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True)
                and (getattr(h, "alt_hesap_turu", None) or "").upper() in ("MEVDUAT", "KMH")
            )
        if tur == "KASA":
            return hesaplari_sirala(
                h
                for h in tum
                if getattr(h, "aktif", True) and (h.hesap_turu or "").upper() == "KASA"
            )
        return []

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
        # Yönsüz "KASA VİRMAN" varsayılan +1 ile bakiyeyi bozuyordu (D2 08.11);
        # yön bilinmiyorsa 0 (nötr) — GİRİŞ/ÇIKIŞ etiketleri kullanılmalı.
        if tur == "KASA VİRMAN":
            return 0
        # EVO/devir/gider ayrıntısı: kart hareketlerinde görünür, bakiyeyi artırmaz
        if tur in ("KK TAKSİT", "KK TAKSİT DETAY"):
            return 0
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
        """Fatura tahsilat finansını geri alır (eski FATURA TAHSİLATI + POS valör yolu)."""
        no = (belge_no or "").strip()
        if not no:
            return
        pos_kayitlari = list(
            session.scalars(select(PosValorKaydi).where(PosValorKaydi.belge_no == no)).all()
        )
        for pv in pos_kayitlari:
            durum = (pv.durum or "").strip().upper()
            if durum == "AKTARILDI" and getattr(pv, "gercek_yatis_tarihi", None):
                raise ValueError(
                    f"{no}: POS tahsilatı bankaya aktarılmış; fatura tahsilatı geri alınamaz. "
                    "Önce POS aktarımını geri alın."
                )
            if durum in ("KISMEN",) or (
                durum == "AKTARILDI" and getattr(pv, "eslesen_banka_hareket_idler", None)
            ):
                raise ValueError(
                    f"{no}: POS tahsilatı kısmen/eşleşmeli aktarılmış; fatura tahsilatı geri alınamaz."
                )
        session.execute(
            delete(FinansHareketi).where(
                FinansHareketi.belge_no == no,
                FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
            )
        )
        if pos_kayitlari:
            session.execute(
                delete(FinansHareketi).where(
                    FinansHareketi.belge_no == no,
                    FinansHareketi.hareket_turu.in_(("POS TAHSİLAT", "POS KOMİSYON")),
                )
            )
            for pv in pos_kayitlari:
                session.delete(pv)
            session.flush()

    @staticmethod
    def siparis_avansini_geri_al(session, belge_no):
        """Sipariş avansı kasa hareketlerini siler (yeniden yazım öncesi)."""
        session.execute(
            delete(FinansHareketi).where(
                FinansHareketi.belge_no == belge_no,
                FinansHareketi.hareket_turu == "SİPARİŞ AVANSI",
            )
        )

    @staticmethod
    def fatura_tahsilati(
        session,
        belge_no,
        tarih,
        tutar,
        odeme_sekli,
        hesap_adi,
        *,
        cari_id=None,
        sube_id=None,
        taksit_sayisi=1,
        kart_tipi="KREDI_KARTI",
    ):
        """Fatura tahsilatını finansa yazar.

        POS hesabına kredi kartı tahsilatı: makbuz ile aynı PosValor yolunu kullanır
        (POS İŞLEMLERİ / bekleyen raporlar). Diğer hesaplarda klasik FATURA TAHSİLATI.
        """
        tutar = Decimal(str(tutar or 0))
        if tutar <= 0:
            return
        if not hesap_adi:
            raise ValueError("Kasa/banka hesabı seçin.")
        from database.banka_pos_birlestir import pos_hesap_adi_coz

        hesap_adi = pos_hesap_adi_coz(hesap_adi)
        hesap = session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == hesap_adi))
        if not hesap:
            raise ValueError("Geçerli bir kasa/banka hesabı seçin.")
        alt = (hesap.alt_hesap_turu or "").upper()
        sekil_kart = _makbuz_sekil_turu(odeme_sekli) == "KART"
        if alt == "POS" or sekil_kart:
            if alt != "POS" or not hesap.banka_karti_id:
                raise ValueError(
                    "Kredi kartı tahsilatı yalnızca POS hesabına işlenebilir."
                )
            if cari_id is None:
                raise ValueError("POS fatura tahsilatı için cari zorunludur.")
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(hesap.banka_karti_id))
                .options(
                    selectinload(BankaKarti.alt_hesaplar),
                    selectinload(BankaKarti.pos_taksit_komisyonlari),
                )
            )
            if not kart:
                raise ValueError("POS banka kartı bulunamadı.")
            kmh = FinansService._pos_hedef_hesap(kart)
            aciklama = (odeme_sekli or "KREDİ KARTIYLA TAHSİLAT").strip() or "KREDİ KARTIYLA TAHSİLAT"
            s = {
                "sira_no": 1,
                "tutar": tutar,
                "tarih": tarih.date() if isinstance(tarih, datetime) else tarih,
                "kart_tipi": (kart_tipi or "KREDI_KARTI").upper(),
                "taksit_sayisi": int(taksit_sayisi or 1),
            }
            FinansService._makbuz_pos_yaz(
                session,
                s,
                hesap,
                kart,
                kmh,
                belge_no,
                int(cari_id),
                sube_id,
                aciklama,
            )
            return
        FinansService.hareket_ekle(
            session, belge_no, tarih, tutar, "FATURA TAHSİLATI", hesap_adi, odeme_sekli
        )

    @staticmethod
    def fatura_pos_tahsilat_eksik_valor_onar(*, dry_run: bool = True, belge_no: str | None = None) -> dict:
        """POS hesabındaki eski FATURA TAHSİLATI satırlarına eksik PosValorKaydi ekler.

        Çift kayıt üretmez: belge için PosValor varsa atlar. Mevcut tutarı brüt kabul eder;
        komisyon kart oranından yazılır (POS bakiyesi komisyon kadar azalabilir — doğru muhasebe).
        """
        yazma_zorunlu("finans_duzenleme")
        from database.models.satis_faturasi import SatisFaturasi

        ozet = {"dry_run": dry_run, "aday": [], "onarilan": [], "atlanan": [], "hata": []}
        with get_session() as session:
            q = (
                select(FinansHareketi)
                .join(FinansHesabi, FinansHareketi.hesap_id == FinansHesabi.id)
                .where(
                    FinansHareketi.hareket_turu == "FATURA TAHSİLATI",
                    FinansHesabi.alt_hesap_turu == "POS",
                )
                .order_by(FinansHareketi.tarih, FinansHareketi.id)
            )
            if belge_no:
                q = q.where(FinansHareketi.belge_no == str(belge_no).strip())
            aday_idler = [int(h.id) for h in session.scalars(q).all()]

        for hid in aday_idler:
            with get_session() as session:
                h = session.get(FinansHareketi, hid)
                if h is None:
                    continue
                no = (h.belge_no or "").strip()
                kayit = {
                    "belge_no": no,
                    "hareket_id": hid,
                    "tutar": str(h.tutar),
                    "tarih": h.tarih.isoformat() if h.tarih else None,
                    "hesap_id": int(h.hesap_id),
                }
                mevcut = session.scalar(select(PosValorKaydi).where(PosValorKaydi.belge_no == no))
                if mevcut is not None:
                    kayit["neden"] = f"PosValor zaten var id={mevcut.id}"
                    ozet["atlanan"].append(kayit)
                    continue
                hesap = session.get(FinansHesabi, int(h.hesap_id))
                if not hesap or not hesap.banka_karti_id:
                    kayit["neden"] = "POS banka kartı yok"
                    ozet["hata"].append(kayit)
                    continue
                fatura = session.scalar(
                    select(SatisFaturasi).where(SatisFaturasi.fatura_no == no)
                )
                cari_id = int(fatura.cari_id) if fatura is not None else None
                sube_id = getattr(fatura, "sube_id", None) if fatura is not None else None
                if cari_id is None:
                    kayit["neden"] = "cari bulunamadı"
                    ozet["hata"].append(kayit)
                    continue
                ozet["aday"].append(dict(kayit))
                if dry_run:
                    continue
                try:
                    tutar = Decimal(str(h.tutar or 0))
                    tarih = h.tarih
                    aciklama = (h.aciklama or "KREDİ KARTIYLA TAHSİLAT").strip()
                    hesap_adi = hesap.hesap_adi
                    session.delete(h)
                    session.flush()
                    FinansService.fatura_tahsilati(
                        session,
                        no,
                        tarih,
                        tutar,
                        aciklama,
                        hesap_adi,
                        cari_id=cari_id,
                        sube_id=sube_id,
                    )
                    pv = session.scalar(select(PosValorKaydi).where(PosValorKaydi.belge_no == no))
                    kayit["pos_valor_id"] = int(pv.id) if pv is not None else None
                    ozet["onarilan"].append(kayit)
                except Exception as exc:
                    kayit["neden"] = str(exc)
                    ozet["hata"].append(kayit)
                    raise
        ozet["aday_sayisi"] = len(ozet["aday"])
        ozet["onarilan_sayisi"] = len(ozet["onarilan"])
        return ozet

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
    def banka_kartlari(aktif_only=True, *, hareketlerle: bool = True):
        """Banka kartları. Liste ekranı için ``hareketlerle=False`` (N×hareket yüklemez)."""
        with get_session() as session:
            alt = selectinload(BankaKarti.alt_hesaplar)
            if hareketlerle:
                alt = alt.selectinload(FinansHesabi.hareketler)
            q = (
                select(BankaKarti)
                .options(alt)
                .order_by(BankaKarti.banka_adi, BankaKarti.sube)
            )
            if aktif_only:
                q = q.where(BankaKarti.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def hesap_bakiyeleri_toplu(hesaplar) -> tuple[dict[int, Decimal], dict[int, list[str]]]:
        """Hesap id → ledger bakiyesi + hareket türleri. Hareket ORM yüklemez."""
        hesaplar = [h for h in (hesaplar or []) if getattr(h, "id", None) is not None]
        if not hesaplar:
            return {}, {}
        ids = [int(h.id) for h in hesaplar]
        bak = {int(h.id): Decimal(str(h.acilis_bakiyesi or 0)) for h in hesaplar}
        turler: dict[int, list[str]] = {int(h.id): [] for h in hesaplar}
        with get_session() as session:
            rows = session.execute(
                select(
                    FinansHareketi.hesap_id,
                    FinansHareketi.tutar,
                    FinansHareketi.hareket_turu,
                ).where(FinansHareketi.hesap_id.in_(ids))
            ).all()
        isaret: dict[str, int] = {}
        for hid, tutar, tur in rows:
            hid_i = int(hid)
            if tur not in isaret:
                isaret[tur] = FinansService.hareket_isareti(tur)
            bak[hid_i] = bak.get(hid_i, Decimal("0")) + Decimal(str(tutar or 0)) * isaret[tur]
            turler.setdefault(hid_i, []).append((tur or "").strip().upper())
        return bak, turler

    @staticmethod
    def bankalar_liste_satirlari(*, aktif_only: bool = False) -> dict:
        """Bankalar ekranı: tek seferde kart + ledger bakiyeleri + POS özeti.

        Dönüş: ``{"satirlar": [...], "aktif": n, "pasif": n}``.
        POS kolonu ``pos_aktif_alacak_ozeti`` neti (ledger değil).
        Krediler kolonu: banka kredisi kalan anapara borcu (negatif); kredi
        kaydı yoksa KREDILER ledger işletme bakiyesine düşer.
        """
        kartlar = FinansService.banka_kartlari(aktif_only=False, hareketlerle=False)
        tum_hesaplar = [h for k in kartlar for h in (k.alt_hesaplar or [])]
        ledger, hareket_turlari = FinansService.hesap_bakiyeleri_toplu(tum_hesaplar)
        pos_harita = FinansService.pos_aktif_alacak_haritalari()
        pos_by_banka = pos_harita["by_banka"]
        kalan_harita, kredi_olan = FinansService.banka_kredi_kalan_anapara_haritasi()
        bos_pos = Decimal("0.00")
        satirlar = []
        aktif = pasif = 0
        for kart in kartlar:
            if not kart.aktif:
                pasif += 1
                continue
            aktif += 1
            bak = {kod: Decimal("0") for kod, _ in BANKA_ALT_HESAP_TURLERI}
            for hesap in kart.alt_hesaplar or []:
                kod = (hesap.alt_hesap_turu or "").strip().upper()
                if kod not in bak or kod == "POS":
                    continue
                hid = int(hesap.id)
                ham = ledger.get(hid, Decimal("0"))
                bak[kod] += FinansService.varlik_bakiyesi(
                    ham,
                    alt_tur=kod,
                    hesap=hesap,
                    hareket_turlari=hareket_turlari.get(hid),
                )
            for kod in bak:
                bak[kod] = FinansService._para_sifirla(bak[kod])
            pos_net = FinansService._para_sifirla(
                Decimal(str((pos_by_banka.get(int(kart.id)) or {}).get("net") or 0))
            )
            kredi_borc = FinansService.banka_kredi_borc_gosterim(
                int(kart.id), kalan_harita=kalan_harita, kredi_olan=kredi_olan
            )
            satirlar.append(
                {
                    "id": int(kart.id),
                    "banka_adi": kart.banka_adi,
                    "sube": kart.sube or "",
                    "hesap_no": kart.hesap_no or "",
                    "iban": kart.iban or "",
                    "MEVDUAT": bak.get("MEVDUAT", bos_pos),
                    "KMH": bak.get("KMH", bos_pos),
                    "POS": pos_net,
                    "KREDI_KARTI": bak.get("KREDI_KARTI", bos_pos),
                    "KREDILER": (
                        kredi_borc if kredi_borc is not None else bak.get("KREDILER", bos_pos)
                    ),
                }
            )
        return {"satirlar": satirlar, "aktif": aktif, "pasif": pasif}

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
        """İlk eşleşen alt hesap. KK/Kredilerde boş yer tutucu yerine gerçek hesabı tercih eder."""
        tur = (alt_tur or "").upper()
        adaylar = [
            h
            for h in (kart.alt_hesaplar or [])
            if (h.alt_hesap_turu or "").upper() == tur
        ]
        if not adaylar:
            return None
        if tur not in {"KREDI_KARTI", "KREDILER"} or len(adaylar) == 1:
            return adaylar[0]

        def _borc_hesap_oncelik(h) -> tuple:
            ad = (h.hesap_adi or "").casefold()
            if tur == "KREDI_KARTI":
                yer = "— kredi kartı hesabı" in ad or ad.endswith("kredi kartı hesabı")
                # POS bağlı / tahsilat hesabı firma kartı borcu değildir
                pos = "pos" in ad
            else:
                yer = "— krediler hesabı" in ad or ad.endswith("krediler hesabı")
                pos = False
            bak = abs(FinansService.bakiye(h))
            return (
                1 if h.aktif else 0,
                0 if pos else 1,  # POS'u en sona
                0 if yer else 1,
                1 if bak > 0 else 0,
                int(h.id or 0),
            )

        return max(adaylar, key=_borc_hesap_oncelik)

    @staticmethod
    def kredi_alt_hesaplari(kart, *, yer_tutucu_dahil: bool = False) -> list:
        """Bankanın taksitli kredi (KREDILER) alt hesapları — KMH/KK/POS değil."""
        from database.hesap_siralama import hesaplari_sirala

        sonuc = []
        for h in kart.alt_hesaplar or []:
            if (h.alt_hesap_turu or "").upper() != "KREDILER":
                continue
            ad = (h.hesap_adi or "").casefold()
            yer = "— krediler hesabı" in ad or ad.endswith("krediler hesabı")
            if yer and not yer_tutucu_dahil:
                if abs(FinansService.bakiye(h)) <= Decimal("0.005"):
                    continue
            sonuc.append(h)
        return hesaplari_sirala(sonuc)

    @staticmethod
    def kk_alt_hesaplari(kart, *, yer_tutucu_dahil: bool = False) -> list:
        """Bankanın kredi kartı alt hesapları (POS tahsilatı değil; firma KK borcu)."""
        from database.hesap_siralama import hesaplari_sirala

        sonuc = []
        for h in kart.alt_hesaplar or []:
            if (h.alt_hesap_turu or "").upper() != "KREDI_KARTI":
                continue
            ad = (h.hesap_adi or "").casefold()
            yer = "— kredi kartı hesabı" in ad or ad.endswith("kredi kartı hesabı")
            if yer and not yer_tutucu_dahil:
                # Boş otomatik yer tutucu (Ana Kart oluştururken); bakiyeli olanlar kalır
                if abs(FinansService.bakiye(h)) <= Decimal("0.005"):
                    continue
            sonuc.append(h)
        return hesaplari_sirala(sonuc)

    @staticmethod
    def _kk_ad_normalize(ad: str) -> str:
        """KK adı eşlemesi: TR küçük harf + aksan sadeleştirme (İ/I, ş/s …)."""
        s = (ad or "").replace("İ", "i").replace("I", "ı")
        s = s.casefold()
        for src, dst in (
            ("ı", "i"),
            ("ş", "s"),
            ("ğ", "g"),
            ("ü", "u"),
            ("ö", "o"),
            ("ç", "c"),
        ):
            s = s.replace(src, dst)
        # Birleşik nokta (İ.casefold artığı)
        s = s.replace("\u0307", "")
        for p in ("kredi karti", "credit card", "hesabi", "—", "-"):
            s = s.replace(p, " ")
        # Kaynak yazım BUSİNES (business değil) — bütün kelime
        s = re.sub(r"\bbusines\b", "business", s)
        parcalar = []
        for p in s.split():
            if parcalar or not (p.isdigit() and len(p) <= 3):
                parcalar.append(p)
        return " ".join(parcalar).strip()

    @staticmethod
    def _kk_ad_benzerlik(a: str, b: str) -> float:
        ta = set(FinansService._kk_ad_normalize(a).split())
        tb = set(FinansService._kk_ad_normalize(b).split())
        if not ta or not tb:
            return 0.0
        kisa, uzun = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        # Kısa adın tüm anlamlı parçaları uzun adın içinde olmalı
        if not kisa.issubset(uzun):
            inter = len(ta & tb)
            return inter / max(len(ta), len(tb))
        return len(kisa) / max(len(ta), len(tb))

    @staticmethod
    def banka_bakiyeler(kart) -> dict[str, Decimal]:
        """Banka ana kartında aynı türdeki tüm gerçek alt hesapları topla.

        POS dahil ham hareket/ledger toplamıdır. Operasyonel bekleyen POS alacağı
        için ``banka_bakiyeler_varlik`` veya ``pos_aktif_alacak_ozeti`` kullanın.
        """
        sonuc = {kod: Decimal("0") for kod, _etiket in BANKA_ALT_HESAP_TURLERI}
        for hesap in kart.alt_hesaplar or []:
            kod = (hesap.alt_hesap_turu or "").strip().upper()
            if kod in sonuc:
                sonuc[kod] += FinansService.bakiye(hesap)
        return sonuc

    @staticmethod
    def pos_operasyonel_net(
        *,
        banka_karti_id=None,
        pos_hesap_id=None,
        kesim: date | None = None,
    ) -> Decimal:
        """Bekleyen POS alacağı (açık PosValor kalan net). Ledger hareket toplamı değildir."""
        ozet = FinansService.pos_aktif_alacak_ozeti(
            banka_karti_id=banka_karti_id,
            pos_hesap_id=pos_hesap_id,
            kesim=kesim,
        )
        return Decimal(str(ozet["net"] or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def pos_hesap_gosterim_bakiyesi(hesap) -> Decimal:
        """Tek POS alt hesabı için ekran/özet bakiyesi = operasyonel açık alacak."""
        if hesap is None:
            return Decimal("0")
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").strip().upper()
        if alt != "POS":
            return FinansService.bakiye(hesap)
        return FinansService.pos_operasyonel_net(pos_hesap_id=int(hesap.id))


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
    def _para_sifirla(tutar) -> Decimal:
        """İki ondalığa yuvarla; -0,00 oluşmasın."""
        deger = Decimal(str(tutar or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if deger == 0:
            return Decimal("0")
        return deger

    @staticmethod
    def _borc_ledger_native_yonlu(hesap=None, *, hareket_turlari=None) -> bool:
        """True: ledger'da borç büyüklüğü (+); işletme = −ham.

        False: Evo/devir gibi ledger zaten işletme yönünde (borç −, fazla ödeme +).
        Hesap yoksa çevirme yapılmaz (``varlik_bakiyesi`` hesabı zorunlu sayar).
        ``hareket_turlari`` verilirse lazy load yapılmaz (liste/toplu yol).
        """
        if hesap is None:
            return False
        native = False
        evo_banka = False
        if hareket_turlari is not None:
            turler = list(hareket_turlari)
        else:
            turler = []
            try:
                from sqlalchemy import inspect as sa_inspect

                insp = sa_inspect(hesap)
                if not insp.detached and "hareketler" not in insp.unloaded:
                    for har in hesap.hareketler or []:
                        turler.append((har.hareket_turu or "").strip().upper())
            except Exception:
                turler = []
        for tur in turler:
            tur_u = (tur or "").strip().upper()
            if any(tur_u.startswith(k) for k in _NATIVE_BORC_HAREKET_KOK):
                native = True
            if tur_u in {"BANKA GİRİŞ", "BANKA ÇIKIŞ", "BANKA GIRIS", "BANKA CIKIS"}:
                evo_banka = True
        if native and not evo_banka:
            return True
        if evo_banka and not native:
            return False
        acilis = Decimal(str(getattr(hesap, "acilis_bakiyesi", 0) or 0))
        # Negatif açılış → Evo borç; pozitif açılış → native borç büyüklüğü
        if acilis < Decimal("-0.005"):
            return False
        if acilis > Decimal("0.005"):
            return True
        # Açılış 0 + hareket yok/yüklenmemiş: çevirme (fazla ödeme + korunur)
        return False

    @staticmethod
    def isletme_bakiyesi(hesap) -> Decimal:
        """Tek hesabın ekran/özet işletme bakiyesi (ortak kaynak).

        POS → operasyonel açık alacak; KK/Krediler → Evo/native yön kuralı;
        Mevduat/KMH → ledger yönü. Mali kaydı değiştirmez.
        """
        if hesap is None:
            return Decimal("0")
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").strip().upper()
        if alt == "POS":
            return FinansService._para_sifirla(
                FinansService.pos_hesap_gosterim_bakiyesi(hesap)
            )
        ham = FinansService.bakiye(hesap)
        return FinansService.varlik_bakiyesi(ham, alt_tur=alt, hesap=hesap)

    @staticmethod
    def varlik_bakiyesi(
        tutar, alt_tur=None, hesap=None, hesap_turu=None, *, hareket_turlari=None
    ) -> Decimal:
        """İşletme bakiyesi: varlık +, bankaya borç −, sıfır nötr.

        Mevduat / KMH / POS: ledger (veya POS operasyonel) yönü korunur.
        KK / Krediler: native Cin'de borç ledger'da + tutulur → işaret çevrilir;
        Evo/devirde borç zaten − ise çevrilmez (körleme ikinci çeviri yok).
        Fazla ödeme / alacak bakiyesi her iki durumda da + görünür.
        ``hesap`` verilmeden borç hesabında işaret çevrilmez — fazla ödemeyi
        eksiye çeviren körleme native varsayımı kaldırıldı.
        ``hareket_turlari``: toplu liste yolunda lazy load yerine tür listesi.
        """
        deger = FinansService._para_sifirla(tutar)
        if not FinansService.borc_hesabi_mi(
            alt_tur=alt_tur, hesap=hesap, hesap_turu=hesap_turu
        ):
            return deger
        if hesap is None:
            # Çağıran hesap vermeli; aksi halde ham = işletme kabul (çift çevirme yok)
            return deger
        if FinansService._borc_ledger_native_yonlu(hesap, hareket_turlari=hareket_turlari):
            return FinansService._para_sifirla(-deger)
        return deger

    @staticmethod
    def banka_bakiyeler_varlik(kart) -> dict[str, Decimal]:
        """UI / varlık özeti: hesap bazında işletme yönü; POS = operasyonel açık alacak.

        POS satırı tarihî hareket (ledger) toplamı değildir; ``pos_aktif_alacak_ozeti``
        netini kullanır. Ham ledger için ``banka_bakiyeler`` / ``bakiye(POS)``.

        ``KREDILER``: bankada kredi kaydı varsa plan kalan anapara borcu (negatif);
        Ana Kart / Bankalar listesi ile aynı kaynak. Kredi kaydı yoksa ledger.
        """
        sonuc = {kod: Decimal("0") for kod, _etiket in BANKA_ALT_HESAP_TURLERI}
        for hesap in kart.alt_hesaplar or []:
            kod = (hesap.alt_hesap_turu or "").strip().upper()
            if kod not in sonuc or kod == "POS":
                continue
            sonuc[kod] += FinansService.isletme_bakiyesi(hesap)
        for kod in sonuc:
            sonuc[kod] = FinansService._para_sifirla(sonuc[kod])
        if getattr(kart, "id", None) is not None:
            # POS: banka düzeyinde açık alacak (hesap bazlı ledger toplamı değil)
            sonuc["POS"] = FinansService._para_sifirla(
                FinansService.pos_operasyonel_net(banka_karti_id=int(kart.id))
            )
            kredi_borc = FinansService.banka_kredi_borc_gosterim(int(kart.id))
            if kredi_borc is not None:
                sonuc["KREDILER"] = kredi_borc
        return sonuc

    @staticmethod
    def banka_varlik_borc_ozeti(kart) -> dict[str, Decimal]:
        """Ana kart özeti: varlık (+), borç büyüklüğü, borç gösterim (−), net."""
        bakiyeler = FinansService.banka_bakiyeler_varlik(kart)
        varlik = Decimal("0")
        borc_buyukluk = Decimal("0")
        for v in bakiyeler.values():
            d = Decimal(str(v or 0))
            if d > 0:
                varlik += d
            elif d < 0:
                borc_buyukluk += -d
        # Yatırım (VADELI) hesapları ana 5 sınıfta yok; varlık toplamına eklenir.
        yatirim_toplam = Decimal("0")
        for h in FinansService.yatirim_alt_hesaplari(kart, aktif_only=True):
            yatirim_toplam += FinansService.isletme_bakiyesi(h)
        yatirim_toplam = FinansService._para_sifirla(yatirim_toplam)
        if yatirim_toplam > 0:
            varlik += yatirim_toplam
        elif yatirim_toplam < 0:
            borc_buyukluk += -yatirim_toplam
        varlik = FinansService._para_sifirla(varlik)
        borc_buyukluk = FinansService._para_sifirla(borc_buyukluk)
        net = FinansService._para_sifirla(varlik - borc_buyukluk)
        bakiyeler = dict(bakiyeler)
        bakiyeler["YATIRIM"] = yatirim_toplam
        return {
            "varlik": varlik,
            "borc_buyukluk": borc_buyukluk,
            "borc_gosterim": FinansService._para_sifirla(-borc_buyukluk)
            if borc_buyukluk
            else Decimal("0"),
            "net": net,
            "bakiyeler": bakiyeler,
        }

    @staticmethod
    def para_metni(tutar, pb: str | None = "TRY", *, isaretli: bool = False) -> str:
        """Türkçe para metni.

        isaretli=True (bakiye alanları): pozitif ``1.234,56 TL`` (artı yok),
        negatif ``-1.234,56 TL``, sıfır ``0,00 TL``.
        isaretli=False: aynı biçimde; negatifte eksi korunur.
        """
        kod = (pb or "TRY").strip().upper() or "TRY"
        etiket = "TL" if kod == "TRY" else kod
        deger = FinansService._para_sifirla(tutar)
        sayi = f"{abs(deger):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if deger < 0:
            return f"-{sayi} {etiket}"
        if deger > 0:
            return f"{sayi} {etiket}"
        return f"0,00 {etiket}"

    @staticmethod
    def bakiye_renk_kodu(tutar) -> str:
        """Pozitif yeşil, negatif (borç) kırmızı, sıfır nötr — tüm raporlarda aynı."""
        deger = FinansService._para_sifirla(tutar)
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
            # Yalnızca yeni kartta eksik alt türleri otomatik oluştur.
            # Mevcut kartta bilerek silinen (ör. sıfır bakiyeli) placeholder'ları yeniden yaratma.
            yeni_kart = False
            if kart_id:
                kart = session.scalar(
                    select(BankaKarti)
                    .where(BankaKarti.id == int(kart_id))
                    .options(selectinload(BankaKarti.alt_hesaplar))
                )
            if not kart:
                yeni_kart = True
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
            # Aktarım hesabı: somut mevduat/KMH id; tür alanı senkron (geriye uyum)
            aktarim_hid = veriler.get("pos_aktarim_hesap_id")
            if aktarim_hid in ("", None):
                aktarim_hid = None
            else:
                try:
                    aktarim_hid = int(aktarim_hid)
                except (TypeError, ValueError) as hata:
                    raise ValueError("Aktarımın yatacağı hesap geçersiz.") from hata
            if aktarim_hid is not None:
                alt = next(
                    (
                        h
                        for h in (kart.alt_hesaplar or [])
                        if int(h.id) == aktarim_hid
                        and (h.alt_hesap_turu or "").upper() in POS_HEDEF_HESAP_TURLERI
                    ),
                    None,
                )
                if alt is None:
                    # Yeni kartta alt hesaplar henüz flush edilmemiş olabilir
                    session.flush()
                    alt = session.scalar(
                        select(FinansHesabi).where(
                            FinansHesabi.id == aktarim_hid,
                            FinansHesabi.banka_karti_id == kart.id,
                        )
                    )
                    if alt is None or (alt.alt_hesap_turu or "").upper() not in POS_HEDEF_HESAP_TURLERI:
                        raise ValueError(
                            "Aktarımın yatacağı hesap bu bankanın mevduat veya KMH hesabı olmalıdır."
                        )
                kart.pos_aktarim_hesap_id = int(alt.id)
                kart.pos_hedef_hesap_turu = (alt.alt_hesap_turu or "MEVDUAT").upper()
            else:
                hedef_tur = (veriler.get("pos_hedef_hesap_turu") or "MEVDUAT").strip().upper()
                if hedef_tur not in POS_HEDEF_HESAP_TURLERI:
                    raise ValueError("POS hedef hesabı Mevduat veya KMH olmalıdır.")
                kart.pos_hedef_hesap_turu = hedef_tur
                # Tür seçildiyse eşleşen alt hesabı id olarak da yaz (varsa)
                eslesen = next(
                    (
                        h
                        for h in (kart.alt_hesaplar or [])
                        if (h.alt_hesap_turu or "").upper() == hedef_tur
                    ),
                    None,
                )
                kart.pos_aktarim_hesap_id = int(eslesen.id) if eslesen is not None else None
            is_gunu_deger = veriler.get("pos_valor_is_gunu", True)
            if isinstance(is_gunu_deger, str):
                s = is_gunu_deger.strip().casefold()
                # "Takvim günü" → False; "İş günü" / evet / 1 → True
                is_gunu_deger = "takvim" not in s and s not in (
                    "0", "false", "hayır", "hayir", "h", "kapalı", "kapali",
                )
            kart.pos_valor_is_gunu = bool(is_gunu_deger)
            # Aktarım yöntemi: Manuel / Otomatik (karşılıklı dışlayan)
            yontem_ham = veriler.get("pos_aktarim_yontemi")
            if yontem_ham is None and "pos_otomatik_mahsup" in veriler:
                oto0 = veriler.get("pos_otomatik_mahsup", False)
                if isinstance(oto0, str):
                    s0 = oto0.strip().casefold()
                    oto0 = s0 in ("1", "true", "evet", "e", "açık", "acik") or s0.startswith("eve")
                yontem_ham = "OTOMATIK" if oto0 else "MANUEL"
            yontem = str(yontem_ham or "MANUEL").strip().upper()
            if yontem in ("OTO", "AUTO", "OTOMATİK", "OTOMATIK"):
                yontem = "OTOMATIK"
            elif yontem in ("MAN", "MANUEL", "MANUAL"):
                yontem = "MANUEL"
            else:
                raise ValueError("Bankaya aktarım yöntemi Manuel veya Otomatik olmalıdır.")
            kart.pos_aktarim_yontemi = yontem
            kart.pos_otomatik_mahsup = yontem == "OTOMATIK"
            bas_raw = veriler.get("pos_otomatik_baslangic")
            if yontem == "OTOMATIK":
                if isinstance(bas_raw, date):
                    kart.pos_otomatik_baslangic = bas_raw
                elif bas_raw and str(bas_raw).strip():
                    try:
                        kart.pos_otomatik_baslangic = datetime.strptime(
                            str(bas_raw).strip(), "%d.%m.%Y"
                        ).date()
                    except ValueError as hata:
                        raise ValueError(
                            "Otomatik aktarım başlangıç tarihi GG.AA.YYYY olmalıdır."
                        ) from hata
                else:
                    kart.pos_otomatik_baslangic = date.today()
            else:
                kart.pos_otomatik_baslangic = None
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
                            # Bilerek pasife alınan / silinen placeholder'ları kaydetmede zorla aktif etme
                            if yeni_kart:
                                h.aktif = True
                    continue
                if not yeni_kart:
                    # Mevcut kartta eksik tür = kullanıcı/temizlik silmiş; yeniden oluşturma
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
    def pos_alt_hesaplari(kart, *, aktif_only: bool = True) -> list:
        """Bankanın POS alt hesapları (birden fazla POS destekler)."""
        from database.hesap_siralama import hesaplari_sirala

        sonuc = []
        for h in kart.alt_hesaplar or []:
            if (h.alt_hesap_turu or "").upper() != "POS":
                continue
            if aktif_only and not h.aktif:
                continue
            sonuc.append(h)
        return hesaplari_sirala(sonuc)

    @staticmethod
    def yatirim_alt_hesaplari(kart, *, aktif_only: bool = True) -> list:
        """Bankanın yatırım (VADELI*) alt hesapları."""
        from database.hesap_siralama import hesaplari_sirala

        sonuc = []
        for h in kart.alt_hesaplar or []:
            alt = (h.alt_hesap_turu or "").strip().upper()
            if alt != "VADELI" and not alt.startswith("VADELI"):
                continue
            if aktif_only and not h.aktif:
                continue
            sonuc.append(h)
        return hesaplari_sirala(sonuc)

    @staticmethod
    def yatirim_hesabi_olustur(banka_karti_id, hesap_adi: str) -> FinansHesabi:
        """Bankaya yeni yatırım hesabı (VADELI) ekler."""
        yazma_zorunlu("finans_duzenleme")
        ad = (hesap_adi or "").strip()
        if not ad:
            raise ValueError("Yatırım hesabı adı zorunludur.")
        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti).where(BankaKarti.id == int(banka_karti_id))
            )
            if not kart:
                raise ValueError("Banka kartı bulunamadı.")
            cakisma = session.scalar(
                select(FinansHesabi).where(FinansHesabi.hesap_adi == ad)
            )
            if cakisma:
                raise ValueError("Bu hesap adı zaten kayıtlı.")
            hesap = FinansHesabi(
                hesap_adi=ad,
                hesap_turu="BANKA",
                alt_hesap_turu="VADELI",
                banka_karti_id=int(kart.id),
                banka_adi=kart.banka_adi,
                aktif=True,
                acilis_bakiyesi=Decimal("0"),
            )
            session.add(hesap)
            session.flush()
            hid = int(hesap.id)
        return FinansService.hesap_getir(hid)

    @staticmethod
    def pos_ayar_karti(hesap_veya_kart, banka_karti_id=None) -> BankaKarti | None:
        """POS komisyon/valör ayarının okunacağı banka kartı.

        Taşınmış POS hesabında ``[POS_KAYNAK_KART=id]`` varsa kaynak kartı kullanır.
        """
        from database.banka_yapi_tasima import pos_kaynak_kart_id

        hesap = None
        kart_id = banka_karti_id
        if isinstance(hesap_veya_kart, FinansHesabi):
            hesap = hesap_veya_kart
            kart_id = hesap.banka_karti_id
        elif isinstance(hesap_veya_kart, BankaKarti):
            return hesap_veya_kart
        elif hesap_veya_kart is not None:
            kart_id = getattr(hesap_veya_kart, "id", None) or kart_id

        kaynak_id = pos_kaynak_kart_id(hesap) if hesap is not None else None
        hedef_id = int(kaynak_id or kart_id or 0)
        if not hedef_id:
            return None
        return FinansService.banka_karti_getir(hedef_id)

    @staticmethod
    def banka_yapi_tasima_uygula() -> dict:
        """Ana listedeki özel kartları hedef bankalara taşır (idempotent)."""
        yazma_zorunlu("finans_duzenleme")
        from database.banka_yapi_tasima import banka_yapi_tasima_uygula as _uygula

        return _uygula()

    @staticmethod
    def banka_karti_kullanim_ozeti(kart_id) -> dict:
        """Banka kartının silme engelleri. Sıfır bakiye kullanılmamış sayılmaz."""
        from database.kart_silme import banka_karti_kullanim_ozeti

        return banka_karti_kullanim_ozeti(int(kart_id))

    @staticmethod
    def banka_karti_sil(kart_id, *, onaylandi: bool = False, session=None) -> dict:
        """Yalnızca finansal geçmişi olmayan banka kartını siler."""
        from database.kart_silme import banka_karti_sil

        return banka_karti_sil(int(kart_id), onaylandi=onaylandi, session=session)

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
        from database.models.finans import FinansBelgeNoRezerv

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
        # Kalıcı silinen numaralar yeniden verilmez
        try:
            from sqlalchemy import inspect as sa_inspect

            if sa_inspect(session.connection()).has_table(FinansBelgeNoRezerv.__tablename__):
                mevcut += session.scalars(
                    select(FinansBelgeNoRezerv.belge_no).where(FinansBelgeNoRezerv.belge_no.like(like))
                ).all()
        except Exception:
            pass
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
    def _fatura_ici_pos_cari_ci_yazma(session, belge_no: str) -> bool:
        """Fatura_no ile saklanan peşin/POS: cari etki SatisHareketi sessiz alacaktan gelir.

        Aynı belge_no ile CariIslem yazılırsa defter SH'yi atlayıp yalnız alacak gösterir
        (RAY-00347 / ABERRA kök nedeni). True → _cari_tahsilat_satiri çağırma.
        """
        no = (belge_no or "").strip()
        if not no:
            return False
        from database.models.satis_faturasi import SatisFaturasi

        fatura = session.scalar(select(SatisFaturasi).where(SatisFaturasi.fatura_no == no))
        return fatura is not None

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

            if "KASA VİRMAN ÇIKIŞ" in turler or "KASA VİRMAN GİRİŞ" in turler:
                cikis_h = next(
                    (h for h in hareketler if h.hareket_turu == "KASA VİRMAN ÇIKIŞ"),
                    None,
                )
                giris_h = next(
                    (h for h in hareketler if h.hareket_turu == "KASA VİRMAN GİRİŞ"),
                    None,
                )
                kaynak_id, _, _ = _hesap_bilgi(cikis_h)
                hedef_id, _, _ = _hesap_bilgi(giris_h)
                return {
                    "tur": "kvr",
                    "belge_no": belge_no,
                    "tarih": tarih,
                    "tutar": Decimal(str((cikis_h or hareketler[0]).tutar)),
                    "aciklama": acik,
                    "dekont_no": dekont,
                    "kaynak_kasa_id": kaynak_id,
                    "hedef_kasa_id": hedef_id,
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
    def banka_islem_fis_sil(belge_no: str) -> dict:
        """KBY/BNC/AHV/GHV/BVR/KVR fişini ve bağlı kasa/banka/cari hareketlerini siler."""
        yazma_zorunlu("finans_duzenleme")
        belge_no = (belge_no or "").strip()
        if not belge_no:
            raise ValueError("Belge numarası gerekli.")
        fis = FinansService.banka_islem_fis_getir(belge_no)
        with get_session() as session:
            hareketler = list(
                session.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)
                ).all()
            )
            if not hareketler:
                raise ValueError("Fiş bulunamadı.")
            hesap_ids = sorted({int(h.hesap_id) for h in hareketler if h.hesap_id})
            from database.finans_evrak_kimligi import kimlik_bul
            from database.muhasebe_entegrasyon import muhasebe_hook
            from database.odeme_sozu_service import OdemeSozuService

            if fis["tur"] in ("ahv", "ghv"):
                FinansService._havale_cari_geri_al(session, belge_no)
            evrak = "banka_havale" if fis["tur"] in ("ahv", "ghv") else "kasa_banka_virman"
            kimlik = kimlik_bul(session, evrak, belge_no)
            if kimlik is not None:
                muhasebe_hook(
                    "iptal_kaynak",
                    evrak,
                    int(kimlik.id),
                    f"Fiş silindi {belge_no}",
                    session=session,
                )
            FinansService._finans_hareketlerini_sil(session, belge_no)
            OdemeSozuService.evrak_baglantilarini_iptal(
                session, belge_no, neden=f"Fiş silindi {belge_no}"
            )
            session.flush()
            return {
                "belge_no": belge_no,
                "tur": fis["tur"],
                "hesap_ids": hesap_ids,
                "silinen": len(hareketler),
            }

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
                    dagitim_yontem="BAGLI",
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
            # Tedarikçi ödemesi defterde BORÇ (Evo BNC ile aynı): alacak bakiyesini düşürür.
            # Kod ön ekinden (T…) yön çıkarılmaz; cari_turu esas alınır.
            FinansService._kapatma_plani_uygula(session, cari.id, tutar, belge_no, tarih, "ODEME", plan)
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
            from database.hesap_siralama import hesaplari_sirala

            hesaplar = list(session.scalars(q).all())
            return hesaplari_sirala(
                h for h in hesaplar if FinansService._kby_hedef_uygun_mu(h)
            )

    @staticmethod
    def alt_hesaplar_listele(
        alt_turler=("MEVDUAT", "KMH", "VADELI"),
        banka_karti_id=None,
        aktif_only=True,
    ):
        """Tüm bankaların seçilen sınıf alt hesapları (Mevduat / KMH / Vadeli sınıf menüsü)."""
        from database.hesap_siralama import hesaplari_sirala

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
                .order_by(FinansHesabi.id)
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
            return hesaplari_sirala(sonuc)

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
        """Kasadan çıkış + banka hesabına (mevduat/KMH/vadeli) giriş.

        Kredi kartı hesabına yatırma ekstre ödemesidir: ekstre seçilir, ödeme ekstre
        ödeme akışıyla (kart borcu ve ekstre bir kez düşer) yazılır, KKE belge no döner.
        """
        yazma_zorunlu("finans_duzenleme")
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
        """Gönderen banka hesabından alıcı banka hesabına transfer/virman (VIRMAN / HAVALE / EFT / FAST).

        İsteğe bağlı banka masrafı aynı fişe bağlı ayrı çıkış hareketidir. Alıcı kredi kartıysa ekstre
        ödemesi olarak yazılır (ekstre seçimi zorunlu, KKE belge no döner).
        """
        yazma_zorunlu("finans_duzenleme")
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
        """Banka hesabından (mevduat/KMH/KK/vadeli) çıkış + kasaya giriş."""
        yazma_zorunlu("finans_duzenleme")
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
    def kasalar_arasi_virman(
        kaynak_kasa_id,
        hedef_kasa_id,
        tarih,
        tutar,
        aciklama=None,
        belge_no=None,
    ) -> str:
        """İki kasa arasında virman — kaynak çıkış + hedef giriş (KVR).

        Aynı PB gerekir; şirket toplam nakdi değişmez. Cari/gelir/gider yazılmaz.
        """
        yazma_zorunlu("finans_duzenleme")
        tutar = _decimal(tutar, "Tutar", Decimal("0.01"))
        if int(kaynak_kasa_id) == int(hedef_kasa_id):
            raise ValueError("Kaynak ve hedef kasa aynı olamaz.")
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

            kaynak = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(kaynak_kasa_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            hedef = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hedef_kasa_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not kaynak or not kaynak.aktif:
                raise ValueError("Kaynak kasa bulunamadı veya pasif.")
            if not hedef or not hedef.aktif:
                raise ValueError("Hedef kasa bulunamadı veya pasif.")
            if (kaynak.hesap_turu or "").upper() != "KASA":
                raise ValueError("Kaynak hesap bir kasa olmalıdır.")
            if (hedef.hesap_turu or "").upper() != "KASA":
                raise ValueError("Hedef hesap bir kasa olmalıdır.")
            # ANA pasif kaldıysa virman için yeniden etkinleştirme — aktif kontrolü yukarıda
            kaynak_pb = FinansService.hesap_pb(kaynak)
            hedef_pb = FinansService.hesap_pb(hedef)
            if kaynak_pb != hedef_pb:
                raise ValueError(
                    f"Aynı PB virmanı gerekir (kaynak {kaynak_pb}, hedef {hedef_pb})."
                )
            kasa_bak = FinansService.bakiye(kaynak)
            if kasa_bak < tutar:
                raise ValueError(
                    f"Kaynak kasa bakiyesi yetersiz. Bakiye {_fmt(kasa_bak)}, tutar {_fmt(tutar)}."
                )
            belgeno = belge_no or FinansService._finans_belge_no(session, "KVR")
            acik = aciklama or f"{kaynak.hesap_adi} → {hedef.hesap_adi}"
            session.add(
                FinansHareketi(
                    hesap_id=kaynak.id,
                    tarih=tarih,
                    hareket_turu="KASA VİRMAN ÇIKIŞ",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.add(
                FinansHareketi(
                    hesap_id=hedef.id,
                    tarih=tarih,
                    hareket_turu="KASA VİRMAN GİRİŞ",
                    belge_no=belgeno,
                    tutar=tutar,
                    aciklama=acik,
                )
            )
            session.flush()
            FinansService._muhasebe_evrak(
                session, "kasa_banka_virman", belgeno, "kasa_banka_virman_fisi", bool(belge_no)
            )
            return belgeno

    @staticmethod
    def kasalar_arasi_virman_listele(limit=300):
        """KVR fişleri (çıkış + giriş kasa eşlemesi)."""
        with get_session() as session:
            cikislar = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.hareket_turu == "KASA VİRMAN ÇIKIŞ")
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
                        FinansHareketi.hareket_turu == "KASA VİRMAN GİRİŞ",
                        FinansHareketi.belge_no.in_(belge_nos),
                    )
                    .options(selectinload(FinansHareketi.hesap))
                ).all()
            )
            giris_map = {h.belge_no: h for h in girisler}
            sonuc = []
            for h in cikislar:
                g = giris_map.get(h.belge_no)
                sonuc.append(
                    {
                        "belge_no": h.belge_no,
                        "tarih": h.tarih,
                        "tutar": Decimal(str(h.tutar)),
                        "aciklama": h.aciklama or "",
                        "kaynak_kasa": h.hesap.hesap_adi if h.hesap else "—",
                        "hedef_kasa": g.hesap.hesap_adi if g and g.hesap else "—",
                        "kaynak_kasa_id": h.hesap_id,
                        "hedef_kasa_id": g.hesap_id if g else None,
                    }
                )
            return sonuc

    @staticmethod
    def bugun_tr() -> date:
        """Europe/Istanbul takvim günü (gece yarısı sınırı)."""
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo("Europe/Istanbul")).date()
        except Exception:
            return date.today()

    @staticmethod
    def kasa_gunluk_ozet(gun: date | None = None) -> dict:
        """Ana kasa listesi: Devir / Bugünkü Tahsilat / Bugünkü Ödeme / Bakiye.

        gun=None → Europe/Istanbul bugünü. Kesim: [gun 00:00, ertesi 00:00).
        Formül bakiye() ile aynıdır (açılış + işaretli hareketler).
        İç virman (KVR) kasa satırında görünür; şirket dış toplamından ayıklanır.
        """
        from database.hesap_siralama import hesaplari_sirala

        gun = gun or FinansService.bugun_tr()
        with get_session() as session:
            kasalar = hesaplari_sirala(
                session.scalars(
                    select(FinansHesabi)
                    .where(
                        FinansHesabi.hesap_turu == "KASA",
                        FinansHesabi.aktif.is_(True),
                    )
                    .options(selectinload(FinansHesabi.hareketler))
                    .order_by(FinansHesabi.id)
                ).all()
            )
            satirlar = []
            dis_giris = Decimal("0")
            dis_cikis = Decimal("0")
            for k in kasalar:
                pb = FinansService.hesap_pb(k)
                acilis = Decimal(str(k.acilis_bakiyesi or 0))
                giris = Decimal("0")
                cikis = Decimal("0")
                onceki_net = Decimal("0")
                gun_net = Decimal("0")
                ic_giris = Decimal("0")
                ic_cikis = Decimal("0")
                for h in k.hareketler or []:
                    t = h.tarih
                    if t is None:
                        continue
                    tut = Decimal(str(h.tutar or 0))
                    isaret = FinansService.hareket_isareti(h.hareket_turu)
                    tur = (h.hareket_turu or "").upper()
                    ic = tur in {"KASA VİRMAN GİRİŞ", "KASA VİRMAN ÇIKIŞ", "KASA VİRMAN"}
                    if t < gun:
                        onceki_net += tut * Decimal(isaret)
                    elif t == gun:
                        gun_net += tut * Decimal(isaret)
                        if isaret > 0:
                            giris += tut
                            if ic:
                                ic_giris += tut
                        elif isaret < 0:
                            cikis += tut
                            if ic:
                                ic_cikis += tut
                # bakiye() ile aynı: acilis + tüm işaretli hareketler (gün sonu = ≤ gun)
                devir = acilis + onceki_net
                bakiye = acilis + onceki_net + gun_net
                satirlar.append(
                    {
                        "hesap_id": k.id,
                        "ad": k.hesap_adi,
                        "pb": pb,
                        "devir": devir,
                        "tahsilat": giris,
                        "odeme": cikis,
                        "bakiye": bakiye,
                        "aciklama": (k.aciklama or "")[:60],
                        "durum": "Aktif" if k.aktif else "Pasif",
                        "ic_giris": ic_giris,
                        "ic_cikis": ic_cikis,
                    }
                )
                dis_giris += giris - ic_giris
                dis_cikis += cikis - ic_cikis
            pb_ozet: dict[str, dict[str, Decimal]] = {}
            for s in satirlar:
                pb = s["pb"]
                g = pb_ozet.setdefault(
                    pb,
                    {
                        "devir": Decimal("0"),
                        "tahsilat": Decimal("0"),
                        "odeme": Decimal("0"),
                        "bakiye": Decimal("0"),
                    },
                )
                g["devir"] += s["devir"]
                g["tahsilat"] += s["tahsilat"]
                g["odeme"] += s["odeme"]
                g["bakiye"] += s["bakiye"]
            return {
                "gun": gun,
                "satirlar": satirlar,
                "dis_giris": dis_giris,
                "dis_cikis": dis_cikis,
                "toplam_devir": sum((s["devir"] for s in satirlar), Decimal("0")),
                "toplam_tahsilat": sum((s["tahsilat"] for s in satirlar), Decimal("0")),
                "toplam_odeme": sum((s["odeme"] for s in satirlar), Decimal("0")),
                "toplam_bakiye": sum((s["bakiye"] for s in satirlar), Decimal("0")),
                "pb_toplamlar": {
                    pb: {k: v for k, v in oz.items()} for pb, oz in pb_ozet.items()
                },
            }

    @staticmethod
    def hareket_ozet_getir(hareket_id: int) -> dict | None:
        """Tek hareket kimliği → tür + belge (açma için; liste sırasına güvenilmez)."""
        with get_session() as session:
            h = session.get(FinansHareketi, int(hareket_id))
            if not h:
                return None
            return {
                "id": h.id,
                "hareket_turu": h.hareket_turu or "",
                "belge_no": h.belge_no or "",
                "hesap_id": h.hesap_id,
                "tarih": h.tarih,
                "tutar": Decimal(str(h.tutar or 0)),
            }

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
                oran = Decimal(str(r.komisyon_orani or 0))
                # Tabloda 0 satırı (UI tüm taksitleri yazar) tek çekimde özel oran sayılmaz
                if oran > 0 or n > 1:
                    return oran
                break
        # Yedek: tek çekim için eski alan (POS Sözleşmeleri kk_komisyon_orani)
        if n == 1:
            return Decimal(str(kart.kk_komisyon_orani or 0))
        return Decimal("0")

    @staticmethod
    def _pos_komisyon_orani_guncel(kart: BankaKarti, kart_tipi: str, taksit_sayisi: int = 1) -> Decimal:
        """Sözleşme oranı; KK tek çekimde kayıtlı oran yoksa %1,99 yedek."""
        oran = FinansService._pos_komisyon_orani(kart, kart_tipi, taksit_sayisi)
        tip = (kart_tipi or "").upper()
        n = int(taksit_sayisi or 1)
        if n < 1:
            n = 1
        if tip == "KREDI_KARTI" and n == 1 and oran <= 0:
            return POS_KK_TEK_CEKIM_YEDEK_ORAN
        return oran

    @staticmethod
    def pos_bekleyen_komisyon_yenile(*, pos_hesap_id) -> dict:
        """Aktarımı başlamamış BEKLIYOR fişlerinde komisyonu güncel sözleşmeden brüte göre yeniden hesaplar.

        Güncellenen alanlar: komisyon_orani, komisyon_tutari, net_tutar.
        Kalan net = beklenen net − aktarılan; aktarım yoksa kalan = net.
        Idempotent: her çalıştırmada brüt × oran / 100 (kuruş) ile yeniden üretir.
        """
        yazma_zorunlu("finans_duzenleme")
        pos_id = int(pos_hesap_id)
        with get_session() as session:
            pos = session.get(FinansHesabi, pos_id)
            if pos is None:
                raise ValueError("POS hesabı bulunamadı.")
            if (pos.alt_hesap_turu or "").upper() != "POS":
                raise ValueError("Seçilen hesap POS alt hesabı değil.")

            ayar_kart = FinansService.pos_ayar_karti(pos)
            if ayar_kart is None:
                raise ValueError("POS sözleşme kartı bulunamadı.")
            # Taksit oranları için ilişkiyi yükle
            ayar_kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(ayar_kart.id))
                .options(selectinload(BankaKarti.pos_taksit_komisyonlari))
            )
            if ayar_kart is None:
                raise ValueError("POS sözleşme kartı bulunamadı.")

            kayitlar = list(
                session.scalars(
                    select(PosValorKaydi)
                    .where(PosValorKaydi.pos_hesap_id == pos_id)
                    .order_by(PosValorKaydi.tahsilat_tarihi, PosValorKaydi.id)
                ).all()
            )
            guncellenen = []
            brut_toplam = Decimal("0")
            eski_kom_toplam = Decimal("0")
            yeni_kom_toplam = Decimal("0")
            eski_net_toplam = Decimal("0")
            yeni_net_toplam = Decimal("0")

            for k in kayitlar:
                durum = (k.durum or "").strip().upper()
                if durum != "BEKLIYOR":
                    continue
                akt = Decimal(str(k.gercek_yatis_tutari or 0))
                if akt > Decimal("0.005"):
                    continue
                if k.gercek_yatis_tarihi is not None:
                    continue
                if (k.aktarim_belge_no or "").strip():
                    continue
                if k.aktarim_zamani is not None:
                    continue

                tip = (k.kart_tipi or "KREDI_KARTI").upper()
                n = int(k.taksit_sayisi or 1)
                brut = Decimal(str(k.brut_tutar or 0)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                oran = FinansService._pos_komisyon_orani_guncel(ayar_kart, tip, n)
                komisyon = (brut * oran / Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                net = (brut - komisyon).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if net < 0:
                    raise ValueError(
                        f"POS #{k.id}: komisyon brüt tutardan büyük olamaz."
                    )

                eski_oran = Decimal(str(k.komisyon_orani or 0))
                eski_kom = Decimal(str(k.komisyon_tutari or 0)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                eski_net = Decimal(str(k.net_tutar or 0)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                eski_kalan = FinansService.pos_aktarim_kalan_net(k)

                k.komisyon_orani = oran
                k.komisyon_tutari = komisyon
                k.net_tutar = net
                # Aktarım yok → kalan net beklenen nete eşit (türetilmiş alan)
                yeni_kalan = FinansService.pos_aktarim_kalan_net(k)

                brut_toplam += brut
                eski_kom_toplam += eski_kom
                yeni_kom_toplam += komisyon
                eski_net_toplam += eski_net
                yeni_net_toplam += net
                guncellenen.append(
                    {
                        "id": int(k.id),
                        "belge_no": k.belge_no,
                        "kart_tipi": tip,
                        "taksit_sayisi": n,
                        "brut": brut,
                        "eski_oran": eski_oran,
                        "yeni_oran": oran,
                        "eski_komisyon": eski_kom,
                        "yeni_komisyon": komisyon,
                        "eski_net": eski_net,
                        "yeni_net": net,
                        "eski_kalan": eski_kalan,
                        "yeni_kalan": yeni_kalan,
                    }
                )
                try:
                    from database.pos_komisyon_gider_service import PosKomisyonGiderService

                    PosKomisyonGiderService.senkronize(session, k, kesin=False)
                except Exception:
                    pass

            session.flush()
            return {
                "pos_hesap_id": pos_id,
                "pos_hesap_adi": pos.hesap_adi,
                "banka_karti_id": int(ayar_kart.id),
                "banka_adi": ayar_kart.banka_adi,
                "adet": len(guncellenen),
                "brut_toplam": brut_toplam.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                "eski_komisyon_toplam": eski_kom_toplam.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                "yeni_komisyon_toplam": yeni_kom_toplam.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                "eski_net_toplam": eski_net_toplam.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                "yeni_net_toplam": yeni_net_toplam.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                "kayitlar": guncellenen,
            }

    @staticmethod
    def _pos_kayit_imza(k: "PosValorKaydi") -> dict:
        """Eşzamanlı düzenleme için kayıt anlık görüntüsü (kimlik alanları)."""
        return {
            "id": int(k.id),
            "brut": str(Decimal(str(k.brut_tutar or 0))),
            "komisyon": str(Decimal(str(k.komisyon_tutari or 0))),
            "net": str(Decimal(str(k.net_tutar or 0))),
            "durum": (k.durum or "").strip().upper(),
            "gercek_yatis": str(Decimal(str(k.gercek_yatis_tutari or 0))),
            "cari_id": str(k.cari_id or ""),
            "pos_hesap_id": str(k.pos_hesap_id),
            "hedef_hesap_id": str(
                getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id
            ),
        }

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
        *,
        komisyon_orani=None,
        komisyon_tutari=None,
        diger_kesinti=None,
        valor_gun=None,
        valor_tarihi=None,
        hedef_hesap_id=None,
        pos_hesap_id=None,
        pos_valor_id=None,
        beklenen_imza=None,
        pva_duzelt=False,
    ) -> dict:
        """POS'a brüt giriş + komisyon; net beklenen valörde hedef hesaba planlanır.

        Komisyon/valör varsayılanı karttan gelir; verilen override işlemle saklanır
        (kart sonradan değişince geçmiş yeniden hesaplanmaz).
        ``pos_hesap_id`` ile çoklu POS'tan biri seçilir; taşınmış POS'ta kaynak
        kart ayarları (``[POS_KAYNAK_KART]``) kullanılır.
        Güncellemede ``pos_valor_id`` belge numarasından önce gelir.
        """
        yazma_zorunlu("finans_duzenleme")
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
            eski = None
            if pos_valor_id is not None:
                eski = session.get(PosValorKaydi, int(pos_valor_id))
            elif belge_no:
                eski = session.scalar(
                    select(PosValorKaydi).where(PosValorKaydi.belge_no == belge_no)
                )
            if eski is not None:
                if (eski.durum or "").strip().upper() in ("IPTAL", "İPTAL"):
                    raise ValueError("İptal edilmiş POS tahsilatı güncellenemez.")
                # Yerinde güncelleme: aktarılmış/kısmi dahil — ikinci tahsilat/PVA üretmez
                return FinansService._pos_tahsilat_bagli_guncelle(
                    session,
                    eski,
                    banka_karti_id=banka_karti_id,
                    tarih=tarih,
                    brut_tutar=brut,
                    kart_tipi=tip,
                    cari_id=cari_id,
                    aciklama=aciklama,
                    taksit_sayisi=n,
                    referans_no=referans_no,
                    komisyon_orani=komisyon_orani,
                    komisyon_tutari=komisyon_tutari,
                    diger_kesinti=diger_kesinti,
                    valor_gun=valor_gun,
                    valor_tarihi=valor_tarihi,
                    hedef_hesap_id=hedef_hesap_id,
                    pos_hesap_id=pos_hesap_id,
                    beklenen_imza=beklenen_imza,
                    pva_duzelt=pva_duzelt,
                )
            if belge_no or pos_valor_id is not None:
                raise ValueError("Güncellenecek POS tahsilat fişi bulunamadı.")

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
            if pos_hesap_id:
                pos = next(
                    (
                        h
                        for h in kart.alt_hesaplar
                        if int(h.id) == int(pos_hesap_id)
                        and (h.alt_hesap_turu or "").upper() == "POS"
                    ),
                    None,
                )
                if pos is None:
                    raise ValueError("Seçilen POS hesabı bu banka kartına ait değil.")
            else:
                pos = next(
                    (h for h in kart.alt_hesaplar if (h.alt_hesap_turu or "") == "POS"),
                    None,
                )
            hedef = FinansService._pos_hedef_hesap(kart)
            if hedef_hesap_id:
                alt = next(
                    (h for h in kart.alt_hesaplar if int(h.id) == int(hedef_hesap_id)),
                    None,
                )
                if alt is None:
                    raise ValueError("Seçilen hedef hesap bu banka kartına ait değil.")
                hedef = alt
            if not pos or not hedef:
                raise ValueError(
                    "POS veya hedef hesap (mevduat/KMH) eksik — banka kartını kaydedin."
                )

            # Taşınmış POS (ör. PayTR): komisyon/valör kaynak karttan
            from database.banka_yapi_tasima import pos_kaynak_kart_id

            ayar_kart = kart
            kaynak_id = pos_kaynak_kart_id(pos)
            if kaynak_id:
                kaynak = session.scalar(
                    select(BankaKarti)
                    .where(BankaKarti.id == int(kaynak_id))
                    .options(selectinload(BankaKarti.pos_taksit_komisyonlari))
                )
                if kaynak is not None:
                    ayar_kart = kaynak

            oran_kart = FinansService._pos_komisyon_orani(ayar_kart, tip, n)
            if komisyon_tutari is not None and str(komisyon_tutari).strip() != "":
                komisyon = _decimal(komisyon_tutari, "Komisyon tutarı", Decimal("0"))
                if komisyon < 0:
                    raise ValueError("Komisyon tutarı negatif olamaz.")
                oran = (
                    (komisyon * Decimal("100") / brut).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    if brut > 0
                    else Decimal("0")
                )
            elif komisyon_orani is not None and str(komisyon_orani).strip() != "":
                oran = _decimal(komisyon_orani, "Komisyon oranı", Decimal("0"))
                if oran < 0 or oran > 100:
                    raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
                komisyon = (brut * oran / Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                oran = oran_kart
                if oran < 0 or oran > 100:
                    raise ValueError("Komisyon oranı 0-100 arasında olmalıdır.")
                komisyon = (brut * oran / Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            kesinti = Decimal("0")
            if diger_kesinti is not None and str(diger_kesinti).strip() != "":
                kesinti = _decimal(diger_kesinti, "Diğer kesinti", Decimal("0"))
                if kesinti < 0:
                    raise ValueError("Diğer kesinti negatif olamaz.")
            net = brut - komisyon - kesinti
            if net < 0:
                raise ValueError("Komisyon + kesinti brüt tutardan büyük olamaz.")

            is_gunu = bool(
                getattr(ayar_kart, "pos_valor_is_gunu", True)
                if getattr(ayar_kart, "pos_valor_is_gunu", None) is not None
                else True
            )
            if valor_gun is not None and str(valor_gun).strip() != "":
                try:
                    v_gun = int(str(valor_gun).strip())
                except ValueError as hata:
                    raise ValueError("Valör günü tam sayı olmalıdır.") from hata
            else:
                v_gun = int(ayar_kart.pos_valor_gun or 1)
            if v_gun < 0:
                raise ValueError("Valör günü negatif olamaz.")
            if valor_tarihi is not None:
                v_tarih = valor_tarihi
            else:
                v_tarih = valor_tarihi_hesapla(tarih, v_gun, is_gunu=is_gunu)
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
            if kesinti > 0:
                session.add(
                    FinansHareketi(
                        hesap_id=pos.id,
                        tarih=tarih,
                        hareket_turu="POS KOMİSYON",
                        belge_no=belgeno,
                        tutar=kesinti,
                        aciklama="Diğer kesinti",
                    )
                )
            if cari_id and not FinansService._fatura_ici_pos_cari_ci_yazma(session, belgeno):
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
                valor_tarihi=v_tarih,
                valor_saati=POS_VALOR_SAATI,
                kart_tipi=tip,
                taksit_sayisi=n,
                brut_tutar=brut,
                komisyon_orani=oran,
                komisyon_tutari=komisyon,
                net_tutar=net,
                diger_kesinti=kesinti,
                valor_gun=v_gun,
                cari_id=int(cari_id) if cari_id else None,
                durum="BEKLIYOR",
                aciklama=acik,
            )
            session.add(kayit)
            session.flush()
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("pos_tahsilat_fisi", int(kayit.id), session=session)
            try:
                from database.pos_komisyon_gider_service import PosKomisyonGiderService

                PosKomisyonGiderService.senkronize(session, kayit, kesin=False)
            except Exception:
                pass
            return {
                "belge_no": belgeno,
                "brut": brut,
                "komisyon": komisyon,
                "komisyon_orani": oran,
                "diger_kesinti": kesinti,
                "net": net,
                "taksit_sayisi": n,
                "valor_gun": v_gun,
                "valor_tarihi": v_tarih,
                "valor_saati": POS_VALOR_SAATI,
                "hedef_hesap_id": hedef.id,
                "hedef_hesap_adi": hedef.hesap_adi,
                "kayit_id": kayit.id,
            }

    @staticmethod
    def _pos_degisiklik_kaydet(session, kayit, eski: dict, yeni: dict) -> None:
        """Alan bazında eski/yeni farklarını PosValorDegisiklik + audit_logs'a yazar."""
        try:
            from database.user_audit import current_actor

            actor = current_actor()
            uid, uname = actor["user_id"], actor.get("full_name") or actor.get("username")
            zaman = actor["now"]
        except Exception:
            uid, uname, zaman = None, None, datetime.now()
        def _norm(v):
            if v is None:
                return None
            try:
                return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            except Exception:
                return str(v)

        degisen = {}
        for alan, yeni_v in (yeni or {}).items():
            eski_v = (eski or {}).get(alan)
            # Para alanlarını kuruşa normalize et; aksi halde metin karşılaştır
            if alan in (
                "brut", "komisyon", "komisyon_orani", "diger_kesinti", "net", "cari_id",
                "banka_karti_id", "hedef_hesap_id", "valor_gun",
            ):
                e_s, y_s = _norm(eski_v), _norm(yeni_v)
            else:
                e_s, y_s = (None if eski_v is None else str(eski_v)), (
                    None if yeni_v is None else str(yeni_v)
                )
            if e_s == y_s:
                continue
            degisen[alan] = {"eski": e_s, "yeni": y_s}
            session.add(
                PosValorDegisiklik(
                    pos_valor_id=int(kayit.id) if getattr(kayit, "id", None) else None,
                    belge_no=kayit.belge_no,
                    alan=str(alan)[:60],
                    eski_deger=None if e_s is None else e_s[:200],
                    yeni_deger=None if y_s is None else y_s[:200],
                    kullanici_id=uid,
                    kullanici_adi=uname,
                    zaman=zaman,
                )
            )
        if degisen:
            try:
                from database.user_audit import audit_document

                audit_document(
                    "POS_TAHSILAT_GUNCELLE",
                    modul="finans_pos",
                    kayit_id=str(getattr(kayit, "id", "") or ""),
                    belge_no=kayit.belge_no,
                    eski={k: v["eski"] for k, v in degisen.items()},
                    yeni={k: v["yeni"] for k, v in degisen.items()},
                )
            except Exception:
                pass

    @staticmethod
    def pos_degisiklik_gecmisi(belge_no: str) -> list[dict]:
        belge_no = (belge_no or "").strip()
        if not belge_no:
            return []
        with get_session() as session:
            try:
                kayitlar = list(
                    session.scalars(
                        select(PosValorDegisiklik)
                        .where(PosValorDegisiklik.belge_no == belge_no)
                        .order_by(PosValorDegisiklik.zaman.desc(), PosValorDegisiklik.id.desc())
                    ).all()
                )
            except Exception:
                return []
            return [
                {
                    "alan": k.alan,
                    "eski": k.eski_deger,
                    "yeni": k.yeni_deger,
                    "kullanici": k.kullanici_adi or (f"#{k.kullanici_id}" if k.kullanici_id else "—"),
                    "zaman": k.zaman,
                }
                for k in kayitlar
            ]

    @staticmethod
    def _pos_pva_bagli_kayitlar(session, pva_belge: str) -> list[PosValorKaydi]:
        """Aktarım belgesi token eşleşmesi (CSV kısmi aktarımlarda yanlış contains yok)."""
        belge = (pva_belge or "").strip()
        if not belge:
            return []
        adaylar = list(
            session.scalars(
                select(PosValorKaydi).where(PosValorKaydi.aktarim_belge_no.contains(belge))
            ).all()
        )
        sonuc = []
        for p in adaylar:
            tokenler = {
                t.strip()
                for t in (getattr(p, "aktarim_belge_no", None) or "").split(",")
                if t.strip()
            }
            if belge in tokenler:
                sonuc.append(p)
        return sonuc

    @staticmethod
    def _pos_pva_toplam_yenile(session, pva_belge: str) -> Decimal:
        """Ortak/tekil PVA finans hareket tutarını Σ gercek_yatis yapar; fiş çoğaltmaz."""
        belge = (pva_belge or "").strip()
        if not belge:
            return Decimal("0")
        bagli = FinansService._pos_pva_bagli_kayitlar(session, belge)
        toplam = sum(
            (Decimal(str(p.gercek_yatis_tutari or 0)) for p in bagli),
            Decimal("0"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        hareketler = list(
            session.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == belge)).all()
        )
        if not hareketler:
            return toplam
        for h in hareketler:
            # Yalnız aktarım satırları (POS↔hedef); başka tür varsa dokunma
            tur = (h.hareket_turu or "").upper()
            if "POS VALÖR AKTARIM" in tur or tur.startswith("POS VAL"):
                h.tutar = toplam
            elif len(hareketler) <= 2:
                # Klasik 2 satırlı PVA
                h.tutar = toplam
        session.flush()
        return toplam

    @staticmethod
    def pos_aktarim_belge_getir(aktarim_belge_no: str) -> dict:
        """PVA banka aktarım fişi — bağlı hareketler ve POS kayıtları."""
        belge = (aktarim_belge_no or "").strip().split(",")[-1].strip()
        if not belge:
            raise ValueError("Aktarım belge numarası gerekli.")
        with get_session() as session:
            hareketler = list(
                session.scalars(
                    select(FinansHareketi)
                    .where(FinansHareketi.belge_no == belge)
                    .options(selectinload(FinansHareketi.hesap))
                    .order_by(FinansHareketi.id)
                ).all()
            )
            if not hareketler:
                raise ValueError(f"Banka aktarım fişi bulunamadı: {belge}")
            pos_kayitlari = FinansService._pos_pva_bagli_kayitlar(session, belge)
            return {
                "belge_no": belge,
                "tarih": hareketler[0].tarih,
                "hareketler": [
                    {
                        "id": int(h.id),
                        "hesap_id": int(h.hesap_id),
                        "hesap_adi": h.hesap.hesap_adi if h.hesap else "",
                        "hareket_turu": h.hareket_turu,
                        "tutar": Decimal(str(h.tutar)),
                        "aciklama": h.aciklama or "",
                    }
                    for h in hareketler
                ],
                "pos_kayitlari": [
                    {
                        "id": int(p.id),
                        "belge_no": p.belge_no,
                        "net": Decimal(str(p.net_tutar)),
                        "aktarilan": Decimal(str(p.gercek_yatis_tutari or 0)),
                        "durum": p.durum,
                        "banka_teyidi": bool(getattr(p, "banka_teyidi", False)),
                        "banka_teyidi_tarihi": getattr(p, "banka_teyidi_tarihi", None),
                        "banka_teyidi_notu": getattr(p, "banka_teyidi_notu", None) or "",
                        "banka_teyidi_kullanici": getattr(p, "banka_teyidi_kullanici", None) or "",
                        "aktarim_yontemi": getattr(p, "aktarim_yontemi", None) or "",
                        "gercek_yatis_tarihi": getattr(p, "gercek_yatis_tarihi", None),
                    }
                    for p in pos_kayitlari
                ],
                "pva_toplam": sum(
                    (Decimal(str(p.gercek_yatis_tutari or 0)) for p in pos_kayitlari),
                    Decimal("0"),
                ),
            }

    @staticmethod
    def _pos_tahsilat_bagli_guncelle(
        session,
        eski: PosValorKaydi,
        *,
        banka_karti_id,
        tarih,
        brut_tutar,
        kart_tipi,
        cari_id,
        aciklama,
        taksit_sayisi,
        referans_no,
        komisyon_orani,
        komisyon_tutari,
        diger_kesinti,
        valor_gun,
        valor_tarihi,
        hedef_hesap_id,
        pos_hesap_id=None,
        beklenen_imza=None,
        pva_duzelt=False,
    ) -> dict:
        """Aktarılmış/kısmi POS fişini yerinde günceller; PVA bağlantısını koparmaz."""
        yazma_zorunlu("finans_duzenleme")
        if beklenen_imza:
            guncel = FinansService._pos_kayit_imza(eski)
            bek = {k: str(v) for k, v in dict(beklenen_imza).items()}
            for anahtar in (
                "id",
                "brut",
                "komisyon",
                "net",
                "durum",
                "gercek_yatis",
                "cari_id",
                "pos_hesap_id",
                "hedef_hesap_id",
            ):
                if anahtar in bek and bek[anahtar] != str(guncel.get(anahtar)):
                    raise ValueError(
                        "Bu POS evrakı başka bir oturumda değişmiş. "
                        "Kaydetmeden önce fişi yeniden açın."
                    )
        brut = _decimal(brut_tutar, "Tahsilat tutarı", Decimal("0.01"))
        tip = (kart_tipi or "KREDI_KARTI").strip().upper()
        n = int(taksit_sayisi or 1)
        akt = Decimal(str(eski.gercek_yatis_tutari or 0))
        eski_snap = {
            "tarih": str(eski.tahsilat_tarihi),
            "brut": str(eski.brut_tutar),
            "komisyon_orani": str(eski.komisyon_orani),
            "komisyon": str(eski.komisyon_tutari),
            "diger_kesinti": str(getattr(eski, "diger_kesinti", 0) or 0),
            "net": str(eski.net_tutar),
            "valor_gun": str(getattr(eski, "valor_gun", "") or ""),
            "valor_tarihi": str(eski.valor_tarihi),
            "cari_id": str(eski.cari_id or ""),
            "banka_karti_id": str(eski.banka_karti_id),
            "pos_hesap_id": str(eski.pos_hesap_id),
            "hedef_hesap_id": str(getattr(eski, "hedef_hesap_id", None) or eski.kmh_hesap_id),
            "aciklama": eski.aciklama or "",
            "durum": eski.durum,
        }
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
        pos_adaylari = [
            h for h in (kart.alt_hesaplar or []) if (h.alt_hesap_turu or "").upper() == "POS"
        ]
        pos = None
        if pos_hesap_id is not None and str(pos_hesap_id).strip() != "":
            pos = next(
                (h for h in pos_adaylari if int(h.id) == int(pos_hesap_id)),
                None,
            )
            if pos is None:
                raise ValueError("Seçilen POS hesabı bu banka kartına ait değil.")
        elif int(eski.banka_karti_id) == int(kart.id):
            # Aynı bankada mevcut POS hesabını koru (PayTR / çoklu POS)
            pos = next(
                (h for h in pos_adaylari if int(h.id) == int(eski.pos_hesap_id)),
                None,
            )
        if pos is None:
            pos = pos_adaylari[0] if pos_adaylari else None
        hedef = FinansService._pos_hedef_hesap(kart)
        if hedef_hesap_id:
            alt = next((h for h in kart.alt_hesaplar if int(h.id) == int(hedef_hesap_id)), None)
            if alt is None:
                raise ValueError("Seçilen hedef hesap bu banka kartına ait değil.")
            hedef = alt
        if not pos or not hedef:
            raise ValueError("POS veya hedef hesap eksik.")

        oran_kart = FinansService._pos_komisyon_orani(kart, tip, n)
        if komisyon_tutari is not None and str(komisyon_tutari).strip() != "":
            komisyon = _decimal(komisyon_tutari, "Komisyon tutarı", Decimal("0"))
            oran = (
                (komisyon * Decimal("100") / brut).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                if brut > 0
                else Decimal("0")
            )
        elif komisyon_orani is not None and str(komisyon_orani).strip() != "":
            oran = _decimal(komisyon_orani, "Komisyon oranı", Decimal("0"))
            komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            oran = Decimal(str(eski.komisyon_orani or oran_kart))
            komisyon = (brut * oran / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        kesinti = Decimal("0")
        if diger_kesinti is not None and str(diger_kesinti).strip() != "":
            kesinti = _decimal(diger_kesinti, "Diğer kesinti", Decimal("0"))
        else:
            kesinti = Decimal(str(getattr(eski, "diger_kesinti", 0) or 0))
        net = brut - komisyon - kesinti
        if net < 0:
            raise ValueError("Komisyon + kesinti brüt tutardan büyük olamaz.")
        if net + Decimal("0.005") < akt:
            raise ValueError(
                f"Yeni net ({net}) aktarılmış tutardan ({akt}) küçük olamaz; "
                "önce aktarım düzeltmesi gerekir."
            )

        is_gunu = bool(
            getattr(kart, "pos_valor_is_gunu", True)
            if getattr(kart, "pos_valor_is_gunu", None) is not None
            else True
        )
        if valor_gun is not None and str(valor_gun).strip() != "":
            v_gun = int(str(valor_gun).strip())
        else:
            v_gun = int(getattr(eski, "valor_gun", None) or kart.pos_valor_gun or 1)
        v_tarih = valor_tarihi if valor_tarihi is not None else valor_tarihi_hesapla(
            tarih, v_gun, is_gunu=is_gunu
        )
        tip_etiket = dict(POS_KART_TIPLERI).get(tip, tip)
        taksit_metin = "Tek çekim" if n == 1 else f"{n} taksit"
        acik = aciklama or f"POS tahsilat ({tip_etiket} / {taksit_metin})"
        ref = (referans_no or "").strip()
        if ref and "| Ref:" not in acik:
            acik = f"{acik} | Ref: {ref}"

        belgeno = eski.belge_no
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook(
            "pos_tahsilat_iptal", int(eski.id), "POS tahsilatı bağlı güncelleme", session=session
        )
        # Yalnız tahsilat belgesi cari/FH — PVA belgelerine dokunma
        FinansService._havale_cari_geri_al(session, belgeno)
        FinansService._finans_hareketlerini_sil(session, belgeno)
        session.flush()

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
        if kesinti > 0:
            session.add(
                FinansHareketi(
                    hesap_id=pos.id,
                    tarih=tarih,
                    hareket_turu="POS KOMİSYON",
                    belge_no=belgeno,
                    tutar=kesinti,
                    aciklama="Diğer kesinti",
                )
            )
        # Fatura içi peşin: _havale_cari_geri_al yukarıda hatalı CI'yi siler; yeniden yazma
        if cari_id and not FinansService._fatura_ici_pos_cari_ci_yazma(session, belgeno):
            FinansService._cari_tahsilat_satiri(
                session, cari_id, tarih, brut, belgeno, pos.hesap_adi, acik
            )

        eski_net = Decimal(str(eski.net_tutar or 0))
        # Ortak/tekil PVA: yalnızca açıkça istenirse veya aktarılan tutar değişmediyse yenile.
        # Komisyon/net değişince gerçek banka geçiş tutarını kendiliğinden eşitleme.
        pva_tokenleri = [
            t.strip()
            for t in (getattr(eski, "aktarim_belge_no", None) or "").split(",")
            if t.strip()
        ]
        net_degisti = abs(net - eski_net) > Decimal("0.005")
        if (
            pva_duzelt
            and akt > 0
            and abs(akt - eski_net) <= Decimal("0.005")
            and net_degisti
            and net + Decimal("0.005") >= akt
        ):
            # Kullanıcı onayladı: aktarılmış tutarı yeni nete çek (yalnız bu POS payı)
            akt = net
            eski.gercek_yatis_tutari = net

        eski.banka_karti_id = kart.id
        eski.pos_hesap_id = pos.id
        eski.kmh_hesap_id = hedef.id
        eski.hedef_hesap_id = hedef.id
        eski.tahsilat_tarihi = tarih
        eski.valor_tarihi = v_tarih
        eski.kart_tipi = tip
        eski.taksit_sayisi = n
        eski.brut_tutar = brut
        eski.komisyon_orani = oran
        eski.komisyon_tutari = komisyon
        eski.diger_kesinti = kesinti
        eski.net_tutar = net
        eski.valor_gun = v_gun
        eski.cari_id = int(cari_id) if cari_id else None
        eski.aciklama = acik
        if akt <= Decimal("0.005"):
            eski.durum = "BEKLIYOR"
            eski.gercek_yatis_tutari = Decimal("0")
        elif akt + Decimal("0.005") >= net:
            eski.durum = "AKTARILDI"
            eski.gercek_yatis_tutari = akt
        else:
            eski.durum = "KISMEN"
            eski.gercek_yatis_tutari = akt
        session.flush()
        # Bağlı PVA fişlerini yeniden topla (diğer POS satırları korunur; mükerrer fiş yok)
        if pva_tokenleri and (pva_duzelt or not net_degisti or akt <= Decimal("0.005")):
            for pva_belge in pva_tokenleri:
                FinansService._pos_pva_toplam_yenile(session, pva_belge)
        muhasebe_hook("pos_tahsilat_fisi", int(eski.id), session=session)
        try:
            from database.pos_komisyon_gider_service import PosKomisyonGiderService

            PosKomisyonGiderService.senkronize(session, eski)
        except Exception:
            pass
        yeni_snap = {
            "tarih": str(tarih),
            "brut": str(brut),
            "komisyon_orani": str(oran),
            "komisyon": str(komisyon),
            "diger_kesinti": str(kesinti),
            "net": str(net),
            "valor_gun": str(v_gun),
            "valor_tarihi": str(v_tarih),
            "cari_id": str(cari_id or ""),
            "banka_karti_id": str(kart.id),
            "pos_hesap_id": str(pos.id),
            "hedef_hesap_id": str(hedef.id),
            "aciklama": acik,
            "durum": eski.durum,
        }
        FinansService._pos_degisiklik_kaydet(session, eski, eski_snap, yeni_snap)
        return {
            "belge_no": belgeno,
            "brut": brut,
            "komisyon": komisyon,
            "komisyon_orani": oran,
            "diger_kesinti": kesinti,
            "net": net,
            "taksit_sayisi": n,
            "valor_gun": v_gun,
            "valor_tarihi": v_tarih,
            "valor_saati": eski.valor_saati or POS_VALOR_SAATI,
            "hedef_hesap_id": hedef.id,
            "hedef_hesap_adi": hedef.hesap_adi,
            "pos_hesap_id": int(pos.id),
            "pos_hesap_adi": pos.hesap_adi,
            "kayit_id": eski.id,
            "bagli_guncelleme": True,
            "durum": eski.durum,
            "gercek_yatis_tutari": Decimal(str(eski.gercek_yatis_tutari or 0)),
            "aktarim_belge_no": getattr(eski, "aktarim_belge_no", None) or "",
            "pva_yenilendi": bool(pva_tokenleri and (pva_duzelt or not net_degisti or akt <= 0)),
        }

    @staticmethod
    def pos_tahsilat_listele(
        limit=500,
        sadece_kk=True,
        *,
        banka_karti_id=None,
        pos_hesap_id=None,
        cari_id=None,
        durum_filtre=None,
        tarih_bas=None,
        tarih_bit=None,
        valor_bas=None,
        valor_bit=None,
        yatis_bas=None,
        yatis_bit=None,
        ara=None,
        bugun: date | None = None,
        aktarim_yontemi=None,
        banka_teyidi=None,
    ):
        """POS işlem listesi — filtreler UI/rapor ortak."""
        from database.models.cari import Cari

        bugun = bugun or date.today()
        with get_session() as session:
            q = select(PosValorKaydi).order_by(
                PosValorKaydi.tahsilat_tarihi.desc(), PosValorKaydi.id.desc()
            )
            if sadece_kk:
                q = q.where(PosValorKaydi.kart_tipi == "KREDI_KARTI")
            if banka_karti_id:
                q = q.where(PosValorKaydi.banka_karti_id == int(banka_karti_id))
            if pos_hesap_id:
                q = q.where(PosValorKaydi.pos_hesap_id == int(pos_hesap_id))
            if cari_id:
                q = q.where(PosValorKaydi.cari_id == int(cari_id))
            if tarih_bas:
                q = q.where(PosValorKaydi.tahsilat_tarihi >= tarih_bas)
            if tarih_bit:
                q = q.where(PosValorKaydi.tahsilat_tarihi <= tarih_bit)
            if valor_bas:
                q = q.where(PosValorKaydi.valor_tarihi >= valor_bas)
            if valor_bit:
                q = q.where(PosValorKaydi.valor_tarihi <= valor_bit)
            if yatis_bas:
                q = q.where(PosValorKaydi.gercek_yatis_tarihi >= yatis_bas)
            if yatis_bit:
                q = q.where(PosValorKaydi.gercek_yatis_tarihi <= yatis_bit)
            if limit:
                q = q.limit(int(limit))
            kayitlar = list(session.scalars(q).all())
            if not kayitlar:
                return []
            cari_ids = {k.cari_id for k in kayitlar if k.cari_id}
            cari_map = {}
            cari_kod = {}
            if cari_ids:
                for c in session.scalars(select(Cari).where(Cari.id.in_(cari_ids))).all():
                    cari_map[c.id] = f"{c.cari_kodu} - {c.unvan}"
                    cari_kod[c.id] = c.cari_kodu or ""
            banka_ids = {k.banka_karti_id for k in kayitlar}
            banka_map = {}
            if banka_ids:
                for b in session.scalars(select(BankaKarti).where(BankaKarti.id.in_(banka_ids))).all():
                    banka_map[b.id] = b.banka_adi
            hesap_ids = {k.pos_hesap_id for k in kayitlar} | {
                int(getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id) for k in kayitlar
            }
            hesap_map = {}
            if hesap_ids:
                for h in session.scalars(select(FinansHesabi).where(FinansHesabi.id.in_(hesap_ids))).all():
                    hesap_map[h.id] = h.hesap_adi
            # Makbuz/fatura bağı — pos_valor_id → fatura_id listesi (tahmin yok)
            fatura_map: dict[int, str] = {}
            fatura_id_map: dict[int, list[int]] = {}
            try:
                from database.models.finans import KasaMakbuzSatiri, SatisFaturaMakbuzBagi
                from database.models.satis_faturasi import SatisFaturasi

                pv_ids = [int(k.id) for k in kayitlar]
                satirlar = (
                    list(
                        session.scalars(
                            select(KasaMakbuzSatiri).where(
                                KasaMakbuzSatiri.pos_valor_id.in_(pv_ids)
                            )
                        ).all()
                    )
                    if pv_ids
                    else []
                )
                makbuz_ids = {int(s.makbuz_id) for s in satirlar if s.makbuz_id}
                baglar = {}
                if makbuz_ids and FinansService._bag_tablosu_var(session):
                    for b in session.scalars(
                        select(SatisFaturaMakbuzBagi).where(
                            SatisFaturaMakbuzBagi.makbuz_id.in_(makbuz_ids)
                        )
                    ).all():
                        baglar[int(b.makbuz_id)] = int(b.fatura_id)
                fatura_ids = set(baglar.values())
                fat_no = {}
                if fatura_ids:
                    for f in session.scalars(
                        select(SatisFaturasi).where(SatisFaturasi.id.in_(fatura_ids))
                    ).all():
                        fat_no[int(f.id)] = f.fatura_no
                for s in satirlar:
                    fid = baglar.get(int(s.makbuz_id)) if s.makbuz_id else None
                    if fid and s.pos_valor_id:
                        pvid = int(s.pos_valor_id)
                        fatura_map[pvid] = fat_no.get(fid, "")
                        fatura_id_map.setdefault(pvid, [])
                        if int(fid) not in fatura_id_map[pvid]:
                            fatura_id_map[pvid].append(int(fid))
                # Fatura içi KK tahsilatı: belge_no = fatura_no (makbuz bağı yok)
                eksik_belgeler = {
                    (k.belge_no or "").strip()
                    for k in kayitlar
                    if int(k.id) not in fatura_map and (k.belge_no or "").strip()
                }
                if eksik_belgeler:
                    for f in session.scalars(
                        select(SatisFaturasi).where(SatisFaturasi.fatura_no.in_(eksik_belgeler))
                    ).all():
                        no = (f.fatura_no or "").strip()
                        if not no:
                            continue
                        for k in kayitlar:
                            pvid = int(k.id)
                            if (k.belge_no or "").strip() == no and pvid not in fatura_map:
                                fatura_map[pvid] = no
                                fatura_id_map.setdefault(pvid, [])
                                if int(f.id) not in fatura_id_map[pvid]:
                                    fatura_id_map[pvid].append(int(f.id))
            except Exception:
                fatura_map = {}
                fatura_id_map = {}

            sonuc = []
            ara_q = (ara or "").strip().casefold()
            for k in kayitlar:
                n = int(getattr(k, "taksit_sayisi", None) or 1)
                bil = FinansService.pos_aktarim_durum_bilgisi(k, bugun=bugun)
                if durum_filtre:
                    df = str(durum_filtre).strip().upper()
                    if df == "GECIKEN" and bil["ek_isaret"] != "Gecikti":
                        continue
                    if df == "VALOR_BUGUN" and bil["ek_isaret"] != "Valörü geldi":
                        continue
                    if df == "AKTARILMAMIS" and bil["durum_kod"] == "AKTARILDI":
                        continue
                    if df in ("BEKLIYOR", "KISMEN", "AKTARILDI", "IPTAL") and bil["durum_kod"] != df:
                        continue
                satir = {
                    "id": int(k.id),
                    "belge_no": k.belge_no,
                    "tarih": k.tahsilat_tarihi,
                    "saat": getattr(k, "valor_saati", None) or "",
                    "cari": cari_map.get(k.cari_id, "—"),
                    "cari_kodu": cari_kod.get(k.cari_id, ""),
                    "cari_id": k.cari_id,
                    "banka": banka_map.get(k.banka_karti_id, ""),
                    "banka_karti_id": k.banka_karti_id,
                    "pos_hesap_id": int(k.pos_hesap_id),
                    "pos_hesap": hesap_map.get(int(k.pos_hesap_id), ""),
                    "hedef_hesap_id": int(getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id),
                    "hedef_hesap": hesap_map.get(
                        int(getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id), ""
                    ),
                    "taksit_sayisi": n,
                    "cekim": "Tek çekim" if n == 1 else f"{n} taksit",
                    "brut": Decimal(str(k.brut_tutar)),
                    "komisyon": Decimal(str(k.komisyon_tutari)),
                    "komisyon_orani": Decimal(str(k.komisyon_orani)),
                    "diger_kesinti": Decimal(str(getattr(k, "diger_kesinti", 0) or 0)),
                    "net": Decimal(str(k.net_tutar)),
                    "valor_gun": getattr(k, "valor_gun", None),
                    "valor_tarihi": k.valor_tarihi,
                    "gercek_yatis_tarihi": getattr(k, "gercek_yatis_tarihi", None),
                    "gercek_yatis_tutari": Decimal(str(k.gercek_yatis_tutari or 0)),
                    "aktarilan_net": bil["aktarilan_net"],
                    "kalan_net": bil["kalan_net"],
                    "durum": bil["durum"],
                    "durum_kod": bil["durum_kod"],
                    "ek_isaret": bil["ek_isaret"],
                    "aktarim_belge_no": getattr(k, "aktarim_belge_no", None) or "",
                    "aktarim_yontemi": getattr(k, "aktarim_yontemi", None) or "",
                    "banka_teyidi": bool(getattr(k, "banka_teyidi", False)),
                    "banka_teyidi_tarihi": getattr(k, "banka_teyidi_tarihi", None),
                    "banka_teyidi_notu": getattr(k, "banka_teyidi_notu", None) or "",
                    "banka_teyidi_kullanici": getattr(k, "banka_teyidi_kullanici", None) or "",
                    "fatura_no": fatura_map.get(int(k.id), ""),
                    "fatura_id": (fatura_id_map.get(int(k.id)) or [None])[0],
                    "fatura_idler": list(fatura_id_map.get(int(k.id)) or []),
                    "aciklama": k.aciklama or "",
                    "para_birimi": "TRY",
                }
                if aktarim_yontemi:
                    ay = str(aktarim_yontemi).strip().upper()
                    if (satir.get("aktarim_yontemi") or "").upper() != ay:
                        continue
                if banka_teyidi is not None:
                    if bool(satir.get("banka_teyidi")) != bool(banka_teyidi):
                        continue
                if ara_q:
                    havuz = " ".join(
                        str(satir.get(a) or "")
                        for a in (
                            "belge_no",
                            "cari",
                            "cari_kodu",
                            "banka",
                            "pos_hesap",
                            "aktarim_belge_no",
                            "fatura_no",
                            "aciklama",
                        )
                    ).casefold()
                    if ara_q not in havuz:
                        continue
                sonuc.append(satir)
            return sonuc

    @staticmethod
    def pos_tahsilat_getir(belge_no: str | None = None, *, pos_valor_id=None) -> dict:
        from database.models.cari import Cari

        belge_no = (belge_no or "").strip()
        with get_session() as session:
            k = None
            if pos_valor_id is not None:
                k = session.get(PosValorKaydi, int(pos_valor_id))
            elif belge_no:
                k = session.scalar(
                    select(PosValorKaydi)
                    .where(PosValorKaydi.belge_no == belge_no)
                    .where(~PosValorKaydi.durum.in_(("IPTAL", "İPTAL")))
                    .order_by(PosValorKaydi.id.desc())
                )
                if k is None:
                    k = session.scalar(
                        select(PosValorKaydi)
                        .where(PosValorKaydi.belge_no == belge_no)
                        .order_by(PosValorKaydi.id.desc())
                    )
            if not k:
                raise ValueError("POS tahsilat fişi bulunamadı.")
            cari = session.get(Cari, k.cari_id) if k.cari_id else None
            pos_hesap = session.get(FinansHesabi, k.pos_hesap_id)
            hedef = session.get(
                FinansHesabi, int(getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id)
            )
            banka = session.get(BankaKarti, k.banka_karti_id)
            bil = FinansService.pos_aktarim_durum_bilgisi(k)
            makbuz_satir = session.scalar(
                select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == int(k.id))
            )
            makbuz_no = None
            if makbuz_satir is not None:
                makbuz = session.get(KasaMakbuzu, makbuz_satir.makbuz_id)
                makbuz_no = (makbuz.belge_no if makbuz else None) or None
            ref = ""
            acik = k.aciklama or ""
            if "| Ref:" in acik:
                parca = acik.split("| Ref:", 1)
                acik = parca[0].strip()
                ref = parca[1].strip() if len(parca) > 1 else ""
            return {
                "id": int(k.id),
                "belge_no": k.belge_no,
                "tarih": k.tahsilat_tarihi,
                "tutar": Decimal(str(k.brut_tutar)),
                "banka_karti_id": k.banka_karti_id,
                "banka_adi": (banka.banka_adi if banka else "") or "",
                "pos_hesap_id": int(k.pos_hesap_id),
                "pos_hesap_adi": (pos_hesap.hesap_adi if pos_hesap else "") or "",
                "hedef_hesap_id": int(getattr(k, "hedef_hesap_id", None) or k.kmh_hesap_id),
                "hedef_hesap_adi": (hedef.hesap_adi if hedef else "") or "",
                "cari_id": k.cari_id,
                "cari_etiket": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                "cari_kodu": cari.cari_kodu if cari else "",
                "cari_unvan": cari.unvan if cari else "",
                "taksit_sayisi": int(getattr(k, "taksit_sayisi", None) or 1),
                "kart_tipi": k.kart_tipi,
                "komisyon_orani": Decimal(str(k.komisyon_orani)),
                "komisyon_tutari": Decimal(str(k.komisyon_tutari)),
                "diger_kesinti": Decimal(str(getattr(k, "diger_kesinti", 0) or 0)),
                "valor_gun": getattr(k, "valor_gun", None),
                "valor_tarihi": k.valor_tarihi,
                "gercek_yatis_tarihi": getattr(k, "gercek_yatis_tarihi", None),
                "gercek_yatis_tutari": Decimal(str(k.gercek_yatis_tutari or 0)),
                "aktarim_belge_no": getattr(k, "aktarim_belge_no", None) or "",
                "aktarim_yontemi": getattr(k, "aktarim_yontemi", None) or "",
                "banka_teyidi": bool(getattr(k, "banka_teyidi", False)),
                "net": Decimal(str(k.net_tutar)),
                "durum": k.durum,
                "durum_kod": bil["durum_kod"],
                "ek_isaret": bil["ek_isaret"],
                "referans_no": ref,
                "aciklama": acik,
                "makbuz_bagli": makbuz_satir is not None,
                "makbuz_belge_no": makbuz_no,
                "imza": FinansService._pos_kayit_imza(k),
            }

    @staticmethod
    def pos_valor_aktif_bul(
        belge_no: str | None = None, *, pos_valor_id=None, cari_id=None
    ) -> dict | None:
        """Aktif (iptal olmayan) POS kaydını belge no veya id ile bulur."""
        no = (belge_no or "").strip()
        with get_session() as session:
            k = None
            if pos_valor_id is not None:
                k = session.get(PosValorKaydi, int(pos_valor_id))
            elif no:
                q = select(PosValorKaydi).where(
                    PosValorKaydi.belge_no == no,
                    ~PosValorKaydi.durum.in_(("IPTAL", "İPTAL")),
                )
                if cari_id is not None:
                    q = q.where(
                        or_(
                            PosValorKaydi.cari_id == int(cari_id),
                            PosValorKaydi.cari_id.is_(None),
                        )
                    )
                k = session.scalar(q.order_by(PosValorKaydi.id.desc()))
            if k is None or (k.durum or "").strip().upper() in ("IPTAL", "İPTAL"):
                return None
            makbuz_satir = session.scalar(
                select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == int(k.id))
            )
            makbuz_no = None
            if makbuz_satir is not None:
                makbuz = session.get(KasaMakbuzu, makbuz_satir.makbuz_id)
                makbuz_no = makbuz.belge_no if makbuz else None
            from database.models.cari import Cari

            cari = session.get(Cari, k.cari_id) if k.cari_id else None
            pos_hesap = session.get(FinansHesabi, k.pos_hesap_id)
            return {
                "id": int(k.id),
                "belge_no": k.belge_no,
                "tarih": k.tahsilat_tarihi,
                "brut": Decimal(str(k.brut_tutar or 0)),
                "komisyon": Decimal(str(k.komisyon_tutari or 0)),
                "net": Decimal(str(k.net_tutar or 0)),
                "cari": f"{cari.cari_kodu} — {cari.unvan}" if cari else "—",
                "cari_id": k.cari_id,
                "pos_hesap": (pos_hesap.hesap_adi if pos_hesap else "") or "—",
                "makbuz_bagli": makbuz_satir is not None,
                "makbuz_belge_no": makbuz_no,
                "aktarim_belge_no": getattr(k, "aktarim_belge_no", None) or "",
                "gercek_yatis_tutari": Decimal(str(k.gercek_yatis_tutari or 0)),
                "durum": k.durum,
            }

    @staticmethod
    def pos_bagli_faturalar(pos_valor_id) -> list[dict]:
        """POS valör kaydına bağlı satış faturaları (id, no, tarih, tutar).

        Zincir: pos_valor_id → KasaMakbuzSatiri → SatisFaturaMakbuzBagi → SatisFaturasi.
        Yedek: belge_no == fatura_no (fatura içi POS). Tahmin/benzerlik kullanılmaz.
        """
        from database.models.satis_faturasi import SatisFaturasi

        try:
            pvid = int(pos_valor_id)
        except (TypeError, ValueError):
            return []
        with get_session() as session:
            pv = session.get(PosValorKaydi, pvid)
            if pv is None:
                return []
            fatura_ids: list[int] = []
            seen: set[int] = set()
            satirlar = list(
                session.scalars(
                    select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == pvid)
                ).all()
            )
            makbuz_ids = {int(s.makbuz_id) for s in satirlar if s.makbuz_id}
            if makbuz_ids and FinansService._bag_tablosu_var(session):
                from database.models.finans import SatisFaturaMakbuzBagi

                for b in session.scalars(
                    select(SatisFaturaMakbuzBagi).where(
                        SatisFaturaMakbuzBagi.makbuz_id.in_(makbuz_ids)
                    )
                ).all():
                    fid = int(b.fatura_id)
                    if fid not in seen:
                        seen.add(fid)
                        fatura_ids.append(fid)
            belge = (pv.belge_no or "").strip()
            if belge:
                fat = session.scalar(
                    select(SatisFaturasi).where(
                        SatisFaturasi.fatura_no == belge,
                        SatisFaturasi.is_deleted.is_(False),
                    )
                )
                if fat is not None and int(fat.id) not in seen:
                    seen.add(int(fat.id))
                    fatura_ids.append(int(fat.id))
            if not fatura_ids:
                return []
            sonuc: list[dict] = []
            for fid in fatura_ids:
                f = session.get(SatisFaturasi, fid)
                if f is None or bool(getattr(f, "is_deleted", False)):
                    continue
                try:
                    tutar = Decimal(
                        str(
                            getattr(f, "tl_genel_toplam", None)
                            or getattr(f, "genel_toplam", None)
                            or getattr(f, "toplam", 0)
                            or 0
                        )
                    )
                except Exception:
                    tutar = Decimal("0")
                sonuc.append(
                    {
                        "fatura_id": int(f.id),
                        "fatura_no": (f.fatura_no or "").strip(),
                        "tarih": getattr(f, "fatura_tarihi", None),
                        "tutar": tutar,
                        "cari_id": getattr(f, "cari_id", None),
                    }
                )
            return sonuc

    @staticmethod
    def pos_bagli_evraklar(belge_no: str, *, cari_id=None) -> list[dict]:
        """Aynı belge numarasına bağlı açılabilir evraklar (POS / fatura / makbuz)."""
        no = (belge_no or "").strip()
        if not no:
            return []
        sonuc: list[dict] = []
        with get_session() as session:
            pv = FinansService.pos_valor_aktif_bul(no, cari_id=cari_id)
            if pv:
                sonuc.append(
                    {
                        "tur": "pos_tahsilat",
                        "etiket": f"POS tahsilatı · {pv['belge_no']} · {_fmt(pv['brut'])} TL",
                        "belge_no": pv["belge_no"],
                        "pos_valor_id": pv["id"],
                        "makbuz_bagli": pv["makbuz_bagli"],
                        "makbuz_belge_no": pv.get("makbuz_belge_no"),
                    }
                )
            from database.models.satis_faturasi import SatisFaturasi

            fat = session.scalar(
                select(SatisFaturasi).where(
                    SatisFaturasi.fatura_no == no,
                    SatisFaturasi.is_deleted.is_(False),
                )
            )
            if fat is not None:
                sonuc.append(
                    {
                        "tur": "satis_faturasi",
                        "etiket": f"Satış faturası · {fat.fatura_no}",
                        "belge_no": fat.fatura_no,
                        "belge_id": int(fat.id),
                    }
                )
            makbuz = session.scalar(
                select(KasaMakbuzu).where(
                    KasaMakbuzu.belge_no == no,
                    ~KasaMakbuzu.durum.in_(("IPTAL", "İPTAL")),
                )
            )
            if makbuz is not None:
                sonuc.append(
                    {
                        "tur": "makbuz",
                        "etiket": f"Tahsilat makbuzu · {makbuz.belge_no}",
                        "belge_no": makbuz.belge_no,
                        "makbuz_id": int(makbuz.id),
                    }
                )
        return sonuc

    @staticmethod
    def pos_silme_ozeti(pos_valor_id: int) -> dict:
        """Silme onayında gösterilecek özet + etkilenecek bağlı kayıtlar."""
        with get_session() as session:
            pv = session.get(PosValorKaydi, int(pos_valor_id))
            if pv is None:
                raise ValueError("POS tahsilat kaydı bulunamadı.")
            if (pv.durum or "").strip().upper() in ("IPTAL", "İPTAL"):
                raise ValueError("POS tahsilatı zaten iptal.")
            from database.models.cari import Cari, SatisHareketi

            cari = session.get(Cari, pv.cari_id) if pv.cari_id else None
            pos_hesap = session.get(FinansHesabi, pv.pos_hesap_id)
            hedef = session.get(
                FinansHesabi, int(getattr(pv, "hedef_hesap_id", None) or pv.kmh_hesap_id)
            )
            makbuz_satir = session.scalar(
                select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == int(pv.id))
            )
            baglilar: list[str] = []
            if makbuz_satir is not None:
                makbuz = session.get(KasaMakbuzu, makbuz_satir.makbuz_id)
                baglilar.append(
                    f"Makbuz satırı: {(makbuz.belge_no if makbuz else '—')} "
                    "(makbuz ekranından silinmeli)"
                )
            akt = Decimal(str(pv.gercek_yatis_tutari or 0))
            pva = (getattr(pv, "aktarim_belge_no", None) or "").strip()
            if akt > 0 or pva:
                baglilar.append(
                    f"Banka aktarımı: {pva or '—'} · aktarılan {_fmt(akt)} TL "
                    "(önce geri alınır; toplu PVA’daki diğer POS payları korunur)"
                )
            baglilar.append(
                f"Cari tahsilat etkisi: {_fmt(pv.brut_tutar)} TL "
                f"({cari.cari_kodu if cari else '—'})"
            )
            baglilar.append(
                f"POS alacağı / komisyon: net {_fmt(pv.net_tutar)} · "
                f"komisyon {_fmt(pv.komisyon_tutari)}"
            )
            if pv.cari_id and pv.belge_no:
                sh = session.scalar(
                    select(SatisHareketi).where(
                        SatisHareketi.belge_no == pv.belge_no,
                        SatisHareketi.cari_id == int(pv.cari_id),
                    )
                )
                if sh is not None:
                    baglilar.append(
                        f"Bağlı satış faturası {pv.belge_no} kalır; "
                        "tahsilat etkisi kaldırılır, kalan borç yeniden açılır"
                    )
            return {
                "id": int(pv.id),
                "belge_no": pv.belge_no,
                "tarih": pv.tahsilat_tarihi,
                "cari": f"{cari.cari_kodu} — {cari.unvan}" if cari else "—",
                "brut": Decimal(str(pv.brut_tutar or 0)),
                "komisyon": Decimal(str(pv.komisyon_tutari or 0)),
                "net": Decimal(str(pv.net_tutar or 0)),
                "pos_hesap": (pos_hesap.hesap_adi if pos_hesap else "") or "—",
                "hedef_hesap": (hedef.hesap_adi if hedef else "") or "—",
                "makbuz_bagli": makbuz_satir is not None,
                "baglilar": baglilar,
            }

    @staticmethod
    def pos_valor_bekleyenler(banka_karti_id=None, pos_hesap_id=None):
        with get_session() as session:
            q = (
                select(PosValorKaydi)
                .where(PosValorKaydi.durum == "BEKLIYOR")
                .order_by(PosValorKaydi.valor_tarihi, PosValorKaydi.id)
            )
            if banka_karti_id:
                q = q.where(PosValorKaydi.banka_karti_id == int(banka_karti_id))
            if pos_hesap_id:
                q = q.where(PosValorKaydi.pos_hesap_id == int(pos_hesap_id))
            return list(session.scalars(q).all())

    @staticmethod
    def _pos_kayit_acik_mi(k: PosValorKaydi, kesim: date | None) -> bool:
        durum = (k.durum or "").strip().upper()
        if durum in {"IPTAL", "İPTAL", "PASIF", "GECMIS_KAPANDI"}:
            return False
        yatis = getattr(k, "gercek_yatis_tarihi", None)
        if kesim is None:
            if durum in ("BEKLIYOR", "KISMEN"):
                return True
            return durum == "AKTARILDI" and yatis is None
        if k.tahsilat_tarihi and k.tahsilat_tarihi > kesim:
            return False
        if durum in ("BEKLIYOR", "KISMEN"):
            return True
        return durum == "AKTARILDI" and (yatis is None or yatis > kesim)

    @staticmethod
    def _pos_kalan_paylar(
        k: PosValorKaydi, kesim: date | None
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Kısmi gerçek yatışta yalnızca kalan brüt/komisyon/net."""
        brut0 = Decimal(str(k.brut_tutar or 0))
        kom0 = Decimal(str(k.komisyon_tutari or 0))
        net0 = Decimal(str(k.net_tutar or 0))
        durum = (k.durum or "").strip().upper()
        yatis_tut = getattr(k, "gercek_yatis_tutari", None)
        if (
            kesim is None
            and durum in ("BEKLIYOR", "KISMEN")
            and yatis_tut is not None
            and net0 > 0
        ):
            yatis_d = Decimal(str(yatis_tut))
            if yatis_d <= 0:
                return brut0, kom0, net0
            if yatis_d >= net0:
                return Decimal("0"), Decimal("0"), Decimal("0")
            oran = (net0 - yatis_d) / net0
            return (
                (brut0 * oran).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                (kom0 * oran).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                (net0 - yatis_d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
        return brut0, kom0, net0

    @staticmethod
    def _pos_ozet_topla(kayitlar, *, kesim: date | None = None) -> dict:
        brut = Decimal("0")
        komisyon = Decimal("0")
        net = Decimal("0")
        acik_kalan: list[PosValorKaydi] = []
        for k in kayitlar:
            if not FinansService._pos_kayit_acik_mi(k, kesim):
                continue
            b, ko, n = FinansService._pos_kalan_paylar(k, kesim)
            if n <= 0 and b <= 0:
                continue
            acik_kalan.append(k)
            brut += b
            komisyon += ko
            net += n
        return {
            "adet": len(acik_kalan),
            "brut": brut.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "komisyon": komisyon.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "net": net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "kayitlar": acik_kalan,
            "kesim": kesim,
        }

    @staticmethod
    def pos_aktif_alacak_haritalari(*, kesim: date | None = None) -> dict:
        """Tek sorguda POS açık alacakları — banka kartı ve POS hesabı bazında.

        Dönüş: ``by_banka``, ``by_pos_hesap``, ``toplam`` (her biri ozet dict).
        Bankalar listesi / ana panel likit için N+1'i önler.
        """
        with get_session() as session:
            kayitlar = list(session.scalars(select(PosValorKaydi)).all())
        by_banka_raw: dict[int, list] = {}
        by_pos_raw: dict[int, list] = {}
        for k in kayitlar:
            if k.banka_karti_id is not None:
                by_banka_raw.setdefault(int(k.banka_karti_id), []).append(k)
            if k.pos_hesap_id is not None:
                by_pos_raw.setdefault(int(k.pos_hesap_id), []).append(k)
        return {
            "by_banka": {
                bid: FinansService._pos_ozet_topla(ks, kesim=kesim)
                for bid, ks in by_banka_raw.items()
            },
            "by_pos_hesap": {
                hid: FinansService._pos_ozet_topla(ks, kesim=kesim)
                for hid, ks in by_pos_raw.items()
            },
            "toplam": FinansService._pos_ozet_topla(kayitlar, kesim=kesim),
        }

    @staticmethod
    def pos_aktif_alacak_ozeti(
        *,
        banka_karti_id=None,
        pos_hesap_id=None,
        kesim: date | None = None,
    ) -> dict:
        """Aktif / kesim günü POS alacağı — PosValorKaydi açık kalanları.

        Ledger ``FinansService.bakiye(POS)`` ile karıştırılmaz.
        ``AKTARILDI`` yalnız ``gercek_yatis_tarihi`` doluysa tahsil edilmiş sayılır;
        valör / iş günü varsayımı veya boş yatış tarihi kapanış kanıtı değildir.
        PosValor yokluğu tek başına tahsil edilmiş anlamına gelmez (ayrı envanter).

        kesim=None → bugün: BEKLIYOR, veya AKTARILDI ama yatış tarihi yok / kısmi kalan.
        kesim verilirse: tahsilat ≤ kesim ve (BEKLIYOR veya yatış yok/kesimden sonra).
        """
        with get_session() as session:
            q = select(PosValorKaydi)
            if banka_karti_id is not None:
                q = q.where(PosValorKaydi.banka_karti_id == int(banka_karti_id))
            if pos_hesap_id is not None:
                q = q.where(PosValorKaydi.pos_hesap_id == int(pos_hesap_id))
            kayitlar = list(session.scalars(q).all())
        return FinansService._pos_ozet_topla(kayitlar, kesim=kesim)

    @staticmethod
    def _pos_hedef_hesap(kart) -> FinansHesabi | None:
        """Kartın varsayılan aktarım hesabı: önce pos_aktarim_hesap_id, yoksa tür yedeği."""
        alts = list(kart.alt_hesaplar or [])
        hid = getattr(kart, "pos_aktarim_hesap_id", None)
        if hid:
            hedef = next(
                (
                    h
                    for h in alts
                    if int(h.id) == int(hid)
                    and (h.alt_hesap_turu or "").upper() in POS_HEDEF_HESAP_TURLERI
                ),
                None,
            )
            if hedef is not None:
                return hedef
        tur = (getattr(kart, "pos_hedef_hesap_turu", None) or "MEVDUAT").strip().upper()
        if tur not in POS_HEDEF_HESAP_TURLERI:
            tur = "MEVDUAT"
        hedef = next(
            (h for h in alts if (h.alt_hesap_turu or "").upper() == tur),
            None,
        )
        if hedef:
            return hedef
        yedek = "KMH" if tur == "MEVDUAT" else "MEVDUAT"
        return next(
            (h for h in alts if (h.alt_hesap_turu or "").upper() == yedek),
            None,
        )

    @staticmethod
    def pos_aktarim_hedefleri(banka_karti_id) -> list[dict]:
        """Kartın seçilebilir aktarım hesapları (MEVDUAT + KMH)."""
        kart = FinansService.banka_karti_getir(int(banka_karti_id))
        if not kart:
            return []
        sonuc = []
        for h in kart.alt_hesaplar or []:
            tur = (h.alt_hesap_turu or "").upper()
            if tur not in POS_HEDEF_HESAP_TURLERI:
                continue
            if getattr(h, "aktif", True) is False:
                continue
            sonuc.append(
                {
                    "id": int(h.id),
                    "hesap_adi": h.hesap_adi,
                    "alt_hesap_turu": tur,
                    "etiket": f"{h.hesap_adi} ({tur})",
                }
            )
        return sonuc

    @staticmethod
    def pos_valor_ozet_metni(kart) -> str:
        """UI etiketleri için kısa POS valör özeti."""
        gun = int(getattr(kart, "pos_valor_gun", 1) or 1)
        is_g = getattr(kart, "pos_valor_is_gunu", True)
        if is_g is None:
            is_g = True
        tip = "iş günü" if is_g else "takvim günü"
        hedef = FinansService._pos_hedef_hesap(kart)
        if hedef is not None:
            tur = (hedef.alt_hesap_turu or "").upper()
            hedef_etiket = f"{hedef.hesap_adi} ({'Mevduat' if tur == 'MEVDUAT' else 'KMH'})"
        else:
            tur = (getattr(kart, "pos_hedef_hesap_turu", None) or "MEVDUAT").upper()
            hedef_etiket = "Mevduat" if tur == "MEVDUAT" else "KMH"
        oto = bool(getattr(kart, "pos_otomatik_mahsup", False))
        mahsup = "otomatik mahsup açık" if oto else "manuel mahsup"
        return f"Valör {gun} {tip} → {hedef_etiket} · {mahsup}"

    @staticmethod
    def pos_valor_vadesi_geldi_mi(kayit, simdi: datetime | None = None) -> bool:
        """Beklenen valör tarihi gelmiş mi (saat şartı yok; iş günü tarihe gömülü)."""
        simdi = simdi or datetime.now()
        return simdi.date() >= kayit.valor_tarihi

    @staticmethod
    def pos_aktarim_kalan_net(kayit) -> Decimal:
        durum = (getattr(kayit, "durum", None) or "").strip().upper()
        if durum in ("IPTAL", "İPTAL", "GECMIS_KAPANDI"):
            return Decimal("0")
        net = Decimal(str(getattr(kayit, "net_tutar", 0) or 0))
        akt = Decimal(str(getattr(kayit, "gercek_yatis_tutari", 0) or 0))
        kalan = net - akt
        return kalan if kalan > 0 else Decimal("0")

    @staticmethod
    def pos_aktarim_durum_bilgisi(kayit, *, bugun: date | None = None) -> dict:
        """Liste/rapor için durum: Bekliyor / Kısmen Aktarıldı / Bankaya Aktarıldı (+ Valörü geldi/Gecikti)."""
        bugun = bugun or date.today()
        durum_ham = (getattr(kayit, "durum", None) or "BEKLIYOR").strip().upper()
        if durum_ham in ("IPTAL", "İPTAL"):
            return {
                "durum_kod": "IPTAL",
                "durum": "İptal",
                "ek_isaret": "",
                "aktarilan_net": Decimal("0"),
                "kalan_net": Decimal("0"),
            }
        if durum_ham == "GECMIS_KAPANDI":
            net0 = Decimal(str(getattr(kayit, "net_tutar", 0) or 0))
            return {
                "durum_kod": "GECMIS_KAPANDI",
                "durum": "Geçmişte bankaya geçmiş",
                "ek_isaret": (getattr(kayit, "kapanis_turu", None) or "")[:40],
                "aktarilan_net": net0.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                "kalan_net": Decimal("0"),
            }
        net = Decimal(str(getattr(kayit, "net_tutar", 0) or 0))
        akt = Decimal(str(getattr(kayit, "gercek_yatis_tutari", 0) or 0))
        if akt < 0:
            akt = Decimal("0")
        if akt > net:
            akt = net
        kalan = net - akt
        yatis = getattr(kayit, "gercek_yatis_tarihi", None)
        if kalan <= Decimal("0.005") and (yatis is not None or akt > 0 or durum_ham == "AKTARILDI"):
            kod, etiket = "AKTARILDI", "Bankaya Aktarıldı"
        elif akt > Decimal("0.005"):
            kod, etiket = "KISMEN", "Kısmen Aktarıldı"
        else:
            kod, etiket = "BEKLIYOR", "Bekliyor"
        ek = ""
        valor = getattr(kayit, "valor_tarihi", None)
        if kod in ("BEKLIYOR", "KISMEN") and isinstance(valor, date):
            if valor < bugun:
                ek = "Gecikti"
            elif valor == bugun:
                ek = "Valörü geldi"
        return {
            "durum_kod": kod,
            "durum": etiket,
            "ek_isaret": ek,
            "aktarilan_net": akt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "kalan_net": max(kalan, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }

    @staticmethod
    def pos_valor_aktar(
        kayit_id,
        *,
        tutar=None,
        aktarim_tarihi=None,
        hedef_hesap_id=None,
        aktarim_belge_no=None,
        aktarim_yontemi="MANUEL",
        banka_teyidi=None,
    ) -> dict:
        """POS net bakiyesini (veya kısmi tutarı) hedef hesaba aktarır; gerçek yatış alanlarını yazar."""
        return FinansService.pos_bankaya_aktar(
            [int(kayit_id)],
            tutarlar={int(kayit_id): tutar} if tutar is not None else None,
            aktarim_tarihi=aktarim_tarihi,
            hedef_hesap_id=hedef_hesap_id,
            aktarim_belge_no=aktarim_belge_no,
            valor_kontrol=True,
            aktarim_yontemi=aktarim_yontemi,
            banka_teyidi=banka_teyidi,
        )[0]

    @staticmethod
    def pos_bankaya_aktar(
        kayit_idler,
        *,
        tutarlar: dict | None = None,
        aktarim_tarihi: date | None = None,
        hedef_hesap_id=None,
        aktarim_belge_no: str | None = None,
        valor_kontrol: bool = False,
        aktarim_yontemi: str = "MANUEL",
        banka_teyidi: bool | None = None,
    ) -> list[dict]:
        """Tekli/toplu/kısmi banka aktarımı. Müşteri tahsilatı yeniden yazılmaz.

        Aynı POS+hedef grubu tek PVA belgesiyle bağlanır. Farklı POS/hedef karıştırılmaz.
        Aktarım fişi (manuel/otomatik) banka_teyidi işaretlemez — gerçek ekstre teyidi ayrıdır.
        """
        yazma_zorunlu("finans_duzenleme")
        yontem = str(aktarim_yontemi or "MANUEL").strip().upper()
        if yontem in ("OTO", "AUTO", "OTOMATİK", "OTOMATIK"):
            yontem = "OTOMATIK"
        else:
            yontem = "MANUEL"
        # Uygulama aktarımı ≠ ekstre teyidi; yalnız açık True verilirse işaretlenir
        if banka_teyidi is None:
            banka_teyidi = False
        idler = [int(i) for i in (kayit_idler or [])]
        if not idler:
            raise ValueError("Aktarılacak POS işlemi seçin.")
        tarih = aktarim_tarihi or date.today()
        if tarih > date.today():
            raise ValueError("Aktarım tarihi gelecek olamaz.")
        sonuclar: list[dict] = []
        with get_session() as session:
            # Tek transaction: eşzamanlı ikinci aktarım kalanı aşamaz
            kayitlar = list(
                session.scalars(
                    select(PosValorKaydi)
                    .where(PosValorKaydi.id.in_(idler))
                    .execution_options(populate_existing=True)
                ).all()
            )
            if len(kayitlar) != len(set(idler)):
                raise ValueError("Bazı POS kayıtları bulunamadı.")
            by_id = {int(k.id): k for k in kayitlar}
            # Grup: (pos_hesap_id, hedef_id)
            gruplar: dict[tuple[int, int], list] = {}
            for kid in idler:
                k = by_id[kid]
                session.refresh(k)
                durum = (k.durum or "").upper()
                if durum in ("IPTAL", "İPTAL"):
                    raise ValueError(f"{k.belge_no}: iptal edilmiş işlem aktarılamaz.")
                if durum == "GECMIS_KAPANDI":
                    raise ValueError(
                        f"{k.belge_no}: geçmişte bankaya geçmiş kapanış — "
                        "yeniden Bankaya Aktar yapılamaz (mükerrer banka girişi önlenir)."
                    )
                if valor_kontrol and not FinansService.pos_valor_vadesi_geldi_mi(k):
                    raise ValueError(
                        f"{k.belge_no}: valör henüz gelmedi ({k.valor_tarihi.strftime('%d.%m.%Y')})."
                    )
                kalan = FinansService.pos_aktarim_kalan_net(k)
                if kalan <= 0:
                    raise ValueError(f"{k.belge_no}: aktarılacak net tutar kalmadı (mükerrer/kapalı).")
                istenen = None
                if tutarlar and kid in tutarlar and tutarlar[kid] is not None:
                    istenen = _decimal(tutarlar[kid], "Aktarım tutarı", Decimal("0.01"))
                    if istenen <= 0:
                        raise ValueError("Aktarım tutarı pozitif olmalıdır.")
                    if istenen > kalan + Decimal("0.005"):
                        raise ValueError(
                            f"{k.belge_no}: aktarım tutarı kalan neti ({kalan}) aşamaz."
                        )
                else:
                    istenen = kalan
                hedef_id = int(
                    hedef_hesap_id
                    or getattr(k, "hedef_hesap_id", None)
                    or k.kmh_hesap_id
                )
                anahtar = (int(k.pos_hesap_id), hedef_id)
                gruplar.setdefault(anahtar, []).append((k, istenen, hedef_id))

            for (pos_id, hedef_id), paket in gruplar.items():
                belge = (aktarim_belge_no or "").strip() or FinansService._finans_belge_no(
                    session, "PVA"
                )
                # Aynı belgede birden fazla grup olmasın
                if len(gruplar) > 1:
                    belge = FinansService._finans_belge_no(session, "PVA")
                toplam_net = sum((t for _k, t, _h in paket), Decimal("0"))
                acik = f"POS banka aktarımı ({len(paket)} işlem)"
                session.add(
                    FinansHareketi(
                        hesap_id=pos_id,
                        tarih=tarih,
                        hareket_turu="POS VALÖR AKTARIM (POS)",
                        belge_no=belge,
                        tutar=toplam_net,
                        aciklama=acik,
                    )
                )
                session.add(
                    FinansHareketi(
                        hesap_id=hedef_id,
                        tarih=tarih,
                        hareket_turu="POS VALÖR AKTARIM (HEDEF)",
                        belge_no=belge,
                        tutar=toplam_net,
                        aciklama=acik,
                    )
                )
                for k, pay, hid in paket:
                    session.refresh(k)
                    onceki = Decimal(str(k.gercek_yatis_tutari or 0))
                    kalan_simdi = FinansService.pos_aktarim_kalan_net(k)
                    if pay > kalan_simdi + Decimal("0.005"):
                        raise ValueError(
                            f"{k.belge_no}: eşzamanlı aktarım — kalan net yetersiz ({kalan_simdi})."
                        )
                    yeni = (onceki + pay).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    net = Decimal(str(k.net_tutar or 0))
                    k.gercek_yatis_tutari = yeni
                    k.gercek_yatis_tarihi = tarih
                    k.hedef_hesap_id = hid
                    k.kmh_hesap_id = hid
                    onceki_belge = (getattr(k, "aktarim_belge_no", None) or "").strip()
                    k.aktarim_belge_no = (
                        f"{onceki_belge},{belge}" if onceki_belge and onceki_belge != belge else belge
                    )
                    k.aktarim_zamani = datetime.now()
                    k.aktarim_yontemi = yontem
                    if banka_teyidi:
                        k.banka_teyidi = True
                    elif getattr(k, "banka_teyidi", None) is None:
                        k.banka_teyidi = False
                    if yeni + Decimal("0.005") >= net:
                        k.durum = "AKTARILDI"
                    else:
                        k.durum = "KISMEN"
                    # Manuel/zorla aktarım: geri alma engelini kaldır
                    if hasattr(k, "otomatik_aktarim_engel"):
                        k.otomatik_aktarim_engel = False
                    session.flush()
                    from database.muhasebe_entegrasyon import muhasebe_hook

                    muhasebe_hook("pos_valor_aktarimi_fisi", int(k.id), session=session)
                    try:
                        from database.pos_komisyon_gider_service import PosKomisyonGiderService

                        # Aktarım komisyon gideri üretmez; mevcut tahmini gideri kesinleştirir
                        PosKomisyonGiderService.senkronize(session, k, kesin=True)
                    except Exception:
                        pass
                    # Tam kapanışta beklenen net ile gerçekleşen farkı bildir
                    fark = Decimal("0")
                    if k.durum == "AKTARILDI":
                        fark = (yeni - net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    sonuclar.append(
                        {
                            "kayit_id": int(k.id),
                            "belge_no": k.belge_no,
                            "aktarim_belge_no": belge,
                            "net": pay,
                            "aktarilan_toplam": yeni,
                            "kalan": FinansService.pos_aktarim_kalan_net(k),
                            "durum": k.durum,
                            "aktarildi": True,
                            "hedef_hesap_id": hid,
                            "fark_uyari": bool(abs(fark) > Decimal("0.005")),
                            "fark": fark,
                        }
                    )
        return sonuclar

    @staticmethod
    def _pos_pva_tokenleri(kayit) -> list[str]:
        return [
            t.strip()
            for t in (getattr(kayit, "aktarim_belge_no", None) or "").split(",")
            if t.strip()
        ]

    @staticmethod
    def _pos_pva_hareketleri(session, pva_belge: str) -> list[FinansHareketi]:
        return list(
            session.scalars(
                select(FinansHareketi).where(FinansHareketi.belge_no == (pva_belge or "").strip())
            ).all()
        )

    @staticmethod
    def _pos_pva_kayit_payi(session, kayit: PosValorKaydi, pva_belge: str) -> Decimal:
        """Bu POS kaydının ortak/tekil PVA içindeki net payı."""
        belge = (pva_belge or "").strip()
        bagli = FinansService._pos_pva_bagli_kayitlar(session, belge)
        hareketler = FinansService._pos_pva_hareketleri(session, belge)
        hedef_h = next(
            (
                h
                for h in hareketler
                if "HEDEF" in (h.hareket_turu or "").upper()
                or (h.hareket_turu or "").upper().endswith("(KMH)")
            ),
            None,
        )
        fh_tutar = Decimal(str(hedef_h.tutar or 0)) if hedef_h else Decimal("0")
        if not bagli:
            return Decimal("0")
        if len(bagli) == 1 and int(bagli[0].id) == int(kayit.id):
            return fh_tutar.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Tek PVA token'lı diğer kayıtların payı = kendi gercek_yatis
        diger = Decimal("0")
        for b in bagli:
            if int(b.id) == int(kayit.id):
                continue
            tokenler = FinansService._pos_pva_tokenleri(b)
            if tokenler == [belge]:
                diger += Decimal(str(b.gercek_yatis_tutari or 0))
        pay = fh_tutar - diger
        if pay < 0:
            pay = Decimal("0")
        # Bu kayıtta tek token ise gercek_yatis ile sınırla
        kendi_token = FinansService._pos_pva_tokenleri(kayit)
        if kendi_token == [belge]:
            pay = min(pay, Decimal(str(kayit.gercek_yatis_tutari or 0)))
        return pay.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _pos_hedef_hesap_dogrula(session, kart: BankaKarti, hedef_hesap_id) -> FinansHesabi:
        hid = int(hedef_hesap_id)
        hedef = session.scalar(
            select(FinansHesabi)
            .where(FinansHesabi.id == hid)
            .options(selectinload(FinansHesabi.hareketler))
        )
        if hedef is None or int(hedef.banka_karti_id or 0) != int(kart.id):
            raise ValueError("Hedef hesap bu banka kartına ait değil.")
        tur = (hedef.alt_hesap_turu or "").upper()
        if tur not in POS_HEDEF_HESAP_TURLERI:
            raise ValueError("Hedef hesap mevduat veya KMH olmalıdır.")
        return hedef

    @staticmethod
    def _pos_pva_hedef_pay_tasi(
        session,
        *,
        pva_belge: str,
        eski_hedef_id: int,
        yeni_hedef_id: int,
        pay: Decimal,
        aciklama: str,
    ) -> None:
        """Ortak/tekil PVA'da hedef hesaptaki payı eski → yeni taşır; POS satırına dokunmaz."""
        if pay <= 0 or int(eski_hedef_id) == int(yeni_hedef_id):
            return
        hareketler = FinansService._pos_pva_hareketleri(session, pva_belge)
        eski_h = next(
            (
                h
                for h in hareketler
                if int(h.hesap_id) == int(eski_hedef_id)
                and (
                    "HEDEF" in (h.hareket_turu or "").upper()
                    or "AKTARIM" in (h.hareket_turu or "").upper()
                )
            ),
            None,
        )
        if eski_h is None:
            # Tür etiketi farklıysa hesap_id ile dene
            eski_h = next((h for h in hareketler if int(h.hesap_id) == int(eski_hedef_id)), None)
        if eski_h is None:
            raise ValueError(f"{pva_belge}: eski hedef hareket bulunamadı.")
        eski_tutar = Decimal(str(eski_h.tutar or 0))
        if pay > eski_tutar + Decimal("0.005"):
            raise ValueError(f"{pva_belge}: taşınacak pay ({pay}) fiş tutarını ({eski_tutar}) aşıyor.")
        kalan = (eski_tutar - pay).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if kalan <= Decimal("0.005"):
            session.delete(eski_h)
        else:
            eski_h.tutar = kalan
        yeni_h = next(
            (
                h
                for h in hareketler
                if int(h.hesap_id) == int(yeni_hedef_id)
                and h.id != getattr(eski_h, "id", None)
            ),
            None,
        )
        if yeni_h is not None:
            yeni_h.tutar = (Decimal(str(yeni_h.tutar or 0)) + pay).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if aciklama and aciklama not in (yeni_h.aciklama or ""):
                yeni_h.aciklama = f"{(yeni_h.aciklama or '').strip()} | {aciklama}".strip(" |")
        else:
            session.add(
                FinansHareketi(
                    hesap_id=int(yeni_hedef_id),
                    tarih=eski_h.tarih,
                    hareket_turu="POS VALÖR AKTARIM (HEDEF)",
                    belge_no=pva_belge,
                    tutar=pay,
                    aciklama=aciklama or (eski_h.aciklama or "POS banka aktarımı (hedef düzeltme)"),
                )
            )
        session.flush()

    @staticmethod
    def _pos_pva_pay_geri_al(
        session,
        *,
        pva_belge: str,
        pos_hesap_id: int,
        hedef_hesap_id: int,
        pay: Decimal,
    ) -> None:
        """Tek kaydın PVA payını POS ve hedef satırlarından düşürür; sıfırsa fişi siler."""
        if pay <= 0:
            return
        hareketler = FinansService._pos_pva_hareketleri(session, pva_belge)
        if not hareketler:
            return

        def _dus(h: FinansHareketi | None) -> None:
            if h is None:
                return
            kalan = (Decimal(str(h.tutar or 0)) - pay).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if kalan <= Decimal("0.005"):
                session.delete(h)
            else:
                h.tutar = kalan

        pos_h = next(
            (
                h
                for h in hareketler
                if int(h.hesap_id) == int(pos_hesap_id)
                and ("(POS)" in (h.hareket_turu or "").upper() or "POS" in (h.hareket_turu or "").upper())
            ),
            None,
        )
        if pos_h is None:
            pos_h = next((h for h in hareketler if int(h.hesap_id) == int(pos_hesap_id)), None)
        hedef_h = next(
            (h for h in hareketler if int(h.hesap_id) == int(hedef_hesap_id)),
            None,
        )
        _dus(pos_h)
        _dus(hedef_h)
        session.flush()
        # Başka satır kalmadıysa temizle
        kalan_h = FinansService._pos_pva_hareketleri(session, pva_belge)
        if not kalan_h:
            return
        # Yalnız sıfır tutarlı artık varsa sil
        for h in list(kalan_h):
            if Decimal(str(h.tutar or 0)) <= Decimal("0.005"):
                session.delete(h)
        session.flush()

    @staticmethod
    def pos_aktarim_hedef_duzelt(
        kayit_id,
        yeni_hedef_hesap_id,
        *,
        gerekce: str | None = None,
    ) -> dict:
        """Aktarılmış POS işleminin hedef hesabını taşır; açık alacağa dönüştürmez.

        Brüt/komisyon/net ve durum korunur. Ortak PVA'da yalnız bu kaydın payı taşınır.
        Idempotent: hedef zaten doğruysa değişiklik yok.
        """
        yazma_zorunlu("finans_duzenleme")
        with get_session() as session:
            kayit = session.scalar(
                select(PosValorKaydi)
                .where(PosValorKaydi.id == int(kayit_id))
                .execution_options(populate_existing=True)
            )
            if kayit is None:
                raise ValueError("POS işlemi bulunamadı.")
            durum = (kayit.durum or "").upper()
            if durum in ("IPTAL", "İPTAL", "GECMIS_KAPANDI"):
                raise ValueError("İptal veya geçmiş kapanış kaydının hedefi değiştirilemez.")
            akt = Decimal(str(kayit.gercek_yatis_tutari or 0))
            if akt <= 0 or not FinansService._pos_pva_tokenleri(kayit):
                raise ValueError("Aktarılmamış işlemde hedef düzeltmesi yapılamaz.")
            eski_id = int(getattr(kayit, "hedef_hesap_id", None) or kayit.kmh_hesap_id)
            yeni_id = int(yeni_hedef_hesap_id)
            if eski_id == yeni_id:
                return {
                    "kayit_id": int(kayit.id),
                    "belge_no": kayit.belge_no,
                    "degisti": False,
                    "eski_hedef_hesap_id": eski_id,
                    "yeni_hedef_hesap_id": yeni_id,
                    "tutar": akt,
                    "durum": kayit.durum,
                }
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(kayit.banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if kart is None:
                raise ValueError("Banka kartı bulunamadı.")
            FinansService._pos_hedef_hesap_dogrula(session, kart, yeni_id)
            gerek = (gerekce or "Aktarım hesabı düzeltildi").strip()[:200]
            tasinan = Decimal("0")
            for pva in FinansService._pos_pva_tokenleri(kayit):
                pay = FinansService._pos_pva_kayit_payi(session, kayit, pva)
                if pay <= 0:
                    continue
                FinansService._pos_pva_hedef_pay_tasi(
                    session,
                    pva_belge=pva,
                    eski_hedef_id=eski_id,
                    yeni_hedef_id=yeni_id,
                    pay=pay,
                    aciklama=gerek,
                )
                tasinan += pay
            if tasinan <= 0:
                raise ValueError("Taşınacak aktarım payı bulunamadı.")
            eski_snap = {"hedef_hesap_id": eski_id, "gerekce": None}
            kayit.hedef_hesap_id = yeni_id
            kayit.kmh_hesap_id = yeni_id
            # Durum / tutarlar aynı kalır
            FinansService._pos_degisiklik_kaydet(
                session,
                kayit,
                eski_snap,
                {
                    "hedef_hesap_id": yeni_id,
                    "gerekce": gerek,
                    "islem": "aktarim_hedef_duzelt",
                    "tutar": tasinan,
                },
            )
            session.flush()
            return {
                "kayit_id": int(kayit.id),
                "belge_no": kayit.belge_no,
                "degisti": True,
                "eski_hedef_hesap_id": eski_id,
                "yeni_hedef_hesap_id": yeni_id,
                "tutar": tasinan,
                "aktarim_belge_no": kayit.aktarim_belge_no,
                "durum": kayit.durum,
                "brut": Decimal(str(kayit.brut_tutar or 0)),
                "komisyon": Decimal(str(kayit.komisyon_tutari or 0)),
                "net": Decimal(str(kayit.net_tutar or 0)),
            }

    @staticmethod
    def pos_aktarim_geri_al(kayit_id, *, gerekce: str | None = None) -> dict:
        """Seçilen aktarımın banka etkisini geri alır; POS alacağını yeniden aktarılabilir yapar.

        Müşteri tahsilatı / cari hareketi iptal edilmez. Otomatik döngü yeniden aktarmaz
        (otomatik_aktarim_engel); kullanıcı Bankaya Aktar ile açıkça başlatır.
        """
        yazma_zorunlu("finans_duzenleme")
        with get_session() as session:
            kayit = session.scalar(
                select(PosValorKaydi)
                .where(PosValorKaydi.id == int(kayit_id))
                .execution_options(populate_existing=True)
            )
            if kayit is None:
                raise ValueError("POS işlemi bulunamadı.")
            durum = (kayit.durum or "").upper()
            if durum in ("IPTAL", "İPTAL", "GECMIS_KAPANDI"):
                raise ValueError("İptal veya geçmiş kapanış aktarımı geri alınamaz.")
            akt = Decimal(str(kayit.gercek_yatis_tutari or 0))
            tokenler = FinansService._pos_pva_tokenleri(kayit)
            if akt <= 0 or not tokenler:
                raise ValueError("Geri alınacak banka aktarımı yok.")
            hedef_id = int(getattr(kayit, "hedef_hesap_id", None) or kayit.kmh_hesap_id)
            pos_id = int(kayit.pos_hesap_id)
            gerek = (gerekce or "Aktarım geri alındı").strip()[:200]
            geri = Decimal("0")
            for pva in tokenler:
                pay = FinansService._pos_pva_kayit_payi(session, kayit, pva)
                if pay <= 0:
                    continue
                FinansService._pos_pva_pay_geri_al(
                    session,
                    pva_belge=pva,
                    pos_hesap_id=pos_id,
                    hedef_hesap_id=hedef_id,
                    pay=pay,
                )
                geri += pay
            if geri <= 0:
                raise ValueError("Geri alınacak pay hesaplanamadı.")
            eski_snap = {
                "gercek_yatis_tutari": akt,
                "durum": kayit.durum,
                "aktarim_belge_no": kayit.aktarim_belge_no,
                "hedef_hesap_id": hedef_id,
            }
            kayit.gercek_yatis_tutari = Decimal("0")
            kayit.gercek_yatis_tarihi = None
            kayit.aktarim_belge_no = None
            kayit.aktarim_zamani = None
            kayit.durum = "BEKLIYOR"
            kayit.otomatik_aktarim_engel = True
            # Banka teyidi aktarıma bağlıydı; alacak yeniden açık → teyit düşer
            kayit.banka_teyidi = False
            kayit.banka_teyidi_tarihi = None
            kayit.banka_teyidi_notu = None
            kayit.banka_teyidi_kullanici = None
            FinansService._pos_degisiklik_kaydet(
                session,
                kayit,
                eski_snap,
                {
                    "gercek_yatis_tutari": Decimal("0"),
                    "durum": "BEKLIYOR",
                    "aktarim_belge_no": None,
                    "hedef_hesap_id": hedef_id,
                    "gerekce": gerek,
                    "islem": "aktarim_geri_al",
                    "tutar": geri,
                    "otomatik_aktarim_engel": True,
                },
            )
            session.flush()
            try:
                from database.pos_komisyon_gider_service import PosKomisyonGiderService

                PosKomisyonGiderService.senkronize(session, kayit, kesin=False)
            except Exception:
                pass
            return {
                "kayit_id": int(kayit.id),
                "belge_no": kayit.belge_no,
                "geri_alinan": geri,
                "hedef_hesap_id": hedef_id,
                "durum": kayit.durum,
                "otomatik_aktarim_engel": True,
            }

    @staticmethod
    def pos_banka_teyidi_ayarla(
        kayit_idler,
        *,
        teyit: bool = True,
        teyit_tarihi: date | None = None,
        notu: str | None = None,
    ) -> list[dict]:
        """Gerçek banka ekstre teyidi — otomatik/manuel aktarım kaydından ayrıdır.

        Teyit, PVA oluştuğu anlamına gelmez; aktarım yokken teyit verilemez.
        """
        yazma_zorunlu("finans_duzenleme")
        idler = [int(i) for i in (kayit_idler or [])]
        if not idler:
            raise ValueError("Teyit için POS işlemi seçin.")
        gun = teyit_tarihi or date.today()
        if gun > date.today():
            raise ValueError("Teyit tarihi gelecek olamaz.")
        not_metin = " ".join((notu or "").split())[:500] or None
        kullanici = None
        try:
            from database.session_manager import oturum

            kullanici = oturum.kullanici_adi or oturum.current_username()
        except Exception:
            pass
        sonuclar: list[dict] = []
        with get_session() as session:
            FinansService._pos_teyit_kolonlari_ensure()
            kayitlar = list(
                session.scalars(select(PosValorKaydi).where(PosValorKaydi.id.in_(idler))).all()
            )
            if len(kayitlar) != len(set(idler)):
                raise ValueError("Bazı POS kayıtları bulunamadı.")
            for k in kayitlar:
                if not (getattr(k, "aktarim_belge_no", None) or "").strip() and not (
                    getattr(k, "gercek_yatis_tarihi", None)
                ):
                    raise ValueError(
                        f"{k.belge_no}: önce banka aktarım fişi (PVA) oluşmalı; "
                        "teyit aktarımdan ayrıdır."
                    )
                eski = bool(getattr(k, "banka_teyidi", False))
                if teyit:
                    k.banka_teyidi = True
                    k.banka_teyidi_tarihi = gun
                    k.banka_teyidi_notu = not_metin
                    k.banka_teyidi_kullanici = (str(kullanici)[:120] if kullanici else None)
                else:
                    k.banka_teyidi = False
                    k.banka_teyidi_tarihi = None
                    k.banka_teyidi_notu = not_metin
                    k.banka_teyidi_kullanici = (str(kullanici)[:120] if kullanici else None)
                session.flush()
                FinansService._pos_degisiklik_kaydet(
                    session,
                    k,
                    {"banka_teyidi": str(eski)},
                    {
                        "banka_teyidi": str(bool(k.banka_teyidi)),
                        "banka_teyidi_tarihi": str(k.banka_teyidi_tarihi or ""),
                        "banka_teyidi_notu": k.banka_teyidi_notu or "",
                    },
                )
                sonuclar.append(
                    {
                        "kayit_id": int(k.id),
                        "belge_no": k.belge_no,
                        "banka_teyidi": bool(k.banka_teyidi),
                        "banka_teyidi_tarihi": k.banka_teyidi_tarihi,
                        "banka_teyidi_notu": k.banka_teyidi_notu or "",
                        "banka_teyidi_kullanici": k.banka_teyidi_kullanici or "",
                        "aktarim_yontemi": getattr(k, "aktarim_yontemi", None) or "",
                        "aktarim_belge_no": getattr(k, "aktarim_belge_no", None) or "",
                    }
                )
        return sonuclar

    @staticmethod
    def _pos_teyit_kolonlari_ensure() -> None:
        """Eksik teyit / geçmiş kapanış kolonlarını ekler (eski firma DB)."""
        from sqlalchemy import inspect, text

        from database.database import engine

        if engine is None:
            return
        insp = inspect(engine)
        if not insp.has_table("pos_valor_kayitlari"):
            return
        mevcut = {s["name"] for s in insp.get_columns("pos_valor_kayitlari")}
        eklenecek = {
            "banka_teyidi_tarihi": "DATE",
            "banka_teyidi_notu": "VARCHAR(500)",
            "banka_teyidi_kullanici": "VARCHAR(120)",
            "kapanis_turu": "VARCHAR(40)",
            "kapanis_dayanak": "VARCHAR(500)",
            "kapanis_zaman": "TIMESTAMP",
            "kapanis_kullanici": "VARCHAR(120)",
            "eslesen_banka_hareket_idler": "VARCHAR(250)",
        }
        with engine.begin() as conn:
            for ad, tip in eklenecek.items():
                if ad not in mevcut:
                    conn.execute(text(f'ALTER TABLE "pos_valor_kayitlari" ADD COLUMN "{ad}" {tip}'))

    @staticmethod
    def pos_gecmis_yatis_kapat(
        kayit_idler: list[int],
        *,
        dayanak: str,
        kapanis_turu: str = "KULLANICI_BILDIRIMI",
        kullanici: str | None = None,
        eslesen_banka_hareket_idler: list[int] | None = None,
        gercek_yatis_tarihi: date | None = None,
        gercek_yatis_tutari=None,
        kismi_izin: bool = False,
    ) -> list[dict]:
        """Geçmiş yatış eşleştirme / kullanıcı bildirimi ile POS kapanışı.

        Yeni banka/PVA/tahsilat/virman hareketi üretmez. Banka bakiyesini değiştirmez.
        Idempotent: zaten GECMIS_KAPANDI veya tam kapanmış kayıtlar atlanır.
        """
        yazma_zorunlu("finans_duzenleme")
        FinansService._pos_teyit_kolonlari_ensure()
        dayanak_metin = (dayanak or "").strip()
        if not dayanak_metin:
            raise ValueError("Kapanış dayanağı zorunludur (uydurma banka fişi yazılmaz).")
        tur = (kapanis_turu or "KULLANICI_BILDIRIMI").strip().upper()
        if tur not in {"KULLANICI_BILDIRIMI", "BANKA_ESLESME"}:
            raise ValueError("kapanis_turu: KULLANICI_BILDIRIMI veya BANKA_ESLESME olmalı.")
        if tur == "KULLANICI_BILDIRIMI" and gercek_yatis_tarihi is not None:
            # Kullanıcı bildiriminde yatış tarihi uydurulmaz
            raise ValueError(
                "Kullanıcı bildirimi kapanışında yatış tarihi verilmez "
                "(ekstre eşleşmesi yoksa yapılmış gibi gösterilmez)."
            )
        if tur == "BANKA_ESLESME" and not eslesen_banka_hareket_idler:
            raise ValueError("Banka eşleştirmesinde mevcut hareket kimlikleri gerekir.")
        idler = [int(i) for i in (kayit_idler or [])]
        if not idler:
            raise ValueError("Kapatılacak POS kaydı seçin.")
        hareket_idler = [int(i) for i in (eslesen_banka_hareket_idler or [])]
        sonuclar: list[dict] = []
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(PosValorKaydi)
                    .where(PosValorKaydi.id.in_(idler))
                    .execution_options(populate_existing=True)
                ).all()
            )
            by_id = {int(k.id): k for k in kayitlar}
            if len(by_id) != len(set(idler)):
                raise ValueError("Bazı POS kayıtları bulunamadı.")

            # Aynı banka hareketi başka (bu çağrı dışı) kapanışta kullanılamaz.
            # Bu çağrıdaki toplu POS’lar aynı yatışı paylaşabilir (kapasite net toplamıyla).
            kullanilan_hareket: set[int] = set()
            mevcut_h: dict[int, FinansHareketi] = {}
            if hareket_idler:
                diger = list(
                    session.scalars(
                        select(PosValorKaydi).where(
                            PosValorKaydi.id.notin_(idler),
                            PosValorKaydi.eslesen_banka_hareket_idler.isnot(None),
                        )
                    ).all()
                )
                for d in diger:
                    for parca in (d.eslesen_banka_hareket_idler or "").split(","):
                        parca = parca.strip()
                        if parca.isdigit():
                            kullanilan_hareket.add(int(parca))
                for hid in hareket_idler:
                    if hid in kullanilan_hareket:
                        raise ValueError(
                            f"Banka hareketi #{hid} başka bir POS kapanışında kullanılmış; "
                            "aynı yatış tutarı tekrar eşleştirilemez."
                        )
                mevcut_h = {
                    int(h.id): h
                    for h in session.scalars(
                        select(FinansHareketi).where(FinansHareketi.id.in_(hareket_idler))
                    ).all()
                }
                if len(mevcut_h) != len(set(hareket_idler)):
                    raise ValueError("Eşleştirilecek banka hareketlerinden bazıları bulunamadı.")
                if tur == "BANKA_ESLESME":
                    kapasite = sum(
                        (
                            Decimal(str(mevcut_h[hid].tutar or 0))
                            for hid in hareket_idler
                            if hid in mevcut_h
                        ),
                        Decimal("0"),
                    )
                    istenen_toplam = sum(
                        (Decimal(str(by_id[i].net_tutar or 0)) for i in idler),
                        Decimal("0"),
                    )
                    if istenen_toplam > kapasite + Decimal("0.05"):
                        raise ValueError(
                            f"Toplu eşleştirme: POS net toplamı ({istenen_toplam}) "
                            f"seçilen banka yatış kapasitesini ({kapasite}) aşıyor."
                        )

            zaman = datetime.now()
            uname = (str(kullanici).strip()[:120] if kullanici else None)
            for kid in idler:
                k = by_id[kid]
                session.refresh(k)
                durum = (k.durum or "").strip().upper()
                if durum in ("IPTAL", "İPTAL"):
                    sonuclar.append(
                        {
                            "kayit_id": kid,
                            "belge_no": k.belge_no,
                            "kapatildi": False,
                            "atlandi": True,
                            "neden": "iptal",
                        }
                    )
                    continue
                if durum == "GECMIS_KAPANDI" or (
                    durum == "AKTARILDI"
                    and FinansService.pos_aktarim_kalan_net(k) <= 0
                    and (getattr(k, "kapanis_turu", None) or getattr(k, "gercek_yatis_tarihi", None))
                ):
                    sonuclar.append(
                        {
                            "kayit_id": kid,
                            "belge_no": k.belge_no,
                            "kapatildi": False,
                            "atlandi": True,
                            "neden": "zaten_kapali",
                            "durum": durum,
                        }
                    )
                    continue
                kalan = FinansService.pos_aktarim_kalan_net(k)
                if kalan <= 0 and not kismi_izin:
                    sonuclar.append(
                        {
                            "kayit_id": kid,
                            "belge_no": k.belge_no,
                            "kapatildi": False,
                            "atlandi": True,
                            "neden": "kalan_yok",
                        }
                    )
                    continue
                net = Decimal(str(k.net_tutar or 0))
                if gercek_yatis_tutari is not None:
                    yatis_tut = _decimal(gercek_yatis_tutari, "Yatış tutarı", Decimal("0.01"))
                else:
                    yatis_tut = net
                if yatis_tut <= 0:
                    raise ValueError(f"{k.belge_no}: kapanış tutarı pozitif olmalı.")
                if yatis_tut > net + Decimal("0.005"):
                    raise ValueError(f"{k.belge_no}: kapanış tutarı neti aşamaz.")
                if not kismi_izin and yatis_tut + Decimal("0.005") < net:
                    raise ValueError(
                        f"{k.belge_no}: kısmi kapanış için kismi_izin=True gerekir; "
                        "yalnız gerçekten aktarılmamış kalan açık bırakılır."
                    )

                eski = {
                    "durum": k.durum,
                    "gercek_yatis_tarihi": str(getattr(k, "gercek_yatis_tarihi", None) or ""),
                    "gercek_yatis_tutari": str(getattr(k, "gercek_yatis_tutari", None) or ""),
                    "kapanis_turu": getattr(k, "kapanis_turu", None) or "",
                }
                if tur == "BANKA_ESLESME":
                    # Mevcut hareket tarihi — uydurma değil
                    tarihler = sorted(
                        {
                            mevcut_h[hid].tarih
                            for hid in hareket_idler
                            if hid in mevcut_h and mevcut_h[hid].tarih
                        }
                    )
                    yatis_tar = gercek_yatis_tarihi or (tarihler[-1] if tarihler else None)
                    if yatis_tar is None:
                        raise ValueError(
                            f"{k.belge_no}: eşleşen banka hareketinde tarih yok; "
                            "yatış tarihi uydurulmaz."
                        )
                    k.durum = "AKTARILDI" if yatis_tut + Decimal("0.005") >= net else "KISMEN"
                    k.gercek_yatis_tarihi = yatis_tar
                    k.gercek_yatis_tutari = yatis_tut
                    k.eslesen_banka_hareket_idler = ",".join(str(i) for i in hareket_idler)[:250]
                else:
                    # Kullanıcı bildirimi: tarih uydurma; durum ayrı kod
                    k.durum = "GECMIS_KAPANDI"
                    k.gercek_yatis_tarihi = None
                    k.gercek_yatis_tutari = yatis_tut
                    if hareket_idler:
                        k.eslesen_banka_hareket_idler = ",".join(str(i) for i in hareket_idler)[:250]

                k.kapanis_turu = tur
                k.kapanis_dayanak = dayanak_metin[:500]
                k.kapanis_zaman = zaman
                k.kapanis_kullanici = uname
                # Otomatik aktarım taramasından düşmesi için BEKLIYOR olmamalı (zaten değil)
                FinansService._pos_degisiklik_kaydet(
                    session,
                    k,
                    eski,
                    {
                        "durum": k.durum,
                        "gercek_yatis_tarihi": str(k.gercek_yatis_tarihi or ""),
                        "gercek_yatis_tutari": str(k.gercek_yatis_tutari or ""),
                        "kapanis_turu": k.kapanis_turu or "",
                        "kapanis_dayanak": k.kapanis_dayanak or "",
                    },
                )
                sonuclar.append(
                    {
                        "kayit_id": kid,
                        "belge_no": k.belge_no,
                        "kapatildi": True,
                        "durum": k.durum,
                        "kapanis_turu": tur,
                        "net": str(net),
                        "kapanan": str(yatis_tut),
                        "kalan": str(FinansService.pos_aktarim_kalan_net(k)),
                        "eslesen_hareket_idler": list(hareket_idler),
                        "gercek_yatis_tarihi": str(k.gercek_yatis_tarihi or ""),
                    }
                )
            session.commit()
        return sonuclar

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
                    select(BankaKarti)
                    .where(BankaKarti.id.in_(kart_ids))
                    .options(selectinload(BankaKarti.alt_hesaplar))
                ).all()
            }
            # Detach-safe özet (session kapandıktan sonra lazy load yok)
            kart_ozet = {}
            for kid, kart in kartlar.items():
                yontem = (getattr(kart, "pos_aktarim_yontemi", None) or "").strip().upper()
                if not yontem:
                    yontem = (
                        "OTOMATIK"
                        if bool(getattr(kart, "pos_otomatik_mahsup", False))
                        else "MANUEL"
                    )
                hedef = FinansService._pos_hedef_hesap(kart)
                kart_ozet[kid] = {
                    "yontem": yontem,
                    "baslangic": getattr(kart, "pos_otomatik_baslangic", None),
                    "hedef_var": hedef is not None,
                }
        sonuclar = []
        for kayit in bekleyenler:
            if not FinansService.pos_valor_vadesi_geldi_mi(kayit):
                continue
            # Geri alınmış / kullanıcı onayı bekleyen: otomatik döngü atlar
            if sadece_otomatik and bool(getattr(kayit, "otomatik_aktarim_engel", False)):
                continue
            oz = kart_ozet.get(int(kayit.banka_karti_id), {})
            yontem = oz.get("yontem") or "MANUEL"
            oto = yontem == "OTOMATIK"
            if sadece_otomatik and not oto and not zorla:
                continue
            if sadece_otomatik and oto:
                bas = oz.get("baslangic")
                if bas and kayit.tahsilat_tarihi and kayit.tahsilat_tarihi < bas:
                    continue
                if not oz.get("hedef_var"):
                    sonuclar.append(
                        {
                            "kayit_id": int(kayit.id),
                            "belge_no": kayit.belge_no,
                            "aktarildi": False,
                            "hata": "Hedef banka hesabı eksik veya geçersiz — otomatik aktarım başlatılmadı",
                        }
                    )
                    continue
            try:
                yontem_kayit = "OTOMATIK" if (sadece_otomatik and oto and not zorla) else "MANUEL"
                sonuclar.append(
                    FinansService.pos_valor_aktar(
                        kayit.id,
                        aktarim_yontemi=yontem_kayit,
                        banka_teyidi=(False if yontem_kayit == "OTOMATIK" else True),
                    )
                )
            except ValueError as hata:
                sonuclar.append(
                    {
                        "kayit_id": int(kayit.id),
                        "belge_no": kayit.belge_no,
                        "aktarildi": False,
                        "hata": str(hata),
                    }
                )
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
        """Manuel iç plan: 1. taksit = işlem/çekim günü.

        Banka son ödeme / ekstre kesimi ayrı alanlarda tutulur; bu öneri onları ezmez.
        ``kart`` parametresi geriye uyum için korunur.
        """
        return cekim_tarihi

    @staticmethod
    def kk_banka_vade_oner(kart, cekim_tarihi: date, taksit_no: int = 1) -> date | None:
        """Kart kesim kuralına göre banka ödeme vadesi (iç plan vadesinden ayrı)."""
        if kart is None:
            return None
        try:
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            if KrediKartiEkstreService.kesim_gunu(kart) is None:
                return None
            donem = KrediKartiEkstreService.taksit_donem_bilgisi(
                cekim_tarihi, max(1, int(taksit_no or 1)), kart
            )
            return donem.get("son_odeme_tarihi") or donem.get("kesim_tarihi")
        except Exception:
            return None

    @staticmethod
    def kk_taksit_plani(
        cekim_tarihi: date,
        taksit_sayisi: int,
        tutar: Decimal,
        ilk_taksit_tarihi: date | None = None,
        kart=None,
    ) -> list[dict]:
        """Manuel iç taksit planı.

        * 1. vade = ``ilk_taksit_tarihi`` veya işlem/çekim günü.
        * n. vade = orijinal başlangıçtan (n−1) takvim ayı (önceki vadeye ay eklenmez).
        * Ayda gün yoksa yalnız o taksit için ay sonu.
        * Kart kesimi varsa ``ekstre_kesim_tarihi`` / ``banka_vade_tarihi`` ayrıca yazılır;
          iç plan vadesini banka son ödemesiyle değiştirmez.
        Evo/banka ekstresinden yazılmış gerçek vadeler bu fonksiyonla topluca yeniden
        yazılmaz (aktarım ayrı kimliklerle korunur).
        """
        n = int(taksit_sayisi)
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        toplam = Decimal(str(tutar)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if toplam <= 0:
            raise ValueError("Taksit planı tutarı sıfırdan büyük olmalıdır.")
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
            if taksit_tutar <= 0:
                raise ValueError("Taksit satır tutarı sıfır/negatif olamaz; sayı veya tutarı düzeltin.")
            # İç plan: her zaman orijinal başlangıçtan
            vade = FinansService._ay_ekle(base, i - 1)
            kesim = None
            banka_vade = None
            donem_bas = None
            if ekstre_servis is not None:
                donem = ekstre_servis.taksit_donem_bilgisi(cekim_tarihi, i, kart)
                kesim = donem.get("kesim_tarihi")
                banka_vade = donem.get("son_odeme_tarihi") or kesim
                donem_bas = donem.get("donem_baslangic")
            plan.append({
                "taksit_no": i,
                "vade_tarihi": vade,
                "tutar": taksit_tutar,
                "anapara": taksit_tutar,
                "faiz_ucret": Decimal("0.00"),
                "ekstre_kesim_tarihi": kesim,
                "banka_vade_tarihi": banka_vade,
                "donem_baslangic": donem_bas,
                "yansima_tarihi": vade,
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
                bid = int(banka_karti_id)
                # Doğrudan bankaya bağlı + bu bankanın KK hesabına bagli_hesap ile bağlı
                hesap_idler = list(
                    session.scalars(
                        select(FinansHesabi.id).where(
                            FinansHesabi.banka_karti_id == bid,
                            FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                        )
                    ).all()
                )
                if hesap_idler:
                    q = q.where(
                        (KrediKartiTanimi.banka_karti_id == bid)
                        | (KrediKartiTanimi.bagli_hesap_id.in_(hesap_idler))
                    )
                else:
                    q = q.where(KrediKartiTanimi.banka_karti_id == bid)
            if aktif_only:
                q = q.where(KrediKartiTanimi.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def kredi_kartlari_eslestir(*, yaz: bool = False) -> dict:
        """KK alt hesapları ile KrediKartiTanimi eşlemesi.

        - Kabuk bankadaki (02 …) tanımı gerçek bankanın KK hesabına bağlar.
        - Tanımı olmayan gerçek KK hesabı için tanım oluşturur (finansal hareket YOK).
        - Limit/kesim/son ödeme uydurulmaz. Idempotent.
        """
        if yaz:
            yazma_zorunlu("finans_duzenleme")
        rapor = {
            "eslesen": [],
            "olusturulan": [],
            "zaten_bagli": [],
            "eslesmeyen_hesap": [],
            "eslesmeyen_tanim": [],
            "yazim": bool(yaz),
        }
        with get_session() as session:
            hesaplar = list(
                session.scalars(
                    select(FinansHesabi)
                    .where(FinansHesabi.alt_hesap_turu == "KREDI_KARTI")
                    .options(selectinload(FinansHesabi.hareketler))
                ).all()
            )
            tanimlar = list(session.scalars(select(KrediKartiTanimi)).all())
            by_bagli = {
                int(t.bagli_hesap_id): t
                for t in tanimlar
                if getattr(t, "bagli_hesap_id", None)
            }
            by_norm: dict[str, list] = {}
            for t in tanimlar:
                by_norm.setdefault(FinansService._kk_ad_normalize(t.kart_adi), []).append(t)

            kullanilan_tanim: set[int] = set()
            for h in hesaplar:
                ad = (h.hesap_adi or "").casefold()
                yer = "— kredi kartı hesabı" in ad or ad.endswith("kredi kartı hesabı")
                bak = FinansService.bakiye(h)
                if yer and abs(bak) <= Decimal("0.005") and not (h.hareketler or []):
                    continue  # boş yer tutucu
                if int(h.id) in by_bagli:
                    t = by_bagli[int(h.id)]
                    kullanilan_tanim.add(int(t.id))
                    degisti = False
                    if int(t.banka_karti_id) != int(h.banka_karti_id or 0):
                        if yaz:
                            t.banka_karti_id = int(h.banka_karti_id)
                        degisti = True
                    rapor["zaten_bagli" if not degisti else "eslesen"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "tanim_id": int(t.id),
                            "kart_adi": t.kart_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "islem": "bagli_guncelle" if degisti else "ok",
                        }
                    )
                    continue
                norm = FinansService._kk_ad_normalize(h.hesap_adi or "")
                adaylar = [
                    t
                    for t in by_norm.get(norm, [])
                    if int(t.id) not in kullanilan_tanim
                    and not getattr(t, "bagli_hesap_id", None)
                ]
                if not adaylar:
                    skorlu: list[tuple[float, object]] = []
                    for t in tanimlar:
                        if int(t.id) in kullanilan_tanim:
                            continue
                        if getattr(t, "bagli_hesap_id", None):
                            continue
                        skor = FinansService._kk_ad_benzerlik(h.hesap_adi or "", t.kart_adi or "")
                        if skor >= 0.75:
                            skorlu.append((skor, t))
                    skorlu.sort(key=lambda x: (-x[0], int(x[1].id)))
                    adaylar = [t for _s, t in skorlu]
                if adaylar:
                    t = adaylar[0]
                    kullanilan_tanim.add(int(t.id))
                    if yaz:
                        t.bagli_hesap_id = int(h.id)
                        t.banka_karti_id = int(h.banka_karti_id)
                        if not (t.kart_bankasi or "").strip():
                            banka = session.get(BankaKarti, int(h.banka_karti_id))
                            t.kart_bankasi = banka.banka_adi if banka else t.kart_bankasi
                    rapor["eslesen"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "tanim_id": int(t.id),
                            "kart_adi": t.kart_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "islem": "tanim_bagla",
                        }
                    )
                    continue
                from database.kart_silme import kk_tanim_engelli

                if kk_tanim_engelli(
                    int(h.banka_karti_id or 0),
                    hesap_id=int(h.id),
                    kart_adi=h.hesap_adi,
                    session=session,
                ):
                    rapor.setdefault("engelli", []).append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "islem": "silinmis_yeniden_acilmadi",
                            "mesaj": (
                                "Bu firma kredi kartı tanımı kullanıcı tarafından silinmiş; "
                                "sessizce yeniden açılmadı. Yeni hareket için eşleştirme gerekir."
                            ),
                        }
                    )
                    continue
                # Yeni tanım — hareket üretmeden
                if yaz:
                    banka = session.get(BankaKarti, int(h.banka_karti_id))
                    t = KrediKartiTanimi(
                        banka_karti_id=int(h.banka_karti_id),
                        kart_adi=(h.hesap_adi or "Kredi Kartı")[:100],
                        kart_bankasi=(banka.banka_adi if banka else None),
                        bagli_hesap_id=int(h.id),
                        kart_limiti=Decimal("0"),
                        aciklama="Otomatik eşleme: mevcut KK hesabından (limit/kesim kaynakta yok)",
                        aktif=bool(h.aktif),
                    )
                    session.add(t)
                    session.flush()
                    kullanilan_tanim.add(int(t.id))
                    rapor["olusturulan"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "tanim_id": int(t.id),
                            "kart_adi": t.kart_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "islem": "tanim_olustur",
                        }
                    )
                else:
                    rapor["eslesmeyen_hesap"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "bakiye": str(bak),
                        }
                    )

            for t in tanimlar:
                if int(t.id) in kullanilan_tanim:
                    continue
                if getattr(t, "bagli_hesap_id", None):
                    continue
                rapor["eslesmeyen_tanim"].append(
                    {
                        "tanim_id": int(t.id),
                        "kart_adi": t.kart_adi,
                        "banka_karti_id": int(t.banka_karti_id),
                        "aktif": bool(t.aktif),
                    }
                )
            if yaz:
                session.commit()
        return rapor

    @staticmethod
    def kredi_karti_hesap_hareketleri(
        banka_karti_id,
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        limit: int = 800,
        kredi_karti_id: int | None = None,
        yalniz_eslesmesiz: bool = False,
    ) -> list[dict]:
        """KK hareketleri — kimlik (kart / bagli_hesap) ile süzülür.

        - ``kredi_karti_id``: yalnız o tanımın ``bagli_hesap_id`` hareketleri.
          Bağlı hesap yoksa boş döner (başka karta düşmez).
        - ``yalniz_eslesmesiz``: hiçbir kart tanımına bağlı olmayan hesap hareketleri.
        - İkisi de yok: bankanın tüm KK hesapları (Tüm kartlar).
        Aynı hareket birden fazla satırda dönmez.
        """
        with get_session() as session:
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(
                    selectinload(BankaKarti.alt_hesaplar).selectinload(
                        FinansHesabi.hareketler
                    )
                )
            )
            if not kart:
                return []
            hesaplar = [
                h
                for h in (kart.alt_hesaplar or [])
                if (h.alt_hesap_turu or "").upper() == "KREDI_KARTI"
            ]
            if not hesaplar:
                return []
            hesap_idler = [int(h.id) for h in hesaplar]
            hesap_ad = {int(h.id): h.hesap_adi for h in hesaplar}
            hesap_by_id = {int(h.id): h for h in hesaplar}
            tanimlar = list(
                session.scalars(
                    select(KrediKartiTanimi).where(
                        (KrediKartiTanimi.banka_karti_id == int(banka_karti_id))
                        | (KrediKartiTanimi.bagli_hesap_id.in_(hesap_idler))
                    )
                ).all()
            )
            bagli_map = {
                int(t.bagli_hesap_id): t
                for t in tanimlar
                if getattr(t, "bagli_hesap_id", None)
            }
            hedef_idler = list(hesap_idler)
            if yalniz_eslesmesiz:
                hedef_idler = [hid for hid in hesap_idler if hid not in bagli_map]
            elif kredi_karti_id is not None:
                kk = next(
                    (t for t in tanimlar if int(t.id) == int(kredi_karti_id)),
                    None,
                )
                if kk is None:
                    kk = session.scalar(
                        select(KrediKartiTanimi).where(
                            KrediKartiTanimi.id == int(kredi_karti_id)
                        )
                    )
                bagli = getattr(kk, "bagli_hesap_id", None) if kk else None
                if not bagli or int(bagli) not in hesap_by_id:
                    return []
                hedef_idler = [int(bagli)]
            if not hedef_idler:
                return []
            q = (
                select(FinansHareketi)
                .where(FinansHareketi.hesap_id.in_(hedef_idler))
                .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                .limit(int(limit))
            )
            if baslangic:
                q = q.where(FinansHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FinansHareketi.tarih <= bitis)
            sonuc = []
            gorulen: set[int] = set()
            for har in session.scalars(q).all():
                hid = int(har.hesap_id)
                har_id = int(har.id)
                if har_id in gorulen:
                    continue
                gorulen.add(har_id)
                kk = bagli_map.get(hid)
                if yalniz_eslesmesiz and kk is not None:
                    continue
                if (
                    kredi_karti_id is not None
                    and not yalniz_eslesmesiz
                    and (kk is None or int(kk.id) != int(kredi_karti_id))
                ):
                    continue
                isaret = FinansService.hareket_isareti(har.hareket_turu)
                sonuc.append(
                    {
                        "id": har_id,
                        "hesap_id": hid,
                        "hesap_adi": hesap_ad.get(hid, ""),
                        "tarih": har.tarih,
                        "hareket_turu": har.hareket_turu,
                        "belge_no": har.belge_no or "",
                        "tutar": Decimal(str(har.tutar or 0)),
                        "isaret": isaret,
                        "aciklama": har.aciklama or "",
                        "kart": kk.kart_adi if kk else "",
                        "kredi_karti_id": int(kk.id) if kk else None,
                        "esleme_bekliyor": kk is None,
                        "planli": False,
                        "durum": "KESIN",
                        "durum_etiket": "Kesin",
                        "taksit_no": None,
                        "taksit_sayisi": None,
                        "ekstre_kesim_tarihi": None,
                        "son_odeme_tarihi": None,
                        "taksit_id": None,
                        "odeme_id": None,
                    }
                )
            try:
                FinansService._kk_hareket_taksit_zenginlestir(session, sonuc)
            except Exception:
                # Zenginleştirme yalnız görüntü içindir; liste hiçbir koşulda düşmesin.
                pass
            return sonuc

    @staticmethod
    def _kk_hareket_taksit_zenginlestir(session, sonuc: list[dict]) -> None:
        """Hareket satırlarına taksit / ekstre kesim / son ödeme bilgisini ekler (salt okunur).

        Eşleşme: ``KrediKartiOdemeTaksit.kk_hareket_belge_no == belge_no`` veya
        belge ``{odeme.belge_no}-T{n}`` biçimindeyse (odeme, taksit_no) çifti.
        """
        if not sonuc:
            return
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        belge_set: set[str] = set()
        taban_set: set[str] = set()
        taban_re = re.compile(r"^(.+)-T(\d+)$")
        for r in sonuc:
            b = (r.get("belge_no") or "").strip()
            if not b:
                continue
            belge_set.add(b)
            m = taban_re.match(b)
            if m:
                taban_set.add(m.group(1))

        by_belge: dict[str, KrediKartiOdemeTaksit] = {}
        by_taban: dict[tuple[str, int], KrediKartiOdemeTaksit] = {}

        def _parcalar(degerler: list[str], n: int = 400):
            for i in range(0, len(degerler), n):
                yield degerler[i:i + n]

        def _topla(t: KrediKartiOdemeTaksit) -> None:
            if getattr(t, "aktif", True) is False:
                return
            if (t.durum or "").upper() == "PLAN_IPTAL":
                return
            kb = (getattr(t, "kk_hareket_belge_no", None) or "").strip()
            if kb:
                by_belge[kb] = t
            o = t.odeme
            if o is not None and o.belge_no:
                by_taban[(o.belge_no, int(t.taksit_no))] = t

        opts = selectinload(KrediKartiOdemeTaksit.odeme).selectinload(KrediKartiOdeme.kredi_karti)
        for parca in _parcalar(sorted(belge_set)):
            for t in session.scalars(
                select(KrediKartiOdemeTaksit)
                .where(KrediKartiOdemeTaksit.kk_hareket_belge_no.in_(parca))
                .options(opts)
            ).all():
                _topla(t)
        for parca in _parcalar(sorted(taban_set)):
            for t in session.scalars(
                select(KrediKartiOdemeTaksit)
                .join(KrediKartiOdeme, KrediKartiOdemeTaksit.odeme_id == KrediKartiOdeme.id)
                .where(KrediKartiOdeme.belge_no.in_(parca))
                .options(opts)
            ).all():
                _topla(t)

        nat_re = re.compile(r"taksit\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)
        for r in sonuc:
            b = (r.get("belge_no") or "").strip()
            t = by_belge.get(b) if b else None
            if t is None and b:
                m = taban_re.match(b)
                if m:
                    t = by_taban.get((m.group(1), int(m.group(2))))
            if t is not None:
                o = t.odeme
                r["taksit_id"] = int(t.id)
                r["odeme_id"] = int(o.id) if o is not None else None
                r["taksit_no"] = int(t.taksit_no)
                r["taksit_sayisi"] = int(o.taksit_sayisi) if o is not None and o.taksit_sayisi else None
                kart_t = o.kredi_karti if o is not None else None
                kesim = None
                son = getattr(t, "banka_vade_tarihi", None)
                if kart_t is not None:
                    try:
                        donem = KrediKartiEkstreService.taksit_kesimi(o, t, kart_t)
                    except Exception:
                        donem = None
                    if donem:
                        kesim = donem.get("kesim_tarihi")
                        son = son or donem.get("son_odeme_tarihi")
                if kesim is None:
                    kesim = getattr(t, "ekstre_kesim_tarihi", None)
                r["ekstre_kesim_tarihi"] = kesim
                r["son_odeme_tarihi"] = son
            # NAT: açıklamada "taksit N/M" varsa ve kayıt tek çekim görünüyorsa N/M tercih edilir
            m2 = nat_re.search(r.get("aciklama") or "")
            if m2:
                n_p, m_p = int(m2.group(1)), int(m2.group(2))
                if m_p > 1 and (r.get("taksit_sayisi") in (None, 0, 1)):
                    r["taksit_no"] = n_p
                    r["taksit_sayisi"] = m_p

    @staticmethod
    def kredi_karti_birlesik_hareketler(
        banka_karti_id,
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        limit: int = 800,
        kredi_karti_id: int | None = None,
        yalniz_eslesmesiz: bool = False,
        planlilari_dahil: bool = True,
        yalniz_planli: bool = False,
    ) -> list[dict]:
        """Ledger hareketleri (taksitler kayıtta kalıcı ``-Tn`` satırları).

        ``planlilari_dahil`` / ``yalniz_planli`` geriye uyum için korunur: eksik
        bağlantılı BEKLIYOR kalırsa geçici görüntü satırı eklenir; asıl yol
        ``eksik_taksit_hareketlerini_tamamla`` ile kalıcı harekettir.
        """
        ledger = FinansService.kredi_karti_hesap_hareketleri(
            banka_karti_id,
            baslangic=baslangic,
            bitis=bitis,
            limit=limit,
            kredi_karti_id=kredi_karti_id,
            yalniz_eslesmesiz=yalniz_eslesmesiz,
        )
        if yalniz_eslesmesiz or not planlilari_dahil:
            return ledger if not yalniz_planli else []

        belge_set = {
            (h.get("belge_no") or "").strip().upper()
            for h in ledger
            if (h.get("belge_no") or "").strip()
        }
        # Eksik bağlantı güvenlik ağı (normalde boş; backfill sonrası kalıcı -Tn var)
        planlar: list[dict] = []
        for t in FinansService.kredi_karti_bekleyen_taksitler(
            banka_karti_id,
            limit=max(limit, 500),
            kredi_karti_id=kredi_karti_id,
        ):
            yansima = t.get("yansima_tarihi") or t.get("vade_tarihi")
            if baslangic and yansima and yansima < baslangic:
                continue
            if bitis and yansima and yansima > bitis:
                continue
            kaynak_belge = (t.get("belge_no") or "").strip()
            tn = int(t.get("taksit_no") or 0)
            adaylar = set()
            if kaynak_belge:
                adaylar.add(kaynak_belge.upper())
                if tn:
                    adaylar.add(f"{kaynak_belge}-T{tn}".upper())
            kk_har = (t.get("kk_hareket_belge_no") or "").strip()
            if kk_har:
                adaylar.add(kk_har.upper())
            if adaylar & belge_set:
                continue  # zaten kesin hareket var
            planlar.append(
                {
                    "id": None,
                    "virtual_id": f"p{t.get('taksit_id')}",
                    "hesap_id": None,
                    "hesap_adi": "",
                    "tarih": yansima,
                    "hareket_turu": "PLANLI TAKSİT",
                    "belge_no": kaynak_belge,
                    "tutar": Decimal(str(t.get("tutar") or 0)),
                    "isaret": 0,
                    "aciklama": (
                        f"Eksik bağlantı — taksit {t.get('taksit_no')}/{t.get('taksit_sayisi')}"
                        f" (kalıcı hareket bekleniyor; borç artırmaz)"
                    ),
                    "kart": t.get("kart") or "",
                    "kredi_karti_id": t.get("kredi_karti_id"),
                    "esleme_bekliyor": False,
                    "planli": True,
                    "durum": "PLANLI",
                    "durum_etiket": "Eksik bağlantı",
                    "taksit_no": t.get("taksit_no"),
                    "taksit_sayisi": t.get("taksit_sayisi"),
                    "ekstre_kesim_tarihi": t.get("ekstre_kesim_tarihi"),
                    "son_odeme_tarihi": t.get("son_odeme_tarihi")
                    or t.get("banka_vade_tarihi"),
                    "taksit_id": t.get("taksit_id"),
                    "odeme_id": t.get("odeme_id"),
                    "kaynak": t.get("kaynak"),
                }
            )

        if yalniz_planli:
            birlesik = planlar
        else:
            birlesik = list(ledger) + planlar
        birlesik.sort(
            key=lambda r: (
                r.get("tarih") or date.min,
                0 if r.get("planli") else 1,
                int(r.get("id") or r.get("taksit_id") or 0),
            ),
            reverse=True,
        )
        # Tek çekim: ana borç + 1/1 ayrıntı aynı listede iki satır olmasın (mali kayıt silinmez)
        birlesik = FinansService._kk_tek_cekim_hareket_birlestir(birlesik)
        return birlesik[: int(limit)]

    @staticmethod
    def _kk_tek_cekim_hareket_birlestir(sonuc: list[dict]) -> list[dict]:
        """Tek çekimde ana ödeme ile ``-T1`` (1/1) satırını tek satırda birleştir.

        Mali kayıtlar silinmez; yalnız liste görünümü birleşir. Çok taksitte
        (``taksit_sayisi > 1`` veya aynı ana için ``-T2+`` varsa) dokunulmaz.
        Ana satır (borç / ``KK ÖDEME``) korunur; taksit / ekstre alanları ``-T1``'den gelir.
        """
        if not sonuc:
            return sonuc
        taban_re = re.compile(r"^(.+)-T(\d+)$")
        by_belge: dict[str, int] = {}
        for i, r in enumerate(sonuc):
            b = (r.get("belge_no") or "").strip()
            if b and b not in by_belge:
                by_belge[b] = i

        def _diger_tn_var(ana: str) -> bool:
            for b in by_belge:
                m = taban_re.match(b)
                if m and m.group(1) == ana and int(m.group(2)) != 1:
                    return True
            return False

        gizle: set[int] = set()
        for b, i in list(by_belge.items()):
            m = taban_re.match(b)
            if not m or int(m.group(2)) != 1:
                continue
            ana = m.group(1)
            det = sonuc[i]
            if det.get("planli"):
                continue
            n = det.get("taksit_sayisi")
            try:
                n_i = int(n) if n is not None else None
            except (TypeError, ValueError):
                n_i = None
            if n_i is not None and n_i > 1:
                continue
            if n_i is None and _diger_tn_var(ana):
                continue
            ana_i = by_belge.get(ana)
            if ana_i is None:
                # Yalnız -T1 görünüyorsa 1/1 bilgisini tamamla; satırı bırak
                if det.get("taksit_no") is None:
                    det["taksit_no"] = 1
                if det.get("taksit_sayisi") is None:
                    det["taksit_sayisi"] = 1
                continue
            ana_r = sonuc[ana_i]
            if ana_r.get("planli"):
                continue
            # Taksit / ekstre alanlarını ana (borç) satıra taşı
            for k in (
                "taksit_id",
                "odeme_id",
                "taksit_no",
                "taksit_sayisi",
                "ekstre_kesim_tarihi",
                "son_odeme_tarihi",
            ):
                if det.get(k) is not None and ana_r.get(k) is None:
                    ana_r[k] = det.get(k)
            if ana_r.get("taksit_no") is None:
                ana_r["taksit_no"] = 1
            if ana_r.get("taksit_sayisi") is None:
                ana_r["taksit_sayisi"] = 1
            # Açma/düzenleme ana belge_no üzerinden (kk_odeme_belge_coz -T1'i de çözer)
            gizle.add(i)

        if not gizle:
            return sonuc
        return [r for j, r in enumerate(sonuc) if j not in gizle]

    @staticmethod
    def kredi_karti_isletme_bakiyesi(kredi_karti_id) -> dict:
        """Tek kart tanımının bağlı KK hesabı işletme bakiyesi (mali veri değiştirmez)."""
        with get_session() as session:
            kk = session.scalar(
                select(KrediKartiTanimi)
                .where(KrediKartiTanimi.id == int(kredi_karti_id))
                .options(selectinload(KrediKartiTanimi.banka_karti))
            )
            if not kk:
                return {
                    "kredi_karti_id": int(kredi_karti_id),
                    "kart_adi": "",
                    "bagli_hesap_id": None,
                    "bakiye": None,
                    "hesap_adi": "",
                }
            bagli_id = getattr(kk, "bagli_hesap_id", None)
            if not bagli_id:
                return {
                    "kredi_karti_id": int(kk.id),
                    "kart_adi": kk.kart_adi or "",
                    "bagli_hesap_id": None,
                    "bakiye": None,
                    "hesap_adi": "",
                }
            hesap = session.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(bagli_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if not hesap:
                return {
                    "kredi_karti_id": int(kk.id),
                    "kart_adi": kk.kart_adi or "",
                    "bagli_hesap_id": int(bagli_id),
                    "bakiye": None,
                    "hesap_adi": "",
                }
            isletme = FinansService.isletme_bakiyesi(hesap)
            return {
                "kredi_karti_id": int(kk.id),
                "kart_adi": kk.kart_adi or "",
                "bagli_hesap_id": int(bagli_id),
                "bakiye": isletme,
                "hesap_adi": hesap.hesap_adi or "",
            }

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

        # CVV toplanmaz / saklanmaz (PCI); eski değer varsa kayitte temizlenir
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
            if hasattr(kart, "guvenlik_kodu"):
                kart.guvenlik_kodu = None
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
            if hasattr(kart, "odeme_vade_yontemi") and "odeme_vade_yontemi" in veriler:
                yontem = (veriler.get("odeme_vade_yontemi") or "KESIM_ARTI_N").strip().upper()
                if yontem not in ("KESIM_ARTI_N", "AYIN_GUNU"):
                    raise ValueError("Ödeme vadesi yöntemi KESIM_ARTI_N veya AYIN_GUNU olmalıdır.")
                kart.odeme_vade_yontemi = yontem
                # Çelişki: tek etkin yöntem — diğerini temizle
                if yontem == "KESIM_ARTI_N":
                    kart.son_odeme_gunu = None
                else:
                    kart.kesimden_sonra_odeme_gun = None
            if hasattr(kart, "banka_urun_turu") and "banka_urun_turu" in veriler:
                tur = (veriler.get("banka_urun_turu") or "").strip().upper() or None
                if tur and tur not in ("BIREYSEL", "TICARI", "KURUMSAL"):
                    raise ValueError("Banka ürün türü BIREYSEL / TICARI / KURUMSAL olmalıdır.")
                kart.banka_urun_turu = tur
            if hasattr(kart, "asgari_oran_yuzde") and "asgari_oran_yuzde" in veriler:
                ham = veriler.get("asgari_oran_yuzde")
                if ham in (None, ""):
                    kart.asgari_oran_yuzde = None
                else:
                    oran = _decimal(ham, "Asgari oran", Decimal("0"))
                    if oran < 0 or oran > 100:
                        raise ValueError("Asgari oran 0-100 arasında olmalıdır.")
                    kart.asgari_oran_yuzde = oran
            if hasattr(kart, "asgari_kaynak") and "asgari_kaynak" in veriler:
                kart.asgari_kaynak = (veriler.get("asgari_kaynak") or "").strip() or None
            if hasattr(kart, "asgari_gecerlilik") and "asgari_gecerlilik" in veriler:
                g = veriler.get("asgari_gecerlilik")
                if isinstance(g, str) and g.strip():
                    from datetime import datetime as _dt

                    try:
                        g = _dt.strptime(g.strip()[:10], "%d.%m.%Y").date()
                    except ValueError:
                        try:
                            g = _dt.strptime(g.strip()[:10], "%Y-%m-%d").date()
                        except ValueError as hata:
                            raise ValueError("Asgari geçerlilik GG.AA.YYYY olmalıdır.") from hata
                elif isinstance(g, str) and not g.strip():
                    g = None
                kart.asgari_gecerlilik = g if isinstance(g, date) or g is None else None
            if hasattr(kart, "otomatik_faiz_tahakkuku") and "otomatik_faiz_tahakkuku" in veriler:
                kart.otomatik_faiz_tahakkuku = bool(veriler.get("otomatik_faiz_tahakkuku"))
            if hasattr(kart, "varsayilan_taksit_adet") and "varsayilan_taksit_adet" in veriler:
                ham_t = veriler.get("varsayilan_taksit_adet")
                if ham_t in (None, ""):
                    kart.varsayilan_taksit_adet = 6
                else:
                    try:
                        n = int(str(ham_t).strip())
                    except ValueError as hata:
                        raise ValueError("Varsayılan taksit 1-12 arasında olmalıdır.") from hata
                    if n < 1 or n > 12:
                        raise ValueError("Varsayılan taksit 1-12 arasında olmalıdır.")
                    kart.varsayilan_taksit_adet = n
            kart.aciklama = (veriler.get("aciklama") or "").strip() or None
            if "aktif" in veriler:
                kart.aktif = bool(veriler["aktif"])
            if "bagli_hesap_id" in veriler:
                bagli = veriler.get("bagli_hesap_id")
                if bagli in (None, "", 0, "0"):
                    kart.bagli_hesap_id = None
                else:
                    hesap = session.scalar(
                        select(FinansHesabi).where(FinansHesabi.id == int(bagli))
                    )
                    if not hesap or (hesap.alt_hesap_turu or "").upper() != "KREDI_KARTI":
                        raise ValueError("Bağlı hesap bir kredi kartı alt hesabı olmalıdır.")
                    if int(hesap.banka_karti_id or 0) != int(banka.id):
                        raise ValueError("Bağlı KK hesabı seçilen bankaya ait olmalıdır.")
                    kart.bagli_hesap_id = int(hesap.id)
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
    def kredi_karti_kullanim_ozeti(kart_id) -> dict:
        """Firma kredi kartı tanımının silme engelleri. Sıfır bakiye kullanılmamış sayılmaz."""
        from database.kart_silme import kredi_karti_kullanim_ozeti

        return kredi_karti_kullanim_ozeti(int(kart_id))

    @staticmethod
    def kredi_karti_sil(kart_id, *, onaylandi: bool = False, session=None) -> dict:
        """Yalnızca finansal geçmişi olmayan firma kredi kartı tanımını siler."""
        from database.kart_silme import kredi_karti_sil

        return kredi_karti_sil(int(kart_id), onaylandi=onaylandi, session=session)

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
        # Yansıma: 1. taksit = işlem tarihi (manuel sapma yok); taksitli aylar _ay_ekle ile
        ilk_taksit_tarihi = tarih
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
                from database.kk_taksit_islem_service import odeme_taksit_hareketlerini_sil

                odeme_taksit_hareketlerini_sil(session, eski)
                session.delete(eski)
                session.flush()

            kart_banka = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart_banka:
                raise ValueError("Banka kartı bulunamadı.")
            kk = session.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.id == int(kredi_karti_id))
            )
            if not kk or not kk.aktif:
                raise ValueError("Ödeme yapılacak kredi kartı bulunamadı veya pasif.")
            if kk.banka_karti_id != kart_banka.id:
                raise ValueError("Seçilen kart bu bankaya ait değil.")

            kk_hesap = None
            if getattr(kk, "bagli_hesap_id", None):
                kk_hesap = next(
                    (
                        h
                        for h in kart_banka.alt_hesaplar
                        if int(h.id) == int(kk.bagli_hesap_id)
                    ),
                    None,
                )
            if not kk_hesap:
                kk_hesap = FinansService.banka_alt_hesap(kart_banka, "KREDI_KARTI")
            if not kk_hesap:
                raise ValueError("Kredi kartı hesabı eksik — banka kartını kaydedin.")

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
            odeme.plan_versiyon = 1
            for satir in plan:
                session.add(
                    KrediKartiOdemeTaksit(
                        odeme_id=odeme.id,
                        taksit_no=satir["taksit_no"],
                        vade_tarihi=satir["vade_tarihi"],
                        tutar=satir["tutar"],
                        durum="BEKLIYOR",
                        ekstre_kesim_tarihi=satir.get("ekstre_kesim_tarihi"),
                        banka_vade_tarihi=satir.get("banka_vade_tarihi"),
                        odenen_tutar=Decimal("0.00"),
                        plan_versiyon=1,
                        aktif=True,
                    )
                )
            session.flush()
            from database.kk_taksit_islem_service import odeme_ilk_taksiti_isle
            from database.muhasebe_entegrasyon import muhasebe_hook

            odeme_ilk_taksiti_isle(session, odeme)
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
    def kk_odeme_belge_coz(belge_no: str) -> str:
        """Kart hareketi / taksit satırı belgesini ana ``KrediKartiOdeme.belge_no``'ya çözer.

        Desteklenen girişler:
        - Ana ödeme: ``KKO-2026-0009``
        - Taksit hareketi: ``KKO-2026-0009-T1`` (``kk_hareket_belge_no`` veya ``{ana}-T{n}``)
        Yalnız metin kesmekle kalmaz; kayıtlı taksit / ödeme ilişkisi kullanılır.
        """
        bn = (belge_no or "").strip()
        if not bn:
            raise ValueError("Belge no gerekli.")
        taban_re = re.compile(r"^(.+)-T(\d+)$")
        with get_session() as session:
            o = session.scalar(
                select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == bn)
            )
            if o is not None:
                return o.belge_no
            t = session.scalar(
                select(KrediKartiOdemeTaksit)
                .where(KrediKartiOdemeTaksit.kk_hareket_belge_no == bn)
                .options(selectinload(KrediKartiOdemeTaksit.odeme))
            )
            if t is not None and t.odeme is not None:
                return t.odeme.belge_no
            m = taban_re.match(bn)
            if m:
                ana, tno = m.group(1), int(m.group(2))
                t2 = session.scalar(
                    select(KrediKartiOdemeTaksit)
                    .join(KrediKartiOdeme, KrediKartiOdemeTaksit.odeme_id == KrediKartiOdeme.id)
                    .where(
                        KrediKartiOdeme.belge_no == ana,
                        KrediKartiOdemeTaksit.taksit_no == tno,
                    )
                    .options(selectinload(KrediKartiOdemeTaksit.odeme))
                )
                if t2 is not None and t2.odeme is not None:
                    return t2.odeme.belge_no
                o2 = session.scalar(
                    select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == ana)
                )
                if o2 is not None:
                    return o2.belge_no
        raise ValueError("KK ödeme fişi bulunamadı.")

    @staticmethod
    def kredi_karti_odeme_getir(belge_no: str) -> dict:
        from database.models.cari import Cari

        belge_no = FinansService.kk_odeme_belge_coz(belge_no)
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
                "gider_kart_odeme_id": int(o.gider_kart_odeme_id) if o.gider_kart_odeme_id else None,
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
    def kredi_karti_bekleyen_taksitler(
        banka_karti_id, limit=200, *, kredi_karti_id: int | None = None
    ):
        with get_session() as session:
            q = (
                select(KrediKartiOdemeTaksit)
                .join(KrediKartiOdeme)
                .where(
                    KrediKartiOdeme.banka_karti_id == int(banka_karti_id),
                    KrediKartiOdeme.durum == "AÇIK",
                    KrediKartiOdemeTaksit.durum == "BEKLIYOR",
                )
                .options(
                    selectinload(KrediKartiOdemeTaksit.odeme).selectinload(
                        KrediKartiOdeme.kredi_karti
                    )
                )
                .order_by(KrediKartiOdemeTaksit.vade_tarihi, KrediKartiOdemeTaksit.id)
                .limit(limit)
            )
            if kredi_karti_id is not None:
                q = q.where(KrediKartiOdeme.kredi_karti_id == int(kredi_karti_id))
            sonuc = []
            for t in session.scalars(q).all():
                if getattr(t, "aktif", True) is False:
                    continue
                if (t.durum or "").upper() == "PLAN_IPTAL":
                    continue
                o = t.odeme
                son_odeme = getattr(t, "banka_vade_tarihi", None)
                kesim = None
                # Hesap kesim = kart takviminden; vade/yansıma kesim sütununa yazılmaz
                if o and o.kredi_karti:
                    try:
                        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

                        donem = KrediKartiEkstreService.taksit_kesimi(o, t, o.kredi_karti)
                        if donem:
                            kesim = donem.get("kesim_tarihi")
                            son_odeme = son_odeme or donem.get("son_odeme_tarihi")
                    except Exception:
                        kayitli = getattr(t, "ekstre_kesim_tarihi", None)
                        if kayitli is not None:
                            try:
                                from database.kredi_karti_ekstre_service import (
                                    KrediKartiEkstreService,
                                )

                                if KrediKartiEkstreService.kesim_gecerli_mi(
                                    kayitli, o.kredi_karti
                                ):
                                    kesim = kayitli
                            except Exception:
                                pass
                from database.kk_taksit_islem_service import taksit_durum_etiket

                sonuc.append({
                    "belge_no": o.belge_no if o else "",
                    "odeme_id": int(o.id) if o else None,
                    "taksit_id": int(t.id),
                    "kart": o.kredi_karti.kart_adi if o and o.kredi_karti else "",
                    "kredi_karti_id": int(o.kredi_karti_id)
                    if o and o.kredi_karti_id
                    else None,
                    "taksit_no": t.taksit_no,
                    "taksit_sayisi": o.taksit_sayisi if o else 0,
                    # vade = taksit vadesi (karta yansıma)
                    "vade_tarihi": t.vade_tarihi,
                    "yansima_tarihi": t.vade_tarihi,
                    "banka_vade_tarihi": getattr(t, "banka_vade_tarihi", None),
                    "ekstre_kesim_tarihi": kesim,
                    "son_odeme_tarihi": son_odeme,
                    "kk_hareket_belge_no": getattr(t, "kk_hareket_belge_no", None) or "",
                    "odenen_tutar": Decimal(str(getattr(t, "odenen_tutar", None) or 0)),
                    "tutar": Decimal(str(t.tutar)),
                    "durum": t.durum,
                    "durum_etiket": taksit_durum_etiket(t.durum),
                    "kaynak": getattr(o, "kaynak_turu", None) or "CARI",
                })
        # Planlanan nakit avans (henüz karta yansımamış) — aynı bekleyen listede
        try:
            from database.nakit_avans_service import NakitAvansService

            for t in NakitAvansService.planlanan_bekleyenler(
                banka_karti_id=int(banka_karti_id),
                kredi_karti_id=int(kredi_karti_id) if kredi_karti_id is not None else None,
                limit=limit,
            ):
                sonuc.append(t)
        except Exception:
            pass
        sonuc.sort(
            key=lambda r: (
                r.get("vade_tarihi") or date.max,
                int(r.get("taksit_id") or 0),
            )
        )
        return sonuc[: int(limit)]

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
    def banka_kredileri(banka_karti_id=None, aktif_only=True, durum_filtre=None):
        """durum_filtre: None | 'KULLANDIRILDI' | 'KAPALI' | 'PASIF' | 'IPTAL' | 'TUMU'."""
        with get_session() as session:
            from database.banka_kredi_service import BankaKrediService

            BankaKrediService.schema_hazirla()
            q = (
                select(BankaKredisi)
                .options(selectinload(BankaKredisi.taksitler))
                .order_by(BankaKredisi.kullandirim_tarihi.desc(), BankaKredisi.id.desc())
            )
            if banka_karti_id:
                bid = int(banka_karti_id)
                hesap_idler = list(
                    session.scalars(
                        select(FinansHesabi.id).where(
                            FinansHesabi.banka_karti_id == bid,
                            FinansHesabi.alt_hesap_turu == "KREDILER",
                        )
                    ).all()
                )
                if hesap_idler:
                    q = q.where(
                        (BankaKredisi.banka_karti_id == bid)
                        | (BankaKredisi.bagli_hesap_id.in_(hesap_idler))
                    )
                else:
                    q = q.where(BankaKredisi.banka_karti_id == bid)
            filtre = (durum_filtre or "").strip().upper()
            if filtre and filtre != "TUMU":
                if filtre == "PASIF":
                    q = q.where(
                        (BankaKredisi.aktif.is_(False))
                        | (BankaKredisi.durum == "PASIF")
                    )
                else:
                    q = q.where(BankaKredisi.durum == filtre)
            elif aktif_only and not filtre:
                q = q.where(BankaKredisi.durum == "KULLANDIRILDI")
            return list(session.scalars(q).all())

    @staticmethod
    def _kredi_kalan_anapara(kredi, session=None) -> Decimal:
        """Kredi kalan anaparası = açık satırlarda (plan anapara − ödenen anapara).

        Açık durumlar: BEKLIYOR / YAKLASIYOR / VADESI_GECTI / KISMEN_ODENDI.
        Kısmen ödenmiş taksitte yalnızca kalan anapara sayılır; faiz/masraf
        ve toplam taksit tutarı eklenmez. Ödenen anapara okunamazsa satır
        ödenmiş sayılmaz (tam plan anaparası kalır).
        Plan yoksa bağlı KREDILER hesabı ledger bakiyesinin mutlak değeri.
        """
        acik = {"BEKLIYOR", "YAKLASIYOR", "VADESI_GECTI", "KISMEN_ODENDI"}
        kalan = Decimal("0")
        for t in kredi.taksitler or []:
            if (t.durum or "").upper() not in acik:
                continue
            try:
                ana = Decimal(str(t.anapara if t.anapara is not None else 0))
            except (InvalidOperation, TypeError, ValueError):
                continue
            try:
                odenen_ana = Decimal(
                    str(
                        t.odenen_anapara
                        if getattr(t, "odenen_anapara", None) is not None
                        else 0
                    )
                )
            except (InvalidOperation, TypeError, ValueError):
                odenen_ana = Decimal("0")
            fark = ana - odenen_ana
            if fark > 0:
                kalan += fark
        if kalan > 0 or (kredi.taksitler or []):
            return kalan.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        bagli_id = getattr(kredi, "bagli_hesap_id", None)
        if not bagli_id:
            return Decimal("0")
        if session is not None:
            hesap = session.get(FinansHesabi, int(bagli_id))
        else:
            with get_session() as s:
                hesap = s.get(FinansHesabi, int(bagli_id))
        if not hesap:
            return Decimal("0")
        return abs(FinansService.bakiye(hesap)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def banka_kredi_kalan_anapara_haritasi() -> tuple[dict[int, Decimal], set[int]]:
        """``(banka_id → pozitif kalan anapara, kredi kaydı olan banka id seti)``.

        Bankalar «Krediler» kolonu ile Ana Kart «Kalan anapara» aynı kaynaktır.
        Kredi kartı nakit avansı / KMH bu toplama girmez.
        """
        with get_session() as session:
            krediler = session.scalars(
                select(BankaKredisi).options(selectinload(BankaKredisi.taksitler))
            ).all()
            harita: dict[int, Decimal] = {}
            kredi_olan: set[int] = set()
            for k in krediler:
                bid = int(k.banka_karti_id)
                kredi_olan.add(bid)
                kalan = FinansService._kredi_kalan_anapara(k, session)
                if kalan <= 0:
                    continue
                harita[bid] = harita.get(bid, Decimal("0")) + kalan
            for bid in list(harita):
                harita[bid] = FinansService._para_sifirla(harita[bid])
            return harita, kredi_olan

    @staticmethod
    def banka_kredi_borc_gosterim(
        banka_karti_id: int,
        *,
        kalan_harita: dict[int, Decimal] | None = None,
        kredi_olan: set[int] | None = None,
    ) -> Decimal | None:
        """Bankalar Krediler kolonu: plan kalan anapara borcu (negatif).

        Kaynak pozitif; işaret bir kez çevrilir. Kredi kaydı yoksa ``None``
        (çağıran ledger yedeğine düşer — sahte borç üretmez).
        """
        if kalan_harita is None or kredi_olan is None:
            kalan_harita, kredi_olan = FinansService.banka_kredi_kalan_anapara_haritasi()
        bid = int(banka_karti_id)
        if bid not in kredi_olan:
            return None
        kalan = Decimal(str(kalan_harita.get(bid, Decimal("0"))))
        if kalan < 0:
            return FinansService._para_sifirla(kalan)
        return FinansService._para_sifirla(-kalan)

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
            kalan_anapara = FinansService._kredi_kalan_anapara(k, session)
            plan_eksik = not (k.taksitler or [])
            taksitler = [
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
                for t in sorted(k.taksitler or [], key=lambda x: (x.taksit_no or 0, x.id or 0))
            ]
            gosterim = FinansService._kredi_taksit_tutari_gosterim(taksitler, plan_eksik=plan_eksik)
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
                "bagli_hesap_id": getattr(k, "bagli_hesap_id", None),
                "plan_eksik": plan_eksik,
                "kalan_anapara": kalan_anapara,
                "taksit_tutari": gosterim["tutar"],
                "taksit_tutari_etiket": gosterim["etiket"],
                "taksit_tutari_degisken": gosterim["degisken"],
                "taksitler": taksitler,
            }

    @staticmethod
    def _kredi_taksit_tutari_gosterim(
        taksitler: list[dict], *, plan_eksik: bool = False
    ) -> dict:
        """Gerçek ödeme planından taksit tutarı; anaparayı bölen tahmini üretmez.

        Sabit planda ortak tutar; değişkende sıradaki ödenmemiş taksit.
        Plan yoksa tutar None (UI «Plan yok» / «—»).
        """
        if plan_eksik or not taksitler:
            return {"tutar": None, "etiket": "Plan yok", "degisken": False}
        # Ödenmiş / iptal taksitleri ayıkla; kalanlar üzerinden sabit/değişken ayrımı
        bekleyen = [
            t
            for t in taksitler
            if (t.get("durum") or "").upper() not in {"ODENDI", "ÖDENDİ", "IPTAL", "İPTAL", "PLAN_IPTAL"}
            and not t.get("odeme_tarihi")
        ]
        kaynak = bekleyen or list(taksitler)
        tutarlar = [
            Decimal(str(t.get("toplam") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for t in kaynak
        ]
        if not tutarlar:
            return {"tutar": None, "etiket": "—", "degisken": False}
        ilk = tutarlar[0]
        if all(t == ilk for t in tutarlar):
            return {"tutar": ilk, "etiket": "", "degisken": False}
        # Değişken: sıradaki (en küçük taksit_no) ödenmemiş
        siradaki = min(kaynak, key=lambda x: (int(x.get("taksit_no") or 0), int(x.get("id") or 0)))
        tutar = Decimal(str(siradaki.get("toplam") or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        no = siradaki.get("taksit_no") or "?"
        return {
            "tutar": tutar,
            "etiket": f"sıradaki (T{no})",
            "degisken": True,
        }

    @staticmethod
    def banka_kredileri_eslestir(*, yaz: bool = False) -> dict:
        """KREDILER alt hesaplarından BankaKredisi tanımı oluştur / bağla.

        Yeni kullandırım, ödeme veya taksit planı üretmez. Ledger bakiyesi değişmez.
        """
        from database.banka_kredi_service import BankaKrediService

        if yaz:
            yazma_zorunlu("finans_duzenleme")
        BankaKrediService.schema_hazirla()
        rapor = {
            "eslesen": [],
            "olusturulan": [],
            "zaten_bagli": [],
            "eslesmeyen_hesap": [],
            "yazim": bool(yaz),
        }
        with get_session() as session:
            hesaplar = list(
                session.scalars(
                    select(FinansHesabi)
                    .where(FinansHesabi.alt_hesap_turu == "KREDILER")
                    .options(selectinload(FinansHesabi.hareketler))
                ).all()
            )
            krediler = list(session.scalars(select(BankaKredisi)).all())
            by_bagli = {
                int(k.bagli_hesap_id): k
                for k in krediler
                if getattr(k, "bagli_hesap_id", None)
            }
            for h in hesaplar:
                ad = (h.hesap_adi or "").casefold()
                yer = "— krediler hesabı" in ad or ad.endswith("krediler hesabı")
                bak = FinansService.bakiye(h)
                if yer and abs(bak) <= Decimal("0.005"):
                    continue
                if int(h.id) in by_bagli:
                    k = by_bagli[int(h.id)]
                    degisti = False
                    if int(k.banka_karti_id) != int(h.banka_karti_id or 0):
                        if yaz:
                            k.banka_karti_id = int(h.banka_karti_id)
                        degisti = True
                    rapor["zaten_bagli" if not degisti else "eslesen"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "kredi_id": int(k.id),
                            "belge_no": k.belge_no,
                            "islem": "bagli_guncelle" if degisti else "ok",
                        }
                    )
                    continue
                # Ada göre mevcut kredi
                norm = FinansService._kk_ad_normalize(h.hesap_adi or "")
                aday = None
                for k in krediler:
                    if getattr(k, "bagli_hesap_id", None):
                        continue
                    if FinansService._kk_ad_benzerlik(h.hesap_adi or "", k.kredi_adi or "") >= 0.75:
                        aday = k
                        break
                    if FinansService._kk_ad_normalize(k.kredi_adi or "") == norm:
                        aday = k
                        break
                if aday is not None:
                    if yaz:
                        aday.bagli_hesap_id = int(h.id)
                        aday.banka_karti_id = int(h.banka_karti_id)
                    rapor["eslesen"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "kredi_id": int(aday.id),
                            "belge_no": aday.belge_no,
                            "islem": "tanim_bagla",
                        }
                    )
                    continue
                # Yeni tanım — hareket/taksit YOK
                acilis = Decimal(str(h.acilis_bakiyesi or 0))
                gozlenen = abs(bak)
                ana = abs(acilis) if acilis != 0 else gozlenen
                har_tarihler = sorted(
                    {x.tarih for x in (h.hareketler or []) if x.tarih}
                )
                kull_tar = har_tarihler[0] if har_tarihler else date.today()
                durum = "KULLANDIRILDI" if gozlenen > Decimal("0.005") else "KAPALI"
                belge = f"EVB-KR-H{int(h.id)}"
                if yaz:
                    # Belge çakışmasın
                    mevcut_belge = session.scalar(
                        select(BankaKredisi).where(BankaKredisi.belge_no == belge)
                    )
                    if mevcut_belge:
                        mevcut_belge.bagli_hesap_id = int(h.id)
                        mevcut_belge.banka_karti_id = int(h.banka_karti_id)
                        rapor["eslesen"].append(
                            {
                                "hesap_id": int(h.id),
                                "hesap_adi": h.hesap_adi,
                                "kredi_id": int(mevcut_belge.id),
                                "belge_no": belge,
                                "islem": "belge_bagla",
                            }
                        )
                        continue
                    k = BankaKredisi(
                        belge_no=belge,
                        banka_karti_id=int(h.banka_karti_id),
                        kredi_adi=(h.hesap_adi or "Kredi")[:120],
                        kredi_turu="ISLETME",
                        ana_para=ana,
                        toplam_faiz=Decimal("0"),
                        toplam_masraf=Decimal("0"),
                        taksit_sayisi=0,
                        kullandirim_tarihi=kull_tar,
                        ilk_taksit_tarihi=kull_tar,
                        odeme_hesap_turu="MEVDUAT",
                        bagli_hesap_id=int(h.id),
                        durum=durum,
                        aktif=bool(h.aktif),
                        para_birimi=getattr(h, "para_birimi", None) or "TRY",
                        aciklama=(
                            "Otomatik eşleme: mevcut KREDILER hesabından. "
                            "Ödeme planı kaynakta yok — varsayımsal taksit üretilmedi. "
                            "Kullandırım/ödeme fişi yazılmadı. "
                            f"Gözlenen ledger bakiye {gozlenen}."
                        )[:500],
                    )
                    session.add(k)
                    session.flush()
                    rapor["olusturulan"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "kredi_id": int(k.id),
                            "belge_no": belge,
                            "ana_para": str(ana),
                            "kalan_ledger": str(gozlenen),
                            "islem": "tanim_olustur",
                        }
                    )
                else:
                    rapor["eslesmeyen_hesap"].append(
                        {
                            "hesap_id": int(h.id),
                            "hesap_adi": h.hesap_adi,
                            "banka_karti_id": int(h.banka_karti_id or 0),
                            "bakiye": str(bak),
                            "ana_para_aday": str(ana),
                        }
                    )
            if yaz:
                session.commit()
        return rapor

    @staticmethod
    def banka_kredi_hesap_hareketleri(
        banka_karti_id,
        *,
        kredi_id: int | None = None,
        baslangic: date | None = None,
        bitis: date | None = None,
        limit: int = 800,
        sadece_eslesmesiz: bool = False,
    ) -> list[dict]:
        """KREDILER hesap hareketleri + kredi eşleme.

        ``kredi_id`` verilirse yalnız o kredinin ``bagli_hesap_id`` hareketleri
        (veya belge_no / ödeme ile o krediye bağlı olanlar) döner.
        Eşleşmemiş hareketler seçili krediye ait gibi gösterilmez; ``sadece_eslesmesiz``
        ile ayrı listelenir.
        """
        with get_session() as session:
            from database.banka_kredi_service import BankaKrediService

            BankaKrediService.schema_hazirla()
            kart = session.scalar(
                select(BankaKarti)
                .where(BankaKarti.id == int(banka_karti_id))
                .options(selectinload(BankaKarti.alt_hesaplar))
            )
            if not kart:
                return []
            hesaplar = [
                h
                for h in (kart.alt_hesaplar or [])
                if (h.alt_hesap_turu or "").upper() == "KREDILER"
            ]
            if not hesaplar:
                return []
            hesap_idler = [int(h.id) for h in hesaplar]
            hesap_ad = {int(h.id): h.hesap_adi for h in hesaplar}
            krediler = list(
                session.scalars(
                    select(BankaKredisi).where(
                        (BankaKredisi.banka_karti_id == int(banka_karti_id))
                        | (BankaKredisi.bagli_hesap_id.in_(hesap_idler))
                    )
                ).all()
            )
            bagli_map = {
                int(k.bagli_hesap_id): k
                for k in krediler
                if getattr(k, "bagli_hesap_id", None)
            }
            belge_map = {
                (k.belge_no or "").strip().upper(): k
                for k in krediler
                if (k.belge_no or "").strip()
            }
            secili = None
            if kredi_id is not None and not sadece_eslesmesiz:
                secili = session.get(BankaKredisi, int(kredi_id))
                if secili is None or int(secili.banka_karti_id) != int(banka_karti_id):
                    return []
                bagli = getattr(secili, "bagli_hesap_id", None)
                if bagli:
                    hesap_idler = [int(bagli)]
            q = (
                select(FinansHareketi)
                .where(FinansHareketi.hesap_id.in_(hesap_idler))
                .order_by(FinansHareketi.tarih.desc(), FinansHareketi.id.desc())
                .limit(int(limit))
            )
            if baslangic:
                q = q.where(FinansHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FinansHareketi.tarih <= bitis)
            sonuc = []
            for har in session.scalars(q).all():
                hid = int(har.hesap_id)
                kr = bagli_map.get(hid)
                bel = (har.belge_no or "").strip().upper()
                if kr is None and bel:
                    kr = belge_map.get(bel)
                isaret = FinansService.hareket_isareti(har.hareket_turu)
                esleme_bekliyor = kr is None
                kid = int(kr.id) if kr else None
                if sadece_eslesmesiz:
                    if not esleme_bekliyor:
                        continue
                elif kredi_id is not None and kid != int(kredi_id):
                    continue
                sonuc.append(
                    {
                        "id": int(har.id),
                        "hesap_id": hid,
                        "hesap_adi": hesap_ad.get(hid, ""),
                        "tarih": har.tarih,
                        "hareket_turu": har.hareket_turu,
                        "belge_no": har.belge_no or "",
                        "tutar": Decimal(str(har.tutar or 0)),
                        "isaret": isaret,
                        "aciklama": har.aciklama or "",
                        "kredi": kr.kredi_adi if kr else "",
                        "kredi_id": kid,
                        "esleme_bekliyor": esleme_bekliyor,
                    }
                )
            return sonuc

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
    def banka_kredi_bekleyen_taksitler(
        banka_karti_id,
        *,
        kredi_id: int | None = None,
        durumlar: tuple[str, ...] | None = None,
        limit=300,
    ):
        """Bekleyen (veya verilen durumdaki) taksitler — isteğe bağlı tek ``kredi_id``.

        ``plan_sira`` / ``plan_adet``: o kredinin planındaki sıra (1..N); banka
        ``taksit_no`` alanı ayrı döner (ör. 17–24 kalan planda 1/8…8/8).
        """
        with get_session() as session:
            durum_kume = {
                (d or "").strip().upper()
                for d in (durumlar or ("BEKLIYOR", "YAKLASIYOR", "VADESI_GECTI", "KISMEN_ODENDI"))
            }
            q = (
                select(BankaKrediTaksit)
                .join(BankaKredisi)
                .where(
                    BankaKredisi.banka_karti_id == int(banka_karti_id),
                    BankaKrediTaksit.durum.in_(sorted(durum_kume)),
                )
                .options(
                    selectinload(BankaKrediTaksit.kredi).selectinload(BankaKredisi.taksitler)
                )
                .order_by(BankaKrediTaksit.vade_tarihi, BankaKrediTaksit.id)
                .limit(limit)
            )
            if kredi_id is not None:
                q = q.where(BankaKredisi.id == int(kredi_id))
            else:
                q = q.where(BankaKredisi.durum == "KULLANDIRILDI")
            sonuc = []
            for t in session.scalars(q).all():
                k = t.kredi
                if k is None:
                    continue
                anapara = Decimal(str(t.anapara))
                faiz = Decimal(str(t.faiz or 0))
                masraf = Decimal(str(t.masraf or 0))
                plan = sorted(
                    (x for x in (k.taksitler or []) if (x.durum or "").upper() != "IPTAL"),
                    key=lambda x: (int(x.taksit_no or 0), int(x.id or 0)),
                )
                plan_adet = len(plan)
                plan_sira = next(
                    (i + 1 for i, x in enumerate(plan) if int(x.id) == int(t.id)),
                    int(t.taksit_no or 0),
                )
                sonuc.append({
                    "taksit_id": t.id,
                    "kredi_id": int(k.id),
                    "belge_no": k.belge_no or "",
                    "kredi_adi": k.kredi_adi or "",
                    "taksit_no": int(t.taksit_no or 0),
                    "taksit_sayisi": int(k.taksit_sayisi or plan_adet or 0),
                    "plan_sira": plan_sira,
                    "plan_adet": plan_adet or int(k.taksit_sayisi or 0),
                    "durum": t.durum or "",
                    "vade_tarihi": t.vade_tarihi,
                    "anapara": anapara,
                    "faiz": faiz,
                    "masraf": masraf,
                    "toplam": anapara + faiz + masraf,
                    "odeme_hesap_turu": k.odeme_hesap_turu if k else "MEVDUAT",
                })
            return sonuc

    @staticmethod
    def banka_kredi_taksitleri(
        kredi_id: int,
        *,
        durumlar: tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Tek kredinin taksitleri (bekleyen + ödenmiş); kredi kimliği zorunlu."""
        k = None
        with get_session() as session:
            k = session.get(BankaKredisi, int(kredi_id))
            if k is None:
                return []
            banka_id = int(k.banka_karti_id)
        return FinansService.banka_kredi_bekleyen_taksitler(
            banka_id,
            kredi_id=int(kredi_id),
            durumlar=durumlar
            or (
                "BEKLIYOR",
                "YAKLASIYOR",
                "VADESI_GECTI",
                "KISMEN_ODENDI",
                "ODENDI",
                "ERKEN_KAPATILDI",
            ),
            limit=limit,
        )

    @staticmethod
    def banka_kredi_taksit_detay(taksit_id) -> dict:
        """Taksit ödeme UI için plan + kalan bileşenler (liste ile aynı hesap)."""
        from database.banka_kredi_service import BILESEN_ALANLARI, BankaKrediService

        with get_session() as session:
            t = session.scalar(
                select(BankaKrediTaksit)
                .where(BankaKrediTaksit.id == int(taksit_id))
                .options(
                    selectinload(BankaKrediTaksit.kredi).selectinload(
                        BankaKredisi.taksitler
                    )
                )
            )
            if not t or not t.kredi:
                raise ValueError("Taksit bulunamadı.")

            plan = BankaKrediService.taksit_bilesenleri(t)
            odenmis = BankaKrediService._odenen_bilesenler(session, t.id)
            kalan_bilesen = {
                alan: max(Decimal("0.00"), plan.get(alan, Decimal("0")) - odenmis[alan])
                for alan in BILESEN_ALANLARI
            }
            # Legacy masraf alanı: plan masraf − ödenen masraf bileşenleri
            plan_masraf = Decimal(str(t.masraf or 0))
            odenen_masraf = BankaKrediService._d(
                getattr(t, "odenen_masraf", None) or 0, "Ödenen masraf"
            )
            kalan_masraf = max(Decimal("0.00"), plan_masraf - odenen_masraf)
            odenen_tutar = BankaKrediService._d(t.odenen_tutar or 0, "Ödenen tutar")
            kalan = BankaKrediService._taksit_kalan(t)
            # Ekran sırası 1..N (banka taksit_no 17–24 olabilir → 17/8 hatası olmasın)
            plan_satir = sorted(
                (
                    x
                    for x in (t.kredi.taksitler or [])
                    if (x.durum or "").upper() != "IPTAL"
                ),
                key=lambda x: (int(x.taksit_no or 0), int(x.id or 0)),
            )
            plan_adet = len(plan_satir) or int(t.kredi.taksit_sayisi or 0)
            plan_sira = next(
                (i + 1 for i, x in enumerate(plan_satir) if int(x.id) == int(t.id)),
                int(t.taksit_no or 0),
            )
            return {
                "taksit_id": t.id,
                "kredi_id": t.kredi.id,
                "kredi_adi": t.kredi.kredi_adi,
                "taksit_no": t.taksit_no,
                "taksit_sayisi": int(t.kredi.taksit_sayisi or plan_adet or 0),
                "plan_sira": plan_sira,
                "plan_adet": plan_adet,
                "vade_tarihi": t.vade_tarihi,
                # Ödeme önizlemesi: kalan tutarlar (kısmi ödemede faiz/masraf kalır)
                "anapara": kalan_bilesen["anapara"],
                "faiz": kalan_bilesen["faiz"],
                "masraf": kalan_masraf,
                "toplam": kalan if kalan > 0 else BankaKrediService.taksit_toplam(kalan_bilesen),
                "plan_anapara": plan["anapara"],
                "plan_faiz": plan["faiz"],
                "plan_masraf": plan_masraf,
                "plan_toplam": plan["toplam"],
                "odenen_tutar": odenen_tutar,
                "odenen_anapara": odenmis["anapara"],
                "kalan": kalan,
                "odeme_hesap_turu": t.kredi.odeme_hesap_turu or "MEVDUAT",
                "durum": t.durum,
                "odeme_belge_no": t.odeme_belge_no or "",
                "gider_belge_no": t.gider_belge_no or "",
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
        from database.hesap_siralama import hesaplari_sirala

        with get_session() as session:
            hesaplar = list(
                session.scalars(
                    select(FinansHesabi)
                    .options(selectinload(FinansHesabi.hareketler), selectinload(FinansHesabi.banka_karti))
                    .where(FinansHesabi.aktif.is_(True))
                    .order_by(FinansHesabi.id)
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
            return hesaplari_sirala(sonuc)

    @staticmethod
    def gider_fisi_listele(limit=300):
        from database.models.hizmet import HizmetKarti

        with get_session() as session:
            fisler = list(
                session.scalars(
                    select(GiderFisi)
                    .options(selectinload(GiderFisi.finans_hesap))
                    .where(GiderFisi.gider_turu.in_(("HIZMET", "POS_KOMISYON", "POS_KESINTI")))
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
    def gider_evraklari_listele(limit: int = 8000) -> list[dict]:
        """Hizmet alış (GIDER) faturaları + HIZMET/POS gider fişleri — birleşik liste satırları.

        Aynı sayısal kimlik karışmasın diye ``kayit_turu`` + ``kayit_id`` ile tanımlanır.
        Yeni fatura üretmez; yalnızca mevcut kayıtları okur.

        ``cari`` = ekrandaki «Cari / Hizmet» (hizmet/açıklama veya fatura carisi metni).
        ``cari_hesap`` = gerçek cari kart etiketi (yoksa «—»); POS tahsilat müşterisi kullanılmaz.
        ``para_birimi`` = gösterim (TL…); ``para_birimi_kod`` = TRY/USD…
        """
        from database.hizmet_faturasi_service import HizmetFaturasiService
        from database.gider_kart_odeme_service import gider_fisi_mahsup_toplami
        from database.gider_fisi_liste_service import gider_fisi_cari_coz
        from database.models.hizmet import HizmetKarti
        from database.models.finans import GiderKartOdeme, KrediKartiOdeme
        from database.teklif_customer_view import para_birimi_etiket

        limit = max(1, min(int(limit or 8000), 20000))
        satirlar: list[dict] = []

        for kayit in HizmetFaturasiService.listele("GIDER"):
            f = kayit["fatura"]
            genel = _decimal(kayit.get("genel_toplam"), "toplam", Decimal("0"))
            odenen = _decimal(getattr(f, "odeme_tutari", 0) or 0, "odenen", Decimal("0"))
            if odenen < 0:
                odenen = Decimal("0.00")
            kalan = max(Decimal("0.00"), (genel - odenen).quantize(Decimal("0.01")))
            cari_ad = f"{f.cari.cari_kodu} - {f.cari.unvan}" if getattr(f, "cari", None) else "—"
            pb_kod = (getattr(f, "para_birimi", None) or "TRY").strip().upper() or "TRY"
            if pb_kod in ("TL", "YTL"):
                pb_kod = "TRY"
            cari_idler = [int(f.cari_id)] if getattr(f, "cari_id", None) else []
            satirlar.append(
                {
                    "kayit_turu": "HIZMET_FATURA",
                    "kayit_id": int(f.id),
                    "belge_no": f.fatura_no,
                    "belge_turu": "Hizmet Alış",
                    "olusturma_kaynagi": "",
                    "tarih": f.fatura_tarihi,
                    "cari": cari_ad,
                    "cari_hesap": cari_ad if cari_idler else "—",
                    "cari_idler": cari_idler,
                    "cari_coklu": False,
                    "toplam": genel,
                    "odenen": odenen,
                    "kalan": kalan,
                    "para_birimi_kod": pb_kod,
                    "para_birimi": para_birimi_etiket(pb_kod),
                    "durum": f.durum or "",
                    "odeme_belge_no": "",
                    "gider_kart_odeme_id": None,
                }
            )

        with get_session() as session:
            fisler = list(
                session.scalars(
                    select(GiderFisi)
                    .options(selectinload(GiderFisi.finans_hesap))
                    .where(GiderFisi.gider_turu.in_(("HIZMET", "POS_KOMISYON", "POS_KESINTI")))
                    .order_by(GiderFisi.tarih.desc(), GiderFisi.id.desc())
                    .limit(limit)
                ).all()
            )
            hizmet_ids = {int(f.hizmet_id) for f in fisler if f.hizmet_id}
            hizmetler = {
                h.id: h
                for h in session.scalars(
                    select(HizmetKarti).where(HizmetKarti.id.in_(hizmet_ids or [-1]))
                ).all()
            }
            gko_map: dict[int, GiderKartOdeme] = {}
            for g in session.scalars(
                select(GiderKartOdeme).where(
                    GiderKartOdeme.gider_fisi_id.in_([int(f.id) for f in fisler] or [-1]),
                    GiderKartOdeme.durum == "AÇIK",
                )
            ).all():
                gko_map[int(g.gider_fisi_id)] = g
            kk_ids = {int(g.kk_odeme_id) for g in gko_map.values() if g.kk_odeme_id}
            kk_map = {
                int(k.id): k
                for k in session.scalars(
                    select(KrediKartiOdeme).where(KrediKartiOdeme.id.in_(kk_ids or [-1]))
                ).all()
            }
            for fis in fisler:
                hiz = hizmetler.get(int(fis.hizmet_id)) if fis.hizmet_id else None
                tur_u = (fis.gider_turu or "").upper()
                # «Cari / Hizmet» sütunu: hizmet veya açıklama (tahsilat müşterisi değil)
                if tur_u in ("POS_KOMISYON", "POS_KESINTI"):
                    cari_ad = fis.aciklama or (
                        "POS komisyon" if tur_u == "POS_KOMISYON" else "POS kesinti"
                    )
                else:
                    cari_ad = (
                        f"{hiz.hizmet_kodu} - {hiz.hizmet_adi}" if hiz else (fis.aciklama or "—")
                    )
                # Gerçek cari kart — POS tahsilat carisi kullanılmaz
                cari_coz = gider_fisi_cari_coz(session, fis)
                toplam = _decimal(fis.tutar, "tutar", Decimal("0.01"))
                if (fis.durum or "") == "IPTAL":
                    odenen = Decimal("0.00")
                    kalan = Decimal("0.00")
                    durum = "IPTAL"
                    kaynak = ""
                    odeme_no = fis.bagli_belge_no or ""
                    gko_id = None
                elif tur_u in ("POS_KOMISYON", "POS_KESINTI"):
                    # POS bakiyesinden düşüldü; ayrı ödeme/mahsup yok
                    odenen = toplam
                    kalan = Decimal("0.00")
                    durum = "KAPALI"
                    kaynak = "POS"
                    odeme_no = fis.bagli_belge_no or ""
                    gko_id = None
                else:
                    mahsup = gider_fisi_mahsup_toplami(session, int(fis.id))
                    odenen = mahsup
                    kalan = max(Decimal("0.00"), (toplam - mahsup).quantize(Decimal("0.01")))
                    durum = "KAPALI" if kalan == 0 and mahsup > 0 else "AÇIK"
                    g = gko_map.get(int(fis.id))
                    gko_id = int(g.id) if g is not None else None
                    ko = kk_map.get(int(g.kk_odeme_id)) if g is not None and g.kk_odeme_id else None
                    odeme_no = (ko.belge_no if ko else None) or (fis.bagli_belge_no or "")
                    kaynak = "Kart" if g is not None or (odeme_no or "").upper().startswith("KKO") else "Manuel"
                if tur_u == "POS_KOMISYON":
                    belge_turu = "POS Komisyon"
                elif tur_u == "POS_KESINTI":
                    belge_turu = "POS Kesinti"
                else:
                    belge_turu = "Gider Fişi"
                hesap = fis.finans_hesap
                pb_kod = "TRY"
                if hesap is not None:
                    pb_kod = (getattr(hesap, "para_birimi", None) or "TRY").strip().upper() or "TRY"
                    if pb_kod in ("TL", "YTL"):
                        pb_kod = "TRY"
                satirlar.append(
                    {
                        "kayit_turu": "GIDER_FISI",
                        "kayit_id": int(fis.id),
                        "belge_no": fis.belge_no,
                        "belge_turu": belge_turu,
                        "olusturma_kaynagi": kaynak,
                        "tarih": fis.tarih,
                        "cari": cari_ad,
                        "cari_hesap": cari_coz.get("cari_etiket") or "—",
                        "cari_idler": list(cari_coz.get("cari_idler") or []),
                        "cari_coklu": bool(cari_coz.get("coklu")),
                        "cari_detay": list(cari_coz.get("cari_detay") or []),
                        "toplam": toplam,
                        "odenen": odenen,
                        "kalan": kalan,
                        "para_birimi_kod": pb_kod,
                        "para_birimi": para_birimi_etiket(pb_kod),
                        "durum": durum,
                        "odeme_belge_no": odeme_no or "",
                        "gider_kart_odeme_id": gko_id,
                        "kaynak_pos_valor_id": getattr(fis, "kaynak_pos_valor_id", None),
                    }
                )

        satirlar.sort(
            key=lambda s: (
                s["tarih"] or date.min,
                0 if s["kayit_turu"] == "HIZMET_FATURA" else 1,
                -int(s["kayit_id"]),
            ),
            reverse=True,
        )
        return satirlar[:limit]

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

        belge_no = (veriler.get("belge_no") or "").strip() or FinansService._finans_belge_no(
            session, "GDF"
        )
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

    @staticmethod
    def gider_fisi_guncelle(fisi_id: int, veriler: dict) -> GiderFisi:
        """Mevcut gider fişini aynı kimlikle günceller.

        Kart ödemesi tutarını değiştirmez. Tutar değişirse mahsup/kalan fiş tarafında
        yeniden hesaplanır; mahsup toplamının altına inilemez.
        """
        yazma_zorunlu("finans_duzenleme", "duzenleme")
        from database.gider_kart_odeme_service import fis_karta_bagli_mi, gider_fisi_mahsup_toplami
        from database.masraf_dagitim_service import KAYNAK_GIDER_FISI, MasrafDagitimService
        from database.models.hizmet import HizmetHareketi, HizmetKarti
        from database.muhasebe_entegrasyon import muhasebe_hook

        MasrafDagitimService.kilit_kontrol(kaynak_id=int(fisi_id), kaynak_turu=KAYNAK_GIDER_FISI)
        with get_session() as session:
            fis = session.get(GiderFisi, int(fisi_id))
            if fis is None:
                raise ValueError("Gider fişi bulunamadı.")
            if (fis.durum or "") == "IPTAL":
                raise ValueError("İptal edilmiş gider fişi düzenlenemez.")
            if (fis.gider_turu or "") != "HIZMET":
                raise ValueError("Bu fiş buradan düzenlenemez.")

            tarih = veriler.get("tarih", fis.tarih)
            if isinstance(tarih, str):
                raise ValueError("Tarih geçersiz.")
            if tarih > date.today():
                raise ValueError("Tarih gelecek olamaz.")

            hizmet_id = int(veriler["hizmet_id"]) if veriler.get("hizmet_id") is not None else int(fis.hizmet_id or 0)
            if not hizmet_id:
                raise ValueError("Gider hizmet kartı seçin.")
            hizmet = session.get(HizmetKarti, hizmet_id)
            if not hizmet or not hizmet.aktif:
                raise ValueError("Gider hizmet kartı seçin.")
            if (hizmet.hizmet_turu or "").upper() != "GIDER":
                raise ValueError("Yalnızca gider hizmet kartı seçilebilir.")

            yeni_tutar = _decimal(veriler.get("tutar", fis.tutar), "Tutar", Decimal("0.01"))
            mahsup = gider_fisi_mahsup_toplami(session, int(fis.id))
            if yeni_tutar < mahsup:
                raise ValueError(
                    f"Tutar ({yeni_tutar} TL) mahsup edilen tutarın ({mahsup} TL) altına inemez. "
                    "Kart ödeme tutarı bu ekrandan değişmez."
                )
            if fis_karta_bagli_mi(session, int(fis.id)) and yeni_tutar != _decimal(fis.tutar, "eski", Decimal("0")):
                # Kart borcu / KKO tutarı korunur; yalnız gider fişi tutarı güncellenir.
                pass

            aciklama = (veriler.get("aciklama") if "aciklama" in veriler else fis.aciklama) or None
            if isinstance(aciklama, str):
                aciklama = aciklama.strip() or None
            acik = aciklama or f"{hizmet.hizmet_kodu} — {hizmet.hizmet_adi}"

            eski_tutar = _decimal(fis.tutar, "eski", Decimal("0"))
            fis.tarih = tarih
            fis.hizmet_id = hizmet.id
            fis.tutar = yeni_tutar
            fis.aciklama = acik

            # Bağlı hizmet hareketini aynı belge no ile senkron tut
            har = session.scalar(
                select(HizmetHareketi).where(
                    HizmetHareketi.belge_no == fis.belge_no,
                    HizmetHareketi.hareket_turu == "GİDER FİŞİ",
                )
            )
            if har is not None:
                har.tarih = tarih
                har.hizmet_id = hizmet.id
                har.birim_fiyat = yeni_tutar
                har.tutar = yeni_tutar
                har.kdv_orani = Decimal(str(hizmet.kdv_orani or 0))
                har.aciklama = acik

            # Kasa/banka çıkışlı (kartsız) fişte finans hareket tutarını güncelle
            if not fis_karta_bagli_mi(session, int(fis.id)) and fis.finans_hesap_id:
                fh = session.scalar(
                    select(FinansHareketi).where(
                        FinansHareketi.belge_no == fis.belge_no,
                        FinansHareketi.hareket_turu == "GİDER FİŞİ",
                    )
                )
                if fh is not None and eski_tutar != yeni_tutar:
                    hesap = session.scalar(
                        select(FinansHesabi)
                        .where(FinansHesabi.id == int(fis.finans_hesap_id))
                        .options(
                            selectinload(FinansHesabi.hareketler),
                            selectinload(FinansHesabi.banka_karti),
                        )
                    )
                    if hesap is not None:
                        fark = yeni_tutar - eski_tutar
                        if fark > 0:
                            FinansService.cikis_kontrol(hesap, fark, kart=hesap.banka_karti)
                        fh.tutar = yeni_tutar
                        fh.tarih = tarih
                        fh.aciklama = acik

            session.flush()
            muhasebe_hook("gider_fisi_fisi", int(fis.id), session=session)
        return FinansService.gider_fisi_getir(int(fisi_id))

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
    def kasa_makbuz_makbuz_no_ile(makbuz_no: str):
        """Kullanıcıya görünen makbuz no (MKB-00046) ile kayıt bulur."""
        from database.models.cari import Cari

        makbuz_no = (makbuz_no or "").strip()
        if not makbuz_no:
            return None
        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .options(
                    selectinload(KasaMakbuzu.finans_hesap),
                    selectinload(KasaMakbuzu.satirlar).selectinload(KasaMakbuzSatiri.finans_hesap),
                )
                .where(KasaMakbuzu.makbuz_no == makbuz_no)
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
                ilk_taksit = s.get("ilk_taksit_tarihi")
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
                        "ilk_taksit_tarihi": ilk_taksit,
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
    def sirket_kredi_kartlari(*, include_ids: list[int] | None = None, ara: str | None = None) -> list[dict]:
        """Tedarikçi ödemesinde seçilebilecek firma kredi kartı tanımları.

        Yalnız ``KrediKartiTanimi`` döner (mevduat/KMH/POS/kredi alt hesapları yok).
        Aynı kart kimliği bir kez listelenir. ``include_ids`` ile geçmiş/pasif kart korunur.
        """
        from database.turkce_normalize import turkce_normalize

        ekstra = {int(x) for x in (include_ids or []) if x}
        with get_session() as session:
            kosul = [KrediKartiTanimi.aktif.is_(True)]
            if ekstra:
                kosul = [or_(KrediKartiTanimi.aktif.is_(True), KrediKartiTanimi.id.in_(list(ekstra)))]
            kartlar = session.scalars(
                select(KrediKartiTanimi)
                .where(*kosul)
                .options(selectinload(KrediKartiTanimi.banka_karti))
                .order_by(KrediKartiTanimi.kart_adi)
            ).all()
            bagli_idler = {
                int(k.bagli_hesap_id)
                for k in kartlar
                if getattr(k, "bagli_hesap_id", None)
            }
            bagli_adlar: dict[int, str] = {}
            if bagli_idler:
                for h in session.scalars(
                    select(FinansHesabi).where(FinansHesabi.id.in_(list(bagli_idler)))
                ).all():
                    bagli_adlar[int(h.id)] = (h.hesap_adi or "").strip()
            ara_n = turkce_normalize(ara or "")
            sonuc: list[dict] = []
            gorulen: set[int] = set()
            for k in kartlar:
                kid = int(k.id)
                if kid in gorulen:
                    continue
                gorulen.add(kid)
                banka = (k.banka_karti.banka_adi if k.banka_karti else "") or ""
                son4 = (k.son_dort_hane or "").strip()
                maske = f"****{son4}" if son4 else ""
                # Kaynak/kart kodu: tanım adındaki «02 …» (Evo önek) korunur
                kaynak = (k.kart_adi or "").strip()
                bagli_ad = bagli_adlar.get(int(k.bagli_hesap_id)) if k.bagli_hesap_id else ""
                if bagli_ad and turkce_normalize(bagli_ad) != turkce_normalize(kaynak):
                    kaynak_ek = bagli_ad
                else:
                    kaynak_ek = ""
                etiket_parca = []
                if banka:
                    etiket_parca.append(banka)
                if kaynak:
                    etiket_parca.append(kaynak)
                if kaynak_ek and kaynak_ek not in etiket_parca:
                    etiket_parca.append(f"[{kaynak_ek}]")
                if maske:
                    etiket_parca.append(maske)
                if not k.aktif:
                    etiket_parca.append("(Pasif)")
                etiket = " · ".join(etiket_parca) if etiket_parca else f"Kart #{kid}"
                if ara_n:
                    havuz = turkce_normalize(" ".join([banka, kaynak, kaynak_ek, maske, etiket]))
                    if ara_n not in havuz:
                        continue
                sonuc.append(
                    {
                        "id": kid,
                        "etiket": etiket,
                        "kart_adi": kaynak,
                        "banka_adi": banka,
                        "kaynak_kodu": kaynak_ek or kaynak,
                        "son_dort_hane": son4 or None,
                        "banka_karti_id": k.banka_karti_id,
                        "bagli_hesap_id": getattr(k, "bagli_hesap_id", None),
                        "aktif": bool(k.aktif),
                    }
                )
            sonuc.sort(
                key=lambda x: (
                    turkce_normalize(x.get("banka_adi") or ""),
                    turkce_normalize(x.get("kart_adi") or ""),
                    x["id"],
                )
            )
            return sonuc

    @staticmethod
    def sirket_kredi_karti_dogrula(kredi_karti_id: int, *, pasif_izin: bool = False) -> KrediKartiTanimi:
        """Ödeme kaydında seçilen kaydın gerçek firma KK tanımı olduğunu doğrular."""
        with get_session() as session:
            kk = session.scalar(
                select(KrediKartiTanimi)
                .where(KrediKartiTanimi.id == int(kredi_karti_id))
                .options(selectinload(KrediKartiTanimi.banka_karti))
            )
            if kk is None:
                raise ValueError("Seçilen kayıt firma kredi kartı tanımı değil.")
            if not kk.aktif and not pasif_izin:
                raise ValueError(f"{kk.kart_adi}: kart pasif; yeni ödemede kullanılamaz.")
            # Session dışına taşı
            session.expunge(kk)
            return kk

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

        istek_anahtari = (veriler.get("istek_anahtari") or "").strip() or None

        with get_session() as session:
            from database.sube_service import SubeService

            sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            cari = session.get(Cari, cari_id)
            if cari is None:
                raise ValueError("Cari hesap seçin.")

            if istek_anahtari and not makbuz_id:
                eski_istek = session.scalar(
                    select(KasaMakbuzu).where(
                        KasaMakbuzu.istek_anahtari == istek_anahtari,
                        KasaMakbuzu.durum != "IPTAL",
                    )
                )
                if eski_istek is not None:
                    return int(eski_istek.id)

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
                    kk_id = s.get("kredi_karti_id")
                    if not kk_id:
                        raise ValueError(
                            f"Satır {s['sira_no']}: firma kredi kartı seçin (mevduat/KMH/POS kabul edilmez)."
                        )
                    kk = session.get(KrediKartiTanimi, int(kk_id))
                    # Düzenlemede bağlı pasif kart korunur; yeni satırda aktif zorunlu
                    pasif_izin = bool(makbuz_id)
                    if not kk:
                        raise ValueError(
                            f"Satır {s['sira_no']}: seçilen kimlik firma kredi kartı tanımı değil."
                        )
                    if not kk.aktif and not pasif_izin:
                        raise ValueError(
                            f"Satır {s['sira_no']}: {kk.kart_adi} pasif; yeni ödemede kullanılamaz."
                        )
                    kk_hesap = None
                    if getattr(kk, "bagli_hesap_id", None):
                        kk_hesap = session.get(FinansHesabi, int(kk.bagli_hesap_id))
                    if kk_hesap is None or (kk_hesap.alt_hesap_turu or "").upper() != "KREDI_KARTI":
                        kk_hesap = session.scalar(
                            select(FinansHesabi).where(
                                FinansHesabi.banka_karti_id == kk.banka_karti_id,
                                FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                                FinansHesabi.aktif.is_(True),
                            )
                        )
                    if kk_hesap is None:
                        kk_hesap = session.scalar(
                            select(FinansHesabi).where(
                                FinansHesabi.banka_karti_id == kk.banka_karti_id,
                                FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                            )
                        )
                    if not kk_hesap:
                        raise ValueError(
                            f"Satır {s['sira_no']}: kartın bankasında kredi kartı hesabı yok — banka kartını kaydedin."
                        )
                    if (kk_hesap.alt_hesap_turu or "").upper() != "KREDI_KARTI":
                        raise ValueError(
                            f"Satır {s['sira_no']}: bağlı hesap kredi kartı değil (mevduat/KMH/POS olamaz)."
                        )
                    sekil_n = (s.get("odeme_sekli") or "").replace("İ", "I").replace("ı", "i").upper()
                    if "TAHSILAT" in sekil_n or "GELEN" in sekil_n:
                        raise ValueError(
                            f"Satır {s['sira_no']}: ödeme makbuzunda tahsilat şekli kullanılamaz."
                        )
                    if not (s.get("odeme_sekli") or "").strip() or (
                        ("SIRKET" in sekil_n or "FIRMA" in sekil_n or "ODEME" in sekil_n)
                        and "KART" in sekil_n
                    ):
                        s["odeme_sekli"] = "KREDİ KARTIYLA ÖDEME — FİRMA KARTI"
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
                    if not hesap.banka_karti_id:
                        raise ValueError(
                            f"Satır {s['sira_no']}: «{hesap.hesap_adi}» bir banka kartına bağlı değil — "
                            "POS hesabını banka kartından kaydedin."
                        )
                    kart = session.scalar(
                        select(BankaKarti)
                        .where(BankaKarti.id == int(hesap.banka_karti_id))
                        .options(
                            selectinload(BankaKarti.alt_hesaplar),
                            selectinload(BankaKarti.pos_taksit_komisyonlari),
                        )
                    )
                    # Aktarım hedefi MEVDUAT veya KMH olabilir (pos_aktarim_hesap_id / tür).
                    # Yalnızca KMH aramak Enpara 002 gibi mevduat hedefli kartlarda hatalı engel üretirdi.
                    hedef = FinansService._pos_hedef_hesap(kart) if kart else None
                    if not kart or not hedef:
                        banka_ad = (kart.banka_adi if kart else "") or "—"
                        pos_ad = (hesap.hesap_adi or "").strip() or "POS"
                        raise ValueError(
                            f"Satır {s['sira_no']}: «{pos_ad}» (banka: {banka_ad}) için "
                            "aktarım hesabı (mevduat veya KMH) eksik — banka kartında "
                            "«Aktarımın yatacağı hesap» bağlantısını kaydedin."
                        )
                    cozulmus.append((s, hesap, "POS", (kart, hedef)))
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
                if istek_anahtari:
                    makbuz.istek_anahtari = istek_anahtari
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
                    istek_anahtari=istek_anahtari,
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
        sekil = s.get("odeme_sekli") or ""
        alt = (hesap.alt_hesap_turu or "").upper()
        hesap_turu = (hesap.hesap_turu or "").upper()
        no = s["sira_no"]
        if tur == "ODEME" and sekil_turu == "KART":
            # Firma kartı yolu kredi_karti_id ile ayrı çözülür; buraya POS/mevduat düşmesin
            raise ValueError(
                f"Satır {no}: firma kartı ödemesinde kasa/banka/POS hesabı seçilemez; firma kredi kartı seçin."
            )
        if tur == "ODEME" and ("GELEN" in sekil.upper().replace("İ", "I") or "TAHSILAT" in sekil.upper().replace("İ", "I")):
            raise ValueError(
                f"Satır {no}: ödeme makbuzunda tahsilat şekli (Gelen Havale / KK Tahsilat) kullanılamaz."
            )
        if sekil_turu == "KASA" and hesap_turu != "KASA":
            raise ValueError(f"Satır {no}: nakit satırı için kasa hesabı seçin.")
        if sekil_turu == "HAVALE" and alt not in ("MEVDUAT", "KMH"):
            raise ValueError(f"Satır {no}: havale satırı için mevduat veya KMH hesabı seçin.")
        if sekil_turu == "HAVALE" and tur == "ODEME" and alt == "POS":
            raise ValueError(f"Satır {no}: gönderilen havale için POS hesabı seçilemez.")
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
        try:
            from database.pos_komisyon_gider_service import PosKomisyonGiderService

            PosKomisyonGiderService.senkronize(session, kayit, kesin=False)
        except Exception:
            pass
        return kayit

    @staticmethod
    def _makbuz_kk_yaz(session, s, kk_hesap, kk, belge_no, cari_id, sube_id, aciklama) -> KrediKartiOdeme:
        """Makbuzdaki şirket kartıyla ödeme: taksit planı + 1. taksiti karta işle; limit kontrolü.

        Ana fiş tutarı cariye makbuzda bir kez yazılır. Kart hesabına tam tutar tek satır
        yazılmaz; her taksit yansıma tarihinde ``{odeme}-Tn`` belge no ile işlenir.
        """
        brut = s["tutar"]
        n = int(s.get("taksit_sayisi") or 1)
        if n < 1 or n > KK_MAX_TAKSIT:
            raise ValueError(f"Satır {s['sira_no']}: taksit sayısı 1-{KK_MAX_TAKSIT} arasında olmalıdır.")
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from database.kk_taksit_islem_service import odeme_ilk_taksiti_isle

        try:
            KrediKartiEkstreService.limit_kontrol(session, kk, brut)
        except ValueError as hata:
            raise ValueError(f"{kk.kart_adi}: {hata}") from hata
        tarih = s["tarih"]
        ilk = s.get("ilk_taksit_tarihi")
        if isinstance(ilk, str):
            try:
                ilk = datetime.strptime(ilk.strip(), "%d.%m.%Y").date()
            except ValueError:
                ilk = None
        plan = FinansService.kk_taksit_plani(tarih, n, brut, ilk_taksit_tarihi=ilk, kart=kk)
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
                    banka_vade_tarihi=satir.get("banka_vade_tarihi"),
                    odenen_tutar=Decimal("0.00"),
                    plan_versiyon=1,
                    aktif=True,
                )
            )
        session.flush()
        odeme_ilk_taksiti_isle(session, odeme, sube_id=sube_id)
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
        from database.kk_taksit_islem_service import odeme_taksit_hareketlerini_sil

        for ko in kk_odemeleri:
            odeme_taksit_hareketlerini_sil(session, ko)
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

    @staticmethod
    def kasa_makbuz_silme_ozeti(makbuz_id) -> dict:
        """Kalıcı silme onay metni için özet (yazmaz)."""
        from database.models.cari import Cari

        FinansService.fatura_makbuz_bag_tablosu_hazirla()
        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .options(selectinload(KasaMakbuzu.satirlar))
                .where(KasaMakbuzu.id == int(makbuz_id))
            )
            if makbuz is None:
                raise ValueError("Makbuz bulunamadı.")
            cari = session.get(Cari, makbuz.cari_id) if makbuz.cari_id else None
            pos_kayitlari, kk_odemeleri = FinansService._makbuz_bagli_kayitlar(session, makbuz)
            bag = FinansService._fatura_bagi(session, makbuz.id)
            aktarilan = [
                pv for pv in pos_kayitlari
                if (pv.durum or "").upper() == "AKTARILDI"
                or Decimal(str(getattr(pv, "gercek_yatis_tutari", 0) or 0)) > Decimal("0.005")
            ]
            etkiler = [
                f"Makbuz {makbuz.makbuz_no or makbuz.belge_no} veritabanından kalıcı silinir (IPTAL satırı kalmaz)",
                f"Belge no {makbuz.belge_no} yeniden kullanılmaz",
                "Cari tahsilat/ödeme ve fatura kapamaları çözülür",
                f"{len(list(makbuz.satirlar or []))} tahsilat/ödeme satırı kaldırılır",
            ]
            if pos_kayitlari:
                etkiler.append(f"{len(pos_kayitlari)} POS kaydı (komisyon/net) kaldırılır")
            if aktarilan:
                etkiler.append(
                    f"{len(aktarilan)} KMH/valör aktarımı önce geri alınır, sonra POS silinir"
                )
            if kk_odemeleri:
                etkiler.append(f"{len(kk_odemeleri)} şirket kartı ödeme satırı kaldırılır")
            return {
                "makbuz_id": int(makbuz.id),
                "belge_no": makbuz.belge_no,
                "makbuz_no": makbuz.makbuz_no,
                "tarih": makbuz.tarih,
                "tutar": Decimal(str(makbuz.tutar or 0)),
                "makbuz_turu": makbuz.makbuz_turu,
                "durum": makbuz.durum,
                "cari": (
                    f"{cari.cari_kodu} — {cari.unvan}" if cari else "—"
                ),
                "satir_sayisi": len(list(makbuz.satirlar or [])),
                "pos_sayisi": len(pos_kayitlari),
                "kk_odeme_sayisi": len(kk_odemeleri),
                "aktarim_sayisi": len(aktarilan),
                "bagli_fatura": bag.fatura_no if bag else None,
                "etkilenecek": etkiler,
                "kalici": True,
            }

    @staticmethod
    def kasa_makbuz_kalici_sil(makbuz_id, *, neden: str, istek_anahtari: str | None = None) -> dict:
        """Makbuzu ve yalnız ona ait mali etkileri veritabanından kalıcı siler.

        Valörü KMH'ye aktarılmış POS varsa önce aktarım geri alınır; ardından POS/KK/cari
        etkileri ve makbuz satırları silinir. IPTAL bayrağı / ters fiş üretilmez.
        """
        from database.gider_kart_odeme_service import _belge_no_rezerve_et
        from database.muhasebe_entegrasyon import muhasebe_hook
        from database.odeme_sozu_service import OdemeSozuService

        yazma_zorunlu("finans_duzenleme", "iptal")
        if not (neden or "").strip():
            raise ValueError("Silme nedeni yazın.")
        neden = neden.strip()[:300]
        ozet = FinansService.kasa_makbuz_silme_ozeti(int(makbuz_id))
        FinansService.fatura_makbuz_bag_tablosu_hazirla()

        # Aktarılmış POS: önce banka/KMH etkisini geri al (ayrı transaction — mevcut API)
        with get_session() as session:
            makbuz0 = session.scalar(
                select(KasaMakbuzu)
                .options(selectinload(KasaMakbuzu.satirlar))
                .where(KasaMakbuzu.id == int(makbuz_id))
            )
            if makbuz0 is None:
                raise ValueError("Makbuz bulunamadı (zaten silinmiş olabilir).")
            pos0, _kk0 = FinansService._makbuz_bagli_kayitlar(session, makbuz0)
            aktar_idler = [
                int(pv.id)
                for pv in pos0
                if (pv.durum or "").upper() == "AKTARILDI"
                or Decimal(str(getattr(pv, "gercek_yatis_tutari", 0) or 0)) > Decimal("0.005")
            ]
        for pid in aktar_idler:
            FinansService.pos_aktarim_geri_al(
                pid, gerekce=f"Makbuz kalıcı silme: {ozet['belge_no']}"
            )

        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .options(selectinload(KasaMakbuzu.satirlar))
                .where(KasaMakbuzu.id == int(makbuz_id))
            )
            if makbuz is None:
                raise ValueError("Makbuz bulunamadı (zaten silinmiş olabilir).")
            belge = makbuz.belge_no
            makbuz_no = makbuz.makbuz_no
            # Ödenmiş kart taksiti hâlâ engel (aktarım geri alındıktan sonra da)
            _pos, kk_odemeleri = FinansService._makbuz_bagli_kayitlar(session, makbuz)
            for ko in kk_odemeleri:
                if any((t.durum or "") == "ODENDI" for t in (ko.taksitler or [])):
                    raise ValueError(
                        f"{ko.belge_no} taksiti ekstrede ödendi; makbuz kalıcı silinemez."
                    )

            try:
                muhasebe_hook(
                    "kasa_makbuzu_iptal",
                    int(makbuz.id),
                    f"Makbuz kalıcı silindi {belge}",
                    session=session,
                )
            except Exception:
                pass

            # iptal=False → POS/KK satırlarını sil; cari/finans etkilerini kaldır
            FinansService._makbuz_etkilerini_geri_al(session, makbuz, iptal=False)
            OdemeSozuService.evrak_baglantilarini_iptal(
                session, belge, neden=f"Makbuz kalıcı silindi {belge}"
            )
            bag = FinansService._fatura_bagi(session, makbuz.id)
            if bag is not None:
                session.delete(bag)
            for satir in list(makbuz.satirlar or []):
                session.delete(satir)
            session.flush()
            session.delete(makbuz)
            session.flush()
            _belge_no_rezerve_et(session, belge, evrak_turu="MAKBUZ", neden=neden)
            if makbuz_no and makbuz_no != belge:
                _belge_no_rezerve_et(session, makbuz_no, evrak_turu="MAKBUZ_NO", neden=neden)
            session.flush()

        return {
            "makbuz_id": int(makbuz_id),
            "belge_no": ozet["belge_no"],
            "makbuz_no": ozet.get("makbuz_no"),
            "kalici": True,
            "neden": neden,
            "aktarim_geri_alindi": len(aktar_idler),
            "istek_anahtari": (istek_anahtari or "")[:64] or None,
        }

    @staticmethod
    def pos_valor_iptal(pv_id, *, neden: str = "") -> dict:
        """Makbuza bağlı olmayan POS tahsilatını iptal eder (cari + finans + bekleyen valör).

        Aktarılmış kayıtta önce ``pos_aktarim_geri_al`` uygulanır; ardından bekleyen net/komisyon
        etkileri kaldırılır ve kayıt IPTAL edilir. Tek veritabanı işlemi.
        """
        yazma_zorunlu("finans_duzenleme", "iptal")
        neden = (neden or "POS tahsilat iptal").strip() or "POS tahsilat iptal"
        with get_session() as session:
            pv = session.get(PosValorKaydi, int(pv_id))
            if pv is None:
                raise ValueError("POS tahsilat kaydı bulunamadı.")
            durum = (pv.durum or "").strip().upper()
            if durum in ("IPTAL", "İPTAL"):
                raise ValueError("POS tahsilatı zaten iptal.")
            bagli_satir = session.scalar(
                select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == int(pv.id))
            )
            if bagli_satir is not None:
                raise ValueError(
                    "Bu POS kaydı tahsilat makbuzuna bağlı; makbuz kartındaki Sil ile iptal edin."
                )
            akt = Decimal(str(pv.gercek_yatis_tutari or 0))
            if akt > Decimal("0.005") or (pv.aktarim_belge_no or "").strip():
                # Aynı session'da aktarım geri alma — dış API yeni session açtığı için inline
                tokenler = FinansService._pos_pva_tokenleri(pv)
                if akt > 0 and tokenler:
                    hedef_id = int(getattr(pv, "hedef_hesap_id", None) or pv.kmh_hesap_id)
                    pos_id = int(pv.pos_hesap_id)
                    for pva in tokenler:
                        pay = FinansService._pos_pva_kayit_payi(session, pv, pva)
                        if pay <= 0:
                            continue
                        FinansService._pos_pva_pay_geri_al(
                            session,
                            pva_belge=pva,
                            pos_hesap_id=pos_id,
                            hedef_hesap_id=hedef_id,
                            pay=pay,
                        )
                    pv.gercek_yatis_tutari = Decimal("0")
                    pv.gercek_yatis_tarihi = None
                    pv.aktarim_belge_no = None
                    pv.aktarim_zamani = None
                    pv.durum = "BEKLIYOR"
                    pv.banka_teyidi = False
                    session.flush()
                elif akt > Decimal("0.005"):
                    raise ValueError(
                        "POS tahsilatı bankaya aktarılmış; aktarım geri alınamadı. "
                        "Önce POS aktarımını geri alın."
                    )

            belge_no = (pv.belge_no or "").strip()
            from database.muhasebe_entegrasyon import muhasebe_hook
            from database.models.cari import CariIslem, SatisHareketi

            muhasebe_hook(
                "pos_tahsilat_iptal",
                int(pv.id),
                f"{neden} ({belge_no})",
                session=session,
            )
            try:
                from database.pos_komisyon_gider_service import PosKomisyonGiderService

                PosKomisyonGiderService.iptal(session, int(pv.id), neden=neden)
            except Exception:
                pass
            # Fatura no ile yazılmış POS (RAY-…): aynı belgede SatisHareketi varken
            # CariIslem silinirse defter satış satırını B+A ile geri basar ve toplamlar bozulur.
            # Bu durumda cari satırını silmek yerine tutarı sıfırla (maske kalır, kapama yoksa reopen yok).
            sh = None
            if pv.cari_id and belge_no:
                sh = session.scalar(
                    select(SatisHareketi).where(
                        SatisHareketi.belge_no == belge_no,
                        SatisHareketi.cari_id == int(pv.cari_id),
                    )
                )
            if sh is not None:
                for islem in list(
                    session.scalars(select(CariIslem).where(CariIslem.belge_no == belge_no)).all()
                ):
                    if pv.cari_id and int(islem.cari_id) != int(pv.cari_id):
                        continue
                    islem.borc = Decimal("0")
                    islem.alacak = Decimal("0")
                    notu = f"İPTAL: {neden}"
                    eski = (islem.aciklama or "").strip()
                    islem.aciklama = f"{eski} | {notu}".strip(" |") if eski else notu
                session.flush()
            else:
                FinansService._havale_cari_geri_al(session, belge_no)
            FinansService._finans_hareketlerini_sil(session, belge_no)
            # Bekleyen net/komisyon: aktif listeden düşür
            pv.durum = "IPTAL"
            session.flush()
            return {
                "pv_id": int(pv.id),
                "belge_no": belge_no,
                "brut": Decimal(str(pv.brut_tutar or 0)),
                "komisyon": Decimal(str(pv.komisyon_tutari or 0)),
                "net": Decimal(str(pv.net_tutar or 0)),
            }

    @staticmethod
    def tahsilat_detay_iptal(
        *,
        makbuz_id=None,
        pos_valor_id=None,
        cari_islem_id=None,
        neden: str = "",
    ) -> dict:
        """Tahsilat detay Sil: benzersiz kayıt kimliğiyle mevcut iptal akışına yönlendirir."""
        if makbuz_id is not None:
            FinansService.kasa_makbuz_iptal(int(makbuz_id))
            return {"tur": "makbuz", "id": int(makbuz_id)}
        if pos_valor_id is not None:
            ozet = FinansService.pos_valor_iptal(int(pos_valor_id), neden=neden)
            ozet["tur"] = "pos_valor"
            ozet["id"] = int(pos_valor_id)
            return ozet
        if cari_islem_id is not None:
            from database.cari_service import CariService

            CariService.tahsilat_odeme_iptal(
                int(cari_islem_id), (neden or "Tahsilat silindi").strip() or "Tahsilat silindi"
            )
            return {"tur": "cari_islem", "id": int(cari_islem_id)}
        raise ValueError("Silinecek kayıt kimliği belirtilmedi.")

    @staticmethod
    def tahsilat_detay_hedef_coz(belge_no: str, *, cari_id=None) -> dict:
        """Cari tahsilat satırından Sil hedefi: makbuz → POS valör → cari işlem (öncelik sırası)."""
        no = (belge_no or "").strip()
        if not no:
            raise ValueError("Belge numarası gerekli.")
        with get_session() as session:
            makbuz = session.scalar(
                select(KasaMakbuzu)
                .where(KasaMakbuzu.belge_no == no)
                .options(selectinload(KasaMakbuzu.satirlar))
            )
            if makbuz is not None and (makbuz.durum or "").upper() != "IPTAL":
                from database.models.cari import Cari

                cari = session.get(Cari, makbuz.cari_id) if makbuz.cari_id else None
                hesap = session.get(FinansHesabi, makbuz.finans_hesap_id) if makbuz.finans_hesap_id else None
                hesap_adi = hesap.hesap_adi if hesap else ""
                # Satırdaki POS hesabı daha doğru olabilir
                satir = next(iter(makbuz.satirlar or []), None)
                if satir and satir.finans_hesap_id:
                    h2 = session.get(FinansHesabi, satir.finans_hesap_id)
                    if h2:
                        hesap_adi = h2.hesap_adi or hesap_adi
                return {
                    "tur": "makbuz",
                    "id": int(makbuz.id),
                    "belge_no": makbuz.belge_no,
                    "makbuz_no": makbuz.makbuz_no,
                    "tarih": makbuz.tarih,
                    "tutar": Decimal(str(makbuz.tutar or 0)),
                    "cari": f"{cari.cari_kodu} — {cari.unvan}" if cari else "—",
                    "hesap": hesap_adi or "—",
                }
            pv_q = select(PosValorKaydi).where(PosValorKaydi.belge_no == no)
            if cari_id is not None:
                pv_q = pv_q.where(
                    or_(PosValorKaydi.cari_id == int(cari_id), PosValorKaydi.cari_id.is_(None))
                )
            pv = session.scalar(
                pv_q.where(
                    ~PosValorKaydi.durum.in_(("IPTAL", "İPTAL"))
                ).order_by(PosValorKaydi.id)
            )
            if pv is None:
                pv = session.scalar(
                    select(PosValorKaydi)
                    .where(PosValorKaydi.belge_no == no)
                    .order_by(PosValorKaydi.id)
                )
            if pv is not None and (pv.durum or "").upper() not in ("IPTAL", "İPTAL"):
                bagli = session.scalar(
                    select(KasaMakbuzSatiri).where(KasaMakbuzSatiri.pos_valor_id == int(pv.id))
                )
                if bagli is None:
                    from database.models.cari import Cari

                    cari = session.get(Cari, pv.cari_id) if pv.cari_id else None
                    hesap = session.get(FinansHesabi, pv.pos_hesap_id)
                    return {
                        "tur": "pos_valor",
                        "id": int(pv.id),
                        "belge_no": pv.belge_no,
                        "makbuz_no": None,
                        "tarih": pv.tahsilat_tarihi,
                        "tutar": Decimal(str(pv.brut_tutar or 0)),
                        "cari": f"{cari.cari_kodu} — {cari.unvan}" if cari else "—",
                        "hesap": (hesap.hesap_adi if hesap else None) or "—",
                    }
            from database.models.cari import Cari, CariIslem

            iq = select(CariIslem).where(
                CariIslem.belge_no == no,
                CariIslem.islem_turu.in_(("Tahsilat", "Ödeme")),
            )
            if cari_id is not None:
                iq = iq.where(CariIslem.cari_id == int(cari_id))
            islemler = list(session.scalars(iq.order_by(CariIslem.id)).all())
            islem = next(
                (
                    i
                    for i in islemler
                    if Decimal(str(i.alacak or 0)) + Decimal(str(i.borc or 0)) > 0
                ),
                None,
            )
            if islem is None:
                raise ValueError(f"{no} için silinebilir tahsilat/ödeme kaydı bulunamadı.")
            cari = session.get(Cari, islem.cari_id) if islem.cari_id else None
            tutar = Decimal(str(islem.alacak or 0)) or Decimal(str(islem.borc or 0))
            return {
                "tur": "cari_islem",
                "id": int(islem.id),
                "belge_no": islem.belge_no,
                "makbuz_no": None,
                "tarih": islem.tarih,
                "tutar": tutar,
                "cari": f"{cari.cari_kodu} — {cari.unvan}" if cari else "—",
                "hesap": islem.hesap_adi or "—",
            }


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

