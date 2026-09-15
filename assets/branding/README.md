# Branding dosyaları (runtime yolu: assets/branding/)

| Dosya | Kullanım |
|--------|----------|
| `CinAcilis.png` | Splash / giriş / Hakkında görseli |
| `CinLogo.png` | Tkinter `iconphoto` (ana + alt pencereler) |
| `CinLogo.ico` | Windows `iconbitmap`, EXE ikonu, masaüstü kısayolu |

PyInstaller `CinMuhasebe.spec` tüm klasörü `datas` olarak paketler; EXE `icon=` yalnızca `.ico` kullanır.
