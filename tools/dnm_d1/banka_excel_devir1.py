"""Banka Toplamı Excel → Devir 1 kanıt (R002).

Manifest: 01.06.2025–31.08.2026, DNM 42178 (tarihler Excel’de yok).
K05 açmaz. Düzeltme fişi/tolerans kapatma yok. Devir2 öğleden sonra.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.banka_excel_devir1
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar

EXCEL_SRC_CANDIDATES = [
    Path.home() / "Downloads" / "table_widget_R002_07-11-2026 (1).xlsx",
    Path.home() / "Downloads" / "table_widget_R002_07-11-2026.xlsx",
]
EXCEL_HEDEF = KAYNAK / "excel" / "Banka_Toplami_D1_20260831_R002.xlsx"

FILTRE_BAS = date(2025, 6, 1)
FILTRE_SON = DONEM_SONU  # 2026-08-31
FIRMA_ID = "42178"
RAPOR_UI = "Banka Toplamı"
KURUS = Decimal("0.01")


def _norm(s: str) -> str:
    s = (s or "").upper().replace("İ", "I").replace("ı", "I")
    for a, b in (("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _dec_opt(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        # float’ı str ile al — ham Excel kayan noktasını koru
        return Decimal(str(v))
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS)


def main() -> int:
    src = next((p for p in EXCEL_SRC_CANDIDATES if p.is_file()), None)
    if not src:
        raise SystemExit("Excel bulunamadı")
    EXCEL_HEDEF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, EXCEL_HEDEF)
    ham_xlsx = EXCEL_HEDEF.read_bytes()
    sha = hashlib.sha256(ham_xlsx).hexdigest().upper()
    EXCEL_HEDEF.with_suffix(".xlsx.sha256").write_text(
        f"{sha}  {EXCEL_HEDEF.name}\n", encoding="ascii"
    )

    wb = openpyxl.load_workbook(EXCEL_HEDEF, data_only=True)
    ws = wb.active
    excel_rows: list[dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        adi = ws.cell(r, 1).value
        if not adi:
            continue
        excel_rows.append(
            {
                "excel_satir": r,
                "adi": str(adi).strip(),
                "toplam_ham": ws.cell(r, 2).value,
                "doviz": ws.cell(r, 3).value,
                "giren_ham": ws.cell(r, 4).value,
                "cikan_ham": ws.cell(r, 5).value,
                "toplam": _dec_opt(ws.cell(r, 2).value),
                "giren": _dec_opt(ws.cell(r, 4).value),
                "cikan": _dec_opt(ws.cell(r, 5).value),
            }
        )

    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    kartlar = list(banka.get("kartlar") or [])
    hareketler = list(banka.get("hareketler") or [])
    pos_sinif = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}POS_KART_KREDI.json").read_text(encoding="utf-8")
    )

    kart_by_norm: dict[str, list[dict]] = defaultdict(list)
    kart_by_id: dict[str, dict] = {}
    for k in kartlar:
        kid = str(k.get("id") or "")
        ad = str(k.get("text") or "").strip()
        kart_by_id[kid] = k
        kart_by_norm[_norm(ad)].append(k)

    # Eşleme
    eslemeler = []
    for er in excel_rows:
        n = _norm(er["adi"])
        aday = kart_by_norm.get(n) or []
        kesin = None
        durum = "ESLESMEDI"
        if len(aday) == 1:
            kesin = str(aday[0]["id"])
            durum = "KESIN_ID"
        elif len(aday) > 1:
            durum = "COKLU_ADAY"
        else:
            # yakın
            yakin = []
            for kn, items in kart_by_norm.items():
                if n in kn or kn in n:
                    yakin.extend(items)
            if len(yakin) == 1:
                kesin = str(yakin[0]["id"])
                durum = "KESIN_YAKIN_AD"
                aday = yakin
            elif yakin:
                durum = "YAKIN_COKLU"
                aday = yakin
        eslemeler.append(
            {
                **{k: er[k] for k in ("excel_satir", "adi", "doviz")},
                "excel_giren": str(er["giren"]) if er["giren"] is not None else None,
                "excel_cikan": str(er["cikan"]) if er["cikan"] is not None else None,
                "excel_toplam": str(er["toplam"]) if er["toplam"] is not None else None,
                "excel_giren_ham_tip": type(er["giren_ham"]).__name__,
                "kaynak_cari_aday_id": [str(a["id"]) for a in aday],
                "kaynak_hesap_id": kesin,
                "esleme_durumu": durum,
                "a_posmu": (kart_by_id.get(kesin) or {}).get("a_posmu") if kesin else None,
            }
        )

    # Hareketleri hesap+tarih ile topla
    def topla(hid: str, *, bas: date | None, son: date) -> dict[str, Any]:
        g = Decimal("0")
        c = Decimal("0")
        n = 0
        once = 0
        ilk = None
        son_t = None
        for h in hareketler:
            if str(h.get("G.a_banka_id") or "") != hid:
                continue
            t = parse_tarih(h.get("G.a_tarih"))
            if t is None:
                continue
            if t > son:
                continue
            if bas is not None and t < bas:
                once += 1
                if ilk is None or t < ilk:
                    ilk = t
                continue
            gir, cik = _yon_tutar(h)
            if gir is None and cik is None:
                continue
            g += gir or Decimal("0")
            c += cik or Decimal("0")
            n += 1
            if ilk is None or t < ilk:
                ilk = t
            if son_t is None or t > son_t:
                son_t = t
        return {
            "giren": g,
            "cikan": c,
            "toplam_net": g - c,
            "hareket_adet": n,
            "filtre_oncesi_adet": once,
            "ilk_tarih": ilk.isoformat() if ilk else None,
            "son_tarih": son_t.isoformat() if son_t else None,
        }

    # Global en eski banka hareketi
    tum_tarihler = []
    for h in hareketler:
        t = parse_tarih(h.get("G.a_tarih"))
        if t:
            tum_tarihler.append(t)
    en_eski_kaynak = min(tum_tarihler) if tum_tarihler else None
    once_filtre = [t for t in tum_tarihler if t < FILTRE_BAS]
    en_eski_once = min(once_filtre) if once_filtre else None

    hesap_sonuclar = []
    for em in eslemeler:
        hid = em["kaynak_hesap_id"]
        eg, ec, et = (
            _dec_opt(em["excel_giren"]),
            _dec_opt(em["excel_cikan"]),
            _dec_opt(em["excel_toplam"]),
        )
        if not hid:
            hesap_sonuclar.append(
                {
                    "excel_adi": em["adi"],
                    "excel_satir": em["excel_satir"],
                    "kaynak_hesap_id": None,
                    "kaynak_adi": None,
                    "a_posmu": None,
                    "esleme_durumu": em["esleme_durumu"],
                    "excel": {
                        "giren": em["excel_giren"],
                        "cikan": em["excel_cikan"],
                        "toplam": em["excel_toplam"],
                    },
                    "karsilastirma": None,
                    "sonuc": "ESLESME_YOK",
                    "kalan_eksik": "kaynak hesap ID eşleşmedi",
                    "donem_neti_kapanis_degil": True,
                    "acilis_devir_uyari": "Eşleşme yok; açılış/devir değerlendirmesi yapılamadı",
                }
            )
            continue

        aralik = topla(hid, bas=FILTRE_BAS, son=FILTRE_SON)
        tum = topla(hid, bas=None, son=FILTRE_SON)
        once_ozet = topla(hid, bas=None, son=FILTRE_BAS - timedelta(days=1))

        kg, kc, kt = aralik["giren"], aralik["cikan"], aralik["toplam_net"]

        def sinif_fark(ex: Decimal | None, ky: Decimal) -> dict[str, Any]:
            if ex is None:
                return {"durum": "EXCEL_YOK", "fark": None}
            fark = ex - ky
            if fark == 0:
                return {"durum": "TAM_ESIT", "fark": "0", "fark_ham": "0"}
            # kuruş eşit mi?
            if _q2(ex) == _q2(ky):
                return {
                    "durum": "KAYAN_NOKTA_ARTIGI",
                    "fark": str(fark),
                    "fark_kurus_sonrasi": "0.00",
                    "aciklama": "Kuruş (0.01) eşit; fark float/kayan nokta artığı — toleransla kapatılmadı, ayrı tutuldu",
                }
            return {
                "durum": "GERCEK_FARK",
                "fark": str(fark),
                "fark_kurus": str(_q2(ex) - _q2(ky)),
            }

        sg = sinif_fark(eg, kg)
        sc = sinif_fark(ec, kc)
        st = sinif_fark(et, kt)

        # Toplam = Giren-Çıkan excel iç tutarlılık
        excel_net_check = None
        if eg is not None and ec is not None and et is not None:
            excel_net_check = {
                "giren_eksi_cikan": str(eg - ec),
                "toplam_sutun": str(et),
                "fark": str(et - (eg - ec)),
                "kurus_esit": _q2(et) == _q2(eg - ec),
            }

        sonuc = "TAM_ESLESME"
        if any(x["durum"] == "GERCEK_FARK" for x in (sg, sc, st)):
            sonuc = "FARK_VAR"
        elif any(x["durum"] == "KAYAN_NOKTA_ARTIGI" for x in (sg, sc, st)):
            sonuc = "ESIT_KAYAN_NOKTA_ARTIGI"
        elif not hid:
            sonuc = "ESLESME_YOK"

        acilis_eksik = once_ozet["hareket_adet"] > 0 or once_ozet["filtre_oncesi_adet"] > 0
        # once_ozet with bas=None son=31.05.2025 counts all before filter
        once_hareket_var = once_ozet["hareket_adet"] > 0

        hesap_sonuclar.append(
            {
                "excel_adi": em["adi"],
                "excel_satir": em["excel_satir"],
                "kaynak_hesap_id": hid,
                "kaynak_adi": (kart_by_id.get(hid) or {}).get("text"),
                "a_posmu": (kart_by_id.get(hid) or {}).get("a_posmu"),
                "esleme_durumu": em["esleme_durumu"],
                "excel": {
                    "giren": str(eg) if eg is not None else None,
                    "cikan": str(ec) if ec is not None else None,
                    "toplam": str(et) if et is not None else None,
                    "net_ic_tutarlilik": excel_net_check,
                },
                "kaynak_filtre_0106_3108": {
                    "giren": str(kg),
                    "cikan": str(kc),
                    "toplam_net": str(kt),
                    "hareket_adet": aralik["hareket_adet"],
                    "ilk_tarih": aralik["ilk_tarih"],
                    "son_tarih": aralik["son_tarih"],
                },
                "kaynak_tum_3108_dahil": {
                    "giren": str(tum["giren"]),
                    "cikan": str(tum["cikan"]),
                    "toplam_net": str(tum["toplam_net"]),
                    "hareket_adet": tum["hareket_adet"],
                    "ilk_tarih": tum["ilk_tarih"],
                },
                "filtre_oncesi_0106_oncesi": {
                    "hareket_adet": once_ozet["hareket_adet"],
                    "giren": str(once_ozet["giren"]),
                    "cikan": str(once_ozet["cikan"]),
                    "net": str(once_ozet["toplam_net"]),
                    "ilk_tarih": once_ozet["ilk_tarih"],
                    "son_tarih": once_ozet["son_tarih"],
                },
                "karsilastirma": {"giren": sg, "cikan": sc, "toplam": st},
                "sonuc": sonuc,
                "donem_neti_kapanis_degil": once_hareket_var,
                "acilis_devir_uyari": (
                    "01.06.2025 öncesi hareket var; Excel dönem neti tek başına 31.08 kapanış sayılmaz"
                    if once_hareket_var
                    else "Bu hesapta filtre öncesi hareket yok (ham kaynakta)"
                ),
            }
        )

    # Sınıflama KK / KMH
    def excel_sinif(adi: str) -> str:
        n = _norm(adi)
        if "HISSE" in n or "RONESANS" in n:
            return "HISSE_SENEDI"
        if "KREDI KART" in n:
            return "KREDI_KARTI"
        if "KMH" in n and "POS" in n:
            return "KMH_POS_BAGLI"  # tek hesap; ikinci bakiye yok
        if "KMH" in n:
            return "KMH"
        if n.startswith("03 ") or " KREDI" in n and "KART" not in n:
            if "KREDI" in n:
                return "KREDI_HESABI"
        if "POS" in n:
            return "POS_HESABI"
        return "BANKA_MEVDUAT_VEYA_DIGER"

    excel_siniflar = Counter(excel_sinif(e["adi"]) for e in excel_rows)
    onceki_kk_ids = {str(x["id"]) for x in (pos_sinif.get("kredi_karti") or [])}
    onceki_pos_ids = {str(x["id"]) for x in (pos_sinif.get("pos") or [])}
    excel_kk = [h for h in hesap_sonuclar if excel_sinif(h["excel_adi"]) == "KREDI_KARTI"]
    excel_kk_ids = {h["kaynak_hesap_id"] for h in excel_kk if h.get("kaynak_hesap_id")}
    # Önceki 13 KK'de olup Excel'de (adında KREDI KART) olmayanlar
    kk_excel_disi = []
    for x in pos_sinif.get("kredi_karti") or []:
        xid = str(x["id"])
        if xid not in excel_kk_ids:
            kk_excel_disi.append(
                {
                    "kaynak_hesap_id": xid,
                    "ad": x.get("ad"),
                    "aciklama": (
                        "Önceki POS_KART_KREDI sınıflamasında kredi_karti; "
                        "bu Banka Toplamı Excel satır adında 'KREDİ KARTI' yok veya eşleşmedi"
                    ),
                    "kart": {
                        "a_posmu": (kart_by_id.get(xid) or {}).get("a_posmu"),
                        "text": (kart_by_id.get(xid) or {}).get("text"),
                    },
                }
            )

    # KMH: Excel 2 = AKBANK KMH POS BAĞLI (id1, a_posmu=1) + DENİZBANK KMH (id17)
    # Önceki 1 KMH sınıflaması muhtemelen yalnız Denizbank; AKBANK POS altında sayılmıştı
    kmh_excel = [h for h in hesap_sonuclar if "KMH" in _norm(h["excel_adi"])]
    pos_bagli = [h for h in hesap_sonuclar if "POS BAGLI" in _norm(h["excel_adi"]) or "POS BAĞLI" in (h["excel_adi"] or "").upper()]

    ronesans = next((h for h in hesap_sonuclar if "RONESANS" in _norm(h["excel_adi"])), None)

    # Gerekli başlangıç
    gereken_baslangic = (
        en_eski_kaynak.isoformat()
        if en_eski_kaynak and en_eski_kaynak < FILTRE_BAS
        else FILTRE_BAS.isoformat()
    )
    sonraki_rapor = {
        "gerekli": (
            f"Banka ekstresi / Banka Toplamı başlangıç ≤ {gereken_baslangic} "
            f"(veya hesap bazlı doğrulanmış açılış/devir) + bitiş 31.08.2026"
        ),
        "neden": (
            "Excel filtresi 01.06.2025; kaynakta daha eski hareketler var. "
            "Önceki bakiye dahil değilse dönem Giren−Çıkan kapanış sayılmaz."
        ),
        "en_eski_kaynak_hareket": en_eski_kaynak.isoformat() if en_eski_kaynak else None,
        "filtre_oncesi_hareket_adet": len(once_filtre),
    }

    sayac = Counter(h["sonuc"] for h in hesap_sonuclar)
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    manifest = {
        "rapor_ui": RAPOR_UI,
        "menu_yolu": "Raporlar → Finans Raporları → Ekstreler → Banka Toplamı",
        "tarih_araligi": {
            "baslangic": FILTRE_BAS.isoformat(),
            "bitis": FILTRE_SON.isoformat(),
            "not": "Tarihler Excel dosyasında yok; kullanıcı ekranı / bu manifest",
        },
        "firma_id": FIRMA_ID,
        "firma_unvan": "DNM- RAY MOBİLYA AKSESUARLAR ETÜD",
        "excel": {
            "yol": str(EXCEL_HEDEF.relative_to(CALISMA)).replace("\\", "/"),
            "kaynak_indirme": str(src),
            "sha256": sha,
            "satir_adet": len(excel_rows),
            "sutunlar": ["Banka Adı", "Toplam", "Döviz Türü", "Giren", "Çıkan"],
        },
        "kaynak_ham": "kaynak/D1_20260831_KAYNAK_BANKA.json",
        "kaynak_kart_adet": len(kartlar),
        "excel_hesap_adet": len(excel_rows),
        "adet_esitligi_kapsam_kabulu_degil": True,
    }

    out = {
        "format": "d1-banka-toplami-excel-devir1-v1",
        "zaman": now,
        "devir": 1,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
        "manifest": manifest,
        "esleme_ozet": {
            "excel_30": len(excel_rows),
            "kaynak_kart_31": len(kartlar),
            "kesin": sum(1 for e in eslemeler if e["esleme_durumu"].startswith("KESIN")),
            "eslesmedi": sum(1 for e in eslemeler if e["esleme_durumu"] == "ESLESMEDI"),
            "not": "30=31 adet eşitliği kapsam kabulü değildir; eşleme ID bazlıdır",
        },
        "karsilastirma_sayac": dict(sayac),
        "hesaplar": hesap_sonuclar,
        "acilis_devir": {
            "filtre_baslangic": FILTRE_BAS.isoformat(),
            "en_eski_kaynak_banka_hareket": en_eski_kaynak.isoformat() if en_eski_kaynak else None,
            "filtre_oncesi_hareket_adet": len(once_filtre),
            "filtre_oncesi_hesap_adet": sum(
                1 for h in hesap_sonuclar if (h.get("filtre_oncesi_0106_oncesi") or {}).get("hareket_adet", 0) > 0
            ),
            "donem_neti_kapanis_sayilmaz": True,
            "gereken_baslangic_tarihi_kapanis_icin": gereken_baslangic,
            "sonraki_kaynak_raporu": sonraki_rapor,
        },
        "siniflama": {
            "excel_ad_bazli": dict(excel_siniflar),
            "kk_excel_11": {
                "adet": len(excel_kk),
                "idler": sorted(excel_kk_ids),
                "adlar": [h["excel_adi"] for h in excel_kk],
            },
            "onceki_pos_kart_kredi_kk_13": {
                "adet": len(onceki_kk_ids),
                "idler": sorted(onceki_kk_ids),
                "excelde_kk_adi_olmayanlar": kk_excel_disi,
                "aciklama": (
                    "Önceki 13=ürün/sınıf listesi (POS_KART_KREDI). "
                    "Excel 11=satır adında 'KREDİ KARTI' geçenler. "
                    "Fark: HALKBANK ESNAF BUSINESS / HALKBANK KREDİ KARTI vb. Excel’de yok veya ad farklı."
                ),
            },
            "kmh": {
                "excel_2": [
                    {
                        "adi": h["excel_adi"],
                        "id": h.get("kaynak_hesap_id"),
                        "a_posmu": h.get("a_posmu"),
                        "sinif": excel_sinif(h["excel_adi"]),
                    }
                    for h in kmh_excel
                ],
                "onceki_1_kmh_notu": (
                    "Önceki özet 1 KMH (muhtemelen 01 DENİZBANK KMH). "
                    "001 AKBANK AVCILAR KMH POS BAĞLI a_posmu=1 ile POS listesindeydi; "
                    "adında KMH geçtiği için Excel’de 2. KMH satırı — ayrı ikinci bakiye üretilmez."
                ),
            },
            "pos_bagli": {
                "hesaplar": [
                    {
                        "id": h.get("kaynak_hesap_id"),
                        "adi": h["excel_adi"],
                        "a_posmu": h.get("a_posmu"),
                        "tek_hesap_tek_bakiye": True,
                    }
                    for h in pos_bagli
                ],
                "kural": "POS BAĞLI ifadesi ikinci hesap/bakiye oluşturmaz; mevcut banka kartı bakiyesidir",
            },
            "ronesans": {
                "excel_adi": (ronesans or {}).get("excel_adi"),
                "kaynak_hesap_id": (ronesans or {}).get("kaynak_hesap_id"),
                "sinif": "HISSE_SENEDI",
                "mevduat_degil": True,
                "not": "Rönesans hisse senedi mevduat sınıfına yerleştirilmedi",
            },
        },
        "tam_eslesen_idler": [
            h["kaynak_hesap_id"] for h in hesap_sonuclar if h["sonuc"] == "TAM_ESLESME"
        ],
        "kayan_nokta_artigi_idler": [
            h["kaynak_hesap_id"] for h in hesap_sonuclar if h["sonuc"] == "ESIT_KAYAN_NOKTA_ARTIGI"
        ],
        "fark_idler": [h["kaynak_hesap_id"] for h in hesap_sonuclar if h["sonuc"] == "FARK_VAR"],
        "duzeltme_fisi_uretilmedi": True,
        "genel_tolerans_kullanilmadi": True,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    # sürümlü
    onceki = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_BANKA_TOPLAMI_EXCEL.json"
    if onceki.is_file():
        surum = CALISMA / "surumler" / f"banka_excel_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        surum.mkdir(parents=True, exist_ok=True)
        shutil.copy2(onceki, surum / onceki.name)

    yaz_kaynak("DOGRULAMA_BANKA_TOPLAMI_EXCEL", out)
    yaz_json(
        CALISMA / "BANKA_TOPLAMI_EXCEL_OZET.json",
        {
            "zaman": now,
            "manifest": manifest["tarih_araligi"],
            "firma_id": FIRMA_ID,
            "excel_30": len(excel_rows),
            "kaynak_kart_31": len(kartlar),
            "sayac": dict(sayac),
            "en_eski_hareket": en_eski_kaynak.isoformat() if en_eski_kaynak else None,
            "gereken_baslangic": gereken_baslangic,
            "kk_excel_11_vs_onceki_13": {
                "excel": 11,
                "onceki": 13,
                "excelde_olmayan": len(kk_excel_disi),
            },
            "kmh_excel_2": 2,
            "ronesans_hisse": True,
            "k05": False,
            "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_BANKA_TOPLAMI_EXCEL.json",
            "sonraki_rapor": sonraki_rapor["gerekli"],
        },
    )

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                f"Banka Toplamı Excel eklendi (01.06.2025–31.08.2026, 42178). "
                f"30 hesap; sayac={dict(sayac)}. "
                f"Önceki hareket en eski={en_eski_kaynak}; dönem neti kapanış değil. "
                f"KK 11 vs önceki 13. K05 kapalı. Devir2 öğleden sonra."
            ),
            "k05": False,
            "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
            "banka_excel": "BANKA_TOPLAMI_EXCEL_OZET.json",
            "mali_yazim": False,
            "exe": False,
        }
    )
    yaz_json(durum_yol, durum)

    print(
        json.dumps(
            {
                "excel": len(excel_rows),
                "sayac": dict(sayac),
                "en_eski": en_eski_kaynak.isoformat() if en_eski_kaynak else None,
                "gereken_bas": gereken_baslangic,
                "kk_eksik_onceki": len(kk_excel_disi),
                "k05": False,
            },
            ensure_ascii=False,
        )
    )
    for h in hesap_sonuclar:
        hid_s = str(h.get("kaynak_hesap_id") or "?")
        print(f"{hid_s:>5} {h['sonuc']:<28} {h['excel_adi'][:45]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
