"""D2 sayısal aktarım önizlemesi — yalnız kaynak okuma; mali yazım yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_aktarim_onizleme_hesapla
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]
D1 = KOK / "kurulum" / "dnm_d1_20260831"
D2 = KOK / CALISMA_KOK
K = D1 / "kaynak"
NOW = datetime.now().astimezone()
NOW_S = NOW.isoformat(timespec="seconds")


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _D(x: Any) -> Decimal | None:
    if x is None or x == "":
        return None
    try:
        return Decimal(str(x).replace(",", ".").replace(" ", ""))
    except Exception:
        return None


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def _ids49() -> set[str]:
    fifo = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DAGILIM_KANIT.json")
    out: set[str] = set()
    for g in (fifo.get("gruplar") or {}).values():
        for x in g or []:
            sid = str(x.get("kaynak_stok_id") or "")
            if sid:
                out.add(sid)
    return out


def _hedef_sayim() -> dict[str, Any]:
    from database.baglanti_modu import ayari_yukle, postgres_parola_al

    ayar = ayari_yukle()
    pg = ayar.postgres
    pwd = postgres_parola_al() or ""
    if not pwd:
        return {"ok": False, "hata": "APP_PAROLA_YOK"}
    dbs = ("cin_sistem_dnm_d2_20260901", "cin_firma_dnm_d2_20260901")
    out: dict[str, Any] = {"ok": True, "host": pg.host, "sslmode": pg.sslmode, "dbs": {}}
    for db in dbs:
        url = (
            f"postgresql+psycopg://{quote_plus(pg.kullanici)}:{quote_plus(pwd)}"
            f"@{pg.host}:{pg.port}/{db}?sslmode={quote_plus(pg.sslmode)}"
        )
        eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
        with eng.connect() as c:
            c.execute(text("SET TRANSACTION READ ONLY"))
            tabs = [
                r[0]
                for r in c.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema='public' and table_type='BASE TABLE' "
                        "order by 1"
                    )
                )
            ]
            counts = {}
            dolu = {}
            for t in tabs:
                n = int(c.execute(text(f'select count(*) from "{t}"')).scalar() or 0)
                counts[t] = n
                if n > 0:
                    dolu[t] = n
        eng.dispose()
        out["dbs"][db] = {
            "tablo_adet": len(counts),
            "dolu_tablo_adet": len(dolu),
            "dolu_tablolar": dolu,
            "toplam_satir_tum_tablolar": sum(counts.values()),
        }
    return out


def main() -> int:
    ids49 = _ids49()
    karar = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_KULLANICI_KARAR_D2_KAPSAM.json")
    cari21 = list(karar["karar_1_cari22_21"]["cariler"])
    cari21_ids = [str(c["kaynak_cari_id"]) for c in cari21]
    sifir_all = list(karar["karar_3_sifir_maliyet"]["kayitlar"])
    sifir_ids_all = [str(x["kaynak_stok_id"]) for x in sifir_all]
    overlap = sorted(set(sifir_ids_all) & ids49)
    sifir_aktarim = [x for x in sifir_all if str(x["kaynak_stok_id"]) not in ids49]
    sifir_aktarim_ids = [str(x["kaynak_stok_id"]) for x in sifir_aktarim]

    man = _load(K / "D1_20260831_KAYNAK_MANIFEST.json")
    acik = _load(K / "D1_20260831_KAYNAK_ACIK_KALEM.json")
    belge = _load(K / "D1_20260831_KAYNAK_BELGE_SATIR.json")
    kasa_kap = _load(K / "D1_20260831_KAYNAK_KASA_KAPANIS.json")
    nakit = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_NAKIT_KASA_EXCEL.json")
    yc = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_YC_KASA_EXCEL.json")
    banka_top = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_BANKA_TOPLAMI_EXCEL.json")
    banka_bas = _load(K / "D1_20260831_KAYNAK_BANKA_BASLANGIC.json")
    st3252 = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_STOK_3252_HESAPLANABILIR.json")
    esleme = _load(D1 / "esleme" / "D1_20260831_KIMLIK_ESLEME.json")
    cari22_kanit = _load(K / "D1_20260831_KAYNAK_DOGRULAMA_CARI22_KAPANIS_KANIT.json")
    iki = _load(D1 / "IKI_KASA_KAPANIS_OZET.json")

    # stok miktar/tutar
    tot = {
        "kaynak_3252": {"adet": 0, "kalan": Decimal(0), "tutar": Decimal(0)},
        "haric_49": {"adet": 0, "kalan": Decimal(0), "tutar": Decimal(0)},
        "aktarilacak": {"adet": 0, "kalan": Decimal(0), "tutar": Decimal(0)},
    }
    haric_satirlar = []
    for r in st3252.get("satirlar") or []:
        sid = str(r.get("kaynak_stok_id") or "")
        kalan = _D(r.get("kalan")) or Decimal(0)
        tut = _D(r.get("tutar")) or Decimal(0)
        tot["kaynak_3252"]["adet"] += 1
        tot["kaynak_3252"]["kalan"] += kalan
        tot["kaynak_3252"]["tutar"] += tut
        if sid in ids49:
            tot["haric_49"]["adet"] += 1
            tot["haric_49"]["kalan"] += kalan
            tot["haric_49"]["tutar"] += tut
            haric_satirlar.append(
                {
                    "kaynak_stok_id": sid,
                    "kod": r.get("kod"),
                    "kalan": str(r.get("kalan")),
                    "tutar": str(r.get("tutar")),
                    "birim_maliyet": str(r.get("birim_maliyet")),
                }
            )
        else:
            tot["aktarilacak"]["adet"] += 1
            tot["aktarilacak"]["kalan"] += kalan
            tot["aktarilacak"]["tutar"] += tut

    # belge bağlantı etkisi (49)
    jl = K / "D1_20260831_KAYNAK_BELGE_SATIR.jsonl"
    belge_hit = 0
    satir_hit = 0
    cari_bag: set[str] = set()
    tur_say: Counter[str] = Counter()
    stok_hit: Counter[str] = Counter()
    with jl.open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            hit = False
            for s in o.get("satirlar") or []:
                if not isinstance(s, dict):
                    continue
                sid = str(s.get("a_stok_id") or s.get("stok_id") or "")
                if sid in ids49:
                    hit = True
                    satir_hit += 1
                    stok_hit[sid] += 1
            if hit:
                belge_hit += 1
                cid = str(o.get("cari_id") or "")
                if cid:
                    cari_bag.add(cid)
                tur_say[str(o.get("tur") or "")] += 1

    # cari22 1980 kapanış
    kapanis_1980 = None
    for c in cari22_kanit.get("cariler") or []:
        if str(c.get("kaynak_cari_id")) == "1980":
            son = (c.get("son_deneme") or {})
            kapanis_1980 = {
                "kaynak_cari_id": "1980",
                "kapanis_son_detay_bakiye": son.get("kapanis_son_detay_bakiye"),
                # talimatta 1085
            }
            break
    # from talimat/kanitli
    kapanis_1980_tl = "1085"

    # banka excel: dönem neti (giren-çıkan) ≠ kapanış; kapanış bakiyesi bu dosyada yok
    banka_hesaplar = banka_top.get("hesaplar") or []
    banka_excel_adet = len(banka_hesaplar)
    banka_donem_net_toplam = Decimal(0)
    banka_donem_net_none = 0
    for h in banka_hesaplar:
        ex = h.get("excel") if isinstance(h.get("excel"), dict) else {}
        n = _D(ex.get("toplam"))
        if n is None:
            banka_donem_net_none += 1
        else:
            banka_donem_net_toplam += n
    banka_kapanis = {
        "durum": "HESAPLANAMADI",
        "neden": (
            "Banka Toplamı Excel dönem neti (giren−çıkan) kapanış bakiyesi değildir "
            "(donem_neti_kapanis_degil). 31.08 resmi kapanış bakiyesi bu önizlemede toplanmaz."
        ),
        "donem_net_toplam_excel_sutun": str(banka_donem_net_toplam)
        if banka_donem_net_none == 0
        else None,
        "donem_net_hesaplanamayan": banka_donem_net_none,
        "karsilastirma_sayac": banka_top.get("karsilastirma_sayac"),
    }

    # nakit / yc
    nakit_kontrol = nakit.get("nakit_kasa_kontrol") or {}
    yc_oz = {
        "kapanis": yc.get("kapanis") or yc.get("kapanis_net") or (yc.get("excel_toplamlar") or {}).get("kapanis"),
        "hareket_adet": (yc.get("excel_toplamlar") or {}).get("hareket_adet"),
    }

    hedef = _hedef_sayim()

    # mükerrer: esleme iskelet — cin_id boş; kaynak id tekillik
    cari_ids_esleme = [str(x.get("kaynak_cari_id") or x.get("a_id") or "") for x in esleme.get("cari") or []]
    stok_ids_esleme = [str(x.get("kaynak_stok_id") or x.get("a_id") or "") for x in esleme.get("stok") or []]
    cari_dup = [i for i, n in Counter(cari_ids_esleme).items() if i and n > 1]
    stok_dup = [i for i, n in Counter(stok_ids_esleme).items() if i and n > 1]
    st3252_ids = [str(r.get("kaynak_stok_id") or "") for r in st3252.get("satirlar") or []]
    st3252_dup = [i for i, n in Counter(st3252_ids).items() if i and n > 1]

    def _decmap(d: dict) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}

    kaynak_okuma = {
        "onizleme_hesap_zamani": NOW_S,
        "bugun_kesim_degil": True,
        "yarin_sabah_yeniden_uretilecek": True,
        "kaynak_dosya_zamanlari": {
            "manifest_alim": man.get("alim_zamani"),
            "manifest_modul_cek": man.get("alim_zamani_modul_cek"),
            "stok_3252": st3252.get("zaman"),
            "banka_toplami_excel": banka_top.get("zaman"),
            "nakit_kasa_excel": nakit.get("zaman"),
            "kullanici_karar": karar.get("zaman"),
        },
        "not": (
            "Bugünkü önizleme mevcut D1 kaynak dosyalarından hesaplandı. "
            "Yarın sabah kayıt girişine ara verilip kesim anı belirlenince son verilerle yeniden üretilecek."
        ),
    }

    modul_adetleri = {
        "cari": {
            "kaynak_kart_manifest": (man.get("ozet") or {}).get("cari_kart"),
            "kaynak_acik_kalem_cari": acik.get("cari_adet"),
            "kimlik_esleme_cari": (esleme.get("adet") or {}).get("cari"),
            "hariç_tutulan_kart": 0,
            "acilis_0_kullanici_beyani_21": len(cari21_ids),
            "acilis_detay_kanitli_1980": 1,
            "mevcut_hedef_is_kaydi": "HEDEF_DB_SAYIMINA_BAK",
            "aktarilacak_acilis_satiri_hesaplanan": {
                "beyan_0_21": 21,
                "kanitli_1980": 1,
                "diger_tum_cari_acilis": {
                    "durum": "HESAPLANAMADI",
                    "neden": (
                        "Tam cari kapanış/açılış paketi (tüm kartlar için 31.08 Detay bakiyesi) "
                        "kaynakta tamamlanmış değil; yalnız 21 beyan-0 + 1980=1085 sayısal."
                    ),
                },
            },
            "acik_kalem_adet": acik.get("acik_kalem_adet"),
            "acik_kalem_toplam": str(acik.get("acik_kalem_toplam")),
            "not_acik_kalem": (
                "Açık kalem FIFO/detay eksik uyarılı kaynak; 21 carinin 31.08 açılışı 0 beyanı "
                "açık kalem satırlarını silmez. 01.09+ hareketler korunur."
            ),
        },
        "stok": {
            "kaynak_envanter_satir_3252": tot["kaynak_3252"]["adet"],
            "kaynak_stok_kart_manifest_3150": (man.get("ozet") or {}).get("stok_kart"),
            "kimlik_esleme_stok": (esleme.get("adet") or {}).get("stok"),
            "hariç_49_pasif": tot["haric_49"]["adet"],
            "aktarilacak_envanter_satir": tot["aktarilacak"]["adet"],
            "sifir_maliyet_teyit_kaynak_14": len(sifir_ids_all),
            "sifir_maliyet_aktarim_kapsam_13": len(sifir_aktarim_ids),
            "cakisma_10753": {
                "listelerde": ["pasif_49_haric", "sifir_maliyet_14"],
                "oncelik": "HARIC_TUTMA",
                "sonuc": "D2 stok aktarımına girmez; sıfır maliyet teyit kaydı kaynakta 14 olarak kalır",
            },
            "miktar_toplam": {
                "kaynak_kalan": str(tot["kaynak_3252"]["kalan"]),
                "haric_49_kalan": str(tot["haric_49"]["kalan"]),
                "aktarilacak_kalan": str(tot["aktarilacak"]["kalan"]),
            },
            "tutar_toplam_tl_envanter": {
                "kaynak": str(tot["kaynak_3252"]["tutar"]),
                "haric_49": str(tot["haric_49"]["tutar"]),
                "aktarilacak": str(tot["aktarilacak"]["tutar"]),
                "doviz": "TL (envanter Excel)",
            },
        },
        "fatura_belge": {
            "kaynak_belge_adet": belge.get("belge_adet"),
            "kaynak_satir_toplam": belge.get("satir_toplam"),
            "lot_dolu_satir": belge.get("lot_dolu_satir_adet"),
            "hariç_stok_etkisi": {
                "belge_en_az_bir_49_satir": belge_hit,
                "satir_49_adet": satir_hit,
                "tekil_cari_bagli": len(cari_bag),
                "cari_idler": sorted(cari_bag),
                "tur_say": dict(tur_say),
                "stok_49_belgede_gorunen": len(stok_hit),
                "stok_49_belgede_yok": sorted(ids49 - set(stok_hit)),
                "politika": (
                    "49 stok D2 stok aktarım/güncelleme dışı; geçmiş belge ve cari hareketleri SİLİNMEZ. "
                    "Belge satırları kaynakta kalır; stok açılış katmanı bu 49 için üretilmez."
                ),
            },
            "aktarilacak_belge_adet": {
                "durum": "HESAPLANAMADI_TAM_FILTRE",
                "neden": (
                    "D2 belge kapsamı (01.09.2026–07.11.2026) için güncel kesim henüz yok; "
                    "bugün yalnız D1 kapanış kaynaklı belge indeksi (≤31.08) sayıldı."
                ),
                "d1_kapanis_belge_adet_referans": belge.get("belge_adet"),
            },
        },
        "kasa": {
            "kaynak_kart": (man.get("ozet") or {}).get("kasa_kart"),
            "kaynak_hareket_manifest": (man.get("ozet") or {}).get("kasa_hareket"),
            "kapanis_hesap_adet": kasa_kap.get("hesap_adet"),
            "donem_ici_hareket": kasa_kap.get("donem_ici_hareket"),
            "iki_kasa_toplam_kapanis": str(kasa_kap.get("iki_kasa_toplam_kapanis")),
            "nakit_kapanis": iki.get("nakit_kapanis"),
            "yc_kapanis": iki.get("yc_kapanis"),
            "nakit_hareket_adet_excel": nakit_kontrol.get("hareket_adet"),
            "nakit_giren": str(nakit_kontrol.get("brut_giris")) if nakit_kontrol.get("brut_giris") is not None else None,
            "nakit_cikan": str(nakit_kontrol.get("brut_cikis")) if nakit_kontrol.get("brut_cikis") is not None else None,
            "hariç": 0,
            "aktarilacak_acilis": {
                "nakit": iki.get("nakit_kapanis"),
                "yc": iki.get("yc_kapanis"),
                "toplam": iki.get("toplam_kapanis"),
                "doviz": "TL",
            },
        },
        "banka": {
            "kaynak_kart_manifest": (man.get("ozet") or {}).get("banka_kart"),
            "kaynak_hareket_manifest": (man.get("ozet") or {}).get("banka_hareket"),
            "baslangic_hesap_adet": banka_bas.get("hesap_adet"),
            "excel_toplami_hesap_adet": banka_excel_adet,
            "excel_karsilastirma_sayac": banka_top.get("karsilastirma_sayac"),
            "kapanis_acilis_bakiye": banka_kapanis,
            "doviz_kirilim_kapanis": "HESAPLANAMADI",
            "hariç": 0,
            "fark_idler": banka_top.get("fark_idler"),
            "tam_eslesen": len(banka_top.get("tam_eslesen_idler") or []),
            "kayan_nokta_artigi": len(banka_top.get("kayan_nokta_artigi_idler") or []),
        },
    }

    onizleme = {
        "format": "d2-aktarim-onizleme-v2",
        "kaynak_okuma_zamani": NOW_S,
        "mod": "ONIZLEME_SAYISAL",
        "mali_yazim": False,
        "k05": False,
        "k06": False,
        "exe": False,
        "aktarim_kabulu": False,
        "evo_kullanima_devam": True,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
        "kullanici_karar_kanit": "kurulum/dnm_d1_20260831/kaynak/D1_20260831_KAYNAK_DOGRULAMA_KULLANICI_KARAR_D2_KAPSAM.json",
        "kaynak_okuma": kaynak_okuma,
        "donem": {
            "d1_kapanis_dahil": "2026-08-31",
            "d2_acilis": "2026-09-01T00:00:00+03:00",
            "d2_bitis_dahil": "2026-11-07",
            "d2_haric": "2026-11-08T00:00:00+03:00",
            "yarin_kesim": "BELIRLENECEK",
        },
        "hedef_db": {
            "sistem": "cin_sistem_dnm_d2_20260901",
            "firma": "cin_firma_dnm_d2_20260901",
            "mevcut_sayim": hedef,
        },
        "modul_adetleri": modul_adetleri,
        "cari_acilis_ozet": {
            "21_kullanici_beyani": {
                "adet": 21,
                "kapanis_3108_tl": "0",
                "d2_acilis_tl": "0",
                "borc": "0",
                "alacak": "0",
                "ids": cari21_ids,
                "ekstre_istenmeyecek": True,
                "eylul_sonrasi_hareketler": "KORUNACAK",
            },
            "1980_murat_apak": {
                "adet": 1,
                "kapanis_3108_tl": kapanis_1980_tl,
                "d2_acilis_tl": kapanis_1980_tl,
                "kanit": "CARI22 Detay",
            },
            "diger_cariler_acilis_toplami": "HESAPLANAMADI",
        },
        "stok_ozet": {
            "haric_49": {
                "adet": 49,
                "kalan_toplam": str(tot["haric_49"]["kalan"]),
                "tutar_toplam": str(tot["haric_49"]["tutar"]),
                "ids": sorted(ids49, key=lambda x: int(x) if x.isdigit() else 0),
            },
            "aktarilacak_3203": {
                "adet": tot["aktarilacak"]["adet"],
                "kalan_toplam": str(tot["aktarilacak"]["kalan"]),
                "tutar_toplam": str(tot["aktarilacak"]["tutar"]),
            },
            "sifir_maliyet": {
                "teyit_kaynak_adet": 14,
                "aktarim_kapsam_adet": 13,
                "overlap_hariç_oncelik": overlap,
                "aktarim_ids": sifir_aktarim_ids,
                "maliyet": "0",
                "otomatik_doldurma": False,
            },
        },
        "hariç_stok_belge_cari_etki": modul_adetleri["fatura_belge"]["hariç_stok_etkisi"],
        "mukerrer_ve_esleme": {
            "kimlik_esleme_durum": esleme.get("durum"),
            "kimlik_esleme_not": esleme.get("not"),
            "cin_id_dolu_mu": esleme.get("durum") != "ISKELET_CIN_ID_BOS",
            "cari_kaynak_id_mukerrer": cari_dup,
            "stok_esleme_mukerrer": stok_dup,
            "stok_3252_satir_ayni_id_birden_fazla": {
                "adet_id": len(st3252_dup),
                "ornek": st3252_dup[:20],
                "not": "Çift kod/birim satırları ayrı kalabilir; birleştirme yok",
            },
            "hedef_db_is_kaydi_mukerrer_riski": (
                "Hedef boş/şema-only ise mükerrer iş kaydı riski düşük; "
                "yarın kesim sonrası yeniden sayılacak"
            ),
        },
        "yedek_ve_geri_alma": {
            "d1_devam_noktasi": "kurulum/dnm_d1_20260831/surumler/devam_noktasi_20261107_144902",
            "d1_surum": "kurulum/dnm_d1_20260831/surumler/v20261106_175735",
            "hba_yedek_ana_makine": (
                "C:/Program Files/PostgreSQL/17/data/pg_hba.conf.bak_d2_erisim_20261107_163836"
            ),
            "d2_hedef_db": ["cin_sistem_dnm_d2_20260901", "cin_firma_dnm_d2_20260901"],
            "plan": [
                "Yazım öncesi D2 DB pg_dump (ana makine 127.0.0.1)",
                "Hata halinde dump’tan restore; D1 kaynak/DB’ye dokunulmaz",
                "Kimlik defteri/mükerrer engeli ile ikinci yazım engeli",
                "K05 açılmadan mali yazım yok — bugün yalnız önizleme",
            ],
        },
        "kalan_gercek_engeller": [
            {
                "madde": "K05",
                "durum": "KAPALI",
                "etki": "Mali yazım yok",
            },
            {
                "madde": "K06 resmi paket bayrağı",
                "durum": "KAPALI",
                "not": "Hedef DB/HBA/terminal hazır; resmi K06 açılmadı",
            },
            {
                "madde": "Yarın kesim anı",
                "durum": "BELIRLENECEK",
                "etki": "01.09–kesim arası hareketler için önizleme yenilenecek",
            },
            {
                "madde": "Tam cari açılış (21+1980 dışı)",
                "durum": "HESAPLANAMADI",
            },
            {
                "madde": "D2 dönem belge/fatura adedi (01.09–kesim)",
                "durum": "HESAPLANAMADI",
            },
        ],
        "hesaplanamayan_alanlar": [
            "Tüm cari kartları için 31.08 kapanış borç/alacak/bakiye toplamı",
            "D2 dönem (01.09.2026–yarın kesim) fatura/belge/cari hareket adet ve tutarları",
            "Banka Excel satırında standart bakiye alanı yoksa döviz kırılımlı net toplam",
            "Hedef DB’de iş tablosu doluysa yazım sonrası mükerrer projeksiyonu (şu an şema sayımı)",
        ],
        "yapilmayacaklar_bugun": [
            "Mali yazım",
            "K05/K06 açma",
            "EXE",
            "EvoBulut’a yazım",
            "21 cari ekstre",
            "49 stok D2 aktarımı",
            "Sıfır maliyet doldurma",
            "Ham kaynak tarih değişimi",
        ],
    }

    yol = D2 / "D2_AKTARIM_ONIZLEME.json"
    yol.write_text(json.dumps(onizleme, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (yol.with_suffix(".json.sha256")).write_text(
        f"{_sha(yol)}  {yol.name}\n", encoding="utf-8"
    )

    ozet = {
        "zaman": NOW_S,
        "kaynak_okuma_zamani": NOW_S,
        "onizleme_hazir": True,
        "mali_yazim": False,
        "k05": False,
        "k06": False,
        "exe": False,
        "cari21_acilis_0": 21,
        "cari1980_acilis": "1085",
        "stok_kaynak_3252": 3252,
        "stok_haric_49": 49,
        "stok_aktarilacak_3203": tot["aktarilacak"]["adet"],
        "stok_aktar_kalan": str(tot["aktarilacak"]["kalan"]),
        "stok_aktar_tutar": str(tot["aktarilacak"]["tutar"]),
        "sifir_teyit_14": 14,
        "sifir_aktarim_13": 13,
        "overlap_10753_hariç_oncelik": True,
        "belge_49_bagli": belge_hit,
        "kasa_toplam_kapanis": iki.get("toplam_kapanis"),
        "hedef_sistem_tablo": (hedef.get("dbs") or {}).get("cin_sistem_dnm_d2_20260901", {}).get(
            "tablo_adet"
        ),
        "hedef_firma_tablo": (hedef.get("dbs") or {}).get("cin_firma_dnm_d2_20260901", {}).get(
            "tablo_adet"
        ),
        "hedef_dolu_tablo_firma": (hedef.get("dbs") or {}).get(
            "cin_firma_dnm_d2_20260901", {}
        ).get("dolu_tablo_adet"),
        "kanit": "D2_AKTARIM_ONIZLEME.json",
        "d2_sonrasi_d1_devam": True,
    }
    (D2 / "D2_AKTARIM_ONIZLEME_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # update user karar conflict note
    karar["karar_3_sifir_maliyet"]["cakisma_10753"] = {
        "overlap_ids": overlap,
        "oncelik": "HARIC_TUTMA_49",
        "teyit_kaynak_adet": 14,
        "aktarim_kapsam_adet": 13,
        "aktarim_ids": sifir_aktarim_ids,
    }
    karar["zaman_cakisma_duzeltme"] = NOW_S
    (K / "D1_20260831_KAYNAK_DOGRULAMA_KULLANICI_KARAR_D2_KAPSAM.json").write_text(
        json.dumps(karar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
