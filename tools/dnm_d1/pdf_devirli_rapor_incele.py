"""Rapor_Teklif.pdf (Müşteri Hesap Toplamı Tarih Devirli) → Devir1 kanıt.

İsimle kesin eşleme/birleştirme yapmaz; PDF satır + kaynak cari ayrı tutulur.
Kapanış üretmek için Devir+Dönem toplamaz (örtüşme kanıtlanmadan).
K05 açmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.pdf_devirli_rapor_incele
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pymupdf

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK

PDF_KAYNAK = Path.home() / "Downloads" / "Rapor_Teklif.pdf"
PDF_HEDEF = KAYNAK / "pdf" / "Rapor_Teklif_D1_20260831.pdf"

# sütun x sınırları (sayfa ölçümü)
X_ADI = (0, 285)
X_DONEM_BORC = (285, 350)
X_DONEM_ALACAK = (350, 445)
X_DEVIR_BORC = (445, 520)
X_DEVIR_ALACAK = (520, 700)

PARA = re.compile(r"^₺?\s*-?[\d.]+,\d{2}$")
RISK22 = {
    "1368",
    "1911",
    "1980",
    "9197",
    "9198",
    "9199",
    "9205",
    "9206",
    "9207",
    "9213",
    "9229",
    "9230",
    "9231",
    "9234",
    "9235",
    "9236",
    "9240",
    "9242",
    "9246",
    "9247",
    "9250",
    "9251",
}


def _norm_ad(s: str) -> str:
    s = (s or "").upper().replace("İ", "I").replace("ı", "I")
    for a, b in (("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _para(s: str | None) -> Decimal | None:
    if s is None or str(s).strip() == "":
        return None
    t = str(s).strip().replace("₺", "").replace(" ", "")
    # TR: 1.234,56
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _col(x0: float) -> str:
    if X_ADI[0] <= x0 < X_ADI[1]:
        return "adi"
    if X_DONEM_BORC[0] <= x0 < X_DONEM_BORC[1]:
        return "donem_borc"
    if X_DONEM_ALACAK[0] <= x0 < X_DONEM_ALACAK[1]:
        return "donem_alacak"
    if X_DEVIR_BORC[0] <= x0 < X_DEVIR_BORC[1]:
        return "devir_borc"
    if X_DEVIR_ALACAK[0] <= x0 < X_DEVIR_ALACAK[1]:
        return "devir_alacak"
    return "diger"


def _sayfa_satirlari(page: pymupdf.Page, sayfa_no: int) -> list[dict[str, Any]]:
    words = page.get_text("words")
    # y bandına grupla (header sonrası)
    rows: dict[int, list] = {}
    for w in words:
        x0, y0, x1, y1, text, *_ = w
        if y0 < 95:  # başlık
            continue
        if text in ("DNM-", "RAY", "MOBİLYA", "AKSESUARLAR", "ETÜD", "Firma", ":", "Başlangıç", "Bitiş", "T."):
            continue
        key = int(round(y0 / 2) * 2)  # ~2pt bucket
        rows.setdefault(key, []).append((x0, text))

    out: list[dict[str, Any]] = []
    for y in sorted(rows):
        cells = {"adi": [], "donem_borc": [], "donem_alacak": [], "devir_borc": [], "devir_alacak": [], "diger": []}
        for x0, text in sorted(rows[y], key=lambda t: t[0]):
            cells[_col(x0)].append(text)
        adi = " ".join(cells["adi"]).strip()
        # tarih satırları / boş
        if not adi and not any(cells[k] for k in ("donem_borc", "donem_alacak", "devir_borc", "devir_alacak")):
            continue
        if adi in ("Müşteri Adı", "Dönem Borç", "Dönem Alacak", "Devir Borç", "Devir Alacak"):
            continue
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", adi or ""):
            continue

        def cell_amt(parts: list[str]) -> str | None:
            if not parts:
                return None
            joined = "".join(parts).strip()
            if PARA.match(joined) or PARA.match(joined.replace(" ", "")):
                return joined
            # parçalı ₺ 1 . 234 , 00
            raw = "".join(parts)
            if "₺" in raw or re.search(r"\d,\d{2}", raw):
                return raw
            return None

        row = {
            "sayfa": sayfa_no,
            "y": y,
            "musteri_adi_pdf": adi or None,
            "donem_borc": cell_amt(cells["donem_borc"]),
            "donem_alacak": cell_amt(cells["donem_alacak"]),
            "devir_borc": cell_amt(cells["devir_borc"]),
            "devir_alacak": cell_amt(cells["devir_alacak"]),
            "ham_adi_parca": cells["adi"],
            "bos_hucre": {
                "donem_borc": cell_amt(cells["donem_borc"]) is None,
                "donem_alacak": cell_amt(cells["donem_alacak"]) is None,
                "devir_borc": cell_amt(cells["devir_borc"]) is None,
                "devir_alacak": cell_amt(cells["devir_alacak"]) is None,
            },
        }
        # yalnız tutar satırı (adı bir üstte) — atlama: ad yoksa öncekiyle birleştirme YAPMA
        if not row["musteri_adi_pdf"]:
            row["musteri_adi_pdf"] = None
            row["adi_yok_uyari"] = True
        out.append(row)
    return out


def _yukle_cari() -> list[dict]:
    p = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI.json"
    return json.loads(p.read_text(encoding="utf-8")).get("kayitlar") or []


def _yukle_cari22() -> dict[str, dict]:
    p = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_CARI22_KAPANIS_KANIT.json"
    if not p.is_file():
        return {}
    return {str(c["kaynak_cari_id"]): c for c in (json.loads(p.read_text(encoding="utf-8")).get("cariler") or [])}


def _cari_ad_indeks(kayitlar: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for r in kayitlar:
        cid = str(r.get("R.a_id") or "")
        ad = (r.get("text") or "").split("----")[0].strip() or str(r.get("R.a_ad") or "")
        kod = r.get("R.a_kod")
        item = {"kaynak_cari_id": cid, "kod": kod, "unvan": ad, "norm": _norm_ad(ad)}
        idx.setdefault(item["norm"], []).append(item)
    return idx


def main() -> int:
    PDF_HEDEF.parent.mkdir(parents=True, exist_ok=True)
    if PDF_KAYNAK.is_file():
        shutil.copy2(PDF_KAYNAK, PDF_HEDEF)
    if not PDF_HEDEF.is_file():
        raise SystemExit(f"PDF yok: {PDF_HEDEF}")

    ham = PDF_HEDEF.read_bytes()
    sha = hashlib.sha256(ham).hexdigest().upper()
    PDF_HEDEF.with_suffix(".pdf.sha256").write_text(f"{sha}  {PDF_HEDEF.name}\n", encoding="ascii")

    doc = pymupdf.open(PDF_HEDEF)
    tum: list[dict] = []
    for i in range(doc.page_count):
        tum.extend(_sayfa_satirlari(doc.load_page(i), i + 1))

    # Adı olan satırlar = rapor cari satırı
    adi_olan = [r for r in tum if r.get("musteri_adi_pdf")]
    adi_yok = [r for r in tum if not r.get("musteri_adi_pdf")]

    kayitlar = _yukle_cari()
    idx = _cari_ad_indeks(kayitlar)
    cari22 = _yukle_cari22()

    # İsim eşleme: yalnız aday listesi; kesin birleştirme yok
    eslesme = []
    for r in adi_olan:
        n = _norm_ad(r["musteri_adi_pdf"])
        adaylar = idx.get(n) or []
        # kısmi aday (içerir) — yalnızca bilgi; birleştirme değil
        kismi = []
        if not adaylar:
            for kn, items in idx.items():
                if n and (n in kn or kn in n):
                    kismi.extend(items)
                    if len(kismi) > 5:
                        break
        eslesme.append(
            {
                **r,
                "norm_ad": n,
                "aday_tam_adet": len(adaylar),
                "aday_tam": adaylar,
                "aday_kismi_adet": len(kismi),
                "aday_kismi": kismi[:5],
                "kesin_eslesme": False,  # politika: PDF'de ID yok → kesin eşleme yok
                "birlestirme_yapilmadi": True,
            }
        )

    tam1 = sum(1 for e in eslesme if e["aday_tam_adet"] == 1)
    tam0 = sum(1 for e in eslesme if e["aday_tam_adet"] == 0)
    tamN = sum(1 for e in eslesme if e["aday_tam_adet"] > 1)

    # Devir vs Dönem örtüşme örnekleri (sayısal)
    ornek_iliski = []
    for e in eslesme:
        db, da = _para(e.get("donem_borc")), _para(e.get("donem_alacak"))
        vb, va = _para(e.get("devir_borc")), _para(e.get("devir_alacak"))
        if None not in (db, da, vb, va):
            ornek_iliski.append(
                {
                    "adi": e["musteri_adi_pdf"],
                    "sayfa": e["sayfa"],
                    "donem_borc": str(db),
                    "donem_alacak": str(da),
                    "devir_borc": str(vb),
                    "devir_alacak": str(va),
                    "donem_net": str(db - da),
                    "devir_net": str(vb - va),
                    "devir_eq_donem": vb == db and va == da,
                    "devir_net_eq_donem_net": (vb - va) == (db - da),
                }
            )
        if len(ornek_iliski) >= 40:
            break

    eq_full = sum(1 for o in ornek_iliski if o["devir_eq_donem"])
    # Tüm satırlarda ilişki özeti
    n_both4 = 0
    n_devir_eq_donem = 0
    n_devir_only = 0
    n_donem_only = 0
    n_all_empty = 0
    for e in eslesme:
        db, da = _para(e.get("donem_borc")), _para(e.get("donem_alacak"))
        vb, va = _para(e.get("devir_borc")), _para(e.get("devir_alacak"))
        donem_var = db is not None or da is not None
        devir_var = vb is not None or va is not None
        if not donem_var and not devir_var:
            n_all_empty += 1
        elif donem_var and not devir_var:
            n_donem_only += 1
        elif devir_var and not donem_var:
            n_devir_only += 1
        else:
            n_both4 += 1
            if db is not None and da is not None and vb is not None and va is not None and db == vb and da == va:
                n_devir_eq_donem += 1

    # 22 risk — PDF satır adayları (isim; kesin ID yok)
    risk_rapor = []
    cari_by_id = {
        str(r.get("R.a_id")): {
            "kod": r.get("R.a_kod"),
            "unvan": ((r.get("text") or "").split("----")[0].strip() or r.get("R.a_ad")),
        }
        for r in kayitlar
    }
    for cid in sorted(RISK22, key=int):
        meta = cari_by_id.get(cid) or {}
        unvan = meta.get("unvan") or ""
        n = _norm_ad(unvan)
        pdf_hits = [e for e in eslesme if e["norm_ad"] == n]
        # özel isimler
        if cid == "1368":
            pdf_hits = [e for e in eslesme if "ERKHAN" in (e["musteri_adi_pdf"] or "").upper()]
        if cid == "1911":
            pdf_hits = [e for e in eslesme if "MERT" in (e["musteri_adi_pdf"] or "").upper() and "FERFORJE" in (e["musteri_adi_pdf"] or "").upper()]
        if cid == "1980":
            pdf_hits = [e for e in eslesme if "MURAT APAK" in (e["musteri_adi_pdf"] or "").upper()]

        k22 = cari22.get(cid) or {}
        hit = pdf_hits[0] if len(pdf_hits) == 1 else None
        cok = len(pdf_hits) > 1

        gorunen = None
        if hit:
            gorunen = {
                "donem_borc": hit.get("donem_borc"),
                "donem_alacak": hit.get("donem_alacak"),
                "devir_borc": hit.get("devir_borc"),
                "devir_alacak": hit.get("devir_alacak"),
                "bos_hucre": hit.get("bos_hucre"),
                "sayfa": hit.get("sayfa"),
                "pdf_adi": hit.get("musteri_adi_pdf"),
            }

        # 1980 özel: Devir 1095/10 = dönem hareket / özet; 1085 ikinci açılış değil
        notlar = []
        kapanis_dogrulanmis = k22.get("kapanis_bakiye_3108_kanitli")
        kanit = k22.get("kanit_durumu") or "PDF_ISIM_ADAY_KESIN_DEGIL"
        if cid == "1980" and hit:
            vb, va = _para(hit.get("devir_borc")), _para(hit.get("devir_alacak"))
            db, da = _para(hit.get("donem_borc")), _para(hit.get("donem_alacak"))
            notlar.append(
                "PDF Devir B/A 1095/10 kaynak Detay dönem borc/alacak ve Özet ile aynı yönde; "
                "1085=1095-10 net/kapanış — ikinci açılış/devir olarak EKLENMEDİ"
            )
            if vb == Decimal("1095") and va == Decimal("10"):
                notlar.append("PDF Devir sütunu 1980 finans_jq borc/alacak (1095/10) ile örtüşüyor")
            if db is None and da is None:
                notlar.append("PDF Dönem sütunları boş; Devir sütunları dolu — Devir≠Dönem kanıtı bu satırda")
            kanit = k22.get("kanit_durumu") or "SON_DETAY_BAKIYE_<=31.08"
        if hit and all(hit["bos_hucre"].values()):
            notlar.append(
                "PDF tüm tutar hücreleri boş — gösterimde boş≠kanıtlı sıfır; sıfır yazılmadı"
            )
            kapanis_dogrulanmis = None
            if kanit.startswith("SON_"):
                pass
            else:
                kanit = "PDF_BOS_HUCRE_SIFIR_YAZILMADI"
        if not hit:
            notlar.append("PDF'de tekil isim satırı yok veya çoklu — ID ile birleştirilmedi")
            kanit = "PDF_ISIM_ESLESMEDI_VEYA_COKLU"
        if cok:
            notlar.append(f"PDF'de aynı norm ad {len(pdf_hits)} satır — birleştirilmedi")

        risk_rapor.append(
            {
                "kaynak_cari_id": cid,
                "kod": meta.get("kod"),
                "unvan_kaynak": unvan,
                "pdf_sayfa": gorunen["sayfa"] if gorunen else None,
                "pdf_gorunen": gorunen,
                "pdf_hit_adet": len(pdf_hits),
                "kapanis_bakiye_3108_kanitli": kapanis_dogrulanmis,
                "kalan_eksik": None
                if kapanis_dogrulanmis is not None
                else "31.08 Detay kanıtı veya PDF satır-ID bağının yokluğu",
                "kanit_durumu": kanit,
                "notlar": notlar,
                "finans_jq_ozet": {
                    "acilis": (k22.get("acilis_devir") or {}).get("bakiye"),
                    "borc": k22.get("borc"),
                    "alacak": k22.get("alacak"),
                    "kapanis": k22.get("kapanis_bakiye_3108_kanitli"),
                    "dogrulanmamis_ozet": k22.get("dogrulanmamis_ozet"),
                }
                if k22
                else None,
            }
        )

    # Adet farkı 1070 vs 1066
    fark_analiz = {
        "pdf_adi_olan_satir": len(adi_olan),
        "pdf_adi_yok_tutar_satir": len(adi_yok),
        "pdf_kullanici_bildirimi_1070": 1070,
        "kaynak_cari_kart_1066": len(kayitlar),
        "fark_1070_minus_1066": 1070 - len(kayitlar),
        "fark_pdf_adi_minus_1066": len(adi_olan) - len(kayitlar),
        "aciklama": (
            "PDF satırında cari ID yok; isimle kesin eşleme/birleştirme yapılmadı. "
            "1070−1066=4 farkı ID ile çözülmeden kart birleştirilmez. "
            "Olası nedenler (kanıt bekler): mükerrer ünvan satırı, kartta olmayan isim, "
            "personel/özel hesap, parse/başlık artığı — aşağıda aday sayıları."
        ),
        "isim_tam_tek_aday": tam1,
        "isim_sifir_aday": tam0,
        "isim_coklu_aday": tamN,
        "sifir_aday_ornek": [
            {"adi": e["musteri_adi_pdf"], "sayfa": e["sayfa"]}
            for e in eslesme
            if e["aday_tam_adet"] == 0
        ][:30],
        "coklu_aday_ornek": [
            {
                "adi": e["musteri_adi_pdf"],
                "sayfa": e["sayfa"],
                "aday_id": [a["kaynak_cari_id"] for a in e["aday_tam"]],
            }
            for e in eslesme
            if e["aday_tam_adet"] > 1
        ][:20],
    }

    bos_anlam = {
        "kural": (
            "Boş hücre rapor gösteriminde tutarın basılmadığı durumdur; "
            "kaynak alan değeri olarak 0 varsayılmaz. "
            "Dönem/Devir için None bırakılır."
        ),
        "kanit": "pdf_bos_hucre_sifir_yazilmadi",
        "tum_bos_satir_adet": n_all_empty,
    }

    devir_anlam = {
        "rapor": "Müşteri Hesap Toplamı Tarih (Devirli) — RAP_MUS002 / mushestop.repx",
        "filtre_tarih": {"bas": "01.09.2025", "bit": "31.08.2026"},
        "sutunlar": ["Dönem Borç", "Dönem Alacak", "Devir Borç", "Devir Alacak"],
        "devir_donem_iliski_ozet": {
            "adi_olan_satir": len(adi_olan),
            "donem_ve_devir_dolu": n_both4,
            "yalniz_donem": n_donem_only,
            "yalniz_devir": n_devir_only,
            "hepsi_bos": n_all_empty,
            "devir_esit_donem_tam_eslesme_adet": n_devir_eq_donem,
            "ornek_iliski_adet": len(ornek_iliski),
            "ornek_devir_eq_donem": eq_full,
        },
        "sonuc": (
            "Devir Borç/Alacak, Dönem Borç/Alacak ile özdeş değil (çoğu satırda farklı veya "
            "yalnız biri dolu). Bu yüzden Devir+Dönem toplanarak kapanış ÜRETİLMEDİ. "
            "MURAT APAK örneğinde PDF Devir B/A, finans_jq dönem borc/alacak (1095/10) ile "
            "aynı yönde; net 1085 ikinci açılış olarak eklenmedi."
        ),
        "kapanis_uretildi_mi": False,
        "ornekler": ornek_iliski[:15],
    }

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    out = {
        "format": "d1-pdf-musteri-hesap-devirli-v1",
        "zaman": now,
        "donem_sonu_dahil": "2026-08-31",
        "devir": 1,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
        "pdf": {
            "yol": str(PDF_HEDEF.relative_to(CALISMA)).replace("\\", "/"),
            "sha256": sha,
            "sayfa_adet": doc.page_count,
            "boyut_bayt": len(ham),
            "baslik_tarih": {"baslangic": "01.09.2025", "bitis": "31.08.2026"},
            "firma": "DNM- RAY MOBİLYA AKSESUARLAR ETÜD",
        },
        "satir_sayimi": fark_analiz,
        "bos_hucre": bos_anlam,
        "devir_sutun_anlami": devir_anlam,
        "risk22": risk_rapor,
        "risk22_ozet": {
            "adet": len(risk_rapor),
            "pdf_tek_hit": sum(1 for r in risk_rapor if r["pdf_hit_adet"] == 1),
            "kanitli_kapanis": sum(
                1 for r in risk_rapor if r.get("kapanis_bakiye_3108_kanitli") is not None
            ),
        },
        "uyari": (
            "Bu toplam rapor açık fatura / vade / kapatma ayrıntısının yerine kullanılmaz."
        ),
        "k05": False,
        "mali_yazim": False,
        "pdf_satirlari_ham_adet": len(tum),
        "pdf_satirlari_ornek": adi_olan[:5] + [e for e in adi_olan if e.get("musteri_adi_pdf") and "ERKHAN" in e["musteri_adi_pdf"].upper()][:1],
    }

    # sürümlü: önceki varsa surumler altına kopyala
    onceki = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_PDF_DEVIRLI_RAPOR.json"
    if onceki.is_file():
        surum = CALISMA / "surumler" / f"pdf_devirli_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        surum.mkdir(parents=True, exist_ok=True)
        shutil.copy2(onceki, surum / onceki.name)

    yaz_kaynak("DOGRULAMA_PDF_DEVIRLI_RAPOR", out)

    # CARI22 özetine PDF bağla (sürümlü yedek)
    ozet_yol = CALISMA / "CARI22_KAPANIS_KANIT_OZET.json"
    if ozet_yol.is_file():
        surum2 = CALISMA / "surumler" / f"cari22_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        surum2.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ozet_yol, surum2 / ozet_yol.name)
        ozet = json.loads(ozet_yol.read_text(encoding="utf-8"))
        ozet["pdf_devirli"] = {
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
            "pdf": out["pdf"]["yol"],
            "sha256": sha,
            "zaman": now,
        }
        ozet["k05"] = False
        yaz_json(ozet_yol, ozet)

    # DURUM
    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                f"PDF Devirli eklendi ({doc.page_count}s). "
                f"PDF ad satır={len(adi_olan)} / kart=1066; isimle birleştirilmedi. "
                f"Risk22 PDF tek hit={out['risk22_ozet']['pdf_tek_hit']}; "
                f"kanıtlı kapanış={out['risk22_ozet']['kanitli_kapanis']}. "
                f"Devir+Dönem toplanmadı. K05 kapalı. Devir2 öğleden sonra."
            ),
            "k05": False,
            "k06": False,
            "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
            "pdf_devirli": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
            "kullanici_adimi_gerekli": [
                "1070−1066 farkı için PDF satır↔ID eşlemesi (isimle birleştirme yok)",
                "21 kanıtsız cari Detay/ekstre",
                "Devir2 öğleden sonra",
            ],
        }
    )
    yaz_json(durum_yol, durum)

    ozet_kisa = {
        "zaman": now,
        "pdf_sayfa": doc.page_count,
        "pdf_adi_satir": len(adi_olan),
        "kart": len(kayitlar),
        "risk22_tek_hit": out["risk22_ozet"]["pdf_tek_hit"],
        "kanitli": out["risk22_ozet"]["kanitli_kapanis"],
        "k05": False,
        "devir_toplandi_mi": False,
        "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
    }
    yaz_json(CALISMA / "PDF_DEVIRLI_RAPOR_OZET.json", ozet_kisa)
    print(json.dumps(ozet_kisa, ensure_ascii=False))
    # risk22 kısa tablo
    for r in risk_rapor:
        g = r.get("pdf_gorunen") or {}
        print(
            f"id={r['kaynak_cari_id']:>5} s={str(r.get('pdf_sayfa')):>3} "
            f"DB={g.get('devir_borc')} DA={g.get('devir_alacak')} "
            f"dB={g.get('donem_borc')} dA={g.get('donem_alacak')} "
            f"kap={r.get('kapanis_bakiye_3108_kanitli')} {r['kanit_durumu'][:40]}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
