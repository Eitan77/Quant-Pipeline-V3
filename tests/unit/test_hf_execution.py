from types import SimpleNamespace
import duckdb,numpy as np,pandas as pd,pytest,torch
from quant_pipeline.hf_intraday.spec import TARGETS
from hf_scan_reference import scan_task
from quant_pipeline.production.hf_execution import connect_inputs,ResidentTargets,scan_surface


@pytest.mark.parametrize('device',['cpu','cuda:0'])
def test_shared_execution_matches_exact_reference(tmp_path,device):
    if device!='cpu' and not torch.cuda.is_available(): pytest.skip('CUDA required')
    rng=np.random.default_rng(812); n=240
    data=dict(symbol=np.repeat(['A','B'],120),session_date=np.tile(np.repeat(['2025-05-01','2025-06-02','2025-06-03'],40),2),
        month=np.tile(np.repeat(['2025-05','2025-06','2025-06'],40),2),minute=np.tile(np.arange(40),6),
        q_ret_tod_tail_1m=np.tile(np.r_[0,.001,.01,.5,.99,.999,1,np.nan],30),q_body_share_1m=rng.random(n))
    for j,key in enumerate(TARGETS):
        values=rng.normal(0,.001,n); values[(np.arange(n)+j)%7==0]=np.nan
        values[j%17]=np.inf; data[key]=values
    data[TARGETS[3]]=np.full(n,np.nan)
    frame=pd.DataFrame(data); path=tmp_path/'source.parquet';frame.to_parquet(path,index=False)
    frame['_hf_rowid']=np.arange(n,dtype=np.int64); database=tmp_path/'inputs.duckdb'
    with duckdb.connect(str(database)) as con:
        con.register('data',frame);con.execute('CREATE TABLE hf_inputs AS SELECT * FROM data')
    machine=dict(duckdb_temp=str(tmp_path/'temp'),duckdb_memory_limit_gb=2)
    finite={key:int(np.isfinite(frame[key]).sum()) for key in frame if key.startswith('q_') or key in TARGETS}
    metadata=dict(rows=n,finite=finite); targets=[key for key in TARGETS if finite[key]>0]
    with connect_inputs(database,machine,1,2) as con:
        resident=ResidentTargets(con,n,targets,device,True)
    scenarios=[dict(a='ret_tod_tail_1m',b=None,resolution=3,tail=None,side=None),
        dict(a='ret_tod_tail_1m',b='body_share_1m',resolution=10,tail=None,side=None),
        dict(a='ret_tod_tail_1m',b=None,resolution=1,tail=.001,side='lower'),
        dict(a='ret_tod_tail_1m',b='body_share_1m',resolution=5,tail=.01,side='upper')]
    for i,scenario in enumerate(scenarios):
        task=dict(key=f'test_{i}',kind='tail' if scenario['tail'] is not None else 'single' if scenario['b'] is None else 'dual',**scenario)
        with duckdb.connect() as con: expected=scan_task(con,str(path),task,'cpu')
        actual=scan_surface(database,metadata,task,machine,1,2,device,resident,4)
        keys=['target','cell','grouping','group_value']
        expected=expected.sort_values(keys).reset_index(drop=True);actual=actual.sort_values(keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual[expected.columns],expected,check_dtype=False,check_exact=False,atol=1e-8,rtol=1e-9)


def test_empty_surface_preserves_complete_cells_without_reading_inputs(tmp_path):
    from quant_pipeline.production.hf_execution import scan_surface
    task=dict(key='empty',kind='dual',a='ret_tod_tail_1m',b='body_share_1m',resolution=10,tail=None,side=None)
    metadata=dict(finite={'q_ret_tod_tail_1m':0,'q_body_share_1m':100})
    result=scan_surface(tmp_path/'missing.duckdb',metadata,task,{},1,1,'cpu',SimpleNamespace(targets=list(TARGETS)),4)
    assert len(result)==100*len(TARGETS)
    assert (result.observations==0).all() and result.mean_bps.isna().all()
