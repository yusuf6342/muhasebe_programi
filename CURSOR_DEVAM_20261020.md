# Cin Muhasebe — 20 Ekim 2026 devam notu

- Bilgisayardaki mevcut kaynak kod korunarak devam edilmeli.
- Toplu Stok Grubu Eşleştirme ekranındaki alt düğmeler düzeltildi.
- Seçim, ön izleme ve güvenli aktarım kontrolleri güncellendi.
- Düzeltmeler yerel stok_grup_toplu_ui.py ve
  database/stok_grup_toplu_service.py dosyalarına uygulanmıştır.
- Windows EXE oluşturuldu ve açıldı. Ray Mobilya, 2026 döneminde
  11 ürün AYAK GRUBU'na başarıyla aktarıldı; işlem geçmişinde görüldü.
- Kullanılan masaüstü kısayolu: Cin Muhasebe - Guncel.
- Gerçek veri yolu: %LOCALAPPDATA%\MuhasebeProgrami\data
- CinMuhasebeTest\data ayrı test verisidir; gerçek verinin yerine bağlanmamalı.
- Güncel EXE: %LOCALAPPDATA%\CinMuhasebeGuncelleme altındaki
  ilgili derlemenin dist\CinMuhasebe\CinMuhasebe.exe dosyasıdır.
- Mevcut CinMuhasebe.spec içindeki personel modülleri korunmalı.
- GitHub PR #1'deki iki kaynak kod düzeltmesi yerelde zaten uygulanmıştır.
  PR içindeki ek testler ayrıca incelenebilir.
- Stok grubu düzeltmesinde 32 otomatik test geçti.
  Diğer yerel modüllerin tamamı bu çalışmada test edilmedi.
- inceleme klasörü yerel tutulur; içeriği silinmemeli.
- Yeni değişikliklerden sonra ilgili testler çalıştırılmalı, EXE yeniden
  oluşturulmalı ve kısayolun doğru EXE ile veri yolunu kullandığı doğrulanmalı.
