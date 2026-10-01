"""Frozen seven-price quote diagnostic; actual misses and forced exits retained."""
import argparse,json,time,hashlib,threading
from pathlib import Path
import duckdb,numpy as np,pandas as pd,exchange_calendars as xc
import competition_fresh_quotes as engine
from competition_fresh_risk import funded
from competition_scalp import metrics
from competition_under2d import ROOT
from intraday_causal_restart import OUT as RESEARCH
from competition_slot_comparison import select

DEST=RESEARCH/'limits_breadth_coarse_probe';DEST.mkdir(exist_ok=True)
LEVELS=[-1,0,1,2,3,4,5]
RULE='breadth_jump_coarse_30m'
DIAGNOSTIC_DAYS_PER_MONTH=0

def prepare_minute():
    minute=RESEARCH/'minute_mechanisms'
    opening=RULE.startswith('gap_')
    breakout=RULE.startswith(('range_','quiet_range_'))
    canonical=RULE.startswith('canonical_')
    special=opening or breakout or canonical
    source=(ROOT/'research'/('canonical_intraday_tail_context_20260930' if RULE.startswith('canonical_tail_') else 'canonical_intraday_hypotheses_20260930')) if canonical else (RESEARCH/('opening_mechanisms' if opening else 'opening_breakout_mechanisms') if special else minute)
    if canonical:
        check=json.loads((source/'finalist_input_audit.json').read_text())
        assert check['passed'] and RULE in check['policies'],'No quote replay without completed finalist audit'
    axes=json.loads((minute/'axes.json').read_text())
    with duckdb.connect() as c:
        f=c.execute('SELECT * FROM read_parquet(?) WHERE candidate_id=?',
          [str(source/('canonical_policy_pool.parquet' if canonical else ('nominations.parquet' if special else 'survivor_nominations.parquet'))),RULE]).fetchdf()
    assert len(f), 'Candidate absent from screened survivors'
    dates=axes['days'] if special else pd.Series(axes['days']).groupby(pd.Series(axes['days']).str[:7]).head(1).tolist()
    if special and DIAGNOSTIC_DAYS_PER_MONTH:
        dates=pd.Series(axes['days']).groupby(pd.Series(axes['days']).str[:7]).head(DIAGNOSTIC_DAYS_PER_MONTH).tolist()
    day=np.array(axes['days'])[f.day.to_numpy()]
    entry_min=f.signal_minute.to_numpy()+1
    blocks=[(30,390)] if canonical else ([(5,6)] if opening else ([(30,241)] if breakout else ([(35,125),(210,300)] if RULE=='momentum_confirmation_etfs_5m' else [(35,45),(150,160),(300,310)])))
    keep=np.isin(day,dates)&np.logical_or.reduce([(entry_min>=a)&(entry_min<b) for a,b in blocks])
    f=f[keep].copy().reset_index(drop=True)
    d=f.day.to_numpy();s=f.symbol_code.to_numpy();m=f.signal_minute.to_numpy()
    f['security_id']=np.array(axes['security_ids'])[s];f['symbol']=np.array(axes['symbols'])[s]
    f['session_date']=pd.to_datetime(np.array(axes['days'])[d])
    # Preserve historical aliases for provider quote requests.
    pit=pd.read_parquet('reference/sp500_pit_membership_daily.parquet')
    pit=pit[pit.in_universe][['security_id','session_date','symbol']].drop_duplicates()
    pit['session_date']=pd.to_datetime(pit.session_date)
    assert not pit.duplicated(['security_id','session_date']).any()
    f=f.merge(pit.rename(columns={'symbol':'pit_symbol'}),on=['security_id','session_date'],how='left',validate='many_to_one')
    f['symbol']=f.pit_symbol.fillna(f.symbol);f=f.drop(columns='pit_symbol')
    f['entry_ts']=pd.to_datetime(np.array(axes['open_epoch_ns'])[d]+(m+1)*60_000_000_000,utc=True).as_unit('ns')
    f['exit_ts']=f.entry_ts+pd.to_timedelta(f.hold_minutes,unit='m')
    f['decision_ts']=f.entry_ts;f['rank_score']=f.score
    f['observation_id']=(d*len(axes['symbols'])+s)*390+m;f['order_id']=np.arange(len(f))
    f.to_parquet(DEST/'policy_pool.parquet',index=False)
    low=np.load(minute/'low.npy',mmap_mode='r');high=np.load(minute/'high.npy',mmap_mode='r')
    bars=[]
    for leg,offset in [('entry',np.zeros(len(f),dtype=int)),('exit',f.hold_minutes.to_numpy())]:
        idx=m+offset+1
        bars.append(pd.DataFrame({'security_id':f.security_id,'symbol':f.symbol,'stamp':f[leg+'_ts'],
          'low':low[d,s,idx],'high':high[d,s,idx]}))
    pd.concat(bars).drop_duplicates(['security_id','stamp']).to_parquet(DEST/'endpoint_bars.parquet',index=False)
    rule=pd.read_parquet(source/'rules.parquet');definition=rule[rule.candidate_id==RULE].iloc[0].to_dict()
    if canonical:
        definition['input_audit_sha256']=hashlib.sha256((source/'finalist_input_audit.json').read_bytes()).hexdigest()
        definition['evidence_nominations_sha256']=hashlib.sha256((source/'EVIDENCE_NOMINATIONS.json').read_bytes()).hexdigest()
    definition.update({'sample_dates':dates,'sample_entry_minutes_after_open':blocks,'attempts':len(f),
      'selectivity_controls':[] if not RULE.startswith('shock_') else ['all frozen nominations','shock strength at least 3','strongest three nominated names per minute','strongest nominated name per minute'],
      'source_scope':json.loads((source/'scope.json').read_text()),
      'diagnostic_sampling':((f'First {DIAGNOSTIC_DAYS_PER_MONTH} known discovery sessions each month, all frozen nominations; not annual performance.' if DIAGNOSTIC_DAYS_PER_MONTH else 'Every known discovery session, all frozen nominations. Complete annual replay.') if special else 'First known discovery session each month, fixed entry blocks recorded above, frozen before pulls. Fragment attainability diagnostic, not annual performance.'),
      'prescribed_bps_per_side':LEVELS,'fees':0,'entry_activation_seconds':5,'exit_activation_seconds':5,
      'selection_delay_seconds':4,'entry_expiry_seconds':59,'exit_limit_expiry_seconds':54,'cancel_ack_assumed_seconds':55,
      'forced_exit_seconds':56,'quote_age_max_seconds':2,'forced_price':'First fresh valid book at/from +56 seconds strictly before session close; long min(bid,sell limit), short max(ask,buy limit). Sparse missing coverage extends up to 180 seconds.',
      'holdouts_accessed':False,'quote_attainability_is_live_order_fill_proof':False,'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (DEST/'FROZEN_REPLAY_SOURCE.py').write_bytes(Path(__file__).read_bytes())
    (DEST/'FROZEN_PROBE.json').write_text(json.dumps(definition,indent=2,default=lambda v:v.tolist() if isinstance(v,np.ndarray) else (v.item() if isinstance(v,np.generic) else str(v))))
    print('FROZEN_MINUTE_PROBE',RULE,len(f),'attempts',len(dates),'dates',flush=True)

def prepare():
    if RULE!='breadth_jump_coarse_30m':return prepare_minute()
    f=pd.read_parquet(RESEARCH/'initial_policy_pool.parquet');f=f[f.candidate_id==RULE].copy()
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
    dates=pd.Series(cal.index,index=cal.index).groupby(cal.index.strftime('%Y-%m')).head(2).dt.date.tolist()
    f=f[f.session_date.dt.date.isin(dates)].copy().reset_index(drop=True);f['order_id']=np.arange(len(f))
    f.to_parquet(DEST/'policy_pool.parquet',index=False)
    points=pd.concat([f[['security_id',col]].rename(columns={col:'stamp'}) for col in ['entry_ts','exit_ts']]).drop_duplicates()
    with duckdb.connect() as c:
        c.execute('SET threads=4');c.register('points',points)
        bars=c.execute('''SELECT p.security_id,p.stamp,b.symbol,b.execution_low AS "low",b.execution_high AS "high"
            FROM read_parquet(?) b JOIN points p ON p.security_id=b.security_id AND p.stamp=b.bar_start_ts_utc''',
            [str(ROOT/'cache/calculation_panels/intraday_5m.parquet')]).fetchdf()
    bars=bars.drop_duplicates(['security_id','stamp']);bars.to_parquet(DEST/'endpoint_bars.parquet',index=False)
    definition=next(x for x in json.loads((RESEARCH/'initial_rules.json').read_text()) if x['candidate_id']==RULE)
    definition.update({'diagnostic_dates':'First two known trading sessions of every discovery month; frozen before pulls. No outcome-dependent sampling.',
      'sample_dates':[str(x) for x in dates],'attempts':len(f),'prescribed_bps_per_side':LEVELS,'fees':0,
      'entry_activation_seconds':5,'exit_activation_seconds':5,'selection_delay_seconds':4,'entry_expiry_seconds':59,
      'exit_limit_expiry_seconds':54,'forced_exit_seconds':56,'quote_age_max_seconds':2,'cancel_ack_assumed_seconds':55,
      'forced_price':'Long min(fresh bid, sell limit); short max(fresh ask, buy limit). Missing liabilities block results.',
      'same_session_stale_exit_reference_fallback':True,'quote_attainability_is_live_order_fill_proof':False,'holdouts_accessed':False,
      'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (DEST/'FROZEN_PROBE.json').write_text(json.dumps(definition,indent=2));print('FROZEN_LIMIT_PROBE',len(f),'attempts',len(dates),'preselected discovery dates',flush=True)

def replay():
    assert (DEST/'FROZEN_PROBE.json').exists()
    f=pd.read_parquet(DEST/'policy_pool.parquet');bars=pd.read_parquet(DEST/'endpoint_bars.parquet')
    # Exact keyed merge; OHLC determines download routing only.
    touch=f.merge(bars.rename(columns={'stamp':'entry_ts'}),on=['security_id','entry_ts'],how='left',suffixes=('','_bar'),validate='many_to_one')
    touched=touch.low.le(touch.entry_price*1.0005).where(touch.direction==1,touch.high.ge(touch.entry_price*.9995))
    f['entry_bar_touch']=touched.to_numpy();f['entry_bar_missing']=touch.low.isna().to_numpy()
    engine.OUT=DEST;engine.Q=(RESEARCH/'minute_quote_cache' if RULE!='breadth_jump_coarse_30m' else DEST/'quotes');engine.Q.mkdir(exist_ok=True)
    engine.HEADERS=engine.transport.api_headers();engine.transport.WINDOW_SECONDS=62
    engine.ACTIVATION_SECONDS=5;engine.EXIT_ACTIVATION_SECONDS=5
    # Pace every HTTP page across workers, keeping retries/cache bounded.
    original_open=engine.transport.urlopen;lock=threading.Lock();last=[0.]
    def paced(*args,**kwargs):
        with lock:
            delay=max(0.,.4-(time.monotonic()-last[0]))
            if delay:time.sleep(delay)
            last[0]=time.monotonic()
        return original_open(*args,**kwargs)
    engine.transport.urlopen=paced
    ep=engine.paths(engine.download(engine.windows(f[f.entry_bar_touch|f.entry_bar_missing],'entry'),'entry'))
    possible=[]
    for r in f.itertuples():
        p=ep.get((r.entry_ts,r.symbol));limit=r.entry_price*(1+r.direction*5/1e4)
        if p is not None and len(p) and ((p.ask_price.min()<=limit) if r.direction==1 else (p.bid_price.max()>=limit)):possible.append(r.order_id)
    xp=engine.paths(engine.download(engine.windows(f[f.order_id.isin(possible)],'exit'),'exit'),exit_leg=True)
    records=[]
    for r in f.itertuples():
        e=ep.get((r.entry_ts,r.symbol));x=xp.get((r.exit_ts,r.symbol))
        for bps in LEVELS:
            el=r.entry_price*(1+r.direction*bps/1e4);xl=r.exit_price*(1-r.direction*bps/1e4)
            ef=e[(e.ask_price<=el) if r.direction==1 else (e.bid_price>=el)].head(1) if e is not None else pd.DataFrame()
            filled=bool(len(ef));xf=x[((x.bid_price>=xl) if r.direction==1 else (x.ask_price<=xl))&(x.quote_ts<=r.exit_ts+pd.Timedelta(seconds=54))].head(1) if x is not None else pd.DataFrame()
            limit_exit=filled and bool(len(xf));force=filled and not limit_exit;book=pd.DataFrame();force_clock=r.exit_ts+pd.Timedelta(seconds=56)
            if force and x is not None:
                before=x[x.quote_ts<=force_clock].tail(1)
                if len(before) and (force_clock-before.quote_ts.iloc[0]).total_seconds()<=2:
                    book=before.copy();book['quote_ts']=force_clock
                else:book=x[x.quote_ts>force_clock].head(1)
            priced=not filled or limit_exit or bool(len(book))
            price=xl if limit_exit else ((min(float(book.bid_price.iloc[0]),xl) if r.direction==1 else max(float(book.ask_price.iloc[0]),xl)) if force and priced else np.nan)
            records.append({'order_id':r.order_id,'bps':bps,'entry_filled':filled,'limit_exit':limit_exit,'forced_exit':force,'priced':priced,
              'entry_fill_ts':ef.quote_ts.iloc[0] if filled else pd.NaT,'exit_fill_ts':xf.quote_ts.iloc[0] if limit_exit else (book.quote_ts.iloc[0] if force and priced else pd.NaT),
              'executed_entry_price':el if filled else np.nan,'executed_exit_price':price,
              'return_value':r.direction*(price/el-1) if filled and priced else (0. if not filled else np.nan)})
    detail=pd.DataFrame(records)
    for col in ['entry_fill_ts','exit_fill_ts']:detail[col]=pd.to_datetime(detail[col],utc=True).dt.as_unit('ns')
    missing=detail[~detail.priced].merge(f[['order_id','symbol','exit_ts','direction','exit_price']],on='order_id')
    # Forced intraday liabilities need the first fresh executable book after
    # second 56. Extend only these sparse coverage gaps; the limit cutoff and
    # every original order price stay unchanged.
    if len(missing):
        force_dir=DEST/'forced_quotes';force_dir.mkdir(exist_ok=True);engine.transport.WINDOW_SECONDS=182
        calendar=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule
        closes=dict(zip(calendar.index.date,pd.to_datetime(calendar['close'],utc=True)))
        recovered={}
        for ts,g in missing.groupby('exit_ts',sort=True):
            names=sorted(g.symbol.unique());digest=hashlib.sha256(','.join(names).encode()).hexdigest()[:12]
            path=force_dir/f'{ts.strftime("%Y%m%dT%H%M%S")}_{digest}.parquet';force_clock=ts+pd.Timedelta(seconds=56)
            if path.exists():q=pd.read_parquet(path)
            else:
                q=engine.transport.fetch_window(force_clock-pd.Timedelta(seconds=2),names,engine.HEADERS);q.to_parquet(path,index=False)
            q=q[(q.bid_price>0)&(q.ask_price>=q.bid_price)&(q.bid_size>0)&(q.ask_size>0)&(q.quote_ts<closes[ts.tz_convert('America/New_York').date()])].sort_values('quote_ts')
            for symbol,p in q.groupby('symbol'):
                before=p[p.quote_ts<=force_clock].tail(1)
                if len(before) and (force_clock-before.quote_ts.iloc[0]).total_seconds()<=2:
                    book=before.iloc[0].copy();book['quote_ts']=force_clock
                else:
                    later=p[p.quote_ts>force_clock].head(1)
                    if later.empty:continue
                    book=later.iloc[0]
                recovered[(ts,symbol)]=book
        for r in missing.itertuples():
            book=recovered.get((r.exit_ts,r.symbol))
            if book is None:continue
            limit=r.exit_price*(1-r.direction*r.bps/1e4)
            price=min(float(book.bid_price),limit) if r.direction==1 else max(float(book.ask_price),limit)
            idx=(detail.order_id==r.order_id)&(detail.bps==r.bps)
            ep=float(detail.loc[idx,'executed_entry_price'].iloc[0]);detail.loc[idx,'priced']=True
            detail.loc[idx,'executed_exit_price']=price;detail.loc[idx,'exit_fill_ts']=book.quote_ts
            detail.loc[idx,'return_value']=r.direction*(price/ep-1)
        (DEST/'forced_liability_coverage.json').write_text(json.dumps({'gap_order_offset_pairs':len(missing),'extra_windows':missing.exit_ts.nunique(),
          'priced_after_recovery':int((~detail.priced).sum())==0,'limit_prices_or_cutoff_changed':False,
          'force_rule':'First fresh valid book at/from +56 seconds, strictly before known session close. Only sparse missing-liability windows extended up to 180 seconds.'},indent=2))
    detail.to_parquet(DEST/'quote_outcomes.parquet',index=False)
    cal=xc.get_calendar('XNYS',start='2025-05-01',end='2026-04-30').schedule;days=cal.index.strftime('%Y-%m-%d').tolist();rows=[];ledgers=[]
    for bps in LEVELS:
        candidate=f.merge(detail[detail.bps==bps],on='order_id',validate='one_to_one')
        if not candidate.priced.all():
            rows.append({'bps':bps,'status':'unpriced_liabilities','unpriced':int((~candidate.priced).sum())});continue
        selected=select(f,detail[detail.bps==bps].rename(columns={'return_value':'return'}),10,4)
        g=selected.rename(columns={'return':'return_value'})
        budgets,cash,mincash=funded(g,10,0);g['budget']=g.order_id.map(budgets).fillna(0);g['funded_pnl']=g.budget*g.return_value
        ledgers.append(g);fills=g[g.entry_filled];day=pd.Index(days).get_indexer(g.entry_ts.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d'))
        rows.append({'bps':bps,'status':'complete_quote_diagnostic','attempts':len(g),'fills':len(fills),'forced_exits':int(g.forced_exit.sum()),
          'mean_filled_bps':float(fills.return_value.mean()*1e4),'cash_funded_probe_return_pct':(cash-1)*100,'minimum_cash':mincash,
          'both_limits':int(g.limit_exit.sum()),'win_fraction':float((fills.return_value>0).mean()),
          **metrics(g.return_value.to_numpy(),day,days,10)})
    pd.DataFrame(rows).to_parquet(DEST/'quote_summary.parquet',index=False)
    if ledgers:pd.concat(ledgers,ignore_index=True).to_parquet(DEST/'quote_attempts.parquet',index=False)
    print('LIMIT_PROBE_RESULT',pd.DataFrame(rows).reindex(columns=['bps','status','attempts','fills','forced_exits','mean_filled_bps','cash_funded_probe_return_pct','positive_months','unpriced']).to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','replay']);p.add_argument('--candidate',default=RULE);p.add_argument('--sample-first-sessions-per-month',type=int,default=0);a=p.parse_args()
    RULE=a.candidate
    DIAGNOSTIC_DAYS_PER_MONTH=a.sample_first_sessions_per_month
    if RULE!='breadth_jump_coarse_30m':DEST=RESEARCH/('limits_'+RULE+('_diagnostic' if DIAGNOSTIC_DAYS_PER_MONTH else '_probe'));DEST.mkdir(exist_ok=True)
    globals()[a.stage]()
