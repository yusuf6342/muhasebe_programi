"""Ürün bazlı fon payı yönetimi.

Dört tutar ayrı izlenir:

* **Satış payı** — onaylı satışta ürün fon oranıyla hesaplanan pay (``fon_hareketleri``).
* **Tahsil edilen pay** — faturaya bağlı geçerli tahsilat oranında hak kazanılan kısım (dinamik).
* **Ayrılmış para** — kullanıcının fon için gerçekten ayırdığını kaydettiği tutar (iç takip).
* **Kullanım** — fondan yapılan harcama kaydı (iç takip).

Fon payı ve iç para hareketleri banka transferi veya muhasebe fişi oluşturmaz; cari, stok ve tahsilat
hareketleri çoğaltılmaz. Düzeltmeler silme ile değil gerekçeli ters kayıtla yapılır.

Yöntem fon tanımındadır: **iç pay** (varsayılan; fatura tutarı değişmez) veya **faturaya ek bedel**
(ürün Net'i üzerinden ek bedel + KDV'si faturaya eklenir, ödenecek toplamı artırır). Yöntem, oran,
KDV oranı ve hesap belgeye bağlanır; ayar sonradan değişse de geçmiş belge değişmez.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import func, select, text, update

from database.access import AccessError, yazma_zorunlu, yetki_var, yetki_zorunlu
from database.database import get_session
from database.models.fon import (
    DURUM_AKTIF,
    DURUM_INCELEME,
    DURUM_IPTAL,
    KAYNAK_IADE,
    KAYNAK_SATIS,
    OLAY_IADE,
    OLAY_INCELEME,
    OLAY_SATIS,
    PARA_AYIR,
    PARA_AYIR_GERI,
    PARA_KULLANIM,
    PARA_KULLANIM_GERI,
    PARA_TRANSFER_CIKIS,
    PARA_TRANSFER_GIRIS,
    TRANSFER_AKTIF,
    TRANSFER_IPTAL,
    YONTEM_EK_BEDEL,
    YONTEM_IC_PAY,
    Fon,
    FonBelgeEkBedeli,
    FonBelgeOrani,
    FonHareketi,
    FonOranGecmisi,
    FonParaHareketi,
    FonTransferi,
    StokFonOrani,
)

KURUS = Decimal("0.01")
YUZ = Decimal("100")
SIFIR = Decimal("0")

VARSAYILAN_FONLAR = (
    ("YARDIM", "Yardım", "Yardım amaçlı ayrılan pay"),
    ("YEDEK", "Yedek Akçe", "Beklenmeyen giderler için yedek"),
    ("TASARRUF", "Tasarruf", "Birikim / tasarruf payı"),
)

DESTEKLENEN_YONTEMLER = ("KASA", "HAVALE", "KART")
YONTEM_ADLARI = {"KASA": "Nakit / Kasa", "HAVALE": "Havale / EFT", "KART": "POS (brüt)"}
DESTEKLENEN_TAHSILAT_ACIKLAMA = (
    "Tahsil edilen paya sayılan yöntemler: Nakit/Kasa, Havale/EFT ve POS (brüt tutar; komisyon ikinci "
    "tahsilat sayılmaz). Çek, senet, mahsup (virman, KK çekimi mahsubu, devir) ve faturaya bağlanmamış "
    "tahsilat/uygulanmamış avans bu sürümde paya sayılmaz."
)

TUTAR_ACIKLAMALARI = {
    "satis_payi": "Satış payı: onaylı satışlarda ürün fon oranıyla hesaplanan pay (iade düşülmüş net).",
    "tahsil_edilen": "Tahsil edilen pay: satış payının faturaya bağlı geçerli tahsilat oranında hak kazanılan kısmı.",
    "ayrilmis": "Ayrılmış para: fon için gerçekten ayrıldığı kaydedilen tutar (iç takip; banka transferi yapılmaz).",
    "kullanim": "Kullanım: fondan yapılan harcama kaydı.",
    "transfer": "Transfer: fonlar arası ayrılmış bakiye aktarımı (satış payı / tahsilat değişmez).",
}

YONTEM_ETIKETLERI = {YONTEM_IC_PAY: "İç pay", YONTEM_EK_BEDEL: "Faturaya ek bedel"}

PARA_TUR_ADLARI = {
    PARA_AYIR: "Para ayırma", PARA_AYIR_GERI: "Ayırmayı geri alma",
    PARA_KULLANIM: "Fon kullanımı", PARA_KULLANIM_GERI: "Kullanım düzeltmesi",
    PARA_TRANSFER_CIKIS: "Transfer çıkışı", PARA_TRANSFER_GIRIS: "Transfer girişi",
}

TABLOLAR = (
    "fonlar",
    "stok_fon_oranlari",
    "fon_oran_gecmisi",
    "fon_belge_oranlari",
    "fon_hareketleri",
    "fon_para_hareketleri",
    "fon_belge_ek_bedelleri",
    "fon_transferleri",
)

_HAZIR_MOTORLAR: set[int] = set()


# ---------------------------------------------------------------- yardımcılar
def _d(deger) -> Decimal:
    if deger is None or deger == "":
        return SIFIR
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger).strip())
    except (InvalidOperation, ValueError) as hata:
        raise ValueError("Geçersiz sayı.") from hata


def _kurus(deger) -> Decimal:
    return _d(deger).quantize(KURUS, rounding=ROUND_HALF_UP)


def tutar_oku(metin, alan: str = "Tutar") -> Decimal:
    """Türkçe ondalık giriş: ``1.234,56`` / ``1234,56`` / ``1234.56``."""
    if isinstance(metin, Decimal):
        return metin
    s = str(metin if metin is not None else "").strip().replace(" ", "").replace("%", "")
    if not s:
        raise ValueError(f"{alan} boş olamaz.")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as hata:
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from hata


def oran_oku(metin) -> Decimal:
    """Yüzde oranı; ``1,5`` = %1,5. Negatif ve 100 üstü reddedilir."""
    oran = tutar_oku(metin, "Fon oranı")
    if oran < 0:
        raise ValueError("Fon oranı negatif olamaz.")
    if oran > YUZ:
        raise ValueError("Fon oranı %100'den büyük olamaz.")
    return oran.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.ad_soyad or oturum.kullanici_adi
    except Exception:  # noqa: BLE001
        return None


def _firma_id() -> int:
    try:
        from database.session_manager import oturum

        return int(oturum.company_id or 0)
    except Exception:  # noqa: BLE001
        return 0


def dagit(degerler: list[Decimal], hedef: Decimal) -> list[Decimal]:
    """Kuruş artığını en büyük kalan yöntemiyle deterministik dağıtır; toplam = ``hedef``."""
    if not degerler:
        return []
    alt = [(_d(v) / KURUS).to_integral_value(rounding="ROUND_FLOOR") * KURUS for v in degerler]
    fark = int(((_kurus(hedef) - sum(alt, SIFIR)) / KURUS).to_integral_value())
    sira = sorted(
        range(len(degerler)), key=lambda i: (-(_d(degerler[i]) - alt[i]), i)
    )
    sonuc = list(alt)
    if fark > 0:
        for k in range(fark):
            sonuc[sira[k % len(sira)]] += KURUS
    elif fark < 0:
        for k in range(-fark):
            sonuc[sira[-1 - (k % len(sira))]] -= KURUS
    return sonuc


def _hizmet_mi(stok) -> bool:
    tur = (getattr(stok, "kart_turu", "") or "").casefold()
    return any(k in tur for k in ("hizmet", "navlun", "masraf"))


def _motor():
    import database.database as veritabani

    return getattr(veritabani.company_db, "_engine", None) or veritabani.engine


def tablolar_var(session=None) -> bool:
    motor = session.get_bind() if session is not None else _motor()
    anahtar = id(motor)
    if anahtar in _HAZIR_MOTORLAR:
        return True
    sorgu = text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fon%'")
    if session is not None:
        adlar = {r[0] for r in session.execute(sorgu)}
    else:
        with motor.connect() as baglanti:
            adlar = {r[0] for r in baglanti.execute(sorgu)}
    if all(t in adlar for t in TABLOLAR):
        _HAZIR_MOTORLAR.add(anahtar)
        return True
    return False


class FonService:
    # ------------------------------------------------------------ şema
    @staticmethod
    def schema_hazirla() -> None:
        """Fon tablolarını oluşturur; mevcut veride önce doğrulanmış yedek alınır."""
        if tablolar_var():
            return
        from database.gecis_guvenligi import guvenli_gecis, yedek_onayi
        from database.models import fon as fon_modelleri

        def calistir() -> None:
            motor = _motor()
            for model in (
                fon_modelleri.Fon,
                fon_modelleri.StokFonOrani,
                fon_modelleri.FonOranGecmisi,
                fon_modelleri.FonBelgeOrani,
                fon_modelleri.FonHareketi,
                fon_modelleri.FonParaHareketi,
                fon_modelleri.FonBelgeEkBedeli,
                fon_modelleri.FonTransferi,
            ):
                model.__table__.create(bind=motor, checkfirst=True)

        try:
            from database.muhasebelestirme_service import MuhasebelestirmeService

            db_yolu = MuhasebelestirmeService._db_yolu()
        except Exception:  # noqa: BLE001
            db_yolu = None
        if db_yolu is None or yedek_onayi(db_yolu) is not None:
            calistir()
        else:
            guvenli_gecis(
                db_yolu, calistir, gerekli=True, etiket="fon_gecis",
                baglantilari_kapat=lambda: _motor().dispose(),
            )
        _HAZIR_MOTORLAR.discard(id(_motor()))
        tablolar_var()

    # ------------------------------------------------------------ tanımlar
    @staticmethod
    def varsayilan_fonlari_hazirla() -> int:
        FonService.schema_hazirla()
        with get_session() as session:
            if session.scalar(select(func.count(Fon.id))):
                return 0
            for kod, ad, amac in VARSAYILAN_FONLAR:
                session.add(Fon(kod=kod, ad=ad, amac=amac, olusturan=_kullanici()))
            return len(VARSAYILAN_FONLAR)

    @staticmethod
    def _fon_dict(f: Fon) -> dict[str, Any]:
        return {
            "id": f.id, "kod": f.kod, "ad": f.ad, "amac": f.amac or "", "para_birimi": f.para_birimi,
            "aktif": bool(f.aktif), "aciklama": f.aciklama or "", "yontem": f.yontem,
            "yontem_adi": YONTEM_ETIKETLERI.get(f.yontem, f.yontem),
            "ek_bedel_kdv_orani": f.ek_bedel_kdv_orani,
            "kullanim_hesap_kodu": f.kullanim_hesap_kodu or "",
            "ayirma_hesap_kodu": f.ayirma_hesap_kodu or "",
            "ek_bedel_hesap_kodu": f.ek_bedel_hesap_kodu or "",
        }

    @staticmethod
    def fon_listesi(sadece_aktif: bool = False) -> list[dict[str, Any]]:
        if not tablolar_var():
            return []
        with get_session() as session:
            q = select(Fon).order_by(Fon.kod)
            if sadece_aktif:
                q = q.where(Fon.aktif.is_(True))
            return [FonService._fon_dict(f) for f in session.scalars(q)]

    @staticmethod
    def fon_kaydet(veri: dict[str, Any], fon_id: int | None = None) -> int:
        yazma_zorunlu("fon_tanim", "finans_duzenleme")
        FonService.schema_hazirla()
        kod = (veri.get("kod") or "").strip().upper()
        ad = (veri.get("ad") or "").strip()
        if not kod:
            raise ValueError("Fon kodu zorunludur.")
        if not ad:
            raise ValueError("Fon adı zorunludur.")
        yontem = (veri.get("yontem") or YONTEM_IC_PAY).strip().upper()
        if yontem not in (YONTEM_IC_PAY, YONTEM_EK_BEDEL):
            raise ValueError("Geçersiz fon yöntemi.")
        pb = (veri.get("para_birimi") or "TRY").strip().upper()
        if pb not in ("TRY", "TL"):
            raise ValueError("Fon takip para birimi TL olmalıdır.")
        ek_kdv = ek_hesap = None
        if yontem == YONTEM_EK_BEDEL:
            ham_kdv = veri.get("ek_bedel_kdv_orani")
            if ham_kdv in (None, ""):
                raise ValueError("Faturaya ek bedel yönteminde 'Ek bedel KDV oranı' zorunludur (0 olabilir).")
            ek_kdv = tutar_oku(ham_kdv, "Ek bedel KDV oranı")
            if ek_kdv < 0 or ek_kdv > YUZ:
                raise ValueError("Ek bedel KDV oranı 0 ile 100 arasında olmalıdır.")
            ek_hesap = (veri.get("ek_bedel_hesap_kodu") or "").strip() or None
            if not ek_hesap:
                raise ValueError("Faturaya ek bedel yönteminde 'Ek bedel muhasebe hesabı' zorunludur.")
            FonService._ek_bedel_hesap_dogrula(ek_hesap)
        with get_session() as session:
            ayni = session.scalar(select(Fon).where(func.upper(Fon.kod) == kod))
            if ayni is not None and ayni.id != fon_id:
                raise ValueError(f"{kod} kodlu fon zaten var.")
            if fon_id:
                fon = session.get(Fon, int(fon_id))
                if fon is None:
                    raise ValueError("Fon bulunamadı.")
                fon.guncelleme = datetime.now()
                fon.guncelleyen = _kullanici()
            else:
                fon = Fon(olusturan=_kullanici())
                session.add(fon)
            eski = (fon.kod, fon.ad, fon.aktif) if fon_id else None
            fon.kod = kod
            fon.ad = ad
            fon.amac = (veri.get("amac") or "").strip() or None
            fon.aciklama = (veri.get("aciklama") or "").strip() or None
            fon.para_birimi = "TRY"
            if fon_id and fon.yontem != yontem:
                eski = (*eski, f"yöntem {fon.yontem}→{yontem}")
            fon.yontem = yontem
            if yontem == YONTEM_EK_BEDEL:
                fon.ek_bedel_kdv_orani = ek_kdv
                fon.ek_bedel_hesap_kodu = ek_hesap
            if "aktif" in veri:
                fon.aktif = bool(veri.get("aktif"))
            session.flush()
            yeni_id = int(fon.id)
        FonService._audit(
            "fon_tanim_guncelle" if fon_id else "fon_tanim_ekle", yeni_id,
            eski=str(eski) if eski else None,
            yeni=f"{kod} / {ad} / {YONTEM_ETIKETLERI[yontem]}"
            + (f" (KDV %{ek_kdv}, hesap {ek_hesap})" if yontem == YONTEM_EK_BEDEL else ""),
        )
        return yeni_id

    @staticmethod
    def _ek_bedel_hesap_dogrula(kod: str, session=None) -> dict:
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        return MuhasebeEntegrasyonService._hesap_kodla(kod, "Ek bedel muhasebe hesabı", session=session)

    @staticmethod
    def fon_aktiflik(fon_id: int, aktif: bool) -> None:
        yazma_zorunlu("fon_tanim", "finans_duzenleme")
        with get_session() as session:
            fon = session.get(Fon, int(fon_id))
            if fon is None:
                raise ValueError("Fon bulunamadı.")
            fon.aktif = bool(aktif)
            fon.guncelleme = datetime.now()
            fon.guncelleyen = _kullanici()
        FonService._audit("fon_aktiflik", fon_id, yeni="aktif" if aktif else "pasif")

    @staticmethod
    def fon_sil(fon_id: int) -> None:
        yazma_zorunlu("fon_tanim", "finans_duzenleme")
        with get_session() as session:
            fon = session.get(Fon, int(fon_id))
            if fon is None:
                raise ValueError("Fon bulunamadı.")
            hareket = session.scalar(select(func.count(FonHareketi.id)).where(FonHareketi.fon_id == fon.id))
            para = session.scalar(
                select(func.count(FonParaHareketi.id)).where(FonParaHareketi.fon_id == fon.id)
            )
            if hareket or para:
                raise ValueError("Hareketi olan fon silinemez; pasifleştirebilirsiniz.")
            session.query(StokFonOrani).filter(StokFonOrani.fon_id == fon.id).delete()
            session.delete(fon)
        FonService._audit("fon_sil", fon_id)

    @staticmethod
    def hesap_listesi() -> list[tuple[str, str]]:
        """Mevcut hesap planından seçilebilir aktif hesaplar (kod, ad)."""
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as session:
            q = select(HesapPlani.hesap_kodu, HesapPlani.hesap_adi).where(HesapPlani.aktif.is_(True))
            fid = _firma_id()
            if fid:
                firma_var = session.scalar(
                    select(func.count(HesapPlani.id)).where(HesapPlani.firma_id == fid)
                )
                if firma_var:
                    q = q.where(HesapPlani.firma_id == fid)
            return [(k, a) for k, a in session.execute(q.order_by(HesapPlani.hesap_kodu))]

    @staticmethod
    def hesap_eslemesi_kaydet(fon_id: int, *, kullanim_hesap_kodu: str | None,
                              ayirma_hesap_kodu: str | None,
                              ek_bedel_hesap_kodu: str | None = None) -> None:
        yazma_zorunlu("fon_hesap_esleme", "finans_duzenleme")
        gecerli = {k for k, _ in FonService.hesap_listesi()}
        temiz: dict[str, str | None] = {}
        for alan, kod in (("kullanim_hesap_kodu", kullanim_hesap_kodu),
                          ("ayirma_hesap_kodu", ayirma_hesap_kodu)):
            kod = (kod or "").strip() or None
            if kod and kod not in gecerli:
                raise ValueError(f"{kod} hesap planında bulunamadı; mevcut bir hesap seçin.")
            temiz[alan] = kod
        ek_kod = (ek_bedel_hesap_kodu or "").strip() or None
        if ek_kod:
            FonService._ek_bedel_hesap_dogrula(ek_kod)
        with get_session() as session:
            fon = session.get(Fon, int(fon_id))
            if fon is None:
                raise ValueError("Fon bulunamadı.")
            ek_degisir = ek_bedel_hesap_kodu is not None
            if ek_degisir and ek_kod is None and fon.yontem == YONTEM_EK_BEDEL:
                raise ValueError("Faturaya ek bedel yöntemindeki fonun ek bedel hesabı boş bırakılamaz.")
            eski = f"{fon.kullanim_hesap_kodu}/{fon.ayirma_hesap_kodu}/{fon.ek_bedel_hesap_kodu}"
            fon.kullanim_hesap_kodu = temiz["kullanim_hesap_kodu"]
            fon.ayirma_hesap_kodu = temiz["ayirma_hesap_kodu"]
            if ek_degisir:
                fon.ek_bedel_hesap_kodu = ek_kod
            ek_kod = fon.ek_bedel_hesap_kodu
            fon.guncelleme = datetime.now()
            fon.guncelleyen = _kullanici()
        FonService._audit("fon_hesap_esleme", fon_id, eski=eski,
                          yeni=f"{temiz['kullanim_hesap_kodu']}/{temiz['ayirma_hesap_kodu']}/{ek_kod}")

    # ------------------------------------------------------------ oranlar
    @staticmethod
    def stok_fon_oranlari(stok_id: int) -> list[dict[str, Any]]:
        if not tablolar_var():
            return []
        with get_session() as session:
            oranlar = {o.fon_id: o for o in session.scalars(
                select(StokFonOrani).where(StokFonOrani.stok_id == int(stok_id))
            )}
            sonuc = []
            for fon in session.scalars(select(Fon).order_by(Fon.kod)):
                o = oranlar.get(fon.id)
                if o is None and not fon.aktif:
                    continue
                sonuc.append({
                    "fon_id": fon.id, "fon_kod": fon.kod, "fon_ad": fon.ad, "fon_aktif": bool(fon.aktif),
                    "oran": o.oran if o else None, "aktif": bool(o.aktif) if o else False,
                    "aciklama": (o.aciklama or "") if o else "",
                    "guncelleme": o.guncelleme if o else None,
                })
            return sonuc

    @staticmethod
    def _oran_yaz(session, stok_id: int, fon_id: int, oran: Decimal, aktif: bool,
                  aciklama: str | None, kaynak: str) -> bool:
        kayit = session.scalar(
            select(StokFonOrani).where(StokFonOrani.stok_id == stok_id, StokFonOrani.fon_id == fon_id)
        )
        eski_oran = kayit.oran if kayit else None
        eski_aktif = bool(kayit.aktif) if kayit else None
        if kayit is not None and _d(kayit.oran) == oran and bool(kayit.aktif) == aktif and (
            (kayit.aciklama or None) == (aciklama or None)
        ):
            return False
        if kayit is None:
            kayit = StokFonOrani(stok_id=stok_id, fon_id=fon_id)
            session.add(kayit)
        kayit.oran = oran
        kayit.aktif = aktif
        kayit.aciklama = aciklama or None
        kayit.guncelleme = datetime.now()
        kayit.guncelleyen = _kullanici()
        if eski_oran is None or _d(eski_oran) != oran or eski_aktif != aktif:
            session.add(FonOranGecmisi(
                stok_id=stok_id, fon_id=fon_id, eski_oran=eski_oran, yeni_oran=oran,
                eski_aktif=eski_aktif, yeni_aktif=aktif, kaynak=kaynak, aciklama=aciklama,
                kullanici=_kullanici(),
            ))
        return True

    @staticmethod
    def _aktif_toplam_kontrol(session, stok_id: int, yeni: dict[int, tuple[Decimal, bool]]) -> Decimal:
        mevcut = {o.fon_id: (_d(o.oran), bool(o.aktif)) for o in session.scalars(
            select(StokFonOrani).where(StokFonOrani.stok_id == stok_id)
        )}
        mevcut.update(yeni)
        aktif_fonlar = {f.id for f in session.scalars(select(Fon).where(Fon.aktif.is_(True)))}
        toplam = sum((o for fid, (o, a) in mevcut.items() if a and fid in aktif_fonlar), SIFIR)
        if toplam > YUZ:
            raise ValueError(f"Ürünün toplam aktif fon oranı %100'ü aşamaz (toplam %{toplam}).")
        return toplam

    @staticmethod
    def stok_fon_oranlarini_kaydet(stok_id: int, satirlar: Iterable[dict[str, Any]]) -> int:
        """Stok kartı Fonlar bölümü. Yeni oran yalnız bundan sonraki onaylara uygulanır."""
        yazma_zorunlu("fon_tanim", "stok_duzenleme")
        FonService.schema_hazirla()
        hazir: dict[int, tuple[Decimal, bool, str | None]] = {}
        for s in satirlar:
            fon_id = int(s["fon_id"])
            ham = s.get("oran")
            if ham in (None, "") and not s.get("aktif"):
                continue
            oran = oran_oku(ham if ham not in (None, "") else "0")
            hazir[fon_id] = (oran, bool(s.get("aktif", True)), (s.get("aciklama") or "").strip() or None)
        degisen = 0
        with get_session() as session:
            FonService._aktif_toplam_kontrol(
                session, int(stok_id), {k: (v[0], v[1]) for k, v in hazir.items()}
            )
            for fon_id, (oran, aktif, aciklama) in hazir.items():
                if FonService._oran_yaz(session, int(stok_id), fon_id, oran, aktif, aciklama, "KART"):
                    degisen += 1
        if degisen:
            FonService._audit("fon_oran_kart", stok_id, yeni=f"{degisen} oran değişti")
        return degisen

    @staticmethod
    def oran_gecmisi(stok_id: int) -> list[dict[str, Any]]:
        if not tablolar_var():
            return []
        with get_session() as session:
            fonlar = {f.id: f.kod for f in session.scalars(select(Fon))}
            q = (select(FonOranGecmisi).where(FonOranGecmisi.stok_id == int(stok_id))
                 .order_by(FonOranGecmisi.zaman.desc(), FonOranGecmisi.id.desc()))
            return [{
                "zaman": g.zaman, "fon": fonlar.get(g.fon_id, g.fon_id), "eski_oran": g.eski_oran,
                "yeni_oran": g.yeni_oran, "eski_aktif": g.eski_aktif, "yeni_aktif": g.yeni_aktif,
                "kaynak": g.kaynak, "kullanici": g.kullanici or "", "aciklama": g.aciklama or "",
            } for g in session.scalars(q)]

    @staticmethod
    def _grup_stoklari(session, grup_id: int):
        from database.models.stok import StokKarti

        gid = int(grup_id)
        return list(session.scalars(
            select(StokKarti).where(
                (StokKarti.ana_grup_id == gid) | (StokKarti.tali_grup_id == gid)
                | (StokKarti.alt_grup_id == gid),
                StokKarti.is_deleted.is_(False),
            ).order_by(StokKarti.stok_kodu)
        ))

    @staticmethod
    def toplu_oran_onizleme(grup_id: int, fon_id: int, oran, politika: str,
                            stok_idler: Iterable[int] | None = None) -> list[dict[str, Any]]:
        """politika: ``BOS`` (yalnız oranı boş olanlar) | ``SECILI`` (seçilen ürünleri değiştir)."""
        oran = oran_oku(oran)
        politika = (politika or "").upper()
        if politika not in ("BOS", "SECILI"):
            raise ValueError("Uygulama seçeneği belirtilmeli: yalnız boş olanlar veya seçilenleri değiştir.")
        secili = {int(i) for i in (stok_idler or [])}
        if politika == "SECILI" and not secili:
            raise ValueError("Değiştirilecek ürünleri seçin.")
        sonuc = []
        with get_session() as session:
            fon = session.get(Fon, int(fon_id))
            if fon is None:
                raise ValueError("Fon bulunamadı.")
            aktif_fonlar = {f.id for f in session.scalars(select(Fon).where(Fon.aktif.is_(True)))}
            for stok in FonService._grup_stoklari(session, grup_id):
                kayitlar = {o.fon_id: o for o in session.scalars(
                    select(StokFonOrani).where(StokFonOrani.stok_id == stok.id)
                )}
                mevcut = kayitlar.get(fon.id)
                satir = {"stok_id": stok.id, "stok_kodu": stok.stok_kodu, "stok_adi": stok.stok_adi,
                         "mevcut": mevcut.oran if mevcut and mevcut.aktif else None, "yeni": oran,
                         "islem": "ATLA", "neden": ""}
                if politika == "BOS":
                    if mevcut is not None and mevcut.aktif:
                        satir["neden"] = "Oran zaten tanımlı"
                        sonuc.append(satir)
                        continue
                elif stok.id not in secili:
                    satir["neden"] = "Seçilmedi"
                    sonuc.append(satir)
                    continue
                diger = sum((_d(o.oran) for fid, o in kayitlar.items()
                             if fid != fon.id and o.aktif and fid in aktif_fonlar), SIFIR)
                if diger + oran > YUZ:
                    satir["neden"] = f"Toplam aktif oran %100'ü aşar (%{diger + oran})"
                elif mevcut is not None and mevcut.aktif and _d(mevcut.oran) == oran:
                    satir["neden"] = "Değişiklik yok"
                else:
                    satir["islem"] = "DEGISTIR" if mevcut is not None and mevcut.aktif else "EKLE"
                sonuc.append(satir)
        return sonuc

    @staticmethod
    def toplu_oran_uygula(grup_id: int, fon_id: int, oran, politika: str,
                          stok_idler: Iterable[int] | None = None) -> dict[str, int]:
        yazma_zorunlu("fon_tanim", "stok_duzenleme")
        FonService.schema_hazirla()
        onizleme = FonService.toplu_oran_onizleme(grup_id, fon_id, oran, politika, stok_idler)
        oran_d = oran_oku(oran)
        sayac = {"EKLE": 0, "DEGISTIR": 0, "ATLA": 0}
        with get_session() as session:
            for s in onizleme:
                if s["islem"] == "ATLA":
                    sayac["ATLA"] += 1
                    continue
                FonService._aktif_toplam_kontrol(session, s["stok_id"], {int(fon_id): (oran_d, True)})
                FonService._oran_yaz(session, s["stok_id"], int(fon_id), oran_d, True,
                                     f"Toplu (grup {grup_id})", "TOPLU")
                sayac[s["islem"]] += 1
        FonService._audit("fon_oran_toplu", grup_id,
                          yeni=f"fon={fon_id} %{oran_d} {politika}: {sayac}")
        return sayac

    # ------------------------------------------------------------ pay hesaplama
    @staticmethod
    def _satir_tabanlari(session, fatura, belge_net: Decimal | None = None) -> list[dict[str, Any]]:
        """Satır başına KDV hariç, iskonto ve genel indirim sonrası net taban (TL)."""
        from database.models.stok import StokKarti
        from database.satis_faturasi_service import SatisFaturasiService

        satirlar = list(fatura.satirlar)
        if not satirlar:
            return []
        netler = []
        for s in satirlar:
            _, _, net = SatisFaturasiService._satir_net(
                _d(s.miktar), _d(s.birim_fiyat), s.iskonto_orani or 0,
                getattr(s, "iskonto_orani_2", 0) or 0, getattr(s, "iskonto_orani_3", 0) or 0,
            )
            netler.append(_d(net))
        satir_genel = _d(SatisFaturasiService.toplam(satirlar)["genel_toplam"])
        # Taban yalnız ürün Net'i: ek fon bedeli ve KDV'si fon tabanına tekrar girmez
        belge_net = (_d(SatisFaturasiService.urun_net_toplam(fatura)) if belge_net is None
                     else _kurus(belge_net))
        if satir_genel > 0 and belge_net != satir_genel:
            carpan = belge_net / satir_genel
            tabanlar = dagit([n * carpan for n in netler], _kurus(sum(netler, SIFIR) * carpan))
        else:
            tabanlar = [_kurus(n) for n in netler]
        kodlar = {(s.urun_kodu or "").strip() for s in satirlar}
        stoklar = {k.stok_kodu: k for k in session.scalars(
            select(StokKarti).where(StokKarti.stok_kodu.in_(kodlar))
        )}
        sonuc = []
        for sira, (s, taban) in enumerate(zip(satirlar, tabanlar), start=1):
            stok = stoklar.get((s.urun_kodu or "").strip())
            if stok is None or _hizmet_mi(stok):
                continue
            carpan = _d(getattr(s, "birim_carpani", None) or 1) or Decimal("1")
            sonuc.append({
                "sira": sira, "satir": s, "stok": stok, "taban": taban,
                "temel_miktar": (_d(s.miktar) * carpan).quantize(Decimal("0.000001")),
            })
        return sonuc

    @staticmethod
    def _gecerli_oranlar(session, stok_idler: set[int]) -> dict[int, dict[int, Decimal]]:
        if not stok_idler:
            return {}
        q = (select(StokFonOrani.stok_id, StokFonOrani.fon_id, StokFonOrani.oran)
             .join(Fon, Fon.id == StokFonOrani.fon_id)
             .where(StokFonOrani.stok_id.in_(stok_idler), StokFonOrani.aktif.is_(True),
                    Fon.aktif.is_(True), StokFonOrani.oran > 0))
        sonuc: dict[int, dict[int, Decimal]] = defaultdict(dict)
        for stok_id, fon_id, oran in session.execute(q):
            sonuc[stok_id][fon_id] = _d(oran)
        return sonuc

    @staticmethod
    def _belge_oranlari(session, belge_id: int | None, stok_idler: set[int]
                        ) -> dict[int, dict[int, dict[str, Any]]]:
        """Ürün × fon için geçerli (oran, yöntem): belgede anlık kayıt varsa o, yoksa güncel tanım.

        Belge bir kez kaydedildiğinde/kesinleştiğinde oran ve yöntem belgeye bağlanır; ayar sonradan
        değişse de geçmiş belge tutarı değişmez.
        """
        if not stok_idler:
            return {}
        anlik: dict[tuple[int, int], FonBelgeOrani] = {}
        if belge_id:
            anlik = {(b.stok_id, b.fon_id): b for b in session.scalars(
                select(FonBelgeOrani).where(FonBelgeOrani.kaynak_turu == KAYNAK_SATIS,
                                            FonBelgeOrani.belge_id == int(belge_id),
                                            FonBelgeOrani.stok_id.in_(stok_idler))
            )}
        gecerli = FonService._gecerli_oranlar(session, stok_idler)
        yontemler = {f.id: (f.yontem or YONTEM_IC_PAY) for f in session.scalars(select(Fon))}
        sonuc: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        for (stok_id, fon_id), b in anlik.items():
            sonuc[stok_id][fon_id] = {"oran": _d(b.oran), "yontem": b.yontem or YONTEM_IC_PAY,
                                      "zaman": b.zaman, "anlik": True}
        for stok_id in stok_idler:
            for fon_id, oran in gecerli.get(stok_id, {}).items():
                if fon_id in sonuc[stok_id]:
                    continue
                sonuc[stok_id][fon_id] = {"oran": oran, "yontem": yontemler.get(fon_id, YONTEM_IC_PAY),
                                          "zaman": None, "anlik": False}
        return sonuc

    @staticmethod
    def _ek_bedel_paylari(session, fatura, belge_id: int | None):
        tabanlar = FonService._satir_tabanlari(session, fatura)
        belge_oranlari = FonService._belge_oranlari(session, belge_id, {t["stok"].id for t in tabanlar})
        ek_oranlar: dict[int, dict[int, Decimal]] = defaultdict(dict)
        for stok_id, fonlar in belge_oranlari.items():
            for fon_id, o in fonlar.items():
                if o["yontem"] == YONTEM_EK_BEDEL and o["oran"] > 0:
                    ek_oranlar[stok_id][fon_id] = o["oran"]
        return FonService._pay_hesapla(tabanlar, ek_oranlar), belge_oranlari

    @staticmethod
    def ek_bedel_hesapla(session, fatura, belge_id: int | None = None) -> dict[str, Any]:
        """Faturaya ek fon bedeli: fon başına matrah, oran, tutar, KDV (TL).

        Matrah ürünlerin KDV hariç, iskonto ve uzlaşma sonrası Net'idir; birden fazla fon aynı ürün
        tabanından hesaplanır (zincirleme yok). KDV oranı ve hesap belgede daha önce saklandıysa o
        kullanılır; yoksa fon ayarından okunur, eksikse ayar adıyla hata verilir.
        """
        bos = {"fonlar": [], "tutar": SIFIR, "kdv": SIFIR, "paylar": [], "belge_oranlari": {}}
        if not tablolar_var(session) or not list(getattr(fatura, "satirlar", []) or []):
            return bos
        paylar, belge_oranlari = FonService._ek_bedel_paylari(session, fatura, belge_id)
        if not paylar:
            return {**bos, "belge_oranlari": belge_oranlari}
        kayitli: dict[int, FonBelgeEkBedeli] = {}
        if belge_id:
            kayitli = {k.fon_id: k for k in session.scalars(select(FonBelgeEkBedeli).where(
                FonBelgeEkBedeli.kaynak_turu == KAYNAK_SATIS, FonBelgeEkBedeli.belge_id == int(belge_id)))}
        fonlar = {f.id: f for f in session.scalars(select(Fon))}
        gruplar: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for p in paylar:
            gruplar[p["fon_id"]].append(p)
        sonuc = []
        for fon_id in sorted(gruplar):
            fon = fonlar[fon_id]
            liste = gruplar[fon_id]
            onceki = kayitli.get(fon_id)
            if onceki is not None:
                kdv_orani, hesap_kodu = _d(onceki.kdv_orani), onceki.hesap_kodu
            else:
                if fon.ek_bedel_kdv_orani is None:
                    raise ValueError(
                        f"{fon.kod} fonu 'Faturaya ek bedel' yönteminde fakat 'Ek bedel KDV oranı' ayarı "
                        "eksik. Fon Yönetimi > Fon Tanımları ekranından tamamlayın."
                    )
                if not (fon.ek_bedel_hesap_kodu or "").strip():
                    raise ValueError(
                        f"{fon.kod} fonu 'Faturaya ek bedel' yönteminde fakat 'Ek bedel muhasebe hesabı' "
                        "ayarı eksik. Fon Yönetimi > Fon Tanımları ekranından tamamlayın."
                    )
                try:
                    FonService._ek_bedel_hesap_dogrula(fon.ek_bedel_hesap_kodu, session=session)
                except ValueError as hata:
                    raise ValueError(f"{fon.kod} fonu: {hata}") from hata
                kdv_orani, hesap_kodu = _d(fon.ek_bedel_kdv_orani), fon.ek_bedel_hesap_kodu
            tutar = sum((p["tutar"] for p in liste), SIFIR)
            oranlar = {p["oran"] for p in liste}
            sonuc.append({
                "fon_id": fon_id, "fon_kod": fon.kod, "fon_ad": fon.ad,
                "matrah": sum((p["taban"] for p in liste), SIFIR),
                "oran": next(iter(oranlar)) if len(oranlar) == 1 else None,
                "tutar": tutar, "kdv_orani": kdv_orani, "kdv": _kurus(tutar * kdv_orani / YUZ),
                "hesap_kodu": hesap_kodu,
            })
        return {"fonlar": sonuc, "tutar": sum((f["tutar"] for f in sonuc), SIFIR),
                "kdv": sum((f["kdv"] for f in sonuc), SIFIR), "paylar": paylar,
                "belge_oranlari": belge_oranlari}

    @staticmethod
    def ek_bedel_uygula(session, fatura) -> dict[str, Any]:
        """Kayıt öncesi: ek bedeli hesaplar ve faturanın ek bedel alanlarına yazar (tahsilat kontrolünden önce)."""
        hesap = FonService.ek_bedel_hesapla(session, fatura, getattr(fatura, "id", None))
        if hesap["tutar"] > 0:
            FonService._kur_dogrula(fatura)
        fatura.fon_ek_bedel_tutari = hesap["tutar"]
        fatura.fon_ek_bedel_kdv = hesap["kdv"]
        return hesap

    @staticmethod
    def ek_bedel_kaydet(session, fatura, hesap: dict[str, Any]) -> None:
        """Kayıt sonrası (fatura kimliği belli): fon başına ek bedel detayı ve oran/yöntem anlık kaydı."""
        if not tablolar_var(session):
            return
        fid = int(fatura.id)
        session.query(FonBelgeEkBedeli).filter(
            FonBelgeEkBedeli.kaynak_turu == KAYNAK_SATIS, FonBelgeEkBedeli.belge_id == fid
        ).delete(synchronize_session=False)
        if not hesap["fonlar"]:
            return
        pb = (getattr(fatura, "para_birimi", "TRY") or "TRY").upper()
        kur = _d(getattr(fatura, "kur", 1) or 0)
        simdi = datetime.now()
        for f in hesap["fonlar"]:
            session.add(FonBelgeEkBedeli(
                kaynak_turu=KAYNAK_SATIS, belge_id=fid, fon_id=f["fon_id"], matrah=f["matrah"],
                oran=f["oran"], tutar=f["tutar"], kdv_orani=f["kdv_orani"], kdv=f["kdv"],
                hesap_kodu=f["hesap_kodu"], para_birimi=pb, kur=kur if kur > 0 else None,
                kaynak_fatura_id=fid, zaman=simdi,
            ))
        yazilan: set[tuple[int, int]] = set()
        for p in hesap["paylar"]:
            anahtar = (p["stok"].id, p["fon_id"])
            o = hesap["belge_oranlari"].get(anahtar[0], {}).get(anahtar[1])
            if o is None or o["anlik"] or anahtar in yazilan:
                continue
            yazilan.add(anahtar)
            session.add(FonBelgeOrani(kaynak_turu=KAYNAK_SATIS, belge_id=fid, stok_id=anahtar[0],
                                      fon_id=anahtar[1], oran=o["oran"], yontem=YONTEM_EK_BEDEL, zaman=simdi))

    @staticmethod
    def belge_ek_bedelleri(kaynak_turu: str, belge_id: int, session=None) -> list[dict[str, Any]]:
        """Baskı / ekran için belgede saklanan ek bedel satırları."""
        def oku(s):
            if not tablolar_var(s):
                return []
            q = (select(FonBelgeEkBedeli, Fon.kod, Fon.ad).join(Fon, Fon.id == FonBelgeEkBedeli.fon_id)
                 .where(FonBelgeEkBedeli.kaynak_turu == kaynak_turu,
                        FonBelgeEkBedeli.belge_id == int(belge_id))
                 .order_by(Fon.kod))
            return [{"fon_id": k.fon_id, "fon_kod": kod, "fon_ad": ad, "matrah": _d(k.matrah),
                     "oran": k.oran, "tutar": _d(k.tutar), "kdv_orani": _d(k.kdv_orani), "kdv": _d(k.kdv),
                     "hesap_kodu": k.hesap_kodu or "", "para_birimi": k.para_birimi, "kur": k.kur}
                    for k, kod, ad in s.execute(q)]

        if session is not None:
            return oku(session)
        with get_session() as s:
            return oku(s)

    @staticmethod
    def _kur_dogrula(fatura) -> None:
        pb = (getattr(fatura, "para_birimi", "TRY") or "TRY").upper()
        if pb in ("TRY", "TL"):
            return
        kur = _d(getattr(fatura, "kur", 0) or 0)
        if kur <= 0 or kur == 1:
            raise ValueError(
                f"{pb} belgenin kuru kayıtlı değil (kur: {kur}). Fon tutarı TL'ye çevrilemez; belgeye "
                "geçerli kur girip yeniden kaydedin. (Kur varsayılmaz, bugünün kuru kullanılmaz.)"
            )

    @staticmethod
    def _pay_hesapla(tabanlar: list[dict[str, Any]],
                     oranlar: dict[int, dict[int, Decimal]]) -> list[dict[str, Any]]:
        """Satır × fon payı; fon bazında kuruş artığı deterministik dağıtılır."""
        fon_satirlari: dict[int, list[tuple[dict, Decimal]]] = defaultdict(list)
        for t in tabanlar:
            if t["taban"] <= 0:
                continue
            for fon_id, oran in sorted(oranlar.get(t["stok"].id, {}).items()):
                if oran > 0:
                    fon_satirlari[fon_id].append((t, oran))
        sonuc = []
        for fon_id in sorted(fon_satirlari):
            liste = fon_satirlari[fon_id]
            tam = [t["taban"] * o / YUZ for t, o in liste]
            paylar = dagit(tam, _kurus(sum(tam, SIFIR)))
            for (t, oran), pay in zip(liste, paylar):
                sonuc.append({**t, "fon_id": fon_id, "oran": oran, "tutar": pay})
        return sonuc

    @staticmethod
    def belge_onizleme(satirlar: list[dict[str, Any]], net_toplam=None,
                       belge_id: int | None = None) -> list[dict[str, Any]]:
        """Taslak / Hızlı Satış ekranı için kalıcı kayıt oluşturmadan fon payı önizlemesi.

        ``net_toplam`` ürün Net'idir (ek fon bedeli hariç). Her fon için yöntem döner; ek bedel
        yöntemindeki fonda ``kdv`` ve ayar eksikse ``eksik_ayar`` metni de vardır.
        """
        if not satirlar or not tablolar_var():
            return []
        from types import SimpleNamespace

        sahte_satirlar = [SimpleNamespace(
            urun_kodu=s.get("urun_kodu"), miktar=_d(s.get("miktar")),
            birim_fiyat=_d(s.get("birim_fiyat")), iskonto_orani=s.get("iskonto_orani") or 0,
            iskonto_orani_2=s.get("iskonto_orani_2") or 0, iskonto_orani_3=s.get("iskonto_orani_3") or 0,
            kdv_orani=s.get("kdv_orani") or 0, birim_carpani=s.get("birim_carpani"),
        ) for s in satirlar if (s.get("urun_kodu") or "").strip()]
        if not sahte_satirlar:
            return []
        from database.satis_faturasi_service import SatisFaturasiService

        if net_toplam is None:
            net_toplam = SatisFaturasiService.toplam(sahte_satirlar)["genel_toplam"]
        sahte = SimpleNamespace(satirlar=sahte_satirlar)
        with get_session() as session:
            tabanlar = FonService._satir_tabanlari(session, sahte, _d(net_toplam))
            belge_oranlari = FonService._belge_oranlari(session, belge_id, {t["stok"].id for t in tabanlar})
            oranlar: dict[int, dict[int, Decimal]] = defaultdict(dict)
            yontem: dict[tuple[int, int], str] = {}
            for stok_id, fonlar_o in belge_oranlari.items():
                for fon_id, o in fonlar_o.items():
                    oranlar[stok_id][fon_id] = o["oran"]
                    yontem[(stok_id, fon_id)] = o["yontem"]
            paylar = FonService._pay_hesapla(tabanlar, oranlar)
            fonlar = {f.id: f for f in session.scalars(select(Fon))}
            kayitli = {}
            if belge_id:
                kayitli = {k.fon_id: k for k in session.scalars(select(FonBelgeEkBedeli).where(
                    FonBelgeEkBedeli.kaynak_turu == KAYNAK_SATIS, FonBelgeEkBedeli.belge_id == int(belge_id)))}
            toplam: dict[tuple[int, str], dict[str, Any]] = {}
            for p in paylar:
                f = fonlar[p["fon_id"]]
                y = yontem.get((p["stok"].id, f.id), YONTEM_IC_PAY)
                k = toplam.setdefault((f.id, y), {"fon_id": f.id, "fon_kod": f.kod, "fon_ad": f.ad,
                                                  "yontem": y, "taban": SIFIR, "tutar": SIFIR})
                k["taban"] += p["taban"]
                k["tutar"] += p["tutar"]
            for (fon_id, y), k in toplam.items():
                if y != YONTEM_EK_BEDEL:
                    continue
                f = fonlar[fon_id]
                onceki = kayitli.get(fon_id)
                kdv_orani = _d(onceki.kdv_orani) if onceki is not None else f.ek_bedel_kdv_orani
                eksik = []
                if kdv_orani is None:
                    eksik.append("Ek bedel KDV oranı")
                if onceki is None and not (f.ek_bedel_hesap_kodu or "").strip():
                    eksik.append("Ek bedel muhasebe hesabı")
                k["kdv_orani"] = _d(kdv_orani) if kdv_orani is not None else None
                k["kdv"] = _kurus(k["tutar"] * _d(kdv_orani) / YUZ) if kdv_orani is not None else SIFIR
                k["eksik_ayar"] = (f"{f.kod}: {', '.join(eksik)} eksik") if eksik else ""
            return [toplam[k] for k in sorted(toplam)]

    @staticmethod
    def ek_bedel_ozeti(onizleme: list[dict[str, Any]]) -> dict[str, Any]:
        """``belge_onizleme`` sonucundan ekran için ek bedel toplamı (iç pay fonları dahil edilmez)."""
        ek = [o for o in onizleme or [] if o.get("yontem") == YONTEM_EK_BEDEL]
        return {
            "tutar": sum((_d(o["tutar"]) for o in ek), SIFIR),
            "kdv": sum((_d(o.get("kdv")) for o in ek), SIFIR),
            "fonlar": ek,
            "eksik_ayar": "; ".join(o["eksik_ayar"] for o in ek if o.get("eksik_ayar")),
        }

    # ------------------------------------------------------------ kancalar (çağıranın session'ı)
    @staticmethod
    def satis_onaylandi(session, fatura) -> int:
        """Onaylı satış: satır × fon satış payı. Aynı belgenin aktif payı varsa tekrar yazılmaz."""
        if not tablolar_var(session):
            return 0
        fid = int(fatura.id)
        aktif_var = session.scalar(
            select(func.count(FonHareketi.id)).where(
                FonHareketi.kaynak_turu == KAYNAK_SATIS, FonHareketi.belge_id == fid,
                FonHareketi.durum == DURUM_AKTIF,
            )
        )
        if aktif_var:
            return 0
        # Kayıtlı ek bedel, bugünkü (belgeye bağlı) oranlarla yeniden hesaplanan bedelle aynı olmalı
        ek = FonService.ek_bedel_hesapla(session, fatura, fid)
        kayitli_ek = _kurus(getattr(fatura, "fon_ek_bedel_tutari", 0) or 0)
        kayitli_kdv = _kurus(getattr(fatura, "fon_ek_bedel_kdv", 0) or 0)
        if ek["tutar"] != kayitli_ek or ek["kdv"] != kayitli_kdv:
            raise ValueError(
                f"Faturadaki ek fon bedeli ({kayitli_ek:.2f} + KDV {kayitli_kdv:.2f} TL) güncel fon "
                f"ayarıyla uyuşmuyor ({ek['tutar']:.2f} + KDV {ek['kdv']:.2f} TL). Fon ayarı fatura "
                "kaydından sonra değişmiş; faturayı açıp yeniden kaydedin."
            )
        tabanlar = FonService._satir_tabanlari(session, fatura)
        stok_idler = {t["stok"].id for t in tabanlar}
        if not stok_idler:
            return 0
        belge_oranlari = FonService._belge_oranlari(session, fid, stok_idler)
        if not belge_oranlari:
            return 0
        simdi = datetime.now()
        oranlar: dict[int, dict[int, Decimal]] = defaultdict(dict)
        bilgiler: dict[tuple[int, int], dict[str, Any]] = {}
        for stok_id, fonlar_o in belge_oranlari.items():
            for fon_id, o in fonlar_o.items():
                oranlar[stok_id][fon_id] = o["oran"]
                bilgiler[(stok_id, fon_id)] = o
        paylar = FonService._pay_hesapla(tabanlar, oranlar)
        if not paylar:
            return 0
        FonService._kur_dogrula(fatura)
        for stok_id, fon_id in {(p["stok"].id, p["fon_id"]) for p in paylar}:
            o = bilgiler[(stok_id, fon_id)]
            if not o["anlik"]:
                # İlk kesinleşme: oran ve yöntem belgeye bağlanır
                o["zaman"] = simdi
                session.add(FonBelgeOrani(kaynak_turu=KAYNAK_SATIS, belge_id=fid, stok_id=stok_id,
                                          fon_id=fon_id, oran=o["oran"], yontem=o["yontem"], zaman=simdi))
        revizyon = int(session.scalar(
            select(func.coalesce(func.max(FonHareketi.revizyon), 0)).where(
                FonHareketi.kaynak_turu == KAYNAK_SATIS, FonHareketi.belge_id == fid)
        ) or 0) + 1
        pb = (getattr(fatura, "para_birimi", "TRY") or "TRY").upper()
        kur = _d(getattr(fatura, "kur", 1) or 0)
        kullanici = _kullanici()
        for p in paylar:
            satir = p["satir"]
            doviz = pb != "TRY" and kur > 0
            o = bilgiler[(p["stok"].id, p["fon_id"])]
            session.add(FonHareketi(
                firma_id=_firma_id(), sube_id=getattr(fatura, "sube_id", None),
                kaynak_turu=KAYNAK_SATIS, belge_id=fid, belge_no=fatura.fatura_no, revizyon=revizyon,
                satir_sira=p["sira"], satir_id=getattr(satir, "id", None), kaynak_fatura_id=fid,
                stok_id=p["stok"].id, urun_kodu=p["stok"].stok_kodu, urun_adi=satir.urun_adi,
                cari_id=fatura.cari_id, fon_id=p["fon_id"], olay=OLAY_SATIS, yontem=o["yontem"],
                oran=p["oran"], oran_zamani=o["zaman"],
                miktar=p["temel_miktar"], taban=p["taban"], tutar=p["tutar"], para_birimi=pb,
                kur=kur if pb != "TRY" and kur > 0 else (Decimal("1") if pb == "TRY" else None),
                doviz_taban=_kurus(p["taban"] / kur) if doviz else None,
                doviz_tutar=_kurus(p["tutar"] / kur) if doviz else None,
                tarih=fatura.fatura_tarihi, durum=DURUM_AKTIF, kullanici=kullanici,
            ))
        return len(paylar)

    @staticmethod
    def _iptal_et(session, kaynak_turu: str, belge_id: int, neden: str) -> int:
        sonuc = session.execute(
            update(FonHareketi)
            .where(FonHareketi.kaynak_turu == kaynak_turu, FonHareketi.belge_id == int(belge_id),
                   FonHareketi.durum.in_((DURUM_AKTIF, DURUM_INCELEME)))
            .values(durum=DURUM_IPTAL, iptal_zamani=datetime.now(), iptal_nedeni=(neden or "")[:300])
        )
        return int(sonuc.rowcount or 0)

    @staticmethod
    def satis_onayi_geri_alindi(session, fatura, neden: str) -> int:
        if not tablolar_var(session):
            return 0
        return FonService._iptal_et(session, KAYNAK_SATIS, int(fatura.id), neden)

    @staticmethod
    def iade_iptal_edildi(session, iade, neden: str) -> int:
        if not tablolar_var(session):
            return 0
        return FonService._iptal_et(session, KAYNAK_IADE, int(iade.id), neden)

    @staticmethod
    def iade_kaydedildi(session, iade) -> int:
        """Satış iadesi: kaynak satırın kayıtlı oran ve payı üzerinden orantılı ters pay.

        Toplam iade, kaynak satırın payını aşamaz. Kaynaksız iade keyfi eşleştirilmez; fon tanımlı
        ürünse ``INCELEME`` kaydı (tutar 0) oluşur.
        """
        if not tablolar_var(session):
            return 0
        from database.models.satis_faturasi import SatisFaturasiSatiri
        from database.models.stok import StokKarti

        iid = int(iade.id)
        FonService._iptal_et(session, KAYNAK_IADE, iid, "İade yeniden kaydedildi")
        session.query(FonBelgeEkBedeli).filter(
            FonBelgeEkBedeli.kaynak_turu == KAYNAK_IADE, FonBelgeEkBedeli.belge_id == iid
        ).delete(synchronize_session=False)
        if hasattr(iade, "fon_ek_bedel_tutari"):
            iade.fon_ek_bedel_tutari = SIFIR
            iade.fon_ek_bedel_kdv = SIFIR
        if (iade.durum or "") == "İPTAL":
            return 0
        ek_iade: dict[tuple[int, int], Decimal] = defaultdict(lambda: SIFIR)
        ek_taban: dict[tuple[int, int], Decimal] = defaultdict(lambda: SIFIR)
        revizyon = int(session.scalar(
            select(func.coalesce(func.max(FonHareketi.revizyon), 0)).where(
                FonHareketi.kaynak_turu == KAYNAK_IADE, FonHareketi.belge_id == iid)
        ) or 0) + 1
        yazilan = 0
        kullanici = _kullanici()
        for sira, s in enumerate(list(iade.satirlar), start=1):
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == (s.urun_kodu or "").strip()))
            if stok is None or _hizmet_mi(stok):
                continue
            carpan = _d(getattr(s, "birim_carpani", None) or 1) or Decimal("1")
            iade_miktar = (_d(s.miktar) * carpan).quantize(Decimal("0.000001"))
            ortak = dict(
                firma_id=_firma_id(), sube_id=getattr(iade, "sube_id", None), kaynak_turu=KAYNAK_IADE,
                belge_id=iid, belge_no=iade.iade_no, revizyon=revizyon, satir_sira=sira,
                satir_id=getattr(s, "id", None), stok_id=stok.id, urun_kodu=stok.stok_kodu,
                urun_adi=s.urun_adi, cari_id=iade.cari_id, tarih=iade.iade_tarihi, kullanici=kullanici,
                miktar=-iade_miktar,
            )
            kaynak_satir_id = getattr(s, "kaynak_fatura_satiri_id", None)
            kaynak_satir = session.get(SatisFaturasiSatiri, int(kaynak_satir_id)) if kaynak_satir_id else None
            if kaynak_satir is None:
                fonlar = FonService._gecerli_oranlar(session, {stok.id}).get(stok.id, {})
                for fon_id, oran in sorted(fonlar.items()):
                    session.add(FonHareketi(
                        **ortak, fon_id=fon_id, olay=OLAY_INCELEME, oran=oran, taban=SIFIR, tutar=SIFIR,
                        durum=DURUM_INCELEME, para_birimi="TRY",
                        aciklama="Kaynaksız iade: fon payı otomatik eşleştirilmedi, inceleme gerekli",
                    ))
                    yazilan += 1
                continue
            fatura_id = int(kaynak_satir.fatura_id)
            asil = list(session.scalars(select(FonHareketi).where(
                FonHareketi.kaynak_turu == KAYNAK_SATIS, FonHareketi.belge_id == fatura_id,
                FonHareketi.durum == DURUM_AKTIF, FonHareketi.satir_id == int(kaynak_satir.id),
            )))
            satir_bazli = bool(asil)
            if not asil:
                asil = list(session.scalars(select(FonHareketi).where(
                    FonHareketi.kaynak_turu == KAYNAK_SATIS, FonHareketi.belge_id == fatura_id,
                    FonHareketi.durum == DURUM_AKTIF, FonHareketi.stok_id == stok.id,
                )))
            fon_gruplari: dict[int, list[FonHareketi]] = defaultdict(list)
            for h in asil:
                fon_gruplari[h.fon_id].append(h)
            for fon_id, hareketler in sorted(fon_gruplari.items()):
                asil_tutar = sum((_d(h.tutar) for h in hareketler), SIFIR)
                asil_taban = sum((_d(h.taban) for h in hareketler), SIFIR)
                asil_miktar = sum((_d(h.miktar) for h in hareketler), SIFIR)
                if asil_tutar <= 0 or asil_miktar <= 0:
                    continue
                q = select(func.coalesce(func.sum(FonHareketi.tutar), 0)).where(
                    FonHareketi.kaynak_turu == KAYNAK_IADE, FonHareketi.olay == OLAY_IADE,
                    FonHareketi.durum == DURUM_AKTIF, FonHareketi.kaynak_fatura_id == fatura_id,
                    FonHareketi.fon_id == fon_id, FonHareketi.stok_id == stok.id,
                )
                if satir_bazli:
                    q = q.where(FonHareketi.kaynak_satir_id == int(kaynak_satir.id))
                onceki_iade = -_d(session.scalar(q) or 0)
                kalan = asil_tutar - onceki_iade
                if kalan <= 0:
                    continue
                oranli = min(Decimal("1"), iade_miktar / asil_miktar)
                pay = min(kalan, _kurus(asil_tutar * oranli))
                taban = _kurus(asil_taban * oranli)
                ilk = hareketler[0]
                doviz = bool(ilk.kur) and ilk.para_birimi != "TRY"
                session.add(FonHareketi(
                    **ortak, kaynak_satir_id=int(kaynak_satir.id), kaynak_fatura_id=fatura_id,
                    fon_id=fon_id, olay=OLAY_IADE, yontem=ilk.yontem, oran=ilk.oran,
                    oran_zamani=ilk.oran_zamani, taban=-taban, tutar=-pay, para_birimi=ilk.para_birimi,
                    kur=ilk.kur,
                    doviz_taban=(-_kurus(taban / _d(ilk.kur))) if doviz else None,
                    doviz_tutar=(-_kurus(pay / _d(ilk.kur))) if doviz else None,
                    durum=DURUM_AKTIF, aciklama=f"İade · kaynak {ilk.belge_no}",
                ))
                yazilan += 1
                if ilk.yontem == YONTEM_EK_BEDEL:
                    ek_iade[(fatura_id, fon_id)] += pay
                    ek_taban[(fatura_id, fon_id)] += taban
        if ek_iade:
            FonService._iade_ek_bedeli_yaz(session, iade, ek_iade, ek_taban)
        return yazilan

    @staticmethod
    def _iade_ek_bedeli_yaz(session, iade, ek_iade: dict[tuple[int, int], Decimal],
                            ek_taban: dict[tuple[int, int], Decimal]) -> None:
        """İade edilen ek bedel payının KDV'si kaynak faturada saklanan KDV oranıyla; toplam iade KDV'si
        kaynaktaki ek bedel KDV'sini aşamaz."""
        from database.models.satis_iade_faturasi import SatisIadeFaturasi

        iid = int(iade.id)
        fon_toplam: dict[int, dict[str, Any]] = {}
        for (fatura_id, fon_id), tutar in sorted(ek_iade.items()):
            kaynak = session.scalar(select(FonBelgeEkBedeli).where(
                FonBelgeEkBedeli.kaynak_turu == KAYNAK_SATIS, FonBelgeEkBedeli.belge_id == fatura_id,
                FonBelgeEkBedeli.fon_id == fon_id))
            if kaynak is None:
                continue
            onceki_kdv = _d(session.scalar(
                select(func.coalesce(func.sum(FonBelgeEkBedeli.kdv), 0))
                .join(SatisIadeFaturasi, SatisIadeFaturasi.id == FonBelgeEkBedeli.belge_id)
                .where(FonBelgeEkBedeli.kaynak_turu == KAYNAK_IADE,
                       FonBelgeEkBedeli.kaynak_fatura_id == fatura_id, FonBelgeEkBedeli.fon_id == fon_id,
                       FonBelgeEkBedeli.belge_id != iid, SatisIadeFaturasi.durum != "İPTAL")
            ) or 0)
            kdv = min(_kurus(tutar * _d(kaynak.kdv_orani) / YUZ), max(SIFIR, _d(kaynak.kdv) - onceki_kdv))
            k = fon_toplam.setdefault(fon_id, {"tutar": SIFIR, "kdv": SIFIR, "matrah": SIFIR,
                                               "kaynak": kaynak, "fatura_id": fatura_id})
            k["tutar"] += tutar
            k["kdv"] += kdv
            k["matrah"] += ek_taban[(fatura_id, fon_id)]
        for fon_id, k in fon_toplam.items():
            kaynak = k["kaynak"]
            session.add(FonBelgeEkBedeli(
                kaynak_turu=KAYNAK_IADE, belge_id=iid, fon_id=fon_id, matrah=k["matrah"], oran=kaynak.oran,
                tutar=k["tutar"], kdv_orani=kaynak.kdv_orani, kdv=k["kdv"], hesap_kodu=kaynak.hesap_kodu,
                para_birimi=kaynak.para_birimi, kur=kaynak.kur, kaynak_fatura_id=k["fatura_id"],
            ))
        if hasattr(iade, "fon_ek_bedel_tutari"):
            iade.fon_ek_bedel_tutari = sum((k["tutar"] for k in fon_toplam.values()), SIFIR)
            iade.fon_ek_bedel_kdv = sum((k["kdv"] for k in fon_toplam.values()), SIFIR)

    # ------------------------------------------------------------ tahsil edilen pay
    @staticmethod
    def _kaynak_belge_tahsilati(session, belge_no: str, tutar: Decimal, bitis: date | None):
        """Kaynak belge no → (desteklenen, desteklenmeyen, yöntem açıklaması)."""
        from database.finans_service import _makbuz_sekil_turu
        from database.models.finans import FinansHareketi, FinansHesabi, KasaMakbuzu

        mkb = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == belge_no))
        if mkb is not None:
            if (mkb.durum or "").upper() == "IPTAL":
                return SIFIR, SIFIR, "İptal makbuz"
            toplam = _d(mkb.tutar)
            destek = sum((_d(s.tutar) for s in mkb.satirlar
                          if _makbuz_sekil_turu(s.odeme_sekli) in DESTEKLENEN_YONTEMLER), SIFIR)
            if toplam <= 0:
                return SIFIR, tutar, "Makbuz"
            pay = _kurus(tutar * min(Decimal("1"), destek / toplam))
            return pay, tutar - pay, "Makbuz"
        hareketler = list(session.execute(
            select(FinansHareketi.tutar, FinansHareketi.aciklama, FinansHesabi.hesap_turu)
            .join(FinansHesabi, FinansHesabi.id == FinansHareketi.hesap_id)
            .where(FinansHareketi.belge_no == belge_no, FinansHareketi.tutar > 0)
        ))
        for _tutar, aciklama, hesap_turu in hareketler:
            tur = _makbuz_sekil_turu(aciklama)
            if tur is None:
                ht = (hesap_turu or "").upper()
                tur = "KASA" if "KASA" in ht else ("HAVALE" if "BANKA" in ht else None)
            if tur in DESTEKLENEN_YONTEMLER:
                return tutar, SIFIR, YONTEM_ADLARI[tur]
        return SIFIR, tutar, "Çek/senet veya mahsup (desteklenmiyor)"

    @staticmethod
    def fatura_tahsil_orani(session, fatura, bitis: date | None = None) -> dict[str, Any]:
        from database.finans_service import _makbuz_sekil_turu
        from database.models.cari import CariKapatma, SatisHareketi
        from database.models.finans import KasaMakbuzu, SatisFaturaMakbuzBagi
        from database.satis_faturasi_service import SatisFaturasiService

        toplam = _d(SatisFaturasiService.net_toplam(fatura))
        destek = SIFIR
        desteksiz = SIFIR
        doviz_sabit = (getattr(fatura, "borc_esasi", "") == "DOVIZ_SABIT"
                       and (getattr(fatura, "para_birimi", "TRY") or "TRY") != "TRY")
        fatura_kur = _d(getattr(fatura, "kur", 1) or 0)
        if fatura.onaylandi:
            for th in fatura.tahsilatlar:
                if bitis and th.tahsilat_tarihi and th.tahsilat_tarihi > bitis:
                    continue
                tutar = _d(th.tutar)
                if doviz_sabit and _d(getattr(th, "odeme_kuru", 0)) > 0 and fatura_kur > 0:
                    # Döviz sabit faturada oran fatura para birimiyle: ödeme kuru ile çevrilir
                    tutar = tutar / _d(th.odeme_kuru) * fatura_kur
                if _makbuz_sekil_turu(th.odeme_sekli) in DESTEKLENEN_YONTEMLER:
                    destek += tutar
                else:
                    desteksiz += tutar
        pb = (getattr(fatura, "para_birimi", "TRY") or "TRY").upper()
        gorulen: set[str] = set()

        def makbuz_baglari() -> None:
            nonlocal destek, desteksiz
            for bag, mkb in session.execute(
                select(SatisFaturaMakbuzBagi, KasaMakbuzu)
                .join(KasaMakbuzu, KasaMakbuzu.id == SatisFaturaMakbuzBagi.makbuz_id)
                .where(SatisFaturaMakbuzBagi.fatura_id == int(fatura.id))
            ):
                if mkb.belge_no in gorulen:
                    continue
                gorulen.add(mkb.belge_no)
                if (mkb.durum or "").upper() == "IPTAL" or (bitis and mkb.tarih > bitis):
                    continue
                d, nd, _ = FonService._kaynak_belge_tahsilati(
                    session, mkb.belge_no, _d(bag.fatura_kapanan), bitis)
                destek += d
                desteksiz += nd

        def kapatmalar() -> None:
            nonlocal destek, desteksiz
            hareket_id = session.scalar(
                select(SatisHareketi.id).where(SatisHareketi.belge_no == fatura.fatura_no))
            if hareket_id is None:
                return
            q = select(CariKapatma).where(
                CariKapatma.hedef_hareket_id == int(hareket_id), CariKapatma.iptal.is_(False),
                CariKapatma.kaynak_tur.in_(("TAHSILAT", "AVANS")),
            )
            islenen: set[str] = set()
            for k in session.scalars(q):
                if k.kaynak_belge_no in gorulen or (bitis and k.tarih > bitis):
                    continue
                islenen.add(k.kaynak_belge_no)
                tutar = _d(k.tutar)
                if doviz_sabit and fatura_kur > 0 and (k.para_birimi or "TRY").upper() == pb:
                    # Döviz sabit borçta kapanan döviz payı faturanın kayıtlı kuruyla TL'ye çevrilir;
                    # farklı kurdan yapılan ödeme hakkı artırmaz (kur farkı ayrı izlenir)
                    tutar = tutar * fatura_kur
                d, nd, _ = FonService._kaynak_belge_tahsilati(session, k.kaynak_belge_no, tutar, bitis)
                destek += d
                desteksiz += nd
            gorulen.update(islenen)

        if doviz_sabit:
            # Kapanış eşleşmesi borç para biriminde tutulur; makbuz bağındaki TL tutarına göre önceliklidir
            kapatmalar()
            makbuz_baglari()
        else:
            makbuz_baglari()
            kapatmalar()
        oran = min(Decimal("1"), destek / toplam) if toplam > 0 else SIFIR
        return {"toplam": toplam, "desteklenen": _kurus(destek), "desteklenmeyen": _kurus(desteksiz),
                "oran": oran}

    # ------------------------------------------------------------ bakiyeler
    @staticmethod
    def _satis_ozetleri(session, bitis: date | None, sube_id: int | None):
        """Fatura × fon: (brüt satış payı, iade düzeltmesi) — tarih ≤ bitis, aktif kayıtlar."""
        q = (select(FonHareketi.kaynak_fatura_id, FonHareketi.fon_id, FonHareketi.olay,
                    func.sum(FonHareketi.tutar))
             .where(FonHareketi.durum == DURUM_AKTIF, FonHareketi.kaynak_fatura_id.is_not(None))
             .group_by(FonHareketi.kaynak_fatura_id, FonHareketi.fon_id, FonHareketi.olay))
        if bitis:
            q = q.where(FonHareketi.tarih <= bitis)
        if sube_id:
            q = q.where(FonHareketi.sube_id == int(sube_id))
        ozet: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: {"satis": SIFIR, "iade": SIFIR})
        for fatura_id, fon_id, olay, toplam in session.execute(q):
            anahtar = "satis" if olay == OLAY_SATIS else "iade"
            ozet[(int(fatura_id), int(fon_id))][anahtar] += _d(toplam)
        return ozet

    @staticmethod
    def _tahsil_edilen(session, bitis: date | None, sube_id: int | None) -> dict[int, Decimal]:
        from database.models.satis_faturasi import SatisFaturasi

        ozet = FonService._satis_ozetleri(session, bitis, sube_id)
        fatura_idler = {f for f, _ in ozet}
        oranlar: dict[int, Decimal] = {}
        for fatura in session.scalars(select(SatisFaturasi).where(SatisFaturasi.id.in_(fatura_idler))):
            if not fatura.onaylandi:
                oranlar[fatura.id] = SIFIR
                continue
            oranlar[fatura.id] = FonService.fatura_tahsil_orani(session, fatura, bitis)["oran"]
        sonuc: dict[int, Decimal] = defaultdict(lambda: SIFIR)
        for (fatura_id, fon_id), t in ozet.items():
            net = t["satis"] + t["iade"]
            if net <= 0:
                continue
            sonuc[fon_id] += min(net, _kurus(t["satis"] * oranlar.get(fatura_id, SIFIR)))
        return sonuc

    @staticmethod
    def _para_toplamlari(session, bitis: date | None, baslangic: date | None = None):
        q = (select(FonParaHareketi.fon_id, FonParaHareketi.tur, func.sum(FonParaHareketi.tutar))
             .group_by(FonParaHareketi.fon_id, FonParaHareketi.tur))
        if bitis:
            q = q.where(FonParaHareketi.tarih <= bitis)
        if baslangic:
            q = q.where(FonParaHareketi.tarih >= baslangic)
        sonuc: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: SIFIR))
        for fon_id, tur, toplam in session.execute(q):
            sonuc[int(fon_id)][tur] += _d(toplam)
        return sonuc

    @staticmethod
    def _durum(session, bitis: date | None, sube_id: int | None) -> dict[int, dict[str, Decimal]]:
        """Belirli tarih sonu bakiye (kümülatif)."""
        satis_q = (select(FonHareketi.fon_id, FonHareketi.olay, func.sum(FonHareketi.tutar))
                   .where(FonHareketi.durum == DURUM_AKTIF)
                   .group_by(FonHareketi.fon_id, FonHareketi.olay))
        if bitis:
            satis_q = satis_q.where(FonHareketi.tarih <= bitis)
        if sube_id:
            satis_q = satis_q.where(FonHareketi.sube_id == int(sube_id))
        satis: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"satis": SIFIR, "iade": SIFIR})
        for fon_id, olay, toplam in session.execute(satis_q):
            satis[int(fon_id)]["satis" if olay == OLAY_SATIS else "iade"] += _d(toplam)
        tahsil = FonService._tahsil_edilen(session, bitis, sube_id)
        para = FonService._para_toplamlari(session, bitis)
        sonuc = {}
        for fon in session.scalars(select(Fon)):
            s = satis[fon.id]
            p = para[fon.id]
            net = s["satis"] + s["iade"]
            t = tahsil.get(fon.id, SIFIR)
            ayrilmis = p[PARA_AYIR] - p[PARA_AYIR_GERI]
            kullanim = p[PARA_KULLANIM] - p[PARA_KULLANIM_GERI]
            # Transfer satış payı / tahsilatı değiştirmez; yalnız kullanılabilir ayrılmış bakiyeyi taşır
            transfer = p[PARA_TRANSFER_GIRIS] - p[PARA_TRANSFER_CIKIS]
            fark = t - ayrilmis
            sonuc[fon.id] = {
                "brut_satis_payi": s["satis"], "iade": s["iade"], "net_satis_payi": net,
                "tahsil_edilen": t, "tahsil_edilmemis": net - t,
                "ayrilmis": ayrilmis, "kullanim": kullanim, "transfer_net": transfer,
                "transfer_giris": p[PARA_TRANSFER_GIRIS], "transfer_cikis": p[PARA_TRANSFER_CIKIS],
                "kullanilabilir": ayrilmis + transfer - kullanim,
                "ayrilabilir": max(SIFIR, fark), "fon_acigi": max(SIFIR, -fark),
                "kullanim_limiti": max(SIFIR, min(ayrilmis, t) + transfer - kullanim),
            }
        return sonuc

    @staticmethod
    def bakiyeler(baslangic: date | None = None, bitis: date | None = None,
                  sube_id: int | None = None) -> list[dict[str, Any]]:
        """Fon ana tablosu: dönem hareketi ve dönem sonu bakiye ayrı alanlarda."""
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        with get_session() as session:
            kapanis = FonService._durum(session, bitis, sube_id)
            acilis = (FonService._durum(session, baslangic - timedelta(days=1), sube_id)
                      if baslangic else None)
            sonuc = []
            for fon in session.scalars(select(Fon).order_by(Fon.kod)):
                k = kapanis[fon.id]
                a = acilis[fon.id] if acilis else {key: SIFIR for key in k}
                satir = {"fon_id": fon.id, "fon_kod": fon.kod, "fon_ad": fon.ad, "aktif": bool(fon.aktif),
                         **k}
                for alan in ("net_satis_payi", "tahsil_edilen", "ayrilmis", "kullanim", "transfer_net"):
                    satir[f"acilis_{alan}"] = a[alan]
                    satir[f"donem_{alan}"] = k[alan] - a[alan]
                sonuc.append(satir)
            return sonuc

    @staticmethod
    def fon_durumu(fon_id: int, bitis: date | None = None) -> dict[str, Decimal]:
        with get_session() as session:
            return FonService._durum(session, bitis, None)[int(fon_id)]

    # ------------------------------------------------------------ para ayır / kullan
    @staticmethod
    def _kilitle(session, fon_id: int) -> Fon:
        # SQLite yazma kilidi: eşzamanlı ayırma/kullanım kontrolleri sırayla çalışır
        session.execute(update(Fon).where(Fon.id == int(fon_id)).values(guncelleme=func.coalesce(
            Fon.guncelleme, Fon.olusturma)))
        fon = session.get(Fon, int(fon_id))
        if fon is None:
            raise ValueError("Fon bulunamadı.")
        return fon

    @staticmethod
    def _kaynak_kapasitesi(session, anahtar: str) -> tuple[Decimal, str]:
        from database.finans_service import _makbuz_sekil_turu
        from database.models.finans import FinansHareketi, KasaMakbuzu
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiTahsilati

        tur, _, deger = (anahtar or "").partition(":")
        if tur == "FT":
            th = session.get(SatisFaturasiTahsilati, int(deger))
            if th is None:
                raise ValueError("Kaynak tahsilat bulunamadı.")
            fatura = session.get(SatisFaturasi, th.fatura_id)
            if fatura is None or not fatura.onaylandi or fatura.durum == "İPTAL":
                raise ValueError("Kaynak tahsilatın faturası onaylı değil.")
            if _makbuz_sekil_turu(th.odeme_sekli) not in DESTEKLENEN_YONTEMLER:
                raise ValueError("Kaynak tahsilat yöntemi desteklenmiyor.")
            return _d(th.tutar), f"{fatura.fatura_no} tahsilatı ({th.odeme_sekli})"
        if tur == "MKB":
            mkb = session.scalar(select(KasaMakbuzu).where(KasaMakbuzu.belge_no == deger))
            if mkb is None or (mkb.durum or "").upper() == "IPTAL" or mkb.makbuz_turu != "TAHSILAT":
                raise ValueError("Kaynak makbuz geçerli bir tahsilat değil.")
            destek = sum((_d(s.tutar) for s in mkb.satirlar
                          if _makbuz_sekil_turu(s.odeme_sekli) in DESTEKLENEN_YONTEMLER), SIFIR)
            return destek, f"Makbuz {mkb.belge_no}"
        if tur == "THS":
            toplam = session.scalar(select(func.coalesce(func.sum(FinansHareketi.tutar), 0)).where(
                FinansHareketi.belge_no == deger, FinansHareketi.tutar > 0,
                FinansHareketi.hareket_turu == "CARİ TAHSİLAT"))
            if not _d(toplam):
                raise ValueError("Kaynak cari tahsilat bulunamadı.")
            return _d(toplam), f"Cari tahsilat {deger}"
        raise ValueError("Geçersiz kaynak tahsilat.")

    @staticmethod
    def _kaynak_kullanilan(session, anahtar: str) -> Decimal:
        ayir = _d(session.scalar(select(func.coalesce(func.sum(FonParaHareketi.tutar), 0)).where(
            FonParaHareketi.kaynak_anahtar == anahtar, FonParaHareketi.tur == PARA_AYIR)))
        geri = _d(session.scalar(select(func.coalesce(func.sum(FonParaHareketi.tutar), 0)).where(
            FonParaHareketi.kaynak_anahtar == anahtar, FonParaHareketi.tur == PARA_AYIR_GERI)))
        return ayir - geri

    @staticmethod
    def kaynak_kullanilan(anahtar: str) -> Decimal:
        with get_session() as session:
            return FonService._kaynak_kullanilan(session, anahtar)

    @staticmethod
    def kaynak_tahsilatlar(limit: int = 300) -> list[dict[str, Any]]:
        """Para ayırmada seçilebilecek kesin tahsilatlar (kapasite ve kalan dağıtılabilir)."""
        from database.finans_service import _makbuz_sekil_turu
        from database.models.finans import KasaMakbuzu
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiTahsilati

        sonuc = []
        with get_session() as session:
            for mkb in session.scalars(
                select(KasaMakbuzu).where(KasaMakbuzu.makbuz_turu == "TAHSILAT", KasaMakbuzu.durum != "IPTAL")
                .order_by(KasaMakbuzu.tarih.desc(), KasaMakbuzu.id.desc()).limit(limit)
            ):
                anahtar = f"MKB:{mkb.belge_no}"
                kap, ad = FonService._kaynak_kapasitesi(session, anahtar)
                if kap <= 0:
                    continue
                sonuc.append({"anahtar": anahtar, "tarih": mkb.tarih, "aciklama": ad, "kapasite": kap,
                              "kalan": kap - FonService._kaynak_kullanilan(session, anahtar)})
            for th, fatura in session.execute(
                select(SatisFaturasiTahsilati, SatisFaturasi)
                .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiTahsilati.fatura_id)
                .where(SatisFaturasi.onaylandi.is_(True), SatisFaturasi.durum != "İPTAL")
                .order_by(SatisFaturasiTahsilati.tahsilat_tarihi.desc()).limit(limit)
            ):
                if _makbuz_sekil_turu(th.odeme_sekli) not in DESTEKLENEN_YONTEMLER or _d(th.tutar) <= 0:
                    continue
                anahtar = f"FT:{th.id}"
                sonuc.append({"anahtar": anahtar, "tarih": th.tahsilat_tarihi,
                              "aciklama": f"{fatura.fatura_no} tahsilatı ({th.odeme_sekli})",
                              "kapasite": _d(th.tutar),
                              "kalan": _d(th.tutar) - FonService._kaynak_kullanilan(session, anahtar)})
        sonuc.sort(key=lambda r: (r["tarih"] or date.min), reverse=True)
        return sonuc

    @staticmethod
    def _tekrar_kontrol(session, istek_kimligi: str | None) -> FonParaHareketi | None:
        if not istek_kimligi:
            return None
        return session.scalar(select(FonParaHareketi).where(FonParaHareketi.istek_kimligi == istek_kimligi))

    @staticmethod
    def para_ayir(fon_id: int, tarih: date, tutar, *, aciklama: str | None = None,
                  hesap_adi: str | None = None, finans_belge_no: str | None = None,
                  kaynak_anahtar: str | None = None, istek_kimligi: str | None = None) -> int:
        yazma_zorunlu("fon_para_ayirma", "finans_duzenleme")
        tutar = _kurus(tutar_oku(tutar))
        if tutar <= 0:
            raise ValueError("Ayrılacak tutar pozitif olmalıdır.")
        with get_session() as session:
            onceki = FonService._tekrar_kontrol(session, istek_kimligi)
            if onceki is not None:
                return int(onceki.id)
            fon = FonService._kilitle(session, fon_id)
            if not fon.aktif:
                raise ValueError("Pasif fona para ayrılamaz.")
            durum = FonService._durum(session, None, None)[fon.id]
            if tutar > durum["ayrilabilir"]:
                raise ValueError(
                    f"Ayırma, fonun tahsil edilmiş fakat henüz ayrılmamış tutarını aşamaz. "
                    f"Ayrılabilecek ek tutar: {durum['ayrilabilir']:.2f} TL"
                )
            kaynak_ad = None
            if kaynak_anahtar:
                kapasite, kaynak_ad = FonService._kaynak_kapasitesi(session, kaynak_anahtar)
                kalan = kapasite - FonService._kaynak_kullanilan(session, kaynak_anahtar)
                if tutar > kalan:
                    raise ValueError(
                        f"Aynı kaynak paradan fonlara yapılan dağıtım kaynak tutarını aşamaz. "
                        f"Kaynakta kalan: {kalan:.2f} TL"
                    )
            belge = (finans_belge_no or "").strip() or None
            kayit = FonParaHareketi(
                firma_id=_firma_id(), fon_id=fon.id, tur=PARA_AYIR, tarih=tarih, tutar=tutar,
                aciklama=(aciklama or "").strip() or None, hesap_adi=(hesap_adi or "").strip() or None,
                finans_belge_no=belge, belgesiz=not (belge or kaynak_anahtar),
                kaynak_anahtar=kaynak_anahtar or None, kaynak_aciklama=kaynak_ad,
                istek_kimligi=istek_kimligi or None, kullanici=_kullanici(),
            )
            session.add(kayit)
            session.flush()
            kid = int(kayit.id)
        FonService._audit("fon_para_ayir", kid, yeni=f"fon={fon_id} {tutar}")
        return kid

    @staticmethod
    def ayirmayi_geri_al(ayirma_id: int, tutar, gerekce: str, tarih: date | None = None,
                         istek_kimligi: str | None = None) -> int:
        yazma_zorunlu("fon_duzeltme", "fon_para_ayirma", "finans_duzenleme")
        gerekce = (gerekce or "").strip()
        if not gerekce:
            raise ValueError("Ayırmayı geri almak için gerekçe zorunludur.")
        tutar = _kurus(tutar_oku(tutar))
        if tutar <= 0:
            raise ValueError("Geri alınacak tutar pozitif olmalıdır.")
        with get_session() as session:
            onceki = FonService._tekrar_kontrol(session, istek_kimligi)
            if onceki is not None:
                return int(onceki.id)
            ayirma = session.get(FonParaHareketi, int(ayirma_id))
            if ayirma is None or ayirma.tur != PARA_AYIR:
                raise ValueError("Geri alınacak ayırma kaydı bulunamadı.")
            FonService._kilitle(session, ayirma.fon_id)
            geri = _d(session.scalar(select(func.coalesce(func.sum(FonParaHareketi.tutar), 0)).where(
                FonParaHareketi.ref_id == ayirma.id, FonParaHareketi.tur == PARA_AYIR_GERI)))
            if tutar > _d(ayirma.tutar) - geri:
                raise ValueError(f"Bu ayırmadan geri alınabilecek en fazla {_d(ayirma.tutar) - geri:.2f} TL.")
            durum = FonService._durum(session, None, None)[ayirma.fon_id]
            if durum["ayrilmis"] + durum["transfer_net"] - tutar < durum["kullanim"]:
                raise ValueError(
                    "Kullanılmış veya başka fona transfer edilmiş tutar geri alınamaz; önce kullanımı / "
                    "transferi düzeltin."
                )
            kayit = FonParaHareketi(
                firma_id=_firma_id(), fon_id=ayirma.fon_id, tur=PARA_AYIR_GERI, tarih=tarih or date.today(),
                tutar=tutar, aciklama=f"Ayırma #{ayirma.id} geri alındı", hesap_adi=ayirma.hesap_adi,
                belgesiz=ayirma.belgesiz, kaynak_anahtar=ayirma.kaynak_anahtar,
                kaynak_aciklama=ayirma.kaynak_aciklama, ref_id=ayirma.id, gerekce=gerekce,
                istek_kimligi=istek_kimligi or None, kullanici=_kullanici(),
            )
            session.add(kayit)
            session.flush()
            kid = int(kayit.id)
        FonService._audit("fon_ayirma_geri_al", kid, yeni=f"ayirma={ayirma_id} {tutar} — {gerekce}")
        return kid

    @staticmethod
    def fon_kullan(fon_id: int, tarih: date, tutar, *, yardim_alan: str, amac: str,
                   aciklama: str | None = None, hesap_adi: str | None = None,
                   finans_belge_no: str | None = None, istek_kimligi: str | None = None) -> int:
        yazma_zorunlu("fon_kullanim", "finans_duzenleme")
        tutar = _kurus(tutar_oku(tutar))
        if tutar <= 0:
            raise ValueError("Kullanım tutarı pozitif olmalıdır.")
        if not (yardim_alan or "").strip():
            raise ValueError("Kullanımda yardım alan / ödeme yapılan kişi zorunludur.")
        if not (amac or "").strip():
            raise ValueError("Kullanım amacı zorunludur.")
        with get_session() as session:
            onceki = FonService._tekrar_kontrol(session, istek_kimligi)
            if onceki is not None:
                return int(onceki.id)
            fon = FonService._kilitle(session, fon_id)
            durum = FonService._durum(session, None, None)[fon.id]
            if durum["fon_acigi"] > 0:
                raise ValueError(
                    f"Fon açığı var ({durum['fon_acigi']:.2f} TL): ayrılmış tutar hak edilen payı aşıyor. "
                    "Yeni kullanım kaydedilemez."
                )
            if tutar > durum["kullanim_limiti"]:
                raise ValueError(
                    f"Kullanım, kullanılabilir ayrılmış bakiyeyi aşamaz. Kullanılabilir: "
                    f"{durum['kullanim_limiti']:.2f} TL"
                )
            belge = (finans_belge_no or "").strip() or None
            kayit = FonParaHareketi(
                firma_id=_firma_id(), fon_id=fon.id, tur=PARA_KULLANIM, tarih=tarih, tutar=tutar,
                aciklama=(aciklama or "").strip() or None, hesap_adi=(hesap_adi or "").strip() or None,
                finans_belge_no=belge, belgesiz=belge is None, yardim_alan=yardim_alan.strip(),
                amac=amac.strip(), istek_kimligi=istek_kimligi or None, kullanici=_kullanici(),
            )
            session.add(kayit)
            session.flush()
            kid = int(kayit.id)
        FonService._audit("fon_kullanim", kid, yeni=f"fon={fon_id} {tutar} → {yardim_alan}")
        return kid

    @staticmethod
    def kullanimi_duzelt(kullanim_id: int, tutar, gerekce: str, tarih: date | None = None,
                         istek_kimligi: str | None = None) -> int:
        yazma_zorunlu("fon_duzeltme", "finans_duzenleme")
        gerekce = (gerekce or "").strip()
        if not gerekce:
            raise ValueError("Kullanım düzeltmesi için gerekçe zorunludur.")
        tutar = _kurus(tutar_oku(tutar))
        if tutar <= 0:
            raise ValueError("Düzeltme tutarı pozitif olmalıdır.")
        with get_session() as session:
            onceki = FonService._tekrar_kontrol(session, istek_kimligi)
            if onceki is not None:
                return int(onceki.id)
            kullanim = session.get(FonParaHareketi, int(kullanim_id))
            if kullanim is None or kullanim.tur != PARA_KULLANIM:
                raise ValueError("Düzeltilecek kullanım kaydı bulunamadı.")
            FonService._kilitle(session, kullanim.fon_id)
            geri = _d(session.scalar(select(func.coalesce(func.sum(FonParaHareketi.tutar), 0)).where(
                FonParaHareketi.ref_id == kullanim.id, FonParaHareketi.tur == PARA_KULLANIM_GERI)))
            if tutar > _d(kullanim.tutar) - geri:
                raise ValueError(f"Bu kullanımdan en fazla {_d(kullanim.tutar) - geri:.2f} TL düzeltilebilir.")
            kayit = FonParaHareketi(
                firma_id=_firma_id(), fon_id=kullanim.fon_id, tur=PARA_KULLANIM_GERI,
                tarih=tarih or date.today(), tutar=tutar, aciklama=f"Kullanım #{kullanim.id} düzeltmesi",
                belgesiz=kullanim.belgesiz, yardim_alan=kullanim.yardim_alan, amac=kullanim.amac,
                ref_id=kullanim.id, gerekce=gerekce, istek_kimligi=istek_kimligi or None,
                kullanici=_kullanici(),
            )
            session.add(kayit)
            session.flush()
            kid = int(kayit.id)
        FonService._audit("fon_kullanim_duzelt", kid, yeni=f"kullanim={kullanim_id} {tutar} — {gerekce}")
        return kid

    # ------------------------------------------------------------ fon transferi
    @staticmethod
    def transfer_onizleme(kaynak_fon_id: int, hedef_fon_id: int | None = None, tutar=None) -> dict[str, Any]:
        """Transfer ekranı: kaynağın kullanılabilir bakiyesi ve transfer sonrası iki fonun bakiyesi."""
        with get_session() as session:
            durum = FonService._durum(session, None, None)
            k = durum.get(int(kaynak_fon_id)) if kaynak_fon_id else None
            h = durum.get(int(hedef_fon_id)) if hedef_fon_id else None
            t = SIFIR
            if tutar not in (None, ""):
                try:
                    t = _kurus(tutar_oku(tutar))
                except ValueError:
                    t = SIFIR
            kaynak_limit = k["kullanim_limiti"] if k else SIFIR
            return {
                "kaynak_kullanilabilir": kaynak_limit,
                "kaynak_sonra": (kaynak_limit - t) if k else None,
                "hedef_kullanilabilir": h["kullanim_limiti"] if h else None,
                "hedef_sonra": (h["kullanim_limiti"] + t) if h else None,
            }

    @staticmethod
    def _transfer_no(session, tarih: date) -> str:
        on_ek = f"FTR{tarih:%Y}-"
        son = session.scalar(
            select(func.max(FonTransferi.transfer_no)).where(FonTransferi.transfer_no.like(f"{on_ek}%"))
        )
        sira = int(son.rsplit("-", 1)[1]) + 1 if son else 1
        return f"{on_ek}{sira:05d}"

    @staticmethod
    def transfer_kaydet(kaynak_fon_id: int, hedef_fon_id: int, tarih: date, tutar, *,
                        aciklama: str | None = None, istek_kimligi: str | None = None,
                        firma_id: int | None = None) -> int:
        """Kaynak fondan hedef fona kullanılabilir ayrılmış TL bakiye aktarır (tek DB işlemi).

        Kasa/banka hareketi ve muhasebe fişi oluşturmaz; şirket toplamı değişmez.
        """
        yazma_zorunlu("fon_transfer", "finans_duzenleme")
        FonService.schema_hazirla()
        if not kaynak_fon_id or not hedef_fon_id:
            raise ValueError("Kaynak ve hedef fon seçilmelidir.")
        kaynak_fon_id, hedef_fon_id = int(kaynak_fon_id), int(hedef_fon_id)
        if kaynak_fon_id == hedef_fon_id:
            raise ValueError("Kaynak ve hedef fon aynı olamaz.")
        tutar = _kurus(tutar_oku(tutar, "Transfer tutarı"))
        if tutar <= 0:
            raise ValueError("Transfer tutarı sıfırdan büyük olmalıdır.")
        if tarih is None:
            raise ValueError("Transfer tarihi zorunludur.")
        aktif_firma = _firma_id()
        if firma_id is not None and int(firma_id) != aktif_firma:
            raise ValueError("Farklı firmaların fonları arasında transfer yapılamaz.")
        with get_session() as session:
            # Sabit sırada kilit: eşzamanlı transferler / tekrar gönderimler sırayla değerlendirilir
            fonlar = {fid: FonService._kilitle(session, fid) for fid in sorted((kaynak_fon_id, hedef_fon_id))}
            if istek_kimligi:
                onceki = session.scalar(select(FonTransferi).where(FonTransferi.istek_kimligi == istek_kimligi))
                if onceki is not None:
                    return int(onceki.id)
            kaynak, hedef = fonlar[kaynak_fon_id], fonlar[hedef_fon_id]
            if not kaynak.aktif or not hedef.aktif:
                raise ValueError("Pasif fon transferde kullanılamaz.")
            durum = FonService._durum(session, None, None)
            limit = durum[kaynak.id]["kullanim_limiti"]
            if tutar > limit:
                raise ValueError(
                    f"Transfer tutarı kaynak fonun kullanılabilir bakiyesini aşamaz. "
                    f"{kaynak.kod} kullanılabilir: {limit:.2f} TL (kullanılmış ve tahsil edilmemiş "
                    "tutar transfer edilemez)."
                )
            kullanici = _kullanici()
            aciklama = (aciklama or "").strip() or None
            kayit = FonTransferi(
                transfer_no=FonService._transfer_no(session, tarih), firma_id=aktif_firma, tarih=tarih,
                kaynak_fon_id=kaynak.id, hedef_fon_id=hedef.id, tutar=tutar, aciklama=aciklama,
                durum=TRANSFER_AKTIF, istek_kimligi=istek_kimligi or None, kullanici=kullanici,
            )
            session.add(kayit)
            session.flush()
            metin = f"Transfer {kayit.transfer_no}: {kaynak.kod} → {hedef.kod}"
            for fon, tur in ((kaynak, PARA_TRANSFER_CIKIS), (hedef, PARA_TRANSFER_GIRIS)):
                session.add(FonParaHareketi(
                    firma_id=aktif_firma, fon_id=fon.id, tur=tur, tarih=tarih, tutar=tutar,
                    aciklama=metin + (f" — {aciklama}" if aciklama else ""), belgesiz=True,
                    finans_belge_no=kayit.transfer_no, ref_id=kayit.id, kullanici=kullanici,
                ))
            session.flush()
            tid, no = int(kayit.id), kayit.transfer_no
            kaynak_kod, hedef_kod = kaynak.kod, hedef.kod
        FonService._audit("fon_transfer", tid,
                          yeni=f"{no} {tarih:%d.%m.%Y} {kaynak_kod}→{hedef_kod} {tutar} TL "
                               f"kullanıcı={kullanici or ''} — {aciklama or ''}")
        return tid

    @staticmethod
    def transfer_iptal(transfer_id: int, gerekce: str, tarih: date | None = None) -> None:
        """Bağlı ters hareketlerle iptal; hedefin kullanılabilir bakiyesi yetmezse engellenir."""
        yazma_zorunlu("fon_transfer", "fon_duzeltme", "finans_duzenleme")
        gerekce = (gerekce or "").strip()
        if not gerekce:
            raise ValueError("Transfer iptali için gerekçe zorunludur.")
        with get_session() as session:
            kayit = session.get(FonTransferi, int(transfer_id))
            if kayit is None:
                raise ValueError("Transfer bulunamadı.")
            fonlar = {fid: FonService._kilitle(session, fid)
                      for fid in sorted((kayit.kaynak_fon_id, kayit.hedef_fon_id))}
            session.refresh(kayit)
            if kayit.durum == TRANSFER_IPTAL:
                raise ValueError("Bu transfer zaten iptal edilmiş.")
            tutar = _d(kayit.tutar)
            hedef = fonlar[kayit.hedef_fon_id]
            limit = FonService._durum(session, None, None)[hedef.id]["kullanim_limiti"]
            if tutar > limit:
                raise ValueError(
                    f"Hedef fonun ({hedef.kod}) kullanılabilir bakiyesi ({limit:.2f} TL) iptal için yetersiz; "
                    "transfer edilen tutar kullanılmış."
                )
            ters_tarih = tarih or date.today()
            kullanici = _kullanici()
            metin = f"Transfer {kayit.transfer_no} iptali"
            for fon_id, tur in ((kayit.hedef_fon_id, PARA_TRANSFER_CIKIS),
                                (kayit.kaynak_fon_id, PARA_TRANSFER_GIRIS)):
                session.add(FonParaHareketi(
                    firma_id=kayit.firma_id, fon_id=fon_id, tur=tur, tarih=ters_tarih, tutar=tutar,
                    aciklama=metin, belgesiz=True, finans_belge_no=kayit.transfer_no, ref_id=kayit.id,
                    gerekce=gerekce, kullanici=kullanici,
                ))
            kayit.durum = TRANSFER_IPTAL
            kayit.iptal_tarihi = ters_tarih
            kayit.iptal_gerekcesi = gerekce[:300]
            kayit.iptal_eden = kullanici
            kayit.iptal_zamani = datetime.now()
            no = kayit.transfer_no
        FonService._audit("fon_transfer_iptal", transfer_id, eski=no, yeni=f"{tutar} TL — {gerekce}")

    @staticmethod
    def transfer_listesi(*, fon_id: int | None = None, baslangic: date | None = None,
                         bitis: date | None = None) -> list[dict[str, Any]]:
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        from sqlalchemy.orm import aliased

        kf, hf = aliased(Fon), aliased(Fon)
        with get_session() as session:
            q = (select(FonTransferi, kf.kod, hf.kod)
                 .join(kf, kf.id == FonTransferi.kaynak_fon_id)
                 .join(hf, hf.id == FonTransferi.hedef_fon_id))
            if fon_id:
                q = q.where((FonTransferi.kaynak_fon_id == int(fon_id)) | (FonTransferi.hedef_fon_id == int(fon_id)))
            if baslangic:
                q = q.where(FonTransferi.tarih >= baslangic)
            if bitis:
                q = q.where(FonTransferi.tarih <= bitis)
            q = q.order_by(FonTransferi.tarih.desc(), FonTransferi.id.desc())
            return [{
                "id": t.id, "transfer_no": t.transfer_no, "tarih": t.tarih, "kaynak_fon_id": t.kaynak_fon_id,
                "kaynak_fon": k_kod, "hedef_fon_id": t.hedef_fon_id, "hedef_fon": h_kod, "tutar": t.tutar,
                "aciklama": t.aciklama or "", "durum": "İptal" if t.durum == TRANSFER_IPTAL else "Aktif",
                "kullanici": t.kullanici or "", "olusturma": t.olusturma,
                "iptal_tarihi": t.iptal_tarihi, "iptal_gerekcesi": t.iptal_gerekcesi or "",
                "iptal_eden": t.iptal_eden or "",
            } for t, k_kod, h_kod in session.execute(q)]

    @staticmethod
    def transfer_hareketleri(transfer_id: int) -> list[dict[str, Any]]:
        """Transferin iki fondaki hareketleri ve (varsa) iptal ters kayıtları."""
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        with get_session() as session:
            q = (select(FonParaHareketi, Fon.kod).join(Fon, Fon.id == FonParaHareketi.fon_id)
                 .where(FonParaHareketi.ref_id == int(transfer_id),
                        FonParaHareketi.tur.in_((PARA_TRANSFER_CIKIS, PARA_TRANSFER_GIRIS)))
                 .order_by(FonParaHareketi.id))
            return [{
                "id": p.id, "tarih": p.tarih, "fon_kod": kod, "tur": p.tur,
                "tur_adi": PARA_TUR_ADLARI.get(p.tur, p.tur), "tutar": p.tutar, "aciklama": p.aciklama or "",
                "ters_kayit": bool(p.gerekce), "gerekce": p.gerekce or "", "kullanici": p.kullanici or "",
            } for p, kod in session.execute(q)]

    # ------------------------------------------------------------ listeler / raporlar
    @staticmethod
    def hareket_listesi(*, fon_id: int | None = None, baslangic: date | None = None,
                        bitis: date | None = None, sube_id: int | None = None, stok_id: int | None = None,
                        sayfa: int = 0, sayfa_boyu: int = 500) -> list[dict[str, Any]]:
        """Satış payı / iade hareketleri (iptal ve inceleme kayıtları da görünür; toplama girmez)."""
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        from database.models.cari import Cari

        with get_session() as session:
            q = (select(FonHareketi, Fon.kod, Cari.unvan)
                 .join(Fon, Fon.id == FonHareketi.fon_id)
                 .outerjoin(Cari, Cari.id == FonHareketi.cari_id))
            if fon_id:
                q = q.where(FonHareketi.fon_id == int(fon_id))
            if baslangic:
                q = q.where(FonHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FonHareketi.tarih <= bitis)
            if sube_id:
                q = q.where(FonHareketi.sube_id == int(sube_id))
            if stok_id:
                q = q.where(FonHareketi.stok_id == int(stok_id))
            q = q.order_by(FonHareketi.tarih.desc(), FonHareketi.id.desc()).offset(
                max(0, sayfa) * sayfa_boyu).limit(sayfa_boyu)
            return [{
                "id": h.id, "tarih": h.tarih, "tur": {OLAY_SATIS: "Satış payı", OLAY_IADE: "İade düzeltmesi",
                                                      OLAY_INCELEME: "İade (inceleme)"}.get(h.olay, h.olay),
                "olay": h.olay, "kaynak_turu": h.kaynak_turu, "belge_id": h.belge_id, "belge_no": h.belge_no,
                "urun_kodu": h.urun_kodu or "", "urun_adi": h.urun_adi or "", "cari": unvan or "",
                "fon_kod": kod, "oran": h.oran, "taban": h.taban, "tutar": h.tutar, "durum": h.durum,
                "yontem": h.yontem, "yontem_adi": YONTEM_ETIKETLERI.get(h.yontem, h.yontem),
                "para_birimi": h.para_birimi, "kur": h.kur, "doviz_tutar": h.doviz_tutar,
                "doviz_taban": h.doviz_taban,
                "kaynak_fatura_id": h.kaynak_fatura_id, "revizyon": h.revizyon,
                "aciklama": h.aciklama or h.iptal_nedeni or "",
            } for h, kod, unvan in session.execute(q)]

    @staticmethod
    def para_hareketleri(*, fon_id: int | None = None, baslangic: date | None = None,
                         bitis: date | None = None) -> list[dict[str, Any]]:
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        adlar = PARA_TUR_ADLARI
        with get_session() as session:
            q = select(FonParaHareketi, Fon.kod).join(Fon, Fon.id == FonParaHareketi.fon_id)
            if fon_id:
                q = q.where(FonParaHareketi.fon_id == int(fon_id))
            if baslangic:
                q = q.where(FonParaHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FonParaHareketi.tarih <= bitis)
            q = q.order_by(FonParaHareketi.tarih.desc(), FonParaHareketi.id.desc())
            return [{
                "id": p.id, "tarih": p.tarih, "tur": p.tur, "tur_adi": adlar.get(p.tur, p.tur), "fon_kod": kod,
                "tutar": p.tutar, "hesap_adi": p.hesap_adi or "",
                "belge": p.finans_belge_no or ("Belgesiz iç takip kaydı" if p.belgesiz else ""),
                "kaynak": p.kaynak_aciklama or "", "yardim_alan": p.yardim_alan or "", "amac": p.amac or "",
                "aciklama": p.aciklama or "", "gerekce": p.gerekce or "", "ref_id": p.ref_id,
                "kullanici": p.kullanici or "",
            } for p, kod in session.execute(q)]

    @staticmethod
    def urun_bazli_rapor(baslangic: date | None = None, bitis: date | None = None) -> list[dict[str, Any]]:
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        with get_session() as session:
            q = (select(FonHareketi.urun_kodu, FonHareketi.urun_adi, Fon.kod, FonHareketi.olay,
                        func.sum(FonHareketi.taban), func.sum(FonHareketi.tutar))
                 .join(Fon, Fon.id == FonHareketi.fon_id)
                 .where(FonHareketi.durum == DURUM_AKTIF)
                 .group_by(FonHareketi.urun_kodu, Fon.kod, FonHareketi.olay))
            if baslangic:
                q = q.where(FonHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FonHareketi.tarih <= bitis)
            satirlar: dict[tuple[str, str], dict[str, Any]] = {}
            for kod, ad, fon, olay, taban, tutar in session.execute(q):
                s = satirlar.setdefault((kod or "", fon), {"urun_kodu": kod or "", "urun_adi": ad or "",
                                                          "fon_kod": fon, "taban": SIFIR, "satis_payi": SIFIR,
                                                          "iade": SIFIR})
                s["taban"] += _d(taban)
                s["satis_payi" if olay == OLAY_SATIS else "iade"] += _d(tutar)
            for s in satirlar.values():
                s["net"] = s["satis_payi"] + s["iade"]
            return sorted(satirlar.values(), key=lambda r: (r["urun_kodu"], r["fon_kod"]))

    @staticmethod
    def tarih_bazli_rapor(baslangic: date | None = None, bitis: date | None = None) -> list[dict[str, Any]]:
        yetki_zorunlu("fon_goruntuleme", "finans_goruntuleme", "finans_duzenleme")
        if not tablolar_var():
            return []
        with get_session() as session:
            gun: dict[tuple[date, str], dict[str, Any]] = {}

            def satir(t, fon):
                return gun.setdefault((t, fon), {"tarih": t, "fon_kod": fon, "satis_payi": SIFIR,
                                                 "iade": SIFIR, "ayrilan": SIFIR, "kullanim": SIFIR,
                                                 "transfer": SIFIR})

            q = (select(FonHareketi.tarih, Fon.kod, FonHareketi.olay, func.sum(FonHareketi.tutar))
                 .join(Fon, Fon.id == FonHareketi.fon_id).where(FonHareketi.durum == DURUM_AKTIF)
                 .group_by(FonHareketi.tarih, Fon.kod, FonHareketi.olay))
            p = (select(FonParaHareketi.tarih, Fon.kod, FonParaHareketi.tur, func.sum(FonParaHareketi.tutar))
                 .join(Fon, Fon.id == FonParaHareketi.fon_id)
                 .group_by(FonParaHareketi.tarih, Fon.kod, FonParaHareketi.tur))
            if baslangic:
                q = q.where(FonHareketi.tarih >= baslangic)
                p = p.where(FonParaHareketi.tarih >= baslangic)
            if bitis:
                q = q.where(FonHareketi.tarih <= bitis)
                p = p.where(FonParaHareketi.tarih <= bitis)
            for t, fon, olay, tutar in session.execute(q):
                satir(t, fon)["satis_payi" if olay == OLAY_SATIS else "iade"] += _d(tutar)
            for t, fon, tur, tutar in session.execute(p):
                s = satir(t, fon)
                if tur == PARA_AYIR:
                    s["ayrilan"] += _d(tutar)
                elif tur == PARA_AYIR_GERI:
                    s["ayrilan"] -= _d(tutar)
                elif tur == PARA_KULLANIM:
                    s["kullanim"] += _d(tutar)
                elif tur == PARA_KULLANIM_GERI:
                    s["kullanim"] -= _d(tutar)
                elif tur == PARA_TRANSFER_GIRIS:
                    s["transfer"] += _d(tutar)
                elif tur == PARA_TRANSFER_CIKIS:
                    s["transfer"] -= _d(tutar)
            return [gun[k] for k in sorted(gun)]

    @staticmethod
    def mutabakat(baslangic: date | None = None, bitis: date | None = None,
                  sube_id: int | None = None) -> list[dict[str, Any]]:
        """Açılış + dönem hareketleri = kapanış (fon × tutar türü)."""
        sonuc = []
        for b in FonService.bakiyeler(baslangic, bitis, sube_id):
            for alan, ad in (("net_satis_payi", "Net satış payı"), ("tahsil_edilen", "Tahsil edilen pay"),
                             ("ayrilmis", "Ayrılmış para"), ("kullanim", "Kullanım"),
                             ("transfer_net", "Transfer (net)")):
                acilis, donem, kapanis = b[f"acilis_{alan}"], b[f"donem_{alan}"], b[alan]
                sonuc.append({"fon_kod": b["fon_kod"], "kalem": ad, "acilis": acilis, "donem": donem,
                              "kapanis": kapanis, "tutarli": acilis + donem == kapanis})
        return sonuc

    @staticmethod
    def stok_fon_gecmisi(stok_id: int) -> list[dict[str, Any]]:
        return FonService.hareket_listesi(stok_id=stok_id)

    # ------------------------------------------------------------ denetim
    @staticmethod
    def _audit(islem: str, kayit_id, *, eski: str | None = None, yeni: str | None = None) -> None:
        try:
            from database.database import get_system_session
            from database.system.auth_service import AuthService

            with get_system_session() as sys_s:
                AuthService.audit(sys_s, islem, modul="fon", kayit_id=str(kayit_id),
                                  eski_deger=eski, yeni_deger=yeni)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["FonService", "oran_oku", "tutar_oku", "dagit", "AccessError", "yetki_var",
           "TUTAR_ACIKLAMALARI", "DESTEKLENEN_TAHSILAT_ACIKLAMA", "YONTEM_ETIKETLERI", "PARA_TUR_ADLARI"]
