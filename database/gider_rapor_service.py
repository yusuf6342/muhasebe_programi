"""Gider raporları R01–R08 ortak hesaplama servisi.

Rapor açmak fiş/ödeme/tahakkuk üretmez. Aynı ekonomik olay bir kez sayılır.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.database import engine, get_session
from database.models.gider_rapor import (
    GIDER_ANA_GRUPLAR,
    SINIF_ANA_GRUP,
    GiderAnaGrup,
    GiderAltGrup,
    GiderButceSatiri,
    GiderDagitimAnahtari,
    GiderDagitimPay,
)
from database.models.hizmet import HizmetKarti, gider_sinifi_etiket
from database.models.hizmet_faturasi import HizmetFaturasi
from database.models.finans import GiderFisi
from database.hizmet_faturasi_service import HizmetFaturasiService

_SIFIR = Decimal("0")
_YUZ = Decimal("100")
_IKI = Decimal("0.01")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _q(v: Decimal) -> Decimal:
    return _d(v).quantize(_IKI, rounding=ROUND_HALF_UP)


def _yuzde(pay: Decimal, payda: Decimal) -> Decimal | None:
    if payda is None or payda <= 0:
        return None
    return _q((pay / payda) * _YUZ)


def _degisim_yuzde(a: Decimal, b: Decimal) -> tuple[Decimal | None, str]:
    """A ana, B karşılaştırma. (yüzde, etiket)."""
    if b > 0:
        return _q(((a - b) / b) * _YUZ), "yuzde"
    if b == 0 and a > 0:
        return None, "yeni"
    if b == 0 and a == 0:
        return None, "yok"
    if b == 0 and a < 0:
        return None, "yeni_negatif"
    return None, "uygun_degil"


def onceki_es_donem(bas: date, bit: date) -> tuple[date, date]:
    """Aynı takvim günü sayısıyla hemen önceki aralık."""
    gun = (bit - bas).days + 1
    yeni_bit = bas - timedelta(days=1)
    yeni_bas = yeni_bit - timedelta(days=gun - 1)
    return yeni_bas, yeni_bit


def ay_araligi(yil: int, ay: int) -> tuple[date, date]:
    son = monthrange(yil, ay)[1]
    return date(yil, ay, 1), date(yil, ay, son)


class GiderRaporService:
    # ------------------------------------------------------------------ şema
    @staticmethod
    def ensure_schema() -> None:
        from database.database import Base

        Base.metadata.create_all(
            bind=engine,
            tables=[
                GiderAnaGrup.__table__,
                GiderAltGrup.__table__,
                GiderButceSatiri.__table__,
                GiderDagitimAnahtari.__table__,
                GiderDagitimPay.__table__,
            ],
        )
        # Hizmet kartı rapor alanları (firma DB açılmadan da güvenli)
        if inspect(engine).has_table("hizmet_kartlari"):
            sutunlar = {c["name"] for c in inspect(engine).get_columns("hizmet_kartlari")}
            ekler = {
                "rapor_ana_grup": "VARCHAR(40)",
                "rapor_alt_grup": "VARCHAR(40)",
                "sonuc_yeri": "VARCHAR(5)",
                "maliyet_davranisi": "VARCHAR(20)",
                "duzenlilik": "VARCHAR(20)",
                "dagitim_anahtar_kod": "VARCHAR(40)",
            }
            with engine.begin() as connection:
                for alan, tip in ekler.items():
                    if alan not in sutunlar:
                        connection.execute(
                            text(f'ALTER TABLE "hizmet_kartlari" ADD COLUMN "{alan}" {tip}')
                        )
        GiderRaporService._varsayilan_gruplari_ekle()

    @staticmethod
    def _varsayilan_gruplari_ekle() -> None:
        with get_session() as session:
            mevcut = {g.kod for g in session.scalars(select(GiderAnaGrup)).all()}
            for i, (kod, ad, yer) in enumerate(GIDER_ANA_GRUPLAR):
                if kod in mevcut:
                    continue
                session.add(
                    GiderAnaGrup(kod=kod, ad=ad, sonuc_yeri=yer, sira=i * 10, aktif=True)
                )
            session.flush()

    @staticmethod
    def ana_gruplari_listele() -> list[dict[str, Any]]:
        GiderRaporService.ensure_schema()
        with get_session() as session:
            gruplar = list(
                session.scalars(
                    select(GiderAnaGrup)
                    .options(selectinload(GiderAnaGrup.alt_gruplar))
                    .order_by(GiderAnaGrup.sira, GiderAnaGrup.ad)
                ).all()
            )
            return [
                {
                    "id": g.id,
                    "kod": g.kod,
                    "ad": g.ad,
                    "sonuc_yeri": g.sonuc_yeri,
                    "aktif": g.aktif,
                    "alt_gruplar": [
                        {"id": a.id, "kod": a.kod, "ad": a.ad, "aktif": a.aktif}
                        for a in (g.alt_gruplar or [])
                        if a.aktif
                    ],
                }
                for g in gruplar
                if g.aktif
            ]

    @staticmethod
    def kart_siniflandirma(kart: HizmetKarti | None) -> dict[str, str]:
        """Karttan kararlı rapor yolu üretir; boşsa sınıflandırılmamış."""
        if kart is None:
            return {
                "ana_grup_kod": "DIGER",
                "ana_grup_ad": "Sınıflandırılmamış",
                "alt_grup_kod": "",
                "alt_grup_ad": "",
                "sonuc_yeri": "O",
                "siniflandirilmamis": True,
                "maliyet_davranisi": "BELIRSIZ",
                "duzenlilik": "",
            }
        ana = (kart.rapor_ana_grup or "").strip().upper()
        if not ana:
            ana = SINIF_ANA_GRUP.get((kart.gider_sinifi or "").upper(), "")
        yer = (kart.sonuc_yeri or "").strip().upper()
        if not yer:
            yer = "F" if ana == "FINANSMAN" or (kart.gider_sinifi or "").upper() == "FINANS_MALI" else "O"
        ad_harita = {k: a for k, a, _ in GIDER_ANA_GRUPLAR}
        siniflandirilmamis = not ana
        if siniflandirilmamis:
            ana = "DIGER"
        return {
            "ana_grup_kod": ana or "DIGER",
            "ana_grup_ad": ad_harita.get(ana, gider_sinifi_etiket(kart.gider_sinifi) if siniflandirilmamis else ana),
            "alt_grup_kod": (kart.rapor_alt_grup or "").strip().upper(),
            "alt_grup_ad": (kart.rapor_alt_grup or "").strip(),
            "sonuc_yeri": yer if yer in ("O", "F") else "O",
            "siniflandirilmamis": siniflandirilmamis and not (kart.gider_sinifi or "").strip(),
            "maliyet_davranisi": (kart.maliyet_davranisi or "BELIRSIZ").upper(),
            "duzenlilik": (kart.duzenlilik or "").upper(),
            "hizmet_id": kart.id,
            "hizmet_kodu": kart.hizmet_kodu,
            "hizmet_adi": kart.hizmet_adi,
            "gider_sinifi": kart.gider_sinifi or "",
        }

    # ----------------------------------------------------------- kaynak satırlar
    @staticmethod
    def kaynak_satirlari(baslangic: date, bitis: date) -> list[dict[str, Any]]:
        """Onaylı dönem gider satırları (KDV hariç net). İade eksi gider."""
        if bitis < baslangic:
            raise ValueError("Bitiş, başlangıçtan önce olamaz.")
        satirlar: list[dict[str, Any]] = []
        with get_session() as session:
            faturalar = list(
                session.scalars(
                    select(HizmetFaturasi)
                    .where(HizmetFaturasi.durum != "İPTAL")
                    .options(
                        selectinload(HizmetFaturasi.satirlar),
                        selectinload(HizmetFaturasi.cari),
                    )
                ).all()
            )
            kart_ids = {
                s.hizmet_id
                for f in faturalar
                for s in (f.satirlar or [])
                if s.hizmet_id
            }
            fisler = list(
                session.scalars(select(GiderFisi).where(GiderFisi.durum != "IPTAL")).all()
            )
            kart_ids |= {f.hizmet_id for f in fisler if f.hizmet_id}
            kartlar = {
                k.id: k
                for k in session.scalars(
                    select(HizmetKarti).where(HizmetKarti.id.in_(kart_ids or [-1]))
                ).all()
            }

            for fatura in faturalar:
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                tur = (fatura.fatura_turu or "").upper()
                if tur not in ("GIDER", "GIDER_IADE"):
                    continue
                iade = tur == "GIDER_IADE"
                for s in fatura.satirlar or []:
                    net = _d(s.miktar) * _d(s.birim_fiyat)
                    net -= net * _d(s.iskonto_orani) / _YUZ
                    net = _q(net)
                    if iade:
                        net = -net
                    kart = kartlar.get(s.hizmet_id)
                    sinif = GiderRaporService.kart_siniflandirma(kart)
                    vergi = _q(net * _d(s.kdv_orani) / _YUZ) if not iade else _q(-abs(net) * _d(s.kdv_orani) / _YUZ)
                    satirlar.append(
                        {
                            "kaynak": "hizmet_fatura",
                            "kaynak_id": fatura.id,
                            "satir_id": s.id,
                            "belge_no": fatura.fatura_no,
                            "tarih": fatura.fatura_tarihi,
                            "vade": fatura.vade_tarihi,
                            "cari_id": fatura.cari_id,
                            "cari_ad": (
                                f"{fatura.cari.cari_kodu} — {fatura.cari.unvan}"
                                if fatura.cari
                                else "—"
                            ),
                            "net": net,
                            "vergi": vergi,
                            "brut": _q(net + vergi),
                            "iade": iade,
                            "muhasebe_durum": "",
                            **sinif,
                        }
                    )

            for fis in fisler:
                if fis.tarih < baslangic or fis.tarih > bitis:
                    continue
                kart = kartlar.get(fis.hizmet_id) if fis.hizmet_id else None
                sinif = GiderRaporService.kart_siniflandirma(kart)
                # Kredi faiz/masraf → finansman
                tur = (fis.gider_turu or "").upper()
                if tur in ("KREDI_FAIZ", "KREDI_MASRAF") and not (kart and kart.rapor_ana_grup):
                    sinif = {
                        **sinif,
                        "ana_grup_kod": "FINANSMAN",
                        "ana_grup_ad": "Finansman giderleri",
                        "sonuc_yeri": "F",
                        "siniflandirilmamis": False,
                    }
                net = _q(_d(fis.tutar))
                satirlar.append(
                    {
                        "kaynak": "gider_fis",
                        "kaynak_id": fis.id,
                        "satir_id": fis.id,
                        "belge_no": fis.belge_no or f"GF-{fis.id}",
                        "tarih": fis.tarih,
                        "vade": fis.tarih,
                        "cari_id": None,
                        "cari_ad": fis.aciklama or "—",
                        "net": net,
                        "vergi": _SIFIR,
                        "brut": net,
                        "iade": False,
                        "muhasebe_durum": "",
                        "gider_turu": tur,
                        **sinif,
                    }
                )
        return satirlar

    @staticmethod
    def _grupla(satirlar: list[dict]) -> dict[str, Any]:
        gruplar: dict[str, dict] = {}
        o = f = sinifsiz = _SIFIR
        for s in satirlar:
            kod = s["ana_grup_kod"]
            g = gruplar.setdefault(
                kod,
                {
                    "kod": kod,
                    "ad": s["ana_grup_ad"],
                    "sonuc_yeri": s["sonuc_yeri"],
                    "net": _SIFIR,
                    "alt": {},
                    "kartlar": {},
                    "satirlar": [],
                },
            )
            g["net"] += s["net"]
            g["satirlar"].append(s)
            alt_kod = s.get("alt_grup_kod") or "_DOGRUDAN"
            alt_ad = s.get("alt_grup_ad") or "Doğrudan gruba kayıtlı"
            alt = g["alt"].setdefault(alt_kod, {"kod": alt_kod, "ad": alt_ad, "net": _SIFIR})
            alt["net"] += s["net"]
            kid = s.get("hizmet_kodu") or f"kaynak:{s['kaynak']}"
            kart = g["kartlar"].setdefault(
                kid,
                {
                    "kod": kid,
                    "ad": s.get("hizmet_adi") or s.get("cari_ad") or kid,
                    "net": _SIFIR,
                },
            )
            kart["net"] += s["net"]
            if s["sonuc_yeri"] == "F":
                f += s["net"]
            else:
                o += s["net"]
            if s.get("siniflandirilmamis"):
                sinifsiz += s["net"]
        for g in gruplar.values():
            g["net"] = _q(g["net"])
            for a in g["alt"].values():
                a["net"] = _q(a["net"])
            for k in g["kartlar"].values():
                k["net"] = _q(k["net"])
        return {
            "gruplar": gruplar,
            "O": _q(o),
            "F": _q(f),
            "E": _q(o + f),
            "siniflandirilmamis": _q(sinifsiz),
            "adet": len(satirlar),
        }

    @staticmethod
    def satis_ozet(baslangic: date, bitis: date, maliyet_yontemi: str = "FIFO") -> dict[str, Decimal]:
        """S/M/B/I — gelir_tablosu çağırmadan (özyineleme yok)."""
        from sqlalchemy.orm import selectinload

        from database.database import get_session
        from database.models.satis_faturasi import SatisFaturasi
        from database.models.satis_iade_faturasi import SatisIadeFaturasi
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.models.hizmet_faturasi import HizmetFaturasi
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.hizmet_faturasi_service import HizmetFaturasiService
        from database.rapor_service import RaporService
        from database.masraf_dagitim_service import MasrafDagitimService
        from sqlalchemy import select

        sifir = _SIFIR
        brut_satis = satis_iskonto = sifir
        satis_iade_brut = satis_iade_iskonto = sifir
        alis_brut = alis_iskonto = sifir
        alis_iade_brut = alis_iade_iskonto = sifir
        hizmet_gelir = sifir
        with get_session() as session:
            for fatura in session.scalars(
                select(SatisFaturasi)
                .where(SatisFaturasi.durum != "İPTAL")
                .options(selectinload(SatisFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                t = SatisFaturasiService.toplam(fatura.satirlar)
                brut_satis += _d(t["ara_toplam"])
                satis_iskonto += _d(t["iskonto"])
            for iade in session.scalars(
                select(SatisIadeFaturasi)
                .where(SatisIadeFaturasi.durum != "İPTAL")
                .options(selectinload(SatisIadeFaturasi.satirlar))
            ).all():
                if iade.iade_tarihi < baslangic or iade.iade_tarihi > bitis:
                    continue
                t = SatisIadeFaturasiService.toplam(iade.satirlar)
                satis_iade_brut += _d(t["ara_toplam"])
                satis_iade_iskonto += _d(t["iskonto"])
            for fatura in session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                t = AlisFaturasiService.toplam(fatura.satirlar)
                alis_brut += _d(t["ara_toplam"])
                alis_iskonto += _d(t["iskonto"])
            for iade in session.scalars(
                select(AlisIadeFaturasi)
                .where(AlisIadeFaturasi.durum.not_in(("İPTAL", "TASLAK")))
                .options(selectinload(AlisIadeFaturasi.satirlar))
            ).all():
                if iade.iade_tarihi < baslangic or iade.iade_tarihi > bitis:
                    continue
                t = AlisIadeFaturasiService.toplam(iade.satirlar)
                alis_iade_brut += _d(t["ara_toplam"])
                alis_iade_iskonto += _d(t["iskonto"])
            for fatura in session.scalars(
                select(HizmetFaturasi)
                .where(HizmetFaturasi.durum != "İPTAL")
                .options(selectinload(HizmetFaturasi.satirlar))
            ).all():
                if fatura.fatura_tarihi < baslangic or fatura.fatura_tarihi > bitis:
                    continue
                t = HizmetFaturasiService.toplam(fatura.satirlar)
                net = _d(t["ara_toplam"]) - _d(t["iskonto"])
                tur = (fatura.fatura_turu or "").upper()
                if tur == "GELIR":
                    hizmet_gelir += net
                elif tur == "GELIR_IADE":
                    hizmet_gelir -= net

        onceki = date.fromordinal(baslangic.toordinal() - 1)
        bas_env = RaporService.stok_envanter(tarih=onceki, maliyet_yontemi=maliyet_yontemi, sadece_pozitif=True)
        son_env = RaporService.stok_envanter(tarih=bitis, maliyet_yontemi=maliyet_yontemi, sadece_pozitif=True)
        maliyete = MasrafDagitimService.maliyete_aktarilan_toplam(baslangic, bitis)
        satis_iade_net = satis_iade_brut - satis_iade_iskonto
        S = _q(brut_satis - satis_iskonto - satis_iade_net)
        alis_iade_net = alis_iade_brut - alis_iade_iskonto
        net_alis = alis_brut - alis_iskonto - alis_iade_net + maliyete
        M = _q(_d(bas_env.get("toplam_tutar")) + net_alis - _d(son_env.get("toplam_tutar")))
        B = _q(S - M)
        return {"S": S, "M": M, "B": B, "I": _q(hizmet_gelir), "J": _SIFIR}

    @staticmethod
    def donem_ozet(
        baslangic: date,
        bitis: date,
        *,
        maliyet_yontemi: str = "FIFO",
        onceki: tuple[date, date] | None = None,
    ) -> dict[str, Any]:
        satirlar = GiderRaporService.kaynak_satirlari(baslangic, bitis)
        g = GiderRaporService._grupla(satirlar)
        satis = GiderRaporService.satis_ozet(baslangic, bitis, maliyet_yontemi)
        S, M, B, I, J = satis["S"], satis["M"], satis["B"], satis["I"], satis["J"]
        O, F, E = g["O"], g["F"], g["E"]
        P = _q(B + I - O)
        K = _q(B + I + J - O - F)
        sonuc = {
            "baslangic": baslangic,
            "bitis": bitis,
            "gun": (bitis - baslangic).days + 1,
            "S": S,
            "M": M,
            "B": B,
            "O": O,
            "F": F,
            "E": E,
            "I": I,
            "J": J,
            "P": P,
            "K": K,
            "oran_e_s": _yuzde(E, S),
            "oran_o_s": _yuzde(O, S),
            "oran_e_b": _yuzde(E, B),
            "oran_k_s": _yuzde(K, S),
            "gruplar": g["gruplar"],
            "siniflandirilmamis": g["siniflandirilmamis"],
            "satirlar": satirlar,
            "adet": g["adet"],
            "hesap_zamani": datetime.now(),
            "maliyet_yontemi": maliyet_yontemi,
        }
        if onceki:
            ob, oe = onceki
            once = GiderRaporService.donem_ozet(ob, oe, maliyet_yontemi=maliyet_yontemi)
            sonuc["onceki"] = once
            sonuc["fark"] = {
                "E": _q(E - once["E"]),
                "S": _q(S - once["S"]),
                "E_yuzde": _degisim_yuzde(E, once["E"]),
                "S_yuzde": _degisim_yuzde(S, once["S"]),
                "oran_e_s_yp": (
                    _q(sonuc["oran_e_s"] - once["oran_e_s"])
                    if sonuc["oran_e_s"] is not None and once["oran_e_s"] is not None
                    else None
                ),
            }
        return sonuc

    # ---------------------------------------------------------------- R01–R08
    @staticmethod
    def r01_genel_bakis(baslangic: date, bitis: date, **kw) -> dict[str, Any]:
        once = onceki_es_donem(baslangic, bitis)
        return GiderRaporService.donem_ozet(baslangic, bitis, onceki=once, **kw)

    @staticmethod
    def r02_dagilim(baslangic: date, bitis: date, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        E, S, B = ozet["E"], ozet["S"], ozet["B"]
        satirlar = []
        for g in sorted(ozet["gruplar"].values(), key=lambda x: -x["net"]):
            satirlar.append(
                {
                    "seviye": "ana",
                    "kod": g["kod"],
                    "ad": g["ad"],
                    "net": g["net"],
                    "pay_e": _yuzde(g["net"], E),
                    "oran_s": _yuzde(g["net"], S),
                    "oran_b": _yuzde(g["net"], B),
                    "sonuc_yeri": g["sonuc_yeri"],
                }
            )
            for a in sorted(g["alt"].values(), key=lambda x: -x["net"]):
                satirlar.append(
                    {
                        "seviye": "alt",
                        "kod": a["kod"],
                        "ad": a["ad"],
                        "net": a["net"],
                        "pay_e": _yuzde(a["net"], E),
                        "pay_ana": _yuzde(a["net"], g["net"]),
                        "oran_s": _yuzde(a["net"], S),
                        "oran_b": _yuzde(a["net"], B),
                        "ana_kod": g["kod"],
                    }
                )
        ozet["dagilim_satirlari"] = satirlar
        return ozet

    @staticmethod
    def r03_karsilastirma(
        baslangic: date,
        bitis: date,
        onceki_bas: date | None = None,
        onceki_bit: date | None = None,
        **kw,
    ) -> dict[str, Any]:
        if onceki_bas is None or onceki_bit is None:
            onceki_bas, onceki_bit = onceki_es_donem(baslangic, bitis)
        a = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        b = GiderRaporService.donem_ozet(onceki_bas, onceki_bit, **kw)
        kodlar = set(a["gruplar"]) | set(b["gruplar"])
        satirlar = []
        for kod in sorted(kodlar):
            ga = a["gruplar"].get(kod, {"ad": kod, "net": _SIFIR})
            gb = b["gruplar"].get(kod, {"ad": ga.get("ad", kod), "net": _SIFIR})
            fark = _q(ga["net"] - gb["net"])
            yuz, etiket = _degisim_yuzde(ga["net"], gb["net"])
            satirlar.append(
                {
                    "kod": kod,
                    "ad": ga.get("ad") or gb.get("ad") or kod,
                    "b": gb["net"],
                    "a": ga["net"],
                    "fark": fark,
                    "yuzde": yuz,
                    "yuzde_etiket": etiket,
                    "oran_s_a": _yuzde(ga["net"], a["S"]),
                    "oran_s_b": _yuzde(gb["net"], b["S"]),
                }
            )
        return {
            "A": a,
            "B": b,
            "satirlar": satirlar,
            "ozet_fark": {
                "E": _q(a["E"] - b["E"]),
                "S": _q(a["S"] - b["S"]),
                "E_yuzde": _degisim_yuzde(a["E"], b["E"]),
                "S_yuzde": _degisim_yuzde(a["S"], b["S"]),
                "oran_e_s_yp": (
                    _q(a["oran_e_s"] - b["oran_e_s"])
                    if a["oran_e_s"] is not None and b["oran_e_s"] is not None
                    else None
                ),
            },
        }

    @staticmethod
    def r04_butce(baslangic: date, bitis: date, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        with get_session() as session:
            butceler = list(
                session.scalars(
                    select(GiderButceSatiri).where(
                        GiderButceSatiri.durum.in_(("ONAYLI", "REVIZE")),
                        GiderButceSatiri.mali_yil >= baslangic.year,
                        GiderButceSatiri.mali_yil <= bitis.year,
                    )
                ).all()
            )
        butce_map: dict[str, Decimal] = {}
        for b in butceler:
            d = date(b.mali_yil, b.ay, 1)
            if d < date(baslangic.year, baslangic.month, 1):
                continue
            if d > date(bitis.year, bitis.month, 1):
                continue
            butce_map[b.ana_grup_kod] = butce_map.get(b.ana_grup_kod, _SIFIR) + _d(b.tutar)
        satirlar = []
        for kod, g in sorted(ozet["gruplar"].items(), key=lambda x: -x[1]["net"]):
            butce = butce_map.get(kod)
            gercek = g["net"]
            if butce is None:
                satirlar.append(
                    {
                        "kod": kod,
                        "ad": g["ad"],
                        "butce": None,
                        "gerceklesen": gercek,
                        "sapma": None,
                        "sapma_yuzde": None,
                        "durum": "tanimli_degil",
                    }
                )
            else:
                sapma = _q(gercek - butce)
                satirlar.append(
                    {
                        "kod": kod,
                        "ad": g["ad"],
                        "butce": _q(butce),
                        "gerceklesen": gercek,
                        "sapma": sapma,
                        "sapma_yuzde": _yuzde(sapma, butce) if butce > 0 else None,
                        "durum": "plansiz" if butce == 0 and gercek > 0 else "karsilastirildi",
                    }
                )
        ozet["butce_satirlari"] = satirlar
        ozet["toplam_butce"] = _q(sum(butce_map.values())) if butce_map else None
        return ozet

    @staticmethod
    def r05_odeme_vade(baslangic: date, bitis: date, rapor_tarihi: date | None = None, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        rapor_tarihi = rapor_tarihi or date.today()
        buckets = {
            "gecikmis": [],
            "bugun": [],
            "1_7": [],
            "8_30": [],
            "31_90": [],
            "90_plus": [],
            "bilinmeyen": [],
        }
        acik_brut = _SIFIR
        with get_session() as session:
            faturalar = list(
                session.scalars(
                    select(HizmetFaturasi)
                    .where(
                        HizmetFaturasi.durum == "AÇIK",
                        HizmetFaturasi.fatura_turu.in_(("GIDER",)),
                    )
                    .options(selectinload(HizmetFaturasi.cari), selectinload(HizmetFaturasi.satirlar))
                ).all()
            )
            for f in faturalar:
                toplam = HizmetFaturasiService.toplam(f.satirlar)["genel_toplam"]
                kalan = _q(_d(toplam) - _d(f.odeme_tutari))
                if kalan <= 0:
                    continue
                acik_brut += kalan
                vade = f.vade_tarihi
                kayit = {
                    "belge_no": f.fatura_no,
                    "cari": f"{f.cari.cari_kodu} — {f.cari.unvan}" if f.cari else "—",
                    "vade": vade,
                    "kalan": kalan,
                    "kaynak_id": f.id,
                }
                if vade is None:
                    buckets["bilinmeyen"].append(kayit)
                    continue
                fark = (vade - rapor_tarihi).days
                if fark < 0:
                    buckets["gecikmis"].append({**kayit, "gecikme": -fark})
                elif fark == 0:
                    buckets["bugun"].append(kayit)
                elif fark <= 7:
                    buckets["1_7"].append(kayit)
                elif fark <= 30:
                    buckets["8_30"].append(kayit)
                elif fark <= 90:
                    buckets["31_90"].append(kayit)
                else:
                    buckets["90_plus"].append(kayit)
        ozet["vade_kovalar"] = buckets
        ozet["acik_borc_brut"] = acik_brut
        ozet["donem_gider_net"] = ozet["E"]
        ozet["rapor_tarihi"] = rapor_tarihi
        return ozet

    @staticmethod
    def r06_finansman_pos(baslangic: date, bitis: date, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        faiz = masraf = pos = _SIFIR
        detay = []
        for s in ozet["satirlar"]:
            if s["sonuc_yeri"] != "F" and s.get("ana_grup_kod") not in ("FINANSMAN", "POS"):
                if s.get("gider_turu") not in ("KREDI_FAIZ", "KREDI_MASRAF"):
                    continue
            tur = s.get("gider_turu") or ""
            if tur == "KREDI_FAIZ" or "faiz" in (s.get("ana_grup_ad") or "").lower():
                faiz += s["net"]
            elif tur == "KREDI_MASRAF":
                masraf += s["net"]
            elif s.get("ana_grup_kod") == "POS":
                pos += s["net"]
            detay.append(s)
        # POS efektif oran — hacim bilinmiyorsa hesaplanamaz
        ozet["finansman"] = {
            "faiz": _q(faiz),
            "masraf": _q(masraf),
            "pos": _q(pos),
            "toplam_f": ozet["F"],
            "pos_efektif_oran": None,
            "pos_efektif_neden": "POS işlem hacmi kaynağı bu dönemde tanımlı değil",
            "detay": detay,
            "not": "POS faaliyet giderindeyse F'ye ikinci kez eklenmez; inceleme görünümüdür.",
        }
        return ozet

    @staticmethod
    def r07_basabas(baslangic: date, bitis: date, hedef_sonuc: Decimal = _SIFIR, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        sabit = degisken = belirsiz = _SIFIR
        for s in ozet["satirlar"]:
            d = (s.get("maliyet_davranisi") or "BELIRSIZ").upper()
            if d == "SABIT":
                sabit += s["net"]
            elif d == "DEGISKEN":
                degisken += s["net"]
            else:
                belirsiz += s["net"]
        # Mal maliyeti varsayılan değişken satış maliyeti
        V = _q(ozet["M"] + degisken)
        T = _q(ozet["S"] - V)
        t = (T / ozet["S"]) if ozet["S"] > 0 else None
        H = _q(sabit)  # yalnız doğrulanmış sabit; belirsiz dahil edilmez
        faaliyet_esik = _q(H / t) if t and t > 0 else None
        finansman_sabit = ozet["F"]  # faiz çoğu durumda sabit kabul; belirsiz ayrılır
        finans_esik = _q((H + finansman_sabit) / t) if t and t > 0 else None
        hedef_satis = (
            _q((H + finansman_sabit + _d(hedef_sonuc)) / t) if t and t > 0 else None
        )
        guvenlik = _q(ozet["S"] - faaliyet_esik) if faaliyet_esik is not None else None
        guvenlik_oran = _yuzde(guvenlik, ozet["S"]) if guvenlik is not None else None
        ozet["basabas"] = {
            "sabit": _q(sabit),
            "degisken_faaliyet": _q(degisken),
            "belirsiz": _q(belirsiz),
            "V": V,
            "T": T,
            "t": _q(t * _YUZ) if t is not None else None,
            "faaliyet_esik": faaliyet_esik,
            "finansman_dahil_esik": finans_esik,
            "hedef_satis": hedef_satis,
            "guvenlik_payi": guvenlik,
            "guvenlik_oran": guvenlik_oran,
            "kismi": belirsiz > 0 or t is None or t <= 0,
            "neden": (
                "Önemli tutarda davranış sınıfı belirsiz veya katkı oranı pozitif değil"
                if belirsiz > 0 or t is None or t <= 0
                else ""
            ),
        }
        return ozet

    @staticmethod
    def r08_belge_kontrol(baslangic: date, bitis: date, **kw) -> dict[str, Any]:
        ozet = GiderRaporService.donem_ozet(baslangic, bitis, **kw)
        kaynak_toplam = sum((s["net"] for s in ozet["satirlar"]), _SIFIR)
        # Aday mükerrerlik: aynı tutar+tarih+cari
        adaylar = []
        anahtarlar: dict[tuple, list] = {}
        for s in ozet["satirlar"]:
            key = (s["tarih"], _q(s["net"]), s.get("cari_id"))
            anahtarlar.setdefault(key, []).append(s)
        for key, lst in anahtarlar.items():
            if len(lst) > 1:
                adaylar.append(lst)
        ozet["kontrol"] = {
            "kaynak_toplam": _q(kaynak_toplam),
            "rapor_toplam": ozet["E"],
            "fark": _q(kaynak_toplam - ozet["E"]),
            "siniflandirilmamis": ozet["siniflandirilmamis"],
            "siniflandirilmamis_adet": sum(
                1 for s in ozet["satirlar"] if s.get("siniflandirilmamis")
            ),
            "mukerrer_aday": adaylar,
            "iptal_haric": True,
            "notlar": [
                "Kaynak fatura ile bağlı muhasebe fişi toplanmaz; fiş mutabakat içindir.",
                "Benzer tutar/tarih otomatik silinmez; aday inceleme listesindedir.",
            ],
        }
        return ozet

    # --------------------------------------------------------------- bütçe CRUD
    @staticmethod
    def butce_kaydet(
        mali_yil: int,
        ay: int,
        ana_grup_kod: str,
        tutar,
        *,
        alt_grup_kod: str | None = None,
        durum: str = "ONAYLI",
        gerekce: str | None = None,
    ) -> GiderButceSatiri:
        from database.access import yazma_zorunlu

        yazma_zorunlu("finans_duzenleme", "yeni_kayit")
        GiderRaporService.ensure_schema()
        with get_session() as session:
            mevcut = session.scalar(
                select(GiderButceSatiri).where(
                    GiderButceSatiri.mali_yil == mali_yil,
                    GiderButceSatiri.ay == ay,
                    GiderButceSatiri.ana_grup_kod == ana_grup_kod,
                    GiderButceSatiri.alt_grup_kod == alt_grup_kod,
                    GiderButceSatiri.surum == 1,
                )
            )
            if mevcut:
                mevcut.tutar = _q(_d(tutar))
                mevcut.durum = durum
                mevcut.gerekce = gerekce
                if durum == "ONAYLI":
                    mevcut.onay_tarihi = date.today()
                sid = mevcut.id
            else:
                kayit = GiderButceSatiri(
                    mali_yil=mali_yil,
                    ay=ay,
                    ana_grup_kod=ana_grup_kod,
                    alt_grup_kod=alt_grup_kod,
                    tutar=_q(_d(tutar)),
                    durum=durum,
                    surum=1,
                    gerekce=gerekce,
                    onay_tarihi=date.today() if durum == "ONAYLI" else None,
                )
                session.add(kayit)
                session.flush()
                sid = kayit.id
        with get_session() as session:
            return session.get(GiderButceSatiri, sid)
