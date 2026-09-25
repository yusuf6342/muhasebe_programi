"""Kalan sipariş / kalan irsaliye rapor ve kısmi dönüşüm veri katmanı.

UI'dan bağımsızdır. Sevk kalanı ile fatura kalanı FATURA_KAYNAK_KURALI gereği
ayrı tutulur (doğrudan fatura sevk sayılmaz).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.satis_faturasi import SatisFaturasiSatiri
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import bos_metin, decimal, satir_kalanlari


IPTAL_DURUMLARI = frozenset({"İPTAL", "IPTAL"})


def _siparis_rapor_durumu(siparis: SatisSiparisi, satir: SatisSiparisiSatiri) -> str:
    d = (siparis.durum or "").strip().upper()
    if d in IPTAL_DURUMLARI:
        return "İptal"
    kalan = satir_kalanlari(satir.miktar, satir.irsaliyelenen_miktar, satir.faturalanan_miktar)
    if kalan["fatura_kalani"] <= 0:
        return "Tamamlandı"
    if (satir.faturalanan_miktar or 0) > 0:
        return "Kısmen Faturalandı"
    return "Açık"


def _irsaliye_rapor_durumu(irsaliye: SatisIrsaliyesi, satir: SatisIrsaliyesiSatiri) -> str:
    d = (irsaliye.durum or "").strip().upper()
    if d in IPTAL_DURUMLARI:
        return "İptal"
    kalan = decimal(satir.miktar or 0, "Miktar", Decimal("0")) - decimal(
        satir.faturalanan_miktar or 0, "Fatura", Decimal("0")
    )
    if kalan <= 0:
        return "Tamamlandı"
    if (satir.faturalanan_miktar or 0) > 0 or d in ("KISMİ FATURALANDI", "KISMI FATURALANDI"):
        return "Kısmen Faturalandı"
    return "Açık"


def _satir_net_tutar(miktar, birim_fiyat, iskonto_orani=0, kdv_orani=0) -> dict[str, Decimal]:
    m = decimal(miktar or 0, "Miktar", Decimal("0"))
    bf = decimal(birim_fiyat or 0, "Fiyat", Decimal("0"))
    isk = decimal(iskonto_orani or 0, "İskonto", Decimal("0"))
    kdv = decimal(kdv_orani or 0, "KDV", Decimal("0"))
    brut = m * bf
    indirim = brut * isk / Decimal("100")
    net = brut - indirim
    kdv_t = net * kdv / Decimal("100")
    return {"brut": brut, "iskonto": indirim, "net": net, "kdv": kdv_t, "genel": net + kdv_t}


def _fatura_nolari_siparis_satiri(session, siparis_satiri_id: int) -> list[str]:
    satirlar = session.scalars(
        select(SatisFaturasiSatiri)
        .options(selectinload(SatisFaturasiSatiri.fatura))
        .where(SatisFaturasiSatiri.siparis_satiri_id == int(siparis_satiri_id))
    ).all()
    nos: list[str] = []
    for s in satirlar:
        fat = s.fatura
        if fat is None or (fat.durum or "").upper() in IPTAL_DURUMLARI:
            continue
        no = fat.fatura_no
        if no and no not in nos:
            nos.append(no)
    return nos


def _fatura_nolari_irsaliye_satiri(session, irsaliye_satiri_id: int) -> list[str]:
    satirlar = session.scalars(
        select(SatisFaturasiSatiri)
        .options(selectinload(SatisFaturasiSatiri.fatura))
        .where(SatisFaturasiSatiri.irsaliye_satiri_id == int(irsaliye_satiri_id))
    ).all()
    nos: list[str] = []
    for s in satirlar:
        fat = s.fatura
        if fat is None or (fat.durum or "").upper() in IPTAL_DURUMLARI:
            continue
        no = fat.fatura_no
        if no and no not in nos:
            nos.append(no)
    return nos


def miktar_kalani_dogrula(
    istenen: object,
    kalan: object,
    *,
    alan: str = "Miktar",
    sifir_izinli: bool = True,
) -> Decimal:
    """0 veya kalan arası miktar; kalanı aşamaz."""
    m = decimal(istenen or 0, alan, Decimal("0"))
    k = decimal(kalan or 0, "Kalan", Decimal("0"))
    if m < 0:
        raise ValueError(f"{alan} negatif olamaz.")
    if not sifir_izinli and m <= 0:
        raise ValueError(f"{alan} sıfırdan büyük olmalıdır.")
    if m > k:
        raise ValueError(f"{alan} kalan miktarı ({k}) aşamaz.")
    return m


def _satir_id_esit(a, b) -> bool:
    try:
        return a is not None and b is not None and int(a) == int(b)
    except (TypeError, ValueError):
        return False


def formdaki_siparis_satir_miktari(form_satirlar: list[dict[str, Any]], siparis_satiri_id) -> Decimal:
    """Bu fatura formunda aynı sipariş satırına bağlı miktar toplamı."""
    toplam = Decimal("0")
    for s in form_satirlar or []:
        if _satir_id_esit(s.get("siparis_satiri_id"), siparis_satiri_id):
            toplam += decimal(s.get("miktar") or 0, "Miktar", Decimal("0"))
    return toplam


def kayitli_fatura_siparis_satir_miktari(fatura_satirlar, siparis_satiri_id) -> Decimal:
    """Kayıtlı fatura satırlarında (DB) aynı sipariş satırı miktarı."""
    toplam = Decimal("0")
    for s in fatura_satirlar or []:
        sid = getattr(s, "siparis_satiri_id", None)
        if sid is None and isinstance(s, dict):
            sid = s.get("siparis_satiri_id")
        if _satir_id_esit(sid, siparis_satiri_id):
            miktar = getattr(s, "miktar", None)
            if miktar is None and isinstance(s, dict):
                miktar = s.get("miktar")
            toplam += decimal(miktar or 0, "Miktar", Decimal("0"))
    return toplam


def siparis_fatura_aktarim_satirlari(
    siparis: SatisSiparisi,
    *,
    form_satirlar: list[dict[str, Any]] | None = None,
    bu_fatura_db_satirlar=None,
) -> list[dict[str, Any]]:
    """Siparişin faturaya eklenecek açık kalan satırları.

    Mevcut bağımsız fatura satırlarını silmez; çağıran APPEND eder.
    Aynı sipariş satırı bu faturada zaten varsa miktar düşülür (mükerrer yok).
    Kayıtlı taslakta faturalanan_miktar bu faturayı da içerdiği için DB katkısı geri eklenir.
    """
    form_satirlar = list(form_satirlar or [])
    sonuc: list[dict[str, Any]] = []
    for satir in siparis.satirlar or []:
        miktar = decimal(satir.miktar or 0, "Miktar", Decimal("0"))
        faturalanan = decimal(satir.faturalanan_miktar or 0, "Faturalanan", Decimal("0"))
        db_bu = kayitli_fatura_siparis_satir_miktari(bu_fatura_db_satirlar, satir.id)
        form_bu = formdaki_siparis_satir_miktari(form_satirlar, satir.id)
        # Global kalan + bu faturanın DB rezervi − formda duran
        kalan = miktar - faturalanan + db_bu - form_bu
        if kalan <= 0:
            continue
        sonuc.append(
            {
                "siparis_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": bos_metin(satir.aciklama),
                "miktar": kalan,
                "birim": satir.birim,
                "birim_satis_fiyati": satir.birim_satis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": 0,
                "iskonto_orani_3": 0,
                "kdv_orani": satir.kdv_orani,
                "fifo_birim_maliyeti": 0,
                "son_alis_birim_maliyeti": 0,
                "ortalama_birim_maliyeti": 0,
                "agirlikli_ortalama_birim_maliyeti": 0,
                "lot_no": "",
                "lot_cikisi": "",
                "irsaliyelenen_miktar": satir.irsaliyelenen_miktar or 0,
                "faturalanan_miktar": 0,
                "manuel_fiyat": False,
                "satir_para_birimi": "TRY",
                "para_birimi": "TRY",
                "kur": "1",
                "irsaliye_satiri_id": None,
            }
        )
    return sonuc


def birim_miktar_cevir(
    miktar: object,
    kaynak_birim: str,
    hedef_birim: str,
    stok_veya_birimler=None,
    ana_birim: str = "Adet",
) -> Decimal:
    """Farklı birimde miktar dönüşümü; kural yoksa açık hata."""
    m = decimal(miktar or 0, "Miktar", Decimal("0"))
    kb = (kaynak_birim or "").strip()
    hb = (hedef_birim or "").strip()
    if not hb or not kb or kb.casefold() == hb.casefold():
        return m
    if stok_veya_birimler is None:
        raise ValueError(
            f"'{kb}' → '{hb}' birim dönüşümü için stok kartı birim tanımı bulunamadı."
        )
    from database.stok_service import StokService

    try:
        onizleme = StokService.birim_donusum_onizleme(
            m, kb, hb, stok_veya_birimler, ana_birim=ana_birim
        )
        if isinstance(onizleme, dict):
            return decimal(onizleme.get("hedef_miktar", 0), "Dönüşen miktar", Decimal("0"))
        return decimal(onizleme, "Dönüşen miktar", Decimal("0"))
    except Exception as exc:
        raise ValueError(
            f"'{kb}' → '{hb}' birim dönüşümü yapılamadı: {exc}"
        ) from exc


def siparis_secim_satirlari(siparis: SatisSiparisi, *, hedef: str) -> list[dict[str, Any]]:
    """Kısmi irsaliye/fatura seçim diyaloğu için satır listesi.

    hedef: 'irsaliye' | 'fatura'
    """
    hedef = (hedef or "").strip().lower()
    sonuc: list[dict[str, Any]] = []
    for satir in siparis.satirlar or []:
        kalanlar = satir_kalanlari(
            satir.miktar, satir.irsaliyelenen_miktar, satir.faturalanan_miktar
        )
        if hedef == "irsaliye":
            kalan = kalanlar["sevk_kalani"]
            onceki = decimal(satir.irsaliyelenen_miktar or 0, "Sevk", Decimal("0"))
        else:
            kalan = kalanlar["fatura_kalani"]
            onceki = decimal(satir.faturalanan_miktar or 0, "Fatura", Decimal("0"))
        if kalan <= 0:
            continue
        sonuc.append(
            {
                "kaynak_satir_id": satir.id,
                "siparis_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "aciklama": bos_metin(satir.aciklama),
                "birim": satir.birim,
                "siparis_miktar": decimal(satir.miktar or 0, "Miktar", Decimal("0")),
                "onceki_miktar": onceki,
                "kalan_miktar": kalan,
                "bu_belge_miktar": kalan,
                "birim_satis_fiyati": satir.birim_satis_fiyati,
                "birim_fiyat": satir.birim_satis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
                "irsaliyelenen_miktar": satir.irsaliyelenen_miktar or 0,
                "faturalanan_miktar": satir.faturalanan_miktar or 0,
            }
        )
    return sonuc


def irsaliye_secim_satirlari(irsaliye: SatisIrsaliyesi) -> list[dict[str, Any]]:
    """Kısmi irsaliye→fatura seçim satırları."""
    sonuc: list[dict[str, Any]] = []
    for satir in irsaliye.satirlar or []:
        sevk = decimal(satir.miktar or 0, "Miktar", Decimal("0"))
        fat = decimal(satir.faturalanan_miktar or 0, "Fatura", Decimal("0"))
        kalan = sevk - fat
        if kalan <= 0:
            continue
        sonuc.append(
            {
                "kaynak_satir_id": satir.id,
                "irsaliye_satiri_id": satir.id,
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "aciklama": bos_metin(satir.aciklama),
                "birim": satir.birim,
                "siparis_miktar": sevk,
                "onceki_miktar": fat,
                "kalan_miktar": kalan,
                "bu_belge_miktar": kalan,
                "birim_satis_fiyati": satir.birim_fiyat,
                "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "kdv_orani": satir.kdv_orani,
            }
        )
    return sonuc


def _secim_miktar_birimli(s: dict[str, Any]) -> tuple[Decimal, str]:
    """Kalan doğrulaması + isteğe bağlı hedef birim dönüşümü."""
    miktar = miktar_kalani_dogrula(
        s.get("bu_belge_miktar", 0), s.get("kalan_miktar", 0), sifir_izinli=True
    )
    kaynak_birim = (s.get("birim") or "").strip()
    hedef_birim = (s.get("hedef_birim") or kaynak_birim).strip()
    if miktar <= 0:
        return miktar, kaynak_birim or "Adet"
    if hedef_birim and kaynak_birim and hedef_birim.casefold() != kaynak_birim.casefold():
        from database.database import get_session
        from database.stok_service import StokService

        with get_session() as session:
            stok = StokService._stok_yukle(session, stok_kodu=s.get("urun_kodu"))
            if stok is None:
                raise ValueError(
                    f"{s.get('urun_kodu')}: '{kaynak_birim}' → '{hedef_birim}' "
                    "dönüşümü için stok kartı bulunamadı."
                )
            ana = getattr(stok, "ana_birim", None) or "Adet"
            miktar = birim_miktar_cevir(
                miktar, kaynak_birim, hedef_birim, stok, ana_birim=ana
            )
            return miktar, hedef_birim
    return miktar, kaynak_birim or "Adet"


def secimden_irsaliye_satirlari(secimler: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Seçim diyaloğu çıktısından irsaliye kartı satırları."""
    satirlar: list[dict[str, Any]] = []
    for s in secimler:
        miktar, birim = _secim_miktar_birimli(s)
        if miktar <= 0:
            continue
        satirlar.append(
            {
                "siparis_satiri_id": s.get("siparis_satiri_id") or s.get("kaynak_satir_id"),
                "urun_kodu": s["urun_kodu"],
                "urun_adi": s["urun_adi"],
                "aciklama": bos_metin(s.get("aciklama")),
                "miktar": miktar,
                "birim": birim,
                "birim_fiyat": s.get("birim_fiyat") or s.get("birim_satis_fiyati") or 0,
                "iskonto_orani": s.get("iskonto_orani") or 0,
                "kdv_orani": s.get("kdv_orani") or 20,
                "siparis_miktar": s.get("siparis_miktar"),
                "onceki_sevk": s.get("onceki_miktar") or s.get("irsaliyelenen_miktar") or 0,
                "lot_no": "",
            }
        )
    if not satirlar:
        raise ValueError("En az bir satırda sıfırdan büyük miktar girin.")
    return satirlar


