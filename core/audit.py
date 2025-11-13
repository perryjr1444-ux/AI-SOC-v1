import json
import hashlib
import datetime
import os
from pathlib import Path

# Use a configurable log directory
_LOG_DIR = Path(os.environ.get("AUDIT_LOG_DIR", "/var/log/mac_blue_team_audit"))
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Fall back to a temp directory if we don't have permissions
    _LOG_DIR = Path("/tmp/mac_blue_team_audit")
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


class AuditLog:
    """
    Append-only log. Every entry is hashed together with the previous
    entry to produce a simple Merkle-chain. The latest root hash can be
    periodically anchored (e.g., to a public blockchain or a signed
    timestamp authority) for extra non-repudiation.
    """

    def __init__(self, case_id: str):
        self.case_id = case_id
        _ensure_log_dir()
        self.file = _LOG_DIR / f"{case_id}.log"

    def _last_hash(self) -> str:
        if not self.file.exists() or self.file.stat().st_size == 0:
            return "0" * 64
        with self.file.open("rb") as f:
            f.seek(-130, 2)  # each line ends with "... <hash>\n"
            tail = f.read().decode()
            return tail.strip().split()[-1]

    def record(self, *, case_id: str, task_id: str, event: str, details: str = ""):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        entry = {
            "case_id": case_id,
            "task_id": task_id,
            "event": event,
            "details": details,
            "ts": ts,
        }
        entry_json = json.dumps(entry, separators=(",", ":"))
        prev = self._last_hash()
        chain_hash = hashlib.sha256((prev + entry_json).encode()).hexdigest()
        line = f"{entry_json} {chain_hash}\n"
        with self.file.open("a", encoding="utf-8") as f:
            f.write(line)

    def get_latest_hash(self) -> str:
        """
        Retrieve the latest hash in the chain. Returns the genesis hash
        (64 zeros) if the log is empty.
        """
        return self._last_hash()

    def get_entries(self, limit: int = None) -> list:
        """
        Retrieve log entries. If limit is specified, returns the last N entries.
        Otherwise returns all entries.
        
        Returns a list of dicts, each containing:
        - entry: the original log entry (dict)
        - hash: the computed hash for this entry
        """
        if not self.file.exists():
            return []
        
        entries = []
        with self.file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Split on last space to separate JSON from hash
                parts = line.rsplit(" ", 1)
                if len(parts) == 2:
                    entry_json, entry_hash = parts
                    try:
                        entry_dict = json.loads(entry_json)
                        entries.append({"entry": entry_dict, "hash": entry_hash})
                    except json.JSONDecodeError:
                        continue
        
        if limit is not None and limit > 0:
            return entries[-limit:]
        return entries

    def get_all_entries(self) -> list:
        """
        Retrieve all log entries. Alias for get_entries() without limit.
        """
        return self.get_entries()

    def verify_chain(self) -> bool:
        """
        Verify the integrity of the entire chain by recomputing hashes.
        Returns True if the chain is valid, False otherwise.
        """
        if not self.file.exists():
            return True
        
        entries = self.get_entries()
        if not entries:
            return True
        
        prev_hash = "0" * 64
        for entry_data in entries:
            entry_json = json.dumps(entry_data["entry"], separators=(",", ":"))
            computed_hash = hashlib.sha256((prev_hash + entry_json).encode()).hexdigest()
            
            if computed_hash != entry_data["hash"]:
                return False
            
            prev_hash = entry_data["hash"]
        
        return True

    def anchor(self, anchor_data: dict = None) -> dict:
        """
        Anchor the current chain state to an external timestamp or blockchain.
        This creates a tamper-evident record of the chain state at a specific point in time.
        
        Args:
            anchor_data: Optional dict containing anchoring metadata (e.g., blockchain tx ID,
                        timestamp authority signature, etc.)
        
        Returns:
            dict containing:
            - latest_hash: the hash being anchored
            - timestamp: ISO 8601 timestamp of anchoring
            - anchor_data: any additional anchoring metadata provided
            - case_id: the case ID this log belongs to
        """
        latest_hash = self.get_latest_hash()
        ts = datetime.datetime.utcnow().isoformat() + "Z"
        
        anchor_record = {
            "case_id": self.case_id,
            "latest_hash": latest_hash,
            "timestamp": ts,
            "anchor_data": anchor_data or {},
        }
        
        # Optionally, store anchor records in a separate file
        anchor_file = _LOG_DIR / f"{self.case_id}_anchors.json"
        anchors = []
        if anchor_file.exists():
            with anchor_file.open("r", encoding="utf-8") as f:
                try:
                    anchors = json.load(f)
                except json.JSONDecodeError:
                    anchors = []
        
        anchors.append(anchor_record)
        
        with anchor_file.open("w", encoding="utf-8") as f:
            json.dump(anchors, f, indent=2)
        
        return anchor_record

    def get_anchors(self) -> list:
        """
        Retrieve all anchor records for this case.
        
        Returns:
            list of anchor records (dicts)
        """
        anchor_file = _LOG_DIR / f"{self.case_id}_anchors.json"
        if not anchor_file.exists():
            return []
        
        with anchor_file.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
