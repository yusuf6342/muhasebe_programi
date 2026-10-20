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

## Bekleyen eski stok çalışması — inceleme sonucu

- `Cin_Bekleyen_Stok_Calismasi.txt` içindeki beş dosyalık eski çalışma,
  20 Ekim 2026 tarihli `1c8f4e3` ana dal koduyla karşılaştırıldı:
  `app.py`, `database/database.py`, `database/models/stok.py`,
  `database/stok_service.py`, `main.py`.
- Stok kartı açıklamaları, birimler, resimler, muhasebe kodları, barkodlar,
  iskonto hesabı, fiyat geçmişi ve stok hareketlerinin güncel kodda karşılıkları var.
  Eski `app.py` içindeki stok ekranları güncel sürümde `stok_ui.py` dosyasına taşınmış.
- Bu kaynak kod incelemesinde ayrıca aktarılması gereken eksik bir özellik
  saptanmadı. Bu sonuç, stok özelliklerinin tamamının uygulamada test edildiği anlamına gelmez.
- Eski değişiklikler güncel koda doğrudan uygulanırken çakışıyor.
  Bekleyen kaydı topluca geri yüklemeyin (Restore / stash pop).
  Güncel `main` üzerinden devam edin.
- Bekleyen kayıt ve dışa alınan dosya yedek olarak korunsun; silinmesin (Discard).
  İleride belirli bir eksiklik bulunursa yalnız ilgili değişiklik güncel kodla
  karşılaştırılarak, ayrı bir dalda ve uygun testlerle değerlendirilsin.
