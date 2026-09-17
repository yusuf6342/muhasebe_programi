"""Kredi kartı ekstre hesaplama ve ödeme — Aylara Göre Ödeme Durumu kaynağı.

Her kart için hesap kesim gününe göre dönem belirlenir; harcamalar tek ekstre
borcuna toplanır ve son ödeme tarihinde tek satır olarak raporlanır.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu, yetki_var
from database.database import get_session
from database.models.finans import (
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)

SIFIR = Decimal("0.00")
KURUS = Decimal("0.01")

DURUM_KESILMEMIS = "KESILMEMIS"
DURUM_KESILMIS = "KESILMIS"
DURUM_KISMI = "KISMI"
DURUM_ODENDI = "ODENDI"
DURUM_GECIKMIS = "GECIKMIS"
DURUM_FAZLA = "FAZLA"

KAYNAK_KK_EKSTRE = "KREDI_KARTI_EKSTRE"


def _d(val, minimum=None) -> Decimal:
    try:
        t = Decimal(str(val if val is not None else 0)).quantize(KURUS, rounding=ROUND_HALF_UP)
    except Exception:
        t = SIFIR
    if minimum is not None and t < minimum:
        return Decimal(str(minimum)).quantize(KURUS, rounding=ROUND_HALF_UP)
    return t


def ay_gunu(yil: int, ay: int, gun: int) -> date:
    """Ayda olmayan gün → ayın son günü (28/29/30/31)."""
    son = calendar.monthrange(int(yil), int(ay))[1]
    return date(int(yil), int(ay), min(max(int(gun), 1), son))


def _ay_kaydir(yil: int, ay: int, n: int) -> tuple[int, int]:
    idx = (yil * 12 + (ay - 1)) + n
    return idx // 12, idx % 12 + 1


class KrediKartiEkstreService:
    """Merkezi ekstre dönem / toplam / ödeme servisi."""

    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text
        from database.database import engine
        import database.models.finans  # noqa: F401

        if engine is None:
            return
        KrediKartiEkstre.__table__.create(engine, checkfirst=True)
        KrediKartiEkstreOdeme.__table__.create(engine, checkfirst=True)
        insp = inspect(engine)
        if not insp.has_table("kredi_karti_tanimlari"):
            return
        mevcut = {c["name"] for c in insp.get_columns("kredi_karti_tanimlari")}
        ekstra = {
            "kesimden_sonra_odeme_gun": "INTEGER",
            "para_birimi": "VARCHAR(10)",
            "bagli_hesap_id": "INTEGER",
            "odeme_hesap_id": "INTEGER",
            "tatil_odeme_kurali": "VARCHAR(20)",
        }
        eksik = {a: t for a, t in ekstra.items() if a not in mevcut}
        if not eksik:
            return
        with engine.begin() as conn:
            for alan, tip in eksik.items():
                conn.execute(text(f'ALTER TABLE "kredi_karti_tanimlari" ADD COLUMN "{alan}" {tip}'))

    @staticmethod
    def kart_gunleri(kart: KrediKartiTanimi | dict) -> tuple[int, int]:
        if isinstance(kart, dict):
            kesim = int(kart.get("hesap_kesim_gunu") or 1)
            odeme = int(kart.get("son_odeme_gunu") or kesim)
            sonra = kart.get("kesimden_sonra_odeme_gun")
        else:
            kesim = int(getattr(kart, "hesap_kesim_gunu", None) or 1)
            odeme = int(getattr(kart, "son_odeme_gunu", None) or kesim)
            sonra = getattr(kart, "kesimden_sonra_odeme_gun", None)
        kesim = max(1, min(31, kesim))
        if sonra is not None and str(sonra).strip() != "":
            try:
                # Kesimden N gün sonra ödeme — odeme günü olarak kullanılmaz, tarih hesabında
                pass
            except Exception:
                pass
        odeme = max(1, min(31, odeme))
        return kesim, odeme

    @staticmethod
    def son_odeme_hesapla(kesim_tarihi: date, kart: KrediKartiTanimi | dict) -> date:
        kesim_gunu, odeme_gunu = KrediKartiEkstreService.kart_gunleri(kart)
        sonra = None
        if isinstance(kart, dict):
            sonra = kart.get("kesimden_sonra_odeme_gun")
        else:
            sonra = getattr(kart, "kesimden_sonra_odeme_gun", None)
        if sonra is not None and str(sonra).strip() != "":
            try:
                return kesim_tarihi + timedelta(days=int(sonra))
            except (TypeError, ValueError):
                pass
        if odeme_gunu >= kesim_gunu:
            return ay_gunu(kesim_tarihi.year, kesim_tarihi.month, odeme_gunu)
        y, a = _ay_kaydir(kesim_tarihi.year, kesim_tarihi.month, 1)
        return ay_gunu(y, a, odeme_gunu)

    @staticmethod
    def donem_bilgisi(
        islem_tarihi: date,
        kart: KrediKartiTanimi | dict,
    ) -> dict[str, date]:
        """İşlem tarihinin dahil olduğu ekstre dönemi.

        Kesim günü döneme DAHİL. Dönem: (önceki_kesim+1) .. kesim
        """
        kesim_gunu, _odeme_gunu = KrediKartiEkstreService.kart_gunleri(kart)
        y, m = islem_tarihi.year, islem_tarihi.month
        for _ in range(0, 14):
            kesim = ay_gunu(y, m, kesim_gunu)
            oy, oa = _ay_kaydir(y, m, -1)
            onceki = ay_gunu(oy, oa, kesim_gunu)
            donem_bas = onceki + timedelta(days=1)
            donem_son = kesim
            if donem_bas <= islem_tarihi <= donem_son:
                return {
                    "kesim_tarihi": kesim,
                    "donem_baslangic": donem_bas,
                    "donem_bitis": donem_son,
                    "son_odeme_tarihi": KrediKartiEkstreService.son_odeme_hesapla(kesim, kart),
                }
            y, m = _ay_kaydir(y, m, 1)
        # yedek: işlem ayı kesimi
        kesim = ay_gunu(islem_tarihi.year, islem_tarihi.month, kesim_gunu)
        oy, oa = _ay_kaydir(islem_tarihi.year, islem_tarihi.month, -1)
        onceki = ay_gunu(oy, oa, kesim_gunu)
        return {
            "kesim_tarihi": kesim,
            "donem_baslangic": onceki + timedelta(days=1),
            "donem_bitis": kesim,
            "son_odeme_tarihi": KrediKartiEkstreService.son_odeme_hesapla(kesim, kart),
        }

    @staticmethod
    def taksit_donem_bilgisi(
        cekim_tarihi: date,
        taksit_no: int,
        kart: KrediKartiTanimi | dict,
    ) -> dict[str, date]:
        """Taksit n → çekim döneminden (n-1) ay sonraki ekstre."""
        base = KrediKartiEkstreService.donem_bilgisi(cekim_tarihi, kart)
        n = max(1, int(taksit_no or 1))
        if n == 1:
            return base
        y, a = _ay_kaydir(base["kesim_tarihi"].year, base["kesim_tarihi"].month, n - 1)
        kesim_gunu, _ = KrediKartiEkstreService.kart_gunleri(kart)
        kesim = ay_gunu(y, a, kesim_gunu)
        oy, oa = _ay_kaydir(y, a, -1)
        onceki = ay_gunu(oy, oa, kesim_gunu)
        return {
            "kesim_tarihi": kesim,
            "donem_baslangic": onceki + timedelta(days=1),
            "donem_bitis": kesim,
            "son_odeme_tarihi": KrediKartiEkstreService.son_odeme_hesapla(kesim, kart),
        }

    @staticmethod
    def obligation_key(kredi_karti_id: int, kesim_tarihi: date) -> str:
        return f"{KAYNAK_KK_EKSTRE}:{int(kredi_karti_id)}:{kesim_tarihi.isoformat()}"

    @staticmethod
    def _durum_hesapla(
        toplam: Decimal,
        odenen: Decimal,
        son_odeme: date,
        *,
        bugun: date | None = None,
        kesin: bool = True,
    ) -> str:
        bugun = bugun or date.today()
        kalan = (toplam - odenen).quantize(KURUS, rounding=ROUND_HALF_UP)
        if odenen > toplam and toplam >= 0:
            return DURUM_FAZLA
        if kalan <= 0 and odenen > 0:
            return DURUM_ODENDI
        if odenen > 0 and kalan > 0:
            if kesin and son_odeme < bugun:
                return DURUM_GECIKMIS
            return DURUM_KISMI
        if not kesin:
            return DURUM_KESILMEMIS
        if son_odeme < bugun and kalan > 0:
            return DURUM_GECIKMIS
        return DURUM_KESILMIS

    @staticmethod
    def _hareketleri_topla(
        kart: KrediKartiTanimi,
        *,
        bugun: date | None = None,
    ) -> dict[tuple[int, date], dict]:
        """Açık taksitleri ekstre anahtarına (kart_id, kesim) göre grupla."""
        bugun = bugun or date.today()
        gruplar: dict[tuple[int, date], dict] = {}
        with get_session() as session:
            q = (
                select(KrediKartiOdemeTaksit)
                .join(KrediKartiOdeme)
                .where(
                    KrediKartiOdeme.kredi_karti_id == int(kart.id),
                    KrediKartiOdeme.durum == "AÇIK",
                )
                .options(
                    selectinload(KrediKartiOdemeTaksit.odeme).selectinload(
                        KrediKartiOdeme.kredi_karti
                    )
                )
                .order_by(KrediKartiOdemeTaksit.vade_tarihi, KrediKartiOdemeTaksit.id)
            )
            for t in session.scalars(q).all():
                o = t.odeme
                if not o:
                    continue
                cekim = o.tarih
                donem = KrediKartiEkstreService.taksit_donem_bilgisi(
                    cekim, t.taksit_no, kart
                )
                key = (int(kart.id), donem["kesim_tarihi"])
                if key not in gruplar:
                    gruplar[key] = {
                        "kart": kart,
                        "kesim_tarihi": donem["kesim_tarihi"],
                        "donem_baslangic": donem["donem_baslangic"],
                        "donem_bitis": donem["donem_bitis"],
                        "son_odeme_tarihi": donem["son_odeme_tarihi"],
                        "satirlar": [],
                        "toplam": SIFIR,
                    }
                tutar = _d(t.tutar)
                # Ödenmiş taksitler ekstre toplamına borç olarak girmez (zaten kapatılmış)
                if t.durum == "ODENDI":
                    etki = SIFIR
                    borc = SIFIR
                    alacak = tutar
                else:
                    etki = tutar
                    borc = tutar
                    alacak = SIFIR
                    gruplar[key]["toplam"] += tutar
                gruplar[key]["satirlar"].append({
                    "taksit_id": t.id,
                    "odeme_id": o.id,
                    "belge_no": o.belge_no,
                    "islem_tarihi": cekim,
                    "aciklama": o.aciklama or f"KK ödeme {o.belge_no}",
                    "is_yeri": "",
                    "islem_turu": o.cekim_turu,
                    "tek_cekim_taksit": (
                        "Tek çekim" if o.cekim_turu == "TEK_CEKIM"
                        else f"Taksit {t.taksit_no}/{o.taksit_sayisi}"
                    ),
                    "taksit_no": t.taksit_no,
                    "taksit_sayisi": o.taksit_sayisi,
                    "borc": borc,
                    "alacak": alacak,
                    "etki": etki,
                    "kaynak_evrak": o.belge_no,
                    "taksit_durum": t.durum,
                })
        return gruplar

    @staticmethod
    def _odenen_toplam(session, ekstre_id: int | None, kart_id: int, kesim: date) -> Decimal:
        if ekstre_id:
            q = select(KrediKartiEkstreOdeme).where(
                KrediKartiEkstreOdeme.ekstre_id == int(ekstre_id),
                KrediKartiEkstreOdeme.iptal.is_(False),
            )
        else:
            # ekstre henüz yoksa 0
            return SIFIR
        return sum((_d(o.tutar) for o in session.scalars(q).all()), SIFIR)

    @staticmethod
    def ekstreleri_hesapla(
        *,
        bugun: date | None = None,
        kredi_karti_id: int | None = None,
        odenenleri_dahil: bool = True,
    ) -> list[dict[str, Any]]:
        """Tüm (veya tek) kart için ekstre ana satırları — mükerrersiz."""
        KrediKartiEkstreService.schema_hazirla()
        bugun = bugun or date.today()
        sonuc: list[dict[str, Any]] = []
        with get_session() as session:
            q = select(KrediKartiTanimi).where(KrediKartiTanimi.aktif.is_(True))
            if kredi_karti_id:
                q = q.where(KrediKartiTanimi.id == int(kredi_karti_id))
            kartlar = list(session.scalars(q).all())

        for kart in kartlar:
            gruplar = KrediKartiEkstreService._hareketleri_topla(kart, bugun=bugun)
            with get_session() as session:
                for (_kid, kesim), g in sorted(gruplar.items(), key=lambda x: x[0][1]):
                    ekstre = session.scalar(
                        select(KrediKartiEkstre).where(
                            KrediKartiEkstre.kredi_karti_id == int(kart.id),
                            KrediKartiEkstre.kesim_tarihi == kesim,
                        )
                    )
                    toplam = _d(g["toplam"])
                    odenen = SIFIR
                    if ekstre:
                        odenen = KrediKartiEkstreService._odenen_toplam(
                            session, ekstre.id, int(kart.id), kesim
                        )
                    kalan = (toplam - odenen).quantize(KURUS, rounding=ROUND_HALF_UP)
                    kesin = kesim <= bugun
                    durum = KrediKartiEkstreService._durum_hesapla(
                        toplam, odenen, g["son_odeme_tarihi"], bugun=bugun, kesin=kesin
                    )
                    if not odenenleri_dahil and durum == DURUM_ODENDI:
                        continue
                    if kalan <= 0 and not odenenleri_dahil:
                        continue
                    # Persist / sync snapshot
                    if ekstre is None:
                        ekstre = KrediKartiEkstre(
                            kredi_karti_id=int(kart.id),
                            kesim_tarihi=kesim,
                            donem_baslangic=g["donem_baslangic"],
                            donem_bitis=g["donem_bitis"],
                            son_odeme_tarihi=g["son_odeme_tarihi"],
                            para_birimi=getattr(kart, "para_birimi", None) or "TRY",
                        )
                        session.add(ekstre)
                        session.flush()
                    ekstre.donem_baslangic = g["donem_baslangic"]
                    ekstre.donem_bitis = g["donem_bitis"]
                    ekstre.son_odeme_tarihi = g["son_odeme_tarihi"]
                    ekstre.toplam_borc = toplam
                    ekstre.odenen = odenen
                    ekstre.kalan = max(kalan, SIFIR)
                    ekstre.durum = durum
                    ekstre.kesin = kesin
                    ekstre.guncelleme = datetime.now()
                    session.flush()

                    banka_adi = getattr(kart, "kart_bankasi", None) or ""
                    try:
                        from database.models.finans import BankaKarti

                        bk = session.get(BankaKarti, kart.banka_karti_id)
                        if bk and getattr(bk, "banka_adi", None):
                            banka_adi = banka_adi or bk.banka_adi
                    except Exception:
                        pass

                    etiket = "Kredi Kartı Ekstresi"
                    certainty = "KESIN" if kesin else "TAHMINI"
                    if not kesin:
                        etiket = "Bekleyen Ekstre"

                    sonuc.append({
                        "ekstre_id": ekstre.id,
                        "obligation_key": KrediKartiEkstreService.obligation_key(
                            int(kart.id), kesim
                        ),
                        "source_type": KAYNAK_KK_EKSTRE,
                        "source_id": f"{kart.id}:{kesim.isoformat()}",
                        "kredi_karti_id": int(kart.id),
                        "due_date": g["son_odeme_tarihi"],
                        "payment_month": (
                            g["son_odeme_tarihi"].year,
                            g["son_odeme_tarihi"].month,
                        ),
                        "kesim_tarihi": kesim,
                        "donem_baslangic": g["donem_baslangic"],
                        "donem_bitis": g["donem_bitis"],
                        "son_odeme_tarihi": g["son_odeme_tarihi"],
                        "aciklama": (
                            f"{kart.kart_adi}"
                            f"{(' •••• ' + kart.son_dort_hane) if kart.son_dort_hane else ''} "
                            f"— {g['donem_baslangic'].strftime('%d.%m.%Y')}–"
                            f"{g['donem_bitis'].strftime('%d.%m.%Y')}"
                        ).strip(),
                        "kaynak_etiket": etiket,
                        "banka_adi": banka_adi or "",
                        "kart_adi": kart.kart_adi,
                        "son_dort_hane": kart.son_dort_hane or "",
                        "belge_no": f"EKSTRE-{kart.id}-{kesim.isoformat()}",
                        "kategori": "Kredi kartı ekstresi",
                        "para_birimi": getattr(kart, "para_birimi", None) or "TRY",
                        "orijinal_tutar": toplam,
                        "tl_tutar": toplam,
                        "odenen": odenen,
                        "kalan": max(kalan, SIFIR),
                        "anapara": SIFIR,
                        "faiz": SIFIR,
                        "masraf": SIFIR,
                        "certainty": certainty,
                        "oncelik": "YUKSEK",
                        "durum": (
                            "ODENDI" if durum == DURUM_ODENDI
                            else "KISMEN_ODENDI" if durum == DURUM_KISMI
                            else "GECIKMIS" if durum == DURUM_GECIKMIS
                            else "PLANLANDI"
                        ),
                        "ekstre_durum": durum,
                        "kesin": kesin,
                        "detay_satirlari": list(g["satirlar"]),
                        "kart_limiti": _d(getattr(kart, "kart_limiti", 0) or 0),
                    })
                session.flush()
        sonuc.sort(key=lambda s: (s["due_date"], s.get("kart_adi") or ""))
        return sonuc

    @staticmethod
    def ekstre_detay(ekstre_id: int | None = None, *, source_id: str | None = None) -> dict:
        KrediKartiEkstreService.schema_hazirla()
        with get_session() as session:
            ekstre = None
            if ekstre_id:
                ekstre = session.get(KrediKartiEkstre, int(ekstre_id))
            elif source_id and ":" in source_id:
                kid_s, kesim_s = source_id.split(":", 1)
                ekstre = session.scalar(
                    select(KrediKartiEkstre).where(
                        KrediKartiEkstre.kredi_karti_id == int(kid_s),
                        KrediKartiEkstre.kesim_tarihi == date.fromisoformat(kesim_s),
                    )
                )
            if not ekstre:
                raise ValueError("Ekstre bulunamadı.")
            kart = session.get(KrediKartiTanimi, ekstre.kredi_karti_id)
            if not kart:
                raise ValueError("Kart bulunamadı.")
        # Yeniden hesapla detay
        hesaplar = KrediKartiEkstreService.ekstreleri_hesapla(
            kredi_karti_id=ekstre.kredi_karti_id, odenenleri_dahil=True
        )
        for h in hesaplar:
            if h.get("ekstre_id") == ekstre.id or (
                h.get("kesim_tarihi") == ekstre.kesim_tarihi
            ):
                return h
        raise ValueError("Ekstre detayı hesaplanamadı.")

    @staticmethod
    def odeme_yap(
        *,
        ekstre_id: int,
        tutar,
        tarih: date | None = None,
        hesap_adi: str | None = None,
        finans_hesap_id: int | None = None,
        dekont_no: str | None = None,
        aciklama: str | None = None,
        tamami: bool = False,
    ) -> dict:
        """Ekstre ödemesi — banka çıkışı + ekstre bakiyesi."""
        yazma_zorunlu("finans_duzenleme")
        if not (
            yetki_var("finans_duzenleme")
            or yetki_var("odeme_durumu_goruntuleme")
            or yetki_var("finans_goruntuleme")
        ):
            raise PermissionError("Ekstre ödeme yetkiniz yok.")

        KrediKartiEkstreService.schema_hazirla()
        tarih = tarih or date.today()

        # Önce bakiyeyi ayrı oturumda güncelle / oku (iç içe yazma yok)
        on_hesap = KrediKartiEkstreService.ekstreleri_hesapla(
            odenenleri_dahil=True,
        )
        guncel = next((h for h in on_hesap if h.get("ekstre_id") == int(ekstre_id)), None)
        if not guncel:
            raise ValueError("Ekstre bulunamadı veya hesaplanamadı.")
        kalan = _d(guncel.get("kalan"))
        if tamami:
            odeme_tutari = kalan
        else:
            odeme_tutari = _d(tutar, minimum=Decimal("0.01"))
        if odeme_tutari <= 0:
            raise ValueError("Ödeme tutarı sıfırdan büyük olmalıdır.")
        if odeme_tutari > kalan + Decimal("0.01"):
            raise ValueError(
                f"Ödeme tutarı kalan borçtan ({kalan}) büyük olamaz. "
                "Fazla ödeme için kalan kadar ödeyin."
            )

        with get_session() as session:
            ekstre = session.get(KrediKartiEkstre, int(ekstre_id))
            if not ekstre:
                raise ValueError("Ekstre bulunamadı.")
            kart = session.get(KrediKartiTanimi, ekstre.kredi_karti_id)
            if not kart:
                raise ValueError("Kart bulunamadı.")

            from database.finans_service import FinansService

            belge_no = FinansService._finans_belge_no(session, "KKE")
            hesap = hesap_adi
            if not hesap and finans_hesap_id:
                from database.models.finans import FinansHesabi

                fh = session.get(FinansHesabi, int(finans_hesap_id))
                hesap = fh.hesap_adi if fh else None
            if not hesap:
                # Kartın bağlı banka mevduat hesabı
                hesaplar_list = list(FinansService.hesaplar() or [])
                hesap = next(
                    (
                        h.hesap_adi
                        for h in hesaplar_list
                        if getattr(h, "banka_karti_id", None) == kart.banka_karti_id
                        and getattr(h, "alt_hesap_turu", None) == "MEVDUAT"
                    ),
                    None,
                )
                if not hesap and hesaplar_list:
                    hesap = hesaplar_list[0].hesap_adi
            if not hesap:
                raise ValueError("Ödeme için banka/kasa hesabı bulunamadı.")

            FinansService.hareket_ekle(
                session,
                belge_no,
                tarih,
                odeme_tutari,
                "KK EKSTRE ÖDEME",
                hesap,
                aciklama
                or f"{kart.kart_adi} ekstre {ekstre.kesim_tarihi.strftime('%d.%m.%Y')}",
            )
            kayit = KrediKartiEkstreOdeme(
                ekstre_id=ekstre.id,
                belge_no=belge_no,
                tarih=tarih,
                tutar=odeme_tutari,
                hesap_turu="MEVDUAT",
                finans_hesap_id=finans_hesap_id,
                dekont_no=(dekont_no or "").strip() or None,
                aciklama=(aciklama or "").strip() or None,
                finans_belge_no=belge_no,
            )
            session.add(kayit)
            session.flush()

            # Taksitleri FIFO kapat (ödendi işaretle)
            KrediKartiEkstreService._taksitleri_kapat(
                session, kart, ekstre, odeme_tutari
            )
            session.flush()

        # Yeniden hesap
        guncel2 = KrediKartiEkstreService.ekstre_detay(ekstre_id)
        return {
            "belge_no": belge_no,
            "tutar": odeme_tutari,
            "ekstre": guncel2,
        }

    @staticmethod
    def _taksitleri_kapat(session, kart, ekstre: KrediKartiEkstre, tutar: Decimal) -> None:
        """Ekstre dönemindeki bekleyen taksitleri FIFO ile ODENDI yap."""
        kalan_odeme = _d(tutar)
        q = (
            select(KrediKartiOdemeTaksit)
            .join(KrediKartiOdeme)
            .where(
                KrediKartiOdeme.kredi_karti_id == int(kart.id),
                KrediKartiOdeme.durum == "AÇIK",
                KrediKartiOdemeTaksit.durum == "BEKLIYOR",
            )
            .options(selectinload(KrediKartiOdemeTaksit.odeme))
            .order_by(KrediKartiOdemeTaksit.vade_tarihi, KrediKartiOdemeTaksit.id)
        )
        for t in session.scalars(q).all():
            if kalan_odeme <= 0:
                break
            o = t.odeme
            if not o:
                continue
            donem = KrediKartiEkstreService.taksit_donem_bilgisi(
                o.tarih, t.taksit_no, kart
            )
            if donem["kesim_tarihi"] != ekstre.kesim_tarihi:
                continue
            tt = _d(t.tutar)
            if tt <= kalan_odeme + Decimal("0.001"):
                t.durum = "ODENDI"
                kalan_odeme -= tt
            # Kısmi taksit kapatma desteklenmiyor — kalan bir sonraki ödemede

    @staticmethod
    def odeme_iptal(belge_no: str) -> None:
        yazma_zorunlu("finans_duzenleme")
        with get_session() as session:
            kayit = session.scalar(
                select(KrediKartiEkstreOdeme).where(
                    KrediKartiEkstreOdeme.belge_no == belge_no
                )
            )
            if not kayit or kayit.iptal:
                raise ValueError("Ödeme kaydı bulunamadı veya zaten iptal.")
            kayit.iptal = True
            kayit.iptal_tarihi = datetime.now()
            if kayit.finans_belge_no:
                from database.finans_service import FinansService

                FinansService._finans_hareketlerini_sil(session, kayit.finans_belge_no)
            # Taksitleri yeniden BEKLIYOR yapamayız güvenli şekilde tek tek;
            # ekstre toplamı ödemelerden hesaplandığı için taksit durumu
            # rapor kalanını bozmamalı — ödemeler düşülünce kalan artar.
            # Ancak _hareketleri_topla ODENDI taksitleri borçtan çıkarıyor.
            # İptalde ilgili dönem taksitlerini geri aç:
            ekstre = session.get(KrediKartiEkstre, kayit.ekstre_id)
            if ekstre:
                kart = session.get(KrediKartiTanimi, ekstre.kredi_karti_id)
                if kart:
                    q = (
                        select(KrediKartiOdemeTaksit)
                        .join(KrediKartiOdeme)
                        .where(
                            KrediKartiOdeme.kredi_karti_id == int(kart.id),
                            KrediKartiOdemeTaksit.durum == "ODENDI",
                        )
                        .options(selectinload(KrediKartiOdemeTaksit.odeme))
                    )
                    for t in session.scalars(q).all():
                        o = t.odeme
                        if not o:
                            continue
                        donem = KrediKartiEkstreService.taksit_donem_bilgisi(
                            o.tarih, t.taksit_no, kart
                        )
                        if donem["kesim_tarihi"] == ekstre.kesim_tarihi:
                            t.durum = "BEKLIYOR"
            session.flush()
