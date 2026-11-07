# -*- coding: utf-8 -*-
"""49 kalan — yalnızca oturum kontrolü OK ise guidejq (a_caller=1051) + ashx SQL.

İsim benzerliği ile eşleştirme YOK. K05/mali/EXE yok. 76/6 yeniden yok.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path

from entegrasyon.evobulut_client import load_credentials

ROOT = Path(__file__).resolve().parents[2]
DNM = ROOT / "kurulum" / "dnm_d1_20260831"
KAYNAK = DNM / "kaynak"
LISTE49 = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DOGRULA.json"
OTURUM = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_OTURUM_KONTROL.json"
OUT = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_GUIDEJQ_DEVAM.json"
OZET = DNM / "STOK_49_GUIDEJQ_DEVAM_OZET.json"
WEB = "https://web.evobulut.com"
FIRMA = "42178"
KOS_PASIF = "pasif^x^15|barkod_goster^x^1|hareketsiz^x^1|"
KOS_PASIF_OZET = "pasif^x^15|barkod_goster^x^1|"


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
        self.firma: str | None = None

    def _req(self, url: str, data: dict | None = None) -> tuple[int, str]:
        body = None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Origin": WEB,
            "Referer": f"{WEB}/index.html#ajax/stok.html",
        }
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
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
        j = json.loads(txt)
        j0 = j[0]
        self.token = j0.get("token")
        self.firma = str(j0.get("firma") or "")
        return {
            "ok": str(j0.get("RES") or "").upper() == "OK" and self.firma == FIRMA and bool(self.token),
            "firma": self.firma,
            "http": st,
        }

    def stok_sql(self, stok_id: str) -> dict:
        st, txt = self._req(
            f"{WEB}/ashx/stok.ashx?evo_server=web.evobulut.com",
            {
                "komut": "SQL",
                "kosul": str(stok_id),
                "evo_token": self.token or "",
                "evo_server": "web.evobulut.com",
            },
        )
        j = json.loads(txt)
        if isinstance(j, list) and j and str(j[0].get("Sonuc") or "").upper() == "HATA":
            return {"ok": False, "hata": j[0].get("ERR")}
        row = (j.get("S") or [None])[0] if isinstance(j, dict) else None
        if not row:
            return {"ok": False, "hata": "S_bos", "head": txt[:200]}
        barkodlar = []
        for b in j.get("barkod") or []:
            barkodlar.append(
                {
                    "a_barkod_no": b.get("a_barkod_no"),
                    "a_brm_id": b.get("a_brm_id"),
                    "Brm_Adi": b.get("Brm_Adi"),
                    "a_carpan": b.get("a_carpan"),
                }
            )
        birimler = []
        for b in j.get("s1") or []:
            birimler.append(
                {
                    "a_brm_id": b.get("a_brm_id") or b.get("a_id"),
                    "adi": b.get("a_adi") or b.get("Brm_Adi") or b.get("adi"),
                    "a_carpan": b.get("a_carpan"),
                }
            )
        return {
            "ok": True,
            "a_id": str(row.get("a_id")),
            "a_kod": row.get("a_kod"),
            "a_adi": row.get("a_adi"),
            "a_pasif": row.get("a_pasif"),
            "barkodlar": barkodlar,
            "birimler": birimler,
            "http": st,
        }

    def guidejq(self, *, kos: str, full_text: str = "", veri: str = "", pagesize: int = 50) -> dict:
        payload = {
            "a_caller": "1051",
            "profil": "",
            "modul": "",
            "grp": "",
            "kos": kos,
            "veri": veri,
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
        st, txt = self._req(f"{WEB}/ashx/guidejq.ashx?evo_server=web.evobulut.com", payload)
        j = json.loads(txt)
        if not isinstance(j, list) or not j:
            return {"http": st, "ok": False, "hata": "yanit", "head": txt[:200]}
        rows = j[0].get("Rows") or []
        keys = list(rows[0].keys())[:15] if rows else []
        cari = any(str(k).startswith("R.") for k in keys)
        return {
            "http": st,
            "ok": True,
            "total": j[0].get("TotalRows"),
            "rows": rows,
            "keys": keys,
            "cari_grid": cari,
            "stok_grid": (not cari) and bool(rows or j[0].get("TotalRows") is not None),
        }


def _kod_esles(row: dict, kod: str) -> bool:
    for k, v in row.items():
        if str(v).strip() == kod and (
            "kod" in k.lower() or k.endswith("a_kod") or k in {"G.a_kod", "a_kod", "Kodu"}
        ):
            return True
    # barkod sütunu
    for k, v in row.items():
        if str(v).strip() == kod and "barkod" in k.lower():
            return True
    return False


def _row_id(row: dict) -> str | None:
    for k in ("G.a_id", "a_id", "Id", "id", "R.a_id"):
        if k in row and row[k] not in (None, ""):
            return str(row[k])
    return None


def main() -> None:
    # oturum dosyası taze olmalı — yeniden koş
    from tools.dnm_d1 import stok_oturum_kontrol as sok

    sok.main()
    ot = json.loads(OTURUM.read_text(encoding="utf-8"))
    api_ok = ot["oturum"]["api_ok"]
    # web_sql yeniden parse sonrası
    web_ok = (
        ot["web_login"].get("ok")
        and ot["web_stok_sql"].get("eslesme_ok")
        and str(ot["web_stok_sql"].get("a_id")) == ot["beklenen"]["kaynak_stok_id"]
        and str(ot["web_stok_sql"].get("a_kod") or "").strip() == ot["beklenen"]["a_kod"]
    )
    # oturum script güncellendi; web_ok alanı dosyada güncel
    web_ok = bool(ot["oturum"].get("web_ok"))
    tam = bool(ot["oturum"].get("tam_ok"))

    rows49 = json.loads(LISTE49.read_text(encoding="utf-8"))["liste_49"]["kayitlar_oncelikli"]

    if not tam:
        out = {
            "format": "d1-stok-49-guidejq-devam-v1",
            "zaman": _now(),
            "durduruldu": True,
            "neden": "Oturum kontrolü tam_ok değil; 49 boş sonuçları geçerli sayılmadı.",
            "oturum_ozet": ot["oturum"],
            "kalan_49": {"durum": "ERISIM_NEDENIYLE_BEKLIYOR", "adet": 49},
            "k05": False,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sha = _sha16(OUT)
        ozet = {"zaman": out["zaman"], "durduruldu": True, "sha16": sha, "k05": False}
        OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _sha16(OZET)
        print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
        return

    creds = load_credentials()
    ws = WebSession()
    login = ws.login(creds.kullanici_kodu, creds.sifre)
    # kontrol tekrarı
    ctrl = ws.stok_sql(ot["beklenen"]["kaynak_stok_id"])
    ctrl_ok = (
        login.get("ok")
        and ctrl.get("ok")
        and ctrl.get("a_id") == ot["beklenen"]["kaynak_stok_id"]
        and str(ctrl.get("a_kod") or "").strip() == ot["beklenen"]["a_kod"]
    )
    if not ctrl_ok:
        out = {
            "format": "d1-stok-49-guidejq-devam-v1",
            "zaman": _now(),
            "durduruldu": True,
            "neden": "Yenilenen web oturumunda kontrol stok_id eşleşmedi",
            "login": login,
            "ctrl": ctrl,
            "kalan_49": {"durum": "ERISIM_NEDENIYLE_BEKLIYOR", "adet": 49},
            "k05": False,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sha = _sha16(OUT)
        OZET.write_text(
            json.dumps({"zaman": out["zaman"], "durduruldu": True, "sha16": sha, "k05": False}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        _sha16(OZET)
        print("CTRL FAIL", flush=True)
        return

    # smoke: bilinen kod Full_Text guidejq
    smoke = ws.guidejq(kos=KOS_PASIF_OZET, full_text=ot["beklenen"]["a_kod"])
    smoke_hit = False
    if smoke.get("ok") and not smoke.get("cari_grid"):
        for r in smoke.get("rows") or []:
            if _kod_esles(r, ot["beklenen"]["a_kod"]) or _row_id(r) == ot["beklenen"]["kaynak_stok_id"]:
                smoke_hit = True
                break

    baglanan = []
    arama_log = []
    # veri alanı: Kodu Eşit — tip alan adı UI'da G.a_kod^Eşit^kod^
    # kosul_listesi_veri format: a^k^d1^d2^tip|
    # bilinmeyen tip için Full_Text exact + SQL doğrulama kullan

    for r in rows49:
        kod = r["kod"]
        hit = None
        for kos in (KOS_PASIF, KOS_PASIF_OZET):
            # 1) Full_Text = kod
            g = ws.guidejq(kos=kos, full_text=kod)
            if g.get("cari_grid"):
                arama_log.append({"kod": kod, "kos": kos, "yol": "Full_Text", "cari_grid": True})
                continue
            for row in g.get("rows") or []:
                if _kod_esles(row, kod):
                    sid = _row_id(row)
                    hit = {
                        "excel_kod": kod,
                        "kaynak_stok_id": sid,
                        "guide_row": {k: row[k] for k in list(row)[:10]},
                        "kanit_guidejq": f"guidejq a_caller=1051 kos={kos} Full_Text exact kod",
                    }
                    break
            if hit:
                break
            # 2) veri filtresi Kodu eşit (deneme)
            veri = f"G.a_kod^=^{kod}^^s|"
            g2 = ws.guidejq(kos=kos, full_text="", veri=veri)
            if not g2.get("cari_grid"):
                for row in g2.get("rows") or []:
                    if _kod_esles(row, kod):
                        sid = _row_id(row)
                        hit = {
                            "excel_kod": kod,
                            "kaynak_stok_id": sid,
                            "guide_row": {k: row[k] for k in list(row)[:10]},
                            "kanit_guidejq": f"guidejq a_caller=1051 kos={kos} veri G.a_kod=exact",
                        }
                        break
            if hit:
                break
            time.sleep(0.04)

        if hit and hit.get("kaynak_stok_id"):
            sql = ws.stok_sql(hit["kaynak_stok_id"])
            # kesin: sql a_kod == excel kod VEYA barkod listesinde excel kod
            barkod_hit = any(str(b.get("a_barkod_no") or "").strip() == kod for b in sql.get("barkodlar") or [])
            kod_hit = str(sql.get("a_kod") or "").strip() == kod
            if sql.get("ok") and (kod_hit or barkod_hit):
                hit["sql"] = {
                    "a_id": sql.get("a_id"),
                    "a_kod": sql.get("a_kod"),
                    "a_adi": sql.get("a_adi"),
                    "a_pasif": sql.get("a_pasif"),
                    "barkod_eslesme": barkod_hit,
                    "kod_eslesme": kod_hit,
                    "barkodlar": sql.get("barkodlar"),
                    "birimler": sql.get("birimler"),
                }
                hit["kesin"] = True
                hit["kanit"] = (
                    hit["kanit_guidejq"]
                    + (" + ashx/stok SQL a_kod exact" if kod_hit else " + ashx/stok SQL barkod exact")
                )
                baglanan.append(hit)
            else:
                arama_log.append(
                    {
                        "kod": kod,
                        "guide_id": hit.get("kaynak_stok_id"),
                        "sql_ok": sql.get("ok"),
                        "red": "sql_kod_barkod_eslesmedi",
                        "sql_kod": sql.get("a_kod"),
                    }
                )
        else:
            arama_log.append({"kod": kod, "hit": False})

        if len(baglanan) and len(baglanan) % 3 == 0:
            print(f"baglanan={len(baglanan)}", flush=True)

    kalan = [r["kod"] for r in rows49 if r["kod"] not in {b["excel_kod"] for b in baglanan}]
    out = {
        "format": "d1-stok-49-guidejq-devam-v1",
        "zaman": _now(),
        "durduruldu": False,
        "oturum_kontrol": {
            "api_ok": api_ok,
            "web_ok": web_ok,
            "tam_ok": tam,
            "kontrol_stok_id": ot["beklenen"]["kaynak_stok_id"],
            "kontrol_kod": ot["beklenen"]["a_kod"],
            "guidejq_smoke_hit": smoke_hit,
            "guidejq_smoke": {
                "total": smoke.get("total"),
                "n": len(smoke.get("rows") or []),
                "cari_grid": smoke.get("cari_grid"),
                "keys": smoke.get("keys"),
            },
        },
        "isim_benzerligi_kullanilmadi": True,
        "kos": [KOS_PASIF, KOS_PASIF_OZET],
        "baglanan": baglanan,
        "baglanan_adet": len(baglanan),
        "kalan_adet": len(kalan),
        "kalan_kodlar": kalan,
        "arama_log_ornek": arama_log[:15],
        "arama_log_adet": len(arama_log),
        "k05": False,
        "yeniden_toplanmadi_76_ve_6": True,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha = _sha16(OUT)
    ozet = {
        "zaman": out["zaman"],
        "tam_ok": tam,
        "smoke_hit": smoke_hit,
        "baglanan": len(baglanan),
        "kalan": len(kalan),
        "kanit": str(OUT.relative_to(DNM)).replace("\\", "/"),
        "sha16": sha,
        "k05": False,
    }
    OZET.write_text(json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sha16(OZET)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
