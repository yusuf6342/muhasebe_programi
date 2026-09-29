"""Fatura / evrak ödeme ve kapatma izleme — mevcut açık kalem altyapısının salt okunur görünümü.

Tek kaynak: ``cari_satis_hareketleri`` (açık kalem) + ``cari_kapatmalar`` (tahsis kayıtları).
Eski (kayıtsız) akışlardan kalan paylar tahmin edilmez: faturaya bağlı makbuz bağı ve fatura içi
tahsilat gibi kayıtlı ilişkiler gösterilir, açıklanamayan kısım "Tarihsel eşleştirme bilinmiyor"
olarak ayrı satırda kalır. Tutarsızlık sessizce düzeltilmez; uyarı ve tanı raporuna yazılır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from database.acik_kalem_service import (
    GECIS_DEVIR_ONEKI,
    TOLERANS,
    AcikKalemService,
    _d,
    _kurus,
    odeme_durumu,
    para_anahtari,
)
from database.database import get_session
from database.models.cari import CariIslem, CariKapatma, SatisHareketi

log = logging.getLogger("muhasebe.kapatma_tani")

BILINMIYOR = "Tarihsel eşleştirme bilinmiyor"
MESAJ_TASLAK = "Henüz cari borç oluşmadı"
MESAJ_KAYIT_YOK = "Bu evraka bağlı kapatma kaydı yok"
MESAJ_AVANS = "Açık kaleme bağlanmadı / Avans"

KAYNAK_TUR_ADLARI = {
    "TAHSILAT": "Tahsilat",
    "ODEME": "Ödeme",
    "IADE": "İade",
    "VIRMAN": "Virman",
    "AVANS": "Avans kullanımı",
    "DEVIR": "Devir",
    "KK_CEKIMI": "KK çekimi (mahsup)",
    "GELIR_KAPAMA": "Dekont (mahsup)",
    "GIDER": "Dekont (mahsup)",
}


def _tur_adi(kayit: CariKapatma) -> str:
    if kayit.kaynak_hareket_id:
        return "Avans kullanımı"
    return KAYNAK_TUR_ADLARI.get((kayit.kaynak_tur or "").upper(), kayit.kaynak_tur or "")


def _yontem_adi(kayit: CariKapatma, kismi: bool) -> str:
    y = (kayit.yontem or "").upper()
    ad = {"MANUEL": "Manuel", "FIFO": "FIFO"}.get(y, y.title())
    return f"{ad} (kısmi)" if kismi else ad


def _bag_tablosu_var(session) -> bool:
    from database.finans_service import FinansService

    try:
        return FinansService._bag_tablosu_var(session)
    except Exception:
        return False


def _evrak_bilgisi(session, cari_id: int | None, belge_no: str) -> dict[str, Any]:
    """Kaynak evrakın türü, toplamı, hesabı ve açma bilgisi (bulunamazsa boş alanlar)."""
    from database.models.finans import CariVirmanMakbuzu, KasaMakbuzu

    bilgi: dict[str, Any] = {
        "evrak_turu": "",
        "toplam": None,
        "hesap": "",
        "para_birimi": "TRY",
        "tarih": None,
        "ac_tur": "",
        "makbuz_id": None,
        "durum": "",
    }
    if not belge_no:
        return bilgi
    makbuz = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == belge_no))
    if makbuz is not None:
        bilgi.update(
            evrak_turu="Tahsilat Makbuzu" if makbuz.makbuz_turu == "TAHSILAT" else "Ödeme Makbuzu",
            toplam=_kurus(makbuz.tutar),
            tarih=makbuz.tarih,
            makbuz_id=int(makbuz.id),
            ac_tur="Tahsilat Makbuzu" if makbuz.makbuz_turu == "TAHSILAT" else "Ödeme Makbuzu",
            durum=makbuz.durum or "",
            evrak_no_goster=(makbuz.makbuz_no or "").strip() or belge_no,
        )
        try:
            bilgi["hesap"] = makbuz.finans_hesap.hesap_adi if makbuz.finans_hesap else ""
        except Exception:
            bilgi["hesap"] = ""
    else:
        virman = session.scalar(
            select(CariVirmanMakbuzu).where(
                (CariVirmanMakbuzu.tahsilat_belge_no == belge_no)
                | (CariVirmanMakbuzu.odeme_belge_no == belge_no)
            )
        )
        if virman is not None:
            bilgi.update(
                evrak_turu="Cari Virman Makbuzu",
                toplam=_kurus(virman.tutar),
                tarih=virman.tarih,
                ac_tur="Cari Virman",
                evrak_no_goster=(virman.makbuz_no or "").strip() or belge_no,
            )
    if not bilgi["evrak_turu"]:
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.models.satis_iade_faturasi import SatisIadeFaturasi

        iade = session.scalar(select(SatisIadeFaturasi).where(SatisIadeFaturasi.iade_no == belge_no))
        if iade is not None:
            bilgi.update(evrak_turu="Satış İade Faturası", tarih=iade.iade_tarihi, ac_tur="Satış İadesi",
                         durum=iade.durum or "")
        else:
            aiade = session.scalar(select(AlisIadeFaturasi).where(AlisIadeFaturasi.iade_no == belge_no))
            if aiade is not None:
                bilgi.update(evrak_turu="Alış İade Faturası", tarih=aiade.iade_tarihi, ac_tur="Alış İadesi",
                             durum=aiade.durum or "")
    sorgu = select(CariIslem).where(CariIslem.belge_no == belge_no)
    if cari_id is not None:
        sorgu = sorgu.where(CariIslem.cari_id == int(cari_id))
    islemler = list(session.scalars(sorgu).all())
    if islemler:
        if bilgi["toplam"] is None:
            bilgi["toplam"] = _kurus(
                sum((_d(i.alacak) + _d(i.borc) for i in islemler), Decimal("0"))
            )
        if not bilgi["hesap"]:
            bilgi["hesap"] = next((i.hesap_adi for i in islemler if i.hesap_adi), "") or ""
        if bilgi["tarih"] is None:
            bilgi["tarih"] = islemler[0].tarih
        bilgi["para_birimi"] = (islemler[0].para_birimi or "TRY").upper()
        if not bilgi["evrak_turu"]:
            tur = islemler[0].islem_turu or ""
            bilgi["evrak_turu"] = "Devir" if tur == "Açılış" else tur
            bilgi["ac_tur"] = tur
    if not bilgi["evrak_turu"] and belge_no.startswith(GECIS_DEVIR_ONEKI):
        bilgi["evrak_turu"] = "Geçiş Devir Farkı"
        bilgi["hesap"] = "Gerçek fatura/tahsilat değildir"
    bilgi.setdefault("evrak_no_goster", belge_no)
    return bilgi


def gecis_devir_aciklamasi(session, belge_no: str) -> str:
    """DVF- kalemi için geçişte yazılan açıklama (kayıt yoksa genel açıklama)."""
    genel = "Geçiş Devir Farkı: veri geçişinde eşleştirilemeyen net fark. Gerçek fatura veya tahsilat değildir."
    try:
        from sqlalchemy import inspect as sa_inspect

        from database.models.acik_kalem_gecis import AcikKalemGecisKaydi

        if not sa_inspect(session.connection()).has_table(AcikKalemGecisKaydi.__tablename__):
            return genel
        kayit = session.scalar(select(AcikKalemGecisKaydi).where(AcikKalemGecisKaydi.belge_no == belge_no))
    except Exception:
        return genel
    if kayit is None:
        return genel
    return f"Geçiş Devir Farkı ({kayit.tarih:%d.%m.%Y}): {kayit.aciklama}"


def _hedef_esas(session, hareket: SatisHareketi, aktif_toplam: Decimal) -> Decimal:
    esas = _kurus(hareket.satis_tutari)
    if esas > 0:
        return esas
    return _kurus(max(_d(hareket.kalan_acik_tutar), Decimal("0")) + aktif_toplam)


def _aktif_kayitlar(session, hedef_id: int) -> list[CariKapatma]:
    if not AcikKalemService._tablo_var(session):
        return []
    return list(
        session.scalars(
            select(CariKapatma)
            .where(CariKapatma.hedef_hareket_id == int(hedef_id), CariKapatma.iptal.is_(False))
            .order_by(CariKapatma.tarih, CariKapatma.id)
        ).all()
    )


def _iptal_satiri(kayit: CariKapatma, *, evrak_no: str, evrak_turu: str) -> dict[str, Any]:
    return {
        "kayit_id": int(kayit.id),
        "islem_tarihi": kayit.tarih,
        "iptal_zamani": kayit.iptal_zamani,
        "kullanici": kayit.iptal_kullanici or "",
        "neden": kayit.iptal_nedeni or "",
        "evrak_no": evrak_no,
        "evrak_turu": evrak_turu,
        "tutar": _kurus(kayit.tutar),
        "para_birimi": kayit.para_birimi or "TRY",
        "tur": _tur_adi(kayit),
    }


def _fatura_bul(session, cari_id: int | None, belge_no: str):
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.satis_faturasi import SatisFaturasi

    sorgu = select(SatisFaturasi).where(SatisFaturasi.fatura_no == belge_no)
    if cari_id is not None:
        sorgu = sorgu.where(SatisFaturasi.cari_id == int(cari_id))
    satis = session.scalar(sorgu)
    if satis is not None:
        return "SATIS", satis
    sorgu = select(AlisFaturasi).where(AlisFaturasi.fatura_no == belge_no)
    if cari_id is not None:
        sorgu = sorgu.where(AlisFaturasi.cari_id == int(cari_id))
    alis = session.scalar(sorgu)
    if alis is not None:
        return "ALIS", alis
    return None, None


def _tani_yaz(belge_no: str, mesaj: str) -> None:
    log.warning("Kapatma tutarsızlığı %s: %s", belge_no, mesaj)


def evrak_kapatma_detayi_oturum(session, belge_no: str, cari_id: int | None = None) -> dict[str, Any]:
    """Borç (veya alacak) doğuran evrakın ödeme / kapatma ayrıntısı ve kaynak olarak kapattıkları."""
    belge_no = (belge_no or "").strip()
    sonuc: dict[str, Any] = {
        "belge_no": belge_no,
        "cari_id": cari_id,
        "evrak_turu": "",
        "mesaj": None,
        "taslak": False,
        "iptal": False,
        "esas_tutar": Decimal("0"),
        "kapanan": Decimal("0"),
        "kalan": Decimal("0"),
        "para_birimi": "TRY",
        "odeme_durumu": "",
        "kapatanlar": [],
        "iptaller": [],
        "tutarli": True,
        "uyari": None,
        "kaynak": None,
    }
    if not belge_no:
        sonuc["mesaj"] = MESAJ_KAYIT_YOK
        return sonuc

    tur, fatura = _fatura_bul(session, cari_id, belge_no)
    if fatura is not None:
        cari_id = int(fatura.cari_id)
        sonuc["cari_id"] = cari_id
        sonuc["evrak_turu"] = "Satış Faturası" if tur == "SATIS" else "Alış Faturası"
        if (fatura.durum or "") == "İPTAL":
            sonuc["iptal"] = True
        elif tur == "SATIS" and not getattr(fatura, "onaylandi", False):
            sonuc["taslak"] = True
            sonuc["mesaj"] = MESAJ_TASLAK

    sorgu = select(SatisHareketi).where(
        SatisHareketi.belge_no == belge_no, SatisHareketi.satis_tutari > 0
    )
    if cari_id is not None:
        sorgu = sorgu.where(SatisHareketi.cari_id == int(cari_id))
    hareket = session.scalar(sorgu.order_by(SatisHareketi.id))
    if hareket is None and belge_no.startswith(GECIS_DEVIR_ONEKI):
        sorgu = select(SatisHareketi).where(SatisHareketi.belge_no == belge_no)
        if cari_id is not None:
            sorgu = sorgu.where(SatisHareketi.cari_id == int(cari_id))
        hareket = session.scalar(sorgu.where(SatisHareketi.kalan_acik_tutar > 0))

    if hareket is not None and not sonuc["taslak"]:
        cari_id = int(hareket.cari_id)
        sonuc["cari_id"] = cari_id
        if not sonuc["evrak_turu"]:
            sonuc["evrak_turu"] = AcikKalemService._evrak_turu(session, hareket)
        aktif = _aktif_kayitlar(session, int(hareket.id))
        aktif_toplam = sum((_d(k.tutar) for k in aktif), Decimal("0"))
        esas = _hedef_esas(session, hareket, aktif_toplam)
        kalan = max(_kurus(hareket.kalan_acik_tutar), Decimal("0"))
        kapanan = _kurus(esas - kalan)
        sonuc.update(
            esas_tutar=esas,
            kalan=kalan,
            kapanan=kapanan,
            para_birimi=para_anahtari(hareket),
            odeme_durumu=odeme_durumu(esas, kapanan),
        )
        kapatanlar = []
        belge_payi: dict[str, Decimal] = {}
        for k in aktif:
            bilgi = _evrak_bilgisi(session, cari_id, k.kaynak_belge_no)
            belge_payi[k.kaynak_belge_no] = belge_payi.get(k.kaynak_belge_no, Decimal("0")) + _d(k.tutar)
            kapatanlar.append(
                {
                    "kaynak": "KAYIT",
                    "kayit_id": int(k.id),
                    "tarih": k.tarih,
                    "evrak_turu": bilgi["evrak_turu"] or _tur_adi(k),
                    "evrak_no": bilgi.get("evrak_no_goster") or k.kaynak_belge_no,
                    "belge_no": k.kaynak_belge_no,
                    "pay": _kurus(k.tutar),
                    "evrak_toplami": bilgi["toplam"],
                    "para_birimi": k.para_birimi or "TRY",
                    "hesap": bilgi["hesap"],
                    "tur": _tur_adi(k),
                    "yontem": _yontem_adi(k, bilgi["toplam"] is not None and _d(k.tutar) < _d(bilgi["toplam"]) - TOLERANS),
                    "kullanici": k.kullanici_adi or "",
                    "ac_tur": bilgi["ac_tur"],
                    "makbuz_id": bilgi["makbuz_id"],
                    "durum": "",
                }
            )
        if tur == "SATIS" and fatura is not None:
            kapatanlar.extend(_fatura_eski_paylari(session, fatura, belge_payi))
        aciklanan = sum((r["pay"] for r in kapatanlar), Decimal("0"))
        bilinmeyen = _kurus(kapanan - aciklanan)
        if bilinmeyen > TOLERANS:
            kapatanlar.append(
                {
                    "kaynak": "BILINMIYOR",
                    "kayit_id": None,
                    "tarih": None,
                    "evrak_turu": BILINMIYOR,
                    "evrak_no": "",
                    "belge_no": "",
                    "pay": bilinmeyen,
                    "evrak_toplami": None,
                    "para_birimi": sonuc["para_birimi"],
                    "hesap": "",
                    "tur": BILINMIYOR,
                    "yontem": "",
                    "kullanici": "",
                    "ac_tur": "",
                    "makbuz_id": None,
                    "durum": "",
                }
            )
        elif bilinmeyen < -TOLERANS:
            sonuc["tutarli"] = False
            sonuc["uyari"] = (
                f"Kapatma payları toplamı ({_kurus(aciklanan)}) + kalan ({kalan}) evrak tutarını "
                f"({esas}) aşıyor. Kayıtlar otomatik düzeltilmedi; tanı raporuna yazıldı."
            )
            _tani_yaz(belge_no, sonuc["uyari"])
        sonuc["kapatanlar"] = kapatanlar
        if belge_no.startswith(GECIS_DEVIR_ONEKI):
            sonuc["mesaj"] = gecis_devir_aciklamasi(session, belge_no)
        if not kapatanlar and not sonuc["mesaj"]:
            sonuc["mesaj"] = MESAJ_KAYIT_YOK
        if AcikKalemService._tablo_var(session):
            for k in session.scalars(
                select(CariKapatma)
                .where(CariKapatma.hedef_hareket_id == int(hareket.id), CariKapatma.iptal.is_(True))
                .order_by(CariKapatma.iptal_zamani, CariKapatma.id)
            ).all():
                bilgi = _evrak_bilgisi(session, cari_id, k.kaynak_belge_no)
                sonuc["iptaller"].append(
                    _iptal_satiri(
                        k,
                        evrak_no=bilgi.get("evrak_no_goster") or k.kaynak_belge_no,
                        evrak_turu=bilgi["evrak_turu"] or _tur_adi(k),
                    )
                )
    elif not sonuc["taslak"] and not sonuc["mesaj"]:
        sonuc["mesaj"] = MESAJ_KAYIT_YOK if not sonuc["iptal"] else "Evrak iptal edildi; cari borç yok."

    if sonuc["taslak"] and fatura is not None:
        from database.satis_faturasi_service import SatisFaturasiService

        try:
            sonuc["esas_tutar"] = _kurus(SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"])
        except Exception:
            sonuc["esas_tutar"] = Decimal("0")
        sonuc["kalan"] = sonuc["esas_tutar"]

    if cari_id is not None:
        kaynak = kaynak_dagitim_detayi_oturum(session, belge_no, cari_id)
        if kaynak["satirlar"] or kaynak["avans_kalan"] > 0 or kaynak["iptaller"]:
            sonuc["kaynak"] = kaynak
            if sonuc["mesaj"] == MESAJ_KAYIT_YOK and hareket is None:
                sonuc["mesaj"] = None
    if belge_no.startswith(GECIS_DEVIR_ONEKI):
        sonuc["mesaj"] = gecis_devir_aciklamasi(session, belge_no)
    return sonuc


def _fatura_eski_paylari(session, fatura, belge_payi: dict[str, Decimal]) -> list[dict[str, Any]]:
    """Kayıtlı ilişkiler: faturaya bağlı makbuzun kayıtsız payı ve fatura içi tahsilatlar."""
    satirlar: list[dict[str, Any]] = []
    if _bag_tablosu_var(session):
        from database.models.finans import KasaMakbuzu, SatisFaturaMakbuzBagi

        for bag in session.scalars(
            select(SatisFaturaMakbuzBagi)
            .where(SatisFaturaMakbuzBagi.fatura_id == fatura.id)
            .order_by(SatisFaturaMakbuzBagi.id)
        ).all():
            makbuz = session.get(KasaMakbuzu, int(bag.makbuz_id))
            if makbuz is None or (makbuz.durum or "") == "IPTAL":
                continue
            eski = _kurus(_d(bag.fatura_kapanan) - belge_payi.get(makbuz.belge_no, Decimal("0")))
            if eski <= TOLERANS:
                continue
            hesap = ""
            try:
                hesap = makbuz.finans_hesap.hesap_adi if makbuz.finans_hesap else ""
            except Exception:
                pass
            satirlar.append(
                {
                    "kaynak": "BAGLI_MAKBUZ",
                    "kayit_id": None,
                    "tarih": makbuz.tarih,
                    "evrak_turu": "Tahsilat Makbuzu (faturaya bağlı)",
                    "evrak_no": (makbuz.makbuz_no or "").strip() or makbuz.belge_no,
                    "belge_no": makbuz.belge_no,
                    "pay": eski,
                    "evrak_toplami": _kurus(makbuz.tutar),
                    "para_birimi": "TRY",
                    "hesap": hesap,
                    "tur": "Tahsilat",
                    "yontem": "Bağlı makbuz",
                    "kullanici": "",
                    "ac_tur": "Tahsilat Makbuzu",
                    "makbuz_id": int(makbuz.id),
                    "durum": "",
                }
            )
    for th in getattr(fatura, "tahsilatlar", None) or []:
        tutar = _kurus(th.tutar)
        if tutar <= 0:
            continue
        satirlar.append(
            {
                "kaynak": "FATURA_ICI",
                "kayit_id": None,
                "tarih": th.tahsilat_tarihi,
                "evrak_turu": f"Fatura içi tahsilat ({th.odeme_sekli})",
                "evrak_no": fatura.fatura_no,
                "belge_no": fatura.fatura_no,
                "pay": tutar,
                "evrak_toplami": tutar,
                "para_birimi": "TRY",
                "hesap": th.hesap or "",
                "tur": "Tahsilat",
                "yontem": "Fatura içi",
                "kullanici": "",
                "ac_tur": "",
                "makbuz_id": None,
                "durum": "",
            }
        )
    return satirlar


def kaynak_dagitim_detayi_oturum(session, belge_no: str, cari_id: int) -> dict[str, Any]:
    """Tahsilat / ödeme / iade / virman evrakının kapattığı borç-alacaklar ve kullanılmamış avansı."""
    bilgi = _evrak_bilgisi(session, cari_id, belge_no)
    satirlar: list[dict[str, Any]] = []
    iptaller: list[dict[str, Any]] = []
    if AcikKalemService._tablo_var(session):
        kayitlar = list(
            session.scalars(
                select(CariKapatma)
                .where(CariKapatma.cari_id == int(cari_id), CariKapatma.kaynak_belge_no == belge_no)
                .order_by(CariKapatma.id)
            ).all()
        )
    else:
        kayitlar = []
    hedef_cache: dict[int, dict[str, Any]] = {}
    for k in kayitlar:
        if k.iptal:
            iptaller.append(_iptal_satiri(k, evrak_no=k.hedef_belge_no, evrak_turu=""))
            continue
        hid = int(k.hedef_hareket_id)
        if hid not in hedef_cache:
            h = session.get(SatisHareketi, hid)
            if h is None:
                hedef_cache[hid] = {"hareket": None, "esas": None, "eski": Decimal("0"), "tur": "Kaldırılmış kalem",
                                    "tarih": None}
            else:
                aktif = _aktif_kayitlar(session, hid)
                aktif_toplam = sum((_d(x.tutar) for x in aktif), Decimal("0"))
                esas = _hedef_esas(session, h, aktif_toplam)
                eski = max(
                    _kurus(esas - max(_d(h.kalan_acik_tutar), Decimal("0")) - aktif_toplam), Decimal("0")
                )
                hedef_cache[hid] = {
                    "hareket": h,
                    "esas": esas,
                    "eski": eski,
                    "tur": AcikKalemService._evrak_turu(session, h),
                    "tarih": h.satis_tarihi,
                    "aktif": aktif,
                }
        hc = hedef_cache[hid]
        sonrasi = None
        if hc["esas"] is not None:
            kumulatif = sum(
                (_d(x.tutar) for x in hc.get("aktif", []) if int(x.id) <= int(k.id)), Decimal("0")
            )
            sonrasi = max(_kurus(hc["esas"] - hc["eski"] - kumulatif), Decimal("0"))
        satirlar.append(
            {
                "kaynak": "KAYIT",
                "kayit_id": int(k.id),
                "tarih": k.tarih,
                "evrak_turu": hc["tur"],
                "evrak_no": k.hedef_belge_no,
                "evrak_tarihi": hc["tarih"],
                "ilk_tutar": hc["esas"],
                "kapatilan": _kurus(k.tutar),
                "sonrasi_kalan": sonrasi,
                "para_birimi": k.para_birimi or "TRY",
                "tur": _tur_adi(k),
                "yontem": _yontem_adi(k, False),
                "ac_tur": _ac_tur(hc["tur"]),
            }
        )
    if bilgi["makbuz_id"] and _bag_tablosu_var(session):
        from database.models.finans import SatisFaturaMakbuzBagi
        from database.models.satis_faturasi import SatisFaturasi

        bag = session.scalar(
            select(SatisFaturaMakbuzBagi).where(SatisFaturaMakbuzBagi.makbuz_id == int(bilgi["makbuz_id"]))
        )
        if bag is not None:
            fatura = session.get(SatisFaturasi, int(bag.fatura_id))
            kayitli = sum(
                (r["kapatilan"] for r in satirlar if r["evrak_no"] == bag.fatura_no), Decimal("0")
            )
            eski = _kurus(_d(bag.fatura_kapanan) - kayitli)
            if eski > TOLERANS:
                satirlar.insert(
                    0,
                    {
                        "kaynak": "BAGLI_MAKBUZ",
                        "kayit_id": None,
                        "tarih": bilgi["tarih"],
                        "evrak_turu": "Satış Faturası (bağlı)",
                        "evrak_no": bag.fatura_no,
                        "evrak_tarihi": getattr(fatura, "fatura_tarihi", None),
                        "ilk_tutar": None,
                        "kapatilan": eski,
                        "sonrasi_kalan": None,
                        "para_birimi": "TRY",
                        "tur": "Tahsilat",
                        "yontem": "Bağlı makbuz",
                        "ac_tur": "Satış",
                    },
                )
    avans_kalan = Decimal("0")
    for h in session.scalars(
        select(SatisHareketi).where(
            SatisHareketi.cari_id == int(cari_id),
            SatisHareketi.belge_no == belge_no,
            SatisHareketi.satis_tutari == 0,
            SatisHareketi.kalan_acik_tutar < 0,
        )
    ).all():
        avans_kalan += -_d(h.kalan_acik_tutar)
    avans_kalan = _kurus(avans_kalan)
    dagitilan = _kurus(sum((r["kapatilan"] for r in satirlar), Decimal("0")))
    toplam = bilgi["toplam"]
    if toplam is None:
        toplam = _kurus(dagitilan + avans_kalan)
    bilinmeyen = _kurus(toplam - dagitilan - avans_kalan)
    tutarli = True
    uyari = None
    if bilinmeyen > TOLERANS and (satirlar or avans_kalan > 0 or bilgi["evrak_turu"]):
        satirlar.append(
            {
                "kaynak": "BILINMIYOR",
                "kayit_id": None,
                "tarih": None,
                "evrak_turu": BILINMIYOR,
                "evrak_no": "",
                "evrak_tarihi": None,
                "ilk_tutar": None,
                "kapatilan": bilinmeyen,
                "sonrasi_kalan": None,
                "para_birimi": bilgi["para_birimi"],
                "tur": BILINMIYOR,
                "yontem": "",
                "ac_tur": "",
            }
        )
    elif bilinmeyen < -TOLERANS:
        tutarli = False
        uyari = (
            f"Dağıtılan ({dagitilan}) + kullanılmamış avans ({avans_kalan}) evrak toplamını ({toplam}) aşıyor. "
            "Kayıtlar otomatik düzeltilmedi; tanı raporuna yazıldı."
        )
        _tani_yaz(belge_no, uyari)
    mesaj = None
    if not any(r["kaynak"] in ("KAYIT", "BAGLI_MAKBUZ") for r in satirlar):
        mesaj = MESAJ_AVANS if avans_kalan > 0 else None
    return {
        "belge_no": belge_no,
        "evrak_turu": bilgi["evrak_turu"],
        "evrak_no": bilgi.get("evrak_no_goster") or belge_no,
        "tarih": bilgi["tarih"],
        "toplam": toplam,
        "dagitilan": dagitilan,
        "avans_kalan": avans_kalan,
        "bilinmeyen": max(bilinmeyen, Decimal("0")),
        "satirlar": satirlar,
        "iptaller": iptaller,
        "mesaj": mesaj,
        "tutarli": tutarli,
        "uyari": uyari,
        "hesap": bilgi["hesap"],
        "makbuz_id": bilgi["makbuz_id"],
        "ac_tur": bilgi["ac_tur"],
    }


def _ac_tur(evrak_turu: str) -> str:
    return {
        "Satış Faturası": "Satış",
        "Alış Faturası": "Alış",
    }.get(evrak_turu or "", evrak_turu or "")


def evrak_kapatma_detayi(belge_no: str, cari_id: int | None = None) -> dict[str, Any]:
    with get_session() as session:
        return evrak_kapatma_detayi_oturum(session, belge_no, cari_id)


def kaynak_dagitim_detayi(belge_no: str, cari_id: int) -> dict[str, Any]:
    with get_session() as session:
        return kaynak_dagitim_detayi_oturum(session, belge_no, int(cari_id))


def fatura_odeme_ozeti(fatura_id: int, tur: str = "SATIS") -> dict[str, Any]:
    """Fatura ekranı alt satırı: toplam, kapanan, kalan ve ödeme durumu."""
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.satis_faturasi import SatisFaturasi

    model = SatisFaturasi if tur == "SATIS" else AlisFaturasi
    with get_session() as session:
        fatura = session.get(model, int(fatura_id))
        if fatura is None:
            raise ValueError("Fatura bulunamadı.")
        detay = evrak_kapatma_detayi_oturum(session, fatura.fatura_no, int(fatura.cari_id))
        return {
            "belge_no": fatura.fatura_no,
            "cari_id": int(fatura.cari_id),
            "toplam": detay["esas_tutar"],
            "kapanan": detay["kapanan"],
            "kalan": detay["kalan"],
            "durum": detay["odeme_durumu"] or (detay["mesaj"] or ""),
            "mesaj": detay["mesaj"],
            "taslak": detay["taslak"],
            "iptal": detay["iptal"],
            "tutarli": detay["tutarli"],
        }


def tutarsizlik_raporu(cari_id: int | None = None) -> list[dict[str, Any]]:
    """Tanı raporu: Σ aktif pay + kalan ≠ evrak tutarı olan açık kalemler (salt okunur)."""
    sonuc = []
    with get_session() as session:
        sorgu = select(SatisHareketi).where(SatisHareketi.satis_tutari > 0)
        if cari_id is not None:
            sorgu = sorgu.where(SatisHareketi.cari_id == int(cari_id))
        for h in session.scalars(sorgu).all():
            aktif_toplam = _kurus(
                session.scalar(
                    select(func.coalesce(func.sum(CariKapatma.tutar), 0)).where(
                        CariKapatma.hedef_hareket_id == int(h.id), CariKapatma.iptal.is_(False)
                    )
                )
                if AcikKalemService._tablo_var(session)
                else 0
            )
            esas = _kurus(h.satis_tutari)
            kalan = _kurus(h.kalan_acik_tutar)
            if aktif_toplam + max(kalan, Decimal("0")) > esas + TOLERANS or kalan < -TOLERANS:
                sonuc.append(
                    {
                        "cari_id": int(h.cari_id),
                        "belge_no": h.belge_no or "",
                        "esas": esas,
                        "aktif_pay": aktif_toplam,
                        "kalan": kalan,
                        "fark": _kurus(aktif_toplam + kalan - esas),
                    }
                )
    for s in sonuc:
        _tani_yaz(s["belge_no"], f"aktif pay {s['aktif_pay']} + kalan {s['kalan']} ≠ tutar {s['esas']}")
    return sonuc


def acik_kalemler_listesi(cari_id: int, *, sadece_vadesi_gecen: bool = False,
                          bugun: date | None = None) -> list[dict[str, Any]]:
    """Cari kart "Açık Kalemler" görünümü (Açık Borçlar raporu ile aynı kaynak)."""
    with get_session() as session:
        satirlar = AcikKalemService.acik_kalem_raporu(session, int(cari_id), bugun=bugun)
    if sadece_vadesi_gecen:
        satirlar = [s for s in satirlar if s["acik"] > 0 and s["gecikme_gunu"] > 0]
    return satirlar
