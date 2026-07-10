#!/usr/bin/env python
"""Pick one random ROI from a dataset JSON and write a single-ROI JSON, so a tiny
local download grabs exactly that ROI for validation:

    uv run --no-project python pick_roi.py                 # random ROI -> metadata/datasets/single_roi.json
    uv run --no-project python pick_roi.py --seed 0        # reproducible pick
    uv run --no-project python pick_roi.py --roi roi12345  # a specific ROI
    uv run python download.py --data-only --from-json metadata/datasets/single_roi.json --cpus 4

The ROI id is taken from a real dataset JSON, so it exists on the server and
survives download.py's intersection with the ROI txt lists. download.py fetches
the whole roiXXXX.tar.gz regardless of how many sequences are referenced, so one
ROI is enough (~184 MB) to get a real sample.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="metadata/datasets/train_tx3_s2-s1_100pct.json")
    ap.add_argument("--out", default="metadata/datasets/single_roi.json")
    ap.add_argument("--seed", type=int, default=None, help="fix the random pick (default: truly random)")
    ap.add_argument("--roi", default=None, help="pick this ROI id instead of a random one")
    args = ap.parse_args()

    data = json.load(open(args.source))
    by_roi: dict[str, dict] = {}
    for k, v in data.items():
        by_roi.setdefault(v["roi"][0], {})[k] = v

    if args.roi:
        if args.roi not in by_roi:
            ap.error(f"{args.roi} not referenced by {args.source} ({len(by_roi):,} ROIs available)")
        roi = args.roi
    else:
        roi = random.Random(args.seed).choice(sorted(by_roi))

    entries = by_roi[roi]
    Path(args.out).write_text(json.dumps(entries))
    lat, lon = entries[next(iter(entries))]["roi"][1]
    print(f"ROI {roi}  ({lat:.4f}, {lon:.4f})  {len(entries)} sequence(s)  ->  {args.out}")
    print(f"download: uv run python download.py --data-only --from-json {args.out} --cpus 4")


if __name__ == "__main__":
    main()
