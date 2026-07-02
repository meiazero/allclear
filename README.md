# AllClear (NeurIPS Datasets & Benchmarks Track)

[Hangyu Zhou](https://zhou-hangyu.github.io/), [Chia-Hsiang Kao](https://iandrover.github.io), [Cheng Perng Phoo](https://cpphoo.github.io), [Utkarsh Mall](https://www.cs.columbia.edu/~utkarshm/), [Bharath Hariharan](https://www.cs.cornell.edu/~bharathh/), [Kavita Bala](http://www.cs.cornell.edu/~kb/)

[![arXiv](https://img.shields.io/badge/arXiv-AllClear-red)](https://arxiv.org/abs/2410.23891)
[![Project](https://img.shields.io/badge/project-AllClear-blue)](https://allclear.cs.cornell.edu)

`AllClear` is a comprehensive dataset/benchmark for cloud detection and removal.

![Geographical distribution of AllClear](images/allclear.svg)

## Setup

```bash
# Clone the repository
git clone <this-repo>
cd allclear

# Install dependencies (requires uv — https://docs.astral.sh/uv)
uv sync
```

> `uv sync` installs everything for both the **download** pipeline and **loading
> the data** (`geopandas`, `requests`, `tqdm`, `rasterio`, and a CPU build of
> `torch`); `numpy` comes in transitively. Only `requests`/`tqdm` are actually
> exercised by the download itself. For GPU work (running the benchmark on CUDA),
> swap in a CUDA `torch` build.

## Dataset Download

The download is split into independent steps. Step 1 (metadata) is required
before step 2. ROI archives are extracted under `./data/`; already-present ROIs
are skipped.

```bash
# Step 1 — metadata (required first, ~few MB)
uv run python download.py --metadata-only

# Step 2 — ROI images (the full dataset, ~4 TB)
uv run python download.py --data-only

# Or run both at once
uv run python download.py
```

Optional filters (combine with `--data-only`):

```bash
# Only ROIs referenced by a given dataset JSON
uv run python download.py --data-only \
    --from-json metadata/datasets/train_tx3_s2-s1_10pct.json

# Only ROIs within a bounding box (LAT_MIN LON_MIN LAT_MAX LON_MAX)
uv run python download.py --data-only --bbox <lat_min> <lon_min> <lat_max> <lon_max>

# Resolve the ROI list and print a size estimate without downloading anything
uv run python download.py --data-only --dry-run
```

## Metadata structure

```
metadata/
├── data/
│   ├── dw_metadata.csv
│   ├── landsat8_metadata.csv
│   ├── landsat9_metadata.csv
│   ├── s1_metadata.csv
│   └── s2_metadata.csv
├── datasets/
│   ├── test_tx3_s2-s1_100pct.json
│   ├── test_tx3_s2-s1_100pct_1proi.json
│   ├── train_tx3_s2-s1_100pct.json
│   ├── train_tx12_s2-s1_100pct.json
│   └── ...
└── rois/
    ├── rois_metadata.csv
    ├── test_rois_3k.txt
    ├── train_rois_19k.txt
    └── val_rois_1k.txt
```

### Dataset JSON naming convention

`{split}_{sequence_length}_{sensors}_{pct_data}[_1proi].json`

| Field | Values |
|---|---|
| `split` | `train`, `val`, `test` |
| `sequence_length` | `tx3` (3 frames), `tx12` (12 frames) |
| `sensors` | `s2-s1`, `s2-s1-landsat`, `s2` (S2-only, derived — see below) |
| `pct_data` | `100pct`, `10pct`, `3.4pct`, `1pct` |
| `1proi` | single-patch-per-ROI lightweight subset |

Runtime tokens (not in file names): `s2p` (seq2point, predict one clear target
frame) / `s2s` (seq2seq) = the loader `target_mode`; `tx` = input sequence
length; `stp` = spatio-temporal-patch, the only supported loader `format`.

### Sentinel-2-only subsets

The shipped JSONs always bundle S1 (and sometimes Landsat). For an **S2-only**
experiment, derive stripped copies with `make_s2_only.py`. It empties every
non-S2 modality (`s1`, `landsat8`, `landsat9`) per sample, keeps `s2_toa` /
`target` / `roi`, and rewrites the `sensors` tag to `s2`:

```bash
uv run python make_s2_only.py \
    metadata/datasets/train_tx3_s2-s1_100pct.json \
    metadata/datasets/test_tx3_s2-s1_100pct.json \
    metadata/datasets/val_tx3_s2-s1-landsat_100pct.json
# → train_tx3_s2_100pct.json  test_tx3_s2_100pct.json  val_tx3_s2_100pct.json
```

The loader treats an empty modality list like an absent one (≈40% of samples
already ship with empty `s1`), so the output trains/vals/tests directly. Like
all of `metadata/`, the derived JSONs are **not versioned** — regenerate them
after downloading metadata. Note: `val` only ships as the `s2-s1-landsat`
variant, so derive it from that file.

## Data dictionary

### Sensors / auxiliary layers

| Key | Source (GEE collection) | Meaning |
|---|---|---|
| `s2_toa` | `COPERNICUS/S2_HARMONIZED` | Sentinel-2 L1C top-of-atmosphere reflectance (main sensor) |
| `s1` | `COPERNICUS/S1_GRD` | Sentinel-1 C-band SAR (VV, VH), dB |
| `landsat8` / `landsat9` | `LANDSAT/LC08│LC09/C02/T1_TOA` | Landsat 8/9 TOA (merged into one input stream by the loader) |
| `dw` | `GOOGLE/DYNAMICWORLD/V1` | Dynamic World land-cover `label` band |
| `cld_shdw` | derived (s2cloudless + dark-pixel projection) | per-pixel cloud & shadow masks |

### Bands (1-indexed, matching `channels` in `dataset.py`)

| Sensor | Bands |
|---|---|
| `s2_toa` (13) | 1–13 = B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B10, B11, B12 |
| `s1` (2) | 1 = VV, 2 = VH |
| `landsat8`/`landsat9` (11) | 1–11 = B1…B11 (TOA) |
| `dw` (1) | 1 = Dynamic World class id `0=water 1=trees 2=grass 3=flooded-veg 4=crops 5=shrub/scrub 6=built 7=bare 8=snow/ice` |
| `cld_shdw` (5) | 1 = s2cloudless probability, 2 = `clouds_30` (prob>30 binary cloud mask), 3–5 = `shadows_thres_{20,25,30}` (dark-pixel shadow masks) |

The loader uses `cld_shdw` channels **`[2, 5]`** = the binary cloud mask
(`clouds_30`) + the strictest shadow mask (`shadows_thres_30`); channels 1, 3, 4
(raw probability and looser shadow thresholds) are unused.

### Preprocessing (`AllClearDataset.preprocess`)

| Sensor | Transform | Rationale |
|---|---|---|
| `s2_toa`, `landsat8/9` | `clip(0, 10000) / 10000`; `NaN→0` | S2/Landsat reflectance is scaled ×10⁴ → maps to `[0, 1]` |
| `s1` (default) | floor at −40 dB; VV `(x+25)/25`, VH `(x+32.5)/32.5`; `NaN→−1` | SAR dB VV∈[−25,0], VH∈[−32.5,0] → `[0, 1]`; −40 dB noise floor |
| `s1` (`uncrtaints` mode) | `clip(−25, 0)` then rescale to `[0, 1]` | matches UnCRtainTS baseline convention |
| `cld_shdw` | `NaN→1` | missing mask ⇒ treated as cloudy (conservative) |
| `dw` | none | class ids passed through |

## Dataset JSON schema

Each dataset JSON maps a sample id to a dict. Paths are absolute to the authors'
cluster (see *Loading the data* below for how they are resolved locally):

```jsonc
{
  "roi171977_2022-08-05_2022-08-30": {
    "roi":    ["roi171977", [-13.40, -60.89]],          // [roi_id, [lat, lon]]
    "s2_toa": [["2022-08-05 14:26:30", "/…/roi171977_s2_toa_2022_8_5_median.tif"], …],
    "s1":     [["…", "/…/roi171977_s1_….tif"], …],       // optional aux sensor(s)
    "target": [["2022-08-15 14:26:32", "/…/roi171977_s2_toa_2022_8_15_median.tif"]]
  }
}
```

`cld_shdw` and `dw` files are **not** listed — the loader derives their paths by
replacing `s2_toa` with `cld_shdw`/`dw` in the tile path. `target` is present for
`s2p` (seq2point); `s2s` (seq2seq) samples reuse the input frames as targets.

## Loading the data

The tile paths inside the JSONs are absolute to the authors' cluster
(`/scratch/allclear/dataset_v3/dataset_30k_v4/roiXXXX/…`), but `download.py`
extracts ROI archives to `./data/roiXXXX/…`. The loader rebases them
automatically via the `data_root` argument (default `"data"`):

```python
from allclear.dataset import AllClearDataset
ds = AllClearDataset(dataset, selected_rois="all", data_root="data")
```

Resolution order per file: (1) the JSON path as-is (original cluster, or you
passed a local path), (2) rebased onto `data_root` by the `roiXXXX/…` tail,
(3) the legacy Cornell `/share/hariharan/…` layout. The benchmark exposes this
as `--data-root` (default `data`).

## Benchmark

Run a baseline through `allclear/benchmark.py`; point `--data-root` at your local
extraction directory and `--dataset-fpath` at a dataset JSON:

```bash
uv run python -m allclear.benchmark \
    --model-name uncrtaints --device cuda \
    --dataset-fpath metadata/datasets/test_tx3_s2-s1_100pct.json \
    --data-root data
```

## Notes

* Images are stored as [Cloud Optimized GeoTIFF (COG)](http://cogeo.org/), 256×256 pixels at 10 m resolution.
* Raw data may contain NaN values near tile boundaries due to map projection; the dataset loader center-crops on the fly.

## License

This project is licensed under the [MIT License](LICENSE).
