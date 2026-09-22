#!/usr/bin/env python3
"""Import Cliplytics remix/result JSON into Somehow True CONTENT.csv.

Usage:
  python import_cliplytics.py --help
  python import_cliplytics.py --cliplytics-dir "C:\\Users\\Mauri\\Documents\\Python Projects\\Cliplytics"
  python import_cliplytics.py --input path\\to\\sidecar.json --write-config --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from providers.cliplytics_bridge import (
    DEFAULT_CLIPLYTICS_DIR,
    discover_paths,
    format_summary,
    import_items,
    load_items,
    prefer_sidecars,
)

ROOT = Path(__file__).resolve().parent
IMPORTS_ROOT = ROOT / "pipeline_output" / "imports"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Map Cliplytics tiktok_ready sidecars or results/*.json VideoResult "
            "objects into CONTENT.csv rows (CLX-* ids). Viral claims stay cited, "
            "not invented."
        )
    )
    parser.add_argument(
        "--cliplytics-dir",
        type=Path,
        default=DEFAULT_CLIPLYTICS_DIR,
        help=(
            "Cliplytics project root containing results/ and tiktok_ready/ "
            f"(default: {DEFAULT_CLIPLYTICS_DIR})"
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Specific JSON file or directory. Overrides --cliplytics-dir when set.",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "results", "tiktok_ready"),
        default="auto",
        help="auto prefers tiktok_ready sidecars, then leftover results JSON (default: auto)",
    )
    parser.add_argument("--limit", type=int, metavar="N", help="Import at most N new rows")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Map and report without writing CONTENT.csv or config files",
    )
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="Also emit produce_video config.json under pipeline_output/imports/<id>/",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "CONTENT.csv",
        help="CONTENT.csv path (default: repo CONTENT.csv)",
    )
    parser.add_argument(
        "--imports-dir",
        type=Path,
        default=IMPORTS_ROOT,
        help="Directory for optional produce configs (default: pipeline_output/imports)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = args.input
    cliplytics_dir = None if input_path is not None else args.cliplytics_dir
    try:
        paths = discover_paths(cliplytics_dir, input_path, args.source)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not paths:
        target = input_path or cliplytics_dir
        print(f"ERROR: No Cliplytics JSON found under {target}", file=sys.stderr)
        return 1

    items, skipped = load_items(paths)
    if args.source == "auto" and input_path is None:
        items, extra_skipped = prefer_sidecars(items)
        skipped.extend(extra_skipped)

    result = import_items(
        items,
        args.csv,
        limit=args.limit,
        dry_run=args.dry_run,
        write_config=args.write_config,
        imports_root=args.imports_dir,
    )
    result.skipped = skipped + result.skipped
    print(format_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
