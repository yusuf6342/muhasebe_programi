"""Otomatik / sonradan muhasebeleştirme: firma ve evrak türü ayarları, belge durumu, toplu işlem.

Fişi her zaman ``MuhasebeEntegrasyonService`` üretir (tek fiş üretim noktası). Bu servis yalnız
*ne zaman* üretileceğine karar verir ve kaynak evrakın muhasebeleştirme durumunu tutar:

- Genel muhasebe kapalı: evrak fiş üretmez, durum kaydı tutulmaz.
- Otomatik: fiş evrakla aynı transaction'da yazılır; yazılamazsa evrak da kaydedilmez.
- Sonradan: evrak ön muhasebede kesinleşir, durum "Bekliyor" olur; fiş "Muhasebeleştirilecek
  Evraklar" ekranından tek tek veya toplu oluşturulur (ön muhasebe hareketleri yeniden üretilmez).

Muhasebeleştirme kimliği firma + evrak türü + kalıcı evrak id'sidir (``uq_mhl_belge``); fiş tarafında
``uq_mh_kaynak`` aynı kaynağa ikinci etkin fişi veritabanı düzeyinde engeller.
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select, text, update

from database.database import get_session
from database.models.genel_muhasebe import (
    BELGE_BEKLIYOR,
    BELGE_DURUMLARI,
    BELGE_HATALI,
    BELGE_INCELEME,
    BELGE_IPTAL,
    BELGE_ISLENEBILIR,
    BELGE_MUHASEBE_DISI,
    BELGE_MUHASEBELESTIRILDI,
    FIRMA_GENELI,
    YONTEM_OTOMATIK,
    YONTEM_SONRADAN,
    YONTEM_VARSAYILAN,
    MuhasebeBelgeDurumu,
    MuhasebeFisi,
    MuhasebeHesapEsleme,
    MuhasebelestirmeAyari,
)
from database.muhasebe_entegrasyon import (
    DESTEKLENMEYEN_EVRAKLAR,
    EVRAKLAR,
    KAYNAK_EVRAK,
    MuhasebeEntegrasyonService,
)
from database.muhasebe_service import (
    MuhasebeService,
    decimal,
    kapali_donem_mi,
    kapali_donem_zorunlu_degil,
    oturum_kullan,
)
from database.session_manager import oturum

YONTEM_KAPALI = "kapali"
YONTEM_ADLARI = {
    YONTEM_OTOMATIK: "Otomatik",
    YONTEM_SONRADAN: "Sonradan",
    YONTEM_VARSAYILAN: "Firma varsayılanı",
}
AYAR_YETKISI = "muhasebelestirme_ayar"
TOPLU_YETKISI = "muhasebelestirme_toplu"

# Fiş için her durumda gereken eşleştirmeler (KDV/kasa gibi koşullu olanlar evrak anında denetlenir)
TEMEL_ANAHTARLAR: dict[str, tuple[str, ...]] = {
    "satis_faturasi": ("musteriler", "yurtici_satislar", "hesaplanan_kdv"),
    "satis_iade": ("musteriler", "yurtici_satislar", "hesaplanan_kdv"),
    "alis_faturasi": ("ticari_mallar", "tedarikciler", "indirilecek_kdv"),
    "alis_iade": ("ticari_mallar", "tedarikciler", "indirilecek_kdv"),
    "hizmet_faturasi": ("giderler", "tedarikciler", "indirilecek_kdv"),
    "gider_fisi": ("giderler", "kasa"),
    "cari_tahsilat": ("musteriler", "kasa"),
    "cari_odeme": ("tedarikciler", "kasa"),
    "kasa_makbuzu": ("musteriler", "kasa"),
    # Banka tarafı kart bazında (banka kartı → Muhasebe Hesabı) çözülür; evrak anında denetlenir
    "kasa_banka_virman": ("kasa",),
    "banka_havale": ("musteriler",),
    "cari_virman": ("musteriler",),
    "cari_virman_makbuzu": ("musteriler", "tedarikciler"),
    # Finans İşlem Ayarları'na bağlı evraklar: gereken hesap / seçenek evrak anında denetlenir
    # (eksikse evrak "İnceleme gerekiyor" kalır, açıklamada ayarın yeri yazar).
    "pos_tahsilat": (),
    "kart_odeme": (),
    "pos_valor_aktarimi": (),
    "cek_senet": (),
    "banka_kredi_kullandirim": (),
    "banka_kredi_odeme": (),
    "kur_farki": (),
}

KESINLESME_OLAYLARI = {t["fn"]: evrak for evrak, t in EVRAKLAR.items()}
IPTAL_OLAYLARI = {
    "satis_faturasi_iptal": "satis_faturasi",
    "alis_faturasi_iptal": "alis_faturasi",
    "gider_fisi_iptal": "gider_fisi",
    "cari_tahsilat_iptal": "cari_tahsilat",
    "cari_odeme_iptal": "cari_odeme",
    "kasa_makbuzu_iptal": "kasa_makbuzu",
    "cari_virman_iptal": "cari_virman",
    "cari_virman_makbuzu_iptal": "cari_virman_makbuzu",
    "pos_tahsilat_iptal": "pos_tahsilat",
    "kart_odeme_iptal": "kart_odeme",
    "cek_senet_iptal": "cek_senet",
    "banka_kredi_odeme_iptal": "banka_kredi_odeme",
    "kur_farki_iptal": "kur_farki",
}


class ZatenCalisiyor(RuntimeError):
    pass


def _kullanici() -> tuple[int | None, str | None]:
    return oturum.user_id, (oturum.kullanici_adi or oturum.ad_soyad)


class MuhasebelestirmeService:
    _hazir_motorlar: set[int] = set()
    _toplu_kilit = threading.Lock()

    # ================================================================ şema / geçiş
    @staticmethod
    def _motor_anahtari(session) -> str:
        bind = session.get_bind()
        return f"{id(bind)}|{bind.url}"

    @staticmethod
    def _tablolar_hazirla(session) -> None:
        from database.models.genel_muhasebe import (
            HesapPlani,
            KurFarkiKaydi,
            MuhasebeFinansAyari,
            MuhasebeFisiSatiri,
            MuhasebeIslemGecmisi,
        )

        from database.models.finans import FinansEvrakKimligi

        baglanti = session.connection()
        for model in (HesapPlani, MuhasebeFisi, MuhasebeFisiSatiri, MuhasebeHesapEsleme,
                      MuhasebeIslemGecmisi, MuhasebelestirmeAyari, MuhasebeBelgeDurumu, FinansEvrakKimligi,
                      MuhasebeFinansAyari, KurFarkiKaydi):
            model.__table__.create(bind=baglanti, checkfirst=True)
        mevcut_idx = {r[1] for r in baglanti.execute(text("PRAGMA index_list('muhasebe_belge_durumlari')"))}
        for idx in MuhasebeBelgeDurumu.__table__.indexes:
            if idx.name not in mevcut_idx:
                idx.create(bind=baglanti)
        MuhasebelestirmeService._fis_kaynak_indeksi(session)

    @staticmethod
    def _fis_kaynak_indeksi(session) -> None:
        """Eski DB'lerde muhasebe_fisleri kaynak benzersizliği yoksa ekler (mükerrer yoksa)."""
        baglanti = session.connection()
        for idx in baglanti.execute(text("PRAGMA index_list('muhasebe_fisleri')")).fetchall():
            if not idx[2]:  # unique değil
                continue
            kolonlar = [r[2] for r in baglanti.execute(text(f"PRAGMA index_info('{idx[1]}')")).fetchall()]
            if kolonlar == ["firma_id", "kaynak_turu", "kaynak_id"]:
                return
        mukerrer = baglanti.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT 1 FROM muhasebe_fisleri WHERE kaynak_turu IS NOT NULL "
                "GROUP BY firma_id, kaynak_turu, kaynak_id HAVING COUNT(*) > 1)"
            )
        ).scalar()
        if mukerrer:
            baglanti.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_mh_fis_kaynak "
                    "ON muhasebe_fisleri (firma_id, kaynak_turu, kaynak_id)"
                )
            )
            return
        baglanti.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_mh_fis_kaynak "
                "ON muhasebe_fisleri (firma_id, kaynak_turu, kaynak_id)"
            )
        )

    @staticmethod
    def _genel_ayar(session, firma_id: int) -> MuhasebelestirmeAyari | None:
        return session.scalar(
            select(MuhasebelestirmeAyari).where(
                MuhasebelestirmeAyari.firma_id == firma_id,
                MuhasebelestirmeAyari.evrak_turu == FIRMA_GENELI,
            )
        )

    @staticmethod
    def _session_db_yolu(session) -> Path | None:
        yol = session.get_bind().url.database
        return Path(yol) if yol and yol != ":memory:" else None

    @staticmethod
    def _gecis_veri_yazar(session, firma_id: int) -> bool:
        """İlk geçiş geçmiş evrak durumları yazacak mı (genel muhasebe kullanılmış firma)."""
        if MuhasebelestirmeService._eslesme_var_mi(session, firma_id):
            return True
        return bool(session.scalar(select(func.count()).select_from(MuhasebeFisi).where(
            MuhasebeFisi.firma_id == firma_id)))

    @staticmethod
    def hazirla(session, *, yeni_firma: bool = False) -> None:
        """Tablolar + (gerekirse) ilk geçiş; verilen transaction içinde, idempotent.

        Genel muhasebe kullanılmış mevcut bir veritabanında ilk geçiş ancak bu süreçte alınmış
        doğrulanmış yedek varken (``schema_hazirla`` / açılış geçişi) çalışır.
        """
        anahtar = MuhasebelestirmeService._motor_anahtari(session)
        if anahtar not in MuhasebelestirmeService._hazir_motorlar:
            MuhasebelestirmeService._tablolar_hazirla(session)
        firma_id = MuhasebeService.yerel_firma_id(session)
        if MuhasebelestirmeService._genel_ayar(session, firma_id) is None:
            if not yeni_firma and MuhasebelestirmeService._gecis_veri_yazar(session, firma_id):
                from database.gecis_guvenligi import GecisYedekHatasi, yedek_onayi

                db_yolu = MuhasebelestirmeService._session_db_yolu(session)
                if db_yolu is not None and yedek_onayi(db_yolu) is None:
                    raise GecisYedekHatasi(
                        "muhasebeleştirme geçişi doğrulanmış yedek alınmadan çalıştırılamaz "
                        "(açılış geçişi yapılmamış)"
                    )
            MuhasebelestirmeService._gecis(session, firma_id, yeni_firma=yeni_firma)
        MuhasebelestirmeService._hazir_motorlar.add(anahtar)

    @staticmethod
    def schema_hazirla(*, yeni_firma: bool = False) -> Path | None:
        """Uygulama açılışı / firma seçimi: tablolar, eski DB indeksleri ve ilk geçiş.

        Mevcut veritabanında geçiş gerekiyorsa önce doğrulanmış SQLite yedeği alınır; yedek
        alınamazsa ``GecisYedekHatasi`` (geçiş başlamaz), geçiş yarıda kalırsa veritabanı yedekten
        geri yüklenir (``GecisHatasi``). Dönüş: alınan yedeğin yolu (yoksa None).
        """
        from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

        db_yolu = MuhasebelestirmeService._db_yolu()

        def calistir() -> None:
            with get_session() as session:
                MuhasebelestirmeService._hazir_motorlar.discard(
                    MuhasebelestirmeService._motor_anahtari(session)
                )
                MuhasebelestirmeService.hazirla(session, yeni_firma=yeni_firma)

        gerekli = not yeni_firma and MuhasebelestirmeService.gecis_gerekli_mi()
        if gerekli and yedek_onayi(db_yolu) is not None:
            # Daha geniş bir açılış geçişinin (main.baslatma_adimlari) içindeyiz: yedek ve geri dönüş orada
            calistir()
            return yedek_onayi(db_yolu).yol
        _, yedek = guvenli_gecis(
            db_yolu, calistir, gerekli=gerekli, etiket="muhasebelestirme_gecis",
            baglantilari_kapat=MuhasebelestirmeService._baglantilari_kapat,
        )
        return yedek.yol if yedek else None

    @staticmethod
    def _baglantilari_kapat() -> None:
        import database.database as veritabani

        MuhasebelestirmeService._hazir_motorlar.clear()
        motor = getattr(veritabani.company_db, "_engine", None) or veritabani.engine
        if motor is not None:
            motor.dispose()

    @staticmethod
    def gecis_gerekli_mi() -> bool:
        with get_session() as session:
            baglanti = session.connection()
            var = baglanti.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='muhasebe_muhasebelestirme_ayarlari'")
            ).first()
            if var is None:
                return True
            firma_id = MuhasebeService.yerel_firma_id(session)
            return MuhasebelestirmeService._genel_ayar(session, firma_id) is None

    @staticmethod
    def _db_yolu() -> Path:
        """Etkin oturumun bağlı olduğu veritabanı dosyası (yedek bu dosyadan alınır)."""
        from database.database import DB_PATH

        with get_session() as session:
            yol = MuhasebelestirmeService._session_db_yolu(session)
        return yol if yol else Path(DB_PATH)

    @staticmethod
    def gecis_oncesi_yedek(db_yolu: Path | None = None) -> Path:
        """SQLite backup API ile tarihli yedek; bütünlük ve tablo satır sayıları doğrulanır."""
        from database.gecis_guvenligi import dogrulanmis_yedek

        db = Path(db_yolu) if db_yolu else MuhasebelestirmeService._db_yolu()
        return dogrulanmis_yedek(db, "muhasebelestirme_gecis").yol

    @staticmethod
    def _eslesme_var_mi(session, firma_id: int) -> bool:
        return bool(
            session.scalar(
                select(func.count()).select_from(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.firma_id == firma_id,
                    MuhasebeHesapEsleme.hesap_id.is_not(None),
                )
            )
        )

    @staticmethod
    def evrak_bugun_fis_uretebilir_mi(session, evrak: str) -> bool:
        """Bugünkü eşleştirmelerle bu evrak türü fiş üretebiliyor mu (temel hesaplar geçerli mi)."""
        return all(
            MuhasebeEntegrasyonService.esleme_sorunu(a, session=session) is None
            for a in TEMEL_ANAHTARLAR[evrak]
        )

    @staticmethod
    def _gecis(session, firma_id: int, *, yeni_firma: bool) -> None:
        """Mevcut çalışma biçimini koruyan ilk ayar.

        - Yeni firma veya genel muhasebe hiç kullanılmamış (eşleştirme/fiş yok): GM kapalı,
          açıldığında varsayılan "Sonradan".
        - Eşleştirme yapılmış firma: bugün fiş üretebilen evrak türleri "Otomatik" kalır; eşleştirmesi
          fiş yazmaya uygun olmayan (bugün fişi sessizce oluşmayan) türler "Sonradan" olur — evrak
          kesinleşmesi engellenmez, eksik fişler bekleyenler listesinde görünür.
        """
        kullanici_id, kullanici_adi = _kullanici()
        fis_var = bool(session.scalar(select(func.count()).select_from(MuhasebeFisi).where(
            MuhasebeFisi.firma_id == firma_id)))
        gm_kullan = not yeni_firma and (MuhasebelestirmeService._eslesme_var_mi(session, firma_id) or fis_var)
        calisan = {
            e: MuhasebelestirmeService.evrak_bugun_fis_uretebilir_mi(session, e) for e in EVRAKLAR
        } if gm_kullan else {}
        varsayilan = YONTEM_OTOMATIK if calisan.get("satis_faturasi") else YONTEM_SONRADAN
        if yeni_firma:
            neden = "Yeni firma: genel muhasebe kapalı; açılırsa başlangıç yöntemi Sonradan."
        elif not gm_kullan:
            neden = "Geçiş: eşleştirme ve fiş yok (genel muhasebe kullanılmıyor); davranış değişmedi."
        else:
            neden = (
                "Geçiş: bugün fiş üretebilen türler Otomatik; eşleştirmesi fişe uygun olmayan türler "
                "Sonradan (evrak engellenmez, bekleyenlerde görünür)."
            )
        session.add(
            MuhasebelestirmeAyari(
                firma_id=firma_id, evrak_turu=FIRMA_GENELI, gm_kullan=gm_kullan, yontem=varsayilan,
                kaynak="yeni_firma" if yeni_firma else "gecis", aciklama=neden,
                guncelleyen_kullanici_id=kullanici_id, guncelleyen_kullanici_adi=kullanici_adi,
            )
        )
        ozet = []
        for evrak, calisiyor in calisan.items():
            tur_yontem = YONTEM_OTOMATIK if calisiyor else YONTEM_SONRADAN
            ozet.append(f"{evrak}={tur_yontem}")
            if tur_yontem != varsayilan:
                session.add(
                    MuhasebelestirmeAyari(
                        firma_id=firma_id, evrak_turu=evrak, gm_kullan=True, yontem=tur_yontem,
                        kaynak="gecis", aciklama="Geçiş: eşleştirme durumuna göre",
                        guncelleyen_kullanici_id=kullanici_id, guncelleyen_kullanici_adi=kullanici_adi,
                    )
                )
        session.flush()
        MuhasebeService._gecmis(
            session, kayit_turu="muhasebelestirme_ayari", kayit_id=0, islem="gecis",
            detay=f"gm_kullan={gm_kullan} varsayilan={varsayilan} {' '.join(ozet)} | {neden}",
        )
        if gm_kullan:
            MuhasebelestirmeService._gecmis_tara(session, firma_id)

    # ================================================================ geçmiş evraklar
    @staticmethod
    def _etkin_fis_haritasi(session, firma_id: int) -> dict[tuple[str, int], int]:
        harita: dict[tuple[str, int], int] = {}
        for kaynak_turu, kaynak_id, fis_id in session.execute(
            select(MuhasebeFisi.kaynak_turu, MuhasebeFisi.kaynak_id, MuhasebeFisi.id).where(
                MuhasebeFisi.firma_id == firma_id,
                MuhasebeFisi.kaynak_turu.is_not(None),
                MuhasebeFisi.durum != "İptal",
            )
        ):
            evrak = KAYNAK_EVRAK.get(kaynak_turu)
            if evrak is None or kaynak_id is None:
                continue
            anahtar = (evrak, int(kaynak_id))
            # Ana fiş (evrakın ilk kaynağı) tahsilat/ödeme fişine tercih edilir
            if anahtar not in harita or kaynak_turu == EVRAKLAR[evrak]["kaynaklar"][0]:
                harita[anahtar] = int(fis_id)
        return harita

    @staticmethod
    def _kesin_evraklar(session) -> list[dict]:
        """Bağlantıyla tanınabilen kesinleşmiş evraklar (taslak/iptal hariç)."""
        from database.models.alis_faturasi import AlisFaturasi
        from database.models.alis_iade_faturasi import AlisIadeFaturasi
        from database.models.cari import Cari
        from database.models.finans import GiderFisi
        from database.models.hizmet_faturasi import HizmetFaturasi
        from database.models.satis_faturasi import SatisFaturasi
        from database.models.satis_iade_faturasi import SatisIadeFaturasi

        from sqlalchemy.exc import OperationalError

        sonuc: list[dict] = []

        def ekle(evrak, sorgu):
            try:
                rows = session.execute(sorgu).all()
            except OperationalError:  # modül tablosu bu DB'de yok
                return
            for r in rows:
                sonuc.append({
                    "evrak_turu": evrak, "kaynak_id": int(r[0]), "belge_no": r[1], "belge_tarihi": r[2],
                    "cari_id": r[3], "cari_adi": r[4], "tutar": decimal(r[5] or 0), "para_birimi": r[6] or "TRY",
                })

        ekle("satis_faturasi",
             select(SatisFaturasi.id, SatisFaturasi.fatura_no, SatisFaturasi.fatura_tarihi, SatisFaturasi.cari_id,
                    Cari.unvan, SatisFaturasi.tl_genel_toplam, SatisFaturasi.para_birimi)
             .join(Cari, Cari.id == SatisFaturasi.cari_id, isouter=True)
             .where(SatisFaturasi.onaylandi.is_(True), SatisFaturasi.durum != "İPTAL",
                    SatisFaturasi.is_deleted.is_(False)))
        ekle("alis_faturasi",
             select(AlisFaturasi.id, AlisFaturasi.fatura_no, AlisFaturasi.fatura_tarihi, AlisFaturasi.cari_id,
                    Cari.unvan, AlisFaturasi.tl_genel_toplam, AlisFaturasi.para_birimi)
             .join(Cari, Cari.id == AlisFaturasi.cari_id, isouter=True)
             .where(AlisFaturasi.durum != "İPTAL"))
        ekle("hizmet_faturasi",
             select(HizmetFaturasi.id, HizmetFaturasi.fatura_no, HizmetFaturasi.fatura_tarihi,
                    HizmetFaturasi.cari_id, Cari.unvan, HizmetFaturasi.tl_genel_toplam, HizmetFaturasi.para_birimi)
             .join(Cari, Cari.id == HizmetFaturasi.cari_id, isouter=True)
             .where(HizmetFaturasi.durum != "İPTAL"))
        from database.models.finans import FinansHesabi

        ekle("gider_fisi",
             select(GiderFisi.id, GiderFisi.belge_no, GiderFisi.tarih, text("NULL"), FinansHesabi.hesap_adi,
                    GiderFisi.tutar, text("'TRY'"))
             .join(FinansHesabi, FinansHesabi.id == GiderFisi.finans_hesap_id, isouter=True)
             .where(GiderFisi.durum.not_in(("IPTAL", "İPTAL")), GiderFisi.gider_turu == "HIZMET"))
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        for evrak, model, servis in (
            ("satis_iade", SatisIadeFaturasi, SatisIadeFaturasiService),
            ("alis_iade", AlisIadeFaturasi, AlisIadeFaturasiService),
        ):
            try:
                iadeler = session.scalars(select(model).where(model.durum.not_in(("İPTAL", "TASLAK")))).all()
            except OperationalError:
                continue
            for f in iadeler:
                cari = session.get(Cari, f.cari_id)
                sonuc.append({
                    "evrak_turu": evrak, "kaynak_id": int(f.id), "belge_no": f.iade_no,
                    "belge_tarihi": f.iade_tarihi, "cari_id": f.cari_id,
                    "cari_adi": cari.unvan if cari else None,
                    "tutar": decimal(servis.toplam(f.satirlar)["genel_toplam"]),
                    "para_birimi": f.para_birimi or "TRY",
                })
        return sonuc

    @staticmethod
    def _gecmis_tara(session, firma_id: int) -> dict[str, int]:
        """Durum kaydı olmayan kesinleşmiş evraklara durum yazar; fiş üretmez, mevcutlara dokunmaz.

        Bağlı (kaynak id'li) etkin fişi olan → Muhasebeleştirildi; olmayan → İnceleme gerekiyor
        (başka yolla muhasebeleşmiş olabilir; evrak no/açıklama ile eşleştirme yapılmaz).
        Cari tahsilat/ödeme geçmişi bu taramaya girmez: kart tahsilatı ile diğer cari hareketler
        kalıcı bir türe göre ayrılamıyor.
        """
        mevcut = {
            (e, int(k)) for e, k in session.execute(
                select(MuhasebeBelgeDurumu.evrak_turu, MuhasebeBelgeDurumu.kaynak_id).where(
                    MuhasebeBelgeDurumu.firma_id == firma_id)
            )
        }
        fisler = MuhasebelestirmeService._etkin_fis_haritasi(session, firma_id)
        kullanici_id, kullanici_adi = _kullanici()
        simdi = datetime.now()
        sayac = {BELGE_MUHASEBELESTIRILDI: 0, BELGE_INCELEME: 0}
        yeni = []
        for b in MuhasebelestirmeService._kesin_evraklar(session):
            anahtar = (b["evrak_turu"], b["kaynak_id"])
            if anahtar in mevcut:
                continue
            fis_id = fisler.get(anahtar)
            durum = BELGE_MUHASEBELESTIRILDI if fis_id else BELGE_INCELEME
            sayac[durum] += 1
            yeni.append({
                **b, "firma_id": firma_id, "durum": durum, "fis_id": fis_id,
                "aciklama": None if fis_id else (
                    "Geçiş öncesi evrak: bağlı muhasebe fişi yok. Başka yolla muhasebeleşmiş olabilir; "
                    "kontrol edip muhasebeleştirin veya muhasebe dışı bırakın."),
                "yontem": None, "deneme_sayisi": 0, "row_version": 1,
                "olusturma_tarihi": simdi, "guncelleme_tarihi": simdi,
                "guncelleyen_kullanici_id": kullanici_id, "guncelleyen_kullanici_adi": kullanici_adi,
            })
        if yeni:
            session.execute(MuhasebeBelgeDurumu.__table__.insert(), yeni)
        MuhasebeService._gecmis(
            session, kayit_turu="muhasebelestirme_ayari", kayit_id=0, islem="gecmis_tara",
            detay=f"muhasebelestirildi={sayac[BELGE_MUHASEBELESTIRILDI]} inceleme={sayac[BELGE_INCELEME]}",
        )
        return {"muhasebelestirildi": sayac[BELGE_MUHASEBELESTIRILDI], "inceleme": sayac[BELGE_INCELEME]}

    @staticmethod
    def gecmis_tara() -> dict[str, int]:
        """Elle: durum kaydı olmayan geçmiş evrakları listeye ekler (fiş üretmez)."""
        from database.access import yazma_zorunlu

        yazma_zorunlu(AYAR_YETKISI, TOPLU_YETKISI)
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            return MuhasebelestirmeService._gecmis_tara(session, MuhasebeService.yerel_firma_id(session))

    @staticmethod
    def gecmis_finans_onizle() -> dict[str, dict[str, list[dict]]]:
        """Geçmiş tahsilat/ödeme/makbuz/havale/virman evrakları: kesin / belirsiz / karar bekliyor /
        muhasebeleştirilmiş / listede. Hiçbir şey yazmaz."""
        from database.access import yetki_zorunlu
        from database.muhasebelestirme_gecmis_finans import onizle

        yetki_zorunlu("muhasebe_goruntuleme", AYAR_YETKISI, "goruntuleme")
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            return onizle(session, MuhasebeService.yerel_firma_id(session))

    @staticmethod
    def gecmis_finans_ekle(secimler: list[tuple[str, Any]]) -> dict[str, Any]:
        """Kullanıcının seçtiği kesin geçmiş evrakları bekleyenlere alır (fiş üretmez).

        Seçim önizlemeyle yeniden doğrulanır: belirsiz, karar bekleyen, zaten muhasebeleştirilmiş
        veya listede olan kayıt alınmaz; bağlı fiş varken ikinci fiş yolu açılmaz.
        """
        from database.access import yazma_zorunlu
        from database.muhasebelestirme_gecmis_finans import kaynak_id_hazirla, onizle

        yazma_zorunlu(AYAR_YETKISI, TOPLU_YETKISI)
        eklenen, reddedilen = [], []
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            if not MuhasebelestirmeService._genel_ayar(session, firma_id).gm_kullan:
                raise ValueError("Genel muhasebe kapalı; geçmiş evrak listeye alınamaz.")
            durum_haritasi = {
                e: {k: (kat, kayit) for kat, liste in kategoriler.items() for kayit in liste
                    for k in (kayit["anahtar"],)}
                for e, kategoriler in onizle(session, firma_id).items()
            }
            for evrak, anahtar in secimler:
                kat, kayit = durum_haritasi.get(evrak, {}).get(anahtar, (None, None))
                if kat != "kesin":
                    neden = {None: "kayıt bulunamadı", "belirsiz": "kaynak evrak kanıtlanamıyor",
                             "karar_bekliyor": "iş kuralı karar bekliyor",
                             "muhasebelestirilmis": "zaten muhasebeleştirilmiş",
                             "listede": "zaten listede"}[kat]
                    reddedilen.append({"evrak_turu": evrak, "anahtar": anahtar,
                                       "neden": f"{neden}" + (f" ({kayit['neden']})" if kayit and kayit["neden"] else "")})
                    continue
                kaynak_id = kaynak_id_hazirla(session, evrak, anahtar)
                if MuhasebeEntegrasyonService.evrak_fis_idleri(evrak, kaynak_id, session=session):
                    reddedilen.append({"evrak_turu": evrak, "anahtar": anahtar, "neden": "bağlı fiş var"})
                    continue
                MuhasebelestirmeService._durum_yaz(
                    session, evrak, kaynak_id, BELGE_BEKLIYOR, yontem=YONTEM_SONRADAN,
                    aciklama="Geçmiş evrak: kullanıcı seçimiyle bekleyenlere alındı.")
                MuhasebelestirmeService._iz(session, evrak, kaynak_id, "gecmis_listeye_al", f"anahtar={anahtar}")
                eklenen.append({"evrak_turu": evrak, "anahtar": anahtar, "kaynak_id": kaynak_id})
        return {"eklenen": eklenen, "reddedilen": reddedilen}

    # ================================================================ ayarlar
    @staticmethod
    def _ayar_satirlari(session, firma_id: int) -> dict[str, MuhasebelestirmeAyari]:
        return {
            a.evrak_turu: a for a in session.scalars(
                select(MuhasebelestirmeAyari).where(MuhasebelestirmeAyari.firma_id == firma_id))
        }

    @staticmethod
    def yontem(evrak_turu: str, *, session=None) -> str:
        """``kapali`` | ``otomatik`` | ``sonradan`` (seçili firma için)."""
        with oturum_kullan(session) as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            satirlar = MuhasebelestirmeService._ayar_satirlari(session, firma_id)
            genel = satirlar[FIRMA_GENELI]
            if not genel.gm_kullan:
                return YONTEM_KAPALI
            tur = satirlar.get(evrak_turu)
            if tur is not None and tur.yontem in (YONTEM_OTOMATIK, YONTEM_SONRADAN):
                return tur.yontem
            return genel.yontem

    @staticmethod
    def ayarlar() -> dict:
        from database.access import yetki_zorunlu

        yetki_zorunlu("muhasebe_goruntuleme", AYAR_YETKISI, "goruntuleme")
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            satirlar = MuhasebelestirmeService._ayar_satirlari(session, firma_id)
            genel = satirlar[FIRMA_GENELI]
            turler = []
            for evrak, t in EVRAKLAR.items():
                ayar = satirlar.get(evrak)
                secim = ayar.yontem if ayar is not None else YONTEM_VARSAYILAN
                etkin = secim if secim in (YONTEM_OTOMATIK, YONTEM_SONRADAN) else genel.yontem
                eksik = [
                    m for a in TEMEL_ANAHTARLAR[evrak]
                    if (m := MuhasebeEntegrasyonService.esleme_sorunu(a, session=session))
                ]
                turler.append({
                    "evrak_turu": evrak, "ad": t["ad"], "kesinlesme": t["kesinlesme"], "secim": secim,
                    "etkin": etkin if genel.gm_kullan else YONTEM_KAPALI, "eslesme_sorunlari": eksik,
                })
            return {
                "gm_kullan": bool(genel.gm_kullan),
                "varsayilan": genel.yontem,
                "kaynak": genel.kaynak,
                "aciklama": genel.aciklama,
                "guncelleyen": genel.guncelleyen_kullanici_adi,
                "guncelleme_tarihi": genel.guncelleme_tarihi,
                "turler": turler,
                "desteklenmeyen": list(DESTEKLENMEYEN_EVRAKLAR),
            }

    @staticmethod
    def ayar_kaydet(*, gm_kullan: bool, varsayilan: str, turler: dict[str, str] | None = None) -> dict:
        """Yalnız seçili firmanın ayarını değiştirir; geçmiş evrak ve mevcut fişlere dokunmaz.

        GM kapalıdan açığa geçilirse yalnız durum kaydı olmayan geçmiş evraklar "İnceleme gerekiyor"
        olarak listeye eklenir (fiş üretilmez).
        """
        from database.access import yazma_zorunlu

        yazma_zorunlu(AYAR_YETKISI, mesaj="Muhasebeleştirme ayarlarını değiştirme yetkiniz yok.")
        if varsayilan not in (YONTEM_OTOMATIK, YONTEM_SONRADAN):
            raise ValueError("Varsayılan yöntem Otomatik veya Sonradan olmalı.")
        turler = dict(turler or {})
        for evrak, y in turler.items():
            if evrak not in EVRAKLAR:
                raise ValueError(f"Desteklenmeyen evrak türü: {evrak}")
            if y not in (YONTEM_OTOMATIK, YONTEM_SONRADAN, YONTEM_VARSAYILAN):
                raise ValueError(f"Geçersiz yöntem: {y}")
        kullanici_id, kullanici_adi = _kullanici()
        tarama = None
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            satirlar = MuhasebelestirmeService._ayar_satirlari(session, firma_id)
            genel = satirlar[FIRMA_GENELI]
            once = (bool(genel.gm_kullan), genel.yontem,
                    {e: a.yontem for e, a in satirlar.items() if e != FIRMA_GENELI})
            acildi = gm_kullan and not genel.gm_kullan
            genel.gm_kullan = bool(gm_kullan)
            genel.yontem = varsayilan
            genel.kaynak = "kullanici"
            genel.aciklama = None
            genel.guncelleyen_kullanici_id = kullanici_id
            genel.guncelleyen_kullanici_adi = kullanici_adi
            genel.guncelleme_tarihi = datetime.now()
            for evrak, y in turler.items():
                ayar = satirlar.get(evrak)
                if ayar is None:
                    ayar = MuhasebelestirmeAyari(firma_id=firma_id, evrak_turu=evrak, gm_kullan=True, yontem=y)
                    session.add(ayar)
                ayar.yontem = y
                ayar.kaynak = "kullanici"
                ayar.guncelleyen_kullanici_id = kullanici_id
                ayar.guncelleyen_kullanici_adi = kullanici_adi
                ayar.guncelleme_tarihi = datetime.now()
            session.flush()
            sonra = (bool(genel.gm_kullan), genel.yontem,
                     {e: a.yontem for e, a in MuhasebelestirmeService._ayar_satirlari(session, firma_id).items()
                      if e != FIRMA_GENELI})
            MuhasebeService._gecmis(
                session, kayit_turu="muhasebelestirme_ayari", kayit_id=0, islem="ayar_degistir",
                detay=f"önce gm={once[0]} varsayilan={once[1]} turler={once[2]} → "
                      f"sonra gm={sonra[0]} varsayilan={sonra[1]} turler={sonra[2]}",
            )
            if acildi:
                tarama = MuhasebelestirmeService._gecmis_tara(session, firma_id)
        return {"gecmis_tarama": tarama}

    # ================================================================ evrak bilgisi
    @staticmethod
    def belge_bilgisi(session, evrak: str, kaynak_id: int) -> dict | None:
        """Evrakın güncel hali: no, tarih, cari, TL tutar, para birimi, iptal/kesin durumu."""
        from database.models.cari import Cari, CariIslem

        def cari_adi(cid):
            c = session.get(Cari, cid) if cid else None
            return c.unvan if c else None

        kid = int(kaynak_id)
        if evrak == "satis_faturasi":
            from database.models.satis_faturasi import SatisFaturasi

            f = session.get(SatisFaturasi, kid)
            if f is None:
                return None
            return {"no": f.fatura_no, "tarih": f.fatura_tarihi, "cari_id": f.cari_id, "cari_adi": cari_adi(f.cari_id),
                    "tutar": decimal(f.tl_genel_toplam or 0), "para_birimi": f.para_birimi or "TRY",
                    "iptal": f.durum == "İPTAL" or bool(getattr(f, "is_deleted", False)),
                    "kesin": bool(f.onaylandi)}
        if evrak in ("alis_faturasi", "hizmet_faturasi"):
            if evrak == "alis_faturasi":
                from database.models.alis_faturasi import AlisFaturasi as M
            else:
                from database.models.hizmet_faturasi import HizmetFaturasi as M
            f = session.get(M, kid)
            if f is None:
                return None
            return {"no": f.fatura_no, "tarih": f.fatura_tarihi, "cari_id": f.cari_id, "cari_adi": cari_adi(f.cari_id),
                    "tutar": decimal(f.tl_genel_toplam or 0), "para_birimi": f.para_birimi or "TRY",
                    "iptal": f.durum == "İPTAL", "kesin": True}
        if evrak in ("satis_iade", "alis_iade"):
            if evrak == "satis_iade":
                from database.models.satis_iade_faturasi import SatisIadeFaturasi as M
                from database.satis_iade_faturasi_service import SatisIadeFaturasiService as S
            else:
                from database.alis_iade_faturasi_service import AlisIadeFaturasiService as S
                from database.models.alis_iade_faturasi import AlisIadeFaturasi as M
            f = session.get(M, kid)
            if f is None:
                return None
            return {"no": f.iade_no, "tarih": f.iade_tarihi, "cari_id": f.cari_id, "cari_adi": cari_adi(f.cari_id),
                    "tutar": decimal(S.toplam(f.satirlar)["genel_toplam"]), "para_birimi": f.para_birimi or "TRY",
                    "iptal": f.durum == "İPTAL", "kesin": f.durum != "TASLAK"}
        if evrak == "gider_fisi":
            from database.models.finans import FinansHesabi, GiderFisi

            f = session.get(GiderFisi, kid)
            if f is None:
                return None
            hesap = session.get(FinansHesabi, f.finans_hesap_id) if f.finans_hesap_id else None
            return {"no": f.belge_no, "tarih": f.tarih, "cari_id": None,
                    "cari_adi": hesap.hesap_adi if hesap else None,
                    "tutar": decimal(f.tutar or 0), "para_birimi": "TRY",
                    "iptal": (f.durum or "").upper() in ("IPTAL", "İPTAL"), "kesin": True}
        if evrak in ("cari_tahsilat", "cari_odeme"):
            from database.finans_evrak_kimligi import kimlik_getir

            kimlik = kimlik_getir(session, kid, evrak)
            i = session.get(CariIslem, kimlik.cari_islem_id) if kimlik and kimlik.cari_islem_id else None
            if i is None:
                return None
            tutar = decimal(i.alacak or 0) if evrak == "cari_tahsilat" else (
                decimal(i.borc or 0) or decimal(i.alacak or 0))
            return {"no": i.belge_no, "tarih": i.tarih, "cari_id": i.cari_id, "cari_adi": cari_adi(i.cari_id),
                    "tutar": tutar, "para_birimi": "TRY", "iptal": False, "kesin": True}
        if evrak == "kasa_makbuzu":
            from database.models.finans import KasaMakbuzu

            m = session.get(KasaMakbuzu, kid)
            if m is None:
                return None
            return {"no": m.belge_no, "tarih": m.tarih, "cari_id": m.cari_id, "cari_adi": cari_adi(m.cari_id),
                    "tutar": decimal(m.tutar or 0), "para_birimi": "TRY",
                    "iptal": (m.durum or "").upper() == "IPTAL", "kesin": True}
        if evrak == "cari_virman_makbuzu":
            from database.models.finans import CariVirmanMakbuzu

            k = session.get(CariVirmanMakbuzu, kid)
            if k is None:
                return None
            return {"no": k.belge_no, "tarih": k.tarih, "cari_id": k.musteri_id,
                    "cari_adi": f"{cari_adi(k.musteri_id)} → {cari_adi(k.tedarikci_id)}",
                    "tutar": decimal(k.tutar or 0), "para_birimi": "TRY",
                    "iptal": (k.durum or "").upper() == "IPTAL", "kesin": True}
        if evrak in ("kasa_banka_virman", "banka_havale", "cari_virman"):
            from database.finans_evrak_kimligi import kimlik_getir
            from database.models.finans import FinansHareketi, FinansHesabi

            kimlik = kimlik_getir(session, kid, evrak)
            if kimlik is None:
                return None
            no = kimlik.belge_no
            if evrak == "kasa_banka_virman":
                hareketler = session.execute(
                    select(FinansHareketi.tarih, FinansHareketi.tutar, FinansHesabi.hesap_adi)
                    .join(FinansHesabi, FinansHesabi.id == FinansHareketi.hesap_id)
                    .where(FinansHareketi.belge_no == no).order_by(FinansHareketi.id)
                ).all()
                if not hareketler:
                    return {"no": no, "tarih": None, "cari_id": None, "cari_adi": None, "tutar": decimal(0),
                            "para_birimi": "TRY", "iptal": True, "kesin": True}
                return {"no": no, "tarih": hareketler[0][0], "cari_id": None,
                        "cari_adi": " → ".join(h[2] for h in hareketler[:2]),
                        "tutar": decimal(hareketler[0][1]), "para_birimi": "TRY", "iptal": False, "kesin": True}
            islemler = session.scalars(select(CariIslem).where(CariIslem.belge_no == no)
                                       .order_by(CariIslem.id)).all()
            if not islemler:
                return {"no": no, "tarih": None, "cari_id": None, "cari_adi": None, "tutar": decimal(0),
                        "para_birimi": "TRY", "iptal": True, "kesin": True}
            ilk = next((i for i in islemler if decimal(i.alacak or 0) > 0), islemler[0])
            return {"no": no, "tarih": ilk.tarih, "cari_id": ilk.cari_id,
                    "cari_adi": " → ".join(filter(None, (cari_adi(i.cari_id) for i in islemler[:2]))),
                    "tutar": decimal(ilk.alacak or 0) + decimal(ilk.borc or 0), "para_birimi": "TRY",
                    "iptal": False, "kesin": True}
        if evrak in ("pos_tahsilat", "pos_valor_aktarimi"):
            from database.models.finans import PosValorKaydi

            p = session.get(PosValorKaydi, kid)
            if p is None:
                return None
            if evrak == "pos_tahsilat":
                return {"no": p.belge_no, "tarih": p.tahsilat_tarihi, "cari_id": p.cari_id,
                        "cari_adi": cari_adi(p.cari_id), "tutar": decimal(p.brut_tutar or 0), "para_birimi": "TRY",
                        "iptal": (p.durum or "").upper() == "IPTAL", "kesin": True}
            return {"no": p.belge_no, "tarih": p.aktarim_zamani.date() if p.aktarim_zamani else p.valor_tarihi,
                    "cari_id": p.cari_id, "cari_adi": cari_adi(p.cari_id), "tutar": decimal(p.net_tutar or 0),
                    "para_birimi": "TRY", "iptal": False, "kesin": (p.durum or "").upper() == "AKTARILDI"}
        if evrak == "kart_odeme":
            from database.models.finans import KrediKartiOdeme

            o = session.get(KrediKartiOdeme, kid)
            if o is None:
                return None
            return {"no": o.belge_no, "tarih": o.tarih, "cari_id": o.cari_id, "cari_adi": cari_adi(o.cari_id),
                    "tutar": decimal(o.tutar or 0), "para_birimi": "TRY",
                    "iptal": (o.durum or "").upper() in ("IPTAL", "İPTAL"), "kesin": True}
        if evrak == "cek_senet":
            from database.models.cek_senet import CekSenetEvrak, CekSenetHareket
            from database.muhasebe_finans_ayarlari import CEK_SENET_ASAMA_ADI

            h = session.get(CekSenetHareket, kid)
            e = session.get(CekSenetEvrak, h.evrak_id) if h is not None else None
            if e is None:
                return None
            asama = MuhasebeEntegrasyonService.cek_senet_asamasi(h.islem_turu, e.islem_yonu)
            cari_id = h.ilgili_cari_id if h.islem_turu == "CIRO" and h.ilgili_cari_id else e.cari_id
            iptal = ((h.islem_turu == "KAYIT" and (e.durum or "").upper() == "IPTAL")
                     or (h.islem_turu == "CIRO" and not h.cari_hareket_id))
            return {"no": f"{e.portfoy_no} / {CEK_SENET_ASAMA_ADI.get(asama, h.islem_turu)}",
                    "tarih": MuhasebeEntegrasyonService.cek_senet_tarihi(session, h, e), "cari_id": cari_id,
                    "cari_adi": cari_adi(cari_id),
                    "tutar": decimal(e.tl_tutari or 0) if h.islem_turu == "KAYIT" else decimal(h.tutar or 0),
                    "para_birimi": "TRY", "iptal": iptal, "kesin": True}
        if evrak in ("banka_kredi_kullandirim", "banka_kredi_odeme"):
            from database.models.finans import BankaKredisi, BankaKrediOdeme

            if evrak == "banka_kredi_kullandirim":
                k = session.get(BankaKredisi, kid)
                if k is None:
                    return None
                return {"no": k.belge_no, "tarih": k.kullandirim_tarihi, "cari_id": None, "cari_adi": k.kredi_adi,
                        "tutar": decimal(k.ana_para or 0), "para_birimi": "TRY",
                        "iptal": (k.durum or "").upper() == "IPTAL", "kesin": True}
            o = session.get(BankaKrediOdeme, kid)
            if o is None:
                return None
            k = session.get(BankaKredisi, o.kredi_id)
            return {"no": o.odeme_belge_no, "tarih": o.odeme_tarihi, "cari_id": None,
                    "cari_adi": k.kredi_adi if k else None, "tutar": decimal(o.toplam or 0), "para_birimi": "TRY",
                    "iptal": (o.durum or "").upper() == "IPTAL", "kesin": True}
        if evrak == "kur_farki":
            from database.models.genel_muhasebe import KUR_FARKI_IPTAL, KurFarkiKaydi

            k = session.get(KurFarkiKaydi, kid)
            if k is None:
                return None
            return {"no": f"KF {k.kapatma_belge_no or k.kaynak_belge_no}", "tarih": k.tarih, "cari_id": k.cari_id,
                    "cari_adi": cari_adi(k.cari_id), "tutar": abs(decimal(k.kur_farki or 0)), "para_birimi": "TRY",
                    "iptal": k.durum == KUR_FARKI_IPTAL, "kesin": True}
        raise ValueError(f"Desteklenmeyen evrak türü: {evrak}")

    # ================================================================ durum kaydı
    @staticmethod
    def _durum(session, firma_id: int, evrak: str, kaynak_id: int) -> MuhasebeBelgeDurumu | None:
        return session.scalar(
            select(MuhasebeBelgeDurumu).where(
                MuhasebeBelgeDurumu.firma_id == firma_id,
                MuhasebeBelgeDurumu.evrak_turu == evrak,
                MuhasebeBelgeDurumu.kaynak_id == int(kaynak_id),
            )
        )

    @staticmethod
    def _durum_yaz(
        session, evrak: str, kaynak_id: int, durum: str, *, fis_id: int | None = None,
        aciklama: str | None = None, yontem: str | None = None, bilgi: dict | None = None,
        deneme_artir: bool = False,
    ) -> MuhasebeBelgeDurumu:
        firma_id = MuhasebeService.yerel_firma_id(session)
        kayit = MuhasebelestirmeService._durum(session, firma_id, evrak, kaynak_id)
        if kayit is None:
            kayit = MuhasebeBelgeDurumu(firma_id=firma_id, evrak_turu=evrak, kaynak_id=int(kaynak_id),
                                        durum=durum, row_version=1, deneme_sayisi=0)
            session.add(kayit)
        if bilgi is None:
            bilgi = MuhasebelestirmeService.belge_bilgisi(session, evrak, kaynak_id)
        if bilgi:
            kayit.belge_no = bilgi["no"]
            kayit.belge_tarihi = bilgi["tarih"]
            kayit.cari_id = bilgi["cari_id"]
            kayit.cari_adi = bilgi["cari_adi"]
            kayit.tutar = bilgi["tutar"]
            kayit.para_birimi = bilgi["para_birimi"]
        kayit.durum = durum
        if fis_id is not None or durum in (BELGE_BEKLIYOR,):
            kayit.fis_id = fis_id
        kayit.aciklama = (aciklama or None) and aciklama[:500]
        if yontem:
            kayit.yontem = yontem
        if deneme_artir:
            kayit.deneme_sayisi = int(kayit.deneme_sayisi or 0) + 1
        kayit.row_version = int(kayit.row_version or 0) + 1
        kayit.guncelleme_tarihi = datetime.now()
        kayit.guncelleyen_kullanici_id, kayit.guncelleyen_kullanici_adi = _kullanici()
        session.flush()
        return kayit

    @staticmethod
    def _iz(session, evrak: str, kaynak_id: int, islem: str, detay: str) -> None:
        MuhasebeService._gecmis(session, kayit_turu=f"belge:{evrak}", kayit_id=int(kaynak_id),
                                islem=islem, detay=detay)

    # ================================================================ evrak olayları
    @staticmethod
    def olay(fn_name: str, args: tuple, kwargs: dict, *, session) -> Any:
        """Evrak servisinin transaction'ı içinde kesinleşme / iptal olayı."""
        if fn_name in KESINLESME_OLAYLARI:
            return MuhasebelestirmeService._kesinlesti(
                session, KESINLESME_OLAYLARI[fn_name], int(args[0]), kwargs.get("yeniden"))
        if fn_name in IPTAL_OLAYLARI:
            neden = kwargs.get("neden") or (args[1] if len(args) > 1 else "")
            return MuhasebelestirmeService._iptal(session, IPTAL_OLAYLARI[fn_name], int(args[0]), neden)
        if fn_name == "iptal_kaynak":
            evrak = KAYNAK_EVRAK.get(args[0])
            neden = kwargs.get("neden") or (args[2] if len(args) > 2 else "")
            if evrak is None:
                return MuhasebeEntegrasyonService.iptal_kaynak(args[0], int(args[1]), neden, session=session)
            return MuhasebelestirmeService._iptal(session, evrak, int(args[1]), neden)
        fn = getattr(MuhasebeEntegrasyonService, fn_name)
        return fn(*args, session=session, **kwargs)

    @staticmethod
    def _kesinlesti(session, evrak: str, kaynak_id: int, yeniden: bool | None) -> int | None:
        yontem = MuhasebelestirmeService.yontem(evrak, session=session)
        if yontem == YONTEM_KAPALI:
            return None
        bilgi = MuhasebelestirmeService.belge_bilgisi(session, evrak, kaynak_id)
        if bilgi is None or bilgi["iptal"] or not bilgi["kesin"]:
            return None
        disi = MuhasebeEntegrasyonService.muhasebe_disi_neden(evrak, kaynak_id, session=session)
        if disi:
            if yeniden:
                for kaynak in EVRAKLAR[evrak]["kaynaklar"]:
                    MuhasebeEntegrasyonService.iptal_kaynak(
                        kaynak, kaynak_id, "Evrak değişti; ayar gereği fiş gerekmiyor", session=session)
            MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_MUHASEBE_DISI, fis_id=None,
                                               aciklama=disi, yontem=yontem, bilgi=bilgi)
            MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebe_disi", disi)
            return None
        karar = MuhasebeEntegrasyonService.karar_bekleyen_neden(evrak, kaynak_id, session=session)
        if karar:
            # İş kuralı tanımlı olmayan kalem: evrak kaydedilir, fiş tahmin edilmez; incelemeye düşer
            if yeniden:
                for kaynak in EVRAKLAR[evrak]["kaynaklar"]:
                    MuhasebeEntegrasyonService.iptal_kaynak(
                        kaynak, kaynak_id, "Evrak değişti; yeniden muhasebeleştirilecek", session=session)
            MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_INCELEME, fis_id=None,
                                               aciklama=f"Karar bekliyor: {karar}", yontem=yontem, bilgi=bilgi)
            MuhasebelestirmeService._iz(session, evrak, kaynak_id, "incelemeye_al", karar)
            return None
        fn = getattr(MuhasebeEntegrasyonService, EVRAKLAR[evrak]["fn"])
        kw = {} if yeniden is None else {"yeniden": bool(yeniden)}
        if yontem == YONTEM_OTOMATIK:
            # Hata yukarı çıkar: evrak da kaydedilmez (yarım kayıt kalmaz)
            try:
                kapali_donem_zorunlu_degil(session, bilgi["tarih"], "Evrak")
                fis_id = fn(kaynak_id, session=session, **kw)
            except ValueError as hata:
                raise ValueError(
                    f"Muhasebe fişi oluşturulamadığı için evrak kesinleştirilmedi.\n{hata}\n\n"
                    "Eşleştirmeyi düzeltin veya bu evrak türünü bilinçli olarak 'Sonradan' "
                    "yöntemine alın (Ayarlar → Muhasebeleştirme Ayarları)."
                ) from hata
            fisler = MuhasebeEntegrasyonService.evrak_fis_idleri(evrak, kaynak_id, session=session)
            fis_id = fis_id or (fisler[0] if fisler else None)
            MuhasebelestirmeService._durum_yaz(
                session, evrak, kaynak_id, BELGE_MUHASEBELESTIRILDI, fis_id=fis_id, yontem=YONTEM_OTOMATIK,
                aciklama=None if fis_id else "Tutar sıfır; fiş gerekmedi.", bilgi=bilgi,
            )
            MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebelestir",
                                        f"otomatik fis={fis_id} no={bilgi['no']}")
            return fis_id
        # Sonradan: evrak bekleyenlere alınır; evrak değiştiyse eski fiş ters kayıtla kapanır.
        firma_id = MuhasebeService.yerel_firma_id(session)
        kayit = MuhasebelestirmeService._durum(session, firma_id, evrak, kaynak_id)
        etkin = MuhasebeEntegrasyonService.evrak_fis_idleri(evrak, kaynak_id, session=session)
        if etkin and not yeniden:
            MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_MUHASEBELESTIRILDI,
                                               fis_id=etkin[0], bilgi=bilgi)
            return etkin[0]
        aciklama = None
        if etkin:
            for kaynak in EVRAKLAR[evrak]["kaynaklar"]:
                MuhasebeEntegrasyonService.iptal_kaynak(
                    kaynak, kaynak_id, "Evrak değişti; yeniden muhasebeleştirilecek", session=session)
            aciklama = "Evrak muhasebeleştirildikten sonra değişti; önceki fiş ters kayıtla kapatıldı."
        elif kayit is not None and kayit.durum == BELGE_MUHASEBE_DISI:
            return None
        MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_BEKLIYOR, aciklama=aciklama,
                                           yontem=YONTEM_SONRADAN, bilgi=bilgi)
        MuhasebelestirmeService._iz(session, evrak, kaynak_id, "bekleyene_al", f"no={bilgi['no']}")
        return None

    @staticmethod
    def _iptal(session, evrak: str, kaynak_id: int, neden: str) -> None:
        """Kaynak evrak iptali / kesinleşmenin geri alınması: etkin fiş bir kez ters kayıtla kapanır."""
        MuhasebelestirmeService.hazirla(session)
        ters = []
        for kaynak in EVRAKLAR[evrak]["kaynaklar"]:
            t = MuhasebeEntegrasyonService.iptal_kaynak(
                kaynak, kaynak_id, neden or f"Kaynak iptal: {evrak}", session=session)
            if t:
                ters.append(t)
        firma_id = MuhasebeService.yerel_firma_id(session)
        kayit = MuhasebelestirmeService._durum(session, firma_id, evrak, kaynak_id)
        if kayit is None and not ters:
            return None
        if kayit is not None and kayit.durum == BELGE_IPTAL and not ters:
            return None
        aciklama = (neden or "Evrak iptal edildi") + (
            f" — fiş ters kayıtla kapatıldı (ters fiş id {', '.join(map(str, ters))})" if ters
            else " — muhasebe fişi oluşturulmamıştı.")
        MuhasebelestirmeService._durum_yaz(
            session, evrak, kaynak_id, BELGE_IPTAL,
            fis_id=kayit.fis_id if kayit is not None else None, aciklama=aciklama)
        MuhasebelestirmeService._iz(session, evrak, kaynak_id, "iptal", aciklama)
        return None

    @staticmethod
    def masraf_kaynagi_muhasebelesti(session, kaynak_turu: str, kaynak_id: int, fis_id: int) -> None:
        """Masraf dağıtımı onayı kaynak belgenin fişini yazdıysa durum kaydını aynı transaction'da günceller."""
        evrak = KAYNAK_EVRAK.get(kaynak_turu)
        if evrak is None:
            return
        MuhasebelestirmeService.hazirla(session)
        MuhasebelestirmeService._durum_yaz(
            session, evrak, kaynak_id, BELGE_MUHASEBELESTIRILDI, fis_id=fis_id,
            aciklama="Masraf dağıtımı onayıyla birlikte muhasebeleştirildi (dağıtım bu kaydı gerektirir).",
        )
        MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebelestir", f"masraf_dagitim fis={fis_id}")

    # ================================================================ sorgular
    @staticmethod
    def belge_durumu(evrak: str, kaynak_id: int) -> dict:
        """Evrak ekranı için: durum metni ve bağlı fiş."""
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            yontem = MuhasebelestirmeService.yontem(evrak, session=session)
            kayit = MuhasebelestirmeService._durum(session, firma_id, evrak, kaynak_id)
            fis_no = None
            if kayit is not None and kayit.fis_id:
                fis = session.get(MuhasebeFisi, kayit.fis_id)
                fis_no = fis.fis_no if fis else None
            if kayit is None:
                durum = "Genel muhasebe kapalı" if yontem == YONTEM_KAPALI else "Kayıt yok"
            else:
                durum = kayit.durum
            return {"durum": durum, "fis_id": kayit.fis_id if kayit else None, "fis_no": fis_no,
                    "aciklama": kayit.aciklama if kayit else None, "yontem": yontem}

    @staticmethod
    def toplu_durum(evrak: str, kaynak_idleri) -> dict[int, str]:
        """Liste ekranları için: kaynak id → muhasebe durumu (tek indeksli sorgu, 500'lük dilimler).

        Durum kaydı olmayan evrak sözlükte yer almaz. Hata (ör. tablo yok) listeyi engellemez: boş döner.
        """
        idler = sorted({int(i) for i in kaynak_idleri if i is not None})
        if not idler:
            return {}
        try:
            with get_session() as session:
                firma_id = MuhasebeService.yerel_firma_id(session)
                sonuc: dict[int, str] = {}
                for i in range(0, len(idler), 500):
                    sonuc.update(session.execute(
                        select(MuhasebeBelgeDurumu.kaynak_id, MuhasebeBelgeDurumu.durum).where(
                            MuhasebeBelgeDurumu.firma_id == firma_id,
                            MuhasebeBelgeDurumu.evrak_turu == evrak,
                            MuhasebeBelgeDurumu.kaynak_id.in_(idler[i:i + 500]))).all())
                return {int(k): d for k, d in sonuc.items()}
        except Exception:
            return {}

    @staticmethod
    def toplu_durum_belge(evrak: str, belge_nolari) -> dict[str, str]:
        """Belge no ile listelenen finans evrakları için: belge no → muhasebe durumu (toplu sorgu).

        Kaynak id, evrakın kalıcı kimliğinden (havale/virman/cari tahsilat-ödeme) veya kendi tablosundan
        (POS tahsilatı, şirket kartı ödemesi) çözülür.
        """
        from database.models.finans import FinansEvrakKimligi, KrediKartiOdeme, PosValorKaydi

        nolar = sorted({str(n) for n in belge_nolari if n})
        if not nolar:
            return {}
        if evrak == "pos_tahsilat":
            kaynak = (PosValorKaydi.id, PosValorKaydi.belge_no, None)
        elif evrak == "kart_odeme":
            kaynak = (KrediKartiOdeme.id, KrediKartiOdeme.belge_no, None)
        else:
            kaynak = (FinansEvrakKimligi.id, FinansEvrakKimligi.belge_no, FinansEvrakKimligi.evrak_turu == evrak)
        try:
            with get_session() as session:
                firma_id = MuhasebeService.yerel_firma_id(session)
                sonuc: dict[str, str] = {}
                for i in range(0, len(nolar), 500):
                    q = (select(kaynak[1], MuhasebeBelgeDurumu.durum)
                         .join(MuhasebeBelgeDurumu, MuhasebeBelgeDurumu.kaynak_id == kaynak[0])
                         .where(MuhasebeBelgeDurumu.firma_id == firma_id,
                                MuhasebeBelgeDurumu.evrak_turu == evrak,
                                kaynak[1].in_(nolar[i:i + 500])))
                    if kaynak[2] is not None:
                        q = q.where(kaynak[2])
                    sonuc.update(session.execute(q).all())
                return sonuc
        except Exception:
            return {}

    @staticmethod
    def baslik_eki(evrak: str, kaynak_id: int | None) -> str:
        """Evrak penceresi başlığı için kısa durum metni; durum kaydı yoksa boş."""
        if not kaynak_id:
            return ""
        try:
            d = MuhasebelestirmeService.belge_durumu(evrak, int(kaynak_id))
        except Exception:
            return ""
        if d["durum"] in ("Kayıt yok", "Genel muhasebe kapalı"):
            return ""
        return f"  ·  Muhasebe: {d['durum']}" + (f" ({d['fis_no']})" if d.get("fis_no") else "")

    @staticmethod
    def fis_kaynagi(fis_id: int) -> dict | None:
        """Fişten kaynak evraka: etkin fişte kaynak alanı, iptal edilmişte durum kaydı kullanılır."""
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            fis = session.get(MuhasebeFisi, int(fis_id))
            if fis is None or fis.firma_id != firma_id:
                return None
            evrak = kaynak_id = None
            if fis.kaynak_turu and fis.kaynak_turu in KAYNAK_EVRAK:
                evrak, kaynak_id = KAYNAK_EVRAK[fis.kaynak_turu], fis.kaynak_id
            else:
                kayit = session.scalar(select(MuhasebeBelgeDurumu).where(
                    MuhasebeBelgeDurumu.firma_id == firma_id, MuhasebeBelgeDurumu.fis_id == fis.id))
                if kayit is not None:
                    evrak, kaynak_id = kayit.evrak_turu, kayit.kaynak_id
            if evrak is None:
                return None
            kayit = MuhasebelestirmeService._durum(session, firma_id, evrak, kaynak_id)
            bilgi = MuhasebelestirmeService.belge_bilgisi(session, evrak, kaynak_id)
            return {"evrak_turu": evrak, "evrak_adi": EVRAKLAR[evrak]["ad"], "kaynak_id": int(kaynak_id),
                    "belge_no": bilgi["no"] if bilgi else (kayit.belge_no if kayit else None),
                    "durum": kayit.durum if kayit else None}

    @staticmethod
    def listele(
        *, baslangic: date | None = None, bitis: date | None = None, evrak_turu: str | None = None,
        cari_id: int | None = None, cari_metni: str | None = None, durumlar: tuple[str, ...] | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        from database.access import yetki_zorunlu

        yetki_zorunlu("muhasebe_goruntuleme", TOPLU_YETKISI, "goruntuleme")
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            q = (
                select(MuhasebeBelgeDurumu, MuhasebeFisi.fis_no)
                .join(MuhasebeFisi, MuhasebeFisi.id == MuhasebeBelgeDurumu.fis_id, isouter=True)
                .where(MuhasebeBelgeDurumu.firma_id == firma_id)
            )
            if durumlar:
                q = q.where(MuhasebeBelgeDurumu.durum.in_(tuple(durumlar)))
            if baslangic:
                q = q.where(MuhasebeBelgeDurumu.belge_tarihi >= baslangic)
            if bitis:
                q = q.where(MuhasebeBelgeDurumu.belge_tarihi <= bitis)
            if evrak_turu:
                q = q.where(MuhasebeBelgeDurumu.evrak_turu == evrak_turu)
            if cari_id:
                q = q.where(MuhasebeBelgeDurumu.cari_id == int(cari_id))
            if cari_metni and cari_metni.strip():
                from database.sqlite_funcs import tr_herhangi_icerir

                q = q.where(tr_herhangi_icerir((MuhasebeBelgeDurumu.cari_adi, MuhasebeBelgeDurumu.belge_no),
                                               cari_metni))
            q = q.order_by(MuhasebeBelgeDurumu.belge_tarihi, MuhasebeBelgeDurumu.id).limit(int(limit))
            tur_sorunlari: dict[str, list[str]] = {}
            sonuc = []
            for k, fis_no in session.execute(q):
                if k.evrak_turu not in tur_sorunlari:
                    tur_sorunlari[k.evrak_turu] = [
                        m for a in TEMEL_ANAHTARLAR.get(k.evrak_turu, ())
                        if (m := MuhasebeEntegrasyonService.esleme_sorunu(a, session=session))
                    ]
                sorun = k.aciklama or ""
                if k.durum in BELGE_ISLENEBILIR and tur_sorunlari[k.evrak_turu]:
                    sorun = "; ".join(filter(None, [sorun, *tur_sorunlari[k.evrak_turu]]))
                sonuc.append({
                    "id": k.id, "evrak_turu": k.evrak_turu,
                    "evrak_adi": EVRAKLAR.get(k.evrak_turu, {}).get("ad", k.evrak_turu),
                    "kaynak_id": k.kaynak_id, "belge_no": k.belge_no, "belge_tarihi": k.belge_tarihi,
                    "cari_id": k.cari_id, "cari_adi": k.cari_adi, "tutar": decimal(k.tutar),
                    "para_birimi": k.para_birimi, "durum": k.durum, "sorun": sorun, "fis_id": k.fis_id,
                    "fis_no": fis_no, "row_version": k.row_version, "deneme_sayisi": k.deneme_sayisi,
                })
            return sonuc

    @staticmethod
    def durum_sayilari() -> dict[str, int]:
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            sayilar = dict(session.execute(
                select(MuhasebeBelgeDurumu.durum, func.count()).where(
                    MuhasebeBelgeDurumu.firma_id == firma_id).group_by(MuhasebeBelgeDurumu.durum)
            ).all())
            return {d: int(sayilar.get(d, 0)) for d in BELGE_DURUMLARI}

    @staticmethod
    def on_kontrol(durum_idleri: list[int]) -> dict:
        """Toplu işlem öncesi: seçili evrak sayısı, işlenebilir olanlar ve tespit edilen sorunlar."""
        with get_session() as session:
            MuhasebelestirmeService.hazirla(session)
            firma_id = MuhasebeService.yerel_firma_id(session)
            kayitlar = session.scalars(select(MuhasebeBelgeDurumu).where(
                MuhasebeBelgeDurumu.firma_id == firma_id,
                MuhasebeBelgeDurumu.id.in_([int(i) for i in durum_idleri]))).all()
            islenebilir = [k for k in kayitlar if k.durum in BELGE_ISLENEBILIR]
            sorunlar: list[str] = []
            atlanacak = len(kayitlar) - len(islenebilir)
            if atlanacak:
                sorunlar.append(f"{atlanacak} evrak zaten muhasebeleştirilmiş, iptal veya muhasebe dışı; atlanacak.")
            yabanci = len(set(map(int, durum_idleri))) - len(kayitlar)
            if yabanci:
                sorunlar.append(f"{yabanci} kayıt bu firmada bulunamadı; işlenmeyecek.")
            for evrak in sorted({k.evrak_turu for k in islenebilir}):
                for a in TEMEL_ANAHTARLAR.get(evrak, ()):
                    m = MuhasebeEntegrasyonService.esleme_sorunu(a, session=session)
                    if m:
                        sorunlar.append(f"{EVRAKLAR[evrak]['ad']}: {m}")
            kilitli = sum(1 for k in islenebilir if k.belge_tarihi and kapali_donem_mi(session, k.belge_tarihi))
            if kilitli:
                sorunlar.append(f"{kilitli} evrakın tarihi kapalı döneme düşüyor; tarih değiştirilmez, hata verir.")
            return {"secili": len(set(map(int, durum_idleri))), "islenebilir": len(islenebilir),
                    "sorunlar": sorunlar}

    # ================================================================ sonradan muhasebeleştirme
    @staticmethod
    def calisiyor_mu() -> bool:
        return MuhasebelestirmeService._toplu_kilit.locked()

    @staticmethod
    def muhasebelestir(
        durum_idleri: list[int] | list[tuple[int, int]],
        *,
        ilerleme: Callable[[int, int, dict], None] | None = None,
        durdur: Callable[[], bool] | None = None,
    ) -> dict:
        """Seçili evrakları tek tek muhasebeleştirir; her evrak kendi transaction'ında.

        Öğeler ``id`` veya ``(id, beklenen_row_version)``. Aynı anda ikinci toplu işlem başlatılamaz.
        Dönüş: başarılı / başarısız / atlanan sayıları ve evrak bazında sonuçlar.
        """
        from database.access import yazma_zorunlu

        yazma_zorunlu(TOPLU_YETKISI, mesaj="Toplu muhasebeleştirme yetkiniz yok.")
        if not MuhasebelestirmeService._toplu_kilit.acquire(blocking=False):
            raise ZatenCalisiyor("Muhasebeleştirme işlemi zaten çalışıyor; bitmesini bekleyin.")
        try:
            ogeler = [(int(o[0]), int(o[1])) if isinstance(o, (tuple, list)) else (int(o), None)
                      for o in durum_idleri]
            sonuc = {"basarili": 0, "basarisiz": 0, "atlanan": 0, "toplam": len(ogeler), "sonuclar": []}
            for i, (did, versiyon) in enumerate(ogeler, start=1):
                if durdur is not None and durdur():
                    sonuc["durduruldu"] = True
                    break
                durum, mesaj, fis_id = MuhasebelestirmeService._tek(did, versiyon)
                sonuc[{"basarili": "basarili", "hata": "basarisiz", "atlandi": "atlanan"}[durum]] += 1
                sonuc["sonuclar"].append({"id": did, "durum": durum, "mesaj": mesaj, "fis_id": fis_id})
                if ilerleme is not None:
                    ilerleme(i, len(ogeler), sonuc)
            return sonuc
        finally:
            MuhasebelestirmeService._toplu_kilit.release()

    @staticmethod
    def _tek(durum_id: int, beklenen_versiyon: int | None) -> tuple[str, str, int | None]:
        try:
            with get_session() as session:
                firma_id = MuhasebeService.yerel_firma_id(session)
                q = update(MuhasebeBelgeDurumu).where(
                    MuhasebeBelgeDurumu.id == int(durum_id),
                    MuhasebeBelgeDurumu.firma_id == firma_id,
                    MuhasebeBelgeDurumu.durum.in_(BELGE_ISLENEBILIR),
                )
                if beklenen_versiyon is not None:
                    q = q.where(MuhasebeBelgeDurumu.row_version == int(beklenen_versiyon))
                talep = session.execute(
                    q.values(row_version=MuhasebeBelgeDurumu.row_version + 1, guncelleme_tarihi=datetime.now())
                    .execution_options(synchronize_session=False)
                )
                kayit = session.get(MuhasebeBelgeDurumu, int(durum_id))
                if kayit is None or kayit.firma_id != firma_id:
                    return "atlandi", "Kayıt bu firmada bulunamadı.", None
                session.refresh(kayit)
                if talep.rowcount != 1:
                    if kayit.durum == BELGE_MUHASEBELESTIRILDI:
                        return "atlandi", "Zaten muhasebeleştirilmiş.", kayit.fis_id
                    if kayit.durum in BELGE_ISLENEBILIR:
                        return "atlandi", "Kayıt başka bir işlemle değişmiş; listeyi yenileyip tekrar deneyin.", None
                    return "atlandi", f"Durum: {kayit.durum}; işlenmedi.", kayit.fis_id
                evrak, kaynak_id = kayit.evrak_turu, int(kayit.kaynak_id)
                bilgi = MuhasebelestirmeService.belge_bilgisi(session, evrak, kaynak_id)
                if bilgi is None or bilgi["iptal"] or not bilgi["kesin"]:
                    neden = ("Evrak bulunamadı." if bilgi is None else
                             "Evrak iptal edilmiş." if bilgi["iptal"] else "Evrakın kesinleşmesi geri alınmış.")
                    MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_IPTAL,
                                                       aciklama=neden, bilgi=bilgi)
                    MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebelestir_atla", neden)
                    return "atlandi", neden, None
                disi = MuhasebeEntegrasyonService.muhasebe_disi_neden(evrak, kaynak_id, session=session)
                if disi:
                    MuhasebelestirmeService._durum_yaz(session, evrak, kaynak_id, BELGE_MUHASEBE_DISI,
                                                       aciklama=disi, bilgi=bilgi)
                    MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebe_disi", disi)
                    return "atlandi", disi, None
                kapali_donem_zorunlu_degil(session, bilgi["tarih"], "Evrak")
                fn = getattr(MuhasebeEntegrasyonService, EVRAKLAR[evrak]["fn"])
                fis_id = fn(kaynak_id, yeniden=False, session=session)
                fisler = MuhasebeEntegrasyonService.evrak_fis_idleri(evrak, kaynak_id, session=session)
                fis_id = fis_id or (fisler[0] if fisler else None)
                MuhasebelestirmeService._durum_yaz(
                    session, evrak, kaynak_id, BELGE_MUHASEBELESTIRILDI, fis_id=fis_id, yontem=YONTEM_SONRADAN,
                    aciklama=None if fis_id else "Tutar sıfır; fiş gerekmedi.", bilgi=bilgi,
                )
                MuhasebelestirmeService._iz(session, evrak, kaynak_id, "muhasebelestir",
                                            f"sonradan fis={fis_id} no={bilgi['no']}")
                return "basarili", "Muhasebeleştirildi.", fis_id
        except Exception as hata:
            mesaj = str(hata).strip() or hata.__class__.__name__
            try:
                with get_session() as session:
                    kayit = session.get(MuhasebeBelgeDurumu, int(durum_id))
                    if kayit is not None and kayit.durum in BELGE_ISLENEBILIR:
                        kayit.durum = BELGE_HATALI
                        kayit.aciklama = mesaj[:500]
                        kayit.deneme_sayisi = int(kayit.deneme_sayisi or 0) + 1
                        kayit.row_version = int(kayit.row_version or 0) + 1
                        kayit.guncelleme_tarihi = datetime.now()
                        kayit.guncelleyen_kullanici_id, kayit.guncelleyen_kullanici_adi = _kullanici()
                        MuhasebelestirmeService._iz(session, kayit.evrak_turu, kayit.kaynak_id,
                                                    "muhasebelestir_hata", mesaj[:400])
            except Exception:
                pass
            return "hata", mesaj, None

    @staticmethod
    def muhasebe_disi_birak(durum_idleri: list[int], neden: str) -> int:
        """İnceleme gereken / bekleyen evrakı fiş üretmeden listeden çıkarır (ör. başka programda işlenmiş)."""
        from database.access import yazma_zorunlu

        yazma_zorunlu(TOPLU_YETKISI, mesaj="Bu işlem için yetkiniz yok.")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Neden zorunludur.")
        sayi = 0
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            for did in durum_idleri:
                kayit = session.get(MuhasebeBelgeDurumu, int(did))
                if kayit is None or kayit.firma_id != firma_id or kayit.durum not in BELGE_ISLENEBILIR:
                    continue
                kayit.durum = BELGE_MUHASEBE_DISI
                kayit.aciklama = neden[:500]
                kayit.row_version = int(kayit.row_version or 0) + 1
                kayit.guncelleme_tarihi = datetime.now()
                kayit.guncelleyen_kullanici_id, kayit.guncelleyen_kullanici_adi = _kullanici()
                MuhasebelestirmeService._iz(session, kayit.evrak_turu, kayit.kaynak_id, "muhasebe_disi", neden)
                sayi += 1
        return sayi

    @staticmethod
    def muhasebe_disindan_geri_al(durum_idleri: list[int]) -> int:
        from database.access import yazma_zorunlu

        yazma_zorunlu(TOPLU_YETKISI, mesaj="Bu işlem için yetkiniz yok.")
        sayi = 0
        with get_session() as session:
            firma_id = MuhasebeService.yerel_firma_id(session)
            for did in durum_idleri:
                kayit = session.get(MuhasebeBelgeDurumu, int(did))
                if kayit is None or kayit.firma_id != firma_id or kayit.durum != BELGE_MUHASEBE_DISI:
                    continue
                kayit.durum = BELGE_BEKLIYOR
                kayit.aciklama = None
                kayit.row_version = int(kayit.row_version or 0) + 1
                kayit.guncelleme_tarihi = datetime.now()
                kayit.guncelleyen_kullanici_id, kayit.guncelleyen_kullanici_adi = _kullanici()
                MuhasebelestirmeService._iz(session, kayit.evrak_turu, kayit.kaynak_id, "bekleyene_al",
                                            "muhasebe dışından geri alındı")
                sayi += 1
        return sayi


__all__ = [
    "AYAR_YETKISI",
    "MuhasebelestirmeService",
    "TOPLU_YETKISI",
    "YONTEM_ADLARI",
    "YONTEM_KAPALI",
    "ZatenCalisiyor",
]
