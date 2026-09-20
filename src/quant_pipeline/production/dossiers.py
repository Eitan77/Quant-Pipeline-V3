from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json,numpy as np,pandas as pd
from quant_pipeline.alpha_discovery.targets.excursions import actual_trade_path_diagnostics
from quant_pipeline.forensics.crossfit import crossfit_surface_diagnostics
from quant_pipeline.forensics.distribution import contribution_concentration,distribution_stats
from quant_pipeline.forensics.inference import session_clustered_mean_se
from quant_pipeline.forensics.interaction import interaction_decomposition
from quant_pipeline.forensics.opportunities import build_episodes,independent_entries_by_exit,independent_entries_fixed_hold,opportunity_timing_summary
from quant_pipeline.forensics.path import direction_aware_excursions,event_path_metrics
from quant_pipeline.forensics.tails import build_tail_mask
from quant_pipeline.production.outputs import ProductionData
from quant_pipeline.production.surface_math import reconstruct_surface

def _table(path,rows,columns=None):
    (rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows,columns=columns)).to_parquet(path,index=False)

def _episodes(obs,active):
    return build_episodes(obs_id=obs.observation_id.to_numpy(),security_id=pd.factorize(obs.security_id,sort=True)[0],session_id=pd.factorize(obs.session_date,sort=True)[0],security_session_seq=obs.groupby("security_id",sort=False).cumcount().to_numpy(),decision_ts_ns=pd.to_datetime(obs.decision_ts,utc=True).astype("int64").to_numpy(),active=active)

def _opportunities(obs,active,ledger):
    eps=_episodes(obs,active); exits=pd.to_datetime(ledger.exit_ts,utc=True,errors="coerce"); entries=pd.to_datetime(ledger.entry_ts,utc=True,errors="coerce"); exit_map={int(obs_id):(None if pd.isna(exit_ts) else int(exit_ts.value)) for obs_id,exit_ts in zip(ledger.observation_id,exits)}; cross=bool(((exits.dt.date!=entries.dt.date)&exits.notna()&entries.notna()).any())
    if cross: accepted=independent_entries_by_exit(episodes=eps,exit_ts_by_obs=exit_map); timing=opportunity_timing_summary(opportunities=accepted,end_ts_by_obs=exit_map)
    else:
        duration=(exits-entries).dropna(); hold_ns=int(duration.median().value) if len(duration) else 0; accepted=independent_entries_fixed_hold(episodes=eps,hold_ns=hold_ns); timing=opportunity_timing_summary(opportunities=accepted,hold_ns=hold_ns)
    return eps,accepted,timing,cross

def _positions(obs,opportunities):
    lookup=pd.Series(np.arange(len(obs)),index=obs.observation_id).to_dict(); return np.asarray([lookup[x.start_obs_id] for x in opportunities if x.start_obs_id in lookup],dtype=int)

def _aligned_stats(raw,direction):
    raw=np.asarray(raw,float); aligned=direction*raw if direction else np.full(raw.shape,np.nan); stats=distribution_stats(aligned); concentration=contribution_concentration(aligned if direction else np.abs(raw)); clean=raw[np.isfinite(raw)]
    return {"raw_mean_bps":float(clean.mean()) if len(clean) else np.nan,"raw_median_bps":float(np.median(clean)) if len(clean) else np.nan,"raw_positive_rate":float(np.mean(clean>0)) if len(clean) else np.nan,"direction_aligned_mean_bps":stats.get("mean_bps",np.nan),"direction_aligned_median_bps":stats.get("median_bps",np.nan),"favorable_rate":stats.get("win_rate",np.nan),"avg_favorable_bps":stats.get("avg_winner_bps",np.nan),"avg_adverse_bps":stats.get("avg_loser_bps",np.nan),**concentration}

def _compatible(data,target):
    fields=("decision_grid","family","return_basis","entry_rule","price_basis")
    return sorted((x for x in data.targets.values() if all(getattr(x,f)==getattr(target,f) for f in fields)),key=lambda x:({"minutes":0,"sessions":1,"session_to_date":2}.get(x.horizon.kind,9),x.horizon.value or 10**9,x.target_id))

