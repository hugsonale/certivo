# Experiment records

Runs are recorded by MLflow under `ml/mlflow/`, which is **never committed**. This folder is for the written conclusions that ARE committed.

## Naming

- One MLflow *experiment* per model family, named like its model: `baseline-synthetic-v0`.
- A run is named `<model>-<short git commit>`, and is tagged with the full commit, whether the working copy was changed, the data fingerprint, and the tool versions.
- A run whose `git.dirty` tag is `true` cannot be reproduced and must not be quoted.

## Comparing

Open the MLflow screen (`mlflow ui --backend-store-uri sqlite:///mlflow/mlflow.db`), tick the runs, and press Compare. Every run lists its settings, so a difference in result can be traced to a difference in settings.

## Writing a conclusion

Add a short markdown file here per finding: what was asked, which runs answer it (commit and data fingerprint), what the numbers are WITH their intervals, and what is still uncertain. A finding with no run behind it is not written down.
