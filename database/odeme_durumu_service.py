"""Aylara Göre Ödeme Durumu — kaynak belgeleri çoğaltmadan birleştiren rapor servisi.

Kaynaklar (Aşama 1):
- Banka kredi taksitleri (BankaKrediService)
- Kredi kartı cari ödeme taksitleri (FinansService.kredi_karti_bekleyen_taksitler)
- Verilen (ödenecek) çek / senet (CekSenetService)

Aynı borç ikinci kez üretilmez; her satır source_type + source_id + due_date ile tanımlanır.
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
KAYNAK_KK = "KREDI_KARTI_TAKSIT"
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


def _durum_hesapla(vade: date | None, kalan: Decimal, odenen: Decimal, mevcut=None) -> str:
    if (mevcut or "").upper() in (DURUM_IPTAL, "IPTAL", "IPTAL_EDILDI"):
        return DURUM_IPTAL
    if kalan <= 0 and odenen > 0:
        return DURUM_ODENDI
    if odenen > 0 and kalan > 0:
        return DURUM_KISMI
    if not vade:
        return DURUM_PLANLANDI
    bugun = date.today()
    if vade < bugun and kalan > 0:
        return DURUM_GECIKMIS
    if vade == bugun:
        return DURUM_BUGUN
    if bugun < vade <= bugun + timedelta(days=YAKLASAN_GUN):
        return DURUM_YAKLASIYOR
    return DURUM_PLANLANDI


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
    def _kk_satirlari() -> list[dict]:
        from database.finans_service import FinansService

        satirlar: list[dict] = []
        try:
            kartlar = FinansService.banka_kartlari()
        except Exception:
            return satirlar
        for kart in kartlar:
            try:
                bekleyen = FinansService.kredi_karti_bekleyen_taksitler(kart.id, limit=500)
            except Exception:
                continue
            for t in bekleyen:
                vade = t.get("vade_tarihi")
                tutar = _d(t.get("tutar") or 0)
                if tutar <= 0 or not vade:
                    continue
                # Unique key: belge + taksit_no
                sid = f"{t.get('belge_no')}:{t.get('taksit_no')}"
                satirlar.append({
                    "obligation_key": OdemeDurumuService.obligation_key(KAYNAK_KK, sid, vade),
                    "source_type": KAYNAK_KK,
                    "source_id": sid,
                    "kredi_id": None,
                    "due_date": vade,
                    "payment_month": (vade.year, vade.month),
                    "aciklama": (
                        f"KK {t.get('kart') or ''} — "
                        f"{t.get('taksit_no')}/{t.get('taksit_sayisi')} taksit"
                    ).strip(),
                    "kaynak_etiket": "Kredi kartı",
                    "banka_adi": getattr(kart, "banka_adi", "") or "",
                    "belge_no": t.get("belge_no") or "",
                    "kategori": "Kredi kartı taksiti",
                    "para_birimi": "TRY",
                    "orijinal_tutar": tutar,
                    "tl_tutar": tutar,
                    "odenen": SIFIR,
                    "kalan": tutar,
                    "anapara": SIFIR,
                    "faiz": SIFIR,
                    "masraf": SIFIR,
                    "certainty": "KESIN",
                    "oncelik": "YUKSEK",
                    "durum": _durum_hesapla(vade, tutar, SIFIR),
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
    ) -> list[dict]:
        OdemeDurumuService.yetki_kontrol()
        if not oturum.firma_secili:
            raise ValueError("Aktif firma seçilmedi.")

        kaynaklar = kaynaklar or {KAYNAK_KREDI, KAYNAK_KK, KAYNAK_CEK}
        birlesik: dict[str, dict] = {}

        if KAYNAK_KREDI in kaynaklar:
            for s in OdemeDurumuService._kredi_satirlari(odenenleri_dahil=odenenleri_dahil):
                birlesik[s["obligation_key"]] = s
        if KAYNAK_KK in kaynaklar:
            for s in OdemeDurumuService._kk_satirlari():
                birlesik.setdefault(s["obligation_key"], s)
        if KAYNAK_CEK in kaynaklar:
            for s in OdemeDurumuService._cek_satirlari():
                birlesik.setdefault(s["obligation_key"], s)

        sonuc = list(birlesik.values())
        if sadece_acik:
            sonuc = [s for s in sonuc if s["durum"] not in (DURUM_ODENDI, DURUM_IPTAL) and s["kalan"] > 0]

        def _sirala(s):
            v = s.get("due_date") or date.max
            return (v, -(s.get("kalan") or SIFIR), s.get("aciklama") or "")

        sonuc.sort(key=_sirala)
        return sonuc

    @staticmethod
    def ay_listesi(baslangic: date | None = None, ay_sayisi: int = 6) -> list[tuple[int, int]]:
        bas = baslangic or date.today().replace(day=1)
        return [(_ay_ekle(bas, i).year, _ay_ekle(bas, i).month) for i in range(ay_sayisi)]

    @staticmethod
    def ay_etiket(yil: int, ay: int) -> str:
        aylar = (
            "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
        )
        return f"{aylar[ay]} {yil}"

    @staticmethod
    def ay_satirlari(yil: int, ay: int, **kwargs) -> list[dict]:
        bas, son = _ay_basi(yil, ay), _ay_sonu(yil, ay)
        return [
            s for s in OdemeDurumuService.tum_yukumlulukler(**kwargs)
            if s.get("due_date") and bas <= s["due_date"] <= son
        ]

    @staticmethod
    def ay_ozeti(yil: int, ay: int, satirlar: list[dict] | None = None) -> dict:
        satirlar = satirlar if satirlar is not None else OdemeDurumuService.ay_satirlari(yil, ay)
        toplam = sum((s["tl_tutar"] for s in satirlar), SIFIR)
        kalan = sum((s["kalan"] for s in satirlar), SIFIR)
        odenen = sum((s["odenen"] for s in satirlar), SIFIR)
        gecikmis = sum(
            (s["kalan"] for s in satirlar if s["durum"] == DURUM_GECIKMIS), SIFIR
        )
        yaklasan = sum(
            (s["kalan"] for s in satirlar if s["durum"] in (DURUM_YAKLASIYOR, DURUM_BUGUN)),
            SIFIR,
        )
        return {
            "yil": yil,
            "ay": ay,
            "etiket": OdemeDurumuService.ay_etiket(yil, ay),
            "toplam": toplam,
            "kalan": kalan,
            "odenen": odenen,
            "gecikmis": gecikmis,
            "yaklasan": yaklasan,
            "adet": len(satirlar),
        }

    @staticmethod
    def kpi(ay_sayisi: int = 6) -> dict[str, Any]:
        bugun = date.today()
        tum = OdemeDurumuService.tum_yukumlulukler(sadece_acik=True)
        bu_ay = [
            s for s in tum
            if s.get("due_date")
            and s["due_date"].year == bugun.year
            and s["due_date"].month == bugun.month
        ]
        gelecek_7 = [
            s for s in tum
            if s.get("due_date") and bugun <= s["due_date"] <= bugun + timedelta(days=7)
        ]
        gelecek_30 = [
            s for s in tum
            if s.get("due_date") and bugun <= s["due_date"] <= bugun + timedelta(days=30)
        ]
        return {
            "bu_ay_toplam": sum((s["tl_tutar"] for s in bu_ay), SIFIR),
            "bu_ay_kalan": sum((s["kalan"] for s in bu_ay), SIFIR),
            "bu_ay_odenen": sum((s["odenen"] for s in bu_ay), SIFIR),
            "gecikmis": sum((s["kalan"] for s in tum if s["durum"] == DURUM_GECIKMIS), SIFIR),
            "gelecek_7_gun": sum((s["kalan"] for s in gelecek_7), SIFIR),
            "gelecek_30_gun": sum((s["kalan"] for s in gelecek_30), SIFIR),
            "tahmini": SIFIR,  # Aşama 1'de tahmini gider yok
            "firma": getattr(oturum, "company_name", None)
            or getattr(oturum, "firma_adi", None)
            or "",
            "donem": getattr(oturum, "donem_adi", None) or "",
            "yenileme": date.today(),
            "aylar": [
                OdemeDurumuService.ay_ozeti(y, a)
                for y, a in OdemeDurumuService.ay_listesi(ay_sayisi=ay_sayisi)
            ],
        }
