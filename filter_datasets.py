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
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

GPKG_PATH = Path("metadata/shapefiles/biomas_wgs84.gpkg")
ROIS_CSV = Path("metadata/rois/rois_metadata.csv")
DATASETS_DIR = Path("metadata/datasets")
ROIS_DIR = Path("metadata/rois")

# Sensors present in the dataset JSONs (besides 'roi' and 'target')
ALL_SENSORS = ["s2_toa", "s1", "landsat8", "landsat9"]
DEFAULT_SENSORS = ["s2_toa"]


def normalize_name(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")


def make_suffix(biomes: list[str]) -> str:
    """Short suffix from biome names: ['amazonia', 'cerrado'] -> 'amz-cer'"""
    return "-".join(b[:3] for b in sorted(biomes))


def load_biome_rois(biomes: list[str]) -> set[str]:
    """Spatial join: return set of roi_ids (e.g. 'roi245610') in selected biomes."""
    if not GPKG_PATH.exists():
        raise FileNotFoundError(
            f"{GPKG_PATH} not found. Run download_shapefile.py first."
        )
    if not ROIS_CSV.exists():
        raise FileNotFoundError(
            f"{ROIS_CSV} not found. Run download.py (metadata step) first."
        )

    print("Loading biomes shapefile...")
    biomes_gdf = gpd.read_file(GPKG_PATH)
    selected = biomes_gdf[biomes_gdf["biome"].isin(biomes)].copy()
    if selected.empty:
        available = sorted(biomes_gdf["biome"].unique())
        raise ValueError(
            f"No biomes matched {biomes}.\nAvailable: {available}"
        )

    print(f"Loading ROI centroids ({ROIS_CSV})...")
    rois_df = pd.read_csv(ROIS_CSV)
    rois_gdf = gpd.GeoDataFrame(
        rois_df,
        geometry=[Point(float(row.longitude), float(row.latitude)) for row in rois_df.itertuples()],
        crs="EPSG:4326",
    )

    print("Running spatial join (point-in-polygon)...")
    joined = gpd.sjoin(rois_gdf, selected[["biome", "geometry"]], how="inner", predicate="within")

    roi_ids = set("roi" + str(rid) for rid in joined["roi_id"].astype(str))

    # Report per biome
    print(f"\nROIs per biome:")
    for biome in sorted(biomes):
        count = joined[joined["biome"] == biome].shape[0]
        print(f"  {biome}: {count:,}")
    print(f"  TOTAL: {len(roi_ids):,} ROIs\n")

    return roi_ids


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
