#!/usr/bin/env python
"""Derive Sentinel-2-only dataset JSONs from the s2-s1 / s2-s1-landsat variants.

The shipped dataset JSONs always bundle S1 (and sometimes Landsat). This empties
every non-S2 modality (``s1``, ``landsat8``, ``landsat9``, …) per sample while
keeping ``s2_toa`` / ``target`` / ``roi``, and rewrites the ``sensors`` tag in
the filename to ``s2``. The loader treats an empty modality list like an absent
one, so the output trains/vals/tests directly.

    uv run python make_s2_only.py metadata/datasets/train_tx3_s2-s1_100pct.json
    # -> metadata/datasets/train_tx3_s2_100pct.json

The output is *not* versioned (all of metadata/ is gitignored); regenerate it
after downloading metadata.
"""
import argparse
import json
import re
from pathlib import Path

KEEP = {"roi", "target", "s2_toa"}  # everything else is a non-S2 modality
# Derived splits land here, NOT in metadata/datasets/: that directory is AllClear's own
# shipped metadata, re-extracted from metadata.tar.gz on every download_metadata(). Keeping
# ours apart makes "shipped" vs "ours" a directory question, not a filename question.
OUT_DIR = Path("metadata/lnlm")


def s2_only(src: Path) -> Path:
    data = json.loads(src.read_text())
    for sample in data.values():
        for key in sample:  # reassign in place; no keys added/removed
            if key not in KEEP:
                sample[key] = []
    name = re.sub(r"s2-s1(-landsat)?", "s2", src.name)
    if name == src.name:
        raise ValueError(f"{src.name}: no 's2-s1[-landsat]' tag to rewrite")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / name
    dst.write_text(json.dumps(data))
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jsons", nargs="+", type=Path,
                    help="s2-s1[-landsat] dataset JSON(s) to strip to S2-only")
    for src in ap.parse_args().jsons:
        print(f"{src.name} -> {s2_only(src).name}")


if __name__ == "__main__":
    main()
