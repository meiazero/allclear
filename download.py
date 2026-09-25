"""AllClear: download, compact and verify under the directory given by --dir.

    python download.py download --dir <dir> [--from-json <list.json> ...]  # login node + verify
    python download.py prepare --dir <dir> --workers 64                   # cpuq: compact + verify
    python download.py verify --dir <dir> [--from-json <list.json> ...] [--sample 500]

Each action exits 0 only when verify passes; re-run the same command to resume.

ROIs: every ROI in metadata/rois/*.txt, restricted to those referenced by --from-json and to
one spatial filter (--biomes, --brazil or --bbox). Verify checks every raster that the sample
lists (--from-json, default every metadata/datasets/*.json) need for the selected ROIs.

Source: https://allclear.cs.cornell.edu/dataset/allclear/{metadata.tar.gz,data/<roi>.tar.gz}
The archives hold float64 rasters; `prepare` rewrites them losslessly (common.py).
"""

import argparse
import csv
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import biomes
import common

URL = "https://allclear.cs.cornell.edu/dataset/allclear"
# Band count per sensor directory.
BANDS = {"s2_toa": 13, "cld_shdw": 5, "s1": 2, "landsat8": 12, "landsat9": 12}
BRAZIL_BBOX = (-33.75, -73.99, 5.27, -28.85)  # (lat_min, lon_min, lat_max, lon_max)
ROI_LISTS = ("test_rois_3k.txt", "train_rois_19k.txt", "val_rois_1k.txt")
AVG_MB_PER_ROI = 184  # ponytail: measured median of sampled ROI archives; --dry-run estimate only


# ---------------------------------------------------------------- ROI selection


def sample_lists(root: Path, lists: list[Path] | None) -> list[Path]:
    return lists or sorted((root / "metadata/datasets").glob("*.json"))


def roi_of(sample: dict) -> str:
    roi = sample["roi"]
    return roi[0] if isinstance(roi, list) else roi


def rois_in_bbox(root: Path, bbox: tuple[float, float, float, float]) -> set[str]:
    lat_min, lon_min, lat_max, lon_max = bbox
    with (root / "metadata/rois/rois_metadata.csv").open(newline="") as f:
        return {
            f"roi{row['roi_id']}"
            for row in csv.DictReader(f)
            if lat_min <= float(row["latitude"]) <= lat_max
            and lon_min <= float(row["longitude"]) <= lon_max
        }


