"""Fiyatlı Stok Ekstresi — okuma amaçlı görünüm (hareket kayıtlarını değiştirmez)."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.access import maliyet_izinli
from database.database import get_session
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum
from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI, StokService

_LOG = logging.getLogger(__name__)

_EKSTRE_GIRIS = set(GIRIS_HAREKETLERI) | {"İRSALİYE İADE GİRİŞ"}
_EKSTRE_CIKIS = set(CIKIS_HAREKETLERI) | {"İRSALİYE ÇIKIŞ"}

_CARI_YOK_TUR = {
    "GİRİŞ",
    "ÇIKIŞ",
    "TRANSFER GİRİŞ",
    "TRANSFER ÇIKIŞ",
    "SAYIM GİRİŞ",
    "SAYIM ÇIKIŞ",
    "PAKET GİRİŞ",
    "PAKET ÇIKIŞ",
}

_ETIKET = {
    "İADE GİRİŞ": "Satış İadesi",
    "SAYIM GİRİŞ": "Sayım",
    "SAYIM ÇIKIŞ": "Sayım",
    "TRANSFER GİRİŞ": "Transfer",
    "TRANSFER ÇIKIŞ": "Transfer",
    "PAKET GİRİŞ": "Paket",
    "PAKET ÇIKIŞ": "Paket",
    "İRSALİYE ÇIKIŞ": "İrsaliye",
    "İRSALİYE İADE GİRİŞ": "İrsaliye İade",
}


def _d(v, default="0") -> Decimal:
    try:
        return Decimal(str(v if v is not None else default))
    except Exception:
        return Decimal(default)


def _net_birim(satir) -> Decimal | None:
    if satir is None:
        return None
    tl = getattr(satir, "tl_birim_fiyat", None)
    if tl is not None and _d(tl) > 0:
        return _d(tl)
    bf = _d(getattr(satir, "birim_fiyat", 0))
    for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
        oran = _d(getattr(satir, alan, 0) or 0)
        if oran:
            bf = bf * (Decimal("1") - oran / Decimal("100"))
    return bf


def _aktif_donem_tarihleri() -> tuple[date, date]:
    bugun = date.today()
    bas, bit = date(bugun.year, 1, 1), bugun
    if not oturum.period_id:
        return bas, bit
    try:
        from database.models.donem import Donem

        with get_session() as session:
            d = session.get(Donem, int(oturum.period_id))
            if d and d.baslangic_tarihi and d.bitis_tarihi:
                return d.baslangic_tarihi, min(d.bitis_tarihi, bugun)
    except Exception as exc:
        _LOG.warning("Dönem tarihleri okunamadı: %s", exc)
    return bas, bit


class FiyatliStokEkstreService:
    @staticmethod
    def varsayilan_tarih_araligi() -> tuple[date, date]:
        return _aktif_donem_tarihleri()

    @staticmethod
    def maliyet_gorunsun_mu() -> bool:
        try:
            return maliyet_izinli() or oturum.role_kod == "YONETICI"
        except Exception:
            return True

    @staticmethod
    def _belge_cari_haritasi(session, hareketler: list) -> dict[tuple[str, str], dict]:
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri

        nos_sf, nos_af, nos_si, nos_ai = set(), set(), set(), set()
        for h in hareketler:
            bn = (h.belge_no or "").strip()
            if not bn:
                continue
            tur = h.hareket_turu or ""
            if tur == "FATURA ÇIKIŞ":
                nos_sf.add(bn)
                nos_ai.add(bn)
            elif tur == "FATURA GİRİŞ":
                nos_af.add(bn)
            elif tur == "İADE GİRİŞ":
                nos_si.add(bn)

        sonuc: dict[tuple[str, str], dict] = {}

        def _cari_bilgi(cari_id):
            if not cari_id:
                return None, None, None
            c = session.get(Cari, int(cari_id))
            if not c:
                return None, None, None
            return int(c.id), (c.cari_kodu or "").strip(), (c.unvan or "").strip()

        if nos_sf:
            for f in session.scalars(
                select(SatisFaturasi).where(SatisFaturasi.fatura_no.in_(nos_sf))
            ).all():
                if getattr(f, "is_deleted", False):
                    continue
                if (f.durum or "").upper() in ("TASLAK", "İPTAL", "IPTAL"):
                    continue
                cid, kod, ad = _cari_bilgi(f.cari_id)
                sonuc[("FATURA ÇIKIŞ", f.fatura_no)] = {
                    "belge_turu": "Satış Faturası",
                    "belge_id": int(f.id),
                    "belge_modul": "satis_fatura",
                    "cari_id": cid,
                    "cari_kodu": kod or "",
                    "cari_adi": ad or "",
                    "para_birimi": getattr(f, "para_birimi", None) or "TRY",
                    "kur": _d(getattr(f, "kur", 1) or 1),
                    "durum": f.durum,
                    "_fatura": f,
                }

        if nos_af:
            for f in session.scalars(
                select(AlisFaturasi).where(AlisFaturasi.fatura_no.in_(nos_af))
            ).all():
                if (f.durum or "").upper() in ("TASLAK", "İPTAL", "IPTAL"):
                    continue
                cid, kod, ad = _cari_bilgi(f.cari_id)
                sonuc[("FATURA GİRİŞ", f.fatura_no)] = {
                    "belge_turu": "Alış Faturası",
                    "belge_id": int(f.id),
                    "belge_modul": "alis_fatura",
                    "cari_id": cid,
                    "cari_kodu": kod or "",
                    "cari_adi": ad or "",
                    "para_birimi": getattr(f, "para_birimi", None) or "TRY",
                    "kur": _d(getattr(f, "kur", 1) or 1),
                    "durum": f.durum,
                    "_fatura": f,
                }

        if nos_si:
            for f in session.scalars(
                select(SatisIadeFaturasi).where(SatisIadeFaturasi.iade_no.in_(nos_si))
            ).all():
                cid, kod, ad = _cari_bilgi(f.cari_id)
                sonuc[("İADE GİRİŞ", f.iade_no)] = {
                    "belge_turu": "Satış İadesi",
                    "belge_id": int(f.id),
                    "belge_modul": "satis_iade",
                    "cari_id": cid,
                    "cari_kodu": kod or "",
                    "cari_adi": ad or "",
                    "para_birimi": getattr(f, "para_birimi", None) or "TRY",
                    "kur": _d(getattr(f, "kur", 1) or 1),
                    "durum": getattr(f, "durum", None),
                    "_fatura": f,
                }

        if nos_ai:
            for f in session.scalars(
                select(AlisIadeFaturasi).where(AlisIadeFaturasi.iade_no.in_(nos_ai))
            ).all():
                cid, kod, ad = _cari_bilgi(f.cari_id)
                key = ("FATURA ÇIKIŞ", f.iade_no)
                if key not in sonuc:
                    sonuc[key] = {
                        "belge_turu": "Alış İadesi",
                        "belge_id": int(f.id),
                        "belge_modul": "alis_iade",
                        "cari_id": cid,
                        "cari_kodu": kod or "",
                        "cari_adi": ad or "",
                        "para_birimi": getattr(f, "para_birimi", None) or "TRY",
                        "kur": _d(getattr(f, "kur", 1) or 1),
                        "durum": getattr(f, "durum", None),
                        "_fatura": f,
                    }

        for meta in sonuc.values():
            fat = meta.pop("_fatura", None)
            meta["_satirlar"] = list(getattr(fat, "satirlar", None) or []) if fat else []

        for _key, meta in list(sonuc.items()):
            if meta.get("_satirlar"):
                continue
            modul = meta.get("belge_modul")
            bid = meta.get("belge_id")
            if not bid:
                continue
            if modul == "satis_fatura":
                meta["_satirlar"] = list(
                    session.scalars(
                        select(SatisFaturasiSatiri).where(SatisFaturasiSatiri.fatura_id == bid)
                    ).all()
                )
            elif modul == "alis_fatura":
                meta["_satirlar"] = list(
                    session.scalars(
                        select(AlisFaturasiSatiri).where(AlisFaturasiSatiri.fatura_id == bid)
                    ).all()
                )
            elif modul == "satis_iade":
                meta["_satirlar"] = list(
                    session.scalars(
                        select(SatisIadeFaturasiSatiri).where(
                            SatisIadeFaturasiSatiri.iade_id == bid
                        )
                    ).all()
                )
            elif modul == "alis_iade":
                meta["_satirlar"] = list(
                    session.scalars(
                        select(AlisIadeFaturasiSatiri).where(AlisIadeFaturasiSatiri.iade_id == bid)
                    ).all()
                )

        return sonuc

    @staticmethod
    def _yon(tur: str) -> str:
        if tur in _EKSTRE_GIRIS:
            return "giris"
        if tur in _EKSTRE_CIKIS:
            return "cikis"
        return "notr"

    @staticmethod
    def ekstre(
        stok_id: int,
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        depo_adi: str | None = None,
        hareket_turu: str | None = None,
        cari_id: int | None = None,
        belge_turu: str | None = None,
        belge_no: str | None = None,
        para_birimi: str | None = None,
        gosterim_birimi: str | None = None,
        kdv_dahil: bool = False,
    ) -> dict[str, Any]:
        if not stok_id:
            raise ValueError("Stok seçilmedi.")
        if baslangic is None or bitis is None:
            vb, ve = _aktif_donem_tarihleri()
            baslangic = baslangic or vb
            bitis = bitis or ve
        if baslangic > bitis:
            raise ValueError("Başlangıç tarihi bitişten büyük olamaz.")

        maliyet_ok = FiyatliStokEkstreService.maliyet_gorunsun_mu()
        uyarilar: list[str] = []

        with get_session() as session:
            stok = session.get(StokKarti, int(stok_id))
            if stok is None or getattr(stok, "is_deleted", False):
                raise ValueError("Stok kartı bulunamadı veya silinmiş.")

            ana_birim = (stok.birim or "Adet").strip() or "Adet"
            gosterim = (gosterim_birimi or ana_birim).strip() or ana_birim
            birimler = StokService.birimleri_dict_listesi(stok)

            def miktar_goster(m: Decimal) -> Decimal:
                if gosterim.casefold() == ana_birim.casefold():
                    return _d(m)
                try:
                    o = StokService.birim_donusum_onizleme(
                        m, ana_birim, gosterim, birimler, ana_birim
                    )
                    return _d(o["hedef_miktar"])
                except Exception as exc:
                    uyarilar.append(f"Birim dönüşümü uyarısı: {exc}")
                    return _d(m)

            q = (
                select(StokHareketi, Depo.ad, StokLotu.lot_no)
                .join(Depo, Depo.id == StokHareketi.depo_id)
                .outerjoin(StokLotu, StokLotu.id == StokHareketi.lot_id)
                .where(StokHareketi.stok_id == int(stok_id))
            )
            if depo_adi and depo_adi not in ("", "(Tümü)", "Tüm Depolar"):
                q = q.where(Depo.ad == depo_adi)
            q = q.order_by(
                StokHareketi.tarih.asc(),
                StokHareketi.olusturma_tarihi.asc(),
                StokHareketi.id.asc(),
            )
            ham = list(session.execute(q).all())
            hareketler = [h for h, _, _ in ham]
            depo_map = {h.id: (d or "") for h, d, _ in ham}
            lot_map = {h.id: (l or "") for h, _, l in ham}

            belge_map = FiyatliStokEkstreService._belge_cari_haritasi(session, hareketler)
            stok_kodu = (stok.stok_kodu or "").strip()

            devir_miktar = Decimal("0")
            devir_deger = Decimal("0")
            for h in hareketler:
                if h.tarih >= baslangic:
                    break
                yon = FiyatliStokEkstreService._yon(h.hareket_turu)
                m = _d(h.miktar)
                c = _d(h.birim_maliyet)
                if yon == "giris":
                    devir_miktar += m
                    devir_deger += m * c
                elif yon == "cikis":
                    devir_miktar -= m
                    devir_deger -= m * c

            devir_birim = (devir_deger / devir_miktar) if devir_miktar != 0 else Decimal("0")

            satirlar: list[dict] = []
            satirlar.append(
                {
                    "satir_turu": "devri",
                    "hareket_id": None,
                    "tarih": baslangic,
                    "saat": "",
                    "hareket_turu": "DEVRİ",
                    "etiket": "Devir",
                    "belge_turu": "",
                    "belge_no": "",
                    "belge_modul": None,
                    "belge_id": None,
                    "cari_id": None,
                    "cari_kodu": "",
                    "cari_adi": "",
                    "depo": depo_adi
                    if depo_adi and depo_adi not in ("(Tümü)", "Tüm Depolar")
                    else "Tüm Depolar",
                    "lot_no": "",
                    "aciklama": f"Açılış bakiyesi ({baslangic.strftime('%d.%m.%Y')} öncesi)",
                    "giren": Decimal("0"),
                    "cikan": Decimal("0"),
                    "kalan": miktar_goster(devir_miktar),
                    "giris_birim_fiyat": None,
                    "cikis_satis_fiyat": None,
                    "cikis_maliyet_fiyat": (devir_birim if maliyet_ok else None),
                    "giris_tutari": None,
                    "cikis_tutari": None,
                    "cikis_maliyeti": None,
                    "kalan_deger": (devir_deger if maliyet_ok else None),
                    "para_birimi": "TRY",
                    "kur": Decimal("1"),
                    "doviz_birim_fiyat": None,
                    "yon": "devri",
                    "uyari": "",
                }
            )

            kalan_m = devir_miktar
            kalan_d = devir_deger
            toplam_giren = Decimal("0")
            toplam_cikan = Decimal("0")
            toplam_giris_tutar = Decimal("0")
            toplam_cikis_maliyet = Decimal("0")
            toplam_cikis_satis = Decimal("0")

            belge_filtre = (belge_no or "").strip().casefold()
            pb_filtre = (para_birimi or "").strip().upper()
            if pb_filtre in ("", "TÜMÜ", "TUMU", "(TÜMÜ)"):
                pb_filtre = ""

            for h in hareketler:
                if h.tarih < baslangic or h.tarih > bitis:
                    continue
                tur = h.hareket_turu or ""
                if hareket_turu and hareket_turu not in ("", "(Tümü)") and tur != hareket_turu:
                    continue
                bn = (h.belge_no or "").strip()
                if belge_filtre and belge_filtre not in bn.casefold():
                    continue

                meta = belge_map.get((tur, bn), {})
                if belge_turu and belge_turu not in ("", "(Tümü)"):
                    bt = meta.get("belge_turu") or ""
                    if belge_turu == "Transfer" and "TRANSFER" not in tur:
                        continue
                    if belge_turu == "Sayım" and "SAYIM" not in tur:
                        continue
                    if belge_turu not in ("Transfer", "Sayım") and bt != belge_turu:
                        continue

                if cari_id and meta.get("cari_id") != int(cari_id):
                    continue
                if pb_filtre and (meta.get("para_birimi") or "TRY").upper() != pb_filtre:
                    continue

                yon = FiyatliStokEkstreService._yon(tur)
                m = _d(h.miktar)
                maliyet = _d(h.birim_maliyet)
                uyari = ""

                satir_orm = None
                for s in meta.get("_satirlar") or []:
                    if (getattr(s, "urun_kodu", None) or "").strip() == stok_kodu:
                        satir_orm = s
                        break
                ticari = _net_birim(satir_orm) if satir_orm else None
                if kdv_dahil and ticari is not None and satir_orm is not None:
                    kdv = _d(getattr(satir_orm, "kdv_orani", 0) or 0)
                    ticari = ticari * (Decimal("1") + kdv / Decimal("100"))

                giren = m if yon == "giris" else Decimal("0")
                cikan = m if yon == "cikis" else Decimal("0")
                kalan_m = kalan_m + giren - cikan

                giris_bf = None
                cikis_sf = None
                cikis_mf = None
                giris_t = None
                cikis_t = None
                cikis_mal_t = None

                if yon == "giris":
                    giris_bf = ticari if ticari is not None else maliyet
                    if maliyet_ok:
                        giris_t = giren * maliyet
                        kalan_d += giren * maliyet
                        toplam_giris_tutar += giren * maliyet
                elif yon == "cikis":
                    cikis_sf = ticari
                    if maliyet_ok:
                        if maliyet == 0 and tur in ("FATURA ÇIKIŞ", "İRSALİYE ÇIKIŞ"):
                            uyari = (
                                "FIFO/maliyet verisi eksik; satış fiyatı maliyet olarak kullanılmadı."
                            )
                            uyarilar.append(f"{bn}: {uyari}")
                        else:
                            cikis_mf = maliyet
                            cikis_mal_t = cikan * maliyet
                            kalan_d -= cikan * maliyet
                            toplam_cikis_maliyet += cikan * maliyet
                    if cikis_sf is not None:
                        cikis_t = cikan * cikis_sf
                        toplam_cikis_satis += cikis_t
                else:
                    uyari = "Yön belirsiz hareket; miktar kalan hesabına dahil edilmedi."
                    uyarilar.append(f"{bn}/{tur}: {uyari}")

                toplam_giren += giren
                toplam_cikan += cikan

                cari_kodu = meta.get("cari_kodu") or ""
                cari_adi = meta.get("cari_adi") or ""
                if tur in _CARI_YOK_TUR and not cari_adi:
                    if "TRANSFER" in tur:
                        cari_adi = "Depo transferi"
                    elif "SAYIM" in tur:
                        cari_adi = "Sayım düzeltmesi"
                    elif tur in ("GİRİŞ", "ÇIKIŞ"):
                        cari_adi = "Manuel stok fişi"
                    elif "PAKET" in tur:
                        cari_adi = "Paket üretimi"

                saat = ""
                if h.olusturma_tarihi:
                    try:
                        saat = h.olusturma_tarihi.strftime("%H:%M:%S")
                    except Exception:
                        saat = ""

                satirlar.append(
                    {
                        "satir_turu": "hareket",
                        "hareket_id": int(h.id),
                        "tarih": h.tarih,
                        "saat": saat,
                        "hareket_turu": tur,
                        "etiket": _ETIKET.get(tur, ""),
                        "belge_turu": meta.get("belge_turu")
                        or (
                            "Transfer"
                            if "TRANSFER" in tur
                            else "Sayım"
                            if "SAYIM" in tur
                            else "Stok Fişi"
                            if tur in ("GİRİŞ", "ÇIKIŞ")
                            else ""
                        ),
                        "belge_no": bn,
                        "belge_modul": meta.get("belge_modul"),
                        "belge_id": meta.get("belge_id"),
                        "cari_id": meta.get("cari_id"),
                        "cari_kodu": cari_kodu,
                        "cari_adi": cari_adi,
                        "depo": depo_map.get(h.id, ""),
                        "lot_no": lot_map.get(h.id, ""),
                        "aciklama": "",
                        "giren": miktar_goster(giren) if giren else Decimal("0"),
                        "cikan": miktar_goster(cikan) if cikan else Decimal("0"),
                        "kalan": miktar_goster(kalan_m),
                        "giris_birim_fiyat": giris_bf,
                        "cikis_satis_fiyat": cikis_sf,
                        "cikis_maliyet_fiyat": cikis_mf if maliyet_ok else None,
                        "giris_tutari": giris_t if maliyet_ok else None,
                        "cikis_tutari": cikis_t,
                        "cikis_maliyeti": cikis_mal_t if maliyet_ok else None,
                        "kalan_deger": (kalan_d if maliyet_ok else None),
                        "para_birimi": meta.get("para_birimi") or "TRY",
                        "kur": meta.get("kur") or Decimal("1"),
                        "doviz_birim_fiyat": (
                            _d(getattr(satir_orm, "birim_fiyat_doviz", 0))
                            if satir_orm and getattr(satir_orm, "birim_fiyat_doviz", None)
                            else None
                        ),
                        "yon": yon,
                        "uyari": uyari,
                    }
                )

            lot_q = select(StokLotu).where(StokLotu.stok_id == stok.id)
            if depo_adi and depo_adi not in ("", "(Tümü)", "Tüm Depolar"):
                lot_q = lot_q.join(Depo, Depo.id == StokLotu.depo_id).where(Depo.ad == depo_adi)
            lotlar = list(session.scalars(lot_q).all())
            fifo_kalan = sum((_d(l.kalan_miktar) for l in lotlar), Decimal("0"))
            fifo_deger = sum(
                (_d(l.kalan_miktar) * _d(l.birim_maliyet) for l in lotlar), Decimal("0")
            )

            return {
                "stok_id": int(stok.id),
                "stok_kodu": stok.stok_kodu,
                "stok_adi": stok.stok_adi,
                "ana_birim": ana_birim,
                "gosterim_birimi": gosterim,
                "baslangic": baslangic,
                "bitis": bitis,
                "depo": depo_adi or "Tüm Depolar",
                "maliyet_yontemi": "FIFO",
                "maliyet_gorunur": maliyet_ok,
                "kdv_dahil": bool(kdv_dahil),
                "ozet": {
                    "devir_miktar": miktar_goster(devir_miktar),
                    "giren_miktar": miktar_goster(toplam_giren),
                    "cikan_miktar": miktar_goster(toplam_cikan),
                    "kalan_miktar": miktar_goster(kalan_m),
                    "devir_degeri": (devir_deger if maliyet_ok else None),
                    "giris_tutari": (toplam_giris_tutar if maliyet_ok else None),
                    "cikis_maliyeti": (toplam_cikis_maliyet if maliyet_ok else None),
                    "cikis_satis_tutari": toplam_cikis_satis,
                    "kalan_stok_degeri": (kalan_d if maliyet_ok else None),
                    "fifo_lot_miktar": miktar_goster(fifo_kalan) if maliyet_ok else None,
                    "fifo_lot_deger": (fifo_deger if maliyet_ok else None),
                },
                "satirlar": satirlar,
                "uyarilar": list(dict.fromkeys(uyarilar)),
                "firma_kodu": getattr(oturum, "firma_kodu", None),
                "uretim_zamani": datetime.now(),
            }

    @staticmethod
    def excel_aktar(sonuc: dict, yol: str) -> str:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Fiyatlı Stok Ekstresi"
        ozet = sonuc.get("ozet") or {}
        ws.append(["Fiyatlı Stok Ekstresi"])
        ws.append([f"Stok: {sonuc.get('stok_kodu')} — {sonuc.get('stok_adi')}"])
        ws.append(
            [
                f"Tarih: {sonuc.get('baslangic')} – {sonuc.get('bitis')} | Depo: {sonuc.get('depo')} | "
                f"Maliyet: {sonuc.get('maliyet_yontemi')}"
            ]
        )
        ws.append(
            [
                "Devir",
                float(ozet.get("devir_miktar") or 0),
                "Giren",
                float(ozet.get("giren_miktar") or 0),
                "Çıkan",
                float(ozet.get("cikan_miktar") or 0),
                "Kalan",
                float(ozet.get("kalan_miktar") or 0),
            ]
        )
        if sonuc.get("maliyet_gorunur"):
            ws.append(
                [
                    "Devir Değeri",
                    float(ozet.get("devir_degeri") or 0),
                    "Giriş Tutarı",
                    float(ozet.get("giris_tutari") or 0),
                    "Çıkış Maliyeti",
                    float(ozet.get("cikis_maliyeti") or 0),
                    "Kalan Değer",
                    float(ozet.get("kalan_stok_degeri") or 0),
                ]
            )
        ws.append([])
        basliklar = [
            "Tarih",
            "Saat",
            "Hareket",
            "Belge Türü",
            "Belge No",
            "Cari Kodu",
            "Cari Kart Adı",
            "Depo",
            "Giren",
            "Çıkan",
            "Kalan",
            "Giriş Birim Fiyatı",
            "Çıkış Satış Fiyatı",
            "Çıkış Maliyet Fiyatı",
            "Giriş Tutarı",
            "Çıkış Tutarı",
            "Çıkış Maliyeti",
            "Kalan Değer",
            "Para Birimi",
            "Kur",
            "Uyarı",
        ]
        ws.append(basliklar)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for s in sonuc.get("satirlar") or []:
            t = s.get("tarih")
            ws.append(
                [
                    t.strftime("%d.%m.%Y") if hasattr(t, "strftime") else str(t or ""),
                    s.get("saat") or "",
                    s.get("hareket_turu") or "",
                    s.get("belge_turu") or "",
                    s.get("belge_no") or "",
                    s.get("cari_kodu") or "",
                    s.get("cari_adi") or "",
                    s.get("depo") or "",
                    float(s.get("giren") or 0),
                    float(s.get("cikan") or 0),
                    float(s.get("kalan") or 0),
                    float(s["giris_birim_fiyat"]) if s.get("giris_birim_fiyat") is not None else None,
                    float(s["cikis_satis_fiyat"]) if s.get("cikis_satis_fiyat") is not None else None,
                    float(s["cikis_maliyet_fiyat"])
                    if s.get("cikis_maliyet_fiyat") is not None
                    else None,
                    float(s["giris_tutari"]) if s.get("giris_tutari") is not None else None,
                    float(s["cikis_tutari"]) if s.get("cikis_tutari") is not None else None,
                    float(s["cikis_maliyeti"]) if s.get("cikis_maliyeti") is not None else None,
                    float(s["kalan_deger"]) if s.get("kalan_deger") is not None else None,
                    s.get("para_birimi") or "",
                    float(s.get("kur") or 1),
                    s.get("uyari") or "",
                ]
            )
        wb.save(yol)
        return yol

    @staticmethod
    def pdf_aktar(sonuc: dict, yol: str) -> str:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError:
            with open(yol, "w", encoding="utf-8") as f:
                f.write("Fiyatlı Stok Ekstresi\n")
                f.write(f"{sonuc.get('stok_kodu')} {sonuc.get('stok_adi')}\n")
                for s in sonuc.get("satirlar") or []:
                    f.write(
                        f"{s.get('tarih')}\t{s.get('hareket_turu')}\t{s.get('belge_no')}\t"
                        f"{s.get('cari_adi')}\t{s.get('giren')}\t{s.get('cikan')}\t{s.get('kalan')}\n"
                    )
            return yol

        doc = SimpleDocTemplate(
            yol,
            pagesize=landscape(A4),
            leftMargin=18,
            rightMargin=18,
            topMargin=24,
            bottomMargin=24,
        )
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph("Fiyatlı Stok Ekstresi", styles["Title"]))
        story.append(
            Paragraph(
                f"{sonuc.get('stok_kodu')} — {sonuc.get('stok_adi')} | "
                f"{sonuc.get('baslangic')} – {sonuc.get('bitis')} | Depo: {sonuc.get('depo')} | "
                f"Maliyet: {sonuc.get('maliyet_yontemi')}",
                styles["Normal"],
            )
        )
        ozet = sonuc.get("ozet") or {}
        story.append(
            Paragraph(
                f"Devir: {ozet.get('devir_miktar')} | Giren: {ozet.get('giren_miktar')} | "
                f"Çıkan: {ozet.get('cikan_miktar')} | Kalan: {ozet.get('kalan_miktar')}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 8))
        data = [
            [
                "Tarih",
                "Hareket",
                "Belge",
                "Cari",
                "Giren",
                "Çıkan",
                "Kalan",
                "G.Fiyat",
                "Ç.Satış",
                "Ç.Maliyet",
                "Kalan Değ.",
            ]
        ]
        for s in sonuc.get("satirlar") or []:
            t = s.get("tarih")
            data.append(
                [
                    t.strftime("%d.%m.%Y") if hasattr(t, "strftime") else "",
                    (s.get("hareket_turu") or "")[:14],
                    (s.get("belge_no") or "")[:12],
                    (s.get("cari_adi") or "")[:18],
                    f"{s.get('giren') or 0}",
                    f"{s.get('cikan') or 0}",
                    f"{s.get('kalan') or 0}",
                    f"{s.get('giris_birim_fiyat') or ''}",
                    f"{s.get('cikis_satis_fiyat') or ''}",
                    f"{s.get('cikis_maliyet_fiyat') or ''}",
                    f"{s.get('kalan_deger') or ''}",
                ]
            )
        tab = Table(data, repeatRows=1)
        tab.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                ]
            )
        )
        story.append(tab)
        doc.build(story)
        return yol
