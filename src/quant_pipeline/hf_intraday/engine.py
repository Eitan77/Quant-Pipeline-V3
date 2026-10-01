from collections import deque
from pathlib import Path
import warnings
import numpy as np
from scipy.stats import skew,kurtosis
from .math import lag,rolling,cs_rank,baseline,empirical,project,fit_models
from .spec import FEATURES,TARGETS

FACTOR_FEATURES=FEATURES[70:90]
EVENT_FEATURES=("post_shock_recovery_1m","post_shock_recovery_3m")
FACTOR_TARGETS=tuple(key for key in TARGETS if "factor_resid" in key)

def factor_features(r,u,evalid,models,liqrank,cfg,tod):
    shape=r[1].shape;eps=cfg["eps"];f={}
    def div(a,b): return np.asarray(a)/(np.asarray(b)+eps)
    for z in (1,2):
        f[f'factor_resid_{z}m']=u[z]; f[f'factor_resid_tod_tail_{z}m']=tod(f'u{z}',u[z])
    f['factor_common_share_1m']=np.minimum(div(abs(r[1]-u[1]),abs(r[1])),cfg['factor_common_cap'])
    f['factor_resid_cs_rank_1m']=cs_rank(np.where(evalid,u[1],np.nan))
    peerkeys=['peer_basket_resid_1m','peer_gap_1m','peer_gap_2m','peer_lead_pred_1m','peer_lead_pred_2m',
              'peer_breadth_sign_1m','peer_shock_breadth_1m','peer_dispersion_1m','peer_move_concentration_1m',
              'peer_leader_count_1m','leader_liquidity_advantage']
    f.update({key:np.full(shape,np.nan) for key in peerkeys})
    for i,peer in enumerate(models['peers']):
        if peer is None: continue
        js,weights=peer; pu=u[1][:,js]; basket=pu@weights
        f['peer_basket_resid_1m'][:,i]=basket
        f['peer_gap_1m'][:,i]=basket-u[1][:,i]; f['peer_gap_2m'][:,i]=u[2][:,js]@weights-u[2][:,i]
        f['peer_dispersion_1m'][:,i]=np.sqrt(((pu-basket[:,None])**2)@weights)
        contributions=abs(pu*weights); den=contributions.sum(axis=1)
        shares=contributions/np.where(den>0,den,np.nan)[:,None]
        f['peer_move_concentration_1m'][:,i]=np.sum(shares**2,axis=1)
        f['leader_liquidity_advantage'][:,i]=liqrank[js]@weights-liqrank[i]
        coef=models['lead1'][i]
        if coef is not None:
            pred=pu@coef; direction=np.sign(pred)
            f['peer_lead_pred_1m'][:,i]=pred
            good=np.isfinite(pu).all(axis=1)&np.isfinite(pred)
            f['peer_breadth_sign_1m'][:,i]=np.where(good,(np.sign(pu)==direction[:,None])@weights,np.nan)
            pt=f['factor_resid_tod_tail_1m'][:,js]
            f['peer_shock_breadth_1m'][:,i]=np.where(good&np.isfinite(pt).all(axis=1),((pt*direction[:,None])>=.98)@weights,np.nan)
            f['peer_leader_count_1m'][:,i]=np.where(good& (abs(pred)>eps),(abs(pu*coef)>=.1*abs(pred[:,None])).sum(axis=1),np.nan)
        if models['lead2'][i] is not None:
            f['peer_lead_pred_2m'][:,i]=np.concatenate((pu,lag(pu)),axis=1)@models['lead2'][i]
    f['peer_gap_velocity_1m']=f['peer_gap_1m']-lag(f['peer_gap_1m'])
    f['network_lead_strength']=np.broadcast_to(models['outgoing'],shape).copy()
    f['network_follow_strength']=np.broadcast_to(models['incoming'],shape).copy()
    return f

