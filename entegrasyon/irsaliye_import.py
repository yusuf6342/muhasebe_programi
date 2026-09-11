"""EvoBulut irsaliye aktarımı (a_tur=70 alış / 71 satış)."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select

from database.alis_irsaliyesi_service import AlisIrsaliyesiService
from database.database import get_session
from database.models.alis_irsaliyesi import AlisIrsaliyesi
from database.models.satis_irsaliyesi import SatisIrsaliyesi
from database.satis_irsaliyesi_service import SatisIrsaliyesiService
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
    satir_verisi_irsaliye,
)

TUR_AYAR = {
    "70": {"onek": "EVB-AIR-", "kod_onek": "AIR", "hedef": "alis"},
    "71": {"onek": "EVB-SIR-", "kod_onek": "SIR", "hedef": "satis"},
}


def _var_mi(hedef: str, no: str) -> bool:
    no = _temiz(no)
    if not no:
        return False
    with get_session() as session:
        if hedef == "alis":
            return (
                session.scalar(select(AlisIrsaliyesi.id).where(AlisIrsaliyesi.irsaliye_no == no))
                is not None
            )
        return (
            session.scalar(select(SatisIrsaliyesi.id).where(SatisIrsaliyesi.irsaliye_no == no))
            is not None
        )


def _tek_aktar(client, liste_satir: dict[str, Any], a_tur: str, sonuc: ImportSonuc) -> bool:
    ayar = TUR_AYAR[str(a_tur)]
    hedef = ayar["hedef"]
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("İrsaliye a_id yok")

    once_no = belge_no_icin(liste_satir, {}, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if once_no and _var_mi(hedef, once_no):
        sonuc.atlanan += 1
        return False

    detay = client.irsaliye_detay(aid)
    ana = detay.get("Ana") or {}
    satirlar_ham = detay.get("Detay") or []
    if not satirlar_ham:
        raise ValueError(f"İrsaliye {aid}: satır yok")

    irsaliye_no = belge_no_icin(liste_satir, ana, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if _var_mi(hedef, irsaliye_no):
        sonuc.atlanan += 1
        return True

    cari = cari_bul_veya_hata(liste_satir, ana)
    tarih = _tarih(ana.get("a_tarih") or liste_satir.get("G.a_tarih"))
    if not tarih:
        raise ValueError(f"İrsaliye {aid}: tarih yok")

    StokService.varsayilanlari_hazirla()
    aciklama = _temiz(ana.get("a_ack"))[:500] or None
    satir_verileri = []
    for line in satirlar_ham:
        try:
            satir_verileri.append(satir_verisi_irsaliye(line, sonuc))
        except ValueError as exc:
            if "miktar" in str(exc).casefold():
                continue
            raise
    if not satir_verileri:
        raise ValueError(f"İrsaliye {aid}: geçerli satır yok")

    veriler = {
        "irsaliye_no": irsaliye_no,
        "irsaliye_tarihi": tarih,
        "cari_id": cari.id,
        "siparis_id": None,
        "aciklama": aciklama,
        "ayrintili_notlar": None,
    }
    if hedef == "alis":
        AlisIrsaliyesiService.kaydet(veriler, satir_verileri)
    else:
        SatisIrsaliyesiService.kaydet(veriler, satir_verileri)

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
    progress_log(progress, f"İrsaliye listesi çekiliyor (a_tur={a_tur})…")
    liste = client.tum_irsaliyeleri_cek(
        a_tur=a_tur, ara=ara, tarih_bas=tarih_bas, tarih_son=tarih_son
    )
    liste.sort(key=_tarih_sirala_anahtar)
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(liste))
    progress_log(progress, f"{len(liste)} irsaliye aktarılıyor…")

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
