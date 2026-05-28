"""One-time migration: re-resolve grounding-redirect URLs in saved intel files.

Walks every .data/{user_id}/results/ and rewrites market_intelligence.json and
company_intelligence.json with sanitized + resolved source_url values. A .bak
copy is written next to each file before overwriting.

Usage:
    python scripts/repair_intel_urls.py [DATA_DIR]

DATA_DIR defaults to .data/ in the repository root.
"""
import json
import shutil
import sys
from pathlib import Path

# Allow running from any cwd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.modules.url_utils import resolve_source_url  # noqa: E402

TARGETS = ("market_intelligence.json", "company_intelligence.json")


def repair_file(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text())
    items = data.get("items") or []
    stats = {"resolved": 0, "kept": 0, "fallback": 0, "empty": 0, "total": len(items)}
    for item in items:
        before = item.get("source_url", "")
        after, status = resolve_source_url(
            before,
            headline=item.get("headline", ""),
            source=item.get("source", ""),
        )
        item["source_url"] = after
        stats[status] += 1
    return data, stats


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / ".data")
    if not data_dir.exists():
        print(f"[repair] {data_dir} does not exist; nothing to do.")
        return

    total = {"resolved": 0, "kept": 0, "fallback": 0, "empty": 0, "files": 0}
    for udir in sorted(data_dir.iterdir()):
        if not udir.is_dir():
            continue
        results = udir / "results"
        if not results.exists():
            continue
        for name in TARGETS:
            path = results / name
            if not path.exists():
                continue
            print(f"\n[repair] {path}")
            backup = path.with_suffix(".json.bak")
            shutil.copy2(path, backup)
            data, stats = repair_file(path)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            print(
                f"  resolved={stats['resolved']} · kept={stats['kept']} · "
                f"fallback={stats['fallback']} · empty={stats['empty']} · "
                f"total={stats['total']} · backup={backup.name}"
            )
            total["resolved"] += stats["resolved"]
            total["kept"] += stats["kept"]
            total["fallback"] += stats["fallback"]
            total["empty"] += stats["empty"]
            total["files"] += 1

    print(
        f"\n[repair] done. {total['files']} file(s) updated. "
        f"resolved={total['resolved']} · kept={total['kept']} · "
        f"fallback={total['fallback']} · empty={total['empty']}"
    )


if __name__ == "__main__":
    main()
