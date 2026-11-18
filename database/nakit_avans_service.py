"""Firma kredi kartı nakit avans — tek çekim / taksitli plan, karta yansıtma, düzeltme.

Kurallar
--------
* Kullandırımda hesaba geçen net tutar bir kez kart bankasının **MEVDUAT/KMH** hesabına
  **NAKİT AVANS GİRİŞ** olarak yazılır (nakit kesintisi yoksa = anapara). Kart ekstresine
  yansıyan kullandırım ücreti nakit girişinden düşülmez; KK hesabına ayrı
  **KK NAKİT AVANS KULLANDIRIM ÜCRETİ** hareketi ve ekstre satırı olarak bir kez izlenir.
* Kayıtta **bütün taksitler** kendi ``yansima_tarihi`` ile karta işlenir (NAT + KK ödeme
  + faiz/masraf/vergi gider fişi); manuel «vadesi gelenleri işle» gerekmez. Gelecek
  vadeler bugünün tarihiyle toplu işlenmez; gider tarihi = ilgili taksit yansıması.
* **Anapara kredi/avans borcudur — giderleşmez.** Gider fişine yalnız faiz / masraf / vergi
  yazılır. Muhasebe planı da anaparayı ``nakit_avans_borcu``, faiz/masrafı gider hesaplarına ayırır.
* Karta işlemek ≠ ödemek. ``kalan_anapara`` yalnız gerçek ekstre ödemesinde
  (KK taksit ODENDI) **ödenen anapara** kadar azalır; faiz tutarı kalandan düşülmez.
* Ekstre ödemesi ikinci faiz/masraf/avans girişi üretmez (mevcut GDF / NAT korunur).
* ``islem_anahtari`` / ``istek_anahtari`` ile mükerrer yazım engellenir.
* Tüm yazmalar tek ``get_session`` işleminde; hata olursa hiçbir satır kalmaz.
"""

from __future__ import annotations

import calendar
import uuid
import weakref
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import (
    KK_MAX_TAKSIT,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
    NakitAvans,
    NakitAvansTaksit,
)

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
YAZMA = ("finans_duzenleme",)
GECIS_MODULU = "nakit_avans"
GECIS_SURUMU = 2
DURUM_PLAN = "PLANLANDI"
DURUM_KARTA = "KARTA_ISLENDI"
DURUM_IPTAL = "IPTAL"
HAREKET_GIRIS = "NAKİT AVANS GİRİŞ"
HAREKET_KART = "KK NAKİT AVANS"
HAREKET_KART_IPTAL = "KK NAKİT AVANS İPTAL"
HAREKET_KUL_UCRET = "KK NAKİT AVANS KULLANDIRIM ÜCRETİ"
HEDEF_ALT_TURLER = ("MEVDUAT", "KMH")

_HAZIR: "weakref.WeakSet" = weakref.WeakSet()


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation as hata:
        raise ValueError(f"Geçersiz tutar: {v}") from hata


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def _kurus(v, alan: str) -> Decimal:
    d = _d(v)
    if d != d.quantize(KURUS):
        raise ValueError(f"{alan} en çok iki ondalık (kuruş) içerebilir.")
    return d.quantize(KURUS)


def _motor():
    import database.database as veritabani

    return getattr(veritabani.company_db, "_engine", None) or veritabani.engine


def _eksik_var(motor) -> bool:
    ins = inspect(motor)
    for t in (NakitAvans.__tablename__, NakitAvansTaksit.__tablename__):
        if not ins.has_table(t):
            return True
    return False


def _gecis_v1(e) -> None:
    from database.modul_sema import eksik_kolonlari_ekle

    NakitAvans.__table__.create(e, checkfirst=True)
    NakitAvansTaksit.__table__.create(e, checkfirst=True)
    eksik_kolonlari_ekle(e, "kredi_karti_odemeleri", {
        "nakit_avans_taksit_id": "INTEGER",
    })
    eksik_kolonlari_ekle(e, "nakit_avans_taksitleri", {
        "faiz_valor_tarihi": "DATE",
    })


def _gecis_v2(e) -> None:
    """v1 tablolar + faiz_valor_tarihi (idempotent)."""
    _gecis_v1(e)


def schema_hazirla(motor=None) -> None:
    motor = motor or _motor()
    if motor is None or motor in _HAZIR:
        return
    from database.modul_sema import surum_uygula

    if not inspect(motor).has_table("kredi_karti_tanimlari"):
        _HAZIR.add(motor)
        return
    if _eksik_var(motor):
        import database.database as veritabani

        db_yolu = getattr(veritabani.company_db, "_db_path", None) if motor is _motor() else None
        if db_yolu:
            from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

            if yedek_onayi(db_yolu) is None:
                guvenli_gecis(
                    db_yolu,
                    lambda: surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v2),
                    gerekli=True,
                    etiket="nakit_avans_gecis",
                    baglantilari_kapat=lambda: motor.dispose(),
                )
                _HAZIR.add(motor)
                return
    surum_uygula(motor, GECIS_MODULU, GECIS_SURUMU, _gecis_v2)
    _HAZIR.add(motor)


def _ay_ekle(bas: date, ay: int) -> date:
    return FinansService._ay_ekle(bas, ay)


def _son_odeme(kart: KrediKartiTanimi, yansima: date) -> date | None:
    """Kesim/yansıma gününden kartın son ödeme kuralıyla tahmini vade."""
    try:
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        return KrediKartiEkstreService.son_odeme_hesapla(yansima, kart)
    except Exception:
        gun = getattr(kart, "son_odeme_gunu", None) or getattr(kart, "kesimden_sonra_odeme_gun", None)
        if not gun:
            return yansima
        try:
            g = int(gun)
        except (TypeError, ValueError):
            return yansima
        if getattr(kart, "kesimden_sonra_odeme_gun", None) and not getattr(kart, "son_odeme_gunu", None):
            from datetime import timedelta

            return yansima + timedelta(days=g)
        y, a = yansima.year, yansima.month
        son = calendar.monthrange(y, a)[1]
        return date(y, a, min(g, son))


