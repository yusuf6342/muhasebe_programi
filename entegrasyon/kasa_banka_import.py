"""EvoBulut kasa / banka hareket aktarımı (best-effort).

Kasa: POST /KasaHareketleri/base (kasa_listesi, jq_list, sql)
Banka: POST /BankHareketleri/base (banka_listesi, jq_list, sql)

Eşleme:
- Cari bağlı tahsilat/ödeme → FinansService kasa makbuz (makbuz_no=EVB-KS-*)
  veya banka için banka_manuel_hareket + CariService (belge EVB-BN-*)
- Cari yoksa yalnızca finans hareketi (EVB önekli belge)

Sınırlamalar:
- a_tur_id / yön alanları EvoBulut'ta tutarsız olabildiği için tutar işareti
  ve CARI_ADI eşlemesi en iyi çaba ile yapılır.
- Fatura tahsilat_tutari/odeme alanları güncellenmez (ayrı nakit aktarımı).
- POS / virman / döviz karmaşık hareketleri atlanabilir veya sadeleştirilir.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select

from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import FinansHareketi, KasaMakbuzu

# SQLAlchemy relationship resolve (alis/satis yanları)
from database.models.alis_siparisi import AlisSiparisi  # noqa: F401
from database.models.alis_irsaliyesi import AlisIrsaliyesi  # noqa: F401
from database.models.alis_faturasi import AlisFaturasi  # noqa: F401
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

from entegrasyon.evb_import_common import (
    DETAY_BEKLE_SN,
    ImportSonuc,
    _decimal,
    _tarih,
    _tarih_sirala_anahtar,
    _temiz,
    cari_bul_veya_hata,
    progress_log,
)


def _makbuz_var_mi(makbuz_no: str) -> bool:
    no = _temiz(makbuz_no)
    if not no:
        return False
    with get_session() as session:
        return (
            session.scalar(select(KasaMakbuzu.id).where(KasaMakbuzu.makbuz_no == no))
            is not None
        )


def _finans_belge_var_mi(belge_no: str) -> bool:
    no = _temiz(belge_no)
    if not no:
        return False
    if CariService.islem_belge_var_mi(no):
        return True
    with get_session() as session:
        return (
            session.scalar(select(FinansHareketi.id).where(FinansHareketi.belge_no == no))
            is not None
        )


def _varsayilan_kasa_id() -> int:
    FinansService.varsayilanlari_hazirla()
    kasalar = FinansService.kasa_hesaplari(aktif_only=True)
    if not kasalar:
        raise ValueError("Yerelde aktif kasa hesabı yok")
    ana = next((k for k in kasalar if (k.hesap_adi or "").upper() == "ANA KASA"), None)
    return (ana or kasalar[0]).id


def _kasa_hesap_id_esle(liste_satir: dict, ana: dict) -> int:
    """Evo kasa id/ad → yerel KASA hesabı; yoksa varsayılan."""
    FinansService.varsayilanlari_hazirla()
    evo_ad = _temiz(
        ana.get("a_kasa_ad")
        or liste_satir.get("TBL_KASA.a_adi")
        or liste_satir.get("KASA_ADI")
        or ana.get("TBL_KASA.a_adi")
    )
    kasalar = FinansService.kasa_hesaplari(aktif_only=True)
    if evo_ad:
        hedef = evo_ad.casefold()
        for k in kasalar:
            if (k.hesap_adi or "").casefold() == hedef:
                return k.id
        # kısmi: NAKİT / YÇ
        for k in kasalar:
            ad = (k.hesap_adi or "").casefold()
            if hedef in ad or ad in hedef:
                return k.id
    return _varsayilan_kasa_id()


def _bagli_fatura_id(liste_satir: dict, ana: dict, cari_id: int | None) -> int | None:
    """Evo mudul_ref / belge no ile yerel satış/alış faturası; yoksa None → FIFO."""
    if cari_id is None:
        return None
    ref = _temiz(
        ana.get("a_mudul_ref_id")
        or liste_satir.get("G.a_mudul_ref_id")
        or ana.get("a_modul_ref_id")
        or liste_satir.get("G.a_modul_ref_id")
    )
    belge = _temiz(
        ana.get("a_belge_no")
        or liste_satir.get("G.a_belge_no")
        or liste_satir.get("a_belge_no")
    )
    if not ref and not belge:
        return None
    # Makbuz bağları yalnız satış faturası destekler; alışta FIFO.
    from database.models.satis_faturasi import SatisFaturasi

    with get_session() as session:
        if belge:
            sf = session.scalar(
                select(SatisFaturasi).where(
                    SatisFaturasi.cari_id == cari_id,
                    SatisFaturasi.fatura_no == belge,
                )
            )
            if sf is not None:
                return int(sf.id)
        if ref:
            for onek in ("EVB-SF-", "EVB-SFIS-"):
                no = f"{onek}{ref}"[:50]
                row = session.scalar(
                    select(SatisFaturasi).where(
                        SatisFaturasi.fatura_no == no,
                        SatisFaturasi.cari_id == cari_id,
                    )
                )
                if row is not None:
                    return int(row.id)
    return None


def _varsayilan_banka_hesap_id() -> int:
    FinansService.varsayilanlari_hazirla()
    bankalar = FinansService.hesaplar(hesap_turu="BANKA", aktif_only=True)
    if not bankalar:
        raise ValueError("Yerelde aktif banka hesabı yok")
    return bankalar[0].id


def _yon_tahsilat_mi(ana: dict, liste: dict, tutar: Decimal) -> bool | None:
    """True=tahsilat/giriş, False=ödeme/çıkış, None=belirsiz."""
    for key in (
        "a_tur_id",
        "G.a_tur_id",
        "a_gc",
        "G.a_gc",
        "TUR_ADI",
        "TBL_BELGE_TUR.a_adi",
        "a_tur_adi",
    ):
        ham = _temiz(ana.get(key) or liste.get(key)).casefold()
        if not ham:
            continue
        if any(x in ham for x in ("tahsil", "giriş", "giris", "alınan", "alinan", "gelen")):
            return True
        if any(x in ham for x in ("ödeme", "odeme", "çıkış", "cikis", "giden", "verilen")):
            return False
        # Evo banka: 20=Alınan Havale (giriş), 21=Gönderilen Havale (çıkış).
        # Eski "20→çıkış" eşlemesi Alınan Havale'yi ters yazıyordu.
        if ham in {"10", "1", "g", "20"}:
            return True
        if ham in {"21", "2", "c"}:
            return False
    # Negatif tutar → ödeme varsay
    if tutar < 0:
        return False
    return True


def _cari_bul_esnek(liste_satir: dict, ana: dict):
    try:
        return cari_bul_veya_hata(liste_satir, ana)
    except ValueError:
        return None


def _tutar_yon_finans(ana: dict, liste: dict) -> tuple[Decimal, bool]:
    """(tutar, tahsilat_mi) — a_giren/a_cikan öncelikli."""
    giren = _decimal(
        ana.get("a_giren") or liste.get("G.a_giren") or liste.get("a_giren"),
        Decimal("0"),
    ) or Decimal("0")
    cikan = _decimal(
        ana.get("a_cikan") or liste.get("G.a_cikan") or liste.get("a_cikan"),
        Decimal("0"),
    ) or Decimal("0")
    if giren > 0 and cikan <= 0:
        return giren, True
    if cikan > 0 and giren <= 0:
        return cikan, False
    tutar = _decimal(ana.get("a_tutar") or liste.get("a_tutar") or liste.get("G.a_tutar"), Decimal("0")) or Decimal("0")
    if tutar != 0:
        yon = _yon_tahsilat_mi(ana, liste, tutar)
        return abs(tutar), True if yon is None else yon
    raise ValueError("tarih/tutar eksik")


def _finans_cari_satir(liste_satir: dict, ana: dict) -> tuple[dict, dict]:
    """Liste/detaydan cari eşleme için sentetik ana/liste."""
    ana2 = dict(ana or {})
    liste2 = dict(liste_satir or {})
    if not ana2.get("a_mkod"):
        ana2["a_mkod"] = liste2.get("MKB_KOD") or ana2.get("a_mkod")
    if not ana2.get("CARI_ADI"):
        ana2["CARI_ADI"] = (
            ana2.get("a_ref_ad")
            or liste2.get("MKB")
            or liste2.get("CARI_ADI")
        )
    if not liste2.get("MKB_KOD") and ana2.get("a_mkod"):
        liste2["MKB_KOD"] = ana2["a_mkod"]
    return liste2, ana2


def _tek_kasa(client, liste_satir: dict[str, Any], sonuc: ImportSonuc) -> bool:
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Kasa a_id yok")
    belge = f"EVB-KS-{aid}"[:50]
    if _makbuz_var_mi(belge) or _finans_belge_var_mi(belge):
        sonuc.atlanan += 1
        return False

    tarih = _tarih(liste_satir.get("G.a_tarih") or liste_satir.get("a_tarih"))
    ana: dict[str, Any] = {}
    api_cagrildi = False
    try:
        tutar, yon = _tutar_yon_finans(ana, liste_satir)
    except ValueError:
        detay = client.kasa_islem_detay(aid)
        ana = detay.get("Ana") or {}
        api_cagrildi = True
        tarih = tarih or _tarih(ana.get("a_tarih"))
        tutar, yon = _tutar_yon_finans(ana, liste_satir)

    if not tarih:
        raise ValueError(f"Kasa {aid}: tarih/tutar eksik")

    # tur adı ile yön netleştir
    tur_adi = _temiz(
        ana.get("a_tur_ad") or liste_satir.get("FIN_TUR.a_adi") or ana.get("a_tur_id")
        or liste_satir.get("G.a_tur_id")
    )
    if tur_adi:
        yon2 = _yon_tahsilat_mi({"a_tur_ad": tur_adi}, liste_satir, tutar if yon else -tutar)
        if yon2 is not None:
            yon = yon2

    liste2, ana2 = _finans_cari_satir(liste_satir, ana)
    cari = _cari_bul_esnek(liste2, ana2)
    aciklama = _temiz(ana.get("a_ack") or liste_satir.get("G.a_ack") or liste_satir.get("a_ack"))
    aciklama = (aciklama or f"EVB kasa {aid} {tur_adi}")[:500]
    kasa_id = _kasa_hesap_id_esle(liste_satir, ana)
    fatura_id = _bagli_fatura_id(liste_satir, ana, cari.id if cari else None)

    # Kasa virman: cari tahsilat/ödeme gibi yazılmaz; yön Evo giren/cikan'dan
    if "virman" in tur_adi.casefold():
        virman_tur = "KASA VİRMAN GİRİŞ" if yon else "KASA VİRMAN ÇIKIŞ"
        with get_session() as session:
            from database.models.finans import FinansHareketi as FH

            session.add(
                FH(
                    hesap_id=kasa_id,
                    tarih=tarih,
                    hareket_turu=virman_tur,
                    belge_no=belge,
                    tutar=tutar,
                    aciklama=aciklama,
                )
            )
        sonuc.olusturulan += 1
        return api_cagrildi

    if cari is not None:
        payload = {
            "tarih": tarih,
            "tutar": tutar,
            "finans_hesap_id": kasa_id,
            "cari_id": cari.id,
            "makbuz_no": belge,
            "aciklama": aciklama,
        }
        if fatura_id is not None:
            payload["fatura_id"] = fatura_id
        if yon:
            FinansService.kasa_tahsilat_makbuzu_kaydet(payload)
        else:
            FinansService.kasa_odeme_makbuzu_kaydet(payload)
    else:
        with get_session() as session:
            from database.models.finans import FinansHareketi as FH

            session.add(
                FH(
                    hesap_id=kasa_id,
                    tarih=tarih,
                    hareket_turu="TAHSİLAT MAKBUZU" if yon else "ÖDEME MAKBUZU",
                    belge_no=belge,
                    tutar=tutar,
                    aciklama=aciklama,
                )
            )
    sonuc.olusturulan += 1
    return api_cagrildi


def _evo_banka_id_bul(liste_satir: dict, ana: dict) -> str:
    return _temiz(
        ana.get("a_banka_id")
        or liste_satir.get("a_banka_id")
        or liste_satir.get("G.a_banka_id")
        or liste_satir.get("BANKA_ID")
        or ana.get("a_banka")
        or liste_satir.get("a_banka")
    )


def _banka_hesap_id_esle(liste_satir: dict, ana: dict) -> int:
    """Evo banka kart eşleştirmesi → eşleşmiş ürün finans hesabı; yoksa varsayılan."""
    from entegrasyon.banka_eslestirme import BankAccountMatchingService

    evo_id = _evo_banka_id_bul(liste_satir, ana)
    iban = _temiz(ana.get("a_iban") or liste_satir.get("a_iban") or liste_satir.get("IBAN"))
    from database.kart_silme import banka_kaynak_engelli_mi, eslestirme_gerekli_mesaji

    if evo_id and banka_kaynak_engelli_mi("EVOBULUT", evo_id):
        # Yalnız kullanıcının sonradan yazdığı açık eşleştirme kabul edilir.
        # IBAN/ad ile başka karta veya varsayılan hesaba sessiz düşülmez.
        hafiza = BankAccountMatchingService.finans_hesap_bul(evo_banka_id=evo_id)
        if hafiza.get("modu") == "hafiza" and hafiza.get("finans_hesap_id"):
            return int(hafiza["finans_hesap_id"])
        ad_engel = _temiz(
            ana.get("a_banka_adi")
            or liste_satir.get("BANKA")
            or liste_satir.get("a_banka_adi")
            or liste_satir.get("banka_adi")
        )
        raise ValueError(eslestirme_gerekli_mesaji(evo_id, ad_engel or None))
    ad = _temiz(
        ana.get("a_banka_adi")
        or liste_satir.get("BANKA")
        or liste_satir.get("a_banka_adi")
        or liste_satir.get("banka_adi")
    )
    # Önce evo_id kuralındaki finans_hesap_id / alt_hesap_turu kullanılır (ürün çatısı).
    sonuc = BankAccountMatchingService.finans_hesap_bul(
        evo_banka_id=evo_id or None,
        iban=iban or None,
        banka_adi=ad or None,
        alt_hesap_turu=None,
    )
    hesap_id = sonuc.get("finans_hesap_id")
    if hesap_id:
        return int(hesap_id)
    return _varsayilan_banka_hesap_id()


def _tek_banka(client, liste_satir: dict[str, Any], sonuc: ImportSonuc) -> bool:
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Banka a_id yok")
    belge = f"EVB-BN-{aid}"[:50]
    if _finans_belge_var_mi(belge):
        sonuc.atlanan += 1
        return False

    tarih = _tarih(liste_satir.get("G.a_tarih") or liste_satir.get("a_tarih"))
    ana: dict[str, Any] = {}
    api_cagrildi = False
    try:
        tutar, yon = _tutar_yon_finans(ana, liste_satir)
    except ValueError:
        detay = client.banka_islem_detay(aid)
        ana = detay.get("Ana") or {}
        api_cagrildi = True
        tarih = tarih or _tarih(ana.get("a_tarih"))
        tutar, yon = _tutar_yon_finans(ana, liste_satir)

    if not tarih:
        raise ValueError(f"Banka {aid}: tarih/tutar eksik")

    # a_giren/a_cikan yönü kesin; G.a_tur_id=20 (Alınan Havale) eski kodda
    # çıkış sanılıp doğru girişi eziyordu — tutar alanları varken tur_id ile ezme.
    giren_var = _decimal(
        ana.get("a_giren") or liste_satir.get("G.a_giren") or liste_satir.get("a_giren"),
        Decimal("0"),
    ) or Decimal("0")
    cikan_var = _decimal(
        ana.get("a_cikan") or liste_satir.get("G.a_cikan") or liste_satir.get("a_cikan"),
        Decimal("0"),
    ) or Decimal("0")
    tur_adi = _temiz(
        ana.get("a_tur_ad") or liste_satir.get("FIN_TUR.a_adi") or ana.get("a_tur_id")
        or liste_satir.get("G.a_tur_id")
    )
    if tur_adi and giren_var <= 0 and cikan_var <= 0:
        yon2 = _yon_tahsilat_mi({"a_tur_adi": tur_adi}, {}, tutar if yon else -tutar)
        if yon2 is not None:
            yon = yon2

    liste2, ana2 = _finans_cari_satir(liste_satir, ana)
    cari = _cari_bul_esnek(liste2, ana2)
    aciklama = _temiz(ana.get("a_ack") or liste_satir.get("G.a_ack") or liste_satir.get("a_ack"))
    aciklama = (aciklama or f"EVB banka {aid} {tur_adi}")[:500]
    hesap_id = _banka_hesap_id_esle(liste_satir, ana)

    # Açılış satırı (liste/tur açıklamasında) → acilis_bakiyesi; hareket yazılmaz
    from entegrasyon.banka_acilis_import import acilis_olarak_uygula, acilis_satiri_mi

    if acilis_satiri_mi(liste_satir, ana):
        acilis_olarak_uygula(hesap_id, tutar, giris=bool(yon))
        sonuc.olusturulan += 1
        return api_cagrildi

    hesap = FinansService.hesap_getir(hesap_id)
    hesap_adi = hesap.hesap_adi if hesap else "BANKA HESABI"

    FinansService.banka_manuel_hareket(
        hesap_id,
        tarih,
        tutar,
        "giris" if yon else "cikis",
        aciklama=aciklama,
        belge_no=belge,
        bakiye_kontrol=False,
    )

    if cari is not None:
        cari_belge = f"EVB-BNC-{aid}"[:50]
        if not CariService.islem_belge_var_mi(cari_belge):
            from database.models.cari import Cari, CariIslem, SatisHareketi

            with get_session() as session:
                cari_db = session.get(Cari, int(cari.id))
                if cari_db is None:
                    raise ValueError("Cari bulunamadı")
                from database.acik_kalem_service import AcikKalemService

                if yon:
                    CariService._alacak_uygula(
                        session, cari_db.id, tutar, cari_belge, tarih, kaynak_tur="TAHSILAT"
                    )
                    session.add(
                        CariIslem(
                            cari_id=cari_db.id,
                            tarih=tarih,
                            islem_turu="Tahsilat",
                            belge_no=cari_belge,
                            aciklama=aciklama,
                            borc=Decimal("0"),
                            alacak=tutar,
                            hesap_adi=hesap_adi,
                        )
                    )
                else:
                    # Ödeme CI her zaman BORÇ (Evo BNC); açık kalem etkisi cari yönüne göre.
                    # Tedarikçi: mevcut borçları kapatır. Müşteri: iade/borç kalemi açar.
                    if (cari_db.cari_turu or "") == "Tedarikçi":
                        CariService._alacak_uygula(
                            session, cari_db.id, tutar, cari_belge, tarih, kaynak_tur="ODEME"
                        )
                    else:
                        AcikKalemService.borc_etkisi(
                            session, cari_db.id, tutar, belge_no=cari_belge, tarih=tarih
                        )
                    session.add(
                        CariIslem(
                            cari_id=cari_db.id,
                            tarih=tarih,
                            islem_turu="Ödeme",
                            belge_no=cari_belge,
                            aciklama=aciklama,
                            borc=tutar,
                            alacak=Decimal("0"),
                            hesap_adi=hesap_adi,
                        )
                    )

    sonuc.olusturulan += 1
    return api_cagrildi


def aktar_kasa_api_den(
    *,
    bas_tar: str = "",
    son_tar: str = "",
    ara: str = "",
    max_adet: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(load_credentials())
    client.login()
    progress_log(progress, "Kasa işlem listesi çekiliyor…")
    liste = client.tum_kasa_islemlerini_cek(ara=ara, bas_tar=bas_tar, son_tar=son_tar)
    liste.sort(key=_tarih_sirala_anahtar)
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(liste))
    progress_log(progress, f"{len(liste)} kasa işlem aktarılıyor…")

    for i, satir in enumerate(liste, start=1):
        aid = _temiz(satir.get("a_id") or satir.get("G.a_id"))
        api_cagrildi = False
        try:
            api_cagrildi = _tek_kasa(client, satir, sonuc)
            if i % 25 == 0 or i == len(liste):
                progress_log(
                    progress,
                    f"  {i}/{len(liste)} — oluşturulan={sonuc.olusturulan} "
                    f"atlanan={sonuc.atlanan} hata={len(sonuc.hatalar)}",
                )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"kasa a_id={aid}: {exc}")
            sonuc.atlanan += 1
            api_cagrildi = True
        if i < len(liste) and api_cagrildi:
            time.sleep(DETAY_BEKLE_SN)
    return sonuc


def aktar_banka_api_den(
    *,
    bas_tar: str = "",
    son_tar: str = "",
    ara: str = "",
    max_adet: int | None = None,
    progress: Callable[[str], None] | None = None,
    creds=None,
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(creds or load_credentials())
    client.login()
    progress_log(progress, "Banka işlem listesi çekiliyor…")
    liste = client.tum_banka_islemlerini_cek(ara=ara, bas_tar=bas_tar, son_tar=son_tar)
    liste.sort(key=_tarih_sirala_anahtar)
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(liste))
    progress_log(progress, f"{len(liste)} banka işlem aktarılıyor…")

    for i, satir in enumerate(liste, start=1):
        aid = _temiz(satir.get("a_id") or satir.get("G.a_id"))
        api_cagrildi = False
        try:
            api_cagrildi = _tek_banka(client, satir, sonuc)
            if i % 25 == 0 or i == len(liste):
                progress_log(
                    progress,
                    f"  {i}/{len(liste)} — oluşturulan={sonuc.olusturulan} "
                    f"atlanan={sonuc.atlanan} hata={len(sonuc.hatalar)}",
                )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"banka a_id={aid}: {exc}")
            sonuc.atlanan += 1
            api_cagrildi = True
        if i < len(liste) and api_cagrildi:
            time.sleep(DETAY_BEKLE_SN)
    return sonuc
