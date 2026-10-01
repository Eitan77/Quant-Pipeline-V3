from pathlib import Path
import json
from math import isfinite

SPEC = json.loads(Path(__file__).with_name('spec.json').read_text(encoding='utf-8'))
FEATURES = tuple(x['id'] for x in SPEC['features'])
TARGETS = tuple(x['id'] for x in SPEC['targets'])
DEFAULTS = dict(model_sessions=20, tod_sessions=60, tod_min_sessions=60,
                model_min_rows=1000, pca_components=5, peer_count=10,
                ridge=0.001, factor_common_cap=10.0, eps=1e-12,
                resolutions=[3, 5, 10], empirical_bins='same_clock_prior60',
                tail_first_leg='listed_orientation', episode_gap_minutes=1)

def validate_pack(pack):
    if set(pack) - set(DEFAULTS):
        raise ValueError(f'Unknown HF settings: {set(pack)-set(DEFAULTS)}')
    settings = DEFAULTS | pack
    if settings['pca_components'] != 5 or settings['tod_sessions'] != 60:
        raise ValueError('HF spec requires K=5 PCA and prior60 TOD')
    if settings['resolutions'] != [3, 5, 10]:
        raise ValueError('HF singles/duals require independent 3/5/10 bins')
    for key in ('model_sessions','tod_min_sessions','model_min_rows','peer_count'):
        if not isinstance(settings[key],int) or isinstance(settings[key],bool) or settings[key]<1:
            raise ValueError(f'Invalid HF {key}')
    if settings['tod_min_sessions'] > 60 or settings['model_sessions'] < 20:
        raise ValueError('Insufficient HF baseline history')
    for key in ('ridge','eps','factor_common_cap'):
        if not isinstance(settings[key],(int,float)) or isinstance(settings[key],bool) or not isfinite(settings[key]) or settings[key]<=0:
            raise ValueError(f'Invalid HF {key}')
    for key in ('empirical_bins','tail_first_leg','episode_gap_minutes'):
        if settings[key] != DEFAULTS[key]:
            raise ValueError(f'Unsupported HF {key}')
    assert len(FEATURES)==117 and len(set(FEATURES))==117
    assert len(TARGETS)==31 and len(set(TARGETS))==31
    assert [p['id'] for p in SPEC['pairs']]==list(range(1,306))
    assert all(p['a'] in FEATURES and p['b'] in FEATURES for p in SPEC['pairs'])
    return settings
