"""İzole kontroller + durum/rapor güncelleme — mali yazım yok, K06 açılmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.izole_kontrol_rapor
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, SURUMLER, sha256_dosya, yaz_json
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK


def _var(ad: str) -> Path | None:
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    return yol if yol.is_file() else None


def _ozet_json(ad: str) -> dict[str, Any] | None:
    yol = _var(ad)
    if not yol:
        return None
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_hata": "JSON_OKUNAMADI", "dosya": yol.name}


def main() -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    moduller = {
        "FIRMA_DOGRULAMA": _ozet_json("FIRMA_DOGRULAMA"),
        "CARI_EKSTRE_KAPANIS": _ozet_json("CARI_EKSTRE_KAPANIS"),
        "ACIK_KALEM": _ozet_json("ACIK_KALEM"),
        "VADE_YASLANDIRMA": _ozet_json("VADE_YASLANDIRMA"),
        "KASA_KAPANIS": _ozet_json("KASA_KAPANIS"),
        "BANKA_KAPANIS": _ozet_json("BANKA_KAPANIS"),
        "KASA_BASLANGIC": _ozet_json("KASA_BASLANGIC"),
        "BANKA_BASLANGIC": _ozet_json("BANKA_BASLANGIC"),
        "POS_VALOR": _ozet_json("POS_VALOR"),
        "POS_KART_KREDI": _ozet_json("POS_KART_KREDI"),
        "STOK_MIKTAR": _ozet_json("STOK_MIKTAR"),
        "STOK_MALIYET": _ozet_json("STOK_MALIYET"),
        "GIDER_GELIR": _ozet_json("GIDER_GELIR"),
        "BELGE": _ozet_json("BELGE"),
        "BELGE_SATIR": _ozet_json("BELGE_SATIR"),
    }

    tamam: list[str] = []
    kismi: list[str] = []
    eksik: list[str] = []
    ozet_satir: dict[str, Any] = {}

    def _flag(ad: str, ok: bool, kismi_mi: bool = False, **extra: Any) -> None:
        if ok:
            tamam.append(ad)
        elif kismi_mi:
            kismi.append(ad)
        else:
            eksik.append(ad)
        ozet_satir[ad] = {"var": _var(ad) is not None, "ok": ok, "kismi": kismi_mi, **extra}

    ak = moduller["ACIK_KALEM"]
    _flag(
        "ACIK_KALEM",
        bool(ak and ak.get("tamam_mi")),
        kismi_mi=bool(ak and not ak.get("tamam_mi")),
        cari=ak.get("cari_adet") if ak else None,
        kalem=ak.get("acik_kalem_adet") if ak else None,
        detay_yok=ak.get("detay_yok_cari_adet") if ak else None,
    )
    sm = moduller["STOK_MALIYET"]
    _flag(
        "STOK_MALIYET",
        bool(sm and sm.get("tamam_mi")),
        kismi_mi=bool(sm and not sm.get("tamam_mi")),
        adet=sm.get("adet") if sm else None,
        maliyet=sm.get("toplam_maliyet_tl") if sm else None,
        lot_api=sm.get("lot_hareket_api") if sm else None,
    )
    bs = moduller["BELGE_SATIR"]
    _flag(
        "BELGE_SATIR",
        bool(bs and bs.get("tamam_mi")),
        kismi_mi=bool(bs and not bs.get("tamam_mi")),
        belge=bs.get("belge_adet") if bs else None,
        satir=bs.get("satir_toplam") if bs else None,
        lot_satir=bs.get("lot_dolu_satir_adet") if bs else None,
    )
    _flag("KASA_BASLANGIC", moduller["KASA_BASLANGIC"] is not None)
    _flag("BANKA_BASLANGIC", moduller["BANKA_BASLANGIC"] is not None)
    pv = moduller["POS_VALOR"]
    _flag(
        "POS_VALOR",
        pv is not None,
        valor_bekleyen=pv.get("valor_bekleyen_adet") if pv else None,
        valor_tutar=pv.get("valor_bekleyen_toplam") if pv else None,
    )
    _flag(
        "CARI_EKSTRE_KAPANIS",
        bool(moduller["CARI_EKSTRE_KAPANIS"] and moduller["CARI_EKSTRE_KAPANIS"].get("tamam_mi")),
        kismi_mi=bool(moduller["CARI_EKSTRE_KAPANIS"]),
        adet=(moduller["CARI_EKSTRE_KAPANIS"] or {}).get("adet"),
    )
    _flag("BELGE_BASLIK", moduller["BELGE"] is not None, toplam=(moduller["BELGE"] or {}).get("toplam"))
    _flag("GIDER_GELIR", moduller["GIDER_GELIR"] is not None, adet=(moduller["GIDER_GELIR"] or {}).get("adet"))

    # K05: tüm kritik kapanışlar tamam + detay_yok=0 ideal; yine de kapalı tut
    k05_aday = (
        "ACIK_KALEM" in tamam
        and "STOK_MALIYET" in tamam
        and "BELGE_SATIR" in tamam
        and "POS_VALOR" in tamam
        and "KASA_BASLANGIC" in tamam
        and "BANKA_BASLANGIC" in tamam
    )
    k05 = False  # bilinçli: kullanıcı K06/ANA doğrulama öncesi kapı açılmasın
    k06 = False

    kalan_eksik = [
        x
        for x in (
            "ACIK_KALEM / vade (FIFO detay)",
            "STOK_MALIYET / LOT (hareket API boş; fatura lot satırları)",
            "BELGE_SATIR (30–37)",
            "K06 izole hedef DB (ANA makine — ertelendi)",
            "Kaynak sürümünün ANA’da yeniden doğrulanması",
            "Gerçek aktarım + kaynak–hedef mutabakat",
            "EXE / güncelleme paketi",
        )
        if True
    ]
    # dinamik: tamamlananları çıkar
    if "ACIK_KALEM" in tamam:
        kalan_eksik = [x for x in kalan_eksik if not x.startswith("ACIK_KALEM")]
    elif "ACIK_KALEM" in kismi:
        kalan_eksik = [
            ("ACIK_KALEM kısmi — " + str((ak or {}).get("detay_yok_cari_adet")) + " cari detay_yok")
            if x.startswith("ACIK_KALEM")
            else x
            for x in kalan_eksik
        ]
    if "STOK_MALIYET" in tamam:
        kalan_eksik = [x for x in kalan_eksik if not x.startswith("STOK_MALIYET")]
    elif "STOK_MALIYET" in kismi:
        kalan_eksik = [
            "STOK_MALIYET kısmi" if x.startswith("STOK_MALIYET") else x for x in kalan_eksik
        ]
    if "BELGE_SATIR" in tamam:
        kalan_eksik = [x for x in kalan_eksik if not x.startswith("BELGE_SATIR")]
    elif "BELGE_SATIR" in kismi:
        kalan_eksik = [
            f"BELGE_SATIR kısmi { (bs or {}).get('belge_adet') }/{ (bs or {}).get('hedef_belge_adet') }"
            if x.startswith("BELGE_SATIR")
            else x
            for x in kalan_eksik
        ]

    son_surum = None
    son_yol = SURUMLER / "SON_SURUM.json"
    if son_yol.is_file():
        son_surum = json.loads(son_yol.read_text(encoding="utf-8"))

    rapor = {
        "format": "d1-izole-kontrol-rapor-v1",
        "zaman": now,
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "mali_yazim": False,
        "k05_kaynak_kapisi": k05,
        "k05_aday_hazir": k05_aday,
        "k06_hedef_izolasyonu": k06,
        "k06_not": "ANA makine DB oluşturma ertelendi; kontrol atlanmadı, bekliyor.",
        "tamamlanan": tamam,
        "kismi": kismi,
        "eksik_dosya": eksik,
        "modul_ozet": ozet_satir,
        "kalan_eksikler": kalan_eksik,
        "son_surum": son_surum,
        "korunan": "Mevcut firma DB’lerine mali kayıt yazılmadı.",
    }
    yaz_json(CALISMA / "IZOLE_KONTROL_RAPOR.json", rapor)

    # DURUM.json
    durum = {
        "calisma_id": "D1-20260831-20261106_140822",
        "guncelleme": now,
        "ozet": (
            f"Kasa/banka başlangıç + POS valör tamam. "
            f"ACIK_KALEM={'OK' if 'ACIK_KALEM' in tamam else ('kısmi' if 'ACIK_KALEM' in kismi else 'yok')}; "
            f"STOK_MALIYET={'OK' if 'STOK_MALIYET' in tamam else ('kısmi' if 'STOK_MALIYET' in kismi else 'yok')}; "
            f"BELGE_SATIR={'OK' if 'BELGE_SATIR' in tamam else ('kısmi' if 'BELGE_SATIR' in kismi else 'yok')}. "
            f"K05/K06 kapalı; mali yazım yok; EXE yok."
        ),
        "kanitlar": {
            "surum": str(son_surum) if son_surum else None,
            "acik_kalem": "kaynak/D1_20260831_KAYNAK_ACIK_KALEM.json" if _var("ACIK_KALEM") else None,
            "stok_maliyet": "kaynak/D1_20260831_KAYNAK_STOK_MALIYET.json" if _var("STOK_MALIYET") else None,
            "belge_satir": "kaynak/D1_20260831_KAYNAK_BELGE_SATIR.json" if _var("BELGE_SATIR") else None,
            "kasa_baslangic": "kaynak/D1_20260831_KAYNAK_KASA_BASLANGIC.json",
            "banka_baslangic": "kaynak/D1_20260831_KAYNAK_BANKA_BASLANGIC.json",
            "pos_valor": "kaynak/D1_20260831_KAYNAK_POS_VALOR.json",
            "izole_rapor": "IZOLE_KONTROL_RAPOR.json",
            "esleme": "esleme/D1_20260831_KIMLIK_ESLEME.json",
            "plan": "plan/D1_20260831_AKTARIM_PLANI.json",
        },
        "eksik_k05": kalan_eksik,
        "engeller": [
            "K06: ANA makinede superuser ile 10_pg_dnm_d1_bos_hedef.ps1 (ertelendi)",
            "K05: kapanış paketinin tam ve tutarlı olması",
        ],
        "kullanici_adimi_gerekli": [
            "ANA makinede izole DB (K06) — şimdilik erte",
            "web.evobulut.com DNM 42178 unvan teyidi",
        ],
        "modul_ozet": ozet_satir,
    }
    yaz_json(CALISMA / "DURUM.json", durum)

    # Kontrol planı seçili satırlar
    kp_yol = CALISMA / "KONTROL_PLANI_DURUM.json"
    if kp_yol.is_file():
        kp = json.loads(kp_yol.read_text(encoding="utf-8"))
        for k in kp.get("kontroller") or []:
            kid = k.get("kontrol_id")
            if kid == "K05":
                k["sonuc"] = "Bekliyor"
                k["aciklama"] = (
                    f"Kapanış ilerliyor; aday_hazir={k05_aday}. Kapı bilinçli kapalı (ANA doğrulama sonrası)."
                )
                k["kaynak_kanit"] = "IZOLE_KONTROL_RAPOR.json"
            elif kid == "K06":
                k["sonuc"] = "Bekliyor"
                k["aciklama"] = "ANA makine DB oluşturma kullanıcı tarafından ertelendi; atlanmadı."
            elif kid == "K03":
                k["sonuc"] = "Kısmi"
                k["kaynak_kanit"] = f"surumler/{(son_surum or {}).get('surum_id')}"
                k["aciklama"] = "Sürümlü paket alındı; kapanışlar tamamlanınca yeni sürüm."
            elif kid == "K10":
                k["sonuc"] = "OK" if "ACIK_KALEM" in tamam else ("Kısmi" if "ACIK_KALEM" in kismi else "Bekliyor")
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_ACIK_KALEM.json" if _var("ACIK_KALEM") else None
                k["aciklama"] = "FIFO açık kalem + vade (finans_jq_listesi Detay)"
            elif kid == "K11":
                k["sonuc"] = "OK" if _var("VADE_YASLANDIRMA") else ("Kısmi" if "ACIK_KALEM" in kismi else "Bekliyor")
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_VADE_YASLANDIRMA.json" if _var("VADE_YASLANDIRMA") else None
            elif kid == "K13":
                k["sonuc"] = "OK" if moduller["STOK_MIKTAR"] else "Bekliyor"
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_STOK_MIKTAR.json"
            elif kid == "K15":
                k["sonuc"] = "OK" if "STOK_MALIYET" in tamam else ("Kısmi" if "STOK_MALIYET" in kismi else "Bekliyor")
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_STOK_MALIYET.json" if _var("STOK_MALIYET") else None
                k["aciklama"] = "Kart FIFO/ort/alış maliyeti; StokHareket API boş"
            elif kid == "K16":
                k["sonuc"] = "Kısmi" if _var("BELGE_SATIR") else "Bekliyor"
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_BELGE_SATIR.json (Seri_Lot_List)"
                k["aciklama"] = "LOT izi fatura satır Seri_Lot_List; ayrı lot listesi API yok"
            elif kid == "K18":
                k["sonuc"] = "OK" if "KASA_BASLANGIC" in tamam else "Kısmi"
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_KASA_BASLANGIC.json + KASA_KAPANIS"
            elif kid == "K19":
                k["sonuc"] = "OK" if "BANKA_BASLANGIC" in tamam else "Kısmi"
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_BANKA_BASLANGIC.json + BANKA_KAPANIS"
            elif kid == "K23":  # POS — kontrol_id numarası dosyada sıraya göre
                pass
            elif k.get("modul") == "POS valör":
                k["sonuc"] = "OK" if "POS_VALOR" in tamam else "Bekliyor"
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_POS_VALOR.json"
            elif k.get("modul") == "Fatura / fiş / iade":
                k["sonuc"] = "OK" if "BELGE_SATIR" in tamam else ("Kısmi" if "BELGE_SATIR" in kismi else "Kısmi")
                k["kaynak_kanit"] = "D1_20260831_KAYNAK_BELGE.json + BELGE_SATIR"
        yaz_json(kp_yol, kp)

    print(json.dumps({"tamam": tamam, "kismi": kismi, "eksik": eksik, "k05_aday": k05_aday}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
