from importlib import import_module
from pathlib import Path
import yaml
def load_pack(path:Path):
    data=yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    required={"pack_id","pack_version","registry","implementation","availability_semantics","price_basis","canonical_mapping"};missing=required-set(data)
    if missing:raise ValueError(f"Feature pack missing {sorted(missing)}")
    def resolve(value):
        module,name=value.split(":",1);return getattr(import_module(module),name)
    return data,resolve(data["registry"]),resolve(data["implementation"])

