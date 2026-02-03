#!/usr/bin/env python3
"""
CLI entrypoint for the orchestrator.

Usage:
    python -m scripts.run_orchestrator "2024年の雇用統計は？"
    python -m scripts.run_orchestrator "人口推計" --year 2024 --retrieve 3
    python -m scripts.run_orchestrator "労働・賃金" --discover 10 --retrieve 2

Options:
    --year         Override year for discovery (default: extracted from question or 2024)
    --lang         Language code (default: J)
    --discover     Max datasets to discover (default: 5)
    --retrieve     Max datasets to retrieve (default: 1)
    --max-rows     Max rows per table in output (default: 100 for CLI display)
    --json         Output as JSON instead of formatted text
    --verbose      Enable debug logging
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from kumonjo.orchestrator import run_orchestrator


def format_result(result, max_preview_rows: int = 10) -> str:
    """Format OrchestratorResult for human-readable CLI output."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"Question: {result.question}")
    lines.append(f"Year: {result.year} | Lang: {result.lang}")
    lines.append("=" * 60)

    if result.error:
        lines.append(f"\n❌ Error: {result.error}")

    # Discovered datasets
    lines.append(f"\n📋 Discovered: {len(result.discovered)} dataset(s)")
    for i, ds in enumerate(result.discovered, 1):
        name = ds.get("statistics_name", "N/A")
        sid = ds.get("statsDataId", "N/A")
        gov = ds.get("gov_org_name", "")
        lines.append(f"  {i}. [{sid}] {name}")
        if gov:
            lines.append(f"     府省: {gov}")

    # Retrieved tables
    lines.append(f"\n📊 Retrieved: {len(result.retrieved)} table(s)")
    for i, table in enumerate(result.retrieved, 1):
        sid = table.get("stats_data_id", "N/A")
        meta = table.get("metadata", {})
        name = meta.get("statistics_name", "N/A")
        error = table.get("error")

        lines.append(f"\n  Table {i}: [{sid}] {name}")
        if error:
            lines.append(f"    ❌ Error: {error}")
            continue

        row_count = table.get("row_count", 0)
        truncated = table.get("truncated", False)
        columns = table.get("columns", [])
        rows = table.get("rows", [])

        lines.append(f"    Rows: {row_count}" + (" (truncated)" if truncated else ""))
        lines.append(f"    Columns: {', '.join(columns[:10])}" + ("..." if len(columns) > 10 else ""))

        # Preview first few rows
        if rows:
            lines.append(f"    Preview ({min(len(rows), max_preview_rows)} rows):")
            for j, row in enumerate(rows[:max_preview_rows]):
                # Show only first few columns for readability
                preview_cols = columns[:5]
                vals = [str(row.get(c, ""))[:20] for c in preview_cols]
                lines.append(f"      {j+1}. " + " | ".join(vals))
            if len(rows) > max_preview_rows:
                lines.append(f"      ... ({len(rows) - max_preview_rows} more rows)")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Run the kumonjo orchestrator: discover and retrieve e-Stat data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "question",
        help="Natural language question (e.g., '2024年の雇用統計は？')",
    )
    parser.add_argument(
        "--year",
        default=None,
        help="Override year for discovery (default: extracted from question or 2024)",
    )
    parser.add_argument(
        "--lang",
        default="J",
        help="Language code (default: J)",
    )
    parser.add_argument(
        "--discover",
        type=int,
        default=5,
        help="Max datasets to discover (default: 5)",
    )
    parser.add_argument(
        "--retrieve",
        type=int,
        default=1,
        help="Max datasets to retrieve (default: 1)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=100,
        help="Max rows per table in output (default: 100)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # Run orchestrator
    result = run_orchestrator(
        question=args.question,
        year=args.year,
        lang=args.lang,
        discover_limit=args.discover,
        retrieve_limit=args.retrieve,
        max_rows_per_table=args.max_rows,
    )

    # Output
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_result(result))

    # Exit with error code if orchestrator failed
    sys.exit(0 if not result.error or result.retrieved else 1)


if __name__ == "__main__":
    main()
