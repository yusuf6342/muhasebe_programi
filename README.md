# Muhasebe Programı

Python + Tkinter ile yazılmış masaüstü muhasebe uygulaması (stok, cari, fatura, finans, EvoBulut entegrasyonu).

**GitHub:** https://github.com/yusuf6342/muhasebe_programi

## Bu bilgisayara kurulum (Windows)

1. Bilgisayarda [Python 3](https://www.python.org/downloads/) kurulu olsun. Kurulumda **Add Python to PATH** işaretli olsun.
2. Projeyi indirin:
   - GitHub’da yeşil **Code → Download ZIP**, zip’i açın  
   - veya: `git clone https://github.com/yusuf6342/muhasebe_programi.git`
3. Klasörde **`masaustu_kisayol.bat`** dosyasına çift tıklayın.
4. Masaüstünde **Muhasebe Programi** kısayolu oluşur. Bundan sonra sadece ona çift tıklayın.

Alternatif: doğrudan **`calistir.bat`** ile de açabilirsiniz.

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