def _concentration(raw,aligned,selected,direction):
    contribution=aligned if direction else np.abs(raw); base=pd.DataFrame({"raw":raw,"aligned":aligned,"contribution":contribution,"security":selected.security_id.to_numpy(),"month":pd.to_datetime(selected.session_date).dt.to_period("M").astype(str),"session":selected.session_date.to_numpy()}); views={"baseline":base}
    if len(base):
        by_symbol=base.groupby("security").contribution.sum(); top=by_symbol.nlargest(5).index; by_month=base.groupby("month").contribution.sum(); by_session=base.groupby("session").contribution.sum(); cut=np.nanquantile(base.contribution,.99)
        views|={"remove_best_symbol":base[base.security!=by_symbol.idxmax()],"remove_top_5_symbols":base[~base.security.isin(top)],"remove_best_month":base[base.month!=by_month.idxmax()],"remove_largest_session":base[base.session!=by_session.abs().idxmax()],"remove_top_1pct_favorable_outcomes":base[base.contribution<cut],"winsorize_top_1pct_favorable_outcomes":base.assign(contribution=base.contribution.clip(upper=cut))}
    return [{"view":name,"remaining_n":len(part),"raw_mean_bps":float(part.raw.mean()) if len(part) else np.nan,"absolute_contribution_bps":float(np.abs(part.raw).sum()) if len(part) else np.nan,"direction_aligned_mean_bps":float(part.aligned.mean()) if direction and len(part) else np.nan,"contribution_basis":"direction_aligned" if direction else "raw_absolute","evidence_role":"discovery_diagnostic"} for name,part in views.items()]

def _active_symbol_breakdown(*,candidate_id,obs,y,mask,security,min_local_n):
    active=obs.loc[mask,["security_id"]].copy(); active["raw_bps"]=np.asarray(y)[mask]*1e4; rows=[]; total_abs=float(active.groupby("security_id").raw_bps.sum().abs().sum()) if len(active) else 0.0
    for sec,part in active.groupby("security_id"):
        raw_sum=float(part.raw_bps.sum()); symbol=security.loc[security.security_id==sec,"symbol"]
        rows.append({"candidate_id":candidate_id,"security_id":sec,"symbol":symbol.iloc[0] if len(symbol) else None,"active_n":len(part),"raw_mean_bps":float(part.raw_bps.mean()),"raw_sum_bps":raw_sum,"absolute_contribution_bps":abs(raw_sum),"absolute_contribution_share":abs(raw_sum)/total_abs if total_abs else np.nan,"sign":int(np.sign(raw_sum)),"specialist_min_n_eligible":len(part)>=min_local_n,"evidence_role":"discovery_diagnostic"})
    return rows

def _resolution_comparison_rows(*,candidate_id,row,duals):
    comparison=duals[(duals.pair_id==row["pair_id"])&(duals.target_id==row["target_id"])] if len(duals) else duals
    rows=[{"candidate_id":candidate_id,"resolution":int(x.v3_resolution),"selected_cell":int(x.selected_cell),"selection_kind":"scanner_selected","selected_state_bps":float(x.selected_state_bps),"selected_interaction_lift_bps":float(x.selected_interaction_lift_bps),"selected_frequency":float(x.selected_frequency),"selected_n":int(x.selected_n),"surface_spread_bps":float((x.best_cell_effect-x.worst_cell_effect)*1e4),"neighbor_effect_retention":float(x.neighbor_effect_retention),"plateau_area":int(x.plateau_area),"evidence_role":"discovery_diagnostic"} for x in comparison.sort_values("v3_resolution").itertuples()]
    if row.get("cell_mode")=="explicit": rows.append({"candidate_id":candidate_id,"resolution":int(row["v3_resolution"]),"selected_cell":int(row["selected_cell"]),"selection_kind":"frozen_candidate","selected_state_bps":float(row["selected_state_bps"]),"selected_interaction_lift_bps":float(row["selected_interaction_lift_bps"]),"selected_frequency":float(row["selected_frequency"]),"selected_n":int(row["selected_n"]),"surface_spread_bps":float((row["best_cell_effect"]-row["worst_cell_effect"])*1e4),"neighbor_effect_retention":float(row["neighbor_effect_retention"]),"plateau_area":int(row["plateau_area"]),"evidence_role":"discovery_diagnostic"})
    return rows

