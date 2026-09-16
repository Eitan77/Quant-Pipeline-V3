from __future__ import annotations
from dataclasses import asdict,dataclass
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
