from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import random
import shutil

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import BASE_DIR, get_session
from database.models.stok import (
    Depo,
    DepoTransferFisi,
    DepoTransferFisiSatiri,
    StokBarkod,
    StokBirim,
    StokFiyati,
    StokFiyatGecmisi,
    StokHareketi,
    StokKarti,
    StokLotu,
    StokPaketBilesen,
    StokPaketUretim,
    StokResmi,
    StokSecenek,
)
from database.satis_siparisi_service import decimal

GIRIS_HAREKETLERI = ("GİRİŞ", "FATURA GİRİŞ", "İADE GİRİŞ", "TRANSFER GİRİŞ", "PAKET GİRİŞ")
CIKIS_HAREKETLERI = ("FATURA ÇIKIŞ", "ÇIKIŞ", "TRANSFER ÇIKIŞ", "PAKET ÇIKIŞ")

STOK_SECENEK_TURLERI = (
    "rapor_grubu",
    "marka",
    "model",
    "fonksiyon1",
    "fonksiyon2",
    "renk",
    "raf_yeri",
    "birim",
    "kart_turu",
)

STOK_FIYAT_ADLARI = (
    "ALIŞ FİYATI",
    "FABRİKA FİYATI",
    "LİSTE FİYATI",
    "SPOT FİYATI",
    "İNTERNET FİYATI",
    "RAKİP FİYATI",
    "SATIŞ FİYATI 1",
    "SATIŞ FİYATI 2",
    "SATIŞ FİYATI 3",
    "SATIŞ FİYATI 4",
    "SATIŞ FİYATI 5",
    "SATIŞ FİYATI 6",
    "SATIŞ FİYATI 7",
    "SATIŞ FİYATI 8",
    "SATIŞ FİYATI 9",
    "SATIŞ FİYATI 10",
)

ALIŞ_FIYAT_ADLARI = (
    "ALIŞ FİYATI",
    "FABRİKA FİYATI",
    "LİSTE FİYATI",
    "SPOT FİYATI",
    "İNTERNET FİYATI",
    "RAKİP FİYATI",
)

SATIS_FIYAT_ADLARI = (
    "SATIŞ FİYATI 1",
    "SATIŞ FİYATI 2",
    "SATIŞ FİYATI 3",
    "SATIŞ FİYATI 4",
    "SATIŞ FİYATI 5",
    "SATIŞ FİYATI 6",
    "SATIŞ FİYATI 7",
    "SATIŞ FİYATI 8",
    "SATIŞ FİYATI 9",
    "SATIŞ FİYATI 10",
)

# Eski kayıt adlarını yeni kart alanlarına taşımak için
ESKI_FIYAT_ESLEME = {
    "ALIŞ FİYATI 1": "ALIŞ FİYATI",
    "ALIŞ FİYATI 2": "SPOT FİYATI",
    "ALIŞ FİYATI 3": "ALIŞ FİYATI",
    "ALIŞ FİYATI 4": "LİSTE FİYATI",
    "SPOT ALIŞ FİYATI": "SPOT FİYATI",
    "LİSTE ALIŞ FİYATI": "LİSTE FİYATI",
    "NET ALIŞ FİYATI": "ALIŞ FİYATI",
    "PERAKENDE": "SATIŞ FİYATI 1",
    "NAKİT": "SATIŞ FİYATI 2",
    "AÇIK HESAP": "SATIŞ FİYATI 3",
    "KREDİ KARTI": "SATIŞ FİYATI 4",
}


def net_alis_hesapla(liste_fiyat, iskonto_1=0, iskonto_2=0, iskonto_3=0) -> Decimal:
    """Liste fiyatına ardışık 3 iskonto uygulayarak fabrika alış fiyatı üretir.

    Örnek: 100 TL, %10 + %5 + %2 → 100 × 0.90 × 0.95 × 0.98
    """
    tutar = decimal(liste_fiyat or "0", "Liste fiyatı", Decimal("0"))
    for sira, deger in enumerate((iskonto_1, iskonto_2, iskonto_3), start=1):
        oran = decimal(deger or "0", f"{sira}. iskonto", Decimal("0"))
        if oran < 0 or oran > 100:
            raise ValueError(f"{sira}. iskonto 0-100 arasında olmalıdır.")
        tutar = tutar * (Decimal("1") - oran / Decimal("100"))
    return tutar.quantize(Decimal("0.0001"))


fabrika_fiyati_hesapla = net_alis_hesapla

KART_TURLERI = (
    "Ticari Mal",
    "Hammadde",
    "Yarı Mamul",
    "Mamul",
    "Sarf Malzeme",
    "Hizmet",
    "Demirbaş",
    "Paket",
)

RESIM_KLASORU = BASE_DIR / "data" / "stok_resimleri"

# İç kullanım / TR GS1 önekleri; varsayılan 869 (Türkiye)
EAN13_ONEK = "869"


def ean13_kontrol_hanesi(on_iki_hane: str) -> str:
    """EAN-13 kontrol hanesini hesaplar (ilk 12 hane verilmeli)."""
    if len(on_iki_hane) != 12 or not on_iki_hane.isdigit():
        raise ValueError("EAN-13 için 12 haneli sayısal gövde gerekir.")
    toplam = 0
    for i, karakter in enumerate(on_iki_hane):
        rakam = int(karakter)
        toplam += rakam if i % 2 == 0 else rakam * 3
    return str((10 - (toplam % 10)) % 10)


def ean13_dogrula(barkod: str) -> bool:
    barkod = (barkod or "").strip()
    if len(barkod) != 13 or not barkod.isdigit():
        return False
    return ean13_kontrol_hanesi(barkod[:12]) == barkod[12]


def ean13_uret(govde_12: str) -> str:
    govde_12 = (govde_12 or "").strip()
    return govde_12 + ean13_kontrol_hanesi(govde_12)


