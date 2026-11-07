"""Kullanıcı kararları: Cari22×21=0, 49 pasif D2 dışı, sıfır maliyet teyit.

Ham kaynak tarihlerini değiştirmez. Mali yazım/K05/K06/EXE açmaz.
Tamamlanan toplamaları yeniden başlatmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kullanici_karar_d2_kapsam_uygula
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK

D2 = CALISMA.parent / "dnm_d2_20260901"
NOW = datetime.now().astimezone().isoformat(timespec="seconds")


def _load(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    talimat = _load(KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_CARI22_GERCEK_DETAY_RAPOR_TALIMAT.json")
    cari21 = list(talimat["hangi_cariler"]["kanitsiz_21"])
    cari21_ids = [str(c["kaynak_cari_id"]) for c in cari21]
    kanitli = list(talimat["hangi_cariler"]["kanitli_1_tekrar_gerekmez"])

    fifo = _load(KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_FIFO_DAGILIM_KANIT.json")
    ids49: list[str] = []
    for g in (fifo.get("gruplar") or {}).values():
        for x in g or []:
            sid = str(x.get("kaynak_stok_id") or "")
            if sid and sid not in ids49:
                ids49.append(sid)

    pasif = _load(KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_PASIF_DAHIL_ESLEME.json")
    sifir_kayitlar = list((pasif.get("sifir_maliyet") or {}).get("kayitlar") or [])

    karar = {
        "format": "d1-kullanici-karar-d2-kapsam-v1",
        "zaman": NOW,
        "kaynak": "KULLANICI_KESIN_BEYAN",
        "ham_kaynak_tarih_degistirilmedi": True,
        "yeniden_toplama_yok": True,
        "ekstre_istenmeyecek_cari21": True,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
        "karar_1_cari22_21": {
            "beyan": (
                "Cari22 listesindeki açık 21 cari 31.08.2026 sonrasında açılmıştır. "
                "31.08.2026 kapanış ve D2 açılış bakiyesi 0 TL kabul edilir."
            ),
            "kapanis_3108_tl": "0",
            "d2_acilis_tl": "0",
            "dayanak": "KULLANICI_BEYANI",
            "ekstre_toplama": False,
            "ozet_2295_vb_kapanis_sayilmaz": True,
            "korunan": (
                "01.09.2026 ve sonrası gerçek hareketler ve bunlardan oluşan bakiyeler korunur; "
                "ham kaynak tarihleri değiştirilmez."
            ),
            "cariler": [
                {
                    "kaynak_cari_id": c["kaynak_cari_id"],
                    "kod": c.get("kod"),
                    "unvan": c.get("unvan"),
                    "onceki_dogrulanmamis_ozet": c.get("dogrulanmamis_ozet_bakiye"),
                    "kapanis_3108": "0",
                    "d2_acilis": "0",
                    "durum": "KABUL_KULLANICI_BEYANI_SIFIR",
                }
                for c in cari21
            ],
            "kanitli_onceki_korunan": kanitli,
        },
        "karar_2_stok49_pasif_d2_disi": {
            "beyan": (
                "Mevcut 49 pasif stok listesi D2 stok aktarımı ve güncellemesi kapsamından çıkarılır. "
                "Bunlara bağlı FIFO/LOT kontrolleri D2’yi bekleten iş olmaktan çıkarılır."
            ),
            "dayanak": "KULLANICI_KARARI",
            "d2_stok_aktarim_kapsaminda": False,
            "d2_bekletmez": True,
            "gecmis_belge_silinmedi": True,
            "cari_hareket_silinmedi": True,
            "fifo_lot_kanitlari_korundu": True,
            "stok_ids": ids49,
            "adet": len(ids49),
            "onceki_kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DAGILIM_KANIT.json",
        },
        "karar_3_sifir_maliyet": {
            "beyan": (
                "Sıfır maliyet kayıtları kullanıcı tarafından doğru olarak teyit edilmiştir. "
                "Sıfır maliyetler aynen korunur; otomatik maliyet doldurma yapılmaz."
            ),
            "dayanak": "KULLANICI_TEYIDI",
            "otomatik_maliyet_doldurma": False,
            "adet": len(sifir_kayitlar),
            "kayitlar": [
                {
                    "kaynak_stok_id": x.get("kaynak_stok_id"),
                    "kod": x.get("kod"),
                    "sinif": x.get("sinif"),
                    "maliyet_korunan": "0",
                    "durum": "KABUL_KULLANICI_TEYIDI",
                }
                for x in sifir_kayitlar
            ],
            "onceki_kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_49_PASIF_DAHIL_ESLEME.json",
        },
    }

    karar_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_KULLANICI_KARAR_D2_KAPSAM.json"
    yaz_json(karar_yol, karar)
    (karar_yol.with_suffix(".json.sha256")).write_text(
        f"{_sha(karar_yol)}  {karar_yol.name}\n", encoding="utf-8"
    )

    # --- Cari22 talimat / özet güncelle ---
    talimat["zaman_kullanici_karar"] = NOW
    talimat["durum"] = "KAPANDI_KULLANICI_BEYANI_SIFIR"
    talimat["kanitsiz_adet_guncel"] = 0
    talimat["kapanis_kullanici_beyani"] = {
        "adet": len(cari21_ids),
        "kapanis_3108": "0",
        "d2_acilis": "0",
        "ids": cari21_ids,
        "kanit": str(karar_yol.relative_to(CALISMA.parent.parent)).replace("\\", "/"),
        "ekstre_istenmeyecek": True,
    }
    talimat["hangi_cariler"]["kanitsiz_21_onceki"] = cari21
    talimat["hangi_cariler"]["kabul_kullanici_beyani_sifir_21"] = karar["karar_1_cari22_21"]["cariler"]
    talimat["hangi_cariler"]["kanitsiz_21"] = []
    yaz_json(
        KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_CARI22_GERCEK_DETAY_RAPOR_TALIMAT.json",
        talimat,
    )
    yaz_json(
        CALISMA / "CARI22_GERCEK_DETAY_RAPOR_TALIMAT_OZET.json",
        {
            "zaman": NOW,
            "durum": "KAPANDI_KULLANICI_BEYANI_SIFIR",
            "kanitsiz_cari_adet": 0,
            "kabul_sifir_adet": 21,
            "kanitli_detay_onceki": 1,
            "kapanis_3108": "0",
            "d2_acilis": "0",
            "ekstre_istenmeyecek": True,
            "ids": cari21_ids,
            "kanit": f"kaynak/{karar_yol.name}",
            "k05": False,
        },
    )

    # --- Açık envanter ---
    env = _load(KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_D1_D2_ACIK_ENVANTER.json")
    for a in env.get("aciklar") or []:
        madde = a.get("madde") or ""
        if "Cari22" in madde or "açık kalem Detay" in madde:
            a["durum"] = "KABUL_KULLANICI_BEYANI_SIFIR"
            a["aktarimi_engeller"] = False
            a["eksik_kaynak_belgesi"] = "—"
            a["yapilacak"] = (
                "21 cari 31.08/D2 açılış=0 (kullanıcı beyanı). "
                "01.09+ hareketler korunur; ekstre yok; ham tarih değişmez."
            )
            a["neden_engel"] = None
            a["cari22_kanitsiz"] = 0
            a["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
        elif "49 pasif" in madde or "FIFO katman" in madde:
            a["durum"] = "D2_KAPSAM_DISI_KULLANICI_KARARI"
            a["aktarimi_engeller"] = False
            a["eksik_kaynak_belgesi"] = "—"
            a["yapilacak"] = (
                "49 pasif stok D2 aktarım/güncelleme dışı; FIFO/LOT D2 bekletmez. "
                "Geçmiş belge/cari silinmedi; kanıtlar korundu."
            )
            a["neden_engel"] = None
            a["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
        elif madde.startswith("LOT katman"):
            a["durum"] = "D2_49_ILE_BIRLIKTE_BEKLETMEZ"
            a["aktarimi_engeller"] = False
            a["yapilacak"] = (
                "49 pasif D2 dışı; genel LOT maliyet D1 devamında. D2 bekletmez (kullanıcı kararı)."
            )
            a["neden_engel"] = None
            a["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
        elif "Sıfır maliyet" in madde:
            a["durum"] = "KABUL_KULLANICI_TEYIDI"
            a["aktarimi_engeller"] = False
            a["eksik_kaynak_belgesi"] = "—"
            a["yapilacak"] = "Sıfır maliyet aynen; otomatik doldurma yok (kullanıcı teyidi)."
            a["neden_engel"] = None
            a["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
        elif madde.startswith("K05"):
            a["durum"] = "KAPALI"
            a["aktarimi_engeller"] = True
            a["yapilacak"] = "Önizleme hazır; gerçek mali yazım için K05 hâlâ kapalı"
        elif madde.startswith("K06"):
            # Ana makine DB+HBA+terminal salt okuma tamam — izole hedef hazır
            a["durum"] = "HEDEF_HAZIR_K06_PAKET_RESMI_ACIK_DEGIL"
            a["aktarimi_engeller"] = False
            a["yapilacak"] = (
                "D2 DB/schema/HBA/terminal salt-okuma kanıtlı. "
                "Resmi K06 paket bayrağı kapalı; önizleme engellemez."
            )
            a["neden_engel"] = None
            a["kanit_guncel"] = [
                "kurulum/dnm_d2_20260901/ANA_MAKINE_HAZIRLIK_RAPORU.json",
                "kurulum/dnm_d2_20260901/yedek/HBA_SONUC_20261107_163837.json",
                "kurulum/dnm_d2_20260901/yedek/ASAMA_TERMINAL_BAGLANTI_TAMAM.json",
            ]

    engel = sum(1 for a in env.get("aciklar") or [] if a.get("aktarimi_engeller"))
    env["zaman"] = NOW
    env["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
    env["ozet"] = {
        "aktarim_engeli_adet": engel,
        "engellemez_adet": sum(
            1 for a in env.get("aciklar") or [] if not a.get("aktarimi_engeller")
        ),
        "kaynak_d1_engel_kullanici_karari_ile_kaldirildi": True,
        "kalan_gercek_engel": [
            a.get("madde")
            for a in env.get("aciklar") or []
            if a.get("aktarimi_engeller")
        ],
    }
    env["k05"] = False
    env["k06"] = False
    env["mali_yazim"] = False
    env["exe"] = False
    yaz_json(KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_D1_D2_ACIK_ENVANTER.json", env)
    yaz_json(
        CALISMA / "D1_D2_ACIK_ENVANTER_OZET.json",
        {
            "zaman": NOW,
            "acik_adet": len(env.get("aciklar") or []),
            "aktarim_engeli": engel,
            "cari22_kanitsiz": 0,
            "cari22_kabul_sifir": 21,
            "stok49_d2_kapsam_disi": True,
            "sifir_maliyet_kullanici_teyidi": True,
            "k05": False,
            "k06": False,
            "mali_yazim": False,
            "exe": False,
            "kanit": f"kaynak/{karar_yol.name}",
        },
    )

    # --- DEVIR1 devam notu (d2 zorunlu maddeler) ---
    notu_p = CALISMA / "DEVIR1_DEVAM_NOTU.json"
    if notu_p.exists():
        notu = _load(notu_p)
        for m in notu.get("d2_acilisi_icin_zorunlu_d1") or []:
            mad = m.get("madde") or ""
            if "Cari22" in mad:
                m["durum"] = "KABUL_KULLANICI_BEYANI_SIFIR"
                m["kanit"] = f"kaynak/{karar_yol.name}"
            elif "49 FIFO" in mad or "FIFO" in mad:
                m["durum"] = "D2_KAPSAM_DISI_KULLANICI_KARARI"
                m["kanit"] = f"kaynak/{karar_yol.name}"
            elif "Sıfır maliyet" in mad or "Sifir" in mad:
                m["durum"] = "KABUL_KULLANICI_TEYIDI"
                m["kanit"] = f"kaynak/{karar_yol.name}"
            elif "K05" in mad:
                m["durum"] = "KAPALI"
            elif "K06" in mad:
                m["durum"] = "HEDEF_HAZIR_ONIZLEME_ENGELLEMEZ"
        notu["zaman_kullanici_karar"] = NOW
        notu["kullanici_karar_kanit"] = f"kaynak/{karar_yol.name}"
        notu["k05"] = False
        notu["k06"] = False
        notu["mali_yazim"] = False
        notu["exe"] = False
        yaz_json(notu_p, notu)
        md = CALISMA / "DEVIR1_DEVAM_NOTU.md"
        if md.exists():
            ekstra = (
                f"\n\n## Kullanıcı kararları ({NOW[:10]})\n"
                f"- Cari22×21: 31.08/D2 açılış **0 TL** (beyan); 01.09+ hareketler korunur.\n"
                f"- 49 pasif stok: **D2 aktarım dışı**; FIFO/LOT D2 bekletmez.\n"
                f"- Sıfır maliyet 14: **kullanıcı teyidi** — doldurma yok.\n"
                f"- Kanıt: `kaynak/{karar_yol.name}`\n"
                f"- D2 sonrası D1 devam geçerli. K05/mali/EXE kapalı.\n"
            )
            txt = md.read_text(encoding="utf-8")
            if "Kullanıcı kararları" not in txt:
                md.write_text(txt.rstrip() + ekstra, encoding="utf-8")

    # --- D2 hazırlık raporları ---
    haz = _load(D2 / "D2_HAZIRLIK_DURUM_RAPORU.json") if (D2 / "D2_HAZIRLIK_DURUM_RAPORU.json").exists() else {}
    haz["zaman"] = NOW
    haz["kullanici_karar_kanit"] = f"../dnm_d1_20260831/kaynak/{karar_yol.name}"
    haz["gercek_aktarimi_engelleyen_d1_aciklar"] = [
        {
            "madde": "Cari22×21",
            "durum": "KABUL_KULLANICI_BEYANI_SIFIR",
            "kapanis_3108": "0",
            "d2_acilis": "0",
            "korunan": "01.09.2026+ hareketler",
        },
        {
            "madde": "Stok 49 pasif FIFO/LOT",
            "durum": "D2_KAPSAM_DISI_KULLANICI_KARARI",
            "d2_bekletmez": True,
            "adet": len(ids49),
        },
        {
            "madde": "Sıfır maliyet 14",
            "durum": "KABUL_KULLANICI_TEYIDI",
            "otomatik_doldurma": False,
        },
        {
            "madde": "K05",
            "durum": "KAPALI",
            "etki": "Gerçek mali yazım yok; yalnız önizleme",
        },
        {
            "madde": "K06 resmi bayrak",
            "durum": "HEDEF_HAZIR_BAYRAK_KAPALI",
            "etki": "DB/HBA/terminal hazır; resmi K06 paket açılmadı",
        },
    ]
    haz["kullanicidan_somut"] = [
        "Kullanıcı kararları uygulandı (Cari22×21=0, 49 D2 dışı, sıfır maliyet teyit).",
        "D2 aktarım önizlemesi hazır — mali yazım/K05 kapalı.",
        "D2 sonrası D1 devam: DEVIR1_DEVAM_NOTU.",
    ]
    haz["korunan"] = {
        **(haz.get("korunan") or {}),
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
        "aktarim_kabulu": False,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
    }
    haz["acik_envanter"] = {
        "zaman": NOW,
        "aktarim_engeli": engel,
        "cari22_kanitsiz": 0,
        "cari22_kabul_sifir": 21,
        "stok49_d2_kapsam_disi": True,
        "sifir_maliyet_teyit": True,
        "k05": False,
        "kanit": f"../dnm_d1_20260831/kaynak/{karar_yol.name}",
    }
    yaz_json(D2 / "D2_HAZIRLIK_DURUM_RAPORU.json", haz)

    # --- Aktarım önizleme (yazım yok) ---
    onizleme = {
        "format": "d2-aktarim-onizleme-v1",
        "zaman": NOW,
        "mod": "ONIZLEME",
        "mali_yazim": False,
        "k05": False,
        "k06": False,
        "exe": False,
        "aktarim_kabulu": False,
        "d1_koruma": True,
        "d2_sonrasi_d1_devam": True,
        "kullanici_karar_kanit": f"../dnm_d1_20260831/kaynak/{karar_yol.name}",
        "hedef_db": {
            "sistem": "cin_sistem_dnm_d2_20260901",
            "firma": "cin_firma_dnm_d2_20260901",
            "altyapi": "OLUSTURULDU+HBA+TERMINAL_SALT_OKUMA",
        },
        "donem": {
            "d1_kapanis_dahil": "2026-08-31",
            "d2_acilis": "2026-09-01T00:00:00+03:00",
            "d2_bitis_dahil": "2026-11-07",
            "d2_haric": "2026-11-08T00:00:00+03:00",
        },
        "kapsam": {
            "cari_acilis": {
                "cari22_21_kullanici_beyani_sifir": {
                    "adet": 21,
                    "acilis_tl": "0",
                    "ids": cari21_ids,
                    "not": "01.09.2026+ gerçek hareketler ayrı korunur / aktarılır",
                },
                "cari22_kanitli_detay": {
                    "adet": 1,
                    "ornek": kanitli,
                    "not": "1980 Detay kapanış korundu",
                },
            },
            "stok": {
                "genel_kimlik_3252_korunur": True,
                "pasif_49_aktarim_disi": {
                    "adet": len(ids49),
                    "ids": ids49,
                    "gerekce": "KULLANICI_KARARI",
                },
                "sifir_maliyet_14": {
                    "adet": len(sifir_kayitlar),
                    "maliyet": "0",
                    "doldurma_yok": True,
                    "dayanak": "KULLANICI_TEYIDI",
                    "ids": [str(x.get("kaynak_stok_id")) for x in sifir_kayitlar],
                },
            },
        },
        "kalan_gercek_engeller": env["ozet"]["kalan_gercek_engel"],
        "onizleme_hazir": engel <= 1 and all(
            ("K05" in (x or "")) for x in (env["ozet"]["kalan_gercek_engel"] or [""])
        )
        or (engel == 1 and env["ozet"]["kalan_gercek_engel"] == ["K05 kaynak kontrolü"])
        or (
            engel >= 1
            and all(str(x).startswith("K05") for x in env["ozet"]["kalan_gercek_engel"])
        ),
        "sonraki_adim": (
            "Önizleme içeriği onaylandıktan sonra K05 açılmadan mali yazım yapılmaz. "
            "Kullanıcı K05/mali yazım izni verene kadar yalnız plan/önizleme."
        ),
        "yapilmayacaklar": [
            "Mali yazım",
            "EXE rebuild zorunlu değil (yalnız rapor)",
            "Ham kaynak tarih değişimi",
            "49 pasif stok D2 aktarımı",
            "Sıfır maliyeti otomatik doldurma",
            "21 cari için ekstre toplama",
        ],
    }
    # Simplify onizleme_hazir: true if only K05 remains as engel
    kalan = [x for x in (env["ozet"]["kalan_gercek_engel"] or []) if x]
    onizleme["onizleme_hazir"] = bool(kalan) and all(
        str(x).startswith("K05") for x in kalan
    ) or (len(kalan) == 0)
    if not kalan:
        onizleme["onizleme_hazir"] = True
    elif all("K05" in str(x) for x in kalan):
        onizleme["onizleme_hazir"] = True
        onizleme["not"] = "Kaynak D1 engelleri kalktı; yalnız K05 mali yazım kapısı kapalı — önizleme serbest."
    else:
        onizleme["onizleme_hazir"] = False

    yaz_json(D2 / "D2_AKTARIM_ONIZLEME.json", onizleme)
    yaz_json(
        D2 / "D2_AKTARIM_ONIZLEME_OZET.json",
        {
            "zaman": NOW,
            "onizleme_hazir": onizleme["onizleme_hazir"],
            "mali_yazim": False,
            "k05": False,
            "cari21_acilis_0": 21,
            "stok49_d2_disi": len(ids49),
            "sifir_maliyet_teyit": len(sifir_kayitlar),
            "kalan_engel": kalan,
            "kanit": "D2_AKTARIM_ONIZLEME.json",
            "kullanici_karar": f"../dnm_d1_20260831/kaynak/{karar_yol.name}",
            "d2_sonrasi_d1_devam": True,
        },
    )
    yaz_json(
        D2 / "HAZIRLIK_OZET.json",
        {
            "zaman": NOW,
            "D2_BITIS_DAHIL": "2026-11-07",
            "D2_HARIC_UST_SINIR": "2026-11-08T00:00:00+03:00",
            "bitis_sabitlendi": True,
            "aktarim_kabulu": False,
            "onizleme_hazir": onizleme["onizleme_hazir"],
            "k05": False,
            "k06": False,
            "mali_yazim": False,
            "kullanici_karar_uygulandi": True,
        },
    )

    yaz_json(
        CALISMA / "KULLANICI_KARAR_D2_KAPSAM_OZET.json",
        {
            "zaman": NOW,
            "cari21_kapanis_0": 21,
            "stok49_d2_disi": len(ids49),
            "sifir_maliyet_teyit": len(sifir_kayitlar),
            "aktarim_engeli_kalan": kalan,
            "onizleme": "kurulum/dnm_d2_20260901/D2_AKTARIM_ONIZLEME.json",
            "kanit": f"kaynak/{karar_yol.name}",
            "k05": False,
            "mali_yazim": False,
            "d2_sonrasi_d1_devam": True,
        },
    )

    print(
        json.dumps(
            {
                "karar": str(karar_yol),
                "engel_kalan": kalan,
                "onizleme_hazir": onizleme["onizleme_hazir"],
                "cari21": len(cari21_ids),
                "stok49": len(ids49),
                "sifir": len(sifir_kayitlar),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
