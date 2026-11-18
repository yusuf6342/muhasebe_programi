"""Hizmet alış (gider) / satış (gelir) fatura servisi — sade standart fatura."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.access import yazma_zorunlu
from database.doviz_service import DovizService
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.hizmet import HizmetHareketi, HizmetKarti
from database.models.hizmet_faturasi import HizmetFaturasi, HizmetFaturasiSatiri
from database.satis_siparisi_service import decimal

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
ODEME_SEKILLERI = ("KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME")
TAHSILAT_SEKILLERI = ("KASA TAHSİLAT", "ALINAN HAVALE", "KREDİ KARTIYLA TAHSİLAT")

HAREKET_GIDER = "HİZMET ALIŞ (GİDER)"
HAREKET_GELIR = "HİZMET SATIŞ (GELİR)"
HAREKET_GIDER_IADE = "HİZMET ALIŞ İADE"
HAREKET_GELIR_IADE = "HİZMET SATIŞ İADE"

FATURA_TURLERI = ("GIDER", "GELIR", "GIDER_IADE", "GELIR_IADE")

# Cari SatisHareketi işareti: alış/gider negatif (tedarikçi alacak); satış/gelir pozitif (müşteri borç).
_SH_ISARET = {"GIDER": -1, "GELIR": 1, "GIDER_IADE": 1, "GELIR_IADE": -1}

# Defter / ekstre belge türü etiketleri (kaynak fatura_turu).
BELGE_TUR_ETIKET = {
    "GIDER": "Hizmet Alış",
    "GELIR": "Hizmet Satış",
    "GIDER_IADE": "Hizmet Alış İadesi",
    "GELIR_IADE": "Hizmet Satış İadesi",
}


def _kart_turu(fatura_turu: str) -> str:
    """İade faturaları ilgili yönün hizmet kartını kullanır."""
    tur = (fatura_turu or "GIDER").upper()
    if tur in ("GIDER", "GIDER_IADE"):
        return "GIDER"
    return "GELIR"


def _sh_tutar_ve_kalan(tur: str, genel_toplam, odeme_tutari) -> tuple[Decimal, Decimal]:
    """Alış faturası ile aynı: GIDER negatif SH; kalan aynı işaretle açık tutar."""
    isaret = _SH_ISARET.get((tur or "GIDER").upper(), -1)
    brut = abs(Decimal(str(genel_toplam or 0)))
    odenen = abs(Decimal(str(odeme_tutari or 0)))
    kalan_abs = brut - odenen
    satis = isaret * brut
    if kalan_abs > 0:
        kalan = isaret * kalan_abs
    elif kalan_abs < 0:
        # Fazla ödeme/tahsilat: ters işaretli avans (alışta pozitif kalan = avans)
        kalan = -isaret * abs(kalan_abs)
    else:
        kalan = Decimal("0")
    return satis, kalan


def odeme_sekli_hesap_uygun_mu(
    odeme_sekli: str | None,
    hesap_adi: str | None,
    *,
    gelir_mi: bool,
    finans_hesap_id: int | None = None,
) -> str | None:
    """Uygun değilse hata metni; uygunsa None. Kayıt katmanı + UI ortak.

    Hesap türü görünen addan değil; ``odeme_hesaplari`` / ``tahsilat_hesaplari``
    (alt_hesap_turu / hesap_turu) ile doğrulanır. Eski kayıtta firma kartı etiketi
    verilmişse bağlı ``KREDI_KARTI`` hesabına çözülür.
    """
    sekil = (odeme_sekli or "").strip()
    hesap = (hesap_adi or "").strip()
    if not sekil:
        return None
    if not hesap and not finans_hesap_id:
        return "Hesap seçin."
    from database.finans_service import FinansService

    tur = FinansService.odeme_sekil_turu(sekil, gelir_mi=gelir_mi)
    try:
        adaylar = (
            FinansService.tahsilat_hesaplari(sekil)
            if gelir_mi
            else FinansService.odeme_hesaplari(sekil)
        )
    except Exception as hata:
        return f"Hesap listesi okunamadı: {hata}"
    idler = {int(h.id) for h in adaylar if getattr(h, "id", None) is not None}
    adlar = {(h.hesap_adi or "").strip() for h in adaylar}
    if finans_hesap_id is not None:
        if int(finans_hesap_id) in idler:
            return None
        return "Seçilen hesap bu ödeme/tahsilat şekline veya firmaya uygun değil."
    if hesap in adlar:
        return None
    # Eski hizmet/alış kayıtları: firma kartı etiketi veya kart_adi
    if not gelir_mi and tur == "KART":
        for k in FinansService.sirket_kredi_kartlari():
            if hesap in {
                (k.get("etiket") or "").strip(),
                (k.get("kart_adi") or "").strip(),
                (k.get("kaynak_kodu") or "").strip(),
            }:
                bagli = k.get("bagli_hesap_id")
                if bagli is not None and int(bagli) in idler:
                    return None
                if bagli is None and not adaylar:
                    return "Bu ödeme şekli için tanımlı kredi kartı hesabı yok."
                if bagli is not None and int(bagli) not in idler:
                    return "Seçilen kartın bağlı kredi kartı hesabı aktif değil veya uygun değil."
                return None
    if not adaylar:
        if tur == "KART":
            return (
                "Bu tahsilat şekli için uygun POS hesabı yok."
                if gelir_mi
                else "Bu ödeme şekli için tanımlı kredi kartı hesabı yok."
            )
        if tur == "HAVALE":
            return "Bu ödeme/tahsilat şekli için uygun mevduat/KMH hesabı yok."
        if tur == "KASA":
            return "Bu ödeme/tahsilat şekli için uygun kasa hesabı yok."
        return "Bu ödeme/tahsilat şekli için uygun hesap yok."
    return "Seçilen hesap bu ödeme/tahsilat şekline uygun değil."


class HizmetFaturasiService:
    @staticmethod
    def aktif_cariler(fatura_turu: str):
        """Gider: hizmet veren (tedarikçi/banka/personel). Gelir: hizmet alan (+ müşteri)."""
        tur = (fatura_turu or "GIDER").upper()
        kosullar = [
            Cari.cari_turu == "Tedarikçi",
            Cari.cari_turu.ilike("tedarik%"),
            Cari.cari_turu == "Banka",
            Cari.cari_turu.ilike("banka%"),
            Cari.cari_turu == "Personel",
            Cari.cari_turu.ilike("personel%"),
        ]
        if tur == "GELIR":
            kosullar.extend(
                [
                    Cari.cari_turu == "Müşteri",
                    Cari.cari_turu == "Musteri",
                    Cari.cari_turu.ilike("müster%"),
                    Cari.cari_turu.ilike("muster%"),
                ]
            )
        with get_session() as session:
            return list(
                session.scalars(
                    select(Cari)
                    .where(Cari.aktif.is_(True), or_(*kosullar))
                    .order_by(Cari.cari_kodu)
                ).all()
            )

    @staticmethod
    def fatura_no(fatura_turu: str) -> str:
        tur = (fatura_turu or "GIDER").upper()
        onek = {
            "GELIR": "HSG",
            "GELIR_IADE": "HSI",
            "GIDER": "HAG",
            "GIDER_IADE": "HAI",
        }.get(tur, "HAG")
        with get_session() as session:
            numaralar = session.scalars(
                select(HizmetFaturasi.fatura_no).where(
                    HizmetFaturasi.fatura_no.like(f"{onek}%")
                )
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek) :]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:06d}"

    @staticmethod
    def toplam(satirlar) -> dict[str, Decimal]:
        ara = iskonto = kdv = Decimal("0")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat"), "Birim fiyat")
            indirim = miktar * fiyat * decimal(get("iskonto_orani", 0), "İskonto") / Decimal("100")
            net = miktar * fiyat - indirim
            ara += miktar * fiyat
            iskonto += indirim
            kdv += net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")
        matrah = ara - iskonto
        # Kuruş: ekran/ödeme karşılaştırması float sapması üretmesin
        q = Decimal("0.01")
        return {
            "ara_toplam": ara.quantize(q),
            "iskonto": iskonto.quantize(q),
            "matrah": matrah.quantize(q),
            "kdv": kdv.quantize(q),
            "genel_toplam": (matrah + kdv).quantize(q),
        }

    @staticmethod
    def listele(fatura_turu=None) -> list[dict[str, Any]]:
        with get_session() as session:
            q = (
                select(HizmetFaturasi)
                .options(
                    selectinload(HizmetFaturasi.cari),
                    selectinload(HizmetFaturasi.satirlar),
                )
                .order_by(HizmetFaturasi.id.desc())
            )
            if fatura_turu:
                q = q.where(HizmetFaturasi.fatura_turu == str(fatura_turu).upper())
            faturalar = list(session.scalars(q).all())
            return [
                {"fatura": f, **HizmetFaturasiService.toplam(f.satirlar)}
                for f in faturalar
            ]

    @staticmethod
    def getir(fatura_id) -> HizmetFaturasi | None:
        with get_session() as session:
            return session.scalar(
                select(HizmetFaturasi)
                .options(
                    selectinload(HizmetFaturasi.cari),
                    selectinload(HizmetFaturasi.satirlar),
                )
                .where(HizmetFaturasi.id == int(fatura_id))
            )

    @staticmethod
    def _hareketleri_sil(session, fatura_no: str):
        session.execute(
            delete(HizmetHareketi).where(HizmetHareketi.belge_no == fatura_no)
        )

    @staticmethod
    def _finans_geri_al(session, fatura: HizmetFaturasi):
        if fatura.fatura_turu == "GELIR":
            FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
        else:
            FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)

    @staticmethod
    def _finans_yaz(session, fatura: HizmetFaturasi):
        if fatura.fatura_turu == "GELIR":
            FinansService.fatura_tahsilati(
                session,
                fatura.fatura_no,
                fatura.fatura_tarihi,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
                cari_id=getattr(fatura, "cari_id", None),
                sube_id=getattr(fatura, "sube_id", None),
            )
        else:
            FinansService.fatura_odemesi(
                session,
                fatura.fatura_no,
                fatura.fatura_tarihi,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
            )

    @staticmethod
    def fatura_no_var_mi(fatura_no: str) -> bool:
        no = (fatura_no or "").strip()
        if not no:
            return False
        with get_session() as session:
            return (
                session.scalar(
                    select(HizmetFaturasi.id).where(HizmetFaturasi.fatura_no == no)
                )
                is not None
            )

    @staticmethod
    def kaydet(
        veriler: dict,
        satir_verileri: list[dict],
        fatura_id=None,
        *,
        cari_etkisi: bool = True,
        finans_yaz: bool = True,
    ) -> HizmetFaturasi:
        """cari_etkisi/finans_yaz=False: EvoBulut aktarımında cari defter ayrı yazıldığında."""
        yazma_zorunlu("finans_duzenleme", "yeni_kayit")
        tarih = veriler["fatura_tarihi"]
        vade = veriler["vade_tarihi"]
        tur = (veriler.get("fatura_turu") or "GIDER").strip().upper()
        if tur not in FATURA_TURLERI:
            raise ValueError("Fatura türü GIDER, GELIR veya ilgili iade olmalıdır.")
        kart_turu = _kart_turu(tur)
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        if fatura_id:
            from database.masraf_dagitim_service import MasrafDagitimService

            MasrafDagitimService.kilit_kontrol(kaynak_id=int(fatura_id))

        with get_session() as session:
            if fatura_id:
                fatura = session.scalar(
                    select(HizmetFaturasi)
                    .options(selectinload(HizmetFaturasi.satirlar))
                    .where(HizmetFaturasi.id == int(fatura_id))
                )
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                if finans_yaz:
                    HizmetFaturasiService._finans_geri_al(session, fatura)
                HizmetFaturasiService._hareketleri_sil(session, fatura.fatura_no)
                if cari_etkisi:
                    from database.acik_kalem_service import AcikKalemService

                    AcikKalemService.belge_kalemlerini_sil(
                        session, fatura.fatura_no, fatura.cari_id, neden=f"Hizmet faturası düzeltme {fatura.fatura_no}"
                    )
                MasrafDagitimService.bagli_taslaklari_iptal(
                    session, kaynak_id=int(fatura.id),
                    neden=f"Kaynak hizmet faturası {fatura.fatura_no} düzenlendi; satırları yeniden oluşturuldu.",
                )
                fatura.satirlar.clear()
            else:
                fatura = HizmetFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip()
                    or HizmetFaturasiService.fatura_no(tur),
                    fatura_turu=tur,
                )
                session.add(fatura)

            fatura.fatura_turu = tur
            fatura.fatura_tarihi = tarih
            fatura.vade_tarihi = vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (
                (veriler.get("islem_saati") or "").strip()
                or datetime.now().strftime("%H:%M")
            )
            fatura.cari_id = int(veriler["cari_id"])
            fatura.odeme_tutari = decimal(veriler.get("odeme_tutari", 0), "Ödeme", Decimal("0"))
            fatura.odeme_sekli = veriler.get("odeme_sekli") or None
            fatura.odeme_hesabi = veriler.get("odeme_hesabi") or None
            fatura.aciklama = (veriler.get("aciklama") or "").strip() or None
            fatura.dokuman_yolu = (veriler.get("dokuman_yolu") or "").strip() or None
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
            fatura.para_birimi = pb
            fatura.kur = kur
            fatura.kur_tarihi = veriler.get("kur_tarihi")
            fatura.kur_turu = veriler.get("kur_turu") or "forex_selling"
            fatura.kur_kaynagi = veriler.get("kur_kaynagi") or "TCMB"
            fatura.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", pb != "TRY"))
            fatura.borc_esasi = veriler.get("borc_esasi") or "TL_SABIT"

            hareket_turu = {
                "GELIR": HAREKET_GELIR,
                "GIDER": HAREKET_GIDER,
                "GELIR_IADE": HAREKET_GELIR_IADE,
                "GIDER_IADE": HAREKET_GIDER_IADE,
            }[tur]
            # Gider −1, gelir +1; iade ters işaret (gider iadesi eksi gider = +1)
            isaret = {"GELIR": 1, "GIDER": -1, "GELIR_IADE": -1, "GIDER_IADE": 1}[tur]
            doviz_ara = Decimal("0")

            for veri in satir_verileri:
                kod = (veri.get("hizmet_kodu") or "").strip().upper()
                if not kod:
                    raise ValueError("Hizmet kodu zorunludur.")
                hizmet = session.scalar(
                    select(HizmetKarti).where(HizmetKarti.hizmet_kodu == kod)
                )
                if not hizmet:
                    raise ValueError(f"{kod} kodlu hizmet kartı bulunamadı.")
                if (hizmet.hizmet_turu or "").upper() != kart_turu:
                    raise ValueError(
                        f"{kod} bu fatura türü için uygun değil "
                        f"({hizmet.hizmet_turu})."
                    )
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                birim_fiyat_doviz = decimal(
                    veri.get("birim_fiyat_doviz", veri.get("birim_fiyat", 0)),
                    "Birim fiyat",
                    Decimal("0"),
                )
                if pb != "TRY" and birim_fiyat_doviz > 0:
                    birim_fiyat = DovizService.dovizden_tle(birim_fiyat_doviz, kur, Decimal("0.0001"))
                    doviz_ara += miktar * (
                        birim_fiyat_doviz
                        - birim_fiyat_doviz
                        * decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                        / Decimal("100")
                    )
                else:
                    birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                    birim_fiyat_doviz = Decimal("0")
                iskonto_orani = decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                kdv_orani = decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0"))
                net = miktar * birim_fiyat - (
                    miktar * birim_fiyat * iskonto_orani / Decimal("100")
                )

                fatura.satirlar.append(
                    HizmetFaturasiSatiri(
                        hizmet_id=hizmet.id,
                        hizmet_kodu=hizmet.hizmet_kodu,
                        hizmet_adi=(veri.get("hizmet_adi") or hizmet.hizmet_adi or "").strip(),
                        aciklama=(veri.get("aciklama") or "").strip() or None,
                        miktar=miktar,
                        birim=(veri.get("birim") or hizmet.birim or "Adet").strip() or "Adet",
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=iskonto_orani,
                        kdv_orani=kdv_orani,
                        birim_fiyat_doviz=birim_fiyat_doviz,
                        tl_birim_fiyat=birim_fiyat,
                        tl_tutar=net.quantize(Decimal("0.01")),
                        # Satışla aynı: manuel birim fiyat bayrağı. Kaynakta yok → False.
                        manuel_fiyat=bool(veri.get("manuel_fiyat") or False),
                        # Anlam: Fiyatlara Dağıt kilidi (satış/alış ile aynı). Kaynakta yok → False.
                        dagitima_kapali=bool(veri.get("dagitima_kapali") or False),
                    )
                )
                session.add(
                    HizmetHareketi(
                        hizmet_id=hizmet.id,
                        tarih=tarih,
                        hareket_turu=hareket_turu,
                        belge_no=fatura.fatura_no,
                        miktar=miktar,
                        birim_fiyat=birim_fiyat,
                        kdv_orani=kdv_orani,
                        tutar=net.quantize(Decimal("0.01")),
                        isaret=isaret,
                        cari_id=fatura.cari_id,
                        aciklama=(veri.get("aciklama") or "").strip() or None,
                    )
                )
                if kart_turu == "GIDER":
                    hizmet.alis_fiyati = birim_fiyat
                else:
                    hizmet.satis_fiyati = birim_fiyat

            toplam_dict = HizmetFaturasiService.toplam(fatura.satirlar)
            toplam = toplam_dict["genel_toplam"]
            fatura.tl_matrah = toplam_dict["ara_toplam"] - toplam_dict["iskonto"]
            fatura.tl_kdv = toplam_dict["kdv"]
            fatura.tl_genel_toplam = toplam
            fatura.doviz_ara_toplam = doviz_ara.quantize(Decimal("0.01")) if pb != "TRY" else Decimal("0")
            odeme_q = Decimal(str(fatura.odeme_tutari or 0)).quantize(Decimal("0.01"))
            toplam_q = Decimal(str(toplam or 0)).quantize(Decimal("0.01"))
            if odeme_q < 0:
                raise ValueError("Ödeme/tahsilat tutarı negatif olamaz.")
            if odeme_q > toplam_q:
                etiket = "Tahsilat" if kart_turu == "GELIR" else "Ödeme"
                raise ValueError(
                    f"{etiket} tutarı fatura kalanını aşamaz "
                    f"(girilen {odeme_q}, fatura {toplam_q})."
                )
            if odeme_q > 0:
                uyari = odeme_sekli_hesap_uygun_mu(
                    fatura.odeme_sekli,
                    fatura.odeme_hesabi,
                    gelir_mi=(kart_turu == "GELIR"),
                )
                if uyari:
                    raise ValueError(uyari)
            fatura.durum = "KAPALI" if odeme_q >= toplam_q else "AÇIK"
            session.flush()

            if cari_etkisi:
                hareket = session.scalar(
                    select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
                )
                if not hareket:
                    hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                    session.add(hareket)
                hareket.cari_id = fatura.cari_id
                hareket.satis_tarihi = tarih
                # Alış (GIDER) negatif — tedarikçi alacak; gelir pozitif — müşteri borç.
                # Yön cari sınıfından değil kaynak fatura_turu'ndan.
                satis_t, kalan_t = _sh_tutar_ve_kalan(tur, toplam_q, odeme_q)
                hareket.satis_tutari = satis_t
                hareket.kalan_acik_tutar = kalan_t
                hareket.para_birimi = pb
                hareket.kur = kur if pb != "TRY" else Decimal("1")
                hareket.borc_esasi = fatura.borc_esasi or "TL_SABIT"
                hareket.doviz_tutari = fatura.doviz_ara_toplam if pb != "TRY" else Decimal("0")
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.avanslari_uygula(session, fatura.cari_id)

            if finans_yaz:
                HizmetFaturasiService._finans_yaz(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            fid = fatura.id
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("hizmet_faturasi_fisi", fid, yeniden=True, session=session)
        return HizmetFaturasiService.getir(fid)

    @staticmethod
    def kapatan_odemeleri(fatura_id: int) -> dict:
        """Faturayı kapatan gerçek ödeme/tahsilat/mahsup kayıtları (cari_kapatmalar).

        Varsayımsal ödeme üretmez; bağlantı yoksa ``eksik_baglanti`` uyarısı döner.
        """
        from database.kapatma_izleme_service import evrak_kapatma_detayi, fatura_odeme_ozeti

        fatura = HizmetFaturasiService.getir(int(fatura_id))
        if fatura is None:
            raise ValueError("Fatura bulunamadı.")
        oz = fatura_odeme_ozeti(int(fatura_id), fatura.fatura_turu or "GIDER")
        detay = evrak_kapatma_detayi(fatura.fatura_no, int(fatura.cari_id))
        kapatanlar = list(detay.get("kapatanlar") or [])
        kayitli_pay = sum(
            (Decimal(str(k.get("pay") or 0)) for k in kapatanlar if k.get("kaynak") != "BILINMIYOR"),
            Decimal("0"),
        )
        bilinmeyen = sum(
            (Decimal(str(k.get("pay") or 0)) for k in kapatanlar if k.get("kaynak") == "BILINMIYOR"),
            Decimal("0"),
        )
        eksik = bool(
            (fatura.durum or "").upper() == "KAPALI"
            and Decimal(str(fatura.odeme_tutari or 0)) > 0
            and kayitli_pay <= 0
            and bilinmeyen <= 0
            and Decimal(str(oz.get("kapanan") or 0)) <= 0
        )
        return {
            "fatura_id": int(fatura.id),
            "fatura_no": fatura.fatura_no,
            "fatura_turu": fatura.fatura_turu,
            "cari_id": int(fatura.cari_id),
            "toplam": oz.get("toplam"),
            "kapanan": oz.get("kapanan"),
            "kalan": oz.get("kalan"),
            "odeme_durumu": oz.get("durum"),
            "satirlar": kapatanlar,
            "eksik_baglanti": eksik,
            "uyari": (
                "Kapalı görünen faturada doğrulanabilir kapatma bağlantısı yok. "
                "Yeni ödeme üretilmedi; cari kapatma / makbuz bağlantısını kontrol edin."
                if eksik
                else (detay.get("uyari") or None)
            ),
            "mesaj": detay.get("mesaj"),
        }

    @staticmethod
    def odeme_durumunu_senkronla(fatura_id: int) -> dict:
        """Kapatma kayıtlarından ödenen/kalan/durum alanlarını günceller (satırlara dokunmaz)."""
        yazma_zorunlu("finans_duzenleme", "duzenleme")
        from database.kapatma_izleme_service import evrak_kapatma_detayi_oturum

        with get_session() as session:
            fatura = session.get(HizmetFaturasi, int(fatura_id))
            if fatura is None:
                raise ValueError("Fatura bulunamadı.")
            if (fatura.durum or "") == "İPTAL":
                return {"fatura_id": int(fatura_id), "durum": "İPTAL"}
            detay = evrak_kapatma_detayi_oturum(
                session, fatura.fatura_no, int(fatura.cari_id)
            )
            # Kapananı yalnızca doğrulanabilir kapatma paylarından al (varsayımsal üretilmez)
            kapanan = sum(
                (
                    Decimal(str(k.get("pay") or 0))
                    for k in (detay.get("kapatanlar") or [])
                    if k.get("kaynak") != "BILINMIYOR"
                ),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
            toplam = Decimal(str(detay.get("esas_tutar") or 0)).quantize(Decimal("0.01"))
            if toplam <= 0:
                t = HizmetFaturasiService.toplam(list(fatura.satirlar or []))
                toplam = Decimal(str(t["genel_toplam"])).quantize(Decimal("0.01"))
            kalan = max(Decimal("0"), (toplam - kapanan).quantize(Decimal("0.01")))
            fatura.odeme_tutari = kapanan
            fatura.durum = "KAPALI" if kapanan + Decimal("0.01") >= toplam else "AÇIK"
            # SH kalanını da senkron tut
            hareket = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == fatura.fatura_no,
                    SatisHareketi.cari_id == int(fatura.cari_id),
                )
            )
            if hareket is not None and Decimal(str(hareket.satis_tutari or 0)) != 0:
                satis_t, kalan_t = _sh_tutar_ve_kalan(
                    fatura.fatura_turu or "GIDER", toplam, kapanan
                )
                hareket.satis_tutari = satis_t
                hareket.kalan_acik_tutar = kalan_t
            session.flush()
            return {
                "fatura_id": int(fatura.id),
                "odeme_tutari": fatura.odeme_tutari,
                "durum": fatura.durum,
                "kalan": kalan,
                "kapanan": kapanan,
            }

    @staticmethod
    def iptal_et(fatura_id):
        yazma_zorunlu("finans_duzenleme", "iptal")
        from database.masraf_dagitim_service import MasrafDagitimService

        MasrafDagitimService.kilit_kontrol(kaynak_id=int(fatura_id))
        with get_session() as session:
            fatura = session.scalar(
                select(HizmetFaturasi)
                .options(selectinload(HizmetFaturasi.satirlar))
                .where(HizmetFaturasi.id == int(fatura_id))
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                return
            HizmetFaturasiService._finans_geri_al(session, fatura)
            HizmetFaturasiService._hareketleri_sil(session, fatura.fatura_no)
            from database.acik_kalem_service import AcikKalemService

            AcikKalemService.belge_kalemlerini_sil(
                session, fatura.fatura_no, fatura.cari_id, neden=f"Hizmet faturası iptal {fatura.fatura_no}"
            )
            MasrafDagitimService.bagli_taslaklari_iptal(
                session, kaynak_id=int(fatura.id), neden=f"Kaynak hizmet faturası {fatura.fatura_no} iptal edildi."
            )
            fatura.durum = "İPTAL"
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("iptal_kaynak", "hizmet_faturasi", int(fatura_id), "Hizmet fatura iptal",
                          session=session)

        MasrafDagitimService.sahipsiz_taslaklari_kapat()
        from database.deleted_record_service import ENTITY_HIZMET_FATURA, safe_log_cancel

        safe_log_cancel(ENTITY_HIZMET_FATURA, fatura_id, note="Hizmet faturası iptal")
