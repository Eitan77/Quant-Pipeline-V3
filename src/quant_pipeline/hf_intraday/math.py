"""Minute-exact arithmetic; missing bars are never compressed or filled."""
import numpy as np
from scipy.stats import rankdata

def lag(x, n=1):
    out=np.full_like(x,np.nan,dtype=float)
    if n>0: out[n:]=x[:-n]
    elif n<0: out[:n]=x[-n:]
    else: out[:]=x
    return out

def rolling(x, n, kind='sum', prior=False):
    x=lag(x) if prior else x
    out=np.full_like(x,np.nan,dtype=float)
    if len(x)<n: return out
    windows=np.lib.stride_tricks.sliding_window_view(x,n,axis=0)
    fn={'sum':np.sum,'std':lambda a,axis:np.std(a,axis=axis,ddof=1),
        'max':np.max,'min':np.min,'mean':np.mean}[kind]
    out[n-1:]=fn(windows,axis=-1)
    return out

def cs_rank(x):
    out=np.full_like(x,np.nan,dtype=float)
    for k,row in enumerate(x):
        good=np.isfinite(row); n=good.sum()
        if n: out[k,good]=(rankdata(row[good],method='average')-.5)/n
    return out

def empirical(x, history, minimum=60):
    if not history: return np.full_like(x,np.nan)
    h=np.stack(history); valid=np.isfinite(h); n=valid.sum(axis=0)
    out=((valid&(h<x)).sum(axis=0)+.5*(valid&(h==x)).sum(axis=0))/np.maximum(n,1)
    return np.where((n>=minimum)&np.isfinite(x),out,np.nan)

def baseline(x, history, kind='tail', minimum=60, eps=1e-12):
    if kind=='tail': return 2*empirical(x,history,minimum)-1
    if not history: return np.full_like(x,np.nan)
    h=np.stack(history); n=np.isfinite(h).sum(axis=0)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        med=np.nanmedian(h,axis=0)
        value=(np.nanquantile(h,.99,axis=0) if kind=='q99' else
               (x-med)/(1.4826*np.nanmedian(abs(h-med),axis=0)+eps))
    return np.where((n>=minimum)&np.isfinite(x),value,np.nan)

def project(x, loadings):
    """Contemporaneous factor scores using only frozen loadings; masked LS."""
    out=np.full_like(x,np.nan)
    usable=np.isfinite(loadings).all(axis=1)
    for t,row in enumerate(x):
        good=usable&np.isfinite(row)
        if good.sum()<loadings.shape[1]+1: continue
        l=loadings[good]
        if np.linalg.matrix_rank(l)<l.shape[1]: continue
        factor=np.linalg.lstsq(l,row[good],rcond=None)[0]
        out[t,good]=row[good]-l@factor
    return out

def pairwise_statistics(x,device='cpu'):
    """Exact centered moments on each pair's observed prior rows; no imputation."""
    import torch
    valid=torch.as_tensor(np.isfinite(x),dtype=torch.float64,device=device)
    values=torch.as_tensor(np.where(np.isfinite(x),x,0),dtype=torch.float64,device=device)
    count=valid.T@valid
    sums=values.T@valid
    denominator=torch.clamp(count-1,min=1)
    covariance=(values.T@values-sums*sums.T/torch.clamp(count,min=1))/denominator
    variance=(values.square().T@valid-sums.square()/torch.clamp(count,min=1))/denominator
    scale=torch.sqrt(torch.clamp(variance*variance.T,min=0))
    correlation=torch.where((count>=2)&(scale>0),covariance/scale,torch.nan).clamp(-1,1)
    covariance=torch.where(count>=2,covariance,torch.nan)
    return covariance,count.cpu().numpy(),correlation.cpu().numpy()