def secimden_fatura_satirlari(
    secimler: list[dict[str, Any]], *, kaynak: str
) -> list[dict[str, Any]]:
    """Seçim diyaloğu çıktısından fatura kartı satırları. kaynak: siparis|irsaliye"""
    satirlar: list[dict[str, Any]] = []
    for s in secimler:
        miktar, birim = _secim_miktar_birimli(s)
        if miktar <= 0:
            continue
        veri = {
            "urun_kodu": s["urun_kodu"],
            "urun_adi": s["urun_adi"],
            "barkod": "",
            "aciklama": bos_metin(s.get("aciklama")),
            "miktar": miktar,
            "birim": birim,
            "birim_satis_fiyati": s.get("birim_satis_fiyati") or s.get("birim_fiyat") or 0,
            "iskonto_orani": s.get("iskonto_orani") or 0,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": s.get("kdv_orani") or 20,
            "fifo_birim_maliyeti": 0,
            "son_alis_birim_maliyeti": 0,
            "ortalama_birim_maliyeti": 0,
            "agirlikli_ortalama_birim_maliyeti": 0,
            "lot_no": "",
            "lot_cikisi": "",
            "irsaliyelenen_miktar": s.get("irsaliyelenen_miktar") or 0,
            "faturalanan_miktar": 0,
            "manuel_fiyat": False,
            "satir_para_birimi": "TRY",
            "para_birimi": "TRY",
            "kur": "1",
        }
        if kaynak == "irsaliye":
            veri["irsaliye_satiri_id"] = s.get("irsaliye_satiri_id") or s.get("kaynak_satir_id")
            veri["siparis_satiri_id"] = s.get("siparis_satiri_id")
            veri["irsaliyelenen_miktar"] = miktar
        else:
            veri["siparis_satiri_id"] = s.get("siparis_satiri_id") or s.get("kaynak_satir_id")
            veri["irsaliye_satiri_id"] = None
        satirlar.append(veri)
    if not satirlar:
        raise ValueError("En az bir satırda sıfırdan büyük miktar girin.")
    return satirlar


