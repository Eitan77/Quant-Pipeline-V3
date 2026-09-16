from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if not os.getenv("QP_V2_REFERENCE_ROOT"): raise RuntimeError("QP_V2_REFERENCE_ROOT is required")
V2=Path(os.environ["QP_V2_REFERENCE_ROOT"]).resolve()
MODULES=["models.py","registry.py","config.py","data/universe.py","data/corporate_actions.py","data/panel.py","data/source.py","data/snapshot.py","features/base.py","features/formulas.py","targets/builder.py","cache/rank_store.py","scan/dual_coarse.py","governance/access.py","execution/quote_replay.py"]
def sha(p):return sha256(p.read_bytes()).hexdigest()
rows=[]
for rel in MODULES:
    a=ROOT/"src/quant_pipeline/alpha_discovery"/rel; b=V2/"src/quant_pipeline/alpha_discovery"/rel; rows.append({"module":rel,"v3_sha256":sha(a),"v2_sha256":sha(b),"match":sha(a)==sha(b)})
cmd=[sys.executable,"-m","pytest","tests/parity","tests/ported_v2","-q"]
result=subprocess.run(cmd,cwd=ROOT)
payload={"created_at_utc":datetime.now(timezone.utc).isoformat(),"v2_read_only_root":str(V2),"runtime_dependency_on_v2":False,"module_parity":rows,"all_module_hashes_match":all(x["match"] for x in rows),"test_command":" ".join(cmd),"test_exit_code":result.returncode}
out=ROOT/"docs/V2_PARITY.json"; out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8"); print(out); raise SystemExit(result.returncode)
