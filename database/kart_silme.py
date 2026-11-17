"""Kullanılmamış banka kartı ve firma kredi kartı tanımı — kalıcı silme.

Yalnızca gerçek finansal geçmişi olmayan kart silinir. Sıfır bakiye yetmez.
Teknik Evo eşleştirmesi (bank_account_match_rules) finansal kayda hizmet etmiyorsa
kaynak engeline yazılır ve kaldırılır; sonraki aktarım kartı sessizce yeniden açmaz.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from database.access import yazma_zorunlu
from database.database import Base, engine, get_session
from database.models.finans import (
    BankAccountMatchRule,
    BankaKarti,
    BankaKaynakEngel,
    BankaKrediOdeme,
    BankaKrediTaksit,
    BankaKredisi,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    GiderKartOdeme,
    KasaMakbuzu,
    KasaMakbuzSatiri,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiOdeme,
    KrediKartiTanimi,
    PosTaksitKomisyon,
    PosValorKaydi,
)

KAYNAK_EVO = "EVOBULUT"
KAYNAK_KK = "KREDI_KARTI"
NEDEN_TEKNIK_ESLESME = "Kullanıcı sildi: boş kart, yalnızca teknik eşleştirme"
NEDEN_KK = "Kullanıcı sildi: kullanılmamış firma kredi kartı"

_hazir_engine_id: int | None = None


def schema_hazirla(eng=None) -> None:
    """banka_kaynak_engelleri tablosu — tekrar çağrı güvenli."""
    global _hazir_engine_id
    bag = eng if eng is not None else engine
    if bag is None:
        return
    if eng is None and _hazir_engine_id == id(bag):
        return
    Base.metadata.create_all(bind=bag, tables=[BankaKaynakEngel.__table__])
    if eng is None or eng is bag:
        _hazir_engine_id = id(bag)


def eslestirme_gerekli_mesaji(evo_id: str, ad: str | None = None) -> str:
    ad_txt = f" ({ad})" if (ad or "").strip() else ""
    return (
        f"Evo banka {evo_id}{ad_txt} daha önce silinmiş boş karttı; "
        "kart yeniden oluşturulmadı. Yeni kaynak hareketi için eşleştirme gerekli."
    )


def banka_kaynak_engelli_mi(kaynak_sistem: str, kaynak_kimlik: str) -> bool:
    schema_hazirla()
    kimlik = str(kaynak_kimlik or "").strip()
    sistem = str(kaynak_sistem or "").strip()
    if not kimlik or not sistem:
        return False
    with get_session() as session:
        return (
            session.scalar(
                select(BankaKaynakEngel.id).where(
                    BankaKaynakEngel.kaynak_sistem == sistem,
                    BankaKaynakEngel.kaynak_kimlik == kimlik,
                )
            )
            is not None
        )


def kk_tanim_engelli(
    banka_karti_id: int | None,
    hesap_id: int | None = None,
    kart_adi: str | None = None,
    *,
    session: Session | None = None,
) -> bool:
    """Silinmiş firma KK tanımı — eşleme bu hesabı sessizce yeniden açmasın."""
    schema_hazirla()
    kimlikler = [k for _, k in _kk_kimlikler(banka_karti_id, hesap_id, kart_adi, None)]
    if not kimlikler:
        return False

    def _var(s: Session) -> bool:
        if not _tablo(s, BankaKaynakEngel.__tablename__):
            return False
        return (
            s.scalar(
                select(BankaKaynakEngel.id).where(
                    BankaKaynakEngel.kaynak_sistem == KAYNAK_KK,
                    BankaKaynakEngel.kaynak_kimlik.in_(kimlikler),
                )
            )
            is not None
        )

    if session is not None:
        return _var(session)
    with get_session() as s:
        return _var(s)


def banka_karti_kullanim_ozeti(kart_id: int) -> dict[str, Any]:
    schema_hazirla()
    with get_session() as session:
        return _banka_ozet(session, int(kart_id))


def kredi_karti_kullanim_ozeti(kart_id: int) -> dict[str, Any]:
    schema_hazirla()
    with get_session() as session:
        return _kk_ozet(session, int(kart_id))


def banka_karti_sil(kart_id: int, *, onaylandi: bool = False, session: Session | None = None) -> dict[str, Any]:
    """BankaKarti yalnızca hiç kullanılmamışsa silinir. Bağlı hareket silinmez."""
    yazma_zorunlu("finans_duzenleme")
    schema_hazirla()
    if not onaylandi:
        raise ValueError("Silme onayı gerekli.")
    kid = int(kart_id)

    def _calistir(s: Session) -> dict[str, Any]:
        ozet = _banka_ozet(s, kid)
        if not ozet["silinebilir"]:
            raise ValueError(ozet["engel_mesaji"] or "Kartın finansal geçmişi var; silinemez.")
        _banka_sil_uygula(s, kid)
        s.flush()
        return {"silindi": True, **{k: v for k, v in ozet.items() if k != "engel_mesaji"}}

    if session is not None:
        return _calistir(session)
    with get_session() as s:
        return _calistir(s)


def kredi_karti_sil(kart_id: int, *, onaylandi: bool = False, session: Session | None = None) -> dict[str, Any]:
    """KrediKartiTanimi yalnızca hiç kullanılmamışsa silinir."""
    yazma_zorunlu("finans_duzenleme")
    schema_hazirla()
    if not onaylandi:
        raise ValueError("Silme onayı gerekli.")
    kid = int(kart_id)

    def _calistir(s: Session) -> dict[str, Any]:
        ozet = _kk_ozet(s, kid)
        if not ozet["silinebilir"]:
            raise ValueError(ozet["engel_mesaji"] or "Kartın finansal geçmişi var; silinemez.")
        kart = s.get(KrediKartiTanimi, kid)
        if kart is None:
            raise ValueError("Kredi kartı bulunamadı.")
        _kk_engel_yaz(s, kart)
        s.delete(kart)
        s.flush()
        return {"silindi": True, **{k: v for k, v in ozet.items() if k != "engel_mesaji"}}

    if session is not None:
        return _calistir(session)
    with get_session() as s:
        return _calistir(s)


def _tablo(session: Session, ad: str) -> bool:
    try:
        return inspect(session.get_bind()).has_table(ad)
    except Exception:
        return False


def _say(session: Session, model, *kriter) -> int:
    if not _tablo(session, model.__tablename__):
        return 0
    return int(session.scalar(select(func.count()).select_from(model).where(*kriter)) or 0)


def _acilis_var(hesap: FinansHesabi) -> bool:
    return Decimal(str(hesap.acilis_bakiyesi or 0)) != 0


def _ad_anahtar(ad: str | None) -> str:
    return " ".join((ad or "").casefold().split())[:60]


def _kk_kimlikler(banka_karti_id, hesap_id, kart_adi, son4) -> list[tuple[str, str]]:
    kimlikler: list[tuple[str, str]] = []
    if hesap_id:
        kimlikler.append((KAYNAK_KK, f"HESAP:{int(hesap_id)}"))
    if banka_karti_id and (kart_adi or "").strip():
        kimlikler.append((KAYNAK_KK, f"AD:{int(banka_karti_id)}:{_ad_anahtar(kart_adi)}"))
    if banka_karti_id and (son4 or "").strip():
        kimlikler.append((KAYNAK_KK, f"SON4:{int(banka_karti_id)}:{str(son4).strip()}"))
    return kimlikler


def _engel_yaz(
    session: Session,
    *,
    sistem: str,
    kimlik: str,
    kart_turu: str,
    kart_kodu: str | None,
    kart_adi: str | None,
    neden: str,
    evo_banka_adi: str | None = None,
    eski_kart_id: int | None = None,
    eski_hesap_id: int | None = None,
) -> None:
    kimlik = str(kimlik or "").strip()
    if not kimlik:
        return
    var = session.scalar(
        select(BankaKaynakEngel).where(
            BankaKaynakEngel.kaynak_sistem == sistem,
            BankaKaynakEngel.kaynak_kimlik == kimlik,
        )
    )
    if var is not None:
        return
    session.add(
        BankaKaynakEngel(
            kaynak_sistem=sistem,
            kaynak_kimlik=kimlik[:80],
            kart_turu=kart_turu,
            kart_kodu=(kart_kodu or None),
            kart_adi=(kart_adi or None),
            evo_banka_adi=(evo_banka_adi or None),
            eski_kart_id=eski_kart_id,
            eski_hesap_id=eski_hesap_id,
            neden=(neden or "")[:300] or None,
        )
    )


def _kk_engel_yaz(session: Session, kart: KrediKartiTanimi) -> None:
    kod = (kart.son_dort_hane or str(kart.id))[:50]
    for _sistem, kimlik in _kk_kimlikler(
        kart.banka_karti_id, kart.bagli_hesap_id, kart.kart_adi, kart.son_dort_hane
    ):
        _engel_yaz(
            session,
            sistem=KAYNAK_KK,
            kimlik=kimlik,
            kart_turu="KREDI_KARTI",
            kart_kodu=kod,
            kart_adi=kart.kart_adi,
            neden=NEDEN_KK,
            eski_kart_id=int(kart.id),
            eski_hesap_id=int(kart.bagli_hesap_id) if kart.bagli_hesap_id else None,
        )


def _hareket_sinifi(tur: str) -> str:
    t = (tur or "").upper()
    for src, dst in (("İ", "I"), ("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        t = t.replace(src, dst)
    if any(k in t for k in ("ACILIS", "DEVIR")):
        return "acilis"
    if any(k in t for k in ("VIRMAN", "HAVALE", "AKTARIM", "TRANSFER")):
        return "transfer"
    if "EKSTRE" in t and "ODE" in t:
        return "odeme"
    if t.startswith("KK ODEME") or "HARCAMA" in t or t.startswith("KK GIDER") or t.startswith("KK IADE"):
        return "harcama"
    if "ODEME" in t or "TAHSIL" in t:
        return "odeme"
    return "diger"


def _hareket_cumlesi(sayilar: dict[str, int]) -> str:
    parca = []
    for anahtar, etiket in (
        ("harcama", "harcama"),
        ("odeme", "ödeme"),
        ("transfer", "virman"),
        ("acilis", "açılış/devir"),
        ("diger", "diğer"),
    ):
        n = int(sayilar.get(anahtar) or 0)
        if n:
            parca.append(f"{n} {etiket}")
    if not parca:
        return ""
    govde = parca[0] if len(parca) == 1 else ", ".join(parca[:-1]) + " ve " + parca[-1]
    return f"{govde} hareketi var; silinemez"


def _mesaj(tur_etiket: str, kod: str, ad: str, engeller: list[str]) -> str:
    if not engeller:
        return ""
    return (
        f"«{tur_etiket} — {kod} / {ad}» silinemez.\n"
        + "\n".join(f"• {e}" for e in engeller)
        + "\n\nGeçmiş kayıtlar korunur. Sil yerine Pasif Yap kullanın."
    )


def _bos_ozet(**ek) -> dict[str, Any]:
    taban = {
        "kart_id": None,
        "tur": "",
        "tur_etiket": "",
        "kod": "",
        "ad": "",
        "silinebilir": False,
        "engeller": [],
        "engel_mesaji": "",
        "hareket": 0,
        "harcama": 0,
        "odeme": 0,
        "transfer": 0,
        "acilis_hareket": 0,
        "acilis_bakiye": 0,
        "kk_odeme": 0,
        "ekstre": 0,
        "ekstre_odeme": 0,
        "gider_kart_odeme": 0,
        "banka_kredi": 0,
        "pos_valor": 0,
        "muhasebe_bag": 0,
        "belge": 0,
        "varsayilan_odeme_ref": 0,
        "teknik_eslestirme": 0,
        "bos_kk_tanim": 0,
    }
    taban.update(ek)
    return taban


def _hareket_sayilari(session: Session, hesap_ids: list[int]) -> dict[str, int]:
    sayilar = {"harcama": 0, "odeme": 0, "transfer": 0, "acilis": 0, "diger": 0, "toplam": 0}
    if not hesap_ids or not _tablo(session, FinansHareketi.__tablename__):
        return sayilar
    rows = session.execute(
        select(FinansHareketi.hareket_turu, func.count())
        .where(FinansHareketi.hesap_id.in_(hesap_ids))
        .group_by(FinansHareketi.hareket_turu)
    ).all()
    for tur, n in rows:
        sinif = _hareket_sinifi(tur or "")
        sayilar[sinif] = sayilar.get(sinif, 0) + int(n or 0)
        sayilar["toplam"] += int(n or 0)
    return sayilar


def _durum_satiri(session: Session, model, durum_kolon, filtre, etiket: str) -> tuple[int, str | None]:
    if not _tablo(session, model.__tablename__):
        return 0, None
    rows = session.execute(
        select(durum_kolon, func.count()).select_from(model).where(filtre).group_by(durum_kolon)
    ).all()
    toplam = sum(int(n or 0) for _, n in rows)
    if not toplam:
        return 0, None
    parca = ", ".join(f"{(d or '—')}:{int(n or 0)}" for d, n in rows)
    return toplam, (
        f"{toplam} {etiket} [{parca}] — taslak, iptal, ödenmiş ve sıfır tutar da sayılır"
    )


def _muhasebe_fis_sayisi(session: Session, hesap_ids: list[int], kk_ids: list[int]) -> int:
    if not _tablo(session, "muhasebe_fisleri"):
        return 0
    from database.models.genel_muhasebe import MuhasebeFisi

    n = 0
    if hesap_ids:
        n += _say(
            session,
            MuhasebeFisi,
            MuhasebeFisi.kaynak_id.in_(hesap_ids),
            MuhasebeFisi.kaynak_turu.in_(
                (
                    "banka_havale",
                    "kasa_banka_virman",
                    "pos_valor_aktarimi",
                    "pos_tahsilat",
                    "gider_fisi",
                    "kasa_makbuzu",
                )
            ),
        )
    if kk_ids:
        n += _say(
            session,
            MuhasebeFisi,
            MuhasebeFisi.kaynak_id.in_(kk_ids),
            MuhasebeFisi.kaynak_turu.in_(("kart_odeme", "kk_ekstre_odeme")),
        )
    return n


def _cek_sayisi(session: Session, hesap_ids: list[int]) -> int:
    if not hesap_ids or not _tablo(session, "cek_senet_evraklari"):
        return 0
    from database.models.cek_senet import CekSenetEvrak

    return _say(
        session,
        CekSenetEvrak,
        or_(
            CekSenetEvrak.banka_hesabi_id.in_(hesap_ids),
            CekSenetEvrak.kasa_id.in_(hesap_ids),
        ),
    )


def _banka_hesaplari(session: Session, kart_id: int) -> list[FinansHesabi]:
    if not _tablo(session, FinansHesabi.__tablename__):
        return []
    return list(
        session.scalars(select(FinansHesabi).where(FinansHesabi.banka_karti_id == int(kart_id))).all()
    )


def _kk_tanimlari(session: Session, kart_id: int, hesap_ids: list[int]) -> list[KrediKartiTanimi]:
    if not _tablo(session, KrediKartiTanimi.__tablename__):
        return []
    filtre = [KrediKartiTanimi.banka_karti_id == int(kart_id)]
    if hesap_ids:
        filtre.append(KrediKartiTanimi.bagli_hesap_id.in_(hesap_ids))
    return list(session.scalars(select(KrediKartiTanimi).where(or_(*filtre))).all())


def _kk_kullanim_engelleri(session: Session, kk_ids: list[int], *, banka_mi: bool) -> tuple[dict[str, int], list[str]]:
    """Firma KK tanımlarına bağlı ödeme / ekstre / gider. Boş tanım engel değildir."""
    sayilar = {"kk_odeme": 0, "ekstre": 0, "ekstre_odeme": 0, "gider_kart_odeme": 0, "makbuz_satir": 0}
    engeller: list[str] = []
    if not kk_ids:
        return sayilar, engeller
    n, metin = _durum_satiri(
        session,
        KrediKartiOdeme,
        KrediKartiOdeme.durum,
        KrediKartiOdeme.kredi_karti_id.in_(kk_ids),
        "kredi kartı ödemesi",
    )
    sayilar["kk_odeme"] = n
    if metin:
        engeller.append(metin)
    n, metin = _durum_satiri(
        session,
        KrediKartiEkstre,
        KrediKartiEkstre.durum,
        KrediKartiEkstre.kredi_karti_id.in_(kk_ids),
        "ekstre",
    )
    sayilar["ekstre"] = n
    if metin:
        engeller.append(metin)
    if _tablo(session, KrediKartiEkstre.__tablename__) and _tablo(session, KrediKartiEkstreOdeme.__tablename__):
        ekstre_ids = list(
            session.scalars(
                select(KrediKartiEkstre.id).where(KrediKartiEkstre.kredi_karti_id.in_(kk_ids))
            ).all()
        )
        if ekstre_ids:
            n_od = _say(
                session,
                KrediKartiEkstreOdeme,
                KrediKartiEkstreOdeme.ekstre_id.in_(ekstre_ids),
            )
            sayilar["ekstre_odeme"] = n_od
            if n_od:
                iptal = _say(
                    session,
                    KrediKartiEkstreOdeme,
                    KrediKartiEkstreOdeme.ekstre_id.in_(ekstre_ids),
                    KrediKartiEkstreOdeme.iptal.is_(True),
                )
                engeller.append(
                    f"{n_od} ekstre ödemesi"
                    + (f" ({iptal} iptal)" if iptal else "")
                    + " — iptal edilen ödemeler de sayılır"
                )
    n_g = _say(session, GiderKartOdeme, GiderKartOdeme.kredi_karti_id.in_(kk_ids))
    sayilar["gider_kart_odeme"] = n_g
    if n_g:
        engeller.append(f"{n_g} gider kart ödemesi — iptal dahil, silinemez")
    if _tablo(session, KasaMakbuzSatiri.__tablename__):
        n_m = _say(session, KasaMakbuzSatiri, KasaMakbuzSatiri.kredi_karti_id.in_(kk_ids))
        sayilar["makbuz_satir"] = n_m
        if n_m:
            engeller.append(f"{n_m} makbuz satırı bu karta bağlı")
    if banka_mi and not engeller:
        return sayilar, engeller
    return sayilar, engeller


def _hesap_belge_engelleri(session: Session, hesap_ids: list[int]) -> tuple[int, list[str]]:
    engeller: list[str] = []
    toplam = 0
    if not hesap_ids:
        return 0, engeller
    for model, kolon, etiket in (
        (GiderFisi, GiderFisi.finans_hesap_id, "gider/gelir fişi"),
        (KasaMakbuzu, KasaMakbuzu.finans_hesap_id, "kasa/banka makbuzu"),
    ):
        if not _tablo(session, model.__tablename__):
            continue
        n, metin = _durum_satiri(session, model, model.durum, kolon.in_(hesap_ids), etiket)
        toplam += n
        if metin:
            engeller.append(metin)
    if _tablo(session, KasaMakbuzSatiri.__tablename__):
        n = _say(session, KasaMakbuzSatiri, KasaMakbuzSatiri.finans_hesap_id.in_(hesap_ids))
        toplam += n
        if n:
            engeller.append(f"{n} makbuz satırı bu hesaba bağlı")
    cek = _cek_sayisi(session, hesap_ids)
    toplam += cek
    if cek:
        engeller.append(f"{cek} çek/senet evrakı bu hesaba bağlı")
    if _tablo(session, KrediKartiEkstreOdeme.__tablename__):
        n = _say(
            session,
            KrediKartiEkstreOdeme,
            or_(
                KrediKartiEkstreOdeme.finans_hesap_id.in_(hesap_ids),
                KrediKartiEkstreOdeme.kart_hesap_id.in_(hesap_ids),
            ),
        )
        toplam += n
        if n:
            engeller.append(f"{n} ekstre ödemesi bu hesaptan geçmiş")
    if _tablo(session, BankaKrediOdeme.__tablename__):
        n = _say(session, BankaKrediOdeme, BankaKrediOdeme.banka_hesap_id.in_(hesap_ids))
        toplam += n
        if n:
            engeller.append(f"{n} kredi ödemesi bu hesaba bağlı")
    if _tablo(session, BankaKrediTaksit.__tablename__):
        n = _say(session, BankaKrediTaksit, BankaKrediTaksit.odeme_hesap_id.in_(hesap_ids))
        toplam += n
        if n:
            engeller.append(f"{n} kredi taksiti bu hesabı ödeme hesabı olarak kullanıyor")
    return toplam, engeller


def _banka_ozet(session: Session, kart_id: int) -> dict[str, Any]:
    kart = session.get(BankaKarti, int(kart_id))
    if kart is None:
        return _bos_ozet(
            kart_id=int(kart_id),
            tur="BANKA",
            tur_etiket="Banka Kartı",
            engel_mesaji="Banka kartı bulunamadı.",
            engeller=["Banka kartı bulunamadı."],
        )
    kod = (kart.hesap_no or kart.iban or str(kart.id) or "").strip() or str(kart.id)
    ad = (kart.banka_adi or "").strip() or str(kart.id)
    hesaplar = _banka_hesaplari(session, kart.id)
    hesap_ids = [int(h.id) for h in hesaplar]
    hesap_set = set(hesap_ids)
    engeller: list[str] = []

    hareket = _hareket_sayilari(session, hesap_ids)
    cumle = _hareket_cumlesi(hareket)
    if cumle:
        engeller.append(cumle)

    acilis_n = 0
    muhasebe_n = 0
    for h in hesaplar:
        if _acilis_var(h):
            acilis_n += 1
            engeller.append(
                f"«{h.hesap_adi}» açılış bakiyesi {h.acilis_bakiyesi}; sıfır bakiye sayılmaz, silinemez"
            )
        if getattr(h, "muhasebe_hesap_id", None) or getattr(h, "muhasebe_komisyon_hesap_id", None):
            muhasebe_n += 1
    if muhasebe_n:
        engeller.append(f"{muhasebe_n} alt hesapta muhasebe bağlantısı var; silinemez")

    tanimlar = _kk_tanimlari(session, kart.id, hesap_ids)
    kk_ids = [int(t.id) for t in tanimlar]
    kk_say, kk_engel = _kk_kullanim_engelleri(session, kk_ids, banka_mi=True)
    engeller.extend(kk_engel)

    kredi_n = _say(session, BankaKredisi, BankaKredisi.banka_karti_id == kart.id)
    if hesap_ids and _tablo(session, BankaKredisi.__tablename__):
        kredi_n += _say(
            session,
            BankaKredisi,
            BankaKredisi.bagli_hesap_id.in_(hesap_ids),
            BankaKredisi.banka_karti_id != kart.id,
        )
    if kredi_n:
        engeller.append(f"{kredi_n} banka kredisi var; iptal ve kapalı krediler de sayılır")

    valor_n = _say(session, PosValorKaydi, PosValorKaydi.banka_karti_id == kart.id)
    if hesap_ids and _tablo(session, PosValorKaydi.__tablename__):
        valor_n += _say(
            session,
            PosValorKaydi,
            or_(
                PosValorKaydi.pos_hesap_id.in_(hesap_ids),
                PosValorKaydi.kmh_hesap_id.in_(hesap_ids),
                PosValorKaydi.hedef_hesap_id.in_(hesap_ids),
            ),
            PosValorKaydi.banka_karti_id != kart.id,
        )
    if valor_n:
        engeller.append(f"{valor_n} POS valör kaydı var; iptal dahil, silinemez")

    belge_n, belge_engel = _hesap_belge_engelleri(session, hesap_ids)
    engeller.extend(belge_engel)

    muhasebe_fis = _muhasebe_fis_sayisi(session, hesap_ids, kk_ids)
    muhasebe_n += muhasebe_fis
    if muhasebe_fis:
        engeller.append(f"{muhasebe_fis} muhasebe fişi bu karta bağlı")

    ref_n = 0
    if hesap_ids and _tablo(session, KrediKartiTanimi.__tablename__):
        dis_kk = _say(
            session,
            KrediKartiTanimi,
            KrediKartiTanimi.odeme_hesap_id.in_(hesap_ids),
            KrediKartiTanimi.id.notin_(kk_ids or [0]),
        )
        dis_bagli = _say(
            session,
            KrediKartiTanimi,
            KrediKartiTanimi.bagli_hesap_id.in_(hesap_ids),
            KrediKartiTanimi.id.notin_(kk_ids or [0]),
        )
        ref_n += dis_kk + dis_bagli
        if dis_kk:
            engeller.append(f"{dis_kk} başka kart bu hesabı varsayılan ödeme hesabı olarak kullanıyor")
        if dis_bagli:
            engeller.append(f"{dis_bagli} başka kredi kartı tanımı bu alt hesaba bağlı")
    if hesap_ids and _tablo(session, BankaKarti.__tablename__):
        dis_pos = _say(
            session,
            BankaKarti,
            BankaKarti.pos_aktarim_hesap_id.in_(hesap_ids),
            BankaKarti.id != kart.id,
        )
        ref_n += dis_pos
        if dis_pos:
            engeller.append(f"{dis_pos} başka banka bu hesabı POS aktarım hesabı olarak kullanıyor")

    teknik, yabanci_engel = _eslestirme_ayir(session, kart.id, hesap_set)
    engeller.extend(yabanci_engel)

    bos_kk = 0
    if not kk_engel:
        bos_kk = len(kk_ids)

    ozet = _bos_ozet(
        kart_id=int(kart.id),
        tur="BANKA",
        tur_etiket="Banka Kartı",
        kod=kod,
        ad=ad,
        engeller=engeller,
        engel_mesaji=_mesaj("Banka Kartı", kod, ad, engeller),
        silinebilir=not engeller,
        hareket=hareket["toplam"],
        harcama=hareket["harcama"],
        odeme=hareket["odeme"],
        transfer=hareket["transfer"],
        acilis_hareket=hareket["acilis"],
        acilis_bakiye=acilis_n,
        kk_odeme=kk_say["kk_odeme"],
        ekstre=kk_say["ekstre"],
        ekstre_odeme=kk_say["ekstre_odeme"],
        gider_kart_odeme=kk_say["gider_kart_odeme"],
        banka_kredi=kredi_n,
        pos_valor=valor_n,
        muhasebe_bag=muhasebe_n,
        belge=belge_n,
        varsayilan_odeme_ref=ref_n,
        teknik_eslestirme=len(teknik) if not engeller else 0,
        bos_kk_tanim=bos_kk if not engeller else 0,
    )
    return ozet


def _eslestirme_ayir(
    session: Session, kart_id: int, hesap_set: set[int]
) -> tuple[list[BankAccountMatchRule], list[str]]:
    """Teknik (bu boş karta bakan) kurallar ile başka hesabın kaydına hizmet edenler."""
    if not _tablo(session, BankAccountMatchRule.__tablename__):
        return [], []
    filtre = [BankAccountMatchRule.banka_karti_id == int(kart_id)]
    if hesap_set:
        filtre.append(BankAccountMatchRule.finans_hesap_id.in_(list(hesap_set)))
    kurallar = list(session.scalars(select(BankAccountMatchRule).where(or_(*filtre))).all())
    teknik: list[BankAccountMatchRule] = []
    engeller: list[str] = []
    for kural in kurallar:
        hedef = int(kural.finans_hesap_id) if kural.finans_hesap_id else None
        if hedef and hedef not in hesap_set:
            hedef_hesap = session.get(FinansHesabi, hedef)
            finansal = False
            if hedef_hesap is not None:
                finansal = _acilis_var(hedef_hesap) or _hareket_sayilari(session, [hedef])["toplam"] > 0
            if finansal:
                engeller.append(
                    f"Evo eşleştirme {kural.evo_banka_id} başka hesabın finansal kaydına bağlı; eşleştirme bozulmaz"
                )
            else:
                engeller.append(
                    f"Evo eşleştirme {kural.evo_banka_id} başka bir hesaba bağlı; silinemez"
                )
            continue
        teknik.append(kural)
    return teknik, engeller


def _kk_ozet(session: Session, kart_id: int) -> dict[str, Any]:
    kart = session.get(KrediKartiTanimi, int(kart_id))
    if kart is None:
        return _bos_ozet(
            kart_id=int(kart_id),
            tur="KREDI_KARTI",
            tur_etiket="Firma Kredi Kartı",
            engel_mesaji="Kredi kartı bulunamadı.",
            engeller=["Kredi kartı bulunamadı."],
        )
    kod = (kart.son_dort_hane or str(kart.id) or "").strip() or str(kart.id)
    ad = (kart.kart_adi or "").strip() or str(kart.id)
    engeller: list[str] = []
    hesap_ids: list[int] = []
    if kart.bagli_hesap_id:
        hesap = session.get(FinansHesabi, int(kart.bagli_hesap_id))
        if hesap is not None:
            hesap_ids = [int(hesap.id)]
            if _acilis_var(hesap):
                engeller.append(
                    f"Bağlı hesap «{hesap.hesap_adi}» açılış bakiyesi {hesap.acilis_bakiyesi}; silinemez"
                )
            if getattr(hesap, "muhasebe_hesap_id", None) or getattr(hesap, "muhasebe_komisyon_hesap_id", None):
                engeller.append(f"Bağlı hesap «{hesap.hesap_adi}» muhasebe hesabına bağlı; silinemez")
    hareket = _hareket_sayilari(session, hesap_ids)
    cumle = _hareket_cumlesi(hareket)
    if cumle:
        engeller.append(cumle)
    kk_say, kk_engel = _kk_kullanim_engelleri(session, [int(kart.id)], banka_mi=False)
    engeller.extend(kk_engel)
    belge_n, belge_engel = _hesap_belge_engelleri(session, hesap_ids)
    engeller.extend(belge_engel)
    muhasebe_n = _muhasebe_fis_sayisi(session, hesap_ids, [int(kart.id)])
    if muhasebe_n:
        engeller.append(f"{muhasebe_n} muhasebe fişi bu karta bağlı")
    acilis_n = 1 if any("açılış bakiyesi" in e for e in engeller) else 0
    return _bos_ozet(
        kart_id=int(kart.id),
        tur="KREDI_KARTI",
        tur_etiket="Firma Kredi Kartı",
        kod=kod,
        ad=ad,
        engeller=engeller,
        engel_mesaji=_mesaj("Firma Kredi Kartı", kod, ad, engeller),
        silinebilir=not engeller,
        hareket=hareket["toplam"],
        harcama=hareket["harcama"],
        odeme=hareket["odeme"],
        transfer=hareket["transfer"],
        acilis_hareket=hareket["acilis"],
        acilis_bakiye=acilis_n,
        kk_odeme=kk_say["kk_odeme"],
        ekstre=kk_say["ekstre"],
        ekstre_odeme=kk_say["ekstre_odeme"],
        gider_kart_odeme=kk_say["gider_kart_odeme"],
        muhasebe_bag=muhasebe_n + (1 if any("muhasebe" in e for e in engeller) else 0),
        belge=belge_n,
    )


def _banka_sil_uygula(session: Session, kart_id: int) -> None:
    kart = session.get(BankaKarti, int(kart_id))
    if kart is None:
        raise ValueError("Banka kartı bulunamadı.")
    hesaplar = _banka_hesaplari(session, kart.id)
    hesap_ids = [int(h.id) for h in hesaplar]
    hesap_set = set(hesap_ids)
    kod = (kart.hesap_no or kart.iban or str(kart.id) or "").strip()
    teknik, yabanci = _eslestirme_ayir(session, kart.id, hesap_set)
    if yabanci:
        raise ValueError("Eşleştirme başka bir hesabın kaydına bağlı; silinemez.")
    for kural in teknik:
        _engel_yaz(
            session,
            sistem=KAYNAK_EVO,
            kimlik=str(kural.evo_banka_id),
            kart_turu="BANKA",
            kart_kodu=kod,
            kart_adi=kart.banka_adi,
            neden=NEDEN_TEKNIK_ESLESME,
            evo_banka_adi=kural.evo_banka_adi,
            eski_kart_id=int(kart.id),
            eski_hesap_id=int(kural.finans_hesap_id) if kural.finans_hesap_id else None,
        )
        session.delete(kural)
    session.flush()

    for tanim in _kk_tanimlari(session, kart.id, hesap_ids):
        _kk_engel_yaz(session, tanim)
        session.delete(tanim)
    session.flush()

    if _hareket_sayilari(session, hesap_ids)["toplam"] or any(_acilis_var(h) for h in hesaplar):
        raise ValueError("Alt hesapta hareket veya açılış bakiyesi var; silinemez.")

    if kart.pos_aktarim_hesap_id:
        kart.pos_aktarim_hesap_id = None
        session.flush()

    if _tablo(session, PosTaksitKomisyon.__tablename__):
        for satir in session.scalars(
            select(PosTaksitKomisyon).where(PosTaksitKomisyon.banka_karti_id == kart.id)
        ).all():
            session.delete(satir)
    for hesap in hesaplar:
        session.delete(hesap)
    session.flush()
    session.expire(
        kart,
        ["alt_hesaplar", "kredi_kartlari", "pos_valor_kayitlari", "pos_taksit_komisyonlari", "banka_kredileri"],
    )
    session.delete(kart)
