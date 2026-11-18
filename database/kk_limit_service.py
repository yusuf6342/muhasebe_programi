"""Firma kredi kartı — kullanılan / kullanılabilir limit (tek hesaplama kaynağı).

Kök neden (Enpara örneği): ekrandaki «Kullanılan» yalnız ``KrediKartiOdeme`` /
taksit planından geliyordu; bağlı KK hesabındaki ledger borcu (işletme bakiyesi
−391.794,07) yok sayılıyordu → Kullanılan=0, Kalan=tam limit.

Kural:
* Bağlı hesap varsa: net kullanım = hesap borcu + henüz ledger'da olmayan plan-only borç.
  Aynı yükümlülük çift sayılmaz (belge_no ledger'da varsa plan-only'ye girmez).
* Bağlı hesap yoksa: yalnız plan borcu; banka toplamı karta yüklenmez.
* Eşleşmemiş banka hareketleri ayrı raporlanır; rastgele karta dağıtılmaz.
* Taksitli harcamanın tam tutarı baştan kullanıma girer (plan satırları toplamı).
* Bankadan canlı limit yoksa etiket: «Hesaplanan kullanılabilir limit».
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import (
    FinansHareketi,
    FinansHesabi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _gelecek_nakit_avans_borcu(session, hesap_id: int, *, bugun: date) -> Decimal:
    """``tarih > bugun`` olan KK NAKİT AVANS hareket tutarları (gelecek dönem)."""
    rows = session.execute(
        select(FinansHareketi.tutar, FinansHareketi.hareket_turu).where(
            FinansHareketi.hesap_id == int(hesap_id),
            FinansHareketi.tarih > bugun,
        )
    ).all()
    top = SIFIR
    for tutar, tur in rows:
        tu = (tur or "").strip().upper()
        if tu == "KK NAKİT AVANS":
            top += _d(tutar)
        elif tu in {"KK NAKİT AVANS İPTAL", "KK NAKIT AVANS IPTAL"}:
            top -= _d(tutar)
    return max(SIFIR, _d(top))


def _plan_only_kalan(session, kredi_karti_id: int, bagli_hesap_id: int) -> tuple[Decimal, list[dict]]:
    """Ledger'da belge_no'su olmayan açık planların kalan anaparası (plan-only EVB vb.)."""
    ledger_belge = {
        (b or "").strip()
        for b in session.scalars(
            select(FinansHareketi.belge_no).where(
                FinansHareketi.hesap_id == int(bagli_hesap_id),
                FinansHareketi.belge_no.isnot(None),
            )
        ).all()
        if (b or "").strip()
    }
    odemeler = list(
        session.scalars(
            select(KrediKartiOdeme)
            .where(
                KrediKartiOdeme.kredi_karti_id == int(kredi_karti_id),
                KrediKartiOdeme.durum == "AÇIK",
            )
            .options(selectinload(KrediKartiOdeme.taksitler))
        ).all()
    )
    toplam = SIFIR
    satirlar: list[dict] = []
    for o in odemeler:
        bel = (o.belge_no or "").strip()
        # Eski tek kalem: ana belge ledger'daysa plan zaten tam tutarla sayılmış
        if bel and bel in ledger_belge:
            continue
        kalan = SIFIR
        for t in o.taksitler or []:
            if getattr(t, "aktif", True) is False:
                continue
            durum = (t.durum or "").upper()
            if durum in ("PLAN_IPTAL", "IADE", "ODENDI", "KARTA_ISLENDI"):
                # Karta işlenmiş / ödenmiş taksit ledger'da; plan-only'ye girmez
                continue
            t_bel = (getattr(t, "kk_hareket_belge_no", None) or "").strip()
            if t_bel and t_bel in ledger_belge:
                continue
            odenen = _d(getattr(t, "odenen_tutar", None) or 0)
            kalan += max(SIFIR, _d(t.tutar) - odenen)
        if kalan <= 0:
            continue
        toplam += kalan
        satirlar.append({
            "belge_no": bel,
            "kalan": kalan,
            "kaynak": "plan_only",
        })
    return _d(toplam), satirlar


def _eslesmemis_ozet(session, banka_karti_id: int) -> dict[str, Any]:
    """Hiçbir kart tanımına bağlı olmayan KK hesaplarının net borcu (karta yüklenmez)."""
    from database.finans_service import FinansService

    hesaplar = list(
        session.scalars(
            select(FinansHesabi)
            .where(
                FinansHesabi.banka_karti_id == int(banka_karti_id),
                FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
            )
            .options(selectinload(FinansHesabi.hareketler))
        ).all()
    )
    bagli_idler = {
        int(t.bagli_hesap_id)
        for t in session.scalars(
            select(KrediKartiTanimi).where(
                KrediKartiTanimi.banka_karti_id == int(banka_karti_id),
                KrediKartiTanimi.bagli_hesap_id.isnot(None),
            )
        ).all()
        if t.bagli_hesap_id
    }
    adet = 0
    borc = SIFIR
    fazla = SIFIR
    for h in hesaplar:
        if int(h.id) in bagli_idler:
            continue
        isletme = FinansService.isletme_bakiyesi(h)
        if isletme < 0:
            borc += -isletme
            adet += 1
        elif isletme > 0:
            fazla += isletme
            adet += 1
    return {
        "adet_hesap": adet,
        "borc": _d(borc),
        "fazla_odeme": _d(fazla),
    }


def limit_kullanimi(
    kredi_karti_id: int,
    *,
    tarih: date | None = None,
    session=None,
    plan_veri: dict | None = None,
) -> dict[str, Any]:
    """Tek kart için net limit kullanımı ve hesaplanan kullanılabilir limit.

    ``tarih`` verilirse geçmiş rapor: kullanılan = o güne kadar plan borcu
    (iptal edilen ekstre ödemesi iptal gününe kadar geçerlidir). Bağlı hesap
    ledger bakiyesi yalnız güncel (``tarih is None``) görünümde kullanıma girer.
    """
    from database.finans_service import FinansService
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService, limit_tanimli

    def _hesapla(s) -> dict[str, Any]:
        kart = s.get(KrediKartiTanimi, int(kredi_karti_id))
        if kart is None:
            raise ValueError("Kredi kartı bulunamadı.")
        if plan_veri is None:
            veri = KrediKartiEkstreService.donem_borclari(
                s, tarih=tarih, kart_ids=[int(kredi_karti_id)]
            )[int(kredi_karti_id)]
        else:
            veri = plan_veri
        plan_borc = _d(veri.get("toplam_borc"))
        # Fazla plan ödemesi (negatif toplam_borc) → kullanım 0, fazla ayrı
        plan_kullanim = max(SIFIR, plan_borc)
        plan_fazla = max(SIFIR, -plan_borc)

        limit = _d(getattr(kart, "kart_limiti", None))
        tanimli = limit_tanimli(limit)

        bagli_id = getattr(kart, "bagli_hesap_id", None)
        hesap_borc = SIFIR
        hesap_fazla = SIFIR
        hesap_adi = ""
        plan_only = SIFIR
        plan_only_satirlar: list[dict] = []
        kaynak = "plan"
        uyari = None
        # Tarihli (as-of) görünüm: iptal aralığı ve plan ödemeleri için plan borcu
        tarihli_gorunum = tarih is not None

        # Kalıcı bagli_hesap yoksa: yalnız 1 kart + 1 KK hesabı ise görüntüleme amaçlı
        # geçici eşleme (mali kayıt yazılmaz; çoklu kartta banka toplamı yüklenmez).
        gecici_bagli = False
        if not bagli_id:
            banka_kartlari = list(
                s.scalars(
                    select(KrediKartiTanimi).where(
                        KrediKartiTanimi.banka_karti_id == int(kart.banka_karti_id),
                        KrediKartiTanimi.aktif.is_(True),
                    )
                ).all()
            )
            kk_hesaplar = list(
                s.scalars(
                    select(FinansHesabi)
                    .where(
                        FinansHesabi.banka_karti_id == int(kart.banka_karti_id),
                        FinansHesabi.alt_hesap_turu == "KREDI_KARTI",
                        FinansHesabi.aktif.is_(True),
                    )
                    .options(selectinload(FinansHesabi.hareketler))
                ).all()
            )
            if len(banka_kartlari) == 1 and len(kk_hesaplar) == 1:
                bagli_id = int(kk_hesaplar[0].id)
                gecici_bagli = True

        if bagli_id:
            hesap = s.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(bagli_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            if hesap is not None:
                hesap_adi = hesap.hesap_adi or ""
                isletme = FinansService.isletme_bakiyesi(hesap)
                if isletme < 0:
                    hesap_borc = _d(-isletme)
                elif isletme > 0:
                    hesap_fazla = _d(isletme)
                # Gelecek tarihli nakit avans NAT'ları bugünün kart borcuna / limitine
                # topluca eklenmesin (hareket kayıtlıdır; dönem ilerledikçe girer).
                if not tarihli_gorunum and hesap_borc > 0:
                    gelecek_na = _gelecek_nakit_avans_borcu(
                        s, int(hesap.id), bugun=date.today()
                    )
                    if gelecek_na > 0:
                        hesap_borc = max(SIFIR, _d(hesap_borc - gelecek_na))
                plan_only, plan_only_satirlar = _plan_only_kalan(
                    s, int(kart.id), int(bagli_id)
                )
                if tarihli_gorunum:
                    # Geçmiş gün: ledger iptal tarihini bilmez; plan as-of kullan
                    kullanilan = plan_kullanim
                    kaynak = "plan_asof"
                else:
                    kullanilan = _d(hesap_borc + plan_only)
                    if plan_only > 0:
                        kaynak = "hesap+plan_only"
                    elif gecici_bagli:
                        kaynak = "tek_kart_tek_hesap"
                        uyari = (
                            "Kart–hesap kalıcı eşlemesi yok; bankada tek kart/tek KK hesabı "
                            "olduğu için limit bu hesaptan hesaplandı (yazılmadı)."
                        )
                    else:
                        kaynak = "bagli_hesap"
            else:
                kullanilan = plan_kullanim
                uyari = "Bağlı KK hesabı bulunamadı; yalnız plan borcu kullanıldı."
        else:
            kullanilan = plan_kullanim
            kaynak = "plan_asof" if tarihli_gorunum else "plan"
            uyari = (
                "Kartın bağlı KK hesabı yok; kullanılan yalnız plan/taksit borcudur. "
                "Banka KK toplamı bu karta yüklenmez."
            )

        fazla = _d(
            (plan_fazla if tarihli_gorunum or not bagli_id else SIFIR)
            + (SIFIR if tarihli_gorunum else hesap_fazla)
        )
        # Bağlı hesapta fazla ödeme varken plan_borc ayrıca pozitifse zaten hesap_borc=0
        if bagli_id and hesap_fazla > 0 and plan_kullanim > hesap_borc + plan_only:
            # Nadir: plan borcu ledger alacağından büyük — plan-only zaten eklendi
            pass

        eslesmemis = _eslesmemis_ozet(s, int(kart.banka_karti_id))
        if eslesmemis["borc"] > 0 or eslesmemis["adet_hesap"] > 0:
            es_uyari = (
                f"Eşleşmemiş KK hesabı: {eslesmemis['adet_hesap']} · "
                f"borç {_d(eslesmemis['borc'])} (karta dağıtılmadı)."
            )
            uyari = f"{uyari} {es_uyari}".strip() if uyari else es_uyari

        kullanilabilir = _d(limit - kullanilan) if tanimli else None
        asim = _d(kullanilan - limit) if tanimli and kullanilan > limit else SIFIR
        yuzde = None
        if tanimli and limit > 0:
            yuzde = float((kullanilan / limit * Decimal("100")).quantize(Decimal("0.1")))

        return {
            "kredi_karti_id": int(kart.id),
            "kart_adi": kart.kart_adi or "",
            "para_birimi": (getattr(kart, "para_birimi", None) or "TRY").upper(),
            "limit": limit if tanimli else None,
            "limit_tanimli": tanimli,
            "kullanilan": kullanilan,
            "kullanilabilir": kullanilabilir,
            "hesaplanan_kullanilabilir": kullanilabilir,  # banka canlı limiti değil
            "limit_asimi": asim if asim > 0 else SIFIR,
            "fazla_odeme": fazla,
            "kullanim_yuzde": yuzde,
            "plan_borc": plan_kullanim,
            "hesap_borc": hesap_borc if bagli_id else None,
            "plan_only_borc": plan_only if not tarihli_gorunum else SIFIR,
            "plan_only_satirlar": plan_only_satirlar if not tarihli_gorunum else [],
            "bagli_hesap_id": int(bagli_id) if bagli_id else None,
            "hesap_adi": hesap_adi,
            "kaynak": kaynak,
            "uyari": uyari,
            "eslesmemis": eslesmemis,
            "banka_dogrulanmis_limit": None,  # canlı banka limiti yok
            "etiket_kullanilabilir": (
                "Hesaplanan kullanılabilir limit"
                if tanimli
                else "Limit tanımlanmamış"
            ),
            "guncel": not tarihli_gorunum,
            "tarih_filtre_etkisiz": not tarihli_gorunum,
        }

    if session is not None:
        return _hesapla(session)
    KrediKartiEkstreService.schema_hazirla()
    with get_session() as s:
        return _hesapla(s)


def borc_ozetine_limit_kat(ozet: dict, limit_oz: dict) -> dict:
    """``kart_borc_ozeti`` sözlüğüne limit alanlarını (tek kaynak) işler."""
    ozet = dict(ozet)
    ozet["kullanilan"] = limit_oz["kullanilan"]
    ozet["kullanilabilir"] = limit_oz["kullanilabilir"]
    ozet["limit"] = limit_oz["limit"]
    ozet["limit_tanimli"] = limit_oz["limit_tanimli"]
    ozet["limit_asimi"] = limit_oz.get("limit_asimi") or SIFIR
    ozet["fazla_odeme"] = limit_oz.get("fazla_odeme") or SIFIR
    ozet["kullanim_yuzde"] = limit_oz.get("kullanim_yuzde")
    ozet["hesaplanan_kullanilabilir"] = limit_oz.get("hesaplanan_kullanilabilir")
    ozet["limit_kaynak"] = limit_oz.get("kaynak")
    ozet["limit_uyari"] = limit_oz.get("uyari")
    ozet["plan_borc"] = limit_oz.get("plan_borc")
    ozet["hesap_borc"] = limit_oz.get("hesap_borc")
    ozet["plan_only_borc"] = limit_oz.get("plan_only_borc")
    ozet["etiket_kullanilabilir"] = limit_oz.get("etiket_kullanilabilir")
    # Toplam kart borcu gösterimi: limit kullanımı ile tutarlı (ledger+plan_only)
    ozet["toplam_borc"] = limit_oz["kullanilan"]
    return ozet
