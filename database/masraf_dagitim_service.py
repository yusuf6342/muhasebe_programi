"""Masraf dağıtımı: kayıtlı gider belgesini alış katmanlarının maliyetine aktarır.

Kurallar
- Dağıtım yeni gider/cari/ödeme/KDV kaydı üretmez; yalnızca maliyet aktarımı ve
  genel muhasebe düzeltme fişi yazar (gider → stok / SMM).
- Hedef, alış faturası satırının oluşturduğu FIFO lotudur (irsaliye stok üretmez;
  aynı alışın irsaliye + faturası tek katmandır).
- Pay tüm katmana yüklenir: stokta kalan kısım stok değerine, satılmış kısım SMM'ye,
  tedarikçiye iade edilmiş kısım giderde kalır. Depo transferleri zincir olarak izlenir.
- Taslak stok ve muhasebeyi etkilemez. Onay ve geri alma tek transaction'dır.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu, yetki_zorunlu
from database.database import get_session
from database.models.masraf_dagitim import (
    MasrafDagitim,
    MasrafDagitimGecmisi,
    MasrafDagitimKaynakSatiri,
    MasrafDagitimSatiri,
)
from database.session_manager import oturum
from database.turkce_normalize import turkce_normalize

KAYNAK_HIZMET = "HIZMET_FATURASI"
KAYNAK_ETIKETLERI = {KAYNAK_HIZMET: "Hizmet alış (gider) faturası"}

YONTEMLER = ("TUTAR", "MIKTAR", "AGIRLIK", "HACIM", "ELLE")
YONTEM_ETIKETLERI = {
    "TUTAR": "Tutar (KDV hariç net)",
    "MIKTAR": "Miktar (ana birim)",
    "AGIRLIK": "Ağırlık",
    "HACIM": "Hacim",
    "ELLE": "Elle dağıtım",
}

DURUM_TASLAK = "TASLAK"
DURUM_ONAYLANDI = "ONAYLANDI"
DURUM_IPTAL = "İPTAL EDİLDİ"
DURUMLAR = (DURUM_TASLAK, DURUM_ONAYLANDI, DURUM_IPTAL)

GM_KAYNAK = "masraf_dagitimi"
GM_KAYNAK_GERI = "masraf_dagitimi_geri"

# Maliyete otomatik uygun (normalize edilmiş parça) / otomatik uygun olmayan
UYGUN_ANAHTARLAR = ("nakl", "tasima", "yukleme", "bosaltma", "hamal", "navlun", "gumruk", "kargo")
UYGUN_OLMAYAN_ANAHTARLAR = ("teslimat", "kira")

GIRIS_TURLERI = (
    "FATURA GİRİŞ",
    "TRANSFER GİRİŞ",
    "GİRİŞ",
    "PAKET GİRİŞ",
    "SAYIM GİRİŞ",
    "İRSALİYE İADE GİRİŞ",
    "İADE GİRİŞ",
)

IKI = Decimal("0.01")
DORT = Decimal("0.0001")
SIFIR = Decimal("0")


class ZatenIslendi(ValueError):
    """Aynı işlem ikinci kez istendi (çift tıklama); ek etki yok."""


def _q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(IKI, rounding=ROUND_HALF_UP)


def _q4(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(DORT, rounding=ROUND_HALF_UP)


def _d(v, alan: str = "Değer") -> Decimal:
    if v is None or v == "":
        return SIFIR
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception as hata:  # noqa: BLE001
        raise ValueError(f"{alan} sayısal olmalıdır.") from hata


def _kullanici() -> str:
    return oturum.ad_soyad or oturum.kullanici_adi or ""


def satir_uygun_mu(kod: str | None, ad: str | None) -> bool:
    metin = turkce_normalize(f"{kod or ''} {ad or ''}")
    if any(k in metin for k in UYGUN_OLMAYAN_ANAHTARLAR):
        return False
    return any(k in metin for k in UYGUN_ANAHTARLAR)


def _agirlik_sayisi(metin) -> Decimal | None:
    import re

    if metin in (None, ""):
        return None
    eslesme = re.search(r"\d+(?:[.,]\d+)?", str(metin))
    if not eslesme:
        return None
    try:
        deger = _d(eslesme.group(0))
    except ValueError:
        return None
    return deger if deger > 0 else None


def paylari_hesapla(tutar: Decimal, bazlar: list[tuple[int, Decimal]]) -> dict[int, Decimal]:
    """tutar × baz / toplam baz; kuruş kalanı en büyük küsurata, eşitlikte küçük id'ye.

    Toplam her zaman tutara birebir eşittir.
    """
    toplam = sum((b for _k, b in bazlar), SIFIR)
    if toplam <= 0:
        raise ValueError("Dağıtım bazı sıfır; seçilen satırlarda dağıtılacak değer yok.")
    kurus = int((tutar / IKI).to_integral_value())
    ham = {k: (Decimal(kurus) * b / toplam) for k, b in bazlar}
    taban = {k: int(v) for k, v in ham.items()}
    kalan = kurus - sum(taban.values())
    sira = sorted(ham, key=lambda k: (-(ham[k] - taban[k]), k))
    for k in sira[:kalan]:
        taban[k] += 1
    return {k: Decimal(v) * IKI for k, v in taban.items()}


class MasrafDagitimService:
    _hazir_motor = None

    # ------------------------------------------------------------------ şema
    @staticmethod
    def schema_hazirla() -> None:
        from database.database import company_db
        from database.modul_sema import surum_uygula

        motor = company_db.engine
        if motor is None or MasrafDagitimService._hazir_motor is motor:
            return

        def _v1(e) -> None:
            for tablo in (
                MasrafDagitim.__table__,
                MasrafDagitimKaynakSatiri.__table__,
                MasrafDagitimSatiri.__table__,
                MasrafDagitimGecmisi.__table__,
            ):
                tablo.create(e, checkfirst=True)

        surum_uygula(motor, "masraf_dagitimi", 1, _v1)
        MasrafDagitimService._hazir_motor = motor

    @staticmethod
    def _tablo_var() -> bool:
        from database.database import company_db

        motor = company_db.engine
        if motor is None:
            return False
        try:
            return inspect(motor).has_table("masraf_dagitimlari")
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ kaynaklar
    @staticmethod
    def _kaynak_dagitilan(session, kaynak_id: int, haric_dagitim_id: int | None = None) -> dict[int, Decimal]:
        q = (
            select(MasrafDagitimKaynakSatiri.kaynak_satir_id, func.sum(MasrafDagitimKaynakSatiri.tutar))
            .join(MasrafDagitim, MasrafDagitim.id == MasrafDagitimKaynakSatiri.dagitim_id)
            .where(
                MasrafDagitim.kaynak_turu == KAYNAK_HIZMET,
                MasrafDagitim.kaynak_id == int(kaynak_id),
                MasrafDagitim.durum == DURUM_ONAYLANDI,
            )
            .group_by(MasrafDagitimKaynakSatiri.kaynak_satir_id)
        )
        if haric_dagitim_id:
            q = q.where(MasrafDagitim.id != int(haric_dagitim_id))
        return {int(k): _q2(v) for k, v in session.execute(q).all()}

    @staticmethod
    def kaynak_belgeler(arama: str | None = None, *, tumu: bool = False) -> list[dict[str, Any]]:
        """Seçilebilir gider belgeleri: iptal değil ve dağıtılabilir kalanı olan."""
        from database.models.hizmet_faturasi import HizmetFaturasi

        MasrafDagitimService.schema_hazirla()
        n_ara = turkce_normalize((arama or "").strip())
        sonuc = []
        with get_session() as session:
            faturalar = session.scalars(
                select(HizmetFaturasi)
                .options(selectinload(HizmetFaturasi.satirlar), selectinload(HizmetFaturasi.cari))
                .where(HizmetFaturasi.fatura_turu == "GIDER", HizmetFaturasi.durum != "İPTAL")
                .order_by(HizmetFaturasi.fatura_tarihi.desc(), HizmetFaturasi.id.desc())
            ).all()
            for f in faturalar:
                cari = f.cari.unvan if f.cari else ""
                if n_ara and n_ara not in turkce_normalize(f"{f.fatura_no} {cari}"):
                    continue
                dagitilan = MasrafDagitimService._kaynak_dagitilan(session, f.id)
                uygun = sum((_q2(s.tl_tutar) for s in f.satirlar if satir_uygun_mu(s.hizmet_kodu, s.hizmet_adi)), SIFIR)
                onceki = sum(dagitilan.values(), SIFIR)
                kalan = sum((_q2(s.tl_tutar) - dagitilan.get(int(s.id), SIFIR) for s in f.satirlar), SIFIR)
                if kalan <= 0 and not tumu:
                    continue
                sonuc.append(
                    {
                        "id": int(f.id),
                        "tur": KAYNAK_HIZMET,
                        "tur_etiket": KAYNAK_ETIKETLERI[KAYNAK_HIZMET],
                        "no": f.fatura_no,
                        "tarih": f.fatura_tarihi,
                        "cari": cari,
                        "cari_id": f.cari_id,
                        "para_birimi": f.para_birimi or "TRY",
                        "kur": _d(f.kur or 1),
                        "matrah": _q2(f.tl_matrah),
                        "uygun_tutar": uygun,
                        "onceki_dagitim": onceki,
                        "kalan": kalan,
                    }
                )
        return sonuc

    @staticmethod
    def kaynak_detay(kaynak_id: int, haric_dagitim_id: int | None = None) -> dict[str, Any]:
        from database.models.hizmet_faturasi import HizmetFaturasi

        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            f = session.scalar(
                select(HizmetFaturasi)
                .options(selectinload(HizmetFaturasi.satirlar), selectinload(HizmetFaturasi.cari))
                .where(HizmetFaturasi.id == int(kaynak_id))
            )
            if f is None:
                raise ValueError("Gider belgesi bulunamadı.")
            dagitilan = MasrafDagitimService._kaynak_dagitilan(session, f.id, haric_dagitim_id)
            satirlar = []
            for s in sorted(f.satirlar, key=lambda x: int(x.id)):
                tutar = _q2(s.tl_tutar)
                d = dagitilan.get(int(s.id), SIFIR)
                satirlar.append(
                    {
                        "id": int(s.id),
                        "kod": s.hizmet_kodu,
                        "ad": s.hizmet_adi,
                        "tutar": tutar,
                        "kdv_orani": _d(s.kdv_orani),
                        "dagitilan": d,
                        "kalan": tutar - d,
                        "uygun": satir_uygun_mu(s.hizmet_kodu, s.hizmet_adi),
                    }
                )
            return {
                "id": int(f.id),
                "no": f.fatura_no,
                "tarih": f.fatura_tarihi,
                "cari": f.cari.unvan if f.cari else "",
                "cari_id": f.cari_id,
                "durum": f.durum,
                "para_birimi": f.para_birimi or "TRY",
                "kur": _d(f.kur or 1),
                "satirlar": satirlar,
            }

    # --------------------------------------------------------------- hedefler
    @staticmethod
    def _lot_bul(session, satir, fatura):
        from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu

        if not satir.lot_girisi:
            return None, None, None
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == satir.urun_kodu))
        if stok is None:
            return None, None, None
        q = select(StokLotu).where(StokLotu.stok_id == stok.id, StokLotu.lot_no == satir.lot_girisi)
        depo = session.scalar(select(Depo).where(Depo.ad == (fatura.depo or "ANA DEPO")))
        if depo is not None:
            q = q.where(StokLotu.depo_id == depo.id)
        lot = session.scalar(q.order_by(StokLotu.id))
        if lot is None:
            return stok, None, None
        giris = session.scalar(
            select(StokHareketi)
            .where(
                StokHareketi.lot_id == lot.id,
                StokHareketi.hareket_turu == "FATURA GİRİŞ",
                StokHareketi.belge_no == fatura.fatura_no,
            )
            .order_by(StokHareketi.id)
        )
        return stok, lot, giris

    @staticmethod
    def hedef_satirlar(arama: str | None = None, *, limit: int = 400) -> list[dict[str, Any]]:
        """Masraf yüklenebilecek alış faturası satırları (iptal değil, FIFO lotu olan)."""
        from database.models.alis_faturasi import AlisFaturasi

        MasrafDagitimService.schema_hazirla()
        n_ara = turkce_normalize((arama or "").strip())
        sonuc: list[dict[str, Any]] = []
        with get_session() as session:
            faturalar = session.scalars(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar), selectinload(AlisFaturasi.cari))
                .where(AlisFaturasi.durum != "İPTAL")
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc())
            ).all()
            dagitilan = MasrafDagitimService._hedef_dagitilan(session)
            for f in faturalar:
                ted = f.cari.unvan if f.cari else ""
                for s in sorted(f.satirlar, key=lambda x: int(x.id)):
                    if n_ara and n_ara not in turkce_normalize(
                        f"{f.fatura_no} {ted} {s.urun_kodu} {s.urun_adi}"
                    ):
                        continue
                    stok, lot, giris = MasrafDagitimService._lot_bul(session, s, f)
                    if lot is None:
                        continue
                    sonuc.append(
                        {
                            "satir_id": int(s.id),
                            "fatura_id": int(f.id),
                            "fatura_no": f.fatura_no,
                            "tarih": f.fatura_tarihi,
                            "tedarikci": ted,
                            "urun_kodu": s.urun_kodu,
                            "urun_adi": s.urun_adi,
                            "depo": f.depo or "",
                            "birim": (stok.birim if stok else None) or s.birim,
                            "ana_miktar": _d(giris.miktar if giris else s.miktar),
                            "alis_tutari": _q2(s.tl_tutar),
                            "birim_maliyet": _q4(lot.birim_maliyet),
                            "kalan": _d(lot.kalan_miktar),
                            "dagitilan": dagitilan.get(int(s.id), SIFIR),
                            "agirlik": _agirlik_sayisi(getattr(stok, "agirlik", None)) if stok else None,
                        }
                    )
                    if len(sonuc) >= limit:
                        return sonuc
        return sonuc

    @staticmethod
    def _hedef_dagitilan(session) -> dict[int, Decimal]:
        rows = session.execute(
            select(MasrafDagitimSatiri.alis_fatura_satiri_id, func.sum(MasrafDagitimSatiri.pay))
            .join(MasrafDagitim, MasrafDagitim.id == MasrafDagitimSatiri.dagitim_id)
            .where(MasrafDagitim.durum == DURUM_ONAYLANDI)
            .group_by(MasrafDagitimSatiri.alis_fatura_satiri_id)
        ).all()
        return {int(k): _q2(v) for k, v in rows}

    # ------------------------------------------------------------- FIFO izi
    @staticmethod
    def _alis_iade_nolari(session) -> set[str]:
        from database.models.alis_iade_faturasi import AlisIadeFaturasi

        try:
            return {n for n in session.scalars(select(AlisIadeFaturasi.iade_no)).all() if n}
        except OperationalError:
            return set()

    @staticmethod
    def _lot_izi(session, lot_id: int, carpan: Decimal, iade_nolari: set[str], lotlar: dict[int, Decimal],
                 uyarilar: list[str], derinlik: int = 0, ziyaret: frozenset = frozenset()) -> tuple[Decimal, Decimal]:
        """Lot ve transferle devam ettiği lotlarda (stokta kalan, iade edilen) miktar eşdeğeri.

        ``carpan``: bu lotun bir biriminin taşıdığı pay / kök katman birim payı.
        ``lotlar``: etkilenen lot → toplam çarpan.
        """
        from database.models.stok import StokHareketi, StokLotu

        if derinlik > 25 or lot_id in ziyaret:
            uyarilar.append("Transfer zinciri çok derin veya döngüsel; kalan kısım SMM sayıldı.")
            return SIFIR, SIFIR
        lot = session.get(StokLotu, int(lot_id))
        if lot is None:
            return SIFIR, SIFIR
        lotlar[int(lot.id)] = lotlar.get(int(lot.id), SIFIR) + carpan
        stok_eq = _d(lot.kalan_miktar) * carpan
        iade_eq = SIFIR
        hareketler = session.scalars(
            select(StokHareketi).where(StokHareketi.lot_id == lot.id).order_by(StokHareketi.id)
        ).all()
        for h in hareketler:
            if h.hareket_turu == "FATURA ÇIKIŞ" and h.belge_no in iade_nolari:
                iade_eq += _d(h.miktar) * carpan
            elif h.hareket_turu == "TRANSFER ÇIKIŞ":
                hedefler = session.scalars(
                    select(StokHareketi).where(
                        StokHareketi.belge_no == h.belge_no,
                        StokHareketi.stok_id == h.stok_id,
                        StokHareketi.hareket_turu == "TRANSFER GİRİŞ",
                    )
                ).all()
                toplam = sum((_d(x.miktar) for x in hedefler), SIFIR)
                if not hedefler or toplam <= 0:
                    uyarilar.append(f"{h.belge_no} transferinin giriş hareketi bulunamadı; SMM sayıldı.")
                    continue
                alt_carpan = carpan * _d(h.miktar) / toplam
                for x in hedefler:
                    if x.lot_id:
                        s_eq, i_eq = MasrafDagitimService._lot_izi(
                            session, int(x.lot_id), alt_carpan, iade_nolari, lotlar, uyarilar,
                            derinlik + 1, ziyaret | {int(lot.id)},
                        )
                        stok_eq += s_eq
                        iade_eq += i_eq
        return stok_eq, iade_eq

    # ------------------------------------------------------------- hesaplama
    @staticmethod
    def _kapali_donem_mi(session, tarih: date) -> bool:
        from database.models.donem import Donem

        try:
            return bool(
                session.scalar(
                    select(func.count()).select_from(Donem).where(
                        Donem.kapali.is_(True),
                        Donem.baslangic_tarihi <= tarih,
                        Donem.bitis_tarihi >= tarih,
                    )
                )
            )
        except OperationalError:
            return False

    @staticmethod
    def _gm_aktif(session, kaynak_id: int | None) -> bool:
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeHesapEsleme

        try:
            if session.scalar(
                select(func.count()).select_from(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.hesap_id.is_not(None))
            ):
                return True
            if kaynak_id and session.scalar(
                select(func.count()).select_from(MuhasebeFisi).where(
                    MuhasebeFisi.kaynak_turu == "hizmet_faturasi",
                    MuhasebeFisi.kaynak_id == int(kaynak_id),
                    MuhasebeFisi.durum != "İptal",
                )
            ):
                return True
        except OperationalError:
            return False
        return False

    @staticmethod
    def _gm_hesap(session, anahtar: str):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme
        from database.muhasebe_service import MuhasebeService

        firma_id = MuhasebeService.yerel_firma_id(session)
        e = session.scalar(
            select(MuhasebeHesapEsleme).where(
                MuhasebeHesapEsleme.firma_id == firma_id,
                MuhasebeHesapEsleme.anahtar == anahtar,
                MuhasebeHesapEsleme.aktif.is_(True),
            )
        )
        if e is None or not e.hesap_id:
            return None
        h = session.get(HesapPlani, e.hesap_id)
        if h is None or not h.aktif or h.firma_id != firma_id:
            return None
        return h

    @staticmethod
    def _gm_engelleri(session, kaynak_id: int, stok: Decimal, smm: Decimal) -> list[str]:
        from database.models.genel_muhasebe import ESLEME_ANAHTARLARI
        from database.tdhp_hesap_plani import fis_icin_alt_hesap_mi

        if not MasrafDagitimService._gm_aktif(session, kaynak_id):
            return []
        adlar = dict(ESLEME_ANAHTARLARI)
        gerekli = ["giderler"]
        if stok > 0:
            gerekli.append("ticari_mallar")
        if smm > 0:
            gerekli.append("satilan_mal_maliyeti")
        engel = []
        for anahtar in gerekli:
            h = MasrafDagitimService._gm_hesap(session, anahtar)
            if h is None:
                engel.append(f"Hesap eşleştirmesi eksik: {adlar.get(anahtar, anahtar)} ({anahtar})")
            elif not fis_icin_alt_hesap_mi(h.hesap_kodu):
                engel.append(f"Eşleştirilen hesap alt hesap değil: {h.hesap_kodu} ({anahtar})")
        return engel

    @staticmethod
    def _hesapla(session, veri: dict[str, Any], haric_dagitim_id: int | None = None) -> dict[str, Any]:
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.hizmet_faturasi import HizmetFaturasi

        tarih = veri.get("dagitim_tarihi") or date.today()
        if isinstance(tarih, datetime):
            tarih = tarih.date()
        if tarih > date.today():
            raise ValueError("Dağıtım tarihi gelecek bir tarih olamaz.")
        if MasrafDagitimService._kapali_donem_mi(session, tarih):
            raise ValueError("Dağıtım tarihi kapalı bir döneme düşüyor; kapalı döneme maliyet aktarılamaz.")
        yontem = (veri.get("yontem") or "TUTAR").upper()
        if yontem not in YONTEMLER:
            raise ValueError("Geçersiz dağıtım yöntemi.")
        tutar = _q2(_d(veri.get("tutar"), "Dağıtım tutarı"))
        if tutar <= 0:
            raise ValueError("Dağıtım tutarı sıfırdan büyük olmalıdır.")

        kaynak = session.scalar(
            select(HizmetFaturasi)
            .options(selectinload(HizmetFaturasi.satirlar))
            .where(HizmetFaturasi.id == int(veri.get("kaynak_id") or 0))
        )
        if kaynak is None:
            raise ValueError("Kaynak gider belgesi bulunamadı.")
        if (kaynak.fatura_turu or "").upper() != "GIDER":
            raise ValueError("Kaynak belge gider (hizmet alış) faturası olmalıdır.")
        if kaynak.durum == "İPTAL":
            raise ValueError("İptal edilmiş gider belgesi dağıtılamaz.")
        secili = [int(x) for x in (veri.get("kaynak_satir_idler") or [])]
        kaynak_satirlari = {int(s.id): s for s in kaynak.satirlar}
        if not secili:
            raise ValueError("Dağıtılacak gider satırı seçin.")
        for sid in secili:
            if sid not in kaynak_satirlari:
                raise ValueError("Seçilen gider satırı bu belgeye ait değil.")
        dagitilan = MasrafDagitimService._kaynak_dagitilan(session, kaynak.id, haric_dagitim_id)
        kalanlar = {sid: _q2(kaynak_satirlari[sid].tl_tutar) - dagitilan.get(sid, SIFIR) for sid in secili}
        secili_kalan = sum(kalanlar.values(), SIFIR)
        if tutar > secili_kalan:
            raise ValueError(
                f"Dağıtım tutarı kaynak belgenin kalan tutarını aşamaz. "
                f"Kalan: {secili_kalan:.2f} TL, istenen: {tutar:.2f} TL."
            )
        kaynak_paylari: list[dict[str, Any]] = []
        acik = tutar
        for sid in sorted(secili):
            if acik <= 0:
                break
            pay = min(acik, kalanlar[sid])
            if pay <= 0:
                continue
            s = kaynak_satirlari[sid]
            kaynak_paylari.append({"kaynak_satir_id": sid, "aciklama": f"{s.hizmet_kodu} {s.hizmet_adi}", "tutar": pay})
            acik -= pay

        hedefler = veri.get("hedefler") or []
        if not hedefler:
            raise ValueError("En az bir alış satırı seçin.")
        gorulen: set[int] = set()
        iade_nolari = MasrafDagitimService._alis_iade_nolari(session)
        satirlar: list[dict[str, Any]] = []
        eksik_olcu: list[str] = []
        uyarilar: list[str] = []
        for h in hedefler:
            sid = int(h.get("satir_id") or 0)
            if sid in gorulen:
                raise ValueError("Aynı alış satırı iki kez seçilemez.")
            gorulen.add(sid)
            satir = session.get(AlisFaturasiSatiri, sid)
            fatura = session.get(AlisFaturasi, int(satir.fatura_id)) if satir else None
            if satir is None or fatura is None:
                raise ValueError("Seçilen alış satırı bulunamadı; fatura değişmiş olabilir.")
            if fatura.durum == "İPTAL":
                raise ValueError(f"{fatura.fatura_no} iptal edilmiş; masraf yüklenemez.")
            stok, lot, giris = MasrafDagitimService._lot_bul(session, satir, fatura)
            if lot is None:
                raise ValueError(f"{fatura.fatura_no} / {satir.urun_kodu} satırının stok katmanı (lot) bulunamadı.")
            ana_miktar = _d(giris.miktar if giris else satir.miktar)
            if ana_miktar <= 0:
                raise ValueError(f"{satir.urun_kodu} satırının ana birim miktarı sıfır.")
            olcu = None
            if yontem in ("AGIRLIK", "HACIM"):
                olcu = _d(h.get("olcu"), "Ölçü") if h.get("olcu") not in (None, "") else None
                if olcu is None and yontem == "AGIRLIK":
                    olcu = _agirlik_sayisi(getattr(stok, "agirlik", None))
                if olcu is None or olcu <= 0:
                    eksik_olcu.append(f"{satir.urun_kodu} {satir.urun_adi}")
            elle = None
            if yontem == "ELLE":
                elle = _q2(_d(h.get("elle_tutar"), "Elle tutar"))
                if elle < 0:
                    raise ValueError("Elle dağıtım tutarı negatif olamaz.")
            satirlar.append(
                {
                    "alis_fatura_id": int(fatura.id),
                    "alis_fatura_satiri_id": sid,
                    "alis_fatura_no": fatura.fatura_no,
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "depo": fatura.depo or "",
                    "birim": (stok.birim if stok else None) or satir.birim,
                    "lot_id": int(lot.id),
                    "ana_miktar": ana_miktar,
                    "alis_tutari": _q2(satir.tl_tutar),
                    "olcu": olcu,
                    "elle_tutar": elle,
                    "eski_birim_maliyet": _q4(lot.birim_maliyet),
                    "_lot_kalan": _d(lot.kalan_miktar),
                }
            )
        if eksik_olcu:
            ad = "Ağırlık" if yontem == "AGIRLIK" else "Hacim"
            raise ValueError(f"{ad} verisi eksik veya sıfır olan satırlar var:\n- " + "\n- ".join(eksik_olcu))

        if yontem == "MIKTAR":
            birimler = {(s["birim"] or "").casefold() for s in satirlar}
            if len(birimler) > 1:
                raise ValueError(
                    "Farklı ana birimli ürünler miktar yöntemiyle karıştırılamaz ("
                    + ", ".join(sorted({s["birim"] or "" for s in satirlar}))
                    + "). Tutar, ağırlık veya elle dağıtım seçin."
                )
        if yontem == "ELLE":
            elle_toplam = sum((s["elle_tutar"] for s in satirlar), SIFIR)
            if elle_toplam != tutar:
                raise ValueError(
                    f"Elle dağıtım toplamı ({elle_toplam:.2f}) dağıtım tutarına ({tutar:.2f}) eşit olmalıdır."
                )
            for s in satirlar:
                s["baz"] = s["elle_tutar"]
                s["pay"] = s["elle_tutar"]
        else:
            for s in satirlar:
                if yontem == "TUTAR":
                    s["baz"] = s["alis_tutari"]
                elif yontem == "MIKTAR":
                    s["baz"] = s["ana_miktar"]
                else:
                    s["baz"] = s["olcu"] * s["ana_miktar"]
            paylar = paylari_hesapla(tutar, [(s["alis_fatura_satiri_id"], s["baz"]) for s in satirlar])
            for s in satirlar:
                s["pay"] = paylar[s["alis_fatura_satiri_id"]]

        stok_top = smm_top = iade_top = SIFIR
        for s in satirlar:
            lotlar: dict[int, Decimal] = {}
            stok_eq, iade_eq = MasrafDagitimService._lot_izi(
                session, s["lot_id"], Decimal("1"), iade_nolari, lotlar, uyarilar
            )
            q = s["ana_miktar"]
            s["stok_payi"] = _q2(s["pay"] * stok_eq / q)
            s["iade_payi"] = _q2(s["pay"] * iade_eq / q)
            s["smm_payi"] = s["pay"] - s["stok_payi"] - s["iade_payi"]
            s["ek_birim"] = s["pay"] / q
            s["yeni_birim_maliyet"] = _q4(s["eski_birim_maliyet"] + s["ek_birim"])
            s["_lotlar"] = lotlar
            stok_top += s["stok_payi"]
            smm_top += s["smm_payi"]
            iade_top += s["iade_payi"]

        engeller = MasrafDagitimService._gm_engelleri(session, kaynak.id, stok_top, smm_top)
        imza_verisi = {
            "tarih": tarih.isoformat(),
            "kaynak": [int(kaynak.id), str(kaynak.durum), str(_q2(kaynak.tl_matrah))],
            "kaynak_paylari": [[p["kaynak_satir_id"], str(p["tutar"]), str(kalanlar[p["kaynak_satir_id"]])] for p in kaynak_paylari],
            "tutar": str(tutar),
            "yontem": yontem,
            "hedef": [
                [s["alis_fatura_satiri_id"], str(s["alis_tutari"]), str(s["ana_miktar"]), str(s["_lot_kalan"]),
                 str(s["eski_birim_maliyet"]), str(s["olcu"]), str(s["elle_tutar"]), str(s["pay"]),
                 str(s["stok_payi"]), str(s["iade_payi"])]
                for s in satirlar
            ],
        }
        imza = hashlib.sha256(json.dumps(imza_verisi, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "dagitim_tarihi": tarih,
            "kaynak_id": int(kaynak.id),
            "kaynak_no": kaynak.fatura_no,
            "kaynak_cari_id": kaynak.cari_id,
            "para_birimi": kaynak.para_birimi or "TRY",
            "kur": _d(kaynak.kur or 1),
            "kaynak_kalan": secili_kalan,
            "kaynak_paylari": kaynak_paylari,
            "yontem": yontem,
            "tutar": tutar,
            "satirlar": satirlar,
            "stok_payi": stok_top,
            "smm_payi": smm_top,
            "iade_payi": iade_top,
            "engeller": engeller,
            "uyarilar": sorted(set(uyarilar)),
            "imza": imza,
        }

    @staticmethod
    def _disa_ver(sonuc: dict[str, Any]) -> dict[str, Any]:
        temiz = dict(sonuc)
        temiz["satirlar"] = [{k: v for k, v in s.items() if not k.startswith("_")} for s in sonuc["satirlar"]]
        return temiz

    @staticmethod
    def onizle(veri: dict[str, Any], haric_dagitim_id: int | None = None) -> dict[str, Any]:
        """Stok/GM'ye dokunmadan dağıtım sonucunu hesaplar."""
        yetki_zorunlu("alis_masraf_goruntuleme", "alis_masraf_duzenleme", "alis_masraf_onay")
        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            sonuc = MasrafDagitimService._hesapla(session, veri, haric_dagitim_id)
            return MasrafDagitimService._disa_ver(sonuc)

    # ---------------------------------------------------------------- taslak
    @staticmethod
    def _sonraki_no(session) -> str:
        son = session.scalar(
            select(MasrafDagitim.dagitim_no)
            .where(MasrafDagitim.dagitim_no.like("MD%"))
            .order_by(MasrafDagitim.dagitim_no.desc())
        )
        try:
            sira = int(str(son)[2:]) + 1 if son else 1
        except ValueError:
            sira = 1
        return f"MD{sira:06d}"

    @staticmethod
    def _gecmis(session, dagitim_id: int, islem: str, detay: str | None = None) -> None:
        session.add(MasrafDagitimGecmisi(dagitim_id=int(dagitim_id), islem=islem, detay=detay, kullanici=_kullanici()))

    @staticmethod
    def taslak_kaydet(veri: dict[str, Any], dagitim_id: int | None = None, beklenen_versiyon: int | None = None) -> int:
        """Önizlemeyi taslak olarak saklar; stok ve muhasebe değişmez."""
        yazma_zorunlu("alis_masraf_duzenleme", "alis_masraf_onay")
        MasrafDagitimService.schema_hazirla()
        for deneme in range(3):
            try:
                with get_session() as session:
                    sonuc = MasrafDagitimService._hesapla(session, veri, dagitim_id)
                    if dagitim_id:
                        d = session.get(MasrafDagitim, int(dagitim_id))
                        if d is None:
                            raise ValueError("Masraf dağıtımı bulunamadı.")
                        if d.durum != DURUM_TASLAK:
                            raise ValueError("Yalnızca taslak dağıtım değiştirilebilir; onaylı kayıt için geri alma kullanın.")
                        if beklenen_versiyon is not None and int(beklenen_versiyon) != int(d.row_version or 1):
                            raise ValueError("Dağıtım başka bir kullanıcı tarafından değiştirilmiş; yeniden açın.")
                        d.kaynak_satirlari.clear()
                        d.satirlar.clear()
                        d.row_version = int(d.row_version or 1) + 1
                        d.guncelleme_tarihi = datetime.now()
                        islem = "TASLAK GÜNCELLE"
                    else:
                        d = MasrafDagitim(
                            dagitim_no=MasrafDagitimService._sonraki_no(session),
                            durum=DURUM_TASLAK,
                            row_version=1,
                            olusturan=_kullanici(),
                        )
                        session.add(d)
                        islem = "TASLAK OLUŞTUR"
                    d.dagitim_tarihi = sonuc["dagitim_tarihi"]
                    d.kaynak_turu = KAYNAK_HIZMET
                    d.kaynak_id = sonuc["kaynak_id"]
                    d.kaynak_no = sonuc["kaynak_no"]
                    d.kaynak_cari_id = sonuc["kaynak_cari_id"]
                    d.yontem = sonuc["yontem"]
                    d.tutar = sonuc["tutar"]
                    d.para_birimi = sonuc["para_birimi"]
                    d.kur = sonuc["kur"]
                    d.aciklama = (veri.get("aciklama") or "").strip() or None
                    d.onizleme_imza = sonuc["imza"]
                    d.stok_payi = sonuc["stok_payi"]
                    d.smm_payi = sonuc["smm_payi"]
                    d.iade_payi = sonuc["iade_payi"]
                    for p in sonuc["kaynak_paylari"]:
                        d.kaynak_satirlari.append(MasrafDagitimKaynakSatiri(**p))
                    for s in sonuc["satirlar"]:
                        d.satirlar.append(MasrafDagitimSatiri(**MasrafDagitimService._satir_kolonlari(s)))
                    session.flush()
                    MasrafDagitimService._gecmis(session, d.id, islem, f"{sonuc['tutar']:.2f} TL / {sonuc['yontem']}")
                    return int(d.id)
            except IntegrityError:
                if deneme == 2 or dagitim_id:
                    raise ValueError("Dağıtım numarası alınamadı; tekrar deneyin.")
        raise ValueError("Dağıtım kaydedilemedi.")

    @staticmethod
    def _satir_kolonlari(s: dict[str, Any]) -> dict[str, Any]:
        alanlar = (
            "alis_fatura_id", "alis_fatura_satiri_id", "alis_fatura_no", "urun_kodu", "urun_adi", "depo", "birim",
            "lot_id", "ana_miktar", "alis_tutari", "olcu", "elle_tutar", "baz", "pay", "eski_birim_maliyet",
            "yeni_birim_maliyet", "stok_payi", "smm_payi", "iade_payi",
        )
        return {k: s.get(k) for k in alanlar}

    @staticmethod
    def _veri_dagitimdan(d: MasrafDagitim) -> dict[str, Any]:
        return {
            "dagitim_tarihi": d.dagitim_tarihi,
            "kaynak_id": d.kaynak_id,
            "kaynak_satir_idler": [k.kaynak_satir_id for k in d.kaynak_satirlari],
            "tutar": d.tutar,
            "yontem": d.yontem,
            "aciklama": d.aciklama,
            "hedefler": [
                {"satir_id": s.alis_fatura_satiri_id, "olcu": s.olcu, "elle_tutar": s.elle_tutar} for s in d.satirlar
            ],
        }

    # ------------------------------------------------------------ uygulama
    @staticmethod
    def _satis_satirlari_guncelle(session, lot, e_lot: Decimal, uyarilar: list[str]) -> int:
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.models.stok import StokKarti

        stok = session.get(StokKarti, lot.stok_id)
        if stok is None or not lot.lot_no:
            return 0
        adet = 0
        adaylar = session.scalars(
            select(SatisFaturasiSatiri).where(
                SatisFaturasiSatiri.urun_kodu == stok.stok_kodu,
                SatisFaturasiSatiri.lot_cikisi.like(f"%{lot.lot_no}%"),
            )
        ).all()
        for satir in adaylar:
            fatura = session.get(SatisFaturasi, satir.fatura_id)
            if fatura is None or fatura.durum == "İPTAL":
                continue
            from database.models.stok import Depo

            depo = session.scalar(select(Depo).where(Depo.ad == (fatura.depo or "ANA DEPO")))
            if depo is not None and depo.id != lot.depo_id:
                continue
            parcalar = []
            for parca in (satir.lot_cikisi or "").split(","):
                if ":" not in parca:
                    continue
                ad, mik = parca.strip().rsplit(":", 1)
                try:
                    parcalar.append((ad.strip(), Decimal(mik.strip())))
                except Exception:  # noqa: BLE001
                    continue
            toplam = sum((m for _a, m in parcalar), SIFIR)
            bu_lot = sum((m for a, m in parcalar if a == lot.lot_no), SIFIR)
            if toplam <= 0 or bu_lot <= 0:
                continue
            if MasrafDagitimService._kapali_donem_mi(session, fatura.fatura_tarihi):
                uyarilar.append(
                    f"{fatura.fatura_no} kapalı dönemde; satış satırı maliyeti değiştirilmedi (SMM fişle düzeltildi)."
                )
                continue
            eski = _d(satir.fifo_birim_maliyeti)
            satir.fifo_birim_maliyeti = max(SIFIR, _q4(eski + e_lot * bu_lot / toplam))
            adet += 1
        return adet

    @staticmethod
    def _etkileri_uygula(session, satirlar: list[dict[str, Any]], isaret: int, uyarilar: list[str]) -> dict[str, int]:
        """Lot, hareket, alış satırı ve satış satırı birim maliyetlerine payı ekler/çıkarır."""
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.stok import StokHareketi, StokLotu

        sayac = {"lot": 0, "hareket": 0, "satis_satiri": 0}
        yon = Decimal(isaret)
        for s in satirlar:
            e_kok = s["pay"] / s["ana_miktar"]
            for lot_id, carpan in s["_lotlar"].items():
                lot = session.get(StokLotu, int(lot_id))
                if lot is None:
                    continue
                e_lot = _q4(e_kok * carpan) * yon
                if e_lot == 0:
                    continue
                lot.birim_maliyet = max(SIFIR, _q4(_d(lot.birim_maliyet) + e_lot))
                sayac["lot"] += 1
                for h in session.scalars(select(StokHareketi).where(StokHareketi.lot_id == lot.id)).all():
                    h.birim_maliyet = max(SIFIR, _q4(_d(h.birim_maliyet) + e_lot))
                    sayac["hareket"] += 1
                sayac["satis_satiri"] += MasrafDagitimService._satis_satirlari_guncelle(session, lot, e_lot, uyarilar)
            alis = session.get(AlisFaturasiSatiri, int(s["alis_fatura_satiri_id"]))
            if alis is not None:
                alis.fifo_birim_maliyeti = max(SIFIR, _q4(_d(alis.fifo_birim_maliyeti) + _q4(e_kok) * yon))
        return sayac

    @staticmethod
    def _gm_fisi_yaz(session, d: MasrafDagitim, kalemler: list[tuple[str, Decimal, Decimal, str]],
                     kaynak_turu: str, tarih: date, aciklama: str) -> int | None:
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri
        from database.muhasebe_service import MuhasebeFisService, MuhasebeService

        temiz = [(a, _q2(b), _q2(al), ac) for a, b, al, ac in kalemler if _q2(b) or _q2(al)]
        if not temiz:
            return None
        toplam_borc = sum((b for _a, b, _al, _ac in temiz), SIFIR)
        toplam_alacak = sum((al for _a, _b, al, _ac in temiz), SIFIR)
        if toplam_borc != toplam_alacak:
            raise ValueError("Muhasebe fişi dengesiz; dağıtım onaylanamadı.")
        firma_id = MuhasebeService.yerel_firma_id(session)
        fis = MuhasebeFisi(
            firma_id=firma_id,
            donem_id=oturum.period_id,
            mali_yil=tarih.year,
            fis_no=MuhasebeFisService._sonraki_fis_no(session, firma_id, tarih.year),
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=aciklama,
            belge_no=d.dagitim_no,
            durum="Kesinleşmiş",
            toplam_borc=toplam_borc,
            toplam_alacak=toplam_alacak,
            kaynak_turu=kaynak_turu,
            kaynak_id=int(d.id),
            olusturan_kullanici_id=oturum.user_id,
        )
        session.add(fis)
        session.flush()
        for sira, (anahtar, borc, alacak, ack) in enumerate(temiz, start=1):
            h = MasrafDagitimService._gm_hesap(session, anahtar)
            if h is None:
                raise ValueError(f"Hesap eşleştirmesi eksik: {anahtar}")
            session.add(
                MuhasebeFisiSatiri(
                    fis_id=fis.id, firma_id=firma_id, sira_no=sira, hesap_id=h.id, hesap_kodu=h.hesap_kodu,
                    hesap_adi=h.hesap_adi, aciklama=ack, borc=borc, alacak=alacak, belge_tarihi=tarih,
                    belge_no=d.dagitim_no,
                )
            )
        session.flush()
        MuhasebeFisService._bakiye_uygula(session, fis.id, yon=1)
        MuhasebeService._gecmis(session, kayit_turu="fis", kayit_id=fis.id, islem="olustur", detay=f"{fis.fis_no} / {aciklama}")
        return int(fis.id)

    @staticmethod
    def onayla(dagitim_id: int, beklenen_versiyon: int | None = None) -> dict[str, Any]:
        """Taslağı yeniden doğrular, maliyetleri ve GM fişini tek transaction'da uygular."""
        yazma_zorunlu("alis_masraf_onay")
        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            q = update(MasrafDagitim).where(MasrafDagitim.id == int(dagitim_id), MasrafDagitim.durum == DURUM_TASLAK)
            if beklenen_versiyon is not None:
                q = q.where(MasrafDagitim.row_version == int(beklenen_versiyon))
            sonuc_upd = session.execute(
                q.values(row_version=MasrafDagitim.row_version + 1, guncelleme_tarihi=datetime.now())
                .execution_options(synchronize_session=False)
            )
            d = session.get(MasrafDagitim, int(dagitim_id))
            if d is None:
                raise ValueError("Masraf dağıtımı bulunamadı.")
            if sonuc_upd.rowcount != 1:
                if d.durum == DURUM_ONAYLANDI:
                    raise ZatenIslendi(f"{d.dagitim_no} zaten onaylanmış; tekrar uygulanmadı.")
                if d.durum == DURUM_IPTAL:
                    raise ValueError(f"{d.dagitim_no} iptal edilmiş; onaylanamaz.")
                raise ValueError("Dağıtım başka bir kullanıcı tarafından değiştirilmiş; yeniden açın.")
            session.refresh(d)
            veri = MasrafDagitimService._veri_dagitimdan(d)
            sonuc = MasrafDagitimService._hesapla(session, veri, d.id)
            if sonuc["imza"] != d.onizleme_imza:
                raise ValueError(
                    "Önizleme artık geçerli değil: kaynak belge, alış satırları veya stok hareketleri değişmiş. "
                    "Yeniden önizleyip taslağı kaydedin."
                )
            if sonuc["engeller"]:
                raise ValueError("Onay engellendi:\n- " + "\n- ".join(sonuc["engeller"]))
            uyarilar = list(sonuc["uyarilar"])
            sayac = MasrafDagitimService._etkileri_uygula(session, sonuc["satirlar"], +1, uyarilar)
            for kayit, s in zip(sorted(d.satirlar, key=lambda x: x.id), sonuc["satirlar"]):
                for k, v in MasrafDagitimService._satir_kolonlari(s).items():
                    setattr(kayit, k, v)
            d.stok_payi, d.smm_payi, d.iade_payi = sonuc["stok_payi"], sonuc["smm_payi"], sonuc["iade_payi"]
            if MasrafDagitimService._gm_aktif(session, d.kaynak_id):
                aktarilan = sonuc["stok_payi"] + sonuc["smm_payi"]
                d.fis_id = MasrafDagitimService._gm_fisi_yaz(
                    session,
                    d,
                    [
                        ("ticari_mallar", sonuc["stok_payi"], SIFIR, f"Masraf dağıtımı stok payı {d.kaynak_no}"),
                        ("satilan_mal_maliyeti", sonuc["smm_payi"], SIFIR, f"Masraf dağıtımı SMM payı {d.kaynak_no}"),
                        ("giderler", SIFIR, aktarilan, f"Maliyete aktarılan gider {d.kaynak_no}"),
                    ],
                    GM_KAYNAK,
                    d.dagitim_tarihi,
                    f"Masraf dağıtımı {d.dagitim_no} ({d.kaynak_no})",
                )
            else:
                uyarilar.append("Genel muhasebe kullanılmıyor (hesap eşleştirmesi yok); muhasebe fişi oluşturulmadı.")
            d.durum = DURUM_ONAYLANDI
            d.onaylayan = _kullanici()
            d.onay_tarihi = datetime.now()
            MasrafDagitimService._gecmis(
                session, d.id, "ONAY",
                f"stok={sonuc['stok_payi']} smm={sonuc['smm_payi']} iade={sonuc['iade_payi']} "
                f"lot={sayac['lot']} hareket={sayac['hareket']} satis_satiri={sayac['satis_satiri']} fis={d.fis_id}",
            )
            session.flush()
            return {
                "id": int(d.id),
                "dagitim_no": d.dagitim_no,
                "stok_payi": sonuc["stok_payi"],
                "smm_payi": sonuc["smm_payi"],
                "iade_payi": sonuc["iade_payi"],
                "fis_id": d.fis_id,
                "uyarilar": sorted(set(uyarilar)),
            }

    @staticmethod
    def geri_al(dagitim_id: int, neden: str) -> bool:
        """Onaylı dağıtımın maliyet ve GM etkisini ters çevirir. İkinci çağrı etkisizdir (False)."""
        yazma_zorunlu("alis_masraf_geri_al")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Geri alma nedeni zorunludur.")
        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            sonuc_upd = session.execute(
                update(MasrafDagitim)
                .where(MasrafDagitim.id == int(dagitim_id), MasrafDagitim.durum == DURUM_ONAYLANDI)
                .values(durum=DURUM_IPTAL, row_version=MasrafDagitim.row_version + 1)
                .execution_options(synchronize_session=False)
            )
            d = session.get(MasrafDagitim, int(dagitim_id))
            if d is None:
                raise ValueError("Masraf dağıtımı bulunamadı.")
            if sonuc_upd.rowcount != 1:
                if d.durum == DURUM_IPTAL:
                    return False
                raise ValueError("Yalnızca onaylı dağıtım geri alınabilir; taslak için İptal kullanın.")
            session.refresh(d)
            bugun = date.today()
            if MasrafDagitimService._kapali_donem_mi(session, bugun):
                raise ValueError("Bugünün tarihi kapalı döneme düşüyor; geri alma yapılamaz.")
            iade_nolari = MasrafDagitimService._alis_iade_nolari(session)
            uyarilar: list[str] = []
            satirlar = []
            stok_simdi = SIFIR
            for kayit in d.satirlar:
                lotlar: dict[int, Decimal] = {}
                stok_eq = SIFIR
                if kayit.lot_id:
                    stok_eq, _i = MasrafDagitimService._lot_izi(
                        session, int(kayit.lot_id), Decimal("1"), iade_nolari, lotlar, uyarilar
                    )
                stok_simdi += _q2(_d(kayit.pay) * stok_eq / _d(kayit.ana_miktar))
                satirlar.append(
                    {
                        "alis_fatura_satiri_id": kayit.alis_fatura_satiri_id,
                        "pay": _d(kayit.pay),
                        "ana_miktar": _d(kayit.ana_miktar),
                        "_lotlar": lotlar,
                    }
                )
            sayac = MasrafDagitimService._etkileri_uygula(session, satirlar, -1, uyarilar)
            if d.fis_id:
                aktarilan = _d(d.stok_payi) + _d(d.smm_payi)
                stok_simdi = min(stok_simdi, aktarilan)
                d.ters_fis_id = MasrafDagitimService._gm_fisi_yaz(
                    session,
                    d,
                    [
                        ("giderler", aktarilan, SIFIR, f"Masraf dağıtımı geri alma {d.kaynak_no}"),
                        ("ticari_mallar", SIFIR, stok_simdi, f"Masraf dağıtımı geri alma stok {d.kaynak_no}"),
                        ("satilan_mal_maliyeti", SIFIR, aktarilan - stok_simdi, f"Masraf dağıtımı geri alma SMM {d.kaynak_no}"),
                    ],
                    GM_KAYNAK_GERI,
                    bugun,
                    f"Ters kayıt: masraf dağıtımı {d.dagitim_no} — {neden}",
                )
                from database.models.genel_muhasebe import MuhasebeFisi

                asil = session.get(MuhasebeFisi, int(d.fis_id))
                if asil is not None:
                    asil.ters_fis_id = d.ters_fis_id
            d.geri_alan = _kullanici()
            d.geri_alma_tarihi = datetime.now()
            d.geri_alma_nedeni = neden[:300]
            MasrafDagitimService._gecmis(
                session, d.id, "GERİ AL",
                f"{neden} | lot={sayac['lot']} hareket={sayac['hareket']} satis_satiri={sayac['satis_satiri']} "
                f"ters_fis={d.ters_fis_id}",
            )
            return True

    @staticmethod
    def iptal_et(dagitim_id: int, neden: str = "") -> None:
        """Taslağı iptal eder (etkisi yoktur). Onaylı kayıt için geri_al kullanılır."""
        yazma_zorunlu("alis_masraf_duzenleme", "alis_masraf_onay")
        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            d = session.get(MasrafDagitim, int(dagitim_id))
            if d is None:
                raise ValueError("Masraf dağıtımı bulunamadı.")
            if d.durum == DURUM_IPTAL:
                return
            if d.durum != DURUM_TASLAK:
                raise ValueError("Onaylı dağıtım doğrudan iptal edilemez; Geri Al kullanın.")
            d.durum = DURUM_IPTAL
            d.row_version = int(d.row_version or 1) + 1
            d.geri_alma_nedeni = (neden or "Taslak iptal")[:300]
            d.geri_alan = _kullanici()
            d.geri_alma_tarihi = datetime.now()
            MasrafDagitimService._gecmis(session, d.id, "TASLAK İPTAL", neden or None)

    # ---------------------------------------------------------------- sorgu
    @staticmethod
    def listele(
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        kaynak: str | None = None,
        cari_id: int | None = None,
        durum: str | None = None,
    ) -> list[dict[str, Any]]:
        yetki_zorunlu("alis_masraf_goruntuleme", "alis_masraf_duzenleme", "alis_masraf_onay", "alis_goruntuleme")
        MasrafDagitimService.schema_hazirla()
        n_kaynak = turkce_normalize((kaynak or "").strip())
        with get_session() as session:
            q = select(MasrafDagitim).options(selectinload(MasrafDagitim.satirlar)).order_by(
                MasrafDagitim.dagitim_tarihi.desc(), MasrafDagitim.id.desc()
            )
            if baslangic:
                q = q.where(MasrafDagitim.dagitim_tarihi >= baslangic)
            if bitis:
                q = q.where(MasrafDagitim.dagitim_tarihi <= bitis)
            if cari_id:
                q = q.where(MasrafDagitim.kaynak_cari_id == int(cari_id))
            if durum and durum != "Tümü":
                q = q.where(MasrafDagitim.durum == durum)
            sonuc = []
            for d in session.scalars(q).all():
                if n_kaynak and n_kaynak not in turkce_normalize(d.kaynak_no):
                    continue
                sonuc.append(
                    {
                        "id": int(d.id),
                        "dagitim_no": d.dagitim_no,
                        "tarih": d.dagitim_tarihi,
                        "kaynak_no": d.kaynak_no,
                        "kaynak_turu": KAYNAK_ETIKETLERI.get(d.kaynak_turu, d.kaynak_turu),
                        "tutar": _q2(d.tutar),
                        "alis_sayisi": len({s.alis_fatura_id for s in d.satirlar}),
                        "yontem": YONTEM_ETIKETLERI.get(d.yontem, d.yontem),
                        "durum": d.durum,
                        "kullanici": d.onaylayan or d.olusturan or "",
                        "row_version": int(d.row_version or 1),
                    }
                )
            return sonuc

    @staticmethod
    def getir(dagitim_id: int) -> dict[str, Any]:
        MasrafDagitimService.schema_hazirla()
        with get_session() as session:
            d = session.scalar(
                select(MasrafDagitim)
                .options(selectinload(MasrafDagitim.satirlar), selectinload(MasrafDagitim.kaynak_satirlari))
                .where(MasrafDagitim.id == int(dagitim_id))
            )
            if d is None:
                raise ValueError("Masraf dağıtımı bulunamadı.")
            gecmis = session.scalars(
                select(MasrafDagitimGecmisi)
                .where(MasrafDagitimGecmisi.dagitim_id == d.id)
                .order_by(MasrafDagitimGecmisi.id)
            ).all()
            kolonlar = [c.name for c in MasrafDagitim.__table__.columns]
            sonuc = {k: getattr(d, k) for k in kolonlar}
            sonuc["kaynak_satir_idler"] = [k.kaynak_satir_id for k in d.kaynak_satirlari]
            sonuc["kaynak_satirlari"] = [
                {"kaynak_satir_id": k.kaynak_satir_id, "aciklama": k.aciklama, "tutar": _q2(k.tutar)}
                for k in d.kaynak_satirlari
            ]
            satir_kolon = [c.name for c in MasrafDagitimSatiri.__table__.columns]
            sonuc["satirlar"] = [{k: getattr(s, k) for k in satir_kolon} for s in sorted(d.satirlar, key=lambda x: x.id)]
            sonuc["gecmis"] = [
                {"islem": g.islem, "detay": g.detay, "kullanici": g.kullanici, "tarih": g.tarih} for g in gecmis
            ]
            return sonuc

    @staticmethod
    def fatura_baglantilari(alis_fatura_id: int) -> list[dict[str, Any]]:
        """Alış faturasına bağlı (iptal edilmemiş) dağıtımlar ve faturanın aldığı pay."""
        if not MasrafDagitimService._tablo_var():
            return []
        with get_session() as session:
            rows = session.execute(
                select(MasrafDagitim, func.sum(MasrafDagitimSatiri.pay))
                .join(MasrafDagitimSatiri, MasrafDagitimSatiri.dagitim_id == MasrafDagitim.id)
                .where(MasrafDagitimSatiri.alis_fatura_id == int(alis_fatura_id), MasrafDagitim.durum != DURUM_IPTAL)
                .group_by(MasrafDagitim.id)
                .order_by(MasrafDagitim.id)
            ).all()
            return [
                {
                    "id": int(d.id), "dagitim_no": d.dagitim_no, "tarih": d.dagitim_tarihi, "kaynak_no": d.kaynak_no,
                    "durum": d.durum, "pay": _q2(p), "tutar": _q2(d.tutar),
                }
                for d, p in rows
            ]

    @staticmethod
    def kaynak_baglantilari(kaynak_id: int) -> dict[str, Any]:
        """Gider belgesine bağlı dağıtımlar; dağıtılan ve kalan tutar."""
        if not MasrafDagitimService._tablo_var():
            return {"dagitimlar": [], "dagitilan": SIFIR, "kalan": None}
        detay = MasrafDagitimService.kaynak_detay(kaynak_id)
        with get_session() as session:
            kayitlar = session.scalars(
                select(MasrafDagitim)
                .where(MasrafDagitim.kaynak_turu == KAYNAK_HIZMET, MasrafDagitim.kaynak_id == int(kaynak_id))
                .order_by(MasrafDagitim.id)
            ).all()
            dagitimlar = [
                {"id": int(d.id), "dagitim_no": d.dagitim_no, "tarih": d.dagitim_tarihi, "durum": d.durum,
                 "tutar": _q2(d.tutar)}
                for d in kayitlar
            ]
        dagitilan = sum((s["dagitilan"] for s in detay["satirlar"]), SIFIR)
        return {
            "dagitimlar": dagitimlar,
            "dagitilan": dagitilan,
            "kalan": sum((s["kalan"] for s in detay["satirlar"]), SIFIR),
            "uygun": sum((s["tutar"] for s in detay["satirlar"] if s["uygun"]), SIFIR),
        }

    @staticmethod
    def kilit_kontrol(*, kaynak_id: int | None = None, alis_fatura_id: int | None = None) -> None:
        """Onaylı dağıtıma bağlı belge düzenlenemez / iptal edilemez."""
        if not MasrafDagitimService._tablo_var():
            return
        with get_session() as session:
            if kaynak_id:
                nolar = session.scalars(
                    select(MasrafDagitim.dagitim_no).where(
                        MasrafDagitim.kaynak_turu == KAYNAK_HIZMET,
                        MasrafDagitim.kaynak_id == int(kaynak_id),
                        MasrafDagitim.durum == DURUM_ONAYLANDI,
                    )
                ).all()
            else:
                nolar = session.scalars(
                    select(MasrafDagitim.dagitim_no)
                    .join(MasrafDagitimSatiri, MasrafDagitimSatiri.dagitim_id == MasrafDagitim.id)
                    .where(
                        MasrafDagitimSatiri.alis_fatura_id == int(alis_fatura_id or 0),
                        MasrafDagitim.durum == DURUM_ONAYLANDI,
                    )
                    .distinct()
                ).all()
        if nolar:
            raise ValueError(
                "Bu belge onaylı masraf dağıtımına bağlı (" + ", ".join(nolar) + "). "
                "Değiştirmek veya iptal etmek için önce Masraf Dağıtımı ekranından dağıtımı geri alın."
            )

    @staticmethod
    def maliyete_aktarilan_toplam(baslangic: date, bitis: date) -> Decimal:
        """Dönemde onaylanmış dağıtımlarla giderden stok/SMM'ye aktarılan toplam."""
        if not MasrafDagitimService._tablo_var():
            return SIFIR
        with get_session() as session:
            deger = session.scalar(
                select(func.coalesce(func.sum(MasrafDagitim.stok_payi + MasrafDagitim.smm_payi), 0)).where(
                    MasrafDagitim.durum == DURUM_ONAYLANDI,
                    MasrafDagitim.dagitim_tarihi >= baslangic,
                    MasrafDagitim.dagitim_tarihi <= bitis,
                )
            )
        return _q2(deger)
