"""Hızlı Satış — sepet → onaylı fatura (Aşama 5) + beklet/geri çağır (Aşama 6)
+ iptal / kısmi iade (Aşama 7) + gün sonu / çıktı verisi (Aşama 8).

Mevcut `SatisFaturasiService` / `FinansService` / `SatisIadeFaturasiService` yollarını kullanır;
paralel belge üretmez.
`kaydet` + `onayla` gövdesi tek `get_session()` içinde çalıştırılır (iç içe oturum yok).

Bekleyen sepetler stok düşürmez / rezervasyon yapmaz (yalnızca DB kopyası).

Aşama 7 notu: tam iptal `SatisFaturasiService.iptal_et` ile stok/kasa/cari geri alır
(soft İPTAL + silinen kayıt günlüğü). Kısmi/tam iade `SatisIadeFaturasiService.kaydet`
ile kaynak faturaya bağlı iade belgesi üretir. POS komisyon / valör hareketleri
`fatura_tahsilatini_geri_al` kapsamı dışındadır (best-effort).

Aşama 8: `gun_sonu_ozeti` / `fatura_cikti_verisi` — yazdırma UI ayrı; işlem logu dosya.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import AccessError, yazma_zorunlu, yetki_var
from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.hizli_satis import (
    DURUM_BEKLIYOR,
    DURUM_CAGIRILDI,
    DURUM_IPTAL,
    HizliSatisBekleyen,
    HizliSatisBekleyenSatiri,
    HizliSatisGrubu,
    HizliSatisHizliUrun,
)
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri, SatisFaturasiTahsilati
from database.models.stok import Depo, StokKarti, StokLotu
from database.satis_faturasi_service import TAHSILAT_SEKILLERI, SatisFaturasiService
from database.satis_siparisi_service import decimal
from database.session_manager import oturum
from database.stok_service import StokService
from hizli_satis_musteri import IZIN_ACIK_HESAP, IZIN_IPTAL, acik_hesap_risk_degerlendir
from hizli_satis_sepet import VARSAYILAN_KDV

KURUS = Decimal("0.01")
VARSAYILAN_DEPO = "ANA DEPO"
HIZLI_SATIS_ETIKET = "Hızlı Satış"
HIZLI_SATIS_ETIKET_TAG = "[HIZLI_SATIS]"

# UI / servis: fatura tahsilat şekilleri + açık hesap (tahsilat satırı yok)
HIZLI_ODEME_SEKILLERI = TAHSILAT_SEKILLERI + ("AÇIK HESAP",)

_token_kilidi = threading.Lock()
_kullanilan_tokenler: set[str] = set()


def _kurus(tutar) -> Decimal:
    return Decimal(str(tutar)).quantize(KURUS, rounding=ROUND_HALF_UP)


def _kdv_orani(deger, varsayilan=VARSAYILAN_KDV) -> Decimal:
    """%0 KDV korunur; yalnızca None / eksik değer varsayılana düşer (`or 20` kullanılmaz)."""
    if deger is None:
        return decimal(varsayilan, "KDV", Decimal("0"))
    return decimal(deger, "KDV", Decimal("0"))


def _hizli_satis_mi(aciklama: str | None) -> bool:
    metin = (aciklama or "").strip()
    if not metin:
        return False
    lower = metin.casefold()
    return (
        HIZLI_SATIS_ETIKET.casefold() in lower
        or "hizli_satis" in lower
        or HIZLI_SATIS_ETIKET_TAG.casefold() in lower
    )


def _odeme_kovasi(odeme_sekli: str | None) -> str:
    """Nakit / kredi_karti / havale / diger."""
    s = (odeme_sekli or "").upper().replace("İ", "I").replace("ı", "I")
    if "NAKIT" in s or "KASA" in s:
        return "nakit"
    if "KART" in s or "POS" in s or "KREDI" in s:
        return "kredi_karti"
    if "HAVALE" in s or "EFT" in s:
        return "havale"
    return "diger"


def gun_sonu_ozet_hesapla(
    aktif_satislar: list[dict[str, Any]],
    *,
    iptaller: list[dict[str, Any]] | None = None,
    iadeler: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Saf özet hesaplama (DB yok — birim test için).

    Her aktif satış: genel_toplam, tahsilat_tutari, iskonto, kdv,
    tahsilatlar: [{odeme_sekli, tutar}].
    """
    odeme = {
        "nakit": Decimal("0.00"),
        "kredi_karti": Decimal("0.00"),
        "havale": Decimal("0.00"),
        "diger": Decimal("0.00"),
    }
    satis_toplami = Decimal("0.00")
    iskonto_toplami = Decimal("0.00")
    kdv_toplami = Decimal("0.00")
    tahsilat_toplami = Decimal("0.00")
    acik_hesap = Decimal("0.00")

    for s in aktif_satislar or []:
        genel = _kurus(s.get("genel_toplam") or 0)
        th = _kurus(s.get("tahsilat_tutari") or 0)
        satis_toplami += genel
        iskonto_toplami += _kurus(s.get("iskonto") or 0)
        kdv_toplami += _kurus(s.get("kdv") or 0)
        tahsilat_toplami += th
        kalan = _kurus(genel - th)
        if kalan > 0:
            acik_hesap += kalan
        satir_th = list(s.get("tahsilatlar") or [])
        if satir_th:
            for t in satir_th:
                kova = _odeme_kovasi(t.get("odeme_sekli"))
                odeme[kova] = _kurus(odeme[kova] + _kurus(t.get("tutar") or 0))
        elif th > 0:
            kova = _odeme_kovasi(s.get("tahsilat_sekli"))
            odeme[kova] = _kurus(odeme[kova] + th)

    iptal_list = iptaller or []
    iade_list = iadeler or []
    iptal_toplami = sum((_kurus(x.get("genel_toplam") or 0) for x in iptal_list), Decimal("0.00"))
    iade_toplami = sum((_kurus(x.get("genel_toplam") or 0) for x in iade_list), Decimal("0.00"))
    adet = len(aktif_satislar or [])
    ortalama = _kurus(satis_toplami / adet) if adet else Decimal("0.00")

    return {
        "satis_adedi": adet,
        "satis_toplami": _kurus(satis_toplami),
        "iskonto_toplami": _kurus(iskonto_toplami),
        "kdv_toplami": _kurus(kdv_toplami),
        "tahsilat_toplami": _kurus(tahsilat_toplami),
        "acik_hesap": _kurus(acik_hesap),
        "odeme_turleri": odeme,
        "iptal_adedi": len(iptal_list),
        "iptal_toplami": _kurus(iptal_toplami),
        "iade_adedi": len(iade_list),
        "iade_toplami": _kurus(iade_toplami),
        "ortalama_sepet": ortalama,
    }


