"""AllClear download, compaction and verify against the local HTTP server."""

import json
from pathlib import Path

import pytest
from conftest import FILES, make_tar, make_tif

import common
import download

S2 = "roi1/2022_1/s2_toa/roi1_s2_toa_2022_1_1_median.tif"
TARGET = "roi1/2022_1/s2_toa/roi1_s2_toa_2022_1_6_median.tif"


def test_download_compact_verify_and_detect_a_missing_file(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = {
        "roi": ["roi1", [0, 0]],
        "s2_toa": [["2022-01-01", S2]],
        "target": [["2022-01-06", TARGET]],
    }
    FILES["/metadata.tar.gz"] = make_tar(
        {
            "metadata/datasets/test_x.json": json.dumps({"k": sample}).encode(),
            "metadata/rois/test_rois_3k.txt": b"roi1\nroi2\n",
            "metadata/rois/train_rois_19k.txt": b"",
            "metadata/rois/val_rois_1k.txt": b"",
        }
    )
    FILES["/data/roi1.tar.gz"] = make_tar(
        {
            S2: make_tif(13),
            TARGET: make_tif(13),
            S2.replace("s2_toa", "cld_shdw"): make_tif(5),
            TARGET.replace("s2_toa", "cld_shdw"): make_tif(5),
        }
    )
    monkeypatch.setattr(download, "URL", server)
    download.download_metadata(tmp_path)
    lists = [tmp_path / "metadata/datasets/test_x.json"]
    rois = download.select_rois(tmp_path, lists)
    assert rois == {"roi1"}  # roi2 is in no sample list
    assert download.download(tmp_path, rois, workers=2) == {}
    assert download.compact(tmp_path, workers=1) == {}
    assert download.verify(tmp_path, rois, sample=10)

    (tmp_path / "data" / S2.replace("s2_toa", "cld_shdw")).unlink()
    assert not download.verify(tmp_path, rois, sample=10)
    report = json.loads((tmp_path / "verify_report.json").read_text())
    assert report["missing_rois"] == ["roi1"] and report["n_missing"] == 1


def test_verify_flags_a_raster_with_the_wrong_band_count(tmp_path: Path) -> None:
    path = tmp_path / "roi1/2022_1/s2_toa/x.tif"
    path.parent.mkdir(parents=True)
    path.write_bytes(make_tif(12))
    assert "13" in common.check_raster(path, download.BANDS["s2_toa"])
