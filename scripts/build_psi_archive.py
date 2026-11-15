#!/usr/bin/env python3
"""Download the full public NASA PSI catalogue and its linked files for packaging.

Run this on an internet-connected build machine before creating the executable.
The PSI archive alone is capped at 12,000,000,000 bytes (12 GB decimal).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.psi import PSIProvider
from app.psi_archive import BUNDLE_DIR, PSI_QUOTA_BYTES, archive_status, sync_psi_archive


async def main() -> int:
    parser = argparse.ArgumentParser(description="Build the bundled NASA PSI research archive")
    parser.add_argument("--output", type=Path, default=BUNDLE_DIR, help="Bundled PSI data directory")
    parser.add_argument("--allow-empty", action="store_true", help="Allow packaging when PSI returns no investigation records")
    parser.add_argument("--allow-incomplete", action="store_true", help="Development only: allow fewer than the reported/expected catalogue count")
    parser.add_argument("--minimum-records", type=int, default=100, help="Minimum expected catalogue records; default guards against a partial first page")
    args = parser.parse_args()
    print(f"NASA PSI source: https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation")
    print(f"PSI-only storage ceiling: {PSI_QUOTA_BYTES:,} bytes (12 GB)")
    provider = PSIProvider()
    result = await sync_psi_archive(provider, directory=args.output, full=True)
    print(f"Investigations: {result['catalog_count']}")
    print(f"Files listed: {result['files_listed']}; downloaded: {result['files_downloaded']}")
    print(f"Storage used: {result['storage']['storage_bytes']:,} bytes")
    for error in result.get("errors", []):
        print(f"WARNING: {error}")
    expected = result.get("catalog_total")
    if not result.get("catalog_complete") and not args.allow_incomplete:
        suffix = f" of {expected}" if expected is not None else ""
        print(f"ERROR: catalogue pagination was not verified ({result['catalog_count']}{suffix} records); refusing a potentially partial snapshot.", file=sys.stderr)
        return 3
    if expected is not None and result["catalog_count"] < expected and not args.allow_incomplete:
        print(f"ERROR: only {result['catalog_count']} of {expected} PSI records were retrieved; refusing a partial snapshot.", file=sys.stderr)
        return 3
    if result["catalog_count"] == 0 and not args.allow_empty:
        print("ERROR: NASA PSI returned zero records. No empty executable snapshot will be published.", file=sys.stderr)
        return 2
    if result["catalog_count"] < args.minimum_records and not args.allow_incomplete:
        print(f"ERROR: only {result['catalog_count']} records were retrieved (minimum {args.minimum_records}). Check pagination/browser fallback; no partial snapshot will be published.", file=sys.stderr)
        return 2
    print(f"Bundled archive written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
