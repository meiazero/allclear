"""Shared biome helpers: name normalization + point-in-polygon ROI selection.

Split out so download.py can import normalize_name (no geopandas) while
load_biome_rois pulls geopandas in lazily, only when --biomes is actually used.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

GPKG_PATH = Path("metadata/shapefiles/biomas_wgs84.gpkg")
ROIS_CSV = Path("metadata/rois/rois_metadata.csv")


def normalize_name(name: str) -> str:
    """Remove accents, lowercase, replace spaces/hyphens with underscores.
    e.g. 'Amazônia' -> 'amazonia', 'Mata Atlântica' -> 'mata_atlantica'
    """
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    return ascii_str.lower().replace(" ", "_").replace("-", "_")


def load_biome_rois(biomes: list[str]) -> set[str]:
    """Point-in-polygon join: ROI ids (e.g. 'roi245610') whose centroid falls
    inside one of `biomes`. Imports geopandas lazily so non-biome paths stay light."""
    try:
        import geopandas as gpd
        import pandas as pd
    except ImportError:
        raise ImportError("geopandas required for --biomes. Run: uv add geopandas")

    if not GPKG_PATH.exists():
        raise FileNotFoundError(f"{GPKG_PATH} not found. Run download_shapefile.py first.")
    if not ROIS_CSV.exists():
        raise FileNotFoundError(f"{ROIS_CSV} not found. Run download.py (metadata step) first.")

    print(f"Loading biomes shapefile for: {biomes}")
    biomes_gdf = gpd.read_file(GPKG_PATH)
    selected = biomes_gdf[biomes_gdf["biome"].isin(biomes)]
    if selected.empty:
        available = sorted(biomes_gdf["biome"].unique())
        raise ValueError(f"No biomes matched {biomes}.\nAvailable: {available}")

    rois_df = pd.read_csv(ROIS_CSV)
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
