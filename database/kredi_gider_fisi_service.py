"""Kredi / nakit avans gider fişi — muhasebe hesabı damgası, açma ve hesap atama.

Ödeme sırasında oluşan faiz/masraf GiderFisi kayıtlarına firma veya kredi özel
eşlemeyi yazar. Eksik eşlemede durum BEKLIYOR kalır; sonradan hesap atamak yeni
fiş üretmez. Gider Raporu bu damgaları kullanır.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.database import engine, get_session
from database.models.finans import (
    BankaKarti,
    BankaKredisi,
    BankaKrediOdeme,
    BankaKrediTaksit,
    FinansHesabi,
    GiderFisi,
)
from database.muhasebe_entegrasyon import KREDI_GIDER_ANAHTARLARI

DURUM_BEKLIYOR = "BEKLIYOR"
DURUM_HAZIR = "HAZIR"
DURUM_AKTARILDI = "AKTARILDI"
DURUM_ETIKET = {
    DURUM_BEKLIYOR: "Muhasebe hesabı bekliyor",
    DURUM_HAZIR: "Hesap hazır",
    DURUM_AKTARILDI: "Muhasebeye aktarıldı",
}

# GiderFisi.gider_turu → MuhasebeHesapEsleme anahtarı
GIDER_TURU_ANAHTAR: dict[str, str] = {
    "KREDI_FAIZ": "kredi_faiz_gideri",
    "KREDI_BSMV": "kredi_bsmv_gideri",
    "KREDI_KKDF": "kredi_kkdf_gideri",
    "KREDI_KOMISYON": "kredi_komisyon_gideri",
    "KREDI_SIGORTA": "kredi_sigorta_gideri",
    "KREDI_DOSYA": "kredi_dosya_masrafi",
    "KREDI_MASRAF": "kredi_diger_finansman",
    "KREDI_GECIKME": "kredi_gecikme_faizi",
    "NAKIT_AVANS_FAIZ": "kredi_faiz_gideri",
    "NAKIT_AVANS_MASRAF": "kredi_dosya_masrafi",
    "NAKIT_AVANS_VERGI": "kredi_bsmv_gideri",
    "NAKIT_AVANS_KUL_MASRAF": "kredi_dosya_masrafi",
    "NAKIT_AVANS_KUL_VERGI": "kredi_bsmv_gideri",
}

FINANSMAN_GIDER_TURLERI = frozenset(GIDER_TURU_ANAHTAR.keys())

GIDER_FISI_YENI_KOLONLAR = {
    "muhasebe_hesap_kodu": "VARCHAR(40)",
    "muhasebe_hesap_id": "INTEGER",
    "muhasebe_durum": "VARCHAR(20)",
    "kaynak_kredi_id": "INTEGER",
}

KREDI_HESAP_KOLONLARI = {
    "faiz_muhasebe_hesap_kodu": "VARCHAR(40)",
    "masraf_muhasebe_hesap_kodu": "VARCHAR(40)",
}

SIFIR = Decimal("0.00")


def _q(v) -> Decimal:
    try:
        return Decimal(str(v or 0)).quantize(Decimal("0.01"))
    except Exception:
        return SIFIR


class KrediGiderFisiService:
    @staticmethod
    def schema_hazirla() -> None:
        if engine is None:
            return
        import database.models.finans  # noqa: F401

        GiderFisi.__table__.create(engine, checkfirst=True)
        BankaKredisi.__table__.create(engine, checkfirst=True)
        insp = inspect(engine)
        for tablo, kolonlar in (
            ("gider_fisleri", GIDER_FISI_YENI_KOLONLAR),
            ("banka_kredileri", KREDI_HESAP_KOLONLARI),
        ):
            if not insp.has_table(tablo):
                continue
            mevcut = {c["name"] for c in insp.get_columns(tablo)}
            eksikler = {a: t for a, t in kolonlar.items() if a not in mevcut}
            if not eksikler:
                continue
            with engine.begin() as connection:
                for alan, tip in eksikler.items():
                    connection.execute(
                        text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}')
                    )

    @staticmethod
    def anahtar_icin(gider_turu: str | None) -> str | None:
        tur = (gider_turu or "").strip().upper()
        return GIDER_TURU_ANAHTAR.get(tur)

    @staticmethod
    def finansman_turu_mi(gider_turu: str | None) -> bool:
        return (gider_turu or "").strip().upper() in FINANSMAN_GIDER_TURLERI

    @staticmethod
    def durum_etiket(durum: str | None) -> str:
        d = (durum or "").strip().upper()
        return DURUM_ETIKET.get(d, d or "—")

    @staticmethod
    def _firma_esleme(session, anahtar: str) -> dict | None:
        """Firma eşlemesinden hesap; yoksa None (hata fırlatmaz)."""
        if not anahtar:
            return None
        try:
            from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

            return MuhasebeEntegrasyonService._hesap(anahtar, session=session)
        except Exception:
            return None

    @staticmethod
    def _kodla_hesap(session, kod: str | None) -> dict | None:
        kod = (kod or "").strip()
        if not kod:
            return None
        try:
            from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

            return MuhasebeEntegrasyonService._hesap_kodla(
                kod, f"Kredi gider hesabı {kod}", session=session
            )
        except Exception:
            return None

    @staticmethod
    def hesap_coz(
        session,
        gider_turu: str,
        *,
        kredi_id: int | None = None,
        kredi: BankaKredisi | None = None,
    ) -> dict | None:
        """Öncelik: kredi özel kod → firma MuhasebeHesapEsleme."""
        anahtar = KrediGiderFisiService.anahtar_icin(gider_turu)
        if not anahtar:
            return None
        k = kredi
        if k is None and kredi_id:
            k = session.get(BankaKredisi, int(kredi_id))
        tur = (gider_turu or "").upper()
        if k is not None:
            if tur == "KREDI_FAIZ" or "FAIZ" in tur:
                ozel = getattr(k, "faiz_muhasebe_hesap_kodu", None)
                bulunan = KrediGiderFisiService._kodla_hesap(session, ozel)
                if bulunan:
                    return bulunan
            if tur in (
                "KREDI_MASRAF",
                "KREDI_DOSYA",
                "KREDI_KOMISYON",
                "KREDI_SIGORTA",
                "KREDI_BSMV",
                "KREDI_KKDF",
                "NAKIT_AVANS_MASRAF",
                "NAKIT_AVANS_KUL_MASRAF",
                "NAKIT_AVANS_VERGI",
                "NAKIT_AVANS_KUL_VERGI",
            ) or "MASRAF" in tur:
                ozel = getattr(k, "masraf_muhasebe_hesap_kodu", None)
                bulunan = KrediGiderFisiService._kodla_hesap(session, ozel)
                if bulunan:
                    return bulunan
        return KrediGiderFisiService._firma_esleme(session, anahtar)

    @staticmethod
    def damgala(
        session,
        fis: GiderFisi,
        *,
        kredi_id: int | None = None,
        kredi: BankaKredisi | None = None,
    ) -> GiderFisi:
        """Gider fişine muhasebe hesabı / durum yazar. Yeni fiş üretmez."""
        kid = kredi_id or (kredi.id if kredi is not None else None) or getattr(
            fis, "kaynak_kredi_id", None
        )
        if kid and hasattr(fis, "kaynak_kredi_id"):
            fis.kaynak_kredi_id = int(kid)
        hesap = KrediGiderFisiService.hesap_coz(
            session, fis.gider_turu or "", kredi_id=kid, kredi=kredi
        )
        if hesap:
            fis.muhasebe_hesap_kodu = hesap.get("kod")
            fis.muhasebe_hesap_id = hesap.get("id")
            # Aktarılmışsa koru; değilse HAZIR
            if (getattr(fis, "muhasebe_durum", None) or "") != DURUM_AKTARILDI:
                fis.muhasebe_durum = DURUM_HAZIR
        else:
            fis.muhasebe_hesap_kodu = None
            fis.muhasebe_hesap_id = None
            if (getattr(fis, "muhasebe_durum", None) or "") != DURUM_AKTARILDI:
                fis.muhasebe_durum = DURUM_BEKLIYOR
        return fis

    @staticmethod
    def odeme_giderlerini_damgala(
        session,
        odeme_belge_no: str,
        *,
        kredi_id: int | None = None,
        kredi: BankaKredisi | None = None,
    ) -> list[GiderFisi]:
        belge = (odeme_belge_no or "").strip()
        if not belge:
            return []
        fisler = list(
            session.scalars(
                select(GiderFisi).where(GiderFisi.bagli_belge_no == belge)
            ).all()
        )
        for f in fisler:
            KrediGiderFisiService.damgala(
                session, f, kredi_id=kredi_id, kredi=kredi
            )
        return fisler

    @staticmethod
    def bagli_fisleri_listele(
        *,
        odeme_belge_no: str | None = None,
        gider_belge_no: str | None = None,
        fis_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Ödeme veya gider belge önekine göre faiz/masraf fişleri."""
        with get_session() as session:
            q = select(GiderFisi)
            if fis_id:
                q = q.where(GiderFisi.id == int(fis_id))
            elif odeme_belge_no:
                q = q.where(GiderFisi.bagli_belge_no == str(odeme_belge_no).strip())
            elif gider_belge_no:
                onek = str(gider_belge_no).strip()
                q = q.where(
                    (GiderFisi.belge_no == onek)
                    | (GiderFisi.belge_no.like(f"{onek}-%"))
                    | (GiderFisi.bagli_belge_no == onek)
                )
            else:
                return []
            fisler = list(session.scalars(q.order_by(GiderFisi.id)).all())
            return [KrediGiderFisiService._fis_sozluk(session, f) for f in fisler]

    @staticmethod
    def ozet(
        *,
        odeme_belge_no: str | None = None,
        gider_belge_no: str | None = None,
        fis_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Tek ödeme için konsolide gider özeti (UI / önizleme)."""
        with get_session() as session:
            odeme = None
            fisler: list[GiderFisi] = []
            if fis_id:
                f0 = session.get(GiderFisi, int(fis_id))
                if f0 is None:
                    return None
                if f0.bagli_belge_no:
                    odeme = session.scalar(
                        select(BankaKrediOdeme).where(
                            BankaKrediOdeme.odeme_belge_no == f0.bagli_belge_no
                        )
                    )
                    fisler = list(
                        session.scalars(
                            select(GiderFisi).where(
                                GiderFisi.bagli_belge_no == f0.bagli_belge_no
                            )
                        ).all()
                    )
                else:
                    fisler = [f0]
            elif odeme_belge_no:
                odeme = session.scalar(
                    select(BankaKrediOdeme).where(
                        BankaKrediOdeme.odeme_belge_no == str(odeme_belge_no).strip()
                    )
                )
                fisler = list(
                    session.scalars(
                        select(GiderFisi).where(
                            GiderFisi.bagli_belge_no == str(odeme_belge_no).strip()
                        )
                    ).all()
                )
            elif gider_belge_no:
                onek = str(gider_belge_no).strip()
                fisler = list(
                    session.scalars(
                        select(GiderFisi).where(
                            (GiderFisi.belge_no == onek)
                            | (GiderFisi.belge_no.like(f"{onek}-%"))
                        )
                    ).all()
                )
                if fisler and fisler[0].bagli_belge_no:
                    bagli = fisler[0].bagli_belge_no
                    odeme = session.scalar(
                        select(BankaKrediOdeme).where(
                            BankaKrediOdeme.odeme_belge_no == bagli
                        )
                    )
                    # Nakit avans: aynı karta yansıma belgesine bağlı tüm faiz/masraf
                    kardes = list(
                        session.scalars(
                            select(GiderFisi).where(GiderFisi.bagli_belge_no == bagli)
                        ).all()
                    )
                    if kardes:
                        fisler = kardes
            if not fisler and odeme is None:
                return None

            kredi = None
            taksit = None
            banka = None
            odeme_hesap = None
            if odeme is not None:
                kredi = session.get(BankaKredisi, odeme.kredi_id)
                if odeme.taksit_id:
                    taksit = session.get(BankaKrediTaksit, odeme.taksit_id)
                odeme_hesap = session.get(FinansHesabi, odeme.banka_hesap_id)
            elif fisler:
                kid = getattr(fisler[0], "kaynak_kredi_id", None)
                if kid:
                    kredi = session.get(BankaKredisi, int(kid))
                if fisler[0].finans_hesap_id:
                    odeme_hesap = session.get(FinansHesabi, fisler[0].finans_hesap_id)
            if kredi is not None:
                banka = session.get(BankaKarti, kredi.banka_karti_id)

            faiz = SIFIR
            masraf = SIFIR
            satirlar = []
            for f in fisler:
                if (f.durum or "").upper() == "IPTAL":
                    continue
                t = _q(f.tutar)
                tur = (f.gider_turu or "").upper()
                if "FAIZ" in tur or tur.endswith("_FAIZ"):
                    faiz += t
                else:
                    masraf += t
                satirlar.append(KrediGiderFisiService._fis_sozluk(session, f))

            bekleyen = any(
                (s.get("muhasebe_durum") or "") == DURUM_BEKLIYOR for s in satirlar
            )
            firma_ad = ""
            try:
                from branding import _aktif_firma_unvani

                firma_ad = _aktif_firma_unvani() or ""
            except Exception:
                pass

            return {
                "firma": firma_ad,
                "banka": banka.banka_adi if banka else "",
                "kredi_id": kredi.id if kredi else None,
                "kredi_adi": kredi.kredi_adi if kredi else "",
                "kredi_belge": kredi.belge_no if kredi else "",
                "taksit_no": taksit.taksit_no if taksit else None,
                "taksit_sayisi": kredi.taksit_sayisi if kredi else None,
                "odeme_belge_no": odeme.odeme_belge_no if odeme else (
                    fisler[0].bagli_belge_no if fisler else None
                ),
                "gider_belge_no": (
                    odeme.gider_belge_no if odeme else (
                        (fisler[0].belge_no or "").rsplit("-", 1)[0] if fisler else None
                    )
                ),
                "odeme_tarihi": odeme.odeme_tarihi if odeme else (
                    fisler[0].tarih if fisler else None
                ),
                "anapara": _q(odeme.anapara) if odeme else SIFIR,
                "faiz": faiz if faiz else (_q(odeme.faiz) if odeme else SIFIR),
                "masraf": masraf if masraf else (
                    _q(
                        sum(
                            (
                                _q(getattr(odeme, a, 0))
                                for a in KREDI_GIDER_ANAHTARLARI
                                if a != "faiz"
                            ),
                            SIFIR,
                        )
                    )
                    if odeme
                    else SIFIR
                ),
                "toplam_odeme": _q(odeme.toplam) if odeme else (faiz + masraf),
                "toplam_gider": faiz + masraf,
                "odeme_hesabi": odeme_hesap.hesap_adi if odeme_hesap else "",
                "muhasebe_bekliyor": bekleyen,
                "muhasebe_durum_etiket": (
                    DURUM_ETIKET[DURUM_BEKLIYOR] if bekleyen else "Hesaplar hazır"
                ),
                "satirlar": satirlar,
                "odeme_durum": odeme.durum if odeme else None,
            }

    @staticmethod
    def _fis_sozluk(session, fis: GiderFisi) -> dict[str, Any]:
        hesap_ad = None
        hid = getattr(fis, "muhasebe_hesap_id", None)
        if hid:
            try:
                from database.models.genel_muhasebe import HesapPlani

                h = session.get(HesapPlani, int(hid))
                if h:
                    hesap_ad = h.hesap_adi
            except Exception:
                pass
        durum = (getattr(fis, "muhasebe_durum", None) or "").strip().upper() or None
        if not durum and KrediGiderFisiService.finansman_turu_mi(fis.gider_turu):
            durum = DURUM_BEKLIYOR if not getattr(fis, "muhasebe_hesap_kodu", None) else DURUM_HAZIR
        return {
            "id": fis.id,
            "belge_no": fis.belge_no,
            "tarih": fis.tarih,
            "gider_turu": fis.gider_turu,
            "tutar": _q(fis.tutar),
            "aciklama": fis.aciklama,
            "durum": fis.durum,
            "bagli_belge_no": fis.bagli_belge_no,
            "muhasebe_hesap_kodu": getattr(fis, "muhasebe_hesap_kodu", None),
            "muhasebe_hesap_id": hid,
            "muhasebe_hesap_adi": hesap_ad,
            "muhasebe_durum": durum,
            "muhasebe_durum_etiket": KrediGiderFisiService.durum_etiket(durum),
            "kaynak_kredi_id": getattr(fis, "kaynak_kredi_id", None),
        }

    @staticmethod
    def hesap_ata(
        fis_id: int,
        *,
        hesap_kodu: str | None = None,
        hesap_id: int | None = None,
        krediye_kaydet: bool = False,
        firma_eslemeye_kaydet: bool = False,
    ) -> dict[str, Any]:
        """Mevcut gider fişine hesap bağlar; ikinci gider kaydı oluşturmaz."""
        with get_session() as session:
            fis = session.get(GiderFisi, int(fis_id))
            if fis is None:
                raise ValueError("Gider fişi bulunamadı.")
            if (fis.durum or "").upper() == "IPTAL":
                raise ValueError("İptal fişe hesap atanamaz.")
            hesap = None
            if hesap_id:
                from database.models.genel_muhasebe import HesapPlani

                h = session.get(HesapPlani, int(hesap_id))
                if h is None or not h.aktif:
                    raise ValueError("Muhasebe hesabı bulunamadı veya pasif.")
                hesap = {"id": h.id, "kod": h.hesap_kodu, "ad": h.hesap_adi}
            elif hesap_kodu:
                hesap = KrediGiderFisiService._kodla_hesap(session, hesap_kodu)
                if hesap is None:
                    raise ValueError(f"Hesap kodu geçersiz: {hesap_kodu}")
            else:
                raise ValueError("Hesap kodu veya id gerekli.")

            onceki = {
                "kod": getattr(fis, "muhasebe_hesap_kodu", None),
                "id": getattr(fis, "muhasebe_hesap_id", None),
                "durum": getattr(fis, "muhasebe_durum", None),
            }
            fis.muhasebe_hesap_kodu = hesap["kod"]
            fis.muhasebe_hesap_id = hesap["id"]
            if (fis.muhasebe_durum or "") != DURUM_AKTARILDI:
                fis.muhasebe_durum = DURUM_HAZIR

            kredi = None
            kid = getattr(fis, "kaynak_kredi_id", None)
            if not kid and fis.bagli_belge_no:
                odeme = session.scalar(
                    select(BankaKrediOdeme).where(
                        BankaKrediOdeme.odeme_belge_no == fis.bagli_belge_no
                    )
                )
                if odeme:
                    kid = odeme.kredi_id
            if kid:
                kredi = session.get(BankaKredisi, int(kid))

            tur = (fis.gider_turu or "").upper()
            if krediye_kaydet and kredi is not None:
                if "FAIZ" in tur:
                    kredi.faiz_muhasebe_hesap_kodu = hesap["kod"]
                else:
                    kredi.masraf_muhasebe_hesap_kodu = hesap["kod"]

            anahtar_firma = None
            if firma_eslemeye_kaydet:
                anahtar_firma = KrediGiderFisiService.anahtar_icin(fis.gider_turu)

            session.flush()
            sonuc = {
                "fis": KrediGiderFisiService._fis_sozluk(session, fis),
                "onceki": onceki,
                "yeni": {"kod": hesap["kod"], "id": hesap["id"], "ad": hesap["ad"]},
            }
        if anahtar_firma:
            try:
                from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

                MuhasebeEntegrasyonService.kaydet(anahtar_firma, hesap["id"])
            except Exception:
                pass
        return sonuc

    @staticmethod
    def kredi_hesap_esleme_kaydet(
        kredi_id: int,
        *,
        faiz_hesap_kodu: str | None = None,
        masraf_hesap_kodu: str | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            kredi = session.get(BankaKredisi, int(kredi_id))
            if kredi is None:
                raise ValueError("Kredi bulunamadı.")
            if faiz_hesap_kodu is not None:
                kod = (faiz_hesap_kodu or "").strip() or None
                if kod and KrediGiderFisiService._kodla_hesap(session, kod) is None:
                    raise ValueError(f"Faiz hesap kodu geçersiz: {kod}")
                kredi.faiz_muhasebe_hesap_kodu = kod
            if masraf_hesap_kodu is not None:
                kod = (masraf_hesap_kodu or "").strip() or None
                if kod and KrediGiderFisiService._kodla_hesap(session, kod) is None:
                    raise ValueError(f"Masraf hesap kodu geçersiz: {kod}")
                kredi.masraf_muhasebe_hesap_kodu = kod
            session.flush()
            return {
                "kredi_id": kredi.id,
                "faiz_muhasebe_hesap_kodu": kredi.faiz_muhasebe_hesap_kodu,
                "masraf_muhasebe_hesap_kodu": kredi.masraf_muhasebe_hesap_kodu,
            }
