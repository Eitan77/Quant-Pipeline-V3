"""Clear causal one-minute mechanisms across the complete eligible universe."""
import argparse,json,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd,torch,exchange_calendars as xc
from numba import njit
from competition_under2d import ROOT
from competition_scalp import metrics

OUT=ROOT/'research/intraday_causal_restart_20260930/minute_mechanisms'
OUT.mkdir(parents=True,exist_ok=True)
LEVELS=[-1,0,1,2,3,4,5]

def prepare():
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    days=cal.index.strftime('%Y-%m-%d').tolist();opens=pd.to_datetime(cal['open'],utc=True).dt.as_unit('ns')
    ends=((pd.to_datetime(cal['close'],utc=True)-opens).dt.total_seconds()/60).to_numpy(int)
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.execute("SET memory_limit='4GB'")
        source=str(ROOT/'cache/calculation_panels/intraday_5m.parquet')
        c.read_parquet(source).create_view('panel');c.read_parquet('reference/sp500_pit_membership_daily.parquet').create_view('pit')
        # Match the contemporary symbol as well as its stable identity. Old
        # aliases must not duplicate another listing's price/volume history.
        c.execute("""CREATE VIEW eligible_source AS SELECT p.* FROM panel p
          WHERE p.session_date BETWEEN DATE '2025-05-01' AND DATE '2026-04-30'
          AND (p.symbol IN ('SPY','QQQ') OR (p.in_universe AND EXISTS
             (SELECT 1 FROM pit m WHERE m.symbol=p.symbol AND m.session_date=p.session_date AND m.in_universe)))""")
        ids=c.execute('SELECT security_id,arg_max(symbol,session_date) symbol FROM eligible_source GROUP BY 1 ORDER BY 1').fetchdf()
        shape=(len(days),len(ids),390);arrays={}
        for name in ['close','high','low','volume','vwap']:
            arrays[name]=np.lib.format.open_memmap(OUT/f'{name}.npy',mode='w+',dtype='float64',shape=shape);arrays[name][:]=np.nan
        stream=c.execute('''SELECT security_id,symbol,session_date,bar_start_ts_utc,execution_close AS "close",execution_high AS "high",execution_low AS "low",volume,vwap*split_factor AS "vwap"
          FROM eligible_source''').fetch_record_batch(500000)
        sid=pd.Index(ids.security_id);day=pd.Index(days);total=0;discarded=0;start=time.time()
        for batch in stream:
            f=batch.to_pandas();d=day.get_indexer(pd.to_datetime(f.session_date).dt.strftime('%Y-%m-%d'));s=sid.get_indexer(f.security_id)
            stamp=pd.to_datetime(f.bar_start_ts_utc,utc=True).dt.as_unit('ns').astype('int64').to_numpy()
            minute=((stamp-opens.astype('int64').to_numpy()[d])//60_000_000_000).astype(int)
            valid=(minute>=0)&(minute<ends[d]);discarded+=int((~valid).sum());d,s,minute=d[valid],s[valid],minute[valid]
            for name,array in arrays.items():array[d,s,minute]=f.loc[valid,name].to_numpy('float64')
            total+=len(d)
            if total%5000000<500000:print('MINUTE_DATA',total,'rows',round(time.time()-start),'seconds',flush=True)
        for array in arrays.values():array.flush()
    axes={'days':days,'security_ids':ids.security_id.tolist(),'symbols':ids.symbol.tolist(),'open_epoch_ns':opens.astype('int64').tolist(),'session_minutes':ends.tolist(),'rows':total,'after_official_close_removed':discarded}
    (OUT/'axes.json').write_text(json.dumps(axes))
    (OUT/'scope.json').write_text(json.dumps({'discovery':['2025-05-01','2026-04-30'],'holdouts_accessed':False,'universe':'Causal PIT eligibility from source panel plus SPY/QQQ; all historical eligible identities, no fitted stock list.',
      'mechanisms':['1m shock reversal','5m momentum with immediate confirmation','15m trend pullback','30m VWAP stretch and turn'],
      'ranking':'Descending signal strength observable at decision; fixed ten reservation lanes; no realized-return ranking.',
      'universe_controls':['all eligible stocks','current trailing-dollar-volume top decile of eligible stocks','SPY/QQQ'],
      'execution':'Completed-minute close references; entry active +5sec, exit active +5sec; scheduled exit plus 60sec lane reservation.',
      'fees':0,'prescribed_bps_per_side':LEVELS,'bar_projection_is_execution_validation':False},indent=2))
    print('PREPARED',total,'rows',len(days),'sessions',len(ids),'identities; outside official RTH removed',discarded,flush=True)

@njit
def reserve(order,d,s,m,hold,slots,symbols):
    free=np.zeros(slots,np.int64);active=np.zeros(symbols,np.int64);last=-1;kept=np.empty(len(order),np.int64);count=0
    for j in order:
        if d[j]!=last:free[:]=0;active[:]=0;last=d[j]
        entry=m[j]+1
        if active[s[j]]>entry:continue
        slot=free.argmin()
        if free[slot]>entry:continue
        release=entry+hold+1;free[slot]=release;active[s[j]]=release;kept[count]=j;count+=1
    return kept[:count]

def screen():
    torch.set_num_threads(4);assert torch.cuda.is_available()
    axes=json.loads((OUT/'axes.json').read_text());days=axes['days'];symbols=axes['symbols'];ends=np.array(axes['session_minutes']);D,S,M=len(days),len(symbols),390
    cube={key:np.load(OUT/f'{key}.npy',mmap_mode='r') for key in ['close','high','low','volume','vwap']}
    definitions={'shock_reversion':(2.,[2,5,10]),'momentum_confirmation':(1.5,[5,15,30]),'trend_pullback':(1.5,[5,15,30]),'vwap_stretch_turn':(1.5,[5,15,30])}
    events={key:[] for key in definitions};start=time.time();spy=symbols.index('SPY');etf=np.isin(np.arange(S),[spy,symbols.index('QQQ')])
    for first in range(0,D,22):
        last=min(D,first+22);p=torch.as_tensor(np.array(cube['close'][first:last]),device='cuda',dtype=torch.float64)
        v=torch.as_tensor(np.array(cube['volume'][first:last]),device='cuda',dtype=torch.float64)
        vw=torch.as_tensor(np.array(cube['vwap'][first:last]),device='cuda',dtype=torch.float64)
        ret=torch.full_like(p,torch.nan);ret[:,:,1:]=torch.log(p[:,:,1:]/p[:,:,:-1])
        sigma=torch.full_like(p,torch.nan);sigma[:,:,30:]=ret[:,:,:-1].unfold(2,30,1).std(dim=-1,unbiased=True)
        z=ret/sigma
        r5=torch.full_like(p,torch.nan);r5[:,:,5:]=torch.log(p[:,:,5:]/p[:,:,:-5])/(sigma[:,:,5:]*np.sqrt(5))
        trend=torch.full_like(p,torch.nan);trend[:,:,16:]=torch.log(p[:,:,15:-1]/p[:,:,:-16])/(sigma[:,:,16:]*np.sqrt(15))
        # Trailing known dollar turnover supplies one liquid-universe control.
        dollars=torch.nan_to_num(v*vw,nan=0.);cs=dollars.cumsum(2);dv=cs.clone();dv[:,:,30:]=cs[:,:,30:]-cs[:,:,:-30]
        stocks=torch.as_tensor(~etf,device='cuda');available=torch.isfinite(p)&stocks[None,:,None]
        ranked=torch.where(available,dv,torch.full_like(dv,-torch.inf));sorted_dv=torch.sort(ranked,dim=1,descending=True).values
        n=available.sum(1);k=((n.double()*.1).ceil().long()-1).clamp(min=0)
        cutoff=sorted_dv.gather(1,k[:,None,:]).squeeze(1);liquid=available&(dv>=cutoff[:,None,:])
        # A trailing VWAP uses only the completed 30 minutes, never session-end VWAP.
        vol=torch.nan_to_num(v,nan=0.);vs=vol.cumsum(2);v30=vs.clone();v30[:,:,30:]=vs[:,:,30:]-vs[:,:,:-30]
        rolling_vwap=dv/v30;stretch=(p/rolling_vwap-1)/(sigma*np.sqrt(30))
        conditions={
          'shock_reversion':(z.abs()>=2.,-torch.sign(z),z.abs()),
          'momentum_confirmation':((r5.abs()>=1.5)&(ret*torch.sign(r5)>0),torch.sign(r5),r5.abs()),
          'trend_pullback':((trend.abs()>=1.5)&(z*torch.sign(trend)<=-1.5),torch.sign(trend),z.abs()),
          'vwap_stretch_turn':((stretch.abs()>=1.5)&(ret*torch.sign(stretch)<0),-torch.sign(stretch),stretch.abs())}
        for name,(mask,side,score) in conditions.items():
            mask=mask&torch.isfinite(score)&(sigma>0);mask[:,:,:31]=False
            d,s,m=torch.where(mask);events[name].append(pd.DataFrame({'day':d.cpu().numpy()+first,'symbol_code':s.cpu().numpy(),'signal_minute':m.cpu().numpy(),
              'direction':side[d,s,m].cpu().numpy().astype('int8'),'score':score[d,s,m].cpu().numpy(),'liquid_decile':liquid[d,s,m].cpu().numpy()}))
        print('GPU_MINUTE_MECHANISMS',first,last,'/',D,round(time.time()-start),'seconds',flush=True)
        del p,v,vw,ret,sigma,z,r5,trend,dollars,cs,dv,ranked,sorted_dv,vol,vs,v30,rolling_vwap,stretch,conditions,mask,side,score;torch.cuda.empty_cache()
    cp=cube['close'];rows=[];rules=[];survivors=[]
    # Causal carry of the latest same-session close for stale exit-reference diagnostics.
    marks=np.array(cp);positions=np.where(np.isfinite(marks),np.arange(M)[None,None,:],0);np.maximum.accumulate(positions,axis=2,out=positions)
    marks=np.take_along_axis(marks,positions,axis=2)
    for name,parts in events.items():
        f=pd.concat(parts,ignore_index=True);d=f.day.to_numpy();s=f.symbol_code.to_numpy();m=f.signal_minute.to_numpy();strength=f.score.to_numpy();direction=f.direction.to_numpy()
        for universe,umask in [('stocks',~etf[s]),('liquid_decile',f.liquid_decile.to_numpy()),('etfs',etf[s])]:
            for hold in definitions[name][1]:
                indices=np.flatnonzero(umask&(m+hold<=ends[d]-2))
                dd,ss,mm=d[indices],s[indices],m[indices];sc=strength[indices]
                order=np.lexsort((ss,-sc,mm,dd));picked=indices[reserve(order,dd,ss,mm,hold,10,S)]
                if not len(picked):continue
                ee=cp[d[picked],s[picked],m[picked]];xx=marks[d[picked],s[picked],m[picked]+hold];side=direction[picked]
                assert np.isfinite(ee).all() and np.isfinite(xx).all(),'Unpriced bar reference retained; no claim'
                cid=f'{name}_{universe}_{hold}m';metrics_by_bps=[]
                for bps in LEVELS:
                    entry=ee*(1+side*bps/1e4);exit=xx*(1-side*bps/1e4);ret=side*(exit/entry-1)
                    profit=pd.Series(ret).groupby(s[picked]).sum().sort_values(ascending=False);trim=~np.isin(s[picked],profit.head(5).index)
                    record={'candidate_id':cid,'mechanism':name,'universe':universe,'hold_minutes':hold,'bps':bps,'eligible_signals':len(indices),
                       'symbols':len(profit),'mean_ex_top5_bps':float(ret[trim].mean()*1e4) if trim.any() else None,'top5_profit_share':float(profit.head(5).sum()/profit.sum()),
                       'stale_exit_references':int((~np.isfinite(cp[d[picked],s[picked],m[picked]+hold])).sum()),**metrics(ret,d[picked],days,10)}
                    rows.append(record);metrics_by_bps.append(record)
                if any(x['bps'] in [-1,0] and x['positive_months']>=10 and x['without_best5_days_pct']>0 and x['trades']>=1000 for x in metrics_by_bps):
                    survivors.append(pd.DataFrame({'candidate_id':cid,'day':d[picked],'symbol_code':s[picked],'signal_minute':m[picked],
                      'direction':side,'score':strength[picked],'entry_price':ee,'exit_price':xx,'hold_minutes':hold}))
                rules.append({'candidate_id':cid,'threshold':definitions[name][0],'hold_minutes':hold,'eligible_signals':len(indices),'nomination_trades':len(picked),'ranking':'causal strength descending; identity ties','slots':10})
        print('BAR_MECHANISM_COMPLETE',name,flush=True)
    result=pd.DataFrame(rows);result.to_parquet(OUT/'bar_sensitivity.parquet',index=False)
    pd.DataFrame(rules).to_parquet(OUT/'rules.parquet',index=False)
    if survivors:pd.concat(survivors,ignore_index=True).to_parquet(OUT/'survivor_nominations.parquet',index=False)
    for bps in [-1,0,1]:
        z=result[result.bps==bps].sort_values(['positive_months','without_best5_days_pct'],ascending=False)
        print('BPS',bps,z[['candidate_id','trades','symbols','mean_trade_bps','return_pct','positive_months','positive_week_fraction','max_dd_pct','mean_ex_top5_bps']].head(6).to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','screen']);a=p.parse_args();globals()[a.stage]()