def plan_hesapla(
    *,
    anapara,
    aylik_faiz_orani=0,
    taksit_sayisi=1,
    kullandirim_tarihi: date | None = None,
    ilk_yansima_tarihi: date | None = None,
    toplam_masraf=0,
    toplam_vergi=0,
    kart: KrediKartiTanimi | None = None,
    manuel_plan: list[dict] | None = None,
    sabit_taksit_tutari=None,
) -> list[dict]:
    """Aylık faiz oranıyla ödeme planı; yansıma / faiz valörü kullandırımdan türetilir.

    * Taksit i karta yansıma = kullandırım + (i−1) ay (1. taksit = kullandırım günü)
    * Taksit i faiz valörü = kullandırım + i ay
    * Faiz = dönemin kalan anaparası × aylık oran
    * ``sabit_taksit_tutari`` verilirse bankanın eşit taksiti kullanılır (anüite PMT yerine);
      aksi halde klasik anüite. Bu tutar global sabit değildir — çağıran belge/banka planı verir.
    * Son ödeme = kartın yansıma dönemindeki son ödeme kuralı
    * Yuvarlama: anapara kuruş farkı son taksitte
    """
    bas = kullandirim_tarihi or ilk_yansima_tarihi
    if bas is None:
        raise ValueError("Kullandırım tarihi gerekli.")
    ana = _kurus(anapara, "Anapara")
    if ana <= 0:
        raise ValueError("Avans anaparası pozitif olmalıdır.")
    try:
        n = int(str(taksit_sayisi).strip() or "1")
    except ValueError as hata:
        raise ValueError("Taksit sayısı tam sayı olmalıdır.") from hata
    if n < 1 or n > KK_MAX_TAKSIT:
        raise ValueError(f"Taksit sayısı 1–{KK_MAX_TAKSIT} arasında olmalıdır.")
    r = _d(aylik_faiz_orani) / Decimal("100")
    masraf_l = FinansService._tutar_bol(_kurus(toplam_masraf or 0, "Masraf"), n)
    vergi_l = FinansService._tutar_bol(_kurus(toplam_vergi or 0, "Vergi"), n)
    sabit_pmt = None
    if sabit_taksit_tutari not in (None, ""):
        sabit_pmt = _kurus(sabit_taksit_tutari, "Banka taksit tutarı")
        if sabit_pmt <= 0:
            raise ValueError("Banka taksit tutarı pozitif olmalıdır.")

    def _tarihler(no: int, sat: dict | None = None) -> tuple[date, date, date | None]:
        """no 1-based → yansıma, faiz_valor, son_odeme."""
        yan = (sat or {}).get("yansima_tarihi") if sat else None
        if yan is None:
            yan = _ay_ekle(bas, no - 1)
        elif isinstance(yan, str):
            yan = datetime.strptime(yan.strip()[:10], "%d.%m.%Y").date()
        valor = (sat or {}).get("faiz_valor_tarihi") if sat else None
        if valor is None:
            valor = _ay_ekle(bas, no)
        elif isinstance(valor, str):
            valor = datetime.strptime(valor.strip()[:10], "%d.%m.%Y").date()
        sod = (sat or {}).get("son_odeme_tarihi") if sat else None
        if isinstance(sod, str) and sod.strip():
            sod = datetime.strptime(sod.strip()[:10], "%d.%m.%Y").date()
        elif sod is None and kart is not None:
            sod = _son_odeme(kart, yan)
        return yan, valor, sod

    if manuel_plan is not None:
        if len(manuel_plan) != n:
            raise ValueError(f"Manuel plan {n} satır olmalıdır (gelen: {len(manuel_plan)}).")
        plan = []
        ana_top = SIFIR
        for i, sat in enumerate(manuel_plan):
            ap = _kurus(sat.get("anapara", 0), f"Taksit {i + 1} anapara")
            fz = _kurus(sat.get("faiz", 0), f"Taksit {i + 1} faiz")
            ms = _kurus(sat.get("masraf", masraf_l[i]), f"Taksit {i + 1} masraf")
            vg = _kurus(sat.get("vergi", vergi_l[i]), f"Taksit {i + 1} vergi")
            yan, valor, sod = _tarihler(i + 1, sat)
            top = _q2(ap + fz + ms + vg)
            plan.append({
                "taksit_no": i + 1,
                "yansima_tarihi": yan,
                "faiz_valor_tarihi": valor,
                "son_odeme_tarihi": sod,
                "anapara": ap,
                "faiz": fz,
                "masraf": ms,
                "vergi": vg,
                "toplam": top,
            })
            ana_top += ap
        if ana_top != ana:
            fark = ana - ana_top
            plan[-1]["anapara"] = _q2(plan[-1]["anapara"] + fark)
            plan[-1]["toplam"] = _q2(
                plan[-1]["anapara"] + plan[-1]["faiz"] + plan[-1]["masraf"] + plan[-1]["vergi"]
            )
        return plan

    # Anüite veya bankanın eşit taksiti: her dönem kalan × oran
    if r == 0 or n == 1:
        ana_l = FinansService._tutar_bol(ana, n)
        faiz_l = [SIFIR] * n
        if n == 1 and r != 0:
            faiz_l = [_q2(ana * r)]
        if n == 1 and sabit_pmt is not None:
            # Tek çekimde banka tutarı = anapara+faiz+masraf/vergi toplamı beklentisi
            pass
    else:
        if sabit_pmt is not None:
            pmt = sabit_pmt
        else:
            bir_arti = (Decimal("1") + r) ** n
            pmt = _q2(ana * r * bir_arti / (bir_arti - Decimal("1")))
        kalan = ana
        ana_l, faiz_l = [], []
        for i in range(1, n + 1):
            fz = _q2(kalan * r)
            if i == n:
                ap = kalan
                # Banka eşit taksit: son taksit de aynı toplam; faiz kalan×oran yerine
                # (pmt − anapara) ile dengelenir (anapara = kalan, toplam = pmt).
                if sabit_pmt is not None:
                    fz = _q2(pmt - ap)
                    if fz < 0:
                        # PMT kalan anaparadan küçükse faiz 0, toplam = anapara
                        fz = SIFIR
            else:
                ap = _q2(pmt - fz)
                if ap < 0:
                    ap = SIFIR
                if ap > kalan:
                    ap = kalan
            ana_l.append(ap)
            faiz_l.append(fz)
            kalan = _q2(kalan - ap)
        fark = ana - sum(ana_l, SIFIR)
        if fark != 0:
            ana_l[-1] = _q2(ana_l[-1] + fark)
            if sabit_pmt is not None and n > 1:
                # Son taksit toplamı banka PMT kalsın
                faiz_l[-1] = _q2(pmt - ana_l[-1])
                if faiz_l[-1] < 0:
                    faiz_l[-1] = SIFIR

    plan = []
    for i in range(n):
        yan, valor, sod = _tarihler(i + 1)
        ap, fz, ms, vg = ana_l[i], faiz_l[i], masraf_l[i], vergi_l[i]
        if sabit_pmt is not None and n > 1:
            top = _q2(sabit_pmt + ms + vg)
            # Anapara+faiz banka taksitine otursun (masraf/vergi ayrı eklenir)
            ic = _q2(ap + fz)
            if ic != sabit_pmt and i == n - 1:
                fz = _q2(sabit_pmt - ap)
                if fz < 0:
                    fz = SIFIR
                    top = _q2(ap + ms + vg)
                else:
                    top = _q2(sabit_pmt + ms + vg)
            elif i < n - 1:
                top = _q2(sabit_pmt + ms + vg)
        else:
            top = _q2(ap + fz + ms + vg)
        plan.append({
            "taksit_no": i + 1,
            "yansima_tarihi": yan,
            "faiz_valor_tarihi": valor,
            "son_odeme_tarihi": sod,
            "anapara": ap,
            "faiz": fz,
            "masraf": ms,
            "vergi": vg,
            "toplam": top,
        })
    return plan


def plan_ozeti(plan: list[dict], anapara) -> dict:
    ana = _q2(anapara)
    top_ana = _q2(sum((_d(x["anapara"]) for x in plan), SIFIR))
    top_faiz = _q2(sum((_d(x["faiz"]) for x in plan), SIFIR))
    top_masraf = _q2(sum((_d(x["masraf"]) for x in plan), SIFIR))
    top_vergi = _q2(sum((_d(x["vergi"]) for x in plan), SIFIR))
    top_taksit = _q2(sum((_d(x["toplam"]) for x in plan), SIFIR))
    return {
        "anapara": ana,
        "plan_anapara": top_ana,
        "anapara_fark": _q2(ana - top_ana),
        "toplam_faiz": top_faiz,
        "toplam_masraf": top_masraf,
        "toplam_vergi": top_vergi,
        "toplam_taksit": top_taksit,
        "geri_odenecek_toplam": top_taksit,
        "net_giris": ana,  # nakit kesintisi yoksa anapara; UI net alanı yazar
        "adet": len(plan),
    }


_BILESEN_ALANLAR = ("anapara", "faiz", "masraf", "vergi")
KAPSAM_TEK = "tek"
KAPSAM_TUM = "tum"


def taksit_bilesenlerini_orantila(
    *,
    anapara,
    faiz,
    masraf,
    vergi,
    yeni_toplam,
) -> dict:
    """Yeni taksit tutarını mevcut bileşen oranlarına göre dağıtır.

    Yeni bileşen = yeni_toplam × eski / eski_toplam.
    Sıfır bileşen sıfır kalır. Kuruş farkı deterministik olarak ilk pozitif
    bileşene (öncelik: anapara → faiz → masraf → vergi) eklenir.
    """
    yeni = _kurus(yeni_toplam, "Yeni taksit tutarı")
    if yeni <= 0:
        raise ValueError("Yeni taksit tutarı pozitif olmalıdır.")
    eski = {
        "anapara": _q2(anapara),
        "faiz": _q2(faiz),
        "masraf": _q2(masraf),
        "vergi": _q2(vergi),
    }
    eski_top = _q2(sum(eski.values(), SIFIR))
    if eski_top == SIFIR:
        raise ValueError(
            "Eski bileşenler toplamı sıfır. Oran hesaplanamaz; "
            "önce anapara/faiz/masraf/vergi tanımlayın."
        )
    yeni_b: dict[str, Decimal] = {}
    for alan in _BILESEN_ALANLAR:
        if eski[alan] == SIFIR:
            yeni_b[alan] = SIFIR
        else:
            yeni_b[alan] = _q2(yeni * eski[alan] / eski_top)
    dagilan = _q2(sum(yeni_b.values(), SIFIR))
    fark = _q2(yeni - dagilan)
    if fark != SIFIR:
        for alan in _BILESEN_ALANLAR:
            if eski[alan] != SIFIR or all(v == SIFIR for v in eski.values()):
                aday = _q2(yeni_b[alan] + fark)
                if aday >= SIFIR:
                    yeni_b[alan] = aday
                    break
        else:
            raise ValueError("Kuruş farkı bileşenlere dağıtılamadı.")
    sonuc_top = _q2(sum(yeni_b.values(), SIFIR))
    if sonuc_top != yeni:
        raise ValueError(
            f"Bileşen toplamı ({sonuc_top}) yeni taksit tutarına ({yeni}) eşit değil."
        )
    return {
        "anapara": yeni_b["anapara"],
        "faiz": yeni_b["faiz"],
        "masraf": yeni_b["masraf"],
        "vergi": yeni_b["vergi"],
        "toplam": yeni,
    }