def select_rois(
    root: Path,
    lists: list[Path] | None = None,
    biome_names: list[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> set[str]:
    """ROIs of metadata/rois/*.txt, restricted to --from-json lists and one spatial filter."""
    out: set[str] = set()
    for name in ROI_LISTS:
        path = root / "metadata/rois" / name
        out |= {line.strip() for line in path.read_text().splitlines() if line.strip()}
    if lists:
        out &= {roi_of(s) for p in lists for s in json.loads(p.read_text()).values()}
    if biome_names:
        out &= biomes.load_biome_rois(biome_names, root / "metadata")
    elif bbox:
        out &= rois_in_bbox(root, bbox)
    return out


# ---------------------------------------------------------------- download


def download_metadata(root: Path) -> None:
    if (root / "metadata/datasets").is_dir():
        return
    archive = root / "metadata.tar.gz"
    common.fetch(f"{URL}/metadata.tar.gz", archive)
    staged = common.extract_atomic(archive, root / ".staging_metadata")
    inner = staged / "metadata" if (staged / "metadata").is_dir() else staged
    common.move_tree(inner, root / "metadata")
    shutil.rmtree(staged, ignore_errors=True)


def download(root: Path, rois: set[str], workers: int = 8) -> dict[str, str]:
    """Fetch and extract every ROI archive not yet in <root>/data -> {roi: error} of failures."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    todo = sorted(r for r in rois if not (data / r).is_dir())

    def one(roi: str) -> tuple[str, str]:
        try:
            archive = data / f"{roi}.tar.gz"
            common.fetch(f"{URL}/data/{roi}.tar.gz", archive)
            staged = common.extract_atomic(archive, data / f".staging_{roi}")
            (staged / roi).rename(data / roi)
            shutil.rmtree(staged, ignore_errors=True)
            return roi, "ok"
        except Exception as e:  # keep going; failures are listed and retried on re-run
            return roi, f"error: {e}"

    print(f"AllClear: {len(todo)} ROIs to download into {data}")
    results = {}
    with ThreadPoolExecutor(workers) as pool:
        for i, (roi, status) in enumerate(pool.map(one, todo), 1):
            results[roi] = status
            if status != "ok" or i % 100 == 0:
                print(f"[{i}/{len(todo)}] {roi} {status}", flush=True)
    failed = {r: s for r, s in results.items() if s != "ok"}
    print(f"AllClear: {len(todo) - len(failed)} downloaded, {len(failed)} failed")
    return failed


def compact(root: Path, workers: int = 8) -> dict[str, str]:
    return common.compact_dirs((d for d in (root / "data").glob("roi*") if d.is_dir()), workers)


# ---------------------------------------------------------------- verify


def needed_paths(root: Path, lists: list[Path] | None, rois: set[str]) -> list[str]:
    """Every raster the sample lists need for `rois`, including the cld_shdw of each S2 date."""
    paths: set[str] = set()
    for path in sample_lists(root, lists):
        for sample in json.loads(path.read_text()).values():
            if roi_of(sample) not in rois:
                continue
            for key in ("s2_toa", "s1", "landsat8", "landsat9", "target"):
                for _, rel in sample.get(key, []):
                    paths.add(rel)
                    if key in ("s2_toa", "target"):
                        paths.add(rel.replace("s2_toa", "cld_shdw"))
    return sorted(paths)


def verify(root: Path, rois: set[str], lists: list[Path] | None = None, sample: int = 500) -> bool:
    """Existence of every file the lists need + a deep read of `sample` random rasters."""
    rels = needed_paths(root, lists, rois)
    missing = [r for r in rels if not (root / "data" / r).is_file()]
    absent = set(missing)
    files = [root / "data" / r for r in rels if r not in absent]
    extra = {
        "lists": [str(p) for p in (lists or [])] or "all metadata/datasets/*.json",
        "selected_rois": len(rois),
        "missing_rois": sorted({m.split("/")[0] for m in missing}),
    }
    return common.verify_files(
        "allclear", root, files, missing, lambda p: BANDS.get(p.parent.name), extra, sample
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("download", "prepare", "verify"))
    ap.add_argument(
        "--dir", type=Path, required=True, help="where the dataset is created and saved"
    )
    ap.add_argument("--from-json", type=Path, nargs="+", help="sample lists (default: all)")
    spatial = ap.add_mutually_exclusive_group()
    spatial.add_argument(
        "--biomes", nargs="+", help="e.g. amazonia cerrado (download_shapefile.py)"
    )
    spatial.add_argument("--brazil", action="store_true", help="Brazil bounding box")
    spatial.add_argument(
        "--bbox", type=float, nargs=4, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX")
    )
    ap.add_argument("--dry-run", action="store_true", help="download: print ROI count and size")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sample", type=int, default=500, help="rasters opened by verify")
    args = ap.parse_args()
    root = args.dir.expanduser().resolve()
    lists = [p.expanduser().resolve() for p in args.from_json] if args.from_json else None

    if args.action == "download":
        download_metadata(root)
    names = [biomes.normalize_name(b) for b in args.biomes] if args.biomes else None
    bbox = BRAZIL_BBOX if args.brazil else tuple(args.bbox) if args.bbox else None
    rois = select_rois(root, lists, names, bbox)
    if args.dry_run:
        gb = len(rois) * AVG_MB_PER_ROI / 1024
        print(f"[dry-run] {len(rois):,} ROIs ~ {gb:,.0f} GB at ~{AVG_MB_PER_ROI} MB/ROI")
        return

    failed = {}
    if args.action == "download":
        failed = download(root, rois, args.workers)
    elif args.action == "prepare":
        failed = compact(root, args.workers)
    ok = verify(root, rois, lists, args.sample)  # after a partial failure too: the report lists it
    raise SystemExit(0 if ok and not failed else 1)


if __name__ == "__main__":
    main()
