#!/bin/bash
# Hydrate the AllClear dataset on a remote pod after extracting the subset tarball.
#
# Assumes you ran scripts/pack_runpod_subset.sh on local, uploaded the tar.gz,
# and extracted it to the pod's working directory (which must contain
# download.py, allclear/, metadata/, scripts/, pyproject.toml, ...).
#
# What this does:
#   1. Verifies metadata/ contents (splits, rois)
#   2. Installs Python deps via uv
#   3. Downloads ROI tiffs from Cornell with the provided filter
#      (default: --biomes amazonia cerrado pantanal)
#   4. Reports total disk usage when done
#
# Usage (run from extracted repo root on the pod):
#   bash scripts/hydrate_pod.sh                                # default biomes filter
#   bash scripts/hydrate_pod.sh --biomes amazonia              # single biome
#   bash scripts/hydrate_pod.sh --brazil                       # bbox approximation
#   bash scripts/hydrate_pod.sh --bbox -33.75 -73.99 5.27 -28.85
#   CPUS=16 bash scripts/hydrate_pod.sh
#
# Env vars (all optional):
#   CPUS       parallelism for downloads             (default: nproc)
#   SKIP_DEPS  set to 1 to skip uv install           (default: 0)

set -euo pipefail

CPUS="${CPUS:-$(nproc)}"
SKIP_DEPS="${SKIP_DEPS:-0}"

# Default download.py args if user passes none
if (( $# == 0 )); then
    set -- --biomes amazonia cerrado pantanal
fi

# Sanity: must be at allclear repo root
for required in download.py allclear pyproject.toml metadata/rois/rois_metadata.csv; do
    if [[ ! -e "$required" ]]; then
        echo "ERROR: '$required' not found. Run this from the extracted repo root." >&2
        exit 1
    fi
done

# Need shapefiles for --biomes filter
NEEDS_SHAPES=0
for arg in "$@"; do
    if [[ "$arg" == "--biomes" ]]; then NEEDS_SHAPES=1; fi
done
if (( NEEDS_SHAPES == 1 )) && [[ ! -f metadata/shapefiles/biomas_wgs84.gpkg ]]; then
    echo "WARN: --biomes requires metadata/shapefiles/biomas_wgs84.gpkg" >&2
    echo "      Re-pack with --with-shapefiles, or run download_shapefile.py here." >&2
    echo "      Attempting download_shapefile.py..."
    uv run python download_shapefile.py
fi

# Install deps
if (( SKIP_DEPS == 0 )); then
    echo "=== Installing deps (uv sync) ==="
    if ! command -v uv >/dev/null 2>&1; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    fi
    uv sync
fi

echo
echo "=== Downloading ROI tiffs ==="
echo "  filter: $*"
echo "  cpus:   $CPUS"
echo
uv run python download.py --data-only --cpus "$CPUS" "$@"

echo
echo "=== Disk usage ==="
du -sh data/ metadata/ 2>/dev/null || du -sh data/
echo
echo "ROI count under data/: $(find data -maxdepth 1 -mindepth 1 -type d | wc -l)"
