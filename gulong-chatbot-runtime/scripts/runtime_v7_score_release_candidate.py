"""Rescore a completed Runtime V7 matrix without repeating live model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime_v7.promotion_health_evaluator import (  # noqa: E402
    load_json,
    render_health_markdown,
    score_release_candidate,
)


def main() -> None:
    """Rescore one saved matrix artifact without repeating live-model calls."""

    parser = argparse.ArgumentParser()
    parser.add_argument("summary", help="Existing release-candidate summary.json")
    parser.add_argument("--baseline-summary", default="")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    artifact = load_json(summary_path)
    baseline = load_json(Path(args.baseline_summary)) if args.baseline_summary else None
    report = score_release_candidate(
        artifact,
        baseline=baseline,
    )

    out_dir = Path(args.out_dir) if args.out_dir else summary_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "promotion_health.json"
    markdown_path = out_dir / "promotion_health.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_health_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "promotion_health_json": str(json_path.resolve()),
                "promotion_health_markdown": str(markdown_path.resolve()),
                "grade": report["grade"],
                "promotion_status": report["promotion_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if report["promotion_status"] != "ready_for_promotion":
        raise SystemExit(2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
