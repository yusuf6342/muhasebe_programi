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
    def _miktar_metin(deger: Decimal) -> str:
        d = Decimal(str(deger or 0))
        if d == d.to_integral_value():
            return str(int(d))
        return f"{d:f}".rstrip("0").rstrip(".")

    @staticmethod
    def _onay_oncesi_stok_yeterlilik(session, fatura) -> None:
        """Onay öncesi depo stokunu ürün bazında toplu kontrol et (çıkış yok)."""
        from sqlalchemy import func

        from database.models.stok import Depo, StokKarti, StokLotu
        from fatura_satir_birim_service import temel_miktar

        depo_adi = (fatura.depo or "").strip()
        if not depo_adi:
            raise ValueError("Fatura onaylanamadı. Depo seçilmemiş.")

        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not depo:
            raise ValueError(f"Fatura onaylanamadı. {depo_adi} deposu bulunamadı.")

        # urun_kodu -> {talep, ad}
        talepler: dict[str, dict[str, Any]] = {}
        for satir in fatura.satirlar:
            skip_stok = False
            if fatura.irsaliye_id and getattr(satir, "irsaliye_satiri_id", None):
                from database.models.satis_irsaliyesi import SatisIrsaliyesi
                from database.satis_irsaliyesi_service import stok_cikis_gerekli

                ir = session.get(SatisIrsaliyesi, fatura.irsaliye_id)
                if ir is not None and not stok_cikis_gerekli(ir):
                    skip_stok = True
            if skip_stok:
                continue
            kod = (satir.urun_kodu or "").strip()
            if not kod:
                continue
            tm = temel_miktar(
                satir.miktar,
                getattr(satir, "birim", None) or "Adet",
                kod,
            )
            if kod not in talepler:
                talepler[kod] = {
                    "talep": Decimal("0"),
                    "ad": (satir.urun_adi or kod).strip() or kod,
                }
            talepler[kod]["talep"] += Decimal(str(tm))

        if not talepler:
            return

        hatalar: list[str] = []
        for kod, bil in sorted(talepler.items(), key=lambda x: x[1]["ad"].casefold()):
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            if not stok:
                hatalar.append(
                    f"{bil['ad']}\n"
                    f"Stok kartı bulunamadı ({kod})."
                )
                continue
            birim = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
            mevcut = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                    StokLotu.stok_id == stok.id,
                    StokLotu.depo_id == depo.id,
                    StokLotu.kalan_miktar > 0,
                )
            )
            mevcut = Decimal(str(mevcut or 0))
            talep = bil["talep"]
            if mevcut < talep:
                eksik = talep - mevcut
                hatalar.append(
                    f"{bil['ad']}\n"
                    f"Mevcut: {SatisFaturasiService._miktar_metin(mevcut)} {birim}\n"
                    f"Faturadaki toplam miktar: {SatisFaturasiService._miktar_metin(talep)} {birim}\n"
                    f"Eksik: {SatisFaturasiService._miktar_metin(eksik)} {birim}"
                )
        if hatalar:
            raise ValueError(
                "Fatura onaylanamadı. Aşağıdaki ürünlerde stok yetersiz:\n\n"
                + "\n\n".join(hatalar)
            )

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
        # Satır toplamı = muhasebe Net (dağıtım sonrası fiyatlar satırlarda)
        from database.fatura_genel_toplam_service import islem_turunu_normalize, netten_islem, kurus

        satir_net = kurus(toplam["genel_toplam"])
        brut_iz = (
            decimal(veriler.get("tl_brut_toplam"), "Brüt toplam", Decimal("0"))
            if veriler.get("tl_brut_toplam") is not None
            else satir_net
        )
        hedef_net = (
            decimal(veriler.get("tl_genel_toplam"), "Net toplam", Decimal("0"))
            if veriler.get("tl_genel_toplam") is not None
            else satir_net
        )
        # Dağıtım yapılmışsa satır toplamı Net'tir; brüt/işlem hesap izi
        if abs(kurus(brut_iz) - satir_net) > Decimal("0.009"):
            try:
                iz = netten_islem(brut_iz, satir_net)
            except ValueError:
                iz = {
                    "brut_toplam": brut_iz,
                    "islem_turu": islem_turunu_normalize(veriler.get("genel_islem_turu")),
                    "islem_orani": decimal(veriler.get("genel_islem_orani", 0), "oran", Decimal("0")),
                    "islem_tutari": decimal(veriler.get("genel_islem_tutari", 0), "tutar", Decimal("0")),
                    "net_toplam": satir_net,
                }
            fatura.tl_brut_toplam = iz["brut_toplam"]
            fatura.genel_islem_turu = iz["islem_turu"] or None
            fatura.genel_islem_orani = iz["islem_orani"]
            fatura.genel_islem_tutari = iz["islem_tutari"]
            fatura.tl_genel_toplam = satir_net
        else:
            fatura.tl_brut_toplam = satir_net
            fatura.genel_islem_turu = None
            fatura.genel_islem_orani = Decimal("0")
            fatura.genel_islem_tutari = Decimal("0")
            fatura.tl_genel_toplam = satir_net
        # İstemci hedefi ile satır neti sapmasın
        if abs(kurus(hedef_net) - satir_net) > Decimal("0.01"):
            raise ValueError(
                f"Fatura sağlaması: satır toplamı ({satir_net}) hedef Net ({hedef_net}) ile uyuşmuyor."
            )

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
                    "cari_kodu": (f.cari.cari_kodu if f.cari else "") or "",
                    "cari_ad": f.cari.unvan if f.cari else "",
                    "vergi_no": (getattr(f.cari, "vergi_no", None) or "") if f.cari else "",
                    "siparis_no": f.siparis.siparis_no if f.siparis else "",
                    "irsaliye_no": f.irsaliye.irsaliye_no if f.irsaliye else "",
                    "depo": f.depo or "",
                    "genel_toplam": genel,
                    "matrah": Decimal(str(getattr(f, "tl_matrah", 0) or 0)),
                    "kdv": Decimal(str(getattr(f, "tl_kdv", 0) or 0)),
                    "tahsilat_tutari": tahsilat,
                    "durum": f.durum or "",
                    "para_birimi": (getattr(f, "para_birimi", None) or "TRY"),
                    "onaylandi": bool(getattr(f, "onaylandi", False)),
                    "created_by_full_name": getattr(f, "created_by_full_name", None),
                    "created_by_user_id": getattr(f, "created_by_user_id", None),
                    "approved_by_full_name": getattr(f, "approved_by_full_name", None),
                    "approved_by_user_id": getattr(f, "approved_by_user_id", None),
                    "aciklama": getattr(f, "aciklama", None),
                    "tahsilat_alan_full_name": getattr(f, "tahsilat_alan_full_name", None),
                    "kasa_terminal": getattr(f, "kasa_terminal", None),
                    "tahsilat_sekli": getattr(f, "tahsilat_sekli", None),
                    "sales_person_id": getattr(f, "sales_person_id", None),
                    "sales_person_full_name": getattr(f, "sales_person_full_name", None),
                    "olusturma_tarihi": getattr(f, "olusturma_tarihi", None),
                    "document_type": "SALES_INVOICE",
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
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_create,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        from database.satis_personeli import secimi_dogrula

        # UI satış personeli alanını kaldırdı; yeni faturalarda boş bırakılabilir.
        # Mevcut faturalardaki değer (pasif personel dahil) korunur.
        sp_raw = veriler.get("sales_person_id")
        if not sp_raw:
            sp_id, sp_ad = None, None
        else:
            try:
                sp_id, sp_ad = secimi_dogrula(sp_raw, zorunlu=False)
            except ValueError:
                sp_id = int(sp_raw)
                sp_ad = (veriler.get("sales_person_full_name") or "").strip() or None
        tahsilat_verileri = list(tahsilat_verileri or [])
        with get_session() as session:
            yeni = False
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
                yeni = True
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
                        manuel_fiyat=bool(veri.get("manuel_fiyat")),
                        dagitima_kapali=bool(
                            veri.get("dagitima_kapali")
                            or veri.get("fiyat_kilitli")
                            or veri.get("distribution_locked")
                        ),
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
            SatisFaturasiService._doviz_alanlarini_yaz(fatura, veriler, toplam_dict)
            # Muhasebe tutarı = Net (tl_genel_toplam)
            toplam = Decimal(str(fatura.tl_genel_toplam or 0))
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
            fatura.sales_person_id = sp_id
            fatura.sales_person_full_name = sp_ad
            if yeni:
                stamp_create(fatura)
            else:
                stamp_update(fatura)
            session.flush()
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            fid = int(fatura.id)
            fno = fatura.fatura_no
            eylem = "FATURA_OLUSTUR" if yeni else "FATURA_DUZENLE"
        audit_document(
            eylem,
            modul="satis_faturasi",
            kayit_id=str(fid),
            belge_no=fno,
        )
        return SatisFaturasiService.getir(fid) or fatura

    @staticmethod
    def satis_personeli_guncelle(fatura_id, sales_person_id):
        """Onaylı fatura dahil satış personelini günceller; değişiklik audit'e yazılır."""
        yazma_zorunlu("satis_duzenleme")
        from database.satis_personeli import secimi_dogrula
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        sp_id, sp_ad = secimi_dogrula(sales_person_id)
        with get_session() as session:
            fatura = session.get(SatisFaturasi, int(fatura_id))
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                raise ValueError("İptal edilmiş faturada satış personeli değiştirilemez.")
            eski_id = getattr(fatura, "sales_person_id", None)
            eski_ad = getattr(fatura, "sales_person_full_name", None)
            if eski_id is not None and int(eski_id) == int(sp_id):
                return SatisFaturasiService.getir(int(fatura_id))
            fatura.sales_person_id = sp_id
            fatura.sales_person_full_name = sp_ad
            stamp_update(fatura)
            session.flush()
            fid = int(fatura.id)
            fno = fatura.fatura_no
            onayli = bool(getattr(fatura, "onaylandi", False))
        if onayli:
            audit_document(
                "SATIS_PERSONELI_DEGISTI",
                modul="satis_faturasi",
                kayit_id=str(fid),
                belge_no=fno,
                eski={
                    "sales_person_id": eski_id,
                    "sales_person_full_name": eski_ad,
                },
                yeni={
                    "sales_person_id": sp_id,
                    "sales_person_full_name": sp_ad,
                },
            )
        else:
            audit_document(
                "FATURA_DUZENLE",
                modul="satis_faturasi",
                kayit_id=str(fid),
                belge_no=fno,
            )
        return SatisFaturasiService.getir(fid)

    @staticmethod
    def onayla(fatura_id):
        """Taslak faturayı onaylar: stok çıkışı, cari borç ve finans tahsilatı oluşturur."""
        yazma_zorunlu("satis_duzenleme")
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_approve,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
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

            # Tüm satırlar için stok yeterlilik (ürün bazında toplu) — çıkıştan önce
            SatisFaturasiService._onay_oncesi_stok_yeterlilik(session, fatura)

            for satir in fatura.satirlar:
                # İrsaliyeden stok çıkışı yapılmışsa fatura satırında tekrar çıkış yapma
                skip_stok = False
                if fatura.irsaliye_id and getattr(satir, "irsaliye_satiri_id", None):
                    from database.models.satis_irsaliyesi import SatisIrsaliyesi
                    from database.satis_irsaliyesi_service import stok_cikis_gerekli

                    ir = session.get(SatisIrsaliyesi, fatura.irsaliye_id)
                    if ir is not None and not stok_cikis_gerekli(ir):
                        skip_stok = True
                        satir.lot_cikisi = "İrsaliye stokundan"
                        if getattr(satir, "fifo_birim_maliyeti", None) is None:
                            satir.fifo_birim_maliyeti = Decimal("0")
                if skip_stok:
                    continue
                try:
                    from fatura_satir_birim_service import temel_miktar

                    stok_miktar = temel_miktar(
                        satir.miktar,
                        getattr(satir, "birim", None) or "Adet",
                        (satir.urun_kodu or "").strip(),
                    )
                    stok_cikisi = StokService.fatura_cikisi(
                        session,
                        fatura.fatura_no,
                        tarih,
                        satir.urun_kodu.strip(),
                        fatura.depo,
                        stok_miktar,
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
            stamp_approve(fatura)
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura onaylanamadı.") from hata
            fid = int(fatura.id)
            fno = fatura.fatura_no
        audit_document(
            "FATURA_ONAY",
            modul="satis_faturasi",
            kayit_id=str(fid),
            belge_no=fno,
        )

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
    def iptal_et(fatura_id, sebep: str | None = None):
        yazma_zorunlu("satis_duzenleme", "iptal")
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_cancel,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        neden = (sebep or "").strip()
        if not neden:
            raise ValueError("İptal nedeni zorunludur.")
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
                stamp_cancel(fatura, neden)
                SatisFaturasiService._durumlari_guncelle(session, fatura)
                fid = int(fatura.id)
                fno = fatura.fatura_no
            else:
                return

        audit_document(
            "FATURA_IPTAL",
            modul="satis_faturasi",
            kayit_id=str(fid),
            belge_no=fno,
            yeni={"cancellation_reason": neden},
        )
        if onayliydi:
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("satis_faturasi_iptal", fid)
        from database.deleted_record_service import ENTITY_SATIS_FATURA, safe_log_cancel

        safe_log_cancel(ENTITY_SATIS_FATURA, fatura_id, note=f"Satış faturası iptal: {neden}")

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
        """Üç kademeli iskonto sonrası KDV matrahı; satır tutarı tam TL (ROUND_HALF_UP).

        Birim fiyat / miktar hassasiyeti korunur; yuvarlama yalnızca satır
        matrahına uygulanır. İskonto yoksa brüt de aynı tam TL değerine çekilir
        (ara toplam = matrah). İskonto varsa brüt ham kalır, fark indirimde.
        """
        from database.iskonto_hesap_service import round_line_total, satir_net_brut_indirim

        brut, indirim, net = satir_net_brut_indirim(
            miktar, fiyat, iskonto1, iskonto2, iskonto3
        )
        net = round_line_total(net)
        if indirim == 0:
            brut = net
            indirim = Decimal("0")
        else:
            indirim = brut - net
        return brut, indirim, net

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
        """Cari net bakiye + isteğe bağlı bu fatura açığı (müşteri listesi ile aynı kaynak).

        haric_fatura_no: düzenlenen fatura belge no (Eski Bakiye'de çift sayım yok).
        eklenecek: bu faturanın açık tutarı → Yeni Bakiye = Eski + eklenecek.
        """
        from database.cari_bakiye_service import fatura_eski_yeni_bakiye

        eklenecek = Decimal(str(eklenecek or 0))
        ozet = fatura_eski_yeni_bakiye(
            int(cari_id),
            exclude_belge_no=haric_fatura_no,
            belge_etkisi=eklenecek,
            tani_log=False,
        )
        # Ağırlıklı ortalama vade (UI): açık SatisHareketi + eklenecek
        ortalama = None
        with get_session() as session:
            hs = session.scalars(
                select(SatisHareketi).where(
                    SatisHareketi.cari_id == int(cari_id),
                    SatisHareketi.kalan_acik_tutar != 0,
                )
            ).all()
            agirlik = Decimal("0")
            agirlik_pay = Decimal("0")
            haric = (haric_fatura_no or "").strip()
            for h in hs:
                if haric and (h.belge_no or "") == haric:
                    continue
                kalan = Decimal(str(h.kalan_acik_tutar or 0))
                if kalan <= 0:
                    continue
                tarih = h.satis_tarihi or date.today()
                agirlik += Decimal(tarih.toordinal()) * kalan
                agirlik_pay += kalan
            if eklenecek > 0:
                agirlik += Decimal((vade or date.today()).toordinal()) * eklenecek
                agirlik_pay += eklenecek
            if agirlik_pay > 0:
                ortalama = date.fromordinal(int(agirlik / agirlik_pay))
        return {"bakiye": ozet["yeni_bakiye"], "ortalama_vade": ortalama, "eski_bakiye": ozet["eski_bakiye"]}

    @staticmethod
    def otomatik_lot_no(firma_adi, tarih=None):
        onek = "".join(c for c in (firma_adi or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{(tarih or date.today()):%Y%m%d}"

    @staticmethod
    def fatura_no():
        """SF-00001 formatında artan satış fatura numarası (tek sorgu)."""
        from sqlalchemy import text

        onek = "SF-"
        with get_session() as session:
            try:
                max_sira = session.execute(
                    text(
                        "SELECT MAX(CAST(SUBSTR(fatura_no, :bas) AS INTEGER)) "
                        "FROM satis_faturalari WHERE fatura_no LIKE :patern "
                        "AND SUBSTR(fatura_no, :bas) GLOB '[0-9]*'"
                    ),
                    {"bas": len(onek) + 1, "patern": f"{onek}%"},
                ).scalar()
                max_sira = int(max_sira or 0)
            except Exception:
                numaralar = session.scalars(
                    select(SatisFaturasi.fatura_no).where(
                        SatisFaturasi.fatura_no.like(f"{onek}%")
                    )
                ).all()
                max_sira = 0
                for no in numaralar:
                    kuyruk = str(no)[len(onek) :]
                    if kuyruk.isdigit():
                        max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:05d}"
