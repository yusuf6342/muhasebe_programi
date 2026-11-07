"""API login vs web login oturum çakışması — salt gözlem notu.

Tekrarlı client.login() / web_login() aynı süreçte token yeniler.
Ayrı tarayıcı oturumu ile script web oturumu birbirini düşürebilir.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]


def main() -> int:
    notu = {
        "format": "d2-oturum-cakisma-not-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bulgular": [
            {
                "kanal": "API (UID)",
                "davranis": "EvobulutClient.login() yeni UID üretir; önceki API UID geçersiz olabilir",
            },
            {
                "kanal": "Web (evo_token/cookie)",
                "davranis": (
                    "web_login() ayrı cookie jar; tarayıcıda yeniden giriş script web oturumunu "
                    "düşürebilir (Oturum Hatasi). Script web_login yenilemesi tarayıcıyı "
                    "zorunlu düşürmez ama aynı hesapta eşzamanlı oturum limiti varsa düşürür."
                ),
            },
            {
                "kanal": "Kontrol",
                "davranis": (
                    "Canlı sorgudan önce: API login + web_login + bilinen stok_id=8 "
                    "(a_kod=2406720255467) + firma 42178 doğrula; boş 49 sonucu kabul etme."
                ),
            },
        ],
        "kullanici_islem": (
            "Web düştüyse: tarayıcıda web.evobulut.com DNM (42178) girişi yap; "
            "script’e «yeniden girdim» de. Eşzamanlı iki script login çalıştırma."
        ),
        "k05": False,
    }
    yol = KOK / CALISMA_KOK / "plan" / "OTURUM_CAKISMA_NOTU.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(notu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"yazildi": str(yol)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
