from __future__ import annotations
from dataclasses import asdict,dataclass
from hashlib import sha256
from pathlib import Path
from quant_pipeline.hashing import content_hash

@dataclass(frozen=True,slots=True)
class SourceFileEntry:
    relative_path:str; size:int; mtime_ns:int

def build_source_manifest(data_root:Path,pattern:str="**/*.parquet")->dict:
    root=Path(data_root).resolve(); files=[]
    for path in sorted(root.glob(pattern)):
        if path.is_file():
            stat=path.stat(); files.append(SourceFileEntry(path.relative_to(root).as_posix(),int(stat.st_size),int(stat.st_mtime_ns)))
    payload={"root_identity":root.name,"file_count":len(files),"files":[asdict(x) for x in files]}
    return {**payload,"source_manifest_hash":content_hash(payload)}

def build_production_source_manifest(*,data_root:Path,repo_root:Path)->dict:
    external=build_source_manifest(data_root); references=[]; root=Path(repo_root)
    for relative in ("reference/security_master.parquet","reference/sp500_pit_membership_daily.parquet","reference/corporate_actions.parquet"):
        path=root/relative; digest=sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""): digest.update(chunk)
        references.append({"relative_path":relative,"size":path.stat().st_size,"sha256":digest.hexdigest()})
    payload={"external_source_manifest_hash":external["source_manifest_hash"],"reference_files":references,"schema_version":1}
    return {**payload,"external_manifest":external,"source_manifest_hash":content_hash(payload)}
