"""EvoBulut DNM D1 kaynak kapanış — salt okuma envanter + dönem hareketleri.

Bugünkü kart bakiyesini 31.08.2026 kapanışı saymaz.
Şifre/token dosyaya yazılmaz. Mali hedefe yazmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_kapanis_cek
  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_kapanis_cek --sadece-firma
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import (
    CALISMA_KOK,
    DONEM_SONU,
    HARIC_UST_SINIR_YEREL,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    RAPOR_ONEKI_KAYNAK,
)

KOK = Path(__file__).resolve().parents[2]
KAYNAK_DIR = KOK / CALISMA_KOK / "kaynak"

BAS_TAR = "01.01.2015"  # alt sınır sabitlenmez; API için geniş aralık, üst 31.08.2026
SON_TAR = DONEM_SONU.strftime("%d.%m.%Y")


def _yaz(ad: str, veri: Any) -> Path:
    KAYNAK_DIR.mkdir(parents=True, exist_ok=True)
    yol = KAYNAK_DIR / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    ham = json.dumps(veri, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")
    print(f"YAZILDI {yol.name} sha256={ozet[:16]}... ({len(ham)} bayt)", flush=True)
    return yol


def _firma_dogrula(istemci) -> dict[str, Any]:
    """Login sonrası firma kimliğini mümkün olan alanlardan çıkar.

    Oturum UID'si firma numarası değildir; rapora yazılmaz.
    """
    bilgi: dict[str, Any] = {
        "beklenen_firma_no": KAYNAK_FIRMA_NO,
        "beklenen_firma_adi": KAYNAK_FIRMA_ADI,
        "dogrulandi": False,
        "oturum_acildi": bool(getattr(istemci, "uid", None)),
        "ham_ipucu": {},
    }
    for alan in ("firma_no", "firma_id", "sirket_id", "firma_adi", "sirket_adi"):
        if hasattr(istemci, alan):
            bilgi["ham_ipucu"][alan] = getattr(istemci, alan)
    for alan in ("_son_login", "login_yaniti", "oturum"):
        if hasattr(istemci, alan):
            v = getattr(istemci, alan)
            if isinstance(v, (dict, str, int)):
                # UID / token sızdırma
                if isinstance(v, dict):
                    temiz = {
                        k: ("***" if "uid" in k.lower() or "token" in k.lower() or "sifre" in k.lower() else val)
                        for k, val in v.items()
                    }
                    bilgi["ham_ipucu"][alan] = temiz
                else:
                    bilgi["ham_ipucu"][alan] = v

    metin = json.dumps(bilgi["ham_ipucu"], ensure_ascii=False, default=str)
    if KAYNAK_FIRMA_NO in metin:
        bilgi["dogrulandi"] = True
        bilgi["bulunan_no"] = KAYNAK_FIRMA_NO
    else:
        bilgi["uyari"] = (
            "API login oturum açtı fakat firma no 42178 yanıtta yok. "
            "DNM – RAY MOBİLYA AKSESUARLAR ETÜD / 42178 web oturumunda doğrulanmalı; "
            "oturum UID firma kimliği değildir."
        )
    return bilgi


def calistir(*, sadece_firma: bool = False) -> int:
    from entegrasyon.evobulut_client import EvobulutClient, EvobulutConfigError, load_credentials

    t0 = time.time()
    alim = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        istemci = EvobulutClient(load_credentials())
        istemci.login()
    except EvobulutConfigError as exc:
        print("CONFIG_HATA", type(exc).__name__, flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        print("LOGIN_HATA", type(exc).__name__, str(exc)[:200], flush=True)
        return 3

    firma = _firma_dogrula(istemci)
    _yaz(
        "FIRMA_DONEM",
        {
            "format": "d1-kaynak-firma-donem-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "haric_ust_sinir": HARIC_UST_SINIR_YEREL.isoformat(),
            "bas_tar_api": BAS_TAR,
            "son_tar_api": SON_TAR,
            "firma": firma,
            "not": (
                "Kart güncel bakiyesi Ağustos kapanışı değildir. "
                "Kapanış, dönem içi hareketlerden veya tarihli resmi rapordan kurulur."
            ),
        },
    )
    if sadece_firma:
        print("SADECE_FIRMA bitti", flush=True)
        return 0 if firma.get("dogrulandi") else 4

    def adim(ad: str, fn):
        t = time.time()
        print(f"... {ad}", flush=True)
        veri = fn()
        n = len(veri) if isinstance(veri, list) else "?"
        print(f"    {ad}: {n} ({time.time() - t:.0f}s)", flush=True)
        return veri

    cariler = adim("cari kart", istemci.tum_carileri_cek)
    stoklar = adim("stok kart", istemci.tum_stoklari_cek)
    kasalar = adim("kasa kart", istemci.kasa_kart_listesi)
    bankalar = adim("banka kart", istemci.banka_kart_listesi)

    _yaz(
        "CARI",
        {
            "format": "d1-kaynak-cari-envanter-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "adet": len(cariler),
            "kayitlar": cariler,
            "uyari": "Liste bakiyeleri güncel görüntü olabilir; kapanış için ekstre/hareket gerekir.",
        },
    )
    _yaz(
        "STOK_MIKTAR",
        {
            "format": "d1-kaynak-stok-envanter-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "adet": len(stoklar),
            "kayitlar": stoklar,
            "uyari": "a_kalan güncel olabilir; 31.08 kapanış için hareket yeniden kurulmalı.",
        },
    )

    print("... kasa hareketleri", flush=True)
    kasa_hrk = istemci.tum_kasa_islemlerini_cek(bas_tar=BAS_TAR, son_tar=SON_TAR)
    print(f"    kasa hareket (ham jq_list): {len(kasa_hrk)}", flush=True)

    print("... banka hareketleri", flush=True)
    banka_hrk = istemci.tum_banka_islemlerini_cek(bas_tar=BAS_TAR, son_tar=SON_TAR)
    print(f"    banka hareket: {len(banka_hrk)}", flush=True)
    _yaz(
        "BANKA",
        {
            "format": "d1-kaynak-banka-v1",
            "alim_zamani": alim,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "kart_adet": len(bankalar),
            "kartlar": bankalar,
            "hareket_adet": len(banka_hrk),
            "hareketler": banka_hrk,
            "aralik": {"bas": BAS_TAR, "son": SON_TAR},
        },
    )

    # Kasa jq_list Bankadan Çekilen / Bankaya Yatırılan döndürmez; banka tur 22/23
    # MKB=kasa karşı bacak görünümü eklenir (banka çoğaltılmaz).
    from tools.dnm_d1.kasa_banka_transfer_bacak import kasa_hareketlerini_zenginlestir

    kasa_paket = {
        "format": "d1-kaynak-kasa-v1",
        "alim_zamani": alim,
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "kart_adet": len(kasalar),
        "kartlar": kasalar,
        "hareket_adet": len(kasa_hrk),
        "hareketler": kasa_hrk,
        "aralik": {"bas": BAS_TAR, "son": SON_TAR},
    }
    kasa_paket, karsi_ozet = kasa_hareketlerini_zenginlestir(
        kasa_paket, {"hareketler": banka_hrk}
    )
    print(
        f"    kasa hareket (karşı bacak sonrası): {kasa_paket['hareket_adet']} "
        f"(+{karsi_ozet.get('eklenen', 0)})",
        flush=True,
    )
    _yaz("KASA", kasa_paket)

    manifest = {
        "format": "d1-kaynak-manifest-v1",
        "alim_zamani": alim,
        "alim_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "haric_ust_sinir": HARIC_UST_SINIR_YEREL.isoformat(),
        "firma": firma,
        "ozet": {
            "cari_kart": len(cariler),
            "stok_kart": len(stoklar),
            "kasa_kart": len(kasalar),
            "kasa_hareket_ham_jq": len(kasa_hrk),
            "kasa_hareket": kasa_paket["hareket_adet"],
            "kasa_karsi_bacak_bankadan": karsi_ozet.get("eklenen", 0),
            "banka_kart": len(bankalar),
            "banka_hareket": len(banka_hrk),
        },
        "kasa_kapsam_notu": (
            "KasaHareketleri jq_list tur 22/23 (Bankaya Yatırılan / Bankadan Çekilen) "
            "döndürmez. Kasa kapsamı banka aynı olayların MKB=kasa karşı bacak "
            "görünümü ile tamamlanır; banka hareketi ikinci kez yazılmaz."
        ),
        "eksik_moduller": [
            "ACIK_KALEM",
            "STOK_MALIYET_LOT",
            "POS",
            "KART_KREDI",
            "GIDER_GELIR",
            "BELGE",
            "CARI_EKSTRE_KAPANIS",
        ],
        "kapanis_durumu": "KISMI_ENVANTER",
        "not": (
            "Bu çekim tam 31.08 mutabakat paketi değildir. "
            "Açık kalem, stok maliyet/LOT, POS/kart, belge ve cari ekstre kapanışı ayrı tamamlanacak. "
            "K05 kapısı bu dosyayla açılmaz."
        ),
        "sure_sn": round(time.time() - t0, 1),
    }
    _yaz("MANIFEST", manifest)
    print("KAPANIS_DURUMU", manifest["kapanis_durumu"], flush=True)
    print("SURE_SN", manifest["sure_sn"], flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DNM D1 kaynak kapanış salt okuma")
    p.add_argument("--sadece-firma", action="store_true")
    args = p.parse_args(argv)
    return calistir(sadece_firma=args.sadece_firma)


if __name__ == "__main__":
    raise SystemExit(main())
