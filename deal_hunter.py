#!/usr/bin/env python3
"""Energy + Protein Deal Radar — entry point.

  python deal_hunter.py                     # auto: picks quick/deep/calibrate/skip by schedule slot
  python deal_hunter.py --mode deep         # one research call per product
  python deal_hunter.py --mode calibrate    # verify labels + set ref prices from regular prices
  python deal_hunter.py --mode check        # tiny API + web search + ntfy connectivity check
  python deal_hunter.py --only barebells    # single product (implies deep)
  python deal_hunter.py --dry-run           # fixtures, no API calls, writes to .dryrun/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252; tiers use emoji
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from radar.pipeline import RunOptions, main_from_cli  # noqa: E402


def parse(argv: list[str] | None = None) -> RunOptions:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default="auto", choices=["auto", "quick", "deep", "calibrate", "check", "init"])
    ap.add_argument("--only", metavar="PRODUCT_ID", help="research a single product")
    ap.add_argument("--dry-run", action="store_true", help="use fixtures; no API calls; no pushes")
    ap.add_argument("--no-push", action="store_true", help="print ntfy payloads instead of sending")
    ap.add_argument("--no-commit", action="store_true", help="tell the workflow not to commit outputs")
    ap.add_argument("--slot", choices=["morning", "midday", "evening", "manual"], help="override schedule slot")
    ap.add_argument("--out", type=Path, help="write data/ and Obsidian-Vault/ under this directory")
    a = ap.parse_args(argv)
    return RunOptions(mode=a.mode, only=a.only, dry_run=a.dry_run, no_push=a.no_push,
                      no_commit=a.no_commit, out=a.out, slot=a.slot)


if __name__ == "__main__":
    sys.exit(main_from_cli(parse()))
