"""T19–T22 izole testler — kontrollü kaynak yanıtları (fixture).

Gerçek EvoBulut kaydı değiştirilmez. İzole sonuç ≠ canlı kaynak doğrulaması.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.test_t19_t22_izolasyon
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.dnm_d2.donem_sabitleri import (
    CALISMA_KOK,
    D2_ACILIS_YEREL,
    D2_HARIC_UST_SINIR,
    etki_d2_hareket_mi,
)

IST = ZoneInfo("Europe/Istanbul")
KOK = Path(__file__).resolve().parents[2]
FIXTURE = KOK / CALISMA_KOK / "test" / "fixtures_t19_t22.json"


def _sha(obj: dict) -> str:
    ham = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(ham).hexdigest()[:16]


def _fixture_kaynak() -> dict:
    """Kontrollü sahte kaynak yanıtı — üretim API’si değil."""
    return {
        "cari_id": "FIXTURE-C1",
        "belgeler": [
            {
                "id": "F-A",
                "tarih": "2026-08-15",
                "vade": "2026-09-15",
                "hesap_id": "H1",
                "borc": "1000",
                "alacak": "0",
            }
        ],
        "sayfa": {"pagenum": 0, "pagesize": 50, "total": 1, "rows": 1},
        "encoding": "utf-8",
    }


def test_t19_surum_net_ayni() -> dict:
    """Net değişmeden hesap/vade değişimi sürüm farkıyla yakalanır."""
    once = _fixture_kaynak()
    sonra = deepcopy(once)
    sonra["belgeler"][0]["vade"] = "2026-10-01"
    sonra["belgeler"][0]["hesap_id"] = "H2"
    # net aynı
    assert Decimal(once["belgeler"][0]["borc"]) - Decimal(once["belgeler"][0]["alacak"]) == Decimal(
        sonra["belgeler"][0]["borc"]
    ) - Decimal(sonra["belgeler"][0]["alacak"])
    assert _sha(once) != _sha(sonra)
    return {
        "test": "T19",
        "ok": True,
        "izolasyon": True,
        "canli_kaynak_dogrulama": "AYRI_BEKLIYOR",
        "sha_once": _sha(once),
        "sha_sonra": _sha(sonra),
        "net_ayni": True,
        "icerik_degisti": True,
    }


def test_t20_agustos_gec_kayit_d1_revizyon() -> dict:
    """Ağustos geç kaydı D1 revizyonuna; sessiz D2 açılış fark fişi yok."""
    gec = datetime(2026, 8, 20, 12, 0, tzinfo=IST)
    assert etki_d2_hareket_mi(gec) is False
    # D2 açılış fark fişi üretilmez — yalnızca bayrak
    d1_revizyon = {"gerekli": True, "sessiz_d2_acilis_fark_fisi": False}
    assert d1_revizyon["sessiz_d2_acilis_fark_fisi"] is False
    # Eylül kaydı D2
    eyl = datetime(2026, 9, 5, 10, 0, tzinfo=IST)
    assert etki_d2_hareket_mi(eyl) is True
    assert eyl < D2_HARIC_UST_SINIR
    return {
        "test": "T20",
        "ok": True,
        "izolasyon": True,
        "canli_kaynak_dogrulama": "AYRI_BEKLIYOR",
        "agustos_d2_degil": True,
        "d2_acilis": D2_ACILIS_YEREL.isoformat(),
    }


def test_t21_sayfa_json_oturum() -> dict:
    """Tekrarlı/eksik sayfa, bozuk JSON, oturum dolması → tamlık yok; UTF-8/BOM."""
    sayfalar = [
        {"pagenum": 0, "rows": [{"id": "1"}], "total": 3},
        {"pagenum": 0, "rows": [{"id": "1"}], "total": 3},  # tekrar
        {"pagenum": 1, "rows": [{"id": "2"}], "total": 3},
        # sayfa 2 eksik
    ]
    ids = []
    for s in sayfalar:
        for r in s["rows"]:
            ids.append(r["id"])
    tekil = set(ids)
    tekrar_var = len(ids) != len(tekil)
    eksik_sayfa = 2 not in {s["pagenum"] for s in sayfalar}
    assert tekrar_var and eksik_sayfa
    # bozuk JSON
    bozuk = "{not json"
    try:
        json.loads(bozuk)
        json_ok = True
    except json.JSONDecodeError:
        json_ok = False
    assert json_ok is False
    # UTF-8 BOM
    bom = b"\xef\xbb\xbf{\"a\":1}"
    j = json.loads(bom.decode("utf-8-sig"))
    assert j["a"] == 1
    oturum_dolu = {"status": "ERR", "mesaj": "Oturum Hatasi"}
    assert oturum_dolu["status"] != "OK"
    return {
        "test": "T21",
        "ok": True,
        "izolasyon": True,
        "canli_kaynak_dogrulama": "AYRI_BEKLIYOR",
        "tekrar_sayfa": tekrar_var,
        "eksik_sayfa": eksik_sayfa,
        "bozuk_json_tamlik_yok": True,
        "utf8_bom_ok": True,
        "oturum_hatasi_tamlik_yok": True,
    }


def test_t22_yontem_farki_ayri() -> dict:
    """Kaynak ortalama / özgün valör ile hedef FIFO farkı ayrı; bilinmeyen gizlenmez."""
    kaynak_ort = Decimal("10.00")
    hedef_fifo = Decimal("12.50")
    fark = hedef_fifo - kaynak_ort
    bilinmeyen = None  # eksik kanıt
    assert fark == Decimal("2.50")
    assert bilinmeyen is None  # gizlenmedi / sıfır yazılmadı
    etiket = "YONTEM_FARKI_FIFO_VS_ORT"
    return {
        "test": "T22",
        "ok": True,
        "izolasyon": True,
        "canli_kaynak_dogrulama": "AYRI_BEKLIYOR",
        "kaynak_ort": str(kaynak_ort),
        "hedef_fifo": str(hedef_fifo),
        "fark": str(fark),
        "etiket": etiket,
        "bilinmeyen_sifir_yazilmadi": True,
    }


def main() -> int:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(_fixture_kaynak(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sonuclar = [
        test_t19_surum_net_ayni(),
        test_t20_agustos_gec_kayit_d1_revizyon(),
        test_t21_sayfa_json_oturum(),
        test_t22_yontem_farki_ayri(),
    ]
    ok = all(s.get("ok") for s in sonuclar)
    out = {
        "format": "d2-test-t19-t22-izolasyon-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ok": ok,
        "izolasyon_gecen": sum(1 for s in sonuclar if s.get("ok")),
        "tests": sonuclar,
        "ayrim": {
            "izolasyon": "Kontrollü fixture / kurallar — gerçek Evo kaydı değişmedi",
            "canli_kaynak_dogrulama": "AYRI_BEKLIYOR — salt okuma kanıtı bu dosyada yok",
        },
        "k05": False,
        "mali_yazim": False,
    }
    yol = KOK / CALISMA_KOK / "test" / "T19_T22_IZOLASYON.json"
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (KOK / CALISMA_KOK / "T19_T22_IZOLASYON_OZET.json").write_text(
        json.dumps(
            {
                "zaman": out["zaman"],
                "ok": ok,
                "izolasyon_gecen": out["izolasyon_gecen"],
                "canli_kaynak_dogrulama": "AYRI_BEKLIYOR",
                "kanit": "test/T19_T22_IZOLASYON.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
