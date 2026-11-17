"""EvoBulut REST istemcisi — kimlik bilgisi olmadan çağrı yapılmaz.

Dokümantasyon: https://dev.evobulut.com
Login: POST /index/base/  cmd=euas
Cari liste: POST /cari/base/  cmd=jq_list  (sayfa başına ~30 kayıt)
  → satır `text` alanında güncel bakiye: "… ---- Bakiye : N (B|A)"
Cari detay: POST /cari/base/  cmd=sql  a_id=…
Hesap ekstresi: POST /Musteri/base/  cmd=finans_jq_listesi  (max 1 yıl aralık)
Stok liste: POST /stok/base/  cmd=jq_list  (sayfa başına ~30 kayıt)
  → satırda güncel miktar: a_kalan, a_giren, a_cikan
Stok detay: POST /stok/base/  cmd=sql  a_stok_id=…
Stok hareket: POST /StokHareket/base/  cmd=list  (stok_id + tarih aralığı zorunlu;
  ayrı 'stok giriş fişi' master listesi yok)
Alış fatura listesi: POST /fatura/base/  cmd=jq_list  tur=30  (a_gc=1)
Alış fatura detay: POST /fatura/base/  cmd=sql  sql_id=…  → veri[0].Ana / Detay
Satış/iade/fiş: aynı uç, tur=31|32|33|34|35
Sipariş: POST /Siparis/base/  cmd=jq_list a_tur=50|51; cmd=sql a_id=…
İrsaliye: POST /irsaliye/base/  cmd=jq_list a_tur=70|71; cmd=sql a_id=…
Kasa: POST /KasaHareketleri/base/  cmd=kasa_listesi|jq_list|sql
Banka: POST /BankHareketleri/base/  cmd=banka_listesi|jq_list|sql
Gelir/Gider: POST /GelirGider/base/  cmd=jq_list|sql
  (a_tur_id 40=Gider, 41=Gelir; OpenAPI'de Cari Virman REST yok)
Gelen e-Fatura: POST /FaturaUbl/base/  cmd=jq_list|sql
Cari export: POST /CariExport/base/  cmd=export
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


DEFAULT_BASE = "https://ws.evobulut.com/api"
WEB_BASE = "https://web.evobulut.com"
CONFIG_PATH = Path(__file__).resolve().parent / "evobulut.env"

# Stok Yönetimi stokjq.ashx — doğrulanmış aktif/pasif kos (UI checkbox)
STOKJQ_KOS_AKTIF = "pasif^x^14|barkod_goster^x^1|"
STOKJQ_KOS_PASIF = "pasif^x^15|barkod_goster^x^1|"
STOKJQ_CALLER = "1051"


class EvobulutConfigError(RuntimeError):
    """Kimlik bilgisi veya yapılandırma eksik."""


class EvobulutApiError(RuntimeError):
    """API yanıtı başarısız veya beklenmeyen format."""


@dataclass(frozen=True)
class EvobulutCredentials:
    kullanici_kodu: str
    sifre: str
    app: str = "muhasebe_programi"
    base_url: str = DEFAULT_BASE


def resolve_config_path(*, for_write: bool = False, path: Path | None = None) -> Path:
    """Kaynak: entegrasyon/evobulut.env; EXE: AppData/.../evobulut.env."""
    if path is not None:
        return path
    adaylar: list[Path] = []
    if getattr(sys, "frozen", False):
        try:
            from database.database import DB_DIR

            adaylar.append(DB_DIR / "evobulut.env")
        except Exception:  # noqa: BLE001
            pass
    adaylar.append(CONFIG_PATH)
    if for_write:
        return adaylar[0]
    for yol in adaylar:
        if yol.is_file():
            return yol
    return adaylar[0]


def _env_oku(yol: Path) -> dict[str, str]:
    degerler: dict[str, str] = {}
    if not yol.is_file():
        return degerler
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        degerler[anahtar.strip()] = deger.strip().strip('"').strip("'")
    return degerler


def peek_credentials(path: Path | None = None) -> dict[str, str]:
    """Dosyadan alanları okur (eksik olsa da). Şifre dahil — yalnız UI ön doldurma."""
    yol = resolve_config_path(path=path)
    d = _env_oku(yol)
    return {
        "kullanici_kodu": d.get("EVOBULUT_KULLANICI_KODU", "").strip(),
        "sifre": d.get("EVOBULUT_SIFRE", "").strip(),
        "app": d.get("EVOBULUT_APP", "muhasebe_programi").strip() or "muhasebe_programi",
        "base_url": d.get("EVOBULUT_BASE_URL", DEFAULT_BASE).strip() or DEFAULT_BASE,
        "path": str(yol),
    }


def save_credentials(
    creds: EvobulutCredentials,
    path: Path | None = None,
) -> Path:
    """Kimliği evobulut.env dosyasına yazar (EXE'de AppData)."""
    yol = resolve_config_path(for_write=True, path=path)
    yol.parent.mkdir(parents=True, exist_ok=True)
    metin = (
        "# EvoBulut API kimlik bilgileri — git'e eklemeyin.\n"
        f"EVOBULUT_BASE_URL={creds.base_url.rstrip('/')}\n"
        f"EVOBULUT_KULLANICI_KODU={creds.kullanici_kodu}\n"
        f"EVOBULUT_SIFRE={creds.sifre}\n"
        f"EVOBULUT_APP={creds.app}\n"
    )
    yol.write_text(metin, encoding="utf-8")
    return yol


def load_credentials(path: Path | None = None) -> EvobulutCredentials:
    """evobulut.env dosyasından okur. Boş alan varsa EvobulutConfigError."""
    yol = resolve_config_path(path=path)
    if not yol.is_file():
        raise EvobulutConfigError(
            f"EvoBulut yapılandırması yok: {yol.name}\n"
            f"Şablon: entegrasyon/evobulut_config.example.env → evobulut.env\n"
            "veya uygulamada EvoBulut şifre ekranını kullanın."
        )
    degerler = _env_oku(yol)
    kullanici = degerler.get("EVOBULUT_KULLANICI_KODU", "").strip()
    sifre = degerler.get("EVOBULUT_SIFRE", "").strip()
    app = degerler.get("EVOBULUT_APP", "muhasebe_programi").strip() or "muhasebe_programi"
    base = degerler.get("EVOBULUT_BASE_URL", DEFAULT_BASE).strip() or DEFAULT_BASE
    if not kullanici or not sifre:
        raise EvobulutConfigError(
            "EVOBULUT_KULLANICI_KODU ve EVOBULUT_SIFRE doldurulmalı "
            f"({yol.name}) veya şifre ekranını kullanın."
        )
    return EvobulutCredentials(
        kullanici_kodu=kullanici,
        sifre=sifre,
        app=app,
        base_url=base.rstrip("/"),
    )


def credentials_available(path: Path | None = None) -> bool:
    try:
        load_credentials(path)
        return True
    except EvobulutConfigError:
        return False


class EvobulutClient:
    def __init__(self, creds: EvobulutCredentials):
        self.creds = creds
        self.uid: str | None = None
        self._web_token: str | None = None
        self._web_firma: str | None = None
        self._web_opener: Any = None
        self._son_stok_cek_meta: dict[str, Any] = {}

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.creds.base_url}/{path.lstrip('/')}"
        if not url.endswith("/"):
            url += "/"
        data = json.dumps(payload).encode("utf-8")
        # Cloudflare Error 1010: default Python UA banned; browser-like headers gerekli.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Origin": "https://ws.evobulut.com",
            "Referer": "https://ws.evobulut.com/",
        }
        if self.uid:
            headers["X-ClientId"] = self.uid
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                ham = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            govde = exc.read().decode("utf-8", errors="replace")
            raise EvobulutApiError(f"HTTP {exc.code}: {govde[:400]}") from exc
        except urllib.error.URLError as exc:
            raise EvobulutApiError(f"Bağlantı hatası: {exc.reason}") from exc
        try:
            return json.loads(ham) if ham else {}
        except json.JSONDecodeError as exc:
            raise EvobulutApiError(f"JSON değil: {ham[:200]}") from exc

    def login(self) -> str:
        yanit = self._post(
            "index/base/",
            {
                "cmd": "euas",
                "p1": self.creds.kullanici_kodu,
                "p2": self.creds.sifre,
                "app": self.creds.app,
            },
        )
        uid = _uid_bul(yanit)
        if not uid:
            raise EvobulutApiError(
                "Login başarısız veya UID alınamadı. "
                "Kullanıcı kodu / şifre / app adını kontrol edin."
            )
        self.uid = uid
        return uid

    def cari_liste_sayfa(self, sayfa: int = 0, ara: str = "") -> tuple[list[dict], int]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "cari/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "ara": ara or "",
            },
        )
        satirlar = _ana_listesi(yanit)
        toplam = _sayfa_adet(yanit)
        return satirlar, toplam

    def tum_carileri_cek(self, ara: str = "", max_sayfa: int = 500) -> list[dict]:
        """Sayfalı cari listesini birleştirir (sayfa başına ~30)."""
        return self._tum_listeyi_cek(self.cari_liste_sayfa, ara=ara, max_sayfa=max_sayfa)

    def stok_liste_sayfa(self, sayfa: int = 0, ara: str = "") -> tuple[list[dict], int]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "stok/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "ara": ara or "",
            },
        )
        return _ana_listesi(yanit), _sayfa_adet(yanit)

    def tum_stoklari_cek(self, ara: str = "", max_sayfa: int = 2000) -> list[dict]:
        """Aktif + pasif stok listesi (stokjq ayrı sorgular, a_id tekilleştirme).

        Eski jq_list yalnız aktif kartları döndürüyordu; pasif envanter satırları
        kayboluyordu. Kalıcı toplayıcı doğrulanmış kos ile iki geçiş yapar.
        `ara` doluysa geriye uyum için jq_list ara kullanılır (tek filtre).
        """
        if ara:
            return self._tum_listeyi_cek(self.stok_liste_sayfa, ara=ara, max_sayfa=max_sayfa)
        return self.tum_stoklari_cek_aktif_pasif(max_sayfa_her=max_sayfa)

    def tum_stoklari_cek_aktif_pasif(
        self, *, max_sayfa_her: int = 2000, pagesize: int = 100
    ) -> list[dict]:
        """Aktif (pasif^x^14) ve pasif (pasif^x^15) stokjq listelerini birleştirir."""
        self.web_login()
        by_id: dict[str, dict] = {}
        meta_sayac = {"aktif": 0, "pasif": 0, "aktif_total": None, "pasif_total": None}
        for etiket, kos in (("aktif", STOKJQ_KOS_AKTIF), ("pasif", STOKJQ_KOS_PASIF)):
            sayfa = 0
            while sayfa < max_sayfa_her:
                satirlar, toplam = self.stokjq_liste_sayfa(
                    sayfa=sayfa, kos=kos, pagesize=pagesize
                )
                if meta_sayac[f"{etiket}_total"] is None:
                    meta_sayac[f"{etiket}_total"] = toplam
                if not satirlar:
                    break
                for s in satirlar:
                    sid = str(s.get("a_id") or "").strip()
                    if not sid:
                        continue
                    if sid not in by_id:
                        by_id[sid] = s
                        meta_sayac[etiket] += 1
                    else:
                        # Tekilleştir: pasif/aktif çakışmasında mevcut kalır; alan tamamla
                        eski = by_id[sid]
                        for k, v in s.items():
                            if eski.get(k) in (None, "") and v not in (None, ""):
                                eski[k] = v
                if toplam is not None and (sayfa + 1) * pagesize >= int(toplam):
                    break
                if len(satirlar) < pagesize:
                    break
                sayfa += 1
        out = list(by_id.values())
        # İzlenebilir meta (liste tüketici yok sayar)
        out.sort(key=lambda r: int(str(r.get("a_id") or "0") or 0))
        self._son_stok_cek_meta = {
            "kaynak": "stokjq.ashx a_caller=1051",
            "kos_aktif": STOKJQ_KOS_AKTIF,
            "kos_pasif": STOKJQ_KOS_PASIF,
            "aktif_unique": meta_sayac["aktif"],
            "pasif_unique": meta_sayac["pasif"],
            "aktif_total_rows": meta_sayac["aktif_total"],
            "pasif_total_rows": meta_sayac["pasif_total"],
            "tekil_adet": len(out),
        }
        return out

    def web_login(self) -> str:
        """web.evobulut.com ashx oturumu (stokjq / stok.ashx). API UID yerine geçmez."""
        if self._web_token and self._web_opener:
            return self._web_token
        cj = CookieJar()
        self._web_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self._web_req(f"{WEB_BASE}/login.html")
        st, txt = self._web_req(
            f"{WEB_BASE}/ashx/login.ashx?komut=login",
            {
                "user_code": self.creds.kullanici_kodu,
                "user_pass": self.creds.sifre,
                "remember": "on",
            },
        )
        try:
            j = json.loads(txt)
        except json.JSONDecodeError as exc:
            raise EvobulutApiError(f"Web login JSON değil: {txt[:160]}") from exc
        if not isinstance(j, list) or not j:
            raise EvobulutApiError(f"Web login beklenmeyen yanıt HTTP {st}")
        j0 = j[0] if isinstance(j[0], dict) else {}
        if str(j0.get("RES") or "").upper() != "OK" or not j0.get("token"):
            raise EvobulutApiError(
                f"Web login başarısız RES={j0.get('RES')!r} HTTP={st}"
            )
        self._web_token = str(j0["token"])
        self._web_firma = str(j0.get("firma") or "")
        return self._web_token

    def _web_req(self, url: str, data: dict | None = None) -> tuple[int, str]:
        if self._web_opener is None:
            self.web_login()
        body = None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Origin": WEB_BASE,
            "Referer": f"{WEB_BASE}/index.html",
        }
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        req = urllib.request.Request(
            url, data=body, headers=headers, method="POST" if body else "GET"
        )
        try:
            with self._web_opener.open(req, timeout=90) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def stokjq_liste_sayfa(
        self,
        *,
        sayfa: int = 0,
        kos: str = STOKJQ_KOS_AKTIF,
        pagesize: int = 100,
        full_text: str = "",
    ) -> tuple[list[dict], int]:
        """UI stokjq.ashx sayfası → API benzeri stok satırları."""
        self.web_login()
        payload = {
            "a_caller": STOKJQ_CALLER,
            "profil": "",
            "modul": "",
            "grp": "",
            "kos": kos,
            "veri": "",
            "export": "view",
            "groupscount": "0",
            "Full_Text": full_text or "",
            "gnm": "jqxgrid_mod1051",
            "pagenum": str(sayfa),
            "pagesize": str(pagesize),
            "recordstartindex": str(sayfa * pagesize),
            "recordendindex": str((sayfa + 1) * pagesize),
            "filterscount": "0",
            "evo_token": self._web_token or "",
            "evo_server": "web.evobulut.com",
        }
        st, txt = self._web_req(
            f"{WEB_BASE}/ashx/stokjq.ashx?depo_izni=0&evo_server=web.evobulut.com",
            payload,
        )
        try:
            j = json.loads(txt)
        except json.JSONDecodeError as exc:
            raise EvobulutApiError(f"stokjq JSON değil HTTP {st}: {txt[:160]}") from exc
        if not isinstance(j, list) or not j:
            return [], 0
        wrap = j[0] if isinstance(j[0], dict) else {}
        rows = wrap.get("Rows") or []
        try:
            toplam = int(str(wrap.get("TotalRows") or "0"))
        except ValueError:
            toplam = 0
        mapped = [_stokjq_satir_map(r, kos=kos) for r in rows if isinstance(r, dict)]
        return mapped, toplam

    def stok_detay_web(self, stok_id: str | int) -> dict:
        """ashx/stok.ashx SQL — pasif kartlar dahil (API sql pasifte boş kalabilir)."""
        self.web_login()
        st, txt = self._web_req(
            f"{WEB_BASE}/ashx/stok.ashx?evo_server=web.evobulut.com",
            {
                "komut": "SQL",
                "kosul": str(stok_id),
                "evo_token": self._web_token or "",
                "evo_server": "web.evobulut.com",
            },
        )
        try:
            j = json.loads(txt)
        except json.JSONDecodeError as exc:
            raise EvobulutApiError(f"stok.ashx SQL JSON değil: {txt[:160]}") from exc
        if isinstance(j, list) and j and str(j[0].get("Sonuc") or "").upper() == "HATA":
            raise EvobulutApiError(f"stok.ashx SQL HATA: {j[0].get('ERR')}")
        if not isinstance(j, dict):
            return {}
        return j

    def stok_detay(self, stok_id: str | int) -> dict:
        """cmd=sql ile stok kartı detayı (barkod, birimler vb.)."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "stok/base/",
            {
                "cmd": "sql",
                "UID": self.uid,
                "a_stok_id": str(stok_id),
                "grupgetir": "1",
                "a_barkod": "",
            },
        )
        if str(yanit.get("status") or "").upper() not in {"OK", "1", ""}:
            # Bazı yanıtlar status=OK; boş/ERR ise yine veri dönebilir
            pass
        return yanit.get("veri") or yanit.get("Veri") or {}

    def stok_kart_turleri(self) -> list[dict]:
        if not self.uid:
            self.login()
        yanit = self._post("stok/base/", {"cmd": "kart_turu", "UID": self.uid})
        return _ana_listesi(yanit)

    def stok_hareketleri(
        self,
        stok_id: str | int,
        *,
        bas_tar: str = "01.01.2020",
        bit_tar: str = "31.12.2099",
        depo: str = "0",
    ) -> list[dict]:
        """Tek stok kartının hareketleri (gir_miktar / cik_miktar, belge_tur).

        Master stok giriş fişi listesi API'de yok; bu uç nokta stok_id ister.
        """
        if not self.uid:
            self.login()
        yanit = self._post(
            "StokHareket/base/",
            {
                "cmd": "list",
                "UID": self.uid,
                "stok_id": str(stok_id),
                "depo": str(depo),
                "birim": "0",
                "carpan": "1",
                "birim_adi": "",
                "bas_tar": bas_tar,
                "bit_tar": bit_tar,
                "dovizli_goster": "0",
            },
        )
        return _ana_listesi(yanit)

    def fatura_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        tur: str = "30",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
    ) -> tuple[list[dict], int]:
        """Fatura listesi. tur=30 alış, tur=31 satış (OpenAPI)."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "fatura/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "ara": ara or "",
                "tur": str(tur),
                "a_onay": "",
                "a_cari_id": "",
                "a_tarih_bas": tarih_bas or "",
                "a_tarih_son": tarih_son or "",
                "a_stok_id": "",
                "a_stok_ack": "",
            },
        )
        return _ana_listesi(yanit), _fatura_adet(yanit)

    def tum_faturalari_cek(
        self,
        *,
        tur: str = "30",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
        max_sayfa: int = 2000,
        progress=None,
    ) -> list[dict]:
        """Fatura listesi (tur parametreli), sayfa başına ~30."""
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.fatura_liste_sayfa(
                sayfa,
                tur=str(tur),
                ara=ara,
                tarih_bas=tarih_bas,
                tarih_son=tarih_son,
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if progress and (sayfa % 10 == 0 or (toplam and len(tum) >= toplam)):
                hedef = toplam if toplam else "?"
                progress(f"  liste sayfa {sayfa} — {len(tum)}/{hedef}")
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def tum_alis_faturalari_cek(
        self,
        *,
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
        max_sayfa: int = 500,
    ) -> list[dict]:
        """Alış faturaları (tur=30), sayfa başına ~30."""
        return self.tum_faturalari_cek(
            tur="30",
            ara=ara,
            tarih_bas=tarih_bas,
            tarih_son=tarih_son,
            max_sayfa=max_sayfa,
        )

    def fatura_detay(self, fatura_id: str | int) -> dict:
        """Fatura başlık + satırlar. Döner: {Ana: dict, Detay: list}.

        Boş Detay ara sıra API yanıtında geliyor; kısa yeniden deneme yapılır.
        """
        import time

        if not self.uid:
            self.login()
        son: dict = {"Ana": {}, "Detay": []}
        for deneme in range(4):
            if deneme == 2:
                # Boş Detay sürerse oturumu yenile (UID/oturum sönmesi)
                try:
                    self.login()
                except Exception:
                    pass
            yanit = self._post(
                "fatura/base/",
                {
                    "cmd": "sql",
                    "UID": self.uid,
                    "sql_id": str(fatura_id),
                },
            )
            veri = yanit.get("veri") or yanit.get("Veri")
            blok = None
            if isinstance(veri, list) and veri:
                blok = veri[0] if isinstance(veri[0], dict) else None
            elif isinstance(veri, dict):
                blok = veri
            if not isinstance(blok, dict):
                if deneme < 3:
                    time.sleep(0.7 * (deneme + 1))
                    continue
                raise EvobulutApiError(f"Fatura detayı alınamadı (id={fatura_id}).")
            ana = blok.get("Ana") or []
            detay = blok.get("Detay") or []
            ana0 = ana[0] if isinstance(ana, list) and ana else {}
            if isinstance(ana, dict):
                ana0 = ana
            detay_list = [x for x in detay if isinstance(x, dict)] if isinstance(detay, list) else []
            son = {
                "Ana": ana0 if isinstance(ana0, dict) else {},
                "Detay": detay_list,
            }
            if detay_list:
                return son
            if deneme < 3:
                time.sleep(0.7 * (deneme + 1))
        return son

    def siparis_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        a_tur: str = "50",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
    ) -> tuple[list[dict], int]:
        """Sipariş listesi. a_tur=50 alınan, a_tur=51 verilen."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "Siparis/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "a_tur": str(a_tur),
                "a_onay": "",
                "a_cari_id": "",
                "a_tarih_bas": tarih_bas or "",
                "a_tarih_son": tarih_son or "",
                "a_stok_id": "",
                "ara": ara or "",
                "acik_siparisler": "0",
                "kismi_siparisler": "0",
            },
        )
        return _ana_listesi(yanit), _fatura_adet(yanit) or _sayfa_adet(yanit)

    def tum_siparisleri_cek(
        self,
        *,
        a_tur: str = "50",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
        max_sayfa: int = 500,
    ) -> list[dict]:
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.siparis_liste_sayfa(
                sayfa,
                a_tur=a_tur,
                ara=ara,
                tarih_bas=tarih_bas,
                tarih_son=tarih_son,
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def siparis_detay(self, siparis_id: str | int) -> dict:
        """Sipariş başlık + satırlar. Döner: {Ana: dict, Detay: list}."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "Siparis/base/",
            {"cmd": "sql", "UID": self.uid, "a_id": str(siparis_id)},
        )
        return _ana_detay_blok(yanit, f"Sipariş detayı alınamadı (id={siparis_id}).")

    def irsaliye_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        a_tur: str = "70",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
    ) -> tuple[list[dict], int]:
        """İrsaliye listesi. a_tur=70 alış, a_tur=71 satış."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "irsaliye/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "a_tur": str(a_tur),
                "a_onay": "-1",
                "a_depo_id": "0",
                "a_cari_id": "0",
                "a_tarih_bas": tarih_bas or "",
                "a_tarih_son": tarih_son or "",
                "ara": ara or "",
            },
        )
        return _ana_listesi(yanit), _fatura_adet(yanit) or _sayfa_adet(yanit)

    def tum_irsaliyeleri_cek(
        self,
        *,
        a_tur: str = "70",
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
        max_sayfa: int = 500,
    ) -> list[dict]:
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.irsaliye_liste_sayfa(
                sayfa,
                a_tur=a_tur,
                ara=ara,
                tarih_bas=tarih_bas,
                tarih_son=tarih_son,
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def irsaliye_detay(self, irsaliye_id: str | int) -> dict:
        """İrsaliye başlık + satırlar. Döner: {Ana: dict, Detay: list}."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "irsaliye/base/",
            {"cmd": "sql", "UID": self.uid, "a_id": str(irsaliye_id)},
        )
        return _ana_detay_blok(yanit, f"İrsaliye detayı alınamadı (id={irsaliye_id}).")

    def kasa_kart_listesi(self, ara: str = "") -> list[dict]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "KasaHareketleri/base/",
            {"cmd": "kasa_listesi", "UID": self.uid, "ara": ara or ""},
        )
        return _ana_listesi(yanit)

    def kasa_islem_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        ara: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        kasa_id: str = "",
        cari_id: str = "",
    ) -> tuple[list[dict], int]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "KasaHareketleri/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "cari_id": cari_id or "",
                "bas_tar": bas_tar or "",
                "son_tar": son_tar or "",
                "kasa_id": kasa_id or "",
                "ara": ara or "",
            },
        )
        return _ana_listesi(yanit), _fatura_adet(yanit) or _sayfa_adet(yanit)

    def tum_kasa_islemlerini_cek(
        self,
        *,
        ara: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        kasa_id: str = "",
        max_sayfa: int = 2000,
    ) -> list[dict]:
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.kasa_islem_liste_sayfa(
                sayfa,
                ara=ara,
                bas_tar=bas_tar,
                son_tar=son_tar,
                kasa_id=kasa_id,
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def kasa_islem_detay(self, islem_id: str | int) -> dict:
        if not self.uid:
            self.login()
        yanit = self._post(
            "KasaHareketleri/base/",
            {"cmd": "sql", "UID": self.uid, "a_id": str(islem_id)},
        )
        return _ana_detay_blok(yanit, f"Kasa işlem detayı alınamadı (id={islem_id}).")

    def banka_kart_listesi(self, ara: str = "") -> list[dict]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "BankHareketleri/base/",
            {"cmd": "banka_listesi", "UID": self.uid, "ara": ara or ""},
        )
        return _ana_listesi(yanit)

    def banka_islem_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        ara: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        cari_id: str = "",
    ) -> tuple[list[dict], int]:
        if not self.uid:
            self.login()
        yanit = self._post(
            "BankHareketleri/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "cari_id": cari_id or "",
                "bas_tar": bas_tar or " ",
                "vbas_tar": " ",
                "son_tar": son_tar or "",
                "vson_tar": "",
                "kasa_id": "",
                "ara": ara or "",
                "pos_bloke": "",
            },
        )
        return _ana_listesi(yanit), _fatura_adet(yanit) or _sayfa_adet(yanit)

    def tum_banka_islemlerini_cek(
        self,
        *,
        ara: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        max_sayfa: int = 2000,
    ) -> list[dict]:
        """Tüm banka işlemleri. Tarih boşsa 2015→bugün yıllık dilimlerle çeker."""
        if not self.uid:
            self.login()
        if bas_tar or son_tar:
            return self._banka_islem_sayfala(
                ara=ara, bas_tar=bas_tar, son_tar=son_tar, max_sayfa=max_sayfa
            )
        from datetime import date

        bugun = date.today()
        tum: list[dict] = []
        gorulen: set[str] = set()
        for yil in range(2015, bugun.year + 1):
            bas = f"01.01.{yil}"
            son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
            dilim = self._banka_islem_sayfala(
                ara=ara, bas_tar=bas, son_tar=son, max_sayfa=max_sayfa
            )
            for s in dilim:
                aid = str(s.get("G.a_id") or s.get("a_id") or "").strip()
                if aid and aid in gorulen:
                    continue
                if aid:
                    gorulen.add(aid)
                tum.append(s)
        if not tum:
            # Yıllık dilim boşsa tek sefer boş filtre dene
            tum = self._banka_islem_sayfala(
                ara=ara, bas_tar="", son_tar="", max_sayfa=max_sayfa
            )
        return tum

    def _banka_islem_sayfala(
        self,
        *,
        ara: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        max_sayfa: int = 2000,
    ) -> list[dict]:
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.banka_islem_liste_sayfa(
                sayfa, ara=ara, bas_tar=bas_tar, son_tar=son_tar
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def banka_islem_detay(self, islem_id: str | int) -> dict:
        if not self.uid:
            self.login()
        yanit = self._post(
            "BankHareketleri/base/",
            {"cmd": "sql", "UID": self.uid, "a_id": str(islem_id)},
        )
        return _ana_detay_blok(yanit, f"Banka işlem detayı alınamadı (id={islem_id}).")

    def gelir_gider_liste_sayfa(
        self,
        sayfa: int = 0,
        *,
        ara: str = "",
        cari_id: str = "",
        bas_tar: str = "",
        son_tar: str = "",
    ) -> tuple[list[dict], int]:
        """Gelir/Gider listesi. tur: 40=Gider, 41=Gelir (FIN_TUR.a_adi)."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "GelirGider/base/",
            {
                "cmd": "jq_list",
                "UID": self.uid,
                "sayfa": str(sayfa),
                "cari_id": cari_id or "",
                "bas_tar": bas_tar or "",
                "son_tar": son_tar or "",
                "ara": ara or "",
            },
        )
        satirlar = _ana_listesi(yanit)
        # sayfa alanı bazen toplam kayıt sayısı (ör. "562")
        adet = _fatura_adet(yanit) or _sayfa_adet(yanit)
        veri = yanit.get("veri") or yanit.get("Veri") or {}
        if adet <= 0 and isinstance(veri, dict):
            ham = str(veri.get("sayfa") or "").strip()
            if ham.isdigit():
                adet = int(ham)
        return satirlar, adet

    def tum_gelir_giderleri_cek(
        self,
        *,
        ara: str = "",
        cari_id: str = "",
        bas_tar: str = "",
        son_tar: str = "",
        max_sayfa: int = 2000,
    ) -> list[dict]:
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.gelir_gider_liste_sayfa(
                sayfa,
                ara=ara,
                cari_id=cari_id,
                bas_tar=bas_tar,
                son_tar=son_tar,
            )
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum

    def gelir_gider_detay(self, kayit_id: str | int) -> dict:
        """Gelir/Gider detayı. Döner: {Ana: dict, OdemeBilgiler: list}."""
        if not self.uid:
            self.login()
        yanit = self._post(
            "GelirGider/base/",
            {"cmd": "sql", "UID": self.uid, "a_id": str(kayit_id)},
        )
        if str(yanit.get("status") or "").upper() not in {"OK", "1", ""}:
            raise EvobulutApiError(f"Gelir/Gider detayı alınamadı (id={kayit_id}).")
        veri = yanit.get("veri") or yanit.get("Veri") or {}
        if not isinstance(veri, dict):
            raise EvobulutApiError(f"Gelir/Gider detayı beklenmeyen format (id={kayit_id}).")
        ana = veri.get("Ana") or {}
        if isinstance(ana, list):
            ana = ana[0] if ana and isinstance(ana[0], dict) else {}
        odemeler = veri.get("OdemeBilgiler") or []
        if not isinstance(odemeler, list):
            odemeler = []
        return {
            "Ana": ana if isinstance(ana, dict) else {},
            "OdemeBilgiler": [x for x in odemeler if isinstance(x, dict)],
        }

    def _tum_listeyi_cek(self, sayfa_fn, ara: str = "", max_sayfa: int = 500) -> list[dict]:
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = sayfa_fn(sayfa=sayfa, ara=ara)
            if toplam is None:
                toplam = adet
            if not satirlar:
                break
            tum.extend(satirlar)
            if toplam is not None and toplam > 0 and len(tum) >= toplam:
                break
            if len(satirlar) < 30:
                break
            sayfa += 1
        return tum


def _ana_detay_blok(yanit: dict, hata_mesaji: str) -> dict:
    """sql yanıtından {Ana, Detay} çıkarır (fatura/sipariş/irsaliye/kasa ortak)."""
    veri = yanit.get("veri") or yanit.get("Veri")
    blok = None
    if isinstance(veri, list) and veri:
        blok = veri[0] if isinstance(veri[0], dict) else None
    elif isinstance(veri, dict):
        # Bazı uçlarda Ana/Detay doğrudan veri altında
        if "Ana" in veri or "Detay" in veri:
            blok = veri
        else:
            # tek kayıt dict olabilir
            blok = {"Ana": [veri], "Detay": []}
    if not isinstance(blok, dict):
        raise EvobulutApiError(hata_mesaji)
    ana = blok.get("Ana") or []
    detay = blok.get("Detay") or []
    if isinstance(ana, dict):
        ana0 = ana
    elif isinstance(ana, list) and ana:
        ana0 = ana[0] if isinstance(ana[0], dict) else {}
    else:
        ana0 = {}
    return {
        "Ana": ana0 if isinstance(ana0, dict) else {},
        "Detay": [x for x in detay if isinstance(x, dict)] if isinstance(detay, list) else [],
    }


def _uid_bul(yanit: dict) -> str | None:
    veri = yanit.get("veri") or yanit.get("Veri") or {}
    ana = veri.get("Ana") if isinstance(veri, dict) else None
    if isinstance(ana, list) and ana:
        ilk = ana[0]
        if isinstance(ilk, dict):
            uid = ilk.get("UID") or ilk.get("uid")
            if uid:
                return str(uid)
    for anahtar in ("UID", "uid", "Token", "token"):
        if yanit.get(anahtar):
            return str(yanit[anahtar])
    return None


def _stokjq_satir_map(row: dict, *, kos: str) -> dict:
    """stokjq G.* satırını STOK_MIKTAR/jq_list alanlarına çevirir."""
    a_pasif = str(row.get("G.a_pasif") or row.get("a_pasif") or "")
    if a_pasif == "15" or "pasif^x^15" in kos:
        aktif_pasif = "Pasif"
    elif a_pasif == "14" or "pasif^x^14" in kos:
        aktif_pasif = "Aktif"
    else:
        aktif_pasif = row.get("TBL_GENEL.a_adi") or ("Pasif" if a_pasif == "15" else "Aktif")
    return {
        "a_id": str(row.get("G.a_id") or row.get("a_id") or ""),
        "a_kod": row.get("G.a_kod") or row.get("a_kod"),
        "a_adi": row.get("G.a_adi") or row.get("a_adi"),
        "a_alt_adi": row.get("G.a_alt_adi"),
        "a_tur": row.get("G.a_tur"),
        "a_brm_id": row.get("G.a_brm_id"),
        "ana_birim_adi": row.get("TBL_STOK_BRM.a_adi") or row.get("ana_birim_adi"),
        "a_giren": row.get("G.a_giren") or row.get("a_giren"),
        "a_cikan": row.get("G.a_cikan") or row.get("a_cikan"),
        "a_kalan": row.get("G.a_kalan") or row.get("a_kalan"),
        "a_fiyat_al": row.get("G.a_fiyat_al"),
        "a_fiyat_sat": row.get("G.a_fiyat_sat"),
        "a_kdv_al": row.get("G.a_kdv_al"),
        "a_kdv_sat": row.get("G.a_kdv_sat"),
        "a_pasif": a_pasif or None,
        "aktif_pasif": aktif_pasif,
        "kaynak_liste": "stokjq",
        "stokjq_kos": kos,
    }


def _ana_listesi(yanit: dict) -> list[dict]:
    veri = yanit.get("veri") or yanit.get("Veri") or {}
    if not isinstance(veri, dict):
        return []
    ana = veri.get("Ana") or []
    return [x for x in ana if isinstance(x, dict)]


def _sayfa_adet(yanit: dict) -> int:
    veri = yanit.get("veri") or yanit.get("Veri") or {}
    if not isinstance(veri, dict):
        return 0
    sayfa = veri.get("sayfa") or []
    if isinstance(sayfa, list) and sayfa and isinstance(sayfa[0], dict):
        ham = sayfa[0]
        for anahtar in ("Adet", "ADET", "adet"):
            if ham.get(anahtar) is not None and str(ham.get(anahtar)).strip() != "":
                try:
                    return int(str(ham.get(anahtar)).replace(".", "").replace(",", ""))
                except ValueError:
                    return 0
    return 0


def _fatura_adet(yanit: dict) -> int:
    """Fatura jq_list: Adet çoğu zaman Toplam_Tutar[0].ADET içinde."""
    n = _sayfa_adet(yanit)
    if n > 0:
        return n
    veri = yanit.get("veri") or yanit.get("Veri") or {}
    if not isinstance(veri, dict):
        return 0
    toplam = veri.get("Toplam_Tutar") or []
    if isinstance(toplam, list) and toplam and isinstance(toplam[0], dict):
        ham = toplam[0].get("ADET") or toplam[0].get("Adet") or toplam[0].get("adet")
        if ham is not None and str(ham).strip() != "":
            try:
                return int(str(ham).replace(".", "").replace(",", ""))
            except ValueError:
                return 0
    return 0
