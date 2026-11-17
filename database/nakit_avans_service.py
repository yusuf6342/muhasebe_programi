"""Firma kredi kartı nakit avans — tek çekim / taksitli plan, karta yansıtma, düzeltme.

Kurallar
--------
* Kullandırımda hesaba geçen net tutar bir kez banka/kasa **NAKİT AVANS GİRİŞ** hareketidir.
  Anapara ``kalan_anapara`` ile izlenir; kullandırım masraf/vergisi ayrı gider fişidir.
* Taksit karta işlenince kart hesabına bileşenler toplamı tek **KK NAKİT AVANS** hareketi yazılır;
  anapara avans borcundan düşülür; faiz/masraf/vergi ayrı gider fişleridir. Ekstre takibi için
  ``KrediKartiOdeme`` (kaynak_turu=NAKIT_AVANS) + tek taksit satırı oluşur.
* ``islem_anahtari`` / ``istek_anahtari`` ile iki terminal aynı taksiti bir kez işler.
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
) -> list[dict]:
    """Aylık faiz oranıyla anüite planı; yansıma / faiz valörü kullandırımdan türetilir.

    * Taksit i karta yansıma = kullandırım + (i−1) ay (1. taksit = kullandırım günü)
    * Taksit i faiz valörü = kullandırım + i ay
    * Faiz = dönemin kalan anaparası × aylık oran (anüite / tek çekim)
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

    # Anüite: her dönem kalan anapara × oran; sabit taksit (anapara+faiz)
    if r == 0 or n == 1:
        ana_l = FinansService._tutar_bol(ana, n)
        faiz_l = [SIFIR] * n
        if n == 1 and r != 0:
            faiz_l = [_q2(ana * r)]
    else:
        bir_arti = (Decimal("1") + r) ** n
        pmt = _q2(ana * r * bir_arti / (bir_arti - Decimal("1")))
        kalan = ana
        ana_l, faiz_l = [], []
        for i in range(1, n + 1):
            fz = _q2(kalan * r)
            if i == n:
                ap = kalan
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

    plan = []
    for i in range(n):
        yan, valor, sod = _tarihler(i + 1)
        ap, fz, ms, vg = ana_l[i], faiz_l[i], masraf_l[i], vergi_l[i]
        plan.append({
            "taksit_no": i + 1,
            "yansima_tarihi": yan,
            "faiz_valor_tarihi": valor,
            "son_odeme_tarihi": sod,
            "anapara": ap,
            "faiz": fz,
            "masraf": ms,
            "vergi": vg,
            "toplam": _q2(ap + fz + ms + vg),
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
        "net_giris": ana,  # kullandırım masrafı ayrı düşülür
        "adet": len(plan),
    }


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
        kullandirim_masraf=0,
        kullandirim_vergi=0,
        plan_masraf=0,
        plan_vergi=0,
        manuel_plan: list[dict] | None = None,
        istek_anahtari: str | None = None,
        sube_id: int | None = None,
    ) -> dict:
        """Avans + plan + hesaba net giriş + 1. taksit karta (tek transaction)."""
        yazma_zorunlu(*YAZMA)
        schema_hazirla()
        ana = _kurus(anapara, "Anapara")
        k_masraf = _kurus(kullandirim_masraf or 0, "Kullandırım masrafı")
        k_vergi = _kurus(kullandirim_vergi or 0, "Kullandırım vergisi")
        net = _q2(ana - k_masraf - k_vergi)
        if net <= 0:
            raise ValueError("Hesaba geçen net tutar pozitif olmalıdır (anapara − masraf − vergi).")
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
                raise ValueError("Hedef banka/kasa hesabı bulunamadı.")
            tur_h = (hesap.hesap_turu or "").upper()
            alt = (hesap.alt_hesap_turu or "").upper()
            if tur_h not in ("KASA", "BANKA") or alt in ("KREDI_KARTI", "KREDILER", "POS"):
                raise ValueError("Hedef hesap kasa, mevduat veya KMH olmalıdır.")
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
            ilk_taksit: NakitAvansTaksit | None = None
            for sat in plan:
                t = NakitAvansTaksit(
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
                s.add(t)
                if int(sat["taksit_no"]) == 1:
                    ilk_taksit = t
            s.flush()
            # Hesaba net giriş
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
            if k_masraf > 0:
                _gider_yaz(s, tarih=islem_tarihi, tutar=k_masraf, tur="NAKIT_AVANS_MASRAF",
                           aciklama=f"Nakit avans kullandırım masrafı {belge}", ref=belge)
            if k_vergi > 0:
                _gider_yaz(s, tarih=islem_tarihi, tutar=k_vergi, tur="NAKIT_AVANS_VERGI",
                           aciklama=f"Nakit avans kullandırım vergisi {belge}", ref=belge)
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
            # 1. taksit: kullandırım günü tek kart hareketi (aynı transaction)
            if ilk_taksit is not None:
                _taksit_karta_isle_oturum(
                    s,
                    ilk_taksit,
                    islem_tarihi=islem_tarihi,
                    islem_anahtari=f"na-kayit-t1-{avans.id}",
                    sube_id=sube_id,
                )
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
        """Yansıma tarihi gelmiş planlanan taksitleri karta işler (idempotent)."""
        bugun = bugun or date.today()
        schema_hazirla()
        sonuc = []
        with get_session() as s:
            q = (
                select(NakitAvansTaksit)
                .join(NakitAvans)
                .where(
                    NakitAvansTaksit.durum == DURUM_PLAN,
                    NakitAvansTaksit.aktif.is_(True),
                    NakitAvansTaksit.yansima_tarihi <= bugun,
                    NakitAvans.durum == "ACIK",
                )
            )
            if kredi_karti_id:
                q = q.where(NakitAvans.kredi_karti_id == int(kredi_karti_id))
            ids = [int(t.id) for t in s.scalars(q).all()]
        for tid in ids:
            try:
                sonuc.append(NakitAvansService.taksit_karta_isle(
                    tid, islem_tarihi=bugun, islem_anahtari=f"na-auto-{tid}"
                ))
            except Exception as exc:
                sonuc.append({"taksit_id": tid, "hata": str(exc)})
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
    belge = FinansService._finans_belge_no(s, "GDF")
    s.add(GiderFisi(
        belge_no=belge,
        tarih=tarih,
        tutar=tutar,
        gider_turu=tur,
        aciklama=aciklama,
        durum="AÇIK",
        bagli_belge_no=ref,
    ))
    s.flush()  # sonraki gider aynı belge_no sayacını görsün
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
    avans.kalan_anapara = _q2(avans.kalan_anapara - _q2(t.anapara))
    if avans.kalan_anapara < 0:
        avans.kalan_anapara = SIFIR
    t.durum = DURUM_KARTA
    t.kk_odeme_id = int(kk_odeme.id)
    t.kk_hareket_belge_no = belge
    t.islem_tarihi = tarih
    t.islem_anahtari = anahtar
    avans.guncelleme = datetime.now()
    if avans.kalan_anapara == 0 and all(
        x.durum in (DURUM_KARTA, DURUM_IPTAL) for x in avans.taksitler if x.aktif
    ):
        avans.durum = "KAPALI"
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
    avans.kalan_anapara = _q2(avans.kalan_anapara + _q2(t.anapara))
    if avans.durum == "KAPALI":
        avans.durum = "ACIK"
    t.faiz_gider_belge_no = None
    t.masraf_gider_belge_no = None
    t.vergi_gider_belge_no = None
    t.kk_odeme_id = None
    t.kk_hareket_belge_no = None
    t.islem_tarihi = None
    t.durum = DURUM_PLAN


def _kalan_yenile(s, avans: NakitAvans) -> None:
    islenen = SIFIR
    for x in avans.taksitler:
        if x.aktif and x.durum == DURUM_KARTA:
            islenen += _q2(x.anapara)
    avans.kalan_anapara = _q2(avans.anapara - islenen)
    if avans.kalan_anapara < 0:
        avans.kalan_anapara = SIFIR


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
    taksitler = [_taksit_dict(t) for t in (a.taksitler or []) if t.aktif or t.durum != DURUM_IPTAL]
    # iptaller de listelensin
    if not taksitler:
        taksitler = [_taksit_dict(t) for t in (a.taksitler or [])]
    return {
        "id": int(a.id),
        "belge_no": a.belge_no,
        "kredi_karti_id": int(a.kredi_karti_id),
        "banka_karti_id": int(a.banka_karti_id),
        "islem_tarihi": a.islem_tarihi,
        "anapara": _q2(a.anapara),
        "kalan_anapara": _q2(a.kalan_anapara),
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
        "taksitler": sorted(taksitler, key=lambda x: x["taksit_no"]),
        "plan_ozeti": plan_ozeti(
            [{k: t[k] for k in ("anapara", "faiz", "masraf", "vergi", "toplam")} for t in taksitler
             if t.get("durum") != DURUM_IPTAL],
            a.anapara,
        ),
    }