def kalan_siparisler(
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
    cari_id: int | None = None,
    musteri: str | None = None,
    siparis_no: str | None = None,
    urun: str | None = None,
    durum: str | None = None,
    sadece_kalan: bool = True,
) -> dict[str, Any]:
    """Kalan sipariş satırları + para birimine göre toplamlar."""
    with get_session() as session:
        stmt = (
            select(SatisSiparisi)
            .options(
                selectinload(SatisSiparisi.satirlar),
                selectinload(SatisSiparisi.cari),
            )
            .order_by(SatisSiparisi.siparis_tarihi.desc(), SatisSiparisi.id.desc())
        )
        if baslangic is not None:
            stmt = stmt.where(SatisSiparisi.siparis_tarihi >= baslangic)
        if bitis is not None:
            stmt = stmt.where(SatisSiparisi.siparis_tarihi <= bitis)
        if cari_id is not None:
            stmt = stmt.where(SatisSiparisi.cari_id == int(cari_id))
        if siparis_no:
            stmt = stmt.where(SatisSiparisi.siparis_no.contains(siparis_no.strip()))
        siparisler = list(session.scalars(stmt).all())
        satirlar: list[dict[str, Any]] = []
        urun_f = (urun or "").strip().casefold()
        durum_f = (durum or "").strip()
        musteri_f = (musteri or "").strip().casefold()
        for siparis in siparisler:
            if (siparis.durum or "").upper() in IPTAL_DURUMLARI:
                continue
            musteri_obj = siparis.cari
            if musteri_f:
                aday = (
                    f"{getattr(musteri_obj, 'cari_kodu', '') or ''} "
                    f"{getattr(musteri_obj, 'unvan', '') or ''}"
                ).casefold()
                if musteri_f not in aday:
                    continue
            for satir in siparis.satirlar or []:
                if urun_f and urun_f not in (
                    (satir.urun_kodu or "").casefold() + " " + (satir.urun_adi or "").casefold()
                ):
                    continue
                kalanlar = satir_kalanlari(
                    satir.miktar, satir.irsaliyelenen_miktar, satir.faturalanan_miktar
                )
                rapor_d = _siparis_rapor_durumu(siparis, satir)
                if durum_f and durum_f.casefold() != rapor_d.casefold():
                    continue
                # Kalan sipariş: sevk veya fatura kalanı olanlar (talimat: ayrı sütunlar)
                if sadece_kalan and kalanlar["sevk_kalani"] <= 0 and kalanlar["fatura_kalani"] <= 0:
                    continue
                tutar = _satir_net_tutar(
                    kalanlar["fatura_kalani"],
                    satir.birim_satis_fiyati,
                    satir.iskonto_orani,
                    satir.kdv_orani,
                )
                fatura_nos = _fatura_nolari_siparis_satiri(session, satir.id)
                satirlar.append(
                    {
                        "siparis_id": siparis.id,
                        "siparis_satiri_id": satir.id,
                        "siparis_tarihi": siparis.siparis_tarihi,
                        "termin_tarihi": siparis.termin_tarihi,
                        "siparis_no": siparis.siparis_no,
                        "musteri_kodu": musteri_obj.cari_kodu if musteri_obj else "",
                        "musteri": musteri_obj.unvan if musteri_obj else "",
                        "cari_id": siparis.cari_id,
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "birim": satir.birim,
                        "siparis_miktar": decimal(satir.miktar or 0, "Miktar", Decimal("0")),
                        "sevk_miktar": decimal(
                            satir.irsaliyelenen_miktar or 0, "Sevk", Decimal("0")
                        ),
                        "sevk_kalani": kalanlar["sevk_kalani"],
                        "fatura_miktar": decimal(
                            satir.faturalanan_miktar or 0, "Fatura", Decimal("0")
                        ),
                        "fatura_kalani": kalanlar["fatura_kalani"],
                        "birim_fiyat": satir.birim_satis_fiyati,
                        "kalan_tutar": tutar["genel"],
                        "para_birimi": "TRY",
                        "durum": rapor_d,
                        "fatura_nolari": ", ".join(fatura_nos),
                    }
                )
        toplamlar: dict[str, Decimal] = {}
        for s in satirlar:
            pb = s["para_birimi"] or "TRY"
            toplamlar[pb] = toplamlar.get(pb, Decimal("0")) + s["kalan_tutar"]
        return {"satirlar": satirlar, "toplamlar": toplamlar}


