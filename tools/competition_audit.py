import json
import argparse
import numpy as np,pandas as pd,duckdb
from competition_full_year import ROOT,OUT
from competition_under2d import allocate_frame,portfolio_stats
from quant_pipeline.production.evidence_store import EvidenceReader

CORE=['positive_return_ma_low20','positive_return_ma_tail','positive_return_ma_r5','positive_return_ma_r3']

def capacity():
    f=pd.read_parquet(OUT/'trades_daily_close.parquet');summaries=[];ledgers=[]
    for name in CORE:
        g=f[f.candidate_id==name]
        for slots in [1,3,5,10]:
            for seed in range(10):
                selected=allocate_frame(g,slots,seed)
                for bps in [-1,0,1,2,3,4,5]:
                    st=portfolio_stats(selected,bps,slots);st['monthly_pct']=json.dumps(st['monthly_pct'])
                    summaries.append({'candidate_id':name,'slots':slots,'seed':seed,'bps':bps,**st})
                if seed==0:
                    ledgers.append(selected.assign(slots=slots))
    result=pd.DataFrame(summaries);result.to_parquet(OUT/'capacity_sensitivity.parquet',index=False)
    pd.concat(ledgers).to_parquet(OUT/'capacity_trades.parquet',index=False)
    print(result[(result.seed==0)&(result.bps==5)][['candidate_id','slots','trades','additive_pct','max_dd_pct','positive_months','ex_top5_mean_bps']].to_string(index=False),flush=True)

def paths():
    f=pd.read_parquet(OUT/'trades_daily_close.parquet');f=f[f.candidate_id.isin(CORE[:3])].copy()
    f['entry_date']=f.entry_ts.dt.tz_convert('America/New_York').dt.date
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('windows',f)
        bars=c.execute('''SELECT w.candidate_id,w.observation_id,b.security_id,b.symbol,b.bar_start_ts_utc stamp,b.open,b.high,b.low,b.close
         FROM bars_1m_raw b JOIN windows w ON b.security_id=w.security_id AND b.session_date=w.entry_date
         AND b.bar_start_ts_utc>=w.entry_ts AND b.bar_start_ts_utc<=w.exit_ts''').fetchdf()
    bars.to_parquet(OUT/'daily_core_paths.parquet',index=False)
    b=bars.merge(f[['candidate_id','observation_id','entry_price','entry_ts']],on=['candidate_id','observation_id'],validate='many_to_one')
    b['minutes']=(b.stamp-b.entry_ts).dt.total_seconds()/60
    b['high_ret']=(b.high/b.entry_price-1)*10000;b['low_ret']=(b.low/b.entry_price-1)*10000;b['open_ret']=(b.open/b.entry_price-1)*10000
    agg=b.groupby(['candidate_id','observation_id']).agg(mfe=('high_ret','max'),mae=('low_ret','min'))
    agg.to_parquet(OUT/'daily_core_excursions.parquet')
    rows=[]
    for cid,g in b.groupby('candidate_id'):
        for h in [30,60,120,240,388]:
            prices=g[g.minutes==h]
            rows.append({'candidate_id':cid,'horizon_minutes':h,'trades_with_endpoint':len(prices),'gross_mean_bps':prices.open_ret.mean(),
                         'mfe_median_bps':agg.loc[cid].mfe.median(),'mae_median_bps':agg.loc[cid].mae.median()})
    result=pd.DataFrame(rows);result.to_parquet(OUT/'daily_core_horizons.parquet',index=False);print(result.to_string(index=False),flush=True)

