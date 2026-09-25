"""Shared biome helpers: name normalization + point-in-polygon ROI selection.

Split out so download.py can import normalize_name (no geopandas) while
load_biome_rois pulls geopandas in lazily, only when --biomes is actually used.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

GPKG = "shapefiles/biomas_wgs84.gpkg"  # under the metadata directory
ROIS_CSV = "rois/rois_metadata.csv"


def normalize_name(name: str) -> str:
    """Remove accents, lowercase, replace spaces/hyphens with underscores.
    e.g. 'Amazônia' -> 'amazonia', 'Mata Atlântica' -> 'mata_atlantica'
    """
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")


def load_biome_rois(biomes: list[str], metadata: Path) -> set[str]:
    """Point-in-polygon join: ROI ids (e.g. 'roi245610') whose centroid falls
    inside one of `biomes`. Imports geopandas lazily so non-biome paths stay light."""
    try:
        import geopandas as gpd
        import pandas as pd
    except ImportError as e:
        raise ImportError("geopandas required for --biomes. Run: uv add geopandas") from e

    gpkg_path, rois_csv = metadata / GPKG, metadata / ROIS_CSV
    if not gpkg_path.exists():
        raise FileNotFoundError(f"{gpkg_path} not found. Run download_shapefile.py first.")
    if not rois_csv.exists():
        raise FileNotFoundError(f"{rois_csv} not found. Run download.py download first.")

    print(f"Loading biomes shapefile for: {biomes}")
    biomes_gdf = gpd.read_file(gpkg_path)
    selected = biomes_gdf[biomes_gdf["biome"].isin(biomes)]
    if selected.empty:
        available = sorted(biomes_gdf["biome"].unique())
        raise ValueError(f"No biomes matched {biomes}.\nAvailable: {available}")

    rois_df = pd.read_csv(rois_csv)
    rois_gdf = gpd.GeoDataFrame(
        rois_df,
        geometry=gpd.points_from_xy(rois_df.longitude, rois_df.latitude),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(rois_gdf, selected[["biome", "geometry"]], how="inner", predicate="within")

    for biome in sorted(biomes):
        count = joined[joined["biome"] == biome].shape[0]
        print(f"  {biome}: {count:,} ROIs")
    return set("roi" + joined["roi_id"].astype(str))