class StokService:
    @staticmethod
    def varsayilanlari_hazirla():
        RESIM_KLASORU.mkdir(parents=True, exist_ok=True)
        with get_session() as session:
            if not session.scalar(select(Depo).where(Depo.ad == "ANA DEPO")):
                session.add(Depo(ad="ANA DEPO"))
            baslangic = {
                "rapor_grubu": ("GENEL", "HAMMADDE", "MAMUL", "SARF"),
                "renk": ("BEYAZ", "SİYAH", "GRİ", "MAVİ", "KIRMIZI", "YEŞİL"),
            }
            for tur, degerler in baslangic.items():
                for ad in degerler:
                    mevcut = session.scalar(
                        select(StokSecenek).where(StokSecenek.tur == tur, StokSecenek.ad == ad)
                    )
                    if not mevcut:
                        session.add(StokSecenek(tur=tur, ad=ad))

    @staticmethod
    def secenekleri_listele(tur):
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokSecenek.ad).where(StokSecenek.tur == tur).order_by(StokSecenek.ad)
                ).all()
            )

    @staticmethod
    def secenek_ekle(tur, ad):
        ad = (ad or "").strip()
        if tur not in STOK_SECENEK_TURLERI:
            raise ValueError("Geçersiz seçenek türü.")
        if not ad:
            raise ValueError("Seçenek adı boş olamaz.")
        with get_session() as session:
            mevcut = session.scalar(
                select(StokSecenek).where(
                    StokSecenek.tur == tur,
                    func.lower(StokSecenek.ad) == ad.lower(),
                )
            )
            if mevcut:
                return mevcut.ad
            session.add(StokSecenek(tur=tur, ad=ad))
            session.flush()
            return ad

    @staticmethod
    def raf_omru_secenekleri():
        """Kayıtlı raf ömrü tarihlerini gg.aa.yyyy listesi olarak döndürür."""
        with get_session() as session:
            tarihler = list(
                session.scalars(
                    select(StokKarti.raf_omru)
                    .where(StokKarti.raf_omru.is_not(None))
                    .distinct()
                    .order_by(StokKarti.raf_omru.desc())
                ).all()
            )
            return [t.strftime("%d.%m.%Y") for t in tarihler if t]

    @staticmethod
    def kart_turu_secenekleri(varsayilanlar):
        ekstra = StokService.secenekleri_listele("kart_turu")
        return list(dict.fromkeys([*(varsayilanlar or []), *ekstra]))

    @staticmethod
    def _barkod_kullaniliyor_mu(session, barkod: str, haric_stok_id=None) -> bool:
        q1 = select(StokKarti.id).where(StokKarti.barkod == barkod)
        q2 = select(StokBarkod.id).where(StokBarkod.barkod == barkod)
        if haric_stok_id:
            q1 = q1.where(StokKarti.id != int(haric_stok_id))
            q2 = q2.where(StokBarkod.stok_id != int(haric_stok_id))
        return session.scalar(q1) is not None or session.scalar(q2) is not None

    @staticmethod
    def ean13_olustur(onek=EAN13_ONEK, stok_id=None, haric_barkodlar=None) -> str:
        """
        Benzersiz 13 haneli EAN-13 üretir.
        Varsayılan önek 869 (TR). Gövde: önek + artan sıra; son hane kontrol hanesi.
        """
        onek = (onek or EAN13_ONEK).strip()
        if not onek.isdigit() or not (1 <= len(onek) <= 7):
            raise ValueError("EAN-13 öneki 1-7 haneli sayı olmalıdır.")
        haric = {str(b).strip() for b in (haric_barkodlar or []) if str(b).strip()}
        govde_uzunluk = 12 - len(onek)
        if govde_uzunluk < 1:
            raise ValueError("EAN-13 öneki çok uzun.")
        maksimum = 10 ** govde_uzunluk

        with get_session() as session:
            mevcut_barkodlar = set(
                session.scalars(
                    select(StokBarkod.barkod).where(StokBarkod.barkod.like(f"{onek}%"))
                ).all()
            )
            mevcut_barkodlar.update(
                session.scalars(
                    select(StokKarti.barkod).where(
                        StokKarti.barkod.is_not(None),
                        StokKarti.barkod.like(f"{onek}%"),
                    )
                ).all()
            )
            mevcut_barkodlar |= haric
            max_sira = 0
            for barkod in mevcut_barkodlar:
                if not barkod or len(barkod) != 13 or not barkod.isdigit():
                    continue
                if not barkod.startswith(onek) or not ean13_dogrula(barkod):
                    continue
                try:
                    max_sira = max(max_sira, int(barkod[len(onek):12]))
                except ValueError:
                    continue
            baslangic = max_sira + 1
            if stok_id:
                baslangic = max(baslangic, (int(stok_id) % maksimum) or 1)
            for aday_sira in range(baslangic, min(baslangic + 10000, maksimum)):
                govde = f"{onek}{aday_sira:0{govde_uzunluk}d}"
                barkod = ean13_uret(govde)
                if barkod in mevcut_barkodlar:
                    continue
                if not StokService._barkod_kullaniliyor_mu(session, barkod, haric_stok_id=stok_id):
                    return barkod
            for _ in range(5000):
                aday_sira = random.randrange(1, maksimum)
                govde = f"{onek}{aday_sira:0{govde_uzunluk}d}"
                barkod = ean13_uret(govde)
                if barkod in mevcut_barkodlar:
                    continue
                if not StokService._barkod_kullaniliyor_mu(session, barkod, haric_stok_id=stok_id):
                    return barkod
        raise ValueError("Uygun boş EAN-13 bulunamadı. Önek veya aralığı kontrol edin.")

    @staticmethod
    def sonraki_ean13(company_code: str = "4201") -> str:
        return StokService.ean13_olustur()

    @staticmethod
    def depolar():
        with get_session() as session:
            return list(session.scalars(select(Depo).where(Depo.aktif.is_(True)).order_by(Depo.ad)).all())

    @staticmethod
    def depo_ekle(ad):
        ad = ad.strip().upper()
        if not ad:
            raise ValueError("Depo adı boş olamaz.")
        with get_session() as session:
            mevcut = session.scalar(select(Depo).where(func.lower(Depo.ad) == ad.lower()))
            if mevcut:
                return mevcut
            depo = Depo(ad=ad)
            session.add(depo)
            session.flush()
            return depo

    @staticmethod
    def _secenek_ekle(session, tur: str, ad: str) -> None:
        """StokSecenek ekler; Türkçe İ / unique çakışmalarında sessizce geçilir."""
        deger = (ad or "").strip()
        if not deger:
            return
        mevcut = session.scalar(
            select(StokSecenek).where(StokSecenek.tur == tur, StokSecenek.ad == deger)
        )
        if mevcut:
            return
        mevcut = session.scalar(
            select(StokSecenek).where(
                StokSecenek.tur == tur,
                func.lower(StokSecenek.ad) == deger.lower(),
            )
        )
        if mevcut:
            return
        try:
            with session.begin_nested():
                session.add(StokSecenek(tur=tur, ad=deger))
                session.flush()
        except IntegrityError:
            pass

    @staticmethod
    def _stok_yukle(session, stok_id=None, stok_kodu=None):
        q = select(StokKarti).options(
            selectinload(StokKarti.fiyatlar),
            selectinload(StokKarti.lotlar),
            selectinload(StokKarti.birimler),
            selectinload(StokKarti.resimler),
            selectinload(StokKarti.barkodlar),
            selectinload(StokKarti.fiyat_gecmisi),
        )
        if stok_id:
            return session.scalar(q.where(StokKarti.id == int(stok_id)))
        if stok_kodu:
            return session.scalar(q.where(StokKarti.stok_kodu == stok_kodu.strip()))
        return None

    @staticmethod
    def stok_getir(stok_id):
        with get_session() as session:
            return StokService._stok_yukle(session, stok_id=stok_id)

    @staticmethod
    def stoklari_ara(arama=""):
        with get_session() as session:
            q = (
                select(StokKarti)
                .where(StokKarti.aktif.is_(True))
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.lotlar),
                    selectinload(StokKarti.barkodlar),
                )
                .order_by(StokKarti.stok_adi)
            )
            if arama:
                ifade = f"%{arama}%"
                barkod_alt = select(StokBarkod.stok_id).where(StokBarkod.barkod.ilike(ifade))
                kosullar = [
                    StokKarti.stok_kodu.ilike(ifade),
                    StokKarti.barkod.ilike(ifade),
                    StokKarti.id.in_(barkod_alt),
                ]
                # Stok adı: en az 3 harf ile içeriden arama
                if len(arama.strip()) >= 3:
                    kosullar.append(StokKarti.stok_adi.ilike(ifade))
                q = q.where(or_(*kosullar))
            return list(session.scalars(q).all())

    @staticmethod
    def stoklari_filtrele(kod="", ad="", limit=250):
        """Ürün kodu ve/veya adı ile AND filtre (fatura satırı seçimi)."""
        kod = (kod or "").strip()
        ad = (ad or "").strip()
        with get_session() as session:
            q = (
                select(StokKarti)
                .where(StokKarti.aktif.is_(True))
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.lotlar),
                    selectinload(StokKarti.barkodlar),
                )
                .order_by(StokKarti.stok_adi)
            )
            if kod:
                q = q.where(StokKarti.stok_kodu.ilike(f"%{kod}%"))
            if ad:
                q = q.where(StokKarti.stok_adi.ilike(f"%{ad}%"))
            return list(session.scalars(q.limit(limit)).all())

    @staticmethod
    def stok_kodu_onerileri(metin, limit=40):
        metin = (metin or "").strip()
        if not metin:
            return []
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokKarti)
                    .where(
                        StokKarti.aktif.is_(True),
                        StokKarti.stok_kodu.ilike(f"%{metin}%"),
                    )
                    .order_by(StokKarti.stok_kodu)
                    .limit(limit)
                ).all()
            )

    @staticmethod
    def stok_adi_onerileri(metin, min_harf=3, limit=40):
        metin = (metin or "").strip()
        if len(metin) < min_harf:
            return []
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokKarti)
                    .where(
                        StokKarti.aktif.is_(True),
                        StokKarti.stok_adi.ilike(f"%{metin}%"),
                    )
                    .order_by(StokKarti.stok_adi)
                    .limit(limit)
                ).all()
            )

    @staticmethod
    def stok_ozeti(stok_id):
        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if not stok:
                return {
                    "toplam_giris": Decimal("0"),
                    "toplam_cikis": Decimal("0"),
                    "kalan": Decimal("0"),
                    "fifo_deger": Decimal("0"),
                }
            hareketler = list(
                session.scalars(select(StokHareketi).where(StokHareketi.stok_id == stok.id)).all()
            )
            toplam_giris = sum(
                (h.miktar for h in hareketler if h.hareket_turu in GIRIS_HAREKETLERI),
                Decimal("0"),
            )
            toplam_cikis = sum(
                (h.miktar for h in hareketler if h.hareket_turu in CIKIS_HAREKETLERI),
                Decimal("0"),
            )
            lotlar = list(session.scalars(select(StokLotu).where(StokLotu.stok_id == stok.id)).all())
            kalan = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
            fifo_deger = sum(
                (lot.kalan_miktar * lot.birim_maliyet for lot in lotlar),
                Decimal("0"),
            )
            return {
                "toplam_giris": toplam_giris,
                "toplam_cikis": toplam_cikis,
                "kalan": kalan,
                "fifo_deger": fifo_deger,
            }

    @staticmethod
    def fiyat_gecmisi(stok_id):
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokFiyatGecmisi)
                    .where(StokFiyatGecmisi.stok_id == int(stok_id))
                    .order_by(StokFiyatGecmisi.degisim_tarihi.desc(), StokFiyatGecmisi.id.desc())
                ).all()
            )

    @staticmethod
    def stok_hareketleri(stok_id, baslangic=None, bitis=None):
        with get_session() as session:
            q = (
                select(StokHareketi, Depo.ad, StokLotu.lot_no)
                .join(Depo, Depo.id == StokHareketi.depo_id)
                .outerjoin(StokLotu, StokLotu.id == StokHareketi.lot_id)
                .where(StokHareketi.stok_id == int(stok_id))
            )
            if baslangic:
                q = q.where(StokHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(StokHareketi.tarih <= bitis)
            q = q.order_by(StokHareketi.tarih.desc(), StokHareketi.id.desc())
            satirlar = []
            for hareket, depo_adi, lot_no in session.execute(q).all():
                satirlar.append(
                    {
                        "tarih": hareket.tarih,
                        "hareket_turu": hareket.hareket_turu,
                        "belge_no": hareket.belge_no,
                        "depo": depo_adi,
                        "lot_no": lot_no or "",
                        "miktar": hareket.miktar,
                        "birim_maliyet": hareket.birim_maliyet,
                        "tutar": hareket.miktar * hareket.birim_maliyet,
                    }
                )
            return satirlar

    @staticmethod
    def belge_bul(belge_no, hareket_turu):
        """Hareket türü ve belge no ile ilgili evrakı bulur. Dönüş: (tur, kayit_id|belge_no)."""
        belge_no = (belge_no or "").strip()
        if not belge_no:
            return None
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.models.satis_faturasi import SatisFaturasi
        from database.models.satis_iade_faturasi import SatisIadeFaturasi

        with get_session() as session:
            if hareket_turu == "FATURA ÇIKIŞ":
                fatura = session.scalar(select(SatisFaturasi).where(SatisFaturasi.fatura_no == belge_no))
                if fatura:
                    return ("satis_fatura", fatura.id)
                iade = session.scalar(select(AlisIadeFaturasi).where(AlisIadeFaturasi.iade_no == belge_no))
                if iade:
                    return ("alis_iade", iade.id)
            elif hareket_turu == "FATURA GİRİŞ":
                fatura = session.scalar(select(AlisFaturasi).where(AlisFaturasi.fatura_no == belge_no))
                if fatura:
                    return ("alis_fatura", fatura.id)
            elif hareket_turu == "İADE GİRİŞ":
                iade = session.scalar(select(SatisIadeFaturasi).where(SatisIadeFaturasi.iade_no == belge_no))
                if iade:
                    return ("satis_iade", iade.id)
            elif hareket_turu == "GİRİŞ":
                return ("stok_giris", belge_no)
        return None

    @staticmethod
    def stok_kaydi(veriler, fiyatlar, birimler=None, barkodlar=None, resimler=None):
        with get_session() as session:
            stok_id = veriler.get("stok_id")
            yeni_kod = (veriler.get("stok_kodu") or "").strip()
            if not yeni_kod:
                raise ValueError("Stok kodu zorunludur.")

            stok = StokService._stok_yukle(session, stok_id=stok_id) if stok_id else None
            if not stok:
                stok = session.scalar(
                    select(StokKarti).where(StokKarti.stok_kodu == yeni_kod)
                )
                if stok:
                    stok = StokService._stok_yukle(session, stok_id=stok.id)

            # Aynı stok kodu başka kartta var mı? (kendi kaydı hariç)
            kod_sorgu = select(StokKarti).where(StokKarti.stok_kodu == yeni_kod)
            if stok:
                kod_sorgu = kod_sorgu.where(StokKarti.id != stok.id)
            cakisan = session.scalar(kod_sorgu)
            if cakisan:
                raise ValueError(
                    f"'{yeni_kod}' stok kodu başka bir stok kartında kullanılıyor "
                    f"(id={cakisan.id}, ad={cakisan.stok_adi})."
                )

            if not stok:
                stok = StokKarti(
                    stok_kodu=yeni_kod,
                    stok_adi=veriler["stok_adi"].strip(),
                    birim=veriler.get("birim") or "Adet",
                    kart_turu=veriler.get("kart_turu") or "Ticari Mal",
                )
                session.add(stok)
                session.flush()

            stok.stok_kodu = yeni_kod
            stok.stok_adi = veriler["stok_adi"].strip()
            stok.birim = veriler.get("birim") or "Adet"
            stok.kart_turu = veriler.get("kart_turu") or "Ticari Mal"
            stok.aciklama = veriler.get("aciklama") or None
            stok.muhasebe_stok_kodu = veriler.get("muhasebe_stok_kodu") or None
            stok.muhasebe_alis_kodu = veriler.get("muhasebe_alis_kodu") or None
            stok.muhasebe_satis_kodu = veriler.get("muhasebe_satis_kodu") or None
            stok.muhasebe_maliyet_kodu = veriler.get("muhasebe_maliyet_kodu") or None
            stok.muhasebe_kdv_alis_kodu = veriler.get("muhasebe_kdv_alis_kodu") or None
            stok.muhasebe_kdv_satis_kodu = veriler.get("muhasebe_kdv_satis_kodu") or None
            stok.iskonto_1 = decimal(veriler.get("iskonto_1") or "0", "1. iskonto", Decimal("0"))
            stok.iskonto_2 = decimal(veriler.get("iskonto_2") or "0", "2. iskonto", Decimal("0"))
            stok.iskonto_3 = decimal(veriler.get("iskonto_3") or "0", "3. iskonto", Decimal("0"))
            stok.marka = veriler.get("marka") or None
            stok.model = veriler.get("model") or None
            stok.fonksiyon1 = veriler.get("fonksiyon1") or None
            stok.fonksiyon2 = veriler.get("fonksiyon2") or None
            stok.renk = veriler.get("renk") or None
            stok.agirlik = veriler.get("agirlik") or None
            stok.birim1 = veriler.get("birim1") or None
            stok.birim2 = veriler.get("birim2") or None
            stok.birim3 = veriler.get("birim3") or None
            stok.rapor_grubu = veriler.get("rapor_grubu") or None
            stok.raf_yeri = veriler.get("raf_yeri") or None
            stok.raf_omru = veriler.get("raf_omru") or None

            for tur in STOK_SECENEK_TURLERI:
                deger = (veriler.get(tur) or "").strip()
                if deger:
                    StokService._secenek_ekle(session, tur, deger)
            for birim_alan in ("birim1", "birim2", "birim3"):
                deger = (veriler.get(birim_alan) or "").strip()
                if not deger:
                    continue
                StokService._secenek_ekle(session, "birim", deger)

            # Eski fiyat adlarını yeni isimlere taşı
            normal_fiyatlar = []
            for ad, tutar in fiyatlar:
                hedef = ESKI_FIYAT_ESLEME.get(ad, ad)
                if str(tutar).strip() == "":
                    continue
                normal_fiyatlar.append((hedef, tutar))

            # Liste + ardışık 3 iskontodan fabrika fiyatı her zaman hesaplanır
            liste_deger = None
            for ad, tutar in list(normal_fiyatlar):
                if ad == "LİSTE FİYATI":
                    liste_deger = tutar
                    break
            if liste_deger is not None and str(liste_deger).strip() != "":
                fabrika = fabrika_fiyati_hesapla(
                    liste_deger, stok.iskonto_1, stok.iskonto_2, stok.iskonto_3
                )
                normal_fiyatlar = [
                    (ad, str(fabrika) if ad == "FABRİKA FİYATI" else tutar)
                    for ad, tutar in normal_fiyatlar
                ]
                if not any(ad == "FABRİKA FİYATI" for ad, _ in normal_fiyatlar):
                    normal_fiyatlar.append(("FABRİKA FİYATI", str(fabrika)))

            eski_fiyatlar = {f.fiyat_adi: f.tutar for f in list(stok.fiyatlar)}
            # SQLite unique: önce sil + flush, sonra ekle (INSERT-before-DELETE hatasını önler)
            stok.fiyatlar.clear()
            session.flush()
            yazilan = set()
            for ad, tutar in normal_fiyatlar:
                if ad in yazilan:
                    continue
                yeni = decimal(tutar, ad, Decimal("0"))
                stok.fiyatlar.append(StokFiyati(fiyat_adi=ad, tutar=yeni, para_birimi="TL"))
                yazilan.add(ad)
                eski = eski_fiyatlar.get(ad)
                if eski is None or Decimal(eski) != yeni:
                    session.add(
                        StokFiyatGecmisi(
                            stok_id=stok.id,
                            fiyat_adi=ad,
                            eski_tutar=eski,
                            yeni_tutar=yeni,
                            degisim_tarihi=datetime.now(),
                        )
                    )

            if birimler is not None:
                stok.birimler.clear()
                session.flush()
                for birim_adi, carpan in birimler:
                    ad = (birim_adi or "").strip()
                    if not ad:
                        continue
                    stok.birimler.append(
                        StokBirim(birim_adi=ad, carpan=decimal(carpan, f"{ad} çarpanı", Decimal("0.000001")))
                    )

            if barkodlar is not None:
                temiz_barkodlar = []
                gorulen = set()
                for kayit in barkodlar:
                    kod = (kayit.get("barkod") or "").strip()
                    if not kod:
                        continue
                    if kod in gorulen:
                        raise ValueError(f"Aynı barkod birden fazla yazılmış: {kod}")
                    gorulen.add(kod)
                    if StokService._barkod_kullaniliyor_mu(session, kod, haric_stok_id=stok.id):
                        raise ValueError(f"'{kod}' barkodu başka bir stok kartında kullanılıyor.")
                    temiz_barkodlar.append(kayit)

                stok.barkodlar.clear()
                # Ana barkod alanını geçici boşalt; unique çakışmayı önler
                stok.barkod = None
                session.flush()
                for kayit in temiz_barkodlar:
                    kod = (kayit.get("barkod") or "").strip()
                    stok.barkodlar.append(
                        StokBarkod(
                            barkod=kod,
                            birim=(kayit.get("birim") or stok.birim or "Adet").strip(),
                            fiyat_adi=(kayit.get("fiyat_adi") or None),
                            fiyat=decimal(kayit.get("fiyat") or "0", "Barkod fiyatı", Decimal("0")),
                            aciklama=(kayit.get("aciklama") or None),
                        )
                    )
                stok.barkod = stok.barkodlar[0].barkod if stok.barkodlar else None
            elif veriler.get("barkod") is not None:
                stok.barkod = veriler.get("barkod") or None

            if resimler is not None:
                stok.resimler.clear()
                session.flush()
                for sira, kayit in enumerate(resimler):
                    yol = (kayit.get("dosya_yolu") or "").strip()
                    if not yol:
                        continue
                    stok.resimler.append(
                        StokResmi(
                            dosya_yolu=yol,
                            aciklama=kayit.get("aciklama") or None,
                            sira=sira,
                        )
                    )

            try:
                session.flush()
            except IntegrityError as hata:
                metin = str(getattr(hata, "orig", hata) or hata)
                if "stok_kodu" in metin.lower() or "uq_stok" in metin.lower() and "kod" in metin.lower():
                    raise ValueError(
                        f"'{yeni_kod}' stok kodu başka bir stok kartında kullanılıyor."
                    ) from hata
                if "barkod" in metin.lower():
                    raise ValueError("Barkod başka bir stok kartında kullanılıyor.") from hata
                raise ValueError(f"Kayıt çakışması: {metin}") from hata
            return StokService._stok_yukle(session, stok_id=stok.id)

    @staticmethod
    def resim_kopyala(stok_kodu, kaynak_yol):
        RESIM_KLASORU.mkdir(parents=True, exist_ok=True)
        kaynak = Path(kaynak_yol)
        if not kaynak.exists():
            raise ValueError("Seçilen resim dosyası bulunamadı.")
        guvenli = "".join(c for c in stok_kodu if c.isalnum() or c in ("-", "_")) or "stok"
        hedef = RESIM_KLASORU / f"{guvenli}_{datetime.now():%Y%m%d%H%M%S}_{kaynak.name}"
        shutil.copy2(kaynak, hedef)
        return str(hedef)

    @staticmethod
    def fiyatlar(stok_kodu):
        with get_session() as session:
            stok = session.scalar(
                select(StokKarti)
                .where(StokKarti.stok_kodu == stok_kodu)
                .options(selectinload(StokKarti.fiyatlar))
            )
            return list(stok.fiyatlar) if stok else []

    @staticmethod
    def alis_fiyatlari(stok_kodu):
        """Stok kartındaki ALIŞ fiyatlarını döner (eski ad eşlemeleri dahil)."""
        hedef = {(ad or "").strip().upper() for ad in ALIŞ_FIYAT_ADLARI}
        for eski, yeni in ESKI_FIYAT_ESLEME.items():
            if (yeni or "").strip().upper() in hedef:
                hedef.add((eski or "").strip().upper())
        return [
            fiyat
            for fiyat in StokService.fiyatlar(stok_kodu)
            if (fiyat.fiyat_adi or "").strip().upper() in hedef
        ]

    @staticmethod
    def satis_fiyati_1(stok_kodu, varsayilan=Decimal("0")):
        """Stok kartındaki SATIŞ FİYATI 1 tutarını döner."""
        fiyatlar = StokService.fiyatlar(stok_kodu)
        for fiyat in fiyatlar:
            if (fiyat.fiyat_adi or "").strip().upper() == "SATIŞ FİYATI 1":
                return Decimal(str(fiyat.tutar))
        for fiyat in fiyatlar:
            ad = (fiyat.fiyat_adi or "").strip().upper()
            if ad.startswith("SATIŞ FİYATI"):
                return Decimal(str(fiyat.tutar))
        return Decimal(str(varsayilan))

    @staticmethod
    def son_alis_fiyati(stok_kodu, varsayilan=Decimal("0")):
        """Son alış faturası neti; yoksa karttaki ALIŞ FİYATI."""
        kod = (stok_kodu or "").strip()
        if not kod:
            return Decimal(str(varsayilan))
        net = StokService.son_alis_faturasi_net(stok_kodu=kod)
        if net is not None:
            return Decimal(str(net))
        for fiyat in StokService.fiyatlar(kod):
            if (fiyat.fiyat_adi or "").strip().upper() == "ALIŞ FİYATI":
                return Decimal(str(fiyat.tutar))
        return Decimal(str(varsayilan))

    @staticmethod
    def alis_fiyatini_guncelle(session, stok_kodu, net_fiyat):
        """Stok kartındaki ALIŞ FİYATI alanını son net alış (iskontolu) ile günceller."""
        stok = session.scalar(
            select(StokKarti)
            .where(StokKarti.stok_kodu == (stok_kodu or "").strip())
            .options(selectinload(StokKarti.fiyatlar))
        )
        if not stok:
            return None
        yeni = decimal(net_fiyat, "Alış fiyatı", Decimal("0")).quantize(Decimal("0.0001"))
        mevcut = next((f for f in stok.fiyatlar if f.fiyat_adi == "ALIŞ FİYATI"), None)
        eski = mevcut.tutar if mevcut is not None else None
        if mevcut is None:
            stok.fiyatlar.append(StokFiyati(fiyat_adi="ALIŞ FİYATI", tutar=yeni, para_birimi="TL"))
        else:
            if Decimal(mevcut.tutar) == yeni:
                return yeni
            mevcut.tutar = yeni
        session.add(
            StokFiyatGecmisi(
                stok_id=stok.id,
                fiyat_adi="ALIŞ FİYATI",
                eski_tutar=eski,
                yeni_tutar=yeni,
                degisim_tarihi=datetime.now(),
            )
        )
        return yeni

    @staticmethod
    def son_alis_faturasi_net(stok_kodu=None, stok_id=None):
        """Son alış faturasındaki net iskontolu birim fiyatı döndürür (yoksa None)."""
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri

        with get_session() as session:
            kod = (stok_kodu or "").strip()
            if not kod and stok_id:
                stok = session.get(StokKarti, int(stok_id))
                kod = stok.stok_kodu if stok else ""
            if not kod:
                return None
            satir = session.scalar(
                select(AlisFaturasiSatiri)
                .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                .where(
                    AlisFaturasiSatiri.urun_kodu == kod,
                    AlisFaturasi.durum != "İPTAL",
                )
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc(), AlisFaturasiSatiri.id.desc())
            )
            if not satir:
                return None
            tutar = decimal(satir.birim_fiyat, "Birim fiyat", Decimal("0"))
            oran = decimal(satir.iskonto_orani or "0", "İskonto", Decimal("0"))
            return (tutar * (Decimal("1") - oran / Decimal("100"))).quantize(Decimal("0.0001"))

    @staticmethod
    def lotlar(stok_kodu, depo_adi):
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokLotu)
                    .join(StokKarti)
                    .join(Depo)
                    .where(
                        StokKarti.stok_kodu == stok_kodu,
                        Depo.ad == depo_adi,
                        StokLotu.kalan_miktar > 0,
                    )
                    .order_by(StokLotu.giris_tarihi, StokLotu.id)
                ).all()
            )

    @staticmethod
    def maliyetler(stok_kodu, depo_adi):
        lotlar = StokService.lotlar(stok_kodu, depo_adi)
        if lotlar:
            toplam_miktar = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
            agirlikli = sum((lot.kalan_miktar * lot.birim_maliyet for lot in lotlar), Decimal("0"))
            return {
                "fifo": lotlar[0].birim_maliyet,
                "son_alis": lotlar[-1].birim_maliyet,
                "ortalama": sum((lot.birim_maliyet for lot in lotlar), Decimal("0")) / Decimal(len(lotlar)),
                "agirlikli": agirlikli / toplam_miktar if toplam_miktar else Decimal("0"),
            }
        # Lot yoksa: kart ALIŞ FİYATI (paket üretiminden yazılır) veya bileşen tahmini
        alis = StokService.son_alis_fiyati(stok_kodu, Decimal("0"))
        if alis and alis > 0:
            return {"fifo": alis, "son_alis": alis, "ortalama": alis, "agirlikli": alis}
        tahmini = StokService.paket_tahmini_birim_maliyet(stok_kodu, depo_adi)
        if tahmini and tahmini > 0:
            return {
                "fifo": tahmini,
                "son_alis": tahmini,
                "ortalama": tahmini,
                "agirlikli": tahmini,
            }
        sifir = Decimal("0")
        return {"fifo": sifir, "son_alis": sifir, "ortalama": sifir, "agirlikli": sifir}

    @staticmethod
    def paket_tahmini_birim_maliyet(paket_stok_kodu, depo_adi):
        """1 paket için bileşen FIFO maliyetleri toplamı (üretim öncesi / yedek)."""
        with get_session() as session:
            paket = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == (paket_stok_kodu or "").strip()))
            if not paket:
                return Decimal("0")
            bilesenler = list(
                session.scalars(
                    select(StokPaketBilesen)
                    .where(StokPaketBilesen.paket_stok_id == paket.id)
                    .options(selectinload(StokPaketBilesen.bilesen_stok))
                ).all()
            )
        if not bilesenler:
            return Decimal("0")
        toplam = Decimal("0")
        for b in bilesenler:
            m = StokService.maliyetler(b.bilesen_stok.stok_kodu, depo_adi)
            birim = m.get("fifo") or m.get("agirlikli") or Decimal("0")
            toplam += birim * b.miktar
        return toplam

    @staticmethod
    def otomatik_lot_no(tedarikci, tarih):
        onek = "".join(c for c in (tedarikci or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{tarih:%Y%m%d}"

    @staticmethod
    def stok_girisi(stok_kodu, depo_adi, tedarikci, tarih, miktar, maliyet, lot_no=""):
        miktar = decimal(miktar, "Miktar", Decimal("0.0001"))
        maliyet = decimal(maliyet, "Birim maliyet", Decimal("0"))
        with get_session() as session:
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
            depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
            if not stok:
                raise ValueError("Stok kartı bulunamadı.")
            if not depo:
                raise ValueError("Depo bulunamadı.")
            temel = lot_no.strip() or StokService.otomatik_lot_no(tedarikci, tarih)
            lot_adi, sira = temel, 1
            while session.scalar(
                select(StokLotu).where(
                    StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.lot_no == lot_adi
                )
            ):
                sira += 1
                lot_adi = f"{temel}-{sira}"
            lot = StokLotu(
                stok_id=stok.id,
                depo_id=depo.id,
                lot_no=lot_adi,
                tedarikci=tedarikci or None,
                giris_tarihi=tarih,
                kalan_miktar=miktar,
                birim_maliyet=maliyet,
            )
            session.add(lot)
            session.flush()
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="GİRİŞ",
                    belge_no=lot_adi,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=miktar,
                    birim_maliyet=maliyet,
                )
            )
            return lot

    @staticmethod
    def fatura_cikislarini_geri_al(session, belge_no):
        hareketler = session.scalars(
            select(StokHareketi).where(
                StokHareketi.belge_no == belge_no, StokHareketi.hareket_turu == "FATURA ÇIKIŞ"
            )
        ).all()
        for hareket in hareketler:
            if hareket.lot_id:
                lot = session.get(StokLotu, hareket.lot_id)
                if lot:
                    lot.kalan_miktar += hareket.miktar
            session.delete(hareket)

    @staticmethod
    def fatura_cikisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, tercih_lot=""):
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Çıkış miktarı", Decimal("0.0001"))
        q = select(StokLotu).where(
            StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.kalan_miktar > 0
        )
        if tercih_lot:
            q = q.where(StokLotu.lot_no == tercih_lot)
        lotlar = list(session.scalars(q.order_by(StokLotu.giris_tarihi, StokLotu.id)).all())
        mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{stok.stok_adi} için {depo.ad} stok yetersiz. Mevcut: {mevcut}, istenen: {miktar}"
            )
        kalan, maliyet, kullanilan = miktar, Decimal("0"), []
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, lot.kalan_miktar)
            lot.kalan_miktar -= cikan
            kalan -= cikan
            maliyet += cikan * lot.birim_maliyet
            kullanilan.append(f"{lot.lot_no}:{cikan}")
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="FATURA ÇIKIŞ",
                    belge_no=belge_no,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=lot.birim_maliyet,
                )
            )
        return {"lot_cikisi": ", ".join(kullanilan), "fifo_birim_maliyeti": maliyet / miktar}

    @staticmethod
    def fatura_girisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, birim_maliyet, tedarikci="", lot_no=""):
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Giriş miktarı", Decimal("0.0001"))
        maliyet = decimal(birim_maliyet, "Birim maliyet", Decimal("0"))
        temel = (lot_no or "").strip() or StokService.otomatik_lot_no(tedarikci, tarih)
        lot_adi, sira = temel, 1
        while session.scalar(
            select(StokLotu).where(
                StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.lot_no == lot_adi
            )
        ):
            sira += 1
            lot_adi = f"{temel}-{sira}"
        lot = StokLotu(
            stok_id=stok.id,
            depo_id=depo.id,
            lot_no=lot_adi,
            tedarikci=tedarikci or None,
            giris_tarihi=tarih,
            kalan_miktar=miktar,
            birim_maliyet=maliyet,
        )
        session.add(lot)
        session.flush()
        session.add(
            StokHareketi(
                tarih=tarih,
                hareket_turu="FATURA GİRİŞ",
                belge_no=belge_no,
                stok_id=stok.id,
                depo_id=depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=maliyet,
            )
        )
        return {"lot_girisi": lot_adi, "birim_maliyet": maliyet}

    @staticmethod
    def fatura_girislerini_geri_al(session, belge_no):
        hareketler = session.scalars(
            select(StokHareketi).where(
                StokHareketi.belge_no == belge_no, StokHareketi.hareket_turu == "FATURA GİRİŞ"
            )
        ).all()
        for hareket in hareketler:
            if hareket.lot_id:
                lot = session.get(StokLotu, hareket.lot_id)
                if lot:
                    if lot.kalan_miktar == hareket.miktar:
                        session.delete(lot)
                    else:
                        lot.kalan_miktar = max(Decimal("0"), lot.kalan_miktar - hareket.miktar)
            session.delete(hareket)

    @staticmethod
    def depo_transfer_fis_no():
        """DTF000001 formatında artan depo transfer fiş numarası."""
        onek = "DTF"
        with get_session() as session:
            son = session.scalar(
                select(DepoTransferFisi.fis_no)
                .where(DepoTransferFisi.fis_no.like(f"{onek}%"))
                .order_by(DepoTransferFisi.fis_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek):]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def depo_transfer_listele():
        with get_session() as session:
            return list(
                session.scalars(
                    select(DepoTransferFisi)
                    .options(selectinload(DepoTransferFisi.satirlar))
                    .order_by(DepoTransferFisi.fis_tarihi.desc(), DepoTransferFisi.id.desc())
                ).all()
            )

    @staticmethod
    def depo_transfer_getir(fis_id):
        with get_session() as session:
            return session.scalar(
                select(DepoTransferFisi)
                .where(DepoTransferFisi.id == fis_id)
                .options(selectinload(DepoTransferFisi.satirlar))
            )

    @staticmethod
    def _transfer_cikisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar):
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Çıkış miktarı", Decimal("0.0001"))
        lotlar = list(
            session.scalars(
                select(StokLotu)
                .where(
                    StokLotu.stok_id == stok.id,
                    StokLotu.depo_id == depo.id,
                    StokLotu.kalan_miktar > 0,
                )
                .order_by(StokLotu.giris_tarihi, StokLotu.id)
            ).all()
        )
        mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{stok.stok_adi} için {depo.ad} stok yetersiz. Mevcut: {mevcut}, istenen: {miktar}"
            )
        kalan, kullanilan = miktar, []
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, lot.kalan_miktar)
            lot.kalan_miktar -= cikan
            kalan -= cikan
            kullanilan.append(f"{lot.lot_no}:{cikan}")
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="TRANSFER ÇIKIŞ",
                    belge_no=belge_no,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=lot.birim_maliyet,
                )
            )
        return ", ".join(kullanilan)

    @staticmethod
    def _transfer_girisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, birim_fiyat, cikis_depo):
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Giriş miktarı", Decimal("0.0001"))
        maliyet = decimal(birim_fiyat, "Birim fiyat", Decimal("0"))
        temel = StokService.otomatik_lot_no(f"TRF-{cikis_depo}", tarih)
        lot_adi, sira = temel, 1
        while session.scalar(
            select(StokLotu).where(
                StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.lot_no == lot_adi
            )
        ):
            sira += 1
            lot_adi = f"{temel}-{sira}"
        lot = StokLotu(
            stok_id=stok.id,
            depo_id=depo.id,
            lot_no=lot_adi,
            tedarikci=f"TRANSFER ({cikis_depo})",
            giris_tarihi=tarih,
            kalan_miktar=miktar,
            birim_maliyet=maliyet,
        )
        session.add(lot)
        session.flush()
        session.add(
            StokHareketi(
                tarih=tarih,
                hareket_turu="TRANSFER GİRİŞ",
                belge_no=belge_no,
                stok_id=stok.id,
                depo_id=depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=maliyet,
            )
        )
        return lot_adi

    @staticmethod
    def depo_transfer_kaydet(veriler, satirlar):
        if not satirlar:
            raise ValueError("En az bir transfer satırı ekleyin.")
        cikis = (veriler.get("cikis_depo") or "").strip()
        giris = (veriler.get("giris_depo") or "").strip()
        if not cikis or not giris:
            raise ValueError("Çıkış ve giriş deposu seçilmelidir.")
        if cikis == giris:
            raise ValueError("Çıkış ve giriş deposu aynı olamaz.")
        tarih = veriler.get("fis_tarihi")
        if not isinstance(tarih, date):
            raise ValueError("Fiş tarihi geçersiz.")
        fis_no = (veriler.get("fis_no") or "").strip() or StokService.depo_transfer_fis_no()

        with get_session() as session:
            if session.scalar(select(DepoTransferFisi).where(DepoTransferFisi.fis_no == fis_no)):
                raise ValueError(f"{fis_no} numaralı fiş zaten var.")
            genel = Decimal("0")
            fis = DepoTransferFisi(
                fis_no=fis_no,
                fis_tarihi=tarih,
                cikis_depo=cikis,
                giris_depo=giris,
                aciklama=(veriler.get("aciklama") or "").strip() or None,
                genel_toplam=0,
            )
            session.add(fis)
            session.flush()
            for veri in satirlar:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                fiyat = decimal(veri.get("birim_fiyat", 0), "Birim fiyat", Decimal("0"))
                tutar = miktar * fiyat
                genel += tutar
                lot_cikis = StokService._transfer_cikisi(
                    session, fis_no, tarih, veri["urun_kodu"], cikis, miktar
                )
                lot_giris = StokService._transfer_girisi(
                    session, fis_no, tarih, veri["urun_kodu"], giris, miktar, fiyat, cikis
                )
                session.add(
                    DepoTransferFisiSatiri(
                        fis_id=fis.id,
                        urun_kodu=veri["urun_kodu"],
                        urun_adi=veri["urun_adi"],
                        birim=veri.get("birim") or "Adet",
                        miktar=miktar,
                        birim_fiyat=fiyat,
                        tutar=tutar,
                        lot_cikisi=lot_cikis,
                        lot_girisi=lot_giris,
                    )
                )
            fis.genel_toplam = genel
            session.flush()
            return fis.id

    @staticmethod
    def _belge_urun_kodlarini_guncelle(session, eski_kod, yeni_kod, yeni_ad, yeni_birim):
        """Belge satırlarındaki urun_kodu / ad / birim alanlarını hedef stoka çeker."""
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasiSatiri
        from database.models.alis_irsaliyesi import AlisIrsaliyesiSatiri
        from database.models.alis_siparisi import AlisSiparisiSatiri
        from database.models.satis_faturasi import SatisFaturasiSatiri
        from database.models.satis_iade_faturasi import SatisIadeFaturasiSatiri
        from database.models.satis_irsaliyesi import SatisIrsaliyesiSatiri
        from database.models.satis_siparisi import SatisSiparisiSatiri

        tablolar = (
            SatisSiparisiSatiri,
            SatisIrsaliyesiSatiri,
            SatisFaturasiSatiri,
            SatisIadeFaturasiSatiri,
            AlisSiparisiSatiri,
            AlisIrsaliyesiSatiri,
            AlisFaturasiSatiri,
            AlisIadeFaturasiSatiri,
            DepoTransferFisiSatiri,
        )
        guncellenen = 0
        for model in tablolar:
            satirlar = list(session.scalars(select(model).where(model.urun_kodu == eski_kod)).all())
            for satir in satirlar:
                satir.urun_kodu = yeni_kod
                if hasattr(satir, "urun_adi"):
                    satir.urun_adi = yeni_ad
                if hasattr(satir, "birim"):
                    satir.birim = yeni_birim
                guncellenen += 1
        return guncellenen

    @staticmethod
    def stok_birlestir(aktarilacak_id, aktarilan_id):
        """
        Aktarılacak stok kartını aktarılan (hedef) karta birleştirir.
        Hareketler, lotlar ve belge satırları hedefe geçer; birim hedef stoktan devam eder.
        Kaynak boşalınca silinir.
        """
        if int(aktarilacak_id) == int(aktarilan_id):
            raise ValueError("Aktarılacak ve aktarılan stok aynı olamaz.")

        with get_session() as session:
            kaynak = StokService._stok_yukle(session, stok_id=aktarilacak_id)
            hedef = StokService._stok_yukle(session, stok_id=aktarilan_id)
            if not kaynak or not hedef:
                raise ValueError("Stok kartı bulunamadı.")
            if not kaynak.aktif:
                raise ValueError("Aktarılacak stok kartı zaten pasif/silinmiş.")

            eski_kod = kaynak.stok_kodu
            yeni_kod = hedef.stok_kodu
            yeni_ad = hedef.stok_adi
            yeni_birim = hedef.birim or "Adet"

            belge_adet = StokService._belge_urun_kodlarini_guncelle(
                session, eski_kod, yeni_kod, yeni_ad, yeni_birim
            )

            # Lotlar: çakışmada miktar birleştir, aksi halde stok_id taşı
            hedef_lot_map = {
                (lot.depo_id, lot.lot_no): lot for lot in list(hedef.lotlar)
            }
            lot_tasinan = 0
            for lot in list(kaynak.lotlar):
                anahtar = (lot.depo_id, lot.lot_no)
                mevcut = hedef_lot_map.get(anahtar)
                if mevcut is None:
                    lot.stok_id = hedef.id
                    hedef_lot_map[anahtar] = lot
                    lot_tasinan += 1
                    continue
                # Aynı depo+lot: miktarları birleştir (ağırlıklı maliyet)
                toplam_miktar = mevcut.kalan_miktar + lot.kalan_miktar
                if toplam_miktar > 0:
                    mevcut.birim_maliyet = (
                        (mevcut.kalan_miktar * mevcut.birim_maliyet)
                        + (lot.kalan_miktar * lot.birim_maliyet)
                    ) / toplam_miktar
                mevcut.kalan_miktar = toplam_miktar
                # Hareketleri yeni lot'a bağla
                for hareket in session.scalars(
                    select(StokHareketi).where(StokHareketi.lot_id == lot.id)
                ).all():
                    hareket.lot_id = mevcut.id
                    hareket.stok_id = hedef.id
                session.delete(lot)
                lot_tasinan += 1

            # Kalan hareketler (lot'suz veya taşınmış lotlu)
            hareket_adet = 0
            for hareket in session.scalars(
                select(StokHareketi).where(StokHareketi.stok_id == kaynak.id)
            ).all():
                hareket.stok_id = hedef.id
                hareket_adet += 1

            # Fiyatlar: hedefte yoksa taşı
            hedef_fiyat_adlari = {f.fiyat_adi for f in hedef.fiyatlar}
            for fiyat in list(kaynak.fiyatlar):
                if fiyat.fiyat_adi in hedef_fiyat_adlari:
                    session.delete(fiyat)
                else:
                    fiyat.stok_id = hedef.id
                    hedef_fiyat_adlari.add(fiyat.fiyat_adi)

            # Birimler
            hedef_birimler = {b.birim_adi for b in hedef.birimler}
            for birim in list(kaynak.birimler):
                if birim.birim_adi in hedef_birimler:
                    session.delete(birim)
                else:
                    birim.stok_id = hedef.id
                    hedef_birimler.add(birim.birim_adi)

            # Barkodlar (benzersiz)
            hedef_barkodlar = {(b.barkod or "").strip() for b in hedef.barkodlar}
            if (hedef.barkod or "").strip():
                hedef_barkodlar.add(hedef.barkod.strip())
            for barkod in list(kaynak.barkodlar):
                kod = (barkod.barkod or "").strip()
                if not kod or kod in hedef_barkodlar:
                    session.delete(barkod)
                else:
                    barkod.stok_id = hedef.id
                    hedef_barkodlar.add(kod)
            kaynak_barkod = (kaynak.barkod or "").strip()
            if kaynak_barkod and kaynak_barkod not in hedef_barkodlar and not (hedef.barkod or "").strip():
                hedef.barkod = kaynak_barkod
                hedef_barkodlar.add(kaynak_barkod)
            kaynak.barkod = None

            # Resimler ve fiyat geçmişi
            for resim in list(kaynak.resimler):
                resim.stok_id = hedef.id
            for gecmis in list(kaynak.fiyat_gecmisi):
                gecmis.stok_id = hedef.id

            session.flush()
            # Kaynakta kalan bağımlılık kalmamalı
            kalan_hareket = session.scalar(
                select(func.count()).select_from(StokHareketi).where(StokHareketi.stok_id == kaynak.id)
            )
            kalan_lot = session.scalar(
                select(func.count()).select_from(StokLotu).where(StokLotu.stok_id == kaynak.id)
            )
            if kalan_hareket or kalan_lot:
                raise ValueError(
                    f"Aktarılacak stok boşaltılamadı (hareket={kalan_hareket}, lot={kalan_lot})."
                )

            session.delete(kaynak)
            session.flush()
            return {
                "eski_kod": eski_kod,
                "yeni_kod": yeni_kod,
                "yeni_ad": yeni_ad,
                "yeni_birim": yeni_birim,
                "belge_satir": belge_adet,
                "hareket": hareket_adet,
                "lot": lot_tasinan,
            }

    # --- Stok paket tanımlama / üretim ---

    @staticmethod
    def paket_uretim_fis_no():
        onek = "PKT"
        with get_session() as session:
            son = session.scalar(
                select(StokPaketUretim.fis_no)
                .where(StokPaketUretim.fis_no.like(f"{onek}%"))
                .order_by(StokPaketUretim.fis_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek):]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def paket_tanimlari():
        """Tanımlı paket stokları (kart_turu=Paket ve bileşeni olanlar)."""
        with get_session() as session:
            paket_idler = set(session.scalars(select(StokPaketBilesen.paket_stok_id).distinct()).all())
            if not paket_idler:
                return []
            stoklar = list(
                session.scalars(
                    select(StokKarti)
                    .where(StokKarti.id.in_(paket_idler), StokKarti.aktif.is_(True))
                    .options(selectinload(StokKarti.lotlar))
                    .order_by(StokKarti.stok_adi)
                ).all()
            )
            sonuc = []
            for stok in stoklar:
                bilesenler = StokService._paket_bilesenleri_session(session, stok.id)
                mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
                sonuc.append({"stok": stok, "bilesenler": bilesenler, "mevcut": mevcut})
            return sonuc

    @staticmethod
    def _paket_bilesenleri_session(session, paket_stok_id):
        satirlar = list(
            session.scalars(
                select(StokPaketBilesen)
                .where(StokPaketBilesen.paket_stok_id == int(paket_stok_id))
                .options(selectinload(StokPaketBilesen.bilesen_stok))
                .order_by(StokPaketBilesen.id)
            ).all()
        )
        return [
            {
                "id": s.id,
                "bilesen_stok_id": s.bilesen_stok_id,
                "urun_kodu": s.bilesen_stok.stok_kodu,
                "urun_adi": s.bilesen_stok.stok_adi,
                "birim": s.bilesen_stok.birim,
                "miktar": s.miktar,
            }
            for s in satirlar
        ]

    @staticmethod
    def paket_bilesenleri(paket_stok_id):
        with get_session() as session:
            return StokService._paket_bilesenleri_session(session, paket_stok_id)

    @staticmethod
    def paket_tanim_kaydet(paket_stok_id, bilesenler):
        """
        bilesenler: [{"urun_kodu": "...", "miktar": 5}, ...] — 1 paket için miktarlar.
        Paket kartının türü 'Paket' yapılır.
        """
        if not bilesenler:
            raise ValueError("Pakete en az bir ürün ekleyin.")
        with get_session() as session:
            paket = session.get(StokKarti, int(paket_stok_id))
            if not paket:
                raise ValueError("Paket stok kartı bulunamadı.")
            paket.kart_turu = "Paket"

            # Eski tanımı temizle
            for eski in list(
                session.scalars(
                    select(StokPaketBilesen).where(StokPaketBilesen.paket_stok_id == paket.id)
                ).all()
            ):
                session.delete(eski)
            session.flush()

            gorulen = set()
            for veri in bilesenler:
                kod = (veri.get("urun_kodu") or "").strip()
                miktar = decimal(veri.get("miktar", 0), "Bileşen miktarı", Decimal("0.0001"))
                bilesen = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
                if not bilesen:
                    raise ValueError(f"Bileşen stok bulunamadı: {kod}")
                if bilesen.id == paket.id:
                    raise ValueError("Paket kendi içine eklenemez.")
                if bilesen.id in gorulen:
                    raise ValueError(f"{kod} pakete birden fazla eklenemez.")
                if (bilesen.kart_turu or "").strip().casefold() == "paket":
                    raise ValueError(f"{kod} zaten bir paket kartı; iç içe paket tanımlamayın.")
                gorulen.add(bilesen.id)
                session.add(
                    StokPaketBilesen(
                        paket_stok_id=paket.id,
                        bilesen_stok_id=bilesen.id,
                        miktar=miktar,
                    )
                )
            session.flush()
            return paket.id

    @staticmethod
    def paket_tanim_sil(paket_stok_id):
        with get_session() as session:
            for eski in list(
                session.scalars(
                    select(StokPaketBilesen).where(StokPaketBilesen.paket_stok_id == int(paket_stok_id))
                ).all()
            ):
                session.delete(eski)

    @staticmethod
    def _paket_bilesen_cikisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar):
        """Bileşeni depodan düşer; gerçek FIFO maliyetini döner."""
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Çıkış miktarı", Decimal("0.0001"))
        lotlar = list(
            session.scalars(
                select(StokLotu)
                .where(
                    StokLotu.stok_id == stok.id,
                    StokLotu.depo_id == depo.id,
                    StokLotu.kalan_miktar > 0,
                )
                .order_by(StokLotu.giris_tarihi, StokLotu.id)
            ).all()
        )
        mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{stok.stok_adi} ({stok.stok_kodu}) için {depo.ad} yetersiz. "
                f"Mevcut: {mevcut}, gereken: {miktar}"
            )
        kalan, maliyet = miktar, Decimal("0")
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, lot.kalan_miktar)
            lot.kalan_miktar -= cikan
            kalan -= cikan
            maliyet += cikan * lot.birim_maliyet
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="PAKET ÇIKIŞ",
                    belge_no=belge_no,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=lot.birim_maliyet,
                )
            )
        return maliyet

    @staticmethod
    def paket_olustur(paket_stok_id, depo_adi, paket_adedi, tarih=None, aciklama=""):
        """
        N adet paket üretir:
        - Her bileşenden (miktar × N) düşülür (maliyetleriyle)
        - Paket stoğa N adet girer; birim maliyet = toplam bileşen maliyeti / N
        """
        tarih = tarih or date.today()
        adet = decimal(paket_adedi, "Paket adedi", Decimal("0.0001"))
        depo_adi = (depo_adi or "").strip()
        if not depo_adi:
            raise ValueError("Depo seçilmelidir.")

        with get_session() as session:
            paket = session.get(StokKarti, int(paket_stok_id))
            if not paket:
                raise ValueError("Paket stok kartı bulunamadı.")
            paket.kart_turu = "Paket"
            bilesenler = list(
                session.scalars(
                    select(StokPaketBilesen)
                    .where(StokPaketBilesen.paket_stok_id == paket.id)
                    .options(selectinload(StokPaketBilesen.bilesen_stok))
                ).all()
            )
            if not bilesenler:
                raise ValueError("Önce paket içeriğini tanımlayın.")

            # Fiş no (aynı oturumda)
            son = session.scalar(
                select(StokPaketUretim.fis_no)
                .where(StokPaketUretim.fis_no.like("PKT%"))
                .order_by(StokPaketUretim.fis_no.desc())
            )
            if not son:
                fis_no = "PKT000001"
            else:
                try:
                    fis_no = f"PKT{int(str(son)[3:]) + 1:06d}"
                except ValueError:
                    fis_no = "PKT000001"
            while session.scalar(select(StokPaketUretim).where(StokPaketUretim.fis_no == fis_no)):
                try:
                    fis_no = f"PKT{int(fis_no[3:]) + 1:06d}"
                except ValueError:
                    fis_no = "PKT000001"
                    break

            toplam_maliyet = Decimal("0")
            bilesen_ozet = []
            for b in bilesenler:
                gereken = b.miktar * adet
                maliyet = StokService._paket_bilesen_cikisi(
                    session, fis_no, tarih, b.bilesen_stok.stok_kodu, depo_adi, gereken
                )
                toplam_maliyet += maliyet
                bilesen_ozet.append(
                    {
                        "urun_kodu": b.bilesen_stok.stok_kodu,
                        "urun_adi": b.bilesen_stok.stok_adi,
                        "miktar": gereken,
                        "maliyet": maliyet,
                    }
                )

            birim_maliyet = (toplam_maliyet / adet) if adet else Decimal("0")
            depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
            if not depo:
                raise ValueError(f"{depo_adi} deposu bulunamadı.")

            temel = StokService.otomatik_lot_no("PAKET", tarih)
            lot_adi, sira = temel, 1
            while session.scalar(
                select(StokLotu).where(
                    StokLotu.stok_id == paket.id,
                    StokLotu.depo_id == depo.id,
                    StokLotu.lot_no == lot_adi,
                )
            ):
                sira += 1
                lot_adi = f"{temel}-{sira}"

            lot = StokLotu(
                stok_id=paket.id,
                depo_id=depo.id,
                lot_no=lot_adi,
                tedarikci="PAKET ÜRETİM",
                giris_tarihi=tarih,
                kalan_miktar=adet,
                birim_maliyet=birim_maliyet,
            )
            session.add(lot)
            session.flush()
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="PAKET GİRİŞ",
                    belge_no=fis_no,
                    stok_id=paket.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=adet,
                    birim_maliyet=birim_maliyet,
                )
            )
            # Kar/zarar (SON ALIŞ vb.) için paket kart maliyeti = bileşen toplamı / adet
            StokService.alis_fiyatini_guncelle(session, paket.stok_kodu, birim_maliyet)

            uretim = StokPaketUretim(
                fis_no=fis_no,
                uretim_tarihi=tarih,
                paket_stok_id=paket.id,
                depo=depo_adi,
                paket_adedi=adet,
                birim_maliyet=birim_maliyet,
                toplam_maliyet=toplam_maliyet,
                aciklama=(aciklama or "").strip() or None,
            )
            session.add(uretim)
            session.flush()
            return {
                "fis_no": fis_no,
                "paket_kodu": paket.stok_kodu,
                "paket_adi": paket.stok_adi,
                "depo": depo_adi,
                "adet": adet,
                "birim_maliyet": birim_maliyet,
                "toplam_maliyet": toplam_maliyet,
                "lot_no": lot_adi,
                "bilesenler": bilesen_ozet,
            }

    @staticmethod
    def paket_uretimleri(limit=100):
        with get_session() as session:
            return list(
                session.scalars(
                    select(StokPaketUretim)
                    .options(selectinload(StokPaketUretim.paket_stok))
                    .order_by(StokPaketUretim.uretim_tarihi.desc(), StokPaketUretim.id.desc())
                    .limit(limit)
                ).all()
            )

    # --- Toplu fiyat değişikliği ---

    @staticmethod
    def fiyat_yuvarla(tutar) -> Decimal:
        """
        ≥ 1 TL: kuruş yok, yukarı (ceiling) tam TL.
        < 1 TL: 3 ondalık (0,001).
        """
        from decimal import ROUND_CEILING, ROUND_HALF_UP

        t = decimal(tutar, "Fiyat", Decimal("0"))
        if t >= 1:
            return t.to_integral_value(rounding=ROUND_CEILING)
        if t <= 0:
            return Decimal("0.000")
        return t.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def toplu_fiyat_stoklari_filtrele(rapor_grubu="", ad_baslangic="", ad_bitis="", stok_filtre=""):
        """
        Rapor grubu / stok adı aralığı / serbest arama.
        Boş kriter = tüm aktif stoklar (sonra diğer filtreler AND).
        """
        rapor = (rapor_grubu or "").strip()
        if rapor in ("", "(Tümü)"):
            rapor = ""
        ad_bas = (ad_baslangic or "").strip()
        if ad_bas in ("", "(Tümü)"):
            ad_bas = ""
        ad_bit = (ad_bitis or "").strip()
        if ad_bit in ("", "(Tümü)"):
            ad_bit = ""
        ara = (stok_filtre or "").strip()

        stoklar = StokService.stoklari_ara(ara)
        sonuc = []
        for stok in stoklar:
            if rapor and (stok.rapor_grubu or "").strip().upper() != rapor.upper():
                continue
            ad = (stok.stok_adi or "").strip()
            ad_cmp = ad.casefold()
            if ad_bas and ad_cmp < ad_bas.casefold():
                continue
            if ad_bit and ad_cmp > ad_bit.casefold():
                continue
            sonuc.append(stok)
        return sonuc

    @staticmethod
    def toplu_fiyat_onizle(
        baz_fiyat_adi,
        yuzdeler,
        stok_filtre="",
        rapor_grubu="",
        ad_baslangic="",
        ad_bitis="",
        stok_idler=None,
    ) -> list[dict]:
        """
        baz_fiyat_adi: örn. ALIŞ FİYATI veya SATIŞ FİYATI 1
        yuzdeler: { "SATIŞ FİYATI 1": Decimal("20"), ... }  (+ artı, − eksi)
        stok_idler: verilirse yalnızca bu stoklar (önizleme sonrası seçim).
        """
        baz_adi = (baz_fiyat_adi or "").strip()
        if not baz_adi:
            raise ValueError("Baz fiyat seçin.")
        if not yuzdeler:
            raise ValueError("En az bir satış fiyatı için yüzde girin.")

        id_set = None
        if stok_idler is not None:
            id_set = {int(i) for i in stok_idler}
            if not id_set:
                return []

        stoklar = StokService.toplu_fiyat_stoklari_filtrele(
            rapor_grubu=rapor_grubu,
            ad_baslangic=ad_baslangic,
            ad_bitis=ad_bitis,
            stok_filtre=stok_filtre,
        )
        sonuc = []
        for stok in stoklar:
            if id_set is not None and stok.id not in id_set:
                continue
            fiyat_map = {(f.fiyat_adi or "").strip(): Decimal(str(f.tutar)) for f in stok.fiyatlar}
            baz = fiyat_map.get(baz_adi)
            if baz is None or baz <= 0:
                continue
            degisimler = []
            for satis_adi, yuzde in yuzdeler.items():
                oran = decimal(yuzde, f"{satis_adi} %", Decimal("0"))
                ham = baz * (Decimal("1") + oran / Decimal("100"))
                yeni = StokService.fiyat_yuvarla(ham)
                eski = fiyat_map.get(satis_adi)
                degisimler.append({
                    "fiyat_adi": satis_adi,
                    "yuzde": oran,
                    "eski": eski,
                    "yeni": yeni,
                })
            if degisimler:
                sonuc.append({
                    "stok_id": stok.id,
                    "stok_kodu": stok.stok_kodu,
                    "stok_adi": stok.stok_adi,
                    "rapor_grubu": stok.rapor_grubu or "",
                    "baz_fiyat": baz,
                    "baz_adi": baz_adi,
                    "degisimler": degisimler,
                })
        return sonuc

    @staticmethod
    def toplu_fiyat_uygula(
        baz_fiyat_adi,
        yuzdeler,
        stok_filtre="",
        rapor_grubu="",
        ad_baslangic="",
        ad_bitis="",
        stok_idler=None,
    ) -> dict:
        """Önizleme sonucunu stok kartlarına yazar (fiyat geçmişi dahil)."""
        onizleme = StokService.toplu_fiyat_onizle(
            baz_fiyat_adi,
            yuzdeler,
            stok_filtre=stok_filtre,
            rapor_grubu=rapor_grubu,
            ad_baslangic=ad_baslangic,
            ad_bitis=ad_bitis,
            stok_idler=stok_idler,
        )
        if not onizleme:
            raise ValueError("Uygulanacak stok bulunamadı (seçim yok veya baz fiyatı olan kart yok).")

        guncellenen = 0
        with get_session() as session:
            for kayit in onizleme:
                stok = StokService._stok_yukle(session, stok_id=kayit["stok_id"])
                if not stok:
                    continue
                mevcut = {f.fiyat_adi: f for f in list(stok.fiyatlar)}
                for d in kayit["degisimler"]:
                    ad = d["fiyat_adi"]
                    yeni = d["yeni"]
                    eski_f = mevcut.get(ad)
                    eski = eski_f.tutar if eski_f else None
                    if eski_f is None:
                        stok.fiyatlar.append(StokFiyati(fiyat_adi=ad, tutar=yeni, para_birimi="TL"))
                    else:
                        if Decimal(eski_f.tutar) == yeni:
                            continue
                        eski_f.tutar = yeni
                    session.add(
                        StokFiyatGecmisi(
                            stok_id=stok.id,
                            fiyat_adi=ad,
                            eski_tutar=eski,
                            yeni_tutar=yeni,
                            degisim_tarihi=datetime.now(),
                        )
                    )
                guncellenen += 1
            session.flush()
        return {"stok_adet": guncellenen, "satir": onizleme}
