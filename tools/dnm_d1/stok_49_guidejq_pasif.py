# -*- coding: utf-8 -*-
"""49 kod — UI guidejq.ashx yolu (pasif^x^15|barkod_goster^x^1). jq_list tekrarı değil."""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

from entegrasyon.evobulut_client import load_credentials

ROOT = Path(__file__).resolve().parents[2]
DNM = ROOT / "kurulum" / "dnm_d1_20260831"
KAYNAK = DNM / "kaynak"
LISTE49 = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DOGRULA.json"
OUT = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_GUIDEJQ_PASIF.json"
OZET = DNM / "STOK_49_GUIDEJQ_PASIF_OZET.json"
WEB = "https://web.evobulut.com"


def _now() -> str:
    return datetime.now(timezone(datetime.now().astimezone().utcoffset())).isoformat()


def _sha16(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    path.with_suffix(path.suffix + ".sha256").write_text(h + "\n", encoding="utf-8")
    return h[:16]


class WebSession:
    def __init__(self) -> None:
        self.cj = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self.token: str | None = None

    def _req(self, url: str, data: dict | None = None, method: str = "GET") -> tuple[int, str]:
        body = None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Origin": WEB,
            "Referer": f"{WEB}/login.html",
        }
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            method = "POST"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=90) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def login(self, email: str, password: str) -> dict:
        self._req(f"{WEB}/login.html")
        url = f"{WEB}/ashx/login.ashx?komut=login"
        payload = {
            "user_code": email,
            "user_pass": password,
            "remember": "on",
        }
        st, txt = self._req(url, payload)
        sonuc = None
        tok = None
        try:
            j = json.loads(txt)
            if isinstance(j, list) and j:
                j0 = j[0] if isinstance(j[0], dict) else {}
                sonuc = j0.get("Sonuc") or j0.get("sonuc")
                tok = j0.get("token") or j0.get("evo_token")
            elif isinstance(j, dict):
                sonuc = j.get("Sonuc") or j.get("status")
                tok = j.get("token") or j.get("evo_token")
        except json.JSONDecodeError:
            j = None
        if tok:
            self.token = str(tok)
        return {
            "token_var": bool(self.token),
            "http": st,
            "sonuc": sonuc,
            "head": txt[:200].replace("\n", " "),
        }

    def guidejq(
        self,
        *,
        modul: str = "1051",
        kos: str,
        veri: str = "",
        full_text: str = "",
        pagenum: int = 0,
        pagesize: int = 100,
    ) -> Any:
        # Veri_Yukle JSON gövdesi (evo_grid)
        payload = {
            "filterscount": "0",
            "groupscount": "0",
            "pagenum": str(pagenum),
            "pagesize": str(pagesize),
            "recordstartindex": str(pagenum * pagesize),
            "recordendindex": str((pagenum + 1) * pagesize),
            "modul": modul,
            "grp": "",
            "kos": kos,
            "veri": veri,
            "export": "view",
            "Full_Text": full_text,
            "gnm": "jqxgrid_mod1051",
            "evo_token": self.token or "",
            "evo_server": "web.evobulut.com",
        }
        url = f"{WEB}/ashx/guidejq.ashx?evo_server=web.evobulut.com"
        st, txt = self._req(url, payload)
        try:
            return {"http": st, "json": json.loads(txt)}
        except json.JSONDecodeError:
            return {"http": st, "text": txt[:500]}


