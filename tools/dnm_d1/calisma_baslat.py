"""DNM D1 çalışma kaydı ve kontrol planı iskeletini üretir.

Mali yazım yapmaz. Kaynak bakiyesi yokken sayısal hücreleri 0 yazmaz.
Kullanım:
  .venv\\Scripts\\python.exe -m tools.dnm_d1.calisma_baslat
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.dnm_d1.donem_sabitleri import (
    CALISMA_KOK,
    DONEM_SONU,
    HARIC_UST_SINIR_UTC,
    HARIC_UST_SINIR_YEREL,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    KORUNAN_HEDEFLER,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    TALIMAT_DOSYA,
    TALIMAT_SHA256,
)

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK


def _sha256(yol: Path) -> str:
    h = hashlib.sha256()
    with yol.open("rb") as f:
        for parca in iter(lambda: f.read(1024 * 1024), b""):
            h.update(parca)
    return h.hexdigest().upper()


def _kontrol_plani() -> list[dict]:
    """Excel Kontrol Planı K01–K43 iskeleti."""
    basliklar = [
        ("K01", "Firma / dönem", "Firma ve dönem manifesti"),
        ("K02", "Tarih sınırı", "Dönem içi / dışı kimlik listeleri"),
        ("K03", "Kaynak sürümü", "Ortak görüntü ve dosya manifesti"),
        ("K04", "Tamlık", "Kart / belge / satır kimlik envanteri"),
        ("K05", "Kaynak öncesi kapı", "Bütün kaynak kapanış raporları"),
        ("K06", "Hedef izolasyonu", "Yeni veritabanı ve profil kaydı"),
        ("K07", "Yedek / geri dönüş", "Yedek ve izole geri yükleme sonucu"),
        ("K08", "Cari", "Cari açılış ve kapanış listesi"),
        ("K09", "Cari grupları", "Özgün grup ve rol eşlemesi"),
        ("K10", "Açık kalem", "Belge/satır bazlı açık kalem listesi"),
        ("K11", "Vade / valör", "Cari valör ve yaşlandırma raporu"),
        ("K12", "Cari virman / devir", "Devir ve virman tam JSON + ekstre"),
        ("K13", "Stok miktarı", "Stok depo dönem sonu miktarları"),
        ("K14", "Stok kapsamı", "Pasif / sıfır / negatif stok listesi"),
        ("K15", "Maliyet", "Aynı yöntemli tarihli envanter"),
        ("K16", "LOT / seri", "LOT miktar ve maliyet ayrıntısı"),
        ("K17", "Negatif LOT", "Negatif ve sıfır miktar maliyet raporu"),
        ("K18", "Kasa", "Her kasa için tarihli ekstre"),
        ("K19", "Banka", "Her alt hesap için tarihli ekstre"),
        ("K20", "Banka eşlemesi", "Çatı / hesap eşleme listesi"),
        ("K21", "Transferler", "Kasa/banka olay ve karşı bacak listesi"),
        ("K22", "POS", "POS işlem tarihli kapanış raporu"),
        ("K23", "POS valör", "Bloke / valör / banka geçiş listesi"),
        ("K24", "Firma kredi kartı", "Kart borcu ve dönem hareketleri"),
        ("K25", "Kredi / KMH", "Kredi kapanışı ve taksit planı"),
        ("K26", "Gider", "Gider kartı/kategori dönem dökümü"),
        ("K27", "Gelir", "Gelir kartı/kategori dönem dökümü"),
        ("K28", "Kaynak iç farkı", "Kaynak alanı fark raporu"),
        ("K29", "Çek / senet", "Dönem sonu açık portföy raporu"),
        ("K30", "Personel / avans", "Personel ve avans hesap listesi"),
        ("K31", "Yatırım / fon", "Tarihli miktar ve kayıtlı değer"),
        ("K32", "Sabit kıymet", "Dönem sonu kıymet listesi"),
        ("K33", "Teminat", "Teminat açık durum listesi"),
        ("K34", "Genel muhasebe", "Hesap bazlı mizan ve fiş kontrolü"),
        ("K35", "Fatura / fiş / iade", "Tür ve durum bazlı belge dökümü"),
        ("K36", "Sipariş / irsaliye", "Açık sipariş/teslim ve dönüşüm listesi"),
        ("K37", "Eksik / fazla kimlik", "Kaynak-hedef birleşim kümesi raporu"),
        ("K38", "Döviz / birim / yöntem", "Karşılaştırma ayar manifesti"),
        ("K39", "Tekrar / kesinti", "İdempotans ve yeniden başlatma testi"),
        ("K40", "Dönem sınırı testleri", "Tarih ve gelecekteki olay test sonuçları"),
        ("K41", "Açıklanmamış farklar", "Kimlik bazlı fark ve hata dökümü"),
        ("K42", "Kapanış kabulü", "Son kapanış manifesti ve raporları"),
        ("K43", "EXE / dağıtım", "Ertelenen son paket / ağ kabul listesi"),
    ]
    satirlar = []
    for kid, modul, rapor in basliklar:
        satirlar.append(
            {
                "kontrol_id": kid,
                "modul": modul,
                "kaynak_raporu": rapor,
                "sonuc": "Bekliyor",
                "kaynak_kanit": None,
                "hedef_kanit": None,
                "aciklama": (
                    "EXE/paket ertelendi (kullanıcı 06.11.2026)"
                    if kid == "K43"
                    else "Kaynak bakiyeleri henüz alınmadı; boş değer sıfır sayılmaz."
                ),
            }
        )
    return satirlar


def main() -> int:
    CALISMA.mkdir(parents=True, exist_ok=True)
    for alt in ("kaynak", "hedef", "mutabakat", "yedek", "envanter"):
        (CALISMA / alt).mkdir(exist_ok=True)

    talimat = KOK / TALIMAT_DOSYA
    if not talimat.is_file():
        print("TALIMAT_YOK", talimat, flush=True)
        return 2
    sha = _sha256(talimat)
    if sha != TALIMAT_SHA256:
        print("TALIMAT_SHA_UYUMSUZ", sha, "beklenen", TALIMAT_SHA256, flush=True)
        return 3

    simdi = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    calisma_id = f"D1-20260831-{datetime.now():%Y%m%d_%H%M%S}"

    manifest = {
        "format": "cin-dnm-d1-calisma-v1",
        "calisma_id": calisma_id,
        "olusturma_zamani": simdi,
        "talimat": {
            "dosya": TALIMAT_DOSYA.replace("\\", "/"),
            "sha256": sha,
            "surum": "4 · 06.11.2026",
            "kullanim": "TALİMAT VE BOŞ DENETİM ŞABLONU",
        },
        "kaynak": {
            "firma_adi": KAYNAK_FIRMA_ADI,
            "firma_no_beklenen": KAYNAK_FIRMA_NO,
            "firma_no_dogrulandi": False,
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "haric_ust_sinir_europe_istanbul": HARIC_UST_SINIR_YEREL.isoformat(),
            "haric_ust_sinir_utc": HARIC_UST_SINIR_UTC.isoformat(),
            "ilk_gercek_kaynak_tarihi": None,
            "goruntu_zamani": None,
            "goruntu_calisma_id": None,
            "kapanis_dosyasi": None,
            "kapanis_sha256": None,
            "gercek_bakiyeler": "HENÜZ ALINMADI",
        },
        "hedef": {
            "onerilen_sistem_db": ONERILEN_SISTEM_DB,
            "onerilen_firma_db": ONERILEN_FIRMA_DB,
            "gercek_sistem_db": None,
            "gercek_firma_db": None,
            "uygulama_durumu": "HENÜZ OLUŞTURULMADI",
            "korunan_kurulumlar": sorted(KORUNAN_HEDEFLER),
            "not": (
                "Mevcut RAY001 / DENEME / kabul / ağ geçişi hedef değildir. "
                "evo_devir.aktarim yalnız bakiye/devir motorudur; D1 tam geçmiş yazımı için kullanılamaz."
            ),
        },
        "uygulama_kapilari": {
            "K05_kaynak_kapanis_tamam": False,
            "K06_hedef_izolasyonu": False,
            "mali_yazim_izinli": False,
            "exe_paket_izinli": False,
        },
        "uygulama_sirasi_ozet": [
            "01 Kaynak kapanışı (EvoBulut 31.08.2026) — yazımdan önce",
            "02 Ayrı hedef sistem/firma DB + profil",
            "03 Korunan kurulumlara dokunma",
            "04 Tam birinci dönem geçmişi (yalnız kapanış bakiyesi değil)",
            "05 Mutabakat şablonlarını gerçek kimliklerle doldur",
            "06 EXE/paket en sonda",
        ],
        "durum": "ISKELET_HAZIR — kaynak bakiyesi ve izole hedef bekleniyor",
    }

    plan = {
        "format": "cin-dnm-d1-kontrol-plani-v1",
        "calisma_id": calisma_id,
        "donem_sonu": DONEM_SONU.isoformat(),
        "kontroller": _kontrol_plani(),
        "ozet": {
            "toplam": 43,
            "bekliyor": 43,
            "tamam": 0,
            "engellenen": 0,
        },
    }

    durum = {
        "calisma_id": calisma_id,
        "guncelleme": simdi,
        "ozet": (
            "Talimat sabitlendi. Gerçek 31.08.2026 kaynak bakiyeleri yok; "
            "veritabanı henüz oluşturulmadı; mali yazım kapalı; EXE ertelendi."
        ),
        "sonraki_adimlar": [
            "EvoBulut DNM 42178 oturumunda firma kimliğini doğrula",
            "Salt okuma ile D1_20260831_KAYNAK_* kapanış raporlarını üret",
            "kurulum/sunucu/10_pg_dnm_d1_bos_hedef.ps1 ile boş izole DB oluştur",
            "Kaynak kapısı (K05) kapanmadan hedefe mali yazma",
        ],
        "engeller": [
            "GERÇEK KAYNAK BAKİYELERİ HENÜZ ALINMADI",
            "VERİTABANI HENÜZ OLUŞTURULMADI",
        ],
    }

    (CALISMA / "CALISMA_MANIFESTI.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CALISMA / "KONTROL_PLANI_DURUM.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (CALISMA / "DURUM.json").write_text(
        json.dumps(durum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("CALISMA_ID", calisma_id, flush=True)
    print("MANIFEST", CALISMA / "CALISMA_MANIFESTI.json", flush=True)
    print("KONTROL", CALISMA / "KONTROL_PLANI_DURUM.json", flush=True)
    print("DURUM", durum["ozet"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
