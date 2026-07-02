#!/bin/bash
# Pack a minimal AllClear subset for upload to a remote pod (RunPod, vast.ai, etc).
#
# What gets packed:
#   - Selected split JSONs from metadata/datasets/ (default: *_ama-cer-pan.json)
#   - metadata/rois/ (ROI lists + rois_metadata.csv)
#   - metadata/shapefiles/ (only if --with-shapefiles)
#   - allclear/ Python package + download.py + pyproject.toml
#   - scripts/hydrate_pod.sh
#
# What is NOT packed (download on the pod from Cornell instead):
#   - metadata/data/*.csv (1.9 GB of global indexes — not needed for eval)
#   - tiff imagery (use scripts/hydrate_pod.sh on the pod)
#
# Usage:
#   bash scripts/pack_runpod_subset.sh                       # default: ama-cer-pan splits, no shapefiles
#   bash scripts/pack_runpod_subset.sh --with-shapefiles     # +52 MB, needed for --biomes filter
#   PATTERN='val_tx3_*_ama-cer-pan.json' bash scripts/pack_runpod_subset.sh
#   OUT_DIR=/tmp/packs bash scripts/pack_runpod_subset.sh
#
# Env vars (all optional):
#   REPO_DIR  allclear repo root         (default: parent of this script)
#   OUT_DIR   where archive is written   (default: $REPO_DIR/archives)
#   PATTERN   glob for split JSONs       (default: *_ama-cer-pan.json)
#
# Output:
#   $OUT_DIR/allclear_runpod_<UTCSTAMP>.tar.gz
#   $OUT_DIR/allclear_runpod_<UTCSTAMP>.sha256

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OUT_DIR="${OUT_DIR:-$REPO_DIR/archives}"
PATTERN="${PATTERN:-*_ama-cer-pan.json}"

WITH_SHAPEFILES=0
for arg in "$@"; do
    case "$arg" in
        --with-shapefiles) WITH_SHAPEFILES=1 ;;
        -h|--help)
            sed -n '2,28p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

cd "$REPO_DIR"

# Resolve splits matching the pattern
shopt -s nullglob
SPLITS=( metadata/datasets/$PATTERN )
shopt -u nullglob
if (( ${#SPLITS[@]} == 0 )); then
    echo "ERROR: no splits matched pattern: metadata/datasets/$PATTERN" >&2
    exit 1
fi

# Files always included
INCLUDE=(
    "${SPLITS[@]}"
    metadata/rois
    allclear
    dataset_construction
    download.py
    download_shapefile.py
    pyproject.toml
    setup.py
    .python-version
    scripts/hydrate_pod.sh
)

# Optional shapefiles for --biomes
if (( WITH_SHAPEFILES == 1 )); then
    INCLUDE+=( metadata/shapefiles )
fi

# Verify all paths exist
MISSING=()
for p in "${INCLUDE[@]}"; do
    [[ -e "$p" ]] || MISSING+=("$p")
done
if (( ${#MISSING[@]} > 0 )); then
    echo "ERROR: required paths missing:" >&2
    printf '  - %s\n' "${MISSING[@]}" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="$OUT_DIR/allclear_runpod_${STAMP}.tar.gz"
MANIFEST="$OUT_DIR/allclear_runpod_${STAMP}.sha256"

echo "=== Packing AllClear subset ==="
echo "  repo:    $REPO_DIR"
echo "  pattern: $PATTERN  (${#SPLITS[@]} split(s) matched)"
echo "  shapes:  $( ((WITH_SHAPEFILES)) && echo yes || echo no )"
for s in "${SPLITS[@]}"; do
    printf '  + %-70s %s\n' "$s" "$(du -h "$s" | cut -f1)"
done

# Exclude noise: pycache, vcs, egg-info
tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='*.egg-info' \
    -czf "$ARCHIVE" "${INCLUDE[@]}"

# Manifest
{
    echo "# allclear runpod subset"
    echo "# generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# host:      $(hostname)"
    echo "# repo:      $REPO_DIR"
    echo "# pattern:   $PATTERN"
    echo "# shapes:    $( ((WITH_SHAPEFILES)) && echo yes || echo no )"
    echo "# archive:   $(basename "$ARCHIVE")"
    echo
    echo "# splits included:"
    printf '#   %s\n' "${SPLITS[@]}"
    echo
    echo "# sha256 of archive:"
    (cd "$OUT_DIR" && sha256sum "$(basename "$ARCHIVE")")
} > "$MANIFEST"

ARCHIVE_SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo
echo "=== Done ==="
echo "  archive : $ARCHIVE   ($ARCHIVE_SIZE)"
echo "  manifest: $MANIFEST"
echo
echo "Next steps on local:"
echo "  # Upload to pod (replace POD_HOST):"
echo "  runpodctl send $ARCHIVE"
echo "  # or:"
echo "  rsync -avP $ARCHIVE root@POD_HOST:/workspace/"
echo
echo "On the pod:"
echo "  tar -xzf $(basename "$ARCHIVE") -C /workspace/allclear"
echo "  cd /workspace/allclear"
echo "  bash scripts/hydrate_pod.sh --biomes amazonia cerrado pantanal"
