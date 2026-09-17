"""Aylara Göre Ödeme Durumu — kaynak belgeleri çoğaltmadan birleştiren rapor servisi.

Kaynaklar:
- Banka kredi taksitleri (BankaKrediService)
- Kredi kartı ekstre borçları (KrediKartiEkstreService — kesim/son ödeme gününe göre)
- Verilen (ödenecek) çek / senet (CekSenetService)

Aynı borç ikinci kez üretilmez; KK satırları ekstre anahtarı (kart + kesim tarihi) ile tekildir.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from database.access import yetki_var
from database.session_manager import oturum

SIFIR = Decimal("0.00")
KURUS = Decimal("0.01")
YAKLASAN_GUN = 7

KAYNAK_KREDI = "KREDI_TAKSIT"
KAYNAK_KK = "KREDI_KARTI_EKSTRE"  # ekstre ana satırı (eski: KREDI_KARTI_TAKSIT)
KAYNAK_KK_TAKSIT_ESKI = "KREDI_KARTI_TAKSIT"  # geriye uyumluluk
KAYNAK_CEK = "CEK_SENET"

DURUM_PLANLANDI = "PLANLANDI"
DURUM_YAKLASIYOR = "YAKLASIYOR"
DURUM_BUGUN = "BUGUN"
DURUM_GECIKMIS = "GECIKMIS"
DURUM_KISMI = "KISMEN_ODENDI"
DURUM_ODENDI = "ODENDI"
DURUM_IPTAL = "IPTAL"


def _d(deger, minimum=None) -> Decimal:
    tutar = Decimal(str(deger or 0)).quantize(KURUS, rounding=ROUND_HALF_UP)
    if minimum is not None and tutar < minimum:
        return Decimal(str(minimum)).quantize(KURUS, rounding=ROUND_HALF_UP)
    return tutar


def _ay_basi(yil: int, ay: int) -> date:
    return date(yil, ay, 1)


def _ay_sonu(yil: int, ay: int) -> date:
    return date(yil, ay, calendar.monthrange(yil, ay)[1])


def _ay_ekle(bas: date, n: int) -> date:
    y = bas.year + (bas.month - 1 + n) // 12
    a = (bas.month - 1 + n) % 12 + 1
    return date(y, a, 1)


def _durum_hesapla(
    vade: date | None,
    kalan: Decimal,
    odenen: Decimal,
    mevcut=None,
    *,
    bugun: date | None = None,
) -> str:
    if (mevcut or "").upper() in (DURUM_IPTAL, "IPTAL", "IPTAL_EDILDI"):
        return DURUM_IPTAL
    if kalan <= 0 and odenen > 0:
        return DURUM_ODENDI
    if odenen > 0 and kalan > 0:
        return DURUM_KISMI
    if not vade:
        return DURUM_PLANLANDI
    bugun = bugun or date.today()
    if vade < bugun and kalan > 0:
        return DURUM_GECIKMIS
    if vade == bugun:
        return DURUM_BUGUN
    if bugun < vade <= bugun + timedelta(days=YAKLASAN_GUN):
        return DURUM_YAKLASIYOR
    return DURUM_PLANLANDI


AY_ADLARI_TR = (
    "",
    "OCAK",
    "ŞUBAT",
    "MART",
    "NİSAN",
    "MAYIS",
    "HAZİRAN",
    "TEMMUZ",
    "AĞUSTOS",
    "EYLÜL",
    "EKİM",
    "KASIM",
    "ARALIK",
)

# Beş aylık pencere: -1 (geçen) + 0 (bu ay) + 1..3 (gelecek)
BES_AYLIK_OFFSETLER = (-1, 0, 1, 2, 3)
ROL_GECEN = "GECEN"
ROL_BU_AY = "BU_AY"
ROL_GELECEK = "GELECEK"


class OdemeDurumuService:
    """Ödeme takvimi — mevcut kayıtları okur, yeni borç üretmez."""

    @staticmethod
    def yetki_kontrol() -> None:
        if not (
            yetki_var("odeme_durumu_goruntuleme")
            or yetki_var("finans_goruntuleme")
            or yetki_var("banka_kredi_rapor")
        ):
            raise PermissionError("Ödeme durumu raporunu görüntüleme yetkiniz yok.")

    @staticmethod
    def obligation_key(source_type: str, source_id, due_date: date | None) -> str:
        vade = due_date.isoformat() if due_date else ""
        return f"{source_type}:{source_id}:{vade}"

    @staticmethod
    def _kredi_satirlari(odenenleri_dahil: bool = False) -> list[dict]:
        from database.banka_kredi_service import BankaKrediService

        BankaKrediService.schema_hazirla()
        satirlar: list[dict] = []
        for t in BankaKrediService.bekleyen_taksitler(limit=5000):
            vade = t.get("vade_tarihi")
            toplam = _d(t.get("toplam") or t.get("kalan") or 0)
            odenen = _d(t.get("odenen_tutar") or 0)
            kalan = _d(t.get("kalan") if t.get("kalan") is not None else (toplam - odenen))
            if kalan < 0:
                kalan = SIFIR
            sid = t.get("taksit_id") or t.get("id")
            satirlar.append({
                "obligation_key": OdemeDurumuService.obligation_key(KAYNAK_KREDI, sid, vade),
                "source_type": KAYNAK_KREDI,
                "source_id": sid,
                "kredi_id": t.get("kredi_id"),
                "due_date": vade,
                "payment_month": (vade.year, vade.month) if vade else None,
                "aciklama": f"{t.get('kredi_adi') or 'Kredi'} — {t.get('taksit_no')}. taksit",
                "kaynak_etiket": "Banka kredisi",
                "banka_adi": t.get("banka_adi") or "",
                "belge_no": t.get("belge_no") or t.get("odeme_belge_no") or "",
                "kategori": "Kredi taksiti",
                "para_birimi": t.get("para_birimi") or "TRY",
                "orijinal_tutar": toplam,
                "tl_tutar": toplam,
                "odenen": odenen,
                "kalan": kalan,
                "anapara": _d(t.get("anapara") or 0),
                "faiz": _d(t.get("faiz") or 0),
                "masraf": _d(
                    Decimal(str(t.get("bsmv") or 0))
                    + Decimal(str(t.get("kkdf") or 0))
                    + Decimal(str(t.get("komisyon") or 0))
                    + Decimal(str(t.get("sigorta") or 0))
                    + Decimal(str(t.get("dosya_masrafi") or 0))
                    + Decimal(str(t.get("diger_masraflar") or 0))
                    + Decimal(str(t.get("masraf") or 0))
                    + Decimal(str(t.get("gecikme_faizi") or 0))
                ),
                "certainty": "KESIN",
                "oncelik": "YUKSEK",
                "durum": _durum_hesapla(vade, kalan, odenen, t.get("durum")),
            })
        if odenenleri_dahil:
            for t in BankaKrediService.odenen_taksitler(limit=2000):
                vade = t.get("vade_tarihi") or t.get("odeme_tarihi")
                toplam = _d(t.get("toplam") or t.get("odenen_tutar") or 0)
                sid = t.get("taksit_id") or t.get("id")
                satirlar.append({
                    "obligation_key": OdemeDurumuService.obligation_key(KAYNAK_KREDI, sid, vade),
                    "source_type": KAYNAK_KREDI,
                    "source_id": sid,
                    "kredi_id": t.get("kredi_id"),
                    "due_date": vade,
                    "payment_month": (vade.year, vade.month) if vade else None,
                    "aciklama": f"{t.get('kredi_adi') or 'Kredi'} — {t.get('taksit_no')}. taksit (ödendi)",
                    "kaynak_etiket": "Banka kredisi",
                    "banka_adi": t.get("banka_adi") or "",
                    "belge_no": t.get("odeme_belge_no") or t.get("belge_no") or "",
                    "kategori": "Kredi taksiti",
                    "para_birimi": "TRY",
                    "orijinal_tutar": toplam,
                    "tl_tutar": toplam,
                    "odenen": toplam,
                    "kalan": SIFIR,
                    "anapara": _d(t.get("anapara") or 0),
                    "faiz": _d(t.get("faiz") or 0),
                    "masraf": SIFIR,
                    "certainty": "KESIN",
                    "oncelik": "NORMAL",
                    "durum": DURUM_ODENDI,
                })
        return satirlar

    @staticmethod
    def _kk_satirlari(*, odenenleri_dahil: bool = False, bugun: date | None = None) -> list[dict]:
        """Kredi kartı: tek tek taksit değil — ekstre ana satırları (son ödeme tarihinde)."""
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        satirlar: list[dict] = []
        try:
            KrediKartiEkstreService.schema_hazirla()
            ekstreler = KrediKartiEkstreService.ekstreleri_hesapla(
                bugun=bugun,
                odenenleri_dahil=odenenleri_dahil,
            )
        except Exception:
            return satirlar
        for e in ekstreler:
            kalan = _d(e.get("kalan") or 0)
            odenen = _d(e.get("odenen") or 0)
            if not odenenleri_dahil and kalan <= 0:
                continue
            vade = e.get("due_date") or e.get("son_odeme_tarihi")
            if not vade:
                continue
            satirlar.append({
                "obligation_key": e.get("obligation_key")
                or OdemeDurumuService.obligation_key(KAYNAK_KK, e.get("source_id"), vade),
                "source_type": KAYNAK_KK,
                "source_id": e.get("source_id"),
                "ekstre_id": e.get("ekstre_id"),
                "kredi_id": None,
                "kredi_karti_id": e.get("kredi_karti_id"),
                "due_date": vade,
                "payment_month": e.get("payment_month") or (vade.year, vade.month),
                "aciklama": e.get("aciklama") or "",
                "kaynak_etiket": e.get("kaynak_etiket") or "Kredi Kartı Ekstresi",
                "banka_adi": e.get("banka_adi") or "",
                "kart_adi": e.get("kart_adi") or "",
                "son_dort_hane": e.get("son_dort_hane") or "",
                "belge_no": e.get("belge_no") or "",
                "kategori": "Kredi kartı ekstresi",
                "para_birimi": e.get("para_birimi") or "TRY",
                "orijinal_tutar": _d(e.get("tl_tutar") or e.get("orijinal_tutar")),
                "tl_tutar": _d(e.get("tl_tutar")),
                "odenen": odenen,
                "kalan": kalan,
                "anapara": SIFIR,
                "faiz": SIFIR,
                "masraf": SIFIR,
                "certainty": e.get("certainty") or "KESIN",
                "oncelik": "YUKSEK",
                "durum": e.get("durum") or _durum_hesapla(vade, kalan, odenen, bugun=bugun),
                "ekstre_durum": e.get("ekstre_durum"),
                "kesin": e.get("kesin", True),
                "kesim_tarihi": e.get("kesim_tarihi"),
                "donem_baslangic": e.get("donem_baslangic"),
                "donem_bitis": e.get("donem_bitis"),
                "detay_satirlari": e.get("detay_satirlari") or [],
            })
        return satirlar

    @staticmethod
    def _cek_satirlari() -> list[dict]:
        from database.cek_senet_service import CekSenetService
        from database.models.cek_senet import ISLEM_YONU_VERILEN

        satirlar: list[dict] = []
        try:
            CekSenetService.schema_hazirla()
            kayitlar = CekSenetService.rapor_portfoy_dokumu(ISLEM_YONU_VERILEN)
        except Exception:
            return satirlar
        for e in kayitlar:
            vade = e.get("vade_tarihi")
            kalan = _d(e.get("kalan_tutar") if e.get("kalan_tutar") is not None else e.get("tl_tutari") or 0)
            if kalan <= 0 or not vade:
                continue
            sid = e.get("id") or e.get("portfoy_no")
            tur = e.get("evrak_turu_etiket") or e.get("basit_tur") or "Çek/Senet"
            satirlar.append({
                "obligation_key": OdemeDurumuService.obligation_key(KAYNAK_CEK, sid, vade),
                "source_type": KAYNAK_CEK,
                "source_id": sid,
                "kredi_id": None,
                "due_date": vade,
                "payment_month": (vade.year, vade.month),
                "aciklama": f"{tur} {e.get('evrak_no') or e.get('portfoy_no') or ''} — {e.get('cari_adi') or ''}".strip(),
                "kaynak_etiket": "Çek / Senet",
                "banka_adi": e.get("banka_adi") or e.get("banka") or "",
                "belge_no": e.get("portfoy_no") or e.get("evrak_no") or "",
                "kategori": tur,
                "para_birimi": e.get("doviz_turu") or "TRY",
                "orijinal_tutar": _d(e.get("doviz_tutari") or e.get("tl_tutari") or kalan),
                "tl_tutar": _d(e.get("tl_tutari") or kalan),
                "odenen": _d(e.get("tahsil_edilen") or 0),
                "kalan": kalan,
                "anapara": SIFIR,
                "faiz": SIFIR,
                "masraf": SIFIR,
                "certainty": "KESIN",
                "oncelik": "NORMAL",
                "durum": _durum_hesapla(vade, kalan, _d(e.get("tahsil_edilen") or 0), e.get("durum")),
            })
        return satirlar

    @staticmethod
    def tum_yukumlulukler(
        *,
        kaynaklar: set[str] | None = None,
        odenenleri_dahil: bool = False,
        sadece_acik: bool = True,
        bugun: date | None = None,
    ) -> list[dict]:
        OdemeDurumuService.yetki_kontrol()
        if not oturum.firma_secili:
            raise ValueError("Aktif firma seçilmedi.")

        bugun = bugun or OdemeDurumuService.referans_tarih()
        kaynaklar = kaynaklar or {KAYNAK_KREDI, KAYNAK_KK, KAYNAK_CEK}
        birlesik: dict[str, dict] = {}

        if KAYNAK_KREDI in kaynaklar:
            for s in OdemeDurumuService._kredi_satirlari(odenenleri_dahil=odenenleri_dahil):
                s["durum"] = _durum_hesapla(
                    s.get("due_date"),
                    _d(s.get("kalan")),
                    _d(s.get("odenen")),
                    s.get("durum"),
                    bugun=bugun,
                )
                birlesik[s["obligation_key"]] = s
        if KAYNAK_KK in kaynaklar or KAYNAK_KK_TAKSIT_ESKI in kaynaklar:
            for s in OdemeDurumuService._kk_satirlari(
                odenenleri_dahil=odenenleri_dahil, bugun=bugun
            ):
                s["durum"] = _durum_hesapla(
                    s.get("due_date"),
                    _d(s.get("kalan")),
                    _d(s.get("odenen")),
                    s.get("durum"),
                    bugun=bugun,
                )
                birlesik.setdefault(s["obligation_key"], s)
        if KAYNAK_CEK in kaynaklar:
            for s in OdemeDurumuService._cek_satirlari():
                s["durum"] = _durum_hesapla(
                    s.get("due_date"),
                    _d(s.get("kalan")),
                    _d(s.get("odenen")),
                    s.get("durum"),
                    bugun=bugun,
                )
                birlesik.setdefault(s["obligation_key"], s)

        sonuc = list(birlesik.values())
        if sadece_acik:
            sonuc = [
                s
                for s in sonuc
                if s["durum"] not in (DURUM_ODENDI, DURUM_IPTAL) and s["kalan"] > 0
            ]

        def _sirala(s):
            v = s.get("due_date") or date.max
            return (v, -(s.get("kalan") or SIFIR), s.get("aciklama") or "")

        sonuc.sort(key=_sirala)
        return sonuc

    @staticmethod
    def referans_tarih() -> date:
        """Raporun tek tarih kaynağı — uygulama günü."""
        return date.today()

    @staticmethod
    def bes_aylik_pencere(referans: date | None = None) -> list[dict]:
        """Her zaman 5 ay: geçen + bu ay + gelecek 3 ay (takvim ayı hesabı).

        Dönüş: [{yil, ay, offset, rol, etiket, baslik, bas, son}, ...]
        """
        bugun = referans or OdemeDurumuService.referans_tarih()
        bu_ay_basi = date(bugun.year, bugun.month, 1)
        sonuc = []
        for offset in BES_AYLIK_OFFSETLER:
            bas = _ay_ekle(bu_ay_basi, offset)
            yil, ay = bas.year, bas.month
            if offset < 0:
                rol = ROL_GECEN
                etiket = "Geçen Ay"
            elif offset == 0:
                rol = ROL_BU_AY
                etiket = "Bu Ay"
            else:
                rol = ROL_GELECEK
                etiket = "Gelecek Dönem"
            sonuc.append({
                "yil": yil,
                "ay": ay,
                "offset": offset,
                "rol": rol,
                "etiket": etiket,
                "baslik": f"{AY_ADLARI_TR[ay]} {yil}",
                "bas": _ay_basi(yil, ay),
                "son": _ay_sonu(yil, ay),
            })
        return sonuc

    @staticmethod
    def ay_listesi(baslangic: date | None = None, ay_sayisi: int = 5) -> list[tuple[int, int]]:
        """Geriye uyumluluk — varsayılan beş aylık pencere."""
        if baslangic is None and ay_sayisi == 5:
            return [(m["yil"], m["ay"]) for m in OdemeDurumuService.bes_aylik_pencere()]
        bas = baslangic or date.today().replace(day=1)
        return [(_ay_ekle(bas, i).year, _ay_ekle(bas, i).month) for i in range(ay_sayisi)]

    @staticmethod
    def ay_etiket(yil: int, ay: int) -> str:
        return f"{AY_ADLARI_TR[ay]} {yil}"

    @staticmethod
    def ay_satirlari(yil: int, ay: int, **kwargs) -> list[dict]:
        bas, son = _ay_basi(yil, ay), _ay_sonu(yil, ay)
        return [
            s
            for s in OdemeDurumuService.tum_yukumlulukler(**kwargs)
            if s.get("due_date") and bas <= s["due_date"] <= son
        ]

    @staticmethod
    def _filtrele_satirlar(
        satirlar: list[dict],
        *,
        durumlar: set[str] | None = None,
        sadece_geciken: bool = False,
        sadece_acik: bool = False,
        min_tutar: Decimal | None = None,
        max_tutar: Decimal | None = None,
        banka: str | None = None,
    ) -> list[dict]:
        sonuc = []
        banka_f = (banka or "").strip().casefold()
        for s in satirlar:
            durum = s.get("durum") or ""
            if sadece_geciken and durum != DURUM_GECIKMIS:
                continue
            if sadece_acik and (
                durum in (DURUM_ODENDI, DURUM_IPTAL) or _d(s.get("kalan")) <= 0
            ):
                continue
            if durumlar and durum not in durumlar:
                continue
            kalan = _d(s.get("kalan") if s.get("kalan") is not None else s.get("tl_tutar"))
            if min_tutar is not None and kalan < min_tutar:
                continue
            if max_tutar is not None and kalan > max_tutar:
                continue
            if banka_f and banka_f not in (s.get("banka_adi") or "").casefold():
                continue
            sonuc.append(s)
        return sonuc

    @staticmethod
    def ay_ozeti(
        yil: int,
        ay: int,
        satirlar: list[dict] | None = None,
        *,
        rol: str | None = None,
        etiket: str | None = None,
        baslik: str | None = None,
        bugun: date | None = None,
    ) -> dict:
        satirlar = (
            list(satirlar)
            if satirlar is not None
            else OdemeDurumuService.ay_satirlari(yil, ay)
        )
        bugun = bugun or OdemeDurumuService.referans_tarih()
        for s in satirlar:
            if s.get("due_date"):
                s["kalan_gun"] = (s["due_date"] - bugun).days

        acik = [
            s
            for s in satirlar
            if s.get("durum") not in (DURUM_ODENDI, DURUM_IPTAL) and _d(s.get("kalan")) > 0
        ]
        odenenler = [s for s in satirlar if s.get("durum") == DURUM_ODENDI]

        def _kaynak_toplam(kod: str) -> Decimal:
            return sum(
                (_d(s.get("kalan")) for s in acik if s.get("source_type") == kod),
                SIFIR,
            )

        toplam_plan = sum((_d(s.get("tl_tutar")) for s in satirlar), SIFIR)
        odenen_toplam = sum((_d(s.get("odenen")) for s in satirlar), SIFIR)
        # Ödenen kayıtların tam tutarını da ödenen toplamına ekle
        for s in odenenler:
            if _d(s.get("odenen")) <= 0:
                odenen_toplam += _d(s.get("tl_tutar"))
        kalan = sum((_d(s.get("kalan")) for s in acik), SIFIR)
        gecikmis = sum(
            (_d(s.get("kalan")) for s in acik if s.get("durum") == DURUM_GECIKMIS),
            SIFIR,
        )
        diger_kodlar = {KAYNAK_KREDI, KAYNAK_KK}
        diger = sum(
            (
                _d(s.get("kalan"))
                for s in acik
                if s.get("source_type") not in diger_kodlar
            ),
            SIFIR,
        )
        return {
            "yil": yil,
            "ay": ay,
            "rol": rol,
            "etiket": etiket or "",
            "baslik": baslik or OdemeDurumuService.ay_etiket(yil, ay),
            "etiket_uzun": OdemeDurumuService.ay_etiket(yil, ay),
            "toplam": toplam_plan,
            "kalan": kalan,
            "odenen": odenen_toplam,
            "gecikmis": gecikmis,
            "yaklasan": sum(
                (
                    _d(s.get("kalan"))
                    for s in acik
                    if s.get("durum") in (DURUM_YAKLASIYOR, DURUM_BUGUN)
                ),
                SIFIR,
            ),
            "kredi_karti_toplam": _kaynak_toplam(KAYNAK_KK),
            "kredi_taksit_toplam": _kaynak_toplam(KAYNAK_KREDI),
            "tekrar_eden_toplam": SIFIR,  # henüz kaynak yok
            "diger_toplam": diger,
            "adet": len(acik),
            "odenen_adet": len(odenenler),
            "bos": len(acik) == 0 and len(odenenler) == 0,
            "acik_satirlar": acik,
            "odenen_satirlar": odenenler,
            "tum_satirlar": satirlar,
        }

    @staticmethod
    def bes_aylik_rapor(
        *,
        referans: date | None = None,
        kaynaklar: set[str] | None = None,
        odenenleri_dahil: bool = False,
        sadece_acik: bool = True,
        sadece_geciken: bool = False,
        durumlar: set[str] | None = None,
        min_tutar: Decimal | None = None,
        max_tutar: Decimal | None = None,
        banka: str | None = None,
    ) -> dict[str, Any]:
        """Beş aylık dinamik görünüm — boş aylar dahil her zaman 5 kart."""
        bugun = referans or OdemeDurumuService.referans_tarih()
        pencere = OdemeDurumuService.bes_aylik_pencere(bugun)
        bas = pencere[0]["bas"]
        son = pencere[-1]["son"]

        # Dönem içi açık + (isteğe bağlı) ödenen; filtre ay kartlarını silmez
        tum = OdemeDurumuService.tum_yukumlulukler(
            kaynaklar=kaynaklar,
            odenenleri_dahil=True,  # dönem özeti için ödenenleri de al
            sadece_acik=False,
            bugun=bugun,
        )
        donem_tum = [
            s for s in tum if s.get("due_date") and bas <= s["due_date"] <= son
        ]

        aylar = []
        for m in pencere:
            ham = [
                s
                for s in donem_tum
                if s.get("due_date") and m["bas"] <= s["due_date"] <= m["son"]
            ]
            # Görünen liste: açık / ödenen ayrımı
            if odenenleri_dahil:
                gorunen = list(ham)
            elif sadece_acik:
                gorunen = [
                    s
                    for s in ham
                    if s.get("durum") not in (DURUM_ODENDI, DURUM_IPTAL)
                    and _d(s.get("kalan")) > 0
                ]
            else:
                gorunen = list(ham)

            gorunen = OdemeDurumuService._filtrele_satirlar(
                gorunen,
                durumlar=durumlar,
                sadece_geciken=sadece_geciken,
                sadece_acik=False,
                min_tutar=min_tutar,
                max_tutar=max_tutar,
                banka=banka,
            )
            ozet = OdemeDurumuService.ay_ozeti(
                m["yil"],
                m["ay"],
                ham,
                rol=m["rol"],
                etiket=m["etiket"],
                baslik=m["baslik"],
                bugun=bugun,
            )
            # Kartta gösterilecek satırlar filtreye göre
            if odenenleri_dahil:
                ozet["gorunen_satirlar"] = gorunen
            else:
                ozet["gorunen_satirlar"] = [
                    s
                    for s in gorunen
                    if s.get("durum") not in (DURUM_ODENDI, DURUM_IPTAL)
                ]
            # Filtre sonrası boş görünüm bayrağı (ay kartı yine durur)
            ozet["gorunen_bos"] = len(ozet["gorunen_satirlar"]) == 0
            # Filtre uygulanmış kalan/toplam gösterimi
            ozet["filtre_kalan"] = sum(
                (_d(s.get("kalan")) for s in ozet["gorunen_satirlar"]), SIFIR
            )
            ozet["filtre_adet"] = len(ozet["gorunen_satirlar"])
            aylar.append(ozet)

        acik_donem = [
            s
            for s in donem_tum
            if s.get("durum") not in (DURUM_ODENDI, DURUM_IPTAL) and _d(s.get("kalan")) > 0
        ]
        gelecek_uc = [
            s
            for s in acik_donem
            if s.get("due_date")
            and s["due_date"] > _ay_sonu(bugun.year, bugun.month)
        ]
        return {
            "referans": bugun,
            "pencere_bas": bas,
            "pencere_son": son,
            "aylar": aylar,  # her zaman 5
            "donem": {
                "toplam_yukumluluk": sum((_d(s.get("tl_tutar")) for s in donem_tum), SIFIR),
                "toplam_odenen": sum(
                    (
                        _d(s.get("odenen")) or _d(s.get("tl_tutar"))
                        for s in donem_tum
                        if s.get("durum") == DURUM_ODENDI
                    ),
                    SIFIR,
                )
                + sum(
                    (
                        _d(s.get("odenen"))
                        for s in donem_tum
                        if s.get("durum") == DURUM_KISMI
                    ),
                    SIFIR,
                ),
                "toplam_kalan": sum((_d(s.get("kalan")) for s in acik_donem), SIFIR),
                "vadesi_gecmis": sum(
                    (
                        _d(s.get("kalan"))
                        for s in acik_donem
                        if s.get("durum") == DURUM_GECIKMIS
                    ),
                    SIFIR,
                ),
                "gelecek_uc_ay": sum((_d(s.get("kalan")) for s in gelecek_uc), SIFIR),
            },
            "firma": getattr(oturum, "company_name", None)
            or getattr(oturum, "firma_adi", None)
            or "",
            "donem_adi": getattr(oturum, "donem_adi", None) or "",
        }

    @staticmethod
    def kpi(ay_sayisi: int = 5) -> dict[str, Any]:
        """KPI — beş aylık rapor özetinden türetilir."""
        rapor = OdemeDurumuService.bes_aylik_rapor()
        bugun = rapor["referans"]
        bu_ay = next((a for a in rapor["aylar"] if a.get("rol") == ROL_BU_AY), None)
        tum_acik = OdemeDurumuService.tum_yukumlulukler(sadece_acik=True, bugun=bugun)
        gelecek_7 = [
            s
            for s in tum_acik
            if s.get("due_date") and bugun <= s["due_date"] <= bugun + timedelta(days=7)
        ]
        return {
            "bu_ay_toplam": bu_ay["toplam"] if bu_ay else SIFIR,
            "bu_ay_kalan": bu_ay["kalan"] if bu_ay else SIFIR,
            "bu_ay_odenen": bu_ay["odenen"] if bu_ay else SIFIR,
            "gecikmis": rapor["donem"]["vadesi_gecmis"],
            "gelecek_7_gun": sum((_d(s.get("kalan")) for s in gelecek_7), SIFIR),
            "gelecek_30_gun": rapor["donem"]["gelecek_uc_ay"],
            "bes_ay_toplam": rapor["donem"]["toplam_yukumluluk"],
            "bes_ay_kalan": rapor["donem"]["toplam_kalan"],
            "bes_ay_odenen": rapor["donem"]["toplam_odenen"],
            "tahmini": SIFIR,
            "firma": rapor["firma"],
            "donem": rapor["donem_adi"],
            "yenileme": bugun,
            "aylar": rapor["aylar"],
            "donem_ozet": rapor["donem"],
        }
