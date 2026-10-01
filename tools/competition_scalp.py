"""Full-year momentum/pullback/shock scalping, then execution research."""
import argparse,json,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd,torch

ROOT=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923')
OUT=ROOT/'research/competition_scalp_full_year_20260930'
SYMBOLS=['SPY','QQQ','NVDA','TSLA','AMD','AAPL','MSFT','META','AMZN','GOOGL','AVGO','NFLX','JPM','XOM','BAC']
LEVELS=[-1,0,1,2,3,4,5]

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'snapshot/source_reference.json').read_text())['catalog']
    with duckdb.connect(source,read_only=True) as c:
        c.execute("SET memory_limit='5GB'");c.execute('SET threads=4');c.register('symbols',pd.DataFrame({'symbol':SYMBOLS}))
        bars=c.execute('''SELECT b.security_id,b.symbol,b.session_date,b.bar_start_ts_utc,b.open,b.high,b.low,b.close,b.volume
          FROM bars_1m_raw b JOIN symbols s USING(symbol)
          LEFT JOIN sp500_pit_membership_daily m ON b.security_id=m.security_id AND b.session_date=m.session_date
          WHERE b.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30'
          AND (b.symbol IN ('SPY','QQQ') OR m.in_universe)
          AND CAST(timezone('America/New_York',b.bar_start_ts_utc) AS TIME)>=TIME '09:30:00'
          AND CAST(timezone('America/New_York',b.bar_start_ts_utc) AS TIME)<TIME '16:00:00'
          ORDER BY b.session_date,b.symbol,b.bar_start_ts_utc''').fetchdf()
    assert not bars.duplicated(['symbol','bar_start_ts_utc']).any()
    clock=bars.bar_start_ts_utc.dt.tz_convert('America/New_York');bars['minute']=clock.dt.hour*60+clock.dt.minute-570
    bars.to_parquet(OUT/'bars.parquet',index=False)
    days=sorted(bars.session_date.unique());symbols=sorted(bars.symbol.unique())
    di=pd.Index(days).get_indexer(bars.session_date);si=pd.Index(symbols).get_indexer(bars.symbol);mi=bars.minute.to_numpy()
    for col in ['open','high','low','close','volume']:
        cube=np.full((len(days),len(symbols),390),np.nan);cube[di,si,mi]=bars[col].to_numpy();np.save(OUT/f'{col}.npy',cube)
    starts=bars.groupby('session_date').bar_start_ts_utc.min().sort_index().to_numpy(dtype='datetime64[ns]').astype('int64')
    axes={'days':[str(pd.Timestamp(d).date()) for d in days],'symbols':symbols,'open_epoch_ns':starts.tolist()}
    (OUT/'axes.json').write_text(json.dumps(axes))
    (OUT/'scope.json').write_text(json.dumps({'discovery':['2025-05-01','2026-04-30'],'out_of_sample_accessed':False,
        'symbols':SYMBOLS,'stock_membership':'stored PIT eligibility each session','etfs':['SPY','QQQ'],
        'mechanisms':['5m continuation','15m trend with 1m pullback','1m shock reversal'],
        'sigma':'prior 30 complete one-minute log returns, excluding signal bar','holds_minutes':[2,5,10],
        'cost_offsets_per_side':LEVELS,'purpose':'High-frequency and consistent structure, then limit attainability.'},indent=2))
    print('PREPARED',len(bars),'bars',len(days),'days',len(symbols),'symbols',flush=True)

def allocate(d,s,m,hold,slots=3):
    if not len(d):return np.array([],dtype=int)
    key=(s.astype(np.uint64)+1)*np.uint64(2654435761)+(d.astype(np.uint64)+1)*np.uint64(2246822519)
    order=np.lexsort((key,m,d));free=np.full(slots,-1);active=np.full(int(s.max())+1,-1);last=-1;kept=[]
    for j in order:
        if d[j]!=last:free[:]=-1;active[:]=-1;last=d[j]
        entry=m[j]+1;exit=entry+hold+1
        if active[s[j]]>entry:continue
        slot=free.argmin()
        if free[slot]>entry:continue
        kept.append(j);free[slot]=exit;active[s[j]]=exit
    return np.array(kept,dtype=int)

def metrics(ret,day,days,slots):
    daily=np.bincount(day,weights=ret/slots,minlength=len(days));cum=daily.cumsum();dd=np.maximum.accumulate(np.r_[0.,cum])[1:]-cum
    ser=pd.Series(daily,index=pd.to_datetime(days));monthly=ser.groupby(ser.index.strftime('%Y-%m')).sum()
    weekly=ser.groupby(ser.index.to_period('W')).sum()
    return {'trades':len(ret),'mean_trade_bps':float(ret.mean()*10000) if len(ret) else 0,
        'return_pct':float(daily.sum()*100),'max_dd_pct':float(dd.max()*100),'positive_months':int((monthly>0).sum()),
        'worst_month_pct':float(monthly.min()*100),'median_month_pct':float(monthly.median()*100),
        'active_days':int(np.count_nonzero(np.bincount(day,minlength=len(days)))),'positive_days':int((daily>0).sum()),
        'positive_week_fraction':float((weekly>0).mean()),'without_best5_days_pct':float((daily.sum()-np.sort(daily)[-5:].sum())*100),
        'monthly_pct':json.dumps(monthly.mul(100).to_dict())}

