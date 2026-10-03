from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from database.cari_service import CariService
from database.database import get_session
from database.access import yazma_zorunlu
from database.models.cari import Cari
from database.models.satis_siparisi import (
    SatisSiparisi,
    SatisSiparisiSatiri,
    SatisSiparisiTahsilati,
)

MALIYET_YONTEMLERI = (
    "FIFO",
    "SON ALIŞ FİYATI",
    "ORTALAMA ALIŞ FİYATI",
    "AĞIRLIKLI ORTALAMA ALIŞ FİYATI",
)
SIPARIS_DURUMLARI = (
    "TASLAK",
    "AÇIK",
    "KISMİ İRSALİYELİ",
    "İRSALİYELİ",
    "KISMİ FATURALI",
    "FATURALI",
    "İPTAL",
)
ODEME_SEKILLERI = ("NAKİT / KASA", "GELEN HAVALE", "KREDİ KARTIYLA TAHSİLAT")
PARA_BIRIMLERI = ("TRY", "USD", "EUR", "GBP")
KURUS = Decimal("0.01")

# Liste / kart ilerleme gösterimi (sipariş durumu alanından bağımsız, satır miktarlarından)
ILERLEME_BEKLIYOR = "BEKLİYOR"
ILERLEME_KISMEN = "KISMEN TAMAMLANDI"
ILERLEME_TAMAM = "TAMAMLANDI"
ILERLEME_IPTAL = "İPTAL"
ILERLEME_TASLAK = "TASLAK"

# Fatura dönüşüm kaynağı (tek kural):
# - Doğrudan siparişten: fatura kalanı = sipariş miktarı − faturalanan_miktar (sevk zorunlu değil).
# - İrsaliyeden: fatura kalanı = irsaliye satır miktarı − faturalanan_miktar; bağlı sipariş
#   satırının faturalanan_miktar'ı da aynı tutarla artar.
# Sevk kalanı her zaman sipariş miktarı − irsaliyelenen_miktar; fatura kalanından bağımsızdır.
FATURA_KAYNAK_KURALI = "SIPARIS_VEYA_IRSALIYE_BAGIMSIZ"


def bos_metin(deger: object) -> str:
    """None / 'None' / boş → boş string (UI ve kayıt tutarlılığı)."""
    if deger is None:
        return ""
    metin = str(deger).strip()
    if not metin or metin.lower() in ("none", "null"):
        return ""
    return metin


def satir_kalanlari(miktar, irsaliyelenen=0, faturalanan=0) -> dict[str, Decimal]:
    """Satır bazında sevk ve fatura kalanları (FATURA_KAYNAK_KURALI)."""
    m = decimal(miktar or 0, "Miktar", Decimal("0"))
    sevk = decimal(irsaliyelenen or 0, "Sevk", Decimal("0"))
    fat = decimal(faturalanan or 0, "Fatura", Decimal("0"))
    return {
        "sevk_kalani": m - sevk,
        "fatura_kalani": m - fat,
    }


def satir_hesapla(miktar, birim_fiyat, iskonto1=0, iskonto2=0, iskonto3=0, kdv_orani=0) -> dict[str, Decimal]:
    """Sipariş satırı tutarları — satış faturası ile aynı kural.

    Kademeli iskonto (toplanmaz), matrah ve KDV kuruşa HALF_UP. Ekran, PDF, Word
    ve liste toplamları bu fonksiyondan üretilir.
    """
    from database.iskonto_hesap_service import satir_net_brut_indirim, yuvarla_kurus

    brut, _indirim, net = satir_net_brut_indirim(miktar, birim_fiyat, iskonto1, iskonto2, iskonto3)
    net = yuvarla_kurus(net)
    brut = yuvarla_kurus(brut)
    iskonto = brut - net
    kdv = yuvarla_kurus(net * decimal(kdv_orani or 0, "KDV oranı", Decimal("0")) / Decimal("100"))
    return {"brut": brut, "iskonto": iskonto, "net": net, "kdv": kdv, "toplam": net + kdv}


def _satir_degeri(satir, alan: str, varsayilan=0):
    if isinstance(satir, dict):
        deger = satir.get(alan, varsayilan)
    else:
        deger = getattr(satir, alan, varsayilan)
    return varsayilan if deger in (None, "") else deger


def belge_toplamlari(satirlar) -> dict[str, Decimal]:
    """Satır listesi (model veya dict) → brüt, iskonto, matrah, KDV, genel toplam."""
    brut = iskonto = net = kdv = Decimal("0")
    for s in satirlar or []:
        fiyat = _satir_degeri(s, "birim_satis_fiyati", None)
        if fiyat is None:
            fiyat = _satir_degeri(s, "birim_fiyat", 0)
        h = satir_hesapla(
            _satir_degeri(s, "miktar"),
            fiyat,
            _satir_degeri(s, "iskonto_orani"),
            _satir_degeri(s, "iskonto_orani_2"),
            _satir_degeri(s, "iskonto_orani_3"),
            _satir_degeri(s, "kdv_orani"),
        )
        brut += h["brut"]
        iskonto += h["iskonto"]
        net += h["net"]
        kdv += h["kdv"]
    return {"ara_toplam": brut, "iskonto": iskonto, "net": net, "kdv": kdv, "genel_toplam": net + kdv}


def siparis_tl_fiyati(siparis, satir) -> Decimal:
    """Aktarım (irsaliye/fatura TL çalışır): döviz siparişte birim fiyat × kur."""
    fiyat = decimal(getattr(satir, "birim_satis_fiyati", 0) or 0, "Birim fiyat", Decimal("0"))
    pb = (getattr(siparis, "para_birimi", None) or "TRY").upper()
    if pb == "TRY":
        return fiyat
    kur = decimal(getattr(siparis, "kur", 1) or 1, "Kur", Decimal("0"))
    return (fiyat * kur).quantize(Decimal("0.0001"))


