"""EvoBulut DNM firma kimliği (42178) doğrulama — salt okuma.

Oturum UID firma numarası değildir. Yanıttaki kalıcı firma alanlarını arar.
Şifre/token yazılmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.firma_dogrula
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import (
    CALISMA_KOK,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    RAPOR_ONEKI_KAYNAK,
)

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"

_GIZLI = re.compile(r"(sifre|password|token|uid|cookie|authorization|p2)", re.I)


def _temizle(obj: Any, *, derinlik: int = 0) -> Any:
    if derinlik > 8:
        return "…"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _GIZLI.search(str(k)):
                out[k] = "***"
            else:
                out[k] = _temizle(v, derinlik=derinlik + 1)
        return out
    if isinstance(obj, list):
        return [_temizle(x, derinlik=derinlik + 1) for x in obj[:50]]
    if isinstance(obj, str) and len(obj) > 200 and re.fullmatch(r"[0-9a-fA-F-]{20,}", obj):
        return "***"
    return obj


def _ara_42178(obj: Any, yol: str = "") -> list[str]:
    bulgular: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            yp = f"{yol}.{k}" if yol else str(k)
            if str(v) == KAYNAK_FIRMA_NO or (isinstance(v, (int, float)) and int(v) == int(KAYNAK_FIRMA_NO)):
                bulgular.append(yp)
            elif isinstance(v, str) and KAYNAK_FIRMA_NO in v and "uid" not in yp.lower():
                bulgular.append(f"{yp}~contains")
            bulgular.extend(_ara_42178(v, yp))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:200]):
            bulgular.extend(_ara_42178(v, f"{yol}[{i}]"))
    return bulgular


def _adi_eslesiyor_mu(metin: str) -> bool:
    u = metin.upper().replace("İ", "I")
    return "DNM" in u and ("RAY" in u or "MOBILYA" in u or "MOBİLYA" in u)


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, EvobulutConfigError, load_credentials

    alim = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        creds = load_credentials()
        istemci = EvobulutClient(creds)
    except EvobulutConfigError as exc:
        print("CONFIG_HATA", type(exc).__name__, flush=True)
        return 2

    # Ham login yanıtını yakala (client.login sadece UID döner)
    yanit = istemci._post(
        "index/base/",
        {
            "cmd": "euas",
            "p1": creds.kullanici_kodu,
            "p2": creds.sifre,
            "app": creds.app,
        },
    )
    from entegrasyon.evobulut_client import _uid_bul

    uid = _uid_bul(yanit)
    if not uid:
        print("LOGIN_HATA", flush=True)
        return 3
    istemci.uid = uid

    temiz_login = _temizle(yanit)
    yollar = _ara_42178(yanit)

    # Ek uçlar: sık görülen firma/şirket bilgi komutları (yoksa sessizce atlanır)
    ek_yanitlar: dict[str, Any] = {}
    aday_istekler = [
        ("index/base/", {"cmd": "user_info", "UID": uid}),
        ("index/base/", {"cmd": "firma", "UID": uid}),
        ("index/base/", {"cmd": "sirket", "UID": uid}),
        ("index/base/", {"cmd": "aktif_firma", "UID": uid}),
        ("Firma/base/", {"cmd": "sql", "UID": uid}),
        ("Sirket/base/", {"cmd": "sql", "UID": uid}),
        ("cari/base/", {"cmd": "jq_list", "UID": uid, "pagenum": "0", "pagesize": "1"}),
    ]
    for path, payload in aday_istekler:
        try:
            y = istemci._post(path, payload)
            anahtar = f"{path}|{payload.get('cmd')}"
            ek_yanitlar[anahtar] = _temizle(y)
            yollar.extend(f"{anahtar}:{p}" for p in _ara_42178(y))
        except Exception as exc:  # noqa: BLE001
            ek_yanitlar[f"{path}|{payload.get('cmd')}"] = {"hata": type(exc).__name__}

    # Cari listesinden örnek unvan / metin taraması (firma adı değil; çapraz ipucu)
    ad_ipuclari: list[str] = []
    try:
        sayfa, toplam = istemci.cari_liste_sayfa(0)
        for s in sayfa[:5]:
            t = str(s.get("text") or s.get("R.a_ad") or "")
            if t:
                ad_ipuclari.append(t[:120])
    except Exception as exc:  # noqa: BLE001
        ad_ipuclari.append(f"cari_hata:{type(exc).__name__}")

    dogrulandi = bool(yollar)
    kanit = {
        "format": "d1-firma-dogrulama-v1",
        "alim_zamani": alim,
        "beklenen_firma_no": KAYNAK_FIRMA_NO,
        "beklenen_firma_adi": KAYNAK_FIRMA_ADI,
        "dogrulandi": dogrulandi,
        "kalici_kimlik_yollari": yollar[:50],
        "login_yanit_ozeti": {
            "tip": type(yanit).__name__,
            "ust_anahtarlar": list(yanit.keys()) if isinstance(yanit, dict) else None,
            "temiz": temiz_login,
        },
        "ek_uclar": ek_yanitlar,
        "cari_ornek_metinler": ad_ipuclari,
        "not": (
            "Oturum UID firma kimliği değildir ve kanıta yazılmaz. "
            "42178 bulunamazsa web.evobulut.com oturumunda firma adı/numarası kullanıcı doğrulaması gerekir."
        ),
    }

    KAYNAK.mkdir(parents=True, exist_ok=True)
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}FIRMA_DOGRULAMA.json"
    ham = json.dumps(kanit, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")

    # Manifest güncelle
    man_yol = KOK / CALISMA_KOK / "CALISMA_MANIFESTI.json"
    if man_yol.is_file():
        man = json.loads(man_yol.read_text(encoding="utf-8"))
        man.setdefault("kaynak", {})["firma_no_dogrulandi"] = dogrulandi
        man["kaynak"]["firma_dogrulama_kaniti"] = str(yol.relative_to(KOK)).replace("\\", "/")
        man["kaynak"]["firma_dogrulama_zamani"] = alim
        if dogrulandi:
            man["kaynak"]["firma_no_bulunan"] = KAYNAK_FIRMA_NO
        man_yol.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("DOGRULANDI" if dogrulandi else "DOGRULANAMADI", flush=True)
    print("KANIT", yol, flush=True)
    print("YOLLAR", len(yollar), flush=True)
    for p in yollar[:20]:
        print("  ", p, flush=True)
    return 0 if dogrulandi else 4


if __name__ == "__main__":
    raise SystemExit(main())
