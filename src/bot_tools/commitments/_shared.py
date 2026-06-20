"""Shared helper for the commitment tools."""
import json


def resolve_commitment(data_dir, index_or_hint: str):
    """Return (commitment_id, description) by 1-based index or keyword match."""
    try:
        path = data_dir / "results" / "commitments_extract.json"
        if not path.exists():
            return None, ""
        data = json.loads(path.read_text())
        items = data.get("items", [])
        try:
            idx = int(index_or_hint) - 1
            if 0 <= idx < len(items):
                return items[idx]["id"], items[idx].get("description", "")
        except ValueError:
            hint = index_or_hint.lower()
            for item in items:
                if hint in (item.get("description") or "").lower():
                    return item["id"], item.get("description", "")
    except Exception:
        pass
    return None, ""
