"""Cari kart silme koruması — hareket / belge / birleştirme geçmişi.

Kesin kural: Geçmişte herhangi bir mali hareket görmüş cari silinemez
(fiziksel veya mantıksal). Bakiye sıfır / pasif yeterli değildir.

Belge bağlantısı (teklif, sipariş, irsaliye, fatura, iade, çek, …) da engeller.
Kontrol ile silme aynı oturumda (mümkünse satır kilidiyle) yapılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from database.models.cari import Cari, CariKaynakEngel

EVO_ID_RE = re.compile(r"Evo cari id\s+(\d+)", re.I)
EVO_KOD_RE = re.compile(r"Evo kod\s+([A-Za-z0-9_-]+)", re.I)
BIRLESTIR_RE = re.compile(r"BİRLEŞTİRİLDİ|BIRLESTIRILDI|MERGED-", re.I)
KAYNAK_EVO = "EVOBULUT"

_hazir_engine_id: int | None = None


def schema_hazirla(eng=None) -> None:
    """cari_kaynak_engelleri — tekrar çağrı güvenli."""
    global _hazir_engine_id
    from database.database import Base, engine

    bag = eng if eng is not None else engine
    if bag is None:
        return
    if eng is None and _hazir_engine_id == id(bag):
        return
    Base.metadata.create_all(bind=bag, tables=[CariKaynakEngel.__table__])
    if eng is None or eng is bag:
        _hazir_engine_id = id(bag)


def cari_kaynak_engelli_mi(kaynak_sistem: str, kaynak_kimlik: str) -> bool:
    schema_hazirla()
    kimlik = str(kaynak_kimlik or "").strip()
    sistem = str(kaynak_sistem or "").strip()
    if not kimlik or not sistem:
        return False
    from database.database import get_session

    with get_session() as session:
        return (
            session.scalar(
                select(CariKaynakEngel.id).where(
                    CariKaynakEngel.kaynak_sistem == sistem,
                    CariKaynakEngel.kaynak_kimlik == kimlik,
                )
            )
            is not None
        )


def cari_kaynak_engel_yaz(
    session: Session,
    *,
    kaynak_sistem: str,
    kaynak_kimlik: str,
    cari_kodu: str | None = None,
    unvan: str | None = None,
    neden: str | None = None,
) -> None:
    """Silinen boş cari kaynağını engelle — mükerrer yazım yok."""
    schema_hazirla()
    sistem = str(kaynak_sistem or "").strip()
    kimlik = str(kaynak_kimlik or "").strip()
    if not sistem or not kimlik:
        return
    mevcut = session.scalar(
        select(CariKaynakEngel).where(
            CariKaynakEngel.kaynak_sistem == sistem,
            CariKaynakEngel.kaynak_kimlik == kimlik,
        )
    )
    if mevcut is not None:
        return
    session.add(
        CariKaynakEngel(
            kaynak_sistem=sistem,
            kaynak_kimlik=kimlik,
            cari_kodu=(cari_kodu or "")[:40] or None,
            unvan=(unvan or "")[:200] or None,
            neden=(neden or "")[:500] or None,
        )
    )


def eslestirme_gerekli_mesaji(evo_id: str, unvan: str | None = None) -> str:
    ad = f" ({unvan})" if (unvan or "").strip() else ""
    return (
        f"Evo cari {evo_id}{ad} daha önce silinmiş boş karttı; "
        "kart yeniden oluşturulmadı. Yeni kaynak hareketi için eşleştirme gerekli."
    )

# (model_import_path, attr, etiket) — durum/is_deleted filtresi YOK (geçmiş de engeller)
_BELGE_MODELLERI: tuple[tuple[str, str, str], ...] = (
    ("database.models.satis_faturasi:SatisFaturasi", "cari_id", "satış faturası"),
    ("database.models.satis_siparisi:SatisSiparisi", "cari_id", "satış siparişi"),
    ("database.models.satis_irsaliyesi:SatisIrsaliyesi", "cari_id", "satış irsaliyesi"),
    ("database.models.satis_iade_faturasi:SatisIadeFaturasi", "cari_id", "satış iade faturası"),
    ("database.models.satis_teklifi:SatisTeklifi", "cari_id", "satış teklifi"),
    ("database.models.alis_faturasi:AlisFaturasi", "cari_id", "alış faturası"),
    ("database.models.alis_siparisi:AlisSiparisi", "cari_id", "alış siparişi"),
    ("database.models.alis_irsaliyesi:AlisIrsaliyesi", "cari_id", "alış irsaliyesi"),
    ("database.models.alis_iade_faturasi:AlisIadeFaturasi", "cari_id", "alış iade faturası"),
    ("database.models.hizmet_faturasi:HizmetFaturasi", "cari_id", "hizmet faturası"),
    ("database.models.konsinye:KonsinyeTeslim", "cari_id", "konsinye teslim"),
    ("database.models.odeme_sozu:OdemeSozu", "cari_id", "ödeme sözü"),
    ("database.models.tedarikci_teklif:TedarikciTeklif", "cari_id", "tedarikçi teklifi"),
    ("database.models.tedarikci_fiyat:TedarikciFiyat", "cari_id", "tedarikçi fiyat"),
)


@dataclass
class CariSilmeDurumu:
    cari_id: int
    cari_kodu: str = ""
    unvan: str = ""
    silinebilir: bool = False
    nedenler: list[str] = field(default_factory=list)
    baglantilar: dict[str, int] = field(default_factory=dict)
    evo_id: str | None = None
    evo_kod: str | None = None

    @property
    def neden_metni(self) -> str:
        if self.silinebilir:
            return ""
        return "\n".join(self.nedenler) if self.nedenler else "Bu cari silinemez."


def _yukle_model(yol: str):
    mod_yol, sinif = yol.split(":")
    import importlib

    mod = importlib.import_module(mod_yol)
    return getattr(mod, sinif)


def _say(session: Session, model, kolon: str, cari_id: int) -> int:
    """Sayım; PG'de tablo/kolon yoksa savepoint ile transaction'ı bozmadan 0."""
    try:
        with session.begin_nested():
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(getattr(model, kolon) == int(cari_id))
                )
                or 0
            )
    except Exception:
        return 0


def _tablo_say(session: Session, tablo: str, kolon: str, cari_id: int) -> int:
    """Ham tablo sayımı; eksik tablo PG abort etmesin diye nested savepoint."""
    try:
        with session.begin_nested():
            return int(
                session.execute(
                    text(f'SELECT COUNT(*) FROM "{tablo}" WHERE "{kolon}" = :c'),
                    {"c": int(cari_id)},
                ).scalar()
                or 0
            )
    except Exception:
        return 0


def evo_meta(cari: Cari | None) -> tuple[str | None, str | None]:
    if cari is None:
        return None, None
    n = cari.ozel_notlar or ""
    m1 = EVO_ID_RE.search(n)
    m2 = EVO_KOD_RE.search(n)
    eid = m1.group(1) if m1 else None
    ekod = m2.group(1) if m2 else None
    # Kabuk kartlarda not boş olabilir; kod EVO-3066 biçiminde
    if eid is None:
        kod = (cari.cari_kodu or "").strip()
        m3 = re.match(r"^EVO-(\d+)$", kod, re.I)
        if m3:
            eid = m3.group(1)
            ekod = ekod or kod
    return (eid, ekod)


def cari_kilitle(session: Session, cari_id: int) -> Cari | None:
    """Mümkünse satır kilidi; SQLite'ta normal get."""
    try:
        return session.scalar(
            select(Cari).where(Cari.id == int(cari_id)).with_for_update()
        )
    except Exception:
        return session.get(Cari, int(cari_id))


