"""Çek / Senet servis katmanı — CRUD, operasyonel akışlar, cari/finans posting ve raporlar (Aşama 5)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from database.database import get_session
from database.models.cek_senet import (
    DURUM_BANKAYA_TAHSILE,
    DURUM_BANKAYA_TEMINATA,
    DURUM_CIRO_EDILDI,
    DURUM_IADE,
    DURUM_IPTAL,
    DURUM_KARSILIKSIZ,
    DURUM_KISMI_ODENDI,
    DURUM_KISMI_TAHSIL,
    DURUM_ODENDI,
    DURUM_PORTFOYDE,
    DURUM_PROTESTO,
    DURUM_TAHSIL_EDILDI,
    DURUM_TEDARIKCIYE_VERILDI,
    DURUM_VADESI_GECTI,
    DURUM_ETIKETLERI,
    EVRAK_TURU_FIRMA_CEKI,
    EVRAK_TURU_FIRMA_SENEDI,
    EVRAK_TURU_MUSTERI_CEKI,
    EVRAK_TURU_MUSTERI_SENEDI,
    EVRAK_TURLERI,
    ISLEM_YONU_ALINAN,
    ISLEM_YONU_VERILEN,
    PORTFOY_ONEK,
    CekSenetEvrak,
    CekSenetHareket,
)

# Düzenleme / iptal için izinli durumlar (Aşama 2)
DUZENLENEBILIR_DURUMLAR = frozenset({DURUM_PORTFOYDE, DURUM_TEDARIKCIYE_VERILDI})
IPTAL_EDILEBILIR_DURUMLAR = frozenset({DURUM_PORTFOYDE, DURUM_TEDARIKCIYE_VERILDI})

# Aşama 3 — operasyonel geçişler
BANKAYA_VERILEBILIR = frozenset({DURUM_PORTFOYDE})
CIRO_EDILEBILIR = frozenset({DURUM_PORTFOYDE})
TAHSIL_EDILEBILIR = frozenset(
    {DURUM_PORTFOYDE, DURUM_BANKAYA_TAHSILE, DURUM_KISMI_TAHSIL}
)
ODE_EDILEBILIR = frozenset(
    {DURUM_TEDARIKCIYE_VERILDI, DURUM_KISMI_ODENDI, DURUM_PORTFOYDE}
)
IADE_EDILEBILIR = frozenset(
    {
        DURUM_PORTFOYDE,
        DURUM_BANKAYA_TAHSILE,
        DURUM_BANKAYA_TEMINATA,
        DURUM_CIRO_EDILDI,
        DURUM_TEDARIKCIYE_VERILDI,
        DURUM_KISMI_TAHSIL,
        DURUM_KISMI_ODENDI,
    }
)
KARSILIKSIZ_EDILEBILIR = frozenset(
    {DURUM_PORTFOYDE, DURUM_BANKAYA_TAHSILE, DURUM_BANKAYA_TEMINATA, DURUM_CIRO_EDILDI}
)

# Aşama 4 — cari/finans belge önekleri ve portföy hesap etiketi (FinansHesabi değil)
PORTFOY_HESAP_ADI = "ÇEK/SENET PORTFÖY"
BELGE_ALINAN_KAYIT = "ACS"  # alınan kayıt → cari tahsilat etkisi
BELGE_VERILEN_KAYIT = "VCS"  # verilen kayıt → cari ödeme etkisi
BELGE_TAHSIL = "CST"  # kasa/banka giriş
BELGE_ODEME = "CSO"  # kasa/banka çıkış
BELGE_CIRO = "CSC"
BELGE_IADE = "CSI"
BELGE_KARSILIKSIZ = "CSK"

# Açık (kapanmamış) evrak durumları — özet kutuları ve Aşama 5 raporları
ACIK_DURUMLAR = frozenset(
    {
        DURUM_PORTFOYDE,
        DURUM_BANKAYA_TAHSILE,
        DURUM_BANKAYA_TEMINATA,
        DURUM_TEDARIKCIYE_VERILDI,
        DURUM_KISMI_TAHSIL,
        DURUM_KISMI_ODENDI,
        DURUM_VADESI_GECTI,
        DURUM_CIRO_EDILDI,
        DURUM_KARSILIKSIZ,
        DURUM_PROTESTO,
    }
)


def _d(val) -> Decimal:
    return Decimal(str(val or 0))


def _decimal(deger: object, alan: str, minimum: Decimal | None = None) -> Decimal:
    try:
        if isinstance(deger, Decimal):
            sonuc = deger
        else:
            metin = str(deger).strip()
            if not metin:
                raise ValueError
            if "," in metin:
                metin = metin.replace(".", "").replace(",", ".")
            sonuc = Decimal(metin)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from None
    if minimum is not None and sonuc < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return sonuc


def _tarih_oku(deger: object, alan: str) -> date:
    if isinstance(deger, date) and not isinstance(deger, datetime):
        return deger
    if isinstance(deger, datetime):
        return deger.date()
    metin = str(deger or "").strip()
    if not metin:
        raise ValueError(f"{alan} zorunludur.")
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{alan} GG.AA.YYYY formatında olmalıdır.")


def _evrak_turu_etiket(kod: str) -> str:
    return dict(EVRAK_TURLERI).get(kod, kod or "")


def _durum_etiket(kod: str) -> str:
    return DURUM_ETIKETLERI.get(kod, kod or "")


def _evrak_turu_coz(basit_tur: str, islem_yonu: str) -> str:
    """Çek/Senet + Alınan/Verilen → model evrak_turu."""
    tur = (basit_tur or "").strip().upper()
    yon = (islem_yonu or "").strip().upper()
    if tur in ("CEK", "ÇEK"):
        tur = "CEK"
    elif tur in ("SENET",):
        tur = "SENET"
    elif tur in (
        EVRAK_TURU_MUSTERI_CEKI,
        EVRAK_TURU_MUSTERI_SENEDI,
        EVRAK_TURU_FIRMA_CEKI,
        EVRAK_TURU_FIRMA_SENEDI,
    ):
        return tur
    else:
        raise ValueError("Evrak türü Çek veya Senet olmalıdır.")

    if yon not in (ISLEM_YONU_ALINAN, ISLEM_YONU_VERILEN):
        raise ValueError("İşlem yönü Alınan veya Verilen olmalıdır.")

    if yon == ISLEM_YONU_ALINAN:
        return EVRAK_TURU_MUSTERI_CEKI if tur == "CEK" else EVRAK_TURU_MUSTERI_SENEDI
    return EVRAK_TURU_FIRMA_CEKI if tur == "CEK" else EVRAK_TURU_FIRMA_SENEDI


def _basit_tur(evrak_turu: str) -> str:
    if evrak_turu in (EVRAK_TURU_MUSTERI_CEKI, EVRAK_TURU_FIRMA_CEKI):
        return "CEK"
    if evrak_turu in (EVRAK_TURU_MUSTERI_SENEDI, EVRAK_TURU_FIRMA_SENEDI):
        return "SENET"
    return ""


class CekSenetService:
    @staticmethod
    def schema_hazirla() -> None:
        """Mevcut firma DB'de çek/senet tabloları yoksa oluştur (checkfirst)."""
        from database.database import engine
        # FK çözümlemesi için finans/cari tabloları metadata'da olmalı
        import database.models.cari  # noqa: F401
        import database.models.finans  # noqa: F401

        for tablo in (CekSenetEvrak.__table__, CekSenetHareket.__table__):
            tablo.create(engine, checkfirst=True)

    @staticmethod
    def portfoy_no_uret(
        evrak_turu: str,
        islem_yonu: str,
        yil: int | None = None,
        session=None,
    ) -> str:
        """ALÇ/ALS/VRÇ/VRS-YYYY-NNNNNN üret. session verilmezse kısa oturum açar."""
        yil = yil or date.today().year
        onek = PORTFOY_ONEK.get((evrak_turu, islem_yonu), "PRT")
        like = f"{onek}-{yil}-%"

        def _uret(sess) -> str:
            mevcut = sess.scalars(
                select(CekSenetEvrak.portfoy_no).where(CekSenetEvrak.portfoy_no.like(like))
            ).all()
            sira = 1
            for no in mevcut:
                try:
                    sira = max(sira, int(str(no).rsplit("-", 1)[-1]) + 1)
                except ValueError:
                    pass
            return f"{onek}-{yil}-{sira:06d}"

        if session is not None:
            return _uret(session)
        with get_session() as sess:
            return _uret(sess)

    @staticmethod
    def _satir_dict(evrak: CekSenetEvrak, bugun: date | None = None) -> dict[str, Any]:
        bugun = bugun or date.today()
        kalan_gun = (evrak.vade_tarihi - bugun).days if evrak.vade_tarihi else None
        cari = evrak.cari
        return {
            "id": evrak.id,
            "portfoy_no": evrak.portfoy_no or "",
            "evrak_turu": evrak.evrak_turu,
            "evrak_turu_etiket": _evrak_turu_etiket(evrak.evrak_turu),
            "basit_tur": _basit_tur(evrak.evrak_turu),
            "islem_yonu": evrak.islem_yonu,
            "islem_yonu_etiket": "Alınan" if evrak.islem_yonu == ISLEM_YONU_ALINAN else "Verilen",
            "evrak_no": evrak.evrak_no or "",
            "seri_no": evrak.seri_no or "",
            "cari_id": evrak.cari_id,
            "cari_kodu": cari.cari_kodu if cari else "",
            "cari_adi": cari.unvan if cari else "",
            "banka": evrak.banka_adi or "",
            "banka_adi": evrak.banka_adi or "",
            "banka_subesi": evrak.banka_subesi or "",
            "sube_kodu": evrak.sube_kodu or "",
            "hesap_no": evrak.hesap_no or "",
            "iban": evrak.iban or "",
            "cek_no": evrak.cek_no or "",
            "senet_no": evrak.senet_no or "",
            "kesideci_adi": evrak.kesideci_adi or "",
            "kesideci_vergi_tc": evrak.kesideci_vergi_tc or "",
            "keside_yeri": evrak.keside_yeri or "",
            "hesap_sahibi": evrak.hesap_sahibi or "",
            "lehtar": evrak.lehtar or "",
            "teslim_eden": evrak.teslim_eden or "",
            "borclu_adi": evrak.borclu_adi or "",
            "borclu_vergi_tc": evrak.borclu_vergi_tc or "",
            "kefil": evrak.kefil or "",
            "duzenleme_yeri": evrak.duzenleme_yeri or "",
            "odeme_yeri": evrak.odeme_yeri or "",
            "kesideci_borclu": evrak.kesideci_adi or evrak.borclu_adi or "",
            "duzenleme_tarihi": evrak.duzenleme_tarihi,
            "vade_tarihi": evrak.vade_tarihi,
            "kalan_gun": kalan_gun,
            "doviz_turu": evrak.doviz_turu or "TL",
            "doviz_tutari": _d(evrak.doviz_tutari),
            "kur": _d(evrak.kur),
            "tl_tutari": _d(evrak.tl_tutari),
            "tahsil_edilen": _d(evrak.tahsil_edilen_tutar),
            "kalan_tutar": _d(evrak.kalan_tutar),
            "durum": evrak.durum,
            "durum_etiket": _durum_etiket(evrak.durum),
            "bulundugu_yer": evrak.bulundugu_yer or "",
            "son_islem_tarihi": evrak.son_islem_tarihi,
            "aciklama": evrak.aciklama or "",
            "ozel_not": evrak.ozel_not or "",
            "created_by": evrak.created_by or "",
            "aktif": bool(evrak.aktif),
            "duzenlenebilir": evrak.durum in DUZENLENEBILIR_DURUMLAR and bool(evrak.aktif),
            "iptal_edilebilir": evrak.durum in IPTAL_EDILEBILIR_DURUMLAR and bool(evrak.aktif),
        }

    @staticmethod
    def _hareket_ekle(
        session,
        evrak: CekSenetEvrak,
        *,
        onceki_durum: str | None,
        yeni_durum: str,
        islem_turu: str,
        tutar: Decimal | None = None,
        aciklama: str | None = None,
        kullanici: str | None = None,
        ilgili_cari_id: int | None = None,
        ilgili_banka_kasa_id: int | None = None,
        cari_hareket_id: int | None = None,
        finans_hareket_id: int | None = None,
        muhasebe_fisi_id: int | None = None,
    ) -> CekSenetHareket:
        h = CekSenetHareket(
            evrak_id=evrak.id,
            tarih=datetime.now(),
            onceki_durum=onceki_durum,
            yeni_durum=yeni_durum,
            islem_turu=islem_turu,
            tutar=tutar,
            aciklama=aciklama,
            ilgili_cari_id=ilgili_cari_id if ilgili_cari_id is not None else evrak.cari_id,
            ilgili_banka_kasa_id=ilgili_banka_kasa_id,
            cari_hareket_id=cari_hareket_id,
            finans_hareket_id=finans_hareket_id,
            muhasebe_fisi_id=muhasebe_fisi_id,
            kullanici=kullanici,
        )
        session.add(h)
        session.flush()
        return h

    @staticmethod
    def _evrak_yukle(session, evrak_id: int) -> CekSenetEvrak:
        from sqlalchemy.orm import selectinload

        evrak = session.scalars(
            select(CekSenetEvrak)
            .options(selectinload(CekSenetEvrak.cari))
            .where(CekSenetEvrak.id == int(evrak_id))
        ).first()
        if not evrak:
            raise ValueError("Evrak bulunamadı.")
        if not evrak.aktif:
            raise ValueError("Pasif evrak üzerinde işlem yapılamaz.")
        return evrak

    @staticmethod
    def _finans_hesap_dogrula(session, hesap_id: int | None, *, zorunlu: bool = True):
        """Finans hesabı (kasa/banka) doğrula; yoksa ValueError."""
        if hesap_id in ("", None):
            if zorunlu:
                raise ValueError("Kasa / banka hesabı seçin.")
            return None
        try:
            hid = int(hesap_id)
        except (TypeError, ValueError) as e:
            raise ValueError("Geçerli bir kasa / banka hesabı seçin.") from e
        from database.models.finans import FinansHesabi

        hesap = session.get(FinansHesabi, hid)
        if hesap is None or not hesap.aktif:
            raise ValueError("Seçilen kasa / banka hesabı bulunamadı.")
        return hesap

    @staticmethod
    def _islem_tarihi(deger: object | None) -> date:
        if deger in (None, ""):
            return date.today()
        return _tarih_oku(deger, "İşlem tarihi")

    # ——— Aşama 4: cari / finans posting yardımcıları ———

    @staticmethod
    def _belge_ozeti(portfoy_no: str | None, evrak_no: str | None) -> str:
        p = (portfoy_no or "").strip()
        e = (evrak_no or "").strip()
        if p and e:
            return f"{p} / {e}"
        return p or e or "çek/senet"

    @staticmethod
    def _kayit_hareketi(session, evrak_id: int) -> CekSenetHareket | None:
        return session.scalars(
            select(CekSenetHareket)
            .where(
                CekSenetHareket.evrak_id == int(evrak_id),
                CekSenetHareket.islem_turu == "KAYIT",
            )
            .order_by(CekSenetHareket.id.asc())
        ).first()

    @staticmethod
    def _cari_islem_belge_no(session, cari_hareket_id: int | None) -> str | None:
        if not cari_hareket_id:
            return None
        from database.models.cari import CariIslem

        islem = session.get(CariIslem, int(cari_hareket_id))
        return (islem.belge_no if islem else None) or None

    @staticmethod
    def _cari_tahsilat_yaz(
        session,
        *,
        cari_id: int,
        tarih: date,
        tutar: Decimal,
        belge_onek: str,
        hesap_adi: str,
        aciklama: str,
    ) -> tuple[int, str]:
        """Cari tahsilat satırı (alacak) + FIFO; finans yok. (islem_id, belge_no)."""
        from database.cari_service import CariService
        from database.models.cari import Cari, CariIslem

        if tutar <= 0:
            raise ValueError("Posting tutarı pozitif olmalıdır.")
        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        belge_no = CariService._belge_no(session, belge_onek)
        CariService._aciklara_uygula(session, cari.id, tutar)
        islem = CariIslem(
            cari_id=cari.id,
            tarih=tarih,
            islem_turu="Tahsilat",
            belge_no=belge_no,
            aciklama=aciklama,
            borc=Decimal("0"),
            alacak=tutar,
            hesap_adi=hesap_adi,
        )
        session.add(islem)
        session.flush()
        return int(islem.id), belge_no

    @staticmethod
    def _cari_odeme_yaz(
        session,
        *,
        cari_id: int,
        tarih: date,
        tutar: Decimal,
        belge_onek: str,
        hesap_adi: str,
        aciklama: str,
    ) -> tuple[int, str]:
        """Cari ödeme satırı (finans_service._cari_odeme_satiri ile aynı mantık)."""
        from database.cari_service import CariService
        from database.models.cari import Cari, CariIslem, SatisHareketi

        if tutar <= 0:
            raise ValueError("Posting tutarı pozitif olmalıdır.")
        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        belge_no = CariService._belge_no(session, belge_onek)
        if (cari.cari_turu or "") == "Tedarikçi":
            kalan = CariService._aciklara_uygula(session, cari.id, tutar)
            if kalan > 0:
                session.add(
                    SatisHareketi(
                        cari_id=cari.id,
                        satis_tarihi=tarih,
                        belge_no=belge_no,
                        satis_tutari=Decimal("0"),
                        kalan_acik_tutar=-kalan,
                    )
                )
            islem = CariIslem(
                cari_id=cari.id,
                tarih=tarih,
                islem_turu="Ödeme",
                belge_no=belge_no,
                aciklama=aciklama,
                borc=Decimal("0"),
                alacak=tutar,
                hesap_adi=hesap_adi,
            )
        else:
            session.add(
                SatisHareketi(
                    cari_id=cari.id,
                    satis_tarihi=tarih,
                    belge_no=belge_no,
                    satis_tutari=tutar,
                    kalan_acik_tutar=tutar,
                )
            )
            islem = CariIslem(
                cari_id=cari.id,
                tarih=tarih,
                islem_turu="Ödeme",
                belge_no=belge_no,
                aciklama=aciklama,
                borc=tutar,
                alacak=Decimal("0"),
                hesap_adi=hesap_adi,
            )
        session.add(islem)
        session.flush()
        return int(islem.id), belge_no

    @staticmethod
    def _cari_tahsilat_kismi_geri(
        session,
        *,
        cari_id: int,
        tarih: date,
        tutar: Decimal,
        belge_onek: str,
        hesap_adi: str,
        aciklama: str,
        islem_turu: str = "Çek İade",
    ) -> tuple[int, str]:
        """Tahsilat/ödeme etkisini kısmen geri alır (borç + FIFO geri aç)."""
        from database.cari_service import CariService
        from database.models.cari import Cari, CariIslem

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401

        if tutar <= 0:
            raise ValueError("Geri alma tutarı pozitif olmalıdır.")
        cari = session.get(Cari, int(cari_id))
        if cari is None:
            raise ValueError("Cari bulunamadı.")
        belge_no = CariService._belge_no(session, belge_onek)
        CariService._aciklara_geri_al(session, cari.id, tutar, belge_no)
        islem = CariIslem(
            cari_id=cari.id,
            tarih=tarih,
            islem_turu=islem_turu,
            belge_no=belge_no,
            aciklama=aciklama,
            borc=tutar,
            alacak=Decimal("0"),
            hesap_adi=hesap_adi,
        )
        session.add(islem)
        session.flush()
        return int(islem.id), belge_no

    @staticmethod
    def _finans_hareket_yaz(
        session,
        *,
        hesap,
        tarih: date,
        tutar: Decimal,
        belge_onek: str,
        hareket_turu: str,
        aciklama: str,
        cikis: bool = False,
    ) -> tuple[int, str]:
        from database.finans_service import FinansService
        from database.models.finans import FinansHareketi

        if tutar <= 0:
            raise ValueError("Finans tutarı pozitif olmalıdır.")
        if cikis:
            FinansService.cikis_kontrol(hesap, tutar)
        belge_no = FinansService._finans_belge_no(session, belge_onek)
        har = FinansHareketi(
            hesap_id=hesap.id,
            tarih=tarih,
            hareket_turu=hareket_turu,
            belge_no=belge_no,
            tutar=tutar,
            aciklama=aciklama,
        )
        session.add(har)
        session.flush()
        return int(har.id), belge_no

    @staticmethod
    def _kayit_cari_posta(session, evrak: CekSenetEvrak, hareket: CekSenetHareket) -> None:
        """Alınan → cari tahsilat; verilen → cari ödeme. Portföy finans hesabına yazılmaz."""
        if hareket.cari_hareket_id:
            return
        tutar = _d(evrak.tl_tutari)
        if tutar <= 0:
            return
        ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)
        tarih = evrak.duzenleme_tarihi or date.today()
        if evrak.islem_yonu == ISLEM_YONU_ALINAN:
            cid, belge = CekSenetService._cari_tahsilat_yaz(
                session,
                cari_id=int(evrak.cari_id),
                tarih=tarih,
                tutar=tutar,
                belge_onek=BELGE_ALINAN_KAYIT,
                hesap_adi=PORTFOY_HESAP_ADI,
                aciklama=f"Alınan çek/senet kayıt {ozet}",
            )
        else:
            cid, belge = CekSenetService._cari_odeme_yaz(
                session,
                cari_id=int(evrak.cari_id),
                tarih=tarih,
                tutar=tutar,
                belge_onek=BELGE_VERILEN_KAYIT,
                hesap_adi=PORTFOY_HESAP_ADI,
                aciklama=f"Verilen çek/senet kayıt {ozet}",
            )
        hareket.cari_hareket_id = cid
        evrak.referans_belge_no = belge
        onceki_acik = (hareket.aciklama or "").strip()
        hareket.aciklama = f"[{belge}] {onceki_acik}" if onceki_acik else f"[{belge}]"

    @staticmethod
    def _kayit_cari_tam_geri_al(session, evrak: CekSenetEvrak) -> None:
        """KAYIT cari postunu tamamen siler (iptal için)."""
        from database.finans_service import FinansService

        # _aciklara_geri_al AlisFaturasi ilişkilerini çözer; mapper için modeller yüklenmeli
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401

        kayit = CekSenetService._kayit_hareketi(session, evrak.id)
        if not kayit or not kayit.cari_hareket_id:
            return
        belge = CekSenetService._cari_islem_belge_no(session, kayit.cari_hareket_id)
        if belge:
            FinansService._havale_cari_geri_al(session, belge)
        kayit.cari_hareket_id = None
        if evrak.referans_belge_no and belge and evrak.referans_belge_no == belge:
            evrak.referans_belge_no = None

    @staticmethod
    def _ciro_cari_geri_al(session, evrak: CekSenetEvrak) -> None:
        from database.finans_service import FinansService

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401

        ciro = session.scalars(
            select(CekSenetHareket)
            .where(
                CekSenetHareket.evrak_id == evrak.id,
                CekSenetHareket.islem_turu == "CIRO",
                CekSenetHareket.cari_hareket_id.isnot(None),
            )
            .order_by(CekSenetHareket.id.desc())
        ).first()
        if not ciro:
            return
        belge = CekSenetService._cari_islem_belge_no(session, ciro.cari_hareket_id)
        if belge:
            FinansService._havale_cari_geri_al(session, belge)
        ciro.cari_hareket_id = None

    @staticmethod
    def _muhasebe_posta_engeli(session, evrak: CekSenetEvrak, *, islem: str) -> None:
        """Düzenleme / iptal öncesi: finans postu varsa engelle."""
        hareketler = session.scalars(
            select(CekSenetHareket).where(CekSenetHareket.evrak_id == evrak.id)
        ).all()
        if any(h.finans_hareket_id for h in hareketler):
            raise ValueError(
                f"Bu evrakta kasa/banka hareketi var; {islem} yapılamaz. "
                "Önce tahsil/ödeme kayıtlarını kontrol edin."
            )

    @staticmethod
    def _verileri_dogrula(veriler: dict[str, Any], *, guncelleme: bool = False) -> dict[str, Any]:
        islem_yonu = (veriler.get("islem_yonu") or "").strip().upper()
        if islem_yonu in ("ALINAN", "VERILEN"):
            pass
        elif islem_yonu in ("ALINAN (MÜŞTERİDEN)", "ALINAN (MUSTERI)"):
            islem_yonu = ISLEM_YONU_ALINAN
        else:
            # UI'dan gelebilir
            etiket = (veriler.get("islem_yonu") or "").strip()
            if etiket.lower().startswith("alınan") or etiket.lower().startswith("alinan"):
                islem_yonu = ISLEM_YONU_ALINAN
            elif etiket.lower().startswith("verilen"):
                islem_yonu = ISLEM_YONU_VERILEN
            else:
                raise ValueError("İşlem yönü seçin (Alınan / Verilen).")

        basit = veriler.get("basit_tur") or veriler.get("evrak_turu_basit") or veriler.get("evrak_turu")
        if veriler.get("evrak_turu") in (
            EVRAK_TURU_MUSTERI_CEKI,
            EVRAK_TURU_MUSTERI_SENEDI,
            EVRAK_TURU_FIRMA_CEKI,
            EVRAK_TURU_FIRMA_SENEDI,
        ) and not veriler.get("basit_tur"):
            evrak_turu = veriler["evrak_turu"]
        else:
            # "Çek" / "Senet" etiketleri
            if isinstance(basit, str):
                b = basit.strip()
                if b.lower() in ("çek", "cek"):
                    basit = "CEK"
                elif b.lower() == "senet":
                    basit = "SENET"
            evrak_turu = _evrak_turu_coz(str(basit or ""), islem_yonu)

        evrak_no = (veriler.get("evrak_no") or veriler.get("cek_no") or veriler.get("senet_no") or "").strip()
        if not evrak_no:
            raise ValueError("Belge / çek-senet numarası zorunludur.")

        duzenleme = _tarih_oku(veriler.get("duzenleme_tarihi"), "Düzenleme tarihi")
        vade = _tarih_oku(veriler.get("vade_tarihi"), "Vade tarihi")
        if vade < duzenleme:
            raise ValueError("Vade tarihi düzenleme tarihinden önce olamaz.")

        tutar = _decimal(veriler.get("doviz_tutari") or veriler.get("tutar"), "Tutar", Decimal("0.01"))
        doviz = (veriler.get("doviz_turu") or veriler.get("para_birimi") or "TL").strip().upper() or "TL"
        kur = _decimal(veriler.get("kur") or 1, "Kur", Decimal("0.000001"))
        if doviz == "TL":
            kur = Decimal("1")
            tl = tutar
        else:
            tl = (tutar * kur).quantize(Decimal("0.01"))

        cari_id = veriler.get("cari_id")
        if cari_id in ("", None):
            cari_id = None
        else:
            try:
                cari_id = int(cari_id)
            except (TypeError, ValueError) as e:
                raise ValueError("Geçerli bir cari seçin.") from e
            if cari_id <= 0:
                cari_id = None
        if cari_id is None:
            raise ValueError("Cari seçimi zorunludur.")

        portfoy_no = (veriler.get("portfoy_no") or "").strip()
        cek_mi = evrak_turu in (EVRAK_TURU_MUSTERI_CEKI, EVRAK_TURU_FIRMA_CEKI)

        return {
            "evrak_turu": evrak_turu,
            "islem_yonu": islem_yonu,
            "evrak_no": evrak_no,
            "seri_no": (veriler.get("seri_no") or "").strip() or None,
            "portfoy_no": portfoy_no or None,
            "duzenleme_tarihi": duzenleme,
            "vade_tarihi": vade,
            "doviz_turu": doviz,
            "doviz_tutari": tutar,
            "kur": kur,
            "tl_tutari": tl,
            "cari_id": cari_id,
            "banka_adi": (veriler.get("banka_adi") or "").strip() or None,
            "banka_subesi": (veriler.get("banka_subesi") or "").strip() or None,
            "sube_kodu": (veriler.get("sube_kodu") or "").strip() or None,
            "hesap_no": (veriler.get("hesap_no") or "").strip() or None,
            "iban": (veriler.get("iban") or "").strip() or None,
            "cek_no": (veriler.get("cek_no") or (evrak_no if cek_mi else "")).strip() or None,
            "senet_no": (veriler.get("senet_no") or (evrak_no if not cek_mi else "")).strip() or None,
            "kesideci_adi": (veriler.get("kesideci_adi") or "").strip() or None,
            "kesideci_vergi_tc": (veriler.get("kesideci_vergi_tc") or "").strip() or None,
            "keside_yeri": (veriler.get("keside_yeri") or "").strip() or None,
            "hesap_sahibi": (veriler.get("hesap_sahibi") or "").strip() or None,
            "lehtar": (veriler.get("lehtar") or "").strip() or None,
            "teslim_eden": (veriler.get("teslim_eden") or "").strip() or None,
            "borclu_adi": (veriler.get("borclu_adi") or "").strip() or None,
            "borclu_vergi_tc": (veriler.get("borclu_vergi_tc") or "").strip() or None,
            "kefil": (veriler.get("kefil") or "").strip() or None,
            "duzenleme_yeri": (veriler.get("duzenleme_yeri") or "").strip() or None,
            "odeme_yeri": (veriler.get("odeme_yeri") or "").strip() or None,
            "aciklama": (veriler.get("aciklama") or "").strip() or None,
            "ozel_not": (veriler.get("ozel_not") or "").strip() or None,
            "created_by": (veriler.get("created_by") or veriler.get("kullanici") or "").strip() or None,
            "guncelleme": guncelleme,
        }

    @staticmethod
    def getir(evrak_id: int) -> dict[str, Any] | None:
        CekSenetService.schema_hazirla()
        with get_session() as session:
            from sqlalchemy.orm import selectinload

            evrak = session.scalars(
                select(CekSenetEvrak)
                .options(selectinload(CekSenetEvrak.cari))
                .where(CekSenetEvrak.id == int(evrak_id))
            ).first()
            if not evrak:
                return None
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def olustur(veriler: dict[str, Any]) -> dict[str, Any]:
        """Yeni evrak + ilk KAYIT hareketi."""
        CekSenetService.schema_hazirla()
        veri = CekSenetService._verileri_dogrula(veriler, guncelleme=False)

        with get_session() as session:
            from database.models.cari import Cari

            cari = session.get(Cari, veri["cari_id"])
            if cari is None:
                raise ValueError("Seçilen cari bulunamadı.")

            portfoy_no = veri["portfoy_no"] or CekSenetService.portfoy_no_uret(
                veri["evrak_turu"], veri["islem_yonu"], yil=veri["duzenleme_tarihi"].year, session=session
            )
            mevcut = session.scalars(
                select(CekSenetEvrak.id).where(CekSenetEvrak.portfoy_no == portfoy_no)
            ).first()
            if mevcut:
                raise ValueError(f"Portföy no zaten kayıtlı: {portfoy_no}")

            if veri["islem_yonu"] == ISLEM_YONU_ALINAN:
                durum = DURUM_PORTFOYDE
                yer = "Portföy"
            else:
                durum = DURUM_TEDARIKCIYE_VERILDI
                yer = "Tedarikçi / Verilen"

            bugun = date.today()
            evrak = CekSenetEvrak(
                cari_id=veri["cari_id"],
                evrak_turu=veri["evrak_turu"],
                islem_yonu=veri["islem_yonu"],
                evrak_no=veri["evrak_no"],
                seri_no=veri["seri_no"],
                portfoy_no=portfoy_no,
                duzenleme_tarihi=veri["duzenleme_tarihi"],
                vade_tarihi=veri["vade_tarihi"],
                doviz_turu=veri["doviz_turu"],
                doviz_tutari=veri["doviz_tutari"],
                kur=veri["kur"],
                tl_tutari=veri["tl_tutari"],
                tahsil_edilen_tutar=Decimal("0"),
                kalan_tutar=veri["tl_tutari"],
                durum=durum,
                bulundugu_yer=yer,
                aciklama=veri["aciklama"],
                ozel_not=veri["ozel_not"],
                banka_adi=veri["banka_adi"],
                banka_subesi=veri["banka_subesi"],
                sube_kodu=veri["sube_kodu"],
                hesap_no=veri["hesap_no"],
                iban=veri["iban"],
                cek_no=veri["cek_no"],
                kesideci_adi=veri["kesideci_adi"],
                kesideci_vergi_tc=veri["kesideci_vergi_tc"],
                keside_yeri=veri["keside_yeri"],
                hesap_sahibi=veri["hesap_sahibi"],
                lehtar=veri["lehtar"],
                teslim_eden=veri["teslim_eden"],
                senet_no=veri["senet_no"],
                borclu_adi=veri["borclu_adi"],
                borclu_vergi_tc=veri["borclu_vergi_tc"],
                kefil=veri["kefil"],
                duzenleme_yeri=veri["duzenleme_yeri"],
                odeme_yeri=veri["odeme_yeri"],
                aktif=True,
                created_by=veri["created_by"],
                created_at=datetime.now(),
                son_islem_tarihi=bugun,
            )
            session.add(evrak)
            session.flush()
            hareket = CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=None,
                yeni_durum=durum,
                islem_turu="KAYIT",
                tutar=veri["tl_tutari"],
                aciklama=veri["aciklama"] or "Evrak kaydı oluşturuldu",
                kullanici=veri["created_by"],
            )
            CekSenetService._kayit_cari_posta(session, evrak, hareket)
            session.flush()
            sonuc = CekSenetService._satir_dict(evrak)
            return sonuc

    @staticmethod
    def guncelle(evrak_id: int, veriler: dict[str, Any]) -> dict[str, Any]:
        CekSenetService.schema_hazirla()
        veri = CekSenetService._verileri_dogrula(veriler, guncelleme=True)

        with get_session() as session:
            from sqlalchemy.orm import selectinload
            from database.models.cari import Cari

            evrak = session.scalars(
                select(CekSenetEvrak)
                .options(selectinload(CekSenetEvrak.cari))
                .where(CekSenetEvrak.id == int(evrak_id))
            ).first()
            if not evrak:
                raise ValueError("Evrak bulunamadı.")
            if not evrak.aktif or evrak.durum not in DUZENLENEBILIR_DURUMLAR:
                raise ValueError(
                    f"Bu evrak düzenlenemez (durum: {_durum_etiket(evrak.durum)})."
                )

            CekSenetService._muhasebe_posta_engeli(session, evrak, islem="düzenleme")
            kayit_h = CekSenetService._kayit_hareketi(session, evrak.id)
            if kayit_h and kayit_h.cari_hareket_id:
                tutar_degisti = _d(veri["tl_tutari"]) != _d(evrak.tl_tutari)
                cari_degisti = int(veri["cari_id"]) != int(evrak.cari_id or 0)
                yon_degisti = veri["islem_yonu"] != evrak.islem_yonu
                if tutar_degisti or cari_degisti or yon_degisti:
                    raise ValueError(
                        "Muhasebe (cari) kaydı oluşmuş; tutar/cari/yön değiştirilemez. "
                        "İptal edip yeniden kaydedin."
                    )

            cari = session.get(Cari, veri["cari_id"])
            if cari is None:
                raise ValueError("Seçilen cari bulunamadı.")

            # Portföy no: mevcut korunur; istenirse değiştirilebilir (benzersiz)
            yeni_portfoy = veri["portfoy_no"] or evrak.portfoy_no
            if yeni_portfoy != evrak.portfoy_no:
                cakisan = session.scalars(
                    select(CekSenetEvrak.id).where(
                        CekSenetEvrak.portfoy_no == yeni_portfoy,
                        CekSenetEvrak.id != evrak.id,
                    )
                ).first()
                if cakisan:
                    raise ValueError(f"Portföy no zaten kayıtlı: {yeni_portfoy}")
                evrak.portfoy_no = yeni_portfoy

            onceki = evrak.durum
            # Tür/yön değişirse verilen/alınan durumunu hizala
            if veri["islem_yonu"] == ISLEM_YONU_ALINAN:
                yeni_durum = DURUM_PORTFOYDE
                yer = "Portföy"
            else:
                yeni_durum = DURUM_TEDARIKCIYE_VERILDI
                yer = "Tedarikçi / Verilen"

            tahsil = _d(evrak.tahsil_edilen_tutar)
            kalan = veri["tl_tutari"] - tahsil
            if kalan < 0:
                raise ValueError("Tutar, tahsil/ödenen tutardan küçük olamaz.")

            evrak.cari_id = veri["cari_id"]
            evrak.evrak_turu = veri["evrak_turu"]
            evrak.islem_yonu = veri["islem_yonu"]
            evrak.evrak_no = veri["evrak_no"]
            evrak.seri_no = veri["seri_no"]
            evrak.duzenleme_tarihi = veri["duzenleme_tarihi"]
            evrak.vade_tarihi = veri["vade_tarihi"]
            evrak.doviz_turu = veri["doviz_turu"]
            evrak.doviz_tutari = veri["doviz_tutari"]
            evrak.kur = veri["kur"]
            evrak.tl_tutari = veri["tl_tutari"]
            evrak.kalan_tutar = kalan
            evrak.durum = yeni_durum
            evrak.bulundugu_yer = yer
            evrak.aciklama = veri["aciklama"]
            evrak.ozel_not = veri["ozel_not"]
            evrak.banka_adi = veri["banka_adi"]
            evrak.banka_subesi = veri["banka_subesi"]
            evrak.sube_kodu = veri["sube_kodu"]
            evrak.hesap_no = veri["hesap_no"]
            evrak.iban = veri["iban"]
            evrak.cek_no = veri["cek_no"]
            evrak.kesideci_adi = veri["kesideci_adi"]
            evrak.kesideci_vergi_tc = veri["kesideci_vergi_tc"]
            evrak.keside_yeri = veri["keside_yeri"]
            evrak.hesap_sahibi = veri["hesap_sahibi"]
            evrak.lehtar = veri["lehtar"]
            evrak.teslim_eden = veri["teslim_eden"]
            evrak.senet_no = veri["senet_no"]
            evrak.borclu_adi = veri["borclu_adi"]
            evrak.borclu_vergi_tc = veri["borclu_vergi_tc"]
            evrak.kefil = veri["kefil"]
            evrak.duzenleme_yeri = veri["duzenleme_yeri"]
            evrak.odeme_yeri = veri["odeme_yeri"]
            evrak.updated_by = veri["created_by"]
            evrak.updated_at = datetime.now()
            evrak.son_islem_tarihi = date.today()
            evrak.version = int(evrak.version or 1) + 1

            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=yeni_durum,
                islem_turu="GUNCELLEME",
                tutar=veri["tl_tutari"],
                aciklama=veri["aciklama"] or "Evrak güncellendi",
                kullanici=veri["created_by"],
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def iptal(evrak_id: int, aciklama: str | None = None, kullanici: str | None = None) -> dict[str, Any]:
        """Soft iptal → durum IPTAL (aktif kalır; listelerde durum filtresiyle görünmez)."""
        CekSenetService.schema_hazirla()
        with get_session() as session:
            from sqlalchemy.orm import selectinload

            evrak = session.scalars(
                select(CekSenetEvrak)
                .options(selectinload(CekSenetEvrak.cari))
                .where(CekSenetEvrak.id == int(evrak_id))
            ).first()
            if not evrak:
                raise ValueError("Evrak bulunamadı.")
            if not evrak.aktif or evrak.durum not in IPTAL_EDILEBILIR_DURUMLAR:
                raise ValueError(
                    f"Bu evrak iptal edilemez (durum: {_durum_etiket(evrak.durum)})."
                )
            CekSenetService._muhasebe_posta_engeli(session, evrak, islem="iptal")
            CekSenetService._kayit_cari_tam_geri_al(session, evrak)
            onceki = evrak.durum
            evrak.durum = DURUM_IPTAL
            evrak.bulundugu_yer = "İptal"
            evrak.son_islem_tarihi = date.today()
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1
            not_metin = (aciklama or "").strip() or "Evrak iptal edildi"
            if evrak.aciklama:
                evrak.aciklama = f"{evrak.aciklama} | İPTAL: {not_metin}"
            else:
                evrak.aciklama = f"İPTAL: {not_metin}"
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=DURUM_IPTAL,
                islem_turu="IPTAL",
                tutar=evrak.kalan_tutar,
                aciklama=not_metin,
                kullanici=kullanici,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    # ——— Aşama 3: operasyonel akışlar ———

    @staticmethod
    def bankaya_ver(
        evrak_id: int,
        *,
        tur: str,
        banka_hesabi_id: int,
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Portföydeki alınan evrakı bankaya tahsile veya teminata ver."""
        CekSenetService.schema_hazirla()
        tur_norm = (tur or "").strip().upper()
        if tur_norm in ("TAHSILE", "TAHSIL", "BANKAYA_TAHSILE"):
            yeni_durum = DURUM_BANKAYA_TAHSILE
            islem = "BANKAYA_TAHSILE"
            yer = "Banka (tahsil)"
        elif tur_norm in ("TEMINATA", "TEMINAT", "BANKAYA_TEMINATA"):
            yeni_durum = DURUM_BANKAYA_TEMINATA
            islem = "BANKAYA_TEMINATA"
            yer = "Banka (teminat)"
        else:
            raise ValueError("Banka işlemi türü Tahsile veya Teminata olmalıdır.")

        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or (
            "Bankaya tahsile verildi" if yeni_durum == DURUM_BANKAYA_TAHSILE else "Bankaya teminata verildi"
        )

        with get_session() as session:
            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.islem_yonu != ISLEM_YONU_ALINAN:
                raise ValueError("Yalnızca alınan (müşteri) evrakları bankaya verilebilir.")
            if evrak.durum not in BANKAYA_VERILEBILIR:
                raise ValueError(
                    f"Bankaya verilemez (durum: {_durum_etiket(evrak.durum)}). "
                    "Portföydeki evrak seçin."
                )
            hesap = CekSenetService._finans_hesap_dogrula(session, banka_hesabi_id)
            onceki = evrak.durum
            evrak.durum = yeni_durum
            evrak.banka_hesabi_id = hesap.id
            evrak.bulundugu_yer = yer
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=yeni_durum,
                islem_turu=islem,
                tutar=evrak.kalan_tutar,
                aciklama=f"{not_metin} — {hesap.hesap_adi}",
                kullanici=kullanici,
                ilgili_banka_kasa_id=hesap.id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def ciro_et(
        evrak_id: int,
        *,
        hedef_cari_id: int,
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Portföydeki alınan evrakı cariye ciro et."""
        CekSenetService.schema_hazirla()
        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or "Ciro edildi"

        with get_session() as session:
            from database.models.cari import Cari

            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.islem_yonu != ISLEM_YONU_ALINAN:
                raise ValueError("Yalnızca alınan evraklar ciro edilebilir.")
            if evrak.durum not in CIRO_EDILEBILIR:
                raise ValueError(
                    f"Ciro edilemez (durum: {_durum_etiket(evrak.durum)}). "
                    "Portföydeki evrak seçin."
                )
            try:
                cid = int(hedef_cari_id)
            except (TypeError, ValueError) as e:
                raise ValueError("Hedef cari seçin.") from e
            hedef = session.get(Cari, cid)
            if hedef is None:
                raise ValueError("Hedef cari bulunamadı.")
            if cid == evrak.cari_id:
                raise ValueError("Ciro hedefi, evrakın mevcut carisi ile aynı olamaz.")

            onceki = evrak.durum
            evrak.durum = DURUM_CIRO_EDILDI
            evrak.bulundugu_yer = f"Ciro: {hedef.unvan or hedef.cari_kodu}"
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1

            ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)
            tutar = _d(evrak.kalan_tutar)
            cari_id = None
            belge = None
            if tutar > 0:
                cari_id, belge = CekSenetService._cari_odeme_yaz(
                    session,
                    cari_id=cid,
                    tarih=islem_tarihi,
                    tutar=tutar,
                    belge_onek=BELGE_CIRO,
                    hesap_adi=PORTFOY_HESAP_ADI,
                    aciklama=f"Çek/senet ciro {ozet} → {hedef.cari_kodu}",
                )

            acik = f"{not_metin} → {hedef.cari_kodu} {hedef.unvan}"
            if belge:
                acik = f"[{belge}] {acik}"
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=DURUM_CIRO_EDILDI,
                islem_turu="CIRO",
                tutar=tutar,
                aciklama=acik,
                kullanici=kullanici,
                ilgili_cari_id=cid,
                cari_hareket_id=cari_id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def tahsil_et(
        evrak_id: int,
        *,
        tutar=None,
        finans_hesap_id: int | None = None,
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Alınan evrakı (portföy veya bankadaki tahsil) tahsil et; kısmi desteklenir."""
        CekSenetService.schema_hazirla()
        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or "Tahsil edildi"

        with get_session() as session:
            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.islem_yonu != ISLEM_YONU_ALINAN:
                raise ValueError("Tahsil yalnızca alınan evraklar için geçerlidir. Verilen için «Öde» kullanın.")
            if evrak.durum not in TAHSIL_EDILEBILIR:
                raise ValueError(
                    f"Tahsil edilemez (durum: {_durum_etiket(evrak.durum)})."
                )
            kalan = _d(evrak.kalan_tutar)
            if kalan <= 0:
                raise ValueError("Evrakın kalan tutarı yok; tahsil yapılamaz.")

            if tutar in (None, ""):
                odeme = kalan
            else:
                odeme = _decimal(tutar, "Tahsil tutarı", Decimal("0.01"))
            if odeme > kalan:
                raise ValueError(f"Tahsil tutarı kalan tutardan ({kalan}) büyük olamaz.")

            hesap = CekSenetService._finans_hesap_dogrula(session, finans_hesap_id)
            onceki = evrak.durum
            yeni_tahsil = _d(evrak.tahsil_edilen_tutar) + odeme
            yeni_kalan = _d(evrak.tl_tutari) - yeni_tahsil
            if yeni_kalan < 0:
                yeni_kalan = Decimal("0")
            if yeni_kalan == 0:
                yeni_durum = DURUM_TAHSIL_EDILDI
                yer = "Tahsil edildi"
                islem = "TAHSIL"
            else:
                yeni_durum = DURUM_KISMI_TAHSIL
                yer = "Kısmi tahsil"
                islem = "KISMI_TAHSIL"

            evrak.tahsil_edilen_tutar = yeni_tahsil
            evrak.kalan_tutar = yeni_kalan
            evrak.durum = yeni_durum
            evrak.kasa_id = hesap.id if (hesap.hesap_turu or "").upper() == "KASA" else evrak.kasa_id
            if (hesap.hesap_turu or "").upper() != "KASA":
                evrak.banka_hesabi_id = hesap.id
            evrak.bulundugu_yer = yer
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1

            # Cari kayıtta düşüldü; tahsilde yalnızca kasa/banka girişi
            ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)
            fin_id, belge = CekSenetService._finans_hareket_yaz(
                session,
                hesap=hesap,
                tarih=islem_tarihi,
                tutar=odeme,
                belge_onek=BELGE_TAHSIL,
                hareket_turu="ÇEK/SENET TAHSİLAT",
                aciklama=f"{not_metin} | {ozet} | {hesap.hesap_adi}",
                cikis=False,
            )
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=yeni_durum,
                islem_turu=islem,
                tutar=odeme,
                aciklama=f"[{belge}] {not_metin} — {hesap.hesap_adi}",
                kullanici=kullanici,
                ilgili_banka_kasa_id=hesap.id,
                finans_hareket_id=fin_id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def ode(
        evrak_id: int,
        *,
        tutar=None,
        finans_hesap_id: int | None = None,
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Verilen (firma) çek/senedi öde; kısmi desteklenir."""
        CekSenetService.schema_hazirla()
        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or "Ödendi"

        with get_session() as session:
            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.islem_yonu != ISLEM_YONU_VERILEN:
                raise ValueError("Ödeme yalnızca verilen (firma) evraklar için geçerlidir.")
            if evrak.durum not in ODE_EDILEBILIR:
                raise ValueError(
                    f"Ödenemez (durum: {_durum_etiket(evrak.durum)})."
                )
            kalan = _d(evrak.kalan_tutar)
            if kalan <= 0:
                raise ValueError("Evrakın kalan tutarı yok; ödeme yapılamaz.")

            if tutar in (None, ""):
                odeme = kalan
            else:
                odeme = _decimal(tutar, "Ödeme tutarı", Decimal("0.01"))
            if odeme > kalan:
                raise ValueError(f"Ödeme tutarı kalan tutardan ({kalan}) büyük olamaz.")

            hesap = CekSenetService._finans_hesap_dogrula(session, finans_hesap_id)
            onceki = evrak.durum
            yeni_tahsil = _d(evrak.tahsil_edilen_tutar) + odeme
            yeni_kalan = _d(evrak.tl_tutari) - yeni_tahsil
            if yeni_kalan < 0:
                yeni_kalan = Decimal("0")
            if yeni_kalan == 0:
                yeni_durum = DURUM_ODENDI
                yer = "Ödendi"
                islem = "ODEME"
            else:
                yeni_durum = DURUM_KISMI_ODENDI
                yer = "Kısmi ödeme"
                islem = "KISMI_ODEME"

            evrak.tahsil_edilen_tutar = yeni_tahsil
            evrak.kalan_tutar = yeni_kalan
            evrak.durum = yeni_durum
            if (hesap.hesap_turu or "").upper() == "KASA":
                evrak.kasa_id = hesap.id
            else:
                evrak.banka_hesabi_id = hesap.id
            evrak.bulundugu_yer = yer
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1

            # Cari kayıtta düşüldü; ödemede yalnızca kasa/banka çıkışı
            ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)
            fin_id, belge = CekSenetService._finans_hareket_yaz(
                session,
                hesap=hesap,
                tarih=islem_tarihi,
                tutar=odeme,
                belge_onek=BELGE_ODEME,
                hareket_turu="ÇEK/SENET ÖDEME",
                aciklama=f"{not_metin} | {ozet} | {hesap.hesap_adi}",
                cikis=True,
            )
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=yeni_durum,
                islem_turu=islem,
                tutar=odeme,
                aciklama=f"[{belge}] {not_metin} — {hesap.hesap_adi}",
                kullanici=kullanici,
                ilgili_banka_kasa_id=hesap.id,
                finans_hareket_id=fin_id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def iade_et(
        evrak_id: int,
        *,
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Evrakı cariye / portföyden iade et."""
        CekSenetService.schema_hazirla()
        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or "İade edildi"

        with get_session() as session:
            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.durum not in IADE_EDILEBILIR:
                raise ValueError(
                    f"İade edilemez (durum: {_durum_etiket(evrak.durum)})."
                )
            onceki = evrak.durum
            kalan = _d(evrak.kalan_tutar)
            ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)

            # Ciro postu varsa hedef cariden geri al
            CekSenetService._ciro_cari_geri_al(session, evrak)

            cari_id = None
            belge = None
            if kalan > 0 and evrak.cari_id:
                cari_id, belge = CekSenetService._cari_tahsilat_kismi_geri(
                    session,
                    cari_id=int(evrak.cari_id),
                    tarih=islem_tarihi,
                    tutar=kalan,
                    belge_onek=BELGE_IADE,
                    hesap_adi=PORTFOY_HESAP_ADI,
                    aciklama=f"Çek/senet iade {ozet}",
                    islem_turu="Çek İade",
                )

            evrak.durum = DURUM_IADE
            evrak.bulundugu_yer = "İade"
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1
            acik = not_metin
            if belge:
                acik = f"[{belge}] {acik}"
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=DURUM_IADE,
                islem_turu="IADE",
                tutar=kalan,
                aciklama=acik,
                kullanici=kullanici,
                cari_hareket_id=cari_id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def karsiliksiz_protesto(
        evrak_id: int,
        *,
        tur: str = "KARSILIKSIZ",
        tarih=None,
        aciklama: str | None = None,
        kullanici: str | None = None,
    ) -> dict[str, Any]:
        """Karşılıksız veya protestolu işaretle."""
        CekSenetService.schema_hazirla()
        tur_norm = (tur or "").strip().upper()
        if tur_norm in ("KARSILIKSIZ", "KARŞILIKSIZ"):
            yeni_durum = DURUM_KARSILIKSIZ
            islem = "KARSILIKSIZ"
            yer = "Karşılıksız"
            varsayilan = "Karşılıksız çıktı"
        elif tur_norm in ("PROTESTO", "PROTESTOLU"):
            yeni_durum = DURUM_PROTESTO
            islem = "PROTESTO"
            yer = "Protestolu"
            varsayilan = "Protesto edildi"
        else:
            raise ValueError("Tür Karşılıksız veya Protestolu olmalıdır.")

        islem_tarihi = CekSenetService._islem_tarihi(tarih)
        not_metin = (aciklama or "").strip() or varsayilan

        with get_session() as session:
            evrak = CekSenetService._evrak_yukle(session, evrak_id)
            if evrak.islem_yonu != ISLEM_YONU_ALINAN:
                raise ValueError("Karşılıksız/protesto yalnızca alınan evraklar için geçerlidir.")
            if evrak.durum not in KARSILIKSIZ_EDILEBILIR:
                raise ValueError(
                    f"Bu işlem yapılamaz (durum: {_durum_etiket(evrak.durum)})."
                )
            onceki = evrak.durum
            kalan = _d(evrak.kalan_tutar)
            ozet = CekSenetService._belge_ozeti(evrak.portfoy_no, evrak.evrak_no)

            CekSenetService._ciro_cari_geri_al(session, evrak)

            cari_id = None
            belge = None
            if kalan > 0 and evrak.cari_id:
                cari_id, belge = CekSenetService._cari_tahsilat_kismi_geri(
                    session,
                    cari_id=int(evrak.cari_id),
                    tarih=islem_tarihi,
                    tutar=kalan,
                    belge_onek=BELGE_KARSILIKSIZ,
                    hesap_adi=PORTFOY_HESAP_ADI,
                    aciklama=f"Çek/senet {varsayilan.lower()} {ozet}",
                    islem_turu="Karşılıksız" if yeni_durum == DURUM_KARSILIKSIZ else "Protesto",
                )

            evrak.durum = yeni_durum
            evrak.bulundugu_yer = yer
            evrak.son_islem_tarihi = islem_tarihi
            evrak.updated_at = datetime.now()
            evrak.updated_by = kullanici
            evrak.version = int(evrak.version or 1) + 1
            acik = not_metin
            if belge:
                acik = f"[{belge}] {acik}"
            CekSenetService._hareket_ekle(
                session,
                evrak,
                onceki_durum=onceki,
                yeni_durum=yeni_durum,
                islem_turu=islem,
                tutar=kalan,
                aciklama=acik,
                kullanici=kullanici,
                cari_hareket_id=cari_id,
            )
            session.flush()
            return CekSenetService._satir_dict(evrak)

    @staticmethod
    def evrak_hareketleri(evrak_id: int) -> list[dict[str, Any]]:
        CekSenetService.schema_hazirla()
        with get_session() as session:
            kayitlar = session.scalars(
                select(CekSenetHareket)
                .where(CekSenetHareket.evrak_id == int(evrak_id))
                .order_by(CekSenetHareket.tarih.desc(), CekSenetHareket.id.desc())
            ).all()
            return [
                {
                    "id": h.id,
                    "tarih": h.tarih,
                    "islem_turu": h.islem_turu,
                    "onceki_durum": _durum_etiket(h.onceki_durum or ""),
                    "yeni_durum": _durum_etiket(h.yeni_durum),
                    "tutar": _d(h.tutar) if h.tutar is not None else None,
                    "aciklama": h.aciklama or "",
                    "kullanici": h.kullanici or "",
                    "ilgili_cari_id": h.ilgili_cari_id,
                    "ilgili_banka_kasa_id": h.ilgili_banka_kasa_id,
                    "cari_hareket_id": h.cari_hareket_id,
                    "finans_hareket_id": h.finans_hareket_id,
                }
                for h in kayitlar
            ]


    @staticmethod
    def listele(
        sekme: str | None = None,
        arama: str = "",
        sadece_aktif: bool = True,
    ) -> list[dict[str, Any]]:
        """Sekmeye göre filtreli liste. Tablo yoksa / hata olursa boş liste."""
        try:
            CekSenetService.schema_hazirla()
        except Exception:
            return []

        durum_filtre: set[str] | None = None
        yonu: str | None = None
        banka_mi = False

        if sekme == "portfoy":
            durum_filtre = {DURUM_PORTFOYDE}
            yonu = ISLEM_YONU_ALINAN
        elif sekme == "verilen":
            yonu = ISLEM_YONU_VERILEN
            durum_filtre = {
                DURUM_PORTFOYDE,
                DURUM_TEDARIKCIYE_VERILDI,
                DURUM_KISMI_ODENDI,
            }
        elif sekme == "tahsil":
            durum_filtre = {DURUM_TAHSIL_EDILDI, DURUM_KISMI_TAHSIL}
        elif sekme == "odenen":
            durum_filtre = {DURUM_ODENDI, DURUM_KISMI_ODENDI}
        elif sekme == "banka":
            durum_filtre = {DURUM_BANKAYA_TAHSILE, DURUM_BANKAYA_TEMINATA}
            banka_mi = True
        elif sekme == "ciro":
            durum_filtre = {DURUM_CIRO_EDILDI}
        elif sekme == "karsiliksiz":
            durum_filtre = {DURUM_KARSILIKSIZ, DURUM_PROTESTO}
        elif sekme == "iade":
            durum_filtre = {DURUM_IADE}
        # "tum" / None → filtre yok

        arama = (arama or "").strip().casefold()
        bugun = date.today()
        try:
            with get_session() as session:
                from sqlalchemy.orm import selectinload

                q = (
                    select(CekSenetEvrak)
                    .options(selectinload(CekSenetEvrak.cari))
                    .order_by(CekSenetEvrak.vade_tarihi.asc(), CekSenetEvrak.id.desc())
                )
                if sadece_aktif:
                    q = q.where(CekSenetEvrak.aktif.is_(True))
                if durum_filtre is not None:
                    q = q.where(CekSenetEvrak.durum.in_(durum_filtre))
                if yonu is not None:
                    q = q.where(CekSenetEvrak.islem_yonu == yonu)

                kayitlar = session.scalars(q).all()
                sonuc: list[dict[str, Any]] = []
                for e in kayitlar:
                    if banka_mi and not (
                        e.durum in (DURUM_BANKAYA_TAHSILE, DURUM_BANKAYA_TEMINATA)
                        or (e.bulundugu_yer or "").upper().startswith("BANKA")
                    ):
                        # durum filtresi zaten yeterli; banka_mi yalnızca netlik
                        pass
                    satir = CekSenetService._satir_dict(e, bugun)
                    if arama:
                        metin = " ".join(
                            str(satir.get(k) or "")
                            for k in (
                                "portfoy_no",
                                "evrak_no",
                                "cari_kodu",
                                "cari_adi",
                                "banka",
                                "kesideci_borclu",
                                "aciklama",
                                "durum_etiket",
                            )
                        ).casefold()
                        if arama not in metin:
                            continue
                    sonuc.append(satir)
                return sonuc
        except Exception:
            return []

    @staticmethod
    def hareketleri_listele(limit: int = 500) -> list[dict[str, Any]]:
        """Tüm hareketler sekmesi için."""
        try:
            CekSenetService.schema_hazirla()
        except Exception:
            return []
        try:
            with get_session() as session:
                from sqlalchemy.orm import selectinload

                kayitlar = session.scalars(
                    select(CekSenetHareket)
                    .options(selectinload(CekSenetHareket.evrak))
                    .order_by(CekSenetHareket.tarih.desc(), CekSenetHareket.id.desc())
                    .limit(limit)
                ).all()
                sonuc = []
                for h in kayitlar:
                    ev = h.evrak
                    sonuc.append(
                        {
                            "id": h.id,
                            "tarih": h.tarih,
                            "portfoy_no": ev.portfoy_no if ev else "",
                            "evrak_no": ev.evrak_no if ev else "",
                            "islem_turu": h.islem_turu,
                            "onceki_durum": _durum_etiket(h.onceki_durum or ""),
                            "yeni_durum": _durum_etiket(h.yeni_durum),
                            "tutar": _d(h.tutar) if h.tutar is not None else None,
                            "aciklama": h.aciklama or "",
                            "kullanici": h.kullanici or "",
                        }
                    )
                return sonuc
        except Exception:
            return []

    @staticmethod
    def _adet_tutar(session, *kosullar) -> dict[str, Any]:
        q = select(
            func.count(CekSenetEvrak.id),
            func.coalesce(func.sum(CekSenetEvrak.kalan_tutar), 0),
        ).where(CekSenetEvrak.aktif.is_(True), *kosullar)
        adet, tutar = session.execute(q).one()
        return {"adet": int(adet or 0), "tutar": _d(tutar)}

    @staticmethod
    def ozet() -> dict[str, dict[str, Any]]:
        """Üst özet kutuları — boş DB'de sıfırlar döner."""
        sifir = {"adet": 0, "tutar": Decimal("0")}
        anahtarlar = (
            "portfoy_musteri_cekleri",
            "portfoy_musteri_senetleri",
            "bankaya_tahsile",
            "bankaya_teminata",
            "ciro_edilenler",
            "tahsil_edilenler",
            "karsiliksiz_protestolu",
            "iade_edilenler",
            "firma_odenecek_cekler",
            "firma_odenecek_senetler",
            "bugun_vade",
            "vade_7_gun",
            "vade_30_gun",
            "vadesi_gecenler",
        )
        bos = {k: dict(sifir) for k in anahtarlar}
        try:
            CekSenetService.schema_hazirla()
        except Exception:
            return bos

        bugun = date.today()
        # Özet kutularında ciro/karşılıksız ayrı satırlarda; vade/firma için çekirdek açık durumlar
        ozet_acik = (
            DURUM_PORTFOYDE,
            DURUM_BANKAYA_TAHSILE,
            DURUM_BANKAYA_TEMINATA,
            DURUM_TEDARIKCIYE_VERILDI,
            DURUM_KISMI_TAHSIL,
            DURUM_KISMI_ODENDI,
            DURUM_VADESI_GECTI,
        )
        try:
            with get_session() as session:
                portfoy = CekSenetEvrak.durum == DURUM_PORTFOYDE
                alinan = CekSenetEvrak.islem_yonu == ISLEM_YONU_ALINAN
                verilen = CekSenetEvrak.islem_yonu == ISLEM_YONU_VERILEN

                return {
                    "portfoy_musteri_cekleri": CekSenetService._adet_tutar(
                        session,
                        portfoy,
                        alinan,
                        CekSenetEvrak.evrak_turu == EVRAK_TURU_MUSTERI_CEKI,
                    ),
                    "portfoy_musteri_senetleri": CekSenetService._adet_tutar(
                        session,
                        portfoy,
                        alinan,
                        CekSenetEvrak.evrak_turu == EVRAK_TURU_MUSTERI_SENEDI,
                    ),
                    "bankaya_tahsile": CekSenetService._adet_tutar(
                        session, CekSenetEvrak.durum == DURUM_BANKAYA_TAHSILE
                    ),
                    "bankaya_teminata": CekSenetService._adet_tutar(
                        session, CekSenetEvrak.durum == DURUM_BANKAYA_TEMINATA
                    ),
                    "ciro_edilenler": CekSenetService._adet_tutar(
                        session, CekSenetEvrak.durum == DURUM_CIRO_EDILDI
                    ),
                    "tahsil_edilenler": CekSenetService._adet_tutar(
                        session, CekSenetEvrak.durum == DURUM_TAHSIL_EDILDI
                    ),
                    "karsiliksiz_protestolu": CekSenetService._adet_tutar(
                        session,
                        CekSenetEvrak.durum.in_((DURUM_KARSILIKSIZ, DURUM_PROTESTO)),
                    ),
                    "iade_edilenler": CekSenetService._adet_tutar(
                        session, CekSenetEvrak.durum == DURUM_IADE
                    ),
                    "firma_odenecek_cekler": CekSenetService._adet_tutar(
                        session,
                        verilen,
                        CekSenetEvrak.evrak_turu == EVRAK_TURU_FIRMA_CEKI,
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                    "firma_odenecek_senetler": CekSenetService._adet_tutar(
                        session,
                        verilen,
                        CekSenetEvrak.evrak_turu == EVRAK_TURU_FIRMA_SENEDI,
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                    "bugun_vade": CekSenetService._adet_tutar(
                        session,
                        CekSenetEvrak.vade_tarihi == bugun,
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                    "vade_7_gun": CekSenetService._adet_tutar(
                        session,
                        CekSenetEvrak.vade_tarihi > bugun,
                        CekSenetEvrak.vade_tarihi <= bugun + timedelta(days=7),
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                    "vade_30_gun": CekSenetService._adet_tutar(
                        session,
                        CekSenetEvrak.vade_tarihi > bugun,
                        CekSenetEvrak.vade_tarihi <= bugun + timedelta(days=30),
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                    "vadesi_gecenler": CekSenetService._adet_tutar(
                        session,
                        CekSenetEvrak.vade_tarihi < bugun,
                        CekSenetEvrak.durum.in_(ozet_acik),
                    ),
                }
        except Exception:
            return bos

    # ——— Aşama 5: Rapor sorguları ———

    @staticmethod
    def _rapor_satirlari(
        *,
        islem_yonu: str | None = None,
        durumlar: set[str] | frozenset[str] | None = None,
        vade_bas: date | None = None,
        vade_bit: date | None = None,
        vade_once: date | None = None,
        sadece_portfoyde: bool = False,
    ) -> list[dict[str, Any]]:
        """Ortak filtreli evrak satırları (raporlar)."""
        try:
            CekSenetService.schema_hazirla()
        except Exception:
            return []
        bugun = date.today()
        try:
            with get_session() as session:
                from sqlalchemy.orm import selectinload

                q = (
                    select(CekSenetEvrak)
                    .options(selectinload(CekSenetEvrak.cari))
                    .where(CekSenetEvrak.aktif.is_(True))
                    .order_by(CekSenetEvrak.vade_tarihi.asc(), CekSenetEvrak.id.desc())
                )
                if islem_yonu:
                    q = q.where(CekSenetEvrak.islem_yonu == islem_yonu)
                if sadece_portfoyde:
                    q = q.where(CekSenetEvrak.durum == DURUM_PORTFOYDE)
                elif durumlar is not None:
                    q = q.where(CekSenetEvrak.durum.in_(tuple(durumlar)))
                if vade_bas is not None:
                    q = q.where(CekSenetEvrak.vade_tarihi >= vade_bas)
                if vade_bit is not None:
                    q = q.where(CekSenetEvrak.vade_tarihi <= vade_bit)
                if vade_once is not None:
                    q = q.where(CekSenetEvrak.vade_tarihi < vade_once)
                return [
                    CekSenetService._satir_dict(e, bugun)
                    for e in session.scalars(q).all()
                ]
        except Exception:
            return []

    @staticmethod
    def rapor_portfoy_dokumu(islem_yonu: str = ISLEM_YONU_ALINAN) -> list[dict[str, Any]]:
        """Portföydeki alınan veya verilen (firma) evrak dökümü."""
        if islem_yonu == ISLEM_YONU_VERILEN:
            # Verilen: portföyde + tedarikçiye verilmiş / kısmi ödenen açık evraklar
            return CekSenetService._rapor_satirlari(
                islem_yonu=ISLEM_YONU_VERILEN,
                durumlar={
                    DURUM_PORTFOYDE,
                    DURUM_TEDARIKCIYE_VERILDI,
                    DURUM_KISMI_ODENDI,
                    DURUM_VADESI_GECTI,
                },
            )
        return CekSenetService._rapor_satirlari(
            islem_yonu=ISLEM_YONU_ALINAN,
            sadece_portfoyde=True,
        )

    @staticmethod
    def rapor_vade_analiz(dilim: str = "bugun") -> list[dict[str, Any]]:
        """Vade dilimi: bugun | 7 | 30 | gecen — açık evraklar."""
        bugun = date.today()
        acik = frozenset(
            {
                DURUM_PORTFOYDE,
                DURUM_BANKAYA_TAHSILE,
                DURUM_BANKAYA_TEMINATA,
                DURUM_TEDARIKCIYE_VERILDI,
                DURUM_KISMI_TAHSIL,
                DURUM_KISMI_ODENDI,
                DURUM_VADESI_GECTI,
            }
        )
        dilim = (dilim or "bugun").strip().lower()
        if dilim in ("gecen", "vadesi_gecen", "gecmis"):
            return CekSenetService._rapor_satirlari(
                durumlar=acik, vade_once=bugun
            )
        if dilim in ("7", "7gun", "vade_7"):
            return CekSenetService._rapor_satirlari(
                durumlar=acik,
                vade_bas=bugun + timedelta(days=1),
                vade_bit=bugun + timedelta(days=7),
            )
        if dilim in ("30", "30gun", "vade_30"):
            return CekSenetService._rapor_satirlari(
                durumlar=acik,
                vade_bas=bugun + timedelta(days=1),
                vade_bit=bugun + timedelta(days=30),
            )
        # bugün
        return CekSenetService._rapor_satirlari(
            durumlar=acik, vade_bas=bugun, vade_bit=bugun
        )

    @staticmethod
    def rapor_durum_ozeti() -> list[dict[str, Any]]:
        """Durum bazında adet + kalan tutar özeti."""
        try:
            CekSenetService.schema_hazirla()
        except Exception:
            return []
        try:
            with get_session() as session:
                satirlar = session.execute(
                    select(
                        CekSenetEvrak.durum,
                        func.count(CekSenetEvrak.id),
                        func.coalesce(func.sum(CekSenetEvrak.kalan_tutar), 0),
                        func.coalesce(func.sum(CekSenetEvrak.tl_tutari), 0),
                    )
                    .where(CekSenetEvrak.aktif.is_(True))
                    .group_by(CekSenetEvrak.durum)
                    .order_by(CekSenetEvrak.durum)
                ).all()
                sonuc = []
                for durum, adet, kalan, tl in satirlar:
                    sonuc.append(
                        {
                            "durum": durum,
                            "durum_etiket": _durum_etiket(durum or ""),
                            "adet": int(adet or 0),
                            "kalan_tutar": _d(kalan),
                            "tl_tutari": _d(tl),
                        }
                    )
                return sonuc
        except Exception:
            return []

    @staticmethod
    def rapor_cari_risk() -> list[dict[str, Any]]:
        """Cari bazlı açık evrak riski (adet + kalan) ve detay satırları."""
        kayitlar = CekSenetService._rapor_satirlari(durumlar=ACIK_DURUMLAR)
        # kalan > 0 olanlar
        aciklar = [k for k in kayitlar if float(k.get("kalan_tutar") or 0) > 0]
        grup: dict[tuple, dict[str, Any]] = {}
        for k in aciklar:
            anahtar = (k.get("cari_id"), k.get("cari_kodu") or "", k.get("cari_adi") or "")
            g = grup.get(anahtar)
            if g is None:
                g = {
                    "cari_id": k.get("cari_id"),
                    "cari_kodu": k.get("cari_kodu") or "",
                    "cari_adi": k.get("cari_adi") or "(Cari yok)",
                    "adet": 0,
                    "kalan_tutar": Decimal("0"),
                    "tl_tutari": Decimal("0"),
                    "evraklar": [],
                }
                grup[anahtar] = g
            g["adet"] += 1
            g["kalan_tutar"] = _d(g["kalan_tutar"]) + _d(k.get("kalan_tutar"))
            g["tl_tutari"] = _d(g["tl_tutari"]) + _d(k.get("tl_tutari"))
            g["evraklar"].append(k)
        sonuc = sorted(
            grup.values(),
            key=lambda x: (-float(x["kalan_tutar"]), x["cari_adi"]),
        )
        return sonuc
