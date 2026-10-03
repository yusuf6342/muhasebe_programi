from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.access import yazma_zorunlu
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.doviz_service import DovizService
from database.models.stok import StokKarti
from database.stok_service import BagliAlisHatasi, StokService

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
ODEME_SEKILLERI = ("KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME")


def alis_evrak_durumu(durum: str | None, onaylandi: bool | None) -> str:
    """Liste/rozet için evrak durumu: İPTAL > ONAYLI > ONAYSIZ (ödeme ayrı izlenir)."""
    if (durum or "").upper() == "İPTAL":
        return "İPTAL"
    return "ONAYLI" if onaylandi else "ONAYSIZ"


def _deger(satir, alan, varsayilan=None):
    if isinstance(satir, dict):
        return satir.get(alan, varsayilan)
    return getattr(satir, alan, varsayilan)


def _sayi(deger) -> Decimal | None:
    try:
        return Decimal(str(deger if deger not in (None, "") else 0).replace(",", "."))
    except Exception:
        return None


def onay_hatalari(
    *,
    cari,
    satirlar,
    fatura_tarihi,
    vade_tarihi,
    depo,
    para_birimi="TRY",
    kur=1,
) -> list[str]:
    """Onay öncesi kontrol; boş liste = onaylanabilir. UI ve servis aynı kuralları kullanır."""
    hatalar: list[str] = []
    if cari is None:
        hatalar.append("Tedarikçi seçilmemiş.")
    else:
        if not getattr(cari, "aktif", True):
            hatalar.append("Seçili tedarikçi kartı pasif.")
        tur = (getattr(cari, "cari_turu", "") or "").casefold()
        if tur and not tur.startswith("tedarik") and "her" not in tur:
            hatalar.append("Seçili cari bir tedarikçi kartı değil.")
    if not fatura_tarihi:
        hatalar.append("Fatura tarihi geçersiz.")
    elif fatura_tarihi > date.today():
        hatalar.append("Fatura tarihi gelecek bir tarih olamaz.")
    if not vade_tarihi:
        hatalar.append("Vade tarihi geçersiz.")
    elif fatura_tarihi and vade_tarihi < fatura_tarihi:
        hatalar.append("Vade tarihi fatura tarihinden önce olamaz.")
    if not (depo or "").strip():
        hatalar.append("Giriş deposu seçilmemiş.")
    pb = (para_birimi or "TRY").upper()
    if pb not in ("TRY", "TL"):
        k = _sayi(kur)
        if k is None or k <= 0:
            hatalar.append(f"{pb} faturası için geçerli bir kur girilmemiş.")
    if not satirlar:
        hatalar.append("Faturada ürün satırı yok.")
    for sira, s in enumerate(satirlar or [], start=1):
        kod = (_deger(s, "urun_kodu", "") or "").strip()
        ad = f"{sira}. satır" + (f" ({kod})" if kod else "")
        if not kod:
            hatalar.append(f"{ad}: ürün kodu boş.")
        miktar = _sayi(_deger(s, "miktar"))
        if miktar is None or miktar <= 0:
            hatalar.append(f"{ad}: miktar sıfırdan büyük olmalı.")
        if not (_deger(s, "birim", "") or "").strip():
            hatalar.append(f"{ad}: birim boş.")
        fiyat = _sayi(_deger(s, "birim_fiyat", _deger(s, "birim_alis_fiyati")))
        if fiyat is None or fiyat <= 0:
            hatalar.append(f"{ad}: birim fiyat sıfırdan büyük olmalı.")
        kdv = _sayi(_deger(s, "kdv_orani"))
        if kdv is None or kdv < 0 or kdv > 100:
            hatalar.append(f"{ad}: KDV oranı geçersiz.")
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            isk = _sayi(_deger(s, alan, 0))
            if isk is None or isk < 0 or isk > 100:
                hatalar.append(f"{ad}: iskonto oranı 0–100 arasında olmalı.")
                break
    return hatalar


class MukerrerTedarikciFaturaHatasi(ValueError):
    def __init__(self, mesaj: str, fatura_id: int, fatura_no: str):
        super().__init__(mesaj)
        self.fatura_id = fatura_id
        self.fatura_no = fatura_no


