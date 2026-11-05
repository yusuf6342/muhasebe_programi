# Cin Muhasebe — Ana Makine Bağlantısı Devam Raporu

Tarih/saat: **2026-11-05 14:11** (DESKTOP-FL08BVD)  
Dayanak: `GECIS_KABUL_TESTLERI_2026-11-05.md` + JSON  
Önceki commit: `9f2d20e` @ `feature/yerel-ag-postgresql`  
DNM / 31.08.2026: **dokunulmadı**

## Özet

| Soru | Cevap |
|------|--------|
| Ana makine kopyası tamamlandı mı? | **Hayır** — bu oturum **terminal** (FL08BVD); `cin_app` CREATEDB=false; postgres superuser env yok |
| Ayrı hedefe restore tamamlandı mı? | **Hayır** (CREATEDB engeli) |
| Canlı geçişe hazır mı? | **Hayır** |
| Canlı geçiş uygulandı mı? | **Hayır** |
| Günlük bağlantı değiştirildi mi? | **Hayır** |

## 1) Ortam doğrulama (14:10)

| Kontrol | Sonuç |
|---------|--------|
| Bu makine | DESKTOP-FL08BVD (terminal, 192.168.1.133) |
| PG sunucu | 192.168.1.114 → DESKTOP-CGSE5GK, ping OK |
| cin_* DB | yalnız `cin_sistem_deneme`, `cin_firma_deneme` |
| RAY001 | `pg:cin_firma_deneme`, aktif=true; diğerleri kilitli |
| cin_app CREATEDB | **false** (önceki engel doğrulandı) |
| MUHASEBE_PG_SUPER_PASSWORD | **yok** |
| kabul/restore DB | **yok** |
| Scriptler | `03` / `04` / yeni `05` mevcut; korunan ad denetimi eklendi |
| Dump SHA | sistem/firma beklenenle **eşleşiyor** |

Kanıt: `kurulum/_kabul_devam_durum.json`

## 2) Terminalde tamamlanan hazırlık

1. Dump paketi (taşınabilir):  
   `%LOCALAPPDATA%\CinMuhasebeAktarim\AnaMakine_Kabul_Paket_2026-11-05\`  
   - `yedek\cin_sistem_deneme.dump` SHA-256 `99c70fe00c9d2ed46d6244a74b0c90d6d2f88ed3ce2961cf1ef7670b43f360e7`  
   - `yedek\cin_firma_deneme.dump` SHA-256 `07e6e5fc02040d8e2bc8f5c45edbc55251ad7ab6e07230a5cda93f2619e49af4`  
   - `yedek\SHA256.txt`, `OKU_BENI.txt`
2. `kurulum\sunucu\03_pg_kabul_kopya.ps1` — korunan ad / kaynak≠hedef denetimi  
3. `kurulum\sunucu\04_pg_restore_ayri_hedef.ps1` — korunan ad; `--create` yok; boş hedef zorunlu  
4. `kurulum\sunucu\05_ana_makine_kabul_calistir.ps1` — kopya+restore tek akış

## 3) EXE (yeniden derleme yok)

| Alan | Değer |
|------|--------|
| Yol | `dist\CinMuhasebe\CinMuhasebe.exe` |
| SHA-256 | `0BD255BA888BF68F0AE1EF502AD562AE3DE4C0FBFEEE19453EF37308CB64C27C` |
| Boyut | 24376959 |
| Not | Kod/paketleme bu adımda değişmedi; gerekçesiz rebuild yok |

İki PC bağlama ve UI testleri: **DENENMEDİ** (kabul DB yok).

## 4) Test durumu (bu devam oturumu)

| Test | Durum |
|------|--------|
| Ortam/DB/SHA doğrulama | **GEÇTİ** |
| İzole TEMPLATE kopya | **DENENMEDİ** (ana makine postgres gerekli) |
| Ayrı hedefe restore | **DENENMEDİ** |
| İki PC EXE + verify-full UI | **DENENMEDİ** |
| Eşzamanlı fatura/barkod/kesinti UI | **DENENMEDİ** |
| Mali fark (yeni) | ölçülmedi / önceki mutabakat boş |

## 5) Kullanıcıya sıradaki **tek** adım

**Bilgisayar:** DESKTOP-CGSE5GK (ana makine, PostgreSQL sunucusu)

1. Paketi ana makineye kopyalayın:  
   `C:\Users\cigde\AppData\Local\CinMuhasebeAktarim\AnaMakine_Kabul_Paket_2026-11-05`  
   (veya USB; kopya sonrası `SHA256.txt` ile hash doğrulayın)
2. Ana makinede PowerShell (parolayı güvenli istemle girin; sohbete yazmayın):

```powershell
cd C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi
.\kurulum\sunucu\05_ana_makine_kabul_calistir.ps1 `
  -DumpKlasor "C:\Users\cigde\AppData\Local\CinMuhasebeAktarim\AnaMakine_Kabul_Paket_2026-11-05\yedek"
```

(`DumpKlasor` kopyaladığınız gerçek yolu kullanın. `-PgHost 127.0.0.1` varsayılan.)

**Beklenen:**  
`cin_sistem_kabul_20261105` / `cin_firma_kabul_20261105`  
`cin_sistem_restore_20261105` / `cin_firma_restore_20261105`  
+ `yedek\SONUC_DESKTOP-CGSE5GK_*.txt`

Sonra bu sohbete dönün; kabul çiftine DENEME profili + iki PC EXE testleri tamamlanır.

## 6) Canlı geçiş notu

04.11 deneme kaynağı güncel operasyon sayılmaz (04–05.11 faturalar raporlanmış). Bu görevde Evo aktarımı ve günlük bağlantı değişimi **yapılmadı**.
