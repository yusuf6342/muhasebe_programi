"""Operasyon belgelerinden otomatik muhasebe fişi üretimi.

Hesap kodları sabit yazılmaz; firma bazlı MuhasebeHesapEsleme kullanılır.
Eşleştirme eksikse fiş oluşturulmaz (işlem engellenmez).
Aynı kaynak için ikinci fiş UniqueConstraint ile engellenir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable

from sqlalchemy import select

from database.database import get_session
from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeHesapEsleme
from database.muhasebe_service import HesapPlanService, MuhasebeFisService, MuhasebeService, decimal

SIFIR = Decimal("0.00")

# Kaynak türleri (çift kayıt engeli için)
KAYNAK_SATIS_FATURA = "satis_faturasi"
KAYNAK_SATIS_TAHSILAT = "satis_fatura_tahsilat"
KAYNAK_ALIS_FATURA = "alis_faturasi"
KAYNAK_ALIS_ODEME = "alis_fatura_odeme"
KAYNAK_SATIS_IADE = "satis_iade"
KAYNAK_ALIS_IADE = "alis_iade"
KAYNAK_HIZMET_FATURA = "hizmet_faturasi"
KAYNAK_CARI_TAHSILAT = "cari_tahsilat"
KAYNAK_CARI_ODEME = "cari_odeme"

# Önerilen alt hesaplar (eşleştirme kolaylığı)
ONERI_HESAPLAR = (
    ("100", "Kasa", "Aktif", "kasa"),
    ("102", "Bankalar", "Aktif", "banka"),
    ("120", "Alıcılar", "Aktif", "musteriler"),
    ("153", "Ticari Mallar", "Aktif", "ticari_mallar"),
    ("191", "İndirilecek KDV", "Aktif", "indirilecek_kdv"),
    ("320", "Satıcılar", "Pasif", "tedarikciler"),
    ("391", "Hesaplanan KDV", "Pasif", "hesaplanan_kdv"),
    ("600", "Yurtiçi Satışlar", "Gelir", "yurtici_satislar"),
    ("621", "Satılan Ticari Mallar Maliyeti", "Gider", "satilan_mal_maliyeti"),
    ("770", "Genel Yönetim Giderleri", "Gider", "giderler"),
)


class HesapEslemeService:
    @staticmethod
    def listele() -> list[dict]:
        MuhasebeService.esleme_sablonlarini_doldur()
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            rows = session.scalars(
                select(MuhasebeHesapEsleme)
                .where(MuhasebeHesapEsleme.firma_id == firma_id)
                .order_by(MuhasebeHesapEsleme.anahtar)
            ).all()
            sonuc = []
            for e in rows:
                kod = ad = None
                if e.hesap_id:
                    h = session.get(HesapPlani, e.hesap_id)
                    if h:
                        kod, ad = h.hesap_kodu, h.hesap_adi
                sonuc.append(
                    {
                        "id": e.id,
                        "anahtar": e.anahtar,
                        "aciklama": e.aciklama,
                        "hesap_id": e.hesap_id,
                        "hesap_kodu": kod,
                        "hesap_adi": ad,
                        "aktif": e.aktif,
                    }
                )
            return sonuc

    @staticmethod
    def kaydet(anahtar: str, hesap_id: int | None) -> None:
        from database.access import yazma_zorunlu

        yazma_zorunlu("muhasebe_fis_duzenleme", "duzenleme")
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            e = session.scalar(
                select(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.firma_id == firma_id,
                    MuhasebeHesapEsleme.anahtar == anahtar,
                )
            )
            if e is None:
                raise ValueError(f"Eşleştirme anahtarı yok: {anahtar}")
            if hesap_id:
                h = session.get(HesapPlani, int(hesap_id))
                if h is None or h.firma_id != firma_id:
                    raise ValueError("Hesap bulunamadı.")
                e.hesap_id = h.id
            else:
                e.hesap_id = None

    @staticmethod
    def oneri_hesaplari_olustur() -> int:
        """Önerilen alt hesapları açar ve eşleştirmeleri doldurur."""
        from database.access import yazma_zorunlu

        yazma_zorunlu("muhasebe_fis_olusturma", "yeni_kayit", "duzenleme")
        MuhasebeService.ana_hesaplari_doldur()
        MuhasebeService.esleme_sablonlarini_doldur()
        eklenen = 0
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            for kod, ad, tur, anahtar in ONERI_HESAPLAR:
                h = session.scalar(
                    select(HesapPlani).where(
                        HesapPlani.firma_id == firma_id, HesapPlani.hesap_kodu == kod
                    )
                )
                if h is None:
                    ust = session.scalar(
                        select(HesapPlani).where(
                            HesapPlani.firma_id == firma_id,
                            HesapPlani.hesap_kodu == kod[0],
                        )
                    )
                    h = HesapPlani(
                        firma_id=firma_id,
                        hesap_kodu=kod,
                        hesap_adi=ad,
                        ust_hesap_id=ust.id if ust else None,
                        hesap_seviyesi=2,
                        hesap_turu=tur,
                        aktif=True,
                    )
                    session.add(h)
                    session.flush()
                    eklenen += 1
                e = session.scalar(
                    select(MuhasebeHesapEsleme).where(
                        MuhasebeHesapEsleme.firma_id == firma_id,
                        MuhasebeHesapEsleme.anahtar == anahtar,
                    )
                )
                if e and e.hesap_id is None:
                    e.hesap_id = h.id
        return eklenen


class MuhasebeEntegrasyonService:
    @staticmethod
    def _guvenli(fn: Callable, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as hata:
            print(f"[Muhasebe entegrasyon] {fn.__name__}: {hata}")
            return None

    @staticmethod
    def mevcut_fis_id(kaynak_turu: str, kaynak_id: int) -> int | None:
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            fis = session.scalar(
                select(MuhasebeFisi).where(
                    MuhasebeFisi.firma_id == firma_id,
                    MuhasebeFisi.kaynak_turu == kaynak_turu,
                    MuhasebeFisi.kaynak_id == int(kaynak_id),
                    MuhasebeFisi.durum != "İptal",
                )
            )
            return fis.id if fis else None

    @staticmethod
    def iptal_kaynak(kaynak_turu: str, kaynak_id: int, neden: str = "") -> None:
        fis_id = MuhasebeEntegrasyonService.mevcut_fis_id(kaynak_turu, kaynak_id)
        if fis_id:
            MuhasebeFisService.iptal(
                fis_id, neden or f"Kaynak iptal: {kaynak_turu}", otomatik=True
            )

    @staticmethod
    def _hesap(anahtar: str) -> dict:
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            e = session.scalar(
                select(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.firma_id == firma_id,
                    MuhasebeHesapEsleme.anahtar == anahtar,
                    MuhasebeHesapEsleme.aktif.is_(True),
                )
            )
            if e is None or not e.hesap_id:
                raise ValueError(f"Hesap eşleştirmesi eksik: {anahtar}")
            h = session.get(HesapPlani, e.hesap_id)
            if h is None or not h.aktif:
                raise ValueError(f"Eşleştirilen hesap pasif/yok: {anahtar}")
            return {"id": h.id, "kod": h.hesap_kodu, "ad": h.hesap_adi}

    @staticmethod
    def _kasa_veya_banka(odeme_sekli: str | None, hesap_adi: str | None) -> dict:
        metin = f"{odeme_sekli or ''} {hesap_adi or ''}".casefold()
        if any(x in metin for x in ("banka", "havale", "eft", "pos", "kredi kart")):
            return MuhasebeEntegrasyonService._hesap("banka")
        return MuhasebeEntegrasyonService._hesap("kasa")

    @staticmethod
    def _satir(hesap: dict, *, borc=SIFIR, alacak=SIFIR, aciklama: str = "") -> dict:
        return {
            "hesap_id": hesap["id"],
            "borc": decimal(borc),
            "alacak": decimal(alacak),
            "aciklama": aciklama,
        }

    @staticmethod
    def _olustur(
        *,
        kaynak_turu: str,
        kaynak_id: int,
        fis_tarihi: date,
        fis_turu: str,
        aciklama: str,
        belge_no: str | None,
        satirlar: list[dict],
        yeniden: bool = False,
    ) -> int | None:
        mevcut = MuhasebeEntegrasyonService.mevcut_fis_id(kaynak_turu, kaynak_id)
        if mevcut and not yeniden:
            return mevcut
        if mevcut and yeniden:
            MuhasebeFisService.iptal(mevcut, "Kaynak belge güncellendi", otomatik=True)
        temiz = [s for s in satirlar if decimal(s.get("borc")) or decimal(s.get("alacak"))]
        if not temiz:
            return None
        return MuhasebeFisService.kaydet(
            {
                "fis_tarihi": fis_tarihi,
                "fis_turu": fis_turu,
                "aciklama": aciklama,
                "belge_no": belge_no,
                "durum": "Kesinleşmiş",
                "kaynak_turu": kaynak_turu,
                "kaynak_id": int(kaynak_id),
                "satirlar": temiz,
            },
            otomatik=True,
        )

    # ---- Satış faturası ----

    @staticmethod
    def satis_faturasi_fisi(fatura_id: int, *, yeniden: bool = False) -> int | None:
        from database.models.satis_faturasi import SatisFaturasi

        with get_session() as session:
            f = session.get(SatisFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL" or not getattr(f, "onaylandi", False):
                return None
            matrah = decimal(getattr(f, "tl_matrah", None) or 0)
            kdv = decimal(getattr(f, "tl_kdv", None) or 0)
            genel = decimal(getattr(f, "tl_genel_toplam", None) or 0)
            if genel <= 0:
                from database.satis_faturasi_service import SatisFaturasiService

                t = SatisFaturasiService.toplam(f.satirlar)
                matrah = decimal(t["ara_toplam"] - t["iskonto"])
                kdv = decimal(t["kdv"])
                genel = decimal(t["genel_toplam"])
            tarih = f.fatura_tarihi
            no = f.fatura_no
            tahsilat = decimal(f.tahsilat_tutari or 0)
            # FIFO maliyet (varsa)
            maliyet = SIFIR
            for s in f.satirlar:
                mb = decimal(getattr(s, "fifo_birim_maliyeti", None) or 0)
                maliyet += mb * decimal(s.miktar)

        musteri = MuhasebeEntegrasyonService._hesap("musteriler")
        satis = MuhasebeEntegrasyonService._hesap("yurtici_satislar")
        hesap_kdv = MuhasebeEntegrasyonService._hesap("hesaplanan_kdv")
        satirlar = [
            MuhasebeEntegrasyonService._satir(
                musteri, borc=genel, aciklama=f"Satış faturası {no}"
            ),
            MuhasebeEntegrasyonService._satir(
                satis, alacak=matrah, aciklama=f"Satış matrah {no}"
            ),
        ]
        if kdv > 0:
            satirlar.append(
                MuhasebeEntegrasyonService._satir(
                    hesap_kdv, alacak=kdv, aciklama=f"Hesaplanan KDV {no}"
                )
            )
        if maliyet > 0:
            try:
                smm = MuhasebeEntegrasyonService._hesap("satilan_mal_maliyeti")
                stok = MuhasebeEntegrasyonService._hesap("ticari_mallar")
                satirlar.append(
                    MuhasebeEntegrasyonService._satir(smm, borc=maliyet, aciklama=f"SMM {no}")
                )
                satirlar.append(
                    MuhasebeEntegrasyonService._satir(stok, alacak=maliyet, aciklama=f"Stok {no}")
                )
            except ValueError:
                pass

        fis_id = MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_SATIS_FATURA,
            kaynak_id=fatura_id,
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=f"Otomatik: Satış faturası {no}",
            belge_no=no,
            satirlar=satirlar,
            yeniden=yeniden,
        )

        if tahsilat > 0:
            try:
                with get_session() as session:
                    f2 = session.get(SatisFaturasi, int(fatura_id))
                    sekil = f2.tahsilat_sekli if f2 else None
                    hesap = f2.tahsilat_hesabi if f2 else None
                    if f2 and f2.tahsilatlar:
                        th0 = f2.tahsilatlar[0]
                        sekil = th0.odeme_sekli or sekil
                        hesap = th0.hesap or hesap
                kasa = MuhasebeEntegrasyonService._kasa_veya_banka(sekil, hesap)
                MuhasebeEntegrasyonService._olustur(
                    kaynak_turu=KAYNAK_SATIS_TAHSILAT,
                    kaynak_id=fatura_id,
                    fis_tarihi=tarih,
                    fis_turu="Tahsil Fişi",
                    aciklama=f"Otomatik: Satış tahsilatı {no}",
                    belge_no=no,
                    satirlar=[
                        MuhasebeEntegrasyonService._satir(
                            kasa, borc=tahsilat, aciklama=f"Tahsilat {no}"
                        ),
                        MuhasebeEntegrasyonService._satir(
                            musteri, alacak=tahsilat, aciklama=f"Tahsilat {no}"
                        ),
                    ],
                    yeniden=yeniden,
                )
            except ValueError as e:
                print(f"[Muhasebe entegrasyon] satış tahsilat fişi: {e}")

        return fis_id

    @staticmethod
    def satis_faturasi_iptal(fatura_id: int) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(
            KAYNAK_SATIS_FATURA, fatura_id, "Satış faturası iptal/onay kaldırma"
        )
        MuhasebeEntegrasyonService.iptal_kaynak(
            KAYNAK_SATIS_TAHSILAT, fatura_id, "Satış tahsilat fişi iptal"
        )

    # ---- Alış faturası ----

    @staticmethod
    def alis_faturasi_fisi(fatura_id: int, *, yeniden: bool = True) -> int | None:
        from database.models.alis_faturasi import AlisFaturasi

        with get_session() as session:
            f = session.get(AlisFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL":
                return None
            matrah = decimal(getattr(f, "tl_matrah", None) or 0)
            kdv = decimal(getattr(f, "tl_kdv", None) or 0)
            genel = decimal(getattr(f, "tl_genel_toplam", None) or 0)
            if genel <= 0:
                from database.alis_faturasi_service import AlisFaturasiService

                t = AlisFaturasiService.toplam(f.satirlar)
                matrah = decimal(t["ara_toplam"] - t["iskonto"])
                kdv = decimal(t["kdv"])
                genel = decimal(t["genel_toplam"])
            tarih = f.fatura_tarihi
            no = f.fatura_no
            odeme = decimal(f.odeme_tutari or 0)
            odeme_sekli = f.odeme_sekli
            odeme_hesabi = f.odeme_hesabi

        stok = MuhasebeEntegrasyonService._hesap("ticari_mallar")
        ted = MuhasebeEntegrasyonService._hesap("tedarikciler")
        satirlar = [
            MuhasebeEntegrasyonService._satir(stok, borc=matrah, aciklama=f"Alış {no}"),
            MuhasebeEntegrasyonService._satir(ted, alacak=genel, aciklama=f"Alış {no}"),
        ]
        if kdv > 0:
            ikdv = MuhasebeEntegrasyonService._hesap("indirilecek_kdv")
            satirlar.insert(
                1,
                MuhasebeEntegrasyonService._satir(ikdv, borc=kdv, aciklama=f"İnd. KDV {no}"),
            )

        fis_id = MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_ALIS_FATURA,
            kaynak_id=fatura_id,
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=f"Otomatik: Alış faturası {no}",
            belge_no=no,
            satirlar=satirlar,
            yeniden=yeniden,
        )

        if odeme > 0:
            try:
                kasa = MuhasebeEntegrasyonService._kasa_veya_banka(odeme_sekli, odeme_hesabi)
                MuhasebeEntegrasyonService._olustur(
                    kaynak_turu=KAYNAK_ALIS_ODEME,
                    kaynak_id=fatura_id,
                    fis_tarihi=tarih,
                    fis_turu="Tediye Fişi",
                    aciklama=f"Otomatik: Alış ödemesi {no}",
                    belge_no=no,
                    satirlar=[
                        MuhasebeEntegrasyonService._satir(
                            ted, borc=odeme, aciklama=f"Ödeme {no}"
                        ),
                        MuhasebeEntegrasyonService._satir(
                            kasa, alacak=odeme, aciklama=f"Ödeme {no}"
                        ),
                    ],
                    yeniden=yeniden,
                )
            except ValueError as e:
                print(f"[Muhasebe entegrasyon] alış ödeme fişi: {e}")
        return fis_id

    @staticmethod
    def alis_faturasi_iptal(fatura_id: int) -> None:
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_ALIS_FATURA, fatura_id, "Alış iptal")
        MuhasebeEntegrasyonService.iptal_kaynak(KAYNAK_ALIS_ODEME, fatura_id, "Alış ödeme iptal")

    # ---- İadeler ----

    @staticmethod
    def satis_iade_fisi(iade_id: int, *, yeniden: bool = True) -> int | None:
        from database.models.satis_iade_faturasi import SatisIadeFaturasi
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        with get_session() as session:
            f = session.get(SatisIadeFaturasi, int(iade_id))
            if f is None or f.durum == "İPTAL":
                return None
            t = SatisIadeFaturasiService.toplam(f.satirlar)
            matrah = decimal(t["ara_toplam"] - t["iskonto"])
            kdv = decimal(t["kdv"])
            genel = decimal(t["genel_toplam"])
            tarih, no = f.iade_tarihi, f.iade_no

        musteri = MuhasebeEntegrasyonService._hesap("musteriler")
        satis = MuhasebeEntegrasyonService._hesap("yurtici_satislar")
        satirlar = [
            MuhasebeEntegrasyonService._satir(satis, borc=matrah, aciklama=f"Satış iade {no}"),
            MuhasebeEntegrasyonService._satir(musteri, alacak=genel, aciklama=f"Satış iade {no}"),
        ]
        if kdv > 0:
            hkdv = MuhasebeEntegrasyonService._hesap("hesaplanan_kdv")
            satirlar.insert(
                1,
                MuhasebeEntegrasyonService._satir(hkdv, borc=kdv, aciklama=f"KDV iade {no}"),
            )
        return MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_SATIS_IADE,
            kaynak_id=iade_id,
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=f"Otomatik: Satış iadesi {no}",
            belge_no=no,
            satirlar=satirlar,
            yeniden=yeniden,
        )

    @staticmethod
    def alis_iade_fisi(iade_id: int, *, yeniden: bool = True) -> int | None:
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService

        with get_session() as session:
            f = session.get(AlisIadeFaturasi, int(iade_id))
            if f is None or f.durum == "İPTAL":
                return None
            t = AlisIadeFaturasiService.toplam(f.satirlar)
            matrah = decimal(t["ara_toplam"] - t["iskonto"])
            kdv = decimal(t["kdv"])
            genel = decimal(t["genel_toplam"])
            tarih, no = f.iade_tarihi, f.iade_no

        stok = MuhasebeEntegrasyonService._hesap("ticari_mallar")
        ted = MuhasebeEntegrasyonService._hesap("tedarikciler")
        satirlar = [
            MuhasebeEntegrasyonService._satir(ted, borc=genel, aciklama=f"Alış iade {no}"),
            MuhasebeEntegrasyonService._satir(stok, alacak=matrah, aciklama=f"Alış iade {no}"),
        ]
        if kdv > 0:
            ikdv = MuhasebeEntegrasyonService._hesap("indirilecek_kdv")
            satirlar.append(
                MuhasebeEntegrasyonService._satir(ikdv, alacak=kdv, aciklama=f"KDV iade {no}")
            )
        return MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_ALIS_IADE,
            kaynak_id=iade_id,
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=f"Otomatik: Alış iadesi {no}",
            belge_no=no,
            satirlar=satirlar,
            yeniden=yeniden,
        )

    # ---- Hizmet faturası ----

    @staticmethod
    def hizmet_faturasi_fisi(fatura_id: int, *, yeniden: bool = True) -> int | None:
        from database.models.hizmet_faturasi import HizmetFaturasi

        with get_session() as session:
            f = session.get(HizmetFaturasi, int(fatura_id))
            if f is None or f.durum == "İPTAL":
                return None
            matrah = decimal(f.tl_matrah or 0)
            kdv = decimal(f.tl_kdv or 0)
            genel = decimal(f.tl_genel_toplam or 0)
            tur = (f.fatura_turu or "GIDER").upper()
            tarih, no = f.fatura_tarihi, f.fatura_no

        if tur == "GELIR":
            musteri = MuhasebeEntegrasyonService._hesap("musteriler")
            gelir = MuhasebeEntegrasyonService._hesap("yurtici_satislar")
            satirlar = [
                MuhasebeEntegrasyonService._satir(musteri, borc=genel, aciklama=no),
                MuhasebeEntegrasyonService._satir(gelir, alacak=matrah, aciklama=no),
            ]
            if kdv > 0:
                hkdv = MuhasebeEntegrasyonService._hesap("hesaplanan_kdv")
                satirlar.append(
                    MuhasebeEntegrasyonService._satir(hkdv, alacak=kdv, aciklama=no)
                )
        else:
            gider = MuhasebeEntegrasyonService._hesap("giderler")
            ted = MuhasebeEntegrasyonService._hesap("tedarikciler")
            satirlar = [
                MuhasebeEntegrasyonService._satir(gider, borc=matrah, aciklama=no),
                MuhasebeEntegrasyonService._satir(ted, alacak=genel, aciklama=no),
            ]
            if kdv > 0:
                ikdv = MuhasebeEntegrasyonService._hesap("indirilecek_kdv")
                satirlar.insert(
                    1,
                    MuhasebeEntegrasyonService._satir(ikdv, borc=kdv, aciklama=no),
                )

        return MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_HIZMET_FATURA,
            kaynak_id=fatura_id,
            fis_tarihi=tarih,
            fis_turu="Mahsup Fişi",
            aciklama=f"Otomatik: Hizmet faturası {no}",
            belge_no=no,
            satirlar=satirlar,
            yeniden=yeniden,
        )

    # ---- Cari tahsilat / ödeme ----

    @staticmethod
    def cari_tahsilat_fisi(islem_id: int) -> int | None:
        from database.models.cari import CariIslem

        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                return None
            tutar = decimal(islem.alacak or 0)
            tarih, no = islem.tarih, islem.belge_no
            hesap_adi = islem.hesap_adi

        if tutar <= 0:
            return None
        kasa = MuhasebeEntegrasyonService._kasa_veya_banka(None, hesap_adi)
        musteri = MuhasebeEntegrasyonService._hesap("musteriler")
        return MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_CARI_TAHSILAT,
            kaynak_id=islem_id,
            fis_tarihi=tarih,
            fis_turu="Tahsil Fişi",
            aciklama=f"Otomatik: Cari tahsilat {no}",
            belge_no=no,
            satirlar=[
                MuhasebeEntegrasyonService._satir(kasa, borc=tutar, aciklama=no),
                MuhasebeEntegrasyonService._satir(musteri, alacak=tutar, aciklama=no),
            ],
        )

    @staticmethod
    def cari_odeme_fisi(islem_id: int) -> int | None:
        from database.models.cari import CariIslem

        with get_session() as session:
            islem = session.get(CariIslem, int(islem_id))
            if islem is None:
                return None
            # Ödemede borc veya alacak tutarı modele göre değişebilir
            tutar = decimal(islem.borc or 0) or decimal(islem.alacak or 0)
            tarih, no = islem.tarih, islem.belge_no
            hesap_adi = islem.hesap_adi

        if tutar <= 0:
            return None
        kasa = MuhasebeEntegrasyonService._kasa_veya_banka(None, hesap_adi)
        ted = MuhasebeEntegrasyonService._hesap("tedarikciler")
        return MuhasebeEntegrasyonService._olustur(
            kaynak_turu=KAYNAK_CARI_ODEME,
            kaynak_id=islem_id,
            fis_tarihi=tarih,
            fis_turu="Tediye Fişi",
            aciklama=f"Otomatik: Cari ödeme {no}",
            belge_no=no,
            satirlar=[
                MuhasebeEntegrasyonService._satir(ted, borc=tutar, aciklama=no),
                MuhasebeEntegrasyonService._satir(kasa, alacak=tutar, aciklama=no),
            ],
        )


def muhasebe_hook(fn_name: str, *args, **kwargs):
    """Operasyon servislerinden güvenli çağrı."""
    fn = getattr(MuhasebeEntegrasyonService, fn_name, None)
    if fn is None:
        return None
    return MuhasebeEntegrasyonService._guvenli(fn, *args, **kwargs)
