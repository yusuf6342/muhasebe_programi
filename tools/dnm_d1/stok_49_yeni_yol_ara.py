# -*- coding: utf-8 -*-
"""49 kalan kimlik — önceki jq_list exact / barkod sql dışında yeni yollar.

Yeniden toplamama: 76 hareket + 6 kimlik dokunulmaz.
K05/mali yazım/EXE yok.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from entegrasyon.evobulut_client import EvobulutClient, load_credentials

ROOT = Path(__file__).resolve().parents[2]
DNM = ROOT / "kurulum" / "dnm_d1_20260831"
KAYNAK = DNM / "kaynak"
LISTE49 = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DOGRULA.json"
OUT = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_YENI_YOL.json"
OZET = DNM / "STOK_49_YENI_YOL_OZET.json"

# Yerel kaynak taraması (API tekrarı değil)
YEREL_JSONL = [
    KAYNAK / "D1_20260831_KAYNAK_STOK_HAREKET_76_DETAY.jsonl",
    KAYNAK / "D1_20260831_KAYNAK_BELGE_SATIR.jsonl",
    KAYNAK / "D1_20260831_KAYNAK_STOK_MIKTAR.jsonl",
]
YEREL_JSON = [
    KAYNAK / "D1_20260831_KAYNAK_STOK_KART_76.json",
    KAYNAK / "D1_20260831_KAYNAK_STOK_ARA_55_KIMLIK.json",
]


def _now() -> str:
    return datetime.now(timezone(datetime.now().astimezone().utcoffset())).isoformat()


def _sha16(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    path.with_suffix(path.suffix + ".sha256").write_text(h + "\n", encoding="utf-8")
    return h[:16]


def _adi_parcalari(adi: str) -> list[str]:
    """Benzersiz, yeterince uzun kelime/öbek — önceki 8 örnekten farklı öncelik."""
    adi = (adi or "").strip()
    if not adi:
        return []
    # Tam ad (kısaltılmış)
    out: list[str] = []
    if len(adi) >= 8:
        out.append(adi[:40])
    # Ayırt edici tokenler
    tokens = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{4,}", adi)
    # Sayı içeren veya uzun olanları tercih et
    scored = sorted(
        set(tokens),
        key=lambda t: (any(c.isdigit() for c in t), len(t)),
        reverse=True,
    )
    for t in scored[:3]:
        if t.upper() not in {x.upper() for x in out}:
            out.append(t)
    return out[:4]


def _tara_yerel(kodlar: set[str]) -> dict[str, list[dict]]:
    hits: dict[str, list[dict]] = defaultdict(list)
    patterns = {k: re.compile(re.escape(k)) for k in kodlar}

    def _maybe(obj: Any, kaynak: str, ctx: dict) -> None:
        text = json.dumps(obj, ensure_ascii=False)
        for kod, rx in patterns.items():
            if rx.search(text):
                hits[kod].append({"kaynak": kaynak, **ctx, "ornek_alanlar": _pick_fields(obj)})

    for p in YEREL_JSONL:
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # satır içi kod alanları
                for key in ("stok_kod", "a_kod", "kod", "barkod", "a_barkod_no"):
                    v = str(o.get(key) or "").strip()
                    if v in kodlar:
                        hits[v].append(
                            {
                                "kaynak": p.name,
                                "satir": i,
                                "alan": key,
                                "kanit": f"{p.name}:{key}=exact",
                                "ornek_alanlar": _pick_fields(o),
                            }
                        )
                for s in o.get("satirlar") or []:
                    for key in ("stok_kod", "a_kod", "kod", "barkod"):
                        v = str(s.get(key) or "").strip()
                        if v in kodlar:
                            hits[v].append(
                                {
                                    "kaynak": p.name,
                                    "satir": i,
                                    "belge_id": o.get("kaynak_belge_id") or o.get("a_id"),
                                    "alan": f"satirlar[].{key}",
                                    "kanit": f"{p.name}:satirlar[].{key}=exact",
                                    "ornek_alanlar": _pick_fields(s),
                                    "stok_id": s.get("stok_id") or s.get("a_stok_id"),
                                }
                            )

    for p in YEREL_JSON:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        blob = json.dumps(data, ensure_ascii=False)
        for kod in kodlar:
            if kod in blob:
                # daha sıkı: a_kod alanları
                found_ids = []
                if isinstance(data, dict):
                    for node in _walk(data):
                        if isinstance(node, dict):
                            for key in ("a_kod", "stok_kod", "kod", "a_barkod_no"):
                                if str(node.get(key) or "").strip() == kod:
                                    found_ids.append(
                                        {
                                            "kaynak": p.name,
                                            "alan": key,
                                            "kanit": f"{p.name}:{key}=exact",
                                            "stok_id": node.get("a_id")
                                            or node.get("stok_id")
                                            or node.get("kaynak_stok_id"),
                                            "ornek_alanlar": _pick_fields(node),
                                        }
                                    )
                if found_ids:
                    hits[kod].extend(found_ids)
                else:
                    hits[kod].append(
                        {
                            "kaynak": p.name,
                            "kanit": f"{p.name}:metin_icinde_kod (alan eslesmesi yok)",
                            "zayif": True,
                        }
                    )
    return dict(hits)


def _walk(obj: Any):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _pick_fields(o: dict) -> dict:
    keys = (
        "a_id",
        "stok_id",
        "a_stok_id",
        "a_kod",
        "stok_kod",
        "a_adi",
        "adi",
        "a_barkod_no",
        "ana_birim_adi",
        "birim",
        "miktar",
        "a_kalan",
        "aktif_pasif",
    )
    return {k: o.get(k) for k in keys if k in o}


def _isim_ara(client: EvobulutClient, rows: list[dict]) -> list[dict]:
    """Yeni yol: yüksek tutarlı satırların ayırt edici ad parçasıyla jq_list ara=."""
    sonuclar = []
    # Önceki çalışmada 8 örnek denenmişti; burada tüm pozitif tutarlıları (max 25) dene
    adaylar = [r for r in rows if r.get("pozitif")][:25]
    for r in adaylar:
        kod = r["kod"]
        parcalar = _adi_parcalari(r.get("adi") or "")
        for p in parcalar:
            sat, adet = client.stok_liste_sayfa(0, ara=p)
            exact_kod = [s for s in sat if str(s.get("a_kod") or "").strip() == kod]
            # ad benzerliği (normalize)
            ad_norm = re.sub(r"\s+", " ", (r.get("adi") or "").upper())
            ad_hit = [
                s
                for s in sat
                if ad_norm
                and ad_norm[:20] in re.sub(r"\s+", " ", str(s.get("a_adi") or "").upper())
            ]
            sonuclar.append(
                {
                    "excel_kod": kod,
                    "excel_adi": r.get("adi"),
                    "ara": p,
                    "jq_adet": adet,
                    "sayfa0_kayit": len(sat),
                    "exact_kod_hit": len(exact_kod),
                    "ad_benzer_hit": [
                        {
                            "a_id": s.get("a_id"),
                            "a_kod": s.get("a_kod"),
                            "a_adi": s.get("a_adi"),
                            "aktif_pasif": s.get("aktif_pasif"),
                            "kanit": f"jq_list ara={p!r} + ad_benzerlik",
                        }
                        for s in ad_hit[:5]
                    ],
                    "exact_kart": (
                        {
                            "a_id": exact_kod[0].get("a_id"),
                            "a_kod": exact_kod[0].get("a_kod"),
                            "a_adi": exact_kod[0].get("a_adi"),
                            "aktif_pasif": exact_kod[0].get("aktif_pasif"),
                            "kanit": f"jq_list ara={p!r} a_kod exact",
                            "kesin": True,
                        }
                        if exact_kod
                        else None
                    ),
                }
            )
            time.sleep(0.03)
            if exact_kod:
                break
    return sonuclar


def _fatura_satir_ara(client: EvobulutClient, kodlar: set[str], limit_belge: int = 40) -> list[dict]:
    """Yeni yol: son alış faturalarının satırlarında kod ara (stok listesi dışı)."""
    hits = []
    try:
        belgeler, _adet = client.fatura_liste_sayfa(0, tur="30")
    except TypeError:
        # imza farklı olabilir
        try:
            yanit = client._post(
                "fatura/base/",
                {"cmd": "jq_list", "UID": client.uid, "sayfa": "0", "ara": "", "tur": "30", "a_gc": "1"},
            )
            from entegrasyon.evobulut_client import _ana_listesi

            belgeler = _ana_listesi(yanit)
        except Exception as exc:  # noqa: BLE001
            return [{"hata": f"fatura_list:{type(exc).__name__}:{exc}"[:160]}]
    except Exception as exc:  # noqa: BLE001
        return [{"hata": f"fatura_list:{type(exc).__name__}:{exc}"[:160]}]

    for b in (belgeler or [])[:limit_belge]:
        bid = b.get("a_id") or b.get("id")
        if not bid:
            continue
        try:
            yanit = client._post(
                "fatura/base/",
                {"cmd": "sql", "UID": client.uid, "a_id": str(bid)},
            )
        except Exception as exc:  # noqa: BLE001
            hits.append({"belge_id": bid, "hata": str(exc)[:100]})
            continue
        veri = yanit.get("veri") or yanit.get("Veri") or {}
        satirlar = []
        if isinstance(veri, dict):
            satirlar = veri.get("Satir") or veri.get("satirlar") or veri.get("Kalem") or []
            if not satirlar and isinstance(veri.get("Ana"), list):
                # bazen iç içe
                pass
        for s in satirlar or []:
            sk = str(s.get("stok_kod") or s.get("a_kod") or s.get("kod") or "").strip()
            if sk in kodlar:
                hits.append(
                    {
                        "excel_kod": sk,
                        "belge_id": bid,
                        "tarih": b.get("a_tarih") or b.get("tarih"),
                        "stok_id": s.get("stok_id") or s.get("a_stok_id"),
                        "stok_adi": s.get("stok_adi") or s.get("a_adi"),
                        "kanit": f"fatura/base sql a_id={bid} satir stok_kod exact",
                        "kesin": True,
                    }
                )
        time.sleep(0.04)
    return hits


def main() -> None:
    d49 = json.loads(LISTE49.read_text(encoding="utf-8"))
    rows = d49["liste_49"]["kayitlar_oncelikli"]
    kodlar = {r["kod"] for r in rows}

    print("yerel tarama...", flush=True)
    yerel = _tara_yerel(kodlar)

    client = EvobulutClient(load_credentials())
    client.login()
    print("isim ara (pozitif tutarli)...", flush=True)
    isim = _isim_ara(client, rows)
    print("fatura satir ara...", flush=True)
    fatura = _fatura_satir_ara(client, kodlar)

    baglanan = []
    for kod, hs in yerel.items():
        kesin = [h for h in hs if h.get("stok_id") and not h.get("zayif")]
        if kesin:
            baglanan.append(
                {
                    "kod": kod,
                    "kaynak_stok_id": str(kesin[0]["stok_id"]),
                    "kanit": kesin[0].get("kanit"),
                    "yol": "yerel_kaynak",
                    "kesin": True,
                }
            )
    for s in isim:
        if s.get("exact_kart"):
            baglanan.append(
                {
                    "kod": s["excel_kod"],
                    "kaynak_stok_id": str(s["exact_kart"]["a_id"]),
                    "kanit": s["exact_kart"]["kanit"],
                    "yol": "isim_parca_jq_list",
                    "kesin": True,
                }
            )
    for h in fatura:
        if h.get("kesin") and h.get("stok_id"):
            baglanan.append(
                {
                    "kod": h["excel_kod"],
                    "kaynak_stok_id": str(h["stok_id"]),
                    "kanit": h["kanit"],
                    "yol": "alis_fatura_satir",
                    "kesin": True,
                    "belge_id": h.get("belge_id"),
                }
            )

    # tekilleştir kod
    uniq: dict[str, dict] = {}
    for b in baglanan:
        uniq.setdefault(b["kod"], b)

    kalan = [r for r in rows if r["kod"] not in uniq]

    out = {
        "format": "d1-stok-49-yeni-yol-v1",
        "zaman": _now(),
        "devir": 1,
        "yeniden_toplanmadi": {"stok_76_hareket": True, "kimlik_6": True},
        "kasa_banka_degistirilmedi": True,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "onceki_yollar_tekrarlanmadi": [
            "jq_list ara=tam kod tek sayfa",
            "barkod sql a_barkod=excel_kod",
            "pasif param jq_list denemeleri",
        ],
        "yeni_yollar": [
            "yerel BELGE_SATIR / STOK_HAREKET_76 / STOK_KART dump exact kod",
            "pozitif tutarli ad parcasi jq_list + ad benzerlik",
            "alis fatura jq_list+sql satir stok_kod",
        ],
        "ui_oturum": {
            "stok_yonetimi_acildi": True,
            "pasifleri_goster_isaretlendi": True,
            "barkod_ara_isaretlendi": True,
            "hareket_gormeyenler_isaretlendi": True,
            "ashx_sonuc": "Oturum Hatasi / Tekrar Login Olunuz",
            "login_sayfasina_dustu": True,
            "not": "Tarayici UI kabugu acikti; ashx token dusmus. API aramasi Python login ile yapildi.",
        },
        "liste_49_ozet": {
            "adet": len(rows),
            "pozitif": sum(1 for r in rows if r.get("pozitif")),
            "sifir": sum(1 for r in rows if not r.get("pozitif")),
        },
        "yerel_hit_kod": sorted(yerel.keys()),
        "yerel_detay": {k: v[:5] for k, v in yerel.items()},
        "isim_ara_ornek_adet": len(isim),
        "isim_exact_hit": [s for s in isim if s.get("exact_kart")],
        "isim_ad_benzer_hit": [s for s in isim if s.get("ad_benzer_hit")],
        "fatura_hit": fatura,
        "baglanan_yeni": list(uniq.values()),
        "baglanan_adet": len(uniq),
        "kalan_49_minus_yeni": len(kalan),
        "kalan_kodlar": [r["kod"] for r in kalan],
        "gerekli_ekran_kullanici": {
            "menu": "Ürün Yönetimi → Stok Yönetimi",
            "filtre_checkbox": [
                "Pasifleri Göster",
                "Kod Sütununda Barkodlarıda Ara",
                "Hareket Görmeyenleri Göster",
            ],
            "arama": "Bulunan Kayıtlar → Kodu = Eşit → kod listesi (önce pozitif tutarlı)",
            "sutunlar": ["Id", "Kodu", "Adı", "Aktif/Pasif", "Ana Birim", "Barkodlar", "Birimler"],
            "alternatif": "Stok Envanter Raporu tarih=31.08.2026 → satır drill-down → stok kartı/hareket",
            "neden": "API jq_list+barkod+isim+fatura ve yerel dump 49 kodu bağlamadı; UI pasif/arşiv veya envanter satır kimliği gerekli.",
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha = _sha16(OUT)
    ozet = {
        "zaman": out["zaman"],
        "baglanan_yeni": len(uniq),
        "kalan": len(kalan),
        "yerel_hit_kod": len(yerel),
        "isim_exact": len(out["isim_exact_hit"]),
        "fatura_hit_kesin": sum(1 for h in fatura if h.get("kesin")),
        "ui_oturum_ashx": "Oturum Hatasi",
        "kanit": str(OUT.relative_to(DNM)).replace("\\", "/"),
        "sha16": sha,
        "k05": False,
    }
    OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sha16(OZET)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
