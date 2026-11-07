"""Keeps data out of git (guide P0-30: "data never committed to git").

It looks at every file git tracks and refuses anything under ml/ that is not on a short list of plain text kinds, anything
that looks like a picture, video, sound, model weights, an archive or a database, and anything in a folder named like a place
where footage or datasets are kept. It is the last line of defence; .gitignore is the first.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath
from typing import Callable

ALLOWED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".json", ".cfg", ".ini", ".lock", ".dvc"}
ALLOWED_NAMES = {".gitignore", ".gitattributes", ".dvcignore", ".gitkeep", "config", "dvc.lock", "dvc.yaml"}
BLOCKED_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
    ".wav", ".mp3", ".flac", ".m4a", ".ogg",
    ".npy", ".npz", ".pt", ".pth", ".onnx", ".tflite", ".mlmodel", ".h5", ".hdf5", ".pkl", ".pickle", ".joblib", ".safetensors",
    ".parquet", ".feather", ".arrow", ".csv", ".tsv",
    ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3",
}
BLOCKED_FOLDERS = {"footage", "datasets", "mlruns", "mlflow", "recordings"}
# Text files are small. A big one is probably data in disguise (a long JSON, a pasted table).
MAX_TEXT_BYTES = {".json": 64 * 1024, ".md": 200 * 1024}
MAX_ANY_BYTES = 256 * 1024
# Folders where the strict list applies: all of ml/, and any footage folder anywhere.
STRICT_ROOTS = ("ml/",)


def violations(paths: list[str], size_of: Callable[[str], int]) -> list[str]:
    """Plain-language reasons why tracked files are not allowed. An empty list means all is well."""
    problems: list[str] = []
    for path in paths:
        parts = PurePosixPath(path)
        suffix = parts.suffix.lower()
        in_ml = any(path.startswith(root) for root in STRICT_ROOTS)
        folders = {part.lower() for part in parts.parts[:-1]}

        bad_folder = folders & BLOCKED_FOLDERS
        if bad_folder:
            problems.append(f"{path}: it is inside a '{sorted(bad_folder)[0]}' folder, where data and footage must never be committed")
            continue
        if suffix in BLOCKED_SUFFIXES and (in_ml or "demo-call/" in path):
            problems.append(f"{path}: a {suffix} file looks like data (pictures, video, sound, arrays, model weights, tables or archives are never committed)")
            continue
        if in_ml:
            if parts.name not in ALLOWED_NAMES and suffix not in ALLOWED_SUFFIXES:
                problems.append(f"{path}: not a kind of file the ml/ folder may hold in git (allowed: plain text such as .py .md .yaml .json)")
                continue
            size = size_of(path)
            limit = MAX_TEXT_BYTES.get(suffix, MAX_ANY_BYTES)
            if size > limit:
                problems.append(f"{path}: {size} bytes is too big for a text file here (limit {limit}); it may be data in disguise")
    return problems


def tracked_files() -> tuple[str, list[str]]:
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    return root, [p for p in listing.split("\0") if p]


def main() -> int:
    import os

    root, paths = tracked_files()
    problems = violations(paths, lambda p: os.path.getsize(os.path.join(root, p)) if os.path.exists(os.path.join(root, p)) else 0)
    if problems:
        print("Data or footage may be about to be committed:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nRemove these from git (git rm --cached <file>), keep them out with .gitignore, and use DVC for data.", file=sys.stderr)
        return 1
    print(f"ok: {len(paths)} tracked files, no data or footage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
