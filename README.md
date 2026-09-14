# Muhasebe Programı

Python + Tkinter ile yazılmış masaüstü muhasebe uygulaması (stok, cari, fatura, finans, EvoBulut entegrasyonu).

**GitHub:** https://github.com/yusuf6342/muhasebe_programi

## En kolay kurulum (Windows) — önerilen

`.bat` dosyası Notepad/Cursor ile açılıyorsa bu yöntemi kullanın. **PowerShell** penceresini açın (Windows tuşu → `powershell` yazın → Enter) ve şu satırı yapıştırıp Enter’a basın:

```powershell
irm https://raw.githubusercontent.com/yusuf6342/muhasebe_programi/main/kurulum_masaustu.ps1 | iex
```

Kurulum bitince masaüstünde **Muhasebe Programi** kısayolu oluşur. Bundan sonra sadece ona çift tıklayın.

> Bilgisayarda [Python 3](https://www.python.org/downloads/) kurulu olsun. Kurulumda **Add Python to PATH** işaretli olsun.

## Alternatif: .bat ile kurulum

1. [kurulum_masaustu.bat](https://raw.githubusercontent.com/yusuf6342/muhasebe_programi/main/kurulum_masaustu.bat) dosyasını indirin.
2. İndirilen dosyaya **sağ tık → Birlikte aç → Komut İstemi** (veya **cmd.exe**) seçin.  
   Çift tıklayınca metin editörü açılıyorsa aşağıdaki “.bat metin olarak açılıyor” bölümüne bakın.

Projeyi zip ile indirdiyseniz klasördeki **`masaustu_kisayol.bat`** ile de kısayol oluşturabilirsiniz.

## .bat metin olarak açılıyor (Windows düzeltmesi)

Bu genelde şu yüzden olur: dosya aslında `.bat.txt` kalmıştır, veya `.bat` varsayılanı Notepad / Cursor yapılmıştır.

### 1) Gerçek uzantıyı görün

1. Dosya Gezgini → **Görünüm** → **Göster** → **Dosya adı uzantıları** (açık olsun).
2. Masaüstünde dosya adı `kurulum_masaustu.bat.txt` ise → sağ tık → **Yeniden adlandır** → `.txt` kısmını silin → `kurulum_masaustu.bat` olsun.

### 2) .bat’ı tekrar Komut İstemi ile açtırın

1. Herhangi bir `.bat` dosyasına **sağ tık** → **Birlikte aç** → **Başka bir uygulama seç**.
2. **Komut İstemi** / `cmd.exe` seçin.
3. **Her zaman bu uygulamayı kullan** / **Her zaman bu uygulamayla aç** işaretleyin → Tamam.

Komut İstemi’nde (yönetici gerekmez) şunu da çalıştırabilirsiniz:

```cmd
assoc .bat=batfile
ftype batfile="%1" %*
```

### 3) OneDrive / Masaüstü notu

Masaüstünüz `C:\Users\Pc\OneDrive\Masaüstü\` ise sorun değil; kurulum OneDrive masaüstüne de kısayol koyar. Dosyayı yeniden adlandırırken OneDrive senkronu bitene kadar bekleyin.

## macOS / Linux

```bash
git clone https://github.com/yusuf6342/muhasebe_programi.git
cd muhasebe_programi
chmod +x calistir.sh masaustu_kisayol.sh
./masaustu_kisayol.sh
```

## Manuel çalıştırma

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Gereksinimler

- Python 3.10+
- `SQLAlchemy`, `openpyxl` (`requirements.txt`)
- Tkinter (Windows/macOS’ta Python ile birlikte gelir)
