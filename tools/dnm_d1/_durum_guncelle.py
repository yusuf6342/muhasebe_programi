"""Kısmi kaynak çekimi sonrası çalışma durumunu günceller."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

kok = Path("kurulum/dnm_d1_20260831")
man = json.loads((kok / "CALISMA_MANIFESTI.json").read_text(encoding="utf-8"))
dur = json.loads((kok / "DURUM.json").read_text(encoding="utf-8"))
plan = json.loads((kok / "KONTROL_PLANI_DURUM.json").read_text(encoding="utf-8"))
km = json.loads((kok / "kaynak/D1_20260831_KAYNAK_MANIFEST.json").read_text(encoding="utf-8"))
simdi = datetime.now().astimezone().isoformat(timespec="seconds")

man["kaynak"]["goruntu_zamani"] = km.get("alim_zamani")
man["kaynak"]["goruntu_calisma_id"] = man["calisma_id"]
man["kaynak"]["kapanis_dosyasi"] = "kaynak/D1_20260831_KAYNAK_MANIFEST.json"
man["kaynak"]["gercek_bakiyeler"] = "KISMI_ENVANTER — kapanış bakiyeleri henüz kurulmadı"
man["kaynak"]["envanter_ozet"] = km.get("ozet")
man["uygulama_kapilari"]["K05_kaynak_kapanis_tamam"] = False
man["durum"] = "KISMI_KAYNAK_ENVANTER — K05 kapalı; mali yazım yok; EXE yok"

for k in plan["kontroller"]:
    if k["kontrol_id"] == "K04":
        k["sonuc"] = "Kısmi"
        k["kaynak_kanit"] = "D1_20260831_KAYNAK_CARI/STOK/KASA/BANKA/MANIFEST"
        k["aciklama"] = f"Kart/hareket envanteri alındı: {km.get('ozet')}"
    if k["kontrol_id"] == "K01":
        k["sonuc"] = "Bekliyor"
        k["aciklama"] = (
            "API oturum açıldı; firma no 42178 yanıtta otomatik doğrulanamadı — web ile doğrula"
        )
    if k["kontrol_id"] == "K03":
        k["sonuc"] = "Kısmi"
        k["kaynak_kanit"] = "D1_20260831_KAYNAK_MANIFEST.json"
        k["aciklama"] = "Ortak alım zamanı kaydedildi; tüm modüller henüz aynı pakette değil"

plan["ozet"] = {
    "toplam": 43,
    "bekliyor": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Bekliyor"),
    "kismi": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Kısmi"),
    "tamam": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Tamam"),
}

dur.update(
    {
        "guncelleme": simdi,
        "ozet": (
            "Talimat uygulandı (iskelet + kısmi kaynak envanteri). "
            f"Cari {km['ozet']['cari_kart']}, stok {km['ozet']['stok_kart']}, "
            f"kasa hareket {km['ozet']['kasa_hareket']}, banka hareket {km['ozet']['banka_hareket']}. "
            "Tam 31.08 kapanış bakiyeleri / açık kalem / LOT / belge eksik. Mali yazım ve EXE kapalı."
        ),
        "sonraki_adimlar": [
            "Web oturumunda DNM firma 42178 doğrula",
            "Eksik D1_20260831_KAYNAK_* modüllerini tamamla (açık kalem, LOT, POS, belge, cari ekstre kapanış)",
            "10_pg_dnm_d1_bos_hedef.ps1 ile boş izole DB oluştur",
            "K05+K06 olmadan mali yazma; evo_devir bakiye motorunu D1 yazımında kullanma",
        ],
        "engeller": [
            "TAM 31.08 KAYNAK KAPANIŞ BAKİYELERİ YOK (KISMI_ENVANTER)",
            "FIRMA NO 42178 OTOMATİK DOĞRULANMADI",
            "VERİTABANI HENÜZ OLUŞTURULMADI",
            "K05/K06 KAPALI → mali yazım engelli",
        ],
    }
)

(kok / "CALISMA_MANIFESTI.json").write_text(
    json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(kok / "KONTROL_PLANI_DURUM.json").write_text(
    json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(kok / "DURUM.json").write_text(
    json.dumps(dur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("GUNCELLENDI", flush=True)