def hedef_hesaplari_kart_bankasi(kredi_karti_id: int) -> list[dict]:
    """Seçili kartın bankasındaki aktif MEVDUAT / KMH hesapları (firma)."""
    with get_session() as s:
        kart = s.get(KrediKartiTanimi, int(kredi_karti_id))
        if kart is None:
            return []
        banka_id = int(kart.banka_karti_id)
        from database.hesap_siralama import hesaplari_sirala

        q = (
            select(FinansHesabi)
            .where(
                FinansHesabi.banka_karti_id == banka_id,
                FinansHesabi.aktif.is_(True),
            )
            .order_by(FinansHesabi.id)
        )
        out: list[dict] = []
        for h in s.scalars(q).all():
            alt = (h.alt_hesap_turu or "").strip().upper()
            if alt not in HEDEF_ALT_TURLER:
                continue
            out.append(
                {
                    "id": int(h.id),
                    "hesap_adi": h.hesap_adi or f"Hesap #{h.id}",
                    "hesap_turu": h.hesap_turu,
                    "alt_hesap_turu": alt,
                    "banka_karti_id": banka_id,
                }
            )
        return hesaplari_sirala(out)


def firma_kredi_kartlari_aktif() -> list[dict]:
    """Seçili firmanın tüm aktif kredi kartları (tüm bankalar)."""
    with get_session() as s:
        q = (
            select(KrediKartiTanimi)
            .where(KrediKartiTanimi.aktif.is_(True))
            .options(selectinload(KrediKartiTanimi.banka_karti))
            .order_by(KrediKartiTanimi.kart_adi, KrediKartiTanimi.id)
        )
        sonuc: list[dict] = []
        for k in s.scalars(q).all():
            banka = getattr(getattr(k, "banka_karti", None), "banka_adi", None) or (
                k.kart_bankasi or "—"
            )
            sonuc.append(
                {
                    "id": int(k.id),
                    "kart_adi": k.kart_adi or f"Kart #{k.id}",
                    "banka_adi": banka,
                    "banka_karti_id": int(k.banka_karti_id),
                    "son_dort_hane": k.son_dort_hane or "",
                    "etiket": (
                        f"{banka} / {k.kart_adi or 'Kart'}"
                        f" · ****{k.son_dort_hane or '????'}"
                    ),
                }
            )
        return sonuc


