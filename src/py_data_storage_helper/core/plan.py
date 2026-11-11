import json
import datetime
from typing import List, Dict, Optional, Any

class StoragePlan:
    """Represents the portable reorganization plan (.stplan) that survives admin elevation."""

    def __init__(self, plan_name: str = "Unbenannter Plan"):
        self.plan_version = "1.4"
        self.created_at = datetime.datetime.now().isoformat()
        self.name = plan_name
        self.operations: List[Dict[str, Any]] = []
        self.batch_rules: List[Dict[str, Any]] = []

    def add_operation(self, op_type: str, src_vol: str, src_path: str, tgt_vol: str, tgt_path: str, size: int) -> None:
        self.operations.append({
            "op_id": f"op_{len(self.operations)+1:04d}",
            "type": op_type,
            "source_volume": src_vol,
            "source_path": src_path,
            "target_volume": tgt_vol,
            "target_path": tgt_path,
            "size": size,
            "status": "PENDING",
            "checksum": None
        })

    def replace_with(self, other: 'StoragePlan') -> None:
        """Übernimmt den Inhalt eines anderen Plans, ohne das Objekt auszutauschen (alle Views teilen sich dieses Objekt)."""
        self.plan_version = other.plan_version
        self.created_at = other.created_at
        self.name = other.name
        self.operations[:] = list(other.operations)
        self.batch_rules[:] = list(other.batch_rules)

    def to_json(self) -> str:
        data = {
            "plan_version": self.plan_version,
            "created_at": self.created_at,
            "name": self.name,
            "operations": self.operations,
            "batch_rules": self.batch_rules
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def save_to_file(self, file_path: str) -> bool:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.to_json())
            return True
        except Exception:
            return False

    @classmethod
    def load_from_file(cls, file_path: str) -> Optional['StoragePlan']:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            plan = cls(plan_name=data.get("name", "Geladener Plan"))
            plan.plan_version = data.get("plan_version", "1.0")
            plan.created_at = data.get("created_at", "")
            plan.operations = data.get("operations", [])
            plan.batch_rules = data.get("batch_rules", [])
            return plan
        except Exception as e:
            print(f"Error loading plan: {e}")
            return None

