# Servis ve Sistem Kontrol Merkezi — Plan

## Mevcut durum

| Alan | Tespit |
|------|--------|
| GUI | Tkinter + ttk (`app.py`, `*_ui.py`) |
| Veritabanı | SQLite (WAL); firma DB + `system.db` |
| ORM | SQLAlchemy 2.x (`Base`, `get_session`, `schema_hazirla` / `create` checkfirst) |
| Yedekleme | `CompanyMgmtService.yedek_al` + `BackupService.servis_oncesi_yedek_al` |
| Log / audit | `AuditLog` (system), branding log dosyası, silinen kayıt günlüğü |
| Yetki | `permissions` / roller; `oturum.has_permission`; YONETICI bypass |

## Ana modüller (tarama adayları)

Hızlı giriş, Satışlar, Satın alma, Stoklar, Finans (kasa/banka/KK/çek-senet), Cari, Gelir-gider, Genel muhasebe, Özet tablolar, Döviz, Silinen kayıtlar, Sistem yönetimi, EvoBulut aktarım, Branding/kaynaklar.

## Riskler

- Onarımın canlı veriyi bozması → Aşama 2–3 salt okunur; Aşama 4 Seviye 1; Aşama 5 Seviye 2 yalnızca önizleme + yedek + yetki + transaction
- GUI donması → uzun işler `ui_bg.arka_planda` / thread
- Paralel yedek yığını → mevcut `yedek_al` / ServisOncesi yeniden kullanılır
- Otomatik DROP/CREATE → yasak; şema yalnızca `checkfirst` ile ek tablo; index `IF NOT EXISTS`

## Aşama 2 (tamam)

- Paket: `database/servis_sistem/`
- Tablolar: `service_issues`, `service_repairs`
- Hızlı kontrol + DB salt okunur; UI menü SERVİS VE SİSTEM
- Onarım yok

## Aşama 3 (tamam)

- Derin salt okunur tarayıcılar: `database/servis_sistem/scanners/`
- UI: Seçili Modülü Tara / Ayrıntılı Kontrol; filtre; detay; Excel + HTML
- Bulgular `service_issues` upsert; `auto_fixable` Seviye 1 kodlarında

## Aşama 4 (tamam)

- **Yedek kapısı:** `BackupService.servis_oncesi_yedek_al` → `CinMuhasebe_ServisOncesi_YYYY-MM-DD_HHMMSS.db`; boyut > 0 doğrulama; başarısızsa onarım iptal
- **Önizleme:** sorun, etkilenen, risk, yedek planı, geri alma, doğrulama planı — onaydan önce mutasyon yok
- **Seviye 1 onarımlar** (`RepairService`):
  - Eksik klasörler: logs / yedek / temp / `assets/branding`
  - Güvenli varsayılan `AppSetting` (`kurulum_tamam`, `tek_firma_otomatik_giris`) — mevcut değere dokunulmaz
  - Beyaz liste `CREATE INDEX IF NOT EXISTS` (service_* + birkaç güvenli FK index)
  - Hesaplanmış özet cache yenileme: bu kod tabanında güvenli kalıp yok → atlandı
- **Transaction + rollback** DB dokunan Seviye 1 için; post-verify; `service_repairs` + issue `resolved`
- **UI:** Onarım Önizlemesi / Güvenli Hataları Düzelt / Seçili Hatayı Düzelt
- **Yetki:** onarım → YONETICI veya `servis_onarim`
- Test: yedek kapısı, klasör onarımı, rollback, issue status, preview L3 engeli

## Aşama 5 (tamam)

- **Seviye 2 kontrollü veri onarımları** (`RepairService.apply_level2` / `apply_repair`):
  - Zorunlu: önizleme, `confirm`, `CinMuhasebe_ServisOncesi_*` yedek kapısı, YONETICI/`servis_onarim`, transaction, post-verify
  - Risk metni: **“Seviye 2 — veri değişir, yedek alındı”**
