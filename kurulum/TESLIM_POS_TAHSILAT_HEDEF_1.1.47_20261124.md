# Teslim — POS tahsilat aktarım hedefi (MEVDUAT/KMH) 1.1.47

## Kök neden

**Kaynak kod** — tahsilat makbuzu kaydında POS satırı yalnız KMH arıyordu; kartta tanımlı MEVDUAT hedefi (ör. 002 Enpara) «KMH hesabı eksik» diye engelleniyordu. Ayar düzeltmesi yeterli değildi.

## Ortak çözüm

- `FinansService._pos_hedef_hesap`: tüm POS kartları için `pos_aktarim_hesap_id` → MEVDUAT/KMH; pasif / başka karta ait hedefler elenir.
- Makbuz kaydı aynı ortak çözümü kullanır; eksik/pasif/yanlış kartta net hata, yarım kayıt yok.
- Enpara / hesap id özel dal yok.

## POS hesap kontrolü (DNM D2 canlı, yazma yok)

| pos_id | ad | aktif | kart | hedef | durum |
|--|--|--|--|--|--|
| 5 | 001 AKBANK … POS | E | 1 | 4 KMH | OK |
| 8 | Enpara Şirket POS | E | 2 | 162 MEVDUAT | OK |
| 10 | 002 ENPARA … POS | E | 2 | 162 MEVDUAT | OK |
| 15 | 003 YAPI KREDİ … POS | E | 3 | 14 KMH | OK |
| 18 | PayTR | E | 3 | 14 KMH | OK |

- Aktif POS: **5/5 tahsilata uygun** — veri düzeltmesi gerekmedi.
- Pasif 22 POS (eski kredi/PayTR vb.): tahsilatta kullanılmaz; 01 Enpara yeniden oluşturulmadı.
- JSON: `kurulum/dnm_d2_20260901/rapor/D2_POS_HEDEF_KONTROL_20261124.json`

## Testler

- Unit: MEVDUAT, KMH, eksik hedef, pasif hedef, çok satır + hata→yarım kayıt yok — **5/5 OK**
- Canlı 2000 TL makbuz **kaydedilmedi**

## Sürüm / T1

| Madde | Değer |
|--|--|
| Sürüm | **1.1.47** |
| EXE SHA-256 | `F2522DE19D62EDB80F2E5069E313EBDE3D54C4805EAC13D18968355ED5E950D8` |
| T1 kurulum | `%LOCALAPPDATA%\CinMuhasebe\DNM_D2\CinMuhasebe\` |
| Kısayol | `Cin Muhasebe.lnk` hedef/ad korundu → aynı EXE |
| Yedek | `%LOCALAPPDATA%\CinMuhasebe\DNM_D2_GERI_20261124_174730` |
| baglanti | korundu (host 192.168.1.114) |
| Zorla kapatma | **Yok** (uygulama zaten kapalıydı) |

## USB / Ana / T2

| Madde | Yol |
|--|--|
| USB teslim | `D:\USB_TESLIM_20261124_POS_TAHSILAT_1.1.47\` |
| ZIP | `CinMuhasebe_DNM_D2_GUNCELLE_20261124_1746.zip` |
| ZIP SHA-256 | `2CFCD5B53007C5E427B243FB8272CB07346D0422294ACC7E0D8FA0E6BBF5C155` |
| USB GUNCELLE | `D:\CinMuhasebe\GUNCELLE.cmd` → [2] Ana / [3] T2 |
| Ortak kurulum | **korundu** — `D:\USB_TESLIM_20261124_HIZLI_SATIS_1.1.46\CinMuhasebe_Ortak_Kurulum_1.1.46.exe` (yeniden üretilmedi) |

Temiz kurulum yaptırmayın; mevcut klasör + DB + ayarlar korunur.