class NakitAvansService:
    @staticmethod
    def liste(*, kredi_karti_id: int | None = None, durum: str | None = None) -> list[dict]:
        schema_hazirla()
        with get_session() as s:
            if not inspect(s.bind).has_table(NakitAvans.__tablename__):
                return []
            q = select(NakitAvans).options(selectinload(NakitAvans.taksitler)).order_by(
                NakitAvans.islem_tarihi.desc(), NakitAvans.id.desc()
            )
            if kredi_karti_id:
                q = q.where(NakitAvans.kredi_karti_id == int(kredi_karti_id))
            if durum:
                q = q.where(NakitAvans.durum == durum)
            out = []
            for a in s.scalars(q).all():
                out.append(_avans_dict(a))
            return out

    @staticmethod
    def getir(avans_id: int) -> dict | None:
        schema_hazirla()
        with get_session() as s:
            a = s.get(NakitAvans, int(avans_id))
            if a is None:
                return None
            s.refresh(a, attribute_names=["taksitler"])
            return _avans_dict(a)

    @staticmethod
    def belgeden_getir(belge_no: str) -> dict | None:
        """NAV (avans) veya NAT (karta işlenmiş taksit hareketi) belge no → avans dict."""
        schema_hazirla()
        bn = (belge_no or "").strip()
        if not bn:
            return None
        with get_session() as s:
            a = s.scalar(select(NakitAvans).where(NakitAvans.belge_no == bn))
            if a is None:
                t = s.scalar(
                    select(NakitAvansTaksit).where(NakitAvansTaksit.kk_hareket_belge_no == bn)
                )
                if t is not None:
                    a = s.get(NakitAvans, int(t.avans_id))
            if a is None:
                return None
            s.refresh(a, attribute_names=["taksitler"])
            return _avans_dict(a)

    @staticmethod
    def kaydet(
        *,
        kredi_karti_id: int,
        islem_tarihi: date,
        anapara,
        hedef_hesap_id: int,
        aylik_faiz_orani=0,
        taksit_sayisi=1,
        ilk_yansima_tarihi: date | None = None,
        aciklama: str | None = None,
        net_giris=None,
        kullandirim_masraf=0,
        kullandirim_vergi=0,
        plan_masraf=0,
        plan_vergi=0,
        manuel_plan: list[dict] | None = None,
        sabit_taksit_tutari=None,
        istek_anahtari: str | None = None,
        sube_id: int | None = None,
    ) -> dict:
        """Avans + plan + hesaba net giriş + 1. taksit karta (tek transaction).

        ``net_giris``: bankanın fiilen yatırdığı tutar (nakit kesintisi yoksa = anapara).
        ``kullandirim_masraf`` / vergi: kart ekstresine ayrı borç (nakitten düşülmez).
        ``sabit_taksit_tutari``: bankanın eşit taksit tutarı (opsiyonel; anüite yerine).
        """
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        ana = _kurus(anapara, "Anapara")
        k_masraf = _kurus(kullandirim_masraf or 0, "Kullandırım masrafı")
        k_vergi = _kurus(kullandirim_vergi or 0, "Kullandırım vergisi")
        if net_giris is None or net_giris == "":
            net = ana  # nakit kesintisi yok → anaparanın tamamı
        else:
            net = _kurus(net_giris, "Net hesaba geçecek")
        if net <= 0:
            raise ValueError("Hesaba geçen net tutar pozitif olmalıdır.")
        if net > ana:
            raise ValueError("Net giriş anaparadan büyük olamaz.")
        anahtar = (istek_anahtari or "").strip() or None
        n = int(taksit_sayisi or 1)
        tur = "TEK_CEKIM" if n == 1 else "TAKSITLI"

        with get_session() as s:
            if anahtar:
                eski = s.scalar(select(NakitAvans).where(NakitAvans.istek_anahtari == anahtar))
                if eski is not None:
                    return _avans_dict(eski)
            kart = s.get(KrediKartiTanimi, int(kredi_karti_id))
            if kart is None or not kart.aktif:
                raise ValueError("Aktif firma kredi kartı bulunamadı.")
            hesap = s.get(FinansHesabi, int(hedef_hesap_id))
            if hesap is None:
                raise ValueError("Hedef mevduat/KMH hesabı bulunamadı.")
            alt = (hesap.alt_hesap_turu or "").strip().upper()
            if alt not in HEDEF_ALT_TURLER:
                raise ValueError("Hedef hesap yalnızca kart bankasının MEVDUAT veya KMH hesabı olabilir.")
            if int(hesap.banka_karti_id or 0) != int(kart.banka_karti_id):
                raise ValueError("Hedef hesap, kartı veren bankaya ait olmalıdır.")
            if not getattr(hesap, "aktif", True):
                raise ValueError("Hedef hesap aktif değil.")
            plan = plan_hesapla(
                anapara=ana,
                aylik_faiz_orani=aylik_faiz_orani,
                taksit_sayisi=n,
                kullandirim_tarihi=islem_tarihi,
                ilk_yansima_tarihi=ilk_yansima_tarihi,
                toplam_masraf=plan_masraf,
                toplam_vergi=plan_vergi,
                kart=kart,
                manuel_plan=manuel_plan,
                sabit_taksit_tutari=sabit_taksit_tutari,
            )
            oz = plan_ozeti(plan, ana)
            if oz["anapara_fark"] != 0:
                raise ValueError(
                    f"Plan anaparası ({oz['plan_anapara']}) avans tutarıyla ({ana}) eşleşmiyor."
                )
            ilk_yan = plan[0]["yansima_tarihi"]
            belge = FinansService._finans_belge_no(s, "NAV")
            avans = NakitAvans(
                belge_no=belge,
                kredi_karti_id=int(kart.id),
                banka_karti_id=int(kart.banka_karti_id),
                islem_tarihi=islem_tarihi,
                anapara=ana,
                kalan_anapara=ana,
                net_giris=net,
                kullandirim_masraf=k_masraf,
                kullandirim_vergi=k_vergi,
                hedef_hesap_id=int(hesap.id),
                aylik_faiz_orani=_d(aylik_faiz_orani),
                taksit_sayisi=n,
                cekim_turu=tur,
                ilk_yansima_tarihi=ilk_yan,
                aciklama=(aciklama or "").strip() or None,
                durum="ACIK",
                plan_versiyon=1,
                istek_anahtari=anahtar,
            )
            s.add(avans)
            s.flush()
            for sat in plan:
                s.add(
                    NakitAvansTaksit(
                        avans_id=int(avans.id),
                        taksit_no=int(sat["taksit_no"]),
                        yansima_tarihi=sat["yansima_tarihi"],
                        faiz_valor_tarihi=sat.get("faiz_valor_tarihi"),
                        son_odeme_tarihi=sat.get("son_odeme_tarihi"),
                        anapara=sat["anapara"],
                        faiz=sat["faiz"],
                        masraf=sat["masraf"],
                        vergi=sat["vergi"],
                        toplam=sat["toplam"],
                        durum=DURUM_PLAN,
                        plan_versiyon=1,
                        aktif=True,
                    )
                )
            s.flush()
            # Hesaba net giriş (bir kez)
            s.add(FinansHareketi(
                hesap_id=int(hesap.id),
                sube_id=sube_id,
                tarih=islem_tarihi,
                hareket_turu=HAREKET_GIRIS,
                belge_no=belge,
                tutar=net,
                aciklama=f"Nakit avans {kart.kart_adi} · {belge}",
            ))
            avans.finans_belge_no = belge
            # Kullandırım ücreti: kart ekstresinde ayrı borç (nakit girişinden düşülmez)
            kul_ucret = _q2(k_masraf + k_vergi)
            if kul_ucret > 0:
                _kullandirim_ucreti_ekstre_yaz(
                    s,
                    kart=kart,
                    avans=avans,
                    tutar=kul_ucret,
                    tarih=islem_tarihi,
                    sube_id=sube_id,
                    masraf=k_masraf,
                    vergi=k_vergi,
                )
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            try:
                KrediKartiEkstreService.limit_kontrol(s, kart, ana)
            except ValueError:
                raise
            except Exception:
                pass
            try:
                from database.muhasebe_entegrasyon import muhasebe_hook

                muhasebe_hook("nakit_avans_kullandirim_fisi", avans.id, session=s)
            except Exception:
                pass
            # Bütün taksitler: kendi yansıma tarihiyle NAT/KK/gider (aynı transaction)
            s.flush()
            for trow in sorted(
                [x for x in (avans.taksitler or []) if x.aktif],
                key=lambda x: int(x.taksit_no),
            ):
                _taksit_karta_isle_oturum(
                    s,
                    trow,
                    islem_tarihi=trow.yansima_tarihi or islem_tarihi,
                    islem_anahtari=f"na-kayit-t{int(trow.taksit_no)}-{avans.id}",
                    sube_id=sube_id,
                )
            _kalan_yenile(s, avans)
            s.flush()
            return _avans_dict(avans)

    @staticmethod
    def taksit_karta_isle(
        taksit_id: int,
        *,
        islem_tarihi: date | None = None,
        islem_anahtari: str | None = None,
        sube_id: int | None = None,
    ) -> dict:
        """Planlanan taksiti karta tek tutar olarak yaz; anaparayı avans borcundan düş."""
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        anahtar = (islem_anahtari or "").strip() or f"na-taksit-{int(taksit_id)}"
        with get_session() as s:
            t = s.get(NakitAvansTaksit, int(taksit_id))
            if t is None:
                raise ValueError("Taksit bulunamadı.")
            return _taksit_karta_isle_oturum(
                s, t, islem_tarihi=islem_tarihi, islem_anahtari=anahtar, sube_id=sube_id
            )

    @staticmethod
    def vadesi_gelenleri_isle(*, kredi_karti_id: int | None = None, bugun: date | None = None) -> list[dict]:
        """Eski API uyumu: eksik PLANLANDI hareketlerini kendi yansıma tarihiyle tamamlar.

        Kayıtta tüm taksitler oluşur; bu metod yalnız onarım içindir.
        ``bugun`` tarih filtrelemez — her satır kendi ``yansima_tarihi`` ile işlenir.
        """
        _ = bugun
        return NakitAvansService.eksik_taksit_hareketlerini_tamamla(
            kredi_karti_id=kredi_karti_id, avans_id=None
        )

    @staticmethod
    def ekstre_odeme_sonrasi_guncelle(
        session,
        *,
        kredi_karti_id: int | None = None,
        banka_karti_id: int | None = None,
    ) -> list[int]:
        """KK taksit ODENDI sonrası ``kalan_anapara`` yenile; ikinci gider/NAT yazma.

        Ekstre ödemesi faiz/masrafı yeniden giderleştirmez — bunlar taksit yansımasında
        bir kez oluşmuştur. Yalnız ödenen anapara bileşeni kalanı düşürür.
        """
        q = (
            select(NakitAvans)
            .where(NakitAvans.durum == "ACIK")
            .options(selectinload(NakitAvans.taksitler))
        )
        if kredi_karti_id is not None:
            q = q.where(NakitAvans.kredi_karti_id == int(kredi_karti_id))
        if banka_karti_id is not None:
            q = q.where(NakitAvans.banka_karti_id == int(banka_karti_id))
        guncellenen: list[int] = []
        for avans in session.scalars(q).all():
            once = _q2(avans.kalan_anapara)
            _kalan_yenile(session, avans)
            if _q2(avans.kalan_anapara) != once or avans.durum == "KAPALI":
                guncellenen.append(int(avans.id))
        return guncellenen

    @staticmethod
    def eksik_taksit_hareketlerini_tamamla(
        *,
        kredi_karti_id: int | None = None,
        avans_id: int | None = None,
    ) -> list[dict]:
        """PLANLANDI kalan taksitleri kendi yansıma tarihiyle karta işler (mükerrer yok)."""
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        with get_session() as s:
            q = (
                select(NakitAvansTaksit)
                .join(NakitAvans, NakitAvans.id == NakitAvansTaksit.avans_id)
                .where(
                    NakitAvansTaksit.durum == DURUM_PLAN,
                    NakitAvansTaksit.aktif.is_(True),
                    NakitAvans.durum == "ACIK",
                )
                .order_by(NakitAvansTaksit.avans_id, NakitAvansTaksit.taksit_no)
            )
            if kredi_karti_id:
                q = q.where(NakitAvans.kredi_karti_id == int(kredi_karti_id))
            if avans_id:
                q = q.where(NakitAvans.id == int(avans_id))
            adaylar = list(s.scalars(q).all())
            sonuc: list[dict] = []
            for t in adaylar:
                try:
                    sonuc.append(
                        _taksit_karta_isle_oturum(
                            s,
                            t,
                            islem_tarihi=t.yansima_tarihi,
                            islem_anahtari=(
                                t.islem_anahtari
                                or f"na-kayit-t{int(t.taksit_no)}-{int(t.avans_id)}"
                            ),
                        )
                    )
                except Exception as exc:
                    sonuc.append({"taksit_id": int(t.id), "hata": str(exc)})
            for aid in {int(t.avans_id) for t in adaylar}:
                av = s.get(NakitAvans, aid)
                if av is not None:
                    _kalan_yenile(s, av)
            s.flush()
            return sonuc

    @staticmethod
    def planlanan_bekleyenler(
        *,
        banka_karti_id: int | None = None,
        kredi_karti_id: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Henüz karta işlenmemiş (PLANLANDI) nakit avans taksitleri — bekleyen listesi / takvim."""
        schema_hazirla()
        with get_session() as s:
            q = (
                select(NakitAvansTaksit)
                .join(NakitAvans)
                .where(
                    NakitAvansTaksit.durum == DURUM_PLAN,
                    NakitAvansTaksit.aktif.is_(True),
                    NakitAvans.durum == "ACIK",
                )
                .options(selectinload(NakitAvansTaksit.avans))
                .order_by(NakitAvansTaksit.yansima_tarihi, NakitAvansTaksit.id)
                .limit(int(limit))
            )
            if banka_karti_id is not None:
                q = q.where(NakitAvans.banka_karti_id == int(banka_karti_id))
            if kredi_karti_id is not None:
                q = q.where(NakitAvans.kredi_karti_id == int(kredi_karti_id))
            sonuc: list[dict] = []
            for t in s.scalars(q).all():
                a = t.avans
                if a is None:
                    continue
                kart = s.get(KrediKartiTanimi, int(a.kredi_karti_id))
                sonuc.append(
                    {
                        "belge_no": a.belge_no,
                        "odeme_id": None,
                        "taksit_id": int(t.id),
                        "nakit_avans_taksit_id": int(t.id),
                        "kart": kart.kart_adi if kart else "",
                        "kredi_karti_id": int(a.kredi_karti_id),
                        "banka_karti_id": int(a.banka_karti_id),
                        "taksit_no": int(t.taksit_no),
                        "taksit_sayisi": int(a.taksit_sayisi),
                        "vade_tarihi": t.son_odeme_tarihi or t.yansima_tarihi,
                        "banka_vade_tarihi": t.son_odeme_tarihi,
                        "ekstre_kesim_tarihi": t.yansima_tarihi,
                        "odenen_tutar": SIFIR,
                        "tutar": _q2(t.toplam),
                        "durum": DURUM_PLAN,
                        "kaynak": "NAKIT_AVANS",
                    }
                )
            return sonuc

    @staticmethod
    def taksit_tutari_onizle(
        *,
        avans_id: int,
        taksit_id: int,
        yeni_tutar,
        kapsam: str,
    ) -> dict:
        """Tek/tüm taksit tutarı değişiminin önizlemesi — veritabanına yazmaz."""
        schema_hazirla()
        yeni = _kurus(yeni_tutar, "Yeni taksit tutarı")
        kap = (kapsam or "").strip().lower()
        if kap not in (KAPSAM_TEK, KAPSAM_TUM):
            raise ValueError("Kapsam 'tek' veya 'tum' olmalıdır.")
        with get_session() as s:
            avans = s.scalar(
                select(NakitAvans)
                .where(NakitAvans.id == int(avans_id))
                .options(selectinload(NakitAvans.taksitler))
            )
            if avans is None:
                raise ValueError("Nakit avans bulunamadı.")
            secili = s.get(NakitAvansTaksit, int(taksit_id))
            if secili is None or int(secili.avans_id) != int(avans.id):
                raise ValueError("Taksit bu nakit avans evrakına ait değil.")
            return _taksit_tutari_plan_hazirla(s, avans, secili, yeni, kap)

    @staticmethod
    def taksit_tutari_uygula(
        *,
        avans_id: int,
        taksit_id: int,
        yeni_tutar,
        kapsam: str,
        onay_anahtari: str | None = None,
    ) -> dict:
        """Seçilen kapsamda taksit tutarını orantılı günceller (tek transaction).

        KARTA_ISLENDI satırlarda NAT/KK ödeme/gider yerinde güncellenir;
        yeni nakit avans girişi veya mükerrer NAT üretilmez.
        """
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        yeni = _kurus(yeni_tutar, "Yeni taksit tutarı")
        kap = (kapsam or "").strip().lower()
        if kap not in (KAPSAM_TEK, KAPSAM_TUM):
            raise ValueError("Kapsam 'tek' veya 'tum' olmalıdır.")
        with get_session() as s:
            avans = s.scalar(
                select(NakitAvans)
                .where(NakitAvans.id == int(avans_id))
                .options(selectinload(NakitAvans.taksitler))
            )
            if avans is None:
                raise ValueError("Nakit avans bulunamadı.")
            secili = s.get(NakitAvansTaksit, int(taksit_id))
            if secili is None or int(secili.avans_id) != int(avans.id):
                raise ValueError("Taksit bu nakit avans evrakına ait değil.")
            oniz = _taksit_tutari_plan_hazirla(s, avans, secili, yeni, kap)
            if not oniz.get("degisecek"):
                if oniz.get("engeller"):
                    nedenler = "; ".join(
                        f"T{e['taksit_no']}: {e['neden']}" for e in oniz["engeller"]
                    )
                    raise ValueError(
                        "Değiştirilebilir taksit yok — işlem uygulanmadı. " + nedenler
                    )
                raise ValueError("Değişecek taksit yok.")
            # "Tüm taksitler": sessizce kısmi uygulama yok — engel varsa açık hata
            if kap == KAPSAM_TUM and oniz.get("engeller"):
                nedenler = "; ".join(
                    f"T{e['taksit_no']}: {e['neden']}" for e in oniz["engeller"]
                )
                raise ValueError(
                    "Tüm taksitler uygulanamadı; değiştirilemeyen kayıtlar var. "
                    + nedenler
                )
            # Plan uygulama anında yeniden hesaplanır (onay_anahtari yalnızca UI izi)
            _ = onay_anahtari

            eski_snap = {
                "belge_no": avans.belge_no,
                "plan_versiyon": int(avans.plan_versiyon or 1),
                "taksitler": [
                    {
                        "taksit_no": d["taksit_no"],
                        "eski": d["eski"],
                        "durum": d["durum"],
                    }
                    for d in oniz["degisecek"]
                ],
            }
            yeni_v = int(avans.plan_versiyon or 1) + 1
            avans.plan_versiyon = yeni_v
            avans.guncelleme = datetime.now()
            simdi = datetime.now()

            for d in oniz["degisecek"]:
                t = s.get(NakitAvansTaksit, int(d["id"]))
                if t is None:
                    raise ValueError(f"Taksit #{d['id']} kaybolmuş.")
                nb = d["yeni"]
                t.anapara = nb["anapara"]
                t.faiz = nb["faiz"]
                t.masraf = nb["masraf"]
                t.vergi = nb["vergi"]
                t.toplam = nb["toplam"]
                t.plan_versiyon = yeni_v
                if t.durum == DURUM_KARTA:
                    _taksit_karta_islenmis_yerinde_guncelle(s, t, nb)
                # PLANLANDI: yalnızca bileşenler; vade/tarih korunur
            _kalan_yenile(s, avans)
            s.flush()
            sonuc = _avans_dict(avans)
            sonuc["taksit_tutari_islem"] = {
                "kapsam": kap,
                "yeni_tutar": str(yeni),
                "plan_versiyon": yeni_v,
                "degisen_adet": len(oniz["degisecek"]),
                "islem_zamani": simdi.isoformat(timespec="seconds"),
                "degisecek": oniz["degisecek"],
            }
            try:
                from database.user_audit import audit_document

                audit_document(
                    "NAKIT_AVANS_TAKSIT_TUTARI",
                    modul=GECIS_MODULU,
                    kayit_id=str(avans.id),
                    belge_no=avans.belge_no,
                    eski=eski_snap,
                    yeni={
                        "kapsam": kap,
                        "yeni_tutar": str(yeni),
                        "plan_versiyon": yeni_v,
                        "degisen": [
                            {"taksit_no": d["taksit_no"], "yeni": d["yeni"]}
                            for d in oniz["degisecek"]
                        ],
                        "islem_zamani": simdi.isoformat(timespec="seconds"),
                    },
                    aciklama=(
                        f"Taksit tutarı {kap}: {_q2(yeni)} · "
                        f"{len(oniz['degisecek'])} satır"
                    ),
                )
            except Exception:
                pass
            return sonuc

    @staticmethod
    def taksit_duzenle(
        taksit_id: int,
        *,
        anapara=None,
        faiz=None,
        masraf=None,
        vergi=None,
        yansima_tarihi=None,
        faiz_valor_tarihi=None,
        son_odeme_tarihi=None,
    ) -> dict:
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        with get_session() as s:
            t = s.get(NakitAvansTaksit, int(taksit_id))
            if t is None:
                raise ValueError("Taksit bulunamadı.")
            avans = s.get(NakitAvans, int(t.avans_id))
            if t.durum == DURUM_IPTAL:
                raise ValueError("İptal taksit düzenlenemez.")
            yeniden_isle = t.durum == DURUM_KARTA
            if yeniden_isle:
                _taksit_kart_geri_al(s, t, avans)
            if anapara is not None:
                t.anapara = _kurus(anapara, "Anapara")
            if faiz is not None:
                t.faiz = _kurus(faiz, "Faiz")
            if masraf is not None:
                t.masraf = _kurus(masraf, "Masraf")
            if vergi is not None:
                t.vergi = _kurus(vergi, "Vergi")
            if yansima_tarihi is not None:
                t.yansima_tarihi = yansima_tarihi
            if faiz_valor_tarihi is not None:
                t.faiz_valor_tarihi = faiz_valor_tarihi
            if son_odeme_tarihi is not None:
                t.son_odeme_tarihi = son_odeme_tarihi
            t.toplam = _q2(t.anapara + t.faiz + t.masraf + t.vergi)
            t.durum = DURUM_PLAN
            t.kk_odeme_id = None
            t.kk_hareket_belge_no = None
            t.islem_anahtari = None
            _kalan_yenile(s, avans)
            tid = int(t.id)
            s.flush()
            if not yeniden_isle:
                return _taksit_dict(t)
        return NakitAvansService.taksit_karta_isle(
            tid, islem_anahtari=f"na-duzelt-{tid}-{uuid.uuid4().hex[:8]}"
        )

    @staticmethod
    def taksit_sil(taksit_id: int) -> dict:
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        with get_session() as s:
            t = s.get(NakitAvansTaksit, int(taksit_id))
            if t is None:
                raise ValueError("Taksit bulunamadı.")
            avans = s.get(NakitAvans, int(t.avans_id))
            if t.durum == DURUM_KARTA:
                _taksit_kart_geri_al(s, t, avans)
            t.durum = DURUM_IPTAL
            t.aktif = False
            _kalan_yenile(s, avans)
            avans.guncelleme = datetime.now()
            s.flush()
            return _taksit_dict(t)


def _taksit_degistirilebilir_mi(s, t: NakitAvansTaksit) -> tuple[bool, str | None]:
    """(uygun_mu, engel_nedeni). İptal / ödenmiş ekstre satırı engellenir."""
    if not t.aktif or t.durum == DURUM_IPTAL:
        return False, "İptal edilmiş taksit düzenlenemez."
    if t.durum not in (DURUM_PLAN, DURUM_KARTA):
        return False, f"Durum '{t.durum}' düzenlemeye uygun değil."
    if t.durum == DURUM_KARTA and t.kk_odeme_id:
        od = s.get(KrediKartiOdeme, int(t.kk_odeme_id))
        if od is not None:
            od_durum = (od.durum or "").upper()
            if od_durum in ("ODENDI", "ÖDENDİ", "KAPALI", "IPTAL", "İPTAL"):
                if od_durum in ("ODENDI", "ÖDENDİ", "KAPALI"):
                    return False, "Kart ödeme kaydı ödenmiş/kapalı; tutar yerinde değiştirilemez."
            for kt in od.taksitler or []:
                kd = (kt.durum or "").upper()
                if kd in ("ODENDI", "ÖDENDİ", "ODENMIS", "ÖDENMİŞ"):
                    return False, "Ekstre taksiti ödenmiş; gerçek ödeme kaydı korunuyor."
    return True, None


def _taksit_tutari_plan_hazirla(
    s,
    avans: NakitAvans,
    secili: NakitAvansTaksit,
    yeni: Decimal,
    kapsam: str,
) -> dict:
    """Önizleme: değişecek / engellenen satırlar (yazma yok)."""
    adaylar: list[NakitAvansTaksit] = []
    if kapsam == KAPSAM_TEK:
        adaylar = [secili]
    else:
        adaylar = sorted(
            [t for t in (avans.taksitler or []) if t.aktif or t.durum != DURUM_IPTAL],
            key=lambda x: int(x.taksit_no),
        )
        # Aynı evrak dışına taşma yok — yalnızca bu avans_id
        adaylar = [t for t in adaylar if int(t.avans_id) == int(avans.id)]

    degisecek: list[dict] = []
    engeller: list[dict] = []
    for t in adaylar:
        uygun, neden = _taksit_degistirilebilir_mi(s, t)
        eski = {
            "anapara": _q2(t.anapara),
            "faiz": _q2(t.faiz),
            "masraf": _q2(t.masraf),
            "vergi": _q2(t.vergi),
            "toplam": _q2(t.toplam),
        }
        if not uygun:
            engeller.append({
                "id": int(t.id),
                "taksit_no": int(t.taksit_no),
                "durum": t.durum,
                "eski": eski,
                "neden": neden,
            })
            continue
        try:
            yeni_b = taksit_bilesenlerini_orantila(
                anapara=eski["anapara"],
                faiz=eski["faiz"],
                masraf=eski["masraf"],
                vergi=eski["vergi"],
                yeni_toplam=yeni,
            )
        except ValueError as exc:
            engeller.append({
                "id": int(t.id),
                "taksit_no": int(t.taksit_no),
                "durum": t.durum,
                "eski": eski,
                "neden": str(exc),
            })
            continue
        degisecek.append({
            "id": int(t.id),
            "taksit_no": int(t.taksit_no),
            "durum": t.durum,
            "yansima_tarihi": t.yansima_tarihi,
            "son_odeme_tarihi": t.son_odeme_tarihi,
            "eski": eski,
            "yeni": {
                "anapara": yeni_b["anapara"],
                "faiz": yeni_b["faiz"],
                "masraf": yeni_b["masraf"],
                "vergi": yeni_b["vergi"],
                "toplam": yeni_b["toplam"],
            },
        })

    # Tüm kapsamda engel varsa kullanıcıya açıkça göster (sessizce geleceklerle sınırlama yok)
    onay = uuid.uuid4().hex[:12]
    aktif_plan = [
        {
            "anapara": _q2(t.anapara),
            "faiz": _q2(t.faiz),
            "masraf": _q2(t.masraf),
            "vergi": _q2(t.vergi),
            "toplam": _q2(t.toplam),
        }
        for t in (avans.taksitler or [])
        if t.aktif and t.durum != DURUM_IPTAL
    ]
    # Önizleme sonrası plan özeti (değişecek satırlar yerine konmuş)
    by_no = {int(d["taksit_no"]): d["yeni"] for d in degisecek}
    oniz_plan = []
    for t in sorted(
        [x for x in (avans.taksitler or []) if x.aktif and x.durum != DURUM_IPTAL],
        key=lambda x: int(x.taksit_no),
    ):
        if int(t.taksit_no) in by_no:
            oniz_plan.append(by_no[int(t.taksit_no)])
        else:
            oniz_plan.append({
                "anapara": _q2(t.anapara),
                "faiz": _q2(t.faiz),
                "masraf": _q2(t.masraf),
                "vergi": _q2(t.vergi),
                "toplam": _q2(t.toplam),
            })
    return {
        "avans_id": int(avans.id),
        "belge_no": avans.belge_no,
        "kapsam": kapsam,
        "yeni_tutar": yeni,
        "secili_taksit_id": int(secili.id),
        "secili_taksit_no": int(secili.taksit_no),
        "taksit_sayisi": int(avans.taksit_sayisi),
        "degisecek": degisecek,
        "engeller": engeller,
        "onay_anahtari": onay,
        "plan_ozeti_once": plan_ozeti(aktif_plan, avans.anapara),
        "plan_ozeti_sonra": plan_ozeti(oniz_plan, avans.anapara),
    }


def _taksit_karta_islenmis_yerinde_guncelle(s, t: NakitAvansTaksit, yeni_b: dict) -> None:
    """KARTA_ISLENDI: mevcut NAT / KK ödeme / gider tutarlarını yerinde güncelle (mükerrer yok)."""
    yeni_top = _q2(yeni_b["toplam"])
    if t.kk_hareket_belge_no:
        fh = s.scalars(
            select(FinansHareketi).where(
                FinansHareketi.belge_no == t.kk_hareket_belge_no,
                FinansHareketi.hareket_turu == HAREKET_KART,
            )
        ).first()
        if fh is not None:
            fh.tutar = yeni_top
            fh.aciklama = (
                f"Nakit avans taksit {int(t.taksit_no)} · "
                f"A{yeni_b['anapara']}+F{yeni_b['faiz']}"
                f"+M{yeni_b['masraf']}+V{yeni_b['vergi']}"
            )
    if t.kk_odeme_id:
        od = s.get(KrediKartiOdeme, int(t.kk_odeme_id))
        if od is not None and (od.durum or "").upper() not in ("IPTAL", "İPTAL"):
            od.tutar = yeni_top
            for kt in od.taksitler or []:
                if not kt.aktif:
                    continue
                kd = (kt.durum or "").upper()
                if kd in ("ODENDI", "ÖDENDİ", "ODENMIS", "ÖDENMİŞ"):
                    continue
                kt.tutar = yeni_top
    for belge_g, alan in (
        (t.faiz_gider_belge_no, "faiz"),
        (t.masraf_gider_belge_no, "masraf"),
        (t.vergi_gider_belge_no, "vergi"),
    ):
        if not belge_g:
            continue
        gf = s.scalar(select(GiderFisi).where(GiderFisi.belge_no == belge_g))
        if gf is not None and (gf.durum or "").upper() not in ("IPTAL", "İPTAL"):
            gf.tutar = _q2(yeni_b[alan])


def _kk_hesap(s, kart: KrediKartiTanimi) -> FinansHesabi:
    hid = getattr(kart, "bagli_hesap_id", None)
    if hid:
        h = s.get(FinansHesabi, int(hid))
        if h is not None:
            return h
    # Banka kartına bağlı KK hesabı
    for h in s.scalars(select(FinansHesabi).where(
            FinansHesabi.banka_karti_id == int(kart.banka_karti_id),
            FinansHesabi.alt_hesap_turu == "KREDI_KARTI")).all():
        return h
    raise ValueError("Kartın bağlı kredi kartı finans hesabı yok.")


def _gider_yaz(s, *, tarih: date, tutar: Decimal, tur: str, aciklama: str, ref: str) -> str:
    from database.kredi_gider_fisi_service import KrediGiderFisiService

    belge = FinansService._finans_belge_no(s, "GDF")
    fis = GiderFisi(
        belge_no=belge,
        tarih=tarih,
        tutar=tutar,
        gider_turu=tur,
        aciklama=aciklama,
        durum="AÇIK",
        bagli_belge_no=ref,
    )
    s.add(fis)
    s.flush()  # sonraki gider aynı belge_no sayacını görsün
    KrediGiderFisiService.damgala(s, fis)
    return belge


def _kullandirim_ucreti_ekstre_yaz(
    s,
    *,
    kart: KrediKartiTanimi,
    avans: NakitAvans,
    tutar: Decimal,
    tarih: date,
    sube_id: int | None,
    masraf: Decimal,
    vergi: Decimal,
) -> str:
    """Kullandırım ücretini kart ekstresine tek borç hareketi olarak yaz (nakitten düşme)."""
    kk_hesap = _kk_hesap(s, kart)
    belge = FinansService._finans_belge_no(s, "NAK")
    s.add(
        FinansHareketi(
            hesap_id=int(kk_hesap.id),
            sube_id=sube_id,
            tarih=tarih,
            hareket_turu=HAREKET_KUL_UCRET,
            belge_no=belge,
            tutar=tutar,
            aciklama=f"Nakit avans kullandırım ücreti {avans.belge_no}",
        )
    )
    kk_odeme = KrediKartiOdeme(
        belge_no=belge,
        tarih=tarih,
        vade_tarihi=tarih,
        banka_karti_id=int(avans.banka_karti_id),
        kredi_karti_id=int(avans.kredi_karti_id),
        cari_id=0,
        cekim_turu="TEK_CEKIM",
        taksit_sayisi=1,
        tutar=tutar,
        aciklama=f"Nakit avans kullandırım ücreti {avans.belge_no}",
        durum="AÇIK",
        kaynak_turu="NAKIT_AVANS",
        plan_versiyon=1,
    )
    s.add(kk_odeme)
    s.flush()
    s.add(
        KrediKartiOdemeTaksit(
            odeme_id=int(kk_odeme.id),
            taksit_no=1,
            vade_tarihi=tarih,
            tutar=tutar,
            durum="BEKLIYOR",
            ekstre_kesim_tarihi=tarih,
            banka_vade_tarihi=tarih,
            plan_versiyon=1,
            aktif=True,
        )
    )
    if masraf > 0:
        _gider_yaz(
            s,
            tarih=tarih,
            tutar=masraf,
            tur="NAKIT_AVANS_KUL_MASRAF",
            aciklama=f"Nakit avans kullandırım masrafı {avans.belge_no}",
            ref=belge,
        )
    if vergi > 0:
        _gider_yaz(
            s,
            tarih=tarih,
            tutar=vergi,
            tur="NAKIT_AVANS_KUL_VERGI",
            aciklama=f"Nakit avans kullandırım vergisi {avans.belge_no}",
            ref=belge,
        )
    s.flush()
    return belge


def _taksit_karta_isle_oturum(
    s,
    t: NakitAvansTaksit,
    *,
    islem_tarihi: date | None = None,
    islem_anahtari: str | None = None,
    sube_id: int | None = None,
) -> dict:
    """Açık oturumda taksiti karta işle (kaydet / vade işle ortak)."""
    if t.durum == DURUM_KARTA and t.kk_hareket_belge_no:
        return _taksit_dict(t)
    if t.durum == DURUM_IPTAL or not t.aktif:
        raise ValueError("İptal taksit karta işlenemez.")
    anahtar = (islem_anahtari or t.islem_anahtari or f"na-taksit-{int(t.id)}").strip()
    if t.islem_anahtari:
        diger = s.scalar(
            select(NakitAvansTaksit).where(
                NakitAvansTaksit.islem_anahtari == t.islem_anahtari,
                NakitAvansTaksit.id != t.id,
            )
        )
        if diger and diger.durum == DURUM_KARTA:
            return _taksit_dict(diger)
    avans = s.get(NakitAvans, int(t.avans_id))
    if avans is None or avans.durum == "IPTAL":
        raise ValueError("Avans kaydı geçersiz.")
    kart = s.get(KrediKartiTanimi, int(avans.kredi_karti_id))
    kk_hesap = _kk_hesap(s, kart)
    tarih = islem_tarihi or t.yansima_tarihi or date.today()
    if t.islem_anahtari is None:
        t.islem_anahtari = anahtar
    if anahtar:
        once = s.scalar(
            select(NakitAvansTaksit).where(
                NakitAvansTaksit.islem_anahtari == anahtar,
                NakitAvansTaksit.durum == DURUM_KARTA,
            )
        )
        if once is not None:
            return _taksit_dict(once)
    belge = FinansService._finans_belge_no(s, "NAT")
    toplam = _q2(t.toplam)
    if toplam <= 0:
        raise ValueError("Taksit toplamı pozitif olmalıdır.")
    s.add(
        FinansHareketi(
            hesap_id=int(kk_hesap.id),
            sube_id=sube_id,
            tarih=tarih,
            hareket_turu=HAREKET_KART,
            belge_no=belge,
            tutar=toplam,
            aciklama=(
                f"Nakit avans taksit {t.taksit_no}/{avans.taksit_sayisi} · "
                f"A{_q2(t.anapara)}+F{_q2(t.faiz)}+M{_q2(t.masraf)}+V{_q2(t.vergi)}"
            ),
        )
    )
    kk_odeme = KrediKartiOdeme(
        belge_no=belge,
        tarih=tarih,
        vade_tarihi=t.son_odeme_tarihi or t.yansima_tarihi,
        banka_karti_id=int(avans.banka_karti_id),
        kredi_karti_id=int(avans.kredi_karti_id),
        cari_id=0,
        cekim_turu="TEK_CEKIM",
        taksit_sayisi=1,
        tutar=toplam,
        aciklama=f"Nakit avans {avans.belge_no} taksit {t.taksit_no}",
        durum="AÇIK",
        kaynak_turu="NAKIT_AVANS",
        plan_versiyon=1,
    )
    s.add(kk_odeme)
    s.flush()
    kk_odeme.nakit_avans_taksit_id = int(t.id)
    s.add(
        KrediKartiOdemeTaksit(
            odeme_id=int(kk_odeme.id),
            taksit_no=1,
            vade_tarihi=t.son_odeme_tarihi or t.yansima_tarihi,
            tutar=toplam,
            durum="BEKLIYOR",
            ekstre_kesim_tarihi=t.yansima_tarihi,
            banka_vade_tarihi=t.son_odeme_tarihi,
            plan_versiyon=1,
            aktif=True,
        )
    )
    if _q2(t.faiz) > 0:
        t.faiz_gider_belge_no = _gider_yaz(
            s,
            tarih=tarih,
            tutar=_q2(t.faiz),
            tur="NAKIT_AVANS_FAIZ",
            aciklama=f"Nakit avans faiz {avans.belge_no} T{t.taksit_no}",
            ref=belge,
        )
    if _q2(t.masraf) > 0:
        t.masraf_gider_belge_no = _gider_yaz(
            s,
            tarih=tarih,
            tutar=_q2(t.masraf),
            tur="NAKIT_AVANS_MASRAF",
            aciklama=f"Nakit avans masraf {avans.belge_no} T{t.taksit_no}",
            ref=belge,
        )
    if _q2(t.vergi) > 0:
        t.vergi_gider_belge_no = _gider_yaz(
            s,
            tarih=tarih,
            tutar=_q2(t.vergi),
            tur="NAKIT_AVANS_VERGI",
            aciklama=f"Nakit avans vergi {avans.belge_no} T{t.taksit_no}",
            ref=belge,
        )
    # Karta işlemek kalan anaparayı düşürmez — yalnız gerçek ödeme düşürür
    t.durum = DURUM_KARTA
    t.kk_odeme_id = int(kk_odeme.id)
    t.kk_hareket_belge_no = belge
    t.islem_tarihi = tarih
    t.islem_anahtari = anahtar
    avans.guncelleme = datetime.now()
    _kalan_yenile(s, avans)
    try:
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("nakit_avans_taksit_fisi", t.id, session=s)
    except Exception:
        pass
    s.flush()
    return _taksit_dict(t)


def _taksit_kart_geri_al(s, t: NakitAvansTaksit, avans: NakitAvans) -> None:
    if not t.kk_hareket_belge_no:
        return
    belge = t.kk_hareket_belge_no
    tarih = t.islem_tarihi or date.today()
    tid = int(t.id)
    # Ters kart hareketi
    eski = s.scalars(select(FinansHareketi).where(
        FinansHareketi.belge_no == belge, FinansHareketi.hareket_turu == HAREKET_KART
    )).first()
    if eski:
        iptal_no = FinansService._finans_belge_no(s, "NAI")
        s.add(FinansHareketi(
            hesap_id=int(eski.hesap_id),
            sube_id=eski.sube_id,
            tarih=tarih,
            hareket_turu=HAREKET_KART_IPTAL,
            belge_no=iptal_no,
            tutar=_q2(eski.tutar),
            aciklama=f"İptal/düzeltme {belge}",
        ))
    if t.kk_odeme_id:
        od = s.get(KrediKartiOdeme, int(t.kk_odeme_id))
        if od is not None:
            od.durum = "İPTAL"
            for kt in od.taksitler:
                kt.durum = "PLAN_IPTAL"
                kt.aktif = False
    for belge_g, tur in (
        (t.faiz_gider_belge_no, "faiz"),
        (t.masraf_gider_belge_no, "masraf"),
        (t.vergi_gider_belge_no, "vergi"),
    ):
        if not belge_g:
            continue
        gf = s.scalar(select(GiderFisi).where(GiderFisi.belge_no == belge_g))
        if gf is not None:
            gf.durum = "IPTAL"
    try:
        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("nakit_avans_taksit_iptal", tid, "Nakit avans taksit geri alındı", session=s)
    except Exception:
        pass
    t.faiz_gider_belge_no = None
    t.masraf_gider_belge_no = None
    t.vergi_gider_belge_no = None
    t.kk_odeme_id = None
    t.kk_hareket_belge_no = None
    t.islem_tarihi = None
    t.durum = DURUM_PLAN
    _kalan_yenile(s, avans)
    if avans.durum == "KAPALI" and avans.kalan_anapara > 0:
        avans.durum = "ACIK"


def _taksit_odendi_mi(s, t: NakitAvansTaksit) -> bool:
    """Gerçek ekstre ödemesi var mı? (Karta işlenmiş + KK taksit ODENDI)."""
    if not t.kk_odeme_id:
        return False
    od = s.get(KrediKartiOdeme, int(t.kk_odeme_id))
    if od is None:
        return False
    od_u = (od.durum or "").upper()
    if od_u in ("ODENDI", "ÖDENDİ", "KAPALI"):
        return True
    for kt in od.taksitler or []:
        if not kt.aktif:
            continue
        kd = (kt.durum or "").upper()
        if kd in ("ODENDI", "ÖDENDİ", "ODENMIS", "ÖDENMİŞ"):
            return True
    return False


def _karta_aktarilan_anapara(avans: NakitAvans) -> Decimal:
    return _q2(
        sum(
            (_q2(x.anapara) for x in (avans.taksitler or []) if x.aktif and x.durum == DURUM_KARTA),
            SIFIR,
        )
    )


def _odenen_anapara_toplami(s, avans: NakitAvans) -> Decimal:
    """Yalnız gerçek ödeme/mahsup ile kapanan taksit anaparası."""
    odenen = SIFIR
    for x in avans.taksitler or []:
        if not x.aktif or x.durum == DURUM_IPTAL:
            continue
        if _taksit_odendi_mi(s, x):
            odenen += _q2(x.anapara)
    return _q2(odenen)


def _kalan_yenile(s, avans: NakitAvans) -> None:
    """kalan_anapara = anapara − ödenen anapara (karta aktarım düşürmez)."""
    odenen = _odenen_anapara_toplami(s, avans)
    avans.kalan_anapara = _q2(avans.anapara - odenen)
    if avans.kalan_anapara < 0:
        avans.kalan_anapara = SIFIR
    if avans.kalan_anapara == 0 and avans.durum == "ACIK":
        aktif = [x for x in (avans.taksitler or []) if x.aktif and x.durum != DURUM_IPTAL]
        if aktif and all(_taksit_odendi_mi(s, x) for x in aktif):
            avans.durum = "KAPALI"


def _taksit_dict(t: NakitAvansTaksit) -> dict:
    return {
        "id": int(t.id),
        "avans_id": int(t.avans_id),
        "taksit_no": int(t.taksit_no),
        "yansima_tarihi": t.yansima_tarihi,
        "faiz_valor_tarihi": getattr(t, "faiz_valor_tarihi", None),
        "son_odeme_tarihi": t.son_odeme_tarihi,
        "anapara": _q2(t.anapara),
        "faiz": _q2(t.faiz),
        "masraf": _q2(t.masraf),
        "vergi": _q2(t.vergi),
        "toplam": _q2(t.toplam),
        "durum": t.durum,
        "kk_odeme_id": t.kk_odeme_id,
        "kk_hareket_belge_no": t.kk_hareket_belge_no,
        "faiz_gider_belge_no": t.faiz_gider_belge_no,
        "masraf_gider_belge_no": t.masraf_gider_belge_no,
        "vergi_gider_belge_no": t.vergi_gider_belge_no,
        "islem_anahtari": t.islem_anahtari,
        "aktif": bool(t.aktif),
    }


def _avans_dict(a: NakitAvans) -> dict:
    from sqlalchemy.orm import object_session

    taksitler = [_taksit_dict(t) for t in (a.taksitler or []) if t.aktif or t.durum != DURUM_IPTAL]
    # iptaller de listelensin
    if not taksitler:
        taksitler = [_taksit_dict(t) for t in (a.taksitler or [])]
    kart_adi = ""
    s = object_session(a)
    if s is not None:
        k = s.get(KrediKartiTanimi, int(a.kredi_karti_id))
        kart_adi = (k.kart_adi if k else "") or ""
    karta_akt = _karta_aktarilan_anapara(a)
    odenen_ana = _odenen_anapara_toplami(s, a) if s is not None else SIFIR
    return {
        "id": int(a.id),
        "belge_no": a.belge_no,
        "kart_adi": kart_adi,
        "kredi_karti_id": int(a.kredi_karti_id),
        "banka_karti_id": int(a.banka_karti_id),
        "islem_tarihi": a.islem_tarihi,
        "anapara": _q2(a.anapara),
        "kalan_anapara": _q2(a.kalan_anapara),
        "karta_aktarilan_anapara": karta_akt,
        "odenen_anapara": odenen_ana,
        "net_giris": _q2(a.net_giris),
        "kullandirim_masraf": _q2(a.kullandirim_masraf),
        "kullandirim_vergi": _q2(a.kullandirim_vergi),
        "hedef_hesap_id": int(a.hedef_hesap_id),
        "aylik_faiz_orani": _d(a.aylik_faiz_orani),
        "taksit_sayisi": int(a.taksit_sayisi),
        "cekim_turu": a.cekim_turu,
        "ilk_yansima_tarihi": a.ilk_yansima_tarihi,
        "aciklama": a.aciklama,
        "durum": a.durum,
        "finans_belge_no": a.finans_belge_no,
        "istek_anahtari": a.istek_anahtari,
        "taksitler": sorted(taksitler, key=lambda x: x["taksit_no"]),
        "plan_ozeti": plan_ozeti(
            [{k: t[k] for k in ("anapara", "faiz", "masraf", "vergi", "toplam")} for t in taksitler
             if t.get("durum") != DURUM_IPTAL],
            a.anapara,
        ),
    }
