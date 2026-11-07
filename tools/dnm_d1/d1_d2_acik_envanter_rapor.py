"""D1/D2 açık envanteri — eksik belge, yapılacak, aktarım engeli.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.d1_d2_acik_envanter_rapor
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tools.dnm_d1._ortak import CALISMA, yaz_json

D2 = CALISMA.parent / "dnm_d2_20260901"


def _o(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    fifo49 = _o(CALISMA / "STOK_49_FIFO_HAREKET_KATMAN_OZET.json")
    fifo_dag = _o(CALISMA / "STOK_49_FIFO_DAGILIM_KANIT_OZET.json")
    cari = _o(CALISMA / "CARI_ACIK_KALEM_DILIM_DUZELT_OZET.json")
    cari22_talimat = _o(CALISMA / "CARI22_GERCEK_DETAY_RAPOR_TALIMAT_OZET.json")
    yedek = _o(D2 / "YEDEK_IZOLASYON_DENEME_OZET.json")
    st3252 = _o(CALISMA / "STOK_3252_HESAPLANABILIR_OZET.json")
    kasa = _o(CALISMA / "IKI_KASA_KAPANIS_OZET.json")
    t19 = _o(D2 / "T19_T22_IZOLASYON_OZET.json")
    pos_fin = _o(CALISMA / "POS_CIFT_SAYIM_FINANS_KAPSAM_OZET.json")

    aciklar = [
        {
            "madde": "Stok kimlik 3252",
            "durum": "TAMAM",
            "eksik_kaynak_belgesi": "—",
            "yapilacak": "Yeniden toplama yok; koru",
            "aktarimi_engeller": False,
            "kanit": st3252.get("kanit_3252"),
        },
        {
            "madde": "Kasa nakit+YC kapanış",
            "durum": "TAMAM",
            "eksik_kaynak_belgesi": "—",
            "yapilacak": "Yeniden toplama yok; koru",
            "aktarimi_engeller": False,
            "kanit": kasa.get("kanit_nakit"),
        },
        {
            "madde": "49 pasif FIFO katman (hareket)",
            "durum": "KISMI",
            "eksik_kaynak_belgesi": (
                f"38 katman: 20 OK / 15 fark / 3 doğrulanamadı; 11 tüketildi/sıfır; "
                f"LOT maliyet BEKLIYOR; maliyet uydurma yok"
            ),
            "yapilacak": (
                "Farklarda gir_fiyat=satır tutarı hipotezi + belge satır birim; "
                "LOT Seri_Lot_List maliyet — kart/ortalama doldurma yok"
            ),
            "aktarimi_engeller": True,
            "neden_engel": "D2 açılış FIFO katman/maliyet kanıtsız kabul edilmez",
            "kanit": fifo_dag.get("kanit") or fifo49.get("kanit"),
            "ilerleme": fifo49.get("durum_say"),
            "dagilim": fifo_dag,
        },
        {
            "madde": "LOT katman maliyeti (genel)",
            "durum": "AÇIK",
            "eksik_kaynak_belgesi": "Seri_Lot_List katman birim maliyet alanı yok (865/906)",
            "yapilacak": "Alış belge satır + LOT bağını izole FIFO ile doğrula; kart fifo doldurma yok",
            "aktarimi_engeller": True,
            "neden_engel": "D2 13/27 LOT maliyet",
        },
        {
            "madde": "Cari22 / açık kalem Detay",
            "durum": "AÇIK",
            "eksik_kaynak_belgesi": (
                "Gerekli: Cari Kart → Hesap Ekstresi (satır Detay). "
                "Yasak: PDF Müşteri Hesap Toplamı (Devirli); boş finans_jq tekrarı"
            ),
            "yapilacak": (
                f"{cari22_talimat.get('gerekli_rapor') or 'Cari Hesap Ekstresi'}; "
                f"bitiş 31.08.2026; 21 kanıtsız cari — "
                f"{cari22_talimat.get('kanit') or 'CARI22_GERCEK_DETAY_RAPOR_TALIMAT'}"
            ),
            "aktarimi_engeller": True,
            "neden_engel": "D2 08–11 açık kalem/FIFO valör açılışı",
            "kanit": cari22_talimat.get("kanit") or cari.get("kanit"),
            "cari22_kanitsiz": cari.get("cari22_kanitsiz"),
            "talimat": cari22_talimat,
        },
        {
            "madde": "Sıfır maliyet 14",
            "durum": "SINIFLI",
            "eksik_kaynak_belgesi": "12 kayıtta dönem içi alış BELGE_SATIR yok",
            "yapilacak": "Bilinmeyen olarak bırak; kart/ortalama doldurma yok",
            "aktarimi_engeller": True,
            "neden_engel": "Bedelsiz kanıtı olmayan sıfır maliyet açılışta provisional",
        },
        {
            "madde": "D2_BITIS_DAHIL",
            "durum": "SABITLENDI",
            "eksik_kaynak_belgesi": "—",
            "yapilacak": "Kapsam filtreleri/raporlar bu aralığı kullanır; ön toplama tamamlanır",
            "aktarimi_engeller": False,
            "not": "01.09.2026–07.11.2026 dahil; HARIC 2026-11-08T00:00+03. Tarih ≠ aktarım kabulü",
            "kanit": "tools/dnm_d2/donem_sabitleri.py + kurulum/dnm_d2_20260901/MANIFEST.json",
        },
        {
            "madde": "K05 kaynak kontrolü",
            "durum": "KAPALI",
            "eksik_kaynak_belgesi": "Kaynak tamlığı + kritik fark çözümü",
            "yapilacak": "Açıklar kapanınca K05 kanıt paketi",
            "aktarimi_engeller": True,
        },
        {
            "madde": "K06 / izole yedek-geri yükleme",
            "durum": "BETIK_HAZIR_DENEME_BEKLIYOR",
            "eksik_kaynak_belgesi": (
                "cin_app CREATEDB/SUPERUSER verilmez; "
                "11_pg_dnm_d2_bos_hedef.ps1 ana makinede superuser ile bekliyor"
            ),
            "yapilacak": (
                "Yetkili yönetim: kurulum/sunucu/11_pg_dnm_d2_bos_hedef.ps1 "
                "(parola env/Read-Host; sohbet yok). Ana makine + gerçek D2 son aşama"
            ),
            "aktarimi_engeller": True,
            "neden_engel": "D2 06 gerçek boş hedef + izole restore",
            "kanit": "kurulum/dnm_d2_20260901/yedek/YEDEK_IZOLASYON_DURUM.json",
            "deneme": yedek,
        },
        {
            "madde": "POS bekleyen ↔ banka çift sayım",
            "durum": "KURAL_KORUNDU_LISTE_TAMAM_DEGIL",
            "eksik_kaynak_belgesi": (
                f"valor_bekleyen={pos_fin.get('valor_bekleyen_adet')}; "
                "Akbank kısmi; diğer hesaplar + tam liste açık"
            ),
            "yapilacak": "Açılışta bekleyen POS’u mevduattan ayrı tut; listeyi tamamla",
            "aktarimi_engeller": False,
            "not": (
                "Çift sayım kuralı korunur ≠ bekleyen POS listesi tamam. "
                "Finans kapsam kanıtı ayrı (tam değil)."
            ),
            "kanit": pos_fin.get("kanit"),
            "finans_kapsam_tam": pos_fin.get("finans_kapsam_tam"),
        },
    ]

    out = {
        "format": "d1-d2-acik-envanter-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tamamlanan_korunan": {
            "stok_kimlik_3252": True,
            "kasa_kontrolleri": True,
            "yeniden_toplanmadi": True,
        },
        "d2_test": {
            "T01_T18": "18/18 OK",
            "T19_T22_izolasyon": t19.get("izolasyon_gecen", "BEKLIYOR"),
            "T19_T22_canli_kaynak": t19.get("canli_kaynak_dogrulama", "AYRI_BEKLIYOR"),
        },
        "aciklar": aciklar,
        "ozet": {
            "aktarim_engeli_adet": sum(1 for a in aciklar if a.get("aktarimi_engeller")),
            "engellemez_adet": sum(1 for a in aciklar if not a.get("aktarimi_engeller")),
        },
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe": False,
    }
    yol = CALISMA / "kaynak" / "D1_20260831_KAYNAK_DOGRULAMA_D1_D2_ACIK_ENVANTER.json"
    yaz_json(yol, out)
    ozet = {
        "zaman": out["zaman"],
        "acik_adet": len(aciklar),
        "aktarim_engeli": out["ozet"]["aktarim_engeli_adet"],
        "fifo49_deger_ok": fifo49.get("deger_ok"),
        "fifo49_miktar_ok": fifo49.get("miktar_ok"),
        "fifo49_dagilim": {
            "20_ok": fifo_dag.get("deger_ok_20"),
            "15_fark": fifo_dag.get("deger_fark_15"),
            "3_dogrulanamadi": fifo_dag.get("dogrulanamadi_3"),
            "11_sifir": fifo_dag.get("tuketildi_veya_sifir_11"),
        },
        "cari22_kanitsiz": cari.get("cari22_kanitsiz"),
        "yedek_basarili": yedek.get("basarili"),
        "yedek_durum": yedek.get("durum"),
        "d2_test_T01_T18": "18/18",
        "d2_test_T19_T22_izolasyon": t19.get("izolasyon_gecen"),
        "d2_test_T19_T22_canli": t19.get("canli_kaynak_dogrulama"),
        "pos_liste_tamam": pos_fin.get("bekleyen_liste_tamam"),
        "finans_kapsam_tam": pos_fin.get("finans_kapsam_tam"),
        "k05": False,
        "mali_yazim": False,
        "kanit": str(yol.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(CALISMA / "D1_D2_ACIK_ENVANTER_OZET.json", ozet)
    # D2 durum raporuna bağla
    d2r = D2 / "D2_HAZIRLIK_DURUM_RAPORU.json"
    if d2r.is_file():
        rep = json.loads(d2r.read_text(encoding="utf-8"))
        rep["zaman"] = out["zaman"]
        rep["acik_envanter"] = ozet
        rep["d2_test_T01_T18"] = "18/18 OK"
        rep["d2_test_T19_T22"] = {
            "izolasyon": t19.get("izolasyon_gecen"),
            "canli_kaynak_dogrulama": t19.get("canli_kaynak_dogrulama"),
            "kanit": t19.get("kanit"),
        }
        rep["yedek_izolasyon"] = yedek
        rep["bitis_kullanicidan_istenecek"] = False
        if "talimat" in rep and isinstance(rep["talimat"], dict):
            rep["talimat"]["bitis_kullanicidan"] = False
            rep["talimat"]["bitis_sabitlendi"] = True
            rep["talimat"]["d2_bitis"] = "2026-11-07"
        # kullanıcıdan somut engeller — bitiş tarihi çıkarıldı
        engeller = [
            "Ana makinede 11_pg_dnm_d2_bos_hedef.ps1 (superuser; CREATEDB cin_app’e yok)",
            "Cari22: Cari Kart → Hesap Ekstresi Detay (21 cari); PDF Toplamı/Devirli kullanma",
            "İş bitimi sonrası kapsam içi yeni/değişmiş kayıtları kimlik+sürüm ile tamamla (ön toplama paketi)",
            "K05/K06 sonrası mali yazım — tarih sabiti kabul değil",
            "Web oturumu düşerse: web.evobulut.com DNM (42178); eşzamanlı iki login yok",
        ]
        rep["kullanicidan_somut"] = engeller
        d2r.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
