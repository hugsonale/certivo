"""Proves that the baseline experiment reproduces from a clean checkout (guide step P0-30).

It clones the repository (what is COMMITTED, not what is on your disk) into a temporary folder, builds a brand-new Python
environment there from the pinned requirements, runs `dvc repro --force` (every stage, none skipped), and then checks that every file that is committed and is
produced by the pipeline (dvc.lock, the metrics file, the model card) came out byte for byte the same. Data and models are
never committed, so they are rebuilt from scratch.

Run from anywhere in the repository:   python ml/scripts/clean_checkout_repro.py
Add --keep to keep the temporary folder, --tests to also run the unit tests there.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"  $ {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=quiet)
    if result.returncode != 0:
        if quiet:
            print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
        raise SystemExit(f"\nFAILED: {' '.join(command)} (exit {result.returncode})")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--tests", action="store_true")
    args = parser.parse_args()

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip())
    tracked = subprocess.run(["git", "ls-files", "--", "ml/dvc.yaml"], cwd=root, capture_output=True, text=True).stdout.strip()
    if not tracked:
        print(
            "STOP: the ML workspace is not committed yet, so a clean checkout would not contain it.\n"
            "This check tests only what is COMMITTED. Commit first, then run it again:\n\n"
            "    git add ml .github/workflows/ml.yml docs/adr/0028-ml-workspace.md\n"
            '    git commit -m "feat(ml): P0-30 ML workspace"\n'
        )
        return 2
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "ml"], cwd=root, capture_output=True, text=True).stdout.strip()
    if dirty:
        print("NOTE: you have uncommitted changes under ml/. Only what is COMMITTED is tested here:\n" + dirty + "\n")

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from certivo_ml.environment import problems_with, summary  # noqa: E402

    print(f"Using {summary()}")
    problems = problems_with()
    if problems:
        print("STOP: this Python cannot run the pinned tools:\n  - " + "\n  - ".join(problems))
        return 2

    work = Path(tempfile.mkdtemp(prefix="certivo-repro-"))
    try:
        print(f"1. Clean checkout into {work}")
        checkout = work / "checkout"
        run(["git", "clone", "--quiet", str(root), str(checkout)], cwd=work)
        ml = checkout / "ml"
        if not (ml / "requirements.txt").exists():
            print("STOP: the clean checkout has no ml/requirements.txt. Is the workspace committed on THIS branch?")
            return 2

        print("2. A brand-new Python environment with the pinned tools")
        venv = work / "venv"
        run([sys.executable, "-m", "venv", str(venv)], cwd=work)
        bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        run([str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt", "-c", "constraints.txt"], cwd=ml, quiet=True)

        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CERTIVO_MLFLOW_DIR": str(work / "mlflow")}
        env.pop("PYTHONPATH", None)

        print("3. Run EVERY stage of the pipeline again (dvc repro --force), so nothing is skipped as 'unchanged'")
        run([str(python), "-m", "dvc", "repro", "--force"], cwd=ml, env=env)

        if args.tests:
            print("4. Run the unit tests")
            run([str(python), "-m", "pytest", "tests", "-q"], cwd=ml, env=env)

        print("\nChecking that every committed file the pipeline produces came out unchanged")
        changed = subprocess.run(["git", "status", "--porcelain"], cwd=checkout, capture_output=True, text=True).stdout.strip()
        if changed:
            print("FAIL: the clean checkout did NOT reproduce. These files differ from what is committed:\n" + changed)
            return 1
        produced = [p for p in ("ml/dvc.lock", "ml/metrics/baseline-synthetic-v0.json", "ml/model_cards/baseline-synthetic-v0.md") if (checkout / p).exists()]
        print("PASS: reproduced from a clean checkout. Unchanged: " + ", ".join(produced))
        print("      Rebuilt (never committed): data/synthetic-v0, models/baseline-synthetic-v0, and a new experiment record.")
        return 0
    finally:
        if args.keep:
            print(f"\nkept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
