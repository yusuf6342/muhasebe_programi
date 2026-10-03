"""Açılış veritabanı geçişlerinin yedek güvencesi.

Mevcut (veri içeren) bir firma veritabanı dönüştürülecekse önce SQLite backup API ile tarihli
yedek alınır; yedek bütünlük (``integrity_check``) ve tablo satır sayılarıyla doğrulanmadan geçiş
başlamaz. Doğrulanan yedek yalnız bu süreçte, bu veritabanı dosyası için ve kısa süre geçerli bir
onay olarak tutulur: eski tarihli ya da başka veritabanına ait yedek geçiş yedeği sayılmaz.

Geçiş ortasında hata olursa veritabanı az önce alınan yedekten geri yüklenir (SQLite'ta DDL
transaction dışında kalıcılaştığından yarım şema ancak böyle temizlenir). Yeni/boş veritabanı
oluşturma bu akışa girmez: korunacak veri yoktur.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

ONAY_SURESI_SN = 30 * 60
YEDEK_KLASORU = "yedekler"


class GecisYedekHatasi(RuntimeError):
    """Yedek alınamadı/doğrulanamadı: geçiş başlatılmadı, veritabanı değişmedi."""

    def __init__(self, neden: str, *, yedek_yolu: Path | None = None):
        self.neden = neden
        self.yedek_yolu = yedek_yolu
        super().__init__(
            "Veritabanı güncellemesi başlatılmadı: güncelleme öncesi yedek "
            f"{'doğrulanamadı' if yedek_yolu else 'alınamadı'}.\n\nNeden: {neden}\n\n"
            "Verileriniz değiştirilmedi. Diskte yer açıp yazma izinlerini kontrol ettikten sonra "
            "programı yeniden açarak (veya firmayı yeniden seçerek) tekrar deneyin."
        )


class GecisHatasi(RuntimeError):
    """Geçiş yarıda kaldı; veritabanı geçiş öncesi yedekten geri yüklendi (veya yüklenemedi)."""

    def __init__(self, neden: str, *, yedek_yolu: Path | None, geri_yuklendi: bool):
        self.neden = neden
        self.yedek_yolu = yedek_yolu
        self.geri_yuklendi = geri_yuklendi
        if geri_yuklendi:
            metin = (
                "Veritabanı güncellemesi tamamlanamadı; veritabanı güncelleme öncesi haline geri "
                f"döndürüldü.\n\nNeden: {neden}\n\nTekrar denemek için programı yeniden açın."
            )
        else:
            metin = (
                "Veritabanı güncellemesi tamamlanamadı ve otomatik geri dönüş yapılamadı.\n\n"
                f"Neden: {neden}\n\nGüncelleme öncesi doğrulanmış yedek: {yedek_yolu}\n"
                "Programı kullanmadan önce bu yedeği geri yükleyin."
            )
        super().__init__(metin)


@dataclass(frozen=True)
class GecisYedegi:
    kaynak: Path
    yol: Path
    zaman: datetime
    tablo_sayilari: dict[str, int] = field(compare=False)
    _monotonik: float = field(default_factory=time.monotonic, compare=False)


_onaylar: dict[str, GecisYedegi] = {}
_kilit = threading.Lock()


def _anahtar(db_yolu: Path | str) -> str:
    return str(Path(db_yolu).resolve()).casefold()


def tablo_sayilari(yol: Path | str) -> dict[str, int]:
    c = sqlite3.connect(f"file:{Path(yol).as_posix()}?mode=ro", uri=True)
    try:
        adlar = [r[0] for r in c.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        return {a: c.execute(f'select count(*) from "{a}"').fetchone()[0] for a in adlar}
    finally:
        c.close()


def veri_var_mi(db_yolu: Path | str) -> bool:
    """Dosyada en az bir satır içeren tablo var mı (yoksa yeni/boş veritabanı)."""
    yol = Path(db_yolu)
    if not yol.is_file() or yol.stat().st_size == 0:
        return False
    return any(tablo_sayilari(yol).values())


def sema_eksikleri(motor, metadata) -> list[str]:
    """Modellerde olup veritabanında bulunmayan tablo/kolonlar (açılış geçişi gerekiyor mu)."""
    from sqlalchemy import inspect

    denetci = inspect(motor)
    mevcut = set(denetci.get_table_names())
    eksik: list[str] = []
    for ad, tablo in metadata.tables.items():
        if ad not in mevcut:
            eksik.append(ad)
            continue
        kolonlar = {k["name"] for k in denetci.get_columns(ad)}
        eksik.extend(f"{ad}.{k.name}" for k in tablo.columns if k.name not in kolonlar)
    return eksik


def _dogrula(kaynak: Path, hedef: Path) -> tuple[str | None, dict[str, int]]:
    c = sqlite3.connect(f"file:{hedef.as_posix()}?mode=ro", uri=True)
    try:
        butunluk = c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()
    s_kaynak = tablo_sayilari(kaynak)
    s_yedek = tablo_sayilari(hedef)
    if butunluk != "ok":
        return f"yedek bütünlük denetimi başarısız ({butunluk})", s_yedek
    if s_kaynak != s_yedek:
        farkli = sorted(t for t in set(s_kaynak) | set(s_yedek) if s_kaynak.get(t) != s_yedek.get(t))
        return f"tablo satır sayıları kaynakla eşleşmiyor ({', '.join(farkli[:5])})", s_yedek
    return None, s_yedek


def _yedek_dosyasi_al(kaynak: Path, hedef: Path) -> None:
    k = sqlite3.connect(str(kaynak), timeout=30)
    h = sqlite3.connect(str(hedef))
    try:
        k.backup(h)
    finally:
        h.close()
        k.close()


def dogrulanmis_yedek(db_yolu: Path | str, etiket: str = "gecis") -> GecisYedegi:
    """Tarihli, doğrulanmış yedek alır ve bu veritabanı için geçiş onayı olarak kaydeder."""
    db = Path(db_yolu).resolve()
    if not db.is_file():
        raise GecisYedekHatasi(f"veritabanı dosyası bulunamadı: {db}")
    zaman = datetime.now()
    klasor = db.parent / YEDEK_KLASORU / f"{etiket}_{zaman:%Y%m%d_%H%M%S_%f}"
    hedef = klasor / db.name
    try:
        klasor.mkdir(parents=True, exist_ok=False)
        _yedek_dosyasi_al(db, hedef)
    except (OSError, sqlite3.Error) as hata:
        try:
            if hedef.exists():
                hedef.unlink()
            klasor.rmdir()
        except OSError:
            pass
        raise GecisYedekHatasi(f"yedek dosyası yazılamadı ({hata})") from hata
    try:
        sorun, sayilar = _dogrula(db, hedef)
    except (OSError, sqlite3.Error) as hata:
        sorun, sayilar = f"yedek okunamadı ({hata})", {}
    rapor = (
        f"Kaynak: {db}\nYedek: {hedef}\nZaman: {zaman:%Y-%m-%d %H:%M:%S}\n"
        f"Tablo: {len(sayilar)} / Satır: {sum(sayilar.values())}\n"
        f"Sonuç: {'GEÇERSİZ - ' + sorun if sorun else 'doğrulandı (integrity_check ok, satır sayıları eşit)'}\n"
    )
    try:
        (klasor / "DOGRULAMA.txt").write_text(rapor, encoding="utf-8")
    except OSError:
        pass
    if sorun:
        try:
            klasor.rename(klasor.with_name(klasor.name + "_GECERSIZ"))
        except OSError:
            pass
        raise GecisYedekHatasi(sorun, yedek_yolu=hedef)
    yedek = GecisYedegi(kaynak=db, yol=hedef, zaman=zaman, tablo_sayilari=sayilar)
    with _kilit:
        _onaylar[_anahtar(db)] = yedek
    return yedek


def yedek_onayi(db_yolu: Path | str | None) -> GecisYedegi | None:
    """Bu veritabanı için bu süreçte alınmış, süresi geçmemiş ve dosyası duran yedek onayı."""
    if not db_yolu:
        return None
    with _kilit:
        yedek = _onaylar.get(_anahtar(db_yolu))
    if yedek is None:
        return None
    if time.monotonic() - yedek._monotonik > ONAY_SURESI_SN or not yedek.yol.is_file():
        onayi_dus(db_yolu)
        return None
    return yedek


def onayi_dus(db_yolu: Path | str) -> None:
    with _kilit:
        _onaylar.pop(_anahtar(db_yolu), None)


def yedekten_geri_yukle(yedek: GecisYedegi) -> None:
    """Geçiş öncesi yedeği kaynak dosyaya geri yazar ve satır sayılarını doğrular."""
    _yedek_dosyasi_al(yedek.yol, yedek.kaynak)
    if tablo_sayilari(yedek.kaynak) != yedek.tablo_sayilari:
        raise RuntimeError("geri yükleme sonrası tablo satır sayıları yedekle eşleşmiyor")


def guvenli_gecis(
    db_yolu: Path | str,
    adimlar: Callable[[], T],
    *,
    gerekli: bool,
    etiket: str = "gecis",
    baglantilari_kapat: Callable[[], None] | None = None,
) -> tuple[T, GecisYedegi | None]:
    """``adimlar``ı yedek güvencesiyle çalıştırır.

    - Geçiş gerekmiyorsa veya veritabanı yeni/boşsa doğrudan çalıştırır.
    - Aksi halde doğrulanmış yedek alınamazsa ``GecisYedekHatasi`` (adımlar hiç çalışmaz).
    - Adımlar hata verirse yedek geri yüklenir ve ``GecisHatasi`` fırlatılır.
    """
    if not gerekli or not veri_var_mi(db_yolu):
        return adimlar(), None
    yedek = dogrulanmis_yedek(db_yolu, etiket)
    try:
        sonuc = adimlar()
    except Exception as hata:
        if baglantilari_kapat is not None:
            try:
                baglantilari_kapat()
            except Exception:
                pass
        try:
            yedekten_geri_yukle(yedek)
        except Exception as geri_hata:
            raise GecisHatasi(
                f"{hata} (geri yükleme hatası: {geri_hata})", yedek_yolu=yedek.yol, geri_yuklendi=False
            ) from hata
        raise GecisHatasi(str(hata), yedek_yolu=yedek.yol, geri_yuklendi=True) from hata
    finally:
        onayi_dus(db_yolu)
    return sonuc, yedek
