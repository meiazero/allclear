"""
Downloads the official IBGE Brazil biomes shapefile (2019, 1:250,000 scale).

Source:
  IBGE - Instituto Brasileiro de Geografia e Estatística
  Biomas do Brasil - Escala 1:250.000 (2019)
  https://geoftp.ibge.gov.br/informacoes_ambientais/estudos_ambientais/biomas/vetores/

Output:
  metadata/shapefiles/biomas_wgs84.gpkg  — reprojected to WGS84 (EPSG:4326)
                                           with normalized biome name column

Cite as:
  IBGE (2019). Biomas do Brasil. Escala 1:250.000.
  Rio de Janeiro: Instituto Brasileiro de Geografia e Estatística.
  Available at: https://www.ibge.gov.br/geociencias/informacoes-ambientais/
  estudos-ambientais/15842-biomas.html
"""

import hashlib
import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from tqdm import tqdm

from biomes import normalize_name

IBGE_URL = (
    "https://geoftp.ibge.gov.br/informacoes_ambientais/estudos_ambientais/"
    "biomas/vetores/Biomas_250mil.zip"
)
DEST_DIR = Path("metadata/shapefiles")
ZIP_PATH = DEST_DIR / "Biomas_250mil.zip"
GPKG_PATH = DEST_DIR / "biomas_wgs84.gpkg"
HASH_PATH = DEST_DIR / ".sha256"
CHUNK_SIZE = 8192


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_zip():
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading IBGE biomes shapefile from:\n  {IBGE_URL}\n")
    with requests.get(IBGE_URL, stream=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        with open(ZIP_PATH, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc="Biomas_250mil.zip") as pbar:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))


def verify_or_record_hash():
    digest = sha256_file(ZIP_PATH)
    if HASH_PATH.exists():
        saved = HASH_PATH.read_text().strip()
        if digest != saved:
            raise RuntimeError(
                f"SHA256 mismatch!\n  expected: {saved}\n  got:      {digest}\n"
                "Delete the zip and re-run to force re-download."
            )
        print(f"SHA256 verified: {digest}")
    else:
        HASH_PATH.write_text(digest + "\n")
        print(f"\n{'='*60}")
        print(f"SHA256 (record this for your paper):\n  {digest}")
        print(f"{'='*60}\n")


def extract_and_reproject():
    extract_dir = DEST_DIR / "raw"
    extract_dir.mkdir(exist_ok=True)

    print("Extracting zip...")
    with zipfile.ZipFile(ZIP_PATH) as zf:
        zf.extractall(extract_dir)

    # Find the .shp file
    shp_files = list(extract_dir.rglob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No .shp found in {extract_dir}")
    shp_path = shp_files[0]
    print(f"Found shapefile: {shp_path.name}")

    print("Loading and reprojecting to WGS84 (EPSG:4326)...")
    gdf = gpd.read_file(shp_path)
    gdf = gdf.to_crs(epsg=4326)

    # Detect biome name column (IBGE uses NomeBioma or Bioma)
    name_col = None
    for candidate in ["NomeBioma", "Bioma", "BIOMA", "NOME_BIOMA", "nome_bioma"]:
        if candidate in gdf.columns:
            name_col = candidate
            break
    if name_col is None:
        print(f"Columns found: {list(gdf.columns)}")
        raise KeyError("Could not detect biome name column. Check columns above.")

    gdf["biome"] = gdf[name_col].apply(normalize_name)
    gdf = gdf[["biome", "geometry"]].copy()

    gdf.to_file(GPKG_PATH, driver="GPKG")
    print(f"Saved: {GPKG_PATH}")
    return gdf


def main():
    if GPKG_PATH.exists() and HASH_PATH.exists():
        print(f"Shapefile already processed: {GPKG_PATH}")
        print("Loading to show available biomes...")
        gdf = gpd.read_file(GPKG_PATH)
    else:
        if not ZIP_PATH.exists():
            download_zip()
        else:
            print(f"Zip already exists: {ZIP_PATH}")

        verify_or_record_hash()
        gdf = extract_and_reproject()

    biomes = sorted(gdf["biome"].unique())
    print(f"\nAvailable biomes ({len(biomes)}):")
    for b in biomes:
        print(f"  {b}")
    print(f"\nUse these names with --biomes in download.py and filter_datasets.py")


if __name__ == "__main__":
    main()