- **Uygulanan L2:**
  1. `FATURA_TOPLAM_UYUSMAZ` / `FATURA_SATIR_MATRAH` — satış/alış başlık `tl_matrah`/`tl_kdv`/`tl_genel_toplam` satırlardan (`SatisFaturasiService.toplam` / `AlisFaturasiService.toplam`); tutar uydurma yok
  2. `CEK_TUTAR_UYUSMAZ` — `kalan_tutar = tl_tutari − tahsil_edilen_tutar`
  3. `FIS_BASLIK_SATIR` — başlık `toplam_borc`/`toplam_alacak` ← satır SUM; satırlar dengesizse **red** (hesap uydurma yok)
- **Ertelenen / manuel:**
  - Cari bakiye hareketlerden yeniden yazım — `CariService` içinde bakiye rewrite metodu yok → **manuel / mevcut servis yok**
  - Index yeniden oluşturma — zaten Seviye 1
  - `FIS_BORC_ALACAK` (satır dengesi bozuk) — Seviye 3; otomatik yok
- **Yasak (Seviye 3, engelli):** cari/stok birleştirme, kapalı dönem yazma, fiziksel silme, fatura no değiştirme, rastgele hesap ile muhasebe dengeleme, sessiz FIFO rewrite
- **UI:** Seçili Hatayı Düzelt + önizleme L2 için açık; L3 mesajla engelli
- **Test:** `test_servis_sistem.py` — L2 confirm, yedek kapısı, fatura recalc, muhasebe header, dengesiz satır engeli, L3 engeli, L2 rollback

## Aşama 6 (tamam — bu teslim)

- **Geniş test paketi** (`test_servis_sistem.py`): L2 çek `kalan_tutar`, kapalı dönem engeli, onarım yetkisi, `apply_repair` yönlendirme, L3 engeli, `scan_all_modules` salt okunur + `sure_ms`, `MAX_ORNEK` tavanı, çek tarama tespiti, persist L2 `auto_fixable`, orta veri seti performans taraması
- **Performans:**
  - Raporlara `sure_ms` (tarama süresi) eklendi (`CheckReport`)
  - Örnek tavanı: `MAX_ORNEK = 40` (sorun satırı); finans bakiye örneklemesi `MAX_FINANS_BAKIYE_ORNEK = 200`
  - Uzun taramalar UI’da `arka_planda` (donma yok)
- **UAT kontrol listesi** (manuel, yönetici hesabı):

  1. Menü **SERVİS VE SİSTEM** açılır; yetkisiz kullanıcıda uyarı
  2. **Hızlı Kontrol** → salt okunur; iş tabloları satır sayısı değişmez; özet / maddeler görünür
  3. **Ayrıntılı Kontrol** / seçili modül (cari, stok, satış, çek, muhasebe) → bulgular listelenir; Excel + HTML dışa aktarım
  4. Seviye 1 sorun (ör. eksik temp klasör) → **Onarım Önizlemesi** → onay → `CinMuhasebe_ServisOncesi_*` yedek oluşur → klasör oluşur → sorun `resolved`
  5. Seviye 2 fatura toplam uyuşmazlığı (test verisi) → önizlemede risk metni → onay + yedek → başlık satırlardan düzelir → yeniden tarama temiz / issue resolved
  6. Seviye 2 çek tutar → `kalan_tutar` düzelir
  7. Kapalı dönem içindeki fatura/çek → Seviye 2 **red** (manuel)
  8. `FIS_BORC_ALACAK` / L3 kod → otomatik onarım **engelli**; mesaj anlaşılır
  9. Yedek klasörü yazılamaz / yedek 0 byte simülasyonu → onarım iptal, veri aynı
  10. Onarım sonrası `service_repairs` kaydı ve (mümkünse) progress çubuğu tamamlanır

- **Hâlâ ertelenen:** cari bakiye rewrite (servis yok); Seviye 3 açılmadı; EXE rebuild bu aşamada yok

## Plan durumu

**Aşama 1–6 tamam.** Servis Merkezi planı bu dokümana göre kapanmıştır (yeni özellik / L3 açılımı ayrı onay ister).
