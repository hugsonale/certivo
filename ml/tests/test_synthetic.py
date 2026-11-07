from __future__ import annotations

import numpy as np

from certivo_ml import synthetic, write_text
from certivo_ml.params import load_params


def config(**changes):
    base = dict(load_params()["synthetic"])
    base.update(changes)
    return base


def test_same_settings_give_exactly_the_same_data():
    a = synthetic.generate(config())
    b = synthetic.generate(config())
    for name in a:
        assert np.array_equal(a[name], b[name]), name


def test_a_different_seed_gives_different_data():
    a = synthetic.generate(config())
    b = synthetic.generate(config(seed=1))
    assert not np.array_equal(a["images"], b["images"])


def test_files_are_identical_byte_for_byte_when_written_twice(tmp_path):
    arrays = synthetic.generate(config(samples=200))
    one = synthetic.write_dataset(arrays, tmp_path / "one", config(samples=200))
    two = synthetic.write_dataset(arrays, tmp_path / "two", config(samples=200))
    assert one["files_sha256"] == two["files_sha256"]
    assert (tmp_path / "one" / "MANIFEST.json").read_bytes() == (tmp_path / "two" / "MANIFEST.json").read_bytes()
    assert synthetic.data_sha256(tmp_path / "one") == synthetic.data_sha256(tmp_path / "two")


def test_the_dataset_fingerprint_changes_when_one_pixel_changes(tmp_path):
    arrays = synthetic.generate(config(samples=100))
    synthetic.write_dataset(arrays, tmp_path / "a", config(samples=100))
    arrays["images"][0, 0, 0] ^= 1
    synthetic.write_dataset(arrays, tmp_path / "b", config(samples=100))
    assert synthetic.data_sha256(tmp_path / "a") != synthetic.data_sha256(tmp_path / "b")


def test_labels_are_balanced_and_splits_are_complete_and_separate():
    data = synthetic.generate(config())
    assert int(data["labels"].sum()) == 1200
    counts = [int((data["split"] == s).sum()) for s in (0, 1, 2)]
    assert counts == [1440, 480, 480]
    assert sum(counts) == len(data["labels"])


def test_the_shape_and_type_of_every_array():
    data = synthetic.generate(config(samples=50))
    assert data["images"].shape == (50, 16, 16) and data["images"].dtype == np.uint8
    assert set(np.unique(data["groups"])) <= {0, 1, 2}


def test_noise_really_grows_with_the_group():
    data = synthetic.generate(config(samples=3000))
    # compare pictures without the stamp to the plain gradient: what is left is noise
    gradient = np.tile(np.linspace(60, 120, 16), (16, 1))
    spread = []
    for g in (0, 1, 2):
        mask = (data["groups"] == g) & (data["labels"] == 0)
        spread.append(float((data["images"][mask].astype(float) - gradient).std()))
    assert spread[0] < spread[1] < spread[2]


def test_the_stamp_is_what_separates_the_labels():
    data = synthetic.generate(config(samples=3000, group_noise=[1, 1, 1]))
    centre = data["images"][:, 5:11, 5:11].astype(float).mean(axis=(1, 2))
    assert centre[data["labels"] == 1].mean() - centre[data["labels"] == 0].mean() > 6


def test_text_files_always_get_plain_line_endings(tmp_path):
    write_text(tmp_path / "x.txt", "a\nb\n")
    assert (tmp_path / "x.txt").read_bytes() == b"a\nb\n"
