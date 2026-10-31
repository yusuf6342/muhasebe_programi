# Son Teslim Raporu — 31.10.2026

## Push edilen commit’ler (`main` → `origin/main`)

| Kısa | Konu |
|---|---|
| `2346d85` | Alınan Sipariş: fatura alt toplamları, uzlaşılan fiyat, Teklif satır yüksekliği, excel çizgi |
| `a54bcbc` | Cari kart hareket sütun görünümü + bakiye/risk özet hizası |
| `1620131` | Sorulan ürün: ölçüm/tekrar/görüşme/tarih log + UI/test |
| `1b5af5b` | Satış faturası: açılış odağı, irsaliyeden seçim, takvim bağlama, Teklifler menü araması |
| *(bu dosya güncellemesi)* | Kapanış raporu |

## Alınan Sipariş — tamamlanan kontroller
- Footer iki kolon (fatura ile aynı yerleşim); Net = Uzlaşılan
- Uzlaşılan Tutar / Fiyatları Düzenle / Dağıtımı Geri Al
- Satır yüksekliği Teklif = Sipariş (**29 / 29** bbox)
- F10 bind, sağ tık/çift tık altyapısı, Tab/Enter, MouseWheel
- Kaydet → yeniden aç; tam/kısmi aktarım (canlı DB **kopyası**)

## Paketlenmiş EXE’de yapılamayan / başarı sayılmayan canlı kontroller
- Girişli dondurulmuş EXE oturumunda menüden uçtan uca fare tıklaması (oturum kapalı / giriş şifresi yok; Computer Use odak çakışması)
- Doğrulama: commit edilen kaynak + canlı DB kopyası + Tk Alınan Sipariş kartı üzerinden yapıldı — **EXE UI oturumu başarı sayılmadı**

## Cari / Sorulan ürün / Fatura (bu kapanışta gönderilen)
- Cari: ürün sütun aç-kapa, sütun sığdırma; borç/alacak özet kutusu fatura üst alan yüksekliğine uyum; çift kayıtsız satışta kapanan tutarın bakiyeye yansıması
- Sorulan ürün: ek tablolar (ölçü/ek/tekrar/görüşme/tarih log), etiketler, UI yenileme/tekrar, testler
- Fatura: Müşteri Adı ilk odak, barkod F8; `fatura_irsaliye_secim_ui`; `takvim_entry_bagla`; menü aramasında Teklifler

## EXE
- Yol: `dist\CinMuhasebe\CinMuhasebe.exe`
- Derleme: kapanış rebuild (kaynak = push edilen son commit’ler)
- Masaüstü: `Cin Muhasebe.lnk` → aynı EXE

## Commit dışı bırakılanlar (silinmedi)
| Ne | Neden |
|---|---|
| `Banka_Guncelleme_Yedek/` | Yedek klasörü |
| `tmp_screens/`, `_fiyat_tab_*.png`, `_talimat_extract/` | Geçici ekran/talimat çıktıları |
| `tools/_shots_*`, `tools/_tmp_*`, ölçüm/png/txt çıktıları | Geçici doğrulama artefaktları |
| `tools/_siparis_*`, `_fatura_*`, `_teklif_*`, `_stok_kart_*`, `_tani_*`, `_verify_*`, müşteri tarama scriptleri | Yerel yardımcı / tanı; ürün kaynak değil; bazıları müşteri verisine değebilir |
| Canlı `muhasebe.db` / system.db / şirket DB | Veritabanı |
| Şifre / lisans dosyaları | Güvenlik |

## Dal
`main` — force push yok.
