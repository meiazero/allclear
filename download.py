import csv
import unicodedata
import requests
from pathlib import Path
import multiprocessing as mp
from tqdm import tqdm
import time
import argparse

# Brazil bounding box
BRAZIL_BBOX = (-33.75, -73.99, 5.27, -28.85)  # (lat_min, lon_min, lat_max, lon_max)

GPKG_PATH = Path("metadata/shapefiles/biomas_wgs84.gpkg")
ROIS_CSV = Path("metadata/rois/rois_metadata.csv")


def normalize_name(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")

# Configuration
BASE_URL = "http://allclear.cs.cornell.edu/dataset/allclear"
CHUNK_SIZE = 8192
AVG_MB_PER_ROI = 184  # ponytail: measured median of sampled ROI archives; --dry-run estimate only

def download_file(url, dest_path, show_progress=True):
    """Download a file with progress bar and return success status"""
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 404:
            return False

        total_size = int(response.headers.get("content-length", 0))
        
        with open(dest_path, "wb") as f:
            if show_progress:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=dest_path.name) as pbar:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            else:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        if dest_path.exists():
            dest_path.unlink()
        return False

def verify_file(file_path):
    """Verify if file is complete by trying to open it"""
    try:
        if file_path.suffix == '.gz':
            import gzip
            with gzip.open(file_path, 'rb') as f:
                f.read(1)  # Try reading first byte
        return True
    except:
        return False

def download_metadata():
    """Download metadata files"""
    metadata_dir = Path("metadata")
    metadata_dir.mkdir(exist_ok=True)
    filename = "metadata.tar.gz"
    url = f"{BASE_URL}/{filename}"
    dest_path = metadata_dir / filename
    print(f"Downloading metadata from {url} to {dest_path}")
    success = download_file(url, dest_path)

    if success and verify_file(dest_path):
        # Extract the tar.gz file
        try:
            import tarfile
            import shutil

            with tarfile.open(dest_path, 'r:gz') as tar:
                tar.extractall(path=metadata_dir)

            nested_dir = metadata_dir / "metadata"
            if nested_dir.exists() and nested_dir.is_dir():
                for item in nested_dir.iterdir():
                    shutil.move(str(item), str(metadata_dir))
                nested_dir.rmdir()
            print(f"Successfully downloaded and extracted {filename}")
            # Remove the tar.gz file after extraction
            dest_path.unlink()
        except Exception as e:
            print(f"Error extracting {filename}: {e}")
            if dest_path.exists():
                dest_path.unlink()
    elif success:
        print(f"Downloaded {filename} but verification failed")
        dest_path.unlink()
    else:
        print(f"Skipping {filename} - not found on server")


def load_roi_list(bbox=None, biomes=None):
    """Load and combine all ROI IDs from metadata files, with optional filtering.

    Priority: biomes (shapefile) > bbox > none (all ROIs).

    Args:
        bbox:   (lat_min, lon_min, lat_max, lon_max) or None
        biomes: list of normalized biome names or None
    """
    metadata_dir = Path("metadata")
    roi_ids = set()

    for filename in ["test_rois_3k.txt", "train_rois_19k.txt", "val_rois_1k.txt"]:
        file_path = metadata_dir / "rois" / filename
        if not file_path.exists():
            print(f"Warning: {filename} not found")
            continue
        with open(file_path, 'r') as f:
            roi_ids.update(line.strip() for line in f if line.strip())

    if biomes:
        return _filter_by_biomes(roi_ids, biomes)

    if bbox:
        return _filter_by_bbox(roi_ids, bbox)

    return sorted(roi_ids)


