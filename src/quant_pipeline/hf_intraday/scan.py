"""HF surface contracts for the shared production executor."""
import os
from pathlib import Path
import numpy as np
from .spec import SPEC,FEATURES

def tasks(settings):
    out=[]
    for resolution in settings['resolutions']:
        for a in FEATURES:
            out.append(dict(key=f'single_{a}_r{resolution}',kind='single',a=a,b=None,resolution=resolution,tail=None,side=None))
        for pair in SPEC['pairs']:
            out.append(dict(key=f"dual_{pair['id']:03}_r{resolution}",kind='dual',a=pair['a'],b=pair['b'],resolution=resolution,tail=None,side=None))
    for a in SPEC['tail_features']:
        matches=[p for p in SPEC['pairs'] if p['a']==a]
        for tail in SPEC['tail_fractions']:
            for side in ('lower','upper'):
                stem=f'{a}_{tail}_{side}'
                out.append(dict(key=f'tail_single_{stem}',kind='tail',a=a,b=None,resolution=1,tail=tail,side=side))
                for p in matches:
                    for resolution in SPEC['tail_bins']:
                        out.append(dict(key=f"tail_dual_{p['id']:03}_{stem}_r{resolution}",kind='tail',a=a,b=p['b'],resolution=resolution,tail=tail,side=side))
    return out

def codes(task,ra,rb=None):
    r=task['resolution']; good=np.isfinite(ra); a=np.minimum((np.nan_to_num(ra)*r).astype(int),r-1)
    if task['tail'] is not None:
        good &= (ra<=task['tail']) if task['side']=='lower' else (ra>=1-task['tail'])
        a=np.zeros_like(a)
    if task['b']:
        good &= np.isfinite(rb); b=np.minimum((np.nan_to_num(rb)*r).astype(int),r-1)
        a=a*r+b
    return np.where(good,a,-1)

def cell_count(task):
    return task['resolution']**2 if task['b'] and task['tail'] is None else task['resolution']

def sql_state(task):
    a=f'"q_{task["a"]}"'; r=task['resolution']
    good=f'isfinite({a})'
    first=f'least({r}-1,floor({a}*{r}))::INTEGER'
    if task['tail'] is not None:
        sign='<=' if task['side']=='lower' else '>='
        cut=task['tail'] if task['side']=='lower' else 1-task['tail']
        good+=f' AND {a}{sign}{cut}'; first='0'
    if task['b']:
        b=f'"q_{task["b"]}"'; good+=f' AND isfinite({b})'
        first=f'({first})*{r}+least({r}-1,floor({b}*{r}))::INTEGER'
    return f'CASE WHEN {good} THEN {first} ELSE -1 END'

def atomic_frame(frame,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.partial'); frame.to_parquet(tmp,index=False); os.replace(tmp,path)

