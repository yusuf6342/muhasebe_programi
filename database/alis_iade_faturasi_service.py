"""Alış iade faturası (tedarikçiye mal iadesi).

Akış: Kaydet → TASLAK (stok/cari/fiş yok) · Onayla → ALIŞ İADE ÇIKIŞ stok hareketi + tedarikçi cari
alacağı + muhasebe (firma/evrak ayarına göre otomatik veya sonradan) tek transaction'da · İptal → bu
iadeye ait stok, cari, tahsilat ve fiş etkileri birlikte geri alınır.

Kaynak kontrolü: kaynaklı satır yalnız aynı tedarikçinin geçerli (iptal olmayan) alış satırına bağlanır;
iade hakkı (alınan − önceki iadeler) ile seçili depoda o alıştan stokta kalan miktar ayrı denetlenir.
Kayıtlı alışta bulunmayan ürün için kullanıcı gerekçeyle devam edebilir (devir / bağlantısız / başka
tedarikçi); tercih ürün-miktar-tedarikçi-depo imzasıyla saklanır, bunlar değişince geçersizdir.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import AccessError, yazma_zorunlu
from database.alis_faturasi_service import AlisFaturasiService
from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_iade_faturasi import (
    AlisIadeFaturasi,
    AlisIadeFaturasiSatiri,
    AlisIadeKaynakDagilimi,
)
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.finans import FinansHareketi
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.satis_siparisi_service import decimal
from database.stok_service import ALIS_IADE_CIKIS, StokService

TASLAK = "TASLAK"
IPTAL = "İPTAL"
ONAYLI_DURUMLAR = ("AÇIK", "KAPALI")

KAYNAKLI = "KAYNAKLI"
DEVIR = "DEVİR"
KAYNAKSIZ = "KAYNAKSIZ"
BASKA_TEDARIKCI = "BAŞKA TEDARİKÇİ"
GEREKCELI_DURUMLAR = (KAYNAKSIZ, BASKA_TEDARIKCI)

MAHSUP_MODLARI = ("FIFO", "KAYNAK", "AVANS")

KAYNAK_YOK_MESAJI = (
    "Bu ürün seçilen tedarikçinin kayıtlı alışlarında bulunamadı. Devirden veya eski kayıtlardan gelmiş "
    "olabilir. Kaynak seçebilir, satırı kaldırabilir veya gerekçe belirterek bağlantısız iadeye devam "
    "edebilirsiniz."
)

DORT = Decimal("0.0001")
IKI = Decimal("0.01")
SIFIR = Decimal("0")


class KaynakTercihiGerekli(ValueError):
    """Kaynaksız satır(lar) için kullanıcı tercihi yok ya da geçersiz (ürün/miktar/depo değişti)."""

    def __init__(self, mesaj: str, satirlar: list[int]):
        super().__init__(mesaj)
        self.satirlar = satirlar


class IadeDegisti(ValueError):
    """Belge başka bir kullanıcı/işlem tarafından değiştirilmiş."""


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:  # noqa: BLE001
        return SIFIR


def _kullanici() -> str:
    try:
        from database.session_manager import oturum

        return (getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None) or "")[:120]
    except Exception:  # noqa: BLE001
        return ""


def kaynak_imzasi(urun_kodu: str, temel_miktar, cari_id, depo: str) -> str:
    """Kullanıcı tercihinin geçerli olduğu ürün/miktar/tedarikçi/depo bileşimi."""
    ham = f"{(urun_kodu or '').strip().casefold()}|{_d(temel_miktar).quantize(DORT)}|{int(cari_id or 0)}|" \
          f"{(depo or '').strip().casefold()}"
    return hashlib.sha1(ham.encode("utf-8")).hexdigest()


def _no_uret(session) -> str:
    """AIF000001 biçiminde, firma veritabanında artan iade numarası (eşzamanlıda unique kısıtı korur)."""
    onek = "AIF"
    try:
        en_buyuk = session.execute(
            text(
                "SELECT MAX(CAST(SUBSTR(iade_no, 4) AS INTEGER)) FROM alis_iade_faturalari "
                "WHERE iade_no LIKE 'AIF%' AND SUBSTR(iade_no, 4) GLOB '[0-9]*'"
            )
        ).scalar()
    except Exception:  # noqa: BLE001
        en_buyuk = None
    return f"{onek}{int(en_buyuk or 0) + 1:06d}"


class AlisIadeFaturasiService:
    TASLAK = TASLAK
    IPTAL = IPTAL
    ONAYLI_DURUMLAR = ONAYLI_DURUMLAR
    KAYNAK_YOK_MESAJI = KAYNAK_YOK_MESAJI

    @staticmethod
    def aktif_tedarikcileri():
        from database.alis_siparisi_service import AlisSiparisiService

        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def iade_no() -> str:
        with get_session() as session:
            return _no_uret(session)

    @staticmethod
    def onayli_mi(iade) -> bool:
        return getattr(iade, "durum", None) in ONAYLI_DURUMLAR

    # ================================================================ sorgular
    @staticmethod
    def listele(filtre: dict[str, Any] | None = None, *, limit: int | None = None,
                offset: int = 0) -> list[dict[str, Any]]:
        """Filtre anahtarları: tarih_bas, tarih_bit, cari_id, urun, depo, sube_id, durum, kaynak_durumu,
        muhasebe (durum metni), arama (belge no / açıklama), iptaller (False: İPTAL hariç)."""
        f = filtre or {}
        with get_session() as session:
            q = select(AlisIadeFaturasi).options(
                selectinload(AlisIadeFaturasi.cari),
                selectinload(AlisIadeFaturasi.kaynak_fatura),
                selectinload(AlisIadeFaturasi.satirlar),
            )
            if f.get("tarih_bas"):
                q = q.where(AlisIadeFaturasi.iade_tarihi >= f["tarih_bas"])
            if f.get("tarih_bit"):
                q = q.where(AlisIadeFaturasi.iade_tarihi <= f["tarih_bit"])
            if f.get("cari_id"):
                q = q.where(AlisIadeFaturasi.cari_id == int(f["cari_id"]))
            if f.get("depo"):
                q = q.where(AlisIadeFaturasi.depo == f["depo"])
            if f.get("sube_id"):
                q = q.where(AlisIadeFaturasi.sube_id == int(f["sube_id"]))
            durum = f.get("durum")
            if durum == "ONAYLI":
                q = q.where(AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR))
            elif durum:
                q = q.where(AlisIadeFaturasi.durum == durum)
            if f.get("iptaller") is False:
                q = q.where(AlisIadeFaturasi.durum != IPTAL)
            if f.get("arama"):
                aranan = f"%{str(f['arama']).strip()}%"
                q = q.where(or_(AlisIadeFaturasi.iade_no.ilike(aranan), AlisIadeFaturasi.aciklama.ilike(aranan),
                                AlisIadeFaturasi.iade_nedeni.ilike(aranan)))
            if f.get("urun"):
                aranan = f"%{str(f['urun']).strip()}%"
                q = q.where(AlisIadeFaturasi.id.in_(
                    select(AlisIadeFaturasiSatiri.iade_id).where(or_(
                        AlisIadeFaturasiSatiri.urun_kodu.ilike(aranan),
                        AlisIadeFaturasiSatiri.urun_adi.ilike(aranan),
                        AlisIadeFaturasiSatiri.barkod.ilike(aranan)))))
            if f.get("kaynak_durumu"):
                kd = f["kaynak_durumu"]
                alt = select(AlisIadeFaturasiSatiri.iade_id)
                if kd == "BELİRSİZ":
                    alt = alt.where(AlisIadeFaturasiSatiri.kaynak_durumu.is_(None),
                                    AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id.is_(None))
                else:
                    alt = alt.where(AlisIadeFaturasiSatiri.kaynak_durumu == kd)
                q = q.where(AlisIadeFaturasi.id.in_(alt))
            q = q.order_by(AlisIadeFaturasi.iade_tarihi.desc(), AlisIadeFaturasi.id.desc())
            if limit and not f.get("muhasebe"):
                q = q.limit(int(limit)).offset(int(offset))
            kayitlar = session.scalars(q).all()
            sonuc = []
            for i in kayitlar:
                t = AlisIadeFaturasiService.belge_toplami(i)
                durumlar = {s.kaynak_durumu or (KAYNAKLI if s.kaynak_fatura_satiri_id else "BELİRSİZ")
                            for s in i.satirlar}
                sonuc.append({"iade": i, **t, "net": t["ara_toplam"] - t["iskonto"],
                              "kaynak_ozet": ", ".join(sorted(durumlar))})
        if f.get("muhasebe"):
            from database.muhasebelestirme_service import MuhasebelestirmeService

            harita = MuhasebelestirmeService.toplu_durum("alis_iade", [k["iade"].id for k in sonuc])
            sonuc = [k for k in sonuc if harita.get(k["iade"].id, "") == f["muhasebe"]]
            if limit:
                sonuc = sonuc[int(offset):int(offset) + int(limit)]
        return sonuc

    @staticmethod
    def liste_toplamlari(kayitlar: list[dict]) -> dict[str, Decimal]:
        """İptal belgeler toplamı artırmaz."""
        t = {"net": SIFIR, "kdv": SIFIR, "genel_toplam": SIFIR, "adet": 0}
        for k in kayitlar:
            if k["iade"].durum == IPTAL:
                continue
            t["net"] += _d(k["net"])
            t["kdv"] += _d(k["kdv"])
            t["genel_toplam"] += _d(k["genel_toplam"])
            t["adet"] += 1
        return t

    @staticmethod
    def getir(iade_id: int) -> AlisIadeFaturasi | None:
        with get_session() as session:
            return session.scalar(
                select(AlisIadeFaturasi)
                .options(
                    selectinload(AlisIadeFaturasi.cari),
                    selectinload(AlisIadeFaturasi.kaynak_fatura),
                    selectinload(AlisIadeFaturasi.satirlar).selectinload(AlisIadeFaturasiSatiri.dagilimlar),
                )
                .where(AlisIadeFaturasi.id == iade_id)
            )

    @staticmethod
    def tedarikci_urun_gecmisi(cari_id: int, urun_kodu: str) -> dict[str, Any]:
        """Tedarikçiden bu ürünün daha önce alınıp alınmadığını ve kaçtan alındığını döner."""
        adaylar = AlisIadeFaturasiService.kaynak_adaylari(cari_id, urun_kodu)
        gecmis = [{
            "fatura_no": a["fatura_no"], "tarih": a["tarih"], "miktar": a["miktar"], "birim": a["birim"],
            "birim_fiyat": a["birim_fiyat"], "iskonto_orani": a["iskonto_orani"], "net_fiyat": a["net_fiyat"],
            "fifo_birim_maliyeti": a["fifo_birim_maliyeti"], "satir_id": a["satir_id"],
        } for a in adaylar]
        ortalama = (sum((g["net_fiyat"] for g in gecmis), SIFIR) / Decimal(len(gecmis))) if gecmis else None
        return {"aldi": bool(gecmis), "adet": len(gecmis), "son_fiyat": gecmis[0]["net_fiyat"] if gecmis else None,
                "ortalama_fiyat": ortalama, "gecmis": gecmis}

    @staticmethod
    def tedarikci_alislari(cari_id: int) -> list[AlisFaturasi]:
        with get_session() as session:
            return list(session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.cari_id == cari_id, AlisFaturasi.durum != IPTAL)
                .options(selectinload(AlisFaturasi.satirlar), selectinload(AlisFaturasi.cari))
                .order_by(AlisFaturasi.fatura_tarihi.desc())
            ).all())

    # ---------------------------------------------------------------- kaynak hakları
    @staticmethod
    def _kaynak_carpani(kart, kaynak: AlisFaturasiSatiri) -> Decimal:
        c = _d(getattr(kaynak, "birim_carpani", None))
        if c > 0:
            return c
        return StokService.birim_carpani_kesin(kart, kaynak.birim or (kart.birim if kart else "Adet"))

    @staticmethod
    def _onceki_iade_temel(session, kaynak_satir_id: int, haric_iade_id: int | None = None) -> Decimal:
        """Kaynak alış satırından onaylı (iptal/taslak dışı) iadelerle çıkmış temel miktar."""
        haric = int(haric_iade_id or 0)
        dagilimli = session.execute(
            select(func.coalesce(func.sum(AlisIadeKaynakDagilimi.temel_miktar), 0))
            .join(AlisIadeFaturasiSatiri, AlisIadeFaturasiSatiri.id == AlisIadeKaynakDagilimi.satir_id)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .where(AlisIadeKaynakDagilimi.kaynak_fatura_satiri_id == int(kaynak_satir_id),
                   AlisIadeKaynakDagilimi.lot_id.is_not(None),
                   AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR), AlisIadeFaturasi.id != haric)
        ).scalar()
        # Eski iadeler (dağılım kaydı yok): satır miktarı × katsayı
        eski = SIFIR
        for s in session.scalars(
            select(AlisIadeFaturasiSatiri)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .where(AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id == int(kaynak_satir_id),
                   AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR), AlisIadeFaturasi.id != haric,
                   ~AlisIadeFaturasiSatiri.id.in_(select(AlisIadeKaynakDagilimi.satir_id)))
        ).all():
            eski += _d(s.miktar) * (_d(s.birim_carpani) or Decimal("1"))
        return _d(dagilimli) + eski

    @staticmethod
    def _onceki_iade_temel_toplu(session, kaynak_satir_idler: list[int],
                                 haric_iade_id: int | None = None) -> dict[int, Decimal]:
        """``_onceki_iade_temel`` ile aynı hesap; çok kaynak satırı için tek seferde."""
        sonuc = {int(i): SIFIR for i in kaynak_satir_idler}
        if not sonuc:
            return sonuc
        haric = int(haric_iade_id or 0)
        for kid, toplam in session.execute(
            select(AlisIadeKaynakDagilimi.kaynak_fatura_satiri_id, func.sum(AlisIadeKaynakDagilimi.temel_miktar))
            .join(AlisIadeFaturasiSatiri, AlisIadeFaturasiSatiri.id == AlisIadeKaynakDagilimi.satir_id)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .where(AlisIadeKaynakDagilimi.kaynak_fatura_satiri_id.in_(list(sonuc)),
                   AlisIadeKaynakDagilimi.lot_id.is_not(None),
                   AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR), AlisIadeFaturasi.id != haric)
            .group_by(AlisIadeKaynakDagilimi.kaynak_fatura_satiri_id)
        ).all():
            sonuc[int(kid)] += _d(toplam)
        for s in session.scalars(
            select(AlisIadeFaturasiSatiri)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .where(AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id.in_(list(sonuc)),
                   AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR), AlisIadeFaturasi.id != haric,
                   ~AlisIadeFaturasiSatiri.id.in_(select(AlisIadeKaynakDagilimi.satir_id)))
        ).all():
            sonuc[int(s.kaynak_fatura_satiri_id)] += _d(s.miktar) * (_d(s.birim_carpani) or Decimal("1"))
        return sonuc

    @staticmethod
    def _kaynak_lotlari(session, kaynak: AlisFaturasiSatiri, stok_id: int, depo_id: int) -> list[StokLotu]:
        """Kaynak alış satırının açtığı katman (ve lot korumalı transferle aynı depoya gelen devamı)."""
        lot_adi = (kaynak.lot_girisi or "").split(":")[0].strip()
        if not lot_adi:
            return []
        return list(session.scalars(
            select(StokLotu).where(
                StokLotu.stok_id == int(stok_id), StokLotu.depo_id == int(depo_id),
                or_(StokLotu.lot_no == lot_adi, StokLotu.lot_no.like(f"{lot_adi}-%")),
            ).order_by(StokLotu.giris_tarihi, StokLotu.id)
        ).all())

    @staticmethod
    def kaynak_adaylari(cari_id: int, urun_kodu: str, depo: str | None = None, *,
                        haric_iade_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Tedarikçinin bu ürün için geçerli alış satırları: hak, önceki iade, depoda stokta kalan."""
        kod = (urun_kodu or "").strip()
        if not kod or not cari_id:
            return []
        with get_session() as session:
            kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod)
                                  .options(selectinload(StokKarti.birimler)))
            depo_kaydi = session.scalar(select(Depo).where(Depo.ad == depo)) if depo else None
            satirlar = session.execute(
                select(AlisFaturasiSatiri, AlisFaturasi)
                .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                .where(AlisFaturasi.cari_id == int(cari_id), AlisFaturasi.durum != IPTAL,
                       AlisFaturasiSatiri.urun_kodu == kod)
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasiSatiri.id.desc())
                .limit(int(limit))
            ).all()
            onceki_harita = AlisIadeFaturasiService._onceki_iade_temel_toplu(
                session, [int(s.id) for s, _f in satirlar], haric_iade_id)
            depo_harita: dict[str, Depo | None] = {}
            lot_harita: dict[int, tuple[dict[str, list[StokLotu]], list[StokLotu]]] = {}

            def _depo_lotlari(depo_id: int):
                if depo_id not in lot_harita:
                    tam: dict[str, list[StokLotu]] = {}
                    tireli: list[StokLotu] = []
                    for l in session.scalars(select(StokLotu).where(
                            StokLotu.stok_id == int(kart.id), StokLotu.depo_id == int(depo_id))):
                        tam.setdefault(l.lot_no, []).append(l)
                        if "-" in (l.lot_no or ""):
                            tireli.append(l)
                    lot_harita[depo_id] = (tam, tireli)
                return lot_harita[depo_id]

            sonuc = []
            for satir, fatura in satirlar:
                try:
                    carpan = AlisIadeFaturasiService._kaynak_carpani(kart, satir)
                except ValueError:
                    carpan = None
                alinan_temel = _d(satir.miktar) * (carpan or Decimal("1"))
                onceki = onceki_harita.get(int(satir.id), SIFIR)
                hak = max(alinan_temel - onceki, SIFIR)
                stokta = None
                hedef_depo = depo_kaydi
                if hedef_depo is None and fatura.depo:
                    if fatura.depo not in depo_harita:
                        depo_harita[fatura.depo] = session.scalar(select(Depo).where(Depo.ad == fatura.depo))
                    hedef_depo = depo_harita[fatura.depo]
                if kart is not None and hedef_depo is not None:
                    lot_adi = (satir.lot_girisi or "").split(":")[0].strip()
                    stokta = SIFIR
                    if lot_adi:
                        tam, tireli = _depo_lotlari(int(hedef_depo.id))
                        eslesen = {id(l): l for l in tam.get(lot_adi, [])}
                        eslesen.update({id(l): l for l in tireli if l.lot_no.startswith(f"{lot_adi}-")})
                        stokta = sum((_d(l.kalan_miktar) for l in eslesen.values()), SIFIR)
                net = AlisFaturasiService._net_birim_maliyet(
                    satir.birim_fiyat, satir.iskonto_orani, getattr(satir, "iskonto_orani_2", 0) or 0,
                    getattr(satir, "iskonto_orani_3", 0) or 0)
                iade_edilebilir = min(hak, stokta) if stokta is not None else hak
                sonuc.append({
                    "satir_id": int(satir.id), "fatura_id": int(fatura.id), "fatura_no": fatura.fatura_no,
                    "tedarikci_fatura_no": getattr(fatura, "tedarikci_fatura_no", None),
                    "tarih": fatura.fatura_tarihi, "depo": fatura.depo, "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi, "miktar": _d(satir.miktar), "birim": satir.birim,
                    "birim_carpani": carpan, "alinan_temel": alinan_temel, "onceki_iade_temel": onceki,
                    "hak_temel": hak, "stokta_temel": stokta, "iade_edilebilir_temel": iade_edilebilir,
                    "birim_fiyat": _d(satir.birim_fiyat), "iskonto_orani": _d(satir.iskonto_orani),
                    "iskonto_orani_2": _d(getattr(satir, "iskonto_orani_2", 0)),
                    "iskonto_orani_3": _d(getattr(satir, "iskonto_orani_3", 0)),
                    "net_fiyat": net, "kdv_orani": _d(satir.kdv_orani),
                    "para_birimi": fatura.para_birimi or "TRY", "kur": _d(fatura.kur or 1),
                    "birim_fiyat_doviz": _d(getattr(satir, "birim_fiyat_doviz", 0)),
                    "fifo_birim_maliyeti": _d(satir.fifo_birim_maliyeti), "lot": satir.lot_girisi,
                })
            return sonuc

    @staticmethod
    def urun_kaynak_durumu(cari_id: int, urun_kodu: str, depo: str | None = None) -> dict[str, Any]:
        """Satır eklenirken: tedarikçi alışı var mı, başka tedarikçide görünüyor mu, devir katmanı var mı."""
        kod = (urun_kodu or "").strip()
        adaylar = AlisIadeFaturasiService.kaynak_adaylari(cari_id, kod, depo)
        with get_session() as session:
            baskalari = [r[0] for r in session.execute(
                select(Cari.unvan).join(AlisFaturasi, AlisFaturasi.cari_id == Cari.id)
                .join(AlisFaturasiSatiri, AlisFaturasiSatiri.fatura_id == AlisFaturasi.id)
                .where(AlisFaturasiSatiri.urun_kodu == kod, AlisFaturasi.durum != IPTAL,
                       AlisFaturasi.cari_id != int(cari_id or 0))
                .group_by(Cari.unvan).limit(20)
            ).all()]
            devir = AlisIadeFaturasiService._devir_lotlari(session, kod, depo)
        durum = KAYNAKLI if adaylar else (BASKA_TEDARIKCI if baskalari else (DEVIR if devir else KAYNAKSIZ))
        return {"durum": durum, "adaylar": adaylar, "baska_tedarikciler": baskalari, "devir_lotlari": devir,
                "mesaj": None if adaylar else KAYNAK_YOK_MESAJI}

    @staticmethod
    def _devir_lotlari(session, urun_kodu: str, depo: str | None) -> list[dict]:
        """Faturasız (devir/açılış/elle giriş) açılmış ve hâlâ stokta olan katmanlar."""
        kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == urun_kodu))
        if kart is None:
            return []
        devir_lot_idler = (select(StokHareketi.lot_id)
                           .where(StokHareketi.stok_id == kart.id, StokHareketi.lot_id.is_not(None),
                                  StokHareketi.hareket_turu.in_(("GİRİŞ", "SAYIM GİRİŞ"))))
        q = (select(StokLotu, Depo.ad)
             .join(Depo, Depo.id == StokLotu.depo_id)
             .where(StokLotu.stok_id == kart.id, StokLotu.kalan_miktar > 0,
                    StokLotu.id.in_(devir_lot_idler))
             .order_by(StokLotu.giris_tarihi, StokLotu.id))
        if depo:
            q = q.where(Depo.ad == depo)
        return [{"lot_id": int(l.id), "lot_no": l.lot_no, "depo": ad, "kalan": _d(l.kalan_miktar),
                 "birim_maliyet": _d(l.birim_maliyet), "giris_tarihi": l.giris_tarihi}
                for l, ad in session.execute(q).all()]

    # ================================================================ kayıt (taslak)
    @staticmethod
    def kaydet(veriler, satir_verileri, iade_id=None):
        """Taslak kaydeder (stok/cari/fiş oluşmaz). Onaylı belgede yalnız açıklama/iade nedeni değişir."""
        yazma_zorunlu("alis_duzenleme", "yeni_kayit")
        tarih = veriler["iade_tarihi"]
        if tarih > date.today():
            raise ValueError("İade tarihi gelecek bir tarih olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir iade satırı ekleyin.")
        if not veriler.get("cari_id"):
            raise ValueError("Tedarikçi seçin.")
        for deneme in range(5):
            try:
                return AlisIadeFaturasiService._kaydet(veriler, satir_verileri, iade_id)
            except IntegrityError as hata:
                if iade_id or veriler.get("iade_no") or deneme == 4:
                    raise ValueError("İade faturası kaydedilemedi (belge numarası çakıştı).") from hata
        raise ValueError("İade faturası kaydedilemedi.")

    @staticmethod
    def _kaydet(veriler, satir_verileri, iade_id):
        iid = AlisIadeFaturasiService._kaydet_yaz(veriler, satir_verileri, iade_id)
        return AlisIadeFaturasiService.getir(iid)

    @staticmethod
    def _kaydet_yaz(veriler, satir_verileri, iade_id) -> int:
        with get_session() as session:
            if iade_id:
                iade = session.get(AlisIadeFaturasi, int(iade_id))
                if not iade:
                    raise ValueError("İade faturası bulunamadı.")
                if iade.durum == IPTAL:
                    raise ValueError("İptal edilmiş iade düzenlenemez.")
                beklenen = veriler.get("row_version")
                if beklenen is not None and int(beklenen) != int(iade.row_version or 1):
                    raise IadeDegisti("Bu iade başka bir kullanıcı tarafından değiştirilmiş. Belgeyi yeniden açın.")
                if iade.durum != TASLAK:
                    AlisIadeFaturasiService._onayli_degisiklik_kontrol(iade, veriler, satir_verileri)
                    iade.aciklama = veriler.get("aciklama")
                    iade.iade_nedeni = veriler.get("iade_nedeni")
                    iade.row_version = int(iade.row_version or 1) + 1
                    session.flush()
                    return int(iade.id)
                eski_tercihler = {
                    (s.urun_kodu, s.kaynak_onay_imza): (s.kaynak_onaylayan, s.kaynak_onay_tarihi)
                    for s in iade.satirlar if s.kaynak_onay_imza
                }
                iade.satirlar.clear()
                session.flush()
                iade.row_version = int(iade.row_version or 1) + 1
            else:
                ozel_no = (veriler.get("iade_no") or "").strip()
                iade = AlisIadeFaturasi(iade_no=ozel_no or _no_uret(session), durum=TASLAK, row_version=1,
                                        olusturan=_kullanici())
                session.add(iade)
                eski_tercihler = {}

            iade.iade_tarihi = veriler["iade_tarihi"]
            iade.cari_id = int(veriler["cari_id"])
            cari = session.get(Cari, iade.cari_id)
            if cari is None:
                raise ValueError("Tedarikçi bulunamadı.")
            from database.sube_service import SubeService

            iade.sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            iade.kaynak_fatura_id = veriler.get("kaynak_fatura_id")
            iade.depo = veriler.get("depo") or "ANA DEPO"
            if session.scalar(select(Depo.id).where(Depo.ad == iade.depo)) is None:
                raise ValueError(f"{iade.depo} deposu bulunamadı.")
            iade.aciklama = veriler.get("aciklama")
            iade.iade_nedeni = veriler.get("iade_nedeni")
            mod = (veriler.get("mahsup_modu") or "FIFO").upper()
            if mod not in MAHSUP_MODLARI:
                raise ValueError("Geçersiz borç kapatma seçimi.")
            iade.mahsup_modu = mod
            iade.iade_odeme_tutari = decimal(veriler.get("iade_odeme_tutari", 0) or 0, "İade ödeme", SIFIR)
            iade.iade_odeme_sekli = veriler.get("iade_odeme_sekli")
            iade.iade_odeme_hesabi = veriler.get("iade_odeme_hesabi")
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1) or 1, "Kur", Decimal("0.000001"))
            iade.para_birimi = pb
            iade.kur = kur if pb != "TRY" else Decimal("1")
            iade.kur_tarihi = veriler.get("kur_tarihi")
            iade.kur_turu = veriler.get("kur_turu") or "forex_selling"
            iade.kur_kaynagi = veriler.get("kur_kaynagi") or "TCMB"
            iade.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", pb != "TRY"))

            doviz_ara = SIFIR
            kartlar: dict[str, StokKarti | None] = {}
            for sira, veri in enumerate(satir_verileri, start=1):
                kod = (veri.get("urun_kodu") or "").strip()
                if not kod:
                    raise ValueError(f"{sira}. satır: ürün kodu boş.")
                if kod not in kartlar:
                    kartlar[kod] = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod)
                                                  .options(selectinload(StokKarti.birimler)))
                kart = kartlar[kod]
                if kart is None:
                    raise ValueError(f"{sira}. satır: {kod} kodlu ürünün stok kartı yok.")
                miktar = _d(veri.get("miktar"))
                if miktar <= 0:
                    raise ValueError(f"{sira}. satır ({kod}): iade miktarı sıfırdan büyük olmalıdır.")
                birim = veri.get("birim") or kart.birim or "Adet"
                carpan = StokService.birim_carpani_kesin(kart, birim)
                temel = (miktar * carpan).quantize(DORT)
                birim_fiyat_doviz = _d(veri.get("birim_fiyat_doviz"))
                if pb != "TRY" and birim_fiyat_doviz > 0:
                    from database.doviz_service import DovizService

                    birim_fiyat = DovizService.dovizden_tle(birim_fiyat_doviz, kur, DORT)
                    from database.iskonto_hesap_service import iskonto_carpani

                    doviz_ara += miktar * birim_fiyat_doviz * iskonto_carpani(
                        veri.get("iskonto_orani", 0) or 0, veri.get("iskonto_orani_2", 0) or 0,
                        veri.get("iskonto_orani_3", 0) or 0)
                else:
                    birim_fiyat = decimal(veri.get("birim_fiyat", 0) or 0, "Birim fiyat", SIFIR)
                    birim_fiyat_doviz = SIFIR

                kaynak_id = veri.get("kaynak_fatura_satiri_id")
                kaynaklar = [k for k in (veri.get("kaynaklar") or []) if k.get("kaynak_fatura_satiri_id")]
                if kaynaklar and not kaynak_id:
                    kaynak_id = kaynaklar[0]["kaynak_fatura_satiri_id"]
                kaynak = None
                if kaynak_id:
                    kaynak = AlisIadeFaturasiService._kaynak_dogrula(session, int(kaynak_id), iade.cari_id, kod)
                    for k in kaynaklar:
                        AlisIadeFaturasiService._kaynak_dogrula(
                            session, int(k["kaynak_fatura_satiri_id"]), iade.cari_id, kod)
                    if kaynaklar:
                        dagitilan = sum((_d(k.get("miktar")) for k in kaynaklar), SIFIR)
                        if dagitilan != miktar:
                            raise ValueError(
                                f"{sira}. satır ({kod}): kaynak dağılımı toplamı ({dagitilan.normalize()}) "
                                f"satır miktarına ({miktar.normalize()}) eşit olmalı.")
                        idler = [int(k["kaynak_fatura_satiri_id"]) for k in kaynaklar]
                        if len(idler) != len(set(idler)):
                            raise ValueError(f"{sira}. satır ({kod}): aynı kaynak alış satırı iki kez seçilemez.")

                satir = AlisIadeFaturasiSatiri(
                    kaynak_fatura_satiri_id=int(kaynak_id) if kaynak_id else None,
                    urun_kodu=kod,
                    urun_adi=(veri.get("urun_adi") or kart.stok_adi or kod).strip(),
                    barkod=veri.get("barkod") or None,
                    miktar=miktar,
                    birim=birim,
                    birim_carpani=carpan,
                    temel_miktar=temel,
                    birim_fiyat=birim_fiyat,
                    birim_fiyat_doviz=birim_fiyat_doviz,
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0) or 0, "İskonto", SIFIR),
                    iskonto_orani_2=decimal(veri.get("iskonto_orani_2", 0) or 0, "İskonto 2", SIFIR),
                    iskonto_orani_3=decimal(veri.get("iskonto_orani_3", 0) or 0, "İskonto 3", SIFIR),
                    kdv_orani=decimal(veri.get("kdv_orani", 20) if veri.get("kdv_orani") not in (None, "")
                                      else 20, "KDV", SIFIR),
                    onceki_alis_fiyati=_d(veri["onceki_alis_fiyati"]) if veri.get("onceki_alis_fiyati")
                    not in (None, "") else None,
                    onceki_fatura_no=veri.get("onceki_fatura_no") or None,
                    lot_no=veri.get("lot_no") or None,
                    fifo_birim_maliyeti=SIFIR,
                )
                if kaynak is not None:
                    satir.kaynak_durumu = KAYNAKLI
                    satir.kaynak_birim_fiyat = AlisFaturasiService._net_birim_maliyet(
                        kaynak.birim_fiyat, kaynak.iskonto_orani, getattr(kaynak, "iskonto_orani_2", 0) or 0,
                        getattr(kaynak, "iskonto_orani_3", 0) or 0)
                    satir.kaynak_kur = _d(kaynak.fatura.kur or 1) if kaynak.fatura else None
                    if kaynak.fatura is not None:
                        satir.kaynak_para_birimi = (kaynak.fatura.para_birimi or "TRY").upper()
                        satir.kaynak_kur_tarihi = (getattr(kaynak.fatura, "kur_tarihi", None)
                                                   or kaynak.fatura.fatura_tarihi)
                    satir.onceki_fatura_no = satir.onceki_fatura_no or (kaynak.fatura.fatura_no if kaynak.fatura
                                                                        else None)
                    satir.onceki_alis_fiyati = satir.onceki_alis_fiyati or satir.kaynak_birim_fiyat
                    for k in kaynaklar or [{"kaynak_fatura_satiri_id": kaynak.id, "miktar": miktar}]:
                        satir.dagilimlar.append(AlisIadeKaynakDagilimi(
                            kaynak_fatura_satiri_id=int(k["kaynak_fatura_satiri_id"]),
                            miktar=_d(k.get("miktar")), temel_miktar=(_d(k.get("miktar")) * carpan).quantize(DORT),
                        ))
                else:
                    durum = veri.get("kaynak_durumu")
                    eski_imza = veri.get("kaynak_onay_imza")
                    if eski_imza and eski_imza != kaynak_imzasi(kod, temel, iade.cari_id, iade.depo):
                        durum = None
                    if durum in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI):
                        gerekce = (veri.get("kaynak_gerekce") or "").strip()
                        if durum in GEREKCELI_DURUMLAR and not gerekce:
                            raise ValueError(f"{sira}. satır ({kod}): bağlantısız iade için gerekçe yazın.")
                        if durum == DEVIR and not veri.get("kaynak_lot_id"):
                            raise ValueError(f"{sira}. satır ({kod}): devir kaynağı için devir katmanını seçin.")
                        imza = kaynak_imzasi(kod, temel, iade.cari_id, iade.depo)
                        satir.kaynak_durumu = durum
                        satir.kaynak_gerekce = gerekce or None
                        satir.kaynak_lot_id = int(veri["kaynak_lot_id"]) if veri.get("kaynak_lot_id") else None
                        satir.kaynak_onay_imza = imza
                        onceki_kim = eski_tercihler.get((kod, imza))
                        if onceki_kim and veri.get("kaynak_onay_tarihi") is None:
                            satir.kaynak_onaylayan, satir.kaynak_onay_tarihi = onceki_kim
                        else:
                            satir.kaynak_onaylayan = veri.get("kaynak_onaylayan") or _kullanici()
                            satir.kaynak_onay_tarihi = veri.get("kaynak_onay_tarihi") or datetime.now()
                iade.satirlar.append(satir)

            iade.doviz_ara_toplam = doviz_ara.quantize(IKI) if pb != "TRY" else SIFIR
            toplam = AlisIadeFaturasiService.toplam(iade.satirlar)["genel_toplam"]
            if iade.iade_odeme_tutari > toplam:
                raise ValueError("İade bedeli tahsilatı iade toplamından büyük olamaz.")
            if iade.iade_odeme_tutari > 0 and not iade.iade_odeme_hesabi:
                raise ValueError("İade bedeli tahsilatı için kasa/banka hesabı seçin.")
            iade.durum = TASLAK
            session.flush()
            return int(iade.id)

    @staticmethod
    def _onayli_degisiklik_kontrol(iade, veriler, satir_verileri) -> None:
        def anahtar(s):
            al = s.get if isinstance(s, dict) else (lambda k, d=None, _s=s: getattr(_s, k, d))
            return ((al("urun_kodu") or "").strip(), _d(al("miktar")).quantize(DORT), al("birim") or "",
                    _d(al("birim_fiyat")).quantize(DORT), _d(al("iskonto_orani")).quantize(IKI),
                    _d(al("kdv_orani")).quantize(IKI))

        degisen = []
        if veriler.get("iade_tarihi") != iade.iade_tarihi:
            degisen.append("tarih")
        if int(veriler.get("cari_id") or 0) != int(iade.cari_id):
            degisen.append("tedarikçi")
        if (veriler.get("depo") or "ANA DEPO") != iade.depo:
            degisen.append("depo")
        if _d(veriler.get("iade_odeme_tutari")) != _d(iade.iade_odeme_tutari):
            degisen.append("tahsilat")
        if sorted(map(anahtar, satir_verileri)) != sorted(map(anahtar, iade.satirlar)):
            degisen.append("satırlar")
        if degisen:
            raise ValueError(
                "Onaylı iadenin stok ve finansı etkileyen alanları değiştirilemez ("
                + ", ".join(degisen) + "). İadeyi iptal edip yeni belge oluşturun.")

    @staticmethod
    def _kaynak_dogrula(session, kaynak_id: int, cari_id: int, urun_kodu: str) -> AlisFaturasiSatiri:
        kaynak = session.get(AlisFaturasiSatiri, int(kaynak_id))
        if kaynak is None or kaynak.fatura is None:
            raise ValueError("Kaynak alış satırı bulunamadı.")
        if kaynak.fatura.durum == IPTAL:
            raise ValueError(f"Kaynak alış {kaynak.fatura.fatura_no} iptal edilmiş; kaynak olarak kullanılamaz.")
        if int(kaynak.fatura.cari_id) != int(cari_id):
            raise ValueError(f"Kaynak alış {kaynak.fatura.fatura_no} seçilen tedarikçiye ait değil.")
        if (kaynak.urun_kodu or "").strip() != (urun_kodu or "").strip():
            raise ValueError(f"Kaynak alış satırı başka bir ürüne ait ({kaynak.urun_kodu}).")
        return kaynak

    # ================================================================ onay
    @staticmethod
    def kaydet_ve_onayla(veriler, satir_verileri, iade_id=None, *, kaynaksiz_gerekce: str | None = None):
        """Taslak kaydı + onay. ``kaynaksiz_gerekce``: kaynak bağlantısı/tercihi olmayan satırlara
        (ör. dış sistemden içe aktarım) aynı gerekçeyle bağlantısız iade tercihi yazar."""
        if kaynaksiz_gerekce:
            satir_verileri = [
                v if (v.get("kaynak_fatura_satiri_id") or v.get("kaynaklar") or v.get("kaynak_durumu"))
                else {**v, "kaynak_durumu": KAYNAKSIZ, "kaynak_gerekce": kaynaksiz_gerekce}
                for v in satir_verileri
            ]
        iade = AlisIadeFaturasiService.kaydet(veriler, satir_verileri, iade_id)
        return AlisIadeFaturasiService.onayla(iade.id)

    @staticmethod
    def onay_on_kontrol(iade_id: int) -> list[str]:
        """Onay öncesi düzeltilmesi gereken eksikler (yazmadan)."""
        sorunlar: list[str] = []
        with get_session() as session:
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                return ["İade bulunamadı."]
            for s in iade.satirlar:
                ad = f"{s.urun_kodu}"
                if s.kaynak_fatura_satiri_id:
                    continue
                if s.kaynak_durumu not in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI):
                    sorunlar.append(f"{ad}: kaynak alış seçilmedi ve bağlantısız iade tercihi yok.")
                elif s.kaynak_onay_imza != kaynak_imzasi(s.urun_kodu, s.temel_miktar, iade.cari_id, iade.depo):
                    sorunlar.append(f"{ad}: ürün/miktar/tedarikçi/depo değiştiği için kaynak tercihi yeniden "
                                    "onaylanmalı.")
        return sorunlar

    @staticmethod
    def onayla(iade_id: int, *, beklenen_versiyon: int | None = None):
        """Taslağı onaylar: stok çıkışı, cari alacak, tahsilat ve muhasebe tek transaction'da, bir kez."""
        yazma_zorunlu("alis_duzenleme", "yeni_kayit")
        with get_session() as session:
            # İlk ifade yazma kilidi alır: eşzamanlı ikinci onay bu güncellemede bekler, sonra 0 satır görür.
            q = update(AlisIadeFaturasi).where(AlisIadeFaturasi.id == int(iade_id),
                                               AlisIadeFaturasi.durum == TASLAK)
            if beklenen_versiyon is not None:
                q = q.where(func.coalesce(AlisIadeFaturasi.row_version, 1) == int(beklenen_versiyon))
            sonuc = session.execute(
                q.values(row_version=func.coalesce(AlisIadeFaturasi.row_version, 1) + 1)
                .execution_options(synchronize_session=False))
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                raise ValueError("İade faturası bulunamadı.")
            session.refresh(iade)
            zaten_onayli = sonuc.rowcount != 1 and iade.durum in ONAYLI_DURUMLAR
            if sonuc.rowcount != 1 and not zaten_onayli:
                if iade.durum == IPTAL:
                    raise ValueError("İptal edilmiş iade onaylanamaz.")
                raise IadeDegisti("İade başka bir kullanıcı tarafından değiştirilmiş. Belgeyi yeniden açın.")
            iid = int(iade.id) if zaten_onayli else AlisIadeFaturasiService._onay_uygula(session, iade)
        if not zaten_onayli:
            try:
                from database.user_audit import audit_document

                audit_document("ALIS_IADE_ONAY", modul="alis_iade", kayit_id=str(iid),
                               aciklama="Alış iadesi onaylandı")
            except Exception:  # noqa: BLE001
                pass
        return AlisIadeFaturasiService.getir(iid)

    @staticmethod
    def _onay_uygula(session, iade) -> int:
            from database.muhasebe_service import kapali_donem_mi

            if kapali_donem_mi(session, iade.iade_tarihi):
                raise AccessError(f"İade tarihi {iade.iade_tarihi:%d.%m.%Y} kapalı (kilitli) bir döneme düşüyor; "
                                  "onaylanamaz.")
            if not iade.satirlar:
                raise ValueError("En az bir iade satırı ekleyin.")
            depo = session.scalar(select(Depo).where(Depo.ad == iade.depo))
            if depo is None:
                raise ValueError(f"{iade.depo} deposu bulunamadı.")

            eksik = []
            for s in iade.satirlar:
                if s.kaynak_fatura_satiri_id:
                    continue
                if s.kaynak_durumu not in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI) or (
                        s.kaynak_durumu in GEREKCELI_DURUMLAR and not (s.kaynak_gerekce or "").strip()):
                    eksik.append(s)
                elif s.kaynak_onay_imza != kaynak_imzasi(s.urun_kodu, s.temel_miktar, iade.cari_id, iade.depo):
                    eksik.append(s)
            if eksik:
                raise KaynakTercihiGerekli(
                    "Kaynak alış bulunmayan satırlar için tercih gerekli:\n"
                    + "\n".join(f"• {s.urun_kodu} — {s.urun_adi}" for s in eksik)
                    + f"\n\n{KAYNAK_YOK_MESAJI}",
                    [int(s.id) for s in eksik])

            kullanim: dict[int, Decimal] = {}
            sorunlar: list[str] = []
            for s in iade.satirlar:
                try:
                    AlisIadeFaturasiService._satir_cik(session, iade, s, depo, kullanim)
                except ValueError as hata:
                    sorunlar.append(f"• {s.urun_kodu} — {s.urun_adi}: {hata}")
            if sorunlar:
                raise ValueError("İade onaylanamadı; stoktan çıkış yapılmadı:\n" + "\n".join(sorunlar))

            session.flush()
            AlisIadeFaturasiService._kdv_kuru_uygula(session, iade)
            t = AlisIadeFaturasiService.belge_toplami(iade)
            toplam = t["genel_toplam"]
            odeme = _d(iade.iade_odeme_tutari)
            if odeme > toplam:
                raise ValueError("İade bedeli tahsilatı iade toplamından büyük olamaz.")
            iade.durum = "KAPALI" if odeme >= toplam and toplam > 0 else "AÇIK"
            iade.onaylayan = _kullanici()
            iade.onay_tarihi = datetime.now()
            session.flush()

            AlisIadeFaturasiService._cari_etkisi(session, iade, toplam)
            AlisIadeFaturasiService._kur_farki_yaz(session, iade)
            if odeme > 0:
                session.flush()
                AlisIadeFaturasiService._tahsilat_yaz(session, iade, odeme, iade.iade_tarihi,
                                                      iade.iade_odeme_hesabi, iade.iade_odeme_sekli)
            session.flush()
            iid = int(iade.id)
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("alis_iade_fisi", iid, yeniden=True, session=session)
            return iid

    @staticmethod
    def _satir_cik(session, iade, s: AlisIadeFaturasiSatiri, depo: Depo, kullanim: dict[int, Decimal]) -> None:
        kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == s.urun_kodu)
                              .options(selectinload(StokKarti.birimler)))
        if kart is None:
            raise ValueError("stok kartı yok.")
        carpan = StokService.birim_carpani_kesin(kart, s.birim)
        temel = (_d(s.miktar) * carpan).quantize(DORT)
        if temel <= 0:
            raise ValueError("iade miktarı sıfırdan büyük olmalı.")
        plan = [d for d in s.dagilimlar if d.lot_id is None]
        for d in list(s.dagilimlar):
            s.dagilimlar.remove(d)
        session.flush()
        parcalar_hepsi: list[tuple[int | None, dict]] = []
        if s.kaynak_fatura_satiri_id:
            if not plan:
                plan = [AlisIadeKaynakDagilimi(kaynak_fatura_satiri_id=s.kaynak_fatura_satiri_id, miktar=s.miktar)]
            for p in plan:
                kaynak = AlisIadeFaturasiService._kaynak_dogrula(
                    session, int(p.kaynak_fatura_satiri_id), iade.cari_id, s.urun_kodu)
                istenen = (_d(p.miktar) * carpan).quantize(DORT)
                k_carpan = AlisIadeFaturasiService._kaynak_carpani(kart, kaynak)
                alinan = _d(kaynak.miktar) * k_carpan
                onceki = AlisIadeFaturasiService._onceki_iade_temel(session, kaynak.id, iade.id)
                onceki += kullanim.get(int(kaynak.id), SIFIR)
                hak = alinan - onceki
                if istenen > hak:
                    raise ValueError(
                        f"kaynak alış {kaynak.fatura.fatura_no} iade hakkı aşıldı — alınan {alinan.normalize()}, "
                        f"önceki iadeler {onceki.normalize()}, kalan hak {max(hak, SIFIR).normalize()}, "
                        f"istenen {istenen.normalize()} {kart.birim or 'Adet'}.")
                lotlar = AlisIadeFaturasiService._kaynak_lotlari(session, kaynak, kart.id, depo.id)
                stokta = sum((_d(l.kalan_miktar) for l in lotlar), SIFIR)
                if istenen > stokta:
                    raise ValueError(
                        f"kaynak alış {kaynak.fatura.fatura_no} katmanından {depo.ad} deposunda stokta kalan "
                        f"{stokta.normalize()} {kart.birim or 'Adet'}; satılmış, tüketilmiş veya başka depoya "
                        f"aktarılmış miktar iade edilemez (istenen {istenen.normalize()}).")
                parcalar = StokService.alis_iade_cikisi(
                    session, iade.iade_no, iade.iade_tarihi, kart.id, depo.id, istenen,
                    lot_idler=[l.id for l in lotlar if _d(l.kalan_miktar) > 0])
                kullanim[int(kaynak.id)] = kullanim.get(int(kaynak.id), SIFIR) + istenen
                parcalar_hepsi.extend((int(kaynak.id), x) for x in parcalar)
        else:
            lot_idler = None
            if s.kaynak_durumu == DEVIR:
                lot = session.get(StokLotu, int(s.kaynak_lot_id or 0))
                if lot is None or int(lot.stok_id) != int(kart.id) or int(lot.depo_id) != int(depo.id):
                    raise ValueError("seçilen devir katmanı bu ürün/depoya ait değil.")
                lot_idler = [int(lot.id)]
            try:
                parcalar = StokService.alis_iade_cikisi(session, iade.iade_no, iade.iade_tarihi, kart.id, depo.id,
                                                        temel, lot_idler=lot_idler)
            except ValueError as hata:
                raise ValueError(f"{depo.ad} deposunda {hata}") from hata
            parcalar_hepsi.extend((None, x) for x in parcalar)

        sifir = [x["lot_no"] for _k, x in parcalar_hepsi if x["birim_maliyet"] <= 0]
        if sifir:
            raise ValueError(
                "güvenilir stok maliyeti yok (maliyeti 0 olan katman: " + ", ".join(sifir[:5])
                + "). Katman maliyetini düzeltmeden onaylanamaz; sıfır maliyet uydurulmaz.")
        maliyet = SIFIR
        for kaynak_id, x in parcalar_hepsi:
            m = (x["miktar"] * x["birim_maliyet"]).quantize(IKI, rounding=ROUND_HALF_UP)
            maliyet += x["miktar"] * x["birim_maliyet"]
            s.dagilimlar.append(AlisIadeKaynakDagilimi(
                kaynak_fatura_satiri_id=kaynak_id, miktar=(x["miktar"] / carpan).quantize(DORT),
                temel_miktar=x["miktar"], lot_id=x["lot_id"], stok_hareket_id=x["hareket_id"],
                birim_maliyet=x["birim_maliyet"], maliyet=m))
        s.birim_carpani = carpan
        s.temel_miktar = temel
        s.fifo_birim_maliyeti = (maliyet / temel).quantize(DORT)
        s.stok_maliyet_toplam = maliyet.quantize(IKI, rounding=ROUND_HALF_UP)
        s.lot_cikisi = ", ".join(f"{x['lot_no']}:{x['miktar'].normalize()}" for _k, x in parcalar_hepsi)[:100]

    @staticmethod
    def _cari_etkisi(session, iade, toplam: Decimal) -> None:
        """Tedarikçiye borcu azaltan alacak: seçime göre FIFO / kaynak alış / kapatmasız (açık alacak)."""
        if toplam <= 0:
            return
        session.add(CariIslem(
            cari_id=iade.cari_id, tarih=iade.iade_tarihi, islem_turu="Alış İadesi", belge_no=iade.iade_no,
            aciklama=iade.aciklama or iade.iade_nedeni or "Alış iade faturası", borc=SIFIR, alacak=toplam,
            hesap_adi=iade.iade_odeme_hesabi,
        ))
        mod = (iade.mahsup_modu or "FIFO").upper()
        dagitim = None
        fazla = "FIFO"
        if mod == "KAYNAK":
            fazla = "AVANS"
            kaynak_nolari = set()
            if iade.kaynak_fatura_id:
                kf = session.get(AlisFaturasi, int(iade.kaynak_fatura_id))
                if kf is not None:
                    kaynak_nolari.add(kf.fatura_no)
            for s in iade.satirlar:
                for d in s.dagilimlar:
                    if d.kaynak_fatura_satiri_id:
                        ks = session.get(AlisFaturasiSatiri, int(d.kaynak_fatura_satiri_id))
                        if ks is not None and ks.fatura is not None:
                            kaynak_nolari.add(ks.fatura.fatura_no)
            if kaynak_nolari:
                from database.acik_kalem_service import AcikKalemService

                kalan = toplam
                dagitim = []
                for h in session.scalars(select(SatisHareketi).where(
                        SatisHareketi.cari_id == iade.cari_id, SatisHareketi.belge_no.in_(sorted(kaynak_nolari)),
                        SatisHareketi.satis_tutari > 0).order_by(SatisHareketi.satis_tarihi, SatisHareketi.id)).all():
                    acik = AcikKalemService._guncel_kalan(session, h)
                    if acik <= 0 or kalan <= 0:
                        continue
                    pay = min(acik, kalan)
                    dagitim.append((int(h.id), pay))
                    kalan -= pay
        elif mod == "AVANS":
            fazla = "AVANS"
        CariService._alacak_uygula(session, iade.cari_id, toplam, iade.iade_no, iade.iade_tarihi,
                                   kaynak_tur="IADE", dagitim=dagitim or None, fazla=fazla)

    # ================================================================ kur farkı (dövizli iade)
    @staticmethod
    def _satir_doviz_genel(s, *, kdv_dahil: bool = True) -> Decimal | None:
        """Satırın döviz cinsinden KDV dahil tutarı (tedarikçi döviz borcundan düşen); döviz fiyatı yoksa None."""
        from database.iskonto_hesap_service import iskonto_carpani

        bf = _d(getattr(s, "birim_fiyat_doviz", 0))
        if bf <= 0:
            return None
        net = _d(s.miktar) * bf * iskonto_carpani(s.iskonto_orani or 0, getattr(s, "iskonto_orani_2", 0) or 0,
                                                  getattr(s, "iskonto_orani_3", 0) or 0)
        carpan = (1 + _d(s.kdv_orani) / 100) if kdv_dahil else Decimal("1")
        return (net * carpan).quantize(IKI, rounding=ROUND_HALF_UP)

    @staticmethod
    def _kaynak_doviz_borcu(fatura: AlisFaturasi) -> Decimal | None:
        toplam = SIFIR
        for s in fatura.satirlar:
            d = AlisIadeFaturasiService._satir_doviz_genel(s)
            if d is None:
                return None
            toplam += d
        return toplam

    @staticmethod
    def _kur_farki_yaz(session, iade) -> None:
        """Dövizli iade tedarikçinin döviz borcunu azaltır: kapatılan döviz × (kaynak alış kuru ↔ iade kuru).

        Kaynak alış faturası başına bir ``KurFarkiKaydi`` (kapatma = iade satırının o alışa ait ilk dağılımı).
        Kaynak kuru / iade kuru / döviz fiyatı yoksa veya para birimi farklıysa fark hesaplanmaz → İNCELEME.
        """
        pb = (iade.para_birimi or "TRY").upper()
        if pb == "TRY":
            return
        from database.kur_farki_service import (
            KAPATMA_ALIS_IADE,
            KAPATMA_ALIS_IADE_KAYNAKSIZ,
            YON_ALIS,
            KurFarkiService,
        )
        from database.models.genel_muhasebe import KUR_FARKI_HESAPLANDI

        session.flush()
        from database.muhasebe_finans_ayarlari import KDV_KURU_KAYNAK

        ik = _d(iade.kur)
        iade_kuru = ik if ik > 0 and ik != 1 else None
        # KDV kaynak kurla ters çevrildiyse KDV kısmında kur farkı yoktur
        kdv_dahil = iade.kdv_kur_yontemi != KDV_KURU_KAYNAK
        for s in iade.satirlar:
            s.iade_kuru = ik
            doviz = AlisIadeFaturasiService._satir_doviz_genel(s, kdv_dahil=kdv_dahil)
            ortak = dict(yon=YON_ALIS, cari_id=iade.cari_id, kapatma_belge_no=iade.iade_no,
                         tarih=iade.iade_tarihi, para_birimi=pb, odeme_kuru=iade_kuru)
            gruplar: dict[int, list[AlisIadeKaynakDagilimi]] = {}
            for d in s.dagilimlar:
                if d.kaynak_fatura_satiri_id:
                    ks = session.get(AlisFaturasiSatiri, int(d.kaynak_fatura_satiri_id))
                    if ks is not None:
                        gruplar.setdefault(int(ks.fatura_id), []).append(d)
            if not gruplar:
                KurFarkiService.kaydet(
                    session, **ortak, kaynak_evrak="alis_iade", kaynak_id=int(iade.id),
                    kaynak_belge_no=iade.iade_no, kapatma_turu=KAPATMA_ALIS_IADE_KAYNAKSIZ, kapatma_id=int(s.id),
                    doviz_tutar=doviz, kaynak_kur=None,
                    eksik_neden=f"{s.urun_kodu}: kaynak alış bağlantısı yok (devir/kaynaksız); kaynak kuru bilinmiyor")
                s.kur_farki_tl = None
                continue
            toplam_temel = sum((_d(d.temel_miktar) for ds in gruplar.values() for d in ds), SIFIR)
            kalan = doviz
            fark, eksik = SIFIR, False
            sirali = sorted(gruplar.items())
            for n, (fid, ds) in enumerate(sirali, start=1):
                f = session.get(AlisFaturasi, fid)
                pay = None
                if doviz is not None:
                    if n == len(sirali) or toplam_temel <= 0:
                        pay = kalan
                    else:
                        pay = (doviz * sum((_d(d.temel_miktar) for d in ds), SIFIR) / toplam_temel).quantize(
                            IKI, rounding=ROUND_HALF_UP)
                        kalan -= pay
                kpb = (f.para_birimi or "TRY").upper()
                kk = _d(f.kur)
                neden = None
                if kpb != pb:
                    neden = f"kaynak alış {f.fatura_no} para birimi {kpb}, iade {pb}; kur farkı hesaplanamaz"
                elif doviz is None:
                    neden = f"{s.urun_kodu}: satırın döviz birim fiyatı yok; kapatılan döviz tutarı belirlenemedi"
                elif iade_kuru is None:
                    neden = f"{iade.iade_no}: iade kuru tanımsız; kur tahmin edilmedi"
                kf = KurFarkiService.kaydet(
                    session, **ortak, kaynak_evrak="alis_faturasi", kaynak_id=int(fid), kaynak_belge_no=f.fatura_no,
                    kapatma_turu=KAPATMA_ALIS_IADE, kapatma_id=min(int(d.id) for d in ds), doviz_tutar=pay,
                    kaynak_kur=kk if kk > 0 and (kk != 1 or kpb == "TRY") else None,
                    doviz_borc=AlisIadeFaturasiService._kaynak_doviz_borcu(f), eksik_neden=neden)
                if kf is not None and kf.durum == KUR_FARKI_HESAPLANDI:
                    fark += _d(kf.kur_farki)
                else:
                    eksik = True
            s.kur_farki_tl = None if eksik else fark

    @staticmethod
    def kur_farki_kayitlari(iade_id: int) -> list[dict[str, Any]]:
        """İadenin kur farkı kayıtları (etkin + iptal), izlenebilirlik için."""
        from database.kur_farki_service import KAPATMA_ALIS_IADE, KAPATMA_ALIS_IADE_KAYNAKSIZ
        from database.models.genel_muhasebe import KurFarkiKaydi

        with get_session() as session:
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                return []
            return [{"id": int(k.id), "kaynak_belge_no": k.kaynak_belge_no, "doviz_tutar": _d(k.doviz_tutar),
                     "para_birimi": k.para_birimi, "kaynak_kur": k.kaynak_kur, "iade_kuru": k.odeme_kuru,
                     "kaynak_tl": _d(k.kaynak_tl), "iade_tl": _d(k.odeme_tl), "kur_farki": _d(k.kur_farki),
                     "durum": k.durum, "aciklama": k.aciklama}
                    for k in session.scalars(select(KurFarkiKaydi).where(
                        KurFarkiKaydi.kapatma_belge_no == iade.iade_no,
                        KurFarkiKaydi.kapatma_turu.in_((KAPATMA_ALIS_IADE, KAPATMA_ALIS_IADE_KAYNAKSIZ)))
                        .order_by(KurFarkiKaydi.id)).all()]

    @staticmethod
    def maliyet_farki(iade) -> dict[str, Decimal] | None:
        """İade bedeli (matrah, TL) ↔ gerçek FIFO stok maliyeti. Maliyeti kaydedilmemiş (eski) iadede None."""
        maliyetler = [getattr(s, "stok_maliyet_toplam", None) for s in iade.satirlar]
        if not maliyetler or any(m is None for m in maliyetler):
            return None
        t = AlisIadeFaturasiService.toplam(iade.satirlar)
        bedel = (t["ara_toplam"] - t["iskonto"]).quantize(IKI)
        maliyet = sum((_d(m) for m in maliyetler), SIFIR).quantize(IKI)
        return {"bedel": bedel, "maliyet": maliyet, "fark": bedel - maliyet}

    # ================================================================ iptal
    @staticmethod
    def iptal_on_kontrol(iade_id: int) -> dict[str, Any]:
        """İptalde birlikte geri alınacak bağlı kayıtlar (kullanıcıya gösterilir)."""
        with get_session() as session:
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                raise ValueError("İade faturası bulunamadı.")
            from database.muhasebe_service import kapali_donem_mi

            tahsilatlar = [(h.belge_no, _d(h.tutar)) for h in session.scalars(select(FinansHareketi).where(
                or_(FinansHareketi.belge_no == iade.iade_no, FinansHareketi.belge_no.like(f"{iade.iade_no}-T%"))
            )).all()]
            kapatmalar = []
            from database.models.cari import CariKapatma

            kapatmalar = [(k.hedef_belge_no, _d(k.tutar)) for k in session.scalars(select(CariKapatma).where(
                CariKapatma.kaynak_belge_no == iade.iade_no, CariKapatma.iptal.is_(False))).all()]
            return {"durum": iade.durum, "kapali_donem": kapali_donem_mi(session, iade.iade_tarihi),
                    "tahsilatlar": tahsilatlar, "kapatmalar": kapatmalar}

    @staticmethod
    def iptal_et(iade_id: int, neden: str = "") -> None:
        yazma_zorunlu("alis_duzenleme", "iptal")
        with get_session() as session:
            sonuc = session.execute(
                update(AlisIadeFaturasi).where(AlisIadeFaturasi.id == int(iade_id), AlisIadeFaturasi.durum != IPTAL)
                .values(row_version=func.coalesce(AlisIadeFaturasi.row_version, 1) + 1)
                .execution_options(synchronize_session=False))
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                raise ValueError("İade faturası bulunamadı.")
            session.refresh(iade)
            if sonuc.rowcount != 1 or iade.durum == IPTAL:
                return
            onayliydi = iade.durum in ONAYLI_DURUMLAR
            if onayliydi:
                from database.muhasebe_service import kapali_donem_mi

                if kapali_donem_mi(session, iade.iade_tarihi):
                    raise AccessError(f"İade tarihi {iade.iade_tarihi:%d.%m.%Y} kapalı döneme düşüyor; iptal "
                                      "edilemez. Dönemi açın veya düzeltmeyi açık dönemde yapın.")
                toplam = AlisIadeFaturasiService.belge_toplami(iade)["genel_toplam"]
                StokService.alis_iade_cikislarini_geri_al(session, iade.iade_no)
                tahsil_nolari = {iade.iade_no} | {
                    n for (n,) in session.execute(select(CariIslem.belge_no).where(
                        CariIslem.belge_no.like(f"{iade.iade_no}-T%"))).all()}
                for no in sorted(tahsil_nolari - {iade.iade_no}):
                    from database.acik_kalem_service import AcikKalemService

                    AcikKalemService.belge_kalemlerini_sil(session, no, iade.cari_id,
                                                          neden=f"Alış iade iptal {iade.iade_no}")
                CariService._aciklara_geri_al(session, iade.cari_id, toplam, iade.iade_no)
                session.execute(FinansHareketi.__table__.delete().where(
                    FinansHareketi.belge_no.in_(sorted(tahsil_nolari))))
                session.execute(CariIslem.__table__.delete().where(CariIslem.belge_no.in_(sorted(tahsil_nolari))))
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.belge_kalemlerini_sil(session, iade.iade_no, iade.cari_id,
                                                      neden=f"Alış iade iptal {iade.iade_no}")
                from database.kur_farki_service import (
                    KAPATMA_ALIS_IADE,
                    KAPATMA_ALIS_IADE_KAYNAKSIZ,
                    KurFarkiService,
                )

                KurFarkiService.kapatma_belgesi_iptal(
                    session, (KAPATMA_ALIS_IADE, KAPATMA_ALIS_IADE_KAYNAKSIZ), iade.iade_no,
                    f"Alış iade iptal {iade.iade_no}")
            iade.durum = IPTAL
            iade.iptal_eden = _kullanici()
            iade.iptal_tarihi = datetime.now()
            iade.iptal_nedeni = (neden or "").strip() or None
            session.flush()
            if onayliydi:
                from database.muhasebe_entegrasyon import muhasebe_hook

                muhasebe_hook("iptal_kaynak", "alis_iade", int(iade_id), neden or "Alış iade iptal", session=session)

        from database.deleted_record_service import ENTITY_ALIS_IADE, safe_log_cancel

        safe_log_cancel(ENTITY_ALIS_IADE, iade_id, note=f"Alış iade faturası iptal {neden or ''}".strip())

    # ================================================================ sonradan tahsilat
    @staticmethod
    def iade_tahsilati(iade_id: int, tutar, tarih: date, hesap_adi: str, odeme_sekli: str | None = None) -> str:
        """İade bedelinin tedarikçiden sonradan tahsili (iade alacağını kapatır; kasa/banka girişi)."""
        yazma_zorunlu("alis_duzenleme", "yeni_kayit")
        tutar = decimal(tutar, "Tahsilat tutarı", IKI)
        if tarih > date.today():
            raise ValueError("Tahsilat tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            sonuc = session.execute(
                update(AlisIadeFaturasi).where(AlisIadeFaturasi.id == int(iade_id),
                                               AlisIadeFaturasi.durum.in_(ONAYLI_DURUMLAR))
                .values(row_version=func.coalesce(AlisIadeFaturasi.row_version, 1) + 1)
                .execution_options(synchronize_session=False))
            iade = session.get(AlisIadeFaturasi, int(iade_id))
            if iade is None:
                raise ValueError("İade faturası bulunamadı.")
            session.refresh(iade)
            if sonuc.rowcount != 1:
                raise ValueError("Yalnız onaylı iadeye tahsilat girilebilir.")
            from database.muhasebe_service import kapali_donem_mi

            if kapali_donem_mi(session, tarih):
                raise AccessError("Tahsilat tarihi kapalı döneme düşüyor.")
            toplam = AlisIadeFaturasiService.belge_toplami(iade)["genel_toplam"]
            tahsil = _d(iade.iade_odeme_tutari)
            if tutar > toplam - tahsil:
                raise ValueError(f"Tahsil edilebilecek kalan iade bedeli {(toplam - tahsil).quantize(IKI)}.")
            belge_no = AlisIadeFaturasiService._tahsilat_yaz(session, iade, tutar, tarih, hesap_adi, odeme_sekli)
            iade.iade_odeme_tutari = tahsil + tutar
            iade.durum = "KAPALI" if iade.iade_odeme_tutari >= toplam else "AÇIK"
            session.flush()
            from database.muhasebe_entegrasyon import muhasebe_hook
            from database.muhasebelestirme_service import YONTEM_OTOMATIK, MuhasebelestirmeService

            otomatik = MuhasebelestirmeService.yontem("alis_iade", session=session) == YONTEM_OTOMATIK
            muhasebe_hook("alis_iade_fisi", int(iade.id), yeniden=not otomatik, session=session)
        return belge_no

    @staticmethod
    def _tahsilat_yaz(session, iade, tutar: Decimal, tarih: date, hesap_adi, odeme_sekli) -> str:
        if not (hesap_adi or "").strip():
            raise ValueError("Tahsilat için kasa/banka hesabı seçin.")
        sira = len(session.execute(select(CariIslem.id).where(
            CariIslem.belge_no.like(f"{iade.iade_no}-T%"))).all()) + 1
        belge_no = f"{iade.iade_no}-T{sira}"
        FinansService.hareket_ekle(session, belge_no, tarih, tutar, "ALIŞ İADE TAHSİLATI", hesap_adi,
                                   f"{iade.iade_no} iade bedeli tahsilatı"
                                   + (f" ({odeme_sekli})" if odeme_sekli else ""))
        session.add(CariIslem(cari_id=iade.cari_id, tarih=tarih, islem_turu="Alış İade Tahsilatı",
                              belge_no=belge_no, aciklama=f"{iade.iade_no} iade bedeli tahsilatı",
                              borc=tutar, alacak=SIFIR, hesap_adi=hesap_adi))
        session.flush()
        from database.acik_kalem_service import AcikKalemService

        AcikKalemService.borc_etkisi(session, iade.cari_id, tutar, belge_no=belge_no, tarih=tarih)
        return belge_no

    # ================================================================ bağlantılar
    @staticmethod
    def kaynaktan_iadeler(alis_fatura_id: int) -> list[dict[str, Any]]:
        """Kaynak alıştan bağlı iadeler (iade satırı veya kaynak dağılımı üzerinden)."""
        with get_session() as session:
            satir_idler = select(AlisFaturasiSatiri.id).where(AlisFaturasiSatiri.fatura_id == int(alis_fatura_id))
            iade_idler = select(AlisIadeFaturasiSatiri.iade_id).where(or_(
                AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id.in_(satir_idler),
                AlisIadeFaturasiSatiri.id.in_(select(AlisIadeKaynakDagilimi.satir_id).where(
                    AlisIadeKaynakDagilimi.kaynak_fatura_satiri_id.in_(satir_idler)))))
            kayitlar = session.scalars(select(AlisIadeFaturasi).where(or_(
                AlisIadeFaturasi.id.in_(iade_idler), AlisIadeFaturasi.kaynak_fatura_id == int(alis_fatura_id)))
                .options(selectinload(AlisIadeFaturasi.satirlar)).order_by(AlisIadeFaturasi.id)).all()
            return [{"id": int(i.id), "no": i.iade_no, "tarih": i.iade_tarihi, "durum": i.durum,
                     "genel": AlisIadeFaturasiService.belge_toplami(i)["genel_toplam"]} for i in kayitlar]

    @staticmethod
    def kaynak_faturalari(*, satir_id: int | None = None,
                          kaynak_satir_idler: list[int] | None = None) -> list[dict[str, Any]]:
        """İade satırının bağlı olduğu kaynak alış faturaları (onaylı: dağılımdan; taslak: seçili kaynaklardan)."""
        with get_session() as session:
            idler = {int(i) for i in (kaynak_satir_idler or []) if i}
            if satir_id:
                s = session.get(AlisIadeFaturasiSatiri, int(satir_id))
                if s is not None:
                    idler |= {int(d.kaynak_fatura_satiri_id) for d in s.dagilimlar if d.kaynak_fatura_satiri_id}
                    if s.kaynak_fatura_satiri_id:
                        idler.add(int(s.kaynak_fatura_satiri_id))
            if not idler:
                return []
            sonuc: dict[int, dict[str, Any]] = {}
            for ks, f in session.execute(
                    select(AlisFaturasiSatiri, AlisFaturasi)
                    .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                    .where(AlisFaturasiSatiri.id.in_(sorted(idler)))).all():
                sonuc.setdefault(int(f.id), {
                    "fatura_id": int(f.id), "fatura_no": f.fatura_no, "tarih": f.fatura_tarihi,
                    "tedarikci_fatura_no": getattr(f, "tedarikci_fatura_no", None), "durum": f.durum,
                    "para_birimi": f.para_birimi or "TRY", "kur": _d(f.kur or 1)})
            return sorted(sonuc.values(), key=lambda x: (x["tarih"] or date.min, x["fatura_id"]))

    @staticmethod
    def kaynak_iade_ozeti(alis_fatura_id: int) -> list[dict[str, Any]]:
        """Alış faturasının satır bazında alınan / onaylı iadelerle çıkan / kalan iade hakkı (temel birim)."""
        with get_session() as session:
            satirlar = list(session.scalars(select(AlisFaturasiSatiri).where(
                AlisFaturasiSatiri.fatura_id == int(alis_fatura_id)).order_by(AlisFaturasiSatiri.id)).all())
            onceki = AlisIadeFaturasiService._onceki_iade_temel_toplu(session, [int(s.id) for s in satirlar])
            kartlar: dict[str, StokKarti | None] = {}
            sonuc = []
            for s in satirlar:
                if s.urun_kodu not in kartlar:
                    kartlar[s.urun_kodu] = session.scalar(select(StokKarti).where(
                        StokKarti.stok_kodu == s.urun_kodu).options(selectinload(StokKarti.birimler)))
                kart = kartlar[s.urun_kodu]
                try:
                    carpan = AlisIadeFaturasiService._kaynak_carpani(kart, s)
                except ValueError:
                    carpan = None
                alinan = _d(s.miktar) * (carpan or Decimal("1"))
                iade = onceki.get(int(s.id), SIFIR)
                sonuc.append({"satir_id": int(s.id), "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi,
                              "birim": (kart.birim if kart else None) or s.birim, "alinan_temel": alinan,
                              "iade_temel": iade, "kalan_temel": max(alinan - iade, SIFIR),
                              "carpan_eksik": carpan is None})
            return sonuc

    @staticmethod
    def satir_baglantilari(satir_id: int) -> dict[str, Any]:
        """İade satırından kaynak alış/devir katmanı ve stok hareketlerine erişim."""
        with get_session() as session:
            s = session.get(AlisIadeFaturasiSatiri, int(satir_id))
            if s is None:
                raise ValueError("Satır bulunamadı.")
            kaynaklar = []
            for d in s.dagilimlar:
                ks = session.get(AlisFaturasiSatiri, int(d.kaynak_fatura_satiri_id)) if d.kaynak_fatura_satiri_id \
                    else None
                lot = session.get(StokLotu, int(d.lot_id)) if d.lot_id else None
                kaynaklar.append({
                    "alis_fatura_id": int(ks.fatura_id) if ks else None,
                    "alis_fatura_no": ks.fatura.fatura_no if ks and ks.fatura else None,
                    "kaynak_satir_id": int(ks.id) if ks else None, "lot_no": lot.lot_no if lot else None,
                    "miktar": _d(d.miktar), "temel_miktar": _d(d.temel_miktar),
                    "birim_maliyet": _d(d.birim_maliyet), "maliyet": _d(d.maliyet),
                    "stok_hareket_id": d.stok_hareket_id,
                })
            hareketler = [{"id": int(h.id), "tur": h.hareket_turu, "miktar": _d(h.miktar),
                           "birim_maliyet": _d(h.birim_maliyet), "lot_id": h.lot_id, "tarih": h.tarih}
                          for h in session.scalars(select(StokHareketi).where(
                              StokHareketi.belge_no == s.iade.iade_no,
                              StokHareketi.hareket_turu.in_((ALIS_IADE_CIKIS, "FATURA ÇIKIŞ")),
                              StokHareketi.id.in_([d.stok_hareket_id for d in s.dagilimlar if d.stok_hareket_id]
                                                  or [0]))).all()]
            devir = None
            if s.kaynak_lot_id:
                lot = session.get(StokLotu, int(s.kaynak_lot_id))
                devir = {"lot_id": int(lot.id), "lot_no": lot.lot_no} if lot else None
            return {"kaynak_durumu": s.kaynak_durumu or (KAYNAKLI if s.kaynak_fatura_satiri_id else None),
                    "gerekce": s.kaynak_gerekce, "onaylayan": s.kaynak_onaylayan, "tarih": s.kaynak_onay_tarihi,
                    "kaynaklar": kaynaklar, "hareketler": hareketler, "devir": devir}

    # ================================================================ hesap
    @staticmethod
    def toplam(satirlar) -> dict[str, Decimal]:
        """Alış faturasıyla aynı ortak hesap (üç kademeli iskonto, satır bazında kuruş yuvarlama)."""
        return AlisFaturasiService.toplam([
            {
                "miktar": (s.get("miktar") if isinstance(s, dict) else getattr(s, "miktar", 0)) or 0,
                "birim_fiyat": (s.get("birim_fiyat") if isinstance(s, dict) else getattr(s, "birim_fiyat", 0)) or 0,
                "iskonto_orani": (s.get("iskonto_orani", 0) if isinstance(s, dict)
                                  else getattr(s, "iskonto_orani", 0)) or 0,
                "iskonto_orani_2": (s.get("iskonto_orani_2", 0) if isinstance(s, dict)
                                    else getattr(s, "iskonto_orani_2", 0)) or 0,
                "iskonto_orani_3": (s.get("iskonto_orani_3", 0) if isinstance(s, dict)
                                    else getattr(s, "iskonto_orani_3", 0)) or 0,
                "kdv_orani": (s.get("kdv_orani", 20) if isinstance(s, dict) else getattr(s, "kdv_orani", 20)),
            }
            for s in satirlar
        ])

    @staticmethod
    def belge_toplami(iade) -> dict[str, Decimal]:
        """İadenin TL toplamı; yöntemli dövizli iadede KDV onayda yazılan TL tutarıdır."""
        t = AlisIadeFaturasiService.toplam(iade.satirlar)
        kdv_tl = getattr(iade, "kdv_tl_toplam", None)
        if kdv_tl is not None:
            kdv_tl = _d(kdv_tl)
            t = {**t, "genel_toplam": t["genel_toplam"] - t["kdv"] + kdv_tl, "kdv": kdv_tl}
        return t

    # ================================================================ dövizli iade KDV kuru
    @staticmethod
    def _firma_kdv_kur_yontemi(session) -> str | None:
        from database.muhasebe_finans_ayarlari import ALIS_IADE_KDV_KURU, ayar_oku

        try:
            return ayar_oku(ALIS_IADE_KDV_KURU, session=session)
        except Exception:  # noqa: BLE001 — ayar tablosu yoksa yöntem seçilmemiş sayılır
            return None

    @staticmethod
    def _satir_kaynak_kuru(session, iade, s) -> Decimal | None:
        """Satırın kaynak alış kuru (birden çok alışa dağıldıysa temel miktarla ağırlıklı); bilinmiyorsa None."""
        pb = (iade.para_birimi or "TRY").upper()
        pay, toplam = SIFIR, SIFIR
        for d in s.dagilimlar:
            ks = session.get(AlisFaturasiSatiri, int(d.kaynak_fatura_satiri_id)) if d.kaynak_fatura_satiri_id else None
            f = ks.fatura if ks is not None else None
            kk = _d(f.kur) if f is not None else SIFIR
            if f is None or (f.para_birimi or "TRY").upper() != pb or kk <= 0 or kk == 1:
                return None
            pay += kk * _d(d.temel_miktar)
            toplam += _d(d.temel_miktar)
        if toplam <= 0:
            return None
        return (pay / toplam).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _kdv_kuru_uygula(session, iade) -> None:
        """Onayda: firma KDV kuru yöntemini iadeye yazar, satır KDV'sinin TL karşılığını hesaplar.

        TL iade ve yöntem seçilmemiş dövizli iade değişmez (KDV belge kuruyla; kesin fiş yazılmaz).
        """
        from database.iskonto_hesap_service import iskonto_carpani
        from database.muhasebe_finans_ayarlari import KDV_KURU_KAYNAK

        iade.kdv_kur_yontemi, iade.kdv_tl_toplam = None, None
        for s in iade.satirlar:
            s.kdv_kuru, s.kdv_tl = None, None
        if (iade.para_birimi or "TRY").upper() == "TRY":
            return
        yontem = AlisIadeFaturasiService._firma_kdv_kur_yontemi(session)
        if not yontem:
            return
        ik = _d(iade.kur)
        toplam, eksik = SIFIR, []
        for s in iade.satirlar:
            if yontem == KDV_KURU_KAYNAK:
                kur = AlisIadeFaturasiService._satir_kaynak_kuru(session, iade, s)
                bf = _d(getattr(s, "birim_fiyat_doviz", 0))
                if kur is None or bf <= 0:
                    eksik.append(f"• {s.urun_kodu} — {s.urun_adi}")
                    continue
                net = _d(s.miktar) * bf * iskonto_carpani(s.iskonto_orani or 0, s.iskonto_orani_2 or 0,
                                                           s.iskonto_orani_3 or 0)
                kdv_tl = (net * _d(s.kdv_orani) / 100 * kur).quantize(IKI, rounding=ROUND_HALF_UP)
            else:
                kur = ik
                kdv_tl = AlisIadeFaturasiService.toplam([s])["kdv"]
            s.kdv_kuru, s.kdv_tl = kur, kdv_tl
            toplam += kdv_tl
        if eksik:
            raise ValueError(
                "KDV 'Kaynak alış kuru' yöntemiyle hesaplanamadı; kaynak alış kuru veya döviz fiyatı bilinmeyen "
                "satırlar (devir/kaynaksız, farklı para birimi):\n" + "\n".join(eksik)
                + "\n\nİade onaylanmadı; stok ve cari hareketi oluşmadı.")
        iade.kdv_kur_yontemi, iade.kdv_tl_toplam = yontem, toplam

    @staticmethod
    def kdv_kur_sorunu(session, iade) -> str | None:
        """Dövizli iadenin kesin muhasebeleşmesini engelleyen KDV kuru eksikliği (yoksa None)."""
        from database.muhasebe_finans_ayarlari import KDV_KURU_EKSIK_MESAJI, KDV_KURU_IADE

        if (iade.para_birimi or "TRY").upper() == "TRY" or iade.kdv_kur_yontemi:
            return None
        firma = AlisIadeFaturasiService._firma_kdv_kur_yontemi(session)
        if not firma:
            return f"{iade.iade_no}: {KDV_KURU_EKSIK_MESAJI}"
        if firma != KDV_KURU_IADE:
            return (f"{iade.iade_no}: KDV kuru yöntemi seçilmeden onaylandı; cari hareketi KDV iade tarihi kuruyla "
                    "oluştu. Firma ayarı 'Kaynak alış kuru' bu iadeye sonradan uygulanamaz; iadeyi iptal edip "
                    "yeniden onaylayın.")
        return None

    @staticmethod
    def satir_tutarlari(s) -> dict[str, Decimal]:
        t = AlisIadeFaturasiService.toplam([s])
        net = t["ara_toplam"] - t["iskonto"]
        miktar = _d(s.get("miktar") if isinstance(s, dict) else getattr(s, "miktar", 0))
        return {**t, "net": net, "net_birim": (net / miktar).quantize(DORT) if miktar else SIFIR}

    @staticmethod
    def stok_maliyeti(iade) -> Decimal | None:
        """Onaylı iadenin gerçek stok çıkış maliyeti (iç bilgi; tedarikçi çıktısına girmez)."""
        if getattr(iade, "durum", None) not in ONAYLI_DURUMLAR and getattr(iade, "durum", None) != IPTAL:
            return None
        return sum((_d(s.stok_maliyet_toplam) for s in iade.satirlar), SIFIR)
