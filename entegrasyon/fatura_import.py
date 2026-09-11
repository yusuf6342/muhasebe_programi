"""EvoBulut fatura/fiş/iade aktarımı (tur=31..35).

tur=35 Alış fişi → AlisFaturasiService (stok IN)
tur=31 Satış faturası → SatisFaturasiService (stok OUT + OTO giriş)
tur=32 Alış iade → AlisIadeFaturasiService (stok OUT + OTO)
tur=33 Satış iade → SatisIadeFaturasiService (stok IN)
tur=34 Satış fişi → SatisFaturasiService (stok OUT + OTO)
"""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select

from database.alis_faturasi_service import AlisFaturasiService
from database.alis_iade_faturasi_service import AlisIadeFaturasiService
from database.database import get_session
from database.models.alis_faturasi import AlisFaturasi
from database.models.alis_iade_faturasi import AlisIadeFaturasi
from database.models.satis_faturasi import SatisFaturasi
from database.models.satis_iade_faturasi import SatisIadeFaturasi
from database.satis_faturasi_service import SatisFaturasiService
from database.satis_iade_faturasi_service import SatisIadeFaturasiService
from database.stok_service import StokService

from database.models.alis_siparisi import AlisSiparisi  # noqa: F401
from database.models.alis_irsaliyesi import AlisIrsaliyesi  # noqa: F401
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401

from entegrasyon.evb_import_common import (
    DETAY_BEKLE_SN,
    ImportSonuc,
    _tarih,
    _tarih_sirala_anahtar,
    _temiz,
    belge_no_icin,
    cari_bul_veya_hata,
    progress_log,
    satir_verisi_fatura,
    satir_verisi_iade,
    stok_yetersizligi_kapat,
)

# tur → (onek, kod_onek, hedef)
TUR_AYAR = {
    "35": {"onek": "EVB-AFIS-", "kod_onek": "AFIS", "hedef": "alis_fis"},
    "31": {"onek": "EVB-SF-", "kod_onek": "SF", "hedef": "satis"},
    "32": {"onek": "EVB-AI-", "kod_onek": "AI", "hedef": "alis_iade"},
    "33": {"onek": "EVB-SI-", "kod_onek": "SI", "hedef": "satis_iade"},
    "34": {"onek": "EVB-SFIS-", "kod_onek": "SFIS", "hedef": "satis_fis"},
}


def _belge_var_mi(hedef: str, no: str) -> bool:
    no = _temiz(no)
    if not no:
        return False
    with get_session() as session:
        if hedef in {"alis_fis"}:
            return session.scalar(select(AlisFaturasi.id).where(AlisFaturasi.fatura_no == no)) is not None
        if hedef in {"satis", "satis_fis"}:
            return session.scalar(select(SatisFaturasi.id).where(SatisFaturasi.fatura_no == no)) is not None
        if hedef == "alis_iade":
            return session.scalar(select(AlisIadeFaturasi.id).where(AlisIadeFaturasi.iade_no == no)) is not None
        if hedef == "satis_iade":
            return session.scalar(select(SatisIadeFaturasi.id).where(SatisIadeFaturasi.iade_no == no)) is not None
    return False


def _satirlari_hazirla(satirlar_ham: list, sonuc: ImportSonuc, hedef: str) -> list[dict]:
    satir_verileri = []
    for line in satirlar_ham:
        try:
            if hedef in {"alis_iade", "satis_iade"}:
                satir_verileri.append(satir_verisi_iade(line, sonuc))
            else:
                satir_verileri.append(satir_verisi_fatura(line, sonuc))
        except ValueError as exc:
            if "miktar" in str(exc).casefold():
                continue
            raise
    return satir_verileri