def _filter_by_biomes(roi_ids: set, biomes: list) -> list:
    """Filter ROIs using the IBGE biomes shapefile (point-in-polygon)."""
    try:
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import Point
    except ImportError:
        raise ImportError("geopandas required for --biomes. Run: uv add geopandas")

    if not GPKG_PATH.exists():
        raise FileNotFoundError(
            f"{GPKG_PATH} not found. Run download_shapefile.py first."
        )
    if not ROIS_CSV.exists():
        raise FileNotFoundError(f"{ROIS_CSV} not found.")

    print(f"Loading biomes shapefile for: {biomes}")
    biomes_gdf = gpd.read_file(GPKG_PATH)
    selected = biomes_gdf[biomes_gdf["biome"].isin(biomes)]
    if selected.empty:
        available = sorted(biomes_gdf["biome"].unique())
        raise ValueError(f"No biomes matched {biomes}.\nAvailable: {available}")

    rois_df = pd.read_csv(ROIS_CSV)
    rois_gdf = gpd.GeoDataFrame(
        rois_df,
        geometry=[Point(float(r.longitude), float(r.latitude)) for r in rois_df.itertuples()],
        crs="EPSG:4326",
    )

    joined = gpd.sjoin(rois_gdf, selected[["biome", "geometry"]], how="inner", predicate="within")
    biome_roi_ids = set("roi" + str(rid) for rid in joined["roi_id"].astype(str))

    result = sorted(roi_ids & biome_roi_ids)
    for biome in sorted(biomes):
        count = joined[joined["biome"] == biome].shape[0]
        print(f"  {biome}: {count:,} ROIs")
    print(f"Biome filter: {len(result):,} ROIs (from {len(roi_ids):,} total)")
    return result


def _filter_by_bbox(roi_ids: set, bbox: tuple) -> list:
    """Filter ROIs using a lat/lon bounding box."""
    lat_min, lon_min, lat_max, lon_max = bbox
    if not ROIS_CSV.exists():
        print("Warning: rois_metadata.csv not found, skipping bbox filter")
        return sorted(roi_ids)

    with open(ROIS_CSV, newline='') as f:
        filtered = {
            f"roi{row['roi_id']}"
            for row in csv.DictReader(f)
            if lat_min <= float(row['latitude']) <= lat_max
            and lon_min <= float(row['longitude']) <= lon_max
        }

    result = sorted(roi_ids & filtered)
    print(f"Bbox filter: {len(result):,} ROIs (from {len(roi_ids):,} total)")
    return result

def rois_from_json(json_paths):
    """Set of ROI ids referenced by one or more dataset JSONs (sample['roi'][0])."""
    import json
    roi_ids = set()
    for p in json_paths:
        with open(p) as f:
            data = json.load(f)
        for v in data.values():
            r = v["roi"]
            roi_ids.add(r[0] if isinstance(r, list) else r)
    return roi_ids


def download_roi_worker(roi_batch):
    """Worker function for parallel ROI downloads"""
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    for roi_id in roi_batch:
        filename = f"{roi_id}.tar.gz"
        dest_path = data_dir / filename
        url = f"{BASE_URL}/data/{filename}"
        
        # Skip if already downloaded, verified, and extracted
        if (data_dir / roi_id).exists():
            continue
            
        # Remove if exists but invalid
        if dest_path.exists():
            dest_path.unlink()
            
        # Download file
        success = download_file(url, dest_path, show_progress=False)
        time.sleep(0.1)
        
        if success and verify_file(dest_path):
            # Extract the tar.gz file
            try:
                import tarfile
                with tarfile.open(dest_path, 'r:gz') as tar:
                    tar.extractall(path=data_dir)
                print(f"Successfully downloaded and extracted {filename}")
                # Remove the tar.gz file after extraction
                dest_path.unlink()
            except Exception as e:
                print(f"Error extracting {filename}: {e}")
                if dest_path.exists():
                    dest_path.unlink()
        elif success:
            print(f"Downloaded {filename} but verification failed")
            dest_path.unlink()
        else:
            print(f"Skipping {filename} - not found on server")

