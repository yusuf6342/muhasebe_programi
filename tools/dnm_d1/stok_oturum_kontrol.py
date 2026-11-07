# -*- coding: utf-8 -*-
"""Veri sorgu oturumu doğrula: bilinen stok_id + firma 42178.

Boş 49 sonuçları ancak bu kontrol OK ise geçerli sayılır.
K05/mali yazım/EXE yok; 76/6 yeniden toplanmaz.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

from entegrasyon.evobulut_client import EvobulutClient, load_credentials

ROOT = Path(__file__).resolve().parents[2]
DNM = ROOT / "kurulum" / "dnm_d1_20260831"
KAYNAK = DNM / "kaynak"
OUT = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_OTURUM_KONTROL.json"
OZET = DNM / "STOK_OTURUM_KONTROL_OZET.json"
WEB = "https://web.evobulut.com"
FIRMA = "42178"

# Daha önce kesin bağlanan (55→6)
KONTROL = {
    "kaynak_stok_id": "8",
    "a_kod": "2406718340567",  # aşağıda dosyadan override
    "a_adi_ipucu": "ALMET U KAPAMA",
}


def _now() -> str:
    return datetime.now(timezone(datetime.now().astimezone().utcoffset())).isoformat()


def _sha16(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    path.with_suffix(path.suffix + ".sha256").write_text(h + "\n", encoding="utf-8")
    return h[:16]


def _beklenen_from_55() -> dict:
    p = KAYNAK / "D1_20260831_KAYNAK_STOK_ARA_55_KIMLIK.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for item in d.get("kayitlar") or d.get("sonuclar") or []:
        bag = item.get("baglanti") or {}
        if str(bag.get("kaynak_stok_id")) == "8":
            bul = (item.get("bulunan") or [{}])[0]
            return {
                "kaynak_stok_id": "8",
                "a_kod": str(bul.get("a_kod") or item.get("kod") or ""),
                "a_adi": bul.get("a_adi") or item.get("adi"),
                "ana_birim_adi": bul.get("ana_birim_adi"),
                "kanit_onceki": bag.get("kanit"),
            }
    # fallback: ara baglanan list
    for b in d.get("baglanan_liste") or []:
        if str(b.get("kaynak_stok_id")) == "8":
            return b
    # raw scan
    text = p.read_text(encoding="utf-8")
    # already know from prior read
    return {
        "kaynak_stok_id": "8",
        "a_kod": "2406718340567",
        "a_adi": "ALMET U KAPAMA 3 METRE PROFİL",
        "kanit_onceki": "STOK_ARA_55 baglanan",
    }


class WebSession:
    def __init__(self) -> None:
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self.token: str | None = None
        self.firma: str | None = None
        self.firma_adi: str | None = None
        self.login_raw_head: str = ""

    def _req(self, url: str, data: dict | str | None = None, *, json_body: dict | None = None) -> tuple[int, str]:
        body = None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Origin": WEB,
            "Referer": f"{WEB}/index.html",
        }
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=UTF-8"
        elif isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        elif isinstance(data, str):
            body = data.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with self.opener.open(req, timeout=90) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def login(self, email: str, password: str) -> dict:
        self._req(f"{WEB}/login.html")
        st, txt = self._req(
            f"{WEB}/ashx/login.ashx?komut=login",
            {"user_code": email, "user_pass": password, "remember": "on"},
        )
        self.login_raw_head = txt[:240].replace("\n", " ")
        try:
            j = json.loads(txt)
        except json.JSONDecodeError:
            return {"ok": False, "http": st, "hata": "json_degil", "head": self.login_raw_head}
        if not isinstance(j, list) or not j:
            return {"ok": False, "http": st, "hata": "beklenmeyen_yanit", "head": self.login_raw_head}
        j0 = j[0]
        # RES:OK formatı
        res = str(j0.get("RES") or j0.get("Sonuc") or "")
        self.token = j0.get("token") or j0.get("evo_token")
        self.firma = str(j0.get("firma") or j0.get("firma_id") or "")
        self.firma_adi = j0.get("firma_adi")
        ok = res.upper() == "OK" and bool(self.token) and self.firma == FIRMA
        return {
            "ok": ok,
            "http": st,
            "res": res,
            "firma": self.firma,
            "firma_adi": self.firma_adi,
            "token_var": bool(self.token),
            "firma_ok": self.firma == FIRMA,
        }

    def stok_sql(self, stok_id: str) -> dict:
        """UI ashx/stok.ashx komut=SQL — oturum+firma bağlı kontrol."""
        st, txt = self._req(
            f"{WEB}/ashx/stok.ashx?evo_server=web.evobulut.com",
            {
                "komut": "SQL",
                "kosul": stok_id,
                "evo_token": self.token or "",
                "evo_server": "web.evobulut.com",
            },
        )
        head = txt[:300].replace("\n", " ")
        try:
            j = json.loads(txt)
        except json.JSONDecodeError:
            return {"http": st, "ok": False, "hata": "json_degil", "head": head}
        # HATA oturum
        if isinstance(j, list) and j and str(j[0].get("Sonuc") or "").upper() == "HATA":
            return {
                "http": st,
                "ok": False,
                "hata": j[0].get("ERR") or j[0].get("SQL"),
                "head": head,
            }
        # UI yanıtı: {"S":[{"a_id","a_kod",...}], "barkod":[...], ...}
        a_id = a_kod = a_adi = None
        barkod_adet = None
        birim_adet = None
        if isinstance(j, dict):
            srows = j.get("S") or j.get("Ana") or j.get("ana")
            if isinstance(srows, list) and srows:
                row = srows[0]
                a_id = row.get("a_id")
                a_kod = row.get("a_kod")
                a_adi = row.get("a_adi")
            else:
                a_id = j.get("a_id")
                a_kod = j.get("a_kod")
                a_adi = j.get("a_adi")
            if isinstance(j.get("barkod"), list):
                barkod_adet = len(j["barkod"])
            if isinstance(j.get("s1"), list):  # birimler sık s1'de
                birim_adet = len(j["s1"])
        elif isinstance(j, list) and j:
            row = j[0]
            a_id = row.get("a_id")
            a_kod = row.get("a_kod")
            a_adi = row.get("a_adi")
        return {
            "http": st,
            "ok": bool(a_id),
            "a_id": str(a_id) if a_id is not None else None,
            "a_kod": a_kod,
            "a_adi": a_adi,
            "barkod_adet": barkod_adet,
            "birim_adet": birim_adet,
            "head": head,
            "keys": list(j.keys())[:20] if isinstance(j, dict) else f"list[{len(j)}]",
        }

    def guidejq_stok(self, *, kos: str, full_text: str = "", pagesize: int = 30) -> dict:
        """Doğru a_caller=1051 ile guidejq."""
        payload = {
            "a_caller": "1051",
            "profil": "",
            "modul": "",
            "grp": "",
            "kos": kos,
            "veri": "",
            "export": "view",
            "groupscount": "0",
            "Full_Text": full_text,
            "gnm": "jqxgrid_mod1051",
            "pagenum": "0",
            "pagesize": str(pagesize),
            "recordstartindex": "0",
            "recordendindex": str(pagesize),
            "filterscount": "0",
            "evo_token": self.token or "",
            "evo_server": "web.evobulut.com",
        }
        # evo_data JSON.parse(t) — application/json veya form? UI $.evo_data often form-encodes object
        st, txt = self._req(
            f"{WEB}/ashx/guidejq.ashx?evo_server=web.evobulut.com",
            payload,
        )
        head = txt[:350].replace("\n", " ")
        try:
            j = json.loads(txt)
        except json.JSONDecodeError:
            return {"http": st, "ok": False, "hata": "json_degil", "head": head}
        rows = []
        total = None
        if isinstance(j, list) and j:
            total = j[0].get("TotalRows")
            rows = j[0].get("Rows") or []
            # yanlış modül teşhisi
            sample = rows[0] if rows else {}
            keys = list(sample.keys())[:12] if isinstance(sample, dict) else []
            stok_mu = any(k.startswith("G.") or k in {"a_kod", "a_id"} for k in keys) or (
                "G.a_kod" in keys or "G.a_id" in keys
            )
            cari_mi = any(k.startswith("R.") for k in keys)
            return {
                "http": st,
                "ok": True,
                "total": total,
                "n": len(rows),
                "keys": keys,
                "stok_grid": stok_mu and not cari_mi,
                "cari_grid": cari_mi,
                "head": head,
                "ornek": {k: sample.get(k) for k in keys[:8]} if sample else {},
            }
        return {"http": st, "ok": False, "hata": "beklenmeyen", "head": head}


def api_kontrol(client: EvobulutClient, beklenen: dict) -> dict:
    sid = beklenen["kaynak_stok_id"]
    kod = beklenen["a_kod"]
    # sql
    det = client.stok_detay(sid)
    ana = det
    if isinstance(det, dict) and (det.get("Ana") or det.get("ana")):
        a = det.get("Ana") or det.get("ana")
        ana = a[0] if isinstance(a, list) and a else det
    a_id = str((ana or {}).get("a_id") or "")
    a_kod = str((ana or {}).get("a_kod") or "").strip()
    sql_ok = a_id == str(sid) and (not kod or a_kod == kod)
    # jq_list ara
    sat, adet = client.stok_liste_sayfa(0, ara=kod)
    exact = [s for s in sat if str(s.get("a_kod") or "").strip() == kod]
    jq_ok = bool(exact) and str(exact[0].get("a_id")) == str(sid)
    return {
        "sql": {
            "ok": sql_ok,
            "a_id": a_id or None,
            "a_kod": a_kod or None,
            "a_adi": (ana or {}).get("a_adi"),
            "beklenen_id": sid,
            "beklenen_kod": kod,
        },
        "jq_list_ara_kod": {
            "ok": jq_ok,
            "adet": adet,
            "exact": [
                {
                    "a_id": e.get("a_id"),
                    "a_kod": e.get("a_kod"),
                    "a_adi": e.get("a_adi"),
                    "aktif_pasif": e.get("aktif_pasif"),
                }
                for e in exact[:3]
            ],
        },
        "ok": sql_ok and jq_ok,
    }


def main() -> None:
    # beklenen kodu 55 dosyasından
    p55 = KAYNAK / "D1_20260831_KAYNAK_STOK_ARA_55_KIMLIK.json"
    d55 = json.loads(p55.read_text(encoding="utf-8"))
    beklenen = {
        "kaynak_stok_id": "8",
        "a_kod": "",
        "a_adi": "",
        "kanit_onceki": "STOK_ARA_55",
    }
    for item in d55.get("kayitlar") or []:
        if str((item.get("baglanti") or {}).get("kaynak_stok_id")) == "8":
            bul = (item.get("bulunan") or [{}])[0]
            beklenen = {
                "kaynak_stok_id": "8",
                "a_kod": str(bul.get("a_kod") or item.get("kod")),
                "a_adi": bul.get("a_adi") or item.get("adi"),
                "kanit_onceki": (item.get("baglanti") or {}).get("kanit"),
            }
            break
    if not beklenen["a_kod"]:
        # alternatif yapı
        for item in d55.get("sonuclar") or d55.get("ara") or []:
            if str((item.get("baglanti") or {}).get("kaynak_stok_id")) == "8":
                bul = (item.get("bulunan") or [{}])[0]
                beklenen["a_kod"] = str(bul.get("a_kod") or item.get("kod"))
                beklenen["a_adi"] = bul.get("a_adi") or item.get("adi")
                break
    if not beklenen["a_kod"]:
        # grep-like from known earlier read of bulunan for id 8
        # file structure: excel entries with bulunan[].a_id
        def walk(o: Any) -> None:
            if beklenen["a_kod"]:
                return
            if isinstance(o, dict):
                if str(o.get("a_id")) == "8" and o.get("a_kod"):
                    beklenen["a_kod"] = str(o["a_kod"])
                    beklenen["a_adi"] = o.get("a_adi")
                    return
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(d55)

    creds = load_credentials()
    client = EvobulutClient(creds)
    client.login()
    api = api_kontrol(client, beklenen)

    ws = WebSession()
    web_login = ws.login(creds.kullanici_kodu, creds.sifre)
    web_sql = ws.stok_sql(beklenen["kaynak_stok_id"]) if web_login.get("token_var") else {"ok": False, "hata": "token_yok"}
    web_sql_ok = (
        web_sql.get("ok")
        and str(web_sql.get("a_id")) == beklenen["kaynak_stok_id"]
        and (not beklenen["a_kod"] or str(web_sql.get("a_kod") or "").strip() == beklenen["a_kod"])
    )
    # guidejq smoke (yalnızca oturum+firma OK ise)
    guide = None
    if web_login.get("ok") and web_sql_ok:
        guide = ws.guidejq_stok(
            kos="pasif^x^15|barkod_goster^x^1|",
            full_text=beklenen["a_kod"],
        )

    # API başarısı web oturumu sayılmaz — web ayrı doğrulanır.
    api_oturum_ok = bool(api.get("ok"))
    web_oturum_ok = bool(web_login.get("ok") and web_sql_ok)
    # 49 araştırması yalnız web kontrolü OK ise açılır
    oturum_ok = web_oturum_ok

    kullanici_islem = None
    if not web_oturum_ok:
        kullanici_islem = {
            "gerekli": True,
            "ekran": "https://web.evobulut.com/login.html",
            "adimlar": [
                "Firma 42178 (DNM) ile giriş yapın",
                "Ürün Yönetimi → Stok Yönetimi açın",
                "Pasifleri Göster + Kod Sütununda Barkodlarıda Ara işaretleyin",
                f"Kontrol: Kodu = {beklenen.get('a_kod')} veya Id = {beklenen['kaynak_stok_id']} kaydı görünmeli",
                "Sonra 49 kod listesini aynı filtrelerle arayın; bulunan Id’yi paylaşın",
            ],
            "neden": (
                "Web ashx oturumu/kart kontrolü beklenen stok_id+firma döndürmedi; "
                "API OK olsa bile 49 boş sonuçları geçerli sayılmıyor."
            ),
            "api_ok_ama_web_degil": api_oturum_ok and not web_oturum_ok,
        }

    out = {
        "format": "d1-stok-oturum-kontrol-v1",
        "zaman": _now(),
        "firma_hedef": FIRMA,
        "beklenen": beklenen,
        "kural": "API kontrolü web oturumu yerine geçmez; 49 yalnız web_ok ile açılır",
        "api": api,
        "web_login": web_login,
        "web_stok_sql": {**web_sql, "eslesme_ok": web_sql_ok},
        "guidejq_smoke": guide,
        "oturum": {
            "api_ok": api_oturum_ok,
            "web_ok": web_oturum_ok,
            "tam_ok": oturum_ok,
            "api_web_ayri": True,
            "49_bos_sonuc_gecerli": bool(web_oturum_ok),
        },
        "kalan_49": {
            "durum": "OTURUM_OK_ARAMAYA_DEVAM" if web_oturum_ok else "ERISIM_NEDENIYLE_BEKLIYOR",
            "adet": 49,
            "bos_arama_gecerli_degil": not web_oturum_ok,
        },
        "kullanici_islem": kullanici_islem,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "yeniden_toplanmadi_76_ve_6": True,
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha = _sha16(OUT)
    ozet = {
        "zaman": out["zaman"],
        "api_ok": api_oturum_ok,
        "web_ok": web_oturum_ok,
        "tam_ok": oturum_ok,
        "firma_web": web_login.get("firma"),
        "kontrol_stok_id": beklenen["kaynak_stok_id"],
        "kontrol_kod": beklenen["a_kod"],
        "kalan_49": out["kalan_49"]["durum"],
        "kullanici_islem_gerekli": bool(kullanici_islem),
        "kanit": str(OUT.relative_to(DNM)).replace("\\", "/"),
        "sha16": sha,
        "k05": False,
    }
    OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sha16(OZET)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