def silme_durumu(
    cari_id: int,
    *,
    session: Session | None = None,
    kilitle: bool = False,
) -> CariSilmeDurumu:
    """Silinebilir mi? Somut nedenlerle döner. session verilirse aynı transaction kullanılır."""
    from database.database import get_session

    def _calis(sess: Session) -> CariSilmeDurumu:
        cari = cari_kilitle(sess, cari_id) if kilitle else sess.get(Cari, int(cari_id))
        if cari is None:
            return CariSilmeDurumu(
                cari_id=int(cari_id),
                silinebilir=False,
                nedenler=["Cari kart bulunamadı."],
            )
        eid, ekod = evo_meta(cari)
        durum = CariSilmeDurumu(
            cari_id=int(cari.id),
            cari_kodu=cari.cari_kodu or "",
            unvan=cari.unvan or "",
            evo_id=eid,
            evo_kod=ekod,
        )
        if bool(getattr(cari, "is_deleted", False)):
            durum.nedenler.append("Bu cari zaten silinmiş.")
            return durum

        # Alt hesap / üst bağlantı
        n_alt = int(
            sess.scalar(
                select(func.count())
                .select_from(Cari)
                .where(
                    Cari.ust_cari_id == int(cari.id),
                    or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                )
            )
            or 0
        )
        if n_alt:
            durum.baglantilar["alt_cari"] = n_alt
            durum.nedenler.append(f"{n_alt} alt cari hesabı var; silinemez.")

        # Bakiye sıfır değilse engelle — hareket yok ama açılış/kalan borç olabilir
        try:
            from decimal import Decimal

            from database.cari_service import CariService

            ozet = CariService._ozet(cari, session=sess)
            bak = Decimal(str(ozet.get("bakiye") or 0))
            if abs(bak) > Decimal("0.005"):
                durum.baglantilar["bakiye"] = 1
                durum.nedenler.append(f"Bakiyesi sıfır değil ({bak}); silinemez.")
        except Exception:
            # Sorgu hatası → silinemez say (C grubu); “kullanım yok” deme
            durum.nedenler.append(
                "Bakiye/kullanım sorgusu tamamlanamadı; doğrulanana kadar silinemez."
            )
            durum.silinebilir = False
            return durum

        # — Mali hareket geçmişi (iptal/silinmiş dahil; yalnız mevcut tablo) —
        from database.models.cari import CariIslem, CariKapatma, SatisHareketi

        n_ci = _say(sess, CariIslem, "cari_id", cari.id)
        if n_ci:
            durum.baglantilar["cari_islemleri"] = n_ci
            durum.nedenler.append(f"{n_ci} cari işlem kaydı var; silinemez.")
        n_sh = _say(sess, SatisHareketi, "cari_id", cari.id)
        if n_sh:
            durum.baglantilar["satis_hareketleri"] = n_sh
            durum.nedenler.append(f"{n_sh} satış hareketi var; silinemez.")
        n_kap = _say(sess, CariKapatma, "cari_id", cari.id)
        if n_kap:
            durum.baglantilar["cari_kapatmalar"] = n_kap
            durum.nedenler.append(f"{n_kap} kapatma kaydı var; silinemez.")

        # USD karşılık / virman karşı taraf
        n_usd = _tablo_say(sess, "cari_usd_karsilik", "cari_id", cari.id)
        if n_usd:
            durum.baglantilar["cari_usd_karsilik"] = n_usd
            durum.nedenler.append(
                f"Bu cari hareket geçmişi bulunduğundan silinemez ({n_usd} USD karşılık)."
            )
        n_karsi = _tablo_say(sess, "cari_islemleri", "karsi_cari_id", cari.id)
        if n_karsi:
            durum.baglantilar["karsi_cari_islem"] = n_karsi
            durum.nedenler.append(
                f"Bu cari hareket geçmişi bulunduğundan silinemez "
                f"({n_karsi} karşı cari işlem)."
            )

        # Finans hareketleri (cari_id kolonu)
        for tablo, etiket in (
            ("finans_hareketleri", "finans hareketi"),
            ("kk_cekimleri", "kredi kartı çekimi"),
            ("cek_senet_evraklar", "çek/senet"),
            ("fon_hareketleri", "fon hareketi"),
            ("hizli_satis_fisleri", "hızlı satış fişi"),
            ("acik_kalem_gecis", "açık kalem geçiş"),
        ):
            n = _tablo_say(sess, tablo, "cari_id", cari.id)
            if n:
                durum.baglantilar[tablo] = n
                durum.nedenler.append(
                    f"Bu cari hareket geçmişi bulunduğundan silinemez ({n} {etiket})."
                )

        # Operasyonel / belge bağlantıları
        for yol, kolon, etiket in _BELGE_MODELLERI:
            try:
                model = _yukle_model(yol)
            except Exception:
                continue
            n = _say(sess, model, kolon, cari.id)
            if n:
                durum.baglantilar[etiket] = n
                durum.nedenler.append(f"{n} {etiket} kaydı var; silinemez.")

        # Çek senet ilgili_cari / stok sahip
        for tablo, kolon, etiket in (
            ("cek_senet_evraklar", "ilgili_cari_id", "çek/senet (ilgili cari)"),
            ("stok_kartlari", "sahip_cari_id", "stok kartı (sahip)"),
            ("masraf_dagitimlari", "kaynak_cari_id", "masraf dağıtımı"),
            ("proje_carileri", "cari_id", "proje"),
            ("aktiviteler", "cari_id", "aktivite"),
            ("sorulan_urunler", "cari_id", "sorulan ürün"),
            ("sabit_giderler", "cari_id", "sabit gider"),
        ):
            n = _tablo_say(sess, tablo, kolon, cari.id)
            if n:
                durum.baglantilar[f"{tablo}.{kolon}"] = n
                durum.nedenler.append(
                    f"Bu cari {etiket} bağlantısı bulunduğundan silinemez ({n} kayıt)."
                )

        # Birleştirme / taşıma izi — bugün boş görünse bile geçmiş vardır
        kod = (cari.cari_kodu or "").upper()
        notlar = cari.ozel_notlar or ""
        if kod.startswith("MERGED-") or BIRLESTIR_RE.search(notlar):
            durum.baglantilar["birlestirme_izi"] = 1
            durum.nedenler.append(
                "Bu cari birleştirme/taşıma geçmişi bulunduğundan silinemez "
                "(hareketler başka karta taşınmış olabilir)."
            )

        # Başka kart bu id'ye birleştirilmiş diye yazmış mı?
        baska = sess.scalar(
            select(func.count())
            .select_from(Cari)
            .where(
                Cari.id != int(cari.id),
                or_(
                    Cari.ozel_notlar.ilike(f"%cari_id={int(cari.id)}%"),
                    Cari.ozel_notlar.ilike(f"%→ cari_id={int(cari.id)}%"),
                ),
            )
        ) or 0
        if baska:
            durum.baglantilar["birlestirme_hedefi"] = int(baska)
            # Hedef kart korunur; engel değil — bilgi amaçlı. Silinebilirliği bozmaz.

        # Silinen kayıt günlüğünde bu cariye taşınmış hareket notu (şüphe → engelle)
        try:
            from database.models.deleted_record import DeletedRecordLog

            n_log = sess.scalar(
                select(func.count())
                .select_from(DeletedRecordLog)
                .where(
                    DeletedRecordLog.entity_type == "cari",
                    DeletedRecordLog.record_id == str(int(cari.id)),
                    DeletedRecordLog.restore_status == "none",
                )
            ) or 0
            if n_log:
                durum.nedenler.append("Bu cari için açık silme günlüğü zaten var.")
        except Exception:
            pass

        # Tekrarlayan nedenleri sadeleştir
        seen: set[str] = set()
        tekil: list[str] = []
        for n in durum.nedenler:
            if n not in seen:
                seen.add(n)
                tekil.append(n)
        durum.nedenler = tekil
        durum.silinebilir = len(durum.nedenler) == 0
        return durum

    if session is not None:
        return _calis(session)
    with get_session() as sess:
        return _calis(sess)