def kalan_irsaliyeler(
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
    cari_id: int | None = None,
    musteri: str | None = None,
    urun: str | None = None,
    durum: str | None = None,
    sadece_kalan: bool = True,
) -> dict[str, Any]:
    """Faturalanmayı bekleyen irsaliye satırları."""
    with get_session() as session:
        stmt = (
            select(SatisIrsaliyesi)
            .options(
                selectinload(SatisIrsaliyesi.satirlar),
                selectinload(SatisIrsaliyesi.cari),
                selectinload(SatisIrsaliyesi.siparis),
            )
            .order_by(SatisIrsaliyesi.irsaliye_tarihi.desc(), SatisIrsaliyesi.id.desc())
        )
        if baslangic is not None:
            stmt = stmt.where(SatisIrsaliyesi.irsaliye_tarihi >= baslangic)
        if bitis is not None:
            stmt = stmt.where(SatisIrsaliyesi.irsaliye_tarihi <= bitis)
        if cari_id is not None:
            stmt = stmt.where(SatisIrsaliyesi.cari_id == int(cari_id))
        irsaliyeler = list(session.scalars(stmt).all())
        satirlar: list[dict[str, Any]] = []
        urun_f = (urun or "").strip().casefold()
        durum_f = (durum or "").strip()
        musteri_f = (musteri or "").strip().casefold()
        for ir in irsaliyeler:
            if (ir.durum or "").upper() in IPTAL_DURUMLARI:
                continue
            musteri_obj = ir.cari
            if musteri_f:
                aday = (
                    f"{getattr(musteri_obj, 'cari_kodu', '') or ''} "
                    f"{getattr(musteri_obj, 'unvan', '') or ''}"
                ).casefold()
                if musteri_f not in aday:
                    continue
            siparis = ir.siparis
            for satir in ir.satirlar or []:
                if urun_f and urun_f not in (
                    (satir.urun_kodu or "").casefold() + " " + (satir.urun_adi or "").casefold()
                ):
                    continue
                sevk = decimal(satir.miktar or 0, "Miktar", Decimal("0"))
                fat = decimal(satir.faturalanan_miktar or 0, "Fatura", Decimal("0"))
                kalan = sevk - fat
                rapor_d = _irsaliye_rapor_durumu(ir, satir)
                if durum_f and durum_f.casefold() != rapor_d.casefold():
                    continue
                if sadece_kalan and kalan <= 0:
                    continue
                tutar = _satir_net_tutar(
                    kalan, satir.birim_fiyat, satir.iskonto_orani, satir.kdv_orani
                )
                fatura_nos = _fatura_nolari_irsaliye_satiri(session, satir.id)
                satirlar.append(
                    {
                        "irsaliye_id": ir.id,
                        "irsaliye_satiri_id": satir.id,
                        "irsaliye_tarihi": ir.irsaliye_tarihi,
                        "irsaliye_no": ir.irsaliye_no,
                        "siparis_no": siparis.siparis_no if siparis else "",
                        "siparis_satiri_id": satir.siparis_satiri_id,
                        "musteri_kodu": musteri_obj.cari_kodu if musteri_obj else "",
                        "musteri": musteri_obj.unvan if musteri_obj else "",
                        "cari_id": ir.cari_id,
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "birim": satir.birim,
                        "sevk_miktar": sevk,
                        "fatura_miktar": fat,
                        "fatura_kalani": kalan,
                        "kalan_tutar": tutar["genel"],
                        "para_birimi": (ir.para_birimi or "TRY").upper(),
                        "durum": rapor_d,
                        "fatura_nolari": ", ".join(fatura_nos),
                    }
                )
        toplamlar: dict[str, Decimal] = {}
        for s in satirlar:
            pb = s["para_birimi"] or "TRY"
            toplamlar[pb] = toplamlar.get(pb, Decimal("0")) + s["kalan_tutar"]
        return {"satirlar": satirlar, "toplamlar": toplamlar}


