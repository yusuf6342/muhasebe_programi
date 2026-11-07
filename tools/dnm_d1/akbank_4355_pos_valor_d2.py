"""AKBANK 4.355 (5 POS tahsilat) — işlem/valör görünümü, 31.08 rolü, D2 bağı.

Vakıfbank kanıtına dokunmaz. Düzeltme fişi / mali yazım / K05 yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.akbank_4355_pos_valor_d2
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

HEDEF_IDS = ("19000", "18997", "18983", "18980", "18938")
HEDEF_TOPLAM = Decimal("4355")
AKBANK_ID = "1"
FILTRE_BAS = date(2025, 6, 1)
KURUS = Decimal("0.01")
GUNLUK_ID = "2030"
HALKBANK_KK_IDS = ("12", "1018")


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS)


def _norm(s: str) -> str:
    s = (s or "").upper().replace("İ", "I").replace("ı", "I")
    for a, b in (("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _urun(adi: str, a_posmu: Any) -> str:
    n = _norm(adi)
    if "HISSE" in n or "RONESANS" in n:
        return "HISSE_SENEDI"
    if str(a_posmu) not in {"", "0", "None"} and "KMH" in n:
        return "POS_KMH_BAGLI"
    if str(a_posmu) not in {"", "0", "None"}:
        return "POS"
    if "KREDI KART" in n:
        return "KREDI_KARTI"
    if "KMH" in n:
        return "KMH"
    if n.startswith("03 ") or (" KREDI" in n and "KART" not in n):
        return "KREDI_HESABI"
    if "VADEL" in n or "GUNLUK" in n:
        return "VADELI_MEVDUAT"
    return "BANKA_MEVDUAT"


def _tarih_kurali(urun: str) -> dict[str, Any]:
    if urun in {"POS", "POS_KMH_BAGLI"}:
        return {
            "kapanis_hareket_tarihi": "G.a_tarih ≤ 31.08.2026",
            "kullanilabilir_banka_filtresi": "G.a_vtarih (yoksa G.a_tarih) ≤ 31.08.2026",
            "valor_bekleyen": "a_tarih≤31.08 ve a_vtarih>31.08 → POS bloke/bekleyen; kullanılabilir bankaya eklenmez",
            "pos_valor_filtresi_genellenir": False,
            "not": "POS valör filtresi yalnızca POS ürününe; KK/kredi/KMH borcuna genellenmez",
        }
    if urun == "KREDI_KARTI":
        return {
            "kapanis_hareket_tarihi": "G.a_tarih ≤ 31.08.2026",
            "pos_valor_filtresi_uygulanmaz": True,
            "not": "KK borç/ekstre — POS valör kuralı yok",
        }
    if urun in {"KREDI_HESABI", "KMH"}:
        return {
            "kapanis_hareket_tarihi": "G.a_tarih ≤ 31.08.2026",
            "pos_valor_filtresi_uygulanmaz": True,
            "not": "Kredi/KMH — POS valör kuralı yok",
        }
    return {
        "kapanis_hareket_tarihi": "G.a_tarih ≤ 31.08.2026",
        "banka_toplami_excel_karsilastirma": "Excel filtre tarihi (manifest) ile; POS valör kuralı yok",
        "pos_valor_filtresi_uygulanmaz": True,
    }


def _hareket_satir(h: dict) -> dict[str, Any]:
    ana = _dec(h.get("G.a_ana_para"))
    giren = _dec(h.get("G.a_giren")) or Decimal("0")
    cikan = _dec(h.get("G.a_cikan")) or Decimal("0")
    kom = _dec(h.get("G.a_komisyon"))
    # Ham alanlar; komisyon birimi kaynakta belirsiz (oran veya tutar) — TL net uydurulmaz
    net_banka_satir = giren - cikan
    return {
        "G.a_id": str(h.get("G.a_id")),
        "hesap_id": str(h.get("G.a_banka_id")),
        "hesap_adi": h.get("TBL_BANKA.a_adi"),
        "islem_turu": h.get("FIN_TUR.a_adi"),
        "tur_id": h.get("G.a_tur_id"),
        "islem_tarihi": parse_tarih(h.get("G.a_tarih")).isoformat()
        if parse_tarih(h.get("G.a_tarih"))
        else None,
        "valor_tarihi": parse_tarih(h.get("G.a_vtarih")).isoformat()
        if parse_tarih(h.get("G.a_vtarih"))
        else None,
        "brut_ana_para": str(ana) if ana is not None else None,
        "giren": str(giren),
        "cikan": str(cikan),
        "komisyon_ham": str(kom) if kom is not None else None,
        "komisyon_birimi": "KAYNAK_HAM_ALAN_G.a_komisyon — TL net türetimi yok",
        "net_banka_satir_giren_eksi_cikan": str(net_banka_satir),
        "kontrol": h.get("G.a_kontrol"),
        "pos_bloke": h.get("G.a_pos_bloke"),
        "modul_id": h.get("G.a_modul_id"),
        "modul_ref_id": h.get("G.a_mudul_ref_id"),
        "ref_id": h.get("G.a_ref_id"),
        "mkb": (str(h.get("MKB") or "").strip() or None),
        "mkb_kod": h.get("MKB_KOD"),
        "cdate": h.get("G.a_cdate"),
        "mdate": h.get("G.a_mdate"),
    }


def main() -> int:
    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    pos_valor = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}POS_VALOR.json").read_text(encoding="utf-8")
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

    by_id = {str(h.get("G.a_id")): h for h in (banka.get("hareketler") or [])}
    bes = []
    for hid in HEDEF_IDS:
        h = by_id.get(hid)
        if not h:
            bes.append({"G.a_id": hid, "bulunamadi": True})
            continue
        bes.append(_hareket_satir(h))

    giren_toplam = sum((_dec(x.get("giren")) or Decimal("0") for x in bes), Decimal("0"))
    assert_ok = _q2(giren_toplam) == HEDEF_TOPLAM and all(not x.get("bulunamadi") for x in bes)

    # POS_VALOR çapraz
    vb_ids = {str(x.get("hareket_id")) for x in (pos_valor.get("valor_bekleyen") or [])}
    bloke_ids = {str(x.get("hareket_id")) for x in (pos_valor.get("bloke") or [])}

    durum_3108 = []
    for x in bes:
        if x.get("bulunamadi"):
            continue
        durum_3108.append(
            {
                "G.a_id": x["G.a_id"],
                "islem_tarihi": x["islem_tarihi"],
                "valor_tarihi": x["valor_tarihi"],
                "kontrol": x["kontrol"],
                "pos_bloke": x["pos_bloke"],
                "pos_valor_bekleyen_listesinde": x["G.a_id"] in vb_ids,
                "pos_bloke_listesinde": x["G.a_id"] in bloke_ids,
                "rol_3108": (
                    "BEKLEYEN_POS_BLOKE — işlem 31.08’de kayıtlı; valör 01.09; "
                    "kullanılabilir banka bakiyesine dahil değil"
                ),
                "ayri_hesap_rolu_yok": True,
                "cift_sayim_yasagi": (
                    "Aynı 4355 POS bekleyen + kullanılabilir bankada iki kez sayılmaz. "
                    "İşlem tarihli brüt görünüm ≠ valör tarihli kullanılabilir banka."
                ),
            }
        )

    # Görünüm A: işlem tarihi
    akbank_hareket = [
        h
        for h in (banka.get("hareketler") or [])
        if str(h.get("G.a_banka_id")) == AKBANK_ID
    ]

    def topla(filtre_fn) -> dict[str, Any]:
        g = c = Decimal("0")
        n = 0
        bes_dahil = []
        for h in akbank_hareket:
            if not filtre_fn(h):
                continue
            gg, cc = _yon_tutar(h)
            g += gg or Decimal("0")
            c += cc or Decimal("0")
            n += 1
            if str(h.get("G.a_id")) in HEDEF_IDS:
                bes_dahil.append(str(h.get("G.a_id")))
        return {
            "hareket_adet": n,
            "giren": str(g),
            "cikan": str(c),
            "net": str(g - c),
            "bes_tahsilat_dahil_idler": bes_dahil,
            "bes_dahil_adet": len(bes_dahil),
        }

    def f_islem(h: dict) -> bool:
        t = parse_tarih(h.get("G.a_tarih"))
        return bool(t and FILTRE_BAS <= t <= DONEM_SONU)

    def f_valor(h: dict) -> bool:
        t = parse_tarih(h.get("G.a_tarih"))
        vt = parse_tarih(h.get("G.a_vtarih"))
        ft = vt or t
        return bool(ft and FILTRE_BAS <= ft <= DONEM_SONU)

    gorunum_islem = topla(f_islem)
    gorunum_valor = topla(f_valor)

    # D2 bağları — aynı G.a_id; yeni fiş yok
    d2_baglar = []
    for x in bes:
        if x.get("bulunamadi"):
            continue
        d2_baglar.append(
            {
                "kaynak_G.a_id": x["G.a_id"],
                "mevcut_islem_tarihi": x["islem_tarihi"],
                "bankaya_gecis_valor": x["valor_tarihi"],
                "baglanti": "Aynı kaynak işlem kimliği; 01.09 valör = mevcut kaydın banka geçiş tarihi",
                "yeni_musteri_tahsilati_uretilmez": True,
                "yeni_satis_geliri_uretilmez": True,
                "yalniz_valore_dayali_yeni_hareket_olusturulmaz": True,
                "d2_hazirlik": (
                    "Devir 2’de bu G.a_id’ler valör gününde kullanılabilir bankaya geçer "
                    "olarak izlenir; mükerrer tahsilat satırı yazılmaz"
                ),
            }
        )

    # Halkbank + günlük vadeli
    kart_by_id = {str(k.get("id")): k for k in (banka.get("kartlar") or [])}
    halkbank = []
    for hid in HALKBANK_KK_IDS:
        kart = kart_by_id.get(hid) or {}
        har = [h for h in (banka.get("hareketler") or []) if str(h.get("G.a_banka_id")) == hid]
        halkbank.append(
            {
                "kaynak_hesap_id": hid,
                "kaynak_adi": kart.get("text"),
                "a_posmu": kart.get("a_posmu"),
                "urun": _urun(str(kart.get("text") or ""), kart.get("a_posmu")),
                "kartlar_listesinde": hid in kart_by_id,
                "hareket_adet_tum": len(har),
                "excel_banka_toplami_satiri": "YOK",
                "aciklama": (
                    "Kaynak kart ID mevcut; dönem içi hareket 0. Banka Toplamı Excel "
                    "(01.06.2025–31.08.2026) bu yüzden satır üretmemiş. "
                    "Eksik eşleşme değil — boş hareketli KK kartı."
                ),
            }
        )

    gunluk_har = [
        h for h in (banka.get("hareketler") or []) if str(h.get("G.a_banka_id")) == GUNLUK_ID
    ]
    g_g = c_g = Decimal("0")
    gunluk_satirlar = []
    for h in gunluk_har:
        t = parse_tarih(h.get("G.a_tarih"))
        if t and FILTRE_BAS <= t <= DONEM_SONU:
            gg, cc = _yon_tutar(h)
            g_g += gg or Decimal("0")
            c_g += cc or Decimal("0")
            gunluk_satirlar.append(_hareket_satir(h))

    excel_gunluk = next(
        (
            h
            for h in (banka_excel.get("hesaplar") or [])
            if "GUNLUK" in _norm(h.get("excel_adi") or "")
            or "VADEL" in _norm(h.get("excel_adi") or "")
        ),
        None,
    )

    gunluk = {
        "kaynak_hesap_id": GUNLUK_ID,
        "kaynak_adi_hareketlerden": "01 AKBANK GÜNLÜK VADELİ HESAP",
        "kartlar_31_listesinde": GUNLUK_ID in kart_by_id,
        "aciklama": (
            "Excel’de satır var; BANKA.json kartlar (31) listesinde ID yok. "
            f"Hareketlerde G.a_banka_id={GUNLUK_ID} ile geçiyor. "
            "Önceki ESLESME_YOK (ad↔kartlar) — gerçek kaynak ID=2030 hareketlerden."
        ),
        "filtre_0106_3108": {
            "hareket_adet": len(gunluk_satirlar),
            "giren": str(g_g),
            "cikan": str(c_g),
            "net": str(g_g - c_g),
            "excel_giren": (excel_gunluk or {}).get("excel", {}).get("giren")
            if excel_gunluk
            else None,
            "excel_cikan": (excel_gunluk or {}).get("excel", {}).get("cikan")
            if excel_gunluk
            else None,
            "excel_toplam": (excel_gunluk or {}).get("excel", {}).get("toplam")
            if excel_gunluk
            else None,
            "kurus_giren_esit": excel_gunluk is not None
            and _q2(g_g) == _q2(_dec((excel_gunluk.get("excel") or {}).get("giren")) or Decimal("0")),
            "kurus_cikan_esit": excel_gunluk is not None
            and _q2(c_g) == _q2(_dec((excel_gunluk.get("excel") or {}).get("cikan")) or Decimal("0")),
        },
        "hareketler": gunluk_satirlar,
        "urun": "VADELI_MEVDUAT",
        "tarih_kurali": _tarih_kurali("VADELI_MEVDUAT"),
    }

    # Kalan hesaplar — ürün + tarih kuralı ile durum
    excel_by_id = {
        str(h.get("kaynak_hesap_id")): h
        for h in (banka_excel.get("hesaplar") or [])
        if h.get("kaynak_hesap_id")
    }
    kalan = []
    for k in banka.get("kartlar") or []:
        hid = str(k.get("id"))
        adi = str(k.get("text") or "")
        urun = _urun(adi, k.get("a_posmu"))
        ex = excel_by_id.get(hid)
        vakif_ok = hid == "5" and bool((vakif.get("kapanis_kontrolu") or {}).get("tamam"))
        if vakif_ok:
            durum = "KAPANIS_KONTROL_TAMAM_VAKIFBANK"
        elif hid == AKBANK_ID:
            durum = "POS_VALOR_4355_ACIKLANDI_KAPANIS_BEKLIYOR"
        elif hid in HALKBANK_KK_IDS:
            durum = "EXCEL_YOK_HAREKET_0"
        elif ex and ex.get("sonuc") == "TAM_ESLESME":
            durum = "EXCEL_DONEM_NET_ESIT_ACILIS_KONTROL_BEKLEYEBILIR"
        elif ex and ex.get("sonuc") == "ESIT_KAYAN_NOKTA_ARTIGI":
            durum = "EXCEL_DONEM_NET_KURUS_ESIT_KAYAN_NOKTA"
        elif ex:
            durum = f"EXCEL_{ex.get('sonuc')}"
        else:
            durum = "EXCEL_ESLESME_YOK"

        # POS valor bekleyen bu hesapta
        vb_hesap = [
            x
            for x in (pos_valor.get("valor_bekleyen") or [])
            if str(x.get("kaynak_banka_id")) == hid
        ]
        kalan.append(
            {
                "kaynak_hesap_id": hid,
                "adi": adi,
                "a_posmu": k.get("a_posmu"),
                "urun": urun,
                "tarih_kurali": _tarih_kurali(urun),
                "durum": durum,
                "excel_sonuc": (ex or {}).get("sonuc"),
                "valor_bekleyen_adet": len(vb_hesap),
                "valor_bekleyen_toplam": str(
                    sum((_dec(x.get("tutar_net")) or Decimal("0") for x in vb_hesap), Decimal("0"))
                ),
                "pos_valor_kurali_sadece_pos": urun in {"POS", "POS_KMH_BAGLI"},
            }
        )

    # 2030 kartlarda yok — ayrı ekle
    kalan.append(
        {
            "kaynak_hesap_id": GUNLUK_ID,
            "adi": "01 AKBANK GÜNLÜK VADELİ HESAP",
            "a_posmu": None,
            "urun": "VADELI_MEVDUAT",
            "tarih_kurali": _tarih_kurali("VADELI_MEVDUAT"),
            "durum": "KARTLAR_LISTESINDE_YOK_HAREKETTEN_ID",
            "excel_sonuc": "once_ESLESME_YOK_simdi_ID_2030",
            "valor_bekleyen_adet": 0,
            "pos_valor_kurali_sadece_pos": False,
        }
    )

    kanit = {
        "format": "d1-akbank-4355-pos-valor-d2-hazirlik-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "devir_2": "HAZIRLIK_REFERANS",
        "vakifbank_korundu": {
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_VAKIFBANK_EKSTRE_EXCEL.json",
            "kapanis_kontrol_tamam": bool((vakif.get("kapanis_kontrolu") or {}).get("tamam")),
            "degistirilmedi": True,
        },
        "bes_tahsilat": {
            "hedef_toplam": str(HEDEF_TOPLAM),
            "giren_toplam": str(giren_toplam),
            "toplam_esit": assert_ok,
            "satirlar": bes,
        },
        "gorunum_islem_tarihli": {
            "filtre": "G.a_tarih ∈ [2025-06-01, 2026-08-31]",
            "aciklama": "Tahsilat işlem günü görünümü — 5 kayıt döneme dahil",
            **gorunum_islem,
            "bes_giren_katkisi": str(HEDEF_TOPLAM),
        },
        "gorunum_valor_tarihli_banka": {
            "filtre": "(G.a_vtarih yoksa G.a_tarih) ∈ [2025-06-01, 2026-08-31]",
            "aciklama": (
                "Kullanılabilir / Banka Toplamı Excel banka görünümü — "
                "5 tahsilat valör 01.09 olduğu için bu aralıkta yok"
            ),
            **gorunum_valor,
            "bes_giren_katkisi": "0",
            "excel_banka_toplami_giren_ile_esit": _q2(
                _dec(gorunum_valor["giren"]) or Decimal("0")
            )
            == Decimal("6357911.93"),
        },
        "durum_3108": {
            "ozet": (
                "31.08 itibarıyla 5 tahsilat: kontrol=Beklemede, pos_bloke=1, "
                "POS_VALOR.valor_bekleyen içinde. Kullanılabilir banka bakiyesi değil; "
                "ayrı ikinci hesap rolü yok."
            ),
            "satirlar": durum_3108,
            "cift_sayim": {
                "pos_bekleyen_ve_kullanilabilir_banka_ayni_4355": False,
                "kural": "POS bloke/valor bekleyen tutar kullanılabilir banka netine ikinci kez eklenmez",
            },
        },
        "d2_01_09_gecis": {
            "valor_tarihi": "2026-09-01",
            "baglar": d2_baglar,
            "kurallar": [
                "Çözülme = mevcut G.a_id valör geçişi",
                "Yeni müşteri tahsilatı üretilmez",
                "Yeni satış geliri üretilmez",
                "Yalnız valör tarihine dayanarak gerçekleşmemiş banka hareketi oluşturulmaz",
            ],
            "mali_yazim": False,
        },
        "excel_disi_hesaplar": {
            "halkbank_kk": halkbank,
            "akbank_gunluk_vadeli": gunluk,
        },
        "kalan_hesap_dogrulama": {
            "pos_valor_filtresi_kk_kredi_kmh_genellenmez": True,
            "hesaplar": kalan,
            "ozet_sayac": {
                k: sum(1 for h in kalan if h["durum"] == k)
                for k in sorted({h["durum"] for h in kalan})
            },
        },
        "duzeltme_fisi_uretilmedi": True,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_AKBANK_4355_POS_VALOR_D2", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "bes_toplam_esit": assert_ok,
        "islem_giren": gorunum_islem["giren"],
        "valor_giren": gorunum_valor["giren"],
        "valor_excel_esit": kanit["gorunum_valor_tarihli_banka"]["excel_banka_toplami_giren_ile_esit"],
        "d2_bag_adet": len(d2_baglar),
        "gunluk_id": GUNLUK_ID,
        "halkbank_hareket_0": [h["kaynak_hesap_id"] for h in halkbank],
        "vakifbank_korundu": True,
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "AKBANK_4355_POS_VALOR_D2_OZET.json", ozet)
    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
