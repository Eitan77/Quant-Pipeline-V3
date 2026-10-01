"""Small deterministic execution diagnostic; never an independent profitability test."""
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from dotenv import dotenv_values

ROOT=Path('D:/AlgoResearch/Quant-Pipeline-V3/runs/v3_comprehensive_20260923')
OUT=ROOT/'research/intraday_strategy_20260928'
DEST=OUT/'quote_sample'; DEST.mkdir(exist_ok=True)
axes=json.loads((OUT/'price_axes.json').read_text())
source=duckdb.connect('D:/AlgoResearch/Quant-Pipeline-V3/cache/source/20240401_20260430/catalog.duckdb',read_only=True)
symbols=dict(source.execute('select security_id,symbol from security_master').fetchall())
samples=[]
for name,file,col,ident in [('fast10','confirmation_trades.parquet','confirmation_id',302),('fast5','confirmation_trades.parquet','confirmation_id',1004),('core240','topone_trades.parquet','id',1),('fresh15','confirmation_trades.parquet','confirmation_id',840),('reversal60','confirmation_trades.parquet','confirmation_id',892)]:
    frame=pd.read_parquet(OUT/'entry_extension'/file)
    frame=frame[frame[col]==ident].sort_values(['entry_minute','observation_id'])
    for idx in np.linspace(0,len(frame)-1,4,dtype=int):
        row=frame.iloc[idx].to_dict(); row['strategy']=name
        row['symbol']=symbols[axes['securities'][int(row['security_code'])]]
        samples.append(row)
manifest=pd.DataFrame(samples); manifest.to_parquet(DEST/'manifest.parquet',index=False)
lake=duckdb.connect('D:/AlgoResearch/data/raw/alpaca/market/stocks/quotes_sip/schema_v1/quote_lake.duckdb',read_only=True)
results=[]
credentials=dotenv_values('D:/AlgoResearch/.env')
headers={'APCA-API-KEY-ID':credentials.get('ALPACA_API_KEY_ID') or credentials.get('APCA_API_KEY_ID'),'APCA-API-SECRET-KEY':credentials.get('ALPACA_API_SECRET_KEY') or credentials.get('APCA_API_SECRET_KEY')}
def fetch(symbol,start,end):
    rows=[]; token=None
    while True:
        params={'symbols':symbol,'start':start.isoformat(),'end':end.isoformat(),'feed':'sip','sort':'asc','limit':10000}
        if token: params['page_token']=token
        with urlopen(Request('https://data.alpaca.markets/v2/stocks/quotes?'+urlencode(params),headers=headers),timeout=30) as response: payload=json.load(response)
        rows.extend(payload.get('quotes',{}).get(symbol,[])); token=payload.get('next_page_token')
        if not token: break
    return pd.DataFrame([{'ns':pd.Timestamp(v['t']).value,'bid':v['bp'],'ask':v['ap'],'bid_size':v['bs'],'ask_size':v['as']} for v in rows])