class HizliSatisService:
    """Sepetten onaylı satış faturası üretir."""

    @staticmethod
    def yeni_idempotency_token() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def token_kullanildi_mi(token: str | None) -> bool:
        if not token:
            return False
        with _token_kilidi:
            return token in _kullanilan_tokenler

    @staticmethod
    def _token_rezerve_et(token: str) -> None:
        tok = (token or "").strip()
        if not tok:
            raise ValueError("İşlem jetonu (idempotency) zorunludur.")
        with _token_kilidi:
            if tok in _kullanilan_tokenler:
                raise ValueError(
                    "Bu satış zaten kaydedildi (çift gönderim engellendi). "
                    "Sepeti yenileyip tekrar deneyin."
                )
            _kullanilan_tokenler.add(tok)

    @staticmethod
    def _token_serbest_birak(token: str) -> None:
        with _token_kilidi:
            _kullanilan_tokenler.discard((token or "").strip())

    @staticmethod
    def hesap_adlari(odeme_sekli: str) -> list[str]:
        """Ödeme şekline uygun finans hesap adları (`FinansService.tahsilat_hesaplari`)."""
        hesaplar = FinansService.tahsilat_hesaplari(odeme_sekli)
        adlar = [h.hesap_adi for h in hesaplar if getattr(h, "hesap_adi", None)]
        if adlar:
            return adlar
        # POS alt hesabı yoksa eski varsayılan KK hesabına düş
        sekil = (odeme_sekli or "").upper().replace("İ", "I")
        if "KART" in sekil or "POS" in sekil:
            tum = FinansService.hesaplar()
            return [
                h.hesap_adi
                for h in tum
                if (h.hesap_turu or "").upper() == "KREDİ KARTI"
                or "POS" in (h.hesap_adi or "").upper()
            ]
        return []

    @staticmethod
    def stok_yeterlilik_kontrol(
        satirlar: list[dict[str, Any]] | Any,
        *,
        depo: str = VARSAYILAN_DEPO,
    ) -> list[str]:
        """UI + kayıt öncesi stok kontrolü. Dönüş: hata mesajları (boş = OK)."""
        depo_adi = (depo or VARSAYILAN_DEPO).strip() or VARSAYILAN_DEPO
        ihtiyac: dict[str, Decimal] = {}
        adlar: dict[str, str] = {}
        for ham in satirlar:
            if hasattr(ham, "stok_kodu"):
                kod = (ham.stok_kodu or "").strip()
                miktar = Decimal(str(getattr(ham, "miktar", 0) or 0))
                adi = (getattr(ham, "stok_adi", None) or kod).strip()
            else:
                kod = (ham.get("urun_kodu") or ham.get("stok_kodu") or "").strip()
                miktar = Decimal(str(ham.get("miktar") or 0))
                adi = (ham.get("urun_adi") or ham.get("stok_adi") or kod).strip()
            if not kod or miktar <= 0:
                continue
            ihtiyac[kod] = ihtiyac.get(kod, Decimal("0")) + miktar
            adlar[kod] = adi

        if not ihtiyac:
            return ["Sepet boş — stok kontrolü yapılamadı."]

        hatalar: list[str] = []
        with get_session() as session:
            depo_row = session.scalar(select(Depo).where(Depo.ad == depo_adi))
            if not depo_row:
                return [f"{depo_adi} deposu bulunamadı."]
            for kod, istenen in ihtiyac.items():
                stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
                if not stok or getattr(stok, "is_deleted", False) or not getattr(stok, "aktif", True):
                    hatalar.append(f"{adlar.get(kod, kod)} ({kod}): stok kartı yok veya pasif.")
                    continue
                lotlar = list(
                    session.scalars(
                        select(StokLotu).where(
                            StokLotu.stok_id == stok.id,
                            StokLotu.depo_id == depo_row.id,
                            StokLotu.kalan_miktar > 0,
                        )
                    ).all()
                )
                mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
                if mevcut < istenen:
                    hatalar.append(
                        f"{adlar.get(kod, kod)} ({kod}): stok yetersiz. "
                        f"Mevcut: {mevcut}, istenen: {istenen}"
                    )
        return hatalar

    @staticmethod
    def _sepetten_satirlar(sepet) -> list[dict[str, Any]]:
        satirlar: list[dict[str, Any]] = []
        kaynak = sepet.satirlar if hasattr(sepet, "satirlar") else list(sepet)
        for s in kaynak:
            if hasattr(s, "stok_kodu"):
                satirlar.append(
                    {
                        "urun_kodu": (s.stok_kodu or "").strip(),
                        "urun_adi": (s.stok_adi or "").strip(),
                        "barkod": getattr(s, "barkod", None),
                        "miktar": s.miktar,
                        "birim": getattr(s, "birim", None) or "Adet",
                        "birim_fiyat": s.birim_fiyat,
                        "iskonto_orani": getattr(s, "iskonto_orani", 0) or 0,
                        "kdv_orani": _kdv_orani(getattr(s, "kdv_orani", None)),
                    }
                )
            else:
                satirlar.append(dict(s))
        return satirlar

    @staticmethod
    def _genel_toplam_satirlardan(satir_verileri: list[dict]) -> Decimal:
        # Geçici satır nesneleri ile SatisFaturasiService.toplam kullan
        class _S:
            pass

        gecici = []
        for v in satir_verileri:
            s = _S()
            s.miktar = decimal(v["miktar"], "Miktar", Decimal("0.0001"))
            s.birim_fiyat = decimal(v["birim_fiyat"], "Birim fiyat", Decimal("0"))
            s.iskonto_orani = decimal(v.get("iskonto_orani", 0), "İskonto 1", Decimal("0"))
            s.iskonto_orani_2 = decimal(v.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0"))
            s.iskonto_orani_3 = decimal(v.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0"))
            s.kdv_orani = _kdv_orani(v.get("kdv_orani"))
            gecici.append(s)
        return SatisFaturasiService.toplam(gecici)["genel_toplam"]

    @staticmethod
    def _tahsilatlari_normalize(
        tahsilatlar: list[dict] | None,
        *,
        genel_toplam: Decimal,
        tarih: date,
    ) -> tuple[list[dict], Decimal]:
        """Geçerli tahsilat satırları + toplam tutar. Açık hesap satırları elenir."""
        sonuc: list[dict] = []
        toplam = Decimal("0")
        for ham in tahsilatlar or []:
            sekil = (ham.get("odeme_sekli") or "").strip()
            if not sekil:
                continue
            if "ACIK HESAP" in sekil.upper().replace("İ", "I").replace("Ç", "C"):
                continue
            tutar = _kurus(decimal(ham.get("tutar", 0), "Tahsilat tutarı", Decimal("0.01")))
            if tutar <= 0:
                continue
            hesap = (ham.get("hesap") or "").strip()
            if not hesap:
                raise ValueError(f"«{sekil}» için kasa/banka/POS hesabı seçin.")
            if sekil not in TAHSILAT_SEKILLERI:
                # Bilinen eş anlamlılar
                u = sekil.upper().replace("İ", "I")
                if "NAKIT" in u or "KASA" in u:
                    sekil = "NAKİT / KASA"
                elif "HAVALE" in u:
                    sekil = "GELEN HAVALE"
                elif "KART" in u or "POS" in u:
                    sekil = "KREDİ KARTIYLA TAHSİLAT"
                else:
                    raise ValueError(f"Geçersiz ödeme şekli: {sekil}")
            sonuc.append(
                {
                    "tahsilat_tarihi": ham.get("tahsilat_tarihi") or tarih,
                    "tutar": tutar,
                    "odeme_sekli": sekil,
                    "hesap": hesap,
                    "aciklama": (ham.get("aciklama") or None),
                }
            )
            toplam += tutar
        toplam = _kurus(toplam)
        if toplam > genel_toplam:
            raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")
        return sonuc, toplam

    @staticmethod
    def _acik_hesap_enforce(
        *,
        kalan: Decimal,
        bakiye=0,
        risk_limiti=None,
    ) -> None:
        if kalan <= 0:
            return
        if not yetki_var(IZIN_ACIK_HESAP):
            raise AccessError(
                "Açık hesap / kısmi tahsilat için «hizli_satis_acik_hesap» yetkisi gerekir."
            )
        risk = acik_hesap_risk_degerlendir(
            bakiye=bakiye,
            risk_limiti=risk_limiti,
            ek_tutar=kalan,
            acik_hesap_yetkisi=True,
        )
        # Yetki varken bile sert engel (limit 0 + borç) — Stage 4 engel durumunu koru
        # acik_hesap_yetkisi=True ile engel→uyari olur; ekstra blok yok.
        if risk["durum"] == "engel":
            raise AccessError(risk["mesaj"] or "Risk limiti aşıldı.")

    @staticmethod
    def satisi_tamamla(
        *,
        sepet,
        cari_id: int,
        tahsilatlar: list[dict] | None,
        idempotency_token: str,
        depo: str = VARSAYILAN_DEPO,
        fatura_tarihi: date | None = None,
        vade_tarihi: date | None = None,
        aciklama: str | None = None,
        musteri_bakiye=None,
        risk_limiti=None,
    ) -> dict[str, Any]:
        """Sepeti onaylı satış faturasına çevirir (tek DB transaction).

        Dönüş: {fatura_id, fatura_no, genel_toplam, tahsilat_tutari, kalan, onaylandi, durum}
        """
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        HizliSatisService._token_rezerve_et(idempotency_token)

        try:
            satir_verileri = HizliSatisService._sepetten_satirlar(sepet)
            if not satir_verileri:
                raise ValueError("Sepet boş — satış tamamlanamaz.")

            hatalar = HizliSatisService.stok_yeterlilik_kontrol(satir_verileri, depo=depo)
            if hatalar:
                raise ValueError("Stok yetersiz — eksi stoka izin yok.\n" + "\n".join(hatalar))

            tarih = fatura_tarihi or date.today()
            if tarih > date.today():
                raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
            vade = vade_tarihi or tarih
            if vade < tarih:
                raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")

            genel = HizliSatisService._genel_toplam_satirlardan(satir_verileri)
            if genel <= 0:
                raise ValueError("Satış tutarı sıfır olamaz.")

            th_listesi, tahsilat_toplam = HizliSatisService._tahsilatlari_normalize(
                tahsilatlar, genel_toplam=genel, tarih=tarih
            )
            kalan = _kurus(genel - tahsilat_toplam)
            HizliSatisService._acik_hesap_enforce(
                kalan=kalan,
                bakiye=musteri_bakiye or 0,
                risk_limiti=risk_limiti,
            )

            veriler = {
                "fatura_tarihi": tarih,
                "vade_tarihi": vade,
                "cari_id": int(cari_id),
                "depo": (depo or VARSAYILAN_DEPO).strip() or VARSAYILAN_DEPO,
                "aciklama": (aciklama or HIZLI_SATIS_ETIKET).strip() or HIZLI_SATIS_ETIKET,
                "para_birimi": "TRY",
                "kur": Decimal("1"),
                "islem_saati": datetime.now().strftime("%H:%M"),
            }

            fatura_id = HizliSatisService._kaydet_ve_onayla_tek_session(
                veriler, satir_verileri, th_listesi
            )
        except Exception:
            HizliSatisService._token_serbest_birak(idempotency_token)
            raise

        fatura = SatisFaturasiService.getir(fatura_id)
        toplam = SatisFaturasiService.toplam(fatura.satirlar)
        th = _kurus(getattr(fatura, "tahsilat_tutari", 0) or 0)
        genel_t = toplam["genel_toplam"]
        return {
            "fatura_id": int(fatura.id),
            "fatura_no": fatura.fatura_no,
            "genel_toplam": genel_t,
            "tahsilat_tutari": th,
            "kalan": _kurus(genel_t - th),
            "onaylandi": bool(getattr(fatura, "onaylandi", False)),
            "durum": fatura.durum,
            "fatura": fatura,
        }

    @staticmethod
    def _sonraki_fatura_no(session) -> str:
        """Aynı oturumda SF-##### üretir (iç içe get_session yok)."""
        onek = "SF-"
        numaralar = session.scalars(
            select(SatisFaturasi.fatura_no).where(SatisFaturasi.fatura_no.like(f"{onek}%"))
        ).all()
        max_sira = 0
        for no in numaralar:
            kuyruk = str(no)[len(onek) :]
            if kuyruk.isdigit():
                max_sira = max(max_sira, int(kuyruk))
        return f"{onek}{max_sira + 1:05d}"

    @staticmethod
    def _kaydet_ve_onayla_tek_session(
        veriler: dict,
        satir_verileri: list[dict],
        tahsilat_verileri: list[dict],
    ) -> int:
        """Taslak kaydet + onayla tek commit (iç içe get_session yok)."""
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            current_actor,
            require_user_session,
            stamp_approve,
            stamp_create,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        actor = current_actor()
        with get_session() as session:
            cari = session.get(Cari, int(veriler["cari_id"]))
            if not cari or getattr(cari, "is_deleted", False) or not getattr(cari, "aktif", True):
                raise ValueError("Geçerli bir müşteri (cari) seçin.")

            fatura_no = HizliSatisService._sonraki_fatura_no(session)

            tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
            fatura = SatisFaturasi(fatura_no=fatura_no)
            session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (veriler.get("islem_saati") or "").strip() or datetime.now().strftime(
                "%H:%M"
            )
            fatura.cari_id = int(veriler["cari_id"])
            fatura.depo = veriler.get("depo") or VARSAYILAN_DEPO
            fatura.aciklama = veriler.get("aciklama") or None
            fatura.siparis_id = None
            fatura.irsaliye_id = None
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))

            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                doviz_satir = SatisFaturasiService._satir_doviz_alanlari(veri, kur, pb)
                fatura.satirlar.append(
                    SatisFaturasiSatiri(
                        urun_kodu=veri["urun_kodu"].strip(),
                        urun_adi=veri["urun_adi"].strip(),
                        barkod=veri.get("barkod") or None,
                        miktar=miktar,
                        birim=veri.get("birim") or "Adet",
                        birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                        iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto 1", Decimal("0")),
                        iskonto_orani_2=decimal(veri.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0")),
                        iskonto_orani_3=decimal(veri.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0")),
                        kdv_orani=_kdv_orani(veri.get("kdv_orani")),
                        birim_fiyat_doviz=doviz_satir["birim_fiyat_doviz"],
                        tl_birim_fiyat=doviz_satir["tl_birim_fiyat"],
                        tl_tutar=doviz_satir["tl_tutar"],
                    )
                )

            tahsilat_toplam = Decimal("0")
            for veri in tahsilat_verileri:
                tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
                tahsilat_toplam += tutar
                fatura.tahsilatlar.append(
                    SatisFaturasiTahsilati(
                        tahsilat_tarihi=veri.get("tahsilat_tarihi") or tarih,
                        tutar=tutar,
                        odeme_sekli=veri["odeme_sekli"],
                        hesap=veri["hesap"],
                        aciklama=veri.get("aciklama") or "Hızlı satış tahsilatı",
                    )
                )

            toplam_dict = SatisFaturasiService.toplam(fatura.satirlar)
            toplam = toplam_dict["genel_toplam"]
            SatisFaturasiService._doviz_alanlarini_yaz(fatura, veriler, toplam_dict)
            if tahsilat_toplam > toplam:
                raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")
            fatura.tahsilat_tutari = tahsilat_toplam
            ilk = fatura.tahsilatlar[0] if fatura.tahsilatlar else None
            fatura.tahsilat_sekli = ilk.odeme_sekli if ilk else None
            fatura.tahsilat_hesabi = ilk.hesap if ilk else None
            fatura.onaylandi = False
            fatura.durum = "TASLAK"
            stamp_create(fatura)
            # Hızlı satışta satış personeli = işlem yapan kullanıcı
            fatura.sales_person_id = actor.get("user_id")
            fatura.sales_person_full_name = actor.get("full_name")
            fatura.tahsilat_alan_user_id = actor["user_id"]
            fatura.tahsilat_alan_full_name = actor["full_name"]
            fatura.kasa_terminal = (veriler.get("kasa_terminal") or "").strip() or None
            fatura.satis_baslangic = veriler.get("satis_baslangic") or actor["now"]
            fatura.satis_bitis = actor["now"]
            session.flush()

            # —— Onay (aynı session) ——
            for satir in fatura.satirlar:
                try:
                    stok_cikisi = StokService.fatura_cikisi(
                        session,
                        fatura.fatura_no,
                        tarih,
                        satir.urun_kodu.strip(),
                        fatura.depo,
                        satir.miktar,
                        satir.lot_no or "",
                    )
                except ValueError as hata:
                    mesaj = str(hata)
                    if "stok yetersiz" in mesaj.casefold() or "yetersiz" in mesaj.casefold():
                        raise ValueError(
                            f"Fatura onaylanamadı — eksi stoka izin yok.\n{mesaj}"
                        ) from hata
                    raise ValueError(f"Fatura onaylanamadı.\n{mesaj}") from hata
                satir.lot_cikisi = stok_cikisi["lot_cikisi"]
                satir.fifo_birim_maliyeti = stok_cikisi["fifo_birim_maliyeti"]

            hareket = session.scalar(
                select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
            )
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id = fatura.cari_id
            hareket.satis_tarihi = tarih
            hareket.satis_tutari = toplam
            hareket.kalan_acik_tutar = toplam - tahsilat_toplam
            hareket.para_birimi = "TRY"
            hareket.kur = Decimal("1")
            hareket.borc_esasi = "TL_SABIT"
            hareket.doviz_tutari = Decimal("0")

            for th in fatura.tahsilatlar:
                if Decimal(str(th.tutar or 0)) <= 0:
                    continue
                FinansService.fatura_tahsilati(
                    session,
                    fatura.fatura_no,
                    th.tahsilat_tarihi,
                    th.tutar,
                    th.odeme_sekli,
                    th.hesap,
                )

            fatura.durum = "KAPALI" if tahsilat_toplam >= toplam else "AÇIK"
            fatura.onaylandi = True
            stamp_approve(fatura)
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi / onaylanamadı.") from hata
            fid = int(fatura.id)
            fno = fatura.fatura_no

        audit_document(
            "HIZLI_SATIS_TAMAMLA",
            modul="hizli_satis",
            kayit_id=str(fid),
            belge_no=fno,
        )
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("satis_faturasi_fisi", fid)
        return fid

    # —— Aşama 6: beklet / geri çağır (stok hareketi yok) ——

    @staticmethod
    def schema_hazirla() -> None:
        """Bekleyen + hızlı ürün pin tablolarını oluştur (checkfirst; veri silinmez)."""
        from database.database import engine

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401

        for tablo in (
            HizliSatisBekleyen.__table__,
            HizliSatisBekleyenSatiri.__table__,
            HizliSatisGrubu.__table__,
            HizliSatisHizliUrun.__table__,
        ):
            tablo.create(engine, checkfirst=True)

    # —— Ürün pin (ÜRÜN EKLE) — stok hareketi / muhasebe yok ——

    STOK_GRUBU_UYARI = (
        "Bu ürün herhangi bir stok grubuna bağlı değildir. "
        "Hızlı Satış ekranına ekleyebilmek için önce bir stok grubu seçiniz."
    )

    @staticmethod
    def pin_sistemi_aktif() -> bool:
        """En az bir hızlı satış grubu veya pin varsa pin modu."""
        HizliSatisService.schema_hazirla()
        with get_session() as session:
            g = session.scalar(select(HizliSatisGrubu.id).limit(1))
            if g:
                return True
            p = session.scalar(select(HizliSatisHizliUrun.id).limit(1))
            return bool(p)

    @staticmethod
    def hizli_gruplari_listele(*, sadece_aktif: bool = True) -> list[dict[str, Any]]:
        """POS sol panel hızlı satış grupları (rapor_grubu değil)."""
        HizliSatisService.schema_hazirla()
        with get_session() as session:
            q = select(HizliSatisGrubu)
            if sadece_aktif:
                q = q.where(HizliSatisGrubu.aktif.is_(True))
            q = q.order_by(HizliSatisGrubu.sira_no, HizliSatisGrubu.ad)
            return [
                {
                    "id": int(g.id),
                    "kod": f"HSG:{int(g.id)}",
                    "ad": g.ad,
                    "sira_no": int(g.sira_no or 0),
                    "aktif": bool(g.aktif),
                    "ozel": False,
                    "pin_grup": True,
                }
                for g in session.scalars(q).all()
            ]

    @staticmethod
    def hizli_grup_olustur(ad: str, *, sira_no: int | None = None) -> dict[str, Any]:
        """Yeni hızlı satış grubu (kullanıcı onayı UI tarafında)."""
        HizliSatisService.schema_hazirla()
        temiz = (ad or "").strip()
        if not temiz:
            raise ValueError("Hızlı satış grubu adı boş olamaz.")
        from sqlalchemy import func as sa_func

        with get_session() as session:
            mevcut = session.scalar(
                select(HizliSatisGrubu).where(
                    sa_func.lower(HizliSatisGrubu.ad) == temiz.casefold()
                )
            )
            if mevcut:
                return {
                    "id": int(mevcut.id),
                    "kod": f"HSG:{int(mevcut.id)}",
                    "ad": mevcut.ad,
                    "sira_no": int(mevcut.sira_no or 0),
                    "aktif": bool(mevcut.aktif),
                    "yeni": False,
                }
            if sira_no is None:
                max_sira = session.scalar(
                    select(sa_func.coalesce(sa_func.max(HizliSatisGrubu.sira_no), 0))
                )
                sira_no = int(max_sira or 0) + 10
            grup = HizliSatisGrubu(
                ad=temiz,
                sira_no=int(sira_no),
                aktif=True,
                olusturma_tarihi=datetime.now(),
                guncelleme_tarihi=datetime.now(),
            )
            session.add(grup)
            session.flush()
            return {
                "id": int(grup.id),
                "kod": f"HSG:{int(grup.id)}",
                "ad": grup.ad,
                "sira_no": int(grup.sira_no or 0),
                "aktif": True,
                "yeni": True,
            }

    @staticmethod
    def hizli_grup_bul_veya_hazirla(
        ad: str, *, olustur: bool = False
    ) -> dict[str, Any] | None:
        """Ada göre hızlı satış grubu; olustur=False ise yoksa None."""
        temiz = (ad or "").strip()
        if not temiz:
            return None
        HizliSatisService.schema_hazirla()
        from sqlalchemy import func as sa_func

        with get_session() as session:
            mevcut = session.scalar(
                select(HizliSatisGrubu).where(
                    sa_func.lower(HizliSatisGrubu.ad) == temiz.casefold()
                )
            )
            if mevcut:
                return {
                    "id": int(mevcut.id),
                    "kod": f"HSG:{int(mevcut.id)}",
                    "ad": mevcut.ad,
                    "sira_no": int(mevcut.sira_no or 0),
                    "aktif": bool(mevcut.aktif),
                    "yeni": False,
                }
        if olustur:
            return HizliSatisService.hizli_grup_olustur(temiz)
        return None

    @staticmethod
    def _grup_id_coz(hizli_satis_grubu_id: int | None = None, grup_kod: str | None = None) -> int:
        if hizli_satis_grubu_id:
            return int(hizli_satis_grubu_id)
        kod = (grup_kod or "").strip()
        if kod.startswith("HSG:"):
            return int(kod.split(":", 1)[1])
        raise ValueError("Geçerli hızlı satış grubu seçilmedi.")

    @staticmethod
    def pin_ekle(
        stok_id: int,
        *,
        hizli_satis_grubu_id: int | None = None,
        grup_kod: str | None = None,
        grup_adi: str | None = None,
        kisa_ad: str | None = None,
        sira_no: int | None = None,
        kart_rengi: str | None = None,
        gorsel_yolu: str | None = None,
        varsayilan_birim: str | None = None,
        varsayilan_miktar: Decimal | str | float | int = 1,
        aktif: bool = True,
        stok_grubu_zorunlu: bool = True,
        grup_olustur_onayli: bool = False,
    ) -> dict[str, Any]:
        """Stok kartını Hızlı Satış'a pinler. Stok hareketi yok."""
        HizliSatisService.schema_hazirla()
        sid = int(stok_id)
        if sid <= 0:
            raise ValueError("Geçersiz stok.")

        with get_session() as session:
            stok = session.scalar(
                select(StokKarti).where(
                    StokKarti.id == sid,
                    *StokService._aktif_stok_kosulu(),
                )
            )
            if not stok:
                raise ValueError("Stok kartı bulunamadı veya pasif/silinmiş.")

            rapor = (stok.rapor_grubu or "").strip()
            if stok_grubu_zorunlu and not rapor:
                raise ValueError(HizliSatisService.STOK_GRUBU_UYARI)

            gid: int | None = None
            if hizli_satis_grubu_id or (grup_kod or "").strip().startswith("HSG:"):
                gid = HizliSatisService._grup_id_coz(hizli_satis_grubu_id, grup_kod)
            else:
                hedef_ad = (grup_adi or "").strip() or rapor
                if not hedef_ad:
                    raise ValueError("Hızlı satış grubu belirtilmedi.")
                from sqlalchemy import func as sa_func

                mevcut_g = session.scalar(
                    select(HizliSatisGrubu).where(
                        sa_func.lower(HizliSatisGrubu.ad) == hedef_ad.casefold()
                    )
                )
                if mevcut_g:
                    gid = int(mevcut_g.id)
                elif grup_olustur_onayli:
                    max_sira = session.scalar(
                        select(sa_func.coalesce(sa_func.max(HizliSatisGrubu.sira_no), 0))
                    )
                    yeni_g = HizliSatisGrubu(
                        ad=hedef_ad,
                        sira_no=int(max_sira or 0) + 10,
                        aktif=True,
                        olusturma_tarihi=datetime.now(),
                        guncelleme_tarihi=datetime.now(),
                    )
                    session.add(yeni_g)
                    session.flush()
                    gid = int(yeni_g.id)
                else:
                    raise ValueError(
                        f"«{hedef_ad}» adlı hızlı satış grubu yok. "
                        "Oluşturmak için onay gerekli."
                    )

            grup = session.get(HizliSatisGrubu, gid)
            if not grup or not grup.aktif:
                raise ValueError("Hızlı satış grubu bulunamadı veya pasif.")

            mevcut_pin = session.scalar(
                select(HizliSatisHizliUrun).where(
                    HizliSatisHizliUrun.stok_id == sid,
                    HizliSatisHizliUrun.hizli_satis_grubu_id == gid,
                )
            )
            if mevcut_pin:
                raise ValueError(
                    f"«{stok.stok_kodu}» bu hızlı satış grubunda zaten kayıtlı."
                )

            if sira_no is None:
                from sqlalchemy import func as sa_func

                max_s = session.scalar(
                    select(
                        sa_func.coalesce(sa_func.max(HizliSatisHizliUrun.sira_no), 0)
                    ).where(HizliSatisHizliUrun.hizli_satis_grubu_id == gid)
                )
                sira_no = int(max_s or 0) + 10

            miktar = decimal(varsayilan_miktar, "varsayılan miktar", Decimal("1"))
            if miktar <= 0:
                raise ValueError("Varsayılan miktar sıfırdan büyük olmalıdır.")

            pin = HizliSatisHizliUrun(
                stok_id=sid,
                hizli_satis_grubu_id=gid,
                kisa_ad=(kisa_ad or "").strip() or None,
                sira_no=int(sira_no),
                kart_rengi=(kart_rengi or "").strip() or None,
                gorsel_yolu=(gorsel_yolu or "").strip() or None,
                varsayilan_birim=(varsayilan_birim or "").strip() or None,
                varsayilan_miktar=miktar,
                aktif=bool(aktif),
                olusturma_tarihi=datetime.now(),
                guncelleme_tarihi=datetime.now(),
            )
            session.add(pin)
            session.flush()
            return {
                "id": int(pin.id),
                "stok_id": sid,
                "hizli_satis_grubu_id": gid,
                "hizli_satis_grubu": grup.ad,
                "kisa_ad": pin.kisa_ad,
                "sira_no": int(pin.sira_no),
                "aktif": bool(pin.aktif),
            }

    @staticmethod
    def pin_guncelle(pin_id: int, **alanlar) -> dict[str, Any]:
        HizliSatisService.schema_hazirla()
        with get_session() as session:
            pin = session.get(HizliSatisHizliUrun, int(pin_id))
            if not pin:
                raise ValueError("Pin kaydı bulunamadı.")
            if "kisa_ad" in alanlar:
                pin.kisa_ad = (alanlar.get("kisa_ad") or "").strip() or None
            if "kart_rengi" in alanlar:
                pin.kart_rengi = (alanlar.get("kart_rengi") or "").strip() or None
            if "gorsel_yolu" in alanlar:
                pin.gorsel_yolu = (alanlar.get("gorsel_yolu") or "").strip() or None
            if "varsayilan_birim" in alanlar:
                pin.varsayilan_birim = (alanlar.get("varsayilan_birim") or "").strip() or None
            if "varsayilan_miktar" in alanlar:
                m = decimal(alanlar["varsayilan_miktar"], "varsayılan miktar", Decimal("1"))
                if m <= 0:
                    raise ValueError("Varsayılan miktar sıfırdan büyük olmalıdır.")
                pin.varsayilan_miktar = m
            if "aktif" in alanlar:
                pin.aktif = bool(alanlar["aktif"])
            if "sira_no" in alanlar and alanlar["sira_no"] is not None:
                pin.sira_no = int(alanlar["sira_no"])
            if "hizli_satis_grubu_id" in alanlar and alanlar["hizli_satis_grubu_id"]:
                yeni_gid = int(alanlar["hizli_satis_grubu_id"])
                if yeni_gid != pin.hizli_satis_grubu_id:
                    cakisan = session.scalar(
                        select(HizliSatisHizliUrun).where(
                            HizliSatisHizliUrun.stok_id == pin.stok_id,
                            HizliSatisHizliUrun.hizli_satis_grubu_id == yeni_gid,
                            HizliSatisHizliUrun.id != pin.id,
                        )
                    )
                    if cakisan:
                        raise ValueError("Bu ürün hedef grupta zaten var.")
                    grup = session.get(HizliSatisGrubu, yeni_gid)
                    if not grup:
                        raise ValueError("Hedef hızlı satış grubu yok.")
                    pin.hizli_satis_grubu_id = yeni_gid
            pin.guncelleme_tarihi = datetime.now()
            session.flush()
            return {
                "id": int(pin.id),
                "stok_id": int(pin.stok_id),
                "hizli_satis_grubu_id": int(pin.hizli_satis_grubu_id),
                "aktif": bool(pin.aktif),
                "sira_no": int(pin.sira_no),
            }

    @staticmethod
    def pin_kaldir(pin_id: int) -> dict[str, Any]:
        """Hızlı Satış'tan kaldırır; stok kartını silmez."""
        HizliSatisService.schema_hazirla()
        with get_session() as session:
            pin = session.get(HizliSatisHizliUrun, int(pin_id))
            if not pin:
                raise ValueError("Pin kaydı bulunamadı.")
            stok_id = int(pin.stok_id)
            session.delete(pin)
            session.flush()
            stok = session.get(StokKarti, stok_id)
            return {
                "kaldirildi": True,
                "stok_id": stok_id,
                "stok_kodu": getattr(stok, "stok_kodu", None),
                "stok_var": stok is not None
                and not bool(getattr(stok, "is_deleted", False)),
            }

    @staticmethod
    def pin_sira_tasi(pin_id: int, yon: str) -> None:
        """yon: left|right|first|last (aynı grup içinde sira_no)."""
        HizliSatisService.schema_hazirla()
        yon = (yon or "").strip().lower()
        with get_session() as session:
            pin = session.get(HizliSatisHizliUrun, int(pin_id))
            if not pin:
                raise ValueError("Pin kaydı bulunamadı.")
            kardesler = list(
                session.scalars(
                    select(HizliSatisHizliUrun)
                    .where(
                        HizliSatisHizliUrun.hizli_satis_grubu_id
                        == pin.hizli_satis_grubu_id
                    )
                    .order_by(HizliSatisHizliUrun.sira_no, HizliSatisHizliUrun.id)
                ).all()
            )
            idx = next((i for i, p in enumerate(kardesler) if p.id == pin.id), None)
            if idx is None:
                return
            if yon == "first":
                kardesler.insert(0, kardesler.pop(idx))
            elif yon == "last":
                kardesler.append(kardesler.pop(idx))
            elif yon == "left" and idx > 0:
                kardesler[idx - 1], kardesler[idx] = kardesler[idx], kardesler[idx - 1]
            elif yon == "right" and idx < len(kardesler) - 1:
                kardesler[idx + 1], kardesler[idx] = kardesler[idx], kardesler[idx + 1]
            for i, p in enumerate(kardesler):
                p.sira_no = (i + 1) * 10
                p.guncelleme_tarihi = datetime.now()
            session.flush()

    @staticmethod
    def pin_toplu_ekle(
        stok_idler: list[int],
        *,
        hizli_satis_grubu_id: int | None = None,
        grup_kod: str | None = None,
        grup_adi: str | None = None,
        grup_olustur_onayli: bool = False,
    ) -> dict[str, Any]:
        eklenen, atlanan, hatalar = [], [], []
        for sid in stok_idler or []:
            try:
                kayit = HizliSatisService.pin_ekle(
                    int(sid),
                    hizli_satis_grubu_id=hizli_satis_grubu_id,
                    grup_kod=grup_kod,
                    grup_adi=grup_adi,
                    grup_olustur_onayli=grup_olustur_onayli,
                )
                eklenen.append(kayit)
            except ValueError as exc:
                msg = str(exc)
                if "zaten" in msg.casefold():
                    atlanan.append({"stok_id": int(sid), "neden": msg})
                else:
                    hatalar.append({"stok_id": int(sid), "neden": msg})
            except Exception as exc:  # noqa: BLE001
                hatalar.append({"stok_id": int(sid), "neden": str(exc)})
        return {
            "eklenen": len(eklenen),
            "atlanan": len(atlanan),
            "basarisiz": len(hatalar),
            "detay_eklenen": eklenen,
            "detay_atlanan": atlanan,
            "detay_hata": hatalar,
        }

    @staticmethod
    def pinli_urunleri(
        grup_kod: str | None = None,
        *,
        hizli_satis_grubu_id: int | None = None,
        limit: int = 36,
        offset: int = 0,
        fiyat_adi: str | None = None,
        sadece_aktif: bool = True,
    ) -> dict[str, Any]:
        """Pinli ürünler; fiyat/stok ana karttan canlı."""
        HizliSatisService.schema_hazirla()
        limit = max(1, min(int(limit or 36), 120))
        offset = max(0, int(offset or 0))
        try:
            gid = HizliSatisService._grup_id_coz(hizli_satis_grubu_id, grup_kod)
        except ValueError:
            return {"urunler": [], "toplam": 0, "limit": limit, "offset": offset}

        with get_session() as session:
            kosul = [HizliSatisHizliUrun.hizli_satis_grubu_id == gid]
            if sadece_aktif:
                kosul.append(HizliSatisHizliUrun.aktif.is_(True))
            from sqlalchemy import func as sa_func

            toplam = (
                session.scalar(
                    select(sa_func.count())
                    .select_from(HizliSatisHizliUrun)
                    .where(*kosul)
                )
                or 0
            )
            pinler = list(
                session.scalars(
                    select(HizliSatisHizliUrun)
                    .where(*kosul)
                    .order_by(HizliSatisHizliUrun.sira_no, HizliSatisHizliUrun.id)
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            if not pinler:
                return {
                    "urunler": [],
                    "toplam": int(toplam),
                    "limit": limit,
                    "offset": offset,
                }

            stok_ids = [int(p.stok_id) for p in pinler]
            stoklar = {
                int(s.id): s
                for s in session.scalars(
                    select(StokKarti)
                    .where(
                        StokKarti.id.in_(stok_ids),
                        *StokService._aktif_stok_kosulu(),
                    )
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.resimler),
                        selectinload(StokKarti.barkodlar),
                        selectinload(StokKarti.birimler),
                    )
                ).all()
            }
            urunler = []
            for pin in pinler:
                stok = stoklar.get(int(pin.stok_id))
                if not stok:
                    continue
                d = StokService._hizli_satis_urun_dict(stok, fiyat_adi)
                if pin.kisa_ad:
                    d["stok_adi"] = pin.kisa_ad
                    d["kisa_ad"] = pin.kisa_ad
                if pin.varsayilan_birim:
                    d["birim"] = pin.varsayilan_birim
                d["miktar"] = Decimal(str(pin.varsayilan_miktar or 1))
                if pin.gorsel_yolu:
                    d["resim_yolu"] = pin.gorsel_yolu
                d["pin_id"] = int(pin.id)
                d["kart_rengi"] = pin.kart_rengi
                d["sira_no"] = int(pin.sira_no or 0)
                d["pin_aktif"] = bool(pin.aktif)
                d["hizli_satis_grubu_id"] = int(pin.hizli_satis_grubu_id)
                urunler.append(d)
            return {
                "urunler": urunler,
                "toplam": int(toplam),
                "limit": limit,
                "offset": offset,
            }

    @staticmethod
    def save_hold(
        sepet: Any,
        *,
        cari_id: int | None = None,
        cari_kodu: str | None = None,
        cari_unvan: str | None = None,
        etiket: str | None = None,
        not_: str | None = None,
        odeme_niyeti: str | None = None,
    ) -> dict[str, Any]:
        """Sepeti bekleyenlere kaydeder. Stok düşmez.

        Dönüş: {id, etiket, satir_sayisi, genel_toplam, olusturma_tarihi}
        """
        yazma_zorunlu("satis_duzenleme", "satis_goruntuleme")
        HizliSatisService.schema_hazirla()

        satirlar = list(getattr(sepet, "satirlar", None) or [])
        if not satirlar:
            raise ValueError("Bekletmek için sepete en az bir ürün ekleyin.")

        if hasattr(sepet, "toplamlar"):
            genel = _kurus(sepet.toplamlar().get("genel_toplam") or 0)
        else:
            genel = Decimal("0.00")

        etiket_temiz = (etiket or "").strip() or None
        not_temiz = (not_ or "").strip() or None
        kod = (cari_kodu or "").strip() or None
        unvan = (cari_unvan or "").strip() or None
        cid = int(cari_id) if cari_id else None
        if cid is not None and cid <= 0:
            cid = None

        with get_session() as session:
            baslik = HizliSatisBekleyen(
                etiket=etiket_temiz,
                cari_id=cid,
                cari_kodu=kod,
                cari_unvan=unvan,
                kullanici_id=getattr(oturum, "user_id", None),
                kullanici_adi=getattr(oturum, "kullanici_adi", None)
                or getattr(oturum, "ad_soyad", None),
                durum=DURUM_BEKLIYOR,
                genel_toplam=genel,
                satir_sayisi=len(satirlar),
                odeme_niyeti=(odeme_niyeti or "").strip() or None,
                not_=not_temiz,
                olusturma_tarihi=datetime.now(),
                guncelleme_tarihi=datetime.now(),
            )
            session.add(baslik)
            session.flush()

            for i, satir in enumerate(satirlar):
                if isinstance(satir, dict):
                    stok_id = int(satir.get("stok_id") or 0)
                    stok_kodu = (satir.get("stok_kodu") or "").strip()
                    stok_adi = (satir.get("stok_adi") or "").strip()
                    birim = (satir.get("birim") or "Adet").strip() or "Adet"
                    miktar = decimal(satir.get("miktar") or 0, "Miktar", Decimal("0.0001"))
                    birim_fiyat = decimal(satir.get("birim_fiyat") or 0, "Birim fiyat", Decimal("0"))
                    iskonto = decimal(satir.get("iskonto_orani") or 0, "İskonto", Decimal("0"))
                    kdv = _kdv_orani(satir.get("kdv_orani"))
                    carpan = decimal(satir.get("carpan") or 1, "Çarpan", Decimal("0.0001"))
                    barkod = (satir.get("barkod") or None)
                else:
                    stok_id = int(getattr(satir, "stok_id", 0) or 0)
                    stok_kodu = (getattr(satir, "stok_kodu", None) or "").strip()
                    stok_adi = (getattr(satir, "stok_adi", None) or "").strip()
                    birim = (getattr(satir, "birim", None) or "Adet").strip() or "Adet"
                    miktar = decimal(getattr(satir, "miktar", 0) or 0, "Miktar", Decimal("0.0001"))
                    birim_fiyat = decimal(
                        getattr(satir, "birim_fiyat", 0) or 0, "Birim fiyat", Decimal("0")
                    )
                    iskonto = decimal(
                        getattr(satir, "iskonto_orani", 0) or 0, "İskonto", Decimal("0")
                    )
                    kdv = _kdv_orani(getattr(satir, "kdv_orani", None))
                    carpan = decimal(getattr(satir, "carpan", 1) or 1, "Çarpan", Decimal("0.0001"))
                    barkod = getattr(satir, "barkod", None)

                if stok_id <= 0 or not stok_kodu:
                    raise ValueError(f"Geçersiz sepet satırı (sıra {i + 1}).")
                if miktar <= 0:
                    raise ValueError(f"Miktar sıfır olamaz (sıra {i + 1}).")

                session.add(
                    HizliSatisBekleyenSatiri(
                        bekleyen_id=baslik.id,
                        sira=i,
                        stok_id=stok_id,
                        stok_kodu=stok_kodu,
                        stok_adi=stok_adi or stok_kodu,
                        birim=birim,
                        miktar=miktar,
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=iskonto,
                        kdv_orani=kdv,
                        carpan=carpan if carpan > 0 else Decimal("1"),
                        barkod=(str(barkod).strip() if barkod else None),
                    )
                )

            session.flush()
            return {
                "id": int(baslik.id),
                "etiket": baslik.etiket,
                "satir_sayisi": int(baslik.satir_sayisi),
                "genel_toplam": _kurus(baslik.genel_toplam),
                "olusturma_tarihi": baslik.olusturma_tarihi,
                "durum": baslik.durum,
            }

    @staticmethod
    def list_holds(*, limit: int = 100, sadece_bekleyen: bool = True) -> list[dict[str, Any]]:
        """Bekleyen sepet listesi (özet satırlar)."""
        HizliSatisService.schema_hazirla()
        lim = max(1, min(int(limit or 100), 500))
        with get_session() as session:
            q = select(HizliSatisBekleyen).order_by(HizliSatisBekleyen.olusturma_tarihi.desc())
            if sadece_bekleyen:
                q = q.where(HizliSatisBekleyen.durum == DURUM_BEKLIYOR)
            q = q.limit(lim)
            kayitlar = list(session.scalars(q).all())
            return [HizliSatisService._hold_ozet(k) for k in kayitlar]

    @staticmethod
    def load_hold(
        hold_id: int,
        *,
        cagirildi_isaretle: bool = True,
    ) -> dict[str, Any]:
        """Bekleyeni yükler; varsayılan olarak durum=CAGIRILDI (listeden düşer).

        Stok hareketi yok. Dönüş: başlık özeti + satirlar listesi.
        """
        HizliSatisService.schema_hazirla()
        hid = int(hold_id)
        if hid <= 0:
            raise ValueError("Geçersiz bekleyen kimliği.")

        with get_session() as session:
            baslik = session.scalar(
                select(HizliSatisBekleyen)
                .where(HizliSatisBekleyen.id == hid)
                .options(selectinload(HizliSatisBekleyen.satirlar))
            )
            if baslik is None:
                raise ValueError("Bekleyen sepet bulunamadı.")
            if baslik.durum != DURUM_BEKLIYOR:
                raise ValueError(
                    f"Bu bekleyen kullanılamaz (durum: {baslik.durum})."
                )

            satirlar = [
                {
                    "stok_id": int(s.stok_id),
                    "stok_kodu": s.stok_kodu,
                    "stok_adi": s.stok_adi,
                    "birim": s.birim,
                    "miktar": decimal(s.miktar, "Miktar", Decimal("0")),
                    "birim_fiyat": decimal(s.birim_fiyat, "Birim fiyat", Decimal("0")),
                    "iskonto_orani": decimal(s.iskonto_orani, "İskonto", Decimal("0")),
                    "kdv_orani": decimal(s.kdv_orani, "KDV", Decimal("0")),
                    "carpan": decimal(s.carpan, "Çarpan", Decimal("0")),
                    "barkod": s.barkod,
                }
                for s in sorted(baslik.satirlar or [], key=lambda x: int(x.sira or 0))
            ]
            ozet = HizliSatisService._hold_ozet(baslik)
            ozet["satirlar"] = satirlar
            ozet["odeme_niyeti"] = baslik.odeme_niyeti

            if cagirildi_isaretle:
                baslik.durum = DURUM_CAGIRILDI
                baslik.guncelleme_tarihi = datetime.now()
                session.flush()

            return ozet

    @staticmethod
    def delete_hold(hold_id: int, *, fiziksel: bool = False) -> None:
        """Bekleyeni iptal eder (durum=IPTAL) veya satırlarıyla siler.

        Stok hareketi yok.
        """
        yazma_zorunlu("satis_duzenleme", "satis_goruntuleme")
        HizliSatisService.schema_hazirla()
        hid = int(hold_id)
        if hid <= 0:
            raise ValueError("Geçersiz bekleyen kimliği.")

        with get_session() as session:
            baslik = session.get(HizliSatisBekleyen, hid)
            if baslik is None:
                raise ValueError("Bekleyen sepet bulunamadı.")
            if fiziksel:
                session.delete(baslik)
            else:
                baslik.durum = DURUM_IPTAL
                baslik.guncelleme_tarihi = datetime.now()
            session.flush()

    @staticmethod
    def _hold_ozet(baslik: HizliSatisBekleyen) -> dict[str, Any]:
        return {
            "id": int(baslik.id),
            "etiket": baslik.etiket,
            "cari_id": int(baslik.cari_id) if baslik.cari_id else None,
            "cari_kodu": baslik.cari_kodu,
            "cari_unvan": baslik.cari_unvan,
            "kullanici_id": baslik.kullanici_id,
            "kullanici_adi": baslik.kullanici_adi,
            "durum": baslik.durum,
            "genel_toplam": _kurus(baslik.genel_toplam or 0),
            "satir_sayisi": int(baslik.satir_sayisi or 0),
            "not": baslik.not_,
            "olusturma_tarihi": baslik.olusturma_tarihi,
            "guncelleme_tarihi": baslik.guncelleme_tarihi,
        }

    # —— Aşama 7: iptal / kısmi iade ——

    @staticmethod
    def _iptal_yetki_zorunlu() -> None:
        yazma_zorunlu(IZIN_IPTAL, mesaj=f"İptal / iade için «{IZIN_IPTAL}» yetkisi gerekir.")

    @staticmethod
    def _neden_zorunlu(neden: str | None) -> str:
        metin = (neden or "").strip()
        if not metin:
            raise ValueError("İptal / iade nedeni zorunludur.")
        if len(metin) < 3:
            raise ValueError("İptal / iade nedeni en az 3 karakter olmalıdır.")
        return metin

    @staticmethod
    def _fatura_hizli_satis_dogrula(session, fatura_id: int) -> SatisFaturasi:
        fatura = session.scalar(
            select(SatisFaturasi)
            .where(SatisFaturasi.id == int(fatura_id))
            .options(
                selectinload(SatisFaturasi.satirlar),
                selectinload(SatisFaturasi.tahsilatlar),
                selectinload(SatisFaturasi.cari),
            )
        )
        if not fatura:
            raise ValueError("Fatura bulunamadı.")
        if getattr(fatura, "is_deleted", False):
            raise ValueError("Fatura silinmiş.")
        if (fatura.durum or "") == "İPTAL":
            raise ValueError("Fatura zaten iptal edilmiş.")
        if not getattr(fatura, "onaylandi", False):
            raise ValueError("Yalnızca onaylı hızlı satış faturaları iptal / iade edilebilir.")
        if not _hizli_satis_mi(fatura.aciklama):
            raise ValueError(
                "Bu fatura hızlı satış olarak işaretli değil "
                f"(açıklama «{HIZLI_SATIS_ETIKET}» içermeli)."
            )
        return fatura

    @staticmethod
    def _aktif_iadeler(session, fatura_id: int) -> list:
        from database.models.satis_iade_faturasi import SatisIadeFaturasi

        return list(
            session.scalars(
                select(SatisIadeFaturasi)
                .where(
                    SatisIadeFaturasi.kaynak_fatura_id == int(fatura_id),
                    SatisIadeFaturasi.durum != "İPTAL",
                )
                .options(selectinload(SatisIadeFaturasi.satirlar))
            ).all()
        )

    @staticmethod
    def _iadeye_uygun_miktarlar(session, fatura: SatisFaturasi) -> dict[int, Decimal]:
        """kaynak satır id → kalan iade edilebilir miktar."""
        iade_edilen: dict[int, Decimal] = {}
        for iade in HizliSatisService._aktif_iadeler(session, int(fatura.id)):
            for isatir in iade.satirlar or []:
                kid = getattr(isatir, "kaynak_fatura_satiri_id", None)
                if not kid:
                    continue
                kid = int(kid)
                iade_edilen[kid] = iade_edilen.get(kid, Decimal("0")) + decimal(
                    isatir.miktar, "İade miktarı", Decimal("0")
                )
        sonuc: dict[int, Decimal] = {}
        for satir in fatura.satirlar or []:
            sid = int(satir.id)
            satilan = decimal(satir.miktar, "Miktar", Decimal("0"))
            kalan = satilan - iade_edilen.get(sid, Decimal("0"))
            if kalan < 0:
                kalan = Decimal("0")
            sonuc[sid] = kalan
        return sonuc

    @staticmethod
    def list_recent_hizli_satislar(
        *,
        gun: int = 1,
        limit: int = 50,
        sadece_bugun: bool = True,
    ) -> list[dict[str, Any]]:
        """Onaylı hızlı satış faturalarını listeler (İPTAL hariç)."""
        lim = max(1, min(int(limit or 50), 200))
        bugun = date.today()
        if sadece_bugun:
            baslangic = bugun
        else:
            baslangic = bugun - timedelta(days=max(0, int(gun or 1) - 1))

        with get_session() as session:
            kayitlar = session.scalars(
                select(SatisFaturasi)
                .where(
                    SatisFaturasi.onaylandi.is_(True),
                    SatisFaturasi.durum != "İPTAL",
                    SatisFaturasi.fatura_tarihi >= baslangic,
                )
                .options(
                    selectinload(SatisFaturasi.cari),
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
                .order_by(SatisFaturasi.id.desc())
                .limit(lim * 3)  # etiket filtresi için tampon
            ).all()

            sonuc: list[dict[str, Any]] = []
            for f in kayitlar:
                if getattr(f, "is_deleted", False):
                    continue
                if not _hizli_satis_mi(f.aciklama):
                    continue
                toplam = SatisFaturasiService.toplam(f.satirlar)["genel_toplam"]
                sonuc.append(
                    {
                        "fatura_id": int(f.id),
                        "fatura_no": f.fatura_no,
                        "fatura_tarihi": f.fatura_tarihi,
                        "islem_saati": f.islem_saati,
                        "cari_id": int(f.cari_id) if f.cari_id else None,
                        "musteri": f.cari.unvan if f.cari else "",
                        "genel_toplam": _kurus(toplam),
                        "tahsilat_tutari": _kurus(getattr(f, "tahsilat_tutari", 0) or 0),
                        "durum": f.durum,
                        "aciklama": f.aciklama,
                        "satir_sayisi": len(f.satirlar or []),
                    }
                )
                if len(sonuc) >= lim:
                    break
            return sonuc

    @staticmethod
    def fatura_iade_ozeti(fatura_id: int) -> dict[str, Any]:
        """İptal/iade diyaloğu için satır + kalan miktar özeti."""
        with get_session() as session:
            fatura = HizliSatisService._fatura_hizli_satis_dogrula(session, fatura_id)
            kalanlar = HizliSatisService._iadeye_uygun_miktarlar(session, fatura)
            aktif_iadeler = HizliSatisService._aktif_iadeler(session, int(fatura.id))
            satirlar = []
            for satir in fatura.satirlar or []:
                sid = int(satir.id)
                satilan = decimal(satir.miktar, "Miktar", Decimal("0"))
                kalan = kalanlar.get(sid, Decimal("0"))
                satirlar.append(
                    {
                        "satir_id": sid,
                        "urun_kodu": satir.urun_kodu,
                        "urun_adi": satir.urun_adi,
                        "birim": satir.birim or "Adet",
                        "miktar": satilan,
                        "kalan_iadeye_uygun": kalan,
                        "birim_fiyat": decimal(satir.birim_fiyat, "Birim fiyat", Decimal("0")),
                        "iskonto_orani": decimal(
                            satir.iskonto_orani or 0, "İskonto", Decimal("0")
                        ),
                        "kdv_orani": _kdv_orani(satir.kdv_orani),
                        "barkod": satir.barkod,
                    }
                )
            toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            tahsilatlar = [
                {
                    "odeme_sekli": th.odeme_sekli,
                    "hesap": th.hesap,
                    "tutar": _kurus(th.tutar or 0),
                }
                for th in (fatura.tahsilatlar or [])
            ]
            return {
                "fatura_id": int(fatura.id),
                "fatura_no": fatura.fatura_no,
                "fatura_tarihi": fatura.fatura_tarihi,
                "cari_id": int(fatura.cari_id),
                "musteri": fatura.cari.unvan if fatura.cari else "",
                "depo": fatura.depo or VARSAYILAN_DEPO,
                "genel_toplam": _kurus(toplam),
                "tahsilat_tutari": _kurus(getattr(fatura, "tahsilat_tutari", 0) or 0),
                "durum": fatura.durum,
                "satirlar": satirlar,
                "tahsilatlar": tahsilatlar,
                "onceki_iade_var": bool(aktif_iadeler),
                "onceki_iade_sayisi": len(aktif_iadeler),
                "tam_iptal_uygun": not aktif_iadeler
                and all(
                    kalanlar.get(int(s.id), Decimal("0"))
                    == decimal(s.miktar, "Miktar", Decimal("0"))
                    for s in (fatura.satirlar or [])
                ),
            }

    @staticmethod
    def satisi_iptal(
        fatura_id: int,
        *,
        neden: str,
        not_: str | None = None,
    ) -> dict[str, Any]:
        """Tamamlanmış hızlı satışı soft-iptal eder (fiziksel silme yok).

        Stok çıkışını, FATURA TAHSİLATI finans hareketlerini ve SatisHareketi kaydını
        geri alır; durum=İPTAL + silinen kayıt günlüğü.

        Sınırlama: Önceki iade belgesi varsa tam iptal reddedilir (çift stok riski).
        POS komisyon/valör satırları geri alınmayabilir.
        """
        HizliSatisService._iptal_yetki_zorunlu()
        neden_temiz = HizliSatisService._neden_zorunlu(neden)
        not_temiz = (not_ or "").strip() or None

        with get_session() as session:
            fatura = HizliSatisService._fatura_hizli_satis_dogrula(session, fatura_id)
            if HizliSatisService._aktif_iadeler(session, int(fatura.id)):
                raise ValueError(
                    "Bu faturaya bağlı iade kaydı var. Tam iptal yapılamaz; "
                    "kalan miktar için kısmi iade kullanın."
                )
            ek = f" | İptal: {neden_temiz}"
            if not_temiz:
                ek += f" ({not_temiz})"
            mevcut = (fatura.aciklama or "").rstrip()
            if " | İptal:" not in mevcut:
                fatura.aciklama = (mevcut + ek).strip()
            fid = int(fatura.id)
            fno = fatura.fatura_no
            session.flush()

        SatisFaturasiService.iptal_et(fid, sebep=neden_temiz)

        try:
            from database.database import get_system_session
            from database.system.auth_service import AuthService

            with get_system_session() as sys_s:
                AuthService.audit(
                    sys_s,
                    "hizli_satis_iptal",
                    modul="satis",
                    kayit_id=str(fid),
                    yeni_deger=f"{fno}: {neden_temiz}"
                    + (f" / {not_temiz}" if not_temiz else ""),
                )
        except Exception:
            pass

        return {
            "fatura_id": fid,
            "fatura_no": fno,
            "durum": "İPTAL",
            "mod": "tam_iptal",
            "neden": neden_temiz,
            "uyari": (
                "POS komisyon / valör hareketleri varsa manuel kontrol gerekebilir "
                "(mevcut tahsilat geri alma yalnızca FATURA TAHSİLATI satırlarını siler)."
            ),
        }

    @staticmethod
    def satisi_iade(
        fatura_id: int,
        *,
        satirlar: list[dict[str, Any]],
        neden: str,
        not_: str | None = None,
        iade_odeme: bool | None = None,
        iade_odeme_sekli: str | None = None,
        iade_odeme_hesabi: str | None = None,
    ) -> dict[str, Any]:
        """Kaynak hızlı satış faturasına bağlı iade belgesi (tam veya kısmi).

        `satirlar`: [{kaynak_fatura_satiri_id | satir_id, miktar}, ...]
        Ödeme varsa kasa/bankadan «SATIŞ İADE ÖDEMESİ» çıkar (mevcut iade servisi).
        """
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        HizliSatisService._iptal_yetki_zorunlu()
        neden_temiz = HizliSatisService._neden_zorunlu(neden)
        not_temiz = (not_ or "").strip() or None

        if not satirlar:
            raise ValueError("En az bir iade satırı seçin.")

        with get_session() as session:
            fatura = HizliSatisService._fatura_hizli_satis_dogrula(session, fatura_id)
            kalanlar = HizliSatisService._iadeye_uygun_miktarlar(session, fatura)
            satir_map = {int(s.id): s for s in (fatura.satirlar or [])}
            depo = fatura.depo or VARSAYILAN_DEPO
            cari_id = int(fatura.cari_id)
            kaynak_id = int(fatura.id)
            fno = fatura.fatura_no

            # Varsayılan iade hesabı: ilk tahsilat hesabı
            varsayilan_hesap = None
            varsayilan_sekil = "NAKİT / KASA"
            for th in fatura.tahsilatlar or []:
                if th.hesap:
                    varsayilan_hesap = th.hesap
                    varsayilan_sekil = th.odeme_sekli or varsayilan_sekil
                    break
            tahsilat_toplam = _kurus(getattr(fatura, "tahsilat_tutari", 0) or 0)

            iade_satirlari: list[dict[str, Any]] = []
            for ham in satirlar:
                sid = ham.get("kaynak_fatura_satiri_id") or ham.get("satir_id")
                if sid is None:
                    raise ValueError("İade satırında kaynak satır kimliği zorunludur.")
                sid = int(sid)
                kaynak = satir_map.get(sid)
                if kaynak is None:
                    raise ValueError(f"Kaynak fatura satırı bulunamadı (id={sid}).")
                miktar = decimal(ham.get("miktar", 0), "İade miktarı", Decimal("0.0001"))
                uygun = kalanlar.get(sid, Decimal("0"))
                if miktar > uygun:
                    raise ValueError(
                        f"{kaynak.urun_kodu}: iade miktarı kalanı aşıyor "
                        f"(istenilen {miktar}, kalan {uygun})."
                    )
                iade_satirlari.append(
                    {
                        "kaynak_fatura_satiri_id": sid,
                        "urun_kodu": kaynak.urun_kodu,
                        "urun_adi": kaynak.urun_adi,
                        "miktar": miktar,
                        "birim": kaynak.birim or "Adet",
                        "birim_fiyat": kaynak.birim_fiyat,
                        "iskonto_orani": kaynak.iskonto_orani or 0,
                        "kdv_orani": kaynak.kdv_orani if kaynak.kdv_orani is not None else 20,
                        "fifo_birim_maliyeti": kaynak.fifo_birim_maliyeti,
                        "onceki_fatura_no": fno,
                    }
                )

        if not iade_satirlari:
            raise ValueError("İade edilecek miktar yok.")

        iade_toplam = SatisIadeFaturasiService.toplam(iade_satirlari)["genel_toplam"]

        # Ödeme: tahsilatlı satışta varsayılan iade tutarı = iade toplamı (açık hesapta 0)
        if iade_odeme is None:
            odeme_yap = tahsilat_toplam > 0
        else:
            odeme_yap = bool(iade_odeme)

        odeme_tutar = _kurus(iade_toplam) if odeme_yap else Decimal("0")
        odeme_sekil = (iade_odeme_sekli or varsayilan_sekil or "NAKİT / KASA").strip()
        odeme_hesap = (iade_odeme_hesabi or varsayilan_hesap or "ANA KASA").strip()
        if odeme_tutar > 0 and not odeme_hesap:
            raise ValueError("İade ödemesi için kasa/banka hesabı gerekli.")

        aciklama = f"{HIZLI_SATIS_ETIKET} iade — {neden_temiz}"
        if not_temiz:
            aciklama += f" ({not_temiz})"
        aciklama += f" · kaynak {fno}"

        iade = SatisIadeFaturasiService.kaydet(
            {
                "iade_tarihi": date.today(),
                "cari_id": cari_id,
                "kaynak_fatura_id": kaynak_id,
                "depo": depo,
                "aciklama": aciklama,
                "iade_odeme_tutari": odeme_tutar,
                "iade_odeme_sekli": odeme_sekil if odeme_tutar > 0 else None,
                "iade_odeme_hesabi": odeme_hesap if odeme_tutar > 0 else None,
            },
            iade_satirlari,
        )

        try:
            from database.database import get_system_session
            from database.system.auth_service import AuthService

            with get_system_session() as sys_s:
                AuthService.audit(
                    sys_s,
                    "hizli_satis_iade",
                    modul="satis",
                    kayit_id=str(iade.id),
                    yeni_deger=(
                        f"{fno} → {iade.iade_no}: {neden_temiz}"
                        + (f" / {not_temiz}" if not_temiz else "")
                    ),
                )
        except Exception:
            pass

        return {
            "fatura_id": kaynak_id,
            "fatura_no": fno,
            "iade_id": int(iade.id),
            "iade_no": iade.iade_no,
            "genel_toplam": _kurus(iade_toplam),
            "iade_odeme_tutari": odeme_tutar,
            "mod": "iade",
            "neden": neden_temiz,
            "satir_sayisi": len(iade_satirlari),
            "uyari": (
                "POS komisyon / valör geri alımı iade yolunda otomatik değildir; "
                "gerekirse finans ekranından kontrol edin."
            ),
        }

    # —— Aşama 8: çıktı verisi + gün sonu ——

    @staticmethod
    def fatura_cikti_verisi(fatura_id: int) -> dict[str, Any]:
        """Fiş / A4 / PDF için fatura özeti (yazdırma satışı bozmaz)."""
        fid = int(fatura_id)
        if fid <= 0:
            raise ValueError("Geçersiz fatura kimliği.")

        with get_session() as session:
            fatura = session.scalar(
                select(SatisFaturasi)
                .where(SatisFaturasi.id == fid)
                .options(
                    selectinload(SatisFaturasi.cari),
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
            )
            if fatura is None:
                raise ValueError("Fatura bulunamadı.")
            if getattr(fatura, "is_deleted", False):
                raise ValueError("Fatura silinmiş.")
            if not _hizli_satis_mi(fatura.aciklama):
                raise ValueError("Bu fatura hızlı satış değil.")

            toplam = SatisFaturasiService.toplam(fatura.satirlar)
            genel = _kurus(toplam["genel_toplam"])
            th = _kurus(getattr(fatura, "tahsilat_tutari", 0) or 0)
            satirlar = []
            for s in fatura.satirlar or []:
                st = SatisFaturasiService.toplam([s])
                satirlar.append(
                    {
                        "urun_kodu": s.urun_kodu,
                        "urun_adi": s.urun_adi,
                        "miktar": decimal(s.miktar, "Miktar", Decimal("0")),
                        "birim": s.birim or "Adet",
                        "birim_fiyat": decimal(s.birim_fiyat, "Birim fiyat", Decimal("0")),
                        "iskonto_orani": decimal(s.iskonto_orani or 0, "İskonto", Decimal("0")),
                        "kdv_orani": decimal(s.kdv_orani or 0, "KDV", Decimal("0")),
                        "satir_toplam": _kurus(st["genel_toplam"]),
                        "barkod": s.barkod,
                    }
                )
            tahsilatlar = [
                {
                    "odeme_sekli": t.odeme_sekli,
                    "hesap": t.hesap,
                    "tutar": _kurus(t.tutar or 0),
                }
                for t in (fatura.tahsilatlar or [])
            ]
            firma = ""
            try:
                firma = (getattr(oturum, "firma_unvan", None) or "").strip()
            except Exception:
                firma = ""
            from database.user_audit import display_user

            kasiyer = display_user(
                getattr(fatura, "created_by_full_name", None)
                or getattr(fatura, "tahsilat_alan_full_name", None),
                getattr(fatura, "created_by_user_id", None),
            )

            return {
                "fatura_id": int(fatura.id),
                "fatura_no": fatura.fatura_no,
                "fatura_tarihi": fatura.fatura_tarihi,
                "islem_saati": fatura.islem_saati,
                "musteri": fatura.cari.unvan if fatura.cari else "",
                "cari_kodu": fatura.cari.cari_kodu if fatura.cari else "",
                "kasiyer": kasiyer,
                "firma": firma,
                "ara_toplam": _kurus(toplam["ara_toplam"]),
                "iskonto": _kurus(toplam["iskonto"]),
                "kdv": _kurus(toplam["kdv"]),
                "genel_toplam": genel,
                "tahsilat_tutari": th,
                "kalan": _kurus(genel - th),
                "durum": fatura.durum,
                "satirlar": satirlar,
                "tahsilatlar": tahsilatlar,
            }

    @staticmethod
    def gun_sonu_ozeti(tarih: date | None = None) -> dict[str, Any]:
        """Belirli günün onaylı hızlı satış özeti (soft-delete dışı)."""
        gun = tarih or date.today()
        with get_session() as session:
            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(
                    SatisFaturasi.fatura_tarihi == gun,
                    SatisFaturasi.onaylandi.is_(True),
                )
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
            ).all()

            aktif: list[dict[str, Any]] = []
            for f in faturalar:
                if getattr(f, "is_deleted", False):
                    continue
                if not _hizli_satis_mi(f.aciklama):
                    continue
                if f.durum == "İPTAL":
                    continue
                toplam = SatisFaturasiService.toplam(f.satirlar)
                aktif.append(
                    {
                        "fatura_id": int(f.id),
                        "fatura_no": f.fatura_no,
                        "genel_toplam": _kurus(toplam["genel_toplam"]),
                        "iskonto": _kurus(toplam["iskonto"]),
                        "kdv": _kurus(toplam["kdv"]),
                        "tahsilat_tutari": _kurus(getattr(f, "tahsilat_tutari", 0) or 0),
                        "tahsilat_sekli": f.tahsilat_sekli,
                        "tahsilatlar": [
                            {
                                "odeme_sekli": t.odeme_sekli,
                                "tutar": _kurus(t.tutar or 0),
                            }
                            for t in (f.tahsilatlar or [])
                        ],
                    }
                )

            # İptaller: aynı gün, etiketli, durum İPTAL (onaylandi False olabilir)
            iptal_kayitlar = session.scalars(
                select(SatisFaturasi)
                .where(
                    SatisFaturasi.fatura_tarihi == gun,
                    SatisFaturasi.durum == "İPTAL",
                )
                .options(selectinload(SatisFaturasi.satirlar))
            ).all()
            iptaller: list[dict[str, Any]] = []
            for f in iptal_kayitlar:
                if getattr(f, "is_deleted", False):
                    continue
                if not _hizli_satis_mi(f.aciklama):
                    continue
                toplam = SatisFaturasiService.toplam(f.satirlar)
                iptaller.append(
                    {
                        "fatura_id": int(f.id),
                        "fatura_no": f.fatura_no,
                        "genel_toplam": _kurus(toplam["genel_toplam"]),
                    }
                )

            from database.models.satis_iade_faturasi import SatisIadeFaturasi

            iade_kayitlar = session.scalars(
                select(SatisIadeFaturasi)
                .where(
                    SatisIadeFaturasi.iade_tarihi == gun,
                    SatisIadeFaturasi.durum != "İPTAL",
                )
                .options(
                    selectinload(SatisIadeFaturasi.satirlar),
                    selectinload(SatisIadeFaturasi.kaynak_fatura),
                )
            ).all()
            iadeler: list[dict[str, Any]] = []
            for iade in iade_kayitlar:
                kaynak = iade.kaynak_fatura
                if kaynak is not None and getattr(kaynak, "is_deleted", False):
                    continue
                if not (
                    _hizli_satis_mi(iade.aciklama)
                    or (kaynak is not None and _hizli_satis_mi(kaynak.aciklama))
                ):
                    continue
                iade_toplam = SatisFaturasiService.toplam(iade.satirlar)["genel_toplam"]
                iadeler.append(
                    {
                        "iade_id": int(iade.id),
                        "iade_no": iade.iade_no,
                        "genel_toplam": _kurus(iade_toplam),
                    }
                )

            ozet = gun_sonu_ozet_hesapla(aktif, iptaller=iptaller, iadeler=iadeler)
            ozet["tarih"] = gun
            return ozet