def fit_models(history, market_history, eligible, settings, device='cpu'):
    """All training rows are prior sessions; lead responses stay within session."""
    s=len(eligible); k=settings['pca_components']; nan=np.full(s,np.nan)
    empty=dict(beta=nan.copy(),loadings=np.full((s,k),np.nan),
               peers=[None]*s,lead1=[None]*s,lead2=[None]*s,
               incoming=nan.copy(),outgoing=nan.copy())
    if len(history)<settings['model_sessions']: return empty
    h=np.stack(history[-settings['model_sessions']:]); m=np.stack(market_history[-settings['model_sessions']:])
    x=h.reshape(-1,s); market=m.reshape(-1); beta=nan.copy()
    for i in np.flatnonzero(eligible):
        good=np.isfinite(x[:,i])&np.isfinite(market)
        if good.sum()>=settings['model_min_rows'] and np.var(market[good])>settings['eps']:
            beta[i]=np.cov(x[good,i],market[good],ddof=1)[0,1]/np.var(market[good],ddof=1)
    # Missing stock-minutes must not discard every other stock's observed rows.
    cols=np.flatnonzero(eligible&(np.isfinite(x).sum(axis=0)>=settings['model_min_rows']))
    if len(cols)<k+2: return empty|{'beta':beta}
    import torch
    cov,counts,_=pairwise_statistics(x[:,cols],device)
    # Retain a deterministic prior-only universe with >=1,000 joint rows per
    # covariance entry. Names with inadequate pair history remain unavailable.
    keep=np.arange(len(cols))
    usable=np.isfinite(cov.diag().cpu().numpy())&(cov.diag().cpu().numpy()>settings['eps'])
    keep=keep[usable]
    while len(keep)>=k+2:
        bad=(counts[np.ix_(keep,keep)]<settings['model_min_rows']).sum(axis=1)
        if not bad.any(): break
        keep=np.delete(keep,int(np.argmax(bad)))
    if len(keep)<k+2: return empty|{'beta':beta}
    index=torch.as_tensor(keep,device=device);cov=cov.index_select(0,index).index_select(1,index)
    cols=cols[keep]
    _,vectors=torch.linalg.eigh(cov); loads=np.full((s,k),np.nan)
    loads[cols]=vectors[:,-k:].cpu().numpy()
    u=np.stack([project(day,loads) for day in h])
    flat=u.reshape(-1,s); _,pair_counts,corr=pairwise_statistics(flat[:,cols],device)
    corr[pair_counts<settings['model_min_rows']]=np.nan
    peers=[None]*s; lead1=[None]*s; lead2=[None]*s
    incoming=nan.copy(); outgoing=nan.copy(); outgoing[cols]=0.0
    def regression(design,response):
        a=design.reshape(-1,design.shape[-1]); y=response.reshape(-1)
        good=np.isfinite(a).all(axis=1)&np.isfinite(y)
        if good.sum()<settings['model_min_rows']: return None
        a=a[good]; y=y[good]; scale=np.std(a,axis=0); scale=np.maximum(scale,settings['eps'])
        z=a/scale
        coefficients=np.linalg.solve(z.T@z+settings['ridge']*len(z)*np.eye(z.shape[1]),z.T@y)/scale
        return coefficients
    for q,i in enumerate(cols):
        choices=np.delete(np.arange(len(cols)),q)
        choices=choices[np.isfinite(corr[q,choices])&(abs(corr[q,choices])>0)]
        choices=choices[np.argsort(-abs(corr[q,choices]),kind='stable')[:settings['peer_count']]]
        if not len(choices): continue
        js=cols[choices]; strength=abs(corr[q,choices]); weights=strength/strength.sum()
        peers[i]=(js,weights)
        a=u[:, :-1, js]; y=u[:,1:,i]; lead1[i]=regression(a,y)
        a2=np.concatenate((u[:,1:-2,js],u[:,:-3,js]),axis=-1)
        lead2[i]=regression(a2,u[:,3:,i])
        if lead1[i] is not None:
            incoming[i]=np.sum(abs(lead1[i])); outgoing[js]+=abs(lead1[i])
    return dict(beta=beta,loadings=loads,peers=peers,lead1=lead1,lead2=lead2,
                incoming=incoming,outgoing=outgoing)