def screen(opening=False):
    torch.set_num_threads(4);axes=json.loads((OUT/'axes.json').read_text());days=axes['days'];symbols=axes['symbols']
    cp=np.load(OUT/'close.npy',mmap_mode='r');op=np.load(OUT/'open.npy',mmap_mode='r')
    p=torch.as_tensor(np.array(cp),device='cuda',dtype=torch.float64)
    returns=torch.full_like(p,torch.nan);returns[:,:,1:]=torch.log(p[:,:,1:]/p[:,:,:-1])
    sigma=torch.full_like(p,torch.nan)
    sigma[:,:,30:]=returns[:,:,:-1].unfold(2,30,1).std(dim=-1,unbiased=True)
    dest=OUT/'opening' if opening else OUT;dest.mkdir(exist_ok=True)
    if opening:
        # Use preceding regular-session returns at the open; exclude the overnight gap.
        po=torch.as_tensor(np.array(op),device='cuda',dtype=torch.float64)
        returns[:,:,0]=torch.log(p[:,:,0]/po[:,:,0])
        flat=returns.permute(1,0,2).reshape(len(symbols),-1)
        padded=torch.cat([torch.full((len(symbols),30),torch.nan,device='cuda'),flat],dim=1)
        prior=padded[:,:-1].unfold(1,30,1).std(dim=-1,unbiased=True)
        sigma=prior.reshape(len(symbols),len(days),390).permute(1,0,2).contiguous()
    r5=torch.full_like(p,torch.nan);r5[:,:,5:]=torch.log(p[:,:,5:]/p[:,:,:-5])
    r15=torch.full_like(p,torch.nan);r15[:,:,15:]=torch.log(p[:,:,15:]/p[:,:,:-15])
    signals=[];rules=[];stats=[];ledger=[]
    mechanisms=[('momentum',r5/(sigma*np.sqrt(5)),returns*torch.sign(r5)>0,[1.,1.5]),
                ('pullback',r15/(sigma*np.sqrt(15)),returns*torch.sign(r15)<-.5*sigma,[1.,1.5]),
                ('reversion',returns/sigma,torch.ones_like(p,dtype=torch.bool),[1.5,2.])]
    for mechanism,strength,condition,thresholds in mechanisms:
        for threshold in thresholds:
            valid=(strength.abs()>=threshold)&condition&torch.isfinite(strength)&(sigma>0)
            if opening:valid[:,:,30:]=False
            else:valid[:,:,:30]=False;valid[:,:,378:]=False
            d,s,m=torch.where(valid);side=torch.sign(strength[d,s,m])*(-1 if mechanism=='reversion' else 1)
            d=d.cpu().numpy();s=s.cpu().numpy();m=m.cpu().numpy();side=side.cpu().numpy().astype(int)
            for hold in [2,5,10]:
                cid=f'{mechanism}_{threshold:g}_{hold}m';ep=np.asarray(op[d,s,m+1]);xp=np.asarray(op[d,s,m+1+hold])
                ok=np.isfinite(ep)&np.isfinite(xp)&(ep>0)&(xp>0)
                dd,ss,mm,dirn=d[ok],s[ok],m[ok],side[ok];ee,xx=ep[ok],xp[ok]
                rules.append({'candidate_id':cid,'mechanism':mechanism,'threshold_sigma':threshold,'hold_minutes':hold})
                # ETF and stock specialists are visible separately; no fitted ticker whitelist.
                scopes=[('all',np.ones(len(dd),bool)),('etfs',np.isin(ss,[symbols.index(x) for x in ['SPY','QQQ']]))]
                scopes += [(symbol,ss==i) for i,symbol in enumerate(symbols)]
                for scope,mask in scopes:
                    idx=np.flatnonzero(mask);picked=idx[allocate(dd[idx],ss[idx],mm[idx],hold,3)]
                    if len(picked)<1000:continue
                    name=cid+'__'+scope
                    f=pd.DataFrame({'candidate_id':name,'day':dd[picked],'symbol_code':ss[picked],'signal_minute':mm[picked],
                        'side':dirn[picked],'entry_price':ee[picked],'exit_price':xx[picked],'hold_minutes':hold})
                    ledger.append(f)
                    for bps in LEVELS:
                        e=ee[picked]*(1+dirn[picked]*bps/10000);x=xx[picked]*(1-dirn[picked]*bps/10000)
                        ret=dirn[picked]*(x-e)/e
                        stats.append({'candidate_id':name,'scope':scope,'mechanism':mechanism,'threshold_sigma':threshold,'hold_minutes':hold,'bps':bps,
                            'slots':3,**metrics(ret,dd[picked],days,3)})
                print('STRUCTURE',cid,'eligible',len(dd),flush=True)
    pd.DataFrame(rules).to_parquet(dest/'rules.parquet',index=False);pd.concat(ledger).to_parquet(dest/'bar_trades.parquet',index=False)
    result=pd.DataFrame(stats);result.to_parquet(dest/'bar_sensitivity.parquet',index=False)
    for bps in [0,1,2]:
        best=result[result.bps==bps].sort_values(['positive_months','without_best5_days_pct'],ascending=False)
        print('BPS',bps,best[['candidate_id','trades','mean_trade_bps','return_pct','max_dd_pct','positive_months','positive_days','positive_week_fraction','worst_month_pct']].head(12).to_string(index=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','screen','opening']);args=parser.parse_args()
    if args.stage=='opening':screen(True)
    else:globals()[args.stage]()
