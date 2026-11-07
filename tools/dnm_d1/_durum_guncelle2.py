import json
from datetime import datetime
from pathlib import Path

kok = Path("kurulum/dnm_d1_20260831")
ek = json.loads((kok / "kaynak/D1_20260831_KAYNAK_CARI_EKSTRE_KAPANIS.json").read_text(encoding="utf-8"))
ok = sum(1 for x in ek["cariler"] if x.get("son_ozet") is not None)
nz = sum(1 for x in ek["cariler"] if x.get("kapanis_bakiye") not in (None, "0", "0.0"))
bel = json.loads((kok / "kaynak/D1_20260831_KAYNAK_BELGE.json").read_text(encoding="utf-8"))
gg = json.loads((kok / "kaynak/D1_20260831_KAYNAK_GIDER_GELIR.json").read_text(encoding="utf-8"))

man = json.loads((kok / "CALISMA_MANIFESTI.json").read_text(encoding="utf-8"))
man["kaynak"]["firma_no_dogrulandi"] = True
man["kaynak"]["firma_no_bulunan"] = "42178"
man["kaynak"]["gercek_bakiyeler"] = (
    "KISMI_KAPANIS — cari ekstre ozet 1066; kasa/banka hareket neti; "
    "stok LOT/acik kalem/valor eksik"
)
man["kaynak"]["goruntu_zamani"] = datetime.now().astimezone().isoformat(timespec="seconds")
man["uygulama_kapilari"]["K05_kaynak_kapanis_tamam"] = False
man["uygulama_kapilari"]["K06_hedef_izolasyonu"] = False
man["uygulama_kapilari"]["mali_yazim_izinli"] = False
man["durum"] = "FIRMA_ID_OK; CARI_EKSTRE_1066; BELGE_10793; K05/K06 KAPALI; YAZIM YOK"
(kok / "CALISMA_MANIFESTI.json").write_text(
    json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

plan = json.loads((kok / "KONTROL_PLANI_DURUM.json").read_text(encoding="utf-8"))
guncelle = {
    "K01": "Kısmi",
    "K03": "Kısmi",
    "K04": "Kısmi",
    "K08": "Kısmi",
    "K18": "Kısmi",
    "K19": "Kısmi",
    "K20": "Kısmi",
    "K22": "Kısmi",
    "K24": "Kısmi",
    "K25": "Kısmi",
    "K26": "Kısmi",
    "K27": "Kısmi",
    "K35": "Kısmi",
}
kanit = {
    "K01": "D1_20260831_KAYNAK_FIRMA_DOGRULAMA.json a_firma_id=42178",
    "K08": "D1_20260831_KAYNAK_CARI_EKSTRE_KAPANIS.json",
    "K18": "D1_20260831_KAYNAK_KASA_KAPANIS.json",
    "K19": "D1_20260831_KAYNAK_BANKA_KAPANIS.json",
    "K22": "D1_20260831_KAYNAK_POS_KART_KREDI.json",
    "K26": "D1_20260831_KAYNAK_GIDER_GELIR.json",
    "K35": "D1_20260831_KAYNAK_BELGE.json",
}
for k in plan["kontroller"]:
    kid = k["kontrol_id"]
    if kid in guncelle:
        k["sonuc"] = guncelle[kid]
    if kid in kanit:
        k["kaynak_kanit"] = kanit[kid]
plan["ozet"] = {
    "toplam": 43,
    "bekliyor": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Bekliyor"),
    "kismi": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Kısmi"),
    "tamam": sum(1 for x in plan["kontroller"] if x["sonuc"] == "Tamam"),
}
(kok / "KONTROL_PLANI_DURUM.json").write_text(
    json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

dur = {
    "calisma_id": man["calisma_id"],
    "guncelleme": datetime.now().astimezone().isoformat(timespec="seconds"),
    "ozet": (
        f"Firma 42178 doğrulandı. Cari ekstre kapanış özeti {ok}/1066 (sıfır-dışı {nz}). "
        f"Belge başlık {bel['toplam']}, gider/gelir {gg['adet']}. "
        "Kasa 2 / banka 30 hareket neti. POS/KK/kredi sınıflandırıldı. "
        "K05/K06 kapalı — mali yazım yok."
    ),
    "kanitlar": {
        "firma": "kaynak/D1_20260831_KAYNAK_FIRMA_DOGRULAMA.json",
        "cari_ekstre": "kaynak/D1_20260831_KAYNAK_CARI_EKSTRE_KAPANIS.json",
        "kasa": "kaynak/D1_20260831_KAYNAK_KASA_KAPANIS.json",
        "banka": "kaynak/D1_20260831_KAYNAK_BANKA_KAPANIS.json",
        "pos_kart": "kaynak/D1_20260831_KAYNAK_POS_KART_KREDI.json",
        "gider_gelir": "kaynak/D1_20260831_KAYNAK_GIDER_GELIR.json",
        "belge": "kaynak/D1_20260831_KAYNAK_BELGE.json",
        "excel": "mutabakat/D1_20260831_MUTABAKAT_DOLU.xlsx",
        "kullanici": "KULLANICI_ADIMLARI.md",
    },
    "eksik_k05": [
        "Açık kalem / vade / valör satırları",
        "Stok depo/LOT miktar ve maliyet kapanışı",
        "Kasa/banka gerçek açılış/devir belgeleri",
        "POS valör/bloke/banka geçiş ayrımı",
        "Belge satır detayları",
    ],
    "engeller": [
        "K06: ANA makinede superuser ile 10_pg_dnm_d1_bos_hedef.ps1",
        "K05: yukarıdaki eksikler",
        "Firma unvanı web teyidi",
    ],
    "kullanici_adimi_gerekli": [
        "web.evobulut.com oturumunda DNM adı + 42178 ekran teyidi",
        "DESKTOP-CGSE5GK üzerinde 10_pg_dnm_d1_bos_hedef.ps1",
    ],
}
(kok / "DURUM.json").write_text(json.dumps(dur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("OK cari", ok, "nz", nz, "belge", bel["toplam"], "gg", gg["adet"])
print("kontrol", plan["ozet"])
