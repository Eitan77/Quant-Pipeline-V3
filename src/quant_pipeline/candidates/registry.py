class EdgeRegistry:
    VALID={"frozen_discovery_candidate","dossier_complete","replication_authorized","replicated","rejected","superseded"}
    def __init__(self):self.rows={}
    def put(self,row):
        if row["status"] not in self.VALID:raise ValueError("Invalid candidate lifecycle status")
        cid=row["candidate_id"]
        if cid in self.rows and self.rows[cid].get("definition_hash")!=row.get("definition_hash"):raise ValueError("Candidate identity conflict")
        self.rows[cid]=dict(row)

