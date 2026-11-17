"""EvoBulut banka kartlarını Cin Muhasebe BankaKarti olarak aktar + eşleştir.

Evo banka_listesi alanları (dokümantasyon):
  id, text, a_dov_id, DOV_Kodu, a_posmu, a_posgun, a_muh_kom_hid, a_kod

Yerel model: BankaKarti (üst çatı) + ürün FinansHesabi (MEVDUAT/KMH/POS/KK/KREDILER).
Ürünün tam adı yeni çatı üretmez; kurum + sahip/grup sınıflandırması kullanılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import BankAccountMatchRule, BankaKarti, FinansHesabi
from entegrasyon.banka_eslestirme import (
    BankAccountMatchingService,
    normalize_banka_adi,
    normalize_iban,
)
from entegrasyon.banka_urun_sinif import siniflandir_evo_satir
from entegrasyon.evb_import_common import ImportSonuc, _temiz


def map_evo_banka_kart(satir: dict[str, Any]) -> dict[str, Any]:
    evo_id = _temiz(satir.get("id") or satir.get("a_id") or satir.get("banka_id"))
    ad = _temiz(satir.get("text") or satir.get("a_adi") or satir.get("banka_adi") or satir.get("BANKA"))
    kod = _temiz(satir.get("a_kod"))
    doviz = _temiz(satir.get("DOV_Kodu") or satir.get("DOV_Sembol") or "TL")
    posmu = _temiz(satir.get("a_posmu")) in {"1", "true", "True", "E", "e"}
    try:
        posgun = int(_temiz(satir.get("a_posgun") or "1") or "1")
    except ValueError:
        posgun = 1
    iban = normalize_iban(satir.get("a_iban") or satir.get("IBAN") or satir.get("iban"))
    hesap_no = _temiz(satir.get("a_hesap_no") or satir.get("hesap_no") or satir.get("HESAP_NO") or kod)
    sube = _temiz(satir.get("a_sube") or satir.get("a_sube_adi") or satir.get("SUBE") or satir.get("sube"))
    sinif = siniflandir_evo_satir(satir)
    notlar = []
    if doviz and doviz.upper() not in {"TL", "TRY"}:
        notlar.append(f"Döviz: {doviz}")
    if posmu:
        notlar.append("POS hesap")
    if kod and kod not in {"", "-"}:
        notlar.append(f"Evo kod: {kod}")
    notlar.append(f"Evo id: {evo_id}")
    notlar.append(f"ürün tür: {sinif['urun_turu']}")
    notlar.append(f"çatı: {sinif['cati']}")
    return {
        "evo_banka_id": evo_id,
        "banka_adi": ad[:100] if ad else f"Evo Banka {evo_id}",
        "cati_adi": sinif["cati"],
        "urun_turu": sinif["urun_turu"],
        "urun_adi": (sinif["urun_adi"] or ad)[:100],
        "belirsiz": sinif["belirsiz"],
        "sube": sube[:100] if sube else None,
        "hesap_no": hesap_no[:50] if hesap_no else None,
        "iban": iban[:34] if iban else None,
        "pos_valor_gun": max(0, posgun),
        "aciklama": " | ".join(notlar)[:500],
        "aktif": True,
        "doviz": doviz,
        "posmu": posmu,
    }


@dataclass
class BankaKartKarsilastirma:
    evo_adet: int = 0
    yerel_adet: int = 0
    eslesen: list[dict] = field(default_factory=list)
    sadece_evo: list[dict] = field(default_factory=list)
    sadece_yerel: list[dict] = field(default_factory=list)


def karsilastir(evo_satirlar: list[dict], yerel_kartlar: list[BankaKarti] | None = None) -> BankaKartKarsilastirma:
    if yerel_kartlar is None:
        yerel_kartlar = FinansService.banka_kartlari(aktif_only=False)
    rapor = BankaKartKarsilastirma(evo_adet=len(evo_satirlar), yerel_adet=len(yerel_kartlar))
    yerel_by_ad = {normalize_banka_adi(k.banka_adi): k for k in yerel_kartlar}
    yerel_by_iban = {normalize_iban(k.iban): k for k in yerel_kartlar if k.iban}
    eslesen_yerel_ids: set[int] = set()

    with get_session() as session:
        kurallar = {
            k.evo_banka_id: k
            for k in session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True)))
        }

    for ham in evo_satirlar:
        m = map_evo_banka_kart(ham)
        evo_id = m["evo_banka_id"]
        kart = None
        yontem = None
        if evo_id and evo_id in kurallar:
            kid = kurallar[evo_id].banka_karti_id
            kart = next((x for x in yerel_kartlar if x.id == kid), None)
            yontem = "evo_id"
        if kart is None and m.get("iban") and m["iban"] in yerel_by_iban:
            kart = yerel_by_iban[m["iban"]]
            yontem = "iban"
        if kart is None:
            ad = normalize_banka_adi(m["banka_adi"])
            if ad in yerel_by_ad:
                kart = yerel_by_ad[ad]
                yontem = "ad"
        if kart is not None:
            eslesen_yerel_ids.add(kart.id)
            rapor.eslesen.append(
                {
                    "evo_id": evo_id,
                    "evo_adi": m["banka_adi"],
                    "yerel_id": kart.id,
                    "yerel_adi": kart.banka_adi,
                    "yontem": yontem,
                }
            )
        else:
            rapor.sadece_evo.append({"evo_id": evo_id, "evo_adi": m["banka_adi"], "doviz": m.get("doviz")})

    for k in yerel_kartlar:
        if k.id not in eslesen_yerel_ids:
            rapor.sadece_yerel.append({"yerel_id": k.id, "yerel_adi": k.banka_adi, "iban": k.iban})
    return rapor


def _cati_bul_veya_olustur(cati_adi: str) -> BankaKarti:
    """Üst banka çatısını bul; yoksa oluştur. Ürün adıyla yeni çatı açmaz."""
    with get_session() as session:
        kart = session.scalar(
            select(BankaKarti).where(BankaKarti.banka_adi == cati_adi, BankaKarti.aktif.is_(True))
        )
        if kart:
            return FinansService.banka_karti_getir(kart.id)
    return FinansService.banka_karti_kaydet(
        {"banka_adi": cati_adi, "aciklama": f"Üst banka çatısı | Evo ürün eşlemesi"}
    )


def _urun_hesap_bul_veya_olustur(
    *,
    cati: BankaKarti,
    urun_turu: str,
    urun_adi: str,
    evo_id: str,
    doviz: str,
    iban: str | None,
    hesap_no: str | None,
    sube: str | None,
) -> FinansHesabi:
    """Çatı altında ürün hesabını bul (eşleşme kuralı / ad / tür) veya oluştur."""
    tur = (urun_turu or "MEVDUAT").upper()
    with get_session() as session:
        # mevcut kural
        kural = session.scalar(
            select(BankAccountMatchRule).where(
                BankAccountMatchRule.evo_banka_id == evo_id,
                BankAccountMatchRule.aktif.is_(True),
            )
        )
        if kural and kural.finans_hesap_id:
            h = session.get(FinansHesabi, kural.finans_hesap_id)
            if h:
                return h
        # aynı çatıda aynı ad
        h = session.scalar(
            select(FinansHesabi).where(
                FinansHesabi.banka_karti_id == cati.id,
                FinansHesabi.hesap_adi == urun_adi[:100],
            )
        )
        if h:
            return h
        # boş şablon (0 hareket varsayımı yok — yalnız ad şablon ve tek ise)
        adaylar = list(
            session.scalars(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == cati.id,
                    FinansHesabi.alt_hesap_turu == tur,
                    FinansHesabi.aktif.is_(True),
                )
            )
        )
        for aday in adaylar:
            if (aday.hesap_adi or "").startswith(cati.banka_adi) and " — " in (aday.hesap_adi or ""):
                # şablon slot — ürün adına çevir
                aday.hesap_adi = urun_adi[:100]
                aday.iban = iban
                aday.hesap_no = hesap_no
                aday.sube = sube
                aday.para_birimi = doviz
                session.flush()
                return aday
        # yeni ürün hesabı
        finans_turu = "KREDİ KARTI" if tur == "KREDI_KARTI" else "BANKA"
        yeni_ad = urun_adi[:100]
        baz = yeni_ad
        n = 2
        while session.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == yeni_ad)):
            yeni_ad = f"{baz} ({n})"[:100]
            n += 1
        h = FinansHesabi(
            hesap_adi=yeni_ad,
            hesap_turu=finans_turu,
            acilis_bakiyesi=Decimal("0"),
            para_birimi=doviz,
            banka_adi=cati.banka_adi,
            banka_karti_id=cati.id,
            alt_hesap_turu=tur,
            iban=iban,
            hesap_no=hesap_no,
            sube=sube,
            aktif=True,
            varsayilan=False,
            aciklama=f"Evo id: {evo_id}",
        )
        session.add(h)
        session.flush()
        session.refresh(h)
        return h


def aktar_satirlari(satirlar: list[dict[str, Any]], *, guncelle: bool = True) -> ImportSonuc:
    """Evo banka ürünlerini üst çatı + doğru alt türe eşle; isim değişince yeni çatı açma."""
    sonuc = ImportSonuc(cekilen=len(satirlar))
    for ham in satirlar:
        try:
            m = map_evo_banka_kart(ham)
            evo_id = m["evo_banka_id"]
            if not evo_id:
                sonuc.hatalar.append("Evo banka id yok")
                continue

            from database.kart_silme import banka_kaynak_engelli_mi, eslestirme_gerekli_mesaji

            if banka_kaynak_engelli_mi("EVOBULUT", evo_id):
                sonuc.hatalar.append(eslestirme_gerekli_mesaji(evo_id, m.get("banka_adi")))
                sonuc.atlanan += 1
                continue

            mevcut = BankAccountMatchingService.kural_bul(evo_id)
            if mevcut and not guncelle:
                sonuc.atlanan += 1
                continue

            doviz = (m.get("doviz") or "TRY").strip().upper()
            if doviz in {"TL", "YTL", ""}:
                doviz = "TRY"

            # 1) üst çatı: ürün adından değil, sınıflandırılmış çatı adından
            hedef_cati = _cati_bul_veya_olustur(m["cati_adi"])
            if mevcut:
                eski = FinansService.banka_karti_getir(mevcut.banka_karti_id)
                # Eski kural yanlış ürün-çatısına bakıyorsa doğru çatıya yönlendir
                if (
                    guncelle
                    and eski
                    and normalize_banka_adi(eski.banka_adi) != normalize_banka_adi(m["cati_adi"])
                ):
                    cati = hedef_cati
                else:
                    cati = eski or hedef_cati
                sonuc.atlanan += 1
            else:
                cati = hedef_cati
                sonuc.olusturulan += 1

            # 2) ürün hesabı (doğru tür)
            hesap = _urun_hesap_bul_veya_olustur(
                cati=cati,
                urun_turu=m["urun_turu"],
                urun_adi=m["urun_adi"],
                evo_id=evo_id,
                doviz=doviz,
                iban=m.get("iban"),
                hesap_no=m.get("hesap_no"),
                sube=m.get("sube"),
            )
            # çatı / tür sapması varsa düzelt (yalnız guncelle; hareket kopyalamaz)
            if guncelle:
                with get_session() as session:
                    h = session.get(FinansHesabi, hesap.id)
                    if h:
                        if h.banka_karti_id != cati.id:
                            h.banka_karti_id = cati.id
                            h.banka_adi = cati.banka_adi
                        if (h.alt_hesap_turu or "").upper() != m["urun_turu"]:
                            h.alt_hesap_turu = m["urun_turu"]
                            h.hesap_turu = (
                                "KREDİ KARTI" if m["urun_turu"] == "KREDI_KARTI" else "BANKA"
                            )
                        session.flush()

            BankAccountMatchingService.hafizaya_yaz(
                evo_banka_id=evo_id,
                banka_karti_id=cati.id,
                evo_banka_adi=m["banka_adi"],
                finans_hesap_id=hesap.id,
                alt_hesap_turu=m["urun_turu"],
                iban=m.get("iban"),
                hesap_no=m.get("hesap_no"),
                guven=Decimal("100"),
                kaynak="api_cati",
            )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"{_temiz(ham.get('text') or ham.get('id'))}: {exc}")
    return sonuc


def aktar_api_den(*, guncelle: bool = True, creds=None) -> tuple[ImportSonuc, BankaKartKarsilastirma]:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(creds or load_credentials())
    client.login()
    satirlar = client.banka_kart_listesi()
    once = karsilastir(satirlar)
    sonuc = aktar_satirlari(satirlar, guncelle=guncelle)
    sonra = karsilastir(satirlar)
    return sonuc, sonra if sonra.evo_adet else once