class AlisFaturasiService:
    @staticmethod
    def mukerrer_tedarikci_faturasi(session, cari_id, tedarikci_fatura_no, haric_id=None):
        """Aynı tedarikçinin aynı fatura numaralı iptal edilmemiş kaydı (firma ayrı veritabanındadır)."""
        no = (tedarikci_fatura_no or "").strip()
        if not no or not cari_id:
            return None
        sorgu = select(AlisFaturasi).where(
            AlisFaturasi.cari_id == int(cari_id),
            AlisFaturasi.durum != "İPTAL",
            func.upper(AlisFaturasi.tedarikci_fatura_no) == no.upper(),
        )
        if haric_id:
            sorgu = sorgu.where(AlisFaturasi.id != int(haric_id))
        if hasattr(AlisFaturasi, "is_deleted"):
            sorgu = sorgu.where(or_(AlisFaturasi.is_deleted.is_(False), AlisFaturasi.is_deleted.is_(None)))
        return session.scalar(sorgu.limit(1))

    @staticmethod
    def mukerrer_kontrol(cari_id, tedarikci_fatura_no, haric_id=None):
        with get_session() as session:
            mevcut = AlisFaturasiService.mukerrer_tedarikci_faturasi(
                session, cari_id, tedarikci_fatura_no, haric_id
            )
            return (int(mevcut.id), mevcut.fatura_no) if mevcut else None

    @staticmethod
    def aktif_tedarikcileri():
        from database.alis_siparisi_service import AlisSiparisiService
        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def urun_alis_hareketleri(urun_kodu: str) -> list[dict[str, Any]]:
        """Ürün alış fatura satırları (yeniden eskiye)."""
        urun_kodu = (urun_kodu or "").strip()
        if not urun_kodu:
            return []
        with get_session() as session:
            satirlar = session.scalars(
                select(AlisFaturasiSatiri)
                .join(AlisFaturasi)
                .where(
                    AlisFaturasi.durum != "İPTAL",
                    AlisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(
                    selectinload(AlisFaturasiSatiri.fatura).selectinload(AlisFaturasi.cari),
                )
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasiSatiri.id.desc())
            ).all()
            kayitlar = []
            for satir in satirlar:
                fiyat = Decimal(str(satir.birim_fiyat or 0))
                net = AlisFaturasiService._net_birim_maliyet(
                    fiyat,
                    Decimal(str(satir.iskonto_orani or 0)),
                    getattr(satir, "iskonto_orani_2", 0) or 0,
                    getattr(satir, "iskonto_orani_3", 0) or 0,
                )
                cari = satir.fatura.cari if satir.fatura else None
                kayitlar.append({
                    "tarih": satir.fatura.fatura_tarihi if satir.fatura else None,
                    "belge_no": satir.fatura.fatura_no if satir.fatura else "",
                    "tedarikci": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                    "miktar": Decimal(str(satir.miktar or 0)),
                    "birim": satir.birim or "",
                    "net_fiyat": net,
                })
            return kayitlar

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            faturalar = session.scalars(
                select(AlisFaturasi)
                .options(
                    selectinload(AlisFaturasi.cari),
                    selectinload(AlisFaturasi.satirlar),
                    selectinload(AlisFaturasi.siparis),
                    selectinload(AlisFaturasi.irsaliye),
                )
                .order_by(AlisFaturasi.id.desc())
            ).all()
            return [{"fatura": f, **AlisFaturasiService.toplam(f.satirlar)} for f in faturalar]

    @staticmethod
    def listele_ozet(tarih_bas=None, tarih_bit=None) -> list[dict[str, Any]]:
        """Liste penceresi için hızlı özet (satır yüklemez)."""
        from sqlalchemy.orm import joinedload

        with get_session() as session:
            statement = (
                select(AlisFaturasi)
                .options(joinedload(AlisFaturasi.cari))
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc())
            )
            # Soft-delete varsa hariç tut
            if hasattr(AlisFaturasi, "is_deleted"):
                from sqlalchemy import or_

                statement = statement.where(
                    or_(AlisFaturasi.is_deleted.is_(False), AlisFaturasi.is_deleted.is_(None))
                )
            if tarih_bas is not None:
                statement = statement.where(AlisFaturasi.fatura_tarihi >= tarih_bas)
            if tarih_bit is not None:
                statement = statement.where(AlisFaturasi.fatura_tarihi <= tarih_bit)
            faturalar = list(session.scalars(statement).unique().all())
            from database.acik_kalem_service import odeme_durumu

            acik_map: dict[tuple[int, str], Decimal] = {}
            nolar = [f.fatura_no for f in faturalar if f.fatura_no]
            for i in range(0, len(nolar), 500):
                for cid, bno, kalan in session.execute(
                    select(
                        SatisHareketi.cari_id, SatisHareketi.belge_no, SatisHareketi.kalan_acik_tutar
                    ).where(
                        SatisHareketi.belge_no.in_(nolar[i:i + 500]),
                        SatisHareketi.satis_tutari > 0,
                    )
                ).all():
                    acik_map[(int(cid), bno)] = Decimal(str(kalan or 0))
            sonuc = []
            for f in faturalar:
                genel = Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0))
                cari = f.cari
                iptal = (f.durum or "") == "İPTAL"
                anahtar = (int(f.cari_id), f.fatura_no)
                if iptal:
                    acik = Decimal("0")
                elif anahtar in acik_map:
                    acik = max(Decimal("0"), acik_map[anahtar])
                else:
                    acik = max(Decimal("0"), genel - Decimal(str(f.odeme_tutari or 0)))
                kapanan = Decimal("0") if iptal else max(Decimal("0"), genel - acik)
                sonuc.append({
                    "kapanan_tutar": kapanan,
                    "acik_tutar": acik,
                    "odeme_durumu": "" if iptal else odeme_durumu(genel, kapanan),
                    "id": f.id,
                    "fatura_no": f.fatura_no or "",
                    "tedarikci_fatura_no": getattr(f, "tedarikci_fatura_no", None) or "",
                    "fatura_tarihi": f.fatura_tarihi,
                    "cari_kodu": (cari.cari_kodu if cari else "") or "",
                    "cari_ad": (cari.unvan if cari else "") or "",
                    "vergi_no": (getattr(cari, "vergi_no", None) or "") if cari else "",
                    "durum": f.durum or "",
                    "onaylandi": bool(getattr(f, "onaylandi", False)),
                    "evrak_durumu": alis_evrak_durumu(f.durum, getattr(f, "onaylandi", False)),
                    "genel_toplam": genel,
                    "matrah": Decimal(str(getattr(f, "tl_matrah", 0) or 0)),
                    "kdv": Decimal(str(getattr(f, "tl_kdv", 0) or 0)),
                    "para_birimi": (getattr(f, "para_birimi", None) or "TRY"),
                    "olusturma_tarihi": getattr(f, "olusturma_tarihi", None),
                    "created_by_full_name": getattr(f, "created_by_full_name", None),
                    "document_type": "PURCHASE_INVOICE",
                })
            return sonuc

    @staticmethod
    def tedarikci_evraklari(cari_id: int) -> dict[str, list[dict[str, Any]]]:
        """Tedarikçi kartı için: faturalanmamış irsaliyeler, alış faturaları, alış iadeleri."""
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.models.alis_iade_faturasi import AlisIadeFaturasi

        with get_session() as session:
            irsaliyeler = session.scalars(
                select(AlisIrsaliyesi)
                .where(
                    AlisIrsaliyesi.cari_id == int(cari_id),
                    AlisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI")),
                )
                .options(selectinload(AlisIrsaliyesi.satirlar), selectinload(AlisIrsaliyesi.siparis))
                .order_by(AlisIrsaliyesi.irsaliye_tarihi.desc(), AlisIrsaliyesi.id.desc())
            ).all()
            faturalar = session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.cari_id == int(cari_id))
                .options(selectinload(AlisFaturasi.siparis), selectinload(AlisFaturasi.irsaliye))
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc())
            ).all()
            iadeler = session.scalars(
                select(AlisIadeFaturasi)
                .where(AlisIadeFaturasi.cari_id == int(cari_id))
                .options(selectinload(AlisIadeFaturasi.satirlar))
                .order_by(AlisIadeFaturasi.iade_tarihi.desc(), AlisIadeFaturasi.id.desc())
            ).all()
            from database.models.alis_siparisi import AlisSiparisi

            siparisler = session.scalars(
                select(AlisSiparisi)
                .where(AlisSiparisi.cari_id == int(cari_id))
                .options(selectinload(AlisSiparisi.satirlar))
                .order_by(AlisSiparisi.siparis_tarihi.desc(), AlisSiparisi.id.desc())
            ).all()
            try:
                from database.satin_alma_talep_service import SatinAlmaTalepService

                talepler = SatinAlmaTalepService.tedarikci_talepleri(int(cari_id))
            except Exception:  # noqa: BLE001
                talepler = []
            return {
                "siparis": [
                    {
                        "id": s.id,
                        "no": s.siparis_no,
                        "tarih": s.siparis_tarihi,
                        "termin": s.termin_tarihi,
                        "satir": len(s.satirlar),
                        "acik_satir": sum(
                            1 for x in s.satirlar
                            if x.miktar > max(x.irsaliyelenen_miktar or 0, x.faturalanan_miktar or 0)
                        ),
                        "durum": s.durum,
                    }
                    for s in siparisler
                ],
                "talep": [
                    {
                        "id": t["id"],
                        "no": t["talep_no"],
                        "tarih": t["tarih"],
                        "termin": t["ihtiyac_tarihi"],
                        "isteyen": t["isteyen"],
                        "durum": t["durum"],
                    }
                    for t in talepler
                ],
                "irsaliye": [
                    {
                        "id": i.id,
                        "no": i.irsaliye_no,
                        "tarih": i.irsaliye_tarihi,
                        "siparis": i.siparis.siparis_no if i.siparis else "",
                        "miktar": sum((s.miktar for s in i.satirlar), Decimal("0")),
                        "kalan": sum((s.miktar - s.faturalanan_miktar for s in i.satirlar), Decimal("0")),
                        "durum": i.durum,
                    }
                    for i in irsaliyeler
                ],
                "fatura": [
                    {
                        "id": f.id,
                        "no": f.fatura_no,
                        "ted_no": f.tedarikci_fatura_no or "",
                        "tarih": f.fatura_tarihi,
                        "siparis": f.siparis.siparis_no if f.siparis else "",
                        "irsaliye": f.irsaliye.irsaliye_no if f.irsaliye else "",
                        "genel": Decimal(str(f.tl_genel_toplam or 0)),
                        "durum": f.durum,
                    }
                    for f in faturalar
                ],
                "iade": [
                    {
                        "id": i.id,
                        "no": i.iade_no,
                        "tarih": i.iade_tarihi,
                        "genel": AlisIadeFaturasiService.toplam(i.satirlar)["genel_toplam"],
                        "durum": i.durum,
                    }
                    for i in iadeler
                ],
            }

    @staticmethod
    def getir(fatura_id):
        with get_session() as session:
            return session.scalar(
                select(AlisFaturasi)
                .options(
                    selectinload(AlisFaturasi.cari),
                    selectinload(AlisFaturasi.siparis),
                    selectinload(AlisFaturasi.irsaliye),
                    selectinload(AlisFaturasi.satirlar),
                )
                .where(AlisFaturasi.id == fatura_id)
            )

    @staticmethod
    def acik_siparisler():
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisSiparisi)
                    .where(AlisSiparisi.durum.notin_(("İPTAL", "TASLAK")))
                    .options(selectinload(AlisSiparisi.cari), selectinload(AlisSiparisi.satirlar))
                    .order_by(AlisSiparisi.id.desc())
                ).all()
            )

    @staticmethod
    def acik_irsaliyeler():
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisIrsaliyesi)
                    .where(AlisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI")))
                    .options(selectinload(AlisIrsaliyesi.cari), selectinload(AlisIrsaliyesi.satirlar))
                    .order_by(AlisIrsaliyesi.id.desc())
                ).all()
            )

    @staticmethod
    def _net_birim_maliyet(birim_fiyat: Decimal, iskonto_orani: Decimal, iskonto2=0, iskonto3=0) -> Decimal:
        """İskonto sonrası (KDV öncesi) birim maliyet — üç kademeli."""
        from database.iskonto_hesap_service import iskonto_carpani

        return Decimal(str(birim_fiyat or 0)) * iskonto_carpani(
            iskonto_orani, iskonto2, iskonto3
        )

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None):
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme", "yeni_kayit")
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        beklenen_versiyon = veriler.get("row_version")
        if fatura_id:
            from database.masraf_dagitim_service import MasrafDagitimService

            MasrafDagitimService.kilit_kontrol(alis_fatura_id=int(fatura_id))
            yalniz_aciklama_id = AlisFaturasiService._bagli_alis_duzenleme(
                int(fatura_id), veriler, satir_verileri, beklenen_versiyon
            )
            if yalniz_aciklama_id is not None:
                return AlisFaturasiService.getir(yalniz_aciklama_id)
        with get_session() as session:
            if fatura_id:
                fatura = session.get(AlisFaturasi, fatura_id)
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                if getattr(fatura, "onaylandi", False):
                    raise ValueError(
                        "Onaylı alış faturası değiştirilemez. Değişiklik için önce onayı kaldırın."
                    )
                mevcut_v = int(getattr(fatura, "row_version", 1) or 1)
                if beklenen_versiyon is not None and int(beklenen_versiyon) != mevcut_v:
                    raise ValueError(
                        "Bu fatura başka bir kullanıcı tarafından değiştirilmiş. "
                        "Listeyi yenileyip tekrar açın."
                    )
                AlisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_girislerini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)
                MasrafDagitimService.bagli_taslaklari_iptal(
                    session, alis_fatura_id=int(fatura.id),
                    neden=f"Alış faturası {fatura.fatura_no} düzenlendi; satırları yeniden oluşturuldu.",
                )
                fatura.satirlar.clear()
                fatura.row_version = mevcut_v + 1
            else:
                fatura = AlisFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip() or AlisFaturasiService.fatura_no(),
                    row_version=1,
                )
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (veriler.get("islem_saati") or "").strip() or datetime.now().strftime("%H:%M")
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "odeme_sekli", "odeme_hesabi", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            ted_no = (veriler.get("tedarikci_fatura_no") or "").strip() or None
            mukerrer = AlisFaturasiService.mukerrer_tedarikci_faturasi(
                session, fatura.cari_id, ted_no, fatura_id
            )
            if mukerrer is not None:
                raise MukerrerTedarikciFaturaHatasi(
                    f"Bu tedarikçinin '{ted_no}' numaralı faturası zaten kayıtlı "
                    f"(kayıt no: {mukerrer.fatura_no}).",
                    int(mukerrer.id),
                    mukerrer.fatura_no,
                )
            fatura.tedarikci_fatura_no = ted_no
            from database.sube_service import SubeService

            fatura.sube_id = SubeService.transaction_subesi(session, veriler.get("sube_id"))
            fatura.odeme_tutari = decimal(veriler.get("odeme_tutari", 0), "Ödeme", Decimal("0"))
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
            fatura.para_birimi = pb
            fatura.kur = kur
            fatura.kur_tarihi = veriler.get("kur_tarihi")
            fatura.kur_turu = veriler.get("kur_turu") or "forex_selling"
            fatura.kur_kaynagi = veriler.get("kur_kaynagi") or "TCMB"
            fatura.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", pb != "TRY"))

            cari = session.get(Cari, fatura.cari_id)
            tedarikci_adi = cari.unvan if cari else ""

            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                kart = session.scalar(
                    select(StokKarti)
                    .where(StokKarti.stok_kodu == veri["urun_kodu"].strip())
                    .options(selectinload(StokKarti.birimler))
                )
                if kart is None:
                    raise ValueError(f"{veri['urun_kodu'].strip()} kodlu ürünün stok kartı yok.")
                carpan = StokService.birim_carpani_kesin(kart, veri.get("birim") or kart.birim or "Adet")
                birim_fiyat_doviz = decimal(
                    veri.get("birim_fiyat_doviz") or veri.get("birim_fiyat", 0),
                    "Birim fiyat",
                    Decimal("0"),
                )
                if pb != "TRY" and birim_fiyat_doviz > 0:
                    birim_fiyat = DovizService.dovizden_tle(birim_fiyat_doviz, kur, Decimal("0.0001"))
                else:
                    birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                    birim_fiyat_doviz = Decimal("0")
                iskonto_orani = decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                iskonto_orani_2 = decimal(veri.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0"))
                iskonto_orani_3 = decimal(veri.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0"))
                irs_id, sip_id = veri.get("irsaliye_satiri_id"), veri.get("siparis_satiri_id")
                if irs_id:
                    kaynak = session.get(AlisIrsaliyesiSatiri, int(irs_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı irsaliyenin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(AlisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            if miktar > siparis_satiri.miktar - siparis_satiri.faturalanan_miktar:
                                raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                            siparis_satiri.faturalanan_miktar += miktar
                            siparis_satiri.fatura_belge_baglantisi = fatura.fatura_no
                        sip_id = kaynak.siparis_satiri_id
                elif sip_id:
                    kaynak = session.get(AlisSiparisiSatiri, int(sip_id))
                    if kaynak is not None and kaynak.siparis.durum == "TASLAK":
                        raise ValueError("Taslak sipariş faturaya çevrilemez; önce siparişi kesinleştirin.")
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no

                birim_maliyet = AlisFaturasiService._net_birim_maliyet(
                    birim_fiyat, iskonto_orani, iskonto_orani_2, iskonto_orani_3
                )
                # Stok kartı ALIŞ FİYATI: faturadaki net iskontolu fiyat (FIFO override'dan bağımsız)
                net_alis_fiyati = birim_maliyet
                stok_maliyeti = birim_maliyet
                if veri.get("fifo_birim_maliyeti") not in (None, "", 0, "0"):
                    stok_maliyeti = decimal(veri["fifo_birim_maliyeti"], "FIFO maliyet", Decimal("0"))

                # Stok ve FIFO lotu temel birimde: 2 Koli (×12) → 24 Adet, maliyet koli fiyatı / 12
                stok_girisi = StokService.fatura_girisi(
                    session,
                    fatura.fatura_no,
                    tarih,
                    veri["urun_kodu"].strip(),
                    fatura.depo,
                    (miktar * carpan).quantize(Decimal("0.0001")),
                    (stok_maliyeti / carpan).quantize(Decimal("0.0001")),
                    tedarikci=tedarikci_adi,
                    lot_no=veri.get("lot_no") or "",
                )
                StokService.alis_fiyatini_guncelle(
                    session,
                    veri["urun_kodu"].strip(),
                    (net_alis_fiyati / carpan).quantize(Decimal("0.0001")),
                )
                fatura.satirlar.append(
                    AlisFaturasiSatiri(
                        siparis_satiri_id=sip_id,
                        irsaliye_satiri_id=irs_id,
                        urun_kodu=veri["urun_kodu"].strip(),
                        urun_adi=veri["urun_adi"].strip(),
                        barkod=veri.get("barkod") or None,
                        aciklama=veri.get("aciklama") or None,
                        lot_no=veri.get("lot_no") or None,
                        lot_girisi=stok_girisi["lot_girisi"],
                        miktar=miktar,
                        birim=veri.get("birim") or "Adet",
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=iskonto_orani,
                        iskonto_orani_2=iskonto_orani_2,
                        iskonto_orani_3=iskonto_orani_3,
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        fifo_birim_maliyeti=stok_girisi["birim_maliyet"],
                        birim_carpani=carpan,
                        birim_fiyat_doviz=birim_fiyat_doviz,
                        tl_birim_fiyat=stok_maliyeti,
                        tl_tutar=(miktar * stok_maliyeti).quantize(Decimal("0.01")),
                    )
                )

            toplam_dict = AlisFaturasiService.toplam(fatura.satirlar)
            satir_genel = toplam_dict["genel_toplam"]
            fatura.tl_matrah = toplam_dict["ara_toplam"] - toplam_dict["iskonto"]
            fatura.tl_kdv = toplam_dict["kdv"]
            fatura.tl_brut_toplam = satir_genel
            fatura.tl_genel_toplam = satir_genel
            if hasattr(fatura, "genel_islem_turu"):
                fatura.genel_islem_turu = None
                fatura.genel_islem_orani = Decimal("0")
                fatura.genel_islem_tutari = Decimal("0")
            if hasattr(fatura, "invoice_rounding_adjustment"):
                fatura.invoice_rounding_adjustment = Decimal("0.00")
            if hasattr(fatura, "rounding_applied"):
                fatura.rounding_applied = False
                fatura.rounding_target_total = None
                fatura.rounding_version = int(veriler.get("rounding_version") or 0)
            toplam = fatura.tl_genel_toplam
            if pb != "TRY":
                from database.iskonto_hesap_service import iskonto_carpani

                doviz_ara = Decimal("0")
                for satir in fatura.satirlar:
                    if satir.birim_fiyat_doviz > 0:
                        carp = iskonto_carpani(
                            satir.iskonto_orani,
                            getattr(satir, "iskonto_orani_2", 0) or 0,
                            getattr(satir, "iskonto_orani_3", 0) or 0,
                        )
                        net = satir.birim_fiyat_doviz * carp
                        doviz_ara += satir.miktar * net
                fatura.doviz_ara_toplam = doviz_ara.quantize(Decimal("0.01"))
            if fatura.odeme_tutari > toplam:
                raise ValueError("Ödeme tutarı fatura toplamından büyük olamaz.")
            fatura.durum = "KAPALI" if fatura.odeme_tutari >= toplam else "AÇIK"
            session.flush()

            hareket = session.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id = fatura.cari_id
            hareket.satis_tarihi = tarih
            hareket.satis_tutari = toplam
            hareket.kalan_acik_tutar = toplam - fatura.odeme_tutari
            hareket.para_birimi = pb
            hareket.kur = kur if pb != "TRY" else Decimal("1")
            hareket.borc_esasi = "TL_SABIT"
            hareket.doviz_tutari = (
                Decimal(str(getattr(fatura, "doviz_ara_toplam", 0) or 0)) if pb != "TRY" else Decimal("0")
            )

            FinansService.fatura_odemesi(
                session,
                fatura.fatura_no,
                tarih,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
            )
            AlisFaturasiService._durumlari_guncelle(session, fatura)
            from database.acik_kalem_service import AcikKalemService

            AcikKalemService.avanslari_uygula(session, fatura.cari_id)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            fid = int(fatura.id)
            from database.muhasebe_entegrasyon import muhasebe_hook

            muhasebe_hook("alis_faturasi_fisi", fid, yeniden=True, session=session)
        return AlisFaturasiService.getir(fid)

    @staticmethod
    def _stok_etkili_degisiklikler(fatura, veriler, satir_verileri) -> list[str]:
        """Stok miktarı, birim, depo, fiyat/maliyet, cari veya ödemeyi etkileyen değişen alanlar."""

        def _d(v) -> Decimal:
            try:
                return Decimal(str(v if v not in (None, "") else 0)).quantize(Decimal("0.0001"))
            except Exception:  # noqa: BLE001
                return Decimal("0")

        def _m(v) -> str:
            return (str(v or "")).strip().casefold()

        degisen = []
        if veriler.get("fatura_tarihi") != fatura.fatura_tarihi:
            degisen.append("Fatura tarihi")
        if veriler.get("vade_tarihi") != fatura.vade_tarihi:
            degisen.append("Vade tarihi")
        if int(veriler.get("cari_id") or 0) != int(fatura.cari_id or 0):
            degisen.append("Tedarikçi")
        if _m(veriler.get("depo") or "ANA DEPO") != _m(fatura.depo or "ANA DEPO"):
            degisen.append("Depo")
        if _m(veriler.get("para_birimi") or "TRY") != _m(fatura.para_birimi or "TRY"):
            degisen.append("Para birimi")
        if (veriler.get("para_birimi") or "TRY").upper() != "TRY" and _d(veriler.get("kur", 1)) != _d(fatura.kur):
            degisen.append("Kur")
        if _d(veriler.get("odeme_tutari")) != _d(fatura.odeme_tutari):
            degisen.append("Ödeme tutarı")
        for alan, etiket in (("odeme_sekli", "Ödeme şekli"), ("odeme_hesabi", "Ödeme hesabı")):
            if _m(veriler.get(alan)) != _m(getattr(fatura, alan, None)):
                degisen.append(etiket)
        eski = list(fatura.satirlar)
        if len(eski) != len(satir_verileri):
            degisen.append("Satır sayısı")
            return degisen
        doviz = (veriler.get("para_birimi") or "TRY").upper() != "TRY"
        for no, (s, v) in enumerate(zip(eski, satir_verileri), start=1):
            fiyat_yeni = v.get("birim_fiyat_doviz") or v.get("birim_fiyat") if doviz else v.get("birim_fiyat")
            fiyat_eski = s.birim_fiyat_doviz if doviz else s.birim_fiyat
            kontroller = (
                ("Ürün", _m(v.get("urun_kodu")) != _m(s.urun_kodu)),
                ("Miktar", _d(v.get("miktar")) != _d(s.miktar)),
                ("Birim", _m(v.get("birim") or "Adet") != _m(s.birim or "Adet")),
                ("Birim fiyat", _d(fiyat_yeni) != _d(fiyat_eski)),
                ("İskonto", _d(v.get("iskonto_orani")) != _d(s.iskonto_orani)),
                ("İskonto 2", _d(v.get("iskonto_orani_2")) != _d(s.iskonto_orani_2)),
                ("İskonto 3", _d(v.get("iskonto_orani_3")) != _d(s.iskonto_orani_3)),
                ("KDV", _d(v.get("kdv_orani", 20)) != _d(s.kdv_orani)),
                ("Lot", _m(v.get("lot_no")) != _m(s.lot_no)),
            )
            for etiket, farkli in kontroller:
                if farkli:
                    degisen.append(f"{no}. satır {etiket}")
        return degisen

    @staticmethod
    def _bagli_alis_duzenleme(fatura_id: int, veriler, satir_verileri, beklenen_versiyon) -> int | None:
        """Lotundan çıkış yapılmış alışta yalnız maliyeti etkilemeyen alanları günceller.

        Bağlı hareket yoksa None (normal kayıt akışı). Stok/maliyet etkili değişiklik varsa
        ``BagliAlisHatasi``. Yalnız açıklama türü alanlar değiştiyse güncelleyip fatura id döner.
        """
        with get_session() as session:
            fatura = session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar))
                .where(AlisFaturasi.id == int(fatura_id))
            )
            if fatura is None or fatura.durum == "İPTAL" or getattr(fatura, "onaylandi", False):
                return None
            bagli = StokService.giris_lotu_bagli_hareketleri(session, fatura.fatura_no)
            if not bagli:
                return None
            mevcut_v = int(getattr(fatura, "row_version", 1) or 1)
            if beklenen_versiyon is not None and int(beklenen_versiyon) != mevcut_v:
                raise ValueError(
                    "Bu fatura başka bir kullanıcı tarafından değiştirilmiş. "
                    "Listeyi yenileyip tekrar açın."
                )
            degisen = AlisFaturasiService._stok_etkili_degisiklikler(fatura, veriler, satir_verileri)
            if degisen:
                raise BagliAlisHatasi(
                    StokService.bagli_alis_mesaji(fatura.fatura_no, bagli, "değiştirilemez")
                    + "\n\nDeğiştirilmek istenen alanlar: " + ", ".join(degisen[:15]),
                    bagli,
                )
            ted_no = (veriler.get("tedarikci_fatura_no") or "").strip() or None
            mukerrer = AlisFaturasiService.mukerrer_tedarikci_faturasi(
                session, fatura.cari_id, ted_no, fatura.id
            )
            if mukerrer is not None:
                raise MukerrerTedarikciFaturaHatasi(
                    f"Bu tedarikçinin '{ted_no}' numaralı faturası zaten kayıtlı "
                    f"(kayıt no: {mukerrer.fatura_no}).",
                    int(mukerrer.id),
                    mukerrer.fatura_no,
                )
            fatura.tedarikci_fatura_no = ted_no
            fatura.aciklama = veriler.get("aciklama") or None
            fatura.dokuman_yolu = veriler.get("dokuman_yolu") or None
            for s, v in zip(fatura.satirlar, satir_verileri):
                s.aciklama = v.get("aciklama") or None
            fatura.row_version = mevcut_v + 1
            session.flush()
            return int(fatura.id)

    @staticmethod
    def onayla(fatura_id, row_version=None):
        """Kaydedilmiş alış faturasını onaylar.

        Stok girişi ve cari borç kayıt sırasında oluşur; onay yalnızca belgeyi doğrulayıp
        kilitler, yeni hareket üretmez. Zaten onaylı fatura için hata verir (tekrar yok).
        """
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme")
        with get_session() as session:
            fatura = session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar), selectinload(AlisFaturasi.cari))
                .where(AlisFaturasi.id == int(fatura_id))
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                raise ValueError("İptal edilmiş fatura onaylanamaz.")
            if getattr(fatura, "onaylandi", False):
                raise ValueError("Bu fatura zaten onaylı.")
            mevcut_v = int(getattr(fatura, "row_version", 1) or 1)
            if row_version is not None and int(row_version) != mevcut_v:
                raise ValueError(
                    "Bu fatura başka bir kullanıcı tarafından değiştirilmiş. "
                    "Faturayı yeniden açıp tekrar deneyin."
                )
            hatalar = onay_hatalari(
                cari=fatura.cari,
                satirlar=list(fatura.satirlar),
                fatura_tarihi=fatura.fatura_tarihi,
                vade_tarihi=fatura.vade_tarihi,
                depo=fatura.depo,
                para_birimi=fatura.para_birimi,
                kur=fatura.kur,
            )
            if hatalar:
                raise ValueError("Fatura onaylanamadı:\n• " + "\n• ".join(hatalar))
            fatura.onaylandi = True
            fatura.onay_tarihi = datetime.now()
            fatura.row_version = mevcut_v + 1
            session.flush()
            fid = int(fatura.id)
            fno = fatura.fatura_no
        try:
            from database.user_audit import audit_document

            audit_document("ALIS_FATURA_ONAY", modul="alis", kayit_id=str(fid), belge_no=fno)
        except Exception:
            pass
        return AlisFaturasiService.getir(fid)

    @staticmethod
    def onay_kaldir(fatura_id):
        """Onayı kaldırır; belge yeniden düzenlenebilir olur. Hareketler kayıtla güncellenir."""
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme", "iptal")
        from database.masraf_dagitim_service import MasrafDagitimService

        MasrafDagitimService.kilit_kontrol(alis_fatura_id=int(fatura_id))
        with get_session() as session:
            fatura = session.get(AlisFaturasi, int(fatura_id))
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                raise ValueError("İptal edilmiş faturanın onayı kaldırılamaz.")
            if not getattr(fatura, "onaylandi", False):
                raise ValueError("Bu fatura zaten onaysız.")
            fatura.onaylandi = False
            fatura.onay_tarihi = None
            fatura.row_version = int(getattr(fatura, "row_version", 1) or 1) + 1
            session.flush()
            fid = int(fatura.id)
            fno = fatura.fatura_no
        try:
            from database.user_audit import audit_document

            audit_document("ALIS_FATURA_ONAY_KALDIR", modul="alis", kayit_id=str(fid), belge_no=fno)
        except Exception:
            pass
        return AlisFaturasiService.getir(fid)

    @staticmethod
    def iptal_et(fatura_id):
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme", "iptal")
        from database.masraf_dagitim_service import MasrafDagitimService

        MasrafDagitimService.kilit_kontrol(alis_fatura_id=int(fatura_id))
        with get_session() as session:
            fatura = session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar))
                .where(AlisFaturasi.id == fatura_id)
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum != "İPTAL":
                bagli = StokService.giris_lotu_bagli_hareketleri(session, fatura.fatura_no)
                if bagli:
                    raise BagliAlisHatasi(
                        StokService.bagli_alis_mesaji(fatura.fatura_no, bagli, "iptal edilemez"), bagli
                    )
                AlisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_girislerini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)
                from database.acik_kalem_service import AcikKalemService

                AcikKalemService.belge_kalemlerini_sil(
                    session, fatura.fatura_no, fatura.cari_id, neden=f"Alış faturası iptal {fatura.fatura_no}"
                )
                MasrafDagitimService.bagli_taslaklari_iptal(
                    session, alis_fatura_id=int(fatura.id), neden=f"Alış faturası {fatura.fatura_no} iptal edildi."
                )
                fatura.durum = "İPTAL"
                AlisFaturasiService._durumlari_guncelle(session, fatura)
                fid = int(fatura.id)
                from database.muhasebe_entegrasyon import muhasebe_hook

                muhasebe_hook("alis_faturasi_iptal", fid, f"Alış faturası iptal {fatura.fatura_no}",
                              session=session)
            else:
                return

        from database.deleted_record_service import ENTITY_ALIS_FATURA, safe_log_cancel

        safe_log_cancel(ENTITY_ALIS_FATURA, fatura_id, note="Alış faturası iptal")

    @staticmethod
    def _baglantilari_geri_al(session, satirlar):
        for satir in satirlar:
            if satir.irsaliye_satiri_id:
                kaynak = session.get(AlisIrsaliyesiSatiri, satir.irsaliye_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(AlisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.faturalanan_miktar = max(
                                Decimal("0"), siparis_satiri.faturalanan_miktar - satir.miktar
                            )
            elif satir.siparis_satiri_id:
                kaynak = session.get(AlisSiparisiSatiri, satir.siparis_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)

    @staticmethod
    def _durumlari_guncelle(session, fatura):
        from database.alis_siparisi_service import AlisSiparisiService

        siparis_id = fatura.siparis_id
        if fatura.irsaliye_id:
            belge = session.scalar(
                select(AlisIrsaliyesi)
                .options(selectinload(AlisIrsaliyesi.satirlar))
                .where(AlisIrsaliyesi.id == fatura.irsaliye_id)
            )
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = (
                    "FATURALANDI" if kalan and all(x <= 0 for x in kalan)
                    else "KISMİ FATURALANDI" if any(s.faturalanan_miktar > 0 for s in belge.satirlar)
                    else "AÇIK"
                )
                if not siparis_id:
                    siparis_id = belge.siparis_id
        AlisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def toplam(satirlar):
        from decimal import ROUND_HALF_UP

        from database.iskonto_hesap_service import satir_net_brut_indirim

        ara = iskonto = kdv = Decimal("0")
        kurus = Decimal("0.01")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat", get("birim_alis_fiyati", 0)), "Birim fiyat")
            brut, indirim, net = satir_net_brut_indirim(
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
        with get_session() as session:
            hs = session.scalars(
                select(SatisHareketi).where(
                    SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar > 0
                )
            ).all()
            faturalar = session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.cari_id == cari_id, AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
            ).all()
            fatura_nolari = {f.fatura_no for f in faturalar}
            bakiye = Decimal("0")
            agirlik = Decimal("0")
            for fatura in faturalar:
                if fatura.fatura_no == haric_fatura_no:
                    continue
                acik = AlisFaturasiService.toplam(fatura.satirlar)["genel_toplam"] - fatura.odeme_tutari
                if acik > 0:
                    bakiye += acik
                    agirlik += Decimal(fatura.vade_tarihi.toordinal()) * acik
            for h in hs:
                if h.belge_no in fatura_nolari or h.belge_no == haric_fatura_no:
                    continue
                if not str(h.belge_no).startswith(("AFAT-", "ARAY")):
                    continue
                bakiye += h.kalan_acik_tutar
                agirlik += Decimal(h.satis_tarihi.toordinal()) * h.kalan_acik_tutar
            bakiye += eklenecek
            if eklenecek > 0:
                agirlik += Decimal((vade or date.today()).toordinal()) * eklenecek
            return {"bakiye": bakiye, "ortalama_vade": date.fromordinal(int(agirlik / bakiye)) if bakiye > 0 else None}

    @staticmethod
    def otomatik_lot_no(firma_adi, tarih=None):
        onek = "".join(c for c in (firma_adi or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{(tarih or date.today()):%Y%m%d}"

    @staticmethod
    def fatura_no():
        """ARAY000001 formatında artan alış fatura numarası."""
        onek = "ARAY"
        with get_session() as session:
            numaralar = session.scalars(
                select(AlisFaturasi.fatura_no).where(AlisFaturasi.fatura_no.like(f"{onek}%"))
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek):]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:06d}"
