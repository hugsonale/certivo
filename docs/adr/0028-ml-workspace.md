# 0028. The ML workspace: DVC, MLflow, model cards and reproduction from a clean checkout (P0-30)

**Date:** 5 November 2026
**Status:** Proposed

## Context

Step P0-30 asks for an `ml/` folder with dataset versioning, experiment tracking, model cards and reproducible training scripts, with data never committed to git, and a baseline experiment that reproduces from a clean checkout.
The guide says to use the v1 documents' tools once known and otherwise DVC and MLflow. The v1 documents were never available to me, so this uses the fallback. Data licences are the biggest legal risk (D-07) and no dataset has been approved yet (P0-31), so the workspace is proven on synthetic data.

## Decision (proposed)

1. **DVC for the pipeline and the data.** `ml/dvc.yaml` has four stages (make data, train, evaluate, model card); `ml/dvc.lock` records the fingerprint of every input and output. DVC lives in `ml/` only (`dvc init --subdir`), with its analytics and update check switched off. Data and models are DVC outputs and are git-ignored. **No DVC remote is configured yet**: it depends on the cloud decision (D-06) and on real data existing.
2. **MLflow for experiment records**, in a local SQLite store under `ml/mlflow/` (never committed). Every run is tagged with the git commit, whether the working copy was changed, the data fingerprint, the tool versions and a standing note that the data is synthetic. No tracking server.
3. **One settings file** (`ml/params.yaml`) that DVC watches, so a change of setting shows in git and invalidates exactly the stages that use it.
4. **Model cards are generated from the metrics file**, never written by hand, and checked: required sections, no unfilled placeholder, no boasting phrase (state of the art, production-ready, human-level, guaranteed, best-in-class), a plain statement that synthetic data says nothing about real-world performance, and an explicit promotion status. Every rate carries a 95 percent (Wilson) interval. A card contains no date or commit id so it reproduces byte for byte.
5. **Data sheets** per dataset (`ml/datasheets/`), with a template, to be completed before a dataset is used (P0-31).
6. **Data never in git, enforced twice.** `ml/.gitignore` ignores data, models and records and every data-like file type. `ml/scripts/check_no_data.py` (run in CI) refuses any tracked file under `ml/` that is not plain text, any picture, video, sound, array, weights, table, archive or database under `ml/` or `demo-call/`, any file in a `footage`, `datasets`, `mlruns` or `mlflow` folder, and any oversized text file.
7. **Reproducible to the byte.** The synthetic data is generated from a fixed seed with NumPy's specified generator and written as plain `.npy` files (no timestamps). The model's distances are whole-number arithmetic, probabilities are rounded to 12 places, and reported floats are rounded, so different machines agree. `ml/.gitattributes` forces plain line endings so Windows and Linux checkouts hash the same.
8. **Test split discipline.** Training uses the training split; the softness of the probability is chosen on the validation split; the test split is used once, in evaluation. A test proves that altering the test pictures and labels cannot change the trained model.
9. **Pinned tools.** `requirements.txt` has exact versions, each at least 14 days old (DVC 3.67.1, MLflow 3.17.2, NumPy 2.5.4, pytest 9.1.1, PyYAML 6.0.3); `constraints.txt` pins everything they pull in (made with Python 3.12 on Linux).
10. **A one-command proof.** `ml/scripts/clean_checkout_repro.py` clones the committed state into a temporary folder, builds a new environment, runs `dvc repro --force` (every stage, none skipped as unchanged) and fails unless `dvc.lock`, the metrics and the model card come out unchanged. CI does the same on every pull request (`.github/workflows/ml.yml`).

## Verification

- 58 unit tests: the synthetic data (determinism to the byte, a changed pixel changes the fingerprint, splits, noise grows with the group), the metrics (hand-worked values, ties, calibration, intervals), the baseline (integer arithmetic against the plain formula, no leakage from the test split, repeatable), the model card (every rule above), the guard (allowed and refused files), the tracking record, and the workspace's own configuration (every dependency exists, parameters exist, pins are exact).
- Reproduced from a clean clone in a brand-new Python environment on Linux, with every stage forced: unchanged `dvc.lock`, metrics and model card.
- The reproduction check was shown to fail when a committed metric is edited by hand and when a setting changes.

## Not verified, and known limits

- **Not run on Windows or macOS by me.** The pins were made on Linux with Python 3.12. The design avoids the usual causes of difference, but this must be confirmed on the founder's machine.
- The baseline is a toy on synthetic data. It says nothing about real accuracy, and its card says so.
- No DVC remote, no real data, no real model, no GPU training, no fairness evaluation on real subgroups (P0-39). The model card template has the fields for them.
- MLflow records are local; there is no shared experiment history yet.
- If the v1 documents name other tools, the stages are isolated enough to swap them (the cost is the tracking module and the pipeline file).

## Related

P0-31 (data plan and licence check), P0-32 and P0-33 (benchmarks), P0-34 and P0-35 (real models), P0-39 (fairness), P0-40 (promotion gate), D-06 (cloud), D-07 (model sourcing and data licences), guide Part 3 (never claim unsubstantiated accuracy) and Part 11.2 (claims register).
