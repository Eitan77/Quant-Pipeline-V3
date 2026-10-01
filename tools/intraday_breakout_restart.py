"""Opening-range expansion: participation versus a quiet initial range."""
import argparse,json
import numpy as np,pandas as pd,torch
from intraday_minute_restart import OUT as MINUTE,reserve
from intraday_causal_restart import OUT as RESEARCH
from competition_scalp import metrics

OUT=RESEARCH/'opening_breakout_mechanisms';OUT.mkdir(exist_ok=True)
LEVELS=[-1,0,1,2,3,4,5]

def run():
    torch.set_num_threads(4);assert torch.cuda.is_available()
    axes=json.loads((MINUTE/'axes.json').read_text());days=axes['days'];D,S=len(days),len(axes['symbols']);ends=np.array(axes['session_minutes'])
    cube={k:np.load(MINUTE/(k+'.npy'),mmap_mode='r') for k in ['close','high','low','volume']}
    f=pd.read_parquet(RESEARCH/'opening_mechanisms/daily_inputs.parquet')
    d=pd.Index(days).get_indexer(f.session_date.dt.strftime('%Y-%m-%d'));s=pd.Index(axes['security_ids']).get_indexer(f.security_id);valid=(d>=0)&(s>=0);f=f[valid];d,s=d[valid],s[valid]
    inputs={k:np.full((D,S),np.nan) for k in ['prior_sigma','prior_dollar_volume','prior_close','split_factor']}
    for k in inputs:inputs[k][d,s]=f[k].to_numpy()
    clean=np.zeros((D,S),bool);clean[d,s]=f.prior_scale_clean.to_numpy()
    stocks=~np.isin(np.array(axes['symbols']),['SPY','QQQ']);volume=np.where(stocks[None,:]&clean,inputs['prior_dollar_volume'],np.nan)
    liquid=volume>=np.nanquantile(volume,.9,axis=1)[:,None]
    events=[]
    for first in range(0,D,22):
        last=min(D,first+22);p,h,l,v=[torch.as_tensor(np.array(cube[k][first:last]),device='cuda') for k in ['close','high','low','volume']]
        upper=h[:,:,:30].max(dim=2).values;lower=l[:,:,:30].min(dim=2).values
        intact=torch.isfinite(h[:,:,:30]).all(2)&torch.isfinite(l[:,:,:30]).all(2)&torch.isfinite(p[:,:,:30]).all(2)
        width=(upper-lower)/p[:,:,29];normalized_width=width/torch.as_tensor(inputs['prior_sigma'][first:last],device='cuda')
        means=torch.full_like(v,torch.nan);means[:,:,20:]=v[:,:,:-1].unfold(2,20,1).mean(dim=-1)
        relative_volume=v/means
        above=p>upper[:,:,None];below=p<lower[:,:,None];previous=torch.full_like(p,torch.nan);previous[:,:,1:]=p[:,:,:-1]
        crossed=(above&(previous<=upper[:,:,None]))|(below&(previous>=lower[:,:,None]))
        crossed[:,:,:30]=False;crossed[:,:,240:]=False
        ratio=p[:,:,0]/torch.as_tensor(inputs['split_factor'][first:last]*inputs['prior_close'][first:last],device='cuda')
        eligible=torch.as_tensor(liquid[first:last]&clean[first:last],device='cuda')&intact&(width>0)&torch.isfinite(normalized_width)&(ratio>.5)&(ratio<2)
        crossed=crossed&eligible[:,:,None]&torch.isfinite(relative_volume)
        # First observed boundary crossing per stock/session. Later outcomes
        # never decide which crossing counts.
        any_event=crossed.any(2);dd,ss=torch.where(any_event);mm=crossed.long().argmax(2)[dd,ss]
        side=torch.where(above[dd,ss,mm],1,-1)
        events.append(pd.DataFrame({'day':dd.cpu().numpy()+first,'symbol_code':ss.cpu().numpy(),'signal_minute':mm.cpu().numpy(),
          'direction':side.cpu().numpy(),'score':relative_volume[dd,ss,mm].cpu().numpy(),'normalized_width':normalized_width[dd,ss].cpu().numpy(),
          'boundary':torch.where(side==1,upper[dd,ss],lower[dd,ss]).cpu().numpy()}))
        del p,h,l,v,upper,lower,intact,width,normalized_width,means,relative_volume,above,below,previous,crossed,ratio,eligible,any_event,dd,ss,mm,side
        torch.cuda.empty_cache()
    f=pd.concat(events,ignore_index=True);d=f.day.to_numpy();s=f.symbol_code.to_numpy();m=f.signal_minute.to_numpy();score=f.score.to_numpy()
    profiles={'range_break_chase':np.ones(len(f),bool),'range_break_retest':np.ones(len(f),bool),
      'quiet_range_retest':f.normalized_width.to_numpy()<=.75,
      'quiet_range_volume_retest':(f.normalized_width.to_numpy()<=.75)&(score>=1.5)}
    marks=np.array(cube['close']);last=np.where(np.isfinite(marks),np.arange(390)[None,None,:],0);np.maximum.accumulate(last,axis=2,out=last)
    marks=np.take_along_axis(marks,last,axis=2);rows=[];nominations=[];rules=[]
    for profile,condition in profiles.items():
        for hold in [15,30,60]:
            indices=np.flatnonzero(condition&(m+hold<=ends[d]-2));dd,ss,mm=d[indices],s[indices],m[indices]
            order=np.lexsort((ss,-score[indices],mm,dd));picked=indices[reserve(order,dd,ss,mm,hold,10,S)]
            ee=cube['close'][d[picked],s[picked],m[picked]] if profile.endswith('chase') else f.boundary.to_numpy()[picked]
            xx=marks[d[picked],s[picked],m[picked]+hold];side=f.direction.to_numpy()[picked];cid=f'{profile}_{hold}m'
            assert np.isfinite(ee).all() and np.isfinite(xx).all()
            for bps in LEVELS:
                ret=side*(xx*(1-side*bps/1e4)/(ee*(1+side*bps/1e4))-1);profit=pd.Series(ret).groupby(s[picked]).sum().sort_values(ascending=False);trim=~np.isin(s[picked],profit.head(5).index)
                rows.append({'candidate_id':cid,'hold_minutes':hold,'bps':bps,'symbols':len(profit),'eligible_signals':len(indices),
                  'mean_ex_top5_bps':float(ret[trim].mean()*1e4),'stale_exit_references':int((~np.isfinite(cube['close'][d[picked],s[picked],m[picked]+hold])).sum()),**metrics(ret,d[picked],days,10)})
            nominations.append(pd.DataFrame({'candidate_id':cid,'day':d[picked],'symbol_code':s[picked],'signal_minute':m[picked],
              'direction':side,'score':score[picked],'entry_price':ee,'exit_price':xx,'hold_minutes':hold}))
            rules.append({'candidate_id':cid,'hold_minutes':hold,'ranking':'Current completed-minute volume / preceding twenty-minute average volume, descending','slots':10})
    result=pd.DataFrame(rows);result.to_parquet(OUT/'bar_sensitivity.parquet',index=False);pd.concat(nominations,ignore_index=True).to_parquet(OUT/'nominations.parquet',index=False);pd.DataFrame(rules).to_parquet(OUT/'rules.parquet',index=False)
    (OUT/'scope.json').write_text(json.dumps({'discovery':['2025-05-01','2026-04-30'],'holdouts_accessed':False,'hypothesis':'Participation-driven expansion beyond the first thirty-minute range; compare chasing with a one-minute passive retest of the known boundary.',
      'universe':'Top decile of previous five-session dollar turnover, PIT stocks only; clean prior price scale.',
      'signal':'First eligible completed-minute close crossing the initial thirty-minute high/low, between 10:00 and 13:30 ET; complete preceding volume history required; one crossing per stock/session.',
      'controls':['plain chase','plain boundary retest','quiet opening width <=0.75 prior daily-return volatility','quiet range and contemporaneous relative volume >=1.5'],
      'entry_reference':'Completed close for chase; known opening high/low for retest. All seven original offsets applied before quotes. Retest orders expire after 59 seconds.',
      'ranking':'Relative volume, observable before order; ten scheduled reservation lanes, one position per identity.',
      'holds_minutes':[15,30,60],'fees':0,'prescribed_bps_per_side':LEVELS,'bar_full_fills_are_hypothetical':True},indent=2))
    f.to_parquet(OUT/'first_crossings.parquet',index=False)
    print(result[result.bps.isin([-1,0])][['candidate_id','bps','trades','mean_trade_bps','positive_months','positive_week_fraction','mean_ex_top5_bps']].to_string(index=False),flush=True)

