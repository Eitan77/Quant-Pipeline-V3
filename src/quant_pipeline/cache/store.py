from __future__ import annotations
import hashlib, json, os, uuid
from pathlib import Path
from quant_pipeline.contracts import ArtifactKey
from quant_pipeline.errors import ArtifactValidationError

class ArtifactStore:
    def __init__(self,root:Path): self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def path_for(self,key:ArtifactKey,suffix:str="") -> Path:
        safe="".join(c if c.isalnum() or c in "-_." else "_" for c in key.semantic_id)
        if len(safe)>40: safe=f"{safe[:24]}-{hashlib.sha256(safe.encode()).hexdigest()[:12]}"
        return self.root/key.artifact_type/key.content_hash[:2]/f"{safe}__{key.content_hash[:24]}{suffix}"
    def manifest_path(self,key): return self.path_for(key,".manifest.json")
    def begin_file(self,key,suffix):
        p=self.path_for(key,f".{uuid.uuid4().hex}.partial{suffix}"); p.parent.mkdir(parents=True,exist_ok=True); return p
    @staticmethod
    def _sha(path):
        h=hashlib.sha256()
        with path.open("rb") as f:
            while b:=f.read(1024*1024): h.update(b)
        return h.hexdigest()
    def commit_file(self,key,partial_path,suffix,manifest_payload):
        final=self.path_for(key,suffix)
        if final.exists(): partial_path.unlink(missing_ok=True); return self.validate_file(key,suffix)
        final.parent.mkdir(parents=True,exist_ok=True); checksum=self._sha(partial_path); os.replace(partial_path,final)
        payload={"artifact_type":key.artifact_type,"artifact_id":key.semantic_id,"content_hash":key.content_hash,"schema_version":key.schema_version,"checksum":checksum,"status":"complete",**manifest_payload}
        tmp=self.manifest_path(key).parent/f"manifest-{uuid.uuid4().hex}.partial"
        tmp.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str),encoding="utf-8"); os.replace(tmp,self.manifest_path(key)); return final
    def has_complete(self,key,suffix=""):
        return self.path_for(key,suffix).exists() and self.manifest_path(key).exists()
    def validate_file(self,key,suffix=""):
        p=self.path_for(key,suffix); m=self.manifest_path(key)
        if not p.exists() or not m.exists(): raise ArtifactValidationError(f"Incomplete artifact {key.semantic_id}")
        data=json.loads(m.read_text(encoding="utf-8"))
        if data.get("status")!="complete" or data.get("checksum")!=self._sha(p): raise ArtifactValidationError(f"Invalid artifact {key.semantic_id}")
        return p
