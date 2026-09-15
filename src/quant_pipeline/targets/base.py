from dataclasses import dataclass
@dataclass(frozen=True,slots=True)
class TargetArray: values:object; valid:object; target_id:str; return_basis:str; definition_hash:str

