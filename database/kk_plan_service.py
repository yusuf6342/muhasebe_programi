"""Firma kredi kartı iç taksit planı düzenleme ve sürümleme."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.database import engine, get_session
from database.finans_service import FinansService
from database.models.finans import (
    KK_MAX_TAKSIT,
    KK_STANDART_MAX_TAKSIT,
    KrediKartiOdeme,
    KrediKartiOdemePlanVersiyon,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def schema_hazirla(bind=None) -> None:
    eng = bind
    if eng is None:
        eng = engine
    if eng is None:
        return
    try:
        KrediKartiOdemePlanVersiyon.__table__.create(eng, checkfirst=True)
        insp = inspect(eng)
    except Exception:
        return
    if insp.has_table("kredi_karti_odemeleri"):
        sutun = {c["name"] for c in insp.get_columns("kredi_karti_odemeleri")}
        if "plan_versiyon" not in sutun:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        'ALTER TABLE "kredi_karti_odemeleri" '
                        'ADD COLUMN "plan_versiyon" INTEGER DEFAULT 1 NOT NULL'
                    )
                )
    if insp.has_table("kredi_karti_odeme_taksitleri"):
        sutun = {c["name"] for c in insp.get_columns("kredi_karti_odeme_taksitleri")}
        ekstra = {
            "banka_vade_tarihi": "DATE",
            "odenen_tutar": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
            "plan_versiyon": "INTEGER DEFAULT 1 NOT NULL",
            "aktif": "BOOLEAN DEFAULT TRUE NOT NULL",
        }
        eklenecek = {a: t for a, t in ekstra.items() if a not in sutun}
        if eklenecek:
            with eng.begin() as conn:
                for alan, tip in eklenecek.items():
                    conn.execute(
                        text(
                            f'ALTER TABLE "kredi_karti_odeme_taksitleri" '
                            f'ADD COLUMN "{alan}" {tip}'
                        )
                    )
    if insp.has_table("kredi_karti_tanimlari"):
        sutun = {c["name"] for c in insp.get_columns("kredi_karti_tanimlari")}
        ekstra = {
            "odeme_vade_yontemi": "VARCHAR(20)",
            "banka_urun_turu": "VARCHAR(20)",
            "asgari_oran_yuzde": "NUMERIC(8, 4)",
            "asgari_kaynak": "VARCHAR(120)",
            "asgari_gecerlilik": "DATE",
            "otomatik_faiz_tahakkuku": "BOOLEAN DEFAULT FALSE NOT NULL",
        }
        eklenecek = {a: t for a, t in ekstra.items() if a not in sutun}
        if eklenecek:
            with eng.begin() as conn:
                for alan, tip in eklenecek.items():
                    conn.execute(
                        text(f'ALTER TABLE "kredi_karti_tanimlari" ADD COLUMN "{alan}" {tip}')
                    )


def _taksit_aktif(t: KrediKartiOdemeTaksit) -> bool:
    if getattr(t, "aktif", True) is False:
        return False
    durum = (t.durum or "").upper()
    return durum not in ("PLAN_IPTAL", "IADE")


def _taksit_odenen(t: KrediKartiOdemeTaksit) -> Decimal:
    durum = (t.durum or "").upper()
    if durum == "ODENDI":
        return _d(t.tutar)
    odenen = _d(getattr(t, "odenen_tutar", None) or 0)
    if odenen > 0:
        return min(odenen, _d(t.tutar))
    return SIFIR


def _taksit_kalan(t: KrediKartiOdemeTaksit) -> Decimal:
    return max(SIFIR, _d(t.tutar) - _taksit_odenen(t))


def plan_durum_ozeti(odeme_id: int) -> dict[str, Any]:
    """Seçili harcama/plan için eski plan + kalan anapara özeti."""
    with get_session() as session:
        schema_hazirla(bind=session.get_bind())
        o = session.scalar(
            select(KrediKartiOdeme)
            .where(KrediKartiOdeme.id == int(odeme_id))
            .options(
                selectinload(KrediKartiOdeme.taksitler),
                selectinload(KrediKartiOdeme.kredi_karti),
            )
        )
        if not o or (o.durum or "").upper() not in ("AÇIK", "ACIK"):
            raise ValueError("Açık kart harcama/plan kaydı bulunamadı.")
        versiyon = int(getattr(o, "plan_versiyon", None) or 1)
        aktif_satirlar = [t for t in (o.taksitler or []) if _taksit_aktif(t)]
        odenen_toplam = sum((_taksit_odenen(t) for t in aktif_satirlar), SIFIR)
        kalan_anapara = sum((_taksit_kalan(t) for t in aktif_satirlar), SIFIR)
        # Ana tutar ile sapma: ödenen+kalan ana borcu temsil eder
        ana = _d(o.tutar)
        if odenen_toplam + kalan_anapara != ana:
            # Kısmi satır / kuruş: kalanı ana − ödenen ile hizala (çift sayım yok)
            kalan_anapara = max(SIFIR, ana - odenen_toplam)
        satirlar = []
        for t in sorted(aktif_satirlar, key=lambda x: (x.taksit_no, x.id)):
            satirlar.append({
                "taksit_id": int(t.id),
                "taksit_no": int(t.taksit_no),
                "vade_tarihi": t.vade_tarihi,
                "banka_vade_tarihi": getattr(t, "banka_vade_tarihi", None),
                "ekstre_kesim_tarihi": t.ekstre_kesim_tarihi,
                "tutar": _d(t.tutar),
                "odenen": _taksit_odenen(t),
                "kalan": _taksit_kalan(t),
                "durum": t.durum,
                "kilitli": _taksit_odenen(t) > 0 and _taksit_kalan(t) <= 0,
                "plan_versiyon": int(getattr(t, "plan_versiyon", None) or versiyon),
            })
        kk = o.kredi_karti
        return {
            "odeme_id": int(o.id),
            "belge_no": o.belge_no,
            "tarih": o.tarih,
            "tutar": ana,
            "cekim_turu": o.cekim_turu,
            "taksit_sayisi": int(o.taksit_sayisi or 1),
            "plan_versiyon": versiyon,
            "odenen_toplam": odenen_toplam,
            "kalan_anapara": kalan_anapara,
            "tamamen_odendi": kalan_anapara <= 0,
            "aciklama": o.aciklama or "",
            "kredi_karti_id": int(o.kredi_karti_id),
            "kart_adi": kk.kart_adi if kk else "",
            "satirlar": satirlar,
        }


def plan_onizleme(
    kalan_anapara: Decimal | str | int | float,
    yeni_kalan_taksit_sayisi: int,
    yeni_baslangic_vade: date,
    *,
    kart=None,
    cekim_tarihi: date | None = None,
    manuel_tutarlar: list | None = None,
) -> list[dict]:
    """Kalan anapara için yeni iç plan önizlemesi (5. bölüm takvim kuralı)."""
    n = int(yeni_kalan_taksit_sayisi)
    if n < 1 or n > KK_STANDART_MAX_TAKSIT:
        raise ValueError(f"Yeni KALAN taksit sayısı 1-{KK_STANDART_MAX_TAKSIT} arasında olmalıdır.")
    kalan = _d(kalan_anapara)
    if kalan <= 0:
        raise ValueError("Kalan borç yok; yeni plan kurulamaz.")
    if manuel_tutarlar is not None:
        if len(manuel_tutarlar) != n:
            raise ValueError("Manuel tutar satır sayısı yeni kalan taksit sayısına eşit olmalıdır.")
        plan = []
        biriken = SIFIR
        for i, ham in enumerate(manuel_tutarlar, start=1):
            tut = _d(ham)
            if tut <= 0:
                raise ValueError("Taksit satır tutarı sıfır/negatif olamaz.")
            if i == n:
                tut = kalan - biriken
            else:
                biriken += tut
            if tut <= 0:
                raise ValueError("Kalan kuruş dağılımı geçersiz; tutarları düzeltin.")
            vade = FinansService._ay_ekle(yeni_baslangic_vade, i - 1)
            banka = FinansService.kk_banka_vade_oner(
                kart, cekim_tarihi or yeni_baslangic_vade, i
            )
            plan.append({
                "taksit_no": i,
                "vade_tarihi": vade,
                "tutar": tut,
                "banka_vade_tarihi": banka,
                "ekstre_kesim_tarihi": None,
            })
        toplam = sum((s["tutar"] for s in plan), SIFIR)
        if toplam != kalan:
            raise ValueError(
                f"Yeni plan toplamı ({toplam}) kalan anaparaya ({kalan}) eşit olmalıdır."
            )
        return plan
    return FinansService.kk_taksit_plani(
        cekim_tarihi or yeni_baslangic_vade,
        n,
        kalan,
        ilk_taksit_tarihi=yeni_baslangic_vade,
        kart=kart,
    )


def plani_duzenle(
    odeme_id: int,
    *,
    yeni_kalan_taksit_sayisi: int,
    yeni_baslangic_vade: date,
    aciklama: str,
    manuel_tutarlar: list | None = None,
    beklenen_versiyon: int | None = None,
    kullanici: str | None = None,
) -> dict[str, Any]:
    """Kalan ödenmemiş anapara için yeni plan sürümü.

    Ödenmiş satırlar kilitli kalır. Yeni harcama/gider üretmez.
    ``beklenen_versiyon`` ile eşzamanlı düzenleme korunur.
    """
    from database.access import yazma_zorunlu

    yazma_zorunlu("finans_duzenleme")
    acik = (aciklama or "").strip()
    if not acik:
        raise ValueError("Değişiklik açıklaması zorunludur.")
    if not isinstance(yeni_baslangic_vade, date):
        raise ValueError("Yeni başlangıç vadesi geçerli bir tarih olmalıdır.")

    with get_session() as session:
        schema_hazirla(bind=session.get_bind())
        try:
            o = session.scalar(
                select(KrediKartiOdeme)
                .where(KrediKartiOdeme.id == int(odeme_id))
                .options(
                    selectinload(KrediKartiOdeme.taksitler),
                    selectinload(KrediKartiOdeme.kredi_karti),
                )
                .with_for_update()
            )
        except Exception:
            # SQLite test ortamı vb. — kilitsiz oku
            o = session.scalar(
                select(KrediKartiOdeme)
                .where(KrediKartiOdeme.id == int(odeme_id))
                .options(
                    selectinload(KrediKartiOdeme.taksitler),
                    selectinload(KrediKartiOdeme.kredi_karti),
                )
            )
        if not o or (o.durum or "").upper() not in ("AÇIK", "ACIK"):
            raise ValueError("Açık kart harcama/plan kaydı bulunamadı.")
        mevcut_v = int(getattr(o, "plan_versiyon", None) or 1)
        if beklenen_versiyon is not None and int(beklenen_versiyon) != mevcut_v:
            raise ValueError(
                "Plan başka bir kullanıcı/oturum tarafından değiştirilmiş. "
                "Listeyi yenileyip tekrar deneyin."
            )
        aktif = [t for t in (o.taksitler or []) if _taksit_aktif(t)]
        odenen_toplam = sum((_taksit_odenen(t) for t in aktif), SIFIR)
        kalan = max(SIFIR, _d(o.tutar) - odenen_toplam)
        if kalan <= 0:
            raise ValueError("Kalan borç yok; tamamen ödenmiş plan yeniden borçlandırılamaz.")

        kart = o.kredi_karti or session.get(KrediKartiTanimi, int(o.kredi_karti_id))
        yeni_plan = plan_onizleme(
            kalan,
            yeni_kalan_taksit_sayisi,
            yeni_baslangic_vade,
            kart=kart,
            cekim_tarihi=o.tarih,
            manuel_tutarlar=manuel_tutarlar,
        )

        # Eski ödenmemiş satırları pasife al (ödenen kilitli)
        eski_snapshot = []
        for t in aktif:
            eski_snapshot.append({
                "taksit_no": t.taksit_no,
                "vade_tarihi": t.vade_tarihi.isoformat() if t.vade_tarihi else None,
                "tutar": str(_d(t.tutar)),
                "odenen": str(_taksit_odenen(t)),
                "kalan": str(_taksit_kalan(t)),
                "durum": t.durum,
            })
            if _taksit_kalan(t) <= 0:
                # Tam ödenmiş — kilitli
                continue
            odenen = _taksit_odenen(t)
            if odenen > 0:
                # Kısmi: ödenen payı koru, kalanı yeni plana taşı (satırı kapat)
                t.tutar = odenen
                t.odenen_tutar = odenen
                t.durum = "ODENDI"
                if hasattr(t, "aktif"):
                    t.aktif = True
            else:
                t.durum = "PLAN_IPTAL"
                if hasattr(t, "aktif"):
                    t.aktif = False

        yeni_v = mevcut_v + 1
        for satir in yeni_plan:
            session.add(
                KrediKartiOdemeTaksit(
                    odeme_id=o.id,
                    taksit_no=int(satir["taksit_no"]),
                    vade_tarihi=satir["vade_tarihi"],
                    tutar=_d(satir["tutar"]),
                    durum="BEKLIYOR",
                    ekstre_kesim_tarihi=satir.get("ekstre_kesim_tarihi"),
                    banka_vade_tarihi=satir.get("banka_vade_tarihi"),
                    odenen_tutar=SIFIR,
                    plan_versiyon=yeni_v,
                    aktif=True,
                )
            )

        # Önceki sürüm kayıtlarını pasife çek
        for eski in session.scalars(
            select(KrediKartiOdemePlanVersiyon).where(
                KrediKartiOdemePlanVersiyon.odeme_id == o.id,
                KrediKartiOdemePlanVersiyon.aktif.is_(True),
            )
        ).all():
            eski.aktif = False

        session.add(
            KrediKartiOdemePlanVersiyon(
                odeme_id=o.id,
                versiyon=yeni_v,
                plan_json=json.dumps(
                    {
                        "eski": eski_snapshot,
                        "yeni": [
                            {
                                "taksit_no": s["taksit_no"],
                                "vade_tarihi": s["vade_tarihi"].isoformat(),
                                "tutar": str(_d(s["tutar"])),
                                "banka_vade_tarihi": (
                                    s["banka_vade_tarihi"].isoformat()
                                    if s.get("banka_vade_tarihi")
                                    else None
                                ),
                            }
                            for s in yeni_plan
                        ],
                        "kalan_anapara": str(kalan),
                        "odenen_toplam": str(odenen_toplam),
                    },
                    ensure_ascii=False,
                ),
                aktif=True,
                aciklama=acik,
                kullanici=(kullanici or "")[:120] or None,
                created_at=datetime.now(),
            )
        )
        o.plan_versiyon = yeni_v
        session.flush()
        # Etkin satır sayısı = kilitli ödenen + yeni kalan plan
        etkin = [
            t
            for t in (o.taksitler or [])
            if _taksit_aktif(t) and (t.durum or "").upper() != "PLAN_IPTAL"
        ]
        o.taksit_sayisi = len(etkin) if etkin else int(yeni_kalan_taksit_sayisi)
        o.vade_tarihi = yeni_plan[0]["vade_tarihi"]
        if o.aciklama:
            o.aciklama = f"{o.aciklama} | Plan v{yeni_v}: {acik}"[:500]
        else:
            o.aciklama = f"Plan v{yeni_v}: {acik}"[:500]
        session.flush()
        return {
            "odeme_id": int(o.id),
            "belge_no": o.belge_no,
            "plan_versiyon": yeni_v,
            "kalan_anapara": kalan,
            "odenen_toplam": odenen_toplam,
            "yeni_plan": yeni_plan,
            "ic_plan": True,
        }


def cvv_temizle(*, kart_id: int | None = None) -> int:
    """Mevcut CVV değerlerini mali kayıtlardan bağımsız temizler; değeri loglamaz."""
    schema_hazirla()
    with get_session() as session:
        q = select(KrediKartiTanimi)
        if kart_id is not None:
            q = q.where(KrediKartiTanimi.id == int(kart_id))
        n = 0
        for kart in session.scalars(q).all():
            if getattr(kart, "guvenlik_kodu", None):
                kart.guvenlik_kodu = None
                n += 1
        return n
