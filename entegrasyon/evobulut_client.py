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
Gelen e-Fatura: POST /FaturaUbl/base/  cmd=jq_list|sql
Cari export: POST /CariExport/base/  cmd=export
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE = "https://ws.evobulut.com/api"
CONFIG_PATH = Path(__file__).resolve().parent / "evobulut.env"


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


def load_credentials(path: Path | None = None) -> EvobulutCredentials:
    """evobulut.env dosyasından okur. Boş alan varsa EvobulutConfigError."""
    yol = path or CONFIG_PATH
    if not yol.is_file():
        raise EvobulutConfigError(
            f"EvoBulut yapılandırması yok: {yol.name}\n"
            f"Şablon: entegrasyon/evobulut_config.example.env → evobulut.env"
        )
    degerler: dict[str, str] = {}
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        degerler[anahtar.strip()] = deger.strip().strip('"').strip("'")

    kullanici = degerler.get("EVOBULUT_KULLANICI_KODU", "").strip()
    sifre = degerler.get("EVOBULUT_SIFRE", "").strip()
    app = degerler.get("EVOBULUT_APP", "muhasebe_programi").strip() or "muhasebe_programi"
    base = degerler.get("EVOBULUT_BASE_URL", DEFAULT_BASE).strip() or DEFAULT_BASE
    if not kullanici or not sifre:
        raise EvobulutConfigError(
            "EVOBULUT_KULLANICI_KODU ve EVOBULUT_SIFRE doldurulmalı "
            f"({yol.name})."
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
        """Sayfalı stok listesini birleştirir (sayfa başına ~30)."""
        return self._tum_listeyi_cek(self.stok_liste_sayfa, ara=ara, max_sayfa=max_sayfa)

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

    def tum_alis_faturalari_cek(
        self,
        *,
        ara: str = "",
        tarih_bas: str = "",
        tarih_son: str = "",
        max_sayfa: int = 500,
    ) -> list[dict]:
        """Alış faturaları (tur=30), sayfa başına ~30."""
        if not self.uid:
            self.login()
        tum: list[dict] = []
        sayfa = 0
        toplam = None
        while sayfa < max_sayfa:
            satirlar, adet = self.fatura_liste_sayfa(
                sayfa,
                tur="30",
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

    def fatura_detay(self, fatura_id: str | int) -> dict:
        """Fatura başlık + satırlar. Döner: {Ana: dict, Detay: list}."""
        if not self.uid:
            self.login()
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
            raise EvobulutApiError(f"Fatura detayı alınamadı (id={fatura_id}).")
        ana = blok.get("Ana") or []
        detay = blok.get("Detay") or []
        ana0 = ana[0] if isinstance(ana, list) and ana else {}
        return {
            "Ana": ana0 if isinstance(ana0, dict) else {},
            "Detay": [x for x in detay if isinstance(x, dict)] if isinstance(detay, list) else [],
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
