from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import random
import shutil

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import BASE_DIR, get_session
from database.access import yazma_zorunlu, maliyet_zorunlu
from database.models.stok import (
    VARSAYILAN_KDV_ORANI,
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

GIRIS_HAREKETLERI = (
    "GİRİŞ",
    "FATURA GİRİŞ",
    "İADE GİRİŞ",
    "TRANSFER GİRİŞ",
    "PAKET GİRİŞ",
    "SAYIM GİRİŞ",
    "İRSALİYE İADE GİRİŞ",
)
CIKIS_HAREKETLERI = (
    "FATURA ÇIKIŞ",
    "ÇIKIŞ",
    "TRANSFER ÇIKIŞ",
    "PAKET ÇIKIŞ",
    "SAYIM ÇIKIŞ",
    "İRSALİYE ÇIKIŞ",
)

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

SATIS_FIYAT_ALANLARI = tuple(f"satis_{i}" for i in range(1, 11))


def _birim_kayit_normalize(kayit, ana_birim="Adet") -> dict:
    """Eski (adi, carpan) veya yeni dict birim kaydını standart dict'e çevirir."""
    if isinstance(kayit, dict):
        ad = (kayit.get("birim_adi") or kayit.get("birim") or "").strip()
        carpan = kayit.get("carpan") or kayit.get("temel_carpan") or "1"
        satis = dict(kayit.get("satis_fiyatlari") or {})
        for i, ad_fiyat in enumerate(SATIS_FIYAT_ADLARI, start=1):
            alan = f"satis_{i}"
            if ad_fiyat not in satis and kayit.get(alan) is not None:
                satis[ad_fiyat] = kayit.get(alan)
        return {
            "birim_adi": ad,
            "carpan": carpan,
            "referans_birim": (kayit.get("referans_birim") or kayit.get("hedef") or ana_birim or "").strip()
            or ana_birim,
            "referans_carpan": kayit.get("referans_carpan") or kayit.get("ust_carpan") or carpan,
            "fiyat_modu": (kayit.get("fiyat_modu") or "manuel").strip().lower() or "manuel",
            "alis_fiyati": kayit.get("alis_fiyati"),
            "satis_fiyatlari": satis,
            "alis_kullanilabilir": bool(kayit.get("alis_kullanilabilir", True)),
            "satis_kullanilabilir": bool(kayit.get("satis_kullanilabilir", True)),
            "varsayilan_goruntuleme": bool(kayit.get("varsayilan_goruntuleme", False)),
            "varsayilan_alis": bool(kayit.get("varsayilan_alis", False)),
            "varsayilan_satis": bool(kayit.get("varsayilan_satis", False)),
            "birim_barkod": (kayit.get("birim_barkod") or "").strip() or None,
            "ondalik": int(kayit.get("ondalik") or 0),
            "aktif": bool(kayit.get("aktif", True)),
        }
    birim_adi = (kayit[0] if kayit else "") or ""
    carpan = kayit[1] if len(kayit) > 1 else "1"
    hedef = kayit[2] if len(kayit) > 2 else ana_birim
    return _birim_kayit_normalize(
        {
            "birim_adi": birim_adi,
            "carpan": carpan,
            "referans_birim": hedef,
            "referans_carpan": carpan,
        },
        ana_birim=ana_birim,
    )


def _birim_orm_to_dict(b: StokBirim) -> dict:
    satis = {}
    for i, ad in enumerate(SATIS_FIYAT_ADLARI, start=1):
        deger = getattr(b, f"satis_{i}", None)
        if deger is not None:
            satis[ad] = f"{Decimal(deger):f}".rstrip("0").rstrip(".")
    return {
        "birim_adi": b.birim_adi,
        "carpan": f"{Decimal(b.carpan):f}".rstrip("0").rstrip("."),
        "referans_birim": getattr(b, "referans_birim", None) or "",
        "referans_carpan": (
            f"{Decimal(b.referans_carpan):f}".rstrip("0").rstrip(".")
            if getattr(b, "referans_carpan", None) is not None
            else ""
        ),
        "fiyat_modu": getattr(b, "fiyat_modu", None) or "manuel",
        "alis_fiyati": (
            f"{Decimal(b.alis_fiyati):f}".rstrip("0").rstrip(".")
            if getattr(b, "alis_fiyati", None) is not None
            else ""
        ),
        "satis_fiyatlari": satis,
        "alis_kullanilabilir": bool(getattr(b, "alis_kullanilabilir", True)),
        "satis_kullanilabilir": bool(getattr(b, "satis_kullanilabilir", True)),
        "varsayilan_goruntuleme": bool(getattr(b, "varsayilan_goruntuleme", False)),
        "varsayilan_alis": bool(getattr(b, "varsayilan_alis", False)),
        "varsayilan_satis": bool(getattr(b, "varsayilan_satis", False)),
        "birim_barkod": getattr(b, "birim_barkod", None) or "",
        "ondalik": int(getattr(b, "ondalik", 0) or 0),
        "aktif": bool(getattr(b, "aktif", True)),
    }


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
    def birim_carpani(stok_veya_birimler, birim_adi, ana_birim="Adet") -> Decimal:
        """1 kaynak birim = kaç temel birim. Bilinmeyen birim → 1."""
        hedef = (birim_adi or "").strip().casefold()
        if hasattr(stok_veya_birimler, "birim"):
            ana = (getattr(stok_veya_birimler, "birim", None) or ana_birim or "Adet").strip()
            birimler = list(getattr(stok_veya_birimler, "birimler", None) or [])
        else:
            ana = (ana_birim or "Adet").strip()
            birimler = list(stok_veya_birimler or [])
        ana_cf = ana.casefold()
        if not hedef or hedef == ana_cf:
            return Decimal("1")
        for b in birimler:
            if isinstance(b, dict):
                ad = (b.get("birim_adi") or "").strip().casefold()
                if ad == hedef:
                    c = Decimal(str(b.get("carpan") or 1))
                    return c if c > 0 else Decimal("1")
            else:
                ad = (getattr(b, "birim_adi", None) or "").strip().casefold()
                if ad == hedef:
                    if getattr(b, "aktif", True) is False:
                        continue
                    c = Decimal(str(getattr(b, "carpan", 1) or 1))
                    return c if c > 0 else Decimal("1")
        return Decimal("1")

    @staticmethod
    def temel_miktara_cevir(miktar, birim_adi, stok_veya_birimler, ana_birim="Adet") -> Decimal:
        """Evrak miktarını temel stok birimine çevirir (Decimal)."""
        m = Decimal(str(miktar or 0))
        return (m * StokService.birim_carpani(stok_veya_birimler, birim_adi, ana_birim)).quantize(
            Decimal("0.000001")
        )

    @staticmethod
    def birim_fiyati_getir(
        stok,
        birim_adi,
        *,
        fiyat_adi="SATIŞ FİYATI 1",
        alis=False,
    ) -> Decimal | None:
        """Birime özel manuel fiyat; yoksa otomatik modda temel×çarpan; yoksa None.

        None = fiyat tanımsız (sessizce 0 kullanma).
        """
        birim_adi = (birim_adi or "").strip()
        ana = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
        carpan = StokService.birim_carpani(stok, birim_adi, ana)

        # Temel kart fiyatları
        ana_map = {}
        for f in getattr(stok, "fiyatlar", None) or []:
            ana_map[(f.fiyat_adi or "").strip().upper()] = Decimal(str(f.tutar))

        hedef_kayit = None
        for b in getattr(stok, "birimler", None) or []:
            if (b.birim_adi or "").strip().casefold() == birim_adi.casefold():
                hedef_kayit = b
                break

        if birim_adi.casefold() == ana.casefold() or hedef_kayit is None:
            if alis:
                v = ana_map.get("ALIŞ FİYATI")
                return v
            return ana_map.get((fiyat_adi or "").strip().upper())

        mod = (getattr(hedef_kayit, "fiyat_modu", None) or "manuel").lower()
        if alis:
            manuel = getattr(hedef_kayit, "alis_fiyati", None)
            if mod.startswith("oto"):
                temel = ana_map.get("ALIŞ FİYATI")
                if temel is None:
                    return Decimal(str(manuel)) if manuel is not None else None
                return (temel * carpan).quantize(Decimal("0.0001"))
            if manuel is not None:
                return Decimal(str(manuel))
            return None

        # Satış 1-10
        idx = None
        ad_u = (fiyat_adi or "").strip().upper()
        for i, ad in enumerate(SATIS_FIYAT_ADLARI, start=1):
            if ad.upper() == ad_u:
                idx = i
                break
        if idx is None:
            idx = 1
            ad_u = "SATIŞ FİYATI 1"
        manuel = getattr(hedef_kayit, f"satis_{idx}", None)
        if mod.startswith("oto"):
            temel = ana_map.get(ad_u)
            if temel is None:
                return Decimal(str(manuel)) if manuel is not None else None
            return (temel * carpan).quantize(Decimal("0.0001"))
        if manuel is not None:
            return Decimal(str(manuel))
        return None

    @staticmethod
    def birimleri_dict_listesi(stok) -> list[dict]:
        return [_birim_orm_to_dict(b) for b in (getattr(stok, "birimler", None) or [])]

    @staticmethod
    def birim_donusum_onizleme(miktar, kaynak_birim, hedef_birim, stok_veya_birimler, ana_birim="Adet"):
        """Kaynak→hedef ve kaynak→temel önizleme."""
        kaynak_c = StokService.birim_carpani(stok_veya_birimler, kaynak_birim, ana_birim)
        hedef_c = StokService.birim_carpani(stok_veya_birimler, hedef_birim, ana_birim)
        m = Decimal(str(miktar or 0))
        temel = m * kaynak_c
        hedef_miktar = (temel / hedef_c) if hedef_c > 0 else Decimal("0")
        return {
            "temel_miktar": temel.quantize(Decimal("0.000001")),
            "hedef_miktar": hedef_miktar.quantize(Decimal("0.000001")),
            "kaynak_carpan": kaynak_c,
            "hedef_carpan": hedef_c,
        }

    @staticmethod
    def varsayilanlari_hazirla():
        RESIM_KLASORU.mkdir(parents=True, exist_ok=True)
        with get_session() as session:
            ana = session.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            if not ana:
                session.add(
                    Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True)
                )
            else:
                if not getattr(ana, "kod", None):
                    ana.kod = "ANA"
                if not any(
                    bool(getattr(d, "varsayilan", False))
                    for d in session.scalars(select(Depo)).all()
                ):
                    ana.varsayilan = True
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
    def depolar(aktif_only: bool = True):
        with get_session() as session:
            q = select(Depo).order_by(Depo.ad)
            if aktif_only:
                q = q.where(Depo.aktif.is_(True))
            return list(session.scalars(q).all())

    @staticmethod
    def depo_getir(depo_id: int) -> Depo | None:
        with get_session() as session:
            return session.get(Depo, int(depo_id))

    @staticmethod
    def _depo_normalize(metin: str) -> str:
        return (metin or "").strip()

    @staticmethod
    def depo_ekle(
        ad,
        *,
        kod: str | None = None,
        aciklama: str | None = None,
        aktif: bool = True,
        varsayilan: bool = False,
    ):
        from database.access import yazma_zorunlu
        from database.user_audit import audit_document

        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        ad_n = StokService._depo_normalize(ad).upper()
        kod_n = StokService._depo_normalize(kod or ad_n).upper()
        if not ad_n:
            raise ValueError("Depo adı zorunludur.")
        if not kod_n:
            raise ValueError("Depo kodu zorunludur.")
        with get_session() as session:
            ad_cakisan = session.scalar(
                select(Depo).where(func.lower(Depo.ad) == ad_n.lower())
            )
            if ad_cakisan:
                raise ValueError(f"Bu firma içinde «{ad_cakisan.ad}» adlı depo zaten var.")
            kod_cakisan = session.scalar(
                select(Depo).where(
                    Depo.kod.is_not(None),
                    func.lower(Depo.kod) == kod_n.lower(),
                )
            )
            if kod_cakisan:
                raise ValueError(f"Bu firma içinde «{kod_cakisan.kod}» kodlu depo zaten var.")
            if varsayilan:
                for d in session.scalars(select(Depo).where(Depo.varsayilan.is_(True))).all():
                    d.varsayilan = False
            depo = Depo(
                kod=kod_n,
                ad=ad_n,
                aciklama=(aciklama or None),
                aktif=bool(aktif),
                varsayilan=bool(varsayilan),
            )
            session.add(depo)
            session.flush()
            depo_id = int(depo.id)
            audit_document(
                "depo_olustur",
                modul="stok",
                kayit_id=str(depo_id),
                yeni={"kod": kod_n, "ad": ad_n, "varsayilan": bool(varsayilan)},
            )
            # Geriye uyum: eski çağrılar Depo nesnesi bekleyebilir
            return session.get(Depo, depo_id)

    @staticmethod
    def depo_kullanim_ozeti(depo_id: int) -> dict:
        """Silme öncesi ilişki sayıları."""
        from database.models.stok_sayim import StokSayimFisi

        with get_session() as session:
            depo = session.get(Depo, int(depo_id))
            if depo is None:
                raise ValueError("Depo bulunamadı.")
            lot_adet = int(
                session.scalar(
                    select(func.count()).select_from(StokLotu).where(StokLotu.depo_id == depo.id)
                )
                or 0
            )
            bakiye = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                    StokLotu.depo_id == depo.id
                )
            )
            hareket = int(
                session.scalar(
                    select(func.count())
                    .select_from(StokHareketi)
                    .where(StokHareketi.depo_id == depo.id)
                )
                or 0
            )
            sayim = 0
            try:
                sayim = int(
                    session.scalar(
                        select(func.count())
                        .select_from(StokSayimFisi)
                        .where(StokSayimFisi.depo_id == depo.id)
                    )
                    or 0
                )
            except Exception:
                sayim = 0
            transfer = int(
                session.scalar(
                    select(func.count())
                    .select_from(DepoTransferFisi)
                    .where(
                        (DepoTransferFisi.cikis_depo == depo.ad)
                        | (DepoTransferFisi.giris_depo == depo.ad)
                    )
                )
                or 0
            )
            bakiye_d = Decimal(str(bakiye or 0))
            engel = bakiye_d != 0 or hareket > 0 or lot_adet > 0 or sayim > 0 or transfer > 0
            return {
                "depo_id": depo.id,
                "kod": getattr(depo, "kod", None) or "",
                "ad": depo.ad,
                "varsayilan": bool(getattr(depo, "varsayilan", False)),
                "lot_adet": lot_adet,
                "bakiye": bakiye_d,
                "hareket": hareket,
                "sayim": sayim,
                "transfer": transfer,
                "silinebilir": not engel,
            }

    @staticmethod
    def depo_sil(depo_id: int) -> None:
        from database.access import yazma_zorunlu
        from database.user_audit import audit_document

        yazma_zorunlu("stok_duzenleme", "silme")
        ozet = StokService.depo_kullanim_ozeti(depo_id)
        if ozet["varsayilan"]:
            raise ValueError(
                "Varsayılan depo silinemez. Önce başka bir depoyu varsayılan yapın."
            )
        if not ozet["silinebilir"]:
            raise ValueError(
                f"«{ozet['kod']} / {ozet['ad']}» deposu silinemez. "
                f"Lot: {ozet['lot_adet']}, bakiye: {ozet['bakiye']}, "
                f"hareket: {ozet['hareket']}, sayım: {ozet['sayim']}, "
                f"transfer: {ozet['transfer']}. İsterseniz pasife alabilirsiniz."
            )
        with get_session() as session:
            depo = session.get(Depo, int(depo_id))
            if depo is None:
                raise ValueError("Depo bulunamadı.")
            eski = {"kod": depo.kod, "ad": depo.ad}
            session.delete(depo)
            session.flush()
            audit_document(
                "depo_sil",
                modul="stok",
                kayit_id=str(depo_id),
                eski=eski,
            )

    @staticmethod
    def depo_pasife_al(depo_id: int) -> None:
        from database.access import yazma_zorunlu
        from database.user_audit import audit_document

        yazma_zorunlu("stok_duzenleme", "duzenleme")
        with get_session() as session:
            depo = session.get(Depo, int(depo_id))
            if depo is None:
                raise ValueError("Depo bulunamadı.")
            if getattr(depo, "varsayilan", False):
                raise ValueError(
                    "Varsayılan depo pasife alınamaz. Önce başka bir varsayılan seçin."
                )
            eski = {"aktif": depo.aktif}
            depo.aktif = False
            session.flush()
            audit_document(
                "depo_pasife",
                modul="stok",
                kayit_id=str(depo.id),
                eski=eski,
                yeni={"aktif": False, "kod": depo.kod, "ad": depo.ad},
            )

    @staticmethod
    def depo_varsayilan_yap(depo_id: int) -> None:
        from database.access import yazma_zorunlu
        from database.user_audit import audit_document

        yazma_zorunlu("stok_duzenleme", "duzenleme")
        with get_session() as session:
            depo = session.get(Depo, int(depo_id))
            if depo is None:
                raise ValueError("Depo bulunamadı.")
            if not depo.aktif:
                raise ValueError("Pasif depo varsayılan yapılamaz.")
            for d in session.scalars(select(Depo).where(Depo.varsayilan.is_(True))).all():
                d.varsayilan = False
            depo.varsayilan = True
            session.flush()
            audit_document(
                "depo_varsayilan",
                modul="stok",
                kayit_id=str(depo.id),
                yeni={"kod": depo.kod, "ad": depo.ad},
            )

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
        kod = (barkod or "").strip()
        if not kod:
            return False
        q1 = select(StokKarti.id).where(StokKarti.barkod == kod)
        q2 = select(StokBarkod.id).where(StokBarkod.barkod == kod)
        q3 = select(StokBirim.id).where(StokBirim.birim_barkod == kod)
        if haric_stok_id:
            hid = int(haric_stok_id)
            q1 = q1.where(StokKarti.id != hid)
            q2 = q2.where(StokBarkod.stok_id != hid)
            q3 = q3.where(StokBirim.stok_id != hid)
        return (
            session.scalar(q1) is not None
            or session.scalar(q2) is not None
            or session.scalar(q3) is not None
        )

    @staticmethod
    def _birimleri_sessiona_yaz(session, stok, birimler: list, *, ana_birim: str | None = None) -> list[dict]:
        """Birim satırlarını stok'a yazar (transaction içinde). Eski/yeni özeti döner."""
        ana = (ana_birim or stok.birim or "Adet").strip() or "Adet"
        eski = [
            {
                "birim_adi": b.birim_adi,
                "carpan": str(b.carpan),
                "birim_barkod": b.birim_barkod,
                "aktif": b.aktif,
            }
            for b in list(stok.birimler or [])
        ]
        stok.birimler.clear()
        session.flush()
        gorulen_ad = set()
        gorulen_barkod = set()
        for ham in birimler or []:
            kayit = _birim_kayit_normalize(ham, ana_birim=ana)
            ad = kayit["birim_adi"]
            if not ad:
                raise ValueError("Birim adı boş olamaz.")
            if ad.casefold() == ana.casefold():
                # Ana birim satırı: katsayı 1 olmalı; DB'ye alternatif olarak yazılmaz
                try:
                    c_ana = decimal(kayit["carpan"], "Ana birim katsayısı", Decimal("1"))
                except Exception:
                    c_ana = Decimal("1")
                if c_ana != 1:
                    raise ValueError("Ana birim dönüşüm katsayısı 1 olmalıdır.")
                continue
            if ad.casefold() in gorulen_ad:
                raise ValueError(f"Aynı stokta «{ad}» birimi birden fazla tanımlı.")
            gorulen_ad.add(ad.casefold())
            carpan_d = decimal(kayit["carpan"], f"{ad} temel çarpanı", Decimal("0.000001"))
            if carpan_d <= 0:
                raise ValueError(f"«{ad}» dönüşüm katsayısı sıfır veya negatif olamaz.")
            bb = kayit.get("birim_barkod")
            if bb:
                if bb.casefold() in {x.casefold() for x in gorulen_barkod}:
                    raise ValueError(f"Birim barkodu mükerrer: {bb}")
                gorulen_barkod.add(bb)
                # Aynı stokun ana barkodu veya ek barkodları
                ana_bk = (getattr(stok, "barkod", None) or "").strip()
                if ana_bk and ana_bk.casefold() == bb.casefold():
                    raise ValueError(
                        f"«{bb}» barkodu bu stokun ana barkodu olarak kayıtlı."
                    )
                for ekstra in list(getattr(stok, "barkodlar", None) or []):
                    ek = (getattr(ekstra, "barkod", None) or "").strip()
                    if ek and ek.casefold() == bb.casefold():
                        raise ValueError(
                            f"«{bb}» barkodu bu stokun başka bir barkod kaydında kullanılıyor."
                        )
                if StokService._barkod_kullaniliyor_mu(session, bb, haric_stok_id=stok.id):
                    raise ValueError(
                        f"«{bb}» barkodu başka bir stokta veya birimde kullanılıyor."
                    )
            ref_c = kayit.get("referans_carpan")
            ref_c_d = None
            if ref_c not in (None, ""):
                ref_c_d = decimal(ref_c, f"{ad} referans çarpanı", Decimal("0.000001"))
                if ref_c_d <= 0:
                    raise ValueError(f"«{ad}» referans katsayısı sıfırdan büyük olmalıdır.")
            alis_d = None
            if kayit.get("alis_fiyati") not in (None, ""):
                alis_d = decimal(kayit["alis_fiyati"], f"{ad} alış", None)
                if alis_d < 0:
                    raise ValueError(f"«{ad}» alış fiyatı negatif olamaz.")
            satis_kwargs = {}
            for i, fiyat_adi in enumerate(SATIS_FIYAT_ADLARI, start=1):
                ham_f = (kayit.get("satis_fiyatlari") or {}).get(fiyat_adi)
                if ham_f not in (None, ""):
                    tutar = decimal(ham_f, fiyat_adi, None)
                    if tutar < 0:
                        raise ValueError(f"{fiyat_adi} negatif olamaz.")
                    satis_kwargs[f"satis_{i}"] = tutar
            stok.birimler.append(
                StokBirim(
                    birim_adi=ad,
                    carpan=carpan_d,
                    referans_birim=(kayit.get("referans_birim") or ana).strip() or ana,
                    referans_carpan=ref_c_d,
                    fiyat_modu="otomatik"
                    if (kayit.get("fiyat_modu") or "").startswith("oto")
                    else "manuel",
                    alis_fiyati=alis_d,
                    alis_kullanilabilir=bool(kayit.get("alis_kullanilabilir", True)),
                    satis_kullanilabilir=bool(kayit.get("satis_kullanilabilir", True)),
                    varsayilan_goruntuleme=bool(kayit.get("varsayilan_goruntuleme", False)),
                    varsayilan_alis=bool(kayit.get("varsayilan_alis", False)),
                    varsayilan_satis=bool(kayit.get("varsayilan_satis", False)),
                    birim_barkod=bb,
                    ondalik=max(0, min(6, int(kayit.get("ondalik") or 0))),
                    aktif=bool(kayit.get("aktif", True)),
                    **satis_kwargs,
                )
            )
            StokService._secenek_ekle(session, "birim", ad)
        yeni = [
            {
                "birim_adi": b.birim_adi,
                "carpan": str(b.carpan),
                "birim_barkod": b.birim_barkod,
                "aktif": b.aktif,
            }
            for b in list(stok.birimler or [])
        ]
        return [{"eski": eski, "yeni": yeni}]

    @staticmethod
    def stok_birimleri_kaydet(
        stok_id: int,
        birimler: list,
        *,
        varsayilan_goruntuleme_birim: str | None = None,
        varsayilan_alis_birim: str | None = None,
        varsayilan_satis_birim: str | None = None,
        ana_birim: str | None = None,
    ) -> dict:
        """Birim Dönüştürücü kaydı — tek transaction, audit."""
        from database.access import yazma_zorunlu
        from database.session_manager import oturum
        from database.user_audit import audit_document

        yazma_zorunlu("stok_duzenleme", "duzenleme")
        if not stok_id:
            raise ValueError("Birim kaydı için önce stok kartını kaydedin.")
        if not oturum.firma_secili:
            raise ValueError("Aktif firma seçilmedi. Birim kaydı yapılamaz.")
        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if stok is None or getattr(stok, "is_deleted", False):
                raise ValueError("Stok kartı bulunamadı veya silinmiş.")
            # Firma bağlamı: company_db zaten firma-scoped
            if ana_birim:
                stok.birim = (ana_birim or "").strip() or stok.birim
            ozet = StokService._birimleri_sessiona_yaz(
                session, stok, birimler, ana_birim=stok.birim
            )
            if varsayilan_goruntuleme_birim is not None:
                stok.varsayilan_goruntuleme_birim = (
                    (varsayilan_goruntuleme_birim or "").strip() or None
                )
            if varsayilan_alis_birim is not None:
                stok.varsayilan_alis_birim = ((varsayilan_alis_birim or "").strip() or None)
            if varsayilan_satis_birim is not None:
                stok.varsayilan_satis_birim = ((varsayilan_satis_birim or "").strip() or None)
            for b in stok.birimler:
                if b.varsayilan_goruntuleme and not stok.varsayilan_goruntuleme_birim:
                    stok.varsayilan_goruntuleme_birim = b.birim_adi
                if b.varsayilan_alis and not stok.varsayilan_alis_birim:
                    stok.varsayilan_alis_birim = b.birim_adi
                if b.varsayilan_satis and not stok.varsayilan_satis_birim:
                    stok.varsayilan_satis_birim = b.birim_adi
            session.flush()
            audit_document(
                "stok_birim_kaydet",
                modul="stok",
                kayit_id=str(stok.id),
                eski=ozet[0]["eski"] if ozet else None,
                yeni={
                    "birimler": ozet[0]["yeni"] if ozet else [],
                    "stok_id": int(stok.id),
                    "stok_kodu": stok.stok_kodu,
                    "firma_id": getattr(oturum, "company_id", None),
                    "firma_kodu": getattr(oturum, "firma_kodu", None),
                    "kullanici": getattr(oturum, "kullanici_adi", None),
                    "varsayilan_goruntuleme_birim": stok.varsayilan_goruntuleme_birim,
                    "varsayilan_alis_birim": stok.varsayilan_alis_birim,
                    "varsayilan_satis_birim": stok.varsayilan_satis_birim,
                },
            )
            return {
                "stok_id": int(stok.id),
                "birim_adet": len(stok.birimler),
                "birimler": StokService.birimleri_dict_listesi(stok),
                "varsayilan_goruntuleme_birim": stok.varsayilan_goruntuleme_birim,
                "varsayilan_alis_birim": stok.varsayilan_alis_birim,
                "varsayilan_satis_birim": stok.varsayilan_satis_birim,
                "ana_birim": stok.birim,
            }

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
    def barkod_ile_bul(barkod: str):
        """Tam barkod eşleşmesi → stok + birim çarpanı + satış fiyatı (soft-delete dışı).

        Dönüş (dict) veya None:
          stok_id, stok_kodu, stok_adi, barkod, birim, carpan, birim_fiyat,
          miktar (okutunca eklenecek miktar; paket/koli çarpanı), mevcut_stok,
          kdv_orani (stok kartındaki seçimli KDV)
        """
        kod = (barkod or "").strip()
        if not kod:
            return None

        def _aktif_silinmemis(stok):
            if stok is None:
                return False
            if not stok.aktif:
                return False
            if bool(getattr(stok, "is_deleted", False)):
                return False
            return True

        def _birim_carpani(stok, birim_adi) -> Decimal:
            return StokService.birim_carpani(stok, birim_adi)

        def _barkod_fiyati(stok, barkod_kayit) -> Decimal:
            barkod_birim = (
                (barkod_kayit.birim if barkod_kayit else None) or stok.birim or "Adet"
            ).strip() or "Adet"
            if barkod_kayit is not None:
                bf = Decimal(str(barkod_kayit.fiyat or 0))
                if bf > 0:
                    return bf
                fiyat_adi = (barkod_kayit.fiyat_adi or "").strip() or "SATIŞ FİYATI 1"
                birim_f = StokService.birim_fiyati_getir(stok, barkod_birim, fiyat_adi=fiyat_adi)
                if birim_f is not None and birim_f > 0:
                    return birim_f
            birim_f = StokService.birim_fiyati_getir(stok, barkod_birim, fiyat_adi="SATIŞ FİYATI 1")
            if birim_f is not None:
                return birim_f
            for f in stok.fiyatlar or []:
                ad = (f.fiyat_adi or "").strip().upper()
                if ad == "SATIŞ FİYATI 1":
                    return Decimal(str(f.tutar))
            for f in stok.fiyatlar or []:
                ad = (f.fiyat_adi or "").strip().upper()
                if ad.startswith("SATIŞ FİYATI"):
                    return Decimal(str(f.tutar))
            return Decimal("0")

        def _sonuc(stok, barkod_kayit=None):
            barkod_birim = (
                (barkod_kayit.birim if barkod_kayit else None) or stok.birim or "Adet"
            ).strip() or "Adet"
            # Birim barkodu eşleşmesi
            if barkod_kayit is None:
                for b in stok.birimler or []:
                    if (getattr(b, "birim_barkod", None) or "").strip() == kod:
                        barkod_birim = (b.birim_adi or barkod_birim).strip()
                        break
            carpan = _birim_carpani(stok, barkod_birim)
            paket_fiyat = _barkod_fiyati(stok, barkod_kayit)
            # Birime özel fiyat zaten paket/koli tutarıdır — ana birime bölme
            birim_ozel = StokService.birim_fiyati_getir(
                stok, barkod_birim, fiyat_adi="SATIŞ FİYATI 1"
            )
            if birim_ozel is not None and birim_ozel > 0 and carpan != Decimal("1"):
                # Hızlı satışta miktar = carpan (temel), birim_fiyat = temel başına
                birim_fiyat = (birim_ozel / carpan).quantize(Decimal("0.0001"))
            elif carpan != Decimal("1") and paket_fiyat > 0:
                birim_fiyat = (paket_fiyat / carpan).quantize(Decimal("0.0001"))
            else:
                birim_fiyat = paket_fiyat
            mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
            kdv = getattr(stok, "kdv_orani", None)
            if kdv is None:
                from database.fatura_kdv_service import firma_varsayilan_kdv_orani

                kdv = firma_varsayilan_kdv_orani()
            return {
                "stok_id": stok.id,
                "stok_kodu": stok.stok_kodu,
                "stok_adi": stok.stok_adi,
                "barkod": kod,
                "birim": (stok.birim or "Adet").strip() or "Adet",
                "barkod_birim": barkod_birim,
                "carpan": carpan,
                "miktar": carpan if carpan > 0 else Decimal("1"),
                "birim_fiyat": birim_fiyat,
                "paket_fiyat": paket_fiyat,
                "mevcut_stok": mevcut,
                "kdv_orani": decimal(kdv, "KDV", Decimal("0")),
            }

        with get_session() as session:
            kayit = session.scalar(
                select(StokBarkod)
                .where(StokBarkod.barkod == kod)
                .options(
                    selectinload(StokBarkod.stok).selectinload(StokKarti.fiyatlar),
                    selectinload(StokBarkod.stok).selectinload(StokKarti.birimler),
                    selectinload(StokBarkod.stok).selectinload(StokKarti.lotlar),
                )
            )
            if kayit is not None and _aktif_silinmemis(kayit.stok):
                return _sonuc(kayit.stok, kayit)

            stok = session.scalar(
                select(StokKarti)
                .where(
                    StokKarti.barkod == kod,
                    StokKarti.aktif.is_(True),
                    or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                )
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.birimler),
                    selectinload(StokKarti.lotlar),
                )
            )
            if stok is not None:
                return _sonuc(stok, None)

            # Birime özel barkod
            birim_kayit = session.scalar(
                select(StokBirim)
                .where(StokBirim.birim_barkod == kod, StokBirim.aktif.is_(True))
                .options(
                    selectinload(StokBirim.stok).selectinload(StokKarti.fiyatlar),
                    selectinload(StokBirim.stok).selectinload(StokKarti.birimler),
                    selectinload(StokBirim.stok).selectinload(StokKarti.lotlar),
                )
            )
            if birim_kayit is not None and _aktif_silinmemis(birim_kayit.stok):
                # Sahte barkod kaydı gibi davran: birim adını taşı
                class _Sahte:
                    birim = birim_kayit.birim_adi
                    fiyat = Decimal("0")
                    fiyat_adi = "SATIŞ FİYATI 1"

                return _sonuc(birim_kayit.stok, _Sahte())
        return None

    # —— Hızlı Satış Aşama 3: grup / kart listeleri ——

    SIK_SATILANLAR_KOD = "__SIK_SATILANLAR__"
    GRUP_YOK_KOD = "__GRUP_YOK__"

    @staticmethod
    def _aktif_stok_kosulu():
        return (
            StokKarti.aktif.is_(True),
            or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
        )

    @staticmethod
    def _hizli_satis_fiyat(stok, fiyat_adi: str | None = None) -> Decimal:
        """Stok kartından satış fiyatı; fiyat_adi verilirse o liste (yoksa SF1 yedek)."""
        hedef = (fiyat_adi or "").strip().upper()
        if hedef in ESKI_FIYAT_ESLEME:
            hedef = ESKI_FIYAT_ESLEME[hedef].upper()
        if hedef:
            for f in stok.fiyatlar or []:
                ad = (f.fiyat_adi or "").strip().upper()
                if ad == hedef:
                    return Decimal(str(f.tutar))
        for f in stok.fiyatlar or []:
            ad = (f.fiyat_adi or "").strip().upper()
            if ad == "SATIŞ FİYATI 1":
                return Decimal(str(f.tutar))
        for f in stok.fiyatlar or []:
            ad = (f.fiyat_adi or "").strip().upper()
            if ad.startswith("SATIŞ FİYATI"):
                return Decimal(str(f.tutar))
        return Decimal("0")

    @staticmethod
    def satis_fiyati_adi_ile(stok_kodu, fiyat_adi: str | None = None, varsayilan=Decimal("0")):
        """Belirtilen satış fiyat listesi tutarı; yoksa SF1 / ilk satış fiyatı."""
        from hizli_satis_musteri import VARSAYILAN_FIYAT_LISTESI

        kod = (stok_kodu or "").strip()
        if not kod:
            return Decimal(str(varsayilan))
        hedef = (fiyat_adi or VARSAYILAN_FIYAT_LISTESI).strip().upper()
        if hedef in ESKI_FIYAT_ESLEME:
            hedef = ESKI_FIYAT_ESLEME[hedef].upper()
        fiyatlar = StokService.fiyatlar(kod)
        for fiyat in fiyatlar:
            if (fiyat.fiyat_adi or "").strip().upper() == hedef:
                return Decimal(str(fiyat.tutar))
        return StokService.satis_fiyati_1(kod, varsayilan=varsayilan)

    @staticmethod
    def _hizli_satis_resim_yolu(stok) -> str | None:
        resimler = list(stok.resimler or [])
        if not resimler:
            return None
        resimler.sort(key=lambda r: int(getattr(r, "sira", 0) or 0))
        yol = (resimler[0].dosya_yolu or "").strip()
        return yol or None

    @staticmethod
    def _hizli_satis_birincil_barkod(stok) -> str | None:
        """Ana barkod; yoksa stok_barkodlari listesindeki ilk dolu kod."""
        ana = (getattr(stok, "barkod", None) or "").strip()
        if ana:
            return ana
        for kayit in getattr(stok, "barkodlar", None) or []:
            kod = (getattr(kayit, "barkod", None) or "").strip()
            if kod:
                return kod
        return None

    @staticmethod
    def _hizli_satis_urun_dict(stok, fiyat_adi: str | None = None) -> dict:
        # Depo miktarı = tüm lotların kalan_miktar toplamı (aktif stok kartları üzerinden)
        mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
        kdv = getattr(stok, "kdv_orani", None)
        if kdv is None:
            try:
                from database.fatura_kdv_service import firma_varsayilan_kdv_orani

                kdv = firma_varsayilan_kdv_orani()
            except Exception:
                kdv = VARSAYILAN_KDV_ORANI
        return {
            "stok_id": int(stok.id),
            "stok_kodu": stok.stok_kodu,
            "stok_adi": stok.stok_adi,
            "birim": (stok.birim or "Adet").strip() or "Adet",
            "birim_fiyat": StokService._hizli_satis_fiyat(stok, fiyat_adi),
            "miktar": Decimal("1"),
            "carpan": Decimal("1"),
            "barkod": StokService._hizli_satis_birincil_barkod(stok),
            "mevcut_stok": mevcut,
            "resim_yolu": StokService._hizli_satis_resim_yolu(stok),
            "rapor_grubu": (stok.rapor_grubu or "").strip() or None,
            "fiyat_listesi": (fiyat_adi or "").strip() or None,
            "kdv_orani": decimal(kdv, "KDV", Decimal("0")),
        }

    @staticmethod
    def hizli_satis_gruplari():
        """Sol panel grupları.

        Pin sistemi aktifse: Sık Satılanlar + hızlı satış grupları.
        Değilse: Sık Satılanlar + rapor_grubu (eski davranış).
        """
        try:
            from database.hizli_satis_service import HizliSatisService

            if HizliSatisService.pin_sistemi_aktif():
                gruplar: list[dict] = [
                    {
                        "kod": StokService.SIK_SATILANLAR_KOD,
                        "ad": "Sık Satılanlar",
                        "ozel": True,
                    }
                ]
                gruplar.extend(HizliSatisService.hizli_gruplari_listele())
                return gruplar
        except Exception:
            pass

        gruplar: list[dict] = [
            {
                "kod": StokService.SIK_SATILANLAR_KOD,
                "ad": "Sık Satılanlar",
                "ozel": True,
            }
        ]
        adlar: list[str] = []
        seen: set[str] = set()

        def _ekle(ad: str) -> None:
            temiz = (ad or "").strip()
            if not temiz:
                return
            anahtar = temiz.casefold()
            if anahtar in seen:
                return
            seen.add(anahtar)
            adlar.append(temiz)

        with get_session() as session:
            for ad in session.scalars(
                select(StokSecenek.ad)
                .where(StokSecenek.tur == "rapor_grubu")
                .order_by(StokSecenek.ad)
            ).all():
                _ekle(ad)

            for ad in session.scalars(
                select(StokKarti.rapor_grubu)
                .where(
                    *StokService._aktif_stok_kosulu(),
                    StokKarti.rapor_grubu.is_not(None),
                    StokKarti.rapor_grubu != "",
                )
                .distinct()
                .order_by(StokKarti.rapor_grubu)
            ).all():
                _ekle(ad)

            grup_yok_var = session.scalar(
                select(func.count())
                .select_from(StokKarti)
                .where(
                    *StokService._aktif_stok_kosulu(),
                    or_(StokKarti.rapor_grubu.is_(None), StokKarti.rapor_grubu == ""),
                )
            )

        for ad in sorted(adlar, key=lambda x: x.casefold()):
            gruplar.append({"kod": ad, "ad": ad, "ozel": False})

        if grup_yok_var:
            gruplar.append(
                {
                    "kod": StokService.GRUP_YOK_KOD,
                    "ad": "Grup Yok",
                    "ozel": False,
                }
            )
        return gruplar

    @staticmethod
    def hizli_satis_sik_satilan_kodlari(limit: int = 48) -> list[str]:
        """Onaylı satış faturalarından en çok satılan stok kodları (best-effort)."""
        limit = max(1, min(int(limit or 48), 200))
        try:
            from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        except Exception:
            return []

        with get_session() as session:
            try:
                satirlar = session.execute(
                    select(
                        SatisFaturasiSatiri.urun_kodu,
                        func.sum(SatisFaturasiSatiri.miktar).label("adet"),
                    )
                    .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiSatiri.fatura_id)
                    .where(
                        SatisFaturasi.onaylandi.is_(True),
                        or_(
                            SatisFaturasi.is_deleted.is_(False),
                            SatisFaturasi.is_deleted.is_(None),
                        ),
                        SatisFaturasi.durum != "İPTAL",
                    )
                    .group_by(SatisFaturasiSatiri.urun_kodu)
                    .order_by(func.sum(SatisFaturasiSatiri.miktar).desc())
                    .limit(limit)
                ).all()
            except Exception:
                return []
            return [str(r[0]).strip() for r in satirlar if r[0] and str(r[0]).strip()]

    @staticmethod
    def hizli_satis_urunleri(
        grup_kod: str | None = None,
        *,
        limit: int = 36,
        offset: int = 0,
        fiyat_adi: str | None = None,
    ) -> dict:
        """Gruba göre ürün kartı verisi (soft-delete dışı, aktif).

        HSG:* kodları → pinli ürünler. Sık Satılanlar / rapor_grubu eski yol.
        Dönüş: {"urunler": [dict, ...], "toplam": int, "limit": int, "offset": int}
        """
        limit = max(1, min(int(limit or 36), 120))
        offset = max(0, int(offset or 0))
        kod = (grup_kod or "").strip()

        if kod.startswith("HSG:"):
            from database.hizli_satis_service import HizliSatisService

            return HizliSatisService.pinli_urunleri(
                grup_kod=kod,
                limit=limit,
                offset=offset,
                fiyat_adi=fiyat_adi,
            )

        with get_session() as session:
            opts = (
                selectinload(StokKarti.fiyatlar),
                selectinload(StokKarti.lotlar),
                selectinload(StokKarti.resimler),
                selectinload(StokKarti.barkodlar),
            )

            if kod == StokService.SIK_SATILANLAR_KOD:
                kodlar = StokService.hizli_satis_sik_satilan_kodlari(
                    limit=max(limit + offset, 48)
                )
                if not kodlar:
                    return {"urunler": [], "toplam": 0, "limit": limit, "offset": offset}
                # Sıra: satış adedine göre (kodlar zaten sıralı)
                stoklar = list(
                    session.scalars(
                        select(StokKarti)
                        .where(
                            *StokService._aktif_stok_kosulu(),
                            StokKarti.stok_kodu.in_(kodlar),
                        )
                        .options(*opts)
                    ).all()
                )
                sirali = {s.stok_kodu: s for s in stoklar}
                sirali_liste = [sirali[k] for k in kodlar if k in sirali]
                toplam = len(sirali_liste)
                dilim = sirali_liste[offset : offset + limit]
                return {
                    "urunler": [
                        StokService._hizli_satis_urun_dict(s, fiyat_adi) for s in dilim
                    ],
                    "toplam": toplam,
                    "limit": limit,
                    "offset": offset,
                }

            kosullar = list(StokService._aktif_stok_kosulu())
            if kod == StokService.GRUP_YOK_KOD or not kod:
                kosullar.append(
                    or_(StokKarti.rapor_grubu.is_(None), StokKarti.rapor_grubu == "")
                )
            else:
                kosullar.append(func.lower(StokKarti.rapor_grubu) == kod.casefold())

            toplam = (
                session.scalar(
                    select(func.count()).select_from(StokKarti).where(*kosullar)
                )
                or 0
            )
            stoklar = list(
                session.scalars(
                    select(StokKarti)
                    .where(*kosullar)
                    .options(*opts)
                    .order_by(StokKarti.stok_adi)
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            return {
                "urunler": [
                    StokService._hizli_satis_urun_dict(s, fiyat_adi) for s in stoklar
                ],
                "toplam": int(toplam),
                "limit": limit,
                "offset": offset,
            }

    @staticmethod
    def stok_rapor_grubu_ata(stok_id: int, rapor_grubu: str) -> dict:
        """Ana stok kartına rapor_grubu (stok grubu) yazar; StokSecenek'e de ekler."""
        temiz = (rapor_grubu or "").strip()
        if not temiz:
            raise ValueError("Stok grubu boş olamaz.")
        with get_session() as session:
            stok = session.scalar(
                select(StokKarti).where(
                    StokKarti.id == int(stok_id),
                    *StokService._aktif_stok_kosulu(),
                )
            )
            if not stok:
                raise ValueError("Stok kartı bulunamadı veya pasif/silinmiş.")
            StokService._secenek_ekle(session, "rapor_grubu", temiz)
            stok.rapor_grubu = temiz
            session.flush()
            secenek = session.scalar(
                select(StokSecenek).where(
                    StokSecenek.tur == "rapor_grubu",
                    func.lower(StokSecenek.ad) == temiz.casefold(),
                )
            )
            return {
                "stok_id": int(stok.id),
                "stok_kodu": stok.stok_kodu,
                "rapor_grubu": stok.rapor_grubu,
                "stok_secenek_id": int(secenek.id) if secenek else None,
            }

    @staticmethod
    def stok_rapor_grubu_toplu_ata(stok_idler: list[int], rapor_grubu: str) -> dict:
        """Tek transaction; hata olursa rollback (get_session context)."""
        temiz = (rapor_grubu or "").strip()
        if not temiz:
            raise ValueError("Stok grubu boş olamaz.")
        idler = [int(x) for x in (stok_idler or []) if x]
        if not idler:
            raise ValueError("Ürün seçilmedi.")
        with get_session() as session:
            StokService._secenek_ekle(session, "rapor_grubu", temiz)
            guncellenen = 0
            for sid in idler:
                stok = session.scalar(
                    select(StokKarti).where(
                        StokKarti.id == sid,
                        *StokService._aktif_stok_kosulu(),
                    )
                )
                if not stok:
                    raise ValueError(f"Stok bulunamadı (id={sid}).")
                stok.rapor_grubu = temiz
                guncellenen += 1
            session.flush()
            secenek = session.scalar(
                select(StokSecenek).where(
                    StokSecenek.tur == "rapor_grubu",
                    func.lower(StokSecenek.ad) == temiz.casefold(),
                )
            )
            return {
                "guncellenen": guncellenen,
                "rapor_grubu": temiz,
                "stok_secenek_id": int(secenek.id) if secenek else None,
            }

    @staticmethod
    def hizli_satis_urun_ara(
        arama: str = "",
        *,
        rapor_grubu: str | None = None,
        marka: str | None = None,
        sadece_stokta: bool = False,
        sadece_grupsuz: bool = False,
        limit: int = 80,
        offset: int = 0,
        fiyat_adi: str | None = None,
    ) -> dict:
        """ÜRÜN EKLE seçici: kod/ad/barkod/marka/grup/raf — soft-delete dışı."""
        limit = max(1, min(int(limit or 80), 200))
        offset = max(0, int(offset or 0))
        qmetin = (arama or "").strip()
        marka_f = (marka or "").strip()
        rapor_f = (rapor_grubu or "").strip()

        with get_session() as session:
            kosullar = list(StokService._aktif_stok_kosulu())
            if sadece_grupsuz:
                kosullar.append(
                    or_(StokKarti.rapor_grubu.is_(None), StokKarti.rapor_grubu == "")
                )
            elif rapor_f and rapor_f not in ("*", "(Tümü)", "Tümü"):
                kosullar.append(
                    func.lower(StokKarti.rapor_grubu) == rapor_f.casefold()
                )
            if marka_f and marka_f not in ("*", "(Tümü)", "Tümü"):
                kosullar.append(func.lower(StokKarti.marka) == marka_f.casefold())

            if qmetin:
                ifade = f"%{qmetin}%"
                barkod_alt = select(StokBarkod.stok_id).where(StokBarkod.barkod.ilike(ifade))
                kosullar.append(
                    or_(
                        StokKarti.stok_kodu.ilike(ifade),
                        StokKarti.stok_adi.ilike(ifade),
                        StokKarti.barkod.ilike(ifade),
                        StokKarti.id.in_(barkod_alt),
                        StokKarti.marka.ilike(ifade),
                        StokKarti.rapor_grubu.ilike(ifade),
                        StokKarti.raf_yeri.ilike(ifade),
                    )
                )

            if sadece_stokta:
                stokta_alt = (
                    select(StokLotu.stok_id)
                    .where(StokLotu.kalan_miktar > 0)
                    .group_by(StokLotu.stok_id)
                )
                kosullar.append(StokKarti.id.in_(stokta_alt))

            toplam = (
                session.scalar(
                    select(func.count()).select_from(StokKarti).where(*kosullar)
                )
                or 0
            )
            stoklar = list(
                session.scalars(
                    select(StokKarti)
                    .where(*kosullar)
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.barkodlar),
                        selectinload(StokKarti.resimler),
                        selectinload(StokKarti.birimler),
                    )
                    .order_by(StokKarti.stok_adi)
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            satirlar = []
            for s in stoklar:
                d = StokService._hizli_satis_urun_dict(s, fiyat_adi)
                d.update(
                    {
                        "marka": (s.marka or "").strip() or None,
                        "raf_yeri": (s.raf_yeri or "").strip() or None,
                        "muhasebe_kdv_satis_kodu": (s.muhasebe_kdv_satis_kodu or "").strip()
                        or None,
                    }
                )
                satirlar.append(d)
            return {
                "urunler": satirlar,
                "toplam": int(toplam),
                "limit": limit,
                "offset": offset,
            }

    @staticmethod
    def stoklari_ara(arama="", limit: int | None = None):
        """Stok ara. limit verilirse en fazla o kadar kayıt döner (fatura araması).

        Dolu sorguda çoklu blok / sıra bağımsız SearchService kullanılır.
        """
        ham = (arama or "").strip()
        if ham:
            from database.search_service import SearchService, tokenize_query

            if tokenize_query(ham):
                lim = 100 if limit is None else max(1, min(int(limit), 200))
                sonuc = SearchService.search_stocks(ham, limit=lim)
                return list(sonuc.get("urunler") or [])
            return []

        with get_session() as session:
            q = (
                select(StokKarti)
                .where(
                    StokKarti.aktif.is_(True),
                    or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                )
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.lotlar),
                    selectinload(StokKarti.barkodlar),
                )
                .order_by(StokKarti.stok_adi)
            )
            if limit is not None:
                q = q.limit(max(1, min(int(limit), 200)))
            return list(session.scalars(q).all())

    @staticmethod
    def stoklari_ayrintili_ara(
        kelimeler=None,
        *,
        yontem: str = "and",
        hizli_arama: str = "",
        min_harf: int = 2,
    ):
        """Ürün adında çoklu kelime araması (AND/OR), hızlı arama ile birleşik.

        Her dolu kutu bağımsız içerir koşuludur; kelime sırası önemli değildir.
        Yanlış:  stok_adi LIKE '%SAMET DEVE FREN%'  (birleşik/sıralı)
        Doğru:   LIKE '%SAMET%' AND LIKE '%DEVE%' AND LIKE '%FREN%'

        kelimeler: en fazla 5 ifade; boşlar atılır. Her dolu kutu ≥ min_harf olmalı.
        yontem: 'and' = tüm kelimeler (sıra bağımsız), 'or' = herhangi biri.
        hizli_arama: üstteki kod/ad/barkod kutusu (mevcut stoklari_ara mantığı).
        """
        from database.turkce_normalize import arama_like_varyantlari, turkce_normalize

        min_harf = max(1, int(min_harf or 2))
        yontem = (yontem or "and").strip().lower()
        if yontem not in ("and", "or"):
            yontem = "and"

        temiz = []
        for k in kelimeler or []:
            t = (k or "").strip()
            if not t:
                continue
            if len(t) < min_harf:
                continue
            temiz.append(t)
        # Aynı ifadeyi bir kez kullan (sıra korunmaz; set değil liste — ama birleşik metin yok)
        gorulen = set()
        benzersiz = []
        for t in temiz:
            anahtar = turkce_normalize(t)
            if not anahtar or anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            benzersiz.append(t)
        temiz = benzersiz[:5]

        hizli = (hizli_arama or "").strip()

        # AND + dolu bloklar: ortak SearchService (çoklu alan, sıra bağımsız)
        if yontem == "and" and (temiz or hizli):
            from database.search_service import SearchService, tokenize_query

            parcalar = []
            if hizli:
                parcalar.append(hizli)
            parcalar.extend(temiz)
            birlesik = " ".join(parcalar).strip()
            if tokenize_query(birlesik):
                return list(
                    SearchService.search_stocks(birlesik, limit=250).get("urunler") or []
                )
            return []

        with get_session() as session:
            q = (
                select(StokKarti)
                .where(
                    StokKarti.aktif.is_(True),
                    or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                )
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.lotlar),
                    selectinload(StokKarti.barkodlar),
                )
                .order_by(StokKarti.stok_adi)
            )

            if hizli:
                ifade = f"%{hizli}%"
                barkod_alt = select(StokBarkod.stok_id).where(StokBarkod.barkod.ilike(ifade))
                hizli_kosul = [
                    StokKarti.stok_kodu.ilike(ifade),
                    StokKarti.barkod.ilike(ifade),
                    StokKarti.id.in_(barkod_alt),
                ]
                if len(hizli) >= 2:
                    hizli_kosul.append(StokKarti.stok_adi.ilike(ifade))
                q = q.where(or_(*hizli_kosul))

            # OR yolu: her kelime ürün adında (eski davranış)
            kelime_kosullari = []
            for kelime in temiz:
                patterns = arama_like_varyantlari(kelime, max_n=16)
                if not patterns:
                    patterns = [f"%{kelime}%"]
                kelime_kosullari.append(
                    or_(*[StokKarti.stok_adi.ilike(p) for p in patterns])
                )

            if kelime_kosullari:
                q = q.where(or_(*kelime_kosullari))

            adaylar = list(session.scalars(q).all())

        if not temiz:
            return adaylar

        n_kelimeler = [turkce_normalize(k) for k in temiz]
        sonuc = []
        gorulen_id = set()
        for stok in adaylar:
            if stok.id in gorulen_id:
                continue
            n_ad = turkce_normalize(stok.stok_adi or "")
            eslesti = any(nk in n_ad for nk in n_kelimeler if nk)
            if eslesti:
                gorulen_id.add(stok.id)
                sonuc.append(stok)
        return sonuc

    @staticmethod
    def stok_liste_filtre_secenekleri():
        """Filtre paneli için grup / tür / birim / KDV / depo listeleri."""
        with get_session() as session:
            gruplar = [
                g
                for g in session.scalars(
                    select(StokKarti.rapor_grubu)
                    .where(StokKarti.rapor_grubu.is_not(None), StokKarti.rapor_grubu != "")
                    .distinct()
                    .order_by(StokKarti.rapor_grubu)
                ).all()
            ]
            turler = [
                t
                for t in session.scalars(
                    select(StokKarti.kart_turu)
                    .where(StokKarti.kart_turu.is_not(None), StokKarti.kart_turu != "")
                    .distinct()
                    .order_by(StokKarti.kart_turu)
                ).all()
            ]
            birimler = [
                b
                for b in session.scalars(
                    select(StokKarti.birim)
                    .where(StokKarti.birim.is_not(None), StokKarti.birim != "")
                    .distinct()
                    .order_by(StokKarti.birim)
                ).all()
            ]
            kdvler = [
                f"{Decimal(k):f}".rstrip("0").rstrip(".")
                for k in session.scalars(
                    select(StokKarti.kdv_orani).where(StokKarti.kdv_orani.is_not(None)).distinct()
                ).all()
                if k is not None
            ]
            kdvler = sorted(set(kdvler), key=lambda x: Decimal(x.replace(",", ".") if "," in x else x))
            depolar = list(
                session.scalars(select(Depo.ad).where(Depo.aktif.is_(True)).order_by(Depo.ad)).all()
            )
        ana_gruplar = []
        try:
            from database.stok_grup_service import SEVIYE_ANA, StokGrupService

            ana_gruplar = StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True)
        except Exception:
            ana_gruplar = []
        return {
            "gruplar": gruplar,
            "kart_turleri": turler,
            "birimler": birimler,
            "kdv_oranlari": kdvler,
            "depolar": depolar,
            "ana_gruplar": ana_gruplar,
            "tali_gruplar": [],
            "alt_gruplar": [],
        }

    @staticmethod
    def stoklari_liste_filtreli(
        kelimeler=None,
        *,
        yontem: str = "and",
        hizli_arama: str = "",
        min_harf: int = 2,
        filtre: dict | None = None,
        limit: int = 250,
        offset: int = 0,
        siralama: str | None = None,
        siralama_desc: bool = False,
        alis_goster: bool = True,
    ):
        """Stok listesi: hızlı + ayrıntılı + gelişmiş filtre; ayrı fiyat alanları.

        Dönüş: {"satirlar": [...], "toplam": int, "gosterilen": int}
        Her satır: id + display değerleri + sort sayısal alanlar.
        """
        from database.turkce_normalize import arama_like_varyantlari, turkce_normalize

        filtre = dict(filtre or {})
        # Filtre panelindeki ek metin → hızlı aramaya birleştir
        ekstra_metin = (filtre.get("metin") or "").strip()
        hizli = (hizli_arama or "").strip()
        if ekstra_metin and ekstra_metin.casefold() not in hizli.casefold():
            hizli = f"{hizli} {ekstra_metin}".strip() if hizli else ekstra_metin

        min_harf = max(1, int(min_harf or 2))
        yontem = (yontem or "and").strip().lower()
        if yontem not in ("and", "or"):
            yontem = "and"
        limit = max(1, min(int(limit or 250), 500))
        offset = max(0, int(offset or 0))

        temiz = []
        for k in kelimeler or []:
            t = (k or "").strip()
            if t and len(t) >= min_harf:
                temiz.append(t)
        gorulen = set()
        benzersiz = []
        for t in temiz:
            anahtar = turkce_normalize(t)
            if not anahtar or anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            benzersiz.append(t)
        temiz = benzersiz[:5]

        aktiflik = str(filtre.get("aktiflik") or "aktif").lower()
        stok_durumu = str(filtre.get("stok_durumu") or "tumu").lower()

        miktar_sub = (
            select(
                StokLotu.stok_id.label("stok_id"),
                func.coalesce(func.sum(StokLotu.kalan_miktar), 0).label("miktar"),
            )
            .group_by(StokLotu.stok_id)
        )
        depolar = [d for d in (filtre.get("depolar") or []) if d]
        if depolar:
            miktar_sub = (
                select(
                    StokLotu.stok_id.label("stok_id"),
                    func.coalesce(func.sum(StokLotu.kalan_miktar), 0).label("miktar"),
                )
                .join(Depo, Depo.id == StokLotu.depo_id)
                .where(Depo.ad.in_(depolar))
                .group_by(StokLotu.stok_id)
            )
        miktar_sub = miktar_sub.subquery()

        alis_sub = (
            select(StokFiyati.stok_id.label("stok_id"), StokFiyati.tutar.label("tutar"))
            .where(StokFiyati.fiyat_adi == "ALIŞ FİYATI")
            .subquery()
        )
        satis_sub = (
            select(StokFiyati.stok_id.label("stok_id"), StokFiyati.tutar.label("tutar"))
            .where(StokFiyati.fiyat_adi == "SATIŞ FİYATI 1")
            .subquery()
        )

        with get_session() as session:
            q = (
                select(
                    StokKarti,
                    func.coalesce(miktar_sub.c.miktar, 0).label("toplam_miktar"),
                    alis_sub.c.tutar.label("alis_tutar"),
                    satis_sub.c.tutar.label("satis1_tutar"),
                )
                .outerjoin(miktar_sub, miktar_sub.c.stok_id == StokKarti.id)
                .outerjoin(alis_sub, alis_sub.c.stok_id == StokKarti.id)
                .outerjoin(satis_sub, satis_sub.c.stok_id == StokKarti.id)
                .where(or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)))
                .options(
                    selectinload(StokKarti.fiyatlar),
                    selectinload(StokKarti.barkodlar),
                )
            )

            if aktiflik == "aktif":
                q = q.where(StokKarti.aktif.is_(True))
            elif aktiflik == "pasif":
                q = q.where(StokKarti.aktif.is_(False))

            from database.search_service import SearchService, tokenize_query

            # Hızlı + kelime kutuları: AND ise ortak SearchService
            birlesik_parca = []
            if hizli:
                birlesik_parca.append(hizli)
            if temiz and yontem == "and":
                birlesik_parca.extend(temiz)
            birlesik = " ".join(birlesik_parca).strip()
            if birlesik and tokenize_query(birlesik):
                hit_ids = [
                    int(s.id)
                    for s in (
                        SearchService.search_stocks(
                            birlesik,
                            limit=400,
                            sadece_aktif=(aktiflik == "aktif"),
                        ).get("urunler")
                        or []
                    )
                ]
                if not hit_ids:
                    q = q.where(StokKarti.id == -1)
                else:
                    q = q.where(StokKarti.id.in_(hit_ids))
            elif birlesik:
                q = q.where(StokKarti.id == -1)
            elif temiz:
                # OR yolu (veya AND olmadan kalan kelimeler)
                kelime_kosullari = []
                for kelime in temiz:
                    patterns = arama_like_varyantlari(kelime, max_n=16) or [f"%{kelime}%"]
                    kelime_kosullari.append(
                        or_(*[StokKarti.stok_adi.ilike(p) for p in patterns])
                    )
                if kelime_kosullari:
                    q = q.where(
                        or_(*kelime_kosullari) if yontem == "or" else and_(*kelime_kosullari)
                    )

            gruplar = [g for g in (filtre.get("gruplar") or []) if g]
            if gruplar:
                q = q.where(StokKarti.rapor_grubu.in_(gruplar))
            # Üç seviyeli grup filtreleri (kademeli; üst seçim altları da kapsar)
            ana_gid = filtre.get("ana_grup_id")
            tali_gid = filtre.get("tali_grup_id")
            alt_gid = filtre.get("alt_grup_id")
            if alt_gid:
                q = q.where(StokKarti.alt_grup_id == int(alt_gid))
            elif tali_gid:
                q = q.where(StokKarti.tali_grup_id == int(tali_gid))
            elif ana_gid:
                q = q.where(StokKarti.ana_grup_id == int(ana_gid))
            turler = [t for t in (filtre.get("kart_turleri") or []) if t]
            if turler:
                q = q.where(StokKarti.kart_turu.in_(turler))
            birimler = [b for b in (filtre.get("birimler") or []) if b]
            if birimler:
                q = q.where(StokKarti.birim.in_(birimler))
            kdvler = []
            for k in filtre.get("kdv_oranlari") or []:
                try:
                    kdvler.append(Decimal(str(k).replace(",", ".")))
                except Exception:
                    pass
            if kdvler:
                q = q.where(StokKarti.kdv_orani.in_(kdvler))

            def _aralik_kosul(kolon, min_v, max_v, bos_dahil):
                kosullar = []
                if min_v is not None:
                    kosullar.append(kolon >= min_v)
                if max_v is not None:
                    kosullar.append(kolon <= max_v)
                if not kosullar:
                    return None
                aralik = and_(*kosullar)
                if bos_dahil:
                    return or_(kolon.is_(None), aralik)
                return and_(kolon.is_not(None), aralik)

            if alis_goster:
                alis_k = _aralik_kosul(
                    alis_sub.c.tutar,
                    filtre.get("alis_min"),
                    filtre.get("alis_max"),
                    bool(filtre.get("alis_bos_dahil")),
                )
                if alis_k is not None:
                    q = q.where(alis_k)
            satis_k = _aralik_kosul(
                satis_sub.c.tutar,
                filtre.get("satis1_min"),
                filtre.get("satis1_max"),
                bool(filtre.get("satis1_bos_dahil")),
            )
            if satis_k is not None:
                q = q.where(satis_k)

            miktar_kol = func.coalesce(miktar_sub.c.miktar, 0)
            miktar_k = _aralik_kosul(
                miktar_kol,
                filtre.get("miktar_min"),
                filtre.get("miktar_max"),
                False,
            )
            if miktar_k is not None:
                q = q.where(miktar_k)

            if stok_durumu == "var":
                q = q.where(miktar_kol > 0)
            elif stok_durumu == "sifir":
                q = q.where(miktar_kol == 0)
            elif stok_durumu == "eksi":
                q = q.where(miktar_kol < 0)

            # Ayrıntılı kelime kesinleştirme için önce adayları çek (normalize)
            # Sayım: sayfalama öncesi toplam
            adaylar = list(session.execute(q).all())

        if temiz:
            n_kelimeler = [turkce_normalize(k) for k in temiz]
            filtrelenmis = []
            for stok, miktar, alis_t, satis_t in adaylar:
                n_ad = turkce_normalize(stok.stok_adi or "")
                if yontem == "or":
                    eslesti = any(nk in n_ad for nk in n_kelimeler if nk)
                else:
                    eslesti = all(nk in n_ad for nk in n_kelimeler if nk)
                if eslesti:
                    filtrelenmis.append((stok, miktar, alis_t, satis_t))
            adaylar = filtrelenmis

        # Sıralama
        siralama_map = {
            "kod": lambda r: (r[0].stok_kodu or "").casefold(),
            "ad": lambda r: (r[0].stok_adi or "").casefold(),
            "barkod": lambda r: (r[0].barkod or "").casefold(),
            "birim": lambda r: (r[0].birim or "").casefold(),
            "kdv": lambda r: Decimal(str(r[0].kdv_orani or 0)),
            "alis": lambda r: Decimal(str(r[2])) if r[2] is not None else Decimal("-1"),
            "satis1": lambda r: Decimal(str(r[3])) if r[3] is not None else Decimal("-1"),
            "miktar": lambda r: Decimal(str(r[1] or 0)),
            "tur": lambda r: (r[0].kart_turu or "").casefold(),
            "grup": lambda r: (r[0].rapor_grubu or "").casefold(),
            "aktif": lambda r: 0 if r[0].aktif else 1,
        }

        def _fiyat_map(stok):
            mp = {}
            for f in stok.fiyatlar or []:
                ad = (f.fiyat_adi or "").strip().upper()
                if ad:
                    mp[ad] = f.tutar
            return mp

        if siralama in ("satis2", "satis3", "satis4"):
            idx = {"satis2": "SATIŞ FİYATI 2", "satis3": "SATIŞ FİYATI 3", "satis4": "SATIŞ FİYATI 4"}[
                siralama
            ]

            def _key(r, ad=idx):
                v = _fiyat_map(r[0]).get(ad)
                return Decimal(str(v)) if v is not None else Decimal("-1")

            adaylar.sort(key=_key, reverse=bool(siralama_desc))
        elif siralama in siralama_map:
            adaylar.sort(key=siralama_map[siralama], reverse=bool(siralama_desc))
        else:
            adaylar.sort(key=lambda r: (r[0].stok_adi or "").casefold())

        toplam = len(adaylar)
        sayfa = adaylar[offset : offset + limit]

        from stok_liste_ui import miktar_goster, para_goster_bos

        satirlar = []
        for stok, miktar, alis_t, satis_t in sayfa:
            fmap = _fiyat_map(stok)
            # SQL'den gelen alış/satış1 tercih; yoksa fiyat map
            alis = alis_t if alis_t is not None else fmap.get("ALIŞ FİYATI")
            s1 = satis_t if satis_t is not None else fmap.get("SATIŞ FİYATI 1")
            s2 = fmap.get("SATIŞ FİYATI 2")
            s3 = fmap.get("SATIŞ FİYATI 3")
            s4 = fmap.get("SATIŞ FİYATI 4")
            if "ALIŞ FİYATI" not in fmap and alis_t is None:
                alis = None
            if "SATIŞ FİYATI 1" not in fmap and satis_t is None:
                s1 = None

            kdv = getattr(stok, "kdv_orani", None)
            from database.fatura_kdv_service import satir_kdv_metin_sayisal

            kdv_metin = satir_kdv_metin_sayisal(kdv if kdv is not None else 20)
            barkod = stok.barkod or ""
            if not barkod and stok.barkodlar:
                barkod = stok.barkodlar[0].barkod or ""

            miktar_d = Decimal(str(miktar or 0))
            values = {
                "kod": stok.stok_kodu or "",
                "ad": stok.stok_adi or "",
                "barkod": barkod,
                "birim": stok.birim or "",
                "kdv": kdv_metin,
                "alis": para_goster_bos(alis) if alis_goster else "—",
                "satis1": para_goster_bos(s1),
                "satis2": para_goster_bos(s2),
                "satis3": para_goster_bos(s3),
                "satis4": para_goster_bos(s4),
                "miktar": miktar_goster(miktar_d),
                "tur": getattr(stok, "kart_turu", "") or "",
                "grup": getattr(stok, "rapor_grubu", "") or "",
                "ana_grup": "",
                "tali_grup": "",
                "alt_grup": "",
                "aktif": "Aktif" if stok.aktif else "Pasif",
            }
            try:
                from database.models.stok import StokGrubu as _SG

                if stok.ana_grup_id:
                    ana = session.get(_SG, stok.ana_grup_id)
                    values["ana_grup"] = (ana.ad if ana else "") or ""
                if stok.tali_grup_id:
                    tali = session.get(_SG, stok.tali_grup_id)
                    values["tali_grup"] = (tali.ad if tali else "") or ""
                if stok.alt_grup_id:
                    alt = session.get(_SG, stok.alt_grup_id)
                    values["alt_grup"] = (alt.ad if alt else "") or ""
            except Exception:
                pass
            sort = {
                "kod": stok.stok_kodu or "",
                "ad": stok.stok_adi or "",
                "barkod": barkod,
                "birim": stok.birim or "",
                "kdv": Decimal(kdv_metin.replace(",", ".")),
                "alis": Decimal(str(alis)) if alis is not None and alis_goster else None,
                "satis1": Decimal(str(s1)) if s1 is not None else None,
                "satis2": Decimal(str(s2)) if s2 is not None else None,
                "satis3": Decimal(str(s3)) if s3 is not None else None,
                "satis4": Decimal(str(s4)) if s4 is not None else None,
                "miktar": miktar_d,
                "tur": values["tur"],
                "grup": values["grup"],
                "aktif": values["aktif"],
            }
            if not alis_goster:
                values["alis"] = "—"
                sort["alis"] = None
            satirlar.append({"id": stok.id, "values": values, "sort": sort})

        return {"satirlar": satirlar, "toplam": toplam, "gosterilen": len(satirlar)}

    @staticmethod
    def stoklari_filtrele(
        kod="",
        ad="",
        limit=250,
        sadece_stokta=False,
        depo_ad=None,
        *,
        kelime_sirasiz=False,
        min_ad_harf=1,
    ):
        """Ürün kodu ve/veya adı ile AND filtre (fatura satırı seçimi).

        kelime_sirasiz=True: çoklu blok sıra bağımsız SearchService araması
        (alanlar: ad, kod, barkod, marka, grup, birim, açıklama).
        """
        kod = (kod or "").strip()
        ad = (ad or "").strip()
        depo_ad = (depo_ad or "").strip() or None
        min_ad_harf = max(1, int(min_ad_harf or 1))
        limit = max(1, min(int(limit or 250), 250))

        # Ortak çoklu blok arama (kod + ad birleşik veya yalnızca ad)
        if kelime_sirasiz:
            from database.search_service import SearchService, tokenize_query

            birlesik = " ".join(p for p in (kod, ad) if p).strip()
            if ad and not kod and len(ad) < min_ad_harf:
                return []
            if not birlesik:
                return []
            # Tek karakter bloklar tokenize'da elenir; hiç blok kalmazsa boş
            if not tokenize_query(birlesik):
                return []
            sonuc = SearchService.search_stocks(
                birlesik,
                limit=limit,
                sadece_stokta=bool(sadece_stokta),
                depo_ad=depo_ad,
            )
            return list(sonuc.get("urunler") or [])

        with get_session() as session:
            q = (
                select(StokKarti)
                .where(
                    StokKarti.aktif.is_(True),
                    or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                )
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
                if len(ad) < min_ad_harf:
                    return []
                q = q.where(StokKarti.stok_adi.ilike(f"%{ad}%"))
            if sadece_stokta:
                stoklu = select(StokLotu.stok_id).where(StokLotu.kalan_miktar > 0)
                if depo_ad:
                    depo = session.scalar(select(Depo).where(Depo.ad == depo_ad))
                    if depo is not None:
                        stoklu = stoklu.where(StokLotu.depo_id == depo.id)
                q = q.where(StokKarti.id.in_(stoklu.distinct()))
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

    _teklif_arama_onbellek: dict = {}
    _TEKLIF_ARAMA_TTL_SN = 4.0
    _TEKLIF_ARAMA_MIN = 3
    _TEKLIF_ARAMA_LIMIT = 50

    @staticmethod
    def teklif_urun_ara(
        metin: str,
        *,
        depo_ad: str | None = None,
        min_harf: int = 3,
        limit: int = 50,
        maliyet_dahil: bool | None = None,
    ) -> dict:
        """Teklif formu hızlı ürün araması (≥3 karakter, contains, TR normalize).

        Dönüş: {urunler: [...], toplam_eslesen: int, daha_fazla: bool, min_harf_uyari: bool}
        SQL parametreli LIKE; sonuçlar Python'da normalize + öncelik sıralaması.
        """
        import time

        from database.access import maliyet_izinli
        from database.turkce_normalize import (
            arama_like_varyantlari,
            kelime_basi_eslesme,
            turkce_normalize,
        )

        q = (metin or "").strip()
        min_harf = max(1, int(min_harf or StokService._TEKLIF_ARAMA_MIN))
        limit = max(1, min(int(limit or StokService._TEKLIF_ARAMA_LIMIT), 50))
        if len(q) < min_harf:
            return {
                "urunler": [],
                "toplam_eslesen": 0,
                "daha_fazla": False,
                "min_harf_uyari": True,
                "arama": q,
            }

        if maliyet_dahil is None:
            maliyet_dahil = bool(maliyet_izinli())
        else:
            maliyet_dahil = bool(maliyet_dahil)

        depo_key = (depo_ad or "").strip() or "ANA DEPO"
        nq = turkce_normalize(q)
        cache_key = (nq, depo_key, bool(maliyet_dahil), limit)
        now = time.monotonic()
        cached = StokService._teklif_arama_onbellek.get(cache_key)
        if cached and (now - cached[0]) < StokService._TEKLIF_ARAMA_TTL_SN:
            return dict(cached[1])

        patterns = arama_like_varyantlari(q, max_n=18)
        if not patterns:
            return {
                "urunler": [],
                "toplam_eslesen": 0,
                "daha_fazla": False,
                "min_harf_uyari": False,
                "arama": q,
            }

        def _alan_eslesir(deger: str | None) -> bool:
            return bool(deger) and nq in turkce_normalize(deger)

        with get_session() as session:
            kosullar = list(StokService._aktif_stok_kosulu())
            alan_or = []
            for p in patterns:
                alan_or.extend(
                    [
                        StokKarti.stok_adi.ilike(p),
                        StokKarti.stok_kodu.ilike(p),
                        StokKarti.barkod.ilike(p),
                        StokKarti.marka.ilike(p),
                        StokKarti.model.ilike(p),
                        StokKarti.aciklama.ilike(p),
                        StokKarti.muhasebe_stok_kodu.ilike(p),
                    ]
                )
            barkod_alt = select(StokBarkod.stok_id).where(
                or_(*[StokBarkod.barkod.ilike(p) for p in patterns])
            )
            alan_or.append(StokKarti.id.in_(barkod_alt))
            kosullar.append(or_(*alan_or))

            # Fazla çek, Python filtre + sıralama sonra limit
            aday_limit = min(250, max(limit * 5, 80))
            stoklar = list(
                session.scalars(
                    select(StokKarti)
                    .where(*kosullar)
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.barkodlar),
                        selectinload(StokKarti.birimler),
                    )
                    .limit(aday_limit)
                ).all()
            )

            depo = session.scalar(select(Depo).where(Depo.ad == depo_key))
            depo_id = depo.id if depo is not None else None

            skorlu = []
            for s in stoklar:
                kod = (s.stok_kodu or "").strip()
                ad = (s.stok_adi or "").strip()
                barkod = (s.barkod or "").strip()
                marka = (s.marka or "").strip()
                model = (s.model or "").strip()
                aciklama = (s.aciklama or "").strip()
                muh = (s.muhasebe_stok_kodu or "").strip()
                ek_barkodlar = [(b.barkod or "").strip() for b in (s.barkodlar or [])]

                # Normalize contains zorunlu (SQL geniş olabilir)
                if not (
                    _alan_eslesir(ad)
                    or _alan_eslesir(kod)
                    or _alan_eslesir(barkod)
                    or _alan_eslesir(marka)
                    or _alan_eslesir(model)
                    or _alan_eslesir(aciklama)
                    or _alan_eslesir(muh)
                    or any(_alan_eslesir(b) for b in ek_barkodlar)
                ):
                    continue

                n_kod = turkce_normalize(kod)
                n_ad = turkce_normalize(ad)
                n_barkod = turkce_normalize(barkod)
                if n_kod == nq:
                    skor = 1
                elif n_barkod == nq or any(turkce_normalize(b) == nq for b in ek_barkodlar):
                    skor = 2
                elif n_ad.startswith(nq):
                    skor = 3
                elif kelime_basi_eslesme(ad, q):
                    skor = 4
                elif nq in n_ad:
                    skor = 5
                elif _alan_eslesir(marka) or _alan_eslesir(model):
                    skor = 6
                else:
                    skor = 7

                depo_stok = Decimal("0")
                kullanilabilir = Decimal("0")
                for lot in s.lotlar or []:
                    kalan = Decimal(str(lot.kalan_miktar or 0))
                    kullanilabilir += kalan
                    if depo_id is None or lot.depo_id == depo_id:
                        depo_stok += kalan

                teklif_fiyat = StokService._hizli_satis_fiyat(s)
                son_alis = None
                para = "TRY"
                if maliyet_dahil:
                    for f in s.fiyatlar or []:
                        ad_f = (f.fiyat_adi or "").strip().upper()
                        if ad_f == "ALIŞ FİYATI":
                            son_alis = Decimal(str(f.tutar or 0))
                            para = (f.para_birimi or "TRY").strip() or "TRY"
                            break

                skorlu.append(
                    (
                        skor,
                        ad.casefold(),
                        {
                            "stok_id": int(s.id),
                            "urun_kodu": kod,
                            "urun_adi": ad,
                            "marka": marka or None,
                            "model": model or None,
                            "birim": (s.birim or "Adet").strip() or "Adet",
                            "barkod": barkod or None,
                            "kdv_orani": Decimal(str(getattr(s, "kdv_orani", 20) or 20)),
                            "aciklama": aciklama or None,
                            "depo_stok": depo_stok,
                            "kullanilabilir_stok": kullanilabilir,
                            "stok_yok": depo_stok <= 0,
                            "teklif_fiyati": teklif_fiyat,
                            "para_birimi": para,
                            "manuel": False,
                            **(
                                {
                                    "son_alis_fiyati": son_alis
                                    if son_alis is not None
                                    else Decimal("0"),
                                }
                                if maliyet_dahil
                                else {}
                            ),
                        },
                    )
                )

            skorlu.sort(key=lambda x: (x[0], x[1]))
            toplam = len(skorlu)
            urunler = [x[2] for x in skorlu[:limit]]
            sonuc = {
                "urunler": urunler,
                "toplam_eslesen": toplam,
                "daha_fazla": toplam > limit,
                "min_harf_uyari": False,
                "arama": q,
            }
            StokService._teklif_arama_onbellek[cache_key] = (now, sonuc)
            # Basit önbellek temizliği
            if len(StokService._teklif_arama_onbellek) > 64:
                StokService._teklif_arama_onbellek.clear()
            return dict(sonuc)

    @staticmethod
    def stok_ozeti(stok_id):
        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if not stok:
                return {
                    "toplam_giris": Decimal("0"),
                    "toplam_cikis": Decimal("0"),
                    "kalan": Decimal("0"),
                    "lot_kalan": Decimal("0"),
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
            # Kalan = hareket neti (devir/açılış dahil tüm giriş − çıkış)
            kalan = toplam_giris - toplam_cikis
            lotlar = list(session.scalars(select(StokLotu).where(StokLotu.stok_id == stok.id)).all())
            lot_kalan = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
            fifo_deger = sum(
                (lot.kalan_miktar * lot.birim_maliyet for lot in lotlar),
                Decimal("0"),
            )
            return {
                "toplam_giris": toplam_giris,
                "toplam_cikis": toplam_cikis,
                "kalan": kalan,
                "lot_kalan": lot_kalan,
                "fifo_deger": fifo_deger,
            }

    @staticmethod
    def stok_depo_ozeti(stok_id):
        """Depo bazlı kalan miktar ve FIFO değer (lotlardan; bakiye elle değişmez)."""
        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if not stok:
                return []
            satirlar = session.execute(
                select(
                    Depo.ad,
                    func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                    func.coalesce(
                        func.sum(StokLotu.kalan_miktar * StokLotu.birim_maliyet),
                        0,
                    ),
                )
                .join(StokLotu, StokLotu.depo_id == Depo.id)
                .where(StokLotu.stok_id == stok.id)
                .group_by(Depo.ad)
                .order_by(Depo.ad)
            ).all()
            raf = (stok.raf_yeri or "").strip()
            return [
                {
                    "depo": ad or "",
                    "mevcut": Decimal(str(miktar or 0)),
                    "fifo_deger": Decimal(str(deger or 0)),
                    "raf": raf,
                }
                for ad, miktar, deger in satirlar
            ]

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
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
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
            yeni_birim = (veriler.get("birim") or "Adet").strip() or "Adet"
            eski_birim = (stok.birim or "").strip()
            if eski_birim and eski_birim != yeni_birim:
                from database.user_audit import audit_document

                audit_document(
                    "stok_ana_birim_degisti",
                    modul="stok",
                    kayit_id=str(stok.id),
                    eski={"birim": eski_birim},
                    yeni={"birim": yeni_birim, "stok_kodu": yeni_kod},
                )
            stok.birim = yeni_birim
            stok.varsayilan_goruntuleme_birim = (
                (veriler.get("varsayilan_goruntuleme_birim") or "").strip() or None
            )
            stok.varsayilan_alis_birim = (veriler.get("varsayilan_alis_birim") or "").strip() or None
            stok.varsayilan_satis_birim = (veriler.get("varsayilan_satis_birim") or "").strip() or None
            stok.kart_turu = veriler.get("kart_turu") or "Ticari Mal"
            stok.aciklama = veriler.get("aciklama") or None
            stok.muhasebe_stok_kodu = veriler.get("muhasebe_stok_kodu") or None
            stok.muhasebe_alis_kodu = veriler.get("muhasebe_alis_kodu") or None
            stok.muhasebe_satis_kodu = veriler.get("muhasebe_satis_kodu") or None
            stok.muhasebe_maliyet_kodu = veriler.get("muhasebe_maliyet_kodu") or None
            stok.muhasebe_kdv_alis_kodu = veriler.get("muhasebe_kdv_alis_kodu") or None
            stok.muhasebe_kdv_satis_kodu = veriler.get("muhasebe_kdv_satis_kodu") or None
            ham_kdv = veriler.get("kdv_orani", VARSAYILAN_KDV_ORANI)
            if ham_kdv is None or (isinstance(ham_kdv, str) and not str(ham_kdv).strip()):
                ham_kdv = VARSAYILAN_KDV_ORANI
            kdv = decimal(ham_kdv, "KDV oranı", Decimal("0"))
            if kdv < 0 or kdv > 100:
                raise ValueError("KDV oranı 0–100 arasında olmalıdır.")
            stok.kdv_orani = kdv
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
            # Üç seviyeli grup (servis doğrulaması)
            ana_gid = veriler.get("ana_grup_id")
            tali_gid = veriler.get("tali_grup_id")
            alt_gid = veriler.get("alt_grup_id")
            if ana_gid or tali_gid or alt_gid or "ana_grup_id" in veriler:
                from database.stok_grup_service import StokGrupService

                dog = StokGrupService.hiyerarsi_dogrula(ana_gid, tali_gid, alt_gid)
                if dog.get("pasif_uyari"):
                    # UI uyarmış olmalı; yine de kaydet — kullanıcı onayladı
                    pass
                stok.ana_grup_id = dog["ana_grup_id"]
                stok.tali_grup_id = dog["tali_grup_id"]
                stok.alt_grup_id = dog["alt_grup_id"]
                if dog["rapor_grubu"]:
                    stok.rapor_grubu = dog["rapor_grubu"]
            stok.raf_yeri = veriler.get("raf_yeri") or None
            stok.raf_omru = veriler.get("raf_omru") or None
            try:
                stok.minimum_stok = decimal(
                    veriler.get("minimum_stok") or "0", "Minimum stok", Decimal("0")
                )
            except Exception:
                stok.minimum_stok = Decimal("0")

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
                StokService._birimleri_sessiona_yaz(
                    session, stok, birimler, ana_birim=stok.birim
                )
                # Kart seviyesindeki varsayılanlar birim bayraklarından da türetilebilir
                for b in stok.birimler:
                    if b.varsayilan_goruntuleme and not stok.varsayilan_goruntuleme_birim:
                        stok.varsayilan_goruntuleme_birim = b.birim_adi
                    if b.varsayilan_alis and not stok.varsayilan_alis_birim:
                        stok.varsayilan_alis_birim = b.birim_adi
                    if b.varsayilan_satis and not stok.varsayilan_satis_birim:
                        stok.varsayilan_satis_birim = b.birim_adi

            # 13 haneli stok kodu → birincil barkod (metin; baştaki sıfır korunur)
            barkod_yaz = barkodlar is not None
            senkron_rapor = None
            try:
                from database.stok_kodu_barkod_service import sync_for_save

                kaynak_barkodlar = barkodlar
                if kaynak_barkodlar is None:
                    kaynak_barkodlar = [
                        {
                            "barkod": str(getattr(b, "barkod", "") or ""),
                            "birim": getattr(b, "birim", None) or stok.birim or "Adet",
                            "fiyat_adi": getattr(b, "fiyat_adi", None) or "",
                            "fiyat": str(getattr(b, "fiyat", 0) or 0),
                            "aciklama": getattr(b, "aciklama", None) or "",
                        }
                        for b in list(getattr(stok, "barkodlar", None) or [])
                    ]
                    if not kaynak_barkodlar and getattr(stok, "barkod", None):
                        kaynak_barkodlar = [
                            {
                                "barkod": str(stok.barkod),
                                "birim": stok.birim or "Adet",
                                "fiyat_adi": "SATIŞ FİYATI 1",
                                "fiyat": "0",
                                "aciklama": "",
                            }
                        ]
                mukerrer_atla = bool(veriler.get("_barkod_mukerrer_atla"))
                barkodlar, senkron_rapor = sync_for_save(
                    kaynak_barkodlar,
                    yeni_kod,  # metin
                    birim=stok.birim or "Adet",
                    exclude_stock_id=int(stok.id) if stok.id else None,
                    raise_on_duplicate=not mukerrer_atla,
                )
                if (
                    barkod_yaz
                    or (senkron_rapor or {}).get("eklendi")
                    or (senkron_rapor or {}).get("guncellendi")
                    or (senkron_rapor or {}).get("kaldirildi")
                ):
                    barkod_yaz = True
            except ValueError:
                raise
            except Exception:
                # Senkron hatası kayıt yolunu kırmasın (eski davranış)
                if barkodlar is None:
                    barkod_yaz = False

            if barkod_yaz and barkodlar is not None:
                temiz_barkodlar = []
                gorulen = set()
                for kayit in barkodlar:
                    kod = str(kayit.get("barkod") or "").strip()  # metin; int'e çevirme
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
                    kod = str(kayit.get("barkod") or "").strip()
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
                if senkron_rapor and (
                    senkron_rapor.get("eklendi") or senkron_rapor.get("guncellendi")
                ):
                    try:
                        from database.user_audit import audit_document

                        audit_document(
                            "stok_kodu_barkod_otomatik",
                            modul="stok",
                            kayit_id=str(stok.id),
                            belge_no=yeni_kod,
                            yeni={
                                "stok_kodu": yeni_kod,
                                "aksiyon": senkron_rapor.get("aksiyon"),
                                "ean_ok": bool(senkron_rapor.get("ean_ok")),
                            },
                        )
                    except Exception:
                        pass
            elif veriler.get("barkod") is not None:
                # Ana barkod alanı da metin olarak saklanır
                ham = veriler.get("barkod")
                stok.barkod = str(ham).strip() if ham not in (None, "") else None

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
    def satis_fiyatlari(stok_kodu):
        """Stok kartındaki SATIŞ fiyatlarını döner (eski ad eşlemeleri dahil)."""
        hedef = {(ad or "").strip().upper() for ad in SATIS_FIYAT_ADLARI}
        for eski, yeni in ESKI_FIYAT_ESLEME.items():
            if (yeni or "").strip().upper() in hedef:
                hedef.add((eski or "").strip().upper())

        def _satis_mi(ad: str) -> bool:
            a = (ad or "").strip().upper()
            if not a:
                return False
            if a in hedef:
                return True
            if a.startswith("SATIŞ FİYATI") or a.startswith("SATIS FIYATI"):
                return True
            return False

        bulunan = [
            fiyat
            for fiyat in StokService.fiyatlar(stok_kodu)
            if _satis_mi(fiyat.fiyat_adi)
        ]

        def _sira(fiyat):
            ad = (fiyat.fiyat_adi or "").strip().upper()
            for i, standart in enumerate(SATIS_FIYAT_ADLARI):
                if ad == standart.upper():
                    return (0, i, ad)
            return (1, 99, ad)

        return sorted(bulunan, key=_sira)

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
        maliyet_zorunlu()
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
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
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
    def irsaliye_cikisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, lot=""):
        """Satış irsaliyesi sevk çıkışı — hareket_turu=İRSALİYE ÇIKIŞ."""
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Çıkış miktarı", Decimal("0.0001"))
        tercih_lot = (lot or "").strip()
        q = select(StokLotu).where(
            StokLotu.stok_id == stok.id, StokLotu.depo_id == depo.id, StokLotu.kalan_miktar > 0
        )
        if tercih_lot:
            q = q.where(StokLotu.lot_no == tercih_lot)
        lotlar = list(session.scalars(q.order_by(StokLotu.giris_tarihi, StokLotu.id)).all())
        mevcut = sum((l.kalan_miktar for l in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{stok.stok_adi} için {depo.ad} stok yetersiz. Mevcut: {mevcut}, istenen: {miktar}"
            )
        kalan, maliyet, kullanilan = miktar, Decimal("0"), []
        for stok_lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, stok_lot.kalan_miktar)
            stok_lot.kalan_miktar -= cikan
            kalan -= cikan
            maliyet += cikan * stok_lot.birim_maliyet
            kullanilan.append(f"{stok_lot.lot_no}:{cikan}")
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu="İRSALİYE ÇIKIŞ",
                    belge_no=belge_no,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=stok_lot.id,
                    miktar=cikan,
                    birim_maliyet=stok_lot.birim_maliyet,
                )
            )
        return {"lot_cikisi": ", ".join(kullanilan), "fifo_birim_maliyeti": maliyet / miktar}

    @staticmethod
    def irsaliye_cikis_iptal(session, belge_no):
        """İrsaliye stok çıkışlarını belge_no ile geri alır (fatura_cikislarini_geri_al aynası)."""
        hareketler = session.scalars(
            select(StokHareketi).where(
                StokHareketi.belge_no == belge_no,
                StokHareketi.hareket_turu == "İRSALİYE ÇIKIŞ",
            )
        ).all()
        for hareket in hareketler:
            if hareket.lot_id:
                lot = session.get(StokLotu, hareket.lot_id)
                if lot:
                    lot.kalan_miktar += hareket.miktar
            session.delete(hareket)

    @staticmethod
    def irsaliye_iade_girisi(session, belge_no, tarih, stok_kodu, depo_adi, miktar, lot_no=""):
        """İrsaliye iade girişi — hareket_turu=İRSALİYE İADE GİRİŞ."""
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} kodlu ürünün stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu bulunamadı.")
        miktar = decimal(miktar, "Giriş miktarı", Decimal("0.0001"))
        temel = (lot_no or "").strip() or StokService.otomatik_lot_no("IRS-IADE", tarih)
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
            tedarikci=None,
            giris_tarihi=tarih,
            kalan_miktar=miktar,
            birim_maliyet=Decimal("0"),
        )
        session.add(lot)
        session.flush()
        session.add(
            StokHareketi(
                tarih=tarih,
                hareket_turu="İRSALİYE İADE GİRİŞ",
                belge_no=belge_no,
                stok_id=stok.id,
                depo_id=depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=Decimal("0"),
            )
        )
        return {"lot_girisi": lot_adi}

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
        yazma_zorunlu("stok_duzenleme")
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
    def _belge_satir_sayisi(session, urun_kodu: str) -> int:
        """Geçmiş belge satırlarını sayar; snapshot alanlarına dokunmaz."""
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasiSatiri
        from database.models.alis_irsaliyesi import AlisIrsaliyesiSatiri
        from database.models.alis_siparisi import AlisSiparisiSatiri
        from database.models.satis_faturasi import SatisFaturasiSatiri
        from database.models.satis_iade_faturasi import SatisIadeFaturasiSatiri
        from database.models.satis_irsaliyesi import SatisIrsaliyesiSatiri
        from database.models.satis_siparisi import SatisSiparisiSatiri

        kod = (urun_kodu or "").strip()
        if not kod:
            return 0
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
        toplam = 0
        for model in tablolar:
            adet = session.scalar(
                select(func.count()).select_from(model).where(model.urun_kodu == kod)
            )
            toplam += int(adet or 0)
        return toplam

    @staticmethod
    def _hareket_miktar_ozeti(session, stok_id: int) -> dict:
        hareketler = list(
            session.scalars(select(StokHareketi).where(StokHareketi.stok_id == int(stok_id))).all()
        )
        toplam_giris = sum(
            (h.miktar for h in hareketler if h.hareket_turu in GIRIS_HAREKETLERI),
            Decimal("0"),
        )
        toplam_cikis = sum(
            (h.miktar for h in hareketler if h.hareket_turu in CIKIS_HAREKETLERI),
            Decimal("0"),
        )
        return {
            "adet": len(hareketler),
            "toplam_giris": toplam_giris,
            "toplam_cikis": toplam_cikis,
            "net": toplam_giris - toplam_cikis,
        }

    @staticmethod
    def _lot_kalan_ve_depolar(session, stok_id: int) -> tuple[Decimal, int, dict]:
        lotlar = list(
            session.scalars(select(StokLotu).where(StokLotu.stok_id == int(stok_id))).all()
        )
        depo_map: dict[int | None, Decimal] = {}
        toplam = Decimal("0")
        for lot in lotlar:
            miktar = lot.kalan_miktar or Decimal("0")
            toplam += miktar
            depo_map[lot.depo_id] = depo_map.get(lot.depo_id, Decimal("0")) + miktar
        return toplam, len({d for d in depo_map if d is not None or depo_map.get(d)}), depo_map

    @staticmethod
    def _stok_birlestir_dogrula(session, aktarilacak_id, aktarilan_id):
        if int(aktarilacak_id) == int(aktarilan_id):
            raise ValueError("Kaynak ve hedef stok aynı olamaz.")

        kaynak = session.scalar(
            select(StokKarti)
            .where(StokKarti.id == int(aktarilacak_id))
            .with_for_update()
        )
        hedef = session.scalar(
            select(StokKarti)
            .where(StokKarti.id == int(aktarilan_id))
            .with_for_update()
        )
        if not kaynak or not hedef:
            raise ValueError("Stok kartı bulunamadı.")
        if bool(getattr(kaynak, "is_deleted", False)) or getattr(
            kaynak, "birlestirildi_hedef_id", None
        ):
            raise ValueError(
                "Kaynak stok zaten birleştirilmiş veya silinmiş; işlem tekrarlanamaz."
            )
        if not kaynak.aktif:
            raise ValueError("Kaynak stok kartı pasif; birleştirilemez.")
        if bool(getattr(hedef, "is_deleted", False)):
            raise ValueError("Hedef stok silinmiş; birleştirilemez.")
        if not hedef.aktif:
            raise ValueError("Hedef stok kartı pasif; birleştirilemez.")
        # Aynı firma DB oturumunda çalışır; farklı firma stokları aynı session'da olamaz.
        return kaynak, hedef

    @staticmethod
    def stok_birlestir_onizleme(aktarilacak_id, aktarilan_id):
        """Birleştirme öncesi etki özeti (salt okunur)."""
        with get_session() as session:
            if int(aktarilacak_id) == int(aktarilan_id):
                raise ValueError("Kaynak ve hedef stok aynı olamaz.")
            kaynak = session.get(StokKarti, int(aktarilacak_id))
            hedef = session.get(StokKarti, int(aktarilan_id))
            if not kaynak or not hedef:
                raise ValueError("Stok kartı bulunamadı.")
            if bool(getattr(kaynak, "is_deleted", False)) or getattr(
                kaynak, "birlestirildi_hedef_id", None
            ):
                raise ValueError("Kaynak stok zaten birleştirilmiş veya silinmiş.")

            kaynak_h = StokService._hareket_miktar_ozeti(session, kaynak.id)
            hedef_h = StokService._hareket_miktar_ozeti(session, hedef.id)
            kaynak_lot, kaynak_depo_adet, kaynak_depo_map = StokService._lot_kalan_ve_depolar(
                session, kaynak.id
            )
            hedef_lot, _, hedef_depo_map = StokService._lot_kalan_ve_depolar(session, hedef.id)
            belge_adet = StokService._belge_satir_sayisi(session, kaynak.stok_kodu)
            beklenen_hedef = hedef_lot + kaynak_lot
            etkilenen_depolar = set(kaynak_depo_map) | set(hedef_depo_map)

            return {
                "kaynak_id": int(kaynak.id),
                "kaynak_kod": kaynak.stok_kodu,
                "kaynak_ad": kaynak.stok_adi,
                "hedef_id": int(hedef.id),
                "hedef_kod": hedef.stok_kodu,
                "hedef_ad": hedef.stok_adi,
                "kaynak_toplam_giris": kaynak_h["toplam_giris"],
                "kaynak_toplam_cikis": kaynak_h["toplam_cikis"],
                "kaynak_net": kaynak_h["net"],
                "kaynak_lot_miktar": kaynak_lot,
                "hedef_mevcut": hedef_lot,
                "hedef_hareket_net": hedef_h["net"],
                "beklenen_hedef_miktar": beklenen_hedef,
                "hareket_adet": kaynak_h["adet"],
                "belge_satir_adet": belge_adet,
                "depo_adet": len([d for d in etkilenen_depolar if d is not None])
                or len(etkilenen_depolar),
                "kaynak_depo_bakiyeleri": {
                    str(k): v for k, v in kaynak_depo_map.items()
                },
                "hedef_depo_bakiyeleri": {
                    str(k): v for k, v in hedef_depo_map.items()
                },
            }

    @staticmethod
    def _paket_referanslarini_aktar(session, kaynak_id: int, hedef_id: int) -> int:
        """Paket bileşen / üretim stok_id bağlarını hedefe çeker."""
        adet = 0
        # Bileşen olarak kaynak → hedef
        for satir in list(
            session.scalars(
                select(StokPaketBilesen).where(StokPaketBilesen.bilesen_stok_id == kaynak_id)
            ).all()
        ):
            mevcut = session.scalar(
                select(StokPaketBilesen).where(
                    StokPaketBilesen.paket_stok_id == satir.paket_stok_id,
                    StokPaketBilesen.bilesen_stok_id == hedef_id,
                )
            )
            if mevcut is not None:
                mevcut.miktar = (mevcut.miktar or Decimal("0")) + (satir.miktar or Decimal("0"))
                session.delete(satir)
            else:
                satir.bilesen_stok_id = hedef_id
            adet += 1

        # Paket kartı olarak kaynak → hedef (bileşen satırlarını taşı / birleştir)
        for satir in list(
            session.scalars(
                select(StokPaketBilesen).where(StokPaketBilesen.paket_stok_id == kaynak_id)
            ).all()
        ):
            if satir.bilesen_stok_id == hedef_id:
                # Hedef kendi bileşeni olamaz
                session.delete(satir)
                adet += 1
                continue
            mevcut = session.scalar(
                select(StokPaketBilesen).where(
                    StokPaketBilesen.paket_stok_id == hedef_id,
                    StokPaketBilesen.bilesen_stok_id == satir.bilesen_stok_id,
                )
            )
            if mevcut is not None:
                mevcut.miktar = (mevcut.miktar or Decimal("0")) + (satir.miktar or Decimal("0"))
                session.delete(satir)
            else:
                satir.paket_stok_id = hedef_id
            adet += 1

        for uretim in list(
            session.scalars(
                select(StokPaketUretim).where(StokPaketUretim.paket_stok_id == kaynak_id)
            ).all()
        ):
            uretim.paket_stok_id = hedef_id
            adet += 1
        return adet

    @staticmethod
    def _hizli_satis_referanslarini_aktar(session, kaynak_id: int, hedef_id: int) -> int:
        """Hızlı satış pin ve bekleyen sepet satırlarında stok_id günceller (snapshot korunur)."""
        from database.models.hizli_satis import HizliSatisBekleyenSatiri, HizliSatisHizliUrun

        adet = 0
        for pin in list(
            session.scalars(
                select(HizliSatisHizliUrun).where(HizliSatisHizliUrun.stok_id == kaynak_id)
            ).all()
        ):
            mevcut = session.scalar(
                select(HizliSatisHizliUrun).where(
                    HizliSatisHizliUrun.stok_id == hedef_id,
                    HizliSatisHizliUrun.hizli_satis_grubu_id == pin.hizli_satis_grubu_id,
                )
            )
            if mevcut is not None:
                session.delete(pin)
            else:
                pin.stok_id = hedef_id
            adet += 1

        for satir in list(
            session.scalars(
                select(HizliSatisBekleyenSatiri).where(
                    HizliSatisBekleyenSatiri.stok_id == kaynak_id
                )
            ).all()
        ):
            # stok_kodu / stok_adi / birim snapshot korunur
            satir.stok_id = hedef_id
            adet += 1
        return adet

    @staticmethod
    def stok_birlestir(aktarilacak_id, aktarilan_id, gerekce: str | None = None):
        """
        Kaynak stok kartını hedef karta birleştirir.

        Hareket ve FIFO lot bağlantıları hedef stock_id'ye taşınır; geçmiş belge
        satırlarındaki ürün adı/kod/birim snapshot'ları korunur. Kaynak kart
        hard-delete edilmez (delete-orphan lot kaybını önlemek için); pasife
        alınır ve birlestirildi_hedef_id saklanır.
        """
        yazma_zorunlu("stok_duzenleme")
        gerekce_metin = (gerekce or "").strip() or "Stok birleştirme"

        with get_session() as session:
            from sqlalchemy.orm.attributes import set_committed_value

            kaynak, hedef = StokService._stok_birlestir_dogrula(
                session, aktarilacak_id, aktarilan_id
            )
            # İlişkileri kilitleme sonrası yükle
            kaynak = StokService._stok_yukle(session, stok_id=kaynak.id)
            hedef = StokService._stok_yukle(session, stok_id=hedef.id)

            eski_kod = kaynak.stok_kodu
            eski_ad = kaynak.stok_adi
            yeni_kod = hedef.stok_kodu
            yeni_ad = hedef.stok_adi
            yeni_birim = hedef.birim or "Adet"
            kaynak_id = int(kaynak.id)
            hedef_id = int(hedef.id)

            kaynak_h_once = StokService._hareket_miktar_ozeti(session, kaynak_id)
            hedef_h_once = StokService._hareket_miktar_ozeti(session, hedef_id)
            kaynak_lot_once, _, kaynak_depo_once = StokService._lot_kalan_ve_depolar(
                session, kaynak_id
            )
            hedef_lot_once, _, hedef_depo_once = StokService._lot_kalan_ve_depolar(
                session, hedef_id
            )
            belge_adet = StokService._belge_satir_sayisi(session, eski_kod)
            beklenen_hedef = hedef_lot_once + kaynak_lot_once

            # --- Lot / FIFO katmanları ---
            hedef_lot_map = {(lot.depo_id, lot.lot_no): lot for lot in list(hedef.lotlar)}
            lot_tasinan = 0
            lot_birlesen = 0
            for lot in list(
                session.scalars(select(StokLotu).where(StokLotu.stok_id == kaynak_id)).all()
            ):
                anahtar = (lot.depo_id, lot.lot_no)
                mevcut = hedef_lot_map.get(anahtar)
                if mevcut is None:
                    lot.stok_id = hedef_id
                    hedef_lot_map[anahtar] = lot
                    lot_tasinan += 1
                    continue
                toplam_miktar = (mevcut.kalan_miktar or Decimal("0")) + (
                    lot.kalan_miktar or Decimal("0")
                )
                if toplam_miktar > 0:
                    mevcut.birim_maliyet = (
                        ((mevcut.kalan_miktar or Decimal("0")) * (mevcut.birim_maliyet or Decimal("0")))
                        + ((lot.kalan_miktar or Decimal("0")) * (lot.birim_maliyet or Decimal("0")))
                    ) / toplam_miktar
                mevcut.kalan_miktar = toplam_miktar
                for hareket in session.scalars(
                    select(StokHareketi).where(StokHareketi.lot_id == lot.id)
                ).all():
                    hareket.lot_id = mevcut.id
                    hareket.stok_id = hedef_id
                session.delete(lot)
                lot_birlesen += 1

            # --- Stok hareketleri ---
            hareket_adet = 0
            aktarilan_giris = Decimal("0")
            aktarilan_cikis = Decimal("0")
            for hareket in list(
                session.scalars(
                    select(StokHareketi).where(StokHareketi.stok_id == kaynak_id)
                ).all()
            ):
                if hareket.hareket_turu in GIRIS_HAREKETLERI:
                    aktarilan_giris += hareket.miktar or Decimal("0")
                elif hareket.hareket_turu in CIKIS_HAREKETLERI:
                    aktarilan_cikis += hareket.miktar or Decimal("0")
                hareket.stok_id = hedef_id
                hareket_adet += 1

            # --- Kart yan tabloları ---
            hedef_fiyat_adlari = {f.fiyat_adi for f in hedef.fiyatlar}
            for fiyat in list(
                session.scalars(select(StokFiyati).where(StokFiyati.stok_id == kaynak_id)).all()
            ):
                if fiyat.fiyat_adi in hedef_fiyat_adlari:
                    session.delete(fiyat)
                else:
                    fiyat.stok_id = hedef_id
                    hedef_fiyat_adlari.add(fiyat.fiyat_adi)

            hedef_birimler = {b.birim_adi for b in hedef.birimler}
            for birim in list(
                session.scalars(select(StokBirim).where(StokBirim.stok_id == kaynak_id)).all()
            ):
                if birim.birim_adi in hedef_birimler:
                    session.delete(birim)
                else:
                    birim.stok_id = hedef_id
                    hedef_birimler.add(birim.birim_adi)

            hedef_barkodlar = {(b.barkod or "").strip() for b in hedef.barkodlar}
            if (hedef.barkod or "").strip():
                hedef_barkodlar.add(hedef.barkod.strip())
            for barkod in list(
                session.scalars(select(StokBarkod).where(StokBarkod.stok_id == kaynak_id)).all()
            ):
                kod = (barkod.barkod or "").strip()
                if not kod or kod in hedef_barkodlar:
                    session.delete(barkod)
                else:
                    barkod.stok_id = hedef_id
                    hedef_barkodlar.add(kod)
            kaynak_barkod = (kaynak.barkod or "").strip()
            if (
                kaynak_barkod
                and kaynak_barkod not in hedef_barkodlar
                and not (hedef.barkod or "").strip()
            ):
                hedef.barkod = kaynak_barkod
                hedef_barkodlar.add(kaynak_barkod)
            kaynak.barkod = None

            for resim in list(
                session.scalars(select(StokResmi).where(StokResmi.stok_id == kaynak_id)).all()
            ):
                resim.stok_id = hedef_id
            for gecmis in list(
                session.scalars(
                    select(StokFiyatGecmisi).where(StokFiyatGecmisi.stok_id == kaynak_id)
                ).all()
            ):
                gecmis.stok_id = hedef_id

            paket_adet = StokService._paket_referanslarini_aktar(session, kaynak_id, hedef_id)
            hizli_adet = StokService._hizli_satis_referanslarini_aktar(
                session, kaynak_id, hedef_id
            )

            session.flush()
            # İlişki koleksiyonlarını boşalt — hard-delete olmasa da orphan riskini kes
            set_committed_value(kaynak, "lotlar", [])
            set_committed_value(kaynak, "fiyatlar", [])
            set_committed_value(kaynak, "birimler", [])
            set_committed_value(kaynak, "barkodlar", [])
            set_committed_value(kaynak, "resimler", [])
            set_committed_value(kaynak, "fiyat_gecmisi", [])

            kalan_hareket = session.scalar(
                select(func.count())
                .select_from(StokHareketi)
                .where(StokHareketi.stok_id == kaynak_id)
            )
            kalan_lot = session.scalar(
                select(func.count()).select_from(StokLotu).where(StokLotu.stok_id == kaynak_id)
            )
            if kalan_hareket or kalan_lot:
                raise ValueError(
                    f"Kaynak stok boşaltılamadı (hareket={kalan_hareket}, lot={kalan_lot})."
                )

            hedef_lot_sonra, _, hedef_depo_sonra = StokService._lot_kalan_ve_depolar(
                session, hedef_id
            )
            hedef_h_sonra = StokService._hareket_miktar_ozeti(session, hedef_id)

            if abs(hedef_lot_sonra - beklenen_hedef) > Decimal("0.0001"):
                raise ValueError(
                    "Hedef stok bakiyesi doğrulanamadı: "
                    f"beklenen={beklenen_hedef}, hesaplanan={hedef_lot_sonra}."
                )

            # Soft-delete: geçmiş belgeler için kart kalır, aramalarda görünmez
            now = datetime.now()
            kaynak.aktif = False
            kaynak.is_deleted = True
            kaynak.deleted_at = now
            kaynak.birlestirildi_hedef_id = hedef_id
            session.flush()

            depo_rapor = []
            tum_depolar = set(hedef_depo_once) | set(kaynak_depo_once) | set(hedef_depo_sonra)
            for depo_id in sorted(tum_depolar, key=lambda x: (x is None, x or 0)):
                depo_rapor.append(
                    {
                        "depo_id": depo_id,
                        "onceki": hedef_depo_once.get(depo_id, Decimal("0")),
                        "kaynak": kaynak_depo_once.get(depo_id, Decimal("0")),
                        "sonra": hedef_depo_sonra.get(depo_id, Decimal("0")),
                    }
                )

            kaynak_snap = {
                "entity": {
                    "id": kaynak_id,
                    "stok_kodu": eski_kod,
                    "stok_adi": eski_ad,
                    "birlestirildi_hedef_id": hedef_id,
                },
                "related": [
                    {"type": "hedef_stok_id", "id": hedef_id, "kod": yeni_kod, "ad": yeni_ad},
                    {"type": "belge_satir_snapshot_korundu", "count": belge_adet},
                    {"type": "hareket", "count": hareket_adet},
                    {"type": "lot_tasinan", "count": lot_tasinan},
                    {"type": "lot_birlesen", "count": lot_birlesen},
                    {
                        "type": "miktar",
                        "kaynak_once": str(kaynak_lot_once),
                        "hedef_once": str(hedef_lot_once),
                        "hedef_sonra": str(hedef_lot_sonra),
                    },
                    {"type": "gerekce", "value": gerekce_metin},
                ],
                "audit": {
                    "kaynak_stock_id": kaynak_id,
                    "kaynak_kod": eski_kod,
                    "kaynak_ad": eski_ad,
                    "hedef_stock_id": hedef_id,
                    "hedef_kod": yeni_kod,
                    "hedef_ad": yeni_ad,
                    "kaynak_miktar_once": str(kaynak_lot_once),
                    "hedef_miktar_once": str(hedef_lot_once),
                    "hedef_miktar_sonra": str(hedef_lot_sonra),
                    "aktarilan_hareket": hareket_adet,
                    "gerekce": gerekce_metin,
                    "tarih": now.isoformat(sep=" ", timespec="seconds"),
                },
            }
            sonuc = {
                "eski_kod": eski_kod,
                "eski_ad": eski_ad,
                "yeni_kod": yeni_kod,
                "yeni_ad": yeni_ad,
                "yeni_birim": yeni_birim,
                "kaynak_id": kaynak_id,
                "hedef_id": hedef_id,
                "belge_satir": belge_adet,
                "hareket": hareket_adet,
                "lot": lot_tasinan + lot_birlesen,
                "lot_tasinan": lot_tasinan,
                "lot_birlesen": lot_birlesen,
                "paket_ref": paket_adet,
                "hizli_satis_ref": hizli_adet,
                "aktarilan_giris": aktarilan_giris,
                "aktarilan_cikis": aktarilan_cikis,
                "kaynak_miktar_once": kaynak_lot_once,
                "hedef_miktar_once": hedef_lot_once,
                "hedef_miktar_sonra": hedef_lot_sonra,
                "hedef_hareket_net_sonra": hedef_h_sonra["net"],
                "kaynak_hareket_giris": kaynak_h_once["toplam_giris"],
                "kaynak_hareket_cikis": kaynak_h_once["toplam_cikis"],
                "hedef_hareket_net_once": hedef_h_once["net"],
                "depo_bakiyeleri": depo_rapor,
                "kaynak_durum": "pasif_soft_delete",
                "gerekce": gerekce_metin,
            }

        from database.deleted_record_service import (
            ENTITY_STOK_BIRLESTIR,
            safe_log_cancel_snapshot,
        )

        safe_log_cancel_snapshot(
            ENTITY_STOK_BIRLESTIR,
            kaynak_id,
            note=(
                f"Stok birleştirme: {eski_kod} → {yeni_kod} | "
                f"miktar {sonuc['hedef_miktar_once']} → {sonuc['hedef_miktar_sonra']} | "
                f"{gerekce_metin}"
            ),
            snapshot=kaynak_snap,
            record_code=eski_kod,
            record_title=f"Stok birleştirildi → {yeni_kod}",
            module="stok",
            reason="Stok birleştirme",
            amount=sonuc["hedef_miktar_sonra"],
        )
        return sonuc

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
        yazma_zorunlu("stok_duzenleme")
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
        yazma_zorunlu("stok_duzenleme", "silme")
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
        yazma_zorunlu("stok_duzenleme")
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