def risk():
    trades=pd.read_parquet(OUT/'capacity_trades.parquet');bars=pd.read_parquet(OUT/'daily_core_paths.parquet')
    # Minute marks include losses that an end-of-day equity curve can hide.
    out=[]
    for (cid,slots),f in trades[trades.candidate_id.isin(CORE[:3])].groupby(['candidate_id','slots']):
        work=bars[bars.candidate_id==cid].merge(f[['observation_id','entry_price','entry_ts','exit_price','exit_ts']],on='observation_id',validate='many_to_one')
        work['pnl']=(work.close*.9995/(work.entry_price*1.0005)-1)/slots
        local=work.stamp.dt.tz_convert('America/New_York');work['date']=local.dt.date;work['clock']=local.dt.strftime('%H:%M')
        # Positions all start at 09:31 and close at 15:59; fill sparse minutes forward per position.
        position=work.pivot(index='stamp',columns='observation_id',values='pnl')
        for column,row in f.set_index('observation_id').iterrows():
            if column not in position:continue
            mask=(position.index>=row.entry_ts)&(position.index<=row.exit_ts)
            position.loc[mask,column]=position.loc[mask,column].ffill()
            position.loc[position.index>row.exit_ts,column]=(row.exit_price*.9995/(row.entry_price*1.0005)-1)/slots
        equity=position.fillna(0).sum(axis=1).to_numpy();dd=np.maximum.accumulate(np.r_[0.,equity])[1:]-equity
        out.append({'candidate_id':cid,'slots':int(slots),'minute_mark_dd_pct':float(dd.max()*100)})
    pd.DataFrame(out).to_parquet(OUT/'minute_risk.parquet',index=False);print(pd.DataFrame(out).to_string(index=False),flush=True)

def integrity():
    f=pd.read_parquet(OUT/'trades_daily_close.parquet');f=f[f.candidate_id.isin(CORE)].copy()
    r=EvidenceReader(ROOT,'evidence/reader.json','daily_close')
    adjusted=r.read_columns('targets',['target_1d__benchmark_adjusted__daily_close'],0,r.rows)[:,0]
    raw=r.read_columns('targets',['target_1d__raw__daily_close'],0,r.rows)[:,0]
    f['benchmark_adjusted_bps']=adjusted[f.observation_id]*10000;f['raw_target_bps']=raw[f.observation_id]*10000
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.register('trades',f)
        membership=c.execute('''SELECT t.candidate_id,t.observation_id,bool_or(coalesce(m.in_universe,false)) eligible
          FROM trades t LEFT JOIN sp500_pit_membership_daily m ON t.security_id=m.security_id AND t.session_date=m.session_date
          GROUP BY 1,2''').fetchdf()
    f=f.merge(membership,on=['candidate_id','observation_id'],validate='one_to_one')
    assert f.eligible.all(),'Trade outside stored PIT membership'
    assert ((f.exit_ts-f.entry_ts)<pd.Timedelta(days=2)).all()
    assert (f.entry_ts>f.decision_ts).all()
    assert f.exit_ts.max() < pd.Timestamp('2026-05-01',tz='America/New_York')
    result=f.groupby('candidate_id').agg(n=('eligible','size'),raw_mean_bps=('raw_target_bps','mean'),benchmark_adjusted_mean_bps=('benchmark_adjusted_bps','mean'),eligible=('eligible','all'))
    result.to_parquet(OUT/'integrity_and_return_basis.parquet');print(result.to_string(),flush=True)

def structure():
    t=pd.read_parquet(OUT/'trades_daily_close.parquet');g=t[t.candidate_id=='positive_return_ma_tail'].copy()
    g['net']=(g.exit_price*.9995/g.entry_price/1.0005-1)*10000
    print('SYMBOLS',g.groupby('symbol').agg(n=('net','size'),edge=('net','mean'),contribution=('net','sum')).sort_values('contribution',ascending=False).head(12).to_string(),flush=True)
    print('MONTHS',g.groupby(pd.to_datetime(g.session_date).dt.strftime('%Y-%m')).agg(n=('net','size'),edge=('net','mean')).to_string(),flush=True)
    c=duckdb.connect();files=[str(p) for stage in ['dual_coarse_results','dual_fine_results','dual_exact_results'] for p in (ROOT/stage/'daily_close').rglob('*.parquet')]
    c.read_parquet(files).create_view('s')
    f=c.execute("select feature_a,feature_b,resolution,surface_counts,surface_sums from s where pair_id='a80d744f007ca5a9b3818172' and target_id='target_1d__raw__daily_close'").fetchdf()
    for x in f.itertuples():
        r=int(x.resolution);n=np.array(x.surface_counts);s=np.array(x.surface_sums)*1e4
        m=np.divide(s,n,out=np.zeros_like(s),where=n>0)
        print('SURFACE',r,'bps',m.reshape(r,r).round(1),'N',n.reshape(r,r),flush=True)
    f.to_parquet(OUT/'daily_tail_full_surfaces.parquet',index=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',nargs='?',default='structure',choices=['structure','capacity','paths','risk','integrity']);args=p.parse_args()
    globals()[args.stage]()
