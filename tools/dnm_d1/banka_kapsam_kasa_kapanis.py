"""Banka kart∪hareket birleşimi (32) + 2030/Halkbank + kasa 2 hesap kapanış.

Vakıfbank / AKBANK 4355 valör kanıtlarına dokunmaz.
K05 / mali yazım / EXE / düzeltme fişi yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.banka_kapsam_kasa_kapanis
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar

FILTRE_BANKA_EXCEL = date(2025, 6, 1)
GUNLUK_ID = "2030"
HALKBANK_KK = ("12", "1018")
AKBANK_4355_IDS = ("19000", "18997", "18983", "18980", "18938")
KURUS = Decimal("0.01")


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS)


def _devir_mi(ack: Any) -> bool:
    return bool(re.search(r"devir", str(ack or ""), re.I))


def _sayim_mi(ack: Any) -> bool:
    return bool(re.search(r"say[iı]m", str(ack or ""), re.I))


def main() -> int:
    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    banka_bas = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA_BASLANGIC.json").read_text(encoding="utf-8")
    )
    banka_excel = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_BANKA_TOPLAMI_EXCEL.json").read_text(
            encoding="utf-8"
        )
    )
    vakif = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_VAKIFBANK_EKSTRE_EXCEL.json").read_text(
            encoding="utf-8"
        )
    )
    akbank4355 = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_AKBANK_4355_POS_VALOR_D2.json").read_text(
            encoding="utf-8"
        )
    )
    kasa = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA.json").read_text(encoding="utf-8"))
    kasa_bas = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA_BASLANGIC.json").read_text(encoding="utf-8")
    )
    kasa_kap = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA_KAPANIS.json").read_text(encoding="utf-8")
    )

    # --- 1) Kart ∪ hareket ---
    kartlar = list(banka.get("kartlar") or [])
    hareketler = list(banka.get("hareketler") or [])
    kart_ids = {str(k["id"]) for k in kartlar}
    har_ids = {
        str(h.get("G.a_banka_id"))
        for h in hareketler
        if h.get("G.a_banka_id") not in (None, "")
    }
    union = kart_ids | har_ids
    only_kart = sorted(kart_ids - har_ids, key=lambda x: int(x))
    only_har = sorted(har_ids - kart_ids, key=lambda x: int(x))
    excel_30 = len(banka_excel.get("hesaplar") or [])

    adi_by_id: dict[str, str] = {}
    for k in kartlar:
        adi_by_id[str(k["id"])] = str(k.get("text") or "")
    for h in hareketler:
        hid = str(h.get("G.a_banka_id") or "")
        if hid and hid not in adi_by_id:
            adi_by_id[hid] = str(h.get("TBL_BANKA.a_adi") or hid)

    birlesim = {
        "kartlar_listesi_adet": len(kart_ids),
        "hareketlerdeki_hesap_id_adet": len(har_ids),
        "birlesim_tekil_hesap_adet": len(union),
        "kesin_tekil_hesap_sayisi": len(union),
        "kartlarda_var_harekette_yok": [
            {"id": i, "adi": adi_by_id.get(i), "not": "Hareket 0 — kapanış=0 sayılmaz"}
            for i in only_kart
        ],
        "harekette_var_kartlarda_yok": [
            {"id": i, "adi": adi_by_id.get(i), "not": "Kart listesi 31 eksik; birleşime dahil"}
            for i in only_har
        ],
        "birlesim_idler": sorted(union, key=lambda x: int(x)),
        "excel_30_tam_kapsam_degil": True,
        "excel_hesap_adet": excel_30,
        "aciklama": (
            f"Kartlar={len(kart_ids)}, hareket ID={len(har_ids)}, birleşim={len(union)}. "
            f"Excel Banka Toplamı {excel_30} satır ≠ kaynak tekil hesap ({len(union)})."
        ),
    }

    # --- 2) 2030 ---
    h2030 = [h for h in hareketler if str(h.get("G.a_banka_id")) == GUNLUK_ID]
    g2030 = c2030 = Decimal("0")
    satirlar_2030 = []
    for h in sorted(h2030, key=lambda x: parse_tarih(x.get("G.a_tarih")) or date.min):
        t = parse_tarih(h.get("G.a_tarih"))
        gg, cc = _yon_tutar(h)
        if t and t <= DONEM_SONU:
            g2030 += gg or Decimal("0")
            c2030 += cc or Decimal("0")
        satirlar_2030.append(
            {
                "G.a_id": h.get("G.a_id"),
                "tarih": t.isoformat() if t else None,
                "valor": parse_tarih(h.get("G.a_vtarih")).isoformat()
                if parse_tarih(h.get("G.a_vtarih"))
                else None,
                "tur": h.get("FIN_TUR.a_adi"),
                "giren": str(gg or 0),
                "cikan": str(cc or 0),
                "doviz": h.get("FIN_DOV.a_kod"),
                "mkb": (str(h.get("MKB") or "").strip() or None),
                "kontrol": h.get("G.a_kontrol"),
                "hesap_adi_satir": h.get("TBL_BANKA.a_adi"),
            }
        )
    excel_gunluk = next(
        (
            h
            for h in (banka_excel.get("hesaplar") or [])
            if "GUNLUK" in (h.get("excel_adi") or "").upper().replace("Ü", "U").replace("İ", "I")
            or "VADEL" in (h.get("excel_adi") or "").upper()
        ),
        None,
    )
    bb2030 = next(
        (
            h
            for h in (banka_bas.get("hesaplar") or [])
            if str(h.get("kaynak_hesap_id")) == GUNLUK_ID
        ),
        None,
    )
    esleme_2030 = {
        "kaynak_hesap_id": GUNLUK_ID,
        "kaynak_adi": "01 AKBANK GÜNLÜK VADELİ HESAP",
        "doviz": "TL",
        "kartlar_31_listesinde": GUNLUK_ID in kart_ids,
        "hareket_adet": len(h2030),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "donem_ici_giren": str(g2030),
        "donem_ici_cikan": str(c2030),
        "donem_ici_net_hareket": str(g2030 - c2030),
        "excel_esleme": {
            "excel_adi": (excel_gunluk or {}).get("excel_adi"),
            "excel_giren": ((excel_gunluk or {}).get("excel") or {}).get("giren"),
            "excel_cikan": ((excel_gunluk or {}).get("excel") or {}).get("cikan"),
            "excel_toplam": ((excel_gunluk or {}).get("excel") or {}).get("toplam"),
            "giren_kurus_esit": excel_gunluk is not None
            and _q2(g2030)
            == _q2(_dec(((excel_gunluk or {}).get("excel") or {}).get("giren")) or Decimal("0")),
            "cikan_kurus_esit": excel_gunluk is not None
            and _q2(c2030)
            == _q2(_dec(((excel_gunluk or {}).get("excel") or {}).get("cikan")) or Decimal("0")),
            "onceki_esleme_yok_adi_kartlarda_yoktu": True,
            "simdi_kaynak_id": GUNLUK_ID,
        },
        "banka_baslangic": bb2030,
        "acilis_devir": {
            "ilk_hareket": "2026-06-16",
            "devir_ack_belge_adet": (bb2030 or {}).get("devir_belge_adet", 0),
            "onceki_bakiye_kaniti": "YOK — net 0 hareket sonucudur; ayrı açılış belgesi yok",
        },
        "hareketler": satirlar_2030,
        "donem_sonu_durum": {
            "hareket_neti": str(g2030 - c2030),
            "kapanis_0_hareketten": _q2(g2030 - c2030) == Decimal("0"),
            "not": "31.08 hareket neti 0; kart kaydı olmadığı için kart bakiyesi ayrı doğrulanamadı",
        },
    }

    # --- Halkbank 12 / 1018 ---
    halkbank = []
    for hid in HALKBANK_KK:
        kart = next((k for k in kartlar if str(k["id"]) == hid), None)
        har = [h for h in hareketler if str(h.get("G.a_banka_id")) == hid]
        bb = next(
            (h for h in (banka_bas.get("hesaplar") or []) if str(h.get("kaynak_hesap_id")) == hid),
            None,
        )
        halkbank.append(
            {
                "kaynak_hesap_id": hid,
                "kaynak_adi": (kart or {}).get("text"),
                "doviz": (kart or {}).get("DOV_Kodu"),
                "a_posmu": (kart or {}).get("a_posmu"),
                "a_kod": (kart or {}).get("a_kod"),
                "kartlarda": kart is not None,
                "hareket_adet": len(har),
                "banka_baslangic_kaydi": bb,
                "excel_satiri": "YOK",
                "sifir_kapanis_sayilmaz": True,
                "acilis_devir_borcu": {
                    "durum": "BELIRSIZ",
                    "gerekce": (
                        "Hareket yok ≠ kapanış bakiyesi 0. Kartta bakiye alanı yok; "
                        "BANKA_BASLANGIC’ta yok; gerçek açılış/devir borcu için "
                        "hesap ekstresi / devirli kart bakiyesi gerekir."
                    ),
                    "istenir": [
                        "Kart bakiyesi (devirli) 31.08.2026",
                        "Varsa açılış/devir fişi",
                        "Dönem hareketi 0 teyidi",
                    ],
                },
                "korundu": True,
            }
        )

    # --- 3) AKBANK 4355 izleme (mevcut kanıt referansı; komisyon neti yok) ---
    akbank_izleme = {
        "mevcut_kanit_korundu": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_AKBANK_4355_POS_VALOR_D2.json",
        "vakifbank_korundu": {
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_VAKIFBANK_EKSTRE_EXCEL.json",
            "kapanis_tamam": bool((vakif.get("kapanis_kontrolu") or {}).get("tamam")),
            "degistirilmedi": True,
        },
        "tutar": "4355",
        "G.a_id": list(AKBANK_4355_IDS),
        "rol_3108": "BEKLEYEN_BLOKELI_POS (kontrol=Beklemede, pos_bloke=1, valor_bekleyen)",
        "komisyon": {
            "net_hesaplanmadi": True,
            "gerekce": "G.a_komisyon anlamı (oran/tutar) doğrulanmadan banka ödeme neti üretilmez",
        },
        "d2": {
            "valor_tarihi_01_09_tek_basina_fiili_cozulme_degil": True,
            "gerekli_kanit": (
                "Aynı G.a_id için kaynakta valör günü sonrası gerçek bankaya geçiş "
                "(kontrol/pos_bloke değişimi veya banka görünümü) — henüz D2 doğrulaması yok"
            ),
            "ikinci_tahsilat_veya_satis_olusturulmaz": True,
            "yalniz_valor_ile_yeni_hareket_yazilmaz": True,
        },
        "onceki_bulgular_ozet": (akbank4355.get("bulgular") if False else None)
        or (akbank4355.get("durum_3108") or {}).get("ozet"),
    }

    # --- 4) Kasa 2 hesap ---
    kasa_kart = {str(k["id"]): k for k in (kasa.get("kartlar") or [])}
    kasa_har = list(kasa.get("hareketler") or [])
    kasa_sonuclar = []
    en_eski_gerekli = None

    for kid in ("1", "2"):
        kart = kasa_kart.get(kid) or {}
        rows = [h for h in kasa_har if str(h.get("G.a_kasa_id")) == kid]
        g = c = Decimal("0")
        g_dev = c_dev = Decimal("0")
        n = n_dev = 0
        tarihler = []
        for h in rows:
            t = parse_tarih(h.get("G.a_tarih"))
            if t is None:
                continue
            if t > DONEM_SONU:
                continue
            tarihler.append(t)
            gg, cc = _yon_tutar(h)
            g += gg or Decimal("0")
            c += cc or Decimal("0")
            n += 1
            if _devir_mi(h.get("G.a_ack")):
                g_dev += gg or Decimal("0")
                c_dev += cc or Decimal("0")
                n_dev += 1
        ilk = min(tarihler) if tarihler else None
        if ilk and (en_eski_gerekli is None or ilk < en_eski_gerekli):
            en_eski_gerekli = ilk

        bas_kayit = next(
            (
                h
                for h in (kasa_bas.get("hesaplar") or [])
                if str(h.get("kaynak_hesap_id")) == kid
            ),
            None,
        )
        kap_kayit = next(
            (h for h in (kasa_kap.get("hesaplar") or []) if str(h.get("hesap_id")) == kid),
            None,
        )

        # İlk gün hareketleri
        ilk_gun = []
        if ilk:
            for h in rows:
                t = parse_tarih(h.get("G.a_tarih"))
                if t == ilk:
                    gg, cc = _yon_tutar(h)
                    ilk_gun.append(
                        {
                            "G.a_id": h.get("G.a_id"),
                            "ack": h.get("G.a_ack"),
                            "tur": h.get("FIN_TUR.a_adi"),
                            "giren": str(gg or 0),
                            "cikan": str(cc or 0),
                            "devir_ack": _devir_mi(h.get("G.a_ack")),
                            "sayim_ack": _sayim_mi(h.get("G.a_ack")),
                        }
                    )

        kasa_sonuclar.append(
            {
                "hesap_id": kid,
                "hesap_adi": kart.get("text") or (kap_kayit or {}).get("hesap_adi"),
                "doviz": kart.get("doviz_kodu") or "TL",
                "ilk_gerekli_hareket_tarihi": ilk.isoformat() if ilk else None,
                "son_hareket_tarihi": max(tarihler).isoformat() if tarihler else None,
                "donem_sonu": DONEM_SONU.isoformat(),
                "giris": str(g),
                "cikis": str(c),
                "kapanis_hareket_neti": str(g - c),
                "hareket_adet": n,
                "devir_ack_ozet": {
                    "adet": n_dev,
                    "giren": str(g_dev),
                    "cikan": str(c_dev),
                    "net": str(g_dev - c_dev),
                    "not": (
                        "Açıklamasında DEVİR geçen hareketlerin toplamı; "
                        "tek satırlı resmi açılış bakiyesi belgesi değildir"
                    ),
                },
                "ilk_gun_hareketleri": ilk_gun[:20],
                "ilk_gun_adet": len(ilk_gun),
                "baslangic_kaynak": {
                    "ilk_hareket_tarih": (bas_kayit or {}).get("ilk_hareket_tarih"),
                    "ilk_hareket_ack": (bas_kayit or {}).get("ilk_hareket_ack"),
                    "ilk_hareket_net": (bas_kayit or {}).get("ilk_hareket_net"),
                    "devir_belge_adet": (bas_kayit or {}).get("devir_belge_adet"),
                },
                "onceki_kapanis_raporu_net": (kap_kayit or {}).get("kapanis_net"),
                "kapanis_raporu_ile_esit": kap_kayit is not None
                and _q2(g - c) == _q2(_dec(kap_kayit.get("kapanis_net")) or Decimal("0")),
                "gercek_acilis_devir": {
                    "durum": "KISMI",
                    "kanit": (
                        "Ham KASA hareketlerinde DEVİR/SAYIM etiketli kayıtlar var; "
                        "resmi Kasa Toplamı / tarihli ekstre yok"
                    ),
                    "tek_acilis_bakiyesi_yok": True,
                },
                "kapanis_kontrolu_tamam": False,
                "neden_tamam_degil": (
                    "Hareket neti hesaplandı; resmi kasa ekstresi / Kasa Toplamı "
                    "Giren-Çıkan-Toplam ile çapraz yok; açılış tek bakiyesi belgesiz"
                ),
            }
        )

    eksik_kasa_raporu = {
        "gerekli": True,
        "menu_yolu_dogrulanmis_kardes": (
            "Raporlar → Finans Raporları → Ekstreler → Kasa Toplamı "
            "(Banka Toplamı ile aynı Ekstreler ekranı; Banka yolu Devir1’de doğrulandı)"
        ),
        "alternatif": "Raporlar → Finans Raporları → Ekstreler → hesap bazlı Kasa ekstresi",
        "rapor_uid_ipucu": "rap_fin_002 (UI’de Kasa/Banka ekstresi)",
        "tarihler": {
            "NAKİT_KASA_baslangic_onerisi": "2025-07-28",
            "YC_KASA_baslangic_onerisi": "2025-12-25",
            "ortak_baslangic_guvenli": en_eski_gerekli.isoformat() if en_eski_gerekli else None,
            "bitis": DONEM_SONU.isoformat(),
            "not": (
                "Her kasa için ilk hareket tarihinden (veya bilinen açılıştan) "
                "31.08.2026’ya kadar; daha kısa aralık açılışı keser"
            ),
        },
        "istenilen_alanlar": [
            "Kasa Adı / hesap kimliği",
            "Giren",
            "Çıkan",
            "Toplam / bakiye",
            "Döviz",
            "Mümkünse açılış/devir bakiyesi veya önceki durum satırı",
            "Firma 42178 teyidi",
        ],
        "hesaplar": ["NAKİT KASA (id=1)", "YÇ KASA (id=2)"],
    }

    kanit = {
        "format": "d1-banka-kapsam-kasa-kapanis-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "korunan_kanitlar": {
            "vakifbank": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_VAKIFBANK_EKSTRE_EXCEL.json",
            "akbank_4355_pos_valor": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_AKBANK_4355_POS_VALOR_D2.json",
            "degistirilmedi": True,
        },
        "banka_hesap_birlesimi": birlesim,
        "hesap_2030_gunluk_vadeli": esleme_2030,
        "halkbank_kk_12_1018": halkbank,
        "akbank_4355_izleme": akbank_izleme,
        "kasa_kapanis_kontrol": {
            "hesap_adet": 2,
            "en_eski_gerekli_hareket": en_eski_gerekli.isoformat() if en_eski_gerekli else None,
            "hesaplar": kasa_sonuclar,
            "durum": "KISMI_HAREKET_NETI_RESMİ_EKSTRE_YOK",
            "eksik_kaynak_raporu": eksik_kasa_raporu,
        },
        "duzeltme_fisi_uretilmedi": True,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_BANKA_KAPSAM_KASA_KAPANIS", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "tekil_banka_hesap": len(union),
        "kart_31": len(kart_ids),
        "hareket_id": len(har_ids),
        "2030_net": str(g2030 - c2030),
        "2030_excel_esit": esleme_2030["excel_esleme"]["giren_kurus_esit"]
        and esleme_2030["excel_esleme"]["cikan_kurus_esit"],
        "halkbank_sifir_sayilmaz": True,
        "kasa_en_eski": en_eski_gerekli.isoformat() if en_eski_gerekli else None,
        "kasa_durum": "KISMI_RESMİ_EKSTRE_YOK",
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "BANKA_KAPSAM_KASA_KAPANIS_OZET.json", ozet)
    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
