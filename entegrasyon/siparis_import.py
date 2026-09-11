"""EvoBulut sipariş aktarımı (a_tur=50 alınan / 51 verilen)."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select

from database.alis_siparisi_service import AlisSiparisiService
from database.database import get_session
from database.models.alis_siparisi import AlisSiparisi
from database.models.satis_siparisi import SatisSiparisi
from database.satis_siparisi_service import MALIYET_YONTEMLERI, SatisSiparisiService
from database.stok_service import StokService

from entegrasyon.evb_import_common import (
    DETAY_BEKLE_SN,
    ImportSonuc,
    _tarih,
    _tarih_sirala_anahtar,
    _temiz,
    belge_no_icin,
    cari_bul_veya_hata,
    progress_log,
    satir_verisi_siparis,
)

TUR_AYAR = {
    "50": {"onek": "EVB-SSP-", "kod_onek": "SSP", "hedef": "satis"},
    "51": {"onek": "EVB-ASP-", "kod_onek": "ASP", "hedef": "alis"},
}


def _var_mi(hedef: str, no: str) -> bool:
    no = _temiz(no)
    if not no:
        return False
    with get_session() as session:
        if hedef == "satis":
            return session.scalar(select(SatisSiparisi.id).where(SatisSiparisi.siparis_no == no)) is not None
        return session.scalar(select(AlisSiparisi.id).where(AlisSiparisi.siparis_no == no)) is not None


def _tek_aktar(client, liste_satir: dict[str, Any], a_tur: str, sonuc: ImportSonuc) -> bool:
    ayar = TUR_AYAR[str(a_tur)]
    hedef = ayar["hedef"]
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Sipariş a_id yok")

    once_no = belge_no_icin(liste_satir, {}, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if once_no and _var_mi(hedef, once_no):
        sonuc.atlanan += 1
        return False

    detay = client.siparis_detay(aid)
    ana = detay.get("Ana") or {}
    satirlar_ham = detay.get("Detay") or []
    if not satirlar_ham:
        raise ValueError(f"Sipariş {aid}: satır yok")

    siparis_no = belge_no_icin(liste_satir, ana, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if _var_mi(hedef, siparis_no):
        sonuc.atlanan += 1
        return True

    cari = cari_bul_veya_hata(liste_satir, ana)
    tarih = _tarih(ana.get("a_tarih") or ana.get("a_siparis_tar") or liste_satir.get("G.a_tarih"))
    termin = (
        _tarih(ana.get("a_vtarih") or ana.get("a_gecerli_tarih") or liste_satir.get("G.a_vtarih"))
        or tarih
    )
    if not tarih:
        raise ValueError(f"Sipariş {aid}: tarih yok")
    if termin < tarih:
        termin = tarih

    StokService.varsayilanlari_hazirla()
    aciklama = _temiz(ana.get("a_ack"))[:500] or None
    fiyat_alani = "birim_satis_fiyati" if hedef == "satis" else "birim_alis_fiyati"
    satir_verileri = []
    for line in satirlar_ham:
        try:
            satir_verileri.append(satir_verisi_siparis(line, sonuc, fiyat_alani=fiyat_alani))
        except ValueError as exc:
            if "miktar" in str(exc).casefold():
                continue
            raise
    if not satir_verileri:
        raise ValueError(f"Sipariş {aid}: geçerli satır yok")

    if hedef == "satis":
        SatisSiparisiService.kaydet(
            {
                "siparis_no": siparis_no,
                "siparis_tarihi": tarih,
                "termin_tarihi": termin,
                "cari_id": cari.id,
                "maliyet_yontemi": MALIYET_YONTEMLERI[0],  # FIFO
                "hedef_kar_marji": 0,
                "aciklama": aciklama,
            },
            satir_verileri,
            [],
        )
    else:
        AlisSiparisiService.kaydet(
            {
                "siparis_no": siparis_no,
                "siparis_tarihi": tarih,
                "termin_tarihi": termin,
                "cari_id": cari.id,
                "aciklama": aciklama,
            },
            satir_verileri,
            [],
        )

    sonuc.olusturulan += 1
    return True


def aktar_api_den(
    *,
    a_tur: str,
    tarih_bas: str = "",
    tarih_son: str = "",
    ara: str = "",
    max_adet: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    a_tur = str(a_tur)
    if a_tur not in TUR_AYAR:
        raise ValueError(f"Desteklenmeyen a_tur={a_tur}")

    client = EvobulutClient(load_credentials())
    client.login()
    progress_log(progress, f"Sipariş listesi çekiliyor (a_tur={a_tur})…")
    liste = client.tum_siparisleri_cek(
        a_tur=a_tur, ara=ara, tarih_bas=tarih_bas, tarih_son=tarih_son
    )
    liste.sort(key=_tarih_sirala_anahtar)
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(liste))
    progress_log(progress, f"{len(liste)} sipariş aktarılıyor…")

    for i, satir in enumerate(liste, start=1):
        aid = _temiz(satir.get("G.a_id") or satir.get("a_id"))
        api_cagrildi = False
        try:
            api_cagrildi = _tek_aktar(client, satir, a_tur, sonuc)
            if i % 25 == 0 or i == len(liste):
                progress_log(
                    progress,
                    f"  {i}/{len(liste)} — oluşturulan={sonuc.olusturulan} "
                    f"atlanan={sonuc.atlanan} hata={len(sonuc.hatalar)}",
                )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"a_id={aid}: {exc}")
            sonuc.atlanan += 1
            api_cagrildi = True
        if i < len(liste) and api_cagrildi:
            time.sleep(DETAY_BEKLE_SN)

    return sonuc
