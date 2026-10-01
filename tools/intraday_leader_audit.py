from intraday_strategy_search import *
def audit_finalists():
    from quant_pipeline.alpha_discovery.features.base import FeatureBuilder
    from quant_pipeline.alpha_discovery.models import CompiledFeatureSpec,TimeScale
    obs=pd.read_parquet(ROOT/'cache/features/intraday_5m/observations.parquet')
    definitions=pd.read_parquet(OUT/'breadth_extension/rules.parquet').set_index('rule_id')
    trades=pd.read_parquet(OUT/'breadth_extension/leader_trades.parquet')
    registry=pd.read_parquet(ROOT/'feature_registry.parquet').set_index('feature_id')
    refs={}
    for meta in (ROOT/'cache/features/intraday_5m').glob('*.json'):
        m=json.loads(meta.read_text())
        for i,f in enumerate(m.get('columns',[])):refs[f]=(meta.with_suffix('.npy'),i)
    checks=[]
    for cid in [115,78]:
        rule=definitions.loc[cid];subset=trades[(trades.rule_id==cid)&(trades.slots==1)]
        for pos in [0,len(subset)//2,len(subset)-1]:
            oid=int(subset.iloc[pos].observation_id);o=obs.iloc[oid];sid=o.security_id
            f=pd.read_parquet(ROOT/f'cache/local_feature_panels/intraday_5m/security_id={sid}')
            # Truncate all future observations before recomputing the signal.
            f=f[(f.session_date==o.session_date)&(f.decision_ts<=o.decision_ts)].copy()
            f['security_id']=sid
            builder=FeatureBuilder(f)
            for feature in [rule.feature_a]:
                record=registry.loc[feature].to_dict();parameters=json.loads(record.pop('parameters'))
                label=record.pop('scale');scale=TimeScale('minutes',int(label[:-1]),label)
                spec=CompiledFeatureSpec(feature_id=feature,scale=scale,parameters=parameters,**record)
                v=builder.build(spec);idx=builder.frame.index[builder.frame.observation_id.eq(oid)][0]
                expected=float(v.loc[idx]);p,col=refs[feature];cached=float(np.load(p,mmap_mode='r')[oid,col])
                checks.append({'candidate_id':cid,'observation_id':oid,'feature':feature,'cached':cached,
                    'prefix_recomputed':expected,'matches':bool(np.isclose(cached,expected,rtol=1e-4,atol=1e-7,equal_nan=True))})
        print('PREFIX AUDIT',cid,flush=True)
    (OUT/'breadth_extension/leader_feature_audit.json').write_text(json.dumps(checks,indent=2))
    print('AUDIT',sum(c['matches'] for c in checks),len(checks),flush=True)

audit_finalists()
