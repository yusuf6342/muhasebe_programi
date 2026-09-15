from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, joinedload

from database.database import get_session
from database.access import yazma_zorunlu, yetki_zorunlu
from database.models.cari import Cari, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri, SatisFaturasiTahsilati
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from database.doviz_service import DovizService
from database.finans_service import FinansService

FATURA_DURUMLARI = ("TASLAK", "AÇIK", "KAPALI", "İPTAL")
TAHSILAT_SEKILLERI = ("NAKİT / KASA", "GELEN HAVALE", "KREDİ KARTIYLA TAHSİLAT")


class SatisFaturasiService:
    @staticmethod
    def _doviz_alanlarini_yaz(fatura, veriler: dict, toplam: dict) -> None:
        pb = (veriler.get("para_birimi") or "TRY").upper()
        fatura.para_birimi = pb
        fatura.kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
        fatura.kur_tarihi = veriler.get("kur_tarihi")
        fatura.kur_turu = veriler.get("kur_turu") or "forex_selling"
        fatura.kur_kaynagi = veriler.get("kur_kaynagi") or "TCMB"
        fatura.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", pb != "TRY"))
        fatura.borc_esasi = veriler.get("borc_esasi") or "TL_SABIT"
        fatura.doviz_ara_toplam = decimal(veriler.get("doviz_ara_toplam", 0), "Döviz ara toplam", Decimal("0"))
        fatura.tl_matrah = toplam["ara_toplam"] - toplam["iskonto"]
        fatura.tl_kdv = toplam["kdv"]
        fatura.tl_genel_toplam = toplam["genel_toplam"]

    @staticmethod
    def _satir_doviz_alanlari(veri: dict, kur: Decimal, para_birimi: str) -> dict:
        pb = (para_birimi or "TRY").upper()
        miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
        bf_doviz = decimal(veri.get("birim_fiyat_doviz", veri.get("birim_fiyat", 0)), "Birim fiyat", Decimal("0"))
        bf_tl = decimal(veri.get("birim_fiyat", veri.get("birim_satis_fiyati", 0)), "TL birim fiyat", Decimal("0"))
        if pb != "TRY" and bf_doviz > 0:
            bf_tl = DovizService.dovizden_tle(bf_doviz, kur, Decimal("0.0001"))
        _, _, net = SatisFaturasiService._satir_net(
            miktar,
            bf_tl,
            veri.get("iskonto_orani", 0),
            veri.get("iskonto_orani_2", 0),
            veri.get("iskonto_orani_3", 0),
        )
        return {
            "birim_fiyat_doviz": bf_doviz if pb != "TRY" else Decimal("0"),
            "tl_birim_fiyat": bf_tl,
            "tl_tutar": net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }

    @staticmethod
    def aktif_musterileri():
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        """Tam fatura + satır yükler (ağır). Liste ekranı için listele_ozet() kullanın."""
        with get_session() as session:
            faturalar = session.scalars(select(SatisFaturasi).options(
                selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.satirlar),
                selectinload(SatisFaturasi.siparis), selectinload(SatisFaturasi.irsaliye)
            ).where(
                or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None))
            ).order_by(SatisFaturasi.id.desc())).all()
            return [{"fatura": f, **SatisFaturasiService.toplam(f.satirlar)} for f in faturalar]

    @staticmethod
    def listele_ozet(tarih_bas=None, tarih_bit=None) -> list[dict[str, Any]]:
        """Liste ekranı için hızlı özet — satırları yüklemez, tl_genel_toplam kullanır.

        tarih_bas / tarih_bit: fatura_tarihi SQL filtresi (dahil).
        """
        with get_session() as session:
            statement = (
                select(SatisFaturasi)
                .options(
                    joinedload(SatisFaturasi.cari).load_only(Cari.id, Cari.unvan),
                    joinedload(SatisFaturasi.siparis).load_only(
                        SatisSiparisi.id, SatisSiparisi.siparis_no
                    ),
                    joinedload(SatisFaturasi.irsaliye).load_only(
                        SatisIrsaliyesi.id, SatisIrsaliyesi.irsaliye_no
                    ),
                )
                .where(
                    or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None))
                )
                .order_by(SatisFaturasi.id.desc())
            )
            if tarih_bas is not None:
                statement = statement.where(SatisFaturasi.fatura_tarihi >= tarih_bas)
            if tarih_bit is not None:
                statement = statement.where(SatisFaturasi.fatura_tarihi <= tarih_bit)
            faturalar = list(session.scalars(statement).unique().all())
            # Eski kayıtlarda tl_genel_toplam boşsa yalnızca onlar için satır çek
            eksik_idler = [
                f.id
                for f in faturalar
                if Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0)) <= 0
            ]
            toplam_map: dict[int, Decimal] = {}
            if eksik_idler:
                satirlar = session.scalars(
                    select(SatisFaturasiSatiri).where(
                        SatisFaturasiSatiri.fatura_id.in_(eksik_idler)
                    )
                ).all()
                by_fid: dict[int, list] = {}
                for satir in satirlar:
                    by_fid.setdefault(satir.fatura_id, []).append(satir)
                for fid, sliste in by_fid.items():
                    genel = SatisFaturasiService.toplam(sliste)["genel_toplam"]
                    toplam_map[fid] = genel
                # Sonraki açılışlar için kalıcı doldur
                for f in faturalar:
                    if f.id in toplam_map:
                        f.tl_genel_toplam = toplam_map[f.id]
                        f.tl_matrah = f.tl_matrah or Decimal("0")
                        f.tl_kdv = f.tl_kdv or Decimal("0")
                try:
                    session.flush()
                except Exception:
                    pass

            sonuc = []
            for f in faturalar:
                genel = Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0))
                if genel <= 0:
                    genel = toplam_map.get(f.id, Decimal("0"))
                tahsilat = Decimal(str(f.tahsilat_tutari or 0))
                sonuc.append({
                    "id": f.id,
                    "fatura_no": f.fatura_no or "",
                    "fatura_tarihi": f.fatura_tarihi,
                    "islem_saati": f.islem_saati or "",
                    "vade_tarihi": f.vade_tarihi,
                    "musteri": f.cari.unvan if f.cari else "",
                    "siparis_no": f.siparis.siparis_no if f.siparis else "",
                    "irsaliye_no": f.irsaliye.irsaliye_no if f.irsaliye else "",
                    "depo": f.depo or "",
                    "genel_toplam": genel,
                    "tahsilat_tutari": tahsilat,
                    "durum": f.durum or "",
                    "onaylandi": bool(getattr(f, "onaylandi", False)),
                })
            return sonuc

    @staticmethod
    def getir(fatura_id):
        with get_session() as session:
            return session.scalar(select(SatisFaturasi).options(
                selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.siparis),
                selectinload(SatisFaturasi.irsaliye), selectinload(SatisFaturasi.satirlar),
                selectinload(SatisFaturasi.tahsilatlar),
            ).where(SatisFaturasi.id == fatura_id))

    @staticmethod
    def acik_siparisler(cari_id=None):
        with get_session() as session:
            statement = (
                select(SatisSiparisi)
                .where(
                    SatisSiparisi.durum.notin_(("İPTAL", "FATURALI")),
                )
                .options(
                    selectinload(SatisSiparisi.cari),
                    selectinload(SatisSiparisi.satirlar),
                )
                .order_by(SatisSiparisi.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisSiparisi.cari_id == int(cari_id))
            siparisler = list(session.scalars(statement).all())
            # Faturalanacak kalan miktarı olanlar
            return [
                s
                for s in siparisler
                if any(
                    (satir.miktar or 0) - (satir.faturalanan_miktar or 0) > 0
                    for satir in (s.satirlar or [])
                )
            ]

    @staticmethod
    def acik_irsaliyeler(cari_id=None, siparis_id=None):
        with get_session() as session:
            statement = (
                select(SatisIrsaliyesi)
                .where(SatisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI")))
                .options(
                    selectinload(SatisIrsaliyesi.cari),
                    selectinload(SatisIrsaliyesi.siparis),
                    selectinload(SatisIrsaliyesi.satirlar),
                )
                .order_by(SatisIrsaliyesi.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisIrsaliyesi.cari_id == int(cari_id))
            if siparis_id is not None:
                statement = statement.where(SatisIrsaliyesi.siparis_id == int(siparis_id))
            return list(session.scalars(statement).all())

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None, tahsilat_verileri=None):
        """Faturayı taslak kaydeder: stok / cari / finans hareketi oluşturmaz.

        Hareketler yalnızca onayla() ile üretilir. Onaylı fatura düzenlenemez;
        önce onay_kaldir() çağrılmalıdır.
        """
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        tahsilat_verileri = list(tahsilat_verileri or [])
        with get_session() as session:
            if fatura_id:
                fatura = session.get(SatisFaturasi, fatura_id)
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                if getattr(fatura, "onaylandi", False):
                    raise ValueError("Düzenlemek için önce Onay Kaldır yapın.")
                SatisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                fatura.satirlar.clear()
                fatura.tahsilatlar.clear()
            else:
                fatura = SatisFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip()
                    or SatisFaturasiService.fatura_no()
                )
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (veriler.get("islem_saati") or "").strip() or datetime.now().strftime("%H:%M")
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            adres_no = veriler.get("adres_no")
            try:
                fatura.adres_no = int(adres_no) if adres_no not in (None, "") else None
            except (TypeError, ValueError):
                fatura.adres_no = None
            fatura.adres_tipi = (veriler.get("adres_tipi") or "").strip() or None
            fatura.adres_metni = (veriler.get("adres_metni") or "").strip() or None
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                doviz_satir = SatisFaturasiService._satir_doviz_alanlari(veri, kur, pb)
                if pb != "TRY":
                    veri = dict(veri)
                    veri["birim_fiyat"] = doviz_satir["tl_birim_fiyat"]
                irs_id, sip_id = veri.get("irsaliye_satiri_id"), veri.get("siparis_satiri_id")
                if irs_id:
                    kaynak = session.get(SatisIrsaliyesiSatiri, int(irs_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı irsaliyenin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            if miktar > siparis_satiri.miktar - siparis_satiri.faturalanan_miktar:
                                raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                            siparis_satiri.faturalanan_miktar += miktar
                            siparis_satiri.fatura_belge_baglantisi = fatura.fatura_no
                        sip_id = kaynak.siparis_satiri_id
                elif sip_id:
                    kaynak = session.get(SatisSiparisiSatiri, int(sip_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no
                fatura.satirlar.append(
                    SatisFaturasiSatiri(
                        siparis_satiri_id=sip_id,
                        irsaliye_satiri_id=irs_id,
                        urun_kodu=veri["urun_kodu"].strip(),
                        urun_adi=veri["urun_adi"].strip(),
                        barkod=veri.get("barkod") or None,
                        aciklama=veri.get("aciklama") or None,
                        lot_no=veri.get("lot_no") or None,
                        lot_cikisi=veri.get("lot_cikisi") or None,
                        miktar=miktar,
                        birim=veri.get("birim") or "Adet",
                        birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                        iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto 1", Decimal("0")),
                        iskonto_orani_2=decimal(veri.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0")),
                        iskonto_orani_3=decimal(veri.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0")),
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        fifo_birim_maliyeti=decimal(
                            veri.get("fifo_birim_maliyeti", 0), "FIFO maliyet", Decimal("0")
                        ),
                        son_alis_birim_maliyeti=decimal(
                            veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")
                        ),
                        ortalama_birim_maliyeti=decimal(
                            veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyet", Decimal("0")
                        ),
                        agirlikli_ortalama_birim_maliyeti=decimal(
                            veri.get("agirlikli_ortalama_birim_maliyeti", 0),
                            "Ağırlıklı maliyet",
                            Decimal("0"),
                        ),
                        birim_fiyat_doviz=doviz_satir["birim_fiyat_doviz"],
                        tl_birim_fiyat=doviz_satir["tl_birim_fiyat"],
                        tl_tutar=doviz_satir["tl_tutar"],
                    )
                )

            tahsilat_toplam = Decimal("0")
            for veri in tahsilat_verileri:
                tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
                odeme_sekli = (veri.get("odeme_sekli") or "").strip()
                hesap = (veri.get("hesap") or "").strip()
                if not odeme_sekli:
                    raise ValueError("Tahsilat ödeme şekli zorunludur.")
                if not hesap:
                    raise ValueError("Tahsilat hesabı zorunludur.")
                tahsilat_tarihi = veri.get("tahsilat_tarihi") or tarih
                if not hasattr(tahsilat_tarihi, "strftime"):
                    tahsilat_tarihi = tarih
                tahsilat_toplam += tutar
                fatura.tahsilatlar.append(
                    SatisFaturasiTahsilati(
                        tahsilat_tarihi=tahsilat_tarihi,
                        tutar=tutar,
                        odeme_sekli=odeme_sekli,
                        hesap=hesap,
                        aciklama=(veri.get("aciklama") or None),
                    )
                )

            if not tahsilat_verileri and veriler.get("tahsilat_tutari") is not None:
                tahsilat_toplam = decimal(veriler.get("tahsilat_tutari", 0), "Tahsilat", Decimal("0"))
                if tahsilat_toplam > 0:
                    sekil = (veriler.get("tahsilat_sekli") or TAHSILAT_SEKILLERI[0]).strip()
                    hesap = (veriler.get("tahsilat_hesabi") or "").strip()
                    if not hesap:
                        raise ValueError("Tahsilat hesabı zorunludur.")
                    fatura.tahsilatlar.append(
                        SatisFaturasiTahsilati(
                            tahsilat_tarihi=tarih,
                            tutar=tahsilat_toplam,
                            odeme_sekli=sekil,
                            hesap=hesap,
                            aciklama="Fatura tahsilatı",
                        )
                    )

            toplam_dict = SatisFaturasiService.toplam(fatura.satirlar)
            toplam = toplam_dict["genel_toplam"]
            SatisFaturasiService._doviz_alanlarini_yaz(fatura, veriler, toplam_dict)
            if pb != "TRY" and fatura.doviz_ara_toplam <= 0:
                doviz_ara = Decimal("0")
                for satir in fatura.satirlar:
                    if satir.birim_fiyat_doviz > 0:
                        brut, _, _ = SatisFaturasiService._satir_net(
                            satir.miktar,
                            satir.birim_fiyat_doviz,
                            satir.iskonto_orani,
                            satir.iskonto_orani_2,
                            satir.iskonto_orani_3,
                        )
                        doviz_ara += brut
                fatura.doviz_ara_toplam = doviz_ara.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if tahsilat_toplam > toplam:
                raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")
            fatura.tahsilat_tutari = tahsilat_toplam
            ilk = fatura.tahsilatlar[0] if fatura.tahsilatlar else None
            fatura.tahsilat_sekli = ilk.odeme_sekli if ilk else None
            fatura.tahsilat_hesabi = ilk.hesap if ilk else None
            fatura.onaylandi = False
            fatura.durum = "TASLAK"
            session.flush()
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            return fatura

    @staticmethod
    def onayla(fatura_id):
        """Taslak faturayı onaylar: stok çıkışı, cari borç ve finans tahsilatı oluşturur."""
        yazma_zorunlu("satis_duzenleme")
        with get_session() as session:
            fatura = session.scalar(
                select(SatisFaturasi)
                .where(SatisFaturasi.id == int(fatura_id))
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                raise ValueError("İptal edilmiş fatura onaylanamaz.")
            if getattr(fatura, "onaylandi", False):
                raise ValueError("Bu fatura zaten onaylanmış.")
            if not fatura.satirlar:
                raise ValueError("Onay için en az bir fatura satırı gerekli.")

            tarih = fatura.fatura_tarihi
            if tarih > date.today():
                raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")

            for satir in fatura.satirlar:
                try:
                    stok_cikisi = StokService.fatura_cikisi(
                        session,
                        fatura.fatura_no,
                        tarih,
                        satir.urun_kodu.strip(),
                        fatura.depo,
                        satir.miktar,
                        satir.lot_no or "",
                    )
                except ValueError as hata:
                    mesaj = str(hata)
                    if "stok yetersiz" in mesaj.casefold() or "yetersiz" in mesaj.casefold():
                        raise ValueError(
                            f"Fatura onaylanamadı — eksi stoka izin yok.\n{mesaj}"
                        ) from hata
                    raise ValueError(f"Fatura onaylanamadı.\n{mesaj}") from hata
                satir.lot_cikisi = stok_cikisi["lot_cikisi"]
                satir.fifo_birim_maliyeti = stok_cikisi["fifo_birim_maliyeti"]

            toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            tahsilat_toplam = Decimal(str(fatura.tahsilat_tutari or 0))
            if tahsilat_toplam > toplam:
                raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")

            hareket = session.scalar(
                select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
            )
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id = fatura.cari_id
            hareket.satis_tarihi = tarih
            hareket.satis_tutari = toplam
            hareket.kalan_acik_tutar = toplam - tahsilat_toplam
            hareket.para_birimi = getattr(fatura, "para_birimi", "TRY") or "TRY"
            hareket.kur = Decimal(str(getattr(fatura, "kur", 1) or 1))
            hareket.borc_esasi = getattr(fatura, "borc_esasi", "TL_SABIT") or "TL_SABIT"
            if hareket.borc_esasi == "DOVIZ_SABIT" and hareket.para_birimi != "TRY":
                hareket.doviz_tutari = Decimal(str(getattr(fatura, "doviz_ara_toplam", 0) or 0))
            else:
                hareket.doviz_tutari = Decimal("0")

            for th in fatura.tahsilatlar:
                if Decimal(str(th.tutar or 0)) <= 0:
                    continue
                if (
                    getattr(fatura, "borc_esasi", "TL_SABIT") == "DOVIZ_SABIT"
                    and getattr(fatura, "para_birimi", "TRY") != "TRY"
                ):
                    try:
                        odeme_kuru = DovizService.kur_degeri(
                            th.tahsilat_tarihi,
                            fatura.para_birimi,
                            getattr(fatura, "kur_turu", "forex_selling"),
                        )
                        th.odeme_kuru = odeme_kuru
                        kalan_doviz = Decimal(str(getattr(fatura, "doviz_ara_toplam", 0) or 0))
                        th.kur_farki = DovizService.kur_farki_hesapla(
                            kalan_doviz,
                            Decimal(str(getattr(fatura, "kur", 1) or 1)),
                            odeme_kuru,
                        )
                        DovizService.kur_farki_fisi_olustur(
                            session,
                            cari_id=fatura.cari_id,
                            fatura_no=fatura.fatura_no,
                            tarih=th.tahsilat_tarihi,
                            kur_farki=th.kur_farki,
                            para_birimi=fatura.para_birimi,
                            fatura_kuru=Decimal(str(getattr(fatura, "kur", 1) or 1)),
                            odeme_kuru=odeme_kuru,
                            sira=int(getattr(th, "id", 0) or 0) or (list(fatura.tahsilatlar).index(th) + 1),
                            finans_hesap_adi=th.hesap,
                        )
                    except ValueError:
                        th.odeme_kuru = Decimal("0")
                        th.kur_farki = Decimal("0")
                FinansService.fatura_tahsilati(
                    session,
                    fatura.fatura_no,
                    th.tahsilat_tarihi,
                    th.tutar,
                    th.odeme_sekli,
                    th.hesap,
                )

            fatura.durum = "KAPALI" if tahsilat_toplam >= toplam else "AÇIK"
            fatura.onaylandi = True
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura onaylanamadı.") from hata
            fid = int(fatura.id)

        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("satis_faturasi_fisi", fid)
        return SatisFaturasiService.getir(fid)

    @staticmethod
    def onay_kaldir(fatura_id):
        """Onayı kaldırır: stok/finans/cari hareketlerini geri alır; satırları silmez."""
        yazma_zorunlu("satis_duzenleme", "iptal")
        with get_session() as session:
            fatura = session.scalar(
                select(SatisFaturasi)
                .where(SatisFaturasi.id == int(fatura_id))
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.tahsilatlar),
                )
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                raise ValueError("İptal edilmiş faturanın onayı kaldırılamaz.")
            if not getattr(fatura, "onaylandi", False):
                raise ValueError("Bu fatura zaten onaysız (taslak).")

            StokService.fatura_cikislarini_geri_al(session, fatura.fatura_no)
            FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
            from database.doviz_service import DovizService

            DovizService.kur_farki_fislerini_sil(session, fatura.fatura_no)
            session.execute(
                delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
            )
            fatura.onaylandi = False
            fatura.durum = "TASLAK"
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Onay kaldırılamadı.") from hata
            fid = int(fatura.id)

        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("satis_faturasi_iptal", fid)
        return SatisFaturasiService.getir(fid)

    @staticmethod
    def iptal_et(fatura_id):
        yazma_zorunlu("satis_duzenleme", "iptal")
        onayliydi = False
        with get_session() as session:
            fatura = session.scalar(
                select(SatisFaturasi)
                .options(selectinload(SatisFaturasi.satirlar))
                .where(SatisFaturasi.id == fatura_id)
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if getattr(fatura, "is_deleted", False):
                raise ValueError("Fatura zaten silinmiş.")
            if fatura.durum != "İPTAL":
                onayliydi = bool(getattr(fatura, "onaylandi", False))
                SatisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                if onayliydi:
                    StokService.fatura_cikislarini_geri_al(session, fatura.fatura_no)
                    FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
                    session.execute(
                        delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
                    )
                fatura.onaylandi = False
                fatura.durum = "İPTAL"
                SatisFaturasiService._durumlari_guncelle(session, fatura)
                fid = int(fatura.id)
            else:
                return

        if onayliydi:
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("satis_faturasi_iptal", fid)
        from database.deleted_record_service import ENTITY_SATIS_FATURA, safe_log_cancel

        safe_log_cancel(ENTITY_SATIS_FATURA, fatura_id, note="Satış faturası iptal")

    @staticmethod
    def taslak_sil(fatura_id, *, reason: str, note: str | None = None, critical_confirm: str | None = None):
        """Yalnızca TASLAK faturaları soft-delete + silme günlüğü."""
        from database.deleted_record_service import AuditDeleteService, ENTITY_SATIS_FATURA

        return AuditDeleteService.delete_record(
            ENTITY_SATIS_FATURA,
            fatura_id,
            reason=reason,
            note=note,
            deletion_type="soft",
            critical_confirm=critical_confirm,
        )

    @staticmethod
    def _baglantilari_geri_al(session, satirlar):
        for satir in satirlar:
            if satir.irsaliye_satiri_id:
                kaynak = session.get(SatisIrsaliyesiSatiri, satir.irsaliye_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.faturalanan_miktar = max(
                                Decimal("0"), siparis_satiri.faturalanan_miktar - satir.miktar
                            )
            elif satir.siparis_satiri_id:
                kaynak = session.get(SatisSiparisiSatiri, satir.siparis_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)

    @staticmethod
    def _durumlari_guncelle(session, fatura):
        from database.satis_siparisi_service import SatisSiparisiService

        siparis_id = fatura.siparis_id
        if fatura.irsaliye_id:
            belge = session.scalar(select(SatisIrsaliyesi).options(selectinload(SatisIrsaliyesi.satirlar)).where(SatisIrsaliyesi.id == fatura.irsaliye_id))
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = (
                    "FATURALANDI" if kalan and all(x <= 0 for x in kalan)
                    else "KISMİ FATURALANDI" if any(s.faturalanan_miktar > 0 for s in belge.satirlar)
                    else "AÇIK"
                )
                if not siparis_id:
                    siparis_id = belge.siparis_id
        SatisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def _satir_net(miktar, fiyat, iskonto1=0, iskonto2=0, iskonto3=0):
        """Üç kademeli (ardışık) iskonto ile net tutar."""
        brut = miktar * fiyat
        net = brut
        for sira, oran in enumerate((iskonto1, iskonto2, iskonto3), start=1):
            o = decimal(oran or 0, f"İskonto {sira}", Decimal("0"))
            if o < 0 or o > 100:
                raise ValueError(f"İskonto {sira} 0-100 arasında olmalıdır.")
            net = net * (Decimal("1") - o / Decimal("100"))
        return brut, brut - net, net

    @staticmethod
    def urun_satis_hareketleri(urun_kodu: str, cari_id: int | None = None) -> list[dict[str, Any]]:
        """Ürün satış fatura satırları (yeniden eskiye). cari_id verilirse yalnızca o müşteri."""
        urun_kodu = (urun_kodu or "").strip()
        if not urun_kodu:
            return []
        with get_session() as session:
            statement = (
                select(SatisFaturasiSatiri)
                .join(SatisFaturasi)
                .where(
                    SatisFaturasi.durum != "İPTAL",
                    SatisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(
                    selectinload(SatisFaturasiSatiri.fatura).selectinload(SatisFaturasi.cari),
                )
                .order_by(SatisFaturasi.fatura_tarihi.desc(), SatisFaturasiSatiri.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisFaturasi.cari_id == int(cari_id))
            kayitlar = []
            for satir in session.scalars(statement).all():
                miktar = Decimal(str(satir.miktar or 0))
                fiyat = Decimal(str(satir.birim_fiyat or 0))
                _, _, net_toplam = SatisFaturasiService._satir_net(
                    miktar,
                    fiyat,
                    satir.iskonto_orani,
                    getattr(satir, "iskonto_orani_2", 0) or 0,
                    getattr(satir, "iskonto_orani_3", 0) or 0,
                )
                net_birim = (net_toplam / miktar) if miktar else Decimal("0")
                cari = satir.fatura.cari if satir.fatura else None
                kayitlar.append({
                    "tarih": satir.fatura.fatura_tarihi if satir.fatura else None,
                    "belge_no": satir.fatura.fatura_no if satir.fatura else "",
                    "musteri": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                    "miktar": miktar,
                    "birim": satir.birim or "",
                    "net_fiyat": net_birim,
                })
            return kayitlar

    @staticmethod
    def toplam(satirlar):
        ara = iskonto = kdv = Decimal("0")
        kurus = Decimal("0.01")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat", get("birim_satis_fiyati", 0)), "Birim fiyat")
            brut, indirim, net = SatisFaturasiService._satir_net(
                miktar,
                fiyat,
                get("iskonto_orani", 0),
                get("iskonto_orani_2", 0),
                get("iskonto_orani_3", 0),
            )
            net = net.quantize(kurus, rounding=ROUND_HALF_UP)
            satir_kdv = (net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")).quantize(
                kurus, rounding=ROUND_HALF_UP
            )
            ara += brut.quantize(kurus, rounding=ROUND_HALF_UP)
            iskonto += indirim.quantize(kurus, rounding=ROUND_HALF_UP)
            kdv += satir_kdv
        ara = ara.quantize(kurus, rounding=ROUND_HALF_UP)
        iskonto = iskonto.quantize(kurus, rounding=ROUND_HALF_UP)
        kdv = kdv.quantize(kurus, rounding=ROUND_HALF_UP)
        genel = (ara - iskonto + kdv).quantize(kurus, rounding=ROUND_HALF_UP)
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": genel}

    @staticmethod
    def bakiye_ozeti(cari_id, eklenecek=Decimal("0"), vade=None, haric_fatura_no=None):
        """Cari açık bakiyesi + isteğe bağlı bu fatura açığı.

        haric_fatura_no verilirse o fatura bakiyeden düşülür (düzenleme ekranı için).
        eklenecek: bu faturanın (yeniden hesaplanan) açık tutarı → yeni bakiye.
        """
        eklenecek = Decimal(str(eklenecek or 0))
        with get_session() as session:
            hs = session.scalars(
                select(SatisHareketi).where(
                    SatisHareketi.cari_id == int(cari_id),
                    SatisHareketi.kalan_acik_tutar != 0,
                )
            ).all()
            faturalar = session.scalars(
                select(SatisFaturasi)
                .where(
                    SatisFaturasi.cari_id == int(cari_id),
                    SatisFaturasi.durum != "İPTAL",
                )
                .options(selectinload(SatisFaturasi.satirlar))
            ).all()
            fatura_nolari = {f.fatura_no for f in faturalar}
            bakiye = Decimal("0")
            agirlik = Decimal("0")
            agirlik_pay = Decimal("0")
            for fatura in faturalar:
                if fatura.fatura_no == haric_fatura_no:
                    continue
                # Taslak / onaysız faturalar cari bakiyeye yansımaz
                if not getattr(fatura, "onaylandi", False) or fatura.durum in ("TASLAK", "İPTAL"):
                    continue
                acik = (
                    SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
                    - Decimal(str(fatura.tahsilat_tutari or 0))
                )
                bakiye += acik
                if acik > 0:
                    agirlik += Decimal(fatura.vade_tarihi.toordinal()) * acik
                    agirlik_pay += acik
            for h in hs:
                if h.belge_no in fatura_nolari or h.belge_no == haric_fatura_no:
                    continue
                kalan = Decimal(str(h.kalan_acik_tutar or 0))
                bakiye += kalan
                if kalan > 0:
                    tarih = h.satis_tarihi or date.today()
                    agirlik += Decimal(tarih.toordinal()) * kalan
                    agirlik_pay += kalan
            bakiye += eklenecek
            if eklenecek > 0:
                agirlik += Decimal((vade or date.today()).toordinal()) * eklenecek
                agirlik_pay += eklenecek
            ortalama = None
            if agirlik_pay > 0:
                ortalama = date.fromordinal(int(agirlik / agirlik_pay))
            return {"bakiye": bakiye, "ortalama_vade": ortalama}

    @staticmethod
    def otomatik_lot_no(firma_adi, tarih=None):
        onek = "".join(c for c in (firma_adi or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{(tarih or date.today()):%Y%m%d}"

    @staticmethod
    def fatura_no():
        """SF-00001 formatında artan satış fatura numarası."""
        onek = "SF-"
        with get_session() as session:
            numaralar = session.scalars(
                select(SatisFaturasi.fatura_no).where(SatisFaturasi.fatura_no.like(f"{onek}%"))
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek):]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:05d}"