def siparis_ilerleme(siparis) -> str:
    """Satır miktarlarına göre: TASLAK / BEKLİYOR / KISMEN TAMAMLANDI / TAMAMLANDI / İPTAL."""
    durum = (getattr(siparis, "durum", "") or "").upper()
    if durum == "İPTAL":
        return ILERLEME_IPTAL
    if durum == "TASLAK":
        return ILERLEME_TASLAK
    satirlar = list(getattr(siparis, "satirlar", None) or [])
    if satirlar and all(
        decimal(s.faturalanan_miktar or 0, "F") >= decimal(s.miktar or 0, "M") for s in satirlar
    ):
        return ILERLEME_TAMAM
    if any(
        decimal(s.faturalanan_miktar or 0, "F") > 0 or decimal(s.irsaliyelenen_miktar or 0, "S") > 0
        for s in satirlar
    ):
        return ILERLEME_KISMEN
    return ILERLEME_BEKLIYOR


def siparis_gecikti_mi(siparis, bugun: date | None = None) -> bool:
    """Açık (tamamlanmamış, iptal/taslak olmayan) sipariş genel veya satır termini geçmişse."""
    bugun = bugun or date.today()
    if siparis_ilerleme(siparis) in (ILERLEME_IPTAL, ILERLEME_TAMAM, ILERLEME_TASLAK):
        return False
    if getattr(siparis, "termin_tarihi", None) and siparis.termin_tarihi < bugun:
        return True
    for s in getattr(siparis, "satirlar", None) or []:
        termin = getattr(s, "estimated_delivery_date", None)
        if termin and termin < bugun and decimal(s.miktar or 0, "M") > decimal(s.irsaliyelenen_miktar or 0, "S"):
            return True
    return False


def decimal(deger: object, alan: str, minimum: Decimal | None = None) -> Decimal:
    try:
        if isinstance(deger, Decimal):
            sonuc = deger
        else:
            metin = str(deger).strip()
            if "," in metin:
                metin = metin.replace(".", "").replace(",", ".")
            sonuc = Decimal(metin)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from None
    if minimum is not None and sonuc < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return sonuc


LISTE_GECIKEN = "GECİKEN"


def siparis_listesi_filtrele(
    kayitlar: list[dict[str, Any]],
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
    musteri: str = "",
    siparis_no: str = "",
    termin_baslangic: date | None = None,
    termin_bitis: date | None = None,
    durum: str = "",
) -> list[dict[str, Any]]:
    """``listele()`` kayıtlarını filtreler. ``durum``: sipariş durumu, ilerleme veya GECİKEN."""
    musteri = (musteri or "").strip().casefold()
    siparis_no = (siparis_no or "").strip().casefold()
    durum = (durum or "").strip()
    sonuc = []
    for k in kayitlar:
        sp = k["siparis"]
        if baslangic and (sp.siparis_tarihi is None or sp.siparis_tarihi < baslangic):
            continue
        if bitis and (sp.siparis_tarihi is None or sp.siparis_tarihi > bitis):
            continue
        if termin_baslangic and (sp.termin_tarihi is None or sp.termin_tarihi < termin_baslangic):
            continue
        if termin_bitis and (sp.termin_tarihi is None or sp.termin_tarihi > termin_bitis):
            continue
        if siparis_no and siparis_no not in (sp.siparis_no or "").casefold() and siparis_no not in (
            getattr(sp, "musteri_siparis_no", None) or ""
        ).casefold():
            continue
        if musteri:
            cari = k.get("musteri")
            metin = f"{getattr(cari, 'cari_kodu', '') or ''} {getattr(cari, 'unvan', '') or ''}".casefold()
            if not all(parca in metin for parca in musteri.split()):
                continue
        if durum:
            if durum == LISTE_GECIKEN:
                if not k.get("gecikti"):
                    continue
            elif durum in SIPARIS_DURUMLARI:
                if (sp.durum or "") != durum:
                    continue
            elif k.get("ilerleme") != durum:
                continue
        sonuc.append(k)
    return sonuc