for n,r in manifest.iterrows():
    entry=pd.Timestamp(r.entry_minute,unit='m',tz='UTC'); end=pd.Timestamp(r.exit_minute,unit='m',tz='UTC')
    # Entry path is 60 seconds; exit is fixed to original scheduled exit.
    paths=[]
    for label,start,finish in [('entry',entry,entry+pd.Timedelta(seconds=60)),('exit',end,end+pd.Timedelta(seconds=1))]:
        covered=lake.execute('select count(*) from sip_quote_coverage where symbol=? and session_date=? and feed=\'sip\' and download_complete and window_start_ts<=? and window_end_ts>=?',[r.symbol,entry.date(),start.to_pydatetime(),finish.to_pydatetime()]).fetchone()[0]
        q=lake.execute('select epoch_ns(quote_ts) as ns,bid_price as bid,ask_price as ask,bid_size,ask_size from sip_quotes where symbol=? and session_date=? and quote_ts>=? and quote_ts<=? order by quote_ts',[r.symbol,entry.date(),start.to_pydatetime(),finish.to_pydatetime()]).df() if covered else pd.DataFrame()
        cached=DEST/f'{n}_{label}_pre30.parquet'
        if q.empty and cached.exists(): q=pd.read_parquet(cached)
        if q.empty: q=fetch(r.symbol,start-pd.Timedelta(seconds=30),finish)
        q.to_parquet(cached,index=False)
        if not q.empty:
            q=q[(q.bid>0)&(q.ask>=q.bid)&(q.bid_size>0)&(q.ask_size>0)]
            prior=q[q.ns<=start.value].tail(1)
            q=pd.concat([prior,q[q.ns>start.value]],ignore_index=True)
        paths.append(q)
    q,x=paths
    print(n,r.strategy,r.symbol,'entry',len(q),'exit',len(x),flush=True)
    if q.empty or x.empty:
        results.append({'sample':n,'strategy':r.strategy,'status':'missing_coverage_or_quotes'});continue
    q=q[(q.bid>0)&(q.ask>=q.bid)&(q.bid_size>0)&(q.ask_size>0)]
    x=x[(x.bid>0)&(x.ask>=x.bid)&(x.bid_size>0)&(x.ask_size>0)]
    if q.empty or x.empty or q.iloc[0].ns-entry.value>1e9 or x.iloc[0].ns-end.value>1e9:
        results.append({'sample':n,'strategy':r.strategy,'status':'no_valid_arrival'});continue
    first=q.iloc[0]; exit_price=x.iloc[0].ask
    midpoint=(first.bid+first.ask)/2
    # All sampled candidates are shorts. Positive offset demands a higher sale price.
    # These sampled stocks trade above $1; round sell limits upward to whole cents.
    methods=[('market',first.bid)]+[(f'limit_{offset:+d}',np.ceil((midpoint*(1+offset/10000)-1e-10)*100)/100) for offset in [-1,0,1,2,3,4,5]]
    for method,limit in methods:
        hits=q[(q.ns>max(first.ns,entry.value))&(q.bid>limit)]
        immediate=method=='market' or limit<=first.bid
        filled=immediate or not hits.empty
        fill_price=first.bid if immediate else limit
        gross=(1-exit_price/fill_price)*10000 if filled else np.nan
        record={'sample':n,'strategy':r.strategy,'symbol':r.symbol,'method':method,'status':'ok','filled_proxy':filled,'bar_gross_bps':r.gross_bps,'quote_gross_bps':gross,'arrival_spread_bps':(first.ask/first.bid-1)*10000,'entry_quote_age_seconds':(entry.value-first.ns)/1e9,'exit_quote_age_seconds':(end.value-x.iloc[0].ns)/1e9,'wait_seconds':0 if method=='market' else (hits.iloc[0].ns-entry.value)/1e9 if filled else 60}
        record.update({'limit_price':limit,'entry_fill_price':fill_price if filled else np.nan,'exit_fill_price':exit_price if filled else np.nan,'immediate':immediate,'wait_seconds':0 if immediate else (hits.iloc[0].ns-entry.value)/1e9 if filled else 60,'fresh_quotes':(entry.value-first.ns)<=5e9 and (end.value-x.iloc[0].ns)<=5e9,'bps_per_attempt':gross if filled else 0})
        results.append(record)
pd.DataFrame(results).to_parquet(DEST/'results.parquet',index=False)
valid=pd.DataFrame(results).query('status == "ok" and fresh_quotes == True')
summary=valid.groupby(['strategy','method']).agg(attempts=('sample','count'),filled=('filled_proxy','sum'),bps_per_fill=('quote_gross_bps','mean'),bps_per_attempt=('bps_per_attempt','mean'),wait_seconds=('wait_seconds','mean')).reset_index()
summary.to_parquet(DEST/'summary.parquet',index=False)
print(summary.to_string(index=False),flush=True)
lines=['# Quote-fill sample: corrected execution comparison','', 'Supersedes the prior quote report and its extra cost tables. No hypothetical cost or rebate is deducted or added to quote-fill returns. Original bar-cost screens remain separate discovery tools.','', 'Twenty predetermined trades: four each from fast10, fast5, core240, fresh15 and reversal60. Limits are -1, 0, 1, 2, 3, 4, 5 bps relative to arrival midpoint; all trades are short, so positive means a higher sale price. Sell limits are rounded upward to cents. Marketable limits receive the arrival bid. Other limits require a later bid strictly above the limit within 60 seconds, with fills priced at the limit. Exits buy at the scheduled exit ask. No fill means zero profit for that attempted opportunity.','', 'Use latest valid quote before arrival, or first within one second afterward. Primary results require entry and exit quotes no more than five seconds old. Two attempts fail the quote-arrival/freshness checks, leaving 18 usable attempts. Market entries/exits are small-order quote-price estimates; passive fills are move-through proxies, not queue-confirmed executions. Quote size positivity is checked, but capital-sized capacity, latency and order acknowledgements are not simulated. Actual broker fees/rebates are not included. Only the entry waiting path and scheduled exit window are replayed, not dynamic exits during the holding period.','', '| Strategy | Entry | Fills / attempts | Bps / fill | Bps / attempt | Mean wait seconds, including cancellations |','|---|---|---:|---:|---:|---:|']
for r in summary.itertuples():lines.append(f'| {r.strategy} | {r.method} | {r.filled}/{r.attempts} | {r.bps_per_fill:.2f} | {r.bps_per_attempt:.2f} | {r.wait_seconds:.1f} |')
lines+=['','The sample is too small to establish expected value, frequency, or a winning offset. Repeated identical results across offsets can reflect cent rounding and the same filled trades. Compare profit per attempt, not just the conditional average of fills. No annualization or promotion is justified.','', 'Artifacts: quote_sample/manifest.parquet, results.parquet, summary.parquet and raw *_pre30.parquet quote windows. Reproduce with tools/intraday_quote_sample.py.']
Path('docs/research/V3_QUOTE_SAMPLE_2026-09-28.md').write_text('\n'.join(lines)+'\n')