def ornek_senaryo_kalanlari(
    siparis_miktar: Decimal,
    sevk_adimlari: list[Decimal],
    fatura_irsaliye_adimlari: list[tuple[int, Decimal]],
    dogrudan_fatura: list[Decimal] | None = None,
) -> dict[str, Decimal]:
    """Test yardımcısı: sevk/fatura sayaçlarını adım adım uygular.

    fatura_irsaliye_adimlari: (irsaliye_index, miktar) — irsaliye satırından fatura.
    dogrudan_fatura: siparişten doğrudan fatura miktarları.
    """
    sevk = Decimal("0")
    fatura = Decimal("0")
    irsaliye_kalanlar: list[Decimal] = []
    for miktar in sevk_adimlari:
        if sevk + miktar > siparis_miktar:
            raise ValueError("Sevk sipariş miktarını aşamaz.")
        sevk += miktar
        irsaliye_kalanlar.append(miktar)
    for idx, miktar in fatura_irsaliye_adimlari:
        if idx < 0 or idx >= len(irsaliye_kalanlar):
            raise ValueError("İrsaliye satırı bulunamadı.")
        if miktar > irsaliye_kalanlar[idx]:
            raise ValueError("İrsaliye fatura kalanını aşamaz.")
        if fatura + miktar > siparis_miktar:
            raise ValueError("Fatura sipariş miktarını aşamaz.")
        irsaliye_kalanlar[idx] -= miktar
        fatura += miktar
    for miktar in dogrudan_fatura or []:
        if fatura + miktar > siparis_miktar:
            raise ValueError("Fatura sipariş miktarını aşamaz.")
        fatura += miktar
    kalanlar = satir_kalanlari(siparis_miktar, sevk, fatura)
    return {
        "sevk_miktar": sevk,
        "fatura_miktar": fatura,
        "sevk_kalani": kalanlar["sevk_kalani"],
        "fatura_kalani": kalanlar["fatura_kalani"],
        "irsaliye_fatura_kalanlari": list(irsaliye_kalanlar),
    }
