"""Devir 1 — Stok envanter Excel eşleme çözüm (kimlik / miktar / sıfır maliyet).

Önceki DOGRULAMA_STOK_ENVANTER_EXCEL_STOK_BAZLI üzerine:
- 131 Excel eşleşmeyeni BELGE_SATIR.stok_kod → stok_id ile çöz (isim birleştirme yok)
- Belirsiz çifti hareket_net ile ayır
- 30 API kartını sınıfla (hizmet/gider vs kalan)
- 23 miktar farkını Excel 2dk yuvarlama vs aktarım diye ayır
- 14 sıfır maliyeti koru (kart doldurma yok)
- Kuruş: yalnız ROUND_DOWN gözlemi
- K05 / mali / EXE yok; yeni maliyet hesabı yok

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_envanter_esleme_coz
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_envanter_excel_devir1 import (
    ALIS_TUR,
    BELGE_SATIR,
    STOK_HRK,
    STOK_MALIYET,
    STOK_MIKTAR,
    _sinif_sifir_maliyet,
    _yukle_alis_fiyatlar,
    tr_dec,
)

STOK_BAZLI = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_EXCEL_STOK_BAZLI.json"
ENV_KANIT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_EXCEL.json"
MANIFEST = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}MANIFEST.json"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
FIFO_IZOLE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_FIFO_KATMAN_IZOLE.json"

KURUS = Decimal("0.01")


def _q2(v: Decimal, rounding=ROUND_HALF_UP) -> Decimal:
    return v.quantize(KURUS, rounding=rounding)


def _yukle_json(yol: Path) -> dict:
    return json.loads(yol.read_text(encoding="utf-8"))


def _belge_kod_to_ids() -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    with BELGE_SATIR.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            for s in o.get("satirlar") or []:
                sk = str(s.get("stok_kod") or "").strip()
                sid = str(s.get("stok_id") or s.get("a_stok_id") or "")
                if sk and sid:
                    out[sk].add(sid)
    return out


def _hareket_by_id() -> dict[str, dict]:
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


def _api_hizmet_mi(kod: str | None, adi: str | None) -> bool:
    """Kaynak kod öneki / bilinen hizmet kart kalıbı — isim birleştirme değil."""
    k = (kod or "").strip()
    ku = k.upper()
    if ku.startswith("GDR") or ku.startswith("H000") or ku.startswith("VF"):
        return True
    if ku in {"KRG", "H000001", "H000002"} or k.lower() == "h000001":
        return True
    # sayısal kod + gelir/gider kalıbı yalnız kod uzunluğu kısa hizmetlerde
    if ku in {"10750", "10564", "10346", "10531000001"}:
        return True
    return False


def _manifest_guncelle() -> None:
    if not MANIFEST.is_file():
        return
    man = _yukle_json(MANIFEST)
    onceki = man.get("stok_envanter_excel") or {}
    man["stok_envanter_excel"] = {
        **onceki,
        "envanter_tarihi": "2026-08-31",
        "maliyet_yontemi": "FIFO",
        "maliyet_hesabi_tarihi": "2026-08-31",
        "maliyet_hesabi_durum": "kullanici_teyidi_tamamlandi",
        "dosya_alinma": {
            "indirme_adi": onceki.get("dosya_adi_indirme")
            or "rapor_stok_envanter_07-11-2026.xlsx",
            "alinma_gunu_dosya_adi": "2026-11-07",
            "dosya_adi_envanter_tarihi_degil": True,
            "kanit_kopya": onceki.get("kanit_kopya"),
            "sha256": onceki.get("sha256"),
            "kaynak_surum": "EvoBulut envanter raporu — FIFO maliyet hesabı 31.08.2026 tamamlandıktan sonra",
        },
        "iki_excel_icerik": {
            "onceki": "rapor_stok_envanter_07-11-2026.xlsx",
            "son": "rapor_stok_envanter_07-11-2026(1).xlsx",
            "kullanici_bildirimi_birebir_ayni": True,
            "farkli_sonuc_varsayilmaz": True,
            "not": (
                "Kullanıcı iki dosya içeriğinin birebir aynı olduğunu bildirdi; "
                "karşılaştırma farklı değer varsaymaz. (1) indirmesi bu oturumda "
                "Downloads’ta yoksa mevcut kanıt kopyası / aynı SHA esas alınır."
            ),
        },
        "kullanici_teyidi": {
            **(onceki.get("kullanici_teyidi") or {}),
            "envanter_tarihi": "2026-08-31",
            "maliyet_yontemi": "FIFO",
            "maliyet_hesabi_tarihi": "2026-08-31",
            "onceki_excel_bugun_tarihli_maliyet_sonrasiydi": True,
            "son_excel_3108_maliyet_yeniden_calistirildiktan_sonra": True,
            "teyit_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "yeni_maliyet_hesabi_baslatilmadi": True,
        "k05": False,
        "devir": 1,
    }
    ham = json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8")
    MANIFEST.write_bytes(ham)
    MANIFEST.with_suffix(".json.sha256").write_text(
        f"{hashlib.sha256(ham).hexdigest().upper()}  {MANIFEST.name}\n",
        encoding="ascii",
    )


def main() -> int:
    baz = _yukle_json(STOK_BAZLI)
    env = _yukle_json(ENV_KANIT) if ENV_KANIT.is_file() else {}
    miktar = _yukle_json(STOK_MIKTAR)
    kartlar = list(miktar.get("kayitlar") or [])
    ids_3150 = {str(k["a_id"]) for k in kartlar}
    by_id = {str(k["a_id"]): k for k in kartlar}
    hareket = _hareket_by_id()
    maliyet = {
        str(s["kaynak_stok_id"]): s
        for s in (_yukle_json(STOK_MALIYET).get("stoklar") or [])
    }
    kod_to_ids = _belge_kod_to_ids()

    eslesen = list(baz.get("eslesen") or [])
    kullanilan = {e["kaynak_stok_id"] for e in eslesen}
    excel_eslesmeyen = list(baz.get("excel_eslesmeyen") or [])
    belirsiz = list(baz.get("belirsiz") or [])
    api_eslesmeyen = list(baz.get("api_eslesmeyen") or [])
    miktar_fark = list(baz.get("miktar_fark") or [])
    negatif = list(baz.get("negatif") or [])
    sifir_mal = list(baz.get("sifir_maliyet_pozitif") or [])

    # --- 1) Belirsiz: hareket_net == excel kalan (isim yok) ---
    belirsiz_cozulen = []
    belirsiz_kalan = []
    for b in belirsiz:
        kal = tr_dec(b.get("kalan")) or Decimal("0")
        adaylar = []
        for sid in b.get("aday_stok_id") or []:
            if sid in kullanilan:
                continue
            hr = hareket.get(sid) or {}
            hn = tr_dec(hr.get("hareket_net"))
            if hn is not None and hn == kal:
                adaylar.append(sid)
        if len(adaylar) == 1:
            sid = adaylar[0]
            kart = by_id[sid]
            hr = hareket.get(sid) or {}
            kayit = {
                "excel_satir": b["excel_satir"],
                "kod": b["kod"],
                "kaynak_stok_id": sid,
                "birim_excel": b.get("birim"),
                "birim_kart": kart.get("ana_birim_adi"),
                "brm_id": kart.get("a_brm_id"),
                "excel_kalan": str(kal),
                "hareket_net_31_08": str(hr.get("hareket_net")),
                "miktar_esit_hareket_net": True,
                "esleme_durum": "BELIRSIZ_HAREKET_NET_COZULDU",
                "esleme_kanit": "aynı a_kod adaylarından yalnız hareket_net=excel_kalan",
                "kart_kalan_otorite_degil": True,
                "in_stok_miktar_3150": True,
            }
            eslesen.append(kayit)
            kullanilan.add(sid)
            belirsiz_cozulen.append(kayit)
        else:
            belirsiz_kalan.append(
                {
                    **b,
                    "esleme_durum": "BELIRSIZ_KALDI",
                    "hareket_net_aday": {
                        sid: (hareket.get(sid) or {}).get("hareket_net")
                        for sid in (b.get("aday_stok_id") or [])
                    },
                }
            )

    # --- 2) Excel eşleşmeyen → BELGE_SATIR exact stok_kod ---
    belge_ile_cozulen = []
    kimlik_yok = []
    for x in excel_eslesmeyen:
        kod = x.get("kod") or ""
        # boş kod: tek boş API kartı
        if not kod:
            bos = [k for k in kartlar if not str(k.get("a_kod") or "").strip()]
            bos = [k for k in bos if str(k["a_id"]) not in kullanilan]
            if len(bos) == 1:
                sid = str(bos[0]["a_id"])
                kayit = {
                    **x,
                    "kaynak_stok_id": sid,
                    "esleme_durum": "BOS_KOD_TEK_KART",
                    "esleme_kanit": "excel boş kod ↔ API tek boş a_kod (isim kullanılmadı)",
                    "in_stok_miktar_3150": True,
                }
                eslesen.append(kayit)
                kullanilan.add(sid)
                belge_ile_cozulen.append(kayit)
                continue
        sids = kod_to_ids.get(kod) or set()
        sids = {s for s in sids if s not in kullanilan}
        if len(sids) == 1:
            sid = next(iter(sids))
            in3150 = sid in ids_3150
            hr = hareket.get(sid) or {}
            kayit = {
                **x,
                "kaynak_stok_id": sid,
                "esleme_durum": (
                    "BELGE_KOD_EXACT_3150_DISI"
                    if not in3150
                    else "BELGE_KOD_EXACT_3150_ICI"
                ),
                "esleme_kanit": "BELGE_SATIR.stok_kod == excel kod (exact); isim birleştirme yok",
                "in_stok_miktar_3150": in3150,
                "hareket_cekildi": sid in hareket,
                "hareket_net_31_08": str(hr.get("hareket_net"))
                if hr.get("hareket_net") is not None
                else None,
                "kapsam_disi_sayilmaz": True,
                "sifir_kabul_edilmez": True,
            }
            # Çakışmasız: 3150 listesinde yoksa eslesen'e ID bağlanır ama
            # "liste_eslesmesi" ayrı kovada tutulur
            belge_ile_cozulen.append(kayit)
            if in3150:
                eslesen.append(kayit)
                kullanilan.add(sid)
            else:
                # ID rezerve — aynı ID başka excel satırına gitmesin
                kullanilan.add(sid)
        elif len(sids) > 1:
            kimlik_yok.append(
                {
                    **x,
                    "esleme_durum": "BELGE_COKLU_STOK_ID",
                    "aday_stok_id": sorted(sids),
                    "kapsam_disi_sayilmaz": True,
                }
            )
        else:
            kimlik_yok.append(
                {
                    **x,
                    "esleme_durum": "KAYNAK_STOK_ID_BULUNAMADI",
                    "arandi": [
                        "STOK_MIKTAR.a_kod",
                        "STOK_HAREKET.kod",
                        "BELGE_SATIR.stok_kod",
                        "STOK_MALIYET.kod",
                    ],
                    "hipotez": [
                        "pasif/silinmiş kart (3150 çekimi yalnız Aktif)",
                        "kod değişikliği (eski kod envanterde)",
                        "stok listesi sayfalama/filtre eksikliği",
                        "görüntü alma zamanı farkı (liste 2026-11-06, excel 2026-11-07)",
                    ],
                    "kapsam_disi_sayilmaz": True,
                    "sifir_kabul_edilmez": True,
                }
            )

    # --- 3) Negatif kimlik ---
    negatif_coz = []
    for n in negatif:
        kod = n.get("kod") or ""
        sids = kod_to_ids.get(kod) or set()
        sid = next(iter(sids)) if len(sids) == 1 else None
        negatif_coz.append(
            {
                **n,
                "kaynak_stok_id": sid,
                "esleme_durum": "BELGE_KOD_EXACT"
                if sid
                else "KAYNAK_STOK_ID_BULUNAMADI",
                "in_stok_miktar_3150": (sid in ids_3150) if sid else False,
                "hareket_cekildi": (sid in hareket) if sid else False,
                "duzeltme_ile_kapatilmaz": True,
                "esleme_kanit": "BELGE_SATIR.stok_kod exact (P… paket birim kartı)"
                if sid
                else None,
            }
        )

    # --- 4) API eşleşmeyen sınıflama ---
    api_sinif = []
    for a in api_eslesmeyen:
        sid = str(a["kaynak_stok_id"])
        if sid in kullanilan and sid not in {
            x["kaynak_stok_id"] for x in belge_ile_cozulen if not x.get("in_stok_miktar_3150")
        }:
            # belirsiz çözümde kullanıldı
            durum = "EXCEL_ILE_ESLESTI_SONRA"
            if any(e.get("kaynak_stok_id") == sid for e in belirsiz_cozulen):
                durum = "BELIRSIZ_COZUMDE_KULLANILDI"
            api_sinif.append({**a, "esleme_durum": durum})
            continue
        if sid in kullanilan:
            api_sinif.append({**a, "esleme_durum": "EXCEL_ILE_ESLESTI"})
            continue
        if _api_hizmet_mi(a.get("kod"), a.get("adi")):
            api_sinif.append(
                {
                    **a,
                    "esleme_durum": "API_HIZMET_GIDER_KARTI",
                    "aciklama": (
                        "Stok listesinde hizmet/gider kartı; FIFO envanter raporunda "
                        "yok. Kapsam farkı — sıfır/yok sayılmaz, ayrı sınıf."
                    ),
                    "excelde_yok": True,
                }
            )
        else:
            api_sinif.append(
                {
                    **a,
                    "esleme_durum": "API_EXCELDE_YOK",
                    "aciklama": "3150 listesinde var; 31.08 Excel envanterinde yok",
                    "excelde_yok": True,
                    "kapsam_disi_sayilmaz": True,
                }
            )

    # --- 5) 23 miktar farkı ---
    miktar_aciklama = []
    for x in miktar_fark:
        ex = tr_dec(x.get("excel_kalan")) or Decimal("0")
        hr = tr_dec(x.get("hareket_net_31_08"))
        kart = tr_dec(x.get("kart_kalan_anlik_bilgi"))
        if hr is None:
            sinif = "HAREKET_NET_YOK"
            aktarim = False
        elif _q2(hr) == ex:
            sinif = "EXCEL_2_ONDALIK_YUVARLAMA"
            aktarim = False
        else:
            sinif = "MIKTAR_FARK_AKTARIM_ADAY"
            aktarim = True
        miktar_aciklama.append(
            {
                **x,
                "sinif": sinif,
                "aktarim_hatasi_degil": not aktarim,
                "excel_kalan_2dk": str(ex),
                "hareket_net_tam": str(hr) if hr is not None else None,
                "hareket_net_q2": str(_q2(hr)) if hr is not None else None,
                "kart_anlik_fark_bilgi": str(kart - hr)
                if (kart is not None and hr is not None)
                else None,
                "kart_anlik_otorite_degil": True,
                "aciklama": (
                    "Excel kalan 2 ondalıklı metin; hareket_net daha yüksek hassasiyet. "
                    "q2(hareket_net)==excel_kalan → görüntü yuvarlaması, aktarım hatası değil. "
                    "Kesin FIFO katman yuvarlanmış miktardan üretilmez."
                    if sinif == "EXCEL_2_ONDALIK_YUVARLAMA"
                    else sinif
                ),
            }
        )

    # --- 6) Sıfır maliyet (kart doldurma yok) — yeniden sınıfla belge ile ---
    zc_ids = {str(z["kaynak_stok_id"]) for z in sifir_mal if z.get("kaynak_stok_id")}
    # belge ile yeni çözülen sıfır maliyet satırları
    for z in belge_ile_cozulen:
        if tr_dec(z.get("kalan") or z.get("excel_kalan")) and (
            tr_dec(z.get("kalan") or "0") or Decimal("0")
        ) > 0:
            # birim maliyet excel bazlı listede; sifir_mal zaten 14
            pass
    alis = _yukle_alis_fiyatlar(zc_ids)
    sifir_yeniden = []
    for z in sifir_mal:
        sid = z.get("kaynak_stok_id")
        # belge ile yeni id
        if not sid:
            hit = next(
                (
                    b
                    for b in belge_ile_cozulen
                    if b.get("excel_satir") == z.get("excel_satir")
                ),
                None,
            )
            if hit:
                sid = hit.get("kaynak_stok_id")
        sinif = _sinif_sifir_maliyet(
            sid, alis.get(sid or "", []), maliyet.get(sid or "") if sid else None
        )
        sifir_yeniden.append(
            {
                **{k: v for k, v in z.items() if k not in sinif},
                "kaynak_stok_id": sid,
                **sinif,
            }
        )

    # --- Hesap verilebilir matris ---
    excel_durum_say = Counter()
    # Önceki 3120 + belirsiz çözüm + boş kod
    for e in eslesen:
        excel_durum_say[e.get("esleme_durum") or "STOK_MIKTAR_KOD_BIRIM"] += 1
    for b in belge_ile_cozulen:
        if not b.get("in_stok_miktar_3150"):
            excel_durum_say[b["esleme_durum"]] += 1
    for k in kimlik_yok:
        excel_durum_say[k["esleme_durum"]] += 1
    for b in belirsiz_kalan:
        excel_durum_say[b["esleme_durum"]] += 1

    api_durum_say = Counter(a["esleme_durum"] for a in api_sinif)

    belge_disi = [b for b in belge_ile_cozulen if not b.get("in_stok_miktar_3150")]
    bos_ek = sum(
        1 for b in belge_ile_cozulen if b.get("esleme_durum") == "BOS_KOD_TEK_KART"
    )
    kimlik_bulunamadi = [
        k for k in kimlik_yok if k["esleme_durum"] == "KAYNAK_STOK_ID_BULUNAMADI"
    ]
    kimlik_coklu = [k for k in kimlik_yok if k["esleme_durum"] == "BELGE_COKLU_STOK_ID"]
    liste_eslesen_net = 3120 + len(belirsiz_cozulen) + bos_ek
    toplam_excel = (
        liste_eslesen_net
        + len(belge_disi)
        + len(kimlik_bulunamadi)
        + len(kimlik_coklu)
        + len(belirsiz_kalan)
    )
    matris = {
        "excel_satir_toplam": 3252,
        "api_kart_toplam": 3150,
        "excel_durum_sayac": dict(excel_durum_say),
        "api_durum_sayac": dict(api_durum_say),
        "ozet_hesap": {
            "excel_liste_eslesen_net": liste_eslesen_net,
            "excel_belge_kimlik_3150_disi": len(belge_disi),
            "excel_kimlik_yok": len(kimlik_bulunamadi),
            "excel_belge_coklu_id": len(kimlik_coklu),
            "excel_belirsiz_kaldi": len(belirsiz_kalan),
            "toplam_kontrol": toplam_excel,
            "toplam_3252_uyum": toplam_excel == 3252,
            "api_hizmet_gider": sum(
                1 for a in api_sinif if a["esleme_durum"] == "API_HIZMET_GIDER_KARTI"
            ),
            "api_excelde_yok": sum(
                1 for a in api_sinif if a["esleme_durum"] == "API_EXCELDE_YOK"
            ),
            "api_belirsiz_cozumde": sum(
                1
                for a in api_sinif
                if a["esleme_durum"] == "BELIRSIZ_COZUMDE_KULLANILDI"
            ),
            "kural": (
                "3252+3150 satır/kart hesapta durur; bulunamayan sıfır veya kapsam dışı "
                "kabul edilmez."
            ),
        },
        "dogrulama_toplam_excel": toplam_excel,
    }

    kurus = {
        "excel_alt_toplam": "3731181.36",
        "ham_toplam_HALF_UP": "3731181.37",
        "gozlem_ROUND_DOWN_uyumu": True,
        "gozlem": (
            "Ham tutar toplamı ROUND_DOWN ile alt toplam metnine uyuyor; HALF_UP 0,01 TL "
            "farklı. Bu yalnız gözlem — kaynak hesaplama yöntemi doğrulanmadan kesin "
            "kök neden yazılmaz."
        ),
        "duzeltme_fisi_yok": True,
        "kesin_kok_neden_yazilmadi": True,
    }

    # FIFO devam engelleri
    fifo_izole = _yukle_json(FIFO_IZOLE) if FIFO_IZOLE.is_file() else {}
    acik_fifo = {
        "fifo_katman_tamam_degil": True,
        "onceki_izole_tam": fifo_izole.get("fifo_izole_tam_adet"),
        "cikisli_bekleyen": fifo_izole.get("esit_ama_cikisli_fifo_bekleyen"),
        "gerekce": (
            "Kapsam/miktar kimlikleri netleştikçe eksik hareket detayı ve LOT maliyet "
            "kanıtına devam. Yeni maliyet hesabı başlatılmadı."
        ),
        "sonraki_cek_gerekceli": {
            "stok_kart_listesi_eksik_id": sorted(
                {b["kaynak_stok_id"] for b in belge_disi}
            )[:80],
            "stok_kart_listesi_eksik_adet": len(belge_disi),
            "stok_id_bulunamayan_excel_kod_adet": matris["ozet_hesap"]["excel_kimlik_yok"],
            "StokHareket_detay": "çıkışlı + belge-kimlikli 3150-dışı kartlar",
            "filtre": {
                "bas_tar": "01.01.2015",
                "bit_tar": "31.08.2026",
                "depo": "tümü",
            },
        },
    }

    ihtimaller = {
        "pasif_silinmis": (
            "STOK_MIKTAR çekimi 3150 kartın tümü Aktif; pasif/silinmiş kart bu listede yok. "
            f"{len(belge_disi)} Excel satırı BELGE_SATIR’da stok_id ile var ama listede yok "
            "(çoğu P… paket birim kartı)."
        ),
        "farkli_birim": (
            "20 çift kod Adet/Unit ayrı a_id; P… kodlar ayrı paket birim kartı (Pk1/Paket). "
            "Dönüşümsüz toplanmaz."
        ),
        "kod_degisikligi": (
            f"{matris['ozet_hesap']['excel_kimlik_yok']} Excel kodu hiçbir D1 kaynağında yok — "
            "kod değişimi veya liste dışı kart hipotezi açık."
        ),
        "eksik_sayfalama_filtre": (
            "tum_stoklari_cek sayfalı liste; belge/envanterde görünen "
            f"{len(belge_disi)} stok_id 3150’de yok → liste kapsamı envanterden dar."
        ),
        "goruntu_alma_zamani": {
            "stok_miktar_alim": miktar.get("alim_zamani"),
            "excel_indirme_gunu": "2026-11-07",
            "donem_sonu": "2026-08-31",
            "not": "Liste güncel Aktif görüntü; Excel 31.08 FIFO envanter raporu.",
        },
    }

    kanit = {
        "format": "d1-stok-envanter-esleme-coz-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "karsilastirma_esasi": {
            "envanter_tarihi": "2026-08-31",
            "maliyet_yontemi": "FIFO",
            "maliyet_hesabi_tarihi": "2026-08-31",
            "yeni_maliyet_hesabi_baslatilmadi": True,
        },
        "kasa_banka_korundu": True,
        "ihtimaller": ihtimaller,
        "matris": matris,
        "belirsiz_cozulen": belirsiz_cozulen,
        "belirsiz_kalan": belirsiz_kalan,
        "belge_ile_kimlik": {
            "adet": len(belge_ile_cozulen),
            "in_3150": sum(1 for b in belge_ile_cozulen if b.get("in_stok_miktar_3150")),
            "notin_3150": len(belge_disi),
            "kayitlar": belge_ile_cozulen,
        },
        "kimlik_yok": kimlik_yok,
        "negatif_kimlik": negatif_coz,
        "api_sinif": api_sinif,
        "miktar_fark_23": {
            "adet": len(miktar_aciklama),
            "sinif_sayac": dict(Counter(m["sinif"] for m in miktar_aciklama)),
            "aktarim_hatasi_adet": sum(
                1 for m in miktar_aciklama if not m["aktarim_hatasi_degil"]
            ),
            "kayitlar": miktar_aciklama,
            "kural": "Yuvarlama ≠ aktarım hatası; kart_anlik dönem sonrası bilgi",
        },
        "sifir_maliyet_pozitif": {
            "adet": len(sifir_yeniden),
            "sinif_sayac": dict(Counter(s["sinif"] for s in sifir_yeniden)),
            "kart_ortalama_doldurma_yok": True,
            "kayitlar": sifir_yeniden,
        },
        "kurus_gozlem": kurus,
        "fifo_devam": acik_fifo,
        "kurallar": [
            "İsim/kod benzerliğiyle birleştirme yok",
            "Bulunamayan satır sıfır/kapsam dışı sayılmaz",
            "Negatif düzeltme ile kapatılmaz",
            "Kart maliyetinden sıfır maliyet doldurulmaz",
            "Kuruşta kesin kök neden yazılmaz",
            "Yeni maliyet hesabı başlatılmaz",
        ],
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    _manifest_guncelle()
    yol, sha = yaz_kaynak("DOGRULAMA_STOK_ENVANTER_ESLEME_COZ", kanit)

    # Stok bazlı güncelle (hesaplanabilir tam döküm)
    stok_bazli = {
        "format": "d1-stok-envanter-excel-stok-bazli-v2",
        "zaman": kanit["zaman"],
        "eslesen_liste": [e for e in eslesen if e.get("in_stok_miktar_3150", True)],
        "belge_kimlik_3150_disi": belge_disi,
        "kimlik_yok": kimlik_yok,
        "belirsiz_kalan": belirsiz_kalan,
        "api_sinif": api_sinif,
        "miktar_fark_aciklama": miktar_aciklama,
        "negatif_kimlik": negatif_coz,
        "sifir_maliyet_pozitif": sifir_yeniden,
        "matris": matris,
        "k05": False,
    }
    yol_sb, sha_sb = yaz_kaynak("DOGRULAMA_STOK_ENVANTER_EXCEL_STOK_BAZLI", stok_bazli)

    # Ana envanter kanıtına bağla
    if env:
        env["esleme_coz"] = {
            "kanit": f"kaynak/{yol.name}",
            "sha16": sha[:16],
            "matris": matris["ozet_hesap"],
            "miktar_fark_sinif": kanit["miktar_fark_23"]["sinif_sayac"],
            "negatif_kimlik": [
                {"kod": n["kod"], "kaynak_stok_id": n.get("kaynak_stok_id")}
                for n in negatif_coz
            ],
            "kurus_gozlem": kurus,
            "fifo_katman_tamam_degil": True,
        }
        env["stok_bazli_kanit"] = f"kaynak/{yol_sb.name}"
        env["stok_bazli_sha16"] = sha_sb[:16]
        env["k05"] = False
        yaz_kaynak("DOGRULAMA_STOK_ENVANTER_EXCEL", env)

    ozet = {
        "zaman": kanit["zaman"],
        "excel_liste_eslesen": matris["ozet_hesap"]["excel_liste_eslesen_net"],
        "belge_kimlik_3150_disi": matris["ozet_hesap"]["excel_belge_kimlik_3150_disi"],
        "kimlik_yok": matris["ozet_hesap"]["excel_kimlik_yok"],
        "belirsiz_kaldi": len(belirsiz_kalan),
        "toplam_excel_kontrol": matris["ozet_hesap"]["toplam_kontrol"],
        "miktar_fark_yuvarlama": kanit["miktar_fark_23"]["sinif_sayac"].get(
            "EXCEL_2_ONDALIK_YUVARLAMA", 0
        ),
        "miktar_aktarim_aday": kanit["miktar_fark_23"]["aktarim_hatasi_adet"],
        "negatif_id": [n.get("kaynak_stok_id") for n in negatif_coz],
        "sifir_mal_sinif": kanit["sifir_maliyet_pozitif"]["sinif_sayac"],
        "api_hizmet": matris["ozet_hesap"]["api_hizmet_gider"],
        "fifo_katman_tamam": False,
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_ENVANTER_ESLEME_COZ_OZET.json", ozet)

    if FIFO_KONTROL.is_file():
        try:
            fifo = _yukle_json(FIFO_KONTROL)
        except json.JSONDecodeError:
            fifo = {"tamamlanan": [], "engeller": []}
        fifo["stok_envanter_esleme_coz"] = ozet
        fifo["k05"] = False
        ham = json.dumps(fifo, ensure_ascii=False, indent=2).encode("utf-8")
        FIFO_KONTROL.write_bytes(ham)
        FIFO_KONTROL.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(ham).hexdigest().upper()}  {FIFO_KONTROL.name}\n",
            encoding="ascii",
        )

    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
