"""Mevcut Evo ödeme bağlantılarını faturada bilgi olarak gösterir; tahsilat yaratmaz."""
from datetime import date, datetime
from decimal import Decimal
import json
from sqlalchemy import inspect, text
from database.database import get_session


def fatura_odeme_bilgisi(fatura_id):
    with get_session() as session:
        if not inspect(session.connection()).has_table('evo_invoice_payment_links'):
            return None
        links=session.execute(text('SELECT * FROM evo_invoice_payment_links WHERE invoice_id=:fid ORDER BY entity,source_id'),{'fid':int(fatura_id)}).mappings().all()
        if not links:return None
        f=session.execute(text('SELECT cari_id,tahsilat_tutari,fatura_tarihi FROM satis_faturalari WHERE id=:fid'),{'fid':int(fatura_id)}).mappings().one()
        trace=session.execute(text("SELECT source_id,source_json FROM evo_import_records WHERE entity='31' AND target_table='satis_faturalari' AND target_id=:fid AND status='imported'"),{'fid':int(fatura_id)}).all()
        if len(trace)!=1:raise ValueError('Faturanın Evo kimliği doğrulanamadı.')
        sid,raw=trace[0];h=json.loads(raw)['Ana'][0];total=Decimal(0);result=[]
        for link in links:
            m=session.execute(text('SELECT f.tutar,f.tarih,f.belge_no,h.hesap_adi FROM finans_hareketleri f JOIN finans_hesaplari h ON h.id=f.hesap_id WHERE f.id=:id'),{'id':link['finance_id']}).mappings().one_or_none()
            ledger=session.execute(text('SELECT cari_id,tarih,belge_no,borc,alacak FROM cari_islemleri WHERE id=:id'),{'id':link['ledger_id']}).mappings().one_or_none()
            source=session.execute(text("SELECT source_json FROM evo_import_records WHERE entity=:entity AND source_id=:sid AND target_id=:tid AND status='imported' AND target_table='finans_hareketleri'"),{'entity':link['entity'],'sid':link['source_id'],'tid':link['finance_id']}).scalar_one_or_none()
            if not source or not m or not ledger:raise ValueError('Bağlı ödeme kaynağı bulunamadı.')
            s=json.loads(source);typ=str(s.get('a_tur_id'));labels={'10':'NAKİT / KASA','20':'GELEN HAVALE','25':'KREDİ KARTIYLA TAHSİLAT'}
            value=Decimal(link['amount']);doc=('EVB-KS-' if link['entity']=='kasa_hareket' else 'EVB-BN-')+link['source_id']
            if (str(s.get('a_modul_id'))!='1054' or str(s.get('a_mudul_ref_id'))!=sid
                    or str(s.get('a_ref_id'))!=str(h.get('a_cari_id')) or labels.get(typ)!=link['method']
                    or Decimal(str(s.get('a_giren') or 0))!=value or Decimal(str(s.get('a_cikan') or 0))!=0
                    or m['belge_no']!=doc or m['hesap_adi']!=link['account'] or Decimal(str(m['tutar']))!=value
                    or ledger['cari_id']!=f['cari_id'] or ledger['belge_no']!=doc or ledger['tarih']!=m['tarih']
                    or Decimal(str(ledger['borc']))!=0 or Decimal(str(ledger['alacak']))!=value
                    or datetime.strptime(str(s.get('a_tarih'))[:10],'%d.%m.%Y').date().isoformat()!=m['tarih']):
                raise ValueError('Bağlı ödeme değişmiş; yeniden kontrol gerekli.')
            total+=value
            result.append({'tahsilat_tarihi':date.fromisoformat(m['tarih']),'tutar':value,
                           'odeme_sekli':link['method'],'hesap':link['account'],
                           'aciklama':'Mevcut Evo tahsilatı: '+doc})
        if total!=Decimal(str(f['tahsilat_tutari'])):raise ValueError('Fatura ve mevcut ödeme toplamları farklı.')
        return result