def main() -> None:
    rows = json.loads(LISTE49.read_text(encoding="utf-8"))["liste_49"]["kayitlar_oncelikli"]
    hedef = {r["kod"]: r for r in rows}
    creds = load_credentials()
    # Web login genelde e-posta; env kullanici_kodu e-posta olabilir
    email = creds.kullanici_kodu
    password = creds.sifre

    ws = WebSession()
    login_info = ws.login(email, password)
    print("login", login_info["token_var"], flush=True)

    kos_pasif = "pasif^x^15|barkod_goster^x^1|"
    kos_aktif = "pasif^x^14|barkod_goster^x^1|"
    bulunan: dict[str, dict] = {}
    sayfa_ozet = []

    if ws.token:
        # 1) Full_Text ile tek tek (önce yüksek tutar)
        for r in rows[:37]:  # pozitif öncelik sırası zaten
            kod = r["kod"]
            for kos in (kos_pasif,):
                resp = ws.guidejq(kos=kos, full_text=kod, pagesize=50)
                j = resp.get("json")
                rows_j = []
                total = None
                if isinstance(j, dict):
                    rows_j = j.get("Rows") or j.get("rows") or j.get("DATA") or []
                    total = j.get("TotalRows") or j.get("totalrecords") or j.get("Total")
                elif isinstance(j, list):
                    rows_j = j
                # match
                for row in rows_j or []:
                    if not isinstance(row, dict):
                        continue
                    # kolon adları değişken olabilir
                    blob = json.dumps(row, ensure_ascii=False)
                    if kod in blob:
                        # id/kod alanlarını yakala
                        sid = (
                            row.get("G.a_id")
                            or row.get("a_id")
                            or row.get("Id")
                            or row.get("id")
                        )
                        akod = row.get("G.a_kod") or row.get("a_kod") or row.get("Kodu")
                        bulunan[kod] = {
                            "kaynak_stok_id": str(sid) if sid is not None else None,
                            "a_kod": akod,
                            "satir": {k: row[k] for k in list(row)[:12]},
                            "kanit": f"guidejq.ashx kos={kos} Full_Text={kod}",
                            "kesin": bool(sid) and (str(akod).strip() == kod if akod else True),
                        }
                        break
                time.sleep(0.05)
                if kod in bulunan:
                    break
            if len(bulunan) and len(bulunan) % 5 == 0:
                print(f"bulunan={len(bulunan)} son={kod}", flush=True)

        # 2) pasif liste sayfa tarama (ilk 20 sayfa) — Full_Text boş
        for pagenum in range(0, 20):
            resp = ws.guidejq(kos=kos_pasif, full_text="", pagenum=pagenum, pagesize=100)
            j = resp.get("json")
            rows_j = []
            if isinstance(j, dict):
                rows_j = j.get("Rows") or j.get("rows") or j.get("DATA") or []
                total = j.get("TotalRows") or j.get("totalrecords")
            else:
                total = None
            sayfa_ozet.append(
                {
                    "pagenum": pagenum,
                    "http": resp.get("http"),
                    "n": len(rows_j) if isinstance(rows_j, list) else None,
                    "total": total,
                    "sample_keys": list(rows_j[0].keys())[:15] if rows_j else [],
                    "head": (resp.get("text") or json.dumps(j, ensure_ascii=False)[:200])
                    if not rows_j
                    else None,
                }
            )
            for row in rows_j or []:
                if not isinstance(row, dict):
                    continue
                akod = str(row.get("G.a_kod") or row.get("a_kod") or row.get("Kodu") or "").strip()
                if akod in hedef and akod not in bulunan:
                    sid = row.get("G.a_id") or row.get("a_id") or row.get("Id")
                    bulunan[akod] = {
                        "kaynak_stok_id": str(sid) if sid is not None else None,
                        "a_kod": akod,
                        "kanit": f"guidejq.ashx kos={kos_pasif} sayfa={pagenum} a_kod exact",
                        "kesin": True,
                        "satir": {k: row[k] for k in list(row)[:12]},
                    }
            if not rows_j:
                break
            time.sleep(0.05)
    else:
        sayfa_ozet.append({"login_basarisiz": True, "info": login_info})

    out = {
        "format": "d1-stok-49-guidejq-pasif-v1",
        "zaman": _now(),
        "yeniden_toplanmadi": {"stok_76_hareket": True, "kimlik_6": True},
        "k05": False,
        "yol": "web.evobulut.com ashx/guidejq.ashx (UI Stok Yönetimi Veri_Yukle)",
        "kos_pasif": kos_pasif,
        "login_token_var": bool(ws.token),
        "login_sonuc": {
            "http": login_info.get("http"),
            "sonuc": login_info.get("sonuc"),
            "head": (login_info.get("head") or "")[:120],
        },
        "bulunan": bulunan,
        "bulunan_adet": len(bulunan),
        "sayfa_ozet": sayfa_ozet[:5],
        "kalan": [r["kod"] for r in rows if r["kod"] not in bulunan],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha = _sha16(OUT)
    ozet = {
        "zaman": out["zaman"],
        "token": bool(ws.token),
        "bulunan": len(bulunan),
        "kalan": len(out["kalan"]),
        "kanit": str(OUT.relative_to(DNM)).replace("\\", "/"),
        "sha16": sha,
        "k05": False,
    }
    OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sha16(OZET)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
