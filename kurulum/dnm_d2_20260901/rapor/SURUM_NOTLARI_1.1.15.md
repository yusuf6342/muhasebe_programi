# Cin Muhasebe 1.1.15 — sürüm notları

**Tarih:** 2026-11-18  
**Dal:** `feature/yerel-ag-postgresql`  
**Kapsam:** Kredi kartı taksit hareketleri + ekstre/devir/ödeme raporu düzeltmeleri

## Özet

- Taksitler evrak işlendiğinde baştan kart hareketlerine kaydedilir; EVO/devir/gider/nakit avansta mükerrer borç yok (`KK TAKSİT` nötr / NAT ana belgeye bağlanır).
- Ekstre dönemleri kartın kendi kesim gününe göre (ör. 16 → önceki ay 17 … ayın 16’sı).
- Önceki dönem borcu, son ödeme günü ve sonrasındaki ödemeler düşülerek **Önceki dönemden devir** olarak yeni ekstreyе geçer; aynı ödeme iki kez düşülmez.
- Raporda yansıma/kaynak/vade alanları, yürüyen bakiye, ödeme/mahsup detayı, iki tarih arası rapor; Etki sütunu kaldırıldı.
- “İşlenmemiş taksit” / “Yalnız planlı” aktarım aşaması kaldırıldı.
- Kullanılan limit, kart ekranı ile aynı kaynaktan (ledger + plan-only) hesaplanır.

## Kurulum / güncelleme

- Paket: `CinMuhasebe_DNM_D2_GUNCELLE_*` + `kurulum\00_D2_GUNCELLE.ps1`
- USB: `CinMuhasebe\GUNCELLE.cmd` → Güncelle
- `baglanti_ayari.json` ve ortak PG korunur; yeni firma/DB oluşturulmaz.

## Test

- `tests/test_kk_ekstre_devir_odeme.py`, `test_kk_taksit_karta_isleme.py`, `test_kredi_karti_ekstre.py`, `test_kk_ekstre_rapor_detached.py`