def _tek_aktar(client, liste_satir: dict[str, Any], tur: str, sonuc: ImportSonuc) -> bool:
    ayar = TUR_AYAR[str(tur)]
    hedef = ayar["hedef"]
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Fatura a_id yok")

    once_no = belge_no_icin(liste_satir, {}, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if once_no and _belge_var_mi(hedef, once_no):
        sonuc.atlanan += 1
        return False

    detay = client.fatura_detay(aid)
    ana = detay.get("Ana") or {}
    satirlar_ham = detay.get("Detay") or []
    if not satirlar_ham:
        raise ValueError(f"Fatura {aid}: satır yok")

    belge_no = belge_no_icin(liste_satir, ana, onek=ayar["onek"], kod_onek=ayar["kod_onek"])
    if _belge_var_mi(hedef, belge_no):
        sonuc.atlanan += 1
        return True

    cari = cari_bul_veya_hata(liste_satir, ana)
    tarih = _tarih(ana.get("a_tarih") or liste_satir.get("G.a_tarih"))
    vade = _tarih(ana.get("a_vtarih") or liste_satir.get("G.a_vtarih")) or tarih
    if not tarih:
        raise ValueError(f"Fatura {aid}: tarih yok")
    if vade and vade < tarih:
        vade = tarih

    StokService.varsayilanlari_hazirla()
    depo = "ANA DEPO"
    aciklama = _temiz(ana.get("a_ack"))[:500] or None
    satir_verileri = _satirlari_hazirla(satirlar_ham, sonuc, hedef)
    if not satir_verileri:
        raise ValueError(f"Fatura {aid}: geçerli satır yok")

    if hedef == "alis_fis":
        AlisFaturasiService.kaydet(
            {
                "fatura_no": belge_no,
                "fatura_tarihi": tarih,
                "vade_tarihi": vade or tarih,
                "cari_id": cari.id,
                "depo": depo,
                "aciklama": aciklama,
                "odeme_tutari": 0,
            },
            satir_verileri,
        )
    elif hedef in {"satis", "satis_fis"}:
        stok_yetersizligi_kapat(
            satir_verileri, fatura_no=belge_no, tarih=tarih, depo=depo, sonuc=sonuc
        )
        SatisFaturasiService.kaydet(
            {
                "fatura_no": belge_no,
                "fatura_tarihi": tarih,
                "vade_tarihi": vade or tarih,
                "cari_id": cari.id,
                "depo": depo,
                "aciklama": aciklama,
                "tahsilat_tutari": 0,
            },
            satir_verileri,
        )
    elif hedef == "alis_iade":
        stok_yetersizligi_kapat(
            satir_verileri, fatura_no=belge_no, tarih=tarih, depo=depo, sonuc=sonuc
        )
        AlisIadeFaturasiService.kaydet(
            {
                "iade_no": belge_no,
                "iade_tarihi": tarih,
                "cari_id": cari.id,
                "depo": depo,
                "aciklama": aciklama,
                "iade_odeme_tutari": 0,
            },
            satir_verileri,
        )
    elif hedef == "satis_iade":
        SatisIadeFaturasiService.kaydet(
            {
                "iade_no": belge_no,
                "iade_tarihi": tarih,
                "cari_id": cari.id,
                "depo": depo,
                "aciklama": aciklama,
                "iade_odeme_tutari": 0,
            },
            satir_verileri,
        )
    else:
        raise ValueError(f"Bilinmeyen hedef: {hedef}")

    sonuc.olusturulan += 1
    return True


def aktar_api_den(
    *,
    tur: str,
    tarih_bas: str = "",
    tarih_son: str = "",
    ara: str = "",
    max_adet: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    tur = str(tur)
    if tur not in TUR_AYAR:
        raise ValueError(f"Desteklenmeyen tur={tur}")

    client = EvobulutClient(load_credentials())
    client.login()
    progress_log(progress, f"Fatura listesi çekiliyor (tur={tur})…")
    liste = client.tum_faturalari_cek(
        tur=tur, ara=ara, tarih_bas=tarih_bas, tarih_son=tarih_son
    )
    liste.sort(key=_tarih_sirala_anahtar)
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(liste))
    progress_log(
        progress,
        f"{len(liste)} belge; detaylar aktarılıyor (~{DETAY_BEKLE_SN:.1f}s/adet)…",
    )

    for i, satir in enumerate(liste, start=1):
        aid = _temiz(satir.get("G.a_id") or satir.get("a_id"))
        api_cagrildi = False
        try:
            api_cagrildi = _tek_aktar(client, satir, tur, sonuc)
            if i % 25 == 0 or i == len(liste):
                progress_log(
                    progress,
                    f"  {i}/{len(liste)} — oluşturulan={sonuc.olusturulan} "
                    f"atlanan={sonuc.atlanan} oto={sonuc.oto_giris} hata={len(sonuc.hatalar)}",
                )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"a_id={aid}: {exc}")
            sonuc.atlanan += 1
            api_cagrildi = True
        if i < len(liste) and api_cagrildi:
            time.sleep(DETAY_BEKLE_SN)

    return sonuc