def silme_engeli_yukselt(durum: CariSilmeDurumu) -> None:
    """SoftDeleteError mesajı için tek satırlık özet."""
    if durum.silinebilir:
        return
    raise ValueError(durum.neden_metni)


def evo_id_ile_aktif_cari(session: Session, evo_id: str) -> Cari | None:
    """Aynı Evo cari id'sine sahip silinmemiş kart (yeniden aktarım koruması)."""
    eid = str(evo_id or "").strip()
    if not eid:
        return None
    for c in session.scalars(
        select(Cari).where(or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)))
    ):
        m = EVO_ID_RE.search(c.ozel_notlar or "")
        if m and m.group(1) == eid:
            return c
    return None


def evo_id_silinmis_mi(session: Session, evo_id: str) -> dict[str, Any] | None:
    """Silinmiş mükerrer logunda / soft-delete kartta aynı Evo id var mı?"""
    eid = str(evo_id or "").strip()
    if not eid:
        return None
    for c in session.scalars(select(Cari).where(Cari.is_deleted.is_(True))):
        m = EVO_ID_RE.search(c.ozel_notlar or "")
        if m and m.group(1) == eid:
            return {
                "cari_id": int(c.id),
                "cari_kodu": c.cari_kodu,
                "unvan": c.unvan,
                "is_deleted": True,
            }
    try:
        from database.models.deleted_record import DeletedRecordLog

        for log in session.scalars(
            select(DeletedRecordLog).where(
                DeletedRecordLog.entity_type == "cari",
                DeletedRecordLog.deletion_reason.in_(("Mükerrer kayıt", "Mükerrer kayıt")),
            )
        ):
            snap = log.snapshot_json or ""
            if f"Evo cari id {eid}" in snap or f'"evo_id": "{eid}"' in snap:
                return {
                    "log_id": int(log.id),
                    "record_id": log.record_id,
                    "record_code": log.record_code,
                    "is_deleted": True,
                }
    except Exception:
        pass
    return None
