"""PDF Devirli kanıt v2 — 1070/1066 aritmetik + risk soft aday (birleştirme yok)."""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime

import pymupdf

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.pdf_devirli_rapor_incele import (
    PDF_HEDEF,
    _norm_ad,
    _para,
    _sayfa_satirlari,
    _yukle_cari,
    _yukle_cari22,
)


def main() -> int:
    p = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_PDF_DEVIRLI_RAPOR.json"
    surum = CALISMA / "surumler" / f"pdf_devirli_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    surum.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, surum / p.name)

    out = json.loads(p.read_text(encoding="utf-8"))
    doc = pymupdf.open(PDF_HEDEF)
    adi: list[dict] = []
    for i in range(doc.page_count):
        adi.extend([r for r in _sayfa_satirlari(doc[i], i + 1) if r.get("musteri_adi_pdf")])
    kay = _yukle_cari()
    cari22 = _yukle_cari22()

    pdf_norms = Counter(_norm_ad(r["musteri_adi_pdf"]) for r in adi)
    kart_by_norm: dict[str, list[str]] = defaultdict(list)
    for r in kay:
        ad = ((r.get("text") or "").split("----")[0].strip() or r.get("R.a_ad") or "")
        kart_by_norm[_norm_ad(ad)].append(str(r.get("R.a_id")))
    kart_norms = Counter({n: len(ids) for n, ids in kart_by_norm.items()})

    pdf_dup_extra = sum(k - 1 for k in pdf_norms.values() if k > 1)
    kart_dup_extra = sum(k - 1 for k in kart_norms.values() if k > 1)
    pdf_only = sorted(set(pdf_norms) - set(kart_norms))
    kart_only = sorted(set(kart_norms) - set(pdf_norms))

    fark = {
        "pdf_satir_1070": len(adi),
        "kart_1066": len(kay),
        "fark_satir": len(adi) - len(kay),
        "pdf_tekil_norm": len(pdf_norms),
        "kart_tekil_norm": len(kart_norms),
        "pdf_mukerrer_ekstra_satir": pdf_dup_extra,
        "kart_mukerrer_unvan_ekstra_id": kart_dup_extra,
        "aritmetik": {
            "aciklama": (
                "satir_farki = (pdf_tekil_norm - kart_tekil_norm) "
                "+ (pdf_mukerrer_ekstra - kart_mukerrer_ekstra)"
            ),
            "tekil_fark": len(pdf_norms) - len(kart_norms),
            "mukerrer_fark": pdf_dup_extra - kart_dup_extra,
            "toplam": (len(pdf_norms) - len(kart_norms)) + (pdf_dup_extra - kart_dup_extra),
        },
        "kart_cift_unvan_id_listesi": [
            {"norm": n, "kaynak_cari_id_ler": ids}
            for n, ids in sorted(kart_by_norm.items())
            if len(ids) > 1
        ],
        "pdf_mukerrer_norm_sayfalar": [
            {
                "norm": n,
                "adet": pdf_norms[n],
                "sayfalar": [r["sayfa"] for r in adi if _norm_ad(r["musteri_adi_pdf"]) == n],
            }
            for n, k in pdf_norms.items()
            if k > 1
        ],
        "pdf_norm_kartta_yok_adet": len(pdf_only),
        "kart_norm_pdfde_yok_adet": len(kart_only),
        "not": (
            "Norm farklarının çoğu MOBİLYA kısalması / yazım; bu ID birleştirmesi değildir. "
            "1070−1066=4 aritmetik: tekil_fark(3)+mukerrer_fark(1)."
        ),
        "birlestirme_yapilmadi": True,
        "kesin_eslesme_isimle_yapilmadi": True,
    }
    out["satir_sayimi"] = {**(out.get("satir_sayimi") or {}), **fark, "guncelleme": "v2_id_aritmetik"}

    soft_map = {
        "9213": [(24, "ÇAĞDAŞ AKSESUARLARI SAN VE TİVC. L")],
        "9247": [(25, "ERTEK TEKERLEK VE AKSESUARLARI")],
        "9207": [(24, "hakan yiğit")],
    }
    for row in out.get("risk22") or []:
        cid = row["kaynak_cari_id"]
        if cid in soft_map and row.get("pdf_hit_adet", 0) != 1:
            row["pdf_isim_aday_kesin_degil"] = [
                {"sayfa": s, "pdf_adi": a} for s, a in soft_map[cid]
            ]
            notes = list(row.get("notlar") or [])
            if cid == "9207":
                notes.append(
                    "PDF hakan yiğit; kart 9207+9208 aynı unvan — ID seçilmeden birleştirilmedi"
                )
                row["kanit_durumu"] = "PDF_ISIM_COKLU_ID_9207_9208"
            elif cid == "9213":
                notes.append(
                    "PDF kısaltılmış aday s24; kaynak unvan daha uzun — kesin ID eşlemesi yok"
                )
                row["pdf_sayfa"] = 24
                row["kanit_durumu"] = "PDF_ISIM_ADAY_KESIN_DEGIL"
            elif cid == "9247":
                notes.append(
                    "PDF ERTEK…AKSESUARLARI s25; kaynak unvanda MOBİLYA ekstra — kesin eşleme yok"
                )
                row["pdf_sayfa"] = 25
                row["kanit_durumu"] = "PDF_ISIM_ADAY_KESIN_DEGIL"
            row["notlar"] = notes

        if cid == "1980":
            g = row.get("pdf_gorunen") or {}
            vb, va = _para(g.get("devir_borc")), _para(g.get("devir_alacak"))
            row["murat_apak_1980"] = {
                "pdf_sayfa": 19,
                "devir_borc": g.get("devir_borc"),
                "devir_alacak": g.get("devir_alacak"),
                "donem_borc": g.get("donem_borc"),
                "donem_alacak": g.get("donem_alacak"),
                "net_1095_minus_10": str(vb - va) if vb is not None and va is not None else None,
                "finans_jq_kapanis_1085": (cari22.get("1980") or {}).get(
                    "kapanis_bakiye_3108_kanitli"
                ),
                "ikinci_acilis_eklendi_mi": False,
                "devir_donem_toplandi_mi": False,
            }

    out["format"] = "d1-pdf-musteri-hesap-devirli-v2"
    out["zaman"] = datetime.now().astimezone().isoformat(timespec="seconds")
    out["devir_2"] = "OGLEDEN_SONRA_BEKLIYOR"
    out["k05"] = False
    yaz_kaynak("DOGRULAMA_PDF_DEVIRLI_RAPOR", out)

    ozet = {
        "zaman": out["zaman"],
        "pdf_satir": 1070,
        "kart": 1066,
        "fark": 4,
        "aritmetik": fark["aritmetik"],
        "devir_toplandi_mi": False,
        "k05": False,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
        "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
        "surum_yedek": str(surum.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(CALISMA / "PDF_DEVIRLI_RAPOR_OZET.json", ozet)

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": out["zaman"],
            "ozet": (
                "PDF Devirli v2: 1070−1066=4 = tekil_norm(+3)+mukerrer(+1); "
                "isimle birleştirilmedi. Devir+Dönem toplanmadı. "
                "1980: PDF Devir 1095/10, kap=1085 ikinci açılış yok. "
                "K05 kapalı. Devir2 öğleden sonra."
            ),
            "k05": False,
            "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
            "pdf_devirli": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIRLI_RAPOR.json",
        }
    )
    yaz_json(durum_yol, durum)
    print(json.dumps(ozet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