class HFEngine:
    """One bounded session at a time; state is updated only after all outputs."""
    def __init__(self,settings,device='cpu',history_root=None):
        self.cfg=settings; self.device=device
        self.history=deque(maxlen=60); self.returns=deque(maxlen=settings['model_sessions'])
        self.markets=deque(maxlen=settings['model_sessions']); self.liquidity=deque(maxlen=20)
        self.prior_close=None
        self.history_root=Path(history_root) if history_root is not None else None
        self.history_maps=deque(); self.history_sequence=0
        if self.history_root is not None: self.history_root.mkdir(parents=True,exist_ok=True)

    def _save_history(self,saved):
        if self.history_root is None:
            self.history.append({key:value.copy() for key,value in saved.items()})
            return
        if len(self.history)==self.history.maxlen:
            self.history.popleft()
            old,path=self.history_maps.popleft()
            old._mmap.close(); path.unlink()
        path=self.history_root/f'{self.history_sequence:06d}.npy'
        keys=list(saved); shape=next(iter(saved.values())).shape
        mapped=np.lib.format.open_memmap(path,mode='w+',dtype=np.float64,shape=(len(keys),*shape))
        for i,key in enumerate(keys): mapped[i]=saved[key]
        mapped.flush()
        self.history.append({key:mapped[i] for i,key in enumerate(keys)})
        self.history_maps.append((mapped,path)); self.history_sequence+=1

    def close(self):
        self.history.clear()
        while self.history_maps:
            mapped,path=self.history_maps.popleft()
            mapped._mmap.close(); path.unlink()

    def repair(self,bars,market_close,eligible,recovery=None,liquidity_rank=None):
        """Recompute the factor block and two event bins; retain other builds."""
        cfg=self.cfg;eps=cfg['eps'];minimum=cfg['tod_min_sessions']
        c=bars['close'];shape=c.shape;evalid=eligible[None,:]&np.isfinite(c)
        def hist(key): return [day[key] for day in self.history]
        saved={}
        def tod(key,value):
            saved[key]=value
            return baseline(value,hist(key),'tail',minimum,eps)
        r={z:c/lag(c,z)-1 for z in (1,2)}
        m=market_close/lag(market_close)-1
        models=fit_models(list(self.returns),list(self.markets),eligible,cfg,self.device)
        e1=r[1]-models['beta']*m[:,None];saved['e1']=e1
        u={z:project(r[z],models['loadings']) for z in (1,2)}
        if liquidity_rank is None:
            liq=np.full(shape[1],np.nan)
            if len(self.liquidity)==20:
                h=np.stack(self.liquidity);good=np.isfinite(h).any(axis=1).all(axis=0)&eligible
                liq[good]=np.nanmedian(h[:,:,good],axis=(0,1))
            liquidity_rank=cs_rank(liq[None,:])[0]
        f=factor_features(r,u,evalid,models,liquidity_rank,cfg,tod)
        if recovery is None:
            tail=baseline(e1,hist('e1'),'tail',minimum,eps)
            event=np.where(np.isfinite(tail),(abs(tail)>=.98).astype(float),np.nan)
            value=np.full(shape,np.nan)
            for i in range(shape[1]):
                shock=None;unknown=None
                for t in range(shape[0]):
                    if not np.isfinite(c[t,i]):shock=None;unknown=t;continue
                    if shock is not None and (unknown is None or shock>unknown) and 1<=t-shock<=3:
                        value[t,i]=-np.sign(e1[shock,i])*(c[t,i]/c[shock,i]-1)
                    if event[t,i]==1:shock=t
                    elif not np.isfinite(event[t,i]):unknown=t
            recovery=dict(post_shock_recovery_1m=np.where(lag(event)==1,-np.sign(lag(e1))*r[1],np.nan),post_shock_recovery_3m=value)
        f.update(recovery)
        q={key:empirical(value,hist(key),1 if key in EVENT_FEATURES and len(self.history)==60 else minimum) for key,value in f.items()}
        y={}
        for z in (1,2,3,5,10,15,30):y[f'fwd_factor_resid_{z}m']=project(lag(c,-z)/c-1,models['loadings'])
        for z in range(1,6):y[f'step_factor_resid_p{z}']=project(lag(c,-z)/lag(c,-(z-1))-1,models['loadings'])
        for mapping in (f,q,y):
            for key,value in mapping.items():mapping[key]=np.where(evalid&np.isfinite(value),value,np.nan)
        saved.update(f);self._save_history(saved)
        self.returns.append(np.where(evalid,r[1],np.nan));self.markets.append(m.copy())
        dv=bars['vwap']*bars['volume']*bars.get('split_factor',1)
        self.liquidity.append(np.where(evalid,dv,np.nan))
        return f,y,q,models

    def build(self,bars,market_close,eligible):
        cfg=self.cfg; eps=cfg['eps']; minimum=cfg['tod_min_sessions']
        c,o,h,l,v,w,n=(bars[key].astype(float) for key in ('close','open','high','low','volume','vwap','trade_count'))
        shape=c.shape; evalid=eligible[None,:]&np.isfinite(c)
        def hist(key,count=60): return [day[key] for day in list(self.history)[-count:] if key in day]
        saved={}; f={}; targets={}
        def tod(key,x,kind='tail'):
            saved[key]=x
            return baseline(x,hist(key),kind,minimum,eps)
        def div(a,b): return np.asarray(a)/(np.asarray(b)+eps)
        r={z:c/lag(c,z)-1 for z in (1,2,3,5)}
        m={z:market_close/lag(market_close,z)-1 for z in (1,2,3,5)}
        # Training universe eligibility is known before today's open.
        models=fit_models(list(self.returns),list(self.markets),eligible,cfg,self.device)
        beta=models['beta']; e={z:r[z]-beta*m[z][:,None] for z in r}
        u={z:project(r[z],models['loadings']) for z in (1,2)}
        # Research prices are split-consistent; actual dollar activity uses raw VWAP.
        dv=w*v*bars.get('split_factor',1.0)
        rng=div(h-l,lag(c)); body=div(abs(c-o),h-l); clv=2*div(c-l,h-l)-1
        for z in r:
            f[f'resid_tod_tail_{z}m']=tod(f'e{z}',e[z])
        f['ret_tod_tail_1m']=tod('r1',r[1]); f['ret_tod_robz_1m']=tod('r1',r[1],'robz')
        f['resid_tod_robz_1m']=tod('e1',e[1],'robz')
        prestd=rolling(e[1],30,'std',True)
        f['resid_prevol_norm_1m']=div(e[1],prestd)
        f['resid_prevol_norm_2m']=div(e[2],prestd*np.sqrt(2))
        f['shock_accel_1m']=e[1]-lag(e[1])
        q=tod('abs_e1',abs(e[1]),'q99')
        f['shock_excess_1pct']=np.sign(e[1])*div(np.maximum(abs(e[1])-q,0),q)
        f['idio_share_1m']=div(abs(e[1]),abs(e[1])+abs(beta*m[1][:,None]))
        f['body_ret_1m']=c/o-1; f['gap_ret_1m']=o/lag(c)-1
        f['body_share_1m']=body; f['clv_signed_1m']=clv
        f['dir_close_extreme_1m']=np.sign(e[1])*clv
        for z in (3,5,10):
            total=rolling(abs(e[1]),z)
            f[f'path_eff_{z}m']=np.where(total>0,abs(rolling(e[1],z))/np.where(total>0,total,np.nan),np.nan)
            if z!=10: f[f'last1_abs_share_{z}m']=np.where(total>0,abs(e[1])/np.where(total>0,total,np.nan),np.nan)
        signs=np.sign(e[1]); streak=np.full(shape,np.nan)
        for t in range(len(c)):
            good=np.isfinite(signs[t]); same=good&(signs[t]!=0)&(t>0)
            if t: same &= signs[t]==signs[t-1]
            streak[t]=np.where(good,np.where(same,abs(streak[t-1])+1 if t else 1,np.where(signs[t]==0,0,1)),np.nan)
        f['same_sign_streak_1m']=streak*signs
        switch=np.where(np.isfinite(signs)&np.isfinite(lag(signs)),(signs!=lag(signs)).astype(float),np.nan)
        f['sign_switch_rate_5m']=rolling(switch,5,'mean')
        tail=f['resid_tod_tail_1m']; event=np.where(np.isfinite(tail),(abs(tail)>=.98).astype(float),np.nan)
        for z in (5,15): f[f'tail_event_count_{z}m']=rolling(event,z)
        f['range_tod_tail_1m']=tod('range',rng)
        inputs={'volume':np.log1p(v),'dollar_volume':np.log1p(dv),'trade_count':np.log1p(n),
                'avg_trade_size':np.log1p(v/np.maximum(n,1)),
                'dollar_per_trade':np.log1p(dv/np.maximum(n,1))}
        for key,x in inputs.items(): f[f'{key}_tod_tail_1m']=tod(key,x)
        impact=div(abs(e[1]),dv/1e6)
        f['impact_per_dollar_1m']=impact; f['impact_tod_tail_1m']=tod('impact',np.log1p(impact))
        f['range_per_dollar_1m']=div(rng,dv/1e6)
        dz=tod('dollar_volume',inputs['dollar_volume'],'robz')
        vz=tod('volume',inputs['volume'],'robz'); nz=tod('trade_count',inputs['trade_count'],'robz')
        ez=tod('abs_e1',abs(e[1]),'robz')
        f['effort_result_1m']=dz-ez; f['volume_return_mismatch_1m']=vz-ez
        f['trade_intensity_mismatch_1m']=nz-ez
        f['prevol_tod_tail_30m']=tod('prevol',np.sqrt(rolling(e[1]**2,30,prior=True)))
        liq=np.full(shape[1],np.nan)
        if len(self.liquidity)==20:
            lh=np.stack(self.liquidity)
            good=np.isfinite(lh).any(axis=1).all(axis=0)&eligible
            # Median over all actual minute observations in the prior 20 sessions.
            # A median of session medians is a different statistic.
            liq[good]=np.nanmedian(lh[:,:,good],axis=(0,1))
        liqrank=cs_rank(liq[None,:])[0]
        f['liquidity_rank_20d']=np.broadcast_to(liqrank,shape).copy()
        f['signed_dollar_pressure_1m']=clv*dz; f['signed_volume_pressure_1m']=clv*vz
        vc=div(c-w,h-l); f['vwap_close_location_1m']=vc; f['vwap_bar_location_1m']=div(w-l,h-l)
        f['vwap_pressure_1m']=vc*dz
        upper=div(h-np.maximum(o,c),h-l); lower=div(np.minimum(o,c)-l,h-l)
        f['upper_rejection_pressure_1m']=upper*np.maximum(dz,0)
        f['lower_rejection_pressure_1m']=lower*np.maximum(dz,0)
        f['wick_skew_pressure_1m']=(lower-upper)*np.maximum(dz,0)
        f['pressure_return_divergence_1m']=clv*dz-f['resid_tod_robz_1m']
        f['absorption_score_1m']=clv*np.maximum(dz-abs(f['resid_tod_robz_1m']),0)
        for z in (1,2,5): f[f'resid_cs_rank_{z}m']=cs_rank(np.where(evalid,e[z],np.nan))
        f['resid_rank_velocity_1m']=f['resid_cs_rank_1m']-lag(f['resid_cs_rank_1m'])
        f['resid_rank_accel_1m']=f['resid_rank_velocity_1m']-lag(f['resid_rank_velocity_1m'])
        masked=np.where(evalid,e[1],np.nan); count=np.isfinite(masked).sum(axis=1)
        def broadcast(x): return np.broadcast_to(np.asarray(x)[:,None],shape).copy()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            disp=np.nanstd(masked,axis=1,ddof=1)
            f['resid_dispersion_1m']=broadcast(disp)
            f['resid_dispersion_tod_tail_1m']=tod('dispersion',broadcast(disp))
            for side in ('down','up'):
                denom=(evalid&np.isfinite(tail)).sum(axis=1)
                hit=(tail<=-.98) if side=='down' else (tail>=.98)
                f[f'tail_breadth_{side}_1m']=broadcast(np.where(denom>0,(hit&evalid).sum(axis=1)/np.maximum(denom,1),np.nan))
            f['tail_breadth_imbalance_1m']=f['tail_breadth_up_1m']-f['tail_breadth_down_1m']
            f['cs_resid_skew_1m']=broadcast(np.where(count>=3,skew(masked,axis=1,nan_policy='omit',bias=False),np.nan))
            f['cs_resid_kurt_1m']=broadcast(np.where(count>=4,kurtosis(masked,axis=1,nan_policy='omit',bias=False),np.nan))
            f['median_stock_ret_1m']=broadcast(np.nanmedian(np.where(evalid,r[1],np.nan),axis=1))
        f['benchmark_minus_median_1m']=broadcast(m[1])-f['median_stock_ret_1m']
        for z in (1,2): f[f'market_tod_tail_{z}m']=tod(f'm{z}',broadcast(m[z]))
        f['market_vol_tod_tail_5m']=tod('market_vol',broadcast(np.sqrt(rolling(m[1]**2,5))))
        f['lagged_market_response_gap_1m']=beta*lag(m[1])[:,None]-r[1]
        denom=(evalid&np.isfinite(r[1])).sum(axis=1)
        f['breadth_positive_1m']=broadcast(np.where(denom>0,((r[1]>0)&evalid).sum(axis=1)/np.maximum(denom,1),np.nan))
        f['breadth_change_1m']=f['breadth_positive_1m']-lag(f['breadth_positive_1m'])
        f.update(factor_features(r,u,evalid,models,liqrank,cfg,tod))
        # Invalid/missing minute bars poison session accumulations from that point.
        cumv=np.cumsum(v,axis=0); svwap=div(np.cumsum(w*v,axis=0),cumv)
        sh=np.maximum.accumulate(h,axis=0); sl=np.minimum.accumulate(l,axis=0)
        f['dist_session_vwap']=c/svwap-1; f['dist_session_open']=c/o[0]-1
        f['dist_prior_close']=c/self.prior_close-1 if self.prior_close is not None else np.full(shape,np.nan)
        f['dist_session_high']=c/sh-1; f['dist_session_low']=c/sl-1
        sr=sh-sl; saved['session_range']=sr
        if hist('session_range'):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                hh=np.stack(hist('session_range')); med=np.nanmedian(hh,axis=0)
                f['session_range_expansion_tod']=np.where(np.isfinite(hh).sum(axis=0)>=minimum,div(sr,med)-1,np.nan)
        else: f['session_range_expansion_tod']=np.full(shape,np.nan)
        f['same_minute_resid_lag1d']=hist('e1',1)[0].copy() if hist('e1',1) else np.full(shape,np.nan)
        for z in (5,20):
            hh=hist('e1',z); f[f'same_minute_resid_mean{z}d']=np.mean(hh,axis=0) if len(hh)==z else np.full(shape,np.nan)
        hh=hist('resid_cs_rank_1m',20)
        f['same_minute_rank_mean20d']=np.mean(hh,axis=0) if len(hh)==20 else np.full(shape,np.nan)
        # Prior30 excludes the recent5 numerator, so compression is disjoint.
        f['prevol_ratio_5_30']=div(np.sqrt(rolling(e[1]**2,5)),np.sqrt(lag(rolling(e[1]**2,30),5))*np.sqrt(5/30))
        f['range_ratio_5_30']=div(rolling(h-l,5),lag(rolling(h-l,30),5)*5/30)
        f['dollar_volume_ratio_5_30']=div(rolling(dv,5),lag(rolling(dv,30),5)*5/30)
        f['squeeze_score_5_30']=-tod('volratio',f['prevol_ratio_5_30'],'robz')
        for z in (5,15):
            f[f'breakout_dist_high_{z}m']=c/rolling(c,z,'max',True)-1
            f[f'breakout_dist_low_{z}m']=c/rolling(c,z,'min',True)-1
        f['dist_orh_5m']=c/np.max(h[:5],axis=0)-1; f['dist_orl_5m']=c/np.min(l[:5],axis=0)-1
        f['dist_orh_5m'][:4]=np.nan; f['dist_orl_5m'][:4]=np.nan
        vside=np.sign(c-svwap); vage=np.full(shape,np.nan); bage=np.full(shape,np.nan)
        since=np.full(shape,np.nan); recovery=np.full(shape,np.nan); cluster=np.zeros(shape)
        for i in range(shape[1]):
            last_cross=None; breakout=None; bsign=0; shock=None; last_unknown_event=None
            for t in range(shape[0]):
                if not np.isfinite(c[t,i]):
                    last_cross=None; breakout=None; shock=None; last_unknown_event=t; continue
                if np.isfinite(vside[t,i]):
                    if t==0 or not np.isfinite(vside[t-1,i]) or vside[t,i]!=vside[t-1,i]: last_cross=t
                    if last_cross is not None: vage[t,i]=vside[t,i]*(t-last_cross)
                up=f['breakout_dist_high_15m'][t,i]>0; down=f['breakout_dist_low_15m'][t,i]<0
                if up or down: breakout=t; bsign=1 if up else -1
                if breakout is not None: bage[t,i]=bsign*(t-breakout)
                known_shock=shock is not None and (last_unknown_event is None or shock>last_unknown_event)
                if known_shock: since[t,i]=min(t-shock,30)
                elif last_unknown_event is None or t-last_unknown_event>30: since[t,i]=30
                if known_shock and 1<=t-shock<=3:
                    recovery[t,i]=-np.sign(e[1][shock,i])*(c[t,i]/c[shock,i]-1)
                if event[t,i]==1: shock=t
                elif not np.isfinite(event[t,i]): last_unknown_event=t
        f['vwap_cross_age_signed']=vage; f['breakout_age_signed_15m']=bage
        f['minutes_since_tail_event']=np.where(np.isfinite(tail),since,np.nan)
        f['post_shock_recovery_1m']=np.where(lag(event)==1,-np.sign(lag(e[1]))*r[1],np.nan)
        f['post_shock_recovery_3m']=recovery
        cluster=np.zeros(shape); valid=np.ones(shape,dtype=bool)
        for age in range(1,16):
            ev=lag(event,age); cluster+=np.nan_to_num(ev)*np.exp(-age/5); valid &= np.isfinite(ev)
        f['shock_cluster_score_15m']=np.where(valid,cluster,np.nan)
        f['vol_accel_1_5']=div(abs(e[1]),np.sqrt(rolling(e[1]**2,5))/np.sqrt(5))
        # Forward labels use exact close endpoints, the same frozen model, no overnight carry.
        for z in (1,2,3,5,10,15,30):
            raw=lag(c,-z)/c-1; fm=lag(market_close,-z)/market_close-1
            targets[f'fwd_raw_{z}m']=raw
            targets[f'fwd_beta_resid_{z}m']=raw-beta*fm[:,None]
            targets[f'fwd_factor_resid_{z}m']=project(raw,models['loadings'])
        for z in range(1,6):
            step=lag(c,-z)/lag(c,-(z-1))-1
            targets[f'step_raw_p{z}']=step
            targets[f'step_factor_resid_p{z}']=project(step,models['loadings'])
        assert set(f)==set(FEATURES),(set(FEATURES)-set(f),set(f)-set(FEATURES))
        assert set(targets)==set(TARGETS)
        # Conditional recovery values are NA outside events. Requiring an event
        # on all 60 sessions makes their bins structurally empty. After a full
        # prior60 calendar window, rank only observed prior events; never fill NA.
        event_features=set(EVENT_FEATURES)
        ranks={key:empirical(value,hist(key),1 if key in event_features and len(hist(key))==60 else minimum)
               for key,value in f.items()}
        for mapping in (f,targets,ranks):
            for key,value in mapping.items(): mapping[key]=np.where(evalid&np.isfinite(value),value,np.nan)
        saved.update(f)
        # Storage is float64 to preserve empirical ties and minute-exact parity.
        self._save_history(saved)
        self.returns.append(np.where(evalid,r[1],np.nan)); self.markets.append(m[1].copy())
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            self.liquidity.append(np.where(evalid,dv,np.nan).copy())
        session_end=np.flatnonzero(np.isfinite(market_close))
        close_minute=bars.get('session_end_minute',int(session_end[-1]) if len(session_end) else None)
        self.prior_close=c[close_minute].copy() if close_minute is not None else np.full(shape[1],np.nan)
        return f,targets,ranks,models