def audit():
    axes=json.loads((MINUTE/'axes.json').read_text());cube={k:np.load(MINUTE/(k+'.npy'),mmap_mode='r') for k in ['close','high','low','volume']}
    n=pd.read_parquet(OUT/'nominations.parquet');n=n[n.candidate_id=='range_break_retest_15m'].sample(100,random_state=20260930)
    error=0.
    for r in n.itertuples():
        p=cube['close'][r.day,r.symbol_code];h=cube['high'][r.day,r.symbol_code];l=cube['low'][r.day,r.symbol_code];v=cube['volume'][r.day,r.symbol_code]
        upper=np.max(h[:30]);lower=np.min(l[:30]);side=1 if p[r.signal_minute]>upper else -1
        assert r.direction==side and r.entry_price==(upper if side==1 else lower)
        crossing=((p[30:240]>upper)&(p[29:239]<=upper))|((p[30:240]<lower)&(p[29:239]>=lower))
        volume_score=np.array([v[i]/np.mean(v[i-20:i]) for i in range(30,240)])
        crossing&=np.isfinite(volume_score)
        assert r.signal_minute==np.flatnonzero(crossing)[0]+30
        score=v[r.signal_minute]/v[r.signal_minute-20:r.signal_minute].mean();error=max(error,abs(score-r.score))
        changed=np.array(p);changed[r.signal_minute+1:]*=1.5
        prefix_cross=((changed[30:r.signal_minute+1]>upper)&(changed[29:r.signal_minute]<=upper))|((changed[30:r.signal_minute+1]<lower)&(changed[29:r.signal_minute]>=lower))
        prefix_cross&=np.isfinite(volume_score[:r.signal_minute-29])
        assert np.flatnonzero(prefix_cross)[0]+30==r.signal_minute
    assert error<1e-10
    (OUT/'input_audit.json').write_text(json.dumps({'sampled_nominations':len(n),'maximum_relative_volume_error':error,
      'first_eligible_completed_boundary_crossing_verified':True,'complete_known_volume_history_required':True,'entry_reference_exact_known_opening_boundary':True,'future_price_perturbation_preserves_signal':True},indent=2))
    print('BREAKOUT_AUDIT',len(n),'source checks; maximum error',error,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['screen','audit'],default='screen',nargs='?');a=p.parse_args()
    if a.stage=='audit':audit()
    else:run()
