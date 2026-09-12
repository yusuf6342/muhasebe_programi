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
        if ham in {"10", "1", "g"}:
            return True
        if ham in {"20", "2", "c"}:
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
    kasa_id = _varsayilan_kasa_id()

    # Kasa virman: cari tahsilat/ödeme gibi yazılmaz (yanlış bakiye riski)
    if "virman" in tur_adi.casefold():
        with get_session() as session:
            from database.models.finans import FinansHareketi as FH

            session.add(
                FH(
                    hesap_id=kasa_id,
                    tarih=tarih,
                    hareket_turu="KASA VİRMAN",
                    belge_no=belge,
                    tutar=tutar,
                    aciklama=aciklama,
                )
            )
        sonuc.olusturulan += 1
        return api_cagrildi

    if cari is not None:
        if yon:
            FinansService.kasa_tahsilat_makbuzu_kaydet(
                {
                    "tarih": tarih,
                    "tutar": tutar,
                    "finans_hesap_id": kasa_id,
                    "cari_id": cari.id,
                    "makbuz_no": belge,
                    "aciklama": aciklama,
                }
            )
        else:
            FinansService.kasa_odeme_makbuzu_kaydet(
                {
                    "tarih": tarih,
                    "tutar": tutar,
                    "finans_hesap_id": kasa_id,
                    "cari_id": cari.id,
                    "makbuz_no": belge,
                    "aciklama": aciklama,
                }
            )
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
    aciklama = (aciklama or f"EVB banka {aid} {tur_adi}")[:500]
    hesap_id = _varsayilan_banka_hesap_id()
    hesap = FinansService.hesap_getir(hesap_id)
    hesap_adi = hesap.hesap_adi if hesap else "BANKA HESABI"

    FinansService.banka_manuel_hareket(
        hesap_id,
        tarih,
        tutar,
        "giris" if yon else "cikis",
        aciklama=aciklama,
        belge_no=belge,
    )

    if cari is not None:
        cari_belge = f"EVB-BNC-{aid}"[:50]
        if not CariService.islem_belge_var_mi(cari_belge):
            from database.models.cari import Cari, CariIslem, SatisHareketi

            with get_session() as session:
                cari_db = session.get(Cari, int(cari.id))
                if cari_db is None:
                    raise ValueError("Cari bulunamadı")
                if yon:
                    CariService._aciklara_uygula(session, cari_db.id, tutar)
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
                    if (cari_db.cari_turu or "") == "Tedarikçi":
                        kalan = CariService._aciklara_uygula(session, cari_db.id, tutar)
                        if kalan > 0:
                            session.add(
                                SatisHareketi(
                                    cari_id=cari_db.id,
                                    satis_tarihi=tarih,
                                    belge_no=cari_belge,
                                    satis_tutari=Decimal("0"),
                                    kalan_acik_tutar=-kalan,
                                )
                            )
                        session.add(
                            CariIslem(
                                cari_id=cari_db.id,
                                tarih=tarih,
                                islem_turu="Ödeme",
                                belge_no=cari_belge,
                                aciklama=aciklama,
                                borc=Decimal("0"),
                                alacak=tutar,
                                hesap_adi=hesap_adi,
                            )
                        )
                    else:
                        session.add(
                            SatisHareketi(
                                cari_id=cari_db.id,
                                satis_tarihi=tarih,
                                belge_no=cari_belge,
                                satis_tutari=tutar,
                                kalan_acik_tutar=tutar,
                            )
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
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(load_credentials())
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