def main():
    parser = argparse.ArgumentParser(
        description="Download AllClear dataset.\n\n"
                    "Steps can be run independently:\n"
                    "  metadata only : --metadata-only\n"
                    "  images only   : --data-only  (metadata must already exist)\n"
                    "  both (default): omit both flags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Steps
    step = parser.add_mutually_exclusive_group()
    step.add_argument('--metadata-only', action='store_true',
                      help='Download and extract metadata only, then stop')
    step.add_argument('--data-only', action='store_true',
                      help='Skip metadata download, go straight to ROI images '
                           '(metadata must already exist in ./metadata/)')
    # Resources
    parser.add_argument('--cpus', type=int, default=8,
                        help='Number of CPU cores to use (default: 8)')
    # Spatial filters (mutually exclusive, biomes takes priority)
    spatial = parser.add_mutually_exclusive_group()
    spatial.add_argument('--biomes', nargs='+',
                         help='Download only ROIs within selected biomes '
                              '(requires download_shapefile.py first). '
                              'e.g. --biomes amazonia cerrado pantanal')
    spatial.add_argument('--brazil', action='store_true',
                         help='Download only ROIs within Brazil (bbox approximation)')
    spatial.add_argument('--bbox', type=float, nargs=4,
                         metavar=('LAT_MIN', 'LON_MIN', 'LAT_MAX', 'LON_MAX'),
                         help='Download only ROIs within bounding box')
    # Sample-driven filter: restrict to ROIs referenced by dataset JSON(s).
    parser.add_argument('--from-json', nargs='+', metavar='JSON',
                        help='Download only ROIs referenced by these dataset JSON(s), e.g. '
                             'metadata/datasets/train_tx3_s2-s1_10pct.json. Note: pct subsets '
                             'are sampled per-sequence, so 10%% of samples still spans ~72%% of '
                             'ROIs. Intersects with any spatial filter.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Resolve the ROI list, print count + estimated size, then exit '
                             '(downloads nothing).')
    args = parser.parse_args()

    n_cores = max(1, args.cpus - 1)

    # --- Step 1: metadata ---
    if not args.data_only:
        print("==> Step 1/2: Downloading metadata...")
        download_metadata()
    else:
        metadata_dir = Path("metadata")
        if not (metadata_dir / "rois" / "rois_metadata.csv").exists():
            parser.error("--data-only requires metadata to already exist. "
                         "Run without --data-only first, or use --metadata-only.")
        print("==> Step 1/2: Skipping metadata download (--data-only).")

    if args.metadata_only:
        print("\nMetadata download complete (--metadata-only).")
        roi_ids = load_roi_list()
        print(f"Available ROIs: {len(roi_ids):,} total")
        return

    # --- Step 2: ROI images ---
    # Resolve spatial filter
    biomes = None
    bbox = None
    if args.biomes:
        biomes = [normalize_name(b) for b in args.biomes]
        print(f"\nBiome filter: {biomes}")
    elif args.brazil:
        bbox = BRAZIL_BBOX
        print(f"\nBrazil bbox filter: {BRAZIL_BBOX}")
    elif args.bbox:
        bbox = tuple(args.bbox)
        print(f"\nBbox filter: {bbox}")

    print("\n==> Step 2/2: Loading ROI list...")
    roi_ids = load_roi_list(bbox=bbox, biomes=biomes)
    print(f"Found {len(roi_ids):,} unique ROI IDs")

    if args.from_json:
        json_rois = rois_from_json(args.from_json)
        roi_ids = sorted(set(roi_ids) & json_rois)
        print(f"JSON filter ({len(args.from_json)} file(s)): {len(json_rois):,} referenced "
              f"→ {len(roi_ids):,} to download")

    if args.dry_run:
        gb = len(roi_ids) * AVG_MB_PER_ROI / 1024
        print(f"\n[dry-run] {len(roi_ids):,} ROIs ≈ {gb:,.0f} GB ({gb / 1024:.2f} TB) "
              f"at ~{AVG_MB_PER_ROI} MB/ROI. Nothing downloaded.")
        return

    chunk_size = len(roi_ids) // n_cores + 1
    roi_chunks = [roi_ids[i:i + chunk_size] for i in range(0, len(roi_ids), chunk_size)]

    print(f"Downloading ROIs using {n_cores} processes...")
    with mp.Pool(n_cores) as pool:
        pool.map(download_roi_worker, roi_chunks)

    print("\nDownload completed!")

if __name__ == "__main__":
    main()