def build_candidate_dossiers(*,legacy_run,candidates:pd.DataFrame,candidate_summary:pd.DataFrame,duals:pd.DataFrame,specialist:pd.DataFrame):
    data=ProductionData(legacy_run); root=legacy_run.root/"candidates"; root.mkdir(exist_ok=True); built=[]; security=pd.read_parquet(Path(legacy_run.config.project_root)/"reference/security_master.parquet",columns=["security_id","symbol"]).drop_duplicates("security_id")
    for candidate in candidates.to_dict("records"):
        row=candidate_summary[candidate_summary.candidate_id.eq(candidate["candidate_id"])].iloc[0].to_dict(); grid,obs,a,b,y,mask,a_cell,b_cell=data.selected(row); direction=int(candidate["direction"]); resolution=int(candidate["resolution"]); target=data.targets[candidate["target_id"]]
        ledger=pd.read_parquet(legacy_run.root/"cache"/"targets"/f"{grid}.parquet",filters=[("target_id","=",candidate["target_id"])]); ledger=obs[["observation_id"]].merge(ledger,on="observation_id",how="left",validate="one_to_one")
        eps,opps,timing,cross=_opportunities(obs,mask,ledger); pos=_positions(obs,opps); raw=y[pos]*1e4 if len(pos) else np.asarray([],float); aligned=direction*raw if direction else np.full(raw.shape,np.nan); selected=obs.iloc[pos].copy(); eligible=(a>=0)&(b>=0)&np.isfinite(y); sessions=int(obs.loc[eligible,"session_date"].nunique())
        dossier=root/candidate["candidate_id"]/"dossier"; dossier.mkdir(parents=True,exist_ok=True); selection={k:row.get(k) for k in ("selection_test_effect","cluster_se","test_statistic","p_value","fold_effects","fold_sign_consistency","fold_magnitude_ratio","outlier_cluster_share","cluster_count")}
        summary={"candidate_id":candidate["candidate_id"],"state_key":row.get("state_key"),"return_basis":candidate["return_basis"],"resolution":resolution,"direction":direction,"active_observation_count":int(mask.sum()),"selected_n":int(row["selected_n"]),"selected_frequency":float(row["selected_frequency"]),"selected_state_bps":float(row["selected_state_bps"]),"selected_interaction_lift_bps":float(row["selected_interaction_lift_bps"]),"weighted_state_contribution_bps":float(row["weighted_state_contribution_bps"]),"weighted_interaction_contribution_bps":float(row["weighted_interaction_contribution_bps"]),"episode_count":len(eps),"fresh_signal_count":len(eps),"independent_opportunity_count":len(opps),"eligible_session_count":sessions,"opportunities_per_day":len(opps)/max(sessions,1),"cross_session_exact_exit_independence":cross,"break_even_round_trip_bps":abs(float(row["selected_state_bps"])) if direction else np.nan,"break_even_per_side_bps":abs(float(row["selected_state_bps"]))/2 if direction else np.nan,"evidence_role":"discovery_diagnostic",**timing,**_aligned_stats(raw,direction),**selection}
        _table(dossier/"summary.parquet",[summary]); _table(dossier/"distribution.parquet",[{"candidate_id":candidate["candidate_id"],**_aligned_stats(raw,direction),"evidence_role":"discovery_diagnostic"}]); _table(dossier/"episodes.parquet",[{**asdict(x),"evidence_role":"discovery_diagnostic"} for x in eps])

        chronology=[]
        if len(pos):
            selected["raw_bps"]=raw; selected["aligned_bps"]=aligned; selected["month"]=pd.to_datetime(selected.session_date).dt.to_period("M").astype(str)
            for month,part in selected.groupby("month"): chronology.append({"candidate_id":candidate["candidate_id"],"diagnostic_type":"month","period":month,"active_n":len(part),"frequency":np.nan,"raw_mean_bps":float(part.raw_bps.mean()),"direction_aligned_mean_bps":float(part.aligned_bps.mean()),"independent_opportunities":len(part),"evidence_role":"discovery_diagnostic"})
        unique_sessions=np.sort(pd.unique(pd.to_datetime(obs.session_date)))
        for start in range(0,max(0,len(unique_sessions)-59),20):
            window=unique_sessions[start:start+60]; inside=pd.to_datetime(obs.session_date).isin(window).to_numpy(); active=mask&inside; _,window_opps,_,_=_opportunities(obs,active,ledger)
            chronology.append({"candidate_id":candidate["candidate_id"],"diagnostic_type":"rolling","period":f"{str(window[0])[:10]}:{str(window[-1])[:10]}","active_n":int(active.sum()),"frequency":float(active.sum()/max(1,(eligible&inside).sum())),"raw_mean_bps":float(np.nanmean(y[active])*1e4) if active.any() else np.nan,"direction_aligned_mean_bps":float(direction*np.nanmean(y[active])*1e4) if direction and active.any() else np.nan,"independent_opportunities":len(window_opps),"evidence_role":"discovery_diagnostic"})
        _table(dossier/"chronology.parquet",chronology,columns=["candidate_id","diagnostic_type","period","active_n","frequency","raw_mean_bps","direction_aligned_mean_bps","independent_opportunities","evidence_role"])

        crossfit,cross_cells=crossfit_surface_diagnostics(state_a=a,state_b=b,target=y,session_date=obs.session_date,resolution=resolution,folds=int(legacy_run.config.stability["chronological_folds"])); crossfit.insert(0,"candidate_id",candidate["candidate_id"]); cross_cells.insert(0,"candidate_id",candidate["candidate_id"]); _table(dossier/"crossfit_diagnostics.parquet",crossfit); _table(dossier/"crossfit_surface.parquet",cross_cells)
        chronology.extend({"candidate_id":candidate["candidate_id"],"diagnostic_type":"crossfit","period":str(x.fold),"active_n":int(x.heldout_n),"frequency":np.nan,"raw_mean_bps":float(x.heldout_state_bps),"direction_aligned_mean_bps":float(direction*x.heldout_state_bps) if direction else np.nan,"independent_opportunities":np.nan,"evidence_role":"discovery_diagnostic"} for x in crossfit.itertuples()); _table(dossier/"chronology.parquet",chronology)
        reconstructed=reconstruct_surface(counts=row["surface_counts"],sums=row["surface_sums"],sumsq=row["surface_sumsq"],resolution=resolution); counts=reconstructed["count"]; means=reconstructed["mean"]; lifts=reconstructed["interaction"]; selected_cell=a_cell*resolution+b_cell; surface=[]
        for i in range(len(counts)):
            distance=abs(i//resolution-a_cell)+abs(i%resolution-b_cell); surface.append({"candidate_id":candidate["candidate_id"],"state_a":i//resolution,"state_b":i%resolution,"n":int(counts[i]),"mean_bps":float(means[i]*1e4) if np.isfinite(means[i]) else None,"interaction_lift_bps":float(lifts[i]*1e4) if np.isfinite(lifts[i]) else None,"is_selected":i==selected_cell,"is_direct_neighbor":distance==1,"manhattan_distance_from_selected":distance,"direction_aligned_mean_bps":float(direction*means[i]*1e4) if direction and np.isfinite(means[i]) else None,"direction_aligned_interaction_lift_bps":float(direction*lifts[i]*1e4) if direction and np.isfinite(lifts[i]) else None,"evidence_role":"discovery_diagnostic"})
        _table(dossier/"surface_cells.parquet",surface)
        _table(dossier/"resolution_comparison.parquet",_resolution_comparison_rows(candidate_id=candidate["candidate_id"],row=row,duals=duals))

        rank_a=data.percentile_rank(grid,row["feature_a"]); rank_b=data.percentile_rank(grid,row["feature_b"]); tails=[]
        for percent in (20,10,5,2,1):
            tail,applicable,reason=build_tail_mask(rank_a=rank_a,rank_b=rank_b,state_a=a,state_b=b,selected_a=a_cell,selected_b=b_cell,resolution=resolution,tail_fraction=percent/100); tail_eligible=np.isfinite(rank_a)&np.isfinite(rank_b)&np.isfinite(y); teps,topps,_,_=_opportunities(obs,tail,ledger); tpos=_positions(obs,topps); traw=y[tpos]*1e4 if len(tpos) else np.asarray([],float); month_values=[]
            if len(tpos): month_values=pd.DataFrame({"month":pd.to_datetime(obs.iloc[tpos].session_date).dt.to_period("M").astype(str),"raw":traw}).groupby("month").raw.mean().to_numpy(float)
            tails.append({"candidate_id":candidate["candidate_id"],"tail_percent":percent,"applicable":applicable,"reason":reason,"active_n":int(tail.sum()),"eligible_n":int(tail_eligible.sum()),"frequency":float(tail.sum()/max(1,tail_eligible.sum())),"raw_edge_bps":float(np.nanmean(y[tail])*1e4) if tail.any() else np.nan,"direction_aligned_edge_bps":float(direction*np.nanmean(y[tail])*1e4) if direction and tail.any() else np.nan,"weighted_contribution_bps":float(direction*np.nanmean(y[tail])*1e4*tail.mean()) if direction and tail.any() else np.nan,"episode_count":len(teps),"independent_opportunity_count":len(topps),"opportunities_per_day":len(topps)/max(1,int(obs.loc[tail_eligible,"session_date"].nunique())),"month_count":len(month_values),"favorable_month_fraction":float(np.mean(direction*np.asarray(month_values)>0)) if direction and len(month_values) else np.nan,"raw_median_month_bps":float(np.median(month_values)) if len(month_values) else np.nan,"direction_aligned_median_month_bps":float(np.median(direction*np.asarray(month_values))) if direction and len(month_values) else np.nan,"evidence_role":"discovery_diagnostic"})
        _table(dossier/"tail_ladder.parquet",tails)

        horizons=[]; events=[]
        for spec in _compatible(data,target):
            values=data.target(grid,spec.target_id)*1e4; active_values=values[mask]; event_values=values[pos] if len(pos) else np.asarray([],float); base={"candidate_id":candidate["candidate_id"],"target_id":spec.target_id,"horizon":spec.horizon.label,"horizon_kind":spec.horizon.kind,"horizon_value":spec.horizon.value,"evidence_role":"discovery_diagnostic"}
            horizons.append({**base,"n":int(np.isfinite(active_values).sum()),"raw_mean_bps":float(np.nanmean(active_values)) if np.isfinite(active_values).any() else np.nan,"direction_aligned_mean_bps":float(direction*np.nanmean(active_values)) if direction and np.isfinite(active_values).any() else np.nan}); events.append({**base,"n":int(np.isfinite(event_values).sum()),"raw_mean_bps":float(np.nanmean(event_values)) if np.isfinite(event_values).any() else np.nan,"direction_aligned_mean_bps":float(direction*np.nanmean(event_values)) if direction and np.isfinite(event_values).any() else np.nan})
        metrics=event_path_metrics(events); _table(dossier/"horizon_ladder.parquet",horizons); _table(dossier/"event_path.parquet",[{**x,**metrics} for x in events])
        if len(pos):
            windows=ledger.iloc[pos][["security_id","entry_ts","exit_ts","entry_price","exit_price"]]; paths=actual_trade_path_diagnostics(windows,duckdb_path=legacy_run.config.source.duckdb_path,bars_table=legacy_run.config.source.bars_1m_raw_table,discovery_end=legacy_run.config.research_periods.discovery_end,temp_directory=Path(legacy_run.config.compute.duckdb_temp_directory)); paths=direction_aware_excursions(paths,direction) if direction else paths.assign(directional_mfe=np.nan,directional_mae=np.nan,time_to_directional_mfe=np.nan,time_to_directional_mae=np.nan,directional_terminal_return=np.nan); paths.insert(0,"candidate_id",candidate["candidate_id"])
        else: paths=pd.DataFrame(columns=["candidate_id","mfe","mae","directional_mfe","directional_mae"])
        _table(dossier/"path_diagnostics.parquet",paths)

        symbols=[]
        if len(pos):
            selected["raw_bps"]=raw; selected["aligned_bps"]=aligned
            for sec,part in selected.groupby("security_id"): symbols.append({"candidate_id":candidate["candidate_id"],"security_id":sec,"n":len(part),"raw_mean_bps":float(part.raw_bps.mean()),"direction_aligned_mean_bps":float(part.aligned_bps.mean()),"evidence_role":"discovery_diagnostic"})
        _table(dossier/"symbol_breakdown.parquet",symbols,columns=["candidate_id","security_id","n","raw_mean_bps","direction_aligned_mean_bps","evidence_role"]); sp=specialist[specialist.state_key==row["state_key"]].copy() if "state_key" in specialist else specialist.head(0).copy(); sp["candidate_id"]=candidate["candidate_id"]; sp["evidence_role"]="discovery_diagnostic"; _table(dossier/"specialist.parquet",sp); _table(dossier/"concentration.parquet",_concentration(raw,aligned,selected,direction)); interaction=interaction_decomposition(target_bps=y*1e4,active_a=a==a_cell,active_b=b==b_cell); _table(dossier/"interaction.parquet",[{"candidate_id":candidate["candidate_id"],**interaction,"evidence_role":"discovery_diagnostic"}])
        min_local=int(sp.specialist_min_local_n.iloc[0]) if len(sp) and "specialist_min_local_n" in sp else 20; active_rows=_active_symbol_breakdown(candidate_id=candidate["candidate_id"],obs=obs,y=y,mask=mask,security=security,min_local_n=min_local)
        _table(dossier/"symbol_active_breakdown.parquet",active_rows,columns=["candidate_id","security_id","symbol","active_n","raw_mean_bps","raw_sum_bps","absolute_contribution_bps","absolute_contribution_share","sign","specialist_min_n_eligible","evidence_role"])
        coverage=[{"candidate_id":candidate["candidate_id"],"eligible_n":int(eligible.sum()),"eligible_fraction_of_grid":float(eligible.mean()),"active_fraction_of_eligible":float(mask.sum()/max(1,eligible.sum())),"eligible_symbols":int(obs.loc[eligible,"security_id"].nunique()),"active_symbols":int(obs.loc[mask,"security_id"].nunique()),"monthly_eligible_n":None,"monthly_active_frequency":None,"evidence_role":"discovery_diagnostic"}]
        for month,idx in obs.groupby(pd.to_datetime(obs.session_date).dt.to_period("M")).groups.items():
            ii=np.asarray(list(idx),int); coverage.append({"candidate_id":candidate["candidate_id"],"month":str(month),"eligible_n":None,"eligible_fraction_of_grid":None,"active_fraction_of_eligible":None,"eligible_symbols":None,"active_symbols":None,"monthly_eligible_n":int(eligible[ii].sum()),"monthly_active_frequency":float(mask[ii].sum()/max(1,eligible[ii].sum())),"evidence_role":"discovery_diagnostic"})
        _table(dossier/"coverage.parquet",coverage)
        tod=[]
        if grid.startswith("intraday"):
            local=pd.to_datetime(obs.decision_ts,utc=True).dt.tz_convert("America/New_York"); minutes=local.dt.hour*60+local.dt.minute
            for name,start,end in (("open",570,630),("morning",630,720),("midday",720,840),("afternoon",840,930),("close",930,960)):
                window=((minutes>=start)&(minutes<end)).to_numpy(); active=mask&window; elig=eligible&window; _,bucket_opps,_,_=_opportunities(obs,active,ledger); tod.append({"candidate_id":candidate["candidate_id"],"bucket":name,"eligible_n":int(elig.sum()),"active_n":int(active.sum()),"frequency":float(active.sum()/max(1,elig.sum())),"raw_edge_bps":float(np.nanmean(y[active])*1e4) if active.any() else np.nan,"direction_aligned_edge_bps":float(direction*np.nanmean(y[active])*1e4) if direction and active.any() else np.nan,"independent_opportunities":len(bucket_opps),"evidence_role":"discovery_diagnostic"})
        _table(dossier/"time_of_day.parquet",tod,columns=["candidate_id","bucket","eligible_n","active_n","frequency","raw_edge_bps","direction_aligned_edge_bps","independent_opportunities","evidence_role"]); _table(dossier/"regime_breakdown.parquet",[{"candidate_id":candidate["candidate_id"],"regime":name,"status":"unavailable","reason":"standard_regime_feature_not_available","evidence_role":"discovery_diagnostic"} for name in ("volatility","trend","breadth","liquidity")])
        sid=pd.factorize(selected.session_date,sort=True)[0] if len(selected) else np.asarray([],int); raw_inf=session_clustered_mean_se(raw,sid); aligned_inf=session_clustered_mean_se(aligned,sid) if direction else {"session_mean_bps":np.nan,"session_clustered_se_bps":np.nan}; se=aligned_inf["session_clustered_se_bps"]
        _table(dossier/"inference.parquet",[{"candidate_id":candidate["candidate_id"],"session_n":raw_inf["session_n"],"raw_session_mean_bps":raw_inf["session_mean_bps"],"raw_session_clustered_se_bps":raw_inf["session_clustered_se_bps"],"direction_aligned_session_mean_bps":aligned_inf["session_mean_bps"],"session_clustered_se_bps":se,"direction_aligned_t_stat":aligned_inf["session_mean_bps"]/se if direction and np.isfinite(se) and se else np.nan,"episode_count":len(eps),"independent_opportunity_count":len(opps),"evidence_role":"discovery_diagnostic"}])
        lifecycle=[]; previous={}
        for ep in eps:
            lifecycle.append({"candidate_id":candidate["candidate_id"],**asdict(ep),"fresh_entry":True,"first_continuation":ep.observation_count>=2,"later_persistence":max(0,ep.observation_count-2),"exit":True,"reentry_after_gap":ep.security_id in previous,"episode_duration":ep.end_ts_ns-ep.start_ts_ns,"gap_from_previous_episode":ep.start_ts_ns-previous[ep.security_id] if ep.security_id in previous else None,"evidence_role":"discovery_diagnostic"}); previous[ep.security_id]=ep.end_ts_ns
        _table(dossier/"state_lifecycle.parquet",lifecycle)
        signals=obs.loc[mask,["observation_id","security_id","decision_ts"]].merge(ledger[["observation_id","exit_ts"]],on="observation_id",how="left").merge(security,on="security_id",how="left"); signals["candidate_id"]=candidate["candidate_id"]; signals["signal_timestamp"]=signals.decision_ts; signals["reference_exit_timestamp"]=signals.exit_ts; signals["direction"]=direction; signals["resolution"]=resolution; signals["state_definition"]=candidate["state_definition"]; signals["state_payload"]=json.dumps(candidate["state_payload"],sort_keys=True); signals.to_parquet(dossier/"signals.parquet",index=False)
        _table(dossier/"redundancy.parquet",[{"candidate_id":candidate["candidate_id"],"status":"deferred_on_demand","reason":"exact_redundancy_requires_explicit_candidate_set"}]); built.append(candidate["candidate_id"]); (dossier/"dossier.json").write_text(json.dumps({"candidate_id":candidate["candidate_id"],"definition_hash":candidate["definition_hash"],"evidence_role":"discovery_diagnostic","files":sorted(x.name for x in dossier.iterdir())},indent=2,default=str),encoding="utf-8")
    if len(candidates): candidates=candidates.copy(); candidates["status"]="dossier_complete"; candidates["dossier_status"]="complete"; candidates.to_parquet(legacy_run.root/"edge_registry.parquet",index=False)
    return built
