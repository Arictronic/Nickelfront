from __future__ import annotations

import argparse
import csv
from pathlib import Path


KEYS = [
    "block_confusion_issue_pages",
    "block_confusion_issue_count",
    "heading_like_body_blocks",
    "formula_like_body_blocks",
    "caption_like_body_blocks",
    "content_sync_issue_pages",
    "final_block_text_not_in_page_pages",
    "qwen_projection_leakage_hits",
    "embedding_projection_leakage_hits",
]


def load_sample_set(path: Path | None) -> set[str]:
    if path is None:
        return set()
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value:
            continue
        items.append(value.lower().replace("/", "\\"))
    return set(items)


def aggregate_summary(path: Path, sample_set: set[str]) -> dict[str, int]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    out = {key: 0 for key in KEYS}
    for row in rows:
        file_key = str(row.get("file") or "").strip().lower().replace("/", "\\")
        if sample_set and file_key not in sample_set:
            continue
        for key in KEYS:
            try:
                out[key] += int(float(row.get(key, 0) or 0))
            except Exception:
                pass
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare PDF parser audit summary metrics.")
    parser.add_argument("--baseline", required=True, help="Path to baseline summary.csv")
    parser.add_argument("--current", required=True, help="Path to current summary.csv")
    parser.add_argument("--sample-list", default="", help="Optional sample list to filter files")
    args = parser.parse_args()

    baseline_path = Path(args.baseline).resolve()
    current_path = Path(args.current).resolve()
    sample_set = load_sample_set(Path(args.sample_list).resolve()) if args.sample_list else set()

    baseline = aggregate_summary(baseline_path, sample_set)
    current = aggregate_summary(current_path, sample_set)
    delta = {key: current[key] - baseline[key] for key in KEYS}

    print("Baseline:", baseline)
    print("Current :", current)
    print("Delta   :", delta)

    failures: list[str] = []
    for key in (
        "block_confusion_issue_pages",
        "block_confusion_issue_count",
        "heading_like_body_blocks",
        "formula_like_body_blocks",
        "caption_like_body_blocks",
        "content_sync_issue_pages",
        "final_block_text_not_in_page_pages",
        "qwen_projection_leakage_hits",
        "embedding_projection_leakage_hits",
    ):
        if delta[key] > 0:
            failures.append(f"{key} regressed by +{delta[key]}")

    if current["caption_like_body_blocks"] > 2:
        failures.append(f"caption_like_body_blocks out of corridor: {current['caption_like_body_blocks']} (>2)")
    if current["content_sync_issue_pages"] > 0:
        failures.append(f"content_sync_issue_pages must be 0, got {current['content_sync_issue_pages']}")
    if current["final_block_text_not_in_page_pages"] > 0:
        failures.append("final_block_text_not_in_page_pages must be 0")
    if current["qwen_projection_leakage_hits"] > 0 or current["embedding_projection_leakage_hits"] > 0:
        failures.append("projection leakage must remain 0")

    if failures:
        print("RESULT: FAIL")
        for item in failures:
            print(" -", item)
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
