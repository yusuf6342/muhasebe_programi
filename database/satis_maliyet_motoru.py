"""Satış maliyeti yöntemleri — firma stok hareket geçmişinden salt okunur hesap.

FIFO satış anında kaydedilen gerçek çıkış maliyetidir (``SatisFaturasiService.satir_birim_maliyeti``); bu modül
yalnız FIFO katman ayrıntısını ve diğer yöntemleri üretir. Hiçbir stok, fatura, cari veya muhasebe kaydı
değiştirilmez; sonuç yalnız rapor hesabında kullanılır.

Hesap kuralları (temel birim başına):
  * Hareket geçmişi firma geneli ve ürün bazındadır; müşteri/ürün filtresi geçmişi daraltmaz. Depolar arası
    transfer firma toplamını değiştirmediği için yok sayılır. Önceki yıllardan devreden hareketler dahildir.
  * Hareketli ağırlıklı ortalama: her girişte (miktar × maliyet) havuza eklenir; çıkışlar o anki ortalamayla
    düşer. Satış iadesi girişleri ortalamayı değiştirmeden geri döner. Satıştan sonraki alışlar etkilemez.
  * Dönemsel ağırlıklı ortalama (aylık): (ay açılış stok değeri + ay içi girişler) / (açılış miktarı + ay içi
    giriş miktarı); ay kapanışı bu ortalamayla değerlenir ve sonraki ayın açılışı olur.
  * Son alış maliyeti: satış tarihine kadarki son maliyetli alış girişinin birim maliyeti (karşılaştırma amaçlı).
  * Standart maliyet: satış tarihinde geçerli tanımlı standart maliyet (karşılaştırma amaçlı).
  * Girişlerin maliyetine dağıtılmış nakliye/masraf payı hareket maliyetine işlenmiş olduğundan dahildir.
  * Maliyet bulunamazsa sıfır verilmez; None ve gerekçe döner.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import inspect, select

from database.models.stok import StokHareketi, StokKarti, StokLotu, StokStandartMaliyet

HAREKETLI = "HAREKETLİ AĞIRLIKLI ORTALAMA"
DONEMSEL = "DÖNEMSEL AĞIRLIKLI ORTALAMA (AYLIK)"
SON_ALIS = "SON ALIŞ MALİYETİ (KARŞILAŞTIRMA AMAÇLI)"
STANDART = "STANDART MALİYET (KARŞILAŞTIRMA AMAÇLI)"
GECMIS_YONTEMLER = (HAREKETLI, DONEMSEL, SON_ALIS, STANDART)
KARSILASTIRMA_AMACLI = frozenset({SON_ALIS, STANDART})

_TRANSFER = frozenset({"TRANSFER GİRİŞ", "TRANSFER ÇIKIŞ"})
_IADE_GIRIS = frozenset({"İADE GİRİŞ", "İRSALİYE İADE GİRİŞ"})
_ALIS_GIRIS = frozenset({"FATURA GİRİŞ", "GİRİŞ"})
_SATIS_CIKIS = frozenset({"FATURA ÇIKIŞ", "İRSALİYE ÇIKIŞ"})

SIFIR = Decimal("0")
DORT = Decimal("0.0001")
_SIFIR_ESIK = Decimal("0.0001")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _tur(hareket_turu: str) -> str | None:
    t = (hareket_turu or "").strip()
    if t in _TRANSFER:
        return "transfer"
    if t in _IADE_GIRIS:
        return "iade"
    if "GİRİŞ" in t:
        return "giris"
    if "ÇIKIŞ" in t:
        return "cikis"
    return None


@dataclass
class _Hareket:
    id: int
    tarih: date
    tur: str
    hareket_turu: str
    belge_no: str
    miktar: Decimal
    maliyet: Decimal


def standart_tablo_var(session) -> bool:
    try:
        return inspect(session.connection()).has_table(StokStandartMaliyet.__tablename__)
    except Exception:  # noqa: BLE001
        return False


def satis_belge_nolari(session, fatura, satir) -> tuple[str, ...]:
    """Satış satırının stok çıkışını taşıyan belge numaraları (fatura; irsaliyeli satırda irsaliye)."""
    nolar = [fatura.fatura_no] if fatura is not None and fatura.fatura_no else []
    if getattr(satir, "irsaliye_satiri_id", None):
        from database.satis_faturasi_service import SatisFaturasiService

        try:
            ir = SatisFaturasiService._satir_irsaliyesi(session, fatura, satir)
        except Exception:  # noqa: BLE001
            ir = None
        if ir is not None and ir.irsaliye_no:
            nolar.insert(0, ir.irsaliye_no)
    return tuple(nolar)


def fifo_katmanlari(session, stok_id: int | None, belge_nolari: Iterable[str]) -> list[dict[str, Any]]:
    """Satış çıkışında tüketilen giriş katmanları (lot) ve miktarları."""
    nolar = [n for n in belge_nolari if n]
    if not stok_id or not nolar:
        return []
    satirlar = session.execute(
        select(StokHareketi, StokLotu)
        .outerjoin(StokLotu, StokLotu.id == StokHareketi.lot_id)
        .where(StokHareketi.stok_id == int(stok_id), StokHareketi.belge_no.in_(nolar),
               StokHareketi.hareket_turu.in_(tuple(_SATIS_CIKIS)))
        .order_by(StokHareketi.id)
    ).all()
    out = []
    for h, lot in satirlar:
        m, b = _d(h.miktar), _d(h.birim_maliyet)
        out.append({
            "hareket_id": int(h.id), "belge_no": h.belge_no, "hareket_turu": h.hareket_turu, "tarih": h.tarih,
            "lot_id": int(lot.id) if lot is not None else None, "lot_no": lot.lot_no if lot is not None else "",
            "giris_tarihi": lot.giris_tarihi if lot is not None else None,
            "tedarikci": (lot.tedarikci or "") if lot is not None else "",
            "miktar": m, "birim_maliyet": b, "tutar": (m * b).quantize(Decimal("0.01")),
        })
    return out


def _lot_giris_belgeleri(session, lot_idler: Iterable[int]) -> dict[int, tuple[str, date | None]]:
    idler = [int(i) for i in lot_idler if i]
    if not idler:
        return {}
    out: dict[int, tuple[str, date | None]] = {}
    for lot_id, belge, tarih, ht in session.execute(
            select(StokHareketi.lot_id, StokHareketi.belge_no, StokHareketi.tarih, StokHareketi.hareket_turu)
            .where(StokHareketi.lot_id.in_(idler)).order_by(StokHareketi.id)).all():
        if int(lot_id) not in out and _tur(ht) in ("giris", "iade", "transfer") and "GİRİŞ" in (ht or ""):
            out[int(lot_id)] = (belge or "", tarih)
    return out


def _dagit(hareketler: list[dict], ihtiyaclar: list[tuple[Any, Decimal]]) -> dict[Any, list[dict]]:
    """Çıkış katmanlarını sırayla satırlara böler; her katman miktarı yalnız bir kez kullanılır."""
    out: dict[Any, list[dict]] = {k: [] for k, _m in ihtiyaclar}
    kuyruk = [dict(h) for h in hareketler]
    i = 0
    for anahtar, gereken in ihtiyaclar:
        kalan = gereken
        while kalan > 0 and i < len(kuyruk):
            h = kuyruk[i]
            al = min(kalan, h["miktar"])
            if al > 0:
                out[anahtar].append({**h, "miktar": al, "tutar": (al * h["birim_maliyet"]).quantize(Decimal("0.01"))})
            h["miktar"] -= al
            kalan -= al
            if h["miktar"] <= 0:
                i += 1
    return out


def satir_fifo_katmanlari(session, fatura, satir) -> tuple[list[dict[str, Any]], str]:
    """Tek fatura satırının tükettiği giriş katmanları. Aynı üründen birden çok satır varsa çıkışlar satır
    sırasıyla bölünür; irsaliyeli satırda irsaliye çıkışı irsaliye satırına bölünür ve faturalanan paya indirgenir."""
    from database.models.satis_irsaliyesi import SatisIrsaliyesi
    from database.satis_faturasi_service import SatisFaturasiService
    from database.stok_service import StokService

    kod = (satir.urun_kodu or "").strip()
    stok_id = session.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == kod))
    if stok_id is None:
        return [], "Stok kartı yok."
    not_ = ""
    if getattr(satir, "irsaliye_satiri_id", None):
        ir = SatisFaturasiService._satir_irsaliyesi(session, fatura, satir)
        if ir is None:
            return [], "İrsaliye bulunamadı."
        ir = session.get(SatisIrsaliyesi, ir.id)
        kardesler = sorted((s for s in ir.satirlar if (s.urun_kodu or "").strip() == kod), key=lambda s: s.id)
        hareketler = fifo_katmanlari(session, stok_id, (ir.irsaliye_no,))
        ihtiyac = [(s.id, _d(s.miktar) * StokService.satir_birim_carpani(session, s)) for s in kardesler]
        bolum = _dagit(hareketler, ihtiyac).get(int(satir.irsaliye_satiri_id), [])
        ir_miktar = dict(ihtiyac).get(int(satir.irsaliye_satiri_id), SIFIR)
        f_miktar = _d(satir.miktar) * StokService.satir_birim_carpani(session, satir)
        if ir_miktar > 0 and f_miktar != ir_miktar:
            oran = f_miktar / ir_miktar
            bolum = [{**k, "miktar": k["miktar"] * oran, "tutar": (k["tutar"] * oran).quantize(Decimal("0.01"))}
                     for k in bolum]
            not_ = f"İrsaliye {ir.irsaliye_no} kısmen faturalandı; katmanlar faturalanan paya ({oran:.4f}) indirgendi."
        else:
            not_ = f"Stok çıkışı irsaliye {ir.irsaliye_no} ile yapıldı; maliyet bir kez sayılır."
    else:
        kardesler = sorted((s for s in fatura.satirlar if (s.urun_kodu or "").strip() == kod
                            and not getattr(s, "irsaliye_satiri_id", None)), key=lambda s: s.id)
        hareketler = fifo_katmanlari(session, stok_id, (fatura.fatura_no,))
        ihtiyac = [(s.id, _d(s.miktar) * StokService.satir_birim_carpani(session, s)) for s in kardesler]
        bolum = _dagit(hareketler, ihtiyac).get(int(satir.id), [])
        if len(kardesler) > 1:
            not_ = (f"Belgede bu üründen {len(kardesler)} satır var; çıkış katmanları satır sırasıyla ayrıldı "
                    "(her katman miktarı bir kez).")
    giris = _lot_giris_belgeleri(session, [k["lot_id"] for k in bolum])
    for k in bolum:
        belge, tarih = giris.get(k["lot_id"] or 0, ("", None))
        k["giris_belge_no"] = belge
        if k.get("giris_tarihi") is None:
            k["giris_tarihi"] = tarih
    return bolum, not_


class MaliyetMotoru:
    """Bir rapor çalıştırması boyunca ürün bazında maliyet zaman çizelgelerini önbellekte tutar."""

    def __init__(self, session, bitis: date | None = None):
        self.session = session
        self.bitis = bitis
        self._hareketler: dict[int, list[_Hareket]] | None = None
        self._hareketli: dict[int, tuple[list, list, list]] = {}
        self._donemsel: dict[int, dict[tuple[int, int], tuple[Decimal | None, str]]] = {}
        self._standart: dict[int, list[tuple[date, Decimal]]] | None = None
        self._alislar: dict[int, tuple[list[date], list[_Hareket]]] = {}
        self._iade_kaynak: dict[tuple[str, int], tuple[str, ...]] | None = None

    # ------------------------------------------------------------------ veri
    def _yukle(self) -> dict[int, list[_Hareket]]:
        if self._hareketler is None:
            q = select(StokHareketi.id, StokHareketi.stok_id, StokHareketi.tarih, StokHareketi.hareket_turu,
                       StokHareketi.belge_no, StokHareketi.miktar, StokHareketi.birim_maliyet)
            if self.bitis is not None:
                q = q.where(StokHareketi.tarih <= self.bitis)
            out: dict[int, list[_Hareket]] = {}
            for hid, sid, tarih, ht, belge, m, b in self.session.execute(
                    q.order_by(StokHareketi.stok_id, StokHareketi.tarih, StokHareketi.id)).all():
                tur = _tur(ht)
                if tur is None or tur == "transfer":
                    continue
                if isinstance(tarih, datetime):
                    tarih = tarih.date()
                out.setdefault(int(sid), []).append(
                    _Hareket(int(hid), tarih, tur, ht or "", belge or "", _d(m), _d(b)))
            self._hareketler = out
        return self._hareketler

    def _hareketli_cizelge(self, stok_id: int):
        """Her hareket için (tarih, id) anahtarı, hareket öncesi ve sonrası (ortalama, maliyetsiz pay) listeleri."""
        if stok_id not in self._hareketli:
            anahtar, once, sonra = [], [], []
            belge_idx: dict[tuple[str, str], int] = {}
            kaynaklar = self._iade_kaynaklari()
            q = v = q0 = SIFIR
            for i, h in enumerate(self._yukle().get(stok_id, [])):
                belge_idx.setdefault((h.tur, h.belge_no), i)
                durum = ((v / q) if q > 0 else None, (q0 / q) if q > 0 else SIFIR)
                anahtar.append((h.tarih, h.id))
                once.append(durum)
                ort = durum[0]
                if h.tur == "iade":
                    # Bağlı iade, orijinal satış çıkışının ortalamasıyla havuza döner.
                    cikis = [belge_idx[("cikis", n)] for n in kaynaklar.get((h.belge_no, stok_id), ())
                             if ("cikis", n) in belge_idx]
                    if cikis and once[min(cikis)][0] is not None:
                        ort = once[min(cikis)][0]
                if h.tur == "giris":
                    if q <= 0:
                        q = v = q0 = SIFIR
                    q += h.miktar
                    v += h.miktar * h.maliyet
                    if h.maliyet <= 0:
                        q0 += h.miktar
                elif h.tur == "iade":
                    if q <= 0:
                        q = v = q0 = SIFIR
                    birim = ort if ort is not None else h.maliyet
                    q += h.miktar
                    v += h.miktar * birim
                    if birim <= 0:
                        q0 += h.miktar
                else:
                    if q > 0:
                        oran = min(h.miktar / q, Decimal("1"))
                        v -= v * oran
                        q0 -= q0 * oran
                    q -= h.miktar
                    if q <= 0:
                        q = v = q0 = SIFIR
                sonra.append(((v / q) if q > 0 else None, (q0 / q) if q > 0 else SIFIR))
            self._hareketli[stok_id] = (anahtar, once, sonra, belge_idx)
        return self._hareketli[stok_id]

    def _iade_kaynaklari(self) -> dict[tuple[str, int], tuple[str, ...]]:
        """(iade no, stok id) → orijinal satış satırının stok çıkış belge numaraları."""
        if self._iade_kaynak is None:
            from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
            from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri

            kodlar = {k: int(i) for i, k in self.session.execute(select(StokKarti.id, StokKarti.stok_kodu)).all()}
            out: dict[tuple[str, int], tuple[str, ...]] = {}
            for iade_no, kod, fs_id in self.session.execute(
                    select(SatisIadeFaturasi.iade_no, SatisIadeFaturasiSatiri.urun_kodu,
                           SatisIadeFaturasiSatiri.kaynak_fatura_satiri_id)
                    .join(SatisIadeFaturasi, SatisIadeFaturasi.id == SatisIadeFaturasiSatiri.iade_id)
                    .where(SatisIadeFaturasiSatiri.kaynak_fatura_satiri_id.is_not(None))).all():
                sid = kodlar.get((kod or "").strip())
                if sid is None or (iade_no, sid) in out:
                    continue
                satir = self.session.get(SatisFaturasiSatiri, int(fs_id))
                fatura = self.session.get(SatisFaturasi, int(satir.fatura_id)) if satir is not None else None
                if fatura is not None:
                    out[(iade_no, sid)] = satis_belge_nolari(self.session, fatura, satir)
            self._iade_kaynak = out
        return self._iade_kaynak

    def _donemsel_cizelge(self, stok_id: int) -> dict[tuple[int, int], tuple[Decimal | None, str]]:
        if stok_id not in self._donemsel:
            aylar: dict[tuple[int, int], list[_Hareket]] = {}
            for h in self._yukle().get(stok_id, []):
                aylar.setdefault((h.tarih.year, h.tarih.month), []).append(h)
            out: dict[tuple[int, int], tuple[Decimal | None, str]] = {}
            if aylar:
                y, m = min(aylar)
                son = max(aylar)
                if self.bitis is not None:
                    son = max(son, (self.bitis.year, self.bitis.month))
                aq = av = aq0 = SIFIR
                while (y, m) <= son:
                    hs = aylar.get((y, m), [])
                    gq = sum((h.miktar for h in hs if h.tur == "giris"), SIFIR)
                    gv = sum((h.miktar * h.maliyet for h in hs if h.tur == "giris"), SIFIR)
                    gq0 = sum((h.miktar for h in hs if h.tur == "giris" and h.maliyet <= 0), SIFIR)
                    tq = aq + gq
                    ort = (av + gv) / tq if tq > 0 else None
                    q0_oran = (aq0 + gq0) / tq if tq > 0 else SIFIR
                    out[(y, m)] = (ort, "" if q0_oran <= _SIFIR_ESIK else "maliyetsiz giriş")
                    cikis = sum((h.miktar for h in hs if h.tur == "cikis"), SIFIR)
                    iade = sum((h.miktar for h in hs if h.tur == "iade"), SIFIR)
                    kq = tq - cikis + iade
                    if kq <= 0 or ort is None:
                        aq = av = aq0 = SIFIR
                    else:
                        aq, av, aq0 = kq, kq * ort, kq * q0_oran
                    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            self._donemsel[stok_id] = out
        return self._donemsel[stok_id]

    def _standartlar(self) -> dict[int, list[tuple[date, Decimal]]]:
        if self._standart is None:
            out: dict[int, list[tuple[date, Decimal]]] = {}
            if standart_tablo_var(self.session):
                for sid, t, b in self.session.execute(
                        select(StokStandartMaliyet.stok_id, StokStandartMaliyet.gecerlilik_tarihi,
                               StokStandartMaliyet.birim_maliyet)
                        .order_by(StokStandartMaliyet.stok_id, StokStandartMaliyet.gecerlilik_tarihi)).all():
                    out.setdefault(int(sid), []).append((t, _d(b)))
            self._standart = out
        return self._standart

    # ------------------------------------------------------------------ yöntemler
    def birim_maliyet(self, yontem: str, stok: StokKarti | None, tarih: date,
                      belge_nolari: Iterable[str] = (), giris: bool = False) -> tuple[Decimal | None, str]:
        """Satış (veya ``giris=True`` ile kaynaksız iade) anındaki temel birim maliyeti ve kaynak açıklaması."""
        if stok is None:
            return None, "Eksik: stok kartı yok"
        sid = int(stok.id)
        nolar = {n for n in belge_nolari if n}
        if yontem == HAREKETLI:
            return self._hareketli_maliyet(sid, tarih, nolar, giris)
        if yontem == DONEMSEL:
            ort, uyari = self._donemsel_cizelge(sid).get((tarih.year, tarih.month), (None, ""))
            if ort is None or ort <= 0:
                return None, f"Eksik: {tarih:%m.%Y} ayında açılış stoku ve girişi yok"
            if uyari:
                return None, f"Eksik: {tarih:%m.%Y} ortalamasına maliyetsiz giriş karıştı"
            return ort.quantize(DORT), f"{tarih:%m.%Y} dönemsel ağırlıklı ortalama"
        if yontem == SON_ALIS:
            if sid not in self._alislar:
                liste = [h for h in self._yukle().get(sid, []) if h.hareket_turu in _ALIS_GIRIS and h.maliyet > 0]
                self._alislar[sid] = ([h.tarih for h in liste], liste)
            tarihler, alislar = self._alislar[sid]
            i = bisect_right(tarihler, tarih)
            if i == 0:
                return None, "Eksik: satış tarihine kadar maliyetli alış yok"
            h = alislar[i - 1]
            return h.maliyet, f"son alış {h.tarih:%d.%m.%Y} {h.belge_no}"
        if yontem == STANDART:
            liste = self._standartlar().get(sid, [])
            i = bisect_right([t for t, _b in liste], tarih)
            if i == 0:
                return None, "Eksik: satış tarihinde geçerli standart maliyet tanımı yok"
            t, b = liste[i - 1]
            if b <= 0:
                return None, "Eksik: standart maliyet 0"
            return b, f"standart maliyet ({t:%d.%m.%Y} itibarıyla)"
        raise ValueError(f"Desteklenmeyen maliyet yöntemi: {yontem}")

    def _hareketli_maliyet(self, sid: int, tarih: date, nolar: set[str], giris: bool):
        anahtar, once, sonra, belge_idx = self._hareketli_cizelge(sid)
        hs = self._yukle().get(sid, [])
        tur = "iade" if giris else "cikis"
        adaylar = [belge_idx[(tur, n)] for n in nolar if (tur, n) in belge_idx]
        idx = min(adaylar) if adaylar else None
        if idx is not None:
            ort, q0 = once[idx]
            kaynak = f"hareketli ortalama ({hs[idx].tarih:%d.%m.%Y} {hs[idx].belge_no} öncesi)"
        else:
            i = bisect_right(anahtar, (tarih, 10 ** 12))
            ort, q0 = sonra[i - 1] if i else (None, SIFIR)
            kaynak = f"hareketli ortalama ({tarih:%d.%m.%Y} gün sonu; belgeye bağlı stok hareketi yok)"
        if ort is None or ort <= 0:
            return None, "Eksik: o tarihte maliyetli stok yok"
        if q0 > _SIFIR_ESIK:
            return None, "Eksik: ortalamaya maliyetsiz giriş karıştı"
        return ort.quantize(DORT), kaynak


# ---------------------------------------------------------------------------
# Standart maliyet tanımları
# ---------------------------------------------------------------------------

def _standart_tablo_hazirla(session) -> None:
    StokStandartMaliyet.__table__.create(bind=session.connection(), checkfirst=True)


def standart_maliyetler(stok_kodu: str = "") -> list[dict[str, Any]]:
    from database.access import maliyet_zorunlu
    from database.database import get_session

    maliyet_zorunlu()
    with get_session() as s:
        if not standart_tablo_var(s):
            return []
        q = (select(StokStandartMaliyet, StokKarti)
             .join(StokKarti, StokKarti.id == StokStandartMaliyet.stok_id)
             .order_by(StokKarti.stok_kodu, StokStandartMaliyet.gecerlilik_tarihi.desc()))
        if stok_kodu:
            q = q.where(StokKarti.stok_kodu == stok_kodu.strip())
        return [{"id": int(m.id), "stok_kodu": k.stok_kodu, "stok_adi": k.stok_adi, "birim": k.birim,
                 "gecerlilik_tarihi": m.gecerlilik_tarihi, "birim_maliyet": _d(m.birim_maliyet),
                 "aciklama": m.aciklama or "", "olusturan": m.olusturan or ""}
                for m, k in s.execute(q).all()]


def standart_maliyet_kaydet(stok_kodu: str, gecerlilik_tarihi: date, birim_maliyet, aciklama: str = "") -> int:
    from database.access import maliyet_zorunlu, yazma_zorunlu
    from database.database import get_session
    from database.session_manager import oturum

    yazma_zorunlu("stok_duzenleme", "yeni_kayit")
    maliyet_zorunlu()
    try:
        tutar = _d(birim_maliyet)
    except ArithmeticError as hata:
        raise ValueError("Birim maliyet sayı olmalı.") from hata
    if tutar <= 0:
        raise ValueError("Standart maliyet sıfırdan büyük olmalı.")
    if not isinstance(gecerlilik_tarihi, date):
        raise ValueError("Geçerlilik tarihi gerekli.")
    with get_session() as s:
        stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == (stok_kodu or "").strip()))
        if stok is None:
            raise ValueError("Stok kartı bulunamadı.")
        _standart_tablo_hazirla(s)
        kayit = s.scalar(select(StokStandartMaliyet).where(
            StokStandartMaliyet.stok_id == stok.id, StokStandartMaliyet.gecerlilik_tarihi == gecerlilik_tarihi))
        if kayit is None:
            kayit = StokStandartMaliyet(stok_id=stok.id, gecerlilik_tarihi=gecerlilik_tarihi)
            s.add(kayit)
        kayit.birim_maliyet = tutar.quantize(DORT)
        kayit.aciklama = (aciklama or "").strip()[:200] or None
        kayit.olusturan = getattr(oturum, "kullanici_adi", None)
        s.flush()
        return int(kayit.id)


def standart_maliyet_sil(kayit_id: int) -> None:
    from database.access import maliyet_zorunlu, yazma_zorunlu
    from database.database import get_session

    yazma_zorunlu("stok_duzenleme", "yeni_kayit")
    maliyet_zorunlu()
    with get_session() as s:
        if not standart_tablo_var(s):
            return
        kayit = s.get(StokStandartMaliyet, int(kayit_id))
        if kayit is not None:
            s.delete(kayit)
