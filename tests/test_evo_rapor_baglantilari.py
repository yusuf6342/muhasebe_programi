"""Kaynak bağlantılı rapor; banka girişini körlemesine tahsilat saymama regresyonları."""
import json
import unittest
from datetime import date
from decimal import Decimal as D
from sqlalchemy import text
from tests.stok_test_ortami import StokOrtami
from database.database import get_session
from database.models.finans import FinansHesabi, FinansHareketi
from database.models.cari import Cari, CariIslem
from database import giris_ozet_service as go

DAY=date(2026,10,10)

class EvoReportTest(unittest.TestCase):
    def setUp(self):
        self.o=StokOrtami('evo_report')
        with get_session() as s:
            s.execute(text('CREATE TABLE evo_import_records(entity TEXT,source_id TEXT,target_id INTEGER,status TEXT,target_table TEXT,source_json TEXT,PRIMARY KEY(entity,source_id))'))
            customer=s.get(Cari,self.o.mus_id);customer.cari_kodu='EVB-1642'
            h=FinansHesabi(hesap_adi='Test KMH',hesap_turu='BANKA',alt_hesap_turu='KMH');s.add(h);s.flush();self.hid=h.id

    def tearDown(self):
        self.o.kapat()

    def payment(self,typ='25',ledger_amount='100',source_amount='100',module='1054',account_type='KMH',party='1642'):
        with get_session() as s:
            h=s.get(FinansHesabi,self.hid);h.alt_hesap_turu=account_type
            m=FinansHareketi(hesap_id=self.hid,tarih=DAY,hareket_turu='BANKA GİRİŞ',belge_no='EVB-BN-1',tutar=D('100'));s.add(m);s.flush()
            source={'a_id':'1','a_tur_id':typ,'a_ref_id':party,'a_giren':source_amount,'a_cikan':'0','a_tarih':'10.10.2026 00:00:00','a_banka_ad':'Test KMH','a_dov_kur':'1','DOV_KOD':'TL','a_modul_id':module,'a_mudul_ref_id':'10'}
            s.execute(text('INSERT INTO evo_import_records VALUES (:e,:sid,:tid,:st,:tab,:raw)'),{'e':'banka_hareket','sid':'1','tid':m.id,'st':'imported','tab':'finans_hareketleri','raw':json.dumps(source)})
            s.add(CariIslem(cari_id=self.o.mus_id,tarih=DAY,islem_turu='Tahsilat',belge_no='EVB-BN-1',borc=0,alacak=D(ledger_amount)))

    def report(self):
        with get_session() as s:
            b=go._Baglam(s,DAY,DAY,None)
            return go.tahsilat_bolumu(b,{'bugun':D('100'),'ay':D('100')})

    def test_kmh_card_uses_source_method(self):
        self.payment()
        r=self.report();self.assertEqual(r['toplam']['ay']['tutar'],D('100'))
        self.assertEqual(r['gercek'][0]['yontem'],go.KART)

    def test_pos_account_havale_keeps_source_method(self):
        self.payment(typ='20',account_type='POS')
        self.assertEqual(self.report()['gercek'][0]['yontem'],go.HAVALE)

    def test_untraced_internal_transfer_is_not_customer_receipt(self):
        # Generic bank movement without source proof never becomes a receipt.
        with get_session() as s:
            s.add(FinansHareketi(hesap_id=self.hid,tarih=DAY,hareket_turu='BANKA GİRİŞ',belge_no='INTERNAL',tutar=D('999')))
        self.assertEqual(self.report()['toplam']['ay']['tutar'],0)

    def test_finance_tamper_is_withheld(self):
        self.payment(source_amount='101')
        self.assertEqual(self.report()['toplam']['ay']['tutar'],0)

    def test_ledger_tamper_is_withheld(self):
        self.payment(ledger_amount='101')
        self.assertEqual(self.report()['toplam']['ay']['tutar'],0)

    def test_wrong_party_is_withheld(self):
        self.payment(party='9999')
        self.assertEqual(self.report()['toplam']['ay']['tutar'],0)

    def test_company_card_havale_is_withheld(self):
        self.payment(typ='20',account_type='KREDI_KARTI')
        self.assertEqual(self.report()['toplam']['ay']['tutar'],0)

    def test_source_draft_return_is_excluded_and_approved_return_uses_ledger(self):
        from database.models.satis_iade_faturasi import SatisIadeFaturasi,SatisIadeFaturasiSatiri
        with get_session() as s:
            s.execute(text('ALTER TABLE satis_iade_faturalari ADD COLUMN tl_genel_toplam NUMERIC DEFAULT 0'))
            for fid,approved,amount in [(1,'0',D('260')),(2,'1',D('40'))]:
                f=SatisIadeFaturasi(id=fid,iade_no='EVO-RETURN-'+str(fid),iade_tarihi=DAY,cari_id=self.o.mus_id,durum='AÇIK',depo='ANA DEPO')
                s.add(f);s.flush()
                s.add(SatisIadeFaturasiSatiri(iade_id=fid,urun_kodu='U001',urun_adi='Test',miktar=1,birim='Adet',birim_fiyat=amount,kdv_orani=0))
                s.execute(text('UPDATE satis_iade_faturalari SET tl_genel_toplam=:v WHERE id=:id'),{'v':str(amount),'id':fid})
                source={'Ana':[{'a_id':str(fid),'a_tur':'33','a_cari_id':'1642','a_tarih':'10.10.2026 00:00:00','a_tutar':str(amount),'a_onay':approved}]}
                s.execute(text('INSERT INTO evo_import_records VALUES (:e,:sid,:tid,:st,:tab,:raw)'),{'e':'33','sid':str(fid),'tid':fid,'st':'imported','tab':'satis_iade_faturalari','raw':json.dumps(source)})
                if approved=='1':s.add(CariIslem(cari_id=self.o.mus_id,tarih=DAY,islem_turu='İade',belge_no=f.iade_no,borc=0,alacak=amount))
        with get_session() as s:
            b=go._Baglam(s,DAY,DAY,None);r=go.satis_bolumu(b)
            self.assertEqual(r['satirlar']['ay']['iade_adedi'],1)
            self.assertEqual(r['satirlar']['ay']['iade_tutari'],D('40'))
            self.assertFalse(any('cari kaydı yok' in x for x in r['uyarilar']))

if __name__=='__main__':unittest.main()
