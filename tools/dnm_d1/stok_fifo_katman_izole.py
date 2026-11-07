"""Devir 1 stok/LOT FIFO katman — izole hesap (3150 kapsam).

- 2522 alt küme ayrı gösterilir; STOK_HAREKET.jsonl yeniden çekilmez.
- Katman maliyeti kart a_maliyet_fifo / ortalamadan uydurulmaz.
- Negatifler korunur; bedelsiz (0) ile bilinmeyen maliyet ayrılır.
- Kaynak FIFO↔ort yöntem farkı miktar/eksik kayıttan ayrı tutulur.
- K05 / mali yazım / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_fifo_katman_izole
  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_fifo_katman_izole
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

STOK_HRK = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET.jsonl"
BELGE_SATIR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
STOK_MALIYET = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MALIYET.json"
LOT_KATMAN = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
KAPSAM_AD = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_KAPSAM_ADLANDIRMA.json"

# Alış / alış iade yönleri (Evo belge türleri)
ALIS_TUR = {"30", "32", "34", "36"}  # alış fatura/fiş/irsaliye (+iade varyantları kontrol)
SATIS_IADE_GIRIS = {"35", "37"}  # satış iade → stok girişi (maliyet = satış iade birim; katman maliyeti şüpheli)
KURUS = Decimal("0.01")


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _q4(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.0001"))


@dataclass
class Katman:
    sira: int
    stok_id: str
    belge_id: str
    belge_tur: str
    belge_tarih: str | None
    satir_index: int
    depo_id: str | None
    birim: str | None
    giren_miktar: Decimal
    kalan_miktar: Decimal
    birim_maliyet: Decimal | None
    maliyet_sinif: str  # KANITLI | BEDELSIZ_SIFIR | BILINMEYEN
    kaynak_satir_fiyat: str | None
    not_: str = ""


@dataclass
class FifoSonuc:
    stok_id: str
    durum: str
    kart_kalan: Decimal | None
    hareket_net: Decimal | None
    miktar_esit: bool
    cikis_var: bool
    katmanlar: list[Katman] = field(default_factory=list)
    fifo_birim_izole: Decimal | None = None
    fifo_toplam_izole: Decimal | None = None
    kaynak_fifo_kart: Decimal | None = None
    kaynak_ort_kart: Decimal | None = None
    yontem_fark_birim: Decimal | None = None
    aciklama: str = ""


def _yukle_hareket_ozet() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with STOK_HRK.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            sid = str(o.get("kaynak_stok_id") or "")
            if sid:
                out[sid] = o
    return out


def _yukle_maliyet() -> dict[str, dict]:
    ham = json.loads(STOK_MALIYET.read_text(encoding="utf-8"))
    return {str(s["kaynak_stok_id"]): s for s in (ham.get("stoklar") or [])}


def _yukle_alis_girisleri() -> dict[str, list[dict]]:
    """stok_id → kronolojik alış/giriş satırları (BELGE_SATIR)."""
    by: dict[str, list[dict]] = defaultdict(list)
    with BELGE_SATIR.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            tur = str(o.get("tur") or o.get("liste_tur") or "")
            # Yalnız alış yönü giriş; satış iade ayrı (maliyet kanıtı zayıf)
            if tur not in ALIS_TUR:
                continue
            t = parse_tarih(o.get("tarih"))
            if t is None or t > DONEM_SONU:
                continue
            bid = str(o.get("kaynak_belge_id") or "")
            for i, s in enumerate(o.get("satirlar") or []):
                sid = str(s.get("stok_id") or s.get("a_stok_id") or "")
                if not sid:
                    continue
                mik = _dec(s.get("miktar"))
                if mik is None or mik == 0:
                    continue
                fiyat = _dec(s.get("birim_fiyat"))
                by[sid].append(
                    {
                        "belge_id": bid,
                        "belge_tur": tur,
                        "belge_tarih": t.isoformat(),
                        "satir_index": i,
                        "depo_id": str(s.get("depo_id") or "") or None,
                        "birim": s.get("birim"),
                        "miktar": mik,
                        "birim_fiyat": fiyat,
                        "stok_kod": s.get("stok_kod"),
                    }
                )
    for sid in by:
        by[sid].sort(
            key=lambda r: (
                r["belge_tarih"] or "",
                r["belge_id"],
                r["satir_index"],
            )
        )
    return by


def _maliyet_sinif(fiyat: Decimal | None) -> str:
    if fiyat is None:
        return "BILINMEYEN"
    if fiyat == 0:
        return "BEDELSIZ_SIFIR"
    return "KANITLI"


def fifo_alis_only(
    stok_id: str,
    *,
    kart_kalan: Decimal | None,
    hareket_net: Decimal | None,
    girisler: list[dict],
    kaynak_fifo: Decimal | None,
    kaynak_ort: Decimal | None,
) -> FifoSonuc:
    """Çıkış yok + miktar eşit → tüm alış satırları kalan katman (FIFO sıra = giriş sırası)."""
    miktar_esit = (
        kart_kalan is not None
        and hareket_net is not None
        and kart_kalan == hareket_net
    )
    cikis_var = False
    if not miktar_esit:
        return FifoSonuc(
            stok_id=stok_id,
            durum="MIKTAR_ESIT_DEGIL",
            kart_kalan=kart_kalan,
            hareket_net=hareket_net,
            miktar_esit=False,
            cikis_var=cikis_var,
            kaynak_fifo_kart=kaynak_fifo,
            kaynak_ort_kart=kaynak_ort,
            aciklama="Kart kalan ≠ hareket net; FIFO katman kurulmaz (miktar hatası yöntem farkı sayılmaz)",
        )

    # Çıkış yok koşulu çağıran tarafta kontrol edilir
    katmanlar: list[Katman] = []
    toplam_giren = Decimal("0")
    for sira, g in enumerate(girisler, 1):
        fiyat = g["birim_fiyat"]
        sinif = _maliyet_sinif(fiyat)
        mik = g["miktar"]
        toplam_giren += mik
        katmanlar.append(
            Katman(
                sira=sira,
                stok_id=stok_id,
                belge_id=g["belge_id"],
                belge_tur=g["belge_tur"],
                belge_tarih=g["belge_tarih"],
                satir_index=g["satir_index"],
                depo_id=g["depo_id"],
                birim=g["birim"],
                giren_miktar=mik,
                kalan_miktar=mik,  # çıkış yok
                birim_maliyet=fiyat if sinif != "BILINMEYEN" else None,
                maliyet_sinif=sinif,
                kaynak_satir_fiyat=str(fiyat) if fiyat is not None else None,
                not_="Alış BELGE_SATIR; çıkış yok — kalan=giren",
            )
        )

    if kart_kalan is not None and toplam_giren != kart_kalan:
        return FifoSonuc(
            stok_id=stok_id,
            durum="ALIS_SATIR_MIKTAR_UYUSMUYOR",
            kart_kalan=kart_kalan,
            hareket_net=hareket_net,
            miktar_esit=True,
            cikis_var=False,
            katmanlar=katmanlar,
            kaynak_fifo_kart=kaynak_fifo,
            kaynak_ort_kart=kaynak_ort,
            aciklama=(
                f"BELGE_SATIR alış toplamı ({toplam_giren}) ≠ kart/hareket ({kart_kalan}); "
                "açılış/devir veya eksik belge — katman tamam sayılmaz"
            ),
        )

    if not katmanlar:
        return FifoSonuc(
            stok_id=stok_id,
            durum="GIRIS_BELGE_YOK",
            kart_kalan=kart_kalan,
            hareket_net=hareket_net,
            miktar_esit=True,
            cikis_var=False,
            kaynak_fifo_kart=kaynak_fifo,
            kaynak_ort_kart=kaynak_ort,
            aciklama="Çıkış yok / miktar eşit ama alış BELGE_SATIR yok (açılış/devir?)",
        )

    bilinmeyen = sum(1 for k in katmanlar if k.maliyet_sinif == "BILINMEYEN")
    bedelsiz = sum(1 for k in katmanlar if k.maliyet_sinif == "BEDELSIZ_SIFIR")
    kanitli = [k for k in katmanlar if k.maliyet_sinif == "KANITLI"]

    if bilinmeyen:
        durum = "KATMAN_MIKTAR_OK_MALIYET_BILINMEYEN"
        fifo_birim = None
        fifo_toplam = None
    else:
        toplam = sum(
            (k.kalan_miktar * (k.birim_maliyet or Decimal("0")) for k in katmanlar),
            Decimal("0"),
        )
        mik = sum((k.kalan_miktar for k in katmanlar), Decimal("0"))
        fifo_toplam = toplam
        fifo_birim = (toplam / mik) if mik else None
        durum = "FIFO_IZOLE_TAM" if bedelsiz == 0 or kanitli else "FIFO_IZOLE_BEDELSIZ_DAHIL"

    yontem_fark = None
    if kaynak_fifo is not None and kaynak_ort is not None:
        yontem_fark = kaynak_fifo - kaynak_ort

    return FifoSonuc(
        stok_id=stok_id,
        durum=durum,
        kart_kalan=kart_kalan,
        hareket_net=hareket_net,
        miktar_esit=True,
        cikis_var=False,
        katmanlar=katmanlar,
        fifo_birim_izole=fifo_birim,
        fifo_toplam_izole=fifo_toplam,
        kaynak_fifo_kart=kaynak_fifo,
        kaynak_ort_kart=kaynak_ort,
        yontem_fark_birim=yontem_fark,
        aciklama="İzole FIFO yalnız kanıtlı alış satırlarından; kart maliyetinden üretilmedi",
    )


def fifo_consume(
    girisler: list[dict],
    cikislar: list[tuple[date, Decimal, str]],
) -> list[Katman]:
    """Genel FIFO tüketim (test / ileride hareket detayı gelince).

    girisler: BELGE_SATIR alış dict listesi
    cikislar: (tarih, miktar, kaynak_id) kronolojik
    """
    q: deque[Katman] = deque()
    sira = 0
    for g in girisler:
        sira += 1
        fiyat = g["birim_fiyat"]
        sinif = _maliyet_sinif(fiyat)
        q.append(
            Katman(
                sira=sira,
                stok_id=str(g.get("stok_id") or ""),
                belge_id=g["belge_id"],
                belge_tur=g["belge_tur"],
                belge_tarih=g["belge_tarih"],
                satir_index=g["satir_index"],
                depo_id=g["depo_id"],
                birim=g["birim"],
                giren_miktar=g["miktar"],
                kalan_miktar=g["miktar"],
                birim_maliyet=fiyat if sinif != "BILINMEYEN" else None,
                maliyet_sinif=sinif,
                kaynak_satir_fiyat=str(fiyat) if fiyat is not None else None,
            )
        )
    for _t, mik, _kid in cikislar:
        kalan_cik = mik
        while kalan_cik > 0 and q:
            kat = q[0]
            al = min(kat.kalan_miktar, kalan_cik)
            kat.kalan_miktar -= al
            kalan_cik -= al
            if kat.kalan_miktar == 0:
                q.popleft()
        # Negatif stok: kalan_cik > 0 → açıkta bırakılır (uydurma giriş yok)
    return [k for k in q if k.kalan_miktar != 0]


def _katman_dict(k: Katman) -> dict[str, Any]:
    return {
        "sira": k.sira,
        "stok_id": k.stok_id,
        "kaynak_belge_id": k.belge_id,
        "belge_tur": k.belge_tur,
        "belge_tarih": k.belge_tarih,
        "satir_index": k.satir_index,
        "depo_id": k.depo_id,
        "birim": k.birim,
        "giren_miktar": str(k.giren_miktar),
        "kalan_miktar": str(k.kalan_miktar),
        "birim_maliyet": str(k.birim_maliyet) if k.birim_maliyet is not None else None,
        "maliyet_sinif": k.maliyet_sinif,
        "kaynak_satir_birim_fiyat": k.kaynak_satir_fiyat,
        "not": k.not_,
    }


def main() -> int:
    hareket = _yukle_hareket_ozet()
    maliyet = _yukle_maliyet()
    alis = _yukle_alis_girisleri()

    kapsam = {}
    if KAPSAM_AD.is_file():
        kapsam = json.loads(KAPSAM_AD.read_text(encoding="utf-8"))

    # 2522 = maliyet çekilen alt küme
    alt_2522 = set(maliyet.keys())
    tum_3150 = set(hareket.keys())

    sayac: Counter = Counter()
    negatif_korunan = []
    fifo_tam: list[dict] = []
    alis_only_aday = 0
    cikisli_esit = 0
    ornek_katman = []

    for sid, hr in hareket.items():
        kart_kalan = _dec(hr.get("kart_kalan"))
        hareket_net = _dec(hr.get("hareket_net"))
        cik = _dec(hr.get("cik_toplam")) or Decimal("0")
        m = maliyet.get(sid) or {}
        kf = _dec(m.get("maliyet_fifo"))
        ko = _dec(m.get("maliyet_ort"))

        if kart_kalan is not None and kart_kalan < 0:
            negatif_korunan.append(
                {
                    "kaynak_stok_id": sid,
                    "kart_kalan": str(kart_kalan),
                    "hareket_net": str(hareket_net) if hareket_net is not None else None,
                    "korundu": True,
                    "fifo_uydurma_yok": True,
                }
            )
            sayac["negatif_kart"] += 1

        miktar_esit = (
            kart_kalan is not None
            and hareket_net is not None
            and kart_kalan == hareket_net
        )
        if not miktar_esit:
            sayac["miktar_esit_degil_veya_eksik"] += 1
            continue

        sayac["miktar_esit"] += 1
        if cik > 0:
            cikisli_esit += 1
            sayac["esit_ama_cikis_var_fifo_bekliyor"] += 1
            continue

        alis_only_aday += 1
        son = fifo_alis_only(
            sid,
            kart_kalan=kart_kalan,
            hareket_net=hareket_net,
            girisler=alis.get(sid) or [],
            kaynak_fifo=kf,
            kaynak_ort=ko,
        )
        sayac[son.durum] += 1
        kayit = {
            "kaynak_stok_id": sid,
            "kod": hr.get("kod") or m.get("kod"),
            "durum": son.durum,
            "kart_kalan": str(son.kart_kalan) if son.kart_kalan is not None else None,
            "hareket_net": str(son.hareket_net) if son.hareket_net is not None else None,
            "katman_adet": len(son.katmanlar),
            "fifo_birim_izole": str(son.fifo_birim_izole)
            if son.fifo_birim_izole is not None
            else None,
            "fifo_toplam_izole": str(son.fifo_toplam_izole)
            if son.fifo_toplam_izole is not None
            else None,
            "kaynak_fifo_kart": str(son.kaynak_fifo_kart)
            if son.kaynak_fifo_kart is not None
            else None,
            "kaynak_ort_kart": str(son.kaynak_ort_kart)
            if son.kaynak_ort_kart is not None
            else None,
            "yontem_fark_birim_kaynak_fifo_minus_ort": str(son.yontem_fark_birim)
            if son.yontem_fark_birim is not None
            else None,
            "yontem_farki_miktar_hatasi_degil": True,
            "katmanlar": [_katman_dict(k) for k in son.katmanlar],
            "aciklama": son.aciklama,
            "alt_kume_2522": sid in alt_2522,
        }
        if son.durum.startswith("FIFO_IZOLE"):
            fifo_tam.append(kayit)
            if len(ornek_katman) < 8:
                ornek_katman.append(kayit)

    # Kaynak yöntem farkı (mevcut kanıt) — miktardan ayrı
    yontem_ayri = {}
    ya_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_ORT_YONTEM_AYRI.json"
    if ya_yol.is_file():
        ya = json.loads(ya_yol.read_text(encoding="utf-8"))
        yontem_ayri = {
            "kanit": ya_yol.name,
            "adet": ya.get("adet"),
            "fark_tutar_abs": ya.get("fark_tutar_abs"),
            "kural": "Yöntem farkı; miktar/eksik kayıt/birim hatası buraya kapatılmaz",
        }

    eksik_kaynak_raporu = {
        "gerekce": (
            "STOK_HAREKET.jsonl yalnız kart özeti (gir/cik toplam); satır satır "
            "tarih/depo/birim/gir_fiyat saklanmadı. Çıkışlı stoklarda izole FIFO "
            "için hareket detayı şart. Seri_Lot_List katman birim maliyet alanı yok."
        ),
        "yeniden_toplama": (
            "Gerekçeli: FIFO katman için stok_id bazlı StokHareket/base cmd=list "
            "detayının jsonl’e yazılması (özet üzerine). Gerekçesiz 3150 özet tekrarı yok."
        ),
        "api": "StokHareket/base/ cmd=list (stok_id, bas_tar=01.01.2015, bit_tar=31.08.2026)",
        "istenilen_alanlar": [
            "tarih / işlem sırası",
            "belge_tur / Fat_id (veya belge_id)",
            "depo",
            "Birim / temel birim çarpanı",
            "gir_miktar / cik_miktar",
            "gir_fiyat (giriş birim veya satır tutarı — birim netliği)",
            "cik_fiyat (satış; FIFO maliyetinde kullanılmaz, izlenebilirlik)",
            "devir bayrağı / açılış işareti",
            "mümkünse lot_no veya ack lot ipucu",
        ],
        "ek_lot_raporu": {
            "menu_veya_api": "fatura/base cmd=sql → Detay.Seri_Lot_List",
            "istenilen_ek": [
                "lot_no",
                "özgün giriş tarihi",
                "katman birim maliyet (şu an yok)",
                "kalan (anlık alanın katman dökümü olmadığı notu korunur)",
            ],
        },
        "acilis_devir": "Devir/açılış fiş satırları (belge türü + birim maliyet) — BELGE_SATIR’da eksikse ayrı çekim",
    }

    lot_durum = {}
    if LOT_KATMAN.is_file():
        lot = json.loads(LOT_KATMAN.read_text(encoding="utf-8"))
        lot_durum = {
            "kanit": LOT_KATMAN.name,
            "katman_maliyet": (lot.get("katman_maliyet") or {}).get("durum"),
            "lot_olay": lot.get("lot_olay_adet"),
        }

    kanit = {
        "format": "d1-stok-fifo-katman-izole-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "kasa_kanitlari_korundu": True,
        "hareket_yeniden_toplanmadi": True,
        "kapsam": {
            "kart_3150": len(tum_3150),
            "alt_kume_2522_maliyet_cekilen": len(alt_2522),
            "2522_ayri_gosterildi": True,
            "kapsam_adlandirma_kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_KAPSAM_ADLANDIRMA.json"
            if kapsam
            else None,
            "kural": "1244/1063 (2522) ile 1775 (3150) arasında gerekçesiz fark kıyaslanmaz",
        },
        "sayac": dict(sayac),
        "alis_only_miktar_esit_aday": alis_only_aday,
        "esit_ama_cikisli_fifo_bekleyen": cikisli_esit,
        "fifo_izole_tam_adet": sum(
            1 for x in fifo_tam if x["durum"] == "FIFO_IZOLE_TAM"
        ),
        "fifo_izole_bedelsiz_dahil_adet": sum(
            1 for x in fifo_tam if x["durum"] == "FIFO_IZOLE_BEDELSIZ_DAHIL"
        ),
        "fifo_izole_kayitlar": fifo_tam[:200],
        "fifo_izole_kayit_adet_toplam": len(fifo_tam),
        "ornek_katman": ornek_katman,
        "negatif_korunan": negatif_korunan[:50],
        "negatif_adet": len(negatif_korunan),
        "bedelsiz_vs_bilinmeyen": {
            "kural": "birim_fiyat=0 → BEDELSIZ_SIFIR; fiyat yok → BILINMEYEN; kart fifo ile doldurulmaz",
        },
        "yontem_karsilastirma": yontem_ayri,
        "lot_mevcut": lot_durum,
        "eksik_kaynak_raporu": eksik_kaynak_raporu,
        "kurallar": [
            "Kart a_maliyet_fifo / ortalama ile geçmiş katman uydurulmaz",
            "Negatif stok korunur",
            "Miktar/eksik/birim hatası yöntem farkına kapatılmaz",
            "Çıkışlı stokta hareket detayı olmadan FIFO kurulmaz",
        ],
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "diger_kaynak_eksikleri_kabul_edilmedi": True,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_FIFO_KATMAN_IZOLE", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "kapsam_3150": len(tum_3150),
        "alt_2522": len(alt_2522),
        "fifo_izole_tam": kanit["fifo_izole_tam_adet"],
        "fifo_izole_bedelsiz": kanit["fifo_izole_bedelsiz_dahil_adet"],
        "cikisli_bekleyen": cikisli_esit,
        "negatif": len(negatif_korunan),
        "hareket_yeniden_toplanmadi": True,
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_FIFO_KATMAN_IZOLE_OZET.json", ozet)

    # FIFO kontrol engeline bağla (kasa tamamını bozma)
    fifo_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
    if fifo_yol.is_file():
        try:
            fifo = json.loads(fifo_yol.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {"format": "d1-fifo-kasa-banka-pos-kontrol-v1", "tamamlanan": [], "engeller": []}
        # engel güncelle
        engeller = []
        for e in fifo.get("engeller") or []:
            if e.get("is") == "FIFO_katman_birim_maliyet":
                e = {
                    **e,
                    "mevcut": {
                        "izole_fifo_tam": kanit["fifo_izole_tam_adet"],
                        "cikisli_bekleyen": cikisli_esit,
                        "kanit": f"kaynak/{yol.name}",
                        "katman_maliyet_durum": "KISMI_ALIS_ONLY_IZOLE",
                    },
                    "gerekli_kaynak": eksik_kaynak_raporu["api"]
                    + " + satır alanları: "
                    + ", ".join(eksik_kaynak_raporu["istenilen_alanlar"][:6]),
                }
            engeller.append(e)
        fifo["engeller"] = engeller
        fifo["k05"] = False
        fifo["stok_fifo_izole"] = ozet
        ham = json.dumps(fifo, ensure_ascii=False, indent=2).encode("utf-8")
        fifo_yol.write_bytes(ham)
        import hashlib

        fifo_yol.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(ham).hexdigest().upper()}  {fifo_yol.name}\n",
            encoding="ascii",
        )

    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
