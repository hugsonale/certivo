from __future__ import annotations

from certivo_ml.guard import violations


def check(paths, size=100):
    return violations(paths, lambda _p: size)


def test_ordinary_files_are_fine():
    assert check(["ml/certivo_ml/baseline.py", "ml/params.yaml", "ml/dvc.lock", "ml/dvc.yaml", "ml/.gitignore", "ml/.dvc/config", "ml/metrics/x.json", "ml/model_cards/x.md", "sdk-web/anything.png"]) == []


def test_pictures_video_sound_arrays_and_weights_in_ml_are_refused():
    for name in ("a.png", "a.JPG", "clip.mp4", "clip.webm", "voice.wav", "images.npy", "x.npz", "model.onnx", "w.pt", "w.safetensors", "t.parquet", "t.csv", "d.zip", "m.db", "x.pkl"):
        assert check([f"ml/data/{name}"]) != [], name


def test_unknown_kinds_of_file_in_ml_are_refused_even_if_they_look_harmless():
    assert check(["ml/notes.docx"]) != []
    assert check(["ml/binary_blob"]) != []


def test_footage_and_dataset_folders_are_refused_anywhere():
    for path in ("demo-call/footage/me.txt", "ml/datasets/a.txt", "foo/Footage/x.md", "ml/mlruns/1/meta.yaml", "ml/mlflow/store.txt"):
        assert check([path]) != [], path


def test_demo_call_media_is_refused():
    assert check(["demo-call/public/me.mp4"]) != []


def test_a_big_text_file_is_probably_data_in_disguise():
    assert check(["ml/something.json"], size=70_000) != []
    assert check(["ml/something.json"], size=60_000) == []
    assert check(["ml/notes.md"], size=300_000) != []
    assert check(["ml/script.py"], size=300_000) != []


def test_every_problem_names_the_file_and_says_why():
    [problem] = check(["ml/data/images.npy"])
    assert "ml/data/images.npy" in problem and "never committed" in problem
