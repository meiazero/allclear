"""
Filters AllClear dataset JSON files to a biome/region subset.

Reads the IBGE biomes shapefile (produced by download_shapefile.py) and
filters both the ROI list and all dataset JSONs to only include ROIs whose
centroid falls within the selected biomes.

Outputs:
  metadata/rois/rois_{suffix}.txt          — filtered ROI ID list
  metadata/datasets/*_{suffix}.json        — filtered dataset JSONs (originals untouched)

Usage:
  uv run python filter_datasets.py --biomes amazonia cerrado pantanal
  uv run python filter_datasets.py --biomes amazonia --sensors s2_toa s1
"""

import argparse
import json
from pathlib import Path

from biomes import load_biome_rois, normalize_name

DATASETS_DIR = Path("metadata/datasets")
ROIS_DIR = Path("metadata/rois")

# Sensors present in the dataset JSONs (besides 'roi' and 'target')
ALL_SENSORS = ["s2_toa", "s1", "landsat8", "landsat9"]
DEFAULT_SENSORS = ["s2_toa"]


def make_suffix(biomes: list[str]) -> str:
    """Short suffix from biome names: ['amazonia', 'cerrado'] -> 'amz-cer'"""
    return "-".join(b[:3] for b in sorted(biomes))


def filter_sample(sample: dict, keep_sensors: list[str]) -> dict:
    """Remove sensor keys not in keep_sensors from a dataset sample."""
    result = {"roi": sample["roi"], "target": sample["target"]}
    for sensor in keep_sensors:
        if sensor in sample:
            result[sensor] = sample[sensor]
    return result


def filter_datasets(roi_ids: set[str], keep_sensors: list[str], suffix: str):
    json_files = sorted(DATASETS_DIR.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {DATASETS_DIR}")
        return

    print(f"Filtering {len(json_files)} dataset JSON files...")
    for json_path in json_files:
        out_path = DATASETS_DIR / f"{json_path.stem}_{suffix}.json"
        if out_path.exists():
            print(f"  skip (exists): {out_path.name}")
            continue

        with open(json_path) as f:
            data = json.load(f)

        filtered = {
            k: filter_sample(v, keep_sensors)
            for k, v in data.items()
            if v["roi"][0] in roi_ids
        }

        with open(out_path, "w") as f:
            json.dump(filtered, f)

        pct = 100 * len(filtered) / len(data) if data else 0
        print(f"  {json_path.name}: {len(filtered):,} / {len(data):,} samples ({pct:.1f}%) → {out_path.name}")


def save_roi_list(roi_ids: set[str], suffix: str):
    out_path = ROIS_DIR / f"rois_{suffix}.txt"
    with open(out_path, "w") as f:
        f.write("\n".join(sorted(roi_ids)) + "\n")
    print(f"ROI list saved: {out_path} ({len(roi_ids):,} ROIs)")


def main():
    parser = argparse.ArgumentParser(description="Filter AllClear datasets by biome")
    parser.add_argument(
        "--biomes",
        nargs="+",
        required=True,
        help="Normalized biome names (run download_shapefile.py to see options). "
             "e.g. --biomes amazonia cerrado pantanal",
    )
    parser.add_argument(
        "--sensors",
        nargs="+",
        default=DEFAULT_SENSORS,
        choices=ALL_SENSORS,
        help=f"Sensors to keep in output JSONs (default: {DEFAULT_SENSORS}). "
             f"Available: {ALL_SENSORS}",
    )
    args = parser.parse_args()

    biomes = [normalize_name(b) for b in args.biomes]
    suffix = make_suffix(biomes)

    print(f"Biomes : {biomes}")
    print(f"Sensors: {args.sensors}")
    print(f"Suffix : _{suffix}\n")

    roi_ids = load_biome_rois(biomes)
    save_roi_list(roi_ids, suffix)
    filter_datasets(roi_ids, args.sensors, suffix)

    print("\nDone. Original files untouched.")


if __name__ == "__main__":
    main()
