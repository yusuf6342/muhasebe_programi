"""D1 devam notu + çalışma yedeği doğrulama — D2 öncesi kayıt noktası.

Karar: Devir 2 sonrasında Devir 1 çalışmasına devam edilecek.
D1 kod/kaynak/eşleme/kanıt/DB korunur; D2 ayrı kök/hedef.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.devir1_devam_notu
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from tools.dnm_d1._ortak import CALISMA, KAYNAK, SURUMLER, yaz_json
from tools.dnm_d1.donem_sabitleri import (
    DONEM_SONU,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
)

D2 = CALISMA.parent / "dnm_d2_20260901"

# Kritik D1 artefaktlar — yedek doğrulama + devam noktası
KRITIK = [
    "DURUM.json",
    "CALISMA_MANIFESTI.json",
    "KONTROL_PLANI_DURUM.json",
    "D1_D2_ACIK_ENVANTER_OZET.json",
    "STOK_3252_HESAPLANABILIR_OZET.json",
    "IKI_KASA_KAPANIS_OZET.json",
    "STOK_49_FIFO_HAREKET_KATMAN_OZET.json",
    "STOK_49_FIFO_DAGILIM_KANIT_OZET.json",
    "CARI22_KAPANIS_KANIT_OZET.json",
    "CARI22_GERCEK_DETAY_RAPOR_TALIMAT_OZET.json",
    "CARI_ACIK_KALEM_DILIM_DUZELT_OZET.json",
    "POS_CIFT_SAYIM_FINANS_KAPSAM_OZET.json",
    "AKBANK_4355_POS_VALOR_D2_OZET.json",
    "VAKIFBANK_EKSTRE_EXCEL_OZET.json",
    "BANKA_TOPLAMI_EXCEL_OZET.json",
    "DEVIR1_DEVAM_OZET.json",
    "surumler/SON_SURUM.json",
    "esleme/D1_20260831_KIMLIK_ESLEME.json",
    "plan/D1_20260831_AKTARIM_PLANI.json",
    "kaynak/D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json",
    "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_49_FIFO_DAGILIM_KANIT.json",
    "kaynak/D1_20260831_KAYNAK_DOGRULAMA_CARI22_GERCEK_DETAY_RAPOR_TALIMAT.json",
]


def _sha_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _yedek_dogrula() -> dict:
    son = {}
    son_yol = SURUMLER / "SON_SURUM.json"
    if son_yol.is_file():
        son = json.loads(son_yol.read_text(encoding="utf-8"))
    surum_id = son.get("surum_id")
    surum_yol = Path(son["yol"]) if son.get("yol") else None
    if surum_yol and not surum_yol.is_absolute():
        surum_yol = CALISMA / surum_yol
    if not surum_yol or not surum_yol.is_dir():
        aday = SURUMLER / (surum_id or "")
        surum_yol = aday if aday.is_dir() else None

    dosya_adet = 0
    man = {}
    if surum_yol and surum_yol.is_dir():
        dosya_adet = sum(1 for p in surum_yol.rglob("*") if p.is_file())
        man_yol = surum_yol / "SURUM_MANIFEST.json"
        if man_yol.is_file():
            man = json.loads(man_yol.read_text(encoding="utf-8"))

    kritik_durum = []
    eksik = []
    for rel in KRITIK:
        p = CALISMA / rel
        sha = _sha_file(p)
        row = {
            "dosya": rel,
            "var": sha is not None,
            "boyut": p.stat().st_size if p.is_file() else 0,
            "sha256_16": (sha or "")[:16] or None,
        }
        kritik_durum.append(row)
        if not row["var"]:
            eksik.append(rel)

    ok = surum_yol is not None and dosya_adet > 0 and not eksik
    return {
        "ok": ok,
        "son_basarili_surum": {
            "surum_id": surum_id,
            "yol": str(surum_yol) if surum_yol else None,
            "dosya_adet": dosya_adet,
            "manifest_format": man.get("format"),
            "manifest_zaman": man.get("zaman"),
        },
        "kritik_artefakt": kritik_durum,
        "kritik_eksik": eksik,
        "d1_db_onerilen": {
            "sistem": ONERILEN_SISTEM_DB,
            "firma": ONERILEN_FIRMA_DB,
            "not": "D1 DB temizlenmez / D2’ye dönüştürülmez / üzerine restore yok",
        },
        "d2_ayri": {
            "kok": "kurulum/dnm_d2_20260901",
            "sistem": "cin_sistem_dnm_d2_20260901",
            "firma": "cin_firma_dnm_d2_20260901",
        },
    }


def _devam_noktasi_yaz(yedek: dict) -> dict:
    """Hafif kayıt noktası: kritik JSON kopyası + envanter (büyük kaynak dump yok)."""
    etiket = datetime.now().strftime("%Y%m%d_%H%M%S")
    hedef = SURUMLER / f"devam_noktasi_{etiket}"
    hedef.mkdir(parents=True, exist_ok=True)
    kopyalanan = []
    for rel in KRITIK:
        src = CALISMA / rel
        if not src.is_file():
            continue
        dst = hedef / rel.replace("/", "__")
        shutil.copy2(src, dst)
        kopyalanan.append(
            {
                "kaynak": rel,
                "kopya": dst.name,
                "sha256_16": (_sha_file(dst) or "")[:16],
                "boyut": dst.stat().st_size,
            }
        )
    meta = {
        "format": "d1-devam-noktasi-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "etiket": etiket,
        "karar": "D2 sonrasında D1 devam",
        "yedek_dogrulama": {
            "ok": yedek.get("ok"),
            "son_surum": yedek.get("son_basarili_surum"),
        },
        "kopyalanan": kopyalanan,
        "buyuk_kaynak_referans": "canlı kurulum/dnm_d1_20260831/kaynak + surumler/v20261106_175735",
        "koruma": {
            "d1_temizleme_yok": True,
            "d1_d2_donusum_yok": True,
            "d1_uzerine_restore_yok": True,
            "d2_ayri_kok": True,
        },
    }
    (hedef / "DEVAM_NOKTASI_MANIFEST.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SURUMLER / "SON_DEVAM_NOKTASI.json").write_text(
        json.dumps(
            {
                "etiket": etiket,
                "yol": str(hedef),
                "zaman": meta["zaman"],
                "kopya_adet": len(kopyalanan),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return meta


def _notu_olustur(yedek: dict, nokta: dict) -> dict:
    acik = {}
    acik_yol = KAYNAK / "D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json"
    if acik_yol.is_file():
        acik = json.loads(acik_yol.read_text(encoding="utf-8"))

    tamam = [
        {
            "madde": "Stok kimlik 3252 (ARA55 dahil)",
            "durum": "TAMAM_KORU",
            "kanit": "STOK_3252_HESAPLANABILIR_OZET.json",
            "yeniden_toplama": False,
        },
        {
            "madde": "Kasa nakit + YC kapanış",
            "durum": "TAMAM_KORU",
            "kanit": "IKI_KASA_KAPANIS_OZET.json",
            "yeniden_toplama": False,
        },
        {
            "madde": "49 pasif stok eşleme / birim test",
            "durum": "TAMAM_KORU",
            "kanit": "STOK_49_PASIF_DAHIL_ESLEME_OZET.json",
        },
        {
            "madde": "Banka Toplamı Excel + Vakıfbank ekstre + Akbank 4355 kök",
            "durum": "TAMAM_KISMI_KORU",
            "kanit": "BANKA_TOPLAMI_EXCEL_OZET.json / VAKIFBANK / AKBANK_4355",
        },
        {
            "madde": "POS çift sayım kuralı",
            "durum": "KURAL_KORUNDU",
            "not": "Liste tamam değil; finans kapsam ayrı",
            "kanit": "POS_CIFT_SAYIM_FINANS_KAPSAM_OZET.json",
        },
        {
            "madde": "Cari22 kanıtlı 1 (1980)",
            "durum": "TAMAM",
            "kanit": "CARI22_KAPANIS_KANIT_OZET.json",
        },
        {
            "madde": "Kaynak sürüm paketi v20261106_175735",
            "durum": "KAYIT_NOKTASI",
            "kanit": "surumler/v20261106_175735",
        },
    ]

    # D2 açılışı için zorunlu D1 (öncelik)
    d2_zorunlu = [
        {
            "oncelik": 1,
            "madde": "Cari22 / 21 kanıtsız — gerçek Hesap Ekstresi Detay",
            "durum": "AÇIK",
            "d2_etki": "D2 08–11 açık kalem / valör açılışı",
            "kanit": "CARI22_GERCEK_DETAY_RAPOR_TALIMAT_OZET.json",
        },
        {
            "oncelik": 2,
            "madde": "49 FIFO katman değer farkı (15) + doğrulanamayan (3) + LOT maliyet",
            "durum": "KISMI",
            "d2_etki": "D2 12–16 / 13/27 açılış katman maliyeti",
            "kanit": "STOK_49_FIFO_DAGILIM_KANIT_OZET.json",
        },
        {
            "oncelik": 3,
            "madde": "Sıfır maliyet 14 (bilinmeyen bırak; uydurma yok)",
            "durum": "SINIFLI",
            "d2_etki": "Provisional açılış riski",
        },
        {
            "oncelik": 4,
            "madde": "K05 kaynak kontrol paketi",
            "durum": "KAPALI",
            "d2_etki": "Gerçek D2 açılış/hareket yazımı önkoşulu",
        },
        {
            "oncelik": 5,
            "madde": "K06 izole yedek (D1 ve D2 ayrı hedefler)",
            "durum": "AÇIK",
            "d2_etki": "Boş D2 hedef + restore; D1 DB üzerine yazılmaz",
        },
    ]

    # D2 sonrası sürdürülecek diğer D1 işleri
    d2_sonrasi = [
        {
            "madde": "PDF Devirli 1070−1066 isim↔ID eşleme (birleştirme yok)",
            "durum": "KAYITLI",
            "kanit": "PDF_DEVIRLI_RAPOR_OZET.json",
        },
        {
            "madde": "Stok kapsam fark sınıfları (3150 hareket / kart dolu farklar)",
            "durum": "KAYITLI",
            "kanit": "KAYNAK_DOGRULAMA_DEVAM2_OZET.json",
        },
        {
            "madde": "POS bekleyen tam liste (Yapı Kredi / Halkbank + finans kapsam)",
            "durum": "KAYITLI",
            "kanit": "POS_CIFT_SAYIM_FINANS_KAPSAM_OZET.json",
        },
        {
            "madde": "Risk21 / PDF cari eşleme adayları",
            "durum": "KAYITLI",
            "kanit": "DEVIR1_DEVAM_OZET.json",
        },
        {
            "madde": "D1 boş PG hedef (cin_*_dnm_d1_20260831) — D2’den ayrı",
            "durum": "KAYITLI",
            "kanit": "10_pg_dnm_d1_bos_hedef.ps1",
        },
        {
            "madde": "EXE / dağıtım",
            "durum": "ERTELI_SONRA",
        },
    ]

    return {
        "format": "d1-devir1-devam-notu-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "karar": {
            "metin": "Devir 2 sonrasında Devir 1 çalışmasına devam edilecek",
            "kesin": True,
            "karar_tarihi": "2026-11-07",
        },
        "firma": {"no": KAYNAK_FIRMA_NO, "adi": KAYNAK_FIRMA_ADI},
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "koruma": {
            "d1_kod": "tools/dnm_d1 + ilgili UI/servis kontrolleri",
            "d1_kaynak": "kurulum/dnm_d1_20260831/kaynak",
            "d1_esleme": "kurulum/dnm_d1_20260831/esleme",
            "d1_kanit": "kurulum/dnm_d1_20260831/*OZET.json + kaynak/DOGRULAMA_*",
            "d1_db": [ONERILEN_SISTEM_DB, ONERILEN_FIRMA_DB],
            "d1_temizleme_yok": True,
            "d1_d2_donusum_yok": True,
            "d1_uzerine_restore_yok": True,
            "ortak_kodda_d1_kontrolleri_korunur": True,
            "d2_ayri_kok": "kurulum/dnm_d2_20260901",
            "d2_ayri_db": [
                "cin_sistem_dnm_d2_20260901",
                "cin_firma_dnm_d2_20260901",
                "cin_sistem_dnm_d2_restore_test",
                "cin_firma_dnm_d2_restore_test",
            ],
        },
        "yedek_dogrulama": yedek,
        "devam_noktasi": {
            "etiket": nokta.get("etiket"),
            "yol": f"surumler/devam_noktasi_{nokta.get('etiket')}",
            "kopya_adet": len(nokta.get("kopyalanan") or []),
        },
        "son_basarili_kayit_noktalari": [
            {
                "tip": "kaynak_surum",
                "id": (yedek.get("son_basarili_surum") or {}).get("surum_id"),
                "yol": "surumler/v20261106_175735",
            },
            {
                "tip": "devam_noktasi",
                "id": nokta.get("etiket"),
                "yol": f"surumler/devam_noktasi_{nokta.get('etiket')}",
            },
            {
                "tip": "stok_3252",
                "kanit": "STOK_3252_HESAPLANABILIR_OZET.json",
            },
            {
                "tip": "kasa",
                "kanit": "IKI_KASA_KAPANIS_OZET.json",
            },
            {
                "tip": "fifo49_dagilim",
                "kanit": "STOK_49_FIFO_DAGILIM_KANIT_OZET.json",
                "ozet": "20 OK / 15 fark / 3 doğrulanamadı / 11 sıfır",
            },
        ],
        "kullanilan_surumler": {
            "kaynak_paket": (yedek.get("son_basarili_surum") or {}).get("surum_id"),
            "calisma_id": None,  # DURUM’dan doldurulur
            "d2_calisma": "kurulum/dnm_d2_20260901 (ayrı)",
        },
        "tamamlanan_isler": tamam,
        "d2_acilisi_icin_zorunlu_d1": d2_zorunlu,
        "d2_sonrasi_surdurulecek_d1": d2_sonrasi,
        "sonradan_bulunan_kayit_kurali": {
            "aciklama": (
                "D1 kapanışını etkileyen sonradan bulunan kayıt, D2 açılışına "
                "etkisini kontrollü sürüm değişikliği olarak raporlanır; "
                "sessiz düzeltme / mükerrer mali etki yok."
            ),
            "rapor_alani": "kontrollu_surum_degisikligi",
            "d2_etki_raporu_zorunlu": True,
        },
        "acik_envanter_ozet": {
            "acik_adet": len(acik.get("aciklar") or []),
            "aktarim_engeli": (acik.get("ozet") or {}).get("aktarim_engeli_adet"),
            "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json",
        },
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
    }


def main() -> int:
    yedek = _yedek_dogrula()
    nokta = _devam_noktasi_yaz(yedek)
    notu = _notu_olustur(yedek, nokta)

    durum_yol = CALISMA / "DURUM.json"
    if durum_yol.is_file():
        durum = json.loads(durum_yol.read_text(encoding="utf-8"))
        notu["kullanilan_surumler"]["calisma_id"] = durum.get("calisma_id")
        durum["guncelleme"] = notu["zaman"]
        durum["devir1_devam_karari"] = (
            "D2 sonrasında D1 devam; D1 korunur; D2 ayrı"
        )
        durum["devir1_devam_notu"] = "DEVIR1_DEVAM_NOTU.json"
        durum["devir1_devam_noktasi"] = notu["devam_noktasi"]["yol"]
        durum["devir_2"] = "AYRI_HAZIRLIK_D1_DEVAM_SONRA"
        durum["k05"] = False
        durum["k06"] = False
        durum["mali_yazim"] = False
        durum["exe"] = False
        yaz_json(durum_yol, durum)

    yaz_json(CALISMA / "DEVIR1_DEVAM_NOTU.json", notu)
    yaz_json(
        CALISMA / "DEVIR1_DEVAM_NOTU_OZET.json",
        {
            "zaman": notu["zaman"],
            "karar": notu["karar"]["metin"],
            "yedek_ok": yedek.get("ok"),
            "son_surum": (yedek.get("son_basarili_surum") or {}).get("surum_id"),
            "devam_noktasi": notu["devam_noktasi"]["yol"],
            "d2_zorunlu_adet": len(notu["d2_acilisi_icin_zorunlu_d1"]),
            "d2_sonrasi_adet": len(notu["d2_sonrasi_surdurulecek_d1"]),
            "kritik_eksik": yedek.get("kritik_eksik"),
            "k05": False,
            "mali_yazim": False,
            "kanit": "DEVIR1_DEVAM_NOTU.json",
        },
    )

    # D2 tarafına referans (D1’i ezmeden)
    if D2.is_dir():
        ref = {
            "zaman": notu["zaman"],
            "d1_devam_karari": notu["karar"],
            "d1_notu": "kurulum/dnm_d1_20260831/DEVIR1_DEVAM_NOTU.json",
            "d1_koruma": notu["koruma"],
            "d2_acilisi_oncesi_zorunlu_d1": [
                x["madde"] for x in notu["d2_acilisi_icin_zorunlu_d1"]
            ],
            "d1_db_uzerine_yazma_yok": True,
            "k05": False,
            "mali_yazim": False,
        }
        (D2 / "D1_DEVAM_REFERANS.json").write_text(
            json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    md = CALISMA / "DEVIR1_DEVAM_NOTU.md"
    md.write_text(
        "\n".join(
            [
                "# Devir 1 devam notu",
                "",
                f"**Karar:** {notu['karar']['metin']} ({notu['karar']['karar_tarihi']})",
                "",
                f"Yedek doğrulama: `{'OK' if yedek.get('ok') else 'EKSIK'}` — "
                f"sürüm `{(yedek.get('son_basarili_surum') or {}).get('surum_id')}`",
                f"Devam noktası: `{notu['devam_noktasi']['yol']}`",
                "",
                "## Koruma",
                "- D1 kaynak/eşleme/kanıt/DB korunur",
                "- D1 temizlenmez, D2’ye dönüştürülmez, üzerine restore yok",
                "- D2 kök/DB ayrı (`kurulum/dnm_d2_20260901`)",
                "- Ortak kodda tamamlanan D1 kontrolleri korunur",
                "",
                "## D2 açılışı için zorunlu D1 (öncelik)",
                *[
                    f"{x['oncelik']}. {x['madde']} — {x['durum']}"
                    for x in notu["d2_acilisi_icin_zorunlu_d1"]
                ],
                "",
                "## D2 sonrası sürdürülecek D1",
                *[f"- {x['madde']}" for x in notu["d2_sonrasi_surdurulecek_d1"]],
                "",
                "## Sonradan bulunan kayıt",
                notu["sonradan_bulunan_kayit_kurali"]["aciklama"],
                "",
            ]
        ),
        encoding="utf-8",
    )

    ozet = json.loads((CALISMA / "DEVIR1_DEVAM_NOTU_OZET.json").read_text(encoding="utf-8"))
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0 if yedek.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