def _iskontolar(veri: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    from database.iskonto_hesap_service import iskonto_oranlarini_dogrula

    return iskonto_oranlarini_dogrula(
        veri.get("iskonto_orani") or 0, veri.get("iskonto_orani_2") or 0, veri.get("iskonto_orani_3") or 0
    )


class SatisSiparisiService:
    @staticmethod
    def _satir_alanlarini_yaz(satir: SatisSiparisiSatiri, veri: dict[str, Any]) -> None:
        """Ticari alanları güncelle; sevk/fatura sayaçlarını DB'den koru (mevcut satır)."""
        miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
        sevk = decimal(satir.irsaliyelenen_miktar or 0, "Sevk", Decimal("0"))
        fat = decimal(satir.faturalanan_miktar or 0, "Fatura", Decimal("0"))
        min_miktar = max(sevk, fat)
        if miktar < min_miktar:
            raise ValueError(
                f"{veri.get('urun_kodu') or 'Satır'}: sipariş miktarı "
                f"sevk/faturalanan miktarın ({min_miktar}) altına indirilemez."
            )
        if min_miktar > 0:
            if (veri["urun_kodu"] or "") != (satir.urun_kodu or ""):
                raise ValueError(
                    f"{satir.urun_kodu}: sevk veya fatura bağlantısı olan satırın ürünü değiştirilemez."
                )
            if (veri["birim"] or "").casefold() != (satir.birim or "").casefold():
                raise ValueError(
                    f"{satir.urun_kodu}: sevk veya fatura bağlantısı olan satırın birimi değiştirilemez."
                )
        satir.urun_kodu = veri["urun_kodu"]
        satir.urun_adi = veri["urun_adi"]
        satir.aciklama = bos_metin(veri.get("aciklama")) or None
        satir.miktar = miktar
        satir.birim = veri["birim"]
        satir.birim_satis_fiyati = decimal(veri["birim_satis_fiyati"], "Birim satış fiyatı", Decimal("0"))
        satir.iskonto_orani, satir.iskonto_orani_2, satir.iskonto_orani_3 = _iskontolar(veri)
        satir.kdv_orani = decimal(veri.get("kdv_orani", 20), "KDV oranı", Decimal("0"))
        satir.fifo_birim_maliyeti = decimal(veri.get("fifo_birim_maliyeti", 0), "FIFO maliyeti", Decimal("0"))
        satir.son_alis_birim_maliyeti = decimal(
            veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")
        )
        satir.ortalama_birim_maliyeti = decimal(
            veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyeti", Decimal("0")
        )
        satir.agirlikli_ortalama_birim_maliyeti = decimal(
            veri.get("agirlikli_ortalama_birim_maliyeti", 0), "Ağırlıklı maliyeti", Decimal("0")
        )
        satir.is_manual_item = bool(veri.get("is_manual_item", False))
        satir.line_type = (
            veri.get("line_type")
            or ("MANUAL_PRODUCT" if veri.get("is_manual_item") else "STOCK_PRODUCT")
        )
        satir.product_id = (
            int(veri["product_id"]) if veri.get("product_id") not in (None, "") else None
        )
        satir.delivery_term_days = (
            int(veri["delivery_term_days"])
            if veri.get("delivery_term_days") not in (None, "")
            else None
        )
        satir.estimated_delivery_date = veri.get("estimated_delivery_date")
        satir.delivery_term_note = veri.get("delivery_term_note")
        satir.stock_pending = bool(
            veri.get("stock_pending", veri.get("is_manual_item", False))
        )

    @staticmethod
    def _satirlari_uygula(
        siparis: SatisSiparisi, satir_verileri: list[dict[str, Any]], *, yeni: bool
    ) -> None:
        """Mevcut satır id'lerini koruyarak güncelle; yeni satır ekle; kullanılmayanı sil."""
        mevcut = {int(s.id): s for s in list(siparis.satirlar) if s.id is not None}
        gorulen: set[int] = set()
        for veri in satir_verileri:
            ham_id = veri.get("id") if veri.get("id") not in (None, "") else veri.get("siparis_satiri_id")
            sid = int(ham_id) if ham_id not in (None, "") else None
            if sid and sid in mevcut:
                satir = mevcut[sid]
                SatisSiparisiService._satir_alanlarini_yaz(satir, veri)
                gorulen.add(sid)
            else:
                satir = SatisSiparisiSatiri(
                    urun_kodu=veri["urun_kodu"],
                    urun_adi=veri["urun_adi"],
                    aciklama=bos_metin(veri.get("aciklama")) or None,
                    miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")),
                    birim=veri["birim"],
                    birim_satis_fiyati=decimal(
                        veri["birim_satis_fiyati"], "Birim satış fiyatı", Decimal("0")
                    ),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV oranı", Decimal("0")),
                    fifo_birim_maliyeti=decimal(
                        veri.get("fifo_birim_maliyeti", 0), "FIFO maliyeti", Decimal("0")
                    ),
                    son_alis_birim_maliyeti=decimal(
                        veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")
                    ),
                    ortalama_birim_maliyeti=decimal(
                        veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyeti", Decimal("0")
                    ),
                    agirlikli_ortalama_birim_maliyeti=decimal(
                        veri.get("agirlikli_ortalama_birim_maliyeti", 0),
                        "Ağırlıklı maliyeti",
                        Decimal("0"),
                    ),
                    is_manual_item=bool(veri.get("is_manual_item", False)),
                    line_type=(
                        veri.get("line_type")
                        or ("MANUAL_PRODUCT" if veri.get("is_manual_item") else "STOCK_PRODUCT")
                    ),
                    product_id=(
                        int(veri["product_id"])
                        if veri.get("product_id") not in (None, "")
                        else None
                    ),
                    delivery_term_days=(
                        int(veri["delivery_term_days"])
                        if veri.get("delivery_term_days") not in (None, "")
                        else None
                    ),
                    estimated_delivery_date=veri.get("estimated_delivery_date"),
                    delivery_term_note=veri.get("delivery_term_note"),
                    stock_pending=bool(
                        veri.get("stock_pending", veri.get("is_manual_item", False))
                    ),
                )
                satir.iskonto_orani, satir.iskonto_orani_2, satir.iskonto_orani_3 = _iskontolar(veri)
                # Yeni satır: sayaçlar sıfır (veya açıkça verilen)
                satir.irsaliyelenen_miktar = decimal(
                    veri.get("irsaliyelenen_miktar", 0), "İrsaliyelenen miktar", Decimal("0")
                )
                satir.faturalanan_miktar = decimal(
                    veri.get("faturalanan_miktar", 0), "Faturalanan miktar", Decimal("0")
                )
                siparis.satirlar.append(satir)
        if not yeni:
            for sid, satir in mevcut.items():
                if sid in gorulen:
                    continue
                sevk = decimal(satir.irsaliyelenen_miktar or 0, "Sevk", Decimal("0"))
                fat = decimal(satir.faturalanan_miktar or 0, "Fatura", Decimal("0"))
                if sevk > 0 or fat > 0:
                    from sqlalchemy.orm import object_session

                    oturum = object_session(siparis)
                    bagli = (
                        SatisSiparisiService._bagli_evrak_metni(oturum, siparis, satir_idleri=[sid])
                        if oturum is not None
                        else ""
                    )
                    raise ValueError(
                        f"{satir.urun_kodu}: sevk veya fatura bağlantısı olan satır silinemez."
                        + (f"\nBağlı evrak: {bagli}" if bagli else "")
                    )
                siparis.satirlar.remove(satir)

    @staticmethod
    def durumu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        siparis = session.scalar(
            select(SatisSiparisi)
            .options(selectinload(SatisSiparisi.satirlar))
            .where(SatisSiparisi.id == siparis_id)
        )
        if siparis is None or siparis.durum == "İPTAL":
            return
        if siparis.durum == "TASLAK":
            return
        if not siparis.satirlar:
            siparis.durum = "AÇIK"
            return
        if all(s.faturalanan_miktar >= s.miktar for s in siparis.satirlar):
            siparis.durum = "FATURALI"
        elif any(s.faturalanan_miktar > 0 for s in siparis.satirlar):
            siparis.durum = "KISMİ FATURALI"
        elif all(s.irsaliyelenen_miktar >= s.miktar for s in siparis.satirlar):
            siparis.durum = "İRSALİYELİ"
        elif any(s.irsaliyelenen_miktar > 0 for s in siparis.satirlar):
            siparis.durum = "KISMİ İRSALİYELİ"
        else:
            siparis.durum = "AÇIK"

    @staticmethod
    def aktif_musterileri() -> list[Cari]:
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            siparisler = session.scalars(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar), selectinload(SatisSiparisi.cari))
                .order_by(SatisSiparisi.id.desc())
            ).all()
            sonuc = []
            for siparis in siparisler:
                toplam = SatisSiparisiService.siparis_toplami(siparis.satirlar)
                tahsilat = sum((item.tutar for item in siparis.tahsilatlar), Decimal("0"))
                sonuc.append(
                    {
                        "siparis": siparis,
                        "musteri": siparis.cari,
                        "toplam": toplam["genel_toplam"],
                        "tahsilat": tahsilat,
                        "kalan": toplam["genel_toplam"] - tahsilat,
                        "ilerleme": siparis_ilerleme(siparis),
                        "gecikti": siparis_gecikti_mi(siparis),
                        "miktarlar": SatisSiparisiService.calculate_order_progress(siparis.satirlar),
                    }
                )
            return sonuc

    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text

        from database.database import engine

        import database.models.satis_siparisi  # noqa: F401

        if engine is None:
            return
        SatisSiparisi.__table__.create(engine, checkfirst=True)
        SatisSiparisiSatiri.__table__.create(engine, checkfirst=True)
        SatisSiparisiTahsilati.__table__.create(engine, checkfirst=True)
        insp = inspect(engine)
        if insp.has_table("satis_siparisleri"):
            ust_mevcut = {c["name"] for c in insp.get_columns("satis_siparisleri")}
            ust_eklenecekler = {
                "siparis_saati": "VARCHAR(8)",
                "depo": "VARCHAR(100)",
                "teslimat_adresi": "TEXT",
                "teslimat_il": "VARCHAR(80)",
                "teslimat_ilce": "VARCHAR(80)",
                "musteri_siparis_no": "VARCHAR(80)",
                "para_birimi": "VARCHAR(3) DEFAULT 'TRY' NOT NULL",
                "kur": "NUMERIC(18, 6) DEFAULT 1 NOT NULL",
                "teslim_kosulu": "VARCHAR(300)",
                "odeme_kosulu": "VARCHAR(300)",
            }
            ust_eksikler = {a: t for a, t in ust_eklenecekler.items() if a not in ust_mevcut}
            if ust_eksikler:
                with engine.begin() as connection:
                    for alan, tip in ust_eksikler.items():
                        connection.execute(
                            text(f'ALTER TABLE "satis_siparisleri" ADD COLUMN "{alan}" {tip}')
                        )
        if not insp.has_table("satis_siparisi_satirlari"):
            return
        mevcut = {c["name"] for c in insp.get_columns("satis_siparisi_satirlari")}
        eklenecekler = {
            "is_manual_item": "BOOLEAN DEFAULT 0 NOT NULL",
            "line_type": "VARCHAR(30) DEFAULT 'STOCK_PRODUCT' NOT NULL",
            "product_id": "INTEGER",
            "delivery_term_days": "INTEGER",
            "estimated_delivery_date": "DATE",
            "delivery_term_note": "VARCHAR(300)",
            "stock_pending": "BOOLEAN DEFAULT 0 NOT NULL",
            "iskonto_orani_2": "NUMERIC(7, 2) DEFAULT 0 NOT NULL",
            "iskonto_orani_3": "NUMERIC(7, 2) DEFAULT 0 NOT NULL",
        }
        eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
        if eksikler:
            with engine.begin() as connection:
                for alan, tip in eksikler.items():
                    connection.execute(
                        text(f'ALTER TABLE "satis_siparisi_satirlari" ADD COLUMN "{alan}" {tip}')
                    )

    @staticmethod
    def getir(siparis_id: int) -> SatisSiparisi | None:
        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar), selectinload(SatisSiparisi.cari))
                .where(SatisSiparisi.id == siparis_id)
            )

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        tahsilat_verileri: list[dict[str, Any]] | None,
        siparis_id: int | None = None,
    ) -> SatisSiparisi:
        """Siparişi kaydeder. ``tahsilat_verileri=None``: kayıtlı avanslar olduğu gibi korunur.

        Stok hareketi veya cari borç oluşturmaz.
        """
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        SatisSiparisiService.schema_hazirla()
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_approve,
            stamp_create,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        siparis_tarihi = veriler["siparis_tarihi"]
        termin_tarihi = veriler["termin_tarihi"]
        if siparis_tarihi > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        if termin_tarihi < siparis_tarihi:
            raise ValueError("Termin tarihi sipariş tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir ürün satırı ekleyin.")
        para_birimi = (bos_metin(veriler.get("para_birimi")) or "TRY").upper()
        kur_ham = veriler.get("kur")
        kur = decimal(1 if kur_ham in (None, "") else kur_ham, "Kur", Decimal("0"))
        if para_birimi == "TRY":
            kur = Decimal("1")
        elif kur <= 0:
            raise ValueError(f"{para_birimi} siparişte kur sıfırdan büyük olmalıdır.")
        with get_session() as session:
            from database.stok_service import StokService

            yeni = False
            eski = session.get(SatisSiparisi, siparis_id) if siparis_id else None
            taslak_kalir = not veriler.get("onayla") and (eski is None or (eski.durum or "") == "TASLAK")
            birim_sorunu = StokService.belge_birim_sorunu(
                session, satir_verileri, "Satış siparişi",
                mevcut=list(eski.satirlar) if eski is not None and (eski.durum or "") != "TASLAK" else None,
                eylem="onaylanamaz" if taslak_kalir else "kaydedilemedi")
            if birim_sorunu is not None and not taslak_kalir:
                raise birim_sorunu
            if siparis_id:
                siparis = session.get(SatisSiparisi, siparis_id)
                if siparis is None:
                    raise ValueError("Sipariş bulunamadı.")
                if (siparis.durum or "") == "İPTAL":
                    raise ValueError("İptal edilmiş sipariş düzenlenemez.")
                bagli = any(
                    decimal(s.irsaliyelenen_miktar or 0, "S") > 0 or decimal(s.faturalanan_miktar or 0, "F") > 0
                    for s in siparis.satirlar
                )
                if bagli and int(veriler["cari_id"]) != int(siparis.cari_id):
                    raise ValueError(
                        "Sevk veya fatura bağlantısı olan siparişin müşterisi değiştirilemez.\n"
                        f"Bağlı evrak: {SatisSiparisiService._bagli_evrak_metni(session, siparis)}"
                    )
                if bagli and para_birimi != (siparis.para_birimi or "TRY").upper():
                    raise ValueError(
                        "Sevk veya fatura bağlantısı olan siparişin para birimi değiştirilemez.\n"
                        f"Bağlı evrak: {SatisSiparisiService._bagli_evrak_metni(session, siparis)}"
                    )
                # Satır kimliklerini koru (irsaliye/fatura FK'ları kırılmasın).
                if tahsilat_verileri is not None:
                    siparis.tahsilatlar.clear()
            else:
                yeni = True
                ozel_no = (veriler.get("siparis_no") or "").strip()
                if ozel_no and session.scalar(
                    select(SatisSiparisi.id).where(SatisSiparisi.siparis_no == ozel_no)
                ):
                    raise ValueError(f"{ozel_no} sipariş numarası zaten kullanılıyor; farklı bir numara girin.")
                baslangic_durum = "AÇIK" if veriler.get("onayla") else "TASLAK"
                siparis = SatisSiparisi(
                    siparis_no=ozel_no or SatisSiparisiService.siparis_no(),
                    durum=baslangic_durum,
                )
                session.add(siparis)
            # Maliyet / hedef kâr sipariş UI'da yok; eski kayıt değerini koru, yoksa varsayılan.
            maliyet_yontemi = (
                bos_metin(veriler.get("maliyet_yontemi"))
                or (getattr(siparis, "maliyet_yontemi", None) if not yeni else None)
                or "FIFO"
            )
            hedef_ham = veriler.get("hedef_kar_marji", None)
            if hedef_ham in (None, ""):
                hedef_ham = getattr(siparis, "hedef_kar_marji", 0) if not yeni else 0
            hedef = decimal(hedef_ham or 0, "Hedef kâr marjı", Decimal("0"))
            if not 0 <= hedef < Decimal("100"):
                raise ValueError("Hedef kâr marjı 0 ile 99,99 arasında olmalıdır.")
            siparis.siparis_tarihi = siparis_tarihi
            siparis.termin_tarihi = termin_tarihi
            if "siparis_saati" in veriler:
                saat = bos_metin(veriler.get("siparis_saati")) or None
                siparis.siparis_saati = saat
            siparis.cari_id = int(veriler["cari_id"])
            siparis.maliyet_yontemi = maliyet_yontemi
            siparis.hedef_kar_marji = hedef
            from database.sube_service import SubeService

            siparis.sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            siparis.aciklama = bos_metin(veriler.get("aciklama")) or None
            siparis.para_birimi = para_birimi
            siparis.kur = kur
            for alan in (
                "depo", "teslimat_adresi", "teslimat_il", "teslimat_ilce", "musteri_siparis_no",
                "teslim_kosulu", "odeme_kosulu",
            ):
                if alan in veriler or yeni:
                    setattr(siparis, alan, bos_metin(veriler.get(alan)) or None)
            if veriler.get("onayla") and siparis.durum == "TASLAK":
                siparis.durum = "AÇIK"
            if siparis.durum == "İPTAL" and not siparis_id:
                siparis.durum = "AÇIK"
            SatisSiparisiService._satirlari_uygula(siparis, satir_verileri, yeni=yeni)
            toplam = SatisSiparisiService.siparis_toplami(siparis.satirlar)
            tahsilat_toplam = Decimal("0")
            if tahsilat_verileri is None:
                tahsilat_toplam = sum(
                    (decimal(t.tutar or 0, "Tahsilat") for t in siparis.tahsilatlar), Decimal("0")
                )
            for veri in tahsilat_verileri or []:
                tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0"))
                tahsilat_toplam += tutar
                siparis.tahsilatlar.append(SatisSiparisiTahsilati(tahsilat_tarihi=veri["tahsilat_tarihi"], tutar=tutar, odeme_sekli=veri["odeme_sekli"], hesap=veri.get("hesap"), aciklama=veri.get("aciklama")))
            if tahsilat_toplam > toplam["genel_toplam"]:
                raise ValueError("Toplam tahsilat sipariş toplamından büyük olamaz.")
            if yeni:
                stamp_create(siparis)
            else:
                stamp_update(siparis)
            if veriler.get("onayla"):
                stamp_approve(siparis)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError(
                    "Sipariş kaydedilemedi; sipariş numarası başka bir kayıtta kullanılıyor olabilir. "
                    "Tekrar deneyin."
                ) from hata
            sid = int(siparis.id)
            sno = siparis.siparis_no
        audit_document(
            "SIPARIS_OLUSTUR" if yeni else "SIPARIS_DUZENLE",
            modul="satis_siparis",
            kayit_id=str(sid),
            belge_no=sno,
        )
        if veriler.get("onayla"):
            audit_document(
                "SIPARIS_ONAY",
                modul="satis_siparis",
                kayit_id=str(sid),
                belge_no=sno,
            )
        sonuc = SatisSiparisiService.getir(sid) or siparis
        sonuc.birim_uyarisi = str(birim_sorunu) if birim_sorunu is not None else None
        return sonuc

    @staticmethod
    def iptal_et(siparis_id: int, sebep: str | None = None) -> None:
        yazma_zorunlu("satis_duzenleme", "iptal")
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_cancel,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        neden = (sebep or "").strip()
        if not neden:
            raise ValueError("İptal nedeni zorunludur.")
        with get_session() as session:
            siparis = session.get(SatisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            if siparis.durum == "İPTAL":
                return
            siparis.durum = "İPTAL"
            stamp_cancel(siparis, neden)
            sno = siparis.siparis_no
        from database.deleted_record_service import ENTITY_SATIS_SIPARIS, safe_log_cancel

        safe_log_cancel(ENTITY_SATIS_SIPARIS, siparis_id, note=f"Satış siparişi iptal: {neden}")
        audit_document(
            "SIPARIS_IPTAL",
            modul="satis_siparis",
            kayit_id=str(siparis_id),
            belge_no=sno,
            aciklama=neden,
        )

    # ------------------------------------------------------------ bağlı evrak
    @staticmethod
    def _bagli_evrak_kayitlari(session, siparis, satir_idleri=None, *, silinen_dahil: bool = False) -> list[dict[str, Any]]:
        """Sipariş satırlarına bağlı irsaliye ve faturalar (iptal edilenler dahil, silinen fatura hariç)."""
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri

        idler = [int(i) for i in (satir_idleri or [s.id for s in siparis.satirlar]) if i]
        sonuc: dict[tuple[str, int], dict[str, Any]] = {}
        if not idler:
            return []
        for satir, belge in session.execute(
            select(SatisIrsaliyesiSatiri, SatisIrsaliyesi)
            .join(SatisIrsaliyesi, SatisIrsaliyesiSatiri.irsaliye_id == SatisIrsaliyesi.id)
            .where(SatisIrsaliyesiSatiri.siparis_satiri_id.in_(idler))
        ).all():
            kayit = sonuc.setdefault(
                ("İrsaliye", int(belge.id)),
                {
                    "tur": "İrsaliye",
                    "id": int(belge.id),
                    "no": belge.irsaliye_no,
                    "tarih": belge.irsaliye_tarihi,
                    "durum": belge.durum or "",
                    "iptal": (belge.durum or "") == "İPTAL",
                    "miktar": Decimal("0"),
                },
            )
            kayit["miktar"] += decimal(satir.miktar or 0, "Miktar")
        for satir, belge in session.execute(
            select(SatisFaturasiSatiri, SatisFaturasi)
            .join(SatisFaturasi, SatisFaturasiSatiri.fatura_id == SatisFaturasi.id)
            .where(SatisFaturasiSatiri.siparis_satiri_id.in_(idler))
        ).all():
            if getattr(belge, "is_deleted", False) and not silinen_dahil:
                continue
            kayit = sonuc.setdefault(
                ("Fatura", int(belge.id)),
                {
                    "tur": "Fatura",
                    "id": int(belge.id),
                    "no": belge.fatura_no,
                    "tarih": belge.fatura_tarihi,
                    "durum": belge.durum or "",
                    "iptal": (belge.durum or "") == "İPTAL",
                    "miktar": Decimal("0"),
                },
            )
            kayit["miktar"] += decimal(satir.miktar or 0, "Miktar")
        return sorted(sonuc.values(), key=lambda k: (k["tur"] != "İrsaliye", str(k["tarih"]), k["no"] or ""))

    @staticmethod
    def _bagli_evrak_metni(session, siparis, satir_idleri=None, *, iptal_dahil: bool = False) -> str:
        kayitlar = SatisSiparisiService._bagli_evrak_kayitlari(session, siparis, satir_idleri)
        return ", ".join(
            f"{k['tur']} {k['no']}" + (" (iptal)" if k["iptal"] else "")
            for k in kayitlar
            if iptal_dahil or not k["iptal"]
        ) or "-"

    @staticmethod
    def bagli_evraklar(siparis_id: int) -> list[dict[str, Any]]:
        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            siparis = session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar))
                .where(SatisSiparisi.id == int(siparis_id))
            )
            if siparis is None:
                return []
            return SatisSiparisiService._bagli_evrak_kayitlari(session, siparis)

    @staticmethod
    def bagli_evrak_metni(siparis_id: int, satir_idleri=None) -> str:
        """«İrsaliye X, Fatura Y» — engellenen işlem mesajları için (iptal edilenler hariç)."""
        with get_session() as session:
            siparis = session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar))
                .where(SatisSiparisi.id == int(siparis_id))
            )
            if siparis is None:
                return "-"
            return SatisSiparisiService._bagli_evrak_metni(session, siparis, satir_idleri)

    @staticmethod
    def _sayac_var(siparis) -> bool:
        return any(
            decimal(s.irsaliyelenen_miktar or 0, "S") > 0 or decimal(s.faturalanan_miktar or 0, "F") > 0
            for s in siparis.satirlar
        )

    # ------------------------------------------------------------ onay / sil
    @staticmethod
    def onayla(siparis_id: int) -> None:
        """TASLAK → AÇIK (irsaliye/faturaya aktarılabilir). Stok/cari etkisi yok."""
        yazma_zorunlu("satis_duzenleme", "onay")
        from database.user_audit import OturumGerekli, audit_document, require_user_session, stamp_approve

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        with get_session() as session:
            siparis = session.get(SatisSiparisi, int(siparis_id))
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            if (siparis.durum or "") == "İPTAL":
                raise ValueError("İptal edilmiş sipariş onaylanamaz.")
            if (siparis.durum or "") != "TASLAK":
                return
            if not siparis.satirlar:
                raise ValueError("Satırı olmayan sipariş onaylanamaz.")
            from database.stok_service import StokService

            birim_sorunu = StokService.belge_birim_sorunu(session, list(siparis.satirlar), "Satış siparişi",
                                                          eylem="onaylanamaz")
            if birim_sorunu is not None:
                raise birim_sorunu
            siparis.durum = "AÇIK"
            stamp_approve(siparis)
            sno = siparis.siparis_no
        audit_document("SIPARIS_ONAY", modul="satis_siparis", kayit_id=str(siparis_id), belge_no=sno)

    @staticmethod
    def onay_kaldir(siparis_id: int) -> None:
        """AÇIK → TASLAK; yalnızca hiç sevk/fatura bağlantısı yoksa."""
        yazma_zorunlu("satis_duzenleme", "onay")
        from database.user_audit import OturumGerekli, audit_document, require_user_session

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        with get_session() as session:
            siparis = session.get(SatisSiparisi, int(siparis_id))
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            if (siparis.durum or "") == "TASLAK":
                return
            if (siparis.durum or "") == "İPTAL":
                raise ValueError("İptal edilmiş siparişin onayı kaldırılamaz.")
            aktif = [k for k in SatisSiparisiService._bagli_evrak_kayitlari(session, siparis) if not k["iptal"]]
            if aktif or SatisSiparisiService._sayac_var(siparis):
                raise ValueError(
                    "Sevk veya fatura bağlantısı olan siparişin onayı kaldırılamaz.\n"
                    f"Bağlı evrak: {SatisSiparisiService._bagli_evrak_metni(session, siparis)}"
                )
            siparis.durum = "TASLAK"
            siparis.approved_by_user_id = None
            siparis.approved_by_full_name = None
            siparis.approved_at = None
            sno = siparis.siparis_no
        audit_document("SIPARIS_ONAY_KALDIR", modul="satis_siparis", kayit_id=str(siparis_id), belge_no=sno)

    @staticmethod
    def sil(siparis_id: int, sebep: str | None = None) -> str:
        """Bağlantısız siparişi kalıcı siler (silme günlüğüne yazılır).

        İrsaliye/fatura satırı (iptal edilmiş olsa bile), teklif bağlantısı veya avans
        tahsilatı olan sipariş silinemez; iptal edilmelidir.
        """
        yazma_zorunlu("satis_duzenleme", "sil")
        SatisSiparisiService.schema_hazirla()
        from database.user_audit import OturumGerekli, audit_document, require_user_session

        reason = (sebep or "").strip() or "Kullanıcı tarafından silindi"
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        with get_session() as session:
            siparis = session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar))
                .where(SatisSiparisi.id == int(siparis_id))
            )
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            kayitlar = SatisSiparisiService._bagli_evrak_kayitlari(session, siparis, silinen_dahil=True)
            if kayitlar or SatisSiparisiService._sayac_var(siparis):
                raise ValueError(
                    "İrsaliye veya faturaya aktarılmış sipariş silinemez.\n"
                    "Bağlı evrak: "
                    + (", ".join(f"{k['tur']} {k['no']}" + (" (iptal)" if k["iptal"] else "") for k in kayitlar) or "-")
                    + "\n"
                    "Bağlı evrak (iptal edilmiş olsa bile) sipariş satırlarına bağlıdır; silmek yerine siparişi iptal edin."
                )
            from database.models.satis_irsaliyesi import SatisIrsaliyesi
            from database.models.satis_faturasi import SatisFaturasi

            baslik_bagli = [
                *(f"İrsaliye {n}" for n in session.scalars(
                    select(SatisIrsaliyesi.irsaliye_no).where(SatisIrsaliyesi.siparis_id == siparis.id)
                )),
                *(f"Fatura {n}" for n in session.scalars(
                    select(SatisFaturasi.fatura_no).where(SatisFaturasi.siparis_id == siparis.id)
                )),
            ]
            if baslik_bagli:
                raise ValueError(
                    "Bu siparişe bağlı evrak var; sipariş silinemez.\n"
                    f"Bağlı evrak: {', '.join(baslik_bagli)}\nSilmek yerine siparişi iptal edin."
                )
            try:
                from database.models.satis_teklifi import SatisTeklifi

                teklifler = list(session.scalars(
                    select(SatisTeklifi.teklif_no).where(SatisTeklifi.siparis_id == siparis.id)
                ))
            except Exception:
                teklifler = []
            if teklifler:
                raise ValueError(
                    f"Sipariş teklif ile bağlantılı ({', '.join(str(t) for t in teklifler)}); silinemez. "
                    "Silmek yerine siparişi iptal edin."
                )
            if siparis.tahsilatlar:
                raise ValueError("Siparişte avans tahsilatı kayıtlı; sipariş silinemez. Silmek yerine iptal edin.")
            snapshot = {
                "siparis_no": siparis.siparis_no,
                "tarih": str(siparis.siparis_tarihi),
                "cari_id": siparis.cari_id,
                "durum": siparis.durum,
                "satirlar": [
                    {"urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "miktar": str(s.miktar), "birim": s.birim}
                    for s in siparis.satirlar
                ],
            }
            sid = int(siparis.id)
            sno = siparis.siparis_no
            unvan = getattr(getattr(siparis, "cari", None), "unvan", "") or ""
            session.delete(siparis)
            session.flush()
        from database.deleted_record_service import ENTITY_SATIS_SIPARIS, safe_log_cancel_snapshot

        safe_log_cancel_snapshot(
            ENTITY_SATIS_SIPARIS,
            sid,
            note=f"Satış siparişi silindi: {reason}",
            snapshot=snapshot,
            reason=reason,
            record_code=sno,
            record_title=unvan,
            module="satis_siparis",
        )
        audit_document("SIPARIS_SIL", modul="satis_siparis", kayit_id=str(sid), belge_no=sno, aciklama=reason)
        return sno

    @staticmethod
    def siparis_no() -> str:
        with get_session() as session:
            mevcutler = session.scalars(
                select(SatisSiparisi.siparis_no).where(SatisSiparisi.siparis_no.like("SIP-%"))
            ).all()
        son_numara = 0
        for siparis_no in mevcutler:
            ek = str(siparis_no)[4:]
            if len(ek) == 5 and ek.isdigit():
                son_numara = max(son_numara, int(ek))
        return f"SIP-{son_numara + 1:05d}"

    @staticmethod
    def calculate_order_progress(satirlar) -> dict[str, Decimal]:
        """Sipariş / sevk / fatura / kalan miktar özeti (FATURA_KAYNAK_KURALI)."""
        siparis = sevk = fatura = Decimal("0")
        for s in satirlar or []:
            get = s.get if isinstance(s, dict) else lambda a, d=0: getattr(s, a, d)
            m = decimal(get("miktar", 0), "Miktar", Decimal("0"))
            ir = decimal(get("irsaliyelenen_miktar", 0), "Sevk", Decimal("0"))
            fa = decimal(get("faturalanan_miktar", 0), "Fatura", Decimal("0"))
            siparis += m
            sevk += ir
            fatura += fa
        sevk_kalani = siparis - sevk
        fatura_kalani = siparis - fatura
        return {
            "siparis_miktar": siparis,
            "sevk_miktar": sevk,
            "fatura_miktar": fatura,
            "sevk_kalani": sevk_kalani,
            "fatura_kalani": fatura_kalani,
            # Eski anahtarlar (geri uyumluluk)
            "kalan_miktar": sevk_kalani,
            "kalan_faturalanacak": fatura_kalani,
        }

    @staticmethod
    def siparis_toplami(satirlar: list[SatisSiparisiSatiri]) -> dict[str, Decimal | float]:
        """Belge tutarları (``satir_hesapla``) + şirket içi maliyet/kâr (müşteri çıktısına girmez)."""
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        maliyet = Decimal("0")
        kar = Decimal("0")
        for satir in satirlar:
            h = satir_hesapla(
                satir.miktar,
                satir.birim_satis_fiyati,
                satir.iskonto_orani or 0,
                getattr(satir, "iskonto_orani_2", 0) or 0,
                getattr(satir, "iskonto_orani_3", 0) or 0,
                satir.kdv_orani or 0,
            )
            ara += h["brut"]
            iskonto += h["iskonto"]
            kdv += h["kdv"]
            birim_maliyet = SatisSiparisiService.birim_maliyeti(satir, satir.siparis.maliyet_yontemi if satir.siparis else "FIFO")
            maliyet += satir.miktar * birim_maliyet
            kar += h["net"] - satir.miktar * birim_maliyet
        net = ara - iskonto
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": net + kdv, "net": net, "maliyet": maliyet, "kar": kar, "marj": (kar / net * Decimal("100")) if net else Decimal("0")}

    @staticmethod
    def birim_maliyeti(satir: SatisSiparisiSatiri, yontem: str) -> Decimal:
        return {"FIFO": satir.fifo_birim_maliyeti, "SON ALIŞ FİYATI": satir.son_alis_birim_maliyeti, "ORTALAMA ALIŞ FİYATI": satir.ortalama_birim_maliyeti, "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": satir.agirlikli_ortalama_birim_maliyeti}.get(yontem, Decimal("0"))

    @staticmethod
    def tahmini_bakiye(cari_id: int, siparis_toplami: Decimal, tahsilat: Decimal) -> Decimal:
        ozet = next((item for item in CariService.listele(hizli=True) if item["cari"].id == cari_id), None)
        return (ozet["bakiye"] if ozet else Decimal("0")) + siparis_toplami - tahsilat